"""Focused PR-05 Danish bridge rule, oracle, and adversarial tests."""

from __future__ import annotations

import ast
import json
import pathlib
import copy
import sys
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from sector import bridge, capacity, codes, conformance, danish_bridge, sls
from tools import pr05_dk_bridge_oracle as oracle


ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import bridge_inputs  # noqa: E402
import bridge_analysis  # noqa: E402
import fatigue_analysis  # noqa: E402
import fatigue_inputs  # noqa: E402
import project_io  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "pr05_dk_bridge_decisions.json"


ASSETS = {
    "road": danish_bridge.ASSET_ROAD,
    "footbridge": danish_bridge.ASSET_FOOT,
    "railway": danish_bridge.ASSET_RAIL,
    "other": danish_bridge.ASSET_OTHER,
}
ENVIRONMENTS = {
    "aggressive": danish_bridge.ENVIRONMENT_AGGRESSIVE,
    "extra_aggressive": danish_bridge.ENVIRONMENT_EXTRA_AGGRESSIVE,
}
MEMBERS = {
    "nonprestressed": danish_bridge.MEMBER_NONPRESTRESSED,
    "prestressed": danish_bridge.MEMBER_PRESTRESSED,
}


def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _criteria(case):
    prestressed = case["member_class"] == "prestressed"
    return sls.crack_criteria_from_inputs({
        "sls_criterion_mode": sls.CRITERION_MODE_STANDARD,
        "sls_edition": sls.EDITION_BRIDGE_DK_2015,
        "sls_code": bridge.EN1992_2_DK_NA,
        "sls_member": "Beam",
        "sls_prestress_class": (
            sls.PRESTRESS_BONDED
            if prestressed
            else sls.PRESTRESS_REINFORCED_UNBONDED
        ),
        "sls_check_durability": True,
        "sls_check_appearance": False,
        "sls_limit_source": "DB-SLS-05",
        "bridge_asset_class": ASSETS[case["asset_class"]],
        "bridge_environment_class": ENVIRONMENTS[case["environment"]],
        "sls_dk_member_class": MEMBERS[case["member_class"]],
        "sls_has_tendons": prestressed,
    })


def _production_route(case):
    output = []
    for criterion in _criteria(case):
        assert criterion["configuration_status"] == "READY"
        output.append((
            (
                "decompression"
                if criterion["kind"] == sls.CRITERION_DECOMPRESSION
                else "width"
            ),
            criterion["required_combination"],
            criterion["limit_mm"],
        ))
    return tuple(output)


def _response_contexts():
    return {
        "QP": {
            "combination": sls.COMBINATION_QUASI_PERMANENT,
            "duration": "long",
            "response_id": "dk-qp",
            "provenance": "explicit Danish QP mapping",
            "solver_provenance": {"state": "dk-qp"},
        },
        "Frequent": {
            "combination": sls.COMBINATION_FREQUENT,
            "duration": "short",
            "response_id": "dk-frequent",
            "provenance": "explicit Danish frequent mapping",
            "solver_provenance": {"state": "dk-frequent"},
        },
    }


def _mapping_scope(contexts):
    return [
        {
            "combination": context["combination"],
            "duration": context["duration"],
            "response": name,
            "response_id": context["response_id"],
            "elastic_case": "dk-elastic-1",
            "state": context["response_id"],
            "provenance": context["provenance"],
            "solver_provenance": context["solver_provenance"],
        }
        for name, context in contexts.items()
    ]


def _dk_crack_results(width=0.29):
    case = {
        "asset_class": "road",
        "member_class": "nonprestressed",
        "environment": "aggressive",
    }
    contexts = _response_contexts()
    responses = {
        "QP": {"wk": 0.01, "element_id": "bar 1"},
        "Frequent": {"wk": width, "element_id": "bar 1"},
    }
    assessment = sls.crack_assessment(
        responses,
        valid=True,
        criteria=_criteria(case),
        response_contexts=contexts,
        response_mapping_scope=_mapping_scope(contexts),
    )
    return {
        "elastic_cases": [{
            "name": "Danish SLS",
            "results": {
                "elastic": {
                    "show_cw": True,
                    "crack_assessment": assessment,
                    "crack_responses": responses,
                    "crack_response_contexts": contexts,
                    "crack_response_mapping_scope": _mapping_scope(
                        contexts
                    ),
                },
            },
        }],
    }


def _dk_crack_control_record(results):
    elastic = results["elastic_cases"][0]["results"]["elastic"]
    assessment = elastic["crack_assessment"]
    informational = set(assessment.get("informational_responses") or ())
    return sls.publication_safe_crack_control_record({
        "cases": [{
            "case": "Danish SLS",
            "assessment": copy.deepcopy(assessment),
            "response_mapping_scope": copy.deepcopy(
                elastic["crack_response_mapping_scope"]
            ),
            "responses": [
                {
                    "name": name,
                    "wk_mm": response["wk"],
                    "element_id": response["element_id"],
                    "solver_status": "OK",
                    "solver_reason": "",
                    "context": copy.deepcopy(
                        elastic["crack_response_contexts"][name]
                    ),
                    "acceptance_role": (
                        "informational"
                        if name in informational
                        else "criterion input"
                    ),
                }
                for name, response in elastic["crack_responses"].items()
            ],
        }],
    })


def _basis(**changes):
    values = {
        "asset_class": danish_bridge.ASSET_ROAD,
        "infrastructure_manager": (
            danish_bridge.MANAGER_ROAD_DIRECTORATE
        ),
        "manager_source": "VD Projekteringsgrundlag 2023+corr.2026",
        "project_basis_source": "DB-05 section 2.3",
        "traffic_fatigue_applicability": (
            danish_bridge.FATIGUE_NOT_APPLICABLE
        ),
        "calculated_fatigue_authority": fatigue_inputs.AUTHORITY_VD,
        "calculated_fatigue_method": fatigue_inputs.METHOD_VD_FLM4,
        "calculated_fatigue_spectrum_source": (
            "VD project basis section 6.8"
        ),
        "calculated_fatigue_cycle_count_source": "Traffic register T-04",
        "environment_class": danish_bridge.ENVIRONMENT_AGGRESSIVE,
        "environment_source": "DB-05 section 4.2",
        "departure_applicability": (
            danish_bridge.APPLICABILITY_NOT_APPLICABLE
        ),
        "departure_source": "",
        "deviations": "",
        "control_class": danish_bridge.CONTROL_NORMAL,
        "control_source": "DB-05 section 2.4",
        "consequence_class": danish_bridge.CONSEQUENCE_CC2,
        "consequence_source": "DB-05 section 2.5",
        "high_strength_approval": danish_bridge.APPROVAL_NOT_APPLICABLE,
        "surface_condition": danish_bridge.SURFACE_WATERPROOFED,
        "deicing_applicability": (
            danish_bridge.APPLICABILITY_NOT_APPLICABLE
        ),
        "cover_category": danish_bridge.COVER_NONPRESTRESSED,
        "nominal_cover_mm": 45.0,
        "cover_source": "Drawing B-105 section A",
        "collision_risk_applicability": (
            danish_bridge.APPLICABILITY_NOT_APPLICABLE
        ),
        "alpha_cc": 1.0,
        "alpha_ct": 1.0,
    }
    values.update(changes)
    return danish_bridge.DanishBridgeBasis(**values)


def _project_scalars(**changes):
    values = {
        "design_methodology": bridge.EN1992_2_DK_NA,
        "conc_fck": 40.0,
        "conc_alpha_cc": 1.0,
        "bridge_brittle_method": bridge.BRITTLE_METHOD_A,
        "bridge_expected_box_walls": 0,
        "bridge_minimum_scope": bridge.MINIMUM_SCOPE_NOT_ESTABLISHED,
        "bridge_shear_scope": bridge.SHEAR_SCOPE_NOT_ESTABLISHED,
        "bridge_exposure": bridge.BRIDGE_EXPOSURE_NOT_ESTABLISHED,
        "bridge_asset_class": danish_bridge.ASSET_ROAD,
        "bridge_infrastructure_manager": (
            danish_bridge.MANAGER_ROAD_DIRECTORATE
        ),
        "bridge_manager_source": "VD basis 2023+corr.2026",
        "bridge_project_basis_source": "DB-05 section 2.3",
        "bridge_authority_approval_reference": "",
        "bridge_traffic_fatigue_applicability": (
            danish_bridge.FATIGUE_NOT_APPLICABLE
        ),
        "bridge_traffic_fatigue_model": "",
        "bridge_traffic_fatigue_source": "",
        "bridge_environment_class": danish_bridge.ENVIRONMENT_AGGRESSIVE,
        "bridge_environment_source": "DB-05 section 4.2",
        "bridge_special_rules": "No mapped special relaxation",
        "bridge_departure_applicability": (
            danish_bridge.APPLICABILITY_NOT_APPLICABLE
        ),
        "bridge_departure_source": "",
        "bridge_deviations": "",
        "bridge_control_class": danish_bridge.CONTROL_NORMAL,
        "bridge_control_source": "DB-05 section 2.4",
        "bridge_consequence_class": danish_bridge.CONSEQUENCE_CC2,
        "bridge_consequence_source": "DB-05 section 2.5",
        "bridge_high_strength_approval": (
            danish_bridge.APPROVAL_NOT_APPLICABLE
        ),
        "bridge_high_strength_approval_reference": "",
        "bridge_execution_conditions_source": "",
        "bridge_surface_condition": danish_bridge.SURFACE_WATERPROOFED,
        "bridge_deicing_applicability": (
            danish_bridge.APPLICABILITY_NOT_APPLICABLE
        ),
        "bridge_deicing_source": "",
        "bridge_cover_category": danish_bridge.COVER_NONPRESTRESSED,
        "bridge_nominal_cover_mm": 45.0,
        "bridge_cover_source": "Drawing B-105 section A",
        "bridge_collision_risk_applicability": (
            danish_bridge.APPLICABILITY_NOT_APPLICABLE
        ),
        "bridge_alpha_cc_basis": conformance.STANDARD_BASIS,
        "bridge_alpha_cc_custom_methodology": "",
        "bridge_alpha_cc_approval_reference": "",
        "bridge_alpha_ct": 1.0,
        "bridge_alpha_ct_basis": conformance.STANDARD_BASIS,
        "bridge_alpha_ct_custom_methodology": "",
        "bridge_alpha_ct_approval_reference": "",
        "sls_dk_member_class": danish_bridge.MEMBER_NONPRESTRESSED,
        "fatigue_on": False,
        "fatigue_check_steel": False,
        "fatigue_check_concrete": False,
    }
    values.update(changes)
    return values


