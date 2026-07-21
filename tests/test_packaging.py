"""Smoke tests for the packaging launcher's path resolution.

These exercise ``packaging/run_sector.py`` without building or starting Streamlit
(its Streamlit import lives inside ``main``), so they are fast and need no bundle.
"""

from __future__ import annotations

import pathlib
import sys
import tomllib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "packaging"))

import run_sector  # noqa: E402


def test_packaging_files_are_in_the_repo():
    # All build inputs must be committed -- notably sector.spec, which the generic
    # .gitignore *.spec rule would drop (it is negated for this one). On a clean
    # checkout (CI) a missing file is simply absent, so this catches it.
    pkg = pathlib.Path(__file__).resolve().parent.parent / "packaging"
    for name in ("sector.spec", "run_sector.py", "build.ps1", "build.bat",
                 "README.md"):
        assert (pkg / name).is_file(), f"packaging/{name} missing from the repo"


def test_build_script_uses_the_hashed_lock():
    root = pathlib.Path(__file__).resolve().parent.parent
    script = (root / "packaging" / "build.ps1").read_text(encoding="utf-8")
    assert "--require-hashes -r requirements-build.txt" in script
    assert '"pyinstaller>=' not in script.lower()


def test_distribution_notices_are_generated_and_package_gated():
    root = pathlib.Path(__file__).resolve().parent.parent
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md",
                 "tools/generate_third_party_notices.py"):
        assert (root / name).is_file(), f"{name} missing from the repository"
    build = (root / "packaging" / "build.ps1").read_text(encoding="utf-8")
    workflow = (root / ".github" / "workflows" / "qa.yml").read_text(
        encoding="utf-8"
    )
    for text in (build, workflow):
        assert "generate_third_party_notices.py" in text
        assert "dist/Sector/LICENSE.txt" in text
        assert "dist/Sector/THIRD_PARTY_NOTICES.txt" in text


def test_kaleido_cli_mocker_is_excluded_from_the_frozen_runtime():
    root = pathlib.Path(__file__).resolve().parent.parent
    spec = (root / "packaging" / "sector.spec").read_text(encoding="utf-8")
    assert "filter_submodules" in spec
    assert 'name.startswith("kaleido.mocker")' in spec


def test_packaged_runtime_embeds_exact_source_provenance():
    root = pathlib.Path(__file__).resolve().parent.parent
    spec = (root / "packaging" / "sector.spec").read_text(encoding="utf-8")
    workflow = (root / ".github" / "workflows" / "qa.yml").read_text(
        encoding="utf-8"
    )
    assert "sector_build_info.json" in spec
    assert "GITHUB_SHA" in spec
    assert "source_revision" in spec
    assert "subprocess" not in spec
    assert "sector/sector_build_info.json" in workflow


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


def test_default_port_is_8502_so_it_does_not_clash_with_bricos(monkeypatch):
    # BriCoS uses Streamlit's default 8501; Sector defaults to 8502 so both can
    # be open at once. The launcher passes it as --server.port.
    monkeypatch.delenv("SECTOR_PORT", raising=False)
    assert run_sector._port() == "8502"
    argv = run_sector._streamlit_argv("app/sector_app.py", run_sector._port())
    assert "--server.port=8502" in argv
    assert "--server.address=127.0.0.1" in argv
    assert "--browser.gatherUsageStats=false" in argv
    assert "--client.toolbarMode=viewer" in argv
    assert "--client.showErrorDetails=type" in argv
    assert argv[:3] == ["streamlit", "run", "app/sector_app.py"]


def test_port_is_overridable_via_env(monkeypatch):
    monkeypatch.setenv("SECTOR_PORT", "8600")
    assert run_sector._port() == "8600"
    assert "--server.port=8600" in run_sector._streamlit_argv("x", run_sector._port())


def _dev_streamlit_config():
    cfg = pathlib.Path(__file__).resolve().parent.parent / ".streamlit" / "config.toml"
    assert cfg.is_file()
    with cfg.open("rb") as handle:
        return tomllib.load(handle)


def test_dev_streamlit_config_is_local_and_production_safe():
    # Direct `streamlit run` must retain the packaged launcher's local-only and
    # user-facing behavior instead of exposing a developer console on the LAN.
    cfg = _dev_streamlit_config()
    assert cfg["server"] == {"port": 8502, "address": "127.0.0.1"}
    assert cfg["client"]["toolbarMode"] == "viewer"
    assert cfg["client"]["showErrorDetails"] == "type"
    assert cfg["browser"]["gatherUsageStats"] is False


def _run_app():
    root = pathlib.Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import run_app
    return run_app


def test_root_launcher_defaults_to_8502(monkeypatch):
    # The README's primary dev command is `python run_app.py`; it must default to
    # 8502 too, so the common launch path does not clash with BriCoS.
    monkeypatch.delenv("SECTOR_PORT", raising=False)
    assert _run_app()._port() == "8502"


def test_root_launcher_port_is_overridable(monkeypatch):
    monkeypatch.setenv("SECTOR_PORT", "8600")
    assert _run_app()._port() == "8600"


def test_root_launcher_is_local_only_and_disables_telemetry():
    argv = _run_app()._streamlit_argv("app/sector_app.py", "8502")
    assert argv[:3] == ["streamlit", "run", "app/sector_app.py"]
    assert argv[argv.index("--server.address") + 1] == "127.0.0.1"
    assert argv[argv.index("--browser.gatherUsageStats") + 1] == "false"
    assert argv[argv.index("--client.toolbarMode") + 1] == "viewer"
    assert argv[argv.index("--client.showErrorDetails") + 1] == "type"
