"""Preflight, validate, and execute Sector's locked dependency audit."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = Path("quality-dependency-audit.toml")
INITIAL_REQUIREMENTS = ("requirements-dev.txt", "requirements-build.txt")
REPORT_PATH = "qa-artifacts/dependency-audit.json"
CHECKOUT_STEP = "Check out source"
CHECKOUT_ACTION = "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5"
SETUP_STEP = "Set up pinned Python"
SETUP_ACTION = "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065"
PREFLIGHT_STEP = "Preflight locked dependency inputs"
INSTALL_STEP = "Install locked QA environment"
PREPARE_STEP = "Prepare QA evidence directory"
VALIDATE_STEP = "Validate dependency audit policy"
EXECUTE_STEP = "Execute locked dependency audit"
FULL_TEST_STEP = "Run complete test suite with coverage"
BASELINE_ENV = "SECTOR_DEPENDENCY_AUDIT_BASE"
BASELINE_EXPRESSION = (
    "${{ github.event.pull_request.base.sha || github.event.before || 'HEAD^' }}"
)
HASH_LINE = re.compile(r"^--hash=sha256:[0-9a-f]{64}(?:\s*\\)?$")
PIN_LINE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?:\[[A-Za-z0-9._,-]+\])?==(?P<version>[^\s;\\]+)"
    r"(?:\s*;\s*[^\\]+?)?(?:\s*\\)?$"
)
CANONICAL_NAME = re.compile(r"[-_.]+")
AUDIT_KEYS = {
    "requirements",
    "service",
    "strict",
    "require_hashes",
    "disable_pip",
    "isolated_python",
    "output_format",
    "descriptions",
    "aliases",
    "spinner",
    "timeout_seconds",
    "report_path",
    "cache_path",
    "ignored_vulnerabilities",
}
SANITISED_ENVIRONMENT = {
    "PIP_CERT",
    "PIP_CONFIG_FILE",
    "PIP_CONSTRAINT",
    "PIP_EXTRA_INDEX_URL",
    "PIP_FIND_LINKS",
    "PIP_INDEX_URL",
    "PIP_NO_INDEX",
    "PIP_REQUIREMENT",
    "PIP_TRUSTED_HOST",
    "PYTHONHOME",
    "PYTHONPATH",
}


class DependencyAuditError(ValueError):
    """Raised when the dependency gate can be weakened or is incomplete."""


@dataclass(frozen=True)
class AuditPolicy:
    """Validated settings that form the dependency-audit identity."""

    requirements: tuple[str, ...]
    report_path: str
    cache_path: str


@dataclass(frozen=True, order=True)
class LockedDependency:
    """Canonical package identity reconstructed from a flattened lock."""

    name: str
    version: str


def _nonblank(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DependencyAuditError(f"{label} must be non-empty text")
    return value.strip()


def _relative_file(value: object, label: str, root: Path) -> str:
    relative = _nonblank(value, label)
    candidate = Path(relative)
    if candidate.is_absolute():
        raise DependencyAuditError(f"{label} must be repository-relative")
    resolved_root = root.resolve()
    resolved = (resolved_root / candidate).resolve()
    if resolved_root != resolved and resolved_root not in resolved.parents:
        raise DependencyAuditError(f"{label} escapes the repository")
    return candidate.as_posix()


def _parse_policy(text: str, label: str) -> dict[str, Any]:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise DependencyAuditError(f"cannot parse {label}: {exc}") from exc


def read_policy(path: Path) -> dict[str, Any]:
    try:
        return _parse_policy(path.read_text(encoding="utf-8"), str(path))
    except OSError as exc:
        raise DependencyAuditError(f"cannot read dependency-audit policy: {exc}") from exc


def _snapshot(policy: Mapping[str, Any], root: Path) -> AuditPolicy:
    if set(policy) != {"schema_version", "audit"}:
        raise DependencyAuditError("dependency-audit top-level keys differ")
    if policy.get("schema_version") != 1:
        raise DependencyAuditError("dependency-audit schema_version must remain 1")
    audit = policy.get("audit")
    if not isinstance(audit, Mapping) or set(audit) != AUDIT_KEYS:
        raise DependencyAuditError("dependency-audit setting inventory differs")

    raw_requirements = audit.get("requirements")
    if not isinstance(raw_requirements, list) or not raw_requirements:
        raise DependencyAuditError("audit.requirements must be a non-empty array")
    requirements = tuple(
        _relative_file(value, f"audit.requirements[{index}]", root)
        for index, value in enumerate(raw_requirements)
    )
    if len(requirements) != len(set(requirements)):
        raise DependencyAuditError("audit.requirements contains duplicates")
    if requirements[: len(INITIAL_REQUIREMENTS)] != INITIAL_REQUIREMENTS:
        raise DependencyAuditError("initial lock identity or order differs")

    exact = {
        "service": "pypi",
        "strict": True,
        "require_hashes": True,
        "disable_pip": True,
        "isolated_python": True,
        "output_format": "json",
        "descriptions": "off",
        "aliases": "on",
        "spinner": "off",
        "timeout_seconds": 15,
        "ignored_vulnerabilities": [],
    }
    for key, expected in exact.items():
        if audit.get(key) != expected:
            raise DependencyAuditError(f"audit.{key} must remain {expected!r}")
    report = _relative_file(audit.get("report_path"), "audit.report_path", root)
    if report != REPORT_PATH:
        raise DependencyAuditError(
            f"audit.report_path must remain {REPORT_PATH!r}"
        )
    cache = _relative_file(audit.get("cache_path"), "audit.cache_path", root)
    if report in requirements or cache in requirements or report == cache:
        raise DependencyAuditError("audit output/cache paths collide with locked inputs")
    return AuditPolicy(requirements, report, cache)


def validate_policy(
    policy: Mapping[str, Any],
    root: Path = ROOT,
    *,
    baseline: Mapping[str, Any] | None = None,
) -> AuditPolicy:
    candidate = _snapshot(policy, root)
    if baseline is None:
        return candidate
    accepted = _snapshot(baseline, root)
    if len(candidate.requirements) < len(accepted.requirements):
        raise DependencyAuditError("accepted lock inventory shrank")
    if candidate.requirements[: len(accepted.requirements)] != accepted.requirements:
        raise DependencyAuditError(
            "accepted lock inventory must remain an exact prefix"
        )
    return candidate


def _canonicalise(name: str) -> str:
    return CANONICAL_NAME.sub("-", name).lower()


def _finish_pin(
    dependency: LockedDependency | None,
    hashes: int,
    path: Path,
) -> None:
    if dependency is not None and hashes == 0:
        raise DependencyAuditError(
            f"locked dependency lacks a SHA-256 hash in {path}: "
            f"{dependency.name}=={dependency.version}"
        )


def parse_lock(path: Path) -> tuple[LockedDependency, ...]:
    """Parse one pip-compile lock without interpreting pip control syntax."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise DependencyAuditError(f"cannot read dependency lock {path}: {exc}") from exc

    dependencies: list[LockedDependency] = []
    names: set[str] = set()
    current: LockedDependency | None = None
    hashes = 0
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("--hash"):
            if current is None:
                raise DependencyAuditError(f"orphan hash in {path}:{number}")
            if HASH_LINE.fullmatch(stripped) is None:
                raise DependencyAuditError(f"malformed SHA-256 hash in {path}:{number}")
            hashes += 1
            continue
        if stripped.startswith("-"):
            raise DependencyAuditError(
                f"unsupported lock control in {path}:{number}: {stripped}"
            )
        if line[0].isspace():
            raise DependencyAuditError(
                f"unexpected indented lock content in {path}:{number}: {stripped}"
            )

        _finish_pin(current, hashes, path)
        match = PIN_LINE.fullmatch(stripped)
        if match is None:
            raise DependencyAuditError(
                f"lock line is not an exact pinned requirement in {path}:{number}"
            )
        dependency = LockedDependency(
            _canonicalise(match.group("name")), match.group("version")
        )
        if dependency.name in names:
            raise DependencyAuditError(
                f"duplicate locked dependency in {path}: {dependency.name}"
            )
        names.add(dependency.name)
        dependencies.append(dependency)
        current = dependency
        hashes = 0

    _finish_pin(current, hashes, path)
    if not dependencies:
        raise DependencyAuditError(f"dependency lock is empty: {path}")
    return tuple(dependencies)


