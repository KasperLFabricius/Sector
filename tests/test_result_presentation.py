"""Display-only assessment and QA-evidence helpers."""

from __future__ import annotations

import copy
import math
import inspect
import pathlib
import sys
from dataclasses import asdict

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import result_presentation as presentation  # noqa: E402

from app import modelled_direction  # noqa: E402
from sector import codes, combined as combined_core  # noqa: E402
from sector.design_standards import DesignBasisKey, get_design_basis  # noqa: E402


@pytest.mark.parametrize(
    ("family", "state"),
    (
        ("shear", "stirrups (VRd,s)"),
        ("shear", "crushing (VRd,max)"),
        ("torsion", "stirrups (TRd,s)"),
        ("torsion", "crushing (TRd,max)"),
    ),
)
def test_authored_resistance_governing_states_survive_exactly(family, state):
    assert presentation.result_reason(state, family) == state


def test_minimum_reinforcement_unresolved_refinement_has_authored_guidance():
    retained = (
        "nominal resistance is too close to the cracking demand for a stable "
        "assessment at the available angular resolution"
    )

    assert presentation.result_reason(
        retained,
        "minimum_reinforcement",
        context="CORE-M02 public result",
    ) == (
        "The nominal resistance is too close to the cracking demand for a stable "
        "assessment; assess this case separately"
    )


def test_minimum_reinforcement_moving_direction_failure_has_authored_guidance():
    assert presentation.result_reason(
        "nominal governing interval could not be refined consistently",
        "minimum_reinforcement",
        context="CORE-M02 public result",
    ) == (
        "The governing nominal resistance direction could not be refined "
        "consistently; assess this case separately"
    )


def test_slab_tendon_face_failure_has_authored_crack_guidance():
    retained = (
        "Move every tendon far enough inside the physical top and bottom slab "
        "faces to provide non-negative clear cover before relying on crack-width "
        "results."
    )

    assert presentation.result_reason(
        retained,
        "crack",
        context="QS-H01 public result",
    ) == retained


@pytest.mark.parametrize(
    ("retained", "expected_mm"),
    ((0.275, 275.0), (0.0, 0.0), (-0.0, 0.0), (np.float64(0.125), 125.0)),
)
def test_plastic_compression_depth_uses_only_retained_nonnegative_value(
    retained,
    expected_mm,
):
    point = {"compression_depth": retained, "na_y": 999.0}
    before = dict(point)

    result = presentation.plastic_compression_depth_mm(point)

    assert type(result) is float
    assert result == pytest.approx(expected_mm)
    if expected_mm == 0.0:
        assert math.copysign(1.0, result) == 1.0
    assert point == before


@pytest.mark.parametrize(
    "retained",
    (
        None,
        True,
        np.bool_(False),
        "0.275",
        -0.1,
        math.nan,
        math.inf,
        -math.inf,
        np.finfo(float).max,
    ),
)
def test_plastic_compression_depth_rejects_unavailable_or_malformed_evidence(
    retained,
):
    point = {"compression_depth": retained, "na_y": 0.275}
    before = dict(point)

    assert presentation.plastic_compression_depth_mm(point) is None
    assert point == before


def test_plastic_compression_depth_requires_a_retained_mapping_field():
    assert presentation.plastic_compression_depth_mm({"na_y": 0.275}) is None
    assert presentation.plastic_compression_depth_mm(None) is None


