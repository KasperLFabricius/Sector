"""Display-only assessment and QA-evidence helpers."""

from __future__ import annotations

import math
import inspect
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import result_presentation as presentation  # noqa: E402

from app import modelled_direction  # noqa: E402
from sector.design_standards import DesignBasisKey, get_design_basis  # noqa: E402


def test_worked_example_selection_retains_named_cases_branches_and_directions():
    out = {
        "plastic_cases": [
            {
                "name": "PL-A",
                "results": {
                    "plastic": {"converged": True, "util": 0.7},
                    "shear": {"directions": {
                        "vx": {"res": {"valid": True}, "util": 0.8},
                        "vy": {"res": {"valid": True}, "util": 0.8},
                    }},
                },
            },
            {
                "name": "PL-B",
                "results": {
                    "plastic": {"converged": True, "util": 0.9},
                    "shear": {"directions": {
                        "vx": {"res": {"valid": True}, "util": 0.95},
                    }},
                },
            },
        ],
        "elastic_cases": [
            {
                "name": "EL-A",
                "results": {"elastic": {
                    "converged": True, "max_conc": 10.0, "max_steel": 100.0,
                    "lambda_cr": 0.9,
                    "crack": {"wk": 0.2}, "crack_short": {"wk": 0.3},
                }},
            },
            {
                "name": "EL-B",
                "results": {"elastic": {
                    "converged": True, "max_conc": 12.0, "max_steel": 120.0,
                    "lambda_cr": 0.7,
                    "crack": {"wk": 0.4}, "crack_short": {"wk": 0.1},
                }},
            },
        ],
    }

    selection = presentation.worked_example_selection({}, out)

    assert selection["families"]["plastic"]["case_id"] == "PL-B"
    assert selection["families"]["shear"] == {
        "case_id": "PL-B", "component": "vx",
    }
    assert selection["families"]["elastic"]["case_id"] == "EL-B"
    assert selection["cracking_threshold"]["case_id"] == "EL-B"
    assert selection["crack_examples"] == [{
        "case_id": "EL-B", "system": "governing", "branch": "crack",
        "label": "long-term",
    }]


def test_torsion_subcheck_selection_accepts_positive_infinity_and_first_tie():
    interaction = {"valid": True, "value": math.inf}
    minimum = {"applicable": True, "value": math.inf}
    out = {"plastic_cases": [{
        "name": "PL-INF",
        "results": {"torsion": {
            "valid": True,
            "util": 0.5,
            "directional_interactions": {
                "vx": {"interaction": interaction, "min_reinf": minimum},
                "vy": {
                    "interaction": dict(interaction), "min_reinf": dict(minimum),
                },
            },
        }},
    }]}

    selected = presentation.worked_example_selection({}, out)[
        "torsion_subchecks"
    ]

    assert selected["interaction"] == {
        "case_id": "PL-INF", "component": "vx",
    }
    assert selected["minimum_reinforcement"] == {
        "case_id": "PL-INF", "component": "vx",
    }


def test_crack_comparison_selection_uses_largest_width_not_largest_ratio():
    out = {
        "elastic_cases": [
            {
                "name": "EL-LARGEST-WIDTH",
                "results": {"elastic": {
                    "converged": True,
                    "crack_output": {
                        "calculation_state": "WITHIN USER-SPECIFIED LIMIT",
                        "value": 0.30,
                        "criterion_mm": 0.40,
                        "ratio": 0.75,
                    },
                }},
            },
            {
                "name": "EL-LARGEST-RATIO",
                "results": {"elastic": {
                    "converged": True,
                    "crack_output": {
                        "calculation_state": "EXCEEDS USER-SPECIFIED LIMIT",
                        "value": 0.20,
                        "criterion_mm": 0.10,
                        "ratio": 2.0,
                    },
                }},
            },
        ],
    }

    selection = presentation.worked_example_selection({}, out)

    assert selection["crack_comparison"] == {
        "case_id": "EL-LARGEST-WIDTH",
    }


def test_unassessed_global_crack_width_suppresses_noncritical_comparison():
    out = {
        "elastic_cases": [
            {
                "name": "EL-GLOBAL-WIDTH",
                "results": {"elastic": {
                    "converged": True,
                    "crack": {"wk": 0.40},
                    "crack_output": {
                        "calculation_state": (
                            "CALCULATED - ACCEPTANCE NOT ASSESSED"
                        ),
                        "value": 0.40,
                        "criterion_mm": None,
                        "ratio": None,
                    },
                }},
            },
            {
                "name": "EL-NONCRITICAL-LIMIT",
                "results": {"elastic": {
                    "converged": True,
                    "crack": {"wk": 0.20},
                    "crack_output": {
                        "calculation_state": "EXCEEDS USER-SPECIFIED LIMIT",
                        "value": 0.20,
                        "criterion_mm": 0.10,
                        "ratio": 2.0,
                    },
                }},
            },
        ],
    }

    selection = presentation.worked_example_selection({}, out)

    assert selection["crack_examples"] == [{
        "case_id": "EL-GLOBAL-WIDTH",
        "system": "governing",
        "branch": "crack",
        "label": "long-term",
    }]
    assert selection["crack_comparison"] is None


