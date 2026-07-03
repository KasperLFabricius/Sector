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


def _open_qs(at):
    """Open the full-width Quick Section builder so its widgets render."""
    at.session_state["_qs_open"] = True
    at.run()
    return at


def _apply_qs(at):
    """Apply the builder to the point tables and return to the analysis layout."""
    at.button(key="qs_apply").click().run()
    return at


def test_app_loads_without_error():
    at = _fresh()
    at.run()
    assert not at.exception
    # Before any calculation the app prompts the user.
    assert "results" not in at.session_state


def test_live_curve_figures_are_memoised():
    # The Stress-Strain curve figures are rebuilt only when a material actually
    # changes -- an unrelated rerun reuses the cached figure (perf: skip the
    # ~20 ms plotly construction).
    at = _fresh()
    at.run()
    at.selectbox(key="view").set_value("Stress-Strain diagrams").run()
    conc_id = id(at.session_state["_fig_cache"]["concrete"][1])
    at.number_input(key="el_phi").set_value(2.0).run()     # unrelated to the concrete law
    assert id(at.session_state["_fig_cache"]["concrete"][1]) == conc_id     # reused
    at.number_input(key="conc_fck").set_value(45.0).run()  # changes the concrete law
    assert id(at.session_state["_fig_cache"]["concrete"][1]) != conc_id     # rebuilt


def test_about_panel_shows_version_and_author():
    # The About panel carries the single-source version plus the author/email block.
    at = _fresh()
    at.run()
    blob = " | ".join(m.value for m in at.markdown) + \
        " | ".join(c.value for c in at.caption)
    from sector import __version__ as version   # single source; no per-bump edit
    assert version in blob and f"v{version}" in (at.title[0].value if at.title else "")
    assert "Kasper Lindskov Fabricius" in blob
    assert "Kasper.LindskovFabricius@sweco.dk" in blob


def test_calculate_plastic_produces_an_envelope():
    at = _fresh()
    at.run()
    at.button(key="calculate").click().run()
    assert not at.exception
    res = at.session_state["results"]
    assert "plastic" in res
    assert len(res["plastic"]["mx"]) > 0
    assert res["plastic"]["max_mx"] > 0  # a rectangle with bottom steel has +Mx capacity
    # Both extremes are reported for each axis (Max and Min), and the min never
    # exceeds the max.
    pl = res["plastic"]
    assert pl["min_mx"] <= pl["max_mx"] and pl["min_my"] <= pl["max_my"]


def test_plastic_view_tolerates_legacy_results_without_min_fields():
    # A result payload cached before min_mx/min_my existed (inputs unchanged, so no
    # recompute) must still render the Plastic Results view: the minima are derived
    # from the envelope rather than raising a KeyError.
    at = _fresh()
    at.run()
    at.button(key="calculate").click().run()
    at.session_state["results"]["plastic"].pop("min_mx", None)
    at.session_state["results"]["plastic"].pop("min_my", None)
    at.selectbox(key="view").set_value("Plastic Results").run()
    assert not at.exception


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
    at.number_input(key="conc_Ec").set_value(25.0).run()      # softer concrete -> larger n_s/n_l
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


def test_nm_interaction_is_opt_in_and_renders():
    at = _fresh()
    at.run()
    # Off by default: the N-M view prompts to enable it, and no interaction is computed.
    at.selectbox(key="view").set_value("N-M Interaction").run()
    at.button(key="calculate").click().run()
    assert not at.exception
    assert "interaction" not in at.session_state["results"]["plastic"]
    assert any("N-M interaction" in m.value for m in at.info)
    # Enable it -> Calculate traces the diagram and the view renders it.
    at.checkbox(key="pl_interaction").set_value(True).run()
    at.button(key="calculate").click().run()
    assert not at.exception
    d = at.session_state["results"]["plastic"]["interaction"]
    assert d["axis"] == "x" and len(d["N"]) == len(d["M"]) > 10
    assert min(d["N"]) < 0.0 < max(d["N"])              # tension to squash
    assert not any("Enable 'N-M interaction" in m.value for m in at.info)  # view rendered
    assert any("Squash load" in mt.label for mt in at.metric)              # its metrics show


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


def test_recalculate_reuses_the_unchanged_analysis_half():
    # The staleness signature is split, so a Both-mode Calculate recomputes only the
    # half whose inputs changed and reuses the other (same result object).
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Both").run()
    at.button(key="calculate").click().run()
    pl1 = at.session_state["results"]["plastic"]
    el1 = at.session_state["results"]["elastic"]

    # Elastic-only change -> plastic reused (identity), elastic recomputed.
    at.number_input(key="el_short_Mx").set_value(123.0).run()
    at.button(key="calculate").click().run()
    res = at.session_state["results"]
    assert res["plastic"] is pl1
    assert res["elastic"] is not el1
    el2 = res["elastic"]

    # Plastic-only change (sweep increment) -> elastic reused, plastic recomputed.
    at.number_input(key="v_inc").set_value(30.0).run()
    at.button(key="calculate").click().run()
    res = at.session_state["results"]
    assert res["elastic"] is el2
    assert res["plastic"] is not pl1

    # Shared change (concrete grade) -> both recomputed.
    pl3 = res["plastic"]
    at.number_input(key="conc_fck").set_value(40.0).run()
    at.button(key="calculate").click().run()
    res = at.session_state["results"]
    assert res["plastic"] is not pl3
    assert res["elastic"] is not el2


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
    _open_qs(at)
    at.selectbox(key="shape").set_value("Circular").run()
    _apply_qs(at)                            # apply the builder to the points
    at.button(key="calculate").click().run()
    assert not at.exception
    assert "plastic" in at.session_state["results"]


