"""Controlled portable-startup tests without launching Sector or a browser."""

from __future__ import annotations

import ctypes
import json
import pathlib
from typing import ClassVar

import pytest

from tools import verify_portable_startup as startup


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
        self.request_call = None
        self.closed = False
        self.__class__.instances.append(self)

    def request(self, method: str, path: str, *, headers: dict[str, str]):
        self.request_call = (method, path, headers)

    def getresponse(self) -> _Response:
        return _Response(self.status, self.body)

    def close(self) -> None:
        self.closed = True


def test_health_request_is_literal_loopback_without_proxy_or_redirect(monkeypatch):
    _Connection.instances.clear()
    _Connection.status = 200
    _Connection.body = b"ok"
    monkeypatch.setattr(startup.http.client, "HTTPConnection", _Connection)

    assert startup._request_health(54321, 0.5) == b"ok"

    connection = _Connection.instances[-1]
    assert connection.host == "127.0.0.1"
    assert connection.port == 54321
    assert connection.request_call == (
        "GET",
        "/_stcore/health",
        {"Accept": "text/plain", "Connection": "close"},
    )
    assert connection.closed is True

    _Connection.status = 302
    _Connection.body = b"ok"
    with pytest.raises(startup.PortableStartupError, match="redirects are rejected"):
        startup._request_health(54321, 0.5)


@pytest.mark.parametrize("body", [b"", b"OK", b"ok\n", b"okay"])
def test_health_request_rejects_every_nonexact_body(monkeypatch, body):
    _Connection.status = 200
    _Connection.body = body
    monkeypatch.setattr(startup.http.client, "HTTPConnection", _Connection)

    with pytest.raises(startup.PortableStartupError, match="exactly b'ok'"):
        startup._request_health(54321, 0.5)


def test_nonloopback_discovery_filters_loopback_unspecified_and_duplicates(
    monkeypatch,
):
    records = [
        (None, None, None, None, ("127.0.0.1", 0)),
        (None, None, None, None, ("0.0.0.0", 0)),
        (None, None, None, None, ("10.20.30.40", 0)),
        (None, None, None, None, ("10.20.30.40", 0)),
        (None, None, None, None, ("192.168.1.5", 0)),
    ]
    monkeypatch.setattr(startup.socket, "gethostname", lambda: "sector-runner")
    monkeypatch.setattr(startup.socket, "getaddrinfo", lambda *args, **kwargs: records)

    assert startup._discover_nonloopback_ipv4() == (
        "10.20.30.40",
        "192.168.1.5",
    )


def test_loopback_boundary_rejects_a_wildcard_bind_adversary(monkeypatch):
    checked: list[tuple[str, int]] = []
    monkeypatch.setattr(
        startup,
        "_discover_nonloopback_ipv4",
        lambda: ("10.20.30.40", "192.168.1.5"),
    )

    def accepts(address: str, port: int) -> bool:
        checked.append((address, port))
        return address == "192.168.1.5"

    monkeypatch.setattr(startup, "_address_accepts_connection", accepts)

    with pytest.raises(startup.PortableStartupError, match="non-loopback address"):
        startup._assert_loopback_only(54321)
    assert checked == [("10.20.30.40", 54321), ("192.168.1.5", 54321)]


def test_loopback_boundary_records_every_closed_nonloopback_address(monkeypatch):
    addresses = ("10.20.30.40", "192.168.1.5")
    monkeypatch.setattr(startup, "_discover_nonloopback_ipv4", lambda: addresses)
    monkeypatch.setattr(
        startup, "_address_accepts_connection", lambda address, port: False
    )

    assert startup._assert_loopback_only(54321) == addresses


class _Job:
    def __init__(self, events: list[str]):
        self.events = events
        self.returncode = None
        self.pid = 4242

    def poll(self):
        return self.returncode

    def owns_pid(self, process_id: int) -> bool:
        return process_id in {self.pid, 4243}

    def terminate_and_wait(self, timeout_seconds: float):
        assert timeout_seconds == startup._TERMINATE_TIMEOUT_SECONDS
        self.events.append("terminate-job")
        self.returncode = 0