def lock_inventory(policy: AuditPolicy, root: Path = ROOT) -> tuple[LockedDependency, ...]:
    merged: dict[str, LockedDependency] = {}
    for relative in policy.requirements:
        for dependency in parse_lock(root / relative):
            previous = merged.get(dependency.name)
            if previous is not None and previous.version != dependency.version:
                raise DependencyAuditError(
                    "conflicting locked versions across audit inputs: "
                    f"{previous.name}=={previous.version} and "
                    f"{dependency.name}=={dependency.version}"
                )
            merged[dependency.name] = dependency
    return tuple(sorted(merged.values()))


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
        raise DependencyAuditError("dependency-audit policy escapes the repository") from exc
    _git(resolved_root, ["cat-file", "-e", f"{baseline}^{{commit}}"])
    names = _git(resolved_root, ["ls-tree", "--name-only", baseline, "--", relative])
    if relative not in names.splitlines():
        return None
    object_name = f"{baseline}:{relative}"
    return _parse_policy(_git(resolved_root, ["show", object_name]), object_name)


def preflight_command() -> str:
    return (
        "python tools/verify_dependency_audit.py "
        "quality-dependency-audit.toml --preflight-locks"
    )


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


def audit_command(policy: AuditPolicy, root: Path = ROOT) -> list[str]:
    command = [
        sys.executable,
        "-I",
        "-m",
        "pip_audit",
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
        "--cache-dir",
        str(root / policy.cache_path),
        "--output",
        str(root / policy.report_path),
    ]
    for relative in policy.requirements:
        command.extend(("--requirement", relative))
    return command


