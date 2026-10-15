"""Native exact-case issue navigation and single-cell correction lifecycle."""

from pathlib import Path
import sys

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import action_workspace
import case_analysis
import load_cases


APP = str(ROOT / "app" / "sector_app.py")


def _route(app, page):
    app.session_state["_next_workflow_page"] = page
    app.run()
    assert not app.exception
    assert app.session_state["_workflow_page"] == page


def _frames(app):
    return {key: load_cases.editor_table(app.session_state[key], key).copy(deep=True)
            for key in load_cases.CASE_TABLE_KEYS}


@pytest.mark.parametrize("table,field,code,family", [
    (load_cases.PLASTIC_TABLE_KEY, "n_ed_kn", "PLASTIC-N-ED", "Plastic"),
    (load_cases.ELASTIC_TABLE_KEY, "n_long_ed_kn", "ELASTIC-N-LONG", "Elastic"),
])
def test_exact_issue_go_to_retains_raw_cell_and_corrects_only_selected_field(
    table, field, code, family, monkeypatch,
):
    calls = []

    def unexpected_calculation(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("Invalid input must block the calculation owner")

    monkeypatch.setattr(case_analysis, "run_case_tables", unexpected_calculation)
    app = AppTest.from_file(APP, default_timeout=120)
    app.session_state[table] = load_cases.normalise_table([
        {"name": "Witness case", field: 7.0, "description": "Retain witness"},
        {},
        {"name": "Target case", field: "bad-cell", "description": "Retain target"},
    ], table)
    app.session_state["plastic_on"] = True
    app.session_state["elastic_on"] = True
    app.session_state[action_workspace.FAMILY_KEY] = "Elastic" if family == "Plastic" else "Plastic"
    app.session_state[action_workspace.selection_key(table)] = 0
    app.run()
    assert not app.exception
    before = _frames(app)
    assert before[table].iloc[2][field] == "bad-cell"
    errors = load_cases.validation_errors(
        app.session_state[load_cases.PLASTIC_TABLE_KEY],
        app.session_state[load_cases.ELASTIC_TABLE_KEY],
    )
    assert [message.code for message in errors] == [code]
    app.button(key="calculate").click().run()
    assert not app.exception
    assert app.session_state["_workflow_page"] == "results"
    assert calls == []
    destinations = [button for button in app.button if button.label == "Go to"]
    assert len(destinations) == 1
    destinations[0].click().run()
    assert not app.exception
    assert app.session_state["_workflow_page"] == "actions"
    location = app.session_state[action_workspace.FOCUS_KEY]
    assert location.table_key == table
    assert location.field_key == field
    assert location.row_position == 2
    assert location.case_name == "Target case"
    assert [tab.label for tab in app.tabs] == ["Plastic", "Elastic", "Fatigue"]
    assert app.session_state[action_workspace.FAMILY_KEY] == family
    editor_keys = {frame.key for frame in app.dataframe}
    selected_editor = "plastic_cases_editor" if family == "Plastic" else "elastic_cases_editor"
    other_editor = "elastic_cases_editor" if family == "Plastic" else "plastic_cases_editor"
    assert selected_editor in editor_keys
    assert other_editor not in editor_keys
    assert "fatigue_spectrum_editor" not in editor_keys
    assert app.selectbox(key=action_workspace.selection_key(table)).value == 2
    key = f"_actions_cell_edit::{table}::2::{field}::{location.row_digest}"
    assert app.text_input(key=key).value == "bad-cell"
    assert app.text_input(key=key).proto.help
    assert any("Row 3: Target case" in str(item.value) for item in app.text)
    _route(app, "materials")
    _route(app, "actions")
    assert [tab.label for tab in app.tabs] == ["Plastic", "Elastic", "Fatigue"]
    assert app.session_state[action_workspace.FAMILY_KEY] == family
    editor_keys = {frame.key for frame in app.dataframe}
    selected_editor = "plastic_cases_editor" if family == "Plastic" else "elastic_cases_editor"
    other_editor = "elastic_cases_editor" if family == "Plastic" else "plastic_cases_editor"
    assert selected_editor in editor_keys
    assert other_editor not in editor_keys
    assert "fatigue_spectrum_editor" not in editor_keys
    assert app.selectbox(key=action_workspace.selection_key(table)).value == 2
    assert app.text_input(key=key).value == "bad-cell"
    app.text_input(key=key).set_value("12,5").run()
    assert not app.exception
    for identity, frame in _frames(app).items():
        pd.testing.assert_frame_equal(frame, before[identity])
    app.button(key=key + "::apply").click().run()
    assert not app.exception
    expected = before[table].copy(deep=True)
    expected.at[2, field] = "12,5"
    expected = load_cases.editor_table(load_cases.normalise_table(expected, table), table)
    after = _frames(app)
    pd.testing.assert_frame_equal(after[table], expected)
    for identity in load_cases.CASE_TABLE_KEYS:
        if identity != table:
            pd.testing.assert_frame_equal(after[identity], before[identity])
    assert float(load_cases.normalise_table(app.session_state[table], table).iloc[2][field]) == 12.5
    assert action_workspace.FOCUS_KEY not in app.session_state.filtered_state
    _route(app, "settings")
    _route(app, "actions")
    assert [tab.label for tab in app.tabs] == ["Plastic", "Elastic", "Fatigue"]
    assert app.session_state[action_workspace.FAMILY_KEY] == family
    editor_keys = {frame.key for frame in app.dataframe}
    selected_editor = "plastic_cases_editor" if family == "Plastic" else "elastic_cases_editor"
    other_editor = "elastic_cases_editor" if family == "Plastic" else "plastic_cases_editor"
    assert selected_editor in editor_keys
    assert other_editor not in editor_keys
    assert "fatigue_spectrum_editor" not in editor_keys
    assert app.selectbox(key=action_workspace.selection_key(table)).value == 2
    pd.testing.assert_frame_equal(_frames(app)[table], expected)
    assert calls == []
