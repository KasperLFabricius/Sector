"""Related-input routes retain the authored result and owning action case."""
import ast
import builtins
import copy
import importlib.util
import os
from pathlib import Path
import sys
import types

import pandas as pd
import pytest

ROOT = Path(os.environ.get("SECTOR_ROUTE_TEST_ROOT", Path(__file__).resolve().parents[1]))
CANDIDATE = Path(__file__).resolve().parents[1] / "app" / "result_workspace.py"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))
import action_workspace
import load_cases
import mvt_workspace

SPEC = importlib.util.spec_from_file_location("route_workspace", CANDIDATE)
workspace = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workspace)


@pytest.mark.parametrize("status", ["CALCULATED", "INVALID", "NOT CALCULATED", "STALE"])
def test_cracking_threshold_routes_to_owning_elastic_actions(status):
    row = {"overview_key": "cracking_threshold", "view": "Elastic Results", "family": "elastic",
           "case": "EL Target", "status": status, "overview_value": 1.2345678901234567,
           "result": "retained output", "criterion": "Output only"}
    before = copy.deepcopy(row)
    assert workspace.input_destination(row) == ("actions", None, None)
    assert row == before


@pytest.mark.parametrize("key,view,destination", [
    ("plastic_bending", "Plastic Results", ("actions", None, None)),
    ("elastic_stresses:scope", "Elastic Results", ("actions", None, None)),
    ("elastic_stress:concrete", "Elastic Results", ("actions", None, None)),
    ("elastic_stress:reinforcement", "Elastic Results", ("actions", None, None)),
    ("elastic_stress:prestress", "Elastic Results", ("actions", None, None)),
    ("crack_width", "Elastic Results", ("settings", "Crack width", None)),
    ("crack_width:scope", "Elastic Results", ("settings", "Crack width", None)),
    ("crack_width:long_term", "Elastic Results", ("settings", "Crack width", None)),
    ("crack_width:short_term", "Elastic Results", ("settings", "Crack width", None)),
    ("heightened_crack_control", "Elastic Results", ("settings", "Crack width", None)),
    ("shear:with_links", "Shear", ("settings", "Shear / torsion / M-V-T", "Shear")),
    ("torsion:resistance", "Torsion", ("settings", "Shear / torsion / M-V-T", "Torsion")),
    ("combined:dkna_sum", "M-V-T Combined", ("settings", "Shear / torsion / M-V-T", "Combined M-V-T")),
    ("minimum_reinforcement", "Detailing", ("settings", "Detailing", None)),
    ("link_detailing:required_links", "Detailing", ("settings", "Detailing", None)),
    ("clear_spacing", "Detailing", ("settings", "Detailing", None)),
    (None, "Fatigue Results", ("settings", "Fatigue", None)),
])
def test_other_authored_route_families_keep_their_destinations(key, view, destination):
    assert workspace.input_destination({"overview_key": key, "view": view}) == destination


def reviewer(state):
    source = ast.parse((ROOT / "app" / "sector_app.py").read_text(encoding="utf-8"))
    node = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == "_review_overview_inputs")
    code = compile(ast.Module(body=[node], type_ignores=[]), "<actual overview input caller>", "exec")
    function = next(c for c in code.co_consts if isinstance(c, types.CodeType))
    return types.FunctionType(function, {"__builtins__": builtins.__dict__,
        "st": types.SimpleNamespace(session_state=state), "result_workspace": workspace,
        "action_workspace": action_workspace, "load_cases": load_cases, "mvt_workspace": mvt_workspace,
        "_INPUT_STATE_KEY": "_durable_input_scalars"})


def initial_state(names):
    elastic = load_cases.normalise_table(pd.DataFrame({load_cases.NAME: names}), "elastic_cases_base")
    plastic = load_cases.normalise_table(pd.DataFrame({load_cases.NAME: ["PL Preserve"]}), "plastic_cases_base")
    return {"elastic_cases_base": elastic, "plastic_cases_base": plastic,
        action_workspace.FAMILY_KEY: "Plastic", "_analysis_group": "Crack width",
        "_durable_input_scalars": {"sls_fctm": 3.125}, "sls_fctm": 3.125,
        "_overview_selection": ("cracking_threshold", "elastic", "EL Target"),
        "results": {"elastic": {"lambda_cr": 1.2345678901234567}}, "result_sig": ("unchanged",),
        "_pending_input_events": {"unchanged": 42}}


def assert_inputs_and_results_unchanged(state, before):
    for key in ["plastic_cases_base", "elastic_cases_base"]:
        pd.testing.assert_frame_equal(state[key], before[key], check_exact=True)
    for key in ["sls_fctm", "results", "result_sig", "_overview_selection", "_pending_input_events", "_analysis_group"]:
        assert state[key] == before[key]
    assert state["_durable_input_scalars"]["sls_fctm"] == 3.125


def test_actual_caller_selects_exact_elastic_case_without_changing_input_or_result():
    state = initial_state(["EL Other", "EL Target"])
    before = copy.deepcopy(state)
    reviewer(state)({"overview_key": "cracking_threshold", "view": "Elastic Results", "family": "elastic", "case": "EL Target"})
    assert state["_next_workflow_page"] == "actions"
    assert state[action_workspace.FAMILY_KEY] == "Elastic"
    selected = action_workspace.selection_key("elastic_cases_base")
    assert state[selected] == 1
    assert state["_durable_input_scalars"][selected] == 1
    assert state["_durable_input_scalars"][action_workspace.FAMILY_KEY] == "Elastic"
    assert_inputs_and_results_unchanged(state, before)


@pytest.mark.parametrize("names", [["EL Other"], ["EL Target", "EL Target"]])
def test_actual_caller_retains_selection_when_case_identity_is_absent_or_ambiguous(names):
    state = initial_state(names)
    selected = action_workspace.selection_key("elastic_cases_base")
    state[selected] = 0
    before = copy.deepcopy(state)
    reviewer(state)({"overview_key": "cracking_threshold", "view": "Elastic Results", "family": "elastic", "case": "EL Target"})
    assert state["_next_workflow_page"] == "actions"
    assert state[action_workspace.FAMILY_KEY] == "Plastic"
    assert state[selected] == 0
    assert_inputs_and_results_unchanged(state, before)
