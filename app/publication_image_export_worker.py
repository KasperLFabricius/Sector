"""Dedicated subprocess entry point for publication image exports.

This file is launched directly by source installations.  The frozen launcher
executes the same file only after routing Sector's private worker flag, before
Streamlit or ``app/sector_app.py`` can start.
"""

from __future__ import annotations

import pathlib
import sys
from typing import BinaryIO


def _protocol_streams() -> tuple[BinaryIO, BinaryIO]:
    reader = sys.stdin.buffer
    writer = sys.stdout.buffer
    # Keep the protocol on the captured binary stream.  Any later diagnostic
    # print from Kaleido/Chrome is redirected away from the framed channel.
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