def test_builder_does_not_touch_points_until_applied():
    # The point tables drive the analysis; the Quick Section builder only writes to
    # them on Apply. Opening it, changing a dimension and pressing Back changes
    # nothing; Apply does.
    at = _fresh()
    at.run()
    at.button(key="calculate").click().run()
    base_mx = at.session_state["results"]["plastic"]["max_mx"]
    _open_qs(at)
    at.number_input(key="h_mm").set_value(1000.0).run()  # taller...
    at.button(key="qs_back").click().run()               # ...but discarded
    at.button(key="calculate").click().run()
    assert at.session_state["results"]["plastic"]["max_mx"] == pytest.approx(base_mx)
    _open_qs(at)
    at.number_input(key="h_mm").set_value(1000.0).run()
    at.button(key="qs_apply").click().run()              # now applied
    at.button(key="calculate").click().run()
    assert at.session_state["results"]["plastic"]["max_mx"] > base_mx  # deeper -> stronger


def test_qs_interleave_places_a_second_bar_size_at_the_midpoints():
    import sector_app
    from sector.templates import bar_area
    row = [(-0.15, -0.25, bar_area(20)), (-0.05, -0.25, bar_area(20)),
           (0.05, -0.25, bar_area(20)), (0.15, -0.25, bar_area(20))]
    out = sector_app._qs_interleave(row, "16")
    xs = sorted(x for x, _y, _a in out)
    assert xs == pytest.approx([-0.10, 0.0, 0.10])              # 3 gap midpoints
    assert all(y == pytest.approx(-0.25) for _x, y, _a in out)  # same layer
    assert all(a == pytest.approx(bar_area(16)) for *_xy, a in out)  # the second size


def test_quick_section_interleaves_a_second_bar_size():
    # The Quick Section can place a second bar size interleaved at the midpoints of a
    # face row, so a section carries e.g. Y20/100 and Y16 in the same bottom layer.
    at = _fresh()
    at.run()
    # A plain apply (no interleave) -> a single bar size at the bottom face.
    _open_qs(at)
    _apply_qs(at)
    plain = len(at.session_state["bars_base"])
    # With a bottom interleave -> more bars, and two distinct bar sizes present.
    _open_qs(at)
    at.selectbox(key="bot_off_d").set_value("16").run()
    _apply_qs(at)
    bars = at.session_state["bars_base"]
    areas = {round(float(a), 1) for a in bars["area (mm2)"]}
    assert len(bars) > plain                               # extra interleaved bars added
    assert len(areas) >= 2                                 # two bar sizes now present


def test_quick_section_builder_places_bars_by_spacing():
    # The builder opens full-width, places slab bars at a target spacing, and Apply
    # writes the generated points into the tables (which then analyse).
    at = _fresh()
    at.run()
    _open_qs(at)
    assert any(b.key == "qs_apply" for b in at.button)    # the builder is showing
    at.selectbox(key="shape").set_value("Slab strip").run()
    at.radio(key="qs_rebar_mode").set_value("By spacing").run()
    at.number_input(key="bot_s").set_value(150.0).run()
    at.number_input(key="top_s").set_value(150.0).run()
    _apply_qs(at)
    assert not at.exception
    # 1 m slab, 50 mm cover -> a 0.9 m face at 150 mm gives 7 bars per row (14 total).
    assert len(at.session_state["bars_base"]) == 14
    at.button(key="calculate").click().run()
    assert not at.exception


def test_quick_section_builder_stacks_multiple_bar_layers():
    # Two bottom layers stack the 6 bottom bars at two y-levels (12), plus the 2 top
    # bars = 14; the second layer sits one layer-spacing above the bottom cover line.
    at = _fresh()
    at.run()
    _open_qs(at)
    at.number_input(key="bot_layers").set_value(2).run()
    at.number_input(key="layer_s").set_value(60.0).run()
    _apply_qs(at)
    assert not at.exception
    bars = at.session_state["bars_base"]
    assert len(bars) == 14                          # 2 x 6 bottom + 1 x 2 top
    ys = sorted(round(float(y), 1) for y in set(bars["y (mm)"]))
    # 600 mm section, 50 mm cover: bottom rows at -250 and -190 mm, top at 250 mm.
    assert ys == [-250.0, -190.0, 250.0]
    at.button(key="calculate").click().run()
    assert not at.exception


def test_quick_section_builder_stacks_tendon_layers():
    # Two tendon layers place the tendons at two y-levels stacked up from the bottom.
    at = _fresh()
    at.run()
    _open_qs(at)
    at.number_input(key="tnd_n").set_value(3).run()
    at.number_input(key="tnd_layers").set_value(2).run()
    at.number_input(key="tnd_layer_s").set_value(60.0).run()
    _apply_qs(at)
    assert not at.exception
    tendons = at.session_state["tendons_base"]
    assert len(tendons) == 6                          # 2 layers x 3 tendons
    ys = sorted(round(float(y), 1) for y in set(tendons["y (mm)"]))
    # 100 mm tendon cover from the -300 mm bottom face -> -200, then +60 -> -140.
    assert ys == [-200.0, -140.0]
    at.button(key="calculate").click().run()
    assert not at.exception


