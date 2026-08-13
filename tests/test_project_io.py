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

from app import modelled_direction
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
        "sls_code": (
            design_standards.DesignBasisKey.FIRST_GEN_DK_NA_2024.value
        ),
        "fatigue_edition": (
            design_standards.DesignBasisKey.FIRST_GEN_DK_NA_2024.value
        ),
        "sls_permitted_crack_width_mm": None,
        "rep_proj_no": "P-001",
    }
    return tables, scalars


def _heightened_inputs() -> dict[str, object]:
    return {
        "sls_heightened_on": True,
        "sls_heightened_reference_case": "One Elastic action",
        "sls_heightened_reinforcement_surface": "ribbed",
        "sls_heightened_effective_tensile_strength_mpa": 2.9,
        "sls_permitted_crack_width_mm": 0.2,
        "sls_heightened_fine_effective_tension_area_mm2": 120_000.0,
        "sls_heightened_coarse_effective_tension_area_mm2": 180_000.0,
    }


_MISSING = object()


def _schema24_payload(
    tables=None,
    scalars=None,
    *,
    criteria=None,
    heightened_width=_MISSING,
):
    """Build an integrity-valid legacy payload from current test inputs."""

    if tables is None or scalars is None:
        tables, scalars = _current_project()
    payload = json.loads(project_io.dump_project(tables, scalars))
    payload["version"] = project_io.MIGRATABLE_VERSION
    payload["scalars"].pop("sls_permitted_crack_width_mm", None)
    elastic = payload["tables"][load_cases.ELASTIC_TABLE_KEY]
    elastic["columns"].append(project_io.LEGACY_ORDINARY_CRACK_WIDTH_KEY)
    values = list(criteria or [None] * len(elastic["rows"]))
    assert len(values) == len(elastic["rows"])
    for row, criterion in zip(elastic["rows"], values, strict=True):
        row.append(criterion)
    if heightened_width is not _MISSING:
        payload["scalars"][
            project_io.LEGACY_HEIGHTENED_CRACK_WIDTH_KEY
        ] = heightened_width
    payload["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": payload["tables"],
        "scalars": payload["scalars"],
    })
    return payload


def _legacy_heightened_schema25_payload(tables=None) -> dict:
    """Build one integrity-valid pre-PR06 schema-25 heightened payload."""

    if tables is None:
        tables, scalars = _current_project()
    else:
        _, scalars = _current_project()
    scalars.update(_heightened_inputs())
    payload = json.loads(project_io.dump_project(tables, scalars))
    persisted = payload["scalars"]
    persisted.pop("sls_heightened_reference_case", None)
    persisted.pop("sls_heightened_fine_effective_tension_area_mm2", None)
    persisted.pop("sls_heightened_coarse_effective_tension_area_mm2", None)
    persisted.update({
        "sls_heightened_crack_system": "fine",
        "sls_heightened_bar_diameter_mm": 16.0,
        "sls_heightened_reinforcement_modulus_mpa": 200_000.0,
        "sls_heightened_effective_tension_area_mm2": 120_000.0,
        "sls_heightened_provided_reinforcement_area_mm2": 2_500.0,
    })
    payload["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": payload["tables"],
        "scalars": persisted,
    })
    return payload


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


def test_schema_25_serializes_only_the_shared_analysis_criterion():
    tables, scalars = _current_project()
    scalars["sls_permitted_crack_width_mm"] = 0.30

    payload = json.loads(project_io.dump_project(tables, scalars))
    elastic = payload["tables"][load_cases.ELASTIC_TABLE_KEY]

    assert payload["version"] == 25
    assert tuple(elastic["columns"]) == load_cases.ELASTIC_COLUMNS
    assert project_io.LEGACY_ORDINARY_CRACK_WIDTH_KEY not in elastic["columns"]
    assert project_io.LEGACY_HEIGHTENED_CRACK_WIDTH_KEY not in payload["scalars"]
    assert payload["scalars"]["sls_permitted_crack_width_mm"] == 0.30


