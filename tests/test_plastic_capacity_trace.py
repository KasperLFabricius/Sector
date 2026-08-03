"""CT-002 selected plastic-capacity trace and independent numerical oracle."""

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
    TraceCalculation,
    TraceValidationError,
    bundle_to_json,
    create_bundle,
    seal_bundle,
    validate_bundle,
)
from sector.combined import radial_util_result
from sector.materials import Prestress
from sector.plastic import (
    PlasticAccumulation,
    _accumulate,
    _material_sequence,
    _prep_section,
    plastic_capacity_at_angle,
    solve_plastic,
)
from sector.plastic_capacity_trace import (
    build_plastic_capacity_trace_family,
    validate_plastic_capacity_trace_family,
)
from sector.plastic_capacity_trace_contract import (
    BRANCH_FAILED_SELECTED,
    BRANCH_FAILED_UNSELECTED,
    BRANCH_FINITE_SELECTED,
    POINT_FIELDS,
    expected_registry,
    expected_sweep,
    point_step_id,
    trace_shape,
)
from sector.section import Section
from sector.section_trace_blocks import section_trace_blocks
from sector.trace_registry import audit_trace_registry


INPUT_SHA = "a" * 64
RESULT_SHA = "b" * 64
CONTEXT = {"case": "mixed finite", "stage": 2}


@pytest.fixture
def mixed_input():
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
    }


def _retained_point(point):
    return {
        "V": point.V,
        "Mx": point.Mx,
        "My": point.My,
        "eps_c": -point.eps_concrete,
        "eps_s": -point.eps_steel,
        "eps_s_comp": -point.eps_steel_comp,
        "eps_cable": -point.eps_cable,
        "kappa": point.curvature,
        "comp_force": point.compression_force,
        "lever": point.lever_arm,
        "dx": point.dx,
        "dy": point.dy,
        "converged": point.converged,
        "axial_requested": point.axial_requested,
        "axial_achieved": point.axial,
        "axial_residual": point.axial_residual,
        "axial_tolerance": point.axial_tolerance,
        "axial_reachable": point.axial_reachable,
        "compression_depth": point.compression_depth,
        "neutral_axis_offset": point.neutral_axis_offset,
        "strain_gradient_x": point.strain_gradient_x,
        "strain_gradient_y": point.strain_gradient_y,
        "strain_offset": point.strain_offset,
        "search_lower_depth": point.search_lower_depth,
        "search_upper_depth": point.search_upper_depth,
        "search_lower_axial": point.search_lower_axial,
        "search_upper_axial": point.search_upper_axial,
        "search_iterations": point.search_iterations,
        "concrete_force": point.concrete_force,
        "concrete_mx": point.concrete_mx,
        "concrete_my": point.concrete_my,
        "bar_force": point.bar_force,
        "bar_mx": point.bar_mx,
        "bar_my": point.bar_my,
        "tendon_force": point.tendon_force,
        "tendon_mx": point.tendon_mx,
        "tendon_my": point.tendon_my,
        "compression_mx": point.compression_mx,
        "compression_my": point.compression_my,
        "tension_force": point.tension_force,
        "tension_mx": point.tension_mx,
        "tension_my": point.tension_my,
    }


def _retained_output(inp):
    plan = expected_sweep(inp["v_min"], inp["v_max"], inp["v_inc"])
    section = inp["section"]
    points = solve_plastic(
        section,
        inp["concrete"],
        inp["steel"],
        -inp["P_pl"],
        plan.solver_min,
        plan.angles[-1],
        plan.solver_increment,
        prestress=(inp.get("prestress") if section.tendons else None),
        bar_materials=inp.get("bar_materials"),
        tendon_materials=inp.get("tendon_materials"),
    )
    mx = [point.Mx for point in points]
    my = [point.My for point in points]
    radial = radial_util_result(mx, my, inp["Mx_pl"], inp["My_pl"])
    return {
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
            "converged": all(point.converged for point in points),
            "points": [_retained_point(point) for point in points],
        }
    }


def _build(inp, out=None, *, context=CONTEXT):
    return build_plastic_capacity_trace_family(
        inp,
        _retained_output(inp) if out is None else out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context=context,
    )


