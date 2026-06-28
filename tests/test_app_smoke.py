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
    at.button(key="load_qs").click().run()   # apply the Quick Section to the points
    at.button(key="calculate").click().run()
    assert not at.exception
    assert "plastic" in at.session_state["results"]


def test_points_are_source_of_truth_until_loaded():
    # The point tables drive the analysis: changing a Quick Section input does
    # nothing until "Load Quick Section into points" is pressed.
    at = _fresh()
    at.run()
    at.button(key="calculate").click().run()
    base_mx = at.session_state["results"]["plastic"]["max_mx"]
    at.number_input(key="h_mm").set_value(1000.0).run()  # taller, but NOT loaded
    at.button(key="calculate").click().run()
    assert at.session_state["results"]["plastic"]["max_mx"] == pytest.approx(base_mx)
    at.button(key="load_qs").click().run()               # apply the Quick Section
    at.button(key="calculate").click().run()
    assert at.session_state["results"]["plastic"]["max_mx"] > base_mx  # deeper -> stronger


def test_point_tables_are_data_only_and_hold_loaded_points():
    # The point tables hold just the coordinate columns (no stored ID -- the plot
    # numbers points by row order); Load Quick Section fills them.
    at = _fresh()
    at.run()
    at.checkbox(key="use_pre").set_value(True).run()
    at.button(key="load_qs").click().run()
    assert list(at.session_state["corners_base"].columns) == ["x (mm)", "y (mm)"]
    assert list(at.session_state["bars_base"].columns) == \
        ["x (mm)", "y (mm)", "area (mm2)"]
    assert len(at.session_state["corners_base"]) >= 3
    assert len(at.session_state["bars_base"]) >= 1
    assert len(at.session_state["tendons_base"]) >= 1


def test_coordinates_are_in_millimetres():
    # Coordinates are entered and stored in mm: the default 400 x 600 mm rectangle
    # (centred) has corners at +/-200 mm and +/-300 mm.
    at = _fresh()
    at.run()
    cb = at.session_state["corners_base"]
    assert list(cb.columns) == ["x (mm)", "y (mm)"]
    assert set(cb["x (mm)"].abs().round().tolist()) == {200.0}
    assert set(cb["y (mm)"].abs().round().tolist()) == {300.0}


def test_clear_section_empties_all_point_tables():
    # The Clear Section button empties every point table -- concrete corners, the
    # void, bars and tendons -- so the section starts blank.
    at = _fresh()
    at.run()
    at.checkbox(key="use_pre").set_value(True).run()   # mount the tendon table too
    at.button(key="load_qs").click().run()             # populate from the template
    assert len(at.session_state["corners_base"]) > 0
    assert len(at.session_state["bars_base"]) > 0
    at.button(key="clear_pts").click().run()
    assert not at.exception
    for base in ("corners_base", "hole_base", "bars_base", "tendons_base"):
        assert len(at.session_state[base]) == 0


def test_cleared_section_does_not_fall_back_to_quick_section():
    # After Clear Section the source-of-truth outline is genuinely empty -- it must
    # not revert to the Quick Section. The Section view and a Calculate run without
    # error, and no results are produced (the section is blank).
    at = _fresh()
    at.run()
    at.button(key="clear_pts").click().run()
    at.selectbox(key="view").set_value("Section").run()
    assert not at.exception
    at.button(key="calculate").click().run()
    assert not at.exception
    assert at.session_state["results"] == {}


def test_blank_and_partial_point_rows_are_skipped():
    # A blank row and a half-typed point (x with no y) and a non-numeric paste are
    # ignored, never crash, and only the complete numeric rows become points.
    import pandas as pd
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.session_state["bars_base"] = pd.DataFrame(
        {"x (mm)": [50.0, None, 150.0, "oops"],   # row 2 blank, row 4 non-numeric
         "y (mm)": [50.0, 50.0, None, 50.0],       # row 3 half-typed (no y)
         "area (mm2)": [491.0, 491.0, 491.0, 491.0]})
    at.button(key="calculate").click().run()
    assert not at.exception
    assert len(at.session_state["results"]["elastic"]["total"]) == 1   # one valid bar


