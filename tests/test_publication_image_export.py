"""Process-wide containment contracts for publication image export."""

from __future__ import annotations

import io
import pathlib
import sys
import threading
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import manual  # noqa: E402
import publication_image_export as image_export  # noqa: E402


class _CountingThreadFactory:
    def __init__(self) -> None:
        self.count = 0
        self._lock = threading.Lock()

    def __call__(self, **kwargs) -> threading.Thread:
        with self._lock:
            self.count += 1
        return threading.Thread(**kwargs)


def _coordinator(starter, *, thread_factory=threading.Thread):
    registered = []
    coordinator = image_export.KaleidoExportCoordinator(
        starter,
        thread_factory=thread_factory,
        register_exit=registered.append,
    )
    return coordinator, registered


def test_ready_is_published_only_after_startup_completes() -> None:
    entered = threading.Event()
    release = threading.Event()

    def start():
        entered.set()
        assert release.wait(2.0)
        return lambda: None

    coordinator, registered = _coordinator(start)
    errors = []

    def ensure():
        try:
            coordinator.ensure_ready(timeout=2.0)
        except BaseException as exc:
            errors.append(exc)

    caller = threading.Thread(target=ensure)
    caller.start()
    assert entered.wait(1.0)
    assert coordinator.state is image_export.KaleidoExportState.NOT_STARTED
    release.set()
    caller.join(2.0)

    assert not caller.is_alive()
    assert not errors
    assert coordinator.state is image_export.KaleidoExportState.READY
    assert len(registered) == 1


def test_concurrent_exports_serialize_and_start_once() -> None:
    counts = {"start": 0, "active": 0, "maximum": 0}
    counts_lock = threading.Lock()
    results = []
    errors = []

    def start():
        counts["start"] += 1

    coordinator, _registered = _coordinator(start)

    def render(payload):
        with counts_lock:
            counts["active"] += 1
            counts["maximum"] = max(counts["maximum"], counts["active"])
        time.sleep(0.03)
        with counts_lock:
            counts["active"] -= 1
        return payload

    def export(payload):
        try:
            results.append(
                coordinator.export_png(
                    lambda: render(payload),
                    timeout=1.0,
                    description="test export",
                )
            )
        except BaseException as exc:
            errors.append(exc)

    callers = [
        threading.Thread(target=export, args=(payload,))
        for payload in (b"one", b"two")
    ]
    for caller in callers:
        caller.start()
    for caller in callers:
        caller.join(2.0)

    assert all(not caller.is_alive() for caller in callers)
    assert not errors
    assert sorted(results) == [b"one", b"two"]
    assert counts == {"start": 1, "active": 0, "maximum": 1}
    assert coordinator.state is image_export.KaleidoExportState.READY


def test_startup_failure_poisons_and_later_calls_spawn_no_threads() -> None:
    threads = _CountingThreadFactory()

    def fail_start():
        raise RuntimeError("browser unavailable")

    coordinator, _registered = _coordinator(
        fail_start,
        thread_factory=threads,
    )
    with pytest.raises(image_export.KaleidoExportError, match="startup failed"):
        coordinator.ensure_ready(timeout=1.0)

    assert coordinator.state is image_export.KaleidoExportState.POISONED
    assert threads.count == 1
    with pytest.raises(image_export.KaleidoExporterPoisoned):
        coordinator.ensure_ready(timeout=1.0)
    with pytest.raises(image_export.KaleidoExporterPoisoned):
        coordinator.export_png(
            lambda: b"unused",
            timeout=1.0,
            description="unused export",
        )
    assert threads.count == 1


def test_export_failure_poisons_and_later_calls_spawn_no_threads() -> None:
    threads = _CountingThreadFactory()
    coordinator, _registered = _coordinator(
        lambda: None,
        thread_factory=threads,
    )

    def fail_render():
        raise ValueError("bad figure")

    with pytest.raises(image_export.KaleidoExportError, match="bad figure"):
        coordinator.export_png(
            fail_render,
            timeout=1.0,
            description="failed export",
        )

    assert coordinator.state is image_export.KaleidoExportState.POISONED
    assert threads.count == 2
    with pytest.raises(image_export.KaleidoExporterPoisoned):
        coordinator.export_png(
            lambda: b"unused",
            timeout=1.0,
            description="unused export",
        )
    assert threads.count == 2


def test_export_timeout_poisons_and_later_calls_spawn_no_threads() -> None:
    threads = _CountingThreadFactory()
    release = threading.Event()
    coordinator, _registered = _coordinator(
        lambda: None,
        thread_factory=threads,
    )

    def block_render():
        release.wait(2.0)
        return b"late"

    try:
        with pytest.raises(image_export.KaleidoExportTimeout, match="timed out"):
            coordinator.export_png(
                block_render,
                timeout=0.02,
                description="blocked export",
            )
        assert coordinator.state is image_export.KaleidoExportState.POISONED
        assert threads.count == 2
        with pytest.raises(image_export.KaleidoExporterPoisoned):
            coordinator.export_png(
                lambda: b"unused",
                timeout=1.0,
                description="unused export",
            )
        assert threads.count == 2
    finally:
        release.set()


def test_production_starter_configures_page_timeout_and_deferred_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"start": None, "stop": None}

    def start(**kwargs):
        calls["start"] = kwargs

    def stop(**kwargs):
        calls["stop"] = kwargs

    monkeypatch.setattr(image_export, "_kaleido_server_api", lambda: (start, stop))
    monkeypatch.setattr(
        image_export,
        "_kaleido_page_path",
        lambda: "persistent-plotly-export.html",
    )

    deferred_stop = image_export._start_kaleido_server()

    assert calls["start"] == {
        "silence_warnings": True,
        "timeout": image_export._KALEIDO_RENDER_TIMEOUT_S,
        "page_generator": "persistent-plotly-export.html",
    }
    assert calls["stop"] is None
    assert deferred_stop is not None
    deferred_stop()
    assert calls["stop"] == {"silence_warnings": True}


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
    monkeypatch.setattr(
        image_export,
        "ensure_ready",
        lambda *, timeout: None,
    )

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
