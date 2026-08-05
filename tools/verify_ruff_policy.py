"""Verify and execute Sector's accepted-base Ruff policy ratchet."""

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
POLICY_PATH = Path("quality-ruff-policy.toml")
WORKFLOW_PATH = Path(".github/workflows/qa.yml")
INITIAL_SCOPE_ORDER = (
    "runtime-errors",
    "capacity-typed-boundary",
    "project-io-test-boundary",
)
CURRENT_WAIVERS = {"project-io-bootstrap-e402"}
RUFF_SAFETY_OPTIONS = (
    "--isolated",
    "--ignore-noqa",
    "--no-respect-gitignore",
)
VALIDATE_STEP = "Validate Ruff policy ratchet"
EXECUTE_STEP = "Execute Ruff policy"
CHECKOUT_STEP = "Check out source"
CHECKOUT_ACTION = "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5"
BASELINE_ENV = "SECTOR_RUFF_POLICY_BASE"
BASELINE_EXPRESSION = (
    "${{ github.event.pull_request.base.sha || github.event.before || 'HEAD^' }}"
)
RULE_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*$")


class RuffPolicyError(ValueError):
    """Raised when the Ruff policy is incomplete, weaker, or bypassed."""


@dataclass(frozen=True)
class ScopeIdentity:
    """Ordered identity retained for one accepted Ruff scope."""

    paths: tuple[str, ...]
    select: tuple[str, ...]
    ignore: frozenset[str]


