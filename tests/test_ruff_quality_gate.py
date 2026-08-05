from __future__ import annotations

import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
import tomllib
import yaml

from tools.verify_ruff_gate import (
    BASELINE_ENV,
    BASELINE_EXPRESSION,
    CHECKOUT_ACTION,
    CHECKOUT_STEP_NAME,
    RUFF_STEP_NAME,
    VALIDATOR_STEP_NAME,
    RuffGateContractError,
    command_arguments,
    expected_runner_command,
    expected_validator_command,
    load_git_baseline,
    run_checks,
    validate_contract,
    validate_workflow,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "quality-ruff-gate.toml"
WORKFLOW = ROOT / ".github" / "workflows" / "qa.yml"


def _contract():
    return tomllib.loads(CONTRACT.read_text(encoding="utf-8"))


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _workflow_text(data) -> str:
    return yaml.safe_dump(data, sort_keys=False)


def _step(workflow, name: str):
    return next(step for step in workflow["jobs"]["test"]["steps"] if step["name"] == name)


def _scope(data, scope_id: str):
    return next(scope for scope in data["scopes"] if scope["id"] == scope_id)


def test_exact_contract_workflow_and_commands_are_aligned():
    data = _contract()
    validate_contract(data, ROOT)
    validate_workflow(WORKFLOW.read_text(encoding="utf-8"))

    assert expected_validator_command().endswith(
        "--baseline-ref $env:SECTOR_RUFF_BASELINE_REF"
    )
    assert expected_runner_command().endswith("--run-checks")
    assert command_arguments(data["scopes"][0]) == [
        "check",
        "--isolated",
        "app",
        "sector",
        "tools",
        "tests",
        "--select",
        "E9,F63,F7,F82",
    ]
    assert command_arguments(data["scopes"][2])[-2:] == ["--ignore", "E402"]


def test_current_ratcheted_ruff_scopes_pass():
    data = _contract()
    validate_contract(data, ROOT)
    run_checks(data, ROOT)


def test_controlled_ruff_finding_fails_the_runner(tmp_path):
    repository = tmp_path / "repository"
    for relative in ("app", "sector", "tools", "tests"):
        (repository / relative).mkdir(parents=True, exist_ok=True)
    (repository / "sector" / "capacity.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repository / "tests" / "test_capacity.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repository / "tests" / "test_project_io.py").write_text(
        "VALUE = 1\n", encoding="utf-8"
    )
    (repository / "app" / "broken.py").write_text(
        "def broken():\n    return missing_name\n", encoding="utf-8"
    )
    (repository / "ruff.toml").write_text(
        '[lint.per-file-ignores]\n"app/broken.py" = ["F821"]\n',
        encoding="utf-8",
    )

    with pytest.raises(RuffGateContractError, match="repository-runtime-errors"):
        run_checks(_contract(), repository)


def test_accepted_scopes_paths_and_selectors_cannot_shrink():
    baseline = deepcopy(_contract())
    _scope(baseline, "capacity-boundary")["paths"].append("sector/bridge.py")
    _scope(baseline, "capacity-boundary")["select"].append("UP")

    candidate = deepcopy(baseline)
    candidate["scopes"].pop(0)
    with pytest.raises(RuffGateContractError, match="initial Ruff scope"):
        validate_contract(candidate, ROOT, baseline=baseline)

    candidate = deepcopy(baseline)
    _scope(candidate, "capacity-boundary")["paths"].remove("sector/bridge.py")
    with pytest.raises(RuffGateContractError, match="accepted Ruff paths"):
        validate_contract(candidate, ROOT, baseline=baseline)

    candidate = deepcopy(baseline)
    _scope(candidate, "capacity-boundary")["select"].remove("UP")
    with pytest.raises(RuffGateContractError, match="accepted Ruff selectors"):
        validate_contract(candidate, ROOT, baseline=baseline)

    candidate = deepcopy(baseline)
    paths = _scope(candidate, "capacity-boundary")["paths"]
    paths[0], paths[1] = paths[1], paths[0]
    with pytest.raises(RuffGateContractError, match="path order"):
        validate_contract(candidate, ROOT, baseline=baseline)

    candidate = deepcopy(baseline)
    selectors = _scope(candidate, "capacity-boundary")["select"]
    selectors[0], selectors[1] = selectors[1], selectors[0]
    with pytest.raises(RuffGateContractError, match="selector order"):
        validate_contract(candidate, ROOT, baseline=baseline)

    candidate = deepcopy(baseline)
    candidate["scopes"][0], candidate["scopes"][1] = (
        candidate["scopes"][1],
        candidate["scopes"][0],
    )
    with pytest.raises(RuffGateContractError, match="scope order"):
        validate_contract(candidate, ROOT, baseline=baseline)


def test_accepted_ignores_cannot_expand_and_can_expire():
    baseline = deepcopy(_contract())
    candidate = deepcopy(baseline)
    project_scope = _scope(candidate, "project-io-boundary")
    project_scope["select"].append("UP")
    project_scope["ignore"].append("UP")
    candidate["waivers"].append(
        {
            "id": "ruff-project-io-up",
            "gate": "ruff",
            "scope": "project-io-boundary",
            "code": "UP",
            "owner": "quality owner",
            "reason": "controlled mutation",
            "exit_condition": "remove after migration",
        }
    )
    with pytest.raises(RuffGateContractError, match="ignores expanded"):
        validate_contract(
            candidate,
            ROOT,
            baseline=baseline,
            candidate_waiver_ids={"ruff-project-io-e402", "ruff-project-io-up"},
        )

    candidate = deepcopy(baseline)
    _scope(candidate, "project-io-boundary")["ignore"] = []
    candidate["waivers"] = []
    validate_contract(
        candidate,
        ROOT,
        baseline=baseline,
        candidate_waiver_ids=set(),
    )


@pytest.mark.parametrize("field", ["owner", "reason", "exit_condition"])
def test_waiver_retains_owner_reason_and_exit(field):
    data = deepcopy(_contract())
    data["waivers"][0][field] = ""

    with pytest.raises(RuffGateContractError, match=field):
        validate_contract(data, ROOT)


def test_ignored_rules_require_exact_owned_waivers():
    data = deepcopy(_contract())
    data["waivers"] = []
    with pytest.raises(RuffGateContractError, match="owned waiver"):
        validate_contract(data, ROOT, candidate_waiver_ids=set())

    data = deepcopy(_contract())
    data["waivers"][0]["scope"] = "capacity-boundary"
    with pytest.raises(RuffGateContractError, match="does not own"):
        validate_contract(data, ROOT)

    data = deepcopy(_contract())
    data["waivers"][0]["gate"] = "mypy"
    with pytest.raises(RuffGateContractError, match="wrong gate"):
        validate_contract(data, ROOT)


def test_duplicate_missing_unknown_and_escaping_fields_are_rejected(tmp_path):
    data = deepcopy(_contract())
    data["unknown"] = True
    with pytest.raises(RuffGateContractError, match="top-level contract keys"):
        validate_contract(data, ROOT)

    data = deepcopy(_contract())
    data["scopes"].append(deepcopy(data["scopes"][0]))
    with pytest.raises(RuffGateContractError, match="duplicate Ruff scope"):
        validate_contract(data, ROOT)

    data = deepcopy(_contract())
    _scope(data, "capacity-boundary")["select"] = []
    with pytest.raises(RuffGateContractError, match="non-empty text list"):
        validate_contract(data, ROOT)

    repository = tmp_path / "repository"
    repository.mkdir()
    data = deepcopy(_contract())
    _scope(data, "repository-runtime-errors")["paths"][0] = "../outside"
    with pytest.raises(RuffGateContractError, match="escapes the repository"):
        validate_contract(data, repository)


def test_git_baseline_is_loaded_from_the_accepted_object(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    candidate_contract = repository / CONTRACT.name
    for arguments in (
        ["init"],
        ["config", "user.name", "Sector QA"],
        ["config", "user.email", "sector-qa@example.invalid"],
        ["commit", "--allow-empty", "-m", "accepted base without Ruff contract"],
    ):
        subprocess.run(
            ["git", *arguments],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )
    assert load_git_baseline("HEAD", candidate_contract, repository) is None

    candidate_contract.write_text(CONTRACT.read_text(encoding="utf-8"), encoding="utf-8")
    for arguments in (
        ["add", CONTRACT.name],
        ["commit", "-m", "accepted Ruff baseline"],
    ):
        subprocess.run(
            ["git", *arguments],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )
    loaded = load_git_baseline("HEAD", candidate_contract, repository)
    assert loaded is not None
    assert [scope["id"] for scope in loaded["scopes"]] == [
        "repository-runtime-errors",
        "capacity-boundary",
        "project-io-boundary",
    ]
    with pytest.raises(RuffGateContractError, match="git baseline inspection"):
        load_git_baseline("missing-accepted-ref", candidate_contract, repository)


@pytest.mark.parametrize("step_name", [VALIDATOR_STEP_NAME, RUFF_STEP_NAME])
@pytest.mark.parametrize(
    ("field", "value"),
    [("if", "false"), ("continue-on-error", True), ("working-directory", "docs")],
)
def test_gate_steps_cannot_be_skipped_or_made_non_propagating(
    step_name, field, value
):
    workflow = _workflow()
    _step(workflow, step_name)[field] = value

    with pytest.raises(
        RuffGateContractError, match="unconditional and failure-propagating"
    ):
        validate_workflow(_workflow_text(workflow))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("if", "false"),
        ("continue-on-error", True),
        ("needs", "windows-package"),
        ("env", {"RUFF_NO_CACHE": "1"}),
    ],
)
def test_test_job_cannot_be_skipped_or_made_non_propagating(field, value):
    workflow = _workflow()
    workflow["jobs"]["test"][field] = value

    with pytest.raises(
        RuffGateContractError, match="unconditional failure-propagating context"
    ):
        validate_workflow(_workflow_text(workflow))


