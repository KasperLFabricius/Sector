import pytest

from sector import sls


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
        "calculation_state": "CALCULATED",
    }
    assert "limit" not in output
    assert "status" not in output


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
