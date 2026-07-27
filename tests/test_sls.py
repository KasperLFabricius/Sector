"""Tests for headless SLS assessment and evidence construction."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sector import sls


def test_upper_limit_assessment_has_explicit_non_pass_states():
    assert sls.upper_limit_assessment(12.0, 18.0)["status"] == "OK"
    assert sls.upper_limit_assessment(20.0, 18.0)["status"] == "EXCEEDED"
    assert sls.upper_limit_assessment(12.0, 0.0)["status"] == "NOT ASSESSED"
    assert sls.upper_limit_assessment(None, 18.0, applicable=False)["status"] == \
        "NOT APPLICABLE"
    assert sls.upper_limit_assessment(12.0, 18.0, valid=False)["status"] == "INVALID"
    assert sls.upper_limit_assessment(float("nan"), 18.0)["status"] == "INVALID"


@pytest.mark.parametrize("value", [True, np.bool_(True)])
@pytest.mark.parametrize("position", ["value", "limit"])
def test_upper_limit_assessment_rejects_boolean_numerics(value, position):
    args = [12.0, 18.0]
    args[0 if position == "value" else 1] = value

    with pytest.raises(ValueError, match="Boolean"):
        sls.upper_limit_assessment(*args)


@pytest.mark.parametrize("value", [True, np.bool_(True)])
@pytest.mark.parametrize(
    "key",
    [
        "concrete_limit_pct",
        "reinforcement_limit_pct",
        "prestress_limit_pct",
    ],
)
def test_stress_assessments_reject_boolean_limits_before_coercion(key, value):
    kwargs = {
        "n_bars": 1,
        "max_concrete_compression": 12.0,
        "fck": 30.0,
        "fyk": 500.0,
        "fpk": 1800.0,
        "concrete_limit_pct": 60.0,
        "reinforcement_limit_pct": 80.0,
        "prestress_limit_pct": 75.0,
        "valid": True,
    }
    kwargs[key] = value

    with pytest.raises(ValueError, match=key):
        sls.stress_assessments([350.0, 420.0], **kwargs)


@pytest.mark.parametrize(
    "total_stress",
    [
        pytest.param(
            np.asarray([True, 420.0], dtype=object),
            id="numpy-object-array",
        ),
        pytest.param(
            pd.Series([True, 420.0], dtype=object),
            id="pandas-object-series",
        ),
        pytest.param(
            np.asarray(True, dtype=object),
            id="numpy-zero-dimensional-object-array",
        ),
        pytest.param(
            iter([True, 420.0]),
            id="one-shot-iterator",
        ),
    ],
)
def test_stress_assessments_reject_boolean_array_like_contents(total_stress):
    with pytest.raises(ValueError, match="total_stress"):
        sls.stress_assessments(
            total_stress,
            n_bars=1,
            max_concrete_compression=12.0,
            fck=30.0,
            fyk=500.0,
            fpk=1800.0,
            concrete_limit_pct=60.0,
            reinforcement_limit_pct=80.0,
            prestress_limit_pct=75.0,
            valid=True,
        )


@pytest.mark.parametrize(
    "total_stress",
    [
        pytest.param(
            np.asarray([350.0, 420.0], dtype=object),
            id="numpy-object-array",
        ),
        pytest.param(
            pd.Series([350.0, 420.0], dtype=object),
            id="pandas-object-series",
        ),
        pytest.param(
            iter([350.0, 420.0]),
            id="one-shot-iterator",
        ),
    ],
)
def test_stress_assessments_accept_numeric_array_like_contents(total_stress):
    checks = sls.stress_assessments(
        total_stress,
        n_bars=1,
        max_concrete_compression=12.0,
        fck=30.0,
        fyk=500.0,
        fpk=1800.0,
        concrete_limit_pct=60.0,
        reinforcement_limit_pct=80.0,
        prestress_limit_pct=75.0,
        valid=True,
    )

    assert checks["reinforcement"]["value"] == pytest.approx(350.0)
    assert checks["prestress"]["value"] == pytest.approx(420.0)


def test_stress_assessments_separate_bars_and_tendons():
    checks = sls.stress_assessments(
        [350.0, 420.0],
        n_bars=1,
        max_concrete_compression=20.0,
        fck=30.0,
        fyk=500.0,
        fpk=1800.0,
        concrete_limit_pct=60.0,
        reinforcement_limit_pct=80.0,
        prestress_limit_pct=75.0,
        valid=True,
    )
    assert checks["concrete"]["limit"] == pytest.approx(18.0)
    assert checks["concrete"]["status"] == "EXCEEDED"
    assert checks["reinforcement"]["governing"] == "bar 1"
    assert checks["reinforcement"]["status"] == "OK"
    assert checks["prestress"]["governing"] == "tendon 1"
    assert checks["prestress"]["limit"] == pytest.approx(1350.0)


def test_stress_assessments_use_stable_element_ids_when_supplied():
    checks = sls.stress_assessments(
        [350.0, 420.0],
        n_bars=1,
        max_concrete_compression=12.0,
        fck=30.0,
        fyk=500.0,
        fpk=1800.0,
        concrete_limit_pct=60.0,
        reinforcement_limit_pct=80.0,
        prestress_limit_pct=75.0,
        valid=True,
        bar_ids=["R7"],
        tendon_ids=["P3"],
    )

    assert checks["reinforcement"]["governing"] == "R7"
    assert checks["prestress"]["governing"] == "P3"


def test_stress_assessments_govern_by_per_element_utilisation():
    # Bar R2 has the lower stress but also the much lower assigned strength, so it
    # governs by utilisation. A raw maximum-stress comparison would select R1.
    checks = sls.stress_assessments(
        [350.0, 260.0],
        n_bars=2,
        max_concrete_compression=12.0,
        fck=30.0,
        fyk=[600.0, 300.0],
        fpk=None,
        concrete_limit_pct=60.0,
        reinforcement_limit_pct=80.0,
        prestress_limit_pct=75.0,
        valid=True,
        bar_ids=["R1", "R2"],
    )

    assert checks["reinforcement"]["governing"] == "R2"
    assert checks["reinforcement"]["value"] == pytest.approx(260.0)
    assert checks["reinforcement"]["limit"] == pytest.approx(240.0)
    assert checks["reinforcement"]["status"] == "EXCEEDED"


def test_element_rows_are_typed_and_include_geometry_strain():
    rows = sls.element_rows(
        [(0.1, -0.2, 314.0)],
        [(-0.1, 0.2, 150.0)],
        total=[200.0, 975.0],
        long=[150.0, 900.0],
        dif=[50.0, 75.0],
        rst1=[40.0, 60.0],
        es_mpa=200_000.0,
        ep_mpa=195_000.0,
    )
    assert [row["element_id"] for row in rows] == ["bar 1", "tendon 1"]
    assert rows[0]["x_mm"] == pytest.approx(100.0)
    assert rows[0]["area_mm2"] == pytest.approx(314.0)
    assert rows[0]["strain_permille"] == pytest.approx(1.0)
    assert rows[1]["strain_permille"] == pytest.approx(5.0)


def test_element_rows_use_stable_element_ids_when_supplied():
    rows = sls.element_rows(
        [(0.1, -0.2, 314.0)],
        [(-0.1, 0.2, 150.0)],
        total=[200.0, 975.0],
        long=[150.0, 900.0],
        dif=[50.0, 75.0],
        rst1=[40.0, 60.0],
        es_mpa=200_000.0,
        ep_mpa=195_000.0,
        bar_ids=["R7"],
        tendon_ids=["P3"],
    )

    assert [row["element_id"] for row in rows] == ["R7", "P3"]


def test_element_rows_report_material_identity_and_per_element_modulus():
    rows = sls.element_rows(
        [(0.1, -0.2, 314.0), (0.0, -0.2, 314.0)],
        [],
        total=[200.0, 200.0], long=[150.0, 150.0],
        dif=[50.0, 50.0], rst1=[0.0, 0.0],
        es_mpa=[200_000.0, 100_000.0], ep_mpa=None,
        bar_ids=["R1", "R2"],
        bar_material_ids=["M1", "M2"],
        bar_material_names=["B500", "Legacy steel"],
    )

    assert rows[0]["material_id"] == "M1"
    assert rows[1]["material_name"] == "Legacy steel"
    assert rows[0]["strain_permille"] == pytest.approx(1.0)
    assert rows[1]["strain_permille"] == pytest.approx(2.0)


def test_concrete_corner_rows_use_public_one_based_points():
    rows = sls.concrete_corner_rows(
        [(-0.1, -0.2), (0.1, -0.2), (0.1, 0.2), (-0.1, 0.2)],
        [],
        stress_plane=(-10_000.0, 0.0, 60_000.0),
        ec_mpa=30_000.0,
    )
    assert [row["point_no"] for row in rows] == [1, 2, 3, 4]
    assert rows[0]["stress_mpa"] < 0.0
    assert rows[2]["stress_mpa"] == 0.0
    assert rows[2]["strain_permille"] > 0.0


def _standard_inputs(**overrides):
    values = {
        "sls_criterion_mode": sls.CRITERION_MODE_STANDARD,
        "sls_edition": "2004",
        "sls_code": "EN 1992-1-1:2005",
        "sls_member": "Beam",
        "sls_dk_na": False,
        "sls_prestress_class": sls.PRESTRESS_REINFORCED_UNBONDED,
        "sls_protection_class": sls.PROTECTION_LEVEL_1_OR_PRETENSIONED,
        "sls_exposure_class": sls.EXPOSURE_XC2_XC4,
        "sls_exposure_context": "XC3 / durability",
        "sls_check_appearance": False,
        "sls_check_durability": True,
        "sls_wk_limit": 0.30,
        "sls_decompression_applicability": sls.DECOMPRESSION_NOT_REQUIRED,
    }
    values.update(overrides)
    return values


def test_ordinary_2004_crack_verdict_uses_qp_not_larger_total_response():
    criteria = sls.crack_criteria_from_inputs(_standard_inputs())
    result = sls.crack_assessment(
        {
            "Long-term": {"wk": 0.22, "element_id": "bar 2"},
            "Total": {"wk": 0.31, "element_id": "tendon 1"},
        },
        valid=True,
        criteria=criteria,
        response_contexts={
            "Long-term": {
                "combination": sls.COMBINATION_QUASI_PERMANENT,
                "duration": "sustained",
                "response_id": "long",
                "provenance": "explicit long_combination field",
            },
            "Total": {
                "combination": sls.COMBINATION_CHARACTERISTIC,
                "duration": "instantaneous total",
                "response_id": "total",
                "provenance": "explicit total_combination field",
            },
        },
    )
    assert result["status"] == "OK"
    assert result["verdict"] == "PASS"
    assert result["case"] == "Long-term"
    assert result["value"] == pytest.approx(0.22)
    assert result["required_combination"] == sls.COMBINATION_QUASI_PERMANENT
    assert result["informational_responses"] == ["Total"]


def test_unrelated_not_assessed_response_cannot_block_qp_criterion():
    result = sls.crack_assessment(
        {
            "Long-term": {"wk": 0.18, "element_id": "bar 2"},
            "Total": None,
        },
        valid=True,
        criteria=sls.crack_criteria_from_inputs(_standard_inputs()),
        response_contexts={
            "Long-term": {
                "combination": sls.COMBINATION_QUASI_PERMANENT,
                "response_id": "long",
            },
            "Total": {
                "combination": sls.COMBINATION_FREQUENT,
                "response_id": "total",
            },
        },
        dispositions={
            "Long-term": {
                "status": "CALCULATED",
                "reason": "Crack width calculated.",
            },
            "Total": {
                "status": "NOT ASSESSED",
                "reason": "The validated scope does not cover this strain state.",
            },
        },
    )

    assert result["status"] == "OK"
    assert result["value"] == pytest.approx(0.18)
    assert result["informational_responses"] == ["Total"]


def test_bonded_prestress_routes_width_to_frequent_and_decompression_to_qp():
    criteria = sls.crack_criteria_from_inputs(_standard_inputs(
        sls_prestress_class=sls.PRESTRESS_BONDED,
        sls_decompression_applicability=sls.DECOMPRESSION_REQUIRED,
    ))
    result = sls.crack_assessment(
        {
            "QP": {
                "wk": 0.18,
                "element_id": "bar 2",
                "decompression": {
                    "status": "OK",
                    "reason": "Concrete remains in compression at tendon level.",
                    "solver_provenance": "synthetic independent regression",
                },
            },
            "Frequent": {"wk": 0.22, "element_id": "tendon 1"},
        },
        valid=True,
        criteria=criteria,
        response_contexts={
            "QP": {
                "combination": sls.COMBINATION_QUASI_PERMANENT,
                "response_id": "qp",
            },
            "Frequent": {
                "combination": sls.COMBINATION_FREQUENT,
                "response_id": "frequent",
            },
        },
    )

    assert result["status"] == "OK"
    assert result["value"] == pytest.approx(0.22)
    assert [
        item["required_combination"] for item in result["criteria"]
    ] == [
        sls.COMBINATION_FREQUENT,
        sls.COMBINATION_QUASI_PERMANENT,
    ]
    assert result["criteria"][1]["kind"] == sls.CRITERION_DECOMPRESSION
    assert result["criteria"][1]["status"] == "OK"


def test_2023_appearance_and_durability_are_separate_qp_criteria():
    criteria = sls.crack_criteria_from_inputs(_standard_inputs(
        sls_edition="2023",
        sls_code="EN 1992-1-1:2023",
        sls_check_appearance=True,
        sls_appearance_limit=0.25,
        sls_wk_limit=0.30,
    ))
    result = sls.crack_assessment(
        {"QP": {"wk": 0.26, "element_id": "bar 2"}},
        valid=True,
        criteria=criteria,
        response_contexts={
            "QP": {
                "combination": sls.COMBINATION_QUASI_PERMANENT,
                "response_id": "qp",
            }
        },
    )

    assert result["status"] == "EXCEEDED"
    assert [item["kind"] for item in result["criteria"]] == [
        sls.CRITERION_APPEARANCE,
        sls.CRITERION_DURABILITY,
    ]
    assert [item["status"] for item in result["criteria"]] == [
        "EXCEEDED",
        "OK",
    ]
    assert all(
        item["required_combination"] == sls.COMBINATION_QUASI_PERMANENT
        for item in result["criteria"]
    )
    assert "Table 9.1" in result["criteria"][0]["criterion_source"]
    assert "Table 9.2" in result["criteria"][1]["criterion_source"]


def test_2023_bonded_appearance_qp_is_separate_from_frequent_durability():
    criteria = sls.crack_criteria_from_inputs(_standard_inputs(
        sls_edition="2023",
        sls_code="EN 1992-1-1:2023",
        sls_prestress_class=sls.PRESTRESS_BONDED,
        sls_check_appearance=True,
        sls_appearance_limit=0.25,
        sls_decompression_applicability=sls.DECOMPRESSION_REQUIRED,
    ))
    result = sls.crack_assessment(
        {
            "QP": {
                "wk": 0.20,
                "element_id": "tendon 1",
                "decompression": {"status": "OK"},
            },
            "Frequent": {"wk": 0.22, "element_id": "tendon 1"},
        },
        valid=True,
        criteria=criteria,
        response_contexts={
            "QP": {
                "combination": sls.COMBINATION_QUASI_PERMANENT,
                "response_id": "qp",
            },
            "Frequent": {
                "combination": sls.COMBINATION_FREQUENT,
                "response_id": "frequent",
            },
        },
    )

    assert result["status"] == "OK"
    assert [
        (item["kind"], item["required_combination"])
        for item in result["criteria"]
    ] == [
        (
            sls.CRITERION_APPEARANCE,
            sls.COMBINATION_QUASI_PERMANENT,
        ),
        (sls.CRITERION_DURABILITY, sls.COMBINATION_FREQUENT),
        (
            sls.CRITERION_DECOMPRESSION,
            sls.COMBINATION_QUASI_PERMANENT,
        ),
    ]


def test_2023_bonded_protection_levels_2_3_use_qp_not_frequent_width():
    criteria = sls.crack_criteria_from_inputs(_standard_inputs(
        sls_edition="2023",
        sls_code="EN 1992-1-1:2023",
        sls_prestress_class=sls.PRESTRESS_BONDED,
        sls_protection_class=sls.PROTECTION_LEVEL_2_OR_3,
        sls_exposure_class=sls.EXPOSURE_XC2_XC4,
    ))
    result = sls.crack_assessment(
        {
            "QP": {"wk": 0.31, "element_id": "tendon 1"},
            "Frequent": {"wk": 0.22, "element_id": "tendon 1"},
        },
        valid=True,
        criteria=criteria,
        response_contexts={
            "QP": {
                "combination": sls.COMBINATION_QUASI_PERMANENT,
                "response_id": "qp",
            },
            "Frequent": {
                "combination": sls.COMBINATION_FREQUENT,
                "response_id": "frequent",
            },
        },
    )

    assert result["status"] == "EXCEEDED"
    assert result["verdict"] == "FAIL"
    assert result["case"] == "QP"
    assert result["value"] == pytest.approx(0.31)
    assert result["required_combination"] == sls.COMBINATION_QUASI_PERMANENT
    assert result["informational_responses"] == ["Frequent"]


@pytest.mark.parametrize(
    ("exposure_class", "expected"),
    [
        (
            sls.EXPOSURE_X0_XC1,
            [(sls.CRITERION_DURABILITY, sls.COMBINATION_FREQUENT)],
        ),
        (
            sls.EXPOSURE_XC2_XC4,
            [
                (sls.CRITERION_DURABILITY, sls.COMBINATION_FREQUENT),
                (
                    sls.CRITERION_DECOMPRESSION,
                    sls.COMBINATION_QUASI_PERMANENT,
                ),
            ],
        ),
        (
            sls.EXPOSURE_XD_XS,
            [(sls.CRITERION_DECOMPRESSION, sls.COMBINATION_FREQUENT)],
        ),
        (
            sls.EXPOSURE_XF,
            [(sls.CRITERION_DECOMPRESSION, sls.COMBINATION_FREQUENT)],
        ),
    ],
)
def test_2023_protection_level_1_exposure_matrix_routes_explicitly(
    exposure_class,
    expected,
):
    criteria = sls.crack_criteria_from_inputs(_standard_inputs(
        sls_edition="2023",
        sls_code="EN 1992-1-1:2023",
        sls_prestress_class=sls.PRESTRESS_BONDED,
        sls_protection_class=sls.PROTECTION_LEVEL_1_OR_PRETENSIONED,
        sls_exposure_class=exposure_class,
    ))

    assert [
        (item["kind"], item["required_combination"])
        for item in criteria
    ] == expected


@pytest.mark.parametrize(
    ("missing_key", "missing_value"),
    [
        ("sls_exposure_class", sls.EXPOSURE_NOT_ESTABLISHED),
        ("sls_protection_class", sls.PROTECTION_NOT_ESTABLISHED),
    ],
)
def test_2023_bonded_missing_structured_route_is_not_assessed(
    missing_key,
    missing_value,
):
    inputs = _standard_inputs(
        sls_edition="2023",
        sls_code="EN 1992-1-1:2023",
        sls_prestress_class=sls.PRESTRESS_BONDED,
    )
    inputs[missing_key] = missing_value
    result = sls.crack_assessment(
        {"Frequent": {"wk": 0.20, "element_id": "tendon 1"}},
        valid=True,
        criteria=sls.crack_criteria_from_inputs(inputs),
        response_contexts={
            "Frequent": {
                "combination": sls.COMBINATION_FREQUENT,
                "response_id": "frequent",
            },
        },
    )

    assert result["status"] == "NOT ASSESSED"
    assert result["verdict"] == "REVIEW"
    assert "Select the" in result["reason"]


@pytest.mark.parametrize(
    "key",
    [
        "sls_wk_limit",
        "sls_appearance_limit",
        "sls_project_characteristic_limit",
        "sls_project_frequent_limit",
        "sls_project_quasi_permanent_limit",
        "sls_tendon_xi",
    ],
)
@pytest.mark.parametrize("value", [True, np.bool_(True)])
def test_boolean_crack_numeric_is_rejected_before_favourable_coercion(
    key,
    value,
):
    inputs = _standard_inputs()
    inputs[key] = value
    result = sls.crack_assessment(
        {"QP": {"wk": 0.31, "element_id": "bar 1"}},
        valid=True,
        criteria=sls.crack_criteria_from_inputs(inputs),
        response_contexts={
            "QP": {
                "combination": sls.COMBINATION_QUASI_PERMANENT,
                "response_id": "qp",
            },
        },
    )

    assert result["status"] == "NOT ASSESSED"
    assert result["verdict"] == "REVIEW"
    assert key in result["reason"]


def test_missing_required_combination_is_review_with_response_provenance():
    result = sls.crack_assessment(
        {"Long-term": {"wk": 0.18, "element_id": "bar 2"}},
        valid=True,
        criteria=sls.crack_criteria_from_inputs(_standard_inputs()),
        response_contexts={
            "Long-term": {
                "combination": sls.COMBINATION_UNSPECIFIED,
                "duration": "sustained",
                "response_id": "long",
                "provenance": "legacy project: no combination field",
                "solver_provenance": {"solver": "cracked-section"},
            }
        },
    )

    assert result["status"] == "NOT ASSESSED"
    assert result["verdict"] == "REVIEW"
    assert "No calculated response" in result["reason"]
    assert result["response_contexts"]["Long-term"]["provenance"].startswith(
        "legacy project"
    )
    assert result["response_contexts"]["Long-term"]["solver_provenance"] == {
        "solver": "cracked-section"
    }
    assert result["solver_provenance"] == [{
        "response": "Long-term",
        "solver": {"solver": "cracked-section"},
    }]


def test_duplicate_independent_mapping_for_required_combination_is_review():
    result = sls.crack_assessment(
        {
            "Long-term": {"wk": 0.18, "element_id": "bar 1"},
            "Total": {"wk": 0.22, "element_id": "bar 1"},
        },
        valid=True,
        criteria=sls.crack_criteria_from_inputs(_standard_inputs()),
        response_contexts={
            "Long-term": {
                "combination": sls.COMBINATION_QUASI_PERMANENT,
                "response_id": "long",
                "provenance": "long response field",
                "solver_provenance": {"state": "long"},
            },
            "Total": {
                "combination": sls.COMBINATION_QUASI_PERMANENT,
                "response_id": "total",
                "provenance": "total response field",
                "solver_provenance": {"state": "total"},
            },
        },
    )

    assert result["status"] == "NOT ASSESSED"
    assert "ambiguous" in result["reason"]
    assert result["criteria"][0]["matched_responses"] == [
        "Long-term",
        "Total",
    ]
    assert result["response_provenance"] == [
        {
            "response": "Long-term",
            "combination": sls.COMBINATION_QUASI_PERMANENT,
            "duration": None,
            "mapping": "long response field",
        },
        {
            "response": "Total",
            "combination": sls.COMBINATION_QUASI_PERMANENT,
            "duration": None,
            "mapping": "total response field",
        },
    ]
    assert result["solver_provenance"] == [
        {"response": "Long-term", "solver": {"state": "long"}},
        {"response": "Total", "solver": {"state": "total"}},
    ]


def test_duplicate_required_combination_across_elastic_cases_is_review():
    result = sls.crack_assessment(
        {"Long-term": {"wk": 0.18, "element_id": "bar 1"}},
        valid=True,
        criteria=sls.crack_criteria_from_inputs(_standard_inputs()),
        response_contexts={
            "Long-term": {
                "combination": sls.COMBINATION_QUASI_PERMANENT,
                "response_id": "long",
                "provenance": "EL-QP-A long response",
            },
        },
        response_mapping_scope=[
            {
                "combination": sls.COMBINATION_QUASI_PERMANENT,
                "response": "EL-QP-A / long",
                "response_id": "EL-QP-A:long",
                "elastic_case": "EL-QP-A",
                "state": "long",
                "provenance": "EL-QP-A long_combination table field",
            },
            {
                "combination": sls.COMBINATION_QUASI_PERMANENT,
                "response": "EL-QP-B / long",
                "response_id": "EL-QP-B:long",
                "elastic_case": "EL-QP-B",
                "state": "long",
                "provenance": "EL-QP-B long_combination table field",
            },
        ],
    )

    assert result["status"] == "NOT ASSESSED"
    assert result["verdict"] == "REVIEW"
    assert "across checked Elastic cases" in result["reason"]
    assert result["criteria"][0]["matched_responses"] == [
        "EL-QP-A / long",
        "EL-QP-B / long",
    ]
    assert [
        item["response_id"] for item in result["response_provenance"]
    ] == ["EL-QP-A:long", "EL-QP-B:long"]
    assert result["response_mapping_scope"][1]["provenance"].endswith(
        "long_combination table field"
    )


def test_project_criteria_require_explicit_per_combination_limits_and_source():
    criteria = sls.crack_criteria_from_inputs({
        "sls_criterion_mode": sls.CRITERION_MODE_PROJECT,
        "sls_limit_source": "Project DB clause SLS-4",
        "sls_project_frequent_limit": 0.24,
        "sls_project_quasi_permanent_limit": 0.21,
    })
    result = sls.crack_assessment(
        {
            "Frequent": {"wk": 0.25, "element_id": "bar 1"},
            "QP": {"wk": 0.20, "element_id": "bar 2"},
        },
        valid=True,
        criteria=criteria,
        response_contexts={
            "Frequent": {
                "combination": sls.COMBINATION_FREQUENT,
                "response_id": "frequent",
            },
            "QP": {
                "combination": sls.COMBINATION_QUASI_PERMANENT,
                "response_id": "qp",
            },
        },
    )

    assert result["status"] == "EXCEEDED"
    assert [item["limit"] for item in result["criteria"]] == [0.24, 0.21]
    assert [item["status"] for item in result["criteria"]] == [
        "EXCEEDED",
        "OK",
    ]


def test_legacy_unstructured_call_fails_closed_instead_of_maxing_durations():
    result = sls.crack_assessment(
        {
            "Long-term": {"wk": 0.22, "element_id": "bar 2"},
            "Total": {"wk": 0.31, "element_id": "tendon 1"},
        },
        limit_mm=0.30,
        valid=True,
    )

    assert result["status"] == "NOT ASSESSED"
    assert result["value"] is None
    assert "structured criterion" in result["reason"]


def test_not_applicable_reason_is_retained_for_required_combination():
    result = sls.crack_assessment(
        {"QP": None, "Total": None},
        valid=True,
        criteria=sls.crack_criteria_from_inputs(_standard_inputs()),
        response_contexts={
            "QP": {
                "combination": sls.COMBINATION_QUASI_PERMANENT,
                "response_id": "qp",
            },
            "Total": {
                "combination": sls.COMBINATION_CHARACTERISTIC,
                "response_id": "total",
            },
        },
        dispositions={
            "QP": {
                "status": "NOT APPLICABLE",
                "reason": "The section is uncracked.",
            },
            "Total": {
                "status": "NOT APPLICABLE",
                "reason": "The section is uncracked.",
            },
        },
    )

    assert result["status"] == "NOT APPLICABLE"
    assert result["reason"] == "The section is uncracked."
