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


def test_plastic_assessment_text_is_compact_and_solver_neutral():
    passed = presentation.plastic_action_assessment(_plastic(util=0.8))
    text = presentation.plastic_assessment_text(passed)
    assert text == (
        "PASS - Plastic bending | utilisation 80.0 % | limit 100 % | "
        "margin +20.0 pp"
    )
    assert "does not exceed" not in text
    assert "ULS" not in text and "SLS" not in text

    capacity_only = presentation.plastic_action_assessment(
        _plastic(check_util=False, util=None))
    assert presentation.plastic_assessment_text(capacity_only) == (
        "NOT ASSESSED - Plastic bending | Capacity only; "
        "applied-moment check disabled"
    )


@pytest.mark.parametrize(
    ("source", "label"),
    [
        ("OK", "PASS"),
        ("EXCEEDED", "FAIL"),
        ("INVALID", "INVALID"),
        ("NOT APPLICABLE", "NOT APPLICABLE"),
    ],
)
def test_acceptance_status_label_uses_common_report_vocabulary(source, label):
    assert presentation.assessment_status_label(source) == label


@pytest.mark.parametrize(
    ("interaction", "applicable", "expected"),
    [
        ({"valid": True, "value": 0.8, "code_applicable": True}, True, "PASS"),
        ({"valid": True, "value": 1.2, "code_applicable": True}, True, "FAIL"),
        ({"valid": True, "value": 0.8, "code_applicable": False}, True,
         "NOT ASSESSED"),
        ({"valid": True, "value": 0.8}, False, "NOT ASSESSED"),
        ({"valid": False, "value": None}, True, "NOT ASSESSED"),
    ],
)
def test_vt_interaction_status_withholds_verdict_outside_applicability(
    interaction, applicable, expected
):
    assert presentation.interaction_assessment_status(
        interaction, applicable=applicable
    ) == expected


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


def test_plastic_state_evidence_uses_and_identifies_each_material():
    low = MildSteel(
        fytk=300.0, fyck=300.0, futk=300.0, eut=0.05,
        gamma_y=1.0, curve=2,
    )
    high = MildSteel(
        fytk=600.0, fyck=600.0, futk=600.0, eut=0.05,
        gamma_y=1.0, curve=2,
    )
    inp = {
        "outer": [(-0.1, -0.1), (0.1, -0.1), (0.1, 0.1), (-0.1, 0.1)],
        "holes": [],
        "bars": [(0.0, -0.05, 500.0), (0.0, -0.05, 500.0)],
        "tendons": [],
        "concrete": Concrete(fck=30.0, gamma_c=1.5),
        "steel": low,
        "bar_materials": [low, high],
        "prestress": None,
        "bar_elements": [
            {"id": "R1", "material_id": "M1"},
            {"id": "R2", "material_id": "M2"},
        ],
        "mild_material_catalog": {
            "items": [
                {"id": "M1", "name": "Low strength"},
                {"id": "M2", "name": "High strength"},
            ]
        },
    }
    point = {
        "V": 90.0, "na_x": float("inf"), "na_y": 0.0, "kappa": 0.10,
    }

    rows = presentation.plastic_state_evidence(inp, point)["elements"]

    assert [row["material_id"] for row in rows] == ["M1", "M2"]
    assert [row["material_name"] for row in rows] == [
        "Low strength", "High strength"
    ]
    assert rows[1]["stress_mpa"] > rows[0]["stress_mpa"]


def test_plastic_state_evidence_rejects_incomplete_material_sequence():
    steel = MildSteel(
        fytk=500.0, fyck=500.0, futk=500.0, eut=0.05,
        gamma_y=1.0, curve=2,
    )
    inp = {
        "outer": [(-0.1, -0.1), (0.1, -0.1), (0.1, 0.1), (-0.1, 0.1)],
        "holes": [],
        "bars": [(0.0, -0.05, 500.0), (0.0, 0.05, 500.0)],
        "bar_materials": [steel],
        "tendons": [],
        "concrete": Concrete(fck=30.0, gamma_c=1.5),
        "steel": steel,
        "prestress": None,
    }

    with pytest.raises(ValueError, match="one material and prestrain"):
        presentation.plastic_state_evidence(
            inp, {"V": 90.0, "na_x": float("inf"), "na_y": 0.0,
                  "kappa": 0.01}
        )


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


def test_shear_screening_does_not_fail_when_selected_links_pass():
    shear = {
        "res": {"valid": True, "vrd_c": 100.0},
        "util": 1.20,
        "method": "DK NA",
        "links": {
            "res": {"valid": True, "governs": "links"},
            "util": 0.80,
            "code_applicable": True,
        },
    }
    rows = presentation.result_summary_rows(
        _inp(mode="Plastic", shear_on=True, shear_links=True),
        {"plastic": _plastic(), "shear": shear},
    )
    by_check = {row["check"]: row for row in rows}

    assert by_check["Shear without links"]["status"] == "NOT APPLICABLE"
    assert by_check["Shear without links"]["util"] == pytest.approx(1.20)
    assert by_check["Shear with links"]["status"] == "PASS"
    assert presentation.overall_summary_status(rows) == "PASS"
    governing = dict(zip(
        (row["check"] for row in rows),
        presentation.summary_governing_flags(rows),
    ))
    assert governing["Shear without links"] is False
    assert governing["Shear with links"] is True


