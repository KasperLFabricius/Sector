"""Display-only assessment and QA-evidence helpers."""

from __future__ import annotations

import copy
import math
import inspect
import pathlib
import pickle
import sys
from dataclasses import asdict

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import result_presentation as presentation  # noqa: E402
from native_member_report_fixtures import native_formula_631_cases  # noqa: E402,F401
from native_member_report_fixtures import native_member_report_cases  # noqa: E402,F401

from app import case_analysis, load_cases, modelled_direction  # noqa: E402
from sector import (  # noqa: E402
    capacity,
    codes,
    combined as combined_core,
    section as section_core,
    shear as shear_core,
)
from sector.design_standards import DesignBasisKey, get_design_basis  # noqa: E402
from sector.materials import Concrete, MildSteel  # noqa: E402


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
    shear_a_vx = _complete_publication_shear(v_ed=80.0, vrd_c=100.0)
    shear_a_vx.update(axis="y", component="vx")
    shear_a_vy = _complete_publication_shear(v_ed=80.0, vrd_c=100.0)
    shear_b_vx = _complete_publication_shear(v_ed=95.0, vrd_c=100.0)
    shear_b_vx.update(axis="y", component="vx")
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
                        "vx": shear_a_vx,
                        "vy": shear_a_vy,
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
                    "shear": {"directions": {"vx": shear_b_vx}},
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
            **_applicable_torsion_evidence(),
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


def test_torsion_subchecks_require_applicable_publication_authority():
    out = {"plastic_cases": [{
        "name": "PL-BLOCKED",
        "results": {"torsion": {
            **_applicable_torsion_evidence(),
            "applicability_blocked": True,
            "interaction": {"valid": True, "value": 987.654},
            "min_reinf": {"applicable": True, "value": 876.543},
        }},
    }]}

    selected = presentation.worked_example_selection({}, out)[
        "torsion_subchecks"
    ]

    assert selected == {}


def test_torsion_worked_family_ignores_blocked_higher_utilisation():
    blocked = {
        **_applicable_torsion_evidence(),
        "applicability_blocked": True,
        "valid": True,
        "util": 9.0,
    }
    applicable = {
        **_applicable_torsion_evidence(),
        "valid": True,
        "util": 0.8,
    }
    out = {
        "plastic_cases": [
            {"name": "PL-BLOCKED", "results": {"torsion": blocked}},
            {"name": "PL-APPLICABLE", "results": {"torsion": applicable}},
        ]
    }

    selected = presentation.worked_example_selection({}, out)["families"]

    assert selected["torsion"] == {
        "case_id": "PL-APPLICABLE",
        "component": None,
    }


def test_retained_worked_family_is_reconciled_without_mutating_completed_state():
    blocked = {
        **_applicable_torsion_evidence(),
        "applicability_blocked": True,
        "valid": True,
        "util": 9.0,
    }
    applicable = {
        **_applicable_torsion_evidence(),
        "valid": True,
        "util": 0.8,
    }
    retained = {
        "schema": 1,
        "families": {
            "torsion": {"case_id": "PL-BLOCKED", "component": None},
        },
        "crack_examples": [],
        "crack_comparison": None,
        "cracking_threshold": None,
        "torsion_subchecks": {},
        "heightened_crack_control": None,
    }
    out = {
        "plastic_cases": [
            {"name": "PL-BLOCKED", "results": {"torsion": blocked}},
            {"name": "PL-APPLICABLE", "results": {"torsion": applicable}},
        ],
        "worked_example_selection": retained,
    }

    reconciled = presentation.validated_worked_example_selection({}, out)

    assert reconciled["families"]["torsion"] == {
        "case_id": "PL-APPLICABLE",
        "component": None,
    }
    assert retained["families"]["torsion"]["case_id"] == "PL-BLOCKED"
    out["worked_example_selection"] = {
        "schema": 1,
        "families": {},
        "crack_examples": [],
        "crack_comparison": None,
        "cracking_threshold": None,
        "torsion_subchecks": {},
        "heightened_crack_control": None,
    }
    assert presentation.validated_worked_example_selection({}, out)[
        "families"
    ]["torsion"] == {
        "case_id": "PL-APPLICABLE",
        "component": None,
    }
    out["worked_example_selection"] = {"schema": True, "families": {}}
    assert presentation.validated_worked_example_selection({}, out) == {}
    out["worked_example_selection"] = {
        "schema": 1,
        "families": {},
        "crack_examples": [{
            "case_id": "__single__",
            "system": "governing",
            "branch": [],
            "label": "long-term",
        }],
        "crack_comparison": None,
        "cracking_threshold": None,
        "torsion_subchecks": {},
        "heightened_crack_control": None,
    }
    assert presentation.validated_worked_example_selection({}, out) == {}
    valid_fine_coarse = [
        {
            "case_id": "EL-FINE",
            "system": "fine",
            "branch": "crack",
            "label": "long-term (fine)",
        },
        {
            "case_id": "EL-COARSE",
            "system": "coarse",
            "branch": "crack_coarse",
            "label": "long-term (coarse)",
        },
    ]
    assert presentation._valid_worked_crack_examples(valid_fine_coarse) is True
    assert presentation._valid_worked_crack_examples([
        valid_fine_coarse[0], {**valid_fine_coarse[0], "case_id": "EL-OTHER"},
    ]) is False
    assert presentation._valid_worked_crack_examples([
        {
            "case_id": "EL-GOVERNING",
            "system": "governing",
            "branch": "crack",
            "label": "long-term",
        },
        valid_fine_coarse[1],
    ]) is False
    complete = presentation.worked_example_selection({}, out)
    out["worked_example_selection"] = complete
    assert presentation.validated_worked_example_selection({}, out)

    incomplete = copy.deepcopy(complete)
    incomplete.pop("crack_examples")
    impossible_family = copy.deepcopy(complete)
    impossible_family["families"]["plastic"] = {
        "case_id": "PL-IMPOSSIBLE",
        "component": "vx",
    }
    unhashable_family = copy.deepcopy(complete)
    unhashable_family["families"]["shear"] = {
        "case_id": "PL-SHEAR",
        "component": [],
    }
    unhashable_subcheck = copy.deepcopy(complete)
    unhashable_subcheck["torsion_subchecks"] = {
        "interaction": {"case_id": "PL-T", "component": {}},
    }
    unhashable_duration = copy.deepcopy(complete)
    unhashable_duration["crack_comparison"] = {
        "case_id": "EL-C",
        "duration": [],
    }
    for malformed in (
        incomplete,
        impossible_family,
        unhashable_family,
        unhashable_subcheck,
        unhashable_duration,
    ):
        out["worked_example_selection"] = malformed
        assert presentation.validated_worked_example_selection({}, out) == {}
    assert presentation.validated_worked_example_selection({}, {}) == {}


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


def test_formula_631_scope_row_remains_in_the_governing_overview(native_formula_631_cases):
    inp, out = native_formula_631_cases(scope_context="selected-2023-no-shear")

    selected = presentation.governing_summary_rows(
        presentation.result_summary_rows(inp, out)
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
    native_formula_631_cases,
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
    inp, out = native_formula_631_cases(
        scope_context=scope_context,
        n_ed=inputs["n_ed"], mx_ed=inputs["mx_ed"], my_ed=inputs["my_ed"],
    )
    native_minimum = out["torsion"]["min_reinf"]
    assert native_minimum["status"] == minimum["status"]
    assert native_minimum["scope_key"] == minimum["scope_key"]
    rows = presentation.result_summary_rows(inp, out)
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
    native_formula_631_cases,
):
    inp, out = native_formula_631_cases(
        condition_status=condition_status, detailing_status=detailing_status,
    )
    minimum = out["torsion"]["min_reinf"]
    assert minimum["detailing_scope_key"] == detailing_scope_key
    rows = presentation.result_summary_rows(inp, out)
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


def _applicable_torsion_evidence(t_ed=40.0):
    return {
        "t_ed": t_ed,
        "applicability_blocked": False,
        "applicability": capacity.torsion_applicability(
            {
                "torsion_design_basis": capacity.TORSION_DESIGN_EQUILIBRIUM,
                "torsion_member_scope": capacity.TORSION_MEMBER_CLOSED,
            },
            t_ed,
        ),
    }


@pytest.mark.parametrize(
    ("axis", "tension_low", "component", "angle", "face"),
        (
            ("x", True, "z_y", 90.0, "bottom (-y)"),
            ("x", False, "z_y", -90.0, "top (+y)"),
            ("y", True, "z_x", 0.0, "left (-x)"),
            ("y", False, "z_x", 180.0, "right (+x)"),
    ),
)
def test_shear_geometry_basis_reconciles_calculated_links_arm_to_source_state(
    axis, tension_low, component, angle, face
):
    shear = _complete_publication_shear(
        v_ed=30.0,
        vrd_c=100.0,
        z_mm=517.787,
    )
    shear.update(
        axis=axis,
        component="vy" if axis == "x" else "vx",
        tension_low=tension_low,
    )
    shear["links"].update(
        z_component=component,
        z_source_angle_deg=angle,
    )

    basis = presentation.shear_geometry_basis(
        _publication_inp(shear),
        shear,
    )

    assert basis["z_mm"] == pytest.approx(shear["links"]["res"]["z"])
    assert f"|{component}| from PL-17" in basis["statement"]
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


def _zero_formula_628_assessment():
    return {
        "status": "PASS",
        "ok": True,
        "reason": "no_longitudinal_torsion_demand",
        "required_asl_mm2": 0.0,
        "required_design_force_kn": 0.0,
        "provided_design_force_kn": 400.0,
        "reference_fyd_mpa": 400.0,
        "demand_ratio": 0.0,
        "area_sufficient": True,
    }


def _complete_longitudinal_candidate(
    utilisation,
    *,
    axis="x",
    tension_low=True,
    conditional=True,
    biaxial=False,
):
    total = float(utilisation) * 100.0
    return {
        "valid": True,
        "status": "PASS" if utilisation <= 1.0 + 1.0e-9 else "FAIL",
        "ok": utilisation <= 1.0 + 1.0e-9,
        "axis": axis,
        "tension_low": tension_low,
        "conditional": conditional,
        "biaxial": biaxial,
        "off_util": 0.0,
        "off_not_evaluated": None,
        "m_ed": total,
        "mv": 0.0,
        "mt": 0.0,
        "m_total": total,
        "m_rd": 100.0,
        "ftd_v": 0.0,
        "ftd_t": 0.0,
        "z": 0.25,
        "util": utilisation,
        "capped": False,
    }


