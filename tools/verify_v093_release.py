"""Assemble and verify the exact unsigned Sector v0.93 draft release assets."""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import importlib.util
import itertools
import json
import os
import re
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

SECTOR_VERSION = "0.93"
PRODUCT_NAME = "Sector"
WORKFLOW_NAME = "Sector QA"
UNSIGNED_STATUS = "verified-pe-certificate-table-absent"
QA_EVIDENCE_SCHEMA = 1
RELEASE_RECEIPT_SCHEMA = 1

SOURCE_ARCHIVE_NAME = "Sector-v0.93-source.zip"
SOURCE_SIDECAR_NAME = f"{SOURCE_ARCHIVE_NAME}.sha256"
PORTABLE_ARCHIVE_NAME = "Sector-v0.93-windows-portable-unsigned.zip"
PORTABLE_SIDECAR_NAME = f"{PORTABLE_ARCHIVE_NAME}.sha256"
PORTABLE_RECEIPT_NAME = (
    "Sector-v0.93-windows-portable-unsigned.portable-distribution.json"
)
RELEASE_RECEIPT_NAME = "Sector-v0.93-release-qa-receipt.json"
CHECKSUMS_NAME = "SHA256SUMS.txt"

RELEASE_ASSET_NAMES = (
    SOURCE_ARCHIVE_NAME,
    SOURCE_SIDECAR_NAME,
    PORTABLE_ARCHIVE_NAME,
    PORTABLE_SIDECAR_NAME,
    PORTABLE_RECEIPT_NAME,
    RELEASE_RECEIPT_NAME,
    CHECKSUMS_NAME,
)
_CHECKSUMMED_ASSET_NAMES = tuple(
    sorted(name for name in RELEASE_ASSET_NAMES if name != CHECKSUMS_NAME)
)
QA_JOB_NAMES = tuple(
    sorted(
        (
            "Full test and report gate",
            "Unsigned QA Windows package",
            "Unsigned portable producer A",
            "Unsigned portable producer B",
            "Compare immutable portable producers",
            "Isolated verified portable startup smoke",
            "Unsigned portable Windows distribution",
        )
    )
)

_OBJECT_ID = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_REPOSITORY = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,99})/"
    r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,99})$"
)
_READ_BLOCK = 1024 * 1024
_MAX_METADATA_BYTES = 16 * 1024 * 1024
_MAX_SOURCE_ARCHIVE_BYTES = 600 * 1024 * 1024
_MAX_PORTABLE_ARCHIVE_BYTES = 2_100_000_000
_MAX_RUN_ID = 2**63 - 1


