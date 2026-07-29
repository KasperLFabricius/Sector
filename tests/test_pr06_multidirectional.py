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

import load_cases  # noqa: E402
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


def _forge_shear_not_applicable_bundle(
    bundle,
    retained_component_ids,
    *,
    inject_resealed_directional_sibling=False,
):
    forged = copy.deepcopy(bundle)
    interaction = forged["shear_cases"][0]["interaction"]
    retained_components = [
        copy.deepcopy(component)
        for component in interaction["components"]
        if component["id"] in retained_component_ids
    ]
    interaction.update(
        interaction_assessed=True,
        status="NOT APPLICABLE",
        verdict="NOT APPLICABLE",
        qualification=None,
        utilisation=None,
        components=retained_components,
        terms=[],
        reason="Forged canonical-disposition mutation.",
        issues=[],
    )
    for key in (
        "approval",
        "authority",
        "axes",
        "calculation_saturated",
        "demand_resultant_rotationally_invariant",
        "domain",
        "formula",
        "parameters",
        "resistance_source",
        "rotation_scope",
        "rotationally_invariant",
        "source",
    ):
        interaction.pop(key, None)
    forged["shear_cases"][0]["interaction"] = _reseal_result(interaction)
    if inject_resealed_directional_sibling:
        obsolete_sibling = {
            "schema": "sector.multidirectional.shear-case.v1",
            "case": forged["shear_cases"][0]["case"],
            "components": copy.deepcopy(retained_components),
        }
        obsolete_sibling["fingerprint"] = _canonical_fingerprint(
            obsolete_sibling
        )
        forged["directional_shear_cases"] = [obsolete_sibling]
    return _reseal_bundle(forged)


def _project_case_tables(case_id, vx_ed_kn, vy_ed_kn):
    return {
        load_cases.PLASTIC_TABLE_KEY: load_cases.table_from_records(
            [{
                "name": case_id,
                "description": "PR-06 authority fixture",
                "n_ed_kn": 0.0,
                "mx_ed_knm": 0.0,
                "my_ed_knm": 0.0,
                "vx_ed_kn": vx_ed_kn,
                "vy_ed_kn": vy_ed_kn,
                "vx_face": load_cases.FACE_AUTO,
                "vy_face": load_cases.FACE_AUTO,
                "t_ed_knm": 0.0,
                "check_minimum_reinforcement": False,
            }],
            load_cases.PLASTIC_TABLE_KEY,
        ),
        load_cases.ELASTIC_TABLE_KEY: load_cases.empty_table(
            load_cases.ELASTIC_TABLE_KEY
        ),
    }


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


def _crack_control_record_from_results(results):
    elastic = results["elastic"]
    responses = [
        {
            "name": name,
            "wk_mm": response.get("wk"),
            "element_id": response.get("element_id"),
            "context": copy.deepcopy(
                elastic["crack_response_contexts"].get(name) or {}
            ),
            "acceptance_role": "criterion input",
        }
        for name, response in elastic["crack_responses"].items()
    ]
    return sls.publication_safe_crack_control_record({
        "cases": [{
            "case": elastic["elastic_case"]["id"],
            "assessment": copy.deepcopy(elastic["crack_assessment"]),
            "response_mapping_scope": copy.deepcopy(
                elastic["crack_response_mapping_scope"]
            ),
            "responses": responses,
        }],
    })


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


def _with_single_case_shear_actions(inputs, results):
    """Return current inputs with action authority matching solver directions."""

    current = copy.deepcopy(inputs)
    directions = (results.get("shear") or {}).get("directions") or {}
    current["shear_on"] = True
    current["shear_components"] = {
        component_id: {
            "signed_v_ed": (
                float(directions[component_id]["signed_v_ed"])
                if component_id in directions
                else 0.0
            ),
        }
        for component_id in ("vx", "vy")
    }
    return current


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
    assert result["demand_resultant_rotationally_invariant"] is True
    assert result["rotationally_invariant"] is False
    assert "external resistance" in result["rotation_scope"]


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
        current_results=dk_results,
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
        current_results=en_crack_results,
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
    shear_inputs = _with_single_case_shear_actions(
        shear_inputs,
        shear_results,
    )
    multidirectional.apply_to_results(shear_inputs, shear_results)
    shear_bundle = multidirectional.interaction_calculation_record(
        shear_results
    )
    assert multidirectional.publication_safe_interaction_record(
        shear_bundle,
        current_inputs=shear_inputs,
        current_results=shear_results,
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
    extreme_case = _shear_case(2.0, 1.0, 0.1, 1.0)
    extreme_inputs = _with_single_case_shear_actions(
        extreme_inputs,
        extreme_case,
    )
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
        current_results=extreme_case,
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
    (
        "retained_component_ids",
        "vx",
        "vy",
        "expected_status",
        "expected_assessed",
    ),
    [
        ([], 0.0, 0.0, "INVALID", False),
        (["vx"], 0.2, 0.0, "NOT APPLICABLE", True),
        (["vx", "vy"], 0.2, 0.3, "PASS", True),
        (["vx", "vy"], 0.9, 0.9, "FAIL", True),
    ],
    ids=["zero-invalid", "one-uniaxial", "two-pass", "two-fail"],
)
def test_canonical_component_count_derives_legal_shear_disposition(
    retained_component_ids,
    vx,
    vy,
    expected_status,
    expected_assessed,
):
    inputs = {
        **multidirectional.crack_configuration({}),
        **_shear_input(),
        "plastic_case": {"id": "ULS-LEGAL"},
    }
    results = _shear_case(vx, 1.0, vy, 1.0)
    results["shear"]["directions"] = {
        component_id: direction
        for component_id, direction in results["shear"]["directions"].items()
        if component_id in retained_component_ids
    }
    if len(retained_component_ids) == 2:
        inputs = _with_single_case_shear_actions(inputs, results)
    multidirectional.apply_to_results(inputs, results)
    interaction = results["shear"]["interaction"]

    assert interaction["status"] == expected_status
    assert interaction["interaction_assessed"] is expected_assessed
    assert [
        component["id"] for component in interaction["components"]
    ] == retained_component_ids
    assert interaction["case_id"] == "ULS-LEGAL"

    bundle = multidirectional.interaction_calculation_record(results)
    safe = multidirectional.publication_safe_interaction_record(
        bundle,
        current_inputs=inputs,
        current_results=results,
    )
    assert safe["publication_validation"]["status"] == "ACCEPTED"
    assert safe["shear_cases"][0]["interaction"]["status"] == expected_status


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


