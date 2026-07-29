"""Headless smoke tests for the Streamlit app via Streamlit's AppTest.

These run the app script in-process (no browser), exercise the Calculate flow
for each analysis mode, and assert it produces results without error.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import math
import pathlib
import re
import sys
import time
from types import SimpleNamespace

import numpy as np
import pytest

from streamlit.testing.v1 import AppTest
from sector import bridge, multidirectional, sls

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))   # so `import sector_app` / `project_io` works standalone

APP = str(ROOT / "app" / "sector_app.py")

from app_case_inputs import apply_case_changes, first_case_value  # noqa: E402

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
                "sls_tendon_bond", "sls_tendon_xi",
                "sls_criterion_mode", "sls_prestress_class",
                "sls_protection_class", "sls_exposure_class",
                "sls_exposure_context", "sls_check_appearance",
                "sls_appearance_limit", "sls_check_durability",
                "sls_decompression_applicability",
                "sls_project_characteristic_limit",
                "sls_project_frequent_limit",
                "sls_project_quasi_permanent_limit",
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


def test_loading_partial_current_project_clears_crack_routing_and_bond_inputs():
    import json
    import project_io

    at = _fresh()
    at.run()
    at.session_state["_pending_project"] = project_io.dump_project(
        {},
        {
            "sls_tendon_bond": "Ribbed / high bond (k1 = 0.8)",
            "sls_tendon_xi": 0.65,
        },
    )
    at.run()
    assert not at.exception
    assert at.session_state["sls_tendon_bond"] == (
        "Ribbed / high bond (k1 = 0.8)"
    )
    assert at.session_state["sls_tendon_xi"] == pytest.approx(0.65)

    # External callers may still provide a valid current-version partial file.
    # Loading it is a whole-input replacement and must not retain the prior
    # project's favourable tendon properties in either live or durable state.
    at.session_state["_pending_project"] = json.dumps({
        "format": project_io.FORMAT,
        "version": project_io.VERSION,
        "tables": {},
        "scalars": {
            "sls_cw": True,
            "sls_code": "EN 1992-1-1:2023",
        },
    })
    at.run()

    assert not at.exception
    assert at.session_state["sls_tendon_bond"] == (
        project_io.DEFAULT_SLS_TENDON_BOND
    )
    assert at.session_state["sls_tendon_xi"] == pytest.approx(
        project_io.DEFAULT_SLS_TENDON_XI
    )
    assert at.session_state["sls_criterion_mode"] == (
        sls.CRITERION_MODE_LEGACY
    )
    durable = at.session_state["_durable_input_scalars"]
    assert durable["sls_tendon_bond"] == project_io.DEFAULT_SLS_TENDON_BOND
    assert durable["sls_tendon_xi"] == pytest.approx(
        project_io.DEFAULT_SLS_TENDON_XI
    )
    assert durable["sls_criterion_mode"] == sls.CRITERION_MODE_LEGACY


def test_loading_v17_boolean_crack_json_is_rejected_before_session_apply():
    import project_io

    at = _fresh()
    at.run()
    before_limit = at.session_state["sls_wk_limit"]
    at.session_state["_pending_project"] = json.dumps({
        "format": project_io.FORMAT,
        "version": 17,
        "tables": {},
        "scalars": {
            "sls_code": "EN 1992-1-1:2023",
            "sls_criterion_mode": sls.CRITERION_MODE_STANDARD,
            "sls_prestress_class": sls.PRESTRESS_BONDED,
            "sls_wk_limit": True,
            "sls_tendon_xi": True,
        },
    })

    at.run()

    assert not at.exception
    assert at.session_state["sls_wk_limit"] == before_limit
    assert not isinstance(at.session_state["sls_wk_limit"], bool)
    assert not isinstance(
        at.session_state["_durable_input_scalars"]["sls_wk_limit"],
        bool,
    )
    level, message = at.session_state["_project_msg"]
    assert level == "error"
    assert "sls_tendon_xi" in message or "sls_wk_limit" in message


def test_loading_structured_crack_snapshot_restores_audit_state_not_live_results():
    import load_cases
    import project_io

    tables = {
        load_cases.ELASTIC_TABLE_KEY: load_cases.normalise_table([{
            "name": "SLS-QP",
            "long_combination": sls.COMBINATION_QUASI_PERMANENT,
            "total_combination": sls.COMBINATION_CHARACTERISTIC,
            "mx_long_ed_knm": 80.0,
            "mx_short_ed_knm": 20.0,
            "check_crack_width": True,
        }], load_cases.ELASTIC_TABLE_KEY),
    }
    scalars = {
        "mode": "Elastic",
        "sls_code": "EN 1992-1-1:2023",
        "sls_criterion_mode": sls.CRITERION_MODE_STANDARD,
        "sls_prestress_class": sls.PRESTRESS_BONDED,
        "sls_protection_class": sls.PROTECTION_LEVEL_2_OR_3,
        "sls_exposure_class": sls.EXPOSURE_XC2_XC4,
        "sls_exposure_context": "XC3 / durability",
        "sls_check_durability": True,
        "sls_wk_limit": 0.30,
        "sls_decompression_applicability": sls.DECOMPRESSION_NOT_REQUIRED,
    }
    digest = project_io.input_sha256(tables, scalars)
    crack_control = {
        "cases": [{
            "case": "SLS-QP",
            "assessment": {
                "status": "OK",
                "verdict": "PASS",
                "case": "QP",
                "required_combination": sls.COMBINATION_QUASI_PERMANENT,
                "value": 0.22,
                "limit": 0.30,
            },
            "responses": [{
                "name": "QP",
                "wk_mm": 0.22,
                "acceptance_role": "criterion input",
                "context": {
                    "combination": sls.COMBINATION_QUASI_PERMANENT,
                    "response_id": "qp",
                    "solver_provenance": {"state": "long"},
                },
            }],
        }],
    }
    text = project_io.dump_project(
        tables,
        scalars,
        calculation={
            "performed_at_utc": "2026-07-27T10:00:00+00:00",
            "sector_version": "0.91",
            "source_revision": "e" * 40,
            "input_sha256": digest,
            "crack_control": crack_control,
        },
    )
    payload = json.loads(text)
    stale_case = payload["calculation"]["crack_control"]["cases"][0]
    stale_case["responses"][0]["wk_mm"] = None
    stale_case["responses"][0]["result_validation"] = (
        "Injected rejected response in loaded audit snapshot."
    )
    text = json.dumps(payload)
    expected_record = project_io.project_provenance(text)[
        "calculation"
    ]["crack_control"]

    at = _fresh()
    at.run()
    at.session_state["results"] = {"stale": True}
    at.session_state["_pending_project"] = text
    at.run()

    assert not at.exception
    assert "results" not in at.session_state
    assert at.session_state["sls_criterion_mode"] == (
        sls.CRITERION_MODE_STANDARD
    )
    assert at.session_state["sls_exposure_context"] == "XC3 / durability"
    assert at.session_state["sls_protection_class"] == (
        sls.PROTECTION_LEVEL_2_OR_3
    )
    assert at.session_state["sls_exposure_class"] == sls.EXPOSURE_XC2_XC4
    elastic = at.session_state[load_cases.ELASTIC_TABLE_KEY]
    assert elastic.loc[0, "long_combination"] == (
        sls.COMBINATION_QUASI_PERMANENT
    )
    loaded_record = at.session_state["calculation_record"]["crack_control"]
    assert loaded_record == expected_record
    loaded_assessment = loaded_record["cases"][0]["assessment"]
    assert loaded_assessment["status"] == "NOT ASSESSED"
    assert loaded_assessment["verdict"] == "REVIEW"
    assert loaded_assessment["value"] is None
    assert loaded_assessment["publication_validation"]["status"] == "REJECTED"
    assert at.session_state["calculation_record"]["matches_saved_inputs"] is True


def test_about_panel_shows_version_author_and_licensee():
    # The About panel carries the single-source release and ownership metadata.
    at = _fresh()
    at.run()
    _goto_input_tab(at, "Project & report")
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
    # Result provenance is added only for an enabled crack-control calculation;
    # an ordinary elastic run must not persist an irrelevant REVIEW snapshot.
    assert "crack_control" not in at.session_state["calculation_record"]


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
    assert f"NA angle ({chr(0x00B0)})" in active
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
    _goto_input_tab(at, "Project & report")
    assert any("hash verified" in caption.value for caption in at.caption)


def test_loaded_fatigue_conformance_snapshot_is_retained_and_visible():
    import project_io

    at = _fresh()
    at.run()
    tables = {
        key: at.session_state[key]
        for key in project_io.PROJECT_TABLE_KEYS
        if key in at.session_state
    }
    scalars = {
        key: at.session_state[key]
        for key in project_io.SCALAR_KEYS
        if key in at.session_state
    }
    scalars["design_methodology"] = bridge.COMPONENT_METHODS
    fatigue_record = _fatigue_bound_snapshot()
    assert fatigue_record is not None
    digest = project_io.input_sha256(tables, scalars)
    source = project_io.dump_project(
        tables,
        scalars,
        calculation={
            "input_sha256": digest,
            "fatigue_conformance": fatigue_record,
        },
    )

    at.session_state["_pending_project"] = source
    at.run()

    assert not at.exception
    assert at.session_state["calculation_record"][
        "fatigue_conformance"
    ] == fatigue_record
    _goto_input_tab(at, "Project & report")
    captions = " | ".join(item.value for item in at.caption)
    assert "Recorded fatigue conformance" in captions
    assert "APPROVED CUSTOM PASS" in captions
    assert "gamma_s=0.5" in captions
    assert "gamma_c,fat=2" in captions
    assert "Miner C=100" in captions
    assert bridge.COMPONENT_METHODS in captions
    assert "DB-FAT-21 / checker approval" in captions
    assert "AUTH-SN-7 / checker approval" in captions


def test_app_restores_fatigue_inputs_into_the_ui():
    import fatigue_inputs
    import project_io

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
            fatigue_inputs.BASIS_KEY:
                fatigue_inputs.default_basis(),
            "fatigue_on": True,
            "fatigue_factor_mode": fatigue_inputs.FACTOR_MODE_PRESET,
            "fatigue_gamma0": 1.0,
            "fatigue_gamma3": 1.0,
            "fatigue_gamma_s": 1.32,
            "fatigue_gamma_c": 1.595,
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
        fatigue_inputs.EC2_2005_DKNA
    )
    assert at.selectbox(key="fatigue_factor_mode").value == (
        fatigue_inputs.FACTOR_MODE_PRESET
    )
    assert "fatigue_spectrum_editor" in at.session_state
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


def test_bridge_methodology_owns_routes_and_defaults_to_blocking_gate():
    import bridge_inputs
    import fatigue_inputs

    at = _fresh().run()
    at.selectbox(key="design_methodology").set_value(
        bridge.EN1992_2_BASE
    ).run()

    assert not at.exception
    assert at.selectbox(key="fatigue_edition").value == (
        fatigue_inputs.EC2_2_2005_AC
    )
    assert at.selectbox(key="sls_code").value == (
        "DS/EN 1992-2:2005 + AC:2008"
    )
    assert at.selectbox(key="sls_criterion_mode").value == (
        sls.CRITERION_MODE_STANDARD
    )
    assert all(
        key in at.session_state
        for key in bridge_inputs.TABLE_KEYS
    )

    _calculate(at)
    payload = at.session_state["results"]["bridge_methodology"]

    assert payload["active"] is True
    assert payload["status"] != bridge.STATUS_PASS
    calculation_bridge = at.session_state["calculation_record"][
        "bridge_methodology"
    ]
    assert calculation_bridge["publication_validation"]["status"] == (
        "ACCEPTED"
    )
    assert at.session_state["result_input_snapshot"][
        "design_methodology"
    ] == bridge.EN1992_2_BASE
    assert all(
        check["status"] == bridge.STATUS_NOT_ASSESSED
        for check in payload["checks"]
    )
    _select_view(at, "Bridge Methodology")
    assert any(
        "NOT ASSESSED" in warning.value
        for warning in at.warning
    )

    _goto_page(at, "Inputs")
    at.selectbox(key="design_methodology").set_value(
        bridge.COMPONENT_METHODS
    ).run()

    assert not at.exception
    assert at.session_state["fatigue_concrete_miner_basis"] == (
        fatigue_inputs.MINER_BASIS_NOT_ESTABLISHED
    )


def test_danish_bridge_method_exposes_noninferred_typed_project_basis():
    from sector import danish_bridge

    at = _fresh().run()
    at.selectbox(key="design_methodology").set_value(
        bridge.EN1992_2_DK_NA
    ).run()

    assert not at.exception
    assert at.selectbox(key="sls_code").value == bridge.EN1992_2_DK_NA
    assert at.session_state["_latest_inputs"]["sls_dk_na"] is True
    assert at.session_state["_latest_inputs"]["sls_edition"] == (
        sls.EDITION_BRIDGE_DK_2015
    )
    for key in (
        "bridge_asset_class",
        "bridge_infrastructure_manager",
        "bridge_environment_class",
        "bridge_departure_applicability",
        "bridge_control_class",
        "bridge_consequence_class",
        "bridge_deicing_applicability",
    ):
        assert at.selectbox(key=key).value == danish_bridge.NOT_ESTABLISHED
    for key in (
        "bridge_manager_source",
        "bridge_project_basis_source",
        "bridge_departure_source",
        "bridge_authority_approval_reference",
        "bridge_environment_source",
        "bridge_deicing_source",
    ):
        assert at.text_input(key=key).value == ""
    assert at.number_input(key="bridge_alpha_ct").value == 1.0
    assert any(
        "declared model must exactly match" in caption.value
        for caption in at.caption
    )

    _calculate(at)
    payload = at.session_state["results"]["bridge_methodology"]
    project_basis = next(
        row for row in payload["checks"]
        if row["check_id"] == "dk_project_basis"
    )
    assert payload["methodology"] == bridge.EN1992_2_DK_NA
    assert payload["evidence_schema"] == bridge.DANISH_BRIDGE_EVIDENCE_SCHEMA
    assert payload["danish_basis"]["asset_class"] == (
        danish_bridge.NOT_ESTABLISHED
    )
    assert project_basis["status"] == bridge.STATUS_NOT_ASSESSED
    assert "Select the bridge class" in project_basis["reason"]
    calculation_bridge = at.session_state["calculation_record"][
        "bridge_methodology"
    ]
    assert calculation_bridge["publication_validation"]["status"] == (
        "ACCEPTED"
    )


def test_danish_bridge_applies_related_dk_na_crack_numerics():
    def calculated(methodology):
        at = _fresh().run()
        at.selectbox(key="design_methodology").set_value(methodology).run()
        _set_and_click(
            at,
            "calculate",
            ("radio", "mode", "Elastic"),
            ("number_input", "el_long_Mx", 400.0),
            ("number_input", "el_short_Mx", 150.0),
            ("checkbox", "sls_cw", True),
        )
        assert not at.exception
        current = at.session_state["result_input_snapshot"]
        elastic = at.session_state["results"]["elastic"]
        assert elastic["crack"] is not None
        assert elastic["crack_short"] is not None
        return current, elastic, at.session_state["calculation_record"]

    base_inputs, inherited, _base_record = calculated(
        bridge.EN1992_2_BASE
    )
    dk_inputs, danish, calculation_record = calculated(
        bridge.EN1992_2_DK_NA
    )

    assert base_inputs["sls_dk_na"] is False
    assert inherited.get("crack_coarse") is None
    assert inherited.get("crack_short_coarse") is None
    assert dk_inputs["sls_dk_na"] is True
    assert danish["crack_coarse"] is not None
    assert danish["crack_short_coarse"] is not None
    assert danish["crack"]["wk"] != pytest.approx(
        inherited["crack"]["wk"]
    )
    assert danish["crack_short"]["wk"] != pytest.approx(
        inherited["crack_short"]["wk"]
    )
    assert danish["crack_numerical_method"][
        "schema"
    ] == sls.CRACK_NUMERICAL_METHOD_SCHEMA
    assert danish["crack_numerical_method"]["dk_na_applied"] is True
    assert danish["crack_numerical_method"]["systems"] == [
        "fine",
        "coarse",
    ]
    assert calculation_record["crack_control"][
        "numerical_method"
    ] == danish["crack_numerical_method"]


def test_danish_bridge_uncracked_keeps_four_not_applicable_responses():
    at = _fresh().run()
    at.selectbox(key="design_methodology").set_value(
        bridge.EN1992_2_DK_NA
    ).run()
    _set_and_click(
        at,
        "calculate",
        ("radio", "mode", "Elastic"),
        ("number_input", "el_long_Mx", 1.0),
        ("number_input", "el_short_Mx", 0.0),
        ("checkbox", "sls_cw", True),
    )

    assert not at.exception
    elastic = at.session_state["results"]["elastic"]
    assert elastic["cracked"] is False
    required = {
        "Long-term (fine)",
        "Total (fine)",
        "Long-term (coarse)",
        "Total (coarse)",
    }
    assert set(elastic["crack_responses"]) == required
    assert all(
        elastic["crack_responses"][name] is None
        for name in required
    )
    assert set(elastic["crack_dispositions"]) == required
    assert all(
        elastic["crack_dispositions"][name]["status"]
        == "NOT APPLICABLE"
        for name in required
    )
    crack_record = at.session_state["calculation_record"][
        "crack_control"
    ]
    assert crack_record["numerical_method"]["schema"] == (
        sls.CRACK_NUMERICAL_METHOD_SCHEMA
    )
    assert {
        response["name"]
        for response in crack_record["cases"][0]["responses"]
    } == required


def test_danish_bridge_stale_base_crack_session_fails_closed_in_ui():
    at = _fresh().run()
    at.selectbox(key="design_methodology").set_value(
        bridge.EN1992_2_DK_NA
    ).run()
    _set_and_click(
        at,
        "calculate",
        ("radio", "mode", "Elastic"),
        ("number_input", "el_long_Mx", 400.0),
        ("number_input", "el_short_Mx", 150.0),
        ("checkbox", "sls_cw", True),
    )
    assert not at.exception
    stale = copy.deepcopy(at.session_state["results"])
    stale["elastic"].pop("crack_numerical_method")
    at.session_state["results"] = stale

    _select_view(at, "Elastic Results")

    assert not at.exception
    assert any(
        "Numerical crack-method evidence rejected" in warning.value
        for warning in at.warning
    )
    assert not any(
        "PASS - Crack width" in success.value
        for success in at.success
    )


def test_bridge_method_switch_invalidates_base_crack_cache():
    at = _fresh().run()
    at.selectbox(key="design_methodology").set_value(
        bridge.EN1992_2_BASE
    ).run()
    _set_and_click(
        at,
        "calculate",
        ("radio", "mode", "Elastic"),
        ("number_input", "el_long_Mx", 400.0),
        ("number_input", "el_short_Mx", 150.0),
        ("checkbox", "sls_cw", True),
    )
    base_sig = at.session_state["result_elastic_sig"]
    base_width = at.session_state["results"]["elastic"]["crack"]["wk"]

    _goto_page(at, "Inputs")
    at.selectbox(key="design_methodology").set_value(
        bridge.EN1992_2_DK_NA
    ).run()
    _calculate(at)

    assert not at.exception
    assert at.session_state["result_elastic_sig"] != base_sig
    elastic = at.session_state["results"]["elastic"]
    assert elastic["crack"]["wk"] != pytest.approx(base_width)
    assert elastic["crack_coarse"] is not None
    assert elastic["crack_numerical_method"]["dk_na_applied"] is True


def test_danish_crack_toggle_invalidates_elastic_context_cache_both_ways():
    at = _fresh().run()
    at.selectbox(key="design_methodology").set_value(
        bridge.EN1992_2_DK_NA
    ).run()
    _set_and_click(
        at,
        "calculate",
        ("radio", "mode", "Elastic"),
        ("number_input", "el_long_Mx", 400.0),
        ("number_input", "el_short_Mx", 150.0),
        ("checkbox", "sls_cw", True),
    )

    assert not at.exception
    enabled_sig = at.session_state[
        "result_elastic_case_context_sig"
    ]
    enabled = at.session_state["results"]["elastic"]
    assert enabled["show_cw"] is True
    assert enabled["crack_numerical_method"]["dk_na_applied"] is True

    _set(at, ("checkbox", "sls_cw", False))
    _calculate(at)

    assert not at.exception
    disabled_sig = at.session_state[
        "result_elastic_case_context_sig"
    ]
    assert disabled_sig != enabled_sig
    disabled = at.session_state["results"]["elastic"]
    assert disabled["show_cw"] is False
    assert disabled["crack_numerical_method"] is None
    assert disabled["crack_code"] is None

    _set(at, ("checkbox", "sls_cw", True))
    _calculate(at)

    assert not at.exception
    reenabled_sig = at.session_state[
        "result_elastic_case_context_sig"
    ]
    assert reenabled_sig != disabled_sig
    reenabled = at.session_state["results"]["elastic"]
    assert reenabled["show_cw"] is True
    assert reenabled["crack_numerical_method"]["dk_na_applied"] is True
    assert set(reenabled["crack_responses"]) == {
        "Long-term (fine)",
        "Total (fine)",
        "Long-term (coarse)",
        "Total (coarse)",
    }


def test_torsion_live_caption_prints_actual_danish_alpha_ct():
    at = _fresh().run()
    at.selectbox(key="design_methodology").set_value(
        bridge.EN1992_2_DK_NA
    ).run()
    _set_and_click(
        at,
        "calculate",
        ("number_input", "bridge_alpha_ct", 0.8),
        ("checkbox", "torsion_on", True),
        ("number_input", "torsion_T", 20.0),
    )

    assert not at.exception
    torsion = at.session_state["results"]["torsion"]
    assert torsion["fctd"] == pytest.approx(
        0.8 * torsion["fctk_005"] / torsion["gamma_ct"]
    )
    assert torsion["alpha_ct"] == pytest.approx(0.8)

    _select_view(at, "Torsion")
    captions = " | ".join(item.value for item in at.caption)
    assert "alpha_ct = 0.800" in captions
    assert (
        f"0.800 x {torsion['fctk_005']:.3f} / "
        f"{torsion['gamma_ct']:.3f} = {torsion['fctd']:.3f} MPa"
    ) in captions
    assert torsion["material_factor_basis"]["reference"] in captions


def test_bridge_view_surfaces_current_methodology_mismatch(monkeypatch):
    import sector_app

    rendered = {"errors": [], "info": []}
    fake_st = SimpleNamespace(
        info=lambda message, **_kwargs: rendered["info"].append(message),
        error=lambda message, **_kwargs: rendered["errors"].append(message),
        success=lambda *_args, **_kwargs: None,
        warning=lambda *_args, **_kwargs: None,
        caption=lambda *_args, **_kwargs: None,
        markdown=lambda *_args, **_kwargs: None,
        dataframe=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(sector_app, "st", fake_st)

    sector_app.bridge_methodology_view(
        {"design_methodology": bridge.COMPONENT_METHODS},
        {"bridge_methodology": _bridge_bound_snapshot()},
    )

    assert any(
        message.startswith("INVALID -")
        for message in rendered["errors"]
    )
    assert any(
        "conflicts with the calculation input snapshot" in message
        for message in rendered["errors"]
    )
    assert rendered["info"] == []


@pytest.mark.parametrize(
    ("attack", "expected"),
    [
        ("stale_standard", "fatigue.gamma_c"),
        ("omitted_gamma_c", "IDs/cardinality"),
        ("stale_gamma_ff", "fatigue_gamma_ff"),
        ("stale_basis", "fatigue basis"),
    ],
)
def test_bridge_view_surfaces_fatigue_correlation_rejection(
    attack,
    expected,
    monkeypatch,
):
    import contextlib
    import fatigue_inputs
    import sector_app

    rendered = {"errors": [], "info": []}
    fake_st = SimpleNamespace(
        info=lambda message, **_kwargs: rendered["info"].append(message),
        error=lambda message, **_kwargs: rendered["errors"].append(message),
        success=lambda *_args, **_kwargs: None,
        warning=lambda *_args, **_kwargs: None,
        caption=lambda *_args, **_kwargs: None,
        markdown=lambda *_args, **_kwargs: None,
        dataframe=lambda *_args, **_kwargs: None,
        expander=lambda *_args, **_kwargs: contextlib.nullcontext(),
    )
    monkeypatch.setattr(sector_app, "st", fake_st)

    current_scalars = _bridge_fatigue_publication_scalars(custom=True)
    if attack == "stale_standard":
        record = _bridge_concrete_fatigue_snapshot(
            _bridge_fatigue_publication_scalars()
        )
    elif attack == "stale_gamma_ff":
        current_scalars = _bridge_fatigue_publication_scalars()
        current_scalars["fatigue_gamma_ff"] = 2.0
        record = _bridge_concrete_fatigue_snapshot(
            _bridge_fatigue_publication_scalars()
        )
    elif attack == "stale_basis":
        record = _bridge_concrete_fatigue_snapshot(current_scalars)
        current_scalars[fatigue_inputs.BASIS_KEY] = {
            **fatigue_inputs.default_basis(),
            "authority": fatigue_inputs.AUTHORITY_VD,
            "method": fatigue_inputs.METHOD_VD_FLM4,
            "spectrum_source": "VD project basis section 6.8",
            "cycle_count_source": "Traffic register T-04",
        }
    else:
        record = _bridge_concrete_fatigue_snapshot(current_scalars)
        concrete = next(
            check for check in record["checks"]
            if check["check_id"] == "concrete_fatigue"
        )
        row = concrete["evidence"][0]
        row["fatigue_parameter_conformance"] = [
            parameter
            for parameter in row["fatigue_parameter_conformance"]
            if parameter["parameter_id"] != "fatigue.gamma_c"
        ]
        row["status"] = bridge.STATUS_PASS
        concrete["status"] = bridge.STATUS_PASS
        record["status"] = bridge.STATUS_PASS
        record["evidence_fingerprint"] = (
            bridge.bridge_evidence_fingerprint(
                record["checks"],
                record["configuration_errors"],
            )
        )
    sector_app.bridge_methodology_view(
        current_scalars,
        {"bridge_methodology": record},
    )

    assert any(
        message.startswith("INVALID -")
        for message in rendered["errors"]
    )
    assert any(
        expected in message
        for message in rendered["errors"]
    )
    assert rendered["info"] == []


def test_standard_miner_custom_c_is_editable_warned_and_round_trips():
    import fatigue_analysis
    import fatigue_inputs
    import project_io

    at = _fresh().run()
    at.toggle(key="fatigue_on").set_value(True).run()
    at.selectbox(key="design_methodology").set_value(
        bridge.EN1992_2_BASE
    ).run()

    standard_c = at.number_input(key="fatigue_concrete_c")
    assert standard_c.value == pytest.approx(14.0)
    assert standard_c.disabled is False
    assert at.session_state["fatigue_concrete_miner_basis"] == (
        fatigue_inputs.MINER_BASIS_BRIDGE_STANDARD
    )

    at.number_input(key="fatigue_concrete_c").set_value(100.0).run()
    assert at.number_input(key="fatigue_concrete_c").value == pytest.approx(
        100.0
    )
    assert any(
        "does not conform to prescribed value = 14" in warning.value
        for warning in at.warning
    )

    standard_saved = project_io.dump_project(
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
    _tables, standard_restored = project_io.parse_project(standard_saved)
    assert standard_restored["fatigue_concrete_c"] == 100.0
    assert standard_restored["fatigue_concrete_miner_basis"] == (
        fatigue_inputs.MINER_BASIS_BRIDGE_STANDARD
    )

    at.selectbox(key="fatigue_concrete_method").set_value(
        fatigue_analysis.CONCRETE_PROJECT_MINER
    ).run()
    assert at.number_input(key="fatigue_concrete_c").disabled is False
    assert at.text_input(key="fatigue_concrete_miner_source").disabled is False
    assert at.session_state["fatigue_concrete_miner_basis"] == (
        fatigue_inputs.MINER_BASIS_PROJECT_SN_RELATION
    )

    at.number_input(key="fatigue_concrete_c").set_value(100.0).run()
    at.text_input(key="fatigue_concrete_miner_source").set_value(
        "AUTH-SN-7 / checker approval"
    ).run()
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
    _tables, restored = project_io.parse_project(saved)
    assert restored["fatigue_concrete_c"] == 100.0
    assert restored["fatigue_concrete_method"] == (
        fatigue_analysis.CONCRETE_PROJECT_MINER
    )
    assert restored["fatigue_concrete_miner_source"] == (
        "AUTH-SN-7 / checker approval"
    )

    at.selectbox(key="fatigue_concrete_method").set_value(
        fatigue_analysis.CONCRETE_MINER
    ).run()
    assert at.number_input(key="fatigue_concrete_c").value == pytest.approx(
        100.0
    )
    assert at.number_input(key="fatigue_concrete_c").disabled is False


def test_bridge_parameter_editor_columns_have_no_normative_numeric_clamp():
    import bridge_inputs
    import sector_app
    from sector import conformance

    for table_key, value_column in (
        (bridge_inputs.BOX_WALL_TABLE_KEY, "cot_theta"),
        (bridge_inputs.MINIMUM_TABLE_KEY, "k"),
    ):
        config = sector_app._bridge_column_config(table_key)
        numeric = config[value_column]["type_config"]
        basis = config["parameter_basis"]["type_config"]

        assert numeric["min_value"] is None
        assert numeric["max_value"] is None
        assert tuple(basis["options"]) == conformance.BASIS_OPTIONS
        assert "assessed separately" in config[value_column]["help"]


def test_fatigue_reuse_signature_recalculates_after_methodology_switch():
    import fatigue_analysis
    import fatigue_inputs

    at = _fresh().run()
    at.toggle(key="fatigue_on").set_value(True).run()
    at.selectbox(key="fatigue_edition").set_value(
        fatigue_inputs.EC2_2_2005_AC
    ).run()
    at.selectbox(key="fatigue_concrete_method").set_value(
        fatigue_analysis.CONCRETE_EQUIVALENT
    ).run()

    _calculate(at)
    component_signature = at.session_state["result_fatigue_sig"]
    assert at.session_state["results"]["fatigue"]["design_methodology"] == (
        bridge.COMPONENT_METHODS
    )

    _goto_page(at, "Inputs")
    at.selectbox(key="design_methodology").set_value(
        bridge.EN1992_2_BASE
    ).run()
    bridge_signature = at.session_state["_latest_inputs"]["fatigue_sig"]
    assert bridge_signature != component_signature

    _calculate(at)
    assert not at.exception
    assert at.session_state["result_fatigue_sig"] == bridge_signature
    assert at.session_state["results"]["fatigue"]["design_methodology"] == (
        bridge.EN1992_2_BASE
    )
    assert at.session_state["result_input_snapshot"]["design_methodology"] == (
        bridge.EN1992_2_BASE
    )
    assert not any(
        "design methodology conflicts with the calculation input snapshot"
        in error.value
        for error in at.error
    )


def test_fatigue_view_fails_closed_on_relabelled_or_malformed_payload(
    monkeypatch,
):
    import fatigue_analysis
    import fatigue_inputs
    import sector_app

    rendered = {"errors": [], "markdown": []}
    fake_st = SimpleNamespace(
        error=lambda message, **_kwargs: rendered["errors"].append(message),
        warning=lambda *_args, **_kwargs: None,
        success=lambda *_args, **_kwargs: None,
        info=lambda *_args, **_kwargs: None,
        markdown=lambda message, **_kwargs: rendered["markdown"].append(message),
    )
    monkeypatch.setattr(sector_app, "st", fake_st)
    base = {
        "valid": True,
        "converged": True,
        "passed": True,
        "errors": (),
        "edition": fatigue_inputs.EC2_2_2005_AC,
        "design_methodology": bridge.EN1992_2_BASE,
        "checks": {"reinforcement": False, "concrete": True},
        "concrete_method": fatigue_analysis.CONCRETE_EQUIVALENT,
        "concrete_parameters": {
            "c": 100.0,
            "method": fatigue_analysis.CONCRETE_MINER,
        },
    }

    for payload in (base, {**base, "errors": 7}):
        rendered["errors"].clear()
        rendered["markdown"].clear()
        sector_app.fatigue_view(
            {
                "fatigue_on": True,
                "design_methodology": bridge.EN1992_2_BASE,
            },
            {"fatigue": payload},
        )
        assert any(
            message.startswith("INVALID -")
            for message in rendered["errors"]
        )
        assert any(
            "calculation parameters" in message
            or "structured list of typed messages" in message
            for message in rendered["markdown"]
        )

    rendered["errors"].clear()
    rendered["markdown"].clear()
    relabelled_basis = {
        **base,
        "design_methodology": bridge.COMPONENT_METHODS,
        "concrete_method": fatigue_analysis.CONCRETE_MINER,
        "concrete_miner_basis": fatigue_inputs.MINER_BASIS_BRIDGE_STANDARD,
        "concrete_miner_source": "DB-FAT-21 / checker approval",
        "concrete_parameters": {
            "c": 14.0,
            "method": fatigue_analysis.CONCRETE_MINER,
        },
    }
    sector_app.fatigue_view(
        {
            "fatigue_on": True,
            "design_methodology": bridge.COMPONENT_METHODS,
        },
        {"fatigue": relabelled_basis},
    )
    assert any(
        message.startswith("INVALID -")
        for message in rendered["errors"]
    )
    assert any(
        "conformance" in message
        for message in rendered["markdown"]
    )


def test_app_fatigue_factor_switches_and_approved_override_persist():
    import fatigue_inputs
    import project_io

    at = _fresh()
    at.run()
    at.toggle(key="fatigue_on").set_value(True).run()

    assert at.number_input(key="fatigue_gamma_s").value == pytest.approx(1.32)
    assert at.number_input(key="fatigue_gamma_c").value == pytest.approx(1.595)

    at.selectbox(key="fatigue_edition").set_value(
        fatigue_inputs.EC2_2005
    ).run()
    assert at.number_input(key="fatigue_gamma_s").value == pytest.approx(1.15)
    assert at.number_input(key="fatigue_gamma_c").value == pytest.approx(1.50)

    at.selectbox(key="fatigue_edition").set_value(
        fatigue_inputs.EC2_2005_DKNA
    ).run()
    at.number_input(key="fatigue_gamma0").set_value(0.95).run()
    at.number_input(key="fatigue_gamma3").set_value(1.10).run()
    assert at.number_input(key="fatigue_gamma_s").value == pytest.approx(
        1.20 * 1.10 * 0.95 * 1.10
    )
    assert at.number_input(key="fatigue_gamma_c").value == pytest.approx(
        1.45 * 1.10 * 0.95 * 1.10
    )

    at.selectbox(key="fatigue_factor_mode").set_value(
        fatigue_inputs.FACTOR_MODE_OVERRIDE
    ).run()
    assert at.number_input(key="fatigue_gamma_s").value is None
    assert at.number_input(key="fatigue_gamma_c").value is None
    assert at.text_input(key="fatigue_factor_approval").value == ""
    at.number_input(key="fatigue_gamma_s").set_value(0.5).run()
    at.number_input(key="fatigue_gamma_c").set_value(2.0).run()
    at.text_input(key="fatigue_factor_approval").set_value(
        "DB-FACT-09 / checker A"
    ).run()
    next(
        widget
        for widget in at.text_input
        if widget.label == "Approval/reference"
    ).set_value("TRAFFIC-09 / authority B").run()
    at.selectbox(key="fatigue_edition").set_value(
        fatigue_inputs.EC2_2023
    ).run()

    assert at.number_input(key="fatigue_gamma_s").value == pytest.approx(0.5)
    assert at.number_input(key="fatigue_gamma_c").value == pytest.approx(2.0)
    assert at.session_state["fatigue_factor_approval"] == (
        "DB-FACT-09 / checker A"
    )
    assert at.session_state[fatigue_inputs.BASIS_KEY][
        "approval_reference"
    ] == "TRAFFIC-09 / authority B"
    assert any(
        "approved custom input" in warning.value
        for warning in at.warning
    )

    at.selectbox(key="fatigue_factor_mode").set_value(
        fatigue_inputs.FACTOR_MODE_PRESET
    ).run()
    assert at.number_input(key="fatigue_gamma_s").value != pytest.approx(0.5)
    assert at.number_input(key="fatigue_gamma_c").value != pytest.approx(2.0)
    at.selectbox(key="fatigue_factor_mode").set_value(
        fatigue_inputs.FACTOR_MODE_OVERRIDE
    ).run()

    assert at.number_input(key="fatigue_gamma_s").value == pytest.approx(0.5)
    assert at.number_input(key="fatigue_gamma_c").value == pytest.approx(2.0)
    assert at.session_state["fatigue_factor_approval"] == (
        "DB-FACT-09 / checker A"
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
    _tables, restored = project_io.parse_project(saved)
    assert restored["fatigue_gamma_s"] == pytest.approx(0.5)
    assert restored["fatigue_gamma_c"] == pytest.approx(2.0)
    assert restored["fatigue_factor_approval"] == (
        "DB-FACT-09 / checker A"
    )


def test_loaded_approved_fatigue_override_keeps_enabled_missing_factor_empty():
    import fatigue_analysis
    import fatigue_inputs
    import project_io

    at = _fresh()
    at.run()
    tables = {
        key: at.session_state[key]
        for key in project_io.PROJECT_TABLE_KEYS
        if key in at.session_state
    }
    common = {
        "fatigue_on": True,
        fatigue_inputs.BASIS_KEY: fatigue_inputs.default_basis(),
        "fatigue_edition": fatigue_inputs.EC2_2005_DKNA,
        "fatigue_factor_mode": fatigue_inputs.FACTOR_MODE_OVERRIDE,
        "fatigue_factor_approval": "DB-FACT-21 / checker F",
        "fatigue_gamma0": 1.0,
        "fatigue_gamma3": 1.0,
    }

    # The fresh session already contains both preset numbers. Loading an approved
    # steel-only override with no steel factor must clear that stale value. The
    # inactive concrete fallback belongs only to calculation preflight and must not
    # become a persisted/widget value that could later masquerade as approved.
    at.session_state["_pending_project"] = project_io.dump_project(
        tables,
        {
            **common,
            "fatigue_check_steel": True,
            "fatigue_check_concrete": False,
        },
    )
    at.run()

    assert not at.exception
    assert at.number_input(key="fatigue_gamma_s").value is None
    assert at.session_state["fatigue_gamma_s"] is None
    assert at.number_input(key="fatigue_gamma_c").value is None
    assert at.session_state["fatigue_gamma_c"] is None
    steel_errors = fatigue_analysis.validation_errors(
        at.session_state["_latest_inputs"]
    )
    assert "final fatigue material factors are required" in steel_errors
    at.number_input(key="fatigue_gamma_s").set_value(1.27).run()
    steel_only_errors = fatigue_analysis.validation_errors(
        at.session_state["_latest_inputs"]
    )
    assert "final fatigue material factors are required" not in steel_only_errors
    at.toggle(key="fatigue_check_concrete").set_value(True).run()
    assert at.number_input(key="fatigue_gamma_c").value is None
    assert (
        "final fatigue material factors are required"
        in fatigue_analysis.validation_errors(
            at.session_state["_latest_inputs"]
        )
    )

    # Repeat in the opposite direction in the same session. This proves that the
    # durable mirror cannot reintroduce the concrete value seeded by the first load.
    at.session_state["_pending_project"] = project_io.dump_project(
        tables,
        {
            **common,
            "fatigue_check_steel": False,
            "fatigue_check_concrete": True,
        },
    )
    at.run()

    assert not at.exception
    assert at.number_input(key="fatigue_gamma_c").value is None
    assert at.session_state["fatigue_gamma_c"] is None
    assert at.number_input(key="fatigue_gamma_s").value is None
    assert at.session_state["fatigue_gamma_s"] is None
    concrete_errors = fatigue_analysis.validation_errors(
        at.session_state["_latest_inputs"]
    )
    assert "final fatigue material factors are required" in concrete_errors

    _calculate(at)
    blocked = at.session_state["results"]["fatigue"]
    assert blocked["valid"] is False
    assert "final fatigue material factors are required" in blocked["errors"]

    _goto_page(at, "Inputs")
    at.number_input(key="fatigue_gamma_c").set_value(1.61).run()
    repaired_errors = fatigue_analysis.validation_errors(
        at.session_state["_latest_inputs"]
    )
    assert "final fatigue material factors are required" not in repaired_errors
    at.toggle(key="fatigue_check_steel").set_value(True).run()
    assert at.number_input(key="fatigue_gamma_s").value is None
    assert (
        "final fatigue material factors are required"
        in fatigue_analysis.validation_errors(
            at.session_state["_latest_inputs"]
        )
    )


def test_boolean_factor_session_state_fails_closed_in_both_mirrors(
    tmp_path,
    monkeypatch,
):
    import fatigue_analysis
    import fatigue_inputs
    import project_io
    from sector import capacity, codes

    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path))
    at = _fresh()
    at.run()
    factor_state = {
        "fatigue_on": True,
        "fatigue_edition": fatigue_inputs.EC2_2005_DKNA,
        "fatigue_factor_mode": fatigue_inputs.FACTOR_MODE_OVERRIDE,
        "fatigue_factor_approval": "DB-FACT-22 / checker G",
        "fatigue_check_steel": True,
        "fatigue_check_concrete": True,
        "fatigue_gamma0": True,
        "fatigue_gamma3": np.bool_(True),
        "fatigue_gamma_s": True,
        "fatigue_gamma_c": np.bool_(True),
        "torsion_on": True,
        "torsion_method": codes.EC2_2005_DKNA.label,
        "torsion_factor_mode": codes.FACTOR_MODE_OVERRIDE,
        "torsion_factor_approval": "DB-TOR-08 / checker G",
        "torsion_gamma0": True,
        "torsion_gamma3": np.bool_(True),
        "torsion_gamma_ct": np.bool_(True),
    }
    for key, value in factor_state.items():
        at.session_state[key] = value
    durable = dict(at.session_state["_durable_input_scalars"])
    durable.update(factor_state)
    at.session_state["_durable_input_scalars"] = durable

    at.run()

    assert not at.exception
    expected_keys = tuple(sorted(project_io.FACTOR_NUMERIC_SCALAR_KEYS))
    assert at.session_state["_invalid_factor_input_keys"] == expected_keys
    for key in project_io.FACTOR_NUMERIC_SCALAR_KEYS:
        assert not isinstance(at.session_state[key], (bool, np.bool_))
        assert not isinstance(
            at.session_state["_durable_input_scalars"][key],
            (bool, np.bool_),
        )
    inp = at.session_state["_latest_inputs"]
    assert inp["invalid_factor_input_keys"] == expected_keys
    assert any(
        "Boolean/non-numeric values are not accepted" in error
        for error in fatigue_analysis.validation_errors(inp)
    )
    assert (
        "Boolean/non-numeric values are not accepted"
        in capacity.torsion_factor_validation_error(inp)
    )
    assert any(
        "Boolean/non-numeric values are not accepted" in message.value
        for message in at.error
    )
    solver_called = False

    def forbidden_engine(*_args, **_kwargs):
        nonlocal solver_called
        solver_called = True
        raise AssertionError("Rejected session factor reached fatigue solver")

    with pytest.raises(
        ValueError,
        match="Boolean/non-numeric values are not accepted",
    ):
        fatigue_analysis.run_analysis(inp, engine=forbidden_engine)
    assert solver_called is False
    with pytest.raises(
        ValueError,
        match="Boolean/non-numeric values are not accepted",
    ):
        capacity.build_torsion_context(inp, 0.0)

    # Autosave/download share _gather_project. Neither may turn Streamlit's
    # reconstructed numeric widget defaults into an apparently valid project.
    at.session_state["_autosave_t"] = 0.0
    at.run()
    assert not (tmp_path / "autosave.json").exists()

    # A real widget event is the explicit repair path; hidden/default-driven
    # reconstruction alone cannot clear a rejected key.
    at.number_input(key="fatigue_gamma_s").set_value(1.32).run()
    repaired = at.session_state["_invalid_factor_input_keys"]
    assert "fatigue_gamma_s" not in repaired
    assert set(repaired) == set(expected_keys) - {"fatigue_gamma_s"}


def test_boolean_crack_state_is_blocked_in_live_durable_result_and_autosave(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path))
    at = _fresh()
    at.run()
    _set(
        at,
        ("radio", "mode", "Elastic"),
        ("number_input", "el_long_Mx", 400.0),
        ("checkbox", "sls_cw", True),
        ("selectbox", "sls_code", "EN 1992-1-1:2023"),
        (
            "selectbox",
            "sls_exposure_class",
            sls.EXPOSURE_XC2_XC4,
        ),
        (
            "selectbox",
            "sls_long_combination",
            sls.COMBINATION_QUASI_PERMANENT,
        ),
        ("text_input", "sls_exposure_context", "XC3 / durability"),
    )
    rejected_state = {
        "sls_wk_limit": True,
        "sls_tendon_xi": np.bool_(True),
    }
    durable = dict(at.session_state["_durable_input_scalars"])
    for key, value in rejected_state.items():
        at.session_state[key] = value
        durable[key] = value
    at.session_state["_durable_input_scalars"] = durable

    at.run()

    expected = tuple(sorted(rejected_state))
    assert not at.exception
    assert at.session_state["_invalid_crack_input_keys"] == expected
    for key in rejected_state:
        assert not isinstance(at.session_state[key], (bool, np.bool_))
        assert not isinstance(
            at.session_state["_durable_input_scalars"][key],
            (bool, np.bool_),
        )
    inp = at.session_state["_latest_inputs"]
    assert inp["sls_invalid_numeric_inputs"] == expected
    assert any(
        "Rejected Boolean/non-numeric crack-control state" in item.value
        for item in at.error
    )

    _calculate(at)
    assessment = at.session_state["results"]["elastic"]["crack_assessment"]
    assert assessment["status"] == "NOT ASSESSED"
    assert assessment["verdict"] == "REVIEW"
    assert "unrepaired" in assessment["reason"]
    assert "sls_wk_limit" in assessment["reason"]

    _goto_page(at, "Inputs")
    at.session_state["_autosave_t"] = 0.0
    at.run()
    assert not (tmp_path / "autosave.json").exists()

    # A real widget edit clears only that key; reconstructed numeric defaults do
    # not clear the other rejection marker.
    at.number_input(key="sls_wk_limit").set_value(0.30).run()
    assert at.session_state["_invalid_crack_input_keys"] == (
        "sls_tendon_xi",
    )


@pytest.mark.parametrize("pending_value", [np.bool_(True), 0.0])
def test_invalid_pending_crack_event_cannot_become_an_explicit_repair(
    monkeypatch,
    pending_value,
):
    import sector_app

    key = "sls_wk_limit"
    state = {
        key: np.bool_(True),
        sector_app._INPUT_STATE_KEY: {key: True},
        sector_app._PENDING_INPUT_EVENTS_KEY: {key: pending_value},
    }
    monkeypatch.setattr(
        sector_app,
        "st",
        SimpleNamespace(session_state=state),
    )

    sector_app._sanitise_crack_input_state()
    assert state[sector_app._INVALID_CRACK_INPUT_KEYS_KEY] == (key,)
    assert key not in state[sector_app._PENDING_INPUT_EVENTS_KEY]

    # Simulate an interrupted rerun: the pending journal survives exactly as the
    # sanitizer left it. A second reconstruction must retain the rejection.
    sector_app._sanitise_crack_input_state()
    assert state[sector_app._INVALID_CRACK_INPUT_KEYS_KEY] == (key,)

    # A genuine widget event carries the current checked value and may repair it.
    state[key] = 0.30
    state[sector_app._PENDING_INPUT_EVENTS_KEY][key] = 0.30
    sector_app._sanitise_crack_input_state()
    assert sector_app._INVALID_CRACK_INPUT_KEYS_KEY not in state


@pytest.mark.parametrize("value", [True, np.bool_(True)])
@pytest.mark.parametrize(
    "key",
    [
        "sls_fctm",
        "sls_conc_limit_pct",
        "sls_steel_limit_pct",
        "sls_pre_limit_pct",
    ],
)
def test_headless_analysis_rejects_boolean_sls_before_solver_use(key, value):
    import sector_app

    with pytest.raises(ValueError, match=key):
        sector_app.run_analysis({"sls_cw": False, key: value})


def test_stale_category_factor_repair_preserves_approved_overrides_and_outputs(
    tmp_path,
    monkeypatch,
):
    import fatigue_analysis
    import fatigue_inputs
    import project_io
    import reinforcement_table as rt
    from sector import capacity, codes

    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path))
    at = _fresh()
    at.run()
    bars = at.session_state["bars_base"].copy(deep=True)
    bars[rt.FATIGUE_DETAIL_ID] = "F1"
    spectrum = fatigue_inputs.normalise_spectrum_table([{
        "spectrum": "Traffic",
        "name": "FAT-REPAIR",
        "description": "Approved-factor repair regression",
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
        "fatigue_edition": fatigue_inputs.EC2_2005_DKNA,
        "fatigue_check_steel": True,
        "fatigue_check_concrete": True,
        "fatigue_factor_mode": fatigue_inputs.FACTOR_MODE_OVERRIDE,
        "fatigue_factor_approval": "DB-FACT-23 / checker H",
        "fatigue_gamma0": 1.0,
        "fatigue_gamma3": 1.0,
        "fatigue_gamma_s": 1.33,
        "fatigue_gamma_c": 1.60,
        "fatigue_gamma_ff": 1.0,
        fatigue_inputs.DETAIL_CATALOG_KEY: fatigue_inputs.default_catalog(),
        fatigue_inputs.BASIS_KEY: fatigue_inputs.default_basis(),
        "torsion_on": True,
        "torsion_method": codes.EC2_2005_DKNA.label,
        "torsion_factor_mode": codes.FACTOR_MODE_OVERRIDE,
        "torsion_factor_approval": "DB-TOR-09 / checker H",
        "torsion_gamma0": 1.0,
        "torsion_gamma3": 1.0,
        "torsion_gamma_ct": 1.71,
    })
    at.session_state["_pending_project"] = project_io.dump_project(
        tables, scalars
    )
    at.run()
    assert not at.exception

    stale_categories = {
        "fatigue_gamma0": True,
        "fatigue_gamma3": np.bool_(True),
        "torsion_gamma0": True,
        "torsion_gamma3": np.bool_(True),
    }
    durable = dict(at.session_state["_durable_input_scalars"])
    for key, value in stale_categories.items():
        at.session_state[key] = value
        durable[key] = value
    at.session_state["_durable_input_scalars"] = durable
    at.run()

    expected_rejected = tuple(sorted(stale_categories))
    assert not at.exception
    assert at.session_state["_invalid_factor_input_keys"] == expected_rejected
    for key in stale_categories:
        assert at.number_input(key=key).disabled is False
    assert at.button(key="confirm_fatigue_factor_repairs").disabled is False
    assert at.button(key="confirm_torsion_factor_repairs").disabled is False
    assert at.number_input(key="fatigue_gamma_s").value == pytest.approx(1.33)
    assert at.number_input(key="fatigue_gamma_c").value == pytest.approx(1.60)
    assert at.number_input(key="torsion_gamma_ct").value == pytest.approx(1.71)

    # Browser reconstruction can place apparently valid values back into the live
    # widget namespace without a real edit. The marker must survive that rerun
    # until the engineer uses the enabled explicit-confirmation control.
    repaired_categories = {
        "fatigue_gamma0": 0.97,
        "fatigue_gamma3": 1.04,
        "torsion_gamma0": 0.98,
        "torsion_gamma3": 1.03,
    }
    for key in ("fatigue_gamma0", "fatigue_gamma3"):
        at.session_state[key] = repaired_categories[key]
    at.run()
    assert at.session_state["_invalid_factor_input_keys"] == expected_rejected
    at.button(key="confirm_fatigue_factor_repairs").click().run()
    assert set(at.session_state["_invalid_factor_input_keys"]) == {
        "torsion_gamma0",
        "torsion_gamma3",
    }

    # Reproduce the former overwrite path for torsion: switch to the preset, repair
    # its categories through enabled controls, then return to override. The
    # separately retained approved final value must survive that whole sequence.
    at.selectbox(key="torsion_factor_mode").set_value(
        codes.FACTOR_MODE_PRESET
    ).run()
    assert at.number_input(key="torsion_gamma_ct").value != pytest.approx(1.71)
    for key in ("torsion_gamma0", "torsion_gamma3"):
        value = repaired_categories[key]
        widget = at.number_input(key=key)
        assert widget.disabled is False
        widget.set_value(value).run()
    at.selectbox(key="torsion_factor_mode").set_value(
        codes.FACTOR_MODE_OVERRIDE
    ).run()

    assert "_invalid_factor_input_keys" not in at.session_state
    assert at.session_state["fatigue_gamma_s"] == pytest.approx(1.33)
    assert at.session_state["fatigue_gamma_c"] == pytest.approx(1.60)
    assert at.session_state["torsion_gamma_ct"] == pytest.approx(1.71)
    assert at.session_state["fatigue_factor_approval"] == (
        "DB-FACT-23 / checker H"
    )
    assert at.session_state["torsion_factor_approval"] == (
        "DB-TOR-09 / checker H"
    )

    # Preset values may be displayed temporarily, but returning to override must
    # restore the separately retained approved values and their approvals.
    at.selectbox(key="fatigue_factor_mode").set_value(
        fatigue_inputs.FACTOR_MODE_PRESET
    ).run()
    assert at.number_input(key="fatigue_gamma_s").value != pytest.approx(1.33)
    at.selectbox(key="fatigue_factor_mode").set_value(
        fatigue_inputs.FACTOR_MODE_OVERRIDE
    ).run()

    inp = at.session_state["_latest_inputs"]
    assert not any(
        "Boolean/non-numeric values are not accepted" in error
        for error in fatigue_analysis.validation_errors(inp)
    )
    assert capacity.torsion_factor_validation_error(inp) is None
    assert inp["fatigue_gamma_s"] == pytest.approx(1.33)
    assert inp["fatigue_gamma_c"] == pytest.approx(1.60)
    assert inp["torsion_gamma_ct"] == pytest.approx(1.71)

    _calculate(at)
    assert not at.exception
    fatigue = at.session_state["results"]["fatigue"]
    assert fatigue["partial_factors"]["gamma_s"] == pytest.approx(1.33)
    assert fatigue["partial_factors"]["gamma_c"] == pytest.approx(1.60)
    calculation_fatigue = at.session_state["calculation_record"][
        "fatigue_conformance"
    ]
    assert calculation_fatigue["partial_factors"]["gamma_s"] == (
        pytest.approx(1.33)
    )
    assert calculation_fatigue["partial_factors"]["gamma_c"] == (
        pytest.approx(1.60)
    )
    assert calculation_fatigue["factor_basis"]["approval_reference"] == (
        "DB-FACT-23 / checker H"
    )

    _goto_input_tab(at, "Project & report")
    download = next(
        widget
        for widget in at.download_button
        if widget.label == "Download project"
    )
    assert download.proto.disabled is False
    at.session_state["_autosave_t"] = 0.0
    at.run()
    saved = tmp_path / "autosave.json"
    assert saved.exists()
    saved_text = saved.read_text(encoding="utf-8")
    _, saved_scalars = project_io.parse_project(saved_text)
    saved_provenance = project_io.project_provenance(saved_text)
    assert saved_scalars["fatigue_factor_mode"] == (
        fatigue_inputs.FACTOR_MODE_OVERRIDE
    )
    assert saved_scalars["fatigue_gamma_s"] == pytest.approx(1.33)
    assert saved_scalars["fatigue_gamma_c"] == pytest.approx(1.60)
    assert saved_scalars["fatigue_factor_approval"] == (
        "DB-FACT-23 / checker H"
    )
    assert saved_scalars["torsion_factor_mode"] == codes.FACTOR_MODE_OVERRIDE
    assert saved_scalars["torsion_gamma_ct"] == pytest.approx(1.71)
    assert saved_scalars["torsion_factor_approval"] == (
        "DB-TOR-09 / checker H"
    )
    assert saved_provenance["calculation"]["fatigue_conformance"] == (
        calculation_fatigue
    )
    assert saved_provenance["calculation"]["matches_saved_inputs"] is (
        saved_provenance["calculation"]["input_sha256"]
        == saved_provenance["input_sha256"]
    )


def test_app_fatigue_override_does_not_reuse_spectrum_method_approval():
    import fatigue_inputs

    at = _fresh()
    at.run()
    at.toggle(key="fatigue_on").set_value(True).run()
    at.selectbox(key="fatigue_factor_mode").set_value(
        fatigue_inputs.FACTOR_MODE_OVERRIDE
    ).run()
    next(
        widget
        for widget in at.text_input
        if widget.label == "Approval/reference"
    ).set_value("VD-FLM5-AGREEMENT").run()

    assert at.text_input(key="fatigue_factor_approval").value == ""
    assert any(
        "does not authorize material-factor changes" in warning.value
        for warning in at.warning
    )

    at.text_input(key="fatigue_factor_approval").set_value(
        "DB-FACT-11 / checker C"
    ).run()

    assert not any(
        "does not authorize material-factor changes" in warning.value
        for warning in at.warning
    )
    assert at.session_state[fatigue_inputs.BASIS_KEY][
        "approval_reference"
    ] == "VD-FLM5-AGREEMENT"


def test_loading_nonfatigue_project_clears_prior_fatigue_state():
    import json
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
            fatigue_inputs.BASIS_KEY:
                fatigue_inputs.default_basis(),
            "fatigue_on": True,
            "fatigue_gamma_c": 1.595,
            "fatigue_source": "Previous project",
        },
    )
    at = _fresh()
    at.session_state["_pending_project"] = fatigue_project
    at.run()
    assert at.session_state["fatigue_on"] is True

    old_project = json.dumps({
        "format": project_io.FORMAT,
        "version": 8,
        "tables": {},
        "scalars": {"mode": "Plastic"},
    })
    at.session_state["_pending_project"] = old_project
    at.run()

    assert not at.exception
    # The mounted UI seeds neutral defaults after clearing the previous project.
    # Values from the first project must not leak into those defaults.
    assert at.session_state["fatigue_on"] is False
    assert fatigue_inputs.spectrum_records(
        at.session_state[fatigue_inputs.SPECTRUM_TABLE_KEY]
    ) == []
    assert at.session_state["fatigue_gamma_c"] == pytest.approx(1.595)
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
    assert payload["fatigue"]["spectrum"] == []
    assert payload["scalars"]["fatigue_on"] is False
    assert payload["scalars"]["fatigue_gamma_c"] == pytest.approx(1.595)


def test_calculate_runs_the_ui_configured_grouped_fatigue_spectrum():
    import fatigue_inputs
    import project_io
    import reinforcement_table as rt

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
        "fatigue_edition": fatigue_inputs.EC2_2005_DKNA,
        "fatigue_check_steel": True,
        "fatigue_check_concrete": False,
        "fatigue_factor_mode": fatigue_inputs.FACTOR_MODE_PRESET,
        "fatigue_gamma0": 1.0,
        "fatigue_gamma3": 1.0,
        "fatigue_gamma_s": 1.32,
        "fatigue_gamma_c": 1.595,
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
    assert fatigue["design_methodology"] == bridge.COMPONENT_METHODS
    assert at.session_state["result_input_snapshot"]["design_methodology"] == (
        bridge.COMPONENT_METHODS
    )
    assert len(fatigue["spectra"]) == 1
    assert fatigue["partial_factors"]["gamma_s"] == pytest.approx(1.32)
    assert fatigue["factor_basis"]["gamma_s_derivation"] == (
        "1.20 x 1.10 x 1.000 x 1.000 = 1.320"
    )
    fatigue_record = at.session_state["calculation_record"][
        "fatigue_conformance"
    ]
    assert fatigue_record["design_methodology"] == bridge.COMPONENT_METHODS
    assert fatigue_record["partial_factors"]["gamma_s"] == pytest.approx(1.32)
    assert fatigue_record["evidence_sha256"]
    assert at.session_state["result_fatigue_sig"] == (
        at.session_state["_latest_inputs"]["fatigue_sig"]
    )
    summary = next(
        frame.value for frame in at.dataframe
        if "Check" in frame.value.columns and "Status" in frame.value.columns
    )
    assert summary.loc[summary["Check"] == "Fatigue"].shape[0] == 1
    register = next(
        frame.value for frame in at.dataframe
        if "Analysis" in frame.value.columns
        and "Result state" in frame.value.columns
    )
    fatigue_register = register.loc[register["Analysis"] == "Fatigue"]
    assert fatigue_register.iloc[0]["Case"] == "Traffic"
    assert fatigue_register.iloc[0]["Result state"] == "Calculated"

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
        if {"Element", "Detail", "Miner D", "Status"}.issubset(
            frame.value.columns
        )
    )
    assert reinforcement.iloc[0]["Element"] == "R1"

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
    assert "Edition" in set(basis_table["Item"])
    assert "Design methodology" in set(basis_table["Item"])
    assert "gamma_Ff" in set(basis_table["Item"])
    assert basis_table["Value"].map(type).eq(str).all()

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
        "predates input snapshots" in error.value
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
    at.number_input(key="conc_fck").set_value(changed_fck).run()
    fck_fatigue_sig = at.session_state["_latest_inputs"]["fatigue_sig"]
    assert fck_fatigue_sig != calculated_fatigue_sig
    current_alpha_cc = float(at.session_state["conc_alpha_cc"])
    changed_alpha_cc = 0.85 if current_alpha_cc != 0.85 else 0.90
    at.number_input(key="conc_alpha_cc").set_value(changed_alpha_cc).run()
    assert at.session_state["_latest_inputs"]["fatigue_sig"] != fck_fatigue_sig

    at.selectbox(key="fatigue_factor_mode").set_value(
        fatigue_inputs.FACTOR_MODE_OVERRIDE
    ).run()
    at.text_input(key="fatigue_factor_approval").set_value(
        "DB-FACT-10 / checker B"
    ).run()
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


def test_fatigue_authority_widgets_write_the_structured_basis():
    import fatigue_inputs

    at = _fresh()
    at.run()
    at.toggle(key="fatigue_on").set_value(True).run()
    prefix = (
        f"fatiguebasis_r{at.session_state['_fatigue_basis_revision']}"
    )
    at.selectbox(key=f"{prefix}_authority").set_value(
        fatigue_inputs.AUTHORITY_VD
    ).run()
    assert at.session_state[fatigue_inputs.BASIS_KEY]["authority"] == (
        fatigue_inputs.AUTHORITY_VD
    )
    assert at.session_state[fatigue_inputs.BASIS_KEY]["method"] == (
        fatigue_inputs.METHOD_VD_FLM1
    )

    at.selectbox(key=f"{prefix}_method").set_value(
        fatigue_inputs.METHOD_VD_FLM4
    )
    at.text_input(key=f"{prefix}_spectrum_source").set_value(
        "Traffic model register"
    )
    at.run()

    basis = at.session_state[fatigue_inputs.BASIS_KEY]
    assert basis["method"] == fatigue_inputs.METHOD_VD_FLM4
    assert basis["spectrum_source"] == "Traffic model register"


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
    _set(
        at,
        ("selectbox", "sls_code", "EN 1992-1-1:2023"),
        ("checkbox", "sls_cw", True),
    )
    _set(
        at,
        (
            "selectbox",
            "sls_exposure_class",
            sls.EXPOSURE_XC2_XC4,
        ),
        (
            "selectbox",
            "sls_long_combination",
            sls.COMBINATION_QUASI_PERMANENT,
        ),
        ("text_input", "sls_exposure_context", "XC3 / durability"),
    )
    at.session_state["_autosave_t"] = 0.0          # make a save due, then rerun
    at.run()
    saved = tmp_path / "autosave.json"
    assert saved.exists()
    _sys.path.insert(0, str(pathlib.Path(APP).resolve().parent))
    import project_io  # noqa: E402
    tables, scalars = project_io.parse_project(saved.read_text(encoding="utf-8"))
    assert len(tables["corners_base"]) >= 3        # the live section, not blank
    assert tables["elastic_cases_base"].loc[0, "long_combination"] == (
        sls.COMBINATION_QUASI_PERMANENT
    )
    assert scalars["sls_criterion_mode"] == sls.CRITERION_MODE_STANDARD
    assert scalars["sls_exposure_class"] == sls.EXPOSURE_XC2_XC4
    assert scalars["sls_exposure_context"] == "XC3 / durability"
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


def test_analysis_fragment_honours_hidden_disabled_autosave(tmp_path, monkeypatch):
    """Widget cleanup must not re-enable autosave on a fragment-only rerun."""
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path))
    at = _fresh()
    at.run()
    _goto_input_tab(at, "Project & report")
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
    _goto_input_tab(at, "Project & report")
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
    _goto_input_tab(at, "Project & report")
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
    _goto_input_tab(at, "Project & report")
    at.session_state["_report_no_figures"] = True
    assert at.selectbox(key="rep_report_content").value == "Default report"
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


def test_report_download_becomes_stale_after_metadata_change():
    at = _fresh()
    at.run()
    _goto_input_tab(at, "Project & report")
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
    _goto_input_tab(at, "Project & report")
    at.session_state["_report_no_figures"] = True
    at.button(key="gen_report").click().run()
    assert not any("Report out of date" in w.value for w in at.warning)

    at.selectbox(key="rep_report_content").set_value(
        "Default report + QA appendix"
    ).run()
    assert any("Report out of date" in w.value for w in at.warning)


def test_report_download_becomes_stale_after_analysis_input_change():
    at = _fresh()
    at.run()
    _goto_input_tab(at, "Project & report")
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

    at.checkbox(key="shear_on").set_value(True).run()
    at.selectbox(key="capacity_steel_material_id").set_value("M2").run()
    assert at.button(key="mild_catalog_delete").disabled is True
    at.selectbox(key="capacity_steel_material_id").set_value("M1").run()
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
    assert not any("shear with links" in item for item in limited["limitations"])
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
    assert crack_only_2023["limitations"] == [
        sector_app.CRACK_DIRECTIONAL_LIMITATION
    ]


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


def test_fatigue_unlocks_the_elastic_material_parameters():
    at = _fresh()
    at.run()
    assert at.number_input(key="conc_Ec").disabled is True

    at.toggle(key="fatigue_on").set_value(True).run()

    assert at.number_input(key="conc_Ec").disabled is False
    assert at.number_input(key="el_phi").disabled is False


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
    for key in (
        "fatigue_edition",
        "fatigue_factor_mode",
        "fatigue_gamma0",
        "fatigue_gamma3",
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
    assert at.text_input(key="fatigue_factor_approval").help
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
    for widget_group in (
        at.number_input, at.selectbox, at.text_input, at.toggle, at.checkbox,
    ):
        for widget in widget_group:
            for value in (getattr(widget, "label", ""), getattr(widget, "help", "")):
                assert not re.search(
                    r"[\x00-\x08\x0b\x0c\x0e-\x1f]",
                    value or "",
                ), (widget.key, value)
    assert at.number_input(key="v_min").label == (
        r"Start angle $\varphi_{NA,\min}$ ($^\circ$)"
    )
    assert at.number_input(key="sls_wk_limit").label == (
        r"Durability crack-width limit "
        r"$w_{\mathrm{lim}}$ (mm, 0 = not assessed)"
    )
    assert at.number_input(key="detailing_d_upper").label == (
        r"Maximum aggregate size $D_{\mathrm{upper}}$ (mm)"
    )
    assert at.selectbox(key="sls_bond").label == r"Mild-steel bond ($k_1$)"
    assert at.selectbox(key="sls_tendon_bond").label == (
        r"Prestressing-steel bond condition ($k_b$)"
    )
    assert at.number_input(key="sls_tendon_xi").label == (
        r"Prestressing bond-strength ratio $\xi$ (0 = not assessed)"
    )
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
    at = _fresh()
    at.run()

    plastic = _widget(at.dataframe, "plastic_cases_editor").value
    elastic = _widget(at.dataframe, "elastic_cases_editor").value
    assert list(plastic.columns) == [
        "name", "description", "n_ed_kn", "mx_ed_knm", "my_ed_knm",
        "vx_ed_kn", "vy_ed_kn", "vx_face", "vy_face", "t_ed_knm",
        "check_minimum_reinforcement",
    ]
    assert list(elastic.columns) == [
        "name", "description",
        "long_combination", "total_combination",
        "n_long_ed_kn", "mx_long_ed_knm", "my_long_ed_knm",
        "n_short_ed_kn", "mx_short_ed_knm", "my_short_ed_knm",
        "check_stress", "check_crack_width",
    ]
    at.toggle(key="fatigue_on").set_value(True).run()
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


def test_native_data_editor_state_is_not_replayed_through_session_state():
    at = _fresh()
    at.run()

    # A real browser edit puts this Streamlit-owned delta in the callback state.
    # Reassigning it before data_editor is reconstructed raises
    # StreamlitValueAssignmentNotAllowedError.
    at.session_state["_pending_input_events"] = {
        "elastic_cases_editor": {
            "edited_rows": {0: {"check_crack_width": True}},
            "added_rows": [],
            "deleted_rows": [],
        },
        "bridge_box_walls_base_editor": {
            "edited_rows": {},
            "added_rows": [{
                "wall_id": "W1",
                "cot_theta": 10.0,
                "v_ed_kn": 100.0,
                "v_rd_max_kn": 200.0,
                "t_ed_equivalent_kn": 10.0,
                "t_rd_max_equivalent_kn": 200.0,
            }],
            "deleted_rows": [],
        },
    }
    at.run()

    assert not at.exception
    assert "_pending_input_events" not in at.session_state
    assert _widget(at.dataframe, "elastic_cases_editor").value is not None


def test_native_editor_callback_commits_delta_before_interrupted_recovery(
    monkeypatch,
):
    import bridge_inputs
    import fatigue_inputs
    import load_cases
    import sector_app

    plastic_key = load_cases.PLASTIC_TABLE_KEY
    plastic_seed = load_cases.normalise_table([
        {"name": "P1", "mx_ed_knm": 10.0},
        {"name": "P2", "mx_ed_knm": 20.0},
    ], plastic_key)
    state = {
        "_main_page": "Inputs",
        plastic_key: plastic_seed.copy(deep=True),
        f"_{plastic_key}_editor_seed": plastic_seed.copy(deep=True),
        "plastic_cases_editor": {
            "edited_rows": {"0": {"mx_ed_knm": 125.0}},
            "deleted_rows": [1],
            "added_rows": [{"name": "P3", "mx_ed_knm": 75.0}],
        },
    }
    monkeypatch.setattr(sector_app.st, "session_state", state)

    sector_app._record_input_event(
        "plastic_cases_editor",
        sector_app._commit_case_editor_delta,
        (plastic_key,),
    )

    committed = state[plastic_key]
    assert committed["name"].tolist() == ["P1", "P3"]
    assert committed["mx_ed_knm"].tolist() == pytest.approx([125.0, 75.0])
    assert "_pending_input_events" not in state

    fatigue_key = fatigue_inputs.SPECTRUM_TABLE_KEY
    fatigue_seed = fatigue_inputs.normalise_spectrum_table([
        {"spectrum": "S1", "name": "F1", "cycles": 1000.0},
    ])
    state.update({
        fatigue_key: fatigue_seed.copy(deep=True),
        f"_{fatigue_key}_editor_seed": fatigue_seed.copy(deep=True),
        "fatigue_spectrum_editor": {
            "edited_rows": {0: {"cycles": 2500.0}},
            "deleted_rows": [],
            "added_rows": [],
        },
    })
    sector_app._record_input_event(
        "fatigue_spectrum_editor",
        sector_app._commit_fatigue_editor_delta,
    )
    assert state[fatigue_key].loc[0, "cycles"] == pytest.approx(2500.0)
    assert "_pending_input_events" not in state

    bridge_key = bridge_inputs.BOX_WALL_TABLE_KEY
    bridge_seed = bridge_inputs.empty_table(bridge_key)
    state.update({
        bridge_key: bridge_seed.copy(deep=True),
        f"_{bridge_key}_editor_seed": bridge_seed.copy(deep=True),
        "bridge_box_walls_base_editor": {
            "edited_rows": {},
            "deleted_rows": [],
            "added_rows": [{
                "wall_id": "W1",
                "cot_theta": 10.0,
                "v_ed_kn": 100.0,
                "v_rd_max_kn": 200.0,
                "t_ed_equivalent_kn": 10.0,
                "t_rd_max_equivalent_kn": 200.0,
            }],
        },
    })
    sector_app._record_input_event(
        "bridge_box_walls_base_editor",
        sector_app._commit_bridge_editor_delta,
        (bridge_key,),
    )
    assert state[bridge_key].loc[0, "wall_id"] == "W1"
    assert state[bridge_key].loc[0, "cot_theta"] == pytest.approx(10.0)
    assert "_pending_input_events" not in state


def test_detailing_controls_run_selected_case_and_section_wide_spacing():
    import load_cases

    at = _fresh()
    at.run()
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
            "Vx_Ed [kN]", "Vy_Ed [kN]", "Vx face", "Vy face",
            "T_Ed [kNm]", "Minimum reinforcement",
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
            "long_combination": sls.COMBINATION_QUASI_PERMANENT,
            "total_combination": sls.COMBINATION_FREQUENT,
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
    assert actions["Action part"].tolist() == ["Long-term", "Short increment"]
    assert actions["Response SLS combination"].tolist() == [
        sls.COMBINATION_QUASI_PERMANENT,
        sls.COMBINATION_FREQUENT,
    ]
    assert actions["Mx_Ed [kNm]"].tolist() == pytest.approx([120.0, 30.0])
    assert any("Acceptance: crack width" in caption.value for caption in at.caption)
    assert not at.exception


def test_duplicate_crack_combination_mappings_across_cases_fail_closed():
    import load_cases

    at = _fresh()
    at.run()
    _set(at, ("radio", "mode", "Elastic"))
    _replace_case_table(at, load_cases.ELASTIC_TABLE_KEY, [
        {
            "name": "EL-QP-A",
            "description": "First independent QP response",
            "long_combination": sls.COMBINATION_QUASI_PERMANENT,
            "mx_long_ed_knm": 400.0,
            "check_crack_width": True,
        },
        {
            "name": "EL-QP-B",
            "description": "Second independent QP response",
            "long_combination": sls.COMBINATION_QUASI_PERMANENT,
            "mx_long_ed_knm": 350.0,
            "check_crack_width": True,
        },
    ])
    _set(
        at,
        ("text_input", "sls_exposure_context", "XC3 / durability"),
    )
    _calculate(at)

    assert not at.exception
    entries = at.session_state["results"]["elastic_cases"]
    assert [entry["name"] for entry in entries] == ["EL-QP-A", "EL-QP-B"]
    for entry in entries:
        assessment = entry["results"]["elastic"]["crack_assessment"]
        assert assessment["status"] == "NOT ASSESSED"
        assert assessment["verdict"] == "REVIEW"
        assert "across checked Elastic cases" in assessment["reason"]
        assert {
            item["response_id"]
            for item in assessment["response_provenance"]
        } == {"EL-QP-A:long", "EL-QP-B:long"}


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
        "Reinforcement detailing",
        "Fatigue",
        "Shear, torsion & combined (Plastic)",
        "Bridge methodology (DS/EN 1992-2 base or Danish NA)",
        "Danish infrastructure-manager and project design basis",
        "Bulk assignments",
    ]
    _goto_input_tab(at, "Project & report")
    labels = [ex.label for ex in at.expander]
    assert labels == [
        "Stress and crack-width criteria (Elastic)",
        "Reinforcement detailing",
        "Fatigue",
        "Shear, torsion & combined (Plastic)",
        "Bridge methodology (DS/EN 1992-2 base or Danish NA)",
        "Danish infrastructure-manager and project design basis",
        "Bulk assignments",
        "About",
        "Report",
        "Save / Load",
    ]


def test_interrupted_inputs_build_cannot_replace_the_last_complete_snapshot():
    at = _fresh()
    at.run()
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
    at.number_input(key="conc_fck").set_value(55.0).run()

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
    at.number_input(key="conc_fck").set_value(55.0).run()

    # The browser records the next widget event before the superseding rerun.
    # Recovery must reject partial defaults but retain this genuine 55 -> 60 edit.
    at.session_state["_inputs_build_in_progress"] = True
    at.number_input(key="conc_fck").set_value(60.0).run()

    assert at.session_state["conc_fck"] == 60.0
    assert at.session_state["_durable_input_scalars"]["conc_fck"] == 60.0
    assert "_pending_input_events" not in at.session_state
    assert not at.exception


def test_interrupted_inputs_recovery_preserves_the_new_tab_selection():
    at = _fresh()
    at.run()
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
    at.run()

    assert at.session_state["_material_tab"] == "Prestressing steel"
    assert at.session_state["conc_fck"] == 55.0
    assert not at.exception


def test_project_load_invalidates_prior_inputs_before_analysis_can_render():
    """A superseded load cannot expose the previous project's solver payload."""
    import project_io

    at = _fresh()
    at.run()
    prior_inputs = at.session_state["_latest_inputs"]
    prior_fck = prior_inputs["concrete"].fck

    tables = {
        key: at.session_state[key]
        for key in project_io.PROJECT_TABLE_KEYS
        if key in at.session_state
    }
    scalars = {
        key: at.session_state[key]
        for key in project_io.SCALAR_KEYS
        if key in at.session_state
    }
    loaded_fck = 55.0 if prior_fck != 55.0 else 45.0
    scalars["conc_fck"] = loaded_fck

    # Reproduce a project-load rerun superseded by a rapid Analysis click before
    # build_inputs() can commit the newly loaded project's immutable payload.
    at.session_state["_pending_project"] = project_io.dump_project(tables, scalars)
    at.session_state["_inputs_build_in_progress"] = True
    at.session_state["_main_page"] = "Analysis"
    at.run()

    assert not at.exception
    assert at.session_state["conc_fck"] == loaded_fck
    assert at.session_state["_durable_input_scalars"]["conc_fck"] == loaded_fck
    assert "_latest_inputs" not in at.session_state
    assert not any(button.key == "calculate" for button in at.button)
    assert any(
        "Open Inputs once to initialise" in info.value
        for info in at.info
    )

    # A completed Inputs build creates the only solver payload that Analysis may
    # consume, and it belongs to the newly loaded project.
    _goto_page(at, "Inputs")
    rebuilt_inputs = at.session_state["_latest_inputs"]
    assert rebuilt_inputs["concrete"].fck == loaded_fck
    _goto_page(at, "Analysis")
    assert any(button.key == "calculate" for button in at.button)


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


