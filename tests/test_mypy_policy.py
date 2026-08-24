from __future__ import annotations

import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
import tomllib
import yaml

from tools.verify_mypy_policy import (
    BASELINE_ENV,
    BASELINE_EXPRESSION,
    CHECKOUT_ACTION,
    CHECKOUT_STEP,
    EXECUTE_STEP,
    INITIAL_FILES,
    LEGACY_INITIAL_FILES,
    VALIDATE_STEP,
    MypyPolicyError,
    execute_policy,
    executor_command,
    policy_from_git,
    validate_policy,
    validate_workflow,
    validator_command,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "quality-mypy-policy.toml"
WORKFLOW = ROOT / ".github" / "workflows" / "qa.yml"
TYPED_BOUNDARY_FILES = (
    *INITIAL_FILES,
    "sector/design_standards.py",
    "app/modelled_direction.py",
    "sector/heightened_crack_control.py",
    "app/publication_equation_layout.py",
)


def _policy():
    return tomllib.loads(POLICY.read_text(encoding="utf-8"))


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _workflow_text(workflow) -> str:
    return yaml.safe_dump(workflow, sort_keys=False)


def _step(workflow, name: str):
    return next(step for step in workflow["jobs"]["test"]["steps"] if step["name"] == name)


def _write_policy(path: Path, files: tuple[str, ...] = INITIAL_FILES) -> None:
    file_rows = "\n".join(f'    "{item}",' for item in files)
    path.write_text(
        "[tool.mypy]\n"
        'python_version = "3.13"\n'
        "strict = true\n"
        'follow_imports = "silent"\n'
        "incremental = false\n"
        "files = [\n"
        f"{file_rows}\n"
        "]\n\n"
        "[sector_policy]\n"
        "schema_version = 1\n\n"
        "[[sector_policy.waivers]]\n"
        'id = "mypy-imported-module-debt"\n'
        'setting = "follow_imports"\n'
        'value = "silent"\n'
        'owner = "type owner"\n'
        'reason = "imported debt"\n'
        'exit_condition = "strengthen imports"\n',
        encoding="utf-8",
    )


def _temporary_repository(tmp_path: Path, owned_source: str) -> tuple[Path, Path]:
    repository = tmp_path / "repository"
    for relative in INITIAL_FILES:
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("VALUE: int = 1\n", encoding="utf-8")
    (repository / INITIAL_FILES[0]).write_text(
        owned_source,
        encoding="utf-8",
    )
    policy_path = repository / POLICY.name
    _write_policy(policy_path)
    return repository, policy_path


def test_live_strict_policy_workflow_and_boundaries_pass():
    policy = _policy()
    validate_policy(policy, ROOT)
    validate_workflow(WORKFLOW.read_text(encoding="utf-8"))
    execute_policy(POLICY, ROOT)

    assert tuple(policy["tool"]["mypy"]["files"]) == TYPED_BOUNDARY_FILES
    assert policy["tool"]["mypy"] == {
        "python_version": "3.13",
        "strict": True,
        "follow_imports": "silent",
        "incremental": False,
        "files": list(TYPED_BOUNDARY_FILES),
    }
    assert validator_command().endswith(
        "--baseline-ref $env:SECTOR_MYPY_POLICY_BASE"
    )
    assert executor_command().endswith("--execute")


def test_controlled_return_type_error_fails_strict_mypy(tmp_path):
    repository, policy_path = _temporary_repository(
        tmp_path,
        'def broken() -> int:\n    return "not an integer"\n',
    )

    with pytest.raises(MypyPolicyError, match="return-value"):
        execute_policy(policy_path, repository)


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            'def broken() -> int:\n    return "text"  # type: ignore[return-value]\n',
            "type: ignore",
        ),
        (
            '# mypy: ignore-errors\ndef broken() -> int:\n    return "text"\n',
            "file-level mypy",
        ),
        (
            '# mypy: disable-error-code="return-value"\n'
            'def broken() -> int:\n    return "text"\n',
            "file-level mypy",
        ),
    ],
)
def test_source_suppressions_cannot_weaken_owned_boundaries(tmp_path, source, message):
    repository, policy_path = _temporary_repository(tmp_path, source)
    policy = tomllib.loads(policy_path.read_text(encoding="utf-8"))

    with pytest.raises(MypyPolicyError, match=message):
        validate_policy(policy, repository)


