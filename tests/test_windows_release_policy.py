"""Adversarial policy checks for protected Windows release signing."""

from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tools.export_commit_tree import export_commit, inspect_commit
from tools.verify_windows_release import (
    EXPECTED_SOURCE_IDENTITY,
    ReleaseVerificationError,
    verify_package,
    verify_source,
)

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "release-windows.yml"
SCRIPT = ROOT / "packaging" / "sign_and_verify.ps1"
COMMIT = subprocess.run(
    ["git", "--no-replace-objects", "-C", str(ROOT), "rev-parse", "HEAD"],
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()
SOURCE_EVIDENCE = inspect_commit(ROOT, COMMIT)


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
        "StringComparison]::Ordinal",
        "git config --local --name-only --get-regexp '^http\\..*\\.extraheader$'",
        "git config --local --unset-all $credentialKey",
        "Checkout credentials remain after the trust-boundary fetch",
    ):
        assert token in script
    assert script.index("git fetch") < script.index("git config --local --unset-all")
    assert all("run" not in step for step in steps[:1])
    assert "tools/" not in script and "packaging/" not in script


def test_dispatch_data_is_never_interpolated_into_executable_source():
    for step in _job()["steps"]:
        if "run" in step:
            assert "${{ inputs.source_sha }}" not in step["run"]
    workflow_text = WORKFLOW.read_text(encoding="utf-8")
    assert "ref: ${{ inputs.source_sha }}" not in workflow_text


def test_preflight_is_isolated_and_runs_before_exact_source_build():
    steps = _job()["steps"]
    preflight = _step("Run isolated release preflight")
    build = _step("Build source-bound package")
    assert "python -I -S tools/verify_windows_release.py" in preflight["run"]
    assert steps.index(preflight) < steps.index(build)
    assert "tools/build_exact_commit.py" in build["run"]
    assert "--source-revision" in build["run"]
    assert "--output" in build["run"]
    assert all(step["name"] != "Install locked build environment" for step in steps)


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
    assert "--package $env:SECTOR_RELEASE_PACKAGE_ROOT" in package_gate["run"]
    assert "--source-identity $env:SECTOR_RELEASE_SOURCE_IDENTITY" in package_gate["run"]
    assert "--repository-root ." in package_gate["run"]
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
        "path": "${{ env.SECTOR_RELEASE_PACKAGE_ROOT }}/",
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
        verify_source(ROOT, revision)


def _source_identity_payload(*, revision: str = COMMIT) -> dict[str, object]:
    return {
        "schema": "sector-source-identity-v1",
        "source_revision": revision,
        "source_tree": SOURCE_EVIDENCE.source_tree,
        "source_epoch": SOURCE_EVIDENCE.source_epoch,
        "built_at_utc": dt.datetime.fromtimestamp(
            SOURCE_EVIDENCE.source_epoch, dt.timezone.utc
        ).isoformat(timespec="seconds"),
        "source_file_count": SOURCE_EVIDENCE.file_count,
        "source_total_bytes": SOURCE_EVIDENCE.total_bytes,
        "source_inventory_sha256": SOURCE_EVIDENCE.inventory_sha256,
    }


def _source_identity(tmp_path: Path, *, revision: str = COMMIT) -> Path:
    path = tmp_path / "source-identity.json"
    path.write_text(
        json.dumps(_source_identity_payload(revision=revision)), encoding="utf-8"
    )
    return path


def _manifest_payload(*, revision: str = COMMIT) -> dict[str, object]:
    return {
        "product_name": EXPECTED_SOURCE_IDENTITY["__product_name__"],
        "description": EXPECTED_SOURCE_IDENTITY["__description__"],
        "sector_version": EXPECTED_SOURCE_IDENTITY["__version__"],
        "author": EXPECTED_SOURCE_IDENTITY["__author__"],
        "licensee": EXPECTED_SOURCE_IDENTITY["__licensee__"],
        "copyright": EXPECTED_SOURCE_IDENTITY["__copyright__"],
        **_source_identity_payload(revision=revision),
    }


def _source_root(tmp_path: Path, *, revision: str = COMMIT) -> Path:
    source = tmp_path / "exact-source"
    export_commit(ROOT, COMMIT, source)
    notice = source / "build" / "legal" / "THIRD_PARTY_NOTICES.txt"
    notice.parent.mkdir(parents=True)
    notice.write_text(
        "SECTOR THIRD-PARTY NOTICES\nnumpy\nstreamlit\n", encoding="utf-8"
    )
    (source / "build" / "sector_build_info.json").write_text(
        json.dumps(_manifest_payload(revision=revision)), encoding="utf-8"
    )
    return source


