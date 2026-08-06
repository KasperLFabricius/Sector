from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
import tomllib
import yaml

from tools.verify_dependency_audit import (
    BASELINE_ENV,
    BASELINE_EXPRESSION,
    CHECKOUT_ACTION,
    CHECKOUT_STEP,
    EXECUTE_STEP,
    FULL_TEST_STEP,
    INITIAL_REQUIREMENTS,
    INSTALL_STEP,
    PREFLIGHT_STEP,
    PREPARE_STEP,
    SETUP_ACTION,
    SETUP_STEP,
    VALIDATE_STEP,
    DependencyAuditError,
    LockedDependency,
    audit_command,
    execute_policy,
    executor_command,
    lock_inventory,
    parse_lock,
    policy_from_git,
    preflight_command,
    read_policy,
    validate_policy,
    validate_report,
    validate_workflow,
    validator_command,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "quality-dependency-audit.toml"
WORKFLOW = ROOT / ".github" / "workflows" / "qa.yml"
TOOL = ROOT / "tools" / "verify_dependency_audit.py"
HASH = "a" * 64


def _policy():
    return tomllib.loads(POLICY.read_text(encoding="utf-8"))


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _workflow_text(workflow) -> str:
    return yaml.safe_dump(workflow, sort_keys=False)


def _step(workflow, name: str):
    return next(step for step in workflow["jobs"]["test"]["steps"] if step["name"] == name)


def _write_lock(path: Path, *pins: tuple[str, str]) -> None:
    rows = []
    for name, version in pins:
        rows.extend(
            (
                f"{name}=={version} \\",
                f"    --hash=sha256:{HASH}",
            )
        )
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _write_policy(path: Path, requirements: tuple[str, ...] = INITIAL_REQUIREMENTS) -> None:
    requirement_rows = "\n".join(f'    "{item}",' for item in requirements)
    path.write_text(
        "schema_version = 1\n\n"
        "[audit]\n"
        "requirements = [\n"
        f"{requirement_rows}\n"
        "]\n"
        'service = "pypi"\n'
        "strict = true\n"
        "require_hashes = true\n"
        "disable_pip = true\n"
        "isolated_python = true\n"
        'output_format = "json"\n'
        'descriptions = "off"\n'
        'aliases = "on"\n'
        'spinner = "off"\n'
        "timeout_seconds = 15\n"
        'report_path = "qa-artifacts/dependency-audit.json"\n'
        'cache_path = ".qa-cache/pip-audit"\n'
        "ignored_vulnerabilities = []\n",
        encoding="utf-8",
    )


def _temporary_repository(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "repository"
    root.mkdir()
    _write_lock(root / INITIAL_REQUIREMENTS[0], ("alpha", "1.0"), ("shared", "3.0"))
    _write_lock(root / INITIAL_REQUIREMENTS[1], ("beta", "2.0"), ("shared", "3.0"))
    policy_path = root / POLICY.name
    _write_policy(policy_path)
    return root, policy_path


def _report(dependencies: tuple[LockedDependency, ...]) -> dict[str, object]:
    return {
        "dependencies": [
            {"name": item.name, "version": item.version, "vulns": []}
            for item in dependencies
        ],
        "fixes": [],
    }


def test_live_policy_workflow_locks_and_standard_library_preflight_pass():
    policy = validate_policy(_policy(), ROOT)
    dependencies = lock_inventory(policy, ROOT)
    validate_workflow(WORKFLOW.read_text(encoding="utf-8"))

    assert policy.requirements == INITIAL_REQUIREMENTS
    assert LockedDependency("pip-audit", "2.10.1") in dependencies
    assert preflight_command().endswith("--preflight-locks")
    assert validator_command().endswith(
        "--baseline-ref $env:SECTOR_DEPENDENCY_AUDIT_BASE"
    )
    assert executor_command().endswith("--execute")

    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(TOOL),
            str(POLICY),
            "--preflight-locks",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("service", "osv", "service"),
        ("strict", False, "strict"),
        ("require_hashes", False, "require_hashes"),
        ("disable_pip", False, "disable_pip"),
        ("isolated_python", False, "isolated_python"),
        ("output_format", "cyclonedx-json", "output_format"),
        ("descriptions", "auto", "descriptions"),
        ("aliases", "off", "aliases"),
        ("spinner", "on", "spinner"),
        ("timeout_seconds", 30, "timeout_seconds"),
        ("ignored_vulnerabilities", ["PYSEC-1"], "ignored_vulnerabilities"),
    ],
)
def test_policy_security_identity_is_exact(field, value, message):
    policy = deepcopy(_policy())
    policy["audit"][field] = value
    with pytest.raises(DependencyAuditError, match=message):
        validate_policy(policy, ROOT)


