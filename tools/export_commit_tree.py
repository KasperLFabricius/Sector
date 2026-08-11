"""Materialize the verified regular-file tree of one exact Git commit."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, cast

OBJECT_ID = re.compile(r"^[0-9a-f]{40}$")
HEADER_NAME = re.compile(rb"^[a-z][a-z0-9-]*$")
IDENTITY = re.compile(rb"^.+ <[^<>\n]+> (-?[0-9]+) ([+-])([0-9]{2})([0-9]{2})$")
WINDOWS_FORBIDDEN = frozenset('<>:"\\|?*')
WINDOWS_RESERVED = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
        *(f"COM{number}" for number in ("\u00b9", "\u00b2", "\u00b3")),
        *(f"LPT{number}" for number in ("\u00b9", "\u00b2", "\u00b3")),
    }
)

# These are hard defaults for every caller of snapshot_commit/export_commit.
# Keep the payload ceilings aligned with the source-release contract so a Git
# repository cannot make a downstream caller allocate an object graph that the
# source archive would subsequently reject.
MAX_SNAPSHOT_FILES = 50_000
MAX_SNAPSHOT_DIRECTORIES = 50_000
MAX_BLOB_BYTES = 256 * 1024 * 1024
MAX_SNAPSHOT_TOTAL_BYTES = 512 * 1024 * 1024
MAX_COMMIT_OBJECT_BYTES = 1 * 1024 * 1024
MAX_TREE_OBJECT_BYTES = 16 * 1024 * 1024
MAX_TREE_TOTAL_BYTES = 64 * 1024 * 1024
MAX_BATCH_HEADER_BYTES = 256


class CommitTreeError(ValueError):
    """The requested commit cannot be exported under the closed contract."""


@dataclass(frozen=True)
class RawObject:
    object_id: str
    kind: str
    payload: bytes


@dataclass(frozen=True)
class ObjectHeader:
    object_id: str
    kind: str
    size: int


@dataclass(frozen=True)
class TreeItem:
    mode: str
    name: str
    object_id: str

    @property
    def is_tree(self) -> bool:
        return self.mode == "40000"


@dataclass(frozen=True)
class SourceFile:
    mode: str
    path: str
    object_id: str


@dataclass(frozen=True)
class ExportEvidence:
    source_revision: str
    source_tree: str
    source_committer_epoch: int
    source_committed_at_utc: str
    file_count: int
    total_bytes: int
    inventory_sha256: str


@dataclass(frozen=True)
class SnapshotFile:
    mode: str
    path: str
    object_id: str
    payload: bytes


@dataclass(frozen=True)
class CommitSnapshot:
    evidence: ExportEvidence
    commit_payload: bytes
    files: tuple[SnapshotFile, ...]


@dataclass(frozen=True)
class ParsedCommit:
    tree_id: str
    committer_epoch: int
    committed_at_utc: str


@dataclass(frozen=True)
class RepositoryBoundary:
    worktree: Path
    git_directory: Path
    common_git_directory: Path


def _git_environment() -> dict[str, str]:
    """Remove inherited Git controls, including case variants on Windows."""
    return {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("GIT_")
    }


def _git_command(root: Path, *arguments: str) -> list[str]:
    return ["git", "--no-replace-objects", "-C", str(root), *arguments]


def _run_git(root: Path, *arguments: str, input_bytes: bytes | None = None) -> bytes:
    try:
        completed = subprocess.run(
            _git_command(root, *arguments),
            input=input_bytes,
            capture_output=True,
            check=False,
            env=_git_environment(),
        )
    except OSError as exc:
        raise CommitTreeError("cannot execute Git object inspection") from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        suffix = f": {detail}" if detail else ""
        raise CommitTreeError(f"Git object inspection failed{suffix}")
    return completed.stdout


def _metadata_path(root: Path, *arguments: str) -> Path:
    try:
        raw = _run_git(root, *arguments).decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise CommitTreeError("Git metadata path is not UTF-8") from exc
    if not raw or "\n" in raw or "\r" in raw:
        raise CommitTreeError("Git metadata path is malformed")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate.resolve(strict=False)


def _repository_boundary(root: Path) -> RepositoryBoundary:
    worktree = _metadata_path(
        root, "rev-parse", "--path-format=absolute", "--show-toplevel"
    )
    try:
        exact = root.samefile(worktree)
    except OSError:
        exact = root == worktree
    if not exact:
        raise CommitTreeError("repository must be the exact worktree root")
    git_directory = _metadata_path(
        root, "rev-parse", "--path-format=absolute", "--git-dir"
    )
    common_git_directory = _metadata_path(
        root, "rev-parse", "--path-format=absolute", "--git-common-dir"
    )
    return RepositoryBoundary(worktree, git_directory, common_git_directory)


def _object_digest(kind: str, payload: bytes) -> str:
    header = f"{kind} {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()


def _parse_object_header(raw: bytes, expected: str) -> ObjectHeader:
    if raw == expected.encode("ascii") + b" missing":
        raise CommitTreeError(f"Git object inspection failed: missing object {expected}")
    try:
        actual, kind, raw_size = raw.decode("ascii").split(" ")
        if not raw_size or (len(raw_size) > 1 and raw_size.startswith("0")):
            raise ValueError
        size = int(raw_size)
    except (UnicodeDecodeError, ValueError) as exc:
        raise CommitTreeError("Git object inspection failed: malformed batch header") from exc
    if actual != expected or kind not in {"blob", "commit", "tree"} or size < 0:
        raise CommitTreeError("Git object inspection failed: unexpected batch object")
    return ObjectHeader(actual, kind, size)


def _object_size_limit(kind: str) -> int:
    return {
        "blob": MAX_BLOB_BYTES,
        "commit": MAX_COMMIT_OBJECT_BYTES,
        "tree": MAX_TREE_OBJECT_BYTES,
    }[kind]


def _object_size_error(kind: str) -> str:
    return f"Git {kind} object exceeds the byte limit"


def _parse_batch_response(raw: bytes, requested: list[str]) -> list[RawObject]:
    """Parse and independently authenticate an ordered cat-file batch."""
    objects: list[RawObject] = []
    cursor = 0
    totals = {"blob": 0, "commit": 0, "tree": 0}
    for expected in requested:
        header_end = raw.find(b"\n", cursor)
        if header_end < 0:
            raise CommitTreeError("Git object inspection failed: missing batch header")
        header = raw[cursor:header_end]
        cursor = header_end + 1
        inspected = _parse_object_header(header, expected)
        kind, size = inspected.kind, inspected.size
        if size > _object_size_limit(kind):
            raise CommitTreeError(_object_size_error(kind))
        totals[kind] += size
        total_limit = (
            MAX_SNAPSHOT_TOTAL_BYTES if kind == "blob" else MAX_TREE_TOTAL_BYTES
        )
        if kind != "commit" and totals[kind] > total_limit:
            raise CommitTreeError(f"Git {kind} objects exceed the total-byte limit")
        end = cursor + size
        if end > len(raw):
            raise CommitTreeError("Git object inspection failed: truncated batch object")
        payload = raw[cursor:end]
        if _object_digest(kind, payload) != expected:
            raise CommitTreeError(f"Git object hash mismatch: {expected}")
        if raw[end : end + 1] != b"\n":
            raise CommitTreeError("Git object inspection failed: missing batch terminator")
        cursor = end + 1
        objects.append(RawObject(expected, kind, payload))
    if cursor != len(raw):
        raise CommitTreeError("Git object inspection failed: trailing batch output")
    return objects


def _read_object_headers(root: Path, object_ids: list[str]) -> list[ObjectHeader]:
    if not object_ids:
        return []
    if any(OBJECT_ID.fullmatch(object_id) is None for object_id in object_ids):
        raise CommitTreeError("internal object request is not an exact lowercase SHA-1")
    requests = b"".join(object_id.encode("ascii") + b"\n" for object_id in object_ids)
    response = _run_git(
        root,
        "cat-file",
        "--batch-check=%(objectname) %(objecttype) %(objectsize)",
        input_bytes=requests,
    )
    if len(response) > len(object_ids) * (MAX_BATCH_HEADER_BYTES + 1):
        raise CommitTreeError("Git object inspection failed: oversized batch header")
    lines = response.splitlines(keepends=True)
    if len(lines) != len(object_ids) or any(
        not line.endswith(b"\n") or len(line) > MAX_BATCH_HEADER_BYTES + 1
        for line in lines
    ):
        raise CommitTreeError("Git object inspection failed: malformed batch header")
    return [
        _parse_object_header(line[:-1], expected)
        for line, expected in zip(lines, object_ids)
    ]


def _validate_object_headers(
    headers: list[ObjectHeader],
    *,
    expected_kind: str,
    per_object_limit: int,
    total_limit: int,
    kind_error: str,
    size_error: str,
    total_error: str,
) -> int:
    total = 0
    for header in headers:
        if header.kind != expected_kind:
            raise CommitTreeError(kind_error)
        if header.size > per_object_limit:
            raise CommitTreeError(size_error)
        total += header.size
        if total > total_limit:
            raise CommitTreeError(total_error)
    return total


def _read_batch_payloads_from_stream(
    root: Path,
    object_ids: list[str],
    headers: list[ObjectHeader],
    requests: bytes,
    request_stream: BinaryIO,
) -> list[RawObject]:
    request_stream.write(requests)
    request_stream.seek(0)
    try:
        process = subprocess.Popen(
            _git_command(root, "cat-file", "--batch"),
            stdin=request_stream,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_git_environment(),
        )
    except OSError as exc:
        raise CommitTreeError("cannot execute Git object inspection") from exc
    try:
        if process.stdout is None or process.stderr is None:
            raise CommitTreeError("Git object inspection pipes are unavailable")
        objects: list[RawObject] = []
        for expected, inspected in zip(object_ids, headers):
            raw_header = process.stdout.readline(MAX_BATCH_HEADER_BYTES + 2)
            if (
                not raw_header.endswith(b"\n")
                or len(raw_header) > MAX_BATCH_HEADER_BYTES + 1
            ):
                raise CommitTreeError(
                    "Git object inspection failed: malformed batch header"
                )
            actual = _parse_object_header(raw_header[:-1], expected)
            if actual != inspected:
                raise CommitTreeError("Git object header changed during inspection")
            payload = process.stdout.read(actual.size)
            if len(payload) != actual.size:
                raise CommitTreeError("Git object inspection failed: truncated batch object")
            if process.stdout.read(1) != b"\n":
                raise CommitTreeError(
                    "Git object inspection failed: missing batch terminator"
                )
            if _object_digest(actual.kind, payload) != expected:
                raise CommitTreeError(f"Git object hash mismatch: {expected}")
            objects.append(RawObject(expected, actual.kind, payload))
        if process.stdout.read(1):
            raise CommitTreeError("Git object inspection failed: trailing batch output")
        error = process.stderr.read(4097)
        return_code = process.wait()
        if return_code != 0:
            detail = error[:4096].decode("utf-8", errors="replace").strip()
            suffix = f": {detail}" if detail else ""
            raise CommitTreeError(f"Git object inspection failed{suffix}")
        return objects
    except CommitTreeError:
        raise
    except (BrokenPipeError, OSError) as exc:
        raise CommitTreeError("Git object inspection failed") from exc
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def _read_batch_payloads(
    root: Path, object_ids: list[str], headers: list[ObjectHeader]
) -> list[RawObject]:
    requests = b"".join(object_id.encode("ascii") + b"\n" for object_id in object_ids)
    try:
        with tempfile.TemporaryFile() as request_stream:
            return _read_batch_payloads_from_stream(
                root,
                object_ids,
                headers,
                requests,
                cast(BinaryIO, request_stream),
            )
    except CommitTreeError:
        raise
    except OSError as exc:
        raise CommitTreeError("Git object inspection failed") from exc


def _read_objects(
    root: Path,
    object_ids: list[str],
    *,
    expected_kind: str,
    per_object_limit: int,
    total_limit: int,
    kind_error: str,
    size_error: str,
    total_error: str,
    headers: list[ObjectHeader] | None = None,
) -> list[RawObject]:
    if not object_ids:
        return []
    inspected = _read_object_headers(root, object_ids) if headers is None else headers
    if len(inspected) != len(object_ids) or any(
        header.object_id != expected
        for header, expected in zip(inspected, object_ids)
    ):
        raise CommitTreeError("Git object inspection returned an unexpected inventory")
    _validate_object_headers(
        inspected,
        expected_kind=expected_kind,
        per_object_limit=per_object_limit,
        total_limit=total_limit,
        kind_error=kind_error,
        size_error=size_error,
        total_error=total_error,
    )
    return _read_batch_payloads(root, object_ids, inspected)


def _parse_headers(payload: bytes) -> list[tuple[bytes, bytes]]:
    if b"\0" in payload or b"\r" in payload:
        raise CommitTreeError("commit object contains forbidden control bytes")
    separator = payload.find(b"\n\n")
    if separator < 0:
        raise CommitTreeError("commit object has no header/message boundary")
    raw_lines = payload[:separator].split(b"\n")
    if not raw_lines or any(not line for line in raw_lines):
        raise CommitTreeError("commit object contains an empty header")
    headers: list[tuple[bytes, bytes]] = []
    for line in raw_lines:
        if line.startswith(b" "):
            if not headers:
                raise CommitTreeError("commit header continuation has no owner")
            key, value = headers[-1]
            headers[-1] = (key, value + b"\n" + line)
            continue
        key, space, value = line.partition(b" ")
        if not space or HEADER_NAME.fullmatch(key) is None or not value:
            raise CommitTreeError("commit object contains a malformed header")
        headers.append((key, value))
    return headers


def _validate_identity(field: str, value: bytes) -> int:
    match = IDENTITY.fullmatch(value)
    if match is None:
        raise CommitTreeError(f"commit {field} identity is malformed")
    timestamp = match.group(1)
    if timestamp.startswith(b"-") or (
        len(timestamp) > 1 and timestamp.startswith(b"0")
    ):
        raise CommitTreeError(
            f"commit {field} identity must use a canonical nonnegative timestamp"
        )
    hours = int(match.group(3))
    minutes = int(match.group(4))
    if hours > 14 or minutes > 59 or (hours == 14 and minutes != 0):
        raise CommitTreeError(f"commit {field} identity has an invalid timezone")
    return int(timestamp)


def _header_object_id(field: str, value: bytes) -> str:
    try:
        candidate = value.decode("ascii")
    except UnicodeDecodeError as exc:
        raise CommitTreeError(f"commit {field} identity is not ASCII") from exc
    if OBJECT_ID.fullmatch(candidate) is None:
        raise CommitTreeError(f"commit {field} identity is not an exact SHA-1")
    return candidate


def _parse_commit(payload: bytes) -> ParsedCommit:
    """Strictly validate one commit and return canonical package-time identity."""
    headers = _parse_headers(payload)
    if headers[0][0] != b"tree":
        raise CommitTreeError("commit must begin with one exact tree identity")
    tree_id = _header_object_id("tree", headers[0][1])

    counts = {b"tree": 0, b"author": 0, b"committer": 0}
    parents: set[str] = set()
    phase = "parents"
    committer_epoch: int | None = None
    for index, (key, value) in enumerate(headers):
        if key in counts:
            counts[key] += 1
        if key == b"tree":
            if counts[key] != 1 or index != 0:
                raise CommitTreeError("commit must contain exactly one leading tree")
        elif key == b"parent":
            parent = _header_object_id("parent", value)
            if phase != "parents":
                raise CommitTreeError("commit parent header is malformed")
            if parent in parents:
                raise CommitTreeError("commit contains a duplicate parent")
            parents.add(parent)
        elif key == b"author":
            if phase != "parents":
                raise CommitTreeError("commit author header is misplaced")
            _validate_identity("author", value)
            phase = "committer"
        elif key == b"committer":
            if phase != "committer":
                raise CommitTreeError("commit committer header is misplaced")
            committer_epoch = _validate_identity("committer", value)
            phase = "extra"
        elif phase in {"parents", "committer"}:
            raise CommitTreeError("commit required identity headers are misplaced")
    if counts != {b"tree": 1, b"author": 1, b"committer": 1} or phase != "extra":
        raise CommitTreeError("commit must contain one tree, author, and committer")
    if committer_epoch is None:
        raise CommitTreeError("commit committer timestamp is unavailable")
    try:
        committed_at = dt.datetime.fromtimestamp(
            committer_epoch, tz=dt.timezone.utc
        ).isoformat(timespec="seconds")
    except (OverflowError, OSError, ValueError) as exc:
        raise CommitTreeError("commit committer timestamp is out of range") from exc
    return ParsedCommit(tree_id, committer_epoch, committed_at)


def _device_stem(component: str) -> str:
    return component.split(".", 1)[0].rstrip(" .").upper()


def _validate_component(raw_name: bytes) -> str:
    try:
        name = raw_name.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CommitTreeError("commit tree name is not valid UTF-8") from exc
    if not name or name in {".", ".."} or "/" in name:
        raise CommitTreeError(f"unsafe commit tree name: {name!r}")
    normalized = unicodedata.normalize("NFC", name)
    if normalized.casefold() == ".git":
        raise CommitTreeError(f"unsafe Git-control commit tree name: {name!r}")
    if (
        name.endswith((" ", "."))
        or any(ord(character) < 32 for character in name)
        or any(character in WINDOWS_FORBIDDEN for character in name)
        or _device_stem(name) in WINDOWS_RESERVED
    ):
        raise CommitTreeError(f"Windows-unsafe commit tree name: {name!r}")
    return name


def _parse_tree_object(payload: bytes) -> list[TreeItem]:
    """Parse a raw tree object while enforcing portable canonical names."""
    items: list[TreeItem] = []
    normalized: dict[str, TreeItem] = {}
    cursor = 0
    prior_order: bytes | None = None
    while cursor < len(payload):
        mode_end = payload.find(b" ", cursor)
        name_end = payload.find(b"\0", mode_end + 1)
        if mode_end < 0 or name_end < 0 or name_end + 21 > len(payload):
            raise CommitTreeError("commit tree object is malformed")
        try:
            mode = payload[cursor:mode_end].decode("ascii")
        except UnicodeDecodeError as exc:
            raise CommitTreeError("commit tree mode is malformed") from exc
        if mode not in {"40000", "100644", "100755"}:
            raise CommitTreeError(f"unsupported commit tree mode: {mode}")
        raw_name = payload[mode_end + 1 : name_end]
        name = _validate_component(raw_name)
        object_id = payload[name_end + 1 : name_end + 21].hex()
        order = raw_name + (b"/" if mode == "40000" else b"\0")
        if prior_order is not None and order <= prior_order:
            raise CommitTreeError("commit tree entries are not in canonical order")
        prior_order = order
        item = TreeItem(mode, name, object_id)
        key = unicodedata.normalize("NFC", name).casefold()
        previous = normalized.get(key)
        if previous is not None:
            if previous.is_tree != item.is_tree:
                raise CommitTreeError("commit tree has colliding file/directory names")
            raise CommitTreeError("commit tree has colliding case/Unicode names")
        normalized[key] = item
        items.append(item)
        cursor = name_end + 21
    if not items:
        raise CommitTreeError("commit tree object is empty")
    return items


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _inventory_tree(root: Path, tree_id: str) -> list[SourceFile]:
    pending: list[tuple[tuple[str, ...], str, frozenset[str]]] = [
        ((), tree_id, frozenset())
    ]
    files: list[SourceFile] = []
    path_kinds: dict[str, tuple[str, str]] = {}
    directory_count = 0
    tree_bytes = 0

    def register(parts: tuple[str, ...], kind: str) -> None:
        path = PurePosixPath(*parts).as_posix()
        key = unicodedata.normalize("NFC", path).casefold()
        previous = path_kinds.get(key)
        if previous is not None:
            if previous[1] != kind:
                raise CommitTreeError("commit tree has colliding file/directory paths")
            raise CommitTreeError("commit tree has colliding case/Unicode paths")
        path_kinds[key] = (path, kind)

    while pending:
        level = pending
        pending = []
        identities = _unique([object_id for _parts, object_id, _seen in level])
        raw_objects = _read_objects(
            root,
            identities,
            expected_kind="tree",
            per_object_limit=MAX_TREE_OBJECT_BYTES,
            total_limit=MAX_TREE_TOTAL_BYTES - tree_bytes,
            kind_error="commit tree references a non-tree object",
            size_error="Git tree object exceeds the byte limit",
            total_error="Git tree objects exceed the total-byte limit",
        )
        tree_bytes += sum(len(item.payload) for item in raw_objects)
        raw_by_id = {item.object_id: item for item in raw_objects}
        for parts, object_id, ancestors in level:
            if object_id in ancestors:
                raise CommitTreeError("commit tree contains an object cycle")
            raw_object = raw_by_id[object_id]
            if raw_object.kind != "tree":
                raise CommitTreeError("commit tree references a non-tree object")
            next_ancestors = ancestors | {object_id}
            for item in _parse_tree_object(raw_object.payload):
                child = (*parts, item.name)
                if item.is_tree:
                    if directory_count >= MAX_SNAPSHOT_DIRECTORIES:
                        raise CommitTreeError(
                            "commit tree exceeds the directory-count limit"
                        )
                    directory_count += 1
                    register(child, "directory")
                    pending.append((child, item.object_id, next_ancestors))
                else:
                    if len(files) >= MAX_SNAPSHOT_FILES:
                        raise CommitTreeError("commit tree exceeds the file-count limit")
                    register(child, "file")
                    files.append(
                        SourceFile(item.mode, PurePosixPath(*child).as_posix(), item.object_id)
                    )
    if not files:
        raise CommitTreeError("commit tree contains no regular files")
    return sorted(files, key=lambda item: item.path)


def _inside(path: Path, directory: Path) -> bool:
    return path == directory or directory in path.parents


def _inventory_digest(files: list[SourceFile], payloads: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for item in files:
        record = [item.path, item.mode, item.object_id, len(payloads[item.object_id])]
        digest.update(
            json.dumps(record, ensure_ascii=True, separators=(",", ":")).encode("ascii")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def _resolved_repository(root: Path) -> Path:
    try:
        resolved = root.resolve(strict=True)
    except OSError as exc:
        raise CommitTreeError("repository root does not exist") from exc
    if not resolved.is_dir():
        raise CommitTreeError("repository root is not a directory")
    _repository_boundary(resolved)
    return resolved


def _snapshot_from_resolved_root(
    root: Path, source_revision: str
) -> CommitSnapshot:
    if OBJECT_ID.fullmatch(source_revision) is None:
        raise CommitTreeError("source revision must be an exact lowercase 40-hex SHA-1")
    commit = _read_objects(
        root,
        [source_revision],
        expected_kind="commit",
        per_object_limit=MAX_COMMIT_OBJECT_BYTES,
        total_limit=MAX_COMMIT_OBJECT_BYTES,
        kind_error="source revision must be a commit object",
        size_error="Git commit object exceeds the byte limit",
        total_error="Git commit object exceeds the byte limit",
    )[0]
    parsed = _parse_commit(commit.payload)
    files = _inventory_tree(root, parsed.tree_id)
    blob_ids = _unique([item.object_id for item in files])
    blob_headers = _read_object_headers(root, blob_ids)
    _validate_object_headers(
        blob_headers,
        expected_kind="blob",
        per_object_limit=MAX_BLOB_BYTES,
        total_limit=MAX_SNAPSHOT_TOTAL_BYTES,
        kind_error="commit regular-file entry references a non-blob object",
        size_error="Git blob object exceeds the byte limit",
        total_error="Git blob objects exceed the total-byte limit",
    )
    sizes = {item.object_id: item.size for item in blob_headers}
    total_bytes = 0
    for item in files:
        total_bytes += sizes[item.object_id]
        if total_bytes > MAX_SNAPSHOT_TOTAL_BYTES:
            raise CommitTreeError("commit snapshot exceeds the total-byte limit")
    blobs = _read_objects(
        root,
        blob_ids,
        expected_kind="blob",
        per_object_limit=MAX_BLOB_BYTES,
        total_limit=MAX_SNAPSHOT_TOTAL_BYTES,
        kind_error="commit regular-file entry references a non-blob object",
        size_error="Git blob object exceeds the byte limit",
        total_error="Git blob objects exceed the total-byte limit",
        headers=blob_headers,
    )
    payloads = {item.object_id: item.payload for item in blobs}
    evidence = ExportEvidence(
        source_revision=source_revision,
        source_tree=parsed.tree_id,
        source_committer_epoch=parsed.committer_epoch,
        source_committed_at_utc=parsed.committed_at_utc,
        file_count=len(files),
        total_bytes=total_bytes,
        inventory_sha256=_inventory_digest(files, payloads),
    )
    return CommitSnapshot(
        evidence=evidence,
        commit_payload=commit.payload,
        files=tuple(
            SnapshotFile(
                mode=item.mode,
                path=item.path,
                object_id=item.object_id,
                payload=payloads[item.object_id],
            )
            for item in files
        ),
    )


def snapshot_commit(root: Path, source_revision: str) -> CommitSnapshot:
    """Capture authenticated raw blobs and identity from one exact commit."""
    return _snapshot_from_resolved_root(_resolved_repository(root), source_revision)


def export_commit(root: Path, source_revision: str, output: Path) -> ExportEvidence:
    """Export the authenticated source tree of one exact commit into a new path."""
    if OBJECT_ID.fullmatch(source_revision) is None:
        raise CommitTreeError("source revision must be an exact lowercase 40-hex SHA-1")
    root = _resolved_repository(root)
    lexical_output = Path(os.path.abspath(output))
    if lexical_output == root or lexical_output in root.parents:
        raise CommitTreeError("export output cannot contain the repository")
    if os.path.lexists(output):
        raise CommitTreeError(f"export output already exists: {output}")
    output = output.resolve(strict=False)
    if output == root or output in root.parents:
        raise CommitTreeError("export output cannot contain the repository")
    if output.exists():
        raise CommitTreeError(f"export output already exists: {output}")

    boundary = _repository_boundary(root)
    for metadata in {boundary.git_directory, boundary.common_git_directory}:
        if _inside(output, metadata):
            raise CommitTreeError("export output cannot be inside Git metadata")

    snapshot = _snapshot_from_resolved_root(root, source_revision)

    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.mkdir()
        for item in snapshot.files:
            relative = PurePosixPath(item.path)
            target = output.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(item.payload)
            os.chmod(target, 0o755 if item.mode == "100755" else 0o644)
    except OSError as exc:
        raise CommitTreeError(f"cannot materialize commit tree: {exc}") from exc

    return snapshot.evidence


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        evidence = export_commit(
            arguments.root, arguments.source_revision, arguments.output
        )
    except CommitTreeError as exc:
        print(f"exact commit export failed: {exc}", file=sys.stderr)
        return 2
    print(
        "exact commit exported: "
        f"{evidence.source_revision} | tree {evidence.source_tree} | "
        f"epoch {evidence.source_committer_epoch} | {evidence.file_count} files | "
        f"{evidence.total_bytes} bytes | {evidence.inventory_sha256}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
