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
        body=[
            ast.Import(names=[ast.alias(name="ast")]),
            ast.Import(names=[ast.alias(name="datetime")]),
            ast.Import(names=[ast.alias(name="os")]),
            *selected,
        ],
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
        '"source_revision": source_revision',
        '"source_date_epoch": source_date_epoch',
        '"author": metadata["__author__"]',
        '"licensee": metadata["__licensee__"]',
        '"copyright": metadata["__copyright__"]',
        '"built_at_utc": datetime.datetime.fromtimestamp(',
    ):
        assert spec.count(mapping) == 1
    assert "subprocess" not in spec


def test_packager_reconstructs_complete_source_identity():
    namespace = _spec_helpers("_sector_metadata")
    assert namespace["_sector_metadata"](ROOT) == EXPECTED


def test_source_revision_prefers_only_complete_environment_identity(monkeypatch):
    namespace = _spec_helpers(
        "_commit_revision", "_git_directories", "_source_revision"
    )
    monkeypatch.setenv("SECTOR_SOURCE_REVISION", "unavailable")
    monkeypatch.setenv("GITHUB_SHA", COMMIT)
    assert namespace["_source_revision"](ROOT / "missing") == COMMIT


def test_source_date_epoch_is_explicit_canonical_and_utc_representable(monkeypatch):
    namespace = _spec_helpers("_source_date_epoch")
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1786000000")
    assert namespace["_source_date_epoch"]() == 1_786_000_000

    for invalid in ("", "-1", "01", "1.5", "not-an-epoch"):
        monkeypatch.setenv("SOURCE_DATE_EPOCH", invalid)
        try:
            namespace["_source_date_epoch"]()
        except ValueError as exc:
            assert "non-negative integer commit timestamp" in str(exc)
        else:
            raise AssertionError(f"packager accepted invalid source epoch {invalid!r}")


def test_source_date_epoch_is_required(monkeypatch):
    namespace = _spec_helpers("_source_date_epoch")
    monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
    try:
        namespace["_source_date_epoch"]()
    except ValueError as exc:
        assert str(exc) == (
            "Sector package source date epoch is unavailable; set "
            "SOURCE_DATE_EPOCH to the non-negative integer commit timestamp"
        )
    else:
        raise AssertionError("packager accepted an uncontrolled wall-clock build")


def test_source_revision_rejects_an_untraceable_export(tmp_path, monkeypatch):
    namespace = _spec_helpers(
        "_commit_revision", "_git_directories", "_source_revision"
    )
    monkeypatch.delenv("SECTOR_SOURCE_REVISION", raising=False)
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    try:
        namespace["_source_revision"](tmp_path)
    except ValueError as exc:
        assert str(exc) == (
            "Sector package source revision is unavailable; set "
            "SECTOR_SOURCE_REVISION to the exact 40-hex commit"
        )
    else:
        raise AssertionError("packager accepted an untraceable source tree")


def test_source_revision_resolves_the_current_checkout(monkeypatch):
    namespace = _spec_helpers(
        "_commit_revision", "_git_directories", "_source_revision"
    )
    monkeypatch.delenv("SECTOR_SOURCE_REVISION", raising=False)
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    revision = namespace["_source_revision"](ROOT)
    assert len(revision) == 40
    assert all(char in "0123456789abcdefABCDEF" for char in revision)


def test_source_revision_resolves_detached_head(tmp_path, monkeypatch):
    namespace = _spec_helpers(
        "_commit_revision", "_git_directories", "_source_revision"
    )
    monkeypatch.delenv("SECTOR_SOURCE_REVISION", raising=False)
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text(COMMIT + "\n", encoding="ascii")
    assert namespace["_source_revision"](tmp_path) == COMMIT


def test_source_revision_resolves_linked_worktree_common_refs(tmp_path, monkeypatch):
    namespace = _spec_helpers(
        "_commit_revision", "_git_directories", "_source_revision"
    )
    monkeypatch.delenv("SECTOR_SOURCE_REVISION", raising=False)
    monkeypatch.delenv("GITHUB_SHA", raising=False)

    project = tmp_path / "project"
    worktree_git = tmp_path / "repo" / ".git" / "worktrees" / "sector"
    common_git = tmp_path / "repo" / ".git"
    branch_ref = common_git / "refs" / "heads" / "candidate"
    project.mkdir()
    worktree_git.mkdir(parents=True)
    branch_ref.parent.mkdir(parents=True)
    (project / ".git").write_text(
        "gitdir: ../repo/.git/worktrees/sector\n", encoding="ascii"
    )
    (worktree_git / "HEAD").write_text(
        "ref: refs/heads/candidate\n", encoding="ascii"
    )
    (worktree_git / "commondir").write_text("../..\n", encoding="ascii")
    branch_ref.write_text(COMMIT + "\n", encoding="ascii")

    assert namespace["_source_revision"](project) == COMMIT


def test_source_revision_resolves_common_packed_refs(tmp_path, monkeypatch):
    namespace = _spec_helpers(
        "_commit_revision", "_git_directories", "_source_revision"
    )
    monkeypatch.delenv("SECTOR_SOURCE_REVISION", raising=False)
    monkeypatch.delenv("GITHUB_SHA", raising=False)

    project = tmp_path / "project"
    worktree_git = tmp_path / "repo" / ".git" / "worktrees" / "sector"
    common_git = tmp_path / "repo" / ".git"
    project.mkdir()
    worktree_git.mkdir(parents=True)
    (project / ".git").write_text(
        "gitdir: ../repo/.git/worktrees/sector\n", encoding="ascii"
    )
    (worktree_git / "HEAD").write_text(
        "ref: refs/heads/packed-candidate\n", encoding="ascii"
    )
    (worktree_git / "commondir").write_text("../..\n", encoding="ascii")
    (common_git / "packed-refs").write_text(
        f"# pack-refs with: peeled fully-peeled sorted\n{COMMIT} refs/heads/packed-candidate\n",
        encoding="ascii",
    )

    assert namespace["_source_revision"](project) == COMMIT


def test_static_identity_surface_contains_no_signing_authority():
    for path in (RESOURCE, SPEC):
        text = path.read_text(encoding="utf-8").casefold()
        assert "authenticode" not in text
        assert "certificate" not in text
        assert "timestamp.digicert.com" not in text
