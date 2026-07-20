"""Smoke tests for the packaging launcher's path resolution.

These exercise ``packaging/run_sector.py`` without building or starting Streamlit
(its Streamlit import lives inside ``main``), so they are fast and need no bundle.
"""

from __future__ import annotations

import pathlib
import sys

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
    assert argv[:3] == ["streamlit", "run", "app/sector_app.py"]


def test_port_is_overridable_via_env(monkeypatch):
    monkeypatch.setenv("SECTOR_PORT", "8600")
    assert run_sector._port() == "8600"
    assert "--server.port=8600" in run_sector._streamlit_argv("x", run_sector._port())


def test_dev_streamlit_config_pins_the_same_port():
    # The dev-run config (streamlit run app/sector_app.py) must pin the same port
    # as the packaged launcher, so both paths serve on 8502.
    cfg = pathlib.Path(__file__).resolve().parent.parent / ".streamlit" / "config.toml"
    assert cfg.is_file()
    assert "port = 8502" in cfg.read_text(encoding="utf-8")


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