def _project_tables(decisions=None):
    selected = decisions or _decisions()
    return {
        bridge_inputs.COVERAGE_TABLE_KEY: (
            bridge_inputs.table_from_records(
                [
                    {
                        "check_id": item.check_id,
                        "applicability": item.applicability,
                        "source": item.source,
                        "notes": item.notes,
                    }
                    for item in selected
                ],
                bridge_inputs.COVERAGE_TABLE_KEY,
            )
        ),
    }


def _project_inputs(scalars=None, decisions=None):
    return {
        **(scalars if scalars is not None else _project_scalars()),
        **_project_tables(decisions),
    }


def _torsion_input(alpha_ct):
    concrete = SimpleNamespace(
        fck=40.0,
        fcd=40.0 / 1.45,
        gamma_c=1.45,
    )
    steel = SimpleNamespace(fytk=550.0, gamma_y=1.20)
    return {
        "outer": [(0.0, 0.0), (0.3, 0.0), (0.3, 0.6), (0.0, 0.6)],
        "holes": [],
        "bars": [(0.05, 0.05, 1000.0)],
        "section": object(),
        "concrete": concrete,
        "steel": steel,
        "torsion_on": True,
        "torsion_method": codes.EC2_2005_DKNA.label,
        "torsion_tef": 0.0,
        "torsion_nu_v": False,
        "torsion_T": 20.0,
        "torsion_subdivide": False,
        "torsion_subrects": [],
        "torsion_factor_mode": codes.FACTOR_MODE_PRESET,
        "torsion_gamma0": 1.0,
        "torsion_gamma3": 1.0,
        "torsion_gamma_ct": 1.70,
        "torsion_factor_approval": "",
        "strut_cot_min": 1.0,
        "strut_cot_max": 2.5,
        "shear_link_dia": 10.0,
        "shear_link_s": 150.0,
        "shear_fywk": 550.0,
        "design_methodology": bridge.EN1992_2_DK_NA,
        "bridge_alpha_ct": alpha_ct,
    }


def test_oracle_has_no_sector_import_and_frozen_fixture_is_self_consistent():
    tree = ast.parse(pathlib.Path(oracle.__file__).read_text(encoding="utf-8"))
    imported = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    imported.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    assert not any(name == "sector" or name.startswith("sector.") for name in imported)

    evaluated = oracle.evaluate_fixture(FIXTURE)
    data = _fixture()
    for group, expected_key in (
        ("crack_cases", "expected"),
        ("cover_cases", "expected_mm"),
        ("torsion_cases", "expected_knm"),
        ("authority_cases", "expected"),
        ("departure_cases", "expected"),
        ("traffic_fatigue_cases", "expected"),
        ("annex_cases", "expected"),
    ):
        for case in data[group]:
            actual = evaluated[group][case["id"]]
            expected = case[expected_key]
            if group == "crack_cases":
                assert actual == tuple(tuple(row) for row in expected)
            elif group in {"cover_cases", "torsion_cases"}:
                assert actual == pytest.approx(expected)
            else:
                assert actual == expected


@pytest.mark.parametrize(
    "case",
    _fixture()["traffic_fatigue_cases"],
    ids=lambda x: x["id"],
)
def test_danish_traffic_fatigue_correlation_matches_independent_oracle(case):
    applicability = {
        "required": danish_bridge.FATIGUE_REQUIRED,
        "not_applicable": danish_bridge.FATIGUE_NOT_APPLICABLE,
        "not_established": danish_bridge.NOT_ESTABLISHED,
    }
    result = danish_bridge.assess_project_basis(_basis(
        traffic_fatigue_applicability=applicability[case["applicability"]],
        traffic_fatigue_model=case["declared_model"],
        traffic_fatigue_source=case["declared_source"],
        calculated_fatigue_authority=case["calculated_authority"],
        calculated_fatigue_method=case["calculated_method"],
        calculated_fatigue_spectrum_source=case[
            "calculated_spectrum_source"
        ],
        calculated_fatigue_cycle_count_source=case[
            "calculated_cycle_count_source"
        ],
        reinforcement_fatigue_applicability=applicability[
            case["reinforcement_applicability"]
        ],
        concrete_fatigue_applicability=applicability[
            case["concrete_applicability"]
        ],
        fatigue_on=case["analysis_enabled"],
        reinforcement_fatigue_on=case["reinforcement_enabled"],
        concrete_fatigue_on=case["concrete_enabled"],
    ))
    actual = (
        "MAPPED"
        if result["status"] == danish_bridge.STATUS_PASS
        else "NOT_ASSESSED"
    )

    assert actual == case["expected"]


@pytest.mark.parametrize("case", _fixture()["crack_cases"], ids=lambda x: x["id"])
def test_danish_crack_matrix_matches_independent_oracle(case):
    expected = oracle.crack_route(
        case["asset_class"],
        case["member_class"],
        case["environment"],
    )
    assert _production_route(case) == expected
    if case["member_class"] == "nonprestressed":
        assert _production_route(case) == (
            ("width", sls.COMBINATION_FREQUENT, expected[0][2]),
        )


def test_danish_crack_route_fails_closed_on_missing_conflicting_or_moderate_class():
    base = {
        "asset_class": "road",
        "member_class": "nonprestressed",
        "environment": "aggressive",
    }
    missing = _criteria({**base, "asset_class": "other"})
    assert missing[0]["required_combination"] is None
    assert missing[0]["configuration_status"] == "NOT ASSESSED"

    moderate = sls.crack_criteria_from_inputs({
        "sls_criterion_mode": sls.CRITERION_MODE_STANDARD,
        "sls_edition": sls.EDITION_BRIDGE_DK_2015,
        "sls_code": bridge.EN1992_2_DK_NA,
        "sls_prestress_class": sls.PRESTRESS_REINFORCED_UNBONDED,
        "sls_check_durability": True,
        "bridge_asset_class": danish_bridge.ASSET_ROAD,
        "bridge_environment_class": danish_bridge.ENVIRONMENT_MODERATE,
        "sls_dk_member_class": danish_bridge.MEMBER_NONPRESTRESSED,
        "sls_has_tendons": False,
    })
    assert moderate[0]["required_combination"] is None
    assert "Moderate is not used" in moderate[0]["configuration_reason"]

    conflict = _criteria({**base, "member_class": "prestressed"})
    assert conflict[0]["configuration_status"] == "READY"
    conflicting_input = {
        "sls_criterion_mode": sls.CRITERION_MODE_STANDARD,
        "sls_edition": sls.EDITION_BRIDGE_DK_2015,
        "sls_code": bridge.EN1992_2_DK_NA,
        "sls_prestress_class": sls.PRESTRESS_BONDED,
        "sls_check_durability": True,
        "bridge_asset_class": danish_bridge.ASSET_ROAD,
        "bridge_environment_class": danish_bridge.ENVIRONMENT_AGGRESSIVE,
        "sls_dk_member_class": danish_bridge.MEMBER_PRESTRESSED,
        "sls_has_tendons": False,
    }
    routed = sls.crack_criteria_from_inputs(conflicting_input)
    assert routed[0]["required_combination"] is None
    assert "containing no tendons" in routed[0]["configuration_reason"]


@pytest.mark.parametrize("has_tendons", [None, "False", 0, 1, float("nan")])
def test_danish_crack_route_requires_typed_tendon_presence(has_tendons):
    routed = sls.crack_criteria_from_inputs({
        "sls_criterion_mode": sls.CRITERION_MODE_STANDARD,
        "sls_edition": sls.EDITION_BRIDGE_DK_2015,
        "sls_code": bridge.EN1992_2_DK_NA,
        "sls_prestress_class": sls.PRESTRESS_REINFORCED_UNBONDED,
        "sls_check_durability": True,
        "bridge_asset_class": danish_bridge.ASSET_ROAD,
        "bridge_environment_class": danish_bridge.ENVIRONMENT_AGGRESSIVE,
        "sls_dk_member_class": danish_bridge.MEMBER_NONPRESTRESSED,
        "sls_has_tendons": has_tendons,
    })
    assert routed[0]["required_combination"] is None
    assert routed[0]["configuration_status"] == "NOT ASSESSED"
    assert "explicit Boolean tendon-presence" in (
        routed[0]["configuration_reason"]
    )


