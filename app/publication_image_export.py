"""Recoverable process boundary for serialized Plotly/Kaleido PNG exports.

Kaleido's synchronous server owns a browser and can block below Python's thread
boundary. Publication exports therefore run in one spawned child process. A
real warm-up render is the READY handshake, and a timeout terminates the worker
and its descendant process tree before a later request may start a clean one.
"""

from __future__ import annotations

import atexit
import ctypes
import json
import math
import multiprocessing
import os
import signal
import threading
import time
from collections.abc import Callable
from enum import Enum
from typing import Any

_KALEIDO_RENDER_TIMEOUT_S = 90.0
_WORKER_SHUTDOWN_GRACE_S = 1.0
_POLL_INTERVAL_S = 0.05
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_POSIX_SIGTERM = getattr(signal, "SIGTERM", 15)
_POSIX_SIGKILL = getattr(signal, "SIGKILL", 9)
_WARMUP_FIGURE = {
    "data": [{"type": "scatter", "x": [0.0], "y": [0.0], "mode": "markers"}],
    "layout": {"width": 32, "height": 32},
}
_WARMUP_OPTIONS = {"format": "png", "width": 32, "height": 32, "scale": 1}


class KaleidoExportState(Enum):
    """Observable lifecycle of the process-owned exporter."""

    NOT_STARTED = "not-started"
    STARTING = "starting"
    READY = "ready"


class KaleidoExportError(RuntimeError):
    """The requested image could not be exported safely."""


class KaleidoExportTimeout(KaleidoExportError):
    """Kaleido did not finish inside the caller's bounded wait."""


PageFactory = Callable[[], str | None]
WorkerTarget = Callable[[Any, PageFactory], None]


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


def _windows_kill_on_close_job() -> int:
    """Put this worker in a job whose closure kills every descendant."""

    from ctypes import wintypes

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimitInformation),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = (
        wintypes.HANDLE,
        wintypes.HANDLE,
    )
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    information = _ExtendedLimitInformation()
    information.BasicLimitInformation.LimitFlags = 0x00002000
    if not kernel32.SetInformationJobObject(
        handle,
        9,
        ctypes.byref(information),
        ctypes.sizeof(information),
    ):
        error = ctypes.get_last_error()
        kernel32.CloseHandle(handle)
        raise ctypes.WinError(error)
    if not kernel32.AssignProcessToJobObject(handle, kernel32.GetCurrentProcess()):
        error = ctypes.get_last_error()
        kernel32.CloseHandle(handle)
        raise ctypes.WinError(error)
    # Retain the sole handle for the worker's lifetime. Windows closes it when
    # the worker is terminated, which kills every Chrome descendant.
    return int(handle)


def _own_descendant_processes() -> int | None:
    """Create the OS boundary used by the parent for whole-tree termination."""

    if os.name == "nt":
        return _windows_kill_on_close_job()
    os.setsid()
    return None


def _valid_png(payload: object) -> bool:
    return isinstance(payload, bytes) and payload.startswith(_PNG_SIGNATURE)


def _posix_group_owned_browser_class() -> type[Any]:
    """Keep Choreographer's browser inside the worker-owned process group."""

    from choreographer.browsers.chromium import Chromium

    class _GroupOwnedChromium(Chromium):
        def get_popen_args(self) -> dict[str, Any]:
            arguments = dict(super().get_popen_args())
            arguments["start_new_session"] = False
            return arguments

    return _GroupOwnedChromium


def _start_and_warm_kaleido(page_path: str | None) -> None:
    """Start Kaleido and prove browser readiness with one real PNG render."""

    import kaleido

    options: dict[str, Any] = {
        "silence_warnings": True,
        "timeout": _KALEIDO_RENDER_TIMEOUT_S,
    }
    if page_path:
        options["page_generator"] = page_path
    if os.name != "nt":
        options["browser_cls"] = _posix_group_owned_browser_class()
    kaleido.start_sync_server(**options)
    warmup = kaleido.calc_fig_sync(_WARMUP_FIGURE, opts=_WARMUP_OPTIONS)
    if not _valid_png(warmup):
        raise RuntimeError("Kaleido warm-up returned no PNG bytes")


