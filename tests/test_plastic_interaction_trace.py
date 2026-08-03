"""CT-003 radial and separately required CT-004 axis trace evidence."""

from __future__ import annotations

import copy
import dataclasses
import inspect
import math
from dataclasses import dataclass

import pytest

from sector import codes
from sector.calculation_trace import (
    RESULT_FAILED,
    RESULT_FINITE,
    SOURCE_PROJECT,
    SOURCE_STANDARD,
    TraceValidationError,
    bundle_to_json,
    create_bundle,
    seal_bundle,
    validate_bundle,
)
from sector.combined import RadialUtilResult, radial_util_result
from sector.materials import Prestress
from sector.plastic import (
    InteractionPoint,
    PlasticPoint,
    plastic_capacity_at_angle,
    solve_interaction,
    solve_plastic,
)
from sector.plastic_capacity_trace_contract import expected_sweep
import sector.plastic_interaction_trace as trace_module
from sector.plastic_interaction_trace import (
    build_plastic_interaction_trace_families,
    validate_plastic_interaction_trace_families,
)
from sector.plastic_interaction_trace_contract import (
    INTERACTION_CARDINALITY,
    INTERACTION_FAILED,
    INTERACTION_FINITE,
    INTERACTION_INTERVALS,
    RADIAL_FAILED_SELECTOR,
    RADIAL_FAILED_SWEEP,
    RADIAL_FINITE_SELECTED,
    RADIAL_FINITE_ZERO,
    action_step_id,
    axis_trace_shape,
    expected_registry,
    radial_trace_shape,
)
from sector.section import Section
from sector.section_trace_blocks import section_trace_blocks
from sector.trace_registry import audit_trace_registry


INPUT_SHA = "a" * 64
RESULT_SHA = "b" * 64
CONTEXT = {"case": "mixed radial and interaction", "stage": 4}


@dataclass(frozen=True)
class Case:
    inp: dict
    out: dict
    bundle: object
    radial_replay: tuple[PlasticPoint, ...]
    branches: dict[float, tuple[InteractionPoint, ...]]
    oracle_radial_points: tuple[PlasticPoint, ...]
    oracle_radial: tuple[float, float | None, float, int | None]
    oracle_axes: dict[str, tuple[PlasticPoint, ...]]


def _input() -> dict:
    section = Section.from_polygon(
        [(-0.20, -0.30), (0.20, -0.30), (0.20, 0.30), (-0.20, 0.30)],
        [
            (-0.15, -0.24, 600.0),
            (0.15, -0.24, 500.0),
            (0.15, 0.24, 450.0),
            (-0.15, 0.24, 550.0),
        ],
        tendons_xy_area_mm2=[(0.0, -0.18, 350.0)],
    )
    return {
        "section": section,
        "concrete": codes.EC2_2005.concrete(35.0),
        "steel": codes.EC2_2005.steel(500.0),
        "prestress": Prestress(curve=1, IS=0.004, gamma_y=1.15),
        "concrete_preset": codes.EC2_2005.label,
        "mild_preset": codes.EC2_2005.label,
        "prestress_preset": "Curve 1 (built-in)",
        "P_pl": -300.0,
        "Mx_pl": 45.0,
        "My_pl": 30.0,
        "v_min": 0.0,
        "v_max": 360.0,
        "v_inc": 90.0,
        "check_util": True,
        "interaction": True,
    }


