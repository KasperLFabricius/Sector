"""Unpublished CT-002 trace for the retained plastic-capacity run."""

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
    ROLE_COMPUTED,
    ROLE_FINAL,
    ROLE_METHOD_VALUE,
    ROLE_USER_INPUT,
    TraceCalculation,
    TraceDependency,
    TraceResult,
    TraceSource,
    TraceStep,
    TraceUnit,
    TraceValidationError,
    create_bundle,
)
from .plastic_capacity_trace_spec import (
    ACTION_KEYS,
    BRANCH_FAILED_SELECTED,
    BRANCH_FAILED_UNSELECTED,
    BRANCH_FINITE_SELECTED,
    COVERAGE_ID,
    INPUT_SOURCE,
    POINT_FIELDS,
    SELECTION_SOURCE,
    SOLVER_SOURCE,
    TraceShape,
    action_step_id,
    element_leaf_id,
    expected_registry,
    material_items,
    material_leaf_id,
    material_vector_id,
    point_evidence_id,
    point_step_id,
    ring_leaf_id,
    token,
    trace_shape,
)
from .section_trace_blocks import MaterialBlock, SectionTraceBlocks, section_trace_blocks
from .trace_registry import TraceRegistryContract, audit_trace_registry


_ONE = TraceUnit("1", "scalar")
_AREA = TraceUnit("m2", "area")
_LENGTH = TraceUnit("m", "length")
_FORCE = TraceUnit("kN", "force")
_MOMENT = TraceUnit("kNm", "moment")
_STRESS = TraceUnit("MPa", "stress")
_ANGLE = TraceUnit("degrees", "angle")
_CURVATURE = TraceUnit("1/m", "curvature")
_STRAIN = TraceUnit("%", "strain")

_PROBE_SHA256 = "0" * 64
_MATERIAL_STRESS_FIELDS = frozenset({"fck", "fytk", "fyck", "futk", "Es"})
_POINT_FORCE_FIELDS = frozenset(
    {
        "axial",
        "axial_action",
        "axial_residual",
        "axial_tolerance",
        "concrete_force",
        "steel_force",
        "tendon_force",
        "comp_force",
        "tension_force",
    }
)
_POINT_MOMENT_FIELDS = frozenset(
    field
    for kind in ("concrete", "steel", "tendon", "comp", "tension")
    for field in (f"{kind}_mx", f"{kind}_my")
) | frozenset({"Mx", "My"})
_POINT_LENGTH_FIELDS = frozenset(
    {
        "na_x",
        "na_y",
        "compression_depth",
        "neutral_axis_depth",
        "lever",
        "dx",
        "dy",
    }
)
_POINT_STRAIN_FIELDS = frozenset({"eps_c", "eps_s", "eps_s_comp", "eps_cable"})


@dataclass(frozen=True, slots=True)
class PlasticCapacityTraceFamily:
    """One validated CT-002 calculation and its exact registry."""

    calculation: TraceCalculation
    registry: TraceRegistryContract


@dataclass(frozen=True, slots=True)
class _Evidence:
    blocks: SectionTraceBlocks
    points: tuple[Mapping[str, Any], ...]
    mx: tuple[float, ...]
    my: tuple[float, ...]
    selected_index: int | None
    demand: float
    resistance: float | None
    utilisation: float
    envelope_converged: bool
    branch: str