def test_nonprestressed_danish_acceptance_uses_frequent_not_qp_or_duration():
    case = {
        "asset_class": "road",
        "member_class": "nonprestressed",
        "environment": "aggressive",
    }
    contexts = _response_contexts()
    result = sls.crack_assessment(
        {
            "QP": {"wk": 0.60, "element_id": "bar 1"},
            "Frequent": {"wk": 0.29, "element_id": "bar 1"},
        },
        valid=True,
        criteria=_criteria(case),
        response_contexts=contexts,
        response_mapping_scope=_mapping_scope(contexts),
    )
    assert result["status"] == "OK"
    assert result["verdict"] == "PASS"
    assert result["case"] == "Frequent"
    assert result["value"] == pytest.approx(0.29)
    assert result["criteria"][0]["matched_responses"] == ["Frequent"]

    missing_frequent_contexts = {"QP": contexts["QP"]}
    missing = sls.crack_assessment(
        {"QP": {"wk": 0.01, "element_id": "bar 1"}},
        valid=True,
        criteria=_criteria(case),
        response_contexts=missing_frequent_contexts,
        response_mapping_scope=_mapping_scope(missing_frequent_contexts),
    )
    assert missing["status"] == "NOT ASSESSED"
    assert missing["verdict"] == "REVIEW"


def test_prestressed_width_pass_cannot_satisfy_missing_decompression_evidence():
    case = {
        "asset_class": "railway",
        "member_class": "prestressed",
        "environment": "extra_aggressive",
    }
    contexts = _response_contexts()
    result = sls.crack_assessment(
        {
            "Frequent": {"wk": 0.09, "element_id": "tendon 1"},
            "QP": {"wk": 0.01, "element_id": "tendon 1"},
        },
        valid=True,
        criteria=_criteria(case),
        response_contexts=contexts,
        response_mapping_scope=_mapping_scope(contexts),
    )
    assert result["status"] == "NOT ASSESSED"
    assert [
        (row["kind"], row["status"])
        for row in result["criteria"]
    ] == [
        (sls.CRITERION_DURABILITY, "OK"),
        (sls.CRITERION_DECOMPRESSION, "NOT ASSESSED"),
    ]

    complete = sls.crack_assessment(
        {
            "Frequent": {"wk": 0.09, "element_id": "tendon 1"},
            "QP": {
                "wk": 0.50,
                "element_id": "tendon 1",
                "decompression": {
                    "status": "OK",
                    "value": -0.05,
                    "governing": "concrete point 4",
                    "solver_provenance": {"state": "dk-qp"},
                },
            },
        },
        valid=True,
        criteria=_criteria(case),
        response_contexts=contexts,
        response_mapping_scope=_mapping_scope(contexts),
    )
    assert complete["status"] == "OK"
    assert complete["verdict"] == "PASS"


def test_duplicate_danish_frequent_mapping_is_not_assessed():
    case = {
        "asset_class": "road",
        "member_class": "nonprestressed",
        "environment": "aggressive",
    }
    contexts = {
        "Frequent A": {
            "combination": sls.COMBINATION_FREQUENT,
            "duration": "short",
            "response_id": "dk-frequent-a",
            "provenance": "first explicit frequent mapping",
            "solver_provenance": {"state": "dk-frequent-a"},
        },
        "Frequent B": {
            "combination": sls.COMBINATION_FREQUENT,
            "duration": "long",
            "response_id": "dk-frequent-b",
            "provenance": "second explicit frequent mapping",
            "solver_provenance": {"state": "dk-frequent-b"},
        },
    }
    result = sls.crack_assessment(
        {
            "Frequent A": {"wk": 0.10, "element_id": "bar 1"},
            "Frequent B": {"wk": 0.20, "element_id": "bar 2"},
        },
        valid=True,
        criteria=_criteria(case),
        response_contexts=contexts,
        response_mapping_scope=_mapping_scope(contexts),
    )
    assert result["status"] == "NOT ASSESSED"
    assert result["criteria"][0]["matched_responses"] == [
        "Frequent A",
        "Frequent B",
    ]


@pytest.mark.parametrize("case", _fixture()["cover_cases"], ids=lambda x: x["id"])
def test_danish_cover_route_matches_independent_oracle(case):
    category = {
        "nonprestressed": danish_bridge.COVER_NONPRESTRESSED,
        "pretensioned": danish_bridge.COVER_PRETENSIONED,
        "posttension_duct": danish_bridge.COVER_POSTTENSION_DUCT,
    }[case["cover_category"]]
    asset = (
        danish_bridge.ASSET_RAIL
        if case.get("railway_collision_risk")
        else danish_bridge.ASSET_ROAD
    )
    collision = (
        danish_bridge.APPLICABILITY_REQUIRED
        if case.get("railway_collision_risk")
        else danish_bridge.APPLICABILITY_NOT_APPLICABLE
    )
    actual, evidence = danish_bridge.nominal_cover_requirement(
        environment_class=ENVIRONMENTS[case["environment"]],
        cover_category=category,
        control_class=danish_bridge.CONTROL_NORMAL,
        collision_risk_applicability=collision,
        asset_class=asset,
    )
    expected = oracle.nominal_cover_requirement_mm(
        case["environment"],
        case["cover_category"],
        railway_collision_risk=case.get("railway_collision_risk", False),
    )
    assert actual == expected == pytest.approx(case["expected_mm"])
    assert evidence["required_nominal_cover_mm"] == expected


def test_cover_uses_actual_value_and_can_fail_without_clamping():
    result = danish_bridge.assess_cover(_basis(nominal_cover_mm=44.9))
    assert result["status"] == danish_bridge.STATUS_FAIL
    assert result["evidence"][0]["actual_nominal_cover_mm"] == pytest.approx(44.9)
    assert result["evidence"][0]["required_nominal_cover_mm"] == 45.0


@pytest.mark.parametrize(
    "bad",
    [True, np.bool_(False), "45", float("nan"), float("inf"), -1.0],
)
def test_cover_malformed_nonfinite_boolean_or_negative_is_hard_error(bad):
    result = danish_bridge.assess_cover(_basis(nominal_cover_mm=bad))
    assert result["status"] == danish_bridge.STATUS_INVALID


def test_missing_cover_is_not_assessed_but_zero_cover_is_a_real_failure():
    missing = danish_bridge.assess_cover(_basis(nominal_cover_mm=None))
    assert missing["status"] == danish_bridge.STATUS_NOT_ASSESSED
    assert "missing" in missing["reason"]

    zero = danish_bridge.assess_cover(_basis(nominal_cover_mm=0.0))
    assert zero["status"] == danish_bridge.STATUS_FAIL
    assert zero["evidence"][0]["actual_nominal_cover_mm"] == 0.0


def test_manager_mapping_is_explicit_and_unmapped_choice_is_warning_only():
    mapped = danish_bridge.assess_project_basis(_basis())
    assert mapped["status"] == danish_bridge.STATUS_PASS

    unmapped = danish_bridge.assess_project_basis(_basis(
        infrastructure_manager=danish_bridge.MANAGER_OTHER,
    ))
    assert unmapped["status"] == danish_bridge.STATUS_REVIEW
    assert "no mapped Sector calculation effect" in unmapped["reason"]

    strict_factor = danish_bridge.assess_project_basis(_basis(
        asset_class=danish_bridge.ASSET_RAIL,
        infrastructure_manager=danish_bridge.MANAGER_BANEDANMARK,
        control_class=danish_bridge.CONTROL_STRICT,
        fatigue_on=True,
        fatigue_gamma3=1.0,
    ))
    assert strict_factor["status"] == danish_bridge.STATUS_REVIEW
    assert "remain calculation inputs" in strict_factor["reason"]


def test_required_traffic_fatigue_cannot_pass_with_analysis_disabled():
    result = danish_bridge.assess_project_basis(_basis(
        traffic_fatigue_applicability=danish_bridge.FATIGUE_REQUIRED,
        traffic_fatigue_model=fatigue_inputs.METHOD_VD_FLM4,
        traffic_fatigue_source="VD project basis section 6.8",
        reinforcement_fatigue_applicability=danish_bridge.FATIGUE_REQUIRED,
        concrete_fatigue_applicability=danish_bridge.FATIGUE_NOT_APPLICABLE,
        reinforcement_fatigue_on=True,
        concrete_fatigue_on=False,
        fatigue_on=False,
    ))

    assert result["status"] == danish_bridge.STATUS_NOT_ASSESSED
    assert "fatigue analysis" in result["reason"]