def _retained_output(inp: dict):
    plan = expected_sweep(inp["v_min"], inp["v_max"], inp["v_inc"])
    section = inp["section"]
    prestress = inp.get("prestress") if section.tendons else None
    radial_points = tuple(
        solve_plastic(
            section,
            inp["concrete"],
            inp["steel"],
            -inp["P_pl"],
            plan.solver_min,
            plan.angles[-1],
            plan.solver_increment,
            prestress=prestress,
            bar_materials=inp.get("bar_materials"),
            tendon_materials=inp.get("tendon_materials"),
        )
    )
    mx = [point.Mx for point in radial_points]
    my = [point.My for point in radial_points]
    radial = radial_util_result(mx, my, inp["Mx_pl"], inp["My_pl"])

    branches = {}
    for angle in (90.0, 270.0, 0.0, 180.0):
        branches[angle] = tuple(
            solve_interaction(
                section,
                inp["concrete"],
                inp["steel"],
                angle,
                prestress=prestress,
                bar_materials=inp.get("bar_materials"),
                tendon_materials=inp.get("tendon_materials"),
                n_points=INTERACTION_INTERVALS,
            )
        )
    loop_x = branches[90.0] + tuple(reversed(branches[270.0]))
    loop_y = branches[0.0] + tuple(reversed(branches[180.0]))
    out = {
        "plastic": {
            "mx": mx,
            "my": my,
            "util": radial.utilisation,
            "util_gov": radial.governing_index,
            "util_demand": radial.demand,
            "util_resistance": radial.resistance,
            "closed": plan.closed,
            "check_util": True,
            "applied": (inp["Mx_pl"], inp["My_pl"]),
            "converged": all(point.converged for point in radial_points),
            "points": [
                {
                    "V": point.V,
                    "Mx": point.Mx,
                    "My": point.My,
                    "converged": point.converged,
                }
                for point in radial_points
            ],
            "interaction": {
                "x": {
                    "N": [-point.axial for point in loop_x],
                    "M": [point.Mx for point in loop_x],
                    "applied": (inp["P_pl"], inp["Mx_pl"]),
                    "converged": all(point.converged for point in loop_x),
                },
                "y": {
                    "N": [-point.axial for point in loop_y],
                    "M": [point.My for point in loop_y],
                    "applied": (inp["P_pl"], inp["My_pl"]),
                    "converged": all(point.converged for point in loop_y),
                },
            },
        }
    }
    return out, radial_points, branches


def _oracle_angles(v_min, v_max, v_inc):
    """Derive the requested closed sweep without a trace or solver helper."""

    start, stop, increment = map(float, (v_min, v_max, v_inc))
    span = max(stop, start) - start
    if span < 1.0e-9 or increment <= 0.0:
        return (start,)
    intervals = max(1, math.ceil(span / increment))
    step = span / intervals
    count = intervals if span >= 360.0 - 1.0e-6 else intervals + 1
    return tuple(start + index * step for index in range(count))


def _oracle_radial(points, applied_x, applied_y):
    """Intersect the original applied ray with original low-level capacities."""

    demand = math.hypot(applied_x, applied_y)
    if demand < 1.0e-9:
        return demand, None, 0.0, None
    ray_x, ray_y = applied_x / demand, applied_y / demand
    hits = []
    for index, first in enumerate(points):
        second = points[(index + 1) % len(points)]
        edge_x = second.Mx - first.Mx
        edge_y = second.My - first.My
        denominator = ray_x * edge_y - ray_y * edge_x
        if abs(denominator) <= 1.0e-12:
            continue
        distance = (edge_y * first.Mx - edge_x * first.My) / denominator
        fraction = (ray_y * first.Mx - ray_x * first.My) / denominator
        if -1.0e-9 <= fraction <= 1.0 + 1.0e-9 and distance > 1.0e-9:
            hits.append((distance, index))
    if not hits:
        return demand, None, math.inf, None
    resistance, edge = min(hits)
    crossing_x, crossing_y = ray_x * resistance, ray_y * resistance
    next_index = (edge + 1) % len(points)
    first_distance = math.hypot(
        points[edge].Mx - crossing_x, points[edge].My - crossing_y
    )
    second_distance = math.hypot(
        points[next_index].Mx - crossing_x,
        points[next_index].My - crossing_y,
    )
    selected = edge if first_distance <= second_distance else next_index
    return demand, resistance, demand / resistance, selected


def _oracle_capacity(inp, requested, angle):
    section = inp["section"]
    return plastic_capacity_at_angle(
        section,
        inp["concrete"],
        inp["steel"],
        requested,
        angle,
        prestress=(inp.get("prestress") if section.tendons else None),
        bar_materials=inp.get("bar_materials"),
        tendon_materials=inp.get("tendon_materials"),
    )


def _oracle_axis(inp, axis):
    """Rebuild both branches directly from clamped low-level capacity solves."""

    positive_angle, negative_angle = (
        (90.0, 270.0) if axis == "x" else (0.0, 180.0)
    )

    def branch(angle):
        tension = _oracle_capacity(inp, -1.0e9, angle).axial
        compression = _oracle_capacity(inp, 1.0e9, angle).axial
        return tuple(
            _oracle_capacity(
                inp,
                tension + (compression - tension) * index / INTERACTION_INTERVALS,
                angle,
            )
            for index in range(INTERACTION_INTERVALS + 1)
        )

    return branch(positive_angle) + tuple(reversed(branch(negative_angle)))


