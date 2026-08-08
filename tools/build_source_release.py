"""Build and verify a provenance-bearing source/application release ZIP."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import io
import json
import os
import re
import sys
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
snapshot_commit = _EXPORTER.snapshot_commit

_MANIFEST_PATH = PurePosixPath("sector/sector_build_info.json")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+$")
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
    value: dict[str, str | int] = {
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
    }
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("ascii")


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
