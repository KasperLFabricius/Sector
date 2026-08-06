from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from tools.verify_windows_release import (
    AUTHOR,
    BUILD_STEP,
    CHECKOUT_ACTION,
    CHECKOUT_STEP,
    FILE_DESCRIPTION,
    INSTALL_STEP,
    LEGAL_COPYRIGHT,
    LICENCE_COMMENT,
    LICENSEE,
    ORIGINAL_FILENAME,
    PREFLIGHT_STEP,
    PREFLIGHT_ENV,
    PRODUCT_NAME,
    RELEASE_WORKFLOW,
    SECRET_ENV,
    SETUP_ACTION,
    SETUP_STEP,
    SIGN_SCRIPT,
    SIGN_STEP,
    SIGNING_ENVIRONMENT,
    TIMESTAMP_URL,
    UPLOAD_ACTION,
    UPLOAD_STEP,
    VERIFY_STEP,
    SectorIdentity,
    WindowsReleaseError,
    preflight_signing_environment,
    read_identity,
    render_version_resource,
    validate_manifest,
    validate_product_files,
    validate_windows_metadata,
    validate_workflow,
    verify_package,
)

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / RELEASE_WORKFLOW
TOOL = ROOT / "tools" / "verify_windows_release.py"
VERSION_RESOURCE = ROOT / "packaging" / "windows_version_info.txt"
SOURCE_SHA = "c" * 40
SIGNER_SUBJECT = "CN=Sector Genuine Code Signing"
SIGNER_THUMBPRINT = "A" * 40
TIMESTAMP_THUMBPRINT = "B" * 40


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _workflow_text(workflow) -> str:
    return yaml.safe_dump(workflow, sort_keys=False)


def _step(workflow, name: str):
    return next(
        step
        for step in workflow["jobs"]["signed-windows-release"]["steps"]
        if step["name"] == name
    )


def _identity(version: str = "0.91") -> SectorIdentity:
    parts = [int(value) for value in version.split(".")]
    version_tuple = tuple(parts + [0] * (4 - len(parts)))
    return SectorIdentity(version, AUTHOR, LICENSEE, version_tuple)


def _metadata(**changes):
    payload = {
        "product_name": PRODUCT_NAME,
        "file_description": FILE_DESCRIPTION,
        "file_version": "0.91.0.0",
        "product_version": "0.91",
        "internal_name": PRODUCT_NAME,
        "original_filename": ORIGINAL_FILENAME,
        "legal_copyright": LEGAL_COPYRIGHT,
        "comments": LICENCE_COMMENT,
        "company_name": None,
        "signature_status": "Valid",
        "signature_status_message": "Signature verified.",
        "signer_subject": SIGNER_SUBJECT,
        "signer_thumbprint": SIGNER_THUMBPRINT,
        "signer_not_after_utc": "2030-01-01T00:00:00+00:00",
        "timestamp_subject": "CN=Timestamp Authority",
        "timestamp_thumbprint": TIMESTAMP_THUMBPRINT,
        "code_signing_eku": True,
        "chain_valid": True,
        "chain_status": [],
    }
    payload.update(changes)
    return payload


def _manifest(identity: SectorIdentity | None = None, **changes):
    identity = identity or _identity()
    payload = {
        "product_name": PRODUCT_NAME,
        "file_description": FILE_DESCRIPTION,
        "sector_version": identity.version,
        "source_revision": SOURCE_SHA,
        "author": identity.author,
        "licensee": identity.licensee,
        "legal_copyright": LEGAL_COPYRIGHT,
        "built_at_utc": "2026-08-06T01:00:00+00:00",
    }
    payload.update(changes)
    return payload


