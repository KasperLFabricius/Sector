"""Build and verify one complete unsigned portable Sector Windows distribution."""

from __future__ import annotations

import argparse
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
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import IO, Any, BinaryIO, cast

MAX_PORTABLE_FILES = 50_000
MAX_PORTABLE_DIRECTORIES = 50_000
MAX_PORTABLE_PATHS = MAX_PORTABLE_FILES + MAX_PORTABLE_DIRECTORIES
MAX_PORTABLE_FILE_BYTES = 1_000_000_000
MAX_PORTABLE_TOTAL_BYTES = 2_000_000_000
MAX_DISTRIBUTION_TOTAL_BYTES = 5_000_000_000
MAX_DISTRIBUTION_TOP_LEVEL_ENTRIES = 4
MAX_ARCHIVE_BYTES = 2_100_000_000
MAX_METADATA_BYTES = 16 * 1024 * 1024
MAX_PE_HEADER_BYTES = 16 * 1024 * 1024
MAX_COMPONENT_BYTES = 255
MAX_RELATIVE_PATH_BYTES = 4096
MAX_SECTOR_VERSION_BYTES = 32
UNSIGNED_STATUS = "verified-pe-certificate-table-absent"
_READ_BLOCK = 1024 * 1024
_PORTABLE_SCHEMA = 1
_RECEIPT_SCHEMA = 1
_COMPARISON_SCHEMA = 1
_ZIP_CREATE_SYSTEM = 3
_ZIP_CREATE_VERSION = 20
_ZIP_EXTRACT_VERSION = 20
_ZIP_UTF8_FLAG = 0x800
_ZIP_CENTRAL_HEADER_BYTES = 46
_ZIP_LOCAL_HEADER_BYTES = 30
_SECTOR_VERSION = re.compile(r"^[0-9]+\.[0-9]+$")
_RESERVED_WINDOWS_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
    *(f"COM{index}" for index in ("\u00b9", "\u00b2", "\u00b3")),
    *(f"LPT{index}" for index in ("\u00b9", "\u00b2", "\u00b3")),
}


