"""Project rollback retains data and lets Streamlit own button events."""

import ast
from pathlib import Path
from types import CodeType, FunctionType, SimpleNamespace

import pytest


def _restore_function():
    source = Path(__file__).resolve().parents[1] / "app" / "sector_app.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "_restore_project_transaction")
    compiled = compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec")
    return next(value for value in compiled.co_consts if isinstance(value, CodeType))


class State(dict):
    def to_dict(self):
        return dict(self)


@pytest.mark.parametrize("calculate_pulse", [False, True])
@pytest.mark.parametrize("context_help_pulse", [False, True])
@pytest.mark.parametrize("about_help_pulse", [False, True])
def test_rollback_restores_all_data_without_assigning_button_events(
    calculate_pulse, context_help_pulse, about_help_pulse,
):
    snapshot = {
        "calculate": calculate_pulse,
        "_context_full_manual": context_help_pulse,
        "open_manual": about_help_pulse,
        "_help_topic": "project", "_manual_open": False,
        "_next_workflow_page": "help", "_workflow_page": "project",
        "conc_fck": 41.0, "fatigue_on": False,
        "results": {"plastic": {"max_mx": 123.0}}, "report_buffer": b"%PDF-prior",
        "_actions_selected::plastic_cases_base": 2,
        "_project_upload_content_identity": "prior-project",
        "_workflow_calculate_request": {"signature": ("prior",), "generation": 4},
    }
    state = State({"calculate": True, "conc_fck": 42.0, "failed_new_key": "partial"})
    namespace = {"st": SimpleNamespace(session_state=state)}
    FunctionType(_restore_function(), namespace)(snapshot)
    button_keys = {"calculate", "_context_full_manual", "open_manual"}
    assert button_keys.isdisjoint(state)
    assert state == {key: value for key, value in snapshot.items() if key not in button_keys}
    assert "failed_new_key" not in state
    assert snapshot["calculate"] is calculate_pulse
    assert snapshot["_context_full_manual"] is context_help_pulse
    assert snapshot["open_manual"] is about_help_pulse
    assert state["results"] is snapshot["results"]
    assert state["_workflow_calculate_request"] is snapshot["_workflow_calculate_request"]
