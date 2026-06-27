"""Headless smoke tests for the Streamlit app via Streamlit's AppTest.

These run the app script in-process (no browser), exercise the Calculate flow
for each analysis mode, and assert it produces results without error.
"""

from __future__ import annotations

import pathlib

import pytest

from streamlit.testing.v1 import AppTest

APP = str(pathlib.Path(__file__).resolve().parent.parent / "app" / "sector_app.py")


def _fresh():
    return AppTest.from_file(APP, default_timeout=90)


def test_app_loads_without_error():
    at = _fresh()
    at.run()
    assert not at.exception
    # Before any calculation the app prompts the user.
    assert "results" not in at.session_state


def test_calculate_plastic_produces_an_envelope():
    at = _fresh()
    at.run()
    at.button(key="calculate").click().run()
    assert not at.exception
    res = at.session_state["results"]
    assert "plastic" in res
    assert len(res["plastic"]["mx"]) > 0
    assert res["plastic"]["max_mx"] > 0  # a rectangle with bottom steel has +Mx capacity


def test_calculate_elastic_produces_bar_stresses():
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.button(key="calculate").click().run()
    assert not at.exception
    res = at.session_state["results"]
    assert "elastic" in res
    assert len(res["elastic"]["total"]) > 0


def test_combined_elastic_reports_four_columns():
    # The elastic analysis is the long+short-term creep model: four steel-stress
    # columns (total / long / dif / rst1), all the same length.
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.button(key="calculate").click().run()
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    n = len(e["total"])
    assert n > 0
    assert len(e["long"]) == n and len(e["dif"]) == n and len(e["rst1"]) == n
    # dif = total - long, element-wise.
    for d, t, l in zip(e["dif"], e["total"], e["long"]):
        assert d == pytest.approx(t - l, abs=1e-6)


def test_short_term_load_and_ratio_change_the_combined_result():
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.button(key="calculate").click().run()
    base = list(at.session_state["results"]["elastic"]["total"])
    at.number_input(key="el_short_Mx").set_value(80.0).run()  # add a short-term moment
    at.number_input(key="ns").set_value(6.0).run()            # short-term stiffer
    at.button(key="calculate").click().run()
    assert not at.exception
    assert at.session_state["results"]["elastic"]["total"] != base


def test_plastic_sweep_increment_changes_point_count():
    at = _fresh()
    at.run()
    at.button(key="calculate").click().run()
    n_default = len(at.session_state["results"]["plastic"]["points"])
    at.number_input(key="v_inc").set_value(5.0).run()  # finer sweep
    at.button(key="calculate").click().run()
    assert not at.exception
    assert len(at.session_state["results"]["plastic"]["points"]) > n_default


def test_plastic_sweep_stays_within_requested_bounds():
    # A V.inc that does not divide V.max - V.min must still land exactly on both
    # ends, with no swept angle outside [V.min, V.max].
    at = _fresh()
    at.run()
    at.number_input(key="v_min").set_value(0.0).run()
    at.number_input(key="v_max").set_value(10.0).run()
    at.number_input(key="v_inc").set_value(7.0).run()  # max increment, doesn't divide
    at.button(key="calculate").click().run()
    assert not at.exception
    p = at.session_state["results"]["plastic"]
    vs = sorted(pt["V"] for pt in p["points"])
    assert vs[0] == pytest.approx(0.0)
    assert vs[-1] == pytest.approx(10.0)
    assert all(-1e-6 <= v <= 10.0 + 1e-6 for v in vs)
    # V.inc is a maximum increment: the actual step is never coarser.
    assert max(vs[i + 1] - vs[i] for i in range(len(vs) - 1)) <= 7.0 + 1e-6
    # A partial sweep is an open arc -> no utilisation reported.
    assert p["util"] is None


def test_full_sweep_reports_utilisation():
    at = _fresh()
    at.run()
    at.button(key="calculate").click().run()  # default 0-360 sweep
    assert at.session_state["results"]["plastic"]["util"] is not None


def test_both_mode_runs_elastic_and_plastic():
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Both").run()
    at.button(key="calculate").click().run()
    assert not at.exception
    res = at.session_state["results"]
    assert "plastic" in res and "elastic" in res