class _Steps:
    def __init__(self) -> None:
        self.items: list[TraceStep] = []
        self.by_id: dict[str, TraceStep] = {}

    def add(
        self,
        step_id: str,
        title: str,
        symbol: str,
        unit: TraceUnit,
        result: TraceResult,
        *,
        role: str,
        source: TraceSource,
        dependencies: tuple[str, ...] = (),
        expression: str,
        substituted: str | None = None,
        warnings: tuple[str, ...] = (),
        assumptions: tuple[str, ...] = (),
    ) -> str:
        if step_id in self.by_id:
            raise TraceValidationError(f"duplicate CT-002 step {step_id}")
        dependency_values = []
        for dependency_id in dependencies:
            dependency = self.by_id.get(dependency_id)
            if dependency is None:
                raise TraceValidationError(
                    f"CT-002 step {step_id} has missing dependency {dependency_id}"
                )
            dependency_values.append(
                TraceDependency(dependency_id, dependency.unit)
            )
        step = TraceStep(
            step_id=step_id,
            title=title,
            dependencies=tuple(dependency_values),
            quantity_role=role,
            source=source,
            symbol=symbol,
            unit=unit,
            actual_expression=expression,
            substituted_expression=(
                substituted if substituted is not None else expression
            ),
            result=result,
            warnings=warnings,
            assumptions=assumptions,
        )
        self.items.append(step)
        self.by_id[step_id] = step
        return step_id


def _finite_result(value: float) -> TraceResult:
    return TraceResult(RESULT_FINITE, float(value))


def _failed_result(reason: str) -> TraceResult:
    return TraceResult(RESULT_FAILED, None, reason)


def _extended_result(value: Any, label: str) -> TraceResult:
    if type(value) not in {int, float} or type(value) is bool:
        raise TraceValidationError(f"{label} must be a non-Boolean number")
    number = float(value)
    if math.isnan(number):
        raise TraceValidationError(f"{label} cannot be NaN")
    if number == math.inf:
        return TraceResult(
            RESULT_POSITIVE_INFINITY,
            None,
            f"{label} is parallel to a coordinate axis",
        )
    if number == -math.inf:
        return TraceResult(
            RESULT_NEGATIVE_INFINITY,
            None,
            f"{label} is parallel to a coordinate axis",
        )
    return _finite_result(number)


def _finite(value: Any, label: str) -> float:
    if type(value) not in {int, float} or type(value) is bool:
        raise TraceValidationError(f"{label} must be a non-Boolean number")
    number = float(value)
    if not math.isfinite(number):
        raise TraceValidationError(f"{label} must be finite")
    return number


def _extended_number(value: Any, label: str) -> float:
    result = _extended_result(value, label)
    if result.state == RESULT_FINITE:
        return float(result.value)
    return math.inf if result.state == RESULT_POSITIVE_INFINITY else -math.inf


