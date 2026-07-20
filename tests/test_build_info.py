"""Tests for executable-free source/build provenance discovery."""

from __future__ import annotations

from sector import build_info


def test_source_revision_prefers_explicit_build_environment(monkeypatch):
    monkeypatch.setenv("SECTOR_SOURCE_REVISION", "abc123")
    assert build_info.source_revision() == "abc123"
    assert build_info.short_revision() == "abc123"


def test_git_revision_reads_loose_ref_without_launching_git(tmp_path):
    git_dir = tmp_path / ".git"
    ref = git_dir / "refs" / "heads" / "main"
    ref.parent.mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="ascii")
    ref.write_text("d" * 40 + "\n", encoding="ascii")

    assert build_info._git_revision(tmp_path) == "d" * 40


def test_git_revision_resolves_worktree_marker(tmp_path):
    metadata = tmp_path / "metadata"
    ref = metadata / "refs" / "heads" / "topic"
    ref.parent.mkdir(parents=True)
    (metadata / "HEAD").write_text("ref: refs/heads/topic\n", encoding="ascii")
    ref.write_text("e" * 40 + "\n", encoding="ascii")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / ".git").write_text(
        "gitdir: ../metadata\n", encoding="ascii",
    )

    assert build_info._git_revision(checkout) == "e" * 40


def test_short_revision_keeps_unavailable_label():
    assert build_info.short_revision("unavailable") == "unavailable"
    assert build_info.short_revision("f" * 40) == "f" * 12
