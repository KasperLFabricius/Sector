"""Mirror native callable-page client state omitted by Streamlit 1.59.2 AppTest."""

from __future__ import annotations

import ast
import contextvars
import inspect
import textwrap


def _restore_completed_page_context(pages_manager, previous):
    """Restore the last completed context, separately from the requested route."""
    if previous:
        pages_manager.set_current_page_script_hash(previous)


def install_callable_page_client(monkeypatch):
    """Retain actual completed page context and emitted client routing per instance.

    AppTest 1.59.2 retains the shutdown query string but omits the page hash.
    A real browser sends both back on its next widget event. No application
    state, widget payload, timeout, return value or run count changes here.
    """
    import streamlit
    from streamlit.testing.v1 import app_test

    from streamlit.runtime.pages_manager import PagesManager
    from streamlit.runtime.scriptrunner_utils.script_run_context import ScriptRunContext
    from streamlit.runtime.scriptrunner.script_runner import ScriptRunner

    manager_source = inspect.getsource(PagesManager.__init__)
    runner_source = inspect.getsource(ScriptRunner._run_script)
    context_source = inspect.getsource(ScriptRunContext.page_script_hash.fget)
    if ('self._current_page_script_hash: PageHash = ""' not in manager_source
            or "return self.pages_manager.current_page_script_hash" not in context_source
            or "previous_page_script_hash != page_script_hash" not in runner_source):
        raise AssertionError("Review retained AppTest page context for this Streamlit source.")

    original = app_test.AppTest._run
    source = textwrap.dedent(inspect.getsource(original))
    tree = ast.parse(source)
    writes_page_hash = any(
        isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store)
        and node.attr == "_page_hash" for node in ast.walk(tree)
    )
    if (streamlit.__version__ != "1.59.2" or writes_page_hash
            or "pages_manager = PagesManager(" not in source
            or 'script_runner.event_data[-1]["client_state"].query_string' not in source):
        raise AssertionError(
            "Review the callable-page AppTest protocol adapter for this Streamlit source."
        )
    owner = contextvars.ContextVar("sector_apptest_owner", default=None)
    original_runner = app_test.LocalScriptRunner

    class NativePageClientRunner(original_runner):
        def __init__(self, script_path, session_state, pages_manager, args=None, kwargs=None):
            active = owner.get()
            previous = getattr(active, "_sector_completed_page_hash", "") if active is not None else ""
            _restore_completed_page_context(pages_manager, previous)
            super().__init__(script_path, session_state, pages_manager, args=args, kwargs=kwargs)

        def run(self, *args, **kwargs):
            active = owner.get()
            result = super().run(*args, **kwargs)
            if active is not None:
                # The original AppTest reads this same completed shutdown event.
                client = self.event_data[-1]["client_state"]
                active._page_hash = client.page_script_hash
                active._sector_completed_page_hash = client.page_script_hash
            return result

    def run_with_native_client(self, *args, **kwargs):
        token = owner.set(self)
        try:
            return original(self, *args, **kwargs)
        finally:
            owner.reset(token)

    monkeypatch.setattr(app_test, "LocalScriptRunner", NativePageClientRunner)
    monkeypatch.setattr(app_test.AppTest, "_run", run_with_native_client)