def test_public_validator_replays_and_rejects_resealed_title_tampering(mixed_input):
    out = _retained_output(mixed_input)
    bundle = _build(mixed_input, out)
    assert validate_plastic_capacity_trace_family(
        bundle,
        mixed_input,
        out,
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context=CONTEXT,
    ) is bundle
    changed = dataclasses.replace(
        bundle.calculations[0], title="Resealed CT-002 title tampering"
    )
    tampered = seal_bundle(dataclasses.replace(
        bundle, calculations=(changed,), content_sha256=""
    ))
    with pytest.raises(TraceValidationError, match="authoritative input replay"):
        validate_plastic_capacity_trace_family(
            tampered,
            mixed_input,
            out,
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
            context=CONTEXT,
        )


def _independent_angles(v_min, v_max, v_inc):
    """Test-only requested-angle derivation, independent of trace/solver helpers."""

    start, stop, increment = map(float, (v_min, v_max, v_inc))
    span = max(stop, start) - start
    if span < 1.0e-9 or increment <= 0.0:
        return (start,)
    interval_count = max(1, math.ceil(span / increment))
    step = span / interval_count
    member_count = interval_count if span >= 360.0 - 1.0e-6 else interval_count + 1
    return tuple(start + index * step for index in range(member_count))


@dataclass(frozen=True)
class OraclePoint:
    angle: float
    bracketed: bool
    compression_depth: float
    neutral_axis_offset: float
    curvature: float
    strain_gradient_x: float
    strain_gradient_y: float
    strain_offset: float
    axial: float
    residual: float
    mx: float
    my: float
    eps_concrete: float
    eps_steel: float
    eps_steel_comp: float
    eps_cable: float
    lever: float
    lever_dx: float
    lever_dy: float
    accumulation: PlasticAccumulation


def _oracle_curvature(
    bar_laws,
    tendon_laws,
    s_max,
    compression_depth,
    bar_projection,
    tendon_projection,
    concrete_ultimate_strain,
):
    """Test-owned first-limit curvature from original laws and projections."""

    neutral_axis = s_max - compression_depth
    candidates = [concrete_ultimate_strain / compression_depth]
    intact = 1.0 - 1.0e-9
    for projection, material in zip(bar_projection, bar_laws):
        if projection < neutral_axis:
            candidates.append(
                intact * material.eut / (neutral_axis - float(projection))
            )
        if material.active_in_compression and projection > neutral_axis:
            candidates.append(
                intact * material.eut / (float(projection) - neutral_axis)
            )
    for projection, material in zip(tendon_projection, tendon_laws):
        available_tension_strain = material.rupture_strain - material.IS
        if projection < neutral_axis and available_tension_strain > 0.0:
            candidates.append(
                intact
                * available_tension_strain
                / (neutral_axis - float(projection))
            )
    return min(candidates)