def test_standard_qp_verdict_ignores_larger_explicit_non_qp_total_response(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path))
    at = _fresh()
    at.run()
    _set_and_click(
        at,
        "calculate",
        ("radio", "mode", "Elastic"),
        ("number_input", "el_long_Mx", 400.0),
        ("number_input", "el_short_Mx", 150.0),
        ("checkbox", "sls_cw", True),
        (
            "selectbox",
            "sls_long_combination",
            sls.COMBINATION_QUASI_PERMANENT,
        ),
        (
            "selectbox",
            "sls_total_combination",
            sls.COMBINATION_CHARACTERISTIC,
        ),
        ("text_input", "sls_exposure_context", "XC3 / durability"),
    )
    first = at.session_state["results"]["elastic"]
    qp_width = first["crack"]["wk"]
    total_width = first["crack_short"]["wk"]
    assert total_width > qp_width
    separating_limit = (qp_width + total_width) / 2.0

    _set_and_click(
        at,
        "calculate",
        ("number_input", "sls_wk_limit", separating_limit),
    )

    assessment = at.session_state["results"]["elastic"]["crack_assessment"]
    assert qp_width < separating_limit < total_width
    assert assessment["status"] == "OK"
    assert assessment["verdict"] == "PASS"
    assert assessment["case"] == "Long-term"
    assert assessment["value"] == pytest.approx(qp_width)
    assert assessment["informational_responses"] == [
        "Total (long + short)"
    ]
    raw_binding = assessment["criteria"][0]["acceptance_evidence"]
    assert raw_binding["schema"] == sls.CRACK_ACCEPTANCE_EVIDENCE_SCHEMA
    assert len(raw_binding["fingerprint"]) == 64
    recorded = at.session_state["calculation_record"]["crack_control"]
    recorded_case = recorded["cases"][0]
    assert recorded_case["assessment"]["verdict"] == "PASS"
    recorded_binding = recorded_case["assessment"]["criteria"][0][
        "acceptance_evidence"
    ]
    assert recorded_binding["fingerprint"] == raw_binding["fingerprint"]
    assert recorded_case["response_mapping_scope"] == (
        first["crack_response_mapping_scope"]
    )
    assert any(
        response["wk_mm"] == pytest.approx(total_width)
        and response["acceptance_role"] == "informational"
        for response in recorded_case["responses"]
    )

    at.session_state["_autosave_t"] = 0.0
    at.run()
    import project_io
    provenance = project_io.project_provenance(
        (tmp_path / "autosave.json").read_text(encoding="utf-8")
    )
    assert provenance["results_included"] is True
    saved_case = provenance["calculation"]["crack_control"]["cases"][0]
    assert saved_case["assessment"]["verdict"] == "PASS"
    assert saved_case["assessment"]["criteria"][0][
        "acceptance_evidence"
    ]["fingerprint"] == raw_binding["fingerprint"]
    assert provenance["calculation"]["matches_saved_inputs"] is True

    stale_record = copy.deepcopy(
        at.session_state["calculation_record"]
    )
    stale_case = stale_record["crack_control"]["cases"][0]
    criterion_response = next(
        response
        for response in stale_case["responses"]
        if response["acceptance_role"] == "criterion input"
    )
    criterion_response["wk_mm"] = total_width
    assert stale_case["assessment"]["verdict"] == "PASS"
    at.session_state["calculation_record"] = stale_record
    at.session_state["_autosave_t"] = 0.0
    at.run()

    provenance = project_io.project_provenance(
        (tmp_path / "autosave.json").read_text(encoding="utf-8")
    )
    saved_case = provenance["calculation"]["crack_control"]["cases"][0]
    assert saved_case["assessment"]["status"] == "NOT ASSESSED"
    assert saved_case["assessment"]["verdict"] == "REVIEW"
    assert saved_case["assessment"]["value"] is None
    assert saved_case["assessment"]["util"] is None
    assert saved_case["assessment"]["margin"] is None
    assert saved_case["assessment"]["publication_validation"][
        "status"
    ] == "REJECTED"
    assert provenance["calculation"]["matches_saved_inputs"] is True


