"""Validate Sector's non-shrinking coverage gate and workflow placement."""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import tomllib
import yaml

ROOT = Path(__file__).resolve().parents[1]
INITIAL_TARGETS = {"app", "sector"}
INITIAL_MINIMUM_LINE_PERCENT = 50
FINAL_MINIMUM_LINE_PERCENT = 90
INITIAL_MINIMUM_BRANCH_PERCENT = 50
FINAL_MINIMUM_BRANCH_PERCENT = 81
REQUIRED_WAIVER_IDS: set[str] = set()
VALIDATOR_STEP_NAME = "Validate non-shrinking coverage gate"
COVERAGE_STEP_NAME = "Run complete test suite with coverage"
BRANCH_COVERAGE_STEP_NAME = "Run decision-branch coverage gate"
CHECKOUT_STEP_NAME = "Check out source"
CHECKOUT_ACTION = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
QA_UPLOAD_STEP_NAME = "Upload QA diagnostics"
QA_UPLOAD_ACTION = (
    "actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9"
)
QA_UPLOAD_SETTINGS = {
    "name": "sector-qa-${{ github.run_id }}",
    "path": "qa-artifacts/",
    "if-no-files-found": "error",
    "retention-days": 7,
    "include-hidden-files": True,
}
BASELINE_ENV = "SECTOR_COVERAGE_BASELINE_REF"
BASELINE_EXPRESSION = (
    "${{ github.event.pull_request.base.sha || github.event.before || 'HEAD^' }}"
)
BRANCH_RESULTS_PATH = "qa-artifacts/branch-coverage.json"


class CoverageGateContractError(ValueError):
    """Raised when the coverage contract or its execution context is unsafe."""


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CoverageGateContractError(f"{label} must be non-empty text")
    return value.strip()


