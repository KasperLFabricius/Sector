import copy
import dataclasses
import math

import pytest

from sector import codes, combined, material_presets, plastic_capacity_trace
from sector.calculation_trace import (
    RESULT_FAILED,
    RESULT_FINITE,
    ROLE_METHOD_VALUE,
    ROLE_USER_INPUT,
    SOURCE_INPUT,
    SOURCE_PROJECT,
    SOURCE_STANDARD,
    TraceResult,
    TraceValidationError,
    create_bundle,
    validate_bundle,
)
from sector.plastic import solve_plastic
from sector.plastic_capacity_trace import build_plastic_capacity_trace_family
from sector.plastic_capacity_trace_spec import (
    BRANCH_FAILED_SELECTED,
    BRANCH_FAILED_UNSELECTED,
    BRANCH_FINITE_SELECTED,
)
from sector.section import Section
from sector.trace_registry import audit_trace_registry


def _oracle(mx, my, ax, ay):
    """Independent ray/polygon reconstruction; no production selector calls."""

    demand = math.hypot(ax, ay)
    ux, uy = ax / demand, ay / demand
    hits = []
    for index, (px, py) in enumerate(zip(mx, my)):
        nxt = (index + 1) % len(mx)
        ex, ey = mx[nxt] - px, my[nxt] - py
        determinant = ux * ey - uy * ex
        if abs(determinant) <= 1.0e-12:
            continue
        ray = (ey * px - ex * py) / determinant
        edge = (uy * px - ux * py) / determinant
        if -1.0e-9 <= edge <= 1.0 + 1.0e-9 and ray > 1.0e-9:
            hits.append((ray, index))
    resistance, edge = min(hits)
    nxt = (edge + 1) % len(mx)
    crossing = (ux * resistance, uy * resistance)
    distances = (
        math.hypot(mx[edge] - crossing[0], my[edge] - crossing[1]),
        math.hypot(mx[nxt] - crossing[0], my[nxt] - crossing[1]),
    )
    selected = edge if distances[0] <= distances[1] else nxt
    return demand / resistance, selected, resistance


def _point(point):
    return {
        "V": point.V,
        "Mx": point.Mx,
        "My": point.My,
        "na_x": point.na_x_intercept,
        "na_y": point.na_y_intercept,
        "eps_c": -point.eps_concrete,
        "eps_s": -point.eps_steel,
        "eps_s_comp": -point.eps_steel_comp,
        "eps_cable": -point.eps_cable,
        "kappa": point.curvature,
        "axial": point.axial,
        "axial_action": -point.axial,
        "compression_depth": point.compression_depth,
        "neutral_axis_depth": point.neutral_axis_depth,
        "axial_residual": point.axial_residual,
        "axial_tolerance": point.axial_tolerance,
        "concrete_force": point.concrete_force,
        "concrete_mx": point.concrete_mx,
        "concrete_my": point.concrete_my,
        "steel_force": point.steel_force,
        "steel_mx": point.steel_mx,
        "steel_my": point.steel_my,
        "tendon_force": point.tendon_force,
        "tendon_mx": point.tendon_mx,
        "tendon_my": point.tendon_my,
        "comp_force": point.compression_force,
        "comp_mx": point.compression_mx,
        "comp_my": point.compression_my,
        "tension_force": point.tension_force,
        "tension_mx": point.tension_mx,
        "tension_my": point.tension_my,
        "lever": point.lever_arm,
        "dx": point.dx,
        "dy": point.dy,
        "converged": point.converged,
    }


def _case(p_pl):
    tendon_values = material_presets.PRESTRESS_PRESETS[codes.EC2_2005.label]
    tendon = material_presets.build_prestress(
        tendon_values["curve"],
        **{key: value for key, value in tendon_values.items() if key != "curve"},
    )
    section = Section.from_polygon(
        [(0.0, 0.0), (0.4, 0.0), (0.4, 0.7), (0.0, 0.7)],
        [
            (0.06, 0.06, 700.0),
            (0.34, 0.06, 700.0),
            (0.34, 0.64, 700.0),
            (0.06, 0.64, 700.0),
        ],
        tendons_xy_area_mm2=[(0.2, 0.1, 500.0)],
    )
    concrete = codes.EC2_2005.concrete(35.0)
    steel = codes.EC2_2005.steel(500.0)
    inp = {
        "section": section,
        "concrete": concrete,
        "steel": steel,
        "prestress": tendon,
        "concrete_preset": codes.EC2_2005.label,
        "mild_preset": codes.EC2_2005.label,
        "prestress_preset": codes.EC2_2005.label,
        "P_pl": p_pl,
        "Mx_pl": 115.0,
        "My_pl": 65.0,
    }
    points = solve_plastic(
        section,
        concrete,
        steel,
        -inp["P_pl"],
        0.0,
        315.0,
        45.0,
        prestress=tendon,
    )
    mx = [item.Mx for item in points]
    my = [item.My for item in points]
    radial = combined.radial_util_result(
        mx,
        my,
        inp["Mx_pl"],
        inp["My_pl"],
    )
    out = {
        "plastic": {
            "mx": mx,
            "my": my,
            "util": radial.utilisation,
            "util_gov": radial.governing_index,
            "closed": True,
            "check_util": True,
            "applied": (inp["Mx_pl"], inp["My_pl"]),
            "demand": radial.demand,
            "resistance": radial.resistance,
            "converged": all(item.converged for item in points),
            "points": [_point(item) for item in points],
        }
    }
    return inp, out


