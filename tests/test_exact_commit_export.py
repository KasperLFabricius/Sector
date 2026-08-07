"""Adversarial contract tests for exact-commit source export."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.export_commit_tree import (
    CommitTreeError,
    _git_environment,
    _parse_batch_response,
    _parse_commit,
    _parse_tree_object,
    export_commit,
    snapshot_commit,
)

ROOT = Path(__file__).resolve().parents[1]


def _git(root: Path, *arguments: str, input_bytes: bytes | None = None) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    return result.stdout.decode("ascii").strip()


def _repository(tmp_path: Path, name: str = "source", marker: str = "accepted"):
    root = tmp_path / name
    root.mkdir(parents=True)
    _git(root, "init", "--quiet")
    _git(root, "config", "user.email", "sector-tests@example.invalid")
    _git(root, "config", "user.name", "Sector tests")
    _git(root, "config", "core.autocrlf", "false")
    (root / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="ascii")
    for folder in ("app", "sector", "assets"):
        target = root / folder
        target.mkdir()
        (target / "tracked.txt").write_bytes(f"{marker}:{folder}\n".encode("ascii"))
    _git(root, "add", ".")
    _git(root, "commit", "--quiet", "-m", f"fixture {marker}")
    return root, _git(root, "rev-parse", "HEAD")


def _write_literal(root: Path, kind: str, payload: bytes) -> str:
    return _git(
        root,
        "hash-object",
        "--literally",
        "-w",
        "-t",
        kind,
        "--stdin",
        input_bytes=payload,
    )


def _commit_payload(
    tree: str,
    *,
    author: bytes | None = None,
    committer: bytes | None = None,
) -> bytes:
    identity = author or b"Sector tests <sector-tests@example.invalid> 1 +0000"
    committer_identity = (
        committer or b"Sector tests <sector-tests@example.invalid> 1 +0000"
    )
    return (
        f"tree {tree}\n".encode("ascii")
        + b"author "
        + identity
        + b"\ncommitter "
        + committer_identity
        + b"\n\nfixture\n"
    )


def _tree_entry(mode: str, name: bytes, object_id: str) -> bytes:
    return mode.encode("ascii") + b" " + name + b"\0" + bytes.fromhex(object_id)


def test_export_uses_only_raw_files_from_the_requested_commit(tmp_path):
    root, commit = _repository(tmp_path)
    (root / "app" / "tracked.txt").write_bytes(b"mutable worktree\n")
    (root / "untracked.txt").write_bytes(b"untracked\n")
    (root / "app" / "__pycache__").mkdir()
    (root / "app" / "__pycache__" / "ignored.pyc").write_bytes(b"ignored")
    destination = tmp_path / "exact-source"

    evidence = export_commit(root, commit, destination)

    assert evidence.source_revision == commit
    assert evidence.file_count == 4
    assert evidence.total_bytes == sum(
        item.stat().st_size for item in destination.rglob("*") if item.is_file()
    )
    assert (destination / "app" / "tracked.txt").read_bytes() == b"accepted:app\n"
    assert not (destination / "untracked.txt").exists()
    assert not (destination / "app" / "__pycache__").exists()
    assert not (destination / ".git").exists()


def test_repeated_exports_have_identical_evidence_and_bytes(tmp_path):
    root, commit = _repository(tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"

    first_evidence = export_commit(root, commit, first)
    second_evidence = export_commit(root, commit, second)

    assert first_evidence == second_evidence
    assert {
        path.relative_to(first): path.read_bytes()
        for path in first.rglob("*")
        if path.is_file()
    } == {
        path.relative_to(second): path.read_bytes()
        for path in second.rglob("*")
        if path.is_file()
    }


def test_snapshot_preserves_raw_commit_bytes_and_epoch_identity(tmp_path):
    root, commit = _repository(tmp_path)
    destination = tmp_path / "exact-source"

    evidence = export_commit(root, commit, destination)
    snapshot = snapshot_commit(root, commit)
    (root / "app" / "tracked.txt").write_bytes(b"hostile mutable worktree\n")

    assert snapshot.evidence == evidence
    assert evidence.source_tree == _git(root, "rev-parse", f"{commit}^{{tree}}")
    assert evidence.source_committer_epoch == int(
        _git(root, "show", "-s", "--format=%ct", commit)
    )
    assert evidence.source_committed_at_utc.endswith("+00:00")
    payloads = {item.path: item.payload for item in snapshot.files}
    assert payloads["app/tracked.txt"] == b"accepted:app\n"


@pytest.mark.parametrize("timestamp", (b"-1", b"01"))
def test_commit_parser_rejects_noncanonical_source_epoch(timestamp):
    identity = b"Sector tests <sector-tests@example.invalid> " + timestamp + b" +0000"

    with pytest.raises(CommitTreeError, match="canonical nonnegative timestamp"):
        _parse_commit(_commit_payload("a" * 40, committer=identity))


def test_unrelated_malformed_object_does_not_affect_selected_closure(tmp_path):
    root, commit = _repository(tmp_path)
    malformed = b"tree " + (b"0" * 40) + b"\nauthor broken\n\ninvalid\n"
    _write_literal(root, "commit", malformed)

    evidence = export_commit(root, commit, tmp_path / "exact-source")

    assert evidence.source_revision == commit


def test_selected_malformed_commit_is_rejected_despite_fsck_policy(tmp_path):
    root, _commit = _repository(tmp_path)
    tree = _git(root, "rev-parse", "HEAD^{tree}")
    malformed = _write_literal(
        root,
        "commit",
        _commit_payload(tree, author=b"Sector tests 1 +0000"),
    )
    _git(root, "config", "fsck.missingEmail", "ignore")
    skip_list = root / "skip-list.txt"
    skip_list.write_text(malformed + "\n", encoding="ascii")
    _git(root, "config", "fsck.skipList", str(skip_list))

    with pytest.raises(CommitTreeError, match="author identity"):
        export_commit(root, malformed, tmp_path / "exact-source")


def test_replacement_ref_cannot_change_the_requested_commit(tmp_path):
    root, original = _repository(tmp_path)
    (root / "app" / "tracked.txt").write_bytes(b"replacement\n")
    _git(root, "add", "app/tracked.txt")
    _git(root, "commit", "--quiet", "-m", "replacement")
    replacement = _git(root, "rev-parse", "HEAD")
    _git(root, "replace", original, replacement)

    export_commit(root, original, tmp_path / "exact-source")

    assert (tmp_path / "exact-source" / "app" / "tracked.txt").read_bytes() == (
        b"accepted:app\n"
    )


@pytest.mark.parametrize("flag", ("--assume-unchanged", "--skip-worktree"))
def test_index_hints_cannot_change_exported_bytes(tmp_path, flag):
    root, commit = _repository(tmp_path)
    _git(root, "update-index", flag, "app/tracked.txt")
    (root / "app" / "tracked.txt").write_bytes(b"mutable\n")

    export_commit(root, commit, tmp_path / "exact-source")

    assert (tmp_path / "exact-source" / "app" / "tracked.txt").read_bytes() == (
        b"accepted:app\n"
    )


def test_attributes_and_clean_filters_cannot_change_exported_bytes(tmp_path):
    root, commit = _repository(tmp_path)
    attributes = root / ".git" / "info" / "attributes"
    attributes.write_text("app/tracked.txt filter=hostile\n", encoding="ascii")
    _git(root, "config", "filter.hostile.clean", "printf 'filtered\\n'")
    (root / "app" / "tracked.txt").write_bytes(b"mutable\n")

    export_commit(root, commit, tmp_path / "exact-source")

    assert (tmp_path / "exact-source" / "app" / "tracked.txt").read_bytes() == (
        b"accepted:app\n"
    )


@pytest.mark.parametrize("variable", ("GIT_DIR", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY"))
def test_inherited_repository_selection_cannot_redirect_git(tmp_path, monkeypatch, variable):
    first, _first_commit = _repository(tmp_path, "first", "first")
    second, second_commit = _repository(tmp_path, "second", "second")
    values = {
        "GIT_DIR": second / ".git",
        "GIT_COMMON_DIR": second / ".git",
        "GIT_OBJECT_DIRECTORY": second / ".git" / "objects",
    }
    monkeypatch.setenv(variable, str(values[variable]))

    with pytest.raises(CommitTreeError, match="object inspection failed"):
        export_commit(first, second_commit, tmp_path / "exact-source")


def test_git_environment_removes_all_git_controls(monkeypatch):
    monkeypatch.setenv("GIT_DIR", "hostile")
    monkeypatch.setenv("git_config_global", "hostile")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "fsck.missingEmail")
    monkeypatch.setenv("SECTOR_KEEP", "yes")

    environment = _git_environment()

    assert all(not key.upper().startswith("GIT_") for key in environment)
    assert environment["SECTOR_KEEP"] == "yes"


def test_linked_worktree_common_metadata_is_not_an_output_location(tmp_path):
    root, commit = _repository(tmp_path)
    linked = tmp_path / "linked"
    _git(root, "worktree", "add", "--detach", "--quiet", str(linked), commit)
    output = root / ".git" / "objects" / "forbidden"

    with pytest.raises(CommitTreeError, match="Git metadata"):
        export_commit(linked, commit, output)
    assert not output.exists()


@pytest.mark.parametrize(
    "revision",
    ("", "f" * 39, "F" * 40, "g" * 40, "HEAD", "f" * 40 + "x"),
)
def test_revision_must_be_exact_lowercase_sha1(revision, tmp_path):
    with pytest.raises(CommitTreeError, match="lowercase 40-hex"):
        export_commit(tmp_path, revision, tmp_path / "exact-source")


def test_requested_object_must_be_a_commit(tmp_path):
    root, _commit = _repository(tmp_path)
    blob = _git(root, "rev-parse", "HEAD:app/tracked.txt")

    with pytest.raises(CommitTreeError, match="must be a commit"):
        export_commit(root, blob, tmp_path / "exact-source")


def test_repository_must_be_the_exact_worktree_root(tmp_path):
    root, commit = _repository(tmp_path)

    with pytest.raises(CommitTreeError, match="exact worktree root"):
        export_commit(root / "app", commit, tmp_path / "exact-source")


def test_existing_destination_is_never_touched(tmp_path):
    root, commit = _repository(tmp_path)
    destination = tmp_path / "exact-source"
    destination.mkdir()
    marker = destination / "preserve.txt"
    marker.write_text("preserve\n", encoding="ascii")

    with pytest.raises(CommitTreeError, match="already exists"):
        export_commit(root, commit, destination)
    assert marker.read_text(encoding="ascii") == "preserve\n"


def test_dangling_symlink_destination_is_rejected_before_resolution(tmp_path):
    root, commit = _repository(tmp_path)
    missing_target = tmp_path / "missing-target"
    destination = tmp_path / "exact-source"
    try:
        destination.symlink_to(missing_target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")
    assert os.path.lexists(destination)
    assert not destination.exists()

    with pytest.raises(CommitTreeError, match="already exists"):
        export_commit(root, commit, destination)
    assert not missing_target.exists()


def test_symlink_aware_existence_check_precedes_destination_resolution(
    tmp_path, monkeypatch
):
    root, commit = _repository(tmp_path)
    destination = tmp_path / "exact-source"
    original_lexists = os.path.lexists

    def reports_dangling_entry(path):
        if os.fspath(path) == os.fspath(destination):
            return True
        return original_lexists(path)

    monkeypatch.setattr(os.path, "lexists", reports_dangling_entry)

    with pytest.raises(CommitTreeError, match="already exists"):
        export_commit(root, commit, destination)


def test_destination_cannot_contain_the_repository(tmp_path):
    root, commit = _repository(tmp_path / "parent")

    with pytest.raises(CommitTreeError, match="contain the repository"):
        export_commit(root, commit, tmp_path)


def test_destination_cannot_be_inside_worktree_git_metadata(tmp_path):
    root, commit = _repository(tmp_path)
    destination = root / ".git" / "forbidden"

    with pytest.raises(CommitTreeError, match="Git metadata"):
        export_commit(root, commit, destination)
    assert not destination.exists()


@pytest.mark.parametrize(
    ("name", "message"),
    (
        (b"..", "unsafe"),
        (b"bad/name", "unsafe"),
        (b"bad:name", "Windows-unsafe"),
        (b"bad\\name", "Windows-unsafe"),
        (b"trailing.", "Windows-unsafe"),
        (b"trailing ", "Windows-unsafe"),
        (b".GiT", "Git-control"),
        (b"\xff", "UTF-8"),
    ),
)
def test_unsafe_tree_names_fail_closed(name, message):
    blob = "b" * 40
    raw = _tree_entry("100644", name, blob)

    with pytest.raises(CommitTreeError, match=message):
        _parse_tree_object(raw)


@pytest.mark.parametrize(
    "name",
    (b"CON.txt", b"aux", b"COM1 .txt", b"LPT9.log", b"COM\xc2\xb9.txt", b"LPT\xc2\xb3"),
)
def test_windows_device_aliases_are_rejected(name):
    raw = _tree_entry("100644", name, "b" * 40)

    with pytest.raises(CommitTreeError, match="Windows-unsafe"):
        _parse_tree_object(raw)


@pytest.mark.parametrize("mode", ("120000", "160000", "100664", "100600"))
def test_non_regular_or_noncanonical_modes_are_rejected(mode):
    raw = _tree_entry(mode, b"entry", "b" * 40)

    with pytest.raises(CommitTreeError, match="unsupported"):
        _parse_tree_object(raw)


def test_tree_entries_must_be_canonically_sorted():
    raw = (
        _tree_entry("100644", b"z", "b" * 40)
        + _tree_entry("100644", b"a", "c" * 40)
    )

    with pytest.raises(CommitTreeError, match="canonical order"):
        _parse_tree_object(raw)


@pytest.mark.parametrize(
    ("first", "second"),
    ((b"APP", b"app"), (b"e\xcc\x81", b"\xc3\xa9")),
)
def test_case_and_unicode_collisions_are_rejected(first, second):
    entries = sorted(
        (
            (first, "b" * 40),
            (second, "c" * 40),
        ),
        key=lambda item: item[0] + b"\0",
    )
    raw = b"".join(_tree_entry("100644", name, oid) for name, oid in entries)

    with pytest.raises(CommitTreeError, match="collid"):
        _parse_tree_object(raw)


def test_file_directory_collision_is_rejected():
    entries = sorted(
        (
            ("40000", b"app", "b" * 40),
            ("100644", b"APP", "c" * 40),
        ),
        key=lambda item: item[1] + (b"/" if item[0] == "40000" else b"\0"),
    )
    raw = b"".join(_tree_entry(mode, name, oid) for mode, name, oid in entries)

    with pytest.raises(CommitTreeError, match="file/directory|collid"):
        _parse_tree_object(raw)


def test_blob_batch_payload_is_independently_rehashed():
    requested = hashlib.sha1(b"blob 8\0expected").hexdigest()
    raw = f"{requested} blob 8\n".encode("ascii") + b"hostile\n"

    with pytest.raises(CommitTreeError, match="hash mismatch"):
        _parse_batch_response(raw, [requested])


def test_commit_parser_requires_strict_author_and_committer_identity():
    tree = "a" * 40
    payload = _commit_payload(tree, author=b"No Email 1 +0000")

    with pytest.raises(CommitTreeError, match="author identity"):
        _parse_commit(payload)


def test_commit_parser_rejects_non_ascii_tree_identity():
    payload = (
        b"tree "
        + (b"a" * 40)
        + b"\xff\nauthor Sector <sector@example.invalid> 1 +0000\n"
        + b"committer Sector <sector@example.invalid> 1 +0000\n\nfixture\n"
    )

    with pytest.raises(CommitTreeError, match="tree identity is not ASCII"):
        _parse_commit(payload)


def test_cli_runs_without_site_packages(tmp_path):
    root, commit = _repository(tmp_path)
    destination = tmp_path / "exact-source"
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
            str(destination),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={key: value for key, value in os.environ.items() if not key.startswith("PYTHON")},
    )

    assert result.returncode == 0, result.stderr
    assert commit in result.stdout
    assert (destination / "sector" / "tracked.txt").read_bytes() == b"accepted:sector\n"