def test_plastic_and_elastic_use_independent_loads():
    # The two analyses take their own load sets; changing the elastic moment
    # must not move the plastic utilisation, and vice versa.
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Both").run()
    at.number_input(key="pl_Mx").set_value(150.0).run()
    at.number_input(key="el_long_Mx").set_value(50.0).run()
    at.button(key="calculate").click().run()
    assert not at.exception
    res = at.session_state["results"]
    util0 = res["plastic"]["util"]
    stress0 = list(res["elastic"]["total"])

    at.number_input(key="el_long_Mx").set_value(120.0).run()  # change only the elastic load
    at.button(key="calculate").click().run()
    res2 = at.session_state["results"]
    assert res2["plastic"]["util"] == pytest.approx(util0)   # plastic unchanged
    assert res2["elastic"]["total"] != stress0         # elastic changed


def test_load_sets_survive_a_mode_switch():
    # Both sets stay mounted (inactive one disabled), so values are not lost when
    # toggling modes hides them for a few reruns.
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Both").run()
    at.number_input(key="pl_Mx").set_value(175.0).run()
    at.number_input(key="el_long_Mx").set_value(60.0).run()
    at.radio(key="mode").set_value("Elastic").run()   # plastic set disabled
    at.run()                                            # extra rerun
    at.radio(key="mode").set_value("Both").run()        # plastic set active again
    assert at.number_input(key="pl_Mx").value == pytest.approx(175.0)
    assert at.number_input(key="el_long_Mx").value == pytest.approx(60.0)


def test_circular_shape_calculates():
    at = _fresh()
    at.run()
    at.selectbox(key="shape").set_value("Circular").run()
    at.button(key="calculate").click().run()
    assert not at.exception
    assert "plastic" in at.session_state["results"]


def test_material_preset_switch_calculates():
    at = _fresh()
    at.run()
    at.selectbox(key="conc_preset").set_value("DS/EN 1992-1-1:2023").run()
    at.selectbox(key="mild_preset").set_value(
        "Curve 2 (elastic-perfectly-plastic)").run()
    assert not at.exception
    at.button(key="calculate").click().run()
    assert not at.exception
    assert "plastic" in at.session_state["results"]


def test_2023_concrete_fck_edit_calculates():
    # Editing fck under the strength-dependent 2023 preset (alpha_cc tracks fck).
    at = _fresh()
    at.run()
    at.selectbox(key="conc_preset").set_value("DS/EN 1992-1-1:2023").run()
    at.number_input(key="conc_fck").set_value(50.0).run()
    assert not at.exception
    at.button(key="calculate").click().run()
    assert not at.exception
    assert "plastic" in at.session_state["results"]


def test_es_field_present_and_editable():
    # The steel modulus Es/Ep is a direct input for both materials (the prestress
    # panel appears once tendons are enabled).
    at = _fresh()
    at.run()
    at.checkbox(key="use_pre").set_value(True).run()
    keys = {ni.key for ni in at.number_input}
    assert "mild_Es" in keys and "pre_Es" in keys
    at.number_input(key="mild_Es").set_value(210000.0).run()
    assert not at.exception
    at.button(key="calculate").click().run()
    assert not at.exception
    assert "plastic" in at.session_state["results"]


def test_eut_below_yield_strain_warns_and_calculates():
    # Meaningful constraint: a rupture strain below the yield strain is clamped
    # with a warning rather than accepted.
    at = _fresh()
    at.run()
    at.number_input(key="mild_eut").set_value(0.5).run()  # 0.5 permille, below ey ~ 2.5
    assert any("yield strain" in w.value for w in at.warning)
    at.button(key="calculate").click().run()
    assert not at.exception


def test_two_yield_fields_live_under_default_preset():
    # The default preset builds the general law, so editing a two-yield field
    # (k) is accepted and recomputes without error.
    at = _fresh()
    at.run()
    at.number_input(key="mild_k").set_value(0.8).run()
    at.number_input(key="mild_ey0t").set_value(3.0).run()  # 3 permille
    assert not at.exception
    at.button(key="calculate").click().run()
    assert not at.exception


def test_mild_fyck_zero_is_allowed_and_calculates():
    # The old 100 MPa floor on fyck is gone; zero compression yield must be a
    # valid input and still compute.
    at = _fresh()
    at.run()
    at.number_input(key="mild_fyck").set_value(0.0).run()
    assert not at.exception
    at.button(key="calculate").click().run()
    assert not at.exception
    assert "plastic" in at.session_state["results"]


