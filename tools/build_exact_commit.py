"""Build an unsigned QA package only from one exported exact commit tree."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from tools.export_commit_tree import ExportEvidence


def _load_exporter() -> Any:
    path = Path(__file__).resolve().with_name("export_commit_tree.py")
    specification = importlib.util.spec_from_file_location(
        "sector_exact_commit_exporter", path
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("cannot load the accepted exact-commit exporter")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        specification.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(specification.name, None)
        raise
    finally:
        sys.dont_write_bytecode = previous
    return module


def _load_source_release() -> Any:
    path = Path(__file__).resolve().with_name("build_source_release.py")
    specification = importlib.util.spec_from_file_location(
        "sector_verified_source_release", path
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("cannot load the accepted source-release verifier")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        specification.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(specification.name, None)
        raise
    finally:
        sys.dont_write_bytecode = previous
    return module


_EXPORTER = _load_exporter()
CommitTreeError = _EXPORTER.CommitTreeError
if not TYPE_CHECKING:
    ExportEvidence = _EXPORTER.ExportEvidence
export_commit = cast(
    "Callable[[Path, str, Path], ExportEvidence]", _EXPORTER.export_commit
)
_SOURCE_RELEASE = _load_source_release()
SourceReleaseError = _SOURCE_RELEASE.SourceReleaseError
materialize_source_release = cast(
    "Callable[[Path, str, Path], ExportEvidence]",
    _SOURCE_RELEASE.materialize_source_release,
)


class ExactBuildError(RuntimeError):
    """The exact-source build could not be prepared or executed safely."""


_BUILD_RUNTIME_ENVIRONMENT = (
    "COMSPEC",
    "NUMBER_OF_PROCESSORS",
    "OS",
    "PATH",
    "PATHEXT",
    "PROCESSOR_ARCHITECTURE",
    "PROCESSOR_IDENTIFIER",
    "PROCESSOR_LEVEL",
    "PROCESSOR_REVISION",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "TMPDIR",
    "WINDIR",
)

_PIP_NETWORK_ENVIRONMENT = (
    "ALL_PROXY",
    "CURL_CA_BUNDLE",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "REQUESTS_CA_BUNDLE",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
)


def _inherited_allowlist(names: tuple[str, ...]) -> dict[str, str]:
    """Copy only explicitly accepted host values under canonical names."""
    return {name: os.environ[name] for name in names if name in os.environ}


@dataclass(frozen=True)
class BuildCommand:
    arguments: tuple[str, ...]
    cwd: Path
    environment: dict[str, str]


@dataclass(frozen=True)
class ExactBuildPlan:
    source_revision: str
    run_root: Path
    source_root: Path
    package_root: Path
    source_identity_path: Path
    source_evidence: ExportEvidence
    commands: tuple[BuildCommand, ...]


@dataclass(frozen=True)
class ExactBuildEvidence:
    source_revision: str
    source_tree: str
    source_committer_epoch: int
    source_committed_at_utc: str
    source_file_count: int
    source_total_bytes: int
    source_inventory_sha256: str
    source_root: Path
    package_root: Path
    source_identity_path: Path


def _build_environment(
    *,
    source_revision: str,
    source_tree: str,
    source_committer_epoch: int,
    source_committed_at_utc: str,
    source_file_count: int,
    source_total_bytes: int,
    source_inventory_sha256: str,
) -> dict[str, str]:
    environment = _inherited_allowlist(_BUILD_RUNTIME_ENVIRONMENT)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["SECTOR_SOURCE_REVISION"] = source_revision
    environment["SECTOR_SOURCE_TREE"] = source_tree
    environment["SECTOR_SOURCE_COMMITTER_EPOCH"] = str(source_committer_epoch)
    environment["SECTOR_SOURCE_COMMITTED_AT_UTC"] = source_committed_at_utc
    environment["SECTOR_SOURCE_FILE_COUNT"] = str(source_file_count)
    environment["SECTOR_SOURCE_TOTAL_BYTES"] = str(source_total_bytes)
    environment["SECTOR_SOURCE_INVENTORY_SHA256"] = source_inventory_sha256
    environment["SOURCE_DATE_EPOCH"] = str(source_committer_epoch)
    # PyInstaller documents build-time hash randomization as a source of
    # otherwise unexplained byte differences in its compiled archives. Pin
    # the seed so an inherited value cannot make controlled builds diverge.
    environment["PYTHONHASHSEED"] = "1"
    return environment


def _pip_environment(environment: dict[str, str]) -> dict[str, str]:
    """Add only network and CA settings justified for the dependency fetch."""
    result = dict(environment)
    result.update(_inherited_allowlist(_PIP_NETWORK_ENVIRONMENT))
    return result


def source_identity_object(evidence: ExportEvidence) -> dict[str, str | int]:
    return {
        "source_revision": evidence.source_revision,
        "source_tree": evidence.source_tree,
        "source_committer_epoch": evidence.source_committer_epoch,
        "source_committed_at_utc": evidence.source_committed_at_utc,
        "source_file_count": evidence.file_count,
        "source_total_bytes": evidence.total_bytes,
        "source_inventory_sha256": evidence.inventory_sha256,
    }


def _write_source_identity(path: Path, evidence: ExportEvidence) -> None:
    payload = (
        json.dumps(source_identity_object(evidence), indent=2, sort_keys=True)
        + "\n"
    ).encode("ascii")
    try:
        with path.open("xb") as stream:
            stream.write(payload)
    except FileExistsError as exc:
        raise ExactBuildError(f"source identity evidence already exists: {path}") from exc
    except OSError as exc:
        raise ExactBuildError(f"cannot preserve source identity evidence: {path}") from exc


def _command(
    arguments: tuple[str, ...], source_root: Path, environment: dict[str, str]
) -> BuildCommand:
    return BuildCommand(arguments, source_root, dict(environment))


def prepare_exact_build(
    root: Path, source_revision: str, output: Path
) -> ExactBuildPlan:
    """Authenticate exact source first, then create an isolated immutable build plan."""
    if os.path.lexists(output):
        raise ExactBuildError(f"exact build output already exists: {output}")
    run_root = output.resolve(strict=False)
    source_root = run_root / "source"
    try:
        source_evidence = export_commit(root, source_revision, source_root)
    except CommitTreeError as git_error:
        try:
            source_evidence = materialize_source_release(
                root, source_revision, source_root
            )
        except SourceReleaseError as release_error:
            raise ExactBuildError(
                "cannot authenticate exact build source as a Git commit or verified "
                f"source release: Git: {git_error}; source release: {release_error}"
            ) from release_error

    source_identity_path = run_root / "source-identity.json"
    _write_source_identity(source_identity_path, source_evidence)
    environment = _build_environment(
        source_revision=source_evidence.source_revision,
        source_tree=source_evidence.source_tree,
        source_committer_epoch=source_evidence.source_committer_epoch,
        source_committed_at_utc=source_evidence.source_committed_at_utc,
        source_file_count=source_evidence.file_count,
        source_total_bytes=source_evidence.total_bytes,
        source_inventory_sha256=source_evidence.inventory_sha256,
    )
    python = str(Path(sys.executable).resolve())
    build_environment_root = run_root / "build-environment"
    environment_python = build_environment_root / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    notices = source_root / "build" / "legal" / "THIRD_PARTY_NOTICES.txt"
    manifest = source_root / "build" / "sector_build_info.json"
    for generated_path in (notices, manifest):
        if os.path.lexists(generated_path):
            raise ExactBuildError(
                f"generated exact-source path already exists: {generated_path}"
            )
    work_path = run_root / "pyinstaller-work"
    dist_path = run_root / "dist"
    pip_environment = _pip_environment(environment)
    pyinstaller_environment = dict(environment)
    pyinstaller_environment["PYINSTALLER_CONFIG_DIR"] = str(
        run_root / "pyinstaller-config"
    )
    commands = (
        _command(
            (
                python,
                "-I",
                "-m",
                "venv",
                str(build_environment_root),
            ),
            source_root,
            environment,
        ),
        _command(
            (
                str(environment_python),
                "-I",
                "-m",
                "pip",
                "--isolated",
                "--disable-pip-version-check",
                "--no-input",
                "install",
                "--require-hashes",
                "-r",
                str(source_root / "requirements-build.txt"),
            ),
            source_root,
            pip_environment,
        ),
        _command(
            (
                str(environment_python),
                str(source_root / "tools" / "generate_third_party_notices.py"),
                "--output",
                str(notices),
                "--requirements",
                str(source_root / "requirements-build.txt"),
                "--tabulator-license",
                str(source_root / "app" / "point_grid_frontend" / "LICENSE"),
            ),
            source_root,
            environment,
        ),
        _command(
            (
                str(environment_python),
                "-P",
                "-s",
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--workpath",
                str(work_path),
                "--distpath",
                str(dist_path),
                str(source_root / "packaging" / "sector.spec"),
            ),
            source_root,
            pyinstaller_environment,
        ),
    )
    return ExactBuildPlan(
        source_revision=source_revision,
        run_root=run_root,
        source_root=source_root,
        package_root=dist_path / "Sector",
        source_identity_path=source_identity_path,
        source_evidence=source_evidence,
        commands=commands,
    )


def _run_checked(command: BuildCommand) -> None:
    try:
        completed = subprocess.run(
            list(command.arguments),
            cwd=command.cwd,
            env=command.environment,
            stdout=None,
            stderr=None,
            check=False,
        )
    except OSError as exc:
        raise ExactBuildError(
            f"cannot execute isolated build command: {command.arguments[0]}"
        ) from exc
    if completed.returncode != 0:
        raise ExactBuildError(
            "isolated build command failed with exit code "
            f"{completed.returncode}: {command.arguments[0]}"
        )


def _copy_new(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise ExactBuildError(f"isolated build input is missing: {source}")
    try:
        with source.open("rb") as input_stream, destination.open("xb") as output_stream:
            while True:
                block = input_stream.read(1024 * 1024)
                if not block:
                    break
                output_stream.write(block)
    except FileExistsError as exc:
        raise ExactBuildError(f"package file already exists: {destination}") from exc
    except OSError as exc:
        raise ExactBuildError(f"cannot assemble isolated package file: {destination}") from exc


def execute_exact_build(
    plan: ExactBuildPlan,
    *,
    runner: Callable[[BuildCommand], None] = _run_checked,
) -> ExactBuildEvidence:
    """Execute one prepared plan without deleting or overwriting prior output."""
    for command in plan.commands:
        runner(command)
    if not plan.package_root.is_dir():
        raise ExactBuildError(f"isolated package directory is missing: {plan.package_root}")
    executable = plan.package_root / "Sector.exe"
    if not executable.is_file():
        raise ExactBuildError(f"unsigned package executable is missing: {executable}")
    _copy_new(plan.source_root / "LICENSE", plan.package_root / "LICENSE.txt")
    _copy_new(
        plan.source_root / "build" / "legal" / "THIRD_PARTY_NOTICES.txt",
        plan.package_root / "THIRD_PARTY_NOTICES.txt",
    )
    evidence = plan.source_evidence
    return ExactBuildEvidence(
        source_revision=plan.source_revision,
        source_tree=evidence.source_tree,
        source_committer_epoch=evidence.source_committer_epoch,
        source_committed_at_utc=evidence.source_committed_at_utc,
        source_file_count=evidence.file_count,
        source_total_bytes=evidence.total_bytes,
        source_inventory_sha256=evidence.inventory_sha256,
        source_root=plan.source_root,
        package_root=plan.package_root,
        source_identity_path=plan.source_identity_path,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        plan = prepare_exact_build(
            arguments.root, arguments.source_revision, arguments.output
        )
        evidence = execute_exact_build(plan)
    except ExactBuildError as exc:
        print(f"exact-source build failed: {exc}", file=sys.stderr)
        return 2
    print(
        "unsigned exact-source QA package built: "
        f"{evidence.source_revision} | tree {evidence.source_tree} | "
        f"epoch {evidence.source_committer_epoch} | "
        f"{evidence.source_file_count} files | "
        f"{evidence.source_total_bytes} bytes | "
        f"{evidence.source_inventory_sha256} | {evidence.package_root}"
    )
    print("inspection only: do not launch, zip, or distribute this unsigned package")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
