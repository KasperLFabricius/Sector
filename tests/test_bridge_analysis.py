from __future__ import annotations

import pathlib
from types import SimpleNamespace
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import bridge_analysis  # noqa: E402
import bridge_inputs  # noqa: E402
import fatigue_analysis  # noqa: E402
import fatigue_inputs  # noqa: E402
from sector import bridge, conformance, sls  # noqa: E402


def _coverage(**states):
    rows = bridge_inputs.default_coverage_records()
    for row in rows:
        row["applicability"] = states.get(
            row["check_id"],
            bridge.NOT_APPLICABLE,
        )
        row["source"] = f"DB-{row['check_id']}"
    return bridge_inputs.table_from_records(
        rows,
        bridge_inputs.COVERAGE_TABLE_KEY,
    )


def _base_input(**changes):
    value = {
        "design_methodology": bridge.EN1992_2_BASE,
        bridge_inputs.COVERAGE_TABLE_KEY: _coverage(
            section_analysis=bridge.REQUIRED,
            sls_stress=bridge.REQUIRED,
        ),
        bridge_inputs.BRITTLE_TABLE_KEY: bridge_inputs.empty_table(
            bridge_inputs.BRITTLE_TABLE_KEY
        ),
        bridge_inputs.BOX_WALL_TABLE_KEY: bridge_inputs.empty_table(
            bridge_inputs.BOX_WALL_TABLE_KEY
        ),
        bridge_inputs.MINIMUM_TABLE_KEY: bridge_inputs.empty_table(
            bridge_inputs.MINIMUM_TABLE_KEY
        ),
        "bridge_brittle_method": bridge.BRITTLE_NOT_ESTABLISHED,
        "bridge_expected_box_walls": 0,
        "bridge_minimum_scope": bridge.MINIMUM_SCOPE_NOT_ESTABLISHED,
        "bridge_shear_scope": bridge.SHEAR_SCOPE_NOT_ESTABLISHED,
        "bridge_exposure": bridge.BRIDGE_EXPOSURE_XD_XS,
        "concrete": SimpleNamespace(fck=40.0),
        "concrete_preset": "DS/EN 1992-1-1:2005",
        "mild_material_catalog": {
            "items": [{"id": "B500", "preset": "EN 1992-1-1:2005"}],
        },
        "prestress_material_catalog": {"items": []},
        "tendons": [],
        "holes": [],
        "mode": "Elastic",
        "shear_on": False,
        "fatigue_on": False,
        "fatigue_gamma_ff": 1.0,
        fatigue_inputs.BASIS_KEY: fatigue_inputs.default_basis(),
    }
    value.update(changes)
    return value


def _bridge_fatigue_payload(
    *,
    coefficient=14.0,
    reinforcement=False,
    concrete=True,
    factor_mode=fatigue_inputs.FACTOR_MODE_PRESET,
    factor_approval="",
    gamma_s=1.15,
    gamma_c=1.50,
    gamma_ff=1.0,
    concrete_method=fatigue_analysis.CONCRETE_MINER,
    miner_basis=fatigue_inputs.MINER_BASIS_BRIDGE_STANDARD,
    miner_source="",
    basis=None,
):
    edition = fatigue_inputs.EC2_2_2005_AC
    gamma_s, gamma_c, factor_basis = (
        fatigue_inputs.resolve_fatigue_factors(
            edition,
            mode=factor_mode,
            gamma_s=gamma_s,
            gamma_c=gamma_c,
            approval_reference=factor_approval,
        )
    )
    miner = (
        fatigue_analysis.concrete_miner_conformance(
            edition=edition,
            concrete_method=concrete_method,
            miner_basis=miner_basis,
            miner_source=miner_source,
            coefficient_c=coefficient,
            design_methodology=bridge.EN1992_2_BASE,
        )
        if concrete
        else None
    )
    records = []
    if reinforcement:
        records.append(
            factor_basis["parameter_conformance"]["gamma_s"]
        )
    if concrete:
        records.extend((
            factor_basis["parameter_conformance"]["gamma_c"],
            miner,
        ))
    aggregate = conformance.aggregate(
        records,
        analytical_status=conformance.STATUS_PASS,
        selected_standard=edition,
    )
    return {
        "errors": (),
        "valid": True,
        "converged": True,
        "passed": True,
        "edition": edition,
        "design_methodology": bridge.EN1992_2_BASE,
        "basis": fatigue_inputs.normalise_basis(basis),
        "checks": {
            "reinforcement": reinforcement,
            "concrete": concrete,
        },
        "concrete_method": concrete_method if concrete else None,
        "concrete_miner_basis": miner_basis if concrete else None,
        "concrete_miner_source": miner_source if concrete else "",
        "partial_factors": {
            "gamma_s": gamma_s,
            "gamma_c": gamma_c,
            "gamma_ff": gamma_ff,
        },
        "factor_basis": factor_basis,
        "parameter_conformance": records,
        "conformance": aggregate,
        "assessment_status": aggregate["assessment_status"],
        "qualified_verdict": aggregate["qualified_verdict"],
        "standard_passed": (
            aggregate["state"] == conformance.STATE_CONFORMS
        ),
        "concrete_parameters": (
            {
                "c": coefficient,
                "method": concrete_method,
                "parameter_conformance": miner,
            }
            if concrete
            else None
        ),
        "calculation_references": {
            **(
                {"reinforcement": "EN 1992-1-1 inherited fatigue method"}
                if reinforcement
                else {}
            ),
            **(
                {"concrete": "EN 1992-2 corrected Expression (6.106)"}
                if concrete
                else {}
            ),
        },
        "spectra": [{
            "spectrum_name": "Traffic",
            "reinforcement": (
                [{
                    "element_id": "R1",
                    "kind": "mild",
                    "detail_id": "D1",
                    "converged": True,
                    "passed": True,
                    "damage_utilisation": 0.40,
                    "yield_utilisation": 0.30,
                    "utilisation": 0.40,
                }]
                if reinforcement
                else []
            ),
            "concrete": (
                [{
                    "fibre_index": 0,
                    "converged": True,
                    "passed": True,
                    "utilisation": 0.5,
                }]
                if concrete
                else []
            ),
        }],
    }


