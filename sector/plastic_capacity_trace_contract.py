"""Independent CT-002 shape, step, and registry declarations."""

from __future__ import annotations

import math
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


COVERAGE_ID = "ct-002"
FAMILY_ID = "ct-002-selected-plastic-capacity"
MEMBER_ID = "selected-plastic-capacity"
REGISTRY_ID = "sector-ct-002-selected-plastic-capacity-v5"

BRANCH_FINITE_SELECTED = "finite-selected"
BRANCH_FAILED_SELECTED = "failed-selected"
BRANCH_FAILED_UNSELECTED = "failed-unselected"
BRANCHES = frozenset(
    {
        BRANCH_FINITE_SELECTED,
        BRANCH_FAILED_SELECTED,
        BRANCH_FAILED_UNSELECTED,
    }
)

INPUT_SOURCE = TraceSource(SOURCE_INPUT, "sector-section-input")
SOLVER_SOURCE = TraceSource(SOURCE_PROJECT, "sector-plastic-section-solver")
SELECTION_SOURCE = TraceSource(SOURCE_PROJECT, "sector-radial-envelope-selector")

ONE = TraceUnit("1", "scalar")
LENGTH = TraceUnit("m", "length")
AREA = TraceUnit("m2", "area")
FORCE = TraceUnit("kN", "force")
MOMENT = TraceUnit("kNm", "moment")
ANGLE = TraceUnit("degrees", "angle")
CURVATURE = TraceUnit("1/m", "curvature")
STRAIN = TraceUnit("%", "strain")
STRAIN_FRACTION = TraceUnit("1", "strain")
STRESS = TraceUnit("MPa", "stress")

ACTION_KEYS = ("P_pl", "Mx_pl", "My_pl")
SWEEP_KEYS = ("v_min", "v_max", "v_inc")

POINT_FIELDS = (
    "Mx",
    "My",
    "axial_requested",
    "axial_achieved",
    "axial_residual",
    "axial_tolerance",
    "axial_reachable",
    "compression_depth",
    "neutral_axis_offset",
    "kappa",
    "strain_gradient_x",
    "strain_gradient_y",
    "strain_offset",
    "eps_c",
    "eps_s",
    "eps_s_comp",
    "eps_cable",
    "concrete_force",
    "concrete_mx",
    "concrete_my",
    "bar_force",
    "bar_mx",
    "bar_my",
    "tendon_force",
    "tendon_mx",
    "tendon_my",
    "comp_force",
    "compression_mx",
    "compression_my",
    "tension_force",
    "tension_mx",
    "tension_my",
    "lever",
    "dx",
    "dy",
    "search_lower_depth",
    "search_upper_depth",
    "search_lower_axial",
    "search_upper_axial",
    "search_iterations",
    "converged",
)


def _number(value: object, label: str) -> float:
    if type(value) not in {int, float} or type(value) is bool:
        raise ValueError(f"{label} must be a finite non-Boolean number")
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError(f"{label} must be a finite non-Boolean number")
    return converted


@dataclass(frozen=True, slots=True)
class SweepPlan:
    """Expected solver sweep derived only from the three requested inputs."""

    requested_min: float
    requested_max: float
    requested_increment: float
    solver_min: float
    solver_max: float
    solver_increment: float
    closed: bool
    angles: tuple[float, ...]


def expected_sweep(v_min: object, v_max: object, v_inc: object) -> SweepPlan:
    """Reproduce the canonical closed-turn plan without reading result arrays."""

    requested_min = _number(v_min, "v_min")
    requested_max = _number(v_max, "v_max")
    requested_increment = _number(v_inc, "v_inc")
    span = max(requested_max, requested_min) - requested_min
    if span < 1.0e-9 or requested_increment <= 0.0:
        solver_min = solver_max = requested_min
        solver_increment = max(requested_increment, 1.0)
    else:
        intervals = max(1, math.ceil(span / requested_increment))
        solver_min = requested_min
        solver_max = requested_min + span
        solver_increment = span / intervals
    closed = solver_max - solver_min >= 360.0 - 1.0e-6
    sweep_max = solver_max - solver_increment if closed else solver_max
    count = (
        int(round((sweep_max - solver_min) / solver_increment))
        if solver_increment
        else 0
    )
    angles = tuple(solver_min + index * solver_increment for index in range(count + 1))
    if not angles:
        raise ValueError("CT-002 sweep must contain a member")
    return SweepPlan(
        requested_min,
        requested_max,
        requested_increment,
        solver_min,
        solver_max,
        solver_increment,
        closed,
        angles,
    )


