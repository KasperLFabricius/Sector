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


def _duration_outputs(**overrides):
    kwargs = {
        "long_term_cases": {
            "Long-term (fine)": {"wk": 0.19, "element_id": "B-2"},
            "Long-term (coarse)": {"wk": 0.21, "element_id": "B-3"},
        },
        "short_term_cases": {
            "Short-term (fine)": {"wk": 0.31, "element_id": "B-7"},
            "Short-term (coarse)": {"wk": 0.29, "element_id": "B-8"},
        },
        "valid": True,
        "long_term_criterion_mm": 0.0,
        "short_term_criterion_mm": 0.0,
        "long_term_criterion_source": sls.crack_criterion_source("long_term"),
        "short_term_criterion_source": sls.crack_criterion_source("short_term"),
    }
    kwargs.update(overrides)
    return sls.crack_outputs(**kwargs)


def test_crack_outputs_select_largest_candidate_inside_each_duration():
    output = _duration_outputs()

    assert tuple(output) == ("long_term", "short_term")
    assert output["long_term"]["value"] == pytest.approx(0.21)
    assert output["long_term"]["case"] == "Long-term (coarse)"
    assert output["long_term"]["governing"] == "B-3"
    assert output["short_term"]["value"] == pytest.approx(0.31)
    assert output["short_term"]["case"] == "Short-term (fine)"
    assert output["short_term"]["governing"] == "B-7"
    assert all(
        item["calculation_state"]
        == "CALCULATED - ACCEPTANCE NOT ASSESSED"
        and item["criterion_mm"] == 0.0
        and item["ratio"] is None
        and item["comparison_equation"] is None
        for item in output.values()
    )


def test_crack_outputs_never_compare_a_duration_with_the_other_limit():
    output = _duration_outputs(
        long_term_criterion_mm=0.20,
        short_term_criterion_mm=0.40,
    )

    assert output["long_term"]["calculation_state"] == (
        "EXCEEDS USER-SPECIFIED LIMIT"
    )
    assert output["long_term"]["ratio"] == pytest.approx(0.21 / 0.20)
    assert output["short_term"]["calculation_state"] == (
        "WITHIN USER-SPECIFIED LIMIT"
    )
    assert output["short_term"]["ratio"] == pytest.approx(0.31 / 0.40)


@pytest.mark.parametrize(
    ("criterion", "expected_status", "expected_ratio"),
    [
        (0.40, "WITHIN USER-SPECIFIED LIMIT", 0.31 / 0.40),
        (0.31, "WITHIN USER-SPECIFIED LIMIT", 1.0),
        (0.30, "EXCEEDS USER-SPECIFIED LIMIT", 0.31 / 0.30),
    ],
)
def test_short_term_crack_boundary_uses_only_the_short_term_criterion(
    criterion, expected_status, expected_ratio
):
    output = _duration_outputs(short_term_criterion_mm=criterion)["short_term"]

    assert output["calculation_state"] == expected_status
    assert output["ratio"] == pytest.approx(expected_ratio)
    assert output["criterion_mm"] == pytest.approx(criterion)
    assert output["criterion_source"] == sls.crack_criterion_source(
        "short_term"
    )
    assert output["comparison_equation"] == "w_k / w_k,criterion"
    assert "PASS" not in str(output) and "FAIL" not in str(output)


def test_zero_criterion_is_an_explicit_no_comparison_state():
    output = _duration_outputs(
        long_term_criterion_mm=0.0,
        short_term_criterion_mm=0.30,
    )

    long_term = output["long_term"]
    assert long_term["criterion_mm"] == 0.0
    assert long_term["calculation_state"] == (
        "CALCULATED - ACCEPTANCE NOT ASSESSED"
    )
    assert long_term["ratio"] is None
    assert long_term["comparison_equation"] is None
    assert "no comparison was requested" in long_term["reason"]
    assert output["short_term"]["calculation_state"] == (
        "EXCEEDS USER-SPECIFIED LIMIT"
    )


def test_crack_output_not_requested_retains_both_criteria_without_widths():
    output = _duration_outputs(
        requested=False,
        long_term_criterion_mm=0.25,
        short_term_criterion_mm=0.30,
    )

    assert all(
        item["calculation_state"] == "NOT REQUESTED"
        and item["value"] is None
        and item["ratio"] is None
        for item in output.values()
    )
    assert output["long_term"]["criterion_mm"] == pytest.approx(0.25)
    assert output["short_term"]["criterion_mm"] == pytest.approx(0.30)


def test_one_unavailable_duration_does_not_suppress_the_other():
    reason = "The tested reinforcement is outside the validated crack scope."
    output = _duration_outputs(
        long_term_cases={
            "Long-term": CrackWidthEvaluation("NOT ASSESSED", reason)
        },
        short_term_cases={
            "Short-term": {"wk": 0.20, "element_id": "B-1"}
        },
        long_term_criterion_mm=0.30,
        short_term_criterion_mm=0.30,
    )

    assert output["long_term"]["calculation_state"] == "NOT ASSESSED"
    assert output["long_term"]["reason"] == reason
    assert output["short_term"]["calculation_state"] == (
        "WITHIN USER-SPECIFIED LIMIT"
    )


def test_invalid_requested_crack_result_is_not_assessed_for_both_durations():
    output = _duration_outputs(valid=False)

    assert all(
        item["calculation_state"] == "NOT ASSESSED"
        and item["value"] is None
        for item in output.values()
    )


@pytest.mark.parametrize(
    "criterion",
    [True, np.bool_(True), -0.1, float("nan"), float("inf"), "0.30", b"0.30"],
)
def test_crack_output_invalid_criterion_fails_closed(criterion):
    output = _duration_outputs(long_term_criterion_mm=criterion)["long_term"]

    assert output["calculation_state"] == "NOT ASSESSED"
    assert output["ratio"] is None
    assert output["reason"] == (
        "The crack-width criterion must be a non-negative finite number."
    )


def test_crack_comparison_requires_user_source_and_millimetre_output():
    without_source = _duration_outputs(
        long_term_criterion_mm=0.30,
        long_term_criterion_source=" ",
    )["long_term"]
    wrong_unit = sls.assess_crack_output(
        {
            "value": 0.20,
            "case": "Short-term",
            "governing": "B-1",
            "unit": "m",
        },
        duration="short_term",
        requested=True,
        criterion_mm=0.30,
        criterion_source=sls.crack_criterion_source("short_term"),
    )

    assert without_source["calculation_state"] == "NOT ASSESSED"
    assert "nonblank criterion source" in without_source["reason"]
    assert wrong_unit["calculation_state"] == "NOT ASSESSED"
    assert "retained in millimetres" in wrong_unit["reason"]


def test_crack_criterion_source_rejects_unknown_duration():
    with pytest.raises(
        ValueError,
        match="duration must be exactly 'long_term' or 'short_term'",
    ):
        sls.crack_criterion_source("frequent")


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
