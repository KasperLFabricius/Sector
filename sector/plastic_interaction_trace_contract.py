"""Independent CT-003 radial and CT-004 axis-interaction contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .calculation_trace import (
    RESULT_FAILED,
    RESULT_FINITE,
    ROLE_COMPUTED,
    ROLE_FINAL,
    ROLE_METHOD_VALUE,
    ROLE_USER_INPUT,
    SOURCE_INPUT,
    SOURCE_PROJECT,
    TraceAxis,
    TraceSource,
    TraceUnit,
    trace_identity_token,
)
from .plastic_capacity_trace_contract import SweepPlan
from .section_trace_blocks import (
    MaterialBlock,
    SectionTraceBlocks,
    context_axes,
    context_id,
)
from .trace_registry import (
    TraceFamilyContract,
    TraceMemberContract,
    TraceRegistryContract,
    TraceSourceContract,
    TraceStepMetadataContract,
)


RADIAL_COVERAGE_ID = "ct-003"
RADIAL_FAMILY_ID = "ct-003-radial-utilisation"
RADIAL_MEMBER_ID = "radial-utilisation"

INTERACTION_COVERAGE_ID = "ct-004"
INTERACTION_FAMILY_IDS = {
    "x": "ct-004-axis-interaction-x",
    "y": "ct-004-axis-interaction-y",
}
INTERACTION_MEMBER_IDS = {
    "x": "axis-interaction-x",
    "y": "axis-interaction-y",
}

REGISTRY_ID = "sector-ct-003-radial-ct-004-axis-interaction-v1"

RADIAL_FINITE_SELECTED = "finite-selected"
RADIAL_FINITE_ZERO = "finite-zero-demand"
RADIAL_FAILED_SWEEP = "failed-sweep"
RADIAL_FAILED_SELECTOR = "failed-selector"
RADIAL_BRANCHES = frozenset(
    {
        RADIAL_FINITE_SELECTED,
        RADIAL_FINITE_ZERO,
        RADIAL_FAILED_SWEEP,
        RADIAL_FAILED_SELECTOR,
    }
)

INTERACTION_FINITE = "finite"
INTERACTION_FAILED = "failed"
INTERACTION_BRANCHES = frozenset({INTERACTION_FINITE, INTERACTION_FAILED})

INTERACTION_INTERVALS = 32
INTERACTION_BRANCH_CARDINALITY = INTERACTION_INTERVALS + 1
INTERACTION_CARDINALITY = 2 * INTERACTION_BRANCH_CARDINALITY
INTERACTION_ANGLES = {"x": (90.0, 270.0), "y": (0.0, 180.0)}

INPUT_SOURCE = TraceSource(SOURCE_INPUT, "sector-section-input")
SOLVER_SOURCE = TraceSource(SOURCE_PROJECT, "sector-plastic-section-solver")
SELECTION_SOURCE = TraceSource(
    SOURCE_PROJECT, "sector-radial-envelope-selector"
)

ONE = TraceUnit("1", "scalar")
LENGTH = TraceUnit("m", "length")
AREA = TraceUnit("m2", "area")
FORCE = TraceUnit("kN", "force")
MOMENT = TraceUnit("kNm", "moment")
ANGLE = TraceUnit("degrees", "angle")
STRAIN_FRACTION = TraceUnit("1", "strain")
STRESS = TraceUnit("MPa", "stress")


@dataclass(frozen=True, slots=True)
class StepSpec:
    step_id: str
    title: str
    unit: TraceUnit
    quantity_role: str
    source: TraceSource
    dependencies: tuple[str, ...] = ()


class _Rows:
    def __init__(self, family: str) -> None:
        self.family = family
        self.rows: list[StepSpec] = []
        self.ids: set[str] = set()

    def add(
        self,
        step_id: str,
        title: str,
        unit: TraceUnit,
        role: str,
        source: TraceSource,
        *dependencies: str,
    ) -> str:
        if step_id in self.ids:
            raise ValueError(f"duplicate {self.family} step {step_id}")
        self.ids.add(step_id)
        self.rows.append(
            StepSpec(step_id, title, unit, role, source, tuple(dependencies))
        )
        return step_id


def _token(value: str) -> str:
    return trace_identity_token(value)


def action_step_id(key: str) -> str:
    return f"input-action-{_token(key)}"


def sweep_step_id(key: str) -> str:
    return f"input-sweep-{_token(key)}"


def radial_member_step_id(index: int, field: str) -> str:
    return f"member-{index:04d}-{field.replace('_', '-').lower()}"


def interaction_member_step_id(index: int, field: str) -> str:
    return f"boundary-member-{index:04d}-{field.replace('_', '-').lower()}"


def _material_prefix(material: MaterialBlock) -> str:
    return (
        f"material-{material.kind}-{_token(material.element_id)}-"
        f"{_token(material.material_id)}"
    )


def material_step_id(material: MaterialBlock, name: str) -> str:
    return f"{_material_prefix(material)}-{_token(name)}"


def _material_unit(name: str) -> TraceUnit:
    if name in {"fck", "fytk", "fyck", "futk", "Es"}:
        return STRESS
    if name in {"eps_c2", "eps_cu2", "eut", "ey0t", "ey0c", "IS"}:
        return STRAIN_FRACTION
    return ONE


def _actions(rows: _Rows, keys: tuple[str, ...]) -> None:
    leaves = []
    for key in keys:
        leaves.append(
            rows.add(
                action_step_id(key),
                f"Requested {key}",
                FORCE if key == "P_pl" else MOMENT,
                ROLE_USER_INPUT,
                INPUT_SOURCE,
            )
        )
    rows.add(
        "action-vector",
        "Relevant requested plastic actions",
        ONE,
        ROLE_COMPUTED,
        SOLVER_SOURCE,
        *leaves,
    )


def _geometry(rows: _Rows, blocks: SectionTraceBlocks) -> None:
    leaves = []
    for ring_index, ring in enumerate(blocks.geometry.rings):
        for point_index, _point in enumerate(ring):
            prefix = f"geometry-ring-{ring_index:03d}-point-{point_index:04d}"
            for coordinate in ("x", "y"):
                leaves.append(
                    rows.add(
                        f"{prefix}-{coordinate}",
                        f"Concrete vertex {coordinate}",
                        LENGTH,
                        ROLE_USER_INPUT,
                        INPUT_SOURCE,
                    )
                )
    for kind, elements in (
        ("bar", blocks.geometry.bars),
        ("tendon", blocks.geometry.tendons),
    ):
        for index, _element in enumerate(elements):
            prefix = f"geometry-{kind}-{index:04d}"
            for field, unit in (("x", LENGTH), ("y", LENGTH), ("area", AREA)):
                leaves.append(
                    rows.add(
                        f"{prefix}-{field}",
                        f"{kind.title()} {field}",
                        unit,
                        ROLE_USER_INPUT,
                        INPUT_SOURCE,
                    )
                )
    rows.add(
        "geometry-vector",
        "Immutable section geometry",
        ONE,
        ROLE_COMPUTED,
        SOLVER_SOURCE,
        *leaves,
    )


def _materials(rows: _Rows, blocks: SectionTraceBlocks) -> None:
    leaves = []
    for material in (blocks.concrete, *blocks.bars, *blocks.tendons):
        for name, _value in material.values:
            leaves.append(
                rows.add(
                    material_step_id(material, name),
                    f"{material.kind.title()} law {name}",
                    _material_unit(name),
                    ROLE_METHOD_VALUE,
                    material.provenance.source,
                )
            )
    rows.add(
        "material-vector",
        "Immutable assigned material laws",
        ONE,
        ROLE_COMPUTED,
        SOLVER_SOURCE,
        *leaves,
    )


def _shared_inputs(
    rows: _Rows,
    blocks: SectionTraceBlocks,
    action_keys: tuple[str, ...],
) -> None:
    _actions(rows, action_keys)
    _geometry(rows, blocks)
    _materials(rows, blocks)


@dataclass(frozen=True, slots=True)
class RadialTraceShape:
    blocks: SectionTraceBlocks
    context_token: str
    axes: tuple[TraceAxis, ...]
    branch: str
    selected_index: int | None
    plan: SweepPlan

    @property
    def calculation_id(self) -> str:
        return f"plastic.{self.context_token}.radial-utilisation"


def radial_trace_shape(
    blocks: SectionTraceBlocks,
    context: Mapping[str, Any],
    plan: SweepPlan,
    branch: str,
    selected_index: int | None,
) -> RadialTraceShape:
    if branch not in RADIAL_BRANCHES:
        raise ValueError("unknown CT-003 branch")
    if not plan.closed:
        raise ValueError("CT-003 requires a closed plastic sweep")
    if branch == RADIAL_FINITE_SELECTED:
        if (
            type(selected_index) is not int
            or type(selected_index) is bool
            or selected_index < 0
            or selected_index >= len(plan.angles)
        ):
            raise ValueError("finite CT-003 needs an in-range selected member")
    elif selected_index is not None:
        raise ValueError("non-selected CT-003 branch cannot declare a member")
    axes = context_axes(
        context,
        **{
            "branch": branch,
            "cardinality": str(len(plan.angles)),
            "selected-member": (
                "none" if selected_index is None else str(selected_index)
            ),
        },
    )
    return RadialTraceShape(
        blocks,
        context_id(context),
        axes,
        branch,
        selected_index,
        plan,
    )


@dataclass(frozen=True, slots=True)
class InteractionMemberPlan:
    retained_index: int
    branch: str
    sample_index: int
    angle: float


def interaction_member_plan(axis: str) -> tuple[InteractionMemberPlan, ...]:
    if axis not in INTERACTION_ANGLES:
        raise ValueError("interaction axis must be x or y")
    positive_angle, negative_angle = INTERACTION_ANGLES[axis]
    positive = tuple(
        InteractionMemberPlan(index, "positive", index, positive_angle)
        for index in range(INTERACTION_BRANCH_CARDINALITY)
    )
    negative = tuple(
        InteractionMemberPlan(
            INTERACTION_BRANCH_CARDINALITY + offset,
            "negative",
            sample_index,
            negative_angle,
        )
        for offset, sample_index in enumerate(
            reversed(range(INTERACTION_BRANCH_CARDINALITY))
        )
    )
    plan = positive + negative
    if len(plan) != INTERACTION_CARDINALITY:
        raise AssertionError("invalid frozen CT-004 cardinality")
    return plan


@dataclass(frozen=True, slots=True)
class AxisTraceShape:
    blocks: SectionTraceBlocks
    context_token: str
    axes: tuple[TraceAxis, ...]
    axis: str
    branch: str
    members: tuple[InteractionMemberPlan, ...]

    @property
    def calculation_id(self) -> str:
        return f"plastic.{self.context_token}.axis-interaction-{self.axis}"


def axis_trace_shape(
    blocks: SectionTraceBlocks,
    context: Mapping[str, Any],
    axis: str,
    branch: str,
) -> AxisTraceShape:
    if axis not in INTERACTION_ANGLES:
        raise ValueError("CT-004 axis must be x or y")
    if branch not in INTERACTION_BRANCHES:
        raise ValueError("unknown CT-004 branch")
    positive_angle, negative_angle = INTERACTION_ANGLES[axis]
    axes = context_axes(
        context,
        **{
            "axis": axis,
            "branch": branch,
            "cardinality": str(INTERACTION_CARDINALITY),
            "intervals": str(INTERACTION_INTERVALS),
            "positive-angle": repr(positive_angle),
            "negative-angle": repr(negative_angle),
        },
    )
    return AxisTraceShape(
        blocks,
        context_id(context),
        axes,
        axis,
        branch,
        interaction_member_plan(axis),
    )


def radial_step_contract(shape: RadialTraceShape) -> tuple[StepSpec, ...]:
    rows = _Rows("CT-003")
    _shared_inputs(rows, shape.blocks, ("P_pl", "Mx_pl", "My_pl"))
    sweep_leaves = []
    for key in ("v_min", "v_max", "v_inc"):
        sweep_leaves.append(
            rows.add(
                sweep_step_id(key),
                f"Requested {key}",
                ANGLE,
                ROLE_USER_INPUT,
                INPUT_SOURCE,
            )
        )
    rows.add(
        "normalised-sweep-plan",
        "Expected closed radial sweep plan",
        ONE,
        ROLE_COMPUTED,
        SOLVER_SOURCE,
        *sweep_leaves,
    )

    finite_envelope = shape.branch in {
        RADIAL_FINITE_SELECTED,
        RADIAL_FINITE_ZERO,
    }
    member_evidence = []
    convergence_flags = []
    for index, _angle in enumerate(shape.plan.angles):
        identity = rows.add(
            radial_member_step_id(index, "angle"),
            f"Radial envelope member {index} angle",
            ANGLE,
            ROLE_COMPUTED,
            SOLVER_SOURCE,
            "normalised-sweep-plan",
        )
        converged = rows.add(
            radial_member_step_id(index, "converged"),
            f"Radial envelope member {index} convergence",
            ONE,
            ROLE_COMPUTED,
            SOLVER_SOURCE,
            identity,
            "geometry-vector",
            "material-vector",
            "action-vector",
        )
        convergence_flags.append(converged)
        if finite_envelope:
            mx = rows.add(
                radial_member_step_id(index, "mx"),
                f"Radial envelope member {index} Mx",
                MOMENT,
                ROLE_COMPUTED,
                SOLVER_SOURCE,
                identity,
                "geometry-vector",
                "material-vector",
                "action-vector",
            )
            my = rows.add(
                radial_member_step_id(index, "my"),
                f"Radial envelope member {index} My",
                MOMENT,
                ROLE_COMPUTED,
                SOLVER_SOURCE,
                identity,
                "geometry-vector",
                "material-vector",
                "action-vector",
            )
            member_evidence.append(
                rows.add(
                    radial_member_step_id(index, "complete-state"),
                    f"Radial envelope member {index} complete state",
                    ONE,
                    ROLE_COMPUTED,
                    SOLVER_SOURCE,
                    identity,
                    converged,
                    mx,
                    my,
                )
            )

    if not finite_envelope:
        rows.add(
            "failure-count",
            "Failed radial sweep member count",
            ONE,
            ROLE_COMPUTED,
            SOLVER_SOURCE,
            *convergence_flags,
        )
        rows.add(
            "radial-failure-state",
            "Radial calculation failure state",
            ONE,
            ROLE_COMPUTED,
            SELECTION_SOURCE,
            "normalised-sweep-plan",
            "geometry-vector",
            "material-vector",
            "action-vector",
            "failure-count",
        )
        rows.add(
            "radial-utilisation-result",
            "CT-003 radial utilisation",
            ONE,
            ROLE_FINAL,
            SELECTION_SOURCE,
            "radial-failure-state",
        )
        return tuple(rows.rows)

    rows.add(
        "complete-envelope-evidence",
        "Complete ordered radial envelope",
        ONE,
        ROLE_COMPUTED,
        SOLVER_SOURCE,
        *member_evidence,
    )
    rows.add(
        "radial-demand",
        "Applied radial moment demand",
        MOMENT,
        ROLE_COMPUTED,
        SELECTION_SOURCE,
        "action-vector",
    )
    if shape.branch == RADIAL_FINITE_ZERO:
        rows.add(
            "zero-demand-state",
            "Zero radial demand state",
            ONE,
            ROLE_COMPUTED,
            SELECTION_SOURCE,
            "radial-demand",
        )
        rows.add(
            "radial-utilisation-result",
            "CT-003 radial utilisation",
            ONE,
            ROLE_FINAL,
            SELECTION_SOURCE,
            "complete-envelope-evidence",
            "radial-demand",
            "zero-demand-state",
        )
        return tuple(rows.rows)

    rows.add(
        "radial-resistance",
        "Selected radial moment resistance",
        MOMENT,
        ROLE_COMPUTED,
        SELECTION_SOURCE,
        "complete-envelope-evidence",
        "radial-demand",
    )
    rows.add(
        "radial-utilisation",
        "Applied radial utilisation",
        ONE,
        ROLE_COMPUTED,
        SELECTION_SOURCE,
        "radial-demand",
        "radial-resistance",
    )
    rows.add(
        "selected-member-index",
        "Authoritative radial member",
        ONE,
        ROLE_COMPUTED,
        SELECTION_SOURCE,
        "complete-envelope-evidence",
        "radial-demand",
    )
    rows.add(
        "selected-member-evidence",
        "Selected radial member evidence",
        ONE,
        ROLE_COMPUTED,
        SELECTION_SOURCE,
        "selected-member-index",
        member_evidence[shape.selected_index],
    )
    rows.add(
        "demand-resistance-verdict",
        "Radial demand versus resistance verdict",
        ONE,
        ROLE_COMPUTED,
        SELECTION_SOURCE,
        "radial-utilisation",
    )
    rows.add(
        "radial-utilisation-result",
        "CT-003 radial utilisation",
        ONE,
        ROLE_FINAL,
        SELECTION_SOURCE,
        "complete-envelope-evidence",
        "selected-member-evidence",
        "radial-demand",
        "radial-resistance",
        "radial-utilisation",
        "demand-resistance-verdict",
    )
    return tuple(rows.rows)


def axis_step_contract(shape: AxisTraceShape) -> tuple[StepSpec, ...]:
    rows = _Rows(f"CT-004 {shape.axis}")
    moment_key = "Mx_pl" if shape.axis == "x" else "My_pl"
    _shared_inputs(rows, shape.blocks, ("P_pl", moment_key))
    rows.add(
        "interaction-interval-count",
        "Interaction intervals per branch",
        ONE,
        ROLE_METHOD_VALUE,
        SOLVER_SOURCE,
    )
    rows.add(
        "positive-branch-angle",
        "Positive interaction branch angle",
        ANGLE,
        ROLE_METHOD_VALUE,
        SOLVER_SOURCE,
    )
    rows.add(
        "negative-branch-angle",
        "Negative interaction branch angle",
        ANGLE,
        ROLE_METHOD_VALUE,
        SOLVER_SOURCE,
    )
    rows.add(
        "interaction-member-plan",
        "Exact ordered interaction member plan",
        ONE,
        ROLE_COMPUTED,
        SOLVER_SOURCE,
        "interaction-interval-count",
        "positive-branch-angle",
        "negative-branch-angle",
    )

    finite = shape.branch == INTERACTION_FINITE
    if finite:
        for branch in ("positive", "negative"):
            angle_id = f"{branch}-branch-angle"
            rows.add(
                f"{branch}-tension-limit",
                f"{branch.title()} branch tension limit",
                FORCE,
                ROLE_COMPUTED,
                SOLVER_SOURCE,
                angle_id,
                "geometry-vector",
                "material-vector",
            )
            rows.add(
                f"{branch}-compression-limit",
                f"{branch.title()} branch compression limit",
                FORCE,
                ROLE_COMPUTED,
                SOLVER_SOURCE,
                angle_id,
                "geometry-vector",
                "material-vector",
            )

    member_evidence = []
    convergence_flags = []
    for member in shape.members:
        angle = rows.add(
            interaction_member_step_id(member.retained_index, "angle"),
            f"Boundary member {member.retained_index} branch angle",
            ANGLE,
            ROLE_COMPUTED,
            SOLVER_SOURCE,
            "interaction-member-plan",
        )
        sample = rows.add(
            interaction_member_step_id(member.retained_index, "sample-index"),
            f"Boundary member {member.retained_index} source sample",
            ONE,
            ROLE_COMPUTED,
            SOLVER_SOURCE,
            angle,
        )
        converged = rows.add(
            interaction_member_step_id(member.retained_index, "converged"),
            f"Boundary member {member.retained_index} convergence",
            ONE,
            ROLE_COMPUTED,
            SOLVER_SOURCE,
            sample,
            "geometry-vector",
            "material-vector",
        )
        convergence_flags.append(converged)
        if finite:
            axial = rows.add(
                interaction_member_step_id(member.retained_index, "axial"),
                f"Boundary member {member.retained_index} axial force",
                FORCE,
                ROLE_COMPUTED,
                SOLVER_SOURCE,
                sample,
                f"{member.branch}-tension-limit",
                f"{member.branch}-compression-limit",
                "geometry-vector",
                "material-vector",
            )
            moment = rows.add(
                interaction_member_step_id(member.retained_index, "moment"),
                f"Boundary member {member.retained_index} {shape.axis} moment",
                MOMENT,
                ROLE_COMPUTED,
                SOLVER_SOURCE,
                sample,
                axial,
                "geometry-vector",
                "material-vector",
            )
            member_evidence.append(
                rows.add(
                    interaction_member_step_id(
                        member.retained_index, "complete-state"
                    ),
                    f"Boundary member {member.retained_index} complete state",
                    ONE,
                    ROLE_COMPUTED,
                    SOLVER_SOURCE,
                    angle,
                    sample,
                    converged,
                    axial,
                    moment,
                )
            )

    if finite:
        rows.add(
            "complete-axis-boundary",
            f"Complete ordered {shape.axis}-axis interaction boundary",
            ONE,
            ROLE_COMPUTED,
            SOLVER_SOURCE,
            *member_evidence,
        )
        rows.add(
            "applied-axis-point",
            f"Applied {shape.axis}-axis interaction point",
            ONE,
            ROLE_COMPUTED,
            SOLVER_SOURCE,
            "action-vector",
        )
        rows.add(
            "axis-interaction-result",
            f"CT-004 {shape.axis}-axis interaction boundary",
            ONE,
            ROLE_FINAL,
            SOLVER_SOURCE,
            "complete-axis-boundary",
            "applied-axis-point",
        )
    else:
        rows.add(
            "failure-count",
            f"Failed {shape.axis}-axis boundary member count",
            ONE,
            ROLE_COMPUTED,
            SOLVER_SOURCE,
            *convergence_flags,
        )
        rows.add(
            "axis-failure-state",
            f"{shape.axis}-axis interaction failure state",
            ONE,
            ROLE_COMPUTED,
            SOLVER_SOURCE,
            "interaction-member-plan",
            "geometry-vector",
            "material-vector",
            "action-vector",
            "failure-count",
        )
        rows.add(
            "axis-interaction-result",
            f"CT-004 {shape.axis}-axis interaction boundary",
            ONE,
            ROLE_FINAL,
            SOLVER_SOURCE,
            "axis-failure-state",
        )
    return tuple(rows.rows)


def _source_contract(source: TraceSource) -> TraceSourceContract:
    return TraceSourceContract(source.kind, source.method_id, source.edition)


def _member_contract(
    *,
    calculation_id: str,
    coverage_id: str,
    member_id: str,
    method_id: str,
    axes: tuple[TraceAxis, ...],
    specs: tuple[StepSpec, ...],
    result_state: str,
) -> TraceMemberContract:
    return TraceMemberContract(
        member_id=member_id,
        calculation_id=calculation_id,
        coverage_id=coverage_id,
        method_id=method_id,
        axes=axes,
        sources=frozenset(_source_contract(spec.source) for spec in specs),
        result_states=frozenset({result_state}),
        step_ids=tuple(spec.step_id for spec in specs),
        step_dependencies=tuple(
            (spec.step_id, spec.dependencies) for spec in specs
        ),
        step_metadata=tuple(
            TraceStepMetadataContract(
                spec.step_id, spec.quantity_role, spec.source
            )
            for spec in specs
        ),
    )


def expected_registry(
    radial: RadialTraceShape,
    x_axis: AxisTraceShape,
    y_axis: AxisTraceShape,
) -> TraceRegistryContract:
    """Declare all required PR-08B.4 families without reading a candidate."""

    if x_axis.axis != "x" or y_axis.axis != "y":
        raise ValueError("CT-004 registry requires exact x then y shapes")
    if not (radial.blocks == x_axis.blocks == y_axis.blocks):
        raise ValueError("PR-08B.4 families must share one immutable block set")
    if not (
        radial.context_token == x_axis.context_token == y_axis.context_token
    ):
        raise ValueError("PR-08B.4 families must share one exact context")
    radial_specs = radial_step_contract(radial)
    x_specs = axis_step_contract(x_axis)
    y_specs = axis_step_contract(y_axis)
    radial_member = _member_contract(
        calculation_id=radial.calculation_id,
        coverage_id=RADIAL_COVERAGE_ID,
        member_id=RADIAL_MEMBER_ID,
        method_id=radial.blocks.plastic_method_id,
        axes=radial.axes,
        specs=radial_specs,
        result_state=(
            RESULT_FINITE
            if radial.branch
            in {RADIAL_FINITE_SELECTED, RADIAL_FINITE_ZERO}
            else RESULT_FAILED
        ),
    )

    def axis_family(shape: AxisTraceShape, specs: tuple[StepSpec, ...]):
        member = _member_contract(
            calculation_id=shape.calculation_id,
            coverage_id=INTERACTION_COVERAGE_ID,
            member_id=INTERACTION_MEMBER_IDS[shape.axis],
            method_id=shape.blocks.plastic_method_id,
            axes=shape.axes,
            specs=specs,
            result_state=(
                RESULT_FINITE
                if shape.branch == INTERACTION_FINITE
                else RESULT_FAILED
            ),
        )
        return TraceFamilyContract(
            INTERACTION_FAMILY_IDS[shape.axis], (member,)
        )

    return TraceRegistryContract(
        REGISTRY_ID,
        (
            TraceFamilyContract(RADIAL_FAMILY_ID, (radial_member,)),
            axis_family(x_axis, x_specs),
            axis_family(y_axis, y_specs),
        ),
    )
