"""Build and verify a provenance-bearing source/application release ZIP."""

from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import importlib.util
import itertools
import json
import os
import re
import stat
import struct
import sys
import tempfile
import unicodedata
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, BinaryIO, cast

if TYPE_CHECKING:
    from tools.export_commit_tree import (
        CommitSnapshot,
        ExportEvidence,
        SnapshotFile,
    )


def _load_exporter() -> Any:
    path = Path(__file__).resolve().with_name("export_commit_tree.py")
    specification = importlib.util.spec_from_file_location(
        "sector_source_release_commit_exporter", path
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


_EXPORTER = _load_exporter()
CommitTreeError = _EXPORTER.CommitTreeError
if not TYPE_CHECKING:
    CommitSnapshot = _EXPORTER.CommitSnapshot
    ExportEvidence = _EXPORTER.ExportEvidence
    SnapshotFile = _EXPORTER.SnapshotFile
snapshot_commit = cast(
    "Callable[[Path, str], CommitSnapshot]", _EXPORTER.snapshot_commit
)

_MANIFEST_PATH = PurePosixPath("sector/sector_build_info.json")
_MANIFEST_SCHEMA = 2
_VERSION = re.compile(r"^[0-9]+\.[0-9]+$")
_OBJECT_ID = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BINARY_SUFFIXES = (".dll", ".exe", ".msi", ".msix")
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
_IDENTITY_NAMES = {
    "__version__",
    "__product_name__",
    "__description__",
    "__author__",
    "__licensee__",
    "__copyright__",
}

MAX_SOURCE_FILES = 50_000
MAX_SOURCE_DIRECTORIES = 50_000
MAX_SOURCE_FILE_BYTES = 256 * 1024 * 1024
MAX_SOURCE_TOTAL_BYTES = 512 * 1024 * 1024
MAX_SOURCE_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_SOURCE_COMMIT_BYTES = 1 * 1024 * 1024
MAX_SOURCE_ARCHIVE_MEMBERS = MAX_SOURCE_FILES + 1
MAX_SOURCE_ARCHIVE_MEMBER_BYTES = MAX_SOURCE_FILE_BYTES
MAX_SOURCE_ARCHIVE_EXPANDED_BYTES = (
    MAX_SOURCE_TOTAL_BYTES + MAX_SOURCE_MANIFEST_BYTES
)
MAX_SOURCE_ARCHIVE_BYTES = 600 * 1024 * 1024
MAX_SECTOR_VERSION_BYTES = 11
MAX_SECTOR_VERSION_COMPONENT = 65_535
MAX_SOURCE_ARCHIVE_NAME_BYTES = 65_535
_READ_BLOCK_BYTES = 1024 * 1024
_ZIP_LOCAL_HEADER_BYTES = 30
_ZIP_CENTRAL_HEADER_BYTES = 46
_ZIP_END_BYTES = 22


class SourceReleaseError(ValueError):
    """Raised when a source release archive is incomplete or unverifiable."""


@dataclass(frozen=True)
class SourceReleaseEvidence:
    source_revision: str
    source_tree: str
    sector_version: str
    source_file_count: int
    source_total_bytes: int
    source_inventory_sha256: str
    archive_entries: int
    archive_bytes: int
    archive_sha256: str


def _snapshot(repository: Path, source_revision: str) -> CommitSnapshot:
    try:
        snapshot = snapshot_commit(repository, source_revision)
    except CommitTreeError as exc:
        raise SourceReleaseError(
            f"cannot authenticate exact source commit: {exc}"
        ) from exc
    _validate_snapshot_bounds(snapshot)
    return snapshot


def _validate_snapshot_bounds(snapshot: CommitSnapshot) -> None:
    files = snapshot.files
    evidence = snapshot.evidence
    if len(files) > MAX_SOURCE_FILES:
        raise SourceReleaseError("source snapshot exceeds the file-count limit")
    total = 0
    for item in files:
        size = len(item.payload)
        if size > MAX_SOURCE_FILE_BYTES:
            raise SourceReleaseError(
                f"source snapshot file exceeds the byte limit: {item.path}"
            )
        total += size
        if total > MAX_SOURCE_TOTAL_BYTES:
            raise SourceReleaseError("source snapshot exceeds the total-byte limit")
    if evidence.file_count != len(files) or evidence.total_bytes != total:
        raise SourceReleaseError("source snapshot resource evidence differs")
    if len(snapshot.commit_payload) > MAX_SOURCE_COMMIT_BYTES:
        raise SourceReleaseError("source commit object exceeds the byte limit")


def _snapshot_file(snapshot: CommitSnapshot, path: str) -> bytes:
    matches = [item.payload for item in snapshot.files if item.path == path]
    if len(matches) != 1:
        raise SourceReleaseError(f"exact source file is missing or duplicated: {path}")
    return cast(bytes, matches[0])


def _validate_sector_version(version: str) -> None:
    try:
        encoded = version.encode("ascii")
    except UnicodeEncodeError as exc:
        raise SourceReleaseError("Sector version is not ASCII") from exc
    if len(encoded) > MAX_SECTOR_VERSION_BYTES or _VERSION.fullmatch(version) is None:
        raise SourceReleaseError("Sector version format or length is invalid")
    if any(
        int(component) > MAX_SECTOR_VERSION_COMPONENT
        for component in version.split(".")
    ):
        raise SourceReleaseError("Sector version component exceeds the limit")


def _source_identity(snapshot: CommitSnapshot) -> dict[str, str]:
    try:
        source = _snapshot_file(snapshot, "sector/__init__.py").decode("utf-8")
        tree = ast.parse(source, filename="sector/__init__.py")
    except (UnicodeDecodeError, SyntaxError) as exc:
        raise SourceReleaseError("Sector source identity cannot be parsed") from exc
    values: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in _IDENTITY_NAMES:
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, TypeError) as exc:
            raise SourceReleaseError("Sector source identity must be literal") from exc
        if not isinstance(value, str) or not value:
            raise SourceReleaseError("Sector source identity must be non-empty text")
        values[target.id] = value
    if set(values) != _IDENTITY_NAMES:
        raise SourceReleaseError("Sector source identity is incomplete or invalid")
    _validate_sector_version(values["__version__"])
    return values


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("ascii")


