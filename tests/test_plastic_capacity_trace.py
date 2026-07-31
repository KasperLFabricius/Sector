from __future__ import annotations

import copy
import dataclasses
import math
import sys
from pathlib import Path

import pytest

from sector import codes, combined, material_presets, plastic_capacity_trace
from sector.calculation_trace import (
    RESULT_FAILED,
    RESULT_FINITE,
    ROLE_METHOD_VALUE,
    ROLE_USER_INPUT,
    SourceCitation,
    TraceAxis,
    TraceResult,
    TraceValidationError,
    create_bundle,
    trace_identity_token,
    validate_bundle,
)
from sector.materials import MildSteel
from sector.plastic import solve_plastic
from sector.plastic_capacity_trace import build_plastic_capacity_trace_family
from sector.plastic_capacity_trace_contract import (
    BRANCH_FAILED_SELECTED,
    BRANCH_FAILED_UNSELECTED,
    BRANCH_FINITE_SELECTED,
    POINT_FIELDS,
)
from sector.section import Section
from sector.trace_registry import audit_trace_registry


def _catalog_item(material_id, preset, law):
    item = {"id": material_id, "preset": preset}
    for field in dataclasses.fields(law):
        value = getattr(law, field.name)
        if field.name in {"IS", "eut", "ey0t", "ey0c"}:
            value *= 1000.0
        elif field.name == "Es":
            value /= 1000.0
        item[field.name] = value
    return item


def _preset_law(values, builder):
    return builder(
        values["curve"],
        **{key: value for key, value in values.items() if key != "curve"},
    )


def _point(point):
    return {
        "V": point.V,
        "compression_depth": point.compression_depth,
        "kappa": point.curvature,
        "neutral_axis_depth": point.neutral_axis_depth,
        "na_x": point.na_x_intercept,
        "na_y": point.na_y_intercept,
        "eps_c": -point.eps_concrete,
        "eps_s": -point.eps_steel,
        "eps_s_comp": -point.eps_steel_comp,
        "eps_cable": -point.eps_cable,
        "requested_axial": point.requested_axial,
        "concrete_force": point.concrete_force,
        "concrete_mx": point.concrete_mx,
        "concrete_my": point.concrete_my,
        "bar_force": point.bar_force,
        "bar_mx": point.bar_mx,
        "bar_my": point.bar_my,
        "tendon_force": point.tendon_force,
        "tendon_mx": point.tendon_mx,
        "tendon_my": point.tendon_my,
        "comp_force": point.compression_force,
        "comp_mx": point.compression_mx,
        "comp_my": point.compression_my,
        "tension_force": point.tension_force,
        "tension_mx": point.tension_mx,
        "tension_my": point.tension_my,
        "achieved_axial": point.axial,
        "axial_residual": point.axial_residual,
        "axial_tolerance": point.axial_tolerance,
        "converged": point.converged,
        "Mx": point.Mx,
        "My": point.My,
        "dx": point.dx,
        "dy": point.dy,
        "lever": point.lever_arm,
    }


def _base_case(p_pl: float):
    concrete = codes.EC2_2005.concrete(35.0)
    standard_bar = codes.EC2_2023.steel(500.0)
    custom_bar = MildSteel(
        620.0,
        430.0,
        futk=680.0,
        eut=0.032,
        curve=1,
        Es=205000.0,
    )
    tendon = _preset_law(
        material_presets.PRESTRESS_PRESETS[codes.EC2_2005.label],
        material_presets.build_prestress,
    )
    section = Section.from_polygon(
        [(-0.2, 0.0), (0.2, 0.0), (0.2, 0.7), (-0.2, 0.7)],
        [(-0.13, 0.06, 900.0), (0.13, 0.64, 650.0)],
        tendons_xy_area_mm2=[(0.07, 0.11, 500.0)],
    )
    return {
        "section": section,
        "concrete": concrete,
        "steel": standard_bar,
        "prestress": tendon,
        "bar_materials": [standard_bar, custom_bar],
        "tendon_materials": [tendon],
        "concrete_preset": codes.EC2_2005.label,
        "mild_preset": codes.EC2_2023.label,
        "prestress_preset": codes.EC2_2005.label,
        "bar_elements": [
            {"id": "B1", "material_id": "S-STD"},
            {"id": "B2", "material_id": "S-CUSTOM"},
        ],
        "tendon_elements": [{"id": "T1", "material_id": "P-STD"}],
        "mild_material_catalog": {
            "items": [
                _catalog_item("S-STD", codes.EC2_2023.label, standard_bar),
                _catalog_item("S-CUSTOM", "Custom / imported", custom_bar),
            ]
        },
        "prestress_material_catalog": {
            "items": [
                _catalog_item("P-STD", codes.EC2_2005.label, tendon),
            ]
        },
        "P_pl": p_pl,
        "Mx_pl": 115.0,
        "My_pl": 65.0,
        "v_min": 0.0,
        "v_max": 360.0,
        "v_inc": 45.0,
    }