def test_box_girder_void_loads_and_calculates():
    # The box cavity loads into the (data-only) void table and the section still
    # calculates.
    at = _fresh()
    at.run()
    at.selectbox(key="shape").set_value("Box girder").run()
    at.button(key="load_qs").click().run()
    hb = at.session_state["hole_base"]
    assert len(hb) >= 3 and list(hb.columns) == ["x (mm)", "y (mm)"]
    at.button(key="calculate").click().run()
    assert not at.exception
    assert "plastic" in at.session_state["results"]


def _two_void_table():
    import pandas as pd
    # two small triangular voids inside the default (centred) rectangle, separated
    # by a blank row.
    return pd.DataFrame({
        "x (mm)": [-100.0, -40.0, -70.0, None, 40.0, 100.0, 70.0],
        "y (mm)": [-50.0, -50.0, 50.0, None, -50.0, -50.0, 50.0]})


def test_two_voids_separated_by_blank_row():
    # Two voids in one table (a blank row between them) become two holes and the
    # section calculates; the table keeps the six corners and the one separator.
    at = _fresh()
    at.run()
    at.session_state["hole_base"] = _two_void_table()
    at.button(key="calculate").click().run()
    assert not at.exception
    assert "plastic" in at.session_state["results"]
    hb = at.session_state["hole_base"]
    assert len(hb) == 7                                    # 2 voids x 3 + 1 blank
    assert int(hb.isna().any(axis=1).sum()) == 1           # one separator row


def test_remove_void_button_drops_the_last_void():
    at = _fresh()
    at.run()
    at.session_state["hole_base"] = _two_void_table()
    at.run()
    at.button(key="rem_void").click().run()
    assert not at.exception
    hb = at.session_state["hole_base"]
    assert len(hb) == 3                                    # one void left
    assert int(hb.isna().any(axis=1).sum()) == 0           # separator gone


def test_void_buttons_preserve_unsaved_edits():
    # Codex P2: void corners typed into the editor (held in its delta, not yet in
    # the base) must survive a + Add void click, not be discarded.
    import pandas as pd
    at = _fresh()
    at.run()
    # base = one void; an extra corner is held only in the live editor delta.
    at.session_state["hole_base"] = pd.DataFrame({
        "x (mm)": [-100.0, -40.0, -70.0], "y (mm)": [-50.0, -50.0, 50.0]})
    at.session_state["ed_hole"] = {
        "edited_rows": {}, "deleted_rows": [],
        "added_rows": [{"x (mm)": 80.0, "y (mm)": -50.0}]}   # an unsaved corner
    at.button(key="add_void").click().run()   # handler reads the delta before re-render
    assert not at.exception
    hb = at.session_state["hole_base"]
    assert (hb["x (mm)"] == 80.0).any()   # the unsaved corner survived the rebuild


def test_void_cap_enforced_when_parsing_not_only_the_button():
    # Pasting more than the cap of voids must not bypass the limit: the extra
    # voids are ignored when building the holes (Codex P2), with a warning.
    import pandas as pd
    at = _fresh()
    at.run()
    xs, ys = [], []
    for i in range(11):                       # 11 small triangular voids
        if i > 0:
            xs.append(None); ys.append(None)  # blank separator
        xs += [10.0 * i, 10.0 * i + 5.0, 10.0 * i + 2.0]
        ys += [0.0, 0.0, 10.0]
    at.session_state["hole_base"] = pd.DataFrame({"x (mm)": xs, "y (mm)": ys})
    at.run()
    assert not at.exception
    assert any("ignored" in w.value.lower() for w in at.warning)