def test_quick_section_box_tendon_layer_splits_into_walls():
    # A box girder tendon layer that rises into the hollow is split into the side
    # walls, preserving the count, rather than placing a tendon in the cavity (the
    # alternative to dropping). Defaults: 800x1000x200 box, 100 mm cover; layer 2
    # (150 mm up, y=-250) is in the hollow.
    at = _fresh()
    at.run()
    _open_qs(at)
    at.selectbox(key="shape").set_value("Box girder").run()
    at.number_input(key="tnd_n").set_value(3).run()
    at.number_input(key="tnd_layers").set_value(2).run()
    at.number_input(key="tnd_layer_s").set_value(150.0).run()
    _apply_qs(at)
    assert not at.exception
    tendons = at.session_state["tendons_base"]
    assert len(tendons) == 6                          # count preserved (3 per layer)
    assert not any("within the concrete" in (e.value or "") for e in at.error)
    hollow = tendons[(tendons["y (mm)"] > -260) & (tendons["y (mm)"] < -240)]
    assert len(hollow) == 3                           # the hollow layer keeps its 3
    assert (hollow["x (mm)"].abs() >= 200).all()      # in the side walls, not the cavity
    at.button(key="calculate").click().run()
    assert not at.exception
    assert "plastic" in at.session_state["results"]


def test_quick_section_circular_zero_cover_keeps_all_bars():
    # At zero cover the ring radius is capped at the polygon apothem, so every bar
    # stays inside the N-gon outline and none are dropped/rejected (Codex P2).
    at = _fresh()
    at.run()
    _open_qs(at)
    at.selectbox(key="shape").set_value("Circular").run()
    at.number_input(key="ring_n").set_value(10).run()
    at.number_input(key="ring_c_mm").set_value(0.0).run()
    _apply_qs(at)
    assert not at.exception
    assert len(at.session_state["bars_base"]) == 10            # all 10 placed
    assert not any("within the concrete" in (e.value or "") for e in at.error)
    at.button(key="calculate").click().run()
    assert not at.exception
    assert "plastic" in at.session_state["results"]


def test_quick_section_tsection_lower_top_layer_fits_the_web():
    # A T-section's top face is the flange; a lower top layer pushed below the flange
    # must narrow to the web, or it would sit outside the concrete and be rejected.
    at = _fresh()
    at.run()
    _open_qs(at)
    at.selectbox(key="shape").set_value("T-section").run()
    at.number_input(key="top_layers").set_value(2).run()
    at.number_input(key="layer_s").set_value(250.0).run()   # pushes layer 2 into the web
    _apply_qs(at)
    assert not at.exception
    assert not any("within the concrete" in (e.value or "") for e in at.error)
    bars = at.session_state["bars_base"]
    lower_top = bars[(bars["y (mm)"] > 50) & (bars["y (mm)"] < 150)]   # the y=100 mm row
    assert len(lower_top) >= 1
    assert lower_top["x (mm)"].abs().max() <= 110           # within the web (bw/2 - cover)
    at.button(key="calculate").click().run()
    assert not at.exception
    assert "plastic" in at.session_state["results"]


def test_quick_section_tsection_spaced_web_layer_has_fewer_bars():
    # By spacing, a T-section top layer narrowed to the web keeps the target spacing,
    # so it has far fewer bars than the flange row (not the flange count crammed in).
    at = _fresh()
    at.run()
    _open_qs(at)
    at.selectbox(key="shape").set_value("T-section").run()
    at.radio(key="qs_rebar_mode").set_value("By spacing").run()
    at.number_input(key="top_s").set_value(150.0).run()
    at.number_input(key="top_layers").set_value(2).run()
    at.number_input(key="layer_s").set_value(250.0).run()       # lower row into the web
    _apply_qs(at)
    assert not at.exception
    assert not any("within the concrete" in (e.value or "") for e in at.error)
    bars = at.session_state["bars_base"]
    flange_row = bars[(bars["y (mm)"] > 300) & (bars["y (mm)"] < 360)]   # y=350, flange
    web_row = bars[(bars["y (mm)"] > 50) & (bars["y (mm)"] < 150)]       # y=100, web
    assert 0 < len(web_row) < len(flange_row)
    assert web_row["x (mm)"].abs().max() <= 110                  # stays in the web


def test_builder_settings_persist_between_openings():
    # The builder widgets are dropped while it is closed, so the settings are
    # mirrored to durable keys: reopening restores the last shape and dimensions.
    at = _fresh()
    at.run()
    _open_qs(at)
    at.selectbox(key="shape").set_value("T-section").run()
    at.number_input(key="bf_mm").set_value(1500.0).run()
    at.button(key="qs_back").click().run()                # close (settings kept)
    _open_qs(at)
    assert at.selectbox(key="shape").value == "T-section"
    assert at.number_input(key="bf_mm").value == pytest.approx(1500.0)