def _oracle_angle(inp, angle, requested_axial):
    """Bracket and solve one axial root without any production search output."""

    section = inp["section"]
    concrete = inp["concrete"]
    steel = inp["steel"]
    prestress = inp.get("prestress") if section.tendons else None
    prep = _prep_section(section, bool(section.tendons))
    bar_laws = _material_sequence(
        steel, inp.get("bar_materials"), len(prep.ba), "bar"
    )
    tendon_laws = _material_sequence(
        prestress,
        inp.get("tendon_materials"),
        len(prep.ta),
        "tendon",
    ) if section.tendons else ()

    radians = math.radians(angle)
    direction_x, direction_y = math.cos(radians), math.sin(radians)
    bar_projection = prep.bx * direction_x + prep.by * direction_y
    tendon_projection = prep.tx * direction_x + prep.ty * direction_y
    bar_data = (prep.bx, prep.by, prep.ba, bar_projection)
    tendon_data = (prep.tx, prep.ty, prep.ta, tendon_projection)
    concrete_projection = (
        prep.verts[:, 0] * direction_x + prep.verts[:, 1] * direction_y
    )
    s_max = float(concrete_projection.max())
    s_min = float(concrete_projection.min())
    full_depth = s_max - s_min
    band_memo = {}

    def state(depth):
        curvature = _oracle_curvature(
            bar_laws,
            tendon_laws,
            s_max,
            depth,
            bar_projection,
            tendon_projection,
            concrete.eps_cu2,
        )
        accumulation = _accumulate(
            concrete,
            bar_laws,
            tendon_laws,
            direction_x,
            direction_y,
            s_max,
            depth,
            curvature,
            80,
            prep.rings,
            bar_data,
            tendon_data,
            prep.ring_xy,
            prep.ring_starts,
            prep.buf_a,
            prep.buf_b,
            band_memo,
        )
        return curvature, accumulation

    lower_depth = full_depth * 1.0e-9
    lower_curvature, lower_state = state(lower_depth)
    upper_depth = full_depth
    upper_curvature, upper_state = state(upper_depth)
    attempts = 0
    while upper_state.axial < requested_axial and attempts < 96:
        upper_depth *= 1.75
        upper_curvature, upper_state = state(upper_depth)
        attempts += 1

    bracketed = lower_state.axial <= requested_axial <= upper_state.axial
    if requested_axial <= lower_state.axial:
        depth, curvature, accumulation = (
            lower_depth,
            lower_curvature,
            lower_state,
        )
    elif requested_axial >= upper_state.axial:
        depth, curvature, accumulation = (
            upper_depth,
            upper_curvature,
            upper_state,
        )
    else:
        lo_depth, lo_axial = lower_depth, lower_state.axial
        hi_depth, hi_axial = upper_depth, upper_state.axial
        for _ in range(180):
            fraction = (requested_axial - lo_axial) / (hi_axial - lo_axial)
            fraction = min(0.85, max(0.15, fraction))
            depth = lo_depth + fraction * (hi_depth - lo_depth)
            curvature, accumulation = state(depth)
            if accumulation.axial < requested_axial:
                lo_depth, lo_axial = depth, accumulation.axial
            else:
                hi_depth, hi_axial = depth, accumulation.axial
            if (
                abs(accumulation.axial - requested_axial)
                <= 2.0e-10 * max(1.0, abs(requested_axial))
                and hi_depth - lo_depth <= 2.0e-10 * full_depth
            ):
                break
        depth = 0.5 * (lo_depth + hi_depth)
        curvature, accumulation = state(depth)

    neutral_axis = s_max - depth
    if accumulation.compression_force and accumulation.tension_force:
        compression_x = (
            accumulation.compression_my / accumulation.compression_force
        )
        compression_y = (
            accumulation.compression_mx / accumulation.compression_force
        )
        tension_x = accumulation.tension_my / accumulation.tension_force
        tension_y = accumulation.tension_mx / accumulation.tension_force
        lever_dx = compression_x - tension_x
        lever_dy = compression_y - tension_y
        lever = math.hypot(lever_dx, lever_dy)
    else:
        lever = lever_dx = lever_dy = 0.0
    return OraclePoint(
        angle=angle,
        bracketed=bracketed,
        compression_depth=depth,
        neutral_axis_offset=neutral_axis,
        curvature=curvature,
        strain_gradient_x=curvature * direction_x,
        strain_gradient_y=curvature * direction_y,
        strain_offset=-curvature * neutral_axis,
        axial=accumulation.axial,
        residual=accumulation.axial - requested_axial,
        mx=accumulation.mx,
        my=accumulation.my,
        eps_concrete=curvature * depth * 100.0,
        eps_steel=accumulation.min_bar_strain * 100.0,
        eps_steel_comp=accumulation.max_bar_strain * 100.0,
        eps_cable=accumulation.min_tendon_strain * 100.0,
        lever=lever,
        lever_dx=lever_dx,
        lever_dy=lever_dy,
        accumulation=accumulation,
    )


def _oracle_sweep(inp):
    angles = _independent_angles(inp["v_min"], inp["v_max"], inp["v_inc"])
    return tuple(_oracle_angle(inp, angle, -inp["P_pl"]) for angle in angles)


