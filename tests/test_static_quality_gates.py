from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import tomllib

from tools.verify_static_gates import (
    StaticGateContractError,
    load_contract,
    validate_contract,
    validate_workflow,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "quality-static-gates.toml"
WORKFLOW = ROOT / ".github" / "workflows" / "qa.yml"


def _contract():
    return tomllib.loads(CONTRACT.read_text(encoding="utf-8"))


def test_tracked_contract_matches_exact_workflow_commands():
    data = load_contract(CONTRACT, ROOT)
    validate_workflow(data, WORKFLOW.read_text(encoding="utf-8"))


@pytest.mark.parametrize("field", ["owner", "reason", "exit_condition"])
def test_every_waiver_retains_complete_ownership(field):
    data = deepcopy(_contract())
    data["waivers"][0][field] = ""

    with pytest.raises(StaticGateContractError, match=field):
        validate_contract(data, ROOT)


def test_coverage_floor_and_targets_cannot_shrink():
    data = deepcopy(_contract())
    data["coverage"]["minimum_percent"] = 49
    with pytest.raises(StaticGateContractError, match="below 50"):
        validate_contract(data, ROOT)

    data = deepcopy(_contract())
    data["coverage"]["targets"].remove("sector")
    with pytest.raises(StaticGateContractError, match="target ratchet shrank"):
        validate_contract(data, ROOT)


@pytest.mark.parametrize("field", ["paths", "select"])
def test_capacity_boundary_scope_cannot_shrink(field):
    data = deepcopy(_contract())
    data["ruff"]["scopes"][1][field].pop()

    with pytest.raises(StaticGateContractError, match="ratchet shrank"):
        validate_contract(data, ROOT)


@pytest.mark.parametrize("scope_index", [0, 1])
def test_e402_cannot_escape_its_one_bootstrapping_file(scope_index):
    data = deepcopy(_contract())
    data["ruff"]["scopes"][scope_index]["ignore"].append("E402")

    with pytest.raises(StaticGateContractError, match="unowned ignore"):
        validate_contract(data, ROOT)


def test_unknown_or_missing_scope_is_rejected():
    data = deepcopy(_contract())
    data["ruff"]["scopes"].pop()
    with pytest.raises(StaticGateContractError, match="scope inventory"):
        validate_contract(data, ROOT)

    data = deepcopy(_contract())
    data["ruff"]["scopes"][0]["id"] = "renamed"
    with pytest.raises(StaticGateContractError, match="scope inventory"):
        validate_contract(data, ROOT)


def test_repository_path_escape_is_rejected(tmp_path):
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside the candidate repository\n", encoding="utf-8")
    data = deepcopy(_contract())
    data["coverage"]["targets"][0] = "../" + outside.name

    with pytest.raises(StaticGateContractError, match="escapes the repository"):
        validate_contract(data, repository_root)


@pytest.mark.parametrize(
    ("retained", "drifted"),
    [
        ("--cov-fail-under=50", "--cov-fail-under=49"),
        ("--select E9,F63,F7,F82", "--select E9,F63,F7"),
        (
            "sector/capacity.py tests/test_capacity.py --select E4,E7,E9,F,I",
            "sector/capacity.py tests/test_capacity.py --select E4,E7,E9,F,I "
            "--ignore E402",
        ),
        ("--ignore E402", "--ignore E402,F401"),
    ],
)
def test_each_workflow_gate_drift_fails_closed(retained, drifted):
    data = load_contract(CONTRACT, ROOT)
    workflow = WORKFLOW.read_text(encoding="utf-8").replace(retained, drifted, 1)

    with pytest.raises(StaticGateContractError, match="one exact static-gate"):
        validate_workflow(data, workflow)