def test_unknown_duplicate_escaping_and_colliding_policy_paths_fail(tmp_path):
    policy = deepcopy(_policy())
    policy["unknown"] = True
    with pytest.raises(DependencyAuditError, match="top-level keys"):
        validate_policy(policy, ROOT)

    policy = deepcopy(_policy())
    policy["audit"]["requirements"].append(INITIAL_REQUIREMENTS[0])
    with pytest.raises(DependencyAuditError, match="duplicates"):
        validate_policy(policy, ROOT)

    policy = deepcopy(_policy())
    policy["audit"]["report_path"] = "../outside.json"
    with pytest.raises(DependencyAuditError, match="escapes"):
        validate_policy(policy, tmp_path)

    policy = deepcopy(_policy())
    policy["audit"]["cache_path"] = policy["audit"]["report_path"]
    with pytest.raises(DependencyAuditError, match="collide"):
        validate_policy(policy, ROOT)


def test_accepted_lock_inventory_is_an_exact_prefix():
    accepted = deepcopy(_policy())
    accepted["audit"]["requirements"].append("requirements-extra.txt")
    candidate = deepcopy(accepted)
    candidate["audit"]["requirements"].append("requirements-tail.txt")
    validate_policy(candidate, ROOT, baseline=accepted)

    shrunk = deepcopy(accepted)
    shrunk["audit"]["requirements"].pop()
    with pytest.raises(DependencyAuditError, match="shrank"):
        validate_policy(shrunk, ROOT, baseline=accepted)

    inserted = deepcopy(accepted)
    inserted["audit"]["requirements"].insert(2, "requirements-middle.txt")
    with pytest.raises(DependencyAuditError, match="exact prefix"):
        validate_policy(inserted, ROOT, baseline=accepted)

    reordered = deepcopy(accepted)
    reordered["audit"]["requirements"][1:3] = reversed(
        reordered["audit"]["requirements"][1:3]
    )
    with pytest.raises(DependencyAuditError, match="initial lock identity|exact prefix"):
        validate_policy(reordered, ROOT, baseline=accepted)


@pytest.mark.parametrize(
    "control",
    [
        "--index-url https://example.invalid/simple",
        "--trusted-host example.invalid",
        "-r hidden.txt",
        "--requirement hidden.txt",
        "-c constraints.txt",
        "--constraint constraints.txt",
        "--find-links wheels",
        "--no-index",
    ],
)
@pytest.mark.parametrize("indent", ["", "    ", "\t"])
def test_flush_and_indented_pip_controls_fail_before_install(tmp_path, control, indent):
    path = tmp_path / "lock.txt"
    path.write_text(f"{indent}{control}\n", encoding="utf-8")
    with pytest.raises(DependencyAuditError, match="unsupported lock control"):
        parse_lock(path)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (f"--hash=sha256:{HASH}\n", "orphan hash"),
        ("alpha==1.0 \\\n    --hash=sha256:xyz\n", "malformed SHA-256"),
        (f"    alpha==1.0 \\\n    --hash=sha256:{HASH}\n", "unexpected indented"),
        (f"alpha>=1.0 \\\n    --hash=sha256:{HASH}\n", "exact pinned"),
        ("alpha==1.0\n", "lacks a SHA-256"),
        ("# comments only\n", "lock is empty"),
        (
            f"alpha==1.0 \\\n    --hash=sha256:{HASH}\n"
            f"alpha==1.0 \\\n    --hash=sha256:{HASH}\n",
            "duplicate locked dependency",
        ),
    ],
)
def test_malformed_or_incomplete_lock_surfaces_fail(tmp_path, text, message):
    path = tmp_path / "lock.txt"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(DependencyAuditError, match=message):
        parse_lock(path)


def test_lock_parser_accepts_generated_comments_markers_extras_and_multiple_hashes(tmp_path):
    path = tmp_path / "lock.txt"
    path.write_text(
        "# generated lock\n"
        "alpha[feature]==1.0 ; python_version >= '3.13' \\\n"
        f"    --hash=sha256:{HASH} \\\n"
        f"    --hash=sha256:{'b' * 64}\n"
        "    # via direct input\n",
        encoding="utf-8",
    )
    assert parse_lock(path) == (LockedDependency("alpha", "1.0"),)


def test_cross_lock_union_allows_same_pin_and_rejects_conflicts(tmp_path):
    root, policy_path = _temporary_repository(tmp_path)
    policy = validate_policy(read_policy(policy_path), root)
    assert lock_inventory(policy, root) == (
        LockedDependency("alpha", "1.0"),
        LockedDependency("beta", "2.0"),
        LockedDependency("shared", "3.0"),
    )

    _write_lock(root / INITIAL_REQUIREMENTS[1], ("beta", "2.0"), ("shared", "4.0"))
    with pytest.raises(DependencyAuditError, match="conflicting locked versions"):
        lock_inventory(policy, root)


