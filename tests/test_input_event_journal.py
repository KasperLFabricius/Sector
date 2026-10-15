"""Pure callback and installed-state regressions for request-bound repeats."""
import ast
import copy
from pathlib import Path
import sys
from types import CodeType, FunctionType, SimpleNamespace

import pytest
from streamlit.proto.WidgetStates_pb2 import WidgetState, WidgetStates
from streamlit.runtime.state.common import WidgetMetadata
from streamlit.runtime.state.session_state import SessionState
from streamlit.runtime.state.safe_session_state import SafeSessionState
from streamlit.runtime.state.session_state_proxy import SessionStateProxy
import streamlit.runtime.state.session_state_proxy as proxy_module

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
for source_path in (ROOT, APP):
    if str(source_path) not in sys.path:
        sys.path.insert(0, str(source_path))
import input_event_journal
from workflow_navigation import take_calculate_request


def state_for(value=2.0):
    signature = ("complete", ("elastic", 2.0))
    return {"_main_page": "Inputs", "_inputs_build_in_progress": False,
            "_latest_inputs": {"signature": signature, "el_phi": value},
            "_workflow_calculate_request": {"signature": signature, "generation": 1},
            "_project_upload_widget_generation": 1, "el_phi": value}


def callback_for(state, *, original=False):
    source = (APP / "sector_app.py").read_text(encoding="utf-8")
    if original:
        changed = '''    from input_event_journal import repeats_requested_input
    if (
        workspace == "Inputs" and key in st.session_state
        and not repeats_requested_input(st.session_state, key, callback=callback)
    ):
        pending = dict(st.session_state.get(_PENDING_INPUT_EVENTS_KEY, {}))'''
        previous = '''    if workspace == "Inputs" and key in st.session_state:
        pending = dict(st.session_state.get(_PENDING_INPUT_EVENTS_KEY, {}))'''
        assert source.count(changed) == 1
        source = source.replace(changed, previous)
    tree = ast.parse(source)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_record_input_event")
    code = compile(ast.Module(body=[node], type_ignores=[]), "callback", "exec")
    function = next(c for c in code.co_consts if isinstance(c, CodeType))
    scope = {"__builtins__": __builtins__, "copy": copy, "st": SimpleNamespace(session_state=state),
             "project_io": SimpleNamespace(REPORT_PROFILE_KEY="report_profile"),
             "_PENDING_INPUT_EVENTS_KEY": "_pending_input_events", "_NON_REPLAYABLE_INPUT_EVENT_KEYS": frozenset(),
             "_REPORT_STATE_SCALAR_SET": frozenset({"rep_author"}), "_PENDING_REPORT_EVENTS_KEY": "_pending_report_events"}
    return FunctionType(function, scope, argdefs=(None, (), None))


@pytest.mark.parametrize("value", [2.0, 0.0, -0.0, 2, True, False, "same"])
def test_exact_canonical_repeat_preserves_state(value):
    state = state_for(value)
    before = copy.deepcopy(state)
    assert input_event_journal.repeats_requested_input(state, "el_phi")
    callback_for(state)("el_phi")
    assert state == before
    assert take_calculate_request(state, state["_latest_inputs"], pending=False, generation=1)


@pytest.mark.parametrize("committed,current", [(2.0, 2.1), (0.0, -0.0), (-0.0, 0.0), (2, 2.0), (True, 1), (1, True), (False, 0), ("a", "b"), (2.0, "2.0")])
def test_every_real_value_or_type_change_is_journaled(committed, current):
    state = state_for(committed)
    state["el_phi"] = current
    callback_for(state)("el_phi")
    assert type(state["_pending_input_events"]["el_phi"]) is type(current)
    assert input_event_journal.project_io.result_sha256(state["_pending_input_events"]["el_phi"]) == input_event_journal.project_io.result_sha256(current)
    assert not take_calculate_request(state, state["_latest_inputs"], pending=True, generation=1)


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), -float("inf"), [], {}, (2.0,), b"2"])
def test_uncertain_or_structured_values_fail_closed(value):
    state = state_for(value)
    assert not input_event_journal.repeats_requested_input(state, "el_phi")
    callback_for(state)("el_phi")
    assert "el_phi" in state["_pending_input_events"]


@pytest.mark.parametrize("change", [
    {"_inputs_build_in_progress": True}, {"_workflow_calculate_request": None},
    {"_latest_inputs": None}, {"_project_upload_widget_generation": 2},
    {"_project_upload_widget_generation": True}, {"_pending_input_events": None},
    {"_workflow_calculate_request": {"signature": (), "generation": 1}},
    {"_workflow_calculate_request": {"signature": ("different",), "generation": 1}},
    {"_workflow_calculate_request": {"signature": ("complete", ("elastic", 2.0)), "generation": True}},
    {"_latest_inputs": {"signature": (), "el_phi": 2.0}},
    {"_latest_inputs": {"signature": ("complete", ("elastic", 2.0))}},
])
def test_incomplete_stale_or_unproven_model_fails_closed(change):
    state = state_for()
    state.update(change)
    assert not input_event_journal.repeats_requested_input(state, "el_phi")


