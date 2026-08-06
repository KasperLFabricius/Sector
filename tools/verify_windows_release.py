"""Validate Sector's Windows identity and fail-closed signed-release gate."""

from __future__ import annotations

import argparse
import ast
import base64
import binascii
import datetime as dt
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE_IDENTITY = Path("sector/__init__.py")
LEGAL_NOTICE = Path("LICENSE")
VERSION_RESOURCE = Path("packaging/windows_version_info.txt")
PACKAGE_SPEC = Path("packaging/sector.spec")
RELEASE_WORKFLOW = Path(".github/workflows/release.yml")
PRODUCT_NAME = "Sector"
FILE_DESCRIPTION = "Sector structural-analysis and design calculation tool"
ORIGINAL_FILENAME = "Sector.exe"
LEGAL_COPYRIGHT = (
    "Copyright (c) 2026 Kasper Lindskov Fabricius. All rights reserved."
)
LICENCE_COMMENT = (
    "Licensed to Sweco Danmark A/S for internal organisational use."
)
AUTHOR = "Kasper Lindskov Fabricius"
LICENSEE = "Sweco Danmark A/S"
SIGNING_ENVIRONMENT = "sector-production-signing"
TIMESTAMP_URL = "https://timestamp.digicert.com"
CHECKOUT_STEP = "Check out exact source"
CHECKOUT_ACTION = "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5"
SETUP_STEP = "Set up pinned Python"
SETUP_ACTION = "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065"
PREFLIGHT_STEP = "Preflight genuine signing authority"
INSTALL_STEP = "Install locked build environment"
VALIDATE_STEP = "Validate signed-release policy"
NOTICE_STEP = "Generate exact legal notices"
BUILD_STEP = "Build provenance-bound Windows package"
ASSEMBLE_STEP = "Assemble legal package files"
SIGN_STEP = "Authenticode sign Sector executable"
VERIFY_STEP = "Verify signed package identity and provenance"
UPLOAD_STEP = "Upload verified signed Windows package"
UPLOAD_ACTION = "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"
SECRET_ENV = {
    "SECTOR_SIGNING_CERTIFICATE_PFX_BASE64": (
        "${{ secrets.SECTOR_SIGNING_CERTIFICATE_PFX_BASE64 }}"
    ),
    "SECTOR_SIGNING_CERTIFICATE_PASSWORD": (
        "${{ secrets.SECTOR_SIGNING_CERTIFICATE_PASSWORD }}"
    ),
    "SECTOR_EXPECTED_SIGNER_SUBJECT": "${{ secrets.SECTOR_EXPECTED_SIGNER_SUBJECT }}",
    "SECTOR_EXPECTED_SIGNER_THUMBPRINT": (
        "${{ secrets.SECTOR_EXPECTED_SIGNER_THUMBPRINT }}"
    ),
}
PREFLIGHT_ENV = {
    **SECRET_ENV,
    "SECTOR_RELEASE_REF": "${{ github.ref }}",
    "SECTOR_RELEASE_SHA": "${{ github.sha }}",
}
THUMBPRINT = re.compile(r"^[0-9A-F]{40}$")
SOURCE_REVISION = re.compile(r"^[0-9a-f]{40}$")

SIGN_SCRIPT = """$ErrorActionPreference = "Stop"
$certificatePath = Join-Path $env:RUNNER_TEMP "sector-signing.pfx"
try {
  $certificateBytes = [Convert]::FromBase64String(
    $env:SECTOR_SIGNING_CERTIFICATE_PFX_BASE64
  )
  [IO.File]::WriteAllBytes($certificatePath, $certificateBytes)
  $signTool = Get-ChildItem -LiteralPath "${env:ProgramFiles(x86)}\\Windows Kits\\10\\bin" `
    -Filter signtool.exe -Recurse |
    Where-Object { $_.Directory.Name -eq 'x64' } |
    Sort-Object FullName -Descending |
    Select-Object -First 1
  if ($null -eq $signTool) {
    throw "A Windows x64 signtool.exe was not found"
  }
  & $signTool.FullName sign /fd SHA256 /td SHA256 `
    /tr https://timestamp.digicert.com `
    /f $certificatePath `
    /p $env:SECTOR_SIGNING_CERTIFICATE_PASSWORD `
    dist/Sector/Sector.exe
  if ($LASTEXITCODE -ne 0) {
    throw "Authenticode signing failed with exit code $LASTEXITCODE"
  }
}
finally {
  if (Test-Path -LiteralPath $certificatePath) {
    Remove-Item -LiteralPath $certificatePath -Force
  }
}"""

