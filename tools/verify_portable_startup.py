"""Run the verified unsigned portable package through a controlled smoke test.

The tool authenticates a complete portable distribution against exact source,
extracts the authenticated archive through the portable core's safe extractor,
and launches only the extracted ``Sector.exe``. The child is assigned, while
still suspended, to a Windows Job Object configured to kill every owned process
on close. Acceptance requires Streamlit's exact loopback health response from a
TCP listener whose PID belongs to that job. No browser, proxy, redirect, shell,
installer, signing credential, or PID-based termination is used.
"""

from __future__ import annotations

import argparse
import ctypes
import http.client
import importlib.util
import ipaddress
import json
import msvcrt
import os
import socket
import stat
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from ctypes import wintypes
from dataclasses import asdict, dataclass
from pathlib import Path
from types import ModuleType
from typing import BinaryIO, Protocol, cast

sys.dont_write_bytecode = True

_LOOPBACK = "127.0.0.1"
_HEALTH_PATH = "/_stcore/health"
_HEALTH_BODY = b"ok"
_HEADLESS_ENV = "SECTOR_HEADLESS"
_PORT_ENV = "SECTOR_PORT"
_TERMINATE_TIMEOUT_SECONDS = 10.0
_PORT_CLOSE_TIMEOUT_SECONDS = 10.0
_MAX_TCP_TABLE_BYTES = 16 * 1024 * 1024
_MAX_TCP_ROWS = 65_536

_CREATE_SUSPENDED = 0x00000004
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
_STARTF_USESTDHANDLES = 0x00000100
_PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 258
_ERROR_INSUFFICIENT_BUFFER = 122
_AF_INET = 2
_TCP_TABLE_OWNER_PID_LISTENER = 3
_MIB_TCP_STATE_LISTEN = 2

_INHERITED_CHILD_ENV = (
    "COMSPEC",
    "NUMBER_OF_PROCESSORS",
    "OS",
    "PATH",
    "PATHEXT",
    "PROCESSOR_ARCHITECTURE",
    "PROCESSOR_IDENTIFIER",
    "PROCESSOR_LEVEL",
    "PROCESSOR_REVISION",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PROGRAMW6432",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "WINDIR",
)

_PORTABLE_CORE: ModuleType | None = None
_WINDOWS_API: _WindowsApi | None = None


class PortableStartupError(RuntimeError):
    """The portable package did not meet the controlled startup contract."""


class _ListenerNotReady(RuntimeError):
    """The reserved loopback port does not have a listener yet."""


class _VerifiedDistributionEvidence(Protocol):
    archive: Path
    archive_sha256: str


class _OwnedJob(Protocol):
    pid: int

    def poll(self) -> int | None: ...

    def owns_pid(self, process_id: int) -> bool: ...

    def terminate_and_wait(self, timeout_seconds: float) -> None: ...


@dataclass(frozen=True)
class PortableStartupEvidence:
    """Stable evidence preserved beside the startup logs."""

    address: str
    archive_sha256: str
    browser_suppression: str
    health_body: str
    health_path: str
    health_status: int
    listener_pid: int
    nonloopback_addresses_checked: tuple[str, ...]
    package_folder: str
    port: int
    stderr_log: str
    stdout_log: str


class _STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(wintypes.BYTE)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [
        ("StartupInfo", _STARTUPINFOW),
        ("lpAttributeList", ctypes.c_void_p),
    ]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
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


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _MIB_TCPROW_OWNER_PID(ctypes.Structure):
    _fields_ = [
        ("dwState", wintypes.DWORD),
        ("dwLocalAddr", wintypes.DWORD),
        ("dwLocalPort", wintypes.DWORD),
        ("dwRemoteAddr", wintypes.DWORD),
        ("dwRemotePort", wintypes.DWORD),
        ("dwOwningPid", wintypes.DWORD),
    ]


@dataclass(frozen=True)
class _CreatedProcess:
    process_handle: int
    thread_handle: int
    process_id: int