def _case(p_pl: float, selection: str = "finite"):
    inp = _base_case(p_pl)
    points = solve_plastic(
        inp["section"],
        inp["concrete"],
        inp["steel"],
        -inp["P_pl"],
        0.0,
        315.0,
        45.0,
        prestress=inp["prestress"],
        bar_materials=inp["bar_materials"],
        tendon_materials=inp["tendon_materials"],
    )
    mx = [point.Mx for point in points]
    my = [point.My for point in points]
    if selection == "selected-failure":
        candidates = [
            (0.2 * x, 0.2 * y)
            for x, y in zip(mx, my)
            if math.hypot(x, y) > 1.0e-9
        ]
        applied = next(
            pair
            for pair in candidates
            if combined.radial_util_result(mx, my, *pair).governing_index
            is not None
        )
    elif selection == "unselected-failure":
        candidates = [
            (100.0 * math.cos(math.radians(angle)),
             100.0 * math.sin(math.radians(angle)))
            for angle in range(0, 360, 5)
        ]
        applied = next(
            pair
            for pair in candidates
            if combined.radial_util_result(mx, my, *pair).governing_index is None
        )
    else:
        applied = (inp["Mx_pl"], inp["My_pl"])
    inp["Mx_pl"], inp["My_pl"] = applied
    radial = combined.radial_util_result(mx, my, *applied)
    out = {
        "plastic": {
            "mx": mx,
            "my": my,
            "util": radial.utilisation,
            "util_gov": radial.governing_index,
            "closed": True,
            "check_util": True,
            "applied": applied,
            "demand": radial.demand,
            "resistance": radial.resistance,
            "converged": all(point.converged for point in points),
            "points": [_point(point) for point in points],
        }
    }
    return inp, out


@pytest.fixture(scope="module")
def finite_case():
    return _case(40.0)


@pytest.fixture(scope="module")
def failed_unselected_case():
    return _case(100000.0, "unselected-failure")


@pytest.fixture(scope="module")
def failed_selected_case():
    return _case(100000.0, "selected-failure")


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


def _radial_oracle(mx, my, ax, ay):
    """Independent ray/polygon oracle; no production selector calls."""

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
    return demand, resistance, demand / resistance, selected


def _material_oracle(inp, point):
    """Independent V=90 rectangle oracle; it never calls trace/reconstruction code."""

    assert point["V"] == pytest.approx(90.0)
    width, bottom, top = 0.4, 0.0, 0.7
    kappa = point["kappa"]
    neutral_axis = point["neutral_axis_depth"]
    concrete = inp["concrete"]

    concrete_force = concrete_mx = 0.0
    peak = neutral_axis + concrete.eps_c2 / kappa
    plateau_low = max(peak, bottom)
    if plateau_low < top:
        force = concrete.fcd * width * (top - plateau_low) * 1000.0
        concrete_force += force
        concrete_mx += force * (top + plateau_low) / 2.0
    ascending_top = min(peak, top)
    ascending_bottom = max(neutral_axis, bottom)
    if ascending_top > ascending_bottom:
        band = (ascending_top - neutral_axis) / 80.0
        for index in range(80):
            low = neutral_axis + index * band
            high = low + band
            clipped_low = max(low, bottom)
            clipped_high = min(high, ascending_top)
            if clipped_high <= clipped_low:
                continue
            strain_midpoint = kappa * ((low + high) / 2.0 - neutral_axis)
            stress = -concrete.stress(-strain_midpoint, design=True)
            force = stress * width * (clipped_high - clipped_low) * 1000.0
            concrete_force += force
            concrete_mx += force * (clipped_low + clipped_high) / 2.0

    def point_resultants(elements, laws, tendon=False):
        force = mx = my = 0.0
        for element, law in zip(elements, laws):
            section_strain = kappa * (element.y - neutral_axis)
            if tendon:
                stress = law.stress(law.IS - section_strain, design=True)
                item_force = -stress * element.area * 1000.0
            else:
                stress = -law.stress(-section_strain, design=True)
                item_force = stress * element.area * 1000.0
            force += item_force
            mx += item_force * element.y
            my += item_force * element.x
        return force, mx, my

    return {
        "concrete": (concrete_force, concrete_mx, 0.0),
        "bar": point_resultants(inp["section"].bars, inp["bar_materials"]),
        "tendon": point_resultants(
            inp["section"].tendons, inp["tendon_materials"], tendon=True
        ),
    }