@pytest.mark.parametrize(
    ("component_field", "forged_value"),
    [
        ("demand_kn", -0.1),
        ("resistance_kn", 0.0),
        ("signed_demand_kn", 9.0),
        ("utilisation", 9.0),
        ("status", "FAIL"),
        ("axis", "forged axis"),
        ("method", "forged method"),
        ("id", {"malformed": "vx"}),
    ],
)
@pytest.mark.parametrize("uniaxial", [False, True], ids=["biaxial", "uniaxial"])
def test_publication_validates_retained_nonpass_shear_components(
    component_field,
    forged_value,
    uniaxial,
):
    inputs = {
        **multidirectional.crack_configuration({}),
        **multidirectional.shear_configuration({}),
        "shear_method": multidirectional.SHEAR_CODE_EN_2023,
    }
    case = _shear_case(0.2, 1.0, 0.3, 1.0)
    if uniaxial:
        case["shear"]["directions"].pop("vy")
        case["shear"].update(
            active_directions=["vx"],
            biaxial=False,
            status="PASS",
        )
    interaction = multidirectional.assess_shear_interaction(
        inputs,
        case,
        case_id="ULS-RETAINED",
    )
    assert interaction["status"] == (
        "NOT APPLICABLE" if uniaxial else "NOT ASSESSED"
    )
    bundle = _reseal_bundle({
        "schema": multidirectional.INTERACTION_BUNDLE_SCHEMA,
        "crack": None,
        "shear_cases": [{
            "case": "ULS-RETAINED",
            "interaction": interaction,
        }],
    })
    forged = copy.deepcopy(bundle)
    forged_interaction = forged["shear_cases"][0]["interaction"]
    forged_interaction["components"][0][component_field] = forged_value
    forged["shear_cases"][0]["interaction"] = _reseal_result(
        forged_interaction
    )
    forged = _reseal_bundle(forged)

    safe = multidirectional.publication_safe_interaction_record(
        forged,
        current_inputs=inputs,
    )

    assert safe["publication_validation"]["status"] == "REJECTED"
    assert any(
        "component" in issue
        for issue in safe["publication_validation"]["issues"]
    )


def test_publication_rejects_unhashable_interaction_term_identity():
    inputs = {
        **multidirectional.crack_configuration({}),
        **_shear_input(),
        "shear_method": multidirectional.SHEAR_CODE_EN_2023,
    }
    interaction = multidirectional.assess_shear_interaction(
        inputs,
        _shear_case(0.2, 1.0, 0.3, 1.0),
        case_id="ULS-MALFORMED-TERM",
    )
    interaction["terms"][0]["id"] = {"malformed": "vx"}
    interaction = _reseal_result(interaction)
    bundle = _reseal_bundle({
        "schema": multidirectional.INTERACTION_BUNDLE_SCHEMA,
        "crack": None,
        "shear_cases": [{
            "case": "ULS-MALFORMED-TERM",
            "interaction": interaction,
        }],
    })

    safe = multidirectional.publication_safe_interaction_record(
        bundle,
        current_inputs=inputs,
    )

    assert safe["publication_validation"]["status"] == "REJECTED"
    assert any(
        "term" in issue
        for issue in safe["publication_validation"]["issues"]
    )


@pytest.mark.parametrize(
    ("kind", "downgraded_status"),
    [
        ("crack", "NOT ASSESSED"),
        ("shear", "NOT ASSESSED"),
        ("crack", "NOT APPLICABLE"),
        ("shear", "NOT APPLICABLE"),
    ],
    ids=[
        "crack-review",
        "shear-review",
        "crack-not-applicable",
        "shear-not-applicable",
    ],
)
@pytest.mark.parametrize(
    "strip_calculation_evidence",
    [False, True],
    ids=["retained-calculation", "stripped-calculation"],
)
@pytest.mark.parametrize(
    "source_status",
    ["PASS", "FAIL"],
    ids=["source-pass", "source-fail"],
)
def test_publication_rejects_downgraded_active_conclusions(
    kind,
    downgraded_status,
    strip_calculation_evidence,
    source_status,
):
    if kind == "crack":
        crack_component = 0.1 if source_status == "PASS" else 0.3
        inputs = {
            **multidirectional.shear_configuration({}),
            **_crack_input(multidirectional.CRACK_METHOD_PROJECT),
            "crack_interaction_domain_confirmed": True,
            "crack_interaction_component_x_mm": crack_component,
            "crack_interaction_component_y_mm": crack_component,
            "crack_interaction_limit_x_mm": 0.3,
            "crack_interaction_limit_y_mm": 0.3,
            "crack_interaction_exponent": 2.0,
            "crack_interaction_source": "Project DB clause CR-06",
            "crack_interaction_approval": "Checker approval CR-06",
        }
        results = _crack_results()
        interaction = multidirectional.assess_crack_interaction(
            inputs,
            results,
        )
        bundle = {
            "schema": multidirectional.INTERACTION_BUNDLE_SCHEMA,
            "crack": interaction,
            "shear_cases": [],
        }
    else:
        inputs = {
            **multidirectional.crack_configuration({}),
            **_shear_input(),
            "shear_method": multidirectional.SHEAR_CODE_EN_2023,
            "plastic_case": {"id": "ULS-DOWNGRADE"},
        }
        results = (
            _shear_case(0.2, 1.0, 0.3, 1.0)
            if source_status == "PASS"
            else _shear_case(0.9, 1.0, 0.9, 1.0)
        )
        multidirectional.apply_to_results(inputs, results)
        bundle = multidirectional.interaction_calculation_record(results)
        interaction = bundle["shear_cases"][0]["interaction"]
    assert interaction["status"] == source_status

    downgraded = copy.deepcopy(interaction)
    downgraded.update(
        interaction_assessed=downgraded_status == "NOT APPLICABLE",
        status=downgraded_status,
        verdict=(
            "NOT APPLICABLE"
            if downgraded_status == "NOT APPLICABLE"
            else "REVIEW"
        ),
        reason="Forged downgraded conclusion.",
        issues=[],
    )
    if strip_calculation_evidence:
        downgraded.update(
            qualification=None,
            utilisation=None,
            components=[],
            terms=[],
        )
        for key in (
            "angle",
            "approval",
            "authority",
            "axes",
            "calculation_saturated",
            "criterion",
            "demand_resultant_rotationally_invariant",
            "domain",
            "formula",
            "parameters",
            "resistance_source",
            "rotation_scope",
            "rotationally_invariant",
            "selected_crack_code",
            "selected_crack_edition",
            "source",
        ):
            downgraded.pop(key, None)
    downgraded = _reseal_result(downgraded)
    if kind == "crack":
        bundle["crack"] = downgraded
    else:
        bundle["shear_cases"][0]["interaction"] = downgraded
    bundle = _reseal_bundle(bundle)

    safe = multidirectional.publication_safe_interaction_record(
        bundle,
        current_inputs=inputs,
        current_results=results,
    )

    assert safe["publication_validation"]["status"] == "REJECTED"
    assert any(
        "downgraded" in issue
        or "active" in issue
        or "NOT APPLICABLE" in issue
        or "directional case" in issue
        or "current case/demand authority" in issue
        for issue in safe["publication_validation"]["issues"]
    )


