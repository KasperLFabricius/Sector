"""Pure adversarial contracts for the unsigned portable Windows distribution."""

from __future__ import annotations

import json
import os
import shutil
import stat
import struct
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

import tools.build_portable_windows as portable_windows
from tools.build_portable_windows import (
    MAX_PORTABLE_FILES,
    UNSIGNED_STATUS,
    ExactBuildError,
    PortableBuildError,
    _pe_unsigned_status,
    _readme,
    _scan_tree,
    _status_signature,
    _validate_relative_path,
    build_portable_windows,
    compare_portable_distributions,
    safe_extract_portable_archive,
    verify_portable_distribution,
)
from tools.build_source_release import build_source_release
from tools.verify_windows_release import verify_source

ROOT = Path(__file__).resolve().parents[1]


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _identity_source(version: str) -> bytes:
    return f'''__version__ = "{version}"
__product_name__ = "Sector"
__description__ = "Structural-analysis and design calculation tool"
__author__ = "Kasper Lindskov Fabricius"
__licensee__ = "Sweco Danmark A/S"
__copyright__ = "Copyright (c) 2026 Kasper Lindskov Fabricius. All rights reserved."
'''.encode()


def _version_resource(version: str) -> bytes:
    major, minor = version.split(".")
    dotted = f"{major}.{minor}.0.0"
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({major}, {minor}, 0, 0), prodvers=({major}, {minor}, 0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('Comments', 'Licensed to Sweco Danmark A/S for internal organisational use only.'),
    StringStruct('FileVersion', '{dotted}'),
    StringStruct('ProductVersion', '{dotted}'),
    StringStruct('ProductName', 'Sector'),
    StringStruct('OriginalFilename', 'Sector.exe')
  ])])]
)
""".encode()


def _repository(tmp_path: Path, *, version: str = "7.3") -> tuple[Path, str]:
    root = tmp_path / "source repository"
    root.mkdir(parents=True)
    _git(root, "init", "--quiet")
    _git(root, "config", "user.email", "portable@example.invalid")
    _git(root, "config", "user.name", "Portable tests")
    _git(root, "config", "core.autocrlf", "false")
    files = {
        "LICENSE": b"proprietary portable test licence\n",
        "requirements-build.txt": b"accepted hash-locked build input\n",
        "sector/__init__.py": _identity_source(version),
        "sector/calculation.py": b"accepted calculation bytes\n",
        "app/sector_app.py": b"accepted app bytes\n",
        "assets/sector.txt": b"accepted asset bytes\n",
        "packaging/windows_version_info.txt": _version_resource(version),
        "packaging/sector.spec": b"# accepted spec\n",
        "packaging/run_sector.py": b"# accepted launcher\n",
        "packaging/README-PORTABLE.txt": (
            b"Sector @SECTOR_VERSION@ unsigned portable application.\n"
            b"Use the complete folder or ZIP under LICENSE. No installation or "
            b"administrator rights are required. This claims no digital signature, "
            b"trusted publisher, SmartScreen reputation, or production approval. "
            b"Microsoft Edge is required for report figures. Authenticate the "
            b"official source ZIP with its externally published SHA-256.\n"
        ),
        "tools/generate_third_party_notices.py": b"# accepted notice generator\n",
        "tools/export_commit_tree.py": (
            ROOT / "tools" / "export_commit_tree.py"
        ).read_bytes(),
        "tools/build_source_release.py": (
            ROOT / "tools" / "build_source_release.py"
        ).read_bytes(),
        "tools/verify_windows_release.py": (
            ROOT / "tools" / "verify_windows_release.py"
        ).read_bytes(),
    }
    for relative, payload in files.items():
        target = root.joinpath(*PurePosixPath(relative).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    _git(root, "add", ".")
    _git(root, "commit", "--quiet", "-m", "portable fixture")
    return root, _git(root, "rev-parse", "HEAD")


def _pe(*, certificate: bool = False) -> bytes:
    payload = bytearray(512)
    payload[:2] = b"MZ"
    struct.pack_into("<I", payload, 0x3C, 0x80)
    payload[0x80:0x84] = b"PE\0\0"
    coff = 0x84
    struct.pack_into("<H", payload, coff + 16, 0xF0)
    optional = coff + 20
    struct.pack_into("<H", payload, optional, 0x20B)
    struct.pack_into("<I", payload, optional + 108, 16)
    if certificate:
        struct.pack_into("<II", payload, optional + 112 + 32, 480, 16)
    return bytes(payload)


def _manifest(environment: dict[str, str], version: str) -> bytes:
    value = {
        "product_name": "Sector",
        "description": "Structural-analysis and design calculation tool",
        "sector_version": version,
        "author": "Kasper Lindskov Fabricius",
        "licensee": "Sweco Danmark A/S",
        "copyright": "Copyright (c) 2026 Kasper Lindskov Fabricius. All rights reserved.",
        "built_at_utc": environment["SECTOR_SOURCE_COMMITTED_AT_UTC"],
        "source_revision": environment["SECTOR_SOURCE_REVISION"],
        "source_tree": environment["SECTOR_SOURCE_TREE"],
        "source_committer_epoch": int(environment["SECTOR_SOURCE_COMMITTER_EPOCH"]),
        "source_committed_at_utc": environment["SECTOR_SOURCE_COMMITTED_AT_UTC"],
        "source_file_count": int(environment["SECTOR_SOURCE_FILE_COUNT"]),
        "source_total_bytes": int(environment["SECTOR_SOURCE_TOTAL_BYTES"]),
        "source_inventory_sha256": environment["SECTOR_SOURCE_INVENTORY_SHA256"],
    }
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("ascii")


def _runner(version: str, *, certificate: bool = False, fail: bool = False):
    def run(command):
        source = command.cwd
        run_root = source.parent
        arguments = tuple(str(item) for item in command.arguments)
        if any(item.endswith("generate_third_party_notices.py") for item in arguments):
            if fail:
                raise ExactBuildError("controlled fake runner failure")
            notices = source / "build" / "legal" / "THIRD_PARTY_NOTICES.txt"
            notices.parent.mkdir(parents=True)
            notices.write_text(
                "SECTOR THIRD-PARTY NOTICES\nnumpy\nstreamlit\n", encoding="utf-8"
            )
        if "PyInstaller" in arguments:
            package = run_root / "dist" / "Sector"
            internal = package / "_internal"
            for name in ("app", "sector", "assets"):
                shutil.copytree(source / name, internal / name)
            build_manifest = source / "build" / "sector_build_info.json"
            build_manifest.parent.mkdir(parents=True, exist_ok=True)
            build_manifest.write_bytes(_manifest(command.environment, version))
            (internal / "sector" / "sector_build_info.json").write_bytes(
                build_manifest.read_bytes()
            )
            package.mkdir(parents=True, exist_ok=True)
            (package / "Sector.exe").write_bytes(_pe(certificate=certificate))

    return run


def _build(tmp_path: Path, *, version: str = "7.3", name: str = "dist"):
    root, revision = _repository(tmp_path / name, version=version)
    output = tmp_path / f"{name} output"
    evidence = build_portable_windows(
        root, revision, output, runner=_runner(version)
    )
    return root, revision, output, evidence


_TEST_ZIP_ROOT = "Sector-v7.3-windows-portable-unsigned"
_TEST_ZIP_TIMESTAMP = (2026, 2, 3, 4, 5, 6)


def _canonical_test_archive(path: Path, relative: str = "plain.txt") -> Path:
    name = f"{_TEST_ZIP_ROOT}/{relative}"
    info = portable_windows._zip_info(name, relative, _TEST_ZIP_TIMESTAMP)
    with zipfile.ZipFile(
        path, "w", compression=zipfile.ZIP_STORED, allowZip64=False
    ) as bundle:
        bundle.writestr(info, b"canonical portable payload\n")
    return path


def _single_zip_header_offsets(path: Path) -> tuple[bytearray, int, int]:
    payload = bytearray(path.read_bytes())
    eocd = payload.rfind(b"PK\x05\x06")
    assert eocd >= 0
    central = struct.unpack_from("<I", payload, eocd + 16)[0]
    assert payload[central : central + 4] == b"PK\x01\x02"
    local = struct.unpack_from("<I", payload, central + 42)[0]
    assert payload[local : local + 4] == b"PK\x03\x04"
    return payload, local, central


def test_complete_portable_build_is_dynamic_canonical_and_reverifiable(tmp_path):
    root, revision, output, evidence = _build(tmp_path)

    assert evidence.sector_version == "7.3"
    assert evidence.folder_name == "Sector-v7.3-windows-portable-unsigned"
    assert evidence.unsigned_status == UNSIGNED_STATUS
    assert evidence.archive.name == f"{evidence.folder_name}.zip"
    assert evidence.sidecar.name == f"{evidence.folder_name}.zip.sha256"
    assert evidence.receipt.name == (
        f"{evidence.folder_name}.portable-distribution.json"
    )
    assert {path.name for path in output.iterdir()} == {
        evidence.folder.name,
        evidence.archive.name,
        evidence.sidecar.name,
        evidence.receipt.name,
    }
    assert {
        "Sector.exe",
        "_internal",
        "README-PORTABLE.txt",
        "LICENSE",
        "THIRD_PARTY_NOTICES.txt",
        "sector_build_info.json",
        "package_manifest.json",
        "SHA256SUMS.txt",
    }.issubset(path.name for path in evidence.folder.iterdir())
    assert verify_portable_distribution(root, revision, output) == evidence

    receipt = json.loads(evidence.receipt.read_text(encoding="ascii"))
    assert receipt["unsigned_status"] == UNSIGNED_STATUS
    assert receipt["built_at_utc"] == receipt["source_committed_at_utc"]
    assert not any(":" in str(value) for key, value in receipt.items() if key.endswith("name"))


def test_tracked_readme_template_and_authenticated_version_render_together():
    attributes = (ROOT / ".gitattributes").read_text(encoding="ascii").splitlines()
    assert "packaging/README-PORTABLE.txt text eol=lf" in attributes
    template = (
        ROOT / "packaging" / "README-PORTABLE.txt"
    ).read_bytes()
    assert b"\r" not in template
    snapshot = SimpleNamespace(
        files=(
            SimpleNamespace(
                path="packaging/README-PORTABLE.txt", payload=template
            ),
        )
    )

    rendered = _readme(snapshot, {"__version__": "8.4"})

    assert b"Sector-v8.4-windows-portable-unsigned" in rendered
    assert b"@SECTOR_VERSION@" not in rendered
    assert b"Microsoft Edge" in rendered
    assert b"trusted release channel" in rendered
    assert b"SHA-256" in rendered


def test_gitless_official_source_authenticates_same_portable_distribution(tmp_path):
    root, revision, output, evidence = _build(tmp_path)
    source_zip = tmp_path / "Sector-source.zip"
    build_source_release(root, revision, source_zip)
    extracted = tmp_path / "OneDrive - Example" / "source with spaces"
    with zipfile.ZipFile(source_zip) as bundle:
        bundle.extractall(extracted)
    [gitless_root] = list(extracted.iterdir())

    verify_source(gitless_root, revision)
    before = sorted(
        path.relative_to(gitless_root).as_posix()
        for path in gitless_root.rglob("*")
    )
    isolated = subprocess.run(
        [
            sys.executable,
            "-B",
            "-I",
            "-S",
            str(gitless_root / "tools" / "verify_windows_release.py"),
            "--root",
            str(gitless_root),
            "--source-revision",
            revision,
            "--preflight",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert isolated.returncode == 0, isolated.stderr
    assert sorted(
        path.relative_to(gitless_root).as_posix()
        for path in gitless_root.rglob("*")
    ) == before
    verified = verify_portable_distribution(gitless_root, revision, output)
    assert verified.archive_sha256 == evidence.archive_sha256


def test_two_builds_and_every_published_byte_are_reproducible(tmp_path):
    root, revision = _repository(tmp_path / "shared")
    first = tmp_path / "first output"
    second = tmp_path / "second output"
    build_portable_windows(root, revision, first, runner=_runner("7.3"))
    build_portable_windows(root, revision, second, runner=_runner("7.3"))
    comparison_path = tmp_path / "portable-comparison.json"

    comparison = compare_portable_distributions(first, second, comparison_path)

    assert comparison.unsigned_status == UNSIGNED_STATUS
    assert comparison.artifact_name == "Sector-v7.3-windows-portable-unsigned"
    assert json.loads(comparison_path.read_text(encoding="ascii"))["result"] == (
        "byte-identical"
    )
    assert str(first) not in comparison_path.read_text(encoding="ascii")
    with pytest.raises(PortableBuildError, match="outside both"):
        compare_portable_distributions(first, second, first / "comparison.json")
    with pytest.raises(PortableBuildError, match="already exists"):
        compare_portable_distributions(first, second, comparison_path)


def test_certificate_table_is_rejected_and_no_final_output_is_published(tmp_path):
    root, revision = _repository(tmp_path)
    output = tmp_path / "final dist"

    with pytest.raises(PortableBuildError, match="certificate table"):
        build_portable_windows(
            root, revision, output, runner=_runner("7.3", certificate=True)
        )
    assert not output.exists()
    assert not list(tmp_path.glob("final dist/*.zip"))


def test_runner_failure_publishes_no_output_or_final_zip(tmp_path):
    root, revision = _repository(tmp_path)
    output = tmp_path / "final dist"

    with pytest.raises(PortableBuildError, match="controlled fake"):
        build_portable_windows(root, revision, output, runner=_runner("7.3", fail=True))
    assert not output.exists()
    assert not list(tmp_path.rglob("Sector-v*-windows-portable-unsigned.zip"))


def test_output_is_create_only_outside_source(tmp_path):
    root, revision = _repository(tmp_path)
    inside = root / "dist"
    with pytest.raises(PortableBuildError, match="outside"):
        build_portable_windows(root, revision, inside, runner=_runner("7.3"))

    existing = tmp_path / "existing"
    existing.mkdir()
    marker = existing / "preserve.txt"
    marker.write_text("preserve\n", encoding="ascii")
    with pytest.raises(PortableBuildError, match="already exists"):
        build_portable_windows(root, revision, existing, runner=_runner("7.3"))
    assert marker.read_text(encoding="ascii") == "preserve\n"


@pytest.mark.parametrize("action", ("build", "verify"))
def test_portable_ingress_rejects_lexical_reparse_root_before_resolve(
    tmp_path, monkeypatch, action
):
    root = tmp_path / "lexical source"
    root.mkdir()
    output = tmp_path / "portable output"
    real_stat = os.stat
    real_resolve = Path.resolve

    def report_reparse(path, *, dir_fd=None, follow_symlinks=True):
        if not follow_symlinks and Path(path) == root:
            status = real_stat(path, dir_fd=dir_fd, follow_symlinks=False)
            return SimpleNamespace(
                st_mode=status.st_mode,
                st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT,
            )
        return real_stat(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)

    def forbid_early_resolve(path, *args, **kwargs):
        if Path(path) == root:
            raise AssertionError("source root resolved before lexical lstat")
        return real_resolve(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", report_reparse)
    monkeypatch.setattr(Path, "resolve", forbid_early_resolve)
    with pytest.raises(PortableBuildError, match="linked or reparse"):
        if action == "build":
            build_portable_windows(root, "a" * 40, output)
        else:
            verify_portable_distribution(root, "a" * 40, output)


@pytest.mark.parametrize(
    "path",
    (
        "../escape.txt",
        "/absolute.txt",
        "C:/drive.txt",
        "folder\\file.txt",
        "folder/file.txt:stream",
        "folder/CON.txt",
        "folder/CON .txt",
        "folder/COM\u00b9.txt",
        "folder/LPT\u00b2.log",
        "folder/trailing. ",
        "folder/e\u0301.txt",
        "folder//empty.txt",
    ),
)
def test_windows_and_archive_unsafe_paths_are_rejected(path):
    with pytest.raises(PortableBuildError):
        _validate_relative_path(path)


def test_portable_version_bound_accepts_current_and_next_release_only_within_limit():
    assert portable_windows._portable_name("0.92").startswith("Sector-v0.92-")
    assert portable_windows._portable_name("0.93").startswith("Sector-v0.93-")
    assert (
        portable_windows.MAX_SECTOR_VERSION_BYTES
        == portable_windows._RELEASE.MAX_SECTOR_VERSION_BYTES
    )
    oversized = "1" * portable_windows.MAX_SECTOR_VERSION_BYTES + ".0"
    with pytest.raises(PortableBuildError, match="version"):
        portable_windows._portable_name(oversized)


@pytest.mark.parametrize(
    ("relative", "expected_flags"),
    (("plain.txt", 0), ("r\u00e9sum\u00e9.txt", 0x800)),
)
def test_canonical_zip_metadata_uses_exact_filename_encoding_policy(
    tmp_path, relative, expected_flags
):
    archive = _canonical_test_archive(tmp_path / "canonical.zip", relative)

    inventory = portable_windows._archive_inventory(archive)
    with zipfile.ZipFile(archive, "r") as bundle:
        [info] = bundle.infolist()

    assert inventory.files[0].path == relative
    assert info.flag_bits == expected_flags
    assert info.create_system == 3
    assert info.create_version == 20
    assert info.extract_version == 20
    assert info.reserved == 0
    assert info.volume == 0
    assert info.internal_attr == 0
    assert info.external_attr == 0o100644 << 16
    extracted = safe_extract_portable_archive(
        archive, tmp_path / "canonical extraction"
    )
    assert (extracted / relative).read_bytes() == b"canonical portable payload\n"


def test_streaming_archive_writer_round_trips_exact_metadata(tmp_path):
    folder = tmp_path / _TEST_ZIP_ROOT
    folder.mkdir()
    (folder / "plain.txt").write_bytes(b"plain\n")
    (folder / "r\u00e9sum\u00e9.txt").write_bytes(b"unicode\n")
    inventory = portable_windows._stable_inventory(folder)
    archive = tmp_path / f"{_TEST_ZIP_ROOT}.zip"

    portable_windows._write_archive(
        folder, _TEST_ZIP_ROOT, inventory, archive, _TEST_ZIP_TIMESTAMP
    )
    archived = portable_windows._archive_inventory(
        archive,
        expected_root=_TEST_ZIP_ROOT,
        expected_timestamp=_TEST_ZIP_TIMESTAMP,
    )
    extracted = safe_extract_portable_archive(
        archive, tmp_path / "streaming writer extraction"
    )

    assert archived.files == inventory.files
    assert portable_windows._stable_inventory(extracted).files == inventory.files


def test_ascii_zip_name_rejects_coherent_utf8_flags(tmp_path):
    archive = _canonical_test_archive(tmp_path / "utf8-ascii.zip")
    payload, local, central = _single_zip_header_offsets(archive)
    struct.pack_into("<H", payload, local + 6, 0x800)
    struct.pack_into("<H", payload, central + 8, 0x800)
    archive.write_bytes(payload)

    with pytest.raises(PortableBuildError, match="metadata is noncanonical"):
        portable_windows._archive_inventory(archive)


@pytest.mark.parametrize(
    "field",
    (
        "create-system",
        "create-version",
        "extract-version",
        "reserved",
        "volume",
        "internal-attr",
        "external-attr",
        "timestamp",
    ),
)
def test_zip_central_metadata_fields_are_exact(tmp_path, field):
    archive = _canonical_test_archive(tmp_path / f"{field}.zip")
    payload, local, central = _single_zip_header_offsets(archive)
    if field == "create-system":
        payload[central + 5] = 0
    elif field == "create-version":
        payload[central + 4] = 19
    elif field == "extract-version":
        payload[central + 6] = 19
        payload[local + 4] = 19
    elif field == "reserved":
        payload[central + 7] = 1
        payload[local + 5] = 1
    elif field == "volume":
        struct.pack_into("<H", payload, central + 34, 1)
    elif field == "internal-attr":
        struct.pack_into("<H", payload, central + 36, 1)
    elif field == "external-attr":
        external = struct.unpack_from("<I", payload, central + 38)[0]
        struct.pack_into("<I", payload, central + 38, external | 1)
    else:
        local_time = struct.unpack_from("<H", payload, local + 10)[0]
        central_time = struct.unpack_from("<H", payload, central + 12)[0]
        struct.pack_into("<H", payload, local + 10, local_time ^ 1)
        struct.pack_into("<H", payload, central + 12, central_time ^ 1)
    archive.write_bytes(payload)

    with pytest.raises(PortableBuildError):
        portable_windows._archive_inventory(
            archive, expected_timestamp=_TEST_ZIP_TIMESTAMP
        )


@pytest.mark.parametrize(
    "field",
    (
        "extract-version",
        "flags",
        "method",
        "time",
        "date",
        "crc",
        "compressed-size",
        "uncompressed-size",
        "name",
        "extra",
    ),
)
def test_zip_local_header_must_equal_central_and_expected_metadata(
    tmp_path, field
):
    archive = _canonical_test_archive(tmp_path / f"local-{field}.zip")
    payload, local, _central = _single_zip_header_offsets(archive)
    if field == "extract-version":
        payload[local + 4] = 19
    elif field == "flags":
        struct.pack_into("<H", payload, local + 6, 0x800)
    elif field == "method":
        struct.pack_into("<H", payload, local + 8, zipfile.ZIP_DEFLATED)
    elif field == "time":
        current = struct.unpack_from("<H", payload, local + 10)[0]
        struct.pack_into("<H", payload, local + 10, current ^ 1)
    elif field == "date":
        current = struct.unpack_from("<H", payload, local + 12)[0]
        struct.pack_into("<H", payload, local + 12, current ^ 1)
    elif field == "crc":
        current = struct.unpack_from("<I", payload, local + 14)[0]
        struct.pack_into("<I", payload, local + 14, current ^ 1)
    elif field == "compressed-size":
        current = struct.unpack_from("<I", payload, local + 18)[0]
        struct.pack_into("<I", payload, local + 18, current + 1)
    elif field == "uncompressed-size":
        current = struct.unpack_from("<I", payload, local + 22)[0]
        struct.pack_into("<I", payload, local + 22, current + 1)
    elif field == "name":
        payload[local + 30] ^= 1
    else:
        struct.pack_into("<H", payload, local + 28, 1)
    archive.write_bytes(payload)

    with pytest.raises(PortableBuildError, match="local metadata is noncanonical"):
        portable_windows._archive_inventory(archive)


@pytest.mark.parametrize("sentinel", ("member-count", "central-size", "member-size"))
def test_zip_raw_preflight_rejects_zip64_sentinels_before_zipfile_allocation(
    tmp_path, monkeypatch, sentinel
):
    archive = _canonical_test_archive(tmp_path / f"zip64-{sentinel}.zip")
    payload, _local, central = _single_zip_header_offsets(archive)
    eocd = payload.rfind(b"PK\x05\x06")
    if sentinel == "member-count":
        struct.pack_into("<H", payload, eocd + 10, 0xFFFF)
    elif sentinel == "central-size":
        struct.pack_into("<I", payload, eocd + 12, 0xFFFFFFFF)
    else:
        struct.pack_into("<I", payload, central + 24, 0xFFFFFFFF)
    archive.write_bytes(payload)

    def unexpected_zipfile(*_args, **_kwargs):
        raise AssertionError("ZipFile opened before raw preflight")

    monkeypatch.setattr(portable_windows.zipfile, "ZipFile", unexpected_zipfile)
    with pytest.raises(PortableBuildError, match="ZIP64"):
        portable_windows._archive_inventory(archive)


def test_zip_raw_preflight_bounds_central_allocation_and_final_size(
    tmp_path, monkeypatch
):
    archive = _canonical_test_archive(tmp_path / "central-bound.zip")
    final_archive = _canonical_test_archive(tmp_path / "final-bound.zip")
    payload = bytearray(archive.read_bytes())
    eocd = payload.rfind(b"PK\x05\x06")
    original_central_size = struct.unpack_from("<I", payload, eocd + 12)[0]
    padding = b"x" * (portable_windows.MAX_RELATIVE_PATH_BYTES + 1)
    payload[eocd:eocd] = padding
    moved_eocd = eocd + len(padding)
    struct.pack_into(
        "<I", payload, moved_eocd + 12, original_central_size + len(padding)
    )
    archive.write_bytes(payload)

    def unexpected_zipfile(*_args, **_kwargs):
        raise AssertionError("ZipFile opened before raw preflight")

    monkeypatch.setattr(portable_windows.zipfile, "ZipFile", unexpected_zipfile)
    with pytest.raises(PortableBuildError, match="allocation bound"):
        portable_windows._archive_inventory(archive)

    monkeypatch.setattr(
        portable_windows, "MAX_ARCHIVE_BYTES", final_archive.stat().st_size - 1
    )
    with pytest.raises(PortableBuildError, match="resource limit|final size"):
        portable_windows._archive_inventory(final_archive)


def test_safe_extraction_preflights_mutated_footer_before_reopening_zipfile(
    tmp_path, monkeypatch
):
    archive = _canonical_test_archive(tmp_path / "reopen-preflight.zip")
    original = portable_windows._archive_inventory

    def authenticate_then_mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        payload = bytearray(archive.read_bytes())
        eocd = payload.rfind(b"PK\x05\x06")
        struct.pack_into("<H", payload, eocd + 10, 0xFFFF)
        archive.write_bytes(payload)
        return result

    monkeypatch.setattr(
        portable_windows, "_archive_inventory", authenticate_then_mutate
    )
    with pytest.raises(PortableBuildError, match="ZIP64"):
        safe_extract_portable_archive(archive, tmp_path / "must-not-exist")


def test_safe_extraction_rechecks_exact_metadata_after_authentication(
    tmp_path, monkeypatch
):
    archive = _canonical_test_archive(tmp_path / "changed-before-extract.zip")
    original = portable_windows._archive_inventory

    def authenticate_then_mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        payload, _local, central = _single_zip_header_offsets(archive)
        struct.pack_into("<H", payload, central + 36, 1)
        archive.write_bytes(payload)
        return result

    monkeypatch.setattr(
        portable_windows, "_archive_inventory", authenticate_then_mutate
    )
    output = tmp_path / "must-not-exist"
    with pytest.raises(PortableBuildError, match="metadata is noncanonical"):
        safe_extract_portable_archive(archive, output)
    assert not output.exists()


def test_safe_extraction_is_create_only_and_preserves_verified_bytes(tmp_path):
    _root, _revision, _output, evidence = _build(tmp_path)
    extraction = tmp_path / "clean extraction"

    wrong = tmp_path / "wrong digest"
    with pytest.raises(PortableBuildError, match="verified distribution digest"):
        safe_extract_portable_archive(
            evidence.archive, wrong, expected_sha256="0" * 64
        )
    assert not wrong.exists()

    extracted_root = safe_extract_portable_archive(
        evidence.archive,
        extraction,
        expected_sha256=evidence.archive_sha256,
    )

    assert extracted_root == extraction / evidence.folder_name
    assert (extracted_root / "Sector.exe").read_bytes() == _pe()
    with pytest.raises(PortableBuildError, match="already exists"):
        safe_extract_portable_archive(evidence.archive, extraction)


def test_safe_extraction_rejects_traversal_before_creating_output(tmp_path):
    archive = tmp_path / "hostile.zip"
    info = zipfile.ZipInfo("Sector-v7.3-windows-portable-unsigned/../escape.txt")
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    info.compress_type = zipfile.ZIP_STORED
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(info, b"hostile")
    output = tmp_path / "extract"

    with pytest.raises(PortableBuildError):
        safe_extract_portable_archive(archive, output)
    assert not output.exists()
    assert not (tmp_path / "escape.txt").exists()


def test_safe_extraction_rejects_archive_mutation_between_authentication_passes(
    tmp_path, monkeypatch
):
    _root, _revision, _output, evidence = _build(tmp_path)
    original = portable_windows._archive_inventory

    def authenticate_then_mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        evidence.archive.write_bytes(evidence.archive.read_bytes() + b"mutated")
        return result

    monkeypatch.setattr(portable_windows, "_archive_inventory", authenticate_then_mutate)
    extraction = tmp_path / "must-not-exist"
    with pytest.raises(PortableBuildError):
        safe_extract_portable_archive(
            evidence.archive,
            extraction,
            expected_sha256=evidence.archive_sha256,
        )
    assert not extraction.exists()


@pytest.mark.parametrize(
    ("target", "match"),
        (
            ("manifest", "manifest"),
            ("sums", "SHA-256 list differs"),
            ("sidecar", "sidecar differs"),
            ("receipt", "receipt"),
            ("archive", "ZIP"),
        ),
)
def test_every_manifest_hash_and_archive_closure_rejects_mutation(tmp_path, target, match):
    root, revision, output, evidence = _build(tmp_path)
    targets = {
        "manifest": evidence.folder / "package_manifest.json",
        "sums": evidence.folder / "SHA256SUMS.txt",
        "sidecar": evidence.sidecar,
        "receipt": evidence.receipt,
        "archive": evidence.archive,
    }
    path = targets[target]
    if target == "archive":
        with zipfile.ZipFile(path, "a") as bundle:
            bundle.writestr("Sector-v7.3-windows-portable-unsigned/foreign.txt", b"x")
    else:
        path.write_bytes(path.read_bytes() + b" ")

    with pytest.raises(PortableBuildError, match=match):
        verify_portable_distribution(root, revision, output)


def test_complete_tree_gate_rejects_reparse_and_resource_exhaustion(tmp_path, monkeypatch):
    tree = tmp_path / "tree"
    tree.mkdir()
    file = tree / "ordinary.txt"
    file.write_bytes(b"ordinary")
    real_stat = os.stat

    def reparse(path, *, dir_fd=None, follow_symlinks=True):
        if not follow_symlinks and Path(path) == file:
            status = real_stat(path, dir_fd=dir_fd, follow_symlinks=False)
            return SimpleNamespace(
                **{
                    name: getattr(status, name)
                    for name in (
                        "st_dev",
                        "st_ino",
                        "st_mode",
                        "st_size",
                        "st_mtime_ns",
                        "st_ctime_ns",
                    )
                },
                st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT,
            )
        return real_stat(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(os, "stat", reparse)
    with pytest.raises(PortableBuildError, match="linked or reparse"):
        _scan_tree(tree)

    monkeypatch.setattr(os, "stat", real_stat)
    for index in range(MAX_PORTABLE_FILES):
        # Do not create tens of thousands of files: force the limit down instead.
        if index == 0:
            break
    monkeypatch.setattr("tools.build_portable_windows.MAX_PORTABLE_FILES", 0)
    with pytest.raises(PortableBuildError, match="file-count"):
        _scan_tree(tree)


def test_tree_and_distribution_scans_stop_before_eager_path_allocation(
    tmp_path, monkeypatch
):
    tree = tmp_path / "bounded tree"
    tree.mkdir()

    class CountingEntries:
        def __init__(self, count):
            self.count = count
            self.yielded = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            for index in range(self.count):
                self.yielded += 1
                yield SimpleNamespace(name=f"entry-{index}")

    tree_entries = CountingEntries(10)
    monkeypatch.setattr(portable_windows, "MAX_PORTABLE_PATHS", 2)
    monkeypatch.setattr(os, "scandir", lambda _path: tree_entries)
    with pytest.raises(PortableBuildError, match="path-count"):
        _scan_tree(tree)
    assert tree_entries.yielded == 3

    distribution_entries = CountingEntries(10)
    monkeypatch.setattr(portable_windows, "MAX_DISTRIBUTION_TOP_LEVEL_ENTRIES", 2)
    monkeypatch.setattr(os, "scandir", lambda _path: distribution_entries)
    with pytest.raises(PortableBuildError, match="top-level path limit"):
        portable_windows._top_level_distribution(tree, "artifact")
    assert distribution_entries.yielded == 3


def test_tree_scan_has_an_independent_directory_cap(tmp_path, monkeypatch):
    tree = tmp_path / "directory bounded tree"
    (tree / "child").mkdir(parents=True)
    monkeypatch.setattr(portable_windows, "MAX_PORTABLE_DIRECTORIES", 0)

    with pytest.raises(PortableBuildError, match="directory-count"):
        _scan_tree(tree)


def test_pe_gate_rejects_malformed_and_signed_images(tmp_path):
    executable = tmp_path / "Sector.exe"
    executable.write_bytes(b"not a PE")
    with pytest.raises(PortableBuildError, match="valid PE"):
        _pe_unsigned_status(executable)
    executable.write_bytes(_pe(certificate=True))
    with pytest.raises(PortableBuildError, match="certificate table"):
        _pe_unsigned_status(executable)


def test_windows_path_stat_and_open_fstat_permission_bits_do_not_false_fail():
    path_status = SimpleNamespace(
        st_dev=1,
        st_ino=2,
        st_mode=stat.S_IFREG | 0o666,
        st_size=3,
        st_mtime_ns=4,
        st_file_attributes=0,
    )
    opened_status = SimpleNamespace(
        st_dev=1,
        st_ino=2,
        st_mode=stat.S_IFREG | 0o444,
        st_size=3,
        st_mtime_ns=4,
        st_file_attributes=0,
    )

    assert _status_signature(path_status) == _status_signature(opened_status)


def test_comparison_stream_check_rejects_coherent_inventory_change(tmp_path):
    root, revision = _repository(tmp_path / "shared")
    first = tmp_path / "first"
    second = tmp_path / "second"
    build_portable_windows(root, revision, first, runner=_runner("7.3"))
    build_portable_windows(root, revision, second, runner=_runner("7.3"))
    target = next(second.rglob("README-PORTABLE.txt"))
    target.write_bytes(target.read_bytes().replace(b"complete", b"tampered"))

    with pytest.raises(PortableBuildError, match="inventories differ"):
        compare_portable_distributions(first, second, tmp_path / "comparison.json")


def test_comparison_allows_only_a_top_level_archive_to_use_archive_size_cap(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(portable_windows, "MAX_PORTABLE_FILE_BYTES", 512)
    monkeypatch.setattr(portable_windows, "MAX_ARCHIVE_BYTES", 700)
    receipt = {
        "source_revision": "a" * 40,
        "source_tree": "b" * 40,
        "sector_version": "0.93",
        "unsigned_status": UNSIGNED_STATUS,
        "folder_name": "Sector-v0.93-windows-portable-unsigned",
    }
    receipt_bytes = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode(
        "ascii"
    )
    assert len(receipt_bytes) < portable_windows.MAX_PORTABLE_FILE_BYTES
    first = tmp_path / "first distribution"
    second = tmp_path / "second distribution"
    for distribution in (first, second):
        distribution.mkdir()
        (distribution / "artifact.zip").write_bytes(b"z" * 600)
        (distribution / "artifact.portable-distribution.json").write_bytes(
            receipt_bytes
        )

    evidence = compare_portable_distributions(
        first, second, tmp_path / "archive-comparison.json"
    )
    assert evidence.distribution_total_bytes == 600 + len(receipt_bytes)

    nested = tmp_path / "nested payload"
    (nested / "payload").mkdir(parents=True)
    (nested / "payload" / "large.zip").write_bytes(b"z" * 600)
    with pytest.raises(PortableBuildError, match="resource limit"):
        portable_windows._stable_inventory(
            nested,
            total_limit=portable_windows.MAX_DISTRIBUTION_TOTAL_BYTES,
            allow_top_level_archive=True,
        )