def _bridge_miner_payload(*, coefficient=14.0):
    return _bridge_fatigue_payload(coefficient=coefficient)


def _bridge_fatigue_input(
    *,
    reinforcement=False,
    concrete=True,
    factor_mode=fatigue_inputs.FACTOR_MODE_PRESET,
    factor_approval="",
    gamma_s=1.15,
    gamma_c=1.50,
    gamma_ff=1.0,
    coefficient=14.0,
    concrete_method=fatigue_analysis.CONCRETE_MINER,
    miner_basis=fatigue_inputs.MINER_BASIS_BRIDGE_STANDARD,
    miner_source="",
    **changes,
):
    value = _base_input(
        fatigue_on=True,
        fatigue_check_steel=reinforcement,
        fatigue_check_concrete=concrete,
        fatigue_edition=fatigue_inputs.EC2_2_2005_AC,
        fatigue_factor_mode=factor_mode,
        fatigue_factor_approval=factor_approval,
        fatigue_gamma_s=gamma_s,
        fatigue_gamma_c=gamma_c,
        fatigue_gamma_ff=gamma_ff,
        fatigue_concrete_method=concrete_method,
        fatigue_concrete_miner_basis=miner_basis,
        fatigue_concrete_miner_source=miner_source,
        fatigue_concrete_c=coefficient,
    )
    value.update(changes)
    return value


def _elastic_results(long_combination, total_combination):
    return {
        "elastic_cases": [{
            "name": "SLS-1",
            "actions": {
                "long_combination": long_combination,
                "total_combination": total_combination,
            },
            "results": {
                "elastic": {
                    "converged": True,
                    "max_conc_long": 20.0,
                    "max_conc": 31.0,
                },
            },
        }],
    }


def _bridge_crack_elastic(
    *,
    label="QP",
    combination=sls.COMBINATION_QUASI_PERMANENT,
    response_id="bridge-qp",
    width=0.22,
):
    context = {
        "combination": combination,
        "duration": "long",
        "response_id": response_id,
        "provenance": f"explicit mapping {response_id}",
        "solver_provenance": {
            "state": response_id,
            "converged": True,
        },
    }
    scope = [{
        "combination": combination,
        "duration": context["duration"],
        "response": label,
        "response_id": response_id,
        "elastic_case": response_id,
        "state": response_id,
        "provenance": context["provenance"],
    }]
    responses = {
        label: {
            "wk": width,
            "element_id": "bar 1",
        },
    }
    criteria = sls.crack_criteria_from_inputs({
        "sls_criterion_mode": sls.CRITERION_MODE_STANDARD,
        "sls_edition": sls.EDITION_BRIDGE_2005_AC,
        "sls_code": "DS/EN 1992-2:2005 + AC:2008",
        "sls_member": "Bridge member",
        "sls_dk_na": False,
        "sls_prestress_class": sls.PRESTRESS_REINFORCED_UNBONDED,
        "sls_protection_class": sls.PROTECTION_LEVEL_1_OR_PRETENSIONED,
        "sls_exposure_class": sls.EXPOSURE_XC2_XC4,
        "sls_exposure_context": "bridge durability",
        "sls_bridge_exposure_class": sls.BRIDGE_EXPOSURE_XC2_XC4,
        "sls_check_appearance": False,
        "sls_check_durability": True,
        "sls_wk_limit": 0.30,
        "sls_decompression_applicability": sls.DECOMPRESSION_NOT_REQUIRED,
    })
    assessment = sls.crack_assessment(
        responses,
        valid=True,
        criteria=criteria,
        response_contexts={label: context},
        response_mapping_scope=scope,
    )
    return {
        "crack_assessment": assessment,
        "crack_responses": responses,
        "crack_response_contexts": {label: context},
        "crack_response_mapping_scope": assessment["response_mapping_scope"],
    }


def test_stress_adapter_keeps_duration_and_combination_independent():
    responses = bridge_analysis.stress_responses(_elastic_results(
        sls.COMBINATION_CHARACTERISTIC,
        sls.COMBINATION_QUASI_PERMANENT,
    ))

    assert [
        (
            item.response_id,
            item.combination,
            item.compression_mpa,
        )
        for item in responses
    ] == [
        ("SLS-1:long", sls.COMBINATION_CHARACTERISTIC, 20.0),
        ("SLS-1:total", sls.COMBINATION_QUASI_PERMANENT, 31.0),
    ]


def test_bridge_gate_uses_only_the_explicit_characteristic_stress_response():
    result = bridge_analysis.assess(
        _base_input(),
        _elastic_results(
            sls.COMBINATION_CHARACTERISTIC,
            sls.COMBINATION_QUASI_PERMANENT,
        ),
    )
    stress = next(
        check
        for check in result["checks"]
        if check["check_id"] == "sls_stress"
    )

    assert result["status"] == bridge.STATUS_PASS
    assert stress["status"] == bridge.STATUS_PASS
    assert stress["evidence"][0]["response_id"] == "SLS-1:long"
    assert stress["utilisation"] == pytest.approx(20.0 / 24.0)


def test_boolean_characteristic_stress_cannot_publish_pass():
    results = _elastic_results(
        sls.COMBINATION_CHARACTERISTIC,
        sls.COMBINATION_QUASI_PERMANENT,
    )
    results["elastic_cases"][0]["results"]["elastic"]["max_conc_long"] = True

    result = bridge_analysis.assess(_base_input(), results)
    stress = next(
        check
        for check in result["checks"]
        if check["check_id"] == "sls_stress"
    )

    assert result["status"] == bridge.STATUS_NOT_ASSESSED
    assert stress["status"] == bridge.STATUS_NOT_ASSESSED