def _independent_radial(points, applied_x, applied_y):
    demand = math.hypot(applied_x, applied_y)
    if demand < 1.0e-9:
        return demand, None, 0.0, None
    ray_x, ray_y = applied_x / demand, applied_y / demand
    hits = []
    for index, first in enumerate(points):
        second = points[(index + 1) % len(points)]
        edge_x, edge_y = second.mx - first.mx, second.my - first.my
        denominator = ray_x * edge_y - ray_y * edge_x
        if abs(denominator) <= 1.0e-12:
            continue
        distance = (edge_y * first.mx - edge_x * first.my) / denominator
        edge_fraction = (ray_y * first.mx - ray_x * first.my) / denominator
        if -1.0e-9 <= edge_fraction <= 1.0 + 1.0e-9 and distance > 1.0e-9:
            hits.append((distance, index))
    if not hits:
        return demand, None, math.inf, None
    resistance, edge = min(hits)
    crossing_x, crossing_y = ray_x * resistance, ray_y * resistance
    next_index = (edge + 1) % len(points)
    first_distance = math.hypot(
        points[edge].mx - crossing_x, points[edge].my - crossing_y
    )
    second_distance = math.hypot(
        points[next_index].mx - crossing_x,
        points[next_index].my - crossing_y,
    )
    selected = edge if first_distance <= second_distance else next_index
    return demand, resistance, demand / resistance, selected


def _step_values(bundle):
    return {
        step.step_id: step.result.value
        for step in bundle.calculations[0].steps
    }


def test_independent_oracle_uses_no_candidate_search_or_trace_path():
    source = "\n".join(
        inspect.getsource(function)
        for function in (
            _independent_angles,
            _oracle_curvature,
            _oracle_angle,
            _oracle_sweep,
            _oracle_endpoint_loads,
            _independent_radial,
        )
    )
    for forbidden in (
        "build_plastic_capacity_trace_family",
        "solve_plastic",
        "plastic_capacity_at_angle",
        "_governing_curvature",
        "_accumulate_at_depth",
        "radial_util_result",
        "expected_sweep",
        "_point_expected",
        "candidate_point",
        "replay",
        "selected_index",
    ):
        assert forbidden not in source


def test_independent_oracle_matches_complete_mixed_sweep_and_trace(mixed_input):
    oracle = _oracle_sweep(mixed_input)
    assert all(point.bracketed for point in oracle)
    out = _retained_output(mixed_input)
    bundle = _build(mixed_input, out)
    calculation = bundle.calculations[0]
    assert calculation.steps[-1].result.state == RESULT_FINITE
    assert dict((axis.name, axis.value) for axis in calculation.axes)["branch"] == (
        BRANCH_FINITE_SELECTED
    )
    values = _step_values(bundle)

    retained = out["plastic"]["points"]
    for index, (expected, actual) in enumerate(zip(oracle, retained)):
        comparisons = {
            "Mx": expected.mx,
            "My": expected.my,
            "axial_achieved": expected.axial,
            "axial_residual": expected.residual,
            "compression_depth": expected.compression_depth,
            "neutral_axis_offset": expected.neutral_axis_offset,
            "kappa": expected.curvature,
            "strain_gradient_x": expected.strain_gradient_x,
            "strain_gradient_y": expected.strain_gradient_y,
            "strain_offset": expected.strain_offset,
            "eps_c": -expected.eps_concrete,
            "eps_s": -expected.eps_steel,
            "eps_s_comp": -expected.eps_steel_comp,
            "eps_cable": -expected.eps_cable,
            "concrete_force": expected.accumulation.concrete_force,
            "concrete_mx": expected.accumulation.concrete_mx,
            "concrete_my": expected.accumulation.concrete_my,
            "bar_force": expected.accumulation.bar_force,
            "bar_mx": expected.accumulation.bar_mx,
            "bar_my": expected.accumulation.bar_my,
            "tendon_force": expected.accumulation.tendon_force,
            "tendon_mx": expected.accumulation.tendon_mx,
            "tendon_my": expected.accumulation.tendon_my,
            "comp_force": expected.accumulation.compression_force,
            "compression_mx": expected.accumulation.compression_mx,
            "compression_my": expected.accumulation.compression_my,
            "tension_force": expected.accumulation.tension_force,
            "tension_mx": expected.accumulation.tension_mx,
            "tension_my": expected.accumulation.tension_my,
            "lever": expected.lever,
            "dx": expected.lever_dx,
            "dy": expected.lever_dy,
        }
        for field, oracle_value in comparisons.items():
            assert actual[field] == pytest.approx(oracle_value, rel=3.0e-7, abs=3.0e-7)
            assert values[point_step_id(index, field)] == pytest.approx(
                oracle_value, rel=3.0e-7, abs=3.0e-7
            )
        assert actual["axial_reachable"] is True
        assert actual["converged"] is True
        assert values[point_step_id(index, "axial_reachable")] == 1.0
        assert values[point_step_id(index, "converged")] == 1.0

    demand, resistance, utilisation, selected = _independent_radial(
        oracle, mixed_input["Mx_pl"], mixed_input["My_pl"]
    )
    assert out["plastic"]["util_gov"] == selected
    assert values["selected-member-index"] == selected
    assert values["radial-demand"] == pytest.approx(demand)
    assert values["radial-resistance"] == pytest.approx(resistance)
    assert values["radial-utilisation"] == pytest.approx(utilisation)
    assert values["demand-resistance-verdict"] == (1.0 if utilisation <= 1.0 else 0.0)


