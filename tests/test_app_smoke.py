"""Headless smoke tests for the Streamlit app via Streamlit's AppTest.

These run the app script in-process (no browser), exercise the Calculate flow
for each analysis mode, and assert it produces results without error.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

from streamlit.testing.v1 import AppTest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))   # so `import sector_app` / `project_io` works standalone

APP = str(ROOT / "app" / "sector_app.py")

from app_case_inputs import apply_case_changes, first_case_value  # noqa: E402


def _fresh():
    return AppTest.from_file(APP, default_timeout=90)


def _fresh_qs(**state):
    """Start directly in Quick Section with optional pre-seeded widget state.

    The app always builds the input tabs before entering the builder, so the first
    run still exercises complete input construction. Skipping an otherwise disposable
    initial Inputs-page run saves one full AppTest rerun per builder scenario.
    """
    at = _fresh()
    for key, value in state.items():
        at.session_state[key] = value
    at.session_state["_qs_open"] = True
    at.session_state["_main_page"] = "Analysis"
    return at.run()


def _goto_page(at, page):
    """Navigate only when needed, preserving the page-local AppTest tree."""
    try:
        current = at.session_state["_main_page"]
    except KeyError:
        current = None
    if current != page:
        at.segmented_control(key="_main_page").set_value(page).run()
    return at


def _goto_input_tab(at, name):
    """Select one tracked input tab by its short engineering name."""
    _goto_page(at, "Inputs")
    d = chr(0x00B7)
    labels = {
        "Analysis settings": f"1 {d} Analysis settings",
        "Section": f"2 {d} Section",
        "Material parameters": f"3 {d} Material parameters",
        "Loads": f"4 {d} Loads",
        "Project & report": "Project & report",
    }
    label = labels[name]
    try:
        current = at.session_state["_input_tab"]
    except KeyError:
        current = None
    if current != label:
        at.session_state["_input_tab"] = label
        at.run()
    return at


def _goto_material_tab(at, name):
    """Open Material parameters and select one material subtab."""
    _goto_input_tab(at, "Material parameters")
    try:
        current = at.session_state["_material_tab"]
    except KeyError:
        current = None
    if current != name:
        at.session_state["_material_tab"] = name
        at.run()
    return at


def _calculate(at):
    _goto_page(at, "Analysis")
    if not any(button.key == "calculate" for button in at.button):
        _goto_page(at, "Inputs")
        _goto_page(at, "Analysis")
    at.button(key="calculate").click().run()
    return at


def _select_view(at, value):
    _goto_page(at, "Analysis")
    if not any(box.key == "view" for box in at.selectbox):
        _goto_page(at, "Inputs")
        _goto_page(at, "Analysis")
    at.selectbox(key="view").set_value(value).run()
    return at


def _replace_base_table(at, base_key, value):
    """Reseed a point-grid base exactly as the application does on project load."""
    _goto_page(at, "Inputs")
    editors = {
        "corners_base": "ed_corners",
        "hole_base": "ed_hole",
        "bars_base": "ed_bars",
        "tendons_base": "ed_tendons",
    }
    editor = editors[base_key]
    try:
        version = at.session_state[editor + "_ver"]
    except KeyError:
        version = 0
    at.session_state[base_key] = value
    at.session_state[editor + "_ver"] = version + 1
    try:
        del at.session_state[editor]
    except KeyError:
        pass
    at.run()
    return at


def _replace_case_table(at, base_key, value):
    """Reseed one canonical load-case editor after replacing its backing table."""
    import load_cases

    _goto_page(at, "Inputs")
    editor = {
        load_cases.PLASTIC_TABLE_KEY: "plastic_cases_editor",
        load_cases.ELASTIC_TABLE_KEY: "elastic_cases_editor",
    }[base_key]
    at.session_state[base_key] = load_cases.normalise_table(value, base_key)
    for state_key in (editor, f"_{base_key}_editor_seed"):
        try:
            del at.session_state[state_key]
        except KeyError:
            pass
    at.run()
    return at


def _set(at, *changes):
    """Stage already-rendered widget changes and perform one Streamlit rerun."""
    changes, case_changed = apply_case_changes(at, changes)
    if case_changed:
        _goto_page(at, "Inputs")
    if changes:
        widget_type, key, _value = changes[0]
        try:
            getattr(at, widget_type)(key=key)
        except KeyError:
            _goto_page(at, "Analysis" if key == "view" else "Inputs")
    for widget_type, key, value in changes:
        getattr(at, widget_type)(key=key).set_value(value)
    return at.run()


def _set_and_click(at, button_key, *changes):
    """Submit a group of existing inputs with one button-triggered rerun."""
    # Quick Section's exit buttons deliberately escalate from a fragment rerun to a
    # full-app rerun. AppTest does not emulate that browser transition and can retain
    # removed builder widgets if their edits and the exit click share one test tick.
    # Stage those edits first; the normal in-fragment buttons remain batched.
    if button_key in {"qs_apply", "qs_back"} and changes:
        _set(at, *changes)
        changes = ()
    elif button_key == "calculate" and changes:
        _set(at, *changes)
        changes = ()
    for widget_type, key, value in changes:
        getattr(at, widget_type)(key=key).set_value(value)
    if button_key == "calculate":
        # Submit the edited input page first, then calculate from the independently
        # rendered Analysis page.
        _goto_page(at, "Analysis")
    at.button(key=button_key).click()
    return at.run()


def _open_qs(at):
    """Open the full-width Quick Section builder so its widgets render."""
    at.session_state["_qs_open"] = True
    at.session_state["_main_page"] = "Analysis"
    at.run()
    return at


def _apply_qs(at):
    """Apply the builder to the point tables and return to the analysis layout."""
    at.button(key="qs_apply").click().run()
    return at


def _clear_section(at):
    """Confirm the two-step section clear and return the rerun AppTest."""
    at.button(key="clear_pts").click().run()
    at.button(key="confirm_clear_pts").click().run()
    return at


def test_app_loads_without_error():
    at = _fresh()
    at.run()
    assert not at.exception
    # Before any calculation the app prompts the user.
    assert "results" not in at.session_state


@pytest.mark.parametrize(
    ("old", "new"),
    [("M-V-T Interaction", "M-V-T Combined"),
     ("Stress-Strain diagrams", "Results Overview"),
     ("Material laws", "Results Overview"),
     ("Section", "Results Overview")],
)
def test_app_migrates_legacy_view_label(old, new):
    # Stored pre-rename view labels migrate before the keyed selectbox renders.
    at = _fresh()
    at.session_state["view"] = old
    at.run()
    assert not at.exception
    assert at.session_state["view"] == new


def test_app_empty_result_reads_not_calculated():
    # An invalid/empty section makes run_analysis return {}; the freshness badge must
    # read "Not calculated yet", not green "Results up to date".
    at = _fresh()
    at.run()
    _clear_section(at)                           # empty the section -> no valid points
    _calculate(at)
    assert ("results" in at.session_state) and at.session_state["results"] == {}
    caps = [c.value for c in at.caption]
    assert any("Not calculated yet" in c for c in caps)
    assert not any("up to date" in c for c in caps)


def test_live_curve_figures_are_memoised():
    # The co-located concrete preview is rebuilt only when its material actually
    # changes; an unrelated rerun reuses the cached figure.
    at = _fresh()
    at.run()
    _goto_material_tab(at, "Concrete")
    conc_id = id(at.session_state["_fig_cache"]["concrete"][1])
    _set(at, ("number_input", "el_phi", 2.0))  # unrelated to the concrete law
    _goto_material_tab(at, "Concrete")
    assert id(at.session_state["_fig_cache"]["concrete"][1]) == conc_id     # reused
    _set(at, ("number_input", "conc_fck", 45.0))  # changes the concrete law
    _goto_material_tab(at, "Concrete")
    assert id(at.session_state["_fig_cache"]["concrete"][1]) != conc_id     # rebuilt


def test_hidden_input_previews_do_not_emit_plotly_figures():
    # Tracked tabs keep every input mounted but build only the visible preview.
    at = _fresh()
    at.run()
    assert "_fig_cache" not in at.session_state

    _goto_input_tab(at, "Section")
    assert set(at.session_state["_fig_cache"]) == {"section"}

    _goto_material_tab(at, "Concrete")
    assert set(at.session_state["_fig_cache"]) == {"section", "concrete"}
    assert not at.exception


def test_ui_hot_paths_are_isolated_streamlit_fragments():
    """Keep non-engineering UI interactions off the live app's full-rerun path.

    Streamlit AppTest intentionally performs full script reruns and cannot time a
    browser fragment rerun. Structural assertions therefore guard the production
    isolation, while the rest of this file verifies the resulting behavior.
    """
    import inspect
    import sector_app

    for func in (
        sector_app._analysis_workspace,
        sector_app._quick_section_viewport,
        sector_app._report_panel,
        sector_app._save_load_panel,
    ):
        assert hasattr(func, "__wrapped__"), func.__name__

    workspace = inspect.getsource(sector_app._analysis_workspace.__wrapped__)
    assert workspace.index('c_calc.button(') < workspace.index('c_view.selectbox(')
    assert "_switch_view" not in workspace
    for panel in (sector_app._report_panel, sector_app._save_load_panel):
        panel_source = inspect.getsource(panel.__wrapped__)
        assert "st.expander(" in panel_source
        assert "parent." not in panel_source


def test_persisted_settings_use_the_seeded_number_helper():
    # These inputs are saved (SCALAR_KEYS), so loading a project writes their key
    # before the widget is created; passing value= too trips Streamlit's "default
    # value and Session State" warning. They must go through _seeded_number
    # (setdefault + no value=), so the bare `key="<name>"` form no longer appears.
    import inspect
    import sector_app
    src = inspect.getsource(sector_app)
    for helper in (
        "_seeded_number", "_seeded_checkbox", "_seeded_selectbox", "_seeded_text",
    ):
        assert f"def {helper}(" in src
    # Widgets whose key is restored from a saved project/session (a value= / index=
    # alongside the externally-set key trips the warning) go through a seeded helper,
    # so the bare `key="<name>"` form no longer appears for them. The Quick Section
    # dimension inputs are included now: their shared shape-varying keys (b_mm/h_mm)
    # are re-seeded on a shape switch by _qs_shape_prefill, so they no longer need
    # value=. (wall_mm keeps key= -- it has a dimension-dependent max, so it seeds and
    # clamps by hand -- but still passes no value=, so it does not warn.)
    for key in ("v_min", "v_max", "v_inc", "el_phi", "sls_phi",
                "label_scale", "label_min_gap",                # seeded number inputs
                "pl_check_util", "pl_interaction",              # seeded checkboxes
                "conc_preset", "mild_preset", "pre_preset",     # seeded selectboxes
                "sls_limit_source",
                "ring_d", "bot_d", "top_d",                     # QS diameter inputs
                "qs_cover_to_edge", "bot_off_d", "top_off_d",   # QS toggle + interleave
                "b_mm", "h_mm", "bf_mm", "hf_mm", "bw_mm", "hw_mm", "dia_mm",  # QS dims
                "ring_n", "ring_c_mm", "bot_c_mm", "top_c_mm",  # QS rebar covers
                "bot_s", "top_s", "bot_n", "top_n", "bot_n2", "top_n2",
                "bot_layers", "top_layers", "layer_s",
                "tnd_n", "tnd_a", "tnd_c_mm", "tnd_layers", "tnd_layer_s"):    # QS tendons
        assert f'key="{key}"' not in src, key


def test_quick_section_shape_switch_reseeds_shared_dimensions():
    # b_mm/h_mm are shared across shapes; switching shape must reset them to the new
    # shape's default (the seeded inputs rely on _qs_shape_prefill for this, since a
    # plain setdefault would keep the previous shape's value).
    at = _fresh_qs()
    assert (at.session_state["b_mm"], at.session_state["h_mm"]) == (400.0, 600.0)
    at.selectbox(key="shape").set_value("Box girder").run()
    assert (at.session_state["b_mm"], at.session_state["h_mm"]) == (800.0, 1000.0)
    at.selectbox(key="shape").set_value("Slab strip").run()
    assert at.session_state["h_mm"] == 300.0                # slab thickness default
    at.selectbox(key="shape").set_value("Rectangle").run()
    assert (at.session_state["b_mm"], at.session_state["h_mm"]) == (400.0, 600.0)


def test_quick_section_reopen_preserves_edited_dimension():
    # A custom dimension survives closing and reopening the builder (the durable qsv_
    # copy restores it), and the seeded input adopts it without a warning/error -- the
    # case that used to trip the "default value + Session State" warning.
    at = _fresh_qs()
    at.selectbox(key="shape").set_value("Box girder").run()
    _set_and_click(
        at, "qs_back", ("number_input", "b_mm", 850.0)
    )  # close and mirror to qsv_
    _open_qs(at)                                            # reopen (restore)
    assert not at.exception
    assert at.session_state["shape"] == "Box girder"
    assert at.session_state["b_mm"] == 850.0               # custom value kept


def test_quick_section_dimensions_survive_a_project_restore():
    # A project saved with a custom dimension must keep it when loaded into a FRESH
    # session and the builder is first opened: qs_shape_prev is absent on that first
    # open, so the shape prefill must treat it as "no change" rather than mistaking
    # the restore for a shape switch and resetting b/h to the shape defaults.
    import project_io
    at = _fresh_qs()
    at.selectbox(key="shape").set_value("Box girder").run()
    _set_and_click(at, "qs_back", ("number_input", "b_mm", 850.0))
    scalars = {k: at.session_state[k] for k in project_io.SCALAR_KEYS
               if k in at.session_state}
    text = project_io.dump_project({}, scalars)

    at2 = _fresh()
    at2.session_state["_pending_project"] = text
    at2.session_state["_qs_open"] = True
    at2.run()
    assert not at2.exception
    assert at2.session_state["shape"] == "Box girder"
    assert at2.session_state["b_mm"] == 850.0            # restored dimension kept
    # A real shape switch after the restore still re-seeds to the new default.
    at2.selectbox(key="shape").set_value("Rectangle").run()
    assert at2.session_state["b_mm"] == 400.0


def test_quick_section_dimensions_survive_a_midsession_project_load():
    # Loading a project after the builder has already been used in this session must
    # also keep the loaded dimension: the earlier use leaves qs_shape_prev set, so the
    # load clears it (else the loaded shape would look like an in-builder switch and
    # the dimension would be re-seeded to the shape default).
    import project_io
    at = _fresh_qs()
    at.selectbox(key="shape").set_value("Box girder").run()
    _set_and_click(at, "qs_back", ("number_input", "b_mm", 850.0))
    scalars = {k: at.session_state[k] for k in project_io.SCALAR_KEYS
               if k in at.session_state}
    text = project_io.dump_project({}, scalars)

    at2 = _fresh_qs()                                    # use the builder first...
    at2.button(key="qs_back").click().run()             # (sets qs_shape_prev)
    at2.session_state["_pending_project"] = text        # ...then load the project
    at2.session_state["_qs_open"] = True
    at2.run()
    assert not at2.exception
    assert at2.session_state["shape"] == "Box girder"
    assert at2.session_state["b_mm"] == 850.0           # loaded dimension kept
    at2.selectbox(key="shape").set_value("Rectangle").run()
    assert at2.session_state["b_mm"] == 400.0           # a later switch still re-seeds


def test_loading_a_project_applies_a_seeded_setting(tmp_path):
    # A loaded project writes v_min before the sweep widget renders; the seeded input
    # must adopt it without error (the setdefault is then a no-op).
    import project_io
    at = _fresh()
    at.run()
    scalars = {k: at.session_state[k] for k in project_io.SCALAR_KEYS
               if k in at.session_state}
    scalars["v_min"] = 45.0
    at.session_state["_clear_section_undo"] = {"obsolete": True}
    at.session_state["_pending_project"] = project_io.dump_project({}, scalars)
    at.run()
    assert not at.exception
    assert at.session_state["v_min"] == 45.0
    assert "_clear_section_undo" not in at.session_state


def test_about_panel_shows_version_author_and_licensee():
    # The About panel carries the single-source release and ownership metadata.
    at = _fresh()
    at.run()
    blob = " | ".join(m.value for m in at.markdown) + \
        " | ".join(c.value for c in at.caption)
    from sector import __version__ as version   # single source; no per-bump edit
    assert version in blob and f"v{version}" in (at.title[0].value if at.title else "")
    assert "Kasper Lindskov Fabricius" in blob
    assert "Kasper.LindskovFabricius@sweco.dk" in blob
    assert "Sweco Danmark A/S" in blob


def test_calculate_plastic_produces_an_envelope():
    at = _fresh()
    at.run()
    _calculate(at)
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
    _calculate(at)
    at.session_state["results"]["plastic"].pop("min_mx", None)
    at.session_state["results"]["plastic"].pop("min_my", None)
    _select_view(at, "Plastic Results")
    assert not at.exception


def test_calculate_elastic_produces_bar_stresses():
    at = _fresh()
    at.run()
    _set_and_click(at, "calculate", ("radio", "mode", "Elastic"))
    assert not at.exception
    res = at.session_state["results"]
    assert "elastic" in res
    assert len(res["elastic"]["total"]) > 0


def test_combined_elastic_reports_four_columns():
    # The elastic analysis is the long+short-term creep model: four steel-stress
    # columns (total / long / dif / rst1), all the same length.
    at = _fresh()
    at.run()
    _set_and_click(at, "calculate", ("radio", "mode", "Elastic"))
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
    _set_and_click(at, "calculate", ("radio", "mode", "Elastic"))
    base = list(at.session_state["results"]["elastic"]["total"])
    _set_and_click(
        at,
        "calculate",
        ("number_input", "el_short_Mx", 80.0),
        ("number_input", "conc_Ec", 25.0),
    )
    assert not at.exception
    assert at.session_state["results"]["elastic"]["total"] != base


def test_plastic_sweep_increment_changes_point_count():
    at = _fresh()
    at.run()
    _calculate(at)
    n_default = len(at.session_state["results"]["plastic"]["points"])
    _set_and_click(
        at, "calculate", ("number_input", "v_inc", 5.0)
    )  # finer sweep
    assert not at.exception
    assert len(at.session_state["results"]["plastic"]["points"]) > n_default


def test_full_sweep_drops_the_duplicate_360_point():
    # A full 360 deg turn's last angle repeats the first, so the sweep stops one step
    # short (the envelope closes itself). The 360 deg row is neither computed nor
    # reported, but the result is still a closed envelope (utilisation available).
    at = _fresh()
    at.run()
    _calculate(at)            # default 0-360, 15 deg
    vs = [p["V"] for p in at.session_state["results"]["plastic"]["points"]]
    assert vs[0] == 0.0 and vs[-1] == 345.0             # stops before the wrap-around
    assert 360.0 not in vs                              # the duplicate of 0 deg is gone
    assert at.session_state["results"]["plastic"]["util"] is not None   # still closed


def test_partial_sweep_keeps_its_end_angle():
    # A partial arc is not a full turn, so both endpoints are distinct and kept.
    at = _fresh()
    at.run()
    _set_and_click(at, "calculate", ("number_input", "v_max", 180.0))
    vs = [p["V"] for p in at.session_state["results"]["plastic"]["points"]]
    assert vs[-1] == 180.0
    assert at.session_state["view"] == "Results Overview"
    _select_view(at, "Plastic Results")
    assert any("NOT ASSESSED - Plastic bending" in item.value
               and "open arc" in item.value.lower() for item in at.warning)


def test_plastic_sweep_stays_within_requested_bounds():
    # A V.inc that does not divide V.max - V.min must still land exactly on both
    # ends, with no swept angle outside [V.min, V.max].
    at = _fresh()
    at.run()
    _set_and_click(
        at,
        "calculate",
        ("number_input", "v_min", 0.0),
        ("number_input", "v_max", 10.0),
        ("number_input", "v_inc", 7.0),
    )  # max increment, doesn't divide
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
    _calculate(at)  # default 0-360 sweep
    assert at.session_state["results"]["plastic"]["util"] is not None


def test_plastic_result_overview_has_explicit_verdict_margin_and_qa_tables():
    at = _fresh()
    at.run()
    _set_and_click(
        at,
        "calculate",
        ("number_input", "pl_Mx", 20.0),
        ("number_input", "pl_My", 0.0),
    )
    assert at.session_state["view"] == "Results Overview"
    _select_view(at, "Plastic Results")
    assert any("PASS - Plastic bending" in item.value for item in at.success)
    assert any("limit 100 %" in item.value and "margin +" in item.value
               and " pp" in item.value
               for item in at.success)
    assert not any("does not exceed" in item.value for item in at.success)

    # Three short applied-action cards replace the five cramped capacity cards.
    labels = [metric.label for metric in at.metric]
    assert labels == [
        r"Axial $N_{Ed}$ (tension +)", r"$M_{x,Ed}$", r"$M_{y,Ed}$",
    ]
    frames = [frame.value for frame in at.dataframe]
    assert any("Bending axis" in frame.columns for frame in frames)
    assert any("State" in frame.columns and "Force (kN)" in frame.columns
               for frame in frames)
    assert any("Ring point" in frame.columns and
               any("Design stress" in str(column) for column in frame.columns)
               for frame in frames)

    _set_and_click(
        at,
        "calculate",
        ("number_input", "pl_Mx", 100000.0),
    )
    assert any("FAIL - Plastic bending" in item.value for item in at.error)
    assert any("margin -" in item.value for item in at.error)


def test_nm_interaction_is_opt_in_and_renders():
    at = _fresh()
    at.run()
    # Off by default: the N-M view prompts to enable it, and no interaction is computed.
    _set_and_click(
        at, "calculate", ("selectbox", "view", "N-M Interaction")
    )
    assert not at.exception
    assert "interaction" not in at.session_state["results"]["plastic"]
    assert any("N-M interaction" in m.value for m in at.info)
    # Enable it -> Calculate traces the diagram and the view renders it.
    _set_and_click(at, "calculate", ("checkbox", "pl_interaction", True))
    assert not at.exception
    d = at.session_state["results"]["plastic"]["interaction"]
    # Both bending axes are traced now (the either/or radio is gone); each is its own
    # closed N-M boundary running from pure tension to the squash load.
    for axis in ("x", "y"):
        assert len(d[axis]["N"]) == len(d[axis]["M"]) > 10
        assert min(d[axis]["N"]) < 0.0 < max(d[axis]["N"])   # tension to squash
    assert not any("Enable 'N-M interaction" in m.value for m in at.info)  # view rendered
    labels = [mt.label for mt in at.metric]
    assert any("Squash load" in lbl for lbl in labels)       # axial metrics show
    assert any("M_x" in lbl for lbl in labels) and any("M_y" in lbl for lbl in labels)
    frames = [frame.value for frame in at.dataframe]
    assert any({"Point", "N, Mx boundary (kN)", "Mx (kNm)",
                "N, My boundary (kN)", "My (kNm)"} <= set(frame.columns)
               for frame in frames)


def test_axial_force_is_tension_positive():
    # N is entered tension-positive: a compression (negative N) raises the flexural
    # capacity relative to pure bending, a tension (positive N) lowers it. This is the
    # boundary flip -- the solver stays compression-positive, so the physics is the
    # same, only the input sign changes.
    at = _fresh()
    at.run()

    def max_mx(P):
        _set_and_click(at, "calculate", ("number_input", "pl_P", P))
        return at.session_state["results"]["plastic"]["max_mx"]

    assert max_mx(-2000.0) > max_mx(0.0) > max_mx(2000.0)   # compression > 0 > tension


def test_nm_squash_is_negative_and_tension_limit_positive():
    # With N tension-positive the squash (pure compression) load is the minimum N and
    # the tension limit the maximum -- the opposite ends of the boundary.
    at = _fresh()
    at.run()
    at.checkbox(key="pl_interaction").set_value(True).run()
    _calculate(at)
    d = at.session_state["results"]["plastic"]["interaction"]
    all_n = list(d["x"]["N"]) + list(d["y"]["N"])
    assert min(all_n) < 0.0            # squash load is a compression (negative)
    assert max(all_n) > 0.0            # tension limit is a tension (positive)
    _select_view(at, "N-M Interaction")
    squash = next(m for m in at.metric if "Squash" in m.label)
    tens = next(m for m in at.metric if "Tension limit" in m.label)
    assert float(squash.value.split()[0]) < 0.0
    assert float(tens.value.split()[0]) > 0.0


def test_plastic_view_defaults_to_the_governing_rotation_each_calculate():
    # The Plastic view's neutral-axis state defaults to the utilisation-governing
    # rotation on every Calculate. The selectbox key persists, so without a reset it
    # would keep the previously shown rotation after the load (and its governing
    # angle) changed -- the "always 90 deg" symptom.
    at = _fresh()
    at.run()
    _set_and_click(
        at,
        "calculate",
        ("number_input", "pl_Mx", 200.0),
        ("number_input", "pl_My", 0.0),
    )  # pure Mx -> governs near V=90
    _select_view(at, "Plastic Results")
    res = at.session_state["results"]["plastic"]
    assert at.session_state["pl_state"] == res["util_gov"]
    # A biaxial load governs at a different rotation; recalculating must follow it.
    _set_and_click(
        at,
        "calculate",
        ("number_input", "pl_Mx", 150.0),
        ("number_input", "pl_My", 120.0),
    )
    res2 = at.session_state["results"]["plastic"]
    assert res2["util_gov"] != res["util_gov"]             # the governing angle changed
    assert at.session_state["pl_state"] == res2["util_gov"]
    # A manual pick between calculations is retained (only Calculate re-defaults it).
    other = (res2["util_gov"] + 3) % len(res2["points"])
    at.selectbox(key="pl_state").set_value(other).run()
    assert at.session_state["pl_state"] == other


def test_plastic_strains_are_reported_tension_positive():
    # Strains follow the tension-positive convention (like N and the stresses): a
    # crushing concrete strain reads negative and a tensile bar strain positive, even
    # though the solver computes them compression-positive internally.
    at = _fresh()
    at.run()
    _set_and_click(
        at,
        "calculate",
        ("number_input", "pl_Mx", 200.0),
        ("number_input", "pl_My", 0.0),
    )  # sagging bending, N = 0
    res = at.session_state["results"]["plastic"]
    pt = res["points"][res["util_gov"]]
    assert pt["eps_c"] < 0.0     # concrete crushing -> compression -> negative
    assert pt["eps_s"] > 0.0     # most tensile bar -> tension -> positive


def test_plastic_table_splits_steel_strain_when_active_in_compression():
    # With the mild steel active in compression the per-angle table reports both the
    # tensile and the compression bar-strain extreme (eps_s,t / eps_s,c); tension-only
    # keeps a single eps_s column.
    from sector_app import _plastic_table
    at = _fresh()
    at.run()
    _calculate(at)
    pts = at.session_state["results"]["plastic"]["points"]
    assert "eps_s_comp" in pts[0]
    active = _plastic_table(pts, False, True)
    assert any(",t (%)" in c for c in active) and any(",c (%)" in c for c in active)
    tension = _plastic_table(pts, False, False)
    assert not any(",c (%)" in c for c in tension)          # no compression column
    assert not any(",t (%)" in c for c in tension)          # the single column is eps_s


def test_plastic_view_tolerates_a_pre_split_payload():
    # A plastic payload cached before the steel-strain split (no eps_s_comp) -- e.g. a
    # reused result across a code update -- must not crash the view even with active-
    # in-compression steel (the default); it degrades to the single strain instead of
    # raising a KeyError.
    at = _fresh()
    at.run()
    _calculate(at)
    res = at.session_state["results"]
    for p in res["plastic"]["points"]:
        p.pop("eps_s_comp", None)             # simulate a pre-v0.40 reused payload
    at.session_state["results"] = res
    _select_view(at, "Plastic Results")
    assert not at.exception


def test_plastic_bar_hover_reports_stress_strain_per_bar_and_varies_with_rotation():
    # The plastic section hover reports each bar's design stress and strain at the
    # selected rotation (tension-positive): a bar on the tension side reads a positive
    # strain, one on the compression side negative, and the values change with the
    # curvature (rotation).
    from sector_app import _plastic_bar_hover
    from sector.materials import MildSteel
    steel = MildSteel(fytk=550.0, fyck=550.0, futk=600.0, eut=0.05, gamma_y=1.15,
                      gamma_u=1.15, curve=3, Es=200000.0, ey0c=2.25)
    hp = (0.0, 1.0, 0.0)                      # NA at y = 0, compression side y > 0
    bars = [(0.0, -0.1), (0.0, 0.1)]          # tension bar (y<0), compression bar (y>0)
    h = _plastic_bar_hover(bars, hp, kappa=0.05, material=steel)
    assert "MPa" in h[0]
    assert "= 0.500 %" in h[0]                # tension bar: +0.5 %
    assert "= -0.500 %" in h[1]               # compression bar: -0.5 %
    h2 = _plastic_bar_hover(bars, hp, kappa=0.10, material=steel)
    assert h2[1] != h[1]                       # a different rotation -> different values
    assert _plastic_bar_hover(bars, hp, 0.05, None) is None   # no material -> no hover


def test_both_mode_runs_elastic_and_plastic():
    at = _fresh()
    at.run()
    _set_and_click(at, "calculate", ("radio", "mode", "Both"))
    assert not at.exception
    res = at.session_state["results"]
    assert "plastic" in res and "elastic" in res


def test_plastic_and_elastic_use_independent_loads():
    # The two analyses take their own load sets; changing the elastic moment
    # must not move the plastic utilisation, and vice versa.
    at = _fresh()
    at.run()
    _set_and_click(
        at,
        "calculate",
        ("radio", "mode", "Both"),
        ("number_input", "pl_Mx", 150.0),
        ("number_input", "el_long_Mx", 50.0),
    )
    assert not at.exception
    res = at.session_state["results"]
    util0 = res["plastic"]["util"]
    stress0 = list(res["elastic"]["total"])

    _set_and_click(
        at, "calculate", ("number_input", "el_long_Mx", 120.0)
    )  # change only the elastic load
    res2 = at.session_state["results"]
    assert res2["plastic"]["util"] == pytest.approx(util0)   # plastic unchanged
    assert res2["elastic"]["total"] != stress0         # elastic changed


def test_recalculate_reuses_the_unchanged_analysis_half():
    # The staleness signature is split, so a Both-mode Calculate recomputes only the
    # half whose inputs changed and reuses the other (same result object).
    at = _fresh()
    at.run()
    _set_and_click(at, "calculate", ("radio", "mode", "Both"))
    pl1 = at.session_state["results"]["plastic"]
    el1 = at.session_state["results"]["elastic"]

    # Elastic-only change -> plastic reused (identity), elastic recomputed.
    _set_and_click(
        at, "calculate", ("number_input", "el_short_Mx", 123.0)
    )
    res = at.session_state["results"]
    assert res["plastic"] is pl1
    assert res["elastic"] is not el1
    el2 = res["elastic"]

    # Plastic-only change (sweep increment) -> elastic reused, plastic recomputed.
    _set_and_click(at, "calculate", ("number_input", "v_inc", 30.0))
    res = at.session_state["results"]
    assert res["elastic"] is el2
    assert res["plastic"] is not pl1

    # Shared change (concrete grade) -> both recomputed.
    pl3 = res["plastic"]
    _set_and_click(at, "calculate", ("number_input", "conc_fck", 40.0))
    res = at.session_state["results"]
    assert res["plastic"] is not pl3
    assert res["elastic"] is not el2


def test_load_sets_survive_a_mode_switch():
    # Both tables remain authoritative across mode changes, so values are not lost.
    at = _fresh()
    at.run()
    _set(
        at,
        ("radio", "mode", "Both"),
        ("number_input", "pl_Mx", 175.0),
        ("number_input", "el_long_Mx", 60.0),
    )
    at.radio(key="mode").set_value("Elastic").run()
    at.run()
    at.radio(key="mode").set_value("Both").run()
    assert first_case_value(at, "pl_Mx") == pytest.approx(175.0)
    assert first_case_value(at, "el_long_Mx") == pytest.approx(60.0)


def test_circular_shape_calculates():
    at = _fresh_qs()
    at.selectbox(key="shape").set_value("Circular").run()
    _apply_qs(at)                            # apply the builder to the points
    _calculate(at)
    assert not at.exception
    assert "plastic" in at.session_state["results"]


def test_builder_does_not_touch_points_until_applied():
    # The point tables drive the analysis; the Quick Section builder only writes to
    # them on Apply. Opening it, changing a dimension and pressing Back changes
    # nothing; Apply does.
    import project_io

    at = _fresh()
    at.run()
    _calculate(at)
    base_mx = at.session_state["results"]["plastic"]["max_mx"]
    base_tables = {
        key: at.session_state[key].copy(deep=True)
        for key in project_io.TABLE_KEYS
    }
    _open_qs(at)
    _set_and_click(
        at, "qs_back", ("number_input", "h_mm", 1000.0)
    )  # taller, but discarded
    for key, expected in base_tables.items():
        assert at.session_state[key].equals(expected), key

    # AppTest cannot continue reliably from the fragment-to-full-app rerun behind
    # Back because it retains removed builder nodes in its element tree. Serialize
    # the exact post-Back state into an independent session and calculate there; this
    # retains the engineering-result assertion without relying on stale test nodes.
    post_back_project = project_io.dump_project(
        {key: at.session_state[key] for key in project_io.TABLE_KEYS},
        {
            key: at.session_state[key]
            for key in project_io.SCALAR_KEYS
            if key in at.session_state
        },
    )
    post_back = _fresh()
    post_back.session_state["_pending_project"] = post_back_project
    post_back.run()
    _calculate(post_back)
    assert (
        post_back.session_state["results"]["plastic"]["max_mx"]
        == pytest.approx(base_mx)
    )

    applied = _fresh_qs()
    _set_and_click(
        applied, "qs_apply", ("number_input", "h_mm", 1000.0)
    )  # now applied
    _calculate(applied)
    assert applied.session_state["results"]["plastic"]["max_mx"] > base_mx


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
    _set_and_click(
        at, "qs_apply", ("number_input", "bot_off_d", 16.0)
    )  # 0 = off; a diameter enables it
    bars = at.session_state["bars_base"]
    areas = {round(float(a), 1) for a in bars["area (mm2)"]}
    assert len(bars) > plain                               # extra interleaved bars added
    assert len(areas) >= 2                                 # two bar sizes now present


def test_quick_section_interleave_skips_the_box_girder_void():
    # A box girder bottom layer that rises into the hollow is split across the two
    # walls; interleaving its midpoints would drop a bar into the void. The
    # interleaved bars are filtered to the concrete, so the section stays valid.
    at = _fresh_qs()
    at.selectbox(key="shape").set_value("Box girder").run()
    _set_and_click(
        at,
        "qs_apply",
        ("number_input", "bot_layers", 2),
        ("number_input", "layer_s", 300.0),
        ("number_input", "bot_off_d", 16.0),
    )  # 2nd layer rises into the hollow
    _calculate(at)
    assert not at.exception
    assert "plastic" in at.session_state["results"]        # no bar in the void -> valid section


def test_quick_section_separate_top_bottom_cover_and_manual_diameter():
    # Separate top/bottom covers place each face row at its own cover, and the bar
    # diameter is a direct mm input (a Y25 bar is 491 mm2).
    at = _fresh_qs()
    _set_and_click(
        at,
        "qs_apply",
        ("number_input", "bot_c_mm", 40.0),
        ("number_input", "top_c_mm", 60.0),
        ("number_input", "bot_d", 25.0),
    )
    b = at.session_state["bars_base"]
    ys = sorted(round(float(y), 3) for y in b["y (mm)"])
    assert min(ys) == pytest.approx(-260.0)                # -300 + 40 bottom cover
    assert max(ys) == pytest.approx(240.0)                 # 300 - 60 top cover
    assert round(float(b["area (mm2)"].iloc[0])) == 491    # Y25 area


def test_quick_section_cover_to_edge_shifts_bars_by_a_radius():
    # With cover measured to the bar edge, the bar centres sit a radius deeper than the
    # cover line (a Y25 bar at 40 mm edge cover -> centre at 40 + 12.5 = 52.5 mm).
    at = _fresh_qs()
    _set_and_click(
        at,
        "qs_apply",
        ("checkbox", "qs_cover_to_edge", True),
        ("number_input", "bot_c_mm", 40.0),
        ("number_input", "bot_d", 25.0),
    )
    yb = min(round(float(y), 2) for y in at.session_state["bars_base"]["y (mm)"])
    assert yb == pytest.approx(-247.5)                     # -300 + 40 + 12.5 radius


def test_quick_section_separate_upper_layer_bar_count():
    # A stacked bottom face can hold a different bar count in the upper layer than the
    # main row (6 in the first, 3 above).
    at = _fresh_qs()
    _set_and_click(
        at,
        "qs_apply",
        ("number_input", "bot_n", 6),
        ("number_input", "bot_layers", 2),
        ("number_input", "bot_n2", 3),
    )
    from collections import Counter
    counts = Counter(round(float(y), 3) for y in at.session_state["bars_base"]["y (mm)"])
    assert sorted(counts.values(), reverse=True)[:2] == [6, 3]


def test_quick_section_builder_places_bars_by_spacing():
    # The builder opens full-width, places slab bars at a target spacing, and Apply
    # writes the generated points into the tables (which then analyse).
    at = _fresh_qs()
    assert any(b.key == "qs_apply" for b in at.button)    # the builder is showing
    at.selectbox(key="shape").set_value("Slab strip").run()
    _set(at, ("radio", "qs_rebar_mode", "By spacing"))
    _set_and_click(
        at,
        "qs_apply",
        ("number_input", "bot_s", 150.0),
        ("number_input", "top_s", 150.0),
    )
    assert not at.exception
    # 1 m slab, 50 mm cover -> a 0.9 m face at 150 mm gives 7 bars per row (14 total).
    assert len(at.session_state["bars_base"]) == 14
    _calculate(at)
    assert not at.exception


def test_quick_section_builder_stacks_multiple_bar_layers():
    # Two bottom layers stack the 6 bottom bars at two y-levels (12), plus the 2 top
    # bars = 14; the second layer sits one layer-spacing above the bottom cover line.
    at = _fresh_qs()
    _set_and_click(
        at,
        "qs_apply",
        ("number_input", "bot_layers", 2),
        ("number_input", "layer_s", 60.0),
    )
    assert not at.exception
    bars = at.session_state["bars_base"]
    assert len(bars) == 14                          # 2 x 6 bottom + 1 x 2 top
    ys = sorted(round(float(y), 1) for y in set(bars["y (mm)"]))
    # 600 mm section, 50 mm cover: bottom rows at -250 and -190 mm, top at 250 mm.
    assert ys == [-250.0, -190.0, 250.0]
    _calculate(at)
    assert not at.exception


def test_quick_section_builder_stacks_tendon_layers():
    # Two tendon layers place the tendons at two y-levels stacked up from the bottom.
    at = _fresh_qs()
    _set_and_click(
        at,
        "qs_apply",
        ("number_input", "tnd_n", 3),
        ("number_input", "tnd_layers", 2),
        ("number_input", "tnd_layer_s", 60.0),
    )
    assert not at.exception
    tendons = at.session_state["tendons_base"]
    assert len(tendons) == 6                          # 2 layers x 3 tendons
    ys = sorted(round(float(y), 1) for y in set(tendons["y (mm)"]))
    # 100 mm tendon cover from the -300 mm bottom face -> -200, then +60 -> -140.
    assert ys == [-200.0, -140.0]
    _calculate(at)
    assert not at.exception


def test_quick_section_box_tendon_layer_splits_into_walls():
    # A box girder tendon layer that rises into the hollow is split into the side
    # walls, preserving the count, rather than placing a tendon in the cavity (the
    # alternative to dropping). Defaults: 800x1000x200 box, 100 mm cover; layer 2
    # (150 mm up, y=-250) is in the hollow.
    at = _fresh_qs()
    at.selectbox(key="shape").set_value("Box girder").run()
    _set_and_click(
        at,
        "qs_apply",
        ("number_input", "tnd_n", 3),
        ("number_input", "tnd_layers", 2),
        ("number_input", "tnd_layer_s", 150.0),
    )
    assert not at.exception
    tendons = at.session_state["tendons_base"]
    assert len(tendons) == 6                          # count preserved (3 per layer)
    assert not any("within the concrete" in (e.value or "") for e in at.error)
    hollow = tendons[(tendons["y (mm)"] > -260) & (tendons["y (mm)"] < -240)]
    assert len(hollow) == 3                           # the hollow layer keeps its 3
    assert (hollow["x (mm)"].abs() >= 200).all()      # in the side walls, not the cavity
    _calculate(at)
    assert not at.exception
    assert "plastic" in at.session_state["results"]


def test_quick_section_circular_zero_cover_keeps_all_bars():
    # At zero cover the ring radius is capped at the polygon apothem, so every bar
    # stays inside the N-gon outline and none are dropped/rejected (Codex P2).
    at = _fresh_qs()
    at.selectbox(key="shape").set_value("Circular").run()
    _set_and_click(
        at,
        "qs_apply",
        ("number_input", "ring_n", 10),
        ("number_input", "ring_c_mm", 0.0),
    )
    assert not at.exception
    assert len(at.session_state["bars_base"]) == 10            # all 10 placed
    assert not any("within the concrete" in (e.value or "") for e in at.error)
    _calculate(at)
    assert not at.exception
    assert "plastic" in at.session_state["results"]


def test_quick_section_tsection_lower_top_layer_fits_the_web():
    # A T-section's top face is the flange; a lower top layer pushed below the flange
    # must narrow to the web, or it would sit outside the concrete and be rejected.
    at = _fresh_qs()
    at.selectbox(key="shape").set_value("T-section").run()
    _set_and_click(
        at,
        "qs_apply",
        ("number_input", "top_layers", 2),
        ("number_input", "layer_s", 250.0),
    )  # pushes layer 2 into the web
    assert not at.exception
    assert not any("within the concrete" in (e.value or "") for e in at.error)
    bars = at.session_state["bars_base"]
    lower_top = bars[(bars["y (mm)"] > 50) & (bars["y (mm)"] < 150)]   # the y=100 mm row
    assert len(lower_top) >= 1
    assert lower_top["x (mm)"].abs().max() <= 110           # within the web (bw/2 - cover)
    _calculate(at)
    assert not at.exception
    assert "plastic" in at.session_state["results"]


def test_quick_section_tsection_spaced_web_layer_has_fewer_bars():
    # By spacing, a T-section top layer narrowed to the web keeps the target spacing,
    # so it has far fewer bars than the flange row (not the flange count crammed in).
    at = _fresh_qs()
    at.selectbox(key="shape").set_value("T-section").run()
    _set(at, ("radio", "qs_rebar_mode", "By spacing"))
    _set_and_click(
        at,
        "qs_apply",
        ("number_input", "top_s", 150.0),
        ("number_input", "top_layers", 2),
        ("number_input", "layer_s", 250.0),
    )  # lower row into the web
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
    at = _fresh_qs()
    at.selectbox(key="shape").set_value("T-section").run()
    _set_and_click(
        at, "qs_back", ("number_input", "bf_mm", 1500.0)
    )  # close with settings kept
    _open_qs(at)
    assert at.selectbox(key="shape").value == "T-section"
    assert at.number_input(key="bf_mm").value == pytest.approx(1500.0)


def test_point_tables_are_data_only_and_hold_loaded_points():
    # The point tables hold just the coordinate columns (no stored ID -- the plot
    # numbers points by row order); the builder Apply fills them.
    at = _fresh_qs()
    _set_and_click(at, "qs_apply", ("number_input", "tnd_n", 4))
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


def test_clear_section_requires_confirmation_and_undo_restores_all_tables():
    # A first click cannot delete data. Cancel leaves the exact tables unchanged;
    # confirmation clears all four, and the one-step undo restores them exactly.
    from pandas.testing import assert_frame_equal

    at = _fresh_qs()
    _set_and_click(
        at, "qs_apply", ("number_input", "tnd_n", 4)
    )  # populate with tendons
    bases = ("corners_base", "hole_base", "bars_base", "tendons_base")
    before = {base: at.session_state[base].copy(deep=True) for base in bases}

    at.button(key="clear_pts").click().run()
    assert not at.exception
    for base in bases:
        assert_frame_equal(at.session_state[base], before[base])
    assert at.button(key="confirm_clear_pts")
    assert at.button(key="cancel_clear_pts")

    at.button(key="cancel_clear_pts").click().run()
    for base in bases:
        assert_frame_equal(at.session_state[base], before[base])

    _clear_section(at)
    assert not at.exception
    for base in bases:
        assert len(at.session_state[base]) == 0
    assert at.button(key="undo_clear_pts")

    at.button(key="undo_clear_pts").click().run()
    assert not at.exception
    for base in bases:
        assert_frame_equal(at.session_state[base], before[base])


def test_quick_section_apply_supersedes_clear_undo():
    at = _fresh()
    at.run()
    _clear_section(at)
    assert "_clear_section_undo" in at.session_state

    _open_qs(at)
    _apply_qs(at)
    assert not at.exception
    assert "_clear_section_undo" not in at.session_state
    assert len(at.session_state["corners_base"]) >= 3


def test_unversioned_pre_upgrade_grid_value_cannot_cancel_clear_undo():
    # A browser tab carried over from the old frontend can report one final plain
    # list after the new app has bumped the grid seed. It is not authoritative:
    # the cleared base and its recovery snapshot must remain intact.
    at = _fresh()
    at.run()
    _clear_section(at)
    at.session_state["ed_corners"] = [
        {"x (mm)": -999.0, "y (mm)": -999.0},
        {"x (mm)": 999.0, "y (mm)": -999.0},
        {"x (mm)": 0.0, "y (mm)": 999.0},
    ]
    at.run()
    assert not at.exception
    assert at.session_state["corners_base"].empty
    assert "_clear_section_undo" in at.session_state


def test_cleared_section_does_not_fall_back_to_quick_section():
    # After Clear Section the source-of-truth outline is genuinely empty -- it must
    # not revert to the Quick Section. The co-located preview and a Calculate run
    # without error, and no results are produced (the section is blank).
    at = _fresh()
    at.run()
    _clear_section(at)
    _goto_input_tab(at, "Section")
    assert not at.exception
    _calculate(at)
    assert not at.exception
    assert at.session_state["results"] == {}


def test_blank_and_partial_point_rows_are_skipped():
    # A blank row and a half-typed point (x with no y) and a non-numeric paste are
    # ignored, never crash, and only the complete numeric rows become points.
    import pandas as pd
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    _replace_base_table(at, "bars_base", pd.DataFrame(
        {"x (mm)": [50.0, None, 150.0, "oops"],   # row 2 blank, row 4 non-numeric
         "y (mm)": [50.0, 50.0, None, 50.0],       # row 3 half-typed (no y)
         "area (mm2)": [491.0, 491.0, 491.0, 491.0]}))
    _calculate(at)
    assert not at.exception
    assert len(at.session_state["results"]["elastic"]["total"]) == 1   # one valid bar


def test_box_girder_void_loads_and_calculates():
    # The box cavity loads into the (data-only) void table and the section still
    # calculates.
    at = _fresh_qs()
    at.selectbox(key="shape").set_value("Box girder").run()
    _apply_qs(at)
    hb = at.session_state["hole_base"]
    assert len(hb) >= 3 and list(hb.columns) == ["x (mm)", "y (mm)"]
    _calculate(at)
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
    _calculate(at)
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
    # The fourth row is an unsaved corner reported by the current grid seed.
    at.session_state["ed_hole"] = {"payload": {
        "data_version": str(at.session_state["ed_hole_ver"]),
        "rows": [
            {"x (mm)": -100.0, "y (mm)": -50.0},
            {"x (mm)": -40.0, "y (mm)": -50.0},
            {"x (mm)": -70.0, "y (mm)": 50.0},
            {"x (mm)": 80.0, "y (mm)": -50.0},
        ],
    }}
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
    # The current grid seed reports that every row was deleted.
    at.session_state["ed_hole"] = {
        "data_version": str(at.session_state["ed_hole_ver"]),
        "rows": [],
    }
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
    at = _fresh_qs()
    _apply_qs(at)                            # default rectangle, no cavity
    assert len(at.session_state["hole_base"]) == 0


def test_injected_void_changes_the_capacity():
    # A void carved out of the compression zone removes concrete, so the plastic
    # +Mx capacity changes -- the void table drives the section.
    import pandas as pd
    at = _fresh()
    at.run()
    _calculate(at)
    solid_mx = at.session_state["results"]["plastic"]["max_mx"]
    _replace_base_table(at, "hole_base", pd.DataFrame(
        {"x (mm)": [-150.0, 150.0, 150.0, -150.0],
         "y (mm)": [100.0, 100.0, 280.0, 280.0]}))  # void in the compression top
    _calculate(at)
    assert not at.exception
    assert at.session_state["results"]["plastic"]["max_mx"] != pytest.approx(solid_mx)


def test_void_slicing_the_section_is_rejected():
    # A slot reaching across the full width disconnects the concrete: the app flags
    # it and refuses to compute a capacity.
    import pandas as pd
    at = _fresh()
    at.run()
    _replace_base_table(at, "hole_base", pd.DataFrame(
        {"x (mm)": [-250.0, 250.0, 250.0, -250.0],
         "y (mm)": [-20.0, -20.0, 20.0, 20.0]}))      # full-width slot at mid-height
    _goto_page(at, "Analysis")
    assert any("disconnected" in e.value for e in at.error)
    _calculate(at)
    assert not at.exception
    assert "plastic" not in at.session_state["results"]


def test_bar_outside_the_concrete_is_rejected():
    # A bar beyond the concrete outline carries no force: the app flags it and
    # refuses to compute (the default section spans y in [-300, 300] mm).
    import pandas as pd
    at = _fresh()
    at.run()
    _replace_base_table(at, "bars_base", pd.DataFrame(
        {"x (mm)": [0.0], "y (mm)": [1000.0], "area (mm2)": [314.0]}))
    _goto_page(at, "Analysis")
    assert any("within the concrete" in e.value for e in at.error)
    _calculate(at)
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
    _calculate(at)
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
    _calculate(at)
    assert not at.exception
    assert "plastic" in at.session_state["results"]


def test_load_project_restores_section_and_calculates():
    # A pending uploaded project is applied before the widgets are built: the point
    # tables and scalar inputs are restored and the section calculates.
    import json
    at = _fresh()
    at.run()
    _calculate(at)
    assert "results" in at.session_state
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
    assert "results" not in at.session_state
    _calculate(at)
    assert not at.exception
    assert "plastic" in at.session_state["results"]


def test_save_load_round_trip_through_the_app():
    # Editing fck, then gathering and re-applying the project, preserves the value.
    import sys as _sys
    at = _fresh()
    at.run()
    _set(
        at,
        ("number_input", "conc_fck", 48.0),
        ("text_input", "pl_case_id", "PL-ROUNDTRIP"),
        ("text_input", "pl_case_source", "Register C7"),
    )
    _sys.path.insert(0, str(pathlib.Path(APP).resolve().parent))
    import project_io  # noqa: E402  (app dir is on sys.path once the app has run)
    text = project_io.dump_project(
        {k: at.session_state[k] for k in project_io.PROJECT_TABLE_KEYS
         if k in at.session_state},
        {k: at.session_state[k] for k in project_io.SCALAR_KEYS if k in at.session_state})
    assert '"format": "sector-project"' in text
    at.number_input(key="conc_fck").set_value(20.0).run()
    at.session_state["_pending_project"] = text
    at.run()
    assert at.session_state["conc_fck"] == 48.0
    plastic = at.session_state["plastic_cases_base"]
    assert plastic.loc[0, "name"] == "PL-ROUNDTRIP"
    assert plastic.loc[0, "description"] == "Source: Register C7"
    assert at.session_state["_loaded_project_provenance"]["input_hash_valid"] is True
    assert any("hash verified" in caption.value for caption in at.caption)


def test_v4_case_tables_follow_current_controls_and_preserve_later_rows():
    import sys as _sys

    at = _fresh()
    at.run()
    _set(at, ("radio", "mode", "Both"))
    _set(
        at,
        ("text_input", "pl_case_id", "PL-CURRENT"),
        ("number_input", "pl_Mx", -125.0),
        ("text_input", "el_case_id", "EL-CURRENT"),
        ("checkbox", "sls_cw", True),
    )
    _sys.path.insert(0, str(pathlib.Path(APP).resolve().parent))
    import load_cases  # noqa: E402
    import project_io  # noqa: E402

    plastic = at.session_state[load_cases.PLASTIC_TABLE_KEY]
    elastic = at.session_state[load_cases.ELASTIC_TABLE_KEY]
    assert plastic.loc[0, "name"] == "PL-CURRENT"
    assert plastic.loc[0, "mx_ed_knm"] == pytest.approx(-125.0)
    assert elastic.loc[0, "name"] == "EL-CURRENT"
    assert bool(elastic.loc[0, "check_crack_width"]) is True

    plastic = load_cases.normalise_table([
        *plastic.to_dict("records"),
        {"name": "PL-LATER", "mx_ed_knm": 75.0},
    ], load_cases.PLASTIC_TABLE_KEY)
    text = project_io.dump_project(
        {
            **{key: at.session_state[key] for key in project_io.TABLE_KEYS},
            load_cases.PLASTIC_TABLE_KEY: plastic,
            load_cases.ELASTIC_TABLE_KEY: elastic,
        },
        {
            key: at.session_state[key]
            for key in project_io.SCALAR_KEYS
            if key in at.session_state
        },
    )
    at.session_state["_pending_project"] = text
    at.run()
    assert at.session_state[load_cases.PLASTIC_TABLE_KEY]["name"].tolist() == [
        "PL-CURRENT", "PL-LATER"
    ]
    assert at.session_state[load_cases.PLASTIC_TABLE_KEY].loc[0, "name"] == "PL-CURRENT"
    assert not at.exception


def test_v4_multiple_case_rows_each_run_through_verified_solvers():
    import load_cases

    at = _fresh()
    at.run()
    _set(at, ("radio", "mode", "Both"))
    plastic = at.session_state[load_cases.PLASTIC_TABLE_KEY]
    elastic = at.session_state[load_cases.ELASTIC_TABLE_KEY]
    first_plastic_name = str(plastic.loc[0, "name"])
    first_elastic_name = str(elastic.loc[0, "name"])
    _replace_case_table(at, load_cases.PLASTIC_TABLE_KEY, [
        *plastic.to_dict("records"),
        {
            "name": "PL-SECOND",
            "description": "Second plastic row",
            "n_ed_kn": -100.0,
            "mx_ed_knm": 75.0,
            "my_ed_knm": -10.0,
        },
    ])
    _replace_case_table(at, load_cases.ELASTIC_TABLE_KEY, [
        *elastic.to_dict("records"),
        {
            "name": "EL-SECOND",
            "description": "Second elastic row",
            "mx_long_ed_knm": 35.0,
            "mx_short_ed_knm": 10.0,
            "check_stress": True,
            "check_crack_width": False,
        },
    ])

    _calculate(at)
    results = at.session_state["results"]

    assert [entry["name"] for entry in results["plastic_cases"]] == [
        first_plastic_name, "PL-SECOND"
    ]
    assert [entry["name"] for entry in results["elastic_cases"]] == [
        first_elastic_name, "EL-SECOND"
    ]
    assert all("plastic" in entry["results"]
               for entry in results["plastic_cases"])
    assert all("elastic" in entry["results"]
               for entry in results["elastic_cases"])
    assert results["plastic_cases"][1]["results"]["plastic"]["applied"] == (
        75.0, -10.0
    )
    assert not at.exception


def test_invalid_hidden_case_row_is_reported_before_calculation():
    import load_cases

    at = _fresh()
    at.run()
    _set(at, ("radio", "mode", "Both"))
    plastic = at.session_state[load_cases.PLASTIC_TABLE_KEY]
    elastic_name = str(
        at.session_state[load_cases.ELASTIC_TABLE_KEY].loc[0, "name"]
    )
    _replace_case_table(at, load_cases.PLASTIC_TABLE_KEY, [
        *plastic.to_dict("records"),
        {"name": elastic_name.swapcase(), "mx_ed_knm": 20.0},
    ])

    _calculate(at)

    assert any("duplicated" in error.value for error in at.error)
    assert not at.exception


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


def test_due_autosave_runs_from_analysis_page(tmp_path, monkeypatch):
    # A genuine Analysis-fragment interaction must service a due autosave even
    # though input widgets and the top-level dispatcher are not rerun (second
    # independent Codex review P2).
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path))
    at = _fresh()
    at.run()
    at.number_input(key="conc_fck").set_value(42.0).run()
    _goto_page(at, "Analysis")
    assert not (tmp_path / "autosave.json").exists()
    at.session_state["_autosave_t"] = 0.0
    at.selectbox(key="view").set_value("Plastic Results").run()

    saved = tmp_path / "autosave.json"
    assert saved.exists()
    import sys as _sys
    _sys.path.insert(0, str(pathlib.Path(APP).resolve().parent))
    import project_io  # noqa: E402
    _, scalars = project_io.parse_project(saved.read_text(encoding="utf-8"))
    assert scalars["conc_fck"] == pytest.approx(42.0)


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
    at = _fresh_qs()
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


def test_load_old_2023_project_migrates_to_general_k_tc():
    # Older projects did not store k_tc and could carry a manually edited effective
    # alpha_cc.  Reloading an identified 2023 preset must derive the normative
    # eta_cc*k_tc value and use the safe general-case default, not preserve a stale
    # coefficient that contradicts the displayed edition.
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
    assert at.session_state["conc_k_tc"] == pytest.approx(0.85)
    assert at.session_state["conc_alpha_cc"] == pytest.approx(0.85)
    assert at.number_input(key="conc_alpha_cc").disabled is True


def test_load_2023_project_preserves_explicit_k_tc_choice():
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
            "tendons_base": {"columns": ["x (mm)", "y (mm)", "area (mm2)"],
                             "rows": []},
        },
        "scalars": {"conc_preset": "DS/EN 1992-1-1:2023", "conc_fck": 50.0,
                    "conc_k_tc": 1.0, "conc_alpha_cc": 0.5, "mode": "Plastic"},
    }
    at.session_state["_pending_project"] = json.dumps(project)
    at.run()
    assert not at.exception
    eta_50 = (40.0 / 50.0) ** (1.0 / 3.0)
    assert at.session_state["conc_k_tc"] == pytest.approx(1.0)
    assert at.session_state["conc_alpha_cc"] == pytest.approx(eta_50)
    assert any("explicitly assuming" in warning.value for warning in at.warning)


def test_generate_report_produces_pdf():
    # The Report panel's Generate button builds a PDF from the current section
    # (figures skipped in the test so it does not need a browser).
    at = _fresh()
    at.run()
    at.session_state["_report_no_figures"] = True
    at.session_state["rep_proj_no"] = "T-1"
    at.session_state["rep_section"] = "S/1"
    at.session_state["rep_rev"] = "A:2"
    at.button(key="gen_report").click().run()
    assert not at.exception
    assert "report_buffer" in at.session_state
    assert at.session_state["report_buffer"][:4] == b"%PDF"
    assert "report_signature" in at.session_state
    assert at.session_state["report_filename"].startswith(
        "Sector_T-1_S-1_Rev-A-2_"
    )
    assert at.session_state["report_filename"].endswith(".pdf")


def test_report_download_becomes_stale_after_metadata_change():
    at = _fresh()
    at.run()
    at.session_state["_report_no_figures"] = True
    at.session_state["rep_proj_no"] = "T-1"
    at.session_state["rep_section"] = "S/1"
    at.session_state["rep_rev"] = "A:2"
    at.button(key="gen_report").click().run()
    assert not any("Report out of date" in w.value for w in at.warning)

    at.text_input(key="rep_rev").set_value("B").run()
    assert any("Report out of date" in w.value for w in at.warning)


def test_report_download_becomes_stale_after_analysis_input_change():
    at = _fresh()
    at.run()
    at.session_state["_report_no_figures"] = True
    at.button(key="gen_report").click().run()
    assert not any("Report out of date" in w.value for w in at.warning)

    _set(at, ("number_input", "pl_Mx", 123.0))
    assert any("Report out of date" in w.value for w in at.warning)


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


def test_partial_v4_project_does_not_inherit_previous_case_tables():
    import json

    at = _fresh()
    at.run()
    _set(at, ("text_input", "pl_case_id", "PL-PREVIOUS"))
    project = {
        "format": "sector-project",
        "version": 4,
        "tables": {},
        "scalars": {"mode": "Plastic"},
    }
    at.session_state["_pending_project"] = json.dumps(project)
    at.run()

    assert not at.exception
    assert at.session_state["plastic_cases_base"].loc[0, "name"] == "PL-01"
    assert not any(
        key in at.session_state
        for key in (
            "pl_case_id", "pl_P", "pl_Mx", "pl_My", "shear_V", "torsion_T"
        )
    )


def test_capacity_only_toggle_drops_utilisation_without_locking_case_table():
    # With utilisation checking off, the result is capacity-only. The case table
    # stays editable because its actions may still feed other requested checks.
    at = _fresh()
    at.run()
    at.checkbox(key="pl_check_util").set_value(False).run()
    assert any(frame.key == "plastic_cases_editor" for frame in at.dataframe)
    _calculate(at)
    assert not at.exception
    pl = at.session_state["results"]["plastic"]
    assert pl["util"] is None and pl["check_util"] is False and pl["applied"] is None
    assert at.session_state["view"] == "Results Overview"
    _select_view(at, "Plastic Results")
    assert any("NOT ASSESSED - Plastic bending" in item.value
               and "capacity only" in item.value.lower()
               for item in at.warning)


def test_shear_method_changes_do_not_lock_the_case_table():
    from sector import codes

    # The Plastic table remains editable in any solver mode. The 2023 shear method
    # consumes MEd, while the 2005 method simply ignores that component.
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.checkbox(key="shear_on").set_value(True).run()
    at.selectbox(key="shear_method").set_value(codes.EC2_2023.label).run()
    assert any(frame.key == "plastic_cases_editor" for frame in at.dataframe)
    assert at.number_input(key="conc_gamma_c").disabled is False
    assert at.number_input(key="mild_gamma_y").disabled is False
    _set(at, ("number_input", "pl_Mx", 110.0))
    assert not at.exception

    # The 2005 method has no action-moment term, but changing method must not imply
    # that the table belongs to a particular limit state or solver.
    at.selectbox(key="shear_method").set_value(codes.EC2_2005_DKNA.label).run()
    assert any(frame.key == "plastic_cases_editor" for frame in at.dataframe)
    assert at.number_input(key="conc_gamma_c").disabled is False


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
    _set_and_click(
        at,
        "conc_Ec_auto",
        ("radio", "mode", "Both"),
        ("number_input", "conc_fck", 70.0),
    )  # high grade -> EC2 secant Ec for C70
    ec70 = at.session_state["conc_Ec"]
    # Manually push the auto values off their derived values.
    _set_and_click(
        at,
        "auto_all_btn",
        ("number_input", "conc_eps_cu2", 5.0),
        ("number_input", "conc_Ec", 20.0),
    )
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
    _set(
        at,
        ("radio", "mode", "Both"),
        ("selectbox", "conc_preset", "DS/EN 1992-1-1:2023"),
    )
    _set_and_click(
        at,
        "auto_all_btn",
        ("number_input", "conc_fck", 70.0),
        ("number_input", "conc_eps_cu2", 2.0),
    )  # skew it, then restore the 2023 constants
    assert not at.exception
    # Constant 0.2%/0.35%/2 -- NOT the Table 3.1 value (~2.66 permille) for C70.
    assert at.session_state["conc_eps_cu2"] == pytest.approx(3.5)
    assert at.session_state["conc_eps_c2"] == pytest.approx(2.0)
    assert at.session_state["conc_n"] == pytest.approx(2.0)


def test_material_preset_switch_calculates():
    at = _fresh()
    at.run()
    _set_and_click(
        at,
        "calculate",
        ("selectbox", "conc_preset", "DS/EN 1992-1-1:2023"),
        ("selectbox", "mild_preset", "Curve 2 (elastic-perfectly-plastic)"),
    )
    assert not at.exception
    assert "plastic" in at.session_state["results"]


def test_2023_concrete_fck_edit_calculates():
    # Editing fck under the strength-dependent 2023 preset (alpha_cc tracks fck).
    at = _fresh()
    at.run()
    at.selectbox(key="conc_preset").set_value("DS/EN 1992-1-1:2023").run()
    _set_and_click(
        at, "calculate", ("number_input", "conc_fck", 50.0)
    )
    assert not at.exception
    assert at.session_state["conc_alpha_cc"] == pytest.approx(
        0.85 * (40.0 / 50.0) ** (1.0 / 3.0)
    )
    assert "plastic" in at.session_state["results"]


def test_2023_concrete_k_tc_is_explicit_and_updates_fcd():
    at = _fresh()
    at.run()
    at.selectbox(key="conc_preset").set_value("DS/EN 1992-1-1:2023").run()
    assert at.session_state["conc_k_tc"] == pytest.approx(0.85)
    fcd_general = 0.85 * at.session_state["conc_fck"] / at.session_state["conc_gamma_c"]
    assert at.session_state["conc_alpha_cc"] == pytest.approx(0.85)

    at.selectbox(key="conc_k_tc").set_value(1.0).run()
    assert not at.exception
    assert at.session_state["conc_alpha_cc"] == pytest.approx(1.0)
    assert any("explicitly assuming" in warning.value for warning in at.warning)
    assert fcd_general < (
        at.session_state["conc_alpha_cc"] * at.session_state["conc_fck"]
        / at.session_state["conc_gamma_c"]
    )


def test_design_basis_summary_identifies_alignment_and_limitations():
    import sector_app

    aligned = sector_app._design_basis_summary(
        concrete_preset="DS/EN 1992-1-1:2023",
        mild_preset="DS/EN 1992-1-1:2023",
        crack_code="EN 1992-1-1:2023",
        shear_method="DS/EN 1992-1-1:2023",
    )
    assert aligned["mixed"] is False
    assert aligned["families"] == ["EN 1992-1-1:2023"]
    assert "Edition-aligned" in aligned["status"]

    limited = sector_app._design_basis_summary(
        concrete_preset="DS/EN 1992-1-1:2023",
        mild_preset="DS/EN 1992-1-1:2023",
        shear_method="DS/EN 1992-1-1:2023",
        shear_links=True,
        torsion_method="DS/EN 1992-1-1:2005 + DK NA:2024",
        combined_method="DS/EN 1992-1-1:2005 + DK NA:2024",
    )
    assert limited["mixed"] is True
    assert any("8.2.3" in item for item in limited["limitations"])
    assert any("does not implement" in item for item in limited["limitations"])

    # An unused material selector must not create a false mixed-edition warning.
    tendon_only = sector_app._design_basis_summary(
        concrete_preset="DS/EN 1992-1-1:2023",
        mild_preset=None,
        prestress_preset="DS/EN 1992-1-1:2023",
    )
    assert tendon_only["mixed"] is False
    assert all(
        component["role"] != "Reinforcing steel"
        for component in tendon_only["components"]
    )

    crack_only_2023 = sector_app._design_basis_summary(
        concrete_preset="DS/EN 1992-1-1:2005 + DK NA:2024",
        mild_preset="DS/EN 1992-1-1:2005 + DK NA:2024",
        crack_code="EN 1992-1-1:2023",
        torsion_method="DS/EN 1992-1-1:2005 + DK NA:2024",
    )
    assert crack_only_2023["mixed"] is True
    assert crack_only_2023["limitations"] == []


def test_es_field_present_and_editable():
    # The steel modulus Es/Ep is a direct input for both materials (the prestress
    # panel is always shown, like mild steel).
    at = _fresh()
    at.run()
    keys = {ni.key for ni in at.number_input}
    assert "mild_Es" in keys and "pre_Es" in keys
    at.number_input(key="mild_Es").set_value(210.0).run()   # GPa
    assert not at.exception
    _calculate(at)
    assert not at.exception
    assert "plastic" in at.session_state["results"]


def test_eut_below_yield_strain_warns_and_calculates():
    # Meaningful constraint: a rupture strain below the yield strain is clamped
    # with a warning rather than accepted.
    at = _fresh()
    at.run()
    at.number_input(key="mild_eut").set_value(0.5).run()  # 0.5 permille, below ey ~ 2.5
    assert any("yield strain" in w.value for w in at.warning)
    _calculate(at)
    assert not at.exception


def test_two_yield_fields_live_under_default_preset():
    # The default preset builds the general law, so editing a two-yield field
    # (k) is accepted and recomputes without error.
    at = _fresh()
    at.run()
    at.number_input(key="mild_k").set_value(0.8).run()
    at.number_input(key="mild_ey0t").set_value(3.0).run()  # 3 permille
    assert not at.exception
    _calculate(at)
    assert not at.exception


def test_mild_fyck_zero_is_allowed_and_calculates():
    # The old 100 MPa floor on fyck is gone; zero compression yield must be a
    # valid input and still compute.
    at = _fresh()
    at.run()
    at.number_input(key="mild_fyck").set_value(0.0).run()
    assert not at.exception
    _calculate(at)
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
    at = _fresh_qs(mode="Elastic")
    _set_and_click(
        at, "qs_apply", ("number_input", "tnd_n", 4)
    )  # put tendons in the section
    _set_and_click(
        at,
        "calculate",
        ("number_input", "pre_IS", 5.0),
        ("number_input", "el_long_Mx", 200.0),
    )
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    assert e["prestress"] is not None and e["prestress"][0] != 0.0   # applied + reported
    base_conc = e["max_conc"]
    _set_and_click(
        at, "calculate", ("number_input", "pre_IS", 9.0)
    )  # stronger prestress
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
    # fctm and Ec only affect the elastic results, so plastic-only mode
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
    _calculate(at)
    base = at.session_state["results"]["plastic"]["max_mx"]
    _set(at, ("checkbox", "mild_active_comp", False))
    assert at.number_input(key="mild_fyck").disabled is True
    _calculate(at)
    assert not at.exception
    assert at.session_state["results"]["plastic"]["max_mx"] < base


def test_elastic_calculates_with_locked_materials():
    # Locking the laws must not break the elastic run.
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    _calculate(at)
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
    _calculate(at)
    assert not at.exception


def test_inputs_carry_help_tooltips():
    # Inputs across the panels expose hover help (the "?" tooltip).
    at = _fresh()
    at.run()
    for key in ("conc_fck", "mild_fytk", "mild_eut", "el_phi"):
        w = (_widget(at.number_input, key) or _widget(at.selectbox, key)
             or _widget(at.radio, key))
        assert w is not None and w.help, key
    assert at.radio(key="mode").help
    _goto_page(at, "Analysis")
    assert at.selectbox(key="view").help
    # The Quick Section builder inputs carry help too.
    _open_qs(at)
    for key in ("shape", "b_mm", "h_mm", "bot_c_mm", "top_c_mm"):
        w = _widget(at.number_input, key) or _widget(at.selectbox, key)
        assert w is not None and w.help, key


def _widget(seq, key):
    for w in seq:
        if w.key == key:
            return w
    return None


def test_label_controls_live_beside_the_section_inputs():
    # Drawing controls stay with the co-located section preview.
    at = _fresh()
    at.run()
    _goto_input_tab(at, "Section")
    keys = {ni.key for ni in at.number_input}
    assert "label_scale" in keys and "label_min_gap" in keys
    at.number_input(key="label_min_gap").set_value(0.2).run()
    at.number_input(key="label_scale").set_value(1.5).run()
    assert not at.exception


def test_workspace_choices_survive_quick_section_viewport():
    # Quick Section temporarily removes the workspace widgets. Streamlit cleans up
    # widget-owned state when that happens, so durable copies must restore both the
    # selected result view and the user's plot-label settings on return.
    at = _fresh()
    at.run()
    _set_and_click(
        at,
        "calculate",
        ("number_input", "label_scale", 1.5),
        ("number_input", "label_min_gap", 0.2),
    )
    assert at.session_state["view"] == "Results Overview"
    _open_qs(at)
    at.button(key="qs_back").click().run()
    _goto_page(at, "Analysis")
    assert at.session_state["view"] == "Results Overview"
    _goto_input_tab(at, "Section")
    assert at.number_input(key="label_scale").value == pytest.approx(1.5)
    assert at.number_input(key="label_min_gap").value == pytest.approx(0.2)
    assert not at.exception


def test_view_dropdown_switches_without_error():
    # Analysis contains calculated result views only; each renders before a run.
    at = _fresh()
    at.run()
    for v in ["Results Overview", "Plastic Results", "Elastic Results"]:
        _select_view(at, v)
        assert not at.exception, v


def test_prestress_curve_is_co_located_with_its_inputs():
    at = _fresh_qs()
    at.number_input(key="tnd_n").set_value(4).run()
    _apply_qs(at)                            # put tendons in the section
    _goto_material_tab(at, "Prestressing steel")
    assert "prestress" in at.session_state["_fig_cache"]
    assert not at.exception


def test_results_views_render_after_calculate():
    at = _fresh()
    at.run()
    _set_and_click(at, "calculate", ("radio", "mode", "Both"))
    for v in ["Results Overview", "Plastic Results", "Elastic Results"]:
        _select_view(at, v)
        assert not at.exception, v


def test_native_load_case_editors_use_consistent_ed_columns():
    at = _fresh()
    at.run()

    plastic = _widget(at.dataframe, "plastic_cases_editor").value
    elastic = _widget(at.dataframe, "elastic_cases_editor").value
    assert list(plastic.columns) == [
        "name", "description", "n_ed_kn", "mx_ed_knm", "my_ed_knm",
        "v_ed_kn", "t_ed_knm",
    ]
    assert list(elastic.columns) == [
        "name", "description",
        "n_long_ed_kn", "mx_long_ed_knm", "my_long_ed_knm",
        "n_short_ed_kn", "mx_short_ed_knm", "my_short_ed_knm",
        "check_stress", "check_crack_width",
    ]
    rendered_keys = {
        widget.key
        for widgets in (at.number_input, at.text_input, at.checkbox)
        for widget in widgets
    }
    assert not rendered_keys.intersection({
        "pl_P", "pl_Mx", "pl_My", "shear_V", "torsion_T",
        "el_long_P", "el_long_Mx", "el_long_My",
        "el_short_P", "el_short_Mx", "el_short_My", "sls_cw",
    })


def test_multi_case_overview_and_result_picker_show_selected_actions():
    import load_cases

    at = _fresh()
    at.run()
    _replace_case_table(at, load_cases.PLASTIC_TABLE_KEY, [
        {
            "name": "PL-LOW",
            "description": "Lower action",
            "mx_ed_knm": 20.0,
        },
        {
            "name": "PL-HIGH",
            "description": "Higher action",
            "mx_ed_knm": 80.0,
        },
    ])
    _calculate(at)
    assert not at.exception

    summary = next(
        frame.value for frame in at.dataframe if "Governing" in frame.value.columns
    )
    bending = summary.loc[summary["Check"] == "Plastic bending"]
    assert bending["Action set"].tolist() == ["PL-LOW", "PL-HIGH"]
    assert bending.loc[bending["Governing"] == "Yes", "Action set"].tolist() == [
        "PL-HIGH"
    ]

    _select_view(at, "Plastic Results")
    picker = at.selectbox(key="_plastic_result_case_index")
    assert picker.options == ["PL-LOW - Lower action", "PL-HIGH - Higher action"]
    picker.set_value(1).run()
    actions = next(
        frame.value for frame in at.dataframe
        if list(frame.value.columns) == [
            "N_Ed [kN]", "Mx_Ed [kNm]", "My_Ed [kNm]",
            "V_Ed [kN]", "T_Ed [kNm]",
        ]
    )
    assert actions.iloc[0]["Mx_Ed [kNm]"] == pytest.approx(80.0)
    assert not at.exception


def test_elastic_case_picker_shows_action_parts_and_acceptance_flags():
    import load_cases

    at = _fresh()
    at.run()
    _set(at, ("radio", "mode", "Elastic"))
    _replace_case_table(at, load_cases.ELASTIC_TABLE_KEY, [
        {
            "name": "EL-STRESS",
            "description": "Characteristic",
            "mx_long_ed_knm": 40.0,
            "check_stress": True,
        },
        {
            "name": "EL-CRACK",
            "description": "Frequent",
            "mx_long_ed_knm": 120.0,
            "mx_short_ed_knm": 30.0,
            "check_crack_width": True,
        },
    ])
    _select_view(at, "Elastic Results")
    picker = at.selectbox(key="_elastic_result_case_index")
    assert picker.options == [
        "EL-STRESS - Characteristic", "EL-CRACK - Frequent"
    ]
    picker.set_value(1).run()
    actions = next(
        frame.value for frame in at.dataframe
        if "Action part" in frame.value.columns
    )
    assert actions["Action part"].tolist() == ["Long-term", "Short-term"]
    assert actions["Mx_Ed [kNm]"].tolist() == pytest.approx([120.0, 30.0])
    assert any("Acceptance: crack width" in caption.value for caption in at.caption)
    assert not at.exception


def test_results_overview_shows_action_provenance_and_explicit_states():
    at = _fresh()
    at.run()
    _select_view(at, "Results Overview")
    status = next(
        frame.value for frame in at.dataframe if "Status" in frame.value.columns
    )
    assert set(status["Status"]) == {"NOT RUN"}
    assert set(status["Action set"]) == {"PL-01"}

    _set_and_click(
        at,
        "calculate",
        ("text_input", "pl_case_id", "PL-GOV-04"),
        ("text_input", "pl_case_source", "Combination register C1"),
    )
    register = next(
        frame.value for frame in at.dataframe
        if "Result state" in frame.value.columns
    )
    status = next(
        frame.value for frame in at.dataframe if "Status" in frame.value.columns
    )
    assert register.iloc[0]["Case"] == "PL-GOV-04"
    assert register.iloc[0]["Description"] == "Source: Combination register C1"
    assert register.iloc[0]["Result state"] == "Calculated"
    assert set(status["Status"]) == {"PASS"}

    _set(at, ("text_input", "pl_case_id", "PL-GOV-05"))
    _select_view(at, "Results Overview")
    stale = next(
        frame.value for frame in at.dataframe if "Status" in frame.value.columns
    )
    assert set(stale["Status"]) == {"STALE"}
    assert any("inputs changed" in warning.value.lower() for warning in at.warning)


def test_case_descriptions_accept_user_defined_limit_state_text():
    at = _fresh()
    at.run()
    _set(
        at,
        ("text_input", "pl_case_type", "ALS"),
        ("text_input", "el_case_type", "FLS"),
    )
    assert at.session_state["plastic_cases_base"].loc[0, "description"] == "ALS"
    assert at.session_state["elastic_cases_base"].loc[0, "description"] == "FLS"


def test_calculate_requires_active_action_set_identifiers():
    at = _fresh()
    at.run()
    _set_and_click(at, "calculate", ("text_input", "pl_case_id", ""))
    assert "results" not in at.session_state
    assert any(
        "At least one Plastic case is required" in error.value
        for error in at.error
    )


def test_applied_moments_default_to_zero():
    # v0.55: no fabricated sample load -- a fresh session starts with zero applied
    # moments (plastic + long-term elastic), so the first Calculate does not report
    # a made-up utilisation.
    at = _fresh()
    at.run()
    assert first_case_value(at, "pl_Mx") == 0.0
    assert first_case_value(at, "el_long_Mx") == 0.0


def test_page_navigation_and_input_tabs_follow_the_workflow_order():
    # Only the selected top-level page renders. The Inputs page stages the four
    # engineering steps plus project/report without tying either solver to a limit
    # state.
    at = _fresh()
    at.run()
    d = chr(0x00B7)   # the step-number middle dot (v0.63)
    nav = at.segmented_control(key="_main_page")
    assert nav.options == ["Inputs", "Analysis"] and nav.value == "Inputs"
    expected_outer = [
        f"1 {d} Analysis settings",
        f"2 {d} Section",
        f"3 {d} Material parameters",
        f"4 {d} Loads",
        "Project & report",
    ]
    labels = [tab.label for tab in at.tabs]
    assert labels == [
        *expected_outer[:3],
        "Concrete", "Mild steel", "Prestressing steel",
        *expected_outer[3:],
    ]
    assert at.session_state["_input_tab"] == expected_outer[0]
    labels = [ex.label for ex in at.expander]
    assert labels == [
        "Stress and crack-width criteria (Elastic)",
        "Shear, torsion & combined (Plastic)",
        "About",
        "Report",
        "Save / Load",
    ]


def test_tracked_input_tabs_survive_page_and_auxiliary_view_lifecycle():
    # Both tracked selections are session preferences, not project inputs. Keep
    # them through runs where the tab widgets are absent and Streamlit cleans up
    # widget-owned state.
    at = _fresh()
    at.run()
    _goto_material_tab(at, "Prestressing steel")
    outer = f"3 {chr(0x00B7)} Material parameters"
    assert at.session_state["_input_tab"] == outer
    assert at.session_state["_material_tab"] == "Prestressing steel"

    _goto_page(at, "Analysis")
    _goto_page(at, "Inputs")
    assert at.session_state["_input_tab"] == outer
    assert at.session_state["_material_tab"] == "Prestressing steel"

    _open_qs(at)
    at.button(key="qs_back").click().run()
    assert at.session_state["_main_page"] == "Inputs"
    assert at.session_state["_input_tab"] == outer
    assert at.session_state["_material_tab"] == "Prestressing steel"
    assert not at.exception


def test_analysis_defaults_to_results_overview_and_excludes_input_previews():
    at = _fresh()
    at.run()
    _goto_page(at, "Analysis")
    assert at.session_state["view"] == "Results Overview"
    assert "Section" not in at.selectbox(key="view").options
    assert "Material laws" not in at.selectbox(key="view").options
    _calculate(at)
    assert at.session_state["view"] == "Results Overview"


def test_calculate_from_a_result_view_stays_put():
    at = _fresh()
    at.run()
    _select_view(at, "Plastic Results")
    _calculate(at)
    assert at.session_state["view"] == "Plastic Results"


def test_staleness_badge_reflects_result_state():
    # v0.60: a freshness badge under Calculate is shown on every view.
    at = _fresh()
    at.run()
    caps = lambda: [c.value for c in at.caption]
    _goto_page(at, "Analysis")
    assert any("Not calculated yet" in c for c in caps())
    _calculate(at)
    assert any("Results up to date" in c for c in caps())
    _set(at, ("number_input", "pl_Mx", 55.0))
    _goto_page(at, "Analysis")
    assert any("recalculate" in c for c in caps())


def test_combined_preflight_warns_when_prerequisites_missing():
    # v0.59: enabling the combined check while its prerequisites are off warns inline
    # (under its toggle) instead of only after Calculate.
    at = _fresh()
    at.run()
    at.checkbox(key="combined_on").set_value(True).run()      # shear+torsion still off
    warns = [w.value for w in at.warning]
    cross = chr(0x2717)
    # v0.63: a requirements checklist -- the missing shear/torsion checks are crossed.
    assert any("Combined M-V-T needs all of these" in w for w in warns)
    assert any(f"{cross} Shear check" in w and f"{cross} Torsion check" in w
               for w in warns)
    # enabling both clears the warning (now a success checklist instead)
    at.checkbox(key="shear_on").set_value(True).run()
    at.checkbox(key="torsion_on").set_value(True).run()
    assert not any("needs all of these" in w.value for w in at.warning)
    assert any("requirements met" in s.value for s in at.success)


def test_combined_view_renamed_to_m_v_t_combined():
    # v0.55: the combined view was renamed "M-V-T Interaction" -> "M-V-T Combined".
    import sector_app
    assert "M-V-T Combined" in sector_app.VIEWS
    assert "M-V-T Interaction" not in sector_app.VIEWS
    at = _fresh()
    at.run()
    _select_view(at, "M-V-T Combined")
    assert not at.exception


def test_section_input_preview_is_geometry_only():
    # The Section-tab preview shows input geometry only; result annotations remain
    # on the Analysis page after a calculation and subsequent input change.
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    _calculate(at)
    _goto_input_tab(at, "Section")
    _set(at, ("number_input", "conc_fck", 40.0))  # change an input after calc
    _goto_input_tab(at, "Section")
    assert not at.exception
    assert not any("neutral axis" in w.value for w in at.warning)


def test_plastic_results_table_and_state_selector():
    # The plastic view exposes the per-angle table data and a state selector.
    at = _fresh()
    at.run()
    _calculate(at)
    _select_view(at, "Plastic Results")
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
    _set(
        at,
        ("number_input", "el_long_P", 5000.0),  # large tension (+ = tension)
        ("number_input", "el_long_Mx", 0.0),
    )
    _calculate(at)
    _select_view(at, "Elastic Results")
    assert not at.exception
    assert at.session_state["results"]["elastic"]["max_conc"] == pytest.approx(0.0)
    assert any("no compression" in c.value for c in at.caption)


def test_elastic_results_show_neutral_axis_and_max_steel():
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    _calculate(at)
    _select_view(at, "Elastic Results")
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    assert "max_steel" in e and "max_conc_xy" in e and "na_x" in e


def test_prestress_plastic_increases_capacity():
    # Enabling tendons in the tension zone must raise the plastic +Mx capacity.
    base = _fresh()
    base.run()
    _calculate(base)
    assert not base.exception
    mx0 = base.session_state["results"]["plastic"]["max_mx"]

    at = _fresh_qs()
    _set_and_click(
        at, "qs_apply", ("number_input", "tnd_n", 4)
    )  # put the tendons in the section
    _calculate(at)
    assert not at.exception
    res = at.session_state["results"]
    assert "plastic" in res
    assert res["plastic"]["max_mx"] > mx0


def test_prestress_both_modes_run_with_tendons():
    at = _fresh_qs()
    _set_and_click(
        at, "qs_apply", ("number_input", "tnd_n", 4)
    )  # load the tendons into the points
    _set_and_click(at, "calculate", ("radio", "mode", "Both"))
    assert not at.exception
    res = at.session_state["results"]
    # Elastic models each tendon as an extra bar, so its stress list grows.
    assert "plastic" in res and "elastic" in res
    assert len(res["elastic"]["total"]) > 0


def test_prestress_preset_curve6_calculates():
    at = _fresh_qs()
    _set_and_click(
        at, "qs_apply", ("number_input", "tnd_n", 4)
    )  # load the tendons into the points
    _set_and_click(
        at, "calculate", ("selectbox", "pre_preset", "Curve 6 (bilinear)")
    )
    assert not at.exception
    assert "plastic" in at.session_state["results"]


def test_material_manual_override_calculates():
    at = _fresh()
    at.run()
    # A picked preset must remain editable.
    at.number_input(key="conc_fck").set_value(45.0).run()
    at.number_input(key="mild_gamma_y").set_value(1.3).run()
    assert not at.exception
    _calculate(at)
    assert not at.exception
    assert "plastic" in at.session_state["results"]


def test_elastic_reports_cracking_and_section_properties():
    # The elastic analysis always reports the cracking threshold and the
    # transformed section properties (cracked + uncracked when cracked).
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    _set(at, ("number_input", "el_long_Mx", 400.0))  # force cracking
    _calculate(at)
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    assert e["cracked"] is True
    assert 0.0 < e["lambda_cr"] < 1.0
    assert e["show_cw"] is False           # crack width off by default
    assert e["crack"] is None              # crack width is its own opt-in
    assert e["props_un"]["area"] > 0.0 and e["props_un"]["Ix"] > 0.0
    assert e["props_cr"] is not None       # cracked -> cracked properties present
    assert e["props_cr"]["area"] < e["props_un"]["area"]   # cracked section is smaller


def test_elastic_reports_explicit_limits_and_complete_evidence():
    at = _fresh()
    at.run()
    _set_and_click(
        at, "calculate",
        ("radio", "mode", "Elastic"),
        ("number_input", "el_long_Mx", 400.0),
        ("number_input", "sls_conc_limit_pct", 10.0),
        ("number_input", "sls_steel_limit_pct", 10.0),
        ("text_input", "sls_limit_source", "DB-SLS-01 section 4"),
    )
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    assert e["converged"] is True
    assert e["stress_assessments"]["concrete"]["status"] == "EXCEEDED"
    assert e["stress_assessments"]["reinforcement"]["status"] == "EXCEEDED"
    assert e["sls_limit_source"] == "DB-SLS-01 section 4"
    assert e["max_conc_point"] >= 1                 # public IDs are one-based
    assert e["elements"][0]["element_type"] == "Bar"
    assert {"x_mm", "y_mm", "area_mm2", "strain_permille", "total_mpa"} <= \
        e["elements"][0].keys()
    assert e["concrete_corners"][0]["point_no"] == 1
    assert {"strain_permille", "stress_mpa"} <= e["concrete_corners"][0].keys()


def test_crack_width_off_by_default():
    # Crack width is an opt-in: a cracked section reports the threshold and
    # properties but no crack width until the toggle is on.
    at = _fresh()
    at.run()
    _set_and_click(
        at,
        "calculate",
        ("radio", "mode", "Elastic"),
        ("number_input", "el_long_Mx", 400.0),
    )
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    assert e["show_cw"] is False
    assert e["crack"] is None              # crack width toggle off


def test_crack_width_reports_both_load_cases():
    # The crack-width toggle reports wk for both the long-term and the short-term
    # load, with no cover input (cover is taken from the geometry per bar).
    at = _fresh()
    at.run()
    _set_and_click(
        at,
        "calculate",
        ("radio", "mode", "Elastic"),
        ("number_input", "el_long_Mx", 400.0),
        ("number_input", "el_short_Mx", 150.0),
        ("checkbox", "sls_cw", True),
    )
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    assert e["show_cw"] is True
    assert e["crack"] is not None and e["crack"]["wk"] > 0.0
    assert e["crack_short"] is not None and e["crack_short"]["wk"] > 0.0
    # The short-term state carries the extra variable load, so its crack is wider.
    assert e["crack_short"]["wk"] > e["crack"]["wk"]
    assert e["crack"]["cover"] > 0.0       # auto cover from the geometry


def test_crack_limit_verdict_and_candidate_table_are_retained():
    at = _fresh()
    at.run()
    _set_and_click(
        at, "calculate",
        ("radio", "mode", "Elastic"),
        ("number_input", "el_long_Mx", 400.0),
        ("checkbox", "sls_cw", True),
        ("number_input", "sls_wk_limit", 0.01),
        ("text_input", "sls_limit_source", "Project crack criterion"),
    )
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    assert e["crack_assessment"]["status"] == "EXCEEDED"
    assert e["crack_assessment"]["limit"] == pytest.approx(0.01)
    assert e["crack_assessment"]["case"] in {"Long-term", "Short-term"}
    assert e["crack_assessment"]["governing"].startswith(("bar ", "tendon "))
    assert e["crack"]["candidates"]
    assert e["crack"]["candidates"][0]["wk"] == pytest.approx(e["crack"]["wk"])
    assert {"element_id", "x_mm", "y_mm", "area_mm2", "cover",
            "sigma_s", "ac_eff", "esm_ecm", "sr_max", "wk"} <= \
        e["crack"]["candidates"][0].keys()
    _select_view(at, "Elastic Results")
    assert any(
        "FAIL - Crack width" in item.value
        and "governing" in item.value
        and "case" in item.value
        and "element" in item.value
        for item in at.error
    )


def test_crack_limit_and_source_are_retained_when_no_width_is_calculated():
    at = _fresh()
    at.run()
    _set_and_click(
        at, "calculate",
        ("radio", "mode", "Elastic"),
        ("number_input", "el_long_Mx", 0.0),
        ("number_input", "el_short_Mx", 0.0),
        ("checkbox", "sls_cw", True),
        ("number_input", "sls_wk_limit", 0.25),
        ("text_input", "sls_limit_source", "Project no-crack criterion"),
    )
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    assert e["crack"] is None and e["crack_short"] is None
    assert e["crack_assessment"]["status"] == "NOT APPLICABLE"
    assert e["crack_assessment"]["limit"] == pytest.approx(0.25)
    assert e["sls_limit_source"] == "Project no-crack criterion"
    _select_view(at, "Elastic Results")
    assert any("No crack width:" in item.value for item in at.info)
    assert any(
        "Project no-crack criterion" in item.value for item in at.caption
    )


def test_dk_na_reports_fine_and_coarse_for_both_load_cases():
    # The single DK NA option reports four crack widths: the fine and the coarse
    # crack system, each for the long-term and the short-term load. The coarse
    # system (centroid-matched effective area + wk/2) is smaller than the fine one.
    at = _fresh()
    at.run()
    _set_and_click(
        at,
        "calculate",
        ("radio", "mode", "Elastic"),
        ("number_input", "el_long_Mx", 400.0),
        ("number_input", "el_short_Mx", 150.0),
        ("checkbox", "sls_cw", True),
        ("selectbox", "sls_code", "DS/EN 1992-1-1 + DK NA"),
    )
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
    _set_and_click(
        at,
        "calculate",
        ("radio", "mode", "Elastic"),
        ("number_input", "el_long_Mx", 400.0),
        ("checkbox", "sls_cw", True),
        ("selectbox", "sls_code", "EN 1992-1-1:2005"),
    )
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    assert e["crack"] is not None
    assert e.get("crack_coarse") is None and e.get("crack_short_coarse") is None


def test_ec2_2023_crack_edition_calculates():
    # Selecting EN 1992-1-1:2023 uses the refined model (9.2.3) and reports its wk.
    at = _fresh()
    at.run()
    _set_and_click(
        at,
        "calculate",
        ("radio", "mode", "Elastic"),
        ("number_input", "el_long_Mx", 400.0),
        ("checkbox", "sls_cw", True),
        ("selectbox", "sls_code", "EN 1992-1-1:2023"),
    )
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
    _set_and_click(
        at,
        "calculate",
        ("radio", "mode", "Elastic"),
        ("number_input", "el_long_Mx", 300.0),
        ("number_input", "el_short_Mx", 150.0),
        ("number_input", "el_phi", 2.0),
        ("checkbox", "sls_cw", True),
    )  # creep: n_l = (1+phi)*n_s != n_s
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
    _set_and_click(
        at,
        "calculate",
        ("radio", "mode", "Elastic"),
        ("number_input", "el_long_Mx", 400.0),
        ("checkbox", "sls_cw", True),
    )
    wk_ribbed = at.session_state["results"]["elastic"]["crack"]["wk"]
    _set_and_click(
        at,
        "calculate",
        ("selectbox", "sls_bond", "Plain round (k1 = 1.6)"),
    )
    assert not at.exception
    wk_plain = at.session_state["results"]["elastic"]["crack"]["wk"]
    assert wk_plain > wk_ribbed


def test_crack_width_with_tendons_runs():
    # With prestressing tendons present, the per-bar k1 (tendons fixed at 1.6,
    # folded after the bars) must line up with the section, so the crack-width
    # path runs without a length mismatch.
    at = _fresh_qs(mode="Elastic")
    _set_and_click(at, "qs_apply", ("number_input", "tnd_n", 4))
    _set_and_click(
        at,
        "calculate",
        ("number_input", "el_long_Mx", 400.0),
        ("checkbox", "sls_cw", True),
    )
    assert not at.exception


def test_dk_na_crack_edition_narrows_wk():
    # Selecting the DK NA crack-width code applies the cover-dependent k3
    # (3.4*(25/c)^(2/3)); for the default cover > 25 mm this narrows wk vs base.
    at = _fresh()
    at.run()
    _set_and_click(
        at,
        "calculate",
        ("radio", "mode", "Elastic"),
        ("number_input", "el_long_Mx", 400.0),
        ("checkbox", "sls_cw", True),
    )
    wk_base = at.session_state["results"]["elastic"]["crack"]["wk"]
    _set_and_click(
        at,
        "calculate",
        ("selectbox", "sls_code", "DS/EN 1992-1-1 + DK NA"),
        ("selectbox", "sls_member", "Slab"),
    )
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    assert "DK NA" in e["crack_code"]
    assert e["crack"]["wk"] < wk_base


def test_elastic_uncracked_below_threshold():
    # A small long-term moment leaves the section uncracked: no crack width and
    # no cracked-section properties.
    at = _fresh()
    at.run()
    _set_and_click(
        at,
        "calculate",
        ("radio", "mode", "Elastic"),
        ("number_input", "el_long_Mx", 5.0),
    )
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    assert e["cracked"] is False
    assert e["crack"] is None
    assert e["props_cr"] is None


def test_elastic_view_renders_with_sls_subsection():
    at = _fresh()
    at.run()
    _set_and_click(
        at,
        "calculate",
        ("radio", "mode", "Elastic"),
        ("number_input", "el_long_Mx", 400.0),
        ("checkbox", "sls_cw", True),
    )
    _select_view(at, "Elastic Results")
    assert not at.exception


def test_cracking_follows_the_total_load():
    # The cracking decision is on the total load. With no short-term load the total
    # equals the long-term load, so raising the long-term moment crosses from
    # uncracked to cracked.
    at = _fresh()
    at.run()
    _set_and_click(
        at,
        "calculate",
        ("radio", "mode", "Elastic"),
        ("number_input", "el_long_Mx", 5.0),
    )
    assert at.session_state["results"]["elastic"]["cracked"] is False
    _set_and_click(
        at, "calculate", ("number_input", "el_long_Mx", 400.0)
    )
    assert at.session_state["results"]["elastic"]["cracked"] is True


def test_short_term_load_triggers_cracking():
    # A section uncracked under the long-term load alone but cracked under the total
    # (long + short) load must be reported as cracked, with a crack width computed --
    # cracking is triggered by the peak load and is irreversible.
    at = _fresh()
    at.run()
    _set_and_click(
        at,
        "calculate",
        ("radio", "mode", "Elastic"),
        ("number_input", "el_long_Mx", 5.0),
        ("number_input", "el_short_Mx", 400.0),
        ("checkbox", "sls_cw", True),
    )  # long-term alone is uncracked; the total cracks
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
    _set_and_click(
        at,
        "calculate",
        ("radio", "mode", "Elastic"),
        ("number_input", "el_long_Mx", 0.0),
        ("number_input", "el_short_Mx", 400.0),
    )
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
    _set_and_click(
        at,
        "calculate",
        ("radio", "mode", "Elastic"),
        ("number_input", "el_long_Mx", 400.0),
        ("number_input", "el_short_Mx", -380.0),
        ("checkbox", "sls_cw", True),
    )  # long-term cracks; total is about 20 kNm
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    assert e["cracked"] is True                    # cracked by the long-term action
    assert e["crack"] is not None and e["crack"]["wk"] > 0.0


def test_plain_elastic_unchanged_by_sls_toggle():
    # The regular cracked-section stresses (zero concrete tension) do not change
    # when the crack-width check is toggled on.
    at = _fresh()
    at.run()
    _set_and_click(
        at,
        "calculate",
        ("radio", "mode", "Elastic"),
        ("number_input", "el_long_Mx", 400.0),
    )
    base = list(at.session_state["results"]["elastic"]["total"])
    _set_and_click(at, "calculate", ("checkbox", "sls_cw", True))
    assert not at.exception
    assert list(at.session_state["results"]["elastic"]["total"]) == base


def test_fctm_auto_button_tracks_grade():
    # The Auto button recomputes fctm from the current concrete grade (EC2
    # Table 3.1): C50 -> 0.30*50^(2/3) ~ 4.07 MPa.
    at = _fresh()
    at.run()
    _set_and_click(
        at,
        "sls_fctm_auto",
        ("radio", "mode", "Elastic"),
        ("number_input", "conc_fck", 50.0),
    )
    assert not at.exception
    assert at.number_input(key="sls_fctm").value == pytest.approx(4.07, abs=0.05)


def test_modular_ratios_are_derived_from_moduli():
    # n_l/n_s are no longer entered: the number inputs and Auto buttons are gone. The
    # loads panel reports the derived ratios instead -- n_s = Es/Ec and, with creep,
    # n_l = (1+phi)*n_s. Es and Ec are entered in GPa; here Es/Ec = 200/40 = 5.0 and
    # n_l = (1+2)*5 = 15.0.
    at = _fresh()
    at.run()
    keys = {w.key for w in at.number_input} | {b.key for b in at.button}
    assert "nl" not in keys and "ns" not in keys              # inputs removed
    assert "nl_auto" not in keys and "ns_auto" not in keys    # Auto buttons removed
    _set(
        at,
        ("radio", "mode", "Both"),
        ("number_input", "mild_Es", 200.0),
        ("number_input", "conc_Ec", 40.0),
        ("number_input", "el_phi", 2.0),
    )
    md = "\n".join(m.value for m in at.markdown)
    assert "Modular ratios" in md
    assert "| Mild (Es/Ec) | 5.000 | 15.000 |" in md


def test_prestress_gets_its_own_derived_modular_ratio():
    # Prestress and mild steel have independent ratios because Es != Ep. With a
    # tendon in the section the loads panel adds a prestress row n = Ep/Ec alongside
    # the mild row; Ep and Ec are in GPa: Ep = 195, Ec = 39 -> Ep/Ec = 5.0, and
    # phi = 0 -> n_l = n_s.
    at = _fresh_qs(mode="Both")
    _set_and_click(
        at, "qs_apply", ("number_input", "tnd_n", 3)
    )  # add tendons
    _set(
        at,
        ("number_input", "pre_Es", 195.0),
        ("number_input", "conc_Ec", 39.0),
        ("number_input", "el_phi", 0.0),
    )
    md = "\n".join(m.value for m in at.markdown)
    assert "| Prestress (Ep/Ec) | 5.000 | 5.000 |" in md


def test_tendon_stress_limit_uses_fpk_not_proof_stress():
    # The prestress material distinguishes fp0.1k (fytk) from fpk (futk).
    # The user-facing tendon stress criterion is explicitly a percentage of fpk.
    at = _fresh_qs(mode="Elastic")
    _set_and_click(at, "qs_apply", ("number_input", "tnd_n", 3))
    _calculate(at)
    check = at.session_state["results"]["elastic"]["stress_assessments"]["prestress"]
    assert check["limit"] == pytest.approx(0.75 * 1860.0)
    assert check["criterion"] == "75% fpk"


def test_transformed_area_uses_the_tendon_modular_ratio():
    # The reported transformed section properties must weight tendons at Ep/Es
    # (n_mult), like the elastic and cracking solves -- so changing Ep moves the
    # reported transformed area. Without n_mult the tendons would take the mild
    # ratio and Ep would have no effect on the properties.
    at = _fresh_qs(mode="Elastic")
    _set_and_click(
        at, "qs_apply", ("number_input", "tnd_n", 3)
    )  # add tendons

    def _area(pre_es):
        _set_and_click(
            at, "calculate", ("number_input", "pre_Es", pre_es)
        )
        return at.session_state["results"]["elastic"]["props_un"]["area"]

    a_soft, a_stiff = _area(160.0), _area(200.0)        # Ep in GPa
    assert a_stiff != pytest.approx(a_soft, rel=1e-6)   # Ep changes the transformed area
    assert a_stiff > a_soft                              # stiffer tendons -> larger area


def test_editing_ec_or_creep_marks_elastic_results_stale():
    # n_l/n_s are derived from Ec and creep, so editing either after Calculate must
    # mark the elastic results stale (the ratios enter the signature via their inputs).
    at = _fresh()
    at.run()
    _set_and_click(
        at,
        "calculate",
        ("radio", "mode", "Elastic"),
    )
    _select_view(at, "Elastic Results")
    assert not any("press Calculate" in w.value for w in at.warning)   # fresh, not stale
    _set(at, ("number_input", "conc_Ec", 20.0))                       # changes n_s and n_l
    _select_view(at, "Elastic Results")
    assert any("press Calculate" in w.value for w in at.warning)      # now stale
    _calculate(at)
    _set(at, ("number_input", "el_phi", 1.0))                        # changes n_l (creep)
    _select_view(at, "Elastic Results")
    assert any("press Calculate" in w.value for w in at.warning)


def test_crack_width_auto_cover_circular_section():
    # No cover input: the crack width takes each bar's clear cover from the
    # geometry. A 100 mm ring cover (to centres) on a circular section gives a
    # clear cover near 100 - phi/2 mm, comfortably above 70 mm.
    at = _fresh_qs(mode="Elastic")
    at.selectbox(key="shape").set_value("Circular").run()
    _set_and_click(
        at, "qs_apply", ("number_input", "ring_c_mm", 100.0)
    )  # apply the ring to the points
    _set_and_click(
        at,
        "calculate",
        ("number_input", "el_long_Mx", 400.0),
        ("checkbox", "sls_cw", True),
    )  # force cracking
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    if e["crack"] is not None:
        assert e["crack"]["cover"] > 70.0
