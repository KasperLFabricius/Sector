"""Fail-closed, standard-library checks for a Sector Windows release package."""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
TREE_RE = COMMIT_RE
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
SOURCE_IDENTITY_SCHEMA = "sector-source-identity-v1"
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
    "schema",
    "source_tree",
    "source_epoch",
    "built_at_utc",
    "source_file_count",
    "source_total_bytes",
    "source_inventory_sha256",
}
SOURCE_IDENTITY_KEYS = {
    "schema",
    "source_revision",
    "source_tree",
    "source_epoch",
    "built_at_utc",
    "source_file_count",
    "source_total_bytes",
    "source_inventory_sha256",
}


def _load_exporter():
    path = Path(__file__).resolve().with_name("export_commit_tree.py")
    specification = importlib.util.spec_from_file_location(
        "sector_release_commit_inspector", path
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("cannot load the accepted exact-commit inspector")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


_EXPORTER = _load_exporter()
CommitTreeError = _EXPORTER.CommitTreeError
materialized_file_inventory = _EXPORTER.materialized_file_inventory
verify_exported_commit = _EXPORTER.verify_exported_commit
GENERATED_SOURCE_FILES = (
    "build/legal/THIRD_PARTY_NOTICES.txt",
    "build/sector_build_info.json",
)


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


def _require_exact_bytes(actual: Path, expected: Path) -> None:
    try:
        actual_bytes = actual.read_bytes()
        expected_bytes = expected.read_bytes()
    except OSError as exc:
        raise ReleaseVerificationError(f"cannot compare packaged source: {exc}") from exc
    if actual_bytes != expected_bytes:
        raise ReleaseVerificationError(
            f"packaged source file differs from verified export: {actual.name}"
        )


def _require_exact_tree(
    source: Path, packaged: Path, *, allowed_packaged_files: tuple[str, ...] = ()
) -> None:
    try:
        source_files = materialized_file_inventory(source)
        packaged_files = materialized_file_inventory(packaged)
    except CommitTreeError as exc:
        raise ReleaseVerificationError(f"cannot compare packaged source tree: {exc}") from exc
    allowed = set(allowed_packaged_files)
    if set(packaged_files) != set(source_files) | allowed:
        raise ReleaseVerificationError("packaged source tree differs from verified export")
    for relative, source_file in source_files.items():
        _require_exact_bytes(packaged_files[relative], source_file)


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseVerificationError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReleaseVerificationError(f"{label} must be an object")
    return value


def _source_timestamp(source_epoch: int) -> str:
    try:
        return dt.datetime.fromtimestamp(source_epoch, dt.timezone.utc).isoformat(
            timespec="seconds"
        )
    except (OSError, OverflowError, ValueError) as exc:
        raise ReleaseVerificationError("source epoch is outside the UTC range") from exc


def load_source_identity(path: Path, source_revision: str) -> dict[str, Any]:
    """Load and strictly validate create-only evidence from the exact exporter."""
    identity = _read_json_object(path, "source identity")
    if set(identity) != SOURCE_IDENTITY_KEYS:
        raise ReleaseVerificationError("source identity keys are incomplete or unknown")
    if identity["schema"] != SOURCE_IDENTITY_SCHEMA:
        raise ReleaseVerificationError("source identity schema is unsupported")
    if identity["source_revision"] != source_revision:
        raise ReleaseVerificationError("source identity revision differs from requested source")
    source_tree = identity["source_tree"]
    if not isinstance(source_tree, str) or TREE_RE.fullmatch(source_tree) is None:
        raise ReleaseVerificationError("source identity tree is not an exact SHA-1")
    epoch = identity["source_epoch"]
    if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 0:
        raise ReleaseVerificationError("source identity epoch is invalid")
    if identity["built_at_utc"] != _source_timestamp(epoch):
        raise ReleaseVerificationError("source identity timestamp differs from source epoch")
    for key, minimum in (("source_file_count", 1), ("source_total_bytes", 0)):
        value = identity[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ReleaseVerificationError(f"source identity field is invalid: {key}")
    digest = identity["source_inventory_sha256"]
    if not isinstance(digest, str) or DIGEST_RE.fullmatch(digest) is None:
        raise ReleaseVerificationError("source identity inventory digest is invalid")
    return identity


def authenticate_source_identity(
    path: Path,
    source_revision: str,
    repository_root: Path,
    source_root: Path,
) -> dict[str, Any]:
    """Bind source-identity evidence to the authenticated selected Git closure."""
    identity = load_source_identity(path, source_revision)
    try:
        evidence = verify_exported_commit(
            repository_root,
            source_revision,
            source_root,
            allowed_extra_files=GENERATED_SOURCE_FILES,
        )
    except CommitTreeError as exc:
        raise ReleaseVerificationError(
            f"cannot authenticate selected source commit: {exc}"
        ) from exc
    expected = {
        "schema": SOURCE_IDENTITY_SCHEMA,
        "source_revision": evidence.source_revision,
        "source_tree": evidence.source_tree,
        "source_epoch": evidence.source_epoch,
        "built_at_utc": evidence.built_at_utc,
        "source_file_count": evidence.file_count,
        "source_total_bytes": evidence.total_bytes,
        "source_inventory_sha256": evidence.inventory_sha256,
    }
    if identity != expected:
        raise ReleaseVerificationError(
            "source identity differs from the authenticated commit closure"
        )
    return identity


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


def verify_package(
    root: Path,
    package: Path,
    source_revision: str,
    source_identity_path: Path,
    repository_root: Path,
) -> None:
    """Validate a built package before any signing secret is exposed."""
    verify_source(root, source_revision)
    source_identity = authenticate_source_identity(
        source_identity_path, source_revision, repository_root, root
    )
    required = {
        "executable": package / "Sector.exe",
        "app": package / "_internal" / "app" / "sector_app.py",
        "core": package / "_internal" / "sector" / "__init__.py",
        "assets": package / "_internal" / "assets",
        "manifest": package / "_internal" / "sector" / "sector_build_info.json",
        "license": package / "LICENSE.txt",
        "notices": package / "THIRD_PARTY_NOTICES.txt",
    }
    missing = [
        label
        for label, path in required.items()
        if not (path.is_dir() if label == "assets" else path.is_file())
    ]
    if missing:
        raise ReleaseVerificationError(
            f"package is missing required files: {', '.join(sorted(missing))}"
        )
    if required["executable"].stat().st_size <= 0:
        raise ReleaseVerificationError("Sector.exe is empty")
    _require_exact_file(required["license"], (root / "LICENSE").read_text(encoding="utf-8"))
    _require_exact_bytes(
        required["notices"], root / "build" / "legal" / "THIRD_PARTY_NOTICES.txt"
    )
    _require_exact_tree(root / "app", package / "_internal" / "app")
    _require_exact_tree(
        root / "sector",
        package / "_internal" / "sector",
        allowed_packaged_files=("sector_build_info.json",),
    )
    _require_exact_tree(root / "assets", required["assets"])

    notices = required["notices"].read_text(encoding="utf-8")
    for token in ("SECTOR THIRD-PARTY NOTICES", "numpy", "streamlit"):
        if token.casefold() not in notices.casefold():
            raise ReleaseVerificationError(
                f"third-party notice bundle is missing {token}"
            )

    manifest = _read_json_object(required["manifest"], "package manifest")
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
        **source_identity,
    }
    for key, value in expected.items():
        if manifest[key] != value:
            raise ReleaseVerificationError(f"unexpected package manifest field: {key}")
    _require_exact_bytes(
        required["manifest"], root / "build" / "sector_build_info.json"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--package", type=Path)
    parser.add_argument("--source-identity", type=Path)
    parser.add_argument("--repository-root", type=Path)
    parser.add_argument("--preflight", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.root.resolve()
    verify_source(root, args.source_revision)
    if args.preflight:
        if (
            args.package is not None
            or args.source_identity is not None
            or args.repository_root is not None
        ):
            raise ReleaseVerificationError(
                "preflight does not accept a package or source identity"
            )
    else:
        if (
            args.package is None
            or args.source_identity is None
            or args.repository_root is None
        ):
            raise ReleaseVerificationError(
                "package verification requires --package, --source-identity, "
                "and --repository-root"
            )
        verify_package(
            root,
            args.package.resolve(),
            args.source_revision,
            args.source_identity.resolve(),
            args.repository_root.resolve(),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
