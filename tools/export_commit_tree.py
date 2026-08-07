"""Materialize the verified regular-file tree of one exact Git commit."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

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


class CommitTreeError(ValueError):
    """The requested commit cannot be exported under the closed contract."""


@dataclass(frozen=True)
class RawObject:
    object_id: str
    kind: str
    payload: bytes


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
class CommitIdentity:
    source_tree: str
    source_epoch: int
    built_at_utc: str


@dataclass(frozen=True)
class ExportEvidence:
    source_revision: str
    source_tree: str
    source_epoch: int
    built_at_utc: str
    file_count: int
    total_bytes: int
    inventory_sha256: str


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
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
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


def _parse_batch_response(raw: bytes, requested: list[str]) -> list[RawObject]:
    """Parse and independently authenticate an ordered cat-file batch."""
    objects: list[RawObject] = []
    cursor = 0
    for expected in requested:
        header_end = raw.find(b"\n", cursor)
        if header_end < 0:
            raise CommitTreeError("Git object inspection failed: missing batch header")
        header = raw[cursor:header_end]
        cursor = header_end + 1
        if header == expected.encode("ascii") + b" missing":
            raise CommitTreeError(f"Git object inspection failed: missing object {expected}")
        try:
            actual, kind, raw_size = header.decode("ascii").split(" ")
            size = int(raw_size)
        except (UnicodeDecodeError, ValueError) as exc:
            raise CommitTreeError("Git object inspection failed: malformed batch header") from exc
        if actual != expected or kind not in {"blob", "commit", "tree"} or size < 0:
            raise CommitTreeError("Git object inspection failed: unexpected batch object")
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


def _read_objects(root: Path, object_ids: list[str]) -> list[RawObject]:
    if not object_ids:
        return []
    if any(OBJECT_ID.fullmatch(object_id) is None for object_id in object_ids):
        raise CommitTreeError("internal object request is not an exact lowercase SHA-1")
    requests = b"".join(object_id.encode("ascii") + b"\n" for object_id in object_ids)
    response = _run_git(root, "cat-file", "--batch", input_bytes=requests)
    return _parse_batch_response(response, object_ids)


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
    raw_timestamp = match.group(1)
    timestamp = int(raw_timestamp)
    if timestamp < 0 or str(timestamp).encode("ascii") != raw_timestamp:
        raise CommitTreeError(f"commit {field} timestamp is not a canonical epoch")
    hours = int(match.group(3))
    minutes = int(match.group(4))
    if hours > 14 or minutes > 59 or (hours == 14 and minutes != 0):
        raise CommitTreeError(f"commit {field} identity has an invalid timezone")
    return timestamp


def _header_object_id(field: str, value: bytes) -> str:
    try:
        candidate = value.decode("ascii")
    except UnicodeDecodeError as exc:
        raise CommitTreeError(f"commit {field} identity is not ASCII") from exc
    if OBJECT_ID.fullmatch(candidate) is None:
        raise CommitTreeError(f"commit {field} identity is not an exact SHA-1")
    return candidate


def _parse_commit_identity(payload: bytes) -> CommitIdentity:
    """Strictly validate one commit and derive its immutable source identity."""
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
    assert committer_epoch is not None
    try:
        built_at_utc = dt.datetime.fromtimestamp(
            committer_epoch, dt.timezone.utc
        ).isoformat(timespec="seconds")
    except (OSError, OverflowError, ValueError) as exc:
        raise CommitTreeError("commit committer epoch is outside the UTC range") from exc
    return CommitIdentity(tree_id, committer_epoch, built_at_utc)


def _parse_commit(payload: bytes) -> str:
    """Strictly validate one commit object and return its root-tree identity."""
    return _parse_commit_identity(payload).source_tree


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
        raw_by_id = {item.object_id: item for item in _read_objects(root, identities)}
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
                    register(child, "directory")
                    pending.append((child, item.object_id, next_ancestors))
                else:
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


def _inspect_selected_closure(
    root: Path, source_revision: str
) -> tuple[ExportEvidence, list[SourceFile], dict[str, bytes]]:
    commit = _read_objects(root, [source_revision])[0]
    if commit.kind != "commit":
        raise CommitTreeError("source revision must be a commit object")
    identity = _parse_commit_identity(commit.payload)
    files = _inventory_tree(root, identity.source_tree)
    blob_ids = _unique([item.object_id for item in files])
    blobs = _read_objects(root, blob_ids)
    if any(item.kind != "blob" for item in blobs):
        raise CommitTreeError("commit regular-file entry references a non-blob object")
    payloads = {item.object_id: item.payload for item in blobs}
    evidence = ExportEvidence(
        source_revision=source_revision,
        source_tree=identity.source_tree,
        source_epoch=identity.source_epoch,
        built_at_utc=identity.built_at_utc,
        file_count=len(files),
        total_bytes=sum(len(payloads[item.object_id]) for item in files),
        inventory_sha256=_inventory_digest(files, payloads),
    )
    return evidence, files, payloads


def _is_reparse_point(info: os.stat_result) -> bool:
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(flag and getattr(info, "st_file_attributes", 0) & flag)


def _materialized_inventory(root: Path) -> tuple[dict[str, Path], set[str]]:
    """Inventory one ordinary directory without following filesystem links."""
    if not os.path.lexists(root):
        raise CommitTreeError(f"materialized source root does not exist: {root}")
    try:
        root_info = root.lstat()
    except OSError as exc:
        raise CommitTreeError(f"cannot inspect materialized source root: {root}") from exc
    if (
        not stat.S_ISDIR(root_info.st_mode)
        or stat.S_ISLNK(root_info.st_mode)
        or _is_reparse_point(root_info)
    ):
        raise CommitTreeError("materialized source root must be an ordinary directory")

    files: dict[str, Path] = {}
    directories: set[str] = set()
    normalized: set[str] = set()
    pending: list[tuple[tuple[str, ...], Path]] = [((), root)]
    while pending:
        parts, directory = pending.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda item: item.name)
        except OSError as exc:
            raise CommitTreeError(f"cannot inspect materialized source: {directory}") from exc
        for entry in entries:
            try:
                raw_name = entry.name.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise CommitTreeError("materialized source name is not valid UTF-8") from exc
            name = _validate_component(raw_name)
            child_parts = (*parts, name)
            relative = PurePosixPath(*child_parts).as_posix()
            key = unicodedata.normalize("NFC", relative).casefold()
            if key in normalized:
                raise CommitTreeError("materialized source has colliding paths")
            normalized.add(key)
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise CommitTreeError(
                    f"cannot inspect materialized source entry: {relative}"
                ) from exc
            if stat.S_ISLNK(info.st_mode) or _is_reparse_point(info):
                raise CommitTreeError(
                    f"materialized source contains a filesystem link: {relative}"
                )
            path = Path(entry.path)
            if stat.S_ISDIR(info.st_mode):
                directories.add(relative)
                pending.append((child_parts, path))
            elif stat.S_ISREG(info.st_mode):
                files[relative] = path
            else:
                raise CommitTreeError(
                    f"materialized source contains a non-regular entry: {relative}"
                )
    return files, directories


def materialized_file_inventory(root: Path) -> dict[str, Path]:
    """Return the fail-closed regular-file inventory of one ordinary tree."""
    files, _directories = _materialized_inventory(root)
    return files


def _validated_extra_paths(paths: tuple[str, ...]) -> set[str]:
    validated: set[str] = set()
    for path in paths:
        candidate = PurePosixPath(path)
        if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
            raise CommitTreeError("allowed generated source path is unsafe")
        normalized_parts = []
        for component in candidate.parts:
            try:
                raw_component = component.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise CommitTreeError(
                    "allowed generated source path is not UTF-8"
                ) from exc
            normalized_parts.append(_validate_component(raw_component))
        normalized = PurePosixPath(*normalized_parts).as_posix()
        if normalized != path or normalized in validated:
            raise CommitTreeError("allowed generated source path is ambiguous")
        validated.add(normalized)
    return validated


def _parent_directories(paths: set[str]) -> set[str]:
    parents: set[str] = set()
    for path in paths:
        candidate = PurePosixPath(path)
        for index in range(1, len(candidate.parts)):
            parents.add(PurePosixPath(*candidate.parts[:index]).as_posix())
    return parents


def verify_exported_commit(
    root: Path,
    source_revision: str,
    source_root: Path,
    *,
    allowed_extra_files: tuple[str, ...] = (),
) -> ExportEvidence:
    """Re-authenticate an existing export against the selected Git closure."""
    if OBJECT_ID.fullmatch(source_revision) is None:
        raise CommitTreeError("source revision must be an exact lowercase 40-hex SHA-1")
    try:
        root = root.resolve(strict=True)
    except OSError as exc:
        raise CommitTreeError("repository root does not exist") from exc
    if not root.is_dir():
        raise CommitTreeError("repository root is not a directory")
    _repository_boundary(root)
    evidence, expected_files, payloads = _inspect_selected_closure(
        root, source_revision
    )
    allowed = _validated_extra_paths(allowed_extra_files)
    actual_files, actual_directories = _materialized_inventory(source_root)
    expected_paths = {item.path for item in expected_files}
    if set(actual_files) != expected_paths | allowed:
        raise CommitTreeError("materialized source inventory differs from selected commit")
    if actual_directories != _parent_directories(expected_paths | allowed):
        raise CommitTreeError(
            "materialized source directory inventory differs from selected commit"
        )

    for item in expected_files:
        try:
            actual = actual_files[item.path].read_bytes()
        except OSError as exc:
            raise CommitTreeError(
                f"cannot read materialized source file: {item.path}"
            ) from exc
        if actual != payloads[item.object_id]:
            raise CommitTreeError(
                f"materialized source file differs from selected commit: {item.path}"
            )
        if os.name != "nt":
            executable = bool(actual_files[item.path].stat().st_mode & 0o111)
            if executable != (item.mode == "100755"):
                raise CommitTreeError(
                    f"materialized source mode differs from selected commit: {item.path}"
                )
    final_files, final_directories = _materialized_inventory(source_root)
    if set(final_files) != set(actual_files) or final_directories != actual_directories:
        raise CommitTreeError("materialized source changed during verification")
    return evidence


def inspect_commit(root: Path, source_revision: str) -> ExportEvidence:
    """Authenticate one selected commit closure without creating output."""
    if OBJECT_ID.fullmatch(source_revision) is None:
        raise CommitTreeError("source revision must be an exact lowercase 40-hex SHA-1")
    try:
        root = root.resolve(strict=True)
    except OSError as exc:
        raise CommitTreeError("repository root does not exist") from exc
    if not root.is_dir():
        raise CommitTreeError("repository root is not a directory")
    _repository_boundary(root)
    evidence, _files, _payloads = _inspect_selected_closure(root, source_revision)
    return evidence


def export_commit(root: Path, source_revision: str, output: Path) -> ExportEvidence:
    """Export the authenticated source tree of one exact commit into a new path."""
    if OBJECT_ID.fullmatch(source_revision) is None:
        raise CommitTreeError("source revision must be an exact lowercase 40-hex SHA-1")
    try:
        root = root.resolve(strict=True)
    except OSError as exc:
        raise CommitTreeError("repository root does not exist") from exc
    lexical_output = Path(os.path.abspath(output))
    if lexical_output == root or lexical_output in root.parents:
        raise CommitTreeError("export output cannot contain the repository")
    if os.path.lexists(output):
        raise CommitTreeError(f"export output already exists: {output}")
    output = output.resolve(strict=False)
    if not root.is_dir():
        raise CommitTreeError("repository root is not a directory")
    if output == root or output in root.parents:
        raise CommitTreeError("export output cannot contain the repository")
    if output.exists():
        raise CommitTreeError(f"export output already exists: {output}")

    boundary = _repository_boundary(root)
    for metadata in {boundary.git_directory, boundary.common_git_directory}:
        if _inside(output, metadata):
            raise CommitTreeError("export output cannot be inside Git metadata")

    evidence, files, payloads = _inspect_selected_closure(root, source_revision)

    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.mkdir()
        for item in files:
            relative = PurePosixPath(item.path)
            target = output.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(payloads[item.object_id])
            os.chmod(target, 0o755 if item.mode == "100755" else 0o644)
    except OSError as exc:
        raise CommitTreeError(f"cannot materialize commit tree: {exc}") from exc

    return evidence


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
        f"{evidence.source_revision} | {evidence.file_count} files | "
        f"{evidence.total_bytes} bytes | {evidence.inventory_sha256}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