def test_required_traffic_fatigue_cannot_use_not_applicable_calculation_checks():
    basis = _basis(
        traffic_fatigue_applicability=danish_bridge.FATIGUE_REQUIRED,
        traffic_fatigue_model=fatigue_inputs.METHOD_VD_FLM4,
        traffic_fatigue_source="VD project basis section 6.8",
        reinforcement_fatigue_applicability=(
            danish_bridge.FATIGUE_NOT_APPLICABLE
        ),
        concrete_fatigue_applicability=(
            danish_bridge.FATIGUE_NOT_APPLICABLE
        ),
        fatigue_on=True,
    )
    result = bridge.assess_base_methodology(bridge.BridgeBaseEvidence(
        methodology=bridge.EN1992_2_DK_NA,
        decisions=tuple(
            bridge.ApplicabilityDecision(
                check_id,
                bridge.NOT_APPLICABLE,
                f"DB-{check_id}",
            )
            for check_id in bridge.APPLICABILITY_CHECK_IDS
        ),
        has_tendons=False,
        has_hollow_section=False,
        fck_mpa=40.0,
        danish_basis=basis,
    ))

    project_basis = next(
        row for row in result["checks"]
        if row["check_id"] == "dk_project_basis"
    )
    assert project_basis["status"] == bridge.STATUS_NOT_ASSESSED
    assert "calculated fatigue check" in project_basis["reason"]
    assert result["status"] == bridge.STATUS_NOT_ASSESSED


def test_required_traffic_fatigue_passes_basis_only_with_matching_calculated_route():
    decisions = tuple(
        bridge.ApplicabilityDecision(
            check_id,
            (
                bridge.REQUIRED
                if check_id == "reinforcement_fatigue"
                else bridge.NOT_APPLICABLE
            ),
            f"DB-{check_id}",
        )
        for check_id in bridge.APPLICABILITY_CHECK_IDS
    )
    basis = _basis(
        traffic_fatigue_applicability=danish_bridge.FATIGUE_REQUIRED,
        traffic_fatigue_model=fatigue_inputs.METHOD_VD_FLM4,
        traffic_fatigue_source="VD project basis section 6.8",
        reinforcement_fatigue_applicability=danish_bridge.FATIGUE_REQUIRED,
        concrete_fatigue_applicability=danish_bridge.FATIGUE_NOT_APPLICABLE,
        reinforcement_fatigue_on=True,
        concrete_fatigue_on=False,
        fatigue_on=True,
    )
    result = bridge.assess_base_methodology(bridge.BridgeBaseEvidence(
        methodology=bridge.EN1992_2_DK_NA,
        decisions=decisions,
        has_tendons=False,
        has_hollow_section=False,
        fck_mpa=40.0,
        reinforcement_fatigue=bridge.ExternalEvidence(
            status=bridge.STATUS_PASS,
            result="governing damage = 0.72",
            criterion="damage <= 1.0",
            source="calculated FLM3 spectrum",
            reason="The enabled reinforcement fatigue route was calculated.",
            evidence=({"status": bridge.STATUS_PASS, "damage": 0.72},),
        ),
        danish_basis=basis,
    ))

    project_basis = next(
        row for row in result["checks"]
        if row["check_id"] == "dk_project_basis"
    )
    reinforcement = next(
        row for row in result["checks"]
        if row["check_id"] == "reinforcement_fatigue"
    )
    assert project_basis["status"] == bridge.STATUS_PASS
    assert reinforcement["status"] == bridge.STATUS_PASS
    assert result["status"] == bridge.STATUS_NOT_ASSESSED


def test_required_traffic_fatigue_rejects_declared_model_calculation_drift():
    result = danish_bridge.assess_project_basis(_basis(
        traffic_fatigue_applicability=danish_bridge.FATIGUE_REQUIRED,
        traffic_fatigue_model="FLM3",
        traffic_fatigue_source="VD project basis section 6.8",
        reinforcement_fatigue_applicability=danish_bridge.FATIGUE_REQUIRED,
        concrete_fatigue_applicability=danish_bridge.FATIGUE_NOT_APPLICABLE,
        reinforcement_fatigue_on=True,
        concrete_fatigue_on=False,
        fatigue_on=True,
        calculated_fatigue_authority=(
            fatigue_inputs.AUTHORITY_USER
        ),
        calculated_fatigue_method=(
            fatigue_inputs.METHOD_USER_GROUPED
        ),
        calculated_fatigue_spectrum_source=(
            "VD project basis section 6.8"
        ),
        calculated_fatigue_cycle_count_source="Traffic register T-04",
    ))

    assert result["status"] == danish_bridge.STATUS_NOT_ASSESSED
    assert "does not match the calculated fatigue method" in result["reason"]


def test_danish_basis_derives_fatigue_routes_from_canonical_inputs():
    decisions = tuple(
        replace(
            decision,
            applicability=bridge.REQUIRED,
            source="DB-reinforcement-fatigue",
        )
        if decision.check_id == "reinforcement_fatigue"
        else decision
        for decision in _decisions()
    )
    inputs = _project_inputs(
        _project_scalars(
            bridge_traffic_fatigue_applicability=(
                danish_bridge.FATIGUE_REQUIRED
            ),
            bridge_traffic_fatigue_model=fatigue_inputs.METHOD_VD_FLM4,
            bridge_traffic_fatigue_source=(
                "VD project basis section 6.8"
            ),
            fatigue_basis={
                **fatigue_inputs.default_basis(),
                "authority": fatigue_inputs.AUTHORITY_VD,
                "method": fatigue_inputs.METHOD_VD_FLM4,
                "spectrum_source": "VD project basis section 6.8",
                "cycle_count_source": "Traffic register T-04",
            },
            fatigue_on=True,
            fatigue_check_steel=True,
            fatigue_check_concrete=False,
        ),
        decisions,
    )
    basis = bridge_inputs.danish_basis_from_inputs(inputs)
    context = danish_bridge.basis_context(basis)

    assert basis.reinforcement_fatigue_applicability == bridge.REQUIRED
    assert basis.concrete_fatigue_applicability == bridge.NOT_APPLICABLE
    assert context["fatigue_on"] is True
    assert context["reinforcement_fatigue_on"] is True
    assert context["concrete_fatigue_on"] is False
    assert context["calculated_fatigue_method"] == (
        fatigue_inputs.METHOD_VD_FLM4
    )


def test_danish_method_rejects_conflicting_fatigue_applicability_snapshots():
    result = bridge.assess_base_methodology(bridge.BridgeBaseEvidence(
        methodology=bridge.EN1992_2_DK_NA,
        decisions=tuple(
            bridge.ApplicabilityDecision(
                check_id,
                bridge.NOT_APPLICABLE,
                f"DB-{check_id}",
            )
            for check_id in bridge.APPLICABILITY_CHECK_IDS
        ),
        has_tendons=False,
        has_hollow_section=False,
        fck_mpa=40.0,
        danish_basis=_basis(
            reinforcement_fatigue_applicability=bridge.REQUIRED,
        ),
    ))

    assert result["status"] == bridge.STATUS_INVALID
    assert any(
        "reinforcement_fatigue applicability conflicts" in error
        for error in result["configuration_errors"]
    )


def test_danish_basis_rejects_malformed_fatigue_route_state():
    malformed_toggle = danish_bridge.assess_project_basis(_basis(
        reinforcement_fatigue_on="true",
    ))
    malformed_route = danish_bridge.assess_project_basis(_basis(
        reinforcement_fatigue_applicability="Required-ish",
    ))

    assert malformed_toggle["status"] == danish_bridge.STATUS_INVALID
    assert "must be Boolean" in malformed_toggle["reason"]
    assert malformed_route["status"] == danish_bridge.STATUS_INVALID
    assert "Unknown reinforcement fatigue applicability" in (
        malformed_route["reason"]
    )


def test_departure_applicability_requires_source_and_approval_without_inference():
    missing_decision = danish_bridge.assess_project_basis(_basis(
        departure_applicability=danish_bridge.NOT_ESTABLISHED,
    ))
    assert missing_decision["status"] == danish_bridge.STATUS_NOT_ASSESSED
    assert "departure / dispensation applicability" in missing_decision["reason"]

    unapproved = danish_bridge.assess_project_basis(_basis(
        departure_applicability=danish_bridge.APPLICABILITY_REQUIRED,
        deviations="Project crack-width departure",
        departure_source="DB-05 section 7.3",
        authority_approval_reference="",
    ))
    assert unapproved["status"] == danish_bridge.STATUS_NOT_ASSESSED
    assert "departure authority approval" in unapproved["reason"]

    approved = danish_bridge.assess_project_basis(_basis(
        departure_applicability=danish_bridge.APPLICABILITY_REQUIRED,
        deviations="Project crack-width departure",
        departure_source="DB-05 section 7.3",
        authority_approval_reference="VD-DISP-05",
    ))
    assert approved["status"] == danish_bridge.STATUS_REVIEW
    assert "cannot be relabelled as an unqualified" in approved["reason"]

    conflicting_text = danish_bridge.assess_project_basis(_basis(
        departure_applicability=danish_bridge.APPLICABILITY_NOT_APPLICABLE,
        deviations="Unclassified reservation text",
    ))
    assert conflicting_text["status"] == danish_bridge.STATUS_REVIEW
    assert "not inferred from free text" in conflicting_text["reason"]

    malformed = danish_bridge.assess_project_basis(_basis(
        asset_class="Silently inferred bridge class",
        departure_applicability=danish_bridge.APPLICABILITY_REQUIRED,
        deviations="Project crack-width departure",
        departure_source="DB-05 section 7.3",
        authority_approval_reference="VD-DISP-05",
    ))
    assert malformed["status"] == danish_bridge.STATUS_INVALID


