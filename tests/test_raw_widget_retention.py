"""Pure native-state qualification of raw-host cleanup and remount retention."""
import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
import streamlit.runtime.state.session_state as state_module
import streamlit.runtime.state.session_state_proxy as proxy_module
from streamlit.proto.WidgetStates_pb2 import WidgetState, WidgetStates
from streamlit.runtime.state.common import WidgetMetadata
from streamlit.runtime.state.safe_session_state import SafeSessionState
from streamlit.runtime.state.session_state import SessionState

HERE = Path(__file__).parent
SOURCE = HERE.parents[0] / 'app/sector_app.py'
if not SOURCE.exists():
    SOURCE = HERE / 'sector_app.py'
_spec = importlib.util.spec_from_file_location('publication_proof', HERE / 'test_seeded_widget_publication.py')
proof = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(proof)
HOST_SOURCE = HERE.parent / 'app/input_stage_host.py'
if not HOST_SOURCE.exists():
    HOST_SOURCE = HERE / 'input_stage_host.py'
_spec = importlib.util.spec_from_file_location('retention_host', HOST_SOURCE)
host_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(host_module)
InputStage = host_module.InputStage


def setup(monkeypatch):
    native = SessionState()
    context = SimpleNamespace(page_script_hash='owner', fragment_ids_this_run=None,
                              widget_ids_this_run=set(), form_ids_this_run=set())
    context.shared = context
    monkeypatch.setattr(state_module, 'get_script_run_ctx', lambda: context)
    safe = SafeSessionState(native, lambda: None)
    monkeypatch.setattr(proxy_module, 'get_session_state', lambda: safe)
    calls = []
    def journal(key, callback, args, kwargs):
        calls.append((key, native[key]))
        if callback:
            callback(*args, **kwargs)
    namespace = {'st': SimpleNamespace(session_state=proxy_module.SessionStateProxy()),
                 'InputStage': InputStage, '_record_input_event': journal}
    namespace['_input_widget_kwargs'] = proof.function(SOURCE, '_input_widget_kwargs', namespace)
    return native, context, namespace, calls


def wire(identity, kind, value):
    item = WidgetState(id=identity)
    setattr(item, kind, value)
    return WidgetStates(widgets=[item])


@pytest.mark.parametrize('name,method,args,retained,edited,intrinsic,wire_type', proof.CASES)
@pytest.mark.parametrize('transition', [
    'normal_cleanup', 'incoming_at_cleanup', 'interrupted_transition',
    'replacement_unmounted', 'replacement_before_cleanup', 'replacement_without_value',
    'changed_identity_remount', 'same_page_live_edit',
])
def test_raw_helpers_keep_latest_value_through_native_lifecycle(
    monkeypatch, name, method, args, retained, edited, intrinsic, wire_type, transition
):
    native, context, namespace, calls = setup(monkeypatch)
    key = 'conc_fck' if name == '_number' else 'retained'
    identity = '$$ID-owner-' + key
    observations = []
    callback_values = []
    callback = lambda: callback_values.append(native[key])

    class Box:
        def __getattr__(self, called):
            assert called == method
            def invoke(*a, **kw):
                assert kw['persist_state'] == 'session'
                metadata = WidgetMetadata(
                    identity, deserializer=lambda value: intrinsic if value is None else value,
                    serializer=lambda value: value, value_type=wire_type,
                    callback=kw['on_change'], callback_args=kw['args'],
                    callback_kwargs=kw.get('kwargs'), persist_state=kw['persist_state'],
                )
                result = native.register_widget(metadata, key)
                context.widget_ids_this_run.add(identity)
                observations.append(result)
                return result.value
            return invoke

    helper = proof.function(SOURCE, name, namespace)
    def mount():
        context.widget_ids_this_run.clear()
        if name == '_number':
            return helper(Box(), *args, disabled=False)
        return helper(Box(), *args, key, on_change=callback)

    native[key] = retained
    assert mount() == retained
    native.on_script_finished({identity})
    context.widget_ids_this_run.clear()
    native.on_script_will_rerun(wire(identity, wire_type, edited))
    assert calls == [(key, edited)]
    assert callback_values == ([] if name == '_number' else [edited])
    if transition != 'incoming_at_cleanup':
        assert mount() == edited
        native.on_script_finished({identity})
        context.widget_ids_this_run.clear()
        native.on_script_will_rerun(WidgetStates())
    expected = edited
    if transition == 'replacement_before_cleanup':
        native[key] = retained
        expected = retained
    if transition != 'same_page_live_edit':
        context.page_script_hash = 'other'
        native.on_script_finished(set())
        assert native[key] == expected
    if transition == 'interrupted_transition':
        native.on_script_will_rerun(WidgetStates())
        native.on_script_finished(set())
        assert native[key] == edited
    if transition in {'replacement_unmounted', 'replacement_without_value'}:
        # Same native key deletion/assignment performed by project replacement.
        if key in native:
            del native[key]
        if transition == 'replacement_unmounted':
            native[key] = retained
            expected = retained
        else:
            expected = intrinsic if name == '_number' else retained
    native.on_script_will_rerun(WidgetStates())
    context.page_script_hash = 'owner'
    if transition == 'changed_identity_remount':
        identity = '$$ID-remounted-' + key
    assert mount() == expected
    assert native[key] == expected
    if observations[-1].value_changed:
        proof.assert_native_frontend_value(method, observations[-1], expected)
    assert calls == [(key, edited)]