def _nonblank(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuffPolicyError(f"{label} must be non-empty text")
    return value.strip()


def _text_list(value: object, label: str, *, empty_ok: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not empty_ok):
        detail = "a text list" if empty_ok else "a non-empty text list"
        raise RuffPolicyError(f"{label} must be {detail}")
    items = [_nonblank(item, label) for item in value]
    if len(items) != len(set(items)):
        raise RuffPolicyError(f"{label} contains duplicates")
    return items


def _validated_paths(value: object, label: str, root: Path) -> list[str]:
    paths = _text_list(value, label)
    resolved_root = root.resolve()
    for relative in paths:
        resolved = (resolved_root / relative).resolve()
        if resolved != resolved_root and resolved_root not in resolved.parents:
            raise RuffPolicyError(f"{label} escapes the repository")
        if not resolved.exists():
            raise RuffPolicyError(f"{label} does not exist: {relative}")
    return paths


def _validated_rules(value: object, label: str, *, empty_ok: bool) -> list[str]:
    rules = _text_list(value, label, empty_ok=empty_ok)
    if any(RULE_PATTERN.fullmatch(rule) is None for rule in rules):
        raise RuffPolicyError(f"{label} contains an invalid Ruff selector")
    return rules


def _parse_policy(text: str, label: str) -> dict[str, Any]:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise RuffPolicyError(f"cannot parse {label}: {exc}") from exc


def read_policy(path: Path) -> dict[str, Any]:
    try:
        return _parse_policy(path.read_text(encoding="utf-8"), str(path))
    except OSError as exc:
        raise RuffPolicyError(f"cannot read Ruff policy: {exc}") from exc


def _snapshot(
    policy: Mapping[str, Any],
    root: Path,
    *,
    required_waivers: set[str] | None,
) -> dict[str, ScopeIdentity]:
    if set(policy) != {"schema_version", "scopes", "waivers"}:
        raise RuffPolicyError("Ruff policy top-level keys differ")
    if policy.get("schema_version") != 1:
        raise RuffPolicyError("Ruff policy schema_version must remain 1")

    raw_scopes = policy.get("scopes")
    if not isinstance(raw_scopes, list) or not raw_scopes:
        raise RuffPolicyError("Ruff scopes must be a non-empty array")
    scopes: dict[str, ScopeIdentity] = {}
    for index, raw in enumerate(raw_scopes):
        label = f"scopes[{index}]"
        if not isinstance(raw, Mapping) or set(raw) != {
            "id",
            "paths",
            "select",
            "ignore",
        }:
            raise RuffPolicyError(f"{label} keys differ")
        scope_id = _nonblank(raw.get("id"), f"{label}.id")
        if scope_id in scopes:
            raise RuffPolicyError(f"duplicate Ruff scope: {scope_id}")
        paths = _validated_paths(raw["paths"], f"{label}.paths", root)
        selected = _validated_rules(raw["select"], f"{label}.select", empty_ok=False)
        ignored = _validated_rules(raw["ignore"], f"{label}.ignore", empty_ok=True)
        if any(
            not any(code.startswith(selector) for selector in selected)
            for code in ignored
        ):
            raise RuffPolicyError(f"{scope_id} ignores an unselected Ruff rule")
        scopes[scope_id] = ScopeIdentity(
            paths=tuple(paths),
            select=tuple(selected),
            ignore=frozenset(ignored),
        )
    if tuple(scopes)[: len(INITIAL_SCOPE_ORDER)] != INITIAL_SCOPE_ORDER:
        raise RuffPolicyError("initial Ruff scope identity or order differs")

    raw_waivers = policy.get("waivers")
    if not isinstance(raw_waivers, list):
        raise RuffPolicyError("Ruff waivers must be an array")
    waiver_ids: set[str] = set()
    waived: set[tuple[str, str]] = set()
    for index, raw in enumerate(raw_waivers):
        label = f"waivers[{index}]"
        if not isinstance(raw, Mapping) or set(raw) != {
            "id",
            "scope",
            "code",
            "owner",
            "reason",
            "exit_condition",
        }:
            raise RuffPolicyError(f"{label} keys differ")
        waiver_id = _nonblank(raw.get("id"), f"{label}.id")
        if waiver_id in waiver_ids:
            raise RuffPolicyError(f"duplicate Ruff waiver: {waiver_id}")
        waiver_ids.add(waiver_id)
        scope_id = _nonblank(raw.get("scope"), f"{label}.scope")
        code = _validated_rules([raw.get("code")], f"{label}.code", empty_ok=False)[0]
        if scope_id not in scopes or code not in scopes[scope_id].ignore:
            raise RuffPolicyError(f"{waiver_id} does not own an ignored rule")
        target = (scope_id, code)
        if target in waived:
            raise RuffPolicyError(f"duplicate Ruff waiver target: {target}")
        waived.add(target)
        for field in ("owner", "reason", "exit_condition"):
            _nonblank(raw.get(field), f"{label}.{field}")

    ignored = {
        (scope_id, code)
        for scope_id, identity in scopes.items()
        for code in identity.ignore
    }
    if waived != ignored:
        raise RuffPolicyError("each ignored Ruff rule requires one owned waiver")
    if required_waivers is not None and waiver_ids != required_waivers:
        raise RuffPolicyError("Ruff waiver inventory differs")
    return scopes


def _ordered_subset(accepted: Sequence[str], candidate: Sequence[str]) -> bool:
    remaining = iter(candidate)
    return all(any(value == current for current in remaining) for value in accepted)


def validate_policy(
    policy: Mapping[str, Any],
    root: Path = ROOT,
    *,
    baseline: Mapping[str, Any] | None = None,
    current_waivers: set[str] | None = None,
) -> None:
    required = CURRENT_WAIVERS if current_waivers is None else current_waivers
    candidate = _snapshot(policy, root, required_waivers=required)
    if baseline is None:
        return
    accepted = _snapshot(baseline, root, required_waivers=None)
    if not set(accepted) <= set(candidate):
        raise RuffPolicyError("accepted Ruff scope inventory shrank")
    if [scope_id for scope_id in candidate if scope_id in accepted] != list(accepted):
        raise RuffPolicyError("accepted Ruff scope order changed")
    for scope_id, old in accepted.items():
        new = candidate[scope_id]
        if not set(old.paths) <= set(new.paths):
            raise RuffPolicyError(f"accepted Ruff paths shrank for {scope_id}")
        if not _ordered_subset(old.paths, new.paths):
            raise RuffPolicyError(f"accepted Ruff path order changed for {scope_id}")
        if not set(old.select) <= set(new.select):
            raise RuffPolicyError(f"accepted Ruff selectors shrank for {scope_id}")
        if not _ordered_subset(old.select, new.select):
            raise RuffPolicyError(f"accepted Ruff selector order changed for {scope_id}")
        if not new.ignore <= old.ignore:
            raise RuffPolicyError(f"Ruff ignores expanded for {scope_id}")


def _git(root: Path, arguments: Sequence[str]) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuffPolicyError(f"Git baseline inspection failed: {detail}")
    return completed.stdout


def policy_from_git(
    reference: str,
    path: Path = POLICY_PATH,
    root: Path = ROOT,
) -> dict[str, Any] | None:
    baseline = _nonblank(reference, "baseline reference")
    resolved_root = root.resolve()
    try:
        relative = path.resolve().relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise RuffPolicyError("Ruff policy path escapes the repository") from exc
    _git(resolved_root, ["cat-file", "-e", f"{baseline}^{{commit}}"])
    names = _git(resolved_root, ["ls-tree", "--name-only", baseline, "--", relative])
    if relative not in names.splitlines():
        return None
    object_name = f"{baseline}:{relative}"
    return _parse_policy(_git(resolved_root, ["show", object_name]), object_name)


def scope_command(scope: Mapping[str, Any], *, executable: str = "ruff") -> list[str]:
    command = [
        executable,
        "check",
        *RUFF_SAFETY_OPTIONS,
        *scope["paths"],
        "--select",
        ",".join(scope["select"]),
    ]
    if scope["ignore"]:
        command.extend(["--ignore", ",".join(scope["ignore"])])
    return command


def execute_policy(
    policy: Mapping[str, Any],
    root: Path = ROOT,
    *,
    executable: str = "ruff",
) -> None:
    for scope in policy["scopes"]:
        completed = subprocess.run(
            scope_command(scope, executable=executable),
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            detail = completed.stdout.strip() or completed.stderr.strip()
            raise RuffPolicyError(
                f"Ruff scope {scope['id']!r} failed with exit code "
                f"{completed.returncode}: {detail}"
            )


def validator_command() -> str:
    return (
        "python tools/verify_ruff_policy.py quality-ruff-policy.toml "
        "--workflow .github/workflows/qa.yml "
        "--baseline-ref $env:SECTOR_RUFF_POLICY_BASE"
    )


def executor_command() -> str:
    return "python tools/verify_ruff_policy.py quality-ruff-policy.toml --execute"


def _workflow(text: str) -> Mapping[str, Any]:
    try:
        workflow = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RuffPolicyError(f"cannot parse workflow YAML: {exc}") from exc
    if not isinstance(workflow, Mapping):
        raise RuffPolicyError("workflow must be a mapping")
    return workflow


def _one_step(steps: object, name: str) -> Mapping[str, Any]:
    if not isinstance(steps, list):
        raise RuffPolicyError("test job steps must be an array")
    found = [
        step
        for step in steps
        if isinstance(step, Mapping) and step.get("name") == name
    ]
    if len(found) != 1:
        raise RuffPolicyError(f"workflow must contain one {name!r} step")
    return found[0]


def validate_workflow(text: str) -> None:
    workflow = _workflow(text)
    triggers = workflow.get("on", workflow.get(True))
    if not isinstance(triggers, Mapping) or set(triggers) != {
        "pull_request",
        "push",
        "workflow_dispatch",
    }:
        raise RuffPolicyError("workflow trigger inventory differs")
    if triggers.get("pull_request") is not None:
        raise RuffPolicyError("pull_request trigger must remain unfiltered")
    if triggers.get("workflow_dispatch") is not None:
        raise RuffPolicyError("workflow_dispatch trigger must remain unfiltered")
    if triggers.get("push") != {"branches": ["main"]}:
        raise RuffPolicyError("push trigger must cover every main change")

    jobs = workflow.get("jobs")
    if not isinstance(jobs, Mapping):
        raise RuffPolicyError("workflow jobs must be a mapping")
    test_job = jobs.get("test")
    if not isinstance(test_job, Mapping) or set(test_job) != {
        "name",
        "runs-on",
        "timeout-minutes",
        "steps",
    }:
        raise RuffPolicyError("test job execution context differs")
    steps = test_job["steps"]

    checkout = _one_step(steps, CHECKOUT_STEP)
    if (
        set(checkout) != {"name", "uses", "with"}
        or checkout.get("uses") != CHECKOUT_ACTION
        or checkout.get("with") != {"fetch-depth": 0}
    ):
        raise RuffPolicyError("test checkout must fetch the accepted Git baseline")

    validator = _one_step(steps, VALIDATE_STEP)
    if set(validator) != {"name", "env", "run"}:
        raise RuffPolicyError("Ruff validator step can be skipped or masked")
    if validator.get("env") != {BASELINE_ENV: BASELINE_EXPRESSION}:
        raise RuffPolicyError("Ruff baseline expression differs")
    if validator.get("run") != validator_command():
        raise RuffPolicyError("Ruff validator command differs")

    executor = _one_step(steps, EXECUTE_STEP)
    if set(executor) != {"name", "run"}:
        raise RuffPolicyError("Ruff executor step can be skipped or masked")
    if executor.get("run") != executor_command():
        raise RuffPolicyError("Ruff executor command differs")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("policy", type=Path)
    parser.add_argument("--workflow", type=Path)
    parser.add_argument("--baseline-ref")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    try:
        policy = read_policy(args.policy)
        baseline = (
            policy_from_git(args.baseline_ref, args.policy)
            if args.baseline_ref is not None
            else None
        )
        validate_policy(policy, baseline=baseline)
        if args.workflow is not None:
            validate_workflow(args.workflow.read_text(encoding="utf-8"))
        if args.execute:
            execute_policy(policy)
    except (OSError, RuffPolicyError) as exc:
        print(f"Ruff policy failed: {exc}", file=sys.stderr)
        return 2
    print("Ruff policy is non-shrinking, isolated, and enforced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
