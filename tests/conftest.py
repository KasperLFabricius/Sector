"""Shared pytest fixtures."""

from __future__ import annotations

import pytest


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