class _WindowsApi:
    """Small fail-closed wrapper around the Windows APIs used by the smoke."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise PortableStartupError("portable startup smoke requires Windows")
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._iphlpapi = ctypes.WinDLL("iphlpapi", use_last_error=True)
        self._bind_signatures()

    def _bind_signatures(self) -> None:
        kernel32 = self._kernel32
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.CreateProcessW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.BOOL,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.LPCWSTR,
            ctypes.c_void_p,
            ctypes.POINTER(_PROCESS_INFORMATION),
        ]
        kernel32.CreateProcessW.restype = wintypes.BOOL
        kernel32.InitializeProcThreadAttributeList.argtypes = [
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        kernel32.InitializeProcThreadAttributeList.restype = wintypes.BOOL
        kernel32.UpdateProcThreadAttribute.argtypes = [
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.c_size_t,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        kernel32.UpdateProcThreadAttribute.restype = wintypes.BOOL
        kernel32.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
        kernel32.DeleteProcThreadAttributeList.restype = None
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
        kernel32.ResumeThread.restype = wintypes.DWORD
        kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateProcess.restype = wintypes.BOOL
        kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.GetExitCodeProcess.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.IsProcessInJob.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.BOOL),
        ]
        kernel32.IsProcessInJob.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        self._iphlpapi.GetExtendedTcpTable.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.BOOL,
            wintypes.ULONG,
            ctypes.c_int,
            wintypes.ULONG,
        ]
        self._iphlpapi.GetExtendedTcpTable.restype = wintypes.DWORD

    @staticmethod
    def _error(action: str) -> PortableStartupError:
        return PortableStartupError(
            f"{action} failed with Windows error {ctypes.get_last_error()}"
        )

    def create_kill_on_close_job(self) -> int:
        handle = self._kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise self._error("CreateJobObjectW")
        job = int(handle)
        limits = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        limits.BasicLimitInformation.LimitFlags = (
            _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        if not self._kernel32.SetInformationJobObject(
            job,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            self.close_handle(job)
            raise self._error("SetInformationJobObject")
        return job

    def create_suspended_process(
        self,
        executable: Path,
        cwd: Path,
        environment: Mapping[str, str],
        stdout_log: BinaryIO,
        stderr_log: BinaryIO,
    ) -> _CreatedProcess:
        startup = _STARTUPINFOEXW()
        startup.StartupInfo.cb = ctypes.sizeof(startup)
        startup.StartupInfo.dwFlags = _STARTF_USESTDHANDLES
        process = _PROCESS_INFORMATION()
        command_line = ctypes.create_unicode_buffer(
            subprocess.list2cmdline([str(executable)])
        )
        environment_block = ctypes.create_unicode_buffer(
            _windows_environment_block(environment)
        )
        with open(os.devnull, "rb") as stdin_stream:
            handles = (
                msvcrt.get_osfhandle(stdin_stream.fileno()),
                msvcrt.get_osfhandle(stdout_log.fileno()),
                msvcrt.get_osfhandle(stderr_log.fileno()),
            )
            startup.StartupInfo.hStdInput = wintypes.HANDLE(handles[0])
            startup.StartupInfo.hStdOutput = wintypes.HANDLE(handles[1])
            startup.StartupInfo.hStdError = wintypes.HANDLE(handles[2])
            previous: list[tuple[int, bool]] = []
            primary_error: Exception | None = None
            restore_errors: list[Exception] = []
            created = False
            create_error = 0
            attribute_list: ctypes.c_void_p | None = None
            attribute_list_initialised = False
            attribute_storage = None
            handle_array = None
            try:
                for handle in handles:
                    previous.append((handle, os.get_handle_inheritable(handle)))
                    os.set_handle_inheritable(handle, True)
                attribute_size = ctypes.c_size_t()
                ctypes.set_last_error(0)
                first_initialisation = bool(
                    self._kernel32.InitializeProcThreadAttributeList(
                        None,
                        1,
                        0,
                        ctypes.byref(attribute_size),
                    )
                )
                if (
                    first_initialisation
                    or ctypes.get_last_error() != _ERROR_INSUFFICIENT_BUFFER
                    or attribute_size.value <= 0
                ):
                    raise PortableStartupError(
                        "cannot size the inherited-handle allowlist"
                    )
                attribute_storage = ctypes.create_string_buffer(attribute_size.value)
                attribute_list = ctypes.cast(attribute_storage, ctypes.c_void_p)
                if not self._kernel32.InitializeProcThreadAttributeList(
                    attribute_list,
                    1,
                    0,
                    ctypes.byref(attribute_size),
                ):
                    raise self._error("InitializeProcThreadAttributeList")
                attribute_list_initialised = True
                handle_array = (wintypes.HANDLE * len(handles))(*handles)
                if not self._kernel32.UpdateProcThreadAttribute(
                    attribute_list,
                    0,
                    _PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                    ctypes.cast(handle_array, ctypes.c_void_p),
                    ctypes.sizeof(handle_array),
                    None,
                    None,
                ):
                    raise self._error("UpdateProcThreadAttribute")
                startup.lpAttributeList = attribute_list
                created = bool(
                    self._kernel32.CreateProcessW(
                        str(executable),
                        command_line,
                        None,
                        None,
                        True,
                        _CREATE_SUSPENDED
                        | _CREATE_UNICODE_ENVIRONMENT
                        | _EXTENDED_STARTUPINFO_PRESENT,
                        environment_block,
                        str(cwd),
                        ctypes.byref(startup),
                        ctypes.byref(process),
                    )
                )
                if not created:
                    create_error = ctypes.get_last_error()
            except Exception as exc:  # noqa: BLE001 - restore inherited handles
                primary_error = exc
            finally:
                if attribute_list_initialised and attribute_list is not None:
                    self._kernel32.DeleteProcThreadAttributeList(attribute_list)
                for handle, inheritable in reversed(previous):
                    try:
                        os.set_handle_inheritable(handle, inheritable)
                    except OSError as exc:
                        restore_errors.append(exc)
        if primary_error is not None or restore_errors:
            cleanup_errors: list[Exception] = []
            if created:
                cleanup_operations: tuple[Callable[[], None], ...] = (
                    lambda: self.terminate_process(int(process.hProcess)),
                    lambda: self.wait_for_handle(
                        int(process.hProcess), _TERMINATE_TIMEOUT_SECONDS
                    ),
                    lambda: self.close_handle(int(process.hThread)),
                    lambda: self.close_handle(int(process.hProcess)),
                )
                for operation in cleanup_operations:
                    try:
                        operation()
                    except Exception as exc:  # noqa: BLE001 - exhaust raw cleanup
                        cleanup_errors.append(exc)
            if cleanup_errors:
                raise PortableStartupError(
                    "suspended process setup failed and raw cleanup was incomplete"
                ) from cleanup_errors[0]
            cause = primary_error or restore_errors[0]
            raise PortableStartupError(
                "cannot establish the isolated inherited-handle boundary"
            ) from cause
        if not created:
            raise PortableStartupError(
                f"CreateProcessW failed with Windows error {create_error}"
            )
        return _CreatedProcess(
            process_handle=int(process.hProcess),
            thread_handle=int(process.hThread),
            process_id=int(process.dwProcessId),
        )

    def assign_process_to_job(self, job: int, process: int) -> None:
        if not self._kernel32.AssignProcessToJobObject(job, process):
            raise self._error("AssignProcessToJobObject")

    def resume_thread(self, thread: int) -> None:
        if int(self._kernel32.ResumeThread(thread)) == 0xFFFFFFFF:
            raise self._error("ResumeThread")

    def terminate_process(self, process: int) -> None:
        if not self._kernel32.TerminateProcess(process, 1):
            raise self._error("TerminateProcess")

    def terminate_job(self, job: int) -> None:
        if not self._kernel32.TerminateJobObject(job, 1):
            raise self._error("TerminateJobObject")

    def wait_for_handle(self, handle: int, timeout_seconds: float) -> None:
        milliseconds = min(0xFFFFFFFE, max(0, int(timeout_seconds * 1000)))
        result = int(self._kernel32.WaitForSingleObject(handle, milliseconds))
        if result == _WAIT_TIMEOUT:
            raise PortableStartupError("owned Windows object did not become idle")
        if result != _WAIT_OBJECT_0:
            raise self._error("WaitForSingleObject")

    def process_exit_code(self, process: int) -> int | None:
        code = wintypes.DWORD()
        if not self._kernel32.GetExitCodeProcess(process, ctypes.byref(code)):
            raise self._error("GetExitCodeProcess")
        return None if code.value == _STILL_ACTIVE else int(code.value)

    def process_is_in_job(self, process_id: int, job: int) -> bool:
        process = self._kernel32.OpenProcess(
            _PROCESS_QUERY_LIMITED_INFORMATION, False, process_id
        )
        if not process:
            return False
        try:
            result = wintypes.BOOL()
            if not self._kernel32.IsProcessInJob(process, job, ctypes.byref(result)):
                raise self._error("IsProcessInJob")
            return bool(result.value)
        finally:
            self.close_handle(int(process))

    def listener_owner_pids(self, address: str, port: int) -> tuple[int, ...]:
        size = wintypes.DWORD()
        result = int(
            self._iphlpapi.GetExtendedTcpTable(
                None,
                ctypes.byref(size),
                False,
                _AF_INET,
                _TCP_TABLE_OWNER_PID_LISTENER,
                0,
            )
        )
        if result not in (0, _ERROR_INSUFFICIENT_BUFFER):
            raise PortableStartupError(
                f"GetExtendedTcpTable sizing failed with Windows error {result}"
            )
        if not ctypes.sizeof(wintypes.DWORD) <= size.value <= _MAX_TCP_TABLE_BYTES:
            raise PortableStartupError("Windows TCP owner table size is invalid")
        buffer = ctypes.create_string_buffer(size.value)
        result = int(
            self._iphlpapi.GetExtendedTcpTable(
                buffer,
                ctypes.byref(size),
                False,
                _AF_INET,
                _TCP_TABLE_OWNER_PID_LISTENER,
                0,
            )
        )
        if result != 0:
            raise PortableStartupError(
                f"GetExtendedTcpTable failed with Windows error {result}"
            )
        count = int(wintypes.DWORD.from_buffer_copy(buffer).value)
        row_size = ctypes.sizeof(_MIB_TCPROW_OWNER_PID)
        required = ctypes.sizeof(wintypes.DWORD) + count * row_size
        if count > _MAX_TCP_ROWS or required > size.value:
            raise PortableStartupError("Windows TCP owner table is malformed")
        expected_address = int(ipaddress.IPv4Address(address))
        owners: set[int] = set()
        for index in range(count):
            offset = ctypes.sizeof(wintypes.DWORD) + index * row_size
            row = _MIB_TCPROW_OWNER_PID.from_buffer_copy(buffer, offset)
            local_address = socket.ntohl(int(row.dwLocalAddr))
            local_port = socket.ntohs(int(row.dwLocalPort) & 0xFFFF)
            if (
                int(row.dwState) == _MIB_TCP_STATE_LISTEN
                and local_address == expected_address
                and local_port == port
            ):
                owners.add(int(row.dwOwningPid))
        return tuple(sorted(owners))

    def close_handle(self, handle: int) -> None:
        if handle and not self._kernel32.CloseHandle(handle):
            raise self._error("CloseHandle")


class _WindowsJobProcess:
    """One process tree owned by an assigned kill-on-close Job Object."""

    def __init__(
        self,
        api: _WindowsApi,
        job_handle: int,
        process_handle: int,
        process_id: int,
    ) -> None:
        self._api = api
        self._job_handle = job_handle
        self._process_handle = process_handle
        self.pid = process_id
        self._closed = False

    @classmethod
    def launch(
        cls,
        api: _WindowsApi,
        executable: Path,
        cwd: Path,
        environment: Mapping[str, str],
        stdout_log: BinaryIO,
        stderr_log: BinaryIO,
    ) -> _WindowsJobProcess:
        job = api.create_kill_on_close_job()
        created: _CreatedProcess | None = None
        assigned = False
        try:
            created = api.create_suspended_process(
                executable, cwd, environment, stdout_log, stderr_log
            )
            api.assign_process_to_job(job, created.process_handle)
            assigned = True
            api.resume_thread(created.thread_handle)
            api.close_handle(created.thread_handle)
            return cls(api, job, created.process_handle, created.process_id)
        except Exception as exc:
            cleanup_errors: list[Exception] = []
            if created is not None:
                try:
                    if assigned:
                        api.terminate_job(job)
                        api.wait_for_handle(job, _TERMINATE_TIMEOUT_SECONDS)
                    else:
                        api.terminate_process(created.process_handle)
                        api.wait_for_handle(
                            created.process_handle, _TERMINATE_TIMEOUT_SECONDS
                        )
                except Exception as cleanup_exc:  # noqa: BLE001 - preserve launch error
                    cleanup_errors.append(cleanup_exc)
                for handle in (created.thread_handle, created.process_handle):
                    try:
                        api.close_handle(handle)
                    except Exception as cleanup_exc:  # noqa: BLE001 - close all handles
                        cleanup_errors.append(cleanup_exc)
            try:
                api.close_handle(job)
            except Exception as cleanup_exc:  # noqa: BLE001 - close kill-on-close job
                cleanup_errors.append(cleanup_exc)
            if cleanup_errors:
                raise PortableStartupError(
                    "suspended process launch failed and owned cleanup was incomplete"
                ) from cleanup_errors[0]
            if isinstance(exc, PortableStartupError):
                raise
            raise PortableStartupError("cannot launch suspended Sector.exe") from exc

    def poll(self) -> int | None:
        if self._closed:
            return 0
        return self._api.process_exit_code(self._process_handle)

    def owns_pid(self, process_id: int) -> bool:
        if self._closed or process_id <= 0:
            return False
        return self._api.process_is_in_job(process_id, self._job_handle)

    def terminate_and_wait(self, timeout_seconds: float) -> None:
        if self._closed:
            return
        primary_error: Exception | None = None
        try:
            self._api.terminate_job(self._job_handle)
            self._api.wait_for_handle(self._job_handle, timeout_seconds)
        except Exception as exc:  # noqa: BLE001 - handles must still close
            primary_error = exc
        finally:
            close_errors: list[Exception] = []
            for handle in (self._process_handle, self._job_handle):
                try:
                    self._api.close_handle(handle)
                except Exception as exc:  # noqa: BLE001 - attempt every handle close
                    close_errors.append(exc)
            self._closed = True
        if primary_error is not None or close_errors:
            cause = primary_error or close_errors[0]
            raise PortableStartupError(
                "owned Windows Job Object cleanup did not complete"
            ) from cause


def _get_windows_api() -> _WindowsApi:
    global _WINDOWS_API
    if _WINDOWS_API is None:
        _WINDOWS_API = _WindowsApi()
    return _WINDOWS_API


def _windows_environment_block(environment: Mapping[str, str]) -> str:
    entries: list[str] = []
    seen: set[str] = set()
    for name in sorted(environment, key=str.casefold):
        value = environment[name]
        folded = name.casefold()
        if (
            not name
            or "=" in name
            or "\0" in name
            or "\0" in value
            or folded in seen
        ):
            raise PortableStartupError("child environment is not a valid Windows block")
        seen.add(folded)
        entries.append(f"{name}={value}")
    return "\0".join(entries) + "\0\0"


def _inherited_environment_value(name: str) -> str | None:
    folded = name.casefold()
    matches = [value for key, value in os.environ.items() if key.casefold() == folded]
    if len(matches) > 1:
        raise PortableStartupError(f"duplicate inherited environment name: {name}")
    return matches[0] if matches else None


def _create_child_environment(workspace: Path, port: int) -> dict[str, str]:
    environment: dict[str, str] = {}
    for name in _INHERITED_CHILD_ENV:
        value = _inherited_environment_value(name)
        if value is not None:
            environment[name] = value
    if "SYSTEMROOT" not in environment:
        raise PortableStartupError("inherited SYSTEMROOT is required for Sector.exe")

    profile = workspace / "child-profile"
    local_app_data = profile / "AppData" / "Local"
    roaming_app_data = profile / "AppData" / "Roaming"
    temporary = workspace / "child-temp"
    autosave = workspace / "sector-data"
    numba_cache = workspace / "numba-cache"
    for directory in (
        local_app_data,
        roaming_app_data,
        temporary,
        autosave,
        numba_cache,
    ):
        try:
            directory.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            if not directory.is_dir():
                raise PortableStartupError(
                    f"isolated child directory is not regular: {directory}"
                )
        except OSError as exc:
            raise PortableStartupError(
                f"cannot create isolated child directory: {directory}"
            ) from exc

    environment.update(
        {
            "APPDATA": str(roaming_app_data),
            "LOCALAPPDATA": str(local_app_data),
            "NUMBA_CACHE_DIR": str(numba_cache),
            _HEADLESS_ENV: "1",
            _PORT_ENV: str(port),
            "SECTOR_AUTOSAVE_DIR": str(autosave),
            "TEMP": str(temporary),
            "TMP": str(temporary),
            "USERPROFILE": str(profile),
        }
    )
    return environment


def _load_portable_core() -> ModuleType:
    global _PORTABLE_CORE
    if _PORTABLE_CORE is not None:
        return _PORTABLE_CORE
    path = Path(__file__).resolve().with_name("build_portable_windows.py")
    specification = importlib.util.spec_from_file_location(
        "sector_portable_windows_core_for_startup", path
    )
    if specification is None or specification.loader is None:
        raise PortableStartupError("cannot load the portable Windows verifier")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    try:
        specification.loader.exec_module(module)
    except (ImportError, OSError, RuntimeError) as exc:
        raise PortableStartupError(
            f"cannot load the portable Windows verifier: {exc}"
        ) from exc
    _PORTABLE_CORE = module
    return module


def _verify_portable_distribution(
    root: Path, source_revision: str, distribution: Path
) -> tuple[Path, str]:
    core = _load_portable_core()
    verifier = getattr(core, "verify_portable_distribution", None)
    if not callable(verifier):
        raise PortableStartupError("portable distribution verifier is unavailable")
    try:
        evidence = cast(
            _VerifiedDistributionEvidence,
            verifier(root, source_revision, distribution),
        )
        archive = Path(evidence.archive)
        archive_sha256 = str(evidence.archive_sha256)
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise PortableStartupError(
            f"portable distribution verification failed: {exc}"
        ) from exc
    if len(archive_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in archive_sha256
    ):
        raise PortableStartupError("portable verifier returned an invalid archive digest")
    return Path(os.path.abspath(archive)), archive_sha256


def _safe_extract_portable_archive(
    archive: Path, output: Path, expected_sha256: str
) -> Path:
    core = _load_portable_core()
    extractor = getattr(core, "safe_extract_portable_archive", None)
    if not callable(extractor):
        raise PortableStartupError("portable safe extractor is unavailable")
    try:
        extracted = extractor(archive, output, expected_sha256=expected_sha256)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise PortableStartupError(f"portable archive verification failed: {exc}") from exc
    return Path(extracted)


def _is_reparse(status: os.stat_result) -> bool:
    attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(status, "st_file_attributes", 0) & attribute)


def _require_regular_executable(package_root: Path) -> Path:
    executable = package_root / "Sector.exe"
    try:
        status = os.stat(executable, follow_symlinks=False)
    except OSError as exc:
        raise PortableStartupError("extracted package is missing Sector.exe") from exc
    if (
        stat.S_ISLNK(status.st_mode)
        or _is_reparse(status)
        or not stat.S_ISREG(status.st_mode)
        or status.st_size <= 0
    ):
        raise PortableStartupError("extracted Sector.exe is not a regular file")
    return executable


def _create_workspace(workspace: Path) -> Path:
    lexical = Path(os.path.abspath(workspace))
    if os.path.lexists(lexical):
        raise PortableStartupError(f"startup workspace already exists: {lexical}")
    try:
        lexical.mkdir()
        status = os.stat(lexical, follow_symlinks=False)
    except OSError as exc:
        raise PortableStartupError(f"cannot create startup workspace: {lexical}") from exc
    if stat.S_ISLNK(status.st_mode) or _is_reparse(status) or not stat.S_ISDIR(
        status.st_mode
    ):
        raise PortableStartupError("startup workspace is not a regular directory")
    return lexical


def _select_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind((_LOOPBACK, 0))
        address, port = reservation.getsockname()
        if address != _LOOPBACK or not 1 <= port <= 65535:
            raise PortableStartupError("could not reserve a literal loopback port")
        return int(port)


def _request_health(port: int, timeout_seconds: float) -> bytes:
    """Read health directly from loopback, without proxy or redirect support."""
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


def _discover_nonloopback_ipv4() -> tuple[str, ...]:
    """Return local IPv4 addresses available without querying the network."""
    discovered: set[str] = set()
    try:
        records = socket.getaddrinfo(
            socket.gethostname(),
            0,
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise PortableStartupError(
            f"cannot discover local IPv4 addresses: {exc}"
        ) from exc
    for record in records:
        candidate = record[4][0]
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if (
            isinstance(address, ipaddress.IPv4Address)
            and not address.is_loopback
            and not address.is_unspecified
        ):
            discovered.add(str(address))
    return tuple(sorted(discovered))


def _address_accepts_connection(address: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex((address, port)) == 0


def _assert_loopback_only(port: int) -> tuple[str, ...]:
    addresses = _discover_nonloopback_ipv4()
    for address in addresses:
        if _address_accepts_connection(address, port):
            raise PortableStartupError(
                "Sector accepted a connection through non-loopback address "
                f"{address}:{port}"
            )
    return addresses


def _listener_owner_pids(port: int) -> tuple[int, ...]:
    return _get_windows_api().listener_owner_pids(_LOOPBACK, port)


def _require_owned_listener(process: _OwnedJob, port: int) -> int:
    owners = _listener_owner_pids(port)
    if not owners:
        raise _ListenerNotReady(f"no listener on {_LOOPBACK}:{port}")
    if len(owners) != 1 or not process.owns_pid(owners[0]):
        raise PortableStartupError(
            "loopback health listener is not uniquely owned by the Sector Job Object"
        )
    return owners[0]


def _wait_for_health(
    process: _OwnedJob, port: int, timeout_seconds: float
) -> tuple[bytes, int]:
    deadline = time.monotonic() + timeout_seconds
    last_error = "connection not accepted"
    while time.monotonic() < deadline:
        try:
            listener_before = _require_owned_listener(process, port)
        except _ListenerNotReady as exc:
            if (returncode := process.poll()) is not None:
                raise PortableStartupError(
                    f"Sector.exe exited before health succeeded (exit {returncode})"
                ) from exc
            last_error = str(exc)
            time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
            continue
        remaining = max(0.05, deadline - time.monotonic())
        try:
            body = _request_health(port, min(1.0, remaining))
        except PortableStartupError:
            raise
        except (OSError, http.client.HTTPException) as exc:
            last_error = str(exc)
            time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
            continue
        try:
            listener_after = _require_owned_listener(process, port)
        except _ListenerNotReady as exc:
            raise PortableStartupError(
                "owned health listener disappeared during the exact response"
            ) from exc
        if listener_before != listener_after:
            raise PortableStartupError(
                "health listener ownership changed during the exact response"
            )
        return body, listener_before
    raise PortableStartupError(
        f"Sector.exe did not reach the health endpoint: {last_error}"
    )


def _launch_owned_job(
    executable: Path,
    cwd: Path,
    environment: Mapping[str, str],
    stdout_log: BinaryIO,
    stderr_log: BinaryIO,
) -> _OwnedJob:
    return _WindowsJobProcess.launch(
        _get_windows_api(),
        executable,
        cwd,
        environment,
        stdout_log,
        stderr_log,
    )


def _loopback_port_is_closed(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.25)
        return probe.connect_ex((_LOOPBACK, port)) != 0


def _wait_for_port_closed(port: int) -> None:
    deadline = time.monotonic() + _PORT_CLOSE_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if _loopback_port_is_closed(port):
            return
        time.sleep(0.1)
    raise PortableStartupError(
        f"loopback port {port} remained open after owned-process cleanup"
    )


def _write_evidence(path: Path, evidence: PortableStartupEvidence) -> None:
    payload = (json.dumps(asdict(evidence), indent=2, sort_keys=True) + "\n").encode(
        "ascii"
    )
    try:
        with path.open("xb") as stream:
            stream.write(payload)
    except OSError as exc:
        raise PortableStartupError(f"cannot preserve startup evidence: {path}") from exc


def run_portable_startup_smoke(
    root: Path,
    source_revision: str,
    distribution: Path,
    workspace: Path,
    *,
    timeout_seconds: float = 120.0,
) -> PortableStartupEvidence:
    """Verify, safely extract, health-check, and stop one owned process job."""
    if not 1.0 <= timeout_seconds <= 600.0:
        raise PortableStartupError("startup timeout must be between 1 and 600 seconds")
    if len(source_revision) != 40 or any(
        character not in "0123456789abcdef" for character in source_revision
    ):
        raise PortableStartupError(
            "source revision must be an exact lowercase 40-hex commit"
        )
    root = Path(os.path.abspath(root))
    distribution = Path(os.path.abspath(distribution))
    archive, archive_sha256 = _verify_portable_distribution(
        root, source_revision, distribution
    )
    try:
        archive.relative_to(distribution)
    except ValueError as exc:
        raise PortableStartupError(
            "portable verifier returned an archive outside the distribution"
        ) from exc
    workspace = _create_workspace(workspace)
    extraction = workspace / "extracted"
    package_root = Path(
        os.path.abspath(
            _safe_extract_portable_archive(
                archive, extraction, expected_sha256=archive_sha256
            )
        )
    )
    try:
        package_root.relative_to(extraction)
    except ValueError as exc:
        raise PortableStartupError(
            "safe extractor returned a package outside its output boundary"
        ) from exc
    executable = _require_regular_executable(package_root)

    stdout_path = workspace / "Sector-startup-stdout.log"
    stderr_path = workspace / "Sector-startup-stderr.log"
    port = _select_loopback_port()
    environment = _create_child_environment(workspace, port)
    process: _OwnedJob | None = None
    health_body: bytes | None = None
    listener_pid: int | None = None
    nonloopback_addresses: tuple[str, ...] = ()
    primary_error: Exception | None = None
    cleanup_error: Exception | None = None

    with stdout_path.open("xb") as stdout_log, stderr_path.open("xb") as stderr_log:
        try:
            process = _launch_owned_job(
                executable,
                package_root,
                environment,
                stdout_log,
                stderr_log,
            )
            health_body, listener_pid = _wait_for_health(
                process, port, timeout_seconds
            )
            nonloopback_addresses = _assert_loopback_only(port)
        except (PortableStartupError, OSError) as exc:
            primary_error = exc
        finally:
            if process is not None:
                try:
                    process.terminate_and_wait(_TERMINATE_TIMEOUT_SECONDS)
                except PortableStartupError as exc:
                    cleanup_error = exc

    try:
        _wait_for_port_closed(port)
    except (PortableStartupError, OSError) as exc:
        if cleanup_error is None:
            cleanup_error = exc

    if cleanup_error is not None:
        raise PortableStartupError(
            "portable startup cleanup failed; inspect the preserved logs at "
            f"{workspace}"
        ) from cleanup_error
    if primary_error is not None:
        if isinstance(primary_error, PortableStartupError):
            raise PortableStartupError(
                f"{primary_error}; inspect the preserved logs at {workspace}"
            ) from primary_error
        raise PortableStartupError(
            f"cannot start Sector.exe; inspect the preserved logs at {workspace}"
        ) from primary_error
    if health_body != _HEALTH_BODY or listener_pid is None:
        raise PortableStartupError("exact owned health response was not recorded")

    evidence = PortableStartupEvidence(
        address=_LOOPBACK,
        archive_sha256=archive_sha256,
        browser_suppression=f"{_HEADLESS_ENV}=1",
        health_body=health_body.decode("ascii"),
        health_path=_HEALTH_PATH,
        health_status=200,
        listener_pid=listener_pid,
        nonloopback_addresses_checked=nonloopback_addresses,
        package_folder=package_root.name,
        port=port,
        stderr_log=stderr_path.name,
        stdout_log=stdout_path.name,
    )
    _write_evidence(workspace / "startup-smoke.json", evidence)
    return evidence


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--distribution", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        evidence = run_portable_startup_smoke(
            arguments.root,
            arguments.source_revision,
            arguments.distribution,
            arguments.workspace,
            timeout_seconds=arguments.timeout_seconds,
        )
    except PortableStartupError as exc:
        print(f"portable startup smoke failed: {exc}", file=sys.stderr)
        return 2
    print(
        "portable startup smoke passed: "
        f"http://{evidence.address}:{evidence.port}{evidence.health_path} "
        f"returned exactly {evidence.health_body!r} from owned PID "
        f"{evidence.listener_pid}; logs and evidence are in "
        f"{Path(os.path.abspath(arguments.workspace))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
