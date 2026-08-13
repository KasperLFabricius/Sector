"""Product-version and ordinary internal-distribution contract."""

from pathlib import Path

from sector import __author__, __licensee__, __version__

ROOT = Path(__file__).resolve().parents[1]


def test_release_version_is_0_93():
    assert __version__ == "0.93"
    assert __author__ == "Kasper Lindskov Fabricius"
    assert __licensee__ == "Sweco Danmark A/S"


def test_internal_version_declares_the_simple_unsigned_portable_build():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    product_identity = (ROOT / "docs" / "product_identity.md").read_text(
        encoding="utf-8"
    )
    manual_source = (ROOT / "app" / "manual.py").read_text(encoding="utf-8")
    project_io_source = (ROOT / "app" / "project_io.py").read_text(encoding="utf-8")
    assert "Current internal version: **Sector 0.93**" in readme
    assert "`BUILD.bat` creates `Sector-v0.93-windows-portable.zip`" in readme
    assert "## 0.93 - 2026-08-11" in changelog
    assert "release receipt" not in readme.casefold()
    assert "authenticated draft" not in readme.casefold()
    for live_surface in (product_identity, manual_source, project_io_source):
        assert "Sector is unreleased" not in live_surface
        assert "Sector 0.93" in live_surface
