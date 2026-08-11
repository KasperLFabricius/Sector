"""Adversarial contracts for the exact unsigned Sector v0.93 draft release."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import tools.verify_v093_release as release

REVISION = "a" * 40
TREE = "b" * 40
PORTABLE_FOLDER_NAME = "Sector-v0.93-windows-portable-unsigned"
SOURCE_BYTES = b"canonical source archive bytes\n"
PORTABLE_BYTES = b"canonical portable archive bytes\n"
PORTABLE_RECEIPT = b'{\n  "portable_distribution_schema": 1\n}\n'


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("ascii")


def _qa_value(*, run_id: int = 987654, run_attempt: int = 3) -> dict[str, object]:
    return {
        "qa_evidence_schema": 1,
        "repository": "KasperLFabricius/Sector",
        "head_repository": "KasperLFabricius/Sector",
        "workflow_name": "Sector QA",
        "event": "push",
        "head_branch": "main",
        "head_sha": REVISION,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "conclusion": "success",
        "jobs": [
            {"name": name, "id": 1000 + index, "conclusion": "success"}
            for index, name in enumerate(release.QA_JOB_NAMES)
        ],
        "artifacts": [
            {
                "name": name,
                "id": 2000 + index,
                "digest": f"sha256:{index + 1:064x}",
                "expired": False,
            }
            for index, name in enumerate(
                release._expected_artifact_names(run_id, run_attempt)
            )
        ],
    }


def _write_qa(path: Path, value: dict[str, object] | None = None) -> Path:
    path.write_bytes(_canonical_json(_qa_value() if value is None else value))
    return path


@pytest.fixture
def release_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "repository"
    root.mkdir()
    qa_path = _write_qa(tmp_path / "qa-evidence.json")
    portable = tmp_path / "portable-distribution"
    folder = portable / PORTABLE_FOLDER_NAME
    folder.mkdir(parents=True)
    (folder / "Sector.exe").write_bytes(b"unsigned executable bytes")
    archive = portable / release.PORTABLE_ARCHIVE_NAME
    archive.write_bytes(PORTABLE_BYTES)
    archive_sha256 = hashlib.sha256(PORTABLE_BYTES).hexdigest()
    sidecar = portable / release.PORTABLE_SIDECAR_NAME
    sidecar.write_bytes(
        f"{archive_sha256}  {release.PORTABLE_ARCHIVE_NAME}\n".encode("ascii")
    )
    receipt = portable / release.PORTABLE_RECEIPT_NAME
    receipt.write_bytes(PORTABLE_RECEIPT)

    def source_evidence(path: Path):
        payload = path.read_bytes()
        if payload != SOURCE_BYTES:
            raise release.SourceReleaseError("controlled source mutation")
        return SimpleNamespace(
            source_revision=REVISION,
            source_tree=TREE,
            sector_version=release.SECTOR_VERSION,
            archive_entries=12,
            archive_bytes=len(payload),
            archive_sha256=hashlib.sha256(payload).hexdigest(),
        )

    def build_source(root_path: Path, revision: str, path: Path):
        assert root_path == root
        assert revision == REVISION
        path.write_bytes(SOURCE_BYTES)
        return source_evidence(path)

    def verify_source(root_path: Path, revision: str, path: Path):
        assert root_path == root
        assert revision == REVISION
        return source_evidence(path)

    def verify_portable(root_path: Path, revision: str, output: Path):
        assert root_path == root
        assert revision == REVISION
        candidate_archive = output / release.PORTABLE_ARCHIVE_NAME
        candidate_sidecar = output / release.PORTABLE_SIDECAR_NAME
        candidate_receipt = output / release.PORTABLE_RECEIPT_NAME
        candidate_folder = output / PORTABLE_FOLDER_NAME
        if not candidate_folder.is_dir() or not (candidate_folder / "Sector.exe").is_file():
            raise release.PortableBuildError("controlled portable folder mutation")
        try:
            payload = candidate_archive.read_bytes()
            sidecar_payload = candidate_sidecar.read_bytes()
            receipt_payload = candidate_receipt.read_bytes()
        except OSError as exc:
            raise release.PortableBuildError("controlled missing portable file") from exc
        digest = hashlib.sha256(payload).hexdigest()
        expected_sidecar = (
            f"{digest}  {release.PORTABLE_ARCHIVE_NAME}\n".encode("ascii")
        )
        if payload != PORTABLE_BYTES or sidecar_payload != expected_sidecar:
            raise release.PortableBuildError("controlled portable mutation")
        if receipt_payload != PORTABLE_RECEIPT:
            raise release.PortableBuildError("controlled portable receipt mutation")
        return SimpleNamespace(
            source_revision=REVISION,
            source_tree=TREE,
            sector_version=release.SECTOR_VERSION,
            unsigned_status=release.UNSIGNED_STATUS,
            folder_name=PORTABLE_FOLDER_NAME,
            archive_name=release.PORTABLE_ARCHIVE_NAME,
            archive_sha256=digest,
            folder_file_count=1,
            folder_total_bytes=len(b"unsigned executable bytes"),
            folder_inventory_sha256="c" * 64,
            output=output,
            folder=candidate_folder,
            archive=candidate_archive,
            sidecar=candidate_sidecar,
            receipt=candidate_receipt,
        )

    def safe_extract(
        candidate_archive: Path,
        output: Path,
        *,
        expected_sha256: str | None = None,
    ) -> Path:
        payload = candidate_archive.read_bytes()
        if payload != PORTABLE_BYTES:
            raise release.PortableBuildError("controlled extraction mutation")
        if expected_sha256 != hashlib.sha256(payload).hexdigest():
            raise release.PortableBuildError("controlled extraction digest mismatch")
        extracted = output / PORTABLE_FOLDER_NAME
        extracted.mkdir(parents=True)
        (extracted / "Sector.exe").write_bytes(b"unsigned executable bytes")
        return extracted

    monkeypatch.setattr(release, "build_source_release", build_source)
    monkeypatch.setattr(release, "verify_source_release", verify_source)
    monkeypatch.setattr(release, "verify_portable_distribution", verify_portable)
    monkeypatch.setattr(release, "safe_extract_portable_archive", safe_extract)
    return SimpleNamespace(
        root=root,
        qa=qa_path,
        portable=portable,
        portable_archive=archive,
        output=tmp_path / "release-assets",
    )


def _assemble(fixture: SimpleNamespace) -> release.V093ReleaseEvidence:
    return release.assemble_v093_release(
        fixture.root,
        REVISION,
        fixture.qa,
        fixture.portable,
        fixture.output,
    )


def test_assemble_and_fresh_download_verification_close_exact_seven_assets(
    release_fixture: SimpleNamespace,
):
    original_portable = release_fixture.portable_archive.read_bytes()
    assembled = _assemble(release_fixture)
    release_fixture.qa.unlink()
    verified = release.verify_v093_release(
        release_fixture.root,
        REVISION,
        release_fixture.output,
    )

    assert assembled == verified
    assert assembled.asset_count == 7
    assert assembled.sector_version == "0.93"
    assert assembled.source_revision == REVISION
    assert assembled.source_tree == TREE
    assert assembled.unsigned_status == release.UNSIGNED_STATUS
    assert {item.name for item in release_fixture.output.iterdir()} == set(
        release.RELEASE_ASSET_NAMES
    )
    assert release_fixture.portable_archive.read_bytes() == original_portable

    source_digest = hashlib.sha256(SOURCE_BYTES).hexdigest()
    assert (release_fixture.output / release.SOURCE_SIDECAR_NAME).read_bytes() == (
        f"{source_digest}  {release.SOURCE_ARCHIVE_NAME}\n".encode("ascii")
    )
    portable_digest = hashlib.sha256(PORTABLE_BYTES).hexdigest()
    assert (release_fixture.output / release.PORTABLE_SIDECAR_NAME).read_bytes() == (
        f"{portable_digest}  {release.PORTABLE_ARCHIVE_NAME}\n".encode("ascii")
    )

    sums = (release_fixture.output / release.CHECKSUMS_NAME).read_text(
        encoding="ascii"
    )
    expected_lines = []
    for name in sorted(set(release.RELEASE_ASSET_NAMES) - {release.CHECKSUMS_NAME}):
        digest = hashlib.sha256((release_fixture.output / name).read_bytes()).hexdigest()
        expected_lines.append(f"{digest}  {name}\n")
    assert sums == "".join(expected_lines)
    assert assembled.assets_sha256 == hashlib.sha256(sums.encode("ascii")).hexdigest()


def test_release_receipt_binds_source_portable_run_jobs_and_artifacts_without_leaks(
    release_fixture: SimpleNamespace,
):
    _assemble(release_fixture)
    raw = (release_fixture.output / release.RELEASE_RECEIPT_NAME).read_bytes()
    receipt = json.loads(raw.decode("ascii"))

    assert raw == _canonical_json(receipt)
    assert receipt["source"] == {
        "archive_bytes": len(SOURCE_BYTES),
        "archive_name": release.SOURCE_ARCHIVE_NAME,
        "archive_sha256": hashlib.sha256(SOURCE_BYTES).hexdigest(),
        "revision": REVISION,
        "tree": TREE,
    }
    assert receipt["portable"]["archive_sha256"] == hashlib.sha256(
        PORTABLE_BYTES
    ).hexdigest()
    assert receipt["unsigned_status"] == release.UNSIGNED_STATUS
    assert receipt["qa"] == _qa_value()
    lowered = raw.decode("ascii").casefold()
    for forbidden in ("created_at", "timestamp", "token", "secret", "password", "c:\\"):
        assert forbidden not in lowered


def test_assembly_is_create_only_and_failure_leaves_no_partial_release(
    release_fixture: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
):
    release_fixture.output.mkdir()
    with pytest.raises(release.V093ReleaseError, match="already exists"):
        _assemble(release_fixture)

    release_fixture.output.rmdir()

    def reject_source(*_arguments):
        raise release.SourceReleaseError("controlled source build failure")

    monkeypatch.setattr(release, "build_source_release", reject_source)
    with pytest.raises(release.V093ReleaseError, match="source release creation failed"):
        _assemble(release_fixture)
    assert not release_fixture.output.exists()
    assert not list(release_fixture.output.parent.glob(".release-assets.assemble-*"))


def test_atomic_publication_refuses_output_created_in_final_race(
    release_fixture: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
):
    publish_no_replace = release._publish_directory_no_replace

    def race(source: Path, destination: Path) -> None:
        destination.mkdir()
        publish_no_replace(source, destination)

    monkeypatch.setattr(release, "_publish_directory_no_replace", race)
    with pytest.raises(release.V093ReleaseError, match="already exists"):
        _assemble(release_fixture)
    assert release_fixture.output.is_dir()
    assert list(release_fixture.output.iterdir()) == []


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda value: value.update({"created_at": "2026-08-11T00:00:00Z"}), "schema"),
        (lambda value: value.update({"qa_evidence_schema": True}), "schema"),
        (lambda value: value.update({"repository": "C:/private/repository"}), "repository"),
        (lambda value: value.update({"head_repository": "attacker/Sector"}), "source repository"),
        (lambda value: value.update({"event": "workflow_dispatch"}), "workflow identity"),
        (lambda value: value.update({"head_branch": "release"}), "workflow identity"),
        (lambda value: value.update({"conclusion": "failure"}), "workflow identity"),
        (lambda value: value["jobs"].pop(), "job inventory"),
        (
            lambda value: value["jobs"][0].update({"conclusion": "skipped"}),
            "job is not",
        ),
        (
            lambda value: value["jobs"][1].update(
                {"id": value["jobs"][0]["id"]}
            ),
            "canonical, and unique",
        ),
        (lambda value: value["jobs"].reverse(), "job inventory"),
        (lambda value: value["artifacts"].pop(), "artifact inventory"),
        (
            lambda value: value.update({"run_attempt": value["run_attempt"] + 1}),
            "artifact name",
        ),
        (
            lambda value: value["artifacts"][0].update({"expired": True}),
            "expired",
        ),
        (
            lambda value: value["artifacts"][0].update(
                {"digest": "sha256:" + "A" * 64}
            ),
            "digest",
        ),
        (
            lambda value: value["artifacts"][0].update({"name": "/tmp/private"}),
            "artifact name",
        ),
        (lambda value: value["artifacts"].reverse(), "artifact inventory"),
    ],
)
def test_qa_evidence_fails_closed_on_non_authoritative_or_leaking_metadata(
    tmp_path: Path, mutation, message: str
):
    value = copy.deepcopy(_qa_value())
    mutation(value)
    path = _write_qa(tmp_path / "qa.json", value)
    with pytest.raises(release.V093ReleaseError, match=message):
        release.read_qa_evidence(path, REVISION)


def test_qa_evidence_rejects_duplicate_keys_and_noncanonical_json(tmp_path: Path):
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_bytes(b'{"run_id":1,"run_id":1}\n')
    with pytest.raises(release.V093ReleaseError, match="duplicate key"):
        release.read_qa_evidence(duplicate, REVISION)

    noncanonical = tmp_path / "noncanonical.json"
    noncanonical.write_text(json.dumps(_qa_value()), encoding="ascii")
    with pytest.raises(release.V093ReleaseError, match="canonical ASCII JSON"):
        release.read_qa_evidence(noncanonical, REVISION)


@pytest.mark.parametrize(
    "asset, payload, message",
    [
        (release.SOURCE_ARCHIVE_NAME, b"mutated source\n", "source release"),
        (release.PORTABLE_ARCHIVE_NAME, b"mutated portable\n", "sidecar"),
        (release.CHECKSUMS_NAME, b"0" * 64 + b"  fake\n", "closure"),
    ],
)
def test_verification_rejects_mutated_archives_and_checksum_closure(
    release_fixture: SimpleNamespace,
    asset: str,
    payload: bytes,
    message: str,
):
    _assemble(release_fixture)
    (release_fixture.output / asset).write_bytes(payload)
    with pytest.raises(release.V093ReleaseError, match=message):
        release.verify_v093_release(
            release_fixture.root,
            REVISION,
            release_fixture.output,
        )


def test_verification_rejects_unknown_receipt_keys_and_changed_qa_binding(
    release_fixture: SimpleNamespace,
):
    _assemble(release_fixture)
    receipt_path = release_fixture.output / release.RELEASE_RECEIPT_NAME
    receipt = json.loads(receipt_path.read_text(encoding="ascii"))
    receipt["token"] = "not-allowed"
    receipt_path.write_bytes(_canonical_json(receipt))
    with pytest.raises(release.V093ReleaseError, match="receipt schema differs"):
        release.verify_v093_release(
            release_fixture.root,
            REVISION,
            release_fixture.output,
        )

    receipt.pop("token")
    receipt_path.write_bytes(_canonical_json(receipt))
    qa = _qa_value()
    qa["jobs"][0]["id"] += 50_000
    _write_qa(release_fixture.qa, qa)
    with pytest.raises(release.V093ReleaseError, match="external QA evidence differs"):
        release.verify_v093_release(
            release_fixture.root,
            REVISION,
            release_fixture.output,
            qa_evidence_path=release_fixture.qa,
        )


def test_authenticated_checksum_digests_cannot_bless_a_late_archive_mutation(
    release_fixture: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
):
    _assemble(release_fixture)
    checksum_payload = release._checksum_payload
    mutated = b"late source archive replacement\n"

    def mutate_after_authentication(digests: dict[str, str]):
        source = release_fixture.output / release.SOURCE_ARCHIVE_NAME
        source.write_bytes(mutated)
        sums = release_fixture.output / release.CHECKSUMS_NAME
        lines = sums.read_text(encoding="ascii").splitlines()
        replacement = hashlib.sha256(mutated).hexdigest()
        sums.write_bytes(
            (
                "\n".join(
                    f"{replacement}  {release.SOURCE_ARCHIVE_NAME}"
                    if line.endswith(f"  {release.SOURCE_ARCHIVE_NAME}")
                    else line
                    for line in lines
                )
                + "\n"
            ).encode("ascii")
        )
        return checksum_payload(digests)

    monkeypatch.setattr(release, "_checksum_payload", mutate_after_authentication)
    with pytest.raises(release.V093ReleaseError, match="closure differs"):
        release.verify_v093_release(
            release_fixture.root,
            REVISION,
            release_fixture.output,
        )


def test_verification_rejects_missing_extra_and_non_file_publication_entries(
    release_fixture: SimpleNamespace,
):
    _assemble(release_fixture)
    (release_fixture.output / "unexpected.txt").write_text("extra\n", encoding="ascii")
    with pytest.raises(release.V093ReleaseError, match="extra assets"):
        release.verify_v093_release(
            release_fixture.root,
            REVISION,
            release_fixture.output,
        )
    (release_fixture.output / "unexpected.txt").unlink()
    (release_fixture.output / release.CHECKSUMS_NAME).unlink()
    with pytest.raises(release.V093ReleaseError, match="inventory differs"):
        release.verify_v093_release(
            release_fixture.root,
            REVISION,
            release_fixture.output,
        )


@pytest.mark.parametrize("revision", ["A" * 40, "a" * 39, "../" + "a" * 40])
def test_revision_identity_is_lowercase_exact_and_path_free(
    tmp_path: Path, revision: str
):
    qa_path = _write_qa(tmp_path / "qa.json")
    with pytest.raises(release.V093ReleaseError, match="lowercase 40-hex"):
        release.read_qa_evidence(qa_path, revision)
