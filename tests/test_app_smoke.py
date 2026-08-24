"""Headless smoke tests for the Streamlit app via Streamlit's AppTest.

These run the app script in-process (no browser), exercise the Calculate flow
for each analysis mode, and assert it produces results without error.
"""

from __future__ import annotations

import dataclasses
import copy
import json
import math
import pathlib
import re
import sys
import time

import pytest

from streamlit.testing.v1 import AppTest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))   # so `import sector_app` / `project_io` works standalone

APP = str(ROOT / "app" / "sector_app.py")

_SLS_BASE = "ec2_1_1_first_gen_base"
_SLS_DK = "ec2_1_1_first_gen_dk_na_2024"
_SLS_2023 = "ec2_1_1_2023_published"

from app_case_inputs import (
    apply_case_changes,
    discard_retired_qs_fragment,
    first_case_value,
)

_MATH_SPAN_RE = re.compile(r"\${1,2}.*?\${1,2}", flags=re.DOTALL)
_LEAKED_MATH_RE = re.compile(
    r"\\[A-Za-z]+|\b(?:sqrt|Cfrac|Big|sincos)\b"
)


def _fresh():
    return AppTest.from_file(APP, default_timeout=90)


def _assert_math_text_is_renderable(value):
    """Guard text surfaces without rejecting valid KaTeX inside ``$...$``."""
    if not isinstance(value, str) or not value:
        return
    assert value.count("$") % 2 == 0, value
    for expression in _MATH_SPAN_RE.findall(value):
        assert r"\Cfrac" not in expression
        assert not re.search(r"\\(?:quad|qquad)[A-Za-z]", expression)
    plain_text = _MATH_SPAN_RE.sub("", value)
    assert not _LEAKED_MATH_RE.search(plain_text), value


def test_crack_result_adapter_preserves_textbook_operands_without_recalculation():
    import sector_app
    from sector.serviceability import (
        CrackEffectiveArea2005Fine,
        CrackMeanStrainOperands,
        CrackSpacing2005Operands,
        CrackWidthCandidate,
        CrackWidthResult,
    )

    mean = CrackMeanStrainOperands(
        sigma_s=200.0, kt=0.4, fctm=2.9, rho_p_eff=0.02,
        alpha_e=6.0, es=200_000.0, concrete_tension_reduction=65.0,
        formula_candidate=0.000675, lower_bound_factor=0.6,
        lower_bound_candidate=0.0006, selected_candidate="formula-7.9",
        selected_esm_ecm=0.000675,
    )
    spacing = CrackSpacing2005Operands(
        cover=35.0, diameter=16.0, rho_p_eff=0.02,
        k1=0.8, k2=0.5, k3_base=3.4, k3_used=3.4, k4=0.425,
        nearest_neighbour_spacing=120.0, close_spacing_limit=215.0,
        tension_zone_depth=0.2, formula_7_11=255.0,
        geometric_7_14=260.0, selected_candidate="formula-7.11",
        selected_spacing=255.0,
    )
    candidate = CrackWidthCandidate(
        bar_index=0, x=0.0, y=-0.12, area=500.0,
        wk=0.172125, sr_max=255.0, esm_ecm=0.000675,
        sigma_s=200.0, rho_p_eff=0.02, ac_eff=0.025,
        hc_ef=0.125, phi=16.0, cover=35.0,
        as_eff=0.0005, mean_strain_operands=mean,
        spacing_operands=spacing,
    )
    area = CrackEffectiveArea2005Fine(
        section_depth=0.3, effective_depth=0.25,
        tension_zone_depth=0.4, h_minus_d=0.05,
        candidate_2_5_h_minus_d=0.125,
        candidate_h_minus_x_over_3=0.13333333333333333,
        candidate_h_over_2=0.15, selected_candidate="2.5(h-d)",
        selected_hc_eff=0.125, band_limit=-0.025, ac_eff=0.025,
    )
    result = CrackWidthResult(
        wk=candidate.wk, sr_max=candidate.sr_max,
        esm_ecm=candidate.esm_ecm, sigma_s=candidate.sigma_s,
        rho_p_eff=candidate.rho_p_eff, ac_eff=candidate.ac_eff,
        hc_ef=candidate.hc_ef, phi=candidate.phi, cover=candidate.cover,
        gov_bar=0, candidates=(candidate,), effective_area_operands=area,
    )

    payload = sector_app._crack_dict(result, ["R1"], [])
    assert payload["element_id"] == "R1"
    assert payload["governing_candidate"]["mean_strain_operands"] == {
        **dataclasses.asdict(mean),
        "record_kind": "CrackMeanStrainOperands",
    }
    assert payload["governing_candidate"]["spacing_operands"] == {
        **dataclasses.asdict(spacing),
        "record_kind": "CrackSpacing2005Operands",
    }
    assert payload["effective_area_operands"] == {
        **dataclasses.asdict(area),
        "record_kind": "CrackEffectiveArea2005Fine",
    }


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
    """Select one tracked outer input stage by its short engineering name."""
    _goto_page(at, "Inputs")
    d = chr(0x00B7)
    labels = {
        "Analysis settings": f"1 {d} Analysis settings",
        "Section": f"2 {d} Section",
        "Material parameters": f"3 {d} Material parameters",
        "Loads": f"4 {d} Loads",
        "Project": "Project",
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
    """Open Material parameters and select one material family."""
    _goto_input_tab(at, "Material parameters")
    try:
        current = at.session_state["_material_tab"]
    except KeyError:
        current = None
    if current != name:
        at.session_state["_material_tab"] = name
        at.session_state["_material_tab_preference"] = name
        at.run()
    return at


def _goto_widget_owner(at, key):
    """Mount the outer stage that owns a requested test widget."""
    if key.startswith("conc_") or key == "sls_fctm":
        return _goto_material_tab(at, "Concrete")
    if key.startswith(("mild_", "mildcat_")):
        return _goto_material_tab(at, "Mild steel")
    if key.startswith(("pre_", "precat_")):
        return _goto_material_tab(at, "Prestressing steel")
    if key.startswith("fatiguecat_"):
        return _goto_material_tab(at, "Fatigue details")
    if key == "el_phi":
        return _goto_input_tab(at, "Loads")
    if key.startswith("rep_"):
        return _goto_page(at, "Report")
    if key.startswith(("autosave_", "project_")):
        return _goto_input_tab(at, "Project")
    if key.startswith(("section_", "label_")):
        return _goto_input_tab(at, "Section")
    return _goto_input_tab(at, "Analysis settings")


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


def _section_outline_from_result_view(at):
    """Return the plotted section outline from a Plastic/Elastic result view."""

    for chart in at.get("plotly_chart"):
        spec = json.loads(chart.proto.spec)
        x_title = (
            spec.get("layout", {})
            .get("xaxis", {})
            .get("title", {})
            .get("text")
        )
        data = spec.get("data", [])
        if (
            x_title == "x (mm)"
            and data
            and data[0].get("fill") == "toself"
        ):
            return data[0]["x"], data[0]["y"]
    raise AssertionError("No section-state Plotly figure was rendered")


def _section_hover_from_result_view(at):
    """Return all custom hover text from a Plastic/Elastic section result."""

    for chart in at.get("plotly_chart"):
        spec = json.loads(chart.proto.spec)
        x_title = (
            spec.get("layout", {})
            .get("xaxis", {})
            .get("title", {})
            .get("text")
        )
        data = spec.get("data", [])
        if (
            x_title == "x (mm)"
            and data
            and data[0].get("fill") == "toself"
        ):
            return [
                str(value)
                for trace in data
                for value in (trace.get("customdata") or [])
            ]
    raise AssertionError("No section-state Plotly figure was rendered")


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
    """Apply changes after mounting each widget's outer owner stage."""
    changes, case_changed = apply_case_changes(at, changes)
    if case_changed:
        _goto_page(at, "Inputs")
        if not changes:
            at.run()
    for widget_type, key, value in changes:
        try:
            widget = getattr(at, widget_type)(key=key)
        except KeyError:
            if key == "view":
                _goto_page(at, "Analysis")
            else:
                _goto_widget_owner(at, key)
            widget = getattr(at, widget_type)(key=key)
        widget.set_value(value).run()
    return at


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
    elif changes:
        _set(at, *changes)
        changes = ()
    for widget_type, key, value in changes:
        getattr(at, widget_type)(key=key).set_value(value)
    if button_key == "calculate":
        # Submit the edited input page first, then calculate from the independently
        # rendered Analysis page.
        _goto_page(at, "Analysis")
    at.button(key=button_key).click()
    at.run()
    if button_key in {"qs_apply", "qs_back"}:
        discard_retired_qs_fragment(at)
    return at


def _open_qs(at):
    """Open the full-width Quick Section builder so its widgets render."""
    at.session_state["_qs_open"] = True
    at.session_state["_main_page"] = "Analysis"
    at.run()
    return at


def _apply_qs(at):
    """Apply the builder to the point tables and return to the analysis layout."""
    at.button(key="qs_apply").click().run()
    discard_retired_qs_fragment(at)
    return at


def _clear_section(at):
    """Confirm the two-step section clear and return the rerun AppTest."""
    _goto_input_tab(at, "Section")
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
    # An invalid/empty section is blocked before solver entry. The freshness badge
    # must read "Not calculated yet", not green "Results up to date", and the
    # blocked attempt must not manufacture a result payload.
    at = _fresh()
    at.run()
    _clear_section(at)                           # empty the section -> no valid points
    _calculate(at)
    assert "results" not in at.session_state
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
        sector_app._input_workspace,
        sector_app._analysis_workspace,
        sector_app._quick_section_viewport,
        sector_app._report_workspace,
        sector_app._save_load_panel,
    ):
        assert hasattr(func, "__wrapped__"), func.__name__

    workspace = inspect.getsource(sector_app._analysis_workspace.__wrapped__)
    assert workspace.index('c_calc.button(') < workspace.index('c_view.selectbox(')
    assert "_switch_view" not in workspace
    report_source = inspect.getsource(sector_app._report_workspace.__wrapped__)
    assert "st.container(border=True)" in report_source
    assert "_generate_report(inp)" in report_source
    assert report_source.index("_restore_report_state") < report_source.index(
        "_normalise_report_profile_session_state()"
    ) < report_source.index("_seeded_segmented_control")
    save_source = inspect.getsource(sector_app._save_load_panel.__wrapped__)
    assert "st.expander(" in save_source
    assert "parent." not in save_source

    input_workspace = inspect.getsource(sector_app._input_workspace.__wrapped__)
    input_commit = inspect.getsource(sector_app._commit_input_fragment)
    quick_section_exit = inspect.getsource(sector_app._open_analysis_content)
    manual_exit = inspect.getsource(sector_app._open_manual_dialog)
    app_source = inspect.getsource(sector_app)
    assert "parallel=True" not in inspect.getsource(sector_app._input_workspace)
    assert input_workspace.index("_restore_input_state(replace=True)") < (
        input_workspace.index("st.session_state[_INPUT_BUILD_KEY] = True")
    )
    assert input_workspace.index("st.session_state[_INPUT_BUILD_KEY] = True") < (
        input_workspace.index("build_inputs(st)")
    )
    assert input_workspace.index("build_inputs(st)") < input_workspace.index(
        "_commit_input_fragment(inp)"
    )
    ordered_commit = (
        "_snapshot_input_state(inp)",
        "st.session_state.pop(_PENDING_INPUT_EVENTS_KEY, None)",
        'st.session_state[_INPUT_BUILD_KEY] = False',
        'st.session_state[_LAST_WORKSPACE_KEY] = "Inputs"',
        "_measured_autosave()",
    )
    assert [input_commit.index(token) for token in ordered_commit] == sorted(
        input_commit.index(token) for token in ordered_commit
    )
    assert 'st.session_state["_next_main_page"] = "Analysis"' in quick_section_exit
    assert 'st.rerun(scope="app")' in quick_section_exit
    assert 'st.rerun(scope="app")' in manual_exit
    assert "on_click=_open_analysis_content" not in app_source
    assert "on_click=_open_manual_dialog" not in app_source
    assert app_source.count(
        "st.session_state[_INPUT_BUILD_KEY] = False"
    ) == 1
    assert "and _has_uncommitted_inputs()" in inspect.getsource(
        sector_app._maybe_autosave
    )


def test_input_fragment_exit_callbacks_request_full_app_reruns(monkeypatch):
    import sector_app

    class FakeStreamlit:
        def __init__(self):
            self.session_state = {}
            self.rerun_scopes = []

        def rerun(self, *, scope):
            self.rerun_scopes.append(scope)

    fake_st = FakeStreamlit()
    snapshots = []
    monkeypatch.setattr(sector_app, "st", fake_st)
    monkeypatch.setattr(
        sector_app,
        "_snapshot_completed_input_state",
        lambda: snapshots.append("complete"),
    )

    sector_app._open_analysis_content("quick_section")
    assert fake_st.session_state["_qs_open"] is True
    assert fake_st.session_state["_next_main_page"] == "Analysis"
    assert "_main_page" not in fake_st.session_state

    sector_app._open_manual_dialog()
    assert fake_st.session_state["_manual_open"] is True
    assert snapshots == ["complete", "complete"]
    assert fake_st.rerun_scopes == ["app", "app"]


def test_interrupted_input_fragment_batches_latest_cross_pane_events():
    at = _fresh()
    at.run()
    d = chr(0x00B7)
    material_stage = f"3 {d} Material parameters"

    # Reproduce two genuine edits plus rapid outer/nested navigation arriving
    # before the preceding Inputs fragment reached its commit point.
    at.session_state["_inputs_build_in_progress"] = True
    at.session_state["_pending_input_events"] = {
        "conc_fck": 47.0,
        "v_inc": 30.0,
        "_input_tab": material_stage,
        "_material_tab": "Mild steel",
    }
    at.session_state["_input_tab"] = material_stage
    at.session_state["_material_tab"] = "Mild steel"
    at.session_state["_material_tab_preference"] = "Mild steel"
    at.run()

    assert not at.exception
    assert at.session_state["_inputs_build_in_progress"] is False
    assert "_pending_input_events" not in at.session_state
    assert at.session_state["_input_tab"] == material_stage
    assert at.session_state["_material_tab"] == "Mild steel"
    assert at.session_state["_durable_input_scalars"]["conc_fck"] == pytest.approx(
        47.0
    )
    assert at.session_state["_durable_input_scalars"]["v_inc"] == pytest.approx(
        30.0
    )
    latest = at.session_state["_latest_inputs"]
    assert latest["concrete"].fck == pytest.approx(47.0)
    assert latest["v_inc"] == pytest.approx(30.0)

    _calculate(at)
    snapshot = at.session_state["result_input_snapshot"]
    assert snapshot["concrete"].fck == pytest.approx(47.0)
    assert snapshot["v_inc"] == pytest.approx(30.0)


def test_input_fragment_commits_latest_value_before_due_autosave(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path))
    at = _fresh()
    at.run()
    _goto_material_tab(at, "Concrete")
    at.session_state["_autosave_t"] = 0.0
    at.number_input(key="conc_fck").set_value(43.0).run()

    assert not at.exception
    saved = tmp_path / "autosave.json"
    assert saved.exists()
    import project_io

    _, scalars = project_io.parse_project(saved.read_text(encoding="utf-8"))
    assert scalars["conc_fck"] == pytest.approx(43.0)
    assert at.session_state["_latest_inputs"]["concrete"].fck == pytest.approx(43.0)


