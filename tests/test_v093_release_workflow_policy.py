"""Adversarial policy contract for the automatic v0.93 draft release."""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from tools.verify_consolidated_publication_gate import (
    CHECKOUT_ACTION,
    RELEASE_STEPS,
    SETUP_PYTHON_ACTION,
    ConsolidatedPublicationGateError,
    validate_release_workflow,
    validate_workflow,
)

ROOT = Path(__file__).resolve().parents[1]
QA_WORKFLOW = ROOT / ".github" / "workflows" / "qa.yml"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release-v093.yml"

QA_JOB_NAMES = {
    "Compare immutable portable producers",
    "Full test and report gate",
    "Isolated verified portable startup smoke",
    "Unsigned portable Windows distribution",
    "Unsigned portable producer A",
    "Unsigned portable producer B",
    "Unsigned QA Windows package",
}

RELEASE_ASSETS = {
    "SHA256SUMS.txt",
    "Sector-v0.93-release-qa-receipt.json",
    "Sector-v0.93-source.zip",
    "Sector-v0.93-source.zip.sha256",
    "Sector-v0.93-windows-portable-unsigned.portable-distribution.json",
    "Sector-v0.93-windows-portable-unsigned.zip",
    "Sector-v0.93-windows-portable-unsigned.zip.sha256",
}


def _workflow(path: Path = RELEASE_WORKFLOW) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _workflow_text(workflow: dict) -> str:
    return yaml.safe_dump(workflow, sort_keys=False)


def _step(job: dict, name: str) -> dict:
    return next(step for step in job["steps"] if step["name"] == name)


def _portable_extractor_script() -> str:
    run = _step(
        _workflow()["jobs"]["release"],
        "Download and safely extract only the qualified portable artifact",
    )["run"]
    marker = "python - <<'PY'\n"
    assert run.count(marker) == 1
    embedded = run.split(marker, 1)[1]
    script, separator, _remainder = embedded.partition("\nPY\n")
    assert separator
    return script + "\n"


def _override_extractor_limit(script: str, name: str, value: int) -> str:
    lines = script.splitlines()
    matches = [
        index for index, line in enumerate(lines) if line.startswith(f"{name} = ")
    ]
    assert len(matches) == 1
    lines[matches[0]] = f"{name} = {value}"
    return "\n".join(lines) + "\n"