@pytest.mark.parametrize(
    "source",
    [
        (
            "import typing\n\n"
            "@typing.no_type_check\n"
            'def broken() -> int:\n    return "text"\n'
        ),
        (
            "import typing as type_api\n\n"
            "@type_api.no_type_check\n"
            'def broken() -> int:\n    return "text"\n'
        ),
        (
            "from typing import no_type_check\n\n"
            "@no_type_check\n"
            'def broken() -> int:\n    return "text"\n'
        ),
        (
            "from typing_extensions import no_type_check as unchecked\n\n"
            "@unchecked\n"
            'def broken() -> int:\n    return "text"\n'
        ),
        (
            "import typing\n"
            "unchecked = typing.no_type_check\n\n"
            "@unchecked\n"
            'def broken() -> int:\n    return "text"\n'
        ),
    ],
)
def test_no_type_check_decorators_cannot_weaken_owned_boundaries(tmp_path, source):
    repository, policy_path = _temporary_repository(tmp_path, source)
    policy = tomllib.loads(policy_path.read_text(encoding="utf-8"))

    with pytest.raises(MypyPolicyError, match="no_type_check decorator"):
        validate_policy(policy, repository)


def test_unrelated_no_type_check_words_are_inert(tmp_path):
    source = (
        'LABEL = "@typing.no_type_check"\n\n'
        "def no_type_check(function):\n    return function\n\n"
        "@no_type_check\n"
        "def retained() -> int:\n    return 1\n"
    )
    repository, policy_path = _temporary_repository(tmp_path, source)
    policy = tomllib.loads(policy_path.read_text(encoding="utf-8"))

    validate_policy(policy, repository)


def test_unknown_or_weaker_mypy_settings_are_rejected():
    policy = deepcopy(_policy())
    policy["tool"]["mypy"]["ignore_missing_imports"] = True
    with pytest.raises(MypyPolicyError, match="setting inventory"):
        validate_policy(policy, ROOT)

    policy = deepcopy(_policy())
    policy["tool"]["mypy"]["strict"] = False
    with pytest.raises(MypyPolicyError, match="strict mypy"):
        validate_policy(policy, ROOT)

    policy = deepcopy(_policy())
    policy["tool"]["mypy"]["incremental"] = True
    with pytest.raises(MypyPolicyError, match="incremental cache"):
        validate_policy(policy, ROOT)

    policy = deepcopy(_policy())
    policy["tool"]["mypy"]["follow_imports"] = "skip"
    with pytest.raises(MypyPolicyError, match="unsupported or weaker"):
        validate_policy(policy, ROOT)


def test_accepted_file_inventory_and_order_cannot_shrink():
    baseline = deepcopy(_policy())
    baseline["tool"]["mypy"]["files"].append("sector/capacity.py")

    candidate = deepcopy(baseline)
    candidate["tool"]["mypy"]["files"].remove("sector/capacity.py")
    with pytest.raises(MypyPolicyError, match="inventory shrank"):
        validate_policy(candidate, ROOT, baseline=baseline)

    candidate = deepcopy(baseline)
    files = candidate["tool"]["mypy"]["files"]
    files[0], files[1] = files[1], files[0]
    with pytest.raises(MypyPolicyError, match="initial typed boundary"):
        validate_policy(candidate, ROOT, baseline=baseline)


def test_deleted_legacy_boundary_is_migrated_only_for_the_accepted_base():
    baseline = deepcopy(_policy())
    baseline["tool"]["mypy"]["files"][: len(LEGACY_INITIAL_FILES)] = (
        LEGACY_INITIAL_FILES
    )

    validate_policy(_policy(), ROOT, baseline=baseline)

    candidate = deepcopy(_policy())
    candidate["tool"]["mypy"]["files"][: len(LEGACY_INITIAL_FILES)] = (
        LEGACY_INITIAL_FILES
    )
    with pytest.raises(MypyPolicyError, match="typed boundary file does not exist"):
        validate_policy(candidate, ROOT, baseline=baseline)


@pytest.mark.parametrize(
    "owned_file",
    (
        "sector/design_standards.py",
        "sector/heightened_crack_control.py",
    ),
)
def test_live_crack_boundaries_cannot_leave_the_typed_boundary(
    owned_file: str,
):
    policy = deepcopy(_policy())
    assert tuple(policy["tool"]["mypy"]["files"]) == TYPED_BOUNDARY_FILES

    candidate = deepcopy(policy)
    candidate["tool"]["mypy"]["files"].remove(owned_file)
    with pytest.raises(MypyPolicyError, match="inventory shrank"):
        validate_policy(candidate, ROOT, baseline=policy)


def test_follow_imports_can_strengthen_and_waiver_can_expire():
    baseline = deepcopy(_policy())
    candidate = deepcopy(baseline)
    candidate["tool"]["mypy"]["follow_imports"] = "normal"
    candidate["sector_policy"]["waivers"] = []

    validate_policy(candidate, ROOT, baseline=baseline, current_waivers=set())

    weakened = deepcopy(candidate)
    weakened["tool"]["mypy"]["follow_imports"] = "silent"
    weakened["sector_policy"]["waivers"] = deepcopy(
        baseline["sector_policy"]["waivers"]
    )
    with pytest.raises(MypyPolicyError, match="accepted baseline"):
        validate_policy(
            weakened,
            ROOT,
            baseline=candidate,
            current_waivers={"mypy-imported-module-debt"},
        )