def _strings(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise CoverageGateContractError(f"{label} must be a non-empty text list")
    result = [_text(item, label) for item in value]
    if len(result) != len(set(result)):
        raise CoverageGateContractError(f"{label} contains duplicates")
    return result


def _paths(value: object, label: str, repository_root: Path) -> list[str]:
    paths = _strings(value, label)
    root = repository_root.resolve()
    for relative in paths:
        candidate = (root / relative).resolve()
        if candidate != root and root not in candidate.parents:
            raise CoverageGateContractError(f"{label} escapes the repository")
        if not candidate.exists():
            raise CoverageGateContractError(f"{label} does not exist: {relative}")
    return paths


def _branch_tests(value: object, repository_root: Path) -> list[str]:
    """Keep complete files or all parameters of an existing test function."""
    label = "branch_coverage.tests"
    selections = _strings(value, label)
    if selections != value:
        raise CoverageGateContractError(f"{label} must use exact test selections")
    parsed: list[tuple[Path, str | None]] = []
    for selection in selections:
        parts = selection.split("::")
        module = parts[0]
        if len(parts) > 2 or re.fullmatch(
            r"tests/(?:[A-Za-z0-9_]+/)*test_[A-Za-z0-9_]+\.py", module
        ) is None:
            raise CoverageGateContractError(f"{label} has an invalid test selection")
        _paths([module], label, repository_root)
        module_path = (repository_root / module).resolve()
        if not module_path.is_file():
            raise CoverageGateContractError(f"{label} must select a test module")
        function = parts[1] if len(parts) == 2 else None
        if function is not None and re.fullmatch(r"test_[A-Za-z0-9_]+", function) is None:
            raise CoverageGateContractError(
                f"{label} must select a whole top-level test function"
            )
        parsed.append((module_path, function))
    # Path equality follows the platform, including Windows case aliases.
    identities = set(parsed)
    if len(identities) != len(parsed):
        raise CoverageGateContractError(f"{label} has duplicate physical test selections")
    for module_path, function in parsed:
        if function is None:
            continue
        if (module_path, None) in identities:
            raise CoverageGateContractError(f"{label} has overlapping test selections")
        try:
            tree = ast.parse(module_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, SyntaxError) as exc:
            raise CoverageGateContractError(f"{label} cannot read test module") from exc
        definitions = [
            node for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == function
        ]
        if len(definitions) != 1:
            raise CoverageGateContractError(
                f"{label} must name one existing top-level test function"
            )
    return selections


def _coverage_modules(
    value: object, label: str, repository_root: Path
) -> dict[str, str]:
    modules = _strings(value, label)
    root = repository_root.resolve()
    resolved: dict[str, str] = {}
    for module in modules:
        if any(not part.isidentifier() for part in module.split(".")):
            raise CoverageGateContractError(f"{label} has an invalid module: {module}")
        candidates = [root / f"{module.replace('.', '/')}.py"]
        if "." not in module:
            candidates.extend((root / "app" / f"{module}.py", root / "sector" / f"{module}.py"))
        existing = [candidate for candidate in candidates if candidate.is_file()]
        if len(existing) != 1:
            raise CoverageGateContractError(
                f"{label} must resolve each module to one source file: {module}"
            )
        resolved[module] = existing[0].relative_to(root).as_posix()
    return resolved


def _minimum_percentage(value: object, label: str, initial: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CoverageGateContractError(f"{label} must be an integer")
    if value < initial:
        raise CoverageGateContractError(f"{label} may not fall below {initial}")
    if value > 100:
        raise CoverageGateContractError(f"{label} may not exceed 100")
    return value


def _snapshot(
    data: Mapping[str, Any],
    repository_root: Path,
    *,
    required_waiver_ids: set[str] | None,
    require_branch: bool,
) -> tuple[set[str], int, set[str] | None, set[str] | None, int | None]:
    schema_version = data.get("schema_version")
    coverage = data.get("coverage")
    if not isinstance(coverage, Mapping):
        raise CoverageGateContractError("coverage contract is incomplete")
    if schema_version == 1:
        if set(data) != {"schema_version", "coverage", "waivers"}:
            raise CoverageGateContractError("legacy top-level contract keys differ")
        if require_branch:
            raise CoverageGateContractError(
                "schema_version 2 is required for branch coverage"
            )
        if set(coverage) != {"targets", "minimum_percent"}:
            raise CoverageGateContractError("legacy coverage contract is incomplete")
        line_minimum = _minimum_percentage(
            coverage.get("minimum_percent"),
            "coverage line minimum",
            INITIAL_MINIMUM_LINE_PERCENT,
        )
        branch_targets = None
        branch_tests = None
        branch_minimum = None
    elif schema_version == 2:
        if set(data) != {
            "schema_version",
            "coverage",
            "branch_coverage",
            "waivers",
        }:
            raise CoverageGateContractError("top-level contract keys differ")
        if set(coverage) != {"targets", "minimum_percent"}:
            raise CoverageGateContractError("coverage contract is incomplete")
        line_minimum = _minimum_percentage(
            coverage.get("minimum_percent"),
            "coverage line minimum",
            INITIAL_MINIMUM_LINE_PERCENT,
        )
        branch = data.get("branch_coverage")
        if not isinstance(branch, Mapping) or set(branch) != {
            "targets",
            "tests",
            "minimum_percent",
        }:
            raise CoverageGateContractError("branch coverage contract is incomplete")
        branch_targets = set(
            _coverage_modules(
                branch.get("targets"),
                "branch_coverage.targets",
                repository_root,
            )
        )
        branch_tests = set(
            _branch_tests(
                branch.get("tests"),
                repository_root,
            )
        )
        if any(not test.startswith("tests/") for test in branch_tests):
            raise CoverageGateContractError(
                "branch coverage tests must remain under tests/"
            )
        branch_minimum = _minimum_percentage(
            branch.get("minimum_percent"),
            "coverage branch minimum",
            INITIAL_MINIMUM_BRANCH_PERCENT,
        )
    else:
        raise CoverageGateContractError("unsupported coverage schema_version")

    targets = set(_paths(coverage["targets"], "coverage.targets", repository_root))
    if not INITIAL_TARGETS <= targets:
        raise CoverageGateContractError("initial coverage target inventory shrank")

    waivers = data.get("waivers")
    if not isinstance(waivers, list):
        raise CoverageGateContractError("waivers must be an array")
    waiver_ids: set[str] = set()
    for index, waiver in enumerate(waivers):
        if not isinstance(waiver, Mapping) or set(waiver) != {
            "id",
            "gate",
            "owner",
            "reason",
            "exit_condition",
        }:
            raise CoverageGateContractError(f"waivers[{index}] is incomplete")
        waiver_id = _text(waiver.get("id"), f"waivers[{index}].id")
        if waiver_id in waiver_ids:
            raise CoverageGateContractError(f"duplicate waiver: {waiver_id}")
        waiver_ids.add(waiver_id)
        if _text(waiver.get("gate"), f"waivers[{index}].gate") != "coverage":
            raise CoverageGateContractError(f"{waiver_id} has the wrong gate")
        for key in ("owner", "reason", "exit_condition"):
            _text(waiver.get(key), f"waivers[{index}].{key}")
    if required_waiver_ids is not None and waiver_ids != required_waiver_ids:
        raise CoverageGateContractError("coverage waiver inventory differs")
    return (
        targets,
        line_minimum,
        branch_targets,
        branch_tests,
        branch_minimum,
    )


def validate_contract(
    data: Mapping[str, Any],
    repository_root: Path = ROOT,
    *,
    baseline: Mapping[str, Any] | None = None,
    candidate_waiver_ids: set[str] | None = None,
) -> None:
    required_waiver_ids = (
        REQUIRED_WAIVER_IDS
        if candidate_waiver_ids is None
        else candidate_waiver_ids
    )
    (
        targets,
        line_minimum,
        branch_targets,
        branch_tests,
        branch_minimum,
    ) = _snapshot(
        data,
        repository_root,
        required_waiver_ids=required_waiver_ids,
        require_branch=True,
    )
    if line_minimum < FINAL_MINIMUM_LINE_PERCENT:
        raise CoverageGateContractError(
            "coverage line minimum may not fall below final accepted "
            f"{FINAL_MINIMUM_LINE_PERCENT}"
        )
    if (
        branch_targets is None
        or branch_tests is None
        or branch_minimum is None
        or branch_minimum < FINAL_MINIMUM_BRANCH_PERCENT
    ):
        raise CoverageGateContractError(
            "coverage branch minimum may not fall below final accepted "
            f"{FINAL_MINIMUM_BRANCH_PERCENT}"
        )
    if baseline is None:
        return
    (
        baseline_targets,
        baseline_line_minimum,
        baseline_branch_targets,
        baseline_branch_tests,
        baseline_branch_minimum,
    ) = _snapshot(
        baseline,
        repository_root,
        required_waiver_ids=None,
        require_branch=False,
    )
    if not baseline_targets <= targets:
        raise CoverageGateContractError("accepted coverage target ratchet shrank")
    if line_minimum < baseline_line_minimum:
        raise CoverageGateContractError(
            "coverage line minimum fell below the previously accepted baseline"
        )
    if (
        baseline_branch_targets is not None
        and not baseline_branch_targets <= branch_targets
    ):
        raise CoverageGateContractError("accepted branch target ratchet shrank")
    if (
        baseline_branch_tests is not None
        and not baseline_branch_tests <= branch_tests
    ):
        raise CoverageGateContractError("accepted branch test ratchet shrank")
    if (
        baseline_branch_minimum is not None
        and branch_minimum < baseline_branch_minimum
    ):
        raise CoverageGateContractError(
            "coverage branch minimum fell below the previously accepted baseline"
        )


def _parse_toml(text: str, label: str) -> dict[str, Any]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise CoverageGateContractError(f"cannot parse {label}: {exc}") from exc
    return data


def _read_contract(path: Path) -> dict[str, Any]:
    try:
        return _parse_toml(path.read_text(encoding="utf-8"), str(path))
    except OSError as exc:
        raise CoverageGateContractError(f"cannot read contract: {exc}") from exc


def _read_results(path: Path) -> Mapping[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CoverageGateContractError(f"cannot read coverage results: {exc}") from exc
    if not isinstance(data, Mapping):
        raise CoverageGateContractError("coverage results must be a mapping")
    return data


def _coverage_counter(totals: Mapping[str, Any], key: str) -> int:
    value = totals.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CoverageGateContractError(f"coverage results {key} is invalid")
    return value


def validate_results(
    data: Mapping[str, Any], results: Mapping[str, Any], repository_root: Path = ROOT
) -> float:
    """Enforce the decision-module branch floor from Coverage.py JSON output."""

    _, _, branch_targets, _, branch_minimum = _snapshot(
        data,
        repository_root,
        required_waiver_ids=REQUIRED_WAIVER_IDS,
        require_branch=True,
    )
    if branch_targets is None or branch_minimum is None:
        raise CoverageGateContractError("coverage branch minimum is missing")
    files = results.get("files")
    if not isinstance(files, Mapping):
        raise CoverageGateContractError("coverage result file inventory is missing")
    measured_targets = {
        str(path).replace("\\", "/")
        for path in files
    }
    expected_target_files = set(
        _coverage_modules(
            sorted(branch_targets),
            "branch_coverage.targets",
            repository_root,
        ).values()
    )
    if not expected_target_files <= measured_targets:
        missing = sorted(expected_target_files - measured_targets)
        raise CoverageGateContractError(
            f"branch coverage target results are missing: {', '.join(missing)}"
        )
    totals = results.get("totals")
    if not isinstance(totals, Mapping):
        raise CoverageGateContractError("coverage results totals are missing")

    branches = _coverage_counter(totals, "num_branches")
    covered_branches = _coverage_counter(totals, "covered_branches")
    if branches == 0 or covered_branches > branches:
        raise CoverageGateContractError(
            "branch measurement is absent or its totals are invalid"
        )

    branch_percent = 100.0 * covered_branches / branches
    if branch_percent + 1e-12 < branch_minimum:
        raise CoverageGateContractError(
            f"branch coverage {branch_percent:.2f}% is below {branch_minimum}%"
        )
    return branch_percent


def _git(
    repository_root: Path, arguments: Sequence[str]
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", "-C", str(repository_root), *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise CoverageGateContractError(f"git baseline inspection failed: {detail}")
    return completed


def load_git_baseline(
    baseline_ref: str, contract_path: Path, repository_root: Path = ROOT
) -> dict[str, Any] | None:
    reference = _text(baseline_ref, "baseline_ref")
    root = repository_root.resolve()
    try:
        relative = contract_path.resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise CoverageGateContractError("contract path escapes the repository") from exc
    _git(root, ["cat-file", "-e", f"{reference}^{{commit}}"])
    listed = _git(root, ["ls-tree", "--name-only", reference, "--", relative])
    if relative not in listed.stdout.splitlines():
        return None
    object_name = f"{reference}:{relative}"
    content = _git(root, ["show", object_name]).stdout
    return _parse_toml(content, object_name)


def expected_validator_command() -> str:
    return (
        "python tools/verify_coverage_gate.py quality-coverage-gate.toml "
        "--workflow .github/workflows/qa.yml "
        "--baseline-ref $env:SECTOR_COVERAGE_BASELINE_REF"
    )



# The balanced core and decision-branch shards and the serial real-image
# shard of tools/qa_core_shards.py; the merge proves their completeness.
CORE_SHARDS = (
    *(f"core-{index:02d}" for index in range(1, 13)),
    *(f"branch-{index:02d}" for index in range(1, 5)),
    "real",
)
CORE_DOWNLOAD_STEP_NAME = "Download exact core shard evidence"
CORE_DOWNLOAD_ACTION = "actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333"
CORE_DOWNLOAD_SETTINGS = {
    # Every attempt of this run: a rerun of failed jobs keeps the evidence of
    # the shards that did not run again (tools/qa_core_shards.py select_artifacts).
    "pattern": "sector-core-${{ github.run_id }}-*",
    "path": "qa-core-inputs",
    "merge-multiple": False,
}
# The preflight and core jobs restore one locked environment. A miss installs it
# from the hash-locked file, and the preflight job saves it. The key changes with
# the exact Python pin and the lock file. The test job keeps its own locked
# install, which the dependency audit policy requires.
CACHE_RESTORE_ACTION = "actions/cache/restore@55cc8345863c7cc4c66a329aec7e433d2d1c52a9"
CACHE_SAVE_ACTION = "actions/cache/save@55cc8345863c7cc4c66a329aec7e433d2d1c52a9"
# The cache holds the installed packages of the pinned toolcache interpreter, so
# `python` stays the real interpreter. A venv is not used: on Windows its
# python.exe is a launcher that starts the interpreter as a child process, and a
# test that stops a child process with terminate() then sees a late release.
QA_ENV_PATH = "${{ env.pythonLocation }}/Lib/site-packages\n${{ env.pythonLocation }}/Scripts\n"
QA_ENV_KEY = (
    "sector-qa-env-v2-${{ runner.os }}-${{ runner.arch }}-${{ steps.python.outputs.python-path }}-"
    "${{ hashFiles('.python-version', 'requirements-dev.txt') }}"
)
QA_ENV_HIT = "steps.qa_env.outputs.cache-hit == 'true'"
QA_ENV_MISS = "steps.qa_env.outputs.cache-hit != 'true'"
QA_ENV_CLEAR = (
    'foreach ($folder in @("$env:pythonLocation\\Lib\\site-packages", "$env:pythonLocation\\Scripts")) '
    "{ if (Test-Path $folder) { Remove-Item -Recurse -Force $folder } }"
)
# Hang limits of the shard step (owner rule, 9 November 2026): the real-image
# shard normally takes 7 min, the longest core shard about 23 min.
CORE_STEP_TIMEOUT = "${{ matrix.shard == 'real' && 20 || 60 }}"


def _environment_steps(*, save: bool) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = [
        {"name": "Look up cached QA environment", "id": "qa_env", "uses": CACHE_RESTORE_ACTION,
         "with": {"path": QA_ENV_PATH, "key": QA_ENV_KEY, "lookup-only": True}},
        {"name": "Clear base packages for the cached QA environment", "if": QA_ENV_HIT, "run": QA_ENV_CLEAR},
        {"name": "Restore cached QA environment", "if": QA_ENV_HIT, "uses": CACHE_RESTORE_ACTION,
         "with": {"path": QA_ENV_PATH, "key": "${{ steps.qa_env.outputs.cache-primary-key }}",
                  "fail-on-cache-miss": True}},
        {"name": "Install locked QA environment", "if": QA_ENV_MISS,
         "run": "python -m pip install --require-hashes -r requirements-dev.txt"},
    ]
    if save:
        steps.append({"name": "Save cached QA environment", "if": QA_ENV_MISS, "uses": CACHE_SAVE_ACTION,
                      "with": {"path": QA_ENV_PATH, "key": "${{ steps.qa_env.outputs.cache-primary-key }}"}})
    return steps


def _setup_steps() -> list[dict[str, Any]]:
    return [
        {"name": CHECKOUT_STEP_NAME, "uses": CHECKOUT_ACTION, "with": {"fetch-depth": 0}},
        {"name": "Set up pinned Python", "id": "python",
         "uses": "actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0",
         "with": {"python-version-file": ".python-version", "cache": "pip", "cache-dependency-path": "requirements-dev.txt"}},
        {"name": "Preflight locked dependency inputs",
         "run": "python tools/verify_dependency_audit.py quality-dependency-audit.toml --preflight-locks"},
    ]


def expected_core_job() -> dict[str, Any]:
    return {
        "name": "Primary pytest (${{ matrix.shard }})",
        "needs": "preflight",
        "runs-on": "windows-latest",
        "timeout-minutes": 120,
        "strategy": {"fail-fast": False, "matrix": {"shard": list(CORE_SHARDS)}},
        "steps": [
            *_setup_steps(),
            *_environment_steps(save=False),
            {"name": "Run complete primary shard", "timeout-minutes": CORE_STEP_TIMEOUT,
             "run": 'python tools/qa_core_shards.py run --shard "${{ matrix.shard }}" --output qa-shard'},
            {"name": "Upload raw primary shard evidence", "if": "always()", "uses": QA_UPLOAD_ACTION,
             "with": {"name": "sector-core-${{ github.run_id }}-${{ github.run_attempt }}-${{ matrix.shard }}",
                      "path": "qa-shard/", "include-hidden-files": True, "if-no-files-found": "error", "retention-days": 7}},
        ],
    }


def expected_preflight_job() -> dict[str, Any]:
    return {
        "name": "Fast source preflight",
        "runs-on": "windows-latest",
        "timeout-minutes": 15,
        "steps": [*_setup_steps(), *_environment_steps(save=True), {
            "name": "Run fast source contracts",
            "run": "python -m pytest tests/test_ascii_only.py tests/test_real_image_export_policy.py -n 0 -q",
        }],
    }


def expected_coverage_command(data: Mapping[str, Any]) -> str:
    coverage = data["coverage"]
    return f'''$ErrorActionPreference = "Stop"
$phaseFailures = @()
if ("${{{{ steps.core_download.outcome }}}}" -ne "success") {{
  $phaseFailures += "core artifact download"
}}
if ("${{{{ needs.core.result }}}}" -ne "success") {{
  $phaseFailures += "primary jobs (${{{{ needs.core.result }}}})"
}}

python tools/qa_core_shards.py merge --input qa-core-inputs --output qa-artifacts
$phaseExit = $LASTEXITCODE
if ($phaseExit -ne 0) {{
  $phaseFailures += "parallel test shards ($phaseExit)"
}}

python -m coverage xml -o qa-artifacts/coverage.xml
$phaseExit = $LASTEXITCODE
if ($phaseExit -ne 0) {{
  $phaseFailures += "coverage XML ($phaseExit)"
}}

python -m coverage report --show-missing --skip-covered --fail-under={coverage['minimum_percent']}
$phaseExit = $LASTEXITCODE
if ($phaseExit -ne 0) {{
  $phaseFailures += "coverage floor ($phaseExit)"
}}

if ($phaseFailures.Count -gt 0) {{
  throw "QA phases failed: $($phaseFailures -join ', ')"
}}
'''


def expected_branch_coverage_command(data: Mapping[str, Any]) -> str:
    # The branch shards run data["branch_coverage"]["tests"]; the merge
    # writes the combined Coverage.py JSON results that this step enforces.
    return f'''$ErrorActionPreference = "Stop"
python tools/verify_coverage_gate.py quality-coverage-gate.toml --results {BRANCH_RESULTS_PATH}
if ($LASTEXITCODE -ne 0) {{
  throw "Decision-branch coverage floor failed ($LASTEXITCODE)"
}}
'''


def _workflow_mapping(workflow_text: str) -> Mapping[str, Any]:
    try:
        workflow = yaml.safe_load(workflow_text)
    except yaml.YAMLError as exc:
        raise CoverageGateContractError(f"cannot parse workflow YAML: {exc}") from exc
    if not isinstance(workflow, Mapping):
        raise CoverageGateContractError("workflow must be a mapping")
    return workflow


def _named_step(steps: object, name: str) -> Mapping[str, Any]:
    if not isinstance(steps, list):
        raise CoverageGateContractError("test job steps must be an array")
    matches = [
        step
        for step in steps
        if isinstance(step, Mapping) and step.get("name") == name
    ]
    if len(matches) != 1:
        raise CoverageGateContractError(f"workflow must contain one {name!r} step")
    return matches[0]


def validate_workflow(data: Mapping[str, Any], workflow_text: str) -> None:
    workflow = _workflow_mapping(workflow_text)
    triggers = workflow.get("on", workflow.get(True))
    if not isinstance(triggers, Mapping) or set(triggers) != {
        "pull_request",
        "push",
        "workflow_dispatch",
    }:
        raise CoverageGateContractError("workflow trigger inventory differs")
    if triggers.get("pull_request") is not None:
        raise CoverageGateContractError("pull_request trigger must remain unfiltered")
    if triggers.get("workflow_dispatch") is not None:
        raise CoverageGateContractError("workflow_dispatch trigger must remain unfiltered")
    if triggers.get("push") != {"branches": ["main"]}:
        raise CoverageGateContractError("push trigger must cover all main changes")

    jobs = workflow.get("jobs")
    if not isinstance(jobs, Mapping):
        raise CoverageGateContractError("workflow jobs must be a mapping")
    test_job = jobs.get("test")
    if not isinstance(test_job, Mapping) or set(test_job) != {
        "name",
        "runs-on",
        "timeout-minutes",
        "steps",
        "needs",
        "if",
    } or test_job.get("needs") != "core" or test_job.get("if") != "always()":
        raise CoverageGateContractError(
            "test job must retain an unconditional failure-propagating context"
        )
    if jobs.get("preflight") != expected_preflight_job():
        raise CoverageGateContractError("fast preflight execution contract differs")
    if jobs.get("core") != expected_core_job():
        raise CoverageGateContractError("core shard execution or evidence contract differs")
    portable = jobs.get("portable")
    if not isinstance(portable, Mapping) or portable.get("needs") != ["core", "test"]:
        raise CoverageGateContractError("portable must require every core shard and the complete aggregate gate")
    if "if" in portable or "continue-on-error" in portable:
        raise CoverageGateContractError("portable prerequisite failure cannot be masked")
    steps = test_job["steps"]

    checkout = _named_step(steps, CHECKOUT_STEP_NAME)
    if (
        set(checkout) != {"name", "uses", "with"}
        or checkout.get("uses") != CHECKOUT_ACTION
        or checkout.get("with") != {"fetch-depth": 0}
    ):
        raise CoverageGateContractError(
            "test checkout must fetch history for the accepted baseline"
        )

    validator = _named_step(steps, VALIDATOR_STEP_NAME)
    if set(validator) != {"name", "env", "run"}:
        raise CoverageGateContractError(
            "coverage validator step must be unconditional and failure-propagating"
        )
    if validator.get("env") != {BASELINE_ENV: BASELINE_EXPRESSION}:
        raise CoverageGateContractError("coverage baseline reference differs")
    if validator.get("run") != expected_validator_command():
        raise CoverageGateContractError("coverage validator command differs")

    download = _named_step(steps, CORE_DOWNLOAD_STEP_NAME)
    if download != {"name": CORE_DOWNLOAD_STEP_NAME, "id": "core_download", "continue-on-error": True,
                    "uses": CORE_DOWNLOAD_ACTION, "with": CORE_DOWNLOAD_SETTINGS}:
        raise CoverageGateContractError("core artifact download must retain exact current-run shard directories")
    coverage_step = _named_step(steps, COVERAGE_STEP_NAME)
    if set(coverage_step) != {"name", "shell", "run"}:
        raise CoverageGateContractError(
            "coverage test step must be unconditional and failure-propagating"
        )
    if coverage_step.get("shell") != "pwsh":
        raise CoverageGateContractError("coverage test shell differs")
    if coverage_step.get("run") != expected_coverage_command(data):
        raise CoverageGateContractError("coverage test command differs")

    branch_step = _named_step(steps, BRANCH_COVERAGE_STEP_NAME)
    if set(branch_step) != {"name", "shell", "run"}:
        raise CoverageGateContractError(
            "branch coverage step must be unconditional and failure-propagating"
        )
    if branch_step.get("shell") != "pwsh":
        raise CoverageGateContractError("branch coverage shell differs")
    if branch_step.get("run") != expected_branch_coverage_command(data):
        raise CoverageGateContractError("branch coverage command differs")

    upload = _named_step(steps, QA_UPLOAD_STEP_NAME)
    if (
        set(upload) != {"name", "if", "uses", "with"}
        or upload.get("if") != "always()"
        or upload.get("uses") != QA_UPLOAD_ACTION
        or upload.get("with") != QA_UPLOAD_SETTINGS
    ):
        raise CoverageGateContractError(
            "QA evidence upload must always retain the complete qa-artifacts directory"
        )

    ordered = [
        download,
        coverage_step,
        branch_step,
        upload,
    ]
    positions = [steps.index(step) for step in ordered]
    if positions != sorted(positions) or len(set(positions)) != len(positions):
        raise CoverageGateContractError(
            "coverage and evidence-upload step order differs"
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contract", type=Path)
    parser.add_argument("--workflow", type=Path)
    parser.add_argument("--baseline-ref")
    parser.add_argument("--results", type=Path)
    arguments = parser.parse_args(argv)
    try:
        data = _read_contract(arguments.contract)
        baseline = (
            load_git_baseline(arguments.baseline_ref, arguments.contract)
            if arguments.baseline_ref is not None
            else None
        )
        validate_contract(data, baseline=baseline)
        if arguments.workflow is not None:
            validate_workflow(data, arguments.workflow.read_text(encoding="utf-8"))
        measured = (
            validate_results(data, _read_results(arguments.results))
            if arguments.results is not None
            else None
        )
    except (OSError, CoverageGateContractError) as exc:
        print(f"coverage gate contract failed: {exc}", file=sys.stderr)
        return 2
    if measured is None:
        print("coverage gate is non-shrinking and unconditionally enforced")
    else:
        print(f"decision-branch coverage floor passed: {measured:.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