def test_shear_without_links_retains_concrete_screening_verdict():
    shear = {
        "res": {"valid": True, "vrd_c": 100.0},
        "util": 1.20,
        "method": "DK NA",
    }
    rows = presentation.result_summary_rows(
        _inp(mode="Plastic", shear_on=True, shear_links=False),
        {"plastic": _plastic(), "shear": shear},
    )
    by_check = {row["check"]: row for row in rows}

    assert by_check["Shear without links"]["status"] == "FAIL"
    assert presentation.overall_summary_status(rows) == "FAIL"


def test_biaxial_shear_summary_keeps_directional_verdicts_and_limitation():
    vx = {
        "res": {"valid": True, "vrd_c": 100.0},
        "util": 0.60,
        "method": "DK NA",
        "status": "PASS",
    }
    vy = {
        "res": {"valid": True, "vrd_c": 80.0},
        "util": 0.75,
        "method": "DK NA",
        "status": "PASS",
    }
    aggregate = dict(
        vx,
        directions={"vx": vx, "vy": vy},
        biaxial=True,
        status="REVIEW",
        interaction_assessed=False,
    )

    rows = presentation.result_summary_rows(
        _inp(mode="Plastic", shear_on=True, shear_links=False),
        {"plastic": _plastic(), "shear": aggregate},
    )
    by_check = {row["check"]: row for row in rows}

    assert by_check["Shear Vx without links"]["status"] == "PASS"
    assert by_check["Shear Vy without links"]["status"] == "PASS"
    assert by_check["Biaxial shear interaction"]["status"] == "NOT ASSESSED"
    assert presentation.overall_summary_status(rows) == "NOT ASSESSED"


def test_biaxial_combined_summary_reports_directions_and_withholds_three_way_verdict():
    combined = {
        "biaxial": True,
        "directions": {
            "vx": {"status": "PASS", "governing_util": 0.72},
            "vy": {"status": "FAIL", "governing_util": 1.14},
        },
        "status": "FAIL",
        "interaction_assessed": False,
    }
    rows = presentation.result_summary_rows(
        _inp(mode="Plastic", combined_on=True),
        {"plastic": _plastic(), "combined": combined},
    )
    by_check = {row["check"]: row for row in rows}

    assert by_check["Combined Vx+T directional screen"]["status"] == "PASS"
    assert by_check["Combined Vy+T directional screen"]["status"] == "FAIL"
    assert by_check["Combined Vx-Vy-T interaction"]["status"] == "NOT ASSESSED"
    assert presentation.overall_summary_status(rows) == "FAIL"


def test_infinite_failure_governs_while_nan_and_non_applicable_do_not():
    rows = [
        {"status": "PASS", "util": 0.80},
        {"status": "FAIL", "util": float("inf")},
        {"status": "FAIL", "util": float("nan")},
        {"status": "NOT APPLICABLE", "util": float("inf")},
    ]

    assert presentation.summary_governing_flags(rows) == [
        False, True, False, False,
    ]


def _plastic_case_entry(name, util, *, vx=0.0, vy=0.0, t=0.0):
    actions = {
        "name": name,
        "description": f"Description {name}",
        "n_ed_kn": 0.0,
        "mx_ed_knm": 10.0,
        "my_ed_knm": 0.0,
        "vx_ed_kn": vx,
        "vy_ed_kn": vy,
        "vx_face": "auto",
        "vy_face": "auto",
        "t_ed_knm": t,
    }
    return {
        "name": name,
        "description": actions["description"],
        "actions": actions,
        "evaluated": True,
        "results": {"plastic": _plastic(util=util)},
    }


def test_multi_case_summary_marks_governing_case_for_each_check():
    inp = _inp(
        mode="Plastic",
        plastic_cases=[],
        elastic_cases=[],
        shear_on=False,
        torsion_on=False,
        combined_on=False,
    )
    rows = presentation.multi_case_summary_rows(inp, {
        "plastic_cases": [
            _plastic_case_entry("PL-A", 0.60),
            _plastic_case_entry("PL-B", 0.90),
        ],
    })

    assert [row["case"] for row in rows] == ["PL-A", "PL-B"]
    assert presentation.summary_governing_case_flags(rows) == [False, True]


def test_multi_case_summary_records_zero_actions_as_not_evaluated():
    inp = _inp(
        mode="Plastic",
        plastic_cases=[],
        elastic_cases=[],
        shear_on=True,
        torsion_on=True,
        combined_on=True,
    )
    rows = presentation.multi_case_summary_rows(inp, {
        "plastic_cases": [_plastic_case_entry("PL-ZERO", 0.50)],
    })
    by_check = {row["check"]: row for row in rows}

    assert by_check["Shear Vx"]["status"] == "NOT APPLICABLE"
    assert by_check["Shear Vy"]["result"] == "Vy,Ed = 0"
    assert by_check["Torsion"]["status"] == "NOT APPLICABLE"
    assert by_check["Combined M-V-T"]["result"] == "Vx,Ed = Vy,Ed = TEd = 0"