def test_point_tables_are_data_only_and_hold_loaded_points():
    # The point tables hold just the coordinate columns (no stored ID -- the plot
    # numbers points by row order); the builder Apply fills them.
    at = _fresh()
    at.run()
    _open_qs(at)
    at.number_input(key="tnd_n").set_value(4).run()
    _apply_qs(at)
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
    _open_qs(at)
    at.number_input(key="tnd_n").set_value(4).run()    # so the builder adds tendons
    _apply_qs(at)                                       # populate from the builder
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
    _open_qs(at)
    at.selectbox(key="shape").set_value("Box girder").run()
    _apply_qs(at)
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
    # Codex P2: void corners typed into the grid (its last reported rows, not yet in
    # the base) must survive a + Add void click, not be discarded.
    import pandas as pd
    at = _fresh()
    at.run()
    # base = one void; the grid's live rows carry an extra, not-yet-saved corner.
    at.session_state["hole_base"] = pd.DataFrame({
        "x (mm)": [-100.0, -40.0, -70.0], "y (mm)": [-50.0, -50.0, 50.0]})
    at.session_state["ed_hole"] = [
        {"x (mm)": -100.0, "y (mm)": -50.0}, {"x (mm)": -40.0, "y (mm)": -50.0},
        {"x (mm)": -70.0, "y (mm)": 50.0},
        {"x (mm)": 80.0, "y (mm)": -50.0}]   # an unsaved corner, live in the grid
    at.button(key="add_void").click().run()   # handler reads the live rows before re-render
    assert not at.exception
    hb = at.session_state["hole_base"]
    assert (hb["x (mm)"] == 80.0).any()   # the unsaved corner survived the rebuild


def test_cleared_grid_is_respected_not_resurrected():
    # Codex P2: when the grid reports an empty list (every row deleted), the live
    # table must be empty -- not fall back to the stale base. With a void in the
    # base but the grid cleared, the void count is 0 so Remove void is disabled.
    import pandas as pd
    at = _fresh()
    at.run()
    at.session_state["hole_base"] = pd.DataFrame(
        {"x (mm)": [-100.0, -40.0, -70.0], "y (mm)": [-50.0, -50.0, 50.0]})
    at.session_state["ed_hole"] = []          # the grid reports all rows deleted
    at.run()
    assert not at.exception
    assert at.button(key="rem_void").disabled  # 0 voids -> Remove disabled


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
    _open_qs(at)
    _apply_qs(at)                            # default rectangle, no cavity
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


def test_bar_outside_the_concrete_is_rejected():
    # A bar beyond the concrete outline carries no force: the app flags it and
    # refuses to compute (the default section spans y in [-300, 300] mm).
    import pandas as pd
    at = _fresh()
    at.run()
    at.session_state["bars_base"] = pd.DataFrame(
        {"x (mm)": [0.0], "y (mm)": [1000.0], "area (mm2)": [314.0]})
    at.run()
    assert any("within the concrete" in e.value for e in at.error)
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
    assert any("must be at least" in w.value and "peak strain" in w.value
               for w in at.warning)
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


def test_fresh_session_project_captures_default_section():
    # The download must reflect the live section even on a fresh session (the panel
    # is filled after the tables are seeded), not an empty one.
    import sys as _sys
    at = _fresh()
    at.run()
    _sys.path.insert(0, str(pathlib.Path(APP).resolve().parent))
    import project_io  # noqa: E402
    text = project_io.dump_project(
        {k: at.session_state[k] for k in project_io.TABLE_KEYS if k in at.session_state},
        {k: at.session_state[k] for k in project_io.SCALAR_KEYS if k in at.session_state})
    tables, _ = project_io.parse_project(text)
    assert len(tables["corners_base"]) >= 3   # default rectangle, not blank


def test_autosave_defaults_on_with_five_minutes(tmp_path, monkeypatch):
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path))
    at = _fresh()
    at.run()
    assert at.session_state["autosave_on"] is True
    assert at.session_state["autosave_min"] == 5


def test_autosave_writes_a_roundtrippable_project(tmp_path, monkeypatch):
    # Once the interval has elapsed, the next rerun (a user interaction) writes the
    # current section to the local autosave file, which parses back to a project.
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path))
    import sys as _sys
    at = _fresh()
    at.run()
    at.session_state["_autosave_t"] = 0.0          # make a save due, then rerun
    at.run()
    saved = tmp_path / "autosave.json"
    assert saved.exists()
    _sys.path.insert(0, str(pathlib.Path(APP).resolve().parent))
    import project_io  # noqa: E402
    tables, scalars = project_io.parse_project(saved.read_text(encoding="utf-8"))
    assert len(tables["corners_base"]) >= 3        # the live section, not blank
    assert at.session_state["_autosave_last"]      # the panel records the time


def test_autosave_restores_last_session_on_next_launch(tmp_path, monkeypatch):
    # The BriCoS principle: a pre-existing autosave is loaded automatically on the
    # next launch, so the section resumes where the user left off.
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path))
    at = _fresh()
    at.run()
    at.number_input(key="conc_fck").set_value(42.0).run()
    at.session_state["_autosave_t"] = 0.0          # make a save due
    at.run()
    assert (tmp_path / "autosave.json").exists()
    at2 = _fresh()                                 # a brand-new session
    at2.run()
    assert at2.session_state["conc_fck"] == 42.0   # restored automatically