def test_schema_24_blank_criteria_migrate_to_unassessed_schema_25_state():
    payload = _schema24_payload(criteria=[None])
    source = json.dumps(payload)

    tables, scalars, info = project_io.parse_project_with_info(source)

    assert info["migrated"] is True
    assert info["source_schema_version"] == 24
    assert info["target_schema_version"] == 25
    assert info["migration_warnings"] == ()
    assert scalars["sls_permitted_crack_width_mm"] is None
    assert project_io.LEGACY_ORDINARY_CRACK_WIDTH_KEY not in tables[
        load_cases.ELASTIC_TABLE_KEY
    ]


def test_schema_24_disabled_heightened_zero_placeholder_migrates_as_blank():
    tables, scalars = _current_project()
    scalars["sls_heightened_on"] = False
    payload = _schema24_payload(
        tables,
        scalars,
        criteria=[None],
        heightened_width=0.0,
    )

    _tables, migrated, info = project_io.parse_project_with_info(
        json.dumps(payload)
    )

    assert migrated["sls_permitted_crack_width_mm"] is None
    assert info["migration_warnings"] == ()
    assert info["migration_provenance"] == {
        "criterion_sources": (),
        "selection_policy": "blank",
        "selected_value_mm": None,
    }


def test_schema_24_enabled_heightened_zero_is_rejected():
    tables, scalars = _current_project()
    scalars.update(_heightened_inputs())
    payload = _schema24_payload(
        tables,
        scalars,
        criteria=[None],
        heightened_width=0.0,
    )

    with pytest.raises(ValueError, match="must be a positive finite number"):
        project_io.parse_project(json.dumps(payload))


def test_schema_24_identical_criteria_migrate_directly_without_warning():
    payload = _schema24_payload(criteria=[0.30], heightened_width=0.30)

    _tables, scalars, info = project_io.parse_project_with_info(
        json.dumps(payload)
    )

    assert scalars["sls_permitted_crack_width_mm"] == pytest.approx(0.30)
    assert info["migration_warnings"] == ()
    migration = info["migration_provenance"]
    assert migration["selection_policy"] == "single-value"
    assert migration["selected_value_mm"] == pytest.approx(0.30)
    assert [item["source"] for item in migration["criterion_sources"]] == [
        "Elastic case One Elastic action",
        "Heightened crack control",
    ]


def test_schema_24_conflicts_use_conservative_minimum_warn_and_resave_clean():
    tables, scalars = _current_project()
    tables[load_cases.ELASTIC_TABLE_KEY] = load_cases.normalise_table(
        [
            {"name": "EL-A", "calculate_crack_width": True},
            {"name": "EL-B", "calculate_crack_width": False},
        ],
        load_cases.ELASTIC_TABLE_KEY,
    )
    payload = _schema24_payload(
        tables, scalars, criteria=[0.30, 0.25], heightened_width=0.20
    )
    source = json.dumps(payload)
    original = source[:]

    migrated_tables, migrated_scalars, info = (
        project_io.parse_project_with_info(source)
    )

    assert source == original
    assert project_io.project_provenance(source)["input_hash_valid"] is True
    assert migrated_scalars["sls_permitted_crack_width_mm"] == pytest.approx(
        0.20
    )
    assert info["migration_provenance"]["selection_policy"] == (
        "conservative-minimum"
    )
    assert len(info["migration_warnings"]) == 1
    assert "0.2 mm" in info["migration_warnings"][0]

    resaved = json.loads(
        project_io.dump_project(migrated_tables, migrated_scalars)
    )
    assert resaved["version"] == 25
    assert project_io.LEGACY_HEIGHTENED_CRACK_WIDTH_KEY not in (
        resaved["scalars"]
    )
    assert project_io.LEGACY_ORDINARY_CRACK_WIDTH_KEY not in resaved[
        "tables"
    ][load_cases.ELASTIC_TABLE_KEY]["columns"]


