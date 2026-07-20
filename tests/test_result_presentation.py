"""Display-only assessment and QA-evidence helpers."""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import result_presentation as presentation  # noqa: E402
from sector.materials import Concrete, MildSteel  # noqa: E402


def _plastic(**updates):
    result = {
        "check_util": True,
        "closed": True,
        "converged": True,
        "util": 0.8,
        "util_gov": 0,
        "points": [{"V": 90.0}],
    }
    result.update(updates)
    return result


@pytest.mark.parametrize(
    ("updates", "status", "assessed"),
    [
        ({}, "PASS", True),
        ({"util": 1.2}, "FAIL", True),
        ({"check_util": False, "util": None}, "NOT ASSESSED", False),
        ({"closed": False, "util": None}, "NOT ASSESSED", False),
        ({"converged": False}, "INVALID", False),
    ],
)
def test_plastic_uls_assessment_has_explicit_semantic_states(
        updates, status, assessed):
    result = presentation.plastic_uls_assessment(_plastic(**updates))
    assert result["status"] == status
    assert result["assessed"] is assessed


def test_plastic_uls_assessment_reports_signed_margin_and_governing_angle():
    passed = presentation.plastic_uls_assessment(_plastic(util=0.8))
    failed = presentation.plastic_uls_assessment(_plastic(util=1.2))
    assert passed["margin"] == pytest.approx(0.2)
    assert failed["margin"] == pytest.approx(-0.2)
    assert passed["governing_angle"] == 90.0


def test_plastic_state_evidence_is_tension_positive_and_uses_mm2_area():
    steel = MildSteel(
        fytk=500.0, fyck=500.0, futk=500.0, eut=0.05,
        gamma_y=1.0, curve=2,
    )
    inp = {
        "outer": [(-0.1, -0.1), (0.1, -0.1), (0.1, 0.1), (-0.1, 0.1)],
        "holes": [],
        "bars": [(0.0, -0.05, 500.0), (0.0, 0.05, 400.0)],
        "tendons": [],
        "concrete": Concrete(fck=30.0, gamma_c=1.5),
        "steel": steel,
        "prestress": None,
    }
    point = {
        "V": 90.0, "na_x": float("inf"), "na_y": 0.0, "kappa": 0.01,
    }
    evidence = presentation.plastic_state_evidence(inp, point)
    assert len(evidence["concrete"]) == 4
    tension, compression = evidence["elements"]
    assert tension["state"] == "Tension" and tension["strain_permille"] > 0.0
    assert compression["state"] == "Compression"
    assert compression["strain_permille"] < 0.0
    assert tension["force_kn"] == pytest.approx(
        tension["stress_mpa"] * 500.0 / 1000.0)


def test_nm_boundary_rows_preserve_both_independent_axial_traces():
    interaction = {
        "x": {"N": [-100.0, 0.0], "M": [0.0, 50.0]},
        "y": {"N": [-120.0], "M": [0.0]},
    }
    rows = presentation.nm_boundary_rows(interaction)
    assert len(rows) == 2
    assert rows[0]["N, Mx boundary (kN)"] == -100.0
    assert rows[0]["N, My boundary (kN)"] == -120.0
    assert rows[1]["N, My boundary (kN)"] is None
