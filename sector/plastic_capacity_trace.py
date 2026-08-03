"""Solver-owned unpublished CT-002 selected plastic-capacity trace."""

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
from .plastic import (
    PlasticPoint,
    _accumulate_at_depth,
    _prep_section,
    solve_plastic,
)
from .plastic_capacity_trace_contract import (
    ACTION_KEYS,
    BRANCH_FAILED_SELECTED,
    BRANCH_FAILED_UNSELECTED,
    BRANCH_FINITE_SELECTED,
    POINT_FIELDS,
    SWEEP_KEYS,
    SweepPlan,
    TraceShape,
    action_step_id,
    expected_registry,
    expected_step_contract,
    expected_sweep,
    member_identity_id,
    point_evidence_id,
    point_step_id,
    sweep_step_id,
    trace_shape,
)
from .section_trace_blocks import SectionTraceBlocks, section_trace_blocks
from .trace_registry import audit_trace_registry


_FAILURE_REASON = (
    "plastic solver did not bracket and converge every expected sweep member"
)


@dataclass(frozen=True, slots=True)
class PlasticCapacityEvidence:
    blocks: SectionTraceBlocks
    plan: SweepPlan
    shape: TraceShape
    result: Mapping[str, Any]
    points: tuple[Mapping[str, Any], ...]
    replay: tuple[PlasticPoint, ...]
    convergence: tuple[bool, ...]
    radial: RadialUtilResult


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


_FINITE_POINT_DIAGNOSTICS = (
    "axial_requested",
    "axial_residual",
    "axial_tolerance",
    "compression_depth",
    "neutral_axis_offset",
    "strain_gradient_x",
    "strain_gradient_y",
    "strain_offset",
    "search_lower_depth",
    "search_upper_depth",
    "search_lower_axial",
    "search_upper_axial",
    "concrete_force",
    "concrete_mx",
    "concrete_my",
    "bar_force",
    "bar_mx",
    "bar_my",
    "tendon_force",
    "tendon_mx",
    "tendon_my",
    "compression_mx",
    "compression_my",
    "tension_force",
    "tension_mx",
    "tension_my",
)


def _require_complete_point_diagnostics(point: PlasticPoint) -> None:
    for field_name in _FINITE_POINT_DIAGNOSTICS:
        value = getattr(point, field_name)
        if value is None or isinstance(value, bool):
            break
        try:
            if not math.isfinite(float(value)):
                break
        except (TypeError, ValueError):
            break
    else:
        if (
            type(point.axial_reachable) is bool
            and type(point.search_iterations) is int
            and point.search_iterations >= 0
        ):
            return
    raise TraceValidationError(
        "authoritative plastic point is missing complete finite solver diagnostics"
    )


def _replay(
    inp: Mapping[str, Any],
    blocks: SectionTraceBlocks,
    plan: SweepPlan,
) -> tuple[PlasticPoint, ...]:
    actions = dict(blocks.plastic_actions.values)
    section = inp["section"]
    prestress = inp.get("prestress") if section.tendons else None
    points = solve_plastic(
        section,
        inp["concrete"],
        inp["steel"],
        -actions["P_pl"],
        plan.solver_min,
        plan.angles[-1],
        plan.solver_increment,
        prestress=prestress,
        bar_materials=inp.get("bar_materials"),
        tendon_materials=inp.get("tendon_materials"),
    )
    if len(points) != len(plan.angles):
        raise TraceValidationError("authoritative replay violated the expected sweep")
    return tuple(points)


