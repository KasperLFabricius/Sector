"""Verify and execute Sector's accepted-base dependency audit policy."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomllib
import yaml

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = Path("quality-dependency-audit.toml")
INITIAL_REQUIREMENTS = (
    "requirements-dev.txt",
    "requirements-build.txt",
)
VALIDATE_STEP = "Validate dependency audit policy ratchet"
EXECUTE_STEP = "Execute dependency vulnerability audit"
INSTALL_STEP = "Install locked QA environment"
PREPARE_STEP = "Prepare QA evidence directory"
FULL_TEST_STEP = "Run complete test suite with coverage"
CHECKOUT_STEP = "Check out source"
CHECKOUT_ACTION = "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5"
BASELINE_ENV = "SECTOR_DEPENDENCY_AUDIT_BASE"
BASELINE_EXPRESSION = (
    "${{ github.event.pull_request.base.sha || github.event.before || 'HEAD^' }}"
)
INSTALL_COMMAND = "python -m pip install --require-hashes -r requirements-dev.txt"
PREPARE_COMMAND = "New-Item -ItemType Directory -Path qa-artifacts -Force | Out-Null"
OUTPUT_PATH = "qa-artifacts/dependency-audit.json"
CACHE_PATH = ".qa-cache/pip-audit"
PIN = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^\s;\\]+)"
    r"(?:\s*;[^\\]+)?\s*\\?$"
)
HASH = re.compile(r"^--hash=sha256:[0-9a-f]{64}(?:\s*\\)?$")


class DependencyAuditError(ValueError):
    """Raised when dependency coverage is incomplete, weaker, or bypassed."""


@dataclass(frozen=True)
class AuditIdentity:
    """Settings that may expand but cannot shrink after acceptance."""

    requirements: tuple[str, ...]


def _nonblank(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DependencyAuditError(f"{label} must be non-empty text")
    return value.strip()


def _text_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise DependencyAuditError(f"{label} must be a non-empty text list")
    items = [_nonblank(item, label) for item in value]
    if len(items) != len(set(items)):
        raise DependencyAuditError(f"{label} contains duplicates")
    return items


def _safe_path(
    value: object,
    root: Path,
    label: str,
    *,
    must_exist: bool,
) -> tuple[str, Path]:
    relative = _nonblank(value, label)
    candidate = Path(relative)
    if candidate.is_absolute():
        raise DependencyAuditError(f"{label} must be repository-relative")
    resolved_root = root.resolve()
    resolved = (resolved_root / candidate).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise DependencyAuditError(f"{label} escapes the repository")
    if must_exist and not resolved.is_file():
        raise DependencyAuditError(f"{label} does not exist: {relative}")
    return candidate.as_posix(), resolved


def _validated_requirements(value: object, root: Path) -> list[str]:
    requirements = _text_list(value, "audit.requirements")
    normalized: list[str] = []
    for relative in requirements:
        path_text, _ = _safe_path(
            relative,
            root,
            "audit requirement",
            must_exist=True,
        )
        if not path_text.endswith(".txt"):
            raise DependencyAuditError("audit requirements must be lock text files")
        normalized.append(path_text)
    if tuple(normalized)[: len(INITIAL_REQUIREMENTS)] != INITIAL_REQUIREMENTS:
        raise DependencyAuditError("initial audit lock identity or order differs")
    return normalized


def _parse_policy(text: str, label: str) -> dict[str, Any]:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise DependencyAuditError(f"cannot parse {label}: {exc}") from exc


def read_policy(path: Path) -> dict[str, Any]:
    try:
        return _parse_policy(path.read_text(encoding="utf-8"), str(path))
    except OSError as exc:
        raise DependencyAuditError(f"cannot read dependency audit policy: {exc}") from exc


def _snapshot(policy: Mapping[str, Any], root: Path) -> AuditIdentity:
    if set(policy) != {"schema_version", "audit"}:
        raise DependencyAuditError("dependency audit top-level keys differ")
    if policy.get("schema_version") != 1:
        raise DependencyAuditError("dependency audit schema_version must remain 1")
    audit = policy.get("audit")
    expected_keys = {
        "requirements",
        "vulnerability_service",
        "strict",
        "require_hashes",
        "disable_pip",
        "python_isolated",
        "progress_spinner",
        "format",
        "descriptions",
        "aliases",
        "timeout_seconds",
        "output_path",
        "cache_path",
        "ignored_vulnerabilities",
    }
    if not isinstance(audit, Mapping) or set(audit) != expected_keys:
        raise DependencyAuditError("audit setting inventory differs")

    requirements = _validated_requirements(audit.get("requirements"), root)
    exact_values: dict[str, object] = {
        "vulnerability_service": "pypi",
        "strict": True,
        "require_hashes": True,
        "disable_pip": True,
        "python_isolated": True,
        "progress_spinner": "off",
        "format": "json",
        "descriptions": "off",
        "aliases": "on",
        "timeout_seconds": 15,
        "output_path": OUTPUT_PATH,
        "cache_path": CACHE_PATH,
        "ignored_vulnerabilities": [],
    }
    for name, expected in exact_values.items():
        if audit.get(name) != expected:
            raise DependencyAuditError(f"audit.{name} differs from the fail-closed policy")

    _safe_path(audit.get("output_path"), root, "audit.output_path", must_exist=False)
    _safe_path(audit.get("cache_path"), root, "audit.cache_path", must_exist=False)
    return AuditIdentity(requirements=tuple(requirements))


def validate_policy(
    policy: Mapping[str, Any],
    root: Path = ROOT,
    *,
    baseline: Mapping[str, Any] | None = None,
) -> None:
    candidate = _snapshot(policy, root)
    if baseline is None:
        return
    accepted = _snapshot(baseline, root)
    if len(candidate.requirements) < len(accepted.requirements):
        raise DependencyAuditError("accepted dependency lock inventory shrank")
    if candidate.requirements[: len(accepted.requirements)] != accepted.requirements:
        raise DependencyAuditError(
            "accepted dependency locks must remain an exact candidate prefix"
        )


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
        raise DependencyAuditError(f"Git baseline inspection failed: {detail}")
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
        raise DependencyAuditError("dependency audit policy path escapes the repository") from exc
    _git(resolved_root, ["cat-file", "-e", f"{baseline}^{{commit}}"])
    names = _git(resolved_root, ["ls-tree", "--name-only", baseline, "--", relative])
    if relative not in names.splitlines():
        return None
    object_name = f"{baseline}:{relative}"
    return _parse_policy(_git(resolved_root, ["show", object_name]), object_name)


def _canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def lock_inventory(requirements: Sequence[str], root: Path = ROOT) -> dict[str, str]:
    inventory: dict[str, str] = {}
    for relative in requirements:
        _, path = _safe_path(relative, root, "audit requirement", must_exist=True)
        current: tuple[str, int] | None = None
        hash_count = 0
        seen_in_lock: set[str] = set()
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            stripped = line.strip()
            if "--hash=sha256:" in stripped:
                if HASH.fullmatch(stripped) is None:
                    raise DependencyAuditError(
                        f"malformed requirement hash in {relative}:{line_number}"
                    )
                hash_count += 1
                continue
            if not stripped or stripped.startswith("#") or line[0].isspace():
                continue
            if stripped.startswith("-"):
                raise DependencyAuditError(
                    f"unsupported lock control in {relative}:{line_number}"
                )
            if current is not None and hash_count == 0:
                raise DependencyAuditError(
                    f"unhashed requirement in {relative}:{current[1]}"
                )
            match = PIN.fullmatch(stripped)
            if match is None:
                raise DependencyAuditError(
                    f"non-exact requirement in {relative}:{line_number}"
                )
            name = _canonical_name(match.group("name"))
            version = match.group("version")
            if name in seen_in_lock:
                raise DependencyAuditError(
                    f"duplicate requirement in {relative}:{line_number}: {name}"
                )
            seen_in_lock.add(name)
            existing = inventory.get(name)
            if existing is not None and existing != version:
                raise DependencyAuditError(
                    f"conflicting audited versions for {name}: {existing} and {version}"
                )
            inventory[name] = version
            current = (name, line_number)
            hash_count = 0
        if current is None:
            raise DependencyAuditError(f"audit requirement is empty: {relative}")
        if hash_count == 0:
            raise DependencyAuditError(f"unhashed requirement in {relative}:{current[1]}")
    if not inventory:
        raise DependencyAuditError("dependency lock inventory is empty")
    return inventory


def verify_report(path: Path, expected: Mapping[str, str]) -> None:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DependencyAuditError(f"cannot read dependency audit report: {exc}") from exc
    if not isinstance(report, Mapping) or set(report) != {"dependencies", "fixes"}:
        raise DependencyAuditError("dependency audit report keys differ")
    if report.get("fixes") != []:
        raise DependencyAuditError("dependency audit must not contain fix records")
    dependencies = report.get("dependencies")
    if not isinstance(dependencies, list):
        raise DependencyAuditError("dependency audit rows must be an array")

    observed: dict[str, str] = {}
    for index, row in enumerate(dependencies):
        label = f"dependency audit row {index}"
        if not isinstance(row, Mapping) or set(row) != {"name", "version", "vulns"}:
            raise DependencyAuditError(f"{label} is skipped, unknown or malformed")
        raw_name = _nonblank(row.get("name"), f"{label}.name")
        name = _canonical_name(raw_name)
        if raw_name != name:
            raise DependencyAuditError(f"{label}.name is not canonical")
        version = _nonblank(row.get("version"), f"{label}.version")
        if row.get("vulns") != []:
            raise DependencyAuditError(f"{label} contains a known vulnerability")
        if name in observed:
            raise DependencyAuditError(f"duplicate dependency audit row: {name}")
        observed[name] = version

    if observed != dict(expected):
        missing = sorted(set(expected) - set(observed))
        extra = sorted(set(observed) - set(expected))
        changed = sorted(
            name
            for name in set(expected) & set(observed)
            if expected[name] != observed[name]
        )
        raise DependencyAuditError(
            "dependency audit inventory differs: "
            f"missing={missing}, extra={extra}, version_changed={changed}"
        )


def audit_command(policy: Mapping[str, Any], root: Path = ROOT) -> list[str]:
    identity = _snapshot(policy, root)
    command = [
        sys.executable,
        "-I",
        "-m",
        "pip_audit",
        "--strict",
        "--require-hashes",
        "--disable-pip",
        "--progress-spinner",
        "off",
        "--vulnerability-service",
        "pypi",
        "--format",
        "json",
        "--desc",
        "off",
        "--aliases",
        "on",
        "--timeout",
        "15",
        "--cache-dir",
        CACHE_PATH,
        "--output",
        OUTPUT_PATH,
    ]
    for requirement in identity.requirements:
        command.extend(("-r", requirement))
    return command


Runner = Callable[..., subprocess.CompletedProcess[str]]


def execute_policy(
    policy_path: Path,
    root: Path = ROOT,
    *,
    runner: Runner | None = None,
) -> None:
    policy = read_policy(policy_path)
    validate_policy(policy, root)
    audit = policy["audit"]
    _, output = _safe_path(
        audit["output_path"],
        root,
        "audit.output_path",
        must_exist=False,
    )
    if output.exists():
        raise DependencyAuditError(f"dependency audit evidence already exists: {output}")
    if not output.parent.is_dir():
        raise DependencyAuditError(
            f"dependency audit evidence directory does not exist: {output.parent}"
        )

    environment = os.environ.copy()
    for name in tuple(environment):
        if name in {"PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP"} or name.startswith(
            "PIP_"
        ):
            environment.pop(name, None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONSAFEPATH"] = "1"
    invoke = subprocess.run if runner is None else runner
    completed = invoke(
        audit_command(policy, root),
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise DependencyAuditError(
            f"dependency audit failed with exit code {completed.returncode}: {detail}"
        )
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    verify_report(output, lock_inventory(audit["requirements"], root))


def validator_command() -> str:
    return (
        "python tools/verify_dependency_audit.py quality-dependency-audit.toml "
        "--workflow .github/workflows/qa.yml "
        "--baseline-ref $env:SECTOR_DEPENDENCY_AUDIT_BASE"
    )


def executor_command() -> str:
    return (
        "python tools/verify_dependency_audit.py "
        "quality-dependency-audit.toml --execute"
    )


def _workflow(text: str) -> Mapping[str, Any]:
    try:
        workflow = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise DependencyAuditError(f"cannot parse workflow YAML: {exc}") from exc
    if not isinstance(workflow, Mapping):
        raise DependencyAuditError("workflow must be a mapping")
    return workflow


def _one_step(steps: object, name: str) -> Mapping[str, Any]:
    if not isinstance(steps, list):
        raise DependencyAuditError("test job steps must be an array")
    found = [
        step
        for step in steps
        if isinstance(step, Mapping) and step.get("name") == name
    ]
    if len(found) != 1:
        raise DependencyAuditError(f"workflow must contain one {name!r} step")
    return found[0]


def validate_workflow(text: str) -> None:
    workflow = _workflow(text)
    triggers = workflow.get("on", workflow.get(True))
    if not isinstance(triggers, Mapping) or set(triggers) != {
        "pull_request",
        "push",
        "workflow_dispatch",
    }:
        raise DependencyAuditError("workflow trigger inventory differs")
    if triggers.get("pull_request") is not None:
        raise DependencyAuditError("pull_request trigger must remain unfiltered")
    if triggers.get("workflow_dispatch") is not None:
        raise DependencyAuditError("workflow_dispatch trigger must remain unfiltered")
    if triggers.get("push") != {"branches": ["main"]}:
        raise DependencyAuditError("push trigger must cover every main change")

    jobs = workflow.get("jobs")
    if not isinstance(jobs, Mapping):
        raise DependencyAuditError("workflow jobs must be a mapping")
    test_job = jobs.get("test")
    if not isinstance(test_job, Mapping) or set(test_job) != {
        "name",
        "runs-on",
        "timeout-minutes",
        "steps",
    }:
        raise DependencyAuditError("test job execution context differs")
    if (
        test_job.get("name") != "Full test and report gate"
        or test_job.get("runs-on") != "windows-latest"
        or test_job.get("timeout-minutes") != 60
    ):
        raise DependencyAuditError("test job execution identity differs")
    steps = test_job["steps"]

    checkout = _one_step(steps, CHECKOUT_STEP)
    if (
        set(checkout) != {"name", "uses", "with"}
        or checkout.get("uses") != CHECKOUT_ACTION
        or checkout.get("with") != {"fetch-depth": 0}
    ):
        raise DependencyAuditError("test checkout must fetch the accepted Git baseline")

    install = _one_step(steps, INSTALL_STEP)
    if set(install) != {"name", "run"} or install.get("run") != INSTALL_COMMAND:
        raise DependencyAuditError("locked QA install can be skipped, masked or weakened")
    prepare = _one_step(steps, PREPARE_STEP)
    if (
        set(prepare) != {"name", "shell", "run"}
        or prepare.get("shell") != "pwsh"
        or prepare.get("run") != PREPARE_COMMAND
    ):
        raise DependencyAuditError("QA evidence preparation differs")

    validator = _one_step(steps, VALIDATE_STEP)
    if set(validator) != {"name", "env", "run"}:
        raise DependencyAuditError("dependency audit validator can be skipped or masked")
    if validator.get("env") != {BASELINE_ENV: BASELINE_EXPRESSION}:
        raise DependencyAuditError("dependency audit baseline expression differs")
    if validator.get("run") != validator_command():
        raise DependencyAuditError("dependency audit validator command differs")

    executor = _one_step(steps, EXECUTE_STEP)
    if set(executor) != {"name", "run"}:
        raise DependencyAuditError("dependency audit executor can be skipped or masked")
    if executor.get("run") != executor_command():
        raise DependencyAuditError("dependency audit executor command differs")

    full_test = _one_step(steps, FULL_TEST_STEP)
    ordered_names = [
        step.get("name")
        for step in steps
        if isinstance(step, Mapping)
    ]
    if not (
        ordered_names.index(INSTALL_STEP)
        < ordered_names.index(PREPARE_STEP)
        < ordered_names.index(VALIDATE_STEP)
        < ordered_names.index(EXECUTE_STEP)
        < ordered_names.index(FULL_TEST_STEP)
    ):
        raise DependencyAuditError("dependency audit step order differs")
    if full_test.get("run") is None:
        raise DependencyAuditError("complete test step is malformed")


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
    except (OSError, DependencyAuditError) as exc:
        print(f"dependency audit policy failed: {exc}", file=sys.stderr)
        return 2
    print("dependency audit policy is complete, non-shrinking and enforced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
