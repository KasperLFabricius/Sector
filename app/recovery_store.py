"""Compare-and-replace protection for the shared local recovery file."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path


class RecoveryBusy(OSError):
    """Another process holds the recovery-file lock."""


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_digest(path: Path) -> str | None:
    """Return the byte identity of one atomic snapshot, or None if absent."""
    try:
        data = Path(path).read_bytes()
    except FileNotFoundError:
        return None
    return digest_bytes(data)


@contextmanager
def recovery_lock(path: Path):
    """Hold an OS lock which is released when the handle or process closes."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep the lock file in place: unlinking it permits locks on different files.
    with path.with_name(path.name + ".lock").open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RecoveryBusy from exc
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RecoveryBusy from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def write_if_current(data: str, path: Path, expected: str | None, writer) -> tuple[str, str | None]:
    """Write only the recovery version this session observed or last saved."""
    try:
        with recovery_lock(path):
            if file_digest(path) != expected:
                return "conflict", None
            if not writer(data, path):
                return "failed", None
            return "saved", file_digest(path)
    except RecoveryBusy:
        return "busy", None
    except Exception:
        return "failed", None
