"""Policy checks for ordinary unsigned Windows QA build surfaces."""

from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "qa.yml"


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _step(job, name: str):
    return next(step for step in job["steps"] if step["name"] == name)


def test_windows_job_is_explicitly_unsigned_qa_only():
    workflow = _workflow()
    job = workflow["jobs"]["windows-package"]
    assert job["name"] == "Unsigned QA Windows package"
    assert job["needs"] == "test"
    assert "environment" not in job
    assert "permissions" not in job
    assert "continue-on-error" not in job

    build = _step(job, "Build unsigned QA package from exact exported source")
    assert build["env"] == {
        "SECTOR_SOURCE_REVISION": "${{ github.sha }}",
        "SECTOR_EXACT_BUILD_ROOT": (
            "qa-artifacts/windows-package-"
            "${{ github.run_id }}-${{ github.run_attempt }}"
        ),
    }
    script = build["run"]
    warning = "UNSIGNED QA PACKAGE ONLY. Do not launch or distribute this artifact."
    assert script.count(warning) == 1
    assert script.index(warning) < script.index("tools/build_exact_commit.py")
    assert "--source-revision $env:SECTOR_SOURCE_REVISION" in script
    assert "--output $env:SECTOR_EXACT_BUILD_ROOT" in script
    assert "python -m PyInstaller" not in script

    upload = _step(job, "Upload unsigned QA package")
    assert upload["with"]["name"] == "Sector-Windows-unsigned-QA"
    assert upload["with"]["path"] == "${{ env.SECTOR_PACKAGE_ROOT }}/"
    assert upload["with"]["retention-days"] == 7


def test_qa_verifies_complete_windows_and_manifest_identity_before_upload():
    job = _workflow()["jobs"]["windows-package"]
    verify = _step(job, "Verify unsigned QA package contents and identity")
    upload = _step(job, "Upload unsigned QA package")
    assert job["steps"].index(verify) < job["steps"].index(upload)
    script = verify["run"]

    for token in (
        'ProductName = "Sector"',
        'FileDescription = "Structural-analysis and design calculation tool"',
        'FileVersion = "0.91.0.0"',
        'ProductVersion = "0.91.0.0"',
        'OriginalFilename = "Sector.exe"',
        'LegalCopyright = "Copyright (c) 2026 Kasper Lindskov Fabricius. All rights reserved."',
        "versionInfo.CompanyName",
    ):
        assert script.count(token) == 1
    for token in (
        "tools/verify_windows_release.py",
        "--source-revision $env:GITHUB_SHA",
        "--source-identity $env:SECTOR_SOURCE_IDENTITY",
        "--package $packageRoot",
    ):
        assert script.count(token) == 1

    verifier = (ROOT / "tools" / "verify_windows_release.py").read_text(
        encoding="utf-8"
    )
    for token in (
        '"__product_name__": "Sector"',
        '"__description__": "Structural-analysis and design calculation tool"',
        '"__version__": "0.91"',
        '"__author__": "Kasper Lindskov Fabricius"',
        '"__licensee__": "Sweco Danmark A/S"',
        '"source_revision"',
        '"source_tree"',
        '"source_committer_epoch"',
        '"source_inventory_sha256"',
        "_require_raw_snapshot_tree",
    ):
        assert token in verifier


def test_ordinary_build_surfaces_forbid_unsigned_launch_and_distribution():
    surfaces = {
        "workflow": WORKFLOW.read_text(encoding="utf-8"),
        "PowerShell": (ROOT / "packaging" / "build.ps1").read_text(
            encoding="utf-8"
        ),
        "batch": (ROOT / "packaging" / "build.bat").read_text(encoding="utf-8"),
        "guide": (ROOT / "packaging" / "README.md").read_text(encoding="utf-8"),
    }
    for name, text in surfaces.items():
        folded = text.casefold()
        assert "unsigned" in folded, name
        assert "do not launch" in folded, name
        assert "distribut" in folded, name

    combined = "\n".join(surfaces.values()).casefold()
    for stale_prompt in (
        "zip that whole folder",
        "zip the whole dist/sector folder",
        "done. run dist/sector/sector.exe",
        "build complete. run dist\\sector\\sector.exe",
    ):
        assert stale_prompt not in combined


def test_ordinary_qa_surface_contains_no_signing_or_launch_authority():
    workflow = WORKFLOW.read_text(encoding="utf-8").casefold()
    for forbidden in (
        "${{ secrets.",
        "signtool",
        "authenticode",
        "certificate",
        ".pfx",
        "timestamp.digicert.com",
        "start-process",
        "invoke-item",
        "& dist/sector/sector.exe",
    ):
        assert forbidden not in workflow
