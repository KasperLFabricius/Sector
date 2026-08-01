"""Independent numerical and exact-contract evidence for PR-08C traces."""

from __future__ import annotations

import copy
import dataclasses
import inspect
import math

import pytest

from sector import capacity, codes, combined, detailing
from sector.calculation_trace import RESULT_FAILED, RESULT_FINITE, SOURCE_PROJECT
from sector.section import Section
from sector.shear_torsion_detailing_trace import (
    build_detailing_trace_family,
    build_pr08c_trace_families,
    build_shear_trace_family,
    build_torsion_trace_family,
)


INPUT_SHA = "1" * 64
RESULT_SHA = "2" * 64
CONTEXT = {"load_case": "ULS-01"}


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


def _input(**overrides):
    outer = [(-0.15, -0.30), (0.15, -0.30), (0.15, 0.30), (-0.15, 0.30)]
    bars = [
        (-0.12, -0.25, 491.0),
        (0.12, -0.25, 491.0),
        (-0.12, 0.25, 491.0),
        (0.12, 0.25, 491.0),
    ]
    code = codes.EC2_2005_DKNA
    concrete = code.concrete(35.0)
    steel = code.steel(500.0)
    section = Section.from_polygon(outer, bars)
    elements = [
        {
            "id": f"R{index + 1}",
            "kind": "bar",
            "x_mm": x * 1000.0,
            "y_mm": y * 1000.0,
            "diameter_mm": 25.0,
            "material_id": "B500",
        }
        for index, (x, y, _area) in enumerate(bars)
    ]
    inp = {
        "outer": outer,
        "holes": [],
        "bars": bars,
        "tendons": [],
        "section": section,
        "concrete": concrete,
        "steel": steel,
        "prestress": None,
        "bar_elements": elements,
        "bar_materials": [steel] * len(bars),
        "tendon_elements": [],
        "tendon_materials": [],
        "mild_material_catalog": {
            "items": [_catalog_item("B500", code.label, steel)]
        },
        "prestress_material_catalog": {"items": []},
        "concrete_preset": code.label,
        "mild_preset": code.label,
        "prestress_preset": code.label,
        "P_pl": 0.0,
        "Mx_pl": 100.0,
        "My_pl": -60.0,
        "shear_on": True,
        "shear_method": code.label,
        "shear_Vx": 60.0,
        "shear_Vy": -80.0,
        "shear_face_x": "auto",
        "shear_face_y": "auto",
        "shear_vx_bw": 0.0,
        "shear_vy_bw": 0.0,
        "shear_vx_link_legs": 2.0,
        "shear_vy_link_legs": 2.0,
        "shear_vx_transverse_leg_spacing": 250.0,
        "shear_vy_transverse_leg_spacing": 250.0,
        "shear_axis": "x",
        "shear_tension": True,
        "shear_V": 80.0,
        "shear_bw": 0.0,
        "shear_link_legs": 2.0,
        "shear_dlower": 16.0,
        "shear_links": True,
        "strut_cot_min": 1.0,
        "strut_cot_max": 2.5,
        "shear_link_dia": 10.0,
        "shear_link_s": 150.0,
        "shear_fywk": 500.0,
        "transverse_ductility_class": "B",
        "transverse_apply_ductility_reduction": False,
        "torsion_on": True,
        "torsion_method": code.label,
        "torsion_T": 35.0,
        "torsion_tef": 0.0,
        "torsion_nu_v": True,
        "torsion_gamma_ct": 1.70,
        "torsion_subdivide": False,
        "torsion_subrects": [],
        "combined_on": False,
        "detailing_edition": detailing.EC2_2005_DKNA,
        "detailing_member_type": detailing.MEMBER_BEAM,
        "detailing_cut_direction": detailing.CUT_TRANSVERSE,
        "minimum_reinforcement_on": True,
        "clear_spacing_on": True,
        "transverse_detailing_on": True,
        "detailing_d_upper": 16.0,
        "detailing_include_tendons": False,
        "sls_fctm": 3.2,
    }
    inp.update(overrides)
    return inp