def _mock_portable_launch(tmp_path: pathlib.Path, monkeypatch, events: list[str]):
    source_root = tmp_path / "verified source"
    source_root.mkdir()
    source_revision = "a" * 40
    distribution = tmp_path / "portable distribution"
    distribution.mkdir()
    archive = distribution / "Sector-v0.92-windows-portable-unsigned.zip"
    archive.write_bytes(b"unit-test archive marker")
    archive_sha256 = "b" * 64
    workspace = tmp_path / "startup workspace"

    def verify(selected_root, selected_revision, selected_distribution):
        events.append("verify-distribution")
        assert selected_root == source_root
        assert selected_revision == source_revision
        assert selected_distribution == distribution
        return archive, archive_sha256

    def safe_extract(
        selected_archive: pathlib.Path,
        output: pathlib.Path,
        expected_sha256: str,
    ):
        events.append("safe-extract")
        assert selected_archive == archive
        assert expected_sha256 == archive_sha256
        package = output / "Sector-v0.92-windows-portable-unsigned"
        package.mkdir(parents=True)
        (package / "Sector.exe").write_bytes(b"not launched")
        return package

    process = _Job(events)
    launch_call = {}

    def launch(executable, cwd, environment, stdout_log, stderr_log):
        events.append("spawn")
        launch_call.update(
            {
                "executable": executable,
                "cwd": cwd,
                "environment": dict(environment),
                "stdout_name": pathlib.Path(stdout_log.name),
                "stderr_name": pathlib.Path(stderr_log.name),
            }
        )
        return process

    monkeypatch.setattr(startup, "_verify_portable_distribution", verify)
    monkeypatch.setattr(startup, "_safe_extract_portable_archive", safe_extract)
    monkeypatch.setattr(startup, "_select_loopback_port", lambda: 54321)
    monkeypatch.setattr(startup, "_launch_owned_job", launch)
    monkeypatch.setattr(
        startup,
        "_wait_for_health",
        lambda selected, port, timeout: events.append("health") or (b"ok", 4243),
    )
    monkeypatch.setattr(
        startup,
        "_assert_loopback_only",
        lambda port: events.append("loopback-boundary") or ("10.20.30.40",),
    )
    monkeypatch.setattr(
        startup,
        "_wait_for_port_closed",
        lambda port: events.append("port-closed"),
    )
    return (
        source_root,
        source_revision,
        distribution,
        workspace,
        process,
        launch_call,
    )


def test_startup_smoke_safely_extracts_checks_and_cleans_up(tmp_path, monkeypatch):
    events: list[str] = []
    source_root, revision, distribution, workspace, process, launch_call = (
        _mock_portable_launch(
        tmp_path, monkeypatch, events
        )
    )

    evidence = startup.run_portable_startup_smoke(
        source_root,
        revision,
        distribution,
        workspace,
        timeout_seconds=30,
    )

    assert events.index("verify-distribution") < events.index("safe-extract")
    assert events.index("safe-extract") < events.index("spawn")
    assert events.index("health") < events.index("loopback-boundary")
    assert events.index("loopback-boundary") < events.index("terminate-job")
    assert events.index("terminate-job") < events.index("port-closed")
    assert process.returncode == 0
    assert launch_call["executable"] == (
        workspace
        / "extracted"
        / "Sector-v0.92-windows-portable-unsigned"
        / "Sector.exe"
    )
    assert launch_call["cwd"] == launch_call["executable"].parent
    environment = launch_call["environment"]
    assert environment["SECTOR_HEADLESS"] == "1"
    assert environment["SECTOR_PORT"] == "54321"
    assert pathlib.Path(environment["LOCALAPPDATA"]).is_relative_to(workspace)
    assert pathlib.Path(environment["APPDATA"]).is_relative_to(workspace)
    assert pathlib.Path(environment["TEMP"]).is_relative_to(workspace)
    assert pathlib.Path(environment["TMP"]).is_relative_to(workspace)
    assert pathlib.Path(environment["USERPROFILE"]).is_relative_to(workspace)
    assert pathlib.Path(environment["SECTOR_AUTOSAVE_DIR"]).is_relative_to(
        workspace
    )
    assert pathlib.Path(environment["NUMBA_CACHE_DIR"]).is_relative_to(workspace)
    assert evidence.address == "127.0.0.1"
    assert evidence.archive_sha256 == "b" * 64
    assert evidence.health_body == "ok"
    assert evidence.listener_pid == 4243
    assert evidence.nonloopback_addresses_checked == ("10.20.30.40",)

    receipt = json.loads((workspace / "startup-smoke.json").read_text("ascii"))
    assert receipt["address"] == "127.0.0.1"
    assert receipt["archive_sha256"] == "b" * 64
    assert receipt["health_body"] == "ok"
    assert receipt["listener_pid"] == 4243
    assert receipt["nonloopback_addresses_checked"] == ["10.20.30.40"]
    assert (workspace / "Sector-startup-stdout.log").is_file()
    assert (workspace / "Sector-startup-stderr.log").is_file()