def test_audit_command_is_one_isolated_exact_process(tmp_path):
    root, policy_path = _temporary_repository(tmp_path)
    policy = validate_policy(read_policy(policy_path), root)
    command = audit_command(policy, root)

    assert command[:4] == [sys.executable, "-I", "-m", "pip_audit"]
    assert command.count("--requirement") == 2
    assert command[-4:] == [
        "--requirement",
        INITIAL_REQUIREMENTS[0],
        "--requirement",
        INITIAL_REQUIREMENTS[1],
    ]
    for required in (
        "--vulnerability-service",
        "pypi",
        "--strict",
        "--require-hashes",
        "--disable-pip",
        "--format",
        "json",
        "--desc",
        "off",
        "--aliases",
        "--progress-spinner",
        "off",
        "--timeout",
        "15",
    ):
        assert required in command
    assert not {"--fix", "--dry-run", "--no-deps", "--ignore-vuln"} & set(command)


def test_complete_clean_report_reproduces_the_canonical_union(tmp_path):
    expected = (
        LockedDependency("alpha", "1.0"),
        LockedDependency("beta", "2.0"),
    )
    report = tmp_path / "report.json"
    report.write_text(json.dumps(_report(expected)), encoding="utf-8")
    validate_report(report, expected)


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda data: data["dependencies"].pop(), "missing"),
        (
            lambda data: data["dependencies"].append(
                {"name": "extra", "version": "1.0", "vulns": []}
            ),
            "extra",
        ),
        (
            lambda data: data["dependencies"][0].update(version="9.0"),
            "changed",
        ),
        (
            lambda data: data["dependencies"].append(deepcopy(data["dependencies"][0])),
            "duplicate audit report",
        ),
        (
            lambda data: data["dependencies"][0]["vulns"].append(
                {"id": "PYSEC-1", "fix_versions": ["2.0"], "aliases": []}
            ),
            "vulnerable dependency",
        ),
        (lambda data: data["fixes"].append({"name": "alpha"}), "fix plan"),
        (lambda data: data.update(skipped=[]), "top-level schema"),
    ],
)
def test_missing_extra_changed_duplicate_vulnerable_and_skipped_reports_fail(
    tmp_path, mutator, message
):
    expected = (
        LockedDependency("alpha", "1.0"),
        LockedDependency("beta", "2.0"),
    )
    payload = _report(expected)
    mutator(payload)
    report = tmp_path / "report.json"
    report.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DependencyAuditError, match=message):
        validate_report(report, expected)


