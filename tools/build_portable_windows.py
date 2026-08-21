"""Build one practical internal-use Sector portable Windows package."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

MAX_WINDOWS_RUNTIME_PATH_CHARS = 240
_BUFFER_BYTES = 1024 * 1024
_RUNTIME_SUFFIXES = {".dll", ".exe", ".pyd"}
_REQUIRED_SOURCE_PATHS = (
    "LICENSE",
    "app/point_grid_frontend/LICENSE",
    "app/publication_image_export_worker.py",
    "app/sector_app.py",
    "assets/logo.png",
    "requirements-build.txt",
    "sector/__init__.py",
    "packaging/README-PORTABLE.txt",
    "packaging/run_sector.py",
    "packaging/sector.spec",
    "packaging/windows_version_info.txt",
    "tools/generate_third_party_notices.py",
    "tools/verify_portable_startup.py",
)


class PortableBuildError(RuntimeError):
    """The ordinary portable build could not be completed."""


@dataclass(frozen=True)
class PortableBuildResult:
    version: str
    source_revision: str
    output: Path
    folder: Path
    archive: Path
    checksum: Path
    archive_sha256: str


CommandRunner = Callable[[Sequence[str], Path, dict[str, str]], None]


def _run(arguments: Sequence[str], cwd: Path, environment: dict[str, str]) -> None:
    try:
        completed = subprocess.run(
            list(arguments), cwd=cwd, env=environment, check=False
        )
    except OSError as exc:
        raise PortableBuildError(
            f"cannot execute build command: {arguments[0]}"
        ) from exc
    if completed.returncode != 0:
        raise PortableBuildError(
            f"build command failed with exit code {completed.returncode}: {arguments[0]}"
        )


def _read_version(root: Path) -> str:
    path = root / "sector" / "__init__.py"
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as exc:
        raise PortableBuildError("cannot read Sector version") from exc
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "__version__"
        ):
            value = ast.literal_eval(node.value)
            if (
                isinstance(value, str)
                and value
                and all(part.isdecimal() for part in value.split("."))
            ):
                return value
    raise PortableBuildError("Sector version is missing or invalid")


def _validate_source(root: Path) -> Path:
    source = Path(os.path.abspath(root))
    if not source.is_dir():
        raise PortableBuildError(f"source directory does not exist: {source}")
    missing = [
        relative
        for relative in _REQUIRED_SOURCE_PATHS
        if not (source / relative).is_file()
    ]
    if missing:
        raise PortableBuildError(
            "source folder is incomplete; missing: " + ", ".join(missing)
        )
    return source


def _validate_output(source: Path, output: Path) -> Path:
    destination = Path(os.path.abspath(output))
    if os.path.lexists(destination):
        raise PortableBuildError(f"output already exists: {destination}")
    try:
        destination.relative_to(source)
    except ValueError:
        pass
    else:
        raise PortableBuildError("portable output must be outside the source folder")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PortableBuildError("cannot create the portable output parent") from exc
    return destination


def _resolve_revision(value: str | None) -> str:
    revision = str(value or "").strip()
    if not revision:
        return "unavailable"
    if revision == "unavailable":
        return revision
    if len(revision) == 40 and all(
        character in "0123456789abcdef" for character in revision
    ):
        return revision
    raise PortableBuildError(
        "source revision must be lowercase 40-hex or 'unavailable'"
    )


def _render_readme(template: Path, version: str) -> bytes:
    try:
        payload = template.read_bytes()
    except OSError as exc:
        raise PortableBuildError("cannot read portable README template") from exc
    token = b"@SECTOR_VERSION@"
    if payload.count(token) != 1:
        raise PortableBuildError("portable README must contain one version token")
    return payload.replace(token, version.encode("ascii"))


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with source.open("rb") as reader, destination.open("xb") as writer:
            shutil.copyfileobj(reader, writer, length=_BUFFER_BYTES)
    except OSError as exc:
        raise PortableBuildError(f"cannot copy package file: {source.name}") from exc


def _copy_package(source: Path, destination: Path) -> None:
    try:
        shutil.copytree(source, destination)
    except OSError as exc:
        raise PortableBuildError("cannot assemble portable application folder") from exc


def _runtime_path_budget(folder: Path, final_folder: Path) -> None:
    for path in folder.rglob("*"):
        if path.is_file() and path.suffix.casefold() in _RUNTIME_SUFFIXES:
            installed_path = final_folder / path.relative_to(folder)
            if len(os.fspath(installed_path)) > MAX_WINDOWS_RUNTIME_PATH_CHARS:
                raise PortableBuildError(
                    "portable output path is too long for Windows native-library "
                    "loading; choose a shorter output location"
                )


def _write_zip(folder: Path, archive: Path) -> None:
    try:
        with zipfile.ZipFile(
            archive,
            "x",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as bundle:
            for path in sorted(folder.rglob("*")):
                if path.is_file():
                    bundle.write(path, path.relative_to(folder.parent).as_posix())
    except OSError as exc:
        raise PortableBuildError("cannot create portable ZIP") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(_BUFFER_BYTES), b""):
                digest.update(block)
    except OSError as exc:
        raise PortableBuildError(f"cannot hash {path.name}") from exc
    return digest.hexdigest()


def _write_checksum(path: Path, digest: str, archive_name: str) -> None:
    try:
        path.write_text(f"{digest}  {archive_name}\n", encoding="ascii", newline="\n")
    except OSError as exc:
        raise PortableBuildError("cannot write portable ZIP checksum") from exc


def _python_in_venv(root: Path) -> Path:
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _run_page_smoke(
    python: Path,
    source: Path,
    package: Path,
    workspace: Path,
    runner: CommandRunner,
    environment: dict[str, str],
) -> None:
    runner(
        (
            str(python),
            "-I",
            "-S",
            str(source / "tools" / "verify_portable_startup.py"),
            "--package",
            str(package),
            "--workspace",
            str(workspace),
            "--timeout-seconds",
            "120",
        ),
        source,
        environment,
    )


def build_portable_windows(
    root: Path,
    output: Path,
    *,
    python_executable: Path | None = None,
    source_revision: str | None = None,
    runner: CommandRunner = _run,
) -> PortableBuildResult:
    """Build once, execute the first page, then publish one folder/ZIP/checksum."""
    source = _validate_source(root)
    destination = _validate_output(source, output)
    version = _read_version(source)
    revision = _resolve_revision(source_revision)
    python = Path(python_executable or sys.executable).resolve()
    if not python.is_file():
        raise PortableBuildError(f"Python executable does not exist: {python}")

    environment = dict(os.environ)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["SECTOR_SOURCE_REVISION"] = revision

    with tempfile.TemporaryDirectory(prefix="sector-build-") as temporary:
        build_root = Path(temporary)
        venv = build_root / "venv"
        venv_python = _python_in_venv(venv)
        work = build_root / "pyinstaller-work"
        dist = build_root / "dist"
        notices = build_root / "THIRD_PARTY_NOTICES.txt"
        runner((str(python), "-I", "-m", "venv", str(venv)), source, environment)
        runner(
            (
                str(venv_python),
                "-I",
                "-m",
                "pip",
                "--isolated",
                "--disable-pip-version-check",
                "--no-input",
                "install",
                "--require-hashes",
                "-r",
                str(source / "requirements-build.txt"),
            ),
            source,
            environment,
        )
        runner(
            (
                str(venv_python),
                str(source / "tools" / "generate_third_party_notices.py"),
                "--output",
                str(notices),
                "--requirements",
                str(source / "requirements-build.txt"),
                "--tabulator-license",
                str(source / "app" / "point_grid_frontend" / "LICENSE"),
            ),
            source,
            environment,
        )
        pyinstaller_environment = dict(environment)
        pyinstaller_environment["PYINSTALLER_CONFIG_DIR"] = str(
            build_root / "pyinstaller-config"
        )
        runner(
            (
                str(venv_python),
                "-P",
                "-s",
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--workpath",
                str(work),
                "--distpath",
                str(dist),
                str(source / "packaging" / "sector.spec"),
            ),
            source,
            pyinstaller_environment,
        )

        built = dist / "Sector"
        if not (built / "Sector.exe").is_file():
            raise PortableBuildError("PyInstaller did not produce Sector.exe")
        folder_name = f"Sector-v{version}-windows-portable"
        staged_output = build_root / "publish"
        staged_output.mkdir()
        staged_folder = staged_output / folder_name
        _copy_package(built, staged_folder)
        _copy_file(source / "LICENSE", staged_folder / "LICENSE.txt")
        _copy_file(notices, staged_folder / "THIRD_PARTY_NOTICES.txt")
        (staged_folder / "README-PORTABLE.txt").write_bytes(
            _render_readme(source / "packaging" / "README-PORTABLE.txt", version)
        )
        _runtime_path_budget(staged_folder, destination / folder_name)
        _run_page_smoke(
            python,
            source,
            staged_folder,
            build_root / "smoke",
            runner,
            environment,
        )

        staged_archive = staged_output / f"{folder_name}.zip"
        staged_checksum = staged_output / f"{folder_name}.zip.sha256"
        _write_zip(staged_folder, staged_archive)
        archive_sha256 = _sha256(staged_archive)
        _write_checksum(staged_checksum, archive_sha256, staged_archive.name)

        created_output = False
        try:
            destination.mkdir()
            created_output = True
            final_folder = destination / staged_folder.name
            final_archive = destination / staged_archive.name
            final_checksum = destination / staged_checksum.name
            shutil.copytree(staged_folder, final_folder)
            shutil.copy2(staged_archive, final_archive)
            shutil.copy2(staged_checksum, final_checksum)
            if _sha256(final_archive) != archive_sha256:
                raise PortableBuildError("published ZIP differs after copy")
        except Exception:
            if created_output:
                shutil.rmtree(destination, ignore_errors=True)
            raise

    return PortableBuildResult(
        version=version,
        source_revision=revision,
        output=destination,
        folder=final_folder,
        archive=final_archive,
        checksum=final_checksum,
        archive_sha256=archive_sha256,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--source-revision", default="unavailable")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        result = build_portable_windows(
            arguments.root,
            arguments.output,
            python_executable=arguments.python,
            source_revision=arguments.source_revision,
        )
    except PortableBuildError as exc:
        print(f"Sector portable build failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({key: str(value) for key, value in asdict(result).items()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
