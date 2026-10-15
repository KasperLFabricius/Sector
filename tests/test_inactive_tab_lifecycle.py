"""Retained tab selections survive real Streamlit widget-state cleanup."""

from collections.abc import MutableMapping
from types import SimpleNamespace

import pandas as pd
import pytest
from streamlit.runtime.state import session_state as native_state
from streamlit.runtime.state.common import WidgetMetadata
from streamlit.proto.WidgetStates_pb2 import WidgetState, WidgetStates

from app import input_stage_host as stages


OWNERS = (
    ("_actions_family", ("Plastic", "Elastic", "Fatigue")),
    ("_material_tab", ("Concrete", "Reinforcing steel", "Prestressing steel", "Fatigue details")),
    ("_input_tab", ("1 \xb7 Analysis settings", "2 \xb7 Section", "3 \xb7 Material parameters", "4 \xb7 Loads", "Project")),
)


class State(MutableMapping):
    def __init__(self):
        self.native = native_state.SessionState()

    def __getitem__(self, key):
        return self.native[key]

    def __setitem__(self, key, value):
        self.native[key] = value

    def __delitem__(self, key):
        del self.native[key]

    def __iter__(self):
        return iter(self.native.filtered_state)

    def __len__(self):
        return len(self.native.filtered_state)


class Host:
    open = True

    def __init__(self, state):
        self.state = state

    def tabs(self, labels, *, key, **kwargs):
        return [SimpleNamespace(open=label == self.state[key]) for label in labels]


def _cleanup_context(monkeypatch):
    context = SimpleNamespace(fragment_ids_this_run=None, page_script_hash="materials",
                              shared=SimpleNamespace(widget_ids_this_run=set(), form_ids_this_run=set()))
    monkeypatch.setattr(native_state, "get_script_run_ctx", lambda: context)


@pytest.mark.parametrize("key,labels", OWNERS)
@pytest.mark.parametrize("target_index", [0, 1, 2])
@pytest.mark.parametrize("browser_transport", [False, True])
def test_inactive_native_tab_cleanup_retains_current_selection(key, labels, target_index, browser_transport, monkeypatch):
    _cleanup_context(monkeypatch)
    state = State()
    old, target = labels[(target_index + 1) % len(labels)], labels[target_index]
    state[key] = old
    state.native._compact_state()
    state[key] = target
    widget_id = "$$ID-lifecycle-" + key
    metadata = WidgetMetadata(widget_id, lambda value: value or labels[0], lambda value: value,
                              "string_value")
    assert state.native.register_widget(metadata, key).value == target
    state["_durable_input_scalars"] = {key: target}
    state.native._compact_state()
    if browser_transport:
        state.native.set_widgets_from_proto(WidgetStates(widgets=[
            WidgetState(id=widget_id, string_value=target),
        ]))
    # The queued public page switch interrupts before hidden input bodies run.
    state.native._remove_stale_widgets(frozenset())
    payload = pd.DataFrame({"N": [-17.125], "M": [9.625]})
    state["engineering"] = payload.copy(deep=True)
    hidden = stages.InputStage(None, active=False, state=state)
    assert not any(tab.open for tab in stages.stateful_input_tabs(hidden, labels, key=key, state=state))
    state.native._remove_stale_widgets(frozenset())
    assert state[key] == target
    # A second switch compacts the retained value under its old widget ID,
    # then cleanup exposes the initial user-key value before active re-entry.
    state.native._compact_state()
    state.native._remove_stale_widgets(frozenset())
    assert state[key] == old
    state.setdefault(key, state["_durable_input_scalars"][key])
    tabs = stages.stateful_input_tabs(Host(state), labels, key=key, state=state)
    assert [tab.open for tab in tabs] == [label == target for label in labels]
    pd.testing.assert_frame_equal(state["engineering"], payload, check_exact=True)


@pytest.mark.parametrize("key,labels", OWNERS)
def test_visible_native_tab_event_precedes_old_mirrors(key, labels):
    state = {key: labels[1], "_durable_input_scalars": {key: labels[0]},
             "_pending_input_events": {key: labels[2]}}
    state["_mounted_input_stage_widget_keys"] = {key}
    tabs = stages.stateful_input_tabs(Host(state), labels, key=key, state=state)
    assert state[key] == labels[1]
    assert [tab.open for tab in tabs] == [False, True] + [False] * (len(labels) - 2)
    assert state["_pending_input_events"][key] == labels[2]


@pytest.mark.parametrize("key,labels", OWNERS)
@pytest.mark.parametrize("authority", ["pending", "durable", "live"])
def test_inactive_tab_retains_interrupted_event_priority(key, labels, authority):
    state = {key: labels[0]}
    if authority in {"pending", "durable"}:
        state["_durable_input_scalars"] = {key: labels[1]}
    if authority == "pending":
        state["_pending_input_events"] = {key: labels[2], "engineering_value": -19.875}
    expected = labels[{"pending": 2, "durable": 1, "live": 0}[authority]]
    hidden = stages.InputStage(None, active=False, state=state)
    assert not any(tab.open for tab in stages.stateful_input_tabs(hidden, labels, key=key, state=state))
    assert state[key] == expected
    if authority == "pending":
        assert state["_pending_input_events"] == {key: labels[2], "engineering_value": -19.875}


@pytest.mark.parametrize("key,labels", OWNERS)
def test_expired_pending_tab_keeps_valid_durable_selection(key, labels):
    state = {key: labels[0], "_pending_input_events": {key: "Removed stage"},
             "_durable_input_scalars": {key: labels[1]}}
    hidden = stages.InputStage(None, active=False, state=state)
    tabs = stages.stateful_input_tabs(hidden, labels, key=key, state=state)
    assert not any(tab.open for tab in tabs)
    assert state[key] == labels[1]
    assert key not in state["_pending_input_events"]


@pytest.mark.parametrize("key,labels", OWNERS)
def test_registered_visible_browser_tab_click_precedes_retained_selection(key, labels, monkeypatch):
    _cleanup_context(monkeypatch)
    state = State()
    state[key] = labels[0]
    state["_durable_input_scalars"] = {key: labels[0]}
    widget_id = "$$ID-active-event-" + key
    metadata = WidgetMetadata(widget_id, lambda value: value or labels[0], lambda value: value,
                              "string_value")
    assert state.native.register_widget(metadata, key).value == labels[0]
    stages.stateful_input_tabs(Host(state), labels, key=key, state=state)
    state.native._compact_state()
    state.native.set_widgets_from_proto(WidgetStates(widgets=[
        WidgetState(id=widget_id, string_value=labels[1]),
    ]))
    assert state[key] == labels[1]
    active = stages.stateful_input_tabs(Host(state), labels, key=key, state=state)
    assert state[key] == labels[1]
    assert [stage.open for stage in active] == [label == labels[1] for label in labels]
    assert state["_durable_input_scalars"][key] == labels[0]
