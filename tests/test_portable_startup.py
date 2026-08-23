"""Tests for the practical packaged first-page smoke."""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import pytest
from streamlit.testing.v1 import AppTest

from tools import verify_portable_startup as startup

APP = Path(__file__).resolve().parents[1] / "app" / "sector_app.py"


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


def test_button_group_protocol_roundtrip_matches_browser_widget_state():
    option_brief = _bytes_field(1, b"Brief")
    option_standard = _bytes_field(1, b"Standard")
    group = b"".join(
        (
            _bytes_field(1, b"$$ID-profile-rep_report_content"),
            _bytes_field(2, option_brief),
            _bytes_field(2, option_standard),
            _bytes_field(11, b"Report profile"),
            _bytes_field(14, b"Standard"),
        )
    )
    forward = _bytes_field(5, _bytes_field(3, _bytes_field(55, group)))

    assert startup._page_button_groups(forward) == (
        startup._ButtonGroupEvidence(
            widget_id="$$ID-profile-rep_report_content",
            label="Report profile",
            options=("Brief", "Standard"),
            selected=("Standard",),
        ),
    )

    string_array = _bytes_field(1, b"Hostile stale value")
    widget = _bytes_field(1, b"$$ID-profile-rep_report_content") + _bytes_field(
        9, string_array
    )
    expected_backmsg = _bytes_field(
        11,
        _bytes_field(2, _bytes_field(1, widget)),
    )
    assert startup._widget_rerun_backmsg(
        (("$$ID-profile-rep_report_content", "Hostile stale value"),)
    ) == expected_backmsg

    tab_widget = _bytes_field(1, b"$$ID-input-tabs") + _bytes_field(
        6, b"Project"
    )
    assert startup._string_widget_rerun_backmsg(
        (("$$ID-input-tabs", "Project"),)
    ) == _bytes_field(11, _bytes_field(2, _bytes_field(1, tab_widget)))


def test_page_protocol_extracts_project_notice_and_stateful_tabs():
    alert = _bytes_field(1, b"Restored autosaved session.") + _varint(
        (2 << 3) | 0
    ) + _varint(4)
    alert_forward = _bytes_field(5, _bytes_field(3, _bytes_field(30, alert)))
    # Proto3 omits the zero-valued default index on the actual wire.
    tab = _bytes_field(2, b"$$ID-input-tabs")
    tab_forward = _bytes_field(5, _bytes_field(6, _bytes_field(6, tab)))

    assert startup._page_alerts(alert_forward) == (
        (4, "Restored autosaved session."),
    )
    assert startup._page_tab_containers(tab_forward) == (
        ("$$ID-input-tabs", 0),
    )


@pytest.mark.parametrize(
    ("scenario", "alert"),
    [
        (
            startup._LEGACY_SCENARIO,
            (4, startup._AUTOSAVE_RESTORED_TEXT),
        ),
        (
            startup._HOSTILE_SCENARIO,
            (
                1,
                (
                    f"{startup._AUTOSAVE_REJECTED_PREFIX} "
                    f"'{startup._HOSTILE_REPORT_PROFILE}'. Starting with the "
                    "default section."
                ),
            ),
        ),
    ],
)
def test_page_session_requires_pre_widget_autosave_notice_and_standard_profile(
    monkeypatch, scenario, alert
):
    workspace = startup._ButtonGroupEvidence(
        "workspace-id",
        "Workspace",
        ("Inputs", "Analysis", "Report"),
        ("Inputs",),
    )
    report_profile = startup._ButtonGroupEvidence(
        "profile-id",
        "Report profile",
        ("Brief", "Standard", "Audit"),
        ("Standard",),
    )
    first_surface = startup._PageSurfaceEvidence(
        button_groups={"Workspace": workspace},
        alerts=(),
        tab_containers={"input-tabs-id": 0},
    )
    project_surface = startup._PageSurfaceEvidence(
        button_groups={"Workspace": workspace},
        alerts=(alert,),
        tab_containers={"input-tabs-id": 4},
    )
    report_surface = startup._PageSurfaceEvidence(
        button_groups={
            "Workspace": workspace,
            "Report profile": report_profile,
        },
        alerts=(),
        tab_containers={},
    )
    runs = iter(
        (
            (startup._PageExecutionEvidence(10, "finished-successfully"), first_surface),
            (startup._PageExecutionEvidence(5, "finished-successfully"), project_surface),
            (startup._PageExecutionEvidence(6, "finished-successfully"), report_surface),
        )
    )
    backmsgs = []

    class FakeConnection:
        def settimeout(self, _timeout):
            return None

        def sendall(self, _payload):
            return None

        def close(self):
            return None

    connection = FakeConnection()
    monkeypatch.setattr(
        startup.socket,
        "create_connection",
        lambda *_args, **_kwargs: connection,
    )
    monkeypatch.setattr(startup, "_websocket_handshake", lambda *_args: None)
    monkeypatch.setattr(
        startup,
        "_execute_page_run",
        lambda _process, _connection, _reader, _deadline, backmsg,
        **_kwargs: (backmsgs.append(backmsg), next(runs))[1],
    )

    evidence = startup._run_page_session(
        _FakeProcess([]), 54321, 30, scenario
    )

    assert evidence == startup._PageExecutionEvidence(21, "finished-successfully")
    assert backmsgs == [
        startup._PAGE_RERUN_BACKMSG,
        startup._string_widget_rerun_backmsg(
            (("input-tabs-id", "Project"),)
        ),
        startup._widget_rerun_backmsg((("workspace-id", "Report"),)),
    ]


