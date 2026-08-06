"""Compare two controlled Sector package trees without trusting build output."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import stat
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
EPOCH_RE = re.compile(r"^(0|[1-9][0-9]*)$")


class PackageReproducibilityError(ValueError):
    """Raised when controlled package evidence is incomplete or differs."""


def parse_source_date_epoch(value: object) -> int:
    """Return one canonical, UTC-representable source date epoch."""
    if isinstance(value, bool):
        raise PackageReproducibilityError(
            "source date epoch must be a non-negative integer"
        )
    text = str(value).strip()
    if EPOCH_RE.fullmatch(text) is None:
        raise PackageReproducibilityError(
            "source date epoch must be a non-negative integer"
        )
    epoch = int(text)
    try:
        dt.datetime.fromtimestamp(epoch, tz=dt.timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise PackageReproducibilityError(
            "source date epoch is outside the supported UTC range"
        ) from exc
    return epoch


def source_date_utc(epoch: int) -> str:
    """Format the controlled epoch with explicit UTC seconds."""
    return dt.datetime.fromtimestamp(epoch, tz=dt.timezone.utc).isoformat(
        timespec="seconds"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def package_inventory(root: Path) -> dict[str, tuple[int, str]]:
    """Inventory every regular package file by path, length and SHA-256."""
    root = root.resolve()
    if not root.is_dir():
        raise PackageReproducibilityError(f"package directory is missing: {root}")

    inventory: dict[str, tuple[int, str]] = {}
    folded_paths: dict[str, str] = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        try:
            mode = path.lstat().st_mode
        except OSError as exc:
            raise PackageReproducibilityError(
                f"cannot inspect package entry: {relative}"
            ) from exc
        if stat.S_ISDIR(mode):
            continue
        if stat.S_ISLNK(mode):
            raise PackageReproducibilityError(
                f"package contains a symbolic link: {relative}"
            )
        if not stat.S_ISREG(mode):
            raise PackageReproducibilityError(
                f"package contains a non-regular entry: {relative}"
            )
        folded = relative.casefold()
        previous = folded_paths.get(folded)
        if previous is not None and previous != relative:
            raise PackageReproducibilityError(
                f"package contains case-colliding paths: {previous}, {relative}"
            )
        folded_paths[folded] = relative
        try:
            size = path.stat().st_size
            digest = _sha256(path)
        except OSError as exc:
            raise PackageReproducibilityError(
                f"cannot hash package entry: {relative}"
            ) from exc
        inventory[relative] = (size, digest)
    if not inventory:
        raise PackageReproducibilityError("package directory contains no files")
    return inventory


def package_tree_sha256(inventory: Mapping[str, tuple[int, str]]) -> str:
    """Hash a canonical ordered representation of the complete inventory."""
    digest = hashlib.sha256()
    for relative in sorted(inventory):
        size, file_digest = inventory[relative]
        record = json.dumps(
            [relative, size, file_digest],
            ensure_ascii=True,
            separators=(",", ":"),
        )
        digest.update(record.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _difference_summary(
    first: Mapping[str, tuple[int, str]],
    second: Mapping[str, tuple[int, str]],
) -> str:
    first_only = sorted(set(first).difference(second))
    second_only = sorted(set(second).difference(first))
    changed = sorted(
        path for path in set(first).intersection(second) if first[path] != second[path]
    )
    parts = []
    for label, paths in (
        ("first only", first_only),
        ("second only", second_only),
        ("byte-different", changed),
    ):
        if paths:
            preview = ", ".join(paths[:10])
            if len(paths) > 10:
                preview += f", ... ({len(paths)} total)"
            parts.append(f"{label}: {preview}")
    return "; ".join(parts)


def compare_packages(
    first_root: Path,
    second_root: Path,
    source_revision: str,
    source_date_epoch: object,
) -> dict[str, Any]:
    """Prove two unsigned package trees are byte-identical."""
    first_root = first_root.resolve()
    second_root = second_root.resolve()
    if first_root == second_root:
        raise PackageReproducibilityError(
            "controlled package roots must be distinct"
        )
    if COMMIT_RE.fullmatch(source_revision) is None:
        raise PackageReproducibilityError(
            "source revision must be an exact lowercase 40-hex commit"
        )
    epoch = parse_source_date_epoch(source_date_epoch)
    first = package_inventory(first_root)
    second = package_inventory(second_root)
    if first != second:
        raise PackageReproducibilityError(
            f"controlled package trees differ: {_difference_summary(first, second)}"
        )
    return {
        "schema_version": 1,
        "comparison": "byte-identical-controlled-unsigned-package",
        "source_revision": source_revision,
        "source_date_epoch": epoch,
        "source_date_utc": source_date_utc(epoch),
        "file_count": len(first),
        "total_bytes": sum(size for size, _digest in first.values()),
        "package_tree_sha256": package_tree_sha256(first),
    }


def write_evidence(path: Path, evidence: Mapping[str, Any]) -> None:
    """Write a new deterministic evidence record without overwriting artifacts."""
    path = path.resolve()
    if path.exists():
        raise PackageReproducibilityError(f"evidence path already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(evidence), indent=2, ensure_ascii=True) + "\n",
        encoding="ascii",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first", type=Path, required=True)
    parser.add_argument("--second", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--source-date-epoch", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        first = arguments.first.resolve()
        second = arguments.second.resolve()
        output = arguments.output.resolve()
        for package in (first, second):
            if output == package or package in output.parents:
                raise PackageReproducibilityError(
                    "evidence output must remain outside both package trees"
                )
        evidence = compare_packages(
            first,
            second,
            arguments.source_revision,
            arguments.source_date_epoch,
        )
        write_evidence(output, evidence)
    except (OSError, PackageReproducibilityError) as exc:
        print(f"package reproducibility failed: {exc}", file=sys.stderr)
        return 2
    print(
        "controlled unsigned package is byte-identical: "
        f"{evidence['package_tree_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