@pytest.mark.parametrize(
    ("location", "invalid"),
    (
        ("ordinary", True),
        ("ordinary", 0.0),
        ("ordinary", -0.1),
        ("ordinary", "NaN"),
        ("heightened", -0.1),
    ),
)
def test_schema_24_rejects_invalid_populated_criteria_even_when_inactive(
    location,
    invalid,
):
    payload = _schema24_payload(
        criteria=[invalid if location == "ordinary" else None],
        heightened_width=(invalid if location == "heightened" else _MISSING),
    )

    with pytest.raises(ValueError, match="must be a positive finite number"):
        project_io.parse_project(json.dumps(payload))


@pytest.mark.parametrize("mutation", ("extra", "reordered"))
def test_schema_24_rejects_every_nonexact_elastic_column_shape(mutation):
    data = _schema24_payload(criteria=[None])
    elastic = data["tables"][load_cases.ELASTIC_TABLE_KEY]
    if mutation == "extra":
        elastic["columns"].append("legacy_crack_limit")
        for row in elastic["rows"]:
            row.append(None)
    else:
        elastic["columns"][-2:] = reversed(elastic["columns"][-2:])
        for row in elastic["rows"]:
            row[-2:] = reversed(row[-2:])
    data["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": data["tables"],
        "scalars": data["scalars"],
    })

    with pytest.raises(ValueError, match="exact legacy Elastic columns"):
        project_io.parse_project(json.dumps(data))


def test_direction_alias_round_trips_outside_calculation_inputs():
    tables, scalars = _current_project()
    without_alias_hash = project_io.input_sha256(tables, scalars)
    without_alias_persistence = project_io.persistence_sha256(tables, scalars)
    scalars[modelled_direction.ALIAS_KEY] = "  span   direction  "

    text = project_io.dump_project(tables, scalars)
    loaded_tables, loaded_scalars = project_io.parse_project(text)
    payload = json.loads(text)

    assert payload["presentation"] == {
        modelled_direction.ALIAS_KEY: "span direction",
        project_io.REPORT_PROFILE_KEY: "Standard",
    }
    assert modelled_direction.ALIAS_KEY not in payload["scalars"]
    assert loaded_scalars[modelled_direction.ALIAS_KEY] == "span direction"
    assert project_io.input_sha256(loaded_tables, loaded_scalars) == (
        without_alias_hash
    )
    assert project_io.persistence_sha256(
        loaded_tables, loaded_scalars
    ) != without_alias_persistence


def test_report_profile_is_presentation_only_but_changes_persistence_identity():
    tables, scalars = _current_project()
    standard = {**scalars, project_io.REPORT_PROFILE_KEY: "Standard"}
    audit = {**scalars, project_io.REPORT_PROFILE_KEY: "Audit"}

    assert project_io.input_sha256(tables, standard) == (
        project_io.input_sha256(tables, audit)
    )
    assert project_io.persistence_sha256(tables, standard) != (
        project_io.persistence_sha256(tables, audit)
    )

    payload = json.loads(project_io.dump_project(tables, audit))
    _, loaded = project_io.parse_project(json.dumps(payload))
    assert project_io.REPORT_PROFILE_KEY not in payload["scalars"]
    assert payload["presentation"][project_io.REPORT_PROFILE_KEY] == "Audit"
    assert loaded[project_io.REPORT_PROFILE_KEY] == "Audit"