@dataclass(frozen=True, slots=True)
class TraceShape:
    blocks: SectionTraceBlocks
    context_token: str
    axes: tuple[TraceAxis, ...]
    branch: str
    selected_index: int | None
    plan: SweepPlan

    @property
    def calculation_id(self) -> str:
        return f"plastic.{self.context_token}.selected-capacity"


def trace_shape(
    blocks: SectionTraceBlocks,
    context: Mapping[str, Any],
    plan: SweepPlan,
    branch: str,
    selected_index: int | None,
) -> TraceShape:
    if branch not in BRANCHES:
        raise ValueError("unknown CT-002 branch")
    if not plan.closed:
        raise ValueError("CT-002 requires a closed plastic sweep")
    if branch == BRANCH_FAILED_UNSELECTED:
        if selected_index is not None:
            raise ValueError("failed-unselected cannot declare a selected member")
    elif (
        type(selected_index) is not int
        or type(selected_index) is bool
        or selected_index < 0
        or selected_index >= len(plan.angles)
    ):
        raise ValueError("selected CT-002 branch needs an in-range member")
    axes = context_axes(
        context,
        branch=branch,
        cardinality=str(len(plan.angles)),
        selected_member=("none" if selected_index is None else str(selected_index)),
    )
    return TraceShape(
        blocks,
        context_id(context),
        axes,
        branch,
        selected_index,
        plan,
    )


@dataclass(frozen=True, slots=True)
class StepSpec:
    step_id: str
    title: str
    unit: TraceUnit
    quantity_role: str
    source: TraceSource
    dependencies: tuple[str, ...] = ()


class _Rows:
    def __init__(self) -> None:
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
            raise ValueError(f"duplicate CT-002 step {step_id}")
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


def member_identity_id(index: int) -> str:
    return f"member-{index:04d}-angle"


def point_step_id(index: int, field: str) -> str:
    return f"member-{index:04d}-{field.replace('_', '-').lower()}"


def point_evidence_id(index: int) -> str:
    return f"member-{index:04d}-complete-state"


def _geometry(rows: _Rows, shape: TraceShape) -> tuple[str, ...]:
    leaves: list[str] = []
    for ring_index, ring in enumerate(shape.blocks.geometry.rings):
        for point_index, (x, y) in enumerate(ring):
            prefix = f"geometry-ring-{ring_index:03d}-point-{point_index:04d}"
            leaves.append(
                rows.add(
                    f"{prefix}-x", "Concrete vertex x", LENGTH,
                    ROLE_USER_INPUT, INPUT_SOURCE,
                )
            )
            leaves.append(
                rows.add(
                    f"{prefix}-y", "Concrete vertex y", LENGTH,
                    ROLE_USER_INPUT, INPUT_SOURCE,
                )
            )
    for kind, elements in (
        ("bar", shape.blocks.geometry.bars),
        ("tendon", shape.blocks.geometry.tendons),
    ):
        for index, _element in enumerate(elements):
            prefix = f"geometry-{kind}-{index:04d}"
            for suffix, unit in (("x", LENGTH), ("y", LENGTH), ("area", AREA)):
                leaves.append(
                    rows.add(
                        f"{prefix}-{suffix}", f"{kind.title()} {suffix}", unit,
                        ROLE_USER_INPUT, INPUT_SOURCE,
                    )
                )
    rows.add(
        "geometry-vector", "Immutable section geometry", ONE, ROLE_COMPUTED,
        SOLVER_SOURCE, *leaves,
    )
    return tuple(leaves)


def _material_prefix(material: MaterialBlock) -> str:
    return (
        f"material-{material.kind}-{_token(material.element_id)}-"
        f"{_token(material.material_id)}"
    )


def _material_unit(name: str) -> TraceUnit:
    if name in {"fck", "fytk", "fyck", "futk", "Es"}:
        return STRESS
    if name in {"eps_c2", "eps_cu2", "eut", "ey0t", "ey0c", "IS"}:
        return STRAIN_FRACTION
    return ONE


