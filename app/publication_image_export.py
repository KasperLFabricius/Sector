"""Process-wide lifecycle for serialized Plotly/Kaleido PNG exports.

Kaleido's synchronous server is process-global.  Every report and manual export
therefore shares this coordinator: server startup and individual image renders
run one at a time, and an indeterminate server is never reused after an error or
timeout.  Recovery belongs at a process boundary; this module deliberately does
not try to kill or restart a browser from a timed-out Python thread.
"""

from __future__ import annotations

import atexit
import os
import threading
from collections.abc import Callable
from enum import Enum
from typing import Any

_KALEIDO_RENDER_TIMEOUT_S = 90.0


class KaleidoExportState(Enum):
    """One-way lifecycle for the process-wide image exporter."""

    NOT_STARTED = "not-started"
    READY = "ready"
    POISONED = "poisoned"


class KaleidoExportError(RuntimeError):
    """The requested image could not be exported safely."""


class KaleidoExportTimeout(KaleidoExportError):
    """Kaleido did not finish inside the caller's bounded wait."""


class KaleidoExporterPoisoned(KaleidoExportError):
    """A previous indeterminate operation made reuse unsafe."""


StopServer = Callable[[], None]
StartServer = Callable[[], StopServer | None]
ThreadFactory = Callable[..., threading.Thread]


def _kaleido_server_api() -> tuple[Callable[..., Any] | None, Callable[..., Any] | None]:
    """Return Kaleido's synchronous process-server API when available."""

    try:
        import kaleido
    except Exception:
        return None, None
    return (
        getattr(kaleido, "start_sync_server", None),
        getattr(kaleido, "stop_sync_server", None),
    )


def _kaleido_page_path() -> str | None:
    """Create one persistent Plotly launcher page outside Kaleido's temp tree."""

    try:
        import kaleido

        generator = kaleido.PageGenerator(mathjax=False)
        document = generator.generate_index()
        configured = (
            os.environ.get("SECTOR_KALEIDO_DIR")
            or os.environ.get("SECTOR_AUTOSAVE_DIR")
        )
        if configured:
            folder = os.path.abspath(configured)
        else:
            local = os.environ.get("LOCALAPPDATA")
            folder = (
                os.path.join(local, "Sector", "kaleido")
                if local
                else os.path.join(os.path.expanduser("~"), ".sector", "kaleido")
            )
        os.makedirs(folder, exist_ok=True)
        page = os.path.join(folder, "plotly_export.html")
        existing = None
        try:
            with open(page, "r", encoding="utf-8") as handle:
                existing = handle.read()
        except OSError:
            pass
        if existing != document:
            with open(page, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(document)
        return page
    except Exception:
        return None


def _safe_stop(stop: Callable[..., Any]) -> None:
    try:
        stop(silence_warnings=True)
    except Exception:
        pass


def _start_kaleido_server() -> StopServer | None:
    start, stop = _kaleido_server_api()
    if start is None:
        raise RuntimeError("Kaleido's synchronous image server is unavailable")
    page = _kaleido_page_path()
    options: dict[str, Any] = {
        "silence_warnings": True,
        "timeout": _KALEIDO_RENDER_TIMEOUT_S,
    }
    if page:
        options["page_generator"] = page
    start(**options)
    if stop is None:
        return None
    return lambda: _safe_stop(stop)


class KaleidoExportCoordinator:
    """Serialize one process-wide Kaleido server and poison unsafe state."""

    def __init__(
        self,
        starter: StartServer,
        *,
        thread_factory: ThreadFactory = threading.Thread,
        register_exit: Callable[[StopServer], Any] = atexit.register,
    ) -> None:
        self._starter = starter
        self._thread_factory = thread_factory
        self._register_exit = register_exit
        self._lock = threading.Lock()
        self._state = KaleidoExportState.NOT_STARTED
        self._poison_reason: str | None = None

    @property
    def state(self) -> KaleidoExportState:
        """Return a non-blocking lifecycle snapshot for diagnostics."""

        return self._state

    @property
    def poison_reason(self) -> str | None:
        """Return the first terminal failure, if any."""

        return self._poison_reason

    def _poison(self, reason: str) -> None:
        if self._state is not KaleidoExportState.POISONED:
            self._poison_reason = reason
        self._state = KaleidoExportState.POISONED

    def _raise_if_poisoned(self) -> None:
        if self._state is KaleidoExportState.POISONED:
            detail = self._poison_reason or "unknown prior failure"
            raise KaleidoExporterPoisoned(
                f"Kaleido image exporter is poisoned: {detail}"
            )

    def _run_locked(
        self,
        operation: Callable[[], Any],
        *,
        timeout: float,
        phase: str,
    ) -> Any:
        if timeout <= 0:
            raise ValueError("Kaleido operation timeout must be positive")
        box: dict[str, Any] = {}

        def work() -> None:
            try:
                box["value"] = operation()
            except BaseException as exc:  # preserve the worker failure for the caller
                box["error"] = exc

        try:
            worker = self._thread_factory(
                target=work,
                daemon=True,
                name=f"sector-kaleido-{phase}",
            )
            worker.start()
            worker.join(timeout)
        except BaseException as exc:
            reason = f"{phase} worker failed: {type(exc).__name__}: {exc}"
            self._poison(reason)
            raise KaleidoExportError(reason) from exc
        if worker.is_alive():
            reason = f"{phase} timed out after {timeout:g} seconds"
            self._poison(reason)
            raise KaleidoExportTimeout(reason)
        error = box.get("error")
        if error is not None:
            reason = f"{phase} failed: {type(error).__name__}: {error}"
            self._poison(reason)
            raise KaleidoExportError(reason) from error
        return box.get("value")

    def _ensure_ready_locked(self, timeout: float) -> None:
        self._raise_if_poisoned()
        if self._state is KaleidoExportState.READY:
            return
        stop = self._run_locked(
            self._starter,
            timeout=timeout,
            phase="startup",
        )
        if stop is not None:
            try:
                self._register_exit(stop)
            except BaseException as exc:
                reason = (
                    "startup cleanup registration failed: "
                    f"{type(exc).__name__}: {exc}"
                )
                self._poison(reason)
                raise KaleidoExportError(reason) from exc
        self._state = KaleidoExportState.READY

    def ensure_ready(self, *, timeout: float) -> None:
        """Start the process server once, serialized with every export."""

        with self._lock:
            self._ensure_ready_locked(timeout)

    def export_png(
        self,
        render: Callable[[], bytes],
        *,
        timeout: float,
        description: str,
    ) -> bytes:
        """Return one non-empty PNG payload or poison the coordinator."""

        with self._lock:
            self._ensure_ready_locked(timeout)
            result = self._run_locked(
                render,
                timeout=timeout,
                phase=description,
            )
            if not isinstance(result, bytes) or not result:
                reason = f"{description} returned no PNG bytes"
                self._poison(reason)
                raise KaleidoExportError(reason)
            return result


_COORDINATOR = KaleidoExportCoordinator(_start_kaleido_server)


def ensure_ready(*, timeout: float) -> None:
    """Ensure the shared exporter is ready without starting duplicate work."""

    _COORDINATOR.ensure_ready(timeout=timeout)


def export_png(
    render: Callable[[], bytes],
    *,
    timeout: float,
    description: str,
) -> bytes:
    """Run one PNG export through the shared serialized coordinator."""

    return _COORDINATOR.export_png(
        render,
        timeout=timeout,
        description=description,
    )
