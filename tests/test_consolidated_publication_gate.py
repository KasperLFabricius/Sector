"""Adversarial contract for the final consolidated QA publication gate."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from tools.verify_consolidated_publication_gate import (
    CONSOLIDATED_STEP,
    PORTABLE_STEPS,
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


def test_live_workflow_is_one_fail_closed_publication_chain():
    workflow = _workflow()
    validate_workflow(WORKFLOW.read_text(encoding="utf-8"))

    test_job = workflow["jobs"]["test"]
    package_job = workflow["jobs"]["windows-package"]
    producer_a = workflow["jobs"]["portable-producer-a"]
    producer_b = workflow["jobs"]["portable-producer-b"]
    comparison = workflow["jobs"]["portable-compare"]
    smoke = workflow["jobs"]["portable-smoke"]
    portable_job = workflow["jobs"]["windows-portable"]
    assert package_job["needs"] == "test"
    assert producer_a["needs"] == "test"
    assert producer_b["needs"] == "test"
    assert comparison["needs"] == ["portable-producer-a", "portable-producer-b"]
    assert smoke["needs"] == ["portable-producer-a", "portable-compare"]
    assert portable_job["needs"] == [
        "portable-producer-a",
        "portable-producer-b",
        "portable-compare",
        "portable-smoke",
    ]
    assert tuple(step["name"] for step in portable_job["steps"]) == PORTABLE_STEPS
    assert test_job["steps"].index(_step(test_job, CONSOLIDATED_STEP)) < test_job[
        "steps"
    ].index(_step(test_job, "Validate dependency audit policy"))


@pytest.mark.parametrize(
    ("step_name", "mutation"),
    [
        ("Execute locked dependency audit", "remove"),
        ("Validate non-shrinking coverage gate", "duplicate"),
        ("Execute strict mypy policy", "skip"),
        ("Run complete test suite with coverage", "continue"),
        ("Render report fixture with real figures", "working-directory"),
    ],
)
def test_required_gate_steps_cannot_disappear_duplicate_or_weaken(
    step_name: str, mutation: str
):
    workflow = _workflow()
    job = workflow["jobs"]["test"]
    step = _step(job, step_name)
    if mutation == "remove":
        job["steps"].remove(step)
    elif mutation == "duplicate":
        job["steps"].append(deepcopy(step))
    elif mutation == "skip":
        step["if"] = "false"
    elif mutation == "continue":
        step["continue-on-error"] = True
    else:
        step["working-directory"] = "docs"

    with pytest.raises(ConsolidatedPublicationGateError):
        validate_workflow(_workflow_text(workflow))


def test_gate_order_and_package_dependency_are_exact():
    workflow = _workflow()
    steps = workflow["jobs"]["test"]["steps"]
    report = _step(workflow["jobs"]["test"], "Render report fixture with real figures")
    manual = _step(workflow["jobs"]["test"], "Render manual fixture with real figures")
    report_index = steps.index(report)
    manual_index = steps.index(manual)
    steps[report_index], steps[manual_index] = steps[manual_index], steps[report_index]
    with pytest.raises(ConsolidatedPublicationGateError, match="step inventory"):
        validate_workflow(_workflow_text(workflow))

    workflow = _workflow()
    workflow["jobs"]["windows-package"]["needs"] = None
    with pytest.raises(ConsolidatedPublicationGateError, match="successful test job"):
        validate_workflow(_workflow_text(workflow))

    workflow = _workflow()
    workflow["jobs"]["portable-producer-a"]["needs"] = "windows-package"
    with pytest.raises(ConsolidatedPublicationGateError, match="dependency"):
        validate_workflow(_workflow_text(workflow))


@pytest.mark.parametrize(
    ("step_name", "field", "value"),
    [
        (
            CONSOLIDATED_STEP,
            "run",
            "python tools/verify_consolidated_publication_gate.py changed.yml",
        ),
        (
            "Render report fixture with real figures",
            "run",
            "python tools/report_render_fixture.py --output changed",
        ),
        (
            "Render manual fixture with real figures",
            "run",
            "python tools/manual_render_fixture.py --output changed",
        ),
        (
            "Upload QA evidence",
            "uses",
            "actions/upload-artifact@main",
        ),
    ],
)
def test_validator_render_and_upload_identity_cannot_drift(
    step_name: str, field: str, value: str
):
    workflow = _workflow()
    _step(workflow["jobs"]["test"], step_name)[field] = value
    with pytest.raises(ConsolidatedPublicationGateError):
        validate_workflow(_workflow_text(workflow))


def test_evidence_retention_and_unsigned_secret_boundary_cannot_drift():
    workflow = _workflow()
    qa_upload = _step(workflow["jobs"]["test"], "Upload QA evidence")
    qa_upload["with"]["retention-days"] = 1
    with pytest.raises(ConsolidatedPublicationGateError, match="QA evidence upload"):
        validate_workflow(_workflow_text(workflow))

    workflow = _workflow()
    package_upload = _step(
        workflow["jobs"]["windows-package"],
        "Upload unsigned QA reproducibility evidence",
    )
    package_upload["with"]["path"] = "dist/Sector"
    with pytest.raises(ConsolidatedPublicationGateError, match="package evidence"):
        validate_workflow(_workflow_text(workflow))

    workflow = _workflow()
    portable_upload = _step(
        workflow["jobs"]["windows-portable"],
        "Upload unsigned portable Windows evidence",
    )
    portable_upload["with"]["path"] = "dist/portable"
    with pytest.raises(ConsolidatedPublicationGateError, match="structured contract"):
        validate_workflow(_workflow_text(workflow))

    workflow = _workflow()
    workflow["jobs"]["windows-package"]["env"] = {
        "CERTIFICATE": "${{ secrets.SECTOR_SIGNING_PFX_BASE64 }}"
    }
    with pytest.raises(ConsolidatedPublicationGateError, match="signing authority"):
        validate_workflow(_workflow_text(workflow))


@pytest.mark.parametrize(
    "secret_expression",
    [
        "${{secrets.SECTOR_SIGNING_PFX_BASE64}}",
        "${{ secrets['SECTOR_SIGNING_PFX_BASE64'] }}",
        "${{ '}' && secrets.SECTOR_SIGNING_PFX_BASE64 }}",
    ],
)
def test_secret_context_syntax_variants_are_rejected(secret_expression: str):
    workflow = _workflow()
    workflow["env"] = {"CERTIFICATE": secret_expression}

    with pytest.raises(ConsolidatedPublicationGateError, match="signing authority"):
        validate_workflow(_workflow_text(workflow))


@pytest.mark.parametrize(
    "permissions",
    [
        "write-all",
        {"contents": "write"},
        {"contents": "read", "actions": "write"},
    ],
)
def test_workflow_permissions_must_remain_read_only(permissions: object):
    workflow = _workflow()
    workflow["permissions"] = permissions

    with pytest.raises(ConsolidatedPublicationGateError, match="permissions"):
        validate_workflow(_workflow_text(workflow))


@pytest.mark.parametrize(
    ("key", "value"),
    [
        (
            "env",
            {
                "PYTEST_ADDOPTS": (
                    "--deselect=tests/test_consolidated_publication_gate.py"
                )
            },
        ),
        ("defaults", {"run": {"shell": "bash"}}),
    ],
)
def test_inherited_workflow_execution_settings_are_rejected(
    key: str, value: object
):
    workflow = _workflow()
    workflow[key] = value

    with pytest.raises(
        ConsolidatedPublicationGateError, match="top-level contract"
    ):
        validate_workflow(_workflow_text(workflow))


@pytest.mark.parametrize(
    ("job_name", "step_name"),
    [
        ("test", "Check out source"),
        ("test", "Set up pinned Python"),
        ("windows-package", "Check out source"),
        ("windows-package", "Set up pinned Python"),
        ("portable-producer-a", "Check out source for producer A"),
        ("portable-producer-b", "Set up producer B Python"),
        ("portable-compare", "Download immutable producer A"),
        ("portable-smoke", "Check out source for isolated smoke"),
        ("windows-portable", "Download producer A for final publication"),
    ],
)
def test_every_action_identity_is_exact(job_name: str, step_name: str):
    workflow = _workflow()
    _step(workflow["jobs"][job_name], step_name)["uses"] = (
        "attacker/action@" + "a" * 40
    )

    with pytest.raises(
        ConsolidatedPublicationGateError, match="approved action identity"
    ):
        validate_workflow(_workflow_text(workflow))


@pytest.mark.parametrize(
    ("step_name", "field", "value"),
    [
        (
            "Build first unsigned QA package from exact exported source",
            "run",
            "Write-Output 'fabricated package'",
        ),
        (
            "Build second unsigned QA package from exact exported source",
            "env",
            {"SECTOR_SOURCE_REVISION": "HEAD"},
        ),
        ("Verify both unsigned QA package identities", "shell", "bash"),
        (
            "Compare independent unsigned QA package builds",
            "run",
            "if ($false) { Write-Output 'comparison skipped' }",
        ),
    ],
)
def test_package_execution_mappings_are_exact(
    step_name: str, field: str, value: object
):
    workflow = _workflow()
    _step(workflow["jobs"]["windows-package"], step_name)[field] = value

    with pytest.raises(
        ConsolidatedPublicationGateError, match="exact structured contract"
    ):
        validate_workflow(_workflow_text(workflow))


def test_extra_job_or_unpinned_action_is_rejected():
    workflow = _workflow()
    workflow["jobs"]["extra"] = deepcopy(workflow["jobs"]["test"])
    with pytest.raises(ConsolidatedPublicationGateError, match="job inventory"):
        validate_workflow(_workflow_text(workflow))

    workflow = _workflow()
    _step(workflow["jobs"]["test"], "Check out source")["uses"] = (
        "actions/checkout@v4"
    )
    with pytest.raises(ConsolidatedPublicationGateError, match="full commit"):
        validate_workflow(_workflow_text(workflow))