def test_queued_revert_remains_pending_and_replaces_previous_edit():
    state = state_for()
    state["_pending_input_events"] = {"el_phi": 2.1, "other": 7}
    callback_for(state)("el_phi")
    assert state["_pending_input_events"] == {"el_phi": 2.0, "other": 7}
    assert not take_calculate_request(state, state["_latest_inputs"], pending=True, generation=1)


def test_other_journal_keys_and_request_remain_exact():
    state = state_for()
    pending = {"other": [1, 2]}
    request = state["_workflow_calculate_request"]
    state["_pending_input_events"] = pending
    callback_for(state)("el_phi")
    assert state["_pending_input_events"] is pending
    assert pending == {"other": [1, 2]}
    assert state["_workflow_calculate_request"] is request


def test_custom_callback_retains_journal_order_and_delegation():
    state = state_for()
    observed = []
    def delegate(a, *, b):
        observed.append((a, b, copy.deepcopy(state["_pending_input_events"])))
    callback_for(state)("el_phi", delegate, (3,), {"b": 4})
    assert observed == [(3, 4, {"el_phi": 2.0})]


def test_report_journal_is_unchanged():
    state = state_for()
    state.update(_main_page="Report", rep_author="Author")
    callback_for(state)("rep_author")
    assert state["_pending_report_events"] == {"rep_author": "Author"}


@pytest.mark.parametrize("key", ["_input_tab", "unknown", "plastic_cases_editor", "fatigue_spectrum_editor"])
def test_navigation_unknown_and_editor_keys_fail_closed(key):
    state = state_for()
    state[key] = {"edited_rows": {}} if "editor" in key else "value"
    assert not input_event_journal.repeats_requested_input(state, key)
    callback_for(state)(key)
    assert key in state["_pending_input_events"]


@pytest.mark.parametrize("original", [True, False])
@pytest.mark.parametrize("incoming", [2.0, 2.1])
def test_installed_native_callback_after_compaction_preserves_request_contract(original, incoming, monkeypatch):
    native = SessionState()
    safe = SafeSessionState(native, lambda: None)
    monkeypatch.setattr(proxy_module, "get_session_state", lambda: safe)
    proxy = SessionStateProxy()
    for key, value in state_for().items():
        native[key] = value
    # A remounted widget can have a default in its old widget slot while the
    # completed canonical input remains2.0. Exercise real callback dispatch.
    identity = "$$ID-late-el_phi"
    callback = callback_for(proxy, original=original)
    metadata = WidgetMetadata(identity, lambda value: 0.0 if value is None else value,
                              lambda value: value, "double_value", callback=callback, callback_args=("el_phi",))
    native.register_widget(metadata, "el_phi")
    native["el_phi"] = 0.0
    native._compact_state()
    native.on_script_will_rerun(WidgetStates(widgets=[WidgetState(id=identity, double_value=incoming)]))
    pending = bool(native.filtered_state.get("_pending_input_events"))
    expected_pending = original or incoming != 2.0
    assert pending is expected_pending
    assert native["el_phi"] == incoming
    assert native["_latest_inputs"]["el_phi"] == 2.0
    accepted = take_calculate_request(proxy, native["_latest_inputs"], pending=pending, generation=1)
    assert accepted is (not expected_pending)


def test_genuine_edit_survives_interruption_until_original_commit():
    state = state_for()
    state["el_phi"] = 2.1
    callback_for(state)("el_phi")
    assert state["_pending_input_events"] == {"el_phi": 2.1}
    state["_inputs_build_in_progress"] = True
    callback_for(state)("el_phi")
    assert state["_pending_input_events"] == {"el_phi": 2.1}
    source = (APP / "sector_app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_commit_input_fragment")
    code = compile(ast.Module(body=[node], type_ignores=[]), "commit", "exec")
    function = next(c for c in code.co_consts if isinstance(c, CodeType))
    snapshots = []
    autosaves = []
    def snapshot(inputs):
        snapshots.append(copy.deepcopy(state["_pending_input_events"]))
        state["_latest_inputs"] = inputs
    scope = {"__builtins__": __builtins__, "st": SimpleNamespace(session_state=state),
             "_snapshot_input_state": snapshot, "_PENDING_INPUT_EVENTS_KEY": "_pending_input_events",
             "_INPUT_ISSUE_FOCUS_KEY": "_input_issue_focus", "_INPUT_BUILD_KEY": "_inputs_build_in_progress",
             "_LAST_WORKSPACE_KEY": "_last_completed_workspace", "_measured_autosave": lambda: autosaves.append(True)}
    inputs = {"signature": ("new", 2.1), "el_phi": 2.1}
    FunctionType(function, scope)(inputs)
    assert snapshots == [{"el_phi": 2.1}]
    assert state["_latest_inputs"] is inputs
    assert "_pending_input_events" not in state
    assert state["_inputs_build_in_progress"] is False
    assert state["_last_completed_workspace"] == "Inputs"
    assert autosaves == [True]
    assert not take_calculate_request(state, inputs, pending=False, generation=1)
