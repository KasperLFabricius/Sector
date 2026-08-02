"""Build and validate the CT-010a reinforcement-fatigue trace family."""

from __future__ import annotations

import math
from collections.abc import Mapping
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
from .fatigue import DAMAGE_LIMIT, steel_fatigue_life
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
    ReplayState,
    app_modules,
    ordered_sequence,
    replay_input,
    retained_flag,
    validate_candidate,
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
_BIN_ACTION_COLUMNS = (
    ("n-long", "n_long_ed_kn"),
    ("mx-long", "mx_long_ed_knm"),
    ("my-long", "my_long_ed_knm"),
    ("n-short", "n_short_ed_kn"),
    ("mx-short", "mx_short_ed_knm"),
    ("my-short", "my_short_ed_knm"),
)


def _catalog_free_materials(
    inp: Mapping[str, Any], kind: str, count: int
) -> tuple[MaterialBlock, ...]:
    law_key = "bar_materials" if kind == "bar" else "tendon_materials"
    element_key = "bar_elements" if kind == "bar" else "tendon_elements"
    expected_type = MildSteel if kind == "bar" else Prestress
    laws = ordered_sequence(inp.get(law_key), law_key)
    records = ordered_sequence(inp.get(element_key), element_key)
    if len(laws) != count or len(records) != count:
        raise TraceValidationError(
            f"catalog-free {kind} laws and assignments must align"
        )
    result = []
    seen = set()
    for index, (law, raw_record) in enumerate(zip(laws, records)):
        if type(law) is not expected_type:
            raise TraceValidationError(
                f"catalog-free {kind} law {index} has the wrong type"
            )
        record = _mapping(raw_record, f"{element_key}[{index}]")
        element_id = record.get("id")
        material_id = record.get("material_id")
        for label, value in (
            ("element ID", element_id),
            ("material ID", material_id),
        ):
            if type(value) is not str or not value or value != value.strip():
                raise TraceValidationError(
                    f"catalog-free {kind} {label} must be non-blank text"
                )
        if element_id in seen:
            raise TraceValidationError(
                f"duplicate catalog-free {kind} element ID {element_id}"
            )
        seen.add(element_id)
        result.append(
            MaterialBlock(
                kind=kind,
                element_id=element_id,
                material_id=material_id,
                values=_law_values(law),
                provenance=ProvenanceBlock(
                    TraceSource(SOURCE_PROJECT, f"project-{kind}-law"),
                    None,
                ),
            )
        )
    return tuple(result)


def _reinforcement_blocks(
    inp: Mapping[str, Any], geometry: GeometryBlock, kind: str
) -> tuple[MaterialBlock, ...]:
    _analysis, _inputs, material_catalog = app_modules()
    material_kind = "mild" if kind == "bar" else "prestress"
    catalog_present = validate_present_material_catalog(
        inp, material_kind, material_catalog
    )
    elements = geometry.bars if kind == "bar" else geometry.tendons
    law_key = "bar_materials" if kind == "bar" else "tendon_materials"
    if inp.get(law_key) is not None and not catalog_present:
        return _catalog_free_materials(inp, kind, len(elements))
    return _materials(
        inp,
        kind=kind,
        count=len(elements),
        default=inp.get("steel") if kind == "bar" else inp.get("prestress"),
    )


def _input_blocks(inp: Mapping[str, Any]) -> InputBlocks:
    geometry = GeometryBlock.from_section(inp["section"])
    concrete = None if inp.get("concrete") is None else _concrete_block(inp)
    return InputBlocks(
        geometry=geometry,
        concrete=concrete,
        bars=_reinforcement_blocks(inp, geometry, "bar"),
        tendons=_reinforcement_blocks(inp, geometry, "tendon"),
    )


def _reject_unimplemented_materials(blocks: InputBlocks) -> None:
    all_materials = (
        (() if blocks.concrete is None else (blocks.concrete,))
        + blocks.bars
        + blocks.tendons
    )
    for material in all_materials:
        citation = material.provenance.source.citation
        if citation is not None and "2023" in citation.document:
            raise TraceValidationError(
                "2023 material provenance is published but not implemented "
                "for CT-010"
            )


