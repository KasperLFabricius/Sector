from __future__ import annotations

import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
import tomllib
import yaml

from tools.verify_ruff_policy import (
    BASELINE_ENV,
    BASELINE_EXPRESSION,
    CHECKOUT_ACTION,
    CHECKOUT_STEP,
    EXECUTE_STEP,
    RUFF_SAFETY_OPTIONS,
    VALIDATE_STEP,
    RuffPolicyError,
    execute_policy,
    executor_command,
    policy_from_git,
    scope_command,
    validate_policy,
    validate_workflow,
    validator_command,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "quality-ruff-policy.toml"
WORKFLOW = ROOT / ".github" / "workflows" / "qa.yml"


def _policy():
    return tomllib.loads(POLICY.read_text(encoding="utf-8"))


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _workflow_text(workflow) -> str:
    return yaml.safe_dump(workflow, sort_keys=False)


def _step(workflow, name: str):
    return next(step for step in workflow["jobs"]["test"]["steps"] if step["name"] == name)


def _scope(policy, scope_id: str):
    return next(scope for scope in policy["scopes"] if scope["id"] == scope_id)


def _temporary_repository(tmp_path: Path, broken_source: str) -> Path:
    repository = tmp_path / "repository"
    for directory in ("app", "sector", "tools", "tests"):
        (repository / directory).mkdir(parents=True, exist_ok=True)
    (repository / "app" / "broken.py").write_text(broken_source, encoding="utf-8")
    (repository / "sector" / "capacity.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repository / "tests" / "test_capacity.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repository / "tests" / "test_project_io.py").write_text("VALUE = 1\n", encoding="utf-8")
    return repository


def test_live_policy_workflow_and_all_scopes_pass():
    policy = _policy()
    validate_policy(policy, ROOT)
    validate_workflow(WORKFLOW.read_text(encoding="utf-8"))
    execute_policy(policy, ROOT)

    command = scope_command(policy["scopes"][0])
    assert command[:5] == ["ruff", "check", *RUFF_SAFETY_OPTIONS]
    assert command[-2:] == ["--select", "E9,F63,F7,F82"]
    assert validator_command().endswith(
        "--baseline-ref $env:SECTOR_RUFF_POLICY_BASE"
    )
    assert executor_command().endswith("--execute")


@pytest.mark.parametrize(
    "broken_source",
    [
        "def broken():\n    return missing_name  # noqa: F821\n",
        "# ruff: noqa\ndef broken():\n    return missing_name\n",
        "# flake8: noqa\ndef broken():\n    return missing_name\n",
    ],
)
def test_source_noqa_cannot_suppress_a_ratcheted_finding(tmp_path, broken_source):
    repository = _temporary_repository(tmp_path, broken_source)

    with pytest.raises(RuffPolicyError, match="runtime-errors"):
        execute_policy(_policy(), repository)


def test_repository_config_cannot_suppress_a_ratcheted_finding(tmp_path):
    repository = _temporary_repository(
        tmp_path,
        "def broken():\n    return missing_name\n",
    )
    (repository / "ruff.toml").write_text(
        '[lint.per-file-ignores]\n"app/broken.py" = ["F821"]\n',
        encoding="utf-8",
    )

    with pytest.raises(RuffPolicyError, match="runtime-errors"):
        execute_policy(_policy(), repository)


def test_gitignore_cannot_hide_a_scoped_file(tmp_path):
    repository = _temporary_repository(
        tmp_path,
        "def broken():\n    return missing_name\n",
    )
    (repository / ".gitignore").write_text("app/broken.py\n", encoding="utf-8")
    subprocess.run(
        ["git", "init"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )

    with pytest.raises(RuffPolicyError, match="runtime-errors"):
        execute_policy(_policy(), repository)


def test_accepted_scope_path_selector_and_order_ratchets():
    baseline = deepcopy(_policy())
    capacity = _scope(baseline, "capacity-typed-boundary")
    capacity["paths"].append("sector/bridge.py")
    capacity["select"].append("UP")

    candidate = deepcopy(baseline)
    candidate["scopes"].pop(0)
    with pytest.raises(RuffPolicyError, match="initial Ruff scope"):
        validate_policy(candidate, ROOT, baseline=baseline)

    candidate = deepcopy(baseline)
    _scope(candidate, "capacity-typed-boundary")["paths"].remove("sector/bridge.py")
    with pytest.raises(RuffPolicyError, match="paths shrank"):
        validate_policy(candidate, ROOT, baseline=baseline)

    candidate = deepcopy(baseline)
    _scope(candidate, "capacity-typed-boundary")["select"].remove("UP")
    with pytest.raises(RuffPolicyError, match="selectors shrank"):
        validate_policy(candidate, ROOT, baseline=baseline)

    candidate = deepcopy(baseline)
    candidate["scopes"][0], candidate["scopes"][1] = candidate["scopes"][1], candidate["scopes"][0]
    with pytest.raises(RuffPolicyError, match="scope identity or order"):
        validate_policy(candidate, ROOT, baseline=baseline)

    candidate = deepcopy(baseline)
    paths = _scope(candidate, "capacity-typed-boundary")["paths"]
    paths[0], paths[1] = paths[1], paths[0]
    with pytest.raises(RuffPolicyError, match="path order"):
        validate_policy(candidate, ROOT, baseline=baseline)

    candidate = deepcopy(baseline)
    selectors = _scope(candidate, "capacity-typed-boundary")["select"]
    selectors[0], selectors[1] = selectors[1], selectors[0]
    with pytest.raises(RuffPolicyError, match="selector order"):
        validate_policy(candidate, ROOT, baseline=baseline)


def test_ignored_rule_cannot_expand_and_waiver_can_expire():
    baseline = deepcopy(_policy())
    candidate = deepcopy(baseline)
    scope = _scope(candidate, "project-io-test-boundary")
    scope["select"].append("UP")
    scope["ignore"].append("UP")
    candidate["waivers"].append(
        {
            "id": "temporary-up-ignore",
            "scope": "project-io-test-boundary",
            "code": "UP",
            "owner": "quality owner",
            "reason": "controlled mutation",
            "exit_condition": "remove after repair",
        }
    )
    with pytest.raises(RuffPolicyError, match="ignores expanded"):
        validate_policy(
            candidate,
            ROOT,
            baseline=baseline,
            current_waivers={"project-io-bootstrap-e402", "temporary-up-ignore"},
        )

    candidate = deepcopy(baseline)
    _scope(candidate, "project-io-test-boundary")["ignore"] = []
    candidate["waivers"] = []
    validate_policy(candidate, ROOT, baseline=baseline, current_waivers=set())


@pytest.mark.parametrize("field", ["owner", "reason", "exit_condition"])
def test_waiver_identity_owner_reason_and_exit_are_required(field):
    candidate = deepcopy(_policy())
    candidate["waivers"][0][field] = ""

    with pytest.raises(RuffPolicyError, match=field):
        validate_policy(candidate, ROOT)


def test_unknown_duplicate_missing_escaping_and_unowned_values_fail(tmp_path):
    candidate = deepcopy(_policy())
    candidate["unknown"] = True
    with pytest.raises(RuffPolicyError, match="top-level keys"):
        validate_policy(candidate, ROOT)

    candidate = deepcopy(_policy())
    candidate["scopes"].append(deepcopy(candidate["scopes"][0]))
    with pytest.raises(RuffPolicyError, match="duplicate Ruff scope"):
        validate_policy(candidate, ROOT)

    candidate = deepcopy(_policy())
    _scope(candidate, "runtime-errors")["select"] = []
    with pytest.raises(RuffPolicyError, match="non-empty text list"):
        validate_policy(candidate, ROOT)

    candidate = deepcopy(_policy())
    candidate["waivers"] = []
    with pytest.raises(RuffPolicyError, match="owned waiver"):
        validate_policy(candidate, ROOT, current_waivers=set())

    repository = tmp_path / "repository"
    repository.mkdir()
    candidate = deepcopy(_policy())
    _scope(candidate, "runtime-errors")["paths"][0] = "../outside"
    with pytest.raises(RuffPolicyError, match="escapes the repository"):
        validate_policy(candidate, repository)


def test_policy_is_loaded_from_the_exact_git_base(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    candidate_path = repository / POLICY.name
    for command in (
        ["init"],
        ["config", "user.name", "Sector QA"],
        ["config", "user.email", "sector-qa@example.invalid"],
        ["commit", "--allow-empty", "-m", "base without Ruff policy"],
    ):
        subprocess.run(
            ["git", *command],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )
    assert policy_from_git("HEAD", candidate_path, repository) is None

    candidate_path.write_text(POLICY.read_text(encoding="utf-8"), encoding="utf-8")
    for command in (
        ["add", POLICY.name],
        ["commit", "-m", "accepted Ruff policy"],
    ):
        subprocess.run(
            ["git", *command],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )
    loaded = policy_from_git("HEAD", candidate_path, repository)
    assert loaded is not None
    assert [scope["id"] for scope in loaded["scopes"]] == list(
        ("runtime-errors", "capacity-typed-boundary", "project-io-test-boundary")
    )
    with pytest.raises(RuffPolicyError, match="Git baseline inspection"):
        policy_from_git("missing-base", candidate_path, repository)


@pytest.mark.parametrize("step_name", [VALIDATE_STEP, EXECUTE_STEP])
@pytest.mark.parametrize(
    ("field", "value"),
    [("if", "false"), ("continue-on-error", True), ("working-directory", "docs")],
)
def test_policy_steps_are_unconditional_and_failure_propagating(step_name, field, value):
    workflow = _workflow()
    _step(workflow, step_name)[field] = value

    with pytest.raises(RuffPolicyError, match="skipped or masked"):
        validate_workflow(_workflow_text(workflow))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("if", "false"),
        ("continue-on-error", True),
        ("needs", "windows-package"),
        ("env", {"RUFF_OUTPUT_FORMAT": "concise"}),
    ],
)
def test_test_job_context_cannot_mask_the_policy(field, value):
    workflow = _workflow()
    workflow["jobs"]["test"][field] = value

    with pytest.raises(RuffPolicyError, match="test job execution context"):
        validate_workflow(_workflow_text(workflow))


def test_checkout_baseline_triggers_and_commands_are_exact():
    workflow = _workflow()
    _step(workflow, CHECKOUT_STEP)["with"]["fetch-depth"] = 1
    with pytest.raises(RuffPolicyError, match="fetch the accepted"):
        validate_workflow(_workflow_text(workflow))

    workflow = _workflow()
    _step(workflow, CHECKOUT_STEP)["uses"] = "actions/checkout@main"
    with pytest.raises(RuffPolicyError, match="fetch the accepted"):
        validate_workflow(_workflow_text(workflow))

    workflow = _workflow()
    _step(workflow, VALIDATE_STEP)["env"][BASELINE_ENV] = "HEAD^"
    with pytest.raises(RuffPolicyError, match="baseline expression"):
        validate_workflow(_workflow_text(workflow))

    workflow = _workflow()
    triggers = workflow.get("on", workflow.get(True))
    triggers["pull_request"] = {"paths": ["sector/**"]}
    with pytest.raises(RuffPolicyError, match="unfiltered"):
        validate_workflow(_workflow_text(workflow))

    workflow = _workflow()
    _step(workflow, EXECUTE_STEP)["run"] += " --exit-zero"
    with pytest.raises(RuffPolicyError, match="executor command"):
        validate_workflow(_workflow_text(workflow))

    workflow = _workflow()
    assert _step(workflow, VALIDATE_STEP)["env"] == {
        BASELINE_ENV: BASELINE_EXPRESSION
    }
    assert _step(workflow, CHECKOUT_STEP)["uses"] == CHECKOUT_ACTION
