"""Bounded start of the shared Kaleido exporter for the render jobs.

The report and manual render fixtures and their real-image tests export every
figure through the killable worker of ``app/publication_image_export.py``. The
start of that worker launches a browser, which can fail or hang under load.
This helper starts the worker before the first figure with a time limit for
each attempt, and starts it one more time after a failed attempt (owner rule,
9 November 2026). Only the start is tried again, never an export or a test.
"""

from __future__ import annotations

import pathlib
import sys
from collections.abc import Callable

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
# Normal start on a CI runner: a few seconds. The report itself allows 20 s.
START_LIMIT_S = 60.0
START_ATTEMPTS = 2


def exporter_module():
    """Return the exporter module that ``sector_report`` and ``manual`` use.

    The app modules import ``publication_image_export`` as a top-level module
    from ``app/``. An import as ``app.publication_image_export`` would make a
    second module with a second, idle coordinator.
    """
    if str(APP) not in sys.path:
        sys.path.insert(0, str(APP))
    import publication_image_export

    return publication_image_export


def start_image_exporter(
    *,
    limit: float = START_LIMIT_S,
    attempts: int = START_ATTEMPTS,
    ensure_ready: Callable[..., None] | None = None,
) -> int:
    """Start the shared exporter and return the number of the attempt that started it.

    Each attempt that fails discards its worker process tree inside the
    coordinator, so the next attempt starts a clean browser. The error of the
    last attempt goes to the caller.
    """
    if attempts < 1:
        raise ValueError("the exporter start needs at least one attempt")
    exporter = exporter_module()
    start_error: type[Exception] = exporter.KaleidoExportError
    if ensure_ready is None:
        ensure_ready = exporter.ensure_ready
    for attempt in range(1, attempts + 1):
        try:
            ensure_ready(timeout=limit)
        except start_error as exc:
            if attempt == attempts:
                raise
            print(
                f"Kaleido start attempt {attempt} of {attempts} failed ({exc}); "
                "starting the exporter again",
                file=sys.stderr,
                flush=True,
            )
        else:
            return attempt
    raise AssertionError("unreachable")