def test_add_void_button_appends_a_separator():
    import pandas as pd
    at = _fresh()
    at.run()
    at.session_state["hole_base"] = pd.DataFrame({
        "x (mm)": [-100.0, -40.0, -70.0], "y (mm)": [-50.0, -50.0, 50.0]})
    at.run()
    before = len(at.session_state["hole_base"])
    at.button(key="add_void").click().run()
    assert not at.exception
    hb = at.session_state["hole_base"]
    assert len(hb) == before + 1                  # a blank separator row was added
    assert int(hb.isna().any(axis=1).sum()) == 1


def test_void_table_migrates_for_old_sessions():
    # An existing (hot-reloaded) session may have pts_init set but no hole_base;
    # the app must re-create it rather than KeyError (Codex review).
    at = _fresh()
    at.run()
    del at.session_state["hole_base"]
    at.run()
    assert not at.exception
    assert "hole_base" in at.session_state


def test_default_solid_section_has_no_void():
    at = _fresh()
    at.run()
    at.button(key="load_qs").click().run()   # default rectangle, no cavity
    assert len(at.session_state["hole_base"]) == 0


def test_injected_void_changes_the_capacity():
    # A void carved out of the compression zone removes concrete, so the plastic
    # +Mx capacity changes -- the void table drives the section.
    import pandas as pd
    at = _fresh()
    at.run()
    at.button(key="calculate").click().run()
    solid_mx = at.session_state["results"]["plastic"]["max_mx"]
    at.session_state["hole_base"] = pd.DataFrame(
        {"x (mm)": [-150.0, 150.0, 150.0, -150.0],
         "y (mm)": [100.0, 100.0, 280.0, 280.0]})   # void in the (compression) top
    at.run()
    at.button(key="calculate").click().run()
    assert not at.exception
    assert at.session_state["results"]["plastic"]["max_mx"] != pytest.approx(solid_mx)


def test_void_slicing_the_section_is_rejected():
    # A slot reaching across the full width disconnects the concrete: the app flags
    # it and refuses to compute a capacity.
    import pandas as pd
    at = _fresh()
    at.run()
    at.session_state["hole_base"] = pd.DataFrame(
        {"x (mm)": [-250.0, 250.0, 250.0, -250.0],
         "y (mm)": [-20.0, -20.0, 20.0, 20.0]})       # full-width slot at mid-height
    at.run()
    assert any("disconnected" in e.value for e in at.error)
    at.button(key="calculate").click().run()
    assert not at.exception
    assert "plastic" not in at.session_state["results"]


def test_high_grade_concrete_auto_strain_calculates():
    # Above C50/60 the Auto button fills the EC2 Table 3.1 strain limits and the
    # section still calculates (eps_cu2 ~ 2.66 permille at C70).
    at = _fresh()
    at.run()
    at.number_input(key="conc_fck").set_value(70.0).run()
    at.button(key="conc_strain_auto").click().run()
    assert at.session_state["conc_eps_cu2"] == pytest.approx(2.66, abs=0.05)
    assert at.session_state["conc_n"] == pytest.approx(1.44, abs=0.02)
    at.button(key="calculate").click().run()
    assert not at.exception
    assert "plastic" in at.session_state["results"]


def test_invalid_concrete_strain_order_is_recoverable():
    # eps_cu2 < eps_c2 is a valid-in-the-form edit but the law rejects it; the panel
    # must warn and clamp, not abort the run.
    at = _fresh()
    at.run()
    at.number_input(key="conc_eps_c2").set_value(5.0).run()   # peak above eps_cu2 (3.5)
    assert not at.exception
    assert any("eps_cu2 must be at least eps_c2" in w.value for w in at.warning)
    at.button(key="calculate").click().run()
    assert not at.exception
    assert "plastic" in at.session_state["results"]