def _load_sibling(filename: str, module_name: str) -> ModuleType:
    path = Path(__file__).resolve().with_name(filename)
    specification = importlib.util.spec_from_file_location(module_name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"cannot load required portable-build module: {filename}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        specification.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


_EXACT = _load_sibling("build_exact_commit.py", "sector_portable_exact_build")
_RELEASE = _load_sibling(
    "verify_windows_release.py", "sector_portable_release_verifier"
)
BuildCommand = _EXACT.BuildCommand
ExactBuildError = _EXACT.ExactBuildError
prepare_exact_build = _EXACT.prepare_exact_build
execute_exact_build = _EXACT.execute_exact_build
ReleaseVerificationError = _RELEASE.ReleaseVerificationError
if _RELEASE.MAX_SECTOR_VERSION_BYTES != MAX_SECTOR_VERSION_BYTES:
    raise RuntimeError("portable and release version bounds differ")


class PortableBuildError(RuntimeError):
    """The portable distribution is unsafe, incomplete, or inconsistent."""


@dataclass(frozen=True)
class PortableBuildEvidence:
    source_revision: str
    source_tree: str
    sector_version: str
    unsigned_status: str
    folder_name: str
    archive_name: str
    archive_sha256: str
    folder_file_count: int
    folder_total_bytes: int
    folder_inventory_sha256: str
    output: Path
    folder: Path
    archive: Path
    sidecar: Path
    receipt: Path


@dataclass(frozen=True)
class PortableComparisonEvidence:
    source_revision: str
    source_tree: str
    sector_version: str
    unsigned_status: str
    artifact_name: str
    distribution_file_count: int
    distribution_total_bytes: int
    distribution_inventory_sha256: str
    evidence_path: Path


@dataclass(frozen=True)
class _FileRecord:
    path: str
    bytes: int
    sha256: str


@dataclass(frozen=True)
class _TreeInventory:
    files: tuple[_FileRecord, ...]
    directories: tuple[str, ...]
    total_bytes: int
    sha256: str


@dataclass(frozen=True)
class _ArchiveInventory:
    root_name: str
    timestamp: tuple[int, int, int, int, int, int]
    files: tuple[_FileRecord, ...]
    archive_bytes: int
    archive_sha256: str


@dataclass(frozen=True)
class _ZipPreflight:
    archive_bytes: int
    member_count: int
    central_size: int
    central_offset: int


def _canonical_json(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("ascii")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise PortableBuildError(f"JSON object contains duplicate key: {key}")
        value[key] = item
    return value


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    raw = _read_regular_file(path, label)
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PortableBuildError(f"{label} is not canonical JSON") from exc
    if not isinstance(value, dict):
        raise PortableBuildError(f"{label} must be a JSON object")
    if raw != _canonical_json(value):
        raise PortableBuildError(f"{label} is not canonical JSON")
    return value, raw


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


def _entry_signature(status: os.stat_result) -> tuple[int, ...]:
    """Compare DirEntry metadata without Windows' unavailable inode fields."""
    return (
        stat.S_IFMT(status.st_mode),
        status.st_size,
        status.st_mtime_ns,
        getattr(status, "st_file_attributes", 0),
    )


def _lstat(path: Path, label: str) -> os.stat_result:
    try:
        return os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise PortableBuildError(f"cannot inspect {label}") from exc


def _require_directory(path: Path, label: str) -> os.stat_result:
    status = _lstat(path, label)
    if stat.S_ISLNK(status.st_mode) or _is_reparse(status):
        raise PortableBuildError(f"{label} is a linked or reparse path")
    if not stat.S_ISDIR(status.st_mode):
        raise PortableBuildError(f"{label} is not an ordinary directory")
    return status


def _lexical_source_root(root: Path) -> Path:
    """Reject a linked source-root entry before any path resolution occurs."""
    lexical = Path(os.path.abspath(root))
    _require_directory(lexical, "portable source root")
    return lexical


def _read_regular_file(
    path: Path,
    label: str,
    *,
    expected: os.stat_result | None = None,
    limit: int = MAX_METADATA_BYTES,
) -> bytes:
    before = _lstat(path, label)
    if stat.S_ISLNK(before.st_mode) or _is_reparse(before):
        raise PortableBuildError(f"{label} is a linked or reparse path")
    if not stat.S_ISREG(before.st_mode):
        raise PortableBuildError(f"{label} is not an ordinary file")
    if expected is not None and _entry_signature(before) != _entry_signature(expected):
        raise PortableBuildError(f"{label} changed before it was read")
    if before.st_size > limit:
        raise PortableBuildError(f"{label} exceeds the portable resource limit")
    chunks: list[bytes] = []
    total = 0
    try:
        with path.open("rb") as stream:
            opened_before = os.fstat(stream.fileno())
            if _status_signature(opened_before) != _status_signature(before):
                raise PortableBuildError(f"{label} changed while it was opened")
            while True:
                block = stream.read(_READ_BLOCK)
                if not block:
                    break
                total += len(block)
                if total > limit:
                    raise PortableBuildError(
                        f"{label} exceeds the portable resource limit"
                    )
                chunks.append(block)
            opened_after = os.fstat(stream.fileno())
        after = _lstat(path, label)
    except PortableBuildError:
        raise
    except OSError as exc:
        raise PortableBuildError(f"cannot read {label}") from exc
    signatures = (before, opened_before, opened_after, after)
    if any(
        _status_signature(left) != _status_signature(right)
        for left, right in itertools.pairwise(signatures)
    ):
        raise PortableBuildError(f"{label} changed while it was read")
    payload = b"".join(chunks)
    if len(payload) != before.st_size:
        raise PortableBuildError(f"{label} byte count changed while it was read")
    return payload


def _hash_regular_file(
    path: Path,
    label: str,
    *,
    expected: os.stat_result | None = None,
    limit: int = MAX_PORTABLE_FILE_BYTES,
) -> tuple[int, str]:
    before = _lstat(path, label)
    if stat.S_ISLNK(before.st_mode) or _is_reparse(before):
        raise PortableBuildError(f"{label} is a linked or reparse path")
    if not stat.S_ISREG(before.st_mode):
        raise PortableBuildError(f"{label} is not an ordinary file")
    if expected is not None and _entry_signature(before) != _entry_signature(expected):
        raise PortableBuildError(f"{label} changed before it was read")
    if before.st_size > limit:
        raise PortableBuildError(f"{label} exceeds the portable resource limit")
    digest = hashlib.sha256()
    count = 0
    try:
        with path.open("rb") as stream:
            opened_before = os.fstat(stream.fileno())
            if _status_signature(opened_before) != _status_signature(before):
                raise PortableBuildError(f"{label} changed while it was opened")
            while True:
                block = stream.read(_READ_BLOCK)
                if not block:
                    break
                count += len(block)
                if count > limit:
                    raise PortableBuildError(
                        f"{label} exceeds the portable resource limit"
                    )
                digest.update(block)
            opened_after = os.fstat(stream.fileno())
        after = _lstat(path, label)
    except PortableBuildError:
        raise
    except OSError as exc:
        raise PortableBuildError(f"cannot read {label}") from exc
    signatures = (before, opened_before, opened_after, after)
    if any(
        _status_signature(left) != _status_signature(right)
        for left, right in itertools.pairwise(signatures)
    ):
        raise PortableBuildError(f"{label} changed while it was read")
    if count != before.st_size:
        raise PortableBuildError(f"{label} byte count changed while it was read")
    return count, digest.hexdigest()


def _copy_regular_to_stream(
    path: Path,
    destination: IO[bytes],
    label: str,
    *,
    expected: _FileRecord,
) -> None:
    before = _lstat(path, label)
    if stat.S_ISLNK(before.st_mode) or _is_reparse(before) or not stat.S_ISREG(
        before.st_mode
    ):
        raise PortableBuildError(f"{label} is not an ordinary no-follow file")
    if before.st_size != expected.bytes or before.st_size > MAX_PORTABLE_FILE_BYTES:
        raise PortableBuildError(f"{label} byte count differs from its inventory")
    digest = hashlib.sha256()
    count = 0
    try:
        with path.open("rb") as source:
            opened_before = os.fstat(source.fileno())
            if _status_signature(opened_before) != _status_signature(before):
                raise PortableBuildError(f"{label} changed while it was opened")
            while True:
                block = source.read(_READ_BLOCK)
                if not block:
                    break
                count += len(block)
                if count > MAX_PORTABLE_FILE_BYTES:
                    raise PortableBuildError(
                        f"{label} exceeds the portable resource limit"
                    )
                digest.update(block)
                destination.write(block)
            opened_after = os.fstat(source.fileno())
        after = _lstat(path, label)
    except PortableBuildError:
        raise
    except OSError as exc:
        raise PortableBuildError(f"cannot stream {label}") from exc
    signatures = (before, opened_before, opened_after, after)
    if any(
        _status_signature(left) != _status_signature(right)
        for left, right in itertools.pairwise(signatures)
    ):
        raise PortableBuildError(f"{label} changed while it was streamed")
    if count != expected.bytes or digest.hexdigest() != expected.sha256:
        raise PortableBuildError(f"{label} bytes differ from its inventory")


def _validate_component(component: str) -> None:
    if not component or component in {".", ".."}:
        raise PortableBuildError("portable path contains an empty or dot component")
    if unicodedata.normalize("NFC", component) != component:
        raise PortableBuildError("portable path contains a non-NFC component")
    try:
        raw = component.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise PortableBuildError("portable path component is not valid UTF-8") from exc
    if len(raw) > MAX_COMPONENT_BYTES:
        raise PortableBuildError("portable path component exceeds the resource limit")
    if component[-1] in {" ", "."}:
        raise PortableBuildError("portable path component has a trailing dot or space")
    if any(ord(character) < 32 or character in '<>:"/\\|?*' for character in component):
        raise PortableBuildError("portable path contains a Windows-unsafe component")
    stem = component.split(".", 1)[0].rstrip(" .").upper()
    if stem in _RESERVED_WINDOWS_NAMES:
        raise PortableBuildError("portable path contains a Windows device name")


def _validate_relative_path(path: str) -> tuple[str, ...]:
    if not path or path.startswith(("/", "\\")) or "\\" in path:
        raise PortableBuildError("portable path is absolute or noncanonical")
    if len(path.encode("utf-8")) > MAX_RELATIVE_PATH_BYTES:
        raise PortableBuildError("portable path exceeds the resource limit")
    pure = PurePosixPath(path)
    if pure.as_posix() != path or pure.is_absolute():
        raise PortableBuildError("portable path is not canonical POSIX text")
    parts = pure.parts
    for component in parts:
        _validate_component(component)
    return parts


def _register_path(
    registry: dict[str, str], parts: tuple[str, ...], kind: str
) -> None:
    for index in range(1, len(parts) + 1):
        prefix = PurePosixPath(*parts[:index]).as_posix()
        prefix_kind = kind if index == len(parts) else "directory"
        key = unicodedata.normalize("NFC", prefix).casefold()
        previous = registry.get(key)
        if previous is None:
            registry[key] = prefix_kind
        elif previous != prefix_kind:
            raise PortableBuildError("portable tree contains a file/directory prefix collision")
        elif prefix_kind == "file":
            raise PortableBuildError("portable tree contains a duplicate or case collision")


def _inventory_digest(records: Iterable[_FileRecord]) -> str:
    digest = hashlib.sha256()
    for record in records:
        digest.update(
            json.dumps(
                [record.path, record.bytes, record.sha256],
                ensure_ascii=True,
                separators=(",", ":"),
            ).encode("ascii")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def _distribution_file_limit(relative: str) -> int:
    parts = PurePosixPath(relative).parts
    if len(parts) == 1 and relative.casefold().endswith(".zip"):
        return MAX_ARCHIVE_BYTES
    return MAX_PORTABLE_FILE_BYTES


def _scan_tree(
    root: Path,
    *,
    total_limit: int = MAX_PORTABLE_TOTAL_BYTES,
    allow_top_level_archive: bool = False,
) -> _TreeInventory:
    root = Path(os.path.abspath(root))
    _require_directory(root, "portable tree root")
    pending: list[tuple[Path, tuple[str, ...]]] = [(root, ())]
    records: list[_FileRecord] = []
    directories: set[str] = set()
    registry: dict[str, str] = {}
    total = 0
    path_count = 0
    while pending:
        directory, parent_parts = pending.pop()
        before = _require_directory(directory, "portable tree directory")
        try:
            entries: list[os.DirEntry[str]] = []
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    path_count += 1
                    if path_count > MAX_PORTABLE_PATHS:
                        raise PortableBuildError(
                            "portable tree exceeds the path-count limit"
                        )
                    entries.append(entry)
            entries.sort(key=lambda item: item.name)
        except PortableBuildError:
            raise
        except OSError as exc:
            raise PortableBuildError("cannot enumerate portable tree") from exc
        after = _require_directory(directory, "portable tree directory")
        if _status_signature(before) != _status_signature(after):
            raise PortableBuildError("portable tree directory changed during inventory")
        for entry in entries:
            parts = (*parent_parts, entry.name)
            relative = PurePosixPath(*parts).as_posix()
            validated = _validate_relative_path(relative)
            try:
                status = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise PortableBuildError(
                    f"cannot inspect portable tree entry: {relative}"
                ) from exc
            if entry.is_symlink() or _is_reparse(status):
                raise PortableBuildError(
                    f"portable tree contains a linked or reparse path: {relative}"
                )
            if stat.S_ISDIR(status.st_mode):
                if len(directories) >= MAX_PORTABLE_DIRECTORIES:
                    raise PortableBuildError(
                        "portable tree exceeds the directory-count limit"
                    )
                _register_path(registry, validated, "directory")
                directories.add(relative)
                pending.append((Path(entry.path), parts))
                continue
            if not stat.S_ISREG(status.st_mode):
                raise PortableBuildError(
                    f"portable tree contains a special entry: {relative}"
                )
            _register_path(registry, validated, "file")
            if len(records) >= MAX_PORTABLE_FILES:
                raise PortableBuildError("portable tree exceeds the file-count limit")
            file_limit = (
                _distribution_file_limit(relative)
                if allow_top_level_archive
                else MAX_PORTABLE_FILE_BYTES
            )
            if status.st_size > file_limit:
                raise PortableBuildError(
                    f"portable file exceeds the resource limit: {relative}"
                )
            total += status.st_size
            if total > total_limit:
                raise PortableBuildError("portable tree exceeds the total-byte limit")
            count, digest = _hash_regular_file(
                Path(entry.path),
                f"portable file {relative}",
                expected=status,
                limit=file_limit,
            )
            records.append(_FileRecord(relative, count, digest))
    records.sort(key=lambda item: item.path)
    # Empty directories cannot be represented by the canonical file-only ZIP.
    populated = {
        PurePosixPath(*PurePosixPath(item.path).parts[:index]).as_posix()
        for item in records
        for index in range(1, len(PurePosixPath(item.path).parts))
    }
    if directories.difference(populated):
        raise PortableBuildError("portable tree contains an empty directory")
    return _TreeInventory(
        tuple(records), tuple(sorted(directories)), total, _inventory_digest(records)
    )


def _stable_inventory(
    root: Path,
    *,
    total_limit: int = MAX_PORTABLE_TOTAL_BYTES,
    allow_top_level_archive: bool = False,
) -> _TreeInventory:
    first = _scan_tree(
        root,
        total_limit=total_limit,
        allow_top_level_archive=allow_top_level_archive,
    )
    second = _scan_tree(
        root,
        total_limit=total_limit,
        allow_top_level_archive=allow_top_level_archive,
    )
    if first != second:
        raise PortableBuildError("portable tree changed between authentication passes")
    return first


def _record_map(inventory: _TreeInventory) -> dict[str, _FileRecord]:
    return {record.path: record for record in inventory.files}


def _write_new(path: Path, payload: bytes, label: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(payload)
    except FileExistsError as exc:
        raise PortableBuildError(f"{label} already exists: {path.name}") from exc
    except OSError as exc:
        raise PortableBuildError(f"cannot write {label}: {path.name}") from exc


def _copy_verified_tree(source: Path, destination: Path) -> _TreeInventory:
    before = _stable_inventory(source)
    try:
        destination.mkdir()
    except OSError as exc:
        raise PortableBuildError("cannot create portable folder staging root") from exc
    source_records = _record_map(before)
    for record in before.files:
        source_path = source.joinpath(*PurePosixPath(record.path).parts)
        target = destination.joinpath(*PurePosixPath(record.path).parts)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                _copy_regular_to_stream(
                    source_path,
                    stream,
                    f"package file {record.path}",
                    expected=record,
                )
        except PortableBuildError:
            raise
        except FileExistsError as exc:
            raise PortableBuildError(
                f"portable file already exists: {record.path}"
            ) from exc
        except OSError as exc:
            raise PortableBuildError(
                f"cannot copy portable file: {record.path}"
            ) from exc
    after = _stable_inventory(source)
    copied = _stable_inventory(destination)
    if before != after or source_records != _record_map(copied):
        raise PortableBuildError("package tree changed while assembling portable output")
    return copied


def _snapshot_identity(
    root: Path, source_revision: str
) -> tuple[Any, dict[str, str]]:
    root = _lexical_source_root(root)
    try:
        snapshot = _RELEASE._snapshot(root, source_revision)
        identity = _RELEASE._product_identity(snapshot)
    except ReleaseVerificationError as exc:
        raise PortableBuildError(f"cannot authenticate portable source: {exc}") from exc
    return snapshot, cast(dict[str, str], identity)


def _source_object(snapshot: Any) -> dict[str, str | int]:
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


def _validate_sector_version(version: str) -> str:
    if (
        not isinstance(version, str)
        or len(version.encode("ascii", errors="ignore")) != len(version)
        or len(version) > MAX_SECTOR_VERSION_BYTES
        or _SECTOR_VERSION.fullmatch(version) is None
    ):
        raise PortableBuildError("portable Sector version is invalid or too long")
    return version


def _portable_name(version: str) -> str:
    return f"Sector-v{_validate_sector_version(version)}-windows-portable-unsigned"


def _snapshot_file(snapshot: Any, relative: str) -> bytes:
    matches = [item.payload for item in snapshot.files if item.path == relative]
    if len(matches) != 1:
        raise PortableBuildError(
            f"authenticated source is missing or duplicates {relative}"
        )
    return cast(bytes, matches[0])


def _readme(snapshot: Any, identity: dict[str, str]) -> bytes:
    raw = _snapshot_file(snapshot, "packaging/README-PORTABLE.txt")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PortableBuildError("portable README template is not UTF-8") from exc
    token = "@SECTOR_VERSION@"
    if text.count(token) != 1 or "\r" in text or not text.endswith("\n"):
        raise PortableBuildError(
            "portable README template must be canonical LF text with one version token"
        )
    rendered = text.replace(token, identity["__version__"])
    if "@SECTOR_" in rendered:
        raise PortableBuildError("portable README template contains an unknown token")
    return rendered.encode("utf-8")


def _pe_unsigned_status(executable: Path) -> str:
    before = _lstat(executable, "Sector.exe")
    if stat.S_ISLNK(before.st_mode) or _is_reparse(before) or not stat.S_ISREG(
        before.st_mode
    ):
        raise PortableBuildError("Sector.exe is not an ordinary no-follow file")
    try:
        with executable.open("rb") as stream:
            opened_before = os.fstat(stream.fileno())
            if _status_signature(opened_before) != _status_signature(before):
                raise PortableBuildError("Sector.exe changed while it was opened")
            dos = stream.read(64)
            if len(dos) != 64 or dos[:2] != b"MZ":
                raise PortableBuildError("Sector.exe is not a valid PE image")
            pe_offset = struct.unpack_from("<I", dos, 0x3C)[0]
            if pe_offset < 64 or pe_offset + 24 > before.st_size or pe_offset > MAX_PE_HEADER_BYTES:
                raise PortableBuildError("Sector.exe has an invalid PE header offset")
            stream.seek(pe_offset)
            pe_and_coff = stream.read(24)
            if len(pe_and_coff) != 24 or pe_and_coff[:4] != b"PE\0\0":
                raise PortableBuildError("Sector.exe has an invalid PE signature")
            optional_size = struct.unpack_from("<H", pe_and_coff, 20)[0]
            if optional_size > MAX_PE_HEADER_BYTES or pe_offset + 24 + optional_size > before.st_size:
                raise PortableBuildError("Sector.exe has a truncated PE optional header")
            optional_payload = stream.read(optional_size)
            opened_after = os.fstat(stream.fileno())
        after = _lstat(executable, "Sector.exe")
    except PortableBuildError:
        raise
    except OSError as exc:
        raise PortableBuildError("cannot inspect Sector.exe PE headers") from exc
    signatures = (before, opened_before, opened_after, after)
    if any(
        _status_signature(left) != _status_signature(right)
        for left, right in itertools.pairwise(signatures)
    ):
        raise PortableBuildError("Sector.exe changed during PE inspection")
    if optional_size < 2 or len(optional_payload) != optional_size:
        raise PortableBuildError("Sector.exe has no PE optional header")
    magic = struct.unpack_from("<H", optional_payload, 0)[0]
    if magic == 0x10B:
        directory_count_offset, directories_offset = 92, 96
    elif magic == 0x20B:
        directory_count_offset, directories_offset = 108, 112
    else:
        raise PortableBuildError("Sector.exe has an unsupported PE optional header")
    security_offset = directories_offset + (4 * 8)
    if optional_size < security_offset + 8:
        raise PortableBuildError("Sector.exe has no inspectable PE security directory")
    directory_count = struct.unpack_from(
        "<I", optional_payload, directory_count_offset
    )[0]
    if directory_count < 5:
        raise PortableBuildError("Sector.exe has no PE certificate-table directory")
    certificate_offset, certificate_size = struct.unpack_from(
        "<II", optional_payload, security_offset
    )
    if certificate_offset != 0 or certificate_size != 0:
        raise PortableBuildError("Sector.exe contains a PE certificate table")
    return UNSIGNED_STATUS


def _manifest_records(records: Iterable[_FileRecord]) -> list[dict[str, str | int]]:
    return [
        {"path": item.path, "bytes": item.bytes, "sha256": item.sha256}
        for item in records
    ]


def _portable_manifest(
    snapshot: Any,
    identity: dict[str, str],
    payload: _TreeInventory,
) -> dict[str, Any]:
    return {
        "portable_manifest_schema": _PORTABLE_SCHEMA,
        "product_name": identity["__product_name__"],
        "description": identity["__description__"],
        "sector_version": identity["__version__"],
        "author": identity["__author__"],
        "licensee": identity["__licensee__"],
        "copyright": identity["__copyright__"],
        "built_at_utc": snapshot.evidence.source_committed_at_utc,
        "unsigned_status": UNSIGNED_STATUS,
        **_source_object(snapshot),
        "payload_file_count": len(payload.files),
        "payload_total_bytes": payload.total_bytes,
        "payload_inventory_sha256": payload.sha256,
        "payload_files": _manifest_records(payload.files),
    }


def _sha256_sums(records: Iterable[_FileRecord]) -> bytes:
    return "".join(f"{item.sha256}  {item.path}\n" for item in records).encode("utf-8")


def _zip_time(epoch: int) -> tuple[int, int, int, int, int, int]:
    moment = datetime.fromtimestamp(epoch, tz=timezone.utc)
    if not 1980 <= moment.year <= 2107:
        raise PortableBuildError("source timestamp is outside the canonical ZIP range")
    return (moment.year, moment.month, moment.day, moment.hour, moment.minute, moment.second // 2 * 2)


def _zip_mode(relative: str) -> int:
    return 0o100755 if relative == "Sector.exe" else 0o100644


def _zip_name_bytes(name: str) -> tuple[bytes, int]:
    try:
        return name.encode("ascii"), 0
    except UnicodeEncodeError:
        return name.encode("utf-8"), _ZIP_UTF8_FLAG


def _zip_dos_datetime(
    timestamp: tuple[int, int, int, int, int, int],
) -> tuple[int, int]:
    try:
        moment = datetime(*timestamp, tzinfo=timezone.utc)
    except (TypeError, ValueError) as exc:
        raise PortableBuildError("portable ZIP timestamp is invalid") from exc
    if not 1980 <= moment.year <= 2107 or moment.second % 2:
        raise PortableBuildError("portable ZIP timestamp is noncanonical")
    dos_time = (moment.hour << 11) | (moment.minute << 5) | (moment.second // 2)
    dos_date = ((moment.year - 1980) << 9) | (moment.month << 5) | moment.day
    return dos_time, dos_date


def _validate_zip_info_metadata(
    info: zipfile.ZipInfo,
    relative: str,
    timestamp: tuple[int, int, int, int, int, int],
    *,
    expected_size: int | None = None,
) -> tuple[bytes, int, int, int]:
    raw_name, expected_flags = _zip_name_bytes(info.filename)
    dos_time, dos_date = _zip_dos_datetime(timestamp)
    expected_external_attr = _zip_mode(relative) << 16
    if (
        info.orig_filename != info.filename
        or info.is_dir()
        or info.compress_type != zipfile.ZIP_STORED
        or info.compress_size != info.file_size
        or (expected_size is not None and info.file_size != expected_size)
        or info.create_system != _ZIP_CREATE_SYSTEM
        or info.create_version != _ZIP_CREATE_VERSION
        or info.extract_version != _ZIP_EXTRACT_VERSION
        or info.reserved != 0
        or info.flag_bits != expected_flags
        or info.volume != 0
        or info.internal_attr != 0
        or info.external_attr != expected_external_attr
        or info.date_time != timestamp
        or info.extra != b""
        or info.comment != b""
    ):
        raise PortableBuildError(
            f"portable ZIP metadata is noncanonical: {info.filename}"
        )
    return raw_name, expected_flags, dos_time, dos_date


def _zip_info(
    name: str,
    relative: str,
    timestamp: tuple[int, int, int, int, int, int],
) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=timestamp)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = _ZIP_CREATE_SYSTEM
    info.create_version = _ZIP_CREATE_VERSION
    info.extract_version = _ZIP_EXTRACT_VERSION
    info.reserved = 0
    info.flag_bits = _zip_name_bytes(name)[1]
    info.volume = 0
    info.internal_attr = 0
    info.external_attr = _zip_mode(relative) << 16
    return info


def _write_archive(
    folder: Path,
    folder_name: str,
    inventory: _TreeInventory,
    archive: Path,
    timestamp: tuple[int, int, int, int, int, int],
) -> None:
    try:
        with archive.open("xb") as raw_stream, zipfile.ZipFile(
            raw_stream, "w", compression=zipfile.ZIP_STORED, allowZip64=False
        ) as bundle:
            for record in inventory.files:
                name = f"{folder_name}/{record.path}"
                info = _zip_info(name, record.path, timestamp)
                info.file_size = record.bytes
                with bundle.open(info, "w", force_zip64=False) as destination:
                    _copy_regular_to_stream(
                        folder.joinpath(*PurePosixPath(record.path).parts),
                        destination,
                        f"portable archive input {record.path}",
                        expected=record,
                    )
    except PortableBuildError:
        raise
    except (OSError, ValueError, zipfile.LargeZipFile) as exc:
        raise PortableBuildError("cannot create canonical portable ZIP") from exc
    if archive.stat().st_size > MAX_ARCHIVE_BYTES:
        raise PortableBuildError("portable archive exceeds the resource limit")
    if _stable_inventory(folder) != inventory:
        raise PortableBuildError("portable folder changed during archive creation")


def _preflight_zip_stream(
    stream: BinaryIO, *, expected_size: int | None = None
) -> _ZipPreflight:
    """Bound the raw ZIP footer and central directory before ZipFile allocates."""
    try:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        if expected_size is not None and size != expected_size:
            raise PortableBuildError(
                "portable ZIP byte count changed before preflight"
            )
        if size < 22 or size > MAX_ARCHIVE_BYTES:
            raise PortableBuildError("portable ZIP final size is invalid")
        stream.seek(size - 22)
        eocd = stream.read(22)
        if len(eocd) != 22 or eocd[:4] != b"PK\x05\x06":
            raise PortableBuildError(
                "portable ZIP has trailing data or a noncanonical footer"
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
        ) = struct.unpack("<4s4H2LH", eocd)
        if (
            disk == 0xFFFF
            or central_disk == 0xFFFF
            or disk_entries == 0xFFFF
            or total_entries == 0xFFFF
            or central_size == 0xFFFFFFFF
            or central_offset == 0xFFFFFFFF
        ):
            raise PortableBuildError("portable ZIP64 metadata is not accepted")
        if (
            disk != 0
            or central_disk != 0
            or disk_entries != total_entries
            or total_entries < 1
            or total_entries > MAX_PORTABLE_FILES
            or comment_length != 0
            or central_offset + central_size != size - 22
        ):
            raise PortableBuildError("portable ZIP footer is noncanonical")
        minimum_central = total_entries * _ZIP_CENTRAL_HEADER_BYTES
        maximum_central = total_entries * (
            _ZIP_CENTRAL_HEADER_BYTES + MAX_RELATIVE_PATH_BYTES
        )
        if not minimum_central <= central_size <= maximum_central:
            raise PortableBuildError(
                "portable ZIP central directory exceeds the allocation bound"
            )

        stream.seek(central_offset)
        consumed = 0
        for _member in range(total_entries):
            header = stream.read(_ZIP_CENTRAL_HEADER_BYTES)
            if (
                len(header) != _ZIP_CENTRAL_HEADER_BYTES
                or header[:4] != b"PK\x01\x02"
            ):
                raise PortableBuildError(
                    "portable ZIP central directory is malformed"
                )
            compressed_size = struct.unpack_from("<I", header, 20)[0]
            uncompressed_size = struct.unpack_from("<I", header, 24)[0]
            filename_size = struct.unpack_from("<H", header, 28)[0]
            extra_size = struct.unpack_from("<H", header, 30)[0]
            member_comment_size = struct.unpack_from("<H", header, 32)[0]
            member_disk = struct.unpack_from("<H", header, 34)[0]
            local_offset = struct.unpack_from("<I", header, 42)[0]
            if (
                compressed_size == 0xFFFFFFFF
                or uncompressed_size == 0xFFFFFFFF
                or member_disk == 0xFFFF
                or local_offset == 0xFFFFFFFF
            ):
                raise PortableBuildError("portable ZIP64 member is not accepted")
            trailing = filename_size + extra_size + member_comment_size
            consumed += _ZIP_CENTRAL_HEADER_BYTES + trailing
            if (
                filename_size < 1
                or trailing > MAX_RELATIVE_PATH_BYTES
                or consumed > central_size
            ):
                raise PortableBuildError(
                    "portable ZIP central member exceeds the allocation bound"
                )
            stream.seek(trailing, os.SEEK_CUR)
        if consumed != central_size or stream.tell() != size - 22:
            raise PortableBuildError(
                "portable ZIP central directory byte count differs"
            )
    except PortableBuildError:
        raise
    except (OSError, struct.error) as exc:
        raise PortableBuildError("cannot preflight portable ZIP") from exc
    return _ZipPreflight(size, total_entries, central_size, central_offset)


def _exact_zip_boundaries(
    stream: BinaryIO,
    entries: list[tuple[zipfile.ZipInfo, str, int | None]],
    timestamp: tuple[int, int, int, int, int, int],
) -> None:
    preflight = _preflight_zip_stream(stream)
    if preflight.member_count != len(entries):
        raise PortableBuildError("portable ZIP central directory is noncanonical")
    expected_offset = 0
    expected_central_size = 0
    for info, relative, expected_size in entries:
        raw_expected_name, expected_flags, dos_time, dos_date = (
            _validate_zip_info_metadata(
                info, relative, timestamp, expected_size=expected_size
            )
        )
        expected_central_size += _ZIP_CENTRAL_HEADER_BYTES + len(raw_expected_name)
        if info.header_offset != expected_offset:
            raise PortableBuildError("portable ZIP contains prefix or inter-entry data")
        stream.seek(info.header_offset)
        local = stream.read(30)
        if len(local) != 30 or local[:4] != b"PK\x03\x04":
            raise PortableBuildError("portable ZIP local header is invalid")
        fields = struct.unpack("<4s5H3L2H", local)
        extract_version, flags, method = fields[1], fields[2], fields[3]
        local_time, local_date, crc = fields[4], fields[5], fields[6]
        compressed_size, uncompressed_size = fields[7], fields[8]
        filename_size, extra_size = fields[9], fields[10]
        raw_name = stream.read(filename_size)
        if (
            extract_version != _ZIP_EXTRACT_VERSION
            or extract_version != info.extract_version
            or flags != expected_flags
            or flags != info.flag_bits
            or method != info.compress_type
            or method != zipfile.ZIP_STORED
            or local_time != dos_time
            or local_date != dos_date
            or crc != info.CRC
            or compressed_size != info.compress_size
            or uncompressed_size != info.file_size
            or extra_size != 0
            or raw_name != raw_expected_name
        ):
            raise PortableBuildError("portable ZIP local metadata is noncanonical")
        expected_offset = (
            info.header_offset
            + _ZIP_LOCAL_HEADER_BYTES
            + filename_size
            + info.compress_size
        )
    if (
        expected_offset != preflight.central_offset
        or expected_central_size != preflight.central_size
    ):
        raise PortableBuildError("portable ZIP contains data outside canonical entries")


def _archive_inventory(
    archive: Path,
    *,
    expected_root: str | None = None,
    expected_timestamp: tuple[int, int, int, int, int, int] | None = None,
) -> _ArchiveInventory:
    before = _lstat(archive, "portable archive")
    if stat.S_ISLNK(before.st_mode) or _is_reparse(before) or not stat.S_ISREG(before.st_mode):
        raise PortableBuildError("portable archive is not an ordinary file")
    if before.st_size > MAX_ARCHIVE_BYTES:
        raise PortableBuildError("portable archive exceeds the resource limit")
    try:
        with archive.open("rb") as stream:
            opened_before = os.fstat(stream.fileno())
            if _status_signature(opened_before) != _status_signature(before):
                raise PortableBuildError("portable archive changed while it was opened")
            preflight = _preflight_zip_stream(
                stream, expected_size=before.st_size
            )
            stream.seek(0)
            with zipfile.ZipFile(stream, "r") as bundle:
                infos = bundle.infolist()
                if (
                    not infos
                    or len(infos) != preflight.member_count
                    or bundle.comment
                ):
                    raise PortableBuildError("portable ZIP inventory is invalid")
                registry: dict[str, str] = {}
                root_name: str | None = None
                seen: set[str] = set()
                total = 0
                prior_name: str | None = None
                timestamp = (
                    infos[0].date_time
                    if expected_timestamp is None
                    else expected_timestamp
                )
                entries: list[tuple[zipfile.ZipInfo, str, int | None]] = []
                for info in infos:
                    if info.filename in seen or (
                        prior_name is not None and info.filename <= prior_name
                    ):
                        raise PortableBuildError(
                            "portable ZIP names are duplicate or unsorted"
                        )
                    seen.add(info.filename)
                    prior_name = info.filename
                    parts = _validate_relative_path(info.filename)
                    if len(parts) < 2:
                        raise PortableBuildError(
                            "portable ZIP entry has no distribution root"
                        )
                    if root_name is None:
                        root_name = parts[0]
                    if parts[0] != root_name or (
                        expected_root is not None and parts[0] != expected_root
                    ):
                        raise PortableBuildError(
                            "portable ZIP has more than one distribution root"
                        )
                    relative = PurePosixPath(*parts[1:]).as_posix()
                    relative_parts = _validate_relative_path(relative)
                    _register_path(registry, relative_parts, "file")
                    if info.file_size > MAX_PORTABLE_FILE_BYTES:
                        raise PortableBuildError(
                            "portable ZIP entry exceeds the resource limit"
                        )
                    total += info.file_size
                    if total > MAX_PORTABLE_TOTAL_BYTES:
                        raise PortableBuildError(
                            "portable ZIP expands beyond the resource limit"
                        )
                    entries.append((info, relative, None))
                _exact_zip_boundaries(stream, entries, timestamp)
                result: list[_FileRecord] = []
                for info, relative, _expected_size in entries:
                    digest = hashlib.sha256()
                    count = 0
                    with bundle.open(info, "r") as member:
                        while True:
                            block = member.read(_READ_BLOCK)
                            if not block:
                                break
                            count += len(block)
                            if count > MAX_PORTABLE_FILE_BYTES:
                                raise PortableBuildError(
                                    "portable ZIP entry exceeds the resource limit"
                                )
                            digest.update(block)
                    if count != info.file_size:
                        raise PortableBuildError(
                            f"portable ZIP entry byte count differs: {relative}"
                        )
                    result.append(_FileRecord(relative, count, digest.hexdigest()))
                if root_name is None:
                    raise PortableBuildError("portable ZIP has no distribution root")
            stream.seek(0)
            archive_digest = hashlib.sha256()
            archive_bytes = 0
            while True:
                block = stream.read(_READ_BLOCK)
                if not block:
                    break
                archive_bytes += len(block)
                if archive_bytes > MAX_ARCHIVE_BYTES:
                    raise PortableBuildError(
                        "portable archive exceeds the resource limit"
                    )
                archive_digest.update(block)
            opened_after = os.fstat(stream.fileno())
        after = _lstat(archive, "portable archive")
    except PortableBuildError:
        raise
    except (OSError, zipfile.BadZipFile, UnicodeError, struct.error) as exc:
        raise PortableBuildError("cannot read canonical portable ZIP") from exc
    signatures = (before, opened_before, opened_after, after)
    if any(
        _status_signature(left) != _status_signature(right)
        for left, right in itertools.pairwise(signatures)
    ):
        raise PortableBuildError("portable archive changed during authentication")
    if archive_bytes != before.st_size:
        raise PortableBuildError("portable archive byte count changed")
    return _ArchiveInventory(
        root_name,
        timestamp,
        tuple(result),
        archive_bytes,
        archive_digest.hexdigest(),
    )


def _verify_archive(
    archive: Path,
    folder: Path,
    folder_name: str,
    inventory: _TreeInventory,
    timestamp: tuple[int, int, int, int, int, int],
) -> tuple[int, str]:
    archived = _archive_inventory(
        archive, expected_root=folder_name, expected_timestamp=timestamp
    )
    if archived.root_name != folder_name or archived.files != inventory.files:
        raise PortableBuildError("portable ZIP bytes differ from the folder closure")
    if _stable_inventory(folder) != inventory:
        raise PortableBuildError("portable folder changed during ZIP verification")
    return archived.archive_bytes, archived.archive_sha256


def _receipt_object(
    snapshot: Any,
    identity: dict[str, str],
    folder_name: str,
    archive_name: str,
    archive_bytes: int,
    archive_sha256: str,
    inventory: _TreeInventory,
) -> dict[str, Any]:
    return {
        "portable_distribution_schema": _RECEIPT_SCHEMA,
        "product_name": identity["__product_name__"],
        "sector_version": identity["__version__"],
        "built_at_utc": snapshot.evidence.source_committed_at_utc,
        "unsigned_status": UNSIGNED_STATUS,
        **_source_object(snapshot),
        "folder_name": folder_name,
        "folder_file_count": len(inventory.files),
        "folder_total_bytes": inventory.total_bytes,
        "folder_inventory_sha256": inventory.sha256,
        "archive_name": archive_name,
        "archive_bytes": archive_bytes,
        "archive_sha256": archive_sha256,
    }


def _artifact_paths(output: Path, folder_name: str) -> tuple[Path, Path, Path, Path]:
    folder = output / folder_name
    archive = output / f"{folder_name}.zip"
    sidecar = output / f"{folder_name}.zip.sha256"
    receipt = output / f"{folder_name}.portable-distribution.json"
    return folder, archive, sidecar, receipt


def _require_output_boundary(root: Path, output: Path) -> tuple[Path, Path]:
    source = _lexical_source_root(root)
    try:
        resolved_source = source.resolve(strict=True)
    except OSError as exc:
        raise PortableBuildError("portable source root does not exist") from exc
    lexical_output = Path(os.path.abspath(output))
    if os.path.lexists(lexical_output):
        raise PortableBuildError(f"portable output already exists: {lexical_output}")
    resolved_output = lexical_output.resolve(strict=False)
    if (
        resolved_output == resolved_source
        or resolved_source in resolved_output.parents
    ):
        raise PortableBuildError("portable output must be outside the source root")
    try:
        lexical_output.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PortableBuildError("cannot create portable output parent") from exc
    return source, lexical_output


def _assemble_folder(
    package: Path,
    source_identity_path: Path,
    folder: Path,
    snapshot: Any,
    identity: dict[str, str],
) -> _TreeInventory:
    _copy_verified_tree(package, folder)
    additions = {
        "README-PORTABLE.txt": _readme(snapshot, identity),
        "LICENSE": _read_regular_file(package / "LICENSE.txt", "packaged licence"),
        "sector_build_info.json": _read_regular_file(
            package / "_internal" / "sector" / "sector_build_info.json",
            "packaged build identity",
        ),
        "source-identity.json": _read_regular_file(
            source_identity_path, "exact-build source identity"
        ),
    }
    for relative, payload in additions.items():
        _write_new(folder / relative, payload, f"portable metadata {relative}")
    payload_inventory = _stable_inventory(folder)
    _write_new(
        folder / "package_manifest.json",
        _canonical_json(_portable_manifest(snapshot, identity, payload_inventory)),
        "portable package manifest",
    )
    sums_inventory = _stable_inventory(folder)
    _write_new(
        folder / "SHA256SUMS.txt",
        _sha256_sums(sums_inventory.files),
        "portable folder SHA-256 list",
    )
    return _stable_inventory(folder)


def _verify_folder_metadata(
    folder: Path,
    snapshot: Any,
    identity: dict[str, str],
    inventory: _TreeInventory,
) -> None:
    records = _record_map(inventory)
    required = {
        "Sector.exe",
        "README-PORTABLE.txt",
        "LICENSE",
        "LICENSE.txt",
        "THIRD_PARTY_NOTICES.txt",
        "sector_build_info.json",
        "source-identity.json",
        "package_manifest.json",
        "SHA256SUMS.txt",
        "_internal/sector/sector_build_info.json",
    }
    if not required.issubset(records):
        raise PortableBuildError("portable folder is missing required files")
    if _pe_unsigned_status(folder / "Sector.exe") != UNSIGNED_STATUS:
        raise PortableBuildError("portable executable unsigned status differs")
    if _read_regular_file(folder / "LICENSE", "portable LICENSE") != _read_regular_file(
        folder / "LICENSE.txt", "packaged LICENSE.txt"
    ):
        raise PortableBuildError("portable licence copies differ")
    if _read_regular_file(
        folder / "sector_build_info.json", "portable build identity"
    ) != _read_regular_file(
        folder / "_internal" / "sector" / "sector_build_info.json",
        "internal build identity",
    ):
        raise PortableBuildError("portable build identity copies differ")
    if _read_regular_file(folder / "README-PORTABLE.txt", "portable README") != _readme(
        snapshot, identity
    ):
        raise PortableBuildError("portable README differs from the unsigned contract")

    manifest, _raw = _read_json(folder / "package_manifest.json", "portable package manifest")
    payload_records = tuple(
        record
        for record in inventory.files
        if record.path not in {"package_manifest.json", "SHA256SUMS.txt"}
    )
    expected_manifest = _portable_manifest(
        snapshot,
        identity,
        _TreeInventory(
            payload_records,
            inventory.directories,
            sum(record.bytes for record in payload_records),
            _inventory_digest(payload_records),
        ),
    )
    if manifest != expected_manifest:
        raise PortableBuildError("portable package manifest differs from the folder closure")

    sum_records = tuple(
        record for record in inventory.files if record.path != "SHA256SUMS.txt"
    )
    if _read_regular_file(folder / "SHA256SUMS.txt", "portable SHA-256 list") != _sha256_sums(sum_records):
        raise PortableBuildError("portable SHA-256 list differs from the folder closure")


def _top_level_distribution(output: Path, folder_name: str) -> None:
    before = _require_directory(output, "portable distribution output")
    expected = {
        folder_name: "directory",
        f"{folder_name}.zip": "file",
        f"{folder_name}.zip.sha256": "file",
        f"{folder_name}.portable-distribution.json": "file",
    }
    actual: dict[str, str] = {}
    registry: dict[str, str] = {}
    try:
        entries: list[os.DirEntry[str]] = []
        with os.scandir(output) as iterator:
            for entry in iterator:
                if len(entries) >= MAX_DISTRIBUTION_TOP_LEVEL_ENTRIES:
                    raise PortableBuildError(
                        "portable distribution exceeds the top-level path limit"
                    )
                entries.append(entry)
    except PortableBuildError:
        raise
    except OSError as exc:
        raise PortableBuildError("cannot inspect portable distribution output") from exc
    for entry in entries:
        parts = _validate_relative_path(entry.name)
        try:
            status = entry.stat(follow_symlinks=False)
        except OSError as exc:
            raise PortableBuildError(
                f"cannot inspect portable distribution entry: {entry.name}"
            ) from exc
        if entry.is_symlink() or _is_reparse(status):
            raise PortableBuildError("portable distribution contains a link or reparse point")
        kind = "directory" if stat.S_ISDIR(status.st_mode) else "file" if stat.S_ISREG(status.st_mode) else "special"
        if kind == "special":
            raise PortableBuildError("portable distribution contains a special entry")
        _register_path(registry, parts, kind)
        actual[entry.name] = kind
    if actual != expected:
        raise PortableBuildError("portable distribution top-level inventory differs")
    after = _require_directory(output, "portable distribution output")
    if _status_signature(before) != _status_signature(after):
        raise PortableBuildError(
            "portable distribution output changed during inventory"
        )


def verify_portable_distribution(
    root: Path, source_revision: str, output: Path
) -> PortableBuildEvidence:
    """Verify a staged or published portable folder, ZIP, sidecar, and receipt."""
    source = _lexical_source_root(root)
    output = Path(os.path.abspath(output))
    snapshot, identity = _snapshot_identity(source, source_revision)
    folder_name = _portable_name(identity["__version__"])
    folder, archive, sidecar, receipt = _artifact_paths(output, folder_name)
    _top_level_distribution(output, folder_name)
    inventory = _stable_inventory(folder)
    try:
        _RELEASE.verify_package(
            source, folder, source_revision, folder / "source-identity.json"
        )
    except ReleaseVerificationError as exc:
        raise PortableBuildError(f"portable exact-package verification failed: {exc}") from exc
    _verify_folder_metadata(folder, snapshot, identity, inventory)
    timestamp = _zip_time(snapshot.evidence.source_committer_epoch)
    archive_bytes, archive_sha256 = _verify_archive(
        archive, folder, folder_name, inventory, timestamp
    )
    expected_sidecar = f"{archive_sha256}  {archive.name}\n".encode("ascii")
    if _read_regular_file(sidecar, "portable archive SHA-256 sidecar") != expected_sidecar:
        raise PortableBuildError("portable archive SHA-256 sidecar differs")
    receipt_value, _raw_receipt = _read_json(
        receipt, "portable distribution receipt"
    )
    expected_receipt = _receipt_object(
        snapshot,
        identity,
        folder_name,
        archive.name,
        archive_bytes,
        archive_sha256,
        inventory,
    )
    if receipt_value != expected_receipt:
        raise PortableBuildError("portable distribution receipt differs")
    return PortableBuildEvidence(
        source_revision=snapshot.evidence.source_revision,
        source_tree=snapshot.evidence.source_tree,
        sector_version=identity["__version__"],
        unsigned_status=UNSIGNED_STATUS,
        folder_name=folder_name,
        archive_name=archive.name,
        archive_sha256=archive_sha256,
        folder_file_count=len(inventory.files),
        folder_total_bytes=inventory.total_bytes,
        folder_inventory_sha256=inventory.sha256,
        output=output,
        folder=folder,
        archive=archive,
        sidecar=sidecar,
        receipt=receipt,
    )


def build_portable_windows(
    root: Path,
    source_revision: str,
    output: Path,
    *,
    runner: Callable[[Any], None] | None = None,
) -> PortableBuildEvidence:
    """Build into private staging and publish one create-only verified distribution."""
    source, output = _require_output_boundary(root, output)
    try:
        resolved_source = source.resolve(strict=True)
    except OSError as exc:
        raise PortableBuildError("portable source root changed before staging") from exc
    snapshot, identity = _snapshot_identity(source, source_revision)
    folder_name = _portable_name(identity["__version__"])
    try:
        with tempfile.TemporaryDirectory(
            prefix=f".{output.name}.portable-", dir=output.parent
        ) as temporary:
            temporary_root = Path(temporary)
            resolved_temporary = temporary_root.resolve(strict=True)
            if (
                resolved_source == resolved_temporary
                or resolved_source in resolved_temporary.parents
            ):
                raise PortableBuildError("portable staging root is inside the source root")
            plan = prepare_exact_build(
                source, source_revision, temporary_root / "exact-build"
            )
            evidence = (
                execute_exact_build(plan)
                if runner is None
                else execute_exact_build(plan, runner=runner)
            )
            try:
                _RELEASE.verify_package(
                    source,
                    evidence.package_root,
                    source_revision,
                    evidence.source_identity_path,
                )
            except ReleaseVerificationError as exc:
                raise PortableBuildError(
                    f"exact package verification failed: {exc}"
                ) from exc
            if _pe_unsigned_status(evidence.package_root / "Sector.exe") != UNSIGNED_STATUS:
                raise PortableBuildError("exact package unsigned status differs")

            publish = temporary_root / "publish"
            publish.mkdir()
            folder, archive, sidecar, receipt = _artifact_paths(publish, folder_name)
            inventory = _assemble_folder(
                evidence.package_root,
                evidence.source_identity_path,
                folder,
                snapshot,
                identity,
            )
            _verify_folder_metadata(folder, snapshot, identity, inventory)
            timestamp = _zip_time(snapshot.evidence.source_committer_epoch)
            _write_archive(folder, folder_name, inventory, archive, timestamp)
            archive_bytes, archive_sha256 = _verify_archive(
                archive, folder, folder_name, inventory, timestamp
            )
            _write_new(
                sidecar,
                f"{archive_sha256}  {archive.name}\n".encode("ascii"),
                "portable archive SHA-256 sidecar",
            )
            _write_new(
                receipt,
                _canonical_json(
                    _receipt_object(
                        snapshot,
                        identity,
                        folder_name,
                        archive.name,
                        archive_bytes,
                        archive_sha256,
                        inventory,
                    )
                ),
                "portable distribution receipt",
            )
            staged = verify_portable_distribution(source, source_revision, publish)
            if os.path.lexists(output):
                raise PortableBuildError(f"portable output already exists: {output}")
            try:
                os.rename(publish, output)
            except OSError as exc:
                raise PortableBuildError("cannot publish create-only portable output") from exc
            return PortableBuildEvidence(
                **{
                    **asdict(staged),
                    "output": output,
                    "folder": output / folder.name,
                    "archive": output / archive.name,
                    "sidecar": output / sidecar.name,
                    "receipt": output / receipt.name,
                }
            )
    except PortableBuildError:
        raise
    except ExactBuildError as exc:
        raise PortableBuildError(f"portable exact-source build failed: {exc}") from exc
    except OSError as exc:
        raise PortableBuildError("portable build staging failed") from exc


def safe_extract_portable_archive(
    archive: Path,
    output: Path,
    *,
    expected_sha256: str | None = None,
) -> Path:
    """Safely extract one canonical portable ZIP into a new destination."""
    archive = Path(os.path.abspath(archive))
    output = Path(os.path.abspath(output))
    if os.path.lexists(output):
        raise PortableBuildError(f"portable extraction output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    authenticated = _archive_inventory(archive)
    if expected_sha256 is not None and (
        len(expected_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha256)
        or authenticated.archive_sha256 != expected_sha256
    ):
        raise PortableBuildError(
            "portable archive differs from the verified distribution digest"
        )
    root_name = authenticated.root_name
    try:
        with tempfile.TemporaryDirectory(
            prefix=f".{output.name}.extract-", dir=output.parent
        ) as temporary:
            publish = Path(temporary) / "publish"
            publish.mkdir()
            before = _lstat(archive, "portable archive")
            if (
                stat.S_ISLNK(before.st_mode)
                or _is_reparse(before)
                or not stat.S_ISREG(before.st_mode)
            ):
                raise PortableBuildError("portable archive is not an ordinary file")
            try:
                with archive.open("rb") as raw_stream:
                    opened_before = os.fstat(raw_stream.fileno())
                    if _status_signature(opened_before) != _status_signature(before):
                        raise PortableBuildError(
                            "portable archive changed while extraction opened it"
                        )
                    preflight = _preflight_zip_stream(
                        raw_stream, expected_size=before.st_size
                    )
                    if preflight.member_count != len(authenticated.files):
                        raise PortableBuildError(
                            "portable archive member count changed before extraction"
                        )
                    raw_stream.seek(0)
                    with zipfile.ZipFile(raw_stream, "r") as bundle:
                        infos = bundle.infolist()
                        if bundle.comment or len(infos) != len(authenticated.files):
                            raise PortableBuildError(
                                "portable archive inventory changed before extraction"
                            )
                        entries: list[
                            tuple[zipfile.ZipInfo, str, int | None]
                        ] = []
                        for info, record in zip(infos, authenticated.files):
                            expected_name = f"{root_name}/{record.path}"
                            if info.filename != expected_name:
                                raise PortableBuildError(
                                    "portable archive metadata changed before extraction"
                                )
                            entries.append((info, record.path, record.bytes))
                        _exact_zip_boundaries(
                            raw_stream, entries, authenticated.timestamp
                        )
                        for (info, _relative, _expected_size), record in zip(
                            entries, authenticated.files
                        ):
                            target = publish / root_name / Path(
                                *PurePosixPath(record.path).parts
                            )
                            target.parent.mkdir(parents=True, exist_ok=True)
                            digest = hashlib.sha256()
                            count = 0
                            with bundle.open(info, "r") as source, target.open(
                                "xb"
                            ) as destination:
                                while True:
                                    block = source.read(_READ_BLOCK)
                                    if not block:
                                        break
                                    count += len(block)
                                    if count > MAX_PORTABLE_FILE_BYTES:
                                        raise PortableBuildError(
                                            "portable ZIP entry exceeds the extraction limit"
                                        )
                                    digest.update(block)
                                    destination.write(block)
                            if (
                                count != record.bytes
                                or digest.hexdigest() != record.sha256
                            ):
                                raise PortableBuildError(
                                    f"portable ZIP entry changed during extraction: {record.path}"
                                )
                    raw_stream.seek(0)
                    archive_digest = hashlib.sha256()
                    archive_bytes = 0
                    while True:
                        block = raw_stream.read(_READ_BLOCK)
                        if not block:
                            break
                        archive_bytes += len(block)
                        if archive_bytes > MAX_ARCHIVE_BYTES:
                            raise PortableBuildError(
                                "portable archive exceeds the extraction limit"
                            )
                        archive_digest.update(block)
                    opened_after = os.fstat(raw_stream.fileno())
                after = _lstat(archive, "portable archive")
            except PortableBuildError:
                raise
            except (
                OSError,
                RuntimeError,
                UnicodeError,
                zipfile.BadZipFile,
            ) as exc:
                raise PortableBuildError("cannot safely extract portable ZIP") from exc
            signatures = (before, opened_before, opened_after, after)
            if any(
                _status_signature(left) != _status_signature(right)
                for left, right in itertools.pairwise(signatures)
            ):
                raise PortableBuildError("portable archive changed during extraction")
            if (
                archive_bytes != authenticated.archive_bytes
                or archive_digest.hexdigest() != authenticated.archive_sha256
            ):
                raise PortableBuildError(
                    "portable archive bytes changed between authentication and extraction"
                )
            extracted = _stable_inventory(publish / root_name)
            if extracted.files != authenticated.files:
                raise PortableBuildError(
                    "extracted portable bytes differ from the authenticated archive"
                )
            if os.path.lexists(output):
                raise PortableBuildError(
                    f"portable extraction output already exists: {output}"
                )
            os.rename(publish, output)
            return output / root_name
    except PortableBuildError:
        raise
    except OSError as exc:
        raise PortableBuildError("cannot publish safely extracted portable ZIP") from exc


def _compare_file_bytes(
    first: Path,
    second: Path,
    relative: str,
    expected: _FileRecord,
    *,
    limit: int = MAX_PORTABLE_FILE_BYTES,
) -> None:
    left = first.joinpath(*PurePosixPath(relative).parts)
    right = second.joinpath(*PurePosixPath(relative).parts)
    left_before = _lstat(left, f"first portable file {relative}")
    right_before = _lstat(right, f"second portable file {relative}")
    for status in (left_before, right_before):
        if (
            stat.S_ISLNK(status.st_mode)
            or _is_reparse(status)
            or not stat.S_ISREG(status.st_mode)
            or status.st_size != expected.bytes
        ):
            raise PortableBuildError(
                f"portable comparison input is not an ordinary expected file: {relative}"
            )
    count = 0
    try:
        with left.open("rb") as left_stream, right.open("rb") as right_stream:
            left_opened_before = os.fstat(left_stream.fileno())
            right_opened_before = os.fstat(right_stream.fileno())
            if (
                _status_signature(left_opened_before)
                != _status_signature(left_before)
                or _status_signature(right_opened_before)
                != _status_signature(right_before)
            ):
                raise PortableBuildError(
                    f"portable comparison input changed while opened: {relative}"
                )
            while True:
                left_block = left_stream.read(_READ_BLOCK)
                right_block = right_stream.read(_READ_BLOCK)
                if left_block != right_block:
                    raise PortableBuildError(
                        f"portable distributions differ: {relative}"
                    )
                if not left_block:
                    break
                count += len(left_block)
                if count > limit:
                    raise PortableBuildError(
                        f"portable comparison input exceeds the limit: {relative}"
                    )
            left_opened_after = os.fstat(left_stream.fileno())
            right_opened_after = os.fstat(right_stream.fileno())
        left_after = _lstat(left, f"first portable file {relative}")
        right_after = _lstat(right, f"second portable file {relative}")
    except PortableBuildError:
        raise
    except OSError as exc:
        raise PortableBuildError(
            f"cannot compare portable distribution file: {relative}"
        ) from exc
    if count != expected.bytes:
        raise PortableBuildError(
            f"portable comparison byte count differs: {relative}"
        )
    left_signatures = (
        left_before,
        left_opened_before,
        left_opened_after,
        left_after,
    )
    right_signatures = (
        right_before,
        right_opened_before,
        right_opened_after,
        right_after,
    )
    if any(
        _status_signature(previous) != _status_signature(current)
        for signatures in (left_signatures, right_signatures)
        for previous, current in itertools.pairwise(signatures)
    ):
        raise PortableBuildError(
            f"portable comparison input changed while read: {relative}"
        )


def compare_portable_distributions(
    first_output: Path, second_output: Path, evidence_path: Path
) -> PortableComparisonEvidence:
    """Prove two complete final distribution trees are byte-identical."""
    first = Path(os.path.abspath(first_output))
    second = Path(os.path.abspath(second_output))
    evidence_path = Path(os.path.abspath(evidence_path))
    if first == second:
        raise PortableBuildError("portable comparison requires independent outputs")
    try:
        resolved_first = first.resolve(strict=True)
        resolved_second = second.resolve(strict=True)
    except OSError as exc:
        raise PortableBuildError("portable comparison input does not exist") from exc
    resolved_evidence = evidence_path.resolve(strict=False)
    if any(
        resolved_evidence == root or root in resolved_evidence.parents
        for root in (resolved_first, resolved_second)
    ):
        raise PortableBuildError(
            "portable comparison evidence must be outside both distribution roots"
        )
    if os.path.lexists(evidence_path):
        raise PortableBuildError(f"portable comparison evidence already exists: {evidence_path}")
    try:
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PortableBuildError("cannot create portable comparison evidence parent") from exc
    _require_directory(
        evidence_path.parent, "portable comparison evidence parent"
    )
    first_inventory = _stable_inventory(
        first,
        total_limit=MAX_DISTRIBUTION_TOTAL_BYTES,
        allow_top_level_archive=True,
    )
    second_inventory = _stable_inventory(
        second,
        total_limit=MAX_DISTRIBUTION_TOTAL_BYTES,
        allow_top_level_archive=True,
    )
    if first_inventory != second_inventory:
        raise PortableBuildError("portable distribution inventories differ")
    for record in first_inventory.files:
        _compare_file_bytes(
            first,
            second,
            record.path,
            record,
            limit=_distribution_file_limit(record.path),
        )
    if (
        _stable_inventory(
            first,
            total_limit=MAX_DISTRIBUTION_TOTAL_BYTES,
            allow_top_level_archive=True,
        )
        != first_inventory
        or _stable_inventory(
            second,
            total_limit=MAX_DISTRIBUTION_TOTAL_BYTES,
            allow_top_level_archive=True,
        )
        != second_inventory
    ):
        raise PortableBuildError("portable distribution changed during comparison")
    receipts = [
        record.path
        for record in first_inventory.files
        if record.path.endswith(".portable-distribution.json")
    ]
    if len(receipts) != 1 or "/" in receipts[0]:
        raise PortableBuildError("portable comparison cannot identify one receipt")
    receipt, _raw = _read_json(first / receipts[0], "portable distribution receipt")
    required = {
        "source_revision",
        "source_tree",
        "sector_version",
        "unsigned_status",
        "folder_name",
    }
    if not required.issubset(receipt) or receipt["unsigned_status"] != UNSIGNED_STATUS:
        raise PortableBuildError("portable comparison receipt identity is invalid")
    value = {
        "portable_comparison_schema": _COMPARISON_SCHEMA,
        "result": "byte-identical",
        "source_revision": receipt["source_revision"],
        "source_tree": receipt["source_tree"],
        "sector_version": receipt["sector_version"],
        "unsigned_status": receipt["unsigned_status"],
        "artifact_name": receipt["folder_name"],
        "distribution_file_count": len(first_inventory.files),
        "distribution_total_bytes": first_inventory.total_bytes,
        "distribution_inventory_sha256": first_inventory.sha256,
    }
    _write_new(evidence_path, _canonical_json(value), "portable comparison evidence")
    return PortableComparisonEvidence(
        source_revision=str(value["source_revision"]),
        source_tree=str(value["source_tree"]),
        sector_version=str(value["sector_version"]),
        unsigned_status=str(value["unsigned_status"]),
        artifact_name=str(value["artifact_name"]),
        distribution_file_count=int(value["distribution_file_count"]),
        distribution_total_bytes=int(value["distribution_total_bytes"]),
        distribution_inventory_sha256=str(value["distribution_inventory_sha256"]),
        evidence_path=evidence_path,
    )


def _display(value: PortableBuildEvidence | PortableComparisonEvidence) -> dict[str, Any]:
    result = asdict(value)
    return {key: str(item) if isinstance(item, Path) else item for key, item in result.items()}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--source-revision")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("FIRST", "SECOND"))
    parser.add_argument("--comparison-evidence", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.compare is not None:
            if (
                arguments.root is not None
                or arguments.source_revision is not None
                or arguments.output is not None
                or arguments.verify_only
                or arguments.comparison_evidence is None
            ):
                raise PortableBuildError(
                    "comparison requires only --compare and --comparison-evidence"
                )
            evidence: PortableBuildEvidence | PortableComparisonEvidence = (
                compare_portable_distributions(
                    arguments.compare[0],
                    arguments.compare[1],
                    arguments.comparison_evidence,
                )
            )
        else:
            if (
                arguments.root is None
                or arguments.source_revision is None
                or arguments.output is None
                or arguments.comparison_evidence is not None
            ):
                raise PortableBuildError(
                    "build and verification require --root, --source-revision, and --output"
                )
            action = verify_portable_distribution if arguments.verify_only else build_portable_windows
            evidence = action(
                arguments.root, arguments.source_revision, arguments.output
            )
    except PortableBuildError as exc:
        print(f"portable Windows distribution failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(_display(evidence), ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