def _point_expected(point: PlasticPoint) -> dict[str, float | int | bool]:
    """Translate one authoritative point to the retained output convention."""

    _require_complete_point_diagnostics(point)
    return {
        "Mx": point.Mx,
        "My": point.My,
        "axial_requested": point.axial_requested,
        "axial_achieved": point.axial,
        "axial_residual": point.axial_residual,
        "axial_tolerance": point.axial_tolerance,
        "axial_reachable": point.axial_reachable,
        "compression_depth": point.compression_depth,
        "neutral_axis_offset": point.neutral_axis_offset,
        "kappa": point.curvature,
        "strain_gradient_x": point.strain_gradient_x,
        "strain_gradient_y": point.strain_gradient_y,
        "strain_offset": point.strain_offset,
        "eps_c": -point.eps_concrete,
        "eps_s": -point.eps_steel,
        "eps_s_comp": -point.eps_steel_comp,
        "eps_cable": -point.eps_cable,
        "concrete_force": point.concrete_force,
        "concrete_mx": point.concrete_mx,
        "concrete_my": point.concrete_my,
        "bar_force": point.bar_force,
        "bar_mx": point.bar_mx,
        "bar_my": point.bar_my,
        "tendon_force": point.tendon_force,
        "tendon_mx": point.tendon_mx,
        "tendon_my": point.tendon_my,
        "comp_force": point.compression_force,
        "compression_mx": point.compression_mx,
        "compression_my": point.compression_my,
        "tension_force": point.tension_force,
        "tension_mx": point.tension_mx,
        "tension_my": point.tension_my,
        "lever": point.lever_arm,
        "dx": point.dx,
        "dy": point.dy,
        "search_lower_depth": point.search_lower_depth,
        "search_upper_depth": point.search_upper_depth,
        "search_lower_axial": point.search_lower_axial,
        "search_upper_axial": point.search_upper_axial,
        "search_iterations": point.search_iterations,
        "converged": point.converged,
    }


def _validate_finite_point(
    inp: Mapping[str, Any],
    retained: Mapping[str, Any],
    replay: PlasticPoint,
    index: int,
    *,
    prep: Any,
    band_memo: dict[Any, Any],
) -> None:
    label = f"plastic point {index}"
    expected = _point_expected(replay)
    for field in POINT_FIELDS:
        if field not in retained:
            raise TraceValidationError(f"{label} is missing {field}")
        value = retained[field]
        authoritative = expected[field]
        if field in {"converged", "axial_reachable"}:
            if type(value) is not bool or value is not authoritative:
                raise TraceValidationError(
                    f"{label} {field} contradicts the authoritative search"
                )
        elif field == "search_iterations":
            if (
                type(value) is not int
                or type(value) is bool
                or value != authoritative
            ):
                raise TraceValidationError(
                    f"{label} search iterations contradict the authoritative search"
                )
        else:
            _require_close(value, float(authoritative), f"{label} {field}")

    section = inp["section"]
    reconstructed = _accumulate_at_depth(
        section,
        inp["concrete"],
        inp["steel"],
        replay.V,
        replay.compression_depth,
        replay.curvature,
        prestress=(inp.get("prestress") if section.tendons else None),
        bar_materials=inp.get("bar_materials"),
        tendon_materials=inp.get("tendon_materials"),
        prep=prep,
        band_memo=band_memo,
    )
    reconstructed_fields = {
        "concrete_force": reconstructed.concrete_force,
        "concrete_mx": reconstructed.concrete_mx,
        "concrete_my": reconstructed.concrete_my,
        "bar_force": reconstructed.bar_force,
        "bar_mx": reconstructed.bar_mx,
        "bar_my": reconstructed.bar_my,
        "tendon_force": reconstructed.tendon_force,
        "tendon_mx": reconstructed.tendon_mx,
        "tendon_my": reconstructed.tendon_my,
        "comp_force": reconstructed.compression_force,
        "compression_mx": reconstructed.compression_mx,
        "compression_my": reconstructed.compression_my,
        "tension_force": reconstructed.tension_force,
        "tension_mx": reconstructed.tension_mx,
        "tension_my": reconstructed.tension_my,
    }
    for field, authoritative in reconstructed_fields.items():
        _require_close(
            retained[field], authoritative, f"{label} reconstructed {field}"
        )

    for field, total in (
        (
            "axial_achieved",
            retained["concrete_force"]
            + retained["bar_force"]
            + retained["tendon_force"],
        ),
        (
            "Mx",
            retained["concrete_mx"]
            + retained["bar_mx"]
            + retained["tendon_mx"],
        ),
        (
            "My",
            retained["concrete_my"]
            + retained["bar_my"]
            + retained["tendon_my"],
        ),
        (
            "axial_achieved",
            retained["comp_force"] + retained["tension_force"],
        ),
        (
            "Mx", retained["compression_mx"] + retained["tension_mx"]
        ),
        (
            "My", retained["compression_my"] + retained["tension_my"]
        ),
    ):
        if not _close(float(retained[field]), float(total)):
            raise TraceValidationError(
                f"{label} has inconsistent material/sign resultants"
            )


