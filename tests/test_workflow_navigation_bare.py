"""The applied navigation adapter also supports imports outside a script run."""

import ast
from pathlib import Path
from types import CodeType, FunctionType, SimpleNamespace

import streamlit as st

from app import workflow_navigation


def test_applied_navigation_uses_page_identity_in_bare_python():
    """Exercise the actual adapter with real, context-free public Page objects."""
    source = (Path(__file__).resolve().parents[1] / "app" / "sector_app.py").read_text()
    function = next(
        node for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == "_workflow_navigation"
    )
    state = {
        "_durable_input_scalars": {}, "_pending_input_events": {},
        "engineering_input": {"N": -123.456},
        "engineering_result": {"stress": 7.25},
    }
    labels = {page.stage: page.stage for page in workflow_navigation.PAGES if page.stage}
    namespace = {
        "st": SimpleNamespace(Page=st.Page, navigation=st.navigation, session_state=state),
        "workflow_navigation": workflow_navigation,
        "app_run_probe": SimpleNamespace(WORKSPACE_NAMES=("Inputs", "Analysis", "Report")),
        "_input_stage_labels": lambda: labels,
        "_INPUT_STATE_KEY": "_durable_input_scalars",
        "_PENDING_INPUT_EVENTS_KEY": "_pending_input_events",
    }
    compiled = compile(ast.Module(body=[function], type_ignores=[]), str(__file__), "exec")
    code = next(value for value in compiled.co_consts if isinstance(value, CodeType))
    selected = FunctionType(code, namespace)()
    assert selected is workflow_navigation.BY_KEY["section"]
    assert state["_workflow_page"] == "section"
    assert state["_main_page"] == "Inputs"
    assert state["_input_tab"] == labels["Section"]
    assert state["_durable_input_scalars"]["_input_tab"] == labels["Section"]
    assert state["_pending_input_events"]["_input_tab"] == labels["Section"]
    assert state["engineering_input"] == {"N": -123.456}
    assert state["engineering_result"] == {"stress": 7.25}
