"""Verify and execute Sector's accepted-base strict-mypy policy."""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
import tokenize
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomllib
import yaml

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = Path("quality-mypy-policy.toml")
INITIAL_FILES = (
    "sector/bridge.py",
    "app/bridge_analysis.py",
    "app/manual_equation_contract.py",
    "app/manual_equation_publication.py",
)
CURRENT_WAIVERS = {"mypy-imported-module-debt"}
FOLLOW_IMPORT_STRENGTH = {"silent": 0, "normal": 1}
VALIDATE_STEP = "Validate mypy policy ratchet"
EXECUTE_STEP = "Execute strict mypy policy"
CHECKOUT_STEP = "Check out source"
CHECKOUT_ACTION = "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5"
BASELINE_ENV = "SECTOR_MYPY_POLICY_BASE"
BASELINE_EXPRESSION = (
    "${{ github.event.pull_request.base.sha || github.event.before || 'HEAD^' }}"
)
TYPE_IGNORE = re.compile(r"^#\s*type:\s*ignore(?:\b|\[)", re.IGNORECASE)
MYPY_DIRECTIVE = re.compile(r"^#\s*mypy\s*:", re.IGNORECASE)
TYPING_MODULES = {"typing", "typing_extensions"}


class MypyPolicyError(ValueError):
    """Raised when the type policy is incomplete, weaker, or bypassed."""


@dataclass(frozen=True)
class MypyIdentity:
    """Settings that form the accepted mypy policy identity."""

    files: tuple[str, ...]
    follow_imports: str


def _nonblank(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MypyPolicyError(f"{label} must be non-empty text")
    return value.strip()


def _text_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise MypyPolicyError(f"{label} must be a non-empty text list")
    items = [_nonblank(item, label) for item in value]
    if len(items) != len(set(items)):
        raise MypyPolicyError(f"{label} contains duplicates")
    return items


def _validated_files(value: object, root: Path) -> list[str]:
    files = _text_list(value, "tool.mypy.files")
    resolved_root = root.resolve()
    for relative in files:
        resolved = (resolved_root / relative).resolve()
        if resolved_root not in resolved.parents:
            raise MypyPolicyError("tool.mypy.files escapes the repository")
        if not resolved.is_file():
            raise MypyPolicyError(f"typed boundary file does not exist: {relative}")
    return files


def _comments(path: Path) -> list[tuple[int, str]]:
    try:
        with tokenize.open(path) as source:
            return [
                (token.start[0], token.string.strip())
                for token in tokenize.generate_tokens(source.readline)
                if token.type == tokenize.COMMENT
            ]
    except (OSError, SyntaxError, tokenize.TokenError) as exc:
        raise MypyPolicyError(f"cannot inspect type suppressions in {path}: {exc}") from exc


def _syntax_tree(path: Path) -> ast.Module:
    try:
        with tokenize.open(path) as source:
            text = source.read()
        return ast.parse(text, filename=str(path))
    except (OSError, SyntaxError, UnicodeError) as exc:
        raise MypyPolicyError(f"cannot inspect type decorators in {path}: {exc}") from exc


def _assigned_names(target: ast.expr) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.List, ast.Tuple)):
        return {
            name
            for item in target.elts
            for name in _assigned_names(item)
        }
    return set()


def _is_typing_module_reference(node: ast.expr, module_names: set[str]) -> bool:
    return isinstance(node, ast.Name) and node.id in module_names


def _is_no_type_check_reference(
    node: ast.expr,
    module_names: set[str],
    decorator_names: set[str],
) -> bool:
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Name):
        return node.id in decorator_names
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "no_type_check"
        and _is_typing_module_reference(node.value, module_names)
    )