def _trace_result(value: float) -> TraceResult:
    if math.isnan(value):
        return TraceResult(RESULT_UNDEFINED, None, _UNDEFINED_REASON)
    if math.isinf(value):
        state = (
            RESULT_POSITIVE_INFINITY if value > 0.0 else RESULT_NEGATIVE_INFINITY
        )
        return TraceResult(state, None, _INFINITE_REASON)
    return TraceResult(RESULT_FINITE, value)


def _close(actual: float, expected: float) -> bool:
    if actual == expected or math.isnan(actual) and math.isnan(expected):
        return True
    return (
        math.isfinite(actual)
        and math.isfinite(expected)
        and math.isclose(actual, expected, rel_tol=1.0e-12, abs_tol=1.0e-12)
    )


def _assert_derived(actual: float, expected: float, label: str) -> None:
    if type(actual) not in {int, float} or type(actual) is bool:
        raise TraceValidationError(f"{label} has the wrong numerical type")
    if not _close(float(actual), float(expected)):
        raise TraceValidationError(f"{label} contradicts its declared operands")


def _miner_damage(cycles: float, life: float) -> float:
    if math.isinf(life):
        return 0.0
    if life == 0.0:
        return math.inf
    return cycles / life


def _proof_utilisation(stress: float, properties: Any, gamma_s: float):
    strength = properties.fytk_mpa
    if stress < 0.0 and properties.fyck_mpa is not None:
        strength = properties.fyck_mpa
    limit = strength / gamma_s
    return limit, abs(stress) / limit


def _expression(step_id: str, final: bool) -> str:
    fixed = {
        "normalised-fatigue-inputs": "Complete validated fatigue input identity",
        "geometry-vector": "Bind every retained concrete-ring and reinforcement coordinate",
        "material-vector": "Bind every assigned material identity and constitutive-law value",
        "damage-total": "D = sum n_i/N_i over all retained bins",
        "governing-damage-bin": "governing = argmax bin damage",
        "yield-utilisation": "yield utilisation = max over retained bins",
        "governing-yield-bin": "governing = argmax bin yield utilisation",
        "utilisation": "utilisation = max(D, yield utilisation)",
        "converged": "converged = all retained bin solves converged",
        "governing-spectrum": "governing = argmax spectrum utilisation",
        "family-utilisation": "utilisation = governing spectrum utilisation",
    }
    if step_id in fixed:
        return fixed[step_id]
    if step_id.endswith("-damage"):
        return "D_i = n_i / N_i"
    if step_id.endswith("-yield-utilisation"):
        return "yield utilisation = abs(governing stress) / proof limit"
    if final:
        return "PASS = 1 when convergence and retained limits pass, else 0"
    return f"Bind {step_id}"


def _calculation(
    calculation_id: str,
    title: str,
    axes: tuple,
    specs: tuple,
    values: Mapping[str, float],
    failed_reason: str | None = None,
) -> TraceCalculation:
    units = {spec.step_id: spec.unit for spec in specs}
    steps = []
    for spec in specs:
        final = spec.role == "final_result"
        if spec.step_id not in values:
            raise TraceValidationError(
                f"internal CT-010 value omitted {spec.step_id}"
            )
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
        steps.append(
            TraceStep(
                step_id=spec.step_id,
                title=spec.title,
                dependencies=tuple(
                    TraceDependency(dependency, units[dependency])
                    for dependency in spec.dependencies
                ),
                quantity_role=spec.role,
                source=spec.source,
                symbol=spec.step_id,
                unit=spec.unit,
                actual_expression=_expression(spec.step_id, final),
                substituted_expression=substituted,
                result=result,
            )
        )
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
    context: Mapping[str, Any],
    blocks: InputBlocks,
    spectrum_index: int,
    spectrum_name: str,
    element_index: int,
    properties: Any,
    material_id: str,
    rows: tuple[Mapping[str, Any], ...],
    edition: str,
) -> ElementShape:
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
        ),
    )


