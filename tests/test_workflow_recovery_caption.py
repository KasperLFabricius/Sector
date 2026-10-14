"""The workflow header retains the successful recovery timestamp contract."""
import ast
import copy
from pathlib import Path
import time
from types import CodeType, FunctionType, SimpleNamespace

import pytest

from app import workflow_navigation


def _run_header(source, timestamp):
    function = next(node for node in ast.parse(source).body
                    if isinstance(node, ast.FunctionDef) and node.name == "_workflow_context")
    function.decorator_list = []
    class Pane:
        def __init__(self):
            self.captions = []
            self.buttons = []
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def markdown(self, *args, **kwargs):
            pass
        def caption(self, value):
            self.captions.append(value)
        def button(self, *args, **kwargs):
            self.buttons.append(kwargs)
            return False
    panes = [Pane(), Pane(), Pane()]
    state = {"_autosave_last": timestamp, "_latest_inputs": {"mode": "Both", "signature": "exact"},
             "_capacity_contract": "current", "numerical_result": {"stress": 12.345}}
    before = copy.deepcopy(state)
    namespace = {
        "st": SimpleNamespace(session_state=state, container=lambda **kw: Pane(), columns=lambda widths: panes),
        "workflow_navigation": workflow_navigation,
        "_has_uncommitted_inputs": lambda: False,
        "_RESULT_CAPACITY_CONTRACT_KEY": "_capacity_contract",
        "_CAPACITY_RESULT_CONTRACT_TOKEN": "current",
        "time": time,
    }
    compiled = compile(ast.Module(body=[function], type_ignores=[]), str(__file__), "exec")
    code = next(value for value in compiled.co_consts if isinstance(value, CodeType))
    FunctionType(code, namespace)()
    assert state == before
    assert panes[2].buttons[0]["key"] == "calculate"
    return panes[0].captions


@pytest.mark.parametrize("timestamp", [None, "", "00:00:01", "15:42:09", "23:59:59"])
def test_successful_autosave_string_keeps_header_and_calculate_available(timestamp):
    source = (Path(__file__).resolve().parents[1] / "app" / "sector_app.py").read_text()
    captions = _run_header(source, timestamp)
    recovery = [value for value in captions if value.startswith("Recovery updated:")]
    assert recovery == (["Recovery updated: " + timestamp] if timestamp else [])