def test_finite_branch_matches_independent_oracles_and_exact_registry(finite_case):
    inp, out = finite_case
    demand, resistance, utilisation, selected = _radial_oracle(
        out["plastic"]["mx"],
        out["plastic"]["my"],
        inp["Mx_pl"],
        inp["My_pl"],
    )
    assert out["plastic"]["demand"] == pytest.approx(demand)
    assert out["plastic"]["resistance"] == pytest.approx(resistance)
    assert out["plastic"]["util"] == pytest.approx(utilisation)
    assert out["plastic"]["util_gov"] == selected

    oracle = _material_oracle(inp, out["plastic"]["points"][2])
    point = out["plastic"]["points"][2]
    for kind, expected in oracle.items():
        assert point[f"{kind}_force"] == pytest.approx(expected[0], abs=1.0e-8)
        assert point[f"{kind}_mx"] == pytest.approx(expected[1], abs=1.0e-8)
        assert point[f"{kind}_my"] == pytest.approx(expected[2], abs=1.0e-8)

    family = build_plastic_capacity_trace_family(
        inp, out, context={"case": "A/B", "stage": 2}
    )
    bundle = _bundle(family)
    assert audit_trace_registry(bundle, family.registry) is bundle
    assert _axis_map(family) == {
        trace_identity_token("case"): "A/B",
        "result_branch": BRANCH_FINITE_SELECTED,
        "retained_cardinality": "8",
        "selected_member": str(selected),
        trace_identity_token("stage"): "2",
    }
    final = _steps(family)[family.calculation.final_step_id]
    assert final.result.state == RESULT_FINITE
    assert final.result.value == pytest.approx(utilisation)

    member = family.registry.families[0].members[0]
    assert len(member.step_ids) == len(member.step_metadata) == len(family.calculation.steps)
    for step, metadata in zip(family.calculation.steps, member.step_metadata):
        assert (step.step_id, step.quantity_role, step.source) == (
            metadata.step_id,
            metadata.quantity_role,
            metadata.source,
        )


def test_canonical_role_closure_reaches_every_input_and_material_leaf(finite_case):
    inp, out = finite_case
    family = build_plastic_capacity_trace_family(inp, out, context={})
    steps = _steps(family)
    reached = _closure(steps, family.calculation.final_step_id)
    expected_leaves = {
        step.step_id
        for step in family.calculation.steps
        if step.quantity_role in {ROLE_USER_INPUT, ROLE_METHOD_VALUE}
    }
    assert expected_leaves
    assert expected_leaves <= reached

    bar_force_closure = _closure(steps, "member-000-bar-force")
    tendon_force_closure = _closure(steps, "member-000-tendon-force")
    concrete_force_closure = _closure(steps, "member-000-concrete-force")
    assert {"geometry-bars-block", "material-bars-block"} <= bar_force_closure
    assert {"geometry-tendons-block", "material-tendons-block"} <= tendon_force_closure
    assert {
        "geometry-concrete-block",
        "material-concrete-block",
        "solver-integration-bands",
    } <= concrete_force_closure


def test_live_solver_path_retains_the_exact_ct002_payload(finite_case, monkeypatch):
    inp, _ = finite_case
    app_dir = Path(__file__).resolve().parents[1] / "app"
    sys.path.insert(0, str(app_dir))
    try:
        import sector_app

        live_input = {
            **inp,
            "mode": "Plastic",
            "v_min": 0.0,
            "v_max": 360.0,
            "v_inc": 45.0,
            "bars": [
                (bar.x, bar.y, bar.area * 1.0e6)
                for bar in inp["section"].bars
            ],
            "tendons": [
                (tendon.x, tendon.y, tendon.area * 1.0e6)
                for tendon in inp["section"].tendons
            ],
        }
        monkeypatch.setattr(sector_app, "_run_capacity_checks", lambda *_: None)
        live = sector_app._run_single_analysis(live_input)
    finally:
        sys.path.remove(str(app_dir))
    assert set(live["plastic"]["points"][0]) == set(POINT_FIELDS)
    assert live["plastic"]["demand"] == pytest.approx(
        math.hypot(inp["Mx_pl"], inp["My_pl"])
    )
    family = build_plastic_capacity_trace_family(
        live_input, live, context={"case": "live"}
    )
    assert _axis_map(family)["result_branch"] == BRANCH_FINITE_SELECTED