def test_persisted_settings_use_the_seeded_number_helper():
    # These inputs are saved (SCALAR_KEYS), so loading a project writes their key
    # before the widget is created; passing value= too trips Streamlit's "default
    # value and Session State" warning. They must go through _seeded_number
    # (setdefault + no value=), so the bare `key="<name>"` form no longer appears.
    import inspect
    import sector_app
    src = inspect.getsource(sector_app)
    for helper in (
        "_seeded_number", "_seeded_checkbox", "_seeded_toggle",
        "_seeded_selectbox", "_seeded_text", "_seeded_text_area",
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
                "ring_d", "bot_d", "top_d",                     # QS diameter inputs
                "qs_cover_to_edge", "bot_off_d", "top_off_d",   # QS toggle + interleave
                "b_mm", "h_mm", "bf_mm", "hf_mm", "bw_mm", "hw_mm", "dia_mm",  # QS dims
                "trap_bottom_mm", "trap_top_mm", "trap_h_mm", "t_orientation",
                "l_b_mm", "l_h_mm", "l_web_mm", "l_flange_mm",
                "i_bf_mm", "i_tf_mm", "i_bw_mm", "i_hw_mm",
                "u_b_mm", "u_h_mm", "u_web_mm", "u_base_mm",
                "annulus_outer_mm", "annulus_inner_mm",
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


def test_expanded_quick_section_dimension_survives_a_project_restore():
    import project_io

    at = _fresh_qs()
    at.selectbox(key="shape").set_value("Annulus").run()
    _set_and_click(
        at, "qs_back", ("number_input", "annulus_outer_mm", 900.0)
    )
    text = project_io.dump_project(
        {
            key: at.session_state[key]
            for key in project_io.PROJECT_TABLE_KEYS
            if key in at.session_state
        },
        {
            key: at.session_state[key]
            for key in project_io.SCALAR_KEYS
            if key in at.session_state
        },
    )

    restored = _fresh()
    restored.session_state["_pending_project"] = text
    restored.session_state["_qs_open"] = True
    restored.run()

    assert not restored.exception
    assert restored.selectbox(key="shape").value == "Annulus"
    assert restored.number_input(key="annulus_outer_mm").value == pytest.approx(900.0)


def test_pre_expansion_project_load_clears_stale_expanded_quick_section_state():
    import project_io

    # This is a valid current-schema project in the form written before PR-13: its
    # T-section fields exist, but the expanded-shape fields and orientation do not.
    pre_expansion_project = project_io.dump_project(
        {},
        {
            "qsv_shape": "T-section",
            "qsv_bf_mm": 1200.0,
            "qsv_hf_mm": 300.0,
            "qsv_bw_mm": 400.0,
            "qsv_hw_mm": 700.0,
        },
    )
    at = _fresh()
    stale = {
        "t_orientation": "Flange at bottom",
        "qsv_t_orientation": "Flange at bottom",
        "annulus_outer_mm": 1337.0,
        "qsv_annulus_outer_mm": 1337.0,
        "annulus_inner_mm": 777.0,
        "qsv_annulus_inner_mm": 777.0,
    }
    for key, value in stale.items():
        at.session_state[key] = value
    at.session_state["_durable_input_scalars"] = {
        key: value for key, value in stale.items() if key.startswith("qsv_")
    }
    at.session_state["_pending_project"] = pre_expansion_project
    at.session_state["_qs_open"] = True
    at.session_state["_main_page"] = "Analysis"
    at.run()

    assert not at.exception
    assert at.selectbox(key="shape").value == "T-section"
    assert at.selectbox(key="t_orientation").value == "Flange at top"
    for key in (
        "annulus_outer_mm",
        "qsv_annulus_outer_mm",
        "annulus_inner_mm",
        "qsv_annulus_inner_mm",
    ):
        assert key not in at.session_state
        assert key not in at.session_state["_durable_input_scalars"]


def test_project_load_without_link_authorities_clears_stale_true_state():
    import project_io

    at = _fresh()
    at.session_state["shear_links"] = True
    at.session_state["torsion_nu_v"] = True
    at.session_state["_durable_input_scalars"] = {
        "shear_links": True,
        "torsion_nu_v": True,
    }
    at.session_state["_pending_project"] = project_io.dump_project({}, {})
    at.run()

    assert not at.exception
    assert at.session_state["shear_links"] is False
    assert at.session_state["torsion_nu_v"] is False
    assert at.session_state["_durable_input_scalars"]["shear_links"] is False
    assert at.session_state["_durable_input_scalars"]["torsion_nu_v"] is False
    assert at.checkbox(key="shear_links").value is False
    assert at.checkbox(key="torsion_nu_v").value is False


def test_current_expanded_quick_section_keys_apply_after_hot_project_load():
    import project_io

    at = _fresh_qs()
    at.session_state["qsv_t_orientation"] = "Flange at top"
    at.session_state["t_orientation"] = "Flange at top"
    at.session_state["_pending_project"] = project_io.dump_project(
        {},
        {
            "qsv_shape": "T-section",
            "qsv_bf_mm": 1200.0,
            "qsv_hf_mm": 300.0,
            "qsv_bw_mm": 400.0,
            "qsv_hw_mm": 700.0,
            "qsv_t_orientation": "Flange at bottom",
        },
    )
    at.session_state["_qs_open"] = True
    at.run()

    assert not at.exception
    assert at.selectbox(key="shape").value == "T-section"
    assert at.selectbox(key="t_orientation").value == "Flange at bottom"


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
    _set_and_click(at2, "qs_back")                      # (sets qs_shape_prev)
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
    _goto_input_tab(at, "Project")
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


def test_calculation_results_have_no_trace_payload_or_trace_view():
    at = _fresh()
    at.run()
    _set_and_click(at, "calculate", ("number_input", "pl_Mx", 50.0))
    assert not at.exception
    results = at.session_state["results"]
    entry = results["plastic_cases"][0]
    assert "calculation_traces" not in entry["results"]
    assert "calculation_traces" not in results
    assert len(at.session_state["calculation_record"]["result_sha256"]) == 64
    view = at.selectbox(key="view")
    assert "Calculation Trace" not in view.options
    assert all(
        box.key != "calculation_trace_selection" for box in at.selectbox
    )

def test_plastic_view_fails_closed_for_a_legacy_pre_contract_result():
    # A cached legacy payload still renders its capacity evidence, but cannot retain
    # a green utilisation verdict after the origin-containment contract changes.
    at = _fresh()
    at.run()
    _calculate(at)
    plastic = at.session_state["results"]["plastic"]
    for key in (
        "min_mx",
        "min_my",
        "util_valid",
        "util_reason",
        "util_origin_inside_or_on",
    ):
        plastic.pop(key, None)
    _select_view(at, "Plastic Results")

    assert not at.exception
    assert any(
        "NOT ASSESSED - Plastic bending" in item.value
        and "cannot confirm that the M-M envelope contains the origin" in item.value
        for item in at.warning
    )
    assert not any("PASS - Plastic bending" in item.value for item in at.success)


def test_combined_view_fails_closed_for_legacy_pre_contract_bending():
    at = _fresh()
    at.run()
    _calculate(at)
    results = at.session_state["results"]
    results["plastic"].pop("util_valid", None)
    results["combined"] = {
        "valid": True,
        "method": "DK NA",
        "r_m": 0.6,
        "r_v": 0.2,
        "r_t": 0.1,
        "dkna_sum": 0.9,
        "dkna_ok": True,
        "m_v_independent": False,
        "asl_torsion": 0.0,
        "delta_ftd": 0.0,
    }
    case_results = results["plastic_cases"][0]["results"]
    case_results["plastic"].pop("util_valid", None)
    case_results["combined"] = dict(results["combined"])

    _select_view(at, "M-V-T Combined")

    assert not at.exception
    assert any(
        "not assessed" in item.value.casefold()
        and "saved bending result cannot confirm" in item.value.casefold()
        and "contains the origin" in item.value.casefold()
        and "recalculate" in item.value.casefold()
        for item in at.warning
    )
    assert not any("Selected calculation method: DK NA" in item.value for item in at.caption)
    assert not any("90.0 %" in str(item.value) for item in at.metric)


def test_calculate_elastic_produces_bar_stresses():
    at = _fresh()
    at.run()
    _set_and_click(at, "calculate", ("radio", "mode", "Elastic"))
    assert not at.exception
    res = at.session_state["results"]
    assert "elastic" in res
    assert len(res["elastic"]["total"]) > 0
    shared_keys = {
        "section_properties", "material_properties",
        "prestress_initial", "elastic_shared",
    }
    assert shared_keys <= set(res)
    assert res["section_properties"]["net_concrete"]["area_m2"] > 0.0
    assert res["material_properties"]["concrete"]["design_strength_mpa"] > 0.0
    assert res["elastic_shared"]["concrete_modulus_mpa"] > 0.0
    assert res["elastic_shared"]["materials"]
    for family in ("plastic_cases", "elastic_cases"):
        for entry in res.get(family, []):
            assert not shared_keys & set(entry.get("results") or {})


def test_run_analysis_prepares_shared_calculations_once_across_named_cases(
    monkeypatch,
):
    """Named cases share one compact preparation result, never a trace."""

    import importlib
    import sector_app
    from sector.materials import Concrete, MildSteel, Prestress
    from sector.section import Section

    case_analysis_core = importlib.import_module("case_analysis")
    capacity_core = importlib.import_module("sector.capacity")
    elastic_core = importlib.import_module("sector.elastic")
    geometry_core = importlib.import_module("sector.geometry")

    concrete = Concrete(fck=30.0, gamma_c=1.5, curve=2)
    steel = MildSteel(
        fytk=500.0, fyck=500.0, futk=550.0, eut=0.05,
        gamma_y=1.15, curve=2,
    )
    prestress = Prestress(curve=1, IS=0.005, gamma_y=1.15)
    inp = {
        "mode": "Elastic",
        "section": Section.from_polygon(
            [(-0.10, -0.15), (0.10, -0.15),
             (0.10, 0.15), (-0.10, 0.15)],
            bars_xy_area_mm2=[(0.0, -0.12, 500.0)],
        ),
        "geometry_error": None, "void_error": None,
        "steel_error": None, "material_error": None,
        "outer": [(-0.10, -0.15), (0.10, -0.15),
                  (0.10, 0.15), (-0.10, 0.15)],
        "holes": [],
        "bars": [(0.0, -0.12, 500.0)],
        "bar_elements": [{"id": "R1", "material_id": "M1"}],
        "bar_materials": [steel], "mild_materials": {"M1": steel},
        "steel": steel, "capacity_steel_material_id": "M1",
        "tendons": [(0.0, -0.10, 500.0)],
        "tendon_elements": [{"id": "T1", "material_id": "P1"}],
        "tendon_materials": [prestress],
        "prestress_materials": {"P1": prestress},
        "prestress": prestress,
        "concrete": concrete, "concrete_preset": "EN 1992-1-1:2005",
        "concrete_eta_cc": 1.0, "concrete_k_tc": 1.0,
        "conc_Ec": 33.0, "el_phi": 1.5,
        "plastic_cases": [], "elastic_cases": [],
        "shear_on": False, "torsion_on": False,
        "clear_spacing_on": False, "fatigue_on": False,
    }
    counts = {
        "geometry": 0, "fcd": 0, "fyd": 0, "prestress_law": 0,
        "prestress": 0, "ratios": 0,
    }

    def counted(name, function):
        def wrapper(*args, **kwargs):
            counts[name] += 1
            return function(*args, **kwargs)
        return wrapper

    monkeypatch.setattr(
        geometry_core,
        "area_moment_breakdown",
        counted("geometry", geometry_core.area_moment_breakdown),
    )
    monkeypatch.setattr(
        Concrete,
        "fcd",
        property(counted("fcd", Concrete.fcd.fget)),
    )
    monkeypatch.setattr(
        capacity_core,
        "design_yield",
        counted("fyd", capacity_core.design_yield),
    )
    monkeypatch.setattr(
        Prestress,
        "stress",
        counted("prestress_law", Prestress.stress),
    )
    monkeypatch.setattr(
        capacity_core,
        "locked_in_prestress_result",
        counted("prestress", capacity_core.locked_in_prestress_result),
    )
    monkeypatch.setattr(
        elastic_core,
        "calculate_modular_ratios",
        counted("ratios", elastic_core.calculate_modular_ratios),
    )

    calls = []

    def fake_single(
        case_inp,
        *,
        reuse_plastic=None,
        reuse_elastic=None,
        elastic_solver_inputs=None,
        shared_results=None,
    ):
        calls.append((case_inp["case_id"], elastic_solver_inputs, shared_results))
        return {"elastic": {"case_id": case_inp["case_id"]}}

    def fake_cases(base, runner, **_kwargs):
        first = runner(dict(base, case_id="EL-A"))
        second = runner(dict(base, case_id="EL-B"))
        return {
            "elastic_cases": [
                {"name": "EL-A", "results": first},
                {"name": "EL-B", "results": second},
            ],
        }

    monkeypatch.setattr(sector_app, "_run_single_analysis", fake_single)
    monkeypatch.setattr(case_analysis_core, "run_case_tables", fake_cases)

    result = sector_app.run_analysis(inp)
    assert counts == {
        "geometry": 1, "fcd": 1, "fyd": 1, "prestress_law": 1,
        "prestress": 1, "ratios": 1,
    }
    assert calls[0][1] is calls[1][1]
    assert calls[0][2] is calls[1][2]
    shared_keys = {
        "section_properties", "material_properties",
        "prestress_initial", "elastic_shared",
    }
    assert shared_keys <= set(result)
    assert result["worked_example_selection"] == {
        "schema": 1,
        "families": {},
        "crack_examples": [],
        "crack_comparison": None,
        "cracking_threshold": None,
        "heightened_crack_control": None,
        "torsion_subchecks": {},
    }
    for entry in result["elastic_cases"]:
        assert not shared_keys & set(entry["results"])


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
    plastic = at.session_state["results"]["plastic"]
    assert plastic["util"] is not None
    assert plastic["util_valid"] is True
    assert plastic["util_reason"] is None
    assert plastic["util_origin_inside_or_on"] is True


def test_origin_invalid_plastic_result_is_retained_and_rendered_invalid(monkeypatch):
    import sector_app
    import sector.combined as combined_core
    from sector.combined import RadialUtilResult

    reason = "Global moment origin lies outside the closed M-M envelope"
    monkeypatch.setattr(
        combined_core,
        "radial_util_result",
        lambda *_args, **_kwargs: RadialUtilResult(
            demand=0.0,
            resistance=None,
            utilisation=None,
            governing_index=None,
            valid=False,
            reason=reason,
            origin_inside_or_on=False,
        ),
    )
    at = _fresh()
    at.run()
    _calculate(at)

    plastic = at.session_state["results"]["plastic"]
    assert plastic["util"] is None
    assert plastic["util_valid"] is False
    assert plastic["util_reason"] == reason
    assert plastic["util_origin_inside_or_on"] is False
    assert plastic["worked_point_basis"] == "peak resultant moment"
    _select_view(at, "Plastic Results")
    assert any(
        "INVALID - Plastic bending" in item.value and reason in item.value
        for item in at.error
    )
    assert not at.exception


def test_plastic_result_overview_has_compact_verdict_and_qa_tables():
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
    assert any("utilisation" in item.value for item in at.success)
    assert not any("margin" in item.value.casefold() for item in at.success)
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
    assert not any("margin" in item.value.casefold() for item in at.error)


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


def test_assembled_report_payload_retains_interaction_and_bond_selection():
    at = _fresh()
    at.run()
    _goto_input_tab(at, "Analysis settings")
    at.checkbox(key="pl_interaction").set_value(True).run()
    at.selectbox(key="sls_bond").set_value(
        "Plain round (k1 = 1.6)"
    ).run()

    assert not at.exception
    latest = at.session_state["_latest_inputs"]
    assert latest["interaction"] is True
    assert latest["sls_bond"] == "Plain round (k1 = 1.6)"
    assert latest["sls_k1"] == pytest.approx(1.6)


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


def test_plastic_selected_state_lists_retained_compression_zone_depth():
    at = _fresh()
    at.run()
    _calculate(at)
    _select_view(at, "Plastic Results")
    result = at.session_state["results"]["plastic"]
    point = result["points"][at.session_state["pl_state"]]
    expected = point["compression_depth"] * 1000.0

    summary = next(
        item.value
        for item in at.markdown
        if "Compression-zone depth" in item.value
    )
    assert "Compression-zone depth" in summary
    assert f"{expected:.3f} mm" in summary
    assert "Source state" in summary and "PL-01" in summary
    assert f"NA angle = {point['V']:.0f}" in summary
    assert "Internal lever arm $z$" in summary
    assert "Lever-arm components $z_x$ / $z_y$" in summary
    assert "$D_x$" not in summary and "$D_y$" not in summary
    assert not any(
        "not effective depths d" in item.value for item in at.caption
    )
    depth = next(
        frame.value
        for frame in at.dataframe
        if "Tension-bar IDs" in frame.value.columns
        and "Calculated arm component" in frame.value.columns
    )
    assert len(depth) == 4
    assert set(depth["Bending axis"]) == {"x", "y"}
    assert set(depth["Tension face"]) == {
        "bottom (-y)", "top (+y)", "left (-x)", "right (+x)"
    }
    assert set(depth["Calculated arm component"]) == {"z_x", "z_y"}

    interaction = next(
        json.loads(chart.proto.spec)
        for chart in at.get("plotly_chart")
        if (
            json.loads(chart.proto.spec)
            .get("layout", {})
            .get("xaxis", {})
            .get("title", {})
            .get("text")
            == "My - about the y-axis (kNm)"
        )
    )
    capacity = next(
        trace for trace in interaction["data"] if trace.get("name") == "capacity"
    )
    assert capacity["mode"] == "lines+markers"
    assert capacity["hoveron"] == "points"
    assert "neutral-axis angle = %{customdata[1]:.0f} deg" in (
        capacity["hovertemplate"]
    )
    assert "|M<sub>Rd</sub>| = %{customdata[0]:.1f} kNm" in (
        capacity["hovertemplate"]
    )


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
    assert f"NA angle ({chr(0x00B0)})" in active
    assert "Internal lever z (mm)" in active
    assert "F_comp (kN)" in active
    assert "Fc (kN)" not in active
    assert "z_x (mm)" in active and "z_y (mm)" in active
    assert "dx (mm)" not in active and "dy (mm)" not in active
    assert not any("deg" in c for c in active)
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


def test_plastic_hover_formats_retained_stress_and_strain_without_a_material_law():
    from sector_app import (
        _elastic_corner_hover,
        _elastic_state_hover,
        _plastic_state_hover,
    )

    rows = [
        {
            "stress_mpa": 500.0,
            "strain_permille": 5.0,
            "material_id": "M<br>1 &",
            "material_name": "B500 <i>trial</i>",
        },
        {"stress_mpa": -420.0, "strain_permille": -5.0, "material_id": "M2"},
    ]
    hover = _plastic_state_hover(rows)
    assert "500.0 MPa" in hover[0]
    assert "= 0.500 %" in hover[0]
    assert "material M&lt;br&gt;1 &amp; - B500 &lt;i&gt;trial&lt;/i&gt;" in hover[0]
    assert "M<br>1" not in hover[0] and "<i>trial</i>" not in hover[0]
    assert "= -0.500 %" in hover[1]
    assert "material M2" in hover[1]
    assert _plastic_state_hover([]) is None

    elastic = _elastic_state_hover([
        {
            "total_mpa": 212.3456,
            "strain_permille": 1.0617,
            "material_id": "M<br>1 &",
            "material_name": "B500 <i>trial</i>",
        },
        {
            "total_mpa": 900.0,
            "strain_permille": 4.5,
            "material_id": None,
            "material_name": None,
        },
    ])
    assert "212.346 MPa" in elastic[0]
    assert "1.0617 " + chr(0x2030) in elastic[0]
    assert (
        "material = M&lt;br&gt;1 &amp; - B500 &lt;i&gt;trial&lt;/i&gt;"
        in elastic[0]
    )
    assert "M<br>1" not in elastic[0] and "<i>trial</i>" not in elastic[0]
    assert "900.000 MPa" in elastic[1]
    assert "material" not in elastic[1]
    assert _elastic_state_hover([]) is None

    corner = _elastic_corner_hover([
        {
            "ring": "Outer",
            "ring_point_no": 2,
            "stress_mpa": -18.25,
            "strain_permille": -0.6083,
        }
    ])
    assert "Outer point 2" in corner[0]
    assert "-18.250 MPa" in corner[0]
    assert "-0.6083 " + chr(0x2030) in corner[0]
    assert _elastic_corner_hover([]) is None


def test_plastic_and_elastic_result_views_route_response_only_section_hover():
    at = _fresh_qs()
    _set_and_click(
        at, "qs_apply", ("number_input", "tnd_n", 4)
    )
    _set_and_click(at, "calculate", ("radio", "mode", "Both"))

    _select_view(at, "Plastic Results")
    plastic_hover = _section_hover_from_result_view(at)
    plastic_bar = next(value for value in plastic_hover if value.startswith("Bar "))
    plastic_tendon = next(
        value for value in plastic_hover if value.startswith("Tendon ")
    )
    for value in (plastic_bar, plastic_tendon):
        assert "MPa" in value and "%" in value
        assert "material" in value
        assert "x =" not in value and "y =" not in value
        assert "area =" not in value
    assert "material P1" in plastic_tendon

    _select_view(at, "Elastic Results")
    elastic_hover = _section_hover_from_result_view(at)
    elastic_bar = next(value for value in elastic_hover if value.startswith("Bar "))
    elastic_tendon = next(
        value for value in elastic_hover if value.startswith("Tendon ")
    )
    elastic_corner = next(
        value for value in elastic_hover if value.startswith("Corner ")
    )
    for value in (elastic_bar, elastic_tendon, elastic_corner):
        assert "MPa" in value and chr(0x2030) in value
        assert "x =" not in value and "y =" not in value
        assert "area =" not in value
    for value in (elastic_bar, elastic_tendon):
        assert "total" in value and "material" in value
    assert "material = P1" in elastic_tendon
    assert "Outer point" in elastic_corner


def test_both_mode_runs_elastic_and_plastic():
    at = _fresh()
    at.run()
    _set_and_click(at, "calculate", ("radio", "mode", "Both"))
    assert not at.exception
    res = at.session_state["results"]
    assert "plastic" in res and "elastic" in res


def test_plastic_and_elastic_payloads_retain_one_textbook_ready_final_state():
    at = _fresh()
    at.run()
    _set_and_click(at, "calculate", ("radio", "mode", "Both"))
    assert not at.exception

    results = at.session_state["results"]
    plastic = results["plastic"]
    point = plastic["points"][plastic["worked_point_index"]]
    assert point["concrete_corner_states"]
    assert point["reinforcement_states"]
    assert point["curvature_candidates"]
    assert point["curvature_selection"]
    for candidate in point["curvature_candidates"]:
        assert candidate["curvature_per_m"] == pytest.approx(
            candidate["strain_limit"] / candidate["distance_from_na_m"]
        )
    assert point["axial_achieved"] == pytest.approx(
        point["concrete_force"] + point["bar_force"] + point["tendon_force"]
    )
    assert point["Mx"] == pytest.approx(
        point["concrete_mx"] + point["bar_mx"] + point["tendon_mx"]
    )
    assert point["My"] == pytest.approx(
        point["concrete_my"] + point["bar_my"] + point["tendon_my"]
    )

    elastic = results["elastic"]
    assert set(elastic["accepted_states"]) == {
        "long_term",
        "instantaneous_combined",
    }
    for state in elastic["accepted_states"].values():
        assert len(state["equilibrium"]["matrix"]) == 3
        assert set(state["equilibrium"]["target"]) == {"n", "mx", "my"}
        assert set(state["equilibrium"]["internal"]) == {"n", "mx", "my"}
        assert set(state["equilibrium"]["residual"]) == {"n", "mx", "my"}
    superposition = elastic["superposition"]
    assert superposition["long_term_reduction_factor"] == pytest.approx(
        1.0
        - superposition["short_term_modular_ratio"]
        / superposition["long_term_modular_ratio"]
    )
    for element in elastic["elements"]:
        assert element["total_mpa"] == pytest.approx(
            element["reduced_long_mpa"]
            + element["rst1_mpa"]
            + element["locked_in_mpa"]
        )
        assert element["dif_mpa"] == pytest.approx(
            element["total_mpa"] - element["long_mpa"]
        )

    assert "calculation_evidence" not in results
    assert "trace" not in results


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


def test_plastic_result_contract_invalidates_every_pre_contract_reuse_gate():
    import sector_app

    at = _fresh()
    at.run()
    _set_and_click(at, "calculate", ("radio", "mode", "Both"))
    latest = at.session_state["_latest_inputs"]
    token = sector_app._PLASTIC_RESULT_CONTRACT_TOKEN

    for key in (
        "plastic_bending_context_sig",
        "plastic_case_context_sig",
        "plastic_sig",
        "signature",
    ):
        assert tuple(latest[key]).count(token) == 1
    assert token not in tuple(latest["elastic_case_context_sig"])
    assert token not in tuple(latest["elastic_sig"])

    plastic_before = at.session_state["results"]["plastic"]
    elastic_before = at.session_state["results"]["elastic"]
    pre_amend_token = (
        "plastic-result-contract",
        "m-m-origin-containment-v1",
    )
    for key in (
        "result_plastic_sig",
        "result_plastic_case_context_sig",
        "result_plastic_bending_context_sig",
    ):
        at.session_state[key] = tuple(
            pre_amend_token if item == token else item
            for item in at.session_state[key]
        )

    _calculate(at)
    results = at.session_state["results"]
    assert results["plastic"] is not plastic_before
    assert results["elastic"] is elastic_before
    assert results["plastic_cases"][0]["reused"] is False
    assert results["elastic_cases"][0]["reused"] is True


def test_capacity_result_contract_invalidates_capacity_without_bending_or_elastic():
    import sector_app

    at = _fresh()
    at.run()
    _set_and_click(
        at,
        "calculate",
        ("radio", "mode", "Both"),
        ("checkbox", "torsion_on", True),
        ("number_input", "torsion_T", 30.0),
    )
    latest = at.session_state["_latest_inputs"]
    token = sector_app._CAPACITY_RESULT_CONTRACT_TOKEN
    assert token[-1] == "closed-torsion-link-authority-v1"

    for key in ("plastic_case_context_sig", "plastic_sig", "signature"):
        assert tuple(latest[key]).count(token) == 1
    for key in (
        "plastic_bending_context_sig",
        "elastic_case_context_sig",
        "elastic_sig",
        "fatigue_sig",
    ):
        assert token not in tuple(latest[key])
    pre_contract_inputs = copy.deepcopy(latest)
    pre_contract_inputs["signature"] = tuple(
        item for item in latest["signature"] if item != token
    )
    assert sector_app._engineering_input_hash(
        pre_contract_inputs
    ) != sector_app._engineering_input_hash(latest)

    plastic_before = at.session_state["results"]["plastic"]
    torsion_before = at.session_state["results"]["torsion"]
    elastic_before = at.session_state["results"]["elastic"]
    for key in (
        "result_sig",
        "result_plastic_sig",
        "result_plastic_case_context_sig",
    ):
        at.session_state[key] = tuple(
            item for item in at.session_state[key] if item != token
        )
    assert at.session_state["result_sig"] != latest["signature"]

    _calculate(at)
    results = at.session_state["results"]
    assert results["plastic"] is plastic_before
    assert results["torsion"] is not torsion_before
    assert results["elastic"] is elastic_before
    assert results["plastic_cases"][0]["reused"] is False
    assert results["elastic_cases"][0]["reused"] is True
    assert at.session_state["result_plastic_bending_context_sig"] == (
        latest["plastic_bending_context_sig"]
    )
    for key in (
        "result_sig",
        "result_plastic_sig",
        "result_plastic_case_context_sig",
    ):
        assert tuple(at.session_state[key]).count(token) == 1


def test_eccentric_prestress_alone_cracks_through_the_real_app_adapter():
    import io

    import load_cases
    import pandas as pd
    import pypdf
    import reinforcement_table
    import sector_app
    import sector_report

    at = _fresh()
    at.run()
    _set(at, ("radio", "mode", "Elastic"))
    _replace_base_table(at, "corners_base", pd.DataFrame({
        "x (mm)": [-150.0, -150.0, 150.0, 150.0],
        "y (mm)": [-300.0, 300.0, 300.0, -300.0],
    }))
    _replace_base_table(at, "bars_base", reinforcement_table.empty_table())
    _replace_base_table(
        at,
        "tendons_base",
        reinforcement_table.table_from_points(
            [(0.0, -250.0, 1000.0)], "tendon"
        ),
    )
    cases = at.session_state[load_cases.ELASTIC_TABLE_KEY].copy(deep=True)
    for column in load_cases.ELASTIC_ACTION_NUMERIC:
        cases.at[0, column] = 0.0
    cases.at[0, "calculate_crack_width"] = False
    case_name = str(cases.at[0, "name"])
    _replace_case_table(at, load_cases.ELASTIC_TABLE_KEY, cases)
    _set(
        at,
        ("number_input", "mild_Es", 200.0),
        ("number_input", "conc_Ec", 200.0 / 6.85),
        ("number_input", "el_phi", 0.0),
        ("number_input", "sls_fctm", 2.9),
        ("number_input", "pre_Es", 195.0),
        ("number_input", "pre_IS", 500.0 / 195.0),
    )
    _calculate(at)

    assert not at.exception
    latest = at.session_state["_latest_inputs"]
    results = at.session_state["results"]
    assert latest["nl"] == pytest.approx(6.85, rel=1e-12)
    assert latest["ns"] == pytest.approx(6.85, rel=1e-12)
    assert not latest["bars"]
    assert len(latest["tendons"]) == 1
    assert latest["tendons"][0] == pytest.approx((0.0, -0.25, 1000.0))
    tendon = latest["tendon_materials"][0]
    assert tendon.Es == pytest.approx(195_000.0)
    assert tendon.IS == pytest.approx(500.0 / 195_000.0, rel=1e-12)
    assert results["prestress_initial"]["elements"][0][
        "locked_in_stress_mpa"
    ] == pytest.approx(500.0, rel=1e-12)

    n_mult, prestress_stress = sector_app._elastic_solver_inputs(latest, results)
    assert n_mult == pytest.approx([0.975], rel=1e-12)
    assert prestress_stress == pytest.approx([500_000.0], rel=1e-12)

    expected_sigma_ct = 3.7389176145082486
    elastic_results = (
        results["elastic"],
        results["elastic_cases"][0]["results"]["elastic"],
    )
    for elastic in elastic_results:
        assert elastic["sigma_ct"] == pytest.approx(
            expected_sigma_ct, rel=1e-12
        )
        assert elastic["lambda_cr"] == 0.0
        assert elastic["cracked"] is True
        assert elastic["props_cr"] is not None
    assert results["worked_example_selection"]["cracking_threshold"] == {
        "case_id": case_name,
    }

    _select_view(at, "Elastic Results")
    warning_text = "\n".join(str(item.value) for item in at.warning)
    assert "CRACKED" in warning_text
    assert "0.000" in warning_text
    assert "fixed prestress already reaches the tensile threshold" in warning_text
    metric = next(
        item for item in at.metric if "Cracking factor" in item.label
    )
    assert metric.value == "0.000"
    for expected in (
        "external N/M",
        "prestress remains fixed",
        "above fctm",
        "lambda_cr < 1 is cracked",
        "lambda_cr >= 1 is uncracked",
    ):
        assert expected in metric.help
    assert not any("UNCRACKED" in str(item.value) for item in at.success)

    report_buffer = io.BytesIO()
    sector_report.ReportBuilder(
        report_buffer,
        {},
        latest,
        results,
        figures=False,
        qa_appendix=False,
    ).build()
    report_text = " ".join(
        " ".join((page.extract_text() or "").split())
        for page in pypdf.PdfReader(
            io.BytesIO(report_buffer.getvalue())
        ).pages
    )
    compact_report = report_text.replace(" ", "")
    assert (
        chr(0x03C3) + "pre,i+" + chr(0x03BB) + "cr"
        + chr(0x03C3) + "ext,i=fct,eff"
    ) in compact_report
    for expected in (
        (
            "1 -150.000 -300.000 2 -150.000 300.000 "
            "3 150.000 300.000 4 150.000 -300.000"
        ),
        "P1 0.000 -250.000 1000.000 35.682",
        "Elastic modulus Ep 195.0 GPa",
        "P1 P1 195000.0 0.002564 500.000 1000.0 500.000",
        "= 1 - 6.85 / 6.85",
        "Long-term 0.000 0.000 0.000 Short-term 0.000 0.000 0.000",
        "Locked-in prestress remains fixed",
        "A prestress-only fibre above",
        "only external N/M scales",
        "lowest positive fibre solution governs",
        "Calculated output:",
        "3.739 MPa",
        "0.000; section is cracked",
        "below 1: cracked; 1 or above: uncracked",
    ):
        assert expected in report_text


def test_elastic_result_contract_invalidates_every_pre_contract_reuse_gate():
    import sector_app

    at = _fresh()
    at.run()
    _set_and_click(at, "calculate", ("radio", "mode", "Both"))
    latest = at.session_state["_latest_inputs"]
    token = sector_app._ELASTIC_RESULT_CONTRACT_TOKEN

    for key in ("elastic_case_context_sig", "elastic_sig", "signature"):
        assert tuple(latest[key]).count(token) == 1
    for key in (
        "plastic_bending_context_sig",
        "plastic_case_context_sig",
        "plastic_sig",
        "fatigue_sig",
    ):
        assert token not in tuple(latest[key])

    plastic_before = at.session_state["results"]["plastic"]
    elastic_before = at.session_state["results"]["elastic"]
    elastic_sig_before = tuple(at.session_state["result_elastic_sig"])
    pre_contract_inputs = copy.deepcopy(latest)
    pre_contract_inputs["signature"] = tuple(
        item for item in latest["signature"] if item != token
    )
    assert sector_app._engineering_input_hash(
        pre_contract_inputs
    ) != sector_app._engineering_input_hash(latest)
    for key in (
        "result_sig",
        "result_elastic_sig",
        "result_elastic_case_context_sig",
    ):
        at.session_state[key] = tuple(
            item for item in at.session_state[key] if item != token
        )
    assert tuple(at.session_state["result_elastic_sig"]) != elastic_sig_before
    assert at.session_state["result_sig"] != latest["signature"]

    _calculate(at)
    results = at.session_state["results"]
    assert results["elastic"] is not elastic_before
    assert results["plastic"] is plastic_before
    assert results["elastic_cases"][0]["reused"] is False
    assert results["plastic_cases"][0]["reused"] is True
    for key in (
        "result_sig",
        "result_elastic_sig",
        "result_elastic_case_context_sig",
    ):
        assert tuple(at.session_state[key]).count(token) == 1


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


def test_expanded_quick_section_catalogue_previews_and_applies():
    expected_catalogue = [
        "Rectangle",
        "Slab strip",
        "Trapezoid",
        "T-section",
        "L-section",
        "I-section",
        "U-section",
        "Box girder",
        "Circular",
        "Annulus",
    ]
    cases = [
        ("Trapezoid", 4, 0, False),
        ("L-section", 6, 0, False),
        ("I-section", 12, 0, True),
        ("U-section", 8, 0, False),
        ("Annulus", 48, 48, True),
    ]
    at = _fresh_qs()
    assert list(at.selectbox(key="shape").options) == expected_catalogue

    for index, (shape, corners, hole_corners, has_auto_rebar) in enumerate(cases):
        at.selectbox(key="shape").set_value(shape).run()
        assert not at.exception, shape
        xs, _ys = _section_outline_from_result_view(at)
        assert len(xs) == corners + 1, shape  # Plotly closes the filled outer ring
        if not has_auto_rebar:
            assert any(
                "Automatic reinforcement placement is not defined" in info.value
                for info in at.info
            ), shape

        _apply_qs(at)
        assert not at.exception, shape
        assert len(at.session_state["corners_base"]) == corners, shape
        assert len(at.session_state["hole_base"]) == hole_corners, shape
        if has_auto_rebar:
            assert len(at.session_state["bars_base"]) > 0, shape
        else:
            assert len(at.session_state["bars_base"]) == 0, shape
            assert len(at.session_state["tendons_base"]) == 0, shape
        if index < len(cases) - 1:
            _open_qs(at)


def test_inverted_t_applies_flange_below_and_keeps_stacked_bars_in_web():
    at = _fresh_qs()
    at.selectbox(key="shape").set_value("T-section").run()
    _set_and_click(
        at,
        "qs_apply",
        ("selectbox", "t_orientation", "Flange at bottom"),
        ("number_input", "bot_layers", 2),
        ("number_input", "layer_s", 250.0),
        ("number_input", "tnd_n", 3),
        ("number_input", "tnd_layers", 2),
        ("number_input", "tnd_layer_s", 250.0),
    )
    assert not at.exception

    corners = at.session_state["corners_base"]
    bottom = corners[corners["y (mm)"] == corners["y (mm)"].min()]
    top = corners[corners["y (mm)"] == corners["y (mm)"].max()]
    assert bottom["x (mm)"].abs().max() == pytest.approx(600.0)
    assert top["x (mm)"].abs().max() == pytest.approx(150.0)

    bars = at.session_state["bars_base"]
    web_layer = bars[(bars["y (mm)"] > -150.0) & (bars["y (mm)"] < -50.0)]
    assert len(web_layer) == 6
    assert web_layer["x (mm)"].abs().max() <= 100.0

    tendons = at.session_state["tendons_base"]
    web_tendons = tendons[(tendons["y (mm)"] > -100.0) & (tendons["y (mm)"] < 0.0)]
    assert len(web_tendons) == 3
    assert web_tendons["x (mm)"].abs().max() <= 50.0


def test_annulus_applies_one_void_and_contained_bar_and_tendon_rings():
    from sector.geometry import points_inside_concrete

    at = _fresh_qs()
    at.selectbox(key="shape").set_value("Annulus").run()
    _set_and_click(
        at,
        "qs_apply",
        ("number_input", "ring_n", 12),
        ("number_input", "tnd_n", 8),
    )
    assert not at.exception
    assert len(at.session_state["corners_base"]) == 48
    assert len(at.session_state["hole_base"]) == 48
    assert len(at.session_state["bars_base"]) == 12
    assert len(at.session_state["tendons_base"]) == 8

    outer = [tuple(row / 1000.0) for row in at.session_state[
        "corners_base"
    ][["x (mm)", "y (mm)"]].to_numpy()]
    hole = [tuple(row / 1000.0) for row in at.session_state[
        "hole_base"
    ][["x (mm)", "y (mm)"]].to_numpy()]
    points = []
    for key in ("bars_base", "tendons_base"):
        points.extend(
            tuple(row / 1000.0)
            for row in at.session_state[key][["x (mm)", "y (mm)"]].to_numpy()
        )
    assert points_inside_concrete(points, outer, [hole]).all()


def test_invalid_quick_section_is_explained_and_cannot_be_applied():
    at = _fresh_qs()
    at.selectbox(key="shape").set_value("Annulus").run()
    at.number_input(key="annulus_inner_mm").set_value(900.0).run()

    assert not at.exception
    assert at.button(key="qs_apply").disabled
    assert any(
        "inner diameter must be less than outer diameter" in error.value
        for error in at.error
    )
    assert any("Preview unavailable" in info.value for info in at.info)


def test_zero_reinforcement_ignores_unused_cover_validation():
    at = _fresh_qs()
    at.selectbox(key="shape").set_value("Annulus").run()
    _set_and_click(
        at,
        "qs_apply",
        ("number_input", "ring_n", 0),
        ("number_input", "ring_c_mm", 300.0),
    )

    assert not at.exception
    assert len(at.session_state["corners_base"]) == 48
    assert len(at.session_state["hole_base"]) == 48
    assert len(at.session_state["bars_base"]) == 0

    solid = _fresh_qs()
    _set_and_click(
        solid,
        "qs_apply",
        ("number_input", "bot_n", 0),
        ("number_input", "top_n", 0),
        ("number_input", "bot_c_mm", 500.0),
        ("number_input", "top_c_mm", 500.0),
    )
    assert not solid.exception
    assert len(solid.session_state["corners_base"]) == 4
    assert len(solid.session_state["bars_base"]) == 0


def test_circular_shape_calculates():
    at = _fresh_qs()
    at.selectbox(key="shape").set_value("Circular").run()
    _apply_qs(at)                            # apply the builder to the points
    _calculate(at)
    assert not at.exception
    assert "plastic" in at.session_state["results"]


def test_quick_section_seeds_catalogues_before_generated_assignments():
    at = _fresh_qs()
    _set_and_click(at, "qs_apply", ("number_input", "tnd_n", 2))

    assert [item["id"] for item in at.session_state[
        "mild_material_catalog"]["items"]] == ["M1"]
    assert [item["id"] for item in at.session_state[
        "prestress_material_catalog"]["items"]] == ["P1"]
    assert set(at.session_state["bars_base"]["material ID"]) == {"M1"}
    assert set(at.session_state["tendons_base"]["material ID"]) == {"P1"}
    assert at.session_state["_latest_inputs"]["material_error"] is None


def test_quick_section_uses_live_catalogue_ids_after_first_suffix_is_deleted():
    import material_catalog

    mild, _ = material_catalog.add_entry(
        material_catalog.default_catalog("mild"), "mild"
    )
    mild = material_catalog.delete_entry(mild, "mild", "M1")
    prestress, _ = material_catalog.add_entry(
        material_catalog.default_catalog("prestress"), "prestress"
    )
    prestress = material_catalog.delete_entry(prestress, "prestress", "P1")

    at = _fresh_qs(
        mild_material_catalog=mild,
        prestress_material_catalog=prestress,
        _mild_catalog_selected="M2",
        _prestress_catalog_selected="P2",
    )
    _set_and_click(at, "qs_apply", ("number_input", "tnd_n", 2))

    assert set(at.session_state["bars_base"]["material ID"]) == {"M2"}
    assert set(at.session_state["tendons_base"]["material ID"]) == {"P2"}
    assert [item["id"] for item in at.session_state[
        "mild_material_catalog"]["items"]] == ["M2"]
    assert [item["id"] for item in at.session_state[
        "prestress_material_catalog"]["items"]] == ["P2"]
    assert at.session_state["_latest_inputs"]["material_error"] is None


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
    # the complete current-schema state into an independent session and calculate
    # there; action tables are inputs too and must not be replaced by empty defaults.
    post_back_project = project_io.dump_project(
        {
            key: at.session_state[key]
            for key in project_io.PROJECT_TABLE_KEYS
            if key in at.session_state
        },
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


def test_section_tables_hold_loaded_points_and_stable_reinforcement_schema():
    # Geometry remains coordinate-only. Reinforcement additionally retains stable
    # IDs, its declared size basis, and assignment metadata for later checks.
    import reinforcement_table as rt

    at = _fresh_qs()
    _set_and_click(at, "qs_apply", ("number_input", "tnd_n", 4))
    assert list(at.session_state["corners_base"].columns) == ["x (mm)", "y (mm)"]
    assert list(at.session_state["bars_base"].columns) == rt.COLUMNS
    assert list(at.session_state["tendons_base"].columns) == rt.COLUMNS
    assert len(at.session_state["corners_base"]) >= 3
    assert len(at.session_state["bars_base"]) >= 1
    assert len(at.session_state["tendons_base"]) >= 1
    assert at.session_state["bars_base"][rt.ELEMENT_ID].is_unique
    assert at.session_state["bars_base"][rt.ELEMENT_ID].str.fullmatch(r"R\d+").all()
    assert set(at.session_state["bars_base"][rt.SIZE_MODE]) == {rt.DIAMETER_MODE}
    assert set(at.session_state["tendons_base"][rt.SIZE_MODE]) == {rt.AREA_MODE}


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

    _goto_input_tab(at, "Section")
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
    assert "results" not in at.session_state


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
    _goto_input_tab(at, "Section")
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
    _goto_input_tab(at, "Section")
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
    _goto_input_tab(at, "Section")
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
    _goto_input_tab(at, "Section")
    assert not at.exception
    assert any("ignored" in w.value.lower() for w in at.warning)


def test_add_void_button_appends_a_separator():
    import pandas as pd
    at = _fresh()
    at.run()
    at.session_state["hole_base"] = pd.DataFrame({
        "x (mm)": [-100.0, -40.0, -70.0], "y (mm)": [-50.0, -50.0, 50.0]})
    _goto_input_tab(at, "Section")
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
    assert "results" not in at.session_state


def test_bow_tie_outline_is_blocked_in_ui_before_solver_entry():
    import pandas as pd

    at = _fresh()
    at.run()
    _replace_base_table(
        at,
        "corners_base",
        pd.DataFrame({
            "x (mm)": [-200.0, 200.0, -200.0, 200.0],
            "y (mm)": [-300.0, 300.0, 300.0, -300.0],
        }),
    )
    _goto_page(at, "Analysis")
    errors = [item.value for item in at.error]
    assert any(
        "Invalid section geometry" in message
        and "outer ring" in message
        and "edge 1" in message
        and "edge 3" in message
        for message in errors
    )
    _calculate(at)
    assert not at.exception
    try:
        results = at.session_state["results"]
    except KeyError:
        results = None
    assert not results


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
    assert "results" not in at.session_state


def test_high_grade_concrete_auto_strain_calculates():
    # Above C50/60 the Auto button fills the EC2 Table 3.1 strain limits and the
    # section still calculates (eps_cu2 ~ 2.66 permille at C70).
    at = _fresh()
    at.run()
    _goto_material_tab(at, "Concrete")
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
    _goto_material_tab(at, "Concrete")
    at.number_input(key="conc_eps_c2").set_value(5.0).run()   # peak above eps_cu2 (3.5)
    assert not at.exception
    assert any("must be at least" in w.value and "peak strain" in w.value
               for w in at.warning)
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
    _goto_material_tab(at, "Concrete")
    at.number_input(key="conc_fck").set_value(20.0).run()
    at.session_state["_pending_project"] = text
    at.run()
    assert at.session_state["conc_fck"] == 48.0
    plastic = at.session_state["plastic_cases_base"]
    assert plastic.loc[0, "name"] == "PL-ROUNDTRIP"
    assert plastic.loc[0, "description"] == "Source: Register C7"
    assert at.session_state["_loaded_project_provenance"]["input_hash_valid"] is True
    _goto_input_tab(at, "Project")
    assert any("file integrity verified" in caption.value for caption in at.caption)


def test_schema_25_shared_crack_width_migrates_with_visible_warning():
    import load_cases
    import project_io

    elastic = load_cases.normalise_table(
        [{"name": "EL-A", "calculate_crack_width": True}],
        load_cases.ELASTIC_TABLE_KEY,
    )
    payload = json.loads(project_io.dump_project(
        {load_cases.ELASTIC_TABLE_KEY: elastic},
        {
            "mode": "Elastic",
            "sls_code": _SLS_DK,
            "sls_long_term_permitted_crack_width_mm": 0.30,
            "sls_short_term_permitted_crack_width_mm": 0.25,
            "sls_heightened_permitted_crack_width_mm": 0.0,
        },
    ))
    payload["version"] = project_io.LEGACY_MIGRATABLE_VERSION
    payload["scalars"].pop("shear_gamma_v", None)
    for key in (
        "sls_long_term_permitted_crack_width_mm",
        "sls_short_term_permitted_crack_width_mm",
        "sls_heightened_permitted_crack_width_mm",
    ):
        payload["scalars"].pop(key)
    payload["scalars"][project_io.LEGACY_SHARED_CRACK_WIDTH_KEY] = 0.20
    payload["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": payload["tables"],
        "scalars": payload["scalars"],
    })
    source = json.dumps(payload)

    at = _fresh()
    at.session_state["_pending_project"] = source
    at.run()

    assert not at.exception
    assert "Sector converted the project file for this session" in (
        at.session_state["_project_msg"][1]
    )
    assert "schema" not in at.session_state["_project_msg"][1].casefold()
    for key in (
        "sls_long_term_permitted_crack_width_mm",
        "sls_short_term_permitted_crack_width_mm",
    ):
        assert at.session_state[key] == pytest.approx(0.20)
        assert at.number_input(key=key).value == pytest.approx(0.20)
    assert at.session_state[
        "sls_heightened_permitted_crack_width_mm"
    ] == 0.0
    assert any(
        "copied to the independent long-term and short-term inputs" in warning.value
        and "long-term and short-term" in warning.value
        for warning in at.warning
    )
    assert at.session_state["_loaded_project_provenance"][
        "schema_version"
    ] == 25
    expected_migration = {
        "source_schema_version": 25,
        "target_schema_version": 27,
        "warnings": [at.session_state["_project_migration_warnings"][0]],
        "migration_provenance": {
            "source_key": project_io.LEGACY_SHARED_CRACK_WIDTH_KEY,
            "shared_value_mm": 0.20,
            "long_term_value_mm": 0.20,
            "short_term_value_mm": 0.20,
            "heightened_value_mm": 0.0,
            "heightened_preserved": False,
            "shear_gamma_v": {
                "defaulted": True,
                "value": 1.40,
                "active_2023_shear": False,
            },
        },
    }
    assert at.session_state["_loaded_project_migration"] == expected_migration

    at.run()

    assert not at.exception
    assert at.session_state["_loaded_project_migration"] == expected_migration

    # A rejected replacement does not replace the active migrated project and
    # therefore must not strip its warning or structured migration evidence.
    expected_warnings = tuple(at.session_state["_project_migration_warnings"])
    at.session_state["_pending_project"] = "not valid project JSON"
    at.run()

    assert not at.exception
    assert at.session_state[
        "sls_long_term_permitted_crack_width_mm"
    ] == pytest.approx(0.20)
    assert at.session_state[
        "sls_short_term_permitted_crack_width_mm"
    ] == pytest.approx(0.20)
    assert at.session_state["_loaded_project_migration"] == expected_migration
    assert tuple(at.session_state["_project_migration_warnings"]) == expected_warnings
    assert at.session_state["_project_msg"][0] == "error"


def test_current_schema_load_clears_prior_migration_evidence():
    import project_io

    at = _fresh()
    at.session_state["_loaded_project_migration"] = {
        "source_schema_version": 24,
        "target_schema_version": 25,
        "warnings": ["stale"],
        "migration_provenance": {"selection_policy": "stale"},
    }
    at.session_state["_project_migration_warnings"] = ("stale",)
    at.session_state["_pending_project"] = project_io.dump_project({}, {})

    at.run()

    assert not at.exception
    assert "_loaded_project_migration" not in at.session_state
    assert "_project_migration_warnings" not in at.session_state


def test_app_restores_fatigue_inputs_into_the_ui():
    import fatigue_inputs
    import project_io
    from sector import design_standards

    spectrum = fatigue_inputs.normalise_spectrum_table([{
        "spectrum": "Traffic",
        "name": "FAT-01",
        "cycles": 2e6,
        "n_long_ed_kn": -500.0,
        "mx_short_ed_knm": 80.0,
    }])
    source = project_io.dump_project(
        {fatigue_inputs.SPECTRUM_TABLE_KEY: spectrum},
        {
            fatigue_inputs.DETAIL_CATALOG_KEY:
                fatigue_inputs.default_catalog(),
            "fatigue_on": True,
            "fatigue_gamma_s": 1.32,
        },
    )

    at = _fresh()
    at.session_state["_pending_project"] = source
    at.run()

    assert not at.exception
    assert fatigue_inputs.SPECTRUM_TABLE_KEY in at.session_state
    assert at.session_state["fatigue_on"] is True
    assert at.toggle(key="fatigue_on").value is True
    assert at.selectbox(key="fatigue_edition").value == (
        design_standards.DesignBasisKey.FIRST_GEN_DK_NA_2024.value
    )
    _goto_input_tab(at, "Loads")
    assert "fatigue_spectrum_editor" in at.session_state
    _goto_material_tab(at, "Fatigue details")
    assert at.selectbox(key="_fatigue_catalog_selected").value == "F1"
    assert (
        at.session_state[fatigue_inputs.DETAIL_CATALOG_KEY]["items"][0]["id"]
        == "F1"
    )
    at.button(key="fatigue_catalog_add_tendon").click().run()
    assert not at.exception
    assert fatigue_inputs.detail_ids(
        at.session_state[fatigue_inputs.DETAIL_CATALOG_KEY],
        fatigue_inputs.PRESTRESS,
    )

    saved = project_io.dump_project(
        {
            key: at.session_state[key]
            for key in project_io.PROJECT_TABLE_KEYS
            if key in at.session_state
        },
        {
            key: at.session_state[key]
            for key in project_io.SCALAR_KEYS
            if key in at.session_state
        },
    )
    restored_tables, restored_scalars = project_io.parse_project(saved)
    assert fatigue_inputs.spectrum_records(
        restored_tables[fatigue_inputs.SPECTRUM_TABLE_KEY]
    ) == fatigue_inputs.spectrum_records(spectrum)
    assert restored_scalars["fatigue_gamma_s"] == 1.32


def test_loading_nonfatigue_project_clears_prior_fatigue_state():
    import fatigue_inputs
    import project_io

    fatigue_project = project_io.dump_project(
        {
            fatigue_inputs.SPECTRUM_TABLE_KEY:
                fatigue_inputs.normalise_spectrum_table([{
                    "spectrum": "Traffic",
                    "name": "FAT-01",
                    "cycles": 2e6,
                }])
        },
        {
            fatigue_inputs.DETAIL_CATALOG_KEY:
                fatigue_inputs.default_catalog(),
            "fatigue_on": True,
            "fatigue_gamma_c": 1.595,
            "fatigue_source": "Previous project",
        },
    )
    at = _fresh()
    at.session_state["_pending_project"] = fatigue_project
    at.run()
    assert at.session_state["fatigue_on"] is True

    current_nonfatigue_project = project_io.dump_project(
        {},
        {"mode": "Plastic"},
    )
    at.session_state["_pending_project"] = current_nonfatigue_project
    at.run()

    assert not at.exception
    # The mounted UI seeds neutral defaults after clearing the previous project.
    # Values from the first project must not leak into those defaults.
    assert at.session_state["fatigue_on"] is False
    assert fatigue_inputs.spectrum_records(
        at.session_state[fatigue_inputs.SPECTRUM_TABLE_KEY]
    ) == []
    assert at.session_state["fatigue_gamma_c"] == pytest.approx(1.50)
    assert at.session_state[fatigue_inputs.BASIS_KEY] == (
        fatigue_inputs.default_basis()
    )
    assert fatigue_inputs.detail_ids(
        at.session_state[fatigue_inputs.DETAIL_CATALOG_KEY]
    ) == ["F1"]
    saved = project_io.dump_project(
        {
            key: at.session_state[key]
            for key in project_io.PROJECT_TABLE_KEYS
            if key in at.session_state
        },
        {
            key: at.session_state[key]
            for key in project_io.SCALAR_KEYS
            if key in at.session_state
        },
    )
    payload = json.loads(saved)
    assert (
        payload["tables"][fatigue_inputs.SPECTRUM_TABLE_KEY]["rows"] == []
    )
    assert payload["scalars"]["fatigue_on"] is False
    assert payload["scalars"]["fatigue_gamma_c"] == pytest.approx(1.50)


def test_loading_project_without_heightened_check_clears_prior_dk_state():
    import load_cases
    import project_io
    from sector import design_standards

    elastic = load_cases.normalise_table(
        [{
            "name": "Reference SLS",
            "calculate_crack_width": True,
        }],
        load_cases.ELASTIC_TABLE_KEY,
    )
    heightened_project = project_io.dump_project(
        {load_cases.ELASTIC_TABLE_KEY: elastic},
        {
            "mode": "Elastic",
            "sls_code": design_standards.DesignBasisKey.FIRST_GEN_DK_NA_2024.value,
            "sls_heightened_on": True,
            "sls_heightened_reference_case": "Reference SLS",
            "sls_heightened_reinforcement_surface": "smooth",
            "sls_heightened_effective_tensile_strength_mpa": 2.9,
            "sls_long_term_permitted_crack_width_mm": 0.20,
            "sls_short_term_permitted_crack_width_mm": 0.20,
            "sls_heightened_permitted_crack_width_mm": 0.20,
            "sls_heightened_fine_effective_tension_area_mm2": 60_000.0,
            "sls_heightened_coarse_effective_tension_area_mm2": 80_000.0,
        },
    )
    at = _fresh()
    at.session_state["_pending_project"] = heightened_project
    at.run()
    assert not at.exception
    assert at.session_state["sls_heightened_on"] is True

    at.session_state["_pending_project"] = project_io.dump_project(
        {},
        {"mode": "Plastic"},
    )
    at.run()

    assert not at.exception
    state = at.session_state.filtered_state
    expected_defaults = {
        "sls_heightened_on": False,
        "sls_heightened_reference_case": "",
        "sls_heightened_reinforcement_surface": "ribbed",
        "sls_heightened_effective_tensile_strength_mpa": 0.0,
        "sls_heightened_permitted_crack_width_mm": 0.0,
        "sls_heightened_fine_effective_tension_area_mm2": 0.0,
        "sls_heightened_coarse_effective_tension_area_mm2": 0.0,
    }
    assert {
        key: state.get(key, expected_defaults[key])
        for key in project_io.HEIGHTENED_CRACK_SCALAR_KEYS
    } == expected_defaults
    durable = state.get("_durable_input_scalars", {})
    assert {
        key: durable.get(key, expected_defaults[key])
        for key in project_io.HEIGHTENED_CRACK_SCALAR_KEYS
    } == expected_defaults


def test_calculate_runs_the_ui_configured_grouped_fatigue_spectrum():
    import fatigue_inputs
    import project_io
    import reinforcement_table as rt
    import sector_app
    from sector import design_standards

    at = _fresh()
    at.run()
    bars = at.session_state["bars_base"].copy(deep=True)
    bars[rt.FATIGUE_DETAIL_ID] = "F1"
    spectrum = fatigue_inputs.normalise_spectrum_table([{
        "spectrum": "Traffic",
        "name": "FAT-01",
        "description": "One constant-amplitude bin",
        "cycles": 2.0e6,
        "n_long_ed_kn": -100.0,
        "mx_long_ed_knm": 0.0,
        "my_long_ed_knm": 0.0,
        "n_short_ed_kn": 0.0,
        "mx_short_ed_knm": 20.0,
        "my_short_ed_knm": 0.0,
    }])
    tables = {
        key: at.session_state[key]
        for key in project_io.PROJECT_TABLE_KEYS
        if key in at.session_state
    }
    tables["bars_base"] = bars
    tables[fatigue_inputs.SPECTRUM_TABLE_KEY] = spectrum
    scalars = {
        key: at.session_state[key]
        for key in project_io.SCALAR_KEYS
        if key in at.session_state
    }
    scalars.update({
        "fatigue_on": True,
        "fatigue_edition": (
            design_standards.DesignBasisKey.FIRST_GEN_DK_NA_2024.value
        ),
        "fatigue_check_steel": True,
        "fatigue_check_concrete": False,
        "fatigue_gamma_s": 1.15,
        "fatigue_gamma_ff": 1.0,
        fatigue_inputs.DETAIL_CATALOG_KEY: fatigue_inputs.default_catalog(),
        fatigue_inputs.BASIS_KEY: fatigue_inputs.default_basis(),
    })
    at.session_state["_pending_project"] = project_io.dump_project(
        tables, scalars
    )
    at.run()
    assert not at.exception

    _calculate(at)

    assert not at.exception
    fatigue = at.session_state["results"]["fatigue"]
    assert fatigue["governing_spectrum"] == "Traffic"
    assert len(fatigue["spectra"]) == 1
    expected_basis = design_standards.get_design_basis(
        design_standards.DesignBasisKey.FIRST_GEN_DK_NA_2024
    )
    assert fatigue["basis_key"] == expected_basis.key.value
    assert fatigue["basis_label"] == expected_basis.label
    assert fatigue["basis_disclosure"] == expected_basis.disclosure
    assert set(fatigue["capability_bindings"]) == {"reinforcement"}
    assert at.session_state["result_fatigue_sig"] == (
        at.session_state["_latest_inputs"]["fatigue_sig"]
    )
    latest = at.session_state["_latest_inputs"]
    token = sector_app._FATIGUE_RESULT_CONTRACT_TOKEN
    assert tuple(latest["fatigue_sig"]).count(token) == 1
    for key in (
        "plastic_bending_context_sig",
        "plastic_case_context_sig",
        "plastic_sig",
        "elastic_case_context_sig",
        "elastic_sig",
    ):
        assert token not in tuple(latest[key])

    fatigue_before = fatigue
    unaffected_before = {
        key: at.session_state["results"][key]
        for key in ("plastic", "elastic")
        if key in at.session_state["results"]
    }
    pre_contract_fatigue_sig = tuple(
        item for item in latest["fatigue_sig"] if item != token
    )
    at.session_state["result_fatigue_sig"] = pre_contract_fatigue_sig
    at.session_state["result_sig"] = tuple(
        pre_contract_fatigue_sig if item == latest["fatigue_sig"] else item
        for item in latest["signature"]
    )

    _calculate(at)
    results = at.session_state["results"]
    fatigue = results["fatigue"]
    assert fatigue is not fatigue_before
    for key, value in unaffected_before.items():
        assert results[key] is value
    assert tuple(at.session_state["result_fatigue_sig"]).count(token) == 1
    assert at.session_state["result_sig"] == latest["signature"]

    assert len(at.table) == 1
    summary = at.table[0].value
    assert summary.loc[summary["Check"] == "Fatigue"].shape[0] == 1
    fatigue_summary = summary.loc[summary["Check"] == "Fatigue"].iloc[0]
    assert fatigue_summary["Governing action"] == "Traffic"

    _select_view(at, "Fatigue Results")
    assert not at.exception
    assert at.selectbox(key="_fatigue_result_spectrum").options == ["Traffic"]
    assert at.selectbox(key="_fatigue_result_element").options[0] == "R1"
    # Every value rendered in the utilisation-map hover must participate in its
    # memo key. A recalculation can change Miner damage while a different criterion
    # leaves the overall utilisation unchanged.
    map_id = id(
        at.session_state["_fig_cache"]["fatigue_utilisation_map"][1]
    )
    spectrum_result = fatigue["spectra"][0]
    steel_result = spectrum_result.reinforcement[0]
    changed_steel_result = dataclasses.replace(
        steel_result,
        damage=steel_result.damage + 0.01,
        damage_utilisation=steel_result.damage_utilisation + 0.01,
    )
    fatigue["spectra"] = (
        dataclasses.replace(
            spectrum_result,
            reinforcement=(
                changed_steel_result,
                *spectrum_result.reinforcement[1:],
            ),
        ),
    )
    at.run()
    assert id(
        at.session_state["_fig_cache"]["fatigue_utilisation_map"][1]
    ) != map_id

    detail = at.segmented_control(key="_fatigue_result_detail")
    assert detail.options == ["Reinforcement", "Spectrum bins", "Basis"]
    spectrum_summary = next(
        frame.value for frame in at.dataframe
        if {"Spectrum", "Governing", "Utilisation [%]"}.issubset(
            frame.value.columns
        )
    )
    assert spectrum_summary.iloc[0]["Spectrum"] == "Traffic"
    reinforcement = next(
        frame.value for frame in at.dataframe
        if {
            "Element", "Detail", "Simplified screen", "Screen limit [MPa]",
            "Miner D", "Status",
        }.issubset(
            frame.value.columns
        )
    )
    assert reinforcement.iloc[0]["Element"] == "R1"
    assert reinforcement.iloc[0]["Screen limit [MPa]"] == pytest.approx(70.0)
    assert reinforcement.iloc[0]["Simplified screen"] in {
        "PASS - DETAILED CHECK NOT REQUIRED",
        "DETAILED CHECK REQUIRED",
    }
    screen_table = next(
        frame.value for frame in at.dataframe
        if {
            "Status", "Detail class", "Range basis", "Limit [MPa]",
            "Governing bin", "Total cycles",
        }.issubset(frame.value.columns)
    )
    assert screen_table.iloc[0]["Range basis"] == "Characteristic"
    assert screen_table.iloc[0]["Limit [MPa]"] == pytest.approx(70.0)

    unsupported_source = (
        "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010, 6.8.6(1)-(2), "
        "with DS/EN 1992-1-1 DK NA:2024, 6.8.6(1) unchanged"
    )
    unsupported_reason = (
        "DS/EN 1992-1-1 6.8.6 shortcut covers unwelded or welded "
        "reinforcing bars in tension"
    )
    assert changed_steel_result.simplified_screen is not None
    unsupported_screen = dataclasses.replace(
        changed_steel_result.simplified_screen,
        status="NOT APPLICABLE",
        applicable=False,
        passed=None,
        detail_class="unsupported first-generation detail",
        range_basis="",
        threshold_mpa=None,
        governing_range_mpa=None,
        utilisation=None,
        governing_bin=None,
        source=unsupported_source,
        reason=unsupported_reason,
    )
    unsupported_steel_result = dataclasses.replace(
        changed_steel_result,
        simplified_screen=unsupported_screen,
        governing_criterion="Miner damage",
        governing_bin=changed_steel_result.governing_damage_bin,
        utilisation=changed_steel_result.damage,
    )
    fatigue["spectra"] = (
        dataclasses.replace(
            fatigue["spectra"][0],
            reinforcement=(
                unsupported_steel_result,
                *fatigue["spectra"][0].reinforcement[1:],
            ),
        ),
    )
    at.run()
    unsupported_summary = next(
        frame.value for frame in at.dataframe
        if {
            "Element", "Detail", "Simplified screen", "Screen limit [MPa]",
            "Miner D", "Status",
        }.issubset(frame.value.columns)
    )
    assert unsupported_summary.iloc[0]["Simplified screen"] == "NOT APPLICABLE"
    unsupported_table = next(
        frame.value for frame in at.dataframe
        if {
            "Status", "Detail class", "Range basis", "Limit [MPa]",
            "Governing bin", "Total cycles",
        }.issubset(frame.value.columns)
    )
    assert unsupported_table.iloc[0]["Status"] == "NOT APPLICABLE"
    assert unsupported_table.iloc[0]["Detail class"] == (
        "unsupported first-generation detail"
    )
    captions = "\n".join(str(item.value) for item in at.caption)
    assert unsupported_reason in captions
    assert "Reference: " + unsupported_source in captions

    detail = at.segmented_control(key="_fatigue_result_detail")
    detail.set_value("Spectrum bins").run()
    assert not at.exception
    action_table = next(
        frame.value for frame in at.dataframe
        if {"Bin", "Nlong,Ed [kN]", "Mx,short,Ed [kNm]"}.issubset(
            frame.value.columns
        )
    )
    assert action_table.iloc[0]["Bin"] == "FAT-01"
    solver_table = next(
        frame.value for frame in at.dataframe
        if {"Bin", "gamma_Ff", "Bond method", "Status"}.issubset(
            frame.value.columns
        )
    )
    assert solver_table.iloc[0]["Status"] == "OK"

    at.segmented_control(key="_fatigue_result_detail").set_value("Basis").run()
    assert not at.exception
    basis_table = next(
        frame.value for frame in at.dataframe
        if list(frame.value.columns) == ["Item", "Value"]
    )
    basis_items = set(basis_table["Item"])
    assert {
        "Design basis",
        "Method scope",
        "gamma_Ff",
    }.issubset(basis_items)
    basis_values = dict(zip(basis_table["Item"], basis_table["Value"]))
    assert basis_values["Design basis"] == expected_basis.label
    assert basis_values["Method scope"] == expected_basis.disclosure
    assert basis_table["Value"].map(type).eq(str).all()
    capability_table = next(
        frame.value
        for frame in at.dataframe
        if {
            "Check",
            "Method",
            "Reference",
            "Scope",
        }.issubset(frame.value.columns)
    )
    assert capability_table.iloc[0]["Method"] == "Reinforcement fatigue"
    assert "first-generation fatigue equations" in capability_table.iloc[0]["Scope"]
    assert "user-supplied factors" in capability_table.iloc[0]["Scope"]

    # Stale results must retain the actions and geometry that produced them. If the
    # live spectrum is edited before recalculation, the result drill-down must not
    # combine those new inputs with the previous engine payload.
    _goto_page(at, "Inputs")
    changed_spectrum = spectrum.copy(deep=True)
    changed_spectrum.loc[0, "n_long_ed_kn"] = -999.0
    at.session_state[fatigue_inputs.SPECTRUM_TABLE_KEY] = changed_spectrum
    for state_key in (
        "fatigue_spectrum_editor",
        f"_{fatigue_inputs.SPECTRUM_TABLE_KEY}_editor_seed",
    ):
        try:
            del at.session_state[state_key]
        except KeyError:
            pass
    at.run()
    _select_view(at, "Fatigue Results")
    at.segmented_control(key="_fatigue_result_detail").set_value(
        "Spectrum bins"
    ).run()
    stale_actions = next(
        frame.value for frame in at.dataframe
        if {"Bin", "Nlong,Ed [kN]", "Mx,short,Ed [kNm]"}.issubset(
            frame.value.columns
        )
    )
    assert stale_actions.iloc[0]["Nlong,Ed [kN]"] == pytest.approx(-100.0)
    assert any("inputs changed" in warning.value.lower() for warning in at.warning)

    # A session can survive a code hot reload from a build that did not yet store
    # snapshots. In that legacy state, suppress input-dependent stale evidence
    # instead of falling back to the newly edited actions or geometry.
    del at.session_state["result_input_snapshot"]
    at.run()
    assert any(
        "cannot be matched to its inputs" in error.value
        for error in at.error
    )
    assert not any(
        {"Bin", "Nlong,Ed [kN]", "Mx,short,Ed [kNm]"}.issubset(
            frame.value.columns
        )
        for frame in at.dataframe
    )

    _goto_page(at, "Inputs")
    calculated_fatigue_sig = at.session_state["result_fatigue_sig"]
    current_fck = float(at.session_state["conc_fck"])
    changed_fck = current_fck + 5.0 if current_fck <= 195.0 else current_fck - 5.0
    _goto_material_tab(at, "Concrete")
    at.number_input(key="conc_fck").set_value(changed_fck).run()
    fck_fatigue_sig = at.session_state["_latest_inputs"]["fatigue_sig"]
    assert fck_fatigue_sig != calculated_fatigue_sig
    current_alpha_cc = float(at.session_state["conc_alpha_cc"])
    changed_alpha_cc = 0.85 if current_alpha_cc != 0.85 else 0.90
    at.number_input(key="conc_alpha_cc").set_value(changed_alpha_cc).run()
    assert at.session_state["_latest_inputs"]["fatigue_sig"] != fck_fatigue_sig

    _goto_input_tab(at, "Analysis settings")
    at.number_input(key="fatigue_gamma_s").set_value(1.20).run()
    assert at.session_state["result_sig"] != (
        at.session_state["_latest_inputs"]["signature"]
    )


def test_fatigue_map_signature_distinguishes_bars_from_tendons():
    import sector_app

    record = {"id": "R1", "x_mm": 0.0, "y_mm": -220.0}
    common = {
        "outer": [(-0.2, -0.3), (0.2, -0.3), (0.2, 0.3), (-0.2, 0.3)],
        "holes": [],
    }
    spectrum = {
        "spectrum_name": "Traffic",
        "reinforcement": [],
        "concrete": [],
        "concrete_search": None,
    }
    bar_input = {
        **common,
        "bar_elements": [record],
        "tendon_elements": [],
    }
    tendon_input = {
        **common,
        "bar_elements": [],
        "tendon_elements": [record],
    }

    assert sector_app._fatigue_map_signature(
        bar_input, spectrum
    ) != sector_app._fatigue_map_signature(tendon_input, spectrum)


def test_fatigue_validation_stays_in_the_ui_instead_of_raising():
    at = _fresh()
    at.run()
    at.toggle(key="fatigue_on").set_value(True).run()
    before = at.session_state["bars_base"].copy(deep=True)

    _calculate(at)

    assert not at.exception
    assert "results" in at.session_state
    assert at.session_state["results"].get("plastic_cases")
    fatigue = at.session_state["results"]["fatigue"]
    assert fatigue["valid"] is False
    assert fatigue["converged"] is False
    assert fatigue["spectra"] == ()
    assert not at.session_state["bars_base"].compare(before).size
    errors = " ".join(item.value for item in at.error)
    assert "At least one fatigue spectrum bin is required" in errors
    assert "fatigue detail ID is required" in errors


def test_catalogue_revisions_preserve_every_live_reinforcement_cell():
    import reinforcement_table as rebar_table

    at = _fresh()
    at.run()
    version = at.session_state["ed_bars_ver"]
    row = {
        rebar_table.ELEMENT_ID: "R1",
        rebar_table.X: 37.5,
        rebar_table.Y: -212.0,
        rebar_table.SIZE_MODE: rebar_table.DIAMETER_MODE,
        rebar_table.AREA: 490.873852123,
        rebar_table.DIAMETER: 25.0,
        rebar_table.MATERIAL_ID: "M1",
        rebar_table.FATIGUE_DETAIL_ID: "",
    }
    at.session_state["ed_bars"] = {
        "payload": {
            "data_version": str(version),
            "rows": [row],
        }
    }
    at.session_state["_material_catalog_revision"] += 1
    at.session_state["_fatigue_catalog_revision"] += 1

    at.run()

    assert not at.exception
    actual = at.session_state["bars_base"].iloc[0].to_dict()
    for key, value in row.items():
        if isinstance(value, float):
            assert actual[key] == pytest.approx(value)
        else:
            assert actual[key] == value


def test_startup_catalogue_repair_reserves_incomplete_row_assignments():
    import fatigue_inputs
    import material_catalog
    import reinforcement_table as rebar_table

    at = _fresh()
    at.session_state["pts_init"] = True
    at.session_state["bars_base"] = rebar_table.normalise_table(
        [{
            rebar_table.X: 0.0,
            rebar_table.Y: 0.0,
            rebar_table.SIZE_MODE: rebar_table.AREA_MODE,
            rebar_table.AREA: None,
            rebar_table.MATERIAL_ID: "M2",
            rebar_table.FATIGUE_DETAIL_ID: "F2",
        }],
        "bar",
    )
    at.session_state[material_catalog.MILD_CATALOG_KEY] = {
        "items": [
            {**material_catalog.default_entry("mild"), "id": "bad"}
        ]
    }
    at.session_state[fatigue_inputs.DETAIL_CATALOG_KEY] = {
        "items": [
            {**fatigue_inputs.default_entry(), "id": "bad"}
        ]
    }
    at.session_state["shear_on"] = True
    at.session_state["capacity_steel_material_id"] = "M3"

    at.run()

    assert not at.exception
    assert material_catalog.material_ids(
        at.session_state[material_catalog.MILD_CATALOG_KEY], "mild"
    ) == ["M1"]
    assert fatigue_inputs.detail_ids(
        at.session_state[fatigue_inputs.DETAIL_CATALOG_KEY]
    ) == ["F1"]
    assert at.session_state["bars_base"].loc[0, rebar_table.MATERIAL_ID] == "M2"
    assert (
        at.session_state["bars_base"].loc[0, rebar_table.FATIGUE_DETAIL_ID]
        == "F2"
    )
    assert at.session_state["capacity_steel_material_id"] == "M3"
    assert at.session_state[
        "_capacity_steel_unresolved_material_id"
    ] == "M3"
    assert at.selectbox(key="capacity_steel_material_id").value == "M3"
    assert "member-check material M3" in at.session_state[
        "_latest_inputs"
    ]["material_error"]


def test_bulk_reinforcement_assignment_updates_all_and_selected_rows():
    from pandas.testing import assert_frame_equal

    import reinforcement_table as rebar_table

    at = _fresh()
    at.run()
    before = at.session_state["bars_base"].copy(deep=True)
    element_ids = before[rebar_table.ELEMENT_ID].tolist()
    geometry_columns = [
        rebar_table.ELEMENT_ID,
        rebar_table.X,
        rebar_table.Y,
        rebar_table.SIZE_MODE,
        rebar_table.AREA,
        rebar_table.DIAMETER,
    ]
    assert len(element_ids) > 1
    assert list(before.columns) == rebar_table.COLUMNS

    _goto_input_tab(at, "Section")
    at.selectbox(key="_ed_bars_bulk_fatigue").set_value("F1").run()
    assert at.button(key="_ed_bars_bulk_apply").disabled is False
    at.button(key="_ed_bars_bulk_apply").click().run()

    assigned = at.session_state["bars_base"].copy(deep=True)
    assert assigned[rebar_table.FATIGUE_DETAIL_ID].tolist() == (
        ["F1"] * len(element_ids)
    )
    assert_frame_equal(
        assigned[geometry_columns],
        before[geometry_columns],
        check_dtype=True,
    )

    at.segmented_control(key="_ed_bars_bulk_scope").set_value(
        "Selected elements"
    ).run()
    at.multiselect(key="_ed_bars_bulk_ids").set_value([element_ids[0]])
    at.selectbox(key="_ed_bars_bulk_fatigue").set_value(
        "__sector_clear__"
    )
    at.run()
    assert at.button(key="_ed_bars_bulk_apply").disabled is False
    at.button(key="_ed_bars_bulk_apply").click().run()

    selected = at.session_state["bars_base"]
    assert selected.iloc[0][rebar_table.FATIGUE_DETAIL_ID] == ""
    assert selected.iloc[1:][rebar_table.FATIGUE_DETAIL_ID].tolist() == (
        ["F1"] * (len(element_ids) - 1)
    )
    assert_frame_equal(
        selected[geometry_columns],
        before[geometry_columns],
        check_dtype=True,
    )
    assert not at.exception


def test_fatigue_basis_records_direct_method_and_action_notes():
    import fatigue_inputs

    at = _fresh()
    at.run()
    at.toggle(key="fatigue_on").set_value(True).run()
    prefix = (
        f"fatiguebasis_r{at.session_state['_fatigue_basis_revision']}"
    )
    at.text_area(key=f"{prefix}_notes").set_value(
        "Traffic model register; cycle counts supplied by the engineer"
    ).run()

    basis = at.session_state[fatigue_inputs.BASIS_KEY]
    assert basis == {
        "method": fatigue_inputs.METHOD_GROUPED,
        "notes": "Traffic model register; cycle counts supplied by the engineer",
    }
    assert not any(
        "authority" in str(widget.key).lower()
        for widgets in (at.selectbox, at.text_input, at.text_area)
        for widget in widgets
    )


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
    assert bool(elastic.loc[0, "calculate_crack_width"]) is True

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
            "calculate_crack_width": False,
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


def test_autosave_preferences_fall_back_to_durable_hidden_widget_values():
    import sector_app

    state = {
        sector_app._INPUT_STATE_KEY: {
            "autosave_on": False,
            "autosave_min": 120,
        },
    }
    assert sector_app._autosave_preferences(state) == (False, 120)

    # A currently mounted widget is newer and therefore takes precedence.
    state["autosave_on"] = True
    state["autosave_min"] = 15
    assert sector_app._autosave_preferences(state) == (True, 15)


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


def test_alias_only_change_refreshes_the_autosave(tmp_path, monkeypatch):
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path))
    at = _fresh()
    at.run()
    at.session_state["_autosave_t"] = 0.0
    at.run()
    saved = tmp_path / "autosave.json"
    before = saved.read_text(encoding="utf-8")

    at.text_input(key="modelled_direction_alias").set_value(
        "span direction"
    ).run()
    at.session_state["_autosave_t"] = 0.0
    at.run()

    after = saved.read_text(encoding="utf-8")
    assert after != before
    import project_io
    _, scalars = project_io.parse_project(after)
    assert scalars["modelled_direction_alias"] == "span direction"
    assert not at.exception


