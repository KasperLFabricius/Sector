"""Fast tests for the user-facing Windows build and frozen launcher."""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging"))

import run_sector


def test_single_packaging_path_is_present_and_retired_paths_are_absent():
    for relative in (
        "BUILD.bat",
        "BUILD_SECTOR_PORTABLE.bat",
        "packaging/build.bat",
        "packaging/build_portable.ps1",
        "packaging/sector.spec",
        "packaging/run_sector.py",
        "packaging/README.md",
        "packaging/README-PORTABLE.txt",
        "tools/build_portable_windows.py",
        "tools/verify_portable_image_export.py",
        "tools/verify_portable_startup.py",
    ):
        assert (ROOT / relative).is_file()
    for relative in (
        "packaging/build.ps1",
        "packaging/build_qa.bat",
        "packaging/sign_and_verify.ps1",
    ):
        assert not (ROOT / relative).exists()


def test_root_build_is_self_relative_nontelevated_and_accepts_generic_source():
    wrapper = (ROOT / "BUILD.bat").read_text(encoding="utf-8")
    folded = wrapper.casefold()
    assert "%~dp0packaging\\build_portable.ps1" in wrapper
    assert "%~dp0tools\\build_portable_windows.py" in wrapper
    assert "%~dp0requirements-build.txt" in wrapper
    assert '"%sector_powershell%"' in folded
    assert "-noprofile" in folded
    assert "-executionpolicy bypass" in folded
    assert "runas" not in folded
    assert "start-process" not in folded
    assert "source_manifest" not in folded
    assert "authenticate" not in folded
    assert "sector-main.zip" not in folded
    assert "extract all" in folded


def test_legacy_build_names_are_simple_aliases():
    legacy = (ROOT / "BUILD_SECTOR_PORTABLE.bat").read_text(encoding="utf-8")
    packaging = (ROOT / "packaging" / "build.bat").read_text(encoding="utf-8")
    assert "%~dp0BUILD.bat" in legacy
    assert "%~dp0..\\BUILD.bat" in packaging
    assert "build_portable.ps1" not in legacy
    assert "build_portable.ps1" not in packaging


def test_build_wrapper_resolves_python_and_delegates_once():
    script = (ROOT / "packaging" / "build_portable.ps1").read_text("utf-8")
    folded = script.casefold()
    for token in ('-cne "cpython"', '-cne "3"', '-cne "13"', '-cne "64"'):
        assert token in folded
    assert "sectorbuilds\\build-" in folded
    assert '$driver = Join-Path $sourceRoot "tools/build_portable_windows.py"' in script
    assert '"--python"' in script
    assert '"--source-revision"' in script
    assert "first-page execution" in folded
    for removed in (
        "portable-distribution.json",
        "source-identity",
        "authenticated source",
        "verify_windows_release",
        "verify_reproducible",
        "sign_and_verify",
    ):
        assert removed not in folded


def test_user_documentation_describes_the_actual_small_output():
    readme = (ROOT / "packaging" / "README.md").read_text("utf-8")
    portable = (ROOT / "packaging" / "README-PORTABLE.txt").read_text("utf-8")
    for text in (readme, portable):
        assert "first Streamlit page" in text or "first page" in text
        assert "folder" in text
        assert "ZIP" in text
        assert "SHA-256" in text
        assert "unsigned" in text
        assert "receipt" not in text.casefold()
        assert "authenticated" not in text.casefold()
        assert "certificate" not in text.casefold()
    assert portable.count("@SECTOR_VERSION@") == 1


def test_build_uses_the_hash_locked_environment_and_notice_generator():
    driver = (ROOT / "tools" / "build_portable_windows.py").read_text("utf-8")
    assert '"--require-hashes"' in driver
    assert '"requirements-build.txt"' in driver
    assert '"generate_third_party_notices.py"' in driver
    assert '"THIRD_PARTY_NOTICES.txt"' in driver
    lock = (ROOT / "requirements-build.txt").read_text("utf-8")
    assert "--hash=sha256:" in lock


def test_frozen_runtime_has_only_the_needed_dynamic_server_imports():
    spec = (ROOT / "packaging" / "sector.spec").read_text("utf-8")
    for module in (
        "uvicorn.lifespan.on",
        "uvicorn.loops.asyncio",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.http.httptools_impl",
        "uvicorn.protocols.websockets.websockets_sansio_impl",
        "anyio._backends._asyncio",
    ):
        assert spec.count(f'"{module}"') == 1
    assert 'collect_all("uvicorn")' not in spec
    assert 'collect_all("anyio")' not in spec
    assert "anyio._backends._trio" not in spec