def _package(
    tmp_path: Path, source: Path, *, revision: str = COMMIT
) -> Path:
    package = tmp_path / "Sector"
    internal = package / "_internal"
    shutil.copytree(source / "app", internal / "app")
    shutil.copytree(source / "sector", internal / "sector")
    shutil.copytree(source / "assets", internal / "assets")
    (package / "Sector.exe").write_bytes(b"not executed")
    shutil.copyfile(source / "LICENSE", package / "LICENSE.txt")
    shutil.copyfile(
        source / "build" / "legal" / "THIRD_PARTY_NOTICES.txt",
        package / "THIRD_PARTY_NOTICES.txt",
    )
    (package / "_internal" / "sector" / "sector_build_info.json").write_text(
        json.dumps(_manifest_payload(revision=revision)), encoding="utf-8"
    )
    return package


def _release_fixture(tmp_path: Path):
    source = _source_root(tmp_path)
    package = _package(tmp_path, source)
    identity = _source_identity(tmp_path)
    return source, package, identity


def test_package_gate_accepts_complete_source_bound_fixture(tmp_path):
    source, package, identity = _release_fixture(tmp_path)
    verify_package(source, package, COMMIT, identity, ROOT)


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        ("delete_exe", "missing required files"),
        ("foreign_license", "differs from source"),
        ("unknown_manifest", "keys are incomplete or unknown"),
        ("wrong_revision", "manifest field: source_revision"),
        ("wrong_epoch", "manifest field: source_epoch"),
        ("local_timestamp", "manifest field: built_at_utc"),
        ("alter_app", "packaged source file differs"),
    ),
)
def test_package_gate_rejects_incomplete_or_resealed_identity(tmp_path, mutation, match):
    source, package, identity = _release_fixture(tmp_path)
    manifest_path = package / "_internal" / "sector" / "sector_build_info.json"
    if mutation == "delete_exe":
        (package / "Sector.exe").unlink()
    elif mutation == "alter_app":
        (package / "_internal" / "app" / "sector_app.py").write_text(
            "# post-build mutation\n", encoding="utf-8"
        )
    elif mutation == "foreign_license":
        (package / "LICENSE.txt").write_text("different", encoding="utf-8")
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if mutation == "unknown_manifest":
            manifest["extra"] = "accepted?"
        elif mutation == "wrong_revision":
            manifest["source_revision"] = "b" * 40
        elif mutation == "wrong_epoch":
            manifest["source_epoch"] += 1
        elif mutation == "local_timestamp":
            manifest["built_at_utc"] = "2026-08-06T06:00:00"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ReleaseVerificationError, match=match):
        verify_package(source, package, COMMIT, identity, ROOT)


def test_package_gate_rejects_missing_or_mismatched_source_identity(tmp_path):
    source = _source_root(tmp_path)
    package = _package(tmp_path, source)
    missing = tmp_path / "missing-source-identity.json"
    with pytest.raises(ReleaseVerificationError, match="cannot read source identity"):
        verify_package(source, package, COMMIT, missing, ROOT)

    identity = _source_identity(tmp_path, revision="d" * 40)
    with pytest.raises(ReleaseVerificationError, match="revision differs"):
        verify_package(source, package, COMMIT, identity, ROOT)


def test_package_gate_rejects_coherently_resealed_commit_evidence(tmp_path):
    source, package, identity_path = _release_fixture(tmp_path)
    manifest_path = package / "_internal" / "sector" / "sector_build_info.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    identity["source_tree"] = "d" * 40
    manifest["source_tree"] = "d" * 40
    identity_path.write_text(json.dumps(identity), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ReleaseVerificationError, match="authenticated commit closure"):
        verify_package(source, package, COMMIT, identity_path, ROOT)


def test_package_gate_rejects_post_export_source_mutation(tmp_path):
    source, package, identity = _release_fixture(tmp_path)
    (source / "app" / "sector_app.py").write_text(
        "# concurrent post-export mutation\n", encoding="utf-8"
    )

    with pytest.raises(ReleaseVerificationError, match="differs from selected commit"):
        verify_package(source, package, COMMIT, identity, ROOT)