@pytest.mark.parametrize(
    ("state", "criterion", "expected_criterion"),
    [
        ("NOT REQUESTED", None, "User criterion not specified"),
        ("NOT ASSESSED", 0.20, "User-specified limit 0.200 mm"),
        (
            "CALCULATED - ACCEPTANCE NOT ASSESSED",
            None,
            "User criterion not specified",
        ),
        ("WITHIN USER-SPECIFIED LIMIT", 0.30, "User-specified limit 0.300 mm"),
        ("EXCEEDS USER-SPECIFIED LIMIT", 0.10, "User-specified limit 0.100 mm"),
    ],
)
def test_crack_summary_preserves_exact_bounded_state(
    state, criterion, expected_criterion,
):
    output = {
        "calculation_state": state,
        "value": None if state in {"NOT REQUESTED", "NOT ASSESSED"} else 0.25,
        "criterion_mm": criterion,
        "ratio": (
            2.5 if state == "EXCEEDS USER-SPECIFIED LIMIT"
            else 0.833 if state == "WITHIN USER-SPECIFIED LIMIT"
            else None
        ),
        "criterion_source": "User input - Elastic case EL-01" if criterion else None,
        "reason": "Retained assessment reason",
    }
    rows = presentation.result_summary_rows(
        _inp(mode="Elastic"),
        {"elastic": {
            "converged": True,
            "stress_outputs": {},
            "lambda_cr": 1.0,
            "crack_output": output,
        }},
    )
    crack = next(row for row in rows if row["check"] == "Crack width")

    assert crack["status"] == state
    assert crack["criterion"] == expected_criterion
    assert crack["util"] is None
    assert "Retained assessment reason" in crack["note"]


def test_heightened_crack_summary_is_singleton_and_not_global_utilisation():
    heightened = {
        "status": "PROVIDED AREA BELOW CALCULATED REQUIREMENT",
        "required_reinforcement_area_mm2": 420.0,
        "provided_reinforcement_area_mm2": 350.0,
        "comparison_ratio": 1.2,
        "disclosure": "User-declared applicability.",
    }
    misleading_input = _inp(
        mode="",
        plastic_cases=[],
        elastic_cases=[],
        elastic_case={
            "id": "EL-NOT-APPLICABLE",
            "type": "Must not be inherited",
            "source": "Must not be inherited",
        },
    )
    rows = presentation.multi_case_summary_rows(
        misleading_input,
        {
            "elastic_cases": [],
            "heightened_crack_control": heightened,
        },
    )
    direct_rows = presentation.result_summary_rows(
        misleading_input,
        {"heightened_crack_control": heightened},
    )
    selected = presentation.worked_example_selection(
        {}, {"heightened_crack_control": heightened},
    )
    rows = [row for row in rows if row["check"] == "DK heightened crack-control minimum"]

    assert len(rows) == 1
    assert rows[0]["status"] == "PROVIDED AREA BELOW CALCULATED REQUIREMENT"
    assert rows[0]["util"] is None
    assert rows[0]["case"] == "-"
    assert rows[0]["case_type"] == "-"
    assert rows[0]["source"] == "-"
    direct = next(
        row
        for row in direct_rows
        if row["check"] == "DK heightened crack-control minimum"
    )
    assert direct["case"] == direct["case_type"] == direct["source"] == "-"
    assert selected["heightened_crack_control"] == {
        "result_key": "heightened_crack_control",
    }


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
    assert text == "PASS - Plastic bending | utilisation 80.0 %"
    assert "does not exceed" not in text
    assert "margin" not in text.casefold()
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
    ("interaction", "expected"),
    [
        ({"valid": True, "value": 0.8}, "PASS"),
        ({"valid": True, "value": 1.2}, "FAIL"),
        ({"valid": False, "value": None}, "NOT ASSESSED"),
    ],
)
def test_vt_interaction_status_reports_mathematical_verdict(interaction, expected):
    assert presentation.interaction_assessment_status(interaction) == expected


