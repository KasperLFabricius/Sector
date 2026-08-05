"""Validate and execute Sector's non-shrinking Ruff gate."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomllib
import yaml

ROOT = Path(__file__).resolve().parents[1]
INITIAL_SCOPE_ORDER = (
    "repository-runtime-errors",
    "capacity-boundary",
    "project-io-boundary",
)
REQUIRED_WAIVER_IDS = {"ruff-project-io-e402"}
VALIDATOR_STEP_NAME = "Validate non-shrinking Ruff gate"
RUFF_STEP_NAME = "Run ratcheted Ruff checks"
CHECKOUT_STEP_NAME = "Check out source"
CHECKOUT_ACTION = "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5"
BASELINE_ENV = "SECTOR_RUFF_BASELINE_REF"
BASELINE_EXPRESSION = (
    "${{ github.event.pull_request.base.sha || github.event.before || 'HEAD^' }}"
)
RULE_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*$")


class RuffGateContractError(ValueError):
    """Raised when the Ruff contract or its execution context is unsafe."""


@dataclass(frozen=True)
class RuffScopeSnapshot:
    """Ordered fields that form one accepted Ruff scope identity."""

    paths: tuple[str, ...]
    selected: tuple[str, ...]
    ignored: frozenset[str]


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuffGateContractError(f"{label} must be non-empty text")
    return value.strip()


def _strings(
    value: object,
    label: str,
    *,
    allow_empty: bool = False,
) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        qualifier = "a text list" if allow_empty else "a non-empty text list"
        raise RuffGateContractError(f"{label} must be {qualifier}")
    result = [_text(item, label) for item in value]
    if len(result) != len(set(result)):
        raise RuffGateContractError(f"{label} contains duplicates")
    return result


def _paths(value: object, label: str, repository_root: Path) -> list[str]:
    paths = _strings(value, label)
    root = repository_root.resolve()
    for relative in paths:
        candidate = (root / relative).resolve()
        if candidate != root and root not in candidate.parents:
            raise RuffGateContractError(f"{label} escapes the repository")
        if not candidate.exists():
            raise RuffGateContractError(f"{label} does not exist: {relative}")
    return paths


def _rules(value: object, label: str, *, allow_empty: bool) -> list[str]:
    rules = _strings(value, label, allow_empty=allow_empty)
    for rule in rules:
        if RULE_PATTERN.fullmatch(rule) is None:
            raise RuffGateContractError(f"{label} contains an invalid Ruff selector")
    return rules


def _snapshot(
    data: Mapping[str, Any],
    repository_root: Path,
    *,
    required_waiver_ids: set[str] | None,
) -> tuple[dict[str, RuffScopeSnapshot], set[str]]:
    if set(data) != {"schema_version", "scopes", "waivers"}:
        raise RuffGateContractError("top-level contract keys differ")
    if data.get("schema_version") != 1:
        raise RuffGateContractError("schema_version must remain 1")

    raw_scopes = data.get("scopes")
    if not isinstance(raw_scopes, list) or not raw_scopes:
        raise RuffGateContractError("scopes must be a non-empty array")
    scopes: dict[str, RuffScopeSnapshot] = {}
    for index, raw_scope in enumerate(raw_scopes):
        label = f"scopes[{index}]"
        if not isinstance(raw_scope, Mapping) or set(raw_scope) != {
            "id",
            "paths",
            "select",
            "ignore",
        }:
            raise RuffGateContractError(f"{label} is incomplete")
        scope_id = _text(raw_scope.get("id"), f"{label}.id")
        if scope_id in scopes:
            raise RuffGateContractError(f"duplicate Ruff scope: {scope_id}")
        paths = _paths(raw_scope["paths"], f"{label}.paths", repository_root)
        selected = _rules(raw_scope["select"], f"{label}.select", allow_empty=False)
        ignored = _rules(raw_scope["ignore"], f"{label}.ignore", allow_empty=True)
        if any(
            not any(code.startswith(selector) for selector in selected)
            for code in ignored
        ):
            raise RuffGateContractError(
                f"{scope_id} ignores rules that its selector does not include"
            )
        scopes[scope_id] = RuffScopeSnapshot(
            paths=tuple(paths),
            selected=tuple(selected),
            ignored=frozenset(ignored),
        )
    if list(scopes)[: len(INITIAL_SCOPE_ORDER)] != list(INITIAL_SCOPE_ORDER):
        raise RuffGateContractError("initial Ruff scope order or inventory differs")

    raw_waivers = data.get("waivers")
    if not isinstance(raw_waivers, list):
        raise RuffGateContractError("waivers must be an array")
    waiver_ids: set[str] = set()
    waived_pairs: set[tuple[str, str]] = set()
    for index, raw_waiver in enumerate(raw_waivers):
        label = f"waivers[{index}]"
        if not isinstance(raw_waiver, Mapping) or set(raw_waiver) != {
            "id",
            "gate",
            "scope",
            "code",
            "owner",
            "reason",
            "exit_condition",
        }:
            raise RuffGateContractError(f"{label} is incomplete")
        waiver_id = _text(raw_waiver.get("id"), f"{label}.id")
        if waiver_id in waiver_ids:
            raise RuffGateContractError(f"duplicate Ruff waiver: {waiver_id}")
        waiver_ids.add(waiver_id)
        if _text(raw_waiver.get("gate"), f"{label}.gate") != "ruff":
            raise RuffGateContractError(f"{waiver_id} has the wrong gate")
        scope_id = _text(raw_waiver.get("scope"), f"{label}.scope")
        code = _rules([raw_waiver.get("code")], f"{label}.code", allow_empty=False)[0]
        if scope_id not in scopes or code not in scopes[scope_id].ignored:
            raise RuffGateContractError(f"{waiver_id} does not own an ignored rule")
        pair = (scope_id, code)
        if pair in waived_pairs:
            raise RuffGateContractError(f"duplicate Ruff waiver target: {pair}")
        waived_pairs.add(pair)
        for key in ("owner", "reason", "exit_condition"):
            _text(raw_waiver.get(key), f"{label}.{key}")

    ignored_pairs = {
        (scope_id, code)
        for scope_id, scope in scopes.items()
        for code in scope.ignored
    }
    if ignored_pairs != waived_pairs:
        raise RuffGateContractError("every ignored Ruff rule must have one owned waiver")
    if required_waiver_ids is not None and waiver_ids != required_waiver_ids:
        raise RuffGateContractError("Ruff waiver inventory differs")
    return scopes, waiver_ids


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
    scopes, _ = _snapshot(
        data,
        repository_root,
        required_waiver_ids=required_waiver_ids,
    )
    if baseline is None:
        return
    baseline_scopes, _ = _snapshot(
        baseline,
        repository_root,
        required_waiver_ids=None,
    )
    if not set(baseline_scopes) <= set(scopes):
        raise RuffGateContractError("accepted Ruff scope inventory shrank")
    if [scope_id for scope_id in scopes if scope_id in baseline_scopes] != list(
        baseline_scopes
    ):
        raise RuffGateContractError("accepted Ruff scope order changed")
    for scope_id, accepted in baseline_scopes.items():
        candidate = scopes[scope_id]
        if not set(accepted.paths) <= set(candidate.paths):
            raise RuffGateContractError(f"accepted Ruff paths shrank for {scope_id}")
        if not _ordered_subset(accepted.paths, candidate.paths):
            raise RuffGateContractError(
                f"accepted Ruff path order changed for {scope_id}"
            )
        if not set(accepted.selected) <= set(candidate.selected):
            raise RuffGateContractError(f"accepted Ruff selectors shrank for {scope_id}")
        if not _ordered_subset(accepted.selected, candidate.selected):
            raise RuffGateContractError(
                f"accepted Ruff selector order changed for {scope_id}"
            )
        if not candidate.ignored <= accepted.ignored:
            raise RuffGateContractError(f"Ruff ignores expanded for {scope_id}")


def _ordered_subset(accepted: Sequence[str], candidate: Sequence[str]) -> bool:
    remaining = iter(candidate)
    return all(any(item == current for current in remaining) for item in accepted)


def _parse_toml(text: str, label: str) -> dict[str, Any]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise RuffGateContractError(f"cannot parse {label}: {exc}") from exc
    return data


def _read_contract(path: Path) -> dict[str, Any]:
    try:
        return _parse_toml(path.read_text(encoding="utf-8"), str(path))
    except OSError as exc:
        raise RuffGateContractError(f"cannot read contract: {exc}") from exc


def _git(
    repository_root: Path,
    arguments: Sequence[str],
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
        raise RuffGateContractError(f"git baseline inspection failed: {detail}")
    return completed


def load_git_baseline(
    baseline_ref: str,
    contract_path: Path,
    repository_root: Path = ROOT,
) -> dict[str, Any] | None:
    reference = _text(baseline_ref, "baseline_ref")
    root = repository_root.resolve()
    try:
        relative = contract_path.resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise RuffGateContractError("contract path escapes the repository") from exc
    _git(root, ["cat-file", "-e", f"{reference}^{{commit}}"])
    listed = _git(root, ["ls-tree", "--name-only", reference, "--", relative])
    if relative not in listed.stdout.splitlines():
        return None
    object_name = f"{reference}:{relative}"
    return _parse_toml(_git(root, ["show", object_name]).stdout, object_name)


def expected_validator_command() -> str:
    return (
        "python tools/verify_ruff_gate.py quality-ruff-gate.toml "
        "--workflow .github/workflows/qa.yml "
        "--baseline-ref $env:SECTOR_RUFF_BASELINE_REF"
    )


def expected_runner_command() -> str:
    return "python tools/verify_ruff_gate.py quality-ruff-gate.toml --run-checks"


def command_arguments(scope: Mapping[str, Any]) -> list[str]:
    arguments = [
        "check",
        "--isolated",
        *scope["paths"],
        "--select",
        ",".join(scope["select"]),
    ]
    if scope["ignore"]:
        arguments.extend(["--ignore", ",".join(scope["ignore"])])
    return arguments


def run_checks(
    data: Mapping[str, Any],
    repository_root: Path = ROOT,
    *,
    ruff_executable: str = "ruff",
) -> None:
    for scope in data["scopes"]:
        completed = subprocess.run(
            [ruff_executable, *command_arguments(scope)],
            cwd=repository_root,
            check=False,
        )
        if completed.returncode != 0:
            raise RuffGateContractError(
                f"Ruff scope {scope['id']!r} failed with exit code "
                f"{completed.returncode}"
            )


def _workflow_mapping(workflow_text: str) -> Mapping[str, Any]:
    try:
        workflow = yaml.safe_load(workflow_text)
    except yaml.YAMLError as exc:
        raise RuffGateContractError(f"cannot parse workflow YAML: {exc}") from exc
    if not isinstance(workflow, Mapping):
        raise RuffGateContractError("workflow must be a mapping")
    return workflow


def _named_step(steps: object, name: str) -> Mapping[str, Any]:
    if not isinstance(steps, list):
        raise RuffGateContractError("test job steps must be an array")
    matches = [
        step
        for step in steps
        if isinstance(step, Mapping) and step.get("name") == name
    ]
    if len(matches) != 1:
        raise RuffGateContractError(f"workflow must contain one {name!r} step")
    return matches[0]


def validate_workflow(workflow_text: str) -> None:
    workflow = _workflow_mapping(workflow_text)
    triggers = workflow.get("on", workflow.get(True))
    if not isinstance(triggers, Mapping) or set(triggers) != {
        "pull_request",
        "push",
        "workflow_dispatch",
    }:
        raise RuffGateContractError("workflow trigger inventory differs")
    if triggers.get("pull_request") is not None:
        raise RuffGateContractError("pull_request trigger must remain unfiltered")
    if triggers.get("workflow_dispatch") is not None:
        raise RuffGateContractError("workflow_dispatch trigger must remain unfiltered")
    if triggers.get("push") != {"branches": ["main"]}:
        raise RuffGateContractError("push trigger must cover all main changes")

    jobs = workflow.get("jobs")
    if not isinstance(jobs, Mapping):
        raise RuffGateContractError("workflow jobs must be a mapping")
    test_job = jobs.get("test")
    if not isinstance(test_job, Mapping) or set(test_job) != {
        "name",
        "runs-on",
        "timeout-minutes",
        "steps",
    }:
        raise RuffGateContractError(
            "test job must retain an unconditional failure-propagating context"
        )
    steps = test_job["steps"]

    checkout = _named_step(steps, CHECKOUT_STEP_NAME)
    if (
        set(checkout) != {"name", "uses", "with"}
        or checkout.get("uses") != CHECKOUT_ACTION
        or checkout.get("with") != {"fetch-depth": 0}
    ):
        raise RuffGateContractError(
            "test checkout must fetch history for the accepted baseline"
        )

    validator = _named_step(steps, VALIDATOR_STEP_NAME)
    if set(validator) != {"name", "env", "run"}:
        raise RuffGateContractError(
            "Ruff validator step must be unconditional and failure-propagating"
        )
    if validator.get("env") != {BASELINE_ENV: BASELINE_EXPRESSION}:
        raise RuffGateContractError("Ruff baseline reference differs")
    if validator.get("run") != expected_validator_command():
        raise RuffGateContractError("Ruff validator command differs")

    runner = _named_step(steps, RUFF_STEP_NAME)
    if set(runner) != {"name", "run"}:
        raise RuffGateContractError(
            "Ruff runner step must be unconditional and failure-propagating"
        )
    if runner.get("run") != expected_runner_command():
        raise RuffGateContractError("Ruff runner command differs")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contract", type=Path)
    parser.add_argument("--workflow", type=Path)
    parser.add_argument("--baseline-ref")
    parser.add_argument("--run-checks", action="store_true")
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
            validate_workflow(arguments.workflow.read_text(encoding="utf-8"))
        if arguments.run_checks:
            run_checks(data)
    except (OSError, RuffGateContractError) as exc:
        print(f"Ruff gate contract failed: {exc}", file=sys.stderr)
        return 2
    print("Ruff gate is non-shrinking and unconditionally enforced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
