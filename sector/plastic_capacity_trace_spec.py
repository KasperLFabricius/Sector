"""Frozen CT-002 identity and dependency contract.

This module declares the expected registry without accepting a candidate
calculation. The production builder creates its calculation separately and the
registry audit compares that candidate with this declaration.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .calculation_trace import (
    RESULT_FAILED,
    RESULT_FINITE,
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
)


COVERAGE_ID = "ct-002"
FAMILY_ID = "ct-002-selected-plastic-capacity"
MEMBER_ID = "selected-plastic-capacity"
REGISTRY_ID = "sector-ct-002-selected-plastic-capacity-v2"

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
    "sector-retained-envelope-selection",
)

ACTION_KEYS = ("P_pl", "Mx_pl", "My_pl")

# Every scalar retained from ``app._run_single_analysis``. Unit names are resolved
# by the builder; the registry uses this tuple only to declare exact IDs/order.
POINT_FIELDS = (
    "V",
    "Mx",
    "My",
    "na_x",
    "na_y",
    "eps_c",
    "eps_s",
    "eps_s_comp",
    "eps_cable",
    "kappa",
    "axial",
    "axial_action",
    "compression_depth",
    "neutral_axis_depth",
    "axial_residual",
    "axial_tolerance",
    "concrete_force",
    "concrete_mx",
    "concrete_my",
    "steel_force",
    "steel_mx",
    "steel_my",
    "tendon_force",
    "tendon_mx",
    "tendon_my",
    "comp_force",
    "comp_mx",
    "comp_my",
    "tension_force",
    "tension_mx",
    "tension_my",
    "lever",
    "dx",
    "dy",
    "converged",
)


@dataclass(frozen=True, slots=True)
class TraceShape:
    """Dynamic cardinalities applied to the frozen CT-002 declaration."""

    blocks: SectionTraceBlocks
    context_token: str
    context_axes: tuple[TraceAxis, ...]
    cardinality: int
    branch: str
    selected_index: int | None

    @property
    def calculation_id(self) -> str:
        return f"plastic.{self.context_token}.selected-capacity"

    @property
    def axes(self) -> tuple[TraceAxis, ...]:
        selected = (
            "none" if self.selected_index is None else str(self.selected_index)
        )
        extras = {
            "result_branch": self.branch,
            "retained_cardinality": str(self.cardinality),
            "selected_member": selected,
        }
        # ``context_axes`` has already encoded and sorted the context. Keep the
        # frozen extra-axis order used by that shared helper.
        extra_axes = tuple(
            TraceAxis(name, value) for name, value in sorted(extras.items())
        )
        return (*self.context_axes, *extra_axes)


def trace_shape(
    blocks: SectionTraceBlocks,
    context: Mapping[str, object],
    *,
    cardinality: int,
    branch: str,
    selected_index: int | None,
) -> TraceShape:
    if type(cardinality) is not int or cardinality <= 0:
        raise ValueError("CT-002 cardinality must be a positive integer")
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
        cardinality=cardinality,
        branch=branch,
        selected_index=selected_index,
    )


def token(value: str) -> str:
    return value.lower().replace("_", "-")


def action_step_id(key: str) -> str:
    return f"input-action-{token(key)}"


def ring_leaf_id(ring: int, point: int, coordinate: str) -> str:
    return f"geometry-ring-{ring:03d}-point-{point:03d}-{coordinate}"


def element_leaf_id(kind: str, index: int, field: str) -> str:
    return f"geometry-{kind}-{index:03d}-{field}"


def material_items(
    blocks: SectionTraceBlocks,
) -> tuple[tuple[str, MaterialBlock], ...]:
    return (
        ("concrete", blocks.concrete),
        *(
            (f"bar-{index:03d}", block)
            for index, block in enumerate(blocks.bars)
        ),
        *(
            (f"tendon-{index:03d}", block)
            for index, block in enumerate(blocks.tendons)
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


def _geometry_contract(shape: TraceShape, add) -> dict[str, str | None]:
    concrete_leaves = []
    for ring_index, ring in enumerate(shape.blocks.geometry.rings):
        for point_index, _ in enumerate(ring):
            for coordinate in ("x", "y"):
                leaf = ring_leaf_id(
                    ring_index,
                    point_index,
                    coordinate,
                )
                add(leaf)
                concrete_leaves.append(leaf)
    add("geometry-concrete-block", *concrete_leaves)

    groups: dict[str, str | None] = {"concrete": "geometry-concrete-block"}
    for kind, elements in (
        ("bar", shape.blocks.geometry.bars),
        ("tendon", shape.blocks.geometry.tendons),
    ):
        leaves = []
        for index, _ in enumerate(elements):
            for field in ("x", "y", "area"):
                leaf = element_leaf_id(kind, index, field)
                add(leaf)
                leaves.append(leaf)
        group_id = f"geometry-{kind}s-block" if leaves else None
        if group_id is not None:
            add(group_id, *leaves)
        groups[kind] = group_id
    return groups


def _material_contract(shape: TraceShape, add) -> dict[str, str | None]:
    vectors: dict[str, str | None] = {}
    bar_vectors = []
    tendon_vectors = []
    for prefix, block in material_items(shape.blocks):
        leaves = []
        for field, _ in block.values:
            leaf = material_leaf_id(prefix, field)
            add(leaf)
            leaves.append(leaf)
        vector = material_vector_id(prefix)
        add(vector, *leaves)
        if prefix == "concrete":
            vectors["concrete"] = vector
        elif prefix.startswith("bar-"):
            bar_vectors.append(vector)
        else:
            tendon_vectors.append(vector)

    for kind, items in (("bar", bar_vectors), ("tendon", tendon_vectors)):
        group_id = f"material-{kind}s-block" if items else None
        if group_id is not None:
            add(group_id, *items)
        vectors[kind] = group_id
    return vectors


def _field_dependencies(
    field: str,
    geometry: Mapping[str, str | None],
    materials: Mapping[str, str | None],
) -> tuple[str, ...]:
    if field.startswith("concrete_"):
        dependencies = (
            action_step_id("P_pl"),
            geometry["concrete"],
            materials["concrete"],
        )
    elif field.startswith("steel_") and geometry["bar"] is not None:
        dependencies = (
            action_step_id("P_pl"),
            geometry["bar"],
            materials["bar"],
        )
    elif field.startswith("tendon_") and geometry["tendon"] is not None:
        dependencies = (
            action_step_id("P_pl"),
            geometry["tendon"],
            materials["tendon"],
        )
    else:
        dependencies = ("section-input-closure",)
    return tuple(item for item in dependencies if item is not None)


def expected_step_contract(
    shape: TraceShape,
) -> tuple[tuple[str, ...], tuple[tuple[str, tuple[str, ...]], ...]]:
    """Declare exact step order/dependencies without reading a calculation."""

    rows: list[tuple[str, tuple[str, ...]]] = []

    def add(step_id: str, *dependencies: str) -> None:
        rows.append((step_id, tuple(dependencies)))

    action_ids = tuple(action_step_id(key) for key in ACTION_KEYS)
    for step_id in action_ids:
        add(step_id)

    geometry = _geometry_contract(shape, add)
    materials = _material_contract(shape, add)
    # The section solver consumes only the requested axial action. Applied Mx/My
    # belong to the later retained radial selection and reach each branch final
    # through that separate path.
    closure_dependencies = [action_step_id("P_pl"), geometry["concrete"]]
    closure_dependencies.extend(
        item for item in (geometry["bar"], geometry["tendon"]) if item
    )
    closure_dependencies.append(materials["concrete"])
    closure_dependencies.extend(
        item for item in (materials["bar"], materials["tendon"]) if item
    )
    add("section-input-closure", *closure_dependencies)
    add("requested-solver-axial", action_step_id("P_pl"))

    point_vectors = []
    for index in range(shape.cardinality):
        field_steps = []
        for field in POINT_FIELDS:
            step_id = point_step_id(index, field)
            add(
                step_id,
                *_field_dependencies(field, geometry, materials),
            )
            field_steps.append(step_id)
        vector = point_evidence_id(index)
        add(vector, *field_steps)
        point_vectors.append(vector)

    array_dependencies = tuple(
        point_step_id(index, field)
        for index in range(shape.cardinality)
        for field in ("V", "Mx", "My")
    )
    add("retained-capacity-arrays", *array_dependencies)
    add(
        "retained-envelope-convergence",
        *(point_step_id(index, "converged") for index in range(shape.cardinality)),
    )
    add(
        "solver-run-evidence",
        "requested-solver-axial",
        "retained-capacity-arrays",
        "retained-envelope-convergence",
        *point_vectors,
    )

    if shape.branch == BRANCH_FINITE_SELECTED:
        selected_vector = point_evidence_id(shape.selected_index)
        add(
            "selected-member-index",
            "retained-capacity-arrays",
            action_step_id("Mx_pl"),
            action_step_id("My_pl"),
        )
        add(
            "selected-member-evidence",
            "selected-member-index",
            selected_vector,
        )
        add(
            "retained-radial-demand",
            action_step_id("Mx_pl"),
            action_step_id("My_pl"),
            "retained-capacity-arrays",
        )
        add(
            "retained-radial-resistance",
            "retained-radial-demand",
            "retained-capacity-arrays",
            "selected-member-index",
        )
        add(
            "retained-radial-utilisation",
            "retained-radial-demand",
            "retained-radial-resistance",
        )
        add("capacity-verdict", "retained-radial-utilisation")
        add(
            "selected-plastic-capacity-result",
            "solver-run-evidence",
            "selected-member-evidence",
            "retained-radial-demand",
            "retained-radial-resistance",
            "retained-radial-utilisation",
            "capacity-verdict",
        )
    elif shape.branch == BRANCH_FAILED_SELECTED:
        add(
            "selected-member-index",
            "retained-capacity-arrays",
            action_step_id("Mx_pl"),
            action_step_id("My_pl"),
        )
        add(
            "failed-selection-evidence",
            "solver-run-evidence",
            "selected-member-index",
            point_evidence_id(shape.selected_index),
        )
        add(
            "selected-plastic-capacity-result",
            "failed-selection-evidence",
        )
    else:
        add(
            "failed-selection-evidence",
            "solver-run-evidence",
            action_step_id("Mx_pl"),
            action_step_id("My_pl"),
        )
        add(
            "selected-plastic-capacity-result",
            "failed-selection-evidence",
        )

    return tuple(step_id for step_id, _ in rows), tuple(rows)


def _source_contract(source: TraceSource) -> TraceSourceContract:
    return TraceSourceContract(source.kind, source.method_id, source.edition)


def expected_registry(shape: TraceShape) -> TraceRegistryContract:
    """Return the exact single-member registry from the frozen specification."""

    step_ids, dependencies = expected_step_contract(shape)
    material_sources = tuple(
        block.provenance.source for _, block in material_items(shape.blocks)
    )
    sources = frozenset(
        _source_contract(source)
        for source in (
            INPUT_SOURCE,
            SOLVER_SOURCE,
            SELECTION_SOURCE,
            *material_sources,
        )
    )
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
        sources=sources,
        result_states=frozenset({result_state}),
        step_ids=step_ids,
        step_dependencies=dependencies,
    )
    return TraceRegistryContract(
        registry_id=REGISTRY_ID,
        families=(TraceFamilyContract(FAMILY_ID, (member,)),),
    )
