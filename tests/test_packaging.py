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
import zipfile
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
    for name in (
        "sector.spec",
        "run_sector.py",
        "build.ps1",
        "build.bat",
        "build_qa.bat",
        "README.md",
        "build_portable.ps1",
        "README-PORTABLE.txt",
    ):
        assert (pkg / name).is_file(), f"packaging/{name} missing from the repo"
    assert (pkg.parent / "BUILD.bat").is_file()
    assert (pkg.parent / "BUILD_SECTOR_PORTABLE.bat").is_file()


def test_portable_batch_is_a_quoted_nontelevated_self_relative_wrapper():
    root = pathlib.Path(__file__).resolve().parent.parent
    wrapper = (root / "BUILD.bat").read_text(encoding="utf-8")
    folded = wrapper.casefold()

    assert "%~dp0packaging\\build_portable.ps1" in wrapper
    assert "%~dp0tools\\build_portable_windows.py" in wrapper
    assert "%~dp0requirements-build.txt" in wrapper
    assert "%~dp0sector\\sector_build_info.json" in wrapper
    assert '"%SECTOR_POWERSHELL%"' in wrapper
    assert '"%SECTOR_BUILD_SCRIPT%"' in wrapper
    assert "-noprofile" in folded
    assert "-file" in folded
    assert "runas" not in folded
    assert "start-process" not in folded
    assert "sector.exe" not in folded
    assert "%*" not in wrapper
    assert "%~1" not in wrapper
    assert "extract all" in folded
    assert "sector-main.zip" in folded
    assert "sector-v^<version^>-source.zip" in folded
    assert "releases/latest" in folded
    assert 'if exist "%~dp0.git" goto :build' in folded


def test_legacy_and_packaging_build_names_route_to_root_build():
    root = pathlib.Path(__file__).resolve().parent.parent
    legacy = (root / "BUILD_SECTOR_PORTABLE.bat").read_text(encoding="utf-8")
    packaging = (root / "packaging" / "build.bat").read_text(encoding="utf-8")
    qa = (root / "packaging" / "build_qa.bat").read_text(encoding="utf-8")

    assert "%~dp0BUILD.bat" in legacy
    assert "%~dp0..\\BUILD.bat" in packaging
    for wrapper in (legacy, packaging):
        folded = wrapper.casefold()
        assert "extract all" in folded
        assert "build_portable.ps1" not in folded
        assert "build.ps1" not in folded
    assert "%~dp0build.ps1" in qa
    assert "unsigned qa package only" in qa.casefold()
    assert "do not launch, zip or distribute" in qa.casefold()


def test_portable_batch_suppresses_pause_only_for_explicit_ci_mode():
    root = pathlib.Path(__file__).resolve().parent.parent
    wrapper = (root / "BUILD.bat").read_text(encoding="utf-8")
    folded = wrapper.casefold()

    pause = folded.index("\npause\n")
    assert folded.index("sector_portable_noninteractive") < pause
    assert folded.index('"%ci%"=="true"') < pause
    assert folded.index('"%ci%"=="1"') < pause


