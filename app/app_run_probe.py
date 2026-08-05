"""Opt-in local measurements for complete Streamlit application runs.

The probe is deliberately narrower than engineering telemetry: it records only
run timing, final navigation labels and aggregate Streamlit message sizes. With
the environment switch disabled, every public operation is inert.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time


SCHEMA_VERSION = 1
HISTORY_LIMIT = 128
ENABLE_ENV = "SECTOR_PERFORMANCE_TELEMETRY"
OUTPUT_ENV = "SECTOR_PERFORMANCE_TELEMETRY_PATH"
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})

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
    active["duration_ms"] = max(0.0, (now_ns - started_ns) / 1_000_000.0)
    active["interrupted"] = bool(interrupted)
    history = list(state.get(_HISTORY_KEY, ()))
    history.append(copy.deepcopy(active))
    state[_HISTORY_KEY] = history[-HISTORY_LIMIT:]
    _append_record(state, active)
    return active


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
        sequence = int(state.get(_SEQUENCE_KEY, 0)) + 1
        state[_SEQUENCE_KEY] = sequence
        state[_ACTIVE_KEY] = {
            "schema_version": SCHEMA_VERSION,
            "run_number": sequence,
            "kind": "app",
            "started_utc": (
                started_utc or datetime.now(timezone.utc).isoformat()
            ),
            "interrupted": False,
            "forward_message_count": 0,
            "forward_message_bytes": 0,
            "largest_forward_message_bytes": 0,
            "byte_accounting": False,
            "_started_ns": now_ns,
            **_labels(state),
        }
        state[_ACTIVE_KEY]["byte_accounting"] = _install_counter(
            context, state
        )
        return sequence
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