def test_boolean_calculated_crack_width_cannot_create_pass_record():
    import sector_app

    criteria = sls.crack_criteria_from_inputs({
        "sls_criterion_mode": sls.CRITERION_MODE_STANDARD,
        "sls_edition": "2004",
        "sls_code": "EN 1992-1-1:2005",
        "sls_member": "Beam",
        "sls_prestress_class": sls.PRESTRESS_REINFORCED_UNBONDED,
        "sls_exposure_context": "XC3 / durability",
        "sls_check_durability": True,
        "sls_wk_limit": 0.30,
        "sls_decompression_applicability": (
            sls.DECOMPRESSION_NOT_REQUIRED
        ),
    })
    contexts = {
        "Long-term": {
            "combination": sls.COMBINATION_QUASI_PERMANENT,
            "response_id": "long",
            "solver_provenance": {"state": "long"},
        },
        "Total (long + short)": {
            "combination": sls.COMBINATION_CHARACTERISTIC,
            "response_id": "total",
            "solver_provenance": {"state": "long-plus-short"},
        },
    }
    rejected_wk = np.asarray(False, dtype=object)
    assessment = sls.crack_assessment(
        {
            "Long-term": {
                "wk": 0.22,
                "element_id": "R1",
            },
            "Total (long + short)": {
                "wk": rejected_wk,
                "element_id": "R1",
            },
        },
        valid=True,
        criteria=criteria,
        response_contexts=contexts,
    )
    record = sector_app.crack_control_calculation_record({
        "elastic": {
            "show_cw": True,
            "crack_assessment": assessment,
            "crack_responses": {
                "Long-term": {
                    "wk": 0.22,
                    "element_id": "R1",
                },
                "Total (long + short)": {
                    "wk": rejected_wk,
                    "element_id": "R1",
                },
            },
            "crack_dispositions": {
                "Long-term": {"status": "OK"},
                "Total (long + short)": {"status": "OK"},
            },
            "crack_response_contexts": contexts,
        },
    })

    recorded = record["cases"][0]
    assert recorded["assessment"]["status"] == "NOT ASSESSED"
    assert recorded["assessment"]["verdict"] == "REVIEW"
    responses = {
        response["name"]: response for response in recorded["responses"]
    }
    assert responses["Long-term"]["wk_mm"] == pytest.approx(0.22)
    rejected = responses["Total (long + short)"]
    assert rejected["wk_mm"] is None
    assert rejected["acceptance_role"] == "informational"
    assert "rejected" in rejected[
        "result_validation"
    ].lower()
    assert '"PASS"' not in json.dumps(record)