def _report_dependencies(payload: object) -> tuple[LockedDependency, ...]:
    if not isinstance(payload, Mapping) or set(payload) != {"dependencies", "fixes"}:
        raise DependencyAuditError("audit report top-level schema differs")
    if payload.get("fixes") != []:
        raise DependencyAuditError("audit report contains an unexpected fix plan")
    rows = payload.get("dependencies")
    if not isinstance(rows, list):
        raise DependencyAuditError("audit report dependencies must be an array")
    dependencies: list[LockedDependency] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or set(row) != {"name", "version", "vulns"}:
            raise DependencyAuditError(f"audit report dependency[{index}] schema differs")
        name = _canonicalise(_nonblank(row.get("name"), f"dependency[{index}].name"))
        version = _nonblank(row.get("version"), f"dependency[{index}].version")
        if name in seen:
            raise DependencyAuditError(f"duplicate audit report dependency: {name}")
        seen.add(name)
        vulns = row.get("vulns")
        if not isinstance(vulns, list):
            raise DependencyAuditError(f"dependency[{index}].vulns must be an array")
        if vulns:
            identifiers = [
                item.get("id", "unknown") if isinstance(item, Mapping) else "malformed"
                for item in vulns
            ]
            raise DependencyAuditError(
                f"vulnerable dependency {name}=={version}: {identifiers}"
            )
        dependencies.append(LockedDependency(name, version))
    return tuple(sorted(dependencies))


def validate_report(path: Path, expected: Sequence[LockedDependency]) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DependencyAuditError(f"cannot read audit JSON report: {exc}") from exc
    actual = _report_dependencies(payload)
    canonical = tuple(sorted(expected))
    if actual != canonical:
        expected_map = {item.name: item.version for item in canonical}
        actual_map = {item.name: item.version for item in actual}
        missing = sorted(set(expected_map) - set(actual_map))
        extra = sorted(set(actual_map) - set(expected_map))
        changed = sorted(
            name
            for name in set(expected_map) & set(actual_map)
            if expected_map[name] != actual_map[name]
        )
        raise DependencyAuditError(
            "audit report does not reproduce the locked union: "
            f"missing={missing}, extra={extra}, changed={changed}"
        )


