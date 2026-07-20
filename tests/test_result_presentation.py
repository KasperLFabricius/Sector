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


def _inp(**updates):
    inp = {
        "mode": "Both",
        "plastic_case": {
            "id": "PL-17",
            "type": "ALS",
            "source": "Combination register C1",
        },
        "elastic_case": {
            "id": "EL-08",
            "type": "FLS",
            "source": "Combination register C2",
        },
    }
    inp.update(updates)
    return inp


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
def test_plastic_action_assessment_has_explicit_semantic_states(
        updates, status, assessed):
    result = presentation.plastic_action_assessment(_plastic(**updates))
    assert result["status"] == status
    assert result["assessed"] is assessed


def test_plastic_action_assessment_reports_signed_margin_and_governing_angle():
    passed = presentation.plastic_action_assessment(_plastic(util=0.8))
    failed = presentation.plastic_action_assessment(_plastic(util=1.2))
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


def test_action_sets_are_normalised_and_required_for_active_families():
    inp = _inp()
    assert presentation.action_set_text(inp, "plastic") == (
        "PL-17 | ALS | Source: Combination register C1"
    )
    assert presentation.required_action_set_errors(inp) == []

    inp["plastic_case"]["id"] = " "
    inp["elastic_case"]["id"] = ""
    assert presentation.required_action_set_errors(inp) == [
        "Plastic action-set ID is required",
        "Elastic action-set ID is required",
    ]

    assert presentation.required_action_set_errors({
        "mode": "Elastic",
        "combined_on": True,
        "plastic_case": {"id": ""},
        "elastic_case": {"id": "EL-01"},
    }) == ["Plastic action-set ID is required"]


def test_result_summary_uses_action_ids_and_explicit_status_vocabulary():
    elastic = {
        "converged": True,
        "stress_assessments": {
            "concrete": {
                "value": 12.0, "limit": 18.0, "util": 2 / 3,
                "status": "OK", "criterion": "60% fck",
            },
            "reinforcement": {
                "value": 450.0, "limit": 400.0, "util": 1.125,
                "status": "EXCEEDED", "criterion": "80% fyk",
            },
        },
        "show_cw": False,
    }
    rows = presentation.result_summary_rows(
        _inp(), {"plastic": _plastic(), "elastic": elastic},
    )
    by_check = {row["check"]: row for row in rows}

    assert by_check["Plastic bending"]["case"] == "PL-17"
    assert by_check["Concrete stress"]["case"] == "EL-08"
    assert by_check["Plastic bending"]["status"] == "PASS"
    assert by_check["Reinforcement stress"]["status"] == "FAIL"
    assert presentation.overall_summary_status(rows) == "FAIL"


def test_stale_summary_retains_last_status_as_evidence():
    rows = presentation.result_summary_rows(
        _inp(mode="Plastic"), {"plastic": _plastic()}, stale=True,
    )
    assert rows[0]["status"] == "STALE"
    assert "Last status: PASS" in rows[0]["note"]
    assert presentation.overall_summary_status(rows) == "STALE"


def test_combined_summary_cannot_hide_subordinate_failure():
    combined = {
        "valid": True,
        "code_applicable": True,
        "method": "DK NA",
        "dkna_sum": 0.80,
        "crushing": {"valid": True, "value": 1.10, "cot": 1.5},
        "transverse": {
            "valid": True, "governing": 0.75, "governs": "stirrups",
        },
        "longitudinal": {
            "valid": True, "util": 0.65, "axis": "x", "biaxial": False,
        },
        "chord_off": {"valid": True, "util": 0.55, "axis": "y"},
    }
    rows = presentation.result_summary_rows(
        _inp(mode="Plastic", combined_on=True),
        {"plastic": _plastic(), "combined": combined},
    )
    by_check = {row["check"]: row for row in rows}

    assert by_check["Combined M-V-T - DK NA sum"]["status"] == "PASS"
    assert by_check["Combined V-T crushing"]["status"] == "FAIL"
    assert by_check["Combined transverse reinforcement"]["status"] == "PASS"
    assert by_check["Combined longitudinal reinforcement"]["status"] == "PASS"
    assert by_check["Combined off-axis chord"]["status"] == "PASS"
    assert presentation.overall_summary_status(rows) == "FAIL"


def test_combined_summary_withholds_verdict_for_fallback_or_missing_checks():
    combined = {
        "valid": True,
        "code_applicable": True,
        "method": "DK NA",
        "dkna_sum": 0.80,
        "crushing": None,
        "transverse": None,
        "longitudinal": {
            "valid": True, "util": 0.60, "axis": "x",
            "biaxial": True, "conditional": False,
        },
    }
    rows = presentation.result_summary_rows(
        _inp(mode="Plastic", combined_on=True),
        {"plastic": _plastic(), "combined": combined},
    )
    by_check = {row["check"]: row for row in rows}

    assert by_check["Combined V-T crushing"]["status"] == "NOT ASSESSED"
    assert by_check["Combined transverse reinforcement"]["status"] == "NOT ASSESSED"
    assert by_check["Combined longitudinal reinforcement"]["status"] == "NOT ASSESSED"
    assert "fallback" in by_check["Combined longitudinal reinforcement"]["note"].lower()


def test_combined_summary_marks_missing_prerequisites_not_assessed():
    combined = {
        "valid": False,
        "have_m": True,
        "have_v": False,
        "have_t": False,
        "method": "DK NA",
    }
    rows = presentation.result_summary_rows(
        _inp(mode="Plastic", combined_on=True),
        {"plastic": _plastic(), "combined": combined},
    )
    by_check = {row["check"]: row for row in rows}

    assert by_check["Combined M-V-T - DK NA sum"]["status"] == "NOT ASSESSED"
    assert by_check["Combined M-V-T - DK NA sum"]["note"] == (
        "Missing prerequisite: V, T"
    )
    assert presentation.overall_summary_status(rows) == "NOT ASSESSED"


def test_combined_summary_surfaces_incomplete_torsion_chord_coverage():
    combined = {
        "valid": True,
        "code_applicable": True,
        "method": "DK NA",
        "dkna_sum": 0.80,
        "crushing": {"valid": True, "value": 0.70, "cot": 1.5},
        "transverse": {
            "valid": True, "governing": 0.75, "governs": "stirrups",
        },
        "longitudinal": {
            "valid": True,
            "util": 0.65,
            "axis": "x",
            "biaxial": False,
            "off_not_evaluated": "not_solved",
        },
    }
    rows = presentation.result_summary_rows(
        _inp(mode="Plastic", combined_on=True),
        {"plastic": _plastic(), "combined": combined},
    )
    by_check = {row["check"]: row for row in rows}

    assert by_check["Combined longitudinal reinforcement"]["status"] == "PASS"
    assert by_check["Combined off-axis chord coverage"]["status"] == "NOT ASSESSED"
    assert "not solved" in by_check["Combined off-axis chord coverage"]["note"]
    assert presentation.overall_summary_status(rows) == "NOT ASSESSED"
