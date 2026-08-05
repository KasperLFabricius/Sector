from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import tomllib

from tools.qa_gate_policy import (
    QualityGatePolicyError,
    load_policy,
    validate_policy,
    validate_workflow,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "quality-gates.toml"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "qa.yml"


def _policy() -> dict[str, object]:
    return tomllib.loads(POLICY_PATH.read_text(encoding="utf-8"))


def test_tracked_quality_gate_policy_and_workflow_are_aligned():
    policy = load_policy(POLICY_PATH, ROOT)
    validate_workflow(policy, WORKFLOW_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("field", ["owner", "exit_condition"])
def test_waiver_requires_named_owner_and_exit_condition(field):
    policy = deepcopy(_policy())
    policy["waivers"][0][field] = ""

    with pytest.raises(QualityGatePolicyError, match=field):
        validate_policy(policy, ROOT)


def test_coverage_ratchet_cannot_be_lowered_below_frozen_floor():
    policy = deepcopy(_policy())
    policy["coverage"]["minimum_percent"] = 49

    with pytest.raises(QualityGatePolicyError, match="may not fall below 50"):
        validate_policy(policy, ROOT)


def test_selected_scope_must_name_existing_repository_paths():
    policy = deepcopy(_policy())
    policy["typing"]["paths"].append("sector/not_a_real_boundary.py")

    with pytest.raises(QualityGatePolicyError, match="does not exist"):
        validate_policy(policy, ROOT)


def test_duplicate_waiver_identity_is_rejected():
    policy = deepcopy(_policy())
    policy["waivers"].append(deepcopy(policy["waivers"][0]))

    with pytest.raises(QualityGatePolicyError, match="duplicate waiver id"):
        validate_policy(policy, ROOT)


def test_required_waiver_inventory_cannot_be_silently_removed():
    policy = deepcopy(_policy())
    policy["waivers"].pop()

    with pytest.raises(QualityGatePolicyError, match="waiver inventory"):
        validate_policy(policy, ROOT)


def test_waiver_identity_cannot_be_relabelled_to_an_unrelated_gate():
    policy = deepcopy(_policy())
    policy["waivers"][0]["gate"] = "ruff"

    with pytest.raises(QualityGatePolicyError, match="must remain coverage"):
        validate_policy(policy, ROOT)


@pytest.mark.parametrize(
    ("table", "field"),
    [
        ("coverage", "targets"),
        ("ruff", "critical_paths"),
        ("ruff", "critical_select"),
        ("ruff", "selected_paths"),
        ("ruff", "selected_select"),
        ("typing", "paths"),
    ],
)
def test_frozen_gate_scope_cannot_shrink(table, field):
    policy = deepcopy(_policy())
    policy[table][field].pop()

    with pytest.raises(QualityGatePolicyError, match="shrinks the frozen ratchet"):
        validate_policy(policy, ROOT)


def test_selected_ruff_ignore_cannot_expand_without_an_owned_policy_change():
    policy = deepcopy(_policy())
    policy["ruff"]["selected_ignore"].append("F401")

    with pytest.raises(QualityGatePolicyError, match="unowned exception"):
        validate_policy(policy, ROOT)


def test_dependency_audit_safeguards_cannot_be_disabled():
    policy = deepcopy(_policy())
    policy["dependency_security"]["strict"] = False

    with pytest.raises(QualityGatePolicyError, match="safeguards"):
        validate_policy(policy, ROOT)


@pytest.mark.parametrize(
    ("retained", "drifted"),
    [
        ("--cov-fail-under=50", "--cov-fail-under=49"),
        ("--select E9,F63,F7,F82", "--select E9,F63,F7"),
        ("--ignore E402", "--ignore E402,F401"),
        ("python -m mypy --strict", "python -m mypy"),
        (
            "python -m pip_audit --strict --require-hashes --disable-pip",
            "python -m pip_audit --strict --require-hashes",
        ),
    ],
)
def test_workflow_gate_drift_is_a_controlled_failure(retained, drifted):
    policy = load_policy(POLICY_PATH, ROOT)
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8").replace(retained, drifted, 1)

    with pytest.raises(QualityGatePolicyError, match="one exact policy command"):
        validate_workflow(policy, workflow)