def _temporary_product_root(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    (root / "sector").mkdir(parents=True)
    (root / "packaging").mkdir()
    (root / "sector" / "__init__.py").write_text(
        '__version__ = "0.91"\n'
        f'__author__ = "{AUTHOR}"\n'
        f'__licensee__ = "{LICENSEE}"\n',
        encoding="utf-8",
    )
    (root / "packaging" / "windows_version_info.txt").write_text(
        render_version_resource(_identity()), encoding="utf-8"
    )
    (root / "packaging" / "sector.spec").write_text(
        (ROOT / "packaging" / "sector.spec").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (root / "LICENSE").write_text(
        (ROOT / "LICENSE").read_text(encoding="ascii"), encoding="ascii"
    )
    return root


def _temporary_package(tmp_path: Path) -> Path:
    package = tmp_path / "Sector"
    manifest = package / "_internal" / "sector" / "sector_build_info.json"
    manifest.parent.mkdir(parents=True)
    (package / ORIGINAL_FILENAME).write_bytes(b"MZ unsigned test fixture")
    manifest.write_text(json.dumps(_manifest()), encoding="utf-8")
    (package / "LICENSE.txt").write_text(
        (ROOT / "LICENSE").read_text(encoding="ascii"), encoding="ascii"
    )
    (package / "THIRD_PARTY_NOTICES.txt").write_text(
        "SECTOR THIRD-PARTY NOTICES\nfixture\n", encoding="utf-8"
    )
    return package


def _signing_environment(**changes):
    environment = {
        "SECTOR_SIGNING_CERTIFICATE_PFX_BASE64": base64.b64encode(
            b"certificate" * 60
        ).decode("ascii"),
        "SECTOR_SIGNING_CERTIFICATE_PASSWORD": "secret-password",
        "SECTOR_EXPECTED_SIGNER_SUBJECT": SIGNER_SUBJECT,
        "SECTOR_EXPECTED_SIGNER_THUMBPRINT": SIGNER_THUMBPRINT,
        "SECTOR_RELEASE_REF": "refs/heads/main",
        "SECTOR_RELEASE_SHA": SOURCE_SHA,
    }
    environment.update(changes)
    return environment


def test_live_product_resource_workflow_and_standard_library_identity_pass():
    identity = validate_product_files(ROOT)
    validate_workflow(WORKFLOW.read_text(encoding="utf-8"))

    assert identity == _identity()
    assert VERSION_RESOURCE.read_text(encoding="utf-8") == render_version_resource(
        identity
    )
    resource = render_version_resource(identity)
    assert "CompanyName" not in resource
    assert "Publisher" not in resource
    assert "0.91.0.0" in resource
    assert AUTHOR in resource
    assert LICENSEE in resource

    completed = subprocess.run(
        [sys.executable, "-I", "-S", str(TOOL)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize(
    ("version", "message"),
    [
        ("0", "Windows version tuple"),
        ("0.91.beta", "Windows version tuple"),
        ("0.1.2.3.4", "Windows version tuple"),
        ("0.65536", "must not exceed"),
    ],
)
def test_invalid_source_versions_cannot_form_windows_identity(tmp_path, version, message):
    source = tmp_path / "__init__.py"
    source.write_text(
        f'__version__ = "{version}"\n'
        f'__author__ = "{AUTHOR}"\n'
        f'__licensee__ = "{LICENSEE}"\n',
        encoding="utf-8",
    )
    with pytest.raises(WindowsReleaseError, match=message):
        read_identity(source)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("__author__", "Sweco Danmark A/S", "author/copyright-holder"),
        ("__licensee__", "Kasper Lindskov Fabricius", "licensed-organisation"),
    ],
)
def test_author_and_licensee_roles_cannot_be_relabelled(tmp_path, field, value, message):
    source = tmp_path / "__init__.py"
    rows = {
        "__version__": "0.91",
        "__author__": AUTHOR,
        "__licensee__": LICENSEE,
    }
    rows[field] = value
    source.write_text(
        "".join(f'{key} = "{item}"\n' for key, item in rows.items()),
        encoding="utf-8",
    )
    with pytest.raises(WindowsReleaseError, match=message):
        read_identity(source)


def test_duplicate_or_nonliteral_source_identity_fails(tmp_path):
    source = tmp_path / "__init__.py"
    source.write_text(
        '__version__ = "0.91"\n'
        '__version__ = "0.92"\n'
        f'__author__ = "{AUTHOR}"\n'
        f'__licensee__ = "{LICENSEE}"\n',
        encoding="utf-8",
    )
    with pytest.raises(WindowsReleaseError, match="exactly once"):
        read_identity(source)

    source.write_text(
        'VERSION = "0.91"\n'
        "__version__ = VERSION\n"
        f'__author__ = "{AUTHOR}"\n'
        f'__licensee__ = "{LICENSEE}"\n',
        encoding="utf-8",
    )
    with pytest.raises(WindowsReleaseError, match="literal text"):
        read_identity(source)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda text: text.replace("ProductVersion', '0.91", "ProductVersion', '0.92"), "resource differs"),
        (lambda text: text + "StringStruct('CompanyName', 'Sweco Danmark A/S')\n", "resource differs"),
        (lambda text: text.replace("StringFileInfo", "OtherFileInfo", 1), "resource differs"),
    ],
)
def test_windows_resource_must_exactly_match_source_identity(tmp_path, mutation, message):
    root = _temporary_product_root(tmp_path)
    resource = root / "packaging" / "windows_version_info.txt"
    resource.write_text(mutation(resource.read_text(encoding="utf-8")), encoding="utf-8")
    with pytest.raises(WindowsReleaseError, match=message):
        validate_product_files(root)


