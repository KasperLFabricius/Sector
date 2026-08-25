"""Launch a built Sector package and execute its critical Streamlit startup path."""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import json
import os
import socket
import struct
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import cast

_LOOPBACK = "127.0.0.1"
_HEALTH_PATH = "/_stcore/health"
_HEALTH_BODY = b"ok"
_PAGE_STREAM_PATH = "/_stcore/stream"
_PAGE_RERUN_BACKMSG = b"\x5a\x00"
_PAGE_SUCCESS_STATUS = 0
_PAGE_EARLY_RERUN_STATUS = 2
_PAGE_FRAGMENT_SUCCESS_STATUS = 3
_WORKSPACE_LABEL = "Workspace"
_INPUT_WORKSPACE = "Inputs"
_REPORT_WORKSPACE = "Report"
_REPORT_PROFILE_LABEL = "Report profile"
_REPORT_PROFILE_DEFAULT = "Standard"
_SECTION_TAB_LABEL = "2 \u00b7 Section"
_PROJECT_TAB_LABEL = "Project"
_PROJECT_DOWNLOAD_LABEL = "Download project"
_USER_MANUAL_BUTTON_LABEL = "User manual"
_MANUAL_GENERATE_BUTTON_LABEL = "Generate PDF"
_MANUAL_CLOSE_BUTTON_LABEL = "Close"
_MANUAL_PDF_DOWNLOAD_LABEL = "Download PDF"
_MANUAL_HTML_DOWNLOAD_LABEL = "Download accessible HTML"
_REPORT_GENERATE_BUTTON_LABEL = "Generate report"
_REPORT_DOWNLOAD_LABEL = "Download report (PDF)"
_LEGACY_REPORT_PROFILE = "Default report"
_HOSTILE_REPORT_PROFILE = "Unknown pre-v0.94 report profile"
_LEGACY_SCENARIO = "legacy-report-profile"
_HOSTILE_SCENARIO = "hostile-report-profile"
_AUTOSAVE_NAME = "autosave.json"
_CURRENT_PROJECT_VERSION = 27
_AUTOSAVE_RESTORED_TEXT = "Restored autosaved session."
_AUTOSAVE_REJECTED_PREFIX = "Autosave not restored: the saved report type"
_AUTOSAVE_REJECTED_TEXT = (
    f"{_AUTOSAVE_REJECTED_PREFIX} is not available in this version of Sector. "
    "Starting with the default section."
)
_MAX_WEBSOCKET_HEADERS = 16 * 1024
_MAX_WEBSOCKET_FRAME = 16 * 1024 * 1024
_MAX_PAGE_MESSAGES = 4096
_MAX_PAGE_BYTES = 64 * 1024 * 1024
_TERMINATE_TIMEOUT_SECONDS = 10.0


class PortableStartupError(RuntimeError):
    """The built application did not start and render correctly."""


@dataclass(frozen=True)
class PortableStartupEvidence:
    package_folder: str
    executable: str
    address: str
    health_status: str
    page_status: str
    page_message_count: int
    scenarios: tuple[PortableStartupScenarioEvidence, ...]


@dataclass(frozen=True)
class PortableStartupScenarioEvidence:
    name: str
    persisted_report_profile: str
    port: int
    health_status: str
    page_status: str
    page_message_count: int
    stdout_log: str
    stderr_log: str
    product_probes: tuple[str, ...] = ()


@dataclass(frozen=True)
class _PageExecutionEvidence:
    message_count: int
    status: str
    product_probes: tuple[str, ...] = ()


@dataclass(frozen=True)
class _ButtonGroupEvidence:
    widget_id: str
    label: str
    options: tuple[str, ...]
    selected: tuple[str, ...]


@dataclass(frozen=True)
class _ButtonEvidence:
    widget_id: str
    label: str
    disabled: bool


@dataclass(frozen=True)
class _DownloadEvidence:
    widget_id: str
    label: str
    disabled: bool
    has_file: bool


@dataclass(frozen=True)
class _DataframeEvidence:
    widget_id: str
    editing_mode: int


@dataclass(frozen=True)
class _BidiComponentEvidence:
    widget_id: str
    component_name: str
    has_json_data: bool


@dataclass(frozen=True)
class _PageSurfaceEvidence:
    button_groups: dict[str, _ButtonGroupEvidence]
    alerts: tuple[tuple[int, str], ...]
    tab_containers: dict[str, int]
    buttons: dict[str, _ButtonEvidence] = field(default_factory=dict)
    downloads: dict[str, _DownloadEvidence] = field(default_factory=dict)
    dataframes: dict[str, _DataframeEvidence] = field(default_factory=dict)
    bidi_components: dict[str, _BidiComponentEvidence] = field(
        default_factory=dict
    )


@dataclass(frozen=True)
class _ProtobufField:
    number: int
    wire_type: int
    value: int | bytes


class _SocketReader:
    def __init__(self, connection: socket.socket) -> None:
        self._connection = connection
        self._buffer = bytearray()

    def read_exact(self, size: int) -> bytes:
        if size < 0 or size > _MAX_WEBSOCKET_FRAME:
            raise PortableStartupError("page WebSocket frame size is invalid")
        while len(self._buffer) < size:
            block = self._connection.recv(min(64 * 1024, size - len(self._buffer)))
            if not block:
                raise PortableStartupError("page WebSocket closed unexpectedly")
            self._buffer.extend(block)
        value = bytes(self._buffer[:size])
        del self._buffer[:size]
        return value

    def read_headers(self) -> bytes:
        marker = b"\r\n\r\n"
        while marker not in self._buffer:
            if len(self._buffer) >= _MAX_WEBSOCKET_HEADERS:
                raise PortableStartupError("page WebSocket headers exceed the limit")
            block = self._connection.recv(4096)
            if not block:
                raise PortableStartupError("page WebSocket handshake closed early")
            self._buffer.extend(block)
        offset = self._buffer.index(marker) + len(marker)
        value = bytes(self._buffer[:offset])
        del self._buffer[:offset]
        return value