@pytest.mark.parametrize(
    "retained_component_ids",
    [[], ["vx"], ["vx", "vy"]],
    ids=[
        "zero-component-truncation",
        "one-component-truncation",
        "two-component-disposition-forgery",
    ],
)
@pytest.mark.parametrize(
    "inject_resealed_directional_sibling",
    [False, True],
    ids=["interaction-only", "jointly-resealed-sibling"],
)
def test_publication_rejects_jointly_truncated_biaxial_not_applicable_forgery(
    retained_component_ids,
    inject_resealed_directional_sibling,
):
    inputs = {
        **multidirectional.crack_configuration({}),
        **_shear_input(),
        "shear_method": multidirectional.SHEAR_CODE_EN_2023,
        "plastic_case": {"id": "ULS-STRIPPED"},
    }
    results = _shear_case(0.9, 1.0, 0.9, 1.0)
    multidirectional.apply_to_results(inputs, results)
    bundle = multidirectional.interaction_calculation_record(results)
    interaction = bundle["shear_cases"][0]["interaction"]
    assert interaction["status"] == "FAIL"
    assert len(interaction["components"]) == 2

    forged = _forge_shear_not_applicable_bundle(
        bundle,
        retained_component_ids,
        inject_resealed_directional_sibling=(
            inject_resealed_directional_sibling
        ),
    )

    safe = multidirectional.publication_safe_interaction_record(
        forged,
        current_inputs=inputs,
        current_results=results,
    )
    assert safe["publication_validation"]["status"] == "REJECTED"
    assert any(
        "independently reconstructed current case/demand authority" in issue
        or "canonical assessment reconstructed" in issue
        or "persisted sibling directional shear evidence" in issue
        for issue in safe["publication_validation"]["issues"]
    )


def test_uniaxial_shear_publication_binds_current_case_and_resaves():
    inputs = {
        **multidirectional.crack_configuration({}),
        **_shear_input(),
        "shear_on": True,
        "shear_method": multidirectional.SHEAR_CODE_EN_2023,
        "plastic_case": {"id": "ULS-UNI"},
    }
    results = _shear_case(0.2, 1.0, 0.3, 1.0)
    results["shear"]["directions"].pop("vy")
    results["shear"].update(
        active_directions=["vx"],
        biaxial=False,
        status="PASS",
    )
    multidirectional.apply_to_results(inputs, results)
    bundle = multidirectional.interaction_calculation_record(results)
    current_authority = multidirectional.directional_shear_case_authority(
        results,
        current_inputs=inputs,
    )

    assert current_authority[0]["case"] == "ULS-UNI"
    assert [
        component["id"]
        for component in current_authority[0]["components"]
    ] == ["vx"]
    safe = multidirectional.publication_safe_interaction_record(
        bundle,
        current_inputs=inputs,
        current_results=results,
    )
    assert safe["publication_validation"]["status"] == "ACCEPTED"

    forged = copy.deepcopy(bundle)
    interaction = forged["shear_cases"][0]["interaction"]
    interaction["components"] = []
    forged["shear_cases"][0]["interaction"] = _reseal_result(interaction)
    forged = _reseal_bundle(forged)
    rejected = multidirectional.publication_safe_interaction_record(
        forged,
        current_inputs=inputs,
        current_results=results,
    )
    assert rejected["publication_validation"]["status"] == "REJECTED"
    assert any(
        "current case/demand authority" in issue
        for issue in rejected["publication_validation"]["issues"]
    )

    tables = _project_case_tables("ULS-UNI", 0.2, 0.0)
    digest = project_io.input_sha256(tables, inputs)
    text = project_io.dump_project(
        tables,
        inputs,
        calculation={
            "performed_at_utc": "2026-07-29T11:00:00+00:00",
            "sector_version": "0.91",
            "source_revision": "7" * 40,
            "input_sha256": digest,
            "multidirectional_interaction": bundle,
        },
    )
    restored_tables, restored = project_io.parse_project(text)
    provenance = project_io.project_provenance(text)
    assert provenance["calculation"]["matches_saved_inputs"] is True
    assert provenance["calculation"]["multidirectional_interaction"][
        "publication_validation"
    ]["status"] == "ACCEPTED"

    resaved = project_io.dump_project(
        restored_tables,
        restored,
        calculation=provenance["calculation"],
    )
    resaved_provenance = project_io.project_provenance(resaved)
    assert resaved_provenance["calculation"]["matches_saved_inputs"] is True
    assert resaved_provenance["calculation"][
        "multidirectional_interaction"
    ]["publication_validation"]["status"] == "ACCEPTED"