def _oracle_endpoint_loads(inp, angle):
    probe = copy.deepcopy(inp)
    probe["P_pl"] = 0.0
    section = probe["section"]
    concrete = probe["concrete"]
    prep = _prep_section(section, bool(section.tendons))
    bars = _material_sequence(probe["steel"], None, len(prep.ba), "bar")
    tendons = _material_sequence(
        probe["prestress"], None, len(prep.ta), "tendon"
    )
    radians = math.radians(angle)
    dx, dy = math.cos(radians), math.sin(radians)
    bar_projection = prep.bx * dx + prep.by * dy
    tendon_projection = prep.tx * dx + prep.ty * dy
    projection = prep.verts[:, 0] * dx + prep.verts[:, 1] * dy
    s_max, s_min = float(projection.max()), float(projection.min())
    full_depth = s_max - s_min
    bar_data = (prep.bx, prep.by, prep.ba, bar_projection)
    tendon_data = (prep.tx, prep.ty, prep.ta, tendon_projection)

    def axial(depth):
        curvature = _oracle_curvature(
            bars,
            tendons,
            s_max,
            depth,
            bar_projection,
            tendon_projection,
            concrete.eps_cu2,
        )
        return _accumulate(
            concrete,
            bars,
            tendons,
            dx,
            dy,
            s_max,
            depth,
            curvature,
            80,
            prep.rings,
            bar_data,
            tendon_data,
            prep.ring_xy,
            prep.ring_starts,
            prep.buf_a,
            prep.buf_b,
            {},
        ).axial

    lower = axial(full_depth * 1.0e-9)
    upper = axial(full_depth)
    return lower, 0.5 * (lower + upper), upper


@pytest.mark.parametrize("position", (0, 1, 2), ids=("lower", "interior", "upper"))
def test_exact_endpoint_and_interior_roots_match_independent_oracle(
    mixed_input, position
):
    requested = _oracle_endpoint_loads(mixed_input, 90.0)[position]
    oracle = _oracle_angle(mixed_input, 90.0, requested)
    retained = plastic_capacity_at_angle(
        mixed_input["section"],
        mixed_input["concrete"],
        mixed_input["steel"],
        requested,
        90.0,
        prestress=mixed_input["prestress"],
    )
    assert oracle.bracketed
    assert retained.axial_reachable
    assert retained.converged
    assert retained.axial == pytest.approx(oracle.axial, rel=3.0e-7, abs=3.0e-7)
    assert retained.compression_depth == pytest.approx(
        oracle.compression_depth, rel=3.0e-7, abs=3.0e-7
    )


def test_near_boundary_unbracketed_sweep_cannot_enter_finite_branch(mixed_input):
    lower_bounds = [
        _oracle_endpoint_loads(mixed_input, angle)[0]
        for angle in _independent_angles(
            mixed_input["v_min"], mixed_input["v_max"], mixed_input["v_inc"]
        )
    ]
    requested = min(lower_bounds)
    requested -= 0.5e-6 * max(1.0, abs(requested))
    hostile = copy.deepcopy(mixed_input)
    hostile["P_pl"] = -requested
    out = _retained_output(hostile)
    assert not out["plastic"]["converged"]
    bundle = _build(hostile, out)
    assert bundle.calculations[0].steps[-1].result.state == RESULT_FAILED