@pytest.mark.skipif(os.name != "nt", reason="cmd.exe wrapper is Windows-only")
def test_build_bat_rejects_an_incomplete_explorer_zip_preview(tmp_path):
    root = pathlib.Path(__file__).resolve().parent.parent
    preview = tmp_path / "Temp" / "Sector-main" / "packaging"
    preview.mkdir(parents=True)
    shutil.copy2(root / "packaging" / "build.bat", preview / "build.bat")
    environment = dict(os.environ)
    environment.update(CI="true", SECTOR_PORTABLE_NONINTERACTIVE="1")

    result = subprocess.run(
        [os.environ["COMSPEC"], "/d", "/s", "/c", "call build.bat"],
        cwd=preview,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    output = f"{result.stdout}\n{result.stderr}".casefold()
    assert result.returncode == 2
    assert "incomplete zip preview" in output
    assert "extract all" in output
    assert "build.ps1" not in output
    assert "windows powershell" not in output


@pytest.mark.skipif(os.name != "nt", reason="cmd.exe wrapper is Windows-only")
def test_root_build_rejects_github_download_zip_before_powershell(tmp_path):
    root = pathlib.Path(__file__).resolve().parent.parent
    source = tmp_path / "Sector-main"
    (source / "packaging").mkdir(parents=True)
    (source / "tools").mkdir()
    shutil.copy2(root / "BUILD.bat", source / "BUILD.bat")
    for relative in (
        pathlib.Path("packaging/build_portable.ps1"),
        pathlib.Path("tools/build_portable_windows.py"),
        pathlib.Path("requirements-build.txt"),
    ):
        shutil.copy2(root / relative, source / relative)
    environment = dict(os.environ)
    environment.update(CI="true", SECTOR_PORTABLE_NONINTERACTIVE="1")

    result = subprocess.run(
        [os.environ["COMSPEC"], "/d", "/s", "/c", "call BUILD.bat"],
        cwd=source,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    output = f"{result.stdout}\n{result.stderr}".casefold()
    assert result.returncode == 3
    assert "cannot authenticate this source folder" in output
    assert "sector-main.zip" in output
    assert "sector-v<version>-source.zip" in output
    assert "windows powershell" not in output


@pytest.mark.skipif(os.name != "nt", reason="cmd.exe wrapper is Windows-only")
@pytest.mark.parametrize(
    "relative_wrapper",
    ("BUILD.bat", "BUILD_SECTOR_PORTABLE.bat", "packaging/build.bat"),
)
def test_build_names_reach_portable_script_from_complete_gitless_source(
    tmp_path, relative_wrapper
):
    root = pathlib.Path(__file__).resolve().parent.parent
    source = tmp_path / "Sector source [official] & exact"
    (source / "packaging").mkdir(parents=True)
    (source / "tools").mkdir()
    (source / "sector").mkdir()
    for relative in (
        pathlib.Path("BUILD.bat"),
        pathlib.Path("BUILD_SECTOR_PORTABLE.bat"),
        pathlib.Path("packaging/build.bat"),
    ):
        shutil.copy2(root / relative, source / relative)
    (source / "packaging" / "build_portable.ps1").write_text(
        "Write-Output 'PORTABLE_SCRIPT_EXECUTED'\nexit 0\n", encoding="ascii"
    )
    (source / "tools" / "build_portable_windows.py").write_text(
        "# portable driver fixture\n", encoding="ascii"
    )
    (source / "requirements-build.txt").write_text(
        "# hashed lock fixture\n", encoding="ascii"
    )
    (source / "sector" / "sector_build_info.json").write_text(
        '{"source_revision":"' + "a" * 40 + '"}\n', encoding="ascii"
    )
    caller = tmp_path / "unrelated caller"
    caller.mkdir()
    wrapper = source / pathlib.Path(relative_wrapper)
    environment = dict(os.environ)
    environment.update(
        CI="true",
        SECTOR_PORTABLE_NONINTERACTIVE="1",
        SECTOR_TEST_WRAPPER=str(wrapper),
    )

    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            (
                "$wrapper = $env:SECTOR_TEST_WRAPPER; "
                "& $env:ComSpec /d /s /c ('call \"{0}\"' -f $wrapper); "
                "exit $LASTEXITCODE"
            ),
        ],
        cwd=caller,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode == 0, output
    assert output.count("PORTABLE_SCRIPT_EXECUTED") == 1
    assert "Sector portable build completed successfully." in output
    assert "incomplete ZIP preview" not in output


def test_github_download_zip_exposes_only_the_helpful_fail_closed_route(tmp_path):
    root = pathlib.Path(__file__).resolve().parent.parent
    archive = tmp_path / "Sector-main.zip"
    tracked = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout.split(b"\0")
    with zipfile.ZipFile(archive, "w") as bundle:
        for raw in tracked:
            if not raw:
                continue
            relative = pathlib.PurePosixPath(os.fsdecode(raw))
            bundle.write(root / pathlib.Path(relative), f"Sector-main/{relative}")

    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
    assert "Sector-main/BUILD.bat" in names
    assert "Sector-main/packaging/build.bat" in names
    assert "Sector-main/packaging/build_qa.bat" in names
    assert "Sector-main/sector/sector_build_info.json" not in names


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
    assert "{'bits': struct.calcsize('P') * 8" in script
    assert '{"bits": struct.calcsize("P") * 8' not in script
    assert "Get-Command python.exe -CommandType Application -All" in script
    assert "foreach ($pythonCommand in $pythonCommands)" in script
    assert "Executable = $pythonSource" in script
    assert "Get-Command py.exe -CommandType Application -All" in script
    assert "foreach ($launcherCommand in $launcherCommands)" in script
    assert "Executable = $launcherSource" in script
    assert "tools/build_portable_windows.py" in script
    assert '"-I"' in script and '"-S"' in script
    assert "$env:SECTOR_SOURCE_REVISION" in script
    assert "$env:SECTOR_PORTABLE_OUTPUT" in script
    assert "start-process" not in folded
    assert "-verb runas" not in folded


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell probe is Windows-only")
def test_portable_probe_survives_windows_powershell_native_argument_rules(tmp_path):
    if (
        sys.implementation.name != "cpython"
        or sys.version_info[:3] != (3, 13, 0)
        or sys.maxsize <= 2**32
    ):
        pytest.skip("probe regression requires exact 64-bit CPython 3.13.0")

    root = pathlib.Path(__file__).resolve().parent.parent
    powershell = shutil.which("powershell")
    assert powershell is not None
    script = (root / "packaging" / "build_portable.ps1").read_text(
        encoding="utf-8"
    )
    definitions = script.split(
        "# Interpreter identity is checked before resolving or creating any output.",
        maxsplit=1,
    )[0]
    harness = tmp_path / "probe-python-identity.ps1"
    harness.write_text(
        definitions
        + r'''
$accepted = Test-SectorPortablePython -Executable $env:SECTOR_TEST_PYTHON
if ($null -eq $accepted) {
    throw 'Exact Python identity probe was rejected'
}
Write-Output ([string]$accepted.Executable)
''',
        encoding="utf-8",
    )
    environment = dict(os.environ)
    environment["SECTOR_TEST_PYTHON"] = sys.executable

    result = subprocess.run(
        [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(harness),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == sys.executable


@pytest.mark.skipif(os.name != "nt", reason="PowerShell resolver is Windows-only")
def test_portable_powershell_enumerates_application_candidates_as_scalars(tmp_path):
    root = pathlib.Path(__file__).resolve().parent.parent
    powershell = shutil.which("powershell")
    assert powershell is not None
    script = (root / "packaging" / "build_portable.ps1").read_text(
        encoding="utf-8"
    )
    definitions = script.split(
        "# Interpreter identity is checked before resolving or creating any output.",
        maxsplit=1,
    )[0]
    harness = tmp_path / "resolve-python-candidates.ps1"
    harness.write_text(
        definitions
        + r'''
$script:seen = @()
function Test-SectorPortablePython {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,
        [string[]]$PrefixArguments = @()
    )
    $script:seen += $Executable
    if ($Executable -cne 'C:\Exact Python\python.exe') {
        return $null
    }
    return [PSCustomObject]@{
        Executable = $Executable
        PrefixArguments = @($PrefixArguments)
    }
}
function Get-Command {
    param(
        [Parameter(Position = 0)]
        [string]$Name,
        [string]$CommandType,
        [switch]$All
    )
    if ($Name -ceq 'python.exe') {
        [PSCustomObject]@{ Source = 'C:\Rejected Python\python.exe' }
        [PSCustomObject]@{ Source = 'C:\Exact Python\python.exe' }
    }
}
$env:SECTOR_PORTABLE_PYTHON = $null
$resolved = Resolve-SectorPortablePython
[PSCustomObject]@{
    Executable = [string]$resolved.Executable
    Seen = @($script:seen)
} | ConvertTo-Json -Compress
''',
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(harness),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    evidence = json.loads(result.stdout.strip())
    assert evidence == {
        "Executable": r"C:\Exact Python\python.exe",
        "Seen": [
            r"C:\Rejected Python\python.exe",
            r"C:\Exact Python\python.exe",
        ],
    }


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
        "double-click build.bat",
        "build_sector_portable.bat remains a backward-compatible alias",
        "explorer's zip preview",
        "sector-main.zip",
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


def _uvicorn_runtime_hidden_imports() -> tuple[str, ...]:
    root = pathlib.Path(__file__).resolve().parent.parent
    source = (root / "packaging" / "sector.spec").read_text(encoding="utf-8")
    tree = ast.parse(source, filename="sector.spec")
    assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "UVICORN_RUNTIME_HIDDEN_IMPORTS"
    )
    value = ast.literal_eval(assignment.value)
    assert isinstance(value, tuple)
    assert all(isinstance(module, str) for module in value)
    return value


def test_uvicorn_runtime_hidden_imports_are_explicit_and_narrow():
    expected = (
        "uvicorn.lifespan.on",
        "uvicorn.loops.asyncio",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.http.httptools_impl",
        "uvicorn.protocols.websockets.websockets_sansio_impl",
    )

    assert _uvicorn_runtime_hidden_imports() == expected

    root = pathlib.Path(__file__).resolve().parent.parent
    tree = ast.parse(
        (root / "packaging" / "sector.spec").read_text(encoding="utf-8")
    )
    broad_uvicorn_collections = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"collect_all", "collect_submodules"}
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "uvicorn"
    ]
    assert not broad_uvicorn_collections

    bindings = [
        node
        for node in tree.body
        if isinstance(node, ast.AugAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "hiddenimports"
        and isinstance(node.op, ast.Add)
        and isinstance(node.value, ast.Name)
        and node.value.id == "UVICORN_RUNTIME_HIDDEN_IMPORTS"
    ]
    assert len(bindings) == 1

    analysis_calls = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "Analysis"
    ]
    assert len(analysis_calls) == 1
    analysis = analysis_calls[0]
    hiddenimports_keywords = [
        keyword
        for keyword in analysis.value.keywords
        if keyword.arg == "hiddenimports"
        and isinstance(keyword.value, ast.Name)
        and keyword.value.id == "hiddenimports"
    ]
    assert len(hiddenimports_keywords) == 1
    assert bindings[0].lineno < analysis.lineno


def test_uvicorn_runtime_hidden_imports_cover_the_locked_server_routes():
    import inspect

    import uvicorn
    from streamlit.web.server.starlette.starlette_server import (
        _get_websocket_protocol,
    )
    from uvicorn import config as uvicorn_config

    parameters = inspect.signature(uvicorn.Config).parameters
    defaults = {
        name: parameters[name].default
        for name in ("http", "lifespan", "loop")
    }
    assert defaults == {"http": "auto", "lifespan": "auto", "loop": "auto"}
    assert _get_websocket_protocol() == "websockets-sansio"

    registry_targets = {
        uvicorn_config.HTTP_PROTOCOLS[defaults["http"]],
        uvicorn_config.LIFESPAN[defaults["lifespan"]],
        uvicorn_config.LOOP_FACTORIES[defaults["loop"]],
        uvicorn_config.WS_PROTOCOLS[_get_websocket_protocol()],
    }
    routed_modules = {target.partition(":")[0] for target in registry_targets}
    assert routed_modules <= set(_uvicorn_runtime_hidden_imports())

    # HTTP auto conditionally imports either locked implementation. Parse its
    # source so an upstream branch change fails closed instead of silently
    # producing another incomplete executable.
    uvicorn_root = pathlib.Path(uvicorn_config.__file__).resolve().parent
    http_auto = ast.parse(
        (uvicorn_root / "protocols" / "http" / "auto.py").read_text(
            encoding="utf-8"
        )
    )
    http_implementations = {
        node.module
        for node in ast.walk(http_auto)
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        and node.module.startswith("uvicorn.protocols.http.")
    }
    assert http_implementations == {
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.http.httptools_impl",
    }
    assert http_implementations <= set(_uvicorn_runtime_hidden_imports())


def _anyio_runtime_hidden_imports() -> tuple[str, ...]:
    root = pathlib.Path(__file__).resolve().parent.parent
    source = (root / "packaging" / "sector.spec").read_text(encoding="utf-8")
    tree = ast.parse(source, filename="sector.spec")
    assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "ANYIO_RUNTIME_HIDDEN_IMPORTS"
    )
    value = ast.literal_eval(assignment.value)
    assert isinstance(value, tuple)
    assert all(isinstance(module, str) for module in value)
    return value