def _shear_output(inp):
    n_prestress = capacity.prestress_axial(inp)
    n_comp = -inp["P_pl"] + n_prestress
    contexts = capacity.build_directional_shear_contexts(inp, n_prestress, n_comp)
    directions = {}
    for component in (key for key in ("vx", "vy") if key in contexts):
        definition = contexts[component]
        candidates = []
        for payload, links in definition["candidates"]:
            shear_result = copy.deepcopy(payload)
            if links is None:
                util = payload["v_ed"] / payload["res"]["vrd_c"]
            else:
                def at(cot):
                    return links["build"](cot, cot)

                utilities = (
                    lambda cot: combined.ratio(
                        payload["v_ed"], at(cot)["vrd_s"]
                    ),
                    lambda cot: combined.ratio(
                        payload["v_ed"], at(cot)["vrd_max"]
                    ),
                )
                cot, _ = combined.governing_strut_cot(
                    utilities, links["cot_min"], links["cot_max"]
                )
                resistance = at(cot)
                util = payload["v_ed"] / resistance["vrd"]
                shear_result["links"] = {
                    "res": resistance,
                    "util": util,
                    "asw": links["asw"],
                    "asw_over_s": links["asw_over_s"],
                    "legs": links["link_legs"],
                    "dia": inp["shear_link_dia"],
                    "s": inp["shear_link_s"],
                    "fywk": inp["shear_fywk"],
                    "cot_min": links["cot_min"],
                    "cot_max": links["cot_max"],
                    "model_2023": links["model_2023"],
                    "z_source": links["z_src"],
                    "required": bool(payload["v_ed"] > links["vrd_c"]),
                }
            shear_result["util"] = payload["v_ed"] / payload["res"]["vrd_c"]
            status = "PASS" if util <= 1.0 + 1.0e-9 else "FAIL"
            candidates.append({
                "tension_low": payload["tension_low"],
                "shear_status": status,
                "shear_metric": util,
                "shear": shear_result,
            })
        governing = max(
            candidates,
            key=lambda item: capacity.assessment_key(
                item["shear_status"], item["shear_metric"]
            ),
        )
        direction = copy.deepcopy(governing["shear"])
        direction.update(
            face_candidates=candidates,
            governing_face=(
                "negative" if governing["tension_low"] else "positive"
            ),
            status=capacity.aggregate_assessment_status(
                item["shear_status"] for item in candidates
            ),
            face_mode=definition["face_mode"],
            both_faces_evaluated=definition["both_faces_evaluated"],
            associated_moment=definition["associated_moment"],
            signed_v_ed=capacity.shear_direction_specs(inp)[component]["signed_v_ed"],
        )
        directions[component] = direction
    if len(directions) == 1:
        return {"shear": next(iter(directions.values()))}
    return {"shear": {"directions": directions}}


