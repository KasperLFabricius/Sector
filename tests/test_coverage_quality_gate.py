from __future__ import annotations

import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
import tomllib
import yaml

from tools.verify_coverage_gate import (
    BASELINE_ENV,
    BASELINE_EXPRESSION,
    CHECKOUT_ACTION,
    CHECKOUT_STEP_NAME,
    COVERAGE_STEP_NAME,
    VALIDATOR_STEP_NAME,
    CoverageGateContractError,
    expected_coverage_command,
    expected_validator_command,
    load_git_baseline,
    validate_contract,
    validate_workflow,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "quality-coverage-gate.toml"
WORKFLOW = ROOT / ".github" / "workflows" / "qa.yml"
CALIBRATION_WAIVER = {
    "id": "coverage-pr14-calibration",
    "gate": "coverage",
    "owner": "PR-14C integration owner",
    "reason": "Temporary calibration floor.",
    "exit_condition": "Remove after the final exact-head measurement.",
}


def _contract():
    return tomllib.loads(CONTRACT.read_text(encoding="utf-8"))


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _workflow_text(data) -> str:
    return yaml.safe_dump(data, sort_keys=False)


def _step(workflow, name: str):
    return next(
        step for step in workflow["jobs"]["test"]["steps"] if step["name"] == name
    )


def test_exact_contract_and_workflow_are_aligned():
    data = _contract()
    validate_contract(data, ROOT)
    validate_workflow(data, WORKFLOW.read_text(encoding="utf-8"))

    assert expected_validator_command().endswith(
        "--baseline-ref $env:SECTOR_COVERAGE_BASELINE_REF"
    )
    assert "--dist loadgroup" in expected_coverage_command(data)
    assert "--basetemp $baseTemp" in expected_coverage_command(data)
    assert "--cov=app" in expected_coverage_command(data)
    assert "--cov=sector" in expected_coverage_command(data)
    assert "--cov-fail-under=90" in expected_coverage_command(data)
    assert data["waivers"] == []


def test_raised_accepted_floor_and_targets_cannot_shrink():
    baseline = deepcopy(_contract())
    baseline["coverage"]["minimum_percent"] = 93
    baseline["coverage"]["targets"].append("docs")

    candidate = deepcopy(baseline)
    candidate["coverage"]["minimum_percent"] = 92
    with pytest.raises(CoverageGateContractError, match="previously accepted"):
        validate_contract(candidate, ROOT, baseline=baseline)

    candidate = deepcopy(baseline)
    candidate["coverage"]["targets"].remove("docs")
    with pytest.raises(CoverageGateContractError, match="accepted coverage target"):
        validate_contract(candidate, ROOT, baseline=baseline)


@pytest.mark.parametrize("minimum", [49, 89, True, 50.5, 101])
def test_invalid_initial_floor_is_rejected(minimum):
    data = deepcopy(_contract())
    data["coverage"]["minimum_percent"] = minimum

    with pytest.raises(CoverageGateContractError, match="coverage minimum"):
        validate_contract(data, ROOT)


def test_duplicate_missing_and_escaping_targets_are_rejected(tmp_path):
    data = deepcopy(_contract())
    data["coverage"]["targets"].append("app")
    with pytest.raises(CoverageGateContractError, match="duplicates"):
        validate_contract(data, ROOT)

    data = deepcopy(_contract())
    data["coverage"]["targets"].remove("sector")
    with pytest.raises(CoverageGateContractError, match="initial coverage target"):
        validate_contract(data, ROOT)

    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    data = deepcopy(_contract())
    data["coverage"]["targets"][0] = "../outside"
    with pytest.raises(CoverageGateContractError, match="escapes the repository"):
        validate_contract(data, repository_root)


@pytest.mark.parametrize("field", ["owner", "reason", "exit_condition"])
def test_reintroduced_waiver_cannot_hide_incomplete_ownership(field):
    data = deepcopy(_contract())
    waiver = deepcopy(CALIBRATION_WAIVER)
    waiver[field] = ""
    data["waivers"].append(waiver)

    with pytest.raises(CoverageGateContractError, match=field):
        validate_contract(data, ROOT, candidate_waiver_ids={waiver["id"]})


def test_unknown_contract_keys_and_waiver_drift_are_rejected():
    data = deepcopy(_contract())
    data["unknown"] = True
    with pytest.raises(CoverageGateContractError, match="top-level contract keys"):
        validate_contract(data, ROOT)

    data = deepcopy(_contract())
    data["coverage"].pop("minimum_percent")
    with pytest.raises(CoverageGateContractError, match="coverage contract"):
        validate_contract(data, ROOT)

    data = deepcopy(_contract())
    data["waivers"] = [deepcopy(CALIBRATION_WAIVER)] * 2
    with pytest.raises(CoverageGateContractError, match="duplicate waiver"):
        validate_contract(data, ROOT, candidate_waiver_ids={CALIBRATION_WAIVER["id"]})

    data = deepcopy(_contract())
    data["waivers"] = [deepcopy(CALIBRATION_WAIVER)]
    data["waivers"][0]["gate"] = "ruff"
    with pytest.raises(CoverageGateContractError, match="wrong gate"):
        validate_contract(data, ROOT, candidate_waiver_ids={CALIBRATION_WAIVER["id"]})


def test_satisfied_calibration_waiver_can_expire_against_accepted_baseline():
    baseline = deepcopy(_contract())
    baseline["coverage"]["minimum_percent"] = 50
    baseline["waivers"] = [deepcopy(CALIBRATION_WAIVER)]
    candidate = deepcopy(_contract())

    validate_contract(candidate, ROOT, baseline=baseline)


def test_git_baseline_is_loaded_from_the_accepted_object(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    candidate_contract = repository / CONTRACT.name
    for arguments in (
        ["init"],
        ["config", "user.name", "Sector QA"],
        ["config", "user.email", "sector-qa@example.invalid"],
        ["commit", "--allow-empty", "-m", "accepted base without coverage contract"],
    ):
        subprocess.run(
            ["git", *arguments],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )
    assert load_git_baseline("HEAD", candidate_contract, repository) is None

    baseline_text = CONTRACT.read_text(encoding="utf-8").replace(
        "minimum_percent = 90", "minimum_percent = 91"
    )
    candidate_contract.write_text(baseline_text, encoding="utf-8")
    for arguments in (
        ["add", CONTRACT.name],
        ["commit", "-m", "accepted coverage baseline"],
    ):
        subprocess.run(
            ["git", *arguments],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )
    candidate_contract.write_text(
        CONTRACT.read_text(encoding="utf-8"), encoding="utf-8"
    )

    baseline = load_git_baseline("HEAD", candidate_contract, repository)
    assert baseline is not None
    assert baseline["coverage"]["minimum_percent"] == 91
    with pytest.raises(CoverageGateContractError, match="previously accepted"):
        validate_contract(_contract(), ROOT, baseline=baseline)
    with pytest.raises(CoverageGateContractError, match="git baseline inspection"):
        load_git_baseline("missing-accepted-ref", candidate_contract, repository)


@pytest.mark.parametrize("step_name", [VALIDATOR_STEP_NAME, COVERAGE_STEP_NAME])
@pytest.mark.parametrize(
    ("field", "value"),
    [("if", "false"), ("continue-on-error", True), ("working-directory", "docs")],
)
def test_gate_steps_cannot_be_skipped_or_made_non_propagating(step_name, field, value):
    workflow = _workflow()
    _step(workflow, step_name)[field] = value

    with pytest.raises(
        CoverageGateContractError, match="unconditional and failure-propagating"
    ):
        validate_workflow(_contract(), _workflow_text(workflow))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("if", "false"),
        ("continue-on-error", True),
        ("needs", "windows-package"),
        ("env", {"PYTEST_ADDOPTS": "--no-cov"}),
    ],
)
def test_test_job_cannot_be_skipped_or_made_non_propagating(field, value):
    workflow = _workflow()
    workflow["jobs"]["test"][field] = value

    with pytest.raises(
        CoverageGateContractError, match="unconditional failure-propagating context"
    ):
        validate_workflow(_contract(), _workflow_text(workflow))