def test_crack_adapter_ignores_unmatched_case_copy_after_one_exact_match():
    exact = _bridge_crack_elastic()
    criterion = exact["crack_assessment"]["criteria"][0]
    unmatched = {
        **criterion,
        "status": "NOT ASSESSED",
        "value": None,
        "util": None,
        "matched_responses": [],
        "reason": "Required combination is in another case",
        "acceptance_evidence": None,
    }
    results = {
        "elastic_cases": [
            {
                "results": {
                    "elastic": exact,
                },
            },
            {
                "results": {
                    "elastic": {
                        "crack_assessment": {"criteria": [unmatched]},
                    },
                },
            },
        ],
    }

    evidence = bridge_analysis.crack_evidence(results)

    assert evidence.status == bridge.STATUS_PASS
    assert evidence.utilisation == pytest.approx(0.22 / 0.30)
    assert "Table 7.101N" in evidence.source
    assert evidence.evidence[0]["matched_responses"] == ["QP"]
    assert (
        evidence.evidence[0]["solver_provenance"]["state"]
        == "bridge-qp"
    )


@pytest.mark.parametrize(
    "mutation",
    ["missing", "arbitrary", "stale-response", "fingerprint"],
)
def test_bridge_crack_acceptance_requires_current_canonical_binding(mutation):
    elastic = _bridge_crack_elastic()
    criterion = elastic["crack_assessment"]["criteria"][0]
    if mutation == "missing":
        criterion.pop("acceptance_evidence")
    elif mutation == "arbitrary":
        criterion["acceptance_evidence"] = {"fingerprint": "0" * 64}
    elif mutation == "stale-response":
        elastic["crack_responses"]["QP"]["wk"] = 0.25
    else:
        criterion["acceptance_evidence"]["fingerprint"] = "0" * 64

    evidence = bridge_analysis.crack_evidence({
        "elastic_cases": [{"results": {"elastic": elastic}}],
    })

    assert evidence.status == bridge.STATUS_NOT_ASSESSED
    assert "Canonical crack acceptance evidence" in evidence.reason


def test_duplicate_matched_bridge_criterion_identity_is_not_assessed():
    first = _bridge_crack_elastic(response_id="bridge-qp-a")
    second = _bridge_crack_elastic(response_id="bridge-qp-b")

    evidence = bridge_analysis.crack_evidence({
        "elastic_cases": [
            {"results": {"elastic": first}},
            {"results": {"elastic": second}},
        ],
    })

    assert evidence.status == bridge.STATUS_NOT_ASSESSED
    assert "Exactly one canonically bound criterion" in evidence.reason


def test_malformed_elastic_case_collection_blocks_without_raising():
    responses = bridge_analysis.stress_responses({
        "elastic_cases": True,
    })

    assert responses == ()


@pytest.mark.parametrize("matched_responses", [True, "QP", {"QP": True}])
def test_malformed_bridge_crack_match_container_cannot_pass(
    matched_responses,
):
    results = {
        "elastic_cases": [{
            "results": {
                "elastic": {
                    "crack_assessment": {
                        "criteria": [{
                            "criterion_id": "bridge-standard-durability",
                            "kind": sls.CRITERION_DURABILITY,
                            "status": "OK",
                            "value": 0.22,
                            "limit_mm": 0.30,
                            "util": 0.22 / 0.30,
                            "matched_responses": matched_responses,
                            "criterion_source": "Table 7.101N",
                            "solver_provenance": {"solve": "v1"},
                        }],
                    },
                },
            },
        }],
    }

    evidence = bridge_analysis.crack_evidence(results)

    assert evidence.status == bridge.STATUS_NOT_ASSESSED


def test_boolean_bridge_crack_value_cannot_pass():
    results = {
        "elastic_cases": [{
            "results": {
                "elastic": {
                    "crack_assessment": {
                        "criteria": [{
                            "criterion_id": "bridge-standard-durability",
                            "kind": sls.CRITERION_DURABILITY,
                            "status": "OK",
                            "value": True,
                            "limit_mm": 0.30,
                            "util": 0.5,
                            "matched_responses": ["QP"],
                            "criterion_source": "Table 7.101N",
                            "solver_provenance": {"solve": "v1"},
                        }],
                    },
                },
            },
        }],
    }

    evidence = bridge_analysis.crack_evidence(results)

    assert evidence.status == bridge.STATUS_NOT_ASSESSED


@pytest.mark.parametrize(
    ("adapter", "component"),
    [
        (bridge_analysis.reinforcement_fatigue_evidence, "reinforcement"),
        (bridge_analysis.concrete_fatigue_evidence, "concrete"),
    ],
)
@pytest.mark.parametrize("utilisation", [True, float("nan")])
def test_malformed_fatigue_utilisation_cannot_pass(
    adapter,
    component,
    utilisation,
):
    payload = {
        "checks": {component: True},
        "calculation_references": {component: "Controlled fatigue source"},
        "spectra": [{
            "spectrum_name": "Traffic",
            component: [{
                "converged": True,
                "passed": True,
                "utilisation": utilisation,
            }],
        }],
    }

    evidence = adapter({"fatigue": payload})

    assert evidence.status == bridge.STATUS_INVALID


