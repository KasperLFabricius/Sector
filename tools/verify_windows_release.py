"""Validate Sector's protected Windows release policy without signing anything."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

CHECKOUT_ACTION = "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5"
SETUP_ACTION = "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065"
UPLOAD_ACTION = "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"
ENVIRONMENT = "sector-production-signing"
JOB = "signed-windows-release"


class ReleasePolicyError(ValueError):
    """Raised when the protected signing boundary is incomplete."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReleasePolicyError(message)


def _step(job: dict, name: str) -> dict:
    matches = [step for step in job.get("steps", []) if step.get("name") == name]
    _require(len(matches) == 1, f"release workflow requires one {name!r} step")
    return matches[0]


def validate_build_lock(input_text: str, lock_text: str) -> None:
    _require(
        len(re.findall(r"(?im)^pyyaml>=6\.0,<7\s*$", input_text)) == 1,
        "requirements-build.in must declare the bounded PyYAML dependency",
    )
    match = re.search(
        r"(?ms)^pyyaml==(?P<version>\d+\.\d+(?:\.\d+)?) \\\n"
        r"(?P<body>(?:    --hash=sha256:[0-9a-f]{64}(?: \\\n|\n))+)",
        lock_text,
    )
    _require(match is not None, "requirements-build.txt must hash-pin PyYAML")
    hashes = re.findall(r"--hash=sha256:[0-9a-f]{64}", match.group("body"))
    _require(len(hashes) >= 2, "PyYAML lock entry requires complete wheel hashes")


def validate_signing_script(script: str) -> None:
    required = (
        'Where-Object { $_.Directory.Name -ceq "x64" }',
        "sign /fd SHA256 /td SHA256",
        '/tr "https://timestamp.digicert.com"',
        "verify /pa /all /v",
        "Get-AuthenticodeSignature",
        'Assert-ExactValue $signature.Status "Valid"',
        'Assert-ExactValue $signature.SignatureType "Authenticode"',
        "SECTOR_SIGNING_CERTIFICATE_BASE64",
        "SECTOR_SIGNING_CERTIFICATE_PASSWORD",
        "SECTOR_SIGNING_CERTIFICATE_THUMBPRINT",
        "SECTOR_SIGNING_CERTIFICATE_SUBJECT",
        '"1.3.6.1.5.5.7.3.3"',
        '"1.3.6.1.5.5.7.3.8"',
        "X509RevocationMode]::Online",
        "X509VerificationFlags]::NoFlag",
        "TimeStamperCertificate",
        'Assert-CertificateChain $signature.SignerCertificate "Code-signing"',
        'Assert-CertificateChain $signature.TimeStamperCertificate "Timestamp"',
        'ProductName = "Sector"',
        'FileDescription = "Structural-analysis and design calculation tool"',
        'FileVersion = "0.91.0.0"',
        'ProductVersion = "0.91.0.0"',
        'OriginalFilename = "Sector.exe"',
        'LegalCopyright = "Copyright (c) 2026 Kasper Lindskov Fabricius. All rights reserved."',
        "versionInfo.CompanyName",
        'product_name = "Sector"',
        'description = "Structural-analysis and design calculation tool"',
        'sector_version = "0.91"',
        'source_revision = $SourceRevision',
        'author = "Kasper Lindskov Fabricius"',
        'licensee = "Sweco Danmark A/S"',
        'copyright = "Copyright (c) 2026 Kasper Lindskov Fabricius. All rights reserved."',
        '"sector-signing-{0}.pfx" -f [Guid]::NewGuid()',
        "finally {",
        "Remove-Item -LiteralPath $pfxPath -Force",
    )
    for token in required:
        _require(script.count(token) >= 1, f"signing script is missing {token!r}")
    folded = script.casefold()
    for forbidden in (
        "start-process",
        "invoke-item",
        "& $executable",
        "catch {",
        " /fd sha1",
        " /td sha1",
    ):
        _require(forbidden not in folded, f"signing script contains {forbidden!r}")
    _require(
        re.search(r"-match[^\n]*x64", script, re.IGNORECASE) is None,
        "signtool architecture must use its concrete parent directory",
    )