def test_due_autosave_runs_from_analysis_page(tmp_path, monkeypatch):
    # A genuine Analysis-fragment interaction must service a due autosave even
    # though input widgets and the top-level dispatcher are not rerun (second
    # independent Codex review P2).
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path))
    at = _fresh()
    at.run()
    _goto_material_tab(at, "Concrete")
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


def test_analysis_fragment_honours_hidden_disabled_autosave(tmp_path, monkeypatch):
    """Widget cleanup must not re-enable autosave on a fragment-only rerun."""
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path))
    at = _fresh()
    at.run()
    _goto_input_tab(at, "Project")
    at.checkbox(key="autosave_on").set_value(False).run()
    assert at.session_state["_durable_input_scalars"]["autosave_on"] is False
    _goto_page(at, "Analysis")

    # Reproduce Streamlit's cleanup of a widget that is no longer rendered.
    if "autosave_on" in at.session_state:
        del at.session_state["autosave_on"]
    at.session_state["_autosave_t"] = 0.0
    at.selectbox(key="view").set_value("Plastic Results").run()

    assert not at.exception
    assert not (tmp_path / "autosave.json").exists()


def test_analysis_fragment_honours_hidden_autosave_interval(tmp_path, monkeypatch):
    """A hidden custom interval must not fall back to the five-minute default."""
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path))
    at = _fresh()
    at.run()
    _goto_input_tab(at, "Project")
    at.number_input(key="autosave_min").set_value(120).run()
    assert at.session_state["_durable_input_scalars"]["autosave_min"] == 120
    _goto_page(at, "Analysis")

    if "autosave_min" in at.session_state:
        del at.session_state["autosave_min"]
    at.session_state["_autosave_t"] = time.time() - 6 * 60
    at.selectbox(key="view").set_value("Plastic Results").run()

    assert not at.exception
    assert not (tmp_path / "autosave.json").exists()


