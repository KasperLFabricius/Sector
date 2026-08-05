import json
import math
import numpy as np
import pandas as pd
import pathlib
import sys
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import bridge_analysis
import bridge_inputs
from sector import bridge


_RAW_BOUNDARY_ROWS = {
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


def _all_active_bridge_input():
    result = {
        "bridge_standard": bridge.COMPONENT_METHODS,
    }
    result.update({
        key: bridge_inputs.normalise_table([dict(row)], key)
        for key, row in _RAW_BOUNDARY_ROWS.items()
    })
    return result


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


def test_kernel_rows_publish_normalized_original_values():
    brittle = bridge.calculate_brittle_method_b([
        bridge.PrestressBrittleRegion(
            "  R1  ",
            np.float64(10.0),
            np.float64(0.5),
            np.float64(500.0),
            np.float64(100.0),
        )
    ])["rows"][0]
    assert tuple(brittle) == (
        "region_id",
        "m_rep_knm",
        "z_s_m",
        "f_yk_mpa",
        "as_required_mm2",
        "as_provided_mm2",
        "utilisation",
        "status",
    )
    assert {
        key: brittle[key]
        for key in ("region_id", "m_rep_knm", "z_s_m", "f_yk_mpa")
    } == {
        "region_id": "R1",
        "m_rep_knm": 10.0,
        "z_s_m": 0.5,
        "f_yk_mpa": 500.0,
    }

    wall = bridge.calculate_box_walls([
        bridge.BoxWall(
            "  W1  ",
            np.float64(1.5),
            np.float64(-20.0),
            np.float64(100.0),
            np.float64(-10.0),
            np.float64(100.0),
        )
    ])["rows"][0]
    assert tuple(wall) == (
        "wall_id",
        "cot_theta",
        "v_ed_kn",
        "v_rd_max_kn",
        "t_ed_equivalent_kn",
        "t_rd_max_equivalent_kn",
        "utilisation",
        "status",
    )
    assert {
        key: wall[key]
        for key in (
            "wall_id",
            "cot_theta",
            "v_ed_kn",
            "v_rd_max_kn",
            "t_ed_equivalent_kn",
            "t_rd_max_equivalent_kn",
        )
    } == {
        "wall_id": "W1",
        "cot_theta": 1.5,
        "v_ed_kn": -20.0,
        "v_rd_max_kn": 100.0,
        "t_ed_equivalent_kn": -10.0,
        "t_rd_max_equivalent_kn": 100.0,
    }

    minimum = bridge.calculate_minimum_crack_reinforcement([
        bridge.MinimumCrackComponent(
            "  WEB  ",
            np.float64(1000.0),
            np.float64(0.4),
            np.float64(0.8),
            np.float64(3.0),
            np.float64(200.0),
            np.float64(100.0),
            True,
        )
    ])["rows"][0]
    assert tuple(minimum) == (
        "component",
        "act_mm2",
        "k_c",
        "k",
        "fct_eff_mpa",
        "sigma_s_mpa",
        "as_provided_mm2",
        "restrained_shrinkage",
        "fct_eff_used_mpa",
        "as_required_mm2",
        "utilisation",
        "status",
    )
    assert {
        key: minimum[key]
        for key in (
            "component",
            "act_mm2",
            "k_c",
            "k",
            "fct_eff_mpa",
            "sigma_s_mpa",
            "as_provided_mm2",
            "restrained_shrinkage",
        )
    } == {
        "component": "web",
        "act_mm2": 1000.0,
        "k_c": 0.4,
        "k": 0.8,
        "fct_eff_mpa": 3.0,
        "sigma_s_mpa": 200.0,
        "as_provided_mm2": 100.0,
        "restrained_shrinkage": True,
    }


@pytest.mark.parametrize(
    "calculation",
    (
        lambda: bridge.minimum_brittle_reinforcement_area(True, 0.5, 500.0),
        lambda: bridge.box_wall_interaction(1.0, 0.0, 1.0, 1.0),
        lambda: bridge.minimum_crack_reinforcement_area(
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            restrained_shrinkage=1,
        ),
    ),
)
def test_expected_kernel_validation_has_typed_input_error(calculation):
    with pytest.raises(bridge.BridgeInputError):
        calculation()


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

    assert tuple(payload) == (
        "selected_standard",
        "scope",
        "calculations",
        "failures",
    )
    assert set(payload["calculations"]) == {"brittle_method_b"}
    assert payload["failures"] == ()
    assert "coverage" not in payload
    assert "approval" not in str(payload).casefold()


def test_complete_success_payload_is_ordered_and_finite():
    payload = bridge_analysis.run(_all_active_bridge_input())
    calculations = payload["calculations"]

    assert payload["failures"] == ()
    assert tuple(calculations) == (
        "brittle_method_b",
        "box_walls",
        "minimum_crack_reinforcement",
    )
    assert tuple(calculations["brittle_method_b"]) == (
        "method",
        "equation",
        "source",
        "selected_standard",
        "warning",
        "rows",
    )
    assert tuple(calculations["box_walls"]) == (
        "method",
        "equation",
        "source",
        "rows",
        "warnings",
    )
    assert tuple(calculations["minimum_crack_reinforcement"]) == (
        "method",
        "equation",
        "source",
        "rows",
    )
    for calculation in calculations.values():
        for row in calculation["rows"]:
            for value in row.values():
                if isinstance(value, float):
                    assert math.isfinite(value)


def test_method_b_positive_finite_denominator_underflow_is_typed():
    with pytest.raises(
        bridge.BridgeNumericalError,
        match="bottom: As,min cannot be represented as a finite result",
    ):
        bridge.calculate_brittle_method_b([
            bridge.PrestressBrittleRegion(
                "bottom",
                m_rep_knm=1.0,
                z_s_m=1.0e-200,
                f_yk_mpa=1.0e-200,
                as_provided_mm2=1.0,
            )
        ])


@pytest.mark.parametrize(
    "calculation",
    (
        lambda: bridge.box_wall_interaction(
            1.0e-308,
            1.0e308,
            0.0,
            1.0,
        ),
        lambda: bridge.minimum_crack_reinforcement_area(
            1.0e-308,
            1.0e-308,
            1.0,
            1.0,
            1.0,
        ),
    ),
)
def test_positive_finite_result_underflow_is_not_published(calculation):
    with pytest.raises(bridge.BridgeNumericalError):
        calculation()


@pytest.mark.parametrize(
    ("failed_key", "changes", "failed_family"),
    (
        (
            bridge_inputs.BRITTLE_TABLE_KEY,
            {"z_s_m": 1.0e-200, "f_yk_mpa": 1.0e-200},
            "brittle_method_b",
        ),
        (
            bridge_inputs.BOX_WALL_TABLE_KEY,
            {"v_ed_kn": 1.0e308, "v_rd_max_kn": 1.0e-308},
            "box_walls",
        ),
        (
            bridge_inputs.MINIMUM_CRACK_TABLE_KEY,
            {"act_mm2": 1.0e308, "k_c": 1.0e308},
            "minimum_crack_reinforcement",
        ),
    ),
)
def test_numerical_failure_is_family_local_and_has_no_verdict(
    failed_key,
    changes,
    failed_family,
):
    inp = _all_active_bridge_input()
    row = dict(_RAW_BOUNDARY_ROWS[failed_key])
    row.update(changes)
    inp[failed_key] = bridge_inputs.normalise_table([row], failed_key)

    payload = bridge_analysis.run(inp)

    expected = tuple(
        bridge_inputs.CALCULATION_KEYS[key]
        for key in bridge_inputs.TABLE_KEYS
        if key != failed_key
    )
    assert tuple(payload["calculations"]) == expected
    assert payload["failures"] == ({
        "family": failed_family,
        "table_key": failed_key,
        "state": "INVALID",
        "code": "NUMERICAL_FAILURE",
        "message": payload["failures"][0]["message"],
    },)
    assert "utilisation" not in payload["failures"][0]
    assert "status" not in payload["failures"][0]


def test_invalid_input_is_family_local_and_typed():
    inp = _all_active_bridge_input()
    row = dict(_RAW_BOUNDARY_ROWS[bridge_inputs.BOX_WALL_TABLE_KEY])
    row["v_rd_max_kn"] = "not numeric"
    inp[bridge_inputs.BOX_WALL_TABLE_KEY] = [row]

    payload = bridge_analysis.run(inp)

    assert tuple(payload["calculations"]) == (
        "brittle_method_b",
        "minimum_crack_reinforcement",
    )
    assert payload["failures"] == ({
        "family": "box_walls",
        "table_key": bridge_inputs.BOX_WALL_TABLE_KEY,
        "state": "INVALID",
        "code": "INVALID_INPUT",
        "message": (
            f"{bridge_inputs.BOX_WALL_TABLE_KEY} row 1: "
            "v_rd_max_kn must be finite numeric"
        ),
    },)


def test_unsupported_standard_is_failure_first_and_parses_no_table():
    payload = bridge_analysis.run({
        "bridge_standard": "future unimplemented route",
        bridge_inputs.BRITTLE_TABLE_KEY: object(),
    })

    assert payload["calculations"] == {}
    assert payload["failures"] == ({
        "family": "selected_standard",
        "table_key": "bridge_standard",
        "state": "UNSUPPORTED",
        "code": "UNSUPPORTED_STANDARD",
        "message": (
            "unknown selected bridge standard: future unimplemented route"
        ),
    },)


def test_scalar_pandas_null_standard_is_typed_unsupported():
    payload = bridge_analysis.run({"bridge_standard": pd.NA})

    assert payload["calculations"] == {}
    assert payload["failures"][0] == {
        "family": "selected_standard",
        "table_key": "bridge_standard",
        "state": "UNSUPPORTED",
        "code": "UNSUPPORTED_STANDARD",
        "message": "unknown selected bridge standard: <NA>",
    }


def test_unexpected_bridge_adapter_defect_propagates(monkeypatch):
    def unexpected(*_args, **_kwargs):
        raise RuntimeError("unexpected implementation defect")

    monkeypatch.setattr(bridge_inputs, "calculate_family", unexpected)

    with pytest.raises(RuntimeError, match="unexpected implementation defect"):
        bridge_analysis.run({
            "bridge_standard": bridge.COMPONENT_METHODS,
        })


def test_pr13a1b_acceptance_contract_is_frozen():
    text = (
        ROOT / "docs" / "pr13a1b_f013_bridge_typed_failure_acceptance.md"
    ).read_text(encoding="utf-8")

    for marker in (
        "f133ebae880b27e07a71586a0aea8fa920306e79",
        "bridge_brittle_base",
        "bridge_box_walls_base",
        "bridge_minimum_crack_base",
        "BridgeInputError",
        "BridgeNumericalError",
        "UNSUPPORTED_STANDARD",
        "NUMERICAL_FAILURE",
        "must not catch `RuntimeError`",
        "No bridge equation",
        "v0.93",
    ):
        assert marker in text


@pytest.mark.parametrize(
    ("table_key", "column"),
    [
        (table_key, column)
        for table_key in bridge_inputs.TABLE_KEYS
        for column in bridge_inputs.TABLE_COLUMNS[table_key]
    ],
)
@pytest.mark.parametrize("blank", [pd.NA, pd.NaT, float("nan")])
def test_scalar_pandas_and_numeric_blanks_stay_inert(
    table_key,
    column,
    blank,
):
    frame = bridge_inputs.normalise_table([{column: blank}], table_key)

    if column in bridge_inputs.TEXT_COLUMNS[table_key]:
        assert frame.loc[0, column] == ""
    elif column in bridge_inputs.BOOLEAN_COLUMNS[table_key]:
        assert frame.loc[0, column] is False or not frame.loc[0, column]
    else:
        assert pd.isna(frame.loc[0, column])
    assert bridge_inputs.records(frame, table_key) == []


@pytest.mark.parametrize(
    ("table_key", "column"),
    [
        (table_key, column)
        for table_key in bridge_inputs.TABLE_KEYS
        for column in bridge_inputs.NUMERIC_COLUMNS[table_key]
    ],
)
@pytest.mark.parametrize(
    "invalid",
    [
        "not numeric",
        True,
        float("inf"),
        float("-inf"),
        10 ** 4000,
        complex(1.0, -2.0),
        np.complex64(1.0 - 2.0j),
    ],
)
def test_every_numeric_bridge_cell_retains_invalid_identity(
    table_key,
    column,
    invalid,
):
    row = dict(_RAW_BOUNDARY_ROWS[table_key])
    row[column] = invalid
    expected = bridge_inputs.table_signature([row], table_key)

    frame = bridge_inputs.normalise_table([row], table_key)
    frame = bridge_inputs.normalise_table(frame, table_key)
    encoded = bridge_inputs.project_cell(frame.loc[0, column], table_key, column)

    assert bridge_inputs.table_signature(frame, table_key) == expected
    json.dumps(encoded, allow_nan=False)
    with pytest.raises(
        bridge.BridgeInputError,
        match=f"{column} must be finite numeric",
    ):
        bridge_inputs.records(frame, table_key)


@pytest.mark.parametrize(
    "invalid",
    [
        "yes",
        1,
        0.0,
        float("inf"),
        10 ** 4000,
        complex(1.0, -2.0),
    ],
)
def test_bridge_boolean_cell_retains_invalid_identity(invalid):
    table_key = bridge_inputs.MINIMUM_CRACK_TABLE_KEY
    row = dict(_RAW_BOUNDARY_ROWS[table_key])
    row["restrained_shrinkage"] = invalid
    expected = bridge_inputs.table_signature([row], table_key)

    frame = bridge_inputs.normalise_table([row], table_key)
    frame = bridge_inputs.normalise_table(frame, table_key)
    encoded = bridge_inputs.project_cell(
        frame.loc[0, "restrained_shrinkage"],
        table_key,
        "restrained_shrinkage",
    )

    assert bridge_inputs.table_signature(frame, table_key) == expected
    json.dumps(encoded, allow_nan=False)
    with pytest.raises(ValueError, match="restrained_shrinkage must be Boolean"):
        bridge_inputs.records(frame, table_key)


def test_bridge_table_signature_preserves_the_valid_legacy_shape():
    table_key = bridge_inputs.BOX_WALL_TABLE_KEY

    assert bridge_inputs.table_signature(
        [_RAW_BOUNDARY_ROWS[table_key]],
        table_key,
    ) == (("W1", 1.5, 50.0, 100.0, 10.0, 100.0),)


def test_bridge_rows_are_materialised_once_and_duplicate_columns_fail():
    table_key = bridge_inputs.BOX_WALL_TABLE_KEY
    rows = (row for row in [_RAW_BOUNDARY_ROWS[table_key]])

    assert bridge_inputs.records(rows, table_key)[0]["wall_id"] == "W1"

    duplicate = pd.DataFrame(
        [["W1", "W2"]],
        columns=["wall_id", "wall_id"],
    )
    with pytest.raises(ValueError, match="duplicate columns"):
        bridge_inputs.normalise_table(duplicate, table_key)


def test_bridge_column_order_defaults_unknowns_and_non_tabular_input_are_pinned():
    table_key = bridge_inputs.BOX_WALL_TABLE_KEY
    frame = bridge_inputs.normalise_table(
        [{"v_ed_kn": 50.0, "wall_id": "W1", "outside": "discarded"}],
        table_key,
    )

    assert tuple(frame.columns) == bridge_inputs.TABLE_COLUMNS[table_key]
    assert "outside" not in frame
    assert bridge_inputs.records([{"outside": "discarded"}], table_key) == []
    with pytest.raises(ValueError, match="must be tabular"):
        bridge_inputs.normalise_table(1.0, table_key)


def test_pr13a1a_r2_acceptance_contract_is_frozen():
    text = (
        ROOT / "docs" / "pr13a1a_r2_f013_bridge_raw_boundary_acceptance.md"
    ).read_text(encoding="utf-8")

    for marker in (
        "89fbc4a9713727093f453d0af7ffdce2dae17393",
        "Scalar pandas-null blanks",
        "bridge-specific project encoding",
        "materialized exactly once",
        "No bridge formula",
        "typed kernel/result adapter",
        "v0.93",
    ):
        assert marker in text


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
