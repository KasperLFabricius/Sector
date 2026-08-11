"""Validate Sector's final fail-closed QA and publication workflow chain."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

CONSOLIDATED_STEP = "Validate consolidated publication gate"
CHECKOUT_ACTION = "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5"
SETUP_PYTHON_ACTION = (
    "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065"
)
UPLOAD_ACTION = "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"
DOWNLOAD_ACTION = (
    "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093"
)
FULL_COMMIT_ACTION = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}$")
SECRET_CONTEXT = re.compile(r"\bsecrets\b\s*(?:\.|\[)", re.IGNORECASE)
JOB_CONTRACT_SHA256 = {
    "test": "4b220d25de52b376ed6ce47f1b123be8989ba7832835f992e9aee4bca91c805f",
    "windows-package": (
        "b1d2dc20ddfbbe626296637a3c240c38873bccc18e118c664acde1ffc9e0f8a1"
    ),
    "portable-producer-a": (
        "52b21221955ff18a6800e4e961eb6c7971c6ca38ad420ed8c548a254c6aa07b5"
    ),
    "portable-producer-b": (
        "19e4bb700f6baf2b44acaa396471329dafca686ed2af942f2b8c086e8cb069e9"
    ),
    "portable-compare": (
        "bed676a36a87127959f1b64443533a9d7a62fcd6ca0bb5cdf1c0b5f63550c6a0"
    ),
    "portable-smoke": (
        "529d95c0e9575b698eb1be2a9c903d3312f0b3aadf9a9366bd12151de79577ab"
    ),
    "windows-portable": (
        "5246e79094eb9b85dfaf72a03280592eeee75dc3bf06ec1f87e8271b97719786"
    ),
}

TEST_STEPS = (
    "Check out source",
    "Set up pinned Python",
    "Preflight locked dependency inputs",
    "Install locked QA environment",
    "Prepare QA evidence directory",
    CONSOLIDATED_STEP,
    "Validate dependency audit policy",
    "Execute locked dependency audit",
    "Validate non-shrinking coverage gate",
    "Validate Ruff policy ratchet",
    "Execute Ruff policy",
    "Validate mypy policy ratchet",
    "Execute strict mypy policy",
    "Run complete test suite with coverage",
    "Render report fixture with real figures",
    "Render manual fixture with real figures",
    "Upload QA evidence",
)

PACKAGE_STEPS = (
    "Check out source",
    "Set up pinned Python",
    "Build first unsigned QA package from exact exported source",
    "Build second unsigned QA package from exact exported source",
    "Verify both unsigned QA package identities",
    "Compare independent unsigned QA package builds",
    "Upload unsigned QA reproducibility evidence",
)

PORTABLE_PRODUCER_A_STEPS = (
    "Check out source for producer A",
    "Set up producer A Python",
    "Prepare authenticated Gitless source for producer A",
    "Record Microsoft Edge prerequisite",
    "Build producer A through root BAT",
    "Verify and stage producer A immutable distribution",
    "Upload immutable producer A distribution",
)

PORTABLE_PRODUCER_B_STEPS = (
    "Check out source for producer B",
    "Set up producer B Python",
    "Prepare authenticated Gitless source for producer B",
    "Build producer B through root BAT",
    "Verify and stage producer B immutable distribution",
    "Upload immutable producer B distribution",
)

PORTABLE_COMPARE_STEPS = (
    "Check out source for portable comparison",
    "Set up portable comparison Python",
    "Download immutable producer A",
    "Download immutable producer B",
    "Verify and compare downloaded portable distributions",
    "Upload portable comparison evidence",
)

PORTABLE_SMOKE_STEPS = (
    "Check out source for isolated smoke",
    "Set up isolated smoke Python",
    "Download verified producer A only",
    "Run controlled Job Object startup smoke",
    "Upload isolated smoke evidence",
)

PORTABLE_STEPS = (
    "Check out source for final portable verification",
    "Set up final portable verification Python",
    "Download producer A for final publication",
    "Download producer B for final publication",
    "Download portable comparison evidence",
    "Download isolated smoke evidence",
    "Re-verify immutable distributions for final publication",
    "Upload unsigned portable Windows evidence",
)


class ConsolidatedPublicationGateError(ValueError):
    """Raised when the final publication chain is incomplete or bypassable."""


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConsolidatedPublicationGateError(f"{label} must be a mapping")
    return value


def _steps(job: Mapping[str, Any], expected: tuple[str, ...], label: str) -> list:
    steps = job.get("steps")
    if not isinstance(steps, list) or not all(isinstance(step, Mapping) for step in steps):
        raise ConsolidatedPublicationGateError(f"{label} steps must be mappings")
    names = tuple(step.get("name") for step in steps)
    if names != expected:
        raise ConsolidatedPublicationGateError(f"{label} step inventory or order differs")
    for step in steps:
        if "continue-on-error" in step or "working-directory" in step:
            raise ConsolidatedPublicationGateError(
                f"{label} steps must remain failure-propagating and repository-rooted"
            )
    return steps


def _named_step(steps: list, name: str) -> Mapping[str, Any]:
    matches = [step for step in steps if step.get("name") == name]
    if len(matches) != 1:
        raise ConsolidatedPublicationGateError(f"workflow must contain one {name!r} step")
    return matches[0]


def _validate_action_pins(*step_groups: list) -> None:
    for steps in step_groups:
        for step in steps:
            action = step.get("uses")
            if action is not None and (
                not isinstance(action, str) or FULL_COMMIT_ACTION.fullmatch(action) is None
            ):
                raise ConsolidatedPublicationGateError(
                    "every workflow action must be pinned to one full commit"
                )


def _validate_action_identities(*step_groups: list) -> None:
    approved = {
        CHECKOUT_ACTION,
        DOWNLOAD_ACTION,
        SETUP_PYTHON_ACTION,
        UPLOAD_ACTION,
    }
    for steps in step_groups:
        for step in steps:
            action = step.get("uses")
            if action is not None and action not in approved:
                raise ConsolidatedPublicationGateError(
                    "workflow uses an action outside the approved action identity set"
                )


def _structured_sha256(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_exact_job_contract(job: Mapping[str, Any], name: str) -> None:
    if _structured_sha256(job) != JOB_CONTRACT_SHA256[name]:
        raise ConsolidatedPublicationGateError(
            f"{name} job differs from its exact structured contract"
        )


def _contains_secret_context(value: object) -> bool:
    if isinstance(value, str):
        return SECRET_CONTEXT.search(value) is not None
    if isinstance(value, Mapping):
        return any(
            _contains_secret_context(key) or _contains_secret_context(item)
            for key, item in value.items()
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return any(_contains_secret_context(item) for item in value)
    return False


def _validate_top_level_contract(workflow: Mapping[object, Any]) -> None:
    if set(workflow) != {"name", True, "permissions", "concurrency", "jobs"}:
        raise ConsolidatedPublicationGateError(
            "workflow differs from its exact top-level contract"
        )
    if workflow.get("name") != "Sector QA":
        raise ConsolidatedPublicationGateError(
            "workflow differs from its exact top-level contract"
        )
    if workflow.get(True) != {
        "pull_request": None,
        "push": {"branches": ["main"]},
        "workflow_dispatch": None,
    }:
        raise ConsolidatedPublicationGateError(
            "workflow differs from its exact top-level contract"
        )
    if workflow.get("concurrency") != {
        "group": "sector-qa-${{ github.ref }}",
        "cancel-in-progress": True,
    }:
        raise ConsolidatedPublicationGateError(
            "workflow differs from its exact top-level contract"
        )


def _validate_test_job(job: Mapping[str, Any]) -> list:
    if set(job) != {"name", "runs-on", "timeout-minutes", "steps"}:
        raise ConsolidatedPublicationGateError(
            "test job must remain unconditional and failure-propagating"
        )
    if job.get("name") != "Full test and report gate":
        raise ConsolidatedPublicationGateError("test job identity differs")
    if job.get("runs-on") != "windows-latest" or job.get("timeout-minutes") != 60:
        raise ConsolidatedPublicationGateError("test runner identity differs")

    steps = _steps(job, TEST_STEPS, "test job")
    always_steps = {
        "Render report fixture with real figures",
        "Render manual fixture with real figures",
        "Upload QA evidence",
    }
    for step in steps:
        expected_if = "always()" if step["name"] in always_steps else None
        if step.get("if") != expected_if:
            raise ConsolidatedPublicationGateError(
                f"{step['name']!r} execution condition differs"
            )

    validator = _named_step(steps, CONSOLIDATED_STEP)
    if validator != {
        "name": CONSOLIDATED_STEP,
        "run": (
            "python tools/verify_consolidated_publication_gate.py "
            ".github/workflows/qa.yml"
        ),
    }:
        raise ConsolidatedPublicationGateError("consolidated validator command differs")

    report = _named_step(steps, "Render report fixture with real figures")
    if report != {
        "name": "Render report fixture with real figures",
        "if": "always()",
        "run": "python tools/report_render_fixture.py --output qa-artifacts/report",
    }:
        raise ConsolidatedPublicationGateError("report render gate differs")

    manual = _named_step(steps, "Render manual fixture with real figures")
    if manual != {
        "name": "Render manual fixture with real figures",
        "if": "always()",
        "run": "python tools/manual_render_fixture.py --output qa-artifacts/manual",
    }:
        raise ConsolidatedPublicationGateError("manual render gate differs")

    upload = _named_step(steps, "Upload QA evidence")
    if upload != {
        "name": "Upload QA evidence",
        "if": "always()",
        "uses": UPLOAD_ACTION,
        "with": {
            "name": "sector-qa-evidence",
            "path": "qa-artifacts/",
            "if-no-files-found": "error",
            "retention-days": 14,
        },
    }:
        raise ConsolidatedPublicationGateError("QA evidence upload differs")
    return steps


def _validate_package_job(job: Mapping[str, Any]) -> list:
    if set(job) != {"name", "needs", "runs-on", "timeout-minutes", "steps"}:
        raise ConsolidatedPublicationGateError(
            "package job must retain its unsigned failure-propagating context"
        )
    if job.get("name") != "Unsigned QA Windows package":
        raise ConsolidatedPublicationGateError("package job identity differs")
    if job.get("needs") != "test":
        raise ConsolidatedPublicationGateError(
            "package job must require the successful test job"
        )
    if job.get("runs-on") != "windows-latest" or job.get("timeout-minutes") != 60:
        raise ConsolidatedPublicationGateError("package runner identity differs")

    steps = _steps(job, PACKAGE_STEPS, "package job")
    if any("if" in step for step in steps):
        raise ConsolidatedPublicationGateError("package steps must not be conditionally skipped")

    upload = _named_step(steps, "Upload unsigned QA reproducibility evidence")
    expected_paths = [
        "${{ env.SECTOR_PACKAGE_ROOT_A }}/",
        "${{ env.SECTOR_PACKAGE_ROOT_B }}/",
        "${{ env.SECTOR_SOURCE_IDENTITY_A }}",
        "${{ env.SECTOR_SOURCE_IDENTITY_B }}",
        "${{ env.SECTOR_REPRODUCIBILITY_EVIDENCE }}",
    ]
    upload_with = upload.get("with", {})
    if (
        upload.get("uses") != UPLOAD_ACTION
        or set(upload) != {"name", "uses", "with"}
        or upload_with.get("name") != "Sector-Windows-unsigned-QA"
        or upload_with.get("if-no-files-found") != "error"
        or upload_with.get("retention-days") != 7
        or str(upload_with.get("path", "")).splitlines() != expected_paths
    ):
        raise ConsolidatedPublicationGateError("package evidence upload differs")
    return steps


def _validate_portable_job(
    job: Mapping[str, Any],
    *,
    label: str,
    display_name: str,
    needs: object,
    timeout_minutes: int,
    expected_steps: tuple[str, ...],
) -> list:
    if set(job) != {
        "name",
        "needs",
        "runs-on",
        "timeout-minutes",
        "permissions",
        "steps",
    }:
        raise ConsolidatedPublicationGateError(
            f"{label} must retain its isolated failure-propagating context"
        )
    if job.get("name") != display_name or job.get("needs") != needs:
        raise ConsolidatedPublicationGateError(f"{label} dependency or identity differs")
    if (
        job.get("runs-on") != "windows-latest"
        or job.get("timeout-minutes") != timeout_minutes
        or job.get("permissions") != {"contents": "read"}
    ):
        raise ConsolidatedPublicationGateError(
            f"{label} runner or minimal permission boundary differs"
        )

    steps = _steps(job, expected_steps, label)
    for step in steps:
        expected_if = (
            "always()" if step["name"] == "Upload isolated smoke evidence" else None
        )
        if step.get("if") != expected_if:
            raise ConsolidatedPublicationGateError(
                f"{step['name']!r} execution condition differs"
            )
    return steps


def validate_workflow(workflow_text: str) -> None:
    try:
        workflow = yaml.safe_load(workflow_text)
    except yaml.YAMLError as exc:
        raise ConsolidatedPublicationGateError(f"cannot parse workflow YAML: {exc}") from exc
    workflow = _mapping(workflow, "workflow")
    if _contains_secret_context(workflow):
        raise ConsolidatedPublicationGateError(
            "ordinary QA workflow must contain no signing authority"
        )
    _validate_top_level_contract(workflow)
    if workflow.get("permissions") != {"contents": "read"}:
        raise ConsolidatedPublicationGateError(
            "workflow permissions must remain exactly contents: read"
        )
    jobs = _mapping(workflow.get("jobs"), "workflow jobs")
    expected_jobs = {
        "test",
        "windows-package",
        "portable-producer-a",
        "portable-producer-b",
        "portable-compare",
        "portable-smoke",
        "windows-portable",
    }
    if set(jobs) != expected_jobs:
        raise ConsolidatedPublicationGateError("workflow job inventory differs")

    test_steps = _validate_test_job(_mapping(jobs["test"], "test job"))
    package_steps = _validate_package_job(
        _mapping(jobs["windows-package"], "package job")
    )
    portable_contracts = (
        (
            "portable-producer-a",
            "Unsigned portable producer A",
            "test",
            60,
            PORTABLE_PRODUCER_A_STEPS,
        ),
        (
            "portable-producer-b",
            "Unsigned portable producer B",
            "test",
            60,
            PORTABLE_PRODUCER_B_STEPS,
        ),
        (
            "portable-compare",
            "Compare immutable portable producers",
            ["portable-producer-a", "portable-producer-b"],
            30,
            PORTABLE_COMPARE_STEPS,
        ),
        (
            "portable-smoke",
            "Isolated verified portable startup smoke",
            ["portable-producer-a", "portable-compare"],
            20,
            PORTABLE_SMOKE_STEPS,
        ),
        (
            "windows-portable",
            "Unsigned portable Windows distribution",
            [
                "portable-producer-a",
                "portable-producer-b",
                "portable-compare",
                "portable-smoke",
            ],
            30,
            PORTABLE_STEPS,
        ),
    )
    portable_step_groups = [
        _validate_portable_job(
            _mapping(jobs[job_name], f"{job_name} job"),
            label=f"{job_name} job",
            display_name=display_name,
            needs=needs,
            timeout_minutes=timeout_minutes,
            expected_steps=expected_steps,
        )
        for job_name, display_name, needs, timeout_minutes, expected_steps in portable_contracts
    ]
    all_step_groups = [test_steps, package_steps, *portable_step_groups]
    _validate_action_pins(*all_step_groups)
    _validate_action_identities(*all_step_groups)
    _validate_exact_job_contract(_mapping(jobs["test"], "test job"), "test")
    _validate_exact_job_contract(
        _mapping(jobs["windows-package"], "package job"), "windows-package"
    )
    for job_name, *_rest in portable_contracts:
        _validate_exact_job_contract(
            _mapping(jobs[job_name], f"{job_name} job"), job_name
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workflow", type=Path)
    arguments = parser.parse_args(argv)
    try:
        validate_workflow(arguments.workflow.read_text(encoding="utf-8"))
    except (OSError, ConsolidatedPublicationGateError) as exc:
        print(f"consolidated publication gate failed: {exc}", file=sys.stderr)
        return 2
    print("consolidated publication gate is complete and fail-closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
