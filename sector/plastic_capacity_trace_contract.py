"""Independent exact contract for unpublished CT-002 selected capacity traces.

The candidate calculation is never accepted as input here. Dynamic cardinality,
context, branch, and material provenance come from immutable solver input blocks;
the expected identity, step order, dependency graph, roles, and full sources are
declared below.
"""

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
REGISTRY_ID = "sector-ct-002-selected-plastic-capacity-v3"

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
    "V",
    "compression_depth",
    "kappa",
    "neutral_axis_depth",
    "na_x",
    "na_y",
    "eps_c",
    "eps_s",
    "eps_s_comp",
    "eps_cable",
    "requested_axial",
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
    "comp_mx",
    "comp_my",
    "tension_force",
    "tension_mx",
    "tension_my",
    "achieved_axial",
    "axial_residual",
    "axial_tolerance",
    "converged",
    "Mx",
    "My",
    "dx",
    "dy",
    "lever",
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
            *(TraceAxis(name, value) for name, value in sorted(extras.items())),
        )


@dataclass(frozen=True, slots=True)
class StepContract:
    step_id: str
    dependencies: tuple[str, ...]
    quantity_role: str
    source: TraceSource


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
    cardinality = len(expected_angles)
    if branch not in BRANCHES:
        raise ValueError(f"unknown CT-002 branch {branch!r}")
    if branch == BRANCH_FAILED_UNSELECTED:
        if selected_index is not None:
            raise ValueError("failed-unselected cannot declare a member")
    elif (
        type(selected_index) is not int
        or selected_index < 0
        or selected_index >= cardinality
    ):
        raise ValueError("selected CT-002 branch needs an in-range member")
    return TraceShape(
        blocks=blocks,
        context_token=context_id(context),
        context_axes=context_axes(context),
        expected_angles=expected_angles,
        branch=branch,
        selected_index=selected_index,
    )


def token(value: str) -> str:
    return value.lower().replace("_", "-")


def action_step_id(key: str) -> str:
    return f"input-action-{token(key)}"


def sweep_step_id(key: str) -> str:
    return f"input-sweep-{token(key)}"


def ring_leaf_id(ring: int, point: int, coordinate: str) -> str:
    return f"geometry-ring-{ring:03d}-point-{point:03d}-{coordinate}"


def element_leaf_id(kind: str, index: int, field: str) -> str:
    return f"geometry-{kind}-{index:03d}-{field}"


def material_items(
    blocks: SectionTraceBlocks,
) -> tuple[tuple[str, MaterialBlock], ...]:
    return (
        ("concrete", blocks.concrete),
        *((f"bar-{index:03d}", item) for index, item in enumerate(blocks.bars)),
        *(
            (f"tendon-{index:03d}", item)
            for index, item in enumerate(blocks.tendons)
        ),
    )


def material_leaf_id(prefix: str, field: str) -> str:
    return f"material-{prefix}-{token(field)}"


def material_vector_id(prefix: str) -> str:
    return f"material-{prefix}-block"


def point_step_id(index: int, field: str) -> str:
    return f"member-{index:03d}-{token(field)}"


def point_evidence_id(index: int) -> str:
    return f"member-{index:03d}-solver-evidence"


class _Rows:
    def __init__(self) -> None:
        self.items: list[StepContract] = []
        self.ids: set[str] = set()

    def add(
        self,
        step_id: str,
        *dependencies: str,
        role: str = ROLE_COMPUTED,
        source: TraceSource = SOLVER_SOURCE,
    ) -> str:
        if step_id in self.ids:
            raise ValueError(f"duplicate CT-002 contract step {step_id}")
        self.ids.add(step_id)
        self.items.append(StepContract(step_id, tuple(dependencies), role, source))
        return step_id