def _selected_index(value: Any, cardinality: int) -> int | None:
    if value is None:
        return None
    if (
        type(value) is not int
        or type(value) is bool
        or value < 0
        or value >= cardinality
    ):
        raise TraceValidationError(
            "util_gov must be null or a non-Boolean in-range integer"
        )
    return value


def _evidence(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    context: Mapping[str, Any],
) -> PlasticCapacityEvidence:
    blocks = section_trace_blocks(inp)
    plan = expected_sweep(*(inp[key] for key in SWEEP_KEYS))
    if not plan.closed or inp.get("check_util", True) is not True:
        raise TraceValidationError("CT-002 requires a checked closed plastic sweep")
    result = _mapping(out.get("plastic"), "plastic result")
    points = _sequence(result.get("points"), "plastic points")
    if len(points) != len(plan.angles):
        raise TraceValidationError("plastic point cardinality contradicts the sweep")

    retained_points: list[Mapping[str, Any]] = []
    convergence: list[bool] = []
    for index, (raw_point, angle) in enumerate(zip(points, plan.angles)):
        point = _mapping(raw_point, f"plastic point {index}")
        _require_close(point.get("V"), angle, f"plastic point {index} angle")
        flag = point.get("converged")
        if type(flag) is not bool:
            raise TraceValidationError(
                f"plastic point {index} converged must be Boolean"
            )
        retained_points.append(point)
        convergence.append(flag)

    replay = _replay(inp, blocks, plan)
    replay_flags = tuple(point.converged for point in replay)
    if replay_flags != tuple(convergence):
        raise TraceValidationError(
            "retained convergence flags contradict the authoritative search"
        )
    envelope_converged = result.get("converged")
    if type(envelope_converged) is not bool:
        raise TraceValidationError("plastic envelope convergence must be Boolean")
    if envelope_converged is not all(convergence):
        raise TraceValidationError(
            "plastic envelope convergence masks a retained member state"
        )

    if "util_gov" not in result:
        raise TraceValidationError("util_gov is required, with null for no selection")
    retained_selected = _selected_index(result["util_gov"], len(plan.angles))
    actions = dict(blocks.plastic_actions.values)
    radial = radial_util_result(
        [point.Mx for point in replay],
        [point.My for point in replay],
        actions["Mx_pl"],
        actions["My_pl"],
    )
    if retained_selected != radial.governing_index:
        raise TraceValidationError(
            "plastic util_gov contradicts the authoritative envelope selection"
        )

    if all(replay_flags):
        if (
            retained_selected is None
            or radial.resistance is None
            or not math.isfinite(radial.resistance)
            or not math.isfinite(radial.utilisation)
        ):
            raise TraceValidationError(
                "converged CT-002 needs a finite authoritative selected member"
            )
        branch = BRANCH_FINITE_SELECTED
    else:
        branch = (
            BRANCH_FAILED_UNSELECTED
            if retained_selected is None
            else BRANCH_FAILED_SELECTED
        )
    shape = trace_shape(blocks, context, plan, branch, retained_selected)

    evidence = PlasticCapacityEvidence(
        blocks,
        plan,
        shape,
        result,
        tuple(retained_points),
        replay,
        tuple(convergence),
        radial,
    )
    if branch == BRANCH_FINITE_SELECTED:
        _validate_finite_evidence(inp, evidence)
    return evidence


def _validate_finite_evidence(
    inp: Mapping[str, Any], evidence: PlasticCapacityEvidence
) -> None:
    result = evidence.result
    if result.get("closed") is not True or result.get("check_util") is not True:
        raise TraceValidationError("finite CT-002 needs checked closed result evidence")
    mx = _sequence(result.get("mx"), "plastic Mx array")
    my = _sequence(result.get("my"), "plastic My array")
    if len(mx) != len(evidence.replay) or len(my) != len(evidence.replay):
        raise TraceValidationError("plastic Mx/My arrays contradict sweep cardinality")
    for index, point in enumerate(evidence.replay):
        _require_close(mx[index], point.Mx, f"plastic Mx member {index}")
        _require_close(my[index], point.My, f"plastic My member {index}")

    applied = _sequence(result.get("applied"), "plastic applied moment")
    actions = dict(evidence.blocks.plastic_actions.values)
    if len(applied) != 2:
        raise TraceValidationError("plastic applied moment needs Mx/My")
    _require_close(applied[0], actions["Mx_pl"], "plastic applied Mx")
    _require_close(applied[1], actions["My_pl"], "plastic applied My")
    _require_close(result.get("util"), evidence.radial.utilisation, "plastic util")
    _require_close(
        result.get("util_demand"), evidence.radial.demand, "plastic radial demand"
    )
    _require_close(
        result.get("util_resistance"),
        float(evidence.radial.resistance),
        "plastic radial resistance",
    )

    prep = _prep_section(inp["section"], bool(inp["section"].tendons))
    band_memo: dict[Any, Any] = {}
    for index, (retained, replay) in enumerate(
        zip(evidence.points, evidence.replay)
    ):
        _validate_finite_point(
            inp,
            retained,
            replay,
            index,
            prep=prep,
            band_memo=band_memo,
        )
        _require_close(retained["Mx"], float(mx[index]), f"point {index} Mx alignment")
        _require_close(retained["My"], float(my[index]), f"point {index} My alignment")


