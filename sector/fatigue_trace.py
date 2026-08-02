"""Unpublished CT-010a successful reinforcement-fatigue traces."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any

import numpy as np

from .calculation_trace import (
    RESULT_FAILED, RESULT_FINITE, RESULT_NEGATIVE_INFINITY,
    RESULT_POSITIVE_INFINITY, RESULT_UNDEFINED, ROLE_COMPUTED, ROLE_FINAL,
    ROLE_METHOD_VALUE, ROLE_USER_INPUT, TraceBundle, TraceCalculation,
    TraceDependency, TraceResult, TraceStep, TraceUnit, TraceValidationError,
    create_bundle, trace_identity_token, validate_bundle,
)
from .fatigue_trace_contract import (
    BOUNDARY, COVERAGE_ID, CYCLES, ELASTIC, FAMILY_ID, INPUT, METHOD_ID, MPA,
    ONE, VERDICT, MemberShape, StepShape, invalid_registry, registry_for,
    selected_sources,
)
from .fatigue_trace_replay import (
    AssessmentReplay, BinReplay, SuccessfulReplay, classify,
    successful_replay,
)
from .section_trace_blocks import context_axes, context_id
from .trace_registry import audit_trace_registry


_HASH_PARTS = 8
_IDENTITY_GROUPS = (
    "complete-fatigue-input",
    "geometry",
    "element-assignments",
    "material-catalogues",
    "fatigue-detail-and-spectrum",
    "adapter-analysis-signature",
    "aligned-preparation",
)


def _freeze(value: Any, active: set[int] | None = None) -> Any:
    """Return a type-, order- and dtype-retaining JSON identity tree."""

    if active is None:
        active = set()
    if value is None:
        return ["none"]
    if type(value) is bool:
        return ["bool", value]
    if type(value) is int:
        return ["int", str(value)]
    if type(value) is float:
        return ["float", value.hex()]
    if type(value) is str:
        return ["str", value]
    if type(value) is bytes:
        return ["bytes", value.hex()]
    if isinstance(value, np.generic):
        return ["numpy-scalar", value.dtype.str, _freeze(value.item(), active)]

    identity = id(value)
    if identity in active:
        raise TraceValidationError("cyclic fatigue input identity is unsupported")
    active.add(identity)
    try:
        if isinstance(value, np.ndarray):
            if value.dtype.hasobject:
                payload = [_freeze(item, active) for item in value.flat]
            else:
                payload = value.tobytes(order="C").hex()
            return ["numpy-array", value.dtype.str, list(value.shape), payload]
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return [
                "dataclass", value.__class__.__module__,
                value.__class__.__qualname__,
                [[field.name, _freeze(getattr(value, field.name), active)]
                 for field in dataclasses.fields(value)],
            ]
        if isinstance(value, Mapping):
            return [
                "mapping", value.__class__.__module__,
                value.__class__.__qualname__,
                [[_freeze(key, active), _freeze(item, active)]
                 for key, item in value.items()],
            ]
        if type(value) in {list, tuple}:
            return [type(value).__name__, [_freeze(item, active) for item in value]]
        module = value.__class__.__module__
        name = value.__class__.__qualname__
        if (module == "pandas" or module.startswith("pandas.")) and hasattr(
                value, "to_numpy"):
            return [
                "pandas", module, name,
                _freeze(list(value.index), active),
                _freeze(list(getattr(value, "columns", ())), active),
                [str(item) for item in getattr(value, "dtypes", ())],
                _freeze(value.to_numpy(), active),
            ]
        if hasattr(value, "__dict__"):
            return ["object", module, name, _freeze(vars(value), active)]
        slots = getattr(value.__class__, "__slots__", ())
        if slots:
            names = (slots,) if type(slots) is str else tuple(slots)
            return [
                "slots", module, name,
                [[slot, _freeze(getattr(value, slot), active)]
                 for slot in names if hasattr(value, slot)],
            ]
    finally:
        active.remove(identity)
    raise TraceValidationError(
        f"unsupported fatigue identity type {type(value).__module__}."
        f"{type(value).__qualname__}")


def _digest_parts(value: Any) -> tuple[float, ...]:
    payload = json.dumps(
        _freeze(value), ensure_ascii=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    digest = hashlib.sha256(payload).digest()
    return tuple(
        float(int.from_bytes(digest[index:index + 4], "big"))
        for index in range(0, 32, 4)
    )


def _selected_input(inp: Mapping[str, Any], predicate) -> tuple[Any, ...]:
    return tuple(
        (key, inp[key]) for key in inp
        if type(key) is str and predicate(key)
    )


def _identity_payloads(
    inp: Mapping[str, Any], replay: SuccessfulReplay,
) -> tuple[tuple[str, Any], ...]:
    section = inp.get("section")
    geometry = {
        "section": section,
        "element_geometry": _selected_input(
            inp, lambda key: key in {"bar_elements", "tendon_elements"}),
    }
    assignments = _selected_input(
        inp, lambda key: key in {"bar_elements", "tendon_elements"})
    materials = _selected_input(
        inp,
        lambda key: (
            key == "concrete" or "material" in key or "catalog" in key
            or "preset" in key),
    )
    fatigue = _selected_input(
        inp, lambda key: key.startswith("fatigue_") or key in {"nl", "ns"})
    boundary = replay.prepared
    return (
        (_IDENTITY_GROUPS[0], inp),
        (_IDENTITY_GROUPS[1], geometry),
        (_IDENTITY_GROUPS[2], assignments),
        (_IDENTITY_GROUPS[3], materials),
        (_IDENTITY_GROUPS[4], fatigue),
        (_IDENTITY_GROUPS[5], replay.analysis_signature),
        (_IDENTITY_GROUPS[6], {
            "spectra": boundary.spectra,
            "reinforcement": boundary.reinforcement,
            "details": boundary.detail_records,
            "elements": boundary.element_records,
            "solver_element_ids": boundary.solver_element_ids,
            "factors": (boundary.gamma_s, boundary.gamma_ff),
        }),
    )


def _result(value: float) -> TraceResult:
    number = float(value)
    if math.isnan(number):
        return TraceResult(RESULT_UNDEFINED, None, "replayed value is NaN")
    if math.isinf(number):
        return TraceResult(
            RESULT_POSITIVE_INFINITY if number > 0.0
            else RESULT_NEGATIVE_INFINITY,
            None,
            "replayed value is infinite",
        )
    return TraceResult(RESULT_FINITE, number)


def _format(value: float) -> str:
    number = float(value)
    return format(number, ".17g") if math.isfinite(number) else str(number)


def _step(
    step_id: str,
    title: str,
    value: float,
    unit: TraceUnit,
    role: str,
    source,
    dependencies: tuple[TraceStep, ...] = (),
    *,
    expression: str = "Retain independently replayed value",
    warning: str | None = None,
) -> TraceStep:
    return TraceStep(
        step_id=step_id,
        title=title,
        dependencies=tuple(
            TraceDependency(item.step_id, item.unit) for item in dependencies),
        quantity_role=role,
        source=source,
        symbol=step_id,
        unit=unit,
        actual_expression=expression,
        substituted_expression=f"{step_id} = {_format(value)} {unit.symbol}",
        result=_result(value),
        warnings=(() if warning is None else (warning,)),
    )


def _identity_steps(payloads: tuple[tuple[str, Any], ...]) -> list[TraceStep]:
    steps = []
    for group, payload in payloads:
        for position, value in enumerate(_digest_parts(payload), start=1):
            steps.append(_step(
                f"identity-{group}-sha256-{position}",
                f"{group.replace('-', ' ').title()} identity word {position}",
                value, ONE, ROLE_USER_INPUT, INPUT,
                expression="SHA-256 word over exact typed retained identity",
            ))
    return steps


def _shape(member_id: str, calculation: TraceCalculation) -> MemberShape:
    return MemberShape(
        member_id, calculation.calculation_id, calculation.axes,
        tuple(StepShape(
            item.step_id, item.title, item.unit, item.quantity_role,
            item.source, tuple(dep.step_id for dep in item.dependencies))
              for item in calculation.steps),
    )


def _type_identity(value: Any) -> tuple[str, str]:
    return type(value).__module__, type(value).__qualname__


def _invalid_identity_payload(candidate: Mapping[str, Any]) -> Any:
    """Project invalid evidence without reading arbitrary failure-only values."""

    safe_keys = tuple(
        key for key in candidate
        if key not in {"partial_factors", "t0_days", "elements"}
    )
    factors = candidate["partial_factors"]
    element_shapes = tuple(
        (
            _type_identity(record),
            tuple(
                (
                    ("text", key) if type(key) is str
                    else ("typed-key", *_type_identity(key)),
                    _type_identity(value),
                )
                for key, value in record.items()
            ) if type(record) is dict else (),
        )
        for record in candidate["elements"]
    )
    return {
        "safe_values": tuple((key, candidate[key]) for key in safe_keys),
        "partial_factor_shape": tuple(
            (key, _type_identity(factors[key])) for key in factors),
        "t0_days_type": _type_identity(candidate["t0_days"]),
        "element_shapes": element_shapes,
    }


def _invalid_member(
    candidate: Mapping[str, Any], context: Mapping[str, Any],
) -> tuple[MemberShape, TraceCalculation]:
    """Build minimal failed evidence without traversing success-only input."""

    steps = []
    identity = _invalid_identity_payload(candidate)
    for position, value in enumerate(_digest_parts(identity), start=1):
        steps.append(_step(
            f"invalid-payload-sha256-{position}",
            f"Exact retained invalid-payload identity word {position}",
            value, ONE, ROLE_METHOD_VALUE, BOUNDARY,
            expression=(
                "SHA-256 word over safe invalid values plus failure-only "
                "inventory/type structure")))
    controls = (
        ("fatigue-enabled", "Fatigue enabled", 1.0),
        ("reinforcement-requested", "Reinforcement fatigue requested", 1.0),
        ("concrete-requested", "Concrete fatigue requested",
         float(candidate["checks"]["concrete"])),
    )
    for step_id, title, value in controls:
        steps.append(_step(
            step_id, title, value, ONE, ROLE_USER_INPUT, INPUT))
    control_steps = tuple(steps[-3:])
    error_count = _step(
        "invalid-error-count", "Retained validation error count",
        float(len(candidate["errors"])), ONE, ROLE_COMPUTED, BOUNDARY,
        control_steps, expression="Count ordered fresh validation errors")
    warning_count = _step(
        "invalid-warning-count", "Retained validation warning count",
        float(len(candidate["warnings"])), ONE, ROLE_COMPUTED, BOUNDARY,
        control_steps, expression="Count ordered fresh validation warnings")
    steps.extend((error_count, warning_count))
    for kind, items, count_step in (
        ("error", candidate["errors"], error_count),
        ("warning", candidate["warnings"], warning_count),
    ):
        for position, message in enumerate(items, start=1):
            token = trace_identity_token(message)
            steps.append(_step(
                f"invalid-{kind}-{position}-{token}",
                f"Retained {kind} {position} identity",
                _digest_parts((position, message))[0], ONE, ROLE_COMPUTED,
                BOUNDARY, (count_step,),
                expression=f"Bind ordered retained {kind} text"))
    final_id = "reinforcement-fatigue-invalid-result"
    reason = "Retained fatigue input failure: " + " | ".join(
        candidate["errors"])
    final = TraceStep(
        step_id=final_id,
        title="Reinforcement fatigue invalid state",
        dependencies=tuple(
            TraceDependency(item.step_id, item.unit) for item in steps),
        quantity_role=ROLE_FINAL,
        source=VERDICT,
        symbol=final_id,
        unit=ONE,
        actual_expression=(
            "Publish calculation-free failed state from genuine retained "
            "validation errors"),
        substituted_expression=(
            f"{final_id} = failed ({len(candidate['errors'])} errors)"),
        result=TraceResult(RESULT_FAILED, None, reason),
    )
    steps.append(final)
    axes = context_axes(
        context,
        fatigue_branch="invalid",
        edition=trace_identity_token(candidate["edition"]),
    )
    calculation_id = f"ct-010-{context_id(context)}-reinforcement-invalid"
    calculation = TraceCalculation(
        calculation_id=calculation_id,
        coverage_id=COVERAGE_ID,
        title="Retained reinforcement fatigue input failure",
        method_id=METHOD_ID,
        axes=axes,
        final_step_id=final_id,
        steps=tuple(steps),
        warnings=tuple(candidate["warnings"]),
        assumptions=(
            "This is calculation-free retained adapter failure evidence; no resistance, utilisation or engineering verdict is implied.",
            "Success-only geometry, material and solver fields are not traversed on this branch.",
        ),
    )
    shape = _shape("reinforcement-fatigue-invalid", calculation)
    return shape, calculation


def _property_steps(
    assessment: AssessmentReplay, sn_source, proof_source,
) -> list[TraceStep]:
    p = assessment.properties
    values = (
        ("n-star", "S-N knee cycles", p.n_star, CYCLES, sn_source),
        ("k1", "Upper S-N exponent", p.k1, ONE, sn_source),
        ("k2", "Lower S-N exponent", p.k2, ONE, sn_source),
        ("delta-sigma-rsk", "Characteristic reference range",
         p.delta_sigma_rsk_mpa, MPA, sn_source),
        ("fytk", "Characteristic proof stress", p.fytk_mpa, MPA,
         proof_source),
        ("fyck", "Characteristic compression proof stress",
         p.fyck_mpa if p.fyck_mpa is not None else p.fytk_mpa, MPA,
         proof_source),
        ("diameter", "Element diameter", p.diameter_mm, TraceUnit("mm", "length"),
         BOUNDARY),
    )
    return [
        _step(step_id, title, value, unit, ROLE_METHOD_VALUE, source,
              warning=(
                  f"Project-defined S-N source: {assessment.detail['source']}"
                  if step_id == "delta-sigma-rsk"
                  and assessment.detail["custom"] else None))
        for step_id, title, value, unit, source in values
    ]


def _bin_steps(
    bin_replay: BinReplay,
    position: int,
    properties: Mapping[str, TraceStep],
    sn_source,
    proof_source,
) -> list[TraceStep]:
    prefix = f"bin-{position + 1}"
    values = bin_replay.values
    identity = _step(
        f"{prefix}-identity", "Matched bin identity",
        _digest_parts((position, bin_replay.input_bin.name,
                       bin_replay.input_bin.description))[0],
        ONE, ROLE_USER_INPUT, INPUT)
    cycles = _step(
        f"{prefix}-cycles", "Cycle count", values["cycles"], CYCLES,
        ROLE_USER_INPUT, INPUT)
    matched = _step(
        f"{prefix}-matched-state", "Matched solver-state convergence",
        values["converged"], ONE, ROLE_COMPUTED, ELASTIC,
        (identity, cycles), expression="Bind exact input/state/reported bin join")
    steps = [identity, cycles, matched]
    by_id = {item.step_id: item for item in steps}
    cycles = by_id[f"{prefix}-cycles"]
    matched = by_id[f"{prefix}-matched-state"]

    def add(name, title, value, unit, deps, source=ELASTIC, expression="Replay retained solver intermediate"):
        item = _step(
            f"{prefix}-{name}", title, values[value], unit, ROLE_COMPUTED,
            source, tuple(deps), expression=expression)
        steps.append(item)
        by_id[item.step_id] = item
        return item

    long_stress = add("long-stress", "Long-term stress", "long_stress", MPA,
                      (matched,))
    elastic_total = add("elastic-total-stress", "Elastic total stress",
                        "elastic_total", MPA, (matched,))
    fatigue_total = add("fatigue-total-stress", "Bond-adjusted total stress",
                        "fatigue_total", MPA, (matched,))
    design_total = add("design-total-stress", "Design total stress",
                       "design_total", MPA,
                       (matched, properties["gamma-ff"]))
    elastic_range = add(
        "elastic-range", "Elastic stress range", "elastic_range", MPA,
        (elastic_total, long_stress),
        expression="abs(sigma_total,elastic - sigma_long)")
    stress_range = add(
        "stress-range", "Bond-adjusted stress range", "stress_range", MPA,
        (fatigue_total, long_stress),
        expression="abs(sigma_total,fatigue - sigma_long)")
    bond = add(
        "bond-factor", "Bond adjustment", "bond_factor", ONE,
        (stress_range, elastic_range), BOUNDARY,
        "delta_sigma_fatigue / delta_sigma_elastic")
    design_range = add(
        "design-range", "Design stress range", "design_range", MPA,
        (design_total, long_stress, bond),
        expression="abs(sigma_design - sigma_long)")
    design_resistance = _step(
        f"{prefix}-delta-sigma-rd", "Design reference stress range",
        bin_replay.reported.delta_sigma_rd_mpa, MPA, ROLE_COMPUTED,
        sn_source,
        (properties["delta-sigma-rsk"], properties["gamma-s"]),
        expression="delta_sigma_Rd = delta_sigma_Rsk / gamma_s")
    steps.append(design_resistance)
    slope = add(
        "sn-slope", "Selected S-N exponent", "sn_slope", ONE,
        (design_range, design_resistance, properties["k1"],
         properties["k2"]), sn_source,
        "k1 above the design knee, otherwise k2")
    log_life = add(
        "log-life", "Logarithmic fatigue life", "log_life", ONE,
        (design_range, properties["n-star"], design_resistance, slope),
        sn_source,
        "log10(N)=log10(N*)+k log10(delta_sigma_Rsk/(gamma_s delta_sigma_Ed))")
    life = add(
        "life", "Cycles to failure", "life", CYCLES, (log_life,), sn_source,
        "N=10**log10(N)")
    add(
        "damage", "Miner damage", "damage", ONE, (cycles, life), VERDICT,
        "D=n/N")
    governing_stress = add(
        "governing-proof-stress", "Governing absolute proof stress",
        "governing_stress", MPA, (long_stress, design_total), proof_source,
        "Select the larger absolute long/design proof utilisation")
    proof_limit = add(
        "proof-limit", "Design proof limit", "proof_limit", MPA,
        (governing_stress, properties["fytk"], properties["fyck"],
         properties["gamma-s"]),
        proof_source, "fyk/gamma_s with sign-specific strength")
    add(
        "proof-utilisation", "Absolute proof utilisation",
        "proof_utilisation", ONE, (governing_stress, proof_limit),
        proof_source, "abs(sigma_governing)/fyd")
    return steps


def _member(
    inp: Mapping[str, Any], replay: SuccessfulReplay,
    assessment: AssessmentReplay, context: Mapping[str, Any],
) -> tuple[MemberShape, TraceCalculation]:
    detail = assessment.detail
    sn_source, proof_source = selected_sources(
        replay.prepared.edition, assessment.properties.kind, detail["custom"])
    steps = _identity_steps(_identity_payloads(inp, replay))
    properties = _property_steps(assessment, sn_source, proof_source)
    properties.extend((
        _step("gamma-s", "Reinforcement fatigue partial factor",
              replay.prepared.gamma_s, ONE, ROLE_USER_INPUT, INPUT),
        _step("gamma-ff", "Fatigue action factor",
              replay.prepared.gamma_ff, ONE, ROLE_USER_INPUT, INPUT),
    ))
    steps.extend(properties)
    property_map = {item.step_id: item for item in properties}
    for position, item in enumerate(assessment.bins):
        steps.extend(_bin_steps(
            item, position, property_map, sn_source, proof_source))

    bin_damage = [item for item in steps if item.step_id.endswith("-damage")]
    bin_proof = [
        item for item in steps if item.step_id.endswith("-proof-utilisation")]
    bin_state = [item for item in steps if item.step_id.endswith("-matched-state")]
    damage = _step(
        "assessment-damage", "Accumulated Miner damage", assessment.damage,
        ONE, ROLE_COMPUTED, VERDICT, tuple(bin_damage), expression="sum(D_i)")
    damage_governor = _step(
        "governing-damage-bin", "Governing damage-bin position",
        float(next(index for index, item in enumerate(assessment.bins, 1)
                   if item.state.name == assessment.governing_damage_bin)),
        ONE, ROLE_COMPUTED, VERDICT, tuple(bin_damage),
        expression="argmax(D_i), first tie in input order")
    proof = _step(
        "assessment-proof-utilisation", "Governing proof utilisation",
        assessment.proof_utilisation, ONE, ROLE_COMPUTED, VERDICT,
        tuple(bin_proof), expression="max(U_proof,i)")
    proof_governor = _step(
        "governing-proof-bin", "Governing proof-bin position",
        float(next(index for index, item in enumerate(assessment.bins, 1)
                   if item.state.name == assessment.governing_proof_bin)),
        ONE, ROLE_COMPUTED, VERDICT, tuple(bin_proof),
        expression="argmax(U_proof,i), first tie in input order")
    converged = _step(
        "assessment-converged", "Assessment convergence",
        float(assessment.converged), ONE, ROLE_COMPUTED, VERDICT,
        tuple(bin_state), expression="all(matched bin convergence)")
    passed = _step(
        "assessment-passed", "Assessment PASS state", float(assessment.passed),
        ONE, ROLE_COMPUTED, VERDICT, (damage, proof, converged),
        expression="converged and damage<=1 and proof<=1")
    steps.extend((damage, damage_governor, proof, proof_governor,
                  converged, passed))
    final = _step(
        "reinforcement-fatigue-result", "Reinforcement fatigue utilisation",
        assessment.utilisation, ONE, ROLE_FINAL, VERDICT, tuple(steps),
        expression="max(accumulated damage, absolute proof utilisation)")
    steps.append(final)

    axes = context_axes(
        context,
        spectrum=assessment.spectrum_name,
        element=assessment.properties.element_id,
        kind=assessment.properties.kind,
        detail=assessment.properties.detail_id,
    )
    token = (
        f"spectrum-{trace_identity_token(assessment.spectrum_name)}."
        f"element-{trace_identity_token(assessment.properties.element_id)}")
    calculation_id = f"ct-010-{token}"
    member_id = f"reinforcement-fatigue-{token}"
    shape = MemberShape(
        member_id, calculation_id, axes,
        tuple(StepShape(
            item.step_id, item.title, item.unit, item.quantity_role,
            item.source, tuple(dep.step_id for dep in item.dependencies))
              for item in steps),
    )
    assumptions = [
        "The trace independently replays retained grouped-spectrum reinforcement mechanics; it does not introduce a second solver.",
        "Stress values are MPa, cycle counts are user-supplied, and PASS requires genuine convergence plus both damage and proof utilisation not exceeding one.",
    ]
    if detail["custom"]:
        assumptions.append(
            "The assigned S-N detail is project-defined/uncited; its retained source text is disclosed without a standards citation.")
    return shape, TraceCalculation(
        calculation_id=calculation_id,
        coverage_id=COVERAGE_ID,
        title=(f"Reinforcement fatigue: {assessment.properties.element_id} / "
               f"{assessment.spectrum_name}"),
        method_id=METHOD_ID,
        axes=axes,
        final_step_id=final.step_id,
        steps=tuple(steps),
        warnings=tuple(replay.prepared.warnings),
        assumptions=tuple(assumptions),
    )


def _aggregate(
    inp: Mapping[str, Any], replay: SuccessfulReplay,
    context: Mapping[str, Any],
) -> tuple[MemberShape, TraceCalculation]:
    steps = _identity_steps(_identity_payloads(inp, replay))
    identity_steps = tuple(steps)
    assessments = [
        item for spectrum in replay.spectra for item in spectrum.assessments]
    spectrum_groups: list[tuple[str, list[AssessmentReplay]]] = []
    for spectrum in replay.spectra:
        spectrum_groups.append((spectrum.name, list(spectrum.assessments)))

    assessment_steps: dict[tuple[int, int], tuple[TraceStep, TraceStep, TraceStep]] = {}
    for item in assessments:
        prefix = f"spectrum-{item.spectrum_position + 1}-element-{item.element_position + 1}"
        util = _step(
            f"{prefix}-utilisation", "Assessment utilisation",
            item.utilisation, ONE, ROLE_COMPUTED, VERDICT,
            identity_steps,
            expression="Replayed max(damage, proof utilisation)")
        converged = _step(
            f"{prefix}-converged", "Assessment convergence",
            float(item.converged), ONE, ROLE_COMPUTED, VERDICT,
            identity_steps, expression="all(matched bin convergence)")
        passed = _step(
            f"{prefix}-passed", "Assessment PASS state", float(item.passed),
            ONE, ROLE_COMPUTED, VERDICT, (util, converged),
            expression="converged and utilisation<=1")
        steps.extend((util, converged, passed))
        assessment_steps[(item.spectrum_position, item.element_position)] = (
            util, converged, passed)

    spectrum_rows = []
    for spectrum_position, (name, items) in enumerate(spectrum_groups):
        triples = [assessment_steps[
            (item.spectrum_position, item.element_position)] for item in items]
        governing = max(items, key=lambda item: item.utilisation)
        prefix = f"spectrum-{spectrum_position + 1}"
        identity = _step(
            f"{prefix}-identity", "Spectrum identity",
            _digest_parts((spectrum_position, name))[0], ONE,
            ROLE_USER_INPUT, INPUT)
        steps.append(identity)
        governor = _step(
            f"{prefix}-governing-element", "Governing element position",
            float(governing.element_position + 1), ONE, ROLE_COMPUTED,
            VERDICT, tuple(row[0] for row in triples),
            expression="argmax(assessment utilisation), first tie in element order")
        util = _step(
            f"{prefix}-utilisation", "Spectrum reinforcement utilisation",
            governing.utilisation, ONE, ROLE_COMPUTED, VERDICT,
            tuple(row[0] for row in triples) + (governor,),
            expression="max(assessment utilisation)")
        converged = _step(
            f"{prefix}-converged", "Spectrum reinforcement convergence",
            float(all(item.converged for item in items)), ONE, ROLE_COMPUTED,
            VERDICT, tuple(row[1] for row in triples),
            expression="all(assessment convergence)")
        passed = _step(
            f"{prefix}-passed", "Spectrum reinforcement PASS state",
            float(all(item.passed for item in items)), ONE, ROLE_COMPUTED,
            VERDICT, tuple(row[2] for row in triples) + (util, converged),
            expression="all(assessment PASS)")
        steps.extend((governor, util, converged, passed))
        spectrum_rows.append((identity, governor, util, converged, passed))

    governing = max(assessments, key=lambda item: item.utilisation)
    global_spectrum = _step(
        "global-governing-spectrum", "Global governing spectrum position",
        float(governing.spectrum_position + 1), ONE, ROLE_COMPUTED, VERDICT,
        tuple(row[2] for row in spectrum_rows),
        expression="argmax(spectrum utilisation), first tie in spectrum order")
    global_element = _step(
        "global-governing-element", "Global governing element position",
        float(governing.element_position + 1), ONE, ROLE_COMPUTED, VERDICT,
        tuple(row[1] for row in spectrum_rows) + (global_spectrum,),
        expression="governing element within governing spectrum")
    utilisation = _step(
        "global-utilisation", "Global reinforcement fatigue utilisation",
        governing.utilisation, ONE, ROLE_COMPUTED, VERDICT,
        tuple(row[2] for row in spectrum_rows)
        + (global_spectrum, global_element,), expression="max(spectrum utilisation)")
    converged = _step(
        "global-converged", "Global reinforcement fatigue convergence",
        float(all(item.converged for item in assessments)), ONE,
        ROLE_COMPUTED, VERDICT, tuple(row[3] for row in spectrum_rows),
        expression="all(spectrum convergence)")
    passed = _step(
        "global-passed", "Global reinforcement fatigue PASS state",
        float(all(item.passed for item in assessments)), ONE, ROLE_COMPUTED,
        VERDICT, tuple(row[4] for row in spectrum_rows)
        + (utilisation, converged,), expression="all(spectrum PASS)")
    steps.extend((global_spectrum, global_element, utilisation, converged, passed))
    final = _step(
        "reinforcement-fatigue-aggregate-result",
        "Reinforcement fatigue aggregate utilisation", governing.utilisation,
        ONE, ROLE_FINAL, VERDICT, tuple(steps),
        expression="Published reinforcement-only global utilisation and verdict closure")
    steps.append(final)
    axes = context_axes(context, scope="reinforcement")
    calculation_id = f"ct-010-{context_id(context)}-reinforcement-aggregate"
    shape = MemberShape(
        "reinforcement-fatigue-aggregate", calculation_id, axes,
        tuple(StepShape(
            item.step_id, item.title, item.unit, item.quantity_role,
            item.source, tuple(dep.step_id for dep in item.dependencies))
              for item in steps),
    )
    return shape, TraceCalculation(
        calculation_id=calculation_id,
        coverage_id=COVERAGE_ID,
        title="Reinforcement fatigue aggregate",
        method_id=METHOD_ID,
        axes=axes,
        final_step_id=final.step_id,
        steps=tuple(steps),
        warnings=tuple(replay.prepared.warnings),
        assumptions=(
            "The aggregate is reinforcement-only; concrete fatigue values are explicitly outside CT-010a.",
            "Every spectrum/element utilisation, convergence state and PASS state is independently retained before governing selection.",
        ),
    )


def _expected_bundle(
    inp: Mapping[str, Any], out: Mapping[str, Any], *, input_sha256: str,
    result_sha256: str, context: Mapping[str, Any] | None,
) -> TraceBundle | None:
    state, candidate = classify(inp, out)
    if state == "none":
        return None
    trace_context = {} if context is None else context
    if state == "invalid":
        shape, calculation = _invalid_member(candidate, trace_context)
        bundle = create_bundle(
            input_sha256=input_sha256,
            result_sha256=result_sha256,
            calculations=(calculation,),
        )
        audit_trace_registry(bundle, invalid_registry(shape))
        return bundle
    replay = successful_replay(inp, candidate)
    if not replay.prepared.check_reinforcement:
        return None
    members = [
        _member(inp, replay, assessment, trace_context)
        for spectrum in replay.spectra for assessment in spectrum.assessments]
    members.append(_aggregate(inp, replay, trace_context))
    shapes = tuple(item[0] for item in members)
    bundle = create_bundle(
        input_sha256=input_sha256,
        result_sha256=result_sha256,
        calculations=tuple(item[1] for item in members),
    )
    audit_trace_registry(bundle, registry_for(shapes))
    return bundle


def build_fatigue_trace_family(
    inp: Mapping[str, Any], out: Mapping[str, Any], *, input_sha256: str,
    result_sha256: str, context: Mapping[str, Any] | None = None,
) -> TraceBundle | None:
    """Build successful reinforcement traces after failure-first replay."""

    try:
        return _expected_bundle(
            inp, out, input_sha256=input_sha256,
            result_sha256=result_sha256, context=context)
    except TraceValidationError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"invalid CT-010a evidence: {exc}") from exc


def validate_fatigue_trace_family(
    bundle: TraceBundle | dict[str, Any] | None,
    inp: Mapping[str, Any], out: Mapping[str, Any], *, input_sha256: str,
    result_sha256: str, context: Mapping[str, Any] | None = None,
) -> TraceBundle | None:
    """Reject stale or coherently resealed CT-010a evidence."""

    expected = _expected_bundle(
        inp, out, input_sha256=input_sha256,
        result_sha256=result_sha256, context=context)
    if expected is None:
        if bundle is not None:
            raise TraceValidationError(
                "inactive/invalid reinforcement fatigue cannot carry a trace")
        return None
    if bundle is None:
        raise TraceValidationError("successful reinforcement fatigue trace is missing")
    candidate = validate_bundle(
        bundle, expected_input_sha256=input_sha256,
        expected_result_sha256=result_sha256)
    expected_shapes = tuple(
        _shape(f"expected-member-{position}", calculation)
        for position, calculation in enumerate(expected.calculations, 1)
    )
    final_states = tuple(
        calculation.steps[-1].result.state
        for calculation in expected.calculations)
    if final_states == (RESULT_FAILED,):
        audit_trace_registry(candidate, invalid_registry(expected_shapes[0]))
    else:
        audit_trace_registry(candidate, registry_for(expected_shapes))
    if candidate.to_dict() != expected.to_dict():
        raise TraceValidationError(
            "CT-010a trace differs from authoritative input replay")
    return candidate


__all__ = (
    "FAMILY_ID", "build_fatigue_trace_family",
    "validate_fatigue_trace_family",
)
