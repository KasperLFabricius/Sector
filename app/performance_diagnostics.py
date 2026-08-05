"""Local opt-in Streamlit performance diagnostics.

The ordinary application does no work here beyond a cheap environment check.
When explicitly enabled, the collector retains bounded timing and Streamlit
forward-message size metadata. It never inspects message contents or engineering
inputs and never transmits a record.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
import os
import pathlib
import time


SCHEMA_VERSION = 1
RUN_LIMIT = 128
ENABLED_ENV = "SECTOR_PERFORMANCE_TELEMETRY"
OUTPUT_ENV = "SECTOR_PERFORMANCE_TELEMETRY_PATH"
TRUE_TOKENS = frozenset({"1", "true", "yes", "on"})
PHASES = (
    "startup",
    "pane_construction",
    "normalization",
    "input_assembly",
    "preview",
    "autosave",
)

_COUNTER_KEY = "_performance_diagnostic_counter"
_CURRENT_KEY = "_performance_diagnostic_current"
_RUNS_KEY = "_performance_diagnostic_runs"
_ERROR_KEY = "_performance_diagnostic_error"
_STATE_KEYS = (_COUNTER_KEY, _CURRENT_KEY, _RUNS_KEY, _ERROR_KEY)


def enabled(environ=None) -> bool:
    """Return whether the explicit local diagnostic switch is enabled."""

    source = os.environ if environ is None else environ
    return str(source.get(ENABLED_ENV, "")).strip().casefold() in TRUE_TOKENS


def state_keys() -> tuple[str, ...]:
    """Return the private state-key inventory for absence/persistence guards."""

    return _STATE_KEYS


def _script_context():
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        return get_script_run_ctx(suppress_warning=True)
    except (ImportError, RuntimeError):
        return None


def _fragment_ids(context) -> tuple[str, ...]:
    values = getattr(context, "fragment_ids_this_run", None) or ()
    return tuple(str(value) for value in values)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_labels(state) -> dict[str, str]:
    return {
        "workspace": str(state.get("_main_page") or ""),
        "input_stage": str(state.get("_input_tab") or ""),
        "material_family": str(state.get("_material_tab") or ""),
    }


def _install_forward_counter(context, state) -> bool:
    """Wrap one session queue without changing any forwarded message."""

    if context is None or not hasattr(context, "_enqueue"):
        return False
    current_enqueue = context._enqueue
    if getattr(current_enqueue, "_sector_performance_wrapper", False):
        return True

    def counted_enqueue(message):
        try:
            current = state.get(_CURRENT_KEY)
            if current is not None:
                size = int(message.ByteSize())
                current["forward_message_count"] += 1
                current["forward_message_bytes"] += size
                current["largest_forward_message_bytes"] = max(
                    current["largest_forward_message_bytes"], size
                )
        except Exception:
            # Diagnostic byte accounting is never allowed to suppress or alter
            # a Streamlit message if protobuf internals change unexpectedly.
            try:
                current = state.get(_CURRENT_KEY)
                if current is not None:
                    current["byte_accounting"] = False
            except Exception:
                pass
        return current_enqueue(message)

    counted_enqueue._sector_performance_wrapper = True
    counted_enqueue._sector_performance_original = current_enqueue
    try:
        context._enqueue = counted_enqueue
    except Exception:
        return False
    return True


def begin_run(state, *, context=None, now_ns=None, started_utc=None):
    """Begin one app or fragment run, closing a superseded run if necessary."""

    if not enabled():
        return None
    context = _script_context() if context is None else context
    now_ns = time.perf_counter_ns() if now_ns is None else int(now_ns)
    if state.get(_CURRENT_KEY) is not None:
        finish_run(state, interrupted=True, now_ns=now_ns)

    number = int(state.get(_COUNTER_KEY, 0)) + 1
    state[_COUNTER_KEY] = number
    fragments = _fragment_ids(context)
    current = {
        "schema_version": SCHEMA_VERSION,
        "run_number": number,
        "kind": "fragment" if fragments else "app",
        "fragment_ids": list(fragments),
        "started_utc": started_utc or _utc_now(),
        "_started_ns": now_ns,
        "interrupted": False,
        "phases": {},
        "forward_message_count": 0,
        "forward_message_bytes": 0,
        "largest_forward_message_bytes": 0,
        "byte_accounting": False,
        **_run_labels(state),
    }
    state[_CURRENT_KEY] = current
    current["byte_accounting"] = _install_forward_counter(context, state)
    return number


def begin_fragment_run(state, *, context=None, now_ns=None, started_utc=None):
    """Begin only when Streamlit is executing a fragment-scoped rerun."""

    if not enabled():
        return None
    context = _script_context() if context is None else context
    if not _fragment_ids(context):
        current = state.get(_CURRENT_KEY)
        return current.get("run_number") if current else None
    return begin_run(
        state,
        context=context,
        now_ns=now_ns,
        started_utc=started_utc,
    )


def begin_phase(state, name: str, *, now_ns=None):
    """Return an opaque phase token, or None while diagnostics are disabled."""

    if name not in PHASES:
        raise ValueError(f"Unknown performance phase: {name}")
    if not enabled():
        return None
    current = state.get(_CURRENT_KEY)
    if current is None:
        return None
    return {
        "run_number": current["run_number"],
        "name": name,
        "started_ns": (
            time.perf_counter_ns() if now_ns is None else int(now_ns)
        ),
    }


def end_phase(state, token, *, now_ns=None):
    """Accumulate one completed phase without recording its input values."""

    if token is None:
        return None
    current = state.get(_CURRENT_KEY)
    if current is None or current.get("run_number") != token.get("run_number"):
        return None
    now_ns = time.perf_counter_ns() if now_ns is None else int(now_ns)
    duration_ms = max(0.0, (now_ns - int(token["started_ns"])) / 1_000_000.0)
    summary = current["phases"].setdefault(
        token["name"],
        {"count": 0, "total_ms": 0.0, "max_ms": 0.0, "last_ms": 0.0},
    )
    summary["count"] += 1
    summary["total_ms"] += duration_ms
    summary["max_ms"] = max(summary["max_ms"], duration_ms)
    summary["last_ms"] = duration_ms
    return duration_ms


def _write_json_line(state, record) -> None:
    raw_path = str(os.environ.get(OUTPUT_ENV, "")).strip()
    if not raw_path:
        return
    path = pathlib.Path(raw_path).expanduser()
    try:
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")))
            stream.write("\n")
        state.pop(_ERROR_KEY, None)
    except Exception as exc:
        state[_ERROR_KEY] = f"{type(exc).__name__}: {exc}"


def finish_run(state, *, interrupted=False, now_ns=None):
    """Finalize, bound, and optionally write the current diagnostic run."""

    if not enabled():
        return None
    current = state.pop(_CURRENT_KEY, None)
    if current is None:
        return None
    # Labels are initialized at run start for live snapshots, then sealed from
    # the state that actually produced the completed render. Cold-start defaults
    # and queued navigation changes are applied between those two boundaries.
    current.update(_run_labels(state))
    now_ns = time.perf_counter_ns() if now_ns is None else int(now_ns)
    started_ns = int(current.pop("_started_ns"))
    current["duration_ms"] = max(0.0, (now_ns - started_ns) / 1_000_000.0)
    current["interrupted"] = bool(interrupted)

    runs = list(state.get(_RUNS_KEY, ()))
    runs.append(copy.deepcopy(current))
    state[_RUNS_KEY] = runs[-RUN_LIMIT:]
    _write_json_line(state, current)
    return current


def finish_fragment_run(state, *, context=None, now_ns=None):
    """Finalize only a genuine fragment-scoped rerun."""

    if not enabled():
        return None
    context = _script_context() if context is None else context
    if not _fragment_ids(context):
        return None
    return finish_run(state, now_ns=now_ns)


def finish_app_run(state, *, context=None, now_ns=None):
    """Finalize only a full application run."""

    if not enabled():
        return None
    context = _script_context() if context is None else context
    if _fragment_ids(context):
        return None
    return finish_run(state, now_ns=now_ns)


def snapshot(state) -> dict:
    """Return a detached diagnostic snapshot for tests or local tooling."""

    runs = copy.deepcopy(list(state.get(_RUNS_KEY, ()))) if enabled() else []
    current = copy.deepcopy(state.get(_CURRENT_KEY)) if enabled() else None
    if current is not None:
        current.pop("_started_ns", None)
    return {
        "schema_version": SCHEMA_VERSION,
        "enabled": enabled(),
        "runs": runs,
        "current": current,
        "error": state.get(_ERROR_KEY) if enabled() else None,
    }