def _torsion_output(inp):
    n_comp = -inp["P_pl"] + capacity.prestress_axial(inp)
    context = capacity.build_torsion_context(inp, n_comp)
    if not all(tube["valid"] for tube in context["subtubes"]):
        return {"torsion": {"valid": False, "reason": context["tube"]["reason"]}}
    def at(cot, tube, demand):
        kwargs = dict(context["_tk"], cot_min=cot, cot_max=cot)
        return capacity.tube_torsion(tube, demand, **kwargs)

    if context["t_ed"] > 0.0:
        utilities = tuple(
            lambda cot, tube=tube, demand=demand: at(cot, tube, demand)["util"]
            for tube, demand in zip(context["subtubes"], context["ted_parts"])
        )
        cot, _ = combined.governing_strut_cot(
            utilities, context["tcot_min"], context["tcot_max"]
        )
        results = [
            at(cot, tube, demand)
            for tube, demand in zip(context["subtubes"], context["ted_parts"])
        ]
    else:
        results = [
            capacity.tube_torsion(tube, demand, **context["_tk"])
            for tube, demand in zip(context["subtubes"], context["ted_parts"])
        ]
    if context["subdivide"]:
        for item, stiffness, dimensions in zip(
            results, context["consts"], context["sub_dims"]
        ):
            item.update(
                stiffness=stiffness,
                x_mm=dimensions[0],
                y_mm=dimensions[1],
                b_mm=dimensions[2],
                h_mm=dimensions[3],
            )
        subtubes = results
        governing = max(range(len(results)), key=lambda i: results[i]["util"])
    else:
        subtubes = None
        governing = None
    primary = results[0]
    return {"torsion": {
        "tube": primary["tube"],
        "trd_s": primary["trd_s"],
        "trd_max": primary["trd_max"],
        "trd_c": primary["trd_c"],
        "cot": primary["cot"],
        "theta_deg": primary["theta_deg"],
        "t_ed": context["t_ed"],
        "fcd": context["fcd"],
        "fywd": context["fywd_t"],
        "fyd_long": context["fyd_long"],
        "nu": primary["nu"],
        "alpha_cw": context["alpha_cw"],
        "fctd": context["fctd"],
        "fctk_005": context["fctk_005"],
        "gamma_c": context["gamma_c"],
        "gamma_ct": context["gamma_ct"],
        "gamma_s": context["gamma_s"],
        "nu_v_detailing": context["nu_detail_applied"],
        "sigma_cp": context["sigma_cp"],
        "n_prestress": capacity.prestress_axial(inp),
        "asw_t": context["asw_t"],
        "asw_over_s": context["asw_over_s_t"],
        "dia": inp["shear_link_dia"],
        "s": inp["shear_link_s"],
        "cot_min": context["tcot_min"],
        "cot_max": context["tcot_max"],
        "governs": primary["governs"],
        "reason": context["tube"].get("reason"),
        "subdivided": context["subdivide"],
        "compound_detected": context["compound_detected"],
        "subdivision_requested": context["subdivision_requested"],
        "subdivision_valid": context["subdivision_valid"],
        "subdivision_reason": context["subdivision_reason"],
        "valid": True,
        "method": inp["torsion_method"],
        "primary": primary,
        "subtubes": subtubes,
        "trd": sum(item["trd"] for item in results),
        "asl_req": sum(item["asl_req"] for item in results),
        "util": max(item["util"] for item in results),
        "governing_sub": governing,
    }}


def _transverse_result(inp):
    n_comp = -inp["P_pl"] + capacity.prestress_axial(inp)
    contexts = capacity.build_directional_shear_contexts(inp, 0.0, n_comp)
    shear_specs = []
    for component in (key for key in ("vx", "vy") if key in contexts):
        candidates = contexts[component]["candidates"]
        payload, links = candidates[0]
        shear_specs.append({
            "component": component,
            "links_present": inp["shear_links"],
            "links_required": any(
                item[0]["v_ed"] > item[0]["res"]["vrd_c"] + 1.0e-9
                for item in candidates
            ),
            "requirement_clause": "6.2.2",
            "bw_mm": payload["bw"],
            "d_mm": min(item[0]["d"] for item in candidates),
            "legs": links["link_legs"],
            "transverse_leg_spacing_mm": inp[
                "shear_vx_transverse_leg_spacing"
                if component == "vx" else "shear_vy_transverse_leg_spacing"
            ],
            "measurement_axis": "y" if component == "vx" else "x",
        })
    torsion_context = capacity.build_torsion_context(inp, n_comp)
    torsion_specs = [] if torsion_context is None else [{
        "label": "Tube",
        "valid": tube["valid"],
        "reason": tube["reason"],
        "tef_mm": tube["tef"],
        "uk_mm": tube["uk"] * 1000.0,
        "minimum_dimension_mm": tube["minimum_dimension_mm"],
    } for tube in torsion_context["subtubes"]]
    return detailing.transverse_reinforcement(
        edition=inp["detailing_edition"],
        fck_mpa=inp["concrete"].fck,
        fywk_mpa=inp["shear_fywk"],
        diameter_mm=inp["shear_link_dia"],
        spacing_mm=inp["shear_link_s"],
        shear_directions=shear_specs,
        torsion_tubes=torsion_specs,
        ductility_class=inp["transverse_ductility_class"],
        apply_ductility_reduction=False,
        member_type=inp["detailing_member_type"],
    )