def test_load_project_restores_section_and_calculates():
    # A pending uploaded project is applied before the widgets are built: the point
    # tables and scalar inputs are restored and the section calculates.
    import json
    at = _fresh()
    at.run()
    project = {
        "format": "sector-project", "version": 1,
        "tables": {
            "corners_base": {"columns": ["x (mm)", "y (mm)"],
                             "rows": [[-100.0, -150.0], [100.0, -150.0],
                                      [100.0, 150.0], [-100.0, 150.0]]},
            "hole_base": {"columns": ["x (mm)", "y (mm)"], "rows": []},
            "bars_base": {"columns": ["x (mm)", "y (mm)", "area (mm2)"],
                          "rows": [[0.0, -120.0, 500.0]]},
            "tendons_base": {"columns": ["x (mm)", "y (mm)", "area (mm2)"], "rows": []},
        },
        "scalars": {"conc_fck": 55.0, "mode": "Plastic"},
    }
    at.session_state["_pending_project"] = json.dumps(project)
    at.run()
    assert not at.exception
    assert at.session_state["conc_fck"] == 55.0
    assert list(at.session_state["corners_base"]["x (mm)"]) == [-100.0, 100.0, 100.0, -100.0]
    at.button(key="calculate").click().run()
    assert not at.exception
    assert "plastic" in at.session_state["results"]


def test_save_load_round_trip_through_the_app():
    # Editing fck, then gathering and re-applying the project, preserves the value.
    import sys as _sys
    at = _fresh()
    at.run()
    at.number_input(key="conc_fck").set_value(48.0).run()
    _sys.path.insert(0, str(pathlib.Path(APP).resolve().parent))
    import project_io  # noqa: E402  (app dir is on sys.path once the app has run)
    text = project_io.dump_project(
        {k: at.session_state[k] for k in project_io.TABLE_KEYS if k in at.session_state},
        {k: at.session_state[k] for k in project_io.SCALAR_KEYS if k in at.session_state})
    assert '"format": "sector-project"' in text
    at.number_input(key="conc_fck").set_value(20.0).run()
    at.session_state["_pending_project"] = text
    at.run()
    assert at.session_state["conc_fck"] == 48.0


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


def test_material_laws_locked_in_elastic_only_mode():
    # In Elastic-only mode the stress-strain laws do not affect the result, so
    # they are disabled -- except fck (feeds fctm) and Es (crack width).
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    for locked in ("conc_gamma_c", "conc_alpha_cc", "mild_fytk", "mild_fyck",
                   "mild_futk", "mild_eut", "mild_gamma_y", "mild_k", "mild_ey0t"):
        assert at.number_input(key=locked).disabled is True, locked
    for editable in ("conc_fck", "mild_Es"):
        assert at.number_input(key=editable).disabled is False, editable


def test_prestress_law_locked_in_elastic_only_mode():
    at = _fresh()
    at.run()
    at.checkbox(key="use_pre").set_value(True).run()
    at.radio(key="mode").set_value("Elastic").run()
    for locked in ("pre_IS", "pre_fytk", "pre_Es", "pre_eut"):
        assert at.number_input(key=locked).disabled is True, locked


def test_material_laws_editable_in_both_and_plastic_modes():
    # Plastic needs the laws, so Both and Plastic keep them editable.
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Both").run()
    assert at.number_input(key="mild_fytk").disabled is False
    assert at.number_input(key="conc_gamma_c").disabled is False
    at.radio(key="mode").set_value("Plastic").run()
    assert at.number_input(key="mild_fytk").disabled is False


def test_fctm_and_ec_locked_in_plastic_only_mode():
    # fctm and Ec only affect the elastic/SLS results, so plastic-only mode
    # disables them; Elastic re-enables them.
    at = _fresh()
    at.run()                                   # default mode is Plastic
    assert at.number_input(key="sls_fctm").disabled is True
    assert at.number_input(key="conc_Ec").disabled is True
    at.radio(key="mode").set_value("Elastic").run()
    assert at.number_input(key="sls_fctm").disabled is False
    assert at.number_input(key="conc_Ec").disabled is False