def _materials(rows: _Rows, shape: TraceShape) -> tuple[str, ...]:
    leaves: list[str] = []
    for material in (
        shape.blocks.concrete,
        *shape.blocks.bars,
        *shape.blocks.tendons,
    ):
        prefix = _material_prefix(material)
        for name, _value in material.values:
            leaves.append(
                rows.add(
                    f"{prefix}-{_token(name)}",
                    f"{material.kind.title()} law {name}",
                    _material_unit(name),
                    ROLE_METHOD_VALUE,
                    material.provenance.source,
                )
            )
    rows.add(
        "material-vector", "Immutable assigned material laws", ONE,
        ROLE_COMPUTED, SOLVER_SOURCE, *leaves,
    )
    return tuple(leaves)


_FORCE_FIELDS = frozenset(
    {
        "axial_requested",
        "axial_achieved",
        "axial_residual",
        "axial_tolerance",
        "concrete_force",
        "bar_force",
        "tendon_force",
        "comp_force",
        "tension_force",
        "search_lower_axial",
        "search_upper_axial",
    }
)
_MOMENT_FIELDS = frozenset(
    {
        "Mx",
        "My",
        "concrete_mx",
        "concrete_my",
        "bar_mx",
        "bar_my",
        "tendon_mx",
        "tendon_my",
        "compression_mx",
        "compression_my",
        "tension_mx",
        "tension_my",
    }
)
_LENGTH_FIELDS = frozenset(
    {
        "compression_depth",
        "neutral_axis_offset",
        "lever",
        "dx",
        "dy",
        "search_lower_depth",
        "search_upper_depth",
    }
)
_STRAIN_FIELDS = frozenset({"eps_c", "eps_s", "eps_s_comp", "eps_cable"})
_CURVATURE_FIELDS = frozenset(
    {"kappa", "strain_gradient_x", "strain_gradient_y"}
)


def point_unit(field: str) -> TraceUnit:
    if field in _FORCE_FIELDS:
        return FORCE
    if field in _MOMENT_FIELDS:
        return MOMENT
    if field in _LENGTH_FIELDS:
        return LENGTH
    if field in _STRAIN_FIELDS:
        return STRAIN
    if field in _CURVATURE_FIELDS:
        return CURVATURE
    return ONE


def _inputs(rows: _Rows, shape: TraceShape, *, finite: bool) -> None:
    if finite:
        action_ids = []
        for key in ACTION_KEYS:
            unit = FORCE if key == "P_pl" else MOMENT
            action_ids.append(
                rows.add(
                    action_step_id(key), f"Requested {key}", unit,
                    ROLE_USER_INPUT, INPUT_SOURCE,
                )
            )
        rows.add(
            "action-vector", "Requested plastic action", ONE, ROLE_COMPUTED,
            SOLVER_SOURCE, *action_ids,
        )
    sweep_ids = []
    for key in SWEEP_KEYS:
        sweep_ids.append(
            rows.add(
                sweep_step_id(key), f"Requested {key}", ANGLE,
                ROLE_USER_INPUT, INPUT_SOURCE,
            )
        )
    rows.add(
        "normalised-sweep-plan", "Expected closed sweep plan", ONE,
        ROLE_COMPUTED, SOLVER_SOURCE, *sweep_ids,
    )


def _failure_contract(rows: _Rows, shape: TraceShape) -> None:
    flags = []
    for index, _angle in enumerate(shape.plan.angles):
        identity = rows.add(
            member_identity_id(index), f"Expected member {index} angle", ANGLE,
            ROLE_COMPUTED, SOLVER_SOURCE, "normalised-sweep-plan",
        )
        flags.append(
            rows.add(
                point_step_id(index, "converged"),
                f"Member {index} Boolean convergence flag",
                ONE,
                ROLE_COMPUTED,
                SOLVER_SOURCE,
                identity,
            )
        )
    rows.add(
        "failure-count", "Failed sweep member count", ONE, ROLE_COMPUTED,
        SOLVER_SOURCE, *flags,
    )
    rows.add(
        "failure-state", "Plastic sweep failure state", ONE, ROLE_COMPUTED,
        SOLVER_SOURCE, "failure-count",
    )
    final_dependencies = [
        "normalised-sweep-plan",
        "failure-count",
        "failure-state",
    ]
    if shape.branch == BRANCH_FAILED_SELECTED:
        final_dependencies.append(
            rows.add(
                "selected-member-index", "Replay selector member", ONE,
                ROLE_COMPUTED, SELECTION_SOURCE,
                "normalised-sweep-plan", *flags,
            )
        )
    rows.add(
        "selected-plastic-capacity-result",
        "CT-002 selected plastic capacity",
        ONE,
        ROLE_FINAL,
        SOLVER_SOURCE,
        *final_dependencies,
    )