def _load_sibling(filename: str, module_name: str) -> ModuleType:
    path = Path(__file__).resolve().with_name(filename)
    specification = importlib.util.spec_from_file_location(module_name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"cannot load required release module: {filename}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        specification.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


_SOURCE_RELEASE = _load_sibling(
    "build_source_release.py", "sector_v093_source_release"
)
_PORTABLE_RELEASE = _load_sibling(
    "build_portable_windows.py", "sector_v093_portable_release"
)
SourceReleaseError = _SOURCE_RELEASE.SourceReleaseError
PortableBuildError = _PORTABLE_RELEASE.PortableBuildError
build_source_release = _SOURCE_RELEASE.build_source_release
verify_source_release = _SOURCE_RELEASE.verify_source_release
verify_portable_distribution = _PORTABLE_RELEASE.verify_portable_distribution
safe_extract_portable_archive = _PORTABLE_RELEASE.safe_extract_portable_archive


class V093ReleaseError(RuntimeError):
    """The v0.93 release evidence or asset closure is unsafe or inconsistent."""


@dataclass(frozen=True)
class V093ReleaseEvidence:
    source_revision: str
    source_tree: str
    sector_version: str
    unsigned_status: str
    qa_run_id: int
    qa_run_attempt: int
    source_archive_sha256: str
    portable_archive_sha256: str
    asset_count: int
    assets_sha256: str
    output: Path


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("ascii")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise V093ReleaseError(f"JSON contains duplicate key: {key}")
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


def _lstat(path: Path, label: str) -> os.stat_result:
    try:
        return os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise V093ReleaseError(f"cannot inspect {label}") from exc


def _require_directory(path: Path, label: str) -> os.stat_result:
    status = _lstat(path, label)
    if stat.S_ISLNK(status.st_mode) or _is_reparse(status):
        raise V093ReleaseError(f"{label} is a linked or reparse path")
    if not stat.S_ISDIR(status.st_mode):
        raise V093ReleaseError(f"{label} is not an ordinary directory")
    return status


def _require_revision(source_revision: str) -> str:
    if _OBJECT_ID.fullmatch(source_revision) is None:
        raise V093ReleaseError("source revision must be one lowercase 40-hex object ID")
    return source_revision


def _read_regular_file(path: Path, label: str, *, limit: int) -> bytes:
    before = _lstat(path, label)
    if stat.S_ISLNK(before.st_mode) or _is_reparse(before):
        raise V093ReleaseError(f"{label} is a linked or reparse path")
    if not stat.S_ISREG(before.st_mode):
        raise V093ReleaseError(f"{label} is not an ordinary file")
    if before.st_size > limit:
        raise V093ReleaseError(f"{label} exceeds the release byte limit")
    chunks: list[bytes] = []
    count = 0
    try:
        with path.open("rb") as stream:
            opened_before = os.fstat(stream.fileno())
            if _status_signature(opened_before) != _status_signature(before):
                raise V093ReleaseError(f"{label} changed while it was opened")
            while True:
                block = stream.read(_READ_BLOCK)
                if not block:
                    break
                count += len(block)
                if count > limit:
                    raise V093ReleaseError(f"{label} exceeds the release byte limit")
                chunks.append(block)
            opened_after = os.fstat(stream.fileno())
        after = _lstat(path, label)
    except V093ReleaseError:
        raise
    except OSError as exc:
        raise V093ReleaseError(f"cannot read {label}") from exc
    signatures = (before, opened_before, opened_after, after)
    if any(
        _status_signature(left) != _status_signature(right)
        for left, right in itertools.pairwise(signatures)
    ):
        raise V093ReleaseError(f"{label} changed while it was read")
    if count != before.st_size:
        raise V093ReleaseError(f"{label} byte count changed while it was read")
    return b"".join(chunks)


def _hash_regular_file(path: Path, label: str, *, limit: int) -> tuple[int, str]:
    before = _lstat(path, label)
    if stat.S_ISLNK(before.st_mode) or _is_reparse(before):
        raise V093ReleaseError(f"{label} is a linked or reparse path")
    if not stat.S_ISREG(before.st_mode):
        raise V093ReleaseError(f"{label} is not an ordinary file")
    if before.st_size > limit:
        raise V093ReleaseError(f"{label} exceeds the release byte limit")
    digest = hashlib.sha256()
    count = 0
    try:
        with path.open("rb") as stream:
            opened_before = os.fstat(stream.fileno())
            if _status_signature(opened_before) != _status_signature(before):
                raise V093ReleaseError(f"{label} changed while it was opened")
            while True:
                block = stream.read(_READ_BLOCK)
                if not block:
                    break
                count += len(block)
                if count > limit:
                    raise V093ReleaseError(f"{label} exceeds the release byte limit")
                digest.update(block)
            opened_after = os.fstat(stream.fileno())
        after = _lstat(path, label)
    except V093ReleaseError:
        raise
    except OSError as exc:
        raise V093ReleaseError(f"cannot hash {label}") from exc
    signatures = (before, opened_before, opened_after, after)
    if any(
        _status_signature(left) != _status_signature(right)
        for left, right in itertools.pairwise(signatures)
    ):
        raise V093ReleaseError(f"{label} changed while it was hashed")
    if count != before.st_size:
        raise V093ReleaseError(f"{label} byte count changed while it was hashed")
    return count, digest.hexdigest()


def _write_new(path: Path, payload: bytes, label: str) -> None:
    try:
        with path.open("xb") as stream:
            stream.write(payload)
    except OSError as exc:
        raise V093ReleaseError(f"cannot write create-only {label}") from exc


def _copy_regular_file(
    source: Path,
    destination: Path,
    label: str,
    *,
    limit: int,
) -> tuple[int, str]:
    before = _lstat(source, label)
    if stat.S_ISLNK(before.st_mode) or _is_reparse(before):
        raise V093ReleaseError(f"{label} is a linked or reparse path")
    if not stat.S_ISREG(before.st_mode):
        raise V093ReleaseError(f"{label} is not an ordinary file")
    if before.st_size > limit:
        raise V093ReleaseError(f"{label} exceeds the release byte limit")
    digest = hashlib.sha256()
    count = 0
    try:
        with source.open("rb") as input_stream, destination.open("xb") as output_stream:
            opened_before = os.fstat(input_stream.fileno())
            if _status_signature(opened_before) != _status_signature(before):
                raise V093ReleaseError(f"{label} changed while it was opened")
            while True:
                block = input_stream.read(_READ_BLOCK)
                if not block:
                    break
                count += len(block)
                if count > limit:
                    raise V093ReleaseError(f"{label} exceeds the release byte limit")
                digest.update(block)
                output_stream.write(block)
            opened_after = os.fstat(input_stream.fileno())
        after = _lstat(source, label)
    except V093ReleaseError:
        raise
    except OSError as exc:
        raise V093ReleaseError(f"cannot copy {label}") from exc
    signatures = (before, opened_before, opened_after, after)
    if any(
        _status_signature(left) != _status_signature(right)
        for left, right in itertools.pairwise(signatures)
    ):
        raise V093ReleaseError(f"{label} changed while it was copied")
    if count != before.st_size:
        raise V093ReleaseError(f"{label} byte count changed while it was copied")
    copied_bytes, copied_sha256 = _hash_regular_file(
        destination, f"copied {label}", limit=limit
    )
    if copied_bytes != count or copied_sha256 != digest.hexdigest():
        raise V093ReleaseError(f"copied {label} differs from its authenticated source")
    return count, copied_sha256


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    raw = _read_regular_file(path, label, limit=_MAX_METADATA_BYTES)
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_unique_object)
    except V093ReleaseError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise V093ReleaseError(f"{label} is not canonical ASCII JSON") from exc
    if not isinstance(value, dict) or raw != _canonical_json(value):
        raise V093ReleaseError(f"{label} is not canonical ASCII JSON")
    return value, raw