def test_execute_sanitises_environment_and_validates_runner_report(tmp_path, monkeypatch):
    root, policy_path = _temporary_repository(tmp_path)
    evidence = root / "qa-artifacts"
    evidence.mkdir()
    captured = {}
    for name in (
        "PIP_INDEX_URL",
        "PIP_EXTRA_INDEX_URL",
        "PIP_TRUSTED_HOST",
        "PIP_FIND_LINKS",
        "PYTHONPATH",
    ):
        monkeypatch.setenv(name, "attacker-controlled")

    def runner(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        expected = (
            LockedDependency("alpha", "1.0"),
            LockedDependency("beta", "2.0"),
            LockedDependency("shared", "3.0"),
        )
        (evidence / "dependency-audit.json").write_text(
            json.dumps(_report(expected)), encoding="utf-8"
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    execute_policy(policy_path, root, runner=runner)
    environment = captured["kwargs"]["env"]
    assert environment["PIP_CONFIG_FILE"] == os.devnull
    assert environment["PIP_DISABLE_PIP_VERSION_CHECK"] == "1"
    for name in (
        "PIP_INDEX_URL",
        "PIP_EXTRA_INDEX_URL",
        "PIP_TRUSTED_HOST",
        "PIP_FIND_LINKS",
        "PYTHONPATH",
    ):
        assert name not in environment
    assert captured["kwargs"]["cwd"] == root
    assert captured["kwargs"]["check"] is False


def test_execute_refuses_missing_evidence_dir_existing_report_and_runner_failure(tmp_path):
    root, policy_path = _temporary_repository(tmp_path)
    with pytest.raises(DependencyAuditError, match="directory must exist"):
        execute_policy(policy_path, root)

    evidence = root / "qa-artifacts"
    evidence.mkdir()
    report = evidence / "dependency-audit.json"
    report.write_text("{}", encoding="utf-8")
    with pytest.raises(DependencyAuditError, match="already exists"):
        execute_policy(policy_path, root)
    report.unlink()

    def failing(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, "", "collector failed")

    with pytest.raises(DependencyAuditError, match="collector failed"):
        execute_policy(policy_path, root, runner=failing)


def test_policy_is_loaded_from_the_exact_git_base(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    policy_path = repository / POLICY.name
    for command in (
        ["init"],
        ["config", "user.name", "Sector QA"],
        ["config", "user.email", "sector-qa@example.invalid"],
        ["commit", "--allow-empty", "-m", "base without dependency policy"],
    ):
        subprocess.run(
            ["git", *command],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )
    assert policy_from_git("HEAD", policy_path, repository) is None

    _write_policy(policy_path)
    for command in (
        ["add", POLICY.name],
        ["commit", "-m", "accepted dependency policy"],
    ):
        subprocess.run(
            ["git", *command],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )
    loaded = policy_from_git("HEAD", policy_path, repository)
    assert loaded is not None
    assert tuple(loaded["audit"]["requirements"]) == INITIAL_REQUIREMENTS
    with pytest.raises(DependencyAuditError, match="Git baseline inspection"):
        policy_from_git("missing-base", policy_path, repository)


@pytest.mark.parametrize("step_name", [PREFLIGHT_STEP, VALIDATE_STEP, EXECUTE_STEP])
@pytest.mark.parametrize(
    ("field", "value"),
    [("if", "false"), ("continue-on-error", True), ("working-directory", "docs")],
)
def test_dependency_steps_are_unconditional_and_failure_propagating(
    step_name, field, value
):
    workflow = _workflow()
    _step(workflow, step_name)[field] = value
    with pytest.raises(DependencyAuditError, match="skipped or masked"):
        validate_workflow(_workflow_text(workflow))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("if", "false"),
        ("continue-on-error", True),
        ("needs", "windows-package"),
        ("env", {"PIP_TRUSTED_HOST": "example.invalid"}),
    ],
)
def test_test_job_context_cannot_mask_the_gate(field, value):
    workflow = _workflow()
    workflow["jobs"]["test"][field] = value
    with pytest.raises(DependencyAuditError, match="execution context"):
        validate_workflow(_workflow_text(workflow))


def test_workflow_preflight_precedes_install_and_all_owned_steps_have_exact_order():
    workflow = _workflow()
    steps = workflow["jobs"]["test"]["steps"]
    names = [step["name"] for step in steps]
    assert names.index(CHECKOUT_STEP) < names.index(SETUP_STEP)
    assert names.index(SETUP_STEP) < names.index(PREFLIGHT_STEP)
    assert names.index(PREFLIGHT_STEP) < names.index(INSTALL_STEP)
    assert names.index(INSTALL_STEP) < names.index(PREPARE_STEP)
    assert names.index(PREPARE_STEP) < names.index(VALIDATE_STEP)
    assert names.index(VALIDATE_STEP) < names.index(EXECUTE_STEP)
    assert names.index(EXECUTE_STEP) < names.index(FULL_TEST_STEP)

    preflight = steps.pop(names.index(PREFLIGHT_STEP))
    install_index = next(
        index for index, step in enumerate(steps) if step["name"] == INSTALL_STEP
    )
    steps.insert(install_index + 1, preflight)
    with pytest.raises(DependencyAuditError, match="workflow order"):
        validate_workflow(_workflow_text(workflow))


def test_workflow_checkout_setup_triggers_commands_and_install_are_exact():
    workflow = _workflow()
    _step(workflow, CHECKOUT_STEP)["with"]["fetch-depth"] = 1
    with pytest.raises(DependencyAuditError, match="exact Git baseline"):
        validate_workflow(_workflow_text(workflow))

    workflow = _workflow()
    _step(workflow, SETUP_STEP)["uses"] = "actions/setup-python@main"
    with pytest.raises(DependencyAuditError, match="Python setup identity"):
        validate_workflow(_workflow_text(workflow))

    workflow = _workflow()
    _step(workflow, INSTALL_STEP)["run"] += " --trusted-host example.invalid"
    with pytest.raises(DependencyAuditError, match="install can be skipped or weakened"):
        validate_workflow(_workflow_text(workflow))

    workflow = _workflow()
    _step(workflow, VALIDATE_STEP)["env"][BASELINE_ENV] = "HEAD^"
    with pytest.raises(DependencyAuditError, match="baseline expression"):
        validate_workflow(_workflow_text(workflow))

    workflow = _workflow()
    triggers = workflow.get("on", workflow.get(True))
    triggers["pull_request"] = {"paths": ["requirements-*.txt"]}
    with pytest.raises(DependencyAuditError, match="unfiltered"):
        validate_workflow(_workflow_text(workflow))

    workflow = _workflow()
    assert _step(workflow, CHECKOUT_STEP)["uses"] == CHECKOUT_ACTION
    assert _step(workflow, SETUP_STEP)["uses"] == SETUP_ACTION
    assert _step(workflow, VALIDATE_STEP)["env"] == {
        BASELINE_ENV: BASELINE_EXPRESSION
    }
