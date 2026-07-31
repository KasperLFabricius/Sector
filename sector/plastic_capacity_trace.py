"""Unpublished CT-002 trace for the selected plastic-capacity state."""

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
    SOURCE_INPUT,
    SOURCE_PROJECT,
    TraceCalculation,
    TraceDependency,
    TraceResult,
    TraceSource,
    TraceStep,
    TraceUnit,
    TraceValidationError,
    create_bundle,
)
from .section_trace_blocks import (
    MaterialBlock,
    SectionTraceBlocks,
    context_axes,
    context_id,
    section_trace_blocks,
)
from .trace_registry import (
    TraceFamilyContract,
    TraceMemberContract,
    TraceRegistryContract,
    TraceSourceContract,
    audit_trace_registry,
)

_ONE = TraceUnit(symbol="1", dimension="scalar")
_AREA = TraceUnit(symbol="m2", dimension="area")
_LENGTH = TraceUnit(symbol="m", dimension="length")
_FORCE = TraceUnit(symbol="kN", dimension="force")
_MOMENT = TraceUnit(symbol="kNm", dimension="moment")
_STRESS = TraceUnit(symbol="MPa", dimension="stress")
_ANGLE = TraceUnit(symbol="degrees", dimension="angle")
_CURVATURE = TraceUnit(symbol="1/m", dimension="curvature")
_STRAIN = TraceUnit(symbol="%", dimension="strain")

_INPUT_SOURCE = TraceSource(
    kind=SOURCE_INPUT,
    method_id="sector-section-input",
)
_SOLVER_SOURCE = TraceSource(
    kind=SOURCE_PROJECT,
    method_id="sector-plastic-section-solver",
)
_SELECTION_SOURCE = TraceSource(
    kind=SOURCE_PROJECT,
    method_id="sector-retained-envelope-selection",
)
_PROBE_SHA256 = "0" * 64
_MATERIAL_STRESS_FIELDS = frozenset(
    {
        "fck",
        "fytk",
        "fyck",
        "futk",
        "Es",
    }
)

_POINT_FIELDS = frozenset(
    {
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
    }
)


@dataclass(frozen=True, slots=True)
class PlasticCapacityTraceFamily:
    """One validated calculation and its exact single-member registry."""

    calculation: TraceCalculation
    registry: TraceRegistryContract


@dataclass(frozen=True, slots=True)
class _Evidence:
    blocks: SectionTraceBlocks
    points: tuple[Mapping[str, Any], ...]
    mx: tuple[float, ...]
    my: tuple[float, ...]
    selected_index: int
    demand: float
    resistance: float
    utilisation: float
    envelope_converged: bool


@dataclass(frozen=True, slots=True)
class _InputSteps:
    actions: Mapping[str, str]
    geometry: str
    concrete_law: str
    bar_laws: tuple[str, ...]
    tendon_laws: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _MemberSteps:
    angle: str
    mx: str
    my: str
    converged: str


@dataclass(frozen=True, slots=True)
class _ResultantSteps:
    force: str
    mx: str
    my: str


def _finite_result(value: float) -> TraceResult:
    return TraceResult(
        state=RESULT_FINITE,
        value=float(value),
    )


def _failed_result(reason: str) -> TraceResult:
    return TraceResult(
        state=RESULT_FAILED,
        value=None,
        reason=reason,
    )


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
            raise TraceValidationError(f"duplicate trace step ID {step_id}")
        try:
            resolved = tuple(
                TraceDependency(
                    step_id=item,
                    unit=self.by_id[item].unit,
                )
                for item in dependencies
            )
        except KeyError as exc:
            raise TraceValidationError(
                f"{step_id} has an undeclared dependency {exc.args[0]}"
            ) from exc
        if substituted is None:
            substituted = (
                f"{symbol} = {result.value!r}"
                if result.state == RESULT_FINITE
                else f"{symbol}: {result.state}; {result.reason}"
            )
        step = TraceStep(
            step_id=step_id,
            title=title,
            dependencies=resolved,
            quantity_role=role,
            source=source,
            symbol=symbol,
            unit=unit,
            actual_expression=expression,
            substituted_expression=substituted,
            result=result,
            warnings=warnings,
            assumptions=assumptions,
        )
        self.items.append(step)
        self.by_id[step_id] = step
        return step_id

    def input(
        self,
        step_id: str,
        title: str,
        symbol: str,
        unit: TraceUnit,
        value: float,
    ) -> str:
        return self.add(
            step_id,
            title,
            symbol,
            unit,
            _finite_result(value),
            role=ROLE_USER_INPUT,
            source=_INPUT_SOURCE,
            expression=f"{symbol} supplied to the section solver",
        )

    def method(
        self,
        step_id: str,
        title: str,
        symbol: str,
        unit: TraceUnit,
        result: TraceResult,
        *,
        source: TraceSource,
        assumptions: tuple[str, ...] = (),
    ) -> str:
        return self.add(
            step_id,
            title,
            symbol,
            unit,
            result,
            role=ROLE_METHOD_VALUE,
            source=source,
            expression=f"{symbol} retained method value",
            assumptions=assumptions,
        )

    def computed(
        self,
        step_id: str,
        title: str,
        symbol: str,
        unit: TraceUnit,
        result: TraceResult,
        dependencies: tuple[str, ...],
        *,
        source: TraceSource = _SOLVER_SOURCE,
        expression: str,
        role: str = ROLE_COMPUTED,
        warnings: tuple[str, ...] = (),
        assumptions: tuple[str, ...] = (),
    ) -> str:
        return self.add(
            step_id,
            title,
            symbol,
            unit,
            result,
            role=role,
            source=source,
            dependencies=dependencies,
            expression=expression,
            warnings=warnings,
            assumptions=assumptions,
        )


