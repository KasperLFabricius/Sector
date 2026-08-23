"""Static checks for Sector's ordinary Windows product metadata."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "packaging" / "sector.spec"
RESOURCE = ROOT / "packaging" / "windows_version_info.txt"

EXPECTED = {
    "__version__": "0.96",
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
    values: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id in EXPECTED:
            value = ast.literal_eval(node.value)
            assert isinstance(value, str)
            values[target.id] = value
    return values


def _sector_metadata_helper():
    tree = ast.parse(SPEC.read_text(encoding="utf-8"), filename=str(SPEC))
    selected = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_sector_metadata"
    ]
    assert len(selected) == 1
    harness = ast.Module(
        body=[
            ast.Import(names=[ast.alias(name="ast")]),
            ast.Import(names=[ast.alias(name="os")]),
            selected[0],
        ],
        type_ignores=[],
    )
    namespace: dict[str, object] = {}
    exec(  # noqa: S102 - isolated AST helper extraction for a spec test
        compile(ast.fix_missing_locations(harness), str(SPEC), "exec"), namespace
    )
    return namespace["_sector_metadata"]


def test_source_product_identity_is_exact_and_version_is_095():
    assert _source_identity() == EXPECTED


def test_windows_resource_is_exact_and_syntactically_valid():
    text = RESOURCE.read_text(encoding="utf-8")
    ast.parse(text, filename=str(RESOURCE))
    for token in (
        "filevers=(0, 96, 0, 0)",
        "prodvers=(0, 96, 0, 0)",
        "StringStruct('FileVersion', '0.96.0.0')",
        "StringStruct('ProductVersion', '0.96.0.0')",
        "StringStruct('ProductName', 'Sector')",
        "StringStruct('OriginalFilename', 'Sector.exe')",
    ):
        assert text.count(token) == 1
    assert "CompanyName" not in text
    assert "Publisher" not in text


def test_packager_embeds_only_useful_diagnostic_metadata():
    spec = SPEC.read_text(encoding="utf-8")
    for mapping in (
        '"product_name": metadata["__product_name__"]',
        '"description": metadata["__description__"]',
        '"sector_version": metadata["__version__"]',
        '"source_revision": source_revision',
    ):
        assert mapping in spec
    for removed in (
        "source_tree",
        "source_inventory_sha256",
        "source_file_count",
        "SOURCE_DATE_EPOCH",
        "certificate",
        "authenticode",
        "GITHUB_SHA",
        "subprocess",
    ):
        assert removed not in spec


def test_packager_reads_the_complete_source_identity():
    helper = _sector_metadata_helper()
    assert callable(helper)
    assert helper(ROOT) == EXPECTED
