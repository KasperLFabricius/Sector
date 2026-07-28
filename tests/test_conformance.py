"""Canonical numerical-validity versus standards-conformance regressions."""

import math

import pytest

from sector import conformance


_COMMON = {
    "parameter_id": "test.factor",
    "label": "Test factor",
    "selected_standard": "DS/EN test",
    "standard_methodology": "Test standard method",
    "normative_source": "DS/EN test, clause 1",
}


def _prescribed(value, **changes):
    return conformance.assess_parameter(
        value,
        prescribed_value=1.0,
        **(_COMMON | changes),
    )


def _range(value, **changes):
    return conformance.assess_parameter(
        value,
        minimum=1.0,
        maximum=2.5,
        **(_COMMON | changes),
    )


def test_standard_prescription_emits_an_unqualified_standard_verdict():
    record = _prescribed(1.0)
    verdict = conformance.aggregate(
        (record,),
        analytical_status=conformance.STATUS_PASS,
        selected_standard="DS/EN test",
    )

    assert record["state"] == conformance.STATE_CONFORMS
    assert record["actual_value"] == 1.0
    assert verdict["assessment_status"] == conformance.STATUS_PASS
    assert verdict["qualified_verdict"] == "STANDARD PASS"
    assert verdict["standard_verdict"] == conformance.STATUS_PASS


@pytest.mark.parametrize(
    "value",
    [
        math.nextafter(1.0, 0.0),
        math.nextafter(2.5, math.inf),
        0.5,
        10.0,
    ],
)
def test_positive_standard_deviation_is_preserved_for_review(value):
    record = _range(value)
    verdict = conformance.aggregate(
        (record,),
        analytical_status=conformance.STATUS_PASS,
        selected_standard="DS/EN test",
    )

    assert record["actual_value"] == value
    assert record["state"] == conformance.STATE_REVIEW
    assert record["deviation"] is True
    assert verdict["assessment_status"] == conformance.STATUS_REVIEW
    assert verdict["qualified_verdict"] == "REVIEW - analytical PASS"
    assert verdict["standard_verdict"] == "NOT FULLY ASSESSED"


@pytest.mark.parametrize("value", [0.5, 2.0])
def test_approved_custom_factor_is_calculable_and_auditable(value):
    record = _prescribed(
        value,
        basis=conformance.CUSTOM_BASIS,
        custom_methodology="Project design-basis factor",
        approval_reference="DB-TEST-01 / checker A",
    )
    verdict = conformance.aggregate(
        (record,),
        analytical_status=conformance.STATUS_FAIL,
        selected_standard="DS/EN test",
    )

    assert record["actual_value"] == value
    assert record["state"] == conformance.STATE_APPROVED_CUSTOM
    assert verdict["assessment_status"] == conformance.STATUS_REVIEW
    assert verdict["qualified_verdict"] == "APPROVED CUSTOM FAIL"
    assert verdict["standard_verdict"] == "NOT FULLY ASSESSED"


@pytest.mark.parametrize(
    ("custom_methodology", "approval_reference"),
    [
        ("", ""),
        ("Project design-basis factor", ""),
        ("", "DB-TEST-01 / checker A"),
    ],
)
def test_incomplete_custom_basis_requires_review(
    custom_methodology,
    approval_reference,
):
    record = _prescribed(
        2.0,
        basis=conformance.CUSTOM_BASIS,
        custom_methodology=custom_methodology,
        approval_reference=approval_reference,
    )

    assert record["actual_value"] == 2.0
    assert record["state"] == conformance.STATE_REVIEW


def test_contradictory_standard_and_custom_metadata_requires_review():
    record = _prescribed(
        1.0,
        basis=conformance.STANDARD_BASIS,
        custom_methodology="Conflicting custom method",
        approval_reference="DB-TEST-02",
    )

    assert record["state"] == conformance.STATE_REVIEW
    assert "conflicts" in record["message"]


@pytest.mark.parametrize(
    "value",
    [True, False, 0.0, -1.0, float("nan"), float("inf"), "1.0"],
)
def test_numerically_unusable_values_are_hard_errors(value):
    with pytest.raises(ValueError, match="finite real number greater than zero"):
        _prescribed(value)


def test_publication_verification_detects_mutable_or_stale_evidence():
    record = _prescribed(1.0)
    verified, errors = conformance.verify_self_contained(record)

    assert verified == record
    assert errors == ()

    record["actual_value"] = 2.0
    _, errors = conformance.verify_self_contained(record)

    assert errors == (
        "parameter conformance evidence is stale, incomplete, or contradictory",
    )


def test_aggregate_rejects_malformed_status_or_cross_standard_records():
    record = _prescribed(1.0)

    with pytest.raises(ValueError, match="PASS or FAIL"):
        conformance.aggregate(
            (record,),
            analytical_status=conformance.STATUS_REVIEW,
            selected_standard="DS/EN test",
        )
    with pytest.raises(ValueError, match="another selected standard"):
        conformance.aggregate(
            (record,),
            analytical_status=conformance.STATUS_PASS,
            selected_standard="Different standard",
        )