def _run_portable_extractor(
    tmp_path: Path,
    entries: tuple[tuple[str, bytes], ...],
    *,
    limits: dict[str, int] | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    archive = tmp_path / "artifact.zip"
    destination = tmp_path / "extracted"
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, payload in entries:
            bundle.writestr(name, payload)
    script = _portable_extractor_script()
    for name, value in (limits or {}).items():
        script = _override_extractor_limit(script, name, value)
    environment = os.environ.copy()
    environment.update(
        {
            "SECTOR_PORTABLE_ARTIFACT_ARCHIVE": str(archive),
            "SECTOR_PORTABLE_ARTIFACT_EXTRACT": str(destination),
        }
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    return completed, destination


def test_live_release_workflow_is_exact_and_consolidated() -> None:
    release_text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    qa_text = QA_WORKFLOW.read_text(encoding="utf-8")
    validate_release_workflow(release_text)
    validate_workflow(qa_text)

    workflow = _workflow()
    assert workflow["name"] == "Sector v0.93 release"
    assert workflow[True] == {
        "workflow_run": {"workflows": ["Sector QA"], "types": ["completed"]}
    }
    assert workflow["permissions"] == {}
    assert workflow["concurrency"] == {
        "group": "sector-v093-release",
        "cancel-in-progress": False,
    }
    assert set(workflow["jobs"]) == {"release"}
    job = workflow["jobs"]["release"]
    assert job["permissions"] == {"actions": "read", "contents": "write"}
    assert tuple(step["name"] for step in job["steps"]) == RELEASE_STEPS
    assert "conclusion == 'success'" in job["if"]
    assert "event == 'push'" in job["if"]
    assert "head_branch == 'main'" in job["if"]
    assert "head_repository.full_name == github.repository" in job["if"]


def test_checkout_and_pre_mutation_boundaries_are_exact() -> None:
    job = _workflow()["jobs"]["release"]
    checkout = _step(job, "Check out authenticated QA source")
    assert checkout == {
        "name": "Check out authenticated QA source",
        "uses": CHECKOUT_ACTION,
        "with": {
            "ref": "${{ github.event.workflow_run.head_sha }}",
            "fetch-depth": 0,
            "persist-credentials": False,
        },
    }
    assert _step(job, "Set up pinned Python") == {
        "name": "Set up pinned Python",
        "uses": SETUP_PYTHON_ACTION,
        "with": {"python-version-file": ".python-version"},
    }

    first = _step(
        job, "Authenticate completed QA authority before checkout"
    )["run"]
    before_code = _step(
        job, "Establish exact current-main boundary before repository code"
    )["run"]
    recheck = _step(
        job, "Recheck QA authority and current main immediately before mutation"
    )["run"]
    for script in (first, recheck):
        assert "/attempts/$SECTOR_QA_RUN_ATTEMPT/jobs?per_page=100" in script
        assert "/artifacts?per_page=100" in script
        assert "SECTOR_QA_CONCLUSION" in script
        assert "SECTOR_HEAD_REPOSITORY" in script
    for script in (before_code, recheck):
        assert "fetch --force --no-tags origin" in script
        assert "refs/remotes/origin/main" in script
        assert 'main_revision" != "$SECTOR_QA_SHA"' in script
    assert "git status --porcelain=v1 --untracked-files=all" in recheck

    names = [step["name"] for step in job["steps"]]
    assert names.index(
        "Recheck QA authority and current main immediately before mutation"
    ) + 1 == names.index("Create or resume exact annotated tag and draft release")


def test_qa_authority_is_exactly_seven_successful_jobs_and_artifacts() -> None:
    job = _workflow()["jobs"]["release"]
    authority = _step(
        job, "Authenticate completed QA authority before checkout"
    )["run"]
    for job_name in QA_JOB_NAMES:
        assert f'"{job_name}"' in authority
    assert 'jobs_payload.get("total_count") != 7' in authority
    assert 'record["conclusion"] != "success"' in authority
    assert 'job.get("run_attempt") != run_attempt' in authority
    assert 're.fullmatch(r"sha256:[0-9a-f]{64}"' in authority
    assert 'record["expired"] is not False' in authority
    assert 'workflow_run.get("id") != run_id' in authority
    assert (
        'json.dumps(evidence, ensure_ascii=True, indent=2, sort_keys=True) + "\\n"'
        in authority
    )

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
    assert {value["name"] for value in jobs.values()} == QA_JOB_NAMES
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


def test_release_assembly_is_unsigned_and_freshly_reverified() -> None:
    job = _workflow()["jobs"]["release"]
    download = _step(
        job, "Download and safely extract only the qualified portable artifact"
    )["run"]
    assemble = _step(job, "Assemble and verify exact v0.93 release assets")[
        "run"
    ]
    publish = _step(
        job, "Create or resume exact annotated tag and draft release"
    )["run"]
    fresh = _step(job, "Freshly download and reverify all seven draft assets")[
        "run"
    ]

    assert "/actions/artifacts/$SECTOR_FINAL_ARTIFACT_ID/zip" in download
    assert "sha256sum" in download
    assert "PurePosixPath" in download
    assert "member escapes extraction root" in download
    assert "non-regular member" in download
    assert "MAX_ARCHIVE_BYTES = 2 * 1024 ** 3" in download
    assert "MAX_MEMBER_COUNT = 20_000" in download
    assert "MAX_MEMBER_BYTES = 1024 ** 3" in download
    assert "MAX_EXPANDED_BYTES = 4 * 1024 ** 3" in download
    assert "portable artifact streaming output exceeds its limits" in download
    assert "shutil.copyfileobj" not in download
    assert download.index("if len(members) > MAX_MEMBER_COUNT") < download.index(
        "destination.mkdir(parents=False)"
    )
    assert download.index("declared_expanded_bytes > MAX_EXPANDED_BYTES") < download.index(
        "destination.mkdir(parents=False)"
    )
    assert download.index(
        'raise ValueError("portable artifact streaming output exceeds its limits")'
    ) < download.index("output.write(chunk)")
    assert "--portable-distribution \"$SECTOR_PORTABLE_DISTRIBUTION\"" in assemble
    assert assemble.count("tools/verify_v093_release.py") == 2
    assert "git/tags" in publish
    assert '"type": "commit"' in publish
    assert '"draft": True' in publish
    assert 'release.get("draft") is not True' in publish
    assert "existing release asset" in publish
    assert "bytes differ" in publish
    assert "--method" in publish and '"POST"' in publish
    for asset_name in RELEASE_ASSETS:
        assert asset_name in publish
        assert asset_name in fresh
    assert "cmp --silent" in fresh
    assert fresh.count("tools/verify_v093_release.py verify") == 1
    assert "--qa-evidence" not in fresh

    collapsed = RELEASE_WORKFLOW.read_text(encoding="utf-8").casefold()
    for forbidden in (
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
    assert "--method\n                      \"delete\"" not in collapsed
    assert "--method\n                      \"patch\"" not in collapsed


def test_outer_portable_artifact_extractor_is_valid_python() -> None:
    compile(_portable_extractor_script(), "release-v093-portable-extractor", "exec")


def test_outer_portable_artifact_extractor_accepts_a_bounded_distribution(
    tmp_path: Path,
) -> None:
    completed, destination = _run_portable_extractor(
        tmp_path,
        (("distribution/Sector/readme.txt", b"bounded portable payload"),),
    )

    assert completed.returncode == 0, completed.stderr
    assert (destination / "distribution" / "Sector" / "readme.txt").read_bytes() == (
        b"bounded portable payload"
    )


@pytest.mark.parametrize(
    ("limits", "entries", "expected_error"),
    [
        (
            {"MAX_ARCHIVE_BYTES": 32},
            (("distribution/file.txt", b"payload"),),
            "archive exceeds its byte limit",
        ),
        (
            {"MAX_MEMBER_COUNT": 1},
            (
                ("distribution/first.txt", b"a"),
                ("distribution/second.txt", b"b"),
            ),
            "member-count limit",
        ),
        (
            {"MAX_MEMBER_BYTES": 4},
            (("distribution/file.txt", b"12345"),),
            "member exceeds its expanded-size limit",
        ),
        (
            {"MAX_EXPANDED_BYTES": 5},
            (
                ("distribution/first.txt", b"123"),
                ("distribution/second.txt", b"456"),
            ),
            "cumulative expanded-size limit",
        ),
    ],
)
def test_outer_portable_artifact_extractor_rejects_resource_limit_breaches(
    tmp_path: Path,
    limits: dict[str, int],
    entries: tuple[tuple[str, bytes], ...],
    expected_error: str,
) -> None:
    completed, destination = _run_portable_extractor(
        tmp_path,
        entries,
        limits=limits,
    )

    assert completed.returncode != 0
    assert expected_error in completed.stderr
    assert not destination.exists()


@pytest.mark.parametrize(
    ("entries", "expected_error"),
    [
        (
            (("distribution/../escape.txt", b"escape"),),
            "member escapes extraction root",
        ),
        (
            (("distribution//file.txt", b"alias"),),
            "non-canonical member path",
        ),
        (
            (
                ("distribution/File.txt", b"first"),
                ("distribution/file.txt", b"second"),
            ),
            "duplicate member paths",
        ),
        (
            (
                ("distribution/\N{LATIN SMALL LETTER E WITH ACUTE}.txt", b"first"),
                ("distribution/e\N{COMBINING ACUTE ACCENT}.txt", b"second"),
            ),
            "duplicate member paths",
        ),
        (
            (
                ("distribution/node", b"file"),
                ("distribution/node/child.txt", b"nested"),
            ),
            "nests content below a file",
        ),
        (
            (("distribution/CON.txt", b"reserved"),),
            "Windows-unsafe member path",
        ),
    ],
)
def test_outer_portable_artifact_extractor_rejects_path_and_collision_risks(
    tmp_path: Path,
    entries: tuple[tuple[str, bytes], ...],
    expected_error: str,
) -> None:
    completed, destination = _run_portable_extractor(tmp_path, entries)

    assert completed.returncode != 0
    assert expected_error in completed.stderr
    assert not destination.exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "manual-trigger",
        "default-write",
        "fork-guard",
        "credential-persistence",
        "protected-environment",
        "skip-reverify",
        "extra-job",
    ],
)
def test_release_authority_cannot_be_weakened(mutation: str) -> None:
    workflow = _workflow()
    job = workflow["jobs"]["release"]
    if mutation == "manual-trigger":
        workflow[True]["workflow_dispatch"] = None
    elif mutation == "default-write":
        workflow["permissions"] = {"contents": "write"}
    elif mutation == "fork-guard":
        job["if"] = job["if"].replace(
            "github.event.workflow_run.head_repository.full_name == github.repository",
            "true",
        )
    elif mutation == "credential-persistence":
        _step(job, "Check out authenticated QA source")["with"][
            "persist-credentials"
        ] = True
    elif mutation == "protected-environment":
        job["environment"] = "sector-production-signing"
    elif mutation == "skip-reverify":
        job["steps"].remove(
            _step(job, "Freshly download and reverify all seven draft assets")
        )
    else:
        workflow["jobs"]["extra"] = deepcopy(job)

    with pytest.raises(ConsolidatedPublicationGateError):
        validate_release_workflow(_workflow_text(workflow))