def _package_executable(package: Path) -> tuple[Path, Path]:
    folder = Path(os.path.abspath(package))
    executable = folder / "Sector.exe"
    if not folder.is_dir() or not executable.is_file():
        raise PortableStartupError("package must be a folder containing Sector.exe")
    return folder, executable


def _create_workspace(workspace: Path) -> Path:
    selected = Path(os.path.abspath(workspace))
    if os.path.lexists(selected):
        raise PortableStartupError(f"startup workspace already exists: {selected}")
    try:
        selected.mkdir(parents=True)
    except OSError as exc:
        raise PortableStartupError("cannot create startup workspace") from exc
    return selected


def _select_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind((_LOOPBACK, 0))
        address, port = reservation.getsockname()
        if address != _LOOPBACK or not 1 <= port <= 65535:
            raise PortableStartupError("could not reserve a loopback port")
        return int(port)


def _request_health(port: int, timeout_seconds: float) -> bytes:
    connection = http.client.HTTPConnection(
        _LOOPBACK, port=port, timeout=timeout_seconds
    )
    try:
        connection.request(
            "GET",
            _HEALTH_PATH,
            headers={"Accept": "text/plain", "Connection": "close"},
        )
        response = connection.getresponse()
        body = response.read(len(_HEALTH_BODY) + 1)
    finally:
        connection.close()
    if response.status != 200:
        raise PortableStartupError(
            f"health endpoint returned HTTP {response.status}; redirects are rejected"
        )
    if body != _HEALTH_BODY:
        raise PortableStartupError("health endpoint body is not exactly b'ok'")
    return body


def _wait_for_health(
    process: subprocess.Popen[bytes], port: int, timeout_seconds: float
) -> bytes:
    deadline = time.monotonic() + timeout_seconds
    last_error = "listener not ready"
    while time.monotonic() < deadline:
        if (returncode := process.poll()) is not None:
            raise PortableStartupError(
                f"Sector.exe exited before health succeeded (exit {returncode})"
            )
        try:
            return _request_health(port, min(1.0, timeout_seconds))
        except (OSError, PortableStartupError) as exc:
            last_error = str(exc)
            time.sleep(0.1)
    raise PortableStartupError(f"health endpoint did not become ready: {last_error}")