@pytest.fixture(scope="module")
def case():
    inp = _input()
    out, radial_replay, branches = _retained_output(inp)
    bundle = build_plastic_interaction_trace_families(
        inp,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context=CONTEXT,
    )
    oracle_radial_points = tuple(
        _oracle_capacity(inp, -inp["P_pl"], angle)
        for angle in _oracle_angles(inp["v_min"], inp["v_max"], inp["v_inc"])
    )
    oracle_radial = _oracle_radial(
        oracle_radial_points, inp["Mx_pl"], inp["My_pl"]
    )
    oracle_axes = {axis: _oracle_axis(inp, axis) for axis in ("x", "y")}
    return Case(
        inp,
        out,
        bundle,
        radial_replay,
        branches,
        oracle_radial_points,
        oracle_radial,
        oracle_axes,
    )


def _axes(calculation):
    return {axis.name: axis.value for axis in calculation.axes}


def _calculation(bundle, *, coverage, axis=None):
    matches = [
        calculation
        for calculation in bundle.calculations
        if calculation.coverage_id == coverage
        and (axis is None or _axes(calculation).get("axis") == axis)
    ]
    assert len(matches) == 1
    return matches[0]


def _values(calculation):
    return {step.step_id: step.result.value for step in calculation.steps}


def _use_cached_solver(monkeypatch, case):
    monkeypatch.setattr(
        trace_module, "solve_plastic", lambda *args, **kwargs: list(case.radial_replay)
    )
    monkeypatch.setattr(
        trace_module,
        "solve_interaction",
        lambda *args, **kwargs: list(case.branches[float(args[3])]),
    )


def _build(inp, out):
    return build_plastic_interaction_trace_families(
        inp,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context=CONTEXT,
    )


def test_public_validator_replays_and_rejects_resealed_title_tampering(case):
    bundle = case.bundle
    assert validate_plastic_interaction_trace_families(
        bundle,
        case.inp,
        case.out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context=CONTEXT,
    ) is bundle
    changed = dataclasses.replace(
        bundle.calculations[0], title="Resealed CT-003 title tampering"
    )
    tampered = seal_bundle(dataclasses.replace(
        bundle,
        calculations=(changed, *bundle.calculations[1:]),
        content_sha256="",
    ))
    with pytest.raises(TraceValidationError, match="authoritative input replay"):
        validate_plastic_interaction_trace_families(
            tampered,
            case.inp,
            case.out,
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
            context=CONTEXT,
        )


def _registry(case):
    blocks = section_trace_blocks(case.inp)
    plan = expected_sweep(
        case.inp["v_min"], case.inp["v_max"], case.inp["v_inc"]
    )
    radial = radial_trace_shape(
        blocks,
        CONTEXT,
        plan,
        RADIAL_FINITE_SELECTED,
        case.oracle_radial[3],
    )
    x_axis = axis_trace_shape(blocks, CONTEXT, "x", INTERACTION_FINITE)
    y_axis = axis_trace_shape(blocks, CONTEXT, "y", INTERACTION_FINITE)
    return expected_registry(radial, x_axis, y_axis)


def _rebundle(calculations):
    return create_bundle(
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        calculations=tuple(calculations),
    )