def _geometry_contract(
    shape: TraceShape,
    rows: _Rows,
) -> dict[str, str | None]:
    concrete_leaves = []
    for ring_index, ring in enumerate(shape.blocks.geometry.rings):
        for point_index, _ in enumerate(ring):
            for coordinate in ("x", "y"):
                concrete_leaves.append(
                    rows.add(
                        ring_leaf_id(ring_index, point_index, coordinate),
                        role=ROLE_USER_INPUT,
                        source=INPUT_SOURCE,
                    )
                )
    concrete = rows.add("geometry-concrete-block", *concrete_leaves)

    groups: dict[str, str | None] = {"concrete": concrete}
    for kind, elements in (
        ("bar", shape.blocks.geometry.bars),
        ("tendon", shape.blocks.geometry.tendons),
    ):
        leaves = []
        for index, _ in enumerate(elements):
            for field in ("x", "y", "area"):
                leaves.append(
                    rows.add(
                        element_leaf_id(kind, index, field),
                        role=ROLE_USER_INPUT,
                        source=INPUT_SOURCE,
                    )
                )
        groups[kind] = (
            rows.add(f"geometry-{kind}s-block", *leaves) if leaves else None
        )
    return groups


def _material_contract(
    shape: TraceShape,
    rows: _Rows,
) -> dict[str, str | None]:
    groups: dict[str, str | None] = {}
    bars = []
    tendons = []
    for prefix, block in material_items(shape.blocks):
        leaves = [
            rows.add(
                material_leaf_id(prefix, field),
                role=ROLE_METHOD_VALUE,
                source=block.provenance.source,
            )
            for field, _ in block.values
        ]
        vector = rows.add(material_vector_id(prefix), *leaves)
        if prefix == "concrete":
            groups["concrete"] = vector
        elif prefix.startswith("bar-"):
            bars.append(vector)
        else:
            tendons.append(vector)
    groups["bar"] = rows.add("material-bars-block", *bars) if bars else None
    groups["tendon"] = (
        rows.add("material-tendons-block", *tendons) if tendons else None
    )
    return groups


def point_dependencies(
    shape: TraceShape,
    index: int,
    field: str,
    geometry: Mapping[str, str | None],
    materials: Mapping[str, str | None],
) -> tuple[str, ...]:
    point = lambda name: point_step_id(index, name)
    plane = (point("V"), point("kappa"), point("neutral_axis_depth"))
    if field == "V":
        dependencies = ("normalised-sweep-plan",)
    elif field == "compression_depth":
        dependencies = ("section-input-closure", point("V"))
    elif field == "kappa":
        dependencies = (
            "section-input-closure",
            point("V"),
            point("compression_depth"),
        )
    elif field == "neutral_axis_depth":
        dependencies = (
            geometry["concrete"],
            point("V"),
            point("compression_depth"),
        )
    elif field in {"na_x", "na_y"}:
        dependencies = (point("V"), point("neutral_axis_depth"))
    elif field == "eps_c":
        dependencies = (point("kappa"), point("compression_depth"))
    elif field in {"eps_s", "eps_s_comp"}:
        dependencies = (*plane, geometry["bar"])
    elif field == "eps_cable":
        dependencies = (*plane, geometry["tendon"], materials["tendon"])
    elif field == "requested_axial":
        dependencies = ("requested-solver-axial",)
    elif field.startswith("concrete_"):
        dependencies = (
            *plane,
            geometry["concrete"],
            materials["concrete"],
            "solver-integration-bands",
        )
    elif field.startswith("bar_"):
        dependencies = (*plane, geometry["bar"], materials["bar"])
    elif field.startswith("tendon_"):
        dependencies = (*plane, geometry["tendon"], materials["tendon"])
    elif field.startswith("comp_") or field.startswith("tension_"):
        dependencies = ("section-input-closure", *plane)
    elif field == "achieved_axial":
        dependencies = tuple(
            point(f"{kind}_force") for kind in ("concrete", "bar", "tendon")
        )
    elif field == "axial_residual":
        dependencies = (point("achieved_axial"), point("requested_axial"))
    elif field == "axial_tolerance":
        dependencies = (
            point("requested_axial"),
            "solver-axial-tolerance-factor",
        )
    elif field == "converged":
        dependencies = (point("axial_residual"), point("axial_tolerance"))
    elif field in {"Mx", "My"}:
        suffix = field.lower()
        dependencies = tuple(
            point(f"{kind}_{suffix}") for kind in ("concrete", "bar", "tendon")
        )
    elif field == "dx":
        dependencies = (
            point("comp_force"),
            point("comp_my"),
            point("tension_force"),
            point("tension_my"),
        )
    elif field == "dy":
        dependencies = (
            point("comp_force"),
            point("comp_mx"),
            point("tension_force"),
            point("tension_mx"),
        )
    elif field == "lever":
        dependencies = (point("dx"), point("dy"))
    else:
        raise ValueError(f"unknown CT-002 point field {field}")
    return tuple(item for item in dependencies if item is not None)


