import math

import pytest

from sector import bridge
from tools import pr04_bridge_oracle as oracle


def _decisions(**states):
    records = []
    for check_id in bridge.APPLICABILITY_CHECK_IDS:
        applicability = states.get(check_id, bridge.NOT_APPLICABLE)
        records.append(bridge.ApplicabilityDecision(
            check_id=check_id,
            applicability=applicability,
            source=f"DB-{check_id}",
            notes="Independent applicability decision",
        ))
    return tuple(records)


def _external(status=bridge.STATUS_PASS, utilisation=0.5):
    return bridge.ExternalEvidence(
        status=status,
        result=f"{utilisation * 100:.1f} %",
        criterion="<= 100 %",
        source="calculated exact response",
        reason="solver evidence retained",
        utilisation=utilisation,
        evidence=({
            "methodology": bridge.EN1992_2_BASE,
            "concrete_method": bridge.CONCRETE_MINER,
            "miner_coefficient_c": bridge.STANDARD_CONCRETE_MINER_C,
        },),
    )


def _complete_evidence(**changes):
    evidence = bridge.BridgeBaseEvidence(
        methodology=bridge.EN1992_2_BASE,
        decisions=_decisions(
            section_analysis=bridge.REQUIRED,
            member_shear=bridge.REQUIRED,
            bridge_shear_detailing=bridge.NOT_APPLICABLE,
            reinforcement_fatigue=bridge.REQUIRED,
            concrete_fatigue=bridge.REQUIRED,
            sls_stress=bridge.REQUIRED,
            sls_crack=bridge.REQUIRED,
            web_flange_minimum=bridge.REQUIRED,
        ),
        has_tendons=False,
        has_hollow_section=False,
        fck_mpa=40.0,
        minimum_scope=bridge.MINIMUM_SCOPE_WEB_AND_FLANGE,
        minimum_components=(
            bridge.MinimumCrackComponent(
                "Web", 100_000.0, 0.4, 1.0, 3.0, 300.0, 500.0
            ),
            bridge.MinimumCrackComponent(
                "Flange", 80_000.0, 0.4, 1.0, 3.0, 300.0, 400.0
            ),
        ),
        shear_scope=bridge.SHEAR_SCOPE_MEMBER,
        bridge_exposure=bridge.BRIDGE_EXPOSURE_XD_XS,
        stress_responses=(
            bridge.StressResponse(
                "SLS-CHAR:total",
                "Characteristic",
                20.0,
                "CONVERGED",
                "Elastic case SLS-CHAR total response",
            ),
        ),
        section_analysis=_external(),
        shear=_external(),
        reinforcement_fatigue=_external(),
        concrete_fatigue=_external(),
        sls_crack=_external(),
    )
    return bridge.BridgeBaseEvidence(**{
        **evidence.__dict__,
        **changes,
    })


def _check(result, check_id):
    return next(
        item for item in result["checks"] if item["check_id"] == check_id
    )


def test_coverage_matrix_records_each_inheritance_state_and_key_gap():
    matrix = bridge.coverage_matrix()

    assert {
        item["disposition"] for item in matrix
    } == {
        bridge.DISPOSITION_INHERITED,
        bridge.DISPOSITION_OVERRIDDEN,
        bridge.DISPOSITION_ADDED,
        bridge.DISPOSITION_NOT_ASSESSED,
    }
    by_id = {item["check_id"]: item for item in matrix}
    assert "6.1(109)-(110)" in by_id["prestress_brittle"]["bridge_reference"]
    assert "6.3.2" in by_id["box_wall_torsion"]["bridge_reference"]
    assert "6.106" in by_id["concrete_fatigue"]["bridge_reference"]
    assert "Table 7.101N" in by_id["sls_crack"]["bridge_reference"]
    assert "7.3.2" in by_id["web_flange_minimum"]["bridge_reference"]


