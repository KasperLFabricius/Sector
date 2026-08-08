"""Fail-closed, raw-commit checks for a Sector Windows release package."""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
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
    specification.loader.exec_module(module)
    return module


_EXPORTER = _load_exporter()
CommitTreeError = _EXPORTER.CommitTreeError
CommitSnapshot = _EXPORTER.CommitSnapshot
snapshot_commit = _EXPORTER.snapshot_commit

EXPECTED_SOURCE_IDENTITY = {
    "__version__": "0.92",
    "__product_name__": "Sector",
    "__description__": "Structural-analysis and design calculation tool",
    "__author__": "Kasper Lindskov Fabricius",
    "__licensee__": "Sweco Danmark A/S",
    "__copyright__": (
        "Copyright (c) 2026 Kasper Lindskov Fabricius. All rights reserved."
    ),
}
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


class ReleaseVerificationError(ValueError):
    """Raised when a release input is incomplete or inconsistent."""


def _snapshot(repository: Path, source_revision: str) -> CommitSnapshot:
    try:
        return snapshot_commit(repository, source_revision)
    except CommitTreeError as exc:
        raise ReleaseVerificationError(
            f"cannot authenticate exact source commit: {exc}"
        ) from exc


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


def _validate_product_identity(snapshot: CommitSnapshot) -> None:
    values = _literal_assignments(
        _decode_source(snapshot, "sector/__init__.py"),
        "sector/__init__.py",
        set(EXPECTED_SOURCE_IDENTITY),
    )
    if values != EXPECTED_SOURCE_IDENTITY:
        raise ReleaseVerificationError("Sector source identity is incomplete or changed")

    resource_text = _decode_source(snapshot, "packaging/windows_version_info.txt")
    try:
        ast.parse(resource_text, filename="packaging/windows_version_info.txt")
    except SyntaxError as exc:
        raise ReleaseVerificationError(
            f"Windows version resource is invalid: {exc}"
        ) from exc
    required_tokens = (
        "filevers=(0, 92, 0, 0)",
        "prodvers=(0, 92, 0, 0)",
        "StringStruct('FileVersion', '0.92.0.0')",
        "StringStruct('ProductVersion', '0.92.0.0')",
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


def _canonical_json(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("ascii")


def _read_json_object(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseVerificationError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReleaseVerificationError(f"{label} must be an object")
    return value, raw


def _authenticate_evidence(
    source_identity_path: Path, snapshot: CommitSnapshot
) -> None:
    value, raw = _read_json_object(source_identity_path, "source identity evidence")
    expected = _source_identity_object(snapshot)
    if set(value) != SOURCE_IDENTITY_KEYS or value != expected:
        raise ReleaseVerificationError(
            "source identity evidence does not match the raw commit closure"
        )
    if raw != _canonical_json(expected):
        raise ReleaseVerificationError("source identity evidence is not canonical")


def _manifest_object(snapshot: CommitSnapshot) -> dict[str, Any]:
    source = _source_identity_object(snapshot)
    return {
        "product_name": EXPECTED_SOURCE_IDENTITY["__product_name__"],
        "description": EXPECTED_SOURCE_IDENTITY["__description__"],
        "sector_version": EXPECTED_SOURCE_IDENTITY["__version__"],
        "author": EXPECTED_SOURCE_IDENTITY["__author__"],
        "licensee": EXPECTED_SOURCE_IDENTITY["__licensee__"],
        "copyright": EXPECTED_SOURCE_IDENTITY["__copyright__"],
        "built_at_utc": source["source_committed_at_utc"],
        **source,
    }


def _is_reparse(status: os.stat_result) -> bool:
    attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(status, "st_file_attributes", 0) & attribute)


def _regular_tree(
    root: Path, *, boundary: Path | None = None
) -> dict[str, Path]:
    root = Path(os.path.abspath(root))
    boundary = root if boundary is None else Path(os.path.abspath(boundary))
    try:
        relative_root = root.relative_to(boundary)
    except ValueError as exc:
        raise ReleaseVerificationError(
            "package source tree escapes the package boundary"
        ) from exc
    ancestors = [boundary]
    for component in relative_root.parts:
        ancestors.append(ancestors[-1] / component)
    for ancestor in ancestors:
        try:
            status = os.stat(ancestor, follow_symlinks=False)
        except OSError as exc:
            raise ReleaseVerificationError(
                f"package source tree is missing: {ancestor.name}"
            ) from exc
        if stat.S_ISLNK(status.st_mode) or _is_reparse(status):
            raise ReleaseVerificationError(
                f"package source contains a link or reparse point: {ancestor}"
            )
        if not stat.S_ISDIR(status.st_mode):
            raise ReleaseVerificationError(
                f"package source ancestor is not a directory: {ancestor}"
            )
    pending: list[tuple[Path, tuple[str, ...]]] = [(root, ())]
    files: dict[str, Path] = {}
    normalized_paths: set[str] = set()
    while pending:
        directory, parts = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            raise ReleaseVerificationError(
                f"cannot inspect package source tree: {directory}"
            ) from exc
        for entry in entries:
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
                    f"package source contains a link or reparse point: {relative}"
                )
            if stat.S_ISDIR(status.st_mode):
                pending.append((Path(entry.path), child))
            elif stat.S_ISREG(status.st_mode):
                key = unicodedata.normalize("NFC", relative).casefold()
                if key in normalized_paths:
                    raise ReleaseVerificationError(
                        f"package source contains colliding paths: {relative}"
                    )
                normalized_paths.add(key)
                files[relative] = Path(entry.path)
            else:
                raise ReleaseVerificationError(
                    f"package source contains a nonregular entry: {relative}"
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
            try:
                payload = actual[relative].read_bytes()
            except OSError as exc:
                raise ReleaseVerificationError(
                    f"cannot read packaged source file: {source_prefix}/{relative}"
                ) from exc
            if payload != item.payload:
                raise ReleaseVerificationError(
                    f"packaged source differs from raw commit: {source_prefix}/{relative}"
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
    snapshot = _snapshot(repository, source_revision)
    _validate_product_identity(snapshot)
    _authenticate_evidence(source_identity_path, snapshot)

    required = {
        "executable": package / "Sector.exe",
        "manifest": package / "_internal" / "sector" / "sector_build_info.json",
        "license": package / "LICENSE.txt",
        "notices": package / "THIRD_PARTY_NOTICES.txt",
    }
    missing = [label for label, path in required.items() if not path.is_file()]
    if missing:
        raise ReleaseVerificationError(
            f"package is missing required files: {', '.join(sorted(missing))}"
        )
    if required["executable"].stat().st_size <= 0:
        raise ReleaseVerificationError("Sector.exe is empty")

    files = _snapshot_files(snapshot)
    try:
        expected_license = files["LICENSE"].payload
        packaged_license = required["license"].read_bytes()
    except (KeyError, OSError) as exc:
        raise ReleaseVerificationError("cannot authenticate packaged license") from exc
    if packaged_license != expected_license:
        raise ReleaseVerificationError("packaged license differs from raw source commit")

    try:
        notices = required["notices"].read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ReleaseVerificationError("cannot read third-party notices") from exc
    for token in ("SECTOR THIRD-PARTY NOTICES", "numpy", "streamlit"):
        if token.casefold() not in notices.casefold():
            raise ReleaseVerificationError(
                f"third-party notice bundle is missing {token}"
            )

    manifest, raw_manifest = _read_json_object(
        required["manifest"], "package manifest"
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
    root = args.root.resolve()
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
            args.source_identity.resolve(),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