def test_startup_failure_still_stops_owned_process_and_checks_port(
    tmp_path, monkeypatch
):
    events: list[str] = []
    source_root, revision, distribution, workspace, process, _call = (
        _mock_portable_launch(
        tmp_path, monkeypatch, events
        )
    )

    def fail_health(selected, port, timeout):
        events.append("health-failed")
        raise startup.PortableStartupError("health refused")

    monkeypatch.setattr(startup, "_wait_for_health", fail_health)

    with pytest.raises(startup.PortableStartupError, match="health refused"):
        startup.run_portable_startup_smoke(
            source_root,
            revision,
            distribution,
            workspace,
            timeout_seconds=30,
        )

    assert process.returncode == 0
    assert events.index("health-failed") < events.index("terminate-job")
    assert events.index("terminate-job") < events.index("port-closed")
    assert (workspace / "Sector-startup-stdout.log").is_file()
    assert (workspace / "Sector-startup-stderr.log").is_file()


def test_existing_workspace_is_preserved_before_extraction(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    source_root.mkdir()
    distribution = tmp_path / "distribution"
    distribution.mkdir()
    archive = distribution / "portable.zip"
    archive.write_bytes(b"marker")
    workspace = tmp_path / "preserve"
    workspace.mkdir()
    marker = workspace / "user.txt"
    marker.write_text("keep", encoding="ascii")
    monkeypatch.setattr(
        startup,
        "_verify_portable_distribution",
        lambda root, revision, output: (archive, "b" * 64),
    )
    monkeypatch.setattr(
        startup,
        "_safe_extract_portable_archive",
        lambda archive, output, expected_sha256: pytest.fail(
            "extractor must not run"
        ),
    )

    with pytest.raises(startup.PortableStartupError, match="already exists"):
        startup.run_portable_startup_smoke(
            source_root, "a" * 40, distribution, workspace
        )
    assert marker.read_text(encoding="ascii") == "keep"


def test_distribution_verification_precedes_workspace_extraction_and_spawn(
    tmp_path, monkeypatch
):
    source_root = tmp_path / "source"
    source_root.mkdir()
    distribution = tmp_path / "distribution"
    distribution.mkdir()
    workspace = tmp_path / "must-not-exist"
    events: list[str] = []

    def reject_distribution(root, revision, output):
        events.append("verify-rejected")
        raise startup.PortableStartupError("distribution changed")

    monkeypatch.setattr(
        startup, "_verify_portable_distribution", reject_distribution
    )
    monkeypatch.setattr(
        startup,
        "_safe_extract_portable_archive",
        lambda *args, **kwargs: pytest.fail("extractor must not run"),
    )
    monkeypatch.setattr(
        startup,
        "_launch_owned_job",
        lambda *args, **kwargs: pytest.fail("process must not start"),
    )

    with pytest.raises(startup.PortableStartupError, match="distribution changed"):
        startup.run_portable_startup_smoke(
            source_root, "a" * 40, distribution, workspace
        )

    assert events == ["verify-rejected"]
    assert not workspace.exists()


def test_child_environment_is_allowlisted_and_uses_only_isolated_writable_dirs(
    tmp_path, monkeypatch
):
    hostile = {
        "GITHUB_ENV": str(tmp_path / "github-env"),
        "GITHUB_WORKSPACE": str(tmp_path / "repository"),
        "SECTOR_PORTABLE_EVIDENCE_ROOT": str(tmp_path / "evidence"),
        "SECTOR_SOURCE_REVISION": "a" * 40,
        "PIP_INDEX_URL": "https://secret.invalid/token",
        "GH_PAT": "secret",
        "ARBITRARY_SECRET_NAME": "secret",
    }
    for name, value in hostile.items():
        monkeypatch.setenv(name, value)
    workspace = tmp_path / "smoke"
    workspace.mkdir()

    environment = startup._create_child_environment(workspace, 54321)

    assert not set(hostile).intersection(environment)
    expected_names = set(startup._INHERITED_CHILD_ENV) | {
        "APPDATA",
        "LOCALAPPDATA",
        "NUMBA_CACHE_DIR",
        "SECTOR_AUTOSAVE_DIR",
        "SECTOR_HEADLESS",
        "SECTOR_PORT",
        "TEMP",
        "TMP",
        "USERPROFILE",
    }
    assert set(environment) <= expected_names
    assert environment["SECTOR_HEADLESS"] == "1"
    assert environment["SECTOR_PORT"] == "54321"
    for name in (
        "APPDATA",
        "LOCALAPPDATA",
        "NUMBA_CACHE_DIR",
        "SECTOR_AUTOSAVE_DIR",
        "TEMP",
        "TMP",
        "USERPROFILE",
    ):
        path = pathlib.Path(environment[name])
        assert path.is_relative_to(workspace)
        assert path.is_dir()


def test_windows_environment_block_is_sorted_and_rejects_case_collisions():
    assert startup._windows_environment_block({"z": "2", "A": "1"}) == (
        "A=1\0z=2\0\0"
    )
    with pytest.raises(startup.PortableStartupError, match="valid Windows block"):
        startup._windows_environment_block({"Path": "one", "PATH": "two"})


class _HandleListKernel32:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.allowed_handles: tuple[int, ...] = ()

    def InitializeProcThreadAttributeList(
        self, attribute_list, count, flags, size_pointer
    ):
        assert count == 1
        assert flags == 0
        size = ctypes.cast(
            size_pointer, ctypes.POINTER(ctypes.c_size_t)
        ).contents
        if not attribute_list:
            size.value = 256
            ctypes.set_last_error(startup._ERROR_INSUFFICIENT_BUFFER)
            self.events.append("size-handle-list")
            return False
        assert size.value == 256
        self.events.append("initialise-handle-list")
        return True

    def UpdateProcThreadAttribute(
        self,
        attribute_list,
        flags,
        attribute,
        value,
        value_size,
        previous_value,
        return_size,
    ):
        assert attribute_list
        assert flags == 0
        assert attribute == startup._PROC_THREAD_ATTRIBUTE_HANDLE_LIST
        assert previous_value is None
        assert return_size is None
        handle_count = value_size // ctypes.sizeof(startup.wintypes.HANDLE)
        assert handle_count == 3
        handle_type = startup.wintypes.HANDLE * handle_count
        handles = ctypes.cast(value, ctypes.POINTER(handle_type)).contents
        self.allowed_handles = tuple(int(handle) for handle in handles)
        self.events.append("update-handle-list")
        return True

    def DeleteProcThreadAttributeList(self, attribute_list):
        assert attribute_list
        self.events.append("delete-handle-list")

    def CreateProcessW(
        self,
        application,
        command_line,
        process_attributes,
        thread_attributes,
        inherit_handles,
        creation_flags,
        environment,
        cwd,
        startup_pointer,
        process_pointer,
    ):
        assert application.endswith("Sector.exe")
        assert command_line
        assert process_attributes is None
        assert thread_attributes is None
        assert inherit_handles is True
        assert creation_flags & startup._CREATE_SUSPENDED
        assert creation_flags & startup._CREATE_UNICODE_ENVIRONMENT
        assert creation_flags & startup._EXTENDED_STARTUPINFO_PRESENT
        assert environment
        assert cwd
        extended = ctypes.cast(
            startup_pointer, ctypes.POINTER(startup._STARTUPINFOEXW)
        ).contents
        assert extended.StartupInfo.cb == ctypes.sizeof(startup._STARTUPINFOEXW)
        assert extended.StartupInfo.dwFlags == startup._STARTF_USESTDHANDLES
        assert extended.lpAttributeList
        process = ctypes.cast(
            process_pointer, ctypes.POINTER(startup._PROCESS_INFORMATION)
        ).contents
        process.hProcess = 202
        process.hThread = 303
        process.dwProcessId = 4242
        process.dwThreadId = 4243
        self.events.append("create-suspended-process")
        return True


def test_native_launch_inherits_only_the_three_explicit_standard_handles(
    tmp_path, monkeypatch
):
    kernel32 = _HandleListKernel32()
    api = object.__new__(startup._WindowsApi)
    api._kernel32 = kernel32
    issued_handles: list[int] = []
    inheritable_events: list[tuple[int, bool]] = []

    def fake_os_handle(file_descriptor: int) -> int:
        handle = 1000 + len(issued_handles)
        issued_handles.append(handle)
        return handle

    monkeypatch.setattr(startup.msvcrt, "get_osfhandle", fake_os_handle)
    monkeypatch.setattr(startup.os, "get_handle_inheritable", lambda handle: False)
    monkeypatch.setattr(
        startup.os,
        "set_handle_inheritable",
        lambda handle, value: inheritable_events.append((handle, value)),
    )
    executable = tmp_path / "Sector.exe"
    executable.write_bytes(b"not executed")
    stdout = tmp_path / "stdout.log"
    stderr = tmp_path / "stderr.log"

    with stdout.open("xb") as stdout_log, stderr.open("xb") as stderr_log:
        created = api.create_suspended_process(
            executable,
            tmp_path,
            {"SECTOR_HEADLESS": "1"},
            stdout_log,
            stderr_log,
        )

    assert created == startup._CreatedProcess(202, 303, 4242)
    assert kernel32.allowed_handles == tuple(issued_handles)
    assert kernel32.events == [
        "size-handle-list",
        "initialise-handle-list",
        "update-handle-list",
        "create-suspended-process",
        "delete-handle-list",
    ]
    assert inheritable_events == [
        *((handle, True) for handle in issued_handles),
        *((handle, False) for handle in reversed(issued_handles)),
    ]


class _FakeWindowsApi:
    def __init__(self):
        self.events: list[str] = []
        self.exit_code: int | None = None

    def create_kill_on_close_job(self):
        self.events.append("create-kill-on-close-job")
        return 101

    def create_suspended_process(
        self, executable, cwd, environment, stdout_log, stderr_log
    ):
        self.events.append("create-suspended-process")
        assert executable.name == "Sector.exe"
        assert cwd == executable.parent
        assert environment["SECTOR_HEADLESS"] == "1"
        assert stdout_log.writable()
        assert stderr_log.writable()
        return startup._CreatedProcess(202, 303, 4242)

    def assign_process_to_job(self, job, process):
        assert (job, process) == (101, 202)
        self.events.append("assign-before-resume")

    def resume_thread(self, thread):
        assert thread == 303
        self.events.append("resume-thread")

    def terminate_process(self, process):
        self.events.append(f"terminate-process-{process}")

    def terminate_job(self, job):
        assert job == 101
        self.events.append("terminate-whole-job")

    def wait_for_handle(self, handle, timeout_seconds):
        self.events.append(f"wait-handle-{handle}")

    def process_exit_code(self, process):
        assert process == 202
        return self.exit_code

    def process_is_in_job(self, process_id, job):
        return process_id in {4242, 4243} and job == 101

    def close_handle(self, handle):
        self.events.append(f"close-handle-{handle}")


def _launch_fake_windows_job(tmp_path, api):
    executable = tmp_path / "Sector.exe"
    executable.write_bytes(b"not executed")
    stdout = tmp_path / "stdout.log"
    stderr = tmp_path / "stderr.log"
    with stdout.open("xb") as stdout_log, stderr.open("xb") as stderr_log:
        return startup._WindowsJobProcess.launch(
            api,
            executable,
            tmp_path,
            {"SECTOR_HEADLESS": "1"},
            stdout_log,
            stderr_log,
        )


def test_job_launch_assigns_suspended_process_before_resume(tmp_path):
    api = _FakeWindowsApi()

    process = _launch_fake_windows_job(tmp_path, api)

    assert process.pid == 4242
    assert api.events == [
        "create-kill-on-close-job",
        "create-suspended-process",
        "assign-before-resume",
        "resume-thread",
        "close-handle-303",
    ]


def test_assignment_failure_never_resumes_and_cleans_exact_process_handles(tmp_path):
    class RejectAssignment(_FakeWindowsApi):
        def assign_process_to_job(self, job, process):
            self.events.append("reject-assignment")
            raise startup.PortableStartupError("assignment rejected")

    api = RejectAssignment()

    with pytest.raises(startup.PortableStartupError, match="assignment rejected"):
        _launch_fake_windows_job(tmp_path, api)

    assert "resume-thread" not in api.events
    assert api.events == [
        "create-kill-on-close-job",
        "create-suspended-process",
        "reject-assignment",
        "terminate-process-202",
        "wait-handle-202",
        "close-handle-303",
        "close-handle-202",
        "close-handle-101",
    ]


def test_cleanup_waits_and_closes_whole_job_even_after_root_exits(tmp_path):
    api = _FakeWindowsApi()
    process = _launch_fake_windows_job(tmp_path, api)
    api.exit_code = 0
    assert process.poll() == 0

    process.terminate_and_wait(10.0)

    assert api.events[-4:] == [
        "terminate-whole-job",
        "wait-handle-101",
        "close-handle-202",
        "close-handle-101",
    ]
    assert "taskkill" not in (startup.__doc__ or "").casefold()
    source = pathlib.Path(startup.__file__).read_text(encoding="utf-8").casefold()
    assert "taskkill" not in source
    assert "subprocess.run" not in source


def test_health_requires_same_owned_tcp_listener_before_and_after(monkeypatch):
    events: list[str] = []
    process = _Job(events)
    owners = iter(((4243,), (4243,)))
    monkeypatch.setattr(startup, "_listener_owner_pids", lambda port: next(owners))
    monkeypatch.setattr(startup, "_request_health", lambda port, timeout: b"ok")

    assert startup._wait_for_health(process, 54321, 1.0) == (b"ok", 4243)


def test_health_rejects_listener_outside_owned_job_before_request(monkeypatch):
    process = _Job([])
    monkeypatch.setattr(startup, "_listener_owner_pids", lambda port: (9999,))
    monkeypatch.setattr(
        startup,
        "_request_health",
        lambda port, timeout: pytest.fail("unowned listener must not be queried"),
    )

    with pytest.raises(startup.PortableStartupError, match="not uniquely owned"):
        startup._wait_for_health(process, 54321, 1.0)


def test_health_rejects_owned_listener_pid_change_during_response(monkeypatch):
    class OwnsBoth(_Job):
        def owns_pid(self, process_id: int) -> bool:
            return process_id in {4243, 4244}

    process = OwnsBoth([])
    owners = iter(((4243,), (4244,)))
    monkeypatch.setattr(startup, "_listener_owner_pids", lambda port: next(owners))
    monkeypatch.setattr(startup, "_request_health", lambda port, timeout: b"ok")

    with pytest.raises(startup.PortableStartupError, match="ownership changed"):
        startup._wait_for_health(process, 54321, 1.0)
