"""Independent adversarial tests for raw exact-commit materialization."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

from tools.export_commit_tree import (
    CommitExportError,
    _git_command,
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


def _repository(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repository"
    root.mkdir()
    _run(root, "init", "--quiet")
    _run(root, "config", "user.email", "sector-tests@example.invalid")
    _run(root, "config", "user.name", "Sector tests")
    _run(root, "config", "core.autocrlf", "false")
    (root / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="ascii")
    for directory in ("app", "sector", "assets"):
        target = root / directory
        target.mkdir()
        (target / "tracked.txt").write_bytes(f"safe:{directory}\n".encode("ascii"))
    _run(root, "add", ".")
    _run(root, "commit", "--quiet", "-m", "fixture")
    return root, _run(root, "rev-parse", "HEAD")


def _inventory_digest(root: Path) -> str:
    records = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        payload = path.read_bytes()
        object_id = hashlib.sha1(
            b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload
        ).hexdigest()
        records.append((relative, object_id, len(payload)))
    digest = hashlib.sha256()
    for relative, object_id, size in records:
        mode = "100644"
        line = f'["{relative}","{mode}","{object_id}",{size}]\n'
        digest.update(line.encode("ascii"))
    return digest.hexdigest()


def test_clean_commit_exports_only_exact_raw_tracked_blobs(tmp_path):
    root, commit = _repository(tmp_path)
    (root / "app" / "__pycache__").mkdir()
    (root / "app" / "__pycache__" / "local.pyc").write_bytes(b"ignored")
    (root / "output.txt").write_text("untracked outside source\n", encoding="ascii")
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


def test_local_attributes_and_filters_cannot_change_raw_blob_export(tmp_path):
    root, commit = _repository(tmp_path)
    info_attributes = root / ".git" / "info" / "attributes"
    info_attributes.write_text("app/tracked.txt filter=hostile\n", encoding="ascii")
    _run(root, "config", "filter.hostile.clean", "printf 'filtered\\n'")
    (root / "app" / "tracked.txt").write_bytes(b"mutable worktree\n")
    output = tmp_path / "export"

    export_commit_tree(root, commit, output)

    assert (output / "app" / "tracked.txt").read_bytes() == b"safe:app\n"


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


def test_existing_output_is_never_overwritten(tmp_path):
    root, commit = _repository(tmp_path)
    output = tmp_path / "export"
    output.mkdir()
    marker = output / "preserve.txt"
    marker.write_text("preserve\n", encoding="ascii")

    with pytest.raises(CommitExportError, match="already exists"):
        export_commit_tree(root, commit, output)
    assert marker.read_text(encoding="ascii") == "preserve\n"


def test_output_inside_git_metadata_is_rejected(tmp_path):
    root, commit = _repository(tmp_path)
    output = root / ".git" / "export"

    with pytest.raises(CommitExportError, match="inside Git metadata"):
        export_commit_tree(root, commit, output)
    assert not output.exists()


@pytest.mark.parametrize(
    ("record", "match"),
    (
        (f"120000 blob {BLOB}\tlink\0".encode(), "unsupported"),
        (f"160000 commit {COMMIT}\tsubmodule\0".encode(), "unsupported"),
        (f"100644 blob {BLOB}\t../escape\0".encode(), "unsafe"),
        (f"100644 blob {BLOB}\tCON.txt\0".encode(), "Windows-unsafe"),
        (f"100644 blob {BLOB}\tCOM1 .txt\0".encode(), "Windows-unsafe"),
        (f"100644 blob {BLOB}\tbad:name\0".encode(), "Windows-unsafe"),
    ),
)
def test_unsafe_or_nonregular_tree_entries_fail_closed(record, match):
    with pytest.raises(CommitExportError, match=match):
        _parse_tree(record)


def test_case_and_unicode_normalization_collisions_fail_closed():
    for first, second in (("app/X.py", "app/x.py"), ("a/e\u0301.py", "a/\u00e9.py")):
        raw = (
            f"100644 blob {BLOB}\t{first}\0"
            f"100644 blob {COMMIT}\t{second}\0"
        ).encode("utf-8")
        with pytest.raises(CommitExportError, match="colliding"):
            _parse_tree(raw)


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
    )
    assert result.returncode == 0, result.stderr
    assert commit in result.stdout
    assert (output / "sector" / "tracked.txt").read_bytes() == b"safe:sector\n"
