"""Launch a built Sector package and execute its first Streamlit page."""

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
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast

_LOOPBACK = "127.0.0.1"
_HEALTH_PATH = "/_stcore/health"
_HEALTH_BODY = b"ok"
_PAGE_STREAM_PATH = "/_stcore/stream"
_PAGE_RERUN_BACKMSG = b"\x5a\x00"
_PAGE_SUCCESS_STATUS = 0
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
    port: int
    health_status: str
    page_status: str
    page_message_count: int
    stdout_log: str
    stderr_log: str


@dataclass(frozen=True)
class _PageExecutionEvidence:
    message_count: int
    status: str


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


def _run_page_session(
    process: subprocess.Popen[bytes], port: int, timeout_seconds: float
) -> _PageExecutionEvidence:
    deadline = time.monotonic() + timeout_seconds
    message_count = 0
    total_bytes = 0
    saw_new_session = False
    saw_element = False
    connection: socket.socket | None = None
    try:
        connection = socket.create_connection(
            (_LOOPBACK, port), timeout=min(5.0, timeout_seconds)
        )
        connection.settimeout(min(1.0, timeout_seconds))
        reader = _SocketReader(connection)
        _websocket_handshake(connection, reader, port)
        connection.sendall(_masked_websocket_frame(2, _PAGE_RERUN_BACKMSG))
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
            if (status := _page_finished_status(payload)) is not None:
                if status != _PAGE_SUCCESS_STATUS:
                    raise PortableStartupError(
                        f"packaged page finished with Streamlit status {status}"
                    )
                if not saw_new_session or not saw_element:
                    raise PortableStartupError(
                        "packaged page finished without a session and rendered element"
                    )
                return _PageExecutionEvidence(
                    message_count=message_count,
                    status="finished-successfully",
                )
        raise PortableStartupError("packaged page did not finish before the timeout")
    except (OSError, struct.error) as exc:
        raise PortableStartupError(f"packaged page session failed: {exc}") from exc
    finally:
        if connection is not None:
            try:
                connection.sendall(_masked_websocket_frame(8, b""))
            except (OSError, PortableStartupError):
                pass
            connection.close()


def _child_environment(workspace: Path, port: int) -> dict[str, str]:
    environment = dict(os.environ)
    state = workspace / "state"
    temp = workspace / "temp"
    state.mkdir()
    temp.mkdir()
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


def run_portable_startup_smoke(
    package: Path, workspace: Path, *, timeout_seconds: float = 120.0
) -> PortableStartupEvidence:
    """Start Sector.exe, require health, and execute one exception-free page."""
    if timeout_seconds <= 0:
        raise PortableStartupError("timeout must be positive")
    folder, executable = _package_executable(package)
    selected_workspace = _create_workspace(workspace)
    stdout_path = selected_workspace / "Sector-startup-stdout.log"
    stderr_path = selected_workspace / "Sector-startup-stderr.log"
    port = _select_loopback_port()
    environment = _child_environment(selected_workspace, port)
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
            page = _run_page_session(process, port, timeout_seconds)
    finally:
        if process is not None:
            _stop_process(process)
    if page is None:
        raise PortableStartupError("page execution did not produce evidence")
    evidence = PortableStartupEvidence(
        package_folder=str(folder),
        executable=str(executable),
        address=_LOOPBACK,
        port=port,
        health_status="ok",
        page_status=page.status,
        page_message_count=page.message_count,
        stdout_log=str(stdout_path),
        stderr_log=str(stderr_path),
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
        f"http://{evidence.address}:{evidence.port}{_HEALTH_PATH} returned ok; "
        f"the first page {evidence.page_status} after "
        f"{evidence.page_message_count} messages."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