def test_checkout_history_and_baseline_identity_are_pinned():
    workflow = _workflow()
    _step(workflow, CHECKOUT_STEP_NAME)["with"]["fetch-depth"] = 1
    with pytest.raises(CoverageGateContractError, match="fetch history"):
        validate_workflow(_contract(), _workflow_text(workflow))

    workflow = _workflow()
    _step(workflow, CHECKOUT_STEP_NAME)["uses"] = "actions/checkout@main"
    with pytest.raises(CoverageGateContractError, match="fetch history"):
        validate_workflow(_contract(), _workflow_text(workflow))

    workflow = _workflow()
    _step(workflow, VALIDATOR_STEP_NAME)["env"][BASELINE_ENV] = "HEAD^"
    with pytest.raises(CoverageGateContractError, match="baseline reference"):
        validate_workflow(_contract(), _workflow_text(workflow))

    workflow = _workflow()
    assert _step(workflow, VALIDATOR_STEP_NAME)["env"] == {
        BASELINE_ENV: BASELINE_EXPRESSION
    }
    assert _step(workflow, CHECKOUT_STEP_NAME)["uses"] == CHECKOUT_ACTION


def test_filtered_trigger_or_command_drift_is_rejected():
    workflow = _workflow()
    triggers = workflow.get("on", workflow.get(True))
    triggers["pull_request"] = {"paths": ["docs/**"]}
    with pytest.raises(CoverageGateContractError, match="unfiltered"):
        validate_workflow(_contract(), _workflow_text(workflow))

    workflow = _workflow()
    _step(workflow, COVERAGE_STEP_NAME)["run"] = _step(workflow, COVERAGE_STEP_NAME)[
        "run"
    ].replace("--cov-fail-under=90", "--cov-fail-under=89")
    with pytest.raises(CoverageGateContractError, match="coverage test command"):
        validate_workflow(_contract(), _workflow_text(workflow))