def preflight(
    workflow_text: str,
    signing_script: str,
    build_input: str,
    build_lock: str,
) -> None:
    validate_build_lock(build_input, build_lock)
    validate_signing_script(signing_script)
    for token in (
        "workflow_dispatch:",
        "environment:",
        f"name: {ENVIRONMENT}",
        "Preflight release policy without dependencies",
        "python -I -S tools/verify_windows_release.py --preflight",
        "Sign and verify protected release",
        "Upload verified signed release",
    ):
        _require(token in workflow_text, f"release workflow is missing {token!r}")


def _load_workflow(workflow_text: str) -> dict:
    try:
        import yaml  # build-locked; deliberately lazy so --preflight is stdlib-only
    except ImportError as exc:
        raise ReleasePolicyError("PyYAML is required after build-lock installation") from exc
    document = yaml.load(workflow_text, Loader=yaml.BaseLoader)
    _require(isinstance(document, dict), "release workflow must be a mapping")
    return document


def validate_workflow(workflow_text: str) -> None:
    workflow = _load_workflow(workflow_text)
    _require(
        workflow.get("name") == "Sector protected signed Windows release",
        "release workflow name is not exact",
    )
    triggers = workflow.get("on")
    _require(
        isinstance(triggers, dict) and set(triggers) == {"workflow_dispatch"},
        "release workflow must be manual-only",
    )
    dispatch = triggers["workflow_dispatch"]
    source = dispatch.get("inputs", {}).get("source_sha", {})
    _require(source.get("required") == "true", "source_sha must be required")
    _require(source.get("type") == "string", "source_sha must be a string")
    _require(
        workflow.get("permissions") == {"contents": "read"},
        "release workflow permissions must be read-only",
    )

    jobs = workflow.get("jobs", {})
    _require(set(jobs) == {JOB}, "release workflow must contain one signing job")
    job = jobs[JOB]
    _require(job.get("runs-on") == "windows-latest", "signing job must run on Windows")
    _require(job.get("environment") == {"name": ENVIRONMENT}, "protected environment is missing")
    _require("permissions" not in job, "signing job cannot broaden permissions")
    _require("env" not in job, "signing secrets must remain step-scoped")
    _require("continue-on-error" not in job, "signing job cannot be non-propagating")

    steps = job.get("steps", [])
    names = [step.get("name") for step in steps]
    expected_names = [
        "Check out exact requested source",
        "Set up pinned Python",
        "Preflight release policy without dependencies",
        "Install locked build environment",
        "Validate protected release policy",
        "Require exact current main commit",
        "Build protected release payload",
        "Sign and verify protected release",
        "Upload verified signed release",
    ]
    _require(names == expected_names, "release steps or order changed")
    for step in steps:
        _require(
            "${{ inputs.source_sha }}" not in step.get("run", ""),
            "dispatch input must never be interpolated into executable script text",
        )

    checkout = _step(job, expected_names[0])
    _require(checkout.get("uses") == CHECKOUT_ACTION, "checkout action is not pinned")
    _require(
        checkout.get("with") == {"ref": "${{ inputs.source_sha }}", "fetch-depth": "0"},
        "checkout must use the exact requested commit with full history",
    )
    setup = _step(job, expected_names[1])
    _require(setup.get("uses") == SETUP_ACTION, "Python setup action is not pinned")
    _require(
        setup.get("with")
        == {
            "python-version-file": ".python-version",
            "cache": "pip",
            "cache-dependency-path": "requirements-build.txt",
        },
        "Python setup must use the pinned runtime and build-lock cache",
    )

    preflight_step = _step(job, expected_names[2])
    _require(
        "python -I -S tools/verify_windows_release.py --preflight" in preflight_step.get("run", ""),
        "dependency-free preflight command is missing",
    )
    install = _step(job, expected_names[3])
    _require(
        install.get("run") == "python -m pip install --require-hashes -r requirements-build.txt",
        "release installation must use the hashed build lock",
    )
    main_step = _step(job, expected_names[5])
    _require(
        main_step.get("env") == {"SECTOR_RELEASE_SOURCE_SHA": "${{ inputs.source_sha }}"},
        "exact-main gate must receive source_sha only through the environment",
    )
    main_gate = main_step.get("run", "")
    _require(
        "$requested = $env:SECTOR_RELEASE_SOURCE_SHA" in main_gate,
        "exact-main gate must parse only the environment value",
    )
    for token in ("^[0-9a-f]{40}$", "git rev-parse HEAD", "git rev-parse origin/main"):
        _require(token in main_gate, f"exact-main gate is missing {token!r}")

    build = _step(job, expected_names[6])
    _require(
        build.get("env") == {"SECTOR_SOURCE_REVISION": "${{ inputs.source_sha }}"},
        "build provenance must use the requested source SHA",
    )
    build_script = build.get("run", "")
    for token in (
        "generate_third_party_notices.py",
        "python -m PyInstaller --noconfirm --clean packaging/sector.spec",
        "dist/Sector/LICENSE.txt",
        "dist/Sector/THIRD_PARTY_NOTICES.txt",
    ):
        _require(token in build_script, f"release build is missing {token!r}")
    signing = _step(job, expected_names[7])
    expected_signing_env = {
        "SECTOR_RELEASE_SOURCE_SHA": "${{ inputs.source_sha }}",
        "SECTOR_SIGNING_CERTIFICATE_BASE64": "${{ secrets.SECTOR_SIGNING_CERTIFICATE_BASE64 }}",
        "SECTOR_SIGNING_CERTIFICATE_PASSWORD": "${{ secrets.SECTOR_SIGNING_CERTIFICATE_PASSWORD }}",
        "SECTOR_SIGNING_CERTIFICATE_THUMBPRINT": "${{ secrets.SECTOR_SIGNING_CERTIFICATE_THUMBPRINT }}",
        "SECTOR_SIGNING_CERTIFICATE_SUBJECT": "${{ secrets.SECTOR_SIGNING_CERTIFICATE_SUBJECT }}",
    }
    _require(
        signing.get("env") == expected_signing_env,
        "signing source identity or secrets are incomplete or broadened",
    )
    secret_expressions = re.findall(r"\$\{\{\s*secrets\.[A-Z0-9_]+\s*\}\}", workflow_text)
    _require(
        sorted(secret_expressions)
        == sorted(value for value in expected_signing_env.values() if "secrets." in value),
        "release workflow may reference only the four protected signing secrets",
    )
    _require(
        "& packaging/sign_and_verify.ps1" in signing.get("run", ""),
        "protected signing script is not invoked",
    )
    _require(
        "-SourceRevision $env:SECTOR_RELEASE_SOURCE_SHA" in signing.get("run", ""),
        "signing script must receive source_sha only through the environment",
    )

    upload = _step(job, expected_names[8])
    _require(upload.get("uses") == UPLOAD_ACTION, "upload action is not pinned")
    _require("if" not in upload, "signed upload cannot bypass prior-step success")
    _require("continue-on-error" not in upload, "signed upload cannot be non-propagating")
    _require(
        upload.get("with")
        == {
            "name": "Sector-Windows-signed-${{ inputs.source_sha }}",
            "path": "dist/Sector/",
            "if-no-files-found": "error",
            "retention-days": "7",
        },
        "signed artifact upload is not exact and source-bound",
    )

    folded = workflow_text.casefold()
    for forbidden in (
        "pull_request:",
        "push:",
        "schedule:",
        "if: always()",
        "start-process",
        "invoke-item",
        "& dist/sector/sector.exe",
        "& .\\dist\\sector\\sector.exe",
    ):
        _require(forbidden not in folded, f"release workflow contains {forbidden!r}")


def validate_files(
    workflow: Path,
    signing_script: Path,
    build_input: Path,
    build_lock: Path,
    *,
    preflight_only: bool,
) -> None:
    workflow_text = workflow.read_text(encoding="utf-8")
    script_text = signing_script.read_text(encoding="utf-8")
    input_text = build_input.read_text(encoding="utf-8")
    lock_text = build_lock.read_text(encoding="utf-8")
    preflight(workflow_text, script_text, input_text, lock_text)
    if not preflight_only:
        validate_workflow(workflow_text)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--workflow", type=Path, required=True)
    parser.add_argument("--signing-script", type=Path, required=True)
    parser.add_argument("--build-input", type=Path, required=True)
    parser.add_argument("--build-lock", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        validate_files(
            args.workflow,
            args.signing_script,
            args.build_input,
            args.build_lock,
            preflight_only=args.preflight,
        )
    except (OSError, ReleasePolicyError) as exc:
        raise SystemExit(f"Windows release policy failed: {exc}") from None
    print("Windows release policy passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
