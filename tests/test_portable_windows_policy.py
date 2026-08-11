"""Fail-closed policy for PR-08's isolated portable Windows job topology."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tools.verify_consolidated_publication_gate import (
    CHECKOUT_ACTION,
    DOWNLOAD_ACTION,
    PORTABLE_COMPARE_STEPS,
    PORTABLE_PRODUCER_A_STEPS,
    PORTABLE_PRODUCER_B_STEPS,
    PORTABLE_SMOKE_STEPS,
    PORTABLE_STEPS,
    SETUP_PYTHON_ACTION,
    UPLOAD_ACTION,
    ConsolidatedPublicationGateError,
    validate_workflow,
)

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "qa.yml"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _workflow_text(workflow: dict) -> str:
    return yaml.safe_dump(workflow, sort_keys=False)


def _step(job: dict, name: str) -> dict:
    return next(step for step in job["steps"] if step["name"] == name)


def test_live_portable_topology_is_remote_split_and_exact() -> None:
    workflow = _workflow()
    validate_workflow(WORKFLOW.read_text(encoding="utf-8"))
    assert set(workflow["jobs"]) == {
        "test",
        "windows-package",
        "portable-producer-a",
        "portable-producer-b",
        "portable-compare",
        "portable-smoke",
        "windows-portable",
    }

    jobs = workflow["jobs"]
    assert jobs["portable-producer-a"]["needs"] == "test"
    assert jobs["portable-producer-b"]["needs"] == "test"
    assert jobs["portable-compare"]["needs"] == [
        "portable-producer-a",
        "portable-producer-b",
    ]
    assert jobs["portable-smoke"]["needs"] == [
        "portable-producer-a",
        "portable-compare",
    ]
    assert jobs["windows-portable"]["needs"] == [
        "portable-producer-a",
        "portable-producer-b",
        "portable-compare",
        "portable-smoke",
    ]
    assert tuple(
        step["name"] for step in jobs["portable-producer-a"]["steps"]
    ) == PORTABLE_PRODUCER_A_STEPS
    assert tuple(
        step["name"] for step in jobs["portable-producer-b"]["steps"]
    ) == PORTABLE_PRODUCER_B_STEPS
    assert tuple(
        step["name"] for step in jobs["portable-compare"]["steps"]
    ) == PORTABLE_COMPARE_STEPS
    assert tuple(
        step["name"] for step in jobs["portable-smoke"]["steps"]
    ) == PORTABLE_SMOKE_STEPS
    assert tuple(
        step["name"] for step in jobs["windows-portable"]["steps"]
    ) == PORTABLE_STEPS


@pytest.mark.parametrize("producer", ["a", "b"])
def test_each_producer_builds_independently_from_authenticated_gitless_source(
    producer: str,
) -> None:
    job = _workflow()["jobs"][f"portable-producer-{producer}"]
    upper = producer.upper()
    prepare = _step(
        job, f"Prepare authenticated Gitless source for producer {upper}"
    )["run"]
    for token in (
        "tools/build_source_release.py",
        "--source-revision $env:GITHUB_SHA",
        "Expand-Archive -LiteralPath $sourceArchive",
        'Join-Path $source ".git"',
        '"BUILD_SECTOR_PORTABLE.bat"',
        '"packaging/build_portable.ps1"',
        '"sector/sector_build_info.json"',
        f'"Sector portable source {upper} [Gitless] & exact-{{0}}-{{1}}"',
        f'"Sector portable output {upper} [QA] & exact-{{0}}-{{1}}"',
    ):
        assert token in prepare
    assert "git clone" not in prepare.casefold()
    assert "git checkout" not in prepare.casefold()

    build = _step(job, f"Build producer {upper} through root BAT")
    assert build["env"] == {
        "CI": "true",
        "SECTOR_PORTABLE_NONINTERACTIVE": "1",
        "SECTOR_SOURCE_REVISION": "${{ github.sha }}",
    }
    for token in (
        "SECTOR_PORTABLE_OUTPUT_ROOT",
        "SECTOR_PORTABLE_OUTPUT = [IO.Path]::GetFullPath",
        'Join-Path $env:pythonLocation "python.exe"',
        "Test-Path -LiteralPath $setupPython -PathType Leaf",
        "SECTOR_PORTABLE_PYTHON = $setupPython",
        '"BUILD_SECTOR_PORTABLE.bat"',
        "$env:ComSpec /d /s /c",
        "Push-Location -LiteralPath $env:SECTOR_PORTABLE_CALLER",
    ):
        assert token in build["run"]
    assert "tools/build_portable_windows.py" not in build["run"]
    assert "Sector.exe" not in build["run"]


@pytest.mark.parametrize("producer", ["a", "b"])
def test_each_producer_quotes_metacharacter_root_bat_path_via_cmd_call(
    producer: str,
) -> None:
    job = _workflow()["jobs"][f"portable-producer-{producer}"]
    upper = producer.upper()
    prepare = _step(
        job, f"Prepare authenticated Gitless source for producer {upper}"
    )["run"]
    build = _step(job, f"Build producer {upper} through root BAT")["run"]

    assert (
        f'"Portable wrapper caller {upper} [outside] & exact-{{0}}-{{1}}"'
        in prepare
    )
    assert "& $env:ComSpec /d /s /c ('call \"{0}\"' -f $wrapper)" in build
    assert "('\"\"{0}\"\"' -f $wrapper)" not in build


@pytest.mark.parametrize("producer", ["a", "b"])
def test_producer_upload_is_verified_create_only_and_immutable(producer: str) -> None:
    job = _workflow()["jobs"][f"portable-producer-{producer}"]
    upper = producer.upper()
    stage = _step(
        job, f"Verify and stage producer {upper} immutable distribution"
    )["run"]
    assert stage.count("tools/build_portable_windows.py") == 2
    assert stage.count("--verify-only") == 2
    assert "verified-pe-certificate-table-absent" in stage
    assert 'ProductName -cne "Sector"' in stage
    assert 'FileDescription -cne `' in stage
    assert '"Structural-analysis and design calculation tool"' in stage
    assert 'OriginalFilename -cne "Sector.exe"' in stage
    assert "FileVersion -cne $expectedVersion" in stage
    assert "ProductVersion -cne $expectedVersion" in stage
    assert "LegalCopyright -cne `" in stage
    assert '"Copyright (c) 2026 Kasper Lindskov Fabricius. All rights reserved."' in stage
    assert "CompanyName" in stage
    assert 'Join-Path $env:SECTOR_PRODUCER_ARTIFACT "distribution"' in stage
    assert "staged distribution already exists" in stage
    assert "Copy-Item -LiteralPath $entry.FullName" in stage

    upload = _step(job, f"Upload immutable producer {upper} distribution")
    assert upload["uses"] == UPLOAD_ACTION
    assert upload["with"] == {
        "name": (
            f"sector-portable-producer-{producer}-"
            "${{ github.run_id }}-${{ github.run_attempt }}"
        ),
        "path": f"qa-artifacts/portable-producer-{producer}/",
        "if-no-files-found": "error",
        "include-hidden-files": True,
        "retention-days": 7,
    }
    assert "overwrite" not in upload["with"]


def test_comparison_consumes_both_remote_immutable_artifacts() -> None:
    job = _workflow()["jobs"]["portable-compare"]
    downloads = [step for step in job["steps"] if step.get("uses") == DOWNLOAD_ACTION]
    assert [step["name"] for step in downloads] == [
        "Download immutable producer A",
        "Download immutable producer B",
    ]
    assert downloads[0]["with"]["name"].startswith("sector-portable-producer-a-")
    assert downloads[1]["with"]["name"].startswith("sector-portable-producer-b-")
    compare = _step(
        job, "Verify and compare downloaded portable distributions"
    )["run"]
    assert compare.count("--verify-only") == 2
    assert "--compare $distributionA $distributionB" in compare
    assert "--comparison-evidence $comparisonPath" in compare
    assert "qa-inputs/producer-a/distribution" in compare
    assert "qa-inputs/producer-b/distribution" in compare
    for forbidden in (
        "verify_portable_startup.py",
        "BUILD_SECTOR_PORTABLE.bat",
        "Start-Process",
        "Invoke-Item",
    ):
        assert forbidden not in compare


def test_smoke_has_minimal_permission_downloads_only_verified_a_and_never_publishes_it():
    job = _workflow()["jobs"]["portable-smoke"]
    assert job["permissions"] == {"contents": "read"}
    downloads = [step for step in job["steps"] if step.get("uses") == DOWNLOAD_ACTION]
    assert len(downloads) == 1
    assert downloads[0]["name"] == "Download verified producer A only"
    assert "producer-a" in downloads[0]["with"]["name"]
    assert "producer-b" not in yaml.safe_dump(job, sort_keys=False).casefold()

    smoke = _step(job, "Run controlled Job Object startup smoke")["run"]
    for token in (
        "tools/verify_portable_startup.py",
        "--root .",
        "--source-revision $env:GITHUB_SHA",
        "--distribution $distribution",
        "--timeout-seconds 120",
        "tools/build_portable_windows.py",
        '"127.0.0.1"',
        '"SECTOR_HEADLESS=1"',
        "listener_pid",
        "Smoke process mutated its downloaded distribution",
    ):
        assert token in smoke
    upload = _step(job, "Upload isolated smoke evidence")
    assert upload["with"]["path"] == "qa-artifacts/portable-smoke/"
    assert "distribution" not in upload["with"]["path"]


def test_final_gather_reverifies_downloads_and_never_executes_sector() -> None:
    job = _workflow()["jobs"]["windows-portable"]
    downloads = [step for step in job["steps"] if step.get("uses") == DOWNLOAD_ACTION]
    assert len(downloads) == 4
    assert [step["with"]["path"] for step in downloads] == [
        "qa-inputs/final-producer-a",
        "qa-inputs/final-producer-b",
        "qa-inputs/final-comparison",
        "qa-inputs/final-smoke",
    ]
    final = _step(
        job, "Re-verify immutable distributions for final publication"
    )["run"]
    assert final.count("--verify-only") == 3
    assert "--compare $distributionA $distributionB" in final
    assert "final-portable-comparison.json" in final
    assert "startup-smoke.json" in final
    assert "listener_pid" in final
    assert '$published = Join-Path $root "distribution"' in final
    assert '$evidence = Join-Path $root "evidence"' in final
    assert 'if ($entry.Name -cne "distribution")' in final
    assert "Canonical portable distribution verification failed" in final
    job_text = yaml.safe_dump(job, sort_keys=False)
    for forbidden in (
        "verify_portable_startup.py",
        "Start-Process",
        "Invoke-Item",
        "BUILD_SECTOR_PORTABLE.bat",
    ):
        assert forbidden not in job_text

    upload = _step(job, "Upload unsigned portable Windows evidence")
    assert "if" not in upload
    assert upload == {
        "name": "Upload unsigned portable Windows evidence",
        "uses": UPLOAD_ACTION,
        "with": {
            "name": "Sector-Windows-portable-unsigned-QA",
            "path": "qa-artifacts/portable-windows/",
            "if-no-files-found": "error",
            "include-hidden-files": True,
            "retention-days": 7,
        },
    }


def test_edge_is_recorded_as_external_prerequisite_without_launch() -> None:
    job = _workflow()["jobs"]["portable-producer-a"]
    edge = _step(job, "Record Microsoft Edge prerequisite")["run"]
    for token in (
        '"ProgramFiles(x86)"',
        '"Microsoft/Edge/Application/msedge.exe"',
        "Get-Item -LiteralPath $candidates[0]",
        "browser_bundled = $false",
        'prerequisite = "Microsoft Edge"',
        'status = "present-on-windows-runner"',
        '"edge-prerequisite.json"',
    ):
        assert token in edge
    for forbidden in ("Start-Process", "Invoke-Item", "& $edge", "http://", "https://"):
        assert forbidden not in edge


def test_all_portable_actions_are_exact_pins_and_checkouts_drop_credentials():
    jobs = _workflow()["jobs"]
    for job_name in (
        "portable-producer-a",
        "portable-producer-b",
        "portable-compare",
        "portable-smoke",
        "windows-portable",
    ):
        for step in jobs[job_name]["steps"]:
            if "uses" in step:
                assert step["uses"] in {
                    CHECKOUT_ACTION,
                    DOWNLOAD_ACTION,
                    SETUP_PYTHON_ACTION,
                    UPLOAD_ACTION,
                }
        checkout = next(
            step for step in jobs[job_name]["steps"] if step.get("uses") == CHECKOUT_ACTION
        )
        assert checkout["with"]["persist-credentials"] is False


@pytest.mark.parametrize(
    ("job_name", "step_name", "field", "value"),
    [
        (
            "portable-producer-a",
            "Upload immutable producer A distribution",
            "uses",
            "actions/upload-artifact@v4",
        ),
        (
            "portable-producer-b",
            "Build producer B through root BAT",
            "run",
            "Write-Output skipped",
        ),
        (
            "portable-compare",
            "Download immutable producer A",
            "with",
            {"name": "mutable"},
        ),
        (
            "portable-smoke",
            "Run controlled Job Object startup smoke",
            "if",
            "false",
        ),
        (
            "windows-portable",
            "Re-verify immutable distributions for final publication",
            "run",
            "Write-Output trusted",
        ),
    ],
)
def test_portable_remote_boundaries_cannot_be_bypassed(
    job_name: str, step_name: str, field: str, value: object
) -> None:
    workflow = _workflow()
    _step(workflow["jobs"][job_name], step_name)[field] = value
    with pytest.raises(ConsolidatedPublicationGateError):
        validate_workflow(_workflow_text(workflow))


def test_portable_jobs_contain_no_signing_or_protected_release_authority() -> None:
    jobs = _workflow()["jobs"]
    portable = {
        name: jobs[name]
        for name in (
            "portable-producer-a",
            "portable-producer-b",
            "portable-compare",
            "portable-smoke",
            "windows-portable",
        )
    }
    text = yaml.safe_dump(portable, sort_keys=False).casefold()
    allowed = "verified-pe-certificate-table-absent"
    assert text.count(allowed) == 2
    text = text.replace(allowed, "")
    for forbidden in (
        "${{ secrets",
        "signtool",
        "authenticode",
        "certificate",
        ".pfx",
        "environment:",
        "release.yml",
        "installer",
        "msi",
        "msix",
    ):
        assert forbidden not in text