def _decode_varint(payload: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    for _index in range(10):
        if offset >= len(payload):
            raise PortableStartupError("page protobuf contains a truncated varint")
        current = payload[offset]
        offset += 1
        value |= (current & 0x7F) << shift
        if current < 0x80:
            return value, offset
        shift += 7
    raise PortableStartupError("page protobuf varint exceeds the 64-bit bound")


def _encode_varint(value: int) -> bytes:
    if value < 0:
        raise PortableStartupError("page protobuf varint cannot be negative")
    encoded = bytearray()
    while value >= 0x80:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _protobuf_bytes_field(number: int, payload: bytes) -> bytes:
    if number <= 0 or len(payload) > _MAX_WEBSOCKET_FRAME:
        raise PortableStartupError("page protobuf byte field is invalid")
    return (
        _encode_varint((number << 3) | 2)
        + _encode_varint(len(payload))
        + payload
    )


def _widget_rerun_backmsg(states: tuple[tuple[str, str], ...]) -> bytes:
    """Encode the same string-array widget state sent by a Streamlit browser."""

    widgets = bytearray()
    for widget_id, value in states:
        try:
            widget_id_bytes = widget_id.encode("utf-8")
            value_bytes = value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise PortableStartupError("page widget state is not UTF-8") from exc
        string_array = _protobuf_bytes_field(1, value_bytes)
        widget = (
            _protobuf_bytes_field(1, widget_id_bytes)
            + _protobuf_bytes_field(9, string_array)
        )
        widgets.extend(_protobuf_bytes_field(1, widget))
    client_state = _protobuf_bytes_field(2, bytes(widgets))
    return _protobuf_bytes_field(11, client_state)


def _string_widget_rerun_backmsg(states: tuple[tuple[str, str], ...]) -> bytes:
    """Encode ordinary string widget state, as used by stateful ``st.tabs``."""

    widgets = bytearray()
    for widget_id, value in states:
        try:
            widget_id_bytes = widget_id.encode("utf-8")
            value_bytes = value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise PortableStartupError("page widget state is not UTF-8") from exc
        widget = _protobuf_bytes_field(1, widget_id_bytes) + _protobuf_bytes_field(
            6, value_bytes
        )
        widgets.extend(_protobuf_bytes_field(1, widget))
    client_state = _protobuf_bytes_field(2, bytes(widgets))
    return _protobuf_bytes_field(11, client_state)


def _trigger_widget_rerun_backmsg(
    trigger_widget_id: str,
    *,
    string_arrays: tuple[tuple[str, str], ...] = (),
    strings: tuple[tuple[str, str], ...] = (),
) -> bytes:
    """Encode retained navigation state plus one browser-style button click."""

    widget_ids = [item[0] for item in (*string_arrays, *strings)]
    if trigger_widget_id in widget_ids or len(set(widget_ids)) != len(widget_ids):
        raise PortableStartupError("page widget state repeats an identity")
    widgets = bytearray()
    try:
        for widget_id, value in string_arrays:
            string_array = _protobuf_bytes_field(1, value.encode("utf-8"))
            widget = _protobuf_bytes_field(
                1, widget_id.encode("utf-8")
            ) + _protobuf_bytes_field(9, string_array)
            widgets.extend(_protobuf_bytes_field(1, widget))
        for widget_id, value in strings:
            widget = _protobuf_bytes_field(
                1, widget_id.encode("utf-8")
            ) + _protobuf_bytes_field(6, value.encode("utf-8"))
            widgets.extend(_protobuf_bytes_field(1, widget))
        trigger = (
            _protobuf_bytes_field(1, trigger_widget_id.encode("utf-8"))
            + _encode_varint((2 << 3) | 0)
            + _encode_varint(1)
        )
    except UnicodeEncodeError as exc:
        raise PortableStartupError("page widget state is not UTF-8") from exc
    widgets.extend(_protobuf_bytes_field(1, trigger))
    client_state = _protobuf_bytes_field(2, bytes(widgets))
    return _protobuf_bytes_field(11, client_state)


def _autosave_payload(report_profile: str) -> bytes:
    """Build a small valid current project with one raw profile value."""

    def table(columns: tuple[str, ...], rows: tuple[tuple, ...] = ()) -> dict:
        return {"columns": list(columns), "rows": [list(row) for row in rows]}

    content = {
        "tables": {
            "corners_base": table(
                ("x (mm)", "y (mm)"),
                (
                    (-200.0, -300.0),
                    (200.0, -300.0),
                    (200.0, 300.0),
                    (-200.0, 300.0),
                ),
            ),
            "hole_base": table(("x (mm)", "y (mm)")),
            "bars_base": table((
                "ID",
                "x (mm)",
                "y (mm)",
                "size mode",
                "area (mm2)",
                "diameter (mm)",
                "material ID",
                "fatigue detail ID",
            )),
            "tendons_base": table((
                "ID",
                "x (mm)",
                "y (mm)",
                "size mode",
                "area (mm2)",
                "diameter (mm)",
                "material ID",
                "fatigue detail ID",
            )),
            "plastic_cases_base": table((
                "name",
                "description",
                "n_ed_kn",
                "mx_ed_knm",
                "my_ed_knm",
                "vx_ed_kn",
                "vy_ed_kn",
                "vx_face",
                "vy_face",
                "t_ed_knm",
                "check_minimum_reinforcement",
            ), (
                (
                    "QA-1",
                    "Portable report gate",
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    "negative",
                    "positive",
                    0.0,
                    False,
                ),
            )),
            "elastic_cases_base": table((
                "name",
                "description",
                "n_long_ed_kn",
                "mx_long_ed_knm",
                "my_long_ed_knm",
                "n_short_ed_kn",
                "mx_short_ed_knm",
                "my_short_ed_knm",
                "calculate_crack_width",
            )),
            "fatigue_spectrum_base": table((
                "spectrum",
                "name",
                "description",
                "cycles",
                "n_long_ed_kn",
                "mx_long_ed_knm",
                "my_long_ed_knm",
                "n_short_ed_kn",
                "mx_short_ed_knm",
                "my_short_ed_knm",
            )),
        },
        "scalars": {
            "sls_long_term_permitted_crack_width_mm": 0.0,
            "sls_short_term_permitted_crack_width_mm": 0.0,
            "sls_heightened_permitted_crack_width_mm": 0.0,
        },
    }
    canonical = json.dumps(
        content, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    payload = {
        "format": "sector-project",
        "version": _CURRENT_PROJECT_VERSION,
        **content,
        "presentation": {
            "modelled_direction_alias": "",
            "rep_report_content": report_profile,
        },
        "provenance": {
            "sector_version": "0.93",
            "saved_at_utc": "2026-01-01T00:00:00+00:00",
            "input_sha256": hashlib.sha256(canonical).hexdigest(),
            "results_included": False,
        },
    }
    return (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("ascii")


def _protobuf_fields(payload: bytes) -> tuple[_ProtobufField, ...]:
    fields: list[_ProtobufField] = []
    offset = 0
    while offset < len(payload):
        tag, offset = _decode_varint(payload, offset)
        number, wire_type = tag >> 3, tag & 0x07
        if number <= 0:
            raise PortableStartupError("page protobuf field number is invalid")
        value: int | bytes
        if wire_type == 0:
            value, offset = _decode_varint(payload, offset)
        elif wire_type == 1:
            if offset + 8 > len(payload):
                raise PortableStartupError("page protobuf fixed64 field is truncated")
            value = payload[offset : offset + 8]
            offset += 8
        elif wire_type == 2:
            size, offset = _decode_varint(payload, offset)
            if size > _MAX_WEBSOCKET_FRAME or offset + size > len(payload):
                raise PortableStartupError("page protobuf byte field is invalid")
            value = payload[offset : offset + size]
            offset += size
        elif wire_type == 5:
            if offset + 4 > len(payload):
                raise PortableStartupError("page protobuf fixed32 field is truncated")
            value = payload[offset : offset + 4]
            offset += 4
        else:
            raise PortableStartupError("page protobuf uses an unsupported wire type")
        fields.append(_ProtobufField(number, wire_type, value))
    return tuple(fields)


def _nested_bytes(fields: tuple[_ProtobufField, ...], number: int) -> tuple[bytes, ...]:
    return tuple(
        cast(bytes, field.value)
        for field in fields
        if field.number == number and field.wire_type == 2
    )


def _utf8_fields(
    fields: tuple[_ProtobufField, ...], number: int, description: str
) -> tuple[str, ...]:
    try:
        return tuple(
            payload.decode("utf-8") for payload in _nested_bytes(fields, number)
        )
    except UnicodeDecodeError as exc:
        raise PortableStartupError(f"page {description} is not UTF-8") from exc


def _page_button_groups(payload: bytes) -> tuple[_ButtonGroupEvidence, ...]:
    """Extract keyed button groups from one Streamlit ``ForwardMsg``.

    Streamlit implements ``st.segmented_control`` as Element.button_group. The
    portable smoke deliberately parses only the stable protobuf fields needed to
    exercise a real browser-style rerun without importing Streamlit at runtime.
    """

    groups = []
    for delta_payload in _nested_bytes(_protobuf_fields(payload), 5):
        for element_payload in _nested_bytes(_protobuf_fields(delta_payload), 3):
            for group_payload in _nested_bytes(
                _protobuf_fields(element_payload), 55
            ):
                fields = _protobuf_fields(group_payload)
                widget_ids = _utf8_fields(fields, 1, "button-group id")
                labels = _utf8_fields(fields, 11, "button-group label")
                if len(widget_ids) != 1 or len(labels) != 1:
                    raise PortableStartupError(
                        "page button group has an invalid identity"
                    )
                options = []
                for option_payload in _nested_bytes(fields, 2):
                    contents = _utf8_fields(
                        _protobuf_fields(option_payload),
                        1,
                        "button-group option",
                    )
                    if len(contents) != 1:
                        raise PortableStartupError(
                            "page button-group option is malformed"
                        )
                    options.append(contents[0])
                groups.append(
                    _ButtonGroupEvidence(
                        widget_id=widget_ids[0],
                        label=labels[0],
                        options=tuple(options),
                        selected=_utf8_fields(
                            fields, 14, "button-group selected value"
                        ),
                    )
                )
    return tuple(groups)


def _page_buttons(payload: bytes) -> tuple[_ButtonEvidence, ...]:
    """Extract ordinary keyed buttons needed for document-generation probes."""

    buttons = []
    for delta_payload in _nested_bytes(_protobuf_fields(payload), 5):
        for element_payload in _nested_bytes(_protobuf_fields(delta_payload), 3):
            for button_payload in _nested_bytes(
                _protobuf_fields(element_payload), 19
            ):
                fields = _protobuf_fields(button_payload)
                widget_ids = _utf8_fields(fields, 1, "button id")
                labels = _utf8_fields(fields, 2, "button label")
                disabled = [
                    cast(int, item.value)
                    for item in fields
                    if item.number == 8 and item.wire_type == 0
                ]
                if (
                    len(widget_ids) != 1
                    or len(labels) != 1
                    or len(disabled) > 1
                ):
                    raise PortableStartupError("page button is malformed")
                buttons.append(
                    _ButtonEvidence(
                        widget_id=widget_ids[0],
                        label=labels[0],
                        disabled=bool(disabled[0]) if disabled else False,
                    )
                )
    return tuple(buttons)


def _page_downloads(payload: bytes) -> tuple[_DownloadEvidence, ...]:
    """Extract registered download controls without fetching private contents."""

    downloads = []
    for delta_payload in _nested_bytes(_protobuf_fields(payload), 5):
        for element_payload in _nested_bytes(_protobuf_fields(delta_payload), 3):
            for download_payload in _nested_bytes(
                _protobuf_fields(element_payload), 43
            ):
                fields = _protobuf_fields(download_payload)
                widget_ids = _utf8_fields(fields, 1, "download id")
                labels = _utf8_fields(fields, 2, "download label")
                urls = _utf8_fields(fields, 6, "download URL")
                deferred_ids = _utf8_fields(fields, 12, "deferred download id")
                disabled = [
                    cast(int, item.value)
                    for item in fields
                    if item.number == 7 and item.wire_type == 0
                ]
                if (
                    len(widget_ids) != 1
                    or len(labels) != 1
                    or len(urls) > 1
                    or len(deferred_ids) > 1
                    or len(disabled) > 1
                ):
                    raise PortableStartupError("page download control is malformed")
                downloads.append(
                    _DownloadEvidence(
                        widget_id=widget_ids[0],
                        label=labels[0],
                        disabled=bool(disabled[0]) if disabled else False,
                        has_file=any(value for value in (*urls, *deferred_ids)),
                    )
                )
    return tuple(downloads)


def _page_dataframes(payload: bytes) -> tuple[_DataframeEvidence, ...]:
    """Extract keyed dataframes and their editing mode from one page message."""

    dataframes = []
    for delta_payload in _nested_bytes(_protobuf_fields(payload), 5):
        for element_payload in _nested_bytes(_protobuf_fields(delta_payload), 3):
            for dataframe_payload in _nested_bytes(
                _protobuf_fields(element_payload), 40
            ):
                fields = _protobuf_fields(dataframe_payload)
                widget_ids = _utf8_fields(fields, 2, "dataframe id")
                modes = [
                    cast(int, item.value)
                    for item in fields
                    if item.number == 4 and item.wire_type == 0
                ]
                if len(widget_ids) > 1 or len(modes) > 1:
                    raise PortableStartupError("page dataframe is malformed")
                if widget_ids:
                    dataframes.append(
                        _DataframeEvidence(
                            widget_id=widget_ids[0],
                            editing_mode=modes[0] if modes else 0,
                        )
                    )
    return tuple(dataframes)


def _page_bidi_components(payload: bytes) -> tuple[_BidiComponentEvidence, ...]:
    """Extract registered Streamlit Components v2 elements from one message."""

    components = []
    for delta_payload in _nested_bytes(_protobuf_fields(payload), 5):
        for element_payload in _nested_bytes(_protobuf_fields(delta_payload), 3):
            for component_payload in _nested_bytes(
                _protobuf_fields(element_payload), 59
            ):
                fields = _protobuf_fields(component_payload)
                widget_ids = _utf8_fields(fields, 1, "component id")
                names = _utf8_fields(fields, 2, "component name")
                json_values = _utf8_fields(fields, 10, "component data")
                if (
                    len(widget_ids) != 1
                    or len(names) != 1
                    or len(json_values) > 1
                ):
                    raise PortableStartupError("page component is malformed")
                components.append(
                    _BidiComponentEvidence(
                        widget_id=widget_ids[0],
                        component_name=names[0],
                        has_json_data=bool(json_values and json_values[0]),
                    )
                )
    return tuple(components)


def _page_alerts(payload: bytes) -> tuple[tuple[int, str], ...]:
    """Extract ``(format, body)`` pairs from Streamlit alert elements."""

    alerts = []
    for delta_payload in _nested_bytes(_protobuf_fields(payload), 5):
        for element_payload in _nested_bytes(_protobuf_fields(delta_payload), 3):
            for alert_payload in _nested_bytes(
                _protobuf_fields(element_payload), 30
            ):
                fields = _protobuf_fields(alert_payload)
                bodies = _utf8_fields(fields, 1, "alert body")
                formats = [
                    cast(int, field.value)
                    for field in fields
                    if field.number == 2 and field.wire_type == 0
                ]
                if len(bodies) != 1 or len(formats) != 1:
                    raise PortableStartupError("page alert is malformed")
                alerts.append((formats[0], bodies[0]))
    return tuple(alerts)


def _page_tab_containers(payload: bytes) -> tuple[tuple[str, int], ...]:
    """Extract stateful tab-container ids and their selected default indices."""

    containers = []
    for delta_payload in _nested_bytes(_protobuf_fields(payload), 5):
        for block_payload in _nested_bytes(_protobuf_fields(delta_payload), 6):
            for tab_payload in _nested_bytes(_protobuf_fields(block_payload), 6):
                fields = _protobuf_fields(tab_payload)
                widget_ids = _utf8_fields(fields, 2, "tab-container id")
                indices = [
                    cast(int, field.value)
                    for field in fields
                    if field.number == 1 and field.wire_type == 0
                ]
                if len(widget_ids) != 1 or len(indices) > 1:
                    raise PortableStartupError("page tab container is malformed")
                containers.append((widget_ids[0], indices[0] if indices else 0))
    return tuple(containers)


def _page_exception(payload: bytes) -> tuple[str, str] | None:
    for delta_payload in _nested_bytes(_protobuf_fields(payload), 5):
        for element_payload in _nested_bytes(_protobuf_fields(delta_payload), 3):
            for exception_payload in _nested_bytes(
                _protobuf_fields(element_payload), 8
            ):
                fields = _protobuf_fields(exception_payload)
                exception_type = _nested_bytes(fields, 1)
                message = _nested_bytes(fields, 2)
                try:
                    type_text = (
                        exception_type[0].decode("utf-8")
                        if exception_type
                        else "Exception"
                    )
                    message_text = message[0].decode("utf-8") if message else ""
                except UnicodeDecodeError as exc:
                    raise PortableStartupError(
                        "page exception payload is not UTF-8"
                    ) from exc
                return type_text[:128], message_text[:512]
    return None


def _page_has_element(payload: bytes) -> bool:
    for delta_payload in _nested_bytes(_protobuf_fields(payload), 5):
        if _nested_bytes(_protobuf_fields(delta_payload), 3):
            return True
    return False


def _page_finished_status(payload: bytes) -> int | None:
    statuses = [
        cast(int, field.value)
        for field in _protobuf_fields(payload)
        if field.number == 6 and field.wire_type == 0
    ]
    if len(statuses) > 1:
        raise PortableStartupError("page protobuf repeats script-finished status")
    return statuses[0] if statuses else None


def _masked_websocket_frame(opcode: int, payload: bytes) -> bytes:
    if not 0 <= opcode <= 0x0F or len(payload) > _MAX_WEBSOCKET_FRAME:
        raise PortableStartupError("page WebSocket client frame is invalid")
    first = 0x80 | opcode
    size = len(payload)
    if size < 126:
        header = bytes((first, 0x80 | size))
    elif size <= 0xFFFF:
        header = bytes((first, 0x80 | 126)) + struct.pack("!H", size)
    else:
        header = bytes((first, 0x80 | 127)) + struct.pack("!Q", size)
    mask = os.urandom(4)
    masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
    return header + mask + masked


def _read_websocket_frame(reader: _SocketReader) -> tuple[int, bytes]:
    first, second = reader.read_exact(2)
    if first & 0x70 or not first & 0x80:
        raise PortableStartupError("page WebSocket frame is fragmented or reserved")
    if second & 0x80:
        raise PortableStartupError("page WebSocket server frame is unexpectedly masked")
    opcode = first & 0x0F
    size = second & 0x7F
    if size == 126:
        size = struct.unpack("!H", reader.read_exact(2))[0]
    elif size == 127:
        size = struct.unpack("!Q", reader.read_exact(8))[0]
    if size > _MAX_WEBSOCKET_FRAME:
        raise PortableStartupError("page WebSocket frame exceeds the limit")
    if opcode >= 8 and size > 125:
        raise PortableStartupError("page WebSocket control frame exceeds the limit")
    return opcode, reader.read_exact(size)


def _websocket_handshake(
    connection: socket.socket, reader: _SocketReader, port: int
) -> None:
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        f"GET {_PAGE_STREAM_PATH} HTTP/1.1\r\n"
        f"Host: {_LOOPBACK}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "Sec-WebSocket-Protocol: streamlit\r\n"
        f"Origin: http://{_LOOPBACK}:{port}\r\n\r\n"
    ).encode("ascii")
    connection.sendall(request)
    try:
        lines = reader.read_headers().decode("ascii").split("\r\n")
    except UnicodeDecodeError as exc:
        raise PortableStartupError("page WebSocket handshake is not ASCII") from exc
    if not lines or not lines[0].startswith("HTTP/1.1 101 "):
        raise PortableStartupError("page WebSocket handshake did not return HTTP 101")
    headers: dict[str, str] = {}
    critical_headers = {
        "connection",
        "sec-websocket-accept",
        "sec-websocket-protocol",
        "upgrade",
    }
    for line in lines[1:]:
        if not line:
            continue
        if ":" not in line:
            raise PortableStartupError("page WebSocket response header is malformed")
        name, value = line.split(":", 1)
        folded = name.strip().casefold()
        if folded in headers and folded in critical_headers:
            raise PortableStartupError("page WebSocket response repeats a header")
        headers.setdefault(folded, value.strip())
    expected_accept = base64.b64encode(
        hashlib.sha1(
            (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii"),
            usedforsecurity=False,
        ).digest()
    ).decode("ascii")
    connection_tokens = {
        token.strip().casefold() for token in headers.get("connection", "").split(",")
    }
    if (
        headers.get("upgrade", "").casefold() != "websocket"
        or "upgrade" not in connection_tokens
        or headers.get("sec-websocket-accept") != expected_accept
        or headers.get("sec-websocket-protocol") != "streamlit"
    ):
        raise PortableStartupError("page WebSocket handshake identity differs")


def _execute_page_run(
    process: subprocess.Popen[bytes],
    connection: socket.socket,
    reader: _SocketReader,
    deadline: float,
    backmsg: bytes,
    *,
    require_new_session: bool,
) -> tuple[_PageExecutionEvidence, _PageSurfaceEvidence]:
    message_count = 0
    total_bytes = 0
    saw_new_session = False
    saw_element = False
    button_groups: dict[str, _ButtonGroupEvidence] = {}
    buttons: dict[str, _ButtonEvidence] = {}
    downloads: dict[str, _DownloadEvidence] = {}
    dataframes: dict[str, _DataframeEvidence] = {}
    bidi_components: dict[str, _BidiComponentEvidence] = {}
    alerts: list[tuple[int, str]] = []
    tab_containers: dict[str, int] = {}
    connection.sendall(_masked_websocket_frame(2, backmsg))
    while time.monotonic() < deadline:
        if (returncode := process.poll()) is not None:
            raise PortableStartupError(
                f"Sector.exe exited during page execution (exit {returncode})"
            )
        connection.settimeout(min(1.0, max(0.05, deadline - time.monotonic())))
        try:
            opcode, payload = _read_websocket_frame(reader)
        except TimeoutError:
            continue
        if opcode == 9:
            connection.sendall(_masked_websocket_frame(10, payload))
            continue
        if opcode == 8:
            raise PortableStartupError(
                "page WebSocket closed before script completion"
            )
        if opcode != 2:
            raise PortableStartupError(
                "page WebSocket returned a non-binary application frame"
            )
        message_count += 1
        total_bytes += len(payload)
        if message_count > _MAX_PAGE_MESSAGES or total_bytes > _MAX_PAGE_BYTES:
            raise PortableStartupError("page execution evidence exceeds the limit")
        fields = _protobuf_fields(payload)
        saw_new_session = saw_new_session or bool(_nested_bytes(fields, 4))
        if exception := _page_exception(payload):
            exception_type, message = exception
            detail = f": {message}" if message else ""
            raise PortableStartupError(
                f"packaged page raised {exception_type}{detail}"
            )
        saw_element = saw_element or _page_has_element(payload)
        for group in _page_button_groups(payload):
            button_groups[group.label] = group
        for button in _page_buttons(payload):
            buttons[button.label] = button
        for download in _page_downloads(payload):
            downloads[download.label] = download
        for dataframe in _page_dataframes(payload):
            dataframes[dataframe.widget_id] = dataframe
        for component in _page_bidi_components(payload):
            bidi_components[component.widget_id] = component
        alerts.extend(_page_alerts(payload))
        for widget_id, default_index in _page_tab_containers(payload):
            tab_containers[widget_id] = default_index
        if (status := _page_finished_status(payload)) is not None:
            if status == _PAGE_EARLY_RERUN_STATUS:
                continue
            if status not in {
                _PAGE_SUCCESS_STATUS,
                _PAGE_FRAGMENT_SUCCESS_STATUS,
            }:
                raise PortableStartupError(
                    f"packaged page finished with Streamlit status {status}"
                )
            if (require_new_session and not saw_new_session) or not saw_element:
                raise PortableStartupError(
                    "packaged page finished without a session and rendered element"
                )
            return (
                _PageExecutionEvidence(
                    message_count=message_count,
                    status="finished-successfully",
                ),
                _PageSurfaceEvidence(
                    button_groups=button_groups,
                    alerts=tuple(alerts),
                    tab_containers=tab_containers,
                    buttons=buttons,
                    downloads=downloads,
                    dataframes=dataframes,
                    bidi_components=bidi_components,
                ),
            )
    raise PortableStartupError("packaged page did not finish before the timeout")


def _required_button_group(
    groups: dict[str, _ButtonGroupEvidence], label: str, option: str
) -> _ButtonGroupEvidence:
    group = groups.get(label)
    if group is None or option not in group.options:
        raise PortableStartupError(
            f"packaged page did not expose {label!r} with option {option!r}"
        )
    return group


def _required_button(
    buttons: dict[str, _ButtonEvidence], label: str
) -> _ButtonEvidence:
    button = buttons.get(label)
    if button is None or button.disabled:
        raise PortableStartupError(
            f"packaged page did not expose enabled button {label!r}"
        )
    return button


def _required_download(
    downloads: dict[str, _DownloadEvidence], label: str
) -> _DownloadEvidence:
    download = downloads.get(label)
    if download is None or download.disabled or not download.has_file:
        raise PortableStartupError(
            f"packaged page did not register enabled download {label!r}"
        )
    return download


def _require_editable_grid(surface: _PageSurfaceEvidence) -> None:
    native_editor = any(
        item.editing_mode != 0 for item in surface.dataframes.values()
    )
    sector_grid = any(
        item.component_name == "sector.point_grid_rich_v1" and item.has_json_data
        for item in surface.bidi_components.values()
    )
    if not native_editor and not sector_grid:
        raise PortableStartupError(
            "packaged first input page did not register an editable data grid"
        )


def _required_input_tabs(surface: _PageSurfaceEvidence) -> str:
    if len(surface.tab_containers) != 1:
        raise PortableStartupError(
            "packaged page did not expose exactly one input tab container"
        )
    widget_id, default_index = next(iter(surface.tab_containers.items()))
    if default_index != 0:
        raise PortableStartupError(
            "packaged page did not start on the first input tab"
        )
    return widget_id


def _require_autosave_notice(
    alerts: tuple[tuple[int, str], ...], scenario: str
) -> None:
    if scenario == _LEGACY_SCENARIO:
        expected_format = 4  # Alert.SUCCESS
        matches = [body for fmt, body in alerts if fmt == expected_format]
        if _AUTOSAVE_RESTORED_TEXT not in matches:
            raise PortableStartupError(
                "packaged page did not confirm legacy autosave restoration"
            )
        return
    if scenario == _HOSTILE_SCENARIO:
        expected_format = 1  # Alert.ERROR
        matches = [
            body
            for fmt, body in alerts
            if fmt == expected_format
            and body == _AUTOSAVE_REJECTED_TEXT
            and _HOSTILE_REPORT_PROFILE not in body
        ]
        if not matches:
            raise PortableStartupError(
                "packaged page did not report hostile autosave rejection"
            )
        return
    raise PortableStartupError(f"unknown packaged startup scenario: {scenario}")


def _run_manual_document_probe(
    process: subprocess.Popen[bytes],
    connection: socket.socket,
    reader: _SocketReader,
    deadline: float,
    workspace: _ButtonGroupEvidence,
    input_tabs_id: str,
    project_surface: _PageSurfaceEvidence,
) -> int:
    """Open the frozen manual, generate both formats, then close the dialog."""

    manual = _required_button(
        project_surface.buttons, _USER_MANUAL_BUTTON_LABEL
    )
    open_page, surface = _execute_page_run(
        process,
        connection,
        reader,
        deadline,
        _trigger_widget_rerun_backmsg(
            manual.widget_id,
            string_arrays=((workspace.widget_id, _INPUT_WORKSPACE),),
            strings=((input_tabs_id, _PROJECT_TAB_LABEL),),
        ),
        require_new_session=False,
    )
    generate = _required_button(
        surface.buttons, _MANUAL_GENERATE_BUTTON_LABEL
    )
    generated_page, surface = _execute_page_run(
        process,
        connection,
        reader,
        deadline,
        _trigger_widget_rerun_backmsg(
            generate.widget_id,
            string_arrays=((workspace.widget_id, _INPUT_WORKSPACE),),
            strings=((input_tabs_id, _PROJECT_TAB_LABEL),),
        ),
        require_new_session=False,
    )
    _required_download(surface.downloads, _MANUAL_PDF_DOWNLOAD_LABEL)
    _required_download(surface.downloads, _MANUAL_HTML_DOWNLOAD_LABEL)
    close = _required_button(surface.buttons, _MANUAL_CLOSE_BUTTON_LABEL)
    closed_page, _surface = _execute_page_run(
        process,
        connection,
        reader,
        deadline,
        _trigger_widget_rerun_backmsg(
            close.widget_id,
            string_arrays=((workspace.widget_id, _INPUT_WORKSPACE),),
            strings=((input_tabs_id, _PROJECT_TAB_LABEL),),
        ),
        require_new_session=False,
    )
    return (
        open_page.message_count
        + generated_page.message_count
        + closed_page.message_count
    )


def _run_report_document_probe(
    process: subprocess.Popen[bytes],
    connection: socket.socket,
    reader: _SocketReader,
    deadline: float,
    workspace: _ButtonGroupEvidence,
    report_profile: _ButtonGroupEvidence,
    report_surface: _PageSurfaceEvidence,
) -> int:
    """Generate and register the frozen program's Standard PDF report."""

    generate = _required_button(
        report_surface.buttons, _REPORT_GENERATE_BUTTON_LABEL
    )
    generated_page, surface = _execute_page_run(
        process,
        connection,
        reader,
        deadline,
        _trigger_widget_rerun_backmsg(
            generate.widget_id,
            string_arrays=(
                (workspace.widget_id, _REPORT_WORKSPACE),
                (report_profile.widget_id, _REPORT_PROFILE_DEFAULT),
            ),
        ),
        require_new_session=False,
    )
    try:
        _required_download(surface.downloads, _REPORT_DOWNLOAD_LABEL)
    except PortableStartupError as exc:
        alerts = " | ".join(body for _format, body in surface.alerts)
        detail = alerts or "no report message was rendered"
        raise PortableStartupError(f"{exc}; report page: {detail}") from exc
    return generated_page.message_count


def _run_page_session(
    process: subprocess.Popen[bytes],
    port: int,
    timeout_seconds: float,
    scenario: str,
) -> _PageExecutionEvidence:
    """Prove pre-widget autosave recovery and the resulting Report profile."""

    deadline = time.monotonic() + timeout_seconds
    connection: socket.socket | None = None
    try:
        connection = socket.create_connection(
            (_LOOPBACK, port), timeout=min(5.0, timeout_seconds)
        )
        connection.settimeout(min(1.0, timeout_seconds))
        reader = _SocketReader(connection)
        _websocket_handshake(connection, reader, port)

        first, surface = _execute_page_run(
            process,
            connection,
            reader,
            deadline,
            _PAGE_RERUN_BACKMSG,
            require_new_session=True,
        )
        input_tabs_id = _required_input_tabs(surface)
        section_page, section_surface = _execute_page_run(
            process,
            connection,
            reader,
            deadline,
            _string_widget_rerun_backmsg(
                ((input_tabs_id, _SECTION_TAB_LABEL),)
            ),
            require_new_session=False,
        )
        _require_editable_grid(section_surface)
        probes = ["editable-data-grid"]
        project_page, project_surface = _execute_page_run(
            process,
            connection,
            reader,
            deadline,
            _string_widget_rerun_backmsg(
                ((input_tabs_id, _PROJECT_TAB_LABEL),)
            ),
            require_new_session=False,
        )
        _require_autosave_notice(project_surface.alerts, scenario)
        probes.append(
            "project-load"
            if scenario == _LEGACY_SCENARIO
            else "invalid-project-rejection"
        )
        _required_download(
            project_surface.downloads, _PROJECT_DOWNLOAD_LABEL
        )
        probes.append("project-save")
        workspace = _required_button_group(
            project_surface.button_groups, _WORKSPACE_LABEL, _REPORT_WORKSPACE
        )
        document_message_count = 0
        if scenario == _LEGACY_SCENARIO:
            document_message_count += _run_manual_document_probe(
                process,
                connection,
                reader,
                deadline,
                workspace,
                input_tabs_id,
                project_surface,
            )
            probes.extend(("manual-pdf", "manual-html"))
        report_page, report_surface = _execute_page_run(
            process,
            connection,
            reader,
            deadline,
            _widget_rerun_backmsg(
                ((workspace.widget_id, _REPORT_WORKSPACE),)
            ),
            require_new_session=False,
        )
        report_profile = _required_button_group(
            report_surface.button_groups,
            _REPORT_PROFILE_LABEL,
            _REPORT_PROFILE_DEFAULT,
        )
        if report_profile.selected != (_REPORT_PROFILE_DEFAULT,):
            raise PortableStartupError(
                "packaged page did not normalize the persisted report profile "
                "to Standard"
            )
        probes.append("report-profile")
        if scenario == _LEGACY_SCENARIO:
            document_message_count += _run_report_document_probe(
                process,
                connection,
                reader,
                deadline,
                workspace,
                report_profile,
                report_surface,
            )
            probes.append("report-pdf")
        return _PageExecutionEvidence(
            message_count=(
                first.message_count
                + section_page.message_count
                + project_page.message_count
                + report_page.message_count
                + document_message_count
            ),
            status="finished-successfully",
            product_probes=tuple(probes),
        )
    except (OSError, struct.error) as exc:
        raise PortableStartupError(f"packaged page session failed: {exc}") from exc
    finally:
        if connection is not None:
            try:
                connection.sendall(_masked_websocket_frame(8, b""))
            except (OSError, PortableStartupError):
                pass
            connection.close()


def _child_environment(
    workspace: Path, port: int, persisted_report_profile: str
) -> dict[str, str]:
    environment = dict(os.environ)
    state = workspace / "state"
    temp = workspace / "temp"
    state.mkdir()
    temp.mkdir()
    (state / _AUTOSAVE_NAME).write_bytes(
        _autosave_payload(persisted_report_profile)
    )
    environment.update(
        {
            "SECTOR_HEADLESS": "1",
            "SECTOR_PORT": str(port),
            "SECTOR_AUTOSAVE_DIR": str(state),
            "NUMBA_CACHE_DIR": str(state / "numba_cache"),
            "LOCALAPPDATA": str(state),
            "APPDATA": str(state),
            "TEMP": str(temp),
            "TMP": str(temp),
        }
    )
    return environment


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=_TERMINATE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=_TERMINATE_TIMEOUT_SECONDS)


def _run_startup_scenario(
    folder: Path,
    executable: Path,
    workspace: Path,
    scenario: str,
    persisted_report_profile: str,
    timeout_seconds: float,
) -> PortableStartupScenarioEvidence:
    scenario_workspace = workspace / scenario
    scenario_workspace.mkdir()
    stdout_path = scenario_workspace / "Sector-startup-stdout.log"
    stderr_path = scenario_workspace / "Sector-startup-stderr.log"
    port = _select_loopback_port()
    environment = _child_environment(
        scenario_workspace, port, persisted_report_profile
    )
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    process: subprocess.Popen[bytes] | None = None
    page: _PageExecutionEvidence | None = None
    try:
        with stdout_path.open("xb") as stdout_log, stderr_path.open("xb") as stderr_log:
            try:
                process = subprocess.Popen(
                    [str(executable)],
                    cwd=folder,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_log,
                    stderr=stderr_log,
                    creationflags=creationflags,
                )
            except OSError as exc:
                raise PortableStartupError("cannot launch Sector.exe") from exc
            _wait_for_health(process, port, timeout_seconds)
            page = _run_page_session(process, port, timeout_seconds, scenario)
    finally:
        if process is not None:
            _stop_process(process)
    if page is None:
        raise PortableStartupError("page execution did not produce evidence")
    return PortableStartupScenarioEvidence(
        name=scenario,
        persisted_report_profile=persisted_report_profile,
        port=port,
        health_status="ok",
        page_status=page.status,
        page_message_count=page.message_count,
        stdout_log=str(stdout_path),
        stderr_log=str(stderr_path),
        product_probes=page.product_probes,
    )


def run_portable_startup_smoke(
    package: Path, workspace: Path, *, timeout_seconds: float = 120.0
) -> PortableStartupEvidence:
    """Start Sector.exe twice and prove both persisted-profile recovery paths."""
    if timeout_seconds <= 0:
        raise PortableStartupError("timeout must be positive")
    folder, executable = _package_executable(package)
    selected_workspace = _create_workspace(workspace)
    scenarios = tuple(
        _run_startup_scenario(
            folder,
            executable,
            selected_workspace,
            scenario,
            profile,
            timeout_seconds,
        )
        for scenario, profile in (
            (_LEGACY_SCENARIO, _LEGACY_REPORT_PROFILE),
            (_HOSTILE_SCENARIO, _HOSTILE_REPORT_PROFILE),
        )
    )
    evidence = PortableStartupEvidence(
        package_folder=str(folder),
        executable=str(executable),
        address=_LOOPBACK,
        health_status="ok",
        page_status="finished-successfully",
        page_message_count=sum(item.page_message_count for item in scenarios),
        scenarios=scenarios,
    )
    (selected_workspace / "startup-smoke.json").write_text(
        json.dumps(asdict(evidence), indent=2, sort_keys=True) + "\n",
        encoding="ascii",
        newline="\n",
    )
    return evidence


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        evidence = run_portable_startup_smoke(
            arguments.package,
            arguments.workspace,
            timeout_seconds=arguments.timeout_seconds,
        )
    except PortableStartupError as exc:
        print(f"Portable startup smoke failed: {exc}", file=sys.stderr)
        return 2
    print(
        "Portable startup smoke passed: "
        f"both isolated {evidence.address} scenarios returned healthy; "
        f"the persisted-profile pages {evidence.page_status} after "
        f"{evidence.page_message_count} messages."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