def test_autosave_after_quick_section_apply_saves_applied_geometry(tmp_path, monkeypatch):
    # Applying the Quick Section reseeds the tables and reruns with the builder
    # closed; a due autosave must then capture the applied geometry, not the stale
    # pre-apply tables (Codex P2).
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path))
    at = _fresh()
    at.run()
    _open_qs(at)
    at.number_input(key="h_mm").set_value(900.0).run()   # distinctive height (450 mm half)
    at.session_state["_autosave_t"] = 0.0                # a save is due
    at.button(key="qs_apply").click().run()              # reseed + close builder + rerun
    assert not at.exception
    saved = tmp_path / "autosave.json"
    assert saved.exists()
    import sys as _sys
    _sys.path.insert(0, str(pathlib.Path(APP).resolve().parent))
    import project_io  # noqa: E402
    tables, _ = project_io.parse_project(saved.read_text(encoding="utf-8"))
    assert tables["corners_base"]["y (mm)"].abs().max() == pytest.approx(450.0, abs=1.0)


def test_autosave_disabled_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path))
    at = _fresh()
    at.run()
    at.checkbox(key="autosave_on").set_value(False).run()
    at.session_state["_autosave_t"] = 0.0          # due, but autosave is off
    at.run()
    assert not (tmp_path / "autosave.json").exists()


def test_autosave_path_respects_env_override(tmp_path, monkeypatch):
    import sys as _sys
    _sys.path.insert(0, str(pathlib.Path(APP).resolve().parent))
    import sector_app  # noqa: E402
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path))
    assert sector_app._autosave_path() == tmp_path / "autosave.json"
    assert sector_app._write_autosave('{"x": 1}', tmp_path / "a.json") is True
    assert (tmp_path / "a.json").read_text(encoding="utf-8") == '{"x": 1}'


def test_write_autosave_is_atomic_and_replaces(tmp_path):
    # The write replaces the old file via a temp + os.replace, leaving no .tmp behind,
    # so a crash mid-write cannot truncate the recovery file (Codex P2).
    import sys as _sys
    _sys.path.insert(0, str(pathlib.Path(APP).resolve().parent))
    import sector_app  # noqa: E402
    p = tmp_path / "autosave.json"
    p.write_text("OLD", encoding="utf-8")
    assert sector_app._write_autosave("NEW", p) is True
    assert p.read_text(encoding="utf-8") == "NEW"
    assert not (tmp_path / "autosave.json.tmp").exists()


def test_autosave_skips_a_blank_outline(tmp_path, monkeypatch):
    # Three blank/NaN corner rows are not three usable corners: autosave must not
    # overwrite the recovery file with an outline-less project (Codex P2).
    import pandas as pd
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path))
    at = _fresh()
    at.run()
    at.session_state["corners_base"] = pd.DataFrame(
        {"x (mm)": [float("nan")] * 3, "y (mm)": [float("nan")] * 3})
    at.session_state["_autosave_t"] = 0.0          # a save is due
    at.run()
    assert not (tmp_path / "autosave.json").exists()


def test_load_preserves_manual_alpha_cc_for_strength_dependent_preset():
    # A manually edited alpha_cc under EN 2023 (eta_cc tracks fck) must round-trip,
    # not be overwritten by the automatic value when the project is reloaded.
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
        "scalars": {"conc_preset": "DS/EN 1992-1-1:2023", "conc_fck": 40.0,
                    "conc_alpha_cc": 0.5, "mode": "Plastic"},
    }
    at.session_state["_pending_project"] = json.dumps(project)
    at.run()
    assert not at.exception
    assert at.session_state["conc_alpha_cc"] == 0.5


def test_generate_report_produces_pdf():
    # The Report panel's Generate button builds a PDF from the current section
    # (figures skipped in the test so it does not need a browser).
    at = _fresh()
    at.run()
    at.session_state["_report_no_figures"] = True
    at.session_state["rep_proj_no"] = "T-1"
    at.button(key="gen_report").click().run()
    assert not at.exception
    assert "report_buffer" in at.session_state
    assert at.session_state["report_buffer"][:4] == b"%PDF"


def test_load_project_without_tendon_table_does_not_crash():
    # An older / partial project may omit the tendon table; the always-mounted
    # tendon editor must still find a (seeded) base rather than KeyError.
    import json
    at = _fresh()
    at.run()
    project = {
        "format": "sector-project", "version": 1,
        "tables": {"corners_base": {"columns": ["x (mm)", "y (mm)"],
                                    "rows": [[-100.0, -150.0], [100.0, -150.0],
                                             [100.0, 150.0], [-100.0, 150.0]]}},
        "scalars": {"mode": "Plastic"},
    }
    at.session_state["_pending_project"] = json.dumps(project)
    at.run()
    assert not at.exception
    assert "tendons_base" in at.session_state
    assert len(at.session_state["tendons_base"]) == 0


def test_capacity_only_toggle_locks_moments_and_drops_utilisation():
    # With utilisation checking off, the applied plastic moments lock and the result
    # carries no utilisation (capacity only); the axial force stays editable.
    at = _fresh()
    at.run()
    at.checkbox(key="pl_check_util").set_value(False).run()
    assert at.number_input(key="pl_Mx").disabled is True
    assert at.number_input(key="pl_My").disabled is True
    assert at.number_input(key="pl_P").disabled is False
    at.button(key="calculate").click().run()
    assert not at.exception
    pl = at.session_state["results"]["plastic"]
    assert pl["util"] is None and pl["check_util"] is False and pl["applied"] is None


def test_prestress_always_available_without_a_toggle():
    # The "include prestressing tendons" checkbox is gone: the prestress material
    # panel and the tendon point table are always present.
    at = _fresh()
    at.run()
    assert "use_pre" not in {cb.key for cb in at.checkbox}
    assert "pre_Es" in {ni.key for ni in at.number_input}   # prestress panel rendered
    assert "tendons_base" in at.session_state                # tendon table mounted