POWERSHELL_INSPECTION = r"""
$ErrorActionPreference = "Stop"
$path = $env:SECTOR_RELEASE_EXE
$item = Get-Item -LiteralPath $path
$version = $item.VersionInfo
$signature = Get-AuthenticodeSignature -LiteralPath $path
$chainValid = $false
$chainStatus = @()
$hasCodeSigningEku = $false
if ($null -ne $signature.SignerCertificate) {
  $chain = [Security.Cryptography.X509Certificates.X509Chain]::new()
  $chainValid = $chain.Build($signature.SignerCertificate)
  $chainStatus = @($chain.ChainStatus | ForEach-Object { $_.Status.ToString() })
  foreach ($extension in $signature.SignerCertificate.Extensions) {
    if ($extension -is [Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension]) {
      foreach ($usage in $extension.EnhancedKeyUsages) {
        if ($usage.Value -eq "1.3.6.1.5.5.7.3.3") {
          $hasCodeSigningEku = $true
        }
      }
    }
  }
}
[ordered]@{
  product_name = $version.ProductName
  file_description = $version.FileDescription
  file_version = $version.FileVersion
  product_version = $version.ProductVersion
  internal_name = $version.InternalName
  original_filename = $version.OriginalFilename
  legal_copyright = $version.LegalCopyright
  comments = $version.Comments
  company_name = $version.CompanyName
  signature_status = $signature.Status.ToString()
  signature_status_message = $signature.StatusMessage
  signer_subject = if ($null -eq $signature.SignerCertificate) { $null } else { $signature.SignerCertificate.Subject }
  signer_thumbprint = if ($null -eq $signature.SignerCertificate) { $null } else { $signature.SignerCertificate.Thumbprint }
  signer_not_after_utc = if ($null -eq $signature.SignerCertificate) { $null } else { $signature.SignerCertificate.NotAfter.ToUniversalTime().ToString("o") }
  timestamp_subject = if ($null -eq $signature.TimeStamperCertificate) { $null } else { $signature.TimeStamperCertificate.Subject }
  timestamp_thumbprint = if ($null -eq $signature.TimeStamperCertificate) { $null } else { $signature.TimeStamperCertificate.Thumbprint }
  code_signing_eku = $hasCodeSigningEku
  chain_valid = $chainValid
  chain_status = $chainStatus
} | ConvertTo-Json -Compress -Depth 4
""".strip()


class WindowsReleaseError(ValueError):
    """Raised when product identity, signing, or release policy can be bypassed."""


@dataclass(frozen=True)
class SectorIdentity:
    """Exact product metadata retained by source, package, and Windows resources."""

    version: str
    author: str
    licensee: str
    version_tuple: tuple[int, int, int, int]

    @property
    def file_version(self) -> str:
        return ".".join(str(value) for value in self.version_tuple)


