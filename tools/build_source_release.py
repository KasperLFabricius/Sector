"""Build and verify a provenance-bearing source/application release ZIP."""

from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import importlib.util
import io
import json
import os
import re
import sys
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


def _load_exporter():
    path = Path(__file__).resolve().with_name("export_commit_tree.py")
    specification = importlib.util.spec_from_file_location(
        "sector_source_release_commit_exporter", path
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
ExportEvidence = _EXPORTER.ExportEvidence
SnapshotFile = _EXPORTER.SnapshotFile
snapshot_commit = _EXPORTER.snapshot_commit

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
        return snapshot_commit(repository, source_revision)
    except CommitTreeError as exc:
        raise SourceReleaseError(
            f"cannot authenticate exact source commit: {exc}"
        ) from exc


def _snapshot_file(snapshot: CommitSnapshot, path: str) -> bytes:
    matches = [item.payload for item in snapshot.files if item.path == path]
    if len(matches) != 1:
        raise SourceReleaseError(f"exact source file is missing or duplicated: {path}")
    return matches[0]


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
    if set(values) != _IDENTITY_NAMES or _VERSION.fullmatch(values["__version__"]) is None:
        raise SourceReleaseError("Sector source identity is incomplete or invalid")
    return values


def _manifest(snapshot: CommitSnapshot, identity: dict[str, str]) -> bytes:
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
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("ascii")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SourceReleaseError(f"source manifest contains duplicate key: {key}")
        result[key] = value
    return result


def _read_manifest(root: Path) -> dict[str, object]:
    path = root.joinpath(*_MANIFEST_PATH.parts)
    if path.is_symlink() or not path.is_file():
        raise SourceReleaseError("source release provenance manifest is missing")
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
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
    return value


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


def _source_records(value: dict[str, object]) -> list[dict[str, object]]:
    raw_records = value["source_files"]
    if not isinstance(raw_records, list) or not raw_records:
        raise SourceReleaseError("source manifest file inventory is invalid")
    records: list[dict[str, object]] = []
    path_kinds: dict[str, str] = {}
    prior_path: str | None = None
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
        return _EXPORTER._object_digest("tree", payload)

    return digest(root)


def _source_paths(root: Path) -> tuple[dict[str, Path], set[str]]:
    files: dict[str, Path] = {}
    directories: set[str] = set()
    pending: list[tuple[Path, tuple[str, ...]]] = [(root, ())]
    while pending:
        directory, parts = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            raise SourceReleaseError(f"cannot inventory source release directory: {exc}") from exc
        for entry in entries:
            child_parts = (*parts, entry.name)
            relative = PurePosixPath(*child_parts).as_posix()
            path = Path(entry.path)
            if entry.is_symlink() or (
                hasattr(path, "is_junction") and path.is_junction()
            ):
                raise SourceReleaseError(f"source release contains a linked path: {relative}")
            if entry.is_dir(follow_symlinks=False):
                directories.add(relative)
                pending.append((path, child_parts))
            elif entry.is_file(follow_symlinks=False):
                files[relative] = path
            else:
                raise SourceReleaseError(f"source release contains a special path: {relative}")
    return files, directories


def verify_source_release_directory(
    root: Path, expected_revision: str | None = None
) -> CommitSnapshot:
    """Authenticate one extracted source release without requiring Git metadata."""
    try:
        root = root.resolve(strict=True)
    except OSError as exc:
        raise SourceReleaseError("source release directory does not exist") from exc
    if not root.is_dir() or root.is_symlink():
        raise SourceReleaseError("source release root is not a regular directory")
    manifest = _read_manifest(root)
    revision = _manifest_text(manifest, "source_revision")
    tree = _manifest_text(manifest, "source_tree")
    inventory = _manifest_text(manifest, "source_inventory_sha256")
    if _OBJECT_ID.fullmatch(revision) is None or _OBJECT_ID.fullmatch(tree) is None:
        raise SourceReleaseError("source manifest commit identity is invalid")
    if _SHA256.fullmatch(inventory) is None:
        raise SourceReleaseError("source manifest inventory identity is invalid")
    if expected_revision is not None and revision != expected_revision:
        raise SourceReleaseError("source manifest revision differs from the requested revision")
    try:
        commit_payload = base64.b64decode(
            _manifest_text(manifest, "source_commit_payload_base64"), validate=True
        )
        parsed_commit = _EXPORTER._parse_commit(commit_payload)
    except (ValueError, CommitTreeError) as exc:
        raise SourceReleaseError("source manifest commit object is invalid") from exc
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

    records = _source_records(manifest)
    if _tree_identity(records) != tree:
        raise SourceReleaseError("source manifest file inventory does not match its Git tree")
    if len(records) != _manifest_integer(manifest, "source_file_count"):
        raise SourceReleaseError("source manifest file count differs")
    if sum(int(item["bytes"]) for item in records) != _manifest_integer(
        manifest, "source_total_bytes"
    ):
        raise SourceReleaseError("source manifest total byte count differs")
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
        try:
            payload = actual_files[path].read_bytes()
        except OSError as exc:
            raise SourceReleaseError(f"cannot read source release file: {path}") from exc
        if len(payload) != item["bytes"] or _EXPORTER._object_digest("blob", payload) != item["object_id"]:
            raise SourceReleaseError(f"source release file differs from its manifest: {path}")
        snapshot_files.append(
            SnapshotFile(str(item["mode"]), path, str(item["object_id"]), payload)
        )
    evidence = ExportEvidence(
        revision,
        tree,
        epoch,
        committed_at,
        len(records),
        sum(len(item.payload) for item in snapshot_files),
        inventory,
    )
    return CommitSnapshot(evidence, commit_payload, tuple(snapshot_files))


def materialize_source_release(
    root: Path, expected_revision: str, output: Path
) -> ExportEvidence:
    """Verify and copy an extracted release into one new isolated source tree."""
    if os.path.lexists(output):
        raise SourceReleaseError(f"source materialization output already exists: {output}")
    resolved_root = root.resolve(strict=True)
    lexical_output = Path(os.path.abspath(output))
    if lexical_output == resolved_root or resolved_root in lexical_output.parents:
        raise SourceReleaseError("source materialization output cannot be inside the release")
    snapshot = verify_source_release_directory(resolved_root, expected_revision)
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
    identity = _source_identity(snapshot)
    prefix = f"Sector-v{identity['__version__']}"
    if any(
        item.path.casefold().endswith(_BINARY_SUFFIXES) for item in snapshot.files
    ):
        raise SourceReleaseError("source release commit contains a Windows binary")
    if any(PurePosixPath(item.path) == _MANIFEST_PATH for item in snapshot.files):
        raise SourceReleaseError("generated source-release manifest path is tracked")
    entries = [
        (f"{prefix}/{item.path}", item.mode, item.payload)
        for item in snapshot.files
    ]
    entries.append(
        (
            f"{prefix}/{_MANIFEST_PATH.as_posix()}",
            "100644",
            _manifest(snapshot, identity),
        )
    )
    return prefix, sorted(entries, key=lambda item: item[0])


def _zip_info(name: str, mode: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=_ZIP_TIME)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = (0o100755 if mode == "100755" else 0o100644) << 16
    return info


def _canonical_archive(entries: list[tuple[str, str, bytes]]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as bundle:
        for name, mode, payload in entries:
            bundle.writestr(_zip_info(name, mode), payload)
    return stream.getvalue()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _evidence(
    snapshot: CommitSnapshot,
    version: str,
    archive: Path,
    entries: int,
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
        archive_bytes=archive.stat().st_size,
        archive_sha256=_sha256(archive),
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
    try:
        archive_bytes = archive.read_bytes()
    except OSError as exc:
        raise SourceReleaseError(f"cannot read source release archive: {exc}") from exc
    if archive_bytes != _canonical_archive(expected):
        raise SourceReleaseError(
            "complete source archive bytes differ from the canonical release"
        )
    try:
        with zipfile.ZipFile(archive, "r") as bundle:
            infos = bundle.infolist()
            names = [item.filename for item in infos]
            if bundle.comment:
                raise SourceReleaseError("source archive comment is not canonical")
            if names != list(expected_by_name):
                raise SourceReleaseError(
                    "source archive inventory differs from the exact commit contract"
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
                if bundle.read(info) != payload:
                    raise SourceReleaseError(
                        f"source archive bytes differ: {info.filename}"
                    )
    except (OSError, zipfile.BadZipFile) as exc:
        raise SourceReleaseError(f"cannot read source release archive: {exc}") from exc
    identity = _source_identity(snapshot)
    marker = f"{prefix}/{_MANIFEST_PATH.as_posix()}"
    if marker not in expected_by_name:
        raise SourceReleaseError("source release provenance manifest is missing")
    return _evidence(snapshot, identity["__version__"], archive, len(expected))


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
            stream.write(_canonical_archive(entries))
    except OSError as exc:
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