def test_complete_explicit_bridge_gate_can_pass_without_hiding_not_applicable_rows():
    result = bridge.assess_base_methodology(_complete_evidence())

    assert result["active"] is True
    assert result["status"] == bridge.STATUS_PASS
    assert {
        item["status"] for item in result["checks"]
    } == {bridge.STATUS_PASS, bridge.STATUS_NOT_APPLICABLE}


def test_inherited_member_shear_failure_is_independent_of_added_bridge_scope():
    evidence = _complete_evidence(
        shear=_external(bridge.STATUS_FAIL, 1.20),
    )

    result = bridge.assess_base_methodology(evidence)

    assert result["status"] == bridge.STATUS_FAIL
    assert _check(result, "member_shear")["status"] == bridge.STATUS_FAIL
    assert (
        _check(result, "bridge_shear_detailing")["status"]
        == bridge.STATUS_NOT_APPLICABLE
    )


def test_hollow_section_cannot_bypass_box_wall_override_without_wall_rows():
    evidence = _complete_evidence(
        decisions=_decisions(
            section_analysis=bridge.REQUIRED,
            member_shear=bridge.REQUIRED,
            bridge_shear_detailing=bridge.NOT_APPLICABLE,
            box_wall_torsion=bridge.NOT_APPLICABLE,
            reinforcement_fatigue=bridge.REQUIRED,
            concrete_fatigue=bridge.REQUIRED,
            sls_stress=bridge.REQUIRED,
            sls_crack=bridge.REQUIRED,
            web_flange_minimum=bridge.REQUIRED,
        ),
        has_hollow_section=True,
        expected_box_walls=0,
        box_walls=(),
    )

    check = _check(
        bridge.assess_base_methodology(evidence),
        "box_wall_torsion",
    )

    assert check["status"] == bridge.STATUS_NOT_ASSESSED
    assert "physical evidence" in check["reason"]


def test_absent_applicability_decisions_block_bridge_methodology():
    evidence = _complete_evidence(decisions=())

    result = bridge.assess_base_methodology(evidence)

    assert result["status"] == bridge.STATUS_NOT_ASSESSED
    assert all(
        item["status"] == bridge.STATUS_NOT_ASSESSED
        for item in result["checks"]
    )


@pytest.mark.parametrize(
    ("m_rep", "z_s", "f_yk"),
    [
        (250.0, 0.50, 500.0),
        (600.0, 0.80, 550.0),
    ],
)
def test_brittle_method_b_matches_independent_oracle(m_rep, z_s, f_yk):
    expected = oracle.brittle_method_b_area_mm2(m_rep, z_s, f_yk)

    assert bridge.minimum_brittle_reinforcement_area(
        m_rep, z_s, f_yk
    ) == pytest.approx(expected)


def test_brittle_method_b_failure_governs_incomplete_sibling_region():
    decisions = _decisions(prestress_brittle=bridge.REQUIRED)
    evidence = bridge.BridgeBaseEvidence(
        methodology=bridge.EN1992_2_BASE,
        decisions=decisions,
        has_tendons=True,
        has_hollow_section=False,
        fck_mpa=40.0,
        brittle_method=bridge.BRITTLE_METHOD_B,
        brittle_regions=(
            bridge.PrestressBrittleRegion(
                "Bottom", 250.0, 0.5, 500.0, 900.0
            ),
            bridge.PrestressBrittleRegion(
                "Top", True, 0.5, 500.0, 1_200.0
            ),
        ),
    )

    result = bridge.assess_base_methodology(evidence)
    check = _check(result, "prestress_brittle")

    assert check["status"] == bridge.STATUS_FAIL
    assert check["utilisation"] > 1.0
    assert "incomplete" in check["reason"]