def test_autosave_restores_last_session_on_next_launch(tmp_path, monkeypatch):
    # The BriCoS principle: a pre-existing autosave is loaded automatically on the
    # next launch, so the section resumes where the user left off.
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path))
    at = _fresh()
    at.run()
    _goto_material_tab(at, "Concrete")
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
    _set_and_click(at, "qs_apply")                       # reseed + close builder + rerun
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
    _goto_input_tab(at, "Project")
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


def test_generate_report_produces_pdf():
    # The Report workspace builds a PDF from the current section
    # (figures skipped in the test so it does not need a browser).
    at = _fresh()
    at.run()
    _goto_page(at, "Report")
    at.session_state["_report_no_figures"] = True
    profile = at.segmented_control(key="rep_report_content")
    assert profile.value == "Standard"
    assert profile.options == ["Brief", "Standard", "Audit"]
    _set(
        at,
        ("text_input", "rep_proj_no", "T-1"),
        ("text_input", "rep_section", "S/1"),
        ("text_input", "rep_rev", "A:2"),
    )
    at.button(key="gen_report").click().run()
    assert not at.exception
    assert "report_buffer" in at.session_state
    assert at.session_state["report_buffer"][:4] == b"%PDF"
    assert "report_signature" in at.session_state
    assert at.session_state["report_filename"].startswith(
        "Sector_T-1_S-1_Rev-A-2_"
    )
    assert at.session_state["report_filename"].endswith(".pdf")
    assert at.session_state["report_generation_record"]["result_source"] == (
        "recalculated-for-report"
    )