def test_independent_oracles_reconstruct_radial_and_both_axes(case):
    oracle_source = "\n".join(
        inspect.getsource(function)
        for function in (
            _oracle_angles,
            _oracle_radial,
            _oracle_capacity,
            _oracle_axis,
        )
    )
    for forbidden in (
        "build_plastic_interaction_trace_families",
        "audit_trace_registry",
        "validate_bundle",
        "solve_interaction(",
        "radial_util_result(",
    ):
        assert forbidden not in oracle_source

    radial = _calculation(case.bundle, coverage="ct-003")
    x_axis = _calculation(case.bundle, coverage="ct-004", axis="x")
    y_axis = _calculation(case.bundle, coverage="ct-004", axis="y")
    assert [item.coverage_id for item in case.bundle.calculations] == [
        "ct-003",
        "ct-004",
        "ct-004",
    ]
    assert _axes(radial)["branch"] == RADIAL_FINITE_SELECTED
    assert _axes(x_axis)["branch"] == INTERACTION_FINITE
    assert _axes(y_axis)["branch"] == INTERACTION_FINITE
    assert _axes(x_axis)["axis"] == "x"
    assert _axes(y_axis)["axis"] == "y"
    assert _axes(x_axis)["cardinality"] == str(INTERACTION_CARDINALITY)
    assert _axes(y_axis)["cardinality"] == str(INTERACTION_CARDINALITY)

    radial_values = _values(radial)
    for index, point in enumerate(case.oracle_radial_points):
        assert radial_values[f"member-{index:04d}-mx"] == pytest.approx(point.Mx)
        assert radial_values[f"member-{index:04d}-my"] == pytest.approx(point.My)
    demand, resistance, utilisation, selected = case.oracle_radial
    assert radial_values["radial-demand"] == pytest.approx(demand)
    assert radial_values["radial-resistance"] == pytest.approx(resistance)
    assert radial_values["radial-utilisation"] == pytest.approx(utilisation)
    assert radial_values["selected-member-index"] == selected
    assert radial_values["demand-resistance-verdict"] == (
        1.0 if utilisation <= 1.0 + 1.0e-9 else 0.0
    )

    for axis, calculation in (("x", x_axis), ("y", y_axis)):
        values = _values(calculation)
        assert not any(
            "utilisation" in step_id or "verdict" in step_id
            for step_id in values
        )
        oracle = case.oracle_axes[axis]
        assert len(oracle) == INTERACTION_CARDINALITY
        for index, point in enumerate(oracle):
            assert values[f"boundary-member-{index:04d}-axial"] == pytest.approx(
                -point.axial, rel=2.0e-7, abs=2.0e-7
            )
            expected_moment = point.Mx if axis == "x" else point.My
            assert values[f"boundary-member-{index:04d}-moment"] == pytest.approx(
                expected_moment, rel=2.0e-7, abs=2.0e-7
            )
        assert values["axis-interaction-result"] == INTERACTION_CARDINALITY


def test_every_used_shared_block_reaches_each_final_result(case):
    for calculation in case.bundle.calculations:
        dependencies = {
            step.step_id: tuple(item.step_id for item in step.dependencies)
            for step in calculation.steps
        }
        reached = set()
        pending = [calculation.final_step_id]
        while pending:
            step_id = pending.pop()
            if step_id in reached:
                continue
            reached.add(step_id)
            pending.extend(dependencies[step_id])
        required = {
            step.step_id
            for step in calculation.steps
            if step.step_id.startswith(("input-action-", "geometry-", "material-"))
        }
        assert required <= reached

    x_ids = {step.step_id for step in _calculation(
        case.bundle, coverage="ct-004", axis="x"
    ).steps}
    y_ids = {step.step_id for step in _calculation(
        case.bundle, coverage="ct-004", axis="y"
    ).steps}
    assert action_step_id("My_pl") not in x_ids
    assert action_step_id("Mx_pl") not in y_ids
    assert {action_step_id("P_pl"), action_step_id("Mx_pl")} <= x_ids
    assert {action_step_id("P_pl"), action_step_id("My_pl")} <= y_ids


def test_exact_sources_keep_standard_and_project_laws_distinct(case):
    expected_method = section_trace_blocks(case.inp).plastic_method_id
    for calculation in case.bundle.calculations:
        assert calculation.method_id == expected_method
        concrete_and_bars = [
            step
            for step in calculation.steps
            if step.step_id.startswith(("material-concrete-", "material-bar-"))
        ]
        tendons = [
            step
            for step in calculation.steps
            if step.step_id.startswith("material-tendon-")
        ]
        assert concrete_and_bars and tendons
        assert all(step.source.kind == SOURCE_STANDARD for step in concrete_and_bars)
        assert all(
            step.source.edition == codes.EC2_2005.label
            for step in concrete_and_bars
        )
        assert all(step.source.citation is not None for step in concrete_and_bars)
        assert all(step.source.kind == SOURCE_PROJECT for step in tendons)
        assert all(step.source.edition is None for step in tendons)
        assert all(step.source.citation is None for step in tendons)


@pytest.mark.parametrize("missing", ("radial", "x", "y"))
def test_registry_rejects_each_missing_family_independently(case, missing):
    registry = _registry(case)
    calculations = list(case.bundle.calculations)
    index = {"radial": 0, "x": 1, "y": 2}[missing]
    calculations.pop(index)
    with pytest.raises(TraceValidationError, match="missing"):
        audit_trace_registry(_rebundle(calculations), registry)