def test_developer_only_modules_are_excluded_and_installer_records_are_omitted():
    spec = (ROOT / "packaging" / "sector.spec").read_text("utf-8")
    assert 'name.startswith("kaleido.mocker")' in spec
    assert 'name.startswith("plotly.matplotlylib")' in spec
    assert '"tests"' in spec
    assert "filter_submodules=_runtime_module" in spec
    assert "_runtime_package_data" in spec
    assert '"labextension"' in spec
    assert '"include"' in spec
    assert '".py"' in spec
    assert "_without_installer_records" in spec
    assert "a.datas = _without_installer_records(a.datas)" in spec


def test_bundle_base_resolves_to_the_app_tree_in_dev():
    assert run_sector._bundle_base() == ROOT


def test_frozen_entrypoint_routes_multiprocessing_before_streamlit(monkeypatch):
    calls = []
    monkeypatch.setattr(run_sector.sys, "argv", ["Sector.exe"])
    monkeypatch.setattr(
        run_sector.multiprocessing,
        "freeze_support",
        lambda: calls.append("freeze"),
    )
    monkeypatch.setattr(run_sector, "main", lambda: calls.append("streamlit"))

    run_sector._entrypoint()

    assert calls == ["freeze", "streamlit"]


def test_frozen_entrypoint_routes_image_worker_after_freeze_support_before_streamlit(
    monkeypatch,
):
    calls = []
    monkeypatch.setattr(
        run_sector.sys,
        "argv",
        ["Sector.exe", run_sector._PUBLICATION_IMAGE_WORKER_FLAG],
    )
    monkeypatch.setattr(
        run_sector, "_run_publication_image_worker", lambda: calls.append("worker")
    )
    monkeypatch.setattr(
        run_sector.multiprocessing,
        "freeze_support",
        lambda: calls.append("freeze"),
    )
    monkeypatch.setattr(
        run_sector,
        "main",
        lambda: pytest.fail("worker invocation reached Streamlit"),
    )

    run_sector._entrypoint()

    assert calls == ["freeze", "worker"]


def test_frozen_entrypoint_rejects_malformed_image_worker_invocation(monkeypatch):
    monkeypatch.setattr(
        run_sector.sys,
        "argv",
        ["Sector.exe", run_sector._PUBLICATION_IMAGE_WORKER_FLAG, "unexpected"],
    )

    with pytest.raises(ValueError, match="invalid publication image worker"):
        run_sector._entrypoint()


def test_frozen_worker_dispatch_executes_only_the_bundled_worker_file(
    tmp_path, monkeypatch
):
    worker = tmp_path / "app" / "publication_image_export_worker.py"
    worker.parent.mkdir()
    worker.write_text("# worker\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(run_sector, "_bundle_base", lambda: tmp_path)
    monkeypatch.setattr(
        run_sector.runpy,
        "run_path",
        lambda path, *, run_name: calls.append(
            (path, run_name, tuple(run_sector.sys.argv))
        ),
    )

    run_sector._run_publication_image_worker()

    assert calls == [(str(worker), "__main__", (str(worker),))]
    exporter = (ROOT / "app" / "publication_image_export.py").read_text(
        encoding="utf-8"
    )
    assert (
        f'_FROZEN_WORKER_FLAG = "{run_sector._PUBLICATION_IMAGE_WORKER_FLAG}"'
        in exporter
    )


def test_user_data_dir_uses_localappdata(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert run_sector._user_data_dir() == tmp_path / "Sector"


def test_user_data_dir_falls_back_to_home(monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert run_sector._user_data_dir() == pathlib.Path.home() / ".sector"


def test_default_port_is_local_8502_and_telemetry_is_disabled(monkeypatch):
    monkeypatch.delenv("SECTOR_PORT", raising=False)
    argv = run_sector._streamlit_argv("app/sector_app.py", run_sector._port())
    assert run_sector._port() == "8502"
    assert "--server.port=8502" in argv
    assert "--server.address=127.0.0.1" in argv
    assert "--browser.gatherUsageStats=false" in argv


def test_port_and_headless_smoke_are_explicit(monkeypatch):
    monkeypatch.setenv("SECTOR_PORT", "8600")
    monkeypatch.setenv("SECTOR_HEADLESS", "1")
    assert run_sector._port() == "8600"
    assert run_sector._headless() is True
    assert "--server.headless=true" in run_sector._streamlit_argv(
        "app/sector_app.py", "8600", headless=True
    )
    monkeypatch.setenv("SECTOR_HEADLESS", "yes")
    with pytest.raises(ValueError, match="must be exactly '1'"):
        run_sector._headless()
