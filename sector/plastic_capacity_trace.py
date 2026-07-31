"""Unpublished solver-owned CT-002 selected plastic-capacity trace."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from . import combined
from .calculation_trace import (
    RESULT_FAILED,
    RESULT_FINITE,
    RESULT_NEGATIVE_INFINITY,
    RESULT_POSITIVE_INFINITY,
    TraceCalculation,
    TraceDependency,
    TraceResult,
    TraceStep,
    TraceValidationError,
    create_bundle,
)
from .plastic import (
    PLASTIC_AXIAL_TOLERANCE_FACTOR,
    PLASTIC_INTEGRATION_BANDS,
    PlasticPoint,
    solve_plastic,
)
from .plastic_capacity_trace_contract import (
    ACTION_KEYS,
    BRANCH_FAILED_SELECTED,
    BRANCH_FAILED_UNSELECTED,
    BRANCH_FINITE_SELECTED,
    COVERAGE_ID,
    POINT_FIELDS,
    SWEEP_KEYS,
    SweepPlan,
    TraceShape,
    action_step_id,
    expected_registry,
    expected_step_contract,
    expected_sweep,
    material_items,
    material_vector_id,
    member_identity_id,
    point_step_id,
    sweep_step_id,
    trace_shape,
)
from .section_trace_blocks import SectionTraceBlocks, section_trace_blocks
from .trace_registry import TraceRegistryContract, audit_trace_registry


_PROBE_SHA256 = "0" * 64
_FAILURE_REASON = (
    "plastic solver did not converge for every retained envelope member"
)


@dataclass(frozen=True, slots=True)
class PlasticCapacityTraceFamily:
    """One audited CT-002 candidate and its independent exact registry."""

    calculation: TraceCalculation
    registry: TraceRegistryContract


@dataclass(frozen=True, slots=True)
class _Evidence:
    blocks: SectionTraceBlocks
    sweep: SweepPlan
    points: tuple[Mapping[str, Any], ...]
    convergence: tuple[bool, ...]
    selected_index: int | None
    radial: combined.RadialUtilResult
    branch: str


def _sequence(value: Any, label: str) -> tuple[Any, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TraceValidationError(f"{label} must be a retained sequence")
    return tuple(value)


def _number(value: Any, label: str, *, extended: bool = False) -> float:
    if type(value) not in {int, float} or type(value) is bool:
        raise TraceValidationError(f"{label} must be a non-Boolean number")
    number = float(value)
    if math.isnan(number) or (not extended and not math.isfinite(number)):
        raise TraceValidationError(f"{label} must be finite")
    return number


def _close(actual: float, expected: float) -> bool:
    if math.isinf(actual) or math.isinf(expected):
        return actual == expected
    return math.isclose(actual, expected, rel_tol=1.0e-12, abs_tol=1.0e-9)


def _require_close(actual: Any, expected: float, label: str, *, extended=False) -> float:
    number = _number(actual, label, extended=extended)
    if not _close(number, float(expected)):
        raise TraceValidationError(
            f"{label} is inconsistent: retained {number!r}, "
            f"expected {expected!r}"
        )
    return number


def _point_values(point: PlasticPoint) -> dict[str, float | bool]:
    values = {
        field: getattr(point, field)
        for field in POINT_FIELDS
        if hasattr(point, field)
    }
    values.update(
        kappa=point.curvature,
        na_x=point.na_x_intercept,
        na_y=point.na_y_intercept,
        eps_c=-point.eps_concrete,
        eps_s=-point.eps_steel,
        eps_s_comp=-point.eps_steel_comp,
        eps_cable=-point.eps_cable,
        achieved_axial=point.axial,
        comp_force=point.compression_force,
        comp_mx=point.compression_mx,
        comp_my=point.compression_my,
        lever=point.lever_arm,
    )
    return values


def _validate_finite_point(
    retained: Mapping[str, Any],
    authoritative: PlasticPoint,
    *,
    index: int,
    mx: float,
    my: float,
) -> None:
    label = f"plastic point {index}"
    if set(retained) != set(POINT_FIELDS):
        missing = sorted(set(POINT_FIELDS) - set(retained))
        extra = sorted(str(item) for item in set(retained) - set(POINT_FIELDS))
        details = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if extra:
            details.append(f"unexpected {', '.join(extra)}")
        raise TraceValidationError(f"{label} fields: {'; '.join(details)}")
    expected = _point_values(authoritative)
    for field in POINT_FIELDS:
        if field == "converged":
            if type(retained[field]) is not bool or retained[field] is not expected[field]:
                raise TraceValidationError(
                    f"{label} convergence contradicts the authoritative search"
                )
            continue
        _require_close(
            retained[field],
            expected[field],
            f"{label} {field}",
            extended=field in {"na_x", "na_y"},
        )
    _require_close(mx, authoritative.Mx, f"{label} aligned Mx")
    _require_close(my, authoritative.My, f"{label} aligned My")


def _replay(inp: Mapping[str, Any], blocks: SectionTraceBlocks, sweep: SweepPlan):
    prestress = inp.get("prestress") if blocks.geometry.tendons else None
    try:
        return tuple(
            solve_plastic(
                inp["section"],
                inp["concrete"],
                inp["steel"],
                -dict(blocks.plastic_actions.values)["P_pl"],
                sweep.solver_min,
                sweep.solver_max,
                sweep.solver_increment,
                prestress=prestress,
                bar_materials=inp.get("bar_materials"),
                tendon_materials=inp.get("tendon_materials"),
                n_bands=PLASTIC_INTEGRATION_BANDS,
            )
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"CT-002 authoritative sweep replay: {exc}") from exc


def _evidence(inp: Mapping[str, Any], out: Mapping[str, Any]) -> _Evidence:
    if not isinstance(inp, Mapping) or not isinstance(out, Mapping):
        raise TraceValidationError("CT-002 input and result must be mappings")
    try:
        blocks = section_trace_blocks(inp)
        sweep = expected_sweep(inp["v_min"], inp["v_max"], inp["v_inc"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"CT-002 shared input evidence: {exc}") from exc
    if len(blocks.geometry.bars) != len(blocks.bars):
        raise TraceValidationError("CT-002 bar geometry/law cardinalities differ")
    if len(blocks.geometry.tendons) != len(blocks.tendons):
        raise TraceValidationError("CT-002 tendon geometry/law cardinalities differ")

    result = out.get("plastic")
    if not isinstance(result, Mapping):
        raise TraceValidationError("CT-002 needs one retained plastic result")
    points = _sequence(result.get("points"), "plastic points")
    if len(points) != len(sweep.angles) or not points:
        raise TraceValidationError(
            "plastic points and requested sweep need exact cardinality"
        )
    if result.get("closed") is not sweep.closed or not sweep.closed:
        raise TraceValidationError("CT-002 needs the exact requested closed sweep")
    if result.get("check_util") is not True:
        raise TraceValidationError("CT-002 needs an enabled radial check")

    angles = []
    convergence = []
    for index, point in enumerate(points):
        if not isinstance(point, Mapping):
            raise TraceValidationError(f"plastic point {index} must be a mapping")
        angles.append(_number(point.get("V"), f"plastic point {index} V"))
        flag = point.get("converged")
        if type(flag) is not bool:
            raise TraceValidationError(
                f"plastic point {index} converged must be Boolean"
            )
        convergence.append(flag)
    if tuple(angles) != sweep.angles:
        raise TraceValidationError(
            "plastic retained angle identities contradict the requested sweep"
        )
    if len(set(angles)) != len(angles):
        raise TraceValidationError("plastic points have duplicate member identities")

    replay = _replay(inp, blocks, sweep)
    replay_angles = tuple(float(point.V) for point in replay)
    replay_flags = tuple(point.converged for point in replay)
    if replay_angles != sweep.angles:
        raise TraceValidationError(
            "authoritative member identities contradict the requested sweep"
        )
    envelope_converged = result.get("converged")
    if type(envelope_converged) is not bool:
        raise TraceValidationError("plastic envelope convergence must be Boolean")
    if envelope_converged is not all(convergence):
        raise TraceValidationError(
            "plastic envelope convergence masks a retained member state"
        )
    if not envelope_converged and replay_flags != tuple(convergence):
        raise TraceValidationError(
            "retained failure convergence contradicts the authoritative search"
        )

    if "util_gov" not in result:
        raise TraceValidationError("util_gov is required even when no member exists")
    raw_selected = result["util_gov"]
    if raw_selected is not None and (
        type(raw_selected) is not int
        or type(raw_selected) is bool
        or raw_selected < 0
        or raw_selected >= len(points)
    ):
        raise TraceValidationError(
            "util_gov must be absent or a non-Boolean in-range integer"
        )
    actions = dict(blocks.plastic_actions.values)
    authoritative_mx = tuple(point.Mx for point in replay)
    authoritative_my = tuple(point.My for point in replay)
    try:
        radial = combined.radial_util_result(
            authoritative_mx,
            authoritative_my,
            actions["Mx_pl"],
            actions["My_pl"],
        )
    except (TypeError, ValueError) as exc:
        raise TraceValidationError(f"CT-002 authoritative radial selector: {exc}") from exc
    if raw_selected != radial.governing_index:
        raise TraceValidationError(
            "plastic util_gov contradicts the authoritative envelope selection"
        )

    if envelope_converged:
        if raw_selected is None:
            raise TraceValidationError(
                "finite-selected CT-002 needs an authoritative selected member"
            )
        mx_raw = _sequence(result.get("mx"), "plastic mx")
        my_raw = _sequence(result.get("my"), "plastic my")
        if len(mx_raw) != len(points) or len(my_raw) != len(points):
            raise TraceValidationError(
                "finite plastic points and arrays need exact cardinality"
            )
        mx = tuple(
            _number(value, f"plastic mx member {i}")
            for i, value in enumerate(mx_raw)
        )
        my = tuple(
            _number(value, f"plastic my member {i}")
            for i, value in enumerate(my_raw)
        )
        for index, (retained, authoritative) in enumerate(zip(points, replay)):
            _validate_finite_point(
                retained,
                authoritative,
                index=index,
                mx=mx[index],
                my=my[index],
            )
        applied = _sequence(result.get("applied"), "plastic applied action")
        if len(applied) != 2:
            raise TraceValidationError("plastic applied action needs Mx and My")
        _require_close(applied[0], actions["Mx_pl"], "plastic applied Mx")
        _require_close(applied[1], actions["My_pl"], "plastic applied My")
        demand = _require_close(
            result.get("demand"), radial.demand, "plastic radial demand"
        )
        if radial.resistance is None:
            raise TraceValidationError("finite-selected CT-002 needs resistance")
        resistance = _require_close(
            result.get("resistance"),
            radial.resistance,
            "plastic radial resistance",
        )
        utilisation = _require_close(
            result.get("util"), radial.utilisation, "plastic radial utilisation"
        )
        if any(
            not math.isfinite(value) or value <= 0.0
            for value in (demand, resistance, utilisation)
        ):
            raise TraceValidationError(
                "finite-selected CT-002 needs positive finite radial evidence"
            )
        _require_close(
            utilisation,
            demand / resistance,
            "plastic demand/resistance utilisation",
        )
        branch = BRANCH_FINITE_SELECTED
    else:
        # Failed-member moments are deliberately outside the minimal record.
        # Selector identity is authenticated from the authoritative replay, so
        # retained failed arrays/resultants are neither parsed nor trusted.
        mx, my = authoritative_mx, authoritative_my
        branch = (
            BRANCH_FAILED_UNSELECTED
            if raw_selected is None
            else BRANCH_FAILED_SELECTED
        )
    return _Evidence(
        blocks,
        sweep,
        points,
        tuple(convergence),
        raw_selected,
        radial,
        branch,
    )


def _finite_values(evidence: _Evidence, specs) -> dict[str, Any]:
    values: dict[str, Any] = {spec.step_id: 1.0 for spec in specs}
    actions = dict(evidence.blocks.plastic_actions.values)
    values.update((action_step_id(key), actions[key]) for key in ACTION_KEYS)
    requested = {
        "v_min": evidence.sweep.requested_min,
        "v_max": evidence.sweep.requested_max,
        "v_inc": evidence.sweep.requested_increment,
    }
    values.update((sweep_step_id(key), requested[key]) for key in SWEEP_KEYS)
    values["normalised-sweep-plan"] = len(evidence.sweep.angles)
    values.update(
        {
            "solver-integration-bands": PLASTIC_INTEGRATION_BANDS,
            "solver-axial-tolerance-factor": PLASTIC_AXIAL_TOLERANCE_FACTOR,
            "section-input-closure": 1.0,
            "requested-solver-axial": -actions["P_pl"],
        }
    )
    for index, point in enumerate(evidence.points):
        values[member_identity_id(index)] = index
        for field in POINT_FIELDS:
            raw = point[field]
            values[point_step_id(index, field)] = (
                1.0 if raw is True else 0.0 if raw is False else raw
            )
    values.update(
        {
            "selected-member-index": evidence.selected_index,
            "retained-radial-demand": evidence.radial.demand,
            "retained-radial-resistance": evidence.radial.resistance,
            "retained-radial-utilisation": evidence.radial.utilisation,
            "capacity-verdict": 1.0
            if evidence.radial.utilisation <= 1.0 + 1.0e-9
            else 0.0,
            "selected-plastic-capacity-result": evidence.radial.utilisation,
        }
    )
    return values


def _block_substitutions(evidence: _Evidence) -> dict[str, str]:
    geometry = evidence.blocks.geometry
    substitutions = {"geometry-concrete-block": repr(geometry.rings)}
    if geometry.bars:
        substitutions["geometry-bars-block"] = repr(geometry.bars)
    if geometry.tendons:
        substitutions["geometry-tendons-block"] = repr(geometry.tendons)
    substitutions.update(
        (material_vector_id(prefix), repr(block))
        for prefix, block in material_items(evidence.blocks)
    )
    return substitutions


def _failure_values(evidence: _Evidence, specs) -> dict[str, Any]:
    requested = {
        "v_min": evidence.sweep.requested_min,
        "v_max": evidence.sweep.requested_max,
        "v_inc": evidence.sweep.requested_increment,
    }
    values = {spec.step_id: 1.0 for spec in specs}
    values.update((sweep_step_id(key), requested[key]) for key in SWEEP_KEYS)
    values["normalised-sweep-plan"] = len(evidence.sweep.angles)
    for index, (angle, converged) in enumerate(
        zip(evidence.sweep.angles, evidence.convergence)
    ):
        values[member_identity_id(index)] = index
        values[point_step_id(index, "V")] = angle
        values[point_step_id(index, "converged")] = 1.0 if converged else 0.0
    values["failure-count"] = sum(not flag for flag in evidence.convergence)
    values["failure-state"] = None
    if evidence.branch == BRANCH_FAILED_SELECTED:
        values["selected-member-index"] = evidence.selected_index
    values["selected-plastic-capacity-result"] = None
    return values


def _result(step_id: str, value: Any, *, failed: bool) -> TraceResult:
    if failed and step_id in {
        "failure-state",
        "selected-plastic-capacity-result",
    }:
        return TraceResult(RESULT_FAILED, None, _FAILURE_REASON)
    number = _number(value, step_id, extended=True)
    if number == math.inf:
        return TraceResult(
            RESULT_POSITIVE_INFINITY,
            None,
            f"{step_id} is parallel to a coordinate axis",
        )
    if number == -math.inf:
        return TraceResult(
            RESULT_NEGATIVE_INFINITY,
            None,
            f"{step_id} is parallel to a coordinate axis",
        )
    return TraceResult(RESULT_FINITE, number)


def _calculation(evidence: _Evidence, shape: TraceShape) -> TraceCalculation:
    specs = expected_step_contract(shape)
    failed = shape.branch != BRANCH_FINITE_SELECTED
    values = (
        _failure_values(evidence, specs)
        if failed
        else _finite_values(evidence, specs)
    )
    substitutions = {} if failed else _block_substitutions(evidence)
    steps = []
    by_id = {}
    passed = evidence.radial.utilisation <= 1.0 + 1.0e-9
    for spec in specs:
        dependencies = tuple(
            TraceDependency(step_id, by_id[step_id].unit)
            for step_id in spec.dependencies
        )
        warnings = ()
        if failed and spec.step_id in {
            "failure-state",
            "selected-plastic-capacity-result",
        }:
            warnings = (_FAILURE_REASON,)
        elif not failed and not passed and spec.step_id in {
            "capacity-verdict",
            "selected-plastic-capacity-result",
        }:
            warnings = ("Demand exceeds retained radial resistance.",)
        value = values[spec.step_id]
        substituted = substitutions.get(
            spec.step_id,
            "failed" if value is None else repr(value),
        )
        step = TraceStep(
            step_id=spec.step_id,
            title=spec.step_id.replace("-", " ").title(),
            dependencies=dependencies,
            quantity_role=spec.quantity_role,
            source=spec.source,
            symbol=spec.step_id,
            unit=spec.unit,
            actual_expression="authoritative retained calculation evidence",
            substituted_expression=substituted,
            result=_result(spec.step_id, value, failed=failed),
            warnings=warnings,
        )
        steps.append(step)
        by_id[step.step_id] = step
    warnings = (_FAILURE_REASON,) if failed else (() if passed else steps[-1].warnings)
    assumptions = (
        (
            "Finite evidence is matched to an exact authoritative solver sweep replay.",
            "Shared geometry, action, material, and provenance blocks are referenced once.",
        )
        if not failed
        else (
            "Failure evidence is limited to sweep identity and genuine convergence state.",
        )
    )
    return TraceCalculation(
        calculation_id=shape.calculation_id,
        coverage_id=COVERAGE_ID,
        title="Selected plastic section capacity",
        method_id=evidence.blocks.plastic_method_id,
        axes=shape.axes,
        final_step_id="selected-plastic-capacity-result",
        steps=tuple(steps),
        warnings=warnings,
        assumptions=assumptions,
    )


def build_plastic_capacity_trace_family(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    context: Mapping[str, Any],
) -> PlasticCapacityTraceFamily:
    """Build and self-audit the exact CT-002 finite or minimal failure branch."""

    if not isinstance(context, Mapping):
        raise TraceValidationError("CT-002 context must be a mapping")
    evidence = _evidence(inp, out)
    try:
        shape = trace_shape(
            evidence.blocks,
            context,
            expected_angles=evidence.sweep.angles,
            branch=evidence.branch,
            selected_index=evidence.selected_index,
        )
        calculation = _calculation(evidence, shape)
        registry = expected_registry(shape)
    except TraceValidationError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"CT-002 trace construction: {exc}") from exc
    probe = create_bundle(
        input_sha256=_PROBE_SHA256,
        result_sha256=_PROBE_SHA256,
        calculations=(calculation,),
    )
    audit_trace_registry(probe, registry)
    return PlasticCapacityTraceFamily(probe.calculations[0], registry)