def _positive_id(value: object, label: str) -> int:
    if type(value) is not int or not 0 < value <= _MAX_RUN_ID:
        raise V093ReleaseError(f"{label} must be a positive bounded integer")
    return value


def _expected_artifact_names(run_id: int, run_attempt: int) -> tuple[str, ...]:
    qualifier = f"{run_id}-{run_attempt}"
    return tuple(
        sorted(
            (
                f"sector-qa-evidence-{qualifier}",
                f"Sector-Windows-unsigned-QA-{qualifier}",
                f"sector-portable-producer-a-{qualifier}",
                f"sector-portable-producer-b-{qualifier}",
                f"sector-portable-comparison-{qualifier}",
                f"sector-portable-smoke-{qualifier}",
                f"Sector-Windows-portable-unsigned-QA-{qualifier}",
            )
        )
    )


def _validate_qa_evidence(
    value: dict[str, Any], source_revision: str
) -> dict[str, Any]:
    expected_keys = {
        "qa_evidence_schema",
        "repository",
        "head_repository",
        "workflow_name",
        "event",
        "head_branch",
        "head_sha",
        "run_id",
        "run_attempt",
        "conclusion",
        "jobs",
        "artifacts",
    }
    if (
        set(value) != expected_keys
        or type(value["qa_evidence_schema"]) is not int
        or value["qa_evidence_schema"] != QA_EVIDENCE_SCHEMA
    ):
        raise V093ReleaseError("QA evidence schema differs")
    repository = value["repository"]
    if not isinstance(repository, str) or _REPOSITORY.fullmatch(repository) is None:
        raise V093ReleaseError("QA repository identity is invalid")
    if value["head_repository"] != repository:
        raise V093ReleaseError("QA run is not from the source repository")
    fixed = {
        "workflow_name": WORKFLOW_NAME,
        "event": "push",
        "head_branch": "main",
        "head_sha": source_revision,
        "conclusion": "success",
    }
    if any(value[name] != expected for name, expected in fixed.items()):
        raise V093ReleaseError("QA workflow identity or successful main-push state differs")
    run_id = _positive_id(value["run_id"], "QA run ID")
    run_attempt = _positive_id(value["run_attempt"], "QA run attempt")

    jobs = value["jobs"]
    if not isinstance(jobs, list) or len(jobs) != len(QA_JOB_NAMES):
        raise V093ReleaseError("QA job inventory differs")
    job_names: list[str] = []
    job_ids: list[int] = []
    for item in jobs:
        if not isinstance(item, dict) or set(item) != {"name", "id", "conclusion"}:
            raise V093ReleaseError("QA job record schema differs")
        name = item["name"]
        if not isinstance(name, str) or item["conclusion"] != "success":
            raise V093ReleaseError("QA job is not an identified success")
        job_names.append(name)
        job_ids.append(_positive_id(item["id"], f"QA job ID for {name}"))
    if tuple(job_names) != QA_JOB_NAMES or len(set(job_ids)) != len(job_ids):
        raise V093ReleaseError("QA job inventory is not exact, canonical, and unique")

    artifacts = value["artifacts"]
    expected_artifacts = _expected_artifact_names(run_id, run_attempt)
    if not isinstance(artifacts, list) or len(artifacts) != len(expected_artifacts):
        raise V093ReleaseError("QA artifact inventory differs")
    artifact_names: list[str] = []
    artifact_ids: list[int] = []
    for item in artifacts:
        if not isinstance(item, dict) or set(item) != {
            "name",
            "id",
            "digest",
            "expired",
        }:
            raise V093ReleaseError("QA artifact record schema differs")
        name = item["name"]
        digest = item["digest"]
        if not isinstance(name, str) or name not in expected_artifacts:
            raise V093ReleaseError("QA artifact name differs")
        if not isinstance(digest, str) or _ARTIFACT_DIGEST.fullmatch(digest) is None:
            raise V093ReleaseError("QA artifact digest is missing or noncanonical")
        if item["expired"] is not False:
            raise V093ReleaseError("QA artifact is expired or has invalid expiry evidence")
        artifact_names.append(name)
        artifact_ids.append(_positive_id(item["id"], f"QA artifact ID for {name}"))
    if (
        tuple(artifact_names) != expected_artifacts
        or len(set(artifact_ids)) != len(artifact_ids)
    ):
        raise V093ReleaseError(
            "QA artifact inventory is not exact, canonical, and unique"
        )
    return value


