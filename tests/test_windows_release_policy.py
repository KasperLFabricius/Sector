"""Adversarial policy checks for protected Windows release signing."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest
import yaml

from tools.verify_windows_release import (
    EXPECTED_SOURCE_IDENTITY,
    ReleaseVerificationError,
    _regular_tree,
    verify_package,
    verify_source,
)
from tools.export_commit_tree import snapshot_commit

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "release-windows.yml"
SCRIPT = ROOT / "packaging" / "sign_and_verify.ps1"
COMMIT = subprocess.run(
    ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
    capture_output=True,
    text=True,
    check=True,
).stdout.strip()


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


def test_preflight_is_isolated_and_runs_before_dependencies_or_build():
    steps = _job()["steps"]
    preflight = _step("Run isolated release preflight")
    build = _step("Build exact source-bound package")
    assert "python -I -S tools/verify_windows_release.py" in preflight["run"]
    assert steps.index(preflight) < steps.index(build)
    assert "tools/build_exact_commit.py" in build["run"]


def test_release_and_qa_use_exact_driver_and_authenticated_identity_evidence():
    release = WORKFLOW.read_text(encoding="utf-8")
    qa = (ROOT / ".github" / "workflows" / "qa.yml").read_text(encoding="utf-8")

    for workflow in (release, qa):
        assert "tools/build_exact_commit.py" in workflow
        assert "tools/verify_windows_release.py" in workflow
        assert "source-identity.json" in workflow
        assert "python -m PyInstaller" not in workflow
    assert "generate_third_party_notices.py --output" not in release
    assert "Copy-Item -LiteralPath LICENSE" not in release
    assert "dist/Sector" not in release


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
    assert "--package $env:SECTOR_PACKAGE_ROOT" in package_gate["run"]
    assert "--source-identity $env:SECTOR_SOURCE_IDENTITY" in package_gate["run"]
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
        "path": "${{ env.SECTOR_PACKAGE_ROOT }}/",
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


def _package(
    tmp_path: Path, *, revision: str = COMMIT, repository: Path = ROOT
) -> Path:
    snapshot = snapshot_commit(repository, revision)
    package = tmp_path / "Sector"
    for item in snapshot.files:
        prefix = item.path.split("/", 1)[0]
        if prefix not in {"app", "sector", "assets"}:
            continue
        target = package / "_internal" / Path(*PurePosixPath(item.path).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(item.payload)
    (package / "Sector.exe").write_bytes(b"not executed")
    raw_files = {item.path: item.payload for item in snapshot.files}
    (package / "LICENSE.txt").write_bytes(raw_files["LICENSE"])
    (package / "THIRD_PARTY_NOTICES.txt").write_text(
        "SECTOR THIRD-PARTY NOTICES\nnumpy\nstreamlit\n", encoding="utf-8"
    )
    evidence = {
        "source_revision": snapshot.evidence.source_revision,
        "source_tree": snapshot.evidence.source_tree,
        "source_committer_epoch": snapshot.evidence.source_committer_epoch,
        "source_committed_at_utc": snapshot.evidence.source_committed_at_utc,
        "source_file_count": snapshot.evidence.file_count,
        "source_total_bytes": snapshot.evidence.total_bytes,
        "source_inventory_sha256": snapshot.evidence.inventory_sha256,
    }
    (tmp_path / "source-identity.json").write_bytes(
        (json.dumps(evidence, indent=2, sort_keys=True) + "\n").encode("ascii")
    )
    manifest = {
        "product_name": EXPECTED_SOURCE_IDENTITY["__product_name__"],
        "description": EXPECTED_SOURCE_IDENTITY["__description__"],
        "sector_version": EXPECTED_SOURCE_IDENTITY["__version__"],
        "author": EXPECTED_SOURCE_IDENTITY["__author__"],
        "licensee": EXPECTED_SOURCE_IDENTITY["__licensee__"],
        "copyright": EXPECTED_SOURCE_IDENTITY["__copyright__"],
        "built_at_utc": evidence["source_committed_at_utc"],
        **evidence,
    }
    (package / "_internal" / "sector" / "sector_build_info.json").write_bytes(
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("ascii")
    )
    return package


def _minimal_release_repository(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "repository"
    repository.mkdir()
    commands = (
        ("init", "--quiet"),
        ("config", "user.email", "sector-release@example.invalid"),
        ("config", "user.name", "Sector release tests"),
        ("config", "core.autocrlf", "false"),
    )
    for arguments in commands:
        subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=True,
            capture_output=True,
        )
    files = {
        "LICENSE": (ROOT / "LICENSE").read_bytes(),
        "sector/__init__.py": (ROOT / "sector" / "__init__.py").read_bytes(),
        "packaging/windows_version_info.txt": (
            ROOT / "packaging" / "windows_version_info.txt"
        ).read_bytes(),
        "app/sector_app.py": b"accepted raw application\n",
        "assets/logo.txt": b"accepted raw asset\n",
    }
    for relative, payload in files.items():
        target = repository / Path(*PurePosixPath(relative).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    subprocess.run(
        ["git", "-C", str(repository), "add", "."],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "commit", "--quiet", "-m", "fixture"],
        check=True,
        capture_output=True,
    )
    revision = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return repository, revision


def test_package_gate_accepts_complete_source_bound_fixture(tmp_path):
    verify_package(
        ROOT, _package(tmp_path), COMMIT, tmp_path / "source-identity.json"
    )


def test_matching_worktree_and_package_mutation_cannot_reseal_raw_snapshot(tmp_path):
    repository, revision = _minimal_release_repository(tmp_path)
    package = _package(tmp_path, revision=revision, repository=repository)
    evidence = tmp_path / "source-identity.json"
    hostile = b"hostile matching mutable source\n"

    (repository / "app" / "sector_app.py").write_bytes(hostile)
    verify_package(repository, package, revision, evidence)

    (package / "_internal" / "app" / "sector_app.py").write_bytes(hostile)
    with pytest.raises(ReleaseVerificationError, match="differs from raw commit"):
        verify_package(repository, package, revision, evidence)


def test_coherent_evidence_and_manifest_reseal_is_rejected(tmp_path):
    package = _package(tmp_path)
    evidence_path = tmp_path / "source-identity.json"
    manifest_path = package / "_internal" / "sector" / "sector_build_info.json"
    evidence = json.loads(evidence_path.read_text(encoding="ascii"))
    manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    evidence["source_inventory_sha256"] = "d" * 64
    manifest["source_inventory_sha256"] = "d" * 64
    evidence_path.write_bytes(
        (json.dumps(evidence, indent=2, sort_keys=True) + "\n").encode("ascii")
    )
    manifest_path.write_bytes(
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("ascii")
    )

    with pytest.raises(ReleaseVerificationError, match="raw commit closure"):
        verify_package(ROOT, package, COMMIT, evidence_path)


@pytest.mark.parametrize("ancestor", ("package", "internal", "tree"))
def test_package_tree_rejects_reparse_root_and_ancestors(
    tmp_path, monkeypatch, ancestor
):
    package = tmp_path / "Sector"
    tree = package / "_internal" / "app"
    tree.mkdir(parents=True)
    (tree / "accepted.py").write_bytes(b"accepted\n")
    targets = {
        "package": package,
        "internal": package / "_internal",
        "tree": tree,
    }
    reparse_path = targets[ancestor]
    real_stat = os.stat

    def report_reparse(path, *, dir_fd=None, follow_symlinks=True):
        if not follow_symlinks and Path(path) == reparse_path:
            return SimpleNamespace(
                st_mode=stat.S_IFDIR,
                st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT,
            )
        return real_stat(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(os, "stat", report_reparse)

    with pytest.raises(ReleaseVerificationError, match="link or reparse point"):
        _regular_tree(tree, boundary=package)


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        ("delete_exe", "missing required files"),
        ("foreign_license", "differs from raw source commit"),
        ("unknown_manifest", "manifest does not match"),
        ("wrong_revision", "manifest does not match"),
        ("local_timestamp", "manifest does not match"),
        ("mutated_app", "differs from raw commit"),
    ),
)
def test_package_gate_rejects_incomplete_or_resealed_identity(tmp_path, mutation, match):
    package = _package(tmp_path)
    manifest_path = package / "_internal" / "sector" / "sector_build_info.json"
    if mutation == "delete_exe":
        (package / "Sector.exe").unlink()
    elif mutation == "foreign_license":
        (package / "LICENSE.txt").write_text("different", encoding="utf-8")
    elif mutation == "mutated_app":
        (package / "_internal" / "app" / "sector_app.py").write_text(
            "hostile matching mutable source\n", encoding="utf-8"
        )
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if mutation == "unknown_manifest":
            manifest["extra"] = "accepted?"
        elif mutation == "wrong_revision":
            manifest["source_revision"] = "b" * 40
        elif mutation == "local_timestamp":
            manifest["built_at_utc"] = "2026-08-06T06:00:00"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ReleaseVerificationError, match=match):
        verify_package(
            ROOT, package, COMMIT, tmp_path / "source-identity.json"
        )