def test_anyio_runtime_hidden_imports_are_explicit_and_narrow():
    expected = ("anyio._backends._asyncio",)

    assert _anyio_runtime_hidden_imports() == expected

    root = pathlib.Path(__file__).resolve().parent.parent
    tree = ast.parse(
        (root / "packaging" / "sector.spec").read_text(encoding="utf-8")
    )
    broad_anyio_collections = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"collect_all", "collect_submodules"}
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "anyio"
    ]
    assert not broad_anyio_collections

    bindings = [
        node
        for node in tree.body
        if isinstance(node, ast.AugAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "hiddenimports"
        and isinstance(node.op, ast.Add)
        and isinstance(node.value, ast.Name)
        and node.value.id == "ANYIO_RUNTIME_HIDDEN_IMPORTS"
    ]
    assert len(bindings) == 1

    analysis_calls = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "Analysis"
    ]
    assert len(analysis_calls) == 1
    analysis = analysis_calls[0]
    hiddenimports_keywords = [
        keyword
        for keyword in analysis.value.keywords
        if keyword.arg == "hiddenimports"
        and isinstance(keyword.value, ast.Name)
        and keyword.value.id == "hiddenimports"
    ]
    assert len(hiddenimports_keywords) == 1
    assert bindings[0].lineno < analysis.lineno