def test_default_material_preset_is_dk_na_with_550():
    # Defaults to the Danish edition with B550 reinforcement.
    at = _fresh()
    at.run()
    assert at.session_state["conc_preset"] == "DS/EN 1992-1-1:2005 + DK NA:2024"
    assert at.session_state["mild_preset"] == "DS/EN 1992-1-1:2005 + DK NA:2024"
    for f in ("mild_fytk", "mild_fyck", "mild_futk"):
        assert at.number_input(key=f).value == pytest.approx(550.0)


def test_active_in_compression_toggle_changes_plastic_capacity():
    # Switching the reinforcement to tension-only drops the compression bars'
    # contribution, lowering the sagging moment capacity. fyck/ey0c also lock.
    at = _fresh()
    at.run()
    at.button(key="calculate").click().run()
    base = at.session_state["results"]["plastic"]["max_mx"]
    at.checkbox(key="mild_active_comp").set_value(False).run()
    assert at.number_input(key="mild_fyck").disabled is True
    at.button(key="calculate").click().run()
    assert not at.exception
    assert at.session_state["results"]["plastic"]["max_mx"] < base


def test_elastic_calculates_with_locked_materials():
    # Locking the laws must not break the elastic run.
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.button(key="calculate").click().run()
    assert not at.exception
    assert "elastic" in at.session_state["results"]


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
    for key in ("shape", "b_mm", "h_mm", "cover_mm", "conc_fck", "mild_fytk",
                "mild_eut", "pl_P", "pl_Mx", "nl", "view"):
        w = (_widget(at.number_input, key) or _widget(at.selectbox, key)
             or _widget(at.radio, key))
        assert w is not None and w.help, key
    assert at.radio(key="mode").help


def _widget(seq, key):
    for w in seq:
        if w.key == key:
            return w
    return None


def test_label_controls_live_in_the_main_view():
    # The label size and spacing controls are in the main viewport (not the
    # sidebar) and changing them re-renders without error.
    at = _fresh()
    at.run()
    keys = {ni.key for ni in at.number_input}
    assert "label_scale" in keys and "label_min_gap" in keys
    at.number_input(key="label_min_gap").set_value(0.2).run()
    at.number_input(key="label_scale").set_value(1.5).run()
    assert not at.exception


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
    at.number_input(key="h_mm").set_value(750.0).run()  # change an input after calc
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
    at.button(key="load_qs").click().run()   # load the tendons into the points
    at.button(key="calculate").click().run()
    assert not at.exception
    res = at.session_state["results"]
    assert "plastic" in res
    assert res["plastic"]["max_mx"] > mx0


def test_prestress_both_modes_run_with_tendons():
    at = _fresh()
    at.run()
    at.checkbox(key="use_pre").set_value(True).run()
    at.button(key="load_qs").click().run()   # load the tendons into the points
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
    at.button(key="load_qs").click().run()   # load the tendons into the points
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


def test_elastic_reports_cracking_and_section_properties():
    # The elastic analysis always reports the cracking threshold and the
    # transformed section properties (cracked + uncracked when cracked).
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.number_input(key="el_long_Mx").set_value(400.0).run()  # force cracking
    at.button(key="calculate").click().run()
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    assert e["cracked"] is True
    assert 0.0 < e["lambda_cr"] < 1.0
    assert e["show_cw"] is False           # crack width off by default
    assert e["crack"] is None              # crack width is its own opt-in
    assert e["props_un"]["area"] > 0.0 and e["props_un"]["Ix"] > 0.0
    assert e["props_cr"] is not None       # cracked -> cracked properties present
    assert e["props_cr"]["area"] < e["props_un"]["area"]   # cracked section is smaller


def test_crack_width_off_by_default():
    # Crack width is an opt-in: a cracked section reports the threshold and
    # properties but no crack width until the toggle is on.
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.number_input(key="el_long_Mx").set_value(400.0).run()
    at.button(key="calculate").click().run()
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    assert e["show_cw"] is False
    assert e["crack"] is None              # crack width toggle off