def _detail_output(inp):
    return {
        "minimum_reinforcement": detailing.minimum_reinforcement(
            inp["section"], inp["bar_elements"], inp["bar_materials"],
            inp["concrete"], edition=inp["detailing_edition"],
            fctm_mpa=inp["sls_fctm"], n_ed_tension_kn=inp["P_pl"],
            mx_ed_knm=inp["Mx_pl"], my_ed_knm=inp["My_pl"],
            member_type=inp["detailing_member_type"],
            cut_direction=inp["detailing_cut_direction"],
        ),
        "clear_spacing": detailing.clear_spacing(
            inp["bar_elements"], d_upper_mm=inp["detailing_d_upper"],
            edition=inp["detailing_edition"], include_tendons=False,
        ),
        "transverse_reinforcement": _transverse_result(inp),
    }


def _values(calculation):
    return {step.step_id: step.result.value for step in calculation.steps}


def test_result_fixtures_do_not_call_trace_or_candidate_selection():
    source = "\n".join(
        inspect.getsource(item)
        for item in (_shear_output, _torsion_output, _transverse_result)
    )
    for forbidden in (
        "build_shear_trace_family", "build_torsion_trace_family",
        "build_detailing_trace_family", "audit_trace_registry",
        "candidate[\"governing_face\"]", "candidate[\"governing_sub\"]",
    ):
        assert forbidden not in source


def test_directional_shear_matches_independent_2005_hand_oracle():
    inp = _input(torsion_on=False)
    out = _shear_output(inp)
    bundle = build_shear_trace_family(
        inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT,
    )
    assert len(bundle.calculations) == 2
    by_component = {
        dict((axis.name, axis.value) for axis in calculation.axes)["component"]:
        calculation for calculation in bundle.calculations
    }
    vx = _values(by_component["vx"])
    # Independent 2005-family VRd,c calculation for Vx about y.
    d, bw, asl = 270.0, 600.0, 982.0
    k = min(1.0 + math.sqrt(200.0 / d), 2.0)
    rho = min(asl / (bw * d), 0.02)
    gamma_c = inp["concrete"].gamma_c
    basic = 0.18 / gamma_c * k * (100.0 * rho * 35.0) ** (1.0 / 3.0)
    floor = 0.051 / gamma_c * k ** 1.5 * math.sqrt(35.0)
    vrd_c = max(basic, floor) * bw * d / 1000.0
    assert vx["concrete-shear-resistance"] == pytest.approx(vrd_c)
    asw_over_s = 2.0 * math.pi * 10.0 ** 2 / 4.0 / 150.0
    a = asw_over_s * 500.0 / inp["steel"].gamma_y
    b = 600.0 * codes.EC2_2005_DKNA.shear_nu1(35.0) * inp["concrete"].fcd
    expected_cot = min(max(math.sqrt(max(b / a - 1.0, 0.0)), 1.0), 2.5)
    assert vx["shared-cot-theta"] == pytest.approx(expected_cot)
    assert vx["utilisation"] == pytest.approx(
        abs(inp["shear_Vx"]) / vx["governing-resistance"]
    )
    assert vx["verdict"] in {0.0, 1.0}


def test_zero_moment_requires_both_faces_and_2023_remains_project_source():
    inp = _input(
        torsion_on=False,
        shear_Vx=0.0,
        shear_Vy=70.0,
        Mx_pl=0.0,
        My_pl=0.0,
        shear_method=codes.EC2_2023.label,
        concrete=codes.EC2_2023.concrete(35.0),
        steel=codes.EC2_2023.steel(500.0),
        concrete_preset=codes.EC2_2023.label,
        mild_preset=codes.EC2_2023.label,
    )
    inp["bar_materials"] = [inp["steel"]] * 4
    inp["mild_material_catalog"] = {
        "items": [_catalog_item("B500", codes.EC2_2023.label, inp["steel"])]
    }
    bundle = build_shear_trace_family(
        inp, _shear_output(inp), input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
    )
    assert len(bundle.calculations) == 2
    assert {
        dict((axis.name, axis.value) for axis in item.axes)["face"]
        for item in bundle.calculations
    } == {"negative", "positive"}
    method_steps = [
        step for item in bundle.calculations for step in item.steps
        if "published-not-implemented-2023-shear" in step.source.method_id
    ]
    assert method_steps
    assert all(step.source.kind == SOURCE_PROJECT for step in method_steps)
    # Independent 2023-family no-links oracle; the local 2023 route remains a
    # project method even though its retained mechanics are reconstructed here.
    d, bw, asl = 550.0, 300.0, 982.0
    ddg = min(16.0 + inp["shear_dlower"], 40.0)
    rho = asl / (bw * d)
    fyd = 500.0 / inp["steel"].gamma_y
    tau_basic = (0.66 / 1.40) * (
        100.0 * rho * 35.0 * ddg / d
    ) ** (1.0 / 3.0)
    tau_min = (11.0 / 1.40) * math.sqrt(35.0 / fyd * ddg / d)
    expected_vrd = max(tau_basic, tau_min) * bw * (0.9 * d) / 1000.0
    assert all(
        _values(item)["concrete-shear-resistance"]
        == pytest.approx(expected_vrd)
        for item in bundle.calculations
    )