def test_box_wall_interaction_and_common_angle_match_oracle():
    walls = (
        bridge.BoxWallEvidence("Top", 1.5, 120.0, 400.0, 80.0, 400.0),
        bridge.BoxWallEvidence("Bottom", 1.5, 100.0, 400.0, 60.0, 400.0),
    )
    evidence = _complete_evidence(
        decisions=_decisions(
            box_wall_torsion=bridge.REQUIRED,
            bridge_shear_detailing=bridge.NOT_APPLICABLE,
            concrete_fatigue=bridge.REQUIRED,
            sls_stress=bridge.REQUIRED,
            sls_crack=bridge.REQUIRED,
            web_flange_minimum=bridge.REQUIRED,
        ),
        has_hollow_section=True,
        expected_box_walls=2,
        box_walls=walls,
    )

    result = bridge.assess_base_methodology(evidence)
    check = _check(result, "box_wall_torsion")

    assert check["status"] == bridge.STATUS_PASS
    assert check["utilisation"] == pytest.approx(
        oracle.box_wall_interaction(120.0, 400.0, 80.0, 400.0)
    )


def test_box_wall_mismatched_angle_blocks_even_when_each_ratio_passes():
    evidence = _complete_evidence(
        decisions=_decisions(
            box_wall_torsion=bridge.REQUIRED,
            bridge_shear_detailing=bridge.NOT_APPLICABLE,
            concrete_fatigue=bridge.REQUIRED,
            sls_stress=bridge.REQUIRED,
            sls_crack=bridge.REQUIRED,
            web_flange_minimum=bridge.REQUIRED,
        ),
        has_hollow_section=True,
        expected_box_walls=2,
        box_walls=(
            bridge.BoxWallEvidence(
                "Top", 1.5, 50.0, 500.0, 50.0, 500.0
            ),
            bridge.BoxWallEvidence(
                "Bottom", 2.0, 50.0, 500.0, 50.0, 500.0
            ),
        ),
    )

    check = _check(
        bridge.assess_base_methodology(evidence),
        "box_wall_torsion",
    )

    assert check["status"] == bridge.STATUS_NOT_ASSESSED
    assert "same compression-field" in check["reason"]


@pytest.mark.parametrize("cot_theta", [1.0, 2.5])
def test_box_wall_normative_strut_angle_bounds_are_inclusive(cot_theta):
    assert oracle.box_wall_cot_theta_is_admissible(cot_theta)
    evidence = _complete_evidence(
        decisions=_decisions(box_wall_torsion=bridge.REQUIRED),
        has_hollow_section=True,
        expected_box_walls=1,
        box_walls=(
            bridge.BoxWallEvidence(
                "Wall", cot_theta, 10.0, 100.0, 10.0, 100.0
            ),
        ),
    )

    check = _check(
        bridge.assess_base_methodology(evidence),
        "box_wall_torsion",
    )

    assert check["status"] == bridge.STATUS_PASS


@pytest.mark.parametrize(
    "cot_theta",
    [
        math.nextafter(1.0, 0.0),
        math.nextafter(2.5, math.inf),
        0.999,
        2.501,
        10.0,
        True,
        float("nan"),
        float("inf"),
    ],
)
def test_box_wall_out_of_domain_or_false_numeric_angle_cannot_pass(cot_theta):
    evidence = _complete_evidence(
        decisions=_decisions(box_wall_torsion=bridge.REQUIRED),
        has_hollow_section=True,
        expected_box_walls=1,
        box_walls=(
            bridge.BoxWallEvidence(
                "Wall", cot_theta, 10.0, 100.0, 10.0, 100.0
            ),
        ),
    )

    check = _check(
        bridge.assess_base_methodology(evidence),
        "box_wall_torsion",
    )

    assert check["status"] == bridge.STATUS_NOT_ASSESSED
    assert bridge.assess_base_methodology(evidence)["status"] != (
        bridge.STATUS_PASS
    )


def test_box_wall_known_failure_governs_incomplete_sibling_wall():
    evidence = _complete_evidence(
        decisions=_decisions(
            box_wall_torsion=bridge.REQUIRED,
            bridge_shear_detailing=bridge.NOT_APPLICABLE,
            concrete_fatigue=bridge.REQUIRED,
            sls_stress=bridge.REQUIRED,
            sls_crack=bridge.REQUIRED,
            web_flange_minimum=bridge.REQUIRED,
        ),
        has_hollow_section=True,
        expected_box_walls=2,
        box_walls=(
            bridge.BoxWallEvidence(
                "Top", 1.5, 400.0, 500.0, 250.0, 500.0
            ),
            bridge.BoxWallEvidence(
                "Bottom", 1.5, True, 500.0, 50.0, 500.0
            ),
        ),
    )

    check = _check(
        bridge.assess_base_methodology(evidence),
        "box_wall_torsion",
    )

    assert check["status"] == bridge.STATUS_FAIL
    assert check["utilisation"] > 1.0
    assert "incomplete" in check["reason"]