@pytest.mark.parametrize("zero_demand", (False, True), ids=("selected", "unselected"))
def test_failure_trace_is_minimal_and_failed_arrays_are_inert(
    mixed_input, zero_demand
):
    inp = copy.deepcopy(mixed_input)
    inp["P_pl"] = 1.0e6
    if zero_demand:
        inp["Mx_pl"] = inp["My_pl"] = 0.0
    out = _retained_output(inp)
    assert not out["plastic"]["converged"]
    expected_branch = (
        BRANCH_FAILED_UNSELECTED
        if out["plastic"]["util_gov"] is None
        else BRANCH_FAILED_SELECTED
    )
    original = _build(inp, out)
    axes = dict((axis.name, axis.value) for axis in original.calculations[0].axes)
    assert axes["branch"] == expected_branch
    assert original.calculations[0].steps[-1].result.state == RESULT_FAILED

    mutated = copy.deepcopy(out)
    plastic = mutated["plastic"]
    plastic["mx"] = list(reversed(plastic["mx"]))
    plastic.pop("my")
    plastic.pop("util")
    plastic.pop("util_demand")
    plastic.pop("util_resistance")
    plastic.pop("applied")
    plastic.pop("closed")
    plastic.pop("check_util")
    for index, point in enumerate(plastic["points"]):
        for field in tuple(point):
            if field not in {"V", "converged"}:
                if index % 2:
                    point.pop(field)
                else:
                    point[field] = 9.87654321e42
    rebuilt = _build(inp, mutated)
    assert bundle_to_json(rebuilt) == bundle_to_json(original)
    step_ids = {step.step_id for step in rebuilt.calculations[0].steps}
    assert not any(
        fragment in step_id
        for step_id in step_ids
        for fragment in (
            "compression-depth",
            "concrete-force",
            "radial-resistance",
            "radial-utilisation",
            "demand-resistance-verdict",
        )
    )


@pytest.mark.parametrize(
    "value",
    [pytest.param(False, id="boolean"), pytest.param(1.5, id="fractional"), pytest.param(99, id="range")],
)
def test_selection_must_be_exact_non_boolean_and_in_range(mixed_input, value):
    out = _retained_output(mixed_input)
    out["plastic"]["util_gov"] = value
    with pytest.raises(TraceValidationError, match="util_gov"):
        _build(mixed_input, out)


def test_missing_and_contradictory_selection_fail_closed(mixed_input):
    out = _retained_output(mixed_input)
    out["plastic"].pop("util_gov")
    with pytest.raises(TraceValidationError, match="required"):
        _build(mixed_input, out)

    out = _retained_output(mixed_input)
    out["plastic"]["util_gov"] = (
        out["plastic"]["util_gov"] + 1
    ) % len(out["plastic"]["points"])
    with pytest.raises(TraceValidationError, match="contradicts"):
        _build(mixed_input, out)


def test_coherent_sweep_deletion_and_reordering_fail_closed(mixed_input):
    for mutation in ("delete", "reorder"):
        out = _retained_output(mixed_input)
        plastic = out["plastic"]
        if mutation == "delete":
            plastic["points"].pop(1)
            plastic["mx"].pop(1)
            plastic["my"].pop(1)
        else:
            order = [1, 0, 2, 3]
            plastic["points"] = [plastic["points"][index] for index in order]
            plastic["mx"] = [plastic["mx"][index] for index in order]
            plastic["my"] = [plastic["my"][index] for index in order]
        radial = radial_util_result(
            plastic["mx"], plastic["my"], mixed_input["Mx_pl"], mixed_input["My_pl"]
        )
        plastic.update(
            util=radial.utilisation,
            util_gov=radial.governing_index,
            util_demand=radial.demand,
            util_resistance=radial.resistance,
        )
        with pytest.raises(TraceValidationError, match="cardinality|angle"):
            _build(mixed_input, out)