def test_non_mapping_crack_response_is_retained_as_rejected_record():
    import sector_app

    contexts = {
        "QP": {
            "combination": sls.COMBINATION_QUASI_PERMANENT,
            "duration": "long",
            "response_id": "qp",
            "provenance": "controlled QP mapping",
            "solver_provenance": {"state": "long"},
        },
    }
    mapping_scope = [{
        "combination": sls.COMBINATION_QUASI_PERMANENT,
        "duration": "long",
        "response": "QP",
        "response_id": "qp",
        "elastic_case": "elastic-1",
        "state": "long",
        "provenance": "controlled QP mapping",
    }]
    assessment = sls.crack_assessment(
        {"QP": {"wk": 0.22, "element_id": "R1"}},
        valid=True,
        criteria=[{
            "id": "qa-durability",
            "kind": sls.CRITERION_DURABILITY,
            "source_type": sls.CRITERION_MODE_STANDARD,
            "source": "QA controlled criterion",
            "required_combination": sls.COMBINATION_QUASI_PERMANENT,
            "limit_mm": 0.30,
            "applicability": {"member": "reinforced"},
        }],
        response_contexts=contexts,
        response_mapping_scope=mapping_scope,
    )
    assert assessment["status"] == "OK"
    assert assessment["verdict"] == "PASS"

    record = sector_app.crack_control_calculation_record({
        "elastic": {
            "show_cw": True,
            "crack_assessment": assessment,
            "crack_responses": {"QP": 1.0},
            "crack_dispositions": {"QP": {"status": "OK"}},
            "crack_response_contexts": contexts,
            "crack_response_mapping_scope": mapping_scope,
        },
    })

    recorded = record["cases"][0]
    assert recorded["assessment"]["status"] == "NOT ASSESSED"
    assert recorded["assessment"]["verdict"] == "REVIEW"
    assert recorded["assessment"]["value"] is None
    assert recorded["assessment"]["util"] is None
    assert recorded["assessment"]["margin"] is None
    assert recorded["assessment"]["publication_validation"][
        "status"
    ] == "REJECTED"
    assert recorded["assessment"]["solver_provenance"] == [{
        "response": "QP",
        "solver": {"state": "long"},
    }]
    response = recorded["responses"][0]
    assert response["wk_mm"] is None
    assert "response rejected" in response["result_validation"].lower()
    assert '"PASS"' not in json.dumps(record)