def test_auto_calc_all_updates_every_derived_value():
    # One button recomputes all the auto-derived values from the current inputs.
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Both").run()
    at.number_input(key="conc_fck").set_value(70.0).run()    # high grade -> Table 3.1
    at.button(key="conc_Ec_auto").click().run()              # the EC2 secant Ec for C70
    ec70 = at.session_state["conc_Ec"]
    # Manually push the auto values off their derived values.
    at.number_input(key="conc_eps_cu2").set_value(5.0).run()
    at.number_input(key="conc_Ec").set_value(20.0).run()     # Ec drives the modular ratios
    at.button(key="auto_all_btn").click().run()
    assert not at.exception
    # eps_cu2 back to the Table 3.1 value for C70 (~2.66 permille), not 5.0.
    assert at.session_state["conc_eps_cu2"] == pytest.approx(2.66, abs=0.05)
    # Ec back to the EC2 secant modulus (not 20.0); the modular ratios follow from it.
    assert at.session_state["conc_Ec"] == pytest.approx(ec70, abs=0.05)
    assert at.session_state["conc_Ec"] != pytest.approx(20.0)


def test_auto_calc_all_respects_2023_constant_strains():
    # EN 1992-1-1:2023 keeps the ultimate parabola strains constant for every class.
    # Auto-calc-all must not silently overwrite them with the Table 3.1
    # strength-dependent values above C50/60 (the Codex P2 on PR #67).
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Both").run()
    at.selectbox(key="conc_preset").set_value("DS/EN 1992-1-1:2023").run()
    at.number_input(key="conc_fck").set_value(70.0).run()
    at.number_input(key="conc_eps_cu2").set_value(2.0).run()     # skew it
    at.button(key="auto_all_btn").click().run()
    assert not at.exception
    # Constant 0.2%/0.35%/2 -- NOT the Table 3.1 value (~2.66 permille) for C70.
    assert at.session_state["conc_eps_cu2"] == pytest.approx(3.5)
    assert at.session_state["conc_eps_c2"] == pytest.approx(2.0)
    assert at.session_state["conc_n"] == pytest.approx(2.0)


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
    # panel is always shown, like mild steel).
    at = _fresh()
    at.run()
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
    at.radio(key="mode").set_value("Elastic").run()
    # The stress-strain law parameters are plastic-only, so they lock; but the
    # initial prestrain IS and the modulus Es (Ep) stay editable -- the elastic
    # analysis applies the tendon prestress Ep*IS and uses Ep/Ec for the tendon.
    for locked in ("pre_fytk", "pre_eut"):
        assert at.number_input(key=locked).disabled is True, locked
    for editable in ("pre_IS", "pre_Es"):
        assert at.number_input(key=editable).disabled is False, editable


def test_elastic_applies_tendon_prestress_from_initial_strain():
    # With tendons + a prestrain, the elastic analysis applies the prestress force
    # from IS (N stays the external force only): the result reports the prestress
    # resultant, and changing IS changes the concrete state.
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    _open_qs(at)
    at.number_input(key="tnd_n").set_value(4).run()       # put tendons in the section
    _apply_qs(at)
    at.number_input(key="pre_IS").set_value(5.0).run()    # permille
    at.number_input(key="el_long_Mx").set_value(200.0).run()
    at.button(key="calculate").click().run()
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    assert e["prestress"] is not None and e["prestress"][0] != 0.0   # applied + reported
    base_conc = e["max_conc"]
    at.number_input(key="pre_IS").set_value(9.0).run()    # stronger prestress
    at.button(key="calculate").click().run()
    assert at.session_state["results"]["elastic"]["max_conc"] != pytest.approx(base_conc)


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
    for key in ("conc_fck", "mild_fytk", "mild_eut", "pl_P", "pl_Mx", "el_phi", "view"):
        w = (_widget(at.number_input, key) or _widget(at.selectbox, key)
             or _widget(at.radio, key))
        assert w is not None and w.help, key
    assert at.radio(key="mode").help
    # The Quick Section builder inputs carry help too.
    _open_qs(at)
    for key in ("shape", "b_mm", "h_mm", "cover_mm"):
        w = _widget(at.number_input, key) or _widget(at.selectbox, key)
        assert w is not None and w.help, key


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
    _open_qs(at)
    at.number_input(key="tnd_n").set_value(4).run()
    _apply_qs(at)                            # put tendons in the section
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
    at.number_input(key="conc_fck").set_value(40.0).run()  # change an input after calc
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
    _open_qs(at)
    at.number_input(key="tnd_n").set_value(4).run()
    _apply_qs(at)                            # put the tendons in the section
    at.button(key="calculate").click().run()
    assert not at.exception
    res = at.session_state["results"]
    assert "plastic" in res
    assert res["plastic"]["max_mx"] > mx0


def test_prestress_both_modes_run_with_tendons():
    at = _fresh()
    at.run()
    _open_qs(at)
    at.number_input(key="tnd_n").set_value(4).run()
    _apply_qs(at)                            # load the tendons into the points
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
    _open_qs(at)
    at.number_input(key="tnd_n").set_value(4).run()
    _apply_qs(at)                            # load the tendons into the points
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


