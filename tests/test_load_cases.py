"""Load-case table schema, validation and legacy-adapter tests."""

from __future__ import annotations

import json
import pathlib
import sys

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import load_cases as lc  # noqa: E402


def test_legacy_scalars_migrate_to_typed_solver_tables():
    tables = lc.tables_from_legacy_scalars({
        "pl_case_id": "ALS-02",
        "pl_case_type": "Accidental combination",
        "pl_case_source": "Model envelope E4",
        "pl_P": -1250.0,
        "pl_Mx": 325.0,
        "pl_My": -40.0,
        "shear_V": -85.0,
        "torsion_T": 12.5,
        "el_case_id": "SLS-FREQ",
        "el_case_type": "Frequent",
        "el_long_P": 100.0,
        "el_long_Mx": 80.0,
        "el_short_My": -22.0,
        "sls_conc_limit_pct": 60.0,
        "sls_steel_limit_pct": 0.0,
        "sls_pre_limit_pct": 0.0,
        "sls_cw": True,
    })

    plastic = tables[lc.PLASTIC_TABLE_KEY]
    assert list(plastic.columns) == list(lc.PLASTIC_COLUMNS)
    assert plastic.loc[0, "name"] == "ALS-02"
    assert plastic.loc[0, "description"] == (
        "Accidental combination | Source: Model envelope E4"
    )
    assert plastic.loc[0, "n_ed_kn"] == -1250.0
    assert plastic.loc[0, "v_ed_kn"] == -85.0
    assert plastic.loc[0, "t_ed_knm"] == 12.5

    elastic = tables[lc.ELASTIC_TABLE_KEY]
    assert list(elastic.columns) == list(lc.ELASTIC_COLUMNS)
    assert elastic.loc[0, "name"] == "SLS-FREQ"
    assert elastic.loc[0, "n_long_ed_kn"] == 100.0
    assert elastic.loc[0, "my_short_ed_knm"] == -22.0
    assert bool(elastic.loc[0, "check_stress"]) is True
    assert bool(elastic.loc[0, "check_crack_width"]) is True


def test_case_records_roundtrip_signed_values_text_and_flags_without_nan():
    source = pd.DataFrame([
        {
            "name": "EL-CHAR",
            "description": "Characteristic stress check",
            "n_long_ed_kn": -5.0,
            "mx_long_ed_knm": 10.0,
            "my_long_ed_knm": 0.0,
            "n_short_ed_kn": 2.0,
            "mx_short_ed_knm": -3.0,
            "my_short_ed_knm": 4.0,
            "check_stress": True,
            "check_crack_width": False,
        }
    ])
    records = lc.table_records(source, lc.ELASTIC_TABLE_KEY)
    encoded = json.dumps(records, allow_nan=False)
    assert "NaN" not in encoded
    restored = lc.table_from_records(json.loads(encoded), lc.ELASTIC_TABLE_KEY)
    pd.testing.assert_frame_equal(
        restored,
        lc.normalise_table(source, lc.ELASTIC_TABLE_KEY),
        check_dtype=True,
    )


def test_validation_requires_globally_unique_names_and_finite_forces():
    plastic = lc.normalise_table([
        {"name": "Case A", "mx_ed_knm": 10.0},
        {"name": "", "n_ed_kn": "not a number", "mx_ed_knm": 4.0},
    ], lc.PLASTIC_TABLE_KEY)
    elastic = lc.normalise_table([
        {"name": "case a", "check_stress": True},
    ], lc.ELASTIC_TABLE_KEY)
    errors = lc.validation_errors(
        plastic, elastic, require_plastic=True, require_elastic=True
    )
    assert any("duplicated" in error for error in errors)
    assert any("Plastic row 2: Name is required" in error for error in errors)
    assert any("must be a finite number" in error for error in errors)


def test_completely_blank_editor_rows_are_ignored():
    plastic = pd.DataFrame([
        {"name": "PL-01", "mx_ed_knm": 5.0},
        {"name": "", "description": "", "n_ed_kn": 0.0},
    ])
    active = lc.active_table(plastic, lc.PLASTIC_TABLE_KEY)
    assert active["name"].tolist() == ["PL-01"]
    assert lc.validation_errors(active, lc.empty_table(lc.ELASTIC_TABLE_KEY)) == []


def test_invalid_numeric_only_row_is_not_mistaken_for_blank():
    plastic = lc.normalise_table([
        {"name": "", "n_ed_kn": "not a number"},
    ], lc.PLASTIC_TABLE_KEY)

    errors = lc.validation_errors(plastic, lc.empty_table(lc.ELASTIC_TABLE_KEY))

    assert "Plastic row 1: Name is required" in errors
    assert "Plastic row 1: n_ed_kn must be a finite number" in errors


def test_legacy_overlay_updates_first_row_and_preserves_later_cases():
    existing = lc.normalise_table([
        {"name": "OLD", "mx_ed_knm": 1.0},
        {"name": "KEEP", "mx_ed_knm": 2.0},
    ], lc.PLASTIC_TABLE_KEY)
    updated = lc.overlay_legacy_head(existing, lc.PLASTIC_TABLE_KEY, {
        "pl_case_id": "CURRENT",
        "pl_Mx": 9.0,
    })
    assert updated["name"].tolist() == ["CURRENT", "KEEP"]
    assert updated["mx_ed_knm"].tolist() == [9.0, 2.0]


def test_first_rows_remain_available_through_legacy_scalar_adapter():
    tables = {
        lc.PLASTIC_TABLE_KEY: lc.normalise_table([
            {"name": "PL-X", "description": "Description", "n_ed_kn": -42.0,
             "mx_ed_knm": 1.0, "my_ed_knm": 2.0, "v_ed_kn": 3.0,
             "t_ed_knm": 4.0},
        ], lc.PLASTIC_TABLE_KEY),
        lc.ELASTIC_TABLE_KEY: lc.normalise_table([
            {"name": "EL-X", "description": "Elastic description",
             "n_long_ed_kn": 5.0, "mx_long_ed_knm": 6.0,
             "my_long_ed_knm": 7.0, "n_short_ed_kn": 8.0,
             "mx_short_ed_knm": 9.0, "my_short_ed_knm": 10.0,
             "check_stress": False, "check_crack_width": True},
        ], lc.ELASTIC_TABLE_KEY),
    }
    scalars = lc.legacy_scalars_from_tables(tables)
    assert scalars["pl_case_id"] == "PL-X"
    assert scalars["pl_case_type"] == "Description"
    assert scalars["pl_P"] == -42.0
    assert scalars["torsion_T"] == 4.0
    assert scalars["el_case_id"] == "EL-X"
    assert scalars["el_short_My"] == 10.0
    assert scalars["sls_cw"] is True
