"""Keep display selection through view changes without changing results."""
import ast
import json
import textwrap
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app" / "sector_app.py"
LABELS = ["Neutral-axis state", "Reinforcement element", "Concrete fibre", "Spectrum",
          "Detail", "Directional result", "Directional combined result", "Result details"]


@pytest.mark.parametrize("label", LABELS)
def test_native_result_control_survives_unmount_and_remount(label):
    if label == "Result details":
        _assert_overview_selection_survives_unmount_and_remount()
        return
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


def _assert_overview_selection_survives_unmount_and_remount():
    """Use the current native dataframe and durable exact-record identity."""
    source = APP.read_text(encoding="utf-8")
    start = source.index("        chosen = result_workspace.reconcile_selection(")
    stop_text = '            st.session_state["_overview_selection"] = result_workspace.identity(selected_row)'
    stop = source.index(stop_text, start) + len(stop_text)
    selection_source = textwrap.dedent(source[start:stop])
    assert 'on_select="rerun", selection_mode="single-row"' in selection_source
    assert 'selection_default={"selection": {"rows": [chosen]}}' in selection_source
    assert stop_text.strip() in selection_source
    setup = f"""import sys
sys.path.insert(0, {str(APP.parent)!r})
import pandas as pd
import streamlit as st
import result_workspace
visible_rows = [dict(overview_key=f'check:{{i}}', family='Plastic', case=f'CASE-{{i}}',
                     view='Plastic Results', check=f'Check {{i}}', status='PASS') for i in (0, 1)]
status_colours = {{}}
choice = 'All checks'
table = st
show = st.checkbox('Show result view', value=True, key='show')
if show:
"""
    script = setup + textwrap.indent(selection_source, "    ") + "\n"
    at = AppTest.from_string(script, default_timeout=20).run()
    assert not at.exception
    assert len(at.dataframe) == 1
    assert at.session_state["_overview_selection"][2] == "CASE-0"

    # AppTest's Dataframe is read-only in the pinned Streamlit version. Send
    # the same serialized row-selection widget state as its browser client.
    from streamlit.elements.arrow import DataframeSelectionSerde
    from streamlit.testing.v1.element_tree import Dataframe
    assert not hasattr(Dataframe, "set_value")
    payload = {"selection": {"rows": [1], "columns": [], "cells": []}}
    serde = DataframeSelectionSerde()
    wire = serde.serialize(payload)
    assert serde.deserialize(wire).selection.rows == [1]
    widget_id = at.dataframe[0].proto.id
    assert widget_id
    states = at._tree.get_widget_states()
    assert all(item.id != widget_id for item in states.widgets)
    states.widgets.add(id=widget_id, string_value=wire)
    at._run(states)
    assert not at.exception
    assert at.session_state["_overview_selection"] == (
        "check:1", "Plastic", "CASE-1", "Plastic Results", "Check 1",
    )
    at.checkbox(key="show").uncheck().run()
    assert not at.exception
    assert not at.dataframe
    assert at.session_state["_overview_selection"][2] == "CASE-1"
    at.checkbox(key="show").check().run()
    assert not at.exception
    assert len(at.dataframe) == 1
    assert at.session_state["_overview_selection"][2] == "CASE-1"
    assert json.loads(at.dataframe[0].proto.selection_default)["selection"]["rows"] == [1]
    independent = AppTest.from_string(script, default_timeout=20).run()
    assert not independent.exception
    assert independent.session_state["_overview_selection"][2] == "CASE-0"
