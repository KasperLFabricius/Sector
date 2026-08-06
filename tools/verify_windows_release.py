"""Fail-closed, standard-library checks for a Sector Windows release package."""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_SOURCE_IDENTITY = {
    "__version__": "0.91",
    "__product_name__": "Sector",
    "__description__": "Structural-analysis and design calculation tool",
    "__author__": "Kasper Lindskov Fabricius",
    "__licensee__": "Sweco Danmark A/S",
    "__copyright__": (
        "Copyright (c) 2026 Kasper Lindskov Fabricius. All rights reserved."
    ),
}
EXPECTED_MANIFEST_KEYS = {
    "product_name",
    "description",
    "sector_version",
    "source_revision",
    "author",
    "licensee",
    "copyright",
    "built_at_utc",
}


class ReleaseVerificationError(ValueError):
    """Raised when a release input is incomplete or inconsistent."""


def _literal_assignments(path: Path, names: set[str]) -> dict[str, str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeError) as exc:
        raise ReleaseVerificationError(f"cannot read source identity: {exc}") from exc
    values: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in names:
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, TypeError) as exc:
            raise ReleaseVerificationError(
                f"source identity {target.id} is not a literal"
            ) from exc
        if not isinstance(value, str) or not value.strip():
            raise ReleaseVerificationError(f"source identity {target.id} is invalid")
        values[target.id] = value
    return values


def _require_exact_file(path: Path, expected: str) -> None:
    try:
        actual = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ReleaseVerificationError(f"cannot read {path}: {exc}") from exc
    if actual != expected:
        raise ReleaseVerificationError(f"packaged file differs from source: {path.name}")


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseVerificationError(f"cannot read package manifest: {exc}") from exc
    if not isinstance(value, dict):
        raise ReleaseVerificationError("package manifest must be an object")
    return value


def _validate_timestamp(value: Any) -> None:
    if not isinstance(value, str) or not value.endswith("+00:00"):
        raise ReleaseVerificationError("built_at_utc must be an explicit UTC timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise ReleaseVerificationError("built_at_utc is malformed") from exc
    if parsed.tzinfo != dt.timezone.utc:
        raise ReleaseVerificationError("built_at_utc must use the UTC offset")


def verify_source(root: Path, source_revision: str) -> None:
    """Validate immutable source identities before installing build dependencies."""
    if COMMIT_RE.fullmatch(source_revision) is None:
        raise ReleaseVerificationError(
            "source revision must be an exact lowercase 40-hex commit"
        )
    values = _literal_assignments(
        root / "sector" / "__init__.py", set(EXPECTED_SOURCE_IDENTITY)
    )
    if values != EXPECTED_SOURCE_IDENTITY:
        raise ReleaseVerificationError("Sector source identity is incomplete or changed")

    resource = root / "packaging" / "windows_version_info.txt"
    try:
        resource_text = resource.read_text(encoding="utf-8")
        ast.parse(resource_text, filename=str(resource))
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise ReleaseVerificationError(f"Windows version resource is invalid: {exc}") from exc
    required_tokens = (
        "filevers=(0, 91, 0, 0)",
        "prodvers=(0, 91, 0, 0)",
        "StringStruct('FileVersion', '0.91.0.0')",
        "StringStruct('ProductVersion', '0.91.0.0')",
        "StringStruct('ProductName', 'Sector')",
        "StringStruct('OriginalFilename', 'Sector.exe')",
        "Licensed to Sweco Danmark A/S for internal organisational use only.",
    )
    for token in required_tokens:
        if resource_text.count(token) != 1:
            raise ReleaseVerificationError(f"Windows resource identity is missing: {token}")
    if "CompanyName" in resource_text or "Publisher" in resource_text:
        raise ReleaseVerificationError("Windows resource advertises a company identity")


def verify_package(root: Path, package: Path, source_revision: str) -> None:
    """Validate a built package before any signing secret is exposed."""
    verify_source(root, source_revision)
    required = {
        "executable": package / "Sector.exe",
        "app": package / "_internal" / "app" / "sector_app.py",
        "core": package / "_internal" / "sector" / "__init__.py",
        "manifest": package / "_internal" / "sector" / "sector_build_info.json",
        "license": package / "LICENSE.txt",
        "notices": package / "THIRD_PARTY_NOTICES.txt",
    }
    missing = [label for label, path in required.items() if not path.is_file()]
    if missing:
        raise ReleaseVerificationError(
            f"package is missing required files: {', '.join(sorted(missing))}"
        )
    if required["executable"].stat().st_size <= 0:
        raise ReleaseVerificationError("Sector.exe is empty")
    _require_exact_file(required["license"], (root / "LICENSE").read_text(encoding="utf-8"))

    notices = required["notices"].read_text(encoding="utf-8")
    for token in ("SECTOR THIRD-PARTY NOTICES", "numpy", "streamlit"):
        if token.casefold() not in notices.casefold():
            raise ReleaseVerificationError(
                f"third-party notice bundle is missing {token}"
            )

    manifest = _read_json_object(required["manifest"])
    if set(manifest) != EXPECTED_MANIFEST_KEYS:
        raise ReleaseVerificationError("package manifest keys are incomplete or unknown")
    expected = {
        "product_name": EXPECTED_SOURCE_IDENTITY["__product_name__"],
        "description": EXPECTED_SOURCE_IDENTITY["__description__"],
        "sector_version": EXPECTED_SOURCE_IDENTITY["__version__"],
        "source_revision": source_revision,
        "author": EXPECTED_SOURCE_IDENTITY["__author__"],
        "licensee": EXPECTED_SOURCE_IDENTITY["__licensee__"],
        "copyright": EXPECTED_SOURCE_IDENTITY["__copyright__"],
    }
    for key, value in expected.items():
        if manifest[key] != value:
            raise ReleaseVerificationError(f"unexpected package manifest field: {key}")
    _validate_timestamp(manifest["built_at_utc"])


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--package", type=Path)
    parser.add_argument("--preflight", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.root.resolve()
    verify_source(root, args.source_revision)
    if args.preflight:
        if args.package is not None:
            raise ReleaseVerificationError("preflight does not accept a package")
    else:
        if args.package is None:
            raise ReleaseVerificationError("package verification requires --package")
        verify_package(root, args.package.resolve(), args.source_revision)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
