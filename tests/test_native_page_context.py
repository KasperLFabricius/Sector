"""Pure retained-context protocol qualification; no app, browser or calculation."""
import ast
import inspect
from pathlib import Path
from types import SimpleNamespace
import textwrap
import types
import pytest
from streamlit.runtime.pages_manager import PagesManager
from streamlit.runtime.scriptrunner.script_cache import ScriptCache
from streamlit.runtime.scriptrunner.script_runner import ScriptRunner
from streamlit.runtime.state.session_state import SessionState
from streamlit.runtime.state.safe_session_state import SafeSessionState
from streamlit.runtime.state.common import WidgetMetadata
from streamlit.proto.WidgetStates_pb2 import WidgetStates,WidgetState
import native_callable_page_client as adapter

@pytest.mark.parametrize('previous,requested,fragment,expect_cleanup',[
 ('','actions',False,True),('actions','actions',False,False),
 ('actions','materials',False,True),('actions','actions',True,False),
 ('materials','actions',False,True)])
def test_actual_page_cleanup_branch_distinguishes_prior_completed_from_request(tmp_path,monkeypatch,previous,requested,fragment,expect_cleanup):
    manager=PagesManager(str(tmp_path/'app.py'),ScriptCache(),setup_watcher=False)
    assert manager.current_page_script_hash==''
    adapter._restore_completed_page_context(manager,previous)
    native=SessionState()
    meta=WidgetMetadata('$$ID-real-tab',deserializer=lambda v:v,serializer=str,value_type='string_value')
    native.register_widget(meta,'tab')
    native._new_widget_state.set_widget_from_proto(WidgetState(id=meta.id,string_value='Elastic'))
    safe=SafeSessionState(native,lambda:None)
    calls=[]
    class ObservedState:
        def query_params(self):return safe.query_params()
        def on_script_finished(self,ids):
            calls.append(ids);safe.on_script_finished(ids)
    source=ast.parse(textwrap.dedent(inspect.getsource(ScriptRunner._run_script)))
    nodes=list(ast.walk(source));condition=next(n for n in nodes if isinstance(n,ast.If) and ast.unparse(n.test)=='previous_page_script_hash != page_script_hash')
    function=ast.FunctionDef(name='cleanup',args=ast.arguments(posonlyargs=[],args=[],kwonlyargs=[],kw_defaults=[],defaults=[]),body=[condition],decorator_list=[])
    tree=ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[]))
    code=next(v for v in compile(tree,'installed-page-cleanup','exec').co_consts if isinstance(v,types.CodeType))
    globals_={'previous_page_script_hash':manager.current_page_script_hash,'page_script_hash':requested,
      'rerun_data':SimpleNamespace(widget_states=WidgetStates(),query_string='',fragment_id_queue=['header'] if fragment else []),
      'self':SimpleNamespace(_session_state=ObservedState(),_pages_manager=manager)}
    import streamlit.runtime.state.session_state as state_module
    monkeypatch.setattr(state_module,'get_script_run_ctx',lambda:SimpleNamespace(page_script_hash=previous,fragment_ids_this_run=None))
    types.FunctionType(code,globals_)()
    assert bool(calls)==expect_cleanup
    assert (meta.id in native._new_widget_state.states)==(not expect_cleanup)


def install_fake_original(monkeypatch,tmp_path):
    from streamlit.testing.v1 import app_test
    installed_text=Path(app_test.__file__).read_text(encoding='utf-8')
    app_class=next(n for n in ast.parse(installed_text).body if isinstance(n,ast.ClassDef) and n.name=='AppTest')
    original_node=next(n for n in app_class.body if isinstance(n,ast.FunctionDef) and n.name=='_run')
    real_source=textwrap.dedent(ast.get_source_segment(installed_text,original_node))
    real_getsource=inspect.getsource
    calls=[]
    class FakeRunner:
        def __init__(self,script_path,session_state,pages_manager,args=None,kwargs=None):
            self.manager=pages_manager;self.session=session_state
            calls.append(('init',pages_manager.current_page_script_hash))
        def run(self,wire,query,timeout,requested):
            calls.append(('run',wire,query,timeout,requested,self.manager.current_page_script_hash))
            if self.session.fail:raise self.session.fail('original failure')
            self.event_data=[{'client_state':SimpleNamespace(page_script_hash=self.session.completed)}]
            return self.session.result
    def original(self,wire=None,timeout=3):
        manager=PagesManager(str(tmp_path/'app.py'),ScriptCache(),setup_watcher=False)
        runner=app_test.LocalScriptRunner('app.py',self,manager)
        return runner.run(wire,{'q':'x'},timeout,self._page_hash)
    monkeypatch.setattr(app_test.AppTest,'_run',original)
    monkeypatch.setattr(app_test,'LocalScriptRunner',FakeRunner)
    monkeypatch.setattr(inspect,'getsource',lambda target:real_source if target is original else real_getsource(target))
    adapter.install_callable_page_client(monkeypatch)
    return app_test.AppTest._run,calls


def test_actual_adapter_retains_completed_context_per_instance_without_changing_wire(monkeypatch,tmp_path):
    run,calls=install_fake_original(monkeypatch,tmp_path)
    first=SimpleNamespace(_page_hash='',completed='actions',fail=False,result=object())
    second=SimpleNamespace(_page_hash='',completed='home',fail=False,result=object())
    wire=WidgetStates(widgets=[WidgetState(id='text',string_value='12,5')])
    before=wire.SerializeToString()
    assert run(first,wire,timeout=9) is first.result
    assert first._sector_completed_page_hash=='actions'
    assert run(first,wire,timeout=9) is first.result
    assert calls[-1][-1]=='actions'
    assert calls[-1][1] is wire and calls[-1][3]==9
    assert wire.SerializeToString()==before
    assert run(second,wire) is second.result
    assert calls[-1][-1]==''
    first._page_hash='materials';first.completed='materials'
    assert run(first,wire) is first.result
    assert calls[-1][-2:] == ('materials','actions')
    assert first._sector_completed_page_hash=='materials'
    assert second._sector_completed_page_hash=='home'
    first.fail=ValueError;first._page_hash='report'
    with pytest.raises(ValueError,match='original failure'):run(first,wire)
    assert first._sector_completed_page_hash=='materials'
    # Explicit native tab events are delegated verbatim, without synthesized tabs.
    second_wire=WidgetStates(widgets=[WidgetState(id='tab',string_value='Elastic')])
    assert run(second,second_wire) is second.result
    assert calls[-1][1] is second_wire
    assert len(second_wire.widgets)==1 and second_wire.widgets[0].string_value=='Elastic'


@pytest.mark.parametrize('error_type',(ValueError,TimeoutError))
def test_internal_callable_switch_and_incomplete_runs_keep_actual_completed_context(monkeypatch,tmp_path,error_type):
    run,calls=install_fake_original(monkeypatch,tmp_path)
    app=SimpleNamespace(_page_hash='actions',_sector_completed_page_hash='actions',completed='report',fail=False,result=object())
    # The body can st.switch_page before final shutdown; its actual emitted page wins.
    assert run(app,None,timeout=12) is app.result
    assert calls[-1][-2:]==('actions','actions')
    assert app._page_hash==app._sector_completed_page_hash=='report'
    app._page_hash='materials';app.fail=error_type
    with pytest.raises(error_type,match='original failure'):run(app,None,timeout=12)
    assert app._page_hash=='materials'
    assert app._sector_completed_page_hash=='report'
    assert calls[-1][-2:]==('materials','report')