def read_qa_evidence(path: Path, source_revision: str) -> dict[str, Any]:
    """Read one canonical, attempt-specific Sector QA metadata receipt."""
    value, _raw = _read_json(path, "QA metadata evidence")
    return _validate_qa_evidence(value, _require_revision(source_revision))


def _asset_limit(name: str) -> int:
    if name == SOURCE_ARCHIVE_NAME:
        return _MAX_SOURCE_ARCHIVE_BYTES
    if name == PORTABLE_ARCHIVE_NAME:
        return _MAX_PORTABLE_ARCHIVE_BYTES
    return _MAX_METADATA_BYTES


def _inventory_release_directory(output: Path) -> None:
    before = _require_directory(output, "v0.93 release asset directory")
    actual: set[str] = set()
    try:
        with os.scandir(output) as entries:
            for entry in entries:
                if len(actual) >= len(RELEASE_ASSET_NAMES):
                    raise V093ReleaseError("v0.93 release contains extra assets")
                status = entry.stat(follow_symlinks=False)
                if entry.is_symlink() or _is_reparse(status):
                    raise V093ReleaseError("v0.93 release contains a link or reparse path")
                if not stat.S_ISREG(status.st_mode):
                    raise V093ReleaseError("v0.93 release contains a non-file asset")
                actual.add(entry.name)
    except V093ReleaseError:
        raise
    except OSError as exc:
        raise V093ReleaseError("cannot inventory v0.93 release assets") from exc
    if actual != set(RELEASE_ASSET_NAMES):
        raise V093ReleaseError("v0.93 release asset inventory differs")
    after = _require_directory(output, "v0.93 release asset directory")
    if _status_signature(before) != _status_signature(after):
        raise V093ReleaseError("v0.93 release directory changed during inventory")


def _portable_release_evidence(
    root: Path,
    source_revision: str,
    archive: Path,
    sidecar: Path,
    receipt: Path,
) -> Any:
    archive_bytes, archive_sha256 = _hash_regular_file(
        archive, "v0.93 portable release archive", limit=_MAX_PORTABLE_ARCHIVE_BYTES
    )
    if archive_bytes <= 0:
        raise V093ReleaseError("v0.93 portable release archive is empty")
    expected_sidecar = f"{archive_sha256}  {PORTABLE_ARCHIVE_NAME}\n".encode("ascii")
    if _read_regular_file(
        sidecar, "v0.93 portable archive sidecar", limit=_MAX_METADATA_BYTES
    ) != expected_sidecar:
        raise V093ReleaseError("v0.93 portable archive sidecar differs")
    _read_json(receipt, "v0.93 portable distribution receipt")
    try:
        with tempfile.TemporaryDirectory(prefix="sector-v093-verify-") as temporary:
            distribution = Path(temporary) / "distribution"
            safe_extract_portable_archive(
                archive, distribution, expected_sha256=archive_sha256
            )
            _copy_regular_file(
                archive,
                distribution / PORTABLE_ARCHIVE_NAME,
                "v0.93 portable release archive",
                limit=_MAX_PORTABLE_ARCHIVE_BYTES,
            )
            _copy_regular_file(
                sidecar,
                distribution / PORTABLE_SIDECAR_NAME,
                "v0.93 portable archive sidecar",
                limit=_MAX_METADATA_BYTES,
            )
            _copy_regular_file(
                receipt,
                distribution / PORTABLE_RECEIPT_NAME,
                "v0.93 portable distribution receipt",
                limit=_MAX_METADATA_BYTES,
            )
            evidence = verify_portable_distribution(
                root, source_revision, distribution
            )
    except (PortableBuildError, OSError) as exc:
        raise V093ReleaseError(
            f"v0.93 portable release authentication failed: {exc}"
        ) from exc
    _final_bytes, final_sha256 = _hash_regular_file(
        archive, "v0.93 portable release archive", limit=_MAX_PORTABLE_ARCHIVE_BYTES
    )
    if final_sha256 != archive_sha256:
        raise V093ReleaseError("v0.93 portable release archive changed during verification")
    if (
        getattr(evidence, "source_revision", None) != source_revision
        or getattr(evidence, "sector_version", None) != SECTOR_VERSION
        or getattr(evidence, "unsigned_status", None) != UNSIGNED_STATUS
        or getattr(evidence, "archive_name", None) != PORTABLE_ARCHIVE_NAME
        or getattr(evidence, "archive_sha256", None) != archive_sha256
    ):
        raise V093ReleaseError("v0.93 portable release identity differs")
    return evidence