def test_combined_component_formatter_retains_subordinate_failure():
    theta_deg = math.degrees(math.atan2(1.0, 1.5))
    combined = {
        "valid": True,
        "method": "DK NA",
        "dkna_sum": 0.80,
        "crushing": {
            "valid": True, "value": 1.10, "cot": 1.5,
            "theta_deg": theta_deg,
        },
        "transverse": {
            "valid": True, "cot": 1.5, "theta_deg": theta_deg,
            "u_crush": 1.10, "u_stirrup": 0.75,
            "shear_fraction": 0.30, "torsion_fraction": 0.45,
            "governing": 1.10, "governs": "crushing",
        },
        "longitudinal": _complete_longitudinal_candidate(0.65),
        "chord_off": _complete_longitudinal_candidate(0.55, axis="y"),
        "governing_longitudinal": _complete_longitudinal_candidate(0.65),
        "longitudinal_all_conditional": True,
        "t_ed": 0.0,
        "asl_torsion": 0.0,
        "torsion_subdivided": False,
        "torsion_subtubes": None,
        "torsion_longitudinal_assessment": _zero_formula_628_assessment(),
    }
    components = presentation.combined_physical_components(combined)
    by_key = {item["key"]: item for item in components}

    assert presentation.combined_dkna_status(combined) == "PASS"
    assert by_key["concrete"]["status"] == "FAIL"
    assert by_key["stirrup"]["status"] == "PASS"
    assert by_key["longitudinal"]["status"] == "PASS"
    assert by_key["longitudinal"]["util"] == pytest.approx(0.65)
    assert capacity.aggregate_assessment_status(
        ("PASS", *(item["status"] for item in components))
    ) == "FAIL"
    _assert_unbound_combined_is_not_published(
        _inp(mode="Plastic", combined_on=True),
        combined,
    )


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
    assert presentation.combined_dkna_status(combined) == "CONDITIONAL"
    note = presentation.combined_dkna_assumption_note(combined)
    assert "design assumption" in note
    assert "area, distribution and anchorage" in note
    assert "N+M+V+T" not in note
    _assert_unbound_combined_is_not_published(
        _inp(mode="Plastic", combined_on=True),
        combined,
    )


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
        else _complete_longitudinal_candidate(longitudinal_util)
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
        "t_ed": 0.0,
        "asl_torsion": 0.0,
        "torsion_subdivided": False,
        "torsion_subtubes": None,
        "torsion_longitudinal_assessment": _zero_formula_628_assessment(),
    }
    components = presentation.combined_physical_components(combined)
    longitudinal_component = next(
        item for item in components if item["key"] == "longitudinal"
    )
    assert presentation.combined_dkna_status(combined) == expected_dkna
    assert longitudinal_component["status"] == expected_physical
    assert capacity.aggregate_assessment_status(
        (expected_dkna, *(item["status"] for item in components))
    ) == overall
    _assert_unbound_combined_is_not_published(
        _inp(mode="Plastic", combined_on=True),
        combined,
    )


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
    by_key = {
        item["key"]: item
        for item in presentation.combined_physical_components(combined)
    }
    assert by_key["concrete"]["status"] == "NOT ASSESSED"
    assert by_key["stirrup"]["status"] == "NOT ASSESSED"
    assert by_key["longitudinal"]["status"] == "NOT ASSESSED"
    assert "pure-axis substitute" in (
        by_key["longitudinal"]["note"].lower()
    )
    _assert_unbound_combined_is_not_published(
        _inp(mode="Plastic", combined_on=True),
        combined,
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
    assert presentation.combined_dkna_screen_label(combined) == (
        "max(N+M+T, N+V+T)"
    )
    assert presentation.combined_dkna_status(combined) == "NOT ASSESSED"
    rows = _assert_unbound_combined_is_not_published(
        _inp(mode="Plastic", combined_on=True),
        combined,
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
        "torsion_longitudinal_assessment": _zero_formula_628_assessment(),
    }
    longitudinal = next(
        item
        for item in presentation.combined_physical_components(combined)
        if item["key"] == "longitudinal"
    )
    assert longitudinal["status"] == "NOT ASSESSED"
    assert "not solved" in longitudinal["note"]
    rows = _assert_unbound_combined_is_not_published(
        _inp(mode="Plastic", combined_on=True),
        combined,
    )
    assert presentation.overall_summary_status(rows) == "NOT ASSESSED"


def test_combined_physical_components_uses_the_governing_longitudinal_face():
    shear_axis = _complete_longitudinal_candidate(0.60)
    shear_axis.update(
        role="shear_axis",
        has_torsion=False,
        gets_shift=False,
    )
    governing = _complete_longitudinal_candidate(
        0.85,
        axis="y",
        tension_low=False,
        biaxial=True,
    )
    governing["role"] = "off_axis"
    components = presentation.combined_physical_components({
        "transverse": {
            "valid": True, "cot": 1.6,
            "u_crush": 0.40, "u_stirrup": 0.55,
            "shear_fraction": 0.20, "torsion_fraction": 0.35,
        },
        "longitudinal": shear_axis,
        "chord_off": governing,
        "governing_longitudinal": governing,
        "longitudinal_candidates": [shear_axis, governing],
        "longitudinal_assessment": {
            "status": "PASS",
            "ok": True,
            "util": 0.85,
            "reason": "required_longitudinal_chords_satisfied",
            "coverage_complete": True,
            "governing": governing,
        },
        "longitudinal_all_conditional": True,
        "t_ed": 0.0,
        "asl_torsion": 0.0,
        "torsion_subdivided": False,
        "torsion_subtubes": None,
        "torsion_longitudinal_assessment": _zero_formula_628_assessment(),
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
    fallback = _complete_longitudinal_candidate(0.60, conditional=False)
    governing = _complete_longitudinal_candidate(
        0.85,
        axis="y",
        tension_low=False,
        biaxial=True,
    )
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
    assert longitudinal["util"] is None
    assert longitudinal["status"] == "NOT ASSESSED"
    assert "pure-axis substitute" in longitudinal["note"]
    assert "x-axis negative face" in longitudinal["note"]


def test_combined_components_preserve_non_governing_face_fallback():
    exact_governing = _complete_longitudinal_candidate(
        0.85,
        tension_low=False,
    )
    fallback_face = _complete_longitudinal_candidate(
        0.60,
        conditional=False,
    )
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
    assert longitudinal["util"] is None
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
    assert components[2]["status"] == "NOT ASSESSED"
    assert components[2]["util"] is None


def test_combined_physical_components_withholds_off_axis_only_verdict():
    governing = _complete_longitudinal_candidate(0.75, axis="y")
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
    (
        "transverse_util",
        "interaction_util",
        "transverse_cot",
        "interaction_cot",
        "transverse_theta",
        "interaction_theta",
        "expected_status",
        "expected_util",
        "expected_angle_valid",
    ),
    (
        (0.50, 0.50, 1.50, 1.50, 33.690067525979785,
         33.690067525979785, "PASS", 0.50, True),
        (0.50, 0.50, 2.00, 2.00, 26.6,
         26.6, "PASS", 0.50, True),
        (True, 0.50, 1.50, 1.50, 33.690067525979785,
         33.690067525979785, "NOT ASSESSED", None, True),
        (0.40, 0.50, 1.50, 1.50, 33.690067525979785,
         33.690067525979785, "NOT ASSESSED", None, True),
        (0.50, True, 1.50, 1.50, 33.690067525979785,
         33.690067525979785, "NOT ASSESSED", None, True),
        (0.50, 0.50, 1.50, 1.40, 33.690067525979785,
         35.53767779197438, "NOT ASSESSED", None, False),
        (0.50, 0.50, True, 1.00, 45.0, 45.0,
         "NOT ASSESSED", None, False),
        (0.50, 0.50, 1.50, math.inf, 33.690067525979785, 0.0,
         "NOT ASSESSED", None, False),
        (0.50, 0.50, 1.50, 1.50, None, 33.690067525979785,
         "NOT ASSESSED", None, False),
        (0.50, 0.50, 1.50, 1.50, 33.690067525979785, "33.69",
         "NOT ASSESSED", None, False),
        (0.50, 0.50, 1.50, 1.50, 33.690067525979785, 60.0,
         "NOT ASSESSED", None, False),
    ),
)
def test_combined_physical_components_reconciles_formula_629_evidence(
    transverse_util,
    interaction_util,
    transverse_cot,
    interaction_cot,
    transverse_theta,
    interaction_theta,
    expected_status,
    expected_util,
    expected_angle_valid,
):
    components = presentation.combined_physical_components({
        "transverse": {
            "valid": True,
            "cot": transverse_cot,
            "theta_deg": transverse_theta,
            "u_crush": transverse_util,
            "u_stirrup": 0.60,
            "shear_fraction": 0.20,
            "torsion_fraction": 0.40,
        },
        "crushing": {
            "valid": True,
            "value": interaction_util,
            "cot": interaction_cot,
            "theta_deg": interaction_theta,
        },
    })

    concrete = next(item for item in components if item["key"] == "concrete")
    assert concrete["status"] == expected_status
    assert concrete["util"] == expected_util
    assert concrete["angle_valid"] is expected_angle_valid
    stirrup = next(item for item in components if item["key"] == "stirrup")
    assert stirrup["status"] == (
        "PASS" if expected_angle_valid else "NOT ASSESSED"
    )
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

    assert "capacity.combined_longitudinal_assessment" in source
    assert "max(" not in source
    assert "candidate_util" not in source


def _complete_publication_shear(
    *,
    v_ed,
    vrd_c,
    asw_over_s=0.5,
    z_mm=500.0,
    longitudinal_assessment=None,
):
    link_result = shear_core.vrd_links(
        35.0,
        codes.EC2_2005_DKNA,
        300.0,
        550.0,
        asw_over_s,
        500.0,
        0.0,
        0.18,
        1.0,
        2.5,
        z_mm=z_mm,
        v_ed_kn=v_ed,
    )
    spacing = 200.0
    link_area = asw_over_s * spacing
    legs = 2.0
    diameter = math.sqrt(4.0 * link_area / (legs * math.pi))
    angle_limits = {
        "minimum": codes.EC2_2005_DKNA.shear_cot_min_limit,
        "maximum": codes.EC2_2005_DKNA.shear_cot_max_limit,
        "basis": "2005-family fixed range",
        "ductility_class": "B",
        "ductility_factor": 1.0,
        "axial_tension_applied": False,
        "compression_extension_credited": False,
        "clause": "EN 1992-1-1:2005, 6.2.3(2), Formula (6.7N)",
    }


    angle_applicability = shear_core.strut_angle_applicability(
        1.0,
        2.5,
        permitted_min=angle_limits["minimum"],
        permitted_max=angle_limits["maximum"],
        method=codes.EC2_2005_DKNA.label,
        basis=angle_limits["basis"],
        clause=angle_limits["clause"],
        active=v_ed > 0.0,
    )
    link_result["angle_applicability"] = angle_applicability
    geometry = shear_core.resolve_shear_geometry(
        model_2023=False,
        solid_rectangle=True,
        section_form=shear_core.SHEAR_SECTION_AUTO,
        bw_mm=300.0,
        bw_user=False,
        links_present=True,
        duct_case=shear_core.SHEAR_DUCT_NONE,
    )
    longitudinal_force = (
        0.0 if v_ed <= vrd_c else 0.5 * v_ed * link_result["cot"]
    )
    if longitudinal_assessment is None:
        longitudinal_assessment = {
            "status": (
                "NOT APPLICABLE"
                if longitudinal_force == 0.0
                else "NOT ASSESSED"
            ),
            "ok": None,
            "util": None,
            "reason": (
                "no_longitudinal_chord_action"
                if longitudinal_force == 0.0
                else "required_longitudinal_chord_coverage_incomplete"
            ),
            "coverage_complete": longitudinal_force == 0.0,
            "governing": None,
        }
    return {
        "v_ed": v_ed,
        "signed_v_ed": v_ed,
        "axis": "x",
        "component": "vy",
        "tension_low": True,
        "n_ed": 0.0,
        "n_ed_comp": 0.0,
        "ac": 0.18,
        "d": 550.0,
        "fck": 35.0,
        "bw": 300.0,
        "res": {"valid": True, "vrd_c": vrd_c},
        "util": v_ed / vrd_c,
        "method": codes.EC2_2005_DKNA.label,
        "model_2023": False,
        "links": {
            "res": link_result,
            "util": v_ed / link_result["vrd"],
            "asw": link_area,
            "asw_over_s": asw_over_s,
            "effective_asw_over_s": asw_over_s,
            "asw_factor": 1.0,
            "legs": legs,
            "dia": diameter,
            "s": spacing,
            "longitudinal_shear_force": longitudinal_force,
            "longitudinal_shear_symbol": "delta_Ftd",
            "longitudinal_shear_clause": "6.2.3(7), Formula (6.18)",
            "delta_ftd": longitudinal_force,
            "required": bool(v_ed > vrd_c),
            "fywk": 500.0,
            "cot_min": 1.0,
            "cot_max": 2.5,
            "cot_limit_lo": 1.0,
            "cot_limit_hi": 2.5,
            "angle_limits": angle_limits,
            "angle_applicability": angle_applicability,
            "model_2023": False,
            "theta_mode": "resistance",
            "member_angle_selection": None,
            "longitudinal_assessment": longitudinal_assessment,
            "longitudinal_all_conditional": False,
            "out_of_limits": False,
            "z_source": "plastic internal lever arm",
            "z_component": "z_y",
            "z_source_angle_deg": 90.0,
            "z_source_case": "PL-17",
            "z_source_axial_kn": 0.0,
            "shear_geometry": geometry,
        },
    }


def _complete_publication_shear_2023(
    *,
    v_ed,
    vrd_c,
    asw_over_s=10.0,
):
    shear = _complete_publication_shear(
        v_ed=v_ed,
        vrd_c=vrd_c,
        asw_over_s=asw_over_s,
    )
    limits = shear_core.compression_field_limits_2023(0.0, v_ed, "B")
    applicability = shear_core.strut_angle_applicability(
        1.0,
        2.5,
        permitted_min=limits["minimum"],
        permitted_max=limits["maximum"],
        method=codes.EC2_2023.label,
        basis=limits["basis"],
        clause=limits["clause"],
        active=v_ed > 0.0,
    )
    links = shear["links"]
    result = shear_core.vrd_links(
        35.0,
        codes.EC2_2023,
        300.0,
        550.0,
        asw_over_s,
        500.0,
        0.0,
        0.18,
        1.0,
        2.5,
        z_mm=500.0,
        fcd_mpa=35.0 / 1.45,
        gamma_s=1.20,
        v_ed_kn=v_ed,
        ductility_class="B",
        angle_applicability=applicability,
    )
    geometry = shear_core.resolve_shear_geometry(
        model_2023=True,
        solid_rectangle=True,
        section_form=shear_core.SHEAR_SECTION_AUTO,
        bw_mm=300.0,
        bw_user=False,
        links_present=True,
        duct_case=shear_core.SHEAR_DUCT_NONE,
    )
    links.update(
        res=result,
        util=v_ed / result["vrd"],
        longitudinal_shear_force=(
            0.0 if v_ed <= vrd_c else v_ed * result["cot"]
        ),
        longitudinal_shear_symbol="NVd",
        longitudinal_shear_clause="8.2.3(8), Formula (8.50)",
        delta_ftd=None,
        cot_limit_lo=limits["minimum"],
        cot_limit_hi=limits["maximum"],
        angle_limits=limits,
        angle_applicability=applicability,
        model_2023=True,
        shear_geometry=geometry,
    )
    shear.update(
        method=codes.EC2_2023.label,
        model_2023=True,
        fck=35.0,
        n_ed_comp=0.0,
        ac=0.18,
    )
    return shear


def _publication_inp(shear, **updates):
    links = shear["links"]
    axis = shear.get("axis", "x")
    component = shear.get("component") or ("vy" if axis == "x" else "vx")
    method = shear.get("method", codes.EC2_2005_DKNA.label)
    angle_limits = links.get("angle_limits") or {}
    ductility_class = angle_limits.get("ductility_class", "B")
    outer = (
        [
            (-0.15, -0.30),
            (0.15, -0.30),
            (0.15, 0.30),
            (-0.15, 0.30),
        ]
        if axis == "x"
        else [
            (-0.30, -0.15),
            (0.30, -0.15),
            (0.30, 0.15),
            (-0.30, 0.15),
        ]
    )
    if axis == "x":
        bars = [(-0.10, -0.25 if shear.get("tension_low", True) else 0.25, 1473.0)]
    else:
        bars = [(-0.25 if shear.get("tension_low", True) else 0.25, -0.10, 1473.0)]
    inp = _inp(
        outer=outer,
        holes=[],
        bars=bars,
        tendons=[],
        section=section_core.Section.from_polygon(
            corners=outer,
            bars_xy_area_mm2=bars,
        ),
        prestress=None,
        concrete=Concrete(fck=35.0, gamma_c=1.45, curve=2),
        steel=MildSteel(
            fytk=500.0,
            fyck=500.0,
            futk=500.0,
            eut=0.05,
            gamma_y=1.2,
            curve=2,
        ),
        P_pl=0.0,
        Mx_pl=0.0,
        My_pl=0.0,
        shear_on=True,
        shear_links=True,
        shear_method=method,
        transverse_ductility_class=ductility_class,
        shear_fywk=500.0,
        shear_section_form=shear_core.SHEAR_SECTION_AUTO,
        shear_axis=axis,
        shear_tension=bool(shear.get("tension_low", True)),
        shear_V=shear["v_ed"],
        shear_bw=0.0,
        shear_link_dia=links["dia"],
        shear_link_s=links["s"],
        strut_cot_min=links["cot_min"],
        strut_cot_max=links["cot_max"],
        shear_vx_bw=0.0,
        shear_vy_bw=0.0,
        shear_vx_web_inclination_deg=0.0,
        shear_vy_web_inclination_deg=0.0,
        shear_hoop_diameter=0.0,
        shear_vx_fitted_z=0.0,
        shear_vy_fitted_z=0.0,
        shear_duct_case=shear_core.SHEAR_DUCT_NONE,
        shear_vx_duct_sum=0.0,
        shear_vy_duct_sum=0.0,
        shear_vx_duct_largest=0.0,
        shear_vy_duct_largest=0.0,
        shear_dlower=16.0,
        shear_gamma_v=1.4,
    )
    inp[f"shear_{component}_link_legs"] = links["legs"]
    inp.update(updates)
    link_result = links.get("res") or {}
    if link_result.get("z") is not None:
        expected_z, _z_reason = capacity.shear_lever_arm(
            inp,
            axis,
            bool(shear.get("tension_low", True)),
            shear["d"],
        )
        assert expected_z is not None
        rebuilt = shear_core.vrd_links(
            shear["fck"],
            capacity.SHEAR_METHODS[inp["shear_method"]],
            shear["bw"],
            shear["d"],
            links["asw_over_s"],
            links["fywk"],
            shear.get("n_ed_comp", 0.0),
            shear.get("ac", 0.18),
            links["cot_min"],
            links["cot_max"],
            z_mm=expected_z,
            fcd_mpa=inp["concrete"].fcd,
            gamma_s=inp["steel"].gamma_y,
            v_ed_kn=shear["v_ed"],
            ductility_class=ductility_class,
            angle_applicability=links["angle_applicability"],
        )
        links["res"] = rebuilt
        links["util"] = shear["v_ed"] / rebuilt["vrd"]
        link_result = rebuilt
        links["z_input_basis"] = capacity.shear_link_arm_publication_basis(
            inp,
            axis,
            bool(shear.get("tension_low", True)),
            link_result["z"],
        )
    return inp


def _bind_concrete_publication_fixture(shear, inp):
    """Replace the synthetic VRd,c child with one complete canonical record."""

    axis = shear["axis"]
    tension_low = shear["tension_low"]
    if axis == "x":
        inp["outer"] = [
            (-0.15, -0.30),
            (0.15, -0.30),
            (0.15, 0.30),
            (-0.15, 0.30),
        ]
        inp["bars"] = [(-0.10, -0.25 if tension_low else 0.25, 1473.0)]
    else:
        inp["outer"] = [
            (-0.30, -0.15),
            (0.30, -0.15),
            (0.30, 0.15),
            (-0.30, 0.15),
        ]
        inp["bars"] = [(-0.25 if tension_low else 0.25, -0.10, 1473.0)]
    area, cx, cy = capacity.gross_area_centroid(inp["outer"], inp["holes"])
    asl, cg, asl_ids = shear_core.tension_reinforcement_selection(
        inp["bars"], axis, tension_low, cy if axis == "x" else cx
    )
    d_mm = shear_core.effective_depth(inp["outer"], axis, tension_low, cg)
    bw_auto = shear_core.min_web_width(inp["outer"], inp["holes"], axis)
    code = capacity.SHEAR_METHODS[inp["shear_method"]]
    model_2023 = getattr(code, "shear_model", "2005") == "2023"
    fyd = capacity.design_yield(inp["steel"])
    geometry = shear_core.resolve_shear_geometry(
        model_2023=model_2023,
        solid_rectangle=True,
        section_form=inp["shear_section_form"],
        bw_mm=bw_auto,
        bw_user=False,
        links_present=True,
        duct_case=inp["shear_duct_case"],
    )
    ddg = code.shear_ddg(inp["concrete"].fck, inp["shear_dlower"]) if model_2023 else 0.0
    gamma_v = (
        shear_core.validate_gamma_v(inp["shear_gamma_v"], label="gamma_V")
        if model_2023
        else None
    )
    m_ed_2023 = inp["Mx_pl"] if axis == "x" else inp["My_pl"]
    concrete = shear_core.vrd_c(
        inp["concrete"].fck,
        code,
        geometry["concrete_bw_mm"],
        d_mm,
        asl,
        0.0,
        area,
        fyd_mpa=fyd,
        ddg_mm=(ddg or 32.0),
        m_ed_knm=m_ed_2023,
        v_ed_kn=shear["v_ed"],
        fcd_mpa=inp["concrete"].fcd,
        gamma_c=inp["concrete"].gamma_c,
        gamma_v=gamma_v,
    )
    shear.update(
        res=concrete,
        util=shear["v_ed"] / concrete["vrd_c"],
        signed_v_ed=shear["v_ed"],
        bw=bw_auto,
        bw_auto=bw_auto,
        bw_user=False,
        shear_geometry=geometry,
        d=d_mm,
        asl=asl,
        asl_bar_ids=asl_ids,
        asl_cg=cg,
        ac=area,
        fck=inp["concrete"].fck,
        n_ed=0.0,
        n_prestress=0.0,
        n_ed_comp=0.0,
        m_ed_2023=m_ed_2023,
        moment_reference_shift=0.0,
        m_prestress=0.0,
        centroid=(cx, cy),
        method=inp["shear_method"],
        model_2023=model_2023,
        ddg=ddg,
        fyd_flex=fyd,
    )
    links = shear.get("links")
    if isinstance(links, dict) and (links.get("res") or {}).get("z") is not None:
        links["required"] = bool(shear["v_ed"] > concrete["vrd_c"])
        links["z_input_basis"] = capacity.shear_link_arm_publication_basis(
            inp,
            axis,
            tension_low,
            links["res"]["z"],
        )
    return concrete["vrd_c"]


def _bind_link_chord_publication_fixture(shear, inp, *, mx_factor=0.0):
    """Attach one current face/chord result to a complete shear fixture."""

    axis = shear["axis"]
    tension_low = shear["tension_low"]
    m_rd, conditional = capacity.shear_face_mrd(
        inp,
        axis,
        tension_low,
        m_off=0.0,
        moment_reference_shift=0.0,
    )
    if axis == "x":
        inp["Mx_pl"] = mx_factor * m_rd
    else:
        inp["My_pl"] = mx_factor * m_rd
    shear["m_ed_2023"] = inp["Mx_pl"] if axis == "x" else inp["My_pl"]
    links = shear["links"]
    force = (
        0.5 * shear["v_ed"] * links["res"]["cot"]
        if shear["v_ed"] > shear["res"]["vrd_c"]
        else 0.0
    )
    links["longitudinal_shear_force"] = force
    links["delta_ftd"] = force
    applied = combined_core.chord_applied_moment(
        inp["Mx_pl"] if axis == "x" else inp["My_pl"],
        tension_low,
    )
    chord = combined_core.longitudinal_check(
        applied,
        m_rd,
        force,
        0.0,
        links["res"]["z"] / 1000.0,
        cap_shear_force=True,
    )
    chord.update(
        valid=True,
        role="shear_axis",
        axis=axis,
        tension_low=tension_low,
        off_util=0.0,
        biaxial=False,
        m_off=0.0,
        conditional=conditional,
        has_torsion=False,
        gets_shift=True,
        off_not_evaluated=None,
        z_src="plastic internal lever arm",
        theta_mode=links["theta_mode"],
    )
    links.update(
        chord=chord,
        chord_off=None,
        chord_candidates=[chord],
        governing_longitudinal=chord,
        longitudinal_fallback=None,
        longitudinal_all_conditional=True,
    )
    links["longitudinal_assessment"] = capacity.longitudinal_chord_assessment(
        links,
        shear_axis=axis,
        shear_tension_low=tension_low,
        shear_live=True,
        torsion_live=False,
        torsion_subdivided=False,
    )
    links["z_input_basis"] = capacity.shear_link_arm_publication_basis(
        inp,
        axis,
        tension_low,
        links["res"]["z"],
    )
    return chord


def test_provided_link_publication_accepts_reversed_entered_cot_limits():
    shear = _complete_publication_shear(v_ed=30.0, vrd_c=47.59286047)
    inp = _publication_inp(shear)
    inp["strut_cot_min"], inp["strut_cot_max"] = (
        inp["strut_cot_max"],
        inp["strut_cot_min"],
    )

    assessment = presentation.provided_link_publication_assessment(inp, shear)

    assert assessment.valid is True
    assert assessment.status == "PASS"


def _directional_publication_inp(shear, *, signed_v=30.0):
    """Return one complete named-case Vx/Vy authority record."""

    inp = _publication_inp(shear)
    inp.update(
        shear_Vx=0.0,
        shear_Vy=float(signed_v),
        shear_face_x="auto",
        shear_face_y="auto",
        shear_components={
            "vx": {
                "signed_v_ed": 0.0,
                "v_ed": 0.0,
                "axis": "y",
                "face": "auto",
                "active": False,
            },
            "vy": {
                "signed_v_ed": float(signed_v),
                "v_ed": abs(float(signed_v)),
                "axis": "x",
                "face": "auto",
                "active": True,
            },
        },
    )
    shear["signed_v_ed"] = float(signed_v)
    return inp


@pytest.mark.parametrize("signed_v", (30.0, -30.0))
def test_directional_link_publication_accepts_coherent_signed_action(signed_v):
    shear = _complete_publication_shear(v_ed=30.0, vrd_c=47.59286047)
    inp = _directional_publication_inp(shear, signed_v=signed_v)

    assessment = presentation.provided_link_publication_assessment(inp, shear)

    assert assessment.valid is True
    assert assessment.status == "PASS"


@pytest.mark.parametrize(
    "attack",
    (
        "raw-action",
        "component-magnitude",
        "component-signed",
        "component-axis",
        "component-face",
        "component-active",
        "mx-action",
        "my-action",
    ),
)
def test_directional_link_publication_rejects_contradictory_action_aliases(attack):
    shear = _complete_publication_shear(v_ed=30.0, vrd_c=47.59286047)
    inp = _directional_publication_inp(shear)
    component = inp["shear_components"]["vy"]
    if attack == "raw-action":
        inp["shear_Vy"] = 31.0
    elif attack == "component-magnitude":
        component["v_ed"] = 31.0
    elif attack == "component-signed":
        component["signed_v_ed"] = 31.0
    elif attack == "component-axis":
        component["axis"] = "y"
    elif attack == "component-face":
        component["face"] = "negative"
    elif attack == "component-active":
        component["active"] = False
    elif attack == "mx-action":
        inp["Mx_pl"] = True
    else:
        inp["My_pl"] = math.inf

    assessment = presentation.provided_link_publication_assessment(inp, shear)

    assert assessment.valid is False
    assert assessment.status == "NOT ASSESSED"
    assert assessment.resistance is None
    assert assessment.utilisation is None


def test_link_publication_recomputes_expected_lever_arm_instead_of_trusting_child():
    shear = _complete_publication_shear(v_ed=30.0, vrd_c=47.59286047)
    inp = _directional_publication_inp(shear)
    links = shear["links"]
    forged_z = links["res"]["z"] + 100.0
    forged = shear_core.vrd_links(
        shear["fck"],
        capacity.SHEAR_METHODS[inp["shear_method"]],
        shear["bw"],
        shear["d"],
        links["asw_over_s"],
        links["fywk"],
        0.0,
        0.18,
        links["cot_min"],
        links["cot_max"],
        z_mm=forged_z,
        v_ed_kn=shear["v_ed"],
        angle_applicability=links["angle_applicability"],
    )
    links["res"] = forged
    links["util"] = shear["v_ed"] / forged["vrd"]
    links["z_input_basis"] = capacity.shear_link_arm_publication_basis(
        inp,
        shear["axis"],
        shear["tension_low"],
        forged_z,
    )

    assessment = presentation.provided_link_publication_assessment(inp, shear)

    assert assessment.valid is False
    assert assessment.status == "NOT ASSESSED"
    assert assessment.resistance is None
    assert assessment.utilisation is None


def _forge_publication_compression_coefficient(shear, coefficient):
    links = shear["links"]
    result = links["res"]
    model_2023 = links["model_2023"]
    a = result["asw_over_s"] * result["fywd"]
    if model_2023:
        result["nu"] = coefficient
        result["nu1"] = coefficient
        b = result["bw"] * coefficient * result["fcd"]
    else:
        result["alpha_cw"] = coefficient
        b = coefficient * result["bw"] * result["nu1"] * result["fcd"]
    angle = shear_core.optimum_strut_angle(
        a,
        b,
        result["cot_min"],
        result["cot_max"],
    )
    vrd_s = a * result["z"] * angle.cot / 1000.0
    vrd_max = b * result["z"] / (angle.cot + angle.tan) / 1000.0
    result.update(
        vrd_s=vrd_s,
        vrd_max=vrd_max,
        vrd=min(vrd_s, vrd_max),
        cot=angle.cot,
        tan=angle.tan,
        theta_deg=angle.theta_deg,
        sin_cos=angle.sin_cos,
        cot_unconstrained=angle.cot_unconstrained,
        angle_selection=angle.selection,
        angle_a=a,
        angle_b=b,
        governs=(
            "links (tau_Rd,sy)"
            if model_2023 and vrd_s <= vrd_max
            else "compression field (sigma_cd)"
            if model_2023
            else "stirrups (VRd,s)"
            if vrd_s <= vrd_max
            else "crushing (VRd,max)"
        ),
    )
    if model_2023:
        tau_ed = shear["v_ed"] * 1000.0 / (result["bw"] * result["z"])
        result.update(
            nu_fcd=coefficient * result["fcd"],
            sigma_cd=tau_ed * (angle.cot + angle.tan),
            tau_ed=tau_ed,
            tau_rd_sy=result["rho_w"] * result["fywd"] * angle.cot,
            tau_rd_max=(
                coefficient * result["fcd"] / (angle.cot + angle.tan)
            ),
        )
    links["util"] = shear["v_ed"] / result["vrd"]
    force = (1.0 if model_2023 else 0.5) * shear["v_ed"] * angle.cot
    links["longitudinal_shear_force"] = force
    if not model_2023:
        links["delta_ftd"] = force


@pytest.mark.parametrize(
    ("factory", "coefficient"),
    (
        (_complete_publication_shear, 2.0),
        (_complete_publication_shear_2023, 1.0),
    ),
)
def test_current_link_publication_rejects_coherent_compression_coefficient_forgery(
    factory,
    coefficient,
):
    shear = factory(v_ed=1000.0, vrd_c=47.59286047, asw_over_s=10.0)
    inp = _publication_inp(shear)
    vrd_c = _bind_concrete_publication_fixture(shear, inp)
    baseline = presentation.provided_link_publication_assessment(inp, shear)
    assert baseline.valid is True
    assert baseline.status == "FAIL"

    _forge_publication_compression_coefficient(shear, coefficient)
    retained = capacity.provided_link_shear_assessment(shear)
    guarded = presentation.provided_link_publication_assessment(inp, shear)

    assert retained.valid is True
    assert retained.status == "PASS"
    assert guarded.valid is False
    assert guarded.status == "NOT ASSESSED"
    assert guarded.resistance is None


@pytest.mark.parametrize(
    "attack",
    (
        "method",
        "fck",
        "gamma-c",
        "diameter",
        "legs",
        "spacing",
        "cotangent",
        "section-form",
        "duct-case",
    ),
)
def test_provided_link_publication_binds_every_current_input_operand(attack):
    shear = _complete_publication_shear(v_ed=30.0, vrd_c=47.59286047)
    inp = _publication_inp(shear)
    if attack == "method":
        inp["shear_method"] = next(
            method
            for method in capacity.SHEAR_METHODS
            if method != codes.EC2_2005_DKNA.label
        )
    elif attack == "fck":
        inp["concrete"] = Concrete(fck=40.0, gamma_c=1.45, curve=2)
    elif attack == "gamma-c":
        inp["concrete"] = Concrete(fck=35.0, gamma_c=1.50, curve=2)
    elif attack == "diameter":
        inp["shear_link_dia"] *= 1.01
    elif attack == "legs":
        inp["shear_vy_link_legs"] += 1.0
    elif attack == "spacing":
        inp["shear_link_s"] += 1.0
    elif attack == "cotangent":
        inp["strut_cot_min"] = 1.1
    elif attack == "section-form":
        inp["shear_section_form"] = shear_core.SHEAR_SECTION_CIRCULAR
    else:
        inp["shear_duct_case"] = shear_core.SHEAR_DUCT_GROUTED_PLASTIC_THIN

    assessment = presentation.provided_link_publication_assessment(inp, shear)

    assert assessment.valid is False
    assert assessment.status == "NOT ASSESSED"
    assert assessment.resistance is None
    assert assessment.utilisation is None


@pytest.mark.parametrize(
    "attack",
    (
        "input-axial",
        "result-axial",
        "retained-axial",
        "angle",
        "case",
        "component",
        "source",
    ),
)
def test_link_arm_publication_rejects_stale_source_evidence(attack):
    shear = _complete_publication_shear(v_ed=30.0, vrd_c=47.59286047)
    inp = _publication_inp(shear)
    if attack == "input-axial":
        inp["P_pl"] = 1.0
    elif attack == "result-axial":
        shear["n_ed"] = 1.0
    elif attack == "retained-axial":
        shear["links"]["z_source_axial_kn"] = 1.0
    elif attack == "angle":
        shear["links"]["z_source_angle_deg"] = 91.0
    elif attack == "case":
        shear["links"]["z_source_case"] = "PL-OLD"
    elif attack == "component":
        shear["links"]["z_component"] = "z_x"
    else:
        shear["links"]["z_source"] = "internal route"

    assessment = presentation.provided_link_publication_assessment(inp, shear)
    basis = presentation.shear_geometry_basis(inp, shear)

    assert assessment.valid is False
    assert basis["z_mm"] is None
    assert "not assessed" in basis["statement"].lower()


def _publication_shear_with_chord(
    *,
    v_ed=120.0,
    vrd_c=100.0,
    m_ed=20.0,
    m_rd=100.0,
):
    shear = _complete_publication_shear(v_ed=v_ed, vrd_c=vrd_c)
    force = shear["links"]["longitudinal_shear_force"]
    chord = combined_core.longitudinal_check(
        m_ed,
        m_rd,
        force,
        0.0,
        0.25,
    )
    chord.update(
        valid=True,
        role="shear_axis",
        axis="x",
        tension_low=True,
        conditional=True,
        biaxial=False,
        off_util=0.0,
        off_not_evaluated=None,
        has_torsion=False,
        gets_shift=True,
    )
    links = shear["links"]
    links.update(
        chord=chord,
        chord_off=None,
        chord_candidates=[chord],
        governing_longitudinal=chord,
        longitudinal_fallback=None,
        longitudinal_all_conditional=True,
    )
    links["longitudinal_assessment"] = capacity.longitudinal_chord_assessment(
        links,
        shear_axis="x",
        shear_tension_low=True,
        shear_live=True,
        torsion_live=False,
        torsion_subdivided=False,
    )
    return shear


@pytest.mark.parametrize(
    "attack",
    (
        "m-total",
        "utilisation",
        "status",
        "candidate",
        "governing-alias",
        "face-alias",
        "force",
        "all-conditional",
    ),
)
def test_link_chord_publication_fails_closed_on_hostile_retained_evidence(attack):
    shear = _publication_shear_with_chord()
    links = shear["links"]
    if attack == "m-total":
        links["chord_candidates"][0]["m_total"] = True
    elif attack == "utilisation":
        links["chord_candidates"][0]["util"] = "0.5"
    elif attack == "status":
        links["longitudinal_assessment"]["status"] = []
    elif attack == "candidate":
        links["chord_candidates"] = ["stale"]
    elif attack == "governing-alias":
        links["governing_longitudinal"] = {"valid": True}
    elif attack == "face-alias":
        links["chord"] = {"valid": True}
    elif attack == "force":
        links["longitudinal_shear_force"] += 1.0
    else:
        links["longitudinal_all_conditional"] = False

    assessment = capacity.provided_link_longitudinal_publication_assessment(
        shear
    )

    assert assessment["valid"] is False
    assert assessment["status"] == "NOT ASSESSED"
    assert assessment["util"] is None
    assert assessment["governing"] is None


def test_link_chord_publication_accepts_one_reconciled_governing_face():
    assessment = capacity.provided_link_longitudinal_publication_assessment(
        _publication_shear_with_chord()
    )

    assert assessment["valid"] is True
    assert assessment["status"] == "PASS"
    assert assessment["governing"]["role"] == "shear_axis"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("route", "internal route"),
        ("resistance", 1.0),
        ("utilisation", True),
        ("status", []),
    ),
)
def test_nominal_shear_publication_rejects_stale_retained_alias(field, value):
    shear = _complete_publication_shear(v_ed=30.0, vrd_c=47.59286047)
    inp = _publication_inp(shear)
    _bind_concrete_publication_fixture(shear, inp)
    canonical = presentation.nominal_shear_resistance(
        shear,
        links_selected=True,
        input_payload=inp,
    )
    assert canonical["valid"] is True
    assert canonical["status"] == "PASS"
    assert canonical["resistance"] > 0.0
    shear["nominal_resistance"] = dict(canonical)
    shear["nominal_resistance"][field] = value

    selected = presentation.nominal_shear_resistance(
        shear,
        links_selected=True,
        input_payload=inp,
    )

    assert selected["valid"] is False
    assert selected["route"] is None
    assert selected["resistance"] is None
    assert selected["utilisation"] is None
    assert selected["status"] == "NOT ASSESSED"