def test_genuine_failed_unselected_branch_precedes_member_requirements(
    failed_unselected_case,
):
    inp, out = failed_unselected_case
    assert not out["plastic"]["converged"]
    assert out["plastic"]["util_gov"] is None
    family = build_plastic_capacity_trace_family(inp, out, context={})
    steps = _steps(family)
    assert _axis_map(family)["result_branch"] == BRANCH_FAILED_UNSELECTED
    assert steps[family.calculation.final_step_id].result.state == RESULT_FAILED
    assert "solver-run-evidence" in steps
    assert "member-000-concrete-force" in steps
    assert "selected-member-index" not in steps
    assert not {
        "retained-radial-demand",
        "retained-radial-resistance",
        "retained-radial-utilisation",
        "capacity-verdict",
    }.intersection(steps)


def test_genuine_failed_selected_branch_retains_no_engineering_verdict(
    failed_selected_case,
):
    inp, out = failed_selected_case
    assert not out["plastic"]["converged"]
    assert type(out["plastic"]["util_gov"]) is int
    family = build_plastic_capacity_trace_family(inp, out, context={})
    steps = _steps(family)
    assert _axis_map(family)["result_branch"] == BRANCH_FAILED_SELECTED
    assert "selected-member-index" in steps
    assert steps[family.calculation.final_step_id].result.state == RESULT_FAILED
    assert not {
        "retained-radial-demand",
        "retained-radial-resistance",
        "retained-radial-utilisation",
        "capacity-verdict",
    }.intersection(steps)


@pytest.mark.parametrize("selection", [None, True, 1.5, -1, 8])
def test_missing_boolean_noninteger_out_of_range_selection_fails_closed(
    finite_case,
    selection,
):
    inp, out = finite_case
    hostile = copy.deepcopy(out)
    hostile["plastic"]["util_gov"] = selection
    with pytest.raises(TraceValidationError, match="util_gov|selected"):
        build_plastic_capacity_trace_family(inp, hostile, context={})


def test_absent_and_contradictory_selection_fails_closed(finite_case):
    inp, out = finite_case
    missing = copy.deepcopy(out)
    missing["plastic"].pop("util_gov")
    with pytest.raises(TraceValidationError, match="util_gov is required"):
        build_plastic_capacity_trace_family(inp, missing, context={})

    contradictory = copy.deepcopy(out)
    selected = out["plastic"]["util_gov"]
    contradictory["plastic"]["util_gov"] = (selected + 1) % len(
        out["plastic"]["points"]
    )
    with pytest.raises(TraceValidationError, match="authoritative"):
        build_plastic_capacity_trace_family(inp, contradictory, context={})


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("remove", "cardinality"),
        ("reorder", "angle order"),
    ],
)
def test_requested_sweep_rejects_coherently_resealed_member_drift(
    finite_case,
    mutation,
    message,
):
    inp, out = finite_case
    hostile = copy.deepcopy(out)
    result = hostile["plastic"]
    if mutation == "remove":
        for key in ("points", "mx", "my"):
            result[key].pop(2)
    else:
        order = (1, 0, *range(2, len(result["points"])))
        for key in ("points", "mx", "my"):
            result[key] = [result[key][index] for index in order]

    radial = combined.radial_util_result(
        result["mx"], result["my"], inp["Mx_pl"], inp["My_pl"]
    )
    result["demand"] = radial.demand
    result["resistance"] = radial.resistance
    result["util"] = radial.utilisation
    result["util_gov"] = radial.governing_index
    result["converged"] = all(point["converged"] for point in result["points"])
    with pytest.raises(TraceValidationError, match=message):
        build_plastic_capacity_trace_family(inp, hostile, context={})