def expected_step_contract(shape: TraceShape) -> tuple[StepContract, ...]:
    """Declare every expected step without inspecting a candidate calculation."""

    rows = _Rows()
    for key in ACTION_KEYS:
        rows.add(
            action_step_id(key),
            role=ROLE_USER_INPUT,
            source=INPUT_SOURCE,
        )
    for key in SWEEP_KEYS:
        rows.add(
            sweep_step_id(key),
            role=ROLE_USER_INPUT,
            source=INPUT_SOURCE,
        )
    rows.add(
        "normalised-sweep-plan",
        *(sweep_step_id(key) for key in SWEEP_KEYS),
    )
    geometry = _geometry_contract(shape, rows)
    materials = _material_contract(shape, rows)
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

    closure = [action_step_id("P_pl"), geometry["concrete"]]
    closure.extend(item for item in (geometry["bar"], geometry["tendon"]) if item)
    closure.append(materials["concrete"])
    closure.extend(item for item in (materials["bar"], materials["tendon"]) if item)
    closure.extend(("solver-integration-bands", "solver-axial-tolerance-factor"))
    rows.add("section-input-closure", *closure)
    rows.add("requested-solver-axial", action_step_id("P_pl"))

    point_vectors = []
    for index in range(shape.cardinality):
        fields = []
        for field in POINT_FIELDS:
            fields.append(
                rows.add(
                    point_step_id(index, field),
                    *point_dependencies(
                        shape, index, field, geometry, materials
                    ),
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
        *(
            point_step_id(index, "converged")
            for index in range(shape.cardinality)
        ),
    )
    rows.add(
        "solver-run-evidence",
        "requested-solver-axial",
        "retained-capacity-arrays",
        "retained-envelope-convergence",
        *point_vectors,
    )

    if shape.branch == BRANCH_FINITE_SELECTED:
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
            "retained-capacity-arrays",
            source=SELECTION_SOURCE,
        )
        rows.add(
            "retained-radial-resistance",
            "retained-radial-demand",
            "retained-capacity-arrays",
            "selected-member-index",
            source=SELECTION_SOURCE,
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
    else:
        failure_dependencies = ["solver-run-evidence"]
        if shape.branch == BRANCH_FAILED_SELECTED:
            rows.add(
                "selected-member-index",
                "retained-capacity-arrays",
                action_step_id("Mx_pl"),
                action_step_id("My_pl"),
                source=SELECTION_SOURCE,
            )
            failure_dependencies.extend(
                (
                    "selected-member-index",
                    point_evidence_id(shape.selected_index),
                )
            )
        else:
            failure_dependencies.extend(
                (action_step_id("Mx_pl"), action_step_id("My_pl"))
            )
        rows.add(
            "failed-selection-evidence",
            *failure_dependencies,
            source=SELECTION_SOURCE,
        )
        rows.add(
            "selected-plastic-capacity-result",
            "failed-selection-evidence",
            role=ROLE_FINAL,
            source=SOLVER_SOURCE,
        )
    return tuple(rows.items)


def _source_contract(source: TraceSource) -> TraceSourceContract:
    return TraceSourceContract(source.kind, source.method_id, source.edition)


def expected_registry(shape: TraceShape) -> TraceRegistryContract:
    """Return the independently declared exact single-member registry."""

    rows = expected_step_contract(shape)
    result_state = (
        RESULT_FINITE
        if shape.branch == BRANCH_FINITE_SELECTED
        else RESULT_FAILED
    )
    member = TraceMemberContract(
        member_id=MEMBER_ID,
        calculation_id=shape.calculation_id,
        coverage_id=COVERAGE_ID,
        method_id=shape.blocks.plastic_method_id,
        axes=shape.axes,
        sources=frozenset(_source_contract(row.source) for row in rows),
        result_states=frozenset({result_state}),
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
        registry_id=REGISTRY_ID,
        families=(TraceFamilyContract(FAMILY_ID, (member,)),),
    )