def test_report_failure_does_not_publish_software_diagnostics(monkeypatch):
    import sector_report

    def fail_report(*_args, **_kwargs):
        raise RuntimeError("SHA payload contract internal_key solver state")

    monkeypatch.setattr(sector_report, "build_report", fail_report)
    at = _fresh()
    at.run()
    _goto_page(at, "Report")
    at.session_state["_report_no_figures"] = True
    at.button(key="gen_report").click().run()

    assert not at.exception
    assert "report_buffer" not in at.session_state
    visible = " ".join(str(item.value) for item in at.error)
    assert "Report generation failed" in visible
    assert not re.search(
        r"\b(?:sha|payload|contract|solver|internal_key)\b",
        visible,
        flags=re.IGNORECASE,
    )


def test_fatigue_failure_boundary_hides_software_diagnostics(monkeypatch):
    import fatigue_analysis
    import sector_app

    hostile = "SHA payload contract internal_key solver state"
    monkeypatch.setattr(
        fatigue_analysis,
        "validation_errors",
        lambda _inp: [hostile],
    )
    monkeypatch.setattr(
        fatigue_analysis,
        "invalid_result",
        lambda _inp, errors: {"errors": tuple(errors)},
    )

    result = sector_app._run_fatigue_or_invalid({})

    assert result["errors"] == ("Review the fatigue inputs and recalculate",)


def test_fatigue_failure_boundary_keeps_distinct_engineering_notation(monkeypatch):
    import fatigue_analysis
    import sector_app

    engineering_errors = [
        "gamma_Ff must be a finite number greater than zero",
        "gamma_s must be a finite number greater than zero",
        "beta_cc(t0) must be a finite number greater than zero",
        "Concrete alpha_cc must be a finite number",
    ]
    monkeypatch.setattr(
        fatigue_analysis,
        "validation_errors",
        lambda _inp: engineering_errors,
    )
    monkeypatch.setattr(
        fatigue_analysis,
        "invalid_result",
        lambda _inp, errors: {"errors": tuple(errors)},
    )

    result = sector_app._run_fatigue_or_invalid({})

    assert result["errors"] == tuple(engineering_errors)


def test_calculation_failure_boundary_hides_software_diagnostics():
    import sector_app

    visible = sector_app._calculation_failure_message(
        ValueError("SHA payload contract internal_key solver state")
    )

    assert visible == (
        "Calculation blocked: Sector could not complete the calculation. "
        "Review the inputs and try again."
    )
    assert not re.search(
        r"\b(?:sha|payload|contract|solver|internal_key)\b",
        visible,
        flags=re.IGNORECASE,
    )


def test_metadata_only_report_edit_reuses_frozen_engineering_results(
    monkeypatch,
):
    import sector_report

    captured = {}

    def capture_report(meta, inp, out, **_kwargs):
        captured["meta"] = copy.deepcopy(meta)
        captured["inp"] = copy.deepcopy(inp)
        captured["out"] = copy.deepcopy(out)
        return b"%PDF-metadata-capture"

    monkeypatch.setattr(sector_report, "build_report", capture_report)
    at = _fresh()
    at.run()
    _calculate(at)
    calculation = copy.deepcopy(at.session_state["calculation_record"])
    engineering_hash = calculation["engineering_input_sha256"]

    _goto_page(at, "Report")
    at.text_input(key="rep_proj_name").set_value("Updated document title").run()
    at.text_input(key="rep_rev").set_value("B").run()
    at.button(key="gen_report").click().run()

    assert not at.exception
    assert at.session_state["calculation_record"] == calculation
    record = at.session_state["report_generation_record"]
    assert record["result_source"] == "reused-current-analysis-results"
    assert record["engineering_input_sha256"] == engineering_hash
    assert captured["meta"]["proj_name"] == "Updated document title"
    assert captured["meta"]["rev"] == "B"
    assert captured["meta"]["engineering_input_sha256"] == engineering_hash
    assert captured["meta"]["project_state_sha256"] == record[
        "project_state_sha256"
    ]


def test_report_download_becomes_stale_after_metadata_change():
    at = _fresh()
    at.run()
    _goto_page(at, "Report")
    at.session_state["_report_no_figures"] = True
    _set(
        at,
        ("text_input", "rep_proj_no", "T-1"),
        ("text_input", "rep_section", "S/1"),
        ("text_input", "rep_rev", "A:2"),
    )
    at.button(key="gen_report").click().run()
    assert not any("Report out of date" in w.value for w in at.warning)

    at.text_input(key="rep_rev").set_value("B").run()
    assert any("Report out of date" in w.value for w in at.warning)


def test_report_download_becomes_stale_after_content_choice_change():
    at = _fresh()
    at.run()
    _goto_page(at, "Report")
    at.session_state["_report_no_figures"] = True
    at.button(key="gen_report").click().run()
    assert not any("Report out of date" in w.value for w in at.warning)

    at.segmented_control(key="rep_report_content").set_value("Audit").run()
    assert any("Report out of date" in w.value for w in at.warning)


def test_report_signature_seals_product_version_and_source_revision():
    import sector_app

    kwargs = {
        "input_signature": ("same-input",),
        "meta": {"modelled_direction_alias": ""},
        "report_content": "Standard",
    }
    issued = sector_app._report_signature(
        **kwargs,
        product_version="0.92",
        revision="a" * 40,
    )
    version_changed = sector_app._report_signature(
        **kwargs,
        product_version="0.93",
        revision="a" * 40,
    )
    revision_changed = sector_app._report_signature(
        **kwargs,
        product_version="0.92",
        revision="b" * 40,
    )

    assert issued[:2] == version_changed[:2] == revision_changed[:2]
    assert issued[2] == ("0.92", "a" * 40)
    assert issued != version_changed
    assert issued != revision_changed


def test_hot_reload_migrates_exact_legacy_report_profile_state():
    at = _fresh()
    legacy = "Default report + QA appendix"
    at.session_state["rep_report_content"] = legacy
    at.session_state["_durable_input_scalars"] = {
        "rep_report_content": legacy,
    }
    at.session_state["_pending_input_events"] = {
        "rep_report_content": legacy,
    }
    at.session_state["_main_page"] = "Report"

    at.run()

    assert not at.exception
    assert at.segmented_control(key="rep_report_content").value == "Audit"
    assert at.session_state["rep_report_content"] == "Audit"
    assert "rep_report_content" not in at.session_state["_durable_input_scalars"]
    assert at.session_state["_durable_report_scalars"][
        "rep_report_content"
    ] == "Audit"
    assert "_pending_input_events" not in at.session_state
    assert "_pending_report_events" not in at.session_state


def test_hot_reload_surfaces_unknown_report_profile_and_clears_old_report():
    at = _fresh()
    at.run()
    _goto_page(at, "Report")
    at.session_state["rep_report_content"] = "Unexpected report"
    at.session_state["_durable_input_scalars"]["rep_report_content"] = (
        "Unexpected report"
    )
    at.session_state["_durable_report_scalars"]["rep_report_content"] = (
        "Unexpected report"
    )
    at.session_state["_pending_report_events"] = {
        "rep_report_content": "Unexpected report",
    }
    at.session_state["report_buffer"] = b"old report"
    at.session_state["report_signature"] = ("old",)
    at.session_state["report_generation_record"] = {"old": True}

    at.run()

    assert not at.exception
    assert at.segmented_control(key="rep_report_content").value == "Standard"
    assert "report_buffer" not in at.session_state
    assert "report_signature" not in at.session_state
    assert "report_generation_record" not in at.session_state
    assert "rep_report_content" not in at.session_state["_durable_input_scalars"]
    assert at.session_state["_durable_report_scalars"][
        "rep_report_content"
    ] == "Standard"
    assert "_pending_report_events" not in at.session_state
    assert any(
        "not recognised" in item.value and "reset to Standard" in item.value
        for item in at.warning
    )


def test_report_fragment_normalises_hostile_profile_before_strict_mount(
    monkeypatch,
):
    import sector_app

    class FakeBox:
        def __init__(self, state):
            self.state = state
            self.warnings = []

        def markdown(self, *_args, **_kwargs):
            return None

        def caption(self, *_args, **_kwargs):
            return None

        def warning(self, message, **_kwargs):
            self.warnings.append(message)

        def text_input(self, _label, *, key, **_kwargs):
            return self.state[key]

        def text_area(self, _label, *, key, **_kwargs):
            return self.state[key]

        def segmented_control(self, _label, _options, *, key, **_kwargs):
            return self.state[key]

        def columns(self, count):
            return tuple(self for _ in range(count))

        def button(self, *_args, **_kwargs):
            return False

        def info(self, *_args, **_kwargs):
            return None

        def empty(self):
            return self

    class FakeStreamlit:
        def __init__(self):
            self.session_state = {
                "rep_report_content": "Hostile stale value",
                "_durable_report_scalars": {
                    "rep_report_content": "Hostile stale value",
                },
                "report_buffer": b"%PDF-old",
                "report_signature": ("old",),
            }
            self.box = FakeBox(self.session_state)

        def subheader(self, *_args, **_kwargs):
            return None

        def caption(self, *_args, **_kwargs):
            return None

        def container(self, **_kwargs):
            return self.box

    fake = FakeStreamlit()
    monkeypatch.setattr(sector_app, "st", fake)
    monkeypatch.setattr(sector_app, "_measured_autosave", lambda: None)

    sector_app._report_workspace.__wrapped__({"signature": ("frozen",)})

    assert fake.session_state["rep_report_content"] == "Standard"
    assert fake.session_state["_durable_report_scalars"][
        "rep_report_content"
    ] == "Standard"
    assert "report_buffer" not in fake.session_state
    assert "report_signature" not in fake.session_state
    assert any("reset to Standard" in warning for warning in fake.box.warnings)


def test_autosave_detects_report_profile_only_change(tmp_path, monkeypatch):
    import project_io

    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path))
    at = _fresh()
    at.run()
    _goto_page(at, "Report")
    at.text_input(key="rep_proj_name").set_value("Durable project").run()
    at.segmented_control(key="rep_report_content").set_value("Audit").run()
    at.session_state["_autosave_t"] = 0.0
    at.run()

    saved = tmp_path / "autosave.json"
    assert saved.exists()
    _, scalars = project_io.parse_project(saved.read_text(encoding="utf-8"))
    assert scalars["rep_proj_name"] == "Durable project"
    assert scalars[project_io.REPORT_PROFILE_KEY] == "Audit"


def test_analysis_autosave_waits_for_interrupted_scalar_and_table_edit(
    tmp_path,
    monkeypatch,
):
    import project_io

    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path))
    at = _fresh()
    at.run()
    at.session_state["_autosave_t"] = 0.0
    at.session_state["_inputs_build_in_progress"] = True
    at.session_state["_pending_input_events"] = {
        "conc_fck": 60.0,
        "plastic_cases_editor": {"edited_rows": {0: {"Mx_kNm": 125.0}}},
    }
    at.session_state["conc_fck"] = 60.0

    at.segmented_control(key="_main_page").set_value("Analysis").run()

    saved = tmp_path / "autosave.json"
    assert not at.exception
    assert at.session_state["_inputs_build_in_progress"] is True
    assert set(at.session_state["_pending_input_events"]) == {
        "conc_fck",
        "plastic_cases_editor",
    }
    assert not saved.exists()

    _goto_page(at, "Inputs")

    assert not at.exception
    assert at.session_state["_inputs_build_in_progress"] is False
    assert "_pending_input_events" not in at.session_state
    assert saved.exists()
    _, scalars = project_io.parse_project(saved.read_text(encoding="utf-8"))
    assert scalars["conc_fck"] == pytest.approx(60.0)


def test_report_download_becomes_stale_after_analysis_input_change():
    at = _fresh()
    at.run()
    _goto_page(at, "Report")
    at.session_state["_report_no_figures"] = True
    at.button(key="gen_report").click().run()
    assert not any("Report out of date" in w.value for w in at.warning)

    _set(at, ("number_input", "pl_Mx", 123.0))
    _goto_page(at, "Report")
    assert any("Report out of date" in w.value for w in at.warning)


def test_interrupted_input_edit_blocks_report_until_payload_is_committed():
    at = _fresh()
    at.run()
    _calculate(at)
    old_result_signature = at.session_state["result_sig"]
    old_input_hash = at.session_state["calculation_record"][
        "engineering_input_sha256"
    ]
    _goto_page(at, "Report")
    at.session_state["_report_no_figures"] = True
    at.button(key="gen_report").click().run()
    old_report = at.session_state["report_buffer"]
    assert at.session_state["report_generation_record"]["result_source"] == (
        "reused-current-analysis-results"
    )

    _goto_page(at, "Inputs")
    at.session_state["_inputs_build_in_progress"] = True
    at.session_state["_pending_input_events"] = {"conc_fck": 60.0}
    at.session_state["conc_fck"] = 30.0
    at.segmented_control(key="_main_page").set_value("Report").run()

    assert not at.exception
    assert at.session_state["_inputs_build_in_progress"] is True
    assert at.session_state["_latest_inputs"]["signature"] == old_result_signature
    assert at.button(key="gen_report").disabled is True
    assert at.session_state["report_buffer"] == old_report
    assert any(
        "Input preparation was interrupted" in warning.value
        for warning in at.warning
    )
    assert not any(
        getattr(item, "label", "") == "Download report (PDF)"
        for item in at.get("download_button")
    )

    _goto_page(at, "Inputs")
    assert at.session_state["_inputs_build_in_progress"] is False
    assert "_pending_input_events" not in at.session_state
    assert at.session_state["_latest_inputs"]["concrete"].fck == pytest.approx(
        60.0
    )

    _goto_page(at, "Report")
    assert at.button(key="gen_report").disabled is False
    at.button(key="gen_report").click().run()

    assert not at.exception
    assert at.session_state["report_generation_record"]["result_source"] == (
        "recalculated-for-report"
    )
    assert at.session_state["report_generation_record"]["input_sha256"] != (
        old_input_hash
    )


def test_direction_alias_is_visible_before_checks_and_follows_the_cut():
    from sector import detailing

    at = _fresh()
    at.run()
    assert at.text_input(key="modelled_direction_alias").value == ""
    assert any(
        item.value == "Modelled reinforcement direction: Longitudinal"
        for item in at.info
    )

    at.text_input(key="modelled_direction_alias").set_value(
        "span direction"
    ).run()
    at.selectbox(key="detailing_member_type").set_value("Slab").run()
    at.selectbox(key="detailing_cut_direction").set_value(
        detailing.CUT_LONGITUDINAL
    ).run()
    expected = (
        "Modelled reinforcement direction: Transverse "
        "(project alias: span direction)"
    )
    assert any(item.value == expected for item in at.info)

    _goto_input_tab(at, "Loads")
    assert any(item.value == expected for item in at.info)
    assert not at.exception


def test_pending_project_rejects_overlong_alias_before_widget_mount():
    import modelled_direction
    import project_io

    payload = json.loads(project_io.dump_project({}, {}))
    too_long = "x" * (modelled_direction.MAX_ALIAS_CHARS + 1)
    payload["presentation"][modelled_direction.ALIAS_KEY] = too_long

    at = _fresh()
    at.session_state["_pending_project"] = json.dumps(payload)
    at.run()

    assert not at.exception
    assert at.session_state["_project_msg"] == (
        "error",
        "Could not load project: modelled direction alias must be at most "
        "60 characters.",
    )
    assert at.text_input(key=modelled_direction.ALIAS_KEY).value == ""
    assert at.session_state[modelled_direction.ALIAS_KEY] == ""


def test_direction_alias_changes_only_the_report_document_signature():
    import sector_app

    input_signature = ("unchanged-calculation",)
    without_alias = sector_app._report_signature(
        input_signature,
        meta={"modelled_direction_alias": ""},
        report_content="Standard",
    )
    with_alias = sector_app._report_signature(
        input_signature,
        meta={"modelled_direction_alias": "span direction"},
        report_content="Standard",
    )

    assert without_alias[0] == with_alias[0] == repr(input_signature)
    assert without_alias[1] != with_alias[1]


def test_engineering_input_hash_uses_only_the_frozen_result_signature():
    import sector_app

    base = {
        "signature": ("plastic", 1.0),
        "mode": "Plastic",
        "modelled_direction_alias": "span",
    }
    renamed = {**base, "modelled_direction_alias": "deck north"}
    metadata = {**base, "rep_proj_name": "New title", "rep_report_content": "Audit"}
    changed = {**base, "signature": ("plastic", 2.0)}

    assert sector_app._engineering_input_hash(base) == (
        sector_app._engineering_input_hash(renamed)
    )
    assert sector_app._engineering_input_hash(base) == (
        sector_app._engineering_input_hash(metadata)
    )
    assert sector_app._engineering_input_hash(base) != (
        sector_app._engineering_input_hash(changed)
    )


def test_report_reuse_requires_one_current_coherent_calculation_tuple():
    import project_io
    import sector_app

    inp = {"signature": ("engineering", 1.0)}
    results = {"plastic": {"mx": [1.0], "my": [2.0]}}
    engineering_hash = sector_app._engineering_input_hash(inp)
    record = {
        "performed_at_utc": "2026-08-13T12:00:00+00:00",
        "sector_version": "0.93-test",
        "source_revision": "current-revision",
        "engineering_input_sha256": engineering_hash,
        "result_sha256": project_io.result_sha256(results),
    }
    state = {
        "results": results,
        "result_sig": inp["signature"],
        "result_input_snapshot": copy.deepcopy(inp),
        "calculation_record": record,
    }

    retained = sector_app._retained_analysis_for_report(
        inp,
        state=state,
        product_version="0.93-test",
        revision="current-revision",
    )
    assert retained is not None
    assert retained[0] == results and retained[0] is not results

    legacy_record = {
        key: value
        for key, value in record.items()
        if key != "engineering_input_sha256"
    }
    mutations = (
        ("calculation_record", None),
        ("calculation_record", legacy_record),
        ("calculation_record", {**record, "sector_version": "0.92"}),
        (
            "calculation_record",
            {**record, "source_revision": "older-revision"},
        ),
        (
            "calculation_record",
            {**record, "engineering_input_sha256": "0" * 64},
        ),
        (
            "calculation_record",
            {**record, "result_sha256": "0" * 64},
        ),
        ("result_sig", ("engineering", 2.0)),
        ("result_input_snapshot", None),
    )
    for key, value in mutations:
        incoherent = copy.deepcopy(state)
        incoherent[key] = value
        assert sector_app._retained_analysis_for_report(
            inp,
            state=incoherent,
            product_version="0.93-test",
            revision="current-revision",
        ) is None

    assert sector_app._retained_analysis_for_report(
        {"signature": ("engineering", 2.0)},
        state=state,
        product_version="0.93-test",
        revision="current-revision",
    ) is None


def test_capacity_only_toggle_drops_utilisation_without_locking_case_table():
    # With utilisation checking off, the result is capacity-only. The case table
    # stays editable because its actions may still feed other requested checks.
    at = _fresh()
    at.run()
    at.checkbox(key="pl_check_util").set_value(False).run()
    _goto_input_tab(at, "Loads")
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
    _goto_input_tab(at, "Loads")
    assert any(frame.key == "plastic_cases_editor" for frame in at.dataframe)
    _goto_material_tab(at, "Concrete")
    assert at.number_input(key="conc_gamma_c").disabled is False
    _goto_material_tab(at, "Mild steel")
    assert at.number_input(key="mild_gamma_y").disabled is False
    _set(at, ("number_input", "pl_Mx", 110.0))
    assert not at.exception

    # The 2005 method has no action-moment term, but changing method must not imply
    # that the table belongs to a particular limit state or solver.
    _goto_input_tab(at, "Analysis settings")
    at.selectbox(key="shear_method").set_value(codes.EC2_2005_DKNA.label).run()
    _goto_input_tab(at, "Loads")
    assert any(frame.key == "plastic_cases_editor" for frame in at.dataframe)
    _goto_material_tab(at, "Concrete")
    assert at.number_input(key="conc_gamma_c").disabled is False


def test_prestress_always_available_without_a_toggle():
    # The "include prestressing tendons" checkbox is gone: the prestress material
    # panel and the tendon point table are always present.
    at = _fresh()
    at.run()
    assert "use_pre" not in {cb.key for cb in at.checkbox}
    _goto_material_tab(at, "Prestressing steel")
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


def test_mild_preset_selector_exposes_concrete_identity_without_rewriting_value():
    at = _fresh().run()
    _goto_material_tab(at, "Mild steel")
    selector = at.selectbox(key="mild_preset")
    assert any(
        "Curve 2 (elastic-perfectly-plastic)" in option
        and "User-defined / project-defined Curve 2 preset; uncited" in option
        for option in selector.options
    )
    assert any(
        "DS/EN 1992-1-1:2005 + DK NA:2024" in option
        and "Curve 3 Eurocode design preset" in option
        for option in selector.options
    )

    selector.set_value("Curve 2 (elastic-perfectly-plastic)").run()
    assert at.session_state["mild_preset"] == (
        "Curve 2 (elastic-perfectly-plastic)"
    )
    captions = "\n".join(str(item.value) for item in at.caption)
    assert "Preset source: User-defined / project-defined Curve 2 preset" in captions
    assert "Every material field remains a direct calculation input" in captions


def test_material_catalogue_add_duplicate_delete_and_assignment_guard():
    at = _fresh().run()
    _goto_material_tab(at, "Mild steel")

    assert [item["id"] for item in at.session_state[
        "mild_material_catalog"]["items"]] == ["M1"]
    # M1 is assigned to the default bars, so it cannot be deleted.
    assert at.button(key="mild_catalog_delete").disabled is True

    at.button(key="mild_catalog_add").click().run()
    assert not at.exception
    assert at.session_state["_mild_catalog_selected"] == "M2"
    assert [item["id"] for item in at.session_state[
        "mild_material_catalog"]["items"]] == ["M1", "M2"]
    assert at.button(key="mild_catalog_delete").disabled is False

    _set(
        at,
        ("checkbox", "shear_on", True),
        ("selectbox", "capacity_steel_material_id", "M2"),
    )
    _goto_material_tab(at, "Mild steel")
    assert at.button(key="mild_catalog_delete").disabled is True
    _set(at, ("selectbox", "capacity_steel_material_id", "M1"))
    _goto_material_tab(at, "Mild steel")
    assert at.button(key="mild_catalog_delete").disabled is False

    at.text_input(key="mildcat_r1_M2_name").set_value(
        "Existing reinforcement"
    ).run()
    assert at.session_state["_fig_cache"]["steel_M2"][1].layout.title.text == (
        "M2 - Existing reinforcement"
    )
    at.button(key="mild_catalog_duplicate").click().run()
    assert not at.exception
    items = at.session_state["mild_material_catalog"]["items"]
    assert [item["id"] for item in items] == ["M1", "M2", "M3"]
    assert items[2]["name"] == "Existing reinforcement copy"

    at.button(key="mild_catalog_delete").click().run()
    assert not at.exception
    assert [item["id"] for item in at.session_state[
        "mild_material_catalog"]["items"]] == ["M1", "M2"]