@pytest.mark.parametrize(
    "snippet",
    [
        '"product_name": PRODUCT_NAME',
        '"source_revision": _source_revision(ROOT)',
        '"author": identity["author"]',
        '"licensee": identity["licensee"]',
        "version=WINDOWS_VERSION_RESOURCE",
    ],
)
def test_package_spec_cannot_drop_identity_or_provenance_wiring(tmp_path, snippet):
    root = _temporary_product_root(tmp_path)
    spec = root / "packaging" / "sector.spec"
    spec.write_text(spec.read_text(encoding="utf-8").replace(snippet, "removed"), encoding="utf-8")
    with pytest.raises(WindowsReleaseError, match="spec omits"):
        validate_product_files(root)


def test_genuine_signing_authority_preflight_accepts_complete_secret_set():
    preflight_signing_environment(_signing_environment())


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("SECTOR_SIGNING_CERTIFICATE_PFX_BASE64", "", "signing certificate"),
        ("SECTOR_SIGNING_CERTIFICATE_PFX_BASE64", "not base64!", "valid base64"),
        (
            "SECTOR_SIGNING_CERTIFICATE_PFX_BASE64",
            base64.b64encode(b"tiny").decode("ascii"),
            "implausibly small",
        ),
        ("SECTOR_SIGNING_CERTIFICATE_PASSWORD", "", "password"),
        ("SECTOR_EXPECTED_SIGNER_SUBJECT", "", "subject"),
        ("SECTOR_EXPECTED_SIGNER_THUMBPRINT", "A" * 39, "40 hex"),
        ("SECTOR_EXPECTED_SIGNER_THUMBPRINT", "G" * 40, "40 hex"),
        ("SECTOR_RELEASE_REF", "refs/heads/feature", "restricted to refs/heads/main"),
        ("SECTOR_RELEASE_SHA", "main", "exact Git commit"),
    ],
)
def test_missing_or_malformed_signing_authority_fails_closed(name, value, message):
    environment = _signing_environment(**{name: value})
    with pytest.raises(WindowsReleaseError, match=message):
        preflight_signing_environment(environment)


def test_valid_signed_windows_metadata_matches_product_identity():
    validate_windows_metadata(
        _metadata(),
        _identity(),
        expected_subject=SIGNER_SUBJECT,
        expected_thumbprint=SIGNER_THUMBPRINT,
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"product_name": "Other"}, "product_name differs"),
        ({"file_description": "Certified calculator"}, "file_description differs"),
        ({"product_version": "0.92"}, "product_version differs"),
        ({"file_version": "0.92.0.0"}, "file_version differs"),
        ({"company_name": "Sweco Danmark A/S"}, "CompanyName"),
        ({"signature_status": "NotSigned"}, "not valid"),
        ({"signer_subject": "CN=Other"}, "subject differs"),
        ({"signer_thumbprint": "C" * 40}, "thumbprint differs"),
        ({"code_signing_eku": False}, "code-signing EKU"),
        ({"chain_valid": False}, "chain is not valid"),
        ({"chain_status": ["UntrustedRoot"]}, "chain is not valid"),
        ({"timestamp_subject": None}, "timestamp signer subject"),
        ({"timestamp_thumbprint": "bad"}, "timestamp thumbprint is malformed"),
        ({"signer_not_after_utc": "not-a-date"}, "expiry is malformed"),
    ],
)
def test_metadata_tampering_unsigned_wrong_signer_and_untimestamped_fail(changes, message):
    with pytest.raises(WindowsReleaseError, match=message):
        validate_windows_metadata(
            _metadata(**changes),
            _identity(),
            expected_subject=SIGNER_SUBJECT,
            expected_thumbprint=SIGNER_THUMBPRINT,
        )


def test_packaged_provenance_is_exact_and_timestamped(tmp_path):
    path = tmp_path / "sector_build_info.json"
    path.write_text(json.dumps(_manifest()), encoding="utf-8")
    validate_manifest(path, _identity(), SOURCE_SHA)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"product_name": "Other"}, "product_name differs"),
        ({"sector_version": "0.92"}, "sector_version differs"),
        ({"source_revision": "d" * 40}, "source_revision differs"),
        ({"author": LICENSEE}, "author differs"),
        ({"licensee": AUTHOR}, "licensee differs"),
        ({"built_at_utc": "unknown"}, "timestamp is malformed"),
    ],
)
def test_packaged_provenance_mutations_fail(tmp_path, changes, message):
    path = tmp_path / "sector_build_info.json"
    path.write_text(json.dumps(_manifest(**changes)), encoding="utf-8")
    with pytest.raises(WindowsReleaseError, match=message):
        validate_manifest(path, _identity(), SOURCE_SHA)