def _sequence(value: Any, label: str) -> tuple[Any, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TraceValidationError(f"{label} must be a retained sequence")
    return tuple(value)


def _close(actual: float, expected: float) -> bool:
    if math.isinf(actual) or math.isinf(expected):
        return actual == expected
    return math.isclose(actual, expected, rel_tol=1.0e-12, abs_tol=1.0e-9)


def _require_close(actual: float, expected: float, label: str) -> None:
    if not _close(actual, expected):
        raise TraceValidationError(
            f"{label} is inconsistent: retained {actual!r}, expected {expected!r}"
        )


def _validate_point(
    point: Any,
    *,
    index: int,
    mx: float,
    my: float,
    requested_solver_axial: float,
    blocks: SectionTraceBlocks,
) -> Mapping[str, Any]:
    label = f"plastic point {index}"
    if not isinstance(point, Mapping):
        raise TraceValidationError(f"{label} must be a mapping")
    actual_fields = set(point)
    expected_fields = set(POINT_FIELDS)
    if actual_fields != expected_fields:
        missing = sorted(expected_fields - actual_fields)
        extra = sorted(str(item) for item in actual_fields - expected_fields)
        details = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if extra:
            details.append(f"unexpected {', '.join(extra)}")
        raise TraceValidationError(f"{label} fields: {'; '.join(details)}")

    finite_fields = expected_fields - {"na_x", "na_y", "converged"}
    values = {
        field: _finite(point[field], f"{label} {field}")
        for field in finite_fields
    }
    na_x = _extended_number(point["na_x"], f"{label} na_x")
    na_y = _extended_number(point["na_y"], f"{label} na_y")
    if type(point["converged"]) is not bool:
        raise TraceValidationError(f"{label} converged must be Boolean")

    checks = (
        (values["Mx"], mx, "Mx array member"),
        (values["My"], my, "My array member"),
        (
            sum(values[f"{kind}_force"] for kind in ("concrete", "steel", "tendon")),
            values["axial"],
            "axial material resultants",
        ),
        (
            sum(values[f"{kind}_mx"] for kind in ("concrete", "steel", "tendon")),
            values["Mx"],
            "x-moment material resultants",
        ),
        (
            sum(values[f"{kind}_my"] for kind in ("concrete", "steel", "tendon")),
            values["My"],
            "y-moment material resultants",
        ),
        (
            values["comp_force"] + values["tension_force"],
            values["axial"],
            "compression and tension forces",
        ),
        (
            values["comp_mx"] + values["tension_mx"],
            values["Mx"],
            "compression and tension x moments",
        ),
        (
            values["comp_my"] + values["tension_my"],
            values["My"],
            "compression and tension y moments",
        ),
        (values["axial_action"], -values["axial"], "axial action convention"),
    )
    for actual, expected, suffix in checks:
        _require_close(actual, expected, f"{label} {suffix}")

    expected_residual = values["axial"] - requested_solver_axial
    expected_tolerance = 1.0e-6 * max(1.0, abs(requested_solver_axial))
    _require_close(
        values["axial_residual"],
        expected_residual,
        f"{label} axial residual",
    )
    _require_close(
        values["axial_tolerance"],
        expected_tolerance,
        f"{label} axial tolerance",
    )
    expected_converged = abs(expected_residual) <= expected_tolerance
    if point["converged"] is not expected_converged:
        raise TraceValidationError(
            f"{label} convergence contradicts its residual and tolerance"
        )

    if values["comp_force"] != 0.0 and values["tension_force"] != 0.0:
        expected_dx = (
            values["comp_my"] / values["comp_force"]
            - values["tension_my"] / values["tension_force"]
        )
        expected_dy = (
            values["comp_mx"] / values["comp_force"]
            - values["tension_mx"] / values["tension_force"]
        )
    else:
        expected_dx = expected_dy = 0.0
    _require_close(values["dx"], expected_dx, f"{label} lever dx")
    _require_close(values["dy"], expected_dy, f"{label} lever dy")
    _require_close(
        values["lever"],
        math.hypot(expected_dx, expected_dy),
        f"{label} lever-arm components",
    )
    if (
        values["compression_depth"] <= 0.0
        or values["kappa"] <= 0.0
        or values["axial_tolerance"] <= 0.0
    ):
        raise TraceValidationError(
            f"{label} needs positive depth, curvature, and tolerance"
        )

    angle = math.radians(values["V"])
    direction_x, direction_y = math.cos(angle), math.sin(angle)
    concrete_projections = tuple(
        x * direction_x + y * direction_y
        for ring in blocks.geometry.rings
        for x, y in ring
    )
    expected_neutral_axis = (
        max(concrete_projections) - values["compression_depth"]
    )
    _require_close(
        values["neutral_axis_depth"],
        expected_neutral_axis,
        f"{label} neutral-axis depth",
    )
    _require_close(
        values["eps_c"],
        -values["kappa"] * values["compression_depth"] * 100.0,
        f"{label} concrete strain plane",
    )

    bar_strains = tuple(
        values["kappa"]
        * (bar.x * direction_x + bar.y * direction_y - expected_neutral_axis)
        for bar in blocks.geometry.bars
    )
    expected_tensile_steel = -min(bar_strains) * 100.0 if bar_strains else 0.0
    expected_compressive_steel = -max(bar_strains) * 100.0 if bar_strains else 0.0
    _require_close(
        values["eps_s"],
        expected_tensile_steel,
        f"{label} tensile steel strain plane",
    )
    _require_close(
        values["eps_s_comp"],
        expected_compressive_steel,
        f"{label} compressive steel strain plane",
    )

    tendon_strains = tuple(
        dict(law.values)["IS"]
        - values["kappa"]
        * (
            tendon.x * direction_x
            + tendon.y * direction_y
            - expected_neutral_axis
        )
        for tendon, law in zip(blocks.geometry.tendons, blocks.tendons)
    )
    expected_tendon_strain = max(tendon_strains) * 100.0 if tendon_strains else 0.0
    _require_close(
        values["eps_cable"],
        expected_tendon_strain,
        f"{label} tendon strain plane",
    )

    for field, retained, direction in (
        ("na_x", na_x, direction_x),
        ("na_y", na_y, direction_y),
    ):
        if abs(direction) <= 1.0e-12:
            if retained != math.inf:
                raise TraceValidationError(
                    f"{label} {field} must be explicit positive infinity"
                )
        else:
            _require_close(
                retained,
                expected_neutral_axis / direction,
                f"{label} {field}",
            )
    return point


def _validate_radial_value(
    retained: Any,
    authoritative: float | None,
    label: str,
) -> float | None:
    if authoritative is None:
        if retained is not None:
            raise TraceValidationError(f"{label} must be absent")
        return None
    number = _extended_number(retained, label)
    _require_close(number, float(authoritative), label)
    return number


def _evidence(inp: Mapping[str, Any], out: Mapping[str, Any]) -> _Evidence:
    if not isinstance(inp, Mapping) or not isinstance(out, Mapping):
        raise TraceValidationError("CT-002 input and result must be mappings")
    try:
        blocks = section_trace_blocks(inp)
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
    mx_raw = _sequence(result.get("mx"), "plastic mx")
    my_raw = _sequence(result.get("my"), "plastic my")
    if not points or len(points) != len(mx_raw) or len(points) != len(my_raw):
        raise TraceValidationError(
            "plastic points, mx, and my need one exact non-empty cardinality"
        )
    mx = tuple(
        _finite(item, f"plastic mx member {index}")
        for index, item in enumerate(mx_raw)
    )
    my = tuple(
        _finite(item, f"plastic my member {index}")
        for index, item in enumerate(my_raw)
    )

    if "util_gov" not in result:
        raise TraceValidationError("util_gov is required even when no member exists")
    raw_selected = result["util_gov"]
    if type(raw_selected) is int:
        if raw_selected < 0 or raw_selected >= len(points):
            raise TraceValidationError("util_gov is outside the retained cardinality")
        selected: int | None = raw_selected
    elif raw_selected is None:
        selected = None
    else:
        raise TraceValidationError(
            "util_gov must be None or a non-Boolean integer"
        )
    if result.get("closed") is not True or result.get("check_util") is not True:
        raise TraceValidationError(
            "CT-002 evidence needs a closed checked plastic envelope"
        )

    actions = dict(blocks.plastic_actions.values)
    applied = _sequence(result.get("applied"), "plastic applied action")
    if len(applied) != 2:
        raise TraceValidationError("plastic applied action needs Mx and My")
    _require_close(
        _finite(applied[0], "plastic applied Mx"),
        actions["Mx_pl"],
        "plastic applied Mx",
    )
    _require_close(
        _finite(applied[1], "plastic applied My"),
        actions["My_pl"],
        "plastic applied My",
    )

    requested_solver_axial = -actions["P_pl"]
    validated = tuple(
        _validate_point(
            point,
            index=index,
            mx=mx[index],
            my=my[index],
            requested_solver_axial=requested_solver_axial,
            blocks=blocks,
        )
        for index, point in enumerate(points)
    )
    angles = tuple(float(point["V"]) for point in validated)
    if len(set(angles)) != len(angles):
        raise TraceValidationError("plastic points have duplicate member angles")

    envelope_converged = result.get("converged")
    if type(envelope_converged) is not bool:
        raise TraceValidationError("plastic envelope convergence must be Boolean")
    if envelope_converged is not all(point["converged"] for point in validated):
        raise TraceValidationError(
            "plastic envelope convergence masks a retained member state"
        )

    authoritative = combined.radial_util_result(
        mx,
        my,
        actions["Mx_pl"],
        actions["My_pl"],
    )
    if authoritative.governing_index != selected:
        raise TraceValidationError(
            "plastic util_gov contradicts the authoritative envelope selection"
        )
    demand = _finite(result.get("demand"), "plastic retained radial demand")
    _require_close(demand, authoritative.demand, "plastic retained radial demand")
    resistance = _validate_radial_value(
        result.get("resistance"),
        authoritative.resistance,
        "plastic retained radial resistance",
    )
    utilisation = _extended_number(
        result.get("util"),
        "plastic retained radial utilisation",
    )
    _require_close(
        utilisation,
        authoritative.utilisation,
        "plastic retained radial utilisation",
    )

    if envelope_converged:
        if selected is None or resistance is None:
            raise TraceValidationError(
                "a converged CT-002 run needs one authoritative selected member"
            )
        if (
            demand <= 0.0
            or resistance <= 0.0
            or not math.isfinite(utilisation)
            or utilisation <= 0.0
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
    elif selected is None:
        if resistance is not None or authoritative.governing_index is not None:
            raise TraceValidationError(
                "failed-unselected CT-002 has contradictory selection evidence"
            )
        branch = BRANCH_FAILED_UNSELECTED
    else:
        if resistance is None:
            raise TraceValidationError(
                "failed-selected CT-002 needs its authoritative selected member"
            )
        branch = BRANCH_FAILED_SELECTED

    return _Evidence(
        blocks=blocks,
        points=validated,
        mx=mx,
        my=my,
        selected_index=selected,
        demand=demand,
        resistance=resistance,
        utilisation=utilisation,
        envelope_converged=envelope_converged,
        branch=branch,
    )


def _point_unit(field: str) -> TraceUnit:
    if field == "V":
        return _ANGLE
    if field == "kappa":
        return _CURVATURE
    if field in _POINT_FORCE_FIELDS:
        return _FORCE
    if field in _POINT_MOMENT_FIELDS:
        return _MOMENT
    if field in _POINT_LENGTH_FIELDS:
        return _LENGTH
    if field in _POINT_STRAIN_FIELDS:
        return _STRAIN
    return _ONE


def _material_unit(field: str) -> TraceUnit:
    return _STRESS if field in _MATERIAL_STRESS_FIELDS else _ONE


def _add_input_step(
    steps: _Steps,
    step_id: str,
    title: str,
    symbol: str,
    unit: TraceUnit,
    value: float,
) -> str:
    return steps.add(
        step_id,
        title,
        symbol,
        unit,
        _finite_result(value),
        role=ROLE_USER_INPUT,
        source=INPUT_SOURCE,
        expression="retained user input",
        substituted=repr(value),
    )


def _add_vector(
    steps: _Steps,
    step_id: str,
    title: str,
    dependencies: tuple[str, ...],
) -> str:
    return steps.add(
        step_id,
        title,
        "count",
        _ONE,
        _finite_result(len(dependencies)),
        role=ROLE_COMPUTED,
        source=SOLVER_SOURCE,
        dependencies=dependencies,
        expression="ordered retained block",
        substituted=f"{len(dependencies)} retained values",
    )


def _add_geometry(
    steps: _Steps,
    blocks: SectionTraceBlocks,
) -> dict[str, str | None]:
    concrete_leaves = []
    for ring_index, ring in enumerate(blocks.geometry.rings):
        for point_index, (x, y) in enumerate(ring):
            for coordinate, value in (("x", x), ("y", y)):
                step_id = ring_leaf_id(ring_index, point_index, coordinate)
                _add_input_step(
                    steps,
                    step_id,
                    f"Concrete ring {ring_index} point {point_index} {coordinate}",
                    coordinate,
                    _LENGTH,
                    value,
                )
                concrete_leaves.append(step_id)
    concrete_id = _add_vector(
        steps,
        "geometry-concrete-block",
        "Retained concrete geometry block",
        tuple(concrete_leaves),
    )

    groups: dict[str, str | None] = {"concrete": concrete_id}
    for kind, elements in (
        ("bar", blocks.geometry.bars),
        ("tendon", blocks.geometry.tendons),
    ):
        leaves = []
        for index, element in enumerate(elements):
            for field, value, unit in (
                ("x", element.x, _LENGTH),
                ("y", element.y, _LENGTH),
                ("area", element.area, _AREA),
            ):
                step_id = element_leaf_id(kind, index, field)
                _add_input_step(
                    steps,
                    step_id,
                    f"{kind.title()} {index} {field}",
                    field,
                    unit,
                    value,
                )
                leaves.append(step_id)
        group_id = None
        if leaves:
            group_id = _add_vector(
                steps,
                f"geometry-{kind}s-block",
                f"Retained {kind} geometry block",
                tuple(leaves),
            )
        groups[kind] = group_id
    return groups


def _add_material_block(
    steps: _Steps,
    prefix: str,
    block: MaterialBlock,
) -> str:
    leaves = []
    for field, value in block.values:
        step_id = material_leaf_id(prefix, field)
        steps.add(
            step_id,
            f"{block.kind} law value {field}",
            f"{prefix}.{field}",
            _material_unit(field),
            _finite_result(value),
            role=ROLE_METHOD_VALUE,
            source=block.provenance.source,
            expression="retained material-law value",
            substituted=(
                f"element_id={block.element_id}; "
                f"material_id={block.material_id}; value={value!r}"
            ),
        )
        leaves.append(step_id)
    return _add_vector(
        steps,
        material_vector_id(prefix),
        f"Retained {prefix} material block",
        tuple(leaves),
    )


def _add_materials(
    steps: _Steps,
    blocks: SectionTraceBlocks,
) -> dict[str, str | None]:
    vectors: dict[str, str | None] = {}
    bars = []
    tendons = []
    for prefix, block in material_items(blocks):
        vector = _add_material_block(steps, prefix, block)
        if prefix == "concrete":
            vectors["concrete"] = vector
        elif prefix.startswith("bar-"):
            bars.append(vector)
        else:
            tendons.append(vector)
    for kind, items in (("bar", bars), ("tendon", tendons)):
        group_id = None
        if items:
            group_id = _add_vector(
                steps,
                f"material-{kind}s-block",
                f"Retained {kind} material-law blocks",
                tuple(items),
            )
        vectors[kind] = group_id
    return vectors


def _point_dependencies(
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


def _add_point(
    steps: _Steps,
    point: Mapping[str, Any],
    index: int,
    geometry: Mapping[str, str | None],
    materials: Mapping[str, str | None],
) -> str:
    field_steps = []
    for field in POINT_FIELDS:
        raw = point[field]
        if field == "converged":
            result = _finite_result(1.0 if raw else 0.0)
            substituted = str(raw)
        elif field in {"na_x", "na_y"}:
            result = _extended_result(raw, f"member {index} {field}")
            substituted = repr(float(raw))
        else:
            result = _finite_result(float(raw))
            substituted = repr(float(raw))
        step_id = point_step_id(index, field)
        steps.add(
            step_id,
            f"Retained member {index} {field}",
            field,
            _point_unit(field),
            result,
            role=ROLE_COMPUTED,
            source=SOLVER_SOURCE,
            dependencies=_point_dependencies(field, geometry, materials),
            expression="retained plastic solver output",
            substituted=substituted,
        )
        field_steps.append(step_id)
    return _add_vector(
        steps,
        point_evidence_id(index),
        f"Retained member {index} solver evidence",
        tuple(field_steps),
    )


def _calculation(evidence: _Evidence, shape: TraceShape) -> TraceCalculation:
    steps = _Steps()
    actions = dict(evidence.blocks.plastic_actions.values)
    for key in ACTION_KEYS:
        _add_input_step(
            steps,
            action_step_id(key),
            f"Applied plastic action {key}",
            key,
            _FORCE if key == "P_pl" else _MOMENT,
            actions[key],
        )

    geometry = _add_geometry(steps, evidence.blocks)
    materials = _add_materials(steps, evidence.blocks)
    # The section solver consumes only P_pl. Applied Mx/My are dependencies of
    # the retained selection path below, not of the plastic envelope mechanics.
    closure_dependencies = [action_step_id("P_pl"), geometry["concrete"]]
    closure_dependencies.extend(
        item for item in (geometry["bar"], geometry["tendon"]) if item
    )
    closure_dependencies.append(materials["concrete"])
    closure_dependencies.extend(
        item for item in (materials["bar"], materials["tendon"]) if item
    )
    _add_vector(
        steps,
        "section-input-closure",
        "Exact section input closure",
        tuple(closure_dependencies),
    )
    steps.add(
        "requested-solver-axial",
        "Requested solver axial action",
        "N_solver,requested",
        _FORCE,
        _finite_result(-actions["P_pl"]),
        role=ROLE_COMPUTED,
        source=SOLVER_SOURCE,
        dependencies=(action_step_id("P_pl"),),
        expression="N_solver,requested = -P_pl",
        substituted=f"-({actions['P_pl']!r})",
    )

    point_vectors = []
    for index, point in enumerate(evidence.points):
        point_vectors.append(
            _add_point(steps, point, index, geometry, materials)
        )

    array_dependencies = tuple(
        point_step_id(index, field)
        for index in range(len(evidence.points))
        for field in ("V", "Mx", "My")
    )
    _add_vector(
        steps,
        "retained-capacity-arrays",
        "Retained plastic capacity arrays",
        array_dependencies,
    )
    steps.add(
        "retained-envelope-convergence",
        "Retained envelope convergence",
        "converged_envelope",
        _ONE,
        _finite_result(1.0 if evidence.envelope_converged else 0.0),
        role=ROLE_COMPUTED,
        source=SOLVER_SOURCE,
        dependencies=tuple(
            point_step_id(index, "converged")
            for index in range(len(evidence.points))
        ),
        expression="all retained member convergence flags",
        substituted=str(evidence.envelope_converged),
    )
    _add_vector(
        steps,
        "solver-run-evidence",
        "Retained plastic solver run evidence",
        (
            "requested-solver-axial",
            "retained-capacity-arrays",
            "retained-envelope-convergence",
            *point_vectors,
        ),
    )

    if evidence.branch == BRANCH_FINITE_SELECTED:
        selected = evidence.selected_index
        steps.add(
            "selected-member-index",
            "Authoritative retained member index",
            "util_gov",
            _ONE,
            _finite_result(selected),
            role=ROLE_COMPUTED,
            source=SELECTION_SOURCE,
            dependencies=(
                "retained-capacity-arrays",
                action_step_id("Mx_pl"),
                action_step_id("My_pl"),
            ),
            expression="existing authoritative radial selector",
            substituted=str(selected),
        )
        _add_vector(
            steps,
            "selected-member-evidence",
            "Exact selected member evidence",
            ("selected-member-index", point_evidence_id(selected)),
        )
        steps.add(
            "retained-radial-demand",
            "Retained radial moment demand",
            "M_Ed,radial",
            _MOMENT,
            _finite_result(evidence.demand),
            role=ROLE_COMPUTED,
            source=SELECTION_SOURCE,
            dependencies=(
                action_step_id("Mx_pl"),
                action_step_id("My_pl"),
                "retained-capacity-arrays",
            ),
            expression="retained authoritative radial demand",
            substituted=repr(evidence.demand),
        )
        steps.add(
            "retained-radial-resistance",
            "Retained governing radial resistance",
            "M_Rd,radial",
            _MOMENT,
            _finite_result(evidence.resistance),
            role=ROLE_COMPUTED,
            source=SELECTION_SOURCE,
            dependencies=(
                "retained-radial-demand",
                "retained-capacity-arrays",
                "selected-member-index",
            ),
            expression="retained authoritative ray intersection",
            substituted=repr(evidence.resistance),
        )
        steps.add(
            "retained-radial-utilisation",
            "Retained radial utilisation",
            "eta_M",
            _ONE,
            _finite_result(evidence.utilisation),
            role=ROLE_COMPUTED,
            source=SELECTION_SOURCE,
            dependencies=(
                "retained-radial-demand",
                "retained-radial-resistance",
            ),
            expression="eta_M = M_Ed,radial / M_Rd,radial",
            substituted=(
                f"{evidence.demand!r} / {evidence.resistance!r}"
            ),
        )
        passed = evidence.utilisation <= 1.0 + 1.0e-9
        steps.add(
            "capacity-verdict",
            "Demand versus resistance verdict",
            "PASS=1",
            _ONE,
            _finite_result(1.0 if passed else 0.0),
            role=ROLE_COMPUTED,
            source=SELECTION_SOURCE,
            dependencies=("retained-radial-utilisation",),
            expression="PASS when eta_M <= 1.0",
            substituted="PASS" if passed else "FAIL",
        )
        warnings = () if passed else ("Demand exceeds retained radial resistance.",)
        steps.add(
            "selected-plastic-capacity-result",
            "Selected plastic capacity result",
            "eta_M",
            _ONE,
            _finite_result(evidence.utilisation),
            role=ROLE_FINAL,
            source=SELECTION_SOURCE,
            dependencies=(
                "solver-run-evidence",
                "selected-member-evidence",
                "retained-radial-demand",
                "retained-radial-resistance",
                "retained-radial-utilisation",
                "capacity-verdict",
            ),
            expression="selected retained plastic capacity check",
            substituted=repr(evidence.utilisation),
            warnings=warnings,
        )
        calculation_warnings = warnings
    else:
        failure_reason = (
            "plastic solver did not converge for every retained envelope member"
        )
        if evidence.branch == BRANCH_FAILED_SELECTED:
            selected = evidence.selected_index
            steps.add(
                "selected-member-index",
                "Retained member index from the failed solver run",
                "util_gov",
                _ONE,
                _finite_result(selected),
                role=ROLE_COMPUTED,
                source=SELECTION_SOURCE,
                dependencies=(
                    "retained-capacity-arrays",
                    action_step_id("Mx_pl"),
                    action_step_id("My_pl"),
                ),
                expression="existing authoritative radial selector",
                substituted=str(selected),
            )
            failure_dependencies = (
                "solver-run-evidence",
                "selected-member-index",
                point_evidence_id(selected),
            )
        else:
            failure_dependencies = (
                "solver-run-evidence",
                action_step_id("Mx_pl"),
                action_step_id("My_pl"),
            )
        steps.add(
            "failed-selection-evidence",
            "Failed solver and selection evidence",
            "failure_evidence",
            _ONE,
            _finite_result(
                sum(not point["converged"] for point in evidence.points)
            ),
            role=ROLE_COMPUTED,
            source=SELECTION_SOURCE,
            dependencies=failure_dependencies,
            expression="retained non-convergence and authoritative selection state",
            substituted=evidence.branch,
            warnings=(failure_reason,),
        )
        steps.add(
            "selected-plastic-capacity-result",
            "Failed plastic capacity result",
            "CT-002",
            _ONE,
            _failed_result(failure_reason),
            role=ROLE_FINAL,
            source=SOLVER_SOURCE,
            dependencies=("failed-selection-evidence",),
            expression="no engineering result from a non-converged solver run",
            substituted="failed",
            warnings=(failure_reason,),
        )
        calculation_warnings = (failure_reason,)

    return TraceCalculation(
        calculation_id=shape.calculation_id,
        coverage_id=COVERAGE_ID,
        title="Selected plastic section capacity",
        method_id=evidence.blocks.plastic_method_id,
        axes=shape.axes,
        final_step_id="selected-plastic-capacity-result",
        steps=tuple(steps.items),
        warnings=calculation_warnings,
        assumptions=(
            "Solver outputs are retained; capacity mechanics are not recomputed by the trace builder.",
        ),
    )


def build_plastic_capacity_trace_family(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    context: Mapping[str, Any],
) -> PlasticCapacityTraceFamily:
    """Build and self-audit the exact CT-002 finite or failed branch."""

    if not isinstance(context, Mapping):
        raise TraceValidationError("CT-002 context must be a mapping")
    evidence = _evidence(inp, out)
    try:
        shape = trace_shape(
            evidence.blocks,
            context,
            cardinality=len(evidence.points),
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