def _leaf_values(
    evidence: PlasticCapacityEvidence,
) -> dict[str, float | int | None]:
    values: dict[str, float | int | None] = {}
    actions = dict(evidence.blocks.plastic_actions.values)
    if evidence.shape.branch == BRANCH_FINITE_SELECTED:
        for key in ACTION_KEYS:
            values[action_step_id(key)] = actions[key]
        values["action-vector"] = len(ACTION_KEYS)
    requested = {
        "v_min": evidence.plan.requested_min,
        "v_max": evidence.plan.requested_max,
        "v_inc": evidence.plan.requested_increment,
    }
    for key in SWEEP_KEYS:
        values[sweep_step_id(key)] = requested[key]
    values["normalised-sweep-plan"] = len(evidence.plan.angles)

    if evidence.shape.branch != BRANCH_FINITE_SELECTED:
        return values

    geometry_count = 0
    for ring_index, ring in enumerate(evidence.blocks.geometry.rings):
        for point_index, (x, y) in enumerate(ring):
            prefix = f"geometry-ring-{ring_index:03d}-point-{point_index:04d}"
            values[f"{prefix}-x"] = x
            values[f"{prefix}-y"] = y
            geometry_count += 2
    for kind, elements in (
        ("bar", evidence.blocks.geometry.bars),
        ("tendon", evidence.blocks.geometry.tendons),
    ):
        for index, element in enumerate(elements):
            prefix = f"geometry-{kind}-{index:04d}"
            values[f"{prefix}-x"] = element.x
            values[f"{prefix}-y"] = element.y
            values[f"{prefix}-area"] = element.area
            geometry_count += 3
    values["geometry-vector"] = geometry_count

    material_count = 0
    for material in (
        evidence.blocks.concrete,
        *evidence.blocks.bars,
        *evidence.blocks.tendons,
    ):
        prefix = (
            f"material-{material.kind}-"
            f"u{material.element_id.encode('utf-8').hex()}-"
            f"u{material.material_id.encode('utf-8').hex()}"
        )
        for name, value in material.values:
            step_id = f"{prefix}-u{name.encode('utf-8').hex()}"
            values[step_id] = value
            material_count += 1
    values["material-vector"] = material_count
    return values


def _trace_values(
    evidence: PlasticCapacityEvidence,
) -> dict[str, float | int | None]:
    values = _leaf_values(evidence)
    for index, (angle, converged) in enumerate(
        zip(evidence.plan.angles, evidence.convergence)
    ):
        values[member_identity_id(index)] = angle
        if evidence.shape.branch == BRANCH_FINITE_SELECTED:
            point = evidence.points[index]
            for field in POINT_FIELDS:
                raw = point[field]
                values[point_step_id(index, field)] = (
                    1.0 if raw is True else 0.0 if raw is False else raw
                )
            values[point_evidence_id(index)] = 1.0
        else:
            values[point_step_id(index, "converged")] = 1.0 if converged else 0.0

    if evidence.shape.branch == BRANCH_FINITE_SELECTED:
        values["complete-envelope-evidence"] = len(evidence.plan.angles)
        values["radial-demand"] = evidence.radial.demand
        values["radial-resistance"] = evidence.radial.resistance
        values["radial-utilisation"] = evidence.radial.utilisation
        values["selected-member-index"] = evidence.shape.selected_index
        values["selected-member-evidence"] = 1.0
        values["demand-resistance-verdict"] = (
            1.0 if evidence.radial.utilisation <= 1.0 + 1.0e-9 else 0.0
        )
        values["selected-plastic-capacity-result"] = evidence.radial.utilisation
    else:
        failure_count = sum(not flag for flag in evidence.convergence)
        values["failure-count"] = failure_count
        values["failure-state"] = None
        if evidence.shape.branch == BRANCH_FAILED_SELECTED:
            values["selected-member-index"] = evidence.shape.selected_index
        values["selected-plastic-capacity-result"] = None
    return values


