"""Adversarial policy checks for protected Windows release signing."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tools.verify_windows_release import (
    EXPECTED_SOURCE_IDENTITY,
    ReleaseVerificationError,
    verify_package,
    verify_source,
)

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "release-windows.yml"
SCRIPT = ROOT / "packaging" / "sign_and_verify.ps1"
COMMIT = "a" * 40
EPOCH = 1_785_996_000


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _job():
    return _workflow()["jobs"]["sign-windows"]


def _step(name: str):
    return next(step for step in _job()["steps"] if step["name"] == name)


def test_manual_main_only_protected_environment_is_the_only_trigger():
    workflow = _workflow()
    triggers = workflow.get("on", workflow.get(True))
    assert set(triggers) == {"workflow_dispatch"}
    assert triggers["workflow_dispatch"]["inputs"] == {
        "source_sha": {
            "description": "Exact lowercase 40-hex commit currently at main",
            "required": True,
            "type": "string",
        }
    }
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"] == {
        "group": "sector-production-signing",
        "cancel-in-progress": False,
    }
    job = _job()
    assert job["if"] == "github.ref == 'refs/heads/main'"
    assert job["environment"] == "sector-production-signing"
    assert job["runs-on"] == "windows-latest"
    assert "continue-on-error" not in job


def test_checkout_is_fixed_to_main_and_trust_gate_precedes_repository_code():
    steps = _job()["steps"]
    checkout = steps[0]
    gate = steps[1]
    assert checkout["name"] == "Check out current main"
    assert checkout["with"] == {
        "ref": "refs/heads/main",
        "fetch-depth": 1,
        "persist-credentials": True,
    }
    assert "inputs.source_sha" not in json.dumps(checkout)
    assert gate["name"] == "Establish exact current-main trust boundary"
    assert gate["env"] == {
        "SECTOR_RELEASE_SOURCE_SHA": "${{ inputs.source_sha }}"
    }
    script = gate["run"]
    for token in (
        "^[0-9a-f]{40}$",
        "git rev-parse HEAD",
        'refs/heads/main:refs/remotes/origin/main',
        "git rev-parse refs/remotes/origin/main",
        "git show -s --format=%ct $sourceRevision",
        "SOURCE_DATE_EPOCH=$sourceDateEpoch",
        "$env:GITHUB_ENV",
        "StringComparison]::Ordinal",
        "git config --local --name-only --get-regexp '^http\\..*\\.extraheader$'",
        "git config --local --unset-all $credentialKey",
        "Checkout credentials remain after the trust-boundary fetch",
    ):
        assert token in script
    assert script.index("git fetch") < script.index("git config --local --unset-all")
    assert script.index("git show -s") < script.index("git config --local --unset-all")
    assert all("run" not in step for step in steps[:1])
    assert "tools/" not in script and "packaging/" not in script


def test_dispatch_data_is_never_interpolated_into_executable_source():
    for step in _job()["steps"]:
        if "run" in step:
            assert "${{ inputs.source_sha }}" not in step["run"]
    workflow_text = WORKFLOW.read_text(encoding="utf-8")
    assert "ref: ${{ inputs.source_sha }}" not in workflow_text


def test_preflight_is_isolated_and_runs_before_dependencies_or_build():
    steps = _job()["steps"]
    preflight = _step("Run isolated release preflight")
    install = _step("Install locked build environment")
    build = _step("Build source-bound package")
    assert "python -I -S tools/verify_windows_release.py" in preflight["run"]
    assert "--source-date-epoch $env:SOURCE_DATE_EPOCH" in preflight["run"]
    assert steps.index(preflight) < steps.index(install) < steps.index(build)
    assert "--require-hashes -r requirements-build.txt" in install["run"]


def test_only_signing_step_receives_the_four_protected_secrets():
    steps = _job()["steps"]
    signing = _step("Sign and independently verify release package")
    expected = {
        "SECTOR_SIGNING_PFX_BASE64": "${{ secrets.SECTOR_SIGNING_PFX_BASE64 }}",
        "SECTOR_SIGNING_PFX_PASSWORD": "${{ secrets.SECTOR_SIGNING_PFX_PASSWORD }}",
        "SECTOR_SIGNING_THUMBPRINT": "${{ secrets.SECTOR_SIGNING_THUMBPRINT }}",
        "SECTOR_SIGNING_SUBJECT": "${{ secrets.SECTOR_SIGNING_SUBJECT }}",
    }
    assert {key: signing["env"][key] for key in expected} == expected
    for step in steps:
        if step["name"] == signing["name"]:
            continue
        assert "secrets." not in json.dumps(step)


def test_unsigned_package_is_verified_before_secret_exposure_and_upload():
    steps = _job()["steps"]
    package_gate = _step("Verify unsigned package before secret exposure")
    identity_gate = _step("Verify Windows identity before secret exposure")
    signing = _step("Sign and independently verify release package")
    upload = _step("Upload verified signed package")
    assert (
        steps.index(package_gate)
        < steps.index(identity_gate)
        < steps.index(signing)
        < steps.index(upload)
    )
    assert "--package dist/Sector" in package_gate["run"]
    assert "--package dist/repro-check/Sector" in package_gate["run"]
    assert "tools/verify_package_reproducibility.py" in package_gate["run"]
    assert "--first dist/Sector --second dist/repro-check/Sector" in package_gate["run"]
    build = _step("Build source-bound package")["run"]
    assert build.count("python -m PyInstaller") == 2
    assert "--workpath build/primary" in build
    assert "--workpath build/repro-check" in build
    for token in (
        "ProductName",
        "FileDescription",
        "FileVersion",
        "ProductVersion",
        "OriginalFilename",
        "LegalCopyright",
        "CompanyName",
        "StringComparison]::Ordinal",
    ):
        assert token in identity_gate["run"]
    assert upload["with"] == {
        "name": "Sector-Windows-signed-${{ inputs.source_sha }}",
        "path": "dist/Sector/",
        "if-no-files-found": "error",
        "retention-days": 30,
    }
    evidence_upload = _step("Upload controlled-build reproducibility evidence")
    assert evidence_upload["with"] == {
        "name": "Sector-Windows-reproducibility-${{ inputs.source_sha }}",
        "path": "build/reproducibility/package-reproducibility.json",
        "if-no-files-found": "error",
        "retention-days": 30,
    }


def test_signer_requires_sha256_rfc3161_and_two_independent_verifiers():
    text = SCRIPT.read_text(encoding="utf-8")
    for token in (
        "/fd SHA256",
        '/tr "http://timestamp.digicert.com"',
        "/td SHA256",
        "& $signTool verify /pa /all /v",
        "Get-AuthenticodeSignature",
        "X509RevocationMode]::Online",
        "X509RevocationFlag]::EntireChain",
        "X509VerificationFlags]::NoFlag",
        '"1.3.6.1.5.5.7.3.3"',
        '"1.3.6.1.5.5.7.3.8"',
        "TimeStamperCertificate",
    ):
        assert token in text


def test_signer_pins_certificate_and_concrete_x64_tool_identity():
    text = SCRIPT.read_text(encoding="utf-8")
    for token in (
        "ExpectedThumbprint",
        "ExpectedSubject",
        "StringComparison]::Ordinal",
        "X509Certificate2]::new",
        "X509KeyStorageFlags]::EphemeralKeySet",
        "HasPrivateKey",
        '"x64\\signtool.exe"',
        "Split-Path -Leaf (Split-Path -Parent $selected.Path)",
        '-cne "x64"',
    ):
        assert token in text


def test_signer_removes_only_its_unique_temporary_pfx_in_finally():
    text = SCRIPT.read_text(encoding="utf-8")
    assert '"Sector-sign-{0}.pfx" -f [guid]::NewGuid().ToString("N")' in text
    finally_block = text.split("finally {", 1)[1]
    assert "Remove-Item -LiteralPath $pfxPath -Force" in finally_block
    assert "Remove-Item -Recurse" not in text


def test_release_workflow_never_launches_the_executable():
    combined = (WORKFLOW.read_text(encoding="utf-8") + SCRIPT.read_text(encoding="utf-8")).casefold()
    for forbidden in (
        "start-process",
        "invoke-item",
        "& dist/sector/sector.exe",
        "& .\\dist\\sector\\sector.exe",
    ):
        assert forbidden not in combined


def test_stdlib_preflight_succeeds_without_site_packages():
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(ROOT / "tools" / "verify_windows_release.py"),
            "--root",
            str(ROOT),
            "--source-revision",
            COMMIT,
            "--source-date-epoch",
            str(EPOCH),
            "--preflight",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "revision",
    ("", "a" * 39, "A" * 40, "g" * 40, "refs/heads/main", "a" * 40 + "; echo bad"),
)
def test_source_preflight_rejects_non_exact_commit_identity(revision):
    with pytest.raises(ReleaseVerificationError, match="lowercase 40-hex"):
        verify_source(ROOT, revision, EPOCH)


@pytest.mark.parametrize("epoch", (True, "", "-1", "01", "1.5", "uncontrolled"))
def test_source_preflight_rejects_noncanonical_build_epoch(epoch):
    with pytest.raises(ReleaseVerificationError, match="non-negative integer"):
        verify_source(ROOT, COMMIT, epoch)


def _package(tmp_path: Path, *, revision: str = COMMIT) -> Path:
    package = tmp_path / "Sector"
    (package / "_internal" / "app").mkdir(parents=True)
    (package / "_internal" / "sector").mkdir(parents=True)
    (package / "Sector.exe").write_bytes(b"not executed")
    (package / "_internal" / "app" / "sector_app.py").write_text("# app\n", encoding="utf-8")
    (package / "_internal" / "sector" / "__init__.py").write_text("# core\n", encoding="utf-8")
    (package / "LICENSE.txt").write_text((ROOT / "LICENSE").read_text(encoding="utf-8"), encoding="utf-8")
    (package / "THIRD_PARTY_NOTICES.txt").write_text(
        "SECTOR THIRD-PARTY NOTICES\nnumpy\nstreamlit\n", encoding="utf-8"
    )
    manifest = {
        "product_name": EXPECTED_SOURCE_IDENTITY["__product_name__"],
        "description": EXPECTED_SOURCE_IDENTITY["__description__"],
        "sector_version": EXPECTED_SOURCE_IDENTITY["__version__"],
        "source_revision": revision,
        "source_date_epoch": EPOCH,
        "author": EXPECTED_SOURCE_IDENTITY["__author__"],
        "licensee": EXPECTED_SOURCE_IDENTITY["__licensee__"],
        "copyright": EXPECTED_SOURCE_IDENTITY["__copyright__"],
        "built_at_utc": "2026-08-06T06:00:00+00:00",
    }
    (package / "_internal" / "sector" / "sector_build_info.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return package


def test_package_gate_accepts_complete_source_bound_fixture(tmp_path):
    verify_package(ROOT, _package(tmp_path), COMMIT, EPOCH)


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        ("delete_exe", "missing required files"),
        ("foreign_license", "differs from source"),
        ("unknown_manifest", "keys are incomplete or unknown"),
        ("wrong_revision", "manifest field: source_revision"),
        ("wrong_epoch", "manifest field: source_date_epoch"),
        ("resealed_timestamp", "controlled source date epoch"),
    ),
)
def test_package_gate_rejects_incomplete_or_resealed_identity(tmp_path, mutation, match):
    package = _package(tmp_path)
    manifest_path = package / "_internal" / "sector" / "sector_build_info.json"
    if mutation == "delete_exe":
        (package / "Sector.exe").unlink()
    elif mutation == "foreign_license":
        (package / "LICENSE.txt").write_text("different", encoding="utf-8")
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if mutation == "unknown_manifest":
            manifest["extra"] = "accepted?"
        elif mutation == "wrong_revision":
            manifest["source_revision"] = "b" * 40
        elif mutation == "wrong_epoch":
            manifest["source_date_epoch"] = EPOCH + 1
        elif mutation == "resealed_timestamp":
            manifest["built_at_utc"] = "2026-08-06T06:00:01+00:00"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ReleaseVerificationError, match=match):
        verify_package(ROOT, package, COMMIT, EPOCH)
