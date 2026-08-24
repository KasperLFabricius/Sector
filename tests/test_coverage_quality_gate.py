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
    BRANCH_COVERAGE_STEP_NAME,
    CHECKOUT_ACTION,
    CHECKOUT_STEP_NAME,
    COVERAGE_STEP_NAME,
    MANUAL_RENDER_COMMAND,
    MANUAL_RENDER_STEP_NAME,
    QA_UPLOAD_ACTION,
    QA_UPLOAD_SETTINGS,
    QA_UPLOAD_STEP_NAME,
    REPORT_RENDER_COMMAND,
    REPORT_RENDER_STEP_NAME,
    VALIDATOR_STEP_NAME,
    CoverageGateContractError,
    expected_branch_coverage_command,
    expected_coverage_command,
    expected_validator_command,
    load_git_baseline,
    validate_contract,
    validate_results,
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
    command = expected_coverage_command(data)
    branch_command = expected_branch_coverage_command(data)

    assert expected_validator_command().endswith(
        "--baseline-ref $env:SECTOR_COVERAGE_BASELINE_REF"
    )
    assert "--dist loadgroup" in command
    assert '-m "not real_image_export"' in command
    assert "--basetemp $coreTemp" in command
    assert command.count("-n 0") == 3
    assert command.count("--cov-append") == 3
    assert "--cov-branch" not in command
    assert "--cov=app" in command
    assert "--cov=sector" in command
    assert "coverage report --show-missing --skip-covered --fail-under=90" in command
    assert "--dist load" in branch_command
    assert branch_command.count("--cov-branch") == 1
    assert "--results qa-artifacts/branch-coverage.json" in branch_command
    assert len(data["branch_coverage"]["targets"]) == 6
    assert len(data["branch_coverage"]["tests"]) == 6
    assert data["coverage"]["minimum_percent"] == 90
    assert data["branch_coverage"]["minimum_percent"] == 81
    assert data["waivers"] == []


def test_raised_accepted_floor_and_targets_cannot_shrink():
    baseline = deepcopy(_contract())
    baseline["coverage"]["minimum_percent"] = 93
    baseline["branch_coverage"]["minimum_percent"] = 84
    baseline["coverage"]["targets"].append("docs")

    candidate = deepcopy(baseline)
    candidate["coverage"]["minimum_percent"] = 92
    with pytest.raises(CoverageGateContractError, match="line minimum.*previously"):
        validate_contract(candidate, ROOT, baseline=baseline)

    candidate = deepcopy(baseline)
    candidate["branch_coverage"]["minimum_percent"] = 83
    with pytest.raises(CoverageGateContractError, match="branch minimum.*previously"):
        validate_contract(candidate, ROOT, baseline=baseline)

    candidate = deepcopy(baseline)
    candidate["coverage"]["targets"].remove("docs")
    with pytest.raises(CoverageGateContractError, match="accepted coverage target"):
        validate_contract(candidate, ROOT, baseline=baseline)

    candidate = deepcopy(baseline)
    candidate["branch_coverage"]["targets"].pop()
    with pytest.raises(CoverageGateContractError, match="branch target ratchet"):
        validate_contract(candidate, ROOT, baseline=baseline)

    candidate = deepcopy(baseline)
    candidate["branch_coverage"]["tests"].pop()
    with pytest.raises(CoverageGateContractError, match="branch test ratchet"):
        validate_contract(candidate, ROOT, baseline=baseline)


@pytest.mark.parametrize(
    ("field", "minimum"),
    [
        ("line", 49),
        ("line", 89),
        ("line", True),
        ("line", 50.5),
        ("line", 101),
        ("branch", 49),
        ("branch", 80),
        ("branch", True),
        ("branch", 50.5),
        ("branch", 101),
    ],
)
def test_invalid_initial_floor_is_rejected(field, minimum):
    data = deepcopy(_contract())
    section = "coverage" if field == "line" else "branch_coverage"
    data[section]["minimum_percent"] = minimum

    with pytest.raises(CoverageGateContractError, match="coverage .* minimum"):
        validate_contract(data, ROOT)


def _results(*, branches: int, branch_total: int):
    files = {}
    for module in _contract()["branch_coverage"]["targets"]:
        relative = f"{module.replace('.', '/')}.py"
        if not (ROOT / relative).is_file():
            relative = f"app/{relative}"
        files[relative] = {}
    return {
        "files": files,
        "totals": {
            "covered_branches": branches,
            "num_branches": branch_total,
        }
    }


def test_measured_decision_branch_floor_is_enforced():
    measured = validate_results(
        _contract(),
        _results(branches=810, branch_total=1000),
        ROOT,
    )
    assert measured == pytest.approx(81.0)

    with pytest.raises(CoverageGateContractError, match="branch coverage 80.90%"):
        validate_results(
            _contract(),
            _results(branches=809, branch_total=1000),
            ROOT,
        )


def test_every_declared_branch_target_must_appear_in_results():
    results = _results(branches=1000, branch_total=1000)
    results["files"].pop(next(iter(results["files"])))
    with pytest.raises(CoverageGateContractError, match="target results are missing"):
        validate_results(_contract(), results, ROOT)