@pytest.mark.parametrize(
    "edition,gamma_ct",
    [(codes.EC2_2005.label, 1.50), (codes.EC2_2005_DKNA.label, 1.70)],
)
def test_torsion_matches_independent_thin_wall_oracle(edition, gamma_ct):
    code = codes.CODES[edition]
    inp = _input(
        shear_on=False,
        torsion_method=edition,
        torsion_gamma_ct=gamma_ct,
        concrete=code.concrete(35.0),
        steel=code.steel(500.0),
        concrete_preset=edition,
        mild_preset=edition,
    )
    bundle = build_torsion_trace_family(
        inp, _torsion_output(inp), input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
    )
    tube = bundle.calculations[0]
    values = _values(tube)
    assert values["tube-area"] == pytest.approx(0.1)
    cot = values["shared-cot-theta"]
    asw_s = math.pi * 10.0 ** 2 / 4.0 / 150.0
    fywd = 500.0 / inp["steel"].gamma_y
    b = code.torsion_nu(35.0, closed_detailing=True) * inp["concrete"].fcd * 100.0
    expected_cot = min(
        max(math.sqrt(max(b / (asw_s * fywd) - 1.0, 0.0)), 1.0),
        2.5,
    )
    assert cot == pytest.approx(expected_cot, abs=1.0e-3)
    trd_s = asw_s * 2.0 * 0.1 * fywd * cot
    nu = code.torsion_nu(35.0, closed_detailing=True)
    trd_max = (
        2.0 * nu * inp["concrete"].fcd * 0.1 * 0.1
        * cot / (1.0 + cot * cot) * 1000.0
    )
    assert values["stirrup-resistance"] == pytest.approx(trd_s)
    assert values["strut-resistance"] == pytest.approx(trd_max)
    assert values["governing-resistance"] == pytest.approx(min(trd_s, trd_max))


def test_subdivided_torsion_order_and_stiffness_shares_come_from_input():
    outer = [
        (-0.15, -0.40), (0.15, -0.40), (0.15, 0.20),
        (0.50, 0.20), (0.50, 0.40), (-0.50, 0.40),
        (-0.50, 0.20), (-0.15, 0.20),
    ]
    bars = _input()["bars"]
    inp = _input(
        shear_on=False,
        outer=outer,
        section=Section.from_polygon(outer, bars),
        torsion_subdivide=True,
        torsion_subrects=[
            (0.0, -100.0, 300.0, 600.0),
            (0.0, 300.0, 1000.0, 200.0),
        ],
    )
    out = _torsion_output(inp)
    bundle = build_torsion_trace_family(
        inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
    )
    assert len(bundle.calculations) == 3
    axes = [dict((axis.name, axis.value) for axis in item.axes)
            for item in bundle.calculations]
    assert [item["order"] for item in axes] == ["1", "2", "3"]
    tube_cots = [
        _values(item)["shared-cot-theta"]
        for item in bundle.calculations[:-1]
    ]
    assert tube_cots == pytest.approx([tube_cots[0]] * 2)
    web, flange = out["torsion"]["subtubes"]
    c_web = 0.6 * 0.3 ** 3 * (
        1.0 / 3.0 - 0.21 * 0.5 * (1.0 - 0.5 ** 4 / 12.0)
    )
    c_flange = 1.0 * 0.2 ** 3 * (
        1.0 / 3.0 - 0.21 * 0.2 * (1.0 - 0.2 ** 4 / 12.0)
    )
    assert web["t_ed"] / flange["t_ed"] == pytest.approx(c_web / c_flange)
    assert out["torsion"]["governing_sub"] == max(
        range(2), key=lambda index: out["torsion"]["subtubes"][index]["util"]
    )