def test_unbounded_fatigue_failure_governs_finite_passing_row():
    evidence = bridge_analysis._external(
        [
            {
                "status": bridge.STATUS_FAIL,
                "result": "infinite Miner damage",
                "criterion": "<= 100 %",
                "util": float("inf"),
                "_requires_utilisation": True,
                "source": "Unbounded concrete fibre",
                "note": "Spectrum A / fibre 4",
            },
            {
                "status": bridge.STATUS_PASS,
                "result": "75.0 %",
                "criterion": "<= 100 %",
                "util": 0.75,
                "_requires_utilisation": True,
                "source": "Finite reinforcement row",
                "note": "Spectrum B / R1",
            },
        ],
        empty_reason="No fatigue evidence.",
        source="Controlled fatigue source",
    )

    assert evidence.status == bridge.STATUS_FAIL
    assert evidence.result == "infinite Miner damage"
    assert evidence.source == "Unbounded concrete fibre"
    assert evidence.utilisation is None
    assert evidence.evidence[0]["unbounded_utilisation"] is True
    assert evidence.evidence[1]["unbounded_utilisation"] is False

    check = bridge._external_result(
        "concrete_fatigue",
        evidence,
        bridge.ApplicabilityDecision(
            "concrete_fatigue",
            bridge.REQUIRED,
            "DB-FAT-UNBOUNDED",
        ),
    )
    assert check.status == bridge.STATUS_FAIL
    assert check.result == "infinite Miner damage"
    assert check.source == "Unbounded concrete fibre"
    assert check.utilisation is None


@pytest.mark.parametrize(
    ("payload_change", "reason"),
    [
        (
            {"edition": "DS/EN 1992-1-1:2023"},
            "calculated fatigue edition",
        ),
        (
            {"design_methodology": bridge.COMPONENT_METHODS},
            "whole-calculation methodology",
        ),
    ],
)
def test_bridge_concrete_fatigue_rejects_mismatched_result_context(
    payload_change,
    reason,
):
    inp = _base_input(
        fatigue_on=True,
        fatigue_edition="DS/EN 1992-2:2005 + AC:2008",
        fatigue_check_concrete=True,
        fatigue_concrete_method="Explicit Palmgren-Miner spectrum",
        fatigue_concrete_miner_basis="EN 1992-2 bridge methodology",
        fatigue_concrete_c=14.0,
    )
    payload = _bridge_miner_payload()
    payload.update(payload_change)

    evidence = bridge_analysis.concrete_fatigue_evidence(
        {"fatigue": payload},
        inp,
    )

    assert evidence.status == bridge.STATUS_INVALID
    assert reason in evidence.reason


@pytest.mark.parametrize(
    ("adapter", "family", "custom_factors", "payload_options", "parameter_id"),
    [
        (
            bridge_analysis.reinforcement_fatigue_evidence,
            "reinforcement",
            {"gamma_s": 0.5, "gamma_c": 1.50},
            {"reinforcement": True, "concrete": False},
            "fatigue.gamma_s",
        ),
        (
            bridge_analysis.concrete_fatigue_evidence,
            "concrete",
            {"gamma_s": 1.15, "gamma_c": 2.0},
            {"reinforcement": False, "concrete": True},
            "fatigue.gamma_c",
        ),
    ],
)
def test_bridge_fatigue_adapters_bind_current_custom_factor_context(
    adapter,
    family,
    custom_factors,
    payload_options,
    parameter_id,
):
    current = _bridge_fatigue_input(
        **payload_options,
        factor_mode=fatigue_inputs.FACTOR_MODE_OVERRIDE,
        factor_approval="DB-CURRENT-FACTOR",
        **custom_factors,
    )
    stale_standard = _bridge_fatigue_payload(**payload_options)

    rejected = adapter({"fatigue": stale_standard}, current)

    assert rejected.status == bridge.STATUS_INVALID
    assert "current fatigue factor" in rejected.reason
    assert "conflict" in rejected.reason

    matching_custom = _bridge_fatigue_payload(
        **payload_options,
        factor_mode=fatigue_inputs.FACTOR_MODE_OVERRIDE,
        factor_approval="DB-CURRENT-FACTOR",
        **custom_factors,
    )
    accepted = adapter({"fatigue": matching_custom}, current)

    assert accepted.status == bridge.STATUS_REVIEW
    assert accepted.evidence[0]["fatigue_factor_mode"] == (
        fatigue_inputs.FACTOR_MODE_OVERRIDE
    )
    assert accepted.evidence[0]["fatigue_factor_approval"] == (
        "DB-CURRENT-FACTOR"
    )
    records = {
        record["parameter_id"]: record
        for record in accepted.evidence[0][
            "fatigue_parameter_conformance"
        ]
    }
    assert records[parameter_id]["actual_value"] == (
        custom_factors["gamma_s"]
        if family == "reinforcement"
        else custom_factors["gamma_c"]
    )
    assert records[parameter_id]["state"] == (
        conformance.STATE_APPROVED_CUSTOM
    )


@pytest.mark.parametrize(
    ("adapter", "payload_options", "current_gamma_ff", "expected_gamma_ff"),
    [
        (
            bridge_analysis.reinforcement_fatigue_evidence,
            {"reinforcement": True, "concrete": False},
            0.5,
            0.5,
        ),
        (
            bridge_analysis.concrete_fatigue_evidence,
            {"reinforcement": False, "concrete": True},
            "2.0",
            2.0,
        ),
    ],
)
def test_bridge_fatigue_adapters_bind_current_gamma_ff(
    adapter,
    payload_options,
    current_gamma_ff,
    expected_gamma_ff,
):
    current = _bridge_fatigue_input(
        **payload_options,
        gamma_ff=current_gamma_ff,
    )
    stale = _bridge_fatigue_payload(
        **payload_options,
        gamma_ff=1.0,
    )

    rejected = adapter({"fatigue": stale}, current)

    assert rejected.status == bridge.STATUS_INVALID
    assert "gamma_Ff" in rejected.reason
    assert "current fatigue" in rejected.reason

    matching = _bridge_fatigue_payload(
        **payload_options,
        gamma_ff=expected_gamma_ff,
    )
    accepted = adapter({"fatigue": matching}, current)

    assert accepted.status == bridge.STATUS_PASS
    assert accepted.evidence[0]["fatigue_gamma_ff"] == pytest.approx(
        expected_gamma_ff
    )
    assert "STANDARD PASS" in accepted.reason