def test_plastic_state_rows_returns_only_the_retained_solver_rows():
    concrete_rows = [
        {
            "point_no": 1,
            "ring": "Outer",
            "strain_permille": -3.1,
            "stress_mpa": -20.0,
        }
    ]
    reinforcement_rows = [
        {
            "element_type": "Bar",
            "element_id": "R1",
            "material_id": "M1",
            "strain_permille": 2.5,
            "stress_mpa": 500.0,
            "force_kn": 250.0,
        },
        {
            "element_type": "Tendon",
            "element_id": "P1",
            "material_id": "P1",
            "strain_permille": 7.0,
            "stress_mpa": 1_400.0,
            "force_kn": 210.0,
        },
    ]
    point = {
        "V": 90.0,
        "na_x": float("inf"),
        "na_y": 0.0,
        "concrete_corner_states": concrete_rows,
        "reinforcement_states": reinforcement_rows,
    }
    rows = presentation.plastic_state_rows(point)

    assert rows["concrete"] == concrete_rows
    assert rows["elements"] == reinforcement_rows
    assert rows["concrete"] is not concrete_rows
    assert rows["elements"] is not reinforcement_rows
    assert rows["halfplane"] == pytest.approx((0.0, 1.0, 0.0))


def test_plastic_state_rows_has_no_material_or_solver_input_boundary():
    assert tuple(inspect.signature(presentation.plastic_state_rows).parameters) == (
        "point",
    )
    source = inspect.getsource(presentation.plastic_state_rows)
    assert ".stress(" not in source
    assert "Concrete(" not in source
    assert "MildSteel(" not in source
    assert "Prestress(" not in source

    rows = presentation.plastic_state_rows(
        {"V": 0.0, "na_x": 0.0, "na_y": float("inf")}
    )
    assert rows["concrete"] == []
    assert rows["elements"] == []


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
        "stress_outputs": {
            "concrete": {
                "value": 12.0, "calculation_state": "CALCULATED",
                "quantity": "maximum concrete compression",
            },
            "reinforcement": {
                "value": 450.0, "calculation_state": "CALCULATED",
                "quantity": "maximum reinforcement tension",
                "governing": "bar 1",
            },
        },
        "lambda_cr": 0.82,
        "cracked": True,
        "show_cw": False,
    }
    rows = presentation.result_summary_rows(
        _inp(), {"plastic": _plastic(), "elastic": elastic},
    )
    by_check = {row["check"]: row for row in rows}

    assert by_check["Plastic bending"]["case"] == "PL-17"
    assert by_check["Concrete stress"]["case"] == "EL-08"
    assert by_check["Plastic bending"]["status"] == "PASS"
    assert by_check["Reinforcement stress"]["status"] == "CALCULATED"
    assert by_check["Reinforcement stress"]["criterion"] == "Output only"
    assert by_check["Reinforcement stress"]["util"] is None
    assert by_check["Cracking threshold/state"]["status"] == "CALCULATED"
    assert by_check["Cracking threshold/state"]["result"] == (
        "lambda_cr 0.820; cracked"
    )
    assert by_check["Cracking threshold/state"]["criterion"] == "Output only"
    assert presentation.overall_summary_status(rows) == "PASS"


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
        "method": "DK NA",
        "dkna_sum": 0.80,
        "crushing": {"valid": True, "value": 1.10, "cot": 1.5},
        "transverse": {
            "valid": True, "cot": 1.5,
            "u_crush": 1.10, "u_stirrup": 0.75,
            "shear_fraction": 0.30, "torsion_fraction": 0.45,
            "governing": 1.10, "governs": "crushing",
        },
        "longitudinal": {
            "valid": True, "util": 0.65, "axis": "x", "biaxial": False,
        },
        "chord_off": {"valid": True, "util": 0.55, "axis": "y"},
        "governing_longitudinal": {
            "valid": True, "util": 0.65, "axis": "x", "biaxial": False,
        },
        "longitudinal_all_conditional": True,
    }
    rows = presentation.result_summary_rows(
        _inp(mode="Plastic", combined_on=True),
        {"plastic": _plastic(), "combined": combined},
    )
    by_check = {row["check"]: row for row in rows}

    assert by_check["Combined M-V-T - DK NA sum"]["status"] == "PASS"
    assert by_check["Combined concrete compression strut"]["status"] == "FAIL"
    assert by_check["Combined closed stirrup"]["status"] == "PASS"
    assert by_check["Combined longitudinal reinforcement"]["status"] == "PASS"
    assert by_check["Combined longitudinal reinforcement"]["util"] == pytest.approx(
        0.65
    )
    assert "Combined transverse reinforcement" not in by_check
    assert "Combined off-axis chord" not in by_check
    assert presentation.overall_summary_status(rows) == "FAIL"