def _render_worker_png(figure_json: str, options: dict[str, Any]) -> bytes:
    """Render one validated JSON figure through the already-warm server."""

    import kaleido

    figure = json.loads(figure_json)
    payload = kaleido.calc_fig_sync(figure, opts=options)
    if not _valid_png(payload):
        raise RuntimeError("Kaleido returned no PNG bytes")
    return payload


def _worker_main(connection: Any, page_factory: PageFactory) -> None:
    """Own Kaleido until the parent stops or terminates this process."""

    tree_guard: int | None = None
    try:
        tree_guard = _own_descendant_processes()
        connection.send(("booted",))
        if connection.recv() != ("proceed",):
            raise RuntimeError("invalid image-export ownership acknowledgement")
        page_path = page_factory()
        _start_and_warm_kaleido(page_path)
        connection.send(("ready",))
        while True:
            message = connection.recv()
            if message == ("stop",):
                return
            if not (
                isinstance(message, tuple)
                and len(message) == 4
                and message[0] == "render"
                and isinstance(message[1], int)
                and isinstance(message[2], str)
                and isinstance(message[3], dict)
            ):
                raise RuntimeError("invalid image-export request")
            _, request_id, figure_json, options = message
            try:
                payload = _render_worker_png(figure_json, options)
            except BaseException as exc:
                connection.send(("error", request_id, type(exc).__name__, str(exc)))
                continue
            connection.send(("result", request_id, payload))
    except BaseException as exc:
        try:
            connection.send(("startup-error", type(exc).__name__, str(exc)))
        except BaseException:
            pass
    finally:
        # Keep the Windows job handle until teardown; closing it here would
        # deliberately terminate this process before the pipe is flushed.
        del tree_guard
        try:
            connection.close()
        except BaseException:
            pass


