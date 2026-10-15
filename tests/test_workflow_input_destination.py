"""Registered input destinations and warning ownership stay explicit."""
import ast
from pathlib import Path

import pytest

from app import workflow_navigation as nav


@pytest.mark.parametrize("stage,expected", [
    (None, "section"), ("", "section"), ("unknown", "section"),
    ("Section", "section"), ("Material parameters", "materials"),
    ("Loads", "actions"), ("Analysis settings", "settings"), ("Project", "project"),
])
def test_input_route_fallback_cannot_resolve_non_input_pages(stage, expected):
    assert nav.input_page(stage) == expected
    assert nav.legacy_destination("Inputs", stage) == expected
    assert nav.BY_KEY[expected].workspace == "Inputs"


def test_pending_edit_notice_uses_existing_manual_warning_reference():
    source = (Path(__file__).resolve().parents[1] / "app" / "sector_app.py").read_text()
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and any(isinstance(child, ast.Constant) and child.value == "_workflow_notice"
                     for child in ast.walk(node))
             and isinstance(node.func, ast.Name) and node.func.id == "_manual_warning"]
    assert len(calls) == 1
    assert calls[0].args[1].value == "input-invalid"
    assert ast.unparse(calls[0].args[2]) == "st.session_state.pop('_workflow_notice')"