def test_crack_width_reports_both_load_cases():
    # The crack-width toggle reports wk for both the long-term and the short-term
    # load, with no cover input (cover is taken from the geometry per bar).
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.number_input(key="el_long_Mx").set_value(400.0).run()
    at.number_input(key="el_short_Mx").set_value(150.0).run()
    at.checkbox(key="sls_cw").set_value(True).run()
    at.button(key="calculate").click().run()
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    assert e["show_cw"] is True
    assert e["crack"] is not None and e["crack"]["wk"] > 0.0
    assert e["crack_short"] is not None and e["crack_short"]["wk"] > 0.0
    # The short-term state carries the extra variable load, so its crack is wider.
    assert e["crack_short"]["wk"] > e["crack"]["wk"]
    assert e["crack"]["cover"] > 0.0       # auto cover from the geometry


def test_short_term_crack_uses_combined_creep_state():
    # With creep (ns != nl) the short-term crack width must come from the combined
    # instantaneous state (total = s2 + RST1), so the governing bar's sigma_s
    # equals the Total steel-stress column -- not a raw (long+short)-at-ns solve.
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.number_input(key="el_long_Mx").set_value(300.0).run()
    at.number_input(key="el_short_Mx").set_value(150.0).run()
    at.number_input(key="nl").set_value(15.0).run()
    at.number_input(key="ns").set_value(6.0).run()      # creep: ns != nl
    at.checkbox(key="sls_cw").set_value(True).run()
    at.button(key="calculate").click().run()
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    cs = e["crack_short"]
    assert cs is not None
    gov = cs["gov_bar"]                                  # 1-based bar index
    assert cs["sigma_s"] == pytest.approx(e["total"][gov - 1], rel=0.02)


def test_bond_coefficient_k1_widens_cracks():
    # k1 (bond) is a user choice the geometry cannot supply: plain round bars
    # (k1 = 1.6) give a wider crack than ribbed / high-bond bars (k1 = 0.8).
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.number_input(key="el_long_Mx").set_value(400.0).run()
    at.checkbox(key="sls_cw").set_value(True).run()
    at.button(key="calculate").click().run()
    wk_ribbed = at.session_state["results"]["elastic"]["crack"]["wk"]
    at.selectbox(key="sls_bond").set_value("Plain round (k1 = 1.6)").run()
    at.button(key="calculate").click().run()
    assert not at.exception
    wk_plain = at.session_state["results"]["elastic"]["crack"]["wk"]
    assert wk_plain > wk_ribbed


def test_crack_width_with_tendons_runs():
    # With prestressing tendons present, the per-bar k1 (tendons fixed at 1.6,
    # folded after the bars) must line up with the section, so the crack-width
    # path runs without a length mismatch.
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.checkbox(key="use_pre").set_value(True).run()
    at.button(key="load_qs").click().run()
    at.number_input(key="el_long_Mx").set_value(400.0).run()
    at.checkbox(key="sls_cw").set_value(True).run()
    at.button(key="calculate").click().run()
    assert not at.exception


def test_dk_na_crack_edition_narrows_wk():
    # Selecting the DK NA crack-width code applies the cover-dependent k3
    # (3.4*(25/c)^(2/3)); for the default cover > 25 mm this narrows wk vs base.
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.number_input(key="el_long_Mx").set_value(400.0).run()
    at.checkbox(key="sls_cw").set_value(True).run()
    at.button(key="calculate").click().run()
    wk_base = at.session_state["results"]["elastic"]["crack"]["wk"]
    at.selectbox(key="sls_code").set_value("DS/EN 1992-1-1 + DK NA").run()
    at.selectbox(key="sls_member").set_value("Slab").run()
    at.button(key="calculate").click().run()
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    assert "DK NA" in e["crack_code"]
    assert e["crack"]["wk"] < wk_base


def test_elastic_uncracked_below_threshold():
    # A small long-term moment leaves the section uncracked: no crack width and
    # no cracked-section properties.
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.number_input(key="el_long_Mx").set_value(5.0).run()
    at.button(key="calculate").click().run()
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    assert e["cracked"] is False
    assert e["crack"] is None
    assert e["props_cr"] is None