def test_registry_rejects_duplicate_family_and_cross_family_masking(case):
    registry = _registry(case)
    duplicate = dataclasses.replace(
        registry,
        families=(registry.families[0], *registry.families),
    )
    with pytest.raises(TraceValidationError, match="duplicate family"):
        audit_trace_registry(case.bundle, duplicate)

    duplicate_member = dataclasses.replace(
        registry,
        families=(
            registry.families[0],
            dataclasses.replace(
                registry.families[1],
                members=(
                    dataclasses.replace(
                        registry.families[1].members[0],
                        member_id=registry.families[0].members[0].member_id,
                    ),
                ),
            ),
            registry.families[2],
        ),
    )
    with pytest.raises(TraceValidationError, match="duplicate member"):
        audit_trace_registry(case.bundle, duplicate_member)

    unrelated = dataclasses.replace(
        case.bundle.calculations[1],
        calculation_id="plastic.unrelated.axis-interaction-y",
    )
    masked = _rebundle(
        (case.bundle.calculations[0], case.bundle.calculations[1], unrelated)
    )
    with pytest.raises(TraceValidationError, match="missing.*unexpected"):
        audit_trace_registry(masked, registry)


def test_registry_rejects_axis_method_edition_order_cardinality_and_graph(case):
    registry = _registry(case)
    radial, x_axis, y_axis = case.bundle.calculations

    wrong_axis = dataclasses.replace(x_axis, axes=y_axis.axes)
    with pytest.raises(TraceValidationError, match="axes"):
        audit_trace_registry(_rebundle((radial, wrong_axis, y_axis)), registry)

    wrong_method = dataclasses.replace(x_axis, method_id="wrong-axis-method")
    with pytest.raises(TraceValidationError, match="method"):
        audit_trace_registry(_rebundle((radial, wrong_method, y_axis)), registry)

    standard_index = next(
        index
        for index, step in enumerate(x_axis.steps)
        if step.source.kind == SOURCE_STANDARD
    )
    steps = list(x_axis.steps)
    source = steps[standard_index].source
    steps[standard_index] = dataclasses.replace(
        steps[standard_index],
        source=dataclasses.replace(source, edition="2099"),
    )
    wrong_edition = dataclasses.replace(x_axis, steps=tuple(steps))
    with pytest.raises(TraceValidationError, match="source"):
        audit_trace_registry(_rebundle((radial, wrong_edition, y_axis)), registry)

    steps = list(x_axis.steps)
    source = steps[standard_index].source
    steps[standard_index] = dataclasses.replace(
        steps[standard_index],
        source=dataclasses.replace(
            source,
            citation=dataclasses.replace(
                source.citation, document="forged standard document"
            ),
        ),
    )
    wrong_citation = dataclasses.replace(x_axis, steps=tuple(steps))
    with pytest.raises(TraceValidationError, match="source"):
        audit_trace_registry(_rebundle((radial, wrong_citation, y_axis)), registry)

    axes = tuple(
        dataclasses.replace(axis, value="65")
        if axis.name == "cardinality"
        else axis
        for axis in x_axis.axes
    )
    wrong_cardinality = dataclasses.replace(x_axis, axes=axes)
    with pytest.raises(TraceValidationError, match="axes"):
        audit_trace_registry(
            _rebundle((radial, wrong_cardinality, y_axis)), registry
        )

    steps = list(x_axis.steps)
    steps[0], steps[1] = steps[1], steps[0]
    wrong_order = dataclasses.replace(x_axis, steps=tuple(steps))
    with pytest.raises(TraceValidationError, match="step IDs"):
        audit_trace_registry(_rebundle((radial, wrong_order, y_axis)), registry)

    steps = list(x_axis.steps)
    moment_index = next(
        index
        for index, step in enumerate(steps)
        if step.step_id.endswith("-moment")
    )
    moment = steps[moment_index]
    steps[moment_index] = dataclasses.replace(
        moment,
        dependencies=tuple(
            dependency
            for dependency in moment.dependencies
            if dependency.step_id != "material-vector"
        ),
    )
    disconnected = dataclasses.replace(x_axis, steps=tuple(steps))
    with pytest.raises(TraceValidationError, match="dependency graph"):
        audit_trace_registry(_rebundle((radial, disconnected, y_axis)), registry)


def test_candidate_family_omissions_fail_closed(case, monkeypatch):
    _use_cached_solver(monkeypatch, case)
    for missing in ("radial", "x", "y"):
        out = copy.deepcopy(case.out)
        if missing == "radial":
            out["plastic"].pop("util")
        else:
            out["plastic"]["interaction"].pop(missing)
        with pytest.raises(TraceValidationError):
            _build(case.inp, out)