@pytest.mark.parametrize("field", ["owner", "reason", "exit_condition"])
def test_import_debt_waiver_retains_owner_reason_and_exit(field):
    policy = deepcopy(_policy())
    policy["sector_policy"]["waivers"][0][field] = ""

    with pytest.raises(MypyPolicyError, match=field):
        validate_policy(policy, ROOT)


def test_missing_duplicate_escaping_and_mismatched_values_fail(tmp_path):
    policy = deepcopy(_policy())
    policy["unknown"] = True
    with pytest.raises(MypyPolicyError, match="top-level keys"):
        validate_policy(policy, ROOT)

    policy = deepcopy(_policy())
    policy["tool"]["mypy"]["files"].append(INITIAL_FILES[0])
    with pytest.raises(MypyPolicyError, match="duplicates"):
        validate_policy(policy, ROOT)

    policy = deepcopy(_policy())
    policy["sector_policy"]["waivers"][0]["value"] = "normal"
    with pytest.raises(MypyPolicyError, match="weakened setting"):
        validate_policy(policy, ROOT)

    repository = tmp_path / "repository"
    repository.mkdir()
    policy = deepcopy(_policy())
    policy["tool"]["mypy"]["files"][0] = "../outside.py"
    with pytest.raises(MypyPolicyError, match="escapes the repository"):
        validate_policy(policy, repository)


def test_policy_is_loaded_from_the_exact_git_base(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    candidate_path = repository / POLICY.name
    for command in (
        ["init"],
        ["config", "user.name", "Sector QA"],
        ["config", "user.email", "sector-qa@example.invalid"],
        ["commit", "--allow-empty", "-m", "base without mypy policy"],
    ):
        subprocess.run(
            ["git", *command],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )
    assert policy_from_git("HEAD", candidate_path, repository) is None

    _write_policy(candidate_path)
    for command in (
        ["add", POLICY.name],
        ["commit", "-m", "accepted mypy policy"],
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
    assert tuple(loaded["tool"]["mypy"]["files"]) == INITIAL_FILES
    with pytest.raises(MypyPolicyError, match="Git baseline inspection"):
        policy_from_git("missing-base", candidate_path, repository)


@pytest.mark.parametrize("step_name", [VALIDATE_STEP, EXECUTE_STEP])
@pytest.mark.parametrize(
    ("field", "value"),
    [("if", "false"), ("continue-on-error", True), ("working-directory", "docs")],
)
def test_policy_steps_are_unconditional_and_failure_propagating(step_name, field, value):
    workflow = _workflow()
    _step(workflow, step_name)[field] = value

    with pytest.raises(MypyPolicyError, match="skipped or masked"):
        validate_workflow(_workflow_text(workflow))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("if", "false"),
        ("continue-on-error", True),
        ("needs", "windows-package"),
        ("env", {"MYPYPATH": "typings"}),
    ],
)
def test_test_job_context_cannot_mask_the_policy(field, value):
    workflow = _workflow()
    workflow["jobs"]["test"][field] = value

    with pytest.raises(MypyPolicyError, match="test job execution context"):
        validate_workflow(_workflow_text(workflow))


def test_checkout_baseline_triggers_and_commands_are_exact():
    workflow = _workflow()
    _step(workflow, CHECKOUT_STEP)["with"]["fetch-depth"] = 1
    with pytest.raises(MypyPolicyError, match="fetch the accepted"):
        validate_workflow(_workflow_text(workflow))

    workflow = _workflow()
    _step(workflow, CHECKOUT_STEP)["uses"] = "actions/checkout@main"
    with pytest.raises(MypyPolicyError, match="fetch the accepted"):
        validate_workflow(_workflow_text(workflow))

    workflow = _workflow()
    _step(workflow, VALIDATE_STEP)["env"][BASELINE_ENV] = "HEAD^"
    with pytest.raises(MypyPolicyError, match="baseline expression"):
        validate_workflow(_workflow_text(workflow))

    workflow = _workflow()
    triggers = workflow.get("on", workflow.get(True))
    triggers["pull_request"] = {"paths": ["app/**"]}
    with pytest.raises(MypyPolicyError, match="unfiltered"):
        validate_workflow(_workflow_text(workflow))

    workflow = _workflow()
    _step(workflow, EXECUTE_STEP)["run"] += " --ignore-missing-imports"
    with pytest.raises(MypyPolicyError, match="executor command"):
        validate_workflow(_workflow_text(workflow))

    workflow = _workflow()
    assert _step(workflow, VALIDATE_STEP)["env"] == {
        BASELINE_ENV: BASELINE_EXPRESSION
    }
    assert _step(workflow, CHECKOUT_STEP)["uses"] == CHECKOUT_ACTION