def test_combined_summary_withholds_verdict_for_fallback_or_missing_checks():
    combined = {
        "valid": True,
        "method": "DK NA",
        "dkna_sum": 0.80,
        "crushing": None,
        "transverse": None,
        "longitudinal": {
            "valid": True, "util": 0.60, "axis": "x",
            "biaxial": True, "conditional": False,
        },
        "governing_longitudinal": {
            "valid": True, "util": 0.60, "axis": "x",
            "biaxial": True, "conditional": False,
        },
        "longitudinal_fallback": {
            "valid": True, "util": 0.60, "axis": "x",
            "biaxial": True, "conditional": False,
        },
        "longitudinal_all_conditional": False,
    }
    rows = presentation.result_summary_rows(
        _inp(mode="Plastic", combined_on=True),
        {"plastic": _plastic(), "combined": combined},
    )
    by_check = {row["check"]: row for row in rows}

    assert by_check["Combined concrete compression strut"]["status"] == "NOT ASSESSED"
    assert by_check["Combined closed stirrup"]["status"] == "NOT ASSESSED"
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
        "method": "DK NA",
        "dkna_sum": 0.80,
        "crushing": {"valid": True, "value": 0.70, "cot": 1.5},
        "transverse": {
            "valid": True, "cot": 1.5,
            "u_crush": 0.70, "u_stirrup": 0.75,
            "shear_fraction": 0.25, "torsion_fraction": 0.50,
            "governing": 0.75, "governs": "stirrups",
        },
        "longitudinal": {
            "valid": True,
            "util": 0.65,
            "axis": "x",
            "biaxial": False,
            "off_not_evaluated": "not_solved",
        },
        "governing_longitudinal": {
            "valid": True,
            "util": 0.65,
            "axis": "x",
            "biaxial": False,
            "off_not_evaluated": "not_solved",
        },
        "longitudinal_all_conditional": True,
    }
    rows = presentation.result_summary_rows(
        _inp(mode="Plastic", combined_on=True),
        {"plastic": _plastic(), "combined": combined},
    )
    by_check = {row["check"]: row for row in rows}

    assert by_check["Combined longitudinal reinforcement"]["status"] == "NOT ASSESSED"
    assert "not solved" in by_check["Combined longitudinal reinforcement"]["note"]
    assert "Combined off-axis chord coverage" not in by_check
    assert presentation.overall_summary_status(rows) == "NOT ASSESSED"


def test_combined_physical_components_uses_the_governing_longitudinal_face():
    shear_axis = {
        "valid": True, "util": 0.60, "axis": "x",
        "tension_low": True, "biaxial": False, "conditional": True,
    }
    governing = {
        "valid": True, "util": 0.85, "axis": "y",
        "tension_low": False, "biaxial": True, "conditional": True,
    }
    components = presentation.combined_physical_components({
        "transverse": {
            "valid": True, "cot": 1.6,
            "u_crush": 0.40, "u_stirrup": 0.55,
            "shear_fraction": 0.20, "torsion_fraction": 0.35,
        },
        "longitudinal": shear_axis,
        "chord_off": governing,
        "governing_longitudinal": governing,
        "longitudinal_all_conditional": True,
    })

    assert [item["label"] for item in components] == [
        "Concrete compression strut",
        "Closed stirrup",
        "Longitudinal reinforcement",
    ]
    longitudinal = components[2]
    assert longitudinal["status"] == "PASS"
    assert longitudinal["util"] == pytest.approx(0.85)
    assert "y-axis positive face" in longitudinal["note"]


def test_combined_components_withhold_verdict_for_non_governing_fallback():
    fallback = {
        "valid": True, "util": 0.60, "axis": "x",
        "tension_low": True, "biaxial": False, "conditional": False,
    }
    governing = {
        "valid": True, "util": 0.85, "axis": "y",
        "tension_low": False, "biaxial": True, "conditional": True,
    }
    components = presentation.combined_physical_components({
        "transverse": {
            "valid": True, "cot": 1.6,
            "u_crush": 0.40, "u_stirrup": 0.55,
            "shear_fraction": 0.20, "torsion_fraction": 0.35,
        },
        "longitudinal": fallback,
        "chord_off": governing,
        "governing_longitudinal": governing,
        "longitudinal_fallback": fallback,
        "longitudinal_all_conditional": False,
    })

    longitudinal = components[2]
    assert longitudinal["util"] == pytest.approx(0.85)
    assert longitudinal["status"] == "NOT ASSESSED"
    assert "pure-axis fallback" in longitudinal["note"]
    assert "x-axis negative face" in longitudinal["note"]