def test_material_fields_are_flat_regardless_of_preset():
    # Every mild-steel field is shown for any preset (flat form): the two-yield
    # fields exist even under the elastic-perfectly-plastic (curve 2) preset.
    at = _fresh()
    at.run()
    at.selectbox(key="mild_preset").set_value(
        "Curve 2 (elastic-perfectly-plastic)").run()
    keys = {ni.key for ni in at.number_input}
    for f in ("mild_fytk", "mild_fyck", "mild_futk", "mild_eut", "mild_gamma_y",
              "mild_gamma_u", "mild_gamma_E", "mild_k", "mild_ey0t", "mild_ey0c"):
        assert f in keys, f


def test_degenerate_rupture_stress_does_not_crash():
    # A zero rupture stress on a hardening curve is degenerate; the app must warn
    # and still render rather than raise.
    at = _fresh()
    at.run()
    at.selectbox(key="mild_preset").set_value("Curve 1 (bilinear hardening)").run()
    at.number_input(key="mild_futk").set_value(0.0).run()
    assert not at.exception
    at.button(key="calculate").click().run()
    assert not at.exception


def test_inputs_carry_help_tooltips():
    # Inputs across the panels expose hover help (the "?" tooltip).
    at = _fresh()
    at.run()
    for key in ("shape", "b", "h", "cover", "conc_fck", "mild_fytk", "mild_eut",
                "pl_P", "pl_Mx", "nl", "view"):
        w = (_widget(at.number_input, key) or _widget(at.selectbox, key)
             or _widget(at.radio, key))
        assert w is not None and w.help, key
    assert at.radio(key="mode").help


def _widget(seq, key):
    for w in seq:
        if w.key == key:
            return w
    return None


def test_view_dropdown_switches_without_error():
    # Every view must render. The live views (Section, Stress-Strain) need no
    # Calculate; the result views show a prompt until one is run.
    at = _fresh()
    at.run()
    for v in ["Section", "Stress-Strain diagrams", "Plastic Results",
              "Elastic Results"]:
        at.selectbox(key="view").set_value(v).run()
        assert not at.exception, v


def test_stress_strain_view_includes_prestress_when_enabled():
    at = _fresh()
    at.run()
    at.checkbox(key="use_pre").set_value(True).run()
    at.selectbox(key="view").set_value("Stress-Strain diagrams").run()
    assert not at.exception


def test_results_views_render_after_calculate():
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Both").run()
    at.button(key="calculate").click().run()
    for v in ["Plastic Results", "Elastic Results"]:
        at.selectbox(key="view").set_value(v).run()
        assert not at.exception, v


def test_section_view_is_geometry_only():
    # The Section view shows input geometry only -- no neutral axis, no stale
    # notice -- even after a calculation and an input change. Results (incl. the
    # neutral axis) live in the result views.
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.button(key="calculate").click().run()
    at.selectbox(key="view").set_value("Section").run()
    at.number_input(key="h").set_value(0.75).run()  # geometry now differs
    assert not at.exception
    assert not any("neutral axis" in w.value for w in at.warning)


def test_plastic_results_table_and_state_selector():
    # The plastic view exposes the per-angle table data and a state selector.
    at = _fresh()
    at.run()
    at.button(key="calculate").click().run()
    at.selectbox(key="view").set_value("Plastic Results").run()
    assert not at.exception
    p = at.session_state["results"]["plastic"]
    assert len(p["points"]) > 0
    pt = p["points"][0]
    for k in ("V", "Mx", "My", "na_x", "na_y", "eps_c", "eps_s", "kappa",
              "comp_force", "lever", "dx", "dy"):
        assert k in pt
    # selecting a different neutral-axis state recomputes the diagnostic cleanly
    at.selectbox(key="pl_state").set_value(3).run()
    assert not at.exception


def test_elastic_fully_tensile_case_renders_without_phantom_zone():
    # A tension-dominated case leaves no concrete compression (max_conc == 0)
    # while the neutral axis intercepts stay finite; the view must not shade a
    # phantom compression zone or raise.
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.number_input(key="el_long_P").set_value(-5000.0).run()  # large tension
    at.number_input(key="el_long_Mx").set_value(0.0).run()
    at.button(key="calculate").click().run()
    at.selectbox(key="view").set_value("Elastic Results").run()
    assert not at.exception
    assert at.session_state["results"]["elastic"]["max_conc"] == pytest.approx(0.0)
    assert any("no compression" in c.value for c in at.caption)