def _release_receipt(
    qa_evidence: dict[str, Any],
    source_evidence: Any,
    portable_evidence: Any,
    portable_receipt_sha256: str,
) -> dict[str, Any]:
    return {
        "release_qa_receipt_schema": RELEASE_RECEIPT_SCHEMA,
        "product_name": PRODUCT_NAME,
        "sector_version": SECTOR_VERSION,
        "release_status": "draft",
        "unsigned_status": UNSIGNED_STATUS,
        "source": {
            "archive_bytes": source_evidence.archive_bytes,
            "archive_name": SOURCE_ARCHIVE_NAME,
            "archive_sha256": source_evidence.archive_sha256,
            "revision": source_evidence.source_revision,
            "tree": source_evidence.source_tree,
        },
        "portable": {
            "archive_name": PORTABLE_ARCHIVE_NAME,
            "archive_sha256": portable_evidence.archive_sha256,
            "distribution_receipt_name": PORTABLE_RECEIPT_NAME,
            "distribution_receipt_sha256": portable_receipt_sha256,
            "folder_file_count": portable_evidence.folder_file_count,
            "folder_inventory_sha256": portable_evidence.folder_inventory_sha256,
            "folder_total_bytes": portable_evidence.folder_total_bytes,
        },
        "qa": qa_evidence,
    }


def _embedded_qa_evidence(
    output: Path,
    source_revision: str,
    qa_evidence_path: Path | None,
) -> dict[str, Any]:
    value, _raw = _read_json(
        output / RELEASE_RECEIPT_NAME, "v0.93 release QA receipt"
    )
    expected_keys = {
        "release_qa_receipt_schema",
        "product_name",
        "sector_version",
        "release_status",
        "unsigned_status",
        "source",
        "portable",
        "qa",
    }
    if (
        set(value) != expected_keys
        or type(value["release_qa_receipt_schema"]) is not int
        or value["release_qa_receipt_schema"] != RELEASE_RECEIPT_SCHEMA
        or value["product_name"] != PRODUCT_NAME
        or value["sector_version"] != SECTOR_VERSION
        or value["release_status"] != "draft"
        or value["unsigned_status"] != UNSIGNED_STATUS
        or not isinstance(value["source"], dict)
        or not isinstance(value["portable"], dict)
        or not isinstance(value["qa"], dict)
    ):
        raise V093ReleaseError("v0.93 release QA receipt schema differs")
    embedded = _validate_qa_evidence(value["qa"], source_revision)
    if qa_evidence_path is not None:
        external = read_qa_evidence(qa_evidence_path, source_revision)
        if external != embedded:
            raise V093ReleaseError(
                "external QA evidence differs from the embedded release authority"
            )
    return embedded


def _sidecar(sha256: str, name: str) -> bytes:
    if _SHA256.fullmatch(sha256) is None:
        raise V093ReleaseError(f"cannot write noncanonical SHA-256 for {name}")
    return f"{sha256}  {name}\n".encode("ascii")