def test_bridge_stress_routes_only_to_explicit_characteristic_response():
    evidence = _complete_evidence(stress_responses=(
        bridge.StressResponse(
            "QP:long",
            "Quasi-permanent",
            30.0,
            "CONVERGED",
            "unrelated QP response",
        ),
        bridge.StressResponse(
            "CHAR:total",
            "Characteristic",
            20.0,
            "CONVERGED",
            "required characteristic response",
        ),
    ))

    check = _check(
        bridge.assess_base_methodology(evidence),
        "sls_stress",
    )

    assert check["status"] == bridge.STATUS_PASS
    assert check["utilisation"] == pytest.approx(
        20.0 / oracle.bridge_stress_limit_mpa(40.0)
    )
    assert check["evidence"][0]["response_id"] == "CHAR:total"


@pytest.mark.parametrize(
    "responses",
    [
        (),
        (
            bridge.StressResponse(
                "A", "Characteristic", 20.0, "CONVERGED", "solve A"
            ),
            bridge.StressResponse(
                "B", "Characteristic", 21.0, "CONVERGED", "solve B"
            ),
        ),
        (
            bridge.StressResponse(
                "A", "Characteristic", True, "CONVERGED", "solve A"
            ),
        ),
    ],
)
def test_bridge_stress_missing_duplicate_or_boolean_evidence_cannot_pass(
    responses,
):
    check = _check(
        bridge.assess_base_methodology(
            _complete_evidence(stress_responses=responses)
        ),
        "sls_stress",
    )

    assert check["status"] == bridge.STATUS_NOT_ASSESSED


def test_web_and_flange_minimum_are_separate_and_apply_shrinkage_floor():
    required, fct_used = bridge.minimum_crack_reinforcement_area(
        100_000.0,
        0.4,
        1.0,
        2.4,
        300.0,
        restrained_shrinkage=True,
    )

    assert fct_used == pytest.approx(2.9)
    assert required == pytest.approx(
        oracle.component_minimum_area_mm2(
            100_000.0,
            0.4,
            1.0,
            2.4,
            300.0,
            restrained_shrinkage=True,
        )
    )


@pytest.mark.parametrize("factor", [0.65, 1.0])
def test_bridge_minimum_k_normative_bounds_are_inclusive(factor):
    required, _ = bridge.minimum_crack_reinforcement_area(
        100_000.0,
        0.4,
        factor,
        3.0,
        300.0,
    )

    assert required == pytest.approx(400.0 * factor)
    dimension = 800.0 if factor == 0.65 else 300.0
    assert factor == pytest.approx(
        oracle.minimum_crack_k_from_dimension_mm(dimension)
    )


@pytest.mark.parametrize(
    "factor",
    [
        math.nextafter(0.65, 0.0),
        math.nextafter(1.0, math.inf),
        0.649,
        1.001,
        0.01,
        True,
        float("nan"),
        float("inf"),
    ],
)
def test_bridge_minimum_k_out_of_domain_or_false_numeric_is_rejected(factor):
    with pytest.raises(ValueError, match="k|real|finite"):
        bridge.minimum_crack_reinforcement_area(
            100_000.0,
            0.4,
            factor,
            3.0,
            300.0,
        )