def test_reordered_catalogues_keep_historical_aliases_bound_by_material_id():
    import material_catalog

    mild, _ = material_catalog.add_entry(
        material_catalog.default_catalog("mild"), "mild"
    )
    mild["items"][0].update(name="Primary mild", fytk=550.0)
    mild["items"][1].update(name="Secondary mild", fytk=235.0)
    mild["items"] = [mild["items"][1], mild["items"][0]]

    prestress, _ = material_catalog.add_entry(
        material_catalog.default_catalog("prestress"), "prestress"
    )
    prestress["items"][0].update(name="Primary tendon", fytk=1640.0)
    prestress["items"][1].update(name="Secondary tendon", fytk=1200.0)
    prestress["items"] = [prestress["items"][1], prestress["items"][0]]

    at = _fresh()
    at.session_state["mild_material_catalog"] = mild
    at.session_state["prestress_material_catalog"] = prestress
    at.run()

    # The first catalogue rows are M2/P2, but the historical widget aliases must
    # still be seeded from M1/P1 and must not overwrite them on panel mount.
    assert at.session_state["mild_fytk"] == pytest.approx(550.0)
    assert at.session_state["pre_fytk"] == pytest.approx(1640.0)
    _goto_material_tab(at, "Mild steel")
    at.selectbox(key="_mild_catalog_selected").set_value("M1").run()
    _goto_material_tab(at, "Prestressing steel")
    at.selectbox(key="_prestress_catalog_selected").set_value("P1").run()

    mild_by_id = material_catalog.entry_map(
        at.session_state["mild_material_catalog"], "mild"
    )
    prestress_by_id = material_catalog.entry_map(
        at.session_state["prestress_material_catalog"], "prestress"
    )
    assert mild_by_id["M1"]["fytk"] == pytest.approx(550.0)
    assert mild_by_id["M2"]["fytk"] == pytest.approx(235.0)
    assert prestress_by_id["P1"]["fytk"] == pytest.approx(1640.0)
    assert prestress_by_id["P2"]["fytk"] == pytest.approx(1200.0)
    assert not at.exception


def test_2023_concrete_fck_edit_calculates():
    # Editing fck under the strength-dependent 2023 preset (alpha_cc tracks fck).
    at = _fresh()
    at.run()
    _goto_material_tab(at, "Concrete")
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
    _goto_material_tab(at, "Concrete")
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


def test_removed_design_basis_aggregate_is_absent():
    import sector_app

    assert not hasattr(sector_app, "_design_basis_summary")
    at = _fresh()
    at.run()
    visible = "\n".join(
        str(item.value)
        for group in (at.markdown, at.caption, at.info, at.warning)
        for item in group
    )
    assert "Design-basis alignment" not in visible
    widget_keys = {
        str(widget.key).lower()
        for group in (
            at.number_input,
            at.text_input,
            at.text_area,
            at.selectbox,
            at.checkbox,
            at.toggle,
            at.radio,
        )
        for widget in group
    }
    for removed in (
        "infrastructure_manager",
        "asset_class",
        "project_basis",
        "approval",
        "approver",
        "cover_calculator",
        "covercalc",
    ):
        assert not any(removed in key for key in widget_keys)


def test_es_field_present_and_editable():
    # The steel modulus Es/Ep is a direct input in both material stages.
    at = _fresh()
    at.run()
    _goto_material_tab(at, "Mild steel")
    keys = {ni.key for ni in at.number_input}
    assert "mild_Es" in keys
    at.number_input(key="mild_Es").set_value(210.0).run()   # GPa
    _goto_material_tab(at, "Prestressing steel")
    assert "pre_Es" in {ni.key for ni in at.number_input}
    assert not at.exception
    _calculate(at)
    assert not at.exception
    assert "plastic" in at.session_state["results"]


def test_eut_below_yield_strain_warns_and_calculates():
    # Meaningful constraint: a rupture strain below the yield strain is clamped
    # with a warning rather than accepted.
    at = _fresh()
    at.run()
    _goto_material_tab(at, "Mild steel")
    at.number_input(key="mild_eut").set_value(0.5).run()  # 0.5 permille, below ey ~ 2.5
    assert any("yield strain" in w.value for w in at.warning)
    _calculate(at)
    assert not at.exception


def test_two_yield_fields_live_under_default_preset():
    # The default preset builds the general law, so editing a two-yield field
    # (k) is accepted and recomputes without error.
    at = _fresh()
    at.run()
    _goto_material_tab(at, "Mild steel")
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
    _goto_material_tab(at, "Mild steel")
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
    _goto_material_tab(at, "Mild steel")
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
    _goto_material_tab(at, "Concrete")
    for locked in ("conc_gamma_c", "conc_alpha_cc"):
        assert at.number_input(key=locked).disabled is True, locked
    assert at.number_input(key="conc_fck").disabled is False
    _goto_material_tab(at, "Mild steel")
    for locked in ("mild_fytk", "mild_fyck", "mild_futk", "mild_eut",
                   "mild_gamma_y", "mild_k", "mild_ey0t"):
        assert at.number_input(key=locked).disabled is True, locked
    assert at.number_input(key="mild_Es").disabled is False


def test_prestress_law_locked_in_elastic_only_mode():
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    _goto_material_tab(at, "Prestressing steel")
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
    _goto_material_tab(at, "Mild steel")
    assert at.number_input(key="mild_fytk").disabled is False
    _goto_material_tab(at, "Concrete")
    assert at.number_input(key="conc_gamma_c").disabled is False
    _goto_input_tab(at, "Analysis settings")
    at.radio(key="mode").set_value("Plastic").run()
    _goto_material_tab(at, "Mild steel")
    assert at.number_input(key="mild_fytk").disabled is False


def test_fctm_and_ec_locked_in_plastic_only_mode():
    # fctm and Ec only affect the elastic results, so plastic-only mode
    # disables them; Elastic re-enables them.
    at = _fresh()
    at.run()                                   # default mode is Plastic
    _goto_material_tab(at, "Concrete")
    assert at.number_input(key="sls_fctm").disabled is True
    assert at.number_input(key="conc_Ec").disabled is True
    _goto_input_tab(at, "Analysis settings")
    at.radio(key="mode").set_value("Elastic").run()
    _goto_material_tab(at, "Concrete")
    assert at.number_input(key="sls_fctm").disabled is False
    assert at.number_input(key="conc_Ec").disabled is False


def test_fatigue_unlocks_the_elastic_material_parameters():
    at = _fresh()
    at.run()
    _goto_material_tab(at, "Concrete")
    assert at.number_input(key="conc_Ec").disabled is True

    _goto_input_tab(at, "Analysis settings")
    at.toggle(key="fatigue_on").set_value(True).run()

    _goto_material_tab(at, "Concrete")
    assert at.number_input(key="conc_Ec").disabled is False
    _goto_input_tab(at, "Loads")
    assert at.number_input(key="el_phi").disabled is False


def test_default_material_preset_is_dk_na_with_550():
    # Defaults to the Danish edition with B550 reinforcement.
    at = _fresh()
    at.run()
    assert at.session_state["conc_preset"] == "DS/EN 1992-1-1:2005 + DK NA:2024"
    assert at.session_state["mild_preset"] == "DS/EN 1992-1-1:2005 + DK NA:2024"
    _goto_material_tab(at, "Mild steel")
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
    _goto_material_tab(at, "Mild steel")
    at.selectbox(key="mild_preset").set_value("Curve 1 (bilinear hardening)").run()
    at.number_input(key="mild_futk").set_value(0.0).run()
    assert not at.exception
    _calculate(at)
    assert not at.exception


def test_creep_help_follows_concrete_preset_without_changing_phi():
    at = _fresh()
    at.run()
    _goto_input_tab(at, "Loads")
    at.number_input(key="el_phi").set_value(1.75).run()
    retained_phi = at.number_input(key="el_phi").value
    assert retained_phi == 1.75

    dk_help = at.number_input(key="el_phi").help
    assert "DK NA:2024, 3.1.4(1)-(2)" in dk_help
    assert "phi = 3 is conditional" in dk_help
    assert "does not infer whether creep is decisive" in dk_help

    _goto_material_tab(at, "Concrete")
    at.selectbox(key="conc_preset").set_value("EN 1992-1-1:2005").run()
    _goto_input_tab(at, "Loads")
    base_help = at.number_input(key="el_phi").help
    assert "3.1.4 and Annex B.1" in base_help
    assert "DK NA:2024" not in base_help
    assert at.number_input(key="el_phi").value == retained_phi

    _goto_material_tab(at, "Concrete")
    at.selectbox(key="conc_preset").set_value("DS/EN 1992-1-1:2023").run()
    _goto_input_tab(at, "Loads")
    published_help = at.number_input(key="el_phi").help
    assert "5.1.5, Table 5.2 and Annex B.5" in published_help
    assert "project adoption required" in published_help
    assert "no Danish National Annex" in published_help
    assert at.number_input(key="el_phi").value == retained_phi

    _goto_material_tab(at, "Concrete")
    at.selectbox(key="conc_preset").set_value(
        "Curve 2 (parabola-rectangle)"
    ).run()
    _goto_input_tab(at, "Loads")
    project_help = at.number_input(key="el_phi").help
    assert "project-defined" in project_help
    assert "no Eurocode source is inferred" in project_help
    assert "DS/EN 1992" not in project_help
    assert at.number_input(key="el_phi").value == retained_phi
    assert not at.exception


def test_detailing_checkbox_help_follows_selected_edition_only():
    at = _fresh()
    at.run()

    minimum = at.checkbox(key="minimum_reinforcement_on")
    links = at.checkbox(key="transverse_detailing_on")
    spacing = at.checkbox(key="clear_spacing_on")
    assert "9.2.1.1(1)" in minimum.help
    assert "Formula (9.1N)" in minimum.help
    assert "high-beam-web provision is not included" in minimum.help
    assert "DK NA:2024, 9.2.2(5), Formula (9.5N NA)" in links.help
    assert "DK NA:2024, 8.2(2) unchanged" in spacing.help

    minimum.set_value(True).run()
    at.selectbox(key="detailing_edition").set_value(
        "EN 1992-1-1:2005"
    ).run()
    base_minimum_help = at.checkbox(key="minimum_reinforcement_on").help
    base_links_help = at.checkbox(key="transverse_detailing_on").help
    base_spacing_help = at.checkbox(key="clear_spacing_on").help
    assert "9.2.1.1(1)" in base_minimum_help
    assert "9.3.1.1(1)-(2)" in base_minimum_help
    assert "9.2.2(5)-(8)" in base_links_help
    assert "9.3.2(2), (4)-(5)" in base_links_help
    assert "8.2(2)" in base_spacing_help
    for help_text in (base_minimum_help, base_links_help, base_spacing_help):
        assert "DK NA:2024" not in help_text

    at.selectbox(key="detailing_edition").set_value(
        "DS/EN 1992-1-1:2023"
    ).run()
    published_minimum = at.checkbox(key="minimum_reinforcement_on").help
    published_links = at.checkbox(key="transverse_detailing_on").help
    published_spacing = at.checkbox(key="clear_spacing_on").help
    assert "12.2(2), Formulae (12.1)-(12.2)" in published_minimum
    assert "Tables 12.1 and 12.2, 12.3.3 and 12.4.2" in published_links
    assert "11.2(2)" in published_spacing
    for help_text in (published_minimum, published_links, published_spacing):
        assert "project adoption required" in help_text
        assert "no Danish National Annex" in help_text
    assert at.checkbox(key="minimum_reinforcement_on").value is True
    assert at.checkbox(key="transverse_detailing_on").value is False
    assert at.checkbox(key="clear_spacing_on").value is False
    assert not at.exception


def test_crack_input_tooltips_follow_the_exact_selected_basis():
    at = _fresh()
    at.run()
    _goto_input_tab(at, "Analysis settings")
    at.radio(key="mode").set_value("Elastic").run()

    assert (
        "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010"
        in at.number_input(key="sls_phi").help
    )
    assert "Formulas (7.8), (7.9), (7.11) and (7.14)" in (
        at.selectbox(key="sls_bond").help
    )
    assert "not used by the selected first-generation" in (
        at.number_input(key="sls_tendon_xi").help
    )
    assert "DK NA fine-system selection" in (
        at.selectbox(key="sls_member").help
    )

    at.selectbox(key="sls_code").set_value(_SLS_2023).run()
    assert "DS/EN 1992-1-1:2023, 9.2.2 and 9.2.3" in (
        at.number_input(key="sls_phi").help
    )
    assert "DS/EN 1992-1-1:2023, 9.2.2(3), Formula (9.6)" in (
        at.number_input(key="sls_tendon_xi").help
    )

    at.selectbox(key="sls_code").set_value(_SLS_DK).run()
    assert "DS/EN 1992-1-1 DK NA:2024, 7.3.4(1)" in (
        at.selectbox(key="sls_member").help
    )
    for key in ("sls_heightened_reinforcement_surface",):
        assert "DK NA:2024" in at.selectbox(key=key).help
        assert "Formula 7.100 NA" in at.selectbox(key=key).help
    for key in (
        "sls_heightened_effective_tensile_strength_mpa",
        "sls_heightened_fine_effective_tension_area_mm2",
        "sls_heightened_coarse_effective_tension_area_mm2",
    ):
        assert "DK NA:2024" in at.number_input(key=key).help
        assert "Formula 7.100 NA" in at.number_input(key=key).help
    assert not at.exception


def test_heightened_reference_becomes_explicit_when_second_case_is_enabled():
    import load_cases

    at = _fresh()
    at.run()
    _set(
        at,
        ("radio", "mode", "Elastic"),
        ("selectbox", "sls_code", _SLS_DK),
    )
    cases = at.session_state[load_cases.ELASTIC_TABLE_KEY].to_dict("records")
    cases[0]["calculate_crack_width"] = True
    first_name = str(cases[0]["name"])
    _replace_case_table(at, load_cases.ELASTIC_TABLE_KEY, cases)
    _set(at, ("toggle", "sls_heightened_on", True))

    assert at.session_state["sls_heightened_reference_case"] == first_name

    _replace_case_table(
        at,
        load_cases.ELASTIC_TABLE_KEY,
        [
            *cases,
            {
                "name": "Second crack case",
                "calculate_crack_width": True,
            },
        ],
    )
    _goto_input_tab(at, "Analysis settings")
    reference = at.selectbox(key="sls_heightened_reference_case")

    assert reference.value == ""
    assert at.session_state["sls_heightened_reference_case"] == ""
    reference.set_value(first_name).run()
    assert at.session_state["sls_heightened_reference_case"] == first_name


def test_fatigue_tooltips_bind_routes_without_citing_custom_detail_values():
    import fatigue_inputs

    at = _fresh()
    at.run()
    _goto_input_tab(at, "Analysis settings")
    at.toggle(key="fatigue_on").set_value(True).run()
    assert "DS/EN 1992-1-1:2005+A1:2014" in (
        at.selectbox(key="fatigue_concrete_method").help
    )
    assert "DS/EN 1992-2:2005/AC:2008 Formula 6.106" in (
        at.selectbox(key="fatigue_concrete_method").help
    )
    first_generation_help = {
        "fatigue_gamma_ff": "2.4.2.3 and 6.8.4(1)",
        "fatigue_gamma_s": "clause 6.8.4 and Tables 6.3N/6.4N",
        "fatigue_gamma_c": "3.1.6 and 6.8.7, Formula (6.76)",
        "fatigue_beta_cc_t0": "3.1.6 and 6.8.7, Formula (6.76)",
        "fatigue_concrete_k1": "3.1.6 and 6.8.7, Formula (6.76)",
        "fatigue_concrete_c": "DS/EN 1992-2:2005/AC:2008 Formula 6.106",
    }
    for key, source in first_generation_help.items():
        assert source in at.number_input(key=key).help

    at.selectbox(key="fatigue_edition").set_value(_SLS_2023).run()
    assert "E.4.3, Formula (E.2)" in (
        at.selectbox(key="fatigue_concrete_method").help
    )
    assert "E.5.3, Formulae (E.7)-(E.8)" in (
        at.selectbox(key="fatigue_concrete_method").help
    )
    published_2023_help = {
        "fatigue_gamma_ff": "DS/EN 1992-1-1:2023, 10.2 and Annex E",
        "fatigue_gamma_s": "Annex E.5 and Tables E.1/E.2",
        "fatigue_gamma_c": "5.1.6(1), Formula (5.3), and 10.5, Formula (10.5)",
        "fatigue_beta_cc_t0": (
            "5.1.6(1), Formula (5.3), and 10.5, Formula (10.5)"
        ),
        "fatigue_concrete_k1": "not used by the 2023 concrete fatigue strength",
        "fatigue_concrete_c": "E.5.3, Formulae (E.7)-(E.8)",
    }
    for key, source in published_2023_help.items():
        assert source in at.number_input(key=key).help

    at.selectbox(key="fatigue_concrete_method").set_value(
        "User-defined Miner S-N relation"
    ).run()
    custom_method_help = at.selectbox(key="fatigue_concrete_method").help
    custom_c_help = at.number_input(key="fatigue_concrete_c").help
    for help_text in (custom_method_help, custom_c_help):
        assert "project-defined" in help_text.casefold()
        assert "record" in help_text.casefold()
        assert "DS/EN 1992" not in help_text
        assert "Formulae (E.7)-(E.8)" not in help_text
    assert at.number_input(key="fatigue_concrete_c").disabled is False

    at.selectbox(key="fatigue_edition").set_value(_SLS_DK).run()
    for help_text in (
        at.selectbox(key="fatigue_concrete_method").help,
        at.number_input(key="fatigue_concrete_c").help,
    ):
        assert "record" in help_text.casefold()
        assert "DS/EN 1992" not in help_text
        assert "Formula 6.106" not in help_text

    at.selectbox(key="fatigue_edition").set_value(_SLS_2023).run()
    _goto_material_tab(at, "Fatigue details")

    def detail_widget(suffix):
        return next(
            widget
            for widget in (
                list(at.number_input)
                + list(at.selectbox)
                + list(at.text_input)
            )
            if str(widget.key).startswith("fatiguecat_")
            and str(widget.key).endswith(suffix)
        )

    # The retained default is a 2005 named preset. Its help follows that preset,
    # not the separately selected 2023 calculation route.
    assert "DS/EN 1992-1-1:2005, Table 6.3N" in (
        detail_widget("_delta_sigma_rsk_mpa").help
    )
    assert "DS/EN 1992-1-1:2005, Table 6.3N" in (
        detail_widget("_source").help
    )
    for suffix in ("_bond_ratio_xi", "_bond_equivalent_diameter_mm"):
        assert "DS/EN 1992-1-1:2023 10.3(2)" in detail_widget(suffix).help

    custom_catalog = fatigue_inputs.default_catalog()
    custom_catalog["items"][0]["preset"] = fatigue_inputs.CUSTOM_PRESET
    custom_at = _fresh()
    custom_at.session_state[fatigue_inputs.DETAIL_CATALOG_KEY] = custom_catalog
    custom_at.session_state["fatigue_on"] = True
    custom_at.session_state["fatigue_edition"] = _SLS_2023
    custom_at.session_state["_main_page"] = "Inputs"
    custom_at.session_state["_input_tab"] = f"3 {chr(0xB7)} Material parameters"
    custom_at.session_state["_material_tab"] = "Fatigue details"
    custom_at.run()
    custom_help = next(
        widget.help
        for widget in custom_at.number_input
        if str(widget.key).startswith("fatiguecat_")
        and str(widget.key).endswith("_delta_sigma_rsk_mpa")
    )
    assert "project-defined value" in custom_help
    assert "No Eurocode source is inferred" in custom_help
    assert "DS/EN 1992" not in custom_help
    custom_source_help = next(
        widget.help
        for widget in custom_at.text_input
        if str(widget.key).startswith("fatiguecat_")
        and str(widget.key).endswith("_source")
    )
    assert "No Eurocode source is inferred" in custom_source_help
    assert "DS/EN 1992" not in custom_source_help
    assert not custom_at.exception


def test_inputs_carry_help_tooltips():
    # Inputs across the panels expose hover help (the "?" tooltip).
    at = _fresh()
    at.run()
    _goto_input_tab(at, "Loads")
    for key in ("el_phi",):
        w = (_widget(at.number_input, key) or _widget(at.selectbox, key)
             or _widget(at.radio, key))
        assert w is not None and w.help, key
    _goto_input_tab(at, "Analysis settings")
    for key in (
        "fatigue_edition",
        "fatigue_check_steel",
        "fatigue_check_concrete",
        "fatigue_concrete_method",
        "fatigue_gamma_ff",
        "fatigue_gamma_s",
        "fatigue_gamma_c",
        "fatigue_beta_cc_t0",
        "fatigue_t0_days",
        "fatigue_concrete_k1",
        "fatigue_concrete_c",
    ):
        w = (
            _widget(at.number_input, key)
            or _widget(at.selectbox, key)
            or _widget(at.toggle, key)
        )
        assert w is not None and w.help, key
    assert at.number_input(key="fatigue_gamma_ff").label == r"$\gamma_{Ff}$"
    assert at.number_input(key="fatigue_gamma_s").label == r"$\gamma_s$"
    assert at.number_input(key="fatigue_gamma_c").label == (
        r"$\gamma_{c,\mathrm{fat}}$"
    )
    assert at.number_input(key="fatigue_beta_cc_t0").label == (
        r"$\beta_{cc}(t_0)$"
    )
    assert r"$\beta_{cc}(t_0)$" in at.number_input(
        key="fatigue_t0_days").help

    _goto_material_tab(at, "Concrete")
    assert at.number_input(key="conc_fck").help
    _goto_material_tab(at, "Mild steel")
    for key in ("mild_fytk", "mild_eut"):
        assert at.number_input(key=key).help
    for widget_group in (
        at.number_input, at.selectbox, at.text_input, at.toggle, at.checkbox,
    ):
        for widget in widget_group:
            for value in (getattr(widget, "label", ""), getattr(widget, "help", "")):
                assert not re.search(
                    r"[\x00-\x08\x0b\x0c\x0e-\x1f]",
                    value or "",
                ), (widget.key, value)
    _goto_input_tab(at, "Analysis settings")
    assert at.number_input(key="v_min").label == (
        r"Start angle $\varphi_{NA,\min}$ ($^\circ$)"
    )
    assert not any(widget.key == "sls_wk_limit" for widget in at.number_input)
    assert at.number_input(key="detailing_d_upper").label == (
        r"Maximum aggregate size $D_{\mathrm{upper}}$ (mm)"
    )
    assert at.selectbox(key="sls_bond").label == r"Mild-steel bond ($k_1$)"
    at.toggle(key="fatigue_on").set_value(True).run()
    _goto_material_tab(at, "Fatigue details")
    fatigue_detail_keys = (
        "_n_star",
        "_delta_sigma_rsk_mpa",
        "_k1",
        "_k2",
        "_stress_model",
        "_mandrel_diameter_mm",
        "_bond_ratio_xi",
        "_bond_equivalent_diameter_mm",
        "_source",
    )
    widgets = (
        list(at.number_input)
        + list(at.selectbox)
        + list(at.text_input)
    )
    for suffix in fatigue_detail_keys:
        matching = [
            w for w in widgets
            if str(w.key).startswith("fatiguecat_")
            and str(w.key).endswith(suffix)
        ]
        assert matching and matching[0].help, suffix
    n_star = next(
        w for w in widgets
        if str(w.key).startswith("fatiguecat_")
        and str(w.key).endswith("_n_star")
    )
    assert n_star.label == r"Reference cycles $N^*$"
    _goto_input_tab(at, "Analysis settings")
    assert at.radio(key="mode").help
    _goto_page(at, "Analysis")
    assert at.selectbox(key="view").help
    # The Quick Section builder inputs carry help too.
    _open_qs(at)
    for key in ("shape", "b_mm", "h_mm", "bot_c_mm", "top_c_mm"):
        w = _widget(at.number_input, key) or _widget(at.selectbox, key)
        assert w is not None and w.help, key