def _checksum_payload(digests: dict[str, str]) -> tuple[bytes, str]:
    if tuple(sorted(digests)) != _CHECKSUMMED_ASSET_NAMES:
        raise V093ReleaseError("v0.93 checksum input inventory differs")
    lines: list[str] = []
    for name in _CHECKSUMMED_ASSET_NAMES:
        digest = digests[name]
        if _SHA256.fullmatch(digest) is None:
            raise V093ReleaseError(f"v0.93 checksum digest is invalid: {name}")
        lines.append(f"{digest}  {name}\n")
    payload = "".join(lines).encode("ascii")
    return payload, hashlib.sha256(payload).hexdigest()


def _current_checksums(output: Path) -> tuple[bytes, str]:
    digests: dict[str, str] = {}
    for name in _CHECKSUMMED_ASSET_NAMES:
        _size, digest = _hash_regular_file(
            output / name, f"v0.93 release asset {name}", limit=_asset_limit(name)
        )
        digests[name] = digest
    return _checksum_payload(digests)


def _verify_release_assets(
    root: Path,
    source_revision: str,
    qa_evidence: dict[str, Any],
    output: Path,
) -> V093ReleaseEvidence:
    _inventory_release_directory(output)
    try:
        source_evidence = verify_source_release(
            root, source_revision, output / SOURCE_ARCHIVE_NAME
        )
    except SourceReleaseError as exc:
        raise V093ReleaseError(
            f"v0.93 source release authentication failed: {exc}"
        ) from exc
    if (
        source_evidence.source_revision != source_revision
        or source_evidence.sector_version != SECTOR_VERSION
        or _OBJECT_ID.fullmatch(source_evidence.source_tree) is None
    ):
        raise V093ReleaseError("v0.93 source release identity differs")
    source_bytes, source_sha256 = _hash_regular_file(
        output / SOURCE_ARCHIVE_NAME,
        "v0.93 source release archive",
        limit=_MAX_SOURCE_ARCHIVE_BYTES,
    )
    if (
        source_bytes != source_evidence.archive_bytes
        or source_sha256 != source_evidence.archive_sha256
    ):
        raise V093ReleaseError("v0.93 source archive evidence differs")
    source_sidecar = _read_regular_file(
        output / SOURCE_SIDECAR_NAME,
        "v0.93 source archive sidecar",
        limit=_MAX_METADATA_BYTES,
    )
    if source_sidecar != _sidecar(source_sha256, SOURCE_ARCHIVE_NAME):
        raise V093ReleaseError("v0.93 source archive sidecar differs")

    portable_evidence = _portable_release_evidence(
        root,
        source_revision,
        output / PORTABLE_ARCHIVE_NAME,
        output / PORTABLE_SIDECAR_NAME,
        output / PORTABLE_RECEIPT_NAME,
    )
    _portable_receipt_bytes, portable_receipt_sha256 = _hash_regular_file(
        output / PORTABLE_RECEIPT_NAME,
        "v0.93 portable distribution receipt",
        limit=_MAX_METADATA_BYTES,
    )
    portable_sidecar = _read_regular_file(
        output / PORTABLE_SIDECAR_NAME,
        "v0.93 portable archive sidecar",
        limit=_MAX_METADATA_BYTES,
    )
    if portable_sidecar != _sidecar(
        portable_evidence.archive_sha256, PORTABLE_ARCHIVE_NAME
    ):
        raise V093ReleaseError("v0.93 portable archive sidecar differs")
    expected_receipt = _release_receipt(
        qa_evidence,
        source_evidence,
        portable_evidence,
        portable_receipt_sha256,
    )
    receipt_value, receipt_raw = _read_json(
        output / RELEASE_RECEIPT_NAME, "v0.93 release QA receipt"
    )
    if receipt_value != expected_receipt or receipt_raw != _canonical_json(expected_receipt):
        raise V093ReleaseError("v0.93 release QA receipt differs")

    authenticated_digests = {
        SOURCE_ARCHIVE_NAME: source_sha256,
        SOURCE_SIDECAR_NAME: hashlib.sha256(source_sidecar).hexdigest(),
        PORTABLE_ARCHIVE_NAME: portable_evidence.archive_sha256,
        PORTABLE_SIDECAR_NAME: hashlib.sha256(portable_sidecar).hexdigest(),
        PORTABLE_RECEIPT_NAME: portable_receipt_sha256,
        RELEASE_RECEIPT_NAME: hashlib.sha256(receipt_raw).hexdigest(),
    }
    expected_checksums, checksums_sha256 = _checksum_payload(
        authenticated_digests
    )
    actual_checksums = _read_regular_file(
        output / CHECKSUMS_NAME,
        "v0.93 release SHA-256 closure",
        limit=_MAX_METADATA_BYTES,
    )
    if actual_checksums != expected_checksums:
        raise V093ReleaseError("v0.93 release SHA-256 closure differs")
    for name, authenticated_sha256 in authenticated_digests.items():
        _final_bytes, final_sha256 = _hash_regular_file(
            output / name,
            f"v0.93 release asset {name}",
            limit=_asset_limit(name),
        )
        if final_sha256 != authenticated_sha256:
            raise V093ReleaseError(
                f"v0.93 release asset changed after authentication: {name}"
            )
    if _read_regular_file(
        output / CHECKSUMS_NAME,
        "v0.93 release SHA-256 closure",
        limit=_MAX_METADATA_BYTES,
    ) != expected_checksums:
        raise V093ReleaseError("v0.93 release SHA-256 closure changed")
    return V093ReleaseEvidence(
        source_revision=source_evidence.source_revision,
        source_tree=source_evidence.source_tree,
        sector_version=SECTOR_VERSION,
        unsigned_status=UNSIGNED_STATUS,
        qa_run_id=qa_evidence["run_id"],
        qa_run_attempt=qa_evidence["run_attempt"],
        source_archive_sha256=source_sha256,
        portable_archive_sha256=portable_evidence.archive_sha256,
        asset_count=len(RELEASE_ASSET_NAMES),
        assets_sha256=checksums_sha256,
        output=output,
    )


