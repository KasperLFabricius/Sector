"""Hang guard for the real-image export tests (owner rule, 9 November 2026).

On 8 November 2026 a real-image test in ``tests/test_viz.py`` hung for 2 h in
CI. Plotly calls Kaleido, and without a running Kaleido server each export
starts a browser in a new thread, which Kaleido 1.5 joins with no time limit
(``kaleido._sync_server.oneshot_async_run``). This guard gives each real-image
test two limits:

- Each in-process Kaleido start, with its export, has a time limit. After a
  time-out or an error inside the one-shot runner, the start is tried one more
  time. An error that occurs in both starts goes to the test. The test itself
  is never run again. Plotly validates a figure before it calls Kaleido, so a
  validation error does not get a second start.
- Each real-image test has a hard limit from the start of the test call. A
  test that passes it writes the stack of every thread and stops the test
  process with the exit code of the shard hang limit. The phase and step
  limits of ``tools/qa_core_shards.py`` and ``qa.yml`` cover fixtures and the
  session finish.

``conftest.py`` applies the guard to every test with the ``real_image_export``
marker.
"""

from __future__ import annotations

import asyncio
import os
import queue
import sys
import threading
import traceback
from collections.abc import Callable
from typing import Any, Self

# The normal real-image test takes less than 60 s, and one in-process export
# about 3 s on a CI runner.
REAL_IMAGE_TEST_LIMIT_S = 300.0
KALEIDO_START_LIMIT_S = 90.0
KALEIDO_START_ATTEMPTS = 2
# The same code as REAL_PHASE_TIMEOUT_EXIT in tools/qa_core_shards.py, so that
# the gate names the phase. pytest itself uses the codes 0 to 5.
HANG_EXIT_CODE = 124


class KaleidoStartTimeout(TimeoutError):
    """No in-process Kaleido start and export finished inside its limits."""


def bounded_oneshot_async_run(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    *,
    limit: float = KALEIDO_START_LIMIT_S,
    attempts: int = KALEIDO_START_ATTEMPTS,
) -> Any:
    """Replace Kaleido's one-shot runner with a time limit for each start.

    The argument order is that of ``kaleido._sync_server.oneshot_async_run``.
    A timed-out start stays in a daemon thread, so it cannot block the exit of
    the test process.
    """
    for attempt in range(1, attempts + 1):
        # Each attempt has its own queue: a late result of a timed-out start
        # cannot reach a later attempt.
        result: queue.Queue[Any] = queue.Queue(maxsize=1)
        worker = threading.Thread(
            target=_run_once,
            args=(func, args, kwargs, result),
            name=f"sector-kaleido-start-{attempt}",
            daemon=True,
        )
        worker.start()
        worker.join(limit)
        if worker.is_alive():
            reason = f"did not finish in {limit:.0f} s"
        else:
            value = result.get_nowait()
            if not isinstance(value, BaseException):
                return value
            if not isinstance(value, Exception) or attempt == attempts:
                raise value
            reason = f"failed ({type(value).__name__}: {value})"
        sys.stderr.write(f"Kaleido start {attempt} of {attempts} {reason}\n")
    raise KaleidoStartTimeout(
        f"Kaleido did not start and export in {attempts} attempts of {limit:.0f} s"
    )


def _run_once(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    result: queue.Queue[Any],
) -> None:
    try:
        result.put(asyncio.run(func(*args, **kwargs)))
    except BaseException as exc:  # noqa: BLE001 - the caller raises it
        result.put(exc)


class RealImageTimeLimit:
    """Stop the test process when one real-image test passes its hard limit."""

    def __init__(
        self,
        nodeid: str,
        config: Any,
        *,
        limit: float = REAL_IMAGE_TEST_LIMIT_S,
        stop: Callable[[int], None] = os._exit,
    ) -> None:
        self._nodeid = nodeid
        self._config = config
        self._limit = limit
        self._stop = stop
        self._timer = threading.Timer(limit, self._expire)
        self._timer.daemon = True
        self._timer.name = "sector-real-image-time-limit"

    def __enter__(self) -> Self:
        self._timer.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._timer.cancel()

    def _expire(self) -> None:
        try:
            self._report()
        finally:
            self._stop(HANG_EXIT_CODE)

    def _report(self) -> None:
        # Show the dump on the console: pytest captures stderr during a test.
        capture = None
        if self._config is not None:
            capture = self._config.pluginmanager.getplugin("capturemanager")
        if capture is not None:
            capture.suspend_global_capture(in_=True)
        sys.stderr.write(
            f"\nREAL-IMAGE HANG GUARD: {self._nodeid} did not finish in "
            f"{self._limit:.0f} s. The stacks of all threads follow, and the "
            "test process stops.\n"
        )
        names = {thread.ident: thread.name for thread in threading.enumerate()}
        for ident, frame in sys._current_frames().items():
            sys.stderr.write(f"\nThread {names.get(ident, ident)}:\n")
            sys.stderr.write("".join(traceback.format_stack(frame)))
        sys.stderr.flush()
