"""Canonicalize PyInstaller's stored base-library ZIP member order."""

from __future__ import annotations

import argparse
import os
import stat
import sys
import tempfile
import zipfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
WINDOWS_FILE_ATTRIBUTES = 0x01800000


class ArchiveCanonicalizationError(ValueError):
    """Raised when a generated archive is unsafe or outside the frozen profile."""


def _safe_member_name(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not name.startswith("/") and "\\" not in name and all(
        part not in {"", ".", ".."} for part in path.parts
    )


def canonicalize_archive(path: Path) -> int:
    """Rewrite one generated archive with a deterministic sorted member order."""
    archive = path.resolve()
    if not archive.is_file():
        raise ArchiveCanonicalizationError(f"archive is missing: {archive}")

    rows: list[tuple[str, bytes]] = []
    names: set[str] = set()
    folded_names: dict[str, str] = {}
    try:
        with zipfile.ZipFile(archive, "r") as source:
            if source.comment:
                raise ArchiveCanonicalizationError("archive comment is not permitted")
            for info in source.infolist():
                name = info.filename
                if info.is_dir() or not _safe_member_name(name):
                    raise ArchiveCanonicalizationError(
                        f"unsafe archive member: {name!r}"
                    )
                if name in names:
                    raise ArchiveCanonicalizationError(
                        f"duplicate archive member: {name}"
                    )
                folded = name.casefold()
                previous = folded_names.get(folded)
                if previous is not None and previous != name:
                    raise ArchiveCanonicalizationError(
                        f"case-colliding archive members: {previous}, {name}"
                    )
                if info.flag_bits & 0x1:
                    raise ArchiveCanonicalizationError(
                        f"encrypted archive member is not permitted: {name}"
                    )
                if info.compress_type != zipfile.ZIP_STORED:
                    raise ArchiveCanonicalizationError(
                        f"base-library member is not stored: {name}"
                    )
                if info.create_system == 3 and stat.S_ISLNK(info.external_attr >> 16):
                    raise ArchiveCanonicalizationError(
                        f"symbolic-link archive member is not permitted: {name}"
                    )
                names.add(name)
                folded_names[folded] = name
                rows.append((name, source.read(info)))
    except zipfile.BadZipFile as exc:
        raise ArchiveCanonicalizationError("archive is not a valid ZIP file") from exc
    if not rows:
        raise ArchiveCanonicalizationError("archive contains no members")

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{archive.name}.", suffix=".canonical", dir=archive.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary, "w", allowZip64=True) as target:
            for name, content in sorted(rows, key=lambda row: row[0]):
                info = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
                info.compress_type = zipfile.ZIP_STORED
                info.create_system = 0
                info.external_attr = WINDOWS_FILE_ATTRIBUTES
                target.writestr(info, content)
        os.replace(temporary, archive)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return len(rows)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        count = canonicalize_archive(arguments.archive)
    except (OSError, ArchiveCanonicalizationError) as exc:
        print(f"archive canonicalization failed: {exc}", file=sys.stderr)
        return 2
    print(f"canonicalized {count} stored PyInstaller base-library members")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