def _result(step_id: str, value: float | int | None, *, failed: bool) -> TraceResult:
    if failed and step_id in {"failure-state", "selected-plastic-capacity-result"}:
        return TraceResult(RESULT_FAILED, None, _FAILURE_REASON)
    if value is None:
        raise TraceValidationError(f"CT-002 step {step_id} has no finite value")
    return TraceResult(RESULT_FINITE, value)


def _calculation(evidence: PlasticCapacityEvidence) -> TraceCalculation:
    specs = expected_step_contract(evidence.shape)
    values = _trace_values(evidence)
    units = {spec.step_id: spec.unit for spec in specs}
    failed = evidence.shape.branch != BRANCH_FINITE_SELECTED
    passed = evidence.radial.utilisation <= 1.0 + 1.0e-9
    steps = []
    for spec in specs:
        value = values.get(spec.step_id)
        warnings: tuple[str, ...] = ()
        if failed and spec.step_id in {
            "failure-state",
            "selected-plastic-capacity-result",
        }:
            warnings = (_FAILURE_REASON,)
        elif (
            not failed
            and not passed
            and spec.step_id in {
                "demand-resistance-verdict",
                "selected-plastic-capacity-result",
            }
        ):
            warnings = ("Applied radial demand exceeds the selected resistance.",)
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
                result=_result(spec.step_id, value, failed=failed),
                warnings=warnings,
            )
        )
    assumptions = (
        (
            "Solver axial force and strain-plane values use compression-positive sign.",
            "Displayed extreme strains retain the existing tension-positive output sign.",
        )
        if not failed
        else (
            "Failure evidence is limited to requested sweep identity and genuine convergence state.",
        )
    )
    return TraceCalculation(
        calculation_id=evidence.shape.calculation_id,
        coverage_id="ct-002",
        title="Selected plastic capacity",
        method_id=evidence.blocks.plastic_method_id,
        axes=evidence.shape.axes,
        final_step_id="selected-plastic-capacity-result",
        steps=tuple(steps),
        warnings=((_FAILURE_REASON,) if failed else ()),
        assumptions=assumptions,
    )


def replay_plastic_capacity_evidence(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    context: Mapping[str, Any] | None = None,
) -> PlasticCapacityEvidence:
    """Return the accepted CT-002 reconstruction for bounded trace joins."""

    try:
        trace_context = (
            {} if context is None else _mapping(context, "CT-002 context")
        )
        return _evidence(
            _mapping(inp, "CT-002 input"),
            _mapping(out, "analysis result"),
            trace_context,
        )
    except TraceValidationError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"invalid CT-002 evidence: {exc}") from exc


def build_plastic_capacity_trace_family(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle:
    """Build, seal, and independently registry-audit one exact CT-002 member."""

    try:
        evidence = replay_plastic_capacity_evidence(
            inp, out, context=context,
        )
        calculation = _calculation(evidence)
        bundle = create_bundle(
            input_sha256=input_sha256,
            result_sha256=result_sha256,
            calculations=(calculation,),
        )
        audit_trace_registry(bundle, expected_registry(evidence.shape))
        return validate_bundle(
            bundle,
            expected_input_sha256=input_sha256,
            expected_result_sha256=result_sha256,
        )
    except TraceValidationError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"invalid CT-002 evidence: {exc}") from exc


def validate_plastic_capacity_trace_family(
    bundle: TraceBundle | dict[str, Any],
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle:
    """Reject stale or coherently resealed CT-002 publication tampering."""

    candidate = validate_bundle(
        bundle,
        expected_input_sha256=input_sha256,
        expected_result_sha256=result_sha256,
    )
    expected = build_plastic_capacity_trace_family(
        inp,
        out,
        input_sha256=input_sha256,
        result_sha256=result_sha256,
        context=context,
    )
    if candidate.to_dict() != expected.to_dict():
        raise TraceValidationError(
            "CT-002 trace differs from authoritative input replay"
        )
    return candidate