def _canonical_app_width_results():
    contexts = {
        name: {
            "combination": sls.COMBINATION_QUASI_PERMANENT,
            "duration": "long",
            "response_id": "qp",
            "provenance": "map-v1",
            "solver_provenance": {"solve": "v1", "converged": True},
        }
        for name in ("Fine", "Coarse")
    }
    mapping_scope = [{
        "combination": sls.COMBINATION_QUASI_PERMANENT,
        "duration": "long",
        "response": "QP",
        "response_id": "qp",
        "elastic_case": "elastic-1",
        "state": "long",
        "provenance": "map-v1",
        "solver_provenance": {"solve": "v1", "converged": True},
    }]
    responses = {
        "Fine": {"wk": 0.22, "element_id": "R1"},
        "Coarse": {"wk": 0.18, "element_id": "R2"},
    }
    assessment = sls.crack_assessment(
        responses,
        valid=True,
        criteria=[{
            "id": "qa-width",
            "kind": sls.CRITERION_DURABILITY,
            "source_type": sls.CRITERION_MODE_STANDARD,
            "source": "QA controlled durability criterion",
            "required_combination": sls.COMBINATION_QUASI_PERMANENT,
            "limit_mm": 0.30,
            "applicability": {"member": "reinforced"},
        }],
        response_contexts=contexts,
        response_mapping_scope=mapping_scope,
    )
    assert assessment["verdict"] == "PASS"
    return {
        "elastic": {
            "show_cw": True,
            "crack_assessment": assessment,
            "crack_responses": responses,
            "crack_dispositions": {
                name: {"status": "OK"} for name in responses
            },
            "crack_response_contexts": contexts,
            "crack_response_mapping_scope": mapping_scope,
        },
    }