def test_coherent_radial_and_axis_tamper_fail_closed(case, monkeypatch):
    _use_cached_solver(monkeypatch, case)
    out = copy.deepcopy(case.out)
    out["plastic"]["mx"][0] += 12.0
    out["plastic"]["points"][0]["Mx"] += 12.0
    points = [
        dataclasses.replace(
            point,
            Mx=out["plastic"]["mx"][index],
            My=out["plastic"]["my"][index],
        )
        for index, point in enumerate(case.radial_replay)
    ]
    demand, resistance, utilisation, selected = _oracle_radial(
        points, case.inp["Mx_pl"], case.inp["My_pl"]
    )
    out["plastic"].update(
        util_demand=demand,
        util_resistance=resistance,
        util=utilisation,
        util_gov=selected,
    )
    with pytest.raises(TraceValidationError, match="resistance|member 0 mx"):
        _build(case.inp, out)

    out = copy.deepcopy(case.out)
    out["plastic"]["interaction"]["x"]["N"] = list(
        out["plastic"]["interaction"]["y"]["N"]
    )
    out["plastic"]["interaction"]["x"]["M"] = list(
        out["plastic"]["interaction"]["y"]["M"]
    )
    with pytest.raises(TraceValidationError, match="CT-004 x member"):
        _build(case.inp, out)


@pytest.mark.parametrize("selection", (False, 99, math.inf))
def test_nonfinite_boolean_and_out_of_range_selection_fail(case, monkeypatch, selection):
    _use_cached_solver(monkeypatch, case)
    out = copy.deepcopy(case.out)
    out["plastic"]["util_gov"] = selection
    with pytest.raises(TraceValidationError, match="util_gov"):
        _build(case.inp, out)


def test_total_preserving_wrong_branch_cardinality_fails(case, monkeypatch):
    monkeypatch.setattr(
        trace_module, "solve_plastic", lambda *args, **kwargs: list(case.radial_replay)
    )

    def wrong_cardinality(*args, **kwargs):
        angle = float(args[3])
        points = list(case.branches[angle])
        if angle == 90.0:
            return points[:-1]
        if angle == 270.0:
            return [points[0], *points]
        return points

    monkeypatch.setattr(trace_module, "solve_interaction", wrong_cardinality)
    with pytest.raises(TraceValidationError, match="branch cardinality"):
        _build(case.inp, case.out)


def test_content_seal_and_stale_hashes_fail_closed(case):
    with pytest.raises(TraceValidationError, match="seal"):
        validate_bundle(dataclasses.replace(case.bundle, warnings=("tamper",)))
    with pytest.raises(TraceValidationError, match="current input"):
        validate_bundle(case.bundle, expected_input_sha256="c" * 64)
    with pytest.raises(TraceValidationError, match="current result"):
        validate_bundle(case.bundle, expected_result_sha256="d" * 64)


def test_positive_finite_overload_keeps_genuine_radial_verdict(case, monkeypatch):
    _use_cached_solver(monkeypatch, case)
    inp = copy.deepcopy(case.inp)
    inp["Mx_pl"] = 450.0
    inp["My_pl"] = 300.0
    out = copy.deepcopy(case.out)
    radial = radial_util_result(
        [point.Mx for point in case.radial_replay],
        [point.My for point in case.radial_replay],
        inp["Mx_pl"],
        inp["My_pl"],
    )
    out["plastic"].update(
        applied=(inp["Mx_pl"], inp["My_pl"]),
        util=radial.utilisation,
        util_gov=radial.governing_index,
        util_demand=radial.demand,
        util_resistance=radial.resistance,
    )
    out["plastic"]["interaction"]["x"]["applied"] = (
        inp["P_pl"], inp["Mx_pl"]
    )
    out["plastic"]["interaction"]["y"]["applied"] = (
        inp["P_pl"], inp["My_pl"]
    )
    bundle = _build(inp, out)
    calculation = _calculation(bundle, coverage="ct-003")
    values = _values(calculation)
    assert values["radial-utilisation"] > 1.0
    assert values["demand-resistance-verdict"] == 0.0
    assert values["radial-utilisation-result"] == pytest.approx(
        radial.utilisation
    )
    assert calculation.steps[-1].warnings


