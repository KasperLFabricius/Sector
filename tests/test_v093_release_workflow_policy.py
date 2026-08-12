"""Adversarial policy contract for the GET-only v0.93 draft recovery."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from tools.verify_consolidated_publication_gate import (
    RELEASE_STEPS,
    SETUP_PYTHON_ACTION,
    ConsolidatedPublicationGateError,
    validate_release_workflow,
    validate_workflow,
)

ROOT = Path(__file__).resolve().parents[1]
QA_WORKFLOW = ROOT / ".github" / "workflows" / "qa.yml"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release-v093.yml"

RELEASE_SOURCE = "d0f08295b528f42493f5e8dd4b438c17dc304ec4"
RELEASE_TREE = "9ac057f723ce8d6b0844541c3573e133fa1b5519"
TAG_OBJECT = "d3bebfaf16f10f83e3da9bc804103b5eabf04331"
RELEASE_ID = 368822456
RELEASE_BODY_SHA256 = "8bfe1d04e79d102d459d4333fa6feebb8d332d3e0e5332587526153d61b9dda6"
QA_RUN_ID = 31525047117
QA_RUN_ATTEMPT = 1

QA_JOBS = {
    "Compare immutable portable producers": 93904131230,
    "Full test and report gate": 93891180278,
    "Isolated verified portable startup smoke": 93905080229,
    "Unsigned QA Windows package": 93901841194,
    "Unsigned portable Windows distribution": 93905809165,
    "Unsigned portable producer A": 93901841185,
    "Unsigned portable producer B": 93901841206,
}
QA_ARTIFACTS = {
    "Sector-Windows-portable-unsigned-QA-31525047117-1": (
        9116409657,
        "074ff74d8f53b287713f1a869d0ef03967a74210aec73342504b0f45beac5ab2",
    ),
    "Sector-Windows-unsigned-QA-31525047117-1": (
        9116091097,
        "e8659cbbe8e4378185913c4cc70d88b6174ec50ea5c56a958b025967311d7cd1",
    ),
    "sector-portable-comparison-31525047117-1": (
        9116190109,
        "210e8eae2b367d166175329ed676ebe4431d38165856d2d88ed43cf210c1a3b2",
    ),
    "sector-portable-producer-a-31525047117-1": (
        9116078390,
        "c26860a0d34b312a5bd5527c8ff2f70e019e3fd2f01af23aa9290d33b1d51b74",
    ),
    "sector-portable-producer-b-31525047117-1": (
        9116050472,
        "1e78f1c5732dd62dfa00bbce1abdc5a4f1673f169d8a50a43f1e49472566b915",
    ),
    "sector-portable-smoke-31525047117-1": (
        9116272667,
        "1160816228b2123c834edec5db408b7ece9901e0b7bf573e234f96795a1d3669",
    ),
    "sector-qa-evidence-31525047117-1": (
        9115805332,
        "e7944c2f1faffd20f23db3993b98114db0776990f694f480e9bc16f3a68387d0",
    ),
}
RELEASE_ASSETS = {
    "SHA256SUMS.txt": (
        510578229,
        647,
        "e835f18c43baa3abead46999a78c9fc6906f320266d38012ac14d3e1f1521a20",
    ),
    "Sector-v0.93-release-qa-receipt.json": (
        510578240,
        3872,
        "e3fb413f2d7e60d631212d3992e98bc4825b07ffb196fdba07e9bc85ac3ee8f1",
    ),
    "Sector-v0.93-source.zip": (
        510578248,
        8000728,
        "df94ced02726350f9c31baa0d5e88d0c0de78bd54d63504527c736ccc4a21d1a",
    ),
    "Sector-v0.93-source.zip.sha256": (
        510578280,
        90,
        "33f9c24c3510999aebf8c668793e2ff73fdee88b093f2e307d03d6f447b5ef71",
    ),
    "Sector-v0.93-windows-portable-unsigned.portable-distribution.json": (
        510578283,
        988,
        "e30d71f873945b3da16d92e58bded3d6764231d660571ea7654880ead7a106d0",
    ),
    "Sector-v0.93-windows-portable-unsigned.zip": (
        510578287,
        431949189,
        "fe0fa0ba01d6203b83d6a0f00318a7b5c40301e46bc1fd63c86ca35105aa5bf8",
    ),
    "Sector-v0.93-windows-portable-unsigned.zip.sha256": (
        510578521,
        109,
        "197c6e4946347b240263b3fd50e8134fd9b1d60e961fe47e3ac5efbd04cf4ad3",
    ),
}


def _workflow(path: Path = RELEASE_WORKFLOW) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _workflow_text(workflow: dict) -> str:
    return yaml.safe_dump(workflow, sort_keys=False)


def _step(job: dict, name: str) -> dict:
    return next(step for step in job["steps"] if step["name"] == name)


def _embedded_script(step_name: str, variable: str) -> str:
    run = _step(_workflow()["jobs"]["recovery"], step_name)["run"]
    marker = f"cat > \"${variable}\" <<'PY'\n"
    assert run.count(marker) == 1
    embedded = run.split(marker, 1)[1]
    script, separator, _remainder = embedded.partition("\nPY\n")
    assert separator
    return script + "\n"


def _capture_payloads(dispatch_sha: str = "a" * 40) -> dict[str, object]:
    repository = "KasperLFabricius/Sector"
    api = f"https://api.github.com/repos/{repository}"
    current_run_id = 40000000001
    current_run_attempt = 1
    release_body = (ROOT / "docs" / "v093_release_notes.md").read_text(encoding="utf-8")
    release_record = {
        "id": RELEASE_ID,
        "node_id": "RE_kwDOTFQLds4V-8i4",
        "tag_name": "v0.93",
        "target_commitish": RELEASE_SOURCE,
        "name": "Sector v0.93",
        "draft": True,
        "immutable": False,
        "prerelease": False,
        "published_at": None,
        "body": release_body,
        "author": {"login": "github-actions[bot]", "id": 41898282},
        "created_at": "2026-08-11T19:51:41Z",
        "updated_at": "2026-08-11T20:00:11Z",
    }
    release_assets = [
        {
            "name": name,
            "id": asset_id,
            "size": size,
            "digest": f"sha256:{digest}",
            "state": "uploaded",
            "content_type": "application/octet-stream",
            "label": "",
            "uploader": {"login": "github-actions[bot]", "id": 41898282},
            "created_at": "2026-08-11T19:59:52Z",
            "updated_at": "2026-08-11T20:00:11Z",
        }
        for name, (asset_id, size, digest) in RELEASE_ASSETS.items()
    ]
    qa_artifact_sizes = {
        "Sector-Windows-portable-unsigned-QA-31525047117-1": 325890257,
        "Sector-Windows-unsigned-QA-31525047117-1": 341830075,
        "sector-portable-comparison-31525047117-1": 2067,
        "sector-portable-producer-a-31525047117-1": 325883006,
        "sector-portable-producer-b-31525047117-1": 325882728,
        "sector-portable-smoke-31525047117-1": 1526,
        "sector-qa-evidence-31525047117-1": 24263798,
    }
    original_jobs = [
        {
            "name": name,
            "id": job_id,
            "run_attempt": QA_RUN_ATTEMPT,
            "conclusion": "success",
        }
        for name, job_id in QA_JOBS.items()
    ]
    original_artifacts = [
        {
            "name": name,
            "id": artifact_id,
            "size_in_bytes": qa_artifact_sizes[name],
            "digest": f"sha256:{digest}",
            "expired": False,
            "workflow_run": {"id": QA_RUN_ID},
        }
        for name, (artifact_id, digest) in QA_ARTIFACTS.items()
    ]
    current_run = {
        "id": current_run_id,
        "run_attempt": current_run_attempt,
        "name": "Sector QA",
        "path": ".github/workflows/qa.yml",
        "event": "push",
        "head_branch": "main",
        "head_sha": dispatch_sha,
        "status": "completed",
        "conclusion": "success",
        "head_repository": {"full_name": repository},
        "repository": {"full_name": repository},
    }
    current_jobs = [
        {
            "name": name,
            "id": 95000000000 + index,
            "run_attempt": current_run_attempt,
            "conclusion": "success",
        }
        for index, name in enumerate(QA_JOBS, start=1)
    ]
    current_qualifier = f"{current_run_id}-{current_run_attempt}"
    current_names = (
        f"Sector-Windows-portable-unsigned-QA-{current_qualifier}",
        f"Sector-Windows-unsigned-QA-{current_qualifier}",
        f"sector-portable-comparison-{current_qualifier}",
        f"sector-portable-producer-a-{current_qualifier}",
        f"sector-portable-producer-b-{current_qualifier}",
        f"sector-portable-smoke-{current_qualifier}",
        f"sector-qa-evidence-{current_qualifier}",
    )
    current_artifacts = [
        {
            "name": name,
            "id": 96000000000 + index,
            "size_in_bytes": 1000 + index,
            "digest": f"sha256:{index:064x}",
            "expired": False,
            "workflow_run": {"id": current_run_id},
        }
        for index, name in enumerate(current_names, start=1)
    ]

    return {
        f"/repos/{repository}/git/ref/heads/main": {
            "ref": "refs/heads/main",
            "node_id": "MAIN_REF_NODE",
            "url": f"{api}/git/refs/heads/main",
            "object": {
                "sha": dispatch_sha,
                "type": "commit",
                "url": f"{api}/git/commits/{dispatch_sha}",
            },
        },
        f"/repos/{repository}/git/ref/tags/v0.93": {
            "ref": "refs/tags/v0.93",
            "node_id": "REF_kwDOTFQLdq9yZWZzL3RhZ3MvdjAuOTM",
            "url": f"{api}/git/refs/tags/v0.93",
            "object": {
                "sha": TAG_OBJECT,
                "type": "tag",
                "url": f"{api}/git/tags/{TAG_OBJECT}",
            },
        },
        f"/repos/{repository}/git/tags/{TAG_OBJECT}": {
            "node_id": (
                "TA_kwDOTFQLdtoAKGQzYmViZmFmMTZmMTBmODNlM2RhOWJjODA0MTAzYjVlYWJmMDQzMzE"
            ),
            "sha": TAG_OBJECT,
            "url": f"{api}/git/tags/{TAG_OBJECT}",
            "tagger": {
                "name": "github-actions[bot]",
                "email": "41898282+github-actions[bot]@users.noreply.github.com",
                "date": "2026-08-11T19:51:41Z",
            },
            "object": {
                "sha": RELEASE_SOURCE,
                "type": "commit",
                "url": f"{api}/git/commits/{RELEASE_SOURCE}",
            },
            "tag": "v0.93",
            "message": "Sector v0.93",
            "verification": {
                "verified": False,
                "reason": "unsigned",
                "signature": None,
                "payload": None,
                "verified_at": None,
            },
        },
        f"/repos/{repository}/git/commits/{RELEASE_SOURCE}": {
            "sha": RELEASE_SOURCE,
            "tree": {"sha": RELEASE_TREE},
        },
        f"/repos/{repository}/releases?per_page=100&page=1": [
            {"id": RELEASE_ID, "tag_name": "v0.93", "draft": True}
        ],
        f"/repos/{repository}/releases/{RELEASE_ID}": release_record,
        f"/repos/{repository}/releases/{RELEASE_ID}/assets?per_page=100": (
            release_assets
        ),
        f"/repos/{repository}/actions/runs/{QA_RUN_ID}": {
            "id": QA_RUN_ID,
            "run_attempt": QA_RUN_ATTEMPT,
            "name": "Sector QA",
            "path": ".github/workflows/qa.yml",
            "event": "push",
            "head_branch": "main",
            "head_sha": RELEASE_SOURCE,
            "status": "completed",
            "conclusion": "success",
            "head_repository": {"full_name": repository},
            "repository": {"full_name": repository},
        },
        (
            f"/repos/{repository}/actions/runs/{QA_RUN_ID}/attempts/"
            f"{QA_RUN_ATTEMPT}/jobs?per_page=100"
        ): {"total_count": 7, "jobs": original_jobs},
        f"/repos/{repository}/actions/runs/{QA_RUN_ID}/artifacts?per_page=100": {
            "total_count": 7,
            "artifacts": original_artifacts,
        },
        (
            f"/repos/{repository}/actions/workflows/qa.yml/runs?branch=main&"
            f"event=push&status=success&head_sha={dispatch_sha}&per_page=100"
        ): {"total_count": 1, "workflow_runs": [current_run]},
        (
            f"/repos/{repository}/actions/runs/{current_run_id}/attempts/"
            f"{current_run_attempt}/jobs?per_page=100"
        ): {"total_count": 7, "jobs": current_jobs},
        f"/repos/{repository}/actions/runs/{current_run_id}/artifacts?per_page=100": {
            "total_count": 7,
            "artifacts": current_artifacts,
        },
    }


def _run_capture(
    tmp_path: Path,
    payloads: dict[str, object],
    label: str,
    *,
    fail_first: bool = False,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    fake_gh = tmp_path / f"fake-gh-{label}.py"
    payload_path = tmp_path / f"payloads-{label}.json"
    snapshot = tmp_path / f"snapshot-{label}.json"
    qa_evidence = tmp_path / f"qa-evidence-{label}.json"
    assets_tsv = tmp_path / f"assets-{label}.tsv"
    fake_gh.write_text(
        """import json
