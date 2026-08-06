"""Fail closed when a Sector package could include uncommitted source bytes."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
PACKAGED_SOURCE_ROOTS = ("app", "sector", "assets")


class PackagedSourceError(ValueError):
    """Raised when package inputs are not determined by one exact commit."""


def _git_bytes(root: Path, *arguments: str, input_bytes: bytes | None = None) -> bytes:
    command = ["git", "-C", str(root), *arguments]
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            input=input_bytes,
            check=False,
        )
    except OSError as exc:
        raise PackagedSourceError("cannot execute Git source inspection") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        suffix = f": {detail}" if detail else ""
        raise PackagedSourceError(f"Git source inspection failed{suffix}")
    return result.stdout


def _exact_head(root: Path) -> str:
    raw = _git_bytes(root, "rev-parse", "--verify", "HEAD")
    try:
        head = raw.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise PackagedSourceError("Git HEAD is not an ASCII commit identity") from exc
    if COMMIT_RE.fullmatch(head) is None:
        raise PackagedSourceError("Git HEAD is not an exact lowercase commit")
    return head


def _path_preview(raw: bytes) -> str:
    paths = [part for part in raw.split(b"\0") if part]
    preview = [part.decode("utf-8", errors="replace") for part in paths[:5]]
    text = ", ".join(preview)
    if len(paths) > 5:
        text += f", ... ({len(paths)} total)"
    return text


def _head_blob_inventory(root: Path) -> list[tuple[str, str]]:
    """Return safe regular-file paths and blob IDs from the exact HEAD tree."""
    raw = _git_bytes(root, "ls-tree", "-r", "-z", "HEAD")
    inventory: list[tuple[str, str]] = []
    folded: dict[str, str] = {}
    for record in (item for item in raw.split(b"\0") if item):
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, object_type, object_id = metadata.decode("ascii").split(" ")
            path = raw_path.decode("utf-8")
        except (UnicodeDecodeError, ValueError) as exc:
            raise PackagedSourceError("HEAD tree inventory is malformed") from exc
        candidate = Path(path)
        if (
            object_type != "blob"
            or mode not in {"100644", "100755"}
            or COMMIT_RE.fullmatch(object_id) is None
            or not path
            or candidate.is_absolute()
            or ".." in candidate.parts
            or "\r" in path
            or "\n" in path
        ):
            raise PackagedSourceError(
                f"HEAD contains an unsupported tracked entry: {path}"
            )
        previous = folded.get(path.casefold())
        if previous is not None and previous != path:
            raise PackagedSourceError(
                f"HEAD contains case-colliding tracked paths: {previous}, {path}"
            )
        folded[path.casefold()] = path
        inventory.append((path, object_id))
    if not inventory:
        raise PackagedSourceError("HEAD contains no tracked files")
    return inventory


def _verify_tracked_bytes(root: Path) -> None:
    """Compare filtered worktree bytes to HEAD without trusting index hints."""
    staged = _git_bytes(
        root,
        "diff-index",
        "--cached",
        "--name-only",
        "-z",
        "HEAD",
        "--",
    )
    if staged:
        raise PackagedSourceError(
            f"staged source tree differs from HEAD: {_path_preview(staged)}"
        )

    expected = _head_blob_inventory(root)
    path_input = ("\n".join(path for path, _object_id in expected) + "\n").encode(
        "utf-8"
    )
    raw_actual = _git_bytes(
        root,
        "hash-object",
        "--stdin-paths",
        input_bytes=path_input,
    )
    try:
        actual = raw_actual.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise PackagedSourceError("worktree blob inventory is malformed") from exc
    if len(actual) != len(expected):
        raise PackagedSourceError("worktree blob inventory is incomplete")
    changed = [
        path
        for (path, object_id), actual_id in zip(expected, actual, strict=True)
        if actual_id != object_id
    ]
    if changed:
        preview = ", ".join(changed[:5])
        if len(changed) > 5:
            preview += f", ... ({len(changed)} total)"
        raise PackagedSourceError(f"tracked worktree bytes differ from HEAD: {preview}")


def verify_packaged_source(root: Path, source_revision: str) -> None:
    """Prove packaged source roots contain no uncommitted payload."""
    if COMMIT_RE.fullmatch(source_revision) is None:
        raise PackagedSourceError(
            "source revision must be an exact lowercase 40-hex commit"
        )
    root = root.resolve()
    if not root.is_dir():
        raise PackagedSourceError(f"repository root is missing: {root}")

    head = _exact_head(root)
    if head != source_revision:
        raise PackagedSourceError("requested source revision is not current HEAD")

    _verify_tracked_bytes(root)

    # Deliberately omit --exclude-standard: ignored bytecode, native libraries,
    # caches and every other untracked entry are unsafe when the PyInstaller spec
    # recursively adds these directories as package data.
    untracked = _git_bytes(
        root,
        "ls-files",
        "--others",
        "-z",
        "--",
        *PACKAGED_SOURCE_ROOTS,
    )
    if untracked:
        raise PackagedSourceError(
            "untracked or ignored files exist inside packaged source trees: "
            f"{_path_preview(untracked)}"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        verify_packaged_source(arguments.root, arguments.source_revision)
    except PackagedSourceError as exc:
        print(f"packaged source verification failed: {exc}", file=sys.stderr)
        return 2
    print(f"packaged source verified at {arguments.source_revision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
