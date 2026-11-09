"""The real-image hang guard bounds each Kaleido start and each real-image test."""

from __future__ import annotations

import asyncio
import inspect
import sys
import threading
import time

import pytest
import real_image_guard as guard

from tools import kaleido_start


def _counted(*outcomes):
    """Return an async Kaleido-like function that plays one outcome per call."""
    calls = []

    async def export(value):
        calls.append(value)
        outcome = outcomes[len(calls) - 1]
        if outcome == "hang":
            await asyncio.sleep(30)
        if isinstance(outcome, BaseException):
            raise outcome
        return f"png-{value}"

    return export, calls


def test_bounded_start_returns_the_export_of_a_normal_start():
    export, calls = _counted("ok")
    assert guard.bounded_oneshot_async_run(export, ("a",), {}, limit=10.0) == "png-a"
    assert calls == ["a"]


def test_error_in_the_first_start_gets_one_more_start(capsys):
    export, calls = _counted(RuntimeError("page not ready"), "ok")
    assert guard.bounded_oneshot_async_run(export, ("d",), {}, limit=10.0) == "png-d"
    assert calls == ["d", "d"]
    assert "Kaleido start 1 of 2 failed (RuntimeError: page not ready)" in capsys.readouterr().err


def test_error_in_both_starts_reaches_the_test():
    export, calls = _counted(ValueError("first"), ValueError("bad figure"))
    with pytest.raises(ValueError, match="bad figure"):
        guard.bounded_oneshot_async_run(export, ("e",), {}, limit=10.0)
    assert calls == ["e", "e"]


def test_interrupt_is_not_tried_again():
    export, calls = _counted(KeyboardInterrupt(), "ok")
    with pytest.raises(KeyboardInterrupt):
        guard.bounded_oneshot_async_run(export, ("f",), {}, limit=10.0)
    assert calls == ["f"]


def test_timed_out_start_is_tried_once_more(capsys):
    export, calls = _counted("hang", "ok")
    started = time.monotonic()
    assert guard.bounded_oneshot_async_run(export, (), {"value": "b"}, limit=3.0) == "png-b"
    assert calls == ["b", "b"] and time.monotonic() - started < 30
    assert "Kaleido start 1 of 2 did not finish in 3 s" in capsys.readouterr().err


def test_late_result_of_a_timed_out_start_cannot_reach_the_next_start():
    # Start 1 returns at 4 s, after its 3 s limit and before start 2 returns at 5 s.
    calls = []

    async def export():
        calls.append(len(calls) + 1)
        number = len(calls)
        await asyncio.sleep(4.0 if number == 1 else 2.0)
        return f"start-{number}"

    assert guard.bounded_oneshot_async_run(export, (), {}, limit=3.0) == "start-2"
    assert calls == [1, 2]


def test_start_that_times_out_twice_fails_in_daemon_threads():
    export, calls = _counted("hang", "hang")
    with pytest.raises(guard.KaleidoStartTimeout, match="2 attempts"):
        guard.bounded_oneshot_async_run(export, ("c",), {}, limit=0.3)
    assert calls == ["c", "c"]
    waiting = [thread for thread in threading.enumerate() if thread.name.startswith("sector-kaleido-start-")]
    assert waiting and all(thread.daemon for thread in waiting)


def test_pinned_kaleido_routes_each_sync_export_through_the_patched_runner():
    """A Kaleido update that moves the one-shot runner must fail here first."""
    import kaleido
    from kaleido import _sync_server

    assert inspect.signature(_sync_server.oneshot_async_run).parameters.keys() == {"func", "args", "kwargs"}
    for name in ("calc_fig_sync", "write_fig_sync", "write_fig_from_object_sync"):
        assert "_sync_server.oneshot_async_run(" in inspect.getsource(getattr(kaleido, name))


def test_test_time_limit_dumps_every_thread_and_stops_the_process(capsys):
    stopped = []
    limit = guard.RealImageTimeLimit("tests/test_x.py::test_hangs", None, limit=0.2, stop=stopped.append)
    with limit:
        deadline = time.monotonic() + 10
        while not stopped and time.monotonic() < deadline:
            time.sleep(0.05)
    assert stopped == [guard.HANG_EXIT_CODE]
    err = capsys.readouterr().err
    assert "REAL-IMAGE HANG GUARD: tests/test_x.py::test_hangs did not finish in 0 s" in err
    assert "Thread MainThread:" in err and "test_test_time_limit_dumps_every_thread" in err