def _reseal_app_acceptance_binding(binding):
    body = {
        key: value
        for key, value in binding.items()
        if key != "fingerprint"
    }
    binding["fingerprint"] = hashlib.sha256(
        json.dumps(
            body,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def test_legacy_scalar_analysis_constructs_complete_explicit_mapping_scope(
    monkeypatch,
):
    import sector_app

    captured = {}

    def capture(single_input, **_kwargs):
        captured.update(single_input)
        return {}

    monkeypatch.setattr(sector_app, "_run_single_analysis", capture)
    inp = {
        "section": object(),
        "sls_cw": True,
        "sls_long_combination": sls.COMBINATION_QUASI_PERMANENT,
        "sls_total_combination": sls.COMBINATION_CHARACTERISTIC,
    }

    result = sector_app.run_analysis(inp)
    assert set(result) == {"bridge_methodology"}
    assert result["bridge_methodology"]["active"] is False
    assert result["bridge_methodology"]["status"] == (
        bridge.STATUS_NOT_APPLICABLE
    )
    assert result["bridge_methodology"]["checks"] == []
    scope = captured["sls_response_mapping_scope"]

    assert "sls_response_mapping_scope" not in inp
    assert [item["response_id"] for item in scope] == ["long", "total"]
    assert [item["state"] for item in scope] == ["long", "total"]
    assert all(item["duration"] for item in scope)
    assert all(item["provenance"] for item in scope)
    assert captured["sls_response_provenance"]["long"].startswith(
        "Legacy scalar"
    )


@pytest.mark.parametrize(
    ("mutation", "changed_value"),
    [
        ("response_id", "other"),
        ("duration", "short"),
        ("provenance", "map-v2"),
        ("solver_provenance", {"solve": "v2", "converged": True}),
        ("width", 0.21),
        ("governing_element", "R9"),
        ("scope_duration", "short"),
        ("scope_provenance", "map-v2"),
        ("criterion_source", "Changed durability criterion"),
        ("applicability", {"member": "changed"}),
    ],
)
def test_calculation_record_rejects_each_acceptance_binding_mutation(
    mutation,
    changed_value,
):
    import sector_app

    results = _canonical_app_width_results()
    elastic = results["elastic"]
    if mutation in {
        "response_id",
        "duration",
        "provenance",
        "solver_provenance",
    }:
        for context in elastic["crack_response_contexts"].values():
            context[mutation] = copy.deepcopy(changed_value)
    elif mutation == "width":
        elastic["crack_responses"]["Fine"]["wk"] = changed_value
    elif mutation == "governing_element":
        elastic["crack_responses"]["Fine"]["element_id"] = changed_value
    elif mutation.startswith("scope_"):
        elastic["crack_response_mapping_scope"][0][
            mutation.removeprefix("scope_")
        ] = copy.deepcopy(changed_value)
    else:
        elastic["crack_assessment"]["criteria"][0][
            mutation
        ] = copy.deepcopy(changed_value)

    record = sector_app.crack_control_calculation_record(results)
    assessment = record["cases"][0]["assessment"]

    assert assessment["status"] == "NOT ASSESSED"
    assert assessment["verdict"] == "REVIEW"
    assert assessment["acceptance_evidence"] is None
    assert assessment["publication_validation"]["reason"]


def test_changed_governing_crack_response_invalidates_stale_pass_record():
    import sector_app

    contexts = {
        name: {
            "combination": sls.COMBINATION_QUASI_PERMANENT,
            "duration": "long",
            "response_id": "qp",
            "provenance": "controlled QP mapping",
            "solver_provenance": {"state": "long"},
        }
        for name in ("QP",)
    }
    mapping_scope = [{
        "combination": sls.COMBINATION_QUASI_PERMANENT,
        "duration": "long",
        "response": "QP",
        "response_id": "qp",
        "elastic_case": "elastic-1",
        "state": "long",
        "provenance": "controlled QP mapping",
    }]
    criteria = [{
        "id": "qa-durability",
        "kind": sls.CRITERION_DURABILITY,
        "source_type": sls.CRITERION_MODE_STANDARD,
        "source": "QA controlled criterion",
        "required_combination": sls.COMBINATION_QUASI_PERMANENT,
        "limit_mm": 0.30,
        "applicability": {"member": "reinforced"},
    }]
    stale_assessment = sls.crack_assessment(
        {"QP": {"wk": 0.22, "element_id": "R1"}},
        valid=True,
        criteria=criteria,
        response_contexts=contexts,
        response_mapping_scope=mapping_scope,
    )
    assert stale_assessment["verdict"] == "PASS"

    record = sector_app.crack_control_calculation_record({
        "elastic": {
            "show_cw": True,
            "crack_assessment": stale_assessment,
            "crack_responses": {
                "QP": {"wk": 0.45, "element_id": "R1"},
            },
            "crack_dispositions": {"QP": {"status": "OK"}},
            "crack_response_contexts": contexts,
            "crack_response_mapping_scope": mapping_scope,
        },
    })

    recorded = record["cases"][0]
    assert recorded["responses"][0]["wk_mm"] == pytest.approx(0.45)
    assert recorded["assessment"]["status"] == "NOT ASSESSED"
    assert recorded["assessment"]["verdict"] == "REVIEW"
    assert recorded["assessment"]["value"] is None
    assert "immutable acceptance evidence does not match" in (
        recorded["assessment"]["publication_validation"]["reason"]
    )
    assert '"PASS"' not in json.dumps(record)

    changed_element = sector_app.crack_control_calculation_record({
        "elastic": {
            "show_cw": True,
            "crack_assessment": stale_assessment,
            "crack_responses": {
                "QP": {"wk": 0.22, "element_id": "R2"},
            },
            "crack_dispositions": {"QP": {"status": "OK"}},
            "crack_response_contexts": contexts,
            "crack_response_mapping_scope": mapping_scope,
        },
    })
    element_assessment = changed_element["cases"][0]["assessment"]
    assert element_assessment["status"] == "NOT ASSESSED"
    assert "immutable acceptance evidence does not match" in (
        element_assessment["publication_validation"]["reason"]
    )


def test_current_decompression_evidence_preserves_matching_pass_record():
    import sector_app

    contexts = {
        "QP": {
            "combination": sls.COMBINATION_QUASI_PERMANENT,
            "duration": "long",
            "response_id": "qp",
            "provenance": "controlled QP mapping",
            "solver_provenance": {"state": "long"},
        },
    }
    mapping_scope = [{
        "combination": sls.COMBINATION_QUASI_PERMANENT,
        "duration": "long",
        "response": "QP",
        "response_id": "qp",
        "elastic_case": "elastic-1",
        "state": "long",
        "provenance": "controlled QP mapping",
    }]
    response = {
        "wk": 0.18,
        "element_id": "T1",
        "decompression": {
            "status": "OK",
            "value": -0.25,
            "governing": "concrete point 1",
            "reason": "Concrete remains in compression at tendon level.",
            "solver_provenance": {"state": "long"},
        },
    }
    assessment = sls.crack_assessment(
        {"QP": response},
        valid=True,
        criteria=[{
            "id": "qa-decompression",
            "kind": sls.CRITERION_DECOMPRESSION,
            "source_type": sls.CRITERION_MODE_STANDARD,
            "source": "QA controlled decompression criterion",
            "required_combination": sls.COMBINATION_QUASI_PERMANENT,
            "limit_mm": None,
            "applicability": {"member": "bonded prestress"},
        }],
        response_contexts=contexts,
        response_mapping_scope=mapping_scope,
    )
    assert assessment["status"] == "OK"
    assert assessment["verdict"] == "PASS"

    record = sector_app.crack_control_calculation_record({
        "elastic": {
            "show_cw": True,
            "crack_assessment": assessment,
            "crack_responses": {"QP": response},
            "crack_dispositions": {"QP": {"status": "OK"}},
            "crack_response_contexts": contexts,
            "crack_response_mapping_scope": mapping_scope,
        },
    })

    recorded = record["cases"][0]
    assert recorded["assessment"]["status"] == "OK"
    assert recorded["assessment"]["verdict"] == "PASS"
    assert recorded["assessment"]["value"] == pytest.approx(-0.25)
    assert recorded["assessment"]["governing"] == "concrete point 1"
    assert recorded["responses"][0]["decompression"]["status"] == "OK"
    assert "publication_validation" not in recorded["assessment"]


@pytest.mark.parametrize(
    ("field", "changed_value", "reason_text"),
    [
        ("value", -0.10, "calculated acceptance evidence"),
        ("value", True, "decompression evidence is incomplete"),
        (
            "solver_provenance",
            float("nan"),
            "decompression evidence is incomplete",
        ),
        (
            "governing",
            "concrete point 2",
            "calculated acceptance evidence",
        ),
    ],
)
def test_changed_decompression_evidence_invalidates_stale_pass_record(
    field,
    changed_value,
    reason_text,
):
    import sector_app

    contexts = {
        "QP": {
            "combination": sls.COMBINATION_QUASI_PERMANENT,
            "duration": "long",
            "response_id": "qp",
            "provenance": "controlled QP mapping",
            "solver_provenance": {"state": "long"},
        },
    }
    mapping_scope = [{
        "combination": sls.COMBINATION_QUASI_PERMANENT,
        "duration": "long",
        "response": "QP",
        "response_id": "qp",
        "elastic_case": "elastic-1",
        "state": "long",
        "provenance": "controlled QP mapping",
    }]
    original_response = {
        "wk": 0.18,
        "element_id": "T1",
        "decompression": {
            "status": "OK",
            "value": -0.25,
            "governing": "concrete point 1",
            "reason": "Concrete remains in compression at tendon level.",
            "solver_provenance": {"state": "long"},
        },
    }
    assessment = sls.crack_assessment(
        {"QP": original_response},
        valid=True,
        criteria=[{
            "id": "qa-decompression",
            "kind": sls.CRITERION_DECOMPRESSION,
            "source_type": sls.CRITERION_MODE_STANDARD,
            "source": "QA controlled decompression criterion",
            "required_combination": sls.COMBINATION_QUASI_PERMANENT,
            "limit_mm": None,
            "applicability": {"member": "bonded prestress"},
        }],
        response_contexts=contexts,
        response_mapping_scope=mapping_scope,
    )
    changed_response = copy.deepcopy(original_response)
    changed_response["decompression"][field] = changed_value

    record = sector_app.crack_control_calculation_record({
        "elastic": {
            "show_cw": True,
            "crack_assessment": assessment,
            "crack_responses": {"QP": changed_response},
            "crack_dispositions": {"QP": {"status": "OK"}},
            "crack_response_contexts": contexts,
            "crack_response_mapping_scope": mapping_scope,
        },
    })

    recorded = record["cases"][0]["assessment"]
    assert recorded["status"] == "NOT ASSESSED"
    assert recorded["verdict"] == "REVIEW"
    assert recorded["value"] is None
    assert reason_text in recorded["publication_validation"]["reason"]


def test_changed_non_governing_decompression_evidence_invalidates_pass():
    import sector_app

    contexts = {
        name: {
            "combination": sls.COMBINATION_QUASI_PERMANENT,
            "duration": "long",
            "response_id": "long",
            "provenance": "controlled QP mapping",
            "solver_provenance": {"state": "long"},
        }
        for name in ("Fine", "Coarse")
    }
    mapping_scope = [{
        "combination": sls.COMBINATION_QUASI_PERMANENT,
        "duration": "long",
        "response": "QP",
        "response_id": "long",
        "elastic_case": "elastic-1",
        "state": "long",
        "provenance": "controlled QP mapping",
    }]
    response = {
        "wk": 0.18,
        "element_id": "T1",
        "decompression": {
            "status": "OK",
            "value": -0.25,
            "governing": "concrete point 1",
            "reason": "Concrete remains in compression at tendon level.",
            "solver_provenance": {"state": "long"},
        },
    }
    original_responses = {
        "Fine": copy.deepcopy(response),
        "Coarse": copy.deepcopy(response),
    }
    assessment = sls.crack_assessment(
        original_responses,
        valid=True,
        criteria=[{
            "id": "qa-decompression",
            "kind": sls.CRITERION_DECOMPRESSION,
            "source_type": sls.CRITERION_MODE_STANDARD,
            "source": "QA controlled decompression criterion",
            "required_combination": sls.COMBINATION_QUASI_PERMANENT,
            "limit_mm": None,
            "applicability": {"member": "bonded prestress"},
        }],
        response_contexts=contexts,
        response_mapping_scope=mapping_scope,
    )
    assert assessment["status"] == "OK"
    assert assessment["verdict"] == "PASS"
    assert assessment["criteria"][0]["matched_responses"] == [
        "Fine",
        "Coarse",
    ]

    current_responses = copy.deepcopy(original_responses)
    current_responses["Coarse"]["decompression"]["value"] = -0.10
    record = sector_app.crack_control_calculation_record({
        "elastic": {
            "show_cw": True,
            "crack_assessment": assessment,
            "crack_responses": current_responses,
            "crack_dispositions": {
                "Fine": {"status": "OK"},
                "Coarse": {"status": "OK"},
            },
            "crack_response_contexts": contexts,
            "crack_response_mapping_scope": mapping_scope,
        },
    })

    recorded = record["cases"][0]["assessment"]
    assert recorded["status"] == "NOT ASSESSED"
    assert recorded["verdict"] == "REVIEW"
    assert recorded["value"] is None
    assert "conflicting decompression acceptance evidence" in (
        recorded["publication_validation"]["reason"]
    )


def _download_and_autosave_publications(
    sector_app,
    crack_control,
    tmp_path,
    monkeypatch,
):
    calculation = {
        "input_sha256": "stale",
        "crack_control": copy.deepcopy(crack_control),
    }
    state = {"calculation_record": copy.deepcopy(calculation)}
    monkeypatch.setattr(
        sector_app,
        "st",
        SimpleNamespace(session_state=state),
    )
    monkeypatch.setattr(
        sector_app,
        "_invalid_factor_input_keys",
        lambda: (),
    )
    monkeypatch.setattr(
        sector_app,
        "_invalid_crack_input_keys",
        lambda: (),
    )
    monkeypatch.setattr(sector_app, "_project_state", lambda: ({}, {}))

    download_text = sector_app._gather_project()
    download = json.loads(download_text)["calculation"][
        "crack_control"
    ]["cases"][0]["assessment"]

    state["calculation_record"] = copy.deepcopy(calculation)
    monkeypatch.setattr(
        sector_app,
        "_current_table",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        sector_app,
        "_pts_from_df",
        lambda *_args, **_kwargs: [(0, 0), (1, 0), (0, 1)],
    )
    monkeypatch.setattr(
        sector_app,
        "_project_input_hash",
        lambda: "current-input-hash",
    )
    captured = {}

    def capture_autosave(data, path):
        captured["data"] = data
        captured["path"] = path
        return True

    monkeypatch.setattr(sector_app, "_write_autosave", capture_autosave)
    monkeypatch.setattr(
        sector_app,
        "_autosave_path",
        lambda: tmp_path / "autosave.json",
    )

    assert sector_app._perform_autosave() is True
    durable = state["calculation_record"]["crack_control"][
        "cases"
    ][0]["assessment"]
    saved = json.loads(captured["data"])["calculation"][
        "crack_control"
    ]["cases"][0]["assessment"]
    return (download, durable, saved), (download_text, captured["data"])


def _bridge_bound_snapshot():
    decisions = tuple(
        bridge.ApplicabilityDecision(
            check_id=check_id,
            applicability=(
                bridge.REQUIRED
                if check_id == "section_analysis"
                else bridge.NOT_APPLICABLE
            ),
            source=f"DB-{check_id}",
        )
        for check_id in bridge.APPLICABILITY_CHECK_IDS
    )
    return bridge.assess_base_methodology(bridge.BridgeBaseEvidence(
        methodology=bridge.EN1992_2_BASE,
        decisions=decisions,
        has_tendons=False,
        has_hollow_section=False,
        fck_mpa=40.0,
        section_analysis=bridge.ExternalEvidence(
            status=bridge.STATUS_PASS,
            result="section solve converged",
            criterion="requested solver converges",
            source="bridge inherited section solver",
            reason="Elastic SLS-1 converged",
        ),
    ))


def _bridge_fatigue_publication_scalars(*, custom=False):
    import fatigue_analysis
    import fatigue_inputs

    scalars = {
        "design_methodology": bridge.EN1992_2_BASE,
        "fatigue_on": True,
        "fatigue_check_steel": False,
        "fatigue_check_concrete": True,
        "fatigue_edition": fatigue_inputs.EC2_2_2005_AC,
        "fatigue_factor_mode": fatigue_inputs.FACTOR_MODE_PRESET,
        "fatigue_gamma_s": 1.15,
        "fatigue_gamma_c": 1.50,
        "fatigue_gamma_ff": 1.0,
        "fatigue_concrete_method": fatigue_analysis.CONCRETE_MINER,
        "fatigue_concrete_miner_basis": (
            fatigue_inputs.MINER_BASIS_BRIDGE_STANDARD
        ),
        "fatigue_concrete_miner_source": "",
        "fatigue_concrete_c": bridge.STANDARD_CONCRETE_MINER_C,
        fatigue_inputs.BASIS_KEY: fatigue_inputs.default_basis(),
    }
    if custom:
        scalars.update({
            "fatigue_factor_mode": fatigue_inputs.FACTOR_MODE_OVERRIDE,
            "fatigue_factor_approval": (
                "DB-FAT-OVERRIDE-02 / checker approval"
            ),
            "fatigue_gamma_c": 2.0,
        })
    return scalars


def _bridge_concrete_fatigue_snapshot(scalars):
    import fatigue_analysis
    from sector import conformance

    context = fatigue_analysis.bridge_publication_context(scalars)
    assert context["errors"] == []
    records = {
        record["parameter_id"]: record
        for record in context["parameter_conformance"]
    }
    concrete_records = (
        records["fatigue.gamma_c"],
        records["concrete_fatigue.miner_c"],
    )
    status = conformance.aggregate(
        concrete_records,
        analytical_status=conformance.STATUS_PASS,
        selected_standard=context["edition"],
    )["assessment_status"]
    decisions = tuple(
        bridge.ApplicabilityDecision(
            check_id=check_id,
            applicability=(
                bridge.REQUIRED
                if check_id in {"section_analysis", "concrete_fatigue"}
                else bridge.NOT_APPLICABLE
            ),
            source=f"DB-{check_id}",
        )
        for check_id in bridge.APPLICABILITY_CHECK_IDS
    )
    return bridge.assess_base_methodology(bridge.BridgeBaseEvidence(
        methodology=bridge.EN1992_2_BASE,
        decisions=decisions,
        has_tendons=False,
        has_hollow_section=False,
        fck_mpa=40.0,
        section_analysis=bridge.ExternalEvidence(
            status=bridge.STATUS_PASS,
            result="section solve converged",
            criterion="requested solver converges",
            source="bridge inherited section solver",
            reason="Elastic SLS-1 converged",
        ),
        concrete_fatigue=bridge.ExternalEvidence(
            status=status,
            result="50.0 %",
            criterion="<= 100 %",
            source="DS/EN 1992-2:2005/AC:2008 Expression (6.106)",
            reason="solver evidence retained",
            utilisation=0.5,
            evidence=({
                "status": status,
                "analytical_status": bridge.STATUS_PASS,
                "methodology": bridge.EN1992_2_BASE,
                "concrete_method": context["concrete_method"],
                "concrete_miner_basis": context["concrete_miner_basis"],
                "concrete_miner_source": context["concrete_miner_source"],
                "miner_coefficient_c": records[
                    "concrete_fatigue.miner_c"
                ]["actual_value"],
                "parameter_conformance": records[
                    "concrete_fatigue.miner_c"
                ],
                "fatigue_parameter_conformance": concrete_records,
                "fatigue_edition": context["edition"],
                "fatigue_factor_mode": context["factor_mode"],
                "fatigue_factor_approval": context["factor_approval"],
                "fatigue_gamma_ff": context["gamma_ff"],
                "fatigue_basis": context["basis"],
            },),
        ),
    ))


def _fatigue_bound_snapshot():
    import fatigue_analysis
    import fatigue_inputs
    from sector import conformance

    edition = fatigue_inputs.EC2_2023
    gamma_s, gamma_c, factor_basis = (
        fatigue_inputs.resolve_fatigue_factors(
            edition,
            mode=fatigue_inputs.FACTOR_MODE_OVERRIDE,
            gamma_s=0.5,
            gamma_c=2.0,
            approval_reference="DB-FAT-21 / checker approval",
        )
    )
    miner_source = "AUTH-SN-7 / checker approval"
    miner_record = fatigue_analysis.concrete_miner_conformance(
        edition=edition,
        concrete_method=fatigue_analysis.CONCRETE_PROJECT_MINER,
        miner_basis=fatigue_inputs.MINER_BASIS_PROJECT_SN_RELATION,
        miner_source=miner_source,
        coefficient_c=100.0,
        design_methodology=bridge.COMPONENT_METHODS,
    )
    records = [
        factor_basis["parameter_conformance"]["gamma_s"],
        factor_basis["parameter_conformance"]["gamma_c"],
        miner_record,
    ]
    aggregate = conformance.aggregate(
        records,
        analytical_status=conformance.STATUS_PASS,
        selected_standard=edition,
    )
    return fatigue_analysis.calculation_conformance_record(
        {
            "valid": True,
            "converged": True,
            "passed": True,
            "errors": (),
            "edition": edition,
            "design_methodology": bridge.COMPONENT_METHODS,
            "checks": {"reinforcement": True, "concrete": True},
            "concrete_method": fatigue_analysis.CONCRETE_PROJECT_MINER,
            "concrete_miner_basis": (
                fatigue_inputs.MINER_BASIS_PROJECT_SN_RELATION
            ),
            "concrete_miner_source": miner_source,
            "basis": fatigue_inputs.default_basis(),
            "partial_factors": {
                "gamma_s": gamma_s,
                "gamma_c": gamma_c,
                "gamma_ff": 1.0,
            },
            "factor_basis": factor_basis,
            "parameter_conformance": records,
            "conformance": aggregate,
            "assessment_status": aggregate["assessment_status"],
            "qualified_verdict": aggregate["qualified_verdict"],
            "standard_passed": False,
            "concrete_parameters": {
                "c": 100.0,
                "method": fatigue_analysis.CONCRETE_PROJECT_MINER,
                "parameter_conformance": miner_record,
            },
        },
        design_methodology=bridge.COMPONENT_METHODS,
        current_basis=fatigue_inputs.default_basis(),
    )


def test_autosave_validation_receives_canonical_bridge_tables(
    tmp_path,
    monkeypatch,
):
    import bridge_inputs
    import project_io
    import sector_app

    coverage = bridge_inputs.table_from_records(
        [
            {
                "check_id": check_id,
                "applicability": (
                    bridge.REQUIRED
                    if check_id == "reinforcement_fatigue"
                    else bridge.NOT_APPLICABLE
                ),
                "source": f"DB-{check_id}",
                "notes": "",
            }
            for check_id in bridge.APPLICABILITY_CHECK_IDS
        ],
        bridge_inputs.COVERAGE_TABLE_KEY,
    )
    tables = {bridge_inputs.COVERAGE_TABLE_KEY: coverage}
    scalars = {"design_methodology": bridge.EN1992_2_DK_NA}
    digest = project_io.input_sha256(tables, scalars)
    calculation = {
        "input_sha256": digest,
        "matches_saved_inputs": True,
    }
    state = {"calculation_record": copy.deepcopy(calculation)}
    monkeypatch.setattr(
        sector_app,
        "st",
        SimpleNamespace(session_state=state),
    )
    monkeypatch.setattr(
        sector_app,
        "_invalid_factor_input_keys",
        lambda: (),
    )
    monkeypatch.setattr(
        sector_app,
        "_invalid_crack_input_keys",
        lambda: (),
    )
    monkeypatch.setattr(
        sector_app,
        "_project_state",
        lambda: (tables, scalars),
    )
    monkeypatch.setattr(
        sector_app,
        "_current_table",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        sector_app,
        "_pts_from_df",
        lambda *_args, **_kwargs: [(0, 0), (1, 0), (0, 1)],
    )
    monkeypatch.setattr(
        sector_app,
        "_project_input_hash",
        lambda: digest,
    )
    publication_calls = []

    def capture_publication(
        raw_calculation,
        *,
        calculation_inputs,
        input_digest,
    ):
        publication_calls.append(calculation_inputs)
        assert input_digest == digest
        return raw_calculation

    monkeypatch.setattr(
        project_io,
        "publication_safe_calculation_record",
        capture_publication,
    )
    monkeypatch.setattr(
        sector_app,
        "_write_autosave",
        lambda _data, _path: True,
    )
    monkeypatch.setattr(
        sector_app,
        "_autosave_path",
        lambda: tmp_path / "autosave.json",
    )

    assert sector_app._perform_autosave() is True
    assert len(publication_calls) == 2
    autosave_inputs = publication_calls[0]
    assert bridge_inputs.COVERAGE_TABLE_KEY in autosave_inputs
    applicability = {
        decision.check_id: decision.applicability
        for decision in bridge_inputs.decisions(
            autosave_inputs[bridge_inputs.COVERAGE_TABLE_KEY]
        )
    }
    assert applicability["reinforcement_fatigue"] == bridge.REQUIRED
    assert applicability["concrete_fatigue"] == bridge.NOT_APPLICABLE


def test_live_fatigue_view_rejects_missing_basis_on_bound_payload(monkeypatch):
    import sector_app

    payload = _fatigue_bound_snapshot()
    assert payload is not None
    del payload["basis"]
    rendered = {"errors": [], "markdown": []}
    monkeypatch.setattr(
        sector_app,
        "st",
        SimpleNamespace(
            error=lambda message, **_kwargs: rendered["errors"].append(message),
            warning=lambda *_args, **_kwargs: None,
            success=lambda *_args, **_kwargs: None,
            info=lambda *_args, **_kwargs: None,
            markdown=lambda message, **_kwargs: rendered["markdown"].append(
                message
            ),
        ),
    )

    sector_app.fatigue_view(
        {
            "fatigue_on": True,
            "design_methodology": bridge.COMPONENT_METHODS,
        },
        {"fatigue": payload},
    )

    assert any(message.startswith("INVALID -") for message in rendered["errors"])
    assert any(
        "fatigue basis" in message.lower()
        for message in rendered["markdown"]
    )


def test_live_fatigue_helper_rejects_stale_complete_basis():
    import fatigue_inputs
    import sector_app

    payload = _fatigue_bound_snapshot()
    assert payload is not None
    current_basis = {
        **fatigue_inputs.default_basis(),
        "notes": "Current edited basis",
    }

    safe = sector_app._publication_safe_fatigue_result(
        {
            "fatigue_on": True,
            "design_methodology": bridge.COMPONENT_METHODS,
            fatigue_inputs.BASIS_KEY: current_basis,
        },
        {"fatigue": payload},
    )

    assert safe["valid"] is False
    assert safe["passed"] is False
    assert safe["standard_passed"] is False
    assert any(
        "basis conflicts with the calculation input snapshot" in error
        for error in safe["errors"]
    )


@pytest.mark.parametrize(
    "attack",
    ["partial_factor", "missing_basis", "incomplete_basis", "boolean_basis"],
)
def test_download_session_and_autosave_reject_fatigue_evidence_mutation(
    attack,
    tmp_path,
    monkeypatch,
):
    import fatigue_analysis
    import project_io
    import sector_app

    scalars = {"design_methodology": bridge.COMPONENT_METHODS}
    fatigue_record = _fatigue_bound_snapshot()
    assert fatigue_record is not None
    if attack == "partial_factor":
        fatigue_record["partial_factors"]["gamma_s"] = 1.15
    elif attack == "missing_basis":
        del fatigue_record["basis"]
    else:
        if attack == "incomplete_basis":
            del fatigue_record["basis"]["notes"]
        else:
            fatigue_record["basis"]["notes"] = True
        body = {
            key: fatigue_record[key]
            for key in fatigue_analysis._FATIGUE_CONFORMANCE_FIELDS
        }
        fatigue_record["evidence_sha256"] = (
            fatigue_analysis._fatigue_conformance_digest(body)
        )
    calculation = {
        "input_sha256": project_io.input_sha256({}, scalars),
        "fatigue_conformance": fatigue_record,
    }
    state = {"calculation_record": copy.deepcopy(calculation)}
    monkeypatch.setattr(
        sector_app,
        "st",
        SimpleNamespace(session_state=state),
    )
    monkeypatch.setattr(
        sector_app,
        "_invalid_factor_input_keys",
        lambda: (),
    )
    monkeypatch.setattr(
        sector_app,
        "_invalid_crack_input_keys",
        lambda: (),
    )
    monkeypatch.setattr(
        sector_app,
        "_project_state",
        lambda: ({}, scalars),
    )

    download = json.loads(sector_app._gather_project())["calculation"]
    assert "fatigue_conformance" not in download
    assert download["matches_saved_inputs"] is False

    state["calculation_record"] = copy.deepcopy(calculation)
    monkeypatch.setattr(
        sector_app,
        "_current_table",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        sector_app,
        "_pts_from_df",
        lambda *_args, **_kwargs: [(0, 0), (1, 0), (0, 1)],
    )
    monkeypatch.setattr(
        sector_app,
        "_project_input_hash",
        lambda: "current-input-hash",
    )
    captured = {}

    def capture_autosave(data, path):
        captured["data"] = data
        return True

    monkeypatch.setattr(sector_app, "_write_autosave", capture_autosave)
    monkeypatch.setattr(
        sector_app,
        "_autosave_path",
        lambda: tmp_path / "autosave.json",
    )

    assert sector_app._perform_autosave() is True
    assert "fatigue_conformance" not in state["calculation_record"]
    assert state["calculation_record"]["matches_saved_inputs"] is False
    saved = json.loads(captured["data"])["calculation"]
    assert "fatigue_conformance" not in saved
    assert saved["matches_saved_inputs"] is False
    restored = project_io.project_provenance(
        captured["data"]
    )["calculation"]
    assert restored["matches_saved_inputs"] is False


def test_download_session_and_autosave_reject_bridge_binding_mutation(
    tmp_path,
    monkeypatch,
):
    import sector_app

    bridge_record = _bridge_bound_snapshot()
    bridge_record["checks"][0]["result"] = "mutated stored result"
    calculation = {
        "input_sha256": "stale",
        "bridge_methodology": bridge_record,
    }
    state = {"calculation_record": copy.deepcopy(calculation)}
    monkeypatch.setattr(
        sector_app,
        "st",
        SimpleNamespace(session_state=state),
    )
    monkeypatch.setattr(
        sector_app,
        "_invalid_factor_input_keys",
        lambda: (),
    )
    monkeypatch.setattr(
        sector_app,
        "_invalid_crack_input_keys",
        lambda: (),
    )
    monkeypatch.setattr(
        sector_app,
        "_project_state",
        lambda: (
            {},
            {"design_methodology": bridge.EN1992_2_BASE},
        ),
    )

    download_text = sector_app._gather_project()
    download = json.loads(download_text)["calculation"][
        "bridge_methodology"
    ]
    assert download["status"] == bridge.STATUS_INVALID
    assert any(
        "fingerprint does not match" in error
        for error in download["configuration_errors"]
    )

    state["calculation_record"] = copy.deepcopy(calculation)
    monkeypatch.setattr(
        sector_app,
        "_current_table",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        sector_app,
        "_pts_from_df",
        lambda *_args, **_kwargs: [(0, 0), (1, 0), (0, 1)],
    )
    monkeypatch.setattr(
        sector_app,
        "_project_input_hash",
        lambda: "current-input-hash",
    )
    captured = {}

    def capture_autosave(data, path):
        captured["data"] = data
        return True

    monkeypatch.setattr(sector_app, "_write_autosave", capture_autosave)
    monkeypatch.setattr(
        sector_app,
        "_autosave_path",
        lambda: tmp_path / "autosave.json",
    )

    assert sector_app._perform_autosave() is True
    durable = state["calculation_record"]["bridge_methodology"]
    saved = json.loads(captured["data"])["calculation"][
        "bridge_methodology"
    ]
    assert durable["status"] == bridge.STATUS_INVALID
    assert saved["status"] == bridge.STATUS_INVALID
    assert durable == saved


@pytest.mark.parametrize(
    "attack",
    [
        "stale_standard",
        "omitted_gamma_c",
        "stale_gamma_ff",
        "stale_basis",
    ],
)
def test_download_durable_and_autosave_reject_bridge_fatigue_correlation(
    attack,
    tmp_path,
    monkeypatch,
):
    import fatigue_inputs
    import project_io
    import sector_app

    scalars = _bridge_fatigue_publication_scalars(custom=True)
    if attack == "stale_standard":
        bridge_record = _bridge_concrete_fatigue_snapshot(
            _bridge_fatigue_publication_scalars()
        )
    elif attack == "stale_gamma_ff":
        scalars = _bridge_fatigue_publication_scalars()
        scalars["fatigue_gamma_ff"] = 2.0
        bridge_record = _bridge_concrete_fatigue_snapshot(
            _bridge_fatigue_publication_scalars()
        )
    elif attack == "stale_basis":
        bridge_record = _bridge_concrete_fatigue_snapshot(scalars)
        scalars[fatigue_inputs.BASIS_KEY] = {
            **fatigue_inputs.default_basis(),
            "authority": fatigue_inputs.AUTHORITY_VD,
            "method": fatigue_inputs.METHOD_VD_FLM4,
            "spectrum_source": "VD project basis section 6.8",
            "cycle_count_source": "Traffic register T-04",
        }
    else:
        bridge_record = _bridge_concrete_fatigue_snapshot(scalars)
        concrete = next(
            check for check in bridge_record["checks"]
            if check["check_id"] == "concrete_fatigue"
        )
        row = concrete["evidence"][0]
        row["fatigue_parameter_conformance"] = [
            record
            for record in row["fatigue_parameter_conformance"]
            if record["parameter_id"] != "fatigue.gamma_c"
        ]
        row["status"] = bridge.STATUS_PASS
        concrete["status"] = bridge.STATUS_PASS
        bridge_record["status"] = bridge.STATUS_PASS
        bridge_record["evidence_fingerprint"] = (
            bridge.bridge_evidence_fingerprint(
                bridge_record["checks"],
                bridge_record["configuration_errors"],
            )
        )
    digest = project_io.input_sha256({}, scalars)
    calculation = {
        "input_sha256": digest,
        "bridge_methodology": bridge_record,
    }
    state = {"calculation_record": copy.deepcopy(calculation)}
    monkeypatch.setattr(
        sector_app,
        "st",
        SimpleNamespace(session_state=state),
    )
    monkeypatch.setattr(
        sector_app,
        "_invalid_factor_input_keys",
        lambda: (),
    )
    monkeypatch.setattr(
        sector_app,
        "_invalid_crack_input_keys",
        lambda: (),
    )
    monkeypatch.setattr(
        sector_app,
        "_project_state",
        lambda: ({}, scalars),
    )

    download_text = sector_app._gather_project()
    download_payload = json.loads(download_text)
    download = download_payload["calculation"]
    assert download["matches_saved_inputs"] is False
    assert download["bridge_methodology"]["status"] == bridge.STATUS_INVALID
    assert download["bridge_methodology"]["publication_validation"][
        "status"
    ] == "REJECTED"
    assert next(
        check
        for check in download["bridge_methodology"]["checks"]
        if check["check_id"] == "concrete_fatigue"
    )["status"] == bridge.STATUS_NOT_ASSESSED

    state["calculation_record"] = copy.deepcopy(calculation)
    monkeypatch.setattr(
        sector_app,
        "_current_table",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        sector_app,
        "_pts_from_df",
        lambda *_args, **_kwargs: [(0, 0), (1, 0), (0, 1)],
    )
    monkeypatch.setattr(
        sector_app,
        "_project_input_hash",
        lambda: digest,
    )
    captured = {}

    def capture_autosave(data, path):
        captured["data"] = data
        return True

    monkeypatch.setattr(sector_app, "_write_autosave", capture_autosave)
    monkeypatch.setattr(
        sector_app,
        "_autosave_path",
        lambda: tmp_path / "autosave.json",
    )

    assert sector_app._perform_autosave() is True
    durable = state["calculation_record"]
    saved = json.loads(captured["data"])["calculation"]
    loaded = project_io.project_provenance(
        captured["data"]
    )["calculation"]
    for record in (durable, saved, loaded):
        assert record["matches_saved_inputs"] is False
        assert record["bridge_methodology"]["publication_validation"][
            "status"
        ] == "REJECTED"
        assert next(
            check
            for check in record["bridge_methodology"]["checks"]
            if check["check_id"] == "concrete_fatigue"
        )["status"] == bridge.STATUS_NOT_ASSESSED


def test_download_session_and_autosave_reject_bridge_methodology_mismatch(
    tmp_path,
    monkeypatch,
):
    import project_io
    import sector_app

    scalars = {"design_methodology": bridge.COMPONENT_METHODS}
    calculation = {
        "input_sha256": project_io.input_sha256({}, scalars),
        "bridge_methodology": _bridge_bound_snapshot(),
    }
    state = {"calculation_record": copy.deepcopy(calculation)}
    monkeypatch.setattr(
        sector_app,
        "st",
        SimpleNamespace(session_state=state),
    )
    monkeypatch.setattr(
        sector_app,
        "_invalid_factor_input_keys",
        lambda: (),
    )
    monkeypatch.setattr(
        sector_app,
        "_invalid_crack_input_keys",
        lambda: (),
    )
    monkeypatch.setattr(
        sector_app,
        "_project_state",
        lambda: ({}, scalars),
    )

    download_payload = json.loads(sector_app._gather_project())
    download = download_payload["calculation"]["bridge_methodology"]
    assert download["status"] == bridge.STATUS_INVALID
    assert download["publication_validation"]["status"] == "REJECTED"
    assert download_payload["calculation"]["matches_saved_inputs"] is False

    state["calculation_record"] = copy.deepcopy(calculation)
    monkeypatch.setattr(
        sector_app,
        "_current_table",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        sector_app,
        "_pts_from_df",
        lambda *_args, **_kwargs: [(0, 0), (1, 0), (0, 1)],
    )
    monkeypatch.setattr(
        sector_app,
        "_project_input_hash",
        lambda: project_io.input_sha256({}, scalars),
    )
    captured = {}

    def capture_autosave(data, path):
        captured["data"] = data
        return True

    monkeypatch.setattr(sector_app, "_write_autosave", capture_autosave)
    monkeypatch.setattr(
        sector_app,
        "_autosave_path",
        lambda: tmp_path / "autosave.json",
    )

    assert sector_app._perform_autosave() is True
    durable = state["calculation_record"]["bridge_methodology"]
    saved_payload = json.loads(captured["data"])
    saved = saved_payload["calculation"]["bridge_methodology"]
    assert durable == saved
    assert durable["status"] == bridge.STATUS_INVALID
    assert durable["publication_validation"]["status"] == "REJECTED"
    assert saved_payload["calculation"]["matches_saved_inputs"] is False


@pytest.mark.parametrize(
    ("mutation", "changed_value"),
    [
        ("response_id", "other"),
        ("duration", "short"),
        ("provenance", "map-v2"),
        ("solver_provenance", {"solve": "v2", "converged": True}),
        ("scope_duration", "short"),
    ],
)
def test_download_session_and_autosave_reject_width_binding_mutations(
    mutation,
    changed_value,
    tmp_path,
    monkeypatch,
):
    import sector_app

    record = sector_app.crack_control_calculation_record(
        _canonical_app_width_results()
    )
    assert record["cases"][0]["assessment"]["verdict"] == "PASS"
    case = record["cases"][0]
    if mutation.startswith("scope_"):
        case["response_mapping_scope"][0][
            mutation.removeprefix("scope_")
        ] = copy.deepcopy(changed_value)
    else:
        for response in case["responses"]:
            response["context"][mutation] = copy.deepcopy(changed_value)

    assessments, texts = _download_and_autosave_publications(
        sector_app,
        record,
        tmp_path,
        monkeypatch,
    )

    for assessment in assessments:
        assert assessment["status"] == "NOT ASSESSED"
        assert assessment["verdict"] == "REVIEW"
        assert assessment["acceptance_evidence"] is None
    assert all('"verdict": "PASS"' not in text for text in texts)


@pytest.mark.parametrize(
    "malformation",
    [
        pytest.param("response-container", id="response-container"),
        pytest.param("text-width", id="text-crack-width"),
    ],
)
def test_download_session_and_autosave_reject_malformed_binding_schema(
    malformation,
    tmp_path,
    monkeypatch,
):
    import sector_app

    record = sector_app.crack_control_calculation_record(
        _canonical_app_width_results()
    )
    binding = record["cases"][0]["assessment"]["criteria"][0][
        "acceptance_evidence"
    ]
    if malformation == "response-container":
        binding["matched_responses"] = ["Fine"]
    else:
        for response in binding["matched_responses"]:
            acceptance = response["acceptance"]
            acceptance["value_mm"] = str(acceptance["value_mm"])
        binding["outcome"]["value"] = str(binding["outcome"]["value"])
    _reseal_app_acceptance_binding(binding)

    assessments, texts = _download_and_autosave_publications(
        sector_app,
        record,
        tmp_path,
        monkeypatch,
    )

    for assessment in assessments:
        assert assessment["status"] == "NOT ASSESSED"
        assert assessment["verdict"] == "REVIEW"
        assert assessment["acceptance_evidence"] is None
        assert "invalid immutable acceptance evidence" in (
            assessment["publication_validation"]["reason"]
        )
    assert all('"verdict": "PASS"' not in text for text in texts)


@pytest.mark.parametrize(
    ("field", "changed_value"),
    [
        ("status", "EXCEEDED"),
        ("value", -0.10),
        ("governing", "concrete point 2"),
        ("solver_provenance", {"state": "changed"}),
    ],
)
def test_download_session_and_autosave_reject_decompression_mutations(
    field,
    changed_value,
    tmp_path,
    monkeypatch,
):
    import sector_app

    contexts = {
        "QP": {
            "combination": sls.COMBINATION_QUASI_PERMANENT,
            "duration": "long",
            "response_id": "qp",
            "provenance": "controlled QP mapping",
            "solver_provenance": {"state": "long"},
        },
    }
    mapping_scope = [{
        "combination": sls.COMBINATION_QUASI_PERMANENT,
        "duration": "long",
        "response": "QP",
        "response_id": "qp",
        "elastic_case": "elastic-1",
        "state": "long",
        "provenance": "controlled QP mapping",
    }]
    response = {
        "wk": 0.18,
        "element_id": "T1",
        "decompression": {
            "status": "OK",
            "value": -0.25,
            "governing": "concrete point 1",
            "solver_provenance": {"state": "long"},
        },
    }
    assessment = sls.crack_assessment(
        {"QP": response},
        valid=True,
        criteria=[{
            "id": "qa-decompression",
            "kind": sls.CRITERION_DECOMPRESSION,
            "source_type": sls.CRITERION_MODE_STANDARD,
            "source": "QA controlled decompression criterion",
            "required_combination": sls.COMBINATION_QUASI_PERMANENT,
            "limit_mm": None,
            "applicability": {"member": "bonded prestress"},
        }],
        response_contexts=contexts,
        response_mapping_scope=mapping_scope,
    )
    record = sector_app.crack_control_calculation_record({
        "elastic": {
            "show_cw": True,
            "crack_assessment": assessment,
            "crack_responses": {"QP": response},
            "crack_dispositions": {"QP": {"status": "OK"}},
            "crack_response_contexts": contexts,
            "crack_response_mapping_scope": mapping_scope,
        },
    })
    assert record["cases"][0]["assessment"]["verdict"] == "PASS"
    record["cases"][0]["responses"][0]["decompression"][
        field
    ] = copy.deepcopy(changed_value)

    assessments, texts = _download_and_autosave_publications(
        sector_app,
        record,
        tmp_path,
        monkeypatch,
    )

    for published in assessments:
        assert published["status"] == "NOT ASSESSED"
        assert published["verdict"] == "REVIEW"
        assert published["acceptance_evidence"] is None
    assert all('"verdict": "PASS"' not in text for text in texts)


def test_download_and_autosave_share_decompression_publication_guard(
    tmp_path,
    monkeypatch,
):
    import sector_app

    contexts = {
        "QP": {
            "combination": sls.COMBINATION_QUASI_PERMANENT,
            "duration": "long",
            "response_id": "qp",
            "provenance": "controlled QP mapping",
            "solver_provenance": {"state": "long"},
        },
    }
    mapping_scope = [{
        "combination": sls.COMBINATION_QUASI_PERMANENT,
        "duration": "long",
        "response": "QP",
        "response_id": "qp",
        "elastic_case": "elastic-1",
        "state": "long",
        "provenance": "controlled QP mapping",
    }]
    response = {
        "wk": 0.18,
        "element_id": "T1",
        "decompression": {
            "status": "OK",
            "value": -0.25,
            "governing": "concrete point 1",
            "solver_provenance": {"state": "long"},
        },
    }
    assessment = sls.crack_assessment(
        {"QP": response},
        valid=True,
        criteria=[{
            "id": "qa-decompression",
            "kind": sls.CRITERION_DECOMPRESSION,
            "source_type": sls.CRITERION_MODE_STANDARD,
            "source": "QA controlled decompression criterion",
            "required_combination": sls.COMBINATION_QUASI_PERMANENT,
            "limit_mm": None,
            "applicability": {"member": "bonded prestress"},
        }],
        response_contexts=contexts,
        response_mapping_scope=mapping_scope,
    )
    invalid_response = copy.deepcopy(response)
    invalid_response["decompression"]["solver_provenance"][
        "residual"
    ] = float("inf")
    stale_record = {
        "cases": [{
            "case": "SLS-QP",
            "assessment": assessment,
            "response_mapping_scope": mapping_scope,
            "responses": [{
                "name": "QP",
                "wk_mm": invalid_response["wk"],
                "element_id": invalid_response["element_id"],
                "decompression": invalid_response["decompression"],
                "acceptance_role": "criterion input",
                "context": contexts["QP"],
            }],
        }],
    }
    calculation = {
        "input_sha256": "stale",
        "crack_control": stale_record,
    }
    state = {"calculation_record": copy.deepcopy(calculation)}
    monkeypatch.setattr(
        sector_app,
        "st",
        SimpleNamespace(session_state=state),
    )
    monkeypatch.setattr(
        sector_app,
        "_invalid_factor_input_keys",
        lambda: (),
    )
    monkeypatch.setattr(
        sector_app,
        "_invalid_crack_input_keys",
        lambda: (),
    )
    monkeypatch.setattr(sector_app, "_project_state", lambda: ({}, {}))

    download_text = sector_app._gather_project()
    download_record = json.loads(download_text)["calculation"][
        "crack_control"
    ]
    download_assessment = download_record["cases"][0]["assessment"]
    assert download_assessment["status"] == "NOT ASSESSED"
    assert download_assessment["verdict"] == "REVIEW"
    assert "Infinity" not in download_text

    state["calculation_record"] = copy.deepcopy(calculation)
    monkeypatch.setattr(
        sector_app,
        "_current_table",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        sector_app,
        "_pts_from_df",
        lambda *_args, **_kwargs: [(0, 0), (1, 0), (0, 1)],
    )
    monkeypatch.setattr(
        sector_app,
        "_project_input_hash",
        lambda: "current-input-hash",
    )
    captured = {}

    def capture_autosave(data, path):
        captured["data"] = data
        captured["path"] = path
        return True

    monkeypatch.setattr(sector_app, "_write_autosave", capture_autosave)
    monkeypatch.setattr(
        sector_app,
        "_autosave_path",
        lambda: tmp_path / "autosave.json",
    )

    assert sector_app._perform_autosave() is True
    durable = state["calculation_record"]["crack_control"][
        "cases"
    ][0]["assessment"]
    saved = json.loads(captured["data"])["calculation"][
        "crack_control"
    ]["cases"][0]["assessment"]
    assert durable["status"] == "NOT ASSESSED"
    assert saved["status"] == "NOT ASSESSED"
    assert "Infinity" not in captured["data"]


def test_crack_panel_labels_decompression_evidence_in_mpa(monkeypatch):
    import sector_app

    rendered = {
        "success": [],
        "dataframes": [],
    }
    fake_st = SimpleNamespace(
        markdown=lambda *_args, **_kwargs: None,
        caption=lambda *_args, **_kwargs: None,
        success=lambda message, **_kwargs: rendered["success"].append(message),
        error=lambda *_args, **_kwargs: None,
        warning=lambda *_args, **_kwargs: None,
        info=lambda *_args, **_kwargs: None,
        dataframe=lambda data, **_kwargs: rendered["dataframes"].append(data),
    )
    monkeypatch.setattr(sector_app, "st", fake_st)
    sector_app._crack_width_panel({
        "crack": None,
        "crack_short": None,
        "crack_code": "EN 1992-1-1:2023",
        "crack_assessment": {
            "status": "OK",
            "criterion": sls.CRITERION_DECOMPRESSION,
            "value": -0.25,
            "limit": None,
            "case": "QP",
            "governing": "concrete point 1",
            "required_combination": sls.COMBINATION_QUASI_PERMANENT,
            "criterion_source": "QA controlled criterion",
            "criteria": [{
                "kind": sls.CRITERION_DECOMPRESSION,
                "status": "OK",
                "value": -0.25,
                "limit": None,
                "matched_responses": ["QP"],
                "required_combination": (
                    sls.COMBINATION_QUASI_PERMANENT
                ),
            }],
            "response_contexts": {},
        },
    })

    assert len(rendered["success"]) == 1
    assert "-0.250 MPa" in rendered["success"][0]
    assert "-0.250 mm" not in rendered["success"][0]
    criterion_row = rendered["dataframes"][0][0]
    assert criterion_row["Limit / requirement"] == "compression required"
    assert criterion_row["Result"] == "-0.250 MPa"


def test_2023_protection_route_change_invalidates_elastic_cache():
    at = _fresh()
    at.run()
    _set(
        at,
        ("radio", "mode", "Elastic"),
        ("number_input", "el_long_Mx", 400.0),
        ("number_input", "el_short_Mx", 100.0),
        ("checkbox", "sls_cw", True),
        ("selectbox", "sls_code", "EN 1992-1-1:2023"),
    )
    _set(
        at,
        ("selectbox", "sls_prestress_class", sls.PRESTRESS_BONDED),
        ("selectbox", "sls_exposure_class", sls.EXPOSURE_XC2_XC4),
        (
            "selectbox",
            "sls_long_combination",
            sls.COMBINATION_QUASI_PERMANENT,
        ),
        (
            "selectbox",
            "sls_total_combination",
            sls.COMBINATION_FREQUENT,
        ),
    )
    _set(
        at,
        (
            "selectbox",
            "sls_protection_class",
            sls.PROTECTION_LEVEL_1_OR_PRETENSIONED,
        ),
    )
    _calculate(at)
    first = at.session_state["results"]["elastic"]
    assert [
        (item["kind"], item["required_combination"])
        for item in first["crack_criteria"]
    ] == [
        (sls.CRITERION_DURABILITY, sls.COMBINATION_FREQUENT),
        (sls.CRITERION_DECOMPRESSION, sls.COMBINATION_QUASI_PERMANENT),
    ]

    _set_and_click(
        at,
        "calculate",
        (
            "selectbox",
            "sls_protection_class",
            sls.PROTECTION_LEVEL_2_OR_3,
        ),
    )
    second = at.session_state["results"]["elastic"]

    assert second is not first
    assert [
        (item["kind"], item["required_combination"])
        for item in second["crack_criteria"]
    ] == [
        (sls.CRITERION_DURABILITY, sls.COMBINATION_QUASI_PERMANENT),
    ]


def test_missing_response_combination_is_review_with_mapping_provenance():
    at = _fresh()
    at.run()
    _set_and_click(
        at,
        "calculate",
        ("radio", "mode", "Elastic"),
        ("number_input", "el_long_Mx", 400.0),
        ("checkbox", "sls_cw", True),
        ("text_input", "sls_exposure_context", "XC3 / durability"),
    )

    assessment = at.session_state["results"]["elastic"]["crack_assessment"]
    assert assessment["status"] == "NOT ASSESSED"
    assert assessment["verdict"] == "REVIEW"
    assert "No calculated response" in assessment["reason"]
    assert assessment["response_contexts"]["Long-term"]["combination"] == (
        sls.COMBINATION_UNSPECIFIED
    )
    assert "long_combination table field" in (
        assessment["response_contexts"]["Long-term"]["provenance"]
    )


def test_crack_limit_verdict_and_candidate_table_are_retained():
    at = _fresh()
    at.run()
    _set_and_click(
        at, "calculate",
        ("radio", "mode", "Elastic"),
        ("number_input", "el_long_Mx", 400.0),
        ("checkbox", "sls_cw", True),
        (
            "selectbox",
            "sls_long_combination",
            sls.COMBINATION_QUASI_PERMANENT,
        ),
        ("number_input", "sls_wk_limit", 0.01),
        ("text_input", "sls_exposure_context", "XC3 / durability"),
        ("text_input", "sls_limit_source", "Project crack criterion"),
    )
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    assert e["crack_assessment"]["status"] == "EXCEEDED"
    assert e["crack_assessment"]["limit"] == pytest.approx(0.01)
    assert e["crack_assessment"]["case"] == "Long-term"
    assert e["crack_assessment"]["governing"].startswith(("R", "P"))
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
        (
            "selectbox",
            "sls_long_combination",
            sls.COMBINATION_QUASI_PERMANENT,
        ),
        ("number_input", "sls_wk_limit", 0.25),
        ("text_input", "sls_exposure_context", "XC3 / durability"),
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
        (
            "selectbox",
            "sls_long_combination",
            sls.COMBINATION_QUASI_PERMANENT,
        ),
        ("text_input", "sls_exposure_context", "XC3 / durability"),
    )
    assert not at.exception
    e = at.session_state["results"]["elastic"]
    for key in ("crack", "crack_short", "crack_coarse", "crack_short_coarse"):
        assert e[key] is not None and e[key]["wk"] > 0.0
    assert e["crack"]["coarse"] is False and e["crack_coarse"]["coarse"] is True
    assert e["crack_coarse"]["wk"] < e["crack"]["wk"]             # coarse < fine, long-term
    assert e["crack_short_coarse"]["wk"] < e["crack_short"]["wk"]  # coarse < fine, short-term
    acceptance_status = e["crack_assessment"]["status"]
    assert acceptance_status in {"OK", "EXCEEDED"}
    criterion = next(
        item
        for item in e["crack_assessment"]["criteria"]
        if item["status"] == acceptance_status
    )
    assert criterion["matched_responses"] == [
        "Long-term (fine)",
        "Long-term (coarse)",
    ]
    recorded = at.session_state["calculation_record"]["crack_control"][
        "cases"
    ][0]["assessment"]
    assert recorded["status"] == acceptance_status
    assert recorded["verdict"] == (
        "PASS" if acceptance_status == "OK" else "FAIL"
    )


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


def test_ec2_2023_mixed_reinforcement_fails_closed_without_xi_then_calculates():
    at = _fresh_qs(mode="Elastic")
    _set_and_click(at, "qs_apply", ("number_input", "tnd_n", 4))
    _set_and_click(
        at,
        "calculate",
        ("number_input", "pre_IS", 5.0),
        ("number_input", "el_long_Mx", 400.0),
        ("checkbox", "sls_cw", True),
        ("selectbox", "sls_code", "EN 1992-1-1:2023"),
        (
            "selectbox",
            "sls_exposure_class",
            sls.EXPOSURE_XC2_XC4,
        ),
        (
            "selectbox",
            "sls_exposure_class",
            sls.EXPOSURE_XC2_XC4,
        ),
        (
            "selectbox",
            "sls_long_combination",
            sls.COMBINATION_QUASI_PERMANENT,
        ),
        ("text_input", "sls_exposure_context", "XC3 / durability"),
    )
    assert not at.exception
    missing = at.session_state["results"]["elastic"]
    assert missing["crack_assessment"]["status"] == "NOT ASSESSED"
    assert "bond ratio xi" in missing["crack_assessment"]["reason"]
    assert missing["crack_assessment"]["value"] is None
    _select_view(at, "Results Overview")
    assert any(
        item.value.startswith("NOT ASSESSED -")
        for item in at.warning
    )

    _set_and_click(
        at,
        "calculate",
        ("number_input", "sls_tendon_xi", 0.50),
    )
    assert not at.exception
    calculated = at.session_state["results"]["elastic"]
    assert calculated["crack_assessment"]["status"] in {"OK", "EXCEEDED"}
    assert calculated["crack"] is not None
    assert calculated["crack"]["ap_eff"] > 0.0
    assert 0.0 < calculated["crack"]["ap_eff_weighted"] < \
        calculated["crack"]["ap_eff"]
    assert calculated["crack"]["xi1_min"] > 0.0
    assert calculated["crack"]["xi1_max"] <= 1.0
    tendon_candidates = [
        candidate
        for candidate in calculated["crack"]["candidates"]
        if candidate["element_type"] == "Tendon"
    ]
    assert tendon_candidates
    latest = at.session_state["_latest_inputs"]
    n_bars = len(latest["bars"])
    for candidate in tendon_candidates:
        tendon_index = candidate["element_no"] - 1
        material = latest["tendon_materials"][tendon_index]
        locked_in_mpa = material.Es * material.IS
        assert locked_in_mpa > 0.0
        global_index = n_bars + tendon_index
        # The long-term crack candidate is the passive increment Delta sigma_p:
        # the combined solver's displayed Long column includes Ep*IS once, while
        # analyse_cracking already returns the passive value.
        assert candidate["sigma_s"] == pytest.approx(
            calculated["long"][global_index] - locked_in_mpa,
            rel=0.02,
        )


def test_ec2_2023_uniform_direct_tension_is_explicitly_scoped():
    at = _fresh_qs(mode="Elastic")
    _set_and_click(
        at,
        "qs_apply",
        ("number_input", "bot_n", 4),
        ("number_input", "top_n", 4),
        ("number_input", "bot_d", 16.0),
        ("number_input", "top_d", 16.0),
        ("number_input", "bot_c_mm", 40.0),
        ("number_input", "top_c_mm", 40.0),
    )
    _set_and_click(
        at,
        "calculate",
        ("radio", "mode", "Elastic"),
        ("number_input", "el_long_P", 1000.0),
        ("number_input", "el_long_Mx", 0.0),
        ("number_input", "el_long_My", 0.0),
        ("number_input", "el_short_P", 0.0),
        ("number_input", "el_short_Mx", 0.0),
        ("number_input", "el_short_My", 0.0),
        ("checkbox", "sls_cw", True),
        ("selectbox", "sls_code", "EN 1992-1-1:2023"),
        (
            "selectbox",
            "sls_exposure_class",
            sls.EXPOSURE_XC2_XC4,
        ),
        (
            "selectbox",
            "sls_long_combination",
            sls.COMBINATION_QUASI_PERMANENT,
        ),
        ("text_input", "sls_exposure_context", "XC3 / appearance"),
    )
    assert not at.exception
    elastic = at.session_state["results"]["elastic"]
    assert elastic["crack_assessment"]["status"] in {
        "OK", "EXCEEDED"
    }, elastic["crack_assessment"].get("reason")
    assert elastic["crack"]["direct_tension"] is True
    assert elastic["crack"]["scope"] == "uniform-direct-tension"
    assert elastic["crack"]["kfl"] == pytest.approx(1.0)
    assert elastic["crack"]["k1_r"] == pytest.approx(1.0)
    _select_view(at, "Results Overview")
    assert any(
        "Crack-control conclusion limitation" in item.value
        for item in at.warning
    )
    _select_view(at, "Elastic Results")
    assert not at.exception
    assert any(
        "Crack-control scope" in item.value
        for item in at.warning
    )


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
    # Both duration-state crack widths remain reported. Acceptance combination is
    # a separate explicit input and is not inferred in this calculation-only test.
    assert e["crack"] is not None and e["crack"]["wk"] > 0.0
    assert e["crack_short"] is not None and e["crack_short"]["wk"] > 0.0


def test_short_term_only_crack_verdict_ignores_no_tension_long_term():
    at = _fresh()
    at.run()
    _set_and_click(
        at,
        "calculate",
        ("radio", "mode", "Elastic"),
        ("number_input", "el_long_Mx", 0.0),
        ("number_input", "el_short_Mx", 400.0),
        ("checkbox", "sls_cw", True),
        (
            "selectbox",
            "sls_total_combination",
            sls.COMBINATION_QUASI_PERMANENT,
        ),
        ("text_input", "sls_exposure_context", "XC3 / durability"),
    )

    assert not at.exception
    elastic = at.session_state["results"]["elastic"]
    assert elastic["crack"] is None
    assert elastic["crack_short"] is not None
    assert elastic["crack_dispositions"]["Long-term"]["status"] == (
        "NOT APPLICABLE"
    )
    assert elastic["crack_assessment"]["status"] in {"OK", "EXCEEDED"}
    assert elastic["crack_assessment"]["case"] == "Total (long + short)"


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


def test_pr06_app_project_shear_method_is_qualified_and_switch_invalidates():
    at = _fresh()
    at.run()
    _set(at, ("checkbox", "shear_on", True))
    _set(
        at,
        ("toggle", "shear_interaction_on", True),
        (
            "selectbox",
            "shear_interaction_method",
            multidirectional.SHEAR_METHOD_PROJECT,
        ),
        ("checkbox", "shear_interaction_domain_confirmed", True),
        ("number_input", "shear_interaction_exponent", 137.0),
        (
            "text_input",
            "shear_interaction_source",
            "Project DB clause INT-06",
        ),
        (
            "text_input",
            "shear_interaction_approval",
            "Checker approval QA-06",
        ),
    )
    _set_and_click(
        at,
        "calculate",
        ("number_input", "shear_Vx", 1.0),
        ("number_input", "shear_Vy", 1.0),
    )

    assert not at.exception
    shear = at.session_state["results"]["shear"]
    assert set(shear["directions"]) == {"vx", "vy"}
    assert all(
        item["status"] == "PASS"
        for item in shear["directions"].values()
    )
    assert shear["interaction"]["verdict"] == "APPROVED CUSTOM PASS"
    assert shear["interaction"]["qualification"] == "APPROVED CUSTOM"
    assert shear["interaction"]["parameters"]["exponent"] == pytest.approx(
        137.0
    )
    assert shear["status"] == "REVIEW"
    record = at.session_state["calculation_record"][
        "multidirectional_interaction"
    ]
    assert record["shear_cases"][0]["interaction"][
        "evidence_fingerprint"
    ]

    prior_signature = at.session_state["result_sig"]
    _goto_page(at, "Inputs")
    at.selectbox(key="shear_interaction_method").set_value(
        multidirectional.SHEAR_METHOD_EN_2023
    ).run()
    assert at.session_state["_latest_inputs"]["signature"] != prior_signature
    _calculate(at)
    switched = at.session_state["results"]["shear"]["interaction"]
    assert switched["status"] == "NOT ASSESSED"
    assert switched["interaction_assessed"] is False
    assert "outside or missing its stated domain" in switched["reason"]


def test_pr06_enabled_without_method_keeps_vx_vy_and_withholds_aggregate():
    at = _fresh()
    at.run()
    _set(at, ("checkbox", "shear_on", True))
    _set(at, ("toggle", "shear_interaction_on", True))
    _set_and_click(
        at,
        "calculate",
        ("number_input", "shear_Vx", 1.0),
        ("number_input", "shear_Vy", 1.0),
    )

    assert not at.exception
    assert (
        "_case_error" not in at.session_state
        or not at.session_state["_case_error"]
    )
    shear = at.session_state["results"]["shear"]
    assert set(shear["directions"]) == {"vx", "vy"}
    assert all(
        item["status"] == "PASS"
        for item in shear["directions"].values()
    )
    assert shear["interaction"]["status"] == "NOT ASSESSED"
    assert shear["interaction_assessed"] is False
    assert shear["status"] == "REVIEW"


def test_pr06_hostile_interaction_state_blocks_calculation_save_and_autosave(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path))
    at = _fresh()
    hostile = {
        "shear_interaction_on": np.bool_(True),
        "shear_interaction_method": ["not", "a", "selection"],
        "shear_interaction_exponent": math.nan,
        "shear_interaction_source": {"not": "text"},
    }
    for key, value in hostile.items():
        at.session_state[key] = value
    at.session_state["_durable_input_scalars"] = dict(hostile)

    at.run()

    expected = tuple(sorted(hostile))
    assert not at.exception
    assert at.session_state["_invalid_interaction_input_keys"] == expected
    inp = at.session_state["_latest_inputs"]
    assert inp["invalid_interaction_input_keys"] == expected
    assert multidirectional.validation_errors(inp)
    assert any(
        "Rejected malformed multidirectional state" in item.value
        for item in at.error
    )

    at.session_state["_autosave_t"] = 0.0
    _calculate(at)
    assert "rejected multidirectional interaction fields" in (
        at.session_state["_case_error"]
    )
    assert not (tmp_path / "autosave.json").exists()

    _goto_page(at, "Inputs")
    at.button(key="confirm_shear_interaction_repairs").click().run()
    assert "_invalid_interaction_input_keys" not in at.session_state