def _positive_timeout(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError("Kaleido operation timeout must be a positive number")
    try:
        timeout = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Kaleido operation timeout must be a positive number") from exc
    if not math.isfinite(timeout) or timeout <= 0.0:
        raise ValueError("Kaleido operation timeout must be a positive number")
    return timeout


def _positive_scale(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError("Kaleido image scale must be a positive number")
    try:
        scale = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Kaleido image scale must be a positive number") from exc
    if not math.isfinite(scale) or scale <= 0.0:
        raise ValueError("Kaleido image scale must be a positive number")
    return scale


def _optional_dimension(name: str, value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"Kaleido image {name} must be a positive integer")
    return value


def _figure_json(figure: object) -> str:
    try:
        from plotly.io import to_json

        payload = to_json(
            figure,
            validate=True,
            pretty=False,
            remove_uids=False,
            engine="json",
        )
    except Exception as exc:
        raise KaleidoExportError(
            f"figure serialization failed: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(payload, str) or not payload:
        raise KaleidoExportError("figure serialization returned no JSON")
    return payload


class KaleidoExportCoordinator:
    """Serialize requests to one replaceable, process-owned Kaleido server."""

    def __init__(
        self,
        *,
        context: Any | None = None,
        worker_target: WorkerTarget = _worker_main,
        page_factory: PageFactory = _kaleido_page_path,
        register_exit: Callable[[Callable[[], None]], Any] = atexit.register,
    ) -> None:
        self._context = context or multiprocessing.get_context("spawn")
        self._worker_target = worker_target
        self._page_factory = page_factory
        self._lock = threading.Lock()
        self._state = KaleidoExportState.NOT_STARTED
        self._connection: Any | None = None
        self._process: Any | None = None
        self._tree_ready = False
        self._request_id = 0
        register_exit(self.close)

    @property
    def state(self) -> KaleidoExportState:
        """Return a non-blocking lifecycle snapshot for diagnostics."""

        return self._state

    def _process_error(self, phase: str) -> KaleidoExportError:
        exitcode = None if self._process is None else self._process.exitcode
        return KaleidoExportError(
            f"{phase} worker exited before responding (exit code {exitcode})"
        )

    def _receive_locked(
        self,
        deadline: float,
        phase: str,
        *,
        consume_queued_on_timeout: bool = False,
    ) -> tuple[Any, ...]:
        connection = self._connection
        process = self._process
        if connection is None or process is None:
            raise KaleidoExportError(f"{phase} worker is unavailable")
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0.0 and not consume_queued_on_timeout:
                raise KaleidoExportTimeout(f"{phase} timed out")
            try:
                if connection.poll(max(0.0, min(remaining, _POLL_INTERVAL_S))):
                    message = connection.recv()
                    if not isinstance(message, tuple):
                        raise KaleidoExportError(
                            f"{phase} worker returned an invalid response"
                        )
                    return message
            except (EOFError, OSError, BrokenPipeError) as exc:
                raise self._process_error(phase) from exc
            if remaining <= 0.0:
                raise KaleidoExportTimeout(f"{phase} timed out")
            if not process.is_alive():
                raise self._process_error(phase)

    def _terminate_process_tree_locked(self) -> None:
        process = self._process
        if process is None:
            return
        group_id = (
            process.pid
            if os.name != "nt" and self._tree_ready and process.pid
            else None
        )
        group_signalled = False
        if group_id is not None:
            try:
                os.killpg(group_id, _POSIX_SIGTERM)
                group_signalled = True
            except OSError:
                pass
        if not group_signalled and process.is_alive():
            process.terminate()

        deadline = time.monotonic() + _WORKER_SHUTDOWN_GRACE_S
        while True:
            worker_alive = process.is_alive()
            group_alive = False
            if group_id is not None:
                try:
                    os.killpg(group_id, 0)
                    group_alive = True
                except OSError:
                    pass
            if not worker_alive and not group_alive:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                break
            time.sleep(min(remaining, _POLL_INTERVAL_S))

        if group_id is not None:
            try:
                os.killpg(group_id, 0)
            except OSError:
                group_alive = False
            else:
                group_alive = True
            if group_alive:
                try:
                    os.killpg(group_id, _POSIX_SIGKILL)
                except OSError:
                    pass
        if process.is_alive():
            process.kill()
        if process.pid is not None:
            process.join(_WORKER_SHUTDOWN_GRACE_S)

    def _discard_worker_locked(self, *, graceful: bool = False) -> None:
        connection = self._connection
        process = self._process
        if graceful and connection is not None and process is not None:
            if process.is_alive():
                try:
                    connection.send(("stop",))
                    process.join(_WORKER_SHUTDOWN_GRACE_S)
                except (BrokenPipeError, EOFError, OSError):
                    pass
        self._terminate_process_tree_locked()
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass
        if process is not None and not process.is_alive():
            try:
                process.close()
            except (OSError, ValueError):
                pass
        self._connection = None
        self._process = None
        self._tree_ready = False
        self._state = KaleidoExportState.NOT_STARTED

    def _start_locked(self, timeout: float) -> None:
        if self._state is KaleidoExportState.READY:
            return
        self._discard_worker_locked()
        child_connection = None
        try:
            parent_connection, child_connection = self._context.Pipe(duplex=True)
            self._connection = parent_connection
            process = self._context.Process(
                target=self._worker_target,
                args=(child_connection, self._page_factory),
                name="sector-kaleido-worker",
                daemon=True,
            )
            self._process = process
            self._state = KaleidoExportState.STARTING
            deadline = time.monotonic() + timeout
            process.start()
            child_connection.close()
            booted = self._receive_locked(
                deadline,
                "startup",
                consume_queued_on_timeout=True,
            )
            if booted and booted[0] == "startup-error":
                detail = ": ".join(str(item) for item in booted[1:])
                raise KaleidoExportError(f"startup failed: {detail}")
            if booted != ("booted",):
                raise KaleidoExportError("startup worker returned no boot handshake")
            self._tree_ready = True
            if deadline - time.monotonic() <= 0.0:
                raise KaleidoExportTimeout("startup timed out")
            assert self._connection is not None
            self._connection.send(("proceed",))
            ready = self._receive_locked(deadline, "startup")
            if ready and ready[0] == "startup-error":
                detail = ": ".join(str(item) for item in ready[1:])
                raise KaleidoExportError(f"startup failed: {detail}")
            if ready != ("ready",):
                raise KaleidoExportError("startup worker returned no ready handshake")
            self._state = KaleidoExportState.READY
        except BaseException as exc:
            if child_connection is not None:
                try:
                    child_connection.close()
                except OSError:
                    pass
            self._discard_worker_locked()
            if not isinstance(exc, Exception):
                raise
            if isinstance(exc, KaleidoExportError):
                raise
            raise KaleidoExportError(
                f"startup failed: {type(exc).__name__}: {exc}"
            ) from exc

    def ensure_ready(self, *, timeout: float) -> None:
        """Warm one child exporter and publish READY only after a real PNG."""

        selected_timeout = _positive_timeout(timeout)
        with self._lock:
            self._start_locked(selected_timeout)

    def export_png(
        self,
        figure: object,
        *,
        width: int | None,
        height: int | None,
        scale: float,
        timeout: float,
        description: str,
    ) -> bytes:
        """Return one PNG; discard an indeterminate worker before returning."""

        selected_timeout = _positive_timeout(timeout)
        selected_width = _optional_dimension("width", width)
        selected_height = _optional_dimension("height", height)
        selected_scale = _positive_scale(scale)
        if not isinstance(description, str) or not description.strip():
            raise ValueError("Kaleido image description must be non-empty text")
        figure_json = _figure_json(figure)
        options: dict[str, Any] = {"format": "png", "scale": selected_scale}
        if selected_width is not None:
            options["width"] = selected_width
        if selected_height is not None:
            options["height"] = selected_height
        with self._lock:
            try:
                self._start_locked(selected_timeout)
                self._request_id += 1
                request_id = self._request_id
                assert self._connection is not None
                self._connection.send(("render", request_id, figure_json, options))
                message = self._receive_locked(
                    time.monotonic() + selected_timeout,
                    description,
                )
                if (
                    len(message) == 3
                    and message[0] == "result"
                    and message[1] == request_id
                    and _valid_png(message[2])
                ):
                    return message[2]
                if (
                    len(message) == 4
                    and message[0] == "error"
                    and message[1] == request_id
                ):
                    raise KaleidoExportError(
                        f"{description} failed: {message[2]}: {message[3]}"
                    )
                raise KaleidoExportError(
                    f"{description} worker returned an invalid response"
                )
            except BaseException as exc:
                self._discard_worker_locked()
                if not isinstance(exc, Exception):
                    raise
                if isinstance(exc, KaleidoExportError):
                    raise
                raise KaleidoExportError(
                    f"{description} failed: {type(exc).__name__}: {exc}"
                ) from exc

    def close(self) -> None:
        """Bound shutdown even if Kaleido's own server thread is wedged."""

        with self._lock:
            self._discard_worker_locked(graceful=True)


_COORDINATOR = KaleidoExportCoordinator()


def ensure_ready(*, timeout: float) -> None:
    """Ensure the shared exporter has completed its real ready handshake."""

    _COORDINATOR.ensure_ready(timeout=timeout)


def export_png(
    figure: object,
    *,
    width: int | None = None,
    height: int | None = None,
    scale: float = 1.0,
    timeout: float,
    description: str,
) -> bytes:
    """Render one Plotly figure through the shared killable worker."""

    return _COORDINATOR.export_png(
        figure,
        width=width,
        height=height,
        scale=scale,
        timeout=timeout,
        description=description,
    )
