"""Tests for the practical packaged first-page smoke."""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import pytest

from tools import verify_portable_startup as startup


def _varint(value: int) -> bytes:
    encoded = bytearray()
    while value >= 0x80:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _bytes_field(number: int, payload: bytes) -> bytes:
    return _varint((number << 3) | 2) + _varint(len(payload)) + payload


class _Response:
    def __init__(self, status: int, body: bytes):
        self.status = status
        self._body = body

    def read(self, limit: int) -> bytes:
        return self._body[:limit]


class _Connection:
    instances: ClassVar[list[_Connection]] = []
    status = 200
    body = b"ok"

    def __init__(self, host: str, *, port: int, timeout: float):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.request_call: tuple[str, str, dict[str, str]] | None = None
        self.closed = False
        self.__class__.instances.append(self)

    def request(self, method: str, path: str, *, headers: dict[str, str]):
        self.request_call = (method, path, headers)

    def getresponse(self) -> _Response:
        return _Response(self.status, self.body)

    def close(self) -> None:
        self.closed = True


def test_health_request_is_exact_loopback_without_redirect(monkeypatch):
    _Connection.instances.clear()
    _Connection.status = 200
    _Connection.body = b"ok"
    monkeypatch.setattr(startup.http.client, "HTTPConnection", _Connection)

    assert startup._request_health(54321, 0.5) == b"ok"
    connection = _Connection.instances[-1]
    assert connection.host == "127.0.0.1"
    assert connection.request_call == (
        "GET",
        "/_stcore/health",
        {"Accept": "text/plain", "Connection": "close"},
    )
    assert connection.closed is True

    _Connection.status = 302
    with pytest.raises(startup.PortableStartupError, match="redirects are rejected"):
        startup._request_health(54321, 0.5)


@pytest.mark.parametrize("body", [b"", b"OK", b"ok\n", b"okay"])
def test_health_rejects_nonexact_body(monkeypatch, body):
    _Connection.status = 200
    _Connection.body = body
    monkeypatch.setattr(startup.http.client, "HTTPConnection", _Connection)
    with pytest.raises(startup.PortableStartupError, match="exactly b'ok'"):
        startup._request_health(54321, 0.5)


def test_streamlit_exception_element_exposes_the_real_import_failure():
    exception = _bytes_field(1, b"ImportError") + _bytes_field(
        2, b"DLL load failed while importing _compute"
    )
    element = _bytes_field(8, exception)
    delta = _bytes_field(3, element)
    forward_exception = _bytes_field(5, delta)

    assert startup._page_exception(forward_exception) == (
        "ImportError",
        "DLL load failed while importing _compute",
    )
    assert startup._page_has_element(forward_exception) is True
    assert startup._page_finished_status(b"\x30\x00") == 0


class _FakeProcess:
    instances: ClassVar[list[_FakeProcess]] = []

    def __init__(self, arguments, **kwargs):
        self.arguments = arguments
        self.kwargs = kwargs
        self.returncode = None
        self.pid = 4242
        self.terminated = False
        self.killed = False
        self.__class__.instances.append(self)

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        del timeout
        return self.returncode


def _package(tmp_path: Path) -> Path:
    package = tmp_path / "Sector-v0.93-windows-portable"
    package.mkdir()
    (package / "Sector.exe").write_bytes(b"fake")
    return package


def test_smoke_launches_package_executes_page_and_writes_diagnostics(
    tmp_path, monkeypatch
):
    package = _package(tmp_path)
    workspace = tmp_path / "smoke"
    _FakeProcess.instances.clear()
    monkeypatch.setattr(startup.subprocess, "Popen", _FakeProcess)
    monkeypatch.setattr(startup, "_select_loopback_port", lambda: 54321)
    monkeypatch.setattr(
        startup, "_wait_for_health", lambda process, port, timeout: b"ok"
    )
    monkeypatch.setattr(
        startup,
        "_run_page_session",
        lambda process, port, timeout: startup._PageExecutionEvidence(
            118, "finished-successfully"
        ),
    )

    evidence = startup.run_portable_startup_smoke(
        package, workspace, timeout_seconds=30
    )

    process = _FakeProcess.instances[-1]
    assert process.arguments == [str(package / "Sector.exe")]
    assert process.kwargs["cwd"] == package
    environment = process.kwargs["env"]
    assert environment["SECTOR_HEADLESS"] == "1"
    assert environment["SECTOR_PORT"] == "54321"
    assert process.terminated is True
    assert evidence.health_status == "ok"
    assert evidence.page_status == "finished-successfully"
    assert evidence.page_message_count == 118
    receipt = json.loads((workspace / "startup-smoke.json").read_text("ascii"))
    assert receipt["page_status"] == "finished-successfully"
    assert (workspace / "Sector-startup-stdout.log").is_file()
    assert (workspace / "Sector-startup-stderr.log").is_file()


def test_page_failure_still_terminates_process(tmp_path, monkeypatch):
    package = _package(tmp_path)
    workspace = tmp_path / "smoke"
    _FakeProcess.instances.clear()
    monkeypatch.setattr(startup.subprocess, "Popen", _FakeProcess)
    monkeypatch.setattr(startup, "_select_loopback_port", lambda: 54321)
    monkeypatch.setattr(
        startup, "_wait_for_health", lambda process, port, timeout: b"ok"
    )

    def fail_page(process, port, timeout):
        del process, port, timeout
        raise startup.PortableStartupError("packaged page raised ImportError")

    monkeypatch.setattr(startup, "_run_page_session", fail_page)
    with pytest.raises(startup.PortableStartupError, match="ImportError"):
        startup.run_portable_startup_smoke(package, workspace, timeout_seconds=30)
    assert _FakeProcess.instances[-1].terminated is True


def test_existing_workspace_and_missing_executable_fail_before_launch(
    tmp_path, monkeypatch
):
    package = _package(tmp_path)
    workspace = tmp_path / "smoke"
    workspace.mkdir()
    monkeypatch.setattr(startup.subprocess, "Popen", _FakeProcess)
    with pytest.raises(startup.PortableStartupError, match="already exists"):
        startup.run_portable_startup_smoke(package, workspace)

    (package / "Sector.exe").unlink()
    with pytest.raises(startup.PortableStartupError, match="containing Sector.exe"):
        startup.run_portable_startup_smoke(package, tmp_path / "other")


def test_startup_tool_has_no_release_authentication_or_signing_surface():
    text = Path(startup.__file__).read_text(encoding="utf-8")
    for removed in (
        "verify_portable_distribution",
        "safe_extract_portable_archive",
        "source_revision",
        "archive_sha256",
        "JobObject",
        "certificate",
        "signature",
    ):
        assert removed not in text