def _identity_values(shape: ElementShape) -> dict[str, float]:
    values = {
        "input-concrete-material-present": (
            0.0 if shape.blocks.concrete is None else 1.0
        )
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


def _element_values(
    shape: ElementShape,
    rows: tuple[Mapping[str, Any], ...],
    prepared: Any,
    result: Any,
    properties: Any,
    elastic_modulus: float,
) -> dict[str, float]:
    if result.element_id != properties.element_id:
        raise TraceValidationError(_DRIFT)
    if len(rows) != len(shape.bin_names) or len(result.bins) != len(rows):
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
    values.update(_identity_values(shape))
    if shape.has_fyck:
        values["detail-fyck"] = properties.fyck_mpa
    if shape.has_bond_xi:
        values["detail-bond-xi"] = properties.bond_ratio_xi
    if shape.has_bond_diameter:
        values["detail-bond-eq-diameter"] = (
            properties.bond_equivalent_diameter_mm
        )

    damages, proof_uses, convergence = [], [], []
    for index, (name, description, row, retained) in enumerate(
        zip(shape.bin_names, shape.bin_descriptions, rows, result.bins)
    ):
        if retained.bin_name != name:
            raise TraceValidationError(_DRIFT)
        _assert_derived(retained.cycles, row["cycles"], f"{name} cycles")
        stress_range = abs(retained.stress_total_mpa - retained.stress_long_mpa)
        elastic_range = abs(
            retained.stress_total_elastic_mpa - retained.stress_long_mpa
        )
        design_range = abs(
            retained.stress_total_design_mpa - retained.stress_long_mpa
        )
        bond = (
            stress_range / elastic_range
            if elastic_range > 0.0
            else math.inf
            if stress_range > 0.0
            else 1.0
        )
        life = steel_fatigue_life(
            design_range,
            n_star=properties.n_star,
            k1=properties.k1,
            k2=properties.k2,
            delta_sigma_rsk_mpa=properties.delta_sigma_rsk_mpa,
            gamma_s=gamma_s,
            gamma_ff=1.0,
        )
        damage = _miner_damage(row["cycles"], life.cycles)
        long_limit, long_use = _proof_utilisation(
            retained.stress_long_mpa, properties, gamma_s
        )
        total_limit, total_use = _proof_utilisation(
            retained.stress_total_design_mpa, properties, gamma_s
        )
        if total_use >= long_use:
            proof_limit, proof_use = total_limit, total_use
        else:
            proof_limit, proof_use = long_limit, long_use
        derived = (
            (retained.stress_range_mpa, stress_range, "stress range"),
            (
                retained.stress_range_elastic_mpa,
                elastic_range,
                "elastic stress range",
            ),
            (
                retained.design_stress_range_mpa,
                design_range,
                "design stress range",
            ),
            (retained.bond_adjustment, bond, "bond adjustment"),
            (retained.sn_exponent, life.exponent, "S-N exponent"),
            (retained.cycles_to_failure, life.cycles, "cycles to failure"),
            (
                retained.log10_cycles_to_failure,
                life.log10_cycles,
                "log10 cycles to failure",
            ),
            (retained.damage, damage, "damage"),
            (retained.yield_limit_mpa, proof_limit, "yield limit"),
            (retained.yield_utilisation, proof_use, "yield utilisation"),
        )
        for actual, expected, label in derived:
            _assert_derived(actual, expected, f"{name} {label}")
        damages.append(damage)
        proof_uses.append(proof_use)
        convergence.append(retained.converged)
        prefix = bin_prefix(index, name)
        values[description_step_id(index, name, description)] = 1.0
        values[f"{prefix}-cycles"] = row["cycles"]
        for suffix, column in _BIN_ACTION_COLUMNS:
            values[f"{prefix}-{suffix}"] = row[column]
        values.update(
            {
                f"{prefix}-upstream-converged": float(retained.converged),
                f"{prefix}-upstream-stress-long": retained.stress_long_mpa,
                f"{prefix}-upstream-stress-total": retained.stress_total_mpa,
                f"{prefix}-upstream-stress-total-elastic": retained.stress_total_elastic_mpa,
                f"{prefix}-upstream-stress-total-design": retained.stress_total_design_mpa,
                f"{prefix}-stress-range": stress_range,
                f"{prefix}-bond-adjustment": bond,
                f"{prefix}-design-stress-range": design_range,
                f"{prefix}-sn-exponent": life.exponent,
                f"{prefix}-log10-cycles-to-failure": life.log10_cycles,
                f"{prefix}-damage": damage,
                f"{prefix}-yield-limit": proof_limit,
                f"{prefix}-yield-utilisation": proof_use,
            }
        )

    total_damage = sum(damages)
    damage_index = max(range(len(damages)), key=damages.__getitem__)
    proof_index = max(range(len(proof_uses)), key=proof_uses.__getitem__)
    proof_use = proof_uses[proof_index]
    utilisation = max(total_damage, proof_use)
    converged = all(convergence)
    passed = converged and total_damage <= DAMAGE_LIMIT and proof_use <= 1.0
    for actual, expected, label in (
        (result.damage, total_damage, "element damage"),
        (result.damage_utilisation, total_damage, "damage utilisation"),
        (result.yield_utilisation, proof_use, "element yield utilisation"),
        (result.utilisation, utilisation, "element utilisation"),
    ):
        _assert_derived(actual, expected, label)
    if (
        result.governing_damage_bin != shape.bin_names[damage_index]
        or result.governing_yield_bin != shape.bin_names[proof_index]
        or result.converged is not converged
        or result.passed is not passed
    ):
        raise TraceValidationError(
            "element fatigue verdict contradicts its declared operands"
        )
    status = STATUS_CODES["PASS" if passed else "FAIL"]
    values.update(
        {
            "damage-total": total_damage,
            "governing-damage-bin": float(damage_index),
            "yield-utilisation": proof_use,
            "governing-yield-bin": float(proof_index),
            "utilisation": utilisation,
            "converged": float(converged),
            "passed": status,
            "ct-010-element-result": status,
        }
    )
    return values


def _output_evidence(
    payload: Mapping[str, Any],
    spectrum_names: tuple[str, ...],
    context: Mapping[str, Any],
) -> tuple[OutputShape, dict[str, float]]:
    spectra = tuple(payload["spectra"])
    if len(spectra) != len(spectrum_names):
        raise TraceValidationError(_DRIFT)
    joint = payload["checks"]["concrete"]
    if type(joint) is not bool:
        raise TraceValidationError(_DRIFT)
    shapes = []
    values = {
        "input-check-steel": 1.0,
        "input-check-concrete": float(joint),
    }
    convergence, pass_states = [], []
    for spectrum_index, (name, spectrum) in enumerate(
        zip(spectrum_names, spectra)
    ):
        if spectrum.spectrum_name != name:
            raise TraceValidationError(_DRIFT)
        ids = tuple(item.element_id for item in spectrum.reinforcement)
        if not ids:
            raise TraceValidationError("reinforcement spectrum has no elements")
        shapes.append(SpectrumShape(name, ids))
        uses = []
        for element_index, item in enumerate(spectrum.reinforcement):
            prefix = output_element_prefix(
                spectrum_index, name, element_index, item.element_id
            )
            uses.append(item.utilisation)
            values[f"{prefix}-utilisation"] = item.utilisation
            values[f"{prefix}-converged"] = float(item.converged)
            values[f"{prefix}-passed"] = float(item.passed)
            convergence.append(item.converged)
            pass_states.append(item.passed)
        governing_index = max(range(len(uses)), key=uses.__getitem__)
        if spectrum.governing_reinforcement_id != ids[governing_index]:
            raise TraceValidationError(
                "governing reinforcement contradicts element utilisations"
            )
        prefix = spectrum_prefix(spectrum_index, name)
        values[f"{prefix}-governing-element"] = float(governing_index)
        if not joint:
            spectrum_use = max(uses)
            _assert_derived(
                spectrum.utilisation,
                spectrum_use,
                f"{name} reinforcement utilisation",
            )
            values[f"{prefix}-utilisation"] = spectrum_use

    all_converged = all(convergence)
    all_passed = all(pass_states)
    status = STATUS_CODES["PASS" if all_passed else "FAIL"]
    values["reinforcement-converged"] = float(all_converged)
    values["reinforcement-passed"] = status
    if not joint:
        uses = tuple(spectrum.utilisation for spectrum in spectra)
        governing_index = max(range(len(uses)), key=uses.__getitem__)
        if payload["governing_spectrum"] != spectrum_names[governing_index]:
            raise TraceValidationError(
                "governing spectrum contradicts spectrum utilisations"
            )
        family_use = uses[governing_index]
        _assert_derived(payload["utilisation"], family_use, "family utilisation")
        if (
            payload["converged"] is not all_converged
            or payload["passed"] is not all_passed
        ):
            raise TraceValidationError(
                "family reinforcement verdict contradicts its operands"
            )
        values["governing-spectrum"] = float(governing_index)
        values["family-utilisation"] = family_use
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


def _invalid_bundle(
    inp: Mapping[str, Any],
    replay: ReplayState,
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any],
) -> TraceBundle:
    errors = tuple(replay.payload["errors"])
    shape = InvalidShape(
        errors=errors,
        calculation_id=f"ct-010-{context_id(context)}-invalid",
        axes=context_axes(
            context, member="invalid", error_count=str(len(errors))
        ),
    )
    values = {
        "input-fatigue-on": 1.0,
        "input-check-steel": float(retained_flag(inp, "fatigue_check_steel")),
        "input-check-concrete": float(
            retained_flag(inp, "fatigue_check_concrete")
        ),
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


def _finite_bundle(
    inp: Mapping[str, Any],
    replay: ReplayState,
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any],
) -> TraceBundle | None:
    payload = replay.payload
    if tuple(payload) != VALID_KEYS:
        raise TraceValidationError(_DRIFT)
    if not payload["checks"]["reinforcement"]:
        return None
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
    spectrum_names = tuple(replay.groups)
    spectra = tuple(payload["spectra"])
    if len(spectrum_names) != len(spectra):
        raise TraceValidationError(_DRIFT)

    shapes, calculations = [], []
    for spectrum_index, (name, spectrum) in enumerate(
        zip(spectrum_names, spectra)
    ):
        if spectrum.spectrum_name != name:
            raise TraceValidationError(_DRIFT)
        rows = tuple(replay.groups[name])
        if len(spectrum.reinforcement) != len(prepared.reinforcement):
            raise TraceValidationError(_DRIFT)
        for element_index, properties in enumerate(prepared.reinforcement):
            material = assigned[element_index]
            shape = _element_shape(
                context,
                blocks,
                spectrum_index,
                name,
                element_index,
                properties,
                material.material_id,
                rows,
                edition,
            )
            values = _element_values(
                shape,
                rows,
                prepared,
                spectrum.reinforcement[element_index],
                properties,
                dict(material.values)["Es"],
            )
            shapes.append(shape)
            calculations.append(
                _calculation(
                    shape.calculation_id,
                    f"Reinforcement fatigue {name} / {properties.element_id}",
                    shape.axes,
                    element_steps(shape),
                    values,
                )
            )
    output_shape, output_values = _output_evidence(
        payload, spectrum_names, context
    )
    calculations.append(
        _calculation(
            output_shape.calculation_id,
            "Reinforcement fatigue output selection",
            output_shape.axes,
            output_steps(output_shape),
            output_values,
        )
    )
    bundle = create_bundle(
        input_sha256=input_sha256,
        result_sha256=result_sha256,
        calculations=tuple(calculations),
    )
    shape = FamilyShape(tuple(shapes), output_shape, None)
    audit_trace_registry(bundle, expected_registry(shape))
    return bundle