def test_signed_package_verification_never_launches_executable(tmp_path, monkeypatch):
    package = _temporary_package(tmp_path)
    captured = {}
    monkeypatch.setenv("SECTOR_SIGNING_CERTIFICATE_PFX_BASE64", "must-not-propagate")
    monkeypatch.setenv("SECTOR_SIGNING_CERTIFICATE_PASSWORD", "must-not-propagate")

    def runner(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, json.dumps(_metadata()), "")

    verify_package(
        package,
        SOURCE_SHA,
        ROOT,
        environment={
            "SECTOR_EXPECTED_SIGNER_SUBJECT": SIGNER_SUBJECT,
            "SECTOR_EXPECTED_SIGNER_THUMBPRINT": SIGNER_THUMBPRINT,
        },
        runner=runner,
    )
    command = captured["command"]
    assert command[:4] == ["powershell", "-NoProfile", "-NonInteractive", "-Command"]
    assert ORIGINAL_FILENAME not in command[:3]
    assert "Start-Process" not in command[-1]
    assert "Get-AuthenticodeSignature" in command[-1]
    process_environment = captured["kwargs"]["env"]
    assert process_environment["SECTOR_RELEASE_EXE"].endswith(ORIGINAL_FILENAME)
    assert "SECTOR_SIGNING_CERTIFICATE_PFX_BASE64" not in process_environment
    assert "SECTOR_SIGNING_CERTIFICATE_PASSWORD" not in process_environment


def test_package_verification_rejects_missing_files_and_failed_inspection(tmp_path):
    package = _temporary_package(tmp_path)
    (package / "LICENSE.txt").unlink()
    with pytest.raises(WindowsReleaseError, match="proprietary notice is missing"):
        verify_package(
            package,
            SOURCE_SHA,
            ROOT,
            environment={
                "SECTOR_EXPECTED_SIGNER_SUBJECT": SIGNER_SUBJECT,
                "SECTOR_EXPECTED_SIGNER_THUMBPRINT": SIGNER_THUMBPRINT,
            },
        )

    package = _temporary_package(tmp_path / "second")

    def failing(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, "", "inspection failed")

    with pytest.raises(WindowsReleaseError, match="inspection failed"):
        verify_package(
            package,
            SOURCE_SHA,
            ROOT,
            environment={
                "SECTOR_EXPECTED_SIGNER_SUBJECT": SIGNER_SUBJECT,
                "SECTOR_EXPECTED_SIGNER_THUMBPRINT": SIGNER_THUMBPRINT,
            },
            runner=failing,
        )


@pytest.mark.parametrize("step_name", [PREFLIGHT_STEP, SIGN_STEP, VERIFY_STEP, UPLOAD_STEP])
@pytest.mark.parametrize(
    ("field", "value"),
    [("if", "false"), ("continue-on-error", True), ("working-directory", "docs")],
)
def test_release_steps_are_unconditional_and_failure_propagating(step_name, field, value):
    workflow = _workflow()
    _step(workflow, step_name)[field] = value
    with pytest.raises(WindowsReleaseError, match="differs|skipped or masked"):
        validate_workflow(_workflow_text(workflow))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("if", "false"),
        ("continue-on-error", True),
        ("needs", "unsigned-build"),
        ("permissions", {"contents": "write"}),
    ],
)
def test_release_job_context_cannot_mask_signing(field, value):
    workflow = _workflow()
    workflow["jobs"]["signed-windows-release"][field] = value
    with pytest.raises(WindowsReleaseError, match="execution context"):
        validate_workflow(_workflow_text(workflow))


def test_release_is_manual_environment_gated_and_uses_pinned_actions():
    workflow = _workflow()
    assert workflow.get("on", workflow.get(True)) == {"workflow_dispatch": None}
    job = workflow["jobs"]["signed-windows-release"]
    assert job["environment"] == SIGNING_ENVIRONMENT
    assert _step(workflow, CHECKOUT_STEP)["uses"] == CHECKOUT_ACTION
    assert _step(workflow, SETUP_STEP)["uses"] == SETUP_ACTION
    assert _step(workflow, UPLOAD_STEP)["uses"] == UPLOAD_ACTION
    assert _step(workflow, PREFLIGHT_STEP)["env"] == PREFLIGHT_ENV


