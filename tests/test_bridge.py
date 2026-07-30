import pandas as pd
import pathlib
import sys
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import bridge_analysis
import bridge_inputs
from sector import bridge


def test_optional_brittle_method_b_remains_numerical_under_danish_selection():
    result = bridge.calculate_brittle_method_b(
        [
            bridge.PrestressBrittleRegion(
                "bottom",
                m_rep_knm=1000.0,
                z_s_m=0.8,
                f_yk_mpa=500.0,
                as_provided_mm2=3000.0,
            )
        ],
        selected_standard=bridge.EN1992_2_DK_NA,
    )

    assert result["rows"][0]["as_required_mm2"] == pytest.approx(2500.0)
    assert result["rows"][0]["utilisation"] == pytest.approx(5.0 / 6.0)
    assert result["rows"][0]["status"] == "PASS"
    assert "status" not in result
    assert "expects a different" in result["warning"]


def test_box_wall_benchmark_retains_actual_custom_angle_with_warning():
    result = bridge.calculate_box_walls(
        [
            bridge.BoxWall(
                "left",
                cot_theta=0.5,
                v_ed_kn=200.0,
                v_rd_max_kn=500.0,
                t_ed_equivalent_kn=50.0,
                t_rd_max_equivalent_kn=250.0,
            )
        ]
    )

    assert result["rows"][0]["cot_theta"] == pytest.approx(0.5)
    assert result["rows"][0]["utilisation"] == pytest.approx(0.6)
    assert result["rows"][0]["status"] == "PASS"
    assert "status" not in result
    assert any("actual values were retained" in item for item in result["warnings"])


def test_web_flange_minimum_crack_reinforcement_benchmark():
    result = bridge.calculate_minimum_crack_reinforcement(
        [
            bridge.MinimumCrackComponent(
                "web",
                act_mm2=100_000.0,
                k_c=0.4,
                k=0.8,
                fct_eff_mpa=3.0,
                sigma_s_mpa=200.0,
                as_provided_mm2=600.0,
            )
        ]
    )

    row = result["rows"][0]
    assert row["as_required_mm2"] == pytest.approx(480.0)
    assert row["utilisation"] == pytest.approx(0.8)
    assert row["status"] == "PASS"
    assert "status" not in result


def test_bridge_adapter_runs_only_nonempty_tables_without_coverage_rows():
    brittle = bridge_inputs.normalise_table(
        [{
            "region_id": "R1",
            "m_rep_knm": 100.0,
            "z_s_m": 0.5,
            "f_yk_mpa": 500.0,
            "as_provided_mm2": 500.0,
        }],
        bridge_inputs.BRITTLE_TABLE_KEY,
    )
    inp = {
        "bridge_standard": bridge.COMPONENT_METHODS,
        bridge_inputs.BRITTLE_TABLE_KEY: brittle,
        bridge_inputs.BOX_WALL_TABLE_KEY: bridge_inputs.empty_table(
            bridge_inputs.BOX_WALL_TABLE_KEY
        ),
        bridge_inputs.MINIMUM_CRACK_TABLE_KEY: bridge_inputs.empty_table(
            bridge_inputs.MINIMUM_CRACK_TABLE_KEY
        ),
    }

    payload = bridge_analysis.run(inp)

    assert set(payload["calculations"]) == {"brittle_method_b"}
    assert "coverage" not in payload
    assert "approval" not in str(payload).casefold()


def test_malformed_bridge_numeric_value_is_rejected():
    table = pd.DataFrame([{
        "wall_id": "W1",
        "cot_theta": "not numeric",
        "v_ed_kn": 1.0,
        "v_rd_max_kn": 2.0,
        "t_ed_equivalent_kn": 0.0,
        "t_rd_max_equivalent_kn": 2.0,
    }])

    with pytest.raises(ValueError, match="finite numeric"):
        bridge_inputs.records(table, bridge_inputs.BOX_WALL_TABLE_KEY)