def verify_v093_release(
    root: Path,
    source_revision: str,
    output: Path,
    *,
    qa_evidence_path: Path | None = None,
) -> V093ReleaseEvidence:
    """Authenticate an existing directory containing exactly seven release assets."""
    revision = _require_revision(source_revision)
    root = Path(os.path.abspath(root))
    output = Path(os.path.abspath(output))
    _require_directory(root, "v0.93 release source root")
    _inventory_release_directory(output)
    qa_evidence = _embedded_qa_evidence(
        output, revision, qa_evidence_path
    )
    return _verify_release_assets(root, revision, qa_evidence, output)


def _publish_directory_no_replace(source: Path, destination: Path) -> None:
    """Atomically rename one directory while refusing every existing target."""
    try:
        if os.name == "nt":
            os.rename(source, destination)
            return
        if not sys.platform.startswith("linux"):
            raise V093ReleaseError(
                "atomic no-replace publication is unsupported on this platform"
            )
        library = ctypes.CDLL(None, use_errno=True)
        try:
            renameat2 = library.renameat2
        except AttributeError as exc:
            raise V093ReleaseError(
                "atomic no-replace publication is unavailable"
            ) from exc
        renameat2.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        renameat2.restype = ctypes.c_int
        result = renameat2(
            -100,
            os.fsencode(source),
            -100,
            os.fsencode(destination),
            1,
        )
        if result != 0:
            error_number = ctypes.get_errno()
            if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
                raise FileExistsError(
                    error_number, os.strerror(error_number), destination
                )
            raise OSError(error_number, os.strerror(error_number), destination)
    except FileExistsError as exc:
        raise V093ReleaseError(
            f"v0.93 release output already exists: {destination}"
        ) from exc
    except V093ReleaseError:
        raise
    except OSError as exc:
        raise V093ReleaseError(
            "cannot atomically publish create-only v0.93 release assets"
        ) from exc


