"""Validate Sector's ratcheted F-012 quality-gate contract."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import tomllib

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
POLICY_GATES = {"coverage", "ruff", "typing", "dependency_security"}
REQUIRED_COVERAGE_TARGETS = {"app", "sector"}
REQUIRED_CRITICAL_RUFF_PATHS = {"app", "sector", "tools", "tests"}
REQUIRED_CRITICAL_RUFF_RULES = {"E9", "F63", "F7", "F82"}
REQUIRED_SELECTED_RUFF_PATHS = {
    "sector/capacity.py",
    "tests/test_capacity.py",
    "tests/test_project_io.py",
}
REQUIRED_SELECTED_RUFF_RULES = {"E4", "E7", "E9", "F", "I"}
PERMITTED_SELECTED_RUFF_IGNORES = {"E402"}
REQUIRED_TYPING_PATHS = {
    "sector/bridge.py",
    "app/bridge_analysis.py",
    "app/manual_equation_contract.py",
    "app/manual_equation_publication.py",
}
REQUIRED_WAIVER_GATES = {
    "coverage-pr14-calibration": "coverage",
    "ruff-existing-scope": "ruff",
    "ruff-project-io-e402": "ruff",
    "mypy-existing-scope": "typing",
}
POLICY_KEYS = {
    "schema_version",
    "coverage",
    "ruff",
    "typing",
    "dependency_security",
    "waivers",
}


class QualityGatePolicyError(ValueError):
    """Raised when the tracked quality-gate contract is incomplete or drifts."""


def _table(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data.get(key)
    if not isinstance(value, Mapping):
        raise QualityGatePolicyError(f"{key} must be a TOML table")
    return value


def _text(table: Mapping[str, Any], key: str, context: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise QualityGatePolicyError(f"{context}.{key} must be non-empty text")
    return value.strip()


def _text_list(
    table: Mapping[str, Any], key: str, context: str, *, allow_empty: bool = False
) -> list[str]:
    value = table.get(key)
    if not isinstance(value, list) or (not value and not allow_empty):
        raise QualityGatePolicyError(f"{context}.{key} must be a text list")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise QualityGatePolicyError(f"{context}.{key} contains an invalid entry")
    result = [item.strip() for item in value]
    if len(result) != len(set(result)):
        raise QualityGatePolicyError(f"{context}.{key} contains duplicates")
    return result


def _existing_paths(
    table: Mapping[str, Any], key: str, context: str, repository_root: Path
) -> list[str]:
    paths = _text_list(table, key, context)
    root = repository_root.resolve()
    for relative in paths:
        candidate = (root / relative).resolve()
        if candidate != root and root not in candidate.parents:
            raise QualityGatePolicyError(f"{context}.{key} escapes the repository")
        if not candidate.exists():
            raise QualityGatePolicyError(f"{context}.{key} does not exist: {relative}")
    return paths


def validate_policy(data: Mapping[str, Any], repository_root: Path) -> None:
    """Validate the complete in-memory policy against the retained repository."""

    unknown = set(data) - POLICY_KEYS
    missing = POLICY_KEYS - set(data)
    if unknown or missing:
        raise QualityGatePolicyError(
            f"policy keys differ: missing={sorted(missing)}, unknown={sorted(unknown)}"
        )
    if data.get("schema_version") != 1:
        raise QualityGatePolicyError("schema_version must remain 1")

    coverage = _table(data, "coverage")
    if set(coverage) != {"targets", "minimum_percent"}:
        raise QualityGatePolicyError("coverage keys are incomplete or unknown")
    coverage_targets = set(
        _existing_paths(coverage, "targets", "coverage", repository_root)
    )
    if not REQUIRED_COVERAGE_TARGETS <= coverage_targets:
        raise QualityGatePolicyError("coverage.targets shrinks the frozen ratchet")
    minimum = coverage.get("minimum_percent")
    if isinstance(minimum, bool) or not isinstance(minimum, int):
        raise QualityGatePolicyError("coverage.minimum_percent must be an integer")
    if not 50 <= minimum <= 100:
        raise QualityGatePolicyError("coverage.minimum_percent may not fall below 50")

    ruff = _table(data, "ruff")
    if set(ruff) != {
        "critical_paths",
        "critical_select",
        "selected_paths",
        "selected_select",
        "selected_ignore",
    }:
        raise QualityGatePolicyError("ruff keys are incomplete or unknown")
    critical_paths = set(
        _existing_paths(ruff, "critical_paths", "ruff", repository_root)
    )
    critical_rules = set(_text_list(ruff, "critical_select", "ruff"))
    selected_paths = set(
        _existing_paths(ruff, "selected_paths", "ruff", repository_root)
    )
    selected_rules = set(_text_list(ruff, "selected_select", "ruff"))
    selected_ignores = set(
        _text_list(ruff, "selected_ignore", "ruff", allow_empty=True)
    )
    if not REQUIRED_CRITICAL_RUFF_PATHS <= critical_paths:
        raise QualityGatePolicyError("ruff.critical_paths shrinks the frozen ratchet")
    if not REQUIRED_CRITICAL_RUFF_RULES <= critical_rules:
        raise QualityGatePolicyError("ruff.critical_select shrinks the frozen ratchet")
    if not REQUIRED_SELECTED_RUFF_PATHS <= selected_paths:
        raise QualityGatePolicyError("ruff.selected_paths shrinks the frozen ratchet")
    if not REQUIRED_SELECTED_RUFF_RULES <= selected_rules:
        raise QualityGatePolicyError("ruff.selected_select shrinks the frozen ratchet")
    if not selected_ignores <= PERMITTED_SELECTED_RUFF_IGNORES:
        raise QualityGatePolicyError("ruff.selected_ignore adds an unowned exception")

    typing = _table(data, "typing")
    if set(typing) != {"strict", "paths"} or typing.get("strict") is not True:
        raise QualityGatePolicyError("typing must contain strict=true and paths")
    typing_paths = set(_existing_paths(typing, "paths", "typing", repository_root))
    if not REQUIRED_TYPING_PATHS <= typing_paths:
        raise QualityGatePolicyError("typing.paths shrinks the frozen ratchet")

    security = _table(data, "dependency_security")
    if set(security) != {
        "requirements",
        "strict",
        "require_hashes",
        "disable_pip",
    }:
        raise QualityGatePolicyError(
            "dependency_security keys are incomplete or unknown"
        )
    if any(
        security.get(key) is not True
        for key in ("strict", "require_hashes", "disable_pip")
    ):
        raise QualityGatePolicyError("dependency audit safeguards must remain enabled")
    requirements = _text(security, "requirements", "dependency_security")
    if requirements != "requirements-dev.txt":
        raise QualityGatePolicyError(
            "dependency_security.requirements must remain requirements-dev.txt"
        )
    root = repository_root.resolve()
    requirements_path = (root / requirements).resolve()
    if root not in requirements_path.parents:
        raise QualityGatePolicyError(
            "dependency-security requirements escape the repository"
        )
    if not requirements_path.is_file():
        raise QualityGatePolicyError("dependency-security requirements file is missing")
    requirements_text = requirements_path.read_text(encoding="utf-8")
    if "--hash=sha256:" not in requirements_text:
        raise QualityGatePolicyError("dependency-security requirements are not hashed")

    waivers = data.get("waivers")
    if not isinstance(waivers, list):
        raise QualityGatePolicyError("waivers must be an array of tables")
    waiver_ids: set[str] = set()
    for index, waiver in enumerate(waivers):
        context = f"waivers[{index}]"
        if not isinstance(waiver, Mapping):
            raise QualityGatePolicyError(f"{context} must be a table")
        if set(waiver) != {"id", "gate", "owner", "reason", "exit_condition"}:
            raise QualityGatePolicyError(f"{context} keys are incomplete or unknown")
        waiver_id = _text(waiver, "id", context)
        if waiver_id in waiver_ids:
            raise QualityGatePolicyError(f"duplicate waiver id: {waiver_id}")
        waiver_ids.add(waiver_id)
        gate = _text(waiver, "gate", context)
        if gate not in POLICY_GATES:
            raise QualityGatePolicyError(f"{context}.gate is unknown: {gate}")
        expected_gate = REQUIRED_WAIVER_GATES.get(waiver_id)
        if expected_gate is not None and gate != expected_gate:
            raise QualityGatePolicyError(
                f"{context}.gate must remain {expected_gate} for {waiver_id}"
            )
        _text(waiver, "owner", context)
        _text(waiver, "reason", context)
        _text(waiver, "exit_condition", context)
    if waiver_ids != set(REQUIRED_WAIVER_GATES):
        raise QualityGatePolicyError("required waiver inventory differs")


def load_policy(path: Path, repository_root: Path = REPOSITORY_ROOT) -> dict[str, Any]:
    """Read and validate one tracked policy file."""

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise QualityGatePolicyError(f"cannot read policy: {exc}") from exc
    validate_policy(data, repository_root)
    return data


def _command_fragments(data: Mapping[str, Any]) -> Sequence[str]:
    coverage = _table(data, "coverage")
    ruff = _table(data, "ruff")
    typing = _table(data, "typing")
    security = _table(data, "dependency_security")
    targets = " ".join(f"--cov={path}" for path in coverage["targets"])
    critical_paths = " ".join(ruff["critical_paths"])
    critical_select = ",".join(ruff["critical_select"])
    selected_paths = " ".join(ruff["selected_paths"])
    selected_select = ",".join(ruff["selected_select"])
    selected_ignore = ",".join(ruff["selected_ignore"])
    ignore_argument = f" --ignore {selected_ignore}" if selected_ignore else ""
    typing_paths = " ".join(typing["paths"])
    requirements = security["requirements"]
    minimum = coverage["minimum_percent"]
    return (
        f"python -m ruff check {critical_paths} --select {critical_select}",
        f"python -m ruff check {selected_paths} --select {selected_select}{ignore_argument}",
        f"python -m mypy --strict {typing_paths}",
        "python -m pip_audit --strict --require-hashes --disable-pip "
        f"-r {requirements} --progress-spinner off",
        f"python -m pytest tests -n 4 {targets} "
        "--cov-report=term-missing:skip-covered "
        "--cov-report=xml:qa-artifacts/coverage.xml "
        f"--cov-fail-under={minimum} --junitxml=qa-artifacts/test-results.xml",
    )


def validate_workflow(data: Mapping[str, Any], workflow_text: str) -> None:
    """Reject a CI workflow that no longer executes the frozen policy."""

    workflow_commands = [
        stripped.removeprefix("run: ")
        for line in workflow_text.splitlines()
        if (stripped := line.strip()).startswith("run: ")
    ]
    for fragment in _command_fragments(data):
        if workflow_commands.count(fragment) != 1:
            raise QualityGatePolicyError(
                f"workflow must contain one exact policy command: {fragment}"
            )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("policy", type=Path)
    parser.add_argument("--workflow", type=Path)
    arguments = parser.parse_args(argv)
    try:
        policy = load_policy(arguments.policy)
        if arguments.workflow is not None:
            validate_workflow(policy, arguments.workflow.read_text(encoding="utf-8"))
    except (OSError, QualityGatePolicyError) as exc:
        print(f"quality-gate policy failed: {exc}", file=sys.stderr)
        return 2
    print("quality-gate policy is complete and aligned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