class _ContractSteps:
    """Independent frozen declaration of exact step order and dependencies."""

    def __init__(self) -> None:
        self.items: list[tuple[str, tuple[str, ...]]] = []
        self.ids: set[str] = set()

    def add(self, step_id: str, *dependencies: str) -> str:
        if step_id in self.ids:
            raise TraceValidationError(
                f"duplicate registry step contract ID {step_id}"
            )
        missing = tuple(
            dependency
            for dependency in dependencies
            if dependency not in self.ids
        )
        if missing:
            raise TraceValidationError(
                f"{step_id} registry contract has undeclared dependencies "
                f"{missing!r}"
            )
        self.items.append((step_id, tuple(dependencies)))
        self.ids.add(step_id)
        return step_id


def _finite(value: Any, label: str) -> float:
    if type(value) not in {int, float} or type(value) is bool:
        raise TraceValidationError(f"{label} must be a non-Boolean number")
    result = float(value)
    if not math.isfinite(result):
        raise TraceValidationError(f"{label} must be finite")
    return result


def _extended(value: Any, label: str) -> TraceResult:
    if type(value) not in {int, float} or type(value) is bool:
        raise TraceValidationError(f"{label} must be a non-Boolean number")
    number = float(value)
    if math.isnan(number):
        raise TraceValidationError(f"{label} cannot be NaN")
    if number == math.inf:
        return TraceResult(
            state=RESULT_POSITIVE_INFINITY,
            value=None,
            reason=f"{label} is parallel to the positive coordinate axis",
        )
    if number == -math.inf:
        return TraceResult(
            state=RESULT_NEGATIVE_INFINITY,
            value=None,
            reason=f"{label} is parallel to the negative coordinate axis",
        )
    return _finite_result(number)