import os
import sys

payloads = json.loads(open(os.environ["FAKE_GH_PAYLOADS"], encoding="utf-8").read())
if (
    len(sys.argv) != 3
    or sys.argv[1] != "api"
    or sys.argv[2] not in payloads
):
    raise SystemExit("unexpected fake gh request")
fail_state = os.environ.get("FAKE_GH_FAIL_FIRST_STATE")
if fail_state and not os.path.exists(fail_state):
    open(fail_state, "x", encoding="utf-8").close()
    raise SystemExit("synthetic first-request failure")
sys.stdout.write(json.dumps(payloads[sys.argv[2]], ensure_ascii=True))
""",
        encoding="utf-8",
        newline="\n",
    )
    payload_path.write_text(
        json.dumps(payloads, ensure_ascii=True), encoding="utf-8", newline="\n"
    )
    script = _embedded_script(
        "Authenticate exact recovery state and original QA authority", "capture"
    )
    exact_call = '["gh", "api", endpoint]'
    assert script.count(exact_call) == 1
    script = script.replace(
        exact_call,
        ('[os.environ["FAKE_PYTHON"], os.environ["FAKE_GH"], "api", endpoint]'),
    )
    environment = os.environ.copy()
    environment.update(
        {
            "SECTOR_DISPATCH_SHA": "a" * 40,
            "FAKE_PYTHON": sys.executable,
            "FAKE_GH": str(fake_gh),
            "FAKE_GH_PAYLOADS": str(payload_path),
        }
    )
    if fail_first:
        environment["FAKE_GH_FAIL_FIRST_STATE"] = str(
            tmp_path / f"fake-gh-first-failure-{label}.state"
        )
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            "--snapshot",
            str(snapshot),
            "--qa-evidence",
            str(qa_evidence),
            "--assets-tsv",
            str(assets_tsv),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    return completed, snapshot


def test_capture_retries_one_bounded_transient_api_failure(tmp_path: Path) -> None:
    completed, snapshot = _run_capture(
        tmp_path,
        _capture_payloads(),
        "bounded-retry",
        fail_first=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert snapshot.is_file()


def test_live_recovery_workflow_is_exact_get_only_and_consolidated() -> None:
    release_text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    qa_text = QA_WORKFLOW.read_text(encoding="utf-8")
    validate_release_workflow(release_text)
    validate_workflow(qa_text)

    workflow = _workflow()
    assert workflow["name"] == "Sector v0.93 draft recovery verification"
    assert workflow[True] == {"workflow_dispatch": {}}
    assert workflow["permissions"] == {}
    assert workflow["concurrency"] == {
        "group": "sector-v093-release",
        "cancel-in-progress": False,
    }
    assert set(workflow["jobs"]) == {"recovery"}
    job = workflow["jobs"]["recovery"]
    assert job["name"] == "Verify existing v0.93 draft release"
    assert "if" not in job
    assert job["runs-on"] == "ubuntu-latest"
    assert job["timeout-minutes"] == 30
    assert job["permissions"] == {"actions": "read", "contents": "write"}
    assert tuple(step["name"] for step in job["steps"]) == RELEASE_STEPS
    assert "environment" not in job


def test_checkout_setup_and_current_main_boundaries_are_exact() -> None:
    job = _workflow()["jobs"]["recovery"]
    checkout = _step(job, "Check out pinned v0.93 release source")
    assert set(checkout) == {"name", "shell", "env", "run"}
    assert checkout["shell"] == "bash"
    assert checkout["env"] == {"SECTOR_RELEASE_SOURCE": RELEASE_SOURCE}
    checkout_run = checkout["run"]
    assert "find . -mindepth 1 -maxdepth 1" in checkout_run
    assert "git init --quiet ." in checkout_run
    assert (
        "git remote add origin https://github.com/KasperLFabricius/Sector.git"
        in checkout_run
    )
    assert "GIT_TERMINAL_PROMPT=0 git -c credential.helper= fetch" in checkout_run
    assert '--no-tags --depth=1 origin "$SECTOR_RELEASE_SOURCE"' in checkout_run
    assert "git checkout --quiet --detach FETCH_HEAD" in checkout_run
    assert 'git rev-parse HEAD)" != "$SECTOR_RELEASE_SOURCE"' in checkout_run
    assert "github.token" not in checkout_run
    assert _step(job, "Set up pinned Python") == {
        "name": "Set up pinned Python",
        "uses": SETUP_PYTHON_ACTION,
        "with": {"python-version-file": ".python-version", "token": ""},
    }

    first = _step(job, "Authenticate exact recovery state and original QA authority")[
        "run"
    ]
    boundary = _step(job, "Verify pinned source and current-main boundary")["run"]
    final = _step(job, "Recheck exact recovery state and current main")["run"]
    assert '[[ "$SECTOR_REPOSITORY" != "KasperLFabricius/Sector" ]]' in first
    assert '[[ "$SECTOR_EVENT_NAME" != "workflow_dispatch" ]]' in first
    assert '[[ "$SECTOR_REF" != "refs/heads/main" ]]' in first
    assert "/git/ref/heads/main" in first
    assert "/git/ref/heads/main" in boundary
    assert 'main_revision" != "$SECTOR_DISPATCH_SHA"' in boundary
    for script in (boundary, final):
        assert "git rev-parse HEAD" in script
        assert "git rev-parse 'HEAD^{tree}'" in script
        assert "git status --porcelain=v1 --untracked-files=all" in script
    assert "docs/v093_release_notes.md" in boundary
    assert RELEASE_BODY_SHA256 in boundary
    assert "extraheader" in boundary
    assert "state-before.json" in first
    assert "state-after.json" in final
    assert "cmp --silent" in final


def test_recovery_pins_tag_draft_original_qa_and_all_assets() -> None:
    authority = _step(
        _workflow()["jobs"]["recovery"],
        "Authenticate exact recovery state and original QA authority",
    )["run"]
    for value in (
        RELEASE_SOURCE,
        RELEASE_TREE,
        TAG_OBJECT,
        str(RELEASE_ID),
        RELEASE_BODY_SHA256,
        str(QA_RUN_ID),
        f"QA_RUN_ATTEMPT = {QA_RUN_ATTEMPT}",
    ):
        assert value in authority
    assert '/releases/{RELEASE_ID}")' in authority
    assert "/releases/{RELEASE_ID}/assets?per_page=100" in authority
    assert "/releases?per_page=100&page={page}" in authority
    assert "/releases/tags/" not in authority
    assert "MAX_RELEASE_PAGES = 10" in authority
    assert "len(tag_release_matches) != 1" in authority
    assert 'tag_release_matches[0].get("id") != RELEASE_ID' in authority
    assert 'tag_release_matches[0].get("draft") is not True' in authority
    assert '"matching_release_ids": [RELEASE_ID]' in authority
    assert '"draft": True' in authority
    assert '"published_at": None' in authority
    assert '"reason": "unsigned"' in authority
    assert "body_sha256" in authority
    assert "len(release_assets) != 7" in authority
    assert 'qa_jobs.get("total_count") != 7' in authority
    assert 'qa_artifacts.get("total_count") != 7' in authority
    assert "MAX_API_BYTES = 16 * 1024 * 1024" in authority
    for job_name, job_id in QA_JOBS.items():
        assert f'"{job_name}": {job_id}' in authority
    for name, (artifact_id, digest) in QA_ARTIFACTS.items():
        assert f'"{name}"' in authority
        assert str(artifact_id) in authority
        assert f"sha256:{digest}" in authority
    for name, (asset_id, size, digest) in RELEASE_ASSETS.items():
        assert f'"{name}"' in authority
        assert str(asset_id) in authority
        assert str(size) in authority
        assert f"sha256:{digest}" in authority


def test_live_original_qa_evidence_is_reconstructed_for_tagged_verifier() -> None:
    job = _workflow()["jobs"]["recovery"]
    authority = _step(
        job, "Authenticate exact recovery state and original QA authority"
    )["run"]
    fresh = _step(job, "Freshly download and verify exact draft assets")["run"]

    assert f"QA_RUN_ID = {QA_RUN_ID}" in authority
    assert f"QA_RUN_ATTEMPT = {QA_RUN_ATTEMPT}" in authority
    assert "/attempts/" in authority and "/jobs?per_page=100" in authority
    assert "/artifacts?per_page=100" in authority
    assert '"qa_evidence_schema": 1' in authority
    assert '"workflow_name": "Sector QA"' in authority
    assert authority.count('"path": ".github/workflows/qa.yml"') >= 2
    assert '"head_sha": RELEASE_SOURCE' in authority
    assert "canonical_json(qa_evidence)" in authority
    assert '--qa-evidence "$SECTOR_QA_EVIDENCE"' in fresh
    assert '--source-revision "$SECTOR_RELEASE_SOURCE"' in fresh
    assert fresh.count("tools/verify_v093_release.py verify") == 1
    assert "/actions/workflows/qa.yml/runs?" in authority
    assert "head_sha={dispatch_sha}" in authority
    assert 'current_qa_runs.get("total_count") != 1' in authority
    assert '"head_sha": dispatch_sha' in authority
    assert 'current_qa_jobs.get("total_count") != 7' in authority
    assert 'current_qa_artifacts.get("total_count") != 7' in authority
    assert '"dispatch_qa_run": current_qa_run_record' in authority


def test_release_asset_downloads_are_by_pinned_id_and_byte_bounded() -> None:
    fresh = _step(
        _workflow()["jobs"]["recovery"],
        "Freshly download and verify exact draft assets",
    )["run"]
    assert "/releases/assets/$asset_id" in fresh
    assert "Accept: application/octet-stream" in fresh
    assert "expected_size - count + 1" in fresh
    assert "next_count > expected_size" in fresh
    assert "count != expected_size" in fresh
    assert "digest.hexdigest() != digest_match.group(1)" in fresh
    assert 'target.open("xb")' in fresh
    assert "target.unlink(missing_ok=True)" in fresh
    assert "asset_count" in fresh and '"$asset_count" -ne 7' in fresh
    assert "--qa-evidence" in fresh
    assert "actions/download-artifact" not in fresh


def test_terminal_success_receipt_is_written_only_after_state_comparison() -> None:
    final = _step(
        _workflow()["jobs"]["recovery"],
        "Recheck exact recovery state and current main",
    )["run"]
    assert final.index("cmp --silent") < final.index("$GITHUB_STEP_SUMMARY")
    for value in (
        "$SECTOR_DISPATCH_SHA",
        "$SECTOR_RELEASE_SOURCE",
        "$SECTOR_RELEASE_TREE",
        TAG_OBJECT,
        str(RELEASE_ID),
        f"{QA_RUN_ID}/{QA_RUN_ATTEMPT}",
        "Assets: 7 freshly downloaded by pinned ID and verified",
    ):
        assert value in final


def test_embedded_recovery_helpers_are_valid_python() -> None:
    compile(
        _embedded_script(
            "Authenticate exact recovery state and original QA authority",
            "capture",
        ),
        "capture-recovery-state",
        "exec",
    )
    compile(
        _embedded_script(
            "Freshly download and verify exact draft assets",
            "bounded_copy",
        ),
        "bounded-asset-copy",
        "exec",
    )


def test_capture_helper_accepts_exact_mocked_github_authority(
    tmp_path: Path,
) -> None:
    completed, snapshot = _run_capture(tmp_path, _capture_payloads(), "exact")
    assert completed.returncode == 0, completed.stderr
    value = json.loads(snapshot.read_text(encoding="utf-8"))
    assert value["dispatch_main_sha"] == "a" * 40
    assert value["release_source_sha"] == RELEASE_SOURCE
    assert value["release_tree_sha"] == RELEASE_TREE
    assert value["release_discovery"] == {
        "pages_scanned": 1,
        "matching_release_ids": [RELEASE_ID],
    }
    assert value["release"]["body_sha256"] == RELEASE_BODY_SHA256
    assert len(value["release_assets"]) == 7
    assert value["qa_run"]["id"] == QA_RUN_ID
    assert value["dispatch_qa_run"]["head_sha"] == "a" * 40
    assert len(value["dispatch_qa_jobs"]) == 7
    assert len(value["dispatch_qa_artifacts"]) == 7


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("duplicate-release", "v0.93 must identify exactly the pinned draft release"),
        ("wrong-asset", "draft release asset differs"),
        ("wrong-main", "Canonical main no longer equals the dispatch source"),
        ("wrong-current-qa", "dispatch-source QA run authority differs"),
    ],
)
def test_capture_helper_rejects_adversarial_github_authority(
    tmp_path: Path,
    mutation: str,
    expected_error: str,
) -> None:
    payloads = _capture_payloads()
    repository = "KasperLFabricius/Sector"
    if mutation == "duplicate-release":
        endpoint = f"/repos/{repository}/releases?per_page=100&page=1"
        assert isinstance(payloads[endpoint], list)
        payloads[endpoint].append(
            {"id": RELEASE_ID + 1, "tag_name": "v0.93", "draft": True}
        )
    elif mutation == "wrong-asset":
        endpoint = f"/repos/{repository}/releases/{RELEASE_ID}/assets?per_page=100"
        assert isinstance(payloads[endpoint], list)
        payloads[endpoint][0]["digest"] = f"sha256:{'0' * 64}"
    elif mutation == "wrong-main":
        endpoint = f"/repos/{repository}/git/ref/heads/main"
        assert isinstance(payloads[endpoint], dict)
        payloads[endpoint]["object"]["sha"] = "b" * 40
    else:
        endpoint = (
            f"/repos/{repository}/actions/workflows/qa.yml/runs?branch=main&"
            f"event=push&status=success&head_sha={'a' * 40}&per_page=100"
        )
        assert isinstance(payloads[endpoint], dict)
        payloads[endpoint]["workflow_runs"][0]["conclusion"] = "failure"

    completed, snapshot = _run_capture(tmp_path, payloads, mutation)
    assert completed.returncode != 0
    assert expected_error in completed.stderr
    assert not snapshot.exists()


def test_capture_snapshots_expose_pre_post_metadata_drift(tmp_path: Path) -> None:
    before_payloads = _capture_payloads()
    before, before_snapshot = _run_capture(tmp_path, before_payloads, "before")
    assert before.returncode == 0, before.stderr

    after_payloads = deepcopy(before_payloads)
    endpoint = (
        f"/repos/KasperLFabricius/Sector/releases/{RELEASE_ID}/assets?per_page=100"
    )
    assert isinstance(after_payloads[endpoint], list)
    after_payloads[endpoint][0]["updated_at"] = "2026-08-11T20:00:12Z"
    after, after_snapshot = _run_capture(tmp_path, after_payloads, "after")
    assert after.returncode == 0, after.stderr
    assert before_snapshot.read_bytes() != after_snapshot.read_bytes()


@pytest.mark.parametrize(
    ("payload", "size_delta", "digest", "expected_error"),
    [
        (b"bounded", 1, None, b"unexpected byte count"),
        (b"bounded", -1, None, b"exceeds its exact byte limit"),
        (b"bounded", 0, "0" * 64, b"unexpected SHA-256"),
    ],
)
def test_bounded_asset_copy_rejects_size_and_digest_mismatch(
    tmp_path: Path,
    payload: bytes,
    size_delta: int,
    digest: str | None,
    expected_error: bytes,
) -> None:
    script = _embedded_script(
        "Freshly download and verify exact draft assets", "bounded_copy"
    )
    target = tmp_path / "asset.bin"
    expected_digest = digest or hashlib.sha256(payload).hexdigest()
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(target),
            str(len(payload) + size_delta),
            f"sha256:{expected_digest}",
        ],
        input=payload,
        capture_output=True,
        check=False,
    )
    assert completed.returncode != 0
    assert expected_error in completed.stderr
    assert not target.exists()


def test_bounded_asset_copy_accepts_exact_bytes_and_digest(tmp_path: Path) -> None:
    script = _embedded_script(
        "Freshly download and verify exact draft assets", "bounded_copy"
    )
    payload = b"exact bounded release asset"
    target = tmp_path / "asset.bin"
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(target),
            str(len(payload)),
            f"sha256:{hashlib.sha256(payload).hexdigest()}",
        ],
        input=payload,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert target.read_bytes() == payload


def test_recovery_has_no_github_mutation_or_unsafe_runtime_launch() -> None:
    workflow = _workflow()
    job = workflow["jobs"]["recovery"]
    release_text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    collapsed = release_text.casefold()
    token_steps = {
        step["name"]
        for step in job["steps"]
        if (step.get("env") or {}).get("GH_TOKEN") == "${{ github.token }}"
    }
    assert token_steps == {
        "Authenticate exact recovery state and original QA authority",
        "Verify pinned source and current-main boundary",
        "Freshly download and verify exact draft assets",
        "Recheck exact recovery state and current main",
    }
    assert release_text.count("GH_TOKEN: ${{ github.token }}") == 4
    assert release_text.count("unset GH_TOKEN") == 4
    assert release_text.count("GH_TOKEN") == 8
    assert release_text.count('["gh", "api", endpoint]') == 1
    assert release_text.count('gh api "/repos/$SECTOR_REPOSITORY/') == 2
    assert "--method" not in release_text
    assert "for attempt in range(1, 4)" in release_text
    assert "timeout=30" in release_text
    assert "time.sleep(attempt)" in release_text
    assert "for api_attempt in 1 2 3" in release_text
    assert "timeout 30 gh api" in release_text
    assert 'sleep "$api_attempt"' in release_text
    assert "for asset_attempt in 1 2 3" in release_text
    assert 'rm -f -- "$asset_target"' in release_text
    assert 'sleep "$asset_attempt"' in release_text
    fresh = _step(job, "Freshly download and verify exact draft assets")["run"]
    assert fresh.index("unset GH_TOKEN") < fresh.index(
        "python -I -S tools/verify_v093_release.py"
    )
    for forbidden in (
        "actions: write",
        "--method post",
        "--method put",
        "--method patch",
        "--method delete",
        "--field",
        "--raw-field",
        "--input",
        "git push",
        "git tag",
        "git update-ref",
        "gh release",
        "gh api graphql",
        "curl ",
        "wget ",
        "invoke-webrequest",
        "uploads.github",
        "/releases/tags/",
        "create release",
        "upload release",
        "delete release",
        "publish release",
        "sector.exe",
        "sign_and_verify",
        "sector_signing",
        "environment:",
        "start-process",
        "invoke-item",
        "browser",
        "chrome",
        "electron",
        "kaleido",
        "actions/download-artifact",
        "actions/upload-artifact",
    ):
        assert forbidden not in collapsed


@pytest.mark.parametrize(
    ("needle", "replacement"),
    [
        (
            '["gh", "api", endpoint]',
            '["gh", "api", "--method", "GET", endpoint]',
        ),
        ('gh api "/repos/$SECTOR_REPOSITORY/', "gh api -f injected=value "),
        ('gh api "/repos/$SECTOR_REPOSITORY/', "curl -X GET "),
        ("unset GH_TOKEN", 'echo "$GH_TOKEN" >> "$GITHUB_OUTPUT"'),
        ("unset GH_TOKEN", "git push origin HEAD:main"),
    ],
)
def test_recovery_rejects_alternate_api_or_token_escape(
    needle: str, replacement: str
) -> None:
    release_text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    mutated = release_text.replace(needle, replacement, 1)
    assert mutated != release_text
    with pytest.raises(ConsolidatedPublicationGateError):
        validate_release_workflow(mutated)


def test_qa_authority_remains_exactly_seven_jobs_and_artifacts() -> None:
    qualifier = "${{ github.run_id }}-${{ github.run_attempt }}"
    expected_uploads = {
        f"Sector-Windows-portable-unsigned-QA-{qualifier}",
        f"Sector-Windows-unsigned-QA-{qualifier}",
        f"sector-portable-comparison-{qualifier}",
        f"sector-portable-producer-a-{qualifier}",
        f"sector-portable-producer-b-{qualifier}",
        f"sector-portable-smoke-{qualifier}",
        f"sector-qa-evidence-{qualifier}",
    }
    qa = _workflow(QA_WORKFLOW)
    jobs = qa["jobs"]
    assert {value["name"] for value in jobs.values()} == set(QA_JOBS)
    actual_uploads = {
        step["with"]["name"]
        for qa_job in jobs.values()
        for step in qa_job["steps"]
        if step.get("uses", "").startswith("actions/upload-artifact@")
    }
    assert actual_uploads == expected_uploads
    assert all(name.endswith(qualifier) for name in actual_uploads)


def test_full_suite_has_unique_previously_nonexistent_basetemp() -> None:
    qa = _workflow(QA_WORKFLOW)
    test_job = qa["jobs"]["test"]
    test_step = _step(test_job, "Run complete test suite with coverage")
    assert test_step["shell"] == "pwsh"
    run = test_step["run"]
    assert "Join-Path $env:RUNNER_TEMP" in run
    assert "$env:GITHUB_RUN_ID, $env:GITHUB_RUN_ATTEMPT" in run
    assert "if (Test-Path -LiteralPath $baseTemp)" in run
    assert "--basetemp $baseTemp" in run
    validator = _step(test_job, "Validate consolidated publication gate")["run"]
    assert validator.endswith(
        ".github/workflows/qa.yml .github/workflows/release-v093.yml"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "automatic-trigger",
        "default-write",
        "job-read",
        "job-skip-guard",
        "canonical-guard",
        "authenticated-checkout",
        "floating-checkout",
        "draft-id",
        "skip-external-qa",
        "extra-job",
    ],
)
def test_recovery_authority_cannot_be_weakened(mutation: str) -> None:
    workflow = _workflow()
    job = workflow["jobs"]["recovery"]
    if mutation == "automatic-trigger":
        workflow[True]["workflow_run"] = {
            "workflows": ["Sector QA"],
            "types": ["completed"],
        }
    elif mutation == "default-write":
        workflow["permissions"] = {"contents": "write"}
    elif mutation == "job-read":
        job["permissions"]["contents"] = "read"
    elif mutation == "job-skip-guard":
        job["if"] = (
            "github.repository == 'KasperLFabricius/Sector' && "
            "github.ref == 'refs/heads/main'"
        )
    elif mutation == "canonical-guard":
        authority = _step(
            job, "Authenticate exact recovery state and original QA authority"
        )
        authority["run"] = authority["run"].replace(
            '[[ "$SECTOR_REPOSITORY" != "KasperLFabricius/Sector" ]]',
            '[[ "$SECTOR_REPOSITORY" != "$SECTOR_REPOSITORY" ]]',
        )
    elif mutation == "authenticated-checkout":
        checkout = _step(job, "Check out pinned v0.93 release source")
        checkout["run"] = checkout["run"].replace(
            "https://github.com/KasperLFabricius/Sector.git",
            "https://x-access-token:${{ github.token }}@github.com/"
            "KasperLFabricius/Sector.git",
        )
    elif mutation == "floating-checkout":
        _step(job, "Check out pinned v0.93 release source")["env"][
            "SECTOR_RELEASE_SOURCE"
        ] = "main"
    elif mutation == "draft-id":
        authority = _step(
            job, "Authenticate exact recovery state and original QA authority"
        )
        authority["run"] = authority["run"].replace(
            f"RELEASE_ID = {RELEASE_ID}", f"RELEASE_ID = {RELEASE_ID + 1}"
        )
    elif mutation == "skip-external-qa":
        fresh = _step(job, "Freshly download and verify exact draft assets")
        original = fresh["run"]
        fresh["run"] = original.replace(
            '  --qa-evidence "$SECTOR_QA_EVIDENCE" \\\n', ""
        )
        assert fresh["run"] != original
    else:
        workflow["jobs"]["extra"] = deepcopy(job)

    with pytest.raises(ConsolidatedPublicationGateError):
        validate_release_workflow(_workflow_text(workflow))
