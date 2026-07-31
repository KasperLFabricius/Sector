"""Independent exact contract for unpublished CT-002 capacity traces."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

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
REGISTRY_ID = "sector-ct-002-selected-plastic-capacity-v4"

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
SELECTION_SOURCE = TraceSource(
    SOURCE_PROJECT,
    "sector-plastic-radial-selector",
)

ACTION_KEYS = ("P_pl", "Mx_pl", "My_pl")
SWEEP_KEYS = ("v_min", "v_max", "v_inc")
POINT_FIELDS = (
    "V", "compression_depth", "kappa", "neutral_axis_depth", "na_x", "na_y",
    "eps_c", "eps_s", "eps_s_comp", "eps_cable", "requested_axial",
    "concrete_force", "concrete_mx", "concrete_my",
    "bar_force", "bar_mx", "bar_my",
    "tendon_force", "tendon_mx", "tendon_my",
    "comp_force", "comp_mx", "comp_my",
    "tension_force", "tension_mx", "tension_my",
    "achieved_axial", "axial_residual", "axial_tolerance", "converged",
    "Mx", "My", "dx", "dy", "lever",
)

ONE = TraceUnit("1", "scalar")
LENGTH = TraceUnit("m", "length")
FORCE = TraceUnit("kN", "force")
MOMENT = TraceUnit("kNm", "moment")
ANGLE = TraceUnit("degrees", "angle")
CURVATURE = TraceUnit("1/m", "curvature")
STRAIN = TraceUnit("%", "strain")


@dataclass(frozen=True, slots=True)
class SweepPlan:
    """Independent requested-to-solver sweep derivation for CT-002."""

    requested_min: float
    requested_max: float
    requested_increment: float
    solver_min: float
    solver_max: float
    solver_increment: float
    closed: bool
    angles: tuple[float, ...]


def expected_sweep(v_min: object, v_max: object, v_inc: object) -> SweepPlan:
    """Derive the exact retained angle order directly from user inputs."""

    values = []
    for label, value in zip(SWEEP_KEYS, (v_min, v_max, v_inc)):
        if (
            type(value) not in {int, float}
            or type(value) is bool
            or not math.isfinite(float(value))
        ):
            raise ValueError(f"{label} must be a finite non-Boolean number")
        values.append(float(value))
    requested_min, requested_max, requested_increment = values
    span = max(requested_max, requested_min) - requested_min
    if span < 1.0e-9 or requested_increment <= 0.0:
        normalised_max = requested_min
        normalised_increment = max(requested_increment, 1.0)
    else:
        intervals = max(1, math.ceil(span / requested_increment))
        normalised_max = requested_min + span
        normalised_increment = span / intervals
    closed = normalised_max - requested_min >= 360.0 - 1.0e-6
    solver_max = (
        normalised_max - normalised_increment if closed else normalised_max
    )
    count = int(
        round((solver_max - requested_min) / normalised_increment)
    ) + 1
    angles = tuple(
        requested_min + index * normalised_increment
        for index in range(count)
    )
    return SweepPlan(
        requested_min,
        requested_max,
        requested_increment,
        requested_min,
        solver_max,
        normalised_increment,
        closed,
        angles,
    )


@dataclass(frozen=True, slots=True)
class TraceShape:
    blocks: SectionTraceBlocks
    context_token: str
    context_axes: tuple[TraceAxis, ...]
    expected_angles: tuple[float, ...]
    branch: str
    selected_index: int | None

    @property
    def cardinality(self) -> int:
        return len(self.expected_angles)

    @property
    def calculation_id(self) -> str:
        return f"plastic.{self.context_token}.selected-capacity"

    @property
    def axes(self) -> tuple[TraceAxis, ...]:
        extras = {
            "result_branch": self.branch,
            "retained_cardinality": str(self.cardinality),
            "selected_member": (
                "none" if self.selected_index is None else str(self.selected_index)
            ),
        }
        return (
            *self.context_axes,
            *(TraceAxis(key, value) for key, value in sorted(extras.items())),
        )


def trace_shape(
    blocks: SectionTraceBlocks,
    context: Mapping[str, object],
    *,
    expected_angles: tuple[float, ...],
    branch: str,
    selected_index: int | None,
) -> TraceShape:
    if (
        type(expected_angles) is not tuple
        or not expected_angles
        or any(
            type(value) is not float or not math.isfinite(value)
            for value in expected_angles
        )
        or len(set(expected_angles)) != len(expected_angles)
    ):
        raise ValueError("CT-002 expected sweep angles must be exact and unique")
    if branch not in BRANCHES:
        raise ValueError(f"unknown CT-002 branch {branch!r}")
    if branch == BRANCH_FAILED_UNSELECTED:
        if selected_index is not None:
            raise ValueError("failed-unselected cannot declare a member")
    elif (
        type(selected_index) is not int
        or type(selected_index) is bool
        or selected_index < 0
        or selected_index >= len(expected_angles)
    ):
        raise ValueError("selected CT-002 branch needs an in-range member")
    return TraceShape(
        blocks,
        context_id(context),
        context_axes(context),
        expected_angles,
        branch,
        selected_index,
    )


@dataclass(frozen=True, slots=True)
class StepSpec:
    """Merged order, dependency, role, source, and unit contract."""

    step_id: str
    dependencies: tuple[str, ...]
    quantity_role: str
    source: TraceSource
    unit: TraceUnit


def _token(value: str) -> str:
    return value.lower().replace("_", "-")


def action_step_id(key: str) -> str:
    return f"input-action-{_token(key)}"


def sweep_step_id(key: str) -> str:
    return f"input-sweep-{_token(key)}"


def material_items(
    blocks: SectionTraceBlocks,
) -> tuple[tuple[str, MaterialBlock], ...]:
    return (
        ("concrete", blocks.concrete),
        *((f"bar-{i:03d}", item) for i, item in enumerate(blocks.bars)),
        *((f"tendon-{i:03d}", item) for i, item in enumerate(blocks.tendons)),
    )


def material_vector_id(prefix: str) -> str:
    return f"material-{prefix}-block"


def member_identity_id(index: int) -> str:
    return f"member-{index:03d}-identity"


def point_step_id(index: int, field: str) -> str:
    token = "angle" if field == "V" else _token(field)
    return f"member-{index:03d}-{token}"


def point_evidence_id(index: int) -> str:
    return f"member-{index:03d}-solver-evidence"


class _Rows:
    def __init__(self) -> None:
        self.items: list[StepSpec] = []
        self.ids: set[str] = set()

    def add(
        self,
        step_id: str,
        *dependencies: str,
        role: str = ROLE_COMPUTED,
        source: TraceSource = SOLVER_SOURCE,
        unit: TraceUnit = ONE,
    ) -> str:
        if step_id in self.ids:
            raise ValueError(f"duplicate CT-002 contract step {step_id}")
        self.ids.add(step_id)
        self.items.append(
            StepSpec(step_id, tuple(dependencies), role, source, unit)
        )
        return step_id


def _inputs(rows: _Rows, *, actions: bool) -> None:
    if actions:
        for key in ACTION_KEYS:
            rows.add(
                action_step_id(key),
                role=ROLE_USER_INPUT,
                source=INPUT_SOURCE,
                unit=FORCE if key == "P_pl" else MOMENT,
            )
    for key in SWEEP_KEYS:
        rows.add(
            sweep_step_id(key),
            role=ROLE_USER_INPUT,
            source=INPUT_SOURCE,
            unit=ANGLE,
        )
    rows.add(
        "normalised-sweep-plan",
        *(sweep_step_id(key) for key in SWEEP_KEYS),
    )


def _geometry(rows: _Rows, shape: TraceShape) -> tuple[str, ...]:
    groups = [
        rows.add(
            "geometry-concrete-block",
            role=ROLE_USER_INPUT,
            source=INPUT_SOURCE,
        )
    ]
    for kind, elements in (
        ("bar", shape.blocks.geometry.bars),
        ("tendon", shape.blocks.geometry.tendons),
    ):
        if elements:
            groups.append(
                rows.add(
                    f"geometry-{kind}s-block",
                    role=ROLE_USER_INPUT,
                    source=INPUT_SOURCE,
                )
            )
    return tuple(groups)


def _materials(rows: _Rows, shape: TraceShape) -> tuple[str, ...]:
    concrete = ""
    bars = []
    tendons = []
    for prefix, block in material_items(shape.blocks):
        vector = rows.add(
            material_vector_id(prefix),
            role=ROLE_METHOD_VALUE,
            source=block.provenance.source,
        )
        if prefix == "concrete":
            concrete = vector
        elif prefix.startswith("bar-"):
            bars.append(vector)
        else:
            tendons.append(vector)
    groups = [concrete]
    if bars:
        groups.append(rows.add("material-bars-block", *bars))
    if tendons:
        groups.append(rows.add("material-tendons-block", *tendons))
    return tuple(groups)


_FORCE_FIELDS = frozenset(
    {
        "requested_axial", "achieved_axial", "axial_residual", "axial_tolerance",
        "concrete_force", "bar_force", "tendon_force",
        "comp_force", "tension_force",
    }
)
_MOMENT_FIELDS = frozenset({"Mx", "My"}) | frozenset(
    f"{kind}_{axis}"
    for kind in ("concrete", "bar", "tendon", "comp", "tension")
    for axis in ("mx", "my")
)
_LENGTH_FIELDS = frozenset(
    {"compression_depth", "neutral_axis_depth", "na_x", "na_y", "dx", "dy", "lever"}
)
_STRAIN_FIELDS = frozenset({"eps_c", "eps_s", "eps_s_comp", "eps_cable"})


def _point_unit(field: str) -> TraceUnit:
    if field == "V":
        return ANGLE
    if field == "kappa":
        return CURVATURE
    if field in _FORCE_FIELDS:
        return FORCE
    if field in _MOMENT_FIELDS:
        return MOMENT
    if field in _LENGTH_FIELDS:
        return LENGTH
    if field in _STRAIN_FIELDS:
        return STRAIN
    return ONE


def _point_dependencies(index: int, field: str) -> tuple[str, ...]:
    point = lambda name: point_step_id(index, name)
    plane = (point("V"), point("compression_depth"), point("kappa"))
    if field == "V":
        return (member_identity_id(index), "normalised-sweep-plan")
    if field == "compression_depth":
        return ("section-input-closure", point("V"))
    if field in {"kappa", "neutral_axis_depth"}:
        return ("section-input-closure", point("V"), point("compression_depth"))
    if field in {"na_x", "na_y"}:
        return (point("V"), point("neutral_axis_depth"))
    if field in _STRAIN_FIELDS:
        return ("section-input-closure", *plane)
    if field == "requested_axial":
        return ("requested-solver-axial",)
    if field.startswith(("concrete_", "bar_", "tendon_")):
        return ("section-input-closure", *plane)
    if field.startswith(("comp_", "tension_")):
        return ("section-input-closure", *plane)
    if field == "achieved_axial":
        return tuple(point(f"{kind}_force") for kind in ("concrete", "bar", "tendon"))
    if field == "axial_residual":
        return (point("achieved_axial"), point("requested_axial"))
    if field == "axial_tolerance":
        return (point("requested_axial"), "solver-axial-tolerance-factor")
    if field == "converged":
        return (point("axial_residual"), point("axial_tolerance"))
    if field in {"Mx", "My"}:
        suffix = field.lower()
        return tuple(point(f"{kind}_{suffix}") for kind in ("concrete", "bar", "tendon"))
    if field == "dx":
        names = ("comp_force", "comp_my", "tension_force", "tension_my")
        return tuple(point(name) for name in names)
    if field == "dy":
        names = ("comp_force", "comp_mx", "tension_force", "tension_mx")
        return tuple(point(name) for name in names)
    if field == "lever":
        return (point("dx"), point("dy"))
    raise ValueError(f"unknown CT-002 point field {field}")


def _failure_contract(shape: TraceShape, rows: _Rows) -> None:
    identities = []
    flags = []
    for index in range(shape.cardinality):
        identity = rows.add(member_identity_id(index), "normalised-sweep-plan")
        angle = rows.add(
            point_step_id(index, "V"),
            identity,
            "normalised-sweep-plan",
            unit=ANGLE,
        )
        identities.extend((identity, angle))
        flags.append(rows.add(point_step_id(index, "converged"), angle))
    rows.add("failure-count", *flags)
    rows.add("failure-state", "failure-count")
    selected = ()
    if shape.branch == BRANCH_FAILED_SELECTED:
        selected = (
            rows.add(
                "selected-member-index",
                *identities,
                *flags,
                source=SELECTION_SOURCE,
            ),
        )
    rows.add(
        "selected-plastic-capacity-result",
        "normalised-sweep-plan",
        *identities,
        *flags,
        "failure-count",
        "failure-state",
        *selected,
        role=ROLE_FINAL,
    )


def _finite_contract(shape: TraceShape, rows: _Rows) -> None:
    geometry = _geometry(rows, shape)
    materials = _materials(rows, shape)
    rows.add(
        "solver-integration-bands",
        role=ROLE_METHOD_VALUE,
        source=SOLVER_SOURCE,
    )
    rows.add(
        "solver-axial-tolerance-factor",
        role=ROLE_METHOD_VALUE,
        source=SOLVER_SOURCE,
    )
    rows.add(
        "section-input-closure",
        action_step_id("P_pl"),
        *geometry,
        *materials,
        "solver-integration-bands",
        "solver-axial-tolerance-factor",
    )
    rows.add(
        "requested-solver-axial",
        action_step_id("P_pl"),
        unit=FORCE,
    )
    point_vectors = []
    for index in range(shape.cardinality):
        rows.add(member_identity_id(index), "normalised-sweep-plan")
        fields = []
        for field in POINT_FIELDS:
            fields.append(
                rows.add(
                    point_step_id(index, field),
                    *_point_dependencies(index, field),
                    unit=_point_unit(field),
                )
            )
        point_vectors.append(rows.add(point_evidence_id(index), *fields))
    rows.add(
        "retained-capacity-arrays",
        *(
            point_step_id(index, field)
            for index in range(shape.cardinality)
            for field in ("V", "Mx", "My")
        ),
    )
    rows.add(
        "retained-envelope-convergence",
        *(point_step_id(i, "converged") for i in range(shape.cardinality)),
    )
    rows.add(
        "solver-run-evidence",
        "requested-solver-axial",
        "retained-capacity-arrays",
        "retained-envelope-convergence",
        *point_vectors,
    )
    rows.add(
        "selected-member-index",
        "retained-capacity-arrays",
        action_step_id("Mx_pl"),
        action_step_id("My_pl"),
        source=SELECTION_SOURCE,
    )
    rows.add(
        "selected-member-evidence",
        "selected-member-index",
        point_evidence_id(shape.selected_index),
    )
    rows.add(
        "retained-radial-demand",
        action_step_id("Mx_pl"),
        action_step_id("My_pl"),
        source=SELECTION_SOURCE,
        unit=MOMENT,
    )
    rows.add(
        "retained-radial-resistance",
        "retained-radial-demand",
        "retained-capacity-arrays",
        "selected-member-index",
        source=SELECTION_SOURCE,
        unit=MOMENT,
    )
    rows.add(
        "retained-radial-utilisation",
        "retained-radial-demand",
        "retained-radial-resistance",
        source=SELECTION_SOURCE,
    )
    rows.add(
        "capacity-verdict",
        "retained-radial-utilisation",
        source=SELECTION_SOURCE,
    )
    rows.add(
        "selected-plastic-capacity-result",
        "solver-run-evidence",
        "selected-member-evidence",
        "retained-radial-demand",
        "retained-radial-resistance",
        "retained-radial-utilisation",
        "capacity-verdict",
        role=ROLE_FINAL,
        source=SELECTION_SOURCE,
    )


def expected_step_contract(shape: TraceShape) -> tuple[StepSpec, ...]:
    """Declare the exact branch shape without reading a candidate trace."""

    rows = _Rows()
    _inputs(rows, actions=shape.branch == BRANCH_FINITE_SELECTED)
    if shape.branch == BRANCH_FINITE_SELECTED:
        _finite_contract(shape, rows)
    else:
        _failure_contract(shape, rows)
    return tuple(rows.items)


def _source_contract(source: TraceSource) -> TraceSourceContract:
    return TraceSourceContract(source.kind, source.method_id, source.edition)


def expected_registry(shape: TraceShape) -> TraceRegistryContract:
    """Return the independent exact single-family registry declaration."""

    rows = expected_step_contract(shape)
    member = TraceMemberContract(
        member_id=MEMBER_ID,
        calculation_id=shape.calculation_id,
        coverage_id=COVERAGE_ID,
        method_id=shape.blocks.plastic_method_id,
        axes=shape.axes,
        sources=frozenset(_source_contract(row.source) for row in rows),
        result_states=frozenset(
            {
                RESULT_FINITE
                if shape.branch == BRANCH_FINITE_SELECTED
                else RESULT_FAILED
            }
        ),
        step_ids=tuple(row.step_id for row in rows),
        step_dependencies=tuple(
            (row.step_id, row.dependencies) for row in rows
        ),
        step_metadata=tuple(
            TraceStepMetadataContract(
                row.step_id,
                row.quantity_role,
                row.source,
            )
            for row in rows
        ),
    )
    return TraceRegistryContract(
        REGISTRY_ID,
        (TraceFamilyContract(FAMILY_ID, (member,)),),
    )