def _sequence(value: Any, label: str) -> tuple[Any, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TraceValidationError(f"{label} must be a retained sequence")
    return tuple(value)


def _close(actual: float, expected: float) -> bool:
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
    if actual_fields != set(_POINT_FIELDS):
        missing = sorted(_POINT_FIELDS - actual_fields)
        extra = sorted(str(item) for item in actual_fields - _POINT_FIELDS)
        details = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if extra:
            details.append(f"unexpected {', '.join(extra)}")
        raise TraceValidationError(f"{label} fields: {'; '.join(details)}")

    finite_fields = _POINT_FIELDS - {"na_x", "na_y", "converged"}
    values = {
        name: _finite(point[name], f"{label} {name}")
        for name in finite_fields
    }
    _extended(point["na_x"], f"{label} na_x")
    _extended(point["na_y"], f"{label} na_y")
    if type(point["converged"]) is not bool:
        raise TraceValidationError(f"{label} converged must be Boolean")

    checks = (
        (values["Mx"], mx, "Mx array member"),
        (values["My"], my, "My array member"),
        (
            sum(
                values[f"{kind}_force"]
                for kind in ("concrete", "steel", "tendon")
            ),
            values["axial"],
            "axial material resultants",
        ),
        (
            sum(
                values[f"{kind}_mx"]
                for kind in ("concrete", "steel", "tendon")
            ),
            values["Mx"],
            "x-moment material resultants",
        ),
        (
            sum(
                values[f"{kind}_my"]
                for kind in ("concrete", "steel", "tendon")
            ),
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
        (
            values["axial_action"],
            -values["axial"],
            "axial action convention",
        ),
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
    if values["compression_depth"] <= 0.0 or values["kappa"] <= 0.0:
        raise TraceValidationError(
            f"{label} needs positive compression depth and curvature"
        )

    angle = math.radians(values["V"])
    direction_x = math.cos(angle)
    direction_y = math.sin(angle)
    neutral_axis_depth = values["neutral_axis_depth"]
    concrete_projections = tuple(
        x * direction_x + y * direction_y
        for ring in blocks.geometry.rings
        for x, y in ring
    )
    expected_neutral_axis_depth = (
        max(concrete_projections) - values["compression_depth"]
    )
    _require_close(
        neutral_axis_depth,
        expected_neutral_axis_depth,
        f"{label} neutral-axis depth",
    )
    _require_close(
        values["eps_c"],
        -values["kappa"] * values["compression_depth"] * 100.0,
        f"{label} concrete strain plane",
    )

    bar_strains = tuple(
        values["kappa"]
        * (
            bar.x * direction_x
            + bar.y * direction_y
            - neutral_axis_depth
        )
        for bar in blocks.geometry.bars
    )
    expected_tensile_steel = (
        -min(bar_strains) * 100.0 if bar_strains else 0.0
    )
    expected_compressive_steel = (
        -max(bar_strains) * 100.0 if bar_strains else 0.0
    )
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
            - neutral_axis_depth
        )
        for tendon, law in zip(
            blocks.geometry.tendons,
            blocks.tendons,
        )
    )
    expected_tendon_strain = (
        max(tendon_strains) * 100.0 if tendon_strains else 0.0
    )
    _require_close(
        values["eps_cable"],
        expected_tendon_strain,
        f"{label} tendon strain plane",
    )

    for field, direction in (("na_x", direction_x), ("na_y", direction_y)):
        retained = float(point[field])
        if abs(direction) <= 1.0e-12:
            if retained != math.inf:
                raise TraceValidationError(
                    f"{label} {field} must be explicit positive infinity"
                )
        else:
            _require_close(
                retained,
                neutral_axis_depth / direction,
                f"{label} {field}",
            )
    return point


def _evidence(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
) -> _Evidence:
    if not isinstance(inp, Mapping) or not isinstance(out, Mapping):
        raise TraceValidationError("CT-002 input and result must be mappings")
    try:
        blocks = section_trace_blocks(inp)
    except (KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"CT-002 shared input evidence: {exc}") from exc
    if len(blocks.geometry.bars) != len(blocks.bars):
        raise TraceValidationError(
            "CT-002 bar geometry and material-law cardinalities differ"
        )
    if len(blocks.geometry.tendons) != len(blocks.tendons):
        raise TraceValidationError(
            "CT-002 tendon geometry and material-law cardinalities differ"
        )

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

    selected = result.get("util_gov")
    if type(selected) is not int:
        raise TraceValidationError(
            "util_gov must be a required non-Boolean integer"
        )
    if selected < 0 or selected >= len(points):
        raise TraceValidationError("util_gov is outside the retained cardinality")
    if result.get("closed") is not True or result.get("check_util") is not True:
        raise TraceValidationError(
            "selected CT-002 evidence needs a closed checked envelope"
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

    demand = _finite(result.get("demand"), "plastic retained moment demand")
    resistance = _finite(
        result.get("resistance"),
        "plastic retained governing resistance",
    )
    utilisation = _finite(result.get("util"), "plastic utilisation")
    if demand <= 0.0 or resistance <= 0.0 or utilisation <= 0.0:
        raise TraceValidationError(
            "selected CT-002 evidence needs positive retained demand, "
            "resistance, and utilisation"
        )
    _require_close(
        demand,
        math.hypot(actions["Mx_pl"], actions["My_pl"]),
        "plastic retained moment demand",
    )
    _require_close(
        utilisation,
        demand / resistance,
        "plastic retained demand/resistance utilisation",
    )

    # Delegate semantic selection validation to the one authoritative radial
    # selector. The trace publishes only the retained result above; no radial
    # formula or substitute capacity calculation is implemented here.
    authoritative = combined.radial_util_result(
        mx,
        my,
        actions["Mx_pl"],
        actions["My_pl"],
    )
    if authoritative.governing_index != selected:
        raise TraceValidationError(
            "plastic retained util_gov contradicts the authoritative "
            "envelope selection"
        )
    if authoritative.resistance is None:
        raise TraceValidationError(
            "plastic retained selection has no authoritative ray resistance"
        )
    _require_close(
        demand,
        authoritative.demand,
        "plastic retained authoritative moment demand",
    )
    _require_close(
        resistance,
        authoritative.resistance,
        "plastic retained authoritative governing resistance",
    )
    _require_close(
        utilisation,
        authoritative.utilisation,
        "plastic retained authoritative utilisation",
    )

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
    )


def _material_vector(
    steps: _Steps,
    block: MaterialBlock,
    prefix: str,
) -> str:
    leaves: list[str] = []
    identity = (
        f"element_id={block.element_id}",
        f"material_id={block.material_id}",
    )
    for name, value in block.values:
        token = name.lower().replace("_", "-")
        unit = _STRESS if name in _MATERIAL_STRESS_FIELDS else _ONE
        leaves.append(
            steps.method(
                f"{prefix}-{token}",
                f"{block.kind} law value {name}",
                f"{prefix}.{name}",
                unit,
                _finite_result(value),
                source=block.provenance.source,
                assumptions=identity,
            )
        )
    return steps.computed(
        f"{prefix}-vector",
        f"Exact {block.kind} solver-law vector",
        f"I_{prefix}",
        _ONE,
        _finite_result(1.0),
        tuple(leaves),
        expression="ordered immutable material-law vector",
        assumptions=identity
        + ("Unity records identity and is not a conformity verdict.",),
    )


def _input_closure(
    steps: _Steps,
    blocks: SectionTraceBlocks,
) -> _InputSteps:
    actions = dict(blocks.plastic_actions.values)
    action_specs = (
        (
            "P_pl",
            "action-p-ed",
            "Requested axial action (tension positive)",
            "N_Ed",
            _FORCE,
        ),
        (
            "Mx_pl",
            "action-mx-ed",
            "Requested x-axis moment",
            "Mx_Ed",
            _MOMENT,
        ),
        (
            "My_pl",
            "action-my-ed",
            "Requested y-axis moment",
            "My_Ed",
            _MOMENT,
        ),
    )
    action_steps = {
        key: steps.input(step_id, title, symbol, unit, actions[key])
        for key, step_id, title, symbol, unit in action_specs
    }

    geometry_leaves: list[str] = []
    for ring_index, ring in enumerate(blocks.geometry.rings, start=1):
        for point_index, (x, y) in enumerate(ring, start=1):
            stem = f"geometry-ring-{ring_index:03d}-point-{point_index:03d}"
            geometry_leaves.extend(
                (
                    steps.input(f"{stem}-x", "Concrete point x", "x", _LENGTH, x),
                    steps.input(f"{stem}-y", "Concrete point y", "y", _LENGTH, y),
                )
            )
    for kind, elements in (
        ("bar", blocks.geometry.bars),
        ("tendon", blocks.geometry.tendons),
    ):
        for index, element in enumerate(elements, start=1):
            stem = f"geometry-{kind}-{index:03d}"
            geometry_leaves.extend(
                (
                    steps.input(
                        f"{stem}-x",
                        f"{kind} point x",
                        "x",
                        _LENGTH,
                        element.x,
                    ),
                    steps.input(
                        f"{stem}-y",
                        f"{kind} point y",
                        "y",
                        _LENGTH,
                        element.y,
                    ),
                    steps.input(
                        f"{stem}-area",
                        f"{kind} area",
                        "A",
                        _AREA,
                        element.area,
                    ),
                )
            )
    geometry = steps.computed(
        "section-geometry-vector",
        "Exact ordered section geometry",
        "I_geometry",
        _ONE,
        _finite_result(1.0),
        tuple(geometry_leaves),
        expression="ordered rings, bars, and tendons supplied to the solver",
        assumptions=("Unity records identity and is not a conformity verdict.",),
    )

    concrete = _material_vector(steps, blocks.concrete, "concrete-law")
    bars = tuple(
        _material_vector(steps, block, f"bar-{index:03d}-law")
        for index, block in enumerate(blocks.bars, start=1)
    )
    tendons = tuple(
        _material_vector(steps, block, f"tendon-{index:03d}-law")
        for index, block in enumerate(blocks.tendons, start=1)
    )
    return _InputSteps(
        actions=action_steps,
        geometry=geometry,
        concrete_law=concrete,
        bar_laws=bars,
        tendon_laws=tendons,
    )


def _calculation(
    evidence: _Evidence,
    *,
    context: Mapping[str, Any],
) -> TraceCalculation:
    blocks = evidence.blocks
    steps = _Steps()
    inputs = _input_closure(steps, blocks)
    action = inputs.actions
    geometry = inputs.geometry
    concrete_law = inputs.concrete_law
    bar_laws = inputs.bar_laws
    tendon_laws = inputs.tendon_laws
    law_closure = (concrete_law, *bar_laws, *tendon_laws)
    solver_closure = (action["P_pl"], geometry, *law_closure)

    member_steps: list[str] = []
    member_records: list[_MemberSteps] = []
    for index, point in enumerate(evidence.points):
        stem = f"retained-member-{index:03d}"
        angle = steps.method(
            f"{stem}-angle",
            f"Retained member {index} neutral-axis angle",
            f"V_{index}",
            _ANGLE,
            _finite_result(point["V"]),
            source=_SELECTION_SOURCE,
            assumptions=(f"retained_member={index}",),
        )
        mx = steps.computed(
            f"{stem}-mx",
            f"Retained member {index} x resistance",
            f"Mx_Rd_{index}",
            _MOMENT,
            _finite_result(evidence.mx[index]),
            (angle, *solver_closure),
            expression="solver-integrated x-axis resistance",
        )
        my = steps.computed(
            f"{stem}-my",
            f"Retained member {index} y resistance",
            f"My_Rd_{index}",
            _MOMENT,
            _finite_result(evidence.my[index]),
            (angle, *solver_closure),
            expression="solver-integrated y-axis resistance",
        )
        converged = steps.computed(
            f"{stem}-converged",
            f"Retained member {index} convergence state",
            f"I_eq_{index}",
            _ONE,
            _finite_result(1.0 if point["converged"] else 0.0),
            (mx, my),
            expression="retained solver convergence flag",
            assumptions=("This is an equilibrium state, not a conformity verdict.",),
        )
        member_steps.extend((angle, mx, my, converged))
        member_records.append(
            _MemberSteps(
                angle=angle,
                mx=mx,
                my=my,
                converged=converged,
            )
        )

    arrays = steps.computed(
        "retained-capacity-arrays",
        "Exact retained Mx and My capacity arrays",
        "I_arrays",
        _ONE,
        _finite_result(1.0),
        tuple(member_steps),
        source=_SELECTION_SOURCE,
        expression="ordered retained capacity members",
        assumptions=("Unity records exact array closure and is not a verdict.",),
    )
    cardinality = steps.computed(
        "retained-cardinality",
        "Retained capacity member count",
        "n_members",
        _ONE,
        _finite_result(len(evidence.points)),
        (arrays,),
        source=_SELECTION_SOURCE,
        expression="length of aligned points, Mx, and My arrays",
    )
    selected_index = steps.computed(
        "selected-member-index",
        "Exact solver-selected utilisation member",
        "util_gov",
        _ONE,
        _finite_result(evidence.selected_index),
        (arrays, cardinality),
        source=_SELECTION_SOURCE,
        expression="retained util_gov without substitution",
        assumptions=("No envelope maximum or alternate member is substituted.",),
    )
    selected = evidence.points[evidence.selected_index]
    selected_member = member_records[evidence.selected_index]
    selected_angle = selected_member.angle
    selected_mx = selected_member.mx
    selected_my = selected_member.my
    selected_flag = selected_member.converged

    selected_state = (selected_index, selected_angle, geometry, *law_closure)
    curvature = steps.computed(
        "selected-curvature",
        "Selected governing ultimate curvature",
        "kappa",
        _CURVATURE,
        _finite_result(selected["kappa"]),
        selected_state,
        expression="retained solver governing-curvature state",
    )
    compression_depth = steps.computed(
        "selected-compression-depth",
        "Selected compression depth",
        "c",
        _LENGTH,
        _finite_result(selected["compression_depth"]),
        (curvature, geometry),
        expression="retained solver compression depth",
    )
    neutral_axis_depth = steps.computed(
        "selected-neutral-axis-depth",
        "Selected neutral-axis depth projection",
        "s_na",
        _LENGTH,
        _finite_result(selected["neutral_axis_depth"]),
        (compression_depth, selected_angle, geometry),
        expression="retained solver neutral-axis depth",
    )
    na_x = steps.computed(
        "selected-na-x",
        "Selected neutral-axis x intercept",
        "x_na",
        _LENGTH,
        _extended(selected["na_x"], "selected na_x"),
        (neutral_axis_depth, selected_angle),
        expression="retained neutral-axis x intercept",
    )
    na_y = steps.computed(
        "selected-na-y",
        "Selected neutral-axis y intercept",
        "y_na",
        _LENGTH,
        _extended(selected["na_y"], "selected na_y"),
        (neutral_axis_depth, selected_angle),
        expression="retained neutral-axis y intercept",
    )
    state_geometry = (
        curvature,
        compression_depth,
        neutral_axis_depth,
        na_x,
        na_y,
        geometry,
    )

    strain_steps: list[str] = []
    for field, title, symbol in (
        ("eps_c", "Selected extreme concrete strain", "eps_c"),
        ("eps_s", "Selected tensile steel strain", "eps_s"),
        ("eps_s_comp", "Selected compressive steel strain", "eps_s_c"),
        ("eps_cable", "Selected tendon strain", "eps_p"),
    ):
        strain_steps.append(
            steps.computed(
                f"selected-{field.replace('_', '-')}",
                title,
                symbol,
                _STRAIN,
                _finite_result(selected[field]),
                (*state_geometry, *law_closure),
                expression="retained solver strain-plane result",
            )
        )

    material_resultants: dict[str, _ResultantSteps] = {}
    for kind, laws in (
        ("concrete", (concrete_law,)),
        ("steel", bar_laws),
        ("tendon", tendon_laws),
    ):
        dependencies = (
            action["P_pl"],
            *state_geometry,
            *(laws or law_closure),
        )
        force = steps.computed(
            f"{kind}-force-resultant",
            f"Selected {kind} axial resultant",
            f"N_{kind}",
            _FORCE,
            _finite_result(selected[f"{kind}_force"]),
            dependencies,
            expression=f"solver-integrated {kind} force resultant",
        )
        mx = steps.computed(
            f"{kind}-mx-resultant",
            f"Selected {kind} x-moment resultant",
            f"Mx_{kind}",
            _MOMENT,
            _finite_result(selected[f"{kind}_mx"]),
            dependencies,
            expression=f"solver-integrated {kind} x-moment resultant",
        )
        my = steps.computed(
            f"{kind}-my-resultant",
            f"Selected {kind} y-moment resultant",
            f"My_{kind}",
            _MOMENT,
            _finite_result(selected[f"{kind}_my"]),
            dependencies,
            expression=f"solver-integrated {kind} y-moment resultant",
        )
        material_resultants[kind] = _ResultantSteps(
            force=force,
            mx=mx,
            my=my,
        )

    force_ids = tuple(item.force for item in material_resultants.values())
    mx_ids = tuple(item.mx for item in material_resultants.values())
    my_ids = tuple(item.my for item in material_resultants.values())
    axial = steps.computed(
        "selected-solver-axial",
        "Selected achieved solver axial resultant",
        "N_achieved_solver",
        _FORCE,
        _finite_result(selected["axial"]),
        force_ids,
        expression="retained solver-integrated axial resultant",
    )
    achieved_action = steps.computed(
        "selected-achieved-axial-action",
        "Selected achieved axial action (tension positive)",
        "N_achieved",
        _FORCE,
        _finite_result(selected["axial_action"]),
        (axial, action["P_pl"]),
        expression="retained solver result in the tension-positive action convention",
    )
    residual = steps.computed(
        "selected-axial-residual",
        "Selected solver axial-equilibrium residual",
        "Delta_N",
        _FORCE,
        _finite_result(selected["axial_residual"]),
        (axial, action["P_pl"]),
        expression="retained solver axial-equilibrium residual",
    )
    tolerance = steps.computed(
        "selected-axial-tolerance",
        "Selected solver axial-equilibrium tolerance",
        "tol_N",
        _FORCE,
        _finite_result(selected["axial_tolerance"]),
        (action["P_pl"],),
        expression="retained solver axial-equilibrium tolerance",
    )
    equilibrium = steps.computed(
        "selected-equilibrium-state",
        "Selected axial-equilibrium state",
        "I_equilibrium",
        _ONE,
        _finite_result(1.0 if selected["converged"] else 0.0),
        (residual, tolerance, selected_flag),
        expression="retained convergence checked against residual tolerance",
        assumptions=("This is an equilibrium state, not a conformity verdict.",),
    )
    envelope = steps.computed(
        "envelope-convergence-state",
        "All retained envelope members converged",
        "I_envelope",
        _ONE,
        _finite_result(1.0 if evidence.envelope_converged else 0.0),
        tuple(record.converged for record in member_records),
        expression="all retained member convergence states",
        assumptions=("This is an equilibrium state, not a conformity verdict.",),
    )

    integrated_mx = steps.computed(
        "selected-integrated-mx",
        "Selected integrated x-moment resistance",
        "Mx_Rd",
        _MOMENT,
        _finite_result(selected["Mx"]),
        mx_ids,
        expression="retained solver-integrated x-moment resultant",
    )
    integrated_my = steps.computed(
        "selected-integrated-my",
        "Selected integrated y-moment resistance",
        "My_Rd",
        _MOMENT,
        _finite_result(selected["My"]),
        my_ids,
        expression="retained solver-integrated y-moment resultant",
    )
    moment_consistency = steps.computed(
        "selected-moment-array-consistency",
        "Selected point matches retained capacity arrays",
        "I_moment_arrays",
        _ONE,
        _finite_result(1.0),
        (integrated_mx, integrated_my, selected_mx, selected_my),
        source=_SELECTION_SOURCE,
        expression="selected point Mx and My equal exact array members",
        assumptions=("Unity records equality and is not a conformity verdict.",),
    )

    compression_force = steps.computed(
        "selected-compression-resultant",
        "Selected total compression resultant",
        "C_Rd",
        _FORCE,
        _finite_result(selected["comp_force"]),
        (equilibrium, *force_ids),
        expression="retained solver compression resultant",
    )
    compression_mx = steps.computed(
        "selected-compression-mx",
        "Selected compression resultant moment about x",
        "Mx_C",
        _MOMENT,
        _finite_result(selected["comp_mx"]),
        (compression_force, integrated_mx),
        expression="retained compression first moment about x",
    )
    compression_my = steps.computed(
        "selected-compression-my",
        "Selected compression resultant moment about y",
        "My_C",
        _MOMENT,
        _finite_result(selected["comp_my"]),
        (compression_force, integrated_my),
        expression="retained compression first moment about y",
    )
    tension_force = steps.computed(
        "selected-tension-resultant",
        "Selected total tension resultant",
        "T_Rd",
        _FORCE,
        _finite_result(selected["tension_force"]),
        (axial, compression_force),
        expression="retained solver tension resultant",
    )
    tension_mx = steps.computed(
        "selected-tension-mx",
        "Selected tension resultant moment about x",
        "Mx_T",
        _MOMENT,
        _finite_result(selected["tension_mx"]),
        (tension_force, integrated_mx, compression_mx),
        expression="retained tension first moment about x",
    )
    tension_my = steps.computed(
        "selected-tension-my",
        "Selected tension resultant moment about y",
        "My_T",
        _MOMENT,
        _finite_result(selected["tension_my"]),
        (tension_force, integrated_my, compression_my),
        expression="retained tension first moment about y",
    )
    lever_dx = steps.computed(
        "selected-lever-dx",
        "Selected internal lever-arm x component",
        "dx",
        _LENGTH,
        _finite_result(selected["dx"]),
        (compression_force, compression_my, tension_force, tension_my),
        expression="retained solver resultant-centroid separation",
    )
    lever_dy = steps.computed(
        "selected-lever-dy",
        "Selected internal lever-arm y component",
        "dy",
        _LENGTH,
        _finite_result(selected["dy"]),
        (compression_force, compression_mx, tension_force, tension_mx),
        expression="retained solver resultant-centroid separation",
    )
    lever = steps.computed(
        "selected-lever-arm",
        "Selected internal resultant lever arm",
        "L",
        _LENGTH,
        _finite_result(selected["lever"]),
        (lever_dx, lever_dy),
        expression="retained solver resultant-centroid lever arm",
    )

    demand = steps.computed(
        "requested-moment-resultant",
        "Retained requested resultant moment",
        "M_Ed",
        _MOMENT,
        _finite_result(evidence.demand),
        (action["Mx_pl"], action["My_pl"]),
        source=_SELECTION_SOURCE,
        expression="retained applied-ray moment demand",
    )
    resistance = steps.computed(
        "governing-ray-resistance",
        "Retained governing resistance on the requested moment ray",
        "M_Rd_ray",
        _MOMENT,
        _finite_result(evidence.resistance),
        (demand, arrays, selected_index),
        source=_SELECTION_SOURCE,
        expression="retained applied-ray envelope intersection resistance",
    )
    retained_utilisation = steps.computed(
        "retained-utilisation",
        "Retained radial envelope utilisation",
        "eta",
        _ONE,
        _finite_result(evidence.utilisation),
        (
            demand,
            resistance,
            arrays,
            selected_index,
            moment_consistency,
        ),
        source=_SELECTION_SOURCE,
        expression="retained result of the existing ray-envelope intersection",
    )

    converged = evidence.envelope_converged and bool(selected["converged"])
    final_result = (
        _finite_result(evidence.utilisation)
        if converged
        else _failed_result(
            "selected plastic-capacity trace failed solver equilibrium"
        )
    )
    warnings = (
        ()
        if converged
        else ("No finite CT-002 result is issued for failed equilibrium.",)
    )
    final = steps.computed(
        "selected-plastic-capacity-result",
        "Selected plastic-capacity utilisation and result",
        "eta_CT002",
        _ONE,
        final_result,
        (
            achieved_action,
            residual,
            tolerance,
            equilibrium,
            envelope,
            integrated_mx,
            integrated_my,
            compression_force,
            lever,
            *strain_steps,
            demand,
            resistance,
            retained_utilisation,
        ),
        source=_SELECTION_SOURCE,
        expression="exact selected CT-002 retained result",
        role=ROLE_FINAL,
        warnings=warnings,
    )

    axes = context_axes(
        context,
        retained_cardinality=str(len(evidence.points)),
        selected_member=str(evidence.selected_index),
    )
    return TraceCalculation(
        calculation_id=f"plastic.{context_id(context)}.selected-capacity",
        coverage_id="ct-002",
        title="CT-002 selected plastic section-capacity state",
        method_id=blocks.plastic_method_id,
        axes=axes,
        final_step_id=final,
        steps=tuple(steps.items),
        warnings=warnings,
        assumptions=(
            "This trace records retained solver outputs and does not re-evaluate "
            "section mechanics.",
            "Input axial action is tension positive; solver resultants are "
            "compression positive.",
        ),
    )


def _source_contract(source: TraceSource) -> TraceSourceContract:
    return TraceSourceContract(
        kind=source.kind,
        method_id=source.method_id,
        edition=source.edition,
    )


def _contract_material_vector(
    steps: _ContractSteps,
    block: MaterialBlock,
    prefix: str,
) -> str:
    leaves = tuple(
        steps.add(f"{prefix}-{name.lower().replace('_', '-')}")
        for name, _ in block.values
    )
    return steps.add(f"{prefix}-vector", *leaves)


def _expected_step_contract(
    evidence: _Evidence,
) -> tuple[tuple[str, ...], tuple[tuple[str, tuple[str, ...]], ...]]:
    """Declare CT-002 order/dependencies without inspecting the calculation."""

    blocks = evidence.blocks
    steps = _ContractSteps()
    actions = {
        "P_pl": steps.add("action-p-ed"),
        "Mx_pl": steps.add("action-mx-ed"),
        "My_pl": steps.add("action-my-ed"),
    }

    geometry_leaves: list[str] = []
    for ring_index, ring in enumerate(blocks.geometry.rings, start=1):
        for point_index, _ in enumerate(ring, start=1):
            stem = f"geometry-ring-{ring_index:03d}-point-{point_index:03d}"
            geometry_leaves.extend(
                (
                    steps.add(f"{stem}-x"),
                    steps.add(f"{stem}-y"),
                )
            )
    for kind, elements in (
        ("bar", blocks.geometry.bars),
        ("tendon", blocks.geometry.tendons),
    ):
        for index, _ in enumerate(elements, start=1):
            stem = f"geometry-{kind}-{index:03d}"
            geometry_leaves.extend(
                (
                    steps.add(f"{stem}-x"),
                    steps.add(f"{stem}-y"),
                    steps.add(f"{stem}-area"),
                )
            )
    geometry = steps.add("section-geometry-vector", *geometry_leaves)

    concrete_law = _contract_material_vector(
        steps,
        blocks.concrete,
        "concrete-law",
    )
    bar_laws = tuple(
        _contract_material_vector(
            steps,
            block,
            f"bar-{index:03d}-law",
        )
        for index, block in enumerate(blocks.bars, start=1)
    )
    tendon_laws = tuple(
        _contract_material_vector(
            steps,
            block,
            f"tendon-{index:03d}-law",
        )
        for index, block in enumerate(blocks.tendons, start=1)
    )
    law_closure = (concrete_law, *bar_laws, *tendon_laws)
    solver_closure = (actions["P_pl"], geometry, *law_closure)

    member_steps: list[str] = []
    member_records: list[_MemberSteps] = []
    for index in range(len(evidence.points)):
        stem = f"retained-member-{index:03d}"
        angle = steps.add(f"{stem}-angle")
        mx = steps.add(f"{stem}-mx", angle, *solver_closure)
        my = steps.add(f"{stem}-my", angle, *solver_closure)
        converged = steps.add(f"{stem}-converged", mx, my)
        member_steps.extend((angle, mx, my, converged))
        member_records.append(
            _MemberSteps(
                angle=angle,
                mx=mx,
                my=my,
                converged=converged,
            )
        )

    arrays = steps.add("retained-capacity-arrays", *member_steps)
    cardinality = steps.add("retained-cardinality", arrays)
    selected_index = steps.add(
        "selected-member-index",
        arrays,
        cardinality,
    )
    selected_member = member_records[evidence.selected_index]

    curvature = steps.add(
        "selected-curvature",
        selected_index,
        selected_member.angle,
        geometry,
        *law_closure,
    )
    compression_depth = steps.add(
        "selected-compression-depth",
        curvature,
        geometry,
    )
    neutral_axis_depth = steps.add(
        "selected-neutral-axis-depth",
        compression_depth,
        selected_member.angle,
        geometry,
    )
    na_x = steps.add(
        "selected-na-x",
        neutral_axis_depth,
        selected_member.angle,
    )
    na_y = steps.add(
        "selected-na-y",
        neutral_axis_depth,
        selected_member.angle,
    )
    state_geometry = (
        curvature,
        compression_depth,
        neutral_axis_depth,
        na_x,
        na_y,
        geometry,
    )
    strain_steps = tuple(
        steps.add(
            step_id,
            *state_geometry,
            *law_closure,
        )
        for step_id in (
            "selected-eps-c",
            "selected-eps-s",
            "selected-eps-s-comp",
            "selected-eps-cable",
        )
    )

    material_resultants: dict[str, _ResultantSteps] = {}
    for kind, laws in (
        ("concrete", (concrete_law,)),
        ("steel", bar_laws),
        ("tendon", tendon_laws),
    ):
        dependencies = (
            actions["P_pl"],
            *state_geometry,
            *(laws or law_closure),
        )
        material_resultants[kind] = _ResultantSteps(
            force=steps.add(
                f"{kind}-force-resultant",
                *dependencies,
            ),
            mx=steps.add(
                f"{kind}-mx-resultant",
                *dependencies,
            ),
            my=steps.add(
                f"{kind}-my-resultant",
                *dependencies,
            ),
        )

    force_ids = tuple(item.force for item in material_resultants.values())
    mx_ids = tuple(item.mx for item in material_resultants.values())
    my_ids = tuple(item.my for item in material_resultants.values())
    axial = steps.add("selected-solver-axial", *force_ids)
    achieved_action = steps.add(
        "selected-achieved-axial-action",
        axial,
        actions["P_pl"],
    )
    residual = steps.add(
        "selected-axial-residual",
        axial,
        actions["P_pl"],
    )
    tolerance = steps.add(
        "selected-axial-tolerance",
        actions["P_pl"],
    )
    equilibrium = steps.add(
        "selected-equilibrium-state",
        residual,
        tolerance,
        selected_member.converged,
    )
    envelope = steps.add(
        "envelope-convergence-state",
        *(member.converged for member in member_records),
    )

    integrated_mx = steps.add("selected-integrated-mx", *mx_ids)
    integrated_my = steps.add("selected-integrated-my", *my_ids)
    moment_consistency = steps.add(
        "selected-moment-array-consistency",
        integrated_mx,
        integrated_my,
        selected_member.mx,
        selected_member.my,
    )

    compression_force = steps.add(
        "selected-compression-resultant",
        equilibrium,
        *force_ids,
    )
    compression_mx = steps.add(
        "selected-compression-mx",
        compression_force,
        integrated_mx,
    )
    compression_my = steps.add(
        "selected-compression-my",
        compression_force,
        integrated_my,
    )
    tension_force = steps.add(
        "selected-tension-resultant",
        axial,
        compression_force,
    )
    tension_mx = steps.add(
        "selected-tension-mx",
        tension_force,
        integrated_mx,
        compression_mx,
    )
    tension_my = steps.add(
        "selected-tension-my",
        tension_force,
        integrated_my,
        compression_my,
    )
    lever_dx = steps.add(
        "selected-lever-dx",
        compression_force,
        compression_my,
        tension_force,
        tension_my,
    )
    lever_dy = steps.add(
        "selected-lever-dy",
        compression_force,
        compression_mx,
        tension_force,
        tension_mx,
    )
    lever = steps.add("selected-lever-arm", lever_dx, lever_dy)

    demand = steps.add(
        "requested-moment-resultant",
        actions["Mx_pl"],
        actions["My_pl"],
    )
    resistance = steps.add(
        "governing-ray-resistance",
        demand,
        arrays,
        selected_index,
    )
    utilisation = steps.add(
        "retained-utilisation",
        demand,
        resistance,
        arrays,
        selected_index,
        moment_consistency,
    )
    steps.add(
        "selected-plastic-capacity-result",
        achieved_action,
        residual,
        tolerance,
        equilibrium,
        envelope,
        integrated_mx,
        integrated_my,
        compression_force,
        lever,
        *strain_steps,
        demand,
        resistance,
        utilisation,
    )

    step_ids = tuple(step_id for step_id, _ in steps.items)
    return step_ids, tuple(steps.items)


def _expected_registry(
    evidence: _Evidence,
    *,
    context: Mapping[str, Any],
) -> TraceRegistryContract:
    blocks = evidence.blocks
    step_ids, step_dependencies = _expected_step_contract(evidence)
    material_sources = (
        blocks.concrete.provenance.source,
        *(block.provenance.source for block in blocks.bars),
        *(block.provenance.source for block in blocks.tendons),
    )
    sources = frozenset(
        _source_contract(source)
        for source in (
            _INPUT_SOURCE,
            _SOLVER_SOURCE,
            _SELECTION_SOURCE,
            *material_sources,
        )
    )
    axes = context_axes(
        context,
        retained_cardinality=str(len(evidence.points)),
        selected_member=str(evidence.selected_index),
    )
    member = TraceMemberContract(
        member_id="selected-plastic-capacity",
        calculation_id=f"plastic.{context_id(context)}.selected-capacity",
        coverage_id="ct-002",
        method_id=blocks.plastic_method_id,
        axes=axes,
        sources=sources,
        result_states=frozenset({RESULT_FINITE, RESULT_FAILED}),
        step_ids=step_ids,
        step_dependencies=step_dependencies,
    )
    return TraceRegistryContract(
        registry_id="sector-ct-002-selected-plastic-capacity-v1",
        families=(
            TraceFamilyContract(
                family_id="ct-002-selected-plastic-capacity",
                members=(member,),
            ),
        ),
    )


def build_plastic_capacity_trace_family(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    context: Mapping[str, Any],
) -> PlasticCapacityTraceFamily:
    """Build and self-audit the exact selected CT-002 trace family."""

    if not isinstance(context, Mapping):
        raise TraceValidationError("CT-002 context must be a mapping")
    evidence = _evidence(inp, out)
    try:
        calculation = _calculation(evidence, context=context)
    except TraceValidationError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"CT-002 trace construction: {exc}") from exc
    registry = _expected_registry(evidence, context=context)
    probe = create_bundle(
        input_sha256=_PROBE_SHA256,
        result_sha256=_PROBE_SHA256,
        calculations=(calculation,),
    )
    audit_trace_registry(probe, registry)
    return PlasticCapacityTraceFamily(
        calculation=probe.calculations[0],
        registry=registry,
    )