def _manifest(
    snapshot: CommitSnapshot, identity: dict[str, str]
) -> dict[str, object]:
    evidence = snapshot.evidence
    value: dict[str, object] = {
        "source_release_schema": _MANIFEST_SCHEMA,
        "product_name": identity["__product_name__"],
        "description": identity["__description__"],
        "sector_version": identity["__version__"],
        "author": identity["__author__"],
        "licensee": identity["__licensee__"],
        "copyright": identity["__copyright__"],
        "built_at_utc": evidence.source_committed_at_utc,
        "source_revision": evidence.source_revision,
        "source_tree": evidence.source_tree,
        "source_committer_epoch": evidence.source_committer_epoch,
        "source_committed_at_utc": evidence.source_committed_at_utc,
        "source_file_count": evidence.file_count,
        "source_total_bytes": evidence.total_bytes,
        "source_inventory_sha256": evidence.inventory_sha256,
        "source_commit_payload_base64": base64.b64encode(
            snapshot.commit_payload
        ).decode("ascii"),
        "source_files": [
            {
                "path": item.path,
                "mode": item.mode,
                "object_id": item.object_id,
                "bytes": len(item.payload),
            }
            for item in snapshot.files
        ],
    }
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SourceReleaseError(f"source manifest contains duplicate key: {key}")
        result[key] = value
    return result


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


def _nonfollowing_status(path: Path, label: str) -> os.stat_result:
    try:
        return os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise SourceReleaseError(f"cannot inspect {label}") from exc


def _require_regular_directory(path: Path, label: str) -> os.stat_result:
    status = _nonfollowing_status(path, label)
    if stat.S_ISLNK(status.st_mode) or _is_reparse(status):
        raise SourceReleaseError(f"{label} is a linked or reparse path")
    if not stat.S_ISDIR(status.st_mode):
        raise SourceReleaseError(f"{label} is not a regular directory")
    return status


def _read_regular_file(
    path: Path,
    label: str,
    *,
    limit: int,
    expected_size: int | None = None,
) -> bytes:
    before = _nonfollowing_status(path, label)
    if stat.S_ISLNK(before.st_mode) or _is_reparse(before):
        raise SourceReleaseError(f"{label} is a linked or reparse path")
    if not stat.S_ISREG(before.st_mode):
        raise SourceReleaseError(f"{label} is not a regular file")
    if before.st_size > limit:
        raise SourceReleaseError(f"{label} exceeds the byte limit")
    if expected_size is not None and before.st_size != expected_size:
        raise SourceReleaseError(f"{label} byte count differs from its manifest")
    chunks: list[bytes] = []
    count = 0
    try:
        with path.open("rb") as stream:
            opened_before = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(opened_before.st_mode)
                or _status_signature(opened_before) != _status_signature(before)
            ):
                raise SourceReleaseError(f"{label} changed while it was opened")
            while True:
                block = stream.read(_READ_BLOCK_BYTES)
                if not block:
                    break
                count += len(block)
                if count > limit:
                    raise SourceReleaseError(f"{label} exceeds the byte limit")
                chunks.append(block)
            opened_after = os.fstat(stream.fileno())
        after = _nonfollowing_status(path, label)
    except SourceReleaseError:
        raise
    except OSError as exc:
        raise SourceReleaseError(f"cannot read {label}") from exc
    signatures = (before, opened_before, opened_after, after)
    if any(
        _status_signature(first) != _status_signature(second)
        for first, second in itertools.pairwise(signatures)
    ):
        raise SourceReleaseError(f"{label} changed while it was read")
    payload = b"".join(chunks)
    if count != before.st_size or (
        expected_size is not None and count != expected_size
    ):
        raise SourceReleaseError(f"{label} byte count changed while it was read")
    return payload


