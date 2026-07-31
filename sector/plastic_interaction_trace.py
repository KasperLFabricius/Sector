"""Solver-owned unpublished CT-003 radial and CT-004 interaction traces."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .calculation_trace import (
    RESULT_FAILED,
    RESULT_FINITE,
    TraceBundle,
    TraceCalculation,
    TraceDependency,
    TraceResult,
    TraceStep,
    TraceValidationError,
    create_bundle,
    validate_bundle,
)
from .combined import RadialUtilResult, radial_util_result
from .plastic import InteractionPoint, PlasticPoint, solve_interaction, solve_plastic
from .plastic_capacity_trace_contract import SweepPlan, expected_sweep
from .plastic_interaction_trace_contract import (
    INTERACTION_ANGLES,
    INTERACTION_BRANCH_CARDINALITY,
    INTERACTION_CARDINALITY,
    INTERACTION_COVERAGE_ID,
    INTERACTION_FAILED,
    INTERACTION_FINITE,
    INTERACTION_INTERVALS,
    RADIAL_COVERAGE_ID,
    RADIAL_FAILED_SELECTOR,
    RADIAL_FAILED_SWEEP,
    RADIAL_FINITE_SELECTED,
    RADIAL_FINITE_ZERO,
    AxisTraceShape,
    RadialTraceShape,
    StepSpec,
    action_step_id,
    axis_step_contract,
    axis_trace_shape,
    expected_registry,
    interaction_member_step_id,
    material_step_id,
    radial_member_step_id,
    radial_step_contract,
    radial_trace_shape,
    sweep_step_id,
)
from .section_trace_blocks import SectionTraceBlocks, section_trace_blocks
from .trace_registry import audit_trace_registry


_RADIAL_SWEEP_FAILURE = (
    "plastic solver did not converge every expected CT-003 radial member"
)
_RADIAL_SELECTOR_FAILURE = (
    "radial selector did not produce a finite resistance and utilisation"
)
_INTERACTION_FAILURE = (
    "plastic solver did not converge every expected CT-004 boundary member"
)


@dataclass(frozen=True, slots=True)
class _RadialEvidence:
    blocks: SectionTraceBlocks
    plan: SweepPlan
    shape: RadialTraceShape
    result: Mapping[str, Any]
    points: tuple[Mapping[str, Any], ...]
    replay: tuple[PlasticPoint, ...]
    convergence: tuple[bool, ...]
    radial: RadialUtilResult


@dataclass(frozen=True, slots=True)
class _AxisEvidence:
    shape: AxisTraceShape
    result: Mapping[str, Any]
    positive: tuple[InteractionPoint, ...]
    negative: tuple[InteractionPoint, ...]
    ordered: tuple[InteractionPoint, ...]
    convergence: tuple[bool, ...]


@dataclass(frozen=True, slots=True)
class _Evidence:
    blocks: SectionTraceBlocks
    radial: _RadialEvidence
    x_axis: _AxisEvidence
    y_axis: _AxisEvidence


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TraceValidationError(f"{label} must be a mapping")
    return value


def _sequence(value: Any, label: str) -> tuple[Any, ...]:
    if type(value) not in {list, tuple}:
        raise TraceValidationError(f"{label} must be an ordered sequence")
    return tuple(value)


def _number(value: Any, label: str) -> float:
    if type(value) not in {int, float} or type(value) is bool:
        raise TraceValidationError(f"{label} must be a finite non-Boolean number")
    converted = float(value)
    if not math.isfinite(converted):
        raise TraceValidationError(f"{label} must be a finite non-Boolean number")
    return converted


def _close(actual: float, expected: float) -> bool:
    return math.isclose(actual, expected, rel_tol=2.0e-9, abs_tol=2.0e-9)


def _require_close(value: Any, expected: float, label: str) -> float:
    actual = _number(value, label)
    if not _close(actual, expected):
        raise TraceValidationError(
            f"{label} contradicts authoritative solver evidence"
        )
    return actual


def _require_flag(value: Any, expected: bool, label: str) -> bool:
    if type(value) is not bool:
        raise TraceValidationError(f"{label} must be Boolean")
    if value is not expected:
        raise TraceValidationError(
            f"{label} contradicts authoritative solver evidence"
        )
    return value


def _require_optional_close(
    value: Any, expected: float | None, label: str
) -> None:
    if expected is None:
        if value is not None:
            raise TraceValidationError(
                f"{label} contradicts authoritative selector evidence"
            )
        return
    _require_close(value, expected, label)


def _require_utilisation(value: Any, expected: float, label: str) -> None:
    if math.isfinite(expected):
        _require_close(value, expected, label)
        return
    if (
        type(value) not in {int, float}
        or type(value) is bool
        or not math.isinf(float(value))
        or float(value) < 0.0
    ):
        raise TraceValidationError(
            f"{label} must retain the authoritative positive-infinite state"
        )


def _require_selection(
    value: Any, expected: int | None, cardinality: int, label: str
) -> None:
    if expected is None:
        if value is not None:
            raise TraceValidationError(
                f"{label} contradicts authoritative selector evidence"
            )
        return
    if (
        type(value) is not int
        or type(value) is bool
        or value < 0
        or value >= cardinality
    ):
        raise TraceValidationError(
            f"{label} must be an exact non-Boolean in-range integer"
        )
    if value != expected:
        raise TraceValidationError(
            f"{label} contradicts authoritative selector evidence"
        )


def _prestress(inp: Mapping[str, Any]) -> Any:
    section = inp["section"]
    return inp.get("prestress") if section.tendons else None


def _replay_radial(
    inp: Mapping[str, Any],
    blocks: SectionTraceBlocks,
    plan: SweepPlan,
) -> tuple[PlasticPoint, ...]:
    actions = dict(blocks.plastic_actions.values)
    points = solve_plastic(
        inp["section"],
        inp["concrete"],
        inp["steel"],
        -actions["P_pl"],
        plan.solver_min,
        plan.angles[-1],
        plan.solver_increment,
        prestress=_prestress(inp),
        bar_materials=inp.get("bar_materials"),
        tendon_materials=inp.get("tendon_materials"),
    )
    if len(points) != len(plan.angles):
        raise TraceValidationError(
            "authoritative CT-003 replay violated expected cardinality"
        )
    return tuple(points)


def _replay_axis(
    inp: Mapping[str, Any], axis: str
) -> tuple[tuple[InteractionPoint, ...], tuple[InteractionPoint, ...]]:
    positive_angle, negative_angle = INTERACTION_ANGLES[axis]

    def branch(angle: float) -> tuple[InteractionPoint, ...]:
        return tuple(
            solve_interaction(
                inp["section"],
                inp["concrete"],
                inp["steel"],
                angle,
                prestress=_prestress(inp),
                bar_materials=inp.get("bar_materials"),
                tendon_materials=inp.get("tendon_materials"),
                n_points=INTERACTION_INTERVALS,
            )
        )

    return branch(positive_angle), branch(negative_angle)


def _validate_radial_result(
    inp: Mapping[str, Any],
    blocks: SectionTraceBlocks,
    plastic: Mapping[str, Any],
    plan: SweepPlan,
    context: Mapping[str, Any],
) -> _RadialEvidence:
    if not plan.closed:
        raise TraceValidationError("CT-003 requires an exact closed sweep")
    if plastic.get("closed") is not True:
        raise TraceValidationError("CT-003 requires retained closed-envelope evidence")
    if plastic.get("check_util") is not True:
        raise TraceValidationError("CT-003 requires the retained radial check")

    replay = _replay_radial(inp, blocks, plan)
    convergence = tuple(point.converged for point in replay)
    _require_flag(
        plastic.get("converged"),
        all(convergence),
        "retained radial sweep convergence",
    )

    retained_points = _sequence(plastic.get("points"), "retained plastic points")
    mx = _sequence(plastic.get("mx"), "retained plastic mx")
    my = _sequence(plastic.get("my"), "retained plastic my")
    cardinality = len(plan.angles)
    if not (
        len(retained_points) == len(mx) == len(my) == cardinality
    ):
        raise TraceValidationError("CT-003 retained arrays have wrong cardinality")
    points = tuple(
        _mapping(value, f"retained plastic point {index}")
        for index, value in enumerate(retained_points)
    )
    for index, (angle, flag, retained) in enumerate(
        zip(plan.angles, convergence, points)
    ):
        _require_close(retained.get("V"), angle, f"radial member {index} angle")
        _require_flag(
            retained.get("converged"),
            flag,
            f"radial member {index} convergence",
        )

    actions = dict(blocks.plastic_actions.values)
    applied = _sequence(plastic.get("applied"), "retained radial applied action")
    if len(applied) != 2:
        raise TraceValidationError("retained radial applied action needs Mx and My")
    _require_close(applied[0], actions["Mx_pl"], "retained applied Mx")
    _require_close(applied[1], actions["My_pl"], "retained applied My")

    replay_mx = tuple(point.Mx for point in replay)
    replay_my = tuple(point.My for point in replay)
    radial = radial_util_result(
        replay_mx, replay_my, actions["Mx_pl"], actions["My_pl"]
    )
    _require_close(
        plastic.get("util_demand"), radial.demand, "retained radial demand"
    )
    _require_optional_close(
        plastic.get("util_resistance"),
        radial.resistance,
        "retained radial resistance",
    )
    _require_utilisation(
        plastic.get("util"), radial.utilisation, "retained radial utilisation"
    )
    _require_selection(
        plastic.get("util_gov"),
        radial.governing_index,
        cardinality,
        "retained radial util_gov",
    )

    if not all(convergence):
        branch = RADIAL_FAILED_SWEEP
        selected_index = None
    elif radial.demand < 1.0e-9:
        branch = RADIAL_FINITE_ZERO
        selected_index = None
    elif (
        radial.resistance is not None
        and math.isfinite(radial.resistance)
        and math.isfinite(radial.utilisation)
        and type(radial.governing_index) is int
    ):
        branch = RADIAL_FINITE_SELECTED
        selected_index = radial.governing_index
    else:
        branch = RADIAL_FAILED_SELECTOR
        selected_index = None

    if branch in {RADIAL_FINITE_SELECTED, RADIAL_FINITE_ZERO}:
        for index, (retained, point, expected_mx, expected_my) in enumerate(
            zip(points, replay, replay_mx, replay_my)
        ):
            _require_close(mx[index], expected_mx, f"radial member {index} mx")
            _require_close(my[index], expected_my, f"radial member {index} my")
            _require_close(
                retained.get("Mx"), point.Mx, f"radial point {index} Mx"
            )
            _require_close(
                retained.get("My"), point.My, f"radial point {index} My"
            )

    shape = radial_trace_shape(
        blocks, context, plan, branch, selected_index
    )
    return _RadialEvidence(
        blocks, plan, shape, plastic, points, replay, convergence, radial
    )


def _validate_axis_result(
    inp: Mapping[str, Any],
    blocks: SectionTraceBlocks,
    interaction: Mapping[str, Any],
    context: Mapping[str, Any],
    axis: str,
) -> _AxisEvidence:
    result = _mapping(interaction.get(axis), f"retained CT-004 {axis} axis")
    positive, negative = _replay_axis(inp, axis)
    if (
        len(positive) != INTERACTION_BRANCH_CARDINALITY
        or len(negative) != INTERACTION_BRANCH_CARDINALITY
    ):
        raise TraceValidationError(
            f"authoritative CT-004 {axis} replay has wrong branch cardinality"
        )
    ordered = positive + tuple(reversed(negative))
    if len(ordered) != INTERACTION_CARDINALITY:
        raise TraceValidationError(
            f"authoritative CT-004 {axis} replay has wrong cardinality"
        )
    convergence = tuple(point.converged for point in ordered)
    finite = all(convergence)
    _require_flag(
        result.get("converged"),
        finite,
        f"retained CT-004 {axis} convergence",
    )

    actions = dict(blocks.plastic_actions.values)
    moment_key = "Mx_pl" if axis == "x" else "My_pl"
    applied = _sequence(
        result.get("applied"), f"retained CT-004 {axis} applied point"
    )
    if len(applied) != 2:
        raise TraceValidationError(
            f"retained CT-004 {axis} applied point needs N and M"
        )
    _require_close(applied[0], actions["P_pl"], f"CT-004 {axis} applied N")
    _require_close(
        applied[1], actions[moment_key], f"CT-004 {axis} applied moment"
    )

    if finite:
        axial = _sequence(
            result.get("N"), f"retained CT-004 {axis} axial array"
        )
        moment = _sequence(
            result.get("M"), f"retained CT-004 {axis} moment array"
        )
        if (
            len(axial) != INTERACTION_CARDINALITY
            or len(moment) != INTERACTION_CARDINALITY
        ):
            raise TraceValidationError(
                f"retained CT-004 {axis} arrays have wrong cardinality"
            )
        for index, point in enumerate(ordered):
            _require_close(
                axial[index], -point.axial, f"CT-004 {axis} member {index} N"
            )
            expected_moment = point.Mx if axis == "x" else point.My
            _require_close(
                moment[index],
                expected_moment,
                f"CT-004 {axis} member {index} moment",
            )

    shape = axis_trace_shape(
        blocks,
        context,
        axis,
        INTERACTION_FINITE if finite else INTERACTION_FAILED,
    )
    return _AxisEvidence(
        shape, result, positive, negative, ordered, convergence
    )


def _evidence(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    context: Mapping[str, Any],
) -> _Evidence:
    blocks = section_trace_blocks(inp)
    plastic = _mapping(out.get("plastic"), "retained plastic result")
    plan = expected_sweep(inp.get("v_min"), inp.get("v_max"), inp.get("v_inc"))
    radial = _validate_radial_result(inp, blocks, plastic, plan, context)
    interaction = _mapping(
        plastic.get("interaction"), "retained CT-004 interaction result"
    )
    x_axis = _validate_axis_result(
        inp, blocks, interaction, context, "x"
    )
    y_axis = _validate_axis_result(
        inp, blocks, interaction, context, "y"
    )
    return _Evidence(blocks, radial, x_axis, y_axis)


def _shared_values(
    blocks: SectionTraceBlocks, action_keys: tuple[str, ...]
) -> dict[str, float | int | None]:
    values: dict[str, float | int | None] = {}
    actions = dict(blocks.plastic_actions.values)
    for key in action_keys:
        values[action_step_id(key)] = actions[key]
    values["action-vector"] = len(action_keys)

    geometry_count = 0
    for ring_index, ring in enumerate(blocks.geometry.rings):
        for point_index, (x, y) in enumerate(ring):
            prefix = f"geometry-ring-{ring_index:03d}-point-{point_index:04d}"
            values[f"{prefix}-x"] = x
            values[f"{prefix}-y"] = y
            geometry_count += 2
    for kind, elements in (
        ("bar", blocks.geometry.bars),
        ("tendon", blocks.geometry.tendons),
    ):
        for index, element in enumerate(elements):
            prefix = f"geometry-{kind}-{index:04d}"
            values[f"{prefix}-x"] = element.x
            values[f"{prefix}-y"] = element.y
            values[f"{prefix}-area"] = element.area
            geometry_count += 3
    values["geometry-vector"] = geometry_count

    material_count = 0
    for material in (blocks.concrete, *blocks.bars, *blocks.tendons):
        for name, value in material.values:
            values[material_step_id(material, name)] = value
            material_count += 1
    values["material-vector"] = material_count
    return values


def _radial_values(
    evidence: _RadialEvidence,
) -> dict[str, float | int | None]:
    values = _shared_values(
        evidence.blocks, ("P_pl", "Mx_pl", "My_pl")
    )
    requested = {
        "v_min": evidence.plan.requested_min,
        "v_max": evidence.plan.requested_max,
        "v_inc": evidence.plan.requested_increment,
    }
    for key, value in requested.items():
        values[sweep_step_id(key)] = value
    values["normalised-sweep-plan"] = len(evidence.plan.angles)

    finite = evidence.shape.branch in {
        RADIAL_FINITE_SELECTED,
        RADIAL_FINITE_ZERO,
    }
    for index, (angle, point, converged) in enumerate(
        zip(evidence.plan.angles, evidence.replay, evidence.convergence)
    ):
        values[radial_member_step_id(index, "angle")] = angle
        values[radial_member_step_id(index, "converged")] = (
            1.0 if converged else 0.0
        )
        if finite:
            values[radial_member_step_id(index, "mx")] = point.Mx
            values[radial_member_step_id(index, "my")] = point.My
            values[radial_member_step_id(index, "complete-state")] = 1.0

    if not finite:
        values["failure-count"] = sum(not flag for flag in evidence.convergence)
        values["radial-failure-state"] = None
        values["radial-utilisation-result"] = None
        return values

    values["complete-envelope-evidence"] = len(evidence.replay)
    values["radial-demand"] = evidence.radial.demand
    if evidence.shape.branch == RADIAL_FINITE_ZERO:
        values["zero-demand-state"] = 1.0
        values["radial-utilisation-result"] = 0.0
        return values

    values["radial-resistance"] = evidence.radial.resistance
    values["radial-utilisation"] = evidence.radial.utilisation
    values["selected-member-index"] = evidence.shape.selected_index
    values["selected-member-evidence"] = 1.0
    values["demand-resistance-verdict"] = (
        1.0 if evidence.radial.utilisation <= 1.0 + 1.0e-9 else 0.0
    )
    values["radial-utilisation-result"] = evidence.radial.utilisation
    return values


def _axis_values(
    evidence: _AxisEvidence,
) -> dict[str, float | int | None]:
    axis = evidence.shape.axis
    moment_key = "Mx_pl" if axis == "x" else "My_pl"
    values = _shared_values(evidence.shape.blocks, ("P_pl", moment_key))
    positive_angle, negative_angle = INTERACTION_ANGLES[axis]
    values["interaction-interval-count"] = INTERACTION_INTERVALS
    values["positive-branch-angle"] = positive_angle
    values["negative-branch-angle"] = negative_angle
    values["interaction-member-plan"] = INTERACTION_CARDINALITY
    finite = evidence.shape.branch == INTERACTION_FINITE
    if finite:
        values["positive-tension-limit"] = -evidence.positive[0].axial
        values["positive-compression-limit"] = -evidence.positive[-1].axial
        values["negative-tension-limit"] = -evidence.negative[0].axial
        values["negative-compression-limit"] = -evidence.negative[-1].axial

    for member, point, converged in zip(
        evidence.shape.members, evidence.ordered, evidence.convergence
    ):
        index = member.retained_index
        values[interaction_member_step_id(index, "angle")] = member.angle
        values[interaction_member_step_id(index, "sample-index")] = (
            member.sample_index
        )
        values[interaction_member_step_id(index, "converged")] = (
            1.0 if converged else 0.0
        )
        if finite:
            values[interaction_member_step_id(index, "axial")] = -point.axial
            values[interaction_member_step_id(index, "moment")] = (
                point.Mx if axis == "x" else point.My
            )
            values[interaction_member_step_id(index, "complete-state")] = 1.0

    if finite:
        values["complete-axis-boundary"] = INTERACTION_CARDINALITY
        values["applied-axis-point"] = 2.0
        values["axis-interaction-result"] = INTERACTION_CARDINALITY
    else:
        values["failure-count"] = sum(not flag for flag in evidence.convergence)
        values["axis-failure-state"] = None
        values["axis-interaction-result"] = None
    return values


def _result(
    step_id: str,
    value: float | int | None,
    failed_step_ids: frozenset[str],
    reason: str,
) -> TraceResult:
    if step_id in failed_step_ids:
        return TraceResult(RESULT_FAILED, None, reason)
    if value is None:
        raise TraceValidationError(f"trace step {step_id} has no finite value")
    return TraceResult(RESULT_FINITE, value)


def _calculation(
    *,
    calculation_id: str,
    coverage_id: str,
    title: str,
    method_id: str,
    axes: tuple[Any, ...],
    final_step_id: str,
    specs: tuple[StepSpec, ...],
    values: Mapping[str, float | int | None],
    failed_step_ids: frozenset[str] = frozenset(),
    failure_reason: str = "",
    failed_demand: bool = False,
    assumptions: tuple[str, ...] = (),
) -> TraceCalculation:
    units = {spec.step_id: spec.unit for spec in specs}
    steps = []
    for spec in specs:
        value = values.get(spec.step_id)
        warnings: tuple[str, ...] = ()
        if spec.step_id in failed_step_ids:
            warnings = (failure_reason,)
        elif failed_demand and spec.step_id in {
            "demand-resistance-verdict",
            "radial-utilisation-result",
        }:
            warnings = ("Applied radial demand exceeds the resistance.",)
        steps.append(
            TraceStep(
                step_id=spec.step_id,
                title=spec.title,
                dependencies=tuple(
                    TraceDependency(dependency, units[dependency])
                    for dependency in spec.dependencies
                ),
                quantity_role=spec.quantity_role,
                source=spec.source,
                symbol=spec.step_id,
                unit=spec.unit,
                actual_expression=f"authoritative {spec.title.lower()}",
                substituted_expression=(
                    f"{spec.title} = "
                    + ("failed" if value is None else repr(value))
                ),
                result=_result(
                    spec.step_id, value, failed_step_ids, failure_reason
                ),
                warnings=warnings,
            )
        )
    return TraceCalculation(
        calculation_id=calculation_id,
        coverage_id=coverage_id,
        title=title,
        method_id=method_id,
        axes=axes,
        final_step_id=final_step_id,
        steps=tuple(steps),
        warnings=((failure_reason,) if failed_step_ids else ()),
        assumptions=assumptions,
    )


def _radial_calculation(evidence: _RadialEvidence) -> TraceCalculation:
    specs = radial_step_contract(evidence.shape)
    failed = evidence.shape.branch in {
        RADIAL_FAILED_SWEEP,
        RADIAL_FAILED_SELECTOR,
    }
    reason = (
        _RADIAL_SWEEP_FAILURE
        if evidence.shape.branch == RADIAL_FAILED_SWEEP
        else _RADIAL_SELECTOR_FAILURE
        if evidence.shape.branch == RADIAL_FAILED_SELECTOR
        else ""
    )
    return _calculation(
        calculation_id=evidence.shape.calculation_id,
        coverage_id=RADIAL_COVERAGE_ID,
        title="Radial plastic utilisation",
        method_id=evidence.blocks.plastic_method_id,
        axes=evidence.shape.axes,
        final_step_id="radial-utilisation-result",
        specs=specs,
        values=_radial_values(evidence),
        failed_step_ids=(
            frozenset({"radial-failure-state", "radial-utilisation-result"})
            if failed
            else frozenset()
        ),
        failure_reason=reason,
        failed_demand=(
            evidence.shape.branch == RADIAL_FINITE_SELECTED
            and evidence.radial.utilisation > 1.0 + 1.0e-9
        ),
        assumptions=(
            "Radial resistance is the nearest forward crossing of the closed chord envelope.",
            "Zero radial demand has no selected member or fabricated resistance.",
        ),
    )


def _axis_calculation(evidence: _AxisEvidence) -> TraceCalculation:
    axis = evidence.shape.axis
    failed = evidence.shape.branch == INTERACTION_FAILED
    return _calculation(
        calculation_id=evidence.shape.calculation_id,
        coverage_id=INTERACTION_COVERAGE_ID,
        title=f"{axis}-axis plastic interaction boundary",
        method_id=evidence.shape.blocks.plastic_method_id,
        axes=evidence.shape.axes,
        final_step_id="axis-interaction-result",
        specs=axis_step_contract(evidence.shape),
        values=_axis_values(evidence),
        failed_step_ids=(
            frozenset({"axis-failure-state", "axis-interaction-result"})
            if failed
            else frozenset()
        ),
        failure_reason=_INTERACTION_FAILURE if failed else "",
        assumptions=(
            "Solver axial force is compression-positive; retained diagram N is tension-positive.",
            "The positive branch is followed by the reversed negative branch.",
            "The boundary records no invented utilisation or pass/fail verdict.",
        ),
    )


def build_plastic_interaction_trace_families(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle:
    """Build and exact-registry-audit CT-003 plus both CT-004 axes."""

    try:
        trace_context = {} if context is None else _mapping(context, "trace context")
        evidence = _evidence(
            _mapping(inp, "CT-003/CT-004 input"),
            _mapping(out, "analysis result"),
            trace_context,
        )
        calculations = (
            _radial_calculation(evidence.radial),
            _axis_calculation(evidence.x_axis),
            _axis_calculation(evidence.y_axis),
        )
        bundle = create_bundle(
            input_sha256=input_sha256,
            result_sha256=result_sha256,
            calculations=calculations,
        )
        registry = expected_registry(
            evidence.radial.shape,
            evidence.x_axis.shape,
            evidence.y_axis.shape,
        )
        audit_trace_registry(bundle, registry)
        return validate_bundle(
            bundle,
            expected_input_sha256=input_sha256,
            expected_result_sha256=result_sha256,
        )
    except TraceValidationError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(
            f"invalid CT-003/CT-004 evidence: {exc}"
        ) from exc