def test_combined_components_preserve_non_governing_face_fallback():
    exact_governing = {
        "valid": True, "util": 0.85, "axis": "x",
        "tension_low": False, "conditional": True,
    }
    fallback_face = {
        "valid": True, "util": 0.60, "axis": "x",
        "tension_low": True, "conditional": False,
    }
    components = presentation.combined_physical_components({
        "transverse": {
            "valid": True, "cot": 1.6,
            "u_crush": 0.40, "u_stirrup": 0.55,
            "shear_fraction": 0.20, "torsion_fraction": 0.35,
        },
        "longitudinal": exact_governing,
        "longitudinal_candidates": [fallback_face, exact_governing],
        "governing_longitudinal": exact_governing,
        "longitudinal_fallback": fallback_face,
        "longitudinal_all_conditional": False,
    })

    longitudinal = components[2]
    assert longitudinal["util"] == pytest.approx(0.85)
    assert longitudinal["status"] == "NOT ASSESSED"
    assert "x-axis negative face" in longitudinal["note"]


def test_combined_physical_components_tolerates_missing_candidate_utilisation():
    governing = {"valid": True, "util": 0.75, "axis": "y"}
    components = presentation.combined_physical_components({
        "transverse": None,
        "longitudinal": {"valid": True, "util": None, "axis": "x"},
        "chord_off": governing,
        "governing_longitudinal": governing,
        "longitudinal_all_conditional": True,
    })
    assert components[2]["util"] == pytest.approx(0.75)


def test_combined_physical_components_withholds_off_axis_only_verdict():
    governing = {"valid": True, "util": 0.75, "axis": "y"}
    components = presentation.combined_physical_components({
        "transverse": None,
        "longitudinal": None,
        "chord_off": governing,
        "governing_longitudinal": governing,
        "longitudinal_all_conditional": True,
    })
    assert components[2]["status"] == "NOT ASSESSED"
    assert "shear-axis" in components[2]["note"]


def test_combined_physical_components_tolerates_missing_strut_angle():
    governing = {"valid": True, "util": 0.60, "axis": "x"}
    components = presentation.combined_physical_components({
        "transverse": {
            "valid": True, "cot": None,
            "u_crush": 0.40, "u_stirrup": 0.55,
            "shear_fraction": 0.20, "torsion_fraction": 0.35,
        },
        "longitudinal": governing,
        "governing_longitudinal": governing,
        "longitudinal_all_conditional": True,
    })
    assert components[0]["status"] == "PASS"
    assert components[0]["note"] == "V-T crushing at the shared member angle"


def test_combined_components_fail_closed_without_retained_governing_chord():
    components = presentation.combined_physical_components({
        "longitudinal": {
            "valid": True, "util": 0.60, "axis": "x",
            "tension_low": True, "conditional": True,
        },
        "chord_off": {
            "valid": True, "util": 0.85, "axis": "y",
            "tension_low": False, "conditional": True,
        },
        "longitudinal_all_conditional": True,
    })

    assert components[2]["status"] == "NOT ASSESSED"
    assert components[2]["util"] is None


def test_combined_component_formatter_does_not_reselect_governing_chords():
    source = inspect.getsource(presentation.combined_physical_components)

    assert "governing_longitudinal" in source
    assert "max(" not in source
    assert "candidate_util" not in source


