"""Tests for the single-build internal Windows portable packager."""

from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

import pytest

from tools import build_portable_windows as portable


def _source_tree(root: Path) -> Path:
    files = {
        "LICENSE": "internal licence\n",
        "app/point_grid_frontend/LICENSE": "frontend licence\n",
        "app/publication_image_export_worker.py": "# worker\n",
        "app/sector_app.py": "# app\n",
        "assets/logo.png": "logo",
        "requirements-build.txt": "",
        "sector/__init__.py": '__version__ = "0.94"\n',
        "packaging/README-PORTABLE.txt": "Sector @SECTOR_VERSION@\n",
        "packaging/run_sector.py": "# launcher\n",
        "packaging/sector.spec": "# spec\n",
        "packaging/windows_version_info.txt": "# version\n",
        "tools/generate_third_party_notices.py": "# notices\n",
        "tools/verify_portable_image_export.py": "# image smoke\n",
        "tools/verify_portable_startup.py": "# smoke\n",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


class _FakeRunner:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []
        self.smoke_package: Path | None = None
        self.image_smoke_package: Path | None = None

    def __call__(
        self, arguments: tuple[str, ...], cwd: Path, environment: dict[str, str]
    ) -> None:
        del cwd, environment
        command = tuple(arguments)
        self.commands.append(command)
        if "venv" in command:
            venv = Path(command[-1])
            (venv / "Scripts").mkdir(parents=True)
            (venv / "Scripts" / "python.exe").write_bytes(b"fake python")
        elif "generate_third_party_notices.py" in " ".join(command):
            output = Path(command[command.index("--output") + 1])
            output.write_text("third-party notices\n", encoding="utf-8")
        elif "PyInstaller" in command:
            dist = Path(command[command.index("--distpath") + 1]) / "Sector"
            (dist / "_internal").mkdir(parents=True)
            (dist / "Sector.exe").write_bytes(b"MZ fake executable")
            (dist / "_internal" / "runtime.pyd").write_bytes(b"runtime")
        elif "verify_portable_image_export.py" in " ".join(command):
            self.image_smoke_package = Path(command[command.index("--package") + 1])
        elif "verify_portable_startup.py" in " ".join(command):
            self.smoke_package = Path(command[command.index("--package") + 1])


def test_version_and_readme_use_094(tmp_path):
    root = _source_tree(tmp_path / "source")
    assert portable._read_version(root) == "0.94"
    assert (
        portable._render_readme(root / "packaging" / "README-PORTABLE.txt", "0.94")
        .decode("ascii")
        .strip()
        == "Sector 0.94"
    )


def test_complete_source_is_required_but_no_authentication_manifest(tmp_path):
    root = _source_tree(tmp_path / "source")
    assert portable._validate_source(root) == root.resolve()
    assert "sector/sector_build_info.json" not in portable._REQUIRED_SOURCE_PATHS
    (root / "app" / "sector_app.py").unlink()
    with pytest.raises(portable.PortableBuildError, match="incomplete"):
        portable._validate_source(root)


def test_revision_is_diagnostic_and_may_be_unavailable():
    assert portable._resolve_revision(None) == "unavailable"
    assert portable._resolve_revision("unavailable") == "unavailable"
    assert portable._resolve_revision("a" * 40) == "a" * 40
    with pytest.raises(portable.PortableBuildError, match="40-hex"):
        portable._resolve_revision("certified")


def test_single_build_runs_page_then_publishes_folder_zip_and_checksum(tmp_path):
    root = _source_tree(tmp_path / "source")
    output = tmp_path / "portable-output"
    runner = _FakeRunner()

    result = portable.build_portable_windows(
        root,
        output,
        python_executable=Path(sys.executable),
        source_revision="a" * 40,
        runner=runner,
    )

    assert result.version == "0.94"
    assert result.folder.name == "Sector-v0.94-windows-portable"
    assert (result.folder / "Sector.exe").is_file()
    assert (result.folder / "LICENSE.txt").is_file()
    assert (result.folder / "THIRD_PARTY_NOTICES.txt").is_file()
    assert result.archive.is_file()
    assert result.checksum.is_file()
    assert runner.smoke_package is not None
    assert runner.smoke_package.name == result.folder.name
    assert runner.image_smoke_package is not None
    assert runner.image_smoke_package.name == result.folder.name
    assert sum("PyInstaller" in command for command in runner.commands) == 1
    assert (
        sum(
            "verify_portable_startup.py" in " ".join(command)
            for command in runner.commands
        )
        == 1
    )
    assert (
        sum(
            "verify_portable_image_export.py" in " ".join(command)
            for command in runner.commands
        )
        == 1
    )

    digest = hashlib.sha256(result.archive.read_bytes()).hexdigest()
    assert digest == result.archive_sha256
    assert result.checksum.read_text("ascii") == (f"{digest}  {result.archive.name}\n")
    with zipfile.ZipFile(result.archive) as archive:
        names = archive.namelist()
        compression = {item.compress_type for item in archive.infolist()}
    assert f"{result.folder.name}/Sector.exe" in names
    assert f"{result.folder.name}/README-PORTABLE.txt" in names
    assert not any("receipt" in name.casefold() for name in names)
    assert compression == {zipfile.ZIP_DEFLATED}


def test_failed_build_or_smoke_publishes_no_output(tmp_path):
    root = _source_tree(tmp_path / "source")
    output = tmp_path / "portable-output"

    def fail(
        arguments: tuple[str, ...], cwd: Path, environment: dict[str, str]
    ) -> None:
        del cwd, environment
        if "venv" in arguments:
            venv = Path(arguments[-1])
            (venv / "Scripts").mkdir(parents=True)
            (venv / "Scripts" / "python.exe").write_bytes(b"fake")
            return
        raise portable.PortableBuildError("simulated failure")

    with pytest.raises(portable.PortableBuildError, match="simulated"):
        portable.build_portable_windows(
            root,
            output,
            python_executable=Path(sys.executable),
            runner=fail,
        )
    assert not output.exists()


def test_output_is_new_and_outside_source(tmp_path):
    root = _source_tree(tmp_path / "source")
    with pytest.raises(portable.PortableBuildError, match="outside"):
        portable._validate_output(root, root / "dist")
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(portable.PortableBuildError, match="already exists"):
        portable._validate_output(root, existing)


def test_native_runtime_paths_are_checked_at_the_final_location(tmp_path):
    staged = tmp_path / "stage"
    nested = staged / ("x" * 80) / ("y" * 80)
    nested.mkdir(parents=True)
    (nested / "runtime.pyd").write_bytes(b"runtime")
    short = Path("C:/S")
    portable._runtime_path_budget(staged, short)
    with pytest.raises(portable.PortableBuildError, match="too long"):
        portable._runtime_path_budget(staged, tmp_path / ("z" * 180))


def test_repository_build_contract_is_deliberately_small():
    root = Path(__file__).resolve().parents[1]
    driver = (root / "tools" / "build_portable_windows.py").read_text("utf-8")
    for removed in (
        "verify_windows_release",
        "build_source_release",
        "compare_portable_distributions",
        "portable-distribution.json",
        "certificate_table",
        "source_inventory",
    ):
        assert removed not in driver
