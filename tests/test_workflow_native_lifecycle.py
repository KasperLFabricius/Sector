"""Native checks for the new workflow around the retained calculation owner."""

import copy
from pathlib import Path

from streamlit.testing.v1 import AppTest

from app import workflow_navigation


APP = str(Path(__file__).parents[1] / "app" / "sector_app.py")


def _route(app, page):
    app.session_state["_next_workflow_page"] = page
    app.run()
    assert not app.exception
    assert app.session_state["_workflow_page"] == page


def test_calculate_from_inputs_runs_once_and_navigation_retains_snapshot(monkeypatch, tmp_path):
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path / "recovery"))
    accepted = []
    original = workflow_navigation.take_calculate_request

    def observe(state, inputs, **kwargs):
        answer = original(state, inputs, **kwargs)
        if answer:
            accepted.append(copy.deepcopy(inputs["signature"]))
        return answer

    monkeypatch.setattr(workflow_navigation, "take_calculate_request", observe)
    app = AppTest.from_file(APP, default_timeout=120).run()
    assert not app.exception
    assert app.session_state["_workflow_page"] == "section"
    _route(app, "actions")
    signature = copy.deepcopy(app.session_state["_latest_inputs"]["signature"])
    app.button(key="calculate").click().run()
    assert not app.exception
    assert app.session_state["_workflow_page"] == "results"
    assert len(accepted) == 1
    assert accepted[0] == signature
    assert app.session_state["results"]["plastic"]
    assert app.session_state["result_sig"] == signature
    assert "_workflow_calculate_request" not in app.session_state.filtered_state
    for page in ("materials", "actions", "settings", "report", "help", "project", "results"):
        _route(app, page)
        assert app.session_state["_latest_inputs"]["signature"] == signature
        assert app.session_state["result_sig"] == signature
        assert len(accepted) == 1


def test_project_replacement_cancels_queued_calculation_and_case_focus(monkeypatch, tmp_path):
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path / "recovery"))
    app = AppTest.from_file(APP, default_timeout=120).run()
    assert not app.exception
    import project_io

    replacement = project_io.dump_project({}, {"rep_proj_no": "Replacement project"})
    before_epoch = app.session_state.filtered_state.get("_project_context_epoch", 0)
    app.session_state["_workflow_calculate_request"] = {
        "signature": app.session_state["_latest_inputs"]["signature"],
        "generation": app.session_state.filtered_state.get("_project_upload_generation", 0),
    }
    app.session_state["_actions_selected::plastic_cases_base"] = "old-project-case"
    app.session_state["_overview_selection"] = ("old-project",)
    app.session_state["_pending_project"] = replacement
    app.run()
    assert not app.exception
    state = app.session_state.filtered_state
    assert "_workflow_calculate_request" not in state
    assert "_actions_selected::plastic_cases_base" not in state
    assert "_overview_selection" not in state
    assert state["_project_context_epoch"] == before_epoch + 1
    assert not state.get("results")
