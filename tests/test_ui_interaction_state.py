"""Keep display selection through view changes without changing results."""
import ast
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app" / "sector_app.py"
LABELS = ["Neutral-axis state", "Reinforcement element", "Concrete fibre", "Spectrum",
          "Detail", "Directional result", "Directional combined result", "Result details"]


@pytest.mark.parametrize("label", LABELS)
def test_native_result_control_survives_unmount_and_remount(label):
    tree = ast.parse(APP.read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute)
             and node.func.attr in {"selectbox", "segmented_control"}
             and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == label]
    assert len(calls) == 1
    call = calls[0]
    assert any(k.arg == "persist_state" and k.value.value == "session" for k in call.keywords)
    script = '''import streamlit as st
options = [0, 1]
detail_options = options
rows = [{'fibre_index': i, 'source': 'literal_$x', 'x_mm': i, 'y_mm': i, 'check': 'Check', 'case': 'Case'} for i in options]
pts = [{'V': 0}, {'V': 90}]
default_i = 0
key = 'selection'
detail_key = 'selection'
_DEG = chr(176)
show = st.checkbox('Show result view', value=True, key='show')
if show:
    selected = ''' + ast.unparse(call) + "\n    st.write(selected)\n"
    at = AppTest.from_string(script, default_timeout=20).run()
    assert not at.exception
    widgets = list(at.selectbox) + list(at.get("button_group"))
    assert len(widgets) == 1
    widgets[0].set_value(1).run()
    assert not at.exception
    at.checkbox(key="show").uncheck().run()
    assert not at.selectbox and not at.get("button_group")
    at.checkbox(key="show").check().run()
    assert not at.exception
    widgets = list(at.selectbox) + list(at.get("button_group"))
    assert widgets[0].value == 1


@pytest.mark.parametrize("axis,negative,positive", [("x", "Left (-x)", "Right (+x)"), ("y", "Bottom (-y)", "Top (+y)")])
def test_face_names_preserve_closed_choices_and_literal_unknowns(axis, negative, positive):
    tree = ast.parse(APP.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_ui_action_face")
    namespace = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(APP), "exec"), namespace)
    function = namespace[node.name]
    assert function("auto", axis) == "Automatic selection"
    for value in ("negative", "low"):
        assert function(value, axis) == negative
    for value in ("positive", "high"):
        assert function(value, axis) == positive
    for literal in (None, 0, "user_$x<text>", "NEGATIVE"):
        assert function(literal, axis) == literal
    assert function("negative", "unknown") == "negative"