def _require_regular_file_bytes(path: Path, label: str, expected: bytes) -> None:
    before = _nonfollowing_status(path, label)
    if stat.S_ISLNK(before.st_mode) or _is_reparse(before):
        raise SourceReleaseError(f"{label} is a linked or reparse path")
    if not stat.S_ISREG(before.st_mode):
        raise SourceReleaseError(f"{label} is not a regular file")
    if before.st_size != len(expected) or before.st_size > MAX_SOURCE_FILE_BYTES:
        raise SourceReleaseError(f"{label} byte count differs from its manifest")
    expected_view = memoryview(expected)
    count = 0
    try:
        with path.open("rb") as stream:
            opened_before = os.fstat(stream.fileno())
            if _status_signature(opened_before) != _status_signature(before):
                raise SourceReleaseError(f"{label} changed while it was opened")
            while True:
                block = stream.read(_READ_BLOCK_BYTES)
                if not block:
                    break
                end = count + len(block)
                if end > len(expected) or memoryview(block) != expected_view[count:end]:
                    raise SourceReleaseError(f"{label} bytes changed")
                count = end
            opened_after = os.fstat(stream.fileno())
        after = _nonfollowing_status(path, label)
    except SourceReleaseError:
        raise
    except OSError as exc:
        raise SourceReleaseError(f"cannot read {label}") from exc
    signatures = (before, opened_before, opened_after, after)
    if any(
        _status_signature(first) != _status_signature(second)
        for first, second in itertools.pairwise(signatures)
    ):
        raise SourceReleaseError(f"{label} changed while it was read")
    if count != len(expected):
        raise SourceReleaseError(f"{label} byte count changed while it was read")


def _read_manifest(root: Path) -> tuple[dict[str, object], bytes]:
    path = root.joinpath(*_MANIFEST_PATH.parts)
    try:
        raw = _read_regular_file(
            path,
            "source release provenance manifest",
            limit=MAX_SOURCE_MANIFEST_BYTES,
        )
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_unique_object)
    except SourceReleaseError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceReleaseError("source release provenance manifest is invalid") from exc
    if not isinstance(value, dict):
        raise SourceReleaseError("source release provenance manifest must be an object")
    expected = {
        "source_release_schema",
        "product_name",
        "description",
        "sector_version",
        "author",
        "licensee",
        "copyright",
        "built_at_utc",
        "source_revision",
        "source_tree",
        "source_committer_epoch",
        "source_committed_at_utc",
        "source_file_count",
        "source_total_bytes",
        "source_inventory_sha256",
        "source_commit_payload_base64",
        "source_files",
    }
    if set(value) != expected:
        raise SourceReleaseError("source release provenance manifest schema differs")
    if value["source_release_schema"] != _MANIFEST_SCHEMA:
        raise SourceReleaseError("source release provenance manifest schema is unsupported")
    return value, raw


def _manifest_text(value: dict[str, object], name: str) -> str:
    candidate = value[name]
    if not isinstance(candidate, str) or not candidate:
        raise SourceReleaseError(f"source manifest field is invalid: {name}")
    return candidate


def _manifest_integer(value: dict[str, object], name: str) -> int:
    candidate = value[name]
    if type(candidate) is not int or candidate < 0:
        raise SourceReleaseError(f"source manifest field is invalid: {name}")
    return candidate


def _source_records(
    value: dict[str, object], *, declared_count: int, declared_total: int
) -> list[dict[str, object]]:
    raw_records = value["source_files"]
    if not isinstance(raw_records, list) or not raw_records:
        raise SourceReleaseError("source manifest file inventory is invalid")
    if declared_count > MAX_SOURCE_FILES:
        raise SourceReleaseError("source manifest exceeds the file-count limit")
    if declared_total > MAX_SOURCE_TOTAL_BYTES:
        raise SourceReleaseError("source manifest exceeds the total-byte limit")
    if len(raw_records) != declared_count:
        raise SourceReleaseError("source manifest file count differs")
    records: list[dict[str, object]] = []
    path_kinds: dict[str, str] = {}
    prior_path: str | None = None
    total = 0
    for raw in raw_records:
        if not isinstance(raw, dict) or set(raw) != {"path", "mode", "object_id", "bytes"}:
            raise SourceReleaseError("source manifest file record is invalid")
        path = raw["path"]
        mode = raw["mode"]
        object_id = raw["object_id"]
        size = raw["bytes"]
        if not isinstance(path, str) or not path or PurePosixPath(path).as_posix() != path:
            raise SourceReleaseError("source manifest path is invalid")
        if path == _MANIFEST_PATH.as_posix():
            raise SourceReleaseError("source manifest cannot inventory itself")
        parts = PurePosixPath(path).parts
        try:
            for part in parts:
                if _EXPORTER._validate_component(part.encode("utf-8")) != part:
                    raise SourceReleaseError("source manifest path is noncanonical")
        except (UnicodeEncodeError, CommitTreeError) as exc:
            raise SourceReleaseError(f"source manifest path is unsafe: {path}") from exc
        if mode not in {"100644", "100755"}:
            raise SourceReleaseError(f"source manifest mode is invalid: {path}")
        if not isinstance(object_id, str) or _OBJECT_ID.fullmatch(object_id) is None:
            raise SourceReleaseError(f"source manifest object identity is invalid: {path}")
        if type(size) is not int or size < 0:
            raise SourceReleaseError(f"source manifest byte count is invalid: {path}")
        if size > MAX_SOURCE_FILE_BYTES:
            raise SourceReleaseError(
                f"source manifest file exceeds the byte limit: {path}"
            )
        total += size
        if total > MAX_SOURCE_TOTAL_BYTES:
            raise SourceReleaseError("source manifest exceeds the total-byte limit")
        if prior_path is not None and path <= prior_path:
            raise SourceReleaseError("source manifest file inventory is not canonical")
        prior_path = path
        for index in range(1, len(parts) + 1):
            prefix = PurePosixPath(*parts[:index]).as_posix()
            kind = "file" if index == len(parts) else "directory"
            key = unicodedata.normalize("NFC", prefix).casefold()
            previous = path_kinds.get(key)
            if previous is not None and previous != kind:
                raise SourceReleaseError("source manifest has colliding file and directory paths")
            if previous == kind and kind == "file":
                raise SourceReleaseError("source manifest has colliding file paths")
            path_kinds[key] = kind
        records.append(raw)
    if total != declared_total:
        raise SourceReleaseError("source manifest total byte count differs")
    return records


