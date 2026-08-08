"""Release-version and source/application publication contract."""

from pathlib import Path

from sector import __author__, __licensee__, __version__

ROOT = Path(__file__).resolve().parents[1]


def test_release_version_is_0_92():
    assert __version__ == "0.92"
    assert __author__ == "Kasper Lindskov Fabricius"
    assert __licensee__ == "Sweco Danmark A/S"


def test_release_is_declared_as_source_application_only():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    acceptance = (
        ROOT / "docs" / "pr15_v092_source_app_release_acceptance.md"
    ).read_text(encoding="utf-8")
    product_identity = (ROOT / "docs" / "product_identity.md").read_text(
        encoding="utf-8"
    )
    manual_source = (ROOT / "app" / "manual.py").read_text(encoding="utf-8")
    project_io_source = (ROOT / "app" / "project_io.py").read_text(encoding="utf-8")
    normalized_readme = " ".join(readme.split())

    assert "Current release: **Sector 0.92**" in readme
    assert "no Windows executable is published" in normalized_readme
    assert "## 0.92 - 2026-08-08" in changelog
    assert "exact-commit source/application ZIP" in changelog
    assert "No EXE, MSI or unsigned QA package is a release asset" in acceptance
    assert "`Sector-v0.92-source.zip` asset" in acceptance
    for live_surface in (product_identity, manual_source, project_io_source):
        assert "Sector is unreleased" not in live_surface
        assert "Sector 0.92" in live_surface