@pytest.mark.parametrize(
    "case",
    _fixture()["authority_cases"],
    ids=lambda value: value["id"],
)
def test_production_authority_mapping_matches_independent_fixture(case):
    managers = {
        "road_directorate": danish_bridge.MANAGER_ROAD_DIRECTORATE,
        "local_road": danish_bridge.MANAGER_LOCAL_ROAD,
        "banedanmark": danish_bridge.MANAGER_BANEDANMARK,
        "regional_rail": danish_bridge.MANAGER_REGIONAL_RAIL,
        "other": danish_bridge.MANAGER_OTHER,
    }
    assets = {
        "road": danish_bridge.ASSET_ROAD,
        "footbridge": danish_bridge.ASSET_FOOT,
        "railway": danish_bridge.ASSET_RAIL,
        "other": danish_bridge.ASSET_OTHER,
    }
    state, _ = danish_bridge.manager_mapping(_basis(
        infrastructure_manager=managers[case["manager"]],
        asset_class=assets[case["asset_class"]],
    ))
    actual = {
        danish_bridge.STATUS_PASS: "MAPPED",
        danish_bridge.STATUS_REVIEW: (
            "REVIEW_ONLY"
            if case["manager"] == "other" or case["asset_class"] == "other"
            else "CONFLICT_REVIEW"
        ),
    }[state]
    assert actual == case["expected"]


@pytest.mark.parametrize(
    "case",
    _fixture()["departure_cases"],
    ids=lambda value: value["id"],
)
def test_production_departure_gate_matches_independent_fixture(case):
    applicability = {
        "not_established": danish_bridge.NOT_ESTABLISHED,
        "required": danish_bridge.APPLICABILITY_REQUIRED,
        "not_applicable": danish_bridge.APPLICABILITY_NOT_APPLICABLE,
    }[case["applicability"]]
    result = danish_bridge.assess_project_basis(_basis(
        departure_applicability=applicability,
        deviations=case["description"],
        departure_source=case["source"],
        authority_approval_reference=case["approval"],
    ))
    if result["status"] == danish_bridge.STATUS_PASS:
        actual = "MAPPED"
    elif result["status"] == danish_bridge.STATUS_NOT_ASSESSED:
        actual = "NOT_ASSESSED"
    elif "not inferred from free text" in result["reason"]:
        actual = "CONFLICT_REVIEW"
    else:
        actual = "REVIEW_ONLY"
    assert actual == case["expected"]


@pytest.mark.parametrize(
    ("asset_class", "expected"),
    [
        (danish_bridge.ASSET_ROAD, (3.0, 3.0)),
        (danish_bridge.ASSET_FOOT, (3.0, 3.0)),
        (danish_bridge.ASSET_RAIL, (5.0, 3.0)),
    ],
)
def test_deicing_route_requires_source_and_records_mapped_distances(
    asset_class,
    expected,
):
    manager = (
        danish_bridge.MANAGER_BANEDANMARK
        if asset_class == danish_bridge.ASSET_RAIL
        else danish_bridge.MANAGER_ROAD_DIRECTORATE
    )
    missing = danish_bridge.assess_project_basis(_basis(
        asset_class=asset_class,
        infrastructure_manager=manager,
        deicing_applicability=danish_bridge.APPLICABILITY_REQUIRED,
        deicing_source="",
    ))
    assert missing["status"] == danish_bridge.STATUS_NOT_ASSESSED
    assert "de-icing applicability source" in missing["reason"]

    mapped = danish_bridge.assess_project_basis(_basis(
        asset_class=asset_class,
        infrastructure_manager=manager,
        deicing_applicability=danish_bridge.APPLICABILITY_REQUIRED,
        deicing_source="DB-05 geometry G-02",
    ))
    assert mapped["status"] == danish_bridge.STATUS_PASS
    assert mapped["evidence"][0]["mapped_deicing_x_m"] == expected[0]
    assert mapped["evidence"][0]["mapped_deicing_y_m"] == expected[1]


def test_high_strength_requires_both_approval_and_execution_conditions():
    incomplete = danish_bridge.assess_high_strength(
        60.0,
        _basis(
            high_strength_approval=danish_bridge.APPROVAL_APPROVED,
            high_strength_approval_reference="VD-APP-12",
            execution_conditions_source="",
        ),
    )
    assert incomplete["status"] == danish_bridge.STATUS_REVIEW
    assert incomplete["evidence"][0]["fck_mpa"] == 60.0

    complete = danish_bridge.assess_high_strength(
        60.0,
        _basis(
            high_strength_approval=danish_bridge.APPROVAL_APPROVED,
            high_strength_approval_reference="VD-APP-12",
            execution_conditions_source="Execution specification EX-4",
        ),
    )
    assert complete["status"] == danish_bridge.STATUS_PASS


def test_custom_positive_alpha_ct_changes_torsion_but_is_not_standard_pass():
    standard = capacity.build_torsion_context(_torsion_input(1.0), 0.0)
    custom = capacity.build_torsion_context(_torsion_input(0.8), 0.0)
    assert standard["tube"]["Ak"] == pytest.approx(0.10)
    assert standard["tube"]["tef"] == pytest.approx(100.0)
    assert standard["fctd"] * 0.8 == pytest.approx(custom["fctd"])
    assert standard["alpha_ct"] == 1.0
    assert custom["alpha_ct"] == 0.8

    oracle_case = next(
        case for case in _fixture()["torsion_cases"]
        if case["id"] == "custom-alpha-ct"
    )
    production_trd = (
        2.0
        * custom["tube"]["Ak"]
        * (custom["tube"]["tef"] / 1000.0)
        * custom["fctd"]
        * 1000.0
    )
    assert production_trd == pytest.approx(oracle_case["expected_knm"])

    conformance_result = danish_bridge.assess_coefficients(_basis(
        alpha_ct=0.8,
        alpha_ct_basis=conformance.STANDARD_BASIS,
    ))
    assert conformance_result["status"] == danish_bridge.STATUS_REVIEW
    assert conformance_result["evidence"][1]["actual_value"] == 0.8


@pytest.mark.parametrize(
    "bad",
    [True, np.bool_(True), "1.0", float("nan"), float("inf"), 0.0, -0.1],
)
def test_alpha_ct_malformed_nonfinite_boolean_or_unusable_is_hard_error(bad):
    result = danish_bridge.assess_coefficients(_basis(alpha_ct=bad))
    assert result["status"] == danish_bridge.STATUS_INVALID
    assert capacity.torsion_factor_validation_error(
        _torsion_input(bad)
    ) is not None


def _decisions():
    return tuple(
        bridge.ApplicabilityDecision(
            check_id=check_id,
            applicability=(
                bridge.REQUIRED
                if check_id == "prestress_brittle"
                else bridge.NOT_APPLICABLE
            ),
            source=f"DB-{check_id}",
        )
        for check_id in bridge.APPLICABILITY_CHECK_IDS
    )


def test_danish_method_is_distinct_and_method_a_never_falls_back_to_method_b():
    matrix = {
        row["check_id"]: row
        for row in bridge.coverage_matrix(bridge.EN1992_2_DK_NA)
    }
    assert bridge.EN1992_2_BASE != bridge.EN1992_2_DK_NA
    assert matrix["prestress_brittle"]["disposition"] == bridge.DISPOSITION_OVERRIDDEN
    assert matrix["sls_crack"]["disposition"] == bridge.DISPOSITION_OVERRIDDEN
    assert "dk_project_basis" in matrix
    assert "dk_annex_routing" in matrix

    evidence = bridge.BridgeBaseEvidence(
        methodology=bridge.EN1992_2_DK_NA,
        decisions=_decisions(),
        has_tendons=True,
        has_hollow_section=False,
        fck_mpa=40.0,
        brittle_method=bridge.BRITTLE_METHOD_B,
        danish_basis=_basis(),
    )
    result = bridge.assess_base_methodology(evidence)
    brittle = next(
        row for row in result["checks"]
        if row["check_id"] == "prestress_brittle"
    )
    assert brittle["status"] == bridge.STATUS_NOT_ASSESSED
    assert "not an applicable Danish bridge route" in brittle["reason"]
    assert result["methodology"] == bridge.EN1992_2_DK_NA
    assert result["evidence_schema"] == bridge.DANISH_BRIDGE_EVIDENCE_SCHEMA
    assert result["danish_basis"]["asset_class"] == danish_bridge.ASSET_ROAD
    relationships = {
        row["check_id"]: row["disposition"]
        for row in result["coverage_matrix"]
    }
    assert {
        row["check_id"]: row["disposition"]
        for row in result["checks"]
    } == relationships