def test_hung_test_stops_a_real_pytest_process_with_its_stacks_on_the_console(tmp_path):
    import subprocess
    from pathlib import Path

    tests = Path(guard.__file__).resolve().parent
    (tmp_path / "conftest.py").write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(tests)!r})\n"
        f"sys.path.insert(0, {str(tests.parent)!r})\n"
        "import pytest\n"
        "from real_image_guard import RealImageTimeLimit\n\n"
        "@pytest.fixture(autouse=True)\n"
        "def _limit(request):\n"
        "    with RealImageTimeLimit(request.node.nodeid, request.config, limit=4.0):\n"
        "        yield\n", encoding="utf-8")
    browser = tmp_path / "browser.pid"
    (tmp_path / "test_hang.py").write_text(
        "import pathlib, subprocess, sys, threading\n\n"
        "def test_passes():\n    pass\n\n"
        "def test_waits_in_a_join():\n"
        "    # A browser-like child process that the hung test leaves behind.\n"
        "    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        f"    pathlib.Path({str(browser)!r}).write_text(str(child.pid))\n"
        "    worker = threading.Thread(target=threading.Event().wait)\n"
        "    worker.daemon = True\n    worker.start()\n    worker.join()\n", encoding="utf-8")
    started = time.monotonic()
    result = subprocess.run([sys.executable, "-m", "pytest", "test_hang.py", "-q", "-p", "no:cacheprovider"],
                            cwd=tmp_path, capture_output=True, text=True, timeout=180, check=False)
    assert result.returncode == guard.HANG_EXIT_CODE and time.monotonic() - started < 120
    output = result.stdout + result.stderr
    assert "REAL-IMAGE HANG GUARD: test_hang.py::test_waits_in_a_join did not finish in 4 s" in output
    assert "Thread MainThread:" in output and "worker.join()" in output
    from test_qa_core_shards import _process_exists

    pid = int(browser.read_text())
    deadline = time.monotonic() + 15
    while _process_exists(pid) and time.monotonic() < deadline:
        time.sleep(0.5)
    assert not _process_exists(pid), "the child process of the hung test survived the guard"


def test_test_time_limit_is_cancelled_when_the_test_ends():
    stopped = []
    with guard.RealImageTimeLimit("tests/test_x.py::test_fast", None, limit=0.3, stop=stopped.append):
        pass
    time.sleep(0.6)
    assert stopped == []


def test_time_limit_stops_the_process_also_when_the_report_fails():
    stopped = []
    limit = guard.RealImageTimeLimit("tests/test_x.py::test_hangs", None, limit=0.2, stop=stopped.append)

    def broken_report():
        raise OSError("console closed")

    limit._report = broken_report
    limit._timer.run = lambda: None  # the expiry runs below, not in the timer thread
    with pytest.raises(OSError):
        limit._expire()
    assert stopped == [guard.HANG_EXIT_CODE]


def test_conftest_applies_the_guard_only_to_the_real_image_marker(tmp_path):
    """Run the repository conftest as a plugin on a marked and an unmarked test."""
    import os
    import subprocess
    from pathlib import Path

    tests = Path(guard.__file__).resolve().parent
    (tmp_path / "test_wiring.py").write_text(
        "import threading\n"
        "import pytest\n"
        "from kaleido import _sync_server\n"
        "import real_image_guard\n\n"
        "@pytest.mark.real_image_export\n"
        "def test_marked():\n"
        "    assert _sync_server.oneshot_async_run is real_image_guard.bounded_oneshot_async_run\n"
        "    assert any(t.name == 'sector-real-image-time-limit' for t in threading.enumerate())\n\n"
        "def test_unmarked():\n"
        "    assert _sync_server.oneshot_async_run is not real_image_guard.bounded_oneshot_async_run\n",
        encoding="utf-8")
    environment = dict(os.environ, PYTHONPATH=os.pathsep.join((str(tests), str(tests.parent))))
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "test_wiring.py", "-p", "conftest", "-q", "-n", "0",
         "-p", "no:cacheprovider", "-o", "addopts=", "-o", "markers=real_image_export: guard"],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=300, check=False)
    assert result.returncode == 0, (result.stdout + result.stderr)[-2000:]
    assert "2 passed" in result.stdout


def test_exporter_start_is_tried_once_more_after_a_failed_start(capsys):
    exporter = kaleido_start.exporter_module()
    calls = []

    def ensure_ready(*, timeout):
        calls.append(timeout)
        if len(calls) == 1:
            raise exporter.KaleidoExportTimeout("startup timed out")

    assert kaleido_start.start_image_exporter(ensure_ready=ensure_ready) == 2
    assert calls == [kaleido_start.START_LIMIT_S, kaleido_start.START_LIMIT_S]
    assert "Kaleido start attempt 1 of 2 failed (startup timed out)" in capsys.readouterr().err


def test_exporter_start_failure_of_the_last_attempt_reaches_the_caller():
    exporter = kaleido_start.exporter_module()
    calls = []

    def ensure_ready(*, timeout):
        calls.append(timeout)
        raise exporter.KaleidoExportError("startup failed: no browser")

    with pytest.raises(exporter.KaleidoExportError, match="no browser"):
        kaleido_start.start_image_exporter(ensure_ready=ensure_ready, limit=5.0)
    assert calls == [5.0, 5.0]


def test_exporter_start_does_not_hide_a_programming_error():
    def ensure_ready(*, timeout):
        raise TypeError("wrong call")

    with pytest.raises(TypeError):
        kaleido_start.start_image_exporter(ensure_ready=ensure_ready)
    with pytest.raises(ValueError):
        kaleido_start.start_image_exporter(attempts=0)


def test_exporter_start_uses_the_module_object_of_the_report_and_manual():
    exporter = kaleido_start.exporter_module()
    assert sys.modules["publication_image_export"] is exporter
    root = kaleido_start.APP
    for name in ("sector_report.py", "manual.py"):
        assert "\nimport publication_image_export\n" in (root / name).read_text(encoding="utf-8")