@pytest.mark.parametrize('host_kind', ['raw', 'active_input_stage', 'inactive_input_stage', 'unspecified'])
@pytest.mark.parametrize('explicit', ['missing', None, 'page', 'session'])
def test_host_policy_preserves_explicit_options_callbacks_and_input_stage(monkeypatch, host_kind, explicit):
    native, context, namespace, calls = setup(monkeypatch)
    delegate = object()
    host = delegate if host_kind == 'raw' else None if host_kind == 'unspecified' else InputStage(delegate, active=host_kind == 'active_input_stage', state={})
    callback = object()
    original = {'on_change': callback, 'args': (7,), 'kwargs': {'x': 'value'}, 'help': 'Exact help'}
    if explicit != 'missing':
        original['persist_state'] = explicit
    before = dict(original)
    actual = namespace['_input_widget_kwargs']('key', original, host=host)
    assert original == before
    assert actual['args'] == ('key', callback, (7,), {'x': 'value'})
    assert actual['help'] == 'Exact help'
    if explicit != 'missing':
        assert actual['persist_state'] == explicit
    elif host_kind == 'raw':
        assert actual['persist_state'] == 'session'
    else:
        assert 'persist_state' not in actual


@pytest.mark.parametrize('owner,key', [('_report_source_editor','_report_source_assignment'),
    ('_report_workspace','_report_presentation_preset_choice'),('_quick_section_geometry','qs_rebar_mode')])
def test_adjacent_raw_choices_use_native_session_retention(owner,key):
    tree=ast.parse(SOURCE.read_text(encoding='utf8'))
    function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==owner)
    matches=[n for n in ast.walk(function) if isinstance(n,ast.Call) and any(
        k.arg=='key' and ((isinstance(k.value,ast.Constant) and k.value.value==key)
        or (key=='_report_source_assignment' and isinstance(k.value,ast.Name) and k.value.id=='key'))
        for k in n.keywords)]
    assert len(matches)==1
    assert any(k.arg=='persist_state' and isinstance(k.value,ast.Constant) and k.value.value=='session' for k in matches[0].keywords)


@pytest.mark.parametrize("scope", [None, "session"])
@pytest.mark.parametrize("key,original,edited,wire_type", [
    ("autosave_on", True, False, "bool_value"),
    ("autosave_min", 2, 9, "int_value"),
    ("_report_source_assignment", "Plastic/P2", "Elastic/E1", "string_value"),
    ("_report_presentation_preset_choice", "Audit", "Brief", "string_value"),
    ("qs_rebar_mode", "By number", "By spacing", "string_value"),
])
def test_installed_cleanup_reproduces_old_value_and_session_policy_retains_edit(
    monkeypatch, scope, key, original, edited, wire_type
):
    native, context, namespace, calls = setup(monkeypatch)
    identity = "$$ID-original-" + key
    metadata = WidgetMetadata(identity, deserializer=lambda value: original if value is None else value,
                              serializer=lambda value: value, value_type=wire_type, persist_state=scope)
    native[key] = original
    native._compact_state()
    # An old raw user key exists before this control first registers.
    assert native._old_state[key] == original
    native[key] = native[key]
    native.register_widget(metadata,key)
    native.on_script_will_rerun(wire(identity,wire_type,edited))
    assert native[key] == edited
    native[key] = native[key]
    native.register_widget(metadata,key)
    native.on_script_will_rerun(WidgetStates())
    context.page_script_hash = "other"
    native.on_script_finished(set())
    assert native[key] == (edited if scope == "session" else original)
    if scope == "session":
        # Full project replacement while the previous widget is unmounted.
        del native[key]
        native[key] = original
        native.on_script_will_rerun(WidgetStates())
        context.page_script_hash = "owner"
        native[key] = native[key]
        assert native.register_widget(metadata,key).value == original


@pytest.mark.parametrize("active", [False, True])
def test_actual_input_stage_receives_unchanged_policy_and_retained_value(monkeypatch, active):
    native, context, namespace, calls = setup(monkeypatch)
    native["key"] = False
    native["_durable_input_scalars"] = {"key": False}
    observations = []
    class Delegate:
        def checkbox(self,*args,**kwargs):
            observations.append((args,kwargs))
            assert "persist_state" not in kwargs
            return kwargs["value"]
    stage = InputStage(Delegate(),active=active,state=namespace["st"].session_state)
    helper = proof.function(SOURCE,"_seeded_checkbox",namespace)
    assert helper(stage,"Exact label",True,"key") is False
    assert native["key"] is False
    assert len(observations) == int(active)
