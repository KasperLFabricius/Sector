"""Release-version and source/application publication contract."""

from pathlib import Path

from sector import __author__, __licensee__, __version__

ROOT = Path(__file__).resolve().parents[1]


def test_release_version_is_0_93():
    assert __version__ == "0.93"
    assert __author__ == "Kasper Lindskov Fabricius"
    assert __licensee__ == "Sweco Danmark A/S"


def test_release_candidate_declares_draft_source_and_unsigned_portable_assets():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    acceptance = (ROOT / "docs" / "pr09_v093_release_acceptance.md").read_text(
        encoding="utf-8"
    )
    product_identity = (ROOT / "docs" / "product_identity.md").read_text(
        encoding="utf-8"
    )
    manual_source = (ROOT / "app" / "manual.py").read_text(encoding="utf-8")
    project_io_source = (ROOT / "app" / "project_io.py").read_text(encoding="utf-8")
    normalized_readme = " ".join(readme.split())

    assert "Current release candidate: **Sector 0.93**" in readme
    assert "No signed installer is prepared" in normalized_readme
    assert "Sector 0.92 remains the last publicly published release" in normalized_readme
    assert "## 0.93 release candidate - 2026-08-11" in changelog
    assert "provenance-bearing" in readme
    assert "`Sector-v0.93-source.zip`" in acceptance
    assert "`Sector-v0.93-windows-portable-unsigned.zip`" in acceptance
    for live_surface in (product_identity, manual_source, project_io_source):
        assert "Sector is unreleased" not in live_surface
        assert "Sector 0.93" in live_surface