@pytest.mark.parametrize(
    ("legacy_label", "expected"),
    (
        ("Default report", "Standard"),
        ("Default report + QA appendix", "Audit"),
        ("Brief", "Brief"),
        ("Standard", "Standard"),
        ("Audit", "Audit"),
    ),
)
def test_schema_24_migrates_exact_legacy_report_labels_and_scalar_placement(
    legacy_label,
    expected,
):
    tables, scalars = _current_project()
    payload = json.loads(project_io.dump_project(tables, scalars))
    payload["presentation"].pop(project_io.REPORT_PROFILE_KEY)
    payload["scalars"][project_io.REPORT_PROFILE_KEY] = legacy_label
    payload["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": payload["tables"],
        "scalars": payload["scalars"],
    })

    text = json.dumps(payload)
    assert project_io.project_provenance(text)["input_hash_valid"] is True
    _, loaded = project_io.parse_project(text)
    assert loaded[project_io.REPORT_PROFILE_KEY] == expected


@pytest.mark.parametrize(
    "value",
    ("default report", "Default report ", "Unknown", 1, ["Audit"]),
)
def test_unknown_or_inexact_persisted_report_profile_fails_closed(value):
    tables, scalars = _current_project()
    payload = json.loads(project_io.dump_project(tables, scalars))
    payload["presentation"][project_io.REPORT_PROFILE_KEY] = value
    text = json.dumps(payload)

    assert project_io.project_provenance(text)["input_hash_valid"] is True
    with pytest.raises(ValueError, match="unknown persisted report profile"):
        project_io.parse_project(text)


def test_direction_alias_validation_is_separate_from_input_integrity():
    tables, scalars = _current_project()
    payload = json.loads(project_io.dump_project(tables, scalars))
    payload["presentation"][modelled_direction.ALIAS_KEY] = "span\ndirection"

    assert project_io.project_provenance(
        json.dumps(payload)
    )["input_hash_valid"] is True
    with pytest.raises(ValueError, match="must be a single line"):
        project_io.parse_project(json.dumps(payload))


def test_direction_alias_length_limit_is_symmetric_and_presentation_only():
    tables, scalars = _current_project()
    too_long = "x" * (modelled_direction.MAX_ALIAS_CHARS + 1)
    message = "^modelled direction alias must be at most 60 characters$"

    with pytest.raises(ValueError, match=message):
        project_io.dump_project(
            tables,
            {**scalars, modelled_direction.ALIAS_KEY: too_long},
        )

    payload = json.loads(project_io.dump_project(tables, scalars))
    payload["presentation"][modelled_direction.ALIAS_KEY] = too_long
    text = json.dumps(payload)

    assert project_io.project_provenance(text)["input_hash_valid"] is True
    with pytest.raises(ValueError, match=message):
        project_io.parse_project(text)


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


def test_noncurrent_non_v23_schema_names_current_and_migratable_versions():
    text = json.dumps({"format": project_io.FORMAT, "version": 22})

    with pytest.raises(
        ValueError,
        match=(
            r"unsupported Sector project schema 22; only current schema 25 "
            r"and migration from schema 24"
        ),
    ):
        project_io.parse_project(text)


def test_schema_25_serialization_contains_no_retired_bridge_inputs():
    tables, scalars = _current_project()
    tables.update({
        "bridge_brittle_base": {"retired": True},
        "bridge_box_walls_base": {"retired": True},
        "bridge_minimum_crack_base": {"retired": True},
    })
    scalars["bridge_standard"] = "retired"

    data = json.loads(project_io.dump_project(tables, scalars))

    assert data["version"] == 25
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


@pytest.mark.parametrize("basis_key", tuple(design_standards.DesignBasisKey))
def test_sls_code_round_trips_only_as_a_registered_basis_key(basis_key):
    tables, scalars = _current_project()
    scalars["sls_code"] = basis_key.value

    text = project_io.dump_project(tables, scalars)
    _, loaded = project_io.parse_project(text)

    assert loaded["sls_code"] == basis_key.value
    assert json.loads(text)["scalars"]["sls_code"] == basis_key.value