def test_danish_static_annex_table_never_passes_without_applicability_evidence():
    result = bridge.assess_base_methodology(bridge.BridgeBaseEvidence(
        methodology=bridge.EN1992_2_DK_NA,
        decisions=tuple(
            bridge.ApplicabilityDecision(
                check_id,
                bridge.NOT_APPLICABLE,
                f"DB-{check_id}",
            )
            for check_id in bridge.APPLICABILITY_CHECK_IDS
        ),
        has_tendons=False,
        has_hollow_section=False,
        fck_mpa=40.0,
        danish_basis=_basis(),
    ))

    annex = next(
        row for row in result["checks"]
        if row["check_id"] == "dk_annex_routing"
    )
    assert annex["status"] == bridge.STATUS_NOT_ASSESSED
    assert "applicability" in annex["reason"]
    assert "analysis evidence" in annex["reason"]
    assert result["status"] == bridge.STATUS_NOT_ASSESSED


def test_danish_direct_crack_method_follows_explicit_applicability():
    decisions = tuple(
        bridge.ApplicabilityDecision(
            check_id,
            bridge.NOT_APPLICABLE,
            f"DB-{check_id}",
        )
        for check_id in bridge.APPLICABILITY_CHECK_IDS
    )
    result = bridge.assess_base_methodology(bridge.BridgeBaseEvidence(
        methodology=bridge.EN1992_2_DK_NA,
        decisions=decisions,
        has_tendons=False,
        has_hollow_section=False,
        fck_mpa=40.0,
        danish_basis=_basis(),
    ))
    direct = next(
        row for row in result["checks"]
        if row["check_id"] == "dk_direct_crack_method"
    )
    assert direct["status"] == bridge.STATUS_NOT_APPLICABLE
    assert "DB-sls_crack" in direct["source"]

    missing_source = tuple(
        replace(
            decision,
            source="",
        )
        if decision.check_id == "sls_crack"
        else decision
        for decision in decisions
    )
    blocked = bridge.assess_base_methodology(bridge.BridgeBaseEvidence(
        methodology=bridge.EN1992_2_DK_NA,
        decisions=missing_source,
        has_tendons=False,
        has_hollow_section=False,
        fck_mpa=40.0,
        danish_basis=_basis(),
    ))
    direct = next(
        row for row in blocked["checks"]
        if row["check_id"] == "dk_direct_crack_method"
    )
    assert direct["status"] == bridge.STATUS_NOT_ASSESSED
    assert "project-basis source" in direct["reason"]


def test_danish_direct_crack_method_can_pass_while_decompression_stays_blocking():
    decisions = tuple(
        bridge.ApplicabilityDecision(
            check_id,
            (
                bridge.REQUIRED
                if check_id in {"prestress_brittle", "sls_crack"}
                else bridge.NOT_APPLICABLE
            ),
            f"DB-{check_id}",
        )
        for check_id in bridge.APPLICABILITY_CHECK_IDS
    )
    sls_evidence = bridge.ExternalEvidence(
        status=bridge.STATUS_NOT_ASSESSED,
        result="-",
        criterion="Danish width plus decompression",
        source="Table 7.101N DK NA",
        reason="The quasi-permanent concrete-stress response is missing.",
        evidence=(
            {
                "criterion_id": "bridge-dk-standard-durability",
                "kind": bridge.DANISH_DIRECT_CRACK_KIND,
                "status": bridge.STATUS_PASS,
                "result": "0.090 mm",
                "required_combination": sls.COMBINATION_FREQUENT,
                "solver_provenance": {"solver": "elastic-v1"},
                "acceptance_evidence": {"schema": "test-current-binding"},
            },
            {
                "criterion_id": "bridge-dk-standard-decompression",
                "kind": "decompression",
                "status": bridge.STATUS_NOT_ASSESSED,
                "result": "-",
                "required_combination": sls.COMBINATION_QUASI_PERMANENT,
                "solver_provenance": None,
                "acceptance_evidence": None,
            },
        ),
    )
    result = bridge.assess_base_methodology(bridge.BridgeBaseEvidence(
        methodology=bridge.EN1992_2_DK_NA,
        decisions=decisions,
        has_tendons=True,
        has_hollow_section=False,
        fck_mpa=40.0,
        brittle_method=bridge.BRITTLE_METHOD_A,
        sls_crack=sls_evidence,
        danish_basis=_basis(),
    ))
    direct = next(
        row for row in result["checks"]
        if row["check_id"] == "dk_direct_crack_method"
    )
    crack = next(
        row for row in result["checks"]
        if row["check_id"] == "sls_crack"
    )
    assert direct["status"] == bridge.STATUS_PASS
    assert direct["evidence"][0]["required_combination"] == (
        sls.COMBINATION_FREQUENT
    )
    assert crack["status"] == bridge.STATUS_NOT_ASSESSED
    assert result["status"] == bridge.STATUS_NOT_ASSESSED


def test_danish_project_save_load_resave_preserves_every_basis_field_and_hash():
    scalars = _project_scalars()
    first = project_io.dump_project({}, scalars)
    first_tables, first_scalars = project_io.parse_project(first)
    second = project_io.dump_project(first_tables, first_scalars)
    _, second_scalars = project_io.parse_project(second)

    for key in project_io.BRIDGE_SCALAR_KEYS:
        assert second_scalars[key] == first_scalars[key]
    assert second_scalars["sls_dk_member_class"] == (
        danish_bridge.MEMBER_NONPRESTRESSED
    )
    assert project_io.input_sha256(first_tables, first_scalars) == (
        project_io.input_sha256(first_tables, second_scalars)
    )
    assert json.loads(second)["version"] == 21


def test_required_fatigue_route_survives_project_save_load_resave():
    decisions = tuple(
        replace(
            decision,
            applicability=bridge.REQUIRED,
            source="DB-reinforcement-fatigue",
        )
        if decision.check_id == "reinforcement_fatigue"
        else decision
        for decision in _decisions()
    )
    scalars = _project_scalars(
        bridge_traffic_fatigue_applicability=danish_bridge.FATIGUE_REQUIRED,
        bridge_traffic_fatigue_model=fatigue_inputs.METHOD_VD_FLM4,
        bridge_traffic_fatigue_source="VD project basis section 6.8",
        fatigue_basis={
            **fatigue_inputs.default_basis(),
            "authority": fatigue_inputs.AUTHORITY_VD,
            "method": fatigue_inputs.METHOD_VD_FLM4,
            "spectrum_source": "VD project basis section 6.8",
            "cycle_count_source": "Traffic register T-04",
        },
        fatigue_on=True,
        fatigue_check_steel=True,
        fatigue_check_concrete=False,
    )
    first = project_io.dump_project(_project_tables(decisions), scalars)
    first_tables, first_scalars = project_io.parse_project(first)
    first_context = bridge_inputs.danish_basis_context({
        **first_scalars,
        **first_tables,
    })

    second = project_io.dump_project(first_tables, first_scalars)
    second_tables, second_scalars = project_io.parse_project(second)
    second_context = bridge_inputs.danish_basis_context({
        **second_scalars,
        **second_tables,
    })

    assert second_context == first_context
    assert second_context["traffic_fatigue_applicability"] == (
        danish_bridge.FATIGUE_REQUIRED
    )
    assert second_context["reinforcement_fatigue_applicability"] == (
        bridge.REQUIRED
    )
    assert second_context["concrete_fatigue_applicability"] == (
        bridge.NOT_APPLICABLE
    )
    assert second_context["fatigue_on"] is True
    assert second_context["reinforcement_fatigue_on"] is True
    assert second_context["concrete_fatigue_on"] is False
    assert project_io.input_sha256(second_tables, second_scalars) == (
        project_io.input_sha256(first_tables, first_scalars)
    )
    assert json.loads(second)["version"] == 21


@pytest.mark.parametrize(
    ("key", "bad"),
    [
        ("bridge_alpha_ct", True),
        ("bridge_alpha_ct", np.bool_(True)),
        ("bridge_alpha_ct", "1.0"),
        ("bridge_alpha_ct", float("nan")),
        ("bridge_alpha_ct", float("inf")),
        ("bridge_alpha_ct", 0.0),
        ("bridge_nominal_cover_mm", True),
        ("bridge_nominal_cover_mm", np.bool_(False)),
        ("bridge_nominal_cover_mm", "45"),
        ("bridge_nominal_cover_mm", float("inf")),
        ("bridge_manager_source", True),
        ("bridge_departure_applicability", "Silently inferred departure"),
        ("bridge_departure_source", True),
        ("bridge_infrastructure_manager", "Unknown silent manager"),
    ],
)
def test_project_boundary_rejects_malformed_danish_bridge_state(key, bad):
    with pytest.raises(ValueError):
        project_io.dump_project({}, _project_scalars(**{key: bad}))


def _dk_methodology_record(**scalar_changes):
    scalars = _project_scalars(**scalar_changes)
    basis = bridge_inputs.danish_basis_from_inputs(_project_inputs(scalars))
    evidence = bridge.BridgeBaseEvidence(
        methodology=bridge.EN1992_2_DK_NA,
        decisions=_decisions(),
        has_tendons=False,
        has_hollow_section=False,
        fck_mpa=scalars["conc_fck"],
        brittle_method=bridge.BRITTLE_METHOD_A,
        danish_basis=basis,
    )
    return bridge.assess_base_methodology(evidence)


