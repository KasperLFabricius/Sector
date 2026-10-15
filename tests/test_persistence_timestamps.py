"""Each project timestamp keeps its existing producer and display contract."""
import ast
import copy
from datetime import datetime
from pathlib import Path
import time
from types import CodeType, FunctionType, SimpleNamespace

import pytest

from test_workflow_recovery_caption import _run_header


APP = Path(__file__).resolve().parents[1] / "app" / "sector_app.py"


def _function(source, name, namespace):
    node = next(item for item in ast.parse(source).body
                if isinstance(item, ast.FunctionDef) and item.name == name)
    node.decorator_list = []
    compiled = compile(ast.Module(body=[node], type_ignores=[]), str(APP), "exec")
    code = next(value for value in compiled.co_consts if isinstance(value, CodeType))
    return FunctionType(code, namespace)


def _actual_recovery_value(source):
    tree = ast.parse(source)
    writes = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Subscript)
                      and isinstance(target.slice, ast.Constant)
                      and target.slice.value == "_autosave_last" for target in node.targets)]
    assert len(writes) == 1
    node = ast.FunctionDef(name="read_producer", args=ast.arguments(
        posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]),
        body=[ast.Return(value=writes[0].value)], decorator_list=[])
    code = compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(APP), "exec")
    frozen_now = datetime(2026, 10, 13, 4, 5, 6)
    produced = FunctionType(next(value for value in code.co_consts if isinstance(value, CodeType)),
                            {"__builtins__": __builtins__,
                             "datetime": SimpleNamespace(now=lambda: frozen_now)})()
    assert produced == "04:05:06"
    return produced


@pytest.mark.parametrize("recovery", [None, "", "00:00:01", "04:05:06"])
@pytest.mark.parametrize("exported", [None, 0, 1700000000, 1700000000.25])
def test_actual_timestamp_consumers_keep_values_and_numeric_export_format(recovery, exported):
    source = APP.read_text(encoding="utf-8")
    state = {"_autosave_last": recovery, "_project_export_offered_at": exported,
             "_latest_inputs": {"signature": "exact"}, "results": {"stress": 12.345}}
    before = copy.deepcopy(state)
    captions = []
    st = SimpleNamespace(session_state=state, markdown=lambda *_: None, caption=captions.append)
    namespace = {"st": st, "time": time}
    _function(source, "_persistence_context", namespace)()
    expected_export = time.strftime("%H:%M:%S", time.localtime(exported)) if exported else "Not yet"
    assert captions == ["Recovery updated: " + (str(recovery) if recovery else "Not yet"),
                        "Project export offered: " + expected_export]
    panel = SimpleNamespace(caption=captions.append)
    namespace.update(_seeded_checkbox=lambda *a, **kw: True,
                     _seeded_number=lambda *a, **kw: None,
                     _AUTOSAVE_DEFAULT_MIN=2, _reset_autosave_clock=lambda: None)
    _function(source, "_autosave_panel", namespace)(panel)
    assert captions[-1] == (f"Autosaved at {recovery}." if recovery
                            else "Local recovery is restored on the next launch.")
    header = _run_header(source, recovery)
    assert [line for line in header if line.startswith("Recovery updated:")] == (
        ["Recovery updated: " + recovery] if recovery else [])
    assert state == before


def test_actual_producers_retain_string_recovery_and_numeric_export_types():
    source = APP.read_text(encoding="utf-8")
    recovery = _actual_recovery_value(source)
    assert type(recovery) is str
    state = {"_autosave_last": recovery, "results": {"stress": 12.345}}
    _function(source, "_record_project_export", {
        "st": SimpleNamespace(session_state=state), "time": SimpleNamespace(time=lambda: 1700000000.25),
    })()
    assert state == {"_autosave_last": "04:05:06", "results": {"stress": 12.345},
                     "_project_export_offered_at": 1700000000.25}
    assert type(state["_project_export_offered_at"]) is float
