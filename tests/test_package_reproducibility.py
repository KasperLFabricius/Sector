"""Independent adversarial checks for controlled Windows package comparison."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from tools.canonicalize_pyinstaller_archive import (
    ArchiveCanonicalizationError,
    canonicalize_archive,
)
from tools.verify_package_reproducibility import (
    PackageReproducibilityError,
    compare_packages,
    parse_source_date_epoch,
    write_evidence,
)

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "a" * 40
EPOCH = 1_786_000_000


def _stored_archive(path: Path, names: list[str]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 0
            info.external_attr = 0x01800000
            archive.writestr(info, f"payload:{name}\n".encode("ascii"))


def _package(root: Path) -> Path:
    package = root / "Sector"
    (package / "_internal" / "sector").mkdir(parents=True)
    (package / "Sector.exe").write_bytes(b"unsigned executable fixture\n")
    (package / "LICENSE.txt").write_text("license\n", encoding="ascii")
    (package / "_internal" / "sector" / "core.py").write_text(
        "VALUE = 1\n", encoding="ascii"
    )
    return package


def _independent_tree_digest(package: Path) -> str:
    records = []
    paths = [item for item in package.rglob("*") if item.is_file()]
    for path in sorted(paths, key=lambda item: item.relative_to(package).as_posix()):
        relative = path.relative_to(package).as_posix()
        content = path.read_bytes()
        records.append([relative, len(content), hashlib.sha256(content).hexdigest()])
    digest = hashlib.sha256()
    for record in records:
        digest.update(
            json.dumps(record, ensure_ascii=True, separators=(",", ":")).encode(
                "ascii"
            )
        )
        digest.update(b"\n")
    return digest.hexdigest()


def test_identical_trees_produce_complete_deterministic_evidence(tmp_path):
    first = _package(tmp_path / "first")
    second = _package(tmp_path / "second")

    evidence = compare_packages(first, second, COMMIT, EPOCH)

    assert evidence == {
        "schema_version": 1,
        "comparison": "byte-identical-controlled-unsigned-package",
        "source_revision": COMMIT,
        "source_date_epoch": EPOCH,
        "source_date_utc": "2026-08-06T07:06:40+00:00",
        "file_count": 3,
        "total_bytes": sum(path.stat().st_size for path in first.rglob("*") if path.is_file()),
        "package_tree_sha256": _independent_tree_digest(first),
    }

    output = tmp_path / "evidence" / "package-reproducibility.json"
    write_evidence(output, evidence)
    parsed = json.loads(output.read_text(encoding="ascii"))
    assert parsed == evidence
    with pytest.raises(PackageReproducibilityError, match="already exists"):
        write_evidence(output, evidence)


def test_comparison_rejects_one_package_root_supplied_twice(tmp_path):
    package = _package(tmp_path / "package")

    with pytest.raises(PackageReproducibilityError, match="roots must be distinct"):
        compare_packages(package, package, COMMIT, EPOCH)


@pytest.mark.parametrize("mutation", ["changed", "missing", "extra"])
def test_any_inventory_or_byte_difference_fails(tmp_path, mutation):
    first = _package(tmp_path / "first")
    second = _package(tmp_path / "second")
    target = second / "_internal" / "sector" / "core.py"
    if mutation == "changed":
        target.write_text("VALUE = 2\n", encoding="ascii")
    elif mutation == "missing":
        target.unlink()
    else:
        (second / "extra.txt").write_text("extra\n", encoding="ascii")

    with pytest.raises(PackageReproducibilityError, match="trees differ"):
        compare_packages(first, second, COMMIT, EPOCH)


@pytest.mark.parametrize(
    "value", [True, -1, "-1", "01", "1.5", "not-an-epoch", ""]
)
def test_epoch_parser_rejects_noncanonical_values(value):
    with pytest.raises(PackageReproducibilityError, match="non-negative integer"):
        parse_source_date_epoch(value)


@pytest.mark.parametrize("revision", ["a" * 39, "A" * 40, "g" * 40, "HEAD"])
def test_comparison_rejects_non_exact_source_identity(tmp_path, revision):
    first = _package(tmp_path / "first")
    second = _package(tmp_path / "second")
    with pytest.raises(PackageReproducibilityError, match="lowercase 40-hex"):
        compare_packages(first, second, revision, EPOCH)


def test_isolated_cli_writes_evidence_without_site_packages(tmp_path):
    first = _package(tmp_path / "first")
    second = _package(tmp_path / "second")
    output = tmp_path / "evidence.json"
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(ROOT / "tools" / "verify_package_reproducibility.py"),
            "--first",
            str(first),
            "--second",
            str(second),
            "--source-revision",
            COMMIT,
            "--source-date-epoch",
            str(EPOCH),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "byte-identical" in result.stdout
    assert json.loads(output.read_text(encoding="ascii"))["source_revision"] == COMMIT


def test_cli_rejects_evidence_inside_a_package_tree(tmp_path):
    first = _package(tmp_path / "first")
    second = _package(tmp_path / "second")
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(ROOT / "tools" / "verify_package_reproducibility.py"),
            "--first",
            str(first),
            "--second",
            str(second),
            "--source-revision",
            COMMIT,
            "--source-date-epoch",
            str(EPOCH),
            "--output",
            str(first / "evidence.json"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "outside both package trees" in result.stderr


def test_cli_rejects_one_package_root_supplied_twice(tmp_path):
    package = _package(tmp_path / "package")
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(ROOT / "tools" / "verify_package_reproducibility.py"),
            "--first",
            str(package),
            "--second",
            str(package),
            "--source-revision",
            COMMIT,
            "--source-date-epoch",
            str(EPOCH),
            "--output",
            str(tmp_path / "evidence.json"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "roots must be distinct" in result.stderr


def test_pyinstaller_base_library_order_is_canonical_and_idempotent(tmp_path):
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    _stored_archive(first, ["operator.pyc", "encodings/utf_8.pyc", "abc.pyc"])
    _stored_archive(second, ["abc.pyc", "operator.pyc", "encodings/utf_8.pyc"])
    assert first.read_bytes() != second.read_bytes()

    assert canonicalize_archive(first) == 3
    assert canonicalize_archive(second) == 3
    assert first.read_bytes() == second.read_bytes()
    canonical = first.read_bytes()
    assert canonicalize_archive(first) == 3
    assert first.read_bytes() == canonical
    with zipfile.ZipFile(first) as archive:
        assert archive.namelist() == sorted(archive.namelist())
        assert archive.read("operator.pyc") == b"payload:operator.pyc\n"


@pytest.mark.parametrize(
    "names, match",
    [
        (["../escape.pyc"], "unsafe"),
        (["core.pyc", "CORE.pyc"], "case-colliding"),
        (["folder/"], "unsafe"),
    ],
)
def test_archive_canonicalization_rejects_unsafe_names(tmp_path, names, match):
    archive = tmp_path / "base_library.zip"
    _stored_archive(archive, names)
    with pytest.raises(ArchiveCanonicalizationError, match=match):
        canonicalize_archive(archive)


def test_archive_canonicalization_rejects_compressed_members(tmp_path):
    archive = tmp_path / "base_library.zip"
    with zipfile.ZipFile(archive, "w") as target:
        target.writestr("core.pyc", b"payload", compress_type=zipfile.ZIP_DEFLATED)
    with pytest.raises(ArchiveCanonicalizationError, match="not stored"):
        canonicalize_archive(archive)


def test_archive_canonicalizer_runs_without_site_packages(tmp_path):
    archive = tmp_path / "base_library.zip"
    _stored_archive(archive, ["z.pyc", "a.pyc"])
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(ROOT / "tools" / "canonicalize_pyinstaller_archive.py"),
            "--archive",
            str(archive),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "canonicalized 2" in result.stdout
    with zipfile.ZipFile(archive) as result_archive:
        assert result_archive.namelist() == ["a.pyc", "z.pyc"]
