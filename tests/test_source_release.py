"""Exact-commit source/application release archive contracts."""

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from tools.build_source_release import (
    SourceReleaseError,
    build_source_release,
    verify_source_release,
)

ROOT = Path(__file__).resolve().parents[1]
COMMIT = subprocess.run(
    ["git", "rev-parse", "HEAD"],
    cwd=ROOT,
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()


def test_source_archive_is_exact_and_reports_revision_without_git(tmp_path):
    archive = tmp_path / "Sector-v0.92-source.zip"
    evidence = build_source_release(ROOT, COMMIT, archive)
    verified = verify_source_release(ROOT, COMMIT, archive)

    assert evidence == verified
    assert evidence.source_revision == COMMIT
    assert evidence.sector_version == "0.92"
    assert evidence.archive_sha256
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        marker = "Sector-v0.92/sector/sector_build_info.json"
        manifest = json.loads(bundle.read(marker))
        assert manifest["source_revision"] == COMMIT
        assert manifest["source_tree"] == evidence.source_tree
        assert manifest["sector_version"] == "0.92"
        assert not any(
            "/.git/" in name or name.endswith((".exe", ".msi")) for name in names
        )
        bundle.extractall(tmp_path / "extracted")

    source_root = tmp_path / "extracted" / "Sector-v0.92"
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-c",
            (
                "import sys;"
                f"sys.path.insert(0, {str(source_root)!r});"
                "from sector.build_info import source_revision;"
                "print(source_revision())"
            ),
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == COMMIT


def test_github_style_snapshot_without_manifest_is_not_a_release_archive(tmp_path):
    accepted = tmp_path / "accepted.zip"
    build_source_release(ROOT, COMMIT, accepted)
    incomplete = tmp_path / "automatic-source.zip"
    with zipfile.ZipFile(accepted) as source, zipfile.ZipFile(
        incomplete, "x", compression=zipfile.ZIP_STORED
    ) as target:
        for info in source.infolist():
            if not info.filename.endswith("/sector/sector_build_info.json"):
                target.writestr(info, source.read(info))

    with pytest.raises(SourceReleaseError, match="inventory differs"):
        verify_source_release(ROOT, COMMIT, incomplete)


def test_two_source_archive_builds_are_byte_identical(tmp_path):
    first = tmp_path / "first" / "Sector-v0.92-source.zip"
    second = tmp_path / "second" / "Sector-v0.92-source.zip"

    first_evidence = build_source_release(ROOT, COMMIT, first)
    second_evidence = build_source_release(ROOT, COMMIT, second)

    assert first.read_bytes() == second.read_bytes()
    assert first_evidence == second_evidence


def test_existing_source_archive_is_preserved(tmp_path):
    archive = tmp_path / "Sector-v0.92-source.zip"
    archive.write_bytes(b"preserve")

    with pytest.raises(SourceReleaseError, match="already exists"):
        build_source_release(ROOT, COMMIT, archive)
    assert archive.read_bytes() == b"preserve"


@pytest.mark.parametrize("revision", ("HEAD", "f" * 39, "F" * 40))
def test_source_archive_requires_exact_commit(revision, tmp_path):
    with pytest.raises(SourceReleaseError, match="exact source commit"):
        build_source_release(
            ROOT,
            revision,
            tmp_path / f"Sector-{len(revision)}-source.zip",
        )
