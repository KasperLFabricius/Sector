"""Killable, recoverable process contracts for publication image export."""

from __future__ import annotations

import base64
import ctypes
import io
import json
import multiprocessing
import os
import pathlib
import subprocess
import sys
import textwrap
import threading
import time
from types import SimpleNamespace

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import manual  # noqa: E402
import publication_image_export as image_export  # noqa: E402


class _ScenarioLauncher:
    def __init__(self, *scenarios) -> None:
        self._scenarios = list(scenarios or ({},))
        self._calls = 0

    @property
    def calls(self) -> int:
        return self._calls

    def __call__(self):
        index = min(self._calls, len(self._scenarios) - 1)
        self._calls += 1
        encoded = base64.urlsafe_b64encode(
            json.dumps(self._scenarios[index]).encode("utf-8")
        ).decode("ascii")
        command = [
            sys.executable,
            str(ROOT / "tests" / "publication_image_export_test_worker.py"),
            encoded,
        ]
        return image_export._launch_worker_command(command)


class _BlockingPageFactory:
    def __init__(self, folder: pathlib.Path) -> None:
        self.entered_path = str(folder / "page-factory-entered")
        self.release_path = str(folder / "page-factory-release")

    def __call__(self) -> str:
        pathlib.Path(self.entered_path).write_text("entered", encoding="ascii")
        deadline = time.monotonic() + 30.0
        while not pathlib.Path(self.release_path).exists():
            if time.monotonic() >= deadline:
                raise RuntimeError("test page factory was not released")
            time.sleep(0.01)
        return "{}"

    def wait_until_entered(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if pathlib.Path(self.entered_path).exists():
                return True
            time.sleep(0.01)
        return pathlib.Path(self.entered_path).exists()

    def release(self) -> None:
        pathlib.Path(self.release_path).write_text("release", encoding="ascii")


def _coordinator(*scenarios):
    launcher = _ScenarioLauncher(*scenarios)
    registered = []
    coordinator = image_export.KaleidoExportCoordinator(
        worker_launcher=launcher,
        register_exit=registered.append,
    )
    return coordinator, launcher, registered


def _figure(name: str) -> dict:
    return {
        "data": [
            {
                "type": "scatter",
                "x": [0.0, 1.0],
                "y": [0.0, 1.0],
                "name": name,
            }
        ]
    }


def _decoded_result(payload: bytes) -> dict:
    assert payload.startswith(image_export._PNG_SIGNATURE)
    return json.loads(payload[len(image_export._PNG_SIGNATURE) :])


def _pid_alive(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel32.OpenProcess(0x00100000, False, pid)
    if not handle:
        return False
    try:
        return kernel32.WaitForSingleObject(handle, 0) == 0x00000102
    finally:
        kernel32.CloseHandle(handle)


def test_ready_is_published_only_after_worker_warmup(tmp_path) -> None:
    release = tmp_path / "release"
    coordinator, pages, registered = _coordinator({"ready_file": str(release)})
    errors = []

    def ensure() -> None:
        try:
            coordinator.ensure_ready(timeout=10.0)
        except BaseException as exc:
            errors.append(exc)

    caller = threading.Thread(target=ensure)
    caller.start()
    deadline = time.monotonic() + 3.0
    while coordinator.state is image_export.KaleidoExportState.NOT_STARTED:
        assert time.monotonic() < deadline
        time.sleep(0.01)
    assert coordinator.state is image_export.KaleidoExportState.STARTING
    assert caller.is_alive()
    release.touch()
    caller.join(12.0)

    try:
        assert not caller.is_alive()
        assert not errors
        assert coordinator.state is image_export.KaleidoExportState.READY
        assert pages.calls == 1
        assert registered == [coordinator.close]
    finally:
        coordinator.close()


def test_concurrent_exports_keep_results_with_their_callers_and_start_once() -> None:
    coordinator, pages, _registered = _coordinator({"render_delay": 0.05})
    results = {}
    errors = []

    def export(name: str) -> None:
        try:
            results[name] = coordinator.export_png(
                _figure(name),
                width=240,
                height=120,
                scale=2,
                timeout=10.0,
                description=f"{name} export",
            )
        except BaseException as exc:
            errors.append(exc)

    callers = [threading.Thread(target=export, args=(name,)) for name in ("one", "two")]
    for caller in callers:
        caller.start()
    for caller in callers:
        caller.join(5.0)

    try:
        assert not errors
        assert all(not caller.is_alive() for caller in callers)
        assert pages.calls == 1
        for name, payload in results.items():
            decoded = _decoded_result(payload)
            assert decoded["figure"]["data"][0]["name"] == name
            assert decoded["options"] == {
                "format": "png",
                "height": 120,
                "scale": 2.0,
                "width": 240,
            }
    finally:
        coordinator.close()


def test_request_and_png_larger_than_a_pipe_buffer_round_trip_within_timeout() -> None:
    coordinator, launches, _registered = _coordinator({})
    large_name = "retained-" + ("x" * (1024 * 1024))
    try:
        payload = coordinator.export_png(
            _figure(large_name),
            width=240,
            height=120,
            scale=1,
            timeout=10.0,
            description="large framed export",
        )

        assert _decoded_result(payload)["figure"]["data"][0]["name"] == large_name
        assert launches.calls == 1
    finally:
        coordinator.close()


@pytest.mark.parametrize("failure", ["startup_error", "startup_block"])
def test_startup_failure_or_timeout_discards_worker_and_recovers(failure) -> None:
    coordinator, pages, _registered = _coordinator({failure: True}, {})
    try:
        expected = (
            image_export.KaleidoExportTimeout
            if failure == "startup_block"
            else image_export.KaleidoExportError
        )
        with pytest.raises(expected):
            coordinator.ensure_ready(timeout=10.0)
        assert coordinator.state is image_export.KaleidoExportState.NOT_STARTED

        coordinator.ensure_ready(timeout=10.0)
        assert coordinator.state is image_export.KaleidoExportState.READY
        assert pages.calls == 2
    finally:
        coordinator.close()


def test_blocking_page_factory_is_inside_the_bounded_worker(tmp_path) -> None:
    page_factory = _BlockingPageFactory(tmp_path)
    launcher = _ScenarioLauncher(
        {
            "page_entered_file": page_factory.entered_path,
            "page_release_file": page_factory.release_path,
        }
    )
    registered = []
    coordinator = image_export.KaleidoExportCoordinator(
        worker_launcher=launcher,
        register_exit=registered.append,
    )
    errors = []

    def start() -> None:
        try:
            coordinator.ensure_ready(timeout=10.0)
        except BaseException as exc:
            errors.append(exc)

    caller = threading.Thread(target=start)
    caller.start()
    entered = page_factory.wait_until_entered(10.0)
    caller.join(11.0)
    bounded = not caller.is_alive()
    page_factory.release()
    caller.join(10.0)
    try:
        assert entered, errors
        assert bounded
        assert len(errors) == 1
        assert isinstance(errors[0], image_export.KaleidoExportTimeout)
        assert coordinator.state is image_export.KaleidoExportState.NOT_STARTED
        assert registered == [coordinator.close]
    finally:
        page_factory.release()
        coordinator.close()


def test_queued_boot_handshake_marks_tree_owned_before_timeout_cleanup(
    monkeypatch,
) -> None:
    class _Connection:
        def __init__(self, *messages) -> None:
            self.messages = list(messages)
            self.poll_waits = []
            self.closed = False

        def poll(self, wait) -> bool:
            self.poll_waits.append(wait)
            return bool(self.messages)

        def recv(self):
            return self.messages.pop(0)

        def close(self) -> None:
            self.closed = True

    class _Process:
        pid = 4321
        exitcode = None

        def __init__(self) -> None:
            self.closed = False

        def is_alive(self) -> bool:
            return False

        def close(self) -> None:
            self.closed = True

    parent = _Connection(("booted",), ("ready",))
    process = _Process()
    launch_calls = []

    def launch():
        launch_calls.append(True)
        return parent, process

    coordinator = image_export.KaleidoExportCoordinator(
        worker_launcher=launch,
        register_exit=lambda _callback: None,
    )
    cleanup_tree_states = []

    def record_cleanup() -> None:
        if coordinator._process is not None:
            cleanup_tree_states.append(coordinator._tree_ready)

    monkeypatch.setattr(coordinator, "_terminate_process_tree_locked", record_cleanup)
    monotonic_values = iter((100.0, 102.0, 102.0))
    monkeypatch.setattr(
        image_export.time,
        "monotonic",
        lambda: next(monotonic_values),
    )

    with pytest.raises(image_export.KaleidoExportTimeout, match="startup timed out"):
        coordinator.ensure_ready(timeout=1.0)

    assert parent.poll_waits == [0.0]
    assert parent.messages == [("ready",)]
    assert cleanup_tree_states == [True]
    assert launch_calls == [True]
    assert process.closed is True
    assert parent.closed is True
    assert coordinator.state is image_export.KaleidoExportState.NOT_STARTED


def test_export_failure_discards_worker_and_later_export_recovers() -> None:
    coordinator, pages, _registered = _coordinator({"render_error": True}, {})
    try:
        with pytest.raises(image_export.KaleidoExportError, match="bad figure"):
            coordinator.export_png(
                _figure("bad"),
                width=None,
                height=None,
                scale=1,
                timeout=10.0,
                description="failed export",
            )
        assert coordinator.state is image_export.KaleidoExportState.NOT_STARTED

        result = coordinator.export_png(
            _figure("clean"),
            width=None,
            height=None,
            scale=1,
            timeout=10.0,
            description="clean export",
        )
        assert _decoded_result(result)["figure"]["data"][0]["name"] == "clean"
        assert pages.calls == 2
    finally:
        coordinator.close()


def test_timeout_kills_owned_descendant_tree_and_later_export_recovers(
    tmp_path,
) -> None:
    descendant_file = tmp_path / "descendant.pid"
    coordinator, pages, _registered = _coordinator(
        {"render_block": True, "descendant_file": str(descendant_file)},
        {},
    )
    try:
        coordinator.ensure_ready(timeout=10.0)
        assert descendant_file.is_file()
        with pytest.raises(image_export.KaleidoExportTimeout, match="timed out"):
            coordinator.export_png(
                _figure("blocked"),
                width=100,
                height=100,
                scale=1,
                timeout=0.3,
                description="blocked export",
            )
        assert coordinator.state is image_export.KaleidoExportState.NOT_STARTED
        pid = int(descendant_file.read_text(encoding="ascii"))
        deadline = time.monotonic() + 5.0
        while _pid_alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not _pid_alive(pid)

        result = coordinator.export_png(
            _figure("recovered"),
            width=100,
            height=100,
            scale=1,
            timeout=10.0,
            description="recovered export",
        )
        assert _decoded_result(result)["figure"]["data"][0]["name"] == "recovered"
        assert pages.calls == 2
    finally:
        coordinator.close()


def test_posix_cleanup_signals_a_group_after_its_leader_has_exited(
    monkeypatch,
) -> None:
    signals = []
    joins = []
    process = SimpleNamespace(
        pid=4321,
        is_alive=lambda: False,
        terminate=lambda: pytest.fail("dead leader must not be terminated"),
        kill=lambda: pytest.fail("dead leader must not be killed"),
        join=lambda timeout: joins.append(timeout),
    )

    def killpg(_group_id, selected_signal):
        if selected_signal == 0:
            raise ProcessLookupError
        signals.append(selected_signal)

    monkeypatch.setattr(image_export.os, "name", "posix")
    monkeypatch.setattr(image_export.os, "killpg", killpg, raising=False)
    coordinator, _pages, _registered = _coordinator({})
    coordinator._process = process
    coordinator._tree_ready = True

    coordinator._terminate_process_tree_locked()

    assert signals == [image_export._POSIX_SIGTERM]
    assert joins == [image_export._WORKER_SHUTDOWN_GRACE_S]


def test_posix_cleanup_escalates_for_a_sigterm_resistant_group(monkeypatch) -> None:
    signals = []
    process = SimpleNamespace(
        pid=4321,
        is_alive=lambda: False,
        terminate=lambda: pytest.fail("dead leader must not be terminated"),
        kill=lambda: pytest.fail("dead leader must not be killed"),
        join=lambda _timeout: None,
    )

    def killpg(_group_id, selected_signal):
        if selected_signal:
            signals.append(selected_signal)

    monkeypatch.setattr(image_export.os, "name", "posix")
    monkeypatch.setattr(image_export.os, "killpg", killpg, raising=False)
    monkeypatch.setattr(image_export, "_WORKER_SHUTDOWN_GRACE_S", 0.0)
    coordinator, _pages, _registered = _coordinator({})
    coordinator._process = process
    coordinator._tree_ready = True

    coordinator._terminate_process_tree_locked()

    assert signals == [image_export._POSIX_SIGTERM, image_export._POSIX_SIGKILL]


def test_actual_worker_protocol_requires_warmup_and_returns_render(monkeypatch) -> None:
    parent, child = multiprocessing.Pipe(duplex=True)
    calls = []
    page_called = threading.Event()
    monkeypatch.setattr(image_export, "_own_descendant_processes", lambda: None)
    monkeypatch.setattr(
        image_export,
        "_start_and_warm_kaleido",
        lambda page: calls.append(("warm", page)),
    )
    monkeypatch.setattr(
        image_export,
        "_render_worker_png",
        lambda figure, options: image_export._PNG_SIGNATURE + b"actual",
    )

    def page_factory():
        page_called.set()
        calls.append(("page",))
        return "persistent.html"

    worker = threading.Thread(
        target=image_export._worker_main,
        args=(child, page_factory),
    )
    worker.start()
    assert parent.recv() == ("booted",)
    assert page_called.wait(0.1) is False
    parent.send(("proceed",))
    assert parent.recv() == ("ready",)
    assert page_called.is_set() is True
    parent.send(("render", 7, "{}", {"format": "png", "scale": 1}))
    assert parent.recv() == (
        "result",
        7,
        image_export._PNG_SIGNATURE + b"actual",
    )
    parent.send(("stop",))
    worker.join(2.0)
    assert not worker.is_alive()
    assert calls == [("page",), ("warm", "persistent.html")]


def test_production_warmup_starts_server_then_requires_real_png(monkeypatch) -> None:
    calls = []

    def start(**kwargs):
        calls.append(("start", kwargs))

    def render(figure, *, opts):
        calls.append(("render", figure, opts))
        return image_export._PNG_SIGNATURE + b"warm"

    monkeypatch.setitem(
        sys.modules,
        "kaleido",
        SimpleNamespace(start_sync_server=start, calc_fig_sync=render),
    )
    monkeypatch.setattr(image_export.os, "name", "nt")
    image_export._start_and_warm_kaleido("persistent.html")

    assert calls == [
        (
            "start",
            {
                "silence_warnings": True,
                "timeout": image_export._KALEIDO_RENDER_TIMEOUT_S,
                "page_generator": "persistent.html",
            },
        ),
        ("render", image_export._WARMUP_FIGURE, image_export._WARMUP_OPTIONS),
    ]


def test_posix_warmup_keeps_locked_chromium_in_worker_group(monkeypatch) -> None:
    from choreographer.browsers.chromium import Chromium

    starts = []

    def start(**kwargs):
        starts.append(kwargs)

    monkeypatch.setattr(
        Chromium,
        "get_popen_args",
        lambda _self: {
            "close_fds": True,
            "start_new_session": True,
            "stdin": "retained-input",
        },
    )
    monkeypatch.setitem(
        sys.modules,
        "kaleido",
        SimpleNamespace(
            start_sync_server=start,
            calc_fig_sync=lambda _figure, *, opts: image_export._PNG_SIGNATURE,
        ),
    )
    monkeypatch.setattr(image_export.os, "name", "posix")

    image_export._start_and_warm_kaleido("persistent.html")

    assert len(starts) == 1
    selected_browser = starts[0]["browser_cls"]
    assert selected_browser is not Chromium
    assert issubclass(selected_browser, Chromium)
    browser = selected_browser.__new__(selected_browser)
    assert browser.get_popen_args() == {
        "close_fds": True,
        "start_new_session": False,
        "stdin": "retained-input",
    }
    assert {key: value for key, value in starts[0].items() if key != "browser_cls"} == {
        "silence_warnings": True,
        "timeout": image_export._KALEIDO_RENDER_TIMEOUT_S,
        "page_generator": "persistent.html",
    }


def test_source_worker_command_is_a_dedicated_script_not_the_streamlit_app(
    monkeypatch,
) -> None:
    monkeypatch.delattr(image_export.sys, "frozen", raising=False)

    command = image_export._worker_command()

    assert command == [
        sys.executable,
        str(ROOT / "app" / "publication_image_export_worker.py"),
    ]
    assert "sector_app.py" not in " ".join(command)
    source = (ROOT / "app" / "publication_image_export.py").read_text(encoding="utf-8")
    assert "import multiprocessing" not in source
    assert "multiprocessing.get_context" not in source


def test_frozen_worker_command_uses_the_pre_streamlit_launcher_route(
    monkeypatch,
) -> None:
    monkeypatch.setattr(image_export.sys, "frozen", True, raising=False)

    assert image_export._worker_command() == [
        sys.executable,
        image_export._FROZEN_WORKER_FLAG,
    ]


def test_dedicated_source_worker_does_not_reexecute_a_hostile_parent_main(
    tmp_path,
) -> None:
    counter = tmp_path / "parent-main-count.txt"
    script = tmp_path / "hostile_parent.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import pathlib
            import sys
            import time

            counter = pathlib.Path(sys.argv[1])
            count = int(counter.read_text(encoding="ascii")) if counter.exists() else 0
            counter.write_text(str(count + 1), encoding="ascii")
            sys.path.insert(0, {str(ROOT / "app")!r})
            import publication_image_export as image_export

            connection, process = image_export._launch_worker()
            try:
                deadline = time.monotonic() + 10.0
                while not connection.poll(0.05):
                    if time.monotonic() >= deadline:
                        raise RuntimeError("dedicated worker sent no boot handshake")
                assert connection.recv() == ("booted",)
                connection.send(("abort-before-kaleido",))
                process.join(5.0)
                assert not process.is_alive()
            finally:
                if process.is_alive():
                    process.kill()
                    process.join(5.0)
                connection.close()
            """
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, str(script), str(counter)],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=20.0,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert counter.read_text(encoding="ascii") == "1"


def test_portable_launcher_worker_route_reaches_boot_before_streamlit() -> None:
    command = [
        sys.executable,
        str(ROOT / "packaging" / "run_sector.py"),
        image_export._FROZEN_WORKER_FLAG,
    ]
    connection, process = image_export._launch_worker_command(command)
    try:
        deadline = time.monotonic() + 10.0
        while not connection.poll(0.05):
            assert time.monotonic() < deadline
        assert connection.recv() == ("booted",)
        connection.send(("abort-before-kaleido",))
        deadline = time.monotonic() + 5.0
        while not connection.poll(0.05):
            assert time.monotonic() < deadline
        error = connection.recv()
        assert error[:2] == ("startup-error", "RuntimeError")
        assert "ownership acknowledgement" in error[2]
        process.join(5.0)
        assert not process.is_alive()
    finally:
        if process.is_alive():
            process.kill()
            process.join(5.0)
        connection.close()


def test_protocol_round_trip_preserves_unicode_metadata_and_png_bytes() -> None:
    message = (
        "result",
        17,
        image_export._PNG_SIGNATURE + (b"x" * (1024 * 1024)),
        "tværsnit",
    )

    encoded = image_export._encode_protocol_message(message)

    assert encoded.endswith(b"\n")
    assert image_export._decode_protocol_message(encoded[:-1]) == message


@pytest.mark.parametrize(
    "payload",
    [
        b'{"kind":"ready"}',
        b'[{"__sector_png_bytes__":"not base64!"}]',
        b"not json",
    ],
)
def test_protocol_rejects_malformed_frames(payload) -> None:
    with pytest.raises((ValueError, json.JSONDecodeError)):
        image_export._decode_protocol_message(payload)


def test_stream_connection_rejects_a_truncated_frame_without_blocking() -> None:
    connection = image_export._StreamConnection(
        io.BytesIO(b'["ready"]'),
        io.BytesIO(),
    )
    try:
        assert connection.poll(1.0) is True
        with pytest.raises(OSError, match="invalid image-export protocol stream"):
            connection.recv()
    finally:
        connection.close()


@pytest.mark.parametrize("timeout", [False, 0, -1, float("nan"), float("inf"), "bad"])
def test_invalid_timeouts_start_no_worker(timeout) -> None:
    coordinator, pages, _registered = _coordinator({})
    with pytest.raises(ValueError, match="timeout"):
        coordinator.ensure_ready(timeout=timeout)
    assert pages.calls == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("width", False),
        ("width", 0),
        ("width", 1.5),
        ("height", -1),
        ("scale", False),
        ("scale", 0),
        ("scale", float("inf")),
    ],
)
def test_invalid_render_options_start_no_worker(field, value) -> None:
    coordinator, pages, _registered = _coordinator({})
    options = {"width": 1, "height": 1, "scale": 1}
    options[field] = value
    with pytest.raises(ValueError, match=field):
        coordinator.export_png(
            _figure("unused"),
            timeout=1,
            description="unused",
            **options,
        )
    assert pages.calls == 0


def test_unserializable_figure_starts_no_worker() -> None:
    coordinator, pages, _registered = _coordinator({})
    with pytest.raises(image_export.KaleidoExportError, match="serialization"):
        coordinator.export_png(
            object(),
            width=None,
            height=None,
            scale=1,
            timeout=1,
            description="unused",
        )
    assert pages.calls == 0


def test_figure_serialization_preserves_control_flow_exceptions(monkeypatch) -> None:
    import plotly.io as plotly_io

    def interrupt(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(plotly_io, "to_json", interrupt)
    coordinator, pages, _registered = _coordinator({})
    with pytest.raises(KeyboardInterrupt):
        coordinator.export_png(
            _figure("unused"),
            width=None,
            height=None,
            scale=1,
            timeout=1,
            description="unused",
        )
    assert pages.calls == 0
    assert coordinator.state is image_export.KaleidoExportState.NOT_STARTED


def test_worker_launch_failure_is_wrapped_as_exporter_error() -> None:
    def fail_launch():
        raise OSError("worker unavailable")

    coordinator = image_export.KaleidoExportCoordinator(
        worker_launcher=fail_launch,
        register_exit=lambda _callback: None,
    )
    with pytest.raises(
        image_export.KaleidoExportError,
        match="startup failed: OSError: worker unavailable",
    ):
        coordinator.ensure_ready(timeout=1)
    assert coordinator.state is image_export.KaleidoExportState.NOT_STARTED


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (OSError("pipe send failed"), image_export.KaleidoExportError),
        (KeyboardInterrupt(), KeyboardInterrupt),
    ],
)
def test_send_failure_cleans_up_and_preserves_exception_boundary(
    failure,
    expected,
) -> None:
    class _BrokenConnection:
        def __init__(self) -> None:
            self.closed = False

        def send(self, _message) -> None:
            raise failure

        def close(self) -> None:
            self.closed = True

    connection = _BrokenConnection()
    process = SimpleNamespace(
        pid=None,
        is_alive=lambda: False,
        terminate=lambda: None,
        kill=lambda: None,
        close=lambda: None,
    )
    coordinator, _pages, _registered = _coordinator({})
    coordinator._connection = connection
    coordinator._process = process
    coordinator._state = image_export.KaleidoExportState.READY

    with pytest.raises(expected):
        coordinator.export_png(
            _figure("unused"),
            width=None,
            height=None,
            scale=1,
            timeout=1,
            description="send export",
        )

    assert connection.closed is True
    assert coordinator.state is image_export.KaleidoExportState.NOT_STARTED


def test_manual_startup_failure_writes_no_partial_pdf(monkeypatch) -> None:
    def fail_start(*, timeout):
        del timeout
        raise image_export.KaleidoExportError("startup failed")

    monkeypatch.setattr(image_export, "ensure_ready", fail_start)
    output = io.BytesIO()

    with pytest.raises(manual.ManualFigureError, match="manual not created"):
        manual.build_manual_pdf(output, figures=True)

    assert output.getvalue() == b""


def test_manual_export_failure_writes_no_partial_pdf(monkeypatch) -> None:
    monkeypatch.setattr(image_export, "ensure_ready", lambda *, timeout: None)

    def fail_export(*args, **kwargs):
        del args, kwargs
        raise image_export.KaleidoExportError("render failed")

    monkeypatch.setattr(image_export, "export_png", fail_export)
    output = io.BytesIO()

    with pytest.raises(manual.ManualFigureError, match="manual not created"):
        manual.build_manual_pdf(output, figures=True)

    assert output.getvalue() == b""


def test_manual_figures_false_never_touches_exporter(monkeypatch) -> None:
    def unexpected(*args, **kwargs):
        del args, kwargs
        raise AssertionError("figures=False touched the exporter")

    monkeypatch.setattr(image_export, "ensure_ready", unexpected)
    monkeypatch.setattr(image_export, "export_png", unexpected)
    output = io.BytesIO()

    manual.build_manual_pdf(output, figures=False)

    assert output.getvalue().startswith(b"%PDF")


def test_declared_kaleido_floor_matches_the_process_server_api() -> None:
    requirements = (ROOT / "requirements.in").read_text(encoding="utf-8")
    assert requirements.count("kaleido>=1.3,<2") == 1
    assert requirements.count("choreographer>=1.3,<2") == 1
    assert "kaleido>=0.2.1" not in requirements
