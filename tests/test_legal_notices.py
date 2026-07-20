"""Checks for the generated proprietary and third-party distribution record."""

from __future__ import annotations

from pathlib import Path

from tools.generate_third_party_notices import build_notice


ROOT = Path(__file__).resolve().parent.parent


def test_proprietary_notice_grants_no_public_licence():
    text = (ROOT / "LICENSE").read_text(encoding="ascii")
    assert "proprietary software" in text.lower()
    assert "No permission is granted" in text
    assert "Third-party components" in text


def test_generated_notice_is_deterministic_and_includes_embedded_frontend():
    tabulator = ROOT / "app" / "point_grid_frontend" / "LICENSE"
    first = build_notice(tabulator_license=tabulator)
    second = build_notice(tabulator_license=tabulator)
    assert first == second
    assert "SECTOR THIRD-PARTY NOTICES" in first
    assert "Tabulator (embedded point-grid frontend)" in first
    assert "Permission is hereby granted" in first
    assert "numpy" in first.lower()
