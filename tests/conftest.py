"""Shared pytest fixtures."""

from __future__ import annotations
import os
import tempfile


import pytest

from tools.qa_core_shards import load_durations, module_seconds, node_row, seconds_for

# A test is marked ``slow`` when its CI duration in tools/qa_shard_durations.json,
# or the mean CI duration of all tests in its module, reaches this many seconds.
# Tests of one module share report and native-run caches: CI charges the shared
# cost to the first test that runs, but a test alone can pay all of it. Every
# serial real-image export test is slow too. ``-m "not slow"`` selects the fast
# local tier; CI ignores the marker and runs every test.
SLOW_SECONDS = 1.0


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):
    """Mark slow tests from the shard duration table before marker selection."""
    durations = load_durations()
    for item in items:
        node, _ = node_row(item)
        seconds = max(seconds_for(node, durations), module_seconds(node, durations))
        if item.get_closest_marker("real_image_export") or seconds >= SLOW_SECONDS:
            item.add_marker(pytest.mark.slow)


@pytest.hookimpl(hookwrapper=True)
def pytest_fixture_setup(fixturedef):
    """Give each module or session fixture its own autosave folder.

    These fixtures run before ``_isolate_autosave``. A setup that takes longer than
    the autosave interval would otherwise write ``~/.sector/autosave.json``, and the
    next fixture app, also in another worker, would restore that project on launch.
    A fixture that sets its own folder keeps it.
    """
    if fixturedef.scope == "function":
        yield
        return
    previous = os.environ.get("SECTOR_AUTOSAVE_DIR")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        os.environ["SECTOR_AUTOSAVE_DIR"] = folder
        yield
    if os.environ.get("SECTOR_AUTOSAVE_DIR") == folder:
        if previous is None:
            del os.environ["SECTOR_AUTOSAVE_DIR"]
        else:
            os.environ["SECTOR_AUTOSAVE_DIR"] = previous


@pytest.fixture(autouse=True)
def _isolate_autosave(tmp_path, monkeypatch):
    """Point the autosave at a per-test temp folder.

    The app restores the last autosave on launch, so without this every AppTest that
    did not set the path itself would read (and could write) the real
    ``~/.sector/autosave.json`` -- leaking a developer's last session into the tests
    and clobbering it. A test that needs a specific location overrides this with its
    own ``monkeypatch.setenv``.
    """
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path / "_autosave"))


@pytest.fixture(scope="session", autouse=True)
def _retain_callable_page_client():
    """Match browser page identity in module fixtures and native test bodies."""
    from native_callable_page_client import install_callable_page_client

    patch = pytest.MonkeyPatch()
    try:
        install_callable_page_client(patch)
        yield
    finally:
        patch.undo()