def test_bridge_minimum_k_false_pass_pair_fails_closed():
    unsafe = _complete_evidence(
        minimum_scope=bridge.MINIMUM_SCOPE_WEB,
        minimum_components=(
            bridge.MinimumCrackComponent(
                "Web", 100_000.0, 0.4, 0.01, 3.0, 300.0, 5.0
            ),
        ),
    )
    normative = _complete_evidence(
        minimum_scope=bridge.MINIMUM_SCOPE_WEB,
        minimum_components=(
            bridge.MinimumCrackComponent(
                "Web", 100_000.0, 0.4, 0.65, 3.0, 300.0, 5.0
            ),
        ),
    )

    unsafe_check = _check(
        bridge.assess_base_methodology(unsafe),
        "web_flange_minimum",
    )
    normative_check = _check(
        bridge.assess_base_methodology(normative),
        "web_flange_minimum",
    )

    assert unsafe_check["status"] == bridge.STATUS_NOT_ASSESSED
    assert normative_check["status"] == bridge.STATUS_FAIL
    assert normative_check["result"].startswith(
        "governing As,min / As,provided"
    )


def test_minimum_known_failure_governs_incomplete_sibling_component():
    evidence = _complete_evidence(minimum_components=(
        bridge.MinimumCrackComponent(
            "Web", 100_000.0, 0.4, 1.0, 3.0, 300.0, 100.0
        ),
        bridge.MinimumCrackComponent(
            "Flange", True, 0.4, 1.0, 3.0, 300.0, 400.0
        ),
    ))

    check = _check(
        bridge.assess_base_methodology(evidence),
        "web_flange_minimum",
    )

    assert check["status"] == bridge.STATUS_FAIL
    assert check["utilisation"] > 1.0
    assert "incomplete" in check["reason"]


def test_required_unsupported_bridge_provision_is_blocking():
    evidence = _complete_evidence(
        decisions=_decisions(
            bridge_shear_detailing=bridge.REQUIRED,
            concrete_fatigue=bridge.REQUIRED,
            shear_torsion_fatigue=bridge.REQUIRED,
            sls_stress=bridge.REQUIRED,
            sls_crack=bridge.REQUIRED,
            web_flange_minimum=bridge.REQUIRED,
        )
    )

    result = bridge.assess_base_methodology(evidence)

    assert result["status"] == bridge.STATUS_NOT_ASSESSED
    assert (
        _check(result, "shear_torsion_fatigue")["status"]
        == bridge.STATUS_NOT_ASSESSED
    )


def test_inactive_component_method_does_not_emit_bridge_checks():
    evidence = _complete_evidence(
        methodology=bridge.COMPONENT_METHODS
    )

    result = bridge.assess_base_methodology(evidence)

    assert result["active"] is False
    assert result["checks"] == []


def test_publication_boundary_recomputes_status_and_rejects_missing_check():
    raw = bridge.assess_base_methodology(_complete_evidence())
    raw["status"] = bridge.STATUS_FAIL

    safe = bridge.publication_safe_record(raw)

    assert safe["status"] == bridge.STATUS_PASS
    assert safe["configuration_errors"] == []

    raw["checks"] = raw["checks"][:-1]
    raw["status"] = bridge.STATUS_PASS
    safe = bridge.publication_safe_record(raw)

    assert safe["status"] == bridge.STATUS_INVALID
    assert any(
        "missing bridge check" in error
        for error in safe["configuration_errors"]
    )
    assert safe["checks"][-1]["status"] == bridge.STATUS_NOT_ASSESSED


def test_publication_boundary_rejects_boolean_utilisation_and_duplicate_check():
    raw = bridge.assess_base_methodology(_complete_evidence())
    raw["checks"][0]["utilisation"] = True
    raw["checks"].append(dict(raw["checks"][1]))

    safe = bridge.publication_safe_record(raw)

    assert safe["status"] == bridge.STATUS_INVALID
    assert any("duplicate bridge check" in error for error in safe[
        "configuration_errors"
    ])
    assert safe["checks"][0]["status"] == bridge.STATUS_NOT_ASSESSED


