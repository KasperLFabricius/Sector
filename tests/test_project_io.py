from __future__ import annotations

import copy
import json
import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import bridge_inputs
import fatigue_inputs
import load_cases
import project_io
import reinforcement_table

from sector import bridge, capacity, codes

_BRIDGE_PROJECT_ROWS = {
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


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (True, 1),
        (1, 1.0),
        ([1.0], (1.0,)),
        (np.float32(1.0), np.float64(1.0)),
        (np.array([1.0], dtype="float32"), np.array([1.0], dtype="float64")),
    ],
)
def test_result_fingerprint_retains_concrete_type(first, second):
    assert project_io.result_sha256(first) != project_io.result_sha256(second)


def test_result_fingerprint_is_order_independent_and_seals_every_mapping_field():
    first = {
        "b": pd.DataFrame({"x": [1.0], "label": ["one"]}),
        "a": {"value": -0.0},
    }
    reordered = {
        "a": {"value": -0.0},
        "b": pd.DataFrame({"x": [1.0], "label": ["one"]}),
    }
    assert project_io.result_sha256(first) == project_io.result_sha256(reordered)

    changed = copy.deepcopy(reordered)
    changed["a"]["retired_metadata"] = {"value": 1}
    assert project_io.result_sha256(changed) != project_io.result_sha256(first)
    assert project_io.result_sha256({"a": [1, True, -0.0]}) == (
        "39b6f6999c42d6fe396078a0a062e91fc58193bd96159099d9a88e96e41ab9f0"
    )


def _current_project():
    tables = {
        "corners_base": pd.DataFrame(
            {
                "x (mm)": [0.0, 500.0, 500.0, 0.0],
                "y (mm)": [0.0, 0.0, 800.0, 800.0],
            }
        ),
        "hole_base": pd.DataFrame(
            columns=["x (mm)", "y (mm)"], dtype="float64"
        ),
        "bars_base": reinforcement_table.empty_table(),
        "tendons_base": reinforcement_table.empty_table(),
        load_cases.PLASTIC_TABLE_KEY: load_cases.normalise_table(
            [{
                "name": "Only characteristic action",
                "description": "User label retained",
                "n_ed_kn": 123.5,
                "mx_ed_knm": -44.0,
                "my_ed_knm": 8.0,
                "vx_ed_kn": 9.0,
                "vy_ed_kn": -11.0,
                "vx_face": "negative",
                "vy_face": "positive",
                "t_ed_knm": 2.0,
                "check_minimum_reinforcement": False,
            }],
            load_cases.PLASTIC_TABLE_KEY,
        ),
        load_cases.ELASTIC_TABLE_KEY: load_cases.normalise_table(
            [{
                "name": "One Elastic action",
                "description": "No completeness inference",
                "n_long_ed_kn": 20.0,
                "mx_long_ed_knm": 30.0,
                "my_long_ed_knm": -12.0,
                "n_short_ed_kn": 3.0,
                "mx_short_ed_knm": 4.0,
                "my_short_ed_knm": 5.0,
                "calculate_crack_width": True,
            }],
            load_cases.ELASTIC_TABLE_KEY,
        ),
        fatigue_inputs.SPECTRUM_TABLE_KEY: (
            fatigue_inputs.empty_spectrum_table()
        ),
    }
    for key in bridge_inputs.TABLE_KEYS:
        tables[key] = bridge_inputs.empty_table(key)
    scalars = {
        "mode": "Both",
        "conc_gamma_c": 0.5,
        "mild_gamma_y": 2.0,
        "torsion_gamma_ct": 2.0,
        "bridge_standard": "Independent component calculations",
        "rep_proj_no": "P-001",
    }
    return tables, scalars


def test_current_schema_save_load_resave_retains_exact_inputs():
    tables, scalars = _current_project()
    first = project_io.dump_project(
        tables,
        scalars,
        app_version="0.91",
        revision="abc123",
    )
    loaded_tables, loaded_scalars = project_io.parse_project(first)
    second = project_io.dump_project(
        loaded_tables,
        loaded_scalars,
        app_version="0.91",
        revision="abc123",
    )

    assert loaded_scalars["conc_gamma_c"] == pytest.approx(0.5)
    assert loaded_scalars["mild_gamma_y"] == pytest.approx(2.0)
    assert loaded_scalars["torsion_gamma_ct"] == pytest.approx(2.0)
    assert (
        loaded_tables[load_cases.PLASTIC_TABLE_KEY].loc[0, "name"]
        == "Only characteristic action"
    )
    assert loaded_tables[load_cases.PLASTIC_TABLE_KEY].loc[
        0, "n_ed_kn"
    ] == pytest.approx(123.5)
    assert project_io.project_provenance(first)["input_hash_valid"] is True
    assert project_io.project_provenance(second)["input_hash_valid"] is True
    assert json.loads(first)["version"] == project_io.VERSION
    assert json.loads(second)["version"] == project_io.VERSION