@pytest.mark.parametrize(
    "results",
    [
        _results(branches=0, branch_total=0),
        _results(branches=2, branch_total=1),
        {"files": {}, "totals": {"covered_branches": "all"}},
        {"files": {}},
        {},
    ],
)
def test_missing_or_invalid_measurement_cannot_pass(results):
    with pytest.raises(CoverageGateContractError, match="coverage|branch"):
        validate_results(_contract(), results, ROOT)


def test_duplicate_missing_and_escaping_targets_are_rejected():
    data = deepcopy(_contract())
    data["coverage"]["targets"].append("app")
    with pytest.raises(CoverageGateContractError, match="duplicates"):
        validate_contract(data, ROOT)

    data = deepcopy(_contract())
    data["coverage"]["targets"].remove("sector")
    with pytest.raises(CoverageGateContractError, match="initial coverage target"):
        validate_contract(data, ROOT)

    data = deepcopy(_contract())
    data["branch_coverage"]["targets"].append(
        data["branch_coverage"]["targets"][0]
    )
    with pytest.raises(CoverageGateContractError, match="duplicates"):
        validate_contract(data, ROOT)

    data = deepcopy(_contract())
    data["branch_coverage"]["targets"][0] = "not/a/module"
    with pytest.raises(CoverageGateContractError, match="invalid module"):
        validate_contract(data, ROOT)

    data = deepcopy(_contract())
    data["coverage"]["targets"][0] = "../outside"
    with pytest.raises(CoverageGateContractError, match="escapes the repository"):
        validate_contract(data, ROOT)


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
    data["branch_coverage"].pop("minimum_percent")
    with pytest.raises(CoverageGateContractError, match="branch coverage contract"):
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
    baseline["schema_version"] = 1
    baseline["coverage"] = {
        "targets": ["app", "sector"],
        "minimum_percent": 50,
    }
    baseline.pop("branch_coverage")
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
    with pytest.raises(CoverageGateContractError, match="line minimum.*previously"):
        validate_contract(_contract(), ROOT, baseline=baseline)
    with pytest.raises(CoverageGateContractError, match="git baseline inspection"):
        load_git_baseline("missing-accepted-ref", candidate_contract, repository)


@pytest.mark.parametrize(
    "step_name",
    [VALIDATOR_STEP_NAME, COVERAGE_STEP_NAME, BRANCH_COVERAGE_STEP_NAME],
)
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
    ].replace("--fail-under=90", "--fail-under=89")
    with pytest.raises(CoverageGateContractError, match="coverage test command"):
        validate_workflow(_contract(), _workflow_text(workflow))

    workflow = _workflow()
    _step(workflow, BRANCH_COVERAGE_STEP_NAME)["run"] = _step(
        workflow, BRANCH_COVERAGE_STEP_NAME
    )["run"].replace("--cov-branch", "", 1)
    with pytest.raises(CoverageGateContractError, match="branch coverage command"):
        validate_workflow(_contract(), _workflow_text(workflow))


def test_real_render_and_upload_evidence_identity_is_pinned():
    workflow = _workflow()

    assert _step(workflow, REPORT_RENDER_STEP_NAME) == {
        "name": REPORT_RENDER_STEP_NAME,
        "if": "always()",
        "run": REPORT_RENDER_COMMAND,
    }
    assert _step(workflow, MANUAL_RENDER_STEP_NAME) == {
        "name": MANUAL_RENDER_STEP_NAME,
        "if": "always()",
        "run": MANUAL_RENDER_COMMAND,
    }
    assert _step(workflow, QA_UPLOAD_STEP_NAME) == {
        "name": QA_UPLOAD_STEP_NAME,
        "if": "always()",
        "uses": QA_UPLOAD_ACTION,
        "with": QA_UPLOAD_SETTINGS,
    }


@pytest.mark.parametrize(
    ("step_name", "mutation"),
    [
        (REPORT_RENDER_STEP_NAME, "remove"),
        (REPORT_RENDER_STEP_NAME, "rename"),
        (REPORT_RENDER_STEP_NAME, "mask"),
        (REPORT_RENDER_STEP_NAME, "destination"),
        (MANUAL_RENDER_STEP_NAME, "remove"),
        (MANUAL_RENDER_STEP_NAME, "rename"),
        (MANUAL_RENDER_STEP_NAME, "mask"),
        (MANUAL_RENDER_STEP_NAME, "destination"),
    ],
)
def test_real_render_evidence_mutations_are_rejected(step_name, mutation):
    workflow = _workflow()
    steps = workflow["jobs"]["test"]["steps"]
    step = _step(workflow, step_name)
    if mutation == "remove":
        steps.remove(step)
    elif mutation == "rename":
        step["name"] += " renamed"
    elif mutation == "mask":
        step["if"] = "success()"
    else:
        step["run"] = step["run"].replace("qa-artifacts/", "temporary/")

    with pytest.raises(CoverageGateContractError, match="evidence|contain one"):
        validate_workflow(_contract(), _workflow_text(workflow))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("if", "success()"),
        ("uses", "actions/upload-artifact@main"),
        ("with", {**QA_UPLOAD_SETTINGS, "path": "qa-artifacts/report/"}),
    ],
)
def test_complete_qa_artifact_upload_cannot_be_masked_or_narrowed(field, value):
    workflow = _workflow()
    _step(workflow, QA_UPLOAD_STEP_NAME)[field] = value

    with pytest.raises(CoverageGateContractError, match="evidence upload"):
        validate_workflow(_contract(), _workflow_text(workflow))