def _nonblank(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WindowsReleaseError(f"{label} must be non-empty text")
    return value.strip()


def _literal_assignments(path: Path) -> dict[str, str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeError) as exc:
        raise WindowsReleaseError(f"cannot parse Sector source identity: {exc}") from exc
    values: dict[str, str] = {}
    required = {"__version__", "__author__", "__licensee__"}
    counts = {name: 0 for name in required}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in required:
            continue
        counts[target.id] += 1
        if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
            raise WindowsReleaseError(f"{target.id} must be literal text")
        values[target.id] = node.value.value
    if any(count != 1 for count in counts.values()):
        raise WindowsReleaseError("Sector source identity must assign each field exactly once")
    return values


def _version_tuple(version: str) -> tuple[int, int, int, int]:
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", version) is None:
        raise WindowsReleaseError("Sector version cannot form a Windows version tuple")
    values = [int(value) for value in version.split(".")]
    if any(value > 65535 for value in values):
        raise WindowsReleaseError("Windows version components must not exceed 65535")
    return tuple(values + [0] * (4 - len(values)))  # type: ignore[return-value]


def read_identity(path: Path = ROOT / SOURCE_IDENTITY) -> SectorIdentity:
    values = _literal_assignments(path)
    version = _nonblank(values.get("__version__"), "__version__")
    author = _nonblank(values.get("__author__"), "__author__")
    licensee = _nonblank(values.get("__licensee__"), "__licensee__")
    if author != AUTHOR:
        raise WindowsReleaseError("Sector author/copyright-holder identity differs")
    if licensee != LICENSEE:
        raise WindowsReleaseError("Sector licensed-organisation identity differs")
    return SectorIdentity(version, author, licensee, _version_tuple(version))


def render_version_resource(identity: SectorIdentity) -> str:
    a, b, c, d = identity.version_tuple
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({a}, {b}, {c}, {d}),
    prodvers=({a}, {b}, {c}, {d}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('Comments', '{LICENCE_COMMENT}'),
          StringStruct('FileDescription', '{FILE_DESCRIPTION}'),
          StringStruct('FileVersion', '{identity.file_version}'),
          StringStruct('InternalName', '{PRODUCT_NAME}'),
          StringStruct('LegalCopyright', '{LEGAL_COPYRIGHT}'),
          StringStruct('OriginalFilename', '{ORIGINAL_FILENAME}'),
          StringStruct('ProductName', '{PRODUCT_NAME}'),
          StringStruct('ProductVersion', '{identity.version}')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def validate_product_files(root: Path = ROOT) -> SectorIdentity:
    identity = read_identity(root / SOURCE_IDENTITY)
    try:
        resource = (root / VERSION_RESOURCE).read_text(encoding="utf-8")
        legal = (root / LEGAL_NOTICE).read_text(encoding="ascii")
        spec = (root / PACKAGE_SPEC).read_text(encoding="utf-8")
    except OSError as exc:
        raise WindowsReleaseError(f"cannot read Windows release input: {exc}") from exc
    if resource.replace("\r\n", "\n") != render_version_resource(identity):
        raise WindowsReleaseError("Windows version resource differs from source identity")
    required_legal = (
        f"Copyright (c) 2026 {identity.author}. All rights reserved.",
        f"Author and copyright holder: {identity.author}",
        "Licensed organisation: Sweco Danmark A/S, CVR 48233511, Denmark",
        "distribute Sector internally for its own business and engineering activities",
        "No permission is granted for public or external distribution",
    )
    if any(value not in legal for value in required_legal):
        raise WindowsReleaseError("proprietary legal identity differs")
    required_spec = (
        'PRODUCT_NAME = "Sector"',
        f'FILE_DESCRIPTION = "{FILE_DESCRIPTION}"',
        'ROOT, "packaging", "windows_version_info.txt"',
        '"product_name": PRODUCT_NAME',
        '"file_description": FILE_DESCRIPTION',
        '"sector_version": identity["sector_version"]',
        '"source_revision": _source_revision(ROOT)',
        '"author": identity["author"]',
        '"licensee": identity["licensee"]',
        '"legal_copyright": LEGAL_COPYRIGHT',
        "version=WINDOWS_VERSION_RESOURCE",
    )
    if any(value not in spec for value in required_spec):
        raise WindowsReleaseError("package spec omits required identity/provenance wiring")
    if "CompanyName" in resource or "Publisher" in resource:
        raise WindowsReleaseError("Windows resource invents a company/publisher identity")
    return identity


def _signing_values(environment: Mapping[str, str]) -> tuple[str, str, str, str]:
    encoded = _nonblank(
        environment.get("SECTOR_SIGNING_CERTIFICATE_PFX_BASE64"),
        "signing certificate",
    )
    password = _nonblank(
        environment.get("SECTOR_SIGNING_CERTIFICATE_PASSWORD"),
        "signing certificate password",
    )
    subject = _nonblank(
        environment.get("SECTOR_EXPECTED_SIGNER_SUBJECT"),
        "expected signer subject",
    )
    thumbprint = re.sub(
        r"\s+",
        "",
        _nonblank(
            environment.get("SECTOR_EXPECTED_SIGNER_THUMBPRINT"),
            "expected signer thumbprint",
        ),
    ).upper()
    if THUMBPRINT.fullmatch(thumbprint) is None:
        raise WindowsReleaseError("expected signer thumbprint must be exactly 40 hex")
    try:
        certificate = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise WindowsReleaseError("signing certificate is not valid base64") from exc
    if len(certificate) < 512:
        raise WindowsReleaseError("signing certificate payload is implausibly small")
    return encoded, password, subject, thumbprint


def preflight_signing_environment(environment: Mapping[str, str] = os.environ) -> None:
    _signing_values(environment)
    reference = _nonblank(environment.get("SECTOR_RELEASE_REF"), "release ref")
    if reference != "refs/heads/main":
        raise WindowsReleaseError("signed releases are restricted to refs/heads/main")
    revision = _nonblank(environment.get("SECTOR_RELEASE_SHA"), "release SHA")
    if SOURCE_REVISION.fullmatch(revision) is None:
        raise WindowsReleaseError("release SHA must be an exact Git commit")


def _workflow(text: str) -> Mapping[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise WindowsReleaseError(
            "PyYAML is required only for post-install release-workflow validation"
        ) from exc
    try:
        workflow = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise WindowsReleaseError(f"cannot parse release workflow YAML: {exc}") from exc
    if not isinstance(workflow, Mapping):
        raise WindowsReleaseError("release workflow must be a mapping")
    return workflow


def _one_step(steps: object, name: str) -> tuple[int, Mapping[str, Any]]:
    if not isinstance(steps, list):
        raise WindowsReleaseError("release steps must be an array")
    found = [
        (index, step)
        for index, step in enumerate(steps)
        if isinstance(step, Mapping) and step.get("name") == name
    ]
    if len(found) != 1:
        raise WindowsReleaseError(f"release workflow must contain one {name!r} step")
    return found[0]


def validate_workflow(text: str) -> None:
    workflow = _workflow(text)
    if set(workflow) != {"name", "on", "permissions", "concurrency", "jobs"} and set(
        workflow
    ) != {"name", True, "permissions", "concurrency", "jobs"}:
        raise WindowsReleaseError("release workflow top-level inventory differs")
    if workflow.get("name") != "Signed Sector Windows release":
        raise WindowsReleaseError("release workflow name differs")
    triggers = workflow.get("on", workflow.get(True))
    if triggers != {"workflow_dispatch": None}:
        raise WindowsReleaseError("signed release must remain manual and unfiltered")
    if workflow.get("permissions") != {"contents": "read"}:
        raise WindowsReleaseError("release workflow permissions differ")
    if workflow.get("concurrency") != {
        "group": "sector-signed-release",
        "cancel-in-progress": False,
    }:
        raise WindowsReleaseError("signed release concurrency differs")
    jobs = workflow.get("jobs")
    if not isinstance(jobs, Mapping) or set(jobs) != {"signed-windows-release"}:
        raise WindowsReleaseError("release job inventory differs")
    job = jobs.get("signed-windows-release")
    if not isinstance(job, Mapping) or set(job) != {
        "name",
        "environment",
        "runs-on",
        "timeout-minutes",
        "steps",
    }:
        raise WindowsReleaseError("release job execution context differs")
    if job.get("name") != "Build, sign and verify Sector for Windows":
        raise WindowsReleaseError("release job name differs")
    if job.get("environment") != SIGNING_ENVIRONMENT:
        raise WindowsReleaseError("release signing environment differs")
    if job.get("runs-on") != "windows-latest" or job.get("timeout-minutes") != 60:
        raise WindowsReleaseError("release Windows identity or timeout differs")
    steps = job.get("steps")

    checkout_index, checkout = _one_step(steps, CHECKOUT_STEP)
    if checkout != {
        "name": CHECKOUT_STEP,
        "uses": CHECKOUT_ACTION,
        "with": {"fetch-depth": 0},
    }:
        raise WindowsReleaseError("release checkout identity differs")
    setup_index, setup = _one_step(steps, SETUP_STEP)
    if setup != {
        "name": SETUP_STEP,
        "uses": SETUP_ACTION,
        "with": {
            "python-version-file": ".python-version",
            "cache": "pip",
            "cache-dependency-path": "requirements-build.txt",
        },
    }:
        raise WindowsReleaseError("release Python setup identity differs")
    preflight_index, preflight = _one_step(steps, PREFLIGHT_STEP)
    if preflight != {
        "name": PREFLIGHT_STEP,
        "env": PREFLIGHT_ENV,
        "run": "python tools/verify_windows_release.py --preflight-signing",
    }:
        raise WindowsReleaseError("signing-authority preflight can be skipped or masked")
    install_index, install = _one_step(steps, INSTALL_STEP)
    if install != {
        "name": INSTALL_STEP,
        "run": "python -m pip install --require-hashes -r requirements-build.txt",
    }:
        raise WindowsReleaseError("locked release install can be skipped or weakened")
    validate_index, validator = _one_step(steps, VALIDATE_STEP)
    if validator != {
        "name": VALIDATE_STEP,
        "run": (
            "python tools/verify_windows_release.py "
            "--workflow .github/workflows/release.yml"
        ),
    }:
        raise WindowsReleaseError("release-policy validation can be skipped or masked")
    notice_index, notice = _one_step(steps, NOTICE_STEP)
    if notice != {
        "name": NOTICE_STEP,
        "run": (
            "python tools/generate_third_party_notices.py "
            "--output build/legal/THIRD_PARTY_NOTICES.txt"
        ),
    }:
        raise WindowsReleaseError("release legal-notice generation differs")
    build_index, build = _one_step(steps, BUILD_STEP)
    if build != {
        "name": BUILD_STEP,
        "env": {"SECTOR_SOURCE_REVISION": "${{ github.sha }}"},
        "run": "python -m PyInstaller --noconfirm --clean packaging/sector.spec",
    }:
        raise WindowsReleaseError("release package build identity differs")
    assemble_index, assemble = _one_step(steps, ASSEMBLE_STEP)
    if assemble != {
        "name": ASSEMBLE_STEP,
        "shell": "pwsh",
        "run": (
            "Copy-Item -LiteralPath LICENSE -Destination dist/Sector/LICENSE.txt -Force\n"
            "Copy-Item -LiteralPath build/legal/THIRD_PARTY_NOTICES.txt "
            "-Destination dist/Sector/THIRD_PARTY_NOTICES.txt -Force"
        ),
    }:
        raise WindowsReleaseError("release legal-file assembly differs")
    sign_index, sign = _one_step(steps, SIGN_STEP)
    if sign != {
        "name": SIGN_STEP,
        "shell": "pwsh",
        "env": {
            "SECTOR_SIGNING_CERTIFICATE_PFX_BASE64": SECRET_ENV[
                "SECTOR_SIGNING_CERTIFICATE_PFX_BASE64"
            ],
            "SECTOR_SIGNING_CERTIFICATE_PASSWORD": SECRET_ENV[
                "SECTOR_SIGNING_CERTIFICATE_PASSWORD"
            ],
        },
        "run": SIGN_SCRIPT,
    }:
        raise WindowsReleaseError("Authenticode signing step differs")
    verify_index, verify = _one_step(steps, VERIFY_STEP)
    if verify != {
        "name": VERIFY_STEP,
        "env": {
            "SECTOR_EXPECTED_SIGNER_SUBJECT": SECRET_ENV[
                "SECTOR_EXPECTED_SIGNER_SUBJECT"
            ],
            "SECTOR_EXPECTED_SIGNER_THUMBPRINT": SECRET_ENV[
                "SECTOR_EXPECTED_SIGNER_THUMBPRINT"
            ],
            "SECTOR_SOURCE_REVISION": "${{ github.sha }}",
        },
        "run": (
            "python tools/verify_windows_release.py --verify-package dist/Sector "
            "--source-revision $env:SECTOR_SOURCE_REVISION"
        ),
    }:
        raise WindowsReleaseError("signed-package verification step differs")
    upload_index, upload = _one_step(steps, UPLOAD_STEP)
    if upload != {
        "name": UPLOAD_STEP,
        "uses": UPLOAD_ACTION,
        "with": {
            "name": "Sector-Windows-signed",
            "path": "dist/Sector/",
            "if-no-files-found": "error",
            "retention-days": 7,
        },
    }:
        raise WindowsReleaseError("verified signed-package upload differs")
    if not (
        checkout_index
        < setup_index
        < preflight_index
        < install_index
        < validate_index
        < notice_index
        < build_index
        < assemble_index
        < sign_index
        < verify_index
        < upload_index
    ):
        raise WindowsReleaseError("signed-release workflow order differs")
    if isinstance(steps, list):
        uploads = [
            step
            for step in steps
            if isinstance(step, Mapping)
            and str(step.get("uses", "")).startswith("actions/upload-artifact@")
        ]
        if uploads != [upload]:
            raise WindowsReleaseError("unsigned or duplicate artifact upload exists")
    lowered = text.lower()
    if "start-process" in lowered or "sector.exe &" in lowered:
        raise WindowsReleaseError("release workflow launches the executable")


def _metadata_payload(text: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise WindowsReleaseError(f"cannot parse Windows signature metadata: {exc}") from exc
    expected = {
        "product_name",
        "file_description",
        "file_version",
        "product_version",
        "internal_name",
        "original_filename",
        "legal_copyright",
        "comments",
        "company_name",
        "signature_status",
        "signature_status_message",
        "signer_subject",
        "signer_thumbprint",
        "signer_not_after_utc",
        "timestamp_subject",
        "timestamp_thumbprint",
        "code_signing_eku",
        "chain_valid",
        "chain_status",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise WindowsReleaseError("Windows signature metadata schema differs")
    return payload


def validate_windows_metadata(
    payload: Mapping[str, Any],
    identity: SectorIdentity,
    *,
    expected_subject: str,
    expected_thumbprint: str,
) -> None:
    exact = {
        "product_name": PRODUCT_NAME,
        "file_description": FILE_DESCRIPTION,
        "file_version": identity.file_version,
        "product_version": identity.version,
        "internal_name": PRODUCT_NAME,
        "original_filename": ORIGINAL_FILENAME,
        "legal_copyright": LEGAL_COPYRIGHT,
        "comments": LICENCE_COMMENT,
    }
    for key, expected in exact.items():
        if payload.get(key) != expected:
            raise WindowsReleaseError(f"signed executable {key} differs")
    if payload.get("company_name") not in (None, ""):
        raise WindowsReleaseError("signed executable invents CompanyName")
    if payload.get("signature_status") != "Valid":
        raise WindowsReleaseError(
            f"Authenticode signature is not valid: {payload.get('signature_status')}"
        )
    if payload.get("signer_subject") != expected_subject:
        raise WindowsReleaseError("Authenticode signer subject differs")
    actual_thumbprint = re.sub(r"\s+", "", str(payload.get("signer_thumbprint") or ""))
    if actual_thumbprint.upper() != expected_thumbprint:
        raise WindowsReleaseError("Authenticode signer thumbprint differs")
    if payload.get("code_signing_eku") is not True:
        raise WindowsReleaseError("signer certificate lacks the code-signing EKU")
    if payload.get("chain_valid") is not True or payload.get("chain_status") not in ([], None):
        raise WindowsReleaseError("signer certificate chain is not valid")
    if not _nonblank(payload.get("timestamp_subject"), "timestamp signer subject"):
        raise WindowsReleaseError("Authenticode signature lacks a timestamp certificate")
    timestamp_thumbprint = re.sub(
        r"\s+",
        "",
        _nonblank(payload.get("timestamp_thumbprint"), "timestamp thumbprint"),
    ).upper()
    if THUMBPRINT.fullmatch(timestamp_thumbprint) is None:
        raise WindowsReleaseError("Authenticode timestamp thumbprint is malformed")
    expiry_text = _nonblank(payload.get("signer_not_after_utc"), "signer expiry")
    try:
        expiry = dt.datetime.fromisoformat(expiry_text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WindowsReleaseError("signer expiry is malformed") from exc
    if expiry.tzinfo is None:
        raise WindowsReleaseError("signer expiry must carry a timezone")


def validate_manifest(
    path: Path,
    identity: SectorIdentity,
    source_revision: str,
) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WindowsReleaseError(f"cannot read packaged provenance: {exc}") from exc
    expected_keys = {
        "product_name",
        "file_description",
        "sector_version",
        "source_revision",
        "author",
        "licensee",
        "legal_copyright",
        "built_at_utc",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected_keys:
        raise WindowsReleaseError("packaged provenance schema differs")
    expected = {
        "product_name": PRODUCT_NAME,
        "file_description": FILE_DESCRIPTION,
        "sector_version": identity.version,
        "source_revision": source_revision,
        "author": identity.author,
        "licensee": identity.licensee,
        "legal_copyright": LEGAL_COPYRIGHT,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise WindowsReleaseError(f"packaged provenance {key} differs")
    built = _nonblank(payload.get("built_at_utc"), "packaged build timestamp")
    try:
        parsed = dt.datetime.fromisoformat(built.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WindowsReleaseError("packaged build timestamp is malformed") from exc
    if parsed.tzinfo is None:
        raise WindowsReleaseError("packaged build timestamp must carry a timezone")


def verify_package(
    package: Path,
    source_revision: str,
    root: Path = ROOT,
    *,
    environment: Mapping[str, str] = os.environ,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    identity = validate_product_files(root)
    revision = _nonblank(source_revision, "release source revision")
    if SOURCE_REVISION.fullmatch(revision) is None:
        raise WindowsReleaseError("release source revision must be an exact Git SHA")
    expected_subject = _nonblank(
        environment.get("SECTOR_EXPECTED_SIGNER_SUBJECT"),
        "expected signer subject",
    )
    expected_thumbprint = re.sub(
        r"\s+",
        "",
        _nonblank(
            environment.get("SECTOR_EXPECTED_SIGNER_THUMBPRINT"),
            "expected signer thumbprint",
        ),
    ).upper()
    if THUMBPRINT.fullmatch(expected_thumbprint) is None:
        raise WindowsReleaseError("expected signer thumbprint must be exactly 40 hex")
    executable = package / ORIGINAL_FILENAME
    manifest = package / "_internal" / "sector" / "sector_build_info.json"
    proprietary = package / "LICENSE.txt"
    third_party = package / "THIRD_PARTY_NOTICES.txt"
    for path, label in (
        (executable, "Sector executable"),
        (manifest, "packaged provenance"),
        (proprietary, "proprietary notice"),
        (third_party, "third-party notice"),
    ):
        if not path.is_file():
            raise WindowsReleaseError(f"{label} is missing")
    process_environment = os.environ.copy()
    process_environment.pop("SECTOR_SIGNING_CERTIFICATE_PFX_BASE64", None)
    process_environment.pop("SECTOR_SIGNING_CERTIFICATE_PASSWORD", None)
    process_environment["SECTOR_RELEASE_EXE"] = str(executable.resolve())
    completed = runner(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            POWERSHELL_INSPECTION,
        ],
        cwd=root,
        env=process_environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise WindowsReleaseError(
            f"Windows signature inspection failed with exit code "
            f"{completed.returncode}: {detail}"
        )
    payload = _metadata_payload(completed.stdout.strip())
    validate_windows_metadata(
        payload,
        identity,
        expected_subject=expected_subject,
        expected_thumbprint=expected_thumbprint,
    )
    validate_manifest(manifest, identity, revision)
    if proprietary.read_text(encoding="ascii") != (root / LEGAL_NOTICE).read_text(
        encoding="ascii"
    ):
        raise WindowsReleaseError("packaged proprietary notice differs from source")
    if not third_party.read_text(encoding="utf-8").startswith(
        "SECTOR THIRD-PARTY NOTICES\n"
    ):
        raise WindowsReleaseError("packaged third-party notice is malformed")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", type=Path)
    parser.add_argument("--preflight-signing", action="store_true")
    parser.add_argument("--verify-package", type=Path)
    parser.add_argument("--source-revision")
    args = parser.parse_args(argv)
    try:
        validate_product_files()
        if args.preflight_signing:
            preflight_signing_environment()
        if args.workflow is not None:
            validate_workflow(args.workflow.read_text(encoding="utf-8"))
        if args.verify_package is not None:
            verify_package(
                args.verify_package,
                _nonblank(args.source_revision, "release source revision"),
            )
        elif args.source_revision is not None:
            raise WindowsReleaseError("source revision requires package verification")
    except (OSError, WindowsReleaseError) as exc:
        print(f"Windows release policy failed: {exc}", file=sys.stderr)
        return 2
    print("Windows product identity and signed-release gate are enforced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
