"""Validate Sector's non-shrinking coverage gate and workflow placement."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import tomllib
import yaml

ROOT = Path(__file__).resolve().parents[1]
INITIAL_TARGETS = {"app", "sector"}
INITIAL_MINIMUM_PERCENT = 50
REQUIRED_WAIVER_IDS = {"coverage-pr14-calibration"}
VALIDATOR_STEP_NAME = "Validate non-shrinking coverage gate"
COVERAGE_STEP_NAME = "Run complete test suite with coverage"
CHECKOUT_STEP_NAME = "Check out source"
CHECKOUT_ACTION = "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5"
BASELINE_ENV = "SECTOR_COVERAGE_BASELINE_REF"
BASELINE_EXPRESSION = (
    "${{ github.event.pull_request.base.sha || github.event.before || 'HEAD^' }}"
)


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


def _snapshot(
    data: Mapping[str, Any],
    repository_root: Path,
    *,
    required_waiver_ids: set[str] | None,
) -> tuple[set[str], int]:
    if set(data) != {"schema_version", "coverage", "waivers"}:
        raise CoverageGateContractError("top-level contract keys differ")
    if data.get("schema_version") != 1:
        raise CoverageGateContractError("schema_version must remain 1")

    coverage = data.get("coverage")
    if not isinstance(coverage, Mapping) or set(coverage) != {
        "targets",
        "minimum_percent",
    }:
        raise CoverageGateContractError("coverage contract is incomplete")
    targets = set(_paths(coverage["targets"], "coverage.targets", repository_root))
    if not INITIAL_TARGETS <= targets:
        raise CoverageGateContractError("initial coverage target inventory shrank")
    minimum = coverage.get("minimum_percent")
    if isinstance(minimum, bool) or not isinstance(minimum, int):
        raise CoverageGateContractError("coverage minimum must be an integer")
    if minimum < INITIAL_MINIMUM_PERCENT:
        raise CoverageGateContractError(
            f"coverage minimum may not fall below {INITIAL_MINIMUM_PERCENT}"
        )
    if minimum > 100:
        raise CoverageGateContractError("coverage minimum may not exceed 100")

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
    return targets, minimum


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
    targets, minimum = _snapshot(
        data, repository_root, required_waiver_ids=required_waiver_ids
    )
    if baseline is None:
        return
    baseline_targets, baseline_minimum = _snapshot(
        baseline, repository_root, required_waiver_ids=None
    )
    if not baseline_targets <= targets:
        raise CoverageGateContractError("accepted coverage target ratchet shrank")
    if minimum < baseline_minimum:
        raise CoverageGateContractError(
            "coverage minimum fell below the previously accepted baseline"
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


def expected_coverage_command(data: Mapping[str, Any]) -> str:
    coverage = data["coverage"]
    targets = " ".join(f"--cov={target}" for target in coverage["targets"])
    return (
        f"python -m pytest tests -n 4 {targets} "
        "--cov-report=term-missing:skip-covered "
        "--cov-report=xml:qa-artifacts/coverage.xml "
        f"--cov-fail-under={coverage['minimum_percent']} "
        "--junitxml=qa-artifacts/test-results.xml"
    )


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
    }:
        raise CoverageGateContractError(
            "test job must retain an unconditional failure-propagating context"
        )
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

    coverage_step = _named_step(steps, COVERAGE_STEP_NAME)
    if set(coverage_step) != {"name", "run"}:
        raise CoverageGateContractError(
            "coverage test step must be unconditional and failure-propagating"
        )
    if coverage_step.get("run") != expected_coverage_command(data):
        raise CoverageGateContractError("coverage test command differs")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contract", type=Path)
    parser.add_argument("--workflow", type=Path)
    parser.add_argument("--baseline-ref")
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
    except (OSError, CoverageGateContractError) as exc:
        print(f"coverage gate contract failed: {exc}", file=sys.stderr)
        return 2
    print("coverage gate is non-shrinking and unconditionally enforced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
