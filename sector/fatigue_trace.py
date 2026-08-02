"""Build and validate the CT-010a reinforcement-fatigue trace family.

The retained application preflight selects the inactive, invalid, or finite
branch before candidate numerics are inspected. Finite evidence is replayed
through the retained fatigue composition and then bound from the published
fatigue payload. Catalog-backed material identities use the shared immutable
section blocks; valid catalog-free laws are represented as uncited project
material blocks rather than being relabelled as standard values.
"""

from __future__ import annotations

import dataclasses
import math
import pathlib
import sys
from collections.abc import Mapping, Sequence
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
from .elastic import CombinedElasticResult
from .fatigue import (
    FatigueBinState,
    FatigueSpectrumResult,
    ReinforcementBinResult,
    ReinforcementFatigueProperties,
    ReinforcementFatigueResult,
)
from .fatigue_trace_contract import (
    BASIS_KEYS,
    BIN_RESULT_FIELDS,
    BIN_STATE_FIELDS,
    CHECK_KEYS,
    CONCRETE_EXCLUDED_BIN_FIELDS,
    CONCRETE_EXCLUDED_KEYS,
    CONCRETE_EXCLUDED_RESULT_FIELDS,
    COVERAGE_ID,
    EDITIONS,
    FACTOR_KEYS,
    INVALID_KEYS,
    METHOD_ID,
    PROPERTY_FIELDS,
    RAW_SOLVER_FIELDS,
    RESULT_FIELDS,
    SPECTRUM_RESULT_FIELDS,
    STATUS_CODES,
    VALID_KEYS,
    ElementShape,
    FamilyShape,
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
from .materials import MildSteel, Prestress
from .section_trace_blocks import (
    ActionBlock,
    GeometryBlock,
    MaterialBlock,
    ProvenanceBlock,
    SectionTraceBlocks,
    _concrete_block,
    _law_values,
    _material_method,
    _materials,
    context_axes,
    context_id,
)
from .torsion_trace import _boolean, _mapping, _number, _retained_mapping
from .trace_registry import audit_trace_registry


_DRIFT = "authoritative CT-010 retained inventory drifted"
_SECTION_ERRORS = (
    "geometry_error", "void_error", "steel_error", "material_error")
_ASSUMPTIONS = (
    "Retained reinforcement fatigue replay; concrete-fatigue values are "
    "the named PR-08D.3b sibling.",
)
_INFINITE_REASON = (
    "The retained fatigue quantity is unbounded and is represented without "
    "a fabricated finite replacement."
)
_UNDEFINED_REASON = (
    "The retained fatigue quantity is undefined and is represented without "
    "a fabricated finite replacement."
)
_FIELD_PINS = {
    ReinforcementFatigueProperties: PROPERTY_FIELDS,
    ReinforcementBinResult: BIN_RESULT_FIELDS,
    ReinforcementFatigueResult: RESULT_FIELDS,
    FatigueBinState: BIN_STATE_FIELDS,
    FatigueSpectrumResult: SPECTRUM_RESULT_FIELDS,
}
_SKIPPED_FIELDS = {
    FatigueBinState: frozenset(
        (*CONCRETE_EXCLUDED_BIN_FIELDS, *RAW_SOLVER_FIELDS)),
    FatigueSpectrumResult: frozenset(CONCRETE_EXCLUDED_RESULT_FIELDS),
}
_BIN_ACTION_COLUMNS = (
    ("n-long", "n_long_ed_kn"),
    ("mx-long", "mx_long_ed_knm"),
    ("my-long", "my_long_ed_knm"),
    ("n-short", "n_short_ed_kn"),
    ("mx-short", "mx_short_ed_knm"),
    ("my-short", "my_short_ed_knm"),
)


def _app_modules():
    try:
        import fatigue_analysis
        import fatigue_inputs
    except ImportError:  # pragma: no cover - direct sector-only import
        sys.path.insert(0, str(
            pathlib.Path(__file__).resolve().parent.parent / "app"))
        import fatigue_analysis
        import fatigue_inputs
    return fatigue_analysis, fatigue_inputs


def _flag(inp: Mapping[str, Any], key: str) -> bool:
    if key not in inp or inp.get(key) is None:
        return False
    return _boolean(inp.get(key), key)


def _exact(actual: Any, expected: Any, label: str) -> None:
    """Compare retained output byte-semantically, with named sibling skips."""

    if expected is None or type(expected) in {bool, str, int}:
        if type(actual) is not type(expected) or actual != expected:
            raise TraceValidationError(
                f"{label} differs from authoritative replay")
        return
    if type(expected) is float:
        if type(actual) is not float:
            raise TraceValidationError(f"{label} has the wrong retained type")
        if actual != expected and not (
                math.isnan(actual) and math.isnan(expected)):
            raise TraceValidationError(
                f"{label} differs from authoritative replay")
        return
    if dataclasses.is_dataclass(expected) and not isinstance(expected, type):
        if type(actual) is not type(expected):
            raise TraceValidationError(f"{label} has the wrong retained type")
        names = tuple(field.name for field in dataclasses.fields(type(expected)))
        pin = _FIELD_PINS.get(type(expected))
        if pin is not None and names != pin:
            raise TraceValidationError(_DRIFT)
        skipped = _SKIPPED_FIELDS.get(type(expected), frozenset())
        for name in names:
            got = getattr(actual, name)
            wanted = getattr(expected, name)
            if name in skipped:
                if type(got) is not type(wanted):
                    raise TraceValidationError(
                        f"{label}.{name} has the wrong retained type")
                if (name in RAW_SOLVER_FIELDS and wanted is not None
                        and type(wanted) is not CombinedElasticResult):
                    raise TraceValidationError(_DRIFT)
                continue
            _exact(got, wanted, f"{label}.{name}")
        return
    if isinstance(expected, Mapping):
        actual = _mapping(actual, label)
        if tuple(actual) != tuple(expected):
            raise TraceValidationError(
                f"{label} retained keys/order differ: {tuple(actual)!r}")
        for key in expected:
            _exact(actual[key], expected[key], f"{label}.{key}")
        return
    if type(expected) in {tuple, list}:
        if type(actual) is not type(expected) or len(actual) != len(expected):
            raise TraceValidationError(f"{label} cardinality differs")
        for index, (got, wanted) in enumerate(zip(actual, expected)):
            _exact(got, wanted, f"{label}[{index}]")
        return
    raise TraceValidationError(f"{label} has an unsupported retained type")


def _pin_retained_contract(fatigue_inputs) -> None:
    if tuple(fatigue_inputs.EDITIONS) != EDITIONS:
        raise TraceValidationError(_DRIFT)
    for kind, fields in _FIELD_PINS.items():
        if tuple(field.name for field in dataclasses.fields(kind)) != fields:
            raise TraceValidationError(_DRIFT)


def _replay(inp: Mapping[str, Any]) -> dict[str, Any]:
    if "fatigue_on" not in inp or inp.get("fatigue_on") is None:
        return {"active": False}
    if not _boolean(inp.get("fatigue_on"), "fatigue_on"):
        return {"active": False}
    if inp.get("section") is None or any(inp.get(key) for key in _SECTION_ERRORS):
        return {"active": False}

    fatigue_analysis, fatigue_inputs = _app_modules()
    _pin_retained_contract(fatigue_inputs)
    check_steel = _flag(inp, "fatigue_check_steel")
    _flag(inp, "fatigue_check_concrete")
    errors = tuple(fatigue_analysis.validation_errors(inp))
    if errors:
        return {
            "active": True,
            "branch": "invalid",
            "payload": fatigue_analysis.invalid_result(inp, errors),
        }

    # The retained adapter intentionally accepts aliases. The trace boundary
    # does not: only an exact published selector may receive standard evidence.
    edition = inp.get("fatigue_edition")
    if type(edition) is not str or edition not in EDITIONS:
        raise TraceValidationError(
            "fatigue_edition must be one exact retained edition string")
    for key in ("nl", "ns", "fatigue_gamma_ff"):
        _number(inp.get(key), key, positive=True)
    if check_steel:
        _number(inp.get("fatigue_gamma_s"), "fatigue_gamma_s", positive=True)

    payload = fatigue_analysis.run_analysis(inp)
    prepared = fatigue_analysis.prepare(inp)
    groups = fatigue_inputs.spectrum_groups(
        inp[fatigue_inputs.SPECTRUM_TABLE_KEY])
    return {
        "active": True,
        "branch": "finite",
        "payload": payload,
        "prepared": prepared,
        "groups": groups,
    }


def _validate_invalid(candidate: Any, expected: Mapping[str, Any]) -> None:
    if tuple(expected) != INVALID_KEYS:
        raise TraceValidationError(_DRIFT)
    candidate = _retained_mapping(
        candidate, INVALID_KEYS, (), "candidate invalid fatigue result")
    if candidate["valid"] is not False or expected["valid"] is not False:
        raise TraceValidationError("invalid fatigue result.valid must be False")
    for key in INVALID_KEYS:
        _exact(candidate[key], expected[key], f"candidate invalid {key}")


def _validate_finite(candidate: Any, expected: Mapping[str, Any]) -> None:
    if tuple(expected) != VALID_KEYS:
        raise TraceValidationError(_DRIFT)
    mapping = _mapping(candidate, "candidate fatigue result")
    if "valid" in mapping:
        raise TraceValidationError(
            "finite fatigue result cannot carry invalid-branch valid")
    candidate = _retained_mapping(
        mapping, VALID_KEYS, (), "candidate fatigue result")
    for pin, keys in (
        ("checks", CHECK_KEYS),
        ("partial_factors", FACTOR_KEYS),
        ("basis", BASIS_KEYS),
    ):
        if tuple(expected[pin]) != keys:
            raise TraceValidationError(_DRIFT)
    for key in VALID_KEYS:
        if key in CONCRETE_EXCLUDED_KEYS:
            if type(candidate[key]) is not type(expected[key]):
                raise TraceValidationError(
                    f"candidate fatigue {key} retained type differs")
            continue
        _exact(candidate[key], expected[key], f"candidate fatigue {key}")


def _ordered(value: Any, label: str) -> tuple[Any, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TraceValidationError(f"{label} must be an ordered sequence")
    return tuple(value)


def _project_materials(inp: Mapping[str, Any], *, kind: str,
                       count: int) -> tuple[MaterialBlock, ...]:
    """Represent valid catalog-free explicit laws with project provenance."""

    law_key = "bar_materials" if kind == "bar" else "tendon_materials"
    element_key = "bar_elements" if kind == "bar" else "tendon_elements"
    expected_type = MildSteel if kind == "bar" else Prestress
    laws = _ordered(inp.get(law_key), law_key)
    records = _ordered(inp.get(element_key), element_key)
    if len(laws) != count or len(records) != count:
        raise TraceValidationError(
            f"catalog-free {kind} laws and assignments must align")
    blocks: list[MaterialBlock] = []
    seen: set[str] = set()
    for index, (law, record) in enumerate(zip(laws, records)):
        if type(law) is not expected_type:
            raise TraceValidationError(
                f"catalog-free {kind} law {index} has the wrong type")
        record = _mapping(record, f"{element_key}[{index}]")
        element_id = record.get("id")
        material_id = record.get("material_id")
        for label, value in (
            ("element ID", element_id), ("material ID", material_id)):
            if (type(value) is not str or not value
                    or value != value.strip()):
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


def _material_blocks(inp: Mapping[str, Any], geometry: GeometryBlock,
                     kind: str) -> tuple[MaterialBlock, ...]:
    elements = geometry.bars if kind == "bar" else geometry.tendons
    law_key = "bar_materials" if kind == "bar" else "tendon_materials"
    catalog_key = (
        "mild_material_catalog" if kind == "bar"
        else "prestress_material_catalog")
    if inp.get(law_key) is not None and inp.get(catalog_key) is None:
        return _project_materials(inp, kind=kind, count=len(elements))
    return _materials(
        inp,
        kind=kind,
        count=len(elements),
        default=inp.get("steel") if kind == "bar" else inp.get("prestress"),
    )


def _fatigue_blocks(inp: Mapping[str, Any]) -> SectionTraceBlocks:
    geometry = GeometryBlock.from_section(inp["section"])
    concrete = _concrete_block(inp)
    bars = _material_blocks(inp, geometry, "bar")
    tendons = _material_blocks(inp, geometry, "tendon")
    materials = (concrete, *bars, *tendons)
    return SectionTraceBlocks(
        geometry=geometry,
        plastic_actions=ActionBlock((
            ("P_pl", 0.0), ("Mx_pl", 0.0), ("My_pl", 0.0))),
        concrete=concrete,
        bars=bars,
        tendons=tendons,
        plastic_method_id=_material_method(materials),
    )


def _reject_unimplemented_materials(blocks: SectionTraceBlocks) -> None:
    for block in (blocks.concrete, *blocks.bars, *blocks.tendons):
        citation = block.provenance.source.citation
        if citation is not None and "2023" in citation.document:
            raise TraceValidationError(
                "2023 material provenance is published but not implemented "
                "for CT-010")


def _result(value: float) -> TraceResult:
    if math.isnan(value):
        return TraceResult(RESULT_UNDEFINED, None, _UNDEFINED_REASON)
    if math.isinf(value):
        state = (RESULT_POSITIVE_INFINITY if value > 0.0
                 else RESULT_NEGATIVE_INFINITY)
        return TraceResult(state, None, _INFINITE_REASON)
    return TraceResult(RESULT_FINITE, value)


def _expression(step_id: str, final: bool) -> str:
    exact = {
        "normalised-fatigue-inputs": "Complete validated fatigue input identity",
        "damage-total": "D = sum n_i/N_i over all retained bins",
        "governing-damage-bin": "governing = argmax bin damage",
        "yield-utilisation": "yield utilisation = max over retained bins",
        "governing-yield-bin": "governing = argmax bin yield utilisation",
        "utilisation": "utilisation = max(D, yield utilisation)",
        "converged": "converged = all retained bin solves converged",
        "governing-spectrum": "governing = argmax spectrum utilisation",
        "family-utilisation": "utilisation = governing spectrum utilisation",
    }
    if step_id in exact:
        return exact[step_id]
    if step_id.endswith("-damage"):
        return "D_i = n_i / N_i"
    if step_id.endswith("-yield-utilisation"):
        return "yield utilisation = abs(governing stress) / proof limit"
    if final:
        return "PASS = 1 when converged and retained limits pass, else 0"
    return f"Bind {step_id}"


def _calculation(calculation_id, title, axes, specs, values,
                 *, failed_reason: str | None = None) -> TraceCalculation:
    units = {spec.step_id: spec.unit for spec in specs}
    steps: list[TraceStep] = []
    for spec in specs:
        final = spec.quantity_role == "final_result"
        if final and failed_reason is not None:
            result = TraceResult(RESULT_FAILED, None, failed_reason)
            substituted = f"{spec.step_id} = failed"
        else:
            numeric = float(values[spec.step_id])
            result = _result(numeric)
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
            quantity_role=spec.quantity_role,
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
        final_step_id=steps[-1].step_id,
        steps=tuple(steps),
        assumptions=_ASSUMPTIONS,
    )


def _element_shape(context, blocks, si, spectrum_name, ei, properties,
                   material_id, rows, edition) -> ElementShape:
    bin_names = tuple(row["name"] for row in rows)
    descriptions = tuple(row["description"] for row in rows)
    mixed = bool(blocks.geometry.bars) and bool(blocks.geometry.tendons)
    calculation_id = (
        f"ct-010-{context_id(context)}-s{si:02d}-"
        f"{_token(spectrum_name)}-e{ei:02d}-"
        f"{_token(properties.element_id)}-{_token(material_id)}-"
        f"{_token(properties.detail_id)}"
    )
    return ElementShape(
        spectrum_index=si,
        spectrum_name=spectrum_name,
        element_index=ei,
        kind=properties.kind,
        element_id=properties.element_id,
        material_id=material_id,
        detail_id=properties.detail_id,
        bin_names=bin_names,
        bin_descriptions=descriptions,
        blocks=blocks,
        has_fyck=properties.fyck_mpa is not None,
        has_bond_xi=properties.bond_ratio_xi is not None,
        has_bond_diameter=(
            properties.bond_equivalent_diameter_mm is not None),
        mixed=mixed,
        edition=edition,
        calculation_id=calculation_id,
        axes=context_axes(
            context,
            member="reinforcement",
            spectrum_index=str(si),
            element_index=str(ei),
            bin_count=str(len(bin_names)),
            fatigue_edition=edition,
            mixed=str(mixed).lower(),
        ),
    )


def _token(value: str) -> str:
    return trace_identity_token(value)


def _block_values(shape: ElementShape) -> dict[str, float]:
    values: dict[str, float] = {}
    for ri, ring in enumerate(shape.blocks.geometry.rings):
        for pi, (x, y) in enumerate(ring):
            prefix = f"geometry-ring-{ri:03d}-point-{pi:04d}"
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
    for material in (
        shape.blocks.concrete,
        *shape.blocks.bars,
        *shape.blocks.tendons,
    ):
        for field, value in material.values:
            values[material_step_id(material, field)] = value
    values["material-vector"] = 1.0
    return values


def _element_values(shape: ElementShape, rows, prepared, result,
                    properties, es: float) -> dict[str, Any]:
    if result.element_id != properties.element_id:
        raise TraceValidationError(_DRIFT)
    if (len(rows) != len(shape.bin_names)
            or len(result.bins) != len(shape.bin_names)):
        raise TraceValidationError(_DRIFT)
    values: dict[str, Any] = {
        "input-check-steel": 1.0,
        "input-edition": float(EDITIONS.index(shape.edition)),
        "input-gamma-s": float(prepared.gamma_s),
        "input-gamma-ff": float(prepared.gamma_ff),
        "input-nl": float(prepared.nl),
        "input-ns": float(prepared.ns),
        "input-diameter": float(properties.diameter_mm),
        "detail-n-star": float(properties.n_star),
        "detail-k1": float(properties.k1),
        "detail-k2": float(properties.k2),
        "detail-delta-sigma-rsk": float(properties.delta_sigma_rsk_mpa),
        "detail-fytk": float(properties.fytk_mpa),
        "element-es": float(es),
        "normalised-fatigue-inputs": 1.0,
    }
    values.update(_block_values(shape))
    if shape.has_fyck:
        values["detail-fyck"] = float(properties.fyck_mpa)
    if shape.has_bond_xi:
        values["detail-bond-xi"] = float(properties.bond_ratio_xi)
    if shape.has_bond_diameter:
        values["detail-bond-eq-diameter"] = float(
            properties.bond_equivalent_diameter_mm)

    for index, (name, description, row, bin_result) in enumerate(zip(
        shape.bin_names, shape.bin_descriptions, rows, result.bins,
    )):
        if (type(name) is not str or type(description) is not str
                or bin_result.bin_name != name):
            raise TraceValidationError(_DRIFT)
        prefix = bin_prefix(index, name)
        values[description_step_id(index, name, description)] = 1.0
        values[f"{prefix}-cycles"] = float(row["cycles"])
        for suffix, column in _BIN_ACTION_COLUMNS:
            values[f"{prefix}-{suffix}"] = float(row[column])
        values.update({
            f"{prefix}-upstream-converged": float(bin_result.converged),
            f"{prefix}-upstream-stress-long": bin_result.stress_long_mpa,
            f"{prefix}-upstream-stress-total": bin_result.stress_total_mpa,
            f"{prefix}-upstream-stress-total-elastic":
                bin_result.stress_total_elastic_mpa,
            f"{prefix}-upstream-stress-total-design":
                bin_result.stress_total_design_mpa,
            f"{prefix}-stress-range": bin_result.stress_range_mpa,
            f"{prefix}-bond-adjustment": bin_result.bond_adjustment,
            f"{prefix}-design-stress-range":
                bin_result.design_stress_range_mpa,
            f"{prefix}-sn-exponent": bin_result.sn_exponent,
            f"{prefix}-log10-cycles-to-failure":
                bin_result.log10_cycles_to_failure,
            f"{prefix}-damage": bin_result.damage,
            f"{prefix}-yield-limit": bin_result.yield_limit_mpa,
            f"{prefix}-yield-utilisation": bin_result.yield_utilisation,
        })
    status = STATUS_CODES["PASS" if result.passed else "FAIL"]
    values.update({
        "damage-total": result.damage,
        "governing-damage-bin": float(
            shape.bin_names.index(result.governing_damage_bin)),
        "yield-utilisation": result.yield_utilisation,
        "governing-yield-bin": float(
            shape.bin_names.index(result.governing_yield_bin)),
        "utilisation": result.utilisation,
        "converged": float(result.converged),
        "passed": status,
        "ct-010-element-result": status,
    })
    return values


def _output_evidence(payload, spectrum_names, context):
    spectra = tuple(payload["spectra"])
    if len(spectra) != len(spectrum_names):
        raise TraceValidationError(_DRIFT)
    joint = payload["checks"]["concrete"]
    spectrum_shapes: list[SpectrumShape] = []
    values: dict[str, Any] = {
        "input-check-steel": 1.0,
        "input-check-concrete": float(joint),
    }
    all_converged: list[bool] = []
    all_passed: list[bool] = []
    for si, (name, spectrum) in enumerate(zip(spectrum_names, spectra)):
        if spectrum.spectrum_name != name:
            raise TraceValidationError(_DRIFT)
        ids = tuple(item.element_id for item in spectrum.reinforcement)
        spectrum_shapes.append(SpectrumShape(name, ids))
        for ei, item in enumerate(spectrum.reinforcement):
            prefix = output_element_prefix(si, name, ei, item.element_id)
            values[f"{prefix}-utilisation"] = item.utilisation
            values[f"{prefix}-converged"] = float(item.converged)
            values[f"{prefix}-passed"] = float(item.passed)
            all_converged.append(item.converged)
            all_passed.append(item.passed)
        prefix = spectrum_prefix(si, name)
        values[f"{prefix}-governing-element"] = float(
            ids.index(spectrum.governing_reinforcement_id))
        if not joint:
            values[f"{prefix}-utilisation"] = spectrum.utilisation

    reinforcement_converged = all(all_converged)
    reinforcement_passed = all(all_passed)
    values["reinforcement-converged"] = float(reinforcement_converged)
    status = STATUS_CODES["PASS" if reinforcement_passed else "FAIL"]
    values["reinforcement-passed"] = status
    if not joint:
        names = tuple(spectrum_names)
        values["governing-spectrum"] = float(
            names.index(payload["governing_spectrum"]))
        values["family-utilisation"] = float(payload["utilisation"])
        if (payload["converged"] is not reinforcement_converged
                or payload["passed"] is not reinforcement_passed):
            raise TraceValidationError(_DRIFT)
    values["ct-010-reinforcement-output-result"] = status
    shape = OutputShape(
        joint=joint,
        spectra=tuple(spectrum_shapes),
        calculation_id=(
            f"ct-010-{context_id(context)}-reinforcement-output"),
        axes=context_axes(
            context,
            member="reinforcement-output",
            joint=str(joint).lower(),
            spectrum_count=str(len(spectrum_shapes)),
        ),
    )
    return shape, values


def _expected_bundle(inp, out, input_sha256, result_sha256, context):
    replay = _replay(inp)
    out = _mapping(out, "retained result mapping")
    candidate_present = "fatigue" in out
    candidate = out.get("fatigue")
    if not replay["active"]:
        if candidate_present:
            raise TraceValidationError(
                "inactive CT-010 input cannot carry a fatigue surface")
        return None
    if not candidate_present or candidate is None:
        raise TraceValidationError(
            "active CT-010 input must publish the fatigue surface")

    if replay["branch"] == "invalid":
        _validate_invalid(candidate, replay["payload"])
        payload = {key: candidate[key] for key in INVALID_KEYS}
        errors = tuple(payload["errors"])
        shape = InvalidShape(
            errors=errors,
            calculation_id=f"ct-010-{context_id(context)}-invalid",
            axes=context_axes(
                context, member="invalid", error_count=str(len(errors))),
        )
        values: dict[str, float] = {
            "input-fatigue-on": 1.0,
            "input-check-steel": float(_flag(inp, "fatigue_check_steel")),
            "input-check-concrete": float(
                _flag(inp, "fatigue_check_concrete")),
        }
        for index, message in enumerate(errors):
            values[invalid_error_id(index, message)] = 1.0
        calculation = _calculation(
            shape.calculation_id,
            "Fatigue invalid input state",
            shape.axes,
            invalid_steps(shape),
            values,
            failed_reason=(
                "Retained fatigue preflight failed: " + "; ".join(errors)),
        )
        bundle = create_bundle(
            input_sha256=input_sha256,
            result_sha256=result_sha256,
            calculations=(calculation,),
        )
        audit_trace_registry(bundle, expected_registry(
            FamilyShape((), None, shape)))
        return bundle

    _validate_finite(candidate, replay["payload"])
    payload = {key: candidate[key] for key in VALID_KEYS}
    if not payload["checks"]["reinforcement"]:
        return None

    prepared = replay["prepared"]
    blocks = _fatigue_blocks(inp)
    _reject_unimplemented_materials(blocks)
    assigned = (*blocks.bars, *blocks.tendons)
    if tuple(block.element_id for block in assigned) != tuple(
            prepared.solver_element_ids):
        raise TraceValidationError("fatigue element identity must align")
    edition = payload["edition"]
    if edition not in EDITIONS:
        raise TraceValidationError(_DRIFT)
    spectrum_names = tuple(replay["groups"])
    spectra = tuple(payload["spectra"])
    if len(spectrum_names) != len(spectra):
        raise TraceValidationError(_DRIFT)

    shapes: list[ElementShape] = []
    calculations: list[TraceCalculation] = []
    for si, (name, spectrum) in enumerate(zip(spectrum_names, spectra)):
        if spectrum.spectrum_name != name:
            raise TraceValidationError(_DRIFT)
        rows = replay["groups"][name]
        if len(spectrum.reinforcement) != len(prepared.reinforcement):
            raise TraceValidationError(_DRIFT)
        for ei, properties in enumerate(prepared.reinforcement):
            material = assigned[ei]
            shape = _element_shape(
                context, blocks, si, name, ei, properties,
                material.material_id, rows, edition)
            values = _element_values(
                shape, rows, prepared, spectrum.reinforcement[ei],
                properties, dict(material.values)["Es"])
            shapes.append(shape)
            calculations.append(_calculation(
                shape.calculation_id,
                f"Reinforcement fatigue {name} / {properties.element_id}",
                shape.axes,
                element_steps(shape),
                values,
            ))

    output_shape, output_values = _output_evidence(
        payload, spectrum_names, context)
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
    audit_trace_registry(bundle, expected_registry(
        FamilyShape(tuple(shapes), output_shape, None)))
    return bundle


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
            inp, out, input_sha256, result_sha256,
            {} if context is None else context)
    except TraceValidationError:
        raise
    except (ArithmeticError, AttributeError, KeyError, TypeError,
            ValueError) as exc:
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
        inp, out,
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
