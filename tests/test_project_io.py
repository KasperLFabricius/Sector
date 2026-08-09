from __future__ import annotations

import copy
import json
import pathlib
import re
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import fatigue_inputs
import load_cases
import material_catalog
import project_io
import reinforcement_table

from sector import capacity, codes, design_standards


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
    scalars = {
        "mode": "Both",
        "conc_gamma_c": 0.5,
        "mild_gamma_y": 2.0,
        "torsion_gamma_ct": 2.0,
        "fatigue_edition": (
            design_standards.DesignBasisKey.FIRST_GEN_DK_NA_2024.value
        ),
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
    assert loaded_scalars["fatigue_edition"] == (
        design_standards.DesignBasisKey.FIRST_GEN_DK_NA_2024.value
    )
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


def test_project_round_trip_preserves_decimal_precision_and_blank_action_zero():
    tables, scalars = _current_project()
    tables[load_cases.PLASTIC_TABLE_KEY] = load_cases.normalise_table(
        [{
            "name": "Decimal input",
            "n_ed_kn": "1,23456789012345",
            "mx_ed_knm": "",
        }],
        load_cases.PLASTIC_TABLE_KEY,
    )

    text = project_io.dump_project(tables, scalars)
    loaded, _loaded_scalars = project_io.parse_project(text)
    row = loaded[load_cases.PLASTIC_TABLE_KEY].iloc[0]

    assert row["n_ed_kn"] == pytest.approx(1.23456789012345)
    assert row["mx_ed_knm"] == 0.0
    assert project_io.project_provenance(text)["input_hash_valid"] is True


@pytest.mark.parametrize(
    ("table_key", "row", "match"),
    [
        (
            load_cases.ELASTIC_TABLE_KEY,
            {"name": "Bad", "mx_short_ed_knm": "12abc"},
            "elastic_cases_base row 1: mx_short_ed_knm",
        ),
        (
            fatigue_inputs.SPECTRUM_TABLE_KEY,
            {
                "spectrum": "Traffic",
                "name": "Bad bin",
                "cycles": "10",
                "n_short_ed_kn": "12abc",
            },
            "fatigue_spectrum_base row 1: n_short_ed_kn",
        ),
    ],
)
def test_project_dump_rejects_malformed_nonblank_decimal_without_json_null(
    table_key, row, match
):
    tables, scalars = _current_project()
    tables[table_key] = (
        load_cases.normalise_table([row], table_key)
        if table_key in load_cases.CASE_TABLE_KEYS
        else fatigue_inputs.normalise_spectrum_table([row])
    )

    with pytest.raises(ValueError, match=match):
        project_io.dump_project(tables, scalars)


@pytest.mark.parametrize(
    ("table_key", "column", "entered"),
    [
        (load_cases.PLASTIC_TABLE_KEY, "n_ed_kn", "12abc"),
        (load_cases.ELASTIC_TABLE_KEY, "mx_short_ed_knm", True),
        (fatigue_inputs.SPECTRUM_TABLE_KEY, "cycles", "10 cycles"),
    ],
)
def test_project_parse_rejects_hash_valid_malformed_nonblank_decimal(
    table_key,
    column,
    entered,
):
    tables, scalars = _current_project()
    if table_key == fatigue_inputs.SPECTRUM_TABLE_KEY:
        tables[table_key] = fatigue_inputs.normalise_spectrum_table(
            [{"spectrum": "Traffic", "name": "Bin 1", "cycles": 10.0}]
        )
    data = json.loads(project_io.dump_project(tables, scalars))
    encoded = data["tables"][table_key]
    encoded["rows"][0][encoded["columns"].index(column)] = entered
    data["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": data["tables"],
        "scalars": data["scalars"],
    })

    with pytest.raises(
        ValueError,
        match=rf"{re.escape(table_key)} row 1: {re.escape(column)} contains "
        r"malformed decimal input",
    ):
        project_io.parse_project(json.dumps(data))


def test_project_dump_allows_a_wholly_blank_fatigue_editor_row():
    tables, scalars = _current_project()
    tables[fatigue_inputs.SPECTRUM_TABLE_KEY] = (
        fatigue_inputs.normalise_spectrum_table([{}])
    )

    text = project_io.dump_project(tables, scalars)
    loaded, _loaded_scalars = project_io.parse_project(text)

    assert len(loaded[fatigue_inputs.SPECTRUM_TABLE_KEY]) == 1
    assert pd.isna(
        loaded[fatigue_inputs.SPECTRUM_TABLE_KEY].loc[0, "cycles"]
    )