def _dk_crack_methodology_record(width=0.29):
    scalars = _project_scalars()
    decisions = tuple(
        replace(
            item,
            applicability=bridge.REQUIRED,
            source="DB-sls_crack",
        )
        if item.check_id == "sls_crack"
        else item
        for item in _decisions()
    )
    results = _dk_crack_results(width)
    evidence = bridge.BridgeBaseEvidence(
        methodology=bridge.EN1992_2_DK_NA,
        decisions=decisions,
        has_tendons=False,
        has_hollow_section=False,
        fck_mpa=40.0,
        brittle_method=bridge.BRITTLE_METHOD_A,
        sls_crack=bridge_analysis.crack_evidence(results),
        danish_basis=bridge_inputs.danish_basis_from_inputs(
            _project_inputs(scalars, decisions)
        ),
    )
    return bridge.assess_base_methodology(evidence), results, decisions


def _dk_crack_context(
    *,
    crack=bridge.ExternalEvidence(),
    decisions=None,
):
    selected = decisions or _decisions()
    decision = next(
        item for item in selected if item.check_id == "sls_crack"
    )
    return bridge.danish_crack_publication_context(crack, decision)


def test_danish_basis_is_bound_against_recomputed_fingerprint_and_current_inputs():
    scalars = _project_scalars()
    context = bridge_inputs.danish_basis_context(_project_inputs(scalars))
    fatigue_context = fatigue_analysis.bridge_publication_context(scalars)
    record = _dk_methodology_record()

    safe = bridge.publication_safe_record(
        record,
        design_methodology=bridge.EN1992_2_DK_NA,
        fatigue_context=fatigue_context,
        danish_basis_context=context,
        danish_fck_mpa=scalars["conc_fck"],
        danish_crack_context=_dk_crack_context(),
    )
    assert safe["publication_validation"]["status"] == "ACCEPTED"

    attacked = copy.deepcopy(record)
    attacked["danish_basis"]["environment_class"] = (
        danish_bridge.ENVIRONMENT_EXTRA_AGGRESSIVE
    )
    attacked["evidence_fingerprint"] = bridge.bridge_evidence_fingerprint(
        attacked["checks"],
        attacked["configuration_errors"],
        methodology=bridge.EN1992_2_DK_NA,
        danish_basis_context=attacked["danish_basis"],
    )
    rejected = bridge.publication_safe_record(
        attacked,
        design_methodology=bridge.EN1992_2_DK_NA,
        fatigue_context=fatigue_context,
        danish_basis_context=context,
        danish_fck_mpa=scalars["conc_fck"],
        danish_crack_context=_dk_crack_context(),
    )
    assert rejected["publication_validation"]["status"] == "REJECTED"
    assert any(
        "basis conflicts" in error
        for error in rejected["publication_validation"]["errors"]
    )

    switched = bridge.publication_safe_record(
        record,
        design_methodology=bridge.EN1992_2_BASE,
        fatigue_context=fatigue_analysis.bridge_publication_context({
            **scalars,
            "design_methodology": bridge.EN1992_2_BASE,
        }),
        danish_basis_context=context,
        danish_fck_mpa=scalars["conc_fck"],
        danish_crack_context=_dk_crack_context(),
    )
    assert switched["publication_validation"]["status"] == "REJECTED"
    assert switched["status"] == bridge.STATUS_INVALID


@pytest.mark.parametrize(
    ("check_id", "scalar_changes"),
    [
        (
            "dk_project_basis",
            {
                "bridge_infrastructure_manager": danish_bridge.MANAGER_OTHER,
            },
        ),
        (
            "dk_concrete_coefficients",
            {
                "bridge_alpha_ct": 0.8,
                "bridge_alpha_ct_basis": conformance.CUSTOM_BASIS,
                "bridge_alpha_ct_custom_methodology": "Project tensile model",
                "bridge_alpha_ct_approval_reference": "DB-05 / checker 04",
            },
        ),
        (
            "dk_high_strength",
            {
                "conc_fck": 60.0,
                "bridge_high_strength_approval": (
                    danish_bridge.APPROVAL_NOT_APPROVED
                ),
            },
        ),
        (
            "dk_cover",
            {
                "bridge_nominal_cover_mm": 40.0,
            },
        ),
        ("dk_annex_routing", {}),
    ],
)
def test_publication_recomputes_danish_derived_checks_after_fingerprint_attack(
    check_id,
    scalar_changes,
):
    scalars = _project_scalars(**scalar_changes)
    record = _dk_methodology_record(**scalar_changes)
    expected = next(
        row for row in record["checks"] if row["check_id"] == check_id
    )
    assert expected["status"] != bridge.STATUS_PASS
    clean = bridge.publication_safe_record(
        record,
        design_methodology=bridge.EN1992_2_DK_NA,
        fatigue_context=fatigue_analysis.bridge_publication_context(scalars),
        danish_basis_context=bridge_inputs.danish_basis_context(
            _project_inputs(scalars)
        ),
        danish_fck_mpa=scalars["conc_fck"],
        danish_crack_context=_dk_crack_context(),
    )
    assert clean["publication_validation"]["status"] == "ACCEPTED"
    assert next(
        row for row in clean["checks"] if row["check_id"] == check_id
    )["status"] == expected["status"]

    attacked = copy.deepcopy(record)
    attacked_check = next(
        row for row in attacked["checks"] if row["check_id"] == check_id
    )
    attacked_check["status"] = bridge.STATUS_PASS
    attacked["status"] = bridge.STATUS_PASS
    attacked["evidence_fingerprint"] = bridge.bridge_evidence_fingerprint(
        attacked["checks"],
        attacked["configuration_errors"],
        methodology=bridge.EN1992_2_DK_NA,
        danish_basis_context=attacked["danish_basis"],
    )

    safe = bridge.publication_safe_record(
        attacked,
        design_methodology=bridge.EN1992_2_DK_NA,
        fatigue_context=fatigue_analysis.bridge_publication_context(scalars),
        danish_basis_context=bridge_inputs.danish_basis_context(
            _project_inputs(scalars)
        ),
        danish_fck_mpa=scalars["conc_fck"],
        danish_crack_context=_dk_crack_context(),
    )
    assert safe["status"] == bridge.STATUS_INVALID
    assert safe["publication_validation"]["status"] == "REJECTED"
    assert any(
        f"{check_id}: stored Danish derived check conflicts" in error
        for error in safe["publication_validation"]["errors"]
    )


@pytest.mark.parametrize(
    "bad_fck",
    [None, True, np.bool_(False), "40", float("nan"), float("inf"), 0.0],
)
def test_danish_publication_requires_current_typed_positive_fck(bad_fck):
    scalars = _project_scalars()
    safe = bridge.publication_safe_record(
        _dk_methodology_record(),
        design_methodology=bridge.EN1992_2_DK_NA,
        fatigue_context=fatigue_analysis.bridge_publication_context(scalars),
        danish_basis_context=bridge_inputs.danish_basis_context(
            _project_inputs(scalars)
        ),
        danish_fck_mpa=bad_fck,
        danish_crack_context=_dk_crack_context(),
    )
    assert safe["status"] == bridge.STATUS_INVALID
    assert safe["publication_validation"]["status"] == "REJECTED"
    assert any(
        "current Danish bridge fck" in error
        for error in safe["publication_validation"]["errors"]
    )


def test_project_publication_latches_rebound_danish_check_forgery():
    scalars = _project_scalars(
        bridge_alpha_ct=0.8,
        bridge_alpha_ct_basis=conformance.CUSTOM_BASIS,
        bridge_alpha_ct_custom_methodology="Project tensile model",
        bridge_alpha_ct_approval_reference="DB-05 / checker 04",
    )
    record = _dk_methodology_record(
        bridge_alpha_ct=0.8,
        bridge_alpha_ct_basis=conformance.CUSTOM_BASIS,
        bridge_alpha_ct_custom_methodology="Project tensile model",
        bridge_alpha_ct_approval_reference="DB-05 / checker 04",
    )
    coefficient = next(
        row
        for row in record["checks"]
        if row["check_id"] == "dk_concrete_coefficients"
    )
    assert coefficient["status"] == bridge.STATUS_REVIEW
    coefficient["status"] = bridge.STATUS_PASS
    record["status"] = bridge.STATUS_PASS
    record["evidence_fingerprint"] = bridge.bridge_evidence_fingerprint(
        record["checks"],
        record["configuration_errors"],
        methodology=bridge.EN1992_2_DK_NA,
        danish_basis_context=record["danish_basis"],
    )
    tables = _project_tables()
    digest = project_io.input_sha256(tables, scalars)
    text = project_io.dump_project(
        tables,
        scalars,
        calculation={
            "performed_at_utc": "2026-07-28T12:00:00+00:00",
            "sector_version": "0.91",
            "source_revision": "pr05-review-attack",
            "input_sha256": digest,
            "bridge_methodology": record,
        },
    )
    provenance = project_io.project_provenance(text)
    assert provenance["calculation"]["matches_saved_inputs"] is False
    assert (
        provenance["calculation"]["bridge_methodology"]
        ["publication_validation"]["status"]
        == "REJECTED"
    )


