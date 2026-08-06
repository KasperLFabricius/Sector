"""Adversarial checks for Sector's protected genuine-signing release path."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from tools.verify_windows_release import (
    ReleasePolicyError,
    preflight,
    validate_build_lock,
    validate_signing_script,
    validate_workflow,
)

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "release-windows.yml"
SCRIPT = ROOT / "packaging" / "sign_and_verify.ps1"
BUILD_INPUT = ROOT / "requirements-build.in"
BUILD_LOCK = ROOT / "requirements-build.txt"
TOOL = ROOT / "tools" / "verify_windows_release.py"


def _texts():
    return (
        WORKFLOW.read_text(encoding="utf-8"),
        SCRIPT.read_text(encoding="utf-8"),
        BUILD_INPUT.read_text(encoding="utf-8"),
        BUILD_LOCK.read_text(encoding="utf-8"),
    )


def test_live_protected_release_policy_passes():
    workflow, script, build_input, build_lock = _texts()
    preflight(workflow, script, build_input, build_lock)
    validate_workflow(workflow)


def test_dependency_free_preflight_runs_under_isolated_python():
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(TOOL),
            "--preflight",
            "--workflow",
            str(WORKFLOW),
            "--signing-script",
            str(SCRIPT),
            "--build-input",
            str(BUILD_INPUT),
            "--build-lock",
            str(BUILD_LOCK),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "Windows release policy passed"


def test_preflight_has_no_nonstdlib_module_import():
    tree = ast.parse(TOOL.read_text(encoding="utf-8"), filename=str(TOOL))
    module_imports = {
        alias.name.split(".", 1)[0]
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    module_imports.update(
        node.module.split(".", 1)[0]
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module
    )
    assert module_imports == {"__future__", "argparse", "pathlib", "re"}


@pytest.mark.parametrize(
    "old,new",
    [
        ("  workflow_dispatch:\n", "  workflow_dispatch:\n  push:\n    branches: [main]\n"),
        ("name: sector-production-signing", "name: unprotected"),
        ("ref: ${{ inputs.source_sha }}", "ref: main"),
        ("git rev-parse origin/main", "git rev-parse HEAD^"),
        ("SECTOR_SIGNING_CERTIFICATE_SUBJECT", "UNPINNED_SIGNER_SUBJECT"),
        ("Upload verified signed release\n", "Upload verified signed release\n        if: always()\n"),
        ("path: dist/Sector/", "path: dist/"),
        (
            "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
            "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065-unpinned",
        ),
        (
            "SECTOR_SIGNING_CERTIFICATE_SUBJECT: ${{ secrets.SECTOR_SIGNING_CERTIFICATE_SUBJECT }}",
            "SECTOR_SIGNING_CERTIFICATE_SUBJECT: ${{ secrets.EXTRA_SIGNING_SECRET }}",
        ),
        (
            "$requested = $env:SECTOR_RELEASE_SOURCE_SHA",
            '$requested = "${{ inputs.source_sha }}"',
        ),
    ],
)
def test_workflow_adversarial_mutations_fail(old, new):
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert workflow.count(old) >= 1
    with pytest.raises(ReleasePolicyError):
        validate_workflow(workflow.replace(old, new, 1))


@pytest.mark.parametrize(
    "old,new",
    [
        ('Where-Object { $_.Directory.Name -ceq "x64" }', 'Where-Object { $_.FullName -match "x64" }'),
        ("sign /fd SHA256 /td SHA256", "sign /fd SHA1 /td SHA1"),
        ('/tr "https://timestamp.digicert.com"', "/t http://timestamp.invalid"),
        ('"1.3.6.1.5.5.7.3.3"', '"1.3.6.1.5.5.7.3.8"'),
        ("X509RevocationMode]::Online", "X509RevocationMode]::NoCheck"),
        (
            'Assert-CertificateChain $signature.TimeStamperCertificate "Timestamp"',
            'Write-Host "Timestamp chain skipped"',
        ),
        ("Remove-Item -LiteralPath $pfxPath -Force", 'Write-Host "PFX retained"'),
        ("finally {", "catch {"),
    ],
)
def test_signing_script_adversarial_mutations_fail(old, new):
    script = SCRIPT.read_text(encoding="utf-8")
    assert script.count(old) >= 1
    with pytest.raises(ReleasePolicyError):
        validate_signing_script(script.replace(old, new, 1))


def test_build_lock_must_retain_hashed_pyyaml():
    build_input = BUILD_INPUT.read_text(encoding="utf-8")
    lock = BUILD_LOCK.read_text(encoding="utf-8")
    validate_build_lock(build_input, lock)
    with pytest.raises(ReleasePolicyError):
        validate_build_lock(build_input, lock.replace("pyyaml==", "removed==", 1))


def test_release_surfaces_never_launch_an_executable():
    combined = "\n".join((WORKFLOW.read_text(encoding="utf-8"), SCRIPT.read_text(encoding="utf-8"))).casefold()
    for forbidden in (
        "start-process",
        "invoke-item",
        "& $executable",
        "sector.exe --",
        "dist/sector/sector.exe",
    ):
        assert forbidden not in combined