@pytest.mark.parametrize(
    "mutation",
    [
        lambda workflow: workflow.update({"on": {"push": {"tags": ["v*"]}}}),
        lambda workflow: workflow.update({"permissions": {"contents": "write"}}),
        lambda workflow: workflow["jobs"]["signed-windows-release"].update(
            {"environment": "unprotected"}
        ),
        lambda workflow: _step(workflow, CHECKOUT_STEP)["with"].update(
            {"fetch-depth": 1}
        ),
        lambda workflow: _step(workflow, SIGN_STEP)["run"].replace(
            TIMESTAMP_URL, "http://example.invalid"
        ),
    ],
)
def test_trigger_permissions_environment_checkout_and_signing_are_exact(mutation):
    workflow = _workflow()
    result = mutation(workflow)
    if isinstance(result, str):
        _step(workflow, SIGN_STEP)["run"] = result
    with pytest.raises(WindowsReleaseError):
        validate_workflow(_workflow_text(workflow))


def test_preflight_precedes_install_and_upload_follows_signature_verification():
    workflow = _workflow()
    steps = workflow["jobs"]["signed-windows-release"]["steps"]
    names = [step["name"] for step in steps]
    assert names.index(PREFLIGHT_STEP) < names.index(INSTALL_STEP)
    assert names.index(SIGN_STEP) < names.index(VERIFY_STEP) < names.index(UPLOAD_STEP)

    upload = steps.pop(names.index(UPLOAD_STEP))
    sign_index = next(index for index, step in enumerate(steps) if step["name"] == SIGN_STEP)
    steps.insert(sign_index, upload)
    with pytest.raises(WindowsReleaseError, match="workflow order"):
        validate_workflow(_workflow_text(workflow))


def test_no_unsigned_or_duplicate_artifact_upload_can_be_added():
    workflow = _workflow()
    extra = deepcopy(_step(workflow, UPLOAD_STEP))
    extra["name"] = "Upload unsigned package"
    steps = workflow["jobs"]["signed-windows-release"]["steps"]
    build_index = next(index for index, step in enumerate(steps) if step["name"] == BUILD_STEP)
    steps.insert(build_index + 1, extra)
    with pytest.raises(WindowsReleaseError, match="unsigned or duplicate"):
        validate_workflow(_workflow_text(workflow))


def test_signing_script_uses_sha256_timestamp_runner_temp_and_finally_cleanup():
    script = _step(_workflow(), SIGN_STEP)["run"]
    assert "/fd SHA256 /td SHA256" in script
    assert f"/tr {TIMESTAMP_URL}" in script
    assert "$env:RUNNER_TEMP" in script
    assert "Where-Object { $_.Directory.Name -eq 'x64' }" in script
    assert "-match" not in script
    assert "finally" in script
    assert "Remove-Item -LiteralPath $certificatePath -Force" in script
    assert "Start-Process" not in script


@pytest.mark.parametrize(
    "script",
    [
        SIGN_SCRIPT,
        (ROOT / "packaging" / "build.ps1").read_text(encoding="utf-8"),
    ],
)
def test_powershell_release_scripts_are_syntactically_valid(script):
    environment = os.environ.copy()
    environment["SECTOR_SCRIPT_UNDER_TEST"] = script
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            (
                "$tokens=$null; $errors=$null; "
                "[Management.Automation.Language.Parser]::ParseInput("
                "$env:SECTOR_SCRIPT_UNDER_TEST,[ref]$tokens,[ref]$errors) "
                "| Out-Null; if ($errors.Count -ne 0) { "
                "$errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
            ),
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_ordinary_build_surfaces_are_explicitly_unsigned_and_never_invite_launch():
    qa = (ROOT / ".github" / "workflows" / "qa.yml").read_text(encoding="utf-8")
    powershell = (ROOT / "packaging" / "build.ps1").read_text(encoding="utf-8")
    batch = (ROOT / "packaging" / "build.bat").read_text(encoding="utf-8")
    readme = (ROOT / "packaging" / "README.md").read_text(encoding="utf-8")

    assert "Sector-Windows-unsigned-QA" in qa
    assert "Unsigned QA Windows package" in qa
    assert "Do not launch or distribute" in powershell
    assert "Do not launch or distribute" in batch
    assert "unsigned QA build" in readme
    assert "there is no unsigned fallback" in readme.lower()


def test_release_workflow_contains_only_secret_references_not_credentials():
    text = WORKFLOW.read_text(encoding="utf-8")
    for expression in SECRET_ENV.values():
        assert expression in text
    assert SIGNER_SUBJECT not in text
    assert SIGNER_THUMBPRINT not in text
    assert "BEGIN CERTIFICATE" not in text