@pytest.mark.parametrize(
    ("adapter", "payload_options"),
    [
        (
            bridge_analysis.reinforcement_fatigue_evidence,
            {"reinforcement": True, "concrete": False},
        ),
        (
            bridge_analysis.concrete_fatigue_evidence,
            {"reinforcement": False, "concrete": True},
        ),
    ],
)
def test_bridge_fatigue_adapters_bind_current_calculation_basis(
    adapter,
    payload_options,
):
    current_basis = {
        **fatigue_inputs.default_basis(),
        "authority": fatigue_inputs.AUTHORITY_VD,
        "method": fatigue_inputs.METHOD_VD_FLM4,
        "spectrum_source": "VD project basis section 6.8",
        "cycle_count_source": "Traffic register T-04",
    }
    stale_basis = {
        **current_basis,
        "authority": fatigue_inputs.AUTHORITY_USER,
        "method": fatigue_inputs.METHOD_USER_GROUPED,
    }
    current = _bridge_fatigue_input(
        **payload_options,
        fatigue_basis=current_basis,
    )

    rejected = adapter(
        {"fatigue": _bridge_fatigue_payload(
            **payload_options,
            basis=stale_basis,
        )},
        current,
    )
    assert rejected.status == bridge.STATUS_INVALID
    assert "calculated fatigue basis conflicts" in rejected.reason

    accepted = adapter(
        {"fatigue": _bridge_fatigue_payload(
            **payload_options,
            basis=current_basis,
        )},
        current,
    )
    assert accepted.status == bridge.STATUS_PASS
    assert accepted.evidence[0]["fatigue_basis"] == current_basis


@pytest.mark.parametrize(
    ("adapter", "payload_options", "check_id"),
    [
        (
            bridge_analysis.reinforcement_fatigue_evidence,
            {"reinforcement": True, "concrete": False},
            "reinforcement_fatigue",
        ),
        (
            bridge_analysis.concrete_fatigue_evidence,
            {"reinforcement": False, "concrete": True},
            "concrete_fatigue",
        ),
    ],
)
@pytest.mark.parametrize("malformed", ["missing", "boolean", "non_finite"])
def test_bridge_fatigue_adapters_reject_malformed_gamma_ff_evidence(
    adapter,
    payload_options,
    check_id,
    malformed,
):
    current = _bridge_fatigue_input(
        **payload_options,
        gamma_ff=2.0,
        **{
            bridge_inputs.COVERAGE_TABLE_KEY: _coverage(
                section_analysis=bridge.REQUIRED,
                **{check_id: bridge.REQUIRED},
            ),
        },
    )
    payload = _bridge_fatigue_payload(**payload_options, gamma_ff=2.0)
    if malformed == "missing":
        del payload["partial_factors"]["gamma_ff"]
    elif malformed == "boolean":
        payload["partial_factors"]["gamma_ff"] = True
    else:
        payload["partial_factors"]["gamma_ff"] = float("inf")

    evidence = adapter({"fatigue": payload}, current)

    assert evidence.status == bridge.STATUS_INVALID
    assert "gamma_Ff" in evidence.reason

    results = _elastic_results(
        sls.COMBINATION_CHARACTERISTIC,
        sls.COMBINATION_QUASI_PERMANENT,
    )
    results["fatigue"] = payload
    record = bridge_analysis.assess(current, results)
    check = next(
        item for item in record["checks"]
        if item["check_id"] == check_id
    )
    assert record["status"] == bridge.STATUS_INVALID
    assert check["status"] == bridge.STATUS_INVALID
    assert "gamma_Ff" in check["reason"]


@pytest.mark.parametrize(
    ("malformed", "value"),
    [
        ("missing", None),
        ("boolean", True),
        ("non_finite", float("inf")),
        ("non_positive", 0.0),
    ],
)
def test_bridge_fatigue_adapter_rejects_invalid_current_gamma_ff(
    malformed,
    value,
):
    current = _bridge_fatigue_input(gamma_ff=value)
    if malformed == "missing":
        del current["fatigue_gamma_ff"]

    evidence = bridge_analysis.concrete_fatigue_evidence(
        {"fatigue": _bridge_fatigue_payload()},
        current,
    )

    assert evidence.status == bridge.STATUS_INVALID
    assert "gamma_Ff" in evidence.reason


@pytest.mark.parametrize(
    ("adapter", "payload_options", "custom_factors"),
    [
        (
            bridge_analysis.reinforcement_fatigue_evidence,
            {"reinforcement": True, "concrete": False},
            {"gamma_s": 0.5, "gamma_c": 1.50},
        ),
        (
            bridge_analysis.concrete_fatigue_evidence,
            {"reinforcement": False, "concrete": True},
            {"gamma_s": 1.15, "gamma_c": 2.0},
        ),
    ],
)
@pytest.mark.parametrize(
    ("payload_mode", "payload_approval", "reason"),
    [
        (
            fatigue_inputs.FACTOR_MODE_PRESET,
            "",
            "factor mode",
        ),
        (
            fatigue_inputs.FACTOR_MODE_OVERRIDE,
            "DB-STALE-APPROVAL",
            "factor approval",
        ),
    ],
)
def test_bridge_fatigue_adapters_reject_self_consistent_mode_or_approval_drift(
    adapter,
    payload_options,
    custom_factors,
    payload_mode,
    payload_approval,
    reason,
):
    current = _bridge_fatigue_input(
        **payload_options,
        factor_mode=fatigue_inputs.FACTOR_MODE_OVERRIDE,
        factor_approval="DB-CURRENT-APPROVAL",
        **custom_factors,
    )
    stale = _bridge_fatigue_payload(
        **payload_options,
        factor_mode=payload_mode,
        factor_approval=payload_approval,
        **custom_factors,
    )

    evidence = adapter({"fatigue": stale}, current)

    assert evidence.status == bridge.STATUS_INVALID
    assert reason in evidence.reason
    assert "current fatigue factor" in evidence.reason