def _tree_identity(records: list[dict[str, object]]) -> str:
    root: dict[str, tuple[str, object]] = {}
    for record in records:
        parts = PurePosixPath(str(record["path"])).parts
        node = root
        for part in parts[:-1]:
            child = node.get(part)
            if child is None:
                directory: dict[str, tuple[str, object]] = {}
                node[part] = ("directory", directory)
                node = directory
                continue
            kind, value = child
            if kind != "directory" or not isinstance(value, dict):
                raise SourceReleaseError("source manifest tree structure is invalid")
            node = value
        if parts[-1] in node:
            raise SourceReleaseError("source manifest tree contains a duplicate entry")
        node[parts[-1]] = ("file", record)

    def digest(node: dict[str, tuple[str, object]]) -> str:
        entries: list[tuple[bytes, bytes]] = []
        for name, (kind, value) in node.items():
            raw_name = name.encode("utf-8")
            if kind == "directory" and isinstance(value, dict):
                mode = b"40000"
                object_id = digest(value)
                order = raw_name + b"/"
            else:
                if kind != "file" or not isinstance(value, dict):
                    raise SourceReleaseError("source manifest tree entry is invalid")
                mode = str(value["mode"]).encode("ascii")
                object_id = str(value["object_id"])
                order = raw_name + b"\0"
            entry = mode + b" " + raw_name + b"\0" + bytes.fromhex(object_id)
            entries.append((order, entry))
        payload = b"".join(entry for _order, entry in sorted(entries))
        return str(_EXPORTER._object_digest("tree", payload))

    return digest(root)


def _source_paths(root: Path) -> tuple[dict[str, Path], set[str]]:
    files: dict[str, Path] = {}
    directories: set[str] = set()
    pending: list[tuple[Path, tuple[str, ...]]] = [(root, ())]
    while pending:
        directory, parts = pending.pop()
        before = _require_regular_directory(directory, "source release directory")
        try:
            iterator = os.scandir(directory)
            entries: list[os.DirEntry[str]] = []
            try:
                for entry in iterator:
                    if (
                        len(files) + len(directories) + len(entries)
                        >= MAX_SOURCE_FILES + MAX_SOURCE_DIRECTORIES + 1
                    ):
                        raise SourceReleaseError(
                            "source release exceeds the path-count limit"
                        )
                    entries.append(entry)
            finally:
                close = getattr(iterator, "close", None)
                if close is not None:
                    close()
        except SourceReleaseError:
            raise
        except OSError as exc:
            raise SourceReleaseError(f"cannot inventory source release directory: {exc}") from exc
        after = _require_regular_directory(directory, "source release directory")
        if _status_signature(before) != _status_signature(after):
            raise SourceReleaseError("source release directory changed during inventory")
        for entry in entries:
            child_parts = (*parts, entry.name)
            relative = PurePosixPath(*child_parts).as_posix()
            path = Path(entry.path)
            try:
                status = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise SourceReleaseError(
                    f"cannot inspect source release path: {relative}"
                ) from exc
            if stat.S_ISLNK(status.st_mode) or _is_reparse(status):
                raise SourceReleaseError(
                    f"source release contains a linked or reparse path: {relative}"
                )
            if stat.S_ISDIR(status.st_mode):
                if len(directories) >= MAX_SOURCE_DIRECTORIES:
                    raise SourceReleaseError(
                        "source release exceeds the directory-count limit"
                    )
                directories.add(relative)
                pending.append((path, child_parts))
            elif stat.S_ISREG(status.st_mode):
                if len(files) >= MAX_SOURCE_FILES + 1:
                    raise SourceReleaseError(
                        "source release exceeds the file-count limit"
                    )
                files[relative] = path
            else:
                raise SourceReleaseError(f"source release contains a special path: {relative}")
    return files, directories


