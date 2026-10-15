"""Native widget-protocol qualification for the three Actions tabs.

AppTest 1.59.2 has no Tab setter. These checks send the same string_value and
string_value widget states as the browser. Browser click and keyboard selection
remain separate acceptance checks.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys

import pandas as pd
import pytest
from streamlit.proto.WidgetStates_pb2 import WidgetState
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import fatigue_inputs  # noqa: E402
import load_cases  # noqa: E402
import project_io  # noqa: E402
from app_workflow_navigation import goto_page  # noqa: E402

APP = str(ROOT / "app/sector_app.py")
FAMILIES = ("Plastic", "Elastic", "Fatigue")
TABLE = fatigue_inputs.SPECTRUM_TABLE_KEY
EDITORS = {"Plastic": "plastic_cases_editor", "Elastic": "elastic_cases_editor",
           "Fatigue": "fatigue_spectrum_editor"}


def _fresh(enabled=True):
    app = AppTest.from_file(APP, default_timeout=120)
    app.session_state["fatigue_on"] = enabled
    app.session_state["_next_workflow_page"] = "actions"
    app.session_state[TABLE] = fatigue_inputs.normalise_spectrum_table([
        {"spectrum": "Traffic", "name": "F1", "cycles": 123456.78901234567,
         "n_long_ed_kn": -100.10000000000001, "mx_short_ed_knm": 7.123456789012345},
        {"spectrum": "Traffic", "name": "F2", "cycles": 50.0,
         "n_long_ed_kn": -20.0, "mx_short_ed_knm": -3.0},
    ])
    app.run()
    assert not app.exception
    return app


def _tab_container(app):
    matches = [node for node in app._tree
               if getattr(node, "type", None) == "tab_container"
               and getattr(node.proto.tab_container, "id", "").endswith("-_actions_family")]
    assert len(matches) == 1
    assert tuple(child.label for child in matches[0].children.values()) == FAMILIES
    return matches[0]


def _widget_id(app, key):
    matches = [getattr(node.proto, "id", "") for node in app._tree
               if getattr(getattr(node, "proto", None), "id", "").endswith("-" + key)]
    assert len(matches) == 1, (key, matches)
    return matches[0]


def _send(app, *changes):
    states = app._tree.get_widget_states()
    replacements = {change.id: change for change in changes}
    for index in reversed(range(len(states.widgets))):
        if states.widgets[index].id in replacements:
            del states.widgets[index]
    states.widgets.extend(changes)
    app._run(widget_state=states)
    assert not app.exception
    return app


def _select(app, family, *, patch=None):
    tab_id = _tab_container(app).proto.tab_container.id
    changes = [WidgetState(id=tab_id, string_value=family)]
    if patch is not None:
        changes.append(WidgetState(id=_widget_id(app, "fatigue_spectrum_editor"),
                                   string_value=json.dumps(patch)))
    _send(app, *changes)
    assert app.session_state["_actions_family"] == family
    _assert_active_only(app, family, bool(app.session_state["fatigue_on"]))
    return app


def _editor_ids(app):
    return {key for key in EDITORS.values()
            if any(getattr(getattr(node, "proto", None), "id", "").endswith("-" + key)
                   for node in app._tree)}


def _assert_active_only(app, family, enabled):
    host = _tab_container(app)
    assert host.proto.tab_container.default_tab_index == FAMILIES.index(family)
    for child in host.children.values():
        if child.label != family:
            assert not child.children, (family, child.label)
    expected = {EDITORS[family]} if family != "Fatigue" or enabled else set()
    assert _editor_ids(app) == expected


def _tables(app):
    return {key: app.session_state[key].copy(deep=True)
            for key in (*load_cases.CASE_TABLE_KEYS, TABLE)}


def _same_tables(app, expected):
    for key, frame in expected.items():
        current = app.session_state[key]
        pd.testing.assert_frame_equal(current, frame, check_exact=True)
        assert current.attrs == frame.attrs


def _payload(app):
    # Exact concrete types and float.hex values, including the complete input
    # payload. Table attrs are checked separately by _same_tables.
    return project_io.result_sha256(app.session_state["_latest_inputs"])


@pytest.mark.parametrize("enabled", [False, True])
def test_tab_page_switches_preserve_all_tables_and_complete_input_payload(enabled):
    app = _fresh(enabled)
    before = _tables(app)
    payload = _payload(app)
    for family in ("Plastic", "Elastic", "Fatigue", "Elastic", "Plastic", "Fatigue"):
        _select(app, family)
        _same_tables(app, before)
        assert _payload(app) == payload
    for page in ("section", "materials", "project", "settings"):
        goto_page(app, page)
        assert not app.exception
        goto_page(app, "actions")
        assert not app.exception
        assert app.session_state["_actions_family"] == "Fatigue"
        _assert_active_only(app, "Fatigue", enabled)
        _same_tables(app, before)
        assert _payload(app) == payload
    if not enabled:
        assert any("Previously entered spectra remain saved" in item.value for item in app.info)
        assert not app.session_state["fatigue_on"]


PATCHES = (
    {"edited_rows": {"0": {"cycles": "0.10000000000000003"}}, "deleted_rows": [], "added_rows": []},
    {"edited_rows": {"0": {"mx_short_ed_knm": "invalid-cycle-action"}}, "deleted_rows": [], "added_rows": []},
    {"edited_rows": {}, "deleted_rows": [], "added_rows": [
        {"spectrum": "Traffic", "name": "F3", "cycles": "12.000000000000002",
         "n_long_ed_kn": "-17.123456789012344"}]},
    {"edited_rows": {}, "deleted_rows": [0], "added_rows": []},
)


def _expected_patch(seed, patch):
    # Independent finite-row oracle: app's recovery helper is deliberately not used.
    rows = fatigue_inputs.editor_spectrum_table(seed).to_dict("records")
    for position, cells in patch["edited_rows"].items():
        rows[int(position)].update(cells)
    rows = [row for index, row in enumerate(rows) if index not in patch["deleted_rows"]]
    for cells in patch["added_rows"]:
        rows.append({column: cells.get(column) for column in fatigue_inputs.SPECTRUM_COLUMNS})
    return fatigue_inputs.normalise_spectrum_table(rows)


@pytest.mark.parametrize("patch", PATCHES, ids=["precise", "invalid", "added", "deleted"])
def test_pending_fatigue_editor_event_survives_simultaneous_tab_switch(patch):
    app = _fresh()
    _select(app, "Fatigue")
    before = _tables(app)
    expected = _expected_patch(app.session_state[f"_{TABLE}_editor_seed"], patch)
    _select(app, "Elastic", patch=patch)
    _select(app, "Plastic")
    goto_page(app, "materials")
    goto_page(app, "actions")
    _select(app, "Fatigue")
    pd.testing.assert_frame_equal(app.session_state[TABLE], expected, check_exact=True)
    assert app.session_state[TABLE].attrs == expected.attrs
    for key in load_cases.CASE_TABLE_KEYS:
        pd.testing.assert_frame_equal(app.session_state[key], before[key], check_exact=True)
    pd.testing.assert_frame_equal(app.session_state["_latest_inputs"][TABLE], expected, check_exact=True)
    # Repeating the transition must not replay additions or deletions twice.
    stable_payload = _payload(app)
    _select(app, "Elastic")
    _select(app, "Fatigue")
    pd.testing.assert_frame_equal(app.session_state[TABLE], expected, check_exact=True)
    assert _payload(app) == stable_payload


def test_settings_link_commits_pending_fatigue_edit_and_preserves_selected_tab():
    app = _fresh()
    _select(app, "Fatigue")
    patch = PATCHES[1]
    expected = _expected_patch(app.session_state[f"_{TABLE}_editor_seed"], patch)
    editor_id = _widget_id(app, "fatigue_spectrum_editor")
    app.button(key="_actions_fatigue_settings").click()
    _send(app, WidgetState(id=editor_id, string_value=json.dumps(patch)))
    assert app.session_state["_workflow_page"] == "settings"
    assert app.session_state["_analysis_group"] == "Fatigue"
    assert app.session_state["fatigue_on"] is True
    goto_page(app, "actions")
    assert app.session_state["_actions_family"] == "Fatigue"
    _assert_active_only(app, "Fatigue", True)
    pd.testing.assert_frame_equal(app.session_state[TABLE], expected, check_exact=True)
    assert fatigue_inputs.editor_spectrum_table(app.session_state[TABLE]).loc[0, "mx_short_ed_knm"] == "invalid-cycle-action"


def test_disable_enable_via_settings_retains_exact_saved_spectrum():
    app = _fresh()
    _select(app, "Fatigue")
    before = _tables(app)
    app.button(key="_actions_fatigue_settings").click().run()
    assert not app.exception
    assert app.session_state["_analysis_group"] == "Fatigue"
    app.toggle(key="fatigue_on").set_value(False).run()
    assert not app.exception
    goto_page(app, "actions")
    _assert_active_only(app, "Fatigue", False)
    _same_tables(app, before)
    app.button(key="_actions_fatigue_settings").click().run()
    app.toggle(key="fatigue_on").set_value(True).run()
    assert not app.exception
    goto_page(app, "actions")
    _assert_active_only(app, "Fatigue", True)
    _same_tables(app, before)


def test_existing_project_upload_roundtrip_preserves_all_actions_and_payload(record_property):
    app = _fresh()
    _select(app, "Fatigue")
    before = _tables(app)
    presave = copy.deepcopy(app.session_state["_latest_inputs"])
    record_property("presave_payload_sha256", _payload(app))
    tables = {key: copy.deepcopy(app.session_state[key]) for key in project_io.PROJECT_TABLE_KEYS
              if key in app.session_state}
    scalars = {key: copy.deepcopy(app.session_state[key]) for key in project_io.SCALAR_KEYS
               if key in app.session_state}
    text = project_io.dump_project(tables, scalars)
    loaded = []
    # Compare two actual upload lifecycles: the existing session and a new one.
    # Both complete payloads must be exactly equal after loading the same bytes.
    for target in (app, AppTest.from_file(APP, default_timeout=120)):
        if target is app:
            goto_page(target, "project")
        else:
            target.session_state["_next_workflow_page"] = "project"
            target.run()
        assert not target.exception and len(target.file_uploader) == 1
        target.file_uploader[0].set_value(("actions-roundtrip.json", text.encode("utf-8"), "application/json")).run()
        assert not target.exception
        goto_page(target, "actions")
        loaded.append(_payload(target))
        for family in FAMILIES:
            _select(target, family)
            _same_tables(target, before)
            assert _payload(target) == loaded[-1]
    assert loaded[0] == loaded[1]
    record_property("loaded_payload_sha256", loaded[0])
    after = app.session_state["_latest_inputs"]
    assert set(presave) == set(after)
    changed = {key for key in presave if project_io.result_sha256(presave[key]) != project_io.result_sha256(after[key])}
    record_property("presave_to_loaded_changed_fields", json.dumps(sorted(changed)))
    # Released-baseline evidence: ui-loaded-parity-independent-review.json.
    # These inactive reference signatures are rebuilt on project load. Every
    # other input field must retain its exact value, and both loaded payloads
    # must match in full, including the rebuilt signatures.
    assert changed <= {"elastic_case_context_sig", "elastic_sig", "signature"}