def test_nominal_shear_publication_preserves_specific_canonical_failure_reason():
    shear = _complete_publication_shear(v_ed=300.0, vrd_c=47.59286047)
    inp = _publication_inp(shear)
    shear["nominal_resistance"] = presentation.nominal_shear_resistance(
        shear,
        links_selected=True,
        input_payload=inp,
    )
    del shear["links"]["res"]["vrd_s"]

    selected = presentation.nominal_shear_resistance(
        shear,
        links_selected=True,
        input_payload=inp,
    )

    assert selected["valid"] is False
    assert selected["reason"] == "provided-link resistance evidence is unavailable"


def test_shear_screening_does_not_fail_when_selected_links_pass():
    shear = _complete_publication_shear(
        v_ed=120.0,
        vrd_c=100.0,
    )
    inp = _publication_inp(shear, mode="Plastic")
    vrd_c = _bind_concrete_publication_fixture(shear, inp)
    _bind_link_chord_publication_fixture(shear, inp)
    rows = presentation.result_summary_rows(
        inp,
        {"plastic": _plastic(), "shear": shear},
    )
    by_check = {row["check"]: row for row in rows}

    assert by_check["Shear without links"]["status"] == "NOT APPLICABLE"
    assert by_check["Shear without links"]["util"] == pytest.approx(
        120.0 / vrd_c
    )
    assert by_check["Shear with links"]["status"] == "PASS"
    assert presentation.overall_summary_status(rows) == "PASS"
    governing = dict(zip(
        (row["check"] for row in rows),
        presentation.summary_governing_flags(rows),
    ))
    assert governing["Plastic bending"] is True
    assert governing["Shear without links"] is False
    assert governing["Shear with links"] is False