def _expected_bundle(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any],
) -> TraceBundle | None:
    replay = replay_input(inp)
    retained_out = _mapping(out, "retained result mapping")
    present = "fatigue" in retained_out
    candidate = retained_out.get("fatigue")
    if not replay.active:
        if present:
            raise TraceValidationError(
                "inactive CT-010 input cannot carry a fatigue surface"
            )
        return None
    if not present or candidate is None:
        raise TraceValidationError(
            "active CT-010 input must publish the fatigue surface"
        )
    validate_candidate(candidate, replay)
    if replay.branch == "invalid":
        return _invalid_bundle(
            inp, replay, input_sha256, result_sha256, context
        )
    return _finite_bundle(inp, replay, input_sha256, result_sha256, context)


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
        ArithmeticError,
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise TraceValidationError(f"invalid CT-010 fatigue evidence: {exc}") from exc


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
                "inapplicable CT-010 input cannot carry a trace bundle"
            )
        return None
    if bundle is None:
        raise TraceValidationError(
            "applicable CT-010 input requires a trace bundle"
        )
    model = validate_bundle(
        bundle,
        expected_input_sha256=input_sha256,
        expected_result_sha256=result_sha256,
    )
    if model != expected:
        raise TraceValidationError(
            "CT-010 trace differs from authoritative exact reconstruction"
        )
    return model


__all__ = ["build_fatigue_trace_family", "validate_fatigue_trace_family"]