def test_dk_na_reports_fine_and_coarse_for_both_load_cases():
    # The single DK NA option reports four crack widths: the fine and the coarse
    # crack system, each for the long-term and the short-term load. The coarse
    # system (centroid-matched effective area + wk/2) is smaller than the fine one.
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.number_input(key="el_long_Mx").set_value(400.0).run()
    at.number_input(key="el_short_Mx").set_value(150.0).run()
    at.checkbox(key="sls_cw").set_value(True).run()
    at.selectbox(key="sls_code").set_value("DS/EN 1992-1-1 + DK NA").run()
    at.button(key="calculate").click().run()
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    for key in ("crack", "crack_short", "crack_coarse", "crack_short_coarse"):
        assert e[key] is not None and e[key]["wk"] > 0.0
    assert e["crack"]["coarse"] is False and e["crack_coarse"]["coarse"] is True
    assert e["crack_coarse"]["wk"] < e["crack"]["wk"]             # coarse < fine, long-term
    assert e["crack_short_coarse"]["wk"] < e["crack_short"]["wk"]  # coarse < fine, short-term


def test_non_dk_na_reports_no_coarse_columns():
    # The base EN 1992-1-1 code has no coarse system, so only the two fine columns.
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.number_input(key="el_long_Mx").set_value(400.0).run()
    at.checkbox(key="sls_cw").set_value(True).run()
    at.selectbox(key="sls_code").set_value("EN 1992-1-1:2005").run()
    at.button(key="calculate").click().run()
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    assert e["crack"] is not None
    assert e.get("crack_coarse") is None and e.get("crack_short_coarse") is None


def test_ec2_2023_crack_edition_calculates():
    # Selecting EN 1992-1-1:2023 uses the refined model (9.2.3) and reports its wk.
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.number_input(key="el_long_Mx").set_value(400.0).run()
    at.checkbox(key="sls_cw").set_value(True).run()
    at.selectbox(key="sls_code").set_value("EN 1992-1-1:2023").run()
    at.button(key="calculate").click().run()
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    assert e["crack_code"] == "EN 1992-1-1:2023"
    assert e["crack"]["edition"] == "2023" and e["crack"]["kw"] == 1.7
    assert e["crack"]["wk"] > 0.0 and e["crack"]["k1_r"] >= 1.0


def test_old_crack_code_alias_targets_a_current_option():
    # A session saved with a since-removed crack-code label (the split fine/coarse
    # DK NA options) is migrated (in build_inputs, before the selectbox reads it) to
    # the merged DK NA option. Verify each alias is retired and maps to a live one.
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "app"))
    import sector_app
    for old, new in sector_app._CRACK_CODE_ALIASES.items():
        assert old not in sector_app._CRACK_CODES      # the old label is retired
        assert new in sector_app._CRACK_CODES          # and points at a live option


def test_short_term_crack_uses_combined_creep_state():
    # With creep (ns != nl) the short-term crack width must come from the combined
    # instantaneous state (total = s2 + RST1), so the governing bar's sigma_s
    # equals the Total steel-stress column -- not a raw (long+short)-at-ns solve.
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.number_input(key="el_long_Mx").set_value(300.0).run()
    at.number_input(key="el_short_Mx").set_value(150.0).run()
    at.number_input(key="el_phi").set_value(2.0).run()  # creep: n_l = (1+phi)*n_s != n_s
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
    _open_qs(at)
    at.number_input(key="tnd_n").set_value(4).run()
    _apply_qs(at)
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


def test_cracking_follows_the_total_load():
    # The cracking decision is on the total load. With no short-term load the total
    # equals the long-term load, so raising the long-term moment crosses from
    # uncracked to cracked.
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.number_input(key="el_long_Mx").set_value(5.0).run()
    at.button(key="calculate").click().run()
    assert at.session_state["results"]["elastic"]["cracked"] is False
    at.number_input(key="el_long_Mx").set_value(400.0).run()
    at.button(key="calculate").click().run()
    assert at.session_state["results"]["elastic"]["cracked"] is True


def test_short_term_load_triggers_cracking():
    # A section uncracked under the long-term load alone but cracked under the total
    # (long + short) load must be reported as cracked, with a crack width computed --
    # cracking is triggered by the peak load and is irreversible.
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.number_input(key="el_long_Mx").set_value(5.0).run()     # uncracked alone
    at.number_input(key="el_short_Mx").set_value(400.0).run()  # cracks the total
    at.checkbox(key="sls_cw").set_value(True).run()
    at.button(key="calculate").click().run()
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    assert e["cracked"] is True                    # cracked by the short-term peak
    assert e["lambda_cr"] < 1.0
    # Both crack widths are reported: the quasi-permanent (long-term) one for the
    # code limit and the short-term one under the peak.
    assert e["crack"] is not None and e["crack"]["wk"] > 0.0
    assert e["crack_short"] is not None and e["crack_short"]["wk"] > 0.0


def test_cracked_properties_use_the_governing_load_when_long_term_is_zero():
    # With no long-term load, the section is cracked only by the short-term peak. The
    # cracked transformed properties must come from that (governing) cracked state,
    # not the degenerate zero-long-term solve (which would keep the full section).
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.number_input(key="el_long_Mx").set_value(0.0).run()
    at.number_input(key="el_short_Mx").set_value(400.0).run()
    at.button(key="calculate").click().run()
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    assert e["cracked"] is True
    assert e["props_cr"] is not None
    assert e["props_cr"]["area"] < e["props_un"]["area"]   # a real cracked section