def test_detailing_oracles_cover_longitudinal_clear_and_transverse_methods():
    inp = _input(My_pl=0.0)
    out = _detail_output(inp)
    bundle = build_detailing_trace_family(
        inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT,
    )
    axes = [dict((axis.name, axis.value) for axis in item.axes) for item in bundle.calculations]
    assert {item["subfamily"] for item in axes} == {
        "longitudinal", "clear-spacing", "transverse"
    }
    longitudinal = next(
        item for item in bundle.calculations
        if dict((axis.name, axis.value) for axis in item.axes)["subfamily"]
        == "longitudinal"
    )
    values = _values(longitudinal)
    expected_as = max(0.26 * 3.2 / 500.0, 0.0013) * 300.0 * 550.0
    assert values["as-min-mm2"] == pytest.approx(expected_as)
    clear = [
        item for item in bundle.calculations
        if dict((axis.name, axis.value) for axis in item.axes)["subfamily"]
        == "clear-spacing"
    ]
    assert len(clear) == math.comb(4, 2)
    transverse = [
        item for item in bundle.calculations
        if dict((axis.name, axis.value) for axis in item.axes)["subfamily"]
        == "transverse"
    ]
    assert len(transverse) == 8  # three per shear direction, two for torsion.
    assert all(item.steps[-1].result.state == RESULT_FINITE for item in bundle.calculations)


def test_2023_pure_tension_detailing_uses_force_equilibrium_oracle():
    code = codes.EC2_2023
    steel = code.steel(500.0)
    inp = _input(
        shear_on=False,
        torsion_on=False,
        minimum_reinforcement_on=True,
        clear_spacing_on=False,
        transverse_detailing_on=False,
        detailing_edition=detailing.EC2_2023,
        P_pl=100.0,
        Mx_pl=0.0,
        My_pl=0.0,
        concrete=code.concrete(35.0),
        steel=steel,
        concrete_preset=code.label,
        mild_preset=code.label,
        bar_materials=[steel] * 4,
        mild_material_catalog={
            "items": [_catalog_item("B500", code.label, steel)]
        },
    )
    bundle = build_detailing_trace_family(
        inp,
        _detail_output(inp),
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        context=CONTEXT,
    )
    assert len(bundle.calculations) == 1
    values = _values(bundle.calculations[0])
    expected_demand = 0.3 * 0.6 * inp["sls_fctm"] * 1000.0
    expected_resistance = 4.0 * 491.0e-6 * 500.0 * 1000.0
    assert values["demand-kn"] == pytest.approx(expected_demand)
    assert values["resistance-kn"] == pytest.approx(expected_resistance)
    assert values["utilisation"] == pytest.approx(
        expected_demand / expected_resistance
    )


def test_combined_builder_keeps_all_three_registry_families_independently():
    inp = _input()
    out = {**_shear_output(inp), **_torsion_output(inp), **_detail_output(inp)}
    bundle = build_pr08c_trace_families(
        inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT,
    )
    assert {item.coverage_id for item in bundle.calculations} == {
        "ct-006", "ct-007", "ct-008"
    }


def test_failure_branches_are_minimal_and_publish_no_resistance_or_verdict():
    inp = _input(
        shear_on=False,
        minimum_reinforcement_on=False,
        clear_spacing_on=True,
        transverse_detailing_on=False,
        bar_elements=[{
            "id": "R1", "kind": "bar", "x_mm": 0.0, "y_mm": 0.0,
            "diameter_mm": 20.0, "material_id": "B500",
        }],
    )
    out = {"clear_spacing": detailing.clear_spacing(
        inp["bar_elements"], d_upper_mm=16.0,
        edition=inp["detailing_edition"],
    )}
    bundle = build_detailing_trace_family(
        inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
    )
    calculation = bundle.calculations[0]
    assert calculation.steps[-1].result.state == RESULT_FAILED
    assert not any(
        token in step.step_id
        for step in calculation.steps
        for token in ("resistance", "utilisation", "verdict")
    )