def test_total_preserving_material_swaps_fail_reconstruction(mixed_input):
    out = _retained_output(mixed_input)
    point = out["plastic"]["points"][2]
    for concrete, bar in (
        ("concrete_force", "bar_force"),
        ("concrete_mx", "bar_mx"),
        ("concrete_my", "bar_my"),
    ):
        point[concrete] += 12.5
        point[bar] -= 12.5
    with pytest.raises(TraceValidationError, match="authoritative|reconstructed"):
        _build(mixed_input, out)


def test_radial_and_point_array_tamper_fail_closed(mixed_input):
    out = _retained_output(mixed_input)
    out["plastic"]["util_resistance"] *= 1.1
    out["plastic"]["util"] = (
        out["plastic"]["util_demand"] / out["plastic"]["util_resistance"]
    )
    with pytest.raises(TraceValidationError, match="resistance|util"):
        _build(mixed_input, out)

    out = _retained_output(mixed_input)
    out["plastic"]["mx"][0] += 1.0
    out["plastic"]["points"][0]["Mx"] += 1.0
    with pytest.raises(TraceValidationError, match="Mx"):
        _build(mixed_input, out)


def test_registry_is_independent_and_rejects_metadata_graph_and_masking(mixed_input):
    out = _retained_output(mixed_input)
    bundle = _build(mixed_input, out)
    selected = out["plastic"]["util_gov"]
    shape = trace_shape(
        section_trace_blocks(mixed_input),
        CONTEXT,
        expected_sweep(
            mixed_input["v_min"], mixed_input["v_max"], mixed_input["v_inc"]
        ),
        BRANCH_FINITE_SELECTED,
        selected,
    )
    registry = expected_registry(shape)
    calculation = bundle.calculations[0]

    material_positions = []
    material_sources = []
    for index, step in enumerate(calculation.steps):
        if (
            step.step_id.startswith("material-")
            and step.source.kind != SOURCE_PROJECT
            and step.source not in material_sources
        ):
            material_positions.append(index)
            material_sources.append(step.source)
    first, second = material_positions[:2]
    steps = list(calculation.steps)
    steps[first] = dataclasses.replace(steps[first], source=steps[second].source)
    steps[second] = dataclasses.replace(steps[second], source=steps[first].source)
    swapped = create_bundle(
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        calculations=(dataclasses.replace(calculation, steps=tuple(steps)),),
    )
    with pytest.raises(TraceValidationError, match="source"):
        audit_trace_registry(swapped, registry)

    final_index = len(calculation.steps) - 1
    steps = list(calculation.steps)
    reordered_dependencies = (
        *steps[final_index].dependencies[:-2],
        steps[final_index].dependencies[-1],
        steps[final_index].dependencies[-2],
    )
    steps[final_index] = dataclasses.replace(
        steps[final_index], dependencies=reordered_dependencies
    )
    graph_drift = create_bundle(
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        calculations=(dataclasses.replace(calculation, steps=tuple(steps)),),
    )
    with pytest.raises(TraceValidationError, match="dependency graph"):
        audit_trace_registry(graph_drift, registry)

    unrelated = dataclasses.replace(
        calculation,
        calculation_id="plastic.unrelated.selected-capacity",
    )
    masked = create_bundle(
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        calculations=(unrelated,),
    )
    with pytest.raises(TraceValidationError, match="missing.*unexpected"):
        audit_trace_registry(masked, registry)


def test_content_seal_stale_hash_and_custom_provenance_close(mixed_input):
    bundle = _build(mixed_input)
    with pytest.raises(TraceValidationError, match="seal"):
        validate_bundle(dataclasses.replace(bundle, warnings=("tamper",)))
    with pytest.raises(TraceValidationError, match="current input"):
        validate_bundle(bundle, expected_input_sha256="c" * 64)

    custom = copy.deepcopy(mixed_input)
    custom["concrete"] = dataclasses.replace(
        custom["concrete"], alpha_cc=0.93
    )
    custom_bundle = _build(custom)
    concrete_steps = [
        step
        for step in custom_bundle.calculations[0].steps
        if step.step_id.startswith("material-concrete-")
    ]
    assert concrete_steps
    assert all(step.source.kind == SOURCE_PROJECT for step in concrete_steps)
    assert all(step.source.citation is None for step in concrete_steps)
