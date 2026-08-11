"""Smoke tests for the packaging launcher's path resolution.

These exercise ``packaging/run_sector.py`` without building or starting Streamlit
(its Streamlit import lives inside ``main``), so they are fast and need no bundle.
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
from types import SimpleNamespace

import pytest
import tomllib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "packaging"))

import run_sector

from tools import verify_windows_release


def test_packaging_files_are_in_the_repo():
    # All build inputs must be committed -- notably sector.spec, which the generic
    # .gitignore *.spec rule would drop (it is negated for this one). On a clean
    # checkout (CI) a missing file is simply absent, so this catches it.
    pkg = pathlib.Path(__file__).resolve().parent.parent / "packaging"
    for name in ("sector.spec", "run_sector.py", "build.ps1", "build.bat",
                 "README.md", "build_portable.ps1", "README-PORTABLE.txt"):
        assert (pkg / name).is_file(), f"packaging/{name} missing from the repo"
    assert (pkg.parent / "BUILD_SECTOR_PORTABLE.bat").is_file()


def test_portable_batch_is_a_quoted_nontelevated_self_relative_wrapper():
    root = pathlib.Path(__file__).resolve().parent.parent
    wrapper = (root / "BUILD_SECTOR_PORTABLE.bat").read_text(encoding="utf-8")
    folded = wrapper.casefold()

    assert "%~dp0packaging\\build_portable.ps1" in wrapper
    assert '"%SECTOR_POWERSHELL%"' in wrapper
    assert '"%SECTOR_BUILD_SCRIPT%"' in wrapper
    assert "-noprofile" in folded
    assert "-file" in folded
    assert "runas" not in folded
    assert "start-process" not in folded
    assert "sector.exe" not in folded
    assert "%*" not in wrapper
    assert "%~1" not in wrapper
    assert "accepts no command-line arguments" in folded


def test_portable_batch_suppresses_pause_only_for_explicit_ci_mode():
    root = pathlib.Path(__file__).resolve().parent.parent
    wrapper = (root / "BUILD_SECTOR_PORTABLE.bat").read_text(encoding="utf-8")
    folded = wrapper.casefold()

    pause = folded.index("\npause\n")
    assert folded.index("sector_portable_noninteractive") < pause
    assert folded.index('"%ci%"=="true"') < pause
    assert folded.index('"%ci%"=="1"') < pause


def test_portable_powershell_checks_exact_python_before_any_output():
    root = pathlib.Path(__file__).resolve().parent.parent
    script = (root / "packaging" / "build_portable.ps1").read_text(
        encoding="utf-8"
    )
    folded = script.casefold()

    check = script.index("$python = Resolve-SectorPortablePython")
    assert check < script.index("$artifactRoot =")
    assert check < script.index('Write-Host "Sector unsigned portable Windows build"')
    assert 'implementation -cne "CPython"' in script
    assert "[int]$identity.bits -ne 64" in script
    assert "[int]$identity.version[0] -ne 3" in script
    assert "[int]$identity.version[1] -ne 13" in script
    assert "[int]$identity.version[2] -ne 0" in script
    assert "tools/build_portable_windows.py" in script
    assert '"-I"' in script and '"-S"' in script
    assert "$env:SECTOR_SOURCE_REVISION" in script
    assert "$env:SECTOR_PORTABLE_OUTPUT" in script
    assert "start-process" not in folded
    assert "-verb runas" not in folded


def test_portable_powershell_prefers_manifest_and_requires_a_root_git_marker():
    root = pathlib.Path(__file__).resolve().parent.parent
    script = (root / "packaging" / "build_portable.ps1").read_text(
        encoding="utf-8"
    )

    manifest = script.index('$manifestPath = Join-Path $sourceRoot "sector/')
    git_marker = script.index('$gitMarker = Join-Path $sourceRoot ".git"')
    git_rev_parse = script.index("rev-parse HEAD")
    assert manifest < git_marker < git_rev_parse
    assert "Test-Path -LiteralPath $gitMarker" in script


@pytest.mark.skipif(os.name != "nt", reason="PowerShell wrapper is Windows-only")
def test_portable_powershell_ignores_an_unrelated_parent_repository(tmp_path):
    root = pathlib.Path(__file__).resolve().parent.parent
    git = shutil.which("git")
    powershell = shutil.which("powershell")
    assert git is not None
    assert powershell is not None

    parent = tmp_path / "unrelated-parent-repository"
    parent.mkdir()
    subprocess.run([git, "init", "--quiet", str(parent)], check=True)
    (parent / "unrelated.txt").write_text("parent", encoding="ascii")
    subprocess.run([git, "-C", str(parent), "add", "unrelated.txt"], check=True)
    subprocess.run(
        [
            git,
            "-C",
            str(parent),
            "-c",
            "user.name=Sector Tests",
            "-c",
            "user.email=sector-tests@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "unrelated parent",
        ],
        check=True,
    )
    parent_revision = subprocess.run(
        [git, "-C", str(parent), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    source = parent / "OneDrive - Example" / "Sector-v0.92"
    (source / "packaging").mkdir(parents=True)
    (source / "sector").mkdir()
    shutil.copy2(
        root / "packaging" / "build_portable.ps1",
        source / "packaging" / "build_portable.ps1",
    )
    manifest_revision = "a" * 40
    (source / "sector" / "sector_build_info.json").write_text(
        json.dumps({"source_revision": manifest_revision}), encoding="ascii"
    )

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    capture = tmp_path / "python-arguments.txt"
    fake_python = fake_bin / "python.ps1"
    fake_python.write_text(
        "[IO.File]::AppendAllText(\n"
        "    $env:SECTOR_TEST_CAPTURE,\n"
        "    (($args | ForEach-Object { [string]$_ }) -join ' ') + "
        "[Environment]::NewLine\n"
        ")\n"
        "$global:LASTEXITCODE = 0\n"
        "Write-Output "
        "'{\"bits\":64,\"implementation\":\"CPython\",\"version\":[3,13,0]}'\n",
        encoding="utf-8",
    )
    environment = dict(os.environ)
    environment.pop("SECTOR_SOURCE_REVISION", None)
    environment["SECTOR_PORTABLE_PYTHON"] = str(fake_python)
    environment["SECTOR_PORTABLE_OUTPUT"] = str(tmp_path / "portable-output")
    environment["SECTOR_TEST_CAPTURE"] = str(capture)

    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(source / "packaging" / "build_portable.ps1"),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode != 0  # fake builder deliberately publishes nothing
    arguments = capture.read_text(encoding="ascii")
    assert "--source-revision" in arguments
    assert manifest_revision in arguments
    assert parent_revision not in arguments


def test_portable_readme_sets_the_complete_unsigned_user_boundary():
    root = pathlib.Path(__file__).resolve().parent.parent
    readme = (root / "packaging" / "README-PORTABLE.txt").read_text(
        encoding="ascii"
    )
    folded = " ".join(readme.casefold().split())
    assert readme.count("@SECTOR_VERSION@") == 1
    assert "<version>" not in readme

    for token in (
        "double-click build_sector_portable.bat",
        "64-bit cpython 3.13.0",
        "administrator rights",
        "whole folder or the whole zip",
        "never copy or share sector.exe by itself",
        "unsigned",
        "smartscreen",
        "corporate security policy",
        "no trusted-publisher",
        "proprietary software",
        "microsoft edge",
        "chromium-family browser",
        "browser is not bundled",
    ):
        assert token in folded


def test_build_script_uses_the_hashed_lock():
    root = pathlib.Path(__file__).resolve().parent.parent
    script = (root / "packaging" / "build.ps1").read_text(encoding="utf-8")
    driver = (root / "tools" / "build_exact_commit.py").read_text(encoding="utf-8")
    assert "tools/build_exact_commit.py" in script
    assert '"--require-hashes"' in driver
    assert '"requirements-build.txt"' in driver
    assert '"pyinstaller>=' not in (script + driver).lower()


def _reparse_status(status):
    return SimpleNamespace(
        st_dev=status.st_dev,
        st_ino=status.st_ino,
        st_mode=status.st_mode,
        st_size=status.st_size,
        st_mtime_ns=status.st_mtime_ns,
        st_file_attributes=(
            getattr(status, "st_file_attributes", 0)
            | getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        ),
    )


def test_release_reader_is_bounded_and_rejects_reparse_ancestors(
    tmp_path, monkeypatch
):
    package = tmp_path / "Sector"
    parent = package / "_internal" / "sector"
    parent.mkdir(parents=True)
    manifest = parent / "sector_build_info.json"
    manifest.write_bytes(b"{}\n")

    with pytest.raises(
        verify_windows_release.ReleaseVerificationError,
        match="release resource limit",
    ):
        verify_windows_release._read_regular_file(
            manifest, "package manifest", boundary=package, limit=2
        )

    real_stat = os.stat

    def report_reparse(path, *, dir_fd=None, follow_symlinks=True):
        status = real_stat(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
        if not follow_symlinks and pathlib.Path(path) == parent:
            return _reparse_status(status)
        return status

    monkeypatch.setattr(os, "stat", report_reparse)
    with pytest.raises(
        verify_windows_release.ReleaseVerificationError,
        match="link or reparse point",
    ):
        verify_windows_release._read_regular_file(
            manifest, "package manifest", boundary=package
        )


def test_release_reader_rejects_a_read_time_path_change(tmp_path, monkeypatch):
    package = tmp_path / "Sector"
    package.mkdir()
    notices = package / "THIRD_PARTY_NOTICES.txt"
    notices.write_bytes(b"accepted notices\n")
    real_stat = os.stat
    target_lstats = 0

    def report_changed_path(path, *, dir_fd=None, follow_symlinks=True):
        nonlocal target_lstats
        status = real_stat(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
        if not follow_symlinks and pathlib.Path(path) == notices:
            target_lstats += 1
            if target_lstats > 1:
                return SimpleNamespace(
                    st_dev=status.st_dev,
                    st_ino=status.st_ino,
                    st_mode=status.st_mode,
                    st_size=status.st_size,
                    st_mtime_ns=status.st_mtime_ns + 1,
                    st_file_attributes=getattr(
                        status, "st_file_attributes", 0
                    ),
                )
        return status

    monkeypatch.setattr(os, "stat", report_changed_path)
    with pytest.raises(
        verify_windows_release.ReleaseVerificationError,
        match="changed while it was read",
    ):
        verify_windows_release._read_regular_file(
            notices, "third-party notices", boundary=package
        )


def test_release_verifier_rejects_reparse_package_root_before_source_lookup(
    tmp_path, monkeypatch
):
    package = tmp_path / "Sector"
    package.mkdir()
    evidence = tmp_path / "source-identity.json"
    evidence.write_bytes(b"{}\n")
    real_stat = os.stat

    def report_reparse(path, *, dir_fd=None, follow_symlinks=True):
        status = real_stat(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
        if not follow_symlinks and pathlib.Path(path) == package:
            return _reparse_status(status)
        return status

    monkeypatch.setattr(os, "stat", report_reparse)
    with pytest.raises(
        verify_windows_release.ReleaseVerificationError,
        match="package root is a link or reparse point",
    ):
        verify_windows_release.verify_package(
            tmp_path, package, "a" * 40, evidence
        )


def test_distribution_notices_are_generated_and_package_gated():
    root = pathlib.Path(__file__).resolve().parent.parent
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md",
                 "tools/generate_third_party_notices.py"):
        assert (root / name).is_file(), f"{name} missing from the repository"
    build = (root / "packaging" / "build.ps1").read_text(encoding="utf-8")
    driver = (root / "tools" / "build_exact_commit.py").read_text(
        encoding="utf-8"
    )
    workflow = (root / ".github" / "workflows" / "qa.yml").read_text(
        encoding="utf-8"
    )
    assert "tools/build_exact_commit.py" in build
    assert "tools/build_exact_commit.py" in workflow
    assert "generate_third_party_notices.py" in driver
    assert '"LICENSE.txt"' in driver
    assert '"THIRD_PARTY_NOTICES.txt"' in driver
    assert "$packageRoot/LICENSE.txt" in workflow
    assert "$packageRoot/THIRD_PARTY_NOTICES.txt" in workflow


def test_kaleido_cli_mocker_is_excluded_from_the_frozen_runtime():
    root = pathlib.Path(__file__).resolve().parent.parent
    spec = (root / "packaging" / "sector.spec").read_text(encoding="utf-8")
    assert "filter_submodules" in spec
    assert 'name.startswith("kaleido.mocker")' in spec


def test_only_path_bound_installer_record_metadata_is_omitted():
    root = pathlib.Path(__file__).resolve().parent.parent
    source = (root / "packaging" / "sector.spec").read_text(encoding="utf-8")
    tree = ast.parse(source)
    helper = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_without_installer_records"
    )
    namespace = {}
    exec(  # noqa: S102 - execute only the selected local pure helper AST
        compile(ast.Module(body=[helper], type_ignores=[]), "sector.spec", "exec"),
        namespace,
    )
    entries = [
        ("jsonschema-4.26.0.dist-info/RECORD", "path-bound", "DATA"),
        ("streamlit-1.57.0.DIST-INFO\\record", "path-bound", "DATA"),
        ("jsonschema-4.26.0.dist-info/METADATA", "retain", "DATA"),
        ("jsonschema-4.26.0.dist-info/licenses/RECORD", "retain", "DATA"),
        ("runtime/RECORD", "retain", "DATA"),
    ]

    filtered = namespace["_without_installer_records"](entries)

    assert filtered == entries[2:]
    assert entries[0][0].endswith("RECORD")


def test_packaged_runtime_embeds_exact_source_provenance():
    root = pathlib.Path(__file__).resolve().parent.parent
    spec = (root / "packaging" / "sector.spec").read_text(encoding="utf-8")
    workflow = (root / ".github" / "workflows" / "qa.yml").read_text(
        encoding="utf-8"
    )
    assert "sector_build_info.json" in spec
    assert "GITHUB_SHA" not in spec
    assert "SOURCE_DATE_EPOCH" in spec
    assert "SECTOR_SOURCE_TREE" in spec
    assert "datetime.datetime.now" not in spec
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
    assert "--server.headless=false" in argv
    assert "--server.fileWatcherType=none" in argv
    assert "--server.runOnSave=false" in argv
    assert "--browser.gatherUsageStats=false" in argv
    assert "--client.toolbarMode=viewer" in argv
    assert "--client.showErrorDetails=type" in argv
    assert argv[:3] == ["streamlit", "run", "app/sector_app.py"]


def test_port_is_overridable_via_env(monkeypatch):
    monkeypatch.setenv("SECTOR_PORT", "8600")
    assert run_sector._port() == "8600"
    assert "--server.port=8600" in run_sector._streamlit_argv("x", run_sector._port())


def test_packaged_headless_control_is_explicit_and_strict(monkeypatch):
    monkeypatch.delenv("SECTOR_HEADLESS", raising=False)
    assert run_sector._headless() is False

    monkeypatch.setenv("SECTOR_HEADLESS", "1")
    assert run_sector._headless() is True

    for invalid in ("", "0", "true", "TRUE", "yes", " 1"):
        monkeypatch.setenv("SECTOR_HEADLESS", invalid)
        with pytest.raises(ValueError, match="must be exactly '1'"):
            run_sector._headless()


def test_headless_smoke_changes_only_the_streamlit_headless_flag():
    normal = run_sector._streamlit_argv("app/sector_app.py", "54321")
    smoke = run_sector._streamlit_argv(
        "app/sector_app.py", "54321", headless=True
    )

    differences = [
        (left, right)
        for left, right in zip(normal, smoke, strict=True)
        if left != right
    ]
    assert differences == [("--server.headless=false", "--server.headless=true")]
    assert "--server.address=127.0.0.1" in smoke


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