def test_elastic_view_renders_with_sls_subsection():
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.number_input(key="el_long_Mx").set_value(400.0).run()
    at.checkbox(key="sls_cw").set_value(True).run()
    at.selectbox(key="view").set_value("Elastic Results").run()
    at.button(key="calculate").click().run()
    assert not at.exception


def test_cracking_follows_the_long_term_load():
    # The SLS checks run on the long-term load: raising it crosses from uncracked
    # to cracked.
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.number_input(key="el_long_Mx").set_value(5.0).run()
    at.button(key="calculate").click().run()
    assert at.session_state["results"]["elastic"]["cracked"] is False
    at.number_input(key="el_long_Mx").set_value(400.0).run()
    at.button(key="calculate").click().run()
    assert at.session_state["results"]["elastic"]["cracked"] is True


def test_plain_elastic_unchanged_by_sls_toggle():
    # The regular cracked-section stresses (zero concrete tension) do not change
    # when the crack-width check is toggled on.
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.number_input(key="el_long_Mx").set_value(400.0).run()
    at.button(key="calculate").click().run()
    base = list(at.session_state["results"]["elastic"]["total"])
    at.checkbox(key="sls_cw").set_value(True).run()
    at.button(key="calculate").click().run()
    assert not at.exception
    assert list(at.session_state["results"]["elastic"]["total"]) == base


def test_fctm_auto_button_tracks_grade():
    # The Auto button recomputes fctm from the current concrete grade (EC2
    # Table 3.1): C50 -> 0.30*50^(2/3) ~ 4.07 MPa.
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.number_input(key="conc_fck").set_value(50.0).run()
    at.button(key="sls_fctm_auto").click().run()
    assert not at.exception
    assert at.number_input(key="sls_fctm").value == pytest.approx(4.07, abs=0.05)


def test_modular_ratios_auto_from_ec():
    # The Auto buttons derive the modular ratios from the concrete Ec: n_s = Es/Ec
    # (~6 for a normal grade) and n_l = Es*(1+phi)/Ec, i.e. (1+phi)*n_s = 3*n_s
    # with the default creep coefficient phi = 2.
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.button(key="conc_Ec_auto").click().run()      # Ec = Ecm for the grade
    at.button(key="ns_auto").click().run()
    at.button(key="nl_auto").click().run()
    assert not at.exception
    ns = at.number_input(key="ns").value
    nl = at.number_input(key="nl").value
    assert 3.5 < ns < 12.0                            # short-term Es/Ec
    assert nl == pytest.approx(3.0 * ns, rel=0.05)    # n_l = (1+phi)*n_s, phi = 2


def test_modular_ratios_default_from_ec_without_buttons():
    # The defaults are now the Ec-derived ratios (not a fixed 15): on first load,
    # without pressing any Auto button, n_s ~ Es/Ec and n_l = (1+phi)*n_s.
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    ns = at.number_input(key="ns").value
    nl = at.number_input(key="nl").value
    assert 3.5 < ns < 12.0
    assert ns != pytest.approx(15.0)                  # not the old fixed default
    assert nl == pytest.approx(3.0 * ns, rel=0.05)


def test_crack_width_auto_cover_circular_section():
    # No cover input: the crack width takes each bar's clear cover from the
    # geometry. A 100 mm ring cover (to centres) on a circular section gives a
    # clear cover near 100 - phi/2 mm, comfortably above 70 mm.
    at = _fresh()
    at.run()
    at.selectbox(key="shape").set_value("Circular").run()
    at.radio(key="mode").set_value("Elastic").run()
    at.number_input(key="ring_c_mm").set_value(100.0).run()
    at.button(key="load_qs").click().run()        # apply the ring to the points
    at.number_input(key="el_long_Mx").set_value(400.0).run()  # force cracking
    at.checkbox(key="sls_cw").set_value(True).run()
    at.button(key="calculate").click().run()
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    if e["crack"] is not None:
        assert e["crack"]["cover"] > 70.0