def test_checkout_history_baseline_trigger_and_command_identity_are_pinned():
    workflow = _workflow()
    _step(workflow, CHECKOUT_STEP_NAME)["with"]["fetch-depth"] = 1
    with pytest.raises(RuffGateContractError, match="fetch history"):
        validate_workflow(_workflow_text(workflow))

    workflow = _workflow()
    _step(workflow, CHECKOUT_STEP_NAME)["uses"] = "actions/checkout@main"
    with pytest.raises(RuffGateContractError, match="fetch history"):
        validate_workflow(_workflow_text(workflow))

    workflow = _workflow()
    _step(workflow, VALIDATOR_STEP_NAME)["env"][BASELINE_ENV] = "HEAD^"
    with pytest.raises(RuffGateContractError, match="baseline reference"):
        validate_workflow(_workflow_text(workflow))

    workflow = _workflow()
    triggers = workflow.get("on", workflow.get(True))
    triggers["pull_request"] = {"paths": ["docs/**"]}
    with pytest.raises(RuffGateContractError, match="unfiltered"):
        validate_workflow(_workflow_text(workflow))

    workflow = _workflow()
    _step(workflow, RUFF_STEP_NAME)["run"] += " --exit-zero"
    with pytest.raises(RuffGateContractError, match="runner command"):
        validate_workflow(_workflow_text(workflow))

    workflow = _workflow()
    assert _step(workflow, VALIDATOR_STEP_NAME)["env"] == {
        BASELINE_ENV: BASELINE_EXPRESSION
    }
    assert _step(workflow, CHECKOUT_STEP_NAME)["uses"] == CHECKOUT_ACTION
