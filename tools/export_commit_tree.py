"""Materialize one exact Sector commit without reading mutable worktree files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

OBJECT_RE = re.compile(r"^[0-9a-f]{40}$")
WINDOWS_FORBIDDEN = frozenset('<>:"\\|?*')
WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


class CommitExportError(ValueError):
    """Raised when an exact raw commit tree cannot be exported safely."""


@dataclass(frozen=True)
class TreeEntry:
    mode: str
    object_id: str
    path: str


@dataclass(frozen=True)
class ExportSummary:
    source_revision: str
    file_count: int
    total_bytes: int
    inventory_sha256: str


def _git_command(root: Path, *arguments: str) -> list[str]:
    return [
        "git",
        "--no-replace-objects",
        "-C",
        str(root),
        *arguments,
    ]


def _git_bytes(
    root: Path, *arguments: str, input_bytes: bytes | None = None
) -> bytes:
    try:
        result = subprocess.run(
            _git_command(root, *arguments),
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        raise CommitExportError("cannot execute Git commit inspection") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        suffix = f": {detail}" if detail else ""
        raise CommitExportError(f"Git commit inspection failed{suffix}")
    return result.stdout


def _safe_path(path: str) -> PurePosixPath:
    candidate = PurePosixPath(path)
    if (
        not path
        or candidate.is_absolute()
        or candidate.as_posix() != path
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise CommitExportError(f"unsafe commit path: {path!r}")
    for part in candidate.parts:
        if (
            part.endswith((" ", "."))
            or any(ord(character) < 32 for character in part)
            or any(character in WINDOWS_FORBIDDEN for character in part)
            or part.split(".", 1)[0].rstrip(" .").upper() in WINDOWS_RESERVED
        ):
            raise CommitExportError(f"Windows-unsafe commit path: {path!r}")
    return candidate


def _parse_tree(raw: bytes) -> list[TreeEntry]:
    entries: list[TreeEntry] = []
    normalized_paths: dict[str, str] = {}
    for record in (item for item in raw.split(b"\0") if item):
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, object_type, object_id = metadata.decode("ascii").split(" ")
            path = raw_path.decode("utf-8")
        except (UnicodeDecodeError, ValueError) as exc:
            raise CommitExportError("commit tree inventory is malformed") from exc
        _safe_path(path)
        if object_type != "blob" or mode not in {"100644", "100755"}:
            raise CommitExportError(f"unsupported commit entry: {path}")
        if OBJECT_RE.fullmatch(object_id) is None:
            raise CommitExportError(f"invalid blob identity for commit path: {path}")
        normalized = unicodedata.normalize("NFC", path).casefold()
        previous = normalized_paths.get(normalized)
        if previous is not None:
            raise CommitExportError(
                f"case- or normalization-colliding commit paths: {previous}, {path}"
            )
        normalized_paths[normalized] = path
        entries.append(TreeEntry(mode=mode, object_id=object_id, path=path))
    if not entries:
        raise CommitExportError("commit tree contains no regular files")

    file_paths = set(normalized_paths)
    for normalized, original in normalized_paths.items():
        parts = PurePosixPath(normalized).parts
        for length in range(1, len(parts)):
            prefix = "/".join(parts[:length])
            if prefix in file_paths:
                raise CommitExportError(
                    f"commit path is both a file and directory: {original}"
                )
    return sorted(entries, key=lambda entry: entry.path)


def _parse_batch(raw: bytes, entries: list[TreeEntry]) -> list[bytes]:
    payloads: list[bytes] = []
    cursor = 0
    for entry in entries:
        header_end = raw.find(b"\n", cursor)
        if header_end < 0:
            raise CommitExportError("Git blob batch ended before its header")
        header = raw[cursor:header_end]
        cursor = header_end + 1
        try:
            object_id, object_type, raw_size = header.decode("ascii").split(" ")
            size = int(raw_size)
        except (UnicodeDecodeError, ValueError) as exc:
            raise CommitExportError("Git blob batch header is malformed") from exc
        if (
            object_id != entry.object_id
            or object_type != "blob"
            or size < 0
            or cursor + size >= len(raw)
        ):
            raise CommitExportError(f"unexpected Git blob response for {entry.path}")
        payload = raw[cursor : cursor + size]
        cursor += size
        if raw[cursor : cursor + 1] != b"\n":
            raise CommitExportError(f"Git blob terminator is missing for {entry.path}")
        cursor += 1
        digest = hashlib.sha1(
            b"blob " + str(size).encode("ascii") + b"\0" + payload
        ).hexdigest()
        if digest != entry.object_id:
            raise CommitExportError(f"Git blob content hash differs for {entry.path}")
        payloads.append(payload)
    if cursor != len(raw):
        raise CommitExportError("Git blob batch contains trailing output")
    return payloads


def _inventory_digest(entries: list[TreeEntry], payloads: list[bytes]) -> str:
    digest = hashlib.sha256()
    for entry, payload in zip(entries, payloads, strict=True):
        record = json.dumps(
            [entry.path, entry.mode, entry.object_id, len(payload)],
            ensure_ascii=True,
            separators=(",", ":"),
        )
        digest.update(record.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def export_commit_tree(
    root: Path, source_revision: str, output: Path
) -> ExportSummary:
    """Write raw regular-file blobs from one exact commit to a new directory."""
    if OBJECT_RE.fullmatch(source_revision) is None:
        raise CommitExportError(
            "source revision must be an exact lowercase 40-hex commit"
        )
    root = root.resolve()
    output = output.resolve()
    if not root.is_dir():
        raise CommitExportError(f"repository root is missing: {root}")
    if output.exists():
        raise CommitExportError(f"export output already exists: {output}")
    if output == root or output in root.parents:
        raise CommitExportError("export output cannot contain the repository root")

    try:
        git_dir = Path(
            _git_bytes(
                root,
                "rev-parse",
                "--path-format=absolute",
                "--git-dir",
            )
            .decode("utf-8")
            .strip()
        ).resolve()
    except UnicodeDecodeError as exc:
        raise CommitExportError("Git metadata path is malformed") from exc
    if output == git_dir or git_dir in output.parents:
        raise CommitExportError("export output cannot be inside Git metadata")

    _git_bytes(
        root,
        "fsck",
        "--strict",
        "--no-reflogs",
        "--no-dangling",
        source_revision,
    )
    object_type = _git_bytes(root, "cat-file", "-t", source_revision)
    if object_type != b"commit\n":
        raise CommitExportError("source revision does not identify a commit object")
    tree = _git_bytes(
        root,
        "ls-tree",
        "-r",
        "-z",
        "--full-tree",
        source_revision,
    )
    entries = _parse_tree(tree)
    requests = b"".join(
        entry.object_id.encode("ascii") + b"\n" for entry in entries
    )
    batch = _git_bytes(root, "cat-file", "--batch", input_bytes=requests)
    payloads = _parse_batch(batch, entries)

    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.mkdir()
        for entry, payload in zip(entries, payloads, strict=True):
            relative = _safe_path(entry.path)
            target = output.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(payload)
            os.chmod(target, 0o755 if entry.mode == "100755" else 0o644)
    except OSError as exc:
        raise CommitExportError(f"cannot materialize commit tree: {exc}") from exc

    return ExportSummary(
        source_revision=source_revision,
        file_count=len(entries),
        total_bytes=sum(len(payload) for payload in payloads),
        inventory_sha256=_inventory_digest(entries, payloads),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        summary = export_commit_tree(
            arguments.root,
            arguments.source_revision,
            arguments.output,
        )
    except CommitExportError as exc:
        print(f"commit export failed: {exc}", file=sys.stderr)
        return 2
    print(
        "exact commit exported: "
        f"{summary.source_revision} | {summary.file_count} files | "
        f"{summary.total_bytes} bytes | {summary.inventory_sha256}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