def test_counteracting_short_term_load_keeps_cracked():
    # If the short-term action counteracts the sustained one so the total is
    # uncracked, the section is still cracked (the long-term action already cracked
    # it -- cracking is irreversible), and the long-term crack width is reported.
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.number_input(key="el_long_Mx").set_value(400.0).run()    # cracks on its own
    at.number_input(key="el_short_Mx").set_value(-380.0).run()  # total ~ 20, uncracked
    at.checkbox(key="sls_cw").set_value(True).run()
    at.button(key="calculate").click().run()
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    assert e["cracked"] is True                    # cracked by the long-term action
    assert e["crack"] is not None and e["crack"]["wk"] > 0.0


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


def test_modular_ratios_are_derived_from_moduli():
    # n_l/n_s are no longer entered: the number inputs and Auto buttons are gone. The
    # loads panel reports the derived ratios instead -- n_s = Es/Ec and, with creep,
    # n_l = (1+phi)*n_s. Here Es/Ec = 200000/40000 = 5.0 and n_l = (1+2)*5 = 15.0.
    at = _fresh()
    at.run()
    keys = {w.key for w in at.number_input} | {b.key for b in at.button}
    assert "nl" not in keys and "ns" not in keys              # inputs removed
    assert "nl_auto" not in keys and "ns_auto" not in keys    # Auto buttons removed
    at.radio(key="mode").set_value("Both").run()
    at.number_input(key="mild_Es").set_value(200000.0).run()
    at.number_input(key="conc_Ec").set_value(40.0).run()      # Es/Ec = 5.0
    at.number_input(key="el_phi").set_value(2.0).run()        # n_l = (1+2)*5 = 15.0
    md = "\n".join(m.value for m in at.markdown)
    assert "Modular ratios" in md
    assert "| Mild (Es/Ec) | 5.0 | 15.0 |" in md


def test_prestress_gets_its_own_derived_modular_ratio():
    # Prestress and mild steel have independent ratios because Es != Ep. With a
    # tendon in the section the loads panel adds a prestress row n = Ep/Ec alongside
    # the mild row; Ep = 195000, Ec = 39000 -> Ep/Ec = 5.0, and phi = 0 -> n_l = n_s.
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Both").run()
    _open_qs(at)
    at.number_input(key="tnd_n").set_value(3).run()           # add tendons
    _apply_qs(at)
    at.number_input(key="pre_Es").set_value(195000.0).run()   # Ep
    at.number_input(key="conc_Ec").set_value(39.0).run()      # Ep/Ec = 5.0
    at.number_input(key="el_phi").set_value(0.0).run()        # no creep: n_l = n_s
    md = "\n".join(m.value for m in at.markdown)
    assert "| Prestress (Ep/Ec) | 5.0 | 5.0 |" in md


def test_transformed_area_uses_the_tendon_modular_ratio():
    # The reported transformed section properties must weight tendons at Ep/Es
    # (n_mult), like the elastic and cracking solves -- so changing Ep moves the
    # reported transformed area. Without n_mult the tendons would take the mild
    # ratio and Ep would have no effect on the properties.
    def _area(pre_es):
        at = _fresh()
        at.run()
        at.radio(key="mode").set_value("Elastic").run()
        _open_qs(at)
        at.number_input(key="tnd_n").set_value(3).run()          # add tendons
        _apply_qs(at)
        at.number_input(key="pre_Es").set_value(pre_es).run()
        at.button(key="calculate").click().run()
        return at.session_state["results"]["elastic"]["props_un"]["area"]

    a_soft, a_stiff = _area(160000.0), _area(200000.0)
    assert a_stiff != pytest.approx(a_soft, rel=1e-6)   # Ep changes the transformed area
    assert a_stiff > a_soft                              # stiffer tendons -> larger area


def test_editing_ec_or_creep_marks_elastic_results_stale():
    # n_l/n_s are derived from Ec and creep, so editing either after Calculate must
    # mark the elastic results stale (the ratios enter the signature via their inputs).
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.selectbox(key="view").set_value("Elastic Results").run()
    at.button(key="calculate").click().run()
    assert not any("press Calculate" in w.value for w in at.warning)   # fresh, not stale
    at.number_input(key="conc_Ec").set_value(20.0).run()              # changes n_s and n_l
    assert any("press Calculate" in w.value for w in at.warning)      # now stale
    at.button(key="calculate").click().run()
    at.number_input(key="el_phi").set_value(1.0).run()               # changes n_l (creep)
    assert any("press Calculate" in w.value for w in at.warning)


def test_crack_width_auto_cover_circular_section():
    # No cover input: the crack width takes each bar's clear cover from the
    # geometry. A 100 mm ring cover (to centres) on a circular section gives a
    # clear cover near 100 - phi/2 mm, comfortably above 70 mm.
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    _open_qs(at)
    at.selectbox(key="shape").set_value("Circular").run()
    at.number_input(key="ring_c_mm").set_value(100.0).run()
    _apply_qs(at)                                 # apply the ring to the points
    at.number_input(key="el_long_Mx").set_value(400.0).run()  # force cracking
    at.checkbox(key="sls_cw").set_value(True).run()
    at.button(key="calculate").click().run()
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    if e["crack"] is not None:
        assert e["crack"]["cover"] > 70.0