def test_anyio_runtime_hidden_imports_cover_locked_streamlit_asyncio_route():
    import importlib
    import importlib.metadata

    import anyio
    from anyio._core import _eventloop as anyio_eventloop
    from streamlit.web.server.starlette import starlette_server

    root = pathlib.Path(__file__).resolve().parent.parent
    locked_versions = set()
    for requirement_file in (
        "requirements.txt",
        "requirements-build.txt",
        "requirements-dev.txt",
    ):
        entries = [
            line.split()[0].partition("==")[2]
            for line in (root / requirement_file).read_text(encoding="utf-8").splitlines()
            if line.startswith("anyio==")
        ]
        assert len(entries) == 1
        locked_versions.update(entries)
    assert locked_versions == {importlib.metadata.version("anyio")}

    anyio_root = pathlib.Path(anyio.__file__).resolve().parent
    eventloop_tree = ast.parse(
        (anyio_root / "_core" / "_eventloop.py").read_text(encoding="utf-8")
    )
    backends_assignment = next(
        node
        for node in eventloop_tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "BACKENDS"
            for target in node.targets
        )
    )
    backends = ast.literal_eval(backends_assignment.value)
    assert backends == ("asyncio", "trio")

    dynamic_imports = [
        node
        for node in ast.walk(eventloop_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "import_module"
    ]
    assert len(dynamic_imports) == 1
    template = dynamic_imports[0].args[0]
    assert isinstance(template, ast.JoinedStr)
    assert len(template.values) == 2
    assert isinstance(template.values[0], ast.Constant)
    assert template.values[0].value == "anyio._backends._"
    assert isinstance(template.values[1], ast.FormattedValue)
    assert isinstance(template.values[1].value, ast.Name)
    assert template.values[1].value.id == "asynclib_name"

    backend_inventory = {
        f"anyio._backends.{path.stem}"
        for path in (anyio_root / "_backends").glob("_*.py")
        if path.name != "__init__.py"
    }
    assert backend_inventory == {
        f"anyio._backends._{backend}" for backend in backends
    }

    streamlit_tree = ast.parse(
        pathlib.Path(starlette_server.__file__).read_text(encoding="utf-8")
    )
    assert any(
        isinstance(node, ast.Import)
        and any(alias.name == "asyncio" for alias in node.names)
        for node in streamlit_tree.body
    )
    asyncio_calls = {
        node.func.attr
        for node in ast.walk(streamlit_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "asyncio"
    }
    assert {"Event", "create_task"} <= asyncio_calls

    runtime_modules = ("anyio._backends._asyncio",)
    assert runtime_modules == _anyio_runtime_hidden_imports()
    assert set(runtime_modules) < backend_inventory
    backend_module = importlib.import_module(runtime_modules[0])
    assert backend_module.backend_class is anyio_eventloop.get_async_backend("asyncio")


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
