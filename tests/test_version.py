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
    normalized_readme = " ".join(readme.split())

    assert "Current release: **Sector 0.92**" in readme
    assert "no Windows executable is published" in normalized_readme
    assert "## 0.92 - 2026-08-08" in changelog
    assert "source/application code only" in changelog
    assert "No EXE, MSI or unsigned QA package is a release asset" in acceptance
