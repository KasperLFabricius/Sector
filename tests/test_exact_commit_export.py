"""Independent adversarial tests for exact raw-commit materialization."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.export_commit_tree import (
    CommitExportError,
    TreeEntry,
    _git_command,
    _git_environment,
    _parse_batch,
    _parse_tree,
    export_commit_tree,
)

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "a" * 40
BLOB = "b" * 40


def _run(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _repository(tmp_path: Path, name: str = "repository", marker: str = "safe"):
    root = tmp_path / name
    root.mkdir(parents=True)
    _run(root, "init", "--quiet")
    _run(root, "config", "user.email", "sector-tests@example.invalid")
    _run(root, "config", "user.name", "Sector tests")
    _run(root, "config", "core.autocrlf", "false")
    (root / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="ascii")
    for directory in ("app", "sector", "assets"):
        target = root / directory
        target.mkdir()
        (target / "tracked.txt").write_bytes(
            f"{marker}:{directory}\n".encode("ascii")
        )
    _run(root, "add", ".")
    _run(root, "commit", "--quiet", "-m", f"fixture {marker}")
    return root, _run(root, "rev-parse", "HEAD")


def _inventory_digest(root: Path) -> str:
    records = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        payload = path.read_bytes()
        object_id = hashlib.sha1(
            b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload
        ).hexdigest()
        records.append((relative, "100644", object_id, len(payload)))
    digest = hashlib.sha256()
    for record in records:
        digest.update(
            json.dumps(record, ensure_ascii=True, separators=(",", ":")).encode(
                "ascii"
            )
        )
        digest.update(b"\n")
    return digest.hexdigest()


def _tree_record(path: str, mode: str = "100644", kind: str = "blob") -> bytes:
    return f"{mode} {kind} {BLOB}\t{path}\0".encode("utf-8")


def test_clean_commit_exports_only_exact_raw_tracked_blobs(tmp_path):
    root, commit = _repository(tmp_path)
    (root / "app" / "__pycache__").mkdir()
    (root / "app" / "__pycache__" / "local.pyc").write_bytes(b"ignored")
    (root / "output.txt").write_text("untracked\n", encoding="ascii")
    output = tmp_path / "export"

    summary = export_commit_tree(root, commit, output)

    assert summary.source_revision == commit
    assert summary.file_count == 4
    assert summary.total_bytes == sum(
        path.stat().st_size for path in output.rglob("*") if path.is_file()
    )
    assert summary.inventory_sha256 == _inventory_digest(output)
    assert (output / "app" / "tracked.txt").read_bytes() == b"safe:app\n"
    assert not (output / "app" / "__pycache__").exists()
    assert not (output / "output.txt").exists()
    assert not (output / ".git").exists()


def test_distinct_exports_of_one_commit_have_identical_evidence(tmp_path):
    root, commit = _repository(tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"

    first_summary = export_commit_tree(root, commit, first)
    second_summary = export_commit_tree(root, commit, second)

    assert first_summary == second_summary
    assert _inventory_digest(first) == _inventory_digest(second)
    assert {
        path.relative_to(first): path.read_bytes()
        for path in first.rglob("*")
        if path.is_file()
    } == {
        path.relative_to(second): path.read_bytes()
        for path in second.rglob("*")
        if path.is_file()
    }


def test_replacement_ref_cannot_redirect_exported_commit(tmp_path):
    root, original = _repository(tmp_path)
    target = root / "app" / "tracked.txt"
    target.write_bytes(b"replacement tree\n")
    _run(root, "add", "app/tracked.txt")
    _run(root, "commit", "--quiet", "-m", "replacement")
    replacement = _run(root, "rev-parse", "HEAD")
    _run(root, "replace", original, replacement)
    assert _run(root, "show", f"{original}:app/tracked.txt") == "replacement tree"

    output = tmp_path / "export"
    export_commit_tree(root, original, output)

    assert (output / "app" / "tracked.txt").read_bytes() == b"safe:app\n"


@pytest.mark.parametrize("flag", ("--assume-unchanged", "--skip-worktree"))
def test_index_hints_and_worktree_changes_cannot_enter_export(tmp_path, flag):
    root, commit = _repository(tmp_path)
    relative = "app/tracked.txt"
    _run(root, "update-index", flag, relative)
    (root / relative).write_bytes(b"mutable worktree\n")

    output = tmp_path / "export"
    export_commit_tree(root, commit, output)

    assert (output / relative).read_bytes() == b"safe:app\n"


def test_local_attributes_and_clean_filters_cannot_change_raw_export(tmp_path):
    root, commit = _repository(tmp_path)
    attributes = root / ".git" / "info" / "attributes"
    attributes.write_text("app/tracked.txt filter=hostile\n", encoding="ascii")
    _run(root, "config", "filter.hostile.clean", "printf 'filtered\\n'")
    (root / "app" / "tracked.txt").write_bytes(b"mutable worktree\n")

    output = tmp_path / "export"
    export_commit_tree(root, commit, output)

    assert (output / "app" / "tracked.txt").read_bytes() == b"safe:app\n"


@pytest.mark.parametrize(
    "variable",
    ("GIT_DIR", "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR"),
)
def test_repository_selection_environment_cannot_redirect_git(
    tmp_path, monkeypatch, variable
):
    root_a, _commit_a = _repository(tmp_path, "repository-a", "a")
    root_b, commit_b = _repository(tmp_path, "repository-b", "b")
    values = {
        "GIT_DIR": root_b / ".git",
        "GIT_OBJECT_DIRECTORY": root_b / ".git" / "objects",
        "GIT_COMMON_DIR": root_b / ".git",
    }
    monkeypatch.setenv(variable, str(values[variable]))
    output = tmp_path / f"export-{variable.casefold()}"

    with pytest.raises(CommitExportError, match="Git commit inspection failed"):
        export_commit_tree(root_a, commit_b, output)
    assert not output.exists()


def test_git_environment_removes_every_inherited_git_variable(monkeypatch):
    monkeypatch.setenv("GIT_DIR", "hostile")
    monkeypatch.setenv("git_object_directory", "hostile")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.worktree")
    monkeypatch.setenv("SECTOR_PRESERVE", "yes")

    environment = _git_environment()

    assert all(not key.upper().startswith("GIT_") for key in environment)
    assert environment["SECTOR_PRESERVE"] == "yes"


def test_linked_worktree_common_git_directory_is_excluded(tmp_path):
    root, commit = _repository(tmp_path)
    linked = tmp_path / "linked"
    _run(root, "worktree", "add", "--detach", "--quiet", str(linked), commit)
    output = root / ".git" / "objects" / "exported"

    with pytest.raises(CommitExportError, match="inside Git metadata"):
        export_commit_tree(linked, commit, output)
    assert not output.exists()


@pytest.mark.parametrize(
    "revision",
    ("", "a" * 39, "A" * 40, "g" * 40, "HEAD", "a" * 40 + "; bad"),
)
def test_non_exact_revision_is_rejected_before_git(tmp_path, revision):
    with pytest.raises(CommitExportError, match="exact lowercase 40-hex"):
        export_commit_tree(tmp_path, revision, tmp_path / "export")


def test_non_commit_object_is_rejected(tmp_path):
    root, _commit = _repository(tmp_path)
    blob = _run(root, "hash-object", "app/tracked.txt")

    with pytest.raises(CommitExportError, match="commit object"):
        export_commit_tree(root, blob, tmp_path / "export")


def test_repository_argument_must_be_the_exact_worktree_root(tmp_path):
    root, commit = _repository(tmp_path)

    with pytest.raises(CommitExportError, match="exact worktree root"):
        export_commit_tree(root / "app", commit, tmp_path / "export")


def test_existing_output_is_never_overwritten(tmp_path):
    root, commit = _repository(tmp_path)
    output = tmp_path / "export"
    output.mkdir()
    marker = output / "preserve.txt"
    marker.write_text("preserve\n", encoding="ascii")

    with pytest.raises(CommitExportError, match="already exists"):
        export_commit_tree(root, commit, output)
    assert marker.read_text(encoding="ascii") == "preserve\n"


def test_output_cannot_contain_the_repository(tmp_path):
    root, commit = _repository(tmp_path / "parent")

    with pytest.raises(CommitExportError, match="contain the repository"):
        export_commit_tree(root, commit, tmp_path)


def test_output_inside_worktree_git_metadata_is_rejected(tmp_path):
    root, commit = _repository(tmp_path)
    output = root / ".git" / "export"

    with pytest.raises(CommitExportError, match="inside Git metadata"):
        export_commit_tree(root, commit, output)
    assert not output.exists()


@pytest.mark.parametrize(
    ("record", "match"),
    (
        (_tree_record("link", "120000"), "unsupported"),
        (_tree_record("submodule", "160000", "commit"), "unsupported"),
        (_tree_record("../escape"), "unsafe"),
        (_tree_record("/absolute"), "unsafe"),
        (_tree_record("bad:name"), "Windows-unsafe"),
        (_tree_record("bad\\name"), "Windows-unsafe"),
        (_tree_record("trailing."), "Windows-unsafe"),
        (_tree_record("trailing "), "Windows-unsafe"),
        (_tree_record(".git/config"), "unsafe Git-control"),
    ),
)
def test_unsafe_or_nonregular_tree_entries_fail_closed(record, match):
    with pytest.raises(CommitExportError, match=match):
        _parse_tree(record)


@pytest.mark.parametrize(
    "path",
    (
        "CON.txt",
        "aux",
        "COM1 .txt",
        "LPT9.log",
        "COM\u00b9.txt",
        "COM\u00b2",
        "LPT\u00b3.data",
    ),
)
def test_every_windows_device_alias_is_rejected_before_materialization(path):
    with pytest.raises(CommitExportError, match="Windows-unsafe"):
        _parse_tree(_tree_record(path))


@pytest.mark.parametrize(
    ("first", "second"),
    (
        ("app/X.py", "app/x.py"),
        ("a/e\u0301.py", "a/\u00e9.py"),
        ("app", "app/main.py"),
        ("APP", "app/main.py"),
    ),
)
def test_case_unicode_and_file_directory_collisions_fail_closed(first, second):
    raw = _tree_record(first) + _tree_record(second)
    with pytest.raises(CommitExportError, match="collid|both a file and directory"):
        _parse_tree(raw)


def test_raw_blob_payload_is_independently_rehashed():
    expected = b"expected"
    object_id = hashlib.sha1(
        b"blob " + str(len(expected)).encode("ascii") + b"\0" + expected
    ).hexdigest()
    entry = TreeEntry(mode="100644", object_id=object_id, path="app/file.txt")
    hostile = b"hostile!"
    raw = (
        f"{object_id} blob {len(hostile)}\n".encode("ascii")
        + hostile
        + b"\n"
    )

    with pytest.raises(CommitExportError, match="content hash differs"):
        _parse_batch(raw, [entry])


def test_every_git_command_disables_replacement_objects(tmp_path):
    command = _git_command(tmp_path, "ls-tree", "HEAD")
    assert command[:4] == ["git", "--no-replace-objects", "-C", str(tmp_path)]
    assert command[4:] == ["ls-tree", "HEAD"]


def test_isolated_cli_exports_without_site_packages(tmp_path):
    root, commit = _repository(tmp_path)
    output = tmp_path / "export"
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(ROOT / "tools" / "export_commit_tree.py"),
            "--root",
            str(root),
            "--source-revision",
            commit,
            "--output",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={key: value for key, value in os.environ.items() if not key.startswith("PYTHON")},
    )
    assert result.returncode == 0, result.stderr
    assert commit in result.stdout
    assert (output / "sector" / "tracked.txt").read_bytes() == b"safe:sector\n"