def test_streamlit_text_uses_katex_or_plain_display_symbols():
    """No LaTeX command may escape a supported math span in rendered UI text."""
    at = _fresh()
    at.run()

    def check_tree():
        groups = (
            "markdown", "caption", "info", "warning", "error", "success",
            "metric", "number_input", "selectbox", "text_input", "text_area",
            "radio", "toggle", "checkbox", "button",
        )
        for group_name in groups:
            for element in getattr(at, group_name, ()):
                for attribute in ("label", "help", "value"):
                    _assert_math_text_is_renderable(
                        getattr(element, attribute, None)
                    )
        # Dataframe cells are deliberately non-Markdown in Streamlit. Column names
        # therefore use display glyphs and may never contain raw LaTeX delimiters.
        for element in at.dataframe:
            value = element.value
            for column in getattr(value, "columns", ()):
                assert "$" not in str(column)
                assert "\\" not in str(column)

    check_tree()
    _calculate(at)
    check_tree()


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
    _set_and_click(at, "qs_back")
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
    for v in [
        "Results Overview", "Plastic Results", "Elastic Results",
        "Fatigue Results", "Detailing",
    ]:
        _select_view(at, v)
        assert not at.exception, v


def test_prestress_curve_is_co_located_with_its_inputs():
    at = _fresh_qs()
    at.number_input(key="tnd_n").set_value(4).run()
    _apply_qs(at)                            # put tendons in the section
    _goto_material_tab(at, "Prestressing steel")
    assert "prestress_P1" in at.session_state["_fig_cache"]
    assert not at.exception


def test_results_views_render_after_calculate():
    at = _fresh()
    at.run()
    _set_and_click(at, "calculate", ("radio", "mode", "Both"))
    for v in [
        "Results Overview", "Plastic Results", "Elastic Results", "Detailing"
    ]:
        _select_view(at, v)
        assert not at.exception, v


def test_native_load_case_editors_use_consistent_ed_columns():
    import fatigue_inputs
    import load_cases

    at = _fresh()
    at.run()
    _goto_input_tab(at, "Loads")
    assert any(
        "Each action reports stresses and can calculate crack width" in item.value
        and "long- and short-term limits apply to their matching branches"
        in item.value
        for item in at.caption
    )
    assert not any("row criterion" in item.value for item in at.caption)

    plastic = _widget(at.dataframe, "plastic_cases_editor").value
    elastic = _widget(at.dataframe, "elastic_cases_editor").value
    assert list(plastic.columns) == [
        "name", "description", "n_ed_kn", "mx_ed_knm", "my_ed_knm",
        "vx_ed_kn", "vy_ed_kn", "vx_face", "vy_face", "t_ed_knm",
        "check_minimum_reinforcement",
    ]
    assert list(elastic.columns) == [
        "name", "description",
        "n_long_ed_kn", "mx_long_ed_knm", "my_long_ed_knm",
        "n_short_ed_kn", "mx_short_ed_knm", "my_short_ed_knm",
        "calculate_crack_width",
    ]
    for editor_key, action_columns in (
        ("plastic_cases_editor", load_cases.PLASTIC_NUMERIC),
        ("elastic_cases_editor", load_cases.ELASTIC_ACTION_NUMERIC),
    ):
        column_config = json.loads(
            _widget(at.dataframe, editor_key).proto.columns
        )
        for key in action_columns:
            assert column_config[key]["required"] is False
            assert column_config[key]["default"] == "0"
            assert column_config[key]["type_config"]["type"] == "text"
    _goto_input_tab(at, "Analysis settings")
    at.toggle(key="fatigue_on").set_value(True).run()
    _goto_input_tab(at, "Loads")
    fatigue = _widget(at.dataframe, "fatigue_spectrum_editor").value
    assert list(fatigue.columns) == [
        "spectrum", "name", "description", "cycles",
        "n_long_ed_kn", "mx_long_ed_knm", "my_long_ed_knm",
        "n_short_ed_kn", "mx_short_ed_knm", "my_short_ed_knm",
    ]
    fatigue_editor = _widget(at.dataframe, "fatigue_spectrum_editor")
    column_config = json.loads(fatigue_editor.proto.columns)
    for key in ("n_short_ed_kn", "mx_short_ed_knm", "my_short_ed_knm"):
        label = column_config[key]["label"]
        assert label.startswith(chr(0x394))
        assert "Delta" not in label and "$" not in label and "\\" not in label
    for key in fatigue_inputs.ACTION_COLUMNS:
        assert column_config[key]["required"] is False
        assert column_config[key]["default"] == "0"
        assert column_config[key]["type_config"]["type"] == "text"
    assert column_config[fatigue_inputs.CYCLES]["required"] is True
    assert column_config[fatigue_inputs.CYCLES]["type_config"]["type"] == "text"
    load_guide_labels = {item.label for item in at.expander}
    assert {
        "Plastic and capacity cases - field guide",
        "Elastic cases - field guide",
        "Grouped fatigue spectrum - field guide",
    }.issubset(load_guide_labels)
    guide_tables = [
        item.value
        for item in at.markdown
        if "| Notation / field | Meaning and sign | Input rule / source |"
        in str(item.value)
    ]
    assert len(guide_tables) == 3
    assert all(value.count("$") % 2 == 0 for value in guide_tables)
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
    _goto_input_tab(at, "Section")
    section_guide_labels = {item.label for item in at.expander}
    assert {
        "Concrete corner points - field guide",
        "Concrete void points - field guide",
        "Reinforcing bars - field guide",
        "Prestressing tendons - field guide",
    }.issubset(section_guide_labels)


def test_fatigue_editor_submits_sparse_new_rows_with_zero_action_defaults():
    import fatigue_inputs

    at = _fresh()
    at.run()
    _goto_input_tab(at, "Analysis settings")
    at.toggle(key="fatigue_on").set_value(True).run()
    _goto_input_tab(at, "Loads")

    editor = _widget(at.dataframe, "fatigue_spectrum_editor")
    column_config = json.loads(editor.proto.columns)
    for key in fatigue_inputs.ACTION_COLUMNS:
        assert column_config[key]["required"] is False
        assert column_config[key]["default"] == "0"
        assert column_config[key]["type_config"]["type"] == "text"

    # Regression for the observed one-bin Train spectrum: the engineer only
    # enters the non-zero cyclic moment. Streamlit must still be able to submit
    # the row, and Sector's canonical contract retains every omitted component
    # as an explicit zero rather than dropping the spectrum.
    sparse_row = {
        "spectrum": "1",
        "name": "Train",
        "description": None,
        "cycles": 36000.0,
        "mx_short_ed_knm": 17.0,
    }
    canonical = fatigue_inputs.normalise_spectrum_table([sparse_row])
    assert fatigue_inputs.spectrum_errors(canonical, require_rows=True) == []
    record = fatigue_inputs.spectrum_records(canonical)[0]
    assert record["mx_short_ed_knm"] == pytest.approx(17.0)
    assert all(
        record[key] == pytest.approx(0.0)
        for key in fatigue_inputs.ACTION_COLUMNS
        if key != "mx_short_ed_knm"
    )


def test_detailing_controls_run_selected_case_and_section_wide_spacing():
    import load_cases

    at = _fresh()
    at.run()
    alias = ":red[span] [deck](https://example.test) **critical**"
    at.text_input(key="modelled_direction_alias").set_value(alias).run()
    _replace_case_table(at, load_cases.PLASTIC_TABLE_KEY, [{
        "name": "PL-DETAIL",
        "mx_ed_knm": 50.0,
        "check_minimum_reinforcement": True,
    }])
    _set(
        at,
        ("checkbox", "minimum_reinforcement_on", True),
        ("checkbox", "clear_spacing_on", True),
    )
    _calculate(at)

    results = at.session_state["results"]
    assert "clear_spacing" in results
    assert "minimum_reinforcement" in results["plastic_cases"][0]["results"]
    _select_view(at, "Detailing")
    minimum = next(
        frame.value for frame in at.dataframe
        if "As,min [mm2]" in frame.value.columns
    )
    spacing = next(
        frame.value for frame in at.dataframe
        if "Required [mm]" in frame.value.columns
    )
    assert not minimum.empty
    assert not spacing.empty
    assert any(
        item.value == (
            "**Longitudinal (project alias: "
            r"\:red\[span\] \[deck\]\(https\:\/\/example\.test\) "
            r"\*\*critical\*\*) minimum reinforcement**"
        )
        for item in at.markdown
    )
    assert not at.exception


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

    assert len(at.table) == 1
    frame = at.table[0]
    summary = frame.value
    bending = summary.loc[summary["Check"] == "Plastic bending"]
    assert bending["Governing action"].tolist() == ["PL-HIGH"]
    assert "Governing" not in summary.columns

    _select_view(at, "Plastic Results")
    picker = at.selectbox(key="_plastic_result_case_index")
    assert picker.options == ["PL-LOW - Lower action", "PL-HIGH - Higher action"]
    picker.set_value(1).run()
    actions = next(
        frame.value for frame in at.dataframe
        if list(frame.value.columns) == [
            "N_Ed [kN]", "Mx_Ed [kNm]", "My_Ed [kNm]",
            "Vx_Ed [kN]", "Vy_Ed [kN]", "Vx face", "Vy face",
            "T_Ed [kNm]", "Minimum reinforcement",
        ]
    )
    assert actions.iloc[0]["Mx_Ed [kNm]"] == pytest.approx(80.0)
    assert not at.exception


def test_results_overview_uses_one_static_content_height_table(monkeypatch):
    import result_presentation
    import sector_app

    rows = [
        {
            "family": f"family-{index}",
            "check": f"Check {index}",
            "case": f"CASE-{index}",
            "status": "PASS",
            "result": f"{index}.0 %",
            "criterion": "<= 100 %",
            "source": f"Register {index}",
            "case_type": "ULS",
            "view": "Plastic Results",
            "note": f"Source {index}",
            "util": index / 100.0,
        }
        for index in range(20)
    ]

    class FakeStreamlit:
        def __init__(self):
            self.tables = []

        def info(self, *_args, **_kwargs):
            return None

        def warning(self, *_args, **_kwargs):
            return None

        def error(self, *_args, **_kwargs):
            return None

        def success(self, *_args, **_kwargs):
            return None

        def caption(self, *_args, **_kwargs):
            return None

        def columns(self, count):
            return [self] * count

        def metric(self, *_args, **_kwargs):
            return None

        def table(self, data, **kwargs):
            self.tables.append((data, kwargs))

        def markdown(self, *_args, **_kwargs):
            return None

        def text(self, *_args, **_kwargs):
            return None

    fake = FakeStreamlit()
    monkeypatch.setattr(sector_app, "st", fake)
    monkeypatch.setattr(sector_app, "presentation", result_presentation)
    monkeypatch.setattr(
        result_presentation,
        "multi_case_summary_rows",
        lambda _inp, _results, stale=False: rows,
    )

    sector_app.results_overview_view({}, {})

    assert len(fake.tables) == 1
    styled, options = fake.tables[0]
    assert len(styled.data) == 20
    assert options["height"] == "content"
    assert options["width"] == "stretch"