def test_worked_example_selection_retains_named_cases_branches_and_directions():
    out = {
        "plastic_cases": [
            {
                "name": "PL-A",
                "results": {
                    "plastic": {
                        "converged": True,
                        "closed": True,
                        "check_util": True,
                        "util": 0.7,
                        "util_valid": True,
                    },
                    "shear": {"directions": {
                        "vx": {"res": {"valid": True}, "util": 0.8},
                        "vy": {"res": {"valid": True}, "util": 0.8},
                    }},
                },
            },
            {
                "name": "PL-B",
                "results": {
                    "plastic": {
                        "converged": True,
                        "closed": True,
                        "check_util": True,
                        "util": 0.9,
                        "util_valid": True,
                    },
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


@pytest.mark.parametrize(
    ("check", "status", "note"),
    [
        (
            {
                "applicable": True,
                "status": "PASS",
                "scope_key": "applicable_first_generation_rectangle",
                "value": 0.8,
                "ok": True,
            },
            "PASS",
            "approximately solid rectangular section",
        ),
        (
            {
                "applicable": False,
                "status": "NOT APPLICABLE",
                "scope_key": "section_geometry",
                "value": None,
                "ok": None,
            },
            "NOT APPLICABLE",
            "complete shear-and-torsion checks",
        ),
        (
            {
                "applicable": False,
                "status": "NOT ASSESSED",
                "scope_key": "shear_resistance_unavailable",
                "value": None,
                "ok": None,
            },
            "NOT ASSESSED",
            "Calculate the first-generation V_Rd,c shear result",
        ),
    ],
)
def test_formula_631_status_and_engineer_guidance_are_retained(
    check,
    status,
    note,
):
    assert presentation.minimum_reinforcement_screen_status(check) == status
    assert note in presentation.minimum_reinforcement_screen_note(check)


def test_formula_631_scope_row_remains_in_the_governing_overview():
    inp = {
        "mode": "",
        "torsion_on": True,
        "plastic_case": {"id": "PL-631", "type": "ULS", "source": "C1"},
    }
    torsion = {
        "valid": True,
        "tube_valid": True,
        "transverse_resistance_assessed": True,
        "closed_links_present": True,
        "assessment_status": "NOT ASSESSED",
        "min_reinf": {
            "applicable": False,
            "status": "NOT APPLICABLE",
            "scope_key": "selected_2023_route",
            "value": None,
            "ok": None,
        },
    }

    selected = presentation.governing_summary_rows(
        presentation.result_summary_rows(inp, {"torsion": torsion})
    )
    result_rows = presentation.governing_result_rows(selected)
    information_rows = presentation.governing_information_rows(selected)
    screen = next(row for row in result_rows if "6.31" in row["check"])

    assert screen["status"] == "NOT APPLICABLE"
    assert "selected 2023 shear method" in screen["note"]
    assert "Assess shear using the 2023 check" in screen["note"]
    assert "assess torsion and interaction using their selected methods" in screen["note"]
    assert "reported 2023 shear check" not in screen["note"]
    assert "2023 shear-and-torsion" not in screen["note"]
    assert screen not in information_rows


@pytest.mark.parametrize(
    ("scope_context", "scope_overrides"),
    (
        ("nonrectangular", {"solid_rectangle": False}),
        ("hollow", {"solid_rectangle": False}),
        (
            "subdivided",
            {"solid_rectangle": False, "subdivided": True},
        ),
        (
            "unavailable-shear",
            {"shear_available": False, "v_ed": None, "vrd_c": None},
        ),
        (
            "selected-2023",
            {
                "model_2023": True,
                "shear_method": "DS/EN 1992-1-1:2023",
                "torsion_method": "DS/EN 1992-1-1:2005 + DK NA:2024",
            },
        ),
    ),
    ids=lambda value: value if isinstance(value, str) else None,
)
@pytest.mark.parametrize(
    ("action", "value"),
    (
        ("n_ed", -20.0),
        ("n_ed", 20.0),
        ("mx_ed", -15.0),
        ("mx_ed", 15.0),
        ("my_ed", -10.0),
        ("my_ed", 10.0),
    ),
)
def test_formula_631_overview_keeps_dkna_combined_requirement(
    scope_context,
    scope_overrides,
    action,
    value,
):
    inputs = dict(
        t_ed=15.0,
        trd_c=60.0,
        v_ed=30.0,
        vrd_c=120.0,
        solid_rectangle=True,
        subdivided=False,
        model_2023=False,
        shear_available=True,
        dk_na=True,
        shear_method="DS/EN 1992-1-1:2005 + DK NA:2024",
        torsion_method="DS/EN 1992-1-1:2005 + DK NA:2024",
        n_ed=0.0,
        mx_ed=0.0,
        my_ed=0.0,
    )
    inputs.update(scope_overrides)
    inputs[action] = value
    minimum = asdict(
        combined_core.minimum_reinforcement_screen_result(**inputs)
    )
    inp = {
        "mode": "",
        "torsion_on": True,
        "plastic_case": {"id": "PL-DK", "type": "ULS", "source": "C1"},
    }
    torsion = {
        "valid": True,
        "tube_valid": True,
        "transverse_resistance_assessed": True,
        "closed_links_present": True,
        "assessment_status": "NOT ASSESSED",
        "min_reinf": minimum,
    }

    rows = presentation.result_summary_rows(inp, {"torsion": torsion})
    screen = next(
        row for row in rows
        if row["check"] == "Formula (6.31) minimum-reinforcement screen"
    )

    assert screen["status"] == "NOT APPLICABLE"
    assert scope_context in {
        "nonrectangular", "hollow", "subdivided", "unavailable-shear",
        "selected-2023",
    }
    if scope_context == "selected-2023":
        assert minimum["model_2023"] is True
        assert minimum["shear_method"] == "DS/EN 1992-1-1:2023"
        assert minimum["torsion_method"] == "DS/EN 1992-1-1:2005 + DK NA:2024"
    assert "DK NA 6.3.2(6) combined N-M-V-T check" in screen["note"]
    assert "low-action condition satisfied" not in screen["note"].casefold()


@pytest.mark.parametrize("condition_status", ("PASS", "FAIL"))
@pytest.mark.parametrize(
    ("detailing_status", "detailing_scope_key"),
    (
        ("PASS", "separate_detailing_passed"),
        ("FAIL", "separate_detailing_failed"),
        ("NOT RUN", "separate_detailing_not_run"),
    ),
)
def test_formula_631_condition_and_detailing_matrix_remain_separate(
    condition_status,
    detailing_status,
    detailing_scope_key,
):
    value = 0.8 if condition_status == "PASS" else 1.2
    minimum = {
        "applicable": True,
        "status": condition_status,
        "scope_key": "applicable_first_generation_rectangle",
        "value": value,
        "ok": condition_status == "PASS",
        "detailing_status": detailing_status,
        "detailing_scope_key": detailing_scope_key,
    }
    inp = {
        "mode": "",
        "torsion_on": True,
        "plastic_case": {"id": "PL-631", "type": "ULS", "source": "C1"},
    }
    torsion = {
        "valid": True,
        "tube_valid": True,
        "transverse_resistance_assessed": True,
        "closed_links_present": True,
        "assessment_status": "NOT ASSESSED",
        "min_reinf": minimum,
    }

    rows = presentation.result_summary_rows(inp, {"torsion": torsion})
    condition = next(
        row for row in rows
        if row.get("overview_key") == "torsion:minimum_reinforcement"
    )
    detailing = next(
        row for row in rows
        if row.get("overview_key")
        == "torsion:minimum_reinforcement:detailing"
    )

    assert condition["status"] == condition_status
    assert presentation.minimum_reinforcement_screen_outcome(minimum) in {
        "low-action condition satisfied",
        "low-action condition not satisfied",
    }
    assert "suffices" not in condition["note"].casefold()
    assert detailing["status"] == detailing_status
    assert detailing["overview_scope_in_result_table"] is True
    if detailing_status == "PASS":
        assert "ratio and spacing" in detailing["note"]
    elif detailing_status == "FAIL":
        assert "checks fail" in detailing["note"]
    else:
        assert "was not selected" in detailing["note"]


def test_crack_comparison_selection_uses_largest_width_not_largest_ratio():
    out = {
        "elastic_cases": [
            {
                "name": "EL-LARGEST-WIDTH",
                "results": {"elastic": {
                    "converged": True,
                    "crack_output": {
                        "long_term": {
                            "duration": "long_term",
                            "calculation_state": "WITHIN USER-SPECIFIED LIMIT",
                            "value": 0.30,
                            "criterion_mm": 0.40,
                            "ratio": 0.75,
                        },
                    },
                }},
            },
            {
                "name": "EL-LARGEST-RATIO",
                "results": {"elastic": {
                    "converged": True,
                    "crack_output": {
                        "long_term": {
                            "duration": "long_term",
                            "calculation_state": "EXCEEDS USER-SPECIFIED LIMIT",
                            "value": 0.20,
                            "criterion_mm": 0.10,
                            "ratio": 2.0,
                        },
                    },
                }},
            },
        ],
    }

    selection = presentation.worked_example_selection({}, out)

    assert selection["crack_comparison"] == {
        "case_id": "EL-LARGEST-WIDTH",
        "duration": "long_term",
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
                        "long_term": {
                            "duration": "long_term",
                            "calculation_state": (
                                "CALCULATED - NO LIMIT COMPARISON"
                            ),
                            "value": 0.40,
                            "criterion_mm": None,
                            "ratio": None,
                        },
                    },
                }},
            },
            {
                "name": "EL-NONCRITICAL-LIMIT",
                "results": {"elastic": {
                    "converged": True,
                    "crack": {"wk": 0.20},
                    "crack_output": {
                        "long_term": {
                            "duration": "long_term",
                            "calculation_state": "EXCEEDS USER-SPECIFIED LIMIT",
                            "value": 0.20,
                            "criterion_mm": 0.10,
                            "ratio": 2.0,
                        },
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
            "CALCULATED - NO LIMIT COMPARISON",
            0.0,
            "No comparison requested",
        ),
        ("WITHIN USER-SPECIFIED LIMIT", 0.30, "User-specified limit 0.300 mm"),
        ("EXCEEDS USER-SPECIFIED LIMIT", 0.10, "User-specified limit 0.100 mm"),
    ],
)
def test_crack_summary_preserves_exact_bounded_state(
    state, criterion, expected_criterion,
):
    output = {
        "duration": "long_term",
        "calculation_state": state,
        "value": None if state in {"NOT REQUESTED", "NOT ASSESSED"} else 0.25,
        "criterion_mm": criterion,
        "ratio": (
            2.5 if state == "EXCEEDS USER-SPECIFIED LIMIT"
            else 0.833 if state == "WITHIN USER-SPECIFIED LIMIT"
            else None
        ),
        "criterion_source": "User input - Analysis settings" if criterion else None,
        "reason": "Retained assessment reason",
    }
    rows = presentation.result_summary_rows(
        _inp(mode="Elastic"),
        {"elastic": {
            "converged": True,
            "stress_outputs": {},
            "lambda_cr": 1.0,
            "crack_output": {"long_term": output},
        }},
    )
    crack = next(
        row for row in rows if row["check"] == "Crack width - Long-term"
    )

    assert crack["status"] == state
    assert crack["criterion"] == expected_criterion
    assert crack["util"] is None
    assert "Retained assessment reason" in crack["note"]


def test_dual_heightened_crack_summary_is_singleton_and_not_global_utilisation():
    heightened = {
        "fine": {"required_reinforcement_area_mm2": 420.0},
        "coarse": {"required_reinforcement_area_mm2": 300.0},
        "provided_reinforcement_area_mm2": 350.0,
        "governing_comparison_ratio": 1.2,
        "governing_crack_system": "fine",
        "governing_status": "PROVIDED AREA BELOW CALCULATED REQUIREMENT",
        "reference_case_id": "EL-REF",
        "ordinary_crack_branch": "Short-term (fine)",
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
    assert "Fine As,req 420.0 mm2" in rows[0]["result"]
    assert "coarse As,req 300.0 mm2" in rows[0]["result"]
    assert "Reference EL-REF / Short-term (fine)" in rows[0]["note"]
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
        "util_valid": True,
        "util_reason": None,
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
    ("axis", "tension_low", "component", "angle", "face"),
    (
        ("x", True, "z_y", 90.0, "bottom (-y)"),
        ("x", False, "z_y", 270.0, "top (+y)"),
        ("y", True, "z_x", 0.0, "left (-x)"),
        ("y", False, "z_x", 180.0, "right (+x)"),
    ),
)
def test_shear_geometry_basis_reconciles_calculated_links_arm_to_source_state(
    axis, tension_low, component, angle, face
):
    shear = {
        "axis": axis,
        "tension_low": tension_low,
        "d": 550.0,
        "res": {"valid": True, "vrd_c": 100.0},
        "links": {
            "res": {"valid": True, "z": 517.787},
            "z_component": component,
            "z_source_angle_deg": angle,
            "z_source_case": "PL-01",
        },
    }

    basis = presentation.shear_geometry_basis(_inp(), shear)

    assert basis["z_mm"] == pytest.approx(517.787)
    assert f"|{component}| from PL-01" in basis["statement"]
    assert f"{face} {angle:.0f}" in basis["statement"]
    assert "used in V_Rd,s and V_Rd,max" in basis["statement"]
    assert "used in V_Rd,c" in basis["statement"]


def test_shear_geometry_basis_distinguishes_both_no_links_routes():
    base = {
        "axis": "x",
        "tension_low": True,
        "d": 550.0,
        "res": {"valid": True, "vrd_c": 100.0},
    }

    route_2005 = presentation.shear_geometry_basis(_inp(), base)
    route_2023 = presentation.shear_geometry_basis(
        _inp(),
        {**base, "model_2023": True, "res": {**base["res"], "z": 495.0}},
    )

    assert route_2005["z_mm"] is None
    assert "2005 no-links resistance has no z operand" in route_2005["statement"]
    assert route_2023["z_mm"] == pytest.approx(495.0)
    assert "0.9d per DS/EN 1992-1-1:2023 8.2.1(3)" in route_2023["statement"]
    assert "used in V_Rd,c" in route_2023["statement"]


@pytest.mark.parametrize(
    ("updates", "status", "assessed"),
    [
        ({}, "PASS", True),
        ({"util": 1.2}, "FAIL", True),
        ({"check_util": False, "util": None}, "NOT ASSESSED", False),
        ({"closed": False, "util": None}, "NOT ASSESSED", False),
        ({"util_valid": None}, "NOT ASSESSED", False),
        (
            {
                "util": None,
                "util_valid": False,
                "util_reason": "Global moment origin lies outside the closed M-M envelope",
                "util_gov": None,
            },
            "INVALID",
            False,
        ),
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

    origin_invalid = presentation.plastic_action_assessment(_plastic(
        util=None,
        util_valid=False,
        util_reason="Global moment origin lies outside the closed M-M envelope",
        util_gov=None,
    ))
    assert origin_invalid["util"] is None
    assert origin_invalid["margin"] is None
    assert presentation.plastic_assessment_text(origin_invalid) == (
        "INVALID - Plastic bending | The closed M-M capacity envelope does not "
        "contain the zero-moment origin"
    )

    legacy = presentation.plastic_action_assessment(_plastic(util_valid=None))
    assert legacy["util"] is None
    assert legacy["margin"] is None
    assert presentation.plastic_assessment_text(legacy) == (
        "NOT ASSESSED - Plastic bending | The saved result cannot confirm that "
        "the M-M envelope contains the origin; recalculate"
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
    assert [
        message.text for message in presentation.required_action_set_errors(inp)
    ] == [
        "Enter a Plastic action-set ID before calculating",
        "Enter an Elastic action-set ID before calculating",
    ]

    errors = presentation.required_action_set_errors({
        "mode": "Elastic",
        "combined_on": True,
        "plastic_case": {"id": ""},
        "elastic_case": {"id": "EL-01"},
    })
    assert [message.text for message in errors] == [
        "Enter a Plastic action-set ID before calculating"
    ]


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


def test_zero_cracking_factor_remains_calculated_and_governs_named_cases():
    elastic = {
        "converged": True,
        "stress_outputs": {},
        "lambda_cr": 0.0,
        "cracked": True,
        "show_cw": False,
    }
    rows = presentation.result_summary_rows(
        _inp(mode="Elastic"), {"elastic": elastic},
    )
    cracking = next(
        row for row in rows if row["check"] == "Cracking threshold/state"
    )

    assert cracking["status"] == "CALCULATED"
    assert cracking["result"] == "lambda_cr 0.000; cracked"

    selected = presentation.worked_example_selection({}, {
        "elastic_cases": [
            {
                "name": "EL-PRESTRESS-ZERO",
                "results": {"elastic": elastic},
            },
            {
                "name": "EL-ORDINARY",
                "results": {"elastic": {
                    **elastic,
                    "lambda_cr": 0.4,
                }},
            },
        ],
    })
    assert selected["cracking_threshold"] == {
        "case_id": "EL-PRESTRESS-ZERO",
    }


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


def test_combined_summary_names_independent_dkna_inclusion_route():
    combined = {
        "valid": True,
        "method": "DK NA",
        "dkna_valid": True,
        "dkna_sum": 0.90,
        "dkna_limit_satisfied": True,
        "dkna_status": "CONDITIONAL",
        "dkna_ok": None,
        "m_v_independent": True,
    }
    rows = presentation.result_summary_rows(
        _inp(mode="Plastic", combined_on=True),
        {"plastic": _plastic(), "combined": combined},
    )
    row = next(
        item for item in rows
        if item["check"] == "Combined M-V-T - DK NA sum"
    )

    assert row["status"] == "CONDITIONAL"
    assert "DK NA screen: max(N+M+T, N+V+T)" in row["note"]
    assert "design assumption" in row["note"]
    assert "area, distribution and anchorage" in row["note"]
    assert "N+M+V+T" not in row["note"]


@pytest.mark.parametrize(
    (
        "verification_state",
        "mechanically_verified",
        "dkna_sum",
        "legacy_ok",
        "expected_status",
        "copy",
    ),
    [
        (
            "adequate", True, 0.90, True, "CONDITIONAL",
            "within the numerical limit",
        ),
        (
            "inadequate", False, 1.10, False, "FAIL",
            "exceeds the numerical limit even under the favourable",
        ),
        (
            "unanchored", False, 0.90, True, "CONDITIONAL",
            "within the numerical limit",
        ),
        (
            "incomplete / unknown", False, 0.90, True, "CONDITIONAL",
            "within the numerical limit",
        ),
    ],
    ids=["adequate", "inadequate", "unanchored", "incomplete-unknown"],
)
def test_separate_mv_assumption_evidence_never_promotes_a_verdict(
    verification_state,
    mechanically_verified,
    dkna_sum,
    legacy_ok,
    expected_status,
    copy,
):
    result = {
        "valid": True,
        "dkna_valid": True,
        "dkna_sum": dkna_sum,
        "dkna_ok": legacy_ok,
        "m_v_independent": True,
        "m_v_separation_condition": {
            "verification_state": verification_state,
            "mechanically_verified": mechanically_verified,
        },
    }

    assert presentation.combined_dkna_status(result) == expected_status
    note = presentation.combined_dkna_assumption_note(result)
    assert copy in note
    if expected_status == "FAIL":
        assert "failed numerical check governs regardless" in note
    else:
        assert "Verify the reinforcement area, distribution and anchorage" in note


@pytest.mark.parametrize("dkna_sum", [None, float("nan"), float("inf")])
def test_separate_mv_missing_numerical_comparison_is_not_assessed(dkna_sum):
    result = {
        "valid": True,
        "dkna_valid": True,
        "dkna_sum": dkna_sum,
        "dkna_limit_satisfied": True,
        "dkna_status": "CONDITIONAL",
        "m_v_independent": True,
    }

    assert presentation.combined_dkna_limit_satisfied(result) is None
    assert presentation.combined_dkna_status(result) == "NOT ASSESSED"
    note = presentation.combined_dkna_assumption_note(result)
    assert note.startswith("NOT ASSESSED:")
    assert "recalculate" in note


@pytest.mark.parametrize(
    (
        "verification_state",
        "longitudinal_util",
        "dkna_sum",
        "expected_dkna",
        "expected_physical",
        "overall",
    ),
    [
        ("adequate", 0.75, 0.90, "CONDITIONAL", "PASS", "CONDITIONAL"),
        ("inadequate", 1.15, 0.90, "CONDITIONAL", "FAIL", "FAIL"),
        ("unanchored", 0.75, 0.90, "CONDITIONAL", "PASS", "CONDITIONAL"),
        (
            "incomplete / unknown", None, 0.90, "CONDITIONAL",
            "NOT ASSESSED", "NOT ASSESSED",
        ),
        ("adequate", 0.75, 1.10, "FAIL", "PASS", "FAIL"),
    ],
    ids=[
        "adequate",
        "inadequate",
        "unanchored",
        "incomplete-unknown",
        "numerical-failure",
    ],
)
def test_separate_mv_assumption_preserves_conservative_overall_state(
    verification_state,
    longitudinal_util,
    dkna_sum,
    expected_dkna,
    expected_physical,
    overall,
):
    longitudinal = (
        None
        if longitudinal_util is None
        else {
            "valid": True,
            "util": longitudinal_util,
            "axis": "x",
            "biaxial": False,
            "tension_low": True,
        }
    )
    combined = {
        "valid": True,
        "method": "DK NA",
        "dkna_valid": True,
        "dkna_sum": dkna_sum,
        "dkna_limit_satisfied": dkna_sum <= 1.0,
        "dkna_ok": False if dkna_sum > 1.0 else True,
        "m_v_independent": True,
        "m_v_separation_condition": {
            "verification_state": verification_state,
            "mechanically_verified": verification_state == "adequate",
        },
        "transverse": {
            "valid": True,
            "cot": 1.5,
            "u_crush": 0.60,
            "u_stirrup": 0.70,
            "shear_fraction": 0.30,
            "torsion_fraction": 0.40,
        },
        "longitudinal": longitudinal,
        "governing_longitudinal": longitudinal,
        "longitudinal_all_conditional": longitudinal is not None,
    }
    rows = presentation.result_summary_rows(
        _inp(mode="Plastic", combined_on=True),
        {"plastic": _plastic(), "combined": combined},
    )
    by_check = {row["check"]: row for row in rows}

    assert by_check["Combined M-V-T - DK NA sum"]["status"] == expected_dkna
    assert by_check["Combined longitudinal reinforcement"]["status"] == (
        expected_physical
    )
    assert presentation.overall_summary_status(rows) == overall


@pytest.mark.parametrize(
    ("dkna_sum", "legacy_ok", "expected"),
    [(0.90, True, "PASS"), (1.10, False, "FAIL")],
)
def test_simultaneous_dkna_route_retains_ordinary_verdict(
    dkna_sum,
    legacy_ok,
    expected,
):
    result = {
        "valid": True,
        "dkna_valid": True,
        "dkna_sum": dkna_sum,
        "dkna_ok": legacy_ok,
        "m_v_independent": False,
    }

    assert presentation.combined_dkna_status(result) == expected


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
    assert "pure-axis substitute" in (
        by_check["Combined longitudinal reinforcement"]["note"].lower()
    )


def test_combined_summary_marks_missing_prerequisites_not_assessed():
    combined = {
        "valid": False,
        "have_m": True,
        "have_v": False,
        "have_t": False,
        "method": "DK NA",
        "m_v_independent": True,
    }
    rows = presentation.result_summary_rows(
        _inp(mode="Plastic", combined_on=True),
        {"plastic": _plastic(), "combined": combined},
    )
    by_check = {row["check"]: row for row in rows}

    assert by_check["Combined M-V-T - DK NA sum"]["status"] == "NOT ASSESSED"
    assert by_check["Combined M-V-T - DK NA sum"]["note"] == (
        "DK NA screen: max(N+M+T, N+V+T); Missing prerequisite: V, T"
    )
    assert presentation.combined_dkna_screen_label(combined) == (
        "max(N+M+T, N+V+T)"
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
    assert "pure-axis substitute" in longitudinal["note"]
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


@pytest.mark.parametrize(
    ("transverse_util", "interaction_util", "expected_status", "expected_util"),
    (
        (0.50, 0.50, "PASS", 0.50),
        (True, 0.50, "NOT ASSESSED", None),
        (0.40, 0.50, "NOT ASSESSED", None),
        (0.50, True, "NOT ASSESSED", None),
    ),
)
def test_combined_physical_components_reconciles_formula_629_evidence(
    transverse_util,
    interaction_util,
    expected_status,
    expected_util,
):
    components = presentation.combined_physical_components({
        "transverse": {
            "valid": True,
            "cot": 1.5,
            "u_crush": transverse_util,
            "u_stirrup": 0.60,
            "shear_fraction": 0.20,
            "torsion_fraction": 0.40,
        },
        "crushing": {
            "valid": True,
            "value": interaction_util,
        },
    })

    concrete = next(item for item in components if item["key"] == "concrete")
    assert concrete["status"] == expected_status
    assert concrete["util"] == expected_util
    if expected_status == "NOT ASSESSED":
        assert "recalculate" in concrete["note"]


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


def test_sparse_links_keep_capacity_pass_and_publish_detailing_failure_separately():
    shear = {
        "v_ed": 80.0,
        "res": {"valid": True, "vrd_c": 103.417},
        "util": 80.0 / 103.417,
        "method": "DK NA",
        "links": {
            "res": {
                "valid": True,
                "vrd": 29.452,
                "governs": "stirrups (VRd,s)",
            },
            "util": 80.0 / 29.452,
            "longitudinal_assessment": {
                "status": "NOT APPLICABLE",
                "util": None,
                "reason": "no_longitudinal_chord_action",
            },
        },
    }
    results = {
        "plastic": _plastic(),
        "shear": shear,
        "transverse_reinforcement": {
            "status": "FAIL",
            "reason": "minimum shear reinforcement is required for this beam",
            "checks": [],
        },
    }
    rows = presentation.result_summary_rows(
        _inp(
            mode="Plastic",
            shear_on=True,
            shear_links=True,
            transverse_detailing_on=True,
        ),
        results,
    )
    by_check = {row["check"]: row for row in rows}

    concrete = by_check["Shear without links"]
    provided_links = by_check["Shear with links"]
    detailing = by_check["Shear/torsion link detailing"]
    assert concrete["status"] == "PASS"
    assert concrete["util"] == pytest.approx(80.0 / 103.417)
    assert provided_links["status"] == "NOT APPLICABLE"
    assert provided_links["util"] is None
    assert "271.6 % (non-governing)" == provided_links["result"]
    assert "context only" in provided_links["note"]
    assert detailing["status"] == "FAIL"
    assert "minimum shear reinforcement" in detailing["note"].lower()
    assert presentation.overall_summary_status(rows) == "FAIL"


def test_unavailable_calculated_link_arm_is_not_assessed_without_a_verdict():
    shear = {
        "res": {"valid": True, "vrd_c": 100.0},
        "util": 1.20,
        "method": "DK NA",
        "links": {
            "res": {
                "valid": False,
                "calculation_state": "NOT ASSESSED",
                "reason": "exact calculated plastic lever arm z is unavailable",
            },
            "util": None,
            "assessment_reason": (
                "calculated plastic lever arm unavailable: the exact face-aligned "
                "Plastic solve did not converge"
            ),
        },
    }

    rows = presentation.result_summary_rows(
        _inp(mode="Plastic", shear_on=True, shear_links=True),
        {"plastic": _plastic(), "shear": shear},
    )
    link_row = next(row for row in rows if row["check"] == "Shear with links")

    assert link_row["status"] == "NOT ASSESSED"
    assert link_row["result"] == "-"
    assert link_row["util"] is None
    assert "did not converge" in link_row["note"]
    assert presentation.overall_summary_status(rows) == "NOT ASSESSED"


def test_2023_axial_compression_guidance_governs_the_links_overview_note():
    reason = (
        "2023 axial-compression applicability conditions were not demonstrated"
    )
    shear = {
        "res": {"valid": True, "vrd_c": 100.0},
        "util": 0.50,
        "method": "DS/EN 1992-1-1:2023",
        "links": {
            "res": {
                "valid": False,
                "calculation_state": "NOT ASSESSED",
                "reason": reason,
            },
            "util": None,
            "assessment_reason": reason,
            "longitudinal_assessment": {
                "status": "NOT ASSESSED",
                "ok": None,
                "util": None,
                "reason": "required_longitudinal_chord_coverage_incomplete",
            },
        },
    }

    rows = presentation.result_summary_rows(
        _inp(mode="Plastic", shear_on=True, shear_links=True),
        {"plastic": _plastic(), "shear": shear},
    )
    link_row = next(row for row in rows if row["check"] == "Shear with links")

    assert link_row["status"] == "NOT ASSESSED"
    assert link_row["result"] == "-"
    assert "Net axial compression is present" in link_row["note"]
    assert "Annex G" in link_row["note"]
    assert "Complete both required longitudinal chord checks" not in link_row["note"]


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


def test_torsion_without_full_resistance_is_not_assessed_on_every_summary():
    torsion = {
        "tube_valid": True,
        "closed_links_present": False,
        "full_resistance_assessed": False,
        "assessment_reason": "closed_links_not_present",
        "valid": False,
        "trd": None,
        "trd_max": 88.0,
        "trd_c": 12.0,
        "util": None,
        "governs": None,
    }
    rows = presentation.result_summary_rows(
        _inp(
            mode="Plastic",
            torsion_on=True,
            combined_on=True,
            shear_links=False,
        ),
        {"plastic": _plastic(), "torsion": torsion},
    )
    by_check = {row["check"]: row for row in rows}

    torsion_row = by_check["Torsion"]
    assert torsion_row["status"] == "NOT ASSESSED"
    assert torsion_row["result"] == "-"
    assert torsion_row["criterion"] == "-"
    assert torsion_row["util"] is None
    assert torsion_row["note"] == (
        "Closed torsion links are required before the transverse/strut "
        "resistance component can be assessed"
    )

    combined_row = by_check["Combined M-V-T"]
    assert combined_row["status"] == "NOT ASSESSED"
    assert combined_row["util"] is None
    assert combined_row["note"] == (
        "Closed torsion links are required before the transverse/strut "
        "resistance component can be assessed"
    )


def _torsion_longitudinal_result(*, status="NOT ASSESSED", ratio=0.47):
    reason = (
        "longitudinal_torsion_reinforcement_insufficient"
        if status == "FAIL"
        else "longitudinal_torsion_reinforcement_not_verified"
    )
    return {
        "tube_valid": True,
        "closed_links_present": True,
        "transverse_resistance_assessed": True,
        "full_resistance_assessed": True,
        "valid": True,
        "t_ed": 40.0,
        "trd": 76.402,
        "util": 0.523548,
        "governs": "stirrups (TRd,s)",
        "resistance_status": "PASS",
        "assessment_status": status,
        "overall_reason": reason,
        "longitudinal_assessment": {
            "status": status,
            "reason": reason,
            "required_asl_mm2": 1176.672,
            "provided_gross_area_mm2": 1000.0 if status == "FAIL" else 2513.274,
            "provided_equivalent_area_mm2": (
                1000.0 if status == "FAIL" else 2513.274
            ),
            "demand_ratio": ratio,
        },
    }


@pytest.mark.parametrize(
    ("status", "ratio"),
    [("NOT ASSESSED", 0.468), ("FAIL", 1.176672)],
)
def test_torsion_summary_separates_component_and_longitudinal_status(
    status,
    ratio,
):
    torsion = _torsion_longitudinal_result(status=status, ratio=ratio)
    rows = presentation.result_summary_rows(
        _inp(mode="Plastic", torsion_on=True, shear_links=True),
        {"plastic": _plastic(), "torsion": torsion},
    )
    by_check = {row["check"]: row for row in rows}

    assert by_check["Torsion"]["status"] == status
    assert by_check["Torsion"]["util"] is None
    assert (
        by_check["Torsion transverse/strut resistance"]["status"]
        == "PASS"
    )
    assert by_check["Torsion transverse/strut resistance"]["util"] == (
        pytest.approx(0.523548)
    )
    longitudinal = by_check["Torsion longitudinal reinforcement"]
    assert longitudinal["status"] == status
    assert longitudinal["util"] == pytest.approx(ratio)
    assert "1177 /" in longitudinal["result"]
    assert presentation.overall_summary_status(rows) == status


@pytest.mark.parametrize("status", ["NOT ASSESSED", "FAIL"])
def test_combined_summary_cannot_promote_torsion_longitudinal_state(status):
    torsion = _torsion_longitudinal_result(status=status)
    combined = {
        "valid": True,
        "method": "DK NA",
        "dkna_valid": True,
        "dkna_sum": 0.80,
        "dkna_limit_satisfied": True,
        "dkna_status": "PASS",
        "dkna_ok": True,
        "m_v_independent": False,
        "torsion_assessment_status": status,
        "torsion_assessment_reason": torsion["overall_reason"],
        "torsion_longitudinal_assessment": torsion[
            "longitudinal_assessment"
        ],
    }
    rows = presentation.result_summary_rows(
        _inp(
            mode="Plastic",
            torsion_on=True,
            combined_on=True,
            shear_links=True,
        ),
        {"plastic": _plastic(), "torsion": torsion, "combined": combined},
    )
    by_check = {row["check"]: row for row in rows}

    combined_row = by_check["Combined M-V-T - DK NA sum"]
    assert combined_row["status"] == status
    assert "numerical component evidence" in combined_row["note"]
    assert presentation.combined_dkna_status(combined) == status


def test_definite_dkna_failure_outranks_unverified_torsion_note():
    combined = {
        "valid": True,
        "method": "DK NA",
        "dkna_valid": True,
        "dkna_sum": 1.10,
        "dkna_limit_satisfied": False,
        "dkna_status": "FAIL",
        "dkna_ok": False,
        "m_v_independent": True,
        "torsion_assessment_status": "NOT ASSESSED",
        "torsion_assessment_reason": (
            "longitudinal_torsion_reinforcement_not_verified"
        ),
    }

    assert presentation.combined_dkna_status(combined) == "FAIL"
    note = presentation.combined_torsion_governing_note(combined)
    assert "definite combined failure governs" in note
    assert "not an overall M-V-T verdict" not in note


def test_combined_longitudinal_component_publishes_governing_ratio():
    combined = {
        "longitudinal": {
            "valid": True,
            "util": 1.25,
            "axis": "x",
            "tension_low": True,
        },
        "governing_longitudinal": {
            "valid": True,
            "util": 1.25,
            "axis": "x",
            "tension_low": True,
        },
        "longitudinal_all_conditional": True,
        "torsion_longitudinal_assessment": {
            "status": "NOT ASSESSED",
            "reason": "longitudinal_torsion_reinforcement_not_verified",
            "demand_ratio": 0.50,
        },
    }

    component = next(
        item
        for item in presentation.combined_physical_components(combined)
        if item["key"] == "longitudinal"
    )

    assert component["status"] == "FAIL"
    assert component["util"] == pytest.approx(1.25)


def test_stale_combined_cannot_bypass_unassessed_torsion_prerequisite():
    torsion = {
        "tube_valid": True,
        "closed_links_present": False,
        "full_resistance_assessed": True,
        "assessment_reason": "closed_links_not_present",
        "valid": True,
        "util": 0.10,
    }
    results = {
        "plastic": _plastic(),
        "torsion": torsion,
        "combined": {
            "valid": True,
            "dkna_sum": 0.10,
            "dkna_ok": True,
        },
    }

    blocker = presentation.combined_bending_assessment_blocker(results)
    assert blocker == (
        "Torsion prerequisite is not assessed: Closed torsion links are required "
        "before the transverse/strut resistance component can be assessed"
    )

    rows = presentation.result_summary_rows(
        _inp(
            mode="Plastic",
            torsion_on=True,
            combined_on=True,
            shear_links=False,
        ),
        results,
    )
    combined_rows = [row for row in rows if row["view"] == "M-V-T Combined"]
    assert combined_rows
    assert all(row["status"] == "NOT ASSESSED" for row in combined_rows)
    assert all(row["util"] is None for row in combined_rows)
    assert (
        presentation.worked_example_selection({}, results)["families"].get(
            "combined"
        )
        is None
    )


def test_torsion_geometry_failure_remains_distinct_from_missing_links():
    rows = presentation.result_summary_rows(
        _inp(mode="Plastic", torsion_on=True, shear_links=True),
        {
            "plastic": _plastic(),
            "torsion": {
                "tube_valid": False,
                "closed_links_present": True,
                "full_resistance_assessed": True,
                "valid": False,
                "util": None,
                "reason": "compound outline requires subdivision",
            },
        },
    )
    torsion_row = next(row for row in rows if row["check"] == "Torsion")

    assert torsion_row["status"] == "INVALID"
    assert torsion_row["note"] == (
        "The compound outline requires subdivision before torsion can be assessed"
    )


def test_torsion_wall_evidence_failure_is_not_assessed_without_stale_value():
    raw_reason = "torsion wall reinforcement mapping is incomplete"
    rows = presentation.result_summary_rows(
        _inp(mode="Plastic", torsion_on=True, shear_links=True),
        {
            "plastic": _plastic(),
            "torsion": {
                "tube_valid": False,
                "closed_links_present": True,
                "transverse_resistance_assessed": False,
                "full_resistance_assessed": False,
                "valid": False,
                "util": 0.42,
                "trd": 999.123,
                "reason": raw_reason,
            },
        },
    )
    torsion_row = next(row for row in rows if row["check"] == "Torsion")

    assert torsion_row["status"] == "NOT ASSESSED"
    assert torsion_row["result"] == "-"
    assert torsion_row["criterion"] == "-"
    assert torsion_row["util"] is None
    assert torsion_row["note"] == (
        "Torsion is not assessed because longitudinal reinforcement has not "
        "been established for every equivalent-tube wall"
    )
    assert raw_reason not in torsion_row["note"]


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
                "dkna_limit_satisfied": False,
                "dkna_status": "CONDITIONAL",
                "m_v_independent": True,
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


def test_base_en_combined_summary_publishes_only_supported_physical_checks():
    def direction(concrete, stirrup, longitudinal):
        return {
            "valid": True,
            "method": codes.EC2_2005.label,
            "transverse": {
                "valid": True,
                "u_crush": concrete,
                "u_stirrup": stirrup,
                "cot": 1.5,
                "shear_fraction": 0.2,
                "torsion_fraction": stirrup - 0.2,
            },
            "longitudinal": {
                "valid": True,
                "util": longitudinal,
                "axis": "x",
                "tension_low": True,
            },
            "governing_longitudinal": {
                "valid": True,
                "util": longitudinal,
                "axis": "x",
                "tension_low": True,
            },
            "longitudinal_all_conditional": True,
            "longitudinal_assessment": {
                "status": "PASS" if longitudinal <= 1.0 else "FAIL",
                "util": longitudinal,
                "coverage_complete": True,
            },
        }

    combined = {
        "biaxial": True,
        "method": codes.EC2_2005.label,
        "directions": {
            "vx": direction(0.50, 0.60, 0.70),
            "vy": direction(0.80, 0.90, 1.10),
        },
    }
    rows = presentation.result_summary_rows(
        _inp(
            mode="Plastic",
            combined_on=True,
            combined_method=codes.EC2_2005.label,
        ),
        {"plastic": _plastic(), "combined": combined},
    )

    combined_rows = [row for row in rows if row["view"] == "M-V-T Combined"]
    checks = {row["check"] for row in combined_rows}
    assert "Combined Vx+T concrete compression strut" in checks
    assert "Combined Vy+T closed stirrup" in checks
    assert "Combined Vy+T longitudinal reinforcement" in checks
    assert "Generic Vx-Vy-T interaction" in checks
    assert all("DK NA" not in row["check"] for row in combined_rows)
    assert all("dkna" not in row["overview_key"] for row in combined_rows)
    assert next(
        row for row in combined_rows
        if row["check"] == "Combined Vy+T longitudinal reinforcement"
    )["status"] == "FAIL"


def test_base_en_incomplete_case_cannot_displace_governing_worked_case():
    def combined_result(util, longitudinal_status):
        longitudinal = {
            "valid": True,
            "util": util - 0.05,
            "axis": "x",
            "tension_low": True,
        }
        return {
            "valid": True,
            "method": codes.EC2_2005.label,
            "transverse": {
                "valid": True,
                "u_crush": util,
                "u_stirrup": util - 0.10,
                "cot": 1.5,
                "shear_fraction": util - 0.30,
                "torsion_fraction": 0.20,
            },
            "longitudinal": longitudinal,
            "governing_longitudinal": longitudinal,
            "longitudinal_all_conditional": True,
            "longitudinal_assessment": {
                "status": longitudinal_status,
                "util": util - 0.05,
                "coverage_complete": longitudinal_status in {"PASS", "FAIL"},
            },
        }

    mixed_biaxial = {
        "method": codes.EC2_2005.label,
        "biaxial": True,
        "directions": {
            "vx": combined_result(0.95, "PASS"),
            "vy": combined_result(0.90, "NOT ASSESSED"),
        },
    }
    out = {
        "plastic_cases": [
            {
                "name": "PL-GOV",
                "results": {
                    "plastic": _plastic(),
                    "combined": combined_result(0.85, "PASS"),
                },
            },
            {
                "name": "PL-INCOMPLETE",
                "results": {
                    "plastic": _plastic(),
                    "combined": combined_result(0.95, "NOT ASSESSED"),
                },
            },
            {
                "name": "PL-BIAXIAL-INCOMPLETE",
                "results": {
                    "plastic": _plastic(),
                    "combined": mixed_biaxial,
                },
            },
        ]
    }

    assert presentation._transverse_metric("combined", mixed_biaxial) is None
    assert presentation.worked_example_selection({}, out)["families"][
        "combined"
    ] == {"case_id": "PL-GOV", "component": None}


@pytest.mark.parametrize(
    "directions",
    (
        {},
        {"vx": {}},
        {"vx": {}, "vy": None},
        {"vx": {}, "vy": "unavailable"},
        "unavailable",
    ),
)
def test_base_en_biaxial_direction_evidence_fails_closed(directions):
    combined = {
        "method": codes.EC2_2005.label,
        "biaxial": True,
        "directions": directions,
    }

    assert presentation.base_en_combined_direction_items(combined) is None
    assert presentation._transverse_metric("combined", combined) is None
    assert presentation._transverse_direction("combined", combined) is None

    rows = presentation.result_summary_rows(
        _inp(
            mode="Plastic",
            combined_on=True,
            combined_method=codes.EC2_2005.label,
        ),
        {"plastic": _plastic(), "combined": combined},
    )
    combined_rows = [row for row in rows if row["view"] == "M-V-T Combined"]
    assert len(combined_rows) == 1
    assert combined_rows[0]["status"] == "NOT ASSESSED"
    assert combined_rows[0]["util"] is None
    assert "both directional combined calculations" in (
        combined_rows[0]["note"].casefold()
    )


def test_base_en_empty_second_direction_cannot_publish_surviving_direction():
    chord = {
        "valid": True,
        "util": 0.70,
        "axis": "x",
        "tension_low": True,
    }
    vx = {
        "valid": True,
        "method": codes.EC2_2005.label,
        "transverse": {
            "valid": True,
            "u_crush": 0.50,
            "u_stirrup": 0.60,
            "cot": 1.5,
            "shear_fraction": 0.30,
            "torsion_fraction": 0.30,
        },
        "longitudinal": chord,
        "governing_longitudinal": chord,
        "longitudinal_all_conditional": True,
        "longitudinal_assessment": {
            "status": "PASS",
            "util": 0.70,
            "coverage_complete": True,
        },
    }
    combined = {
        "method": codes.EC2_2005.label,
        "biaxial": True,
        "directions": {"vx": vx, "vy": {}},
    }

    assert presentation.base_en_combined_direction_items(combined) is None
    assert presentation._transverse_metric("combined", combined) is None
    assert presentation._transverse_direction("combined", combined) is None

    rows = presentation.result_summary_rows(
        _inp(
            mode="Plastic",
            combined_on=True,
            combined_method=codes.EC2_2005.label,
        ),
        {"plastic": _plastic(), "combined": combined},
    )
    combined_rows = [row for row in rows if row["view"] == "M-V-T Combined"]
    assert len(combined_rows) == 1
    assert combined_rows[0]["status"] == "NOT ASSESSED"
    assert combined_rows[0]["result"] == "-"


@pytest.mark.parametrize(
    ("retained", "transverse_retained", "generic_interaction_status"),
    (
        (True, True, "NOT ASSESSED"),
        (np.bool_(True), np.bool_(True), "NOT ASSESSED"),
        ("0.5", "0.5", "NOT ASSESSED"),
        (-0.25, -0.25, "NOT ASSESSED"),
        (math.inf, True, "FAIL"),
    ),
)
def test_base_en_invalid_utilisations_are_not_publication_numbers(
    retained,
    transverse_retained,
    generic_interaction_status,
):
    chord = {
        "valid": True,
        "util": retained,
        "axis": "x",
        "tension_low": True,
    }
    combined = {
        "valid": True,
        "method": codes.EC2_2005.label,
        "transverse": {
            "valid": True,
            "u_crush": transverse_retained,
            "u_stirrup": transverse_retained,
            "cot": 1.5,
            "shear_fraction": transverse_retained,
            "torsion_fraction": transverse_retained,
        },
        "longitudinal": chord,
        "governing_longitudinal": chord,
        "longitudinal_all_conditional": True,
        "longitudinal_assessment": {
            "status": "PASS",
            "util": retained,
            "coverage_complete": True,
        },
        "torsion_longitudinal_assessment": {
            "status": "FAIL",
            "demand_ratio": retained,
            "reason": "longitudinal_torsion_reinforcement_not_verified",
        },
    }

    components = presentation.combined_physical_components(combined)
    assert {item["status"] for item in components} == {"NOT ASSESSED"}
    assert all(item["util"] is None for item in components)
    longitudinal = next(
        item for item in components if item["key"] == "longitudinal"
    )
    assert longitudinal["chord_status"] == "NOT ASSESSED"
    assert longitudinal["chord_util"] is None
    assert presentation._transverse_metric("combined", combined) is None
    assert presentation.interaction_assessment_status(
        {"valid": True, "value": retained}
    ) == generic_interaction_status
    assert presentation.viz.util_ok(retained) is False

    rows = presentation.result_summary_rows(
        _inp(
            mode="Plastic",
            combined_on=True,
            combined_method=codes.EC2_2005.label,
        ),
        {"plastic": _plastic(), "combined": combined},
    )
    combined_rows = [row for row in rows if row["view"] == "M-V-T Combined"]
    assert len(combined_rows) == 3
    assert {row["status"] for row in combined_rows} == {"NOT ASSESSED"}
    assert all(row["result"] == "-" and row["util"] is None for row in combined_rows)


def test_biaxial_unavailable_combined_keeps_aggregate_separate_route_identity():
    unavailable = {
        "valid": True,
        "dkna_valid": False,
        "dkna_sum": None,
        "dkna_reason": "Action-alone resistance unavailable",
        "m_v_independent": True,
    }
    combined = {
        "biaxial": True,
        "m_v_independent": True,
        "m_v_separation_condition": {
            "declared": True,
            "mechanically_verified": False,
        },
        "directions": {
            "vx": dict(unavailable),
            "vy": dict(unavailable),
        },
    }

    rows = presentation.result_summary_rows(
        _inp(mode="Plastic", combined_on=True),
        {"plastic": _plastic(), "combined": combined},
    )
    directional = [
        row for row in rows
        if row["check"] in {
            "Combined Vx+T - DK NA sum",
            "Combined Vy+T - DK NA sum",
        }
    ]

    assert presentation.combined_dkna_screen_label(combined) == (
        "max(N+M+T, N+V+T)"
    )
    assert len(directional) == 2
    assert all(row["status"] == "NOT ASSESSED" for row in directional)
    assert all(
        "max(N+M+T, N+V+T)" in row["note"]
        for row in directional
    )
    assert presentation.overall_summary_status(rows) == "NOT ASSESSED"


def test_legacy_plastic_invalidates_retained_combined_summary_and_selection():
    plastic = _plastic()
    plastic.pop("util_valid")
    combined = {
        "valid": True,
        "r_m": 0.6,
        "r_v": 0.2,
        "r_t": 0.1,
        "dkna_sum": 0.9,
        "dkna_ok": True,
        "method": "DK NA",
    }
    results = {"plastic": plastic, "combined": combined}

    rows = presentation.result_summary_rows(
        _inp(mode="Plastic", combined_on=True),
        results,
    )
    combined_rows = [row for row in rows if row["check"].startswith("Combined")]

    assert len(combined_rows) == 1
    assert combined_rows[0]["status"] == "NOT ASSESSED"
    assert combined_rows[0]["result"] == "-"
    assert combined_rows[0]["util"] is None
    assert "m-m envelope contains the origin" in combined_rows[0]["note"].casefold()
    assert "recalculate" in combined_rows[0]["note"].casefold()
    assert "recalculate" in combined_rows[0]["note"].casefold()
    selection = presentation.worked_example_selection({}, results)
    assert "combined" not in selection["families"]

    current_combined = dict(combined, dkna_sum=0.7)
    named = {
        "plastic_cases": [
            {
                "name": "PL-LEGACY",
                "results": {"plastic": plastic, "combined": combined},
            },
            {
                "name": "PL-CURRENT",
                "results": {
                    "plastic": _plastic(util=0.5),
                    "combined": current_combined,
                },
            },
        ]
    }
    named_selection = presentation.worked_example_selection({}, named)
    assert named_selection["families"]["combined"] == {
        "case_id": "PL-CURRENT",
        "component": None,
    }


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


def _overview_row(
    status,
    *,
    check="Plastic bending",
    family="plastic",
    case="PL-1",
    util=None,
    source="Case register",
    view="Plastic Results",
    note="Retained note",
    overview_key=None,
    overview_parent=None,
    overview_placeholder=False,
):
    row = {
        "check": check,
        "family": family,
        "case": case,
        "case_type": "ULS",
        "source": source,
        "status": status,
        "result": "-" if util is None else f"{util}",
        "criterion": "<= 100 %",
        "util": util,
        "view": view,
        "note": note,
    }
    if overview_key is not None:
        row["overview_key"] = overview_key
    if overview_parent is not None:
        row["overview_parent"] = overview_parent
    if overview_placeholder:
        row["overview_placeholder"] = True
    return row


def test_governing_overview_freezes_complete_status_precedence():
    statuses = presentation.GOVERNING_OVERVIEW_STATUS_PRECEDENCE
    assert statuses == (
        "INVALID",
        "FAIL",
        "EXCEEDS USER-SPECIFIED LIMIT",
        "PROVIDED AREA BELOW CALCULATED REQUIREMENT",
        "STALE",
        "REVIEW",
        "NOT ASSESSED",
        "CONDITIONAL",
        "CALCULATED - NO LIMIT COMPARISON",
        "PASS",
        "WITHIN USER-SPECIFIED LIMIT",
        "PROVIDED AREA AT LEAST CALCULATED REQUIREMENT",
        "CALCULATED",
        "NOT RUN",
        "NOT CALCULATED",
        "NOT APPLICABLE",
        "NOT REQUESTED",
    )
    for more_governing, less_governing in zip(statuses, statuses[1:]):
        for ordered in (
            (less_governing, more_governing),
            (more_governing, less_governing),
        ):
            selected = presentation.governing_summary_rows([
                _overview_row(status, case=f"case-{index}")
                for index, status in enumerate(ordered)
            ])
            assert len(selected) == 1
            assert selected[0]["status"] == more_governing


def test_governing_overview_numeric_selection_and_ties_are_deterministic():
    rows = [
        _overview_row("FAIL", case="missing", util=None),
        _overview_row("FAIL", case="string", util="9.0"),
        _overview_row("FAIL", case="boolean", util=True),
        _overview_row("FAIL", case="negative", util=-1.0),
        _overview_row("FAIL", case="nan", util=math.nan),
        _overview_row("FAIL", case="finite", util=1.2),
        _overview_row("FAIL", case="infinite-first", util=math.inf),
        _overview_row("FAIL", case="infinite-second", util=math.inf),
    ]
    before = [dict(row) for row in rows]

    selected = presentation.governing_summary_rows(rows)

    assert selected[0]["case"] == "infinite-first"
    assert rows == before
    selected[0]["case"] = "changed copy"
    assert rows[-2]["case"] == "infinite-first"


def test_governing_overview_all_malformed_utilisation_keeps_first_row():
    rows = [
        _overview_row("FAIL", case="first-missing", util=None),
        _overview_row("FAIL", case="later-string", util="9.0"),
        _overview_row("FAIL", case="later-boolean", util=True),
        _overview_row("FAIL", case="later-negative", util=-1.0),
        _overview_row("FAIL", case="later-negative-infinity", util=-math.inf),
        _overview_row("FAIL", case="later-nan", util=math.nan),
    ]

    assert presentation.governing_summary_rows(rows)[0]["case"] == "first-missing"


@pytest.mark.parametrize(
    "rows",
    [
        [
            _overview_row("FAIL", case="eligible", util=1.2),
            _overview_row("FAIL", case="later-malformed", util="9.0"),
        ],
        [
            _overview_row("FAIL", case="first-malformed", util="9.0"),
            _overview_row("FAIL", case="eligible", util=1.2),
        ],
        [
            _overview_row("FAIL", case="eligible", util=0.0),
            _overview_row("FAIL", case="later-malformed", util=None),
        ],
        [
            _overview_row("FAIL", case="first-malformed", util=None),
            _overview_row("FAIL", case="eligible", util=0.0),
        ],
    ],
)
def test_governing_overview_eligible_utilisation_beats_malformed_in_both_orders(rows):
    assert presentation.governing_summary_rows(rows)[0]["case"] == "eligible"


def test_governing_overview_preserves_family_order_and_selected_provenance():
    rows = [
        _overview_row("PASS", case="PL-A", util=0.60, source="Source A"),
        _overview_row(
            "CALCULATED",
            family="elastic",
            check="Concrete stress",
            case="EL-A",
            source="Elastic source",
            view="Elastic Results",
        ),
        _overview_row(
            "FAIL",
            case="PL-B",
            util=1.20,
            source="Source B",
            note="Governing retained case",
        ),
        _overview_row(
            "PASS",
            check="Shear Vx with links",
            case="PL-C",
            util=0.80,
        ),
        _overview_row(
            "FAIL",
            check="Shear Vy with links",
            case="PL-D",
            util=1.10,
        ),
        _overview_row(
            "FAIL",
            family="independent-family",
            case="PL-E",
            util=1.30,
        ),
    ]

    selected = presentation.governing_summary_rows(rows)

    assert [row["check"] for row in selected] == [
        "Plastic bending",
        "Concrete stress",
        "Shear Vx with links",
        "Shear Vy with links",
        "Plastic bending",
    ]
    assert selected[0]["case"] == "PL-B"
    assert selected[0]["source"] == "Source B"
    assert selected[0]["view"] == "Plastic Results"
    assert selected[0]["note"] == "Governing retained case"
    assert selected[2]["case"] == "PL-C"
    assert selected[3]["case"] == "PL-D"
    assert selected[4]["case"] == "PL-E"


def test_non_governing_overview_rows_preserve_exact_complement_order_and_copies():
    rows = [
        _overview_row("PASS", case="PL-A", util=0.80),
        _overview_row("FAIL", case="PL-B", util=1.25),
        _overview_row(
            "CALCULATED", case="EL-A", check="Concrete stress", util=None
        ),
        _overview_row(
            "CALCULATED", case="EL-B", check="Concrete stress", util=None
        ),
    ]
    before = [dict(row) for row in rows]

    non_governing = presentation.non_governing_summary_rows(rows)

    assert [row["case"] for row in non_governing] == ["PL-A", "EL-B"]
    assert rows == before
    non_governing[0]["case"] = "changed copy"
    assert rows[0]["case"] == "PL-A"
    with pytest.raises(ValueError, match="rows must be objects"):
        presentation.non_governing_summary_rows([rows[0], None])


def test_governing_overview_keeps_unknown_status_visible_and_rejects_bad_rows():
    rows = [
        _overview_row("PASS", case="known", util=0.5),
        _overview_row("FUTURE STATUS", case="future"),
    ]

    assert presentation.governing_summary_rows(rows)[0]["case"] == "future"
    with pytest.raises(ValueError, match="rows must be objects"):
        presentation.governing_summary_rows([rows[0], None])


def test_governing_overview_groups_directions_by_semantic_check_type():
    rows = [
        _overview_row(
            "PASS", check="Shear Vx with links", case="PL-X", util=0.82,
            overview_key="shear:with_links",
        ),
        _overview_row(
            "FAIL", check="Shear Vy with links", case="PL-Y", util=1.08,
            overview_key="shear:with_links",
        ),
    ]

    selected = presentation.governing_summary_rows(rows)

    assert len(selected) == 1
    assert selected[0]["check"] == "Shear Vy with links"
    assert selected[0]["case"] == "PL-Y"


@pytest.mark.parametrize("inactive", ["NOT RUN", "NOT APPLICABLE", "NOT REQUESTED"])
def test_governing_overview_executed_result_beats_inactive_state(inactive):
    rows = [
        _overview_row(
            inactive, case="PL-ZERO", overview_key="torsion",
        ),
        _overview_row(
            "PASS", case="PL-ACTIVE", util=0.72, overview_key="torsion",
        ),
    ]

    assert presentation.governing_summary_rows(rows)[0]["case"] == "PL-ACTIVE"


def test_governing_overview_suppresses_generic_parent_when_child_exists():
    rows = [
        _overview_row(
            "NOT RUN", check="Shear", case="PL-A",
            overview_key="shear:scope", overview_parent="shear",
            overview_placeholder=True,
        ),
        _overview_row(
            "PASS", check="Shear Vx without links", case="PL-B", util=0.55,
            overview_key="shear:without_links", overview_parent="shear",
        ),
    ]

    selected = presentation.governing_summary_rows(rows)

    assert [row["check"] for row in selected] == ["Shear Vx without links"]


def test_governing_overview_separates_scope_states_from_retained_results():
    rows = [
        _overview_row("PASS", overview_key="plastic_bending", util=0.80),
        _overview_row(
            "NOT CALCULATED", check="Cross-direction interaction",
            overview_key="cross_direction",
        ),
    ]
    selected = presentation.governing_summary_rows(rows)

    assert [row["status"] for row in presentation.governing_result_rows(selected)] == [
        "PASS"
    ]
    assert [row["status"] for row in presentation.governing_information_rows(selected)] == [
        "NOT CALCULATED"
    ]


def test_result_summary_ignores_payloads_for_disabled_checks():
    rows = presentation.result_summary_rows(
        _inp(
            mode="",
            minimum_reinforcement_on=False,
            transverse_detailing_on=False,
            clear_spacing_on=False,
            shear_on=False,
            torsion_on=False,
            combined_on=False,
        ),
        {
            "plastic": _plastic(),
            "elastic": {"converged": True},
            "minimum_reinforcement": {"status": "PASS", "checks": []},
            "transverse_reinforcement": {"status": "PASS", "checks": []},
            "clear_spacing": {"status": "PASS", "governing": {}},
            "shear": {"valid": True, "util": 0.5, "res": {"valid": True}},
            "torsion": {"valid": True, "util": 0.5},
            "combined": {"valid": True, "dkna_sum": 0.5},
        },
    )

    assert rows == []


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


def test_non_governing_fatigue_spectra_are_retained_without_mutation():
    inp = _inp(
        mode="",
        fatigue_on=True,
        fatigue_edition=DesignBasisKey.FIRST_GEN_DK_NA_2024.value,
        fatigue_basis={"method": "LIVE METHOD"},
    )
    fatigue = {
        "basis_label": "CALCULATED EDITION",
        "basis": {"spectrum_source": "CALCULATED SOURCE"},
        "governing_spectrum": "Road traffic",
        "spectra": [
            {
                "spectrum_name": "Road traffic",
                "converged": True,
                "passed": False,
                "utilisation": 1.20,
            },
            {
                "spectrum_name": "Rail traffic",
                "converged": True,
                "passed": True,
                "utilisation": 0.23,
            },
        ],
    }
    before = copy.deepcopy(fatigue)

    rows = presentation.non_governing_fatigue_spectrum_rows(
        inp, {"fatigue": fatigue}
    )

    assert rows == [{
        "check": "Fatigue",
        "family": "fatigue",
        "case": "Rail traffic",
        "case_type": "CALCULATED EDITION",
        "source": "CALCULATED SOURCE",
        "status": "PASS",
        "result": "23.0 %",
        "criterion": "<= 100 %",
        "util": 0.23,
        "view": "Fatigue Results",
        "note": "Independently checked non-governing spectrum",
    }]
    assert fatigue == before
    assert presentation.non_governing_fatigue_spectrum_rows(
        inp, {"fatigue": fatigue}, stale=True
    )[0]["status"] == "STALE"


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
    assert row["note"] == (
        "6.2.2; Provide shear links because the resistance without links is "
        "insufficient"
    )


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
