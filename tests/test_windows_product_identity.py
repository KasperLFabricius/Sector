"""Independent checks for Sector's static Windows package identity."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "packaging" / "sector.spec"
RESOURCE = ROOT / "packaging" / "windows_version_info.txt"
COMMIT = "a" * 40

EXPECTED = {
    "__version__": "0.91",
    "__product_name__": "Sector",
    "__description__": "Structural-analysis and design calculation tool",
    "__author__": "Kasper Lindskov Fabricius",
    "__licensee__": "Sweco Danmark A/S",
    "__copyright__": (
        "Copyright (c) 2026 Kasper Lindskov Fabricius. All rights reserved."
    ),
}


def _source_identity() -> dict[str, str]:
    tree = ast.parse((ROOT / "sector" / "__init__.py").read_text(encoding="utf-8"))
    values = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id in EXPECTED:
            values[target.id] = ast.literal_eval(node.value)
    return values


def _spec_helpers(*names: str):
    tree = ast.parse(SPEC.read_text(encoding="utf-8"), filename=str(SPEC))
    selected = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    assert {node.name for node in selected} == set(names)
    harness = ast.Module(
        body=[ast.Import(names=[ast.alias(name="ast")]),
              ast.Import(names=[ast.alias(name="datetime")]),
              ast.Import(names=[ast.alias(name="os")]), *selected],
        type_ignores=[],
    )
    namespace = {}
    exec(compile(ast.fix_missing_locations(harness), str(SPEC), "exec"), namespace)
    return namespace


def test_source_product_identity_is_exact_and_complete():
    assert _source_identity() == EXPECTED


def test_windows_resource_is_exact_and_syntactically_valid():
    text = RESOURCE.read_text(encoding="utf-8")
    ast.parse(text, filename=str(RESOURCE))
    for token in (
        "filevers=(0, 91, 0, 0)",
        "prodvers=(0, 91, 0, 0)",
        "StringStruct('FileVersion', '0.91.0.0')",
        "StringStruct('ProductVersion', '0.91.0.0')",
        "StringStruct('ProductName', 'Sector')",
        "StringStruct('FileDescription', 'Structural-analysis and design calculation tool')",
        "StringStruct('OriginalFilename', 'Sector.exe')",
        "StringStruct('LegalCopyright', 'Copyright (c) 2026 Kasper Lindskov Fabricius. All rights reserved.')",
        "Licensed to Sweco Danmark A/S for internal organisational use only.",
    ):
        assert text.count(token) == 1
    assert "CompanyName" not in text
    assert "Publisher" not in text


def test_packager_maps_every_identity_to_resource_and_manifest():
    spec = SPEC.read_text(encoding="utf-8")
    assert spec.count(
        'WINDOWS_VERSION_INFO = os.path.join(SPECPATH, "windows_version_info.txt")'
    ) == 1
    assert spec.count("version=WINDOWS_VERSION_INFO") == 1
    for mapping in (
        '"product_name": metadata["__product_name__"]',
        '"description": metadata["__description__"]',
        '"sector_version": metadata["__version__"]',
        '"author": metadata["__author__"]',
        '"licensee": metadata["__licensee__"]',
        '"copyright": metadata["__copyright__"]',
        "**source_identity",
    ):
        assert spec.count(mapping) == 1
    assert "subprocess" not in spec


def test_packager_reconstructs_complete_source_identity():
    namespace = _spec_helpers("_sector_metadata")
    assert namespace["_sector_metadata"](ROOT) == EXPECTED


def _sealed_environment(monkeypatch):
    values = {
        "SECTOR_SOURCE_IDENTITY_SCHEMA": "sector-source-identity-v1",
        "SECTOR_SOURCE_REVISION": COMMIT,
        "SECTOR_SOURCE_TREE": "b" * 40,
        "SECTOR_SOURCE_EPOCH": "1785996000",
        "SOURCE_DATE_EPOCH": "1785996000",
        "SECTOR_SOURCE_FILE_COUNT": "234",
        "SECTOR_SOURCE_TOTAL_BYTES": "6005838",
        "SECTOR_SOURCE_INVENTORY_SHA256": "c" * 64,
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return values


def _identity_helpers():
    return _spec_helpers(
        "_required_environment",
        "_exact_lower_hex",
        "_canonical_integer",
        "_source_identity",
    )


def test_packager_accepts_only_the_complete_sealed_environment(monkeypatch):
    values = _sealed_environment(monkeypatch)
    identity = _identity_helpers()["_source_identity"]()

    assert identity["schema"] == values["SECTOR_SOURCE_IDENTITY_SCHEMA"]
    assert identity["source_revision"] == COMMIT
    assert identity["source_tree"] == "b" * 40
    assert identity["source_epoch"] == 1785996000
    assert identity["source_file_count"] == 234
    assert identity["source_total_bytes"] == 6005838
    assert identity["source_inventory_sha256"] == "c" * 64
    assert identity["built_at_utc"].endswith("+00:00")


def test_packager_has_no_checkout_or_github_identity_fallback(monkeypatch):
    values = _sealed_environment(monkeypatch)
    for key in values:
        monkeypatch.delenv(key)
    monkeypatch.setenv("GITHUB_SHA", COMMIT)

    try:
        _identity_helpers()["_source_identity"]()
    except ValueError as exc:
        assert "SECTOR_SOURCE_IDENTITY_SCHEMA" in str(exc)
    else:
        raise AssertionError("packager accepted an unsealed checkout identity")


def test_packager_rejects_mismatched_or_noncanonical_epoch(monkeypatch):
    _sealed_environment(monkeypatch)
    source_identity = _identity_helpers()["_source_identity"]
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1785996001")
    try:
        source_identity()
    except ValueError as exc:
        assert "differs" in str(exc)
    else:
        raise AssertionError("packager accepted a mismatched source epoch")

    monkeypatch.setenv("SOURCE_DATE_EPOCH", "01785996000")
    try:
        source_identity()
    except ValueError as exc:
        assert "noncanonical" in str(exc)
    else:
        raise AssertionError("packager accepted an ambiguous source epoch")


def test_static_identity_surface_contains_no_signing_authority():
    for path in (RESOURCE, SPEC):
        text = path.read_text(encoding="utf-8").casefold()
        assert "authenticode" not in text
        assert "certificate" not in text
        assert "timestamp.digicert.com" not in text