@pytest.fixture(scope="module")
def finite_case():
    return _case(40.0)


@pytest.fixture(scope="module")
def failed_unselected_case():
    return _case(100000.0)


def _bundle(family, input_hash="a" * 64, result_hash="b" * 64):
    return create_bundle(
        input_sha256=input_hash,
        result_sha256=result_hash,
        calculations=(family.calculation,),
    )


def _steps(family):
    return {step.step_id: step for step in family.calculation.steps}


def _closure(steps, root):
    reached = set()
    pending = [root]
    while pending:
        step_id = pending.pop()
        if step_id in reached:
            continue
        reached.add(step_id)
        pending.extend(item.step_id for item in steps[step_id].dependencies)
    return reached


def _axis_map(family):
    return {axis.name: axis.value for axis in family.calculation.axes}


def test_finite_branch_has_independent_numerical_and_exact_registry_closure(
    finite_case,
):
    inp, out = finite_case
    util, selected, resistance = _oracle(
        out["plastic"]["mx"],
        out["plastic"]["my"],
        inp["Mx_pl"],
        inp["My_pl"],
    )
    assert util == pytest.approx(0.3231334179)
    assert selected == 1
    assert resistance == pytest.approx(408.8046633)

    family = build_plastic_capacity_trace_family(
        inp,
        out,
        context={"case": "A"},
    )
    steps = _steps(family)
    final = steps[family.calculation.final_step_id]
    member = family.registry.families[0].members[0]
    axes = _axis_map(family)

    assert final.result == TraceResult(RESULT_FINITE, pytest.approx(util))
    assert member.result_states == frozenset({RESULT_FINITE})
    assert axes["result_branch"] == BRANCH_FINITE_SELECTED
    assert axes["retained_cardinality"] == "8"
    assert axes["selected_member"] == str(selected)
    assert steps["retained-radial-demand"].result.value == pytest.approx(
        math.hypot(inp["Mx_pl"], inp["My_pl"])
    )
    assert steps["retained-radial-resistance"].result.value == pytest.approx(
        resistance
    )
    assert steps["retained-radial-utilisation"].result.value == pytest.approx(util)
    assert steps["capacity-verdict"].result.value == 1.0

    point = out["plastic"]["points"][selected]
    assert point["axial"] == pytest.approx(
        point["concrete_force"] + point["steel_force"] + point["tendon_force"]
    )
    assert point["Mx"] == pytest.approx(
        point["concrete_mx"] + point["steel_mx"] + point["tendon_mx"]
    )
    assert point["My"] == pytest.approx(
        point["concrete_my"] + point["steel_my"] + point["tendon_my"]
    )
    assert point["axial_residual"] == pytest.approx(
        point["axial"] - (-inp["P_pl"])
    )
    assert point["axial_tolerance"] == pytest.approx(40.0e-6)
    assert point["lever"] == pytest.approx(math.hypot(point["dx"], point["dy"]))

    standard_editions = {
        source.edition
        for source in member.sources
        if source.kind == SOURCE_STANDARD
    }
    assert standard_editions == {codes.EC2_2005.label}
    assert audit_trace_registry(_bundle(family), family.registry)


