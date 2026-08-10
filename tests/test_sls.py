import numpy as np
import pytest

from sector import sls
from sector.serviceability import CrackWidthEvaluation


def test_stress_outputs_are_numerical_without_limits_or_verdicts():
    outputs = sls.stress_outputs(
        [125.0, -20.0, 780.0],
        n_bars=2,
        max_concrete_compression=18.5,
        valid=True,
        bar_ids=["B-A", "B-B"],
        tendon_ids=["P-A"],
    )

    assert outputs["concrete"]["value"] == pytest.approx(18.5)
    assert outputs["reinforcement"]["value"] == pytest.approx(125.0)
    assert outputs["reinforcement"]["governing"] == "B-A"
    assert outputs["prestress"]["value"] == pytest.approx(780.0)
    assert outputs["prestress"]["governing"] == "P-A"
    assert all(
        "status" not in output
        and "limit" not in output
        and "util" not in output
        and "verdict" not in output
        for output in outputs.values()
    )


def test_stress_outputs_reject_invalid_solver_state_without_a_verdict():
    outputs = sls.stress_outputs(
        [125.0],
        n_bars=1,
        max_concrete_compression=18.5,
        valid=False,
    )
    assert outputs["concrete"]["value"] is None
    assert outputs["reinforcement"]["value"] is None
    assert outputs["concrete"]["calculation_state"] == "INVALID"


def test_crack_outputs_select_largest_actual_calculation():
    output = sls.crack_outputs(
        {
            "Named sustained part": {"wk": 0.19, "element_id": "B-2"},
            "Named instantaneous part": {"wk": 0.31, "element_id": "B-7"},
        },
        valid=True,
    )

    assert output == {
        "value": pytest.approx(0.31),
        "case": "Named instantaneous part",
        "governing": "B-7",
        "unit": "mm",
        "calculation_state": "CALCULATED - ACCEPTANCE NOT ASSESSED",
        "criterion_mm": None,
        "ratio": None,
        "criterion_source": None,
        "reason": (
            "No ordinary crack-width criterion was specified; acceptance "
            "is not assessed."
        ),
        "comparison_equation": None,
    }
    assert "limit" not in output
    assert "status" not in output


def test_crack_output_not_requested_retains_stored_criterion_without_a_width():
    source = sls.crack_criterion_source("EL-quiet")
    output = sls.crack_outputs(
        {"Short-term": {"wk": 0.31, "element_id": "B-7"}},
        valid=True,
        requested=False,
        criterion_mm=0.30,
        criterion_source=source,
    )

    assert output["calculation_state"] == "NOT REQUESTED"
    assert output["value"] is None
    assert output["criterion_mm"] == pytest.approx(0.30)
    assert output["criterion_source"] == source
    assert output["ratio"] is None


def test_crack_output_preserves_evaluation_reason_when_width_is_unavailable():
    reason = "The tested reinforcement is outside the validated crack scope."
    output = sls.crack_outputs(
        {"Short-term": CrackWidthEvaluation("NOT ASSESSED", reason)},
        valid=True,
        requested=True,
        criterion_mm=0.30,
        criterion_source=sls.crack_criterion_source("EL-scope"),
    )

    assert output["calculation_state"] == "NOT ASSESSED"
    assert output["value"] is None
    assert output["reason"] == reason


def test_invalid_requested_crack_result_is_not_assessed_with_retained_reason():
    reason = "The cracked-section iteration did not converge."
    output = sls.crack_outputs(
        {"Short-term": CrackWidthEvaluation("NOT ASSESSED", reason)},
        valid=False,
        requested=True,
        criterion_mm=0.30,
        criterion_source=sls.crack_criterion_source("EL-invalid-result"),
    )

    assert output["calculation_state"] == "NOT ASSESSED"
    assert output["reason"] == reason


@pytest.mark.parametrize(
    ("criterion", "expected_status", "expected_ratio"),
    [
        (0.40, "WITHIN USER-SPECIFIED LIMIT", 0.31 / 0.40),
        (0.31, "WITHIN USER-SPECIFIED LIMIT", 1.0),
        (0.30, "EXCEEDS USER-SPECIFIED LIMIT", 0.31 / 0.30),
    ],
)
def test_crack_output_compares_only_with_a_user_criterion(
    criterion, expected_status, expected_ratio
):
    source = sls.crack_criterion_source("EL-limit")
    output = sls.crack_outputs(
        {"Short-term": {"wk": 0.31, "element_id": "B-7"}},
        valid=True,
        requested=True,
        criterion_mm=criterion,
        criterion_source=source,
    )

    assert output["calculation_state"] == expected_status
    assert output["ratio"] == pytest.approx(expected_ratio)
    assert output["criterion_mm"] == pytest.approx(criterion)
    assert output["criterion_source"] == source
    assert output["comparison_equation"] == "w_k / w_k,criterion"
    assert "PASS" not in str(output) and "FAIL" not in str(output)


@pytest.mark.parametrize(
    "criterion",
    [True, np.bool_(True), 0.0, -0.1, float("inf"), "bad"],
)
def test_crack_output_invalid_criterion_fails_closed(criterion):
    output = sls.crack_outputs(
        {"Short-term": {"wk": 0.20, "element_id": "B-1"}},
        valid=True,
        requested=True,
        criterion_mm=criterion,
        criterion_source=sls.crack_criterion_source("EL-invalid"),
    )

    assert output["calculation_state"] == "NOT ASSESSED"
    assert output["ratio"] is None
    assert output["reason"] == (
        "The crack-width criterion must be a positive finite number."
    )


def test_crack_comparison_requires_user_source_and_millimetre_output():
    without_source = sls.crack_outputs(
        {"Short-term": {"wk": 0.20, "element_id": "B-1"}},
        valid=True,
        criterion_mm=0.30,
        criterion_source=" ",
    )
    wrong_unit = sls.assess_crack_output(
        {
            "value": 0.20,
            "case": "Short-term",
            "governing": "B-1",
            "unit": "m",
        },
        requested=True,
        criterion_mm=0.30,
        criterion_source=sls.crack_criterion_source("EL-units"),
    )

    assert without_source["calculation_state"] == "NOT ASSESSED"
    assert "nonblank criterion source" in without_source["reason"]
    assert wrong_unit["calculation_state"] == "NOT ASSESSED"
    assert "retained in millimetres" in wrong_unit["reason"]


def test_element_rows_keep_bar_and_tendon_identity():
    rows = sls.element_rows(
        [(0.0, 0.0, 100.0)],
        [(0.1, 0.0, 150.0)],
        total=[100.0, 800.0],
        long=[60.0, 700.0],
        dif=[40.0, 100.0],
        rst1=[35.0, 90.0],
        es_mpa=[200_000.0],
        ep_mpa=[195_000.0],
        bar_ids=["B-custom"],
        tendon_ids=["P-custom"],
    )

    assert [row["element_type"] for row in rows] == ["Bar", "Tendon"]
    assert [row["element_id"] for row in rows] == ["B-custom", "P-custom"]
    assert rows[0]["total_mpa"] == pytest.approx(100.0)
    assert rows[1]["total_mpa"] == pytest.approx(800.0)
