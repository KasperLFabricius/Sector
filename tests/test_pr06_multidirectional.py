"""Independent-oracle and fail-closed regressions for PR-06."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import project_io  # noqa: E402
import result_presentation  # noqa: E402
from sector import danish_bridge, multidirectional, sls  # noqa: E402
from tools.pr06_multidirectional_oracle import (  # noqa: E402
    benchmark_matrix,
    crack_dk_2004,
    crack_en_2023_g5,
    planar_resultant,
    project_power_sum,
    rotate,
)


def _canonical_fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _reseal_result(record):
    record = copy.deepcopy(record)
    record.pop("evidence_fingerprint", None)
    record["evidence_fingerprint"] = _canonical_fingerprint(record)
    return record


def _reseal_bundle(bundle):
    bundle = copy.deepcopy(bundle)
    bundle.pop("fingerprint", None)
    bundle.pop("publication_validation", None)
    bundle["fingerprint"] = _canonical_fingerprint(bundle)
    return bundle


def _crack_results(
    *,
    case_id="SLS-01",
    criterion_id="qa-width",
    combination=sls.COMBINATION_QUASI_PERMANENT,
    limit_mm=0.3,
    width_mm=0.22,
):
    contexts = {
        "QP": {
            "combination": combination,
            "duration": "long",
            "response_id": "qp-current",
            "provenance": "pr06-map-v1",
            "solver_provenance": {
                "solve": "pr06-current",
                "converged": True,
            },
        },
    }
    scope = [{
        "combination": combination,
        "duration": "long",
        "response": "QP",
        "response_id": "qp-current",
        "elastic_case": case_id,
        "state": "long",
        "provenance": "pr06-map-v1",
        "solver_provenance": {
            "solve": "pr06-current",
            "converged": True,
        },
    }]
    responses = {
        "QP": {
            "wk": width_mm,
            "element_id": "R-QA",
        },
    }
    assessment = sls.crack_assessment(
        responses,
        valid=True,
        criteria=[{
            "id": criterion_id,
            "kind": sls.CRITERION_DURABILITY,
            "source_type": sls.CRITERION_MODE_STANDARD,
            "source": "PR-06 controlled durability criterion",
            "required_combination": combination,
            "limit_mm": limit_mm,
            "applicability": {"member": "reinforced"},
        }],
        response_contexts=contexts,
        response_mapping_scope=scope,
    )
    assert assessment["criteria"][0]["status"] == "OK"
    elastic = {
        "elastic_case": {"id": case_id},
        "show_cw": True,
        "cracked": True,
        "crack_assessment": assessment,
        "crack_responses": responses,
        "crack_response_contexts": contexts,
        "crack_response_mapping_scope": scope,
    }
    return {"elastic": elastic}


def _crack_input(method):
    values = multidirectional.crack_configuration({})
    values.update({
        "crack_interaction_on": True,
        "crack_interaction_method": method,
        "crack_interaction_case_id": "SLS-01",
        "crack_interaction_criterion_id": "qa-width",
        "crack_interaction_combination": sls.COMBINATION_QUASI_PERMANENT,
        "crack_interaction_axis_x": "deck longitudinal reinforcement",
        "crack_interaction_axis_y": "deck transverse reinforcement",
    })
    return values


def _direction(
    component,
    demand,
    resistance,
    *,
    signed=None,
    width=1000.0,
    depth=500.0,
    method=multidirectional.SHEAR_CODE_EN_2023,
):
    return {
        "component": component,
        "axis": "y" if component == "vx" else "x",
        "v_ed": abs(float(demand)),
        "signed_v_ed": float(demand if signed is None else signed),
        "bw": float(width),
        "d": float(depth),
        "method": method,
        "status": "PASS" if abs(demand) <= resistance else "FAIL",
        "util": abs(float(demand)) / float(resistance),
        "res": {
            "valid": True,
            "vrd_c": float(resistance),
        },
        "governing_face": "negative",
    }


def _shear_case(
    vx,
    rx,
    vy,
    ry,
    *,
    width_x=1000.0,
    width_y=1000.0,
    depth_x=500.0,
    depth_y=500.0,
    method=multidirectional.SHEAR_CODE_EN_2023,
):
    directions = {
        "vx": _direction(
            "vx", vx, rx, width=width_x, depth=depth_x, method=method
        ),
        "vy": _direction(
            "vy", vy, ry, width=width_y, depth=depth_y, method=method
        ),
    }
    return {
        "shear": {
            "directions": directions,
            "active_directions": ["vx", "vy"],
            "biaxial": True,
            "status": (
                "FAIL"
                if any(item["status"] == "FAIL" for item in directions.values())
                else "REVIEW"
            ),
            "interaction_assessed": False,
            "interaction_status": "NOT ASSESSED",
        },
    }


def _shear_input(method=multidirectional.SHEAR_METHOD_PROJECT):
    values = multidirectional.shear_configuration({})
    values.update({
        "shear_interaction_on": True,
        "shear_interaction_method": method,
        "shear_interaction_axis_x": "global x / Vx",
        "shear_interaction_axis_y": "global y / Vy",
        "shear_interaction_domain_confirmed": True,
        "shear_interaction_exponent": 2.0,
        "shear_interaction_source": "Project DB clause INT-06",
        "shear_interaction_approval": "Checker approval QA-06",
    })
    return values


def test_independent_oracle_covers_limits_boundary_and_symmetries():
    matrix = benchmark_matrix()
    points = matrix["points"]
    assert points["x_limit"]["utilisation"] == pytest.approx(1.0)
    assert points["y_limit"]["utilisation"] == pytest.approx(1.0)
    assert points["zero"]["utilisation"] == pytest.approx(0.0)
    assert points["balanced"]["utilisation"] == pytest.approx(1.0)
    assert points["below"]["passes"] is True
    assert points["above"]["passes"] is False
    assert matrix["swap_invariant"] is True
    assert matrix["sign_invariant"] is True
    assert matrix["rigid_rotation_invariant"] is True
    assert matrix["anisotropic_rotation_invariant"] is False


@pytest.mark.parametrize(
    ("vx", "vy"),
    [
        (1.0, 0.0),
        (0.0, 1.0),
        (math.sqrt(0.5), math.sqrt(0.5)),
        (
            math.sqrt(0.5) * (1.0 - 1.0e-8),
            math.sqrt(0.5) * (1.0 - 1.0e-8),
        ),
        (
            math.sqrt(0.5) * (1.0 + 1.0e-8),
            math.sqrt(0.5) * (1.0 + 1.0e-8),
        ),
    ],
)
def test_project_shear_power_sum_matches_independent_oracle(vx, vy):
    result = multidirectional.assess_shear_interaction(
        _shear_input(),
        _shear_case(vx, 1.0, vy, 1.0),
        case_id="ULS-01",
    )
    assert result["utilisation"] == pytest.approx(
        project_power_sum(vx, 1.0, vy, 1.0, 2.0),
        rel=1.0e-12,
    )
    assert result["verdict"].startswith("APPROVED CUSTOM")
    assert result["qualification"] == "APPROVED CUSTOM"


def test_shear_power_sum_swap_sign_and_rotation_properties_are_explicit():
    base = multidirectional.assess_shear_interaction(
        _shear_input(),
        _shear_case(0.8, 1.0, 0.3, 1.0),
    )
    swapped = multidirectional.assess_shear_interaction(
        _shear_input(),
        _shear_case(0.3, 1.0, 0.8, 1.0),
    )
    reversed_sign = multidirectional.assess_shear_interaction(
        _shear_input(),
        _shear_case(-0.8, 1.0, -0.3, 1.0),
    )
    rotated = rotate(0.8, 0.3, 37.0)
    rigid = multidirectional.assess_shear_interaction(
        _shear_input(),
        _shear_case(rotated[0], 1.0, rotated[1], 1.0),
    )
    anisotropic = multidirectional.assess_shear_interaction(
        _shear_input(),
        _shear_case(rotated[0], 1.0, rotated[1], 2.0),
    )

    assert swapped["utilisation"] == pytest.approx(base["utilisation"])
    assert reversed_sign["utilisation"] == pytest.approx(base["utilisation"])
    assert rigid["utilisation"] == pytest.approx(base["utilisation"])
    assert base["rotationally_invariant"] is True
    assert anisotropic["rotationally_invariant"] is False
    assert anisotropic["utilisation"] != pytest.approx(base["utilisation"])


def test_false_pass_probe_retains_components_but_no_method_never_aggregates_pass():
    case = _shear_case(0.2, 1.0, 0.3, 1.0)
    inputs = {
        **multidirectional.shear_configuration({}),
        **multidirectional.crack_configuration({}),
    }
    multidirectional.apply_to_results(inputs, case)

    shear = case["shear"]
    assert [item["status"] for item in shear["directions"].values()] == [
        "PASS",
        "PASS",
    ]
    assert shear["status"] == "REVIEW"
    assert shear["interaction"]["status"] == "NOT ASSESSED"
    assert shear["interaction_assessed"] is False
    assert "no biaxial shear interaction methodology" in (
        shear["interaction"]["reason"].lower()
    )


def test_enabled_not_assessed_selection_does_not_block_component_calculation():
    case = _shear_case(0.2, 1.0, 0.3, 1.0)
    inputs = {
        **multidirectional.crack_configuration({}),
        **multidirectional.shear_configuration({}),
        "shear_interaction_on": True,
    }

    assert multidirectional.validation_errors(inputs) == ()
    multidirectional.apply_to_results(inputs, case)
    assert all(
        item["status"] == "PASS"
        for item in case["shear"]["directions"].values()
    )
    assert case["shear"]["interaction"]["status"] == "NOT ASSESSED"
    assert case["shear"]["status"] == "REVIEW"


def test_project_method_pass_is_qualified_and_does_not_relabel_eurocode_aggregate():
    case = _shear_case(0.2, 1.0, 0.3, 1.0)
    inputs = {
        **multidirectional.crack_configuration({}),
        **_shear_input(),
    }
    multidirectional.apply_to_results(inputs, case)

    assert case["shear"]["interaction"]["verdict"] == "APPROVED CUSTOM PASS"
    assert case["shear"]["interaction"]["status"] == "PASS"
    assert case["shear"]["status"] == "REVIEW"
    assert set(case["shear"]["directions"]) == {"vx", "vy"}


def test_en_2023_planar_resultant_matches_oracle_and_stays_qualified():
    inputs = _shear_input(multidirectional.SHEAR_METHOD_EN_2023)
    inputs.update({
        "shear_interaction_planar_member": True,
        "shear_interaction_same_control_point": True,
        "shear_interaction_per_unit_width": True,
        "shear_interaction_out_of_plane": True,
        "shear_interaction_depth_route": (
            multidirectional.DEPTH_ROUTE_ROTATED
        ),
        "shear_interaction_resultant_resistance_kn_per_m": 300.0,
        "shear_interaction_source": "Directional resistance note SR-06",
        "shear_interaction_approval": "Independent checker IC-06",
    })
    case = _shear_case(
        90.0,
        500.0,
        240.0,
        500.0,
        width_x=500.0,
        width_y=1000.0,
        depth_x=400.0,
        depth_y=600.0,
    )
    result = multidirectional.assess_shear_interaction(
        inputs, case, case_id="ULS-PLANAR"
    )
    expected = planar_resultant(90.0, 500.0, 240.0, 1000.0)
    assert expected == pytest.approx(300.0)
    assert result["parameters"]["resultant_demand_kn_per_m"] == pytest.approx(
        expected
    )
    assert result["utilisation"] == pytest.approx(1.0)
    assert result["verdict"] == "QUALIFIED PASS"
    assert result["qualification"].startswith("QUALIFIED")


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("shear_interaction_planar_member", False, "planar"),
        ("shear_interaction_same_control_point", False, "control point"),
        ("shear_interaction_per_unit_width", False, "per-unit-width"),
        ("shear_interaction_out_of_plane", False, "out-of-plane"),
    ],
)
def test_en_2023_planar_method_fails_closed_outside_domain(field, value, reason):
    inputs = _shear_input(multidirectional.SHEAR_METHOD_EN_2023)
    inputs.update({
        "shear_interaction_planar_member": True,
        "shear_interaction_same_control_point": True,
        "shear_interaction_per_unit_width": True,
        "shear_interaction_out_of_plane": True,
        "shear_interaction_resultant_resistance_kn_per_m": 500.0,
    })
    inputs[field] = value
    result = multidirectional.assess_shear_interaction(
        inputs,
        _shear_case(100.0, 500.0, 100.0, 500.0),
    )
    assert result["status"] == "NOT ASSESSED"
    assert result["interaction_assessed"] is False
    assert reason in result["reason"]


def test_en_2023_planar_method_rejects_wrong_component_edition():
    inputs = _shear_input(multidirectional.SHEAR_METHOD_EN_2023)
    inputs.update({
        "shear_interaction_planar_member": True,
        "shear_interaction_same_control_point": True,
        "shear_interaction_per_unit_width": True,
        "shear_interaction_out_of_plane": True,
        "shear_interaction_resultant_resistance_kn_per_m": 500.0,
    })
    result = multidirectional.assess_shear_interaction(
        inputs,
        _shear_case(
            100.0,
            500.0,
            100.0,
            500.0,
            method="DS/EN 1992-1-1:2005 + DK NA:2024",
        ),
    )
    assert result["status"] == "NOT ASSESSED"
    assert "explicit DS/EN 1992-1-1:2023" in result["reason"]


@pytest.mark.parametrize(
    ("selected_code", "selected_edition"),
    [
        (multidirectional.CRACK_CODE_DK_2004, "2004"),
        (danish_bridge.METHODOLOGY, sls.EDITION_BRIDGE_DK_2015),
    ],
)
def test_dk_crack_formula_matches_independent_oracle_and_binding(
    selected_code,
    selected_edition,
):
    inputs = _crack_input(multidirectional.CRACK_METHOD_DK_2004)
    inputs.update({
        "sls_code": selected_code,
        "sls_edition": selected_edition,
        "crack_interaction_orthogonal": True,
        "crack_interaction_plane_stress": True,
        "crack_interaction_no_discontinuity": True,
        "crack_interaction_angle_deg": 40.0,
        "crack_interaction_spacing_x_mm": 120.0,
        "crack_interaction_spacing_y_mm": 180.0,
        "crack_interaction_strain_x": 0.0004,
        "crack_interaction_strain_y": 0.0005,
    })
    result = multidirectional.assess_crack_interaction(
        inputs, _crack_results()
    )
    spacing, strain, width = crack_dk_2004(
        40.0, 120.0, 180.0, 0.0004, 0.0005
    )
    assert result["parameters"]["combined_spacing_mm"] == pytest.approx(spacing)
    assert result["parameters"]["combined_strain"] == pytest.approx(strain)
    assert result["parameters"]["crack_width_mm"] == pytest.approx(width)
    assert result["criterion"]["acceptance_fingerprint"]
    assert result["status"] == "PASS"


def test_en_2023_crack_formula_matches_independent_oracle():
    inputs = _crack_input(multidirectional.CRACK_METHOD_EN_2023)
    inputs.update({
        "sls_code": multidirectional.CRACK_CODE_EN_2023,
        "sls_edition": "2023",
        "crack_interaction_orthogonal": True,
        "crack_interaction_membrane": True,
        "crack_interaction_no_discontinuity": True,
        "crack_interaction_angle_deg": 35.0,
        "crack_interaction_spacing_x_mm": 110.0,
        "crack_interaction_spacing_y_mm": 170.0,
        "crack_interaction_strain_x": 0.0003,
        "crack_interaction_strain_y": 0.0004,
        "crack_interaction_transverse_strain": -0.0002,
    })
    result = multidirectional.assess_crack_interaction(
        inputs, _crack_results()
    )
    spacing, strain, width = crack_en_2023_g5(
        35.0, 110.0, 170.0, 0.0003, 0.0004, -0.0002
    )
    assert result["parameters"]["combined_spacing_mm"] == pytest.approx(spacing)
    assert result["parameters"]["combined_strain"] == pytest.approx(strain)
    assert result["parameters"]["crack_width_mm"] == pytest.approx(width)
    assert result["status"] == "PASS"


def test_standard_methods_pass_semantic_publication_recomputation():
    dk_inputs = _crack_input(multidirectional.CRACK_METHOD_DK_2004)
    dk_inputs.update({
        "sls_code": multidirectional.CRACK_CODE_DK_2004,
        "sls_edition": "2004",
        "crack_interaction_orthogonal": True,
        "crack_interaction_plane_stress": True,
        "crack_interaction_no_discontinuity": True,
        "crack_interaction_angle_deg": 40.0,
        "crack_interaction_spacing_x_mm": 120.0,
        "crack_interaction_spacing_y_mm": 180.0,
        "crack_interaction_strain_x": 0.0004,
        "crack_interaction_strain_y": 0.0005,
    })
    dk_results = _crack_results()
    multidirectional.apply_to_results(dk_inputs, dk_results)
    dk_bundle = multidirectional.interaction_calculation_record(dk_results)
    assert multidirectional.publication_safe_interaction_record(
        dk_bundle,
        current_inputs=dk_inputs,
    )["publication_validation"]["status"] == "ACCEPTED"

    en_crack_inputs = _crack_input(multidirectional.CRACK_METHOD_EN_2023)
    en_crack_inputs.update({
        "sls_code": multidirectional.CRACK_CODE_EN_2023,
        "sls_edition": "2023",
        "crack_interaction_orthogonal": True,
        "crack_interaction_membrane": True,
        "crack_interaction_no_discontinuity": True,
        "crack_interaction_angle_deg": 35.0,
        "crack_interaction_spacing_x_mm": 110.0,
        "crack_interaction_spacing_y_mm": 170.0,
        "crack_interaction_strain_x": 0.0003,
        "crack_interaction_strain_y": 0.0004,
        "crack_interaction_transverse_strain": -0.0002,
    })
    en_crack_results = _crack_results()
    multidirectional.apply_to_results(en_crack_inputs, en_crack_results)
    en_crack_bundle = multidirectional.interaction_calculation_record(
        en_crack_results
    )
    assert multidirectional.publication_safe_interaction_record(
        en_crack_bundle,
        current_inputs=en_crack_inputs,
    )["publication_validation"]["status"] == "ACCEPTED"

    shear_inputs = _shear_input(multidirectional.SHEAR_METHOD_EN_2023)
    shear_inputs.update({
        "shear_method": multidirectional.SHEAR_CODE_EN_2023,
        "shear_interaction_planar_member": True,
        "shear_interaction_same_control_point": True,
        "shear_interaction_per_unit_width": True,
        "shear_interaction_out_of_plane": True,
        "shear_interaction_depth_route": (
            multidirectional.DEPTH_ROUTE_ROTATED
        ),
        "shear_interaction_resultant_resistance_kn_per_m": 300.0,
        "shear_interaction_source": "Directional resistance note SR-06",
        "shear_interaction_approval": "Independent checker IC-06",
    })
    shear_results = _shear_case(
        90.0,
        500.0,
        240.0,
        500.0,
        width_x=500.0,
        width_y=1000.0,
        depth_x=400.0,
        depth_y=600.0,
    )
    multidirectional.apply_to_results(shear_inputs, shear_results)
    shear_bundle = multidirectional.interaction_calculation_record(
        shear_results
    )
    assert multidirectional.publication_safe_interaction_record(
        shear_bundle,
        current_inputs=shear_inputs,
    )["publication_validation"]["status"] == "ACCEPTED"


@pytest.mark.parametrize(
    ("scale", "expected"),
    [
        (1.0 - 1.0e-8, "PASS"),
        (1.0, "PASS"),
        (1.0 + 1.0e-8, "FAIL"),
    ],
)
def test_project_crack_boundary_matches_independent_oracle(scale, expected):
    component = math.sqrt(0.5) * 0.3 * scale
    inputs = _crack_input(multidirectional.CRACK_METHOD_PROJECT)
    inputs.update({
        "crack_interaction_domain_confirmed": True,
        "crack_interaction_component_x_mm": component,
        "crack_interaction_component_y_mm": component,
        "crack_interaction_limit_x_mm": 0.3,
        "crack_interaction_limit_y_mm": 0.3,
        "crack_interaction_exponent": 2.0,
        "crack_interaction_source": "Project crack note CR-06",
        "crack_interaction_approval": "Approved by checker AC-06",
    })
    result = multidirectional.assess_crack_interaction(
        inputs, _crack_results()
    )
    expected_util = project_power_sum(
        component, 0.3, component, 0.3, 2.0
    )
    assert result["utilisation"] == pytest.approx(expected_util)
    assert result["status"] == expected
    assert result["verdict"].startswith("APPROVED CUSTOM")


def test_crack_interaction_is_separate_from_history_and_combination_routing():
    results = _crack_results()
    canonical_before = copy.deepcopy(results["elastic"]["crack_assessment"])
    inputs = _crack_input(multidirectional.CRACK_METHOD_PROJECT)
    inputs.update({
        "crack_interaction_domain_confirmed": True,
        "crack_interaction_component_x_mm": 0.1,
        "crack_interaction_component_y_mm": 0.1,
        "crack_interaction_limit_x_mm": 0.3,
        "crack_interaction_limit_y_mm": 0.3,
        "crack_interaction_source": "CR-06",
        "crack_interaction_approval": "AC-06",
    })
    result = multidirectional.assess_crack_interaction(inputs, results)
    assert result["status"] == "PASS"
    assert results["elastic"]["cracked"] is True
    assert results["elastic"]["crack_assessment"] == canonical_before

    inputs["crack_interaction_combination"] = sls.COMBINATION_FREQUENT
    wrong_route = multidirectional.assess_crack_interaction(inputs, results)
    assert wrong_route["status"] == "INVALID"
    assert "does not match the current criterion" in wrong_route["reason"]


def test_crack_method_edition_switch_invalidates_the_conclusion():
    inputs = _crack_input(multidirectional.CRACK_METHOD_EN_2023)
    inputs.update({
        "sls_code": multidirectional.CRACK_CODE_DK_2004,
        "sls_edition": "2005",
        "crack_interaction_orthogonal": True,
        "crack_interaction_membrane": True,
        "crack_interaction_no_discontinuity": True,
    })
    result = multidirectional.assess_crack_interaction(
        inputs, _crack_results()
    )
    assert result["status"] == "NOT ASSESSED"
    assert "requires the explicit EN 1992-1-1:2023" in result["reason"]


@pytest.mark.parametrize(
    ("selected_code", "selected_edition"),
    [
        (multidirectional.CRACK_CODE_DK_2004, "2023"),
        (multidirectional.CRACK_CODE_EN_2023, "2004"),
    ],
)
def test_contradictory_2023_crack_code_and_edition_fail_closed(
    selected_code,
    selected_edition,
):
    inputs = _crack_input(multidirectional.CRACK_METHOD_EN_2023)
    inputs.update({
        "sls_code": selected_code,
        "sls_edition": selected_edition,
        "crack_interaction_orthogonal": True,
        "crack_interaction_membrane": True,
        "crack_interaction_no_discontinuity": True,
    })

    result = multidirectional.assess_crack_interaction(
        inputs,
        _crack_results(),
    )

    assert result["status"] == "NOT ASSESSED"
    assert "requires the explicit EN 1992-1-1:2023" in result["reason"]


@pytest.mark.parametrize(
    ("mutate_inputs", "expected_status"),
    [
        (
            {
                "sls_code": multidirectional.CRACK_CODE_DK_2004,
                "sls_edition": "2004",
            },
            "NOT ASSESSED",
        ),
        (
            {"crack_interaction_criterion_id": "missing-criterion"},
            "INVALID",
        ),
    ],
)
def test_failed_crack_interaction_is_attached_to_selected_elastic_case(
    mutate_inputs,
    expected_status,
):
    target = _crack_results()
    target_elastic = target.pop("elastic")
    results = {
        "elastic_cases": [
            {
                "name": "SLS-01",
                "results": {"elastic": target_elastic},
            },
            {
                "name": "SLS-OTHER",
                "results": {"elastic": copy.deepcopy(target_elastic)},
            },
        ],
    }
    results["elastic_cases"][1]["results"]["elastic"][
        "crack_interaction"
    ] = {"status": "PASS", "stale": True}
    inputs = _crack_input(multidirectional.CRACK_METHOD_EN_2023)
    inputs.update({
        "sls_code": multidirectional.CRACK_CODE_EN_2023,
        "sls_edition": "2023",
        **mutate_inputs,
    })

    multidirectional.apply_to_results(inputs, results)

    top = results["crack_interaction"]
    target_record = results["elastic_cases"][0]["results"]["elastic"][
        "crack_interaction"
    ]
    assert top["status"] == expected_status
    assert target_record == top
    assert (
        "crack_interaction"
        not in results["elastic_cases"][1]["results"]["elastic"]
    )


def test_crack_stale_duplicate_and_missing_evidence_fail_closed():
    inputs = _crack_input(multidirectional.CRACK_METHOD_PROJECT)
    inputs.update({
        "crack_interaction_domain_confirmed": True,
        "crack_interaction_component_x_mm": 0.1,
        "crack_interaction_component_y_mm": 0.1,
        "crack_interaction_limit_x_mm": 0.3,
        "crack_interaction_limit_y_mm": 0.3,
        "crack_interaction_source": "CR-06",
        "crack_interaction_approval": "AC-06",
    })

    stale = _crack_results()
    stale["elastic"]["crack_responses"]["QP"]["wk"] = 0.29
    assert multidirectional.assess_crack_interaction(
        inputs, stale
    )["status"] == "INVALID"

    duplicate = _crack_results()
    duplicate["elastic"]["crack_assessment"]["criteria"].append(
        copy.deepcopy(
            duplicate["elastic"]["crack_assessment"]["criteria"][0]
        )
    )
    assert multidirectional.assess_crack_interaction(
        inputs, duplicate
    )["status"] == "INVALID"

    missing = _crack_results()
    missing["elastic"].pop("crack_response_mapping_scope")
    assert multidirectional.assess_crack_interaction(
        inputs, missing
    )["status"] == "INVALID"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("shear_interaction_exponent", True),
        ("shear_interaction_exponent", math.nan),
        ("shear_interaction_exponent", math.inf),
        ("shear_interaction_on", 1),
        ("shear_interaction_method", ["not", "a", "selection"]),
        ("shear_interaction_source", ["not", "text"]),
    ],
)
def test_malformed_boolean_nonfinite_and_text_shear_values_fail_closed(
    field, value
):
    inputs = _shear_input()
    inputs[field] = value
    result = multidirectional.assess_shear_interaction(
        inputs, _shear_case(0.2, 1.0, 0.3, 1.0)
    )
    assert result["status"] == "INVALID"
    assert result["interaction_assessed"] is False


def test_positive_custom_parameters_are_preserved_even_when_nonstandard():
    inputs = _shear_input()
    inputs["shear_interaction_exponent"] = 0.37
    result = multidirectional.assess_shear_interaction(
        inputs, _shear_case(0.2, 1.0, 0.3, 1.0)
    )
    assert result["parameters"]["exponent"] == pytest.approx(0.37)
    assert result["qualification"] == "APPROVED CUSTOM"
    assert result["utilisation"] == pytest.approx(
        project_power_sum(0.2, 1.0, 0.3, 1.0, 0.37)
    )
    assert result["status"] == "FAIL"

    extreme_inputs = _shear_input()
    extreme_inputs["shear_interaction_exponent"] = 1.0e308
    extreme_case = _shear_case(2.0, 1.0, 0.0, 1.0)
    extreme = multidirectional.assess_shear_interaction(
        extreme_inputs, extreme_case
    )
    assert extreme["parameters"]["exponent"] == pytest.approx(1.0e308)
    assert extreme["calculation_saturated"] is True
    assert math.isfinite(extreme["utilisation"])
    assert extreme["status"] == "FAIL"
    multidirectional.apply_to_results(extreme_inputs, extreme_case)
    extreme_bundle = multidirectional.interaction_calculation_record(
        extreme_case
    )
    published = multidirectional.publication_safe_interaction_record(
        extreme_bundle,
        current_inputs=extreme_inputs,
    )
    assert published["publication_validation"]["status"] == "ACCEPTED"

    tampered = copy.deepcopy(extreme_bundle)
    interaction = tampered["shear_cases"][0]["interaction"]
    interaction["calculation_saturated"] = False
    tampered["shear_cases"][0]["interaction"] = _reseal_result(interaction)
    tampered = _reseal_bundle(tampered)
    rejected = multidirectional.publication_safe_interaction_record(
        tampered,
        current_inputs=extreme_inputs,
    )
    assert rejected["publication_validation"]["status"] == "REJECTED"
    assert any(
        "finite-range marker contradicts" in issue
        for issue in rejected["publication_validation"]["issues"]
    )

    crack_inputs = _crack_input(multidirectional.CRACK_METHOD_PROJECT)
    crack_inputs.update({
        "crack_interaction_domain_confirmed": True,
        "crack_interaction_component_x_mm": 2.5,
        "crack_interaction_component_y_mm": 3.0,
        "crack_interaction_limit_x_mm": 1001.0,
        "crack_interaction_limit_y_mm": 1201.0,
        "crack_interaction_exponent": 137.0,
        "crack_interaction_source": "Project crack note CR-CUSTOM",
        "crack_interaction_approval": "Checker approval AC-CUSTOM",
    })
    crack = multidirectional.assess_crack_interaction(
        crack_inputs, _crack_results()
    )
    assert crack["parameters"] == {
        "exponent": 137.0,
        "limit_x_mm": 1001.0,
        "limit_y_mm": 1201.0,
    }
    assert crack["qualification"] == "APPROVED CUSTOM"
    assert crack["status"] == "PASS"


def test_missing_or_inconsistent_shear_component_evidence_fails_closed():
    case = _shear_case(0.2, 1.0, 0.3, 1.0)
    case["shear"]["directions"]["vx"]["util"] = 0.1
    result = multidirectional.assess_shear_interaction(
        _shear_input(), case
    )
    assert result["status"] == "INVALID"
    assert "internally inconsistent" in result["reason"]

    unknown = _shear_case(0.2, 1.0, 0.3, 1.0)
    unknown["shear"]["directions"]["vz"] = copy.deepcopy(
        unknown["shear"]["directions"]["vy"]
    )
    result = multidirectional.assess_shear_interaction(
        _shear_input(), unknown
    )
    assert result["status"] == "INVALID"
    assert "unknown component identities" in result["reason"]


def test_live_rejection_marker_blocks_self_consistent_placeholder_values():
    inputs = _shear_input()
    inputs["invalid_interaction_input_keys"] = (
        "shear_interaction_method",
    )
    result = multidirectional.assess_shear_interaction(
        inputs, _shear_case(0.2, 1.0, 0.3, 1.0)
    )
    assert result["status"] == "INVALID"
    assert "live input boundary rejected" in result["reason"]
    assert multidirectional.validation_errors(inputs)


def test_uniaxial_fallback_retains_component_and_case_identity():
    results = _shear_case(0.2, 1.0, 0.3, 1.0)
    results["shear"]["directions"].pop("vy")
    results["shear"].update(
        active_directions=["vx"],
        biaxial=False,
        status="PASS",
    )
    interaction = multidirectional.assess_shear_interaction(
        _shear_input(),
        results,
        case_id="ULS-UNI",
    )

    assert interaction["status"] == "NOT APPLICABLE"
    assert interaction["case_id"] == "ULS-UNI"
    assert [item["id"] for item in interaction["components"]] == ["vx"]
    assert interaction["components"][0]["status"] == "PASS"


@pytest.mark.parametrize(
    ("malformed_field", "malformed_value"),
    [
        ("criterion", "not-an-evidence-object"),
        ("configuration", "not-a-configuration-object"),
    ],
)
def test_publication_rejects_malformed_crack_case_binding_without_crash(
    malformed_field,
    malformed_value,
):
    results = _crack_results()
    inputs = {
        **multidirectional.shear_configuration({}),
        **_crack_input(multidirectional.CRACK_METHOD_PROJECT),
    }
    inputs.update({
        "crack_interaction_domain_confirmed": True,
        "crack_interaction_component_x_mm": 0.1,
        "crack_interaction_component_y_mm": 0.1,
        "crack_interaction_limit_x_mm": 0.3,
        "crack_interaction_limit_y_mm": 0.3,
        "crack_interaction_source": "CR-06",
        "crack_interaction_approval": "AC-06",
    })
    multidirectional.apply_to_results(inputs, results)
    for record in (
        results["crack_interaction"],
        results["elastic"]["crack_interaction"],
    ):
        if malformed_field == "configuration":
            record["criterion"] = {}
        record[malformed_field] = malformed_value
        sealed = _reseal_result(record)
        record.clear()
        record.update(sealed)

    safe = multidirectional.publication_safe_results(
        results,
        current_inputs=inputs,
    )

    assert safe["crack_interaction"]["status"] == "NOT ASSESSED"
    assert (
        safe["crack_interaction"]["qualification"]
        == "PUBLICATION REJECTED"
    )
    assert safe["crack_interaction"]["publication_validation"][
        "status"
    ] == "REJECTED"


def test_publication_rejects_tampered_stale_duplicate_and_durable_evidence():
    results = _crack_results()
    inputs = {
        **multidirectional.shear_configuration({}),
        **_crack_input(multidirectional.CRACK_METHOD_PROJECT),
    }
    inputs.update({
        "crack_interaction_domain_confirmed": True,
        "crack_interaction_component_x_mm": 0.1,
        "crack_interaction_component_y_mm": 0.1,
        "crack_interaction_limit_x_mm": 0.3,
        "crack_interaction_limit_y_mm": 0.3,
        "crack_interaction_source": "CR-06",
        "crack_interaction_approval": "AC-06",
    })
    multidirectional.apply_to_results(inputs, results)
    bundle = multidirectional.interaction_calculation_record(results)
    accepted = multidirectional.publication_safe_interaction_record(
        bundle, current_inputs=inputs
    )
    assert accepted["publication_validation"]["status"] == "ACCEPTED"

    tampered = copy.deepcopy(bundle)
    tampered["crack"]["utilisation"] = 0.0
    rejected = multidirectional.publication_safe_interaction_record(
        tampered, current_inputs=inputs
    )
    assert rejected["publication_validation"]["status"] == "REJECTED"
    assert rejected["crack"]["status"] == "NOT ASSESSED"

    repaired_body = copy.deepcopy(tampered)
    repaired_body["crack"] = _reseal_result(repaired_body["crack"])
    repaired_body = _reseal_bundle(repaired_body)
    contradictory = multidirectional.publication_safe_interaction_record(
        repaired_body, current_inputs=inputs
    )
    assert contradictory["publication_validation"]["status"] == "REJECTED"
    assert any(
        "utilisation contradicts" in issue
        for issue in contradictory["publication_validation"]["issues"]
    )

    forged_formula = copy.deepcopy(bundle)
    forged_formula["crack"]["formula"] = (
        "eta = max(wk,x/wlim,x, wk,y/wlim,y)"
    )
    forged_formula["crack"] = _reseal_result(forged_formula["crack"])
    forged_formula = _reseal_bundle(forged_formula)
    formula_rejected = multidirectional.publication_safe_interaction_record(
        forged_formula,
        current_inputs=inputs,
    )
    assert formula_rejected["publication_validation"]["status"] == "REJECTED"
    assert any(
        "formula, authority, or domain is contradictory" in issue
        for issue in formula_rejected["publication_validation"]["issues"]
    )

    changed = copy.deepcopy(inputs)
    changed["crack_interaction_exponent"] = 3.0
    stale = multidirectional.publication_safe_interaction_record(
        bundle, current_inputs=changed
    )
    assert stale["publication_validation"]["status"] == "REJECTED"

    changed_edition = copy.deepcopy(inputs)
    changed_edition["sls_edition"] = "2023"
    edition_stale = multidirectional.publication_safe_interaction_record(
        bundle,
        current_inputs=changed_edition,
    )
    assert edition_stale["publication_validation"]["status"] == "REJECTED"
    assert any(
        "edition does not match" in issue
        for issue in edition_stale["publication_validation"]["issues"]
    )

    missing_crack = copy.deepcopy(bundle)
    missing_crack["crack"] = None
    missing_crack = _reseal_bundle(missing_crack)
    missing_crack_result = (
        multidirectional.publication_safe_interaction_record(
            missing_crack,
            current_inputs=inputs,
        )
    )
    assert missing_crack_result["publication_validation"]["status"] == (
        "REJECTED"
    )
    assert any(
        "active crack-interaction evidence is missing" in issue
        for issue in missing_crack_result["publication_validation"]["issues"]
    )

    duplicated_crack_results = copy.deepcopy(results)
    current_elastic = duplicated_crack_results.pop("elastic")
    duplicated_crack_results["elastic_cases"] = [
        {
            "name": "SLS-01",
            "results": {"elastic": copy.deepcopy(current_elastic)},
        },
        {
            "name": "SLS-OTHER",
            "results": {"elastic": copy.deepcopy(current_elastic)},
        },
    ]
    duplicate_crack_safe = multidirectional.publication_safe_results(
        duplicated_crack_results,
        current_inputs=inputs,
    )
    duplicate_crack_validation = duplicate_crack_safe[
        "_publication_interaction_bundle"
    ]["publication_validation"]
    assert duplicate_crack_validation["status"] == "REJECTED"
    assert any(
        "not represented exactly once" in issue
        for issue in duplicate_crack_validation["issues"]
    )

    duplicated = copy.deepcopy(bundle)
    if not duplicated["shear_cases"]:
        duplicated["shear_cases"] = [{
            "case": "ULS-01",
            "interaction": multidirectional.assess_shear_interaction(
                _shear_input(),
                _shear_case(0.2, 1.0, 0.3, 1.0),
                case_id="ULS-01",
            ),
        }]
    duplicated["shear_cases"].append(
        copy.deepcopy(duplicated["shear_cases"][0])
    )
    duplicated = _reseal_bundle(duplicated)
    duplicate_rejected = (
        multidirectional.publication_safe_interaction_record(
            duplicated,
            current_inputs={
                **inputs,
                **_shear_input(),
            },
        )
    )
    assert duplicate_rejected["publication_validation"]["status"] == "REJECTED"
    assert any(
        "duplicated" in issue
        for issue in duplicate_rejected["publication_validation"]["issues"]
    )

    durable = multidirectional.publication_safe_interaction_record(
        rejected, current_inputs=inputs
    )
    assert durable["publication_validation"]["status"] == "REJECTED"
    assert any(
        "prior publication boundary" in issue
        or "durable publication rejection" in issue
        for issue in durable["publication_validation"]["issues"]
    )


def test_publication_rejects_nested_evidence_when_bundle_fields_are_deleted():
    shear_inputs = {
        **multidirectional.crack_configuration({}),
        **_shear_input(),
    }
    shear_results = _shear_case(0.2, 1.0, 0.3, 1.0)
    multidirectional.apply_to_results(shear_inputs, shear_results)
    shear_results.pop("crack_interaction")
    shear_results.pop("shear_interactions")

    safe_shear = multidirectional.publication_safe_results(
        shear_results,
        current_inputs=shear_inputs,
    )
    assert set(safe_shear["shear"]["directions"]) == {"vx", "vy"}
    assert safe_shear["shear"]["interaction"]["status"] == "NOT ASSESSED"
    assert safe_shear["shear"]["interaction"]["qualification"] == (
        "PUBLICATION REJECTED"
    )

    no_shear_evidence = _shear_case(0.2, 1.0, 0.3, 1.0)
    no_shear_evidence["shear"]["status"] = "PASS"
    safe_without_any_shear_record = (
        multidirectional.publication_safe_results(
            no_shear_evidence,
            current_inputs=shear_inputs,
        )
    )
    assert set(
        safe_without_any_shear_record["shear"]["directions"]
    ) == {"vx", "vy"}
    assert safe_without_any_shear_record["shear"]["status"] == "REVIEW"
    assert safe_without_any_shear_record["shear"]["interaction"][
        "qualification"
    ] == "PUBLICATION REJECTED"
    assert (
        safe_without_any_shear_record["_publication_interaction_bundle"][
            "publication_validation"
        ]["status"]
        == "REJECTED"
    )

    crack_results = _crack_results()
    crack_inputs = {
        **multidirectional.shear_configuration({}),
        **_crack_input(multidirectional.CRACK_METHOD_PROJECT),
        "crack_interaction_domain_confirmed": True,
        "crack_interaction_component_x_mm": 0.1,
        "crack_interaction_component_y_mm": 0.1,
        "crack_interaction_limit_x_mm": 0.3,
        "crack_interaction_limit_y_mm": 0.3,
        "crack_interaction_source": "CR-06",
        "crack_interaction_approval": "AC-06",
    }
    multidirectional.apply_to_results(crack_inputs, crack_results)
    crack_results.pop("crack_interaction")
    crack_results.pop("shear_interactions")

    safe_crack = multidirectional.publication_safe_results(
        crack_results,
        current_inputs=crack_inputs,
    )
    assert safe_crack["elastic"]["crack_assessment"]["status"] == "OK"
    assert safe_crack["elastic"]["crack_interaction"]["status"] == (
        "NOT ASSESSED"
    )
    assert safe_crack["elastic"]["crack_interaction"]["qualification"] == (
        "PUBLICATION REJECTED"
    )

    no_crack_evidence = _crack_results()
    safe_without_any_crack_record = (
        multidirectional.publication_safe_results(
            no_crack_evidence,
            current_inputs=crack_inputs,
        )
    )
    assert safe_without_any_crack_record["elastic"]["crack_assessment"][
        "status"
    ] == "OK"
    assert safe_without_any_crack_record["elastic"]["crack_interaction"][
        "qualification"
    ] == "PUBLICATION REJECTED"


def test_publication_safe_results_retains_components_on_rejection():
    results = _shear_case(0.2, 1.0, 0.3, 1.0)
    inputs = {
        **multidirectional.crack_configuration({}),
        **_shear_input(),
    }
    multidirectional.apply_to_results(inputs, results)
    results["shear"]["interaction"]["utilisation"] = 0.0

    safe = multidirectional.publication_safe_results(
        results, current_inputs=inputs
    )
    assert set(safe["shear"]["directions"]) == {"vx", "vy"}
    assert all(
        item["status"] == "PASS"
        for item in safe["shear"]["directions"].values()
    )
    assert safe["shear"]["status"] == "REVIEW"
    assert safe["shear"]["interaction"]["status"] == "NOT ASSESSED"


def test_publication_reassesses_sealed_evidence_against_current_solver_results():
    shear_inputs = {
        **multidirectional.crack_configuration({}),
        **_shear_input(),
    }
    shear_results = _shear_case(0.2, 1.0, 0.3, 1.0)
    multidirectional.apply_to_results(shear_inputs, shear_results)
    forged_shear = copy.deepcopy(
        shear_results["shear"]["interaction"]
    )
    forged_shear["components"][0]["axis"] = "forged shear axis"
    forged_shear = _reseal_result(forged_shear)
    shear_results["shear"]["interaction"] = copy.deepcopy(forged_shear)
    shear_results["shear_interactions"][0]["interaction"] = copy.deepcopy(
        forged_shear
    )

    safe_shear = multidirectional.publication_safe_results(
        shear_results,
        current_inputs=shear_inputs,
    )
    shear_validation = safe_shear[
        "_publication_interaction_bundle"
    ]["publication_validation"]
    assert shear_validation["status"] == "REJECTED"
    assert any(
        "does not match current directional results" in issue
        for issue in shear_validation["issues"]
    )
    assert set(safe_shear["shear"]["directions"]) == {"vx", "vy"}

    crack_inputs = {
        **multidirectional.shear_configuration({}),
        **_crack_input(multidirectional.CRACK_METHOD_PROJECT),
        "crack_interaction_domain_confirmed": True,
        "crack_interaction_component_x_mm": 0.1,
        "crack_interaction_component_y_mm": 0.1,
        "crack_interaction_limit_x_mm": 0.3,
        "crack_interaction_limit_y_mm": 0.3,
        "crack_interaction_source": "CR-06",
        "crack_interaction_approval": "AC-06",
    }
    crack_results = _crack_results()
    multidirectional.apply_to_results(crack_inputs, crack_results)
    forged_crack = copy.deepcopy(crack_results["crack_interaction"])
    forged_crack["criterion"]["response_id"] = "forged-current-response"
    forged_crack = _reseal_result(forged_crack)
    crack_results["crack_interaction"] = copy.deepcopy(forged_crack)
    crack_results["elastic"]["crack_interaction"] = copy.deepcopy(
        forged_crack
    )

    safe_crack = multidirectional.publication_safe_results(
        crack_results,
        current_inputs=crack_inputs,
    )
    crack_validation = safe_crack[
        "_publication_interaction_bundle"
    ]["publication_validation"]
    assert crack_validation["status"] == "REJECTED"
    assert any(
        "does not match the current canonical crack results" in issue
        for issue in crack_validation["issues"]
    )
    assert safe_crack["elastic"]["crack_assessment"]["status"] == "OK"


def test_publication_rejects_missing_active_shear_and_method_switch():
    inputs = {
        **multidirectional.crack_configuration({}),
        **_shear_input(),
        "shear_method": multidirectional.SHEAR_CODE_EN_2023,
    }
    results = _shear_case(0.2, 1.0, 0.3, 1.0)
    multidirectional.apply_to_results(inputs, results)
    bundle = multidirectional.interaction_calculation_record(results)

    missing = copy.deepcopy(bundle)
    missing["shear_cases"] = []
    missing = _reseal_bundle(missing)
    rejected_missing = multidirectional.publication_safe_interaction_record(
        missing,
        current_inputs=inputs,
    )
    assert rejected_missing["publication_validation"]["status"] == "REJECTED"
    assert any(
        "active shear-interaction evidence is missing" in issue
        for issue in rejected_missing["publication_validation"]["issues"]
    )

    changed = copy.deepcopy(inputs)
    changed["shear_method"] = "DS/EN 1992-1-1:2005 + DK NA:2024"
    rejected_method = multidirectional.publication_safe_interaction_record(
        bundle,
        current_inputs=changed,
    )
    assert rejected_method["publication_validation"]["status"] == "REJECTED"
    assert any(
        "method edition does not match" in issue
        for issue in rejected_method["publication_validation"]["issues"]
    )


def test_project_save_load_resave_preserves_current_interaction_evidence():
    scalars = {
        **multidirectional.crack_configuration({}),
        **_shear_input(),
    }
    scalars["shear_interaction_exponent"] = 137.0
    results = _shear_case(0.2, 1.0, 0.3, 1.0)
    multidirectional.apply_to_results(scalars, results)
    record = multidirectional.interaction_calculation_record(results)
    digest = project_io.input_sha256({}, scalars)
    text = project_io.dump_project(
        {},
        scalars,
        calculation={
            "performed_at_utc": "2026-07-29T10:00:00+00:00",
            "sector_version": "0.91",
            "source_revision": "6" * 40,
            "input_sha256": digest,
            "multidirectional_interaction": record,
        },
    )
    _tables, restored = project_io.parse_project(text)
    provenance = project_io.project_provenance(text)
    assert provenance["calculation"]["matches_saved_inputs"] is True
    assert (
        provenance["calculation"]["multidirectional_interaction"][
            "publication_validation"
        ]["status"]
        == "ACCEPTED"
    )
    assert multidirectional.shear_configuration(restored) == (
        multidirectional.shear_configuration(scalars)
    )

    resaved = project_io.dump_project(
        {},
        restored,
        calculation=provenance["calculation"],
    )
    resaved_provenance = project_io.project_provenance(resaved)
    assert resaved_provenance["calculation"]["matches_saved_inputs"] is True
    assert (
        resaved_provenance["calculation"]["multidirectional_interaction"][
            "publication_validation"
        ]["status"]
        == "ACCEPTED"
    )


def test_current_project_omissions_and_malformed_values_fail_closed():
    current_missing = {
        "format": project_io.FORMAT,
        "version": project_io.VERSION,
        "tables": {},
        "scalars": {
            "shear_interaction_on": True,
            "shear_interaction_method": (
                multidirectional.SHEAR_METHOD_PROJECT
            ),
        },
    }
    with pytest.raises(ValueError, match="missing required fields"):
        project_io.parse_project(json.dumps(current_missing))
    with pytest.raises(ValueError, match="missing required fields"):
        project_io.dump_project({}, current_missing["scalars"])

    for key, value in (
        ("shear_interaction_on", 1),
        ("shear_interaction_exponent", True),
        ("shear_interaction_exponent", math.nan),
        ("shear_interaction_source", ["not", "text"]),
    ):
        malformed = copy.deepcopy(current_missing)
        malformed["scalars"] = {
            **multidirectional.shear_configuration({}),
            key: value,
        }
        with pytest.raises(ValueError, match="multidirectional input"):
            project_io.parse_project(json.dumps(malformed))

    malformed_method = copy.deepcopy(current_missing)
    malformed_method["scalars"] = {
        **multidirectional.shear_configuration({}),
        "shear_interaction_method": ["not", "a", "selection"],
    }
    with pytest.raises(ValueError, match="unknown shear-interaction"):
        project_io.parse_project(json.dumps(malformed_method))


def test_legacy_project_migrates_without_synthesised_interaction_authority():
    legacy = {
        "format": project_io.FORMAT,
        "version": project_io.VERSION - 1,
        "tables": {},
        "scalars": {
            "shear_on": True,
            "shear_interaction_on": True,
            "shear_interaction_method": (
                multidirectional.SHEAR_METHOD_PROJECT
            ),
            "shear_interaction_source": "legacy unbound text",
            "shear_interaction_approval": "legacy unbound approval",
        },
    }
    _tables, restored = project_io.parse_project(json.dumps(legacy))
    assert restored["shear_interaction_on"] is False
    assert (
        restored["shear_interaction_method"]
        == multidirectional.SHEAR_METHOD_NONE
    )
    assert restored["shear_interaction_source"] == ""
    assert restored["shear_interaction_approval"] == ""
    assert restored["shear_interaction_domain_confirmed"] is False


def test_summary_keeps_component_and_qualified_aggregate_distinct():
    case_results = _shear_case(0.2, 1.0, 0.3, 1.0)
    inputs = {
        **multidirectional.crack_configuration({}),
        **_shear_input(),
        "plastic_cases": [],
    }
    multidirectional.apply_to_results(inputs, case_results)
    rows = result_presentation.result_summary_rows(inputs, case_results)
    interaction_rows = [
        row for row in rows if row["check"] == "Biaxial shear interaction"
    ]
    assert len(interaction_rows) == 1
    assert interaction_rows[0]["status"] == "REVIEW"
    assert "APPROVED CUSTOM PASS" in interaction_rows[0]["note"]
    assert set(case_results["shear"]["directions"]) == {"vx", "vy"}