@pytest.mark.parametrize(
    "mutation",
    [
        lambda check: check.update(status=bridge.STATUS_FAIL),
        lambda check: check.update(result="stale result"),
        lambda check: check.update(source="different source"),
        lambda check: check.update(evidence=[]),
    ],
)
def test_publication_boundary_rejects_mutated_bound_check_body(mutation):
    raw = bridge.assess_base_methodology(_complete_evidence())
    stress = next(
        check
        for check in raw["checks"]
        if check["check_id"] == "sls_stress"
    )
    mutation(stress)

    safe = bridge.publication_safe_record(raw)

    assert safe["status"] == bridge.STATUS_INVALID
    assert any(
        "fingerprint does not match" in error
        for error in safe["configuration_errors"]
    )


def _rebind_mutated_record(record):
    record["evidence_fingerprint"] = bridge.bridge_evidence_fingerprint(
        record["checks"],
        record["configuration_errors"],
    )
    return record


def test_publication_boundary_revalidates_stored_box_wall_cot_theta():
    evidence = _complete_evidence(
        decisions=_decisions(
            section_analysis=bridge.REQUIRED,
            member_shear=bridge.REQUIRED,
            box_wall_torsion=bridge.REQUIRED,
            reinforcement_fatigue=bridge.REQUIRED,
            concrete_fatigue=bridge.REQUIRED,
            sls_stress=bridge.REQUIRED,
            sls_crack=bridge.REQUIRED,
            web_flange_minimum=bridge.REQUIRED,
        ),
        has_hollow_section=True,
        expected_box_walls=1,
        box_walls=(
            bridge.BoxWallEvidence(
                "Wall", 1.5, 10.0, 100.0, 10.0, 100.0
            ),
        ),
    )
    raw = bridge.assess_base_methodology(evidence)
    check = _check(raw, "box_wall_torsion")
    check["evidence"][0]["cot_theta"] = 10.0
    _rebind_mutated_record(raw)

    safe = bridge.publication_safe_record(raw)
    safe_check = _check(safe, "box_wall_torsion")

    assert safe["status"] == bridge.STATUS_INVALID
    assert safe_check["status"] == bridge.STATUS_NOT_ASSESSED
    assert any(
        "cot(theta) is outside" in error
        for error in safe["configuration_errors"]
    )


def test_publication_boundary_revalidates_stored_minimum_k():
    raw = bridge.assess_base_methodology(_complete_evidence())
    check = _check(raw, "web_flange_minimum")
    check["evidence"][0]["k"] = 0.01
    _rebind_mutated_record(raw)

    safe = bridge.publication_safe_record(raw)
    safe_check = _check(safe, "web_flange_minimum")

    assert safe["status"] == bridge.STATUS_INVALID
    assert safe_check["status"] == bridge.STATUS_NOT_ASSESSED
    assert any(
        "minimum-reinforcement row 1 k is outside" in error
        for error in safe["configuration_errors"]
    )


def test_publication_boundary_revalidates_stored_bridge_miner_c():
    raw = bridge.assess_base_methodology(_complete_evidence())
    check = _check(raw, "concrete_fatigue")
    check["evidence"][0]["miner_coefficient_c"] = 100.0
    _rebind_mutated_record(raw)

    safe = bridge.publication_safe_record(raw)
    safe_check = _check(safe, "concrete_fatigue")

    assert safe["status"] == bridge.STATUS_INVALID
    assert safe_check["status"] == bridge.STATUS_NOT_ASSESSED
    assert any(
        "not bound to C = 14" in error
        for error in safe["configuration_errors"]
    )


def test_publication_boundary_is_idempotent_and_retains_configuration_errors():
    raw = bridge.assess_base_methodology(_complete_evidence(
        configuration_errors=("bridge table evidence is malformed",)
    ))

    first = bridge.publication_safe_record(raw)
    second = bridge.publication_safe_record(first)

    assert first == second
    assert second["status"] == bridge.STATUS_INVALID
    assert second["configuration_errors"] == [
        "bridge table evidence is malformed"
    ]
    assert second["evidence_schema"] == bridge.BRIDGE_EVIDENCE_SCHEMA
    assert len(second["evidence_fingerprint"]) == 64