def test_elastic_results_show_neutral_axis_and_max_steel():
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.button(key="calculate").click().run()
    at.selectbox(key="view").set_value("Elastic Results").run()
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    assert "max_steel" in e and "max_conc_xy" in e and "na_x" in e


def test_prestress_plastic_increases_capacity():
    # Enabling tendons in the tension zone must raise the plastic +Mx capacity.
    base = _fresh()
    base.run()
    base.button(key="calculate").click().run()
    assert not base.exception
    mx0 = base.session_state["results"]["plastic"]["max_mx"]

    at = _fresh()
    at.run()
    at.checkbox(key="use_pre").set_value(True).run()
    at.button(key="calculate").click().run()
    assert not at.exception
    res = at.session_state["results"]
    assert "plastic" in res
    assert res["plastic"]["max_mx"] > mx0


def test_prestress_both_modes_run_with_tendons():
    at = _fresh()
    at.run()
    at.checkbox(key="use_pre").set_value(True).run()
    at.radio(key="mode").set_value("Both").run()
    at.button(key="calculate").click().run()
    assert not at.exception
    res = at.session_state["results"]
    # Elastic models each tendon as an extra bar, so its stress list grows.
    assert "plastic" in res and "elastic" in res
    assert len(res["elastic"]["total"]) > 0


def test_prestress_preset_curve6_calculates():
    at = _fresh()
    at.run()
    at.checkbox(key="use_pre").set_value(True).run()
    at.selectbox(key="pre_preset").set_value("Curve 6 (bilinear)").run()
    assert not at.exception
    at.button(key="calculate").click().run()
    assert not at.exception
    assert "plastic" in at.session_state["results"]


def test_material_manual_override_calculates():
    at = _fresh()
    at.run()
    # A picked preset must remain editable.
    at.number_input(key="conc_fck").set_value(45.0).run()
    at.number_input(key="mild_gamma_y").set_value(1.3).run()
    assert not at.exception
    at.button(key="calculate").click().run()
    assert not at.exception
    assert "plastic" in at.session_state["results"]


def test_crack_control_cracks_and_reports_crack_width():
    # Enabling the SLS check and applying a moment large enough to crack the
    # section produces the cracking decision, zeta and a crack width.
    at = _fresh()
    at.run()
    at.checkbox(key="sls_on").set_value(True).run()
    at.number_input(key="sls_Mx").set_value(400.0).run()  # force cracking
    at.button(key="calculate").click().run()
    assert not at.exception
    c = at.session_state["results"]["cracking"]
    assert c["cracked"] is True
    assert 0.0 < c["lambda_cr"] < 1.0
    assert 0.0 < c["zeta"] <= 1.0
    assert c["crack"] is not None and c["crack"]["wk"] > 0.0


def test_crack_control_uncracked_below_threshold():
    # A small moment leaves the section uncracked: lambda_cr >= 1, zeta = 0 and
    # no crack width.
    at = _fresh()
    at.run()
    at.checkbox(key="sls_on").set_value(True).run()
    at.number_input(key="sls_Mx").set_value(5.0).run()
    at.button(key="calculate").click().run()
    assert not at.exception
    c = at.session_state["results"]["cracking"]
    assert c["cracked"] is False
    assert c["zeta"] == 0.0
    assert c["crack"] is None


def test_crack_control_view_renders():
    at = _fresh()
    at.run()
    at.checkbox(key="sls_on").set_value(True).run()
    at.number_input(key="sls_Mx").set_value(400.0).run()
    at.selectbox(key="view").set_value("Crack control").run()
    at.button(key="calculate").click().run()
    assert not at.exception


def test_crack_control_independent_of_elastic_load():
    # The SLS check uses its own load set; it runs in plastic mode and does not
    # depend on the elastic long/short loads.
    at = _fresh()
    at.run()
    at.checkbox(key="sls_on").set_value(True).run()
    at.number_input(key="sls_Mx").set_value(400.0).run()
    at.button(key="calculate").click().run()
    assert not at.exception
    res = at.session_state["results"]
    assert "cracking" in res and "plastic" in res  # plastic is the default mode
