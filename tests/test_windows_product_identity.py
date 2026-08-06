"""Independent static checks for Sector's Windows product identity."""

from __future__ import annotations

import ast
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


def test_committed_windows_resource_parses_and_matches_source_identity():
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


def test_identity_gate_has_only_standard_library_imports():
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
    assert roots == {"__future__", "ast", "pathlib"}


def test_packager_applies_resource_and_retains_complete_provenance():
    spec = (ROOT / "packaging" / "sector.spec").read_text(encoding="utf-8")
    assert 'WINDOWS_VERSION_INFO = os.path.join(SPECPATH, "windows_version_info.txt")' in spec
    assert "version=WINDOWS_VERSION_INFO" in spec
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


def test_normal_qa_artifact_is_explicitly_unsigned_and_identity_checked():
    workflow = (ROOT / ".github" / "workflows" / "qa.yml").read_text(
        encoding="utf-8"
    )
    assert "Unsigned QA Windows package" in workflow
    assert "Sector-Windows-unsigned-QA" in workflow
    assert "Do not launch or distribute it" in workflow
    for check in (
        '$versionInfo.ProductName -ne "Sector"',
        '$versionInfo.FileDescription -ne "Structural-analysis and design calculation tool"',
        '$versionInfo.FileVersion -ne "0.91.0.0"',
        '$versionInfo.ProductVersion -ne "0.91.0.0"',
        '$versionInfo.LegalCopyright -ne "Copyright (c) 2026 Kasper Lindskov Fabricius. All rights reserved."',
    ):
        assert workflow.count(check) == 1
    assert '$versionInfo.CompanyName' in workflow
    assert "signtool" not in workflow.casefold()


def test_local_build_surfaces_never_invite_unsigned_launch_or_distribution():
    powershell = (ROOT / "packaging" / "build.ps1").read_text(encoding="utf-8")
    batch = (ROOT / "packaging" / "build.bat").read_text(encoding="utf-8")
    readme = (ROOT / "packaging" / "README.md").read_text(encoding="utf-8")
    combined = "\n".join((powershell, batch, readme)).casefold()
    assert "unsigned qa" in combined
    assert "do not launch or distribute" in combined
    assert "there is no\nunsigned fallback" in combined
    assert "done. run dist/sector/sector.exe" not in combined
    assert "build complete. run dist\\sector\\sector.exe" not in combined


def test_windows_identity_slice_contains_no_signing_authority():
    for path in (
        ROOT / "packaging" / "sector.spec",
        ROOT / "packaging" / "build.ps1",
        ROOT / "packaging" / "build.bat",
    ):
        text = path.read_text(encoding="utf-8").casefold()
        assert "authenticode" not in text
        assert "certificate" not in text
        assert "timestamp.digicert.com" not in text
