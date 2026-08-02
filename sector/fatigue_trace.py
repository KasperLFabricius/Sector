"""Build and validate CT-010a reinforcement-fatigue evidence."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .calculation_trace import (
    RESULT_FAILED,
    RESULT_FINITE,
    RESULT_NEGATIVE_INFINITY,
    RESULT_POSITIVE_INFINITY,
    RESULT_UNDEFINED,
    SOURCE_PROJECT,
    TraceBundle,
    TraceCalculation,
    TraceDependency,
    TraceResult,
    TraceSource,
    TraceStep,
    TraceValidationError,
    create_bundle,
    trace_identity_token,
    validate_bundle,
)
from .fatigue import DAMAGE_LIMIT
from .fatigue_trace_contract import (
    COVERAGE_ID,
    EDITIONS,
    METHOD_ID,
    STATUS_CODES,
    VALID_KEYS,
    ElementShape,
    FamilyShape,
    InputBlocks,
    InvalidShape,
    OutputShape,
    SpectrumShape,
    bin_prefix,
    description_step_id,
    element_steps,
    expected_registry,
    invalid_error_id,
    invalid_steps,
    material_step_id,
    output_element_prefix,
    output_steps,
    spectrum_prefix,
)
from .fatigue_trace_reader import (
    app_modules,
    ordered_sequence,
    replay_input,
    retained_flag,
    validate_candidate,
    validate_fatigue_detail_catalog,
    validate_present_material_catalog,
)
from .materials import MildSteel, Prestress
from .section_trace_blocks import (
    GeometryBlock,
    MaterialBlock,
    ProvenanceBlock,
    _concrete_block,
    _law_values,
    _materials,
    context_axes,
    context_id,
)
from .torsion_trace import _mapping
from .trace_registry import audit_trace_registry


_DRIFT = "authoritative CT-010 retained inventory drifted"
_ASSUMPTIONS = (
    "Retained reinforcement fatigue replay; concrete-fatigue values belong "
    "to the named PR-08D.3b sibling.",
)
_INFINITE_REASON = (
    "The retained fatigue quantity is unbounded and is represented without "
    "a fabricated finite replacement."
)
_UNDEFINED_REASON = (
    "The retained fatigue quantity is undefined and is represented without "
    "a fabricated finite replacement."
)
_LOG10_MAX = math.log10(float.fromhex("0x1.fffffffffffffp+1023"))
_LOG10_MIN = math.log10(math.ulp(0.0))
_BIN_ACTION_COLUMNS = (
    ("n-long", "n_long_ed_kn"),
    ("mx-long", "mx_long_ed_knm"),
    ("my-long", "my_long_ed_knm"),
    ("n-short", "n_short_ed_kn"),
    ("mx-short", "mx_short_ed_knm"),
    ("my-short", "my_short_ed_knm"),
)


@dataclass(frozen=True, slots=True)
class _ElementSummary:
    element_id: str
    utilisation: float
    converged: bool
    passed: bool


def _catalog_free_blocks(inp, kind, count):
    law_key = "bar_materials" if kind == "bar" else "tendon_materials"
    element_key = "bar_elements" if kind == "bar" else "tendon_elements"
    expected_type = MildSteel if kind == "bar" else Prestress
    laws = ordered_sequence(inp.get(law_key), law_key)
    records = ordered_sequence(inp.get(element_key), element_key)
    if len(laws) != count or len(records) != count:
        raise TraceValidationError(
            f"catalog-free {kind} laws and assignments must align")
    blocks = []
    seen = set()
    for index, (law, raw_record) in enumerate(zip(laws, records)):
        if type(law) is not expected_type:
            raise TraceValidationError(
                f"catalog-free {kind} law {index} has the wrong type")
        record = _mapping(raw_record, f"{element_key}[{index}]")
        element_id = record.get("id")
        material_id = record.get("material_id")
        for label, value in (
            ("element ID", element_id), ("material ID", material_id)
        ):
            if type(value) is not str or not value or value != value.strip():
                raise TraceValidationError(
                    f"catalog-free {kind} {label} must be non-blank text")
        if element_id in seen:
            raise TraceValidationError(
                f"duplicate catalog-free {kind} element ID {element_id}")
        seen.add(element_id)
        blocks.append(MaterialBlock(
            kind=kind,
            element_id=element_id,
            material_id=material_id,
            values=_law_values(law),
            provenance=ProvenanceBlock(
                TraceSource(SOURCE_PROJECT, f"project-{kind}-law"), None),
        ))
    return tuple(blocks)


def _reinforcement_blocks(inp, geometry, kind):
    _analysis, _inputs, material_catalog = app_modules()
    material_kind = "mild" if kind == "bar" else "prestress"
    catalog_present = validate_present_material_catalog(
        inp, material_kind, material_catalog)
    elements = geometry.bars if kind == "bar" else geometry.tendons
    law_key = "bar_materials" if kind == "bar" else "tendon_materials"
    if inp.get(law_key) is not None and not catalog_present:
        return _catalog_free_blocks(inp, kind, len(elements))
    return _materials(
        inp,
        kind=kind,
        count=len(elements),
        default=inp.get("steel") if kind == "bar" else inp.get("prestress"),
    )


def _input_blocks(inp):
    geometry = GeometryBlock.from_section(inp["section"])
    concrete = None if inp.get("concrete") is None else _concrete_block(inp)
    return InputBlocks(
        geometry=geometry,
        concrete=concrete,
        bars=_reinforcement_blocks(inp, geometry, "bar"),
        tendons=_reinforcement_blocks(inp, geometry, "tendon"),
    )


def _reject_unimplemented_materials(blocks):
    materials = (
        (() if blocks.concrete is None else (blocks.concrete,))
        + blocks.bars
        + blocks.tendons
    )
    for material in materials:
        citation = material.provenance.source.citation
        if citation is not None and "2023" in citation.document:
            raise TraceValidationError(
                "2023 material provenance is published but not implemented "
                "for CT-010")


def _trace_result(value):
    if math.isnan(value):
        return TraceResult(RESULT_UNDEFINED, None, _UNDEFINED_REASON)
    if math.isinf(value):
        state = (
            RESULT_POSITIVE_INFINITY if value > 0.0
            else RESULT_NEGATIVE_INFINITY)
        return TraceResult(state, None, _INFINITE_REASON)
    return TraceResult(RESULT_FINITE, value)


def _close(actual, expected):
    if actual == expected or math.isnan(actual) and math.isnan(expected):
        return True
    return (
        math.isfinite(actual)
        and math.isfinite(expected)
        and math.isclose(actual, expected, rel_tol=1.0e-12, abs_tol=1.0e-12)
    )


def _assert_number(actual, expected, label):
    if type(actual) not in {int, float} or type(actual) is bool:
        raise TraceValidationError(f"{label} has the wrong numerical type")
    if not _close(float(actual), float(expected)):
        raise TraceValidationError(f"{label} contradicts its declared operands")


def _assert_bool(actual, expected, label):
    if type(actual) is not bool or actual is not expected:
        raise TraceValidationError(f"{label} contradicts its declared operands")


def _assert_text(actual, expected, label):
    if type(actual) is not str or actual != expected:
        raise TraceValidationError(f"{label} contradicts its declared operands")


def _pow10(log10_value):
    if math.isinf(log10_value):
        return math.inf if log10_value > 0.0 else 0.0
    if log10_value > _LOG10_MAX:
        return math.inf
    if log10_value < _LOG10_MIN:
        return 0.0
    return 10.0 ** log10_value


def _damage_from_log(cycles, log10_life):
    """Reconstruct Miner damage without first materialising underflowed life."""

    if type(cycles) not in {int, float} or type(cycles) is bool:
        raise TraceValidationError("fatigue cycles must be numerical")
    cycles = float(cycles)
    if not math.isfinite(cycles) or cycles <= 0.0:
        raise TraceValidationError("fatigue cycles must be finite and positive")
    if math.isinf(log10_life):
        return 0.0 if log10_life > 0.0 else math.inf
    return _pow10(math.log10(cycles) - log10_life)


def _sn_life(stress_range, properties, gamma_s):
    if stress_range == 0.0:
        return math.inf, math.inf, 0.0
    reference = float(properties.delta_sigma_rsk_mpa)
    knee = reference / gamma_s
    exponent = properties.k1 if stress_range >= knee else properties.k2
    log10_life = (
        math.log10(float(properties.n_star))
        + float(exponent)
        * math.log10(reference / (gamma_s * stress_range))
    )
    return _pow10(log10_life), log10_life, float(exponent)


def _proof(stress, properties, gamma_s):
    strength = properties.fytk_mpa
    if stress < 0.0 and properties.fyck_mpa is not None:
        strength = properties.fyck_mpa
    limit = float(strength) / gamma_s
    return limit, abs(stress) / limit


def _expression(step_id, final):
    fixed = {
        "normalised-fatigue-inputs": "Complete validated fatigue input identity",
        "geometry-vector": "Bind every retained section coordinate and area",
        "material-vector": "Bind every assigned material identity and law",
        "damage-total": "D = sum n_i/N_i over all retained bins",
        "governing-damage-bin": "governing = argmax bin damage",
        "yield-utilisation": "yield utilisation = max over retained bins",
        "governing-yield-bin": "governing = argmax bin yield utilisation",
        "utilisation": "utilisation = max(D, yield utilisation)",
        "converged": "converged = all retained raw bin solves converged",
        "governing-spectrum": "governing = argmax spectrum utilisation",
        "family-utilisation": "utilisation = governing spectrum utilisation",
    }
    if step_id in fixed:
        return fixed[step_id]
    if step_id.endswith("-damage"):
        return "D_i = 10^(log10(n_i) - log10(N_i))"
    if step_id.endswith("-yield-utilisation"):
        return "yield utilisation = abs(governing stress) / proof limit"
    if final:
        return "PASS = 1 when convergence and retained limits pass, else 0"
    return f"Bind {step_id}"


def _calculation(calculation_id, title, axes, specs, values, failed_reason=None):
    units = {spec.step_id: spec.unit for spec in specs}
    steps = []
    for spec in specs:
        if spec.step_id not in values:
            raise TraceValidationError(
                f"internal CT-010 value omitted {spec.step_id}")
        final = spec.role == "final_result"
        if final and failed_reason is not None:
            result = TraceResult(RESULT_FAILED, None, failed_reason)
            substituted = f"{spec.step_id} = failed"
        else:
            numeric = float(values[spec.step_id])
            result = _trace_result(numeric)
            substituted = (
                f"{spec.step_id} = {numeric:.17g} {spec.unit.symbol}"
                if result.state == RESULT_FINITE
                else f"{spec.step_id} = {result.state}"
            )
        steps.append(TraceStep(
            step_id=spec.step_id,
            title=spec.title,
            dependencies=tuple(
                TraceDependency(dependency, units[dependency])
                for dependency in spec.dependencies),
            quantity_role=spec.role,
            source=spec.source,
            symbol=spec.step_id,
            unit=spec.unit,
            actual_expression=_expression(spec.step_id, final),
            substituted_expression=substituted,
            result=result,
        ))
    return TraceCalculation(
        calculation_id=calculation_id,
        coverage_id=COVERAGE_ID,
        title=title,
        method_id=METHOD_ID,
        axes=axes,
        final_step_id=specs[-1].step_id,
        steps=tuple(steps),
        assumptions=_ASSUMPTIONS,
    )


def _element_shape(
    context, blocks, spectrum_index, spectrum_name, element_index,
    properties, material_id, rows, edition, joint,
):
    names = tuple(row["name"] for row in rows)
    descriptions = tuple(row["description"] for row in rows)
    if any(type(value) is not str for value in (*names, *descriptions)):
        raise TraceValidationError(_DRIFT)
    mixed = bool(blocks.geometry.bars) and bool(blocks.geometry.tendons)
    calculation_id = (
        f"ct-010-{context_id(context)}-s{spectrum_index:02d}-"
        f"{trace_identity_token(spectrum_name)}-e{element_index:02d}-"
        f"{trace_identity_token(properties.element_id)}-"
        f"{trace_identity_token(material_id)}-"
        f"{trace_identity_token(properties.detail_id)}"
    )
    return ElementShape(
        spectrum_index=spectrum_index,
        spectrum_name=spectrum_name,
        element_index=element_index,
        element_id=properties.element_id,
        material_id=material_id,
        detail_id=properties.detail_id,
        bin_names=names,
        bin_descriptions=descriptions,
        blocks=blocks,
        has_fyck=properties.fyck_mpa is not None,
        has_bond_xi=properties.bond_ratio_xi is not None,
        has_bond_diameter=properties.bond_equivalent_diameter_mm is not None,
        mixed=mixed,
        joint=joint,
        edition=edition,
        calculation_id=calculation_id,
        axes=context_axes(
            context,
            member="reinforcement",
            spectrum_index=str(spectrum_index),
            element_index=str(element_index),
            bin_count=str(len(names)),
            fatigue_edition=edition,
            mixed=str(mixed).lower(),
            joint=str(joint).lower(),
        ),
    )


def _identity_values(shape):
    values = {
        "input-concrete-material-present": (
            0.0 if shape.blocks.concrete is None else 1.0)
    }
    for ring_index, ring in enumerate(shape.blocks.geometry.rings):
        for point_index, (x, y) in enumerate(ring):
            prefix = f"geometry-ring-{ring_index:03d}-point-{point_index:04d}"
            values[f"{prefix}-x"] = x
            values[f"{prefix}-y"] = y
    for kind, elements in (
        ("bar", shape.blocks.geometry.bars),
        ("tendon", shape.blocks.geometry.tendons),
    ):
        for index, element in enumerate(elements):
            prefix = f"geometry-{kind}-{index:04d}"
            values[f"{prefix}-x"] = element.x
            values[f"{prefix}-y"] = element.y
            values[f"{prefix}-area"] = element.area
    values["geometry-vector"] = 1.0
    materials = (
        (() if shape.blocks.concrete is None else (shape.blocks.concrete,))
        + shape.blocks.bars
        + shape.blocks.tendons
    )
    for material in materials:
        for field, value in material.values:
            values[material_step_id(material, field)] = value
    values["material-vector"] = 1.0
    return values


def _raw_state_vectors(state, count, gamma_ff):
    if state.elastic_result is None or state.design_elastic_result is None:
        raise TraceValidationError("fatigue state omitted retained Elastic results")
    raw = state.elastic_result
    design = state.design_elastic_result
    long = tuple(float(value) / 1000.0 for value in raw.bar_stress_long)
    total = tuple(float(value) / 1000.0 for value in raw.bar_stress_total)
    design_total = tuple(
        float(value) / 1000.0 for value in design.bar_stress_total)
    if len(long) != count or len(total) != count or len(design_total) != count:
        raise TraceValidationError("retained Elastic bar vectors drifted")
    for actual, expected, label in (
        (state.bar_stress_long_mpa, long, "long stress vector"),
        (state.bar_stress_total_mpa, total, "total stress vector"),
        (state.bar_stress_design_total_mpa, design_total, "design stress vector"),
    ):
        if len(actual) != len(expected):
            raise TraceValidationError(f"{label} cardinality contradicts solver")
        for index, (got, wanted) in enumerate(zip(actual, expected)):
            _assert_number(got, wanted, f"{label}[{index}]")
    expected_converged = bool(raw.converged and design.converged)
    _assert_bool(state.converged, expected_converged, "bin convergence")
    _assert_number(
        state.design_action_factor, gamma_ff, "design action factor")


def _element_values(
    shape, rows, states, prepared, retained_result, properties,
    elastic_modulus,
):
    if retained_result.element_id != properties.element_id:
        raise TraceValidationError(_DRIFT)
    if not (
        len(rows) == len(states) == len(retained_result.bins)
        == len(shape.bin_names)
    ):
        raise TraceValidationError(_DRIFT)
    gamma_s = float(prepared.gamma_s)
    values = {
        "input-check-steel": 1.0,
        "input-edition": float(EDITIONS.index(shape.edition)),
        "input-gamma-s": gamma_s,
        "input-gamma-ff": prepared.gamma_ff,
        "input-nl": prepared.nl,
        "input-ns": prepared.ns,
        "input-diameter": properties.diameter_mm,
        "detail-n-star": properties.n_star,
        "detail-k1": properties.k1,
        "detail-k2": properties.k2,
        "detail-delta-sigma-rsk": properties.delta_sigma_rsk_mpa,
        "detail-fytk": properties.fytk_mpa,
        "element-es": elastic_modulus,
        "normalised-fatigue-inputs": 1.0,
    }
    if shape.joint:
        values["input-gamma-c"] = prepared.gamma_c
    values.update(_identity_values(shape))
    if shape.has_fyck:
        values["detail-fyck"] = properties.fyck_mpa
    if shape.has_bond_xi:
        values["detail-bond-xi"] = properties.bond_ratio_xi
    if shape.has_bond_diameter:
        values["detail-bond-eq-diameter"] = (
            properties.bond_equivalent_diameter_mm)

    damages, yield_uses, convergence = [], [], []
    count = len(prepared.reinforcement)
    element_index = shape.element_index
    for index, (name, description, row, state, retained) in enumerate(zip(
        shape.bin_names,
        shape.bin_descriptions,
        rows,
        states,
        retained_result.bins,
    )):
        _raw_state_vectors(state, count, prepared.gamma_ff)
        _assert_text(state.name, name, f"{name} raw bin name")
        _assert_text(state.description, description, f"{name} description")
        _assert_number(state.cycles, row["cycles"], f"{name} raw cycles")
        _assert_text(retained.bin_name, name, f"{name} result bin name")
        _assert_number(retained.cycles, state.cycles, f"{name} result cycles")
        _assert_bool(
            retained.converged, state.converged, f"{name} convergence")

        long = float(state.bar_stress_long_mpa[element_index])
        elastic_total = float(state.bar_stress_total_mpa[element_index])
        corrected = (
            state.bar_stress_fatigue_total_mpa
            or state.bar_stress_total_mpa)
        corrected_design = (
            state.bar_stress_fatigue_design_total_mpa or corrected)
        total = float(corrected[element_index])
        design_total = float(corrected_design[element_index])
        stress_range = abs(total - long)
        elastic_range = abs(elastic_total - long)
        design_range = abs(design_total - long)
        bond = (
            stress_range / elastic_range
            if elastic_range > 0.0
            else math.inf if stress_range > 0.0 else 1.0)
        cycles_to_failure, log10_life, exponent = _sn_life(
            design_range, properties, gamma_s)
        damage = _damage_from_log(state.cycles, log10_life)
        long_limit, long_use = _proof(long, properties, gamma_s)
        total_limit, total_use = _proof(design_total, properties, gamma_s)
        if total_use >= long_use:
            governing_stress = design_total
            proof_limit, yield_use = total_limit, total_use
        else:
            governing_stress = long
            proof_limit, yield_use = long_limit, long_use

        comparisons = (
            (retained.stress_long_mpa, long, "long stress"),
            (retained.stress_total_mpa, total, "total stress"),
            (retained.stress_total_design_mpa, design_total, "design stress"),
            (retained.stress_total_elastic_mpa, elastic_total, "elastic stress"),
            (retained.stress_range_mpa, stress_range, "stress range"),
            (retained.stress_range_elastic_mpa, elastic_range, "elastic range"),
            (retained.bond_adjustment, bond, "bond adjustment"),
            (retained.design_stress_range_mpa, design_range, "design range"),
            (retained.delta_sigma_rsk_mpa,
             properties.delta_sigma_rsk_mpa, "characteristic resistance"),
            (retained.delta_sigma_rd_mpa,
             properties.delta_sigma_rsk_mpa / gamma_s, "design resistance"),
            (retained.sn_exponent, exponent, "S-N exponent"),
            (retained.cycles_to_failure, cycles_to_failure, "cycles to failure"),
            (retained.log10_cycles_to_failure, log10_life, "log10 life"),
            (retained.damage, damage, "damage"),
            (retained.governing_stress_mpa,
             governing_stress, "governing stress"),
            (retained.yield_limit_mpa, proof_limit, "yield limit"),
            (retained.yield_utilisation, yield_use, "yield utilisation"),
        )
        for actual, expected, label in comparisons:
            _assert_number(actual, expected, f"{name} {label}")
        _assert_text(
            retained.bond_method, state.bond_method, f"{name} bond method")

        damages.append(damage)
        yield_uses.append(yield_use)
        convergence.append(state.converged)
        prefix = bin_prefix(index, name)
        values[description_step_id(index, name, description)] = 1.0
        values[f"{prefix}-cycles"] = row["cycles"]
        for suffix, column in _BIN_ACTION_COLUMNS:
            values[f"{prefix}-{suffix}"] = row[column]
        values.update({
            f"{prefix}-upstream-converged": float(state.converged),
            f"{prefix}-upstream-stress-long": long,
            f"{prefix}-upstream-stress-total": total,
            f"{prefix}-upstream-stress-total-elastic": elastic_total,
            f"{prefix}-upstream-stress-total-design": design_total,
            f"{prefix}-stress-range": stress_range,
            f"{prefix}-bond-adjustment": bond,
            f"{prefix}-design-stress-range": design_range,
            f"{prefix}-sn-exponent": exponent,
            f"{prefix}-log10-cycles-to-failure": log10_life,
            f"{prefix}-damage": damage,
            f"{prefix}-yield-limit": proof_limit,
            f"{prefix}-yield-utilisation": yield_use,
        })

    damage_total = sum(damages)
    damage_index = max(range(len(damages)), key=damages.__getitem__)
    yield_index = max(range(len(yield_uses)), key=yield_uses.__getitem__)
    yield_use = yield_uses[yield_index]
    utilisation = max(damage_total, yield_use)
    converged = all(convergence)
    passed = converged and damage_total <= DAMAGE_LIMIT and yield_use <= 1.0
    aggregate = (
        (retained_result.damage, damage_total, "element damage"),
        (retained_result.damage_utilisation,
         damage_total, "damage utilisation"),
        (retained_result.yield_utilisation,
         yield_use, "element yield utilisation"),
        (retained_result.utilisation, utilisation, "element utilisation"),
    )
    for actual, expected, label in aggregate:
        _assert_number(actual, expected, label)
    _assert_text(
        retained_result.governing_damage_bin,
        shape.bin_names[damage_index],
        "governing damage bin",
    )
    _assert_text(
        retained_result.governing_yield_bin,
        shape.bin_names[yield_index],
        "governing yield bin",
    )
    _assert_bool(retained_result.converged, converged, "element convergence")
    _assert_bool(retained_result.passed, passed, "element status")
    status = STATUS_CODES["PASS" if passed else "FAIL"]
    values.update({
        "damage-total": damage_total,
        "governing-damage-bin": float(damage_index),
        "yield-utilisation": yield_use,
        "governing-yield-bin": float(yield_index),
        "utilisation": utilisation,
        "converged": float(converged),
        "passed": status,
        "ct-010-element-result": status,
    })
    return values, _ElementSummary(
        properties.element_id, utilisation, converged, passed)


def _output_evidence(payload, spectrum_names, summaries, context, gamma_c):
    spectra = tuple(payload["spectra"])
    if len(spectra) != len(spectrum_names) or len(summaries) != len(spectra):
        raise TraceValidationError(_DRIFT)
    joint = payload["checks"]["concrete"]
    if type(joint) is not bool:
        raise TraceValidationError(_DRIFT)
    shapes = []
    values = {
        "input-check-steel": 1.0,
        "input-check-concrete": float(joint),
    }
    if joint:
        values["input-gamma-c"] = gamma_c
    all_convergence, all_passed = [], []
    for si, (name, spectrum, derived) in enumerate(zip(
        spectrum_names, spectra, summaries
    )):
        if spectrum.spectrum_name != name:
            raise TraceValidationError(_DRIFT)
        ids = tuple(item.element_id for item in derived)
        if not ids or len(spectrum.reinforcement) != len(derived):
            raise TraceValidationError(_DRIFT)
        shapes.append(SpectrumShape(name, ids))
        uses = []
        for ei, (retained, item) in enumerate(zip(
            spectrum.reinforcement, derived
        )):
            _assert_text(retained.element_id, item.element_id, "output element")
            _assert_number(
                retained.utilisation, item.utilisation,
                f"{name} {item.element_id} utilisation")
            _assert_bool(
                retained.converged, item.converged,
                f"{name} {item.element_id} convergence")
            _assert_bool(
                retained.passed, item.passed,
                f"{name} {item.element_id} status")
            prefix = output_element_prefix(si, name, ei, item.element_id)
            values[f"{prefix}-utilisation"] = item.utilisation
            values[f"{prefix}-converged"] = float(item.converged)
            values[f"{prefix}-passed"] = float(item.passed)
            uses.append(item.utilisation)
            all_convergence.append(item.converged)
            all_passed.append(item.passed)
        governing = max(range(len(uses)), key=uses.__getitem__)
        _assert_text(
            spectrum.governing_reinforcement_id,
            ids[governing],
            f"{name} governing reinforcement",
        )
        prefix = spectrum_prefix(si, name)
        values[f"{prefix}-governing-element"] = float(governing)
        if not joint:
            spectrum_use = uses[governing]
            _assert_number(
                spectrum.utilisation, spectrum_use,
                f"{name} reinforcement utilisation")
            values[f"{prefix}-utilisation"] = spectrum_use

    converged = all(all_convergence)
    passed = all(all_passed)
    status = STATUS_CODES["PASS" if passed else "FAIL"]
    values["reinforcement-converged"] = float(converged)
    values["reinforcement-passed"] = status
    if not joint:
        spectrum_uses = tuple(
            max(item.utilisation for item in group) for group in summaries)
        governing = max(
            range(len(spectrum_uses)), key=spectrum_uses.__getitem__)
        _assert_text(
            payload["governing_spectrum"], spectrum_names[governing],
            "family governing spectrum")
        _assert_number(
            payload["utilisation"], spectrum_uses[governing],
            "family reinforcement utilisation")
        _assert_bool(payload["converged"], converged, "family convergence")
        _assert_bool(payload["passed"], passed, "family status")
        values["governing-spectrum"] = float(governing)
        values["family-utilisation"] = spectrum_uses[governing]
    values["ct-010-reinforcement-output-result"] = status
    shape = OutputShape(
        joint=joint,
        spectra=tuple(shapes),
        calculation_id=f"ct-010-{context_id(context)}-reinforcement-output",
        axes=context_axes(
            context,
            member="reinforcement-output",
            joint=str(joint).lower(),
            spectrum_count=str(len(shapes)),
        ),
    )
    return shape, values


def _invalid_bundle(inp, replay, input_sha256, result_sha256, context):
    errors = tuple(replay.payload["errors"])
    shape = InvalidShape(
        errors=errors,
        calculation_id=f"ct-010-{context_id(context)}-invalid",
        axes=context_axes(
            context, member="invalid", error_count=str(len(errors))),
    )
    values = {
        "input-fatigue-on": 1.0,
        "input-check-steel": float(retained_flag(inp, "fatigue_check_steel")),
        "input-check-concrete": float(
            retained_flag(inp, "fatigue_check_concrete")),
    }
    for index, message in enumerate(errors):
        values[invalid_error_id(index, message)] = 1.0
    values["ct-010-invalid-result"] = 0.0
    calculation = _calculation(
        shape.calculation_id,
        "Fatigue invalid input state",
        shape.axes,
        invalid_steps(shape),
        values,
        failed_reason="Retained fatigue preflight failed: " + "; ".join(errors),
    )
    bundle = create_bundle(
        input_sha256=input_sha256,
        result_sha256=result_sha256,
        calculations=(calculation,),
    )
    audit_trace_registry(bundle, expected_registry(FamilyShape((), None, shape)))
    return bundle


def _finite_bundle(inp, replay, input_sha256, result_sha256, context):
    payload = replay.payload
    if tuple(payload) != VALID_KEYS:
        raise TraceValidationError(_DRIFT)
    if not payload["checks"]["reinforcement"]:
        return None
    _analysis, fatigue_inputs, _material_catalog = app_modules()
    validate_fatigue_detail_catalog(inp, fatigue_inputs)
    prepared = replay.prepared
    blocks = _input_blocks(inp)
    _reject_unimplemented_materials(blocks)
    assigned = (*blocks.bars, *blocks.tendons)
    if tuple(item.element_id for item in assigned) != tuple(
        prepared.solver_element_ids
    ):
        raise TraceValidationError("fatigue element identity must align")
    edition = payload["edition"]
    if edition not in EDITIONS:
        raise TraceValidationError(_DRIFT)
    joint = payload["checks"]["concrete"]
    if type(joint) is not bool:
        raise TraceValidationError(_DRIFT)
    if joint and prepared.gamma_c is None:
        raise TraceValidationError("joint fatigue input omitted gamma_c")
    spectrum_names = tuple(replay.groups)
    spectra = tuple(payload["spectra"])
    if len(spectrum_names) != len(spectra):
        raise TraceValidationError(_DRIFT)

    shapes, calculations, output_summaries = [], [], []
    for si, (name, spectrum) in enumerate(zip(spectrum_names, spectra)):
        if spectrum.spectrum_name != name:
            raise TraceValidationError(_DRIFT)
        rows = tuple(replay.groups[name])
        states = tuple(spectrum.bins)
        if len(spectrum.reinforcement) != len(prepared.reinforcement):
            raise TraceValidationError(_DRIFT)
        spectrum_summaries = []
        for ei, properties in enumerate(prepared.reinforcement):
            material = assigned[ei]
            shape = _element_shape(
                context, blocks, si, name, ei, properties,
                material.material_id, rows, edition, joint)
            values, summary = _element_values(
                shape, rows, states, prepared,
                spectrum.reinforcement[ei], properties,
                dict(material.values)["Es"])
            shapes.append(shape)
            spectrum_summaries.append(summary)
            calculations.append(_calculation(
                shape.calculation_id,
                f"Reinforcement fatigue {name} / {properties.element_id}",
                shape.axes,
                element_steps(shape),
                values,
            ))
        output_summaries.append(tuple(spectrum_summaries))

    output_shape, output_values = _output_evidence(
        payload,
        spectrum_names,
        tuple(output_summaries),
        context,
        prepared.gamma_c,
    )
    calculations.append(_calculation(
        output_shape.calculation_id,
        "Reinforcement fatigue output selection",
        output_shape.axes,
        output_steps(output_shape),
        output_values,
    ))
    bundle = create_bundle(
        input_sha256=input_sha256,
        result_sha256=result_sha256,
        calculations=tuple(calculations),
    )
    family_shape = FamilyShape(tuple(shapes), output_shape, None)
    audit_trace_registry(bundle, expected_registry(family_shape))
    return bundle


def _expected_bundle(inp, out, input_sha256, result_sha256, context):
    replay = replay_input(inp)
    retained_out = _mapping(out, "retained result mapping")
    present = "fatigue" in retained_out
    candidate = retained_out.get("fatigue")
    if not replay.active:
        if present:
            raise TraceValidationError(
                "inactive CT-010 input cannot carry a fatigue surface")
        return None
    if not present or candidate is None:
        raise TraceValidationError(
            "active CT-010 input must publish the fatigue surface")
    validate_candidate(candidate, replay)
    if replay.branch == "invalid":
        return _invalid_bundle(
            inp, replay, input_sha256, result_sha256, context)
    return _finite_bundle(
        inp, replay, input_sha256, result_sha256, context)


def build_fatigue_trace_family(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle | None:
    """Build exact retained CT-010a evidence or its legitimate absence."""

    try:
        return _expected_bundle(
            inp,
            out,
            input_sha256,
            result_sha256,
            {} if context is None else context,
        )
    except TraceValidationError:
        raise
    except (
        ArithmeticError, AttributeError, KeyError, TypeError, ValueError
    ) as exc:
        raise TraceValidationError(
            f"invalid CT-010 fatigue evidence: {exc}") from exc


def validate_fatigue_trace_family(
    bundle: TraceBundle | dict[str, Any] | None,
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle | None:
    """Reject stale, resealed, source, graph, unit, and identity tampering."""

    expected = build_fatigue_trace_family(
        inp,
        out,
        input_sha256=input_sha256,
        result_sha256=result_sha256,
        context=context,
    )
    if expected is None:
        if bundle is not None:
            raise TraceValidationError(
                "inapplicable CT-010 input cannot carry a trace bundle")
        return None
    if bundle is None:
        raise TraceValidationError(
            "applicable CT-010 input requires a trace bundle")
    model = validate_bundle(
        bundle,
        expected_input_sha256=input_sha256,
        expected_result_sha256=result_sha256,
    )
    if model != expected:
        raise TraceValidationError(
            "CT-010 trace differs from authoritative exact reconstruction")
    return model


__all__ = ["build_fatigue_trace_family", "validate_fatigue_trace_family"]