@pytest.mark.parametrize(
    ("adapter", "payload_options", "custom_factors", "omitted_id"),
    [
        (
            bridge_analysis.reinforcement_fatigue_evidence,
            {"reinforcement": True, "concrete": False},
            {"gamma_s": 0.5, "gamma_c": 1.50},
            "fatigue.gamma_s",
        ),
        (
            bridge_analysis.concrete_fatigue_evidence,
            {"reinforcement": False, "concrete": True},
            {"gamma_s": 1.15, "gamma_c": 2.0},
            "fatigue.gamma_c",
        ),
    ],
)
def test_bridge_fatigue_adapters_require_complete_current_parameter_records(
    adapter,
    payload_options,
    custom_factors,
    omitted_id,
):
    current = _bridge_fatigue_input(
        **payload_options,
        factor_mode=fatigue_inputs.FACTOR_MODE_OVERRIDE,
        factor_approval="DB-CURRENT-FACTOR",
        **custom_factors,
    )
    payload = _bridge_fatigue_payload(
        **payload_options,
        factor_mode=fatigue_inputs.FACTOR_MODE_OVERRIDE,
        factor_approval="DB-CURRENT-FACTOR",
        **custom_factors,
    )
    payload["parameter_conformance"] = [
        record
        for record in payload["parameter_conformance"]
        if record["parameter_id"] != omitted_id
    ]

    evidence = adapter({"fatigue": payload}, current)

    assert evidence.status == bridge.STATUS_INVALID
    assert "parameter records" in evidence.reason
    assert "current fatigue factor" in evidence.reason


@pytest.mark.parametrize(
    ("adapter", "current_options", "stale_options"),
    [
        (
            bridge_analysis.reinforcement_fatigue_evidence,
            {"reinforcement": True, "concrete": False},
            {"reinforcement": False, "concrete": True},
        ),
        (
            bridge_analysis.concrete_fatigue_evidence,
            {"reinforcement": False, "concrete": True},
            {"reinforcement": True, "concrete": False},
        ),
    ],
)
def test_bridge_fatigue_adapters_reject_stale_disabled_family_payloads(
    adapter,
    current_options,
    stale_options,
):
    current = _bridge_fatigue_input(**current_options)
    stale = _bridge_fatigue_payload(**stale_options)

    evidence = adapter({"fatigue": stale}, current)

    assert evidence.status == bridge.STATUS_INVALID
    assert "check selection" in evidence.reason
    assert "current fatigue inputs" in evidence.reason


@pytest.mark.parametrize(
    ("family", "payload_options", "custom_factors", "check_id"),
    [
        (
            "reinforcement",
            {"reinforcement": True, "concrete": False},
            {"gamma_s": 0.5, "gamma_c": 1.50},
            "reinforcement_fatigue",
        ),
        (
            "concrete",
            {"reinforcement": False, "concrete": True},
            {"gamma_s": 1.15, "gamma_c": 2.0},
            "concrete_fatigue",
        ),
    ],
)
def test_raw_bridge_assess_never_passes_stale_standard_fatigue_factors(
    family,
    payload_options,
    custom_factors,
    check_id,
):
    coverage = _coverage(
        section_analysis=bridge.REQUIRED,
        **{check_id: bridge.REQUIRED},
    )
    standard_input = _bridge_fatigue_input(
        **payload_options,
        **{bridge_inputs.COVERAGE_TABLE_KEY: coverage},
    )
    standard_payload = _bridge_fatigue_payload(**payload_options)

    def assess(inp, payload):
        results = _elastic_results(
            sls.COMBINATION_CHARACTERISTIC,
            sls.COMBINATION_QUASI_PERMANENT,
        )
        results["fatigue"] = payload
        record = bridge_analysis.assess(inp, results)
        check = next(
            item for item in record["checks"]
            if item["check_id"] == check_id
        )
        return record, check

    standard_record, standard_check = assess(
        standard_input,
        standard_payload,
    )
    assert standard_record["status"] == bridge.STATUS_PASS
    assert standard_check["status"] == bridge.STATUS_PASS

    current_custom = {
        **standard_input,
        "fatigue_factor_mode": fatigue_inputs.FACTOR_MODE_OVERRIDE,
        "fatigue_factor_approval": "DB-CURRENT-FACTOR",
        "fatigue_gamma_s": custom_factors["gamma_s"],
        "fatigue_gamma_c": custom_factors["gamma_c"],
    }
    stale_record, stale_check = assess(current_custom, standard_payload)
    assert stale_record["status"] == bridge.STATUS_INVALID
    assert stale_check["status"] == bridge.STATUS_INVALID
    assert "current fatigue factor" in stale_check["reason"]

    custom_payload = _bridge_fatigue_payload(
        **payload_options,
        factor_mode=fatigue_inputs.FACTOR_MODE_OVERRIDE,
        factor_approval="DB-CURRENT-FACTOR",
        **custom_factors,
    )
    custom_record, custom_check = assess(current_custom, custom_payload)
    assert custom_record["status"] == bridge.STATUS_REVIEW
    assert custom_check["status"] == bridge.STATUS_REVIEW
    assert custom_check["evidence"][0]["analytical_status"] == (
        bridge.STATUS_PASS
    )


