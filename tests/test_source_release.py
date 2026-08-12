"""Exact-commit source/application release archive contracts."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import tools.build_source_release as source_release
from sector import __version__ as SECTOR_VERSION
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
SOURCE_ARCHIVE_NAME = f"Sector-v{SECTOR_VERSION}-source.zip"
SOURCE_ROOT_NAME = f"Sector-v{SECTOR_VERSION}"


@pytest.fixture(scope="module")
def extracted_source_release(tmp_path_factory):
    root = tmp_path_factory.mktemp("verified-source-release")
    archive = root / SOURCE_ARCHIVE_NAME
    build_source_release(ROOT, COMMIT, archive)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(root / "extracted")
    return root / "extracted" / SOURCE_ROOT_NAME


@pytest.fixture(scope="module")
def accepted_source_archive(tmp_path_factory):
    root = tmp_path_factory.mktemp("accepted-source-archive")
    archive = root / SOURCE_ARCHIVE_NAME
    build_source_release(ROOT, COMMIT, archive)
    return archive


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_git_snapshot_limits_match_source_release_ceilings():
    assert source_release._EXPORTER.MAX_SNAPSHOT_FILES == source_release.MAX_SOURCE_FILES
    assert (
        source_release._EXPORTER.MAX_SNAPSHOT_DIRECTORIES
        == source_release.MAX_SOURCE_DIRECTORIES
    )
    assert source_release._EXPORTER.MAX_BLOB_BYTES == source_release.MAX_SOURCE_FILE_BYTES
    assert (
        source_release._EXPORTER.MAX_SNAPSHOT_TOTAL_BYTES
        == source_release.MAX_SOURCE_TOTAL_BYTES
    )
    assert (
        source_release._EXPORTER.MAX_COMMIT_OBJECT_BYTES
        == source_release.MAX_SOURCE_COMMIT_BYTES
    )


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
    archive = tmp_path / SOURCE_ARCHIVE_NAME
    evidence = build_source_release(ROOT, COMMIT, archive)
    verified = verify_source_release(ROOT, COMMIT, archive)

    assert evidence == verified
    assert evidence.source_revision == COMMIT
    assert evidence.sector_version == SECTOR_VERSION
    assert evidence.archive_sha256
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        marker = f"{SOURCE_ROOT_NAME}/sector/sector_build_info.json"
        manifest = json.loads(bundle.read(marker))
        assert f"{SOURCE_ROOT_NAME}/BUILD.bat" in names
        assert f"{SOURCE_ROOT_NAME}/BUILD_SECTOR_PORTABLE.bat" in names
        assert f"{SOURCE_ROOT_NAME}/packaging/build.bat" in names
        assert f"{SOURCE_ROOT_NAME}/packaging/build_qa.bat" in names
        assert manifest["source_revision"] == COMMIT
        assert manifest["source_tree"] == evidence.source_tree
        assert manifest["sector_version"] == SECTOR_VERSION
        assert manifest["source_release_schema"] == 2
        assert manifest["source_commit_payload_base64"]
        assert len(manifest["source_files"]) == evidence.source_file_count
        assert not any(
            "/.git/" in name or name.endswith((".exe", ".msi")) for name in names
        )
        bundle.extractall(tmp_path / "extracted")

    source_root = tmp_path / "extracted" / SOURCE_ROOT_NAME
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


def _altered_release(extracted_source_release: Path, tmp_path: Path) -> Path:
    altered = tmp_path / "altered-release"
    shutil.copytree(extracted_source_release, altered)
    return altered


def _manifest_path(root: Path) -> Path:
    return root / "sector" / "sector_build_info.json"


def _canonical_manifest(value: dict[str, object]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("ascii")


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("product_name", "Sector lookalike"),
        ("sector_version", "9.99"),
        ("author", "Untrusted author"),
    ),
)
def test_gitless_release_rejects_manifest_identity_mutations(
    extracted_source_release, tmp_path, field, replacement
):
    altered = _altered_release(extracted_source_release, tmp_path)
    manifest_path = _manifest_path(altered)
    manifest = json.loads(manifest_path.read_bytes())
    manifest[field] = replacement
    manifest_path.write_bytes(_canonical_manifest(manifest))

    with pytest.raises(SourceReleaseError, match="identity differs"):
        verify_source_release_directory(altered, COMMIT)


def test_gitless_release_rejects_noncanonical_manifest_formatting(
    extracted_source_release, tmp_path
):
    altered = _altered_release(extracted_source_release, tmp_path)
    manifest_path = _manifest_path(altered)
    manifest = json.loads(manifest_path.read_bytes())
    manifest_path.write_bytes(
        (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "ascii"
        )
    )

    with pytest.raises(SourceReleaseError, match="manifest is not canonical"):
        verify_source_release_directory(altered, COMMIT)


def test_manifest_byte_limit_is_checked_before_manifest_allocation(
    extracted_source_release, monkeypatch
):
    size = _manifest_path(extracted_source_release).stat().st_size
    monkeypatch.setattr(source_release, "MAX_SOURCE_MANIFEST_BYTES", size - 1)

    with pytest.raises(SourceReleaseError, match="manifest exceeds the byte limit"):
        verify_source_release_directory(extracted_source_release, COMMIT)


@pytest.mark.parametrize(
    ("constant", "manifest_field", "limit_error"),
    (
        ("MAX_SOURCE_FILES", "source_file_count", "file-count limit"),
        ("MAX_SOURCE_TOTAL_BYTES", "source_total_bytes", "total-byte limit"),
        ("MAX_SOURCE_FILE_BYTES", None, "file exceeds the byte limit"),
    ),
)
def test_manifest_resource_bounds_are_checked_before_source_file_reads(
    extracted_source_release,
    monkeypatch,
    constant,
    manifest_field,
    limit_error,
):
    manifest = json.loads(_manifest_path(extracted_source_release).read_bytes())
    if manifest_field is None:
        declared = max(record["bytes"] for record in manifest["source_files"])
    else:
        declared = manifest[manifest_field]
    assert declared > 0
    monkeypatch.setattr(source_release, constant, declared - 1)
    original = source_release._read_regular_file

    def reject_source_file_reads(path, label, **kwargs):
        if label.startswith("source release file:"):
            raise AssertionError("source payload was read before manifest bounds")
        return original(path, label, **kwargs)

    monkeypatch.setattr(source_release, "_read_regular_file", reject_source_file_reads)

    with pytest.raises(SourceReleaseError, match=limit_error):
        verify_source_release_directory(extracted_source_release, COMMIT)


def _archive_infos(archive: Path) -> list[zipfile.ZipInfo]:
    with zipfile.ZipFile(archive, "r") as bundle:
        return bundle.infolist()


def test_archive_final_size_bound_precedes_zip_inventory_allocation(
    accepted_source_archive, monkeypatch
):
    size = accepted_source_archive.stat().st_size
    monkeypatch.setattr(source_release, "MAX_SOURCE_ARCHIVE_BYTES", size - 1)
    with accepted_source_archive.open("rb") as stream, pytest.raises(
        SourceReleaseError, match="final byte count"
    ):
        source_release._preflight_archive_stream(stream, size)


def test_archive_member_count_bound_precedes_zip_inventory_allocation(
    accepted_source_archive, monkeypatch
):
    infos = _archive_infos(accepted_source_archive)
    monkeypatch.setattr(
        source_release, "MAX_SOURCE_ARCHIVE_MEMBERS", len(infos) - 1
    )
    with accepted_source_archive.open("rb") as stream, pytest.raises(
        SourceReleaseError, match="member-count limit"
    ):
        source_release._preflight_archive_stream(
            stream, accepted_source_archive.stat().st_size
        )


def test_archive_member_size_bound_precedes_member_reads(
    accepted_source_archive, monkeypatch
):
    infos = _archive_infos(accepted_source_archive)
    largest = max(info.file_size for info in infos)
    assert largest > 0
    monkeypatch.setattr(
        source_release, "MAX_SOURCE_ARCHIVE_MEMBER_BYTES", largest - 1
    )

    with pytest.raises(SourceReleaseError, match="member exceeds the byte limit"):
        source_release._validate_archive_infos(infos, {})


def test_archive_expanded_size_bound_precedes_member_reads(
    accepted_source_archive, monkeypatch
):
    infos = _archive_infos(accepted_source_archive)
    expanded = sum(info.file_size for info in infos)
    assert expanded > 0
    monkeypatch.setattr(
        source_release, "MAX_SOURCE_ARCHIVE_EXPANDED_BYTES", expanded - 1
    )

    with pytest.raises(SourceReleaseError, match="expanded-byte limit"):
        source_release._validate_archive_infos(infos, {})


def test_exact_archive_overhead_is_bounded_before_writer_allocation(monkeypatch):
    snapshot = source_release._snapshot(ROOT, COMMIT)
    _prefix, entries = source_release._archive_entries(snapshot)
    exact_size = source_release._validate_archive_entry_bounds(entries)
    stream = io.BytesIO()
    monkeypatch.setattr(source_release, "MAX_SOURCE_ARCHIVE_BYTES", exact_size - 1)

    with pytest.raises(SourceReleaseError, match="final-byte limit"):
        source_release._write_canonical_archive(stream, entries)

    assert stream.getvalue() == b""


@pytest.mark.parametrize(
    ("version", "message"),
    (
        ("65536.1", "component"),
        ("000000000000.1", "length"),
    ),
)
def test_source_version_bounds_precede_archive_name_amplification(
    tmp_path, version, message
):
    repository, _commit = _source_build_script_repository(tmp_path)
    identity = repository / "sector" / "__init__.py"
    identity.write_bytes(
        identity.read_bytes().replace(
            b'__version__ = "0.92"',
            f'__version__ = "{version}"'.encode("ascii"),
        )
    )
    _git(repository, "add", "sector/__init__.py")
    _git(repository, "commit", "--quiet", "-m", "adversarial version")
    commit = _git(repository, "rev-parse", "HEAD")
    archive = tmp_path / "bounded-version.zip"

    with pytest.raises(SourceReleaseError, match=message):
        build_source_release(repository, commit, archive)

    assert not archive.exists()


def test_verification_evidence_uses_the_authenticated_open_stream(
    accepted_source_archive, tmp_path, monkeypatch
):
    archive = tmp_path / "accepted.zip"
    shutil.copyfile(accepted_source_archive, archive)
    authenticated = archive.read_bytes()
    expected_digest = hashlib.sha256(authenticated).hexdigest()
    replacement = b"replacement after final pathname status\n"
    original_status = source_release._nonfollowing_status
    archive_status_calls = 0

    def swap_after_final_status(path, label):
        nonlocal archive_status_calls
        status = original_status(path, label)
        if Path(path) == archive:
            archive_status_calls += 1
            if archive_status_calls == 2:
                archive.replace(tmp_path / "authenticated-original.zip")
                archive.write_bytes(replacement)
        return status

    monkeypatch.setattr(
        source_release, "_nonfollowing_status", swap_after_final_status
    )

    evidence = verify_source_release(ROOT, COMMIT, archive)

    assert archive.read_bytes() == replacement
    assert evidence.archive_bytes == len(authenticated)
    assert evidence.archive_sha256 == expected_digest


def _with_reparse_attribute(status):
    return SimpleNamespace(
        st_dev=status.st_dev,
        st_ino=status.st_ino,
        st_mode=status.st_mode,
        st_size=status.st_size,
        st_mtime_ns=status.st_mtime_ns,
        st_file_attributes=(
            getattr(status, "st_file_attributes", 0)
            | getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        ),
    )


def test_extracted_source_release_rejects_a_reparse_root_before_resolution(
    extracted_source_release, monkeypatch
):
    real_stat = os.stat
    lexical_root = Path(os.path.abspath(extracted_source_release))

    def report_reparse(path, *, dir_fd=None, follow_symlinks=True):
        status = real_stat(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
        if Path(path) == lexical_root and not follow_symlinks:
            return _with_reparse_attribute(status)
        return status

    monkeypatch.setattr(os, "stat", report_reparse)

    with pytest.raises(SourceReleaseError, match="root is a linked or reparse"):
        verify_source_release_directory(extracted_source_release, COMMIT)


def test_extracted_source_release_rejects_a_generic_child_reparse_point(
    extracted_source_release, monkeypatch
):
    real_scandir = os.scandir
    target = extracted_source_release / "LICENSE"

    class EntryProxy:
        def __init__(self, entry):
            self._entry = entry

        def __getattr__(self, name):
            return getattr(self._entry, name)

        def stat(self, *, follow_symlinks=True):
            status = self._entry.stat(follow_symlinks=follow_symlinks)
            if Path(self._entry.path) == target and not follow_symlinks:
                return _with_reparse_attribute(status)
            return status

    def report_child_reparse(path):
        with real_scandir(path) as entries:
            return [EntryProxy(entry) for entry in entries]

    monkeypatch.setattr(os, "scandir", report_child_reparse)

    with pytest.raises(SourceReleaseError, match="linked or reparse path: LICENSE"):
        verify_source_release_directory(extracted_source_release, COMMIT)


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
    first = tmp_path / "first" / SOURCE_ARCHIVE_NAME
    second = tmp_path / "second" / SOURCE_ARCHIVE_NAME

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
    archive = tmp_path / SOURCE_ARCHIVE_NAME
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