def test_sparse_links_keep_capacity_pass_and_publish_detailing_failure_separately():
    shear = _complete_publication_shear(
        v_ed=80.0,
        vrd_c=103.417,
        asw_over_s=0.0571190303030303,
        z_mm=495.0,
        longitudinal_assessment={
            "status": "NOT APPLICABLE",
            "util": None,
            "reason": "no_longitudinal_chord_action",
        },
    )
    inp = _publication_inp(
        shear,
        mode="Plastic",
        transverse_detailing_on=True,
    )
    vrd_c = _bind_concrete_publication_fixture(shear, inp)
    results = {
        "plastic": _plastic(),
        "shear": shear,
        "transverse_reinforcement": {
            "status": "FAIL",
            "reason": "minimum shear reinforcement is required for this beam",
            "checks": [],
        },
    }
    rows = presentation.result_summary_rows(inp, results)
    by_check = {row["check"]: row for row in rows}

    concrete = by_check["Shear without links"]
    provided_links = by_check["Shear with links"]
    detailing = by_check["Shear/torsion link detailing"]
    assert concrete["status"] == "PASS"
    assert concrete["util"] == pytest.approx(80.0 / vrd_c)
    assert provided_links["status"] == "FAIL"
    expected_link_util = 80.0 / shear["links"]["res"]["vrd"]
    assert provided_links["util"] == pytest.approx(expected_link_util)
    assert (
        f"{100.0 * expected_link_util:.1f} % (non-governing)"
        == provided_links["result"]
    )
    assert "independent non-governing resistance subcheck" in provided_links["note"]
    assert detailing["status"] == "FAIL"
    assert "minimum shear reinforcement" in detailing["note"].lower()
    assert presentation.overall_summary_status(rows) == "FAIL"