def test_pr06_app_crack_method_binds_current_canonical_criterion():
    at = _fresh()
    at.run()
    _set(
        at,
        ("radio", "mode", "Elastic"),
        ("number_input", "el_long_Mx", 400.0),
        ("checkbox", "sls_cw", True),
        ("selectbox", "sls_code", "EN 1992-1-1:2023"),
        (
            "selectbox",
            "sls_exposure_class",
            sls.EXPOSURE_XC2_XC4,
        ),
        (
            "selectbox",
            "sls_long_combination",
            sls.COMBINATION_QUASI_PERMANENT,
        ),
        ("text_input", "sls_exposure_context", "XC3 / durability"),
    )
    case_id = str(first_case_value(at, "el_case_id"))
    _set(
        at,
        ("toggle", "crack_interaction_on", True),
        (
            "selectbox",
            "crack_interaction_method",
            multidirectional.CRACK_METHOD_PROJECT,
        ),
        ("text_input", "crack_interaction_case_id", case_id),
        (
            "text_input",
            "crack_interaction_criterion_id",
            "standard-durability",
        ),
        (
            "selectbox",
            "crack_interaction_combination",
            sls.COMBINATION_QUASI_PERMANENT,
        ),
        ("checkbox", "crack_interaction_domain_confirmed", True),
        ("number_input", "crack_interaction_component_x_mm", 0.10),
        ("number_input", "crack_interaction_component_y_mm", 0.10),
        ("number_input", "crack_interaction_limit_x_mm", 0.30),
        ("number_input", "crack_interaction_limit_y_mm", 0.30),
        ("number_input", "crack_interaction_exponent", 2.0),
        (
            "text_input",
            "crack_interaction_source",
            "Project crack note CR-06",
        ),
        (
            "text_input",
            "crack_interaction_approval",
            "Checker approval AC-06",
        ),
    )
    _calculate(at)

    assert not at.exception
    elastic = at.session_state["results"]["elastic"]
    interaction = at.session_state["results"]["crack_interaction"]
    criterion = next(
        item
        for item in elastic["crack_assessment"]["criteria"]
        if item["criterion_id"] == "standard-durability"
    )
    assert interaction["verdict"] == "APPROVED CUSTOM PASS"
    assert interaction["criterion"]["elastic_case"] == case_id
    assert interaction["criterion"]["required_combination"] == (
        sls.COMBINATION_QUASI_PERMANENT
    )
    assert interaction["criterion"]["acceptance_fingerprint"] == (
        criterion["acceptance_evidence"]["fingerprint"]
    )
    assert elastic["crack_interaction"] == interaction
    assert elastic["crack_assessment"]["status"] in {"OK", "EXCEEDED"}


