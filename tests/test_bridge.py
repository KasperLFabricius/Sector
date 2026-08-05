import pandas as pd
import pathlib
import sys
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import bridge_analysis
import bridge_inputs
from sector import bridge


_VALID_BRIDGE_ROWS = {
    bridge_inputs.BRITTLE_TABLE_KEY: {
        "region_id": "R1",
        "m_rep_knm": 100.0,
        "z_s_m": 0.5,
        "f_yk_mpa": 500.0,
        "as_provided_mm2": 500.0,
    },
    bridge_inputs.BOX_WALL_TABLE_KEY: {
        "wall_id": "W1",
        "cot_theta": 1.5,
        "v_ed_kn": 50.0,
        "v_rd_max_kn": 100.0,
        "t_ed_equivalent_kn": 10.0,
        "t_rd_max_equivalent_kn": 100.0,
    },
    bridge_inputs.MINIMUM_CRACK_TABLE_KEY: {
        "component": "web",
        "act_mm2": 1000.0,
        "k_c": 0.4,
        "k": 0.8,
        "fct_eff_mpa": 3.0,
        "sigma_s_mpa": 200.0,
        "as_provided_mm2": 100.0,
        "restrained_shrinkage": False,
    },
}


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


def test_bridge_table_retains_invalid_cells_until_validation():
    invalid_numeric = bridge_inputs.normalise_table(
        [{"cot_theta": "not numeric"}],
        bridge_inputs.BOX_WALL_TABLE_KEY,
    )
    invalid_numeric = bridge_inputs.normalise_table(
        invalid_numeric,
        bridge_inputs.BOX_WALL_TABLE_KEY,
    )
    assert invalid_numeric.loc[0, "cot_theta"] == "not numeric"
    with pytest.raises(ValueError, match="cot_theta must be finite numeric"):
        bridge_inputs.records(
            invalid_numeric,
            bridge_inputs.BOX_WALL_TABLE_KEY,
        )

    invalid_boolean = bridge_inputs.normalise_table(
        [{
            "component": "web",
            "act_mm2": 1000.0,
            "k_c": 0.4,
            "k": 0.8,
            "fct_eff_mpa": 3.0,
            "sigma_s_mpa": 200.0,
            "as_provided_mm2": 100.0,
            "restrained_shrinkage": "yes",
        }],
        bridge_inputs.MINIMUM_CRACK_TABLE_KEY,
    )
    invalid_boolean = bridge_inputs.normalise_table(
        invalid_boolean,
        bridge_inputs.MINIMUM_CRACK_TABLE_KEY,
    )
    assert invalid_boolean.loc[0, "restrained_shrinkage"] == "yes"
    with pytest.raises(ValueError, match="restrained_shrinkage must be Boolean"):
        bridge_inputs.records(
            invalid_boolean,
            bridge_inputs.MINIMUM_CRACK_TABLE_KEY,
        )


@pytest.mark.parametrize(
    ("table_key", "column"),
    [
        (table_key, column)
        for table_key in bridge_inputs.TABLE_KEYS
        for column in bridge_inputs.NUMERIC_COLUMNS[table_key]
    ],
)
def test_every_bridge_numeric_cell_retains_invalid_type(table_key, column):
    row = dict(_VALID_BRIDGE_ROWS[table_key])
    row[column] = "not numeric"

    frame = bridge_inputs.normalise_table([row], table_key)
    frame = bridge_inputs.normalise_table(frame, table_key)

    assert frame.loc[0, column] == "not numeric"
    with pytest.raises(ValueError, match=f"{column} must be finite numeric"):
        bridge_inputs.records(frame, table_key)


@pytest.mark.parametrize(
    ("table_key", "column"),
    [
        (table_key, column)
        for table_key in bridge_inputs.TABLE_KEYS
        for column in bridge_inputs.NUMERIC_COLUMNS[table_key]
    ],
)
@pytest.mark.parametrize("value", [float("inf"), float("-inf")])
def test_every_non_finite_bridge_cell_has_stable_json_safe_identity(
    table_key,
    column,
    value,
):
    row = dict(_VALID_BRIDGE_ROWS[table_key])
    row[column] = value

    expected_signature = bridge_inputs.table_signature([row], table_key)
    frame = bridge_inputs.normalise_table([row], table_key)
    frame = bridge_inputs.normalise_table(frame, table_key)

    assert bridge_inputs.table_signature(frame, table_key) == expected_signature
    assert frame.loc[0, column] == {
        "__sector_bridge_invalid_number__": {
            "type": "builtins.float",
            "value": (
                "positive_infinity" if value > 0.0 else "negative_infinity"
            ),
        }
    }
    with pytest.raises(ValueError, match=f"{column} must be finite numeric"):
        bridge_inputs.records(frame, table_key)


