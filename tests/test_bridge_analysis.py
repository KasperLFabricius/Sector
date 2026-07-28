from __future__ import annotations

import pathlib
from types import SimpleNamespace
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import bridge_analysis  # noqa: E402
import bridge_inputs  # noqa: E402
from sector import bridge, sls  # noqa: E402


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
    }
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
    source = "DS/EN 1992-2:2005 Table 7.101N"
    criterion = {
        "criterion_id": "bridge-standard-durability",
        "kind": sls.CRITERION_DURABILITY,
        "status": "OK",
        "value": 0.22,
        "limit_mm": 0.30,
        "util": 0.22 / 0.30,
        "matched_responses": ["QP"],
        "criterion_source": source,
        "reason": "Exact QP response",
        "required_combination": sls.COMBINATION_QUASI_PERMANENT,
        "response_duration": "long",
        "response_provenance": "map-v1",
        "solver_provenance": {"solve": "v1", "converged": True},
    }
    unmatched = {
        **criterion,
        "status": "NOT ASSESSED",
        "value": None,
        "util": None,
        "matched_responses": [],
        "reason": "Required combination is in another case",
    }
    results = {
        "elastic_cases": [
            {
                "results": {
                    "elastic": {
                        "crack_assessment": {"criteria": [criterion]},
                    },
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
    assert evidence.source == source
    assert evidence.evidence[0]["matched_responses"] == ["QP"]
    assert evidence.evidence[0]["solver_provenance"]["solve"] == "v1"


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

    assert evidence.status == bridge.STATUS_INVALID


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


@pytest.mark.parametrize(
    ("payload_change", "reason"),
    [
        (
            {"edition": "DS/EN 1992-1-1:2023"},
            "calculated fatigue edition",
        ),
        (
            {
                "concrete_miner_basis": (
                    "Approved project-basis adoption"
                ),
            },
            "Miner applicability",
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
    )
    payload = {
        "edition": "DS/EN 1992-2:2005 + AC:2008",
        "checks": {"concrete": True},
        "concrete_method": "Explicit Palmgren-Miner spectrum",
        "concrete_miner_basis": "EN 1992-2 bridge methodology",
        "calculation_references": {
            "concrete": "EN 1992-2 corrected Expression (6.106)",
        },
        "spectra": [],
    }
    payload.update(payload_change)

    evidence = bridge_analysis.concrete_fatigue_evidence(
        {"fatigue": payload},
        inp,
    )

    assert evidence.status == bridge.STATUS_INVALID
    assert reason in evidence.reason


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