def test_concrete_nominal_route_rejects_current_fck_mismatch_value_free():
    shear = _complete_publication_shear(
        v_ed=80.0,
        vrd_c=103.417,
        asw_over_s=0.0571190303030303,
        z_mm=495.0,
    )
    inp = _publication_inp(shear, mode="Plastic")
    _bind_concrete_publication_fixture(shear, inp)
    baseline = presentation.nominal_shear_resistance(
        shear,
        links_selected=True,
        input_payload=inp,
    )
    assert baseline["valid"] is True
    assert baseline["route"] == "concrete"

    stale_input = dict(
        inp,
        concrete=Concrete(fck=80.0, gamma_c=1.45, curve=2),
    )
    selected = presentation.nominal_shear_resistance(
        shear,
        links_selected=True,
        input_payload=stale_input,
    )

    assert presentation.concrete_shear_publication_input_is_current(
        stale_input, shear
    )[0] is False
    assert selected["valid"] is False
    assert selected["status"] == "NOT ASSESSED"
    assert selected["resistance"] is None
    assert selected["utilisation"] is None


def test_current_concrete_context_survives_malformed_links_without_nominal_bypass():
    shear = _complete_publication_shear(
        v_ed=80.0,
        vrd_c=103.417,
        asw_over_s=0.0571190303030303,
        z_mm=495.0,
    )
    inp = _publication_inp(shear, mode="Plastic")
    _bind_concrete_publication_fixture(shear, inp)
    shear["links"] = "poison"

    selected = presentation.nominal_shear_resistance(
        shear,
        links_selected=True,
        input_payload=inp,
    )
    rows = presentation.result_summary_rows(
        inp, {"plastic": _plastic(), "shear": shear}
    )
    by_check = {row["check"]: row for row in rows}

    assert selected["valid"] is False
    assert selected["status"] == "NOT ASSESSED"
    assert presentation.concrete_shear_publication_input_is_current(
        inp, shear
    )[0] is True
    assert by_check["Shear without links"]["status"] == "PASS"
    assert by_check["Shear without links"]["result"] != "-"
    assert by_check["Shear with links"]["status"] == "NOT ASSESSED"
    assert by_check["Shear with links"]["result"] == "-"
    assert presentation.overall_summary_status(rows) == "NOT ASSESSED"


def test_selected_link_nominal_route_fails_closed_on_stale_publication_geometry():
    shear = _complete_publication_shear(
        v_ed=300.0,
        vrd_c=47.59286047,
        asw_over_s=0.5,
    )
    shear["links"]["shear_geometry"]["duct_factor_links"] = "bad"

    rows = presentation.result_summary_rows(
        _publication_inp(shear, mode="Plastic"),
        {"plastic": _plastic(), "shear": shear},
    )
    by_check = {row["check"]: row for row in rows}

    assert by_check["Shear without links"]["status"] == "NOT ASSESSED"
    assert by_check["Shear without links"]["result"] == "-"
    assert by_check["Shear without links"]["util"] is None
    assert by_check["Shear with links"]["status"] == "NOT ASSESSED"
    assert by_check["Shear with links"]["result"] == "-"
    assert by_check["Shear with links"]["util"] is None


@pytest.mark.parametrize("malformed_links", ("poison", True, ["stale"]))
def test_nonmapping_provided_links_fail_closed_in_overview(malformed_links):
    shear = _complete_publication_shear(
        v_ed=30.0,
        vrd_c=47.59286047,
        asw_over_s=0.5,
    )
    shear["links"] = malformed_links

    rows = presentation.result_summary_rows(
        _inp(mode="Plastic", shear_on=True, shear_links=True),
        {"plastic": _plastic(), "shear": shear},
    )
    link_row = next(row for row in rows if row["check"] == "Shear with links")

    assert link_row["status"] == "NOT ASSESSED"
    assert link_row["result"] == "-"
    assert link_row["util"] is None


def test_stale_provided_link_child_does_not_suppress_valid_detailing_row():
    shear = _complete_publication_shear(
        v_ed=30.0,
        vrd_c=47.59286047,
        asw_over_s=0.5,
    )
    inp = _publication_inp(
        shear,
        mode="Plastic",
        transverse_detailing_on=True,
    )
    vrd_c = _bind_concrete_publication_fixture(shear, inp)
    del shear["links"]["res"]["vrd_s"]
    results = {
        "plastic": _plastic(),
        "shear": shear,
        "transverse_reinforcement": {
            "status": "FAIL",
            "reason": "entered link spacing exceeds the permitted limit",
            "checks": [],
        },
    }

    rows = presentation.result_summary_rows(inp, results)
    by_check = {row["check"]: row for row in rows}

    assert by_check["Shear with links"]["status"] == "NOT ASSESSED"
    assert by_check["Shear with links"]["result"] == "-"
    assert by_check["Shear/torsion link detailing"]["status"] == "FAIL"


@pytest.mark.parametrize("attack", ("missing", "empty", "malformed"))
def test_malformed_provided_link_geometry_fails_closed_before_overview_copy(
    attack,
):
    shear = _complete_publication_shear(
        v_ed=30.0,
        vrd_c=47.59286047,
        asw_over_s=0.5,
    )
    if attack == "missing":
        del shear["links"]["shear_geometry"]
    elif attack == "empty":
        shear["links"]["shear_geometry"] = {}
    else:
        shear["links"]["shear_geometry"]["duct_factor_links"] = "bad"

    rows = presentation.result_summary_rows(
        _publication_inp(shear, mode="Plastic"),
        {"plastic": _plastic(), "shear": shear},
    )
    link_row = next(row for row in rows if row["check"] == "Shear with links")

    assert link_row["status"] == "NOT ASSESSED"
    assert link_row["result"] == "-"
    assert link_row["util"] is None


def test_links_governing_resistance_row_is_independent_of_failed_chord():
    shear = _complete_publication_shear(
        v_ed=300.0,
        vrd_c=50.0,
        asw_over_s=5.0,
    )
    inp = _publication_inp(shear, mode="Plastic")
    _bind_concrete_publication_fixture(shear, inp)
    _bind_link_chord_publication_fixture(shear, inp, mx_factor=1.10)

    rows = presentation.result_summary_rows(
        inp,
        {"plastic": _plastic(), "shear": shear},
    )
    by_check = {row["check"]: row for row in rows}

    assert by_check["Shear with links"]["status"] == "PASS"
    assert by_check["Shear with links"]["util"] == pytest.approx(
        300.0 / shear["links"]["res"]["vrd"]
    )
    assert by_check["Shear longitudinal chords"]["status"] == "FAIL"
    assert by_check["Shear longitudinal chords"]["util"] > 1.0
    assert presentation.overall_summary_status(rows) == "FAIL"