def test_live_analysis_retains_the_solver_owned_ct002_payload():
    from app.sector_app import _run_single_analysis

    section = Section.from_polygon(
        [(0.0, 0.0), (0.4, 0.0), (0.4, 0.7), (0.0, 0.7)],
        [
            (0.06, 0.06, 700.0),
            (0.34, 0.06, 700.0),
            (0.34, 0.64, 700.0),
            (0.06, 0.64, 700.0),
        ],
    )
    inp = {
        "section": section,
        "concrete": codes.EC2_2005.concrete(35.0),
        "steel": codes.EC2_2005.steel(500.0),
        "concrete_preset": codes.EC2_2005.label,
        "mild_preset": codes.EC2_2005.label,
        "mode": "Plastic",
        "geometry_error": None,
        "void_error": None,
        "steel_error": None,
        "material_error": None,
        "v_min": 0.0,
        "v_max": 360.0,
        "v_inc": 90.0,
        "prestress": None,
        "tendons": [],
        "P_pl": 40.0,
        "Mx_pl": 115.0,
        "My_pl": 65.0,
        "check_util": True,
        "interaction": False,
        "minimum_reinforcement_on": False,
        "shear_on": False,
        "torsion_on": False,
        "transverse_detailing_on": False,
    }
    out = _run_single_analysis(inp)
    retained = out["plastic"]
    radial = combined.radial_util_result(
        retained["mx"],
        retained["my"],
        inp["Mx_pl"],
        inp["My_pl"],
    )

    assert retained["demand"] == radial.demand
    assert retained["resistance"] == radial.resistance
    assert retained["util"] == radial.utilisation
    assert retained["util_gov"] == radial.governing_index
    assert set(retained["points"][0]) == set(_point(solve_plastic(
        section,
        inp["concrete"],
        inp["steel"],
        -inp["P_pl"],
        0.0,
        0.0,
        90.0,
    )[0]))
    family = build_plastic_capacity_trace_family(inp, out, context={"case": "live"})
    assert _steps(family)[family.calculation.final_step_id].result.state == RESULT_FINITE


def test_canonical_role_and_provenance_constants_close_every_leaf(finite_case):
    inp, out = finite_case
    family = build_plastic_capacity_trace_family(inp, out, context={})
    steps = _steps(family)
    closure = _closure(steps, family.calculation.final_step_id)
    leaves = {
        step.step_id
        for step in family.calculation.steps
        if step.quantity_role in {ROLE_USER_INPUT, ROLE_METHOD_VALUE}
    }

    assert ROLE_USER_INPUT == "user_input"
    assert ROLE_METHOD_VALUE == "method_value"
    assert leaves
    assert leaves <= closure
    assert {
        step.source.kind
        for step in family.calculation.steps
        if step.quantity_role == ROLE_USER_INPUT
    } == {SOURCE_INPUT}
    assert {
        step.source.kind
        for step in family.calculation.steps
        if step.quantity_role == ROLE_METHOD_VALUE
    } <= {SOURCE_STANDARD, SOURCE_PROJECT}

    block_controls = {
        "geometry-concrete-block": "geometry-ring-000-point-000-x",
        "section-input-closure": "input-action-p-pl",
        "material-concrete-block": "material-concrete-fck",
        "material-bar-000-block": "material-bar-000-fytk",
        "material-tendon-000-block": "material-tendon-000-is",
    }
    for intermediate, leaf in block_controls.items():
        assert leaf in _closure(steps, intermediate)
        assert intermediate in closure


@pytest.mark.parametrize(
    ("block", "step_id", "dependency_id"),
    [
        ("geometry", "member-000-concrete-force", "geometry-concrete-block"),
        ("action", "member-000-concrete-force", "input-action-p-pl"),
        ("concrete", "member-000-concrete-force", "material-concrete-block"),
        ("bar", "member-000-steel-force", "material-bars-block"),
        ("tendon", "member-000-tendon-force", "material-tendons-block"),
    ],
)
def test_each_used_block_disconnect_mutation_breaks_the_exact_graph(
    finite_case,
    block,
    step_id,
    dependency_id,
):
    inp, out = finite_case
    family = build_plastic_capacity_trace_family(inp, out, context={})
    original_steps = _steps(family)
    assert dependency_id in {
        item.step_id for item in original_steps[step_id].dependencies
    }, block

    changed = []
    for step in family.calculation.steps:
        if step.step_id == step_id:
            step = dataclasses.replace(
                step,
                dependencies=tuple(
                    item
                    for item in step.dependencies
                    if item.step_id != dependency_id
                ),
            )
        changed.append(step)
    calculation = dataclasses.replace(family.calculation, steps=tuple(changed))
    candidate = create_bundle(
        input_sha256="a" * 64,
        result_sha256="b" * 64,
        calculations=(calculation,),
    )
    mutated_steps = {step.step_id: step for step in calculation.steps}
    assert dependency_id not in _closure(mutated_steps, step_id), block
    with pytest.raises(TraceValidationError, match="dependency graph"):
        audit_trace_registry(candidate, family.registry)