@pytest.mark.parametrize(
    ("payload_options", "check_id"),
    [
        (
            {"reinforcement": True, "concrete": False},
            "reinforcement_fatigue",
        ),
        (
            {"reinforcement": False, "concrete": True},
            "concrete_fatigue",
        ),
    ],
)
def test_raw_bridge_assess_never_passes_stale_gamma_ff(
    payload_options,
    check_id,
):
    coverage = _coverage(
        section_analysis=bridge.REQUIRED,
        **{check_id: bridge.REQUIRED},
    )
    current = _bridge_fatigue_input(
        **payload_options,
        gamma_ff=2.0,
        **{bridge_inputs.COVERAGE_TABLE_KEY: coverage},
    )

    def assess(payload):
        results = _elastic_results(
            sls.COMBINATION_CHARACTERISTIC,
            sls.COMBINATION_QUASI_PERMANENT,
        )
        results["fatigue"] = payload
        record = bridge_analysis.assess(current, results)
        check = next(
            item for item in record["checks"]
            if item["check_id"] == check_id
        )
        return record, check

    stale_record, stale_check = assess(
        _bridge_fatigue_payload(**payload_options, gamma_ff=1.0)
    )
    assert stale_record["status"] == bridge.STATUS_INVALID
    assert stale_check["status"] == bridge.STATUS_INVALID
    assert "gamma_Ff" in stale_check["reason"]

    matching_record, matching_check = assess(
        _bridge_fatigue_payload(**payload_options, gamma_ff=2.0)
    )
    assert matching_record["status"] == bridge.STATUS_PASS
    assert matching_check["status"] == bridge.STATUS_PASS
    assert matching_check["evidence"][0]["fatigue_gamma_ff"] == pytest.approx(
        2.0
    )


@pytest.mark.parametrize(
    ("input_c", "result_c"),
    [
        (100.0, 14.0),
        (14.0, 100.0),
    ],
)
def test_bridge_concrete_fatigue_requires_exact_input_result_correlation(
    input_c,
    result_c,
):
    inp = _base_input(
        fatigue_on=True,
        fatigue_edition="DS/EN 1992-2:2005 + AC:2008",
        fatigue_check_concrete=True,
        fatigue_concrete_method="Explicit Palmgren-Miner spectrum",
        fatigue_concrete_miner_basis="EN 1992-2 bridge methodology",
        fatigue_concrete_c=input_c,
    )
    payload = _bridge_miner_payload(coefficient=result_c)

    evidence = bridge_analysis.concrete_fatigue_evidence(
        {"fatigue": payload},
        inp,
    )

    assert evidence.status == bridge.STATUS_INVALID
    assert "current and calculated concrete Miner coefficients conflict" in (
        evidence.reason
    )


def test_bridge_concrete_fatigue_correlation_accepts_equal_integer_real_values():
    inp = _bridge_fatigue_input(coefficient=14.0)
    payload = _bridge_fatigue_payload(coefficient=14)

    evidence = bridge_analysis.concrete_fatigue_evidence(
        {"fatigue": payload},
        inp,
    )

    assert evidence.status == bridge.STATUS_PASS
    assert evidence.evidence[0]["miner_coefficient_c"] == 14


def test_bridge_concrete_fatigue_c100_is_analytical_review_not_standard_pass():
    inp = _base_input(
        fatigue_on=True,
        fatigue_edition=fatigue_inputs.EC2_2_2005_AC,
        fatigue_check_concrete=True,
        fatigue_concrete_method=fatigue_analysis.CONCRETE_MINER,
        fatigue_concrete_miner_basis=(
            fatigue_inputs.MINER_BASIS_BRIDGE_STANDARD
        ),
        fatigue_concrete_c=100.0,
    )
    evidence = bridge_analysis.concrete_fatigue_evidence(
        {"fatigue": _bridge_miner_payload(coefficient=100.0)},
        inp,
    )

    assert evidence.status == bridge.STATUS_REVIEW
    assert evidence.evidence[0]["analytical_status"] == bridge.STATUS_PASS
    assert evidence.evidence[0]["miner_coefficient_c"] == 100.0
    assert evidence.evidence[0]["methodology"] == bridge.EN1992_2_BASE
    assert evidence.evidence[0]["fatigue_edition"] == (
        fatigue_inputs.EC2_2_2005_AC
    )
    assert evidence.evidence[0]["fatigue_factor_mode"] == (
        fatigue_inputs.FACTOR_MODE_PRESET
    )
    assert evidence.evidence[0]["fatigue_factor_approval"] == ""
    assert evidence.evidence[0]["concrete_miner_basis"] == (
        fatigue_inputs.MINER_BASIS_BRIDGE_STANDARD
    )
    assert evidence.evidence[0]["concrete_miner_source"] == ""
    assert [
        record["parameter_id"]
        for record in evidence.evidence[0][
            "fatigue_parameter_conformance"
        ]
    ] == ["fatigue.gamma_c", "concrete_fatigue.miner_c"]
    assert (
        evidence.evidence[0]["parameter_conformance"]["state"]
        == conformance.STATE_REVIEW
    )


def test_bridge_concrete_fatigue_sourced_c100_remains_calculated_custom_review():
    source = "DB-SN-C100 / checker approval"
    inp = _bridge_fatigue_input(
        coefficient=100.0,
        concrete_method=fatigue_analysis.CONCRETE_PROJECT_MINER,
        miner_basis=fatigue_inputs.MINER_BASIS_PROJECT_SN_RELATION,
        miner_source=source,
    )
    payload = _bridge_fatigue_payload(
        coefficient=100.0,
        concrete_method=fatigue_analysis.CONCRETE_PROJECT_MINER,
        miner_basis=fatigue_inputs.MINER_BASIS_PROJECT_SN_RELATION,
        miner_source=source,
    )

    evidence = bridge_analysis.concrete_fatigue_evidence(
        {"fatigue": payload},
        inp,
    )

    assert evidence.status == bridge.STATUS_REVIEW
    assert evidence.evidence[0]["analytical_status"] == bridge.STATUS_PASS
    assert evidence.evidence[0]["miner_coefficient_c"] == 100.0
    assert evidence.evidence[0]["concrete_method"] == (
        fatigue_analysis.CONCRETE_PROJECT_MINER
    )
    assert evidence.evidence[0]["concrete_miner_source"] == source
    assert evidence.evidence[0]["parameter_conformance"]["state"] == (
        conformance.STATE_APPROVED_CUSTOM
    )