def test_project_calculation_record_rejects_basis_mutation_after_save():
    scalars = _project_scalars()
    tables = _project_tables()
    digest = project_io.input_sha256(tables, scalars)
    text = project_io.dump_project(
        tables,
        scalars,
        calculation={
            "performed_at_utc": "2026-07-28T12:00:00+00:00",
            "sector_version": "0.91",
            "source_revision": "pr05-test",
            "input_sha256": digest,
            "bridge_methodology": _dk_methodology_record(),
        },
    )
    accepted = project_io.project_provenance(text)
    assert accepted["calculation"]["matches_saved_inputs"] is True
    assert (
        accepted["calculation"]["bridge_methodology"]
        ["publication_validation"]["status"]
        == "ACCEPTED"
    )

    payload = json.loads(text)
    payload["scalars"]["bridge_environment_class"] = (
        danish_bridge.ENVIRONMENT_EXTRA_AGGRESSIVE
    )
    attacked = project_io.project_provenance(json.dumps(payload))
    assert attacked["input_hash_valid"] is False
    assert attacked["calculation"]["matches_saved_inputs"] is False
    assert (
        attacked["calculation"]["bridge_methodology"]
        ["publication_validation"]["status"]
        == "REJECTED"
    )


@pytest.mark.parametrize(
    "check_id",
    ["sls_crack", "dk_direct_crack_method"],
)
def test_publication_rejects_rebound_danish_crack_verdict_forgery(check_id):
    """A bridge-body fingerprint is not current crack-response evidence."""

    scalars = _project_scalars()
    record = _dk_methodology_record()
    attacked = copy.deepcopy(record)
    attacked_check = next(
        row for row in attacked["checks"] if row["check_id"] == check_id
    )
    assert attacked_check["status"] == bridge.STATUS_NOT_APPLICABLE
    attacked_check.update(
        status=bridge.STATUS_PASS,
        result="Forged Danish crack acceptance",
        criterion="Forged criterion",
        source="Forged self-consistent source",
        reason="Forged self-consistent reason",
        evidence=[{
            "criterion_id": "bridge-dk-standard-durability",
            "kind": bridge.DANISH_DIRECT_CRACK_KIND,
            "status": bridge.STATUS_PASS,
            "result": "0.090 mm",
            "solver_provenance": {"solver": "forged"},
            "acceptance_evidence": {"schema": "forged"},
        }],
    )
    attacked["status"] = bridge.STATUS_PASS
    attacked["evidence_fingerprint"] = bridge.bridge_evidence_fingerprint(
        attacked["checks"],
        attacked["configuration_errors"],
        methodology=bridge.EN1992_2_DK_NA,
        danish_basis_context=attacked["danish_basis"],
    )

    safe = bridge.publication_safe_record(
        attacked,
        design_methodology=bridge.EN1992_2_DK_NA,
        fatigue_context=fatigue_analysis.bridge_publication_context(scalars),
        danish_basis_context=bridge_inputs.danish_basis_context(
            _project_inputs(scalars)
        ),
        danish_fck_mpa=scalars["conc_fck"],
        danish_crack_context=_dk_crack_context(),
    )
    assert safe["status"] == bridge.STATUS_INVALID
    assert safe["publication_validation"]["status"] == "REJECTED"
    assert any(
        f"{check_id}: stored Danish derived check conflicts" in error
        for error in safe["publication_validation"]["errors"]
    )


def test_live_and_saved_danish_crack_context_reconstruct_identical_verdicts():
    record, results, decisions = _dk_crack_methodology_record(width=0.31)
    scalars = _project_scalars()
    inp = {
        **scalars,
        **_project_tables(decisions),
    }
    crack = next(
        row for row in record["checks"] if row["check_id"] == "sls_crack"
    )
    direct = next(
        row
        for row in record["checks"]
        if row["check_id"] == "dk_direct_crack_method"
    )
    assert crack["status"] == bridge.STATUS_FAIL
    assert direct["status"] == bridge.STATUS_PASS

    live_context = bridge_analysis.danish_crack_publication_context(
        inp,
        results,
    )
    saved_context = bridge_analysis.danish_crack_publication_context(
        inp,
        crack_control_record=_dk_crack_control_record(results),
    )
    assert saved_context == live_context

    for context in (live_context, saved_context):
        safe = bridge.publication_safe_record(
            record,
            design_methodology=bridge.EN1992_2_DK_NA,
            fatigue_context=fatigue_analysis.bridge_publication_context(
                scalars
            ),
            danish_basis_context=bridge_inputs.danish_basis_context(
                _project_inputs(scalars, decisions)
            ),
            danish_fck_mpa=scalars["conc_fck"],
            danish_crack_context=context,
        )
        assert safe["publication_validation"]["status"] == "ACCEPTED"
        assert next(
            row
            for row in safe["checks"]
            if row["check_id"] == "sls_crack"
        )["status"] == bridge.STATUS_FAIL


@pytest.mark.parametrize(
    "context",
    [
        None,
        {"schema": bridge.DANISH_CRACK_PUBLICATION_CONTEXT_SCHEMA},
        {
            **_dk_crack_context(),
            "crack": {
                **_dk_crack_context()["crack"],
                "utilisation": True,
            },
        },
    ],
)
def test_danish_publication_rejects_missing_or_malformed_crack_context(
    context,
):
    scalars = _project_scalars()
    safe = bridge.publication_safe_record(
        _dk_methodology_record(),
        design_methodology=bridge.EN1992_2_DK_NA,
        fatigue_context=fatigue_analysis.bridge_publication_context(scalars),
        danish_basis_context=bridge_inputs.danish_basis_context(
            _project_inputs(scalars)
        ),
        danish_fck_mpa=scalars["conc_fck"],
        danish_crack_context=context,
    )
    assert safe["status"] == bridge.STATUS_INVALID
    assert safe["publication_validation"]["status"] == "REJECTED"
    assert any(
        "Danish crack" in error
        for error in safe["publication_validation"]["errors"]
    )


def test_project_crack_sibling_rejects_bridge_forgery_and_latches_resave():
    record, results, decisions = _dk_crack_methodology_record(width=0.31)
    sibling = _dk_crack_control_record(results)
    scalars = _project_scalars()
    tables = _project_tables(decisions)
    digest = project_io.input_sha256(tables, scalars)
    calculation = {
        "performed_at_utc": "2026-07-28T12:00:00+00:00",
        "sector_version": "0.91",
        "source_revision": "pr05-crack-correlation",
        "input_sha256": digest,
        "crack_control": sibling,
        "bridge_methodology": record,
    }
    clean_text = project_io.dump_project(
        tables,
        scalars,
        calculation=calculation,
    )
    clean = project_io.project_provenance(clean_text)["calculation"]
    assert clean["matches_saved_inputs"] is True
    assert (
        clean["bridge_methodology"]["publication_validation"]["status"]
        == "ACCEPTED"
    )

    attacked = copy.deepcopy(record)
    crack = next(
        row
        for row in attacked["checks"]
        if row["check_id"] == "sls_crack"
    )
    crack["status"] = bridge.STATUS_PASS
    crack["result"] = "0.010 mm"
    attacked["status"] = bridge.STATUS_PASS
    attacked["evidence_fingerprint"] = bridge.bridge_evidence_fingerprint(
        attacked["checks"],
        attacked["configuration_errors"],
        methodology=bridge.EN1992_2_DK_NA,
        danish_basis_context=attacked["danish_basis"],
    )
    attacked_text = project_io.dump_project(
        tables,
        scalars,
        calculation={
            **calculation,
            "bridge_methodology": attacked,
        },
    )
    attacked_provenance = project_io.project_provenance(attacked_text)
    attacked_calculation = attacked_provenance["calculation"]
    assert attacked_calculation["matches_saved_inputs"] is False
    assert (
        attacked_calculation["bridge_methodology"]
        ["publication_validation"]["status"]
        == "REJECTED"
    )

    loaded_tables, loaded_scalars = project_io.parse_project(attacked_text)
    resaved_text = project_io.dump_project(
        loaded_tables,
        loaded_scalars,
        calculation=attacked_calculation,
    )
    resaved = project_io.project_provenance(resaved_text)["calculation"]
    assert resaved["matches_saved_inputs"] is False
    assert (
        resaved["bridge_methodology"]["publication_validation"]["status"]
        == "REJECTED"
    )


def test_bridge_summary_rejects_rebound_danish_crack_verdict():
    record, results, decisions = _dk_crack_methodology_record(width=0.31)
    scalars = _project_scalars()
    inp = {
        **scalars,
        **_project_tables(decisions),
    }
    attacked = copy.deepcopy(record)
    crack = next(
        row
        for row in attacked["checks"]
        if row["check_id"] == "sls_crack"
    )
    crack["status"] = bridge.STATUS_PASS
    crack["result"] = "0.010 mm"
    attacked["evidence_fingerprint"] = bridge.bridge_evidence_fingerprint(
        attacked["checks"],
        attacked["configuration_errors"],
        methodology=bridge.EN1992_2_DK_NA,
        danish_basis_context=attacked["danish_basis"],
    )

    rows = bridge_analysis.presentation.bridge_summary_rows(
        inp,
        {
            **results,
            "bridge_methodology": attacked,
        },
    )
    assert any(
        row["check"] == "Bridge methodology configuration"
        and row["status"] == bridge.STATUS_INVALID
        and "sls_crack: stored Danish derived check conflicts" in row["note"]
        for row in rows
    )
