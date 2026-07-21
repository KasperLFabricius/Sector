"""Checks for the generated proprietary and third-party distribution record."""

from __future__ import annotations

from pathlib import Path

from tools.generate_third_party_notices import build_notice, distributions_from_lock


ROOT = Path(__file__).resolve().parent.parent


def test_proprietary_notice_grants_no_public_licence():
    text = (ROOT / "LICENSE").read_text(encoding="ascii")
    assert "proprietary software" in text.lower()
    assert "Kasper Lindskov Fabricius" in text
    assert "Sweco Danmark A/S, CVR 48233511, Denmark" in text
    assert "does not grant any person a personal licence" in text
    assert "public or external distribution" in text
    assert "No permission is granted" in text
    assert "Third-party components" in text


def test_generated_notice_is_deterministic_and_includes_embedded_frontend():
    tabulator = ROOT / "app" / "point_grid_frontend" / "LICENSE"
    # The QA job installs requirements-dev.txt, which contains the complete
    # runtime lock but intentionally omits PyInstaller-only packages. Exercise
    # selection with that installed runtime subset; the Windows package job runs
    # the CLI against requirements-build.txt and fails there if any build pin is
    # absent or mismatched.
    locked = distributions_from_lock(ROOT / "requirements.txt")
    first = build_notice(distributions=locked, tabulator_license=tabulator)
    second = build_notice(distributions=locked, tabulator_license=tabulator)
    assert first == second
    assert "SECTOR THIRD-PARTY NOTICES" in first
    assert "Tabulator (embedded point-grid frontend)" in first
    assert "Permission is hereby granted" in first
    assert "numpy" in first.lower()
    assert "\npytest " not in first.lower()  # installed for QA, absent from build lock


def test_locked_inventory_rejects_a_missing_or_mismatched_distribution(tmp_path):
    lock = tmp_path / "requirements.txt"
    lock.write_text("numpy==0.0.0 \\\n    --hash=sha256:" + "0" * 64 + "\n", encoding="utf-8")
    try:
        distributions_from_lock(lock)
    except RuntimeError as exc:
        assert "numpy==0.0.0" in str(exc)
    else:  # pragma: no cover - guards the fail-closed contract
        raise AssertionError("A mismatched lock entry was accepted")
