"""Scroll context remains bounded browser presentation state."""
import copy
import json
import types

import pytest

from app import navigation_context as context


@pytest.mark.parametrize("page", list(context.BY_KEY))
def test_context_identity_contains_exact_page_and_subpage(page):
    data = context.context_data(page, 'case <A> / Long', 2, 'session')
    assert json.loads(data['context']) == [page, 'case <A> / Long']
    assert data['epoch'] == 2
    assert data['restore'] is True


@pytest.mark.parametrize('changes', [
    {'page': 'unknown'}, {'subpage': None}, {'subpage': 'x' * 161},
    {'project_epoch': -1}, {'project_epoch': True}, {'project_epoch': 1.0},
    {'scope': ''}, {'scope': 'x' * 65}, {'restore': 'true'},
])
def test_context_rejects_unbounded_or_ambiguous_identity(changes):
    arguments = {'page': 'section', 'subpage': '', 'project_epoch': 0, 'scope': 'session'}
    arguments.update(changes)
    with pytest.raises(ValueError):
        context.context_data(**arguments)


def test_render_writes_only_its_session_identity_and_emits_no_callbacks(monkeypatch):
    state = {'signature': ('exact', 1.234), 'results': {'value': 10.}, '_pending_input_events': {'N': -50.}}
    frozen = copy.deepcopy(state)
    calls = []
    monkeypatch.setattr(context, 'st', types.SimpleNamespace(session_state=state))
    monkeypatch.setattr(context, '_scroll_context', lambda **kwargs: calls.append(kwargs))
    context.render('settings', 'MVT / Shear', project_epoch=3)
    session = state.pop(context.SESSION_KEY)
    assert len(session) == 32
    assert state == frozen
    assert not any(key.startswith('on_') for key in calls[0])
    assert calls[0]['height'] == 0
    assert calls[0]['data']['epoch'] == 3


def test_render_preserves_session_and_allows_explicit_issue_focus(monkeypatch):
    state = {context.SESSION_KEY: 'existing'}
    calls = []
    monkeypatch.setattr(context, 'st', types.SimpleNamespace(session_state=state))
    monkeypatch.setattr(context, '_scroll_context', lambda **kwargs: calls.append(kwargs))
    context.render('actions', 'Elastic', project_epoch=4, restore=False)
    assert state == {context.SESSION_KEY: 'existing'}
    assert calls[0]['data']['restore'] is False


def test_frontend_has_no_python_event_bridge_or_private_dom_selector():
    for forbidden in ('setStateValue', 'setTriggerValue', 'postMessage',
                      'data-testid', 'stMain', 'stAppViewContainer'):
        assert forbidden not in context._JS
    assert 'getComputedStyle' in context._JS
    assert 'return dispose' in context._JS


def test_component_registers_across_fresh_apptest_runtimes_and_reruns():
    from streamlit.testing.v1 import AppTest

    source = '''
import streamlit as st
from app import navigation_context
st.session_state.setdefault("engineering_input", {"N": -123.456})
st.session_state.setdefault("engineering_result", {"stress": 7.25})
st.button("Rerun")
navigation_context.render("section", project_epoch=0)
'''
    for _ in range(2):
        app = AppTest.from_string(source).run()
        for rerun in range(2):
            assert not app.exception
            components = app.get("bidi_component")
            assert len(components) == 1
            assert components[0].proto.component_name == "sector_navigation_scroll_context"
            assert app.session_state["engineering_input"] == {"N": -123.456}
            assert app.session_state["engineering_result"] == {"stress": 7.25}
            if rerun == 0:
                app.button[0].click().run()
