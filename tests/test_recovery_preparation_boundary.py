"""Invalid recovery transactions stop before any project replacement."""
import ast
import copy
from pathlib import Path
from types import CodeType, FunctionType, SimpleNamespace

import pandas as pd
import pytest

import load_cases
import project_widget_state as recovery


class State(dict):
    def to_dict(self):
        return dict(self)


def functions(state, apply):
    path = Path(__file__).resolve().parents[1] / "app/sector_app.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    scope = {"copy": copy, "st": SimpleNamespace(session_state=state),
             "_PENDING_PROJECT_CONTENT_ID_KEY": "_pending_project_content_identity",
             "_PENDING_PROJECT_WIDGET_KEY": "_pending_project_widget_key",
             "_PROJECT_UPLOAD_CONTENT_ID_KEY": "_project_upload_content_identity",
             "_apply_project_text": apply,
             "_project_not_applied_message": lambda exc: str(exc),
             "_advance_project_upload_widget": lambda key: None}
    for name in ("_project_transaction_snapshot", "_restore_project_transaction", "_apply_pending_project"):
        node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
        compiled = compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec")
        code = next(value for value in compiled.co_consts if isinstance(value, CodeType))
        scope[name] = FunctionType(code, scope)
    return scope


@pytest.mark.parametrize("seed", [None, "malformed", pd.DataFrame({"wrong": [1]})])
@pytest.mark.parametrize("patch", [
    {"edited_rows": {"0": {"name": "pending"}}},
    {"added_rows": [{"name": "pending"}]},
    {"deleted_rows": [0]},
])
def test_missing_or_malformed_seed_aborts_before_replacement(seed, patch):
    table = "plastic_cases_base"
    durable = {"results": {"n": 123.0}, "report_buffer": b"old-report", "conc_fck": 41.0,
               table: load_cases.default_tables()[table], "plastic_cases_editor": patch,
               "_next_main_page": "Inputs", "_actions_selected::plastic_cases_base": 0}
    if seed is not None:
        durable[f"_{table}_editor_seed"] = seed
    state = State({**durable, "_pending_project": "replacement"})
    called = []
    functions(state, lambda text: called.append(text))["_apply_pending_project"]()
    assert not called
    assert "_pending_project" not in state
    assert state["_project_msg"][0] == "error"
    assert all(state[key] is value for key, value in durable.items())


@pytest.mark.parametrize("patch", [None, [], {"edited_rows": {"bad": {"name": "x"}}},
                                     {"unknown": [1]}, {"deleted_rows": [-1]}, {"edited_rows": []}])
def test_malformed_patch_aborts_before_replacement(patch):
    table = "plastic_cases_base"
    seed = load_cases.default_tables()[table]
    state = State({"_pending_project": "replacement", table: seed,
                   f"_{table}_editor_seed": seed, "plastic_cases_editor": patch,
                   "results": {"n": 9.1}, "report_buffer": b"prior"})
    durable = dict(state)
    called = []
    functions(state, lambda text: called.append(text))["_apply_pending_project"]()
    assert not called
    assert state["_project_msg"][0] == "error"
    for key, value in durable.items():
        if key != "_pending_project":
            assert state[key] is value


def test_valid_prepared_snapshot_rolls_back_even_after_partial_replacement():
    table = "plastic_cases_base"
    seed = load_cases.normalise_table([{"name": "A", "n_ed_kn": 0.12345678901234567}], table)
    state = State({"_pending_project": "replacement", table: seed,
                   f"_{table}_editor_seed": seed,
                   "plastic_cases_editor": {"edited_rows": {"0": {"n_ed_kn": "invalid"}}},
                   "results": {"n": 9.1}, "report_buffer": b"prior", "open_qs": False})
    expected = recovery.recovery_values(copy.deepcopy(dict(state)))
    def partial(text):
        state.clear()
        state.update({"results": "partly replaced", table: "partial", "new": 1})
        raise ValueError("injected application failure")
    functions(state, partial)["_apply_pending_project"]()
    assert "new" not in state and "open_qs" not in state and "plastic_cases_editor" not in state
    assert state["results"] == expected["results"]
    assert state["report_buffer"] == expected["report_buffer"]
    pd.testing.assert_frame_equal(state[table], expected[table])
    assert load_cases.editor_table(state[table], table).loc[0, "n_ed_kn"] == "invalid"
    assert state["_project_msg"] == ("error", "injected application failure")
