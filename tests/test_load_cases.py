import math
import pathlib
import sys

import pandas as pd
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import load_cases


def test_default_tables_are_current_output_only_schema():
    tables = load_cases.default_tables()
    elastic = tables[load_cases.ELASTIC_TABLE_KEY]

    assert tuple(elastic.columns) == load_cases.ELASTIC_COLUMNS
    assert "calculate_crack_width" in elastic
    assert "ordinary_crack_criterion_mm" not in elastic
    assert "check_stress" not in elastic
    assert "check_crack_width" not in elastic
    assert not any("limit" in column for column in elastic.columns)


def test_legacy_ordinary_crack_criterion_is_not_action_table_state():
    elastic = load_cases.normalise_table(
        [{
            "name": "EL-ordinary",
            "calculate_crack_width": False,
            "ordinary_crack_criterion_mm": "0,30",
        }],
        load_cases.ELASTIC_TABLE_KEY,
    )

    assert tuple(elastic.columns) == load_cases.ELASTIC_COLUMNS
    assert "ordinary_crack_criterion_mm" not in elastic
    assert load_cases.validation_errors(
        load_cases.empty_table(load_cases.PLASTIC_TABLE_KEY), elastic
    ) == []
    record = load_cases.table_records(
        elastic, load_cases.ELASTIC_TABLE_KEY
    )[0]
    assert "ordinary_crack_criterion_mm" not in record
    assert record["calculate_crack_width"] is False


def test_any_single_named_characteristic_action_is_valid():
    elastic = load_cases.normalise_table(
        [{
            "name": "Only characteristic case",
            "description": "User-defined action set",
            "n_long_ed_kn": 125.0,
            "mx_long_ed_knm": 22.0,
            "my_long_ed_knm": -8.0,
            "n_short_ed_kn": 0.0,
            "mx_short_ed_knm": 0.0,
            "my_short_ed_knm": 0.0,
            "calculate_crack_width": True,
        }],
        load_cases.ELASTIC_TABLE_KEY,
    )

    assert load_cases.validation_errors(
        load_cases.empty_table(load_cases.PLASTIC_TABLE_KEY),
        elastic,
        require_elastic=True,
    ) == []
    record = load_cases.table_records(
        elastic, load_cases.ELASTIC_TABLE_KEY
    )[0]
    assert record["name"] == "Only characteristic case"
    assert record["calculate_crack_width"] is True
    assert record["n_long_ed_kn"] == pytest.approx(125.0)


def test_independent_vx_vy_values_and_faces_roundtrip():
    plastic = load_cases.normalise_table(
        [{
            "name": "P1",
            "description": "signed directions",
            "n_ed_kn": 0.0,
            "mx_ed_knm": 20.0,
            "my_ed_knm": -30.0,
            "vx_ed_kn": -40.0,
            "vy_ed_kn": 55.0,
            "vx_face": "left",
            "vy_face": "top",
            "t_ed_knm": 0.0,
            "check_minimum_reinforcement": False,
        }],
        load_cases.PLASTIC_TABLE_KEY,
    )
    record = load_cases.table_records(
        plastic, load_cases.PLASTIC_TABLE_KEY
    )[0]

    assert record["vx_ed_kn"] == pytest.approx(-40.0)
    assert record["vy_ed_kn"] == pytest.approx(55.0)
    assert record["vx_face"] == load_cases.FACE_NEGATIVE
    assert record["vy_face"] == load_cases.FACE_POSITIVE


def test_malformed_active_numeric_value_is_rejected_not_replaced():
    elastic = pd.DataFrame([{
        "name": "E1",
        "mx_long_ed_knm": "not-a-number",
    }])
    normalised = load_cases.normalise_table(
        elastic, load_cases.ELASTIC_TABLE_KEY
    )
    assert math.isnan(normalised.loc[0, "mx_long_ed_knm"])
    with pytest.raises(ValueError, match="finite number"):
        load_cases.table_records(
            normalised, load_cases.ELASTIC_TABLE_KEY
        )


def test_duplicate_names_are_rejected_across_action_families():
    plastic = load_cases.normalise_table(
        [{"name": "same"}], load_cases.PLASTIC_TABLE_KEY
    )
    elastic = load_cases.normalise_table(
        [{"name": "SAME"}], load_cases.ELASTIC_TABLE_KEY
    )
    assert any(
        "duplicated" in error
        for error in load_cases.validation_errors(plastic, elastic)
    )