def test_pr06_download_durable_autosave_and_resave_reject_mutated_evidence(
    tmp_path,
    monkeypatch,
):
    import project_io
    import sector_app

    def direction(component, demand, resistance):
        return {
            "component": component,
            "axis": "y" if component == "vx" else "x",
            "v_ed": demand,
            "signed_v_ed": demand,
            "bw": 1000.0,
            "d": 500.0,
            "method": multidirectional.SHEAR_CODE_EN_2023,
            "status": "PASS",
            "util": demand / resistance,
            "res": {
                "valid": True,
                "vrd_c": resistance,
            },
        }

    scalars = {
        **multidirectional.crack_configuration({}),
        **multidirectional.shear_configuration({}),
        "shear_interaction_on": True,
        "shear_interaction_method": (
            multidirectional.SHEAR_METHOD_PROJECT
        ),
        "shear_interaction_axis_x": "global x / Vx",
        "shear_interaction_axis_y": "global y / Vy",
        "shear_interaction_domain_confirmed": True,
        "shear_interaction_exponent": 2.0,
        "shear_interaction_source": "Project DB clause INT-06",
        "shear_interaction_approval": "Checker approval QA-06",
    }
    results = {
        "shear": {
            "directions": {
                "vx": direction("vx", 0.2, 1.0),
                "vy": direction("vy", 0.3, 1.0),
            },
            "biaxial": True,
            "status": "REVIEW",
        },
    }
    multidirectional.apply_to_results(scalars, results)
    bundle = multidirectional.interaction_calculation_record(results)
    bundle["shear_cases"][0]["interaction"]["utilisation"] = 0.0
    digest = project_io.input_sha256({}, scalars)
    calculation = {
        "input_sha256": digest,
        "multidirectional_interaction": bundle,
    }
    state = {"calculation_record": copy.deepcopy(calculation)}
    monkeypatch.setattr(
        sector_app,
        "st",
        SimpleNamespace(session_state=state),
    )
    monkeypatch.setattr(
        sector_app, "_invalid_factor_input_keys", lambda: ()
    )
    monkeypatch.setattr(
        sector_app, "_invalid_crack_input_keys", lambda: ()
    )
    monkeypatch.setattr(
        sector_app, "_invalid_interaction_input_keys", lambda: ()
    )
    monkeypatch.setattr(
        sector_app, "_project_state", lambda: ({}, scalars)
    )

    download = json.loads(sector_app._gather_project())
    download_record = download["calculation"][
        "multidirectional_interaction"
    ]
    assert download["calculation"]["matches_saved_inputs"] is False
    assert download_record["publication_validation"]["status"] == "REJECTED"
    assert download_record["shear_cases"][0]["interaction"]["status"] == (
        "NOT ASSESSED"
    )

    state["calculation_record"] = copy.deepcopy(calculation)
    monkeypatch.setattr(
        sector_app, "_current_table", lambda *_args, **_kwargs: object()
    )
    monkeypatch.setattr(
        sector_app,
        "_pts_from_df",
        lambda *_args, **_kwargs: [(0, 0), (1, 0), (0, 1)],
    )
    monkeypatch.setattr(
        sector_app, "_project_input_hash", lambda: digest
    )
    captured = {}

    def capture_autosave(data, path):
        captured["data"] = data
        captured["path"] = path
        return True

    monkeypatch.setattr(
        sector_app, "_write_autosave", capture_autosave
    )
    monkeypatch.setattr(
        sector_app,
        "_autosave_path",
        lambda: tmp_path / "autosave.json",
    )
    assert sector_app._perform_autosave() is True
    durable = state["calculation_record"][
        "multidirectional_interaction"
    ]
    autosaved = json.loads(captured["data"])["calculation"][
        "multidirectional_interaction"
    ]
    assert durable["publication_validation"]["status"] == "REJECTED"
    assert autosaved["publication_validation"]["status"] == "REJECTED"

    resaved = json.loads(sector_app._gather_project())["calculation"][
        "multidirectional_interaction"
    ]
    assert resaved["publication_validation"]["status"] == "REJECTED"
