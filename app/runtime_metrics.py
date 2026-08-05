"""Opt-in local runtime measurements for the Streamlit application.

The normal application pays only for an environment-variable check. When an
engineer explicitly enables measurements, Sector retains a bounded history of
run timings and Streamlit forward-message sizes. Engineering inputs, results,
message contents, and user identity are never inspected or recorded.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time


SCHEMA_VERSION = 1
RUN_LIMIT = 128
ENABLE_ENV = "SECTOR_PERFORMANCE_TELEMETRY"
OUTPUT_ENV = "SECTOR_PERFORMANCE_TELEMETRY_PATH"
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
PHASE_NAMES = (
    "startup",
    "pane_construction",
    "normalization",
    "input_assembly",
    "preview",
    "autosave",
)

_SEQUENCE_KEY = "_runtime_metrics_sequence"
_ACTIVE_KEY = "_runtime_metrics_active"
_HISTORY_KEY = "_runtime_metrics_history"
_ERROR_KEY = "_runtime_metrics_error"
_PRIVATE_KEYS = (_SEQUENCE_KEY, _ACTIVE_KEY, _HISTORY_KEY, _ERROR_KEY)


def is_enabled(environ=None) -> bool:
    """Return whether local runtime measurements were explicitly enabled."""

    source = os.environ if environ is None else environ
    return str(source.get(ENABLE_ENV, "")).strip().casefold() in TRUE_VALUES


def state_keys() -> tuple[str, ...]:
    """Expose the private key inventory for persistence and absence guards."""

    return _PRIVATE_KEYS


def _script_context():
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        return get_script_run_ctx(suppress_warning=True)
    except Exception:
        return None


def _target_fragment_ids(context) -> tuple[str, ...]:
    values = getattr(context, "fragment_ids_this_run", None) or ()
    return tuple(str(value) for value in values)


def _executing_fragment_id() -> str | None:
    try:
        from streamlit.runtime.scriptrunner_utils.script_run_context import (
            ThreadState,
        )

        value = ThreadState.get().fragment_id
        return str(value) if value else None
    except Exception:
        return None


def _labels(state) -> dict[str, str]:
    return {
        "workspace": str(state.get("_main_page") or ""),
        "input_stage": str(state.get("_input_tab") or ""),
        "material_family": str(state.get("_material_tab") or ""),
    }


def _install_message_counter(context, state) -> bool:
    """Count protobuf bytes while forwarding every message unchanged."""

    if context is None or not hasattr(context, "_enqueue"):
        return False
    original = context._enqueue
    if getattr(original, "_sector_runtime_metrics_wrapper", False):
        return True

    def measured_enqueue(message):
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
        return original(message)

    measured_enqueue._sector_runtime_metrics_wrapper = True
    measured_enqueue._sector_runtime_metrics_original = original
    try:
        context._enqueue = measured_enqueue
    except Exception:
        return False
    return True


def _new_run(
    state,
    *,
    kind: str,
    context,
    fragment_name: str = "",
    fragment_id: str = "",
    now_ns=None,
    started_utc=None,
):
    now_ns = time.perf_counter_ns() if now_ns is None else int(now_ns)
    if state.get(_ACTIVE_KEY) is not None:
        close_run(state, interrupted=True, now_ns=now_ns)

    sequence = int(state.get(_SEQUENCE_KEY, 0)) + 1
    state[_SEQUENCE_KEY] = sequence
    active = {
        "schema_version": SCHEMA_VERSION,
        "run_number": sequence,
        "kind": kind,
        "fragment_name": fragment_name,
        "fragment_id": fragment_id,
        "started_utc": started_utc or datetime.now(timezone.utc).isoformat(),
        "interrupted": False,
        "phases": {},
        "forward_message_count": 0,
        "forward_message_bytes": 0,
        "largest_forward_message_bytes": 0,
        "byte_accounting": False,
        "_started_ns": now_ns,
        **_labels(state),
    }
    state[_ACTIVE_KEY] = active
    active["byte_accounting"] = _install_message_counter(context, state)
    return sequence


def open_app_run(state, *, context=None, now_ns=None, started_utc=None):
    """Open a full-application run, never a fragment-scoped rerun."""

    if not is_enabled():
        return None
    context = _script_context() if context is None else context
    if _target_fragment_ids(context):
        return None
    return _new_run(
        state,
        kind="app",
        context=context,
        now_ns=now_ns,
        started_utc=started_utc,
    )


def open_fragment_run(
    state,
    fragment_name: str,
    *,
    context=None,
    fragment_id=None,
    now_ns=None,
    started_utc=None,
):
    """Open only the fragment that owns the current fragment-scoped rerun.

    Nested fragments are executed while their parent is rendered. Comparing the
    executing fragment ID with Streamlit's requested IDs prevents those nested
    calls from splitting or replacing the parent run record.
    """

    if not is_enabled():
        return None
    context = _script_context() if context is None else context
    targets = _target_fragment_ids(context)
    executing = (
        _executing_fragment_id() if fragment_id is None else str(fragment_id)
    )
    if not executing or executing not in targets:
        return None
    active = state.get(_ACTIVE_KEY)
    if (
        active is not None
        and active.get("kind") == "fragment"
        and active.get("fragment_id") == executing
    ):
        return active.get("run_number")
    return _new_run(
        state,
        kind="fragment",
        context=context,
        fragment_name=str(fragment_name),
        fragment_id=executing,
        now_ns=now_ns,
        started_utc=started_utc,
    )


def start_phase(state, name: str, *, now_ns=None):
    """Start one advertised timing phase and return an opaque token."""

    if name not in PHASE_NAMES:
        raise ValueError(f"Unknown runtime phase: {name}")
    if not is_enabled():
        return None
    active = state.get(_ACTIVE_KEY)
    if active is None:
        return None
    return {
        "run_number": active["run_number"],
        "name": name,
        "started_ns": time.perf_counter_ns() if now_ns is None else int(now_ns),
    }


def stop_phase(state, token, *, now_ns=None):
    """Accumulate one completed phase without retaining phase inputs."""

    if token is None:
        return None
    active = state.get(_ACTIVE_KEY)
    if active is None or active.get("run_number") != token.get("run_number"):
        return None
    now_ns = time.perf_counter_ns() if now_ns is None else int(now_ns)
    elapsed_ms = max(
        0.0, (now_ns - int(token["started_ns"])) / 1_000_000.0
    )
    phase = active["phases"].setdefault(
        token["name"],
        {"count": 0, "total_ms": 0.0, "max_ms": 0.0, "last_ms": 0.0},
    )
    phase["count"] += 1
    phase["total_ms"] += elapsed_ms
    phase["max_ms"] = max(phase["max_ms"], elapsed_ms)
    phase["last_ms"] = elapsed_ms
    return elapsed_ms


def _append_json_line(state, record) -> None:
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
        state[_ERROR_KEY] = f"{type(exc).__name__}: {exc}"


def close_run(state, *, interrupted=False, now_ns=None):
    """Seal, bound, and optionally publish the active local run record."""

    if not is_enabled():
        return None
    active = state.pop(_ACTIVE_KEY, None)
    if active is None:
        return None
    active.update(_labels(state))
    now_ns = time.perf_counter_ns() if now_ns is None else int(now_ns)
    started_ns = int(active.pop("_started_ns"))
    active["duration_ms"] = max(
        0.0, (now_ns - started_ns) / 1_000_000.0
    )
    active["interrupted"] = bool(interrupted)
    history = list(state.get(_HISTORY_KEY, ()))
    history.append(copy.deepcopy(active))
    state[_HISTORY_KEY] = history[-RUN_LIMIT:]
    _append_json_line(state, active)
    return active


def close_app_run(state, *, context=None, now_ns=None):
    """Close only a full-application run."""

    if not is_enabled():
        return None
    context = _script_context() if context is None else context
    if _target_fragment_ids(context):
        return None
    active = state.get(_ACTIVE_KEY)
    if active is None or active.get("kind") != "app":
        return None
    return close_run(state, now_ns=now_ns)


def close_fragment_run(
    state, *, context=None, fragment_id=None, now_ns=None
):
    """Close only the fragment that owns the current scoped rerun."""

    if not is_enabled():
        return None
    context = _script_context() if context is None else context
    targets = _target_fragment_ids(context)
    executing = (
        _executing_fragment_id() if fragment_id is None else str(fragment_id)
    )
    active = state.get(_ACTIVE_KEY)
    if (
        not executing
        or executing not in targets
        or active is None
        or active.get("kind") != "fragment"
        or active.get("fragment_id") != executing
    ):
        return None
    return close_run(state, now_ns=now_ns)


def snapshot(state) -> dict:
    """Return a detached local snapshot for tests and developer tooling."""

    if not is_enabled():
        return {
            "schema_version": SCHEMA_VERSION,
            "enabled": False,
            "history": [],
            "active": None,
            "error": None,
        }
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