def test_elastic_case_picker_shows_action_parts_and_crack_choice():
    import load_cases

    at = _fresh()
    at.run()
    _set(at, ("radio", "mode", "Elastic"))
    _replace_case_table(at, load_cases.ELASTIC_TABLE_KEY, [
        {
            "name": "EL-STRESS",
            "description": "Characteristic",
            "mx_long_ed_knm": 40.0,
            "calculate_crack_width": False,
        },
        {
            "name": "EL-CRACK",
            "description": "Frequent",
            "mx_long_ed_knm": 120.0,
            "mx_short_ed_knm": 30.0,
            "calculate_crack_width": True,
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
    assert any(
        "Stresses are reported for this action. Crack width: calculated" in caption.value
        for caption in at.caption
    )
    assert not at.exception


def test_results_overview_shows_action_provenance_and_explicit_states():
    at = _fresh()
    at.run()
    _select_view(at, "Results Overview")
    assert not at.table
    assert any("Plastic bending | PL-01 | NOT RUN" in item.value for item in at.text)

    _set_and_click(
        at,
        "calculate",
        ("text_input", "pl_case_id", "PL-GOV-04"),
        ("text_input", "pl_case_source", "Combination register C1"),
    )
    assert len(at.table) == 1
    status = at.table[0].value
    bending = status.loc[status["Check"] == "Plastic bending"].iloc[0]
    assert bending["Governing action"] == "PL-GOV-04"
    assert "Source / description" not in status.columns
    assert set(status["Status"]) == {"PASS"}

    _set(at, ("text_input", "pl_case_id", "PL-GOV-05"))
    _select_view(at, "Results Overview")
    stale = at.table[0].value
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
    assert not at.exception
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


def test_page_navigation_and_input_stages_follow_the_workflow_order():
    # Only the selected top-level workspace renders. Inputs stages four engineering
    # steps plus Project; Report is the peer immediately right of Analysis.
    at = _fresh()
    at.run()
    d = chr(0x00B7)   # the step-number middle dot (v0.63)
    nav = at.segmented_control(key="_main_page")
    assert nav.options == ["Inputs", "Analysis", "Report"]
    assert nav.value == "Inputs"
    expected_outer = [
        f"1 {d} Analysis settings",
        f"2 {d} Section",
        f"3 {d} Material parameters",
        f"4 {d} Loads",
        "Project",
    ]
    assert [tab.label for tab in at.tabs] == expected_outer
    assert at.session_state["_input_tab"] == expected_outer[0]
    labels = [ex.label for ex in at.expander]
    assert labels == [
        "Elastic crack-width method",
        "Reinforcement detailing",
        "Fatigue",
        "Shear, torsion & combined (Plastic)",
    ]
    _goto_input_tab(at, "Project")
    labels = [ex.label for ex in at.expander]
    assert labels == ["About", "Save / Load"]
    assert "rep_proj_no" not in {widget.key for widget in at.text_input}

    _goto_page(at, "Report")
    assert at.segmented_control(key="rep_report_content").value == "Standard"
    assert "rep_proj_no" in {widget.key for widget in at.text_input}
    assert not at.expander


def test_v093_hot_reload_purges_schema23_bridge_state_before_widgets_mount():
    import session_state_migrations as migrations

    at = _fresh()
    at.run()
    assert not at.exception

    del at.session_state[migrations.MIGRATION_MARKER]
    for key in migrations.RETIRED_BRIDGE_STATE_KEYS:
        at.session_state[key] = {"legacy": key}
    at.session_state["_durable_input_scalars"] = {
        "autosave_min": 17,
        "bridge_standard": "legacy",
        "bridge_brittle_base": [{"region_id": "R1"}],
    }
    at.session_state["_pending_input_events"] = {
        "autosave_on": False,
        "bridge_box_walls_base": [{"wall_id": "W1"}],
    }
    at.session_state["_latest_inputs"] = {
        "signature": ("schema-23",),
        "bridge_standard": "legacy",
    }
    at.session_state["results"] = {
        "plastic": {"legacy": True},
        "bridge": {"calculations": {"legacy": True}},
    }
    at.session_state["result_sig"] = ("schema-23",)
    at.session_state["result_plastic_sig"] = ("schema-23",)
    at.session_state["result_input_snapshot"] = {"bridge_standard": "legacy"}
    at.session_state["calculation_record"] = {"input_sha256": "legacy"}
    at.session_state["report_buffer"] = b"legacy report"
    at.session_state["report_signature"] = ("schema-23",)
    at.session_state["manual_pdf"] = b"legacy manual"
    at.session_state["view"] = "Bridge Calculations"
    at.session_state["_workspace_view"] = "Bridge Calculations"
    at.session_state["_main_page"] = "Analysis"

    at.run()

    assert not at.exception
    assert at.session_state[migrations.MIGRATION_MARKER] is True
    for key in migrations.RETIRED_BRIDGE_STATE_KEYS:
        assert key not in at.session_state
    assert at.session_state["_durable_input_scalars"]["autosave_min"] == 17
    assert "bridge_standard" not in at.session_state["_durable_input_scalars"]
    assert "_pending_input_events" not in at.session_state
    assert "results" not in at.session_state
    assert "result_sig" not in at.session_state
    assert "result_plastic_sig" not in at.session_state
    assert "result_input_snapshot" not in at.session_state
    assert "calculation_record" not in at.session_state
    assert "report_buffer" not in at.session_state
    assert "report_signature" not in at.session_state
    assert "manual_pdf" not in at.session_state
    assert "bridge_standard" not in at.session_state["_latest_inputs"]
    assert at.session_state["_main_page"] == "Inputs"
    assert at.session_state["view"] == "Results Overview"
    assert at.session_state["_workspace_view"] == "Results Overview"
    assert all(
        "bridge" not in expander.label.casefold()
        for expander in at.expander
    )


def test_only_selected_outer_stage_mounts_and_retains_material_edits():
    at = _fresh()
    at.run()

    assert "conc_fck" not in {widget.key for widget in at.number_input}
    assert "section_label_scale" not in {widget.key for widget in at.number_input}
    assert not at.get("data_editor")

    _goto_material_tab(at, "Concrete")
    at.number_input(key="conc_fck").set_value(55.0).run()
    assert at.session_state["_durable_input_scalars"]["conc_fck"] == 55.0

    _goto_input_tab(at, "Loads")
    assert "conc_fck" not in {widget.key for widget in at.number_input}
    assert any(frame.key == "plastic_cases_editor" for frame in at.dataframe)
    assert at.session_state["conc_fck"] == 55.0

    _goto_material_tab(at, "Concrete")
    assert at.number_input(key="conc_fck").value == 55.0
    assert not at.exception


def test_only_selected_material_family_mounts_and_retains_sibling_edits():
    at = _fresh()
    at.run()
    _goto_input_tab(at, "Material parameters")

    assert at.session_state["_material_tab"] == "Concrete"
    dot = chr(0x00B7)
    assert [tab.label for tab in at.tabs] == [
        f"1 {dot} Analysis settings",
        f"2 {dot} Section",
        f"3 {dot} Material parameters",
        "Concrete",
        "Mild steel",
        "Prestressing steel",
        f"4 {dot} Loads",
        "Project",
    ]
    number_keys = {widget.key for widget in at.number_input}
    assert "conc_fck" in number_keys
    assert "mild_fytk" not in number_keys
    assert "pre_fytk" not in number_keys

    at.number_input(key="conc_fck").set_value(55.0).run()
    _goto_material_tab(at, "Mild steel")
    number_keys = {widget.key for widget in at.number_input}
    assert "conc_fck" not in number_keys
    assert "mild_fytk" in number_keys
    assert "pre_fytk" not in number_keys
    at.number_input(key="mild_fytk").set_value(525.0).run()

    _goto_material_tab(at, "Prestressing steel")
    number_keys = {widget.key for widget in at.number_input}
    assert "conc_fck" not in number_keys
    assert "mild_fytk" not in number_keys
    assert "pre_fytk" in number_keys

    _goto_material_tab(at, "Concrete")
    assert at.number_input(key="conc_fck").value == 55.0
    assert at.session_state["mild_fytk"] == 525.0
    assert not at.exception


def test_fatigue_material_family_is_conditional_and_cannot_mount_outside_owner():
    at = _fresh()
    at.run()
    at.toggle(key="fatigue_on").set_value(True).run()
    _goto_input_tab(at, "Material parameters")

    labels = [tab.label for tab in at.tabs]
    start = labels.index("Concrete")
    assert labels[start:start + 4] == [
        "Concrete", "Mild steel", "Prestressing steel", "Fatigue details",
    ]
    _goto_material_tab(at, "Fatigue details")
    assert any(button.key == "fatigue_catalog_add_mild" for button in at.button)
    assert "conc_fck" not in {widget.key for widget in at.number_input}

    _goto_input_tab(at, "Analysis settings")
    assert not any(button.key == "fatigue_catalog_add_mild" for button in at.button)
    at.toggle(key="fatigue_on").set_value(False).run()
    assert at.session_state["_material_tab"] == "Concrete"

    _goto_input_tab(at, "Material parameters")
    labels = [tab.label for tab in at.tabs]
    start = labels.index("Concrete")
    assert labels[start:start + 3] == [
        "Concrete", "Mild steel", "Prestressing steel",
    ]
    assert "Fatigue details" not in labels
    assert at.session_state["_material_tab"] == "Concrete"
    assert not at.exception


def test_auto_all_updates_concrete_while_mild_family_is_mounted():
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Both").run()
    _goto_material_tab(at, "Concrete")
    for key, value in {
        "conc_eps_c2": 4.0,
        "conc_eps_cu2": 6.0,
        "conc_n": 3.0,
        "sls_fctm": 1.0,
        "conc_Ec": 10.0,
    }.items():
        at.number_input(key=key).set_value(value).run()

    _goto_material_tab(at, "Mild steel")
    assert "conc_eps_c2" not in {widget.key for widget in at.number_input}
    at.button(key="auto_all_btn").click().run()

    expected = {
        "conc_eps_c2": 2.0,
        "conc_eps_cu2": 3.5,
        "conc_n": 2.0,
        "sls_fctm": 3.21,
        "conc_Ec": 34.1,
    }
    assert at.session_state["_material_tab"] == "Mild steel"
    for key, value in expected.items():
        assert at.session_state[key] == pytest.approx(value)
        assert at.session_state["_durable_input_scalars"][key] == pytest.approx(
            value
        )
    assert "_pending_input_events" not in at.session_state
    assert not at.exception


def test_pending_section_clear_is_inert_outside_its_owner_stage():
    at = _fresh()
    at.run()
    _goto_input_tab(at, "Section")
    at.button(key="clear_pts").click().run()
    assert any(button.key == "confirm_clear_pts" for button in at.button)

    _goto_input_tab(at, "Loads")
    assert not any(button.key == "confirm_clear_pts" for button in at.button)
    assert not at.session_state["corners_base"].empty

    _goto_input_tab(at, "Section")
    assert any(button.key == "confirm_clear_pts" for button in at.button)
    assert not at.exception


def test_interrupted_inputs_build_cannot_replace_the_last_complete_snapshot():
    at = _fresh()
    at.run()
    _goto_material_tab(at, "Concrete")
    at.number_input(key="conc_fck").set_value(55.0).run()
    assert at.session_state["_durable_input_scalars"]["conc_fck"] == 55.0

    # Reproduce the state left by a browser event that supersedes Inputs while
    # widgets are only partly reconstructed: a default-valued widget key exists,
    # but the build has not reached its commit point.
    at.session_state["_inputs_build_in_progress"] = True
    at.session_state["conc_fck"] = 30.0
    at.segmented_control(key="_main_page").set_value("Analysis").run()
    assert at.session_state["_durable_input_scalars"]["conc_fck"] == 55.0

    _goto_page(at, "Inputs")
    assert not at.exception
    assert at.session_state["conc_fck"] == 55.0
    assert at.session_state["_durable_input_scalars"]["conc_fck"] == 55.0


def test_interrupted_inputs_callback_cannot_commit_partial_widget_values():
    at = _fresh()
    at.run()
    _goto_material_tab(at, "Concrete")
    at.number_input(key="conc_fck").set_value(55.0).run()
    _goto_input_tab(at, "Section")

    # Quick Section is a callback on the still-visible Inputs page. It must still
    # navigate, but may not snapshot a partially reconstructed widget namespace.
    at.session_state["_inputs_build_in_progress"] = True
    at.session_state["conc_fck"] = 30.0
    at.button(key="open_qs").click().run()

    assert at.session_state["_main_page"] == "Analysis"
    assert at.session_state["_durable_input_scalars"]["conc_fck"] == 55.0
    assert at.session_state["conc_fck"] == 55.0
    assert not at.exception


def test_interrupted_inputs_recovery_replays_the_genuine_engineering_event():
    at = _fresh()
    at.run()
    _goto_material_tab(at, "Concrete")
    at.number_input(key="conc_fck").set_value(55.0).run()

    # The browser records the next widget event before the superseding rerun.
    # Recovery must reject partial defaults but retain this genuine 55 -> 60 edit.
    at.session_state["_inputs_build_in_progress"] = True
    at.number_input(key="conc_fck").set_value(60.0).run()

    assert at.session_state["conc_fck"] == 60.0
    assert at.session_state["_durable_input_scalars"]["conc_fck"] == 60.0
    assert "_pending_input_events" not in at.session_state
    assert not at.exception


def test_live_data_editor_event_is_not_reassigned_before_widget_mount():
    at = _fresh()
    at.run()
    _goto_input_tab(at, "Loads")

    # A browser data-editor edit is installed in widget state before its callback
    # journals the same payload.  Reassigning that live payload through Session
    # State before data_editor(data=...) mounts is rejected by Streamlit.
    editor_key = "plastic_cases_editor"
    at.session_state["_pending_input_events"] = {
        editor_key: copy.deepcopy(at.session_state[editor_key]),
    }
    at.run()

    assert not at.exception
    assert editor_key in at.session_state
    assert "_pending_input_events" not in at.session_state


def test_interrupted_inputs_recovery_preserves_the_new_tab_selection():
    at = _fresh()
    at.run()
    _goto_material_tab(at, "Concrete")
    at.number_input(key="conc_fck").set_value(55.0).run()
    section_tab = f"2 {chr(0x00B7)} Section"

    # Streamlit stores the tab event before beginning the replacement rerun.
    # Restore engineering state, but retain that just-recorded navigation value.
    at.session_state["_inputs_build_in_progress"] = True
    at.session_state["conc_fck"] = 30.0
    at.session_state["_input_tab"] = section_tab
    at.run()

    assert at.session_state["_input_tab"] == section_tab
    assert at.session_state["conc_fck"] == 55.0
    assert at.session_state["_durable_input_scalars"]["conc_fck"] == 55.0
    assert not at.exception

    _goto_material_tab(at, "Concrete")
    at.session_state["_inputs_build_in_progress"] = True
    at.session_state["conc_fck"] = 30.0
    at.session_state["_material_tab"] = "Prestressing steel"
    at.session_state["_material_tab_preference"] = "Prestressing steel"
    at.run()

    assert at.session_state["_material_tab"] == "Prestressing steel"
    assert at.session_state["conc_fck"] == 55.0
    assert not at.exception


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
    _set_and_click(at, "qs_back")
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


@pytest.mark.parametrize("view", ["Plastic Results", "Elastic Results"])
def test_stale_result_views_keep_the_calculated_section_geometry(view):
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Both").run()
    _calculate(at)
    _select_view(at, view)
    calculated_outline = _section_outline_from_result_view(at)

    changed = at.session_state["corners_base"].copy(deep=True)
    changed["x (mm)"] *= 1.25
    changed["y (mm)"] *= 1.25
    _replace_base_table(at, "corners_base", changed)
    assert (
        at.session_state["_latest_inputs"]["outer"]
        != at.session_state["result_input_snapshot"]["outer"]
    )

    _select_view(at, view)
    assert not at.exception
    assert _section_outline_from_result_view(at) == calculated_outline
    assert any(
        "inputs changed" in warning.value.lower()
        for warning in at.warning
    )


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
    # Enabling both component checks still leaves the current physical
    # shared-link authority missing.
    at.checkbox(key="shear_on").set_value(True).run()
    at.checkbox(key="torsion_on").set_value(True).run()
    assert any(
        f"{cross} Shared links / closed torsion stirrups present" in w.value
        for w in at.warning
    )

    # Selecting the shared physical link authority completes the preflight.
    at.checkbox(key="shear_links").set_value(True).run()
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
    _goto_material_tab(at, "Concrete")
    at.number_input(key="conc_fck").set_value(45.0).run()
    at.number_input(key="conc_gamma_c").set_value(0.5).run()
    _goto_material_tab(at, "Mild steel")
    at.number_input(key="mild_gamma_y").set_value(2.0).run()
    assert not at.exception
    _calculate(at)
    assert not at.exception
    assert "plastic" in at.session_state["results"]
    snapshot = at.session_state["result_input_snapshot"]
    assert snapshot["concrete"].gamma_c == pytest.approx(0.5)
    assert snapshot["steel"].gamma_y == pytest.approx(2.0)
    assert snapshot["concrete"].fcd == pytest.approx(
        snapshot["concrete"].alpha_cc * 45.0 / 0.5
    )
    assert snapshot["steel"].fytk / snapshot["steel"].gamma_y == pytest.approx(
        275.0
    )


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


def test_elastic_reports_output_only_stresses_and_complete_evidence():
    at = _fresh()
    at.run()
    _set_and_click(
        at, "calculate",
        ("radio", "mode", "Elastic"),
        ("number_input", "el_long_Mx", 400.0),
    )
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    assert e["converged"] is True
    assert e["stress_outputs"]["concrete"]["calculation_state"] == "CALCULATED"
    assert e["stress_outputs"]["reinforcement"]["calculation_state"] == "CALCULATED"
    assert e["stress_outputs"]["concrete"]["value"] > 0.0
    assert e["stress_outputs"]["reinforcement"]["value"] > 0.0
    assert not {"limit", "util", "status"} & set(e["stress_outputs"]["concrete"])
    assert "sls_limit_source" not in e
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
    output = e["crack_output"]
    assert set(output) == {"long_term", "short_term"}
    for duration in ("long_term", "short_term"):
        assert output[duration]["calculation_state"] == "NOT REQUESTED"
        assert output[duration]["criterion_mm"] == 0.0
        assert output[duration]["value"] is None
        assert output[duration]["ratio"] is None


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


def test_crack_output_and_candidate_table_are_retained_without_verdict():
    at = _fresh()
    at.run()
    _set_and_click(
        at, "calculate",
        ("radio", "mode", "Elastic"),
        ("number_input", "el_long_Mx", 400.0),
        ("checkbox", "sls_cw", True),
    )
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    assert set(e["crack_output"]) == {"long_term", "short_term"}
    for duration, output in e["crack_output"].items():
        assert output["duration"] == duration
        assert output["calculation_state"] == (
            "CALCULATED - NO LIMIT COMPARISON"
        )
        assert output["value"] > 0.0
        expected_label = (
            "Long-term" if duration == "long_term" else "Short-term"
        )
        assert output["case"].startswith(expected_label)
        assert output["governing"].startswith(("R", "P"))
        assert output["criterion_mm"] == 0.0
        assert output["ratio"] is None
        assert not {"limit", "util", "status"} & set(output)
    assert e["crack"]["candidates"]
    assert e["crack"]["candidates"][0]["wk"] == pytest.approx(e["crack"]["wk"])
    assert {"element_id", "x_mm", "y_mm", "area_mm2", "cover",
            "sigma_s", "ac_eff", "esm_ecm", "sr_max", "wk"} <= \
        e["crack"]["candidates"][0].keys()
    _select_view(at, "Elastic Results")
    assert any(
        "User limit: 0 mm; no comparison requested" in item.value
        for item in at.caption
    )
    assert not any("FAIL - Crack width" in item.value for item in at.error)


def test_independent_duration_crack_criteria_are_assessed_for_elastic_rows():
    import load_cases

    at = _fresh()
    at.run()
    _set(at, ("radio", "mode", "Elastic"))
    cases = at.session_state[load_cases.ELASTIC_TABLE_KEY].copy(deep=True)
    cases.at[0, "mx_long_ed_knm"] = 400.0
    cases.at[0, "calculate_crack_width"] = True
    _replace_case_table(at, load_cases.ELASTIC_TABLE_KEY, cases)
    _set(
        at,
        ("number_input", "sls_long_term_permitted_crack_width_mm", 0.001),
        ("number_input", "sls_short_term_permitted_crack_width_mm", 1.0),
    )
    _calculate(at)

    assert not at.exception
    outputs = at.session_state["results"]["elastic"]["crack_output"]
    long_term = outputs["long_term"]
    short_term = outputs["short_term"]
    assert long_term["calculation_state"] == "EXCEEDS USER-SPECIFIED LIMIT"
    assert long_term["criterion_mm"] == pytest.approx(0.001)
    assert long_term["ratio"] == pytest.approx(long_term["value"] / 0.001)
    assert long_term["criterion_source"] == (
        "User input - Analysis settings - long-term"
    )
    assert short_term["calculation_state"] == "WITHIN USER-SPECIFIED LIMIT"
    assert short_term["criterion_mm"] == pytest.approx(1.0)
    assert short_term["ratio"] == pytest.approx(short_term["value"] / 1.0)
    assert short_term["criterion_source"] == (
        "User input - Analysis settings - short-term"
    )
    for output in outputs.values():
        assert output["comparison_equation"] == "w_k / w_k,criterion"
        assert not {"status", "pass", "fail", "global_compliance"} & set(
            output
        )

    _select_view(at, "Elastic Results")
    assert any(
        "EXCEEDS USER-SPECIFIED LIMIT" in item.value
        and "User limit: 0.001 mm" in item.value
        for item in at.caption
    )

    _set(
        at,
        ("number_input", "sls_long_term_permitted_crack_width_mm", 1.0),
    )
    _select_view(at, "Elastic Results")
    assert any("press Calculate" in item.value for item in at.warning)


def test_no_crack_width_is_not_assessed_without_a_numerical_result():
    at = _fresh()
    at.run()
    _set_and_click(
        at, "calculate",
        ("radio", "mode", "Elastic"),
        ("number_input", "el_long_Mx", 0.0),
        ("number_input", "el_short_Mx", 0.0),
        ("checkbox", "sls_cw", True),
    )
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    assert e["crack"] is None and e["crack_short"] is None
    for output in e["crack_output"].values():
        assert output["calculation_state"] == "NOT ASSESSED"
        assert output["value"] is None
    assert "sls_limit_source" not in e
    _select_view(at, "Elastic Results")
    reasons = {
        output["reason"] for output in e["crack_output"].values()
        if output.get("reason")
    }
    assert reasons
    assert all(any(reason in item.value for item in at.info) for reason in reasons)
    assert not any(
        "No crack width: section uncracked or no reinforcement" in item.value
        for item in at.info
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
        ("selectbox", "sls_code", _SLS_DK),
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
        ("selectbox", "sls_code", _SLS_BASE),
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
        ("selectbox", "sls_code", _SLS_2023),
    )
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    assert e["crack_basis_key"] == _SLS_2023
    assert "2023" in e["crack_code"]
    assert e["crack"]["edition"] == "2023" and e["crack"]["kw"] == 1.7
    assert e["crack"]["wk"] > 0.0 and e["crack"]["k1_r"] >= 1.0


def test_bonded_tendon_ratio_invalidates_elastic_results_and_report():
    # xi enters the 2023 mixed-reinforcement crack equation. Editing it must make
    # both the elastic result and its generated report stale, and Calculate must
    # recompute rather than reuse the old elastic result object.
    at = _fresh_qs(mode="Elastic")
    _set_and_click(at, "qs_apply", ("number_input", "tnd_n", 4))
    _set_and_click(
        at,
        "calculate",
        ("number_input", "el_long_Mx", 400.0),
        ("checkbox", "sls_cw", True),
        ("selectbox", "sls_code", _SLS_2023),
        ("number_input", "sls_tendon_xi", 0.5),
    )
    assert not at.exception
    elastic_before = at.session_state["results"]["elastic"]
    wk_before = elastic_before["crack"]["wk"]

    _goto_page(at, "Report")
    at.session_state["_report_no_figures"] = True
    at.button(key="gen_report").click().run()
    assert "report_buffer" in at.session_state
    assert at.session_state["report_generation_record"]["result_source"] == (
        "reused-current-analysis-results"
    )
    assert not any("Report out of date" in w.value for w in at.warning)

    _goto_input_tab(at, "Analysis settings")
    _set(at, ("number_input", "sls_tendon_xi", 0.75))
    _select_view(at, "Elastic Results")
    assert any("press Calculate" in w.value for w in at.warning)
    _goto_page(at, "Report")
    assert any("Report out of date" in w.value for w in at.warning)

    _calculate(at)
    elastic_after = at.session_state["results"]["elastic"]
    assert elastic_after is not elastic_before
    assert elastic_after["crack"]["wk"] != pytest.approx(wk_before)


def test_crack_basis_widget_uses_only_stable_capability_keys():
    from sector import design_standards

    at = _fresh()
    at.run()
    box = at.selectbox(key="sls_code")
    assert box.options == [
        design_standards.get_design_basis(key).label
        for key in (_SLS_BASE, _SLS_DK, _SLS_2023)
    ]
    assert box.value == _SLS_BASE
    assert at.session_state["sls_code"] == _SLS_BASE


def test_heightened_crack_control_runs_once_and_its_inputs_mark_results_stale():
    import load_cases
    import project_io
    import reinforcement_table

    at = _fresh()
    at.run()
    bars = at.session_state["bars_base"].copy(deep=True)
    bars[reinforcement_table.SIZE_MODE] = reinforcement_table.AREA_MODE
    _replace_base_table(at, "bars_base", bars)
    cases = at.session_state[load_cases.ELASTIC_TABLE_KEY].copy(deep=True)
    reference_name = str(cases.loc[0, "name"])
    cases.at[0, "mx_long_ed_knm"] = 400.0
    cases.at[0, "calculate_crack_width"] = True
    _replace_case_table(at, load_cases.ELASTIC_TABLE_KEY, cases)
    _set_and_click(
        at,
        "calculate",
        ("radio", "mode", "Elastic"),
        ("selectbox", "sls_code", _SLS_DK),
        ("toggle", "sls_heightened_on", True),
        ("selectbox", "sls_heightened_reinforcement_surface", "ribbed"),
        (
            "number_input",
            "sls_heightened_effective_tensile_strength_mpa",
            2.9,
        ),
        (
            "number_input",
            "sls_heightened_permitted_crack_width_mm",
            0.2,
        ),
        (
            "number_input",
            "sls_heightened_fine_effective_tension_area_mm2",
            100000.0,
        ),
        (
            "number_input",
            "sls_heightened_coarse_effective_tension_area_mm2",
            150000.0,
        ),
    )

    assert not at.exception
    results = at.session_state["results"]
    heightened = results["heightened_crack_control"]
    assert heightened["basis_key"] == _SLS_DK
    assert heightened["formula_identity"] == "Formula 7.100 NA"
    assert heightened["reference_case_id"] == reference_name
    assert heightened["effective_tensile_strength_mpa"] == pytest.approx(2.9)
    assert heightened["fine"]["effective_tension_area_mm2"] == pytest.approx(
        100000.0
    )
    assert heightened["coarse"]["effective_tension_area_mm2"] == pytest.approx(
        150000.0
    )
    assert heightened["fine"]["required_reinforcement_area_mm2"] > 0.0
    assert heightened["coarse"]["required_reinforcement_area_mm2"] > 0.0
    assert heightened["provided_reinforcement_area_mm2"] > 0.0
    assert heightened["bar_diameter_mm"] > 0.0
    assert heightened["reinforcement_modulus_mpa"] > 0.0
    assert heightened["contributions"]
    assert all(
        row["diameter_source"] == "equivalent-area-fallback"
        for row in heightened["contributions"]
    )
    assert results["worked_example_selection"]["heightened_crack_control"] == {
        "result_key": "heightened_crack_control"
    }
    assert all(
        "heightened_crack_control" not in entry["results"]
        for entry in results["elastic_cases"]
    )
    overview = next(
        table.value
        for table in at.table
        if {"Check", "Governing action", "Status"}.issubset(table.value.columns)
    )
    heightened_summary = overview.loc[
        overview["Check"] == "DK heightened crack-control minimum"
    ]
    assert heightened_summary["Governing action"].tolist() == ["-"]

    _select_view(at, "Elastic Results")
    assert sum(
        item.value == "#### DK NA heightened crack control"
        for item in at.markdown
    ) == 1
    _set(
        at,
        (
            "number_input",
            "sls_heightened_coarse_effective_tension_area_mm2",
            175000.0,
        ),
    )
    _select_view(at, "Elastic Results")
    assert any("press Calculate" in item.value for item in at.warning)

    # A later reference state with no calculated ordinary crack evidence must
    # fail closed without replacing the last completed result or crashing the app.
    retained_result_hash = project_io.result_sha256(
        at.session_state["results"]
    )
    cases = at.session_state[load_cases.ELASTIC_TABLE_KEY].copy(deep=True)
    for key in (
        "n_long_ed_kn",
        "mx_long_ed_knm",
        "my_long_ed_knm",
        "n_short_ed_kn",
        "mx_short_ed_knm",
        "my_short_ed_knm",
    ):
        cases.at[0, key] = 0.0
    _replace_case_table(at, load_cases.ELASTIC_TABLE_KEY, cases)
    _calculate(at)

    assert not at.exception
    assert project_io.result_sha256(at.session_state["results"]) == (
        retained_result_hash
    )
    assert "Calculation blocked:" in at.session_state["_case_error"]
    assert any(
        "Calculation blocked:" in item.value
        for item in at.error
    )

    # Turning the optional calculation off and changing basis must not erase the
    # dormant user operands; returning to DK restores the exact prior value.
    _set(at, ("toggle", "sls_heightened_on", False))
    _set(at, ("selectbox", "sls_code", _SLS_2023))
    assert not any(
        widget.key and widget.key.startswith("sls_heightened_")
        for widgets in (at.toggle, at.selectbox, at.number_input)
        for widget in widgets
    )
    _set(at, ("selectbox", "sls_code", _SLS_DK))
    assert at.number_input(
        key="sls_heightened_coarse_effective_tension_area_mm2"
    ).value == pytest.approx(175000.0)


def test_persisted_enabled_heightened_config_is_hidden_and_rejected_for_2023():
    at = _fresh()
    seeded = {
        "mode": "Elastic",
        "sls_code": _SLS_2023,
        "sls_heightened_on": True,
        "sls_heightened_reference_case": "Elastic 1",
        "sls_heightened_reinforcement_surface": "ribbed",
        "sls_heightened_effective_tensile_strength_mpa": 2.9,
        "sls_long_term_permitted_crack_width_mm": 0.0,
        "sls_short_term_permitted_crack_width_mm": 0.0,
        "sls_heightened_permitted_crack_width_mm": 0.2,
        "sls_heightened_fine_effective_tension_area_mm2": 100000.0,
        "sls_heightened_coarse_effective_tension_area_mm2": 150000.0,
    }
    for key, value in seeded.items():
        at.session_state[key] = value
    at.run()

    assert not at.exception
    assert at.selectbox(key="sls_code").value == _SLS_2023
    assert not any(
        widget.key and widget.key.startswith("sls_heightened_")
        for widgets in (at.toggle, at.selectbox, at.number_input)
        for widget in widgets
    )
    _calculate(at)
    assert "results" not in at.session_state
    assert any(
        "Heightened crack control is available only with the first-generation "
        "DK NA:2024 design basis" in item.value
        for item in at.error
    )


def test_blocking_issues_are_separate_and_navigate_to_the_exact_input_stage():
    at = _fresh()
    seeded = {
        "mode": "Elastic",
        "sls_code": _SLS_DK,
        "sls_heightened_on": True,
        "sls_heightened_reinforcement_surface": "ribbed",
        "sls_heightened_effective_tensile_strength_mpa": 0.0,
        # Zero disables each ordinary comparison but remains invalid for the
        # separately enabled heightened Formula 7.100 NA operand.
        "sls_long_term_permitted_crack_width_mm": 0.0,
        "sls_short_term_permitted_crack_width_mm": 0.0,
        "sls_heightened_permitted_crack_width_mm": 0.0,
        "sls_heightened_fine_effective_tension_area_mm2": 0.0,
        "sls_heightened_coarse_effective_tension_area_mm2": 0.0,
        "_material_tab": "Mild steel",
    }
    for key, value in seeded.items():
        at.session_state[key] = value
    at.run()

    # A retained pre-snapshot result is a supported hot-reload state. Current
    # blockers and their navigation controls must remain visible even though the
    # stale input-dependent result itself is suppressed.
    at.session_state["results"] = {"legacy_hot_reload": True}
    at.session_state["result_sig"] = "legacy-signature"
    try:
        del at.session_state["result_input_snapshot"]
    except KeyError:
        pass
    _calculate(at)

    errors = [item.value for item in at.error]
    assert any("cannot be matched to its inputs" in message for message in errors)
    assert "Effective tensile strength must be a positive finite number" in errors
    assert "Fine-system effective tension area must be a positive finite number" in errors
    assert "Coarse-system effective tension area must be a positive finite number" in errors
    assert len(
        [message for message in errors if "positive finite number" in message]
    ) == 4
    assert any(
        button.key and button.key.endswith("heightened-2")
        for button in at.button
    )

    at.button(
        key="analysis-input-issue-1-heightened-1"
    ).click().run()

    stage = f"1 {chr(0x00B7)} Analysis settings"
    assert at.session_state["_main_page"] == "Inputs"
    assert at.session_state["_input_tab"] == stage
    assert at.session_state["_material_tab"] == "Mild steel"
    durable = at.session_state["_durable_input_scalars"]
    assert durable["_input_tab"] == stage
    assert durable["_material_tab"] == "Mild steel"
    assert durable["_material_tab_preference"] == "Mild steel"
    assert at.number_input(key="sls_heightened_effective_tensile_strength_mpa")
    assert any(
        "Correction target: **Effective tensile strength**" in item.value
        for item in at.info
    )

def test_material_blocker_navigates_to_its_material_family(monkeypatch):
    import material_catalog

    catalogue = material_catalog.default_catalog("mild")
    catalogue, added_id = material_catalog.add_entry(catalogue, "mild")
    assert added_id == "M2"
    catalogue["items"][1]["description"] = "force-invalid-definition"
    original = material_catalog.build_material

    def fail_marked_definition(entry, kind):
        if entry.get("description") == "force-invalid-definition":
            raise ValueError("test-invalid material law")
        return original(entry, kind)

    monkeypatch.setattr(material_catalog, "build_material", fail_marked_definition)
    at = _fresh()
    at.session_state[material_catalog.MILD_CATALOG_KEY] = catalogue
    at.session_state["_mild_catalog_selected"] = "M1"
    at.run()
    _goto_page(at, "Analysis")
    # Simulate an interrupted Inputs edit that would otherwise replay M1 over
    # the authoritative Go-to destination during returning-state restoration.
    at.session_state["_pending_input_events"] = {
        "_mild_catalog_selected": "M1",
    }

    assert any(
        "Invalid material definition: M2: test-invalid material law" in item.value
        for item in at.error
    )
    at.button(
        key="analysis-input-issue-1-material-definition-1"
    ).click().run()

    material_stage = f"3 {chr(0x00B7)} Material parameters"
    assert at.session_state["_main_page"] == "Inputs"
    assert at.session_state["_input_tab"] == material_stage
    assert at.session_state["_material_tab"] == "Mild steel"
    assert at.session_state["_mild_catalog_selected"] == "M2"
    assert at.session_state["_durable_input_scalars"][
        "_material_tab"
    ] == "Mild steel"
    assert at.session_state["_durable_input_scalars"][
        "_material_tab_preference"
    ] == "Mild steel"
    assert at.session_state["_durable_input_scalars"][
        "_mild_catalog_selected"
    ] == "M2"
    assert at.selectbox(key="_mild_catalog_selected").value == "M2"
    assert "_pending_input_events" not in at.session_state
    assert any(
        "Opened **Material parameters / Mild steel**" in item.value
        for item in at.info
    )


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
        ("selectbox", "sls_code", _SLS_DK),
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
    _goto_input_tab(at, "Loads")
    md = "\n".join(m.value for m in at.markdown)
    assert "Modular ratios" in md
    assert "| M1 - B550 reinforcement | 200.0 | 5.000 | 15.000 |" in md


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
    _goto_input_tab(at, "Loads")
    md = "\n".join(m.value for m in at.markdown)
    assert "| P1 - Prestressing steel | 195.0 | 5.000 | 5.000 |" in md


def test_tendon_stress_is_an_output_without_a_limit():
    at = _fresh_qs(mode="Elastic")
    _set_and_click(at, "qs_apply", ("number_input", "tnd_n", 3))
    _calculate(at)
    output = at.session_state["results"]["elastic"]["stress_outputs"]["prestress"]
    assert output["calculation_state"] == "CALCULATED"
    assert math.isfinite(output["value"])
    assert not {"limit", "util", "status", "criterion"} & set(output)


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
