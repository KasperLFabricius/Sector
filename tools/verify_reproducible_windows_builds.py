"""Compare two exact-source Windows packages without trusting either builder."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _load_release_verifier():
    path = Path(__file__).resolve().with_name("verify_windows_release.py")
    specification = importlib.util.spec_from_file_location(
        "sector_reproducibility_release_verifier", path
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("cannot load the accepted Windows release verifier")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


_RELEASE = _load_release_verifier()
ReleaseVerificationError = _RELEASE.ReleaseVerificationError
SOURCE_IDENTITY_KEYS = _RELEASE.SOURCE_IDENTITY_KEYS
_is_reparse = _RELEASE._is_reparse
_regular_tree = _RELEASE._regular_tree
verify_package = _RELEASE.verify_package

BLOCK_SIZE = 1024 * 1024


class ReproducibilityVerificationError(ValueError):
    """Two independently built packages could not be proven byte-identical."""


@dataclass(frozen=True)
class PackageFileEvidence:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class ComparisonPass:
    package_file_count: int
    package_total_bytes: int
    package_inventory_sha256: str
    files: tuple[PackageFileEvidence, ...]


@dataclass(frozen=True)
class ReproducibilityEvidence:
    source_revision: str
    source_tree: str
    source_committer_epoch: int
    source_committed_at_utc: str
    source_file_count: int
    source_total_bytes: int
    source_inventory_sha256: str
    source_identity_sha256: str
    package_file_count: int
    package_total_bytes: int
    package_inventory_sha256: str
    files: tuple[PackageFileEvidence, ...]
    evidence_path: Path


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("ascii")


def _canonical_line(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("ascii")


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(path))


def _normalized(path: Path) -> str:
    return os.path.normcase(str(_absolute(path)))


def _within(path: Path, root: Path) -> bool:
    try:
        _absolute(path).relative_to(_absolute(root))
    except ValueError:
        return False
    return True


def _same_file(first: Path, second: Path, label: str) -> None:
    try:
        identical = os.path.samefile(first, second)
    except OSError as exc:
        raise ReproducibilityVerificationError(
            f"cannot authenticate distinct {label}: {exc}"
        ) from exc
    if identical:
        raise ReproducibilityVerificationError(
            f"reproducibility comparison requires distinct {label}"
        )


def _require_regular_file(path: Path, label: str) -> None:
    try:
        status = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise ReproducibilityVerificationError(f"cannot inspect {label}: {exc}") from exc
    if stat.S_ISLNK(status.st_mode) or _is_reparse(status):
        raise ReproducibilityVerificationError(f"{label} is a link or reparse point")
    if not stat.S_ISREG(status.st_mode):
        raise ReproducibilityVerificationError(f"{label} is not a regular file")


def _require_regular_directory(path: Path, label: str) -> None:
    try:
        status = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise ReproducibilityVerificationError(f"cannot inspect {label}: {exc}") from exc
    if stat.S_ISLNK(status.st_mode) or _is_reparse(status):
        raise ReproducibilityVerificationError(f"{label} is a link or reparse point")
    if not stat.S_ISDIR(status.st_mode):
        raise ReproducibilityVerificationError(f"{label} is not a directory")


def _validate_layout(
    package_a: Path,
    package_b: Path,
    identity_a: Path,
    identity_b: Path,
    evidence_path: Path,
) -> tuple[Path, Path]:
    if os.path.lexists(evidence_path):
        raise ReproducibilityVerificationError(
            f"reproducibility evidence already exists: {evidence_path}"
        )
    package_a = _absolute(package_a)
    package_b = _absolute(package_b)
    identity_a = _absolute(identity_a)
    identity_b = _absolute(identity_b)
    build_a = package_a.parent.parent
    build_b = package_b.parent.parent
    expected_a = build_a / "source-identity.json"
    expected_b = build_b / "source-identity.json"
    if package_a.parent.name != "dist" or package_a.name != "Sector":
        raise ReproducibilityVerificationError("first package has an invalid build layout")
    if package_b.parent.name != "dist" or package_b.name != "Sector":
        raise ReproducibilityVerificationError("second package has an invalid build layout")
    if _normalized(identity_a) != _normalized(expected_a):
        raise ReproducibilityVerificationError(
            "first source identity is outside its exact build root"
        )
    if _normalized(identity_b) != _normalized(expected_b):
        raise ReproducibilityVerificationError(
            "second source identity is outside its exact build root"
        )
    if _normalized(build_a) == _normalized(build_b):
        raise ReproducibilityVerificationError(
            "reproducibility comparison requires distinct build roots"
        )
    if _within(build_a, build_b) or _within(build_b, build_a):
        raise ReproducibilityVerificationError(
            "reproducibility build roots must not contain each other"
        )
    if _within(evidence_path, build_a) or _within(evidence_path, build_b):
        raise ReproducibilityVerificationError(
            "reproducibility evidence must be outside both build roots"
        )
    _require_regular_directory(evidence_path.parent, "reproducibility evidence parent")
    _require_regular_file(identity_a, "first source identity")
    _require_regular_file(identity_b, "second source identity")
    _same_file(build_a, build_b, "build roots")
    _same_file(package_a, package_b, "package roots")
    _same_file(identity_a, identity_b, "source identity files")
    return package_a, package_b


def _read_source_identity(
    path: Path, source_revision: str
) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReproducibilityVerificationError(
            f"cannot read source identity evidence: {exc}"
        ) from exc
    if not isinstance(value, dict) or set(value) != SOURCE_IDENTITY_KEYS:
        raise ReproducibilityVerificationError("source identity is incomplete")
    if raw != _canonical_json(value):
        raise ReproducibilityVerificationError("source identity is not canonical")
    if value.get("source_revision") != source_revision:
        raise ReproducibilityVerificationError(
            "source identity does not name the selected commit"
        )
    return value, raw


def _status_signature(status: os.stat_result) -> tuple[int, ...]:
    return (
        status.st_dev,
        status.st_ino,
        status.st_size,
        status.st_mtime_ns,
    )


def _compare_regular_files(
    first: Path, second: Path, relative: str
) -> PackageFileEvidence:
    digest = hashlib.sha256()
    total = 0
    try:
        first_path_before = os.stat(first, follow_symlinks=False)
        second_path_before = os.stat(second, follow_symlinks=False)
        with first.open("rb") as stream_a, second.open("rb") as stream_b:
            first_handle_before = os.fstat(stream_a.fileno())
            second_handle_before = os.fstat(stream_b.fileno())
            if not stat.S_ISREG(first_handle_before.st_mode) or not stat.S_ISREG(
                second_handle_before.st_mode
            ):
                raise ReproducibilityVerificationError(
                    f"package output is not a regular file: {relative}"
                )
            if _status_signature(first_path_before) != _status_signature(
                first_handle_before
            ) or _status_signature(second_path_before) != _status_signature(
                second_handle_before
            ):
                raise ReproducibilityVerificationError(
                    f"package output changed while it was opened: {relative}"
                )
            while True:
                block_a = stream_a.read(BLOCK_SIZE)
                block_b = stream_b.read(BLOCK_SIZE)
                if block_a != block_b:
                    raise ReproducibilityVerificationError(
                        f"package bytes differ between builds: {relative}"
                    )
                if not block_a:
                    break
                digest.update(block_a)
                total += len(block_a)
            first_handle_after = os.fstat(stream_a.fileno())
            second_handle_after = os.fstat(stream_b.fileno())
        first_path_after = os.stat(first, follow_symlinks=False)
        second_path_after = os.stat(second, follow_symlinks=False)
    except ReproducibilityVerificationError:
        raise
    except OSError as exc:
        raise ReproducibilityVerificationError(
            f"cannot compare package output: {relative}"
        ) from exc
    signatures = (
        (first_path_before, first_handle_before),
        (first_handle_before, first_handle_after),
        (first_handle_after, first_path_after),
        (second_path_before, second_handle_before),
        (second_handle_before, second_handle_after),
        (second_handle_after, second_path_after),
    )
    if any(
        _status_signature(before) != _status_signature(after)
        for before, after in signatures
    ):
        raise ReproducibilityVerificationError(
            f"package output changed during comparison: {relative}"
        )
    return PackageFileEvidence(relative, total, digest.hexdigest())


def _compare_pass(package_a: Path, package_b: Path) -> ComparisonPass:
    try:
        files_a = _regular_tree(package_a, boundary=package_a.parent.parent)
        files_b = _regular_tree(package_b, boundary=package_b.parent.parent)
    except ReleaseVerificationError as exc:
        raise ReproducibilityVerificationError(
            f"cannot authenticate complete package trees: {exc}"
        ) from exc
    if set(files_a) != set(files_b):
        raise ReproducibilityVerificationError(
            "package inventories differ between builds"
        )
    evidence = tuple(
        _compare_regular_files(files_a[relative], files_b[relative], relative)
        for relative in sorted(files_a)
    )
    inventory = hashlib.sha256()
    for item in evidence:
        inventory.update(
            _canonical_line(
                {"path": item.path, "sha256": item.sha256, "size": item.size}
            )
        )
    return ComparisonPass(
        package_file_count=len(evidence),
        package_total_bytes=sum(item.size for item in evidence),
        package_inventory_sha256=inventory.hexdigest(),
        files=evidence,
    )


def _evidence_object(
    source_identity: dict[str, Any],
    source_identity_sha256: str,
    comparison: ComparisonPass,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "comparison": "complete-package-byte-identity",
        "source_identity": source_identity,
        "source_identity_sha256": source_identity_sha256,
        "package_file_count": comparison.package_file_count,
        "package_total_bytes": comparison.package_total_bytes,
        "package_inventory_sha256": comparison.package_inventory_sha256,
        "files": [
            {"path": item.path, "size": item.size, "sha256": item.sha256}
            for item in comparison.files
        ],
    }


def _write_evidence(path: Path, value: dict[str, Any]) -> None:
    try:
        with path.open("xb") as stream:
            stream.write(_canonical_json(value))
    except FileExistsError as exc:
        raise ReproducibilityVerificationError(
            f"reproducibility evidence already exists: {path}"
        ) from exc
    except OSError as exc:
        raise ReproducibilityVerificationError(
            f"cannot preserve reproducibility evidence: {path}"
        ) from exc


def compare_reproducible_builds(
    repository: Path,
    source_revision: str,
    package_a: Path,
    package_b: Path,
    source_identity_a: Path,
    source_identity_b: Path,
    evidence_path: Path,
) -> ReproducibilityEvidence:
    """Authenticate two distinct packages and prove complete byte identity."""
    repository = _absolute(repository)
    package_a = _absolute(package_a)
    package_b = _absolute(package_b)
    source_identity_a = _absolute(source_identity_a)
    source_identity_b = _absolute(source_identity_b)
    evidence_path = _absolute(evidence_path)
    package_a, package_b = _validate_layout(
        package_a,
        package_b,
        source_identity_a,
        source_identity_b,
        evidence_path,
    )
    try:
        verify_package(
            repository, package_a, source_revision, source_identity_a
        )
        verify_package(
            repository, package_b, source_revision, source_identity_b
        )
    except ReleaseVerificationError as exc:
        raise ReproducibilityVerificationError(
            f"exact-source package verification failed: {exc}"
        ) from exc
    identity_a, raw_identity_a = _read_source_identity(
        source_identity_a, source_revision
    )
    identity_b, raw_identity_b = _read_source_identity(
        source_identity_b, source_revision
    )
    if identity_a != identity_b or raw_identity_a != raw_identity_b:
        raise ReproducibilityVerificationError(
            "independent builds have different source identity evidence"
        )

    first_pass = _compare_pass(package_a, package_b)
    second_pass = _compare_pass(package_a, package_b)
    if first_pass != second_pass:
        raise ReproducibilityVerificationError(
            "package outputs changed between authentication passes"
        )
    final_identity_a, final_raw_identity_a = _read_source_identity(
        source_identity_a, source_revision
    )
    final_identity_b, final_raw_identity_b = _read_source_identity(
        source_identity_b, source_revision
    )
    if (
        identity_a != final_identity_a
        or identity_b != final_identity_b
        or raw_identity_a != final_raw_identity_a
        or raw_identity_b != final_raw_identity_b
    ):
        raise ReproducibilityVerificationError(
            "source identity changed during package comparison"
        )
    source_identity_sha256 = hashlib.sha256(raw_identity_a).hexdigest()
    value = _evidence_object(identity_a, source_identity_sha256, second_pass)
    _write_evidence(evidence_path, value)
    return ReproducibilityEvidence(
        source_revision=identity_a["source_revision"],
        source_tree=identity_a["source_tree"],
        source_committer_epoch=identity_a["source_committer_epoch"],
        source_committed_at_utc=identity_a["source_committed_at_utc"],
        source_file_count=identity_a["source_file_count"],
        source_total_bytes=identity_a["source_total_bytes"],
        source_inventory_sha256=identity_a["source_inventory_sha256"],
        source_identity_sha256=source_identity_sha256,
        package_file_count=second_pass.package_file_count,
        package_total_bytes=second_pass.package_total_bytes,
        package_inventory_sha256=second_pass.package_inventory_sha256,
        files=second_pass.files,
        evidence_path=evidence_path,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--package-a", required=True, type=Path)
    parser.add_argument("--package-b", required=True, type=Path)
    parser.add_argument("--source-identity-a", required=True, type=Path)
    parser.add_argument("--source-identity-b", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        evidence = compare_reproducible_builds(
            arguments.root,
            arguments.source_revision,
            arguments.package_a,
            arguments.package_b,
            arguments.source_identity_a,
            arguments.source_identity_b,
            arguments.evidence,
        )
    except ReproducibilityVerificationError as exc:
        print(f"two-build reproducibility verification failed: {exc}", file=sys.stderr)
        return 2
    print(
        "independent packages are byte-identical: "
        f"{evidence.source_revision} | tree {evidence.source_tree} | "
        f"{evidence.package_file_count} files | "
        f"{evidence.package_total_bytes} bytes | "
        f"{evidence.package_inventory_sha256} | {evidence.evidence_path}"
    )
    print("inspection only: neither unsigned executable was launched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