def execute_policy(
    policy_path: Path,
    root: Path = ROOT,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    policy = validate_policy(read_policy(policy_path), root)
    expected = lock_inventory(policy, root)
    report = root / policy.report_path
    if report.exists():
        raise DependencyAuditError("audit report already exists and will not be overwritten")
    if not report.parent.is_dir():
        raise DependencyAuditError("audit report directory must exist before execution")
    cache = root / policy.cache_path
    cache.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    for name in SANITISED_ENVIRONMENT:
        environment.pop(name, None)
    environment["PIP_CONFIG_FILE"] = os.devnull
    environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    completed = runner(
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
    validate_report(report, expected)


def _workflow(text: str) -> Mapping[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise DependencyAuditError(
            "PyYAML is required only for the post-install workflow validation"
        ) from exc
    try:
        workflow = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise DependencyAuditError(f"cannot parse workflow YAML: {exc}") from exc
    if not isinstance(workflow, Mapping):
        raise DependencyAuditError("workflow must be a mapping")
    return workflow


def _one_step(steps: object, name: str) -> tuple[int, Mapping[str, Any]]:
    if not isinstance(steps, list):
        raise DependencyAuditError("test job steps must be an array")
    found = [
        (index, step)
        for index, step in enumerate(steps)
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
    job = jobs.get("test")
    if not isinstance(job, Mapping) or set(job) != {
        "name",
        "runs-on",
        "timeout-minutes",
        "steps",
    }:
        raise DependencyAuditError("test job execution context differs")
    if job.get("name") != "Full test and report gate":
        raise DependencyAuditError("test job name differs")
    if job.get("runs-on") != "windows-latest" or job.get("timeout-minutes") != 90:
        raise DependencyAuditError("test job Windows identity or timeout differs")
    steps = job.get("steps")

    checkout_index, checkout = _one_step(steps, CHECKOUT_STEP)
    if (
        set(checkout) != {"name", "uses", "with"}
        or checkout.get("uses") != CHECKOUT_ACTION
        or checkout.get("with") != {"fetch-depth": 0}
    ):
        raise DependencyAuditError("test checkout must fetch the exact Git baseline")
    setup_index, setup = _one_step(steps, SETUP_STEP)
    if (
        set(setup) != {"name", "uses", "with"}
        or setup.get("uses") != SETUP_ACTION
        or setup.get("with")
        != {
            "python-version-file": ".python-version",
            "cache": "pip",
            "cache-dependency-path": "requirements-dev.txt",
        }
    ):
        raise DependencyAuditError("test Python setup identity differs")

    preflight_index, preflight = _one_step(steps, PREFLIGHT_STEP)
    if set(preflight) != {"name", "run"} or preflight.get("run") != preflight_command():
        raise DependencyAuditError("dependency preflight can be skipped or masked")
    install_index, install = _one_step(steps, INSTALL_STEP)
    if set(install) != {"name", "run"} or install.get("run") != (
        "python -m pip install --require-hashes -r requirements-dev.txt"
    ):
        raise DependencyAuditError("locked QA install can be skipped or weakened")
    prepare_index, prepare = _one_step(steps, PREPARE_STEP)
    if set(prepare) != {"name", "shell", "run"} or prepare != {
        "name": PREPARE_STEP,
        "shell": "pwsh",
        "run": "New-Item -ItemType Directory -Path qa-artifacts -Force | Out-Null",
    }:
        raise DependencyAuditError("QA evidence preparation differs")
    validate_index, validator = _one_step(steps, VALIDATE_STEP)
    if set(validator) != {"name", "env", "run"}:
        raise DependencyAuditError("dependency validator can be skipped or masked")
    if validator.get("env") != {BASELINE_ENV: BASELINE_EXPRESSION}:
        raise DependencyAuditError("dependency baseline expression differs")
    if validator.get("run") != validator_command():
        raise DependencyAuditError("dependency validator command differs")
    execute_index, executor = _one_step(steps, EXECUTE_STEP)
    if set(executor) != {"name", "run"} or executor.get("run") != executor_command():
        raise DependencyAuditError("dependency executor can be skipped or masked")
    full_test_index, _ = _one_step(steps, FULL_TEST_STEP)
    if not (
        checkout_index
        < setup_index
        < preflight_index
        < install_index
        < prepare_index
        < validate_index
        < execute_index
        < full_test_index
    ):
        raise DependencyAuditError("dependency gate workflow order differs")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("policy", type=Path)
    parser.add_argument("--preflight-locks", action="store_true")
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
        snapshot = validate_policy(policy, baseline=baseline)
        if args.preflight_locks:
            lock_inventory(snapshot)
        if args.workflow is not None:
            validate_workflow(args.workflow.read_text(encoding="utf-8"))
        if args.execute:
            execute_policy(args.policy)
    except (OSError, DependencyAuditError) as exc:
        print(f"dependency audit policy failed: {exc}", file=sys.stderr)
        return 2
    print("locked dependency audit policy is complete and enforced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
