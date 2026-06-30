"""Smoke tests for the packaging launcher's path resolution.

These exercise ``packaging/run_sector.py`` without building or starting Streamlit
(its Streamlit import lives inside ``main``), so they are fast and need no bundle.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "packaging"))

import run_sector  # noqa: E402


def test_bundle_base_resolves_to_the_app_tree_in_dev():
    base = run_sector._bundle_base()
    assert (base / "app" / "sector_app.py").is_file()
    assert (base / "sector" / "__init__.py").is_file()


def test_user_data_dir_uses_localappdata(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert run_sector._user_data_dir() == tmp_path / "Sector"


def test_user_data_dir_falls_back_to_home(monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert run_sector._user_data_dir() == pathlib.Path.home() / ".sector"
