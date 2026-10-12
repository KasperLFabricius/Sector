"""Verify idle autosave timing without a solver or workspace rerun."""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

APP = Path(__file__).resolve().parents[1] / "app" / "sector_app.py"


@pytest.fixture
def service():
    tree = ast.parse(APP.read_text(encoding="utf-8-sig"))
    names = {"_autosave_preferences", "_maybe_autosave", "_idle_autosave"}
    selected = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    constant = next(n.value.value for n in tree.body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "_AUTOSAVE_DEFAULT_MIN" for t in n.targets))
    state = {"_autosave_t": 100.0}
    calls = []
    intervals = []
    st = SimpleNamespace(session_state=state, toast=lambda x: calls.append(("toast", x)))
    def fragment(*, run_every):
        intervals.append(run_every)
        return lambda fn: fn
    st.fragment = fragment
    clock = SimpleNamespace(value=219.999)
    ns = {"st": st, "time": SimpleNamespace(time=lambda: clock.value),
          "_INPUT_STATE_KEY": "durable", "_REPORT_BUILD_KEY": "report_build", "_PENDING_REPORT_EVENTS_KEY": "report_pending",
          "_AUTOSAVE_DEFAULT_MIN": constant,
          "_has_uncommitted_inputs": lambda: bool(state.get("pending") or state.get("input_build")),
          "_perform_autosave": lambda: calls.append(("save", clock.value)) or True}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(APP), "exec"), ns)
    return ns, state, calls, clock, intervals


def test_idle_default_is_two_minutes_and_fragment_is_isolated(service):
    ns, state, calls, clock, intervals = service
    assert ns["_autosave_preferences"]({}) == (True, 2)
    assert intervals == [5]
    ns["_idle_autosave"]()
    assert calls == []
    assert state["_autosave_t"] == 100.0
    clock.value = 220.0
    ns["_idle_autosave"]()
    assert calls == [("save", 220.0), ("toast", "Autosaved.")]
    clock.value = 225.0
    ns["_idle_autosave"]()
    assert len(calls) == 2


@pytest.mark.parametrize("page", ["Inputs", "Analysis", "Report"])
@pytest.mark.parametrize("guard", ["pending", "input_build", "report_build", "report_pending", "_pending_project"])
def test_idle_cannot_serialize_partial_or_replacement_state(service, page, guard):
    ns, state, calls, clock, _ = service
    state.update({"_main_page": page, guard: True})
    clock.value = 220.0
    ns["_idle_autosave"]()
    assert calls == []
    assert state["_autosave_t"] == 100.0
    del state[guard]
    ns["_idle_autosave"]()
    assert calls[0] == ("save", 220.0)


@pytest.mark.parametrize("enabled,minutes", [(False, 2), (True, 5), (True, 120)])
def test_idle_preserves_explicit_hidden_preferences(service, enabled, minutes):
    ns, state, calls, clock, _ = service
    state["durable"] = {"autosave_on": enabled, "autosave_min": minutes}
    clock.value = 220.0
    ns["_idle_autosave"]()
    assert calls == []
    clock.value = 100.0 + minutes * 60
    ns["_idle_autosave"]()
    assert bool(calls) is enabled


def test_idle_no_change_or_failed_write_has_no_success_notice(service):
    ns, state, calls, clock, _ = service
    ns["_perform_autosave"] = lambda: False
    clock.value = 220.0
    ns["_idle_autosave"]()
    assert calls == []
    assert state["_autosave_t"] == 220.0


@pytest.fixture
def recovery_service(tmp_path):
    import hashlib
    import json
    import os
    import pathlib
    from datetime import datetime
    from app import recovery_store

    tree = ast.parse(APP.read_text(encoding="utf-8-sig"))
    names = {"_autosave_startup", "_perform_autosave", "_write_autosave", "_maybe_autosave", "_autosave_preferences"}
    selected = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    state = {}
    notices = []
    path = tmp_path / "autosave.json"
    def parse(data):
        value = json.loads(data)
        return value.get("tables", {}), value.get("scalars", {})
    project = '{"tables":{},"scalars":{"project":"current"}}\n'
    ns = {
        "st": SimpleNamespace(session_state=state, toast=notices.append),
        "pathlib": pathlib, "os": os, "datetime": datetime,
        "time": SimpleNamespace(time=lambda: 1000.0), "recovery_store": recovery_store,
        "_INPUT_STATE_KEY": "durable", "_AUTOSAVE_DEFAULT_MIN": 2,
        "_autosave_path": lambda: path,
        "_has_uncommitted_inputs": lambda: False,
        "project_io": SimpleNamespace(parse_project=parse,
            engineer_error_message=lambda exc: "The recovery file is invalid",
            persistence_sha256=lambda *args: "restored-identity"),
        "_pts_from_df": lambda *args: [(0, 0), (1, 0), (0, 1)],
        "_current_table": lambda *args: None, "_CORNER_COLS": (),
        "_project_persistence_hash": lambda: "current-identity",
        "_gather_project": lambda: project,
    }
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(APP), "exec"), ns)
    return ns, state, notices, path


@pytest.mark.parametrize("upload", [False, True])
def test_invalid_recovery_is_preserved_even_with_queued_upload(recovery_service, upload):
    ns, state, _, path = recovery_service
    path.write_bytes(b"invalid existing recovery")
    if upload:
        state["_pending_project"] = "explicit uploaded project"
    ns["_autosave_startup"]()
    assert state["_autosave_recovery_blocked"]
    assert ns["_perform_autosave"]() is False
    assert path.read_bytes() == b"invalid existing recovery"
    if upload:
        assert state["_pending_project"] == "explicit uploaded project"


def test_startup_snapshot_cannot_replace_later_session_write(recovery_service):
    ns, state, notices, path = recovery_service
    path.write_text('{"tables":{},"scalars":{"project":"A"}}')
    ns["_autosave_startup"]()
    path.write_text('{"tables":{},"scalars":{"project":"B"}}')
    before = path.read_bytes()
    assert ns["_perform_autosave"]() is False
    assert ns["_perform_autosave"]() is False
    assert len(notices) == 1
    assert "Download project" in notices[0]
    assert path.read_bytes() == before


def test_own_unchanged_project_does_not_rewrite_recovery(recovery_service):
    ns, state, notices, path = recovery_service
    ns["_autosave_startup"]()
    assert ns["_perform_autosave"]() is True
    before = path.read_bytes(), path.stat().st_mtime_ns
    assert ns["_perform_autosave"]() is False
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert not notices


def test_lock_contention_retries_at_next_service_tick(recovery_service):
    ns, state, notices, path = recovery_service
    ns["_autosave_startup"]()
    state["_autosave_t"] = 0.0
    with ns["recovery_store"].recovery_lock(path):
        ns["_maybe_autosave"]()
    assert state["_autosave_t"] == 0.0
    assert not path.exists()
    ns["_maybe_autosave"]()
    assert path.exists()
    assert notices == ["Autosaved."]


def test_failed_atomic_write_preserves_recovery_and_warns_once(recovery_service):
    ns, state, notices, path = recovery_service
    ns["_autosave_startup"]()
    ns["_write_autosave"] = lambda *args: False
    state["_autosave_t"] = 0.0
    ns["_maybe_autosave"]()
    ns["_maybe_autosave"]()
    assert not path.exists()
    assert state["_autosave_t"] == 0.0
    assert len(notices) == 1 and "Download project" in notices[0]