def assemble_v093_release(
    root: Path,
    source_revision: str,
    qa_evidence_path: Path,
    portable_distribution: Path,
    output: Path,
) -> V093ReleaseEvidence:
    """Create and atomically publish the exact seven unsigned draft-release assets."""
    revision = _require_revision(source_revision)
    qa_evidence = read_qa_evidence(qa_evidence_path, revision)
    root = Path(os.path.abspath(root))
    portable_distribution = Path(os.path.abspath(portable_distribution))
    output = Path(os.path.abspath(output))
    _require_directory(root, "v0.93 release source root")
    if os.path.lexists(output):
        raise V093ReleaseError(f"v0.93 release output already exists: {output}")
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise V093ReleaseError("cannot create v0.93 release output parent") from exc
    _require_directory(output.parent, "v0.93 release output parent")
    try:
        portable_before = verify_portable_distribution(
            root, revision, portable_distribution
        )
    except PortableBuildError as exc:
        raise V093ReleaseError(
            f"upstream portable distribution authentication failed: {exc}"
        ) from exc
    if (
        portable_before.source_revision != revision
        or portable_before.sector_version != SECTOR_VERSION
        or portable_before.unsigned_status != UNSIGNED_STATUS
        or portable_before.archive_name != PORTABLE_ARCHIVE_NAME
        or portable_before.sidecar.name != PORTABLE_SIDECAR_NAME
        or portable_before.receipt.name != PORTABLE_RECEIPT_NAME
    ):
        raise V093ReleaseError("upstream portable distribution identity differs")

    try:
        with tempfile.TemporaryDirectory(
            prefix=f".{output.name}.assemble-", dir=output.parent
        ) as temporary:
            publish = Path(temporary) / "publish"
            publish.mkdir()
            source_archive = publish / SOURCE_ARCHIVE_NAME
            try:
                source_evidence = build_source_release(root, revision, source_archive)
                independently_verified = verify_source_release(
                    root, revision, source_archive
                )
            except SourceReleaseError as exc:
                raise V093ReleaseError(
                    f"v0.93 source release creation failed: {exc}"
                ) from exc
            if source_evidence != independently_verified:
                raise V093ReleaseError("source release build and verification evidence differ")
            if (
                source_evidence.source_revision != revision
                or source_evidence.sector_version != SECTOR_VERSION
                or _OBJECT_ID.fullmatch(source_evidence.source_tree) is None
            ):
                raise V093ReleaseError("created source release identity differs")
            _write_new(
                publish / SOURCE_SIDECAR_NAME,
                _sidecar(source_evidence.archive_sha256, SOURCE_ARCHIVE_NAME),
                "v0.93 source archive sidecar",
            )
            _portable_bytes, portable_sha256 = _copy_regular_file(
                portable_before.archive,
                publish / PORTABLE_ARCHIVE_NAME,
                "upstream portable archive",
                limit=_MAX_PORTABLE_ARCHIVE_BYTES,
            )
            _copy_regular_file(
                portable_before.sidecar,
                publish / PORTABLE_SIDECAR_NAME,
                "upstream portable archive sidecar",
                limit=_MAX_METADATA_BYTES,
            )
            _portable_receipt_bytes, portable_receipt_sha256 = _copy_regular_file(
                portable_before.receipt,
                publish / PORTABLE_RECEIPT_NAME,
                "upstream portable distribution receipt",
                limit=_MAX_METADATA_BYTES,
            )
            try:
                portable_after = verify_portable_distribution(
                    root, revision, portable_distribution
                )
            except PortableBuildError as exc:
                raise V093ReleaseError(
                    f"upstream portable distribution changed: {exc}"
                ) from exc
            if portable_before != portable_after or portable_sha256 != portable_before.archive_sha256:
                raise V093ReleaseError("upstream portable distribution changed during assembly")
            _write_new(
                publish / RELEASE_RECEIPT_NAME,
                _canonical_json(
                    _release_receipt(
                        qa_evidence,
                        source_evidence,
                        portable_before,
                        portable_receipt_sha256,
                    )
                ),
                "v0.93 release QA receipt",
            )
            checksum_payload, _checksum_sha256 = _current_checksums(publish)
            _write_new(
                publish / CHECKSUMS_NAME,
                checksum_payload,
                "v0.93 release SHA-256 closure",
            )
            staged = _verify_release_assets(root, revision, qa_evidence, publish)
            if os.path.lexists(output):
                raise V093ReleaseError(
                    f"v0.93 release output appeared during assembly: {output}"
                )
            _publish_directory_no_replace(publish, output)
            return V093ReleaseEvidence(
                **{**staged.__dict__, "output": output}
            )
    except V093ReleaseError:
        raise
    except OSError as exc:
        raise V093ReleaseError("cannot atomically publish v0.93 release assets") from exc


def _display(evidence: V093ReleaseEvidence) -> dict[str, object]:
    return {
        name: str(value) if isinstance(value, Path) else value
        for name, value in evidence.__dict__.items()
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    for action in ("assemble", "verify"):
        command = subparsers.add_parser(action)
        command.add_argument("--root", required=True, type=Path)
        command.add_argument("--source-revision", required=True)
        command.add_argument("--output", required=True, type=Path)
        if action == "assemble":
            command.add_argument("--qa-evidence", required=True, type=Path)
            command.add_argument(
                "--portable-distribution", required=True, type=Path
            )
        else:
            command.add_argument("--qa-evidence", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.action == "assemble":
            evidence = assemble_v093_release(
                arguments.root,
                arguments.source_revision,
                arguments.qa_evidence,
                arguments.portable_distribution,
                arguments.output,
            )
        else:
            evidence = verify_v093_release(
                arguments.root,
                arguments.source_revision,
                arguments.output,
                qa_evidence_path=arguments.qa_evidence,
            )
    except V093ReleaseError as exc:
        print(f"Sector v0.93 release failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(_display(evidence), ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
