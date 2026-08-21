"""Subprocess-only protocol worker used by publication exporter tests."""

from __future__ import annotations

import base64
import json
import pathlib
import subprocess
import sys
import time


def main() -> None:
    if len(sys.argv) != 2:
        raise RuntimeError("test image worker requires one encoded scenario")
    scenario = json.loads(base64.urlsafe_b64decode(sys.argv[1]).decode("utf-8"))
    reader = sys.stdin.buffer
    writer = sys.stdout.buffer
    sys.stdout = sys.stderr

    root = pathlib.Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "app"))
    import publication_image_export as image_export

    connection = image_export._SynchronousStreamConnection(reader, writer)
    tree_guard = None
    descendant = None
    try:
        tree_guard = image_export._own_descendant_processes()
        connection.send(("booted",))
        if connection.recv() != ("proceed",):
            raise RuntimeError("test worker received no ownership acknowledgement")
        if scenario.get("startup_error"):
            connection.send(("startup-error", "RuntimeError", "browser unavailable"))
            return
        if scenario.get("startup_block"):
            time.sleep(30)
            return
        entered_file = scenario.get("page_entered_file")
        release_file = scenario.get("page_release_file")
        if entered_file:
            pathlib.Path(entered_file).write_text("entered", encoding="ascii")
            deadline = time.monotonic() + 30.0
            while release_file and not pathlib.Path(release_file).exists():
                if time.monotonic() >= deadline:
                    raise RuntimeError("test page factory was not released")
                time.sleep(0.01)
        ready_file = scenario.get("ready_file")
        if ready_file:
            deadline = time.monotonic() + 10.0
            while not pathlib.Path(ready_file).exists():
                if time.monotonic() >= deadline:
                    raise RuntimeError("test ready release was not created")
                time.sleep(0.01)
        descendant_file = scenario.get("descendant_file")
        if descendant_file:
            descendant = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            pathlib.Path(descendant_file).write_text(
                str(descendant.pid), encoding="ascii"
            )
        connection.send(("ready",))
        while True:
            message = connection.recv()
            if message == ("stop",):
                return
            _, request_id, figure_json, options = message
            if scenario.get("render_block"):
                time.sleep(30)
                return
            if scenario.get("render_error"):
                connection.send(("error", request_id, "ValueError", "bad figure"))
                continue
            delay = float(scenario.get("render_delay", 0.0))
            if delay:
                time.sleep(delay)
            response = json.dumps(
                {"figure": json.loads(figure_json), "options": options},
                sort_keys=True,
            ).encode("utf-8")
            connection.send(
                ("result", request_id, image_export._PNG_SIGNATURE + response)
            )
    finally:
        del tree_guard
        if descendant is not None and descendant.poll() is None:
            descendant.terminate()
        connection.close()


if __name__ == "__main__":
    main()