@pytest.mark.parametrize(
    ("target", "compensator"),
    [
        (f"{target}_{component}", f"{other}_{component}")
        for component in ("force", "mx", "my")
        for target, other in (
            ("concrete", "bar"),
            ("bar", "concrete"),
            ("tendon", "bar"),
        )
    ],
)
def test_authoritative_reconstruction_rejects_each_forged_material_component(
    finite_case,
    target,
    compensator,
):
    inp, out = finite_case
    hostile = copy.deepcopy(out)
    point = hostile["plastic"]["points"][2]
    point[target] += 7.25
    point[compensator] -= 7.25
    with pytest.raises(TraceValidationError, match="reconstructed"):
        build_plastic_capacity_trace_family(inp, hostile, context={})


@pytest.mark.parametrize(("first", "second"), [("concrete", "bar"), ("bar", "tendon")])
def test_coherent_cross_material_swaps_preserve_totals_but_fail_reconstruction(
    finite_case,
    first,
    second,
):
    inp, out = finite_case
    hostile = copy.deepcopy(out)
    point = hostile["plastic"]["points"][2]
    for component in ("force", "mx", "my"):
        a, b = f"{first}_{component}", f"{second}_{component}"
        point[a], point[b] = point[b], point[a]
    with pytest.raises(TraceValidationError, match="reconstructed"):
        build_plastic_capacity_trace_family(inp, hostile, context={})


def test_coherent_radial_tamper_is_rejected_by_authoritative_selector(finite_case):
    inp, out = finite_case
    hostile = copy.deepcopy(out)
    hostile["plastic"]["resistance"] *= 2.0
    hostile["plastic"]["util"] = (
        hostile["plastic"]["demand"] / hostile["plastic"]["resistance"]
    )
    with pytest.raises(TraceValidationError, match="radial resistance"):
        build_plastic_capacity_trace_family(inp, hostile, context={})


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda out: out["plastic"]["mx"].__setitem__(0, out["plastic"]["mx"][0] + 1.0),
            "Mx array member",
        ),
        (
            lambda out: out["plastic"]["points"][0].__setitem__(
                "axial_residual", out["plastic"]["points"][0]["axial_residual"] + 1.0
            ),
            "axial residual",
        ),
        (
            lambda out: out["plastic"].__setitem__("converged", False),
            "masks",
        ),
        (
            lambda out: out["plastic"]["points"][0].pop("bar_mx"),
            "missing bar_mx",
        ),
    ],
)
def test_array_residual_convergence_and_resultant_drift_fails_closed(
    finite_case,
    mutation,
    message,
):
    inp, out = finite_case
    hostile = copy.deepcopy(out)
    mutation(hostile)
    with pytest.raises(TraceValidationError, match=message):
        build_plastic_capacity_trace_family(inp, hostile, context={})


def _replace_steps(calculation, replacements):
    return dataclasses.replace(
        calculation,
        steps=tuple(replacements.get(step.step_id, step) for step in calculation.steps),
    )


def test_resealed_role_source_and_citation_swaps_fail_exact_metadata(finite_case):
    inp, out = finite_case
    family = build_plastic_capacity_trace_family(inp, out, context={})
    steps = _steps(family)
    action = steps["input-action-mx-pl"]
    material = steps["material-concrete-fck"]
    swapped = _replace_steps(
        family.calculation,
        {
            action.step_id: dataclasses.replace(
                action,
                quantity_role=material.quantity_role,
                source=material.source,
            ),
            material.step_id: dataclasses.replace(
                material,
                quantity_role=action.quantity_role,
                source=action.source,
            ),
        },
    )
    resealed = create_bundle(
        input_sha256="a" * 64,
        result_sha256="b" * 64,
        calculations=(swapped,),
    )
    with pytest.raises(TraceValidationError, match="quantity role|source"):
        audit_trace_registry(resealed, family.registry)

    bar_material = steps["material-bar-000-fytk"]
    source_swapped = _replace_steps(
        family.calculation,
        {
            material.step_id: dataclasses.replace(
                material, source=bar_material.source
            ),
            bar_material.step_id: dataclasses.replace(
                bar_material, source=material.source
            ),
        },
    )
    resealed = create_bundle(
        input_sha256="a" * 64,
        result_sha256="b" * 64,
        calculations=(source_swapped,),
    )
    with pytest.raises(TraceValidationError, match="source"):
        audit_trace_registry(resealed, family.registry)

    citation = material.source.citation
    forged_source = dataclasses.replace(
        material.source,
        citation=SourceCitation(
            citation.document,
            citation.clause,
            citation.locator + " forged",
        ),
    )
    forged = _replace_steps(
        family.calculation,
        {material.step_id: dataclasses.replace(material, source=forged_source)},
    )
    resealed = create_bundle(
        input_sha256="a" * 64,
        result_sha256="b" * 64,
        calculations=(forged,),
    )
    with pytest.raises(TraceValidationError, match="source"):
        audit_trace_registry(resealed, family.registry)