@pytest.mark.parametrize(
    ("key", "label"),
    [
        *(
            ("shear_method", label)
            for label in capacity.SHEAR_METHODS
        ),
        *(
            ("torsion_method", label)
            for label in capacity.SHEAR_CODES
        ),
        *(
            ("combined_method", label)
            for label in capacity.SHEAR_CODES
        ),
    ],
)
def test_current_schema_retains_every_capacity_method_identity(key, label):
    tables, scalars = _current_project()
    scalars[key] = label

    first = project_io.dump_project(tables, scalars)
    loaded_tables, loaded_scalars = project_io.parse_project(first)
    second = project_io.dump_project(loaded_tables, loaded_scalars)
    _, reloaded_scalars = project_io.parse_project(second)

    assert loaded_scalars[key] == label
    assert reloaded_scalars[key] == label
    assert project_io.project_provenance(first)["input_hash_valid"] is True
    assert project_io.project_provenance(second)["input_hash_valid"] is True


@pytest.mark.parametrize(
    "key",
    ["shear_method", "torsion_method", "combined_method"],
)
@pytest.mark.parametrize(
    "invalid",
    [None, "", "unsupported method", True, 1, []],
)
def test_current_schema_rejects_present_unsupported_capacity_method(
    key,
    invalid,
):
    tables, scalars = _current_project()
    scalars[key] = invalid

    with pytest.raises(capacity.CapacityMethodError, match="unsupported"):
        project_io.dump_project(tables, scalars)


@pytest.mark.parametrize(
    ("key", "label"),
    [
        ("shear_method", codes.EC2_2005_DKNA.label),
        ("torsion_method", codes.EC2_2005.label),
        ("combined_method", codes.EC2_2005_DKNA.label),
    ],
)
def test_current_loader_rejects_coherently_rehashed_unsupported_method(
    key,
    label,
):
    tables, scalars = _current_project()
    scalars[key] = label
    data = json.loads(project_io.dump_project(tables, scalars))
    data["scalars"][key] = "unsupported method"
    data["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": data["tables"],
        "scalars": data["scalars"],
    })

    with pytest.raises(capacity.CapacityMethodError, match="unsupported"):
        project_io.parse_project(json.dumps(data))


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
def test_current_project_round_trips_every_invalid_bridge_numeric_cell(
    table_key,
    column,
    invalid,
):
    tables, scalars = _current_project()
    row = dict(_BRIDGE_PROJECT_ROWS[table_key])
    row[column] = invalid
    tables[table_key] = [row]
    expected = bridge_inputs.table_signature([row], table_key)

    first = project_io.dump_project(tables, scalars)
    loaded, loaded_scalars = project_io.parse_project(first)
    second = project_io.dump_project(loaded, loaded_scalars)
    reloaded, _ = project_io.parse_project(second)

    assert project_io.project_provenance(first)["input_hash_valid"] is True
    assert project_io.project_provenance(second)["input_hash_valid"] is True
    assert bridge_inputs.table_signature(loaded[table_key], table_key) == expected
    assert bridge_inputs.table_signature(reloaded[table_key], table_key) == expected
    with pytest.raises(
        bridge.BridgeInputError,
        match=f"{column} must be finite numeric",
    ):
        bridge_inputs.records(reloaded[table_key], table_key)


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
def test_current_project_round_trips_invalid_bridge_boolean_identity(invalid):
    table_key = bridge_inputs.MINIMUM_CRACK_TABLE_KEY
    tables, scalars = _current_project()
    row = dict(_BRIDGE_PROJECT_ROWS[table_key])
    row["restrained_shrinkage"] = invalid
    tables[table_key] = [row]
    expected = bridge_inputs.table_signature([row], table_key)

    text = project_io.dump_project(tables, scalars)
    loaded, _ = project_io.parse_project(text)

    assert project_io.project_provenance(text)["input_hash_valid"] is True
    assert bridge_inputs.table_signature(loaded[table_key], table_key) == expected
    with pytest.raises(
        bridge.BridgeInputError,
        match="restrained_shrinkage must be Boolean",
    ):
        bridge_inputs.records(loaded[table_key], table_key)


def test_current_project_keeps_scalar_pandas_bridge_blanks_inert():
    tables, scalars = _current_project()
    for table_key in bridge_inputs.TABLE_KEYS:
        tables[table_key] = [{
            column: pd.NA
            for column in bridge_inputs.TABLE_COLUMNS[table_key]
        }]

    text = project_io.dump_project(tables, scalars)
    loaded, _ = project_io.parse_project(text)

    assert project_io.project_provenance(text)["input_hash_valid"] is True
    for table_key in bridge_inputs.TABLE_KEYS:
        assert bridge_inputs.records(loaded[table_key], table_key) == []


def test_bridge_project_loader_rejects_duplicate_columns_before_mapping():
    key = bridge_inputs.BRITTLE_TABLE_KEY
    with pytest.raises(ValueError, match="contains duplicate columns"):
        project_io._obj_to_table({
            "columns": ["region_id", "region_id"],
            "rows": [["R1", "R2"]],
        }, key)


