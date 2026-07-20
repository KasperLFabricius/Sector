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

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


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


def distributions_from_lock(lock_path: Path,
                            installed: Iterable | None = None) -> list:
    """Return exactly the installed distributions selected by a hashed lock.

    Hash lines and pip-compile provenance comments are ignored; each active
    requirement must use an exact ``==`` pin. Installed runner-only packages are
    excluded, and a missing or mismatched locked package fails the build.
    """
    pinned: dict[str, tuple[str, str]] = {}
    for raw in lock_path.read_text(encoding="utf-8").splitlines():
        if not raw or raw[0].isspace():
            continue
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        requirement = Requirement(line.removesuffix("\\").strip())
        if requirement.marker is not None and not requirement.marker.evaluate():
            continue
        specs = list(requirement.specifier)
        if len(specs) != 1 or specs[0].operator != "==":
            raise ValueError(f"Lock entry is not exactly pinned: {line}")
        key = canonicalize_name(requirement.name)
        value = (requirement.name, specs[0].version)
        if key in pinned and pinned[key] != value:
            raise ValueError(f"Conflicting lock entries for {requirement.name}")
        pinned[key] = value

    available: dict[str, list] = {}
    for dist in list(installed or metadata.distributions()):
        name = _clean(dist.metadata.get("Name"))
        if name:
            available.setdefault(canonicalize_name(name), []).append(dist)

    selected = []
    for key, (name, version) in sorted(pinned.items()):
        matches = [dist for dist in available.get(key, [])
                   if _clean(getattr(dist, "version", "")) == version]
        if not matches:
            installed_versions = sorted(
                {_clean(getattr(dist, "version", ""))
                 for dist in available.get(key, [])}
            )
            detail = ", ".join(v for v in installed_versions if v) or "not installed"
            raise RuntimeError(
                f"Locked distribution {name}=={version} is unavailable ({detail})"
            )
        selected.append(matches[0])
    return selected


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
        "hash-locked build dependency set and may include build-only packages.",
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
    parser.add_argument(
        "--requirements",
        type=Path,
        default=Path("requirements-build.txt"),
        help="pip-compile lock defining the package inventory",
    )
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        build_notice(
            distributions=distributions_from_lock(args.requirements),
            tabulator_license=args.tabulator_license,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
