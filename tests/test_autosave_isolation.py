"""Module fixtures must not share an autosave folder or use the home folder.

A shared autosave lets a slow fixture app leak its project into the next fixture
app, which restores the autosave on launch.
"""

from __future__ import annotations

import os
import pathlib

import pytest


@pytest.fixture(scope="module")
def first_folder():
    return os.environ.get("SECTOR_AUTOSAVE_DIR")


@pytest.fixture(scope="module")
def second_folder():
    return os.environ.get("SECTOR_AUTOSAVE_DIR")


def test_each_module_fixture_has_its_own_autosave_folder(first_folder, second_folder):
    home = pathlib.Path.home() / ".sector"
    assert first_folder and second_folder
    assert first_folder != second_folder
    assert pathlib.Path(first_folder) != home
    assert pathlib.Path(second_folder) != home