@pytest.mark.parametrize(
    "persisted_profile",
    ["Default report", "Unknown pre-v0.94 report profile"],
)
def test_exact_entrypoint_recovers_legacy_or_hostile_profile_on_startup(
    persisted_profile, tmp_path, monkeypatch
):
    """The package gate seeds this same durable file before process launch."""

    state = tmp_path / "state"
    state.mkdir()
    (state / startup._AUTOSAVE_NAME).write_bytes(
        startup._autosave_payload(persisted_profile)
    )
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(state))

    app = AppTest.from_file(str(APP), default_timeout=90)
    app.session_state["_input_tab"] = "Project"

    app.run()

    assert not app.exception
    if persisted_profile == startup._LEGACY_REPORT_PROFILE:
        assert startup._AUTOSAVE_RESTORED_TEXT in [item.value for item in app.success]
    else:
        assert any(
            item.value.startswith(startup._AUTOSAVE_REJECTED_PREFIX)
            and startup._HOSTILE_REPORT_PROFILE in item.value
            for item in app.error
        )

    app.segmented_control(key="_main_page").set_value("Report").run()

    assert not app.exception
    assert app.segmented_control(key="rep_report_content").value == "Standard"
    assert app.session_state["rep_report_content"] == "Standard"
    assert app.session_state["_durable_report_scalars"][
        "rep_report_content"
    ] == "Standard"


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
    package = tmp_path / "Sector-v0.96-windows-portable"
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
    ports = iter((54321, 54322))
    monkeypatch.setattr(startup, "_select_loopback_port", lambda: next(ports))
    monkeypatch.setattr(
        startup, "_wait_for_health", lambda process, port, timeout: b"ok"
    )
    monkeypatch.setattr(
        startup,
        "_run_page_session",
        lambda process, port, timeout, scenario: startup._PageExecutionEvidence(
            118 if scenario == startup._LEGACY_SCENARIO else 120,
            "finished-successfully",
        ),
    )

    evidence = startup.run_portable_startup_smoke(
        package, workspace, timeout_seconds=30
    )

    assert len(_FakeProcess.instances) == 2
    for process, expected_port, expected_profile in zip(
        _FakeProcess.instances,
        ("54321", "54322"),
        (startup._LEGACY_REPORT_PROFILE, startup._HOSTILE_REPORT_PROFILE),
        strict=True,
    ):
        assert process.arguments == [str(package / "Sector.exe")]
        assert process.kwargs["cwd"] == package
        environment = process.kwargs["env"]
        assert environment["SECTOR_HEADLESS"] == "1"
        assert environment["SECTOR_PORT"] == expected_port
        autosave = Path(environment["SECTOR_AUTOSAVE_DIR"]) / "autosave.json"
        assert json.loads(autosave.read_text("ascii"))["presentation"][
            "rep_report_content"
        ] == expected_profile
        assert process.terminated is True
    assert evidence.health_status == "ok"
    assert evidence.page_status == "finished-successfully"
    assert evidence.page_message_count == 238
    assert [item.name for item in evidence.scenarios] == [
        startup._LEGACY_SCENARIO,
        startup._HOSTILE_SCENARIO,
    ]
    receipt = json.loads((workspace / "startup-smoke.json").read_text("ascii"))
    assert receipt["page_status"] == "finished-successfully"
    for scenario in (startup._LEGACY_SCENARIO, startup._HOSTILE_SCENARIO):
        assert (workspace / scenario / "Sector-startup-stdout.log").is_file()
        assert (workspace / scenario / "Sector-startup-stderr.log").is_file()


def test_page_failure_still_terminates_process(tmp_path, monkeypatch):
    package = _package(tmp_path)
    workspace = tmp_path / "smoke"
    _FakeProcess.instances.clear()
    monkeypatch.setattr(startup.subprocess, "Popen", _FakeProcess)
    monkeypatch.setattr(startup, "_select_loopback_port", lambda: 54321)
    monkeypatch.setattr(
        startup, "_wait_for_health", lambda process, port, timeout: b"ok"
    )

    def fail_page(process, port, timeout, scenario):
        del process, port, timeout, scenario
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
