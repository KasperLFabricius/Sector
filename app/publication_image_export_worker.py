"""Dedicated subprocess entry point for publication image exports.

This file is launched directly by source installations.  The frozen launcher
executes the same file only after routing Sector's private worker flag, before
Streamlit or ``app/sector_app.py`` can start.
"""

from __future__ import annotations

import os
import pathlib
import sys
from typing import BinaryIO


def _publish_windows_standard_handle(descriptor: int, standard_handle: int) -> None:
    """Keep subprocess defaults on a valid native null handle after ``dup2``."""

    if os.name != "nt":
        return
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.SetStdHandle.argtypes = (wintypes.DWORD, wintypes.HANDLE)
    kernel32.SetStdHandle.restype = wintypes.BOOL
    native_handle = msvcrt.get_osfhandle(descriptor)
    if not kernel32.SetStdHandle(standard_handle, native_handle):
        raise ctypes.WinError(ctypes.get_last_error())


def _protocol_streams() -> tuple[BinaryIO, BinaryIO]:
    """Detach framed IPC from inherited standard handles before imports."""

    stdin_fd = sys.stdin.buffer.fileno()
    stdout_fd = sys.stdout.buffer.fileno()
    reader_fd = os.dup(stdin_fd)
    writer_fd = os.dup(stdout_fd)
    try:
        os.set_inheritable(reader_fd, False)
        os.set_inheritable(writer_fd, False)
        null_reader = os.open(os.devnull, os.O_RDONLY)
        try:
            os.dup2(null_reader, stdin_fd, inheritable=False)
        finally:
            os.close(null_reader)
        _publish_windows_standard_handle(stdin_fd, -10)
        null_writer = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(null_writer, stdout_fd, inheritable=False)
        finally:
            os.close(null_writer)
        _publish_windows_standard_handle(stdout_fd, -11)
        reader = os.fdopen(reader_fd, "rb", buffering=0)
        reader_fd = -1
        writer = os.fdopen(writer_fd, "wb", buffering=0)
        writer_fd = -1
    finally:
        for descriptor in (reader_fd, writer_fd):
            if descriptor >= 0:
                os.close(descriptor)

    # Python, native libraries and inherited browser processes now see only
    # the null standard handles; the private non-inheritable duplicates carry
    # Sector's framed protocol.
    sys.stdout = sys.stderr
    return reader, writer


def main() -> None:
    if len(sys.argv) != 1:
        raise RuntimeError("publication image worker accepts no arguments")
    reader, writer = _protocol_streams()
    app_folder = pathlib.Path(__file__).resolve().parent
    app_path = str(app_folder)
    if app_path not in sys.path:
        sys.path.insert(0, app_path)

    import publication_image_export as image_export

    connection = image_export._SynchronousStreamConnection(reader, writer)
    image_export._worker_main(connection, image_export._kaleido_page_path)


if __name__ == "__main__":
    main()
