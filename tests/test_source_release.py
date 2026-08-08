"""Exact-commit source/application release archive contracts."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from tools.build_exact_commit import prepare_exact_build
from tools.build_source_release import (
    SourceReleaseError,
    build_source_release,
    materialize_source_release,
    verify_source_release,
    verify_source_release_directory,
)

ROOT = Path(__file__).resolve().parents[1]
COMMIT = subprocess.run(
    ["git", "rev-parse", "HEAD"],
    cwd=ROOT,
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()


@pytest.fixture(scope="module")
def extracted_source_release(tmp_path_factory):
    root = tmp_path_factory.mktemp("verified-source-release")
    archive = root / "Sector-v0.92-source.zip"
    build_source_release(ROOT, COMMIT, archive)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(root / "extracted")
    return root / "extracted" / "Sector-v0.92"


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _source_build_script_repository(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "source-build-script-repository"
    root.mkdir()
    _git(root, "init", "--quiet")
    _git(root, "config", "user.email", "sector-source@example.invalid")
    _git(root, "config", "user.name", "Sector source release tests")
    _git(root, "config", "core.autocrlf", "false")
    files = {
        "packaging/build.ps1": (ROOT / "packaging" / "build.ps1").read_bytes(),
        "tools/build_exact_commit.py": (
            ROOT / "tools" / "build_exact_commit.py"
        ).read_bytes(),
        "tools/build_source_release.py": (
            ROOT / "tools" / "build_source_release.py"
        ).read_bytes(),
        "tools/export_commit_tree.py": (
            ROOT / "tools" / "export_commit_tree.py"
        ).read_bytes(),
        "sector/__init__.py": (
            b'__version__ = "0.92"\n'
            b'__product_name__ = "Sector"\n'
            b'__description__ = "Fixture"\n'
            b'__author__ = "Fixture author"\n'
            b'__licensee__ = "Fixture licensee"\n'
            b'__copyright__ = "Fixture copyright"\n'
        ),
    }
    for relative, payload in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    _git(root, "add", ".")
    _git(root, "commit", "--quiet", "-m", "source build resolver fixture")
    return root, _git(root, "rev-parse", "HEAD")


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
        assert manifest["source_release_schema"] == 2
        assert manifest["source_commit_payload_base64"]
        assert len(manifest["source_files"]) == evidence.source_file_count
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


def test_extracted_source_release_materializes_an_exact_isolated_build_tree(
    extracted_source_release, tmp_path
):
    snapshot = verify_source_release_directory(extracted_source_release, COMMIT)
    isolated = tmp_path / "isolated-source"

    evidence = materialize_source_release(
        extracted_source_release, COMMIT, isolated
    )

    assert evidence == snapshot.evidence
    assert evidence.source_revision == COMMIT
    assert not (isolated / "sector" / "sector_build_info.json").exists()
    assert (isolated / "packaging" / "build.ps1").read_bytes() == (
        extracted_source_release / "packaging" / "build.ps1"
    ).read_bytes()


def test_exact_build_plan_accepts_a_verified_extracted_source_release(
    extracted_source_release, tmp_path
):
    plan = prepare_exact_build(
        extracted_source_release, COMMIT, tmp_path / "exact-build"
    )

    assert plan.source_revision == COMMIT
    assert plan.source_evidence.source_tree
    assert not (plan.source_root / "sector" / "sector_build_info.json").exists()
    assert plan.commands[0].cwd == plan.source_root


def test_extracted_source_release_rejects_a_tampered_file_without_output(
    extracted_source_release, tmp_path
):
    altered = tmp_path / "altered"
    shutil.copytree(extracted_source_release, altered)
    target = altered / "packaging" / "build.ps1"
    target.write_bytes(target.read_bytes() + b"# altered\n")
    output = tmp_path / "must-not-exist"

    with pytest.raises(SourceReleaseError, match="differs from its manifest"):
        materialize_source_release(altered, COMMIT, output)
    assert not output.exists()


def test_extracted_source_release_rejects_uninventoried_files(
    extracted_source_release, tmp_path
):
    altered = tmp_path / "altered"
    shutil.copytree(extracted_source_release, altered)
    (altered / "unexpected.txt").write_text("not accepted\n", encoding="ascii")

    with pytest.raises(SourceReleaseError, match="directory inventory differs"):
        verify_source_release_directory(altered, COMMIT)


def test_extracted_source_release_rejects_the_wrong_requested_revision(
    extracted_source_release,
):
    with pytest.raises(SourceReleaseError, match="requested revision"):
        verify_source_release_directory(extracted_source_release, "0" * 40)


@pytest.mark.skipif(os.name != "nt", reason="PowerShell resolver contract is Windows-only")
def test_powershell_resolves_verified_source_revision_without_git(tmp_path):
    repository, commit = _source_build_script_repository(tmp_path)
    archive = tmp_path / "Sector-v0.92-source.zip"
    build_source_release(repository, commit, archive)
    extracted = tmp_path / "extracted"
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(extracted)
    source_root = extracted / "Sector-v0.92"
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    capture = tmp_path / "python-arguments.txt"
    (fake_bin / "python.bat").write_text(
        '@echo off\r\necho %* > "%SECTOR_TEST_CAPTURE%"\r\nexit /b 0\r\n',
        encoding="ascii",
    )
    powershell = shutil.which("powershell")
    assert powershell is not None
    environment = dict(os.environ)
    environment["PATH"] = str(fake_bin)
    environment["SECTOR_TEST_CAPTURE"] = str(capture)

    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(source_root / "packaging" / "build.ps1"),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    arguments = capture.read_text(encoding="ascii")
    assert "--source-revision" in arguments
    assert commit in arguments
    assert "--root" in arguments
    assert "not a git repository" not in (result.stdout + result.stderr)


def test_extracted_build_driver_does_not_mutate_source_while_loading(tmp_path):
    repository, commit = _source_build_script_repository(tmp_path)
    archive = tmp_path / "Sector-v0.92-source.zip"
    build_source_release(repository, commit, archive)
    extracted = tmp_path / "extracted"
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(extracted)
    source_root = extracted / "Sector-v0.92"

    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(source_root / "tools" / "build_exact_commit.py"),
            "--help",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert not list(source_root.rglob("*.pyc"))
    assert not list(source_root.rglob("__pycache__"))
    assert verify_source_release_directory(source_root, commit).evidence.source_revision == commit


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

    with pytest.raises(SourceReleaseError, match="complete source archive bytes differ"):
        verify_source_release(ROOT, COMMIT, incomplete)


def test_two_source_archive_builds_are_byte_identical(tmp_path):
    first = tmp_path / "first" / "Sector-v0.92-source.zip"
    second = tmp_path / "second" / "Sector-v0.92-source.zip"

    first_evidence = build_source_release(ROOT, COMMIT, first)
    second_evidence = build_source_release(ROOT, COMMIT, second)

    assert first.read_bytes() == second.read_bytes()
    assert first_evidence == second_evidence


@pytest.mark.parametrize("position", ("prefix", "suffix"))
def test_source_archive_rejects_bytes_outside_canonical_zip(tmp_path, position):
    accepted = tmp_path / "accepted.zip"
    build_source_release(ROOT, COMMIT, accepted)
    payload = accepted.read_bytes()
    altered = tmp_path / f"{position}.zip"
    altered.write_bytes(
        b"unverified-prefix" + payload
        if position == "prefix"
        else payload + b"unverified-suffix"
    )

    with pytest.raises(SourceReleaseError, match="complete source archive bytes differ"):
        verify_source_release(ROOT, COMMIT, altered)


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
