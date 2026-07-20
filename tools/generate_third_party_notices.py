"""Generate the legal-notice bundle shipped with the Windows application.

The inventory is derived from the installed, locked build environment so it
cannot silently drift away from the package dependency set. Available licence
and notice files are copied verbatim from distribution metadata. Build-only
distributions are intentionally retained: over-inclusion is safer and makes the
record reproducible without guessing which transitive files PyInstaller used.
"""

from __future__ import annotations

import argparse
from importlib import metadata
from pathlib import Path
from typing import Iterable


_NOTICE_NAMES = ("license", "licence", "copying", "notice")


def _clean(value: str | None) -> str:
    value = (value or "").strip()
    return "" if value.upper() in {"UNKNOWN", "NONE", "N/A"} else value


def _source_url(meta) -> str:
    for item in meta.get_all("Project-URL") or []:
        if "," in item:
            label, url = item.split(",", 1)
            if label.strip().lower() in {"homepage", "source", "repository"}:
                return url.strip()
    return _clean(meta.get("Home-page"))


def _licence_files(dist) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in sorted(dist.files or [], key=str):
        name = Path(str(item)).name.lower()
        if not name.startswith(_NOTICE_NAMES):
            continue
        path = Path(dist.locate_file(item))
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        text = raw.decode("utf-8", errors="replace").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        found.append((str(item).replace("\\", "/"), text))
    return found


def build_notice(distributions: Iterable | None = None,
                 tabulator_license: Path | None = None) -> str:
    """Return a deterministic consolidated notice for installed distributions."""
    distributions = list(distributions or metadata.distributions())
    records = []
    for dist in distributions:
        meta = dist.metadata
        name = _clean(meta.get("Name")) or "unnamed distribution"
        version = _clean(meta.get("Version")) or _clean(getattr(dist, "version", ""))
        records.append((name.casefold(), name, version, dist, meta))
    records.sort(key=lambda row: (row[0], row[2]))

    lines = [
        "SECTOR THIRD-PARTY NOTICES",
        "",
        "Sector itself is proprietary software. This inventory covers the",
        "installed locked build environment and may include build-only packages.",
        "Third-party components remain governed by their respective terms.",
        "",
    ]
    seen_packages: set[tuple[str, str]] = set()
    for key, name, version, dist, meta in records:
        identity = (key, version)
        if identity in seen_packages:
            continue
        seen_packages.add(identity)
        expression = _clean(meta.get("License-Expression"))
        declared = expression or _clean(meta.get("License"))
        url = _source_url(meta)
        files = _licence_files(dist)
        lines.extend([
            "=" * 78,
            f"{name} {version}".rstrip(),
            f"Declared licence: {declared or 'not stated in package metadata'}",
            f"Source: {url or 'not stated in package metadata'}",
        ])
        if files:
            for filename, text in files:
                lines.extend(["", f"--- {filename} ---", text])
        elif declared:
            lines.extend(["", declared])
        lines.append("")

    if tabulator_license is not None:
        tabulator_text = tabulator_license.read_text(encoding="utf-8").strip()
        lines.extend([
            "=" * 78,
            "Tabulator (embedded point-grid frontend)",
            "Source: https://tabulator.info/",
            "Declared licence: MIT",
            "",
            tabulator_text,
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--tabulator-license",
        type=Path,
        default=Path("app/point_grid_frontend/LICENSE"),
    )
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        build_notice(tabulator_license=args.tabulator_license), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