@pytest.mark.parametrize(
    "invalid",
    (
        "EN 1992-1-1:2005",
        "DS/EN 1992-1-1 + DK NA",
        "DS/EN 1992-1-1 + DK NA (fine crack system)",
        "EN 1992-1-1:2023",
        "ec2_1_1_first_gen_dk_na_2024 ",
        "unknown",
        "",
        None,
        True,
    ),
)
def test_sls_code_rejects_labels_aliases_whitespace_and_unknown_values(invalid):
    tables, scalars = _current_project()
    scalars["sls_code"] = invalid

    with pytest.raises(ValueError, match="registered basis keys"):
        project_io.dump_project(tables, scalars)


def test_ordinary_crack_request_requires_a_persisted_sls_basis_key():
    tables, scalars = _current_project()
    scalars.pop("sls_code")

    with pytest.raises(
        ValueError,
        match="sls_code is required when an Elastic case requests crack width",
    ):
        project_io.dump_project(tables, scalars)


def test_active_heightened_inputs_round_trip_with_direct_fct_eff():
    tables, scalars = _current_project()
    scalars.update(_heightened_inputs())
    scalars["sls_fctm"] = 9.9

    text = project_io.dump_project(tables, scalars)
    _, loaded = project_io.parse_project(text)
    persisted = json.loads(text)["scalars"]

    for key, value in _heightened_inputs().items():
        assert loaded[key] == value
        assert persisted[key] == value
    assert loaded["sls_heightened_effective_tensile_strength_mpa"] == 2.9
    assert loaded["sls_fctm"] == 9.9


def test_legacy_schema25_heightened_operands_migrate_to_dual_contract():
    payload = _legacy_heightened_schema25_payload()

    _, loaded, info = project_io.parse_project_with_info(json.dumps(payload))

    assert info["migrated"] is True
    assert len(info["migration_warnings"]) == 1
    assert "copied to both systems" in info["migration_warnings"][0]
    assert loaded["sls_heightened_reference_case"] == "One Elastic action"
    assert loaded[
        "sls_heightened_fine_effective_tension_area_mm2"
    ] == pytest.approx(120_000.0)
    assert loaded[
        "sls_heightened_coarse_effective_tension_area_mm2"
    ] == pytest.approx(120_000.0)
    assert not project_io.LEGACY_HEIGHTENED_OPERAND_KEYS.intersection(loaded)


def test_legacy_heightened_migration_refuses_ambiguous_reference_case():
    tables, _ = _current_project()
    elastic = tables[load_cases.ELASTIC_TABLE_KEY].to_dict("records")
    tables[load_cases.ELASTIC_TABLE_KEY] = load_cases.normalise_table(
        [
            *elastic,
            {
                "name": "Second Elastic action",
                "calculate_crack_width": True,
            },
        ],
        load_cases.ELASTIC_TABLE_KEY,
    )
    payload = _legacy_heightened_schema25_payload(tables)

    with pytest.raises(ValueError, match="does not identify one reference case"):
        project_io.parse_project_with_info(json.dumps(payload))


def test_legacy_heightened_migration_rejects_mixed_old_and_new_contract():
    payload = _legacy_heightened_schema25_payload()
    payload["scalars"][
        "sls_heightened_fine_effective_tension_area_mm2"
    ] = 120_000.0
    payload["provenance"]["input_sha256"] = project_io._input_digest({
        "tables": payload["tables"],
        "scalars": payload["scalars"],
    })

    with pytest.raises(ValueError, match="mixes retired and current"):
        project_io.parse_project_with_info(json.dumps(payload))


@pytest.mark.parametrize(
    "basis_key",
    (
        design_standards.DesignBasisKey.FIRST_GEN_BASE,
        design_standards.DesignBasisKey.PUBLISHED_2023,
    ),
)
def test_active_heightened_check_is_strictly_dk_na_2024_only(basis_key):
    tables, scalars = _current_project()
    scalars.update(_heightened_inputs())
    scalars["sls_code"] = basis_key.value

    with pytest.raises(
        ValueError,
        match="heightened crack control requires "
        "ec2_1_1_first_gen_dk_na_2024",
    ):
        project_io.dump_project(tables, scalars)