def test_zero_radial_demand_is_finite_without_fabricated_resistance(case):
    inp = copy.deepcopy(case.inp)
    inp["Mx_pl"] = inp["My_pl"] = 0.0
    out, _radial, _branches = _retained_output(inp)
    bundle = _build(inp, out)
    radial = _calculation(bundle, coverage="ct-003")
    step_ids = {step.step_id for step in radial.steps}
    assert _axes(radial)["branch"] == RADIAL_FINITE_ZERO
    assert radial.steps[-1].result.state == RESULT_FINITE
    assert radial.steps[-1].result.value == 0.0
    assert not {
        "radial-resistance",
        "radial-utilisation",
        "selected-member-index",
        "demand-resistance-verdict",
    } & step_ids


def test_radial_selector_failure_is_explicit_and_cannot_publish_values(
    case, monkeypatch
):
    _use_cached_solver(monkeypatch, case)
    demand = math.hypot(case.inp["Mx_pl"], case.inp["My_pl"])
    monkeypatch.setattr(
        trace_module,
        "radial_util_result",
        lambda *args, **kwargs: RadialUtilResult(demand, None, math.inf, None),
    )
    out = copy.deepcopy(case.out)
    out["plastic"].update(
        util_demand=demand,
        util_resistance=None,
        util=math.inf,
        util_gov=None,
    )
    bundle = _build(case.inp, out)
    radial = _calculation(bundle, coverage="ct-003")
    step_ids = {step.step_id for step in radial.steps}
    assert _axes(radial)["branch"] == RADIAL_FAILED_SELECTOR
    assert radial.steps[-1].result.state == RESULT_FAILED
    assert not {
        "radial-resistance",
        "radial-utilisation",
        "selected-member-index",
        "demand-resistance-verdict",
    } & step_ids


def test_radial_sweep_failure_and_branch_promotion_fail_closed(case, monkeypatch):
    inp = copy.deepcopy(case.inp)
    inp["P_pl"] = 1.0e6
    out, _radial, _branches = _retained_output(inp)
    assert not out["plastic"]["converged"]
    bundle = _build(inp, out)
    radial = _calculation(bundle, coverage="ct-003")
    assert _axes(radial)["branch"] == RADIAL_FAILED_SWEEP
    assert radial.steps[-1].result.state == RESULT_FAILED
    assert "radial-resistance" not in {step.step_id for step in radial.steps}

    promoted = copy.deepcopy(out)
    promoted["plastic"]["converged"] = True
    monkeypatch.setattr(
        trace_module, "solve_interaction", lambda *args, **kwargs: list(
            case.branches[float(args[3])]
        )
    )
    with pytest.raises(TraceValidationError, match="convergence"):
        _build(inp, promoted)


def test_one_axis_failure_does_not_mask_the_other_or_allow_promotion(
    case, monkeypatch
):
    monkeypatch.setattr(
        trace_module, "solve_plastic", lambda *args, **kwargs: list(case.radial_replay)
    )

    def failed_x(*args, **kwargs):
        angle = float(args[3])
        points = list(case.branches[angle])
        if angle == 90.0:
            points[5] = dataclasses.replace(points[5], converged=False)
        return points

    monkeypatch.setattr(trace_module, "solve_interaction", failed_x)
    out = copy.deepcopy(case.out)
    out["plastic"]["interaction"]["x"]["converged"] = False
    bundle = _build(case.inp, out)
    x_axis = _calculation(bundle, coverage="ct-004", axis="x")
    y_axis = _calculation(bundle, coverage="ct-004", axis="y")
    assert _axes(x_axis)["branch"] == INTERACTION_FAILED
    assert x_axis.steps[-1].result.state == RESULT_FAILED
    assert _axes(y_axis)["branch"] == INTERACTION_FINITE
    assert y_axis.steps[-1].result.state == RESULT_FINITE
    assert not any(step.step_id.endswith("-moment") for step in x_axis.steps)

    without_arrays = copy.deepcopy(out)
    without_arrays["plastic"]["interaction"]["x"].pop("N")
    without_arrays["plastic"]["interaction"]["x"].pop("M")
    minimal = _build(case.inp, without_arrays)
    assert bundle_to_json(minimal) == bundle_to_json(bundle)

    promoted = copy.deepcopy(without_arrays)
    promoted["plastic"]["interaction"]["x"]["converged"] = True
    with pytest.raises(TraceValidationError, match="x convergence"):
        _build(case.inp, promoted)