@pytest.mark.parametrize(
    ("table_key", "kind", "assigned_id", "catalog_key", "catalog"),
    [
        (
            "bars_base",
            "bar",
            "M2",
            material_catalog.MILD_CATALOG_KEY,
            {
                "items": [
                    material_catalog.default_entry("mild", material_id="M1"),
                    material_catalog.default_entry("mild", material_id="bad"),
                ]
            },
        ),
        (
            "tendons_base",
            "tendon",
            "P2",
            material_catalog.PRESTRESS_CATALOG_KEY,
            {
                "items": [
                    material_catalog.default_entry(
                        "prestress", material_id="P1"
                    ),
                    material_catalog.default_entry(
                        "prestress", material_id="bad"
                    ),
                ]
            },
        ),
    ],
)
def test_project_catalog_repair_never_rebinds_assigned_material_gap(
    table_key, kind, assigned_id, catalog_key, catalog
):
    tables, scalars = _current_project()
    tables[table_key] = reinforcement_table.normalise_table(
        [{
            reinforcement_table.X: 0.0,
            reinforcement_table.Y: 0.0,
            reinforcement_table.SIZE_MODE: reinforcement_table.AREA_MODE,
            reinforcement_table.AREA: 100.0,
            reinforcement_table.MATERIAL_ID: assigned_id,
        }],
        kind,
    )
    scalars[catalog_key] = catalog

    with pytest.raises(ValueError, match=assigned_id):
        project_io.dump_project(tables, scalars)


def test_project_catalog_repair_never_rebinds_active_capacity_material_gap():
    tables, scalars = _current_project()
    scalars.update(
        shear_on=True,
        capacity_steel_material_id="M2",
        mild_material_catalog={
            "items": [
                material_catalog.default_entry("mild", material_id="M1"),
                material_catalog.default_entry("mild", material_id="bad"),
            ]
        },
    )

    with pytest.raises(ValueError, match="M2"):
        project_io.dump_project(tables, scalars)


def test_project_catalog_repair_never_rebinds_assigned_fatigue_gap():
    tables, scalars = _current_project()
    tables["bars_base"] = reinforcement_table.normalise_table(
        [{
            reinforcement_table.X: 0.0,
            reinforcement_table.Y: 0.0,
            reinforcement_table.SIZE_MODE: reinforcement_table.AREA_MODE,
            reinforcement_table.AREA: 100.0,
            reinforcement_table.MATERIAL_ID: "M1",
            reinforcement_table.FATIGUE_DETAIL_ID: "F2",
        }],
        "bar",
    )
    scalars[material_catalog.MILD_CATALOG_KEY] = (
        material_catalog.default_catalog("mild")
    )
    scalars[fatigue_inputs.DETAIL_CATALOG_KEY] = {
        "items": [
            fatigue_inputs.default_entry(detail_id="F1"),
            fatigue_inputs.default_entry(detail_id="bad"),
        ]
    }

    with pytest.raises(ValueError, match="F2"):
        project_io.dump_project(tables, scalars)


def test_parse_rejects_hash_valid_project_with_missing_assigned_material():
    tables, scalars = _current_project()
    tables["bars_base"] = reinforcement_table.normalise_table(
        [{
            reinforcement_table.X: 0.0,
            reinforcement_table.Y: 0.0,
            reinforcement_table.SIZE_MODE: reinforcement_table.AREA_MODE,
            reinforcement_table.AREA: 100.0,
            reinforcement_table.MATERIAL_ID: "M1",
        }],
        "bar",
    )
    scalars[material_catalog.MILD_CATALOG_KEY] = (
        material_catalog.default_catalog("mild")
    )
    data = json.loads(project_io.dump_project(tables, scalars))
    bar_table = data["tables"]["bars_base"]
    material_column = bar_table["columns"].index(
        reinforcement_table.MATERIAL_ID
    )
    bar_table["rows"][0][material_column] = "M2"
    data["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": data["tables"],
        "scalars": data["scalars"],
    })

    with pytest.raises(ValueError, match="M2"):
        project_io.parse_project(json.dumps(data))


def test_parse_rejects_hash_valid_project_with_missing_capacity_material():
    tables, scalars = _current_project()
    scalars.update(shear_on=True, capacity_steel_material_id="M1")
    scalars[material_catalog.MILD_CATALOG_KEY] = (
        material_catalog.default_catalog("mild")
    )
    data = json.loads(project_io.dump_project(tables, scalars))
    data["scalars"]["capacity_steel_material_id"] = "M2"
    data["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": data["tables"],
        "scalars": data["scalars"],
    })

    with pytest.raises(ValueError, match="M2"):
        project_io.parse_project(json.dumps(data))


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