@pytest.mark.parametrize(
    "missing",
    project_io.HEIGHTENED_CRACK_SCALAR_KEYS[2:],
)
def test_active_heightened_check_requires_every_selector_and_operand(missing):
    tables, scalars = _current_project()
    heightened = _heightened_inputs()
    heightened.pop(missing)
    scalars.update(heightened)

    with pytest.raises(ValueError, match=rf"^{re.escape(missing)} is required"):
        project_io.dump_project(tables, scalars)


def test_active_heightened_reference_is_auto_selected_for_one_crack_case():
    tables, scalars = _current_project()
    scalars.update(_heightened_inputs())
    scalars.pop("sls_heightened_reference_case")

    text = project_io.dump_project(tables, scalars)
    _, loaded = project_io.parse_project(text)

    assert loaded["sls_heightened_reference_case"] == "One Elastic action"


@pytest.mark.parametrize(
    ("key", "invalid", "message"),
    (
        (
            "sls_heightened_reinforcement_surface",
            "Ribbed",
            "ribbed.*smooth",
        ),
        (
            "sls_heightened_reinforcement_surface",
            "smooth ",
            "ribbed.*smooth",
        ),
        (
            "sls_heightened_reinforcement_surface",
            False,
            "ribbed.*smooth",
        ),
    ),
)
def test_active_heightened_selectors_are_exact(key, invalid, message):
    tables, scalars = _current_project()
    scalars.update(_heightened_inputs())
    scalars[key] = invalid

    with pytest.raises(ValueError, match=message):
        project_io.dump_project(tables, scalars)


@pytest.mark.parametrize(
    "key",
    (
        "sls_heightened_effective_tensile_strength_mpa",
        "sls_permitted_crack_width_mm",
        "sls_heightened_fine_effective_tension_area_mm2",
        "sls_heightened_coarse_effective_tension_area_mm2",
    ),
)
@pytest.mark.parametrize(
    "invalid",
    (True, "1.0", 0.0, -1.0, float("nan"), float("inf")),
)
def test_active_heightened_operands_must_be_positive_finite_reals(key, invalid):
    tables, scalars = _current_project()
    scalars.update(_heightened_inputs())
    scalars[key] = invalid

    with pytest.raises(
        ValueError,
        match=rf"^{re.escape(key)} must be a positive",
    ):
        project_io.dump_project(tables, scalars)


def test_active_heightened_fct_eff_never_falls_back_to_sls_fctm():
    tables, scalars = _current_project()
    heightened = _heightened_inputs()
    heightened.pop("sls_heightened_effective_tensile_strength_mpa")
    scalars.update(heightened)
    scalars["sls_fctm"] = 2.9

    with pytest.raises(
        ValueError,
        match="sls_heightened_effective_tensile_strength_mpa is required",
    ):
        project_io.dump_project(tables, scalars)


@pytest.mark.parametrize("invalid", (0, 1, "true", None))
def test_heightened_enable_flag_must_be_an_exact_boolean(invalid):
    tables, scalars = _current_project()
    scalars.update(_heightened_inputs())
    scalars["sls_heightened_on"] = invalid

    with pytest.raises(ValueError, match="sls_heightened_on must be a Boolean"):
        project_io.dump_project(tables, scalars)


def test_dormant_heightened_values_round_trip_under_a_non_dk_basis():
    tables, scalars = _current_project()
    dormant = _heightened_inputs()
    dormant["sls_heightened_on"] = False
    scalars.update(dormant)
    scalars["sls_code"] = (
        design_standards.DesignBasisKey.PUBLISHED_2023.value
    )

    text = project_io.dump_project(tables, scalars)
    _, loaded = project_io.parse_project(text)

    for key, value in dormant.items():
        assert loaded[key] == value
    assert loaded["sls_code"] == (
        design_standards.DesignBasisKey.PUBLISHED_2023.value
    )


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
