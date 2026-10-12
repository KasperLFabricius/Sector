"""Product-version and ordinary internal-distribution contract."""

from pathlib import Path

from sector import __author__, __licensee__, __version__

ROOT = Path(__file__).resolve().parents[1]


def test_release_version_is_0_96_7():
    assert __version__ == "0.96.7"
    assert __author__ == "Kasper Lindskov Fabricius"
    assert __licensee__ == "Sweco Danmark A/S"


def test_internal_version_declares_the_simple_unsigned_portable_build():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    release_notes = (ROOT / "docs" / "v0967_release_notes.md").read_text(
        encoding="utf-8"
    )
    product_identity = (ROOT / "docs" / "product_identity.md").read_text(
        encoding="utf-8"
    )
    manual_source = (ROOT / "app" / "manual.py").read_text(encoding="utf-8")
    project_io_source = (ROOT / "app" / "project_io.py").read_text(encoding="utf-8")
    assert "Current internal version: **Sector 0.96.7**" in readme
    assert "[v0.96.7 release notes](docs/v0967_release_notes.md)" in readme
    assert "`BUILD.bat` creates `Sector-v0.96.7-windows-portable.zip`" in readme
    assert "## 0.96.7 - 2026-10-11" in changelog
    assert release_notes.startswith("# Sector 0.96.7 notes\n")
    assert "Supported project schema: 27" in release_notes
    assert "Sector-v0.96.7-windows-portable" in release_notes
    assert "release receipt" not in readme.casefold()
    assert "authenticated draft" not in readme.casefold()
    for live_surface in (product_identity, project_io_source):
        assert "Sector is unreleased" not in live_surface
        assert "Sector 0.96.7" in live_surface
    assert '<meta name="sector-version"' in manual_source
    assert "source_revision" not in manual_source
    assert "sector-source-revision" not in manual_source


def test_manual_asset_manifest_matches_the_release_version():
    import json

    manifest = json.loads(
        (ROOT / "assets/manual/manifest.json").read_text(encoding="ascii")
    )
    assert manifest["version"] == __version__


def test_workspace_asset_has_the_current_version_without_image_export(monkeypatch):
    import hashlib
    import json

    monkeypatch.syspath_prepend(str(ROOT / "app"))
    import manual

    def unexpected_export(*args, **kwargs):
        raise AssertionError("The version check must not start image export")

    monkeypatch.setattr(manual.publication_image_export, "export_png", unexpected_export)
    figure = manual.fig_workspace_overview()
    assert manual.APP_VERSION == __version__
    assert figure.layout.title.text == f"Sector v{__version__} - workspace schematic"
    manifest = json.loads(
        (ROOT / "assets/manual/manifest.json").read_text(encoding="ascii")
    )
    record = manifest["figures"]["fig_workspace_overview"]
    assert hashlib.sha256(figure.to_json().encode("utf-8")).hexdigest() == record["figure_sha256"]
    png = (ROOT / "assets/manual/fig_workspace_overview.png").read_bytes()
    assert hashlib.sha256(png).hexdigest() == record["png_sha256"]
