"""Validate the non-shrinking F-012 coverage and Ruff gate contract."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import tomllib

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_TARGETS = {"app", "sector"}
REQUIRED_SCOPES = {
    "repository-fatal": {
        "paths": {"app", "sector", "tools", "tests"},
        "select": {"E9", "F63", "F7", "F82"},
        "permitted_ignore": set(),
    },
    "capacity-boundary": {
        "paths": {"sector/capacity.py", "tests/test_capacity.py"},
        "select": {"E4", "E7", "E9", "F", "I"},
        "permitted_ignore": set(),
    },
    "project-io-bootstrap": {
        "paths": {"tests/test_project_io.py"},
        "select": {"E4", "E7", "E9", "F", "I"},
        "permitted_ignore": {"E402"},
    },
}
REQUIRED_WAIVERS = {
    "coverage-pr14-calibration": "coverage",
    "ruff-existing-scope": "ruff",
    "ruff-project-io-e402": "ruff",
}


class StaticGateContractError(ValueError):
    """Raised when a static gate, local exception or workflow command drifts."""


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StaticGateContractError(f"{label} must be non-empty text")
    return value.strip()


def _strings(value: object, label: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise StaticGateContractError(f"{label} must be a text list")
    result = [_text(item, label) for item in value]
    if len(result) != len(set(result)):
        raise StaticGateContractError(f"{label} contains duplicates")
    return result


def _paths(value: object, label: str, repository_root: Path) -> list[str]:
    paths = _strings(value, label)
    root = repository_root.resolve()
    for relative in paths:
        candidate = (root / relative).resolve()
        if candidate != root and root not in candidate.parents:
            raise StaticGateContractError(f"{label} escapes the repository")
        if not candidate.exists():
            raise StaticGateContractError(f"{label} does not exist: {relative}")
    return paths


def validate_contract(data: Mapping[str, Any], repository_root: Path) -> None:
    if set(data) != {"schema_version", "coverage", "ruff", "waivers"}:
        raise StaticGateContractError("top-level contract keys differ")
    if data.get("schema_version") != 1:
        raise StaticGateContractError("schema_version must remain 1")

    coverage = data.get("coverage")
    if not isinstance(coverage, Mapping) or set(coverage) != {
        "targets",
        "minimum_percent",
    }:
        raise StaticGateContractError("coverage contract is incomplete")
    targets = set(_paths(coverage["targets"], "coverage.targets", repository_root))
    if not REQUIRED_TARGETS <= targets:
        raise StaticGateContractError("coverage target ratchet shrank")
    minimum = coverage.get("minimum_percent")
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 50:
        raise StaticGateContractError("coverage floor may not fall below 50")
    if minimum > 100:
        raise StaticGateContractError("coverage floor may not exceed 100")

    ruff = data.get("ruff")
    if not isinstance(ruff, Mapping) or set(ruff) != {"scopes"}:
        raise StaticGateContractError("Ruff contract is incomplete")
    scopes = ruff.get("scopes")
    if not isinstance(scopes, list):
        raise StaticGateContractError("ruff.scopes must be an array")
    by_id: dict[str, Mapping[str, Any]] = {}
    for index, scope in enumerate(scopes):
        if not isinstance(scope, Mapping) or set(scope) != {
            "id",
            "paths",
            "select",
            "ignore",
        }:
            raise StaticGateContractError(f"ruff.scopes[{index}] is incomplete")
        scope_id = _text(scope.get("id"), f"ruff.scopes[{index}].id")
        if scope_id in by_id:
            raise StaticGateContractError(f"duplicate Ruff scope: {scope_id}")
        by_id[scope_id] = scope
    if set(by_id) != set(REQUIRED_SCOPES):
        raise StaticGateContractError("Ruff scope inventory differs")

    for scope_id, required in REQUIRED_SCOPES.items():
        scope = by_id[scope_id]
        paths = set(_paths(scope["paths"], f"{scope_id}.paths", repository_root))
        selected = set(_strings(scope["select"], f"{scope_id}.select"))
        ignored = set(_strings(scope["ignore"], f"{scope_id}.ignore", allow_empty=True))
        if not required["paths"] <= paths:
            raise StaticGateContractError(f"{scope_id} path ratchet shrank")
        if not required["select"] <= selected:
            raise StaticGateContractError(f"{scope_id} rule ratchet shrank")
        if not ignored <= required["permitted_ignore"]:
            raise StaticGateContractError(f"{scope_id} gained an unowned ignore")

    waivers = data.get("waivers")
    if not isinstance(waivers, list):
        raise StaticGateContractError("waivers must be an array")
    waiver_ids: set[str] = set()
    for index, waiver in enumerate(waivers):
        if not isinstance(waiver, Mapping) or set(waiver) != {
            "id",
            "gate",
            "owner",
            "reason",
            "exit_condition",
        }:
            raise StaticGateContractError(f"waivers[{index}] is incomplete")
        waiver_id = _text(waiver.get("id"), f"waivers[{index}].id")
        if waiver_id in waiver_ids:
            raise StaticGateContractError(f"duplicate waiver: {waiver_id}")
        waiver_ids.add(waiver_id)
        gate = _text(waiver.get("gate"), f"waivers[{index}].gate")
        if REQUIRED_WAIVERS.get(waiver_id) not in (None, gate):
            raise StaticGateContractError(f"{waiver_id} has the wrong gate")
        for key in ("owner", "reason", "exit_condition"):
            _text(waiver.get(key), f"waivers[{index}].{key}")
    if waiver_ids != set(REQUIRED_WAIVERS):
        raise StaticGateContractError("required waiver inventory differs")


def load_contract(path: Path, repository_root: Path = ROOT) -> dict[str, Any]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise StaticGateContractError(f"cannot read contract: {exc}") from exc
    validate_contract(data, repository_root)
    return data


def expected_commands(data: Mapping[str, Any]) -> tuple[str, ...]:
    coverage = data["coverage"]
    commands = [
        "python tools/verify_static_gates.py quality-static-gates.toml "
        "--workflow .github/workflows/qa.yml"
    ]
    for scope in data["ruff"]["scopes"]:
        paths = " ".join(scope["paths"])
        selected = ",".join(scope["select"])
        ignored = ",".join(scope["ignore"])
        suffix = f" --ignore {ignored}" if ignored else ""
        commands.append(f"python -m ruff check {paths} --select {selected}{suffix}")
    targets = " ".join(f"--cov={target}" for target in coverage["targets"])
    commands.append(
        f"python -m pytest tests -n 4 {targets} "
        "--cov-report=term-missing:skip-covered "
        "--cov-report=xml:qa-artifacts/coverage.xml "
        f"--cov-fail-under={coverage['minimum_percent']} "
        "--junitxml=qa-artifacts/test-results.xml"
    )
    return tuple(commands)


def validate_workflow(data: Mapping[str, Any], workflow_text: str) -> None:
    run_commands = [
        stripped.removeprefix("run: ")
        for line in workflow_text.splitlines()
        if (stripped := line.strip()).startswith("run: ")
    ]
    for command in expected_commands(data):
        if run_commands.count(command) != 1:
            raise StaticGateContractError(
                f"workflow must contain one exact static-gate command: {command}"
            )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contract", type=Path)
    parser.add_argument("--workflow", type=Path)
    arguments = parser.parse_args(argv)
    try:
        data = load_contract(arguments.contract)
        if arguments.workflow is not None:
            validate_workflow(data, arguments.workflow.read_text(encoding="utf-8"))
    except (OSError, StaticGateContractError) as exc:
        print(f"static-gate contract failed: {exc}", file=sys.stderr)
        return 2
    print("coverage and Ruff gate contract is complete and aligned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