def _finite_contract(rows: _Rows, shape: TraceShape) -> None:
    _geometry(rows, shape)
    _materials(rows, shape)
    point_evidence = []
    for index, _angle in enumerate(shape.plan.angles):
        identity = rows.add(
            member_identity_id(index), f"Expected member {index} angle", ANGLE,
            ROLE_COMPUTED, SOLVER_SOURCE, "normalised-sweep-plan",
        )
        fields = []
        for field in POINT_FIELDS:
            fields.append(
                rows.add(
                    point_step_id(index, field),
                    f"Member {index} {field}",
                    point_unit(field),
                    ROLE_COMPUTED,
                    SOLVER_SOURCE,
                    identity,
                    "action-vector",
                    "geometry-vector",
                    "material-vector",
                )
            )
        point_evidence.append(
            rows.add(
                point_evidence_id(index), f"Member {index} complete state", ONE,
                ROLE_COMPUTED, SOLVER_SOURCE, *fields,
            )
        )
    rows.add(
        "complete-envelope-evidence", "Complete aligned plastic envelope", ONE,
        ROLE_COMPUTED, SOLVER_SOURCE, *point_evidence,
    )
    rows.add(
        "radial-demand", "Applied radial moment demand", MOMENT, ROLE_COMPUTED,
        SELECTION_SOURCE, "action-vector",
    )
    rows.add(
        "radial-resistance", "Selected radial moment resistance", MOMENT,
        ROLE_COMPUTED, SELECTION_SOURCE,
        "complete-envelope-evidence", "radial-demand",
    )
    rows.add(
        "radial-utilisation", "Applied radial utilisation", ONE, ROLE_COMPUTED,
        SELECTION_SOURCE, "radial-demand", "radial-resistance",
    )
    rows.add(
        "selected-member-index", "Authoritative selected member", ONE,
        ROLE_COMPUTED, SELECTION_SOURCE,
        "complete-envelope-evidence", "radial-demand",
    )
    rows.add(
        "selected-member-evidence", "Selected complete member state", ONE,
        ROLE_COMPUTED, SELECTION_SOURCE,
        "selected-member-index", point_evidence[shape.selected_index],
    )
    rows.add(
        "demand-resistance-verdict", "Demand versus resistance verdict", ONE,
        ROLE_COMPUTED, SELECTION_SOURCE, "radial-utilisation",
    )
    rows.add(
        "selected-plastic-capacity-result",
        "CT-002 selected plastic capacity",
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


def expected_step_contract(shape: TraceShape) -> tuple[StepSpec, ...]:
    rows = _Rows()
    finite = shape.branch == BRANCH_FINITE_SELECTED
    _inputs(rows, shape, finite=finite)
    if finite:
        _finite_contract(rows, shape)
    else:
        _failure_contract(rows, shape)
    return tuple(rows.rows)


def _source_contract(source: TraceSource) -> TraceSourceContract:
    return TraceSourceContract(source.kind, source.method_id, source.edition)


def expected_registry(shape: TraceShape) -> TraceRegistryContract:
    """Declare CT-002 without inspecting a candidate calculation or bundle."""

    specs = expected_step_contract(shape)
    member = TraceMemberContract(
        member_id=MEMBER_ID,
        calculation_id=shape.calculation_id,
        coverage_id=COVERAGE_ID,
        method_id=shape.blocks.plastic_method_id,
        axes=shape.axes,
        sources=frozenset(_source_contract(spec.source) for spec in specs),
        result_states=frozenset(
            {
                RESULT_FINITE
                if shape.branch == BRANCH_FINITE_SELECTED
                else RESULT_FAILED
            }
        ),
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
    return TraceRegistryContract(
        REGISTRY_ID,
        (TraceFamilyContract(FAMILY_ID, (member,)),),
    )