def test_corrupt_current_input_is_rejected_by_hash():
    tables, scalars = _current_project()
    data = json.loads(project_io.dump_project(tables, scalars))
    data["scalars"]["conc_gamma_c"] = 2.0

    with pytest.raises(ValueError, match="hash mismatch"):
        project_io.parse_project(json.dumps(data))


def test_schema_23_fails_first_with_the_exact_current_only_message():
    text = json.dumps({
        "format": project_io.FORMAT,
        "version": 23,
        "tables": "deliberately malformed",
        "scalars": None,
    })

    for reader in (project_io.project_provenance, project_io.parse_project):
        with pytest.raises(ValueError) as caught:
            reader(text)
        assert str(caught.value) == project_io.V23_UNSUPPORTED_MESSAGE


def test_noncurrent_non_v23_schema_uses_the_generic_current_only_message():
    text = json.dumps({"format": project_io.FORMAT, "version": 22})

    with pytest.raises(
        ValueError,
        match=r"unsupported Sector project schema 22; only current schema 24",
    ):
        project_io.parse_project(text)


def test_schema_24_serialization_contains_no_retired_bridge_inputs():
    tables, scalars = _current_project()
    tables.update({
        "bridge_brittle_base": {"retired": True},
        "bridge_box_walls_base": {"retired": True},
        "bridge_minimum_crack_base": {"retired": True},
    })
    scalars["bridge_standard"] = "retired"

    data = json.loads(project_io.dump_project(tables, scalars))

    assert data["version"] == 24
    assert set(data["tables"]) == set(project_io.PROJECT_TABLE_KEYS)
    assert not {
        "bridge_brittle_base",
        "bridge_box_walls_base",
        "bridge_minimum_crack_base",
    }.intersection(data["tables"])
    assert "bridge_standard" not in data["scalars"]
    assert not hasattr(project_io, "BRIDGE_TABLE_KEYS")


@pytest.mark.parametrize(
    "retired_table",
    (
        "bridge_brittle_base",
        "bridge_box_walls_base",
        "bridge_minimum_crack_base",
    ),
)
def test_rehashed_schema_24_rejects_each_retired_table_as_unknown(
    retired_table,
):
    tables, scalars = _current_project()
    data = json.loads(project_io.dump_project(tables, scalars))
    data["tables"][retired_table] = {"columns": [], "rows": []}
    data["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": data["tables"],
        "scalars": data["scalars"],
    })

    with pytest.raises(
        ValueError,
        match=rf"^unknown current-schema tables: {re.escape(retired_table)}$",
    ):
        project_io.parse_project(json.dumps(data))


def test_rehashed_schema_24_rejects_retired_bridge_scalar_as_unknown():
    tables, scalars = _current_project()
    data = json.loads(project_io.dump_project(tables, scalars))
    data["scalars"]["bridge_standard"] = "retired"
    data["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": data["tables"],
        "scalars": data["scalars"],
    })

    with pytest.raises(
        ValueError,
        match=r"^unknown current-schema inputs: bridge_standard$",
    ):
        project_io.parse_project(json.dumps(data))


@pytest.mark.parametrize("basis_key", tuple(design_standards.DesignBasisKey))
def test_fatigue_edition_round_trips_only_as_a_registered_basis_key(basis_key):
    tables, scalars = _current_project()
    scalars["fatigue_edition"] = basis_key.value

    text = project_io.dump_project(tables, scalars)
    _, loaded = project_io.parse_project(text)

    assert loaded["fatigue_edition"] == basis_key.value
    assert json.loads(text)["scalars"]["fatigue_edition"] == basis_key.value


@pytest.mark.parametrize(
    "invalid",
    (
        "DS/EN 1992-1-1:2005",
        "DS/EN 1992-1-1:2005 + DK NA:2024",
        "DS/EN 1992-1-1:2023",
        "ec2_1_1_2023_published ",
        "",
        None,
    ),
)
def test_fatigue_edition_rejects_labels_legacy_tokens_and_near_matches(
    invalid,
):
    tables, scalars = _current_project()
    scalars["fatigue_edition"] = invalid

    with pytest.raises(ValueError, match="registered basis keys"):
        project_io.dump_project(tables, scalars)


def test_rehashed_schema_24_rejects_an_unregistered_fatigue_edition():
    tables, scalars = _current_project()
    data = json.loads(project_io.dump_project(tables, scalars))
    data["scalars"]["fatigue_edition"] = "DS/EN 1992-1-1:2023"
    data["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": data["tables"],
        "scalars": data["scalars"],
    })

    with pytest.raises(ValueError, match="registered basis keys"):
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
        "bridge_standard",
        "design_basis",
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