@pytest.mark.parametrize("row", [["R1"], "R1", {"region_id": "R1"}])
def test_bridge_project_loader_rejects_wrong_row_cardinality(row):
    key = bridge_inputs.BRITTLE_TABLE_KEY
    with pytest.raises(ValueError, match="rows are not tabular"):
        project_io._obj_to_table({
            "columns": list(bridge_inputs.TABLE_COLUMNS[key]),
            "rows": [row],
        }, key)


def test_encoded_invalid_bridge_identity_is_covered_by_the_project_hash():
    table_key = bridge_inputs.BOX_WALL_TABLE_KEY
    tables, scalars = _current_project()
    row = dict(_BRIDGE_PROJECT_ROWS[table_key])
    row["cot_theta"] = float("inf")
    tables[table_key] = [row]
    data = json.loads(project_io.dump_project(tables, scalars))
    column = data["tables"][table_key]["columns"].index("cot_theta")
    cell = data["tables"][table_key]["rows"][0][column]
    cell["__sector_bridge_invalid_cell_v1__"]["representation"] = (
        "negative_infinity"
    )

    with pytest.raises(ValueError, match="hash mismatch"):
        project_io.parse_project(json.dumps(data))


def test_corrupt_current_input_is_rejected_by_hash():
    tables, scalars = _current_project()
    data = json.loads(project_io.dump_project(tables, scalars))
    data["scalars"]["conc_gamma_c"] = 2.0

    with pytest.raises(ValueError, match="hash mismatch"):
        project_io.parse_project(json.dumps(data))


def test_older_schema_is_explicitly_unsupported():
    tables, scalars = _current_project()
    data = json.loads(project_io.dump_project(tables, scalars))
    data["version"] = project_io.VERSION - 1

    with pytest.raises(ValueError, match="only current schema"):
        project_io.parse_project(json.dumps(data))


def test_obsolete_compliance_and_approval_inputs_are_not_in_schema():
    forbidden = {
        "checker",
        "approver",
        "infrastructure_manager",
        "asset_class",
        "project_basis",
        "cover_calculator",
        "approval_reference",
        "sls_crack_limit",
        "check_stress",
        "multidirectional_interaction",
    }
    joined = "\n".join(project_io.SCALAR_KEYS)
    assert not any(name in joined for name in forbidden)


def test_calculation_record_is_correlated_but_results_are_not_persisted():
    tables, scalars = _current_project()
    digest = project_io.input_sha256(tables, scalars)
    text = project_io.dump_project(
        tables,
        scalars,
        calculation={
            "performed_at_utc": "2026-07-29T12:00:00+00:00",
            "sector_version": "0.91",
            "source_revision": "abc123",
            "input_sha256": digest,
            "result_sha256": "f" * 64,
        },
    )
    provenance = project_io.project_provenance(text)

    assert provenance["results_included"] is False
    assert provenance["calculation"]["matches_saved_inputs"] is True
    assert provenance["calculation"]["result_sha256"] == "f" * 64

    with pytest.raises(ValueError, match="result_sha256"):
        project_io.dump_project(
            tables,
            scalars,
            calculation={"input_sha256": digest, "result_sha256": "not-a-hash"},
        )


def test_nonpositive_factor_is_rejected_but_positive_custom_values_are_not():
    tables, scalars = _current_project()
    for value in (0.5, 2.0):
        custom = dict(scalars, conc_gamma_c=value)
        _, loaded = project_io.parse_project(
            project_io.dump_project(tables, custom)
        )
        assert loaded["conc_gamma_c"] == pytest.approx(value)
    with pytest.raises(ValueError, match="positive finite"):
        project_io.dump_project(tables, dict(scalars, conc_gamma_c=0.0))


@pytest.mark.parametrize("value", [0.5, 2.0])
def test_current_schema_retains_direct_torsion_tensile_factor(value):
    tables, scalars = _current_project()
    scalars.update(torsion_on=True, torsion_gamma_ct=value)

    text = project_io.dump_project(tables, scalars)
    _, loaded = project_io.parse_project(text)

    assert loaded["torsion_gamma_ct"] == pytest.approx(value)


@pytest.mark.parametrize(
    "value", [True, False, 0.0, -1.0, float("inf"), float("-inf"), float("nan")]
)
def test_current_schema_rejects_invalid_torsion_tensile_factor(value):
    tables, scalars = _current_project()
    scalars.update(torsion_on=True, torsion_gamma_ct=value)

    with pytest.raises(ValueError, match="positive finite real"):
        project_io.dump_project(tables, scalars)


def test_current_schema_requires_torsion_tensile_factor_when_active():
    tables, scalars = _current_project()
    scalars["torsion_on"] = True
    scalars.pop("torsion_gamma_ct")

    with pytest.raises(ValueError, match="torsion_gamma_ct is required"):
        project_io.dump_project(tables, scalars)