def test_genuine_no_selection_nonconvergence_emits_explicit_failed_trace(
    failed_unselected_case,
):
    inp, out = failed_unselected_case
    assert out["plastic"]["converged"] is False
    assert out["plastic"]["util_gov"] is None
    assert out["plastic"]["resistance"] is None
    assert out["plastic"]["util"] == math.inf

    family = build_plastic_capacity_trace_family(
        inp,
        out,
        context={"case": "unreachable"},
    )
    steps = _steps(family)
    final = steps[family.calculation.final_step_id]
    axes = _axis_map(family)
    member = family.registry.families[0].members[0]

    assert final.result.state == RESULT_FAILED
    assert member.result_states == frozenset({RESULT_FAILED})
    assert axes["result_branch"] == BRANCH_FAILED_UNSELECTED
    assert axes["selected_member"] == "none"
    assert axes["retained_cardinality"] == "8"
    assert "selected-member-index" not in steps
    assert "retained-radial-resistance" not in steps
    assert "retained-radial-utilisation" not in steps
    assert "capacity-verdict" not in steps
    for index, point in enumerate(out["plastic"]["points"]):
        assert steps[f"member-{index:03d}-axial-residual"].result.value == pytest.approx(
            point["axial_residual"]
        )
        assert steps[f"member-{index:03d}-axial-tolerance"].result.value == pytest.approx(
            point["axial_tolerance"]
        )
        assert steps[f"member-{index:03d}-converged"].result.value == 0.0
    assert audit_trace_registry(_bundle(family), family.registry)


def test_selected_nonconvergence_is_an_exact_failed_branch(finite_case):
    inp, out = finite_case
    failed_input = {**inp, "P_pl": inp["P_pl"] + 1.0}
    failed = copy.deepcopy(out)
    for point in failed["plastic"]["points"]:
        point["axial_residual"] += 1.0
        point["axial_tolerance"] = 41.0e-6
        point["converged"] = False
    failed["plastic"]["converged"] = False

    family = build_plastic_capacity_trace_family(
        failed_input,
        failed,
        context={},
    )
    steps = _steps(family)
    assert steps[family.calculation.final_step_id].result.state == RESULT_FAILED
    assert _axis_map(family)["result_branch"] == BRANCH_FAILED_SELECTED
    assert "selected-member-index" in steps
    assert "retained-radial-resistance" not in steps
    assert "retained-radial-utilisation" not in steps
    assert "capacity-verdict" not in steps
    assert family.registry.families[0].members[0].result_states == frozenset(
        {RESULT_FAILED}
    )


@pytest.mark.parametrize("selection", [True, 1.5, -1, 8])
def test_corrupt_selection_evidence_never_becomes_a_solver_failure(
    failed_unselected_case,
    selection,
):
    inp, out = failed_unselected_case
    hostile = copy.deepcopy(out)
    hostile["plastic"]["util_gov"] = selection
    with pytest.raises(TraceValidationError, match="util_gov"):
        build_plastic_capacity_trace_family(inp, hostile, context={})


def test_missing_selection_and_converged_no_selection_fail_closed(
    finite_case,
    failed_unselected_case,
):
    failed_input, failed_out = failed_unselected_case
    missing = copy.deepcopy(failed_out)
    del missing["plastic"]["util_gov"]
    with pytest.raises(TraceValidationError, match="util_gov is required"):
        build_plastic_capacity_trace_family(failed_input, missing, context={})

    finite_input, finite_out = finite_case
    no_selection = copy.deepcopy(finite_out)
    no_selection["plastic"]["util_gov"] = None
    with pytest.raises(TraceValidationError, match="authoritative envelope"):
        build_plastic_capacity_trace_family(finite_input, no_selection, context={})


