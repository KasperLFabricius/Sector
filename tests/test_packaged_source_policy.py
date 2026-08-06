"""Adversarial checks for the exact packaged-source boundary."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import tools.verify_packaged_source as policy
from tools.verify_packaged_source import (
    PACKAGED_SOURCE_ROOTS,
    PackagedSourceError,
    verify_packaged_source,
)

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "a" * 40


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
    (root / ".gitignore").write_text("__pycache__/\n*.pyc\n*.so\n", encoding="ascii")
    for directory in PACKAGED_SOURCE_ROOTS:
        path = root / directory
        path.mkdir()
        (path / "tracked.txt").write_text(f"{directory}\n", encoding="ascii")
    _run(root, "add", ".gitignore", *PACKAGED_SOURCE_ROOTS)
    _run(root, "commit", "--quiet", "-m", "fixture")
    return root, _run(root, "rev-parse", "HEAD")


def test_clean_commit_accepts_untracked_artifacts_outside_packaged_trees(tmp_path):
    root, commit = _repository(tmp_path)
    output = root / "output"
    output.mkdir()
    (output / "qa-evidence.txt").write_text("preserve\n", encoding="ascii")

    verify_packaged_source(root, commit)


@pytest.mark.parametrize(
    ("relative", "ignored"),
    (
        ("app/local.py", False),
        ("app/__pycache__/local.pyc", True),
        ("sector/native.so", True),
        ("assets/private.bin", False),
    ),
)
def test_every_untracked_packaged_payload_is_rejected(tmp_path, relative, ignored):
    root, commit = _repository(tmp_path)
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"uncommitted payload\n")
    ignored_result = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "--quiet", relative],
        check=False,
    )
    assert (ignored_result.returncode == 0) is ignored

    with pytest.raises(PackagedSourceError, match="untracked or ignored"):
        verify_packaged_source(root, commit)


def test_dirty_tracked_source_is_rejected(tmp_path):
    root, commit = _repository(tmp_path)
    (root / "sector" / "tracked.txt").write_text("changed\n", encoding="ascii")

    with pytest.raises(PackagedSourceError, match="tracked worktree bytes differ"):
        verify_packaged_source(root, commit)


def test_staged_tracked_source_is_rejected(tmp_path):
    root, commit = _repository(tmp_path)
    target = root / "sector" / "tracked.txt"
    target.write_text("staged change\n", encoding="ascii")
    _run(root, "add", "sector/tracked.txt")

    with pytest.raises(PackagedSourceError, match="staged source tree differs"):
        verify_packaged_source(root, commit)


@pytest.mark.parametrize("flag", ("--assume-unchanged", "--skip-worktree"))
def test_index_hints_cannot_hide_changed_tracked_bytes(tmp_path, flag):
    root, commit = _repository(tmp_path)
    relative = "app/tracked.txt"
    _run(root, "update-index", flag, relative)
    (root / relative).write_text("hidden change\n", encoding="ascii")
    assert _run(root, "status", "--porcelain=v1") == ""

    with pytest.raises(PackagedSourceError, match="tracked worktree bytes differ"):
        verify_packaged_source(root, commit)


@pytest.mark.parametrize(
    "revision",
    ("", "a" * 39, "A" * 40, "g" * 40, "HEAD", "a" * 40 + "; bad"),
)
def test_non_exact_requested_revision_is_rejected(tmp_path, revision):
    root, _commit = _repository(tmp_path)

    with pytest.raises(PackagedSourceError, match="exact lowercase 40-hex"):
        verify_packaged_source(root, revision)


def test_different_exact_head_is_rejected(tmp_path):
    root, commit = _repository(tmp_path)
    assert commit != COMMIT

    with pytest.raises(PackagedSourceError, match="not current HEAD"):
        verify_packaged_source(root, COMMIT)


def test_isolated_cli_succeeds_without_site_packages(tmp_path):
    root, commit = _repository(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(ROOT / "tools" / "verify_packaged_source.py"),
            "--root",
            str(root),
            "--source-revision",
            commit,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert commit in result.stdout


def test_policy_command_cannot_hide_ignored_packaged_files(tmp_path, monkeypatch):
    calls: list[tuple[str, ...]] = []

    def fake_git(_root, *arguments, input_bytes=None):
        calls.append(arguments)
        if arguments[:2] == ("rev-parse", "--verify"):
            return (COMMIT + "\n").encode("ascii")
        if arguments[:3] == ("ls-tree", "-r", "-z"):
            return b"100644 blob " + COMMIT.encode("ascii") + b"\ttracked.txt\0"
        if arguments[:2] == ("hash-object", "--stdin-paths"):
            assert input_bytes == b"tracked.txt\n"
            return (COMMIT + "\n").encode("ascii")
        return b""

    monkeypatch.setattr(policy, "_git_bytes", fake_git)
    verify_packaged_source(tmp_path, COMMIT)

    assert calls[-1] == (
        "ls-files",
        "--others",
        "-z",
        "--",
        *PACKAGED_SOURCE_ROOTS,
    )
    assert all("--exclude-standard" not in call for call in calls)