def test_resealed_dependency_identity_cardinality_state_and_masking_tamper_fail(
    finite_case,
):
    inp, out = finite_case
    family = build_plastic_capacity_trace_family(inp, out, context={})
    steps = _steps(family)

    resultant = steps["member-000-concrete-force"]
    graph_drift = _replace_steps(
        family.calculation,
        {
            resultant.step_id: dataclasses.replace(
                resultant, dependencies=resultant.dependencies[:-1]
            )
        },
    )
    resealed = create_bundle(
        input_sha256="a" * 64,
        result_sha256="b" * 64,
        calculations=(graph_drift,),
    )
    with pytest.raises(TraceValidationError, match="dependency graph"):
        audit_trace_registry(resealed, family.registry)

    for hostile in (
        dataclasses.replace(family.calculation, method_id="forged-method"),
        dataclasses.replace(
            family.calculation,
            axes=tuple(
                TraceAxis(axis.name, "999")
                if axis.name == "retained_cardinality"
                else axis
                for axis in family.calculation.axes
            ),
        ),
        _replace_steps(
            family.calculation,
            {
                family.calculation.final_step_id: dataclasses.replace(
                    steps[family.calculation.final_step_id],
                    result=TraceResult(RESULT_FAILED, None, "forged failure"),
                )
            },
        ),
    ):
        resealed = create_bundle(
            input_sha256="a" * 64,
            result_sha256="b" * 64,
            calculations=(hostile,),
        )
        with pytest.raises(TraceValidationError, match="identity mismatch"):
            audit_trace_registry(resealed, family.registry)

    unrelated = dataclasses.replace(
        family.calculation, calculation_id="plastic.other.selected-capacity"
    )
    masked = create_bundle(
        input_sha256="a" * 64,
        result_sha256="b" * 64,
        calculations=(family.calculation, unrelated),
    )
    with pytest.raises(TraceValidationError, match="unexpected"):
        audit_trace_registry(masked, family.registry)
    replacement = create_bundle(
        input_sha256="a" * 64,
        result_sha256="b" * 64,
        calculations=(unrelated,),
    )
    with pytest.raises(TraceValidationError, match="missing.*unexpected"):
        audit_trace_registry(replacement, family.registry)


def test_content_seal_and_stale_hash_tamper_fail_closed(finite_case):
    inp, out = finite_case
    family = build_plastic_capacity_trace_family(inp, out, context={})
    bundle = _bundle(family)
    with pytest.raises(TraceValidationError, match="input fingerprint"):
        validate_bundle(bundle, expected_input_sha256="c" * 64)

    hostile_calculation = dataclasses.replace(
        family.calculation, title="Forged selected capacity"
    )
    hostile_bundle = dataclasses.replace(
        bundle, calculations=(hostile_calculation,)
    )
    with pytest.raises(TraceValidationError, match="content seal"):
        validate_bundle(hostile_bundle)


def test_builder_self_audit_does_not_derive_metadata_from_candidate(
    finite_case,
    monkeypatch,
):
    inp, out = finite_case
    original = plastic_capacity_trace._calculation

    def hostile_calculation(evidence, shape):
        calculation = original(evidence, shape)
        steps = {step.step_id: step for step in calculation.steps}
        action = steps["input-action-my-pl"]
        material = steps["material-concrete-fck"]
        return _replace_steps(
            calculation,
            {
                action.step_id: dataclasses.replace(
                    action,
                    quantity_role=material.quantity_role,
                    source=material.source,
                ),
                material.step_id: dataclasses.replace(
                    material,
                    quantity_role=action.quantity_role,
                    source=action.source,
                ),
            },
        )

    monkeypatch.setattr(plastic_capacity_trace, "_calculation", hostile_calculation)
    with pytest.raises(TraceValidationError, match="quantity role|source"):
        build_plastic_capacity_trace_family(inp, out, context={})
