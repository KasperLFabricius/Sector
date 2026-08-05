"""Opt-in local measurements for Streamlit application and fragment runs.

The probe is deliberately narrower than engineering telemetry: it records only
run timing, UI construction phases, final navigation labels and aggregate
Streamlit message sizes. With the environment switch disabled, every public
operation is inert.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time


SCHEMA_VERSION = 2
HISTORY_LIMIT = 128
ENABLE_ENV = "SECTOR_PERFORMANCE_TELEMETRY"
OUTPUT_ENV = "SECTOR_PERFORMANCE_TELEMETRY_PATH"
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
FRAGMENT_NAMES = (
    "inputs",
    "save_load",
    "report",
    "quick_section",
    "analysis",
)
PHASE_NAMES = (
    "startup",
    "pane_construction",
    "normalization",
    "input_assembly",
    "preview",
    "autosave",
)

_SEQUENCE_KEY = "_app_run_probe_sequence"
_ACTIVE_KEY = "_app_run_probe_active"
_HISTORY_KEY = "_app_run_probe_history"
_ERROR_KEY = "_app_run_probe_error"
_STATE_KEYS = (_SEQUENCE_KEY, _ACTIVE_KEY, _HISTORY_KEY, _ERROR_KEY)


def enabled(environ=None) -> bool:
    """Return true only for an explicit local opt-in token."""

    source = os.environ if environ is None else environ
    try:
        value = source.get(ENABLE_ENV, "")
    except Exception:
        return False
    return str(value).strip().casefold() in TRUE_VALUES


def state_keys() -> tuple[str, ...]:
    """Return the private state inventory for absence/persistence guards."""

    return _STATE_KEYS


def _context():
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        return get_script_run_ctx(suppress_warning=True)
    except Exception:
        return None


def _is_fragment_run(context) -> bool:
    try:
        return bool(getattr(context, "fragment_ids_this_run", None))
    except Exception:
        return False


def _fragment_ids(context) -> tuple[str, ...]:
    try:
        return tuple(str(value) for value in context.fragment_ids_this_run or ())
    except Exception:
        return ()


def _executing_fragment_id() -> str | None:
    try:
        from streamlit.runtime.scriptrunner_utils.script_run_context import (
            ThreadState,
        )

        value = ThreadState.get().fragment_id
        return str(value) if value else None
    except Exception:
        return None


def _run_token(context):
    """Return the object replaced by ScriptRunContext.reset for every run."""

    try:
        token = context.parallel_coordinator
    except Exception:
        token = None
    if token is not None:
        return token
    try:
        return context.fragment_ids_this_run
    except Exception:
        return None


def _labels(state) -> dict[str, str]:
    labels = {}
    for name, key in (
        ("workspace", "_main_page"),
        ("input_stage", "_input_tab"),
        ("material_family", "_material_tab"),
    ):
        try:
            labels[name] = str(state.get(key) or "")
        except Exception:
            labels[name] = ""
    return labels


def _install_counter(context, state) -> bool:
    """Wrap the queue before the first top-level Streamlit message is sent."""

    try:
        original = context._enqueue
    except Exception:
        return False
    if getattr(original, "_sector_app_run_probe", False):
        return True

    def measured_enqueue(message):
        result = original(message)
        try:
            active = state.get(_ACTIVE_KEY)
            if active is not None:
                size = int(message.ByteSize())
                active["forward_message_count"] += 1
                active["forward_message_bytes"] += size
                active["largest_forward_message_bytes"] = max(
                    active["largest_forward_message_bytes"], size
                )
        except Exception:
            try:
                active = state.get(_ACTIVE_KEY)
                if active is not None:
                    active["byte_accounting"] = False
            except Exception:
                pass
        return result

    measured_enqueue._sector_app_run_probe = True
    measured_enqueue._sector_app_run_probe_original = original
    try:
        context._enqueue = measured_enqueue
    except Exception:
        return False
    return True


def _append_record(state, record) -> None:
    raw_path = str(os.environ.get(OUTPUT_ENV, "")).strip()
    if not raw_path:
        return
    try:
        path = Path(raw_path).expanduser()
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")))
            stream.write("\n")
        state.pop(_ERROR_KEY, None)
    except Exception as exc:
        try:
            state[_ERROR_KEY] = f"{type(exc).__name__}: {exc}"
        except Exception:
            pass


def _seal(state, *, interrupted: bool, now_ns: int):
    active = state.pop(_ACTIVE_KEY, None)
    if active is None:
        return None
    active.update(_labels(state))
    started_ns = int(active.pop("_started_ns"))
    active.pop("_run_token", None)
    active["duration_ms"] = max(0.0, (now_ns - started_ns) / 1_000_000.0)
    active["interrupted"] = bool(interrupted)
    history = list(state.get(_HISTORY_KEY, ()))
    history.append(copy.deepcopy(active))
    state[_HISTORY_KEY] = history[-HISTORY_LIMIT:]
    _append_record(state, active)
    return active


def _start_record(
    state,
    *,
    context,
    kind: str,
    now_ns: int,
    started_utc,
    fragment_name: str = "",
    fragment_id: str = "",
):
    sequence = int(state.get(_SEQUENCE_KEY, 0)) + 1
    state[_SEQUENCE_KEY] = sequence
    active = {
        "schema_version": SCHEMA_VERSION,
        "run_number": sequence,
        "kind": kind,
        "started_utc": started_utc or datetime.now(timezone.utc).isoformat(),
        "interrupted": False,
        "phases": {},
        "forward_message_count": 0,
        "forward_message_bytes": 0,
        "largest_forward_message_bytes": 0,
        "byte_accounting": False,
        "_started_ns": now_ns,
        "_run_token": _run_token(context),
        **_labels(state),
    }
    if kind == "fragment":
        active["fragment_name"] = fragment_name
        active["fragment_id"] = fragment_id
    state[_ACTIVE_KEY] = active
    active["byte_accounting"] = _install_counter(context, state)
    return sequence


def open_run(state, *, context=None, now_ns=None, started_utc=None):
    """Open one full-app envelope before any top-level Streamlit output."""

    if not enabled():
        return None
    try:
        context = _context() if context is None else context
        if context is None or _is_fragment_run(context):
            return None
        now_ns = time.perf_counter_ns() if now_ns is None else int(now_ns)
        if state.get(_ACTIVE_KEY) is not None:
            _seal(state, interrupted=True, now_ns=now_ns)
        return _start_record(
            state,
            context=context,
            kind="app",
            now_ns=now_ns,
            started_utc=started_utc,
        )
    except Exception:
        return None


def close_run(state, *, context=None, now_ns=None):
    """Seal the active full-app envelope without affecting application flow."""

    if not enabled():
        return None
    try:
        context = _context() if context is None else context
        if context is None or _is_fragment_run(context):
            return None
        now_ns = time.perf_counter_ns() if now_ns is None else int(now_ns)
        return _seal(state, interrupted=False, now_ns=now_ns)
    except Exception:
        return None


def open_fragment_run(
    state,
    fragment_name: str,
    *,
    context=None,
    fragment_id=None,
    now_ns=None,
    started_utc=None,
):
    """Open only the root fragment currently dispatched by Streamlit.

    A queued parent can execute nested fragment bodies while the same queue also
    contains those descendants. The active record's ScriptRunContext reset token
    distinguishes that same-run nesting from a later queued root dispatch.
    """

    if fragment_name not in FRAGMENT_NAMES:
        raise ValueError(f"Unknown fragment owner: {fragment_name}")
    if not enabled():
        return None
    try:
        context = _context() if context is None else context
        targets = _fragment_ids(context)
        executing = (
            _executing_fragment_id()
            if fragment_id is None
            else str(fragment_id)
        )
        if (
            context is None
            or not targets
            or not executing
            or executing not in targets
        ):
            return None
        now_ns = time.perf_counter_ns() if now_ns is None else int(now_ns)
        token = _run_token(context)
        active = state.get(_ACTIVE_KEY)
        if active is not None:
            if active.get("_run_token") is token:
                if (
                    active.get("kind") == "fragment"
                    and active.get("fragment_id") == executing
                ):
                    return active.get("run_number")
                return None
            _seal(state, interrupted=True, now_ns=now_ns)
        return _start_record(
            state,
            context=context,
            kind="fragment",
            fragment_name=str(fragment_name),
            fragment_id=executing,
            now_ns=now_ns,
            started_utc=started_utc,
        )
    except Exception:
        return None


def close_fragment_run(
    state, *, context=None, fragment_id=None, now_ns=None
):
    """Seal only the root fragment that owns the active run record."""

    if not enabled():
        return None
    try:
        context = _context() if context is None else context
        targets = _fragment_ids(context)
        executing = (
            _executing_fragment_id()
            if fragment_id is None
            else str(fragment_id)
        )
        active = state.get(_ACTIVE_KEY)
        if (
            context is None
            or not targets
            or not executing
            or executing not in targets
            or active is None
            or active.get("kind") != "fragment"
            or active.get("fragment_id") != executing
            or active.get("_run_token") is not _run_token(context)
        ):
            return None
        now_ns = time.perf_counter_ns() if now_ns is None else int(now_ns)
        return _seal(state, interrupted=False, now_ns=now_ns)
    except Exception:
        return None


def start_phase(state, name: str, *, now_ns=None):
    """Start one frozen UI-construction phase on the active run."""

    if name not in PHASE_NAMES:
        raise ValueError(f"Unknown run phase: {name}")
    if not enabled():
        return None
    try:
        active = state.get(_ACTIVE_KEY)
        if active is None:
            return None
        return {
            "run_number": active["run_number"],
            "name": name,
            "started_ns": (
                time.perf_counter_ns() if now_ns is None else int(now_ns)
            ),
        }
    except Exception:
        return None


def stop_phase(state, token, *, now_ns=None):
    """Accumulate a completed phase without retaining phase inputs."""

    if token is None or not enabled():
        return None
    try:
        name = token.get("name")
        if name not in PHASE_NAMES:
            return None
        active = state.get(_ACTIVE_KEY)
        if active is None or active.get("run_number") != token.get("run_number"):
            return None
        now_ns = time.perf_counter_ns() if now_ns is None else int(now_ns)
        elapsed_ms = max(
            0.0, (now_ns - int(token["started_ns"])) / 1_000_000.0
        )
        phase = active["phases"].setdefault(
            name,
            {"count": 0, "total_ms": 0.0, "max_ms": 0.0, "last_ms": 0.0},
        )
        phase["count"] += 1
        phase["total_ms"] += elapsed_ms
        phase["max_ms"] = max(phase["max_ms"], elapsed_ms)
        phase["last_ms"] = elapsed_ms
        return elapsed_ms
    except Exception:
        return None


def snapshot(state) -> dict:
    """Return a detached snapshot for local tests and developer tooling."""

    if not enabled():
        return {
            "schema_version": SCHEMA_VERSION,
            "enabled": False,
            "history": [],
            "active": None,
            "error": None,
        }
    try:
        active = copy.deepcopy(state.get(_ACTIVE_KEY))
        if active is not None:
            active.pop("_started_ns", None)
            active.pop("_run_token", None)
        return {
            "schema_version": SCHEMA_VERSION,
            "enabled": True,
            "history": copy.deepcopy(list(state.get(_HISTORY_KEY, ()))),
            "active": active,
            "error": state.get(_ERROR_KEY),
        }
    except Exception:
        return {
            "schema_version": SCHEMA_VERSION,
            "enabled": True,
            "history": [],
            "active": None,
            "error": "state unavailable",
        }
