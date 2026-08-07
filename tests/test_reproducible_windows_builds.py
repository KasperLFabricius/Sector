"""Adversarial contract for deterministic two-build Windows verification."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

import tools.verify_reproducible_windows_builds as subject


ROOT = Path(__file__).resolve().parent.parent
COMMIT = "a" * 40
TREE = "b" * 40
INVENTORY = "c" * 64
IDENTITY = {
    "source_revision": COMMIT,
    "source_tree": TREE,
    "source_committer_epoch": 123,
    "source_committed_at_utc": "1970-01-01T00:02:03+00:00",
    "source_file_count": 235,
    "source_total_bytes": 6033255,
    "source_inventory_sha256": INVENTORY,
}


def _canonical(value) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("ascii")


def _build(
    root: Path,
    name: str,
    files: dict[str, bytes],
    *,
    identity: dict | None = None,
):
    build_root = root / name
    package = build_root / "dist" / "Sector"
    for relative, payload in files.items():
        path = package / Path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    source_identity = build_root / "source-identity.json"
    source_identity.write_bytes(_canonical(IDENTITY if identity is None else identity))
    return package, source_identity


def _packages(tmp_path: Path):
    files = {
        "Sector.exe": b"deterministic-pe-bytes",
        "LICENSE.txt": b"license\n",
        "_internal/runtime.dll": b"runtime-dependency",
        "_internal/sector/sector_build_info.json": b"manifest\n",
    }
    package_a, identity_a = _build(tmp_path, "build-a", files)
    package_b, identity_b = _build(tmp_path, "build-b", files)
    return package_a, package_b, identity_a, identity_b, files


def _accept_raw_packages(monkeypatch):
    calls = []

    def verify(repository, package, revision, source_identity):
        calls.append((repository, package, revision, source_identity))

    monkeypatch.setattr(subject, "verify_package", verify)
    return calls


def test_complete_packages_match_byte_for_byte_and_write_canonical_evidence(
    tmp_path, monkeypatch
):
    package_a, package_b, identity_a, identity_b, files = _packages(tmp_path)
    calls = _accept_raw_packages(monkeypatch)
    repository = tmp_path / "repository"
    evidence_path = tmp_path / "reproducibility.json"

    evidence = subject.compare_reproducible_builds(
        repository,
        COMMIT,
        package_a,
        package_b,
        identity_a,
        identity_b,
        evidence_path,
    )

    assert calls == [
        (repository, package_a, COMMIT, identity_a),
        (repository, package_b, COMMIT, identity_b),
    ]
    value = json.loads(evidence_path.read_bytes())
    assert evidence_path.read_bytes() == _canonical(value)
    assert value["schema_version"] == 1
    assert value["comparison"] == "complete-package-byte-identity"
    assert value["source_identity"] == IDENTITY
    assert value["source_identity_sha256"] == hashlib.sha256(
        _canonical(IDENTITY)
    ).hexdigest()
    assert value["package_file_count"] == len(files)
    assert value["package_total_bytes"] == sum(map(len, files.values()))
    assert value["package_inventory_sha256"] == evidence.package_inventory_sha256
    assert [item["path"] for item in value["files"]] == sorted(files)
    assert {item["sha256"] for item in value["files"]} == {
        hashlib.sha256(payload).hexdigest() for payload in files.values()
    }


@pytest.mark.parametrize("defect", ("changed", "missing", "extra"))
def test_any_package_inventory_or_byte_difference_fails_without_evidence(
    tmp_path, monkeypatch, defect
):
    package_a, package_b, identity_a, identity_b, _files = _packages(tmp_path)
    _accept_raw_packages(monkeypatch)
    if defect == "changed":
        (package_b / "_internal" / "runtime.dll").write_bytes(b"changed")
    elif defect == "missing":
        (package_b / "LICENSE.txt").unlink()
    else:
        (package_b / "unexpected.bin").write_bytes(b"unexpected")
    evidence_path = tmp_path / "reproducibility.json"

    with pytest.raises(subject.ReproducibilityVerificationError):
        subject.compare_reproducible_builds(
            tmp_path / "repository",
            COMMIT,
            package_a,
            package_b,
            identity_a,
            identity_b,
            evidence_path,
        )

    assert not evidence_path.exists()


def test_matching_mutation_between_passes_is_rejected(tmp_path, monkeypatch):
    package_a, package_b, identity_a, identity_b, _files = _packages(tmp_path)
    _accept_raw_packages(monkeypatch)
    original = subject._compare_pass
    calls = 0

    def mutate_after_first(*args, **kwargs):
        nonlocal calls
        result = original(*args, **kwargs)
        calls += 1
        if calls == 1:
            for package in (package_a, package_b):
                (package / "_internal" / "runtime.dll").write_bytes(
                    b"matching mutation"
                )
        return result

    monkeypatch.setattr(subject, "_compare_pass", mutate_after_first)
    evidence_path = tmp_path / "reproducibility.json"
    with pytest.raises(
        subject.ReproducibilityVerificationError,
        match="changed between authentication passes",
    ):
        subject.compare_reproducible_builds(
            tmp_path / "repository",
            COMMIT,
            package_a,
            package_b,
            identity_a,
            identity_b,
            evidence_path,
        )
    assert not evidence_path.exists()


def test_source_identity_mutation_during_comparison_is_rejected(
    tmp_path, monkeypatch
):
    package_a, package_b, identity_a, identity_b, _files = _packages(tmp_path)
    _accept_raw_packages(monkeypatch)
    original = subject._compare_pass
    calls = 0

    def mutate_identity_after_first(*args, **kwargs):
        nonlocal calls
        result = original(*args, **kwargs)
        calls += 1
        if calls == 1:
            changed = {**IDENTITY, "source_tree": "d" * 40}
            for path in (identity_a, identity_b):
                path.write_bytes(_canonical(changed))
        return result

    monkeypatch.setattr(subject, "_compare_pass", mutate_identity_after_first)
    evidence_path = tmp_path / "reproducibility.json"
    with pytest.raises(
        subject.ReproducibilityVerificationError,
        match="source identity changed during package comparison",
    ):
        subject.compare_reproducible_builds(
            tmp_path / "repository",
            COMMIT,
            package_a,
            package_b,
            identity_a,
            identity_b,
            evidence_path,
        )
    assert not evidence_path.exists()


def test_build_roots_and_identity_files_must_be_genuinely_distinct(
    tmp_path, monkeypatch
):
    package_a, _package_b, identity_a, _identity_b, _files = _packages(tmp_path)
    calls = _accept_raw_packages(monkeypatch)
    with pytest.raises(
        subject.ReproducibilityVerificationError, match="distinct build roots"
    ):
        subject.compare_reproducible_builds(
            tmp_path / "repository",
            COMMIT,
            package_a,
            package_a,
            identity_a,
            identity_a,
            tmp_path / "reproducibility.json",
        )
    assert calls == []


def test_source_identity_bytes_must_match_and_remain_canonical(
    tmp_path, monkeypatch
):
    package_a, package_b, identity_a, identity_b, _files = _packages(tmp_path)
    calls = _accept_raw_packages(monkeypatch)
    changed = {**IDENTITY, "source_tree": "d" * 40}
    identity_b.write_bytes(_canonical(changed))
    evidence_path = tmp_path / "reproducibility.json"

    with pytest.raises(
        subject.ReproducibilityVerificationError, match="source identity"
    ):
        subject.compare_reproducible_builds(
            tmp_path / "repository",
            COMMIT,
            package_a,
            package_b,
            identity_a,
            identity_b,
            evidence_path,
        )

    assert len(calls) == 2
    assert not evidence_path.exists()


def test_existing_evidence_is_never_overwritten(tmp_path, monkeypatch):
    package_a, package_b, identity_a, identity_b, _files = _packages(tmp_path)
    calls = _accept_raw_packages(monkeypatch)
    evidence_path = tmp_path / "reproducibility.json"
    evidence_path.write_bytes(b"preserve me")

    with pytest.raises(
        subject.ReproducibilityVerificationError, match="already exists"
    ):
        subject.compare_reproducible_builds(
            tmp_path / "repository",
            COMMIT,
            package_a,
            package_b,
            identity_a,
            identity_b,
            evidence_path,
        )

    assert calls == []
    assert evidence_path.read_bytes() == b"preserve me"


def _workflow(path: str):
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def _step(job, name: str):
    return next(step for step in job["steps"] if step["name"] == name)


def test_qa_builds_twice_compares_before_upload_and_preserves_both_outputs():
    job = _workflow(".github/workflows/qa.yml")["jobs"]["windows-package"]
    first = _step(job, "Build first unsigned QA package from exact exported source")
    second = _step(job, "Build second unsigned QA package from exact exported source")
    verify = _step(job, "Verify both unsigned QA package identities")
    compare = _step(job, "Compare independent unsigned QA package builds")
    upload = _step(job, "Upload unsigned QA reproducibility evidence")
    assert job["steps"].index(first) < job["steps"].index(second)
    assert job["steps"].index(second) < job["steps"].index(verify)
    assert job["steps"].index(verify) < job["steps"].index(compare)
    assert job["steps"].index(compare) < job["steps"].index(upload)
    assert first["env"]["SECTOR_EXACT_BUILD_ROOT"].endswith("-build-a")
    assert second["env"]["SECTOR_EXACT_BUILD_ROOT"].endswith("-build-b")
    assert first["env"]["SECTOR_EXACT_BUILD_ROOT"] != second["env"][
        "SECTOR_EXACT_BUILD_ROOT"
    ]
    assert first["run"].count("tools/build_exact_commit.py") == 1
    assert second["run"].count("tools/build_exact_commit.py") == 1
    assert verify["run"].count("tools/verify_windows_release.py") == 2
    assert compare["run"].count("tools/verify_reproducible_windows_builds.py") == 1
    upload_paths = upload["with"]["path"]
    for token in (
        "SECTOR_PACKAGE_ROOT_A",
        "SECTOR_PACKAGE_ROOT_B",
        "SECTOR_SOURCE_IDENTITY_A",
        "SECTOR_SOURCE_IDENTITY_B",
        "SECTOR_REPRODUCIBILITY_EVIDENCE",
    ):
        assert token in upload_paths


def test_protected_release_compares_two_builds_before_secret_exposure():
    job = _workflow(".github/workflows/release-windows.yml")["jobs"]["sign-windows"]
    first = _step(job, "Build first exact source-bound package")
    second = _step(job, "Build second exact source-bound package")
    verify = _step(job, "Verify both unsigned packages before secret exposure")
    compare = _step(job, "Compare independent builds before secret exposure")
    identity = _step(job, "Verify Windows identity before secret exposure")
    signing = _step(job, "Sign and independently verify release package")
    steps = job["steps"]
    assert steps.index(first) < steps.index(second) < steps.index(verify)
    assert steps.index(verify) < steps.index(compare) < steps.index(identity)
    assert steps.index(identity) < steps.index(signing)
    assert first["env"]["SECTOR_EXACT_BUILD_ROOT"].endswith("-build-a")
    assert second["env"]["SECTOR_EXACT_BUILD_ROOT"].endswith("-build-b")
    assert compare["run"].count("tools/verify_reproducible_windows_builds.py") == 1
    for step in (first, second, verify, compare, identity):
        assert "secrets." not in json.dumps(step)