def test_non_json_numeric_object_has_stable_json_safe_identity():
    key = bridge_inputs.BOX_WALL_TABLE_KEY
    value = complex(1.0, -2.0)

    frame = bridge_inputs.normalise_table([{"cot_theta": value}], key)
    signature = bridge_inputs.table_signature(frame, key)
    frame = bridge_inputs.normalise_table(frame, key)

    assert frame.loc[0, "cot_theta"] == {
        "__sector_bridge_invalid_number__": {
            "type": "builtins.complex",
            "value": "malformed:(1-2j)",
        }
    }
    assert bridge_inputs.table_signature(frame, key) == signature
    with pytest.raises(ValueError, match="cot_theta must be finite numeric"):
        bridge_inputs.records(frame, key)


@pytest.mark.parametrize("value", ["yes", 1, 0.0])
def test_bridge_boolean_cell_retains_invalid_type(value):
    row = dict(_VALID_BRIDGE_ROWS[bridge_inputs.MINIMUM_CRACK_TABLE_KEY])
    row["restrained_shrinkage"] = value

    frame = bridge_inputs.normalise_table(
        [row],
        bridge_inputs.MINIMUM_CRACK_TABLE_KEY,
    )
    frame = bridge_inputs.normalise_table(
        frame,
        bridge_inputs.MINIMUM_CRACK_TABLE_KEY,
    )

    assert frame.loc[0, "restrained_shrinkage"] == value
    with pytest.raises(ValueError, match="restrained_shrinkage must be Boolean"):
        bridge_inputs.records(
            frame,
            bridge_inputs.MINIMUM_CRACK_TABLE_KEY,
        )


def test_bridge_table_signature_retains_invalid_cell_identity():
    first = [{"cot_theta": "bad-one"}]
    second = [{"cot_theta": "bad-two"}]

    assert bridge_inputs.table_signature(
        first,
        bridge_inputs.BOX_WALL_TABLE_KEY,
    ) != bridge_inputs.table_signature(
        second,
        bridge_inputs.BOX_WALL_TABLE_KEY,
    )
    assert bridge_inputs.table_signature(
        [_VALID_BRIDGE_ROWS[bridge_inputs.BOX_WALL_TABLE_KEY]],
        bridge_inputs.BOX_WALL_TABLE_KEY,
    ) == (("W1", 1.5, 50.0, 100.0, 10.0, 100.0),)


def test_bridge_records_materialises_one_shot_table_once():
    rows = bridge_inputs.records(
        (
            row
            for row in [{
                "wall_id": "W1",
                "cot_theta": 1.5,
                "v_ed_kn": 50.0,
                "v_rd_max_kn": 100.0,
                "t_ed_equivalent_kn": 10.0,
                "t_rd_max_equivalent_kn": 100.0,
            }]
        ),
        bridge_inputs.BOX_WALL_TABLE_KEY,
    )

    assert rows[0]["wall_id"] == "W1"
    assert rows[0]["cot_theta"] == pytest.approx(1.5)


def test_duplicate_bridge_columns_are_rejected_before_normalisation():
    table = pd.DataFrame([["W1", "W2"]], columns=["wall_id", "wall_id"])

    with pytest.raises(ValueError, match="duplicate columns"):
        bridge_inputs.normalise_table(
            table,
            bridge_inputs.BOX_WALL_TABLE_KEY,
        )


def test_bridge_columns_order_defaults_and_unknown_exclusion_are_pinned():
    frame = bridge_inputs.normalise_table(
        pd.DataFrame([{
            "v_ed_kn": 50.0,
            "wall_id": "W1",
            "outside_contract": "discarded",
        }]),
        bridge_inputs.BOX_WALL_TABLE_KEY,
    )

    assert tuple(frame.columns) == bridge_inputs.TABLE_COLUMNS[
        bridge_inputs.BOX_WALL_TABLE_KEY
    ]
    assert "outside_contract" not in frame
    assert frame.loc[0, "wall_id"] == "W1"
    assert frame.loc[0, "v_ed_kn"] == pytest.approx(50.0)
    assert bridge_inputs.records(
        [{}],
        bridge_inputs.BOX_WALL_TABLE_KEY,
    ) == []
    assert bridge_inputs.records(
        [{"outside_contract": "discarded"}],
        bridge_inputs.BOX_WALL_TABLE_KEY,
    ) == []


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


def test_pr13a1a_acceptance_contract_pins_raw_boundary_and_exclusions():
    text = (
        ROOT / "docs" / "pr13a1a_f013_bridge_raw_boundary_acceptance.md"
    ).read_text(encoding="utf-8")

    for marker in (
        "89fbc4a9713727093f453d0af7ffdce2dae17393",
        "materialized exactly once",
        "malformed numerical or Boolean cell remains distinguishable",
        "No bridge formula",
        "typed kernel/result adapter",
        "v0.93",
    ):
        assert marker in text