@pytest.mark.parametrize(
    "case_attack",
    [
        "missing",
        "empty",
        "substituted-case",
        "substituted-assessment-case",
        "duplicate-case",
    ],
)
def test_shear_publication_requires_exact_current_authority_coverage(
    case_attack,
):
    inputs = {
        **multidirectional.crack_configuration({}),
        **_shear_input(multidirectional.SHEAR_METHOD_EN_2023),
        "shear_method": multidirectional.SHEAR_CODE_EN_2023,
        "shear_interaction_planar_member": True,
        "shear_interaction_same_control_point": True,
        "shear_interaction_no_torsion": True,
        "shear_interaction_resultant_resistance_kn": 1.0,
        "shear_interaction_resistance_source": "FE envelope SH-06",
    }
    results = _shear_case(0.3, 1.0, 0.4, 1.0)
    multidirectional.apply_to_results(inputs, results)
    bundle = multidirectional.interaction_calculation_record(results)
    assert multidirectional.publication_safe_interaction_record(
        bundle,
        current_inputs=inputs,
        current_results=results,
    )["publication_validation"]["status"] == "ACCEPTED"

    attacked = copy.deepcopy(bundle)
    if case_attack == "missing":
        attacked.pop("shear_cases")
    elif case_attack == "empty":
        attacked["shear_cases"] = []
    elif case_attack == "substituted-case":
        attacked["shear_cases"][0]["case"] = "ULS-ORPHAN"
    elif case_attack == "substituted-assessment-case":
        interaction = attacked["shear_cases"][0]["interaction"]
        interaction["case_id"] = "ULS-ORPHAN"
        attacked["shear_cases"][0]["interaction"] = _reseal_result(
            interaction
        )
    else:
        attacked["shear_cases"].append(
            copy.deepcopy(attacked["shear_cases"][0])
        )
    attacked = _reseal_bundle(attacked)

    safe = multidirectional.publication_safe_interaction_record(
        attacked,
        current_inputs=inputs,
        current_results=results,
    )
    assert safe["publication_validation"]["status"] == "REJECTED"
    assert any(
        "current directional shear case authority" in issue
        or "independently reconstructed current case authority" in issue
        for issue in safe["publication_validation"]["issues"]
    )