def verify_source_release_directory(
    root: Path, expected_revision: str | None = None
) -> CommitSnapshot:
    """Authenticate one extracted source release without requiring Git metadata."""
    lexical_root = Path(os.path.abspath(root))
    _require_regular_directory(lexical_root, "source release root")
    try:
        root = lexical_root.resolve(strict=True)
    except OSError as exc:
        raise SourceReleaseError("source release directory does not exist") from exc
    _require_regular_directory(root, "source release root")
    manifest, raw_manifest = _read_manifest(root)
    revision = _manifest_text(manifest, "source_revision")
    tree = _manifest_text(manifest, "source_tree")
    inventory = _manifest_text(manifest, "source_inventory_sha256")
    if _OBJECT_ID.fullmatch(revision) is None or _OBJECT_ID.fullmatch(tree) is None:
        raise SourceReleaseError("source manifest commit identity is invalid")
    if _SHA256.fullmatch(inventory) is None:
        raise SourceReleaseError("source manifest inventory identity is invalid")
    if expected_revision is not None and revision != expected_revision:
        raise SourceReleaseError("source manifest revision differs from the requested revision")
    declared_count = _manifest_integer(manifest, "source_file_count")
    declared_total = _manifest_integer(manifest, "source_total_bytes")
    if declared_count > MAX_SOURCE_FILES:
        raise SourceReleaseError("source manifest exceeds the file-count limit")
    if declared_total > MAX_SOURCE_TOTAL_BYTES:
        raise SourceReleaseError("source manifest exceeds the total-byte limit")
    encoded_commit = _manifest_text(manifest, "source_commit_payload_base64")
    if len(encoded_commit) > ((MAX_SOURCE_COMMIT_BYTES + 2) // 3) * 4:
        raise SourceReleaseError("source manifest commit object exceeds the byte limit")
    try:
        commit_payload = base64.b64decode(
            encoded_commit, validate=True
        )
        parsed_commit = _EXPORTER._parse_commit(commit_payload)
    except (ValueError, CommitTreeError) as exc:
        raise SourceReleaseError("source manifest commit object is invalid") from exc
    if len(commit_payload) > MAX_SOURCE_COMMIT_BYTES:
        raise SourceReleaseError("source manifest commit object exceeds the byte limit")
    if _EXPORTER._object_digest("commit", commit_payload) != revision:
        raise SourceReleaseError("source manifest commit object does not match its revision")
    epoch = _manifest_integer(manifest, "source_committer_epoch")
    committed_at = _manifest_text(manifest, "source_committed_at_utc")
    if (
        parsed_commit.tree_id != tree
        or parsed_commit.committer_epoch != epoch
        or parsed_commit.committed_at_utc != committed_at
        or _manifest_text(manifest, "built_at_utc") != committed_at
    ):
        raise SourceReleaseError("source manifest commit metadata differs")

    records = _source_records(
        manifest,
        declared_count=declared_count,
        declared_total=declared_total,
    )
    if _tree_identity(records) != tree:
        raise SourceReleaseError("source manifest file inventory does not match its Git tree")
    digest = hashlib.sha256()
    for item in records:
        record = [item["path"], item["mode"], item["object_id"], item["bytes"]]
        digest.update(
            json.dumps(record, ensure_ascii=True, separators=(",", ":")).encode("ascii")
        )
        digest.update(b"\n")
    if digest.hexdigest() != inventory:
        raise SourceReleaseError("source manifest inventory digest differs")

    actual_files, actual_directories = _source_paths(root)
    expected_files = {str(item["path"]) for item in records}
    expected_files.add(_MANIFEST_PATH.as_posix())
    expected_directories = {
        PurePosixPath(*PurePosixPath(path).parts[:index]).as_posix()
        for path in expected_files
        for index in range(1, len(PurePosixPath(path).parts))
    }
    if set(actual_files) != expected_files or actual_directories != expected_directories:
        raise SourceReleaseError("source release directory inventory differs from its manifest")

    snapshot_files: list[SnapshotFile] = []
    for item in records:
        path = str(item["path"])
        payload = _read_regular_file(
            actual_files[path],
            f"source release file: {path}",
            limit=MAX_SOURCE_FILE_BYTES,
            expected_size=cast(int, item["bytes"]),
        )
        if len(payload) != item["bytes"] or _EXPORTER._object_digest("blob", payload) != item["object_id"]:
            raise SourceReleaseError(f"source release file differs from its manifest: {path}")
        snapshot_files.append(
            SnapshotFile(str(item["mode"]), path, str(item["object_id"]), payload)
        )
    snapshot = CommitSnapshot(
        ExportEvidence(
            revision,
            tree,
            epoch,
            committed_at,
            len(records),
            declared_total,
            inventory,
        ),
        commit_payload,
        tuple(snapshot_files),
    )
    identity = _source_identity(snapshot)
    expected_manifest = _manifest(snapshot, identity)
    parsed_identity = {
        "product_name": manifest["product_name"],
        "description": manifest["description"],
        "sector_version": manifest["sector_version"],
        "author": manifest["author"],
        "licensee": manifest["licensee"],
        "copyright": manifest["copyright"],
    }
    expected_identity = {
        "product_name": identity["__product_name__"],
        "description": identity["__description__"],
        "sector_version": identity["__version__"],
        "author": identity["__author__"],
        "licensee": identity["__licensee__"],
        "copyright": identity["__copyright__"],
    }
    if parsed_identity != expected_identity or manifest != expected_manifest:
        raise SourceReleaseError(
            "source manifest identity differs from the authenticated source"
        )
    if raw_manifest != _canonical_json(expected_manifest):
        raise SourceReleaseError("source release provenance manifest is not canonical")
    final_files, final_directories = _source_paths(root)
    if set(final_files) != set(actual_files) or final_directories != actual_directories:
        raise SourceReleaseError("source release directory changed during authentication")
    final_manifest, final_raw_manifest = _read_manifest(root)
    if final_manifest != manifest or final_raw_manifest != raw_manifest:
        raise SourceReleaseError("source release manifest changed during authentication")
    for snapshot_file in snapshot_files:
        _require_regular_file_bytes(
            final_files[snapshot_file.path],
            f"source release file: {snapshot_file.path}",
            snapshot_file.payload,
        )
    _validate_snapshot_bounds(snapshot)
    return snapshot


def materialize_source_release(
    root: Path, expected_revision: str, output: Path
) -> ExportEvidence:
    """Verify and copy an extracted release into one new isolated source tree."""
    if os.path.lexists(output):
        raise SourceReleaseError(f"source materialization output already exists: {output}")
    lexical_root = Path(os.path.abspath(root))
    _require_regular_directory(lexical_root, "source release root")
    resolved_root = lexical_root.resolve(strict=True)
    lexical_output = Path(os.path.abspath(output))
    if lexical_output == resolved_root or resolved_root in lexical_output.parents:
        raise SourceReleaseError("source materialization output cannot be inside the release")
    snapshot = verify_source_release_directory(lexical_root, expected_revision)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.mkdir()
        for item in snapshot.files:
            target = output.joinpath(*PurePosixPath(item.path).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(item.payload)
            os.chmod(target, 0o755 if item.mode == "100755" else 0o644)
    except OSError as exc:
        raise SourceReleaseError(f"cannot materialize verified source release: {exc}") from exc
    return snapshot.evidence


def _archive_entries(
    snapshot: CommitSnapshot,
) -> tuple[str, list[tuple[str, str, bytes]]]:
    _validate_snapshot_bounds(snapshot)
    identity = _source_identity(snapshot)
    prefix = f"Sector-v{identity['__version__']}"
    if any(
        item.path.casefold().endswith(_BINARY_SUFFIXES) for item in snapshot.files
    ):
        raise SourceReleaseError("source release commit contains a Windows binary")
    if any(PurePosixPath(item.path) == _MANIFEST_PATH for item in snapshot.files):
        raise SourceReleaseError("generated source-release manifest path is tracked")
    manifest = _canonical_json(_manifest(snapshot, identity))
    if len(manifest) > MAX_SOURCE_MANIFEST_BYTES:
        raise SourceReleaseError("source release manifest exceeds the byte limit")
    relative_entries = [
        (item.path, item.mode, item.payload) for item in snapshot.files
    ]
    relative_entries.append((_MANIFEST_PATH.as_posix(), "100644", manifest))
    _preflight_relative_archive_layout(prefix, relative_entries)
    entries = [
        (f"{prefix}/{relative}", mode, payload)
        for relative, mode, payload in relative_entries
    ]
    entries.sort(key=lambda item: item[0])
    _validate_archive_entry_bounds(entries)
    return prefix, entries


def _zip_info(name: str, mode: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=_ZIP_TIME)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = (0o100755 if mode == "100755" else 0o100644) << 16
    return info


def _zip_name_bytes(name: str) -> bytes:
    try:
        raw = name.encode("ascii")
    except UnicodeEncodeError:
        raw = name.encode("utf-8")
    if not raw or len(raw) > MAX_SOURCE_ARCHIVE_NAME_BYTES:
        raise SourceReleaseError("source archive member name exceeds the byte limit")
    return raw


def _checked_archive_size(current: int, name_bytes: int, payload_bytes: int) -> int:
    size = (
        current
        + _ZIP_LOCAL_HEADER_BYTES
        + name_bytes
        + payload_bytes
        + _ZIP_CENTRAL_HEADER_BYTES
        + name_bytes
    )
    if size > MAX_SOURCE_ARCHIVE_BYTES:
        raise SourceReleaseError("source archive exceeds the final-byte limit")
    return size


def _preflight_relative_archive_layout(
    prefix: str, entries: list[tuple[str, str, bytes]]
) -> int:
    prefix_bytes = _zip_name_bytes(prefix)
    size = _ZIP_END_BYTES
    for relative, _mode, payload in entries:
        relative_bytes = _zip_name_bytes(relative)
        name_bytes = len(prefix_bytes) + 1 + len(relative_bytes)
        if name_bytes > MAX_SOURCE_ARCHIVE_NAME_BYTES:
            raise SourceReleaseError(
                "source archive member name exceeds the byte limit"
            )
        size = _checked_archive_size(size, name_bytes, len(payload))
    return size


def _validate_archive_entry_bounds(
    entries: list[tuple[str, str, bytes]],
) -> int:
    if not entries or len(entries) > MAX_SOURCE_ARCHIVE_MEMBERS:
        raise SourceReleaseError("source archive exceeds the member-count limit")
    prior_name: str | None = None
    total = 0
    final_size = _ZIP_END_BYTES
    for name, _mode, payload in entries:
        if prior_name is not None and name <= prior_name:
            raise SourceReleaseError(
                "source archive member inventory is not canonical"
            )
        prior_name = name
        size = len(payload)
        if size > MAX_SOURCE_ARCHIVE_MEMBER_BYTES:
            raise SourceReleaseError(
                f"source archive member exceeds the byte limit: {name}"
            )
        total += size
        if total > MAX_SOURCE_ARCHIVE_EXPANDED_BYTES:
            raise SourceReleaseError("source archive exceeds the expanded-byte limit")
        final_size = _checked_archive_size(
            final_size, len(_zip_name_bytes(name)), size
        )
    return final_size


def _write_canonical_archive(
    stream: BinaryIO, entries: list[tuple[str, str, bytes]]
) -> int:
    expected_size = _validate_archive_entry_bounds(entries)
    with zipfile.ZipFile(
        stream,
        "w",
        compression=zipfile.ZIP_STORED,
        allowZip64=False,
    ) as bundle:
        for name, mode, payload in entries:
            bundle.writestr(_zip_info(name, mode), payload)
    stream.flush()
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    if size != expected_size:
        raise SourceReleaseError("source archive final byte count is noncanonical")
    return int(size)


def _preflight_archive_stream(stream: BinaryIO, size: int) -> int:
    if size < 22 or size > MAX_SOURCE_ARCHIVE_BYTES:
        raise SourceReleaseError("source archive final byte count is invalid")
    stream.seek(size - 22)
    footer = stream.read(22)
    if len(footer) != 22 or footer[:4] != b"PK\x05\x06":
        raise SourceReleaseError(
            "complete source archive bytes differ from the canonical release"
        )
    (
        _signature,
        disk,
        central_disk,
        disk_entries,
        total_entries,
        central_size,
        central_offset,
        comment_length,
    ) = struct.unpack("<4s4H2LH", footer)
    if total_entries > MAX_SOURCE_ARCHIVE_MEMBERS:
        raise SourceReleaseError("source archive exceeds the member-count limit")
    if (
        disk != 0
        or central_disk != 0
        or disk_entries != total_entries
        or total_entries < 1
        or central_size == 0xFFFFFFFF
        or central_offset == 0xFFFFFFFF
        or comment_length != 0
        or central_offset + central_size != size - 22
    ):
        raise SourceReleaseError(
            "complete source archive bytes differ from the canonical release"
        )
    return int(total_entries)


def _validate_archive_infos(
    infos: list[zipfile.ZipInfo],
    expected_by_name: dict[str, tuple[str, bytes]],
) -> None:
    if not infos or len(infos) > MAX_SOURCE_ARCHIVE_MEMBERS:
        raise SourceReleaseError("source archive exceeds the member-count limit")
    expanded = 0
    for info in infos:
        if info.file_size > MAX_SOURCE_ARCHIVE_MEMBER_BYTES:
            raise SourceReleaseError(
                f"source archive member exceeds the byte limit: {info.filename}"
            )
        expanded += info.file_size
        if expanded > MAX_SOURCE_ARCHIVE_EXPANDED_BYTES:
            raise SourceReleaseError("source archive exceeds the expanded-byte limit")

    names = [item.filename for item in infos]
    if names != list(expected_by_name):
        raise SourceReleaseError(
            "complete source archive bytes differ from the canonical release"
        )
    if len(names) != len(set(names)):
        raise SourceReleaseError("source archive contains duplicate entries")
    for info in infos:
        mode, payload = expected_by_name[info.filename]
        expected_mode = 0o100755 if mode == "100755" else 0o100644
        actual_mode = (info.external_attr >> 16) & 0xFFFF
        if (
            info.is_dir()
            or info.compress_type != zipfile.ZIP_STORED
            or info.compress_size != info.file_size
            or info.file_size != len(payload)
            or info.date_time != _ZIP_TIME
            or info.create_system != 3
            or actual_mode != expected_mode
            or info.extra
            or info.comment
            or info.flag_bits & 0x1
        ):
            raise SourceReleaseError(
                f"source archive metadata differs: {info.filename}"
            )


def _require_archive_member_bytes(
    bundle: zipfile.ZipFile, info: zipfile.ZipInfo, expected: bytes
) -> None:
    expected_view = memoryview(expected)
    count = 0
    try:
        with bundle.open(info, "r") as member:
            while True:
                block = member.read(_READ_BLOCK_BYTES)
                if not block:
                    break
                end = count + len(block)
                if (
                    end > len(expected)
                    or end > MAX_SOURCE_ARCHIVE_MEMBER_BYTES
                    or memoryview(block) != expected_view[count:end]
                ):
                    raise SourceReleaseError(
                        f"source archive bytes differ: {info.filename}"
                    )
                count = end
    except SourceReleaseError:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise SourceReleaseError(
            f"cannot read source archive member: {info.filename}"
        ) from exc
    if count != info.file_size or count != len(expected):
        raise SourceReleaseError(f"source archive bytes differ: {info.filename}")


def _streams_equal(left: BinaryIO, right: BinaryIO) -> bool:
    left.seek(0)
    right.seek(0)
    total = 0
    while True:
        left_block = left.read(_READ_BLOCK_BYTES)
        right_block = right.read(_READ_BLOCK_BYTES)
        if left_block != right_block:
            return False
        if not left_block:
            return True
        total += len(left_block)
        if total > MAX_SOURCE_ARCHIVE_BYTES:
            raise SourceReleaseError("source archive exceeds the final-byte limit")


def _stream_sha256(stream: BinaryIO, expected_size: int) -> tuple[int, str]:
    digest = hashlib.sha256()
    count = 0
    stream.seek(0)
    while True:
        block = stream.read(_READ_BLOCK_BYTES)
        if not block:
            break
        count += len(block)
        if count > MAX_SOURCE_ARCHIVE_BYTES:
            raise SourceReleaseError("source archive exceeds the final-byte limit")
        digest.update(block)
    if count != expected_size:
        raise SourceReleaseError("source release archive byte count changed")
    return count, digest.hexdigest()


def _evidence(
    snapshot: CommitSnapshot,
    version: str,
    entries: int,
    archive_bytes: int,
    archive_sha256: str,
) -> SourceReleaseEvidence:
    source = snapshot.evidence
    return SourceReleaseEvidence(
        source_revision=source.source_revision,
        source_tree=source.source_tree,
        sector_version=version,
        source_file_count=source.file_count,
        source_total_bytes=source.total_bytes,
        source_inventory_sha256=source.inventory_sha256,
        archive_entries=entries,
        archive_bytes=archive_bytes,
        archive_sha256=archive_sha256,
    )


def verify_source_release(
    repository: Path,
    source_revision: str,
    archive: Path,
) -> SourceReleaseEvidence:
    """Verify one source ZIP against the authenticated raw commit tree."""
    snapshot = _snapshot(repository, source_revision)
    prefix, expected = _archive_entries(snapshot)
    expected_by_name = {name: (mode, payload) for name, mode, payload in expected}
    before = _nonfollowing_status(archive, "source release archive")
    if stat.S_ISLNK(before.st_mode) or _is_reparse(before):
        raise SourceReleaseError("source release archive is a linked or reparse path")
    if not stat.S_ISREG(before.st_mode):
        raise SourceReleaseError("source release archive is not a regular file")
    if before.st_size > MAX_SOURCE_ARCHIVE_BYTES:
        raise SourceReleaseError("source archive exceeds the final-byte limit")
    try:
        with archive.open("rb") as stream:
            opened_before = os.fstat(stream.fileno())
            if _status_signature(opened_before) != _status_signature(before):
                raise SourceReleaseError(
                    "source release archive changed while it was opened"
                )
            declared_members = _preflight_archive_stream(stream, before.st_size)
            stream.seek(0)
            with zipfile.ZipFile(stream, "r") as bundle:
                infos = bundle.infolist()
                if len(infos) != declared_members:
                    raise SourceReleaseError(
                        "source archive member count differs from its footer"
                    )
                if bundle.comment:
                    raise SourceReleaseError(
                        "source archive comment is not canonical"
                    )
                _validate_archive_infos(infos, expected_by_name)
                for info in infos:
                    _require_archive_member_bytes(
                        bundle, info, expected_by_name[info.filename][1]
                    )
            with tempfile.SpooledTemporaryFile(
                max_size=MAX_SOURCE_MANIFEST_BYTES,
                mode="w+b",
            ) as canonical:
                canonical_stream = cast(BinaryIO, canonical)
                canonical_size = _write_canonical_archive(
                    canonical_stream, expected
                )
                if (
                    canonical_size != before.st_size
                    or not _streams_equal(stream, canonical_stream)
                ):
                    raise SourceReleaseError(
                        "complete source archive bytes differ from the canonical release"
                    )
            archive_bytes, archive_sha256 = _stream_sha256(
                stream, before.st_size
            )
            opened_after = os.fstat(stream.fileno())
        after = _nonfollowing_status(archive, "source release archive")
    except SourceReleaseError:
        raise
    except (OSError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise SourceReleaseError(f"cannot read source release archive: {exc}") from exc
    signatures = (before, opened_before, opened_after, after)
    if any(
        _status_signature(first) != _status_signature(second)
        for first, second in itertools.pairwise(signatures)
    ):
        raise SourceReleaseError(
            "source release archive changed during authentication"
        )
    identity = _source_identity(snapshot)
    marker = f"{prefix}/{_MANIFEST_PATH.as_posix()}"
    if marker not in expected_by_name:
        raise SourceReleaseError("source release provenance manifest is missing")
    return _evidence(
        snapshot,
        identity["__version__"],
        len(expected),
        archive_bytes,
        archive_sha256,
    )


def build_source_release(
    repository: Path,
    source_revision: str,
    archive: Path,
) -> SourceReleaseEvidence:
    """Build and then independently verify one exact-commit source ZIP."""
    if archive.suffix.casefold() != ".zip":
        raise SourceReleaseError("source release output must use the .zip suffix")
    if os.path.lexists(archive):
        raise SourceReleaseError(f"source release output already exists: {archive}")
    snapshot = _snapshot(repository, source_revision)
    _prefix, entries = _archive_entries(snapshot)
    try:
        archive.parent.mkdir(parents=True, exist_ok=True)
        with archive.open("xb") as stream:
            _write_canonical_archive(stream, entries)
    except SourceReleaseError:
        raise
    except (OSError, ValueError, zipfile.LargeZipFile) as exc:
        raise SourceReleaseError(f"cannot write source release archive: {exc}") from exc
    return verify_source_release(repository, source_revision, archive)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--verify-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        action = verify_source_release if arguments.verify_only else build_source_release
        evidence = action(
            arguments.root.resolve(),
            arguments.source_revision,
            arguments.archive.resolve(),
        )
    except SourceReleaseError as exc:
        print(f"source release failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(evidence.__dict__, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