def test_shear_screening_does_not_fail_when_selected_links_pass():
    shear = {
        "res": {"valid": True, "vrd_c": 100.0},
        "util": 1.20,
        "method": "DK NA",
        "links": {
            "res": {"valid": True, "governs": "links"},
            "util": 0.80,
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
    )

    rows = presentation.result_summary_rows(
        _inp(mode="Plastic", shear_on=True, shear_links=False),
        {"plastic": _plastic(), "shear": aggregate},
    )
    by_check = {row["check"]: row for row in rows}

    assert by_check["Shear Vx without links"]["status"] == "PASS"
    assert by_check["Shear Vy without links"]["status"] == "PASS"
    assert by_check["Generic cross-direction shear interaction"]["status"] == (
        "NOT CALCULATED"
    )
    assert presentation.overall_summary_status(rows) == "PASS"


def test_biaxial_combined_summary_reports_directions_without_three_way_verdict():
    combined = {
        "biaxial": True,
        "directions": {
            "vx": {
                "valid": True, "dkna_sum": 0.72, "dkna_ok": True,
                "method": "DK NA",
            },
            "vy": {
                "valid": True, "dkna_sum": 1.14, "dkna_ok": False,
                "method": "DK NA",
            },
        },
    }
    rows = presentation.result_summary_rows(
        _inp(mode="Plastic", combined_on=True),
        {"plastic": _plastic(), "combined": combined},
    )
    by_check = {row["check"]: row for row in rows}

    assert by_check["Combined Vx+T - DK NA sum"]["status"] == "PASS"
    assert by_check["Combined Vy+T - DK NA sum"]["status"] == "FAIL"
    assert by_check["Combined Vx+T - DK NA sum"]["criterion"] == "<= 100 %"
    assert by_check["Generic Vx-Vy-T interaction"]["status"] == "NOT CALCULATED"
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


@pytest.mark.parametrize(
    ("fatigue", "stale", "status"),
    [
        (None, False, "NOT RUN"),
        ({
            "governing_spectrum": "Traffic",
            "utilisation": 0.75,
            "converged": True,
            "passed": True,
            "warnings": (),
        }, False, "PASS"),
        ({
            "governing_spectrum": "Traffic",
            "utilisation": 1.20,
            "converged": True,
            "passed": False,
            "warnings": (),
        }, False, "FAIL"),
        ({
            "governing_spectrum": "Traffic",
            "utilisation": 0.75,
            "converged": True,
            "passed": True,
            "warnings": ("Spectrum source is not stated",),
        }, False, "REVIEW"),
        ({
            "governing_spectrum": "Traffic",
            "utilisation": 0.75,
            "converged": False,
            "passed": False,
            "warnings": (),
        }, False, "INVALID"),
        ({
            "governing_spectrum": "Traffic",
            "utilisation": 0.75,
            "converged": True,
            "passed": True,
            "warnings": (),
        }, True, "STALE"),
    ],
)
def test_fatigue_summary_prevents_a_false_overall_pass(
        fatigue, stale, status):
    inp = _inp(
        mode="",
        fatigue_on=True,
        fatigue_edition=DesignBasisKey.FIRST_GEN_DK_NA_2024.value,
        fatigue_basis={"method": "User-defined grouped spectrum"},
    )
    results = {"fatigue": fatigue} if fatigue is not None else {}

    rows = presentation.multi_case_summary_rows(
        inp, results, stale=stale
    )

    assert len(rows) == 1
    assert rows[0]["check"] == "Fatigue"
    assert rows[0]["status"] == status
    assert presentation.overall_summary_status(rows) == status


def test_stale_fatigue_summary_uses_the_calculated_basis_not_live_edits():
    inp = _inp(
        mode="",
        fatigue_on=True,
        fatigue_edition="NEW EDITION",
        fatigue_basis={
            "method": "NEW METHOD",
            "spectrum_source": "NEW SOURCE",
        },
    )
    fatigue = {
        "edition": "CALCULATED EDITION",
        "basis": {
            "method": "CALCULATED METHOD",
            "spectrum_source": "CALCULATED SOURCE",
        },
        "governing_spectrum": "OLD SPECTRUM",
        "utilisation": 0.75,
        "converged": True,
        "passed": True,
        "warnings": (),
    }

    row = presentation.fatigue_summary_rows(
        inp, {"fatigue": fatigue}, stale=True
    )[0]

    assert row["status"] == "STALE"
    assert row["case"] == "OLD SPECTRUM"
    assert row["case_type"] == "CALCULATED EDITION"
    assert row["source"] == "CALCULATED SOURCE"


def test_fatigue_summary_formats_stable_keys_and_prefers_result_basis_label():
    live_basis = DesignBasisKey.PUBLISHED_2023
    calculated_basis = DesignBasisKey.FIRST_GEN_DK_NA_2024
    inp = _inp(
        mode="",
        fatigue_on=True,
        fatigue_edition=live_basis.value,
        fatigue_basis={"method": "Grouped"},
    )
    not_run = presentation.fatigue_summary_rows(inp, {})[0]
    assert not_run["case_type"] == get_design_basis(live_basis).label
    assert live_basis.value not in not_run["case_type"]

    calculated_label = get_design_basis(calculated_basis).label
    fatigue = {
        "basis_key": calculated_basis.value,
        "basis_label": calculated_label,
        "edition": "legacy fallback must not win",
        "basis": {"method": "Grouped"},
        "governing_spectrum": "Traffic",
        "utilisation": 0.75,
        "converged": True,
        "passed": True,
        "warnings": (),
    }
    stale = presentation.fatigue_summary_rows(
        inp,
        {"fatigue": fatigue},
        stale=True,
    )[0]
    assert stale["case_type"] == calculated_label
    assert stale["status"] == "STALE"


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


def test_detailing_summary_reports_values_status_and_target_view():
    minimum = {
        "status": "PASS",
        "clause": "9.2.1.1(1), Formula (9.1N)",
        "checks": [{
            "type": "minimum area", "status": "PASS",
            "axis": "x", "face": "bottom",
            "as_provided_mm2": 628.0, "as_min_mm2": 410.0,
            "utilisation": 410.0 / 628.0,
        }],
    }
    spacing = {
        "status": "FAIL", "clause": "8.2(2)",
        "governing": {
            "first_id": "R1", "second_id": "R2", "clear_mm": 18.0,
            "required_mm": 25.0,
        },
    }

    rows = presentation.result_summary_rows(
        _inp(
            mode="Plastic",
            minimum_reinforcement_on=True,
            clear_spacing_on=True,
        ),
        {"minimum_reinforcement": minimum, "clear_spacing": spacing},
    )
    by_check = {row["check"]: row for row in rows}

    minimum_row = by_check["Longitudinal minimum reinforcement Mx bottom"]
    assert minimum_row["status"] == "PASS"
    assert "As,prov 628.0" in minimum_row["result"]
    assert minimum_row["view"] == "Detailing"
    spacing_row = by_check["Reinforcement clear spacing"]
    assert spacing_row["status"] == "FAIL"
    assert spacing_row["result"] == "18.0 mm (R1-R2)"
    assert spacing_row["note"] == "8.2(2)"
    assert presentation.overall_summary_status(rows) == "FAIL"


def test_detailing_summary_uses_retained_direction_then_optional_alias():
    minimum = {
        "status": "PASS",
        "modelled_reinforcement_direction": "transverse",
        "checks": [],
    }

    rows = presentation.result_summary_rows(
        _inp(
            mode="Plastic",
            minimum_reinforcement_on=True,
            detailing_cut_direction="Transverse cut",
            **{modelled_direction.ALIAS_KEY: "cross-span"},
        ),
        {"minimum_reinforcement": minimum},
    )

    assert rows[-1]["check"] == (
        "Transverse (project alias: cross-span) minimum reinforcement"
    )


def test_transverse_detailing_summary_keeps_ratio_and_spacing_evidence():
    transverse = {
        "status": "FAIL",
        "edition": "DS/EN 1992-1-1:2005 + DK NA:2024",
        "checks": [
            {
                "kind": "minimum_ratio",
                "scope": "Shear VX",
                "status": "PASS",
                "provided": 0.00120,
                "limit": 0.00069,
                "utilisation": 0.575,
                "clause": "9.2.2(5)",
            },
            {
                "kind": "transverse_leg_spacing",
                "scope": "Shear VX",
                "status": "FAIL",
                "provided": 500.0,
                "limit": 412.5,
                "utilisation": 500.0 / 412.5,
                "clause": "9.2.2(8)",
                "spacing_source": "user",
                "measurement_axis": "y",
            },
        ],
    }
    rows = presentation.result_summary_rows(
        _inp(mode="Plastic", transverse_detailing_on=True),
        {"transverse_reinforcement": transverse},
    )
    ratio = next(row for row in rows if "minimum ratio" in row["check"])
    spacing = next(
        row for row in rows if "transverse leg spacing along y" in row["check"]
    )
    assert ratio["status"] == "PASS"
    assert "0.00120" in ratio["result"]
    assert spacing["status"] == "FAIL"
    assert spacing["criterion"] == "sprov <= smax = 412.5 mm"
    assert spacing["view"] == "Detailing"


def test_link_detailing_summary_states_when_required_links_are_missing():
    transverse = {
        "status": "FAIL",
        "edition": "DS/EN 1992-1-1:2005 + DK NA:2024",
        "checks": [{
            "kind": "required_links",
            "scope": "Shear VX",
            "status": "FAIL",
            "provided": 0.0,
            "limit": 1.0,
            "utilisation": math.inf,
            "clause": "6.2.2",
            "reason": "shear resistance without links is insufficient",
        }],
    }
    rows = presentation.result_summary_rows(
        _inp(mode="Plastic", transverse_detailing_on=True),
        {"transverse_reinforcement": transverse},
    )
    row = next(item for item in rows if "required links" in item["check"])
    assert row["status"] == "FAIL"
    assert row["result"] == "No links defined"
    assert row["criterion"] == "Links required"
    assert row["note"] == "6.2.2; shear resistance without links is insufficient"


def test_link_detailing_summary_does_not_treat_missing_links_as_not_applicable():
    plastic_cases = [{
        "name": "PL-SHEAR",
        "actions": {
            "name": "PL-SHEAR",
            "description": "",
            "n_ed_kn": 0.0,
            "mx_ed_knm": 0.0,
            "my_ed_knm": 0.0,
            "vx_ed_kn": 50.0,
            "vy_ed_kn": 0.0,
            "t_ed_knm": 0.0,
        },
        "evaluated": False,
        "results": {},
    }]
    rows = presentation.multi_case_summary_rows(
        _inp(
            mode="",
            transverse_detailing_on=True,
            shear_on=True,
            shear_links=False,
            torsion_on=False,
            plastic_cases=[plastic_cases[0]["actions"]],
        ),
        {"plastic_cases": plastic_cases},
    )
    row = next(
        item for item in rows
        if item["check"] == "Shear/torsion link detailing"
    )
    assert row["status"] == "NOT RUN"
    assert row["note"] == "Calculate required"


def test_detailing_summary_labels_one_biaxial_resultant_check():
    minimum = {
        "status": "PASS",
        "clause": "9.2.1.1(1), Formula (9.1N)",
        "checks": [{
            "type": "minimum area", "status": "PASS", "axis": "xy",
            "face": "resultant tension zone",
            "as_provided_mm2": 800.0, "as_min_mm2": 500.0,
            "utilisation": 0.625,
        }],
    }

    rows = presentation.result_summary_rows(
        _inp(mode="Plastic", minimum_reinforcement_on=True),
        {"minimum_reinforcement": minimum},
    )

    biaxial = next(
        row for row in rows
        if row["check"].startswith("Longitudinal minimum reinforcement")
    )
    assert biaxial["check"] == (
        "Longitudinal minimum reinforcement Mx+My resultant"
    )
    assert biaxial["status"] == "PASS"


def test_failed_2005_minimum_area_summary_is_not_presented_as_2023_resistance():
    minimum = {
        "status": "FAIL",
        "clause": "9.2.1.1(1), Formula (9.1N)",
        "checks": [{
            "type": "minimum area", "status": "FAIL", "axis": "xy",
            "face": "resultant tension zone", "as_provided_mm2": 0.0,
            "as_min_mm2": None, "utilisation": None,
            "reason": "No ordinary reinforcement bar lies in the tension zone.",
        }],
    }

    rows = presentation.result_summary_rows(
        _inp(mode="Plastic", minimum_reinforcement_on=True),
        {"minimum_reinforcement": minimum},
    )

    row = next(
        item for item in rows
        if item["check"].startswith("Longitudinal minimum reinforcement")
    )
    assert row["status"] == "FAIL"
    assert row["result"] == "As,prov 0.0 mm2; As,min -"
    assert row["criterion"] == "As,prov >= As,min"
    assert "MR,nom" not in row["result"]


def test_multi_case_summary_adds_section_wide_spacing_only_once():
    inp = _inp(
        mode="Plastic",
        plastic_cases=[],
        elastic_cases=[],
        minimum_reinforcement_on=True,
        clear_spacing_on=True,
        shear_on=False,
        torsion_on=False,
        combined_on=False,
    )
    first = _plastic_case_entry("PL-A", 0.60)
    second = _plastic_case_entry("PL-B", 0.70)
    for entry in (first, second):
        entry["actions"]["check_minimum_reinforcement"] = True
        entry["results"]["minimum_reinforcement"] = {
            "status": "PASS",
            "clause": "9.2.1.1(1)",
            "checks": [{
                "type": "minimum area", "status": "PASS",
                "axis": "x", "face": "bottom",
                "as_provided_mm2": 600.0, "as_min_mm2": 400.0,
                "utilisation": 2.0 / 3.0,
            }],
        }
    spacing = {
        "status": "PASS", "clause": "8.2(2)",
        "governing": {
            "first_id": "R1", "second_id": "R2", "clear_mm": 40.0,
            "required_mm": 25.0,
        },
    }

    rows = presentation.multi_case_summary_rows(inp, {
        "plastic_cases": [first, second],
        "clear_spacing": spacing,
    })

    assert sum(
        row["check"] == "Reinforcement clear spacing" for row in rows
    ) == 1
    assert not any(row["status"] == "NOT RUN" for row in rows)
    spacing_row = next(
        row for row in rows if row["check"] == "Reinforcement clear spacing"
    )
    assert spacing_row["case"] == "-"
    assert presentation.overall_summary_status(rows) == "PASS"
    minimum_rows = [
        row for row in rows
        if row["check"].startswith("Longitudinal minimum reinforcement")
    ]
    assert [row["case"] for row in minimum_rows] == ["PL-A", "PL-B"]