@pytest.mark.parametrize(
    "malformed_action_basis",
    [
        {
            "shear_on": True,
            "shear_components": {
                "vx": {"signed_v_ed": 0.3},
            },
        },
        {
            "shear_on": 1,
            "shear_Vx": 0.3,
            "shear_Vy": 0.4,
        },
        {
            "shear_on": True,
            "load_cases": {"plastic": "not-a-case-list"},
        },
    ],
    ids=["missing-direction", "boolean-like-enable", "malformed-case-list"],
)
def test_publication_never_falls_back_past_malformed_current_action_basis(
    malformed_action_basis,
):
    inputs = {
        **multidirectional.crack_configuration({}),
        **_shear_input(),
        **malformed_action_basis,
    }
    results = _shear_case(0.3, 1.0, 0.4, 1.0)
    multidirectional.apply_to_results(inputs, results)
    bundle = multidirectional.interaction_calculation_record(results)

    safe = multidirectional.publication_safe_interaction_record(
        bundle,
        current_inputs=inputs,
        current_results=results,
    )
    assert safe["publication_validation"]["status"] == "REJECTED"
    assert any(
        "current directional shear case authority is missing" in issue
        for issue in safe["publication_validation"]["issues"]
    )
    assert safe["shear_cases"][0]["interaction"]["status"] == "NOT ASSESSED"


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
        bundle,
        current_inputs=inputs,
        current_results=results,
    )
    assert accepted["publication_validation"]["status"] == "ACCEPTED"

    tampered = copy.deepcopy(bundle)
    tampered["crack"]["utilisation"] = 0.0
    rejected = multidirectional.publication_safe_interaction_record(
        tampered,
        current_inputs=inputs,
        current_results=results,
    )
    assert rejected["publication_validation"]["status"] == "REJECTED"
    assert rejected["crack"]["status"] == "NOT ASSESSED"

    repaired_body = copy.deepcopy(tampered)
    repaired_body["crack"] = _reseal_result(repaired_body["crack"])
    repaired_body = _reseal_bundle(repaired_body)
    contradictory = multidirectional.publication_safe_interaction_record(
        repaired_body,
        current_inputs=inputs,
        current_results=results,
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
        current_results=results,
    )
    assert formula_rejected["publication_validation"]["status"] == "REJECTED"
    assert any(
        "formula, authority, or domain is contradictory" in issue
        for issue in formula_rejected["publication_validation"]["issues"]
    )

    changed = copy.deepcopy(inputs)
    changed["crack_interaction_exponent"] = 3.0
    stale = multidirectional.publication_safe_interaction_record(
        bundle,
        current_inputs=changed,
        current_results=results,
    )
    assert stale["publication_validation"]["status"] == "REJECTED"

    changed_edition = copy.deepcopy(inputs)
    changed_edition["sls_edition"] = "2023"
    edition_stale = multidirectional.publication_safe_interaction_record(
        bundle,
        current_inputs=changed_edition,
        current_results=results,
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
            current_results=results,
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


def test_rejected_publication_overlay_strips_untrusted_aggregate_calculation():
    results = _shear_case(0.2, 1.0, 0.3, 1.0)
    inputs = {
        **multidirectional.crack_configuration({}),
        **_shear_input(),
    }
    multidirectional.apply_to_results(inputs, results)

    forged = copy.deepcopy(results["shear"]["interaction"])
    forged.update({
        "utilisation": 0.000123456789,
        "formula": "UNTRUSTED AGGREGATE FORMULA QA-06",
        "parameters": {"untrusted_parameter": 123456.0},
        "terms": [{"id": "untrusted-term", "value": 987654.0}],
        "source": "UNTRUSTED AGGREGATE SOURCE QA-06",
        "approval": "UNTRUSTED AGGREGATE APPROVAL QA-06",
    })
    forged["components"][0]["axis"] = (
        "UNTRUSTED AGGREGATE COMPONENT QA-06"
    )
    forged = _reseal_result(forged)
    results["shear"]["interaction"] = copy.deepcopy(forged)
    results["shear_interactions"][0]["interaction"] = copy.deepcopy(forged)

    safe = multidirectional.publication_safe_results(
        results,
        current_inputs=inputs,
    )
    aggregate = safe["shear"]["interaction"]

    assert aggregate["status"] == "NOT ASSESSED"
    assert aggregate["qualification"] == "PUBLICATION REJECTED"
    assert aggregate["components"] == []
    assert {
        "utilisation",
        "formula",
        "parameters",
        "terms",
        "axes",
        "domain",
        "source",
        "resistance_source",
        "approval",
        "authority",
        "calculation_saturated",
        "rotationally_invariant",
    }.isdisjoint(aggregate)
    assert set(safe["shear"]["directions"]) == {"vx", "vy"}
    assert all(
        item["status"] == "PASS"
        for item in safe["shear"]["directions"].values()
    )
    assert "UNTRUSTED AGGREGATE" not in json.dumps(safe, sort_keys=True)


def test_rejected_crack_overlay_uses_current_case_without_aggregate_binding():
    inputs = {
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
    results = _crack_results()
    multidirectional.apply_to_results(inputs, results)
    selected = results.pop("elastic")
    other = copy.deepcopy(selected)
    other.pop("crack_interaction", None)
    results["elastic_cases"] = [
        {
            "name": "SLS-01",
            "results": {"elastic": selected},
        },
        {
            "name": "SLS-OTHER",
            "results": {"elastic": other},
        },
    ]
    results["crack_interaction"]["utilisation"] = 0.0

    safe = multidirectional.publication_safe_results(
        results,
        current_inputs=inputs,
    )
    by_case = {
        item["name"]: item["results"]["elastic"]
        for item in safe["elastic_cases"]
    }
    rejected = by_case["SLS-01"]["crack_interaction"]

    assert rejected["qualification"] == "PUBLICATION REJECTED"
    assert rejected["components"] == []
    assert "configuration" not in rejected
    assert "criterion" not in rejected
    assert "formula" not in rejected
    assert "crack_interaction" not in by_case["SLS-OTHER"]
    assert by_case["SLS-01"]["crack_assessment"]["status"] == "OK"
    assert by_case["SLS-OTHER"]["crack_assessment"]["status"] == "OK"


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


def test_project_save_load_resave_requires_current_result_recalculation():
    scalars = {
        **multidirectional.crack_configuration({}),
        **_shear_input(),
        "shear_on": True,
        "shear_method": multidirectional.SHEAR_CODE_EN_2023,
        "plastic_case": {"id": "ULS-PERSIST"},
    }
    scalars["shear_interaction_exponent"] = 137.0
    results = _shear_case(0.2, 1.0, 0.3, 1.0)
    multidirectional.apply_to_results(scalars, results)
    record = multidirectional.interaction_calculation_record(results)
    tables = _project_case_tables("ULS-PERSIST", 0.2, 0.3)
    digest = project_io.input_sha256(tables, scalars)
    text = project_io.dump_project(
        tables,
        scalars,
        calculation={
            "performed_at_utc": "2026-07-29T10:00:00+00:00",
            "sector_version": "0.91",
            "source_revision": "6" * 40,
            "input_sha256": digest,
            "multidirectional_interaction": record,
        },
    )
    restored_tables, restored = project_io.parse_project(text)
    saved_record = json.loads(text)["calculation"][
        "multidirectional_interaction"
    ]
    assert any(
        "current solver component/resistance authority" in issue
        for issue in saved_record["publication_validation"]["issues"]
    )
    provenance = project_io.project_provenance(text)
    assert provenance["calculation"]["matches_saved_inputs"] is False
    assert (
        provenance["calculation"]["multidirectional_interaction"][
            "publication_validation"
        ]["status"]
        == "REJECTED"
    )
    assert any(
        "prior publication boundary" in issue
        or "durable publication rejection" in issue
        for issue in provenance["calculation"][
            "multidirectional_interaction"
        ]["publication_validation"]["issues"]
    )
    assert multidirectional.shear_configuration(restored) == (
        multidirectional.shear_configuration(scalars)
    )

    resaved = project_io.dump_project(
        restored_tables,
        restored,
        calculation=provenance["calculation"],
    )
    resaved_provenance = project_io.project_provenance(resaved)
    assert resaved_provenance["calculation"]["matches_saved_inputs"] is False
    assert (
        resaved_provenance["calculation"]["multidirectional_interaction"][
            "publication_validation"
        ]["status"]
        == "REJECTED"
    )
    assert any(
        "prior publication boundary" in issue
        or "durable publication rejection" in issue
        for issue in resaved_provenance["calculation"][
            "multidirectional_interaction"
        ]["publication_validation"]["issues"]
    )


def test_project_save_load_resave_rejects_joint_directional_truncation():
    case_id = "ULS-PERSIST-MUTATION"
    scalars = {
        **multidirectional.crack_configuration({}),
        **_shear_input(),
        "shear_on": True,
        "shear_method": multidirectional.SHEAR_CODE_EN_2023,
        "plastic_case": {"id": case_id},
    }
    results = _shear_case(0.2, 1.0, 0.3, 1.0)
    multidirectional.apply_to_results(scalars, results)
    raw_record = multidirectional.interaction_calculation_record(results)
    forged_record = _forge_shear_not_applicable_bundle(
        raw_record,
        ["vx"],
        inject_resealed_directional_sibling=True,
    )
    tables = _project_case_tables(case_id, 0.2, 0.3)
    digest = project_io.input_sha256(tables, scalars)

    saved = project_io.dump_project(
        tables,
        scalars,
        calculation={
            "performed_at_utc": "2026-07-29T10:00:00+00:00",
            "sector_version": "0.91",
            "source_revision": "7" * 40,
            "input_sha256": digest,
            "multidirectional_interaction": forged_record,
        },
    )
    provenance = project_io.project_provenance(saved)
    rejected = provenance["calculation"]["multidirectional_interaction"]
    assert provenance["calculation"]["matches_saved_inputs"] is False
    assert rejected["publication_validation"]["status"] == "REJECTED"
    assert rejected["shear_cases"][0]["interaction"]["status"] == (
        "NOT ASSESSED"
    )
    assert any(
        "independently reconstructed current case/demand authority" in issue
        or "persisted sibling directional shear evidence" in issue
        for issue in rejected["publication_validation"]["issues"]
    )

    restored_tables, restored_scalars = project_io.parse_project(saved)
    resaved = project_io.dump_project(
        restored_tables,
        restored_scalars,
        calculation=provenance["calculation"],
    )
    resaved_provenance = project_io.project_provenance(resaved)
    resaved_record = resaved_provenance["calculation"][
        "multidirectional_interaction"
    ]
    assert resaved_provenance["calculation"]["matches_saved_inputs"] is False
    assert resaved_record["publication_validation"]["status"] == "REJECTED"
    assert any(
        "prior publication boundary" in issue
        or "durable publication rejection" in issue
        for issue in resaved_record["publication_validation"]["issues"]
    )


def test_project_rejects_jointly_resealed_standard_crack_false_pass():
    inputs = {
        **multidirectional.shear_configuration({}),
        **_crack_input(multidirectional.CRACK_METHOD_DK_2004),
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
    }
    current_results = _crack_results(limit_mm=0.05, width_mm=0.04)
    multidirectional.apply_to_results(inputs, current_results)
    assert current_results["crack_interaction"]["status"] == "FAIL"

    forged_results = _crack_results(limit_mm=0.30, width_mm=0.04)
    multidirectional.apply_to_results(inputs, forged_results)
    forged_interaction = forged_results["crack_interaction"]
    assert forged_interaction["status"] == "PASS"
    forged_bundle = _reseal_bundle({
        "schema": multidirectional.INTERACTION_BUNDLE_SCHEMA,
        "crack": forged_interaction,
        "shear_cases": [],
    })
    forged_crack_control = _crack_control_record_from_results(
        forged_results
    )
    assert forged_crack_control["cases"][0]["assessment"]["status"] == "OK"

    live_rejected = multidirectional.publication_safe_interaction_record(
        forged_bundle,
        current_inputs=inputs,
        current_results=current_results,
    )
    assert live_rejected["publication_validation"]["status"] == "REJECTED"
    assert any(
        "canonical assessment reconstructed from current inputs and crack "
        "results" in issue
        for issue in live_rejected["publication_validation"]["issues"]
    )

    tables = _project_case_tables("ULS-CRACK-AUDIT", 0.0, 0.0)
    digest = project_io.input_sha256(tables, inputs)
    text = project_io.dump_project(
        tables,
        inputs,
        calculation={
            "input_sha256": digest,
            "crack_control": forged_crack_control,
            "multidirectional_interaction": forged_bundle,
        },
    )
    raw_saved = json.loads(text)["calculation"][
        "multidirectional_interaction"
    ]
    assert any(
        "without independent current crack-result authority" in issue
        for issue in raw_saved["publication_validation"]["issues"]
    )
    provenance = project_io.project_provenance(text)
    saved = provenance["calculation"]["multidirectional_interaction"]
    assert provenance["calculation"]["matches_saved_inputs"] is False
    assert saved["publication_validation"]["status"] == "REJECTED"
    assert saved["crack"]["status"] == "NOT ASSESSED"
    assert any(
        "prior publication boundary" in issue
        or "durable publication rejection" in issue
        for issue in saved["publication_validation"]["issues"]
    )


def test_project_rejects_jointly_resealed_shear_resistance_false_pass():
    case_id = "ULS-RESISTANCE-AUDIT"
    inputs = {
        **multidirectional.crack_configuration({}),
        **_shear_input(),
        "shear_on": True,
        "shear_method": multidirectional.SHEAR_CODE_EN_2023,
        "plastic_case": {"id": case_id},
    }
    current_results = _shear_case(0.8, 1.0, 0.8, 1.0)
    inputs = _with_single_case_shear_actions(inputs, current_results)
    multidirectional.apply_to_results(inputs, current_results)
    assert current_results["shear"]["interaction"]["status"] == "FAIL"

    forged_results = _shear_case(0.8, 10.0, 0.8, 10.0)
    multidirectional.apply_to_results(inputs, forged_results)
    forged_bundle = multidirectional.interaction_calculation_record(
        forged_results
    )
    assert forged_bundle["shear_cases"][0]["interaction"]["status"] == "PASS"

    live_rejected = multidirectional.publication_safe_interaction_record(
        forged_bundle,
        current_inputs=inputs,
        current_results=current_results,
    )
    assert live_rejected["publication_validation"]["status"] == "REJECTED"
    assert any(
        "canonical assessment reconstructed from current inputs and "
        "directional case evidence" in issue
        for issue in live_rejected["publication_validation"]["issues"]
    )

    tables = _project_case_tables(case_id, 0.8, 0.8)
    digest = project_io.input_sha256(tables, inputs)
    text = project_io.dump_project(
        tables,
        inputs,
        calculation={
            "input_sha256": digest,
            "multidirectional_interaction": forged_bundle,
        },
    )
    raw_saved = json.loads(text)["calculation"][
        "multidirectional_interaction"
    ]
    assert any(
        "current solver component/resistance authority" in issue
        for issue in raw_saved["publication_validation"]["issues"]
    )
    provenance = project_io.project_provenance(text)
    saved = provenance["calculation"]["multidirectional_interaction"]
    assert provenance["calculation"]["matches_saved_inputs"] is False
    assert saved["publication_validation"]["status"] == "REJECTED"
    assert saved["shear_cases"][0]["interaction"]["status"] == "NOT ASSESSED"
    assert any(
        "prior publication boundary" in issue
        or "durable publication rejection" in issue
        for issue in saved["publication_validation"]["issues"]
    )


@pytest.mark.parametrize(
    ("vx", "vy", "expected_status"),
    [
        (0.2, 0.3, "PASS"),
        (0.9, 0.9, "FAIL"),
    ],
    ids=["assessed-pass", "assessed-fail"],
)
def test_assessed_shear_requires_both_authorities_raw_and_headless(
    vx,
    vy,
    expected_status,
):
    case_id = "ULS-DUAL-AUTHORITY"
    inputs_without_actions = {
        **multidirectional.crack_configuration({}),
        **_shear_input(),
        "shear_on": True,
        "shear_method": multidirectional.SHEAR_CODE_EN_2023,
        "plastic_case": {"id": case_id},
    }
    jointly_forged_results = _shear_case(vx, 1.0, vy, 1.0)
    multidirectional.apply_to_results(
        inputs_without_actions,
        jointly_forged_results,
    )
    bundle = multidirectional.interaction_calculation_record(
        jointly_forged_results
    )
    assert bundle["shear_cases"][0]["interaction"]["status"] == (
        expected_status
    )

    raw_rejected = multidirectional.publication_safe_interaction_record(
        bundle,
        current_inputs=inputs_without_actions,
        current_results=jointly_forged_results,
    )
    assert raw_rejected["publication_validation"]["status"] == "REJECTED"
    assert any(
        "without both independent current authorities" in issue
        and "action case/signed-demand authority" in issue
        for issue in raw_rejected["publication_validation"]["issues"]
    )

    headless_rejected = multidirectional.publication_safe_results(
        jointly_forged_results,
        current_inputs=inputs_without_actions,
    )
    assert headless_rejected["_publication_interaction_bundle"][
        "publication_validation"
    ]["status"] == "REJECTED"
    assert set(headless_rejected["shear"]["directions"]) == {"vx", "vy"}
    assert headless_rejected["shear"]["interaction"]["status"] == (
        "NOT ASSESSED"
    )

    inputs_with_actions = _with_single_case_shear_actions(
        inputs_without_actions,
        jointly_forged_results,
    )
    missing_solver = multidirectional.publication_safe_interaction_record(
        bundle,
        current_inputs=inputs_with_actions,
    )
    assert missing_solver["publication_validation"]["status"] == "REJECTED"
    assert any(
        "without both independent current authorities" in issue
        and "solver component/resistance authority" in issue
        for issue in missing_solver["publication_validation"]["issues"]
    )

    raw_accepted = multidirectional.publication_safe_interaction_record(
        bundle,
        current_inputs=inputs_with_actions,
        current_results=jointly_forged_results,
    )
    assert raw_accepted["publication_validation"]["status"] == "ACCEPTED"
    headless_accepted = multidirectional.publication_safe_results(
        jointly_forged_results,
        current_inputs=inputs_with_actions,
    )
    assert headless_accepted["_publication_interaction_bundle"][
        "publication_validation"
    ]["status"] == "ACCEPTED"
    assert headless_accepted["shear"]["interaction"]["status"] == (
        expected_status
    )


def test_single_solver_result_binds_only_the_sole_canonical_action_case():
    case_id = "PL-01"
    calculation_inputs = {
        **multidirectional.crack_configuration({}),
        **multidirectional.shear_configuration({}),
        "shear_on": False,
        "plastic_case": {"id": case_id},
    }
    current_results = {"shear": {"directions": {}}}
    multidirectional.apply_to_results(calculation_inputs, current_results)
    bundle = multidirectional.interaction_calculation_record(current_results)
    assert bundle["shear_cases"][0]["interaction"]["status"] == "INVALID"

    publication_inputs = copy.deepcopy(calculation_inputs)
    publication_inputs.pop("plastic_case")
    publication_inputs["load_cases"] = {
        "plastic": [{
            "name": case_id,
            "vx_ed_kn": 0.0,
            "vy_ed_kn": 0.0,
        }],
    }
    solver_authority = multidirectional.directional_shear_case_authority(
        current_results,
        current_inputs=publication_inputs,
    )
    assert solver_authority[0]["case"] == case_id
    assert solver_authority[0]["assessment_case_id"] == case_id
    assert solver_authority[0]["components"] == []
    accepted = multidirectional.publication_safe_interaction_record(
        bundle,
        current_inputs=publication_inputs,
        current_results=current_results,
    )
    assert accepted["publication_validation"]["status"] == "ACCEPTED"
    assert accepted["shear_cases"][0]["interaction"]["status"] == "INVALID"

    for ambiguous_actions in (
        [],
        [
            {"name": case_id, "vx_ed_kn": 0.0, "vy_ed_kn": 0.0},
            {"name": "PL-02", "vx_ed_kn": 0.0, "vy_ed_kn": 0.0},
        ],
    ):
        ambiguous_inputs = copy.deepcopy(publication_inputs)
        ambiguous_inputs["load_cases"]["plastic"] = ambiguous_actions
        assert multidirectional.directional_shear_case_authority(
            current_results,
            current_inputs=ambiguous_inputs,
        ) is None
        rejected = multidirectional.publication_safe_interaction_record(
            bundle,
            current_inputs=ambiguous_inputs,
            current_results=current_results,
        )
        assert rejected["publication_validation"]["status"] == "REJECTED"


@pytest.mark.parametrize(
    "action_attack",
    [
        "missing-case",
        "partial-case",
        "duplicate-case",
        "substituted-case",
    ],
)
def test_assessed_shear_requires_exact_multicase_action_authority(
    action_attack,
):
    actions = [
        {"name": "ULS-A", "vx_ed_kn": 0.2, "vy_ed_kn": 0.3},
        {"name": "ULS-B", "vx_ed_kn": -0.4, "vy_ed_kn": 0.1},
    ]
    inputs = {
        **multidirectional.crack_configuration({}),
        **_shear_input(),
        "shear_on": True,
        "shear_method": multidirectional.SHEAR_CODE_EN_2023,
        "load_cases": {"plastic": copy.deepcopy(actions)},
    }
    results = {
        "plastic_cases": [
            {
                "name": "ULS-A",
                "results": _shear_case(0.2, 1.0, 0.3, 1.0),
            },
            {
                "name": "ULS-B",
                "results": _shear_case(
                    0.4,
                    1.0,
                    0.1,
                    1.0,
                    method=multidirectional.SHEAR_CODE_EN_2023,
                ),
            },
        ],
    }
    results["plastic_cases"][1]["results"]["shear"]["directions"]["vx"][
        "signed_v_ed"
    ] = -0.4
    multidirectional.apply_to_results(inputs, results)
    bundle = multidirectional.interaction_calculation_record(results)
    accepted = multidirectional.publication_safe_interaction_record(
        bundle,
        current_inputs=inputs,
        current_results=results,
    )
    assert accepted["publication_validation"]["status"] == "ACCEPTED"

    attacked = copy.deepcopy(inputs)
    attacked_actions = copy.deepcopy(actions)
    if action_attack == "missing-case":
        attacked_actions.pop()
    elif action_attack == "partial-case":
        attacked_actions[1].pop("vy_ed_kn")
    elif action_attack == "duplicate-case":
        attacked_actions[1]["name"] = "ULS-A"
    else:
        attacked_actions[1]["name"] = "ULS-SUBSTITUTED"
    attacked["load_cases"]["plastic"] = attacked_actions

    rejected = multidirectional.publication_safe_interaction_record(
        bundle,
        current_inputs=attacked,
        current_results=results,
    )
    assert rejected["publication_validation"]["status"] == "REJECTED"
    assert any(
        "current input-action" in issue
        or "current action inputs" in issue
        or "does not cover exactly" in issue
        or "directional shear case authority is missing" in issue
        for issue in rejected["publication_validation"]["issues"]
    )


@pytest.mark.parametrize(
    (
        "component_ids",
        "interaction_enabled",
        "resistance",
        "expected_status",
        "expected_validation",
    ),
    [
        ((), True, 1.0, "INVALID", "ACCEPTED"),
        (("vx",), True, 1.0, "NOT APPLICABLE", "ACCEPTED"),
        (("vx", "vy"), False, 1.0, "NOT ASSESSED", "ACCEPTED"),
        (("vx", "vy"), True, 1.0, "PASS", "REJECTED"),
        (("vx", "vy"), True, 0.1, "FAIL", "REJECTED"),
    ],
    ids=[
        "zero-invalid",
        "one-not-applicable",
        "two-disabled-not-assessed",
        "two-active-pass-needs-resistance-authority",
        "two-active-fail-needs-resistance-authority",
    ],
)
def test_input_only_directional_disposition_matrix(
    component_ids,
    interaction_enabled,
    resistance,
    expected_status,
    expected_validation,
):
    case_id = "ULS-INPUT-ONLY"
    inputs = {
        **multidirectional.crack_configuration({}),
        **_shear_input(),
        "shear_interaction_on": interaction_enabled,
        "shear_on": True,
        "shear_method": multidirectional.SHEAR_CODE_EN_2023,
        "plastic_case": {"id": case_id},
        "shear_components": {
            "vx": {"signed_v_ed": 0.2 if "vx" in component_ids else 0.0},
            "vy": {"signed_v_ed": 0.3 if "vy" in component_ids else 0.0},
        },
    }
    results = _shear_case(0.2, resistance, 0.3, resistance)
    for component_id in {"vx", "vy"}.difference(component_ids):
        results["shear"]["directions"].pop(component_id)
    multidirectional.apply_to_results(inputs, results)
    bundle = multidirectional.interaction_calculation_record(results)
    raw_interaction = bundle["shear_cases"][0]["interaction"]
    assert raw_interaction["status"] == expected_status

    safe = multidirectional.publication_safe_interaction_record(
        bundle,
        current_inputs=inputs,
    )
    assert safe["publication_validation"]["status"] == expected_validation
    if expected_validation == "ACCEPTED":
        assert safe["shear_cases"][0]["interaction"]["status"] == (
            expected_status
        )
        assert [
            component["id"]
            for component in safe["shear_cases"][0]["interaction"]["components"]
        ] == list(component_ids)
    else:
        assert safe["shear_cases"][0]["interaction"]["status"] == (
            "NOT ASSESSED"
        )
        assert any(
            "current solver component/resistance authority" in issue
            for issue in safe["publication_validation"]["issues"]
        )


@pytest.mark.parametrize(
    ("enabled_key", "method_key"),
    [
        ("crack_interaction_on", "crack_interaction_method"),
        ("shear_interaction_on", "shear_interaction_method"),
    ],
)
@pytest.mark.parametrize("method_value", ["missing", None])
def test_current_active_project_requires_explicit_interaction_method(
    enabled_key,
    method_key,
    method_value,
):
    scalars = {enabled_key: True}
    if method_value is None:
        scalars[method_key] = None
    project = {
        "format": project_io.FORMAT,
        "version": project_io.VERSION,
        "tables": {},
        "scalars": scalars,
    }

    with pytest.raises(ValueError, match=method_key):
        project_io.parse_project(json.dumps(project))
    with pytest.raises(ValueError, match=method_key):
        project_io.dump_project({}, scalars)


@pytest.mark.parametrize(
    ("enabled_key", "method_key", "method"),
    [
        (
            "crack_interaction_on",
            "crack_interaction_method",
            multidirectional.CRACK_METHOD_NONE,
        ),
        (
            "shear_interaction_on",
            "shear_interaction_method",
            multidirectional.SHEAR_METHOD_NONE,
        ),
    ],
)
def test_current_active_project_preserves_explicit_not_assessed_method(
    enabled_key,
    method_key,
    method,
):
    encoded = project_io.dump_project(
        {},
        {
            enabled_key: True,
            method_key: method,
        },
    )
    _tables, restored = project_io.parse_project(encoded)

    assert restored[enabled_key] is True
    assert restored[method_key] == method


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
