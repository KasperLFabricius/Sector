"""Fail-closed, raw-commit checks for a Sector Windows release package."""

from __future__ import annotations

import argparse
import ast
import importlib.util
import itertools
import json
import os
import re
import stat
import sys
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any


def _load_exporter():
    path = Path(__file__).resolve().with_name("export_commit_tree.py")
    specification = importlib.util.spec_from_file_location(
        "sector_release_commit_exporter", path
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("cannot load the accepted exact-commit exporter")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        specification.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def _load_source_release():
    path = Path(__file__).resolve().with_name("build_source_release.py")
    specification = importlib.util.spec_from_file_location(
        "sector_release_source_archive", path
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("cannot load the accepted source-release verifier")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        specification.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


_EXPORTER = _load_exporter()
CommitTreeError = _EXPORTER.CommitTreeError
CommitSnapshot = _EXPORTER.CommitSnapshot
snapshot_commit = _EXPORTER.snapshot_commit
_SOURCE_RELEASE = _load_source_release()
SourceReleaseError = _SOURCE_RELEASE.SourceReleaseError
verify_source_release_directory = _SOURCE_RELEASE.verify_source_release_directory

EXPECTED_SOURCE_IDENTITY = {
    "__version__": "0.93",
    "__product_name__": "Sector",
    "__description__": "Structural-analysis and design calculation tool",
    "__author__": "Kasper Lindskov Fabricius",
    "__licensee__": "Sweco Danmark A/S",
    "__copyright__": (
        "Copyright (c) 2026 Kasper Lindskov Fabricius. All rights reserved."
    ),
}
_SECTOR_VERSION = re.compile(r"^[0-9]+\.[0-9]+$")
SOURCE_IDENTITY_KEYS = {
    "source_revision",
    "source_tree",
    "source_committer_epoch",
    "source_committed_at_utc",
    "source_file_count",
    "source_total_bytes",
    "source_inventory_sha256",
}
EXPECTED_MANIFEST_KEYS = {
    "product_name",
    "description",
    "sector_version",
    "author",
    "licensee",
    "copyright",
    "built_at_utc",
    *SOURCE_IDENTITY_KEYS,
}
_READ_BLOCK = 1024 * 1024
_MAX_RELEASE_METADATA_BYTES = 16 * 1024 * 1024
_MAX_RELEASE_EXECUTABLE_BYTES = 2 * 1024 * 1024 * 1024
_MAX_RELEASE_FILES = 50_000
_MAX_RELEASE_DIRECTORIES = 50_000
_MAX_RELEASE_TREE_ENTRIES = _MAX_RELEASE_FILES + _MAX_RELEASE_DIRECTORIES
MAX_SECTOR_VERSION_BYTES = 32


class ReleaseVerificationError(ValueError):
    """Raised when a release input is incomplete or inconsistent."""


def _snapshot(repository: Path, source_revision: str) -> CommitSnapshot:
    repository = _lexical_source_root(repository)
    if _EXPORTER.OBJECT_ID.fullmatch(source_revision) is None:
        raise ReleaseVerificationError(
            "source revision must be an exact lowercase 40-hex SHA-1"
        )
    try:
        return snapshot_commit(repository, source_revision)
    except CommitTreeError as git_error:
        try:
            return verify_source_release_directory(repository, source_revision)
        except SourceReleaseError as release_error:
            raise ReleaseVerificationError(
                "cannot authenticate exact source as a Git commit or verified "
                f"source release: Git: {git_error}; source release: {release_error}"
            ) from release_error


def _snapshot_files(snapshot: CommitSnapshot) -> dict[str, Any]:
    return {item.path: item for item in snapshot.files}


def _source_identity_object(snapshot: CommitSnapshot) -> dict[str, str | int]:
    evidence = snapshot.evidence
    return {
        "source_revision": evidence.source_revision,
        "source_tree": evidence.source_tree,
        "source_committer_epoch": evidence.source_committer_epoch,
        "source_committed_at_utc": evidence.source_committed_at_utc,
        "source_file_count": evidence.file_count,
        "source_total_bytes": evidence.total_bytes,
        "source_inventory_sha256": evidence.inventory_sha256,
    }


def _decode_source(snapshot: CommitSnapshot, relative: str) -> str:
    item = _snapshot_files(snapshot).get(relative)
    if item is None:
        raise ReleaseVerificationError(f"source commit is missing {relative}")
    try:
        return item.payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReleaseVerificationError(
            f"source commit file is not UTF-8: {relative}"
        ) from exc


def _literal_assignments(
    source: str, filename: str, names: set[str]
) -> dict[str, str]:
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        raise ReleaseVerificationError(f"cannot parse source identity: {exc}") from exc
    values: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in names:
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, TypeError) as exc:
            raise ReleaseVerificationError(
                f"source identity {target.id} is not a literal"
            ) from exc
        if not isinstance(value, str) or not value.strip():
            raise ReleaseVerificationError(f"source identity {target.id} is invalid")
        values[target.id] = value
    return values


def _product_identity(snapshot: CommitSnapshot) -> dict[str, str]:
    values = _literal_assignments(
        _decode_source(snapshot, "sector/__init__.py"),
        "sector/__init__.py",
        set(EXPECTED_SOURCE_IDENTITY),
    )
    expected_nonversion = {
        key: value
        for key, value in EXPECTED_SOURCE_IDENTITY.items()
        if key != "__version__"
    }
    actual_nonversion = {
        key: value for key, value in values.items() if key != "__version__"
    }
    version = values.get("__version__", "")
    if (
        set(values) != set(EXPECTED_SOURCE_IDENTITY)
        or actual_nonversion != expected_nonversion
        or len(version) > MAX_SECTOR_VERSION_BYTES
        or _SECTOR_VERSION.fullmatch(version) is None
    ):
        raise ReleaseVerificationError("Sector source identity is incomplete or changed")

    resource_text = _decode_source(snapshot, "packaging/windows_version_info.txt")
    try:
        ast.parse(resource_text, filename="packaging/windows_version_info.txt")
    except SyntaxError as exc:
        raise ReleaseVerificationError(
            f"Windows version resource is invalid: {exc}"
        ) from exc
    major, minor = (int(component) for component in version.split("."))
    dotted_version = f"{major}.{minor}.0.0"
    required_tokens = (
        f"filevers=({major}, {minor}, 0, 0)",
        f"prodvers=({major}, {minor}, 0, 0)",
        f"StringStruct('FileVersion', '{dotted_version}')",
        f"StringStruct('ProductVersion', '{dotted_version}')",
        "StringStruct('ProductName', 'Sector')",
        "StringStruct('OriginalFilename', 'Sector.exe')",
        "Licensed to Sweco Danmark A/S for internal organisational use only.",
    )
    for token in required_tokens:
        if resource_text.count(token) != 1:
            raise ReleaseVerificationError(
                f"Windows resource identity is missing: {token}"
            )
    if "CompanyName" in resource_text or "Publisher" in resource_text:
        raise ReleaseVerificationError("Windows resource advertises a company identity")
    return values


def _validate_product_identity(snapshot: CommitSnapshot) -> None:
    _product_identity(snapshot)


def _canonical_json(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("ascii")


def _read_json_object(
    path: Path, label: str, *, boundary: Path | None = None
) -> tuple[dict[str, Any], bytes]:
    try:
        raw = _read_regular_file(path, label, boundary=boundary)
        value = json.loads(raw)
    except ReleaseVerificationError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseVerificationError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReleaseVerificationError(f"{label} must be an object")
    return value, raw


def _authenticate_evidence(
    source_identity_path: Path, snapshot: CommitSnapshot
) -> None:
    value, raw = _read_json_object(
        source_identity_path,
        "source identity evidence",
        boundary=source_identity_path.parent,
    )
    expected = _source_identity_object(snapshot)
    if set(value) != SOURCE_IDENTITY_KEYS or value != expected:
        raise ReleaseVerificationError(
            "source identity evidence does not match the raw commit closure"
        )
    if raw != _canonical_json(expected):
        raise ReleaseVerificationError("source identity evidence is not canonical")


def _manifest_object(snapshot: CommitSnapshot) -> dict[str, Any]:
    source = _source_identity_object(snapshot)
    identity = _product_identity(snapshot)
    return {
        "product_name": identity["__product_name__"],
        "description": identity["__description__"],
        "sector_version": identity["__version__"],
        "author": identity["__author__"],
        "licensee": identity["__licensee__"],
        "copyright": identity["__copyright__"],
        "built_at_utc": source["source_committed_at_utc"],
        **source,
    }


def _is_reparse(status: os.stat_result) -> bool:
    attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(status, "st_file_attributes", 0) & attribute)


def _status_signature(status: os.stat_result) -> tuple[int, ...]:
    return (
        status.st_dev,
        status.st_ino,
        stat.S_IFMT(status.st_mode),
        status.st_size,
        status.st_mtime_ns,
        getattr(status, "st_file_attributes", 0),
    )


def _lstat(path: Path, label: str) -> os.stat_result:
    try:
        return os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise ReleaseVerificationError(f"cannot inspect {label}") from exc


def _require_regular_directory(path: Path, label: str) -> os.stat_result:
    status = _lstat(path, label)
    if stat.S_ISLNK(status.st_mode) or _is_reparse(status):
        raise ReleaseVerificationError(f"{label} is a link or reparse point")
    if not stat.S_ISDIR(status.st_mode):
        raise ReleaseVerificationError(f"{label} is not a regular directory")
    return status


def _lexical_source_root(root: Path) -> Path:
    """Reject a linked repository-root entry before exporter resolution."""
    lexical = Path(os.path.abspath(root))
    _require_regular_directory(lexical, "release source root")
    return lexical


def _directory_chain(
    directory: Path, boundary: Path, label: str
) -> tuple[tuple[Path, os.stat_result], ...]:
    directory = Path(os.path.abspath(directory))
    boundary = Path(os.path.abspath(boundary))
    try:
        relative = directory.relative_to(boundary)
    except ValueError as exc:
        raise ReleaseVerificationError(f"{label} escapes the package boundary") from exc
    paths = [boundary]
    for component in relative.parts:
        paths.append(paths[-1] / component)
    return tuple(
        (path, _require_regular_directory(path, f"{label} ancestor"))
        for path in paths
    )


def _same_status_chain(
    first: tuple[tuple[Path, os.stat_result], ...],
    second: tuple[tuple[Path, os.stat_result], ...],
) -> bool:
    return len(first) == len(second) and all(
        first_path == second_path
        and _status_signature(first_status) == _status_signature(second_status)
        for (first_path, first_status), (second_path, second_status) in zip(
            first, second, strict=True
        )
    )


def _consume_regular_file(
    path: Path,
    label: str,
    *,
    boundary: Path | None,
    limit: int,
    collect: bool,
    expected: bytes | None = None,
    mismatch_message: str | None = None,
) -> tuple[bytes, int]:
    path = Path(os.path.abspath(path))
    ancestor_before = (
        _directory_chain(path.parent, boundary, label)
        if boundary is not None
        else ()
    )
    before = _lstat(path, label)
    if stat.S_ISLNK(before.st_mode) or _is_reparse(before):
        raise ReleaseVerificationError(f"{label} is a link or reparse point")
    if not stat.S_ISREG(before.st_mode):
        raise ReleaseVerificationError(f"{label} is not a regular file")
    mismatch = expected is not None and before.st_size != len(expected)
    if mismatch:
        raise ReleaseVerificationError(
            mismatch_message or f"{label} differs from authenticated bytes"
        )
    if before.st_size > limit:
        raise ReleaseVerificationError(f"{label} exceeds the release resource limit")

    flags = os.O_RDONLY
    for flag_name in ("O_BINARY", "O_CLOEXEC", "O_NOINHERIT", "O_NOFOLLOW"):
        flags |= getattr(os, flag_name, 0)
    chunks: list[bytes] = []
    total = 0
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            opened_before = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(opened_before.st_mode)
                or _is_reparse(opened_before)
                or _status_signature(opened_before) != _status_signature(before)
            ):
                raise ReleaseVerificationError(f"{label} changed while it was opened")
            while True:
                block = stream.read(_READ_BLOCK)
                if not block:
                    break
                end = total + len(block)
                if end > limit:
                    raise ReleaseVerificationError(
                        f"{label} exceeds the release resource limit"
                    )
                if expected is not None and block != expected[total:end]:
                    mismatch = True
                total = end
                if collect:
                    chunks.append(block)
            opened_after = os.fstat(stream.fileno())
        after = _lstat(path, label)
        ancestor_after = (
            _directory_chain(path.parent, boundary, label)
            if boundary is not None
            else ()
        )
    except ReleaseVerificationError:
        raise
    except OSError as exc:
        raise ReleaseVerificationError(f"cannot read {label}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    signatures = (before, opened_before, opened_after, after)
    if any(
        _status_signature(left) != _status_signature(right)
        for left, right in itertools.pairwise(signatures)
    ):
        raise ReleaseVerificationError(f"{label} changed while it was read")
    if total != before.st_size:
        raise ReleaseVerificationError(f"{label} byte count changed while it was read")
    if not _same_status_chain(ancestor_before, ancestor_after):
        raise ReleaseVerificationError(f"{label} ancestor changed while it was read")
    if expected is not None and (mismatch or total != len(expected)):
        raise ReleaseVerificationError(
            mismatch_message or f"{label} differs from authenticated bytes"
        )
    return (b"".join(chunks) if collect else b""), total


def _read_regular_file(
    path: Path,
    label: str,
    *,
    boundary: Path | None = None,
    limit: int = _MAX_RELEASE_METADATA_BYTES,
) -> bytes:
    payload, _size = _consume_regular_file(
        path,
        label,
        boundary=boundary,
        limit=limit,
        collect=True,
    )
    return payload


def _verify_regular_file(
    path: Path,
    label: str,
    *,
    boundary: Path | None = None,
    limit: int,
    expected: bytes | None = None,
    mismatch_message: str | None = None,
) -> int:
    _payload, size = _consume_regular_file(
        path,
        label,
        boundary=boundary,
        limit=limit,
        collect=False,
        expected=expected,
        mismatch_message=mismatch_message,
    )
    return size


def _regular_tree(
    root: Path, *, boundary: Path | None = None
) -> dict[str, Path]:
    root = Path(os.path.abspath(root))
    boundary = root if boundary is None else Path(os.path.abspath(boundary))
    root_chain_before = _directory_chain(root, boundary, "package source")
    pending: list[tuple[Path, tuple[str, ...]]] = [(root, ())]
    files: dict[str, Path] = {}
    normalized_paths: set[str] = set()
    entry_count = 0
    file_count = 0
    directory_count = 0
    while pending:
        directory, parts = pending.pop()
        directory_before = _require_regular_directory(
            directory, "package source directory"
        )
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    entry_count += 1
                    if entry_count > _MAX_RELEASE_TREE_ENTRIES:
                        raise ReleaseVerificationError(
                            "package source tree exceeds the entry limit"
                        )
                    try:
                        status = entry.stat(follow_symlinks=False)
                    except OSError as exc:
                        raise ReleaseVerificationError(
                            f"cannot inspect package source entry: {entry.name}"
                        ) from exc
                    child = (*parts, entry.name)
                    relative = PurePosixPath(*child).as_posix()
                    if entry.is_symlink() or _is_reparse(status):
                        raise ReleaseVerificationError(
                            "package source contains a link or reparse point: "
                            f"{relative}"
                        )
                    key = unicodedata.normalize("NFC", relative).casefold()
                    if key in normalized_paths:
                        raise ReleaseVerificationError(
                            f"package source contains colliding paths: {relative}"
                        )
                    normalized_paths.add(key)
                    if stat.S_ISDIR(status.st_mode):
                        directory_count += 1
                        if directory_count > _MAX_RELEASE_DIRECTORIES:
                            raise ReleaseVerificationError(
                                "package source tree exceeds the directory limit"
                            )
                        pending.append((Path(entry.path), child))
                    elif stat.S_ISREG(status.st_mode):
                        file_count += 1
                        if file_count > _MAX_RELEASE_FILES:
                            raise ReleaseVerificationError(
                                "package source tree exceeds the file limit"
                            )
                        files[relative] = Path(entry.path)
                    else:
                        raise ReleaseVerificationError(
                            f"package source contains a nonregular entry: {relative}"
                        )
        except OSError as exc:
            raise ReleaseVerificationError(
                f"cannot inspect package source tree: {directory}"
            ) from exc
        directory_after = _require_regular_directory(
            directory, "package source directory"
        )
        if _status_signature(directory_before) != _status_signature(directory_after):
            raise ReleaseVerificationError(
                f"package source directory changed while inspected: {directory}"
            )
    root_chain_after = _directory_chain(root, boundary, "package source")
    if not _same_status_chain(root_chain_before, root_chain_after):
        raise ReleaseVerificationError(
            "package source ancestor changed while the tree was inspected"
        )
    return files


def _require_raw_snapshot_tree(
    snapshot: CommitSnapshot,
    source_prefix: str,
    package_root: Path,
    *,
    boundary: Path,
    allowed_extra: frozenset[str] = frozenset(),
) -> None:
    prefix = source_prefix + "/"
    expected = {
        item.path[len(prefix) :]: item
        for item in snapshot.files
        if item.path.startswith(prefix)
    }
    if not expected:
        raise ReleaseVerificationError(
            f"source commit has no files under {source_prefix}"
        )
    for _authentication_pass in range(2):
        actual = _regular_tree(package_root, boundary=boundary)
        actual_paths = set(actual)
        if actual_paths.difference(allowed_extra) != set(expected):
            raise ReleaseVerificationError(
                f"packaged {source_prefix} inventory differs from raw source commit"
            )
        for relative, item in expected.items():
            mismatch = (
                "packaged source differs from raw commit: "
                f"{source_prefix}/{relative}"
            )
            _verify_regular_file(
                actual[relative],
                f"packaged source file: {source_prefix}/{relative}",
                boundary=boundary,
                limit=len(item.payload),
                expected=item.payload,
                mismatch_message=mismatch,
            )


def verify_source(repository: Path, source_revision: str) -> None:
    """Authenticate product identity only from the selected raw commit closure."""
    snapshot = _snapshot(repository, source_revision)
    _validate_product_identity(snapshot)


def verify_package(
    repository: Path,
    package: Path,
    source_revision: str,
    source_identity_path: Path | None = None,
) -> None:
    """Validate packaged identity against an in-memory raw Git snapshot."""
    if source_identity_path is None:
        raise ReleaseVerificationError(
            "package verification requires source identity evidence"
        )
    package = Path(os.path.abspath(package))
    source_identity_path = Path(os.path.abspath(source_identity_path))
    package_before = _require_regular_directory(package, "package root")
    snapshot = _snapshot(repository, source_revision)
    _validate_product_identity(snapshot)
    _authenticate_evidence(source_identity_path, snapshot)

    required = {
        "executable": package / "Sector.exe",
        "manifest": package / "_internal" / "sector" / "sector_build_info.json",
        "license": package / "LICENSE.txt",
        "notices": package / "THIRD_PARTY_NOTICES.txt",
    }
    missing = [
        label for label, path in required.items() if not os.path.lexists(path)
    ]
    if missing:
        raise ReleaseVerificationError(
            f"package is missing required files: {', '.join(sorted(missing))}"
        )
    executable_size = _verify_regular_file(
        required["executable"],
        "Sector.exe",
        boundary=package,
        limit=_MAX_RELEASE_EXECUTABLE_BYTES,
    )
    if executable_size <= 0:
        raise ReleaseVerificationError("Sector.exe is empty")

    files = _snapshot_files(snapshot)
    try:
        expected_license = files["LICENSE"].payload
    except KeyError as exc:
        raise ReleaseVerificationError("cannot authenticate packaged license") from exc
    _verify_regular_file(
        required["license"],
        "packaged license",
        boundary=package,
        limit=len(expected_license),
        expected=expected_license,
        mismatch_message="packaged license differs from raw source commit",
    )

    try:
        notices = _read_regular_file(
            required["notices"],
            "third-party notices",
            boundary=package,
        ).decode("utf-8")
    except UnicodeError as exc:
        raise ReleaseVerificationError("cannot read third-party notices") from exc
    for token in ("SECTOR THIRD-PARTY NOTICES", "numpy", "streamlit"):
        if token.casefold() not in notices.casefold():
            raise ReleaseVerificationError(
                f"third-party notice bundle is missing {token}"
            )

    manifest, raw_manifest = _read_json_object(
        required["manifest"], "package manifest", boundary=package
    )
    expected_manifest = _manifest_object(snapshot)
    if set(manifest) != EXPECTED_MANIFEST_KEYS or manifest != expected_manifest:
        raise ReleaseVerificationError(
            "package manifest does not match authenticated source identity"
        )
    if raw_manifest != _canonical_json(expected_manifest):
        raise ReleaseVerificationError("package manifest is not canonical")

    internal = package / "_internal"
    _require_raw_snapshot_tree(
        snapshot, "app", internal / "app", boundary=package
    )
    _require_raw_snapshot_tree(
        snapshot,
        "sector",
        internal / "sector",
        boundary=package,
        allowed_extra=frozenset({"sector_build_info.json"}),
    )
    _require_raw_snapshot_tree(
        snapshot, "assets", internal / "assets", boundary=package
    )
    package_after = _require_regular_directory(package, "package root")
    if _status_signature(package_before) != _status_signature(package_after):
        raise ReleaseVerificationError("package root changed during verification")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--package", type=Path)
    parser.add_argument("--source-identity", type=Path)
    parser.add_argument("--preflight", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = _lexical_source_root(args.root)
    if args.preflight:
        if args.package is not None or args.source_identity is not None:
            raise ReleaseVerificationError(
                "preflight does not accept package or source identity evidence"
            )
        verify_source(root, args.source_revision)
    else:
        if args.package is None or args.source_identity is None:
            raise ReleaseVerificationError(
                "package verification requires --package and --source-identity"
            )
        verify_package(
            root,
            Path(os.path.abspath(args.package)),
            args.source_revision,
            Path(os.path.abspath(args.source_identity)),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
