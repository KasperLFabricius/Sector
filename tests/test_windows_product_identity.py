"""Standard-library checks for Sector's static Windows product identity."""

from __future__ import annotations

import ast
import os
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
RESOURCE = ROOT / "packaging" / "windows_version_info.txt"

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


def test_source_product_identity_is_exact_and_complete():
    assert _source_identity() == EXPECTED


def test_committed_windows_resource_is_exact_and_syntactically_valid():
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
    spec = (ROOT / "packaging" / "sector.spec").read_text(encoding="utf-8")
    assert spec.count(
        'WINDOWS_VERSION_INFO = os.path.join(SPECPATH, "windows_version_info.txt")'
    ) == 1
    assert spec.count("version=WINDOWS_VERSION_INFO") == 1
    for mapping in (
        '"product_name": metadata["__product_name__"]',
        '"description": metadata["__description__"]',
        '"sector_version": metadata["__version__"]',
        '"source_revision": _source_revision(ROOT)',
        '"author": metadata["__author__"]',
        '"licensee": metadata["__licensee__"]',
        '"copyright": metadata["__copyright__"]',
        '"built_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(',
    ):
        assert spec.count(mapping) == 1
    assert "subprocess" not in spec


def test_packager_metadata_reader_reconstructs_complete_source_identity():
    path = ROOT / "packaging" / "sector.spec"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    helper = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_sector_metadata"
    )
    harness = ast.Module(
        body=[
            ast.Import(names=[ast.alias(name="os")]),
            ast.Import(names=[ast.alias(name="re")]),
            helper,
        ],
        type_ignores=[],
    )
    namespace = {}
    exec(compile(ast.fix_missing_locations(harness), str(path), "exec"), namespace)
    assert namespace["_sector_metadata"](ROOT) == EXPECTED


def test_packager_rejects_an_unresolvable_source_revision():
    path = ROOT / "packaging" / "sector.spec"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    helper = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_source_revision"
    )
    harness = ast.Module(
        body=[ast.Import(names=[ast.alias(name="os")]), helper],
        type_ignores=[],
    )
    namespace = {}
    exec(compile(ast.fix_missing_locations(harness), str(path), "exec"), namespace)

    retained = {
        name: os.environ.pop(name, None)
        for name in ("SECTOR_SOURCE_REVISION", "GITHUB_SHA")
    }
    try:
        with tempfile.TemporaryDirectory() as empty_root:
            try:
                namespace["_source_revision"](empty_root)
            except ValueError as exc:
                assert str(exc) == (
                    "Sector package source revision is unavailable; set "
                    "SECTOR_SOURCE_REVISION to the exact source revision"
                )
            else:
                raise AssertionError("packager accepted an untraceable source tree")
    finally:
        for name, value in retained.items():
            if value is not None:
                os.environ[name] = value


def test_identity_gate_uses_only_standard_library_imports():
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    roots = {
        node.module.split(".", 1)[0]
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module
    }
    roots.update(
        alias.name.split(".", 1)[0]
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    assert roots == {"__future__", "ast", "os", "pathlib", "tempfile"}


def test_static_identity_surface_contains_no_signing_authority():
    for path in (RESOURCE, ROOT / "packaging" / "sector.spec"):
        text = path.read_text(encoding="utf-8").casefold()
        assert "authenticode" not in text
        assert "certificate" not in text
        assert "timestamp.digicert.com" not in text