def test_coherent_radial_and_selected_member_tamper_fail_authoritative_check(
    finite_case,
):
    inp, out = finite_case
    hostile = copy.deepcopy(out)
    hostile["plastic"]["resistance"] *= 2.0
    hostile["plastic"]["util"] = (
        hostile["plastic"]["demand"] / hostile["plastic"]["resistance"]
    )
    hostile["plastic"]["util_gov"] = (
        hostile["plastic"]["util_gov"] + 1
    ) % len(hostile["plastic"]["points"])
    with pytest.raises(TraceValidationError, match="authoritative envelope"):
        build_plastic_capacity_trace_family(inp, hostile, context={})

    resistance_only = copy.deepcopy(out)
    resistance_only["plastic"]["resistance"] *= 2.0
    resistance_only["plastic"]["util"] = (
        resistance_only["plastic"]["demand"]
        / resistance_only["plastic"]["resistance"]
    )
    with pytest.raises(TraceValidationError, match="radial resistance"):
        build_plastic_capacity_trace_family(inp, resistance_only, context={})


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("array", "Mx array member"),
        ("residual", "axial residual"),
        ("resultant", "axial material resultants"),
        ("masking", "masks a retained member"),
        ("missing", "missing tendon_my"),
    ],
)
def test_array_residual_resultant_masking_and_omission_fail_closed(
    finite_case,
    mutation,
    message,
):
    inp, out = finite_case
    hostile = copy.deepcopy(out)
    run_input = inp
    selected = hostile["plastic"]["util_gov"]
    point = hostile["plastic"]["points"][selected]
    if mutation == "array":
        point["Mx"] += 1.0
    elif mutation == "residual":
        point["axial_residual"] += 1.0
    elif mutation == "resultant":
        point["concrete_force"] += 1.0
    elif mutation == "masking":
        run_input = {**inp, "P_pl": inp["P_pl"] + 1.0}
        for retained in hostile["plastic"]["points"]:
            retained["axial_residual"] += 1.0
            retained["axial_tolerance"] = 41.0e-6
            retained["converged"] = False
    else:
        del point["tendon_my"]
    with pytest.raises(TraceValidationError, match=message):
        build_plastic_capacity_trace_family(run_input, hostile, context={})


@pytest.mark.parametrize(
    ("drift", "message"),
    [
        ("method", "identity mismatch"),
        ("axes", "identity mismatch"),
        ("source-edition", "identity mismatch"),
        ("step-order", "step IDs"),
        ("dependency", "dependency graph"),
    ],
)
def test_builder_self_audits_against_independently_declared_registry(
    finite_case,
    monkeypatch,
    drift,
    message,
):
    inp, out = finite_case
    original = plastic_capacity_trace._calculation

    def drifting_calculation(evidence, shape):
        calculation = original(evidence, shape)
        if drift == "method":
            return dataclasses.replace(calculation, method_id="project-drift")
        if drift == "axes":
            return dataclasses.replace(calculation, axes=calculation.axes[:-1])

        changed = list(calculation.steps)
        if drift == "source-edition":
            index = next(
                index
                for index, step in enumerate(changed)
                if step.source.kind == SOURCE_STANDARD
            )
            step = changed[index]
            changed[index] = dataclasses.replace(
                step,
                source=dataclasses.replace(step.source, edition="wrong-edition"),
            )
        elif drift == "step-order":
            changed[0], changed[1] = changed[1], changed[0]
        else:
            changed = [
                dataclasses.replace(
                    step,
                    dependencies=tuple(
                        item
                        for item in step.dependencies
                        if item.step_id != "geometry-concrete-block"
                    ),
                )
                if step.step_id == "member-000-concrete-force"
                else step
                for step in changed
            ]
        return dataclasses.replace(calculation, steps=tuple(changed))

    monkeypatch.setattr(
        plastic_capacity_trace,
        "_calculation",
        drifting_calculation,
    )
    with pytest.raises(TraceValidationError, match=message):
        build_plastic_capacity_trace_family(inp, out, context={})


def test_content_stale_edition_and_masking_trace_fail_closed(finite_case):
    inp, out = finite_case
    family = build_plastic_capacity_trace_family(
        inp,
        out,
        context={"case": "A"},
    )
    bundle = _bundle(family)
    changed = tuple(
        dataclasses.replace(
            step,
            result=TraceResult(RESULT_FINITE, step.result.value + 0.01),
        )
        if step.step_id == family.calculation.final_step_id
        else step
        for step in family.calculation.steps
    )
    tampered = dataclasses.replace(
        bundle,
        calculations=(dataclasses.replace(family.calculation, steps=changed),),
    )
    with pytest.raises(TraceValidationError, match="content seal"):
        validate_bundle(tampered)
    with pytest.raises(TraceValidationError, match="current input"):
        validate_bundle(bundle, expected_input_sha256="c" * 64)

    wrong_edition = {**inp, "concrete_preset": codes.EC2_2023.label}
    edition_candidate = build_plastic_capacity_trace_family(
        wrong_edition,
        out,
        context={"case": "A"},
    )
    with pytest.raises(TraceValidationError, match="identity mismatch"):
        audit_trace_registry(_bundle(edition_candidate), family.registry)

    masking_calculation = dataclasses.replace(
        family.calculation,
        calculation_id="plastic.other.selected-capacity",
    )
    masking_bundle = create_bundle(
        input_sha256="a" * 64,
        result_sha256="b" * 64,
        calculations=(masking_calculation,),
    )
    with pytest.raises(TraceValidationError, match="missing.*unexpected"):
        audit_trace_registry(masking_bundle, family.registry)