def test_bridge_concrete_fatigue_rejects_self_consistent_stale_custom_source():
    current_source = "DB-SN-C100 / current checker approval"
    stale_source = "DB-SN-C100 / superseded approval"
    inp = _bridge_fatigue_input(
        coefficient=100.0,
        concrete_method=fatigue_analysis.CONCRETE_PROJECT_MINER,
        miner_basis=fatigue_inputs.MINER_BASIS_PROJECT_SN_RELATION,
        miner_source=current_source,
    )
    stale = _bridge_fatigue_payload(
        coefficient=100.0,
        concrete_method=fatigue_analysis.CONCRETE_PROJECT_MINER,
        miner_basis=fatigue_inputs.MINER_BASIS_PROJECT_SN_RELATION,
        miner_source=stale_source,
    )

    evidence = bridge_analysis.concrete_fatigue_evidence(
        {"fatigue": stale},
        inp,
    )

    assert evidence.status == bridge.STATUS_INVALID
    assert "Miner source/approval" in evidence.reason
    assert "current fatigue inputs" in evidence.reason


def test_bridge_fatigue_missing_override_approval_is_review_not_replaced():
    inp = _bridge_fatigue_input(
        factor_mode=fatigue_inputs.FACTOR_MODE_OVERRIDE,
        factor_approval="",
        gamma_c=2.0,
    )
    payload = _bridge_fatigue_payload(
        factor_mode=fatigue_inputs.FACTOR_MODE_OVERRIDE,
        factor_approval="",
        gamma_c=2.0,
    )

    evidence = bridge_analysis.concrete_fatigue_evidence(
        {"fatigue": payload},
        inp,
    )

    assert evidence.status == bridge.STATUS_REVIEW
    gamma_record = next(
        record
        for record in evidence.evidence[0][
            "fatigue_parameter_conformance"
        ]
        if record["parameter_id"] == "fatigue.gamma_c"
    )
    assert gamma_record["actual_value"] == 2.0
    assert gamma_record["state"] == conformance.STATE_REVIEW


def test_bridge_concrete_fatigue_rejects_stale_miner_basis_evidence():
    inp = _base_input(
        fatigue_on=True,
        fatigue_edition=fatigue_inputs.EC2_2_2005_AC,
        fatigue_check_concrete=True,
        fatigue_concrete_method=fatigue_analysis.CONCRETE_MINER,
        fatigue_concrete_miner_basis=(
            fatigue_inputs.MINER_BASIS_BRIDGE_STANDARD
        ),
        fatigue_concrete_c=14.0,
    )
    payload = _bridge_miner_payload()
    payload["concrete_miner_basis"] = (
        fatigue_inputs.MINER_BASIS_PROJECT_ADOPTION
    )

    evidence = bridge_analysis.concrete_fatigue_evidence(
        {"fatigue": payload},
        inp,
    )

    assert evidence.status == bridge.STATUS_INVALID
    assert "conformance" in evidence.reason


def test_malformed_headless_bridge_boundaries_return_invalid_record():
    malformed_inputs = bridge_analysis.assess(True, {})
    malformed_results = bridge_analysis.assess(_base_input(), True)

    assert malformed_inputs["status"] == bridge.STATUS_INVALID
    assert malformed_results["status"] == bridge.STATUS_INVALID
    assert any(
        "not structured evidence" in error
        for error in malformed_results["configuration_errors"]
    )


def test_unused_incompatible_material_catalogue_entry_does_not_block():
    inp = _base_input(
        mild_material_catalog={
            "items": [{
                "id": "UNUSED-2023",
                "preset": "DS/EN 1992-1-1:2023",
            }],
        },
    )

    evidence = bridge_analysis.section_analysis_evidence(
        inp,
        _elastic_results(
            sls.COMBINATION_CHARACTERISTIC,
            sls.COMBINATION_QUASI_PERMANENT,
        ),
    )

    assert evidence.status == bridge.STATUS_PASS


def test_assigned_incompatible_material_or_nonconverged_solver_blocks():
    results = _elastic_results(
        sls.COMBINATION_CHARACTERISTIC,
        sls.COMBINATION_QUASI_PERMANENT,
    )
    incompatible = _base_input(
        bars=[(0.0, 0.0, 500.0)],
        bar_elements=[{
            "id": "R1",
            "material_id": "M23",
        }],
        mild_material_catalog={
            "items": [{
                "id": "M23",
                "preset": "DS/EN 1992-1-1:2023",
            }],
        },
    )

    material_evidence = bridge_analysis.section_analysis_evidence(
        incompatible,
        results,
    )
    results["elastic_cases"][0]["results"]["elastic"]["converged"] = False
    solver_evidence = bridge_analysis.section_analysis_evidence(
        _base_input(),
        results,
    )

    assert material_evidence.status == bridge.STATUS_NOT_ASSESSED
    assert "not in the inherited base 2005 family" in material_evidence.reason
    assert solver_evidence.status == bridge.STATUS_INVALID
    assert "did not converge" in solver_evidence.reason


def test_malformed_coverage_rows_reach_overall_invalid_status():
    inp = _base_input()
    inp[bridge_inputs.COVERAGE_TABLE_KEY] = [
        {
            "check_id": "section_analysis",
            "applicability": bridge.REQUIRED,
            "source": "DB-A",
            "notes": "",
        },
        {
            "check_id": "section_analysis",
            "applicability": bridge.NOT_APPLICABLE,
            "source": "DB-B",
            "notes": "",
        },
    ]

    result = bridge_analysis.assess(
        inp,
        _elastic_results(
            sls.COMBINATION_CHARACTERISTIC,
            sls.COMBINATION_QUASI_PERMANENT,
        ),
    )

    assert result["status"] == bridge.STATUS_INVALID
    assert any(
        "duplicate check_id" in error
        for error in result["configuration_errors"]
    )
