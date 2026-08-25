"""Policy checks for the intentionally small Windows packaging workflow."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "qa.yml"
UPLOAD_ACTION = "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"
MINIMUM_QA_RETENTION_DAYS = 7
MINIMUM_PORTABLE_RETENTION_DAYS = 14


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _step(job, name: str):
    return next(step for step in job["steps"] if step["name"] == name)


def test_workflow_has_only_engineering_qa_and_one_real_portable_build():
    workflow = _workflow()
    assert set(workflow["jobs"]) == {"test", "portable"}
    portable = workflow["jobs"]["portable"]
    assert portable["needs"] == "test"
    assert portable["name"] == "Build and run portable Sector"


def test_portable_job_runs_build_bat_once_and_executes_the_page_gate():
    portable = _workflow()["jobs"]["portable"]
    build = _step(portable, "Build once and execute the packaged first page")
    script = build["run"]
    assert script.count('"BUILD.bat"') == 1
    assert "SECTOR_PORTABLE_NONINTERACTIVE" in build["env"]
    assert "SECTOR_PORTABLE_PYTHON" in script
    assert "SECTOR_PORTABLE_OUTPUT" in script
    driver = (ROOT / "tools" / "build_portable_windows.py").read_text("utf-8")
    assert driver.count("_run_page_smoke(") == 2
    assert '"verify_portable_startup.py"' in driver


def test_portable_upload_is_only_the_zip_and_checksum():
    portable = _workflow()["jobs"]["portable"]
    upload = _step(portable, "Upload portable ZIP")
    assert upload["uses"].split()[0] == UPLOAD_ACTION
    assert upload["with"]["name"].startswith("Sector-v0.96.1-windows-portable-")
    paths = upload["with"]["path"].splitlines()
    assert paths == [
        "${{ env.SECTOR_PORTABLE_OUTPUT }}/*.zip",
        "${{ env.SECTOR_PORTABLE_OUTPUT }}/*.zip.sha256",
    ]
    assert upload["with"]["if-no-files-found"] == "error"
    assert upload["with"]["retention-days"] >= MINIMUM_PORTABLE_RETENTION_DAYS


def test_qa_evidence_is_always_uploaded_for_at_least_one_review_cycle():
    test_job = _workflow()["jobs"]["test"]
    upload = _step(test_job, "Upload QA diagnostics")
    assert upload["if"] == "always()"
    assert upload["uses"].split()[0] == UPLOAD_ACTION
    assert upload["with"]["path"] == "qa-artifacts/"
    assert upload["with"]["if-no-files-found"] == "error"
    assert upload["with"]["retention-days"] >= MINIMUM_QA_RETENTION_DAYS


def test_removed_certification_topology_cannot_return_unnoticed():
    text = WORKFLOW.read_text(encoding="utf-8").casefold()
    for removed in (
        "producer a",
        "producer b",
        "immutable producer",
        "reproducib",
        "receipt",
        "source-identity",
        "build_exact_commit",
        "verify_windows_release",
        "sign_and_verify",
        "certificate table",
        "release-windows",
    ):
        assert removed not in text


def test_actions_are_immutable_pins_and_no_write_permission_exists():
    workflow = _workflow()
    assert workflow["permissions"] == {"contents": "read"}
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            action = step.get("uses")
            if action:
                _name, sha = action.split("@", 1)
                assert len(sha.split()[0]) == 40
    assert "write" not in WORKFLOW.read_text(encoding="utf-8").casefold()


def test_retired_release_certification_files_are_absent():
    for relative in (
        ".github/workflows/release-windows.yml",
        "packaging/build.ps1",
        "packaging/build_qa.bat",
        "packaging/sign_and_verify.ps1",
        "tools/build_exact_commit.py",
        "tools/build_source_release.py",
        "tools/export_commit_tree.py",
        "tools/verify_consolidated_publication_gate.py",
        "tools/verify_reproducible_windows_builds.py",
        "tools/verify_v093_release.py",
        "tools/verify_windows_release.py",
    ):
        assert not (ROOT / relative).exists()
