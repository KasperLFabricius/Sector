"""Independent checks for Sector's static Windows package identity."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "packaging" / "sector.spec"
RESOURCE = ROOT / "packaging" / "windows_version_info.txt"
COMMIT = "a" * 40
TREE = "b" * 40
INVENTORY = "c" * 64
EPOCH = "123"
COMMITTED_AT_UTC = "1970-01-01T00:02:03+00:00"
SOURCE_SEAL = {
    "SECTOR_SOURCE_REVISION": COMMIT,
    "SECTOR_SOURCE_TREE": TREE,
    "SECTOR_SOURCE_COMMITTER_EPOCH": EPOCH,
    "SECTOR_SOURCE_COMMITTED_AT_UTC": COMMITTED_AT_UTC,
    "SECTOR_SOURCE_FILE_COUNT": "235",
    "SECTOR_SOURCE_TOTAL_BYTES": "6032876",
    "SECTOR_SOURCE_INVENTORY_SHA256": INVENTORY,
    "SOURCE_DATE_EPOCH": EPOCH,
}

EXPECTED = {
    "__version__": "0.93",
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


def _set_source_seal(monkeypatch, **overrides):
    values = {**SOURCE_SEAL, **overrides}
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_source_product_identity_is_exact_and_complete():
    assert _source_identity() == EXPECTED


def test_windows_resource_is_exact_and_syntactically_valid():
    text = RESOURCE.read_text(encoding="utf-8")
    ast.parse(text, filename=str(RESOURCE))
    for token in (
        "filevers=(0, 93, 0, 0)",
        "prodvers=(0, 93, 0, 0)",
        "StringStruct('FileVersion', '0.93.0.0')",
        "StringStruct('ProductVersion', '0.93.0.0')",
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
        '"built_at_utc": source_seal["source_committed_at_utc"]',
        "**source_seal",
    ):
        assert spec.count(mapping) == 1
    assert "subprocess" not in spec
    assert "GITHUB_SHA" not in spec
    assert "datetime.datetime.now" not in spec


def test_packager_reconstructs_complete_source_identity():
    namespace = _spec_helpers("_sector_metadata")
    assert namespace["_sector_metadata"](ROOT) == EXPECTED


def test_source_seal_accepts_only_the_complete_canonical_environment(monkeypatch):
    namespace = _spec_helpers(
        "_commit_revision", "_canonical_integer", "_source_seal"
    )
    _set_source_seal(monkeypatch)
    assert namespace["_source_seal"]() == {
        "source_revision": COMMIT,
        "source_tree": TREE,
        "source_committer_epoch": 123,
        "source_committed_at_utc": COMMITTED_AT_UTC,
        "source_file_count": 235,
        "source_total_bytes": 6032876,
        "source_inventory_sha256": INVENTORY,
    }


def test_source_seal_rejects_missing_identity_despite_github_fallback(
    monkeypatch,
):
    namespace = _spec_helpers(
        "_commit_revision", "_canonical_integer", "_source_seal"
    )
    _set_source_seal(monkeypatch)
    monkeypatch.delenv("SECTOR_SOURCE_TREE")
    monkeypatch.setenv("GITHUB_SHA", TREE)
    with pytest.raises(ValueError, match="invalid sealed source commit identity"):
        namespace["_source_seal"]()


@pytest.mark.parametrize(
    ("name", "value", "message"),
    (
        ("SECTOR_SOURCE_REVISION", COMMIT.upper(), "commit identity"),
        ("SECTOR_SOURCE_COMMITTER_EPOCH", "0123", "source integer"),
        ("SOURCE_DATE_EPOCH", "124", "does not match"),
        ("SECTOR_SOURCE_COMMITTED_AT_UTC", "1970-01-01T00:02:04+00:00", "UTC time"),
        ("SECTOR_SOURCE_INVENTORY_SHA256", INVENTORY.upper(), "inventory digest"),
    ),
)
def test_source_seal_rejects_noncanonical_or_mismatched_fields(
    monkeypatch, name, value, message
):
    namespace = _spec_helpers(
        "_commit_revision", "_canonical_integer", "_source_seal"
    )
    _set_source_seal(monkeypatch, **{name: value})
    with pytest.raises(ValueError, match=message):
        namespace["_source_seal"]()


def test_spec_contains_no_git_or_checkout_identity_fallback():
    tree = ast.parse(SPEC.read_text(encoding="utf-8"), filename=str(SPEC))
    function_names = {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    assert {"_commit_revision", "_canonical_integer", "_source_seal"} <= function_names
    assert {"_git_directories", "_source_revision"}.isdisjoint(function_names)
    text = SPEC.read_text(encoding="utf-8")
    for forbidden in ("GITHUB_SHA", "git rev-parse", "packed-refs", "subprocess"):
        assert forbidden not in text


def test_static_identity_surface_contains_no_signing_authority():
    for path in (RESOURCE, SPEC):
        text = path.read_text(encoding="utf-8").casefold()
        assert "authenticode" not in text
        assert "certificate" not in text
        assert "timestamp.digicert.com" not in text