def _reject_no_type_check_decorators(path: Path, relative: str) -> None:
    tree = _syntax_tree(path)
    module_names: set[str] = set()
    decorator_names: set[str] = set()
    assignments: list[tuple[set[str], ast.expr]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for imported in node.names:
                if imported.name in TYPING_MODULES:
                    module_names.add(imported.asname or imported.name)
        elif isinstance(node, ast.ImportFrom) and node.module in TYPING_MODULES:
            for imported in node.names:
                if imported.name in {"no_type_check", "*"}:
                    decorator_names.add(imported.asname or "no_type_check")
        elif isinstance(node, ast.Assign):
            names = {
                name
                for target in node.targets
                for name in _assigned_names(target)
            }
            if names:
                assignments.append((names, node.value))
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            names = _assigned_names(node.target)
            if names:
                assignments.append((names, node.value))

    changed = True
    while changed:
        changed = False
        for names, value in assignments:
            if _is_typing_module_reference(value, module_names):
                previous = len(module_names)
                module_names.update(names)
                changed = changed or len(module_names) != previous
            if _is_no_type_check_reference(value, module_names, decorator_names):
                previous = len(decorator_names)
                decorator_names.update(names)
                changed = changed or len(decorator_names) != previous

    for node in ast.walk(tree):
        for decorator in getattr(node, "decorator_list", ()):
            if _is_no_type_check_reference(
                decorator,
                module_names,
                decorator_names,
            ):
                line = getattr(decorator, "lineno", getattr(node, "lineno", 0))
                raise MypyPolicyError(
                    f"unowned no_type_check decorator in {relative}:{line}"
                )


def _reject_source_suppressions(files: Sequence[str], root: Path) -> None:
    for relative in files:
        path = root / relative
        for line, comment in _comments(path):
            if TYPE_IGNORE.match(comment):
                raise MypyPolicyError(
                    f"unowned type: ignore suppression in {relative}:{line}"
                )
            if MYPY_DIRECTIVE.match(comment):
                raise MypyPolicyError(
                    f"unowned file-level mypy directive in {relative}:{line}"
                )
        _reject_no_type_check_decorators(path, relative)


def _parse_policy(text: str, label: str) -> dict[str, Any]:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise MypyPolicyError(f"cannot parse {label}: {exc}") from exc


def read_policy(path: Path) -> dict[str, Any]:
    try:
        return _parse_policy(path.read_text(encoding="utf-8"), str(path))
    except OSError as exc:
        raise MypyPolicyError(f"cannot read mypy policy: {exc}") from exc


def _snapshot(
    policy: Mapping[str, Any],
    root: Path,
    *,
    required_waivers: set[str] | None,
    scan_sources: bool,
) -> MypyIdentity:
    if set(policy) != {"tool", "sector_policy"}:
        raise MypyPolicyError("mypy policy top-level keys differ")
    tool = policy.get("tool")
    if not isinstance(tool, Mapping) or set(tool) != {"mypy"}:
        raise MypyPolicyError("tool table must contain only mypy")
    mypy = tool.get("mypy")
    if not isinstance(mypy, Mapping) or set(mypy) != {
        "python_version",
        "strict",
        "follow_imports",
        "incremental",
        "files",
    }:
        raise MypyPolicyError("tool.mypy setting inventory differs")
    if mypy.get("python_version") != "3.13":
        raise MypyPolicyError("mypy python_version must remain 3.13")
    if mypy.get("strict") is not True:
        raise MypyPolicyError("strict mypy cannot be disabled")
    if mypy.get("incremental") is not False:
        raise MypyPolicyError("mypy must run without incremental cache")
    follow_imports = _nonblank(mypy.get("follow_imports"), "follow_imports")
    if follow_imports not in FOLLOW_IMPORT_STRENGTH:
        raise MypyPolicyError("follow_imports is unsupported or weaker than silent")
    files = _validated_files(mypy.get("files"), root)
    if tuple(files)[: len(INITIAL_FILES)] != INITIAL_FILES:
        raise MypyPolicyError("initial typed boundary identity or order differs")
    if scan_sources:
        _reject_source_suppressions(files, root)

    sector_policy = policy.get("sector_policy")
    if not isinstance(sector_policy, Mapping) or set(sector_policy) != {
        "schema_version",
        "waivers",
    }:
        raise MypyPolicyError("sector_policy keys differ")
    if sector_policy.get("schema_version") != 1:
        raise MypyPolicyError("sector_policy schema_version must remain 1")
    raw_waivers = sector_policy.get("waivers")
    if not isinstance(raw_waivers, list):
        raise MypyPolicyError("mypy waivers must be an array")
    waiver_ids: set[str] = set()
    targets: set[tuple[str, str]] = set()
    for index, raw in enumerate(raw_waivers):
        label = f"sector_policy.waivers[{index}]"
        if not isinstance(raw, Mapping) or set(raw) != {
            "id",
            "setting",
            "value",
            "owner",
            "reason",
            "exit_condition",
        }:
            raise MypyPolicyError(f"{label} keys differ")
        waiver_id = _nonblank(raw.get("id"), f"{label}.id")
        if waiver_id in waiver_ids:
            raise MypyPolicyError(f"duplicate mypy waiver: {waiver_id}")
        waiver_ids.add(waiver_id)
        setting = _nonblank(raw.get("setting"), f"{label}.setting")
        value = _nonblank(raw.get("value"), f"{label}.value")
        target = (setting, value)
        if target in targets:
            raise MypyPolicyError(f"duplicate mypy waiver target: {target}")
        targets.add(target)
        for field in ("owner", "reason", "exit_condition"):
            _nonblank(raw.get(field), f"{label}.{field}")

    expected_targets = (
        {("follow_imports", "silent")} if follow_imports == "silent" else set()
    )
    if targets != expected_targets:
        raise MypyPolicyError("mypy waiver does not match the weakened setting")
    if required_waivers is not None and waiver_ids != required_waivers:
        raise MypyPolicyError("mypy waiver inventory differs")
    return MypyIdentity(files=tuple(files), follow_imports=follow_imports)


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
    candidate = _snapshot(
        policy,
        root,
        required_waivers=required,
        scan_sources=True,
    )
    if baseline is None:
        return
    accepted = _snapshot(
        baseline,
        root,
        required_waivers=None,
        scan_sources=False,
    )
    if not set(accepted.files) <= set(candidate.files):
        raise MypyPolicyError("accepted typed boundary inventory shrank")
    if not _ordered_subset(accepted.files, candidate.files):
        raise MypyPolicyError("accepted typed boundary order changed")
    if FOLLOW_IMPORT_STRENGTH[candidate.follow_imports] < FOLLOW_IMPORT_STRENGTH[
        accepted.follow_imports
    ]:
        raise MypyPolicyError("follow_imports weakened below the accepted baseline")


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
        raise MypyPolicyError(f"Git baseline inspection failed: {detail}")
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
        raise MypyPolicyError("mypy policy path escapes the repository") from exc
    _git(resolved_root, ["cat-file", "-e", f"{baseline}^{{commit}}"])
    names = _git(resolved_root, ["ls-tree", "--name-only", baseline, "--", relative])
    if relative not in names.splitlines():
        return None
    object_name = f"{baseline}:{relative}"
    return _parse_policy(_git(resolved_root, ["show", object_name]), object_name)


def execute_policy(
    policy_path: Path,
    root: Path = ROOT,
    *,
    executable: str = "mypy",
) -> None:
    environment = os.environ.copy()
    environment.pop("MYPYPATH", None)
    environment.pop("MYPY_CONFIG_FILE", None)
    completed = subprocess.run(
        [executable, "--config-file", str(policy_path)],
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stdout.strip() or completed.stderr.strip()
        raise MypyPolicyError(
            f"strict mypy failed with exit code {completed.returncode}: {detail}"
        )


def validator_command() -> str:
    return (
        "python tools/verify_mypy_policy.py quality-mypy-policy.toml "
        "--workflow .github/workflows/qa.yml "
        "--baseline-ref $env:SECTOR_MYPY_POLICY_BASE"
    )


def executor_command() -> str:
    return "python tools/verify_mypy_policy.py quality-mypy-policy.toml --execute"


def _workflow(text: str) -> Mapping[str, Any]:
    try:
        workflow = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise MypyPolicyError(f"cannot parse workflow YAML: {exc}") from exc
    if not isinstance(workflow, Mapping):
        raise MypyPolicyError("workflow must be a mapping")
    return workflow


def _one_step(steps: object, name: str) -> Mapping[str, Any]:
    if not isinstance(steps, list):
        raise MypyPolicyError("test job steps must be an array")
    found = [
        step
        for step in steps
        if isinstance(step, Mapping) and step.get("name") == name
    ]
    if len(found) != 1:
        raise MypyPolicyError(f"workflow must contain one {name!r} step")
    return found[0]


def validate_workflow(text: str) -> None:
    workflow = _workflow(text)
    triggers = workflow.get("on", workflow.get(True))
    if not isinstance(triggers, Mapping) or set(triggers) != {
        "pull_request",
        "push",
        "workflow_dispatch",
    }:
        raise MypyPolicyError("workflow trigger inventory differs")
    if triggers.get("pull_request") is not None:
        raise MypyPolicyError("pull_request trigger must remain unfiltered")
    if triggers.get("workflow_dispatch") is not None:
        raise MypyPolicyError("workflow_dispatch trigger must remain unfiltered")
    if triggers.get("push") != {"branches": ["main"]}:
        raise MypyPolicyError("push trigger must cover every main change")

    jobs = workflow.get("jobs")
    if not isinstance(jobs, Mapping):
        raise MypyPolicyError("workflow jobs must be a mapping")
    test_job = jobs.get("test")
    if not isinstance(test_job, Mapping) or set(test_job) != {
        "name",
        "runs-on",
        "timeout-minutes",
        "steps",
    }:
        raise MypyPolicyError("test job execution context differs")
    steps = test_job["steps"]

    checkout = _one_step(steps, CHECKOUT_STEP)
    if (
        set(checkout) != {"name", "uses", "with"}
        or checkout.get("uses") != CHECKOUT_ACTION
        or checkout.get("with") != {"fetch-depth": 0}
    ):
        raise MypyPolicyError("test checkout must fetch the accepted Git baseline")

    validator = _one_step(steps, VALIDATE_STEP)
    if set(validator) != {"name", "env", "run"}:
        raise MypyPolicyError("mypy validator step can be skipped or masked")
    if validator.get("env") != {BASELINE_ENV: BASELINE_EXPRESSION}:
        raise MypyPolicyError("mypy baseline expression differs")
    if validator.get("run") != validator_command():
        raise MypyPolicyError("mypy validator command differs")

    executor = _one_step(steps, EXECUTE_STEP)
    if set(executor) != {"name", "run"}:
        raise MypyPolicyError("mypy executor step can be skipped or masked")
    if executor.get("run") != executor_command():
        raise MypyPolicyError("mypy executor command differs")


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
            execute_policy(args.policy)
    except (OSError, MypyPolicyError) as exc:
        print(f"mypy policy failed: {exc}", file=sys.stderr)
        return 2
    print("strict mypy policy is non-shrinking and enforced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