def test_unavailable_calculated_link_arm_is_not_assessed_without_a_verdict():
    shear = {
        "v_ed": 120.0,
        "res": {"valid": True, "vrd_c": 100.0},
        "util": 1.20,
        "method": codes.EC2_2005_DKNA.label,
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
    assert link_row["note"] == (
        "Recalculate the applied shear action and resistance before relying on "
        "this result"
    )
    assert "did not converge" not in link_row["note"]
    assert presentation.overall_summary_status(rows) == "NOT ASSESSED"


def test_out_of_range_links_keep_angle_free_concrete_route_and_no_link_verdict():
    reason = "selected strut-angle range is outside the permitted method range"
    applicability = {
        "applicable": False,
        "requested_min": 1.0,
        "requested_max": 3.0,
        "permitted_min": 1.0,
        "permitted_max": 2.5,
    }
    shear = _complete_publication_shear(v_ed=80.0, vrd_c=103.417)
    inp = _publication_inp(
        shear,
        mode="Plastic",
        strut_cot_max=3.0,
    )
    vrd_c = _bind_concrete_publication_fixture(shear, inp)
    shear["links"].update(
        res={
            "valid": False,
            "calculation_state": "NOT ASSESSED",
            "reason": reason,
            "vrd": None,
            "angle_applicability": applicability,
        },
        util=None,
        assessment_reason=reason,
        angle_applicability=applicability,
    )

    rows = presentation.result_summary_rows(
        inp, {"plastic": _plastic(), "shear": shear}
    )
    by_check = {row["check"]: row for row in rows}

    assert by_check["Shear without links"]["status"] == "PASS"
    assert by_check["Shear without links"]["util"] == pytest.approx(
        80.0 / vrd_c
    )
    assert by_check["Shear with links"]["status"] == "NOT ASSESSED"
    assert by_check["Shear with links"]["result"] == "-"
    assert by_check["Shear with links"]["util"] is None
    assert "outside the permitted range" in by_check["Shear with links"]["note"]
    assert presentation.overall_summary_status(rows) == "NOT ASSESSED"


def test_retained_out_of_range_torsion_blocks_stale_torsion_and_combined_values():
    reason = "selected strut-angle range is outside the permitted method range"
    torsion = {
        **_applicable_torsion_evidence(),
        "tube_valid": True,
        "closed_links_present": True,
        "transverse_resistance_assessed": False,
        "full_resistance_assessed": False,
        "valid": False,
        "trd": 999.0,
        "util": 0.01,
        "reason": reason,
        "assessment_reason": reason,
        "angle_applicability": {
            "applicable": False,
            "requested_min": 1.0,
            "requested_max": 3.0,
            "permitted_min": 1.0,
            "permitted_max": 2.5,
        },
    }
    results = {
        "plastic": _plastic(),
        "torsion": torsion,
        "combined": {
            "valid": True,
            "dkna_valid": True,
            "dkna_sum": 0.10,
            "dkna_ok": True,
        },
    }

    rows = _unbound_torsion_summary(
        _inp(
            mode="Plastic",
            torsion_on=True,
            combined_on=True,
            shear_links=True,
        ),
        results,
    )
    torsion_row = next(row for row in rows if row["check"] == "Torsion")
    combined_rows = [row for row in rows if row["view"] == "M-V-T Combined"]

    assert torsion_row["status"] == "NOT ASSESSED"
    assert torsion_row["result"] == "-"
    assert torsion_row["util"] is None
    assert "outside the permitted range" in presentation.result_reason(reason, "torsion")
    assert combined_rows
    assert all(row["status"] == "NOT ASSESSED" for row in combined_rows)
    assert all(row["util"] is None for row in combined_rows)


@pytest.mark.parametrize(
    "retained_blocker",
    [
        pytest.param(None, id="missing"),
        pytest.param(False, id="explicit-false"),
    ],
)
@pytest.mark.parametrize(
    "applicability_evidence",
    (
        "canonical-blocked",
        "missing",
        "non-mapping",
        "contradictory-applicable",
        "incomplete-applicable",
    ),
)
def test_retained_torsion_applicability_poison_is_rejected_before_summary(
    retained_blocker, applicability_evidence,
):
    applicability = capacity.torsion_applicability(
        {
            "torsion_design_basis": capacity.TORSION_DESIGN_EQUILIBRIUM,
            "torsion_member_scope": capacity.TORSION_MEMBER_OPEN,
        },
        40.0,
    )
    torsion = capacity.unassessed_torsion_applicability(
        {
            "applicability": applicability,
            "t_ed": 40.0,
            "t_ed_signed": -40.0,
            "method": codes.EC2_2005_DKNA.label,
        }
    )
    torsion.update(
        tube_valid=True,
        transverse_resistance_assessed=True,
        full_resistance_assessed=True,
        valid=True,
        trd=999.0,
        util=0.01,
        resistance_status="PASS",
    )
    if applicability_evidence == "missing":
        torsion.pop("applicability", None)
    elif applicability_evidence == "non-mapping":
        torsion["applicability"] = []
    elif applicability_evidence == "contradictory-applicable":
        torsion["applicability"] = dict(
            applicability,
            status="APPLICABLE",
            reason=None,
        )
    elif applicability_evidence == "incomplete-applicable":
        torsion["applicability"] = {
            "status": "APPLICABLE",
            "design_basis": capacity.TORSION_DESIGN_EQUILIBRIUM,
            "member_scope": capacity.TORSION_MEMBER_CLOSED,
        }
    if retained_blocker is None:
        torsion.pop("applicability_blocked", None)
    else:
        torsion["applicability_blocked"] = retained_blocker
    inp = _inp(mode='Plastic', torsion_on=True, combined_on=True, shear_links=True)
    out = {'plastic': _plastic(), 'torsion': torsion, 'combined': {'valid': True, 'dkna_valid': True, 'dkna_sum': 0.01, 'dkna_ok': True}}
    # The authored payload has no complete native physical companions.
    # Its root summary must therefore stop at the real currentness guard.
    current, reason = presentation.torsion_publication_component_is_current(inp, out.get("shear"), torsion)
    assert current is False and reason
    rows = presentation.result_summary_rows(inp, out)
    by_check = {row["check"]: row for row in rows}
    assert "Torsion applicability" not in by_check

    assert presentation.torsion_applicability_publication_status(torsion) == "NOT ASSESSED"
    assert by_check["Torsion"]["status"] == "NOT ASSESSED"
    assert by_check["Torsion"]["result"] == "-"
    assert by_check["Torsion"]["util"] is None
    assert "Torsion transverse/strut resistance" not in by_check
    combined_rows = [row for row in rows if row["view"] == "M-V-T Combined"]
    assert combined_rows
    assert all(row["status"] == "NOT ASSESSED" for row in combined_rows)
    assert all(row["util"] is None for row in combined_rows)


@pytest.mark.parametrize(
    "authority_case",
    (
        "stale-blocker",
        "malformed-blocker",
        "lowercase-status",
        "missing-route-entry",
        "wrong-route",
        "stale-reason",
        "text-ted",
        "boolean-ted",
        "nonfinite-ted",
    ),
)
def test_retained_torsion_authority_poison_is_rejected_before_summary(
    authority_case,
):
    applicability = capacity.torsion_applicability(
        {
            "torsion_design_basis": capacity.TORSION_DESIGN_EQUILIBRIUM,
            "torsion_member_scope": capacity.TORSION_MEMBER_CLOSED,
        },
        40.0,
    )
    torsion = {
        "applicability": dict(applicability),
        "applicability_blocked": False,
        "t_ed": 40.0,
        "tube_valid": True,
        "transverse_resistance_assessed": True,
        "full_resistance_assessed": True,
        "closed_links_present": True,
        "valid": True,
        "trd": 999.0,
        "util": 0.01,
        "resistance_status": "PASS",
        "assessment_status": "PASS",
    }
    # This positive establishes declaration eligibility only, not resistance.
    assert presentation.torsion_applicability_publication_status(torsion) == "APPLICABLE"
    if authority_case == "stale-blocker":
        torsion["applicability_blocked"] = True
    elif authority_case == "malformed-blocker":
        torsion["applicability_blocked"] = "False"
    elif authority_case == "lowercase-status":
        torsion["applicability"]["status"] = "applicable"
    elif authority_case == "missing-route-entry":
        torsion["applicability"].pop("full_resistance_route_entered")
    elif authority_case == "wrong-route":
        torsion["applicability"]["route"] = "compatibility residual full resistance"
    elif authority_case == "stale-reason":
        torsion["applicability"]["reason"] = (
            "open or warping-sensitive torsion requires member analysis"
        )
    elif authority_case == "text-ted":
        torsion["t_ed"] = "40"
    elif authority_case == "boolean-ted":
        torsion["t_ed"] = True
    else:
        torsion["t_ed"] = math.nan

    inp = _inp(mode='Plastic', torsion_on=True, combined_on=True, shear_links=True)
    out = {'plastic': _plastic(), 'torsion': torsion, 'combined': {'valid': True, 'dkna_valid': True, 'dkna_sum': 0.01, 'dkna_ok': True}}
    # The authored payload has no complete native physical companions.
    # Its root summary must therefore stop at the real currentness guard.
    current, reason = presentation.torsion_publication_component_is_current(inp, out.get("shear"), torsion)
    assert current is False and reason
    rows = presentation.result_summary_rows(inp, out)
    by_check = {row["check"]: row for row in rows}
    assert "Torsion applicability" not in by_check

    assert presentation.torsion_applicability_publication_status(torsion) == (
        "NOT ASSESSED"
    )
    assert presentation.torsion_applicability_publication_status(torsion) == "NOT ASSESSED"
    assert "not mutually consistent" in presentation.torsion_applicability_note(torsion)
    assert by_check["Torsion"]["status"] == "NOT ASSESSED"
    assert by_check["Torsion"]["result"] == "-"
    assert by_check["Torsion"]["util"] is None
    combined_rows = [row for row in rows if row["view"] == "M-V-T Combined"]
    assert combined_rows
    assert all(row["status"] == "NOT ASSESSED" for row in combined_rows)
    assert all(row["util"] is None for row in combined_rows)


def test_2023_axial_compression_guidance_governs_the_links_overview_note():
    reason = (
        "2023 axial-compression applicability conditions were not demonstrated"
    )
    shear = {
        "v_ed": 50.0,
        "res": {"valid": True, "vrd_c": 100.0},
        "util": 0.50,
        "method": codes.EC2_2023.label,
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
    assert link_row["note"] == (
        "Recalculate the applied shear action and resistance before relying on "
        "this result"
    )
    assert "Net axial compression" not in link_row["note"]
    assert "Annex G" not in link_row["note"]
    assert "Complete both required longitudinal chord checks" not in link_row["note"]


def test_shear_without_links_retains_concrete_screening_verdict():
    shear = _complete_publication_shear(v_ed=120.0, vrd_c=100.0)
    inp = _publication_inp(
        shear,
        mode="Plastic",
        shear_links=False,
    )
    _bind_concrete_publication_fixture(shear, inp)
    shear.pop("links")
    rows = presentation.result_summary_rows(
        inp,
        {"plastic": _plastic(), "shear": shear},
    )
    by_check = {row["check"]: row for row in rows}

    assert by_check["Shear without links"]["status"] == "FAIL"
    assert presentation.overall_summary_status(rows) == "FAIL"


def test_retained_torsion_without_full_resistance_is_not_assessed_on_every_summary():
    torsion = {
        **_applicable_torsion_evidence(),
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
    rows = _unbound_torsion_summary(
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
    assert presentation.result_reason(torsion["assessment_reason"], "torsion") == (
        "Closed torsion links are required before the transverse/strut "
        "resistance component can be assessed"
    )

    combined_row = by_check["Combined M-V-T supported components"]
    # The original retained payload contains no Combined calculation.
    assert combined_row["status"] == "NOT RUN"
    assert combined_row["util"] is None
    assert combined_row["note"] == "Calculate required"


def _torsion_longitudinal_result(*, status="NOT ASSESSED", ratio=0.47):
    reason = (
        "longitudinal_torsion_reinforcement_insufficient"
        if status == "FAIL"
        else "longitudinal_torsion_reinforcement_not_verified"
    )
    required_asl = 1176.672
    reference_fyd = 416.67
    provided_equivalent_area = required_asl / ratio
    required_force = required_asl * reference_fyd / 1000.0
    provided_force = provided_equivalent_area * reference_fyd / 1000.0
    return {
        **_applicable_torsion_evidence(),
        "tube_valid": True,
        "closed_links_present": True,
        "transverse_resistance_assessed": True,
        "full_resistance_assessed": True,
        "valid": True,
        "t_ed": 40.0,
        "asl_req": required_asl,
        "subdivided": False,
        "subtubes": None,
        "trd": 76.402,
        "util": 0.523548,
        "governs": "stirrups (TRd,s)",
        "resistance_status": "PASS",
        "assessment_status": status,
        "overall_reason": reason,
        "longitudinal_assessment": {
            "status": status,
            "ok": False if status == "FAIL" else None,
            "reason": reason,
            "required_asl_mm2": required_asl,
            "required_by_tube_mm2": (required_asl,),
            "required_design_force_kn": required_force,
            "provided_gross_area_mm2": provided_equivalent_area,
            "provided_design_force_kn": provided_force,
            "provided_equivalent_area_mm2": provided_equivalent_area,
            "reference_fyd_mpa": reference_fyd,
            "demand_ratio": ratio,
            "area_sufficient": status != "FAIL",
        },
    }


@pytest.mark.parametrize(
    ("status", "ratio"),
    [("NOT ASSESSED", 0.468), ("FAIL", 1.176672)],
)
def test_retained_torsion_summary_separates_component_and_longitudinal_status(
    status,
    ratio,
):
    torsion = _torsion_longitudinal_result(status=status, ratio=ratio)
    rows = _unbound_torsion_summary(
        _inp(mode="Plastic", torsion_on=True, shear_links=True),
        {"plastic": _plastic(), "torsion": torsion},
    )
    by_check = {row["check"]: row for row in rows}

    assert by_check["Torsion"]["status"] == "NOT ASSESSED"
    assert by_check["Torsion"]["util"] is None
    # These rounded scalars remain retained units; native bar-size cases
    # separately prove the actual component and longitudinal display rows.
    assert torsion["resistance_status"] == "PASS"
    assert torsion["util"] == pytest.approx(0.523548)
    longitudinal = presentation.torsion_longitudinal_assessment(torsion)
    assert longitudinal["evidence_consistent"] is True
    assert longitudinal["status"] == status
    assert longitudinal["demand_ratio"] == pytest.approx(ratio)
    assert longitudinal["required_asl_mm2"] == pytest.approx(1176.672)
    assert presentation.torsion_assessment_status(torsion) == status


def test_retained_torsion_summary_rebuilds_formula_628_before_publishing_pass():
    torsion = _torsion_longitudinal_result(status="NOT ASSESSED", ratio=0.50)
    torsion.update(
        t_ed=0.0,
        asl_req=0.0,
        subdivided=True,
        subtubes=(
            {"asl_req": 0.0, "t_ed": 10.0},
            {"asl_req": 0.0, "t_ed": 20.0},
        ),
        applicability=_applicable_torsion_evidence(0.0)["applicability"],
        assessment_status="PASS",
        assessment_ok=True,
        overall_reason="no_longitudinal_torsion_demand",
    )
    torsion["longitudinal_assessment"].update(
        status="PASS",
        ok=True,
        reason="no_longitudinal_torsion_demand",
        required_asl_mm2=0.0,
        required_by_tube_mm2=(0.0, 0.0),
        required_design_force_kn=0.0,
        provided_design_force_kn=100.0,
        provided_gross_area_mm2=250.0,
        provided_equivalent_area_mm2=250.0,
        reference_fyd_mpa=400.0,
        demand_ratio=0.0,
        area_sufficient=True,
    )

    rows = _unbound_torsion_summary(
        _inp(mode="Plastic", torsion_on=True, shear_links=True),
        {"plastic": _plastic(), "torsion": torsion},
    )
    by_check = {row["check"]: row for row in rows}

    assert presentation.torsion_assessment_status(torsion) == "NOT ASSESSED"
    sanitized = presentation.torsion_longitudinal_assessment(torsion)
    assert sanitized["evidence_consistent"] is False
    assert sanitized["status"] == "NOT ASSESSED"
    assert by_check["Torsion"]["status"] == "NOT ASSESSED"
    assert "Torsion longitudinal reinforcement" not in by_check


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
    assert presentation.combined_dkna_status(combined) == status
    _assert_unbound_combined_is_not_published(
        _inp(
            mode="Plastic",
            torsion_on=True,
            combined_on=True,
            shear_links=True,
        ),
        combined,
    )


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
            "status": "FAIL",
            "ok": False,
            "util": 1.25,
            "axis": "x",
            "tension_low": True,
            "conditional": True,
            "biaxial": False,
            "off_not_evaluated": None,
            "m_ed": 80.0,
            "mv": 5.0,
            "mt": 40.0,
            "m_total": 125.0,
            "m_rd": 100.0,
            "ftd_v": 20.0,
            "ftd_t": 320.0,
            "z": 0.25,
            "capped": False,
        },
        "governing_longitudinal": {
            "valid": True,
            "status": "FAIL",
            "ok": False,
            "util": 1.25,
            "axis": "x",
            "tension_low": True,
            "conditional": True,
            "biaxial": False,
            "off_not_evaluated": None,
            "m_ed": 80.0,
            "mv": 5.0,
            "mt": 40.0,
            "m_total": 125.0,
            "m_rd": 100.0,
            "ftd_v": 20.0,
            "ftd_t": 320.0,
            "z": 0.25,
            "capped": False,
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


def _assert_unbound_combined_is_not_published(inp, combined, *, plastic=None):
    """Synthetic component payloads cannot act as current root evidence."""

    rows = presentation.result_summary_rows(
        inp,
        {"plastic": plastic or _plastic(), "combined": combined},
    )
    combined_rows = [row for row in rows if row["view"] == "M-V-T Combined"]
    assert len(combined_rows) == 1
    row = combined_rows[0]
    assert row["status"] == "NOT ASSESSED"
    assert row["result"] == "-"
    assert row["util"] is None
    assert row["note"] == (
        "Combined component evidence is not current. Recalculate the shear, "
        "torsion and M-V-T checks."
    )
    return rows


def test_pub_h01_exact_longitudinal_failure_feeds_component_formatter():
    direct = {
        "valid": True,
        "status": "FAIL",
        "ok": False,
        "axis": "x",
        "tension_low": True,
        "conditional": True,
        "biaxial": False,
        "off_util": 0.0,
        "off_not_evaluated": None,
        "m_ed": 80.0,
        "mv": 4.213620,
        "mt": 39.711696,
        "m_total": 123.925316,
        "m_rd": 100.0,
        "ftd_v": 17.34,
        "ftd_t": 326.8452380952381,
        "z": 0.243,
        "util": 1.2392531643,
        "capped": False,
    }


    combined = {
        "valid": True,
        "method": codes.EC2_2005.label,
        "longitudinal": direct,
        "torsion_longitudinal_assessment": {
            "status": "NOT ASSESSED",
            "ok": None,
            "reason": "longitudinal_torsion_reinforcement_not_verified",
            "demand_ratio": 0.50,
        },
    }
    canonical = capacity.combined_longitudinal_assessment(combined)
    combined["overall_longitudinal_assessment"] = canonical

    component = next(
        item
        for item in presentation.combined_physical_components(combined)
        if item["key"] == "longitudinal"
    )
    assert component["assessment"] is canonical
    assert component["governing"] is direct
    assert component["status"] == "FAIL"
    assert component["util"] == pytest.approx(1.2392531643)
    _assert_unbound_combined_is_not_published(
        {"combined_on": True, "combined_method": codes.EC2_2005.label},
        combined,
        plastic={},
    )


def test_stale_combined_cannot_bypass_unassessed_torsion_prerequisite():
    torsion = {
        **_applicable_torsion_evidence(),
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


def test_retained_torsion_geometry_failure_remains_distinct_from_missing_links():
    rows = _unbound_torsion_summary(
        _inp(mode="Plastic", torsion_on=True, shear_links=True),
        {
            "plastic": _plastic(),
            "torsion": {
                **_applicable_torsion_evidence(),
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

    assert torsion_row["status"] == "NOT ASSESSED"
    assert presentation.result_reason("compound outline requires subdivision", "torsion") == (
        "The compound outline requires subdivision before torsion can be assessed"
    )


def test_retained_torsion_wall_evidence_failure_is_not_assessed_without_stale_value():
    raw_reason = "torsion wall reinforcement mapping is incomplete"
    rows = _unbound_torsion_summary(
        _inp(mode="Plastic", torsion_on=True, shear_links=True),
        {
            "plastic": _plastic(),
            "torsion": {
                **_applicable_torsion_evidence(),
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
    assert presentation.result_reason(raw_reason, "torsion") == (
        "Torsion is not assessed because longitudinal reinforcement has not "
        "been established for every equivalent-tube wall"
    )
    assert raw_reason not in torsion_row["note"]


def test_biaxial_shear_summary_keeps_directional_verdicts_and_limitation():
    seed = _complete_publication_shear(v_ed=60.0, vrd_c=100.0)
    inp = _publication_inp(
        seed,
        mode="Plastic",
        shear_links=False,
        shear_Vx=60.0,
        shear_Vy=60.0,
        shear_face_x="negative",
        shear_face_y="negative",
    )
    inp["bars"] = [
        (-0.10, -0.10, 500.0),
        (0.10, -0.10, 500.0),
        (0.10, 0.10, 500.0),
        (-0.10, 0.10, 500.0),
    ]
    contexts = capacity.build_directional_shear_contexts(inp, 0.0, 0.0)
    directions = {}
    specs = capacity.shear_direction_specs(inp)
    for component in ("vx", "vy"):
        child = dict(contexts[component]["candidates"][0][0])
        nominal = capacity.select_nominal_shear_resistance(
            child, links_selected=False
        )
        child.update(
            signed_v_ed=specs[component]["signed_v_ed"],
            nominal_resistance=asdict(nominal),
            resistance_status=nominal.status,
            assessment_status=nominal.status,
            assessment_ok=nominal.ok,
        )
        face = {
            "tension_low": True,
            "shear_status": nominal.status,
            "shear_metric": nominal.utilisation,
            "torsion_status": "NOT RUN",
            "torsion_metric": 0.0,
            "min_reinf_status": "NOT RUN",
            "min_reinf_metric": 0.0,
            "combined_status": "NOT RUN",
            "combined_metric": 0.0,
            "shear": child,
            "torsion": None,
            "combined": None,
        }
        directions[component] = dict(
            child,
            face_mode="negative",
            both_faces_evaluated=False,
            governing_face="negative",
            associated_moment=specs[component]["moment"],
            associated_moment_origin=specs[component]["moment_origin"],
            status=nominal.status,
            governing_domains={
                "shear": {
                    "face": "negative",
                    "cot": None,
                    "status": nominal.status,
                    "util": nominal.utilisation,
                }
            },
            face_candidates=[face],
        )
    aggregate = {
        "directions": directions,
        "active_directions": ["vx", "vy"],
        "biaxial": True,
    }

    rows = presentation.result_summary_rows(
        inp,
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
    assert presentation.combined_dkna_status(
        combined["directions"]["vx"]
    ) == "PASS"
    assert presentation.combined_dkna_status(
        combined["directions"]["vy"]
    ) == "FAIL"
    _assert_unbound_combined_is_not_published(
        _inp(mode="Plastic", combined_on=True),
        combined,
    )


def test_base_en_combined_summary_publishes_only_supported_physical_checks():
    def direction(concrete, stirrup, longitudinal):
        candidate = _complete_longitudinal_candidate(longitudinal)
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
            "longitudinal": candidate,
            "governing_longitudinal": candidate,
            "longitudinal_all_conditional": True,
            "longitudinal_assessment": {
                "status": "PASS" if longitudinal <= 1.0 else "FAIL",
                "ok": longitudinal <= 1.0,
                "util": longitudinal,
                "coverage_complete": True,
                "governing": candidate,
            },
            "torsion_longitudinal_assessment": _zero_formula_628_assessment(),
        }

    combined = {
        "biaxial": True,
        "method": codes.EC2_2005.label,
        "directions": {
            "vx": direction(0.50, 0.60, 0.70),
            "vy": direction(0.80, 0.90, 1.10),
        },
    }
    direction_items = presentation.base_en_combined_direction_items(combined)
    assert direction_items is not None
    by_direction = dict(direction_items)
    vy_components = presentation.combined_physical_components(
        by_direction["vy"]
    )
    assert next(
        item for item in vy_components if item["key"] == "longitudinal"
    )["status"] == "FAIL"
    assert all(
        presentation.combined_uses_dkna(item) is False
        for item in by_direction.values()
    )
    _assert_unbound_combined_is_not_published(
        _inp(
            mode="Plastic",
            combined_on=True,
            combined_method=codes.EC2_2005.label,
        ),
        combined,
    )


def test_base_en_incomplete_case_cannot_displace_governing_worked_case():
    def combined_result(util, longitudinal_status):
        longitudinal = _complete_longitudinal_candidate(util - 0.05)
        assessed = longitudinal_status in {"PASS", "FAIL"}
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
                "ok": (longitudinal_status == "PASS") if assessed else None,
                "util": (util - 0.05) if assessed else None,
                "coverage_complete": assessed,
                "governing": longitudinal,
            },
            "t_ed": 0.0,
            "asl_torsion": 0.0,
            "torsion_subdivided": False,
            "torsion_subtubes": None,
            "torsion_longitudinal_assessment": (
                _zero_formula_628_assessment()
            ),
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

    _assert_unbound_combined_is_not_published(
        _inp(
            mode="Plastic",
            combined_on=True,
            combined_method=codes.EC2_2005.label,
        ),
        combined,
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

    _assert_unbound_combined_is_not_published(
        _inp(
            mode="Plastic",
            combined_on=True,
            combined_method=codes.EC2_2005.label,
        ),
        combined,
    )


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

    assert presentation.combined_dkna_screen_label(combined) == (
        "max(N+M+T, N+V+T)"
    )
    assert all(
        presentation.combined_dkna_status(item) == "NOT ASSESSED"
        for item in combined["directions"].values()
    )
    rows = _assert_unbound_combined_is_not_published(
        _inp(mode="Plastic", combined_on=True),
        combined,
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
        "check_minimum_reinforcement": False,
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
    entries = [
        _plastic_case_entry("PL-A", 0.60),
        _plastic_case_entry("PL-B", 0.90),
    ]
    inp["plastic_cases"] = [entry["actions"] for entry in entries]
    for entry in entries:
        entry["signature"] = case_analysis.case_signature(
            entry["actions"],
            load_cases.PLASTIC_TABLE_KEY,
            inp,
        )
    rows = presentation.multi_case_summary_rows(
        inp,
        {"plastic_cases": entries},
    )

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
    entry = _plastic_case_entry("PL-ZERO", 0.50)
    inp["plastic_cases"] = [entry["actions"]]
    entry["signature"] = case_analysis.case_signature(
        entry["actions"],
        load_cases.PLASTIC_TABLE_KEY,
        inp,
    )
    rows = presentation.multi_case_summary_rows(
        inp,
        {"plastic_cases": [entry]},
    )
    by_check = {row["check"]: row for row in rows}

    assert by_check["Shear Vx"]["status"] == "NOT APPLICABLE"
    assert by_check["Shear Vy"]["result"] == "Vy,Ed = 0"
    assert by_check["Torsion"]["status"] == "NOT APPLICABLE"
    assert by_check["Combined M-V-T"]["result"] == "Vx,Ed = Vy,Ed = TEd = 0"


def test_multi_case_summary_withholds_every_changed_action_result_value():
    retained = _plastic_case_entry(
        "PL-STALE",
        0.50,
        vy=50.0,
        t=40.0,
    )
    retained["results"].update(
        shear=_complete_publication_shear(v_ed=50.0, vrd_c=100.0),
        torsion={
            **_applicable_torsion_evidence(40.0),
            "valid": True,
            "util": 0.40,
            "assessment_status": "PASS",
        },
        combined={
            "valid": True,
            "method": codes.EC2_2005_DKNA.label,
            "dkna_valid": True,
            "dkna_sum": 0.80,
            "dkna_status": "PASS",
        },
    )
    current_action = dict(retained["actions"], t_ed_knm=41.0)
    inp = _inp(
        mode="Plastic",
        plastic_cases=[current_action],
        elastic_cases=[],
        shear_on=True,
        torsion_on=True,
        combined_on=True,
        shear_links=True,
    )
    old_inp = dict(inp, plastic_cases=[retained["actions"]])
    retained["signature"] = case_analysis.case_signature(
        retained["actions"],
        load_cases.PLASTIC_TABLE_KEY,
        old_inp,
    )

    rows = presentation.multi_case_summary_rows(
        inp,
        {"plastic_cases": [retained]},
    )
    derived = [
        row for row in rows
        if not row.get("overview_placeholder")
    ]

    assert derived
    assert {row["case"] for row in derived} == {"PL-STALE"}
    assert {row["status"] for row in derived} == {"NOT ASSESSED"}
    assert all(
        row["result"] == "-" and row["util"] is None
        for row in derived
    )
    assert all(
        row["note"] == "Recalculate this action set before relying on the result"
        for row in derived
    )


def test_multi_case_summary_replaces_removed_result_case_with_current_not_run():
    old = _plastic_case_entry("PL-OLD", 0.75)
    current = _plastic_case_entry("PL-NEW", 0.0)["actions"]
    inp = _inp(
        mode="Plastic",
        plastic_cases=[current],
        elastic_cases=[],
        shear_on=False,
        torsion_on=False,
        combined_on=False,
    )

    rows = presentation.multi_case_summary_rows(
        inp,
        {"plastic_cases": [old]},
    )

    assert rows
    assert {row["case"] for row in rows} == {"PL-NEW"}
    assert {row["status"] for row in rows} == {"NOT RUN"}
    assert "PL-OLD" not in repr(rows)


def test_multi_case_summary_keeps_fresh_named_case_not_run():
    current = _plastic_case_entry("PL-FRESH", 0.0)["actions"]
    inp = _inp(
        mode="Plastic",
        plastic_cases=[current],
        elastic_cases=[],
        shear_on=False,
        torsion_on=False,
        combined_on=False,
    )

    rows = presentation.multi_case_summary_rows(inp, {})

    assert len(rows) == 1
    assert rows[0]["case"] == "PL-FRESH"
    assert rows[0]["status"] == "NOT RUN"
    assert rows[0]["result"] == "-"


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
            "vx_face": "auto",
            "vy_face": "auto",
            "t_ed_knm": 0.0,
            "check_minimum_reinforcement": False,
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
    inp["plastic_cases"] = [first["actions"], second["actions"]]
    for entry in (first, second):
        entry["signature"] = case_analysis.case_signature(
            entry["actions"],
            load_cases.PLASTIC_TABLE_KEY,
            inp,
        )
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



@presentation.publication_calculation_scope()
def _exercise_native_torsion_summary_variants(bundle, variants, mutate, tmp_path, family):
    """Prove root-declaration reconciliation without altering native face data."""
    import json

    inp, out = copy.deepcopy(bundle)
    original = pickle.dumps((inp, out))
    torsion = out["torsion"]
    assert out["plastic_cases"][0]["results"]["torsion"] is torsion
    original_signature = tuple(out["plastic_cases"][0]["signature"])
    assert presentation.torsion_publication_component_is_current(inp, out["shear"], torsion) == (True, None)
    assert presentation.torsion_applicability_publication_status(torsion) == "APPLICABLE"
    contexts = [item for item in presentation._worked_case_contexts(inp, out, "torsion")
                if item[0] == "PL-01"]
    assert len(contexts) == 1 and contexts[0][3] is True
    assert contexts[0][2]["torsion"] is torsion
    case_inp, case_out = contexts[0][1:3]
    assert presentation.torsion_publication_component_is_current(
        case_inp, case_out["shear"], case_out["torsion"],
    ) == (True, None)
    assert presentation.combined_publication_evidence_is_current(inp, out) == (True, None)
    assert presentation.combined_publication_evidence_is_current(case_inp, case_out) == (True, None)
    assert presentation.combined_bending_assessment_blocker(out, inp) is None
    assert presentation.combined_bending_assessment_blocker(case_out, case_inp) is None
    positive = presentation.multi_case_summary_rows(inp, out)
    applicability = [row for row in positive
                     if str(row["overview_key"]).startswith("torsion:applicability:")]
    assert len(applicability) == 1
    assert applicability[0]["check"] == "Torsion applicability"
    assert applicability[0]["status"] == applicability[0]["result"] == "APPLICABLE"
    assert applicability[0]["case"] == "PL-01"
    assert applicability[0]["util"] is None
    assert applicability[0]["criterion"] == "Design basis and member scope"
    assert applicability[0]["note"] == (
        "Equilibrium torsion is selected; the entered TEd must be resisted by the section"
    )
    resistance = [row for row in positive if row["overview_key"] == "torsion:resistance"]
    assert len(resistance) == 1 and resistance[0]["case"] == "PL-01"
    assert resistance[0]["status"] in {"PASS", "FAIL"}
    assert resistance[0]["util"] is not None and resistance[0]["result"] != "-"
    positive_combined = [row for row in positive if str(row["overview_key"]).startswith("combined")]
    assert positive_combined and all(row["case"] == "PL-01" for row in positive_combined)
    assert any(row["status"] in {"PASS", "FAIL"} and row["util"] is not None
               and row["result"] != "-" for row in positive_combined)
    untouched_rows = [row for row in positive
                      if not str(row["overview_key"]).startswith(("torsion", "combined"))]
    assert any(row["status"] in {"PASS", "FAIL"} and row["util"] is not None
               and row["result"] != "-" for row in untouched_rows)
    evidence = []
    for variant in variants:
        poisoned = copy.deepcopy(out)
        candidate = poisoned["torsion"]
        assert poisoned["plastic_cases"][0]["results"]["torsion"] is candidate
        shear_before = pickle.dumps(poisoned["shear"])
        combined_before = pickle.dumps(poisoned["combined"])
        primary_before = pickle.dumps(candidate["primary"])
        other_fields = {key: pickle.dumps(value) for key, value in candidate.items()
                        if key not in {"applicability", "applicability_blocked", "t_ed"}}
        candidate["applicability"] = copy.deepcopy(candidate["applicability"])
        mutate(candidate, variant)
        assert pickle.dumps(poisoned["shear"]) == shear_before, variant
        assert pickle.dumps(poisoned["combined"]) == combined_before, variant
        assert pickle.dumps(candidate["primary"]) == primary_before, variant
        assert all(pickle.dumps(candidate[key]) == value for key, value in other_fields.items()), variant
        assert tuple(poisoned["plastic_cases"][0]["signature"]) == original_signature
        frozen_poisoned = pickle.dumps(poisoned)
        assert presentation.torsion_applicability_publication_status(candidate) == "NOT ASSESSED", variant
        current, reason = presentation.torsion_publication_component_is_current(inp, poisoned["shear"], candidate)
        assert current is False, variant
        poisoned_contexts = [item for item in presentation._worked_case_contexts(inp, poisoned, "torsion")
                             if item[0] == "PL-01"]
        assert len(poisoned_contexts) == 1 and poisoned_contexts[0][3] is True
        poisoned_case_inp, poisoned_case_out = poisoned_contexts[0][1:3]
        assert poisoned_case_out["torsion"] is candidate
        assert presentation.torsion_publication_component_is_current(
            poisoned_case_inp, poisoned_case_out["shear"], candidate,
        )[0] is False, variant
        # Combined still owns unchanged native physical-face arithmetic.
        # Its publication must nevertheless fail the root torsion prerequisite.
        assert presentation.combined_publication_evidence_is_current(inp, poisoned) == (True, None), variant
        assert presentation.combined_publication_evidence_is_current(poisoned_case_inp, poisoned_case_out) == (True, None), variant
        blocker = "Torsion prerequisite is not assessed: " + presentation.torsion_applicability_note(candidate)
        assert presentation.combined_bending_assessment_blocker(poisoned, inp) == blocker, variant
        assert presentation.combined_bending_assessment_blocker(poisoned_case_out, poisoned_case_inp) == blocker, variant
        negative = presentation.multi_case_summary_rows(inp, poisoned)
        assert [row for row in negative
                if not str(row["overview_key"]).startswith(("torsion", "combined"))] == untouched_rows, variant
        blocked = [row for row in negative if str(row["overview_key"]).startswith(("torsion", "combined"))]
        assert any(row["overview_key"] == "torsion" for row in blocked), variant
        assert any(str(row["overview_key"]).startswith("combined") for row in blocked), variant
        assert all(row["status"] == "NOT ASSESSED" and row["util"] is None
                   and row["result"] == "-" and row["case"] == "PL-01" for row in blocked), variant
        assert not any(str(row["overview_key"]).startswith("torsion:applicability:") for row in negative), variant
        assert not any(row["overview_key"] == "torsion:resistance" for row in negative), variant
        assert all(row["note"] == blocker for row in blocked
                   if str(row["overview_key"]).startswith("combined")), variant
        assert pickle.dumps(poisoned) == frozen_poisoned, variant
        evidence.append({"variant": variant, "current": current, "reason": reason,
                         "combined_current": True, "combined_blocker": blocker,
                         "blocked_rows": [{key: row[key] for key in ("overview_key", "check", "case", "status", "result", "util")}
                                          for row in blocked]})
    assert len(evidence) == len(variants)
    assert pickle.dumps((inp, out)) == original
    (tmp_path / f"native-torsion-summary-{family}.json").write_text(
        json.dumps({"family": family, "positive_rows": positive, "variants": evidence}, indent=2) + "\n",
        encoding="utf-8",
    )


@pytest.mark.xdist_group("native-member-report")
def test_native_torsion_summary_rejects_scope_declaration_variants(native_member_report_cases, tmp_path):
    variants = [(kind, flag) for kind in (
        "canonical-blocked", "missing", "non-mapping", "contradictory-applicable", "incomplete-applicable",
    ) for flag in (None, False)]
    assert len(variants) == 10

    def mutate(torsion, variant):
        kind, flag = variant
        applicability = capacity.torsion_applicability(
            {"torsion_design_basis": capacity.TORSION_DESIGN_EQUILIBRIUM,
             "torsion_member_scope": capacity.TORSION_MEMBER_OPEN},
            torsion["t_ed"],
        )
        torsion["applicability"] = applicability
        if kind == "missing":
            torsion.pop("applicability")
        elif kind == "non-mapping":
            torsion["applicability"] = []
        elif kind == "contradictory-applicable":
            torsion["applicability"] = dict(applicability, status="APPLICABLE", reason=None)
        elif kind == "incomplete-applicable":
            torsion["applicability"] = {
                "status": "APPLICABLE", "design_basis": capacity.TORSION_DESIGN_EQUILIBRIUM,
                "member_scope": capacity.TORSION_MEMBER_CLOSED,
            }
        if flag is None:
            torsion.pop("applicability_blocked", None)
        else:
            torsion["applicability_blocked"] = flag

    _exercise_native_torsion_summary_variants(native_member_report_cases["two-face"], variants, mutate, tmp_path, "scope")


@pytest.mark.xdist_group("native-member-report")
def test_native_torsion_summary_rejects_route_declaration_variants(native_member_report_cases, tmp_path):
    variants = ("stale-blocker", "malformed-blocker", "lowercase-status", "missing-route-entry", "wrong-route",
                "stale-reason", "text-ted", "boolean-ted", "nonfinite-ted")
    assert len(variants) == 9

    def mutate(torsion, variant):
        if variant == "stale-blocker":
            torsion["applicability_blocked"] = True
        elif variant == "malformed-blocker":
            torsion["applicability_blocked"] = "False"
        elif variant == "lowercase-status":
            torsion["applicability"]["status"] = "applicable"
        elif variant == "missing-route-entry":
            torsion["applicability"].pop("full_resistance_route_entered")
        elif variant == "wrong-route":
            torsion["applicability"]["route"] = "compatibility residual full resistance"
        elif variant == "stale-reason":
            torsion["applicability"]["reason"] = "open or warping-sensitive torsion requires member analysis"
        elif variant == "text-ted":
            torsion["t_ed"] = str(torsion["t_ed"])
        elif variant == "boolean-ted":
            torsion["t_ed"] = True
        else:
            torsion["t_ed"] = math.nan

    _exercise_native_torsion_summary_variants(native_member_report_cases["two-face"], variants, mutate, tmp_path, "route")


def _unbound_torsion_summary(inp, results):
    """Exercise the real early guard on each untouched incomplete input."""
    before = pickle.dumps((inp, results), protocol=pickle.HIGHEST_PROTOCOL)
    current, reason = presentation.torsion_publication_component_is_current(
        inp, results.get("shear"), results["torsion"],
    )
    assert (current, reason) == (False, "torsion result evidence is unavailable")
    rows = presentation.result_summary_rows(inp, results)
    by_check = {row["check"]: row for row in rows}
    root = by_check["Torsion"]
    assert (root["status"], root["result"], root["criterion"], root["util"]) == (
        "NOT ASSESSED", "-", "-", None,
    )
    assert root["note"] == presentation.result_reason(reason, "torsion")
    assert not {
        "Torsion applicability", "Torsion transverse/strut resistance",
        "Torsion longitudinal reinforcement",
    }.intersection(by_check)
    assert pickle.dumps((inp, results), protocol=pickle.HIGHEST_PROTOCOL) == before
    return rows
