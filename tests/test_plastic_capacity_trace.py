from __future__ import annotations

import copy
import dataclasses
import math

import pytest

from sector import codes, combined, material_presets
from sector.calculation_trace import (
    RESULT_FAILED,
    RESULT_FINITE,
    ROLE_METHOD_VALUE,
    SourceCitation,
    TraceAxis,
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


def _point(point):
    values = {
        field: getattr(point, field)
        for field in POINT_FIELDS
        if hasattr(point, field)
    }
    values.update(
        kappa=point.curvature,
        na_x=point.na_x_intercept,
        na_y=point.na_y_intercept,
        eps_c=-point.eps_concrete,
        eps_s=-point.eps_steel,
        eps_s_comp=-point.eps_steel_comp,
        eps_cable=-point.eps_cable,
        achieved_axial=point.axial,
        comp_force=point.compression_force,
        comp_mx=point.compression_mx,
        comp_my=point.compression_my,
        lever=point.lever_arm,
    )
    return values


def _base_input(p_pl):
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
    values = material_presets.PRESTRESS_PRESETS[codes.EC2_2005.label]
    tendon = material_presets.build_prestress(
        values["curve"],
        **{key: value for key, value in values.items() if key != "curve"},
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
        "v_inc": 90.0,
    }


def _case(p_pl, selection="finite"):
    inp = _base_input(p_pl)
    points = solve_plastic(
        inp["section"],
        inp["concrete"],
        inp["steel"],
        -inp["P_pl"],
        0.0,
        270.0,
        90.0,
        prestress=inp["prestress"],
        bar_materials=inp["bar_materials"],
        tendon_materials=inp["tendon_materials"],
    )
    mx = [point.Mx for point in points]
    my = [point.My for point in points]
    if selection == "unselected":
        applied = (0.0, 0.0)
    elif selection == "selected":
        applied = next(
            (0.2 * x, 0.2 * y)
            for x, y in zip(mx, my)
            if combined.radial_util_result(
                mx, my, 0.2 * x, 0.2 * y
            ).governing_index
            is not None
        )
    else:
        applied = (inp["Mx_pl"], inp["My_pl"])
    inp["Mx_pl"], inp["My_pl"] = applied
    radial = combined.radial_util_result(mx, my, *applied)
    return inp, {
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


@pytest.fixture(scope="module")
def finite_case():
    return _case(40.0)


@pytest.fixture(scope="module")
def failed_selected_case():
    return _case(100000.0, "selected")


@pytest.fixture(scope="module")
def failed_unselected_case():
    return _case(100000.0, "unselected")


def _bundle(family, input_hash="a" * 64, result_hash="b" * 64):
    return create_bundle(
        input_sha256=input_hash,
        result_sha256=result_hash,
        calculations=(family.calculation,),
    )


def _steps(family):
    return {step.step_id: step for step in family.calculation.steps}


def _radial_oracle(mx, my, ax, ay):
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
    """Independent V=90 rectangular integration; no trace builder calls."""

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
    if ascending_top > neutral_axis:
        band = (ascending_top - neutral_axis) / 80.0
        for index in range(80):
            low = neutral_axis + index * band
            high = low + band
            clipped_low = max(low, bottom)
            clipped_high = min(high, ascending_top)
            if clipped_high <= clipped_low:
                continue
            strain = kappa * ((low + high) / 2.0 - neutral_axis)
            stress = -concrete.stress(-strain, design=True)
            force = stress * width * (clipped_high - clipped_low) * 1000.0
            concrete_force += force
            concrete_mx += force * (clipped_low + clipped_high) / 2.0

    def point_resultants(elements, laws, tendon=False):
        force = mx = my = 0.0
        for element, law in zip(elements, laws):
            strain = kappa * (element.y - neutral_axis)
            stress = (
                law.stress(law.IS - strain, design=True)
                if tendon
                else -law.stress(-strain, design=True)
            )
            item_force = (-1.0 if tendon else 1.0) * stress * element.area * 1000.0
            force += item_force
            mx += item_force * element.y
            my += item_force * element.x
        return force, mx, my

    return {
        "concrete": (concrete_force, concrete_mx, 0.0),
        "bar": point_resultants(inp["section"].bars, inp["bar_materials"]),
        "tendon": point_resultants(
            inp["section"].tendons,
            inp["tendon_materials"],
            tendon=True,
        ),
    }


def test_finite_branch_matches_independent_oracles_and_registry(finite_case):
    inp, out = finite_case
    oracle = _radial_oracle(
        out["plastic"]["mx"],
        out["plastic"]["my"],
        inp["Mx_pl"],
        inp["My_pl"],
    )
    assert out["plastic"]["demand"] == pytest.approx(oracle[0])
    assert out["plastic"]["resistance"] == pytest.approx(oracle[1])
    assert out["plastic"]["util"] == pytest.approx(oracle[2])
    assert out["plastic"]["util_gov"] == oracle[3]
    point = out["plastic"]["points"][1]
    for kind, expected in _material_oracle(inp, point).items():
        for field, value in zip(("force", "mx", "my"), expected):
            assert point[f"{kind}_{field}"] == pytest.approx(value, abs=1.0e-8)

    family = build_plastic_capacity_trace_family(
        inp, out, context={"case": "A/B", "stage": 2}
    )
    bundle = _bundle(family)
    assert audit_trace_registry(bundle, family.registry) is bundle
    axes = {axis.name: axis.value for axis in family.calculation.axes}
    assert axes == {
        trace_identity_token("case"): "A/B",
        trace_identity_token("stage"): "2",
        "result_branch": BRANCH_FINITE_SELECTED,
        "retained_cardinality": "4",
        "selected_member": str(oracle[3]),
    }
    assert _steps(family)[family.calculation.final_step_id].result.state == RESULT_FINITE
    member = family.registry.families[0].members[0]
    assert len(member.step_ids) == len(member.step_metadata) == len(family.calculation.steps)


def test_live_solver_retains_detail_only_for_finite_branch(monkeypatch):
    from app import sector_app

    monkeypatch.setattr(sector_app, "_warm_solver", lambda: None)
    monkeypatch.setattr(sector_app, "_run_capacity_checks", lambda inp, out: None)
    finite = _base_input(40.0)
    finite.update(mode="Plastic", tendons=finite["section"].tendons)
    finite_out = sector_app._run_single_analysis(finite)
    assert set(finite_out["plastic"]["points"][0]) == set(POINT_FIELDS)
    assert {"demand", "resistance"} <= set(finite_out["plastic"])
    build_plastic_capacity_trace_family(finite, finite_out, context={})

    failed = _base_input(100000.0)
    failed.update(
        mode="Plastic",
        tendons=failed["section"].tendons,
        Mx_pl=0.0,
        My_pl=0.0,
    )
    failed_out = sector_app._run_single_analysis(failed)
    assert "compression_depth" not in failed_out["plastic"]["points"][0]
    assert "demand" not in failed_out["plastic"]
    family = build_plastic_capacity_trace_family(failed, failed_out, context={})
    assert _steps(family)[family.calculation.final_step_id].result.state == RESULT_FAILED


@pytest.mark.parametrize("fixture_name", ["failed_selected_case", "failed_unselected_case"])
def test_failure_trace_is_minimal_and_hidden_engineering_is_inert(
    request, fixture_name
):
    inp, out = request.getfixturevalue(fixture_name)
    family = build_plastic_capacity_trace_family(inp, out, context={"case": "F"})
    steps = _steps(family)
    branch = (
        BRANCH_FAILED_SELECTED
        if out["plastic"]["util_gov"] is not None
        else BRANCH_FAILED_UNSELECTED
    )
    assert {axis.name: axis.value for axis in family.calculation.axes}[
        "result_branch"
    ] == branch
    assert steps[family.calculation.final_step_id].result.state == RESULT_FAILED
    forbidden = {
        "compression-depth",
        "kappa",
        "neutral-axis",
        "eps-",
        "force",
        "-mx",
        "-my",
        "resistance",
        "utilisation",
        "verdict",
        "lever",
    }
    assert not any(
        token in step_id for token in forbidden for step_id in steps
    )
    assert steps["failure-count"].result.value == sum(
        not point["converged"] for point in out["plastic"]["points"]
    )

    hostile = copy.deepcopy(out)
    for point in hostile["plastic"]["points"]:
        for field in set(POINT_FIELDS) - {"V", "converged"}:
            point[field] = 987654.25
    hostile["plastic"]["mx"] = "unreported failed array"
    hostile["plastic"]["my"] = None
    hostile["plastic"].update(
        demand=999.0,
        resistance=1.0,
        util=999.0,
        verdict=True,
    )
    rebuilt = build_plastic_capacity_trace_family(
        inp, hostile, context={"case": "F"}
    )
    assert rebuilt == family

    removed = copy.deepcopy(out)
    removed["plastic"].pop("mx")
    removed["plastic"].pop("my")
    for point in removed["plastic"]["points"]:
        point.pop("Mx")
        point.pop("My")
    assert build_plastic_capacity_trace_family(
        inp, removed, context={"case": "F"}
    ) == family

    reordered = copy.deepcopy(out)
    reordered["plastic"]["mx"].reverse()
    reordered["plastic"]["my"].reverse()
    point_mx = [point["Mx"] for point in reordered["plastic"]["points"]]
    point_my = [point["My"] for point in reordered["plastic"]["points"]]
    for point, mx, my in zip(
        reordered["plastic"]["points"], reversed(point_mx), reversed(point_my)
    ):
        point["Mx"], point["My"] = mx, my
    assert build_plastic_capacity_trace_family(
        inp, reordered, context={"case": "F"}
    ) == family

    flag_tamper = copy.deepcopy(out)
    index = next(
        i for i, point in enumerate(flag_tamper["plastic"]["points"])
        if not point["converged"]
    )
    flag_tamper["plastic"]["points"][index]["converged"] = True
    with pytest.raises(TraceValidationError):
        build_plastic_capacity_trace_family(inp, flag_tamper, context={})

    promotion = copy.deepcopy(out)
    promotion["plastic"]["converged"] = True
    for point in promotion["plastic"]["points"]:
        point["converged"] = True
    with pytest.raises(TraceValidationError):
        build_plastic_capacity_trace_family(inp, promotion, context={})


def test_corrupt_selection_fails_closed(failed_selected_case, failed_unselected_case):
    inp, out = failed_selected_case
    selected = out["plastic"]["util_gov"]
    variants = []
    missing = copy.deepcopy(out)
    del missing["plastic"]["util_gov"]
    variants.append(missing)
    for value in (True, 1.5, len(out["plastic"]["points"]), None):
        hostile = copy.deepcopy(out)
        hostile["plastic"]["util_gov"] = value
        variants.append(hostile)
    wrong = copy.deepcopy(out)
    wrong["plastic"]["util_gov"] = (selected + 1) % len(out["plastic"]["points"])
    variants.append(wrong)
    for hostile in variants:
        with pytest.raises(TraceValidationError):
            build_plastic_capacity_trace_family(inp, hostile, context={})

    inp, out = failed_unselected_case
    hostile = copy.deepcopy(out)
    hostile["plastic"]["util_gov"] = 0
    with pytest.raises(TraceValidationError):
        build_plastic_capacity_trace_family(inp, hostile, context={})


def _recompute_radial(inp, out):
    result = out["plastic"]
    radial = combined.radial_util_result(
        result["mx"], result["my"], inp["Mx_pl"], inp["My_pl"]
    )
    result.update(
        util=radial.utilisation,
        util_gov=radial.governing_index,
        demand=radial.demand,
        resistance=radial.resistance,
    )


def test_sweep_material_and_radial_tamper_fail_closed(finite_case):
    inp, out = finite_case
    deleted = copy.deepcopy(out)
    for key in ("points", "mx", "my"):
        del deleted["plastic"][key][1]
    _recompute_radial(inp, deleted)

    reordered = copy.deepcopy(out)
    order = (1, 0, 2, 3)
    for key in ("points", "mx", "my"):
        values = reordered["plastic"][key]
        reordered["plastic"][key] = [values[index] for index in order]
    _recompute_radial(inp, reordered)
    for hostile in (deleted, reordered):
        with pytest.raises(TraceValidationError):
            build_plastic_capacity_trace_family(inp, hostile, context={})

    swapped = copy.deepcopy(out)
    point = swapped["plastic"]["points"][1]
    for suffix, delta in (("force", 10.0), ("mx", 2.0), ("my", 3.0)):
        point[f"concrete_{suffix}"] += delta
        point[f"bar_{suffix}"] -= delta
    with pytest.raises(TraceValidationError):
        build_plastic_capacity_trace_family(inp, swapped, context={})

    radial = copy.deepcopy(out)
    radial["plastic"]["resistance"] *= 2.0
    radial["plastic"]["util"] = (
        radial["plastic"]["demand"] / radial["plastic"]["resistance"]
    )
    with pytest.raises(TraceValidationError):
        build_plastic_capacity_trace_family(inp, radial, context={})

    depth = copy.deepcopy(out)
    depth["plastic"]["points"][0]["compression_depth"] += 1.0e-5
    with pytest.raises(TraceValidationError):
        build_plastic_capacity_trace_family(inp, depth, context={})


def _resealed(family, steps):
    calculation = dataclasses.replace(family.calculation, steps=tuple(steps))
    return create_bundle(
        input_sha256="a" * 64,
        result_sha256="b" * 64,
        calculations=(calculation,),
    )


def test_metadata_seals_staleness_and_masking_fail_closed(finite_case):
    inp, out = finite_case
    family = build_plastic_capacity_trace_family(inp, out, context={})
    steps = list(family.calculation.steps)

    index = next(i for i, step in enumerate(steps) if step.step_id == "input-action-p-pl")
    role_steps = list(steps)
    role_steps[index] = dataclasses.replace(
        role_steps[index], quantity_role=ROLE_METHOD_VALUE
    )
    with pytest.raises(TraceValidationError):
        audit_trace_registry(_resealed(family, role_steps), family.registry)

    index = next(i for i, step in enumerate(steps) if step.source.citation is not None)
    source_steps = list(steps)
    source = source_steps[index].source
    citation = source.citation
    source_steps[index] = dataclasses.replace(
        source_steps[index],
        source=dataclasses.replace(
            source,
            citation=SourceCitation(
                citation.document,
                citation.clause + " hostile",
                citation.locator,
            ),
        ),
    )
    with pytest.raises(TraceValidationError):
        audit_trace_registry(_resealed(family, source_steps), family.registry)

    index = next(i for i, step in enumerate(steps) if step.step_id == "capacity-verdict")
    dependency_steps = list(steps)
    selected = _steps(family)["selected-member-index"]
    dependency_steps[index] = dataclasses.replace(
        dependency_steps[index],
        dependencies=(
            dataclasses.replace(
                dependency_steps[index].dependencies[0],
                step_id=selected.step_id,
                unit=selected.unit,
            ),
        ),
    )
    with pytest.raises(TraceValidationError):
        audit_trace_registry(_resealed(family, dependency_steps), family.registry)

    order_steps = list(steps)
    order_steps[0], order_steps[1] = order_steps[1], order_steps[0]
    with pytest.raises(TraceValidationError):
        audit_trace_registry(_resealed(family, order_steps), family.registry)

    bundle = _bundle(family)
    with pytest.raises(TraceValidationError):
        validate_bundle(dataclasses.replace(bundle, warnings=("tampered",)))
    with pytest.raises(TraceValidationError):
        validate_bundle(bundle, expected_input_sha256="c" * 64)

    masking = dataclasses.replace(
        family.calculation,
        calculation_id="plastic.mask.selected-capacity",
        axes=(TraceAxis("mask", "true"),),
    )
    masked = create_bundle(
        input_sha256="a" * 64,
        result_sha256="b" * 64,
        calculations=(family.calculation, masking),
    )
    with pytest.raises(TraceValidationError):
        audit_trace_registry(masked, family.registry)


def test_contract_is_independent_of_candidate_metadata(finite_case, monkeypatch):
    inp, out = finite_case
    import sector.plastic_capacity_trace as module

    original = module._calculation

    def hostile(evidence, shape):
        calculation = original(evidence, shape)
        steps = list(calculation.steps)
        steps[0] = dataclasses.replace(
            steps[0], quantity_role=ROLE_METHOD_VALUE
        )
        return dataclasses.replace(calculation, steps=tuple(steps))

    monkeypatch.setattr(module, "_calculation", hostile)
    with pytest.raises(TraceValidationError):
        build_plastic_capacity_trace_family(inp, out, context={})
