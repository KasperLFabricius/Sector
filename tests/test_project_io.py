"""Round-trip tests for the project save/load serialisation (pure, no Streamlit)."""

from __future__ import annotations

import json
import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import fatigue_inputs  # noqa: E402
import load_cases  # noqa: E402
import material_catalog  # noqa: E402
import project_io  # noqa: E402
import reinforcement_table as rebar_table  # noqa: E402


def test_migrate_legacy_torsion_only_stirrup():
    # v0.48: a torsion-only legacy project's separate stirrup folds into the shared
    # shear_link_* keys (whose shear_link_* held only unused defaults).
    import json
    proj = {"format": "sector-project", "version": 2, "tables": {},
            "scalars": {"torsion_on": True, "shear_links": False,
                        "torsion_stirrup_dia": 12.0, "torsion_stirrup_s": 120.0,
                        "torsion_fywk": 550.0, "shear_link_dia": 10.0}}
    _, scalars = project_io.parse_project(json.dumps(proj))
    assert scalars["shear_link_dia"] == 12.0
    assert scalars["shear_link_s"] == 120.0
    assert scalars["shear_fywk"] == 550.0
    assert "torsion_stirrup_dia" not in scalars   # obsolete key dropped


def test_migrate_keeps_shear_stirrup_when_both_active():
    # With shear links truly active (shear_on and shear_links), the shear stirrup is
    # the shared one (two independent stirrups cannot both survive).
    import json
    proj = {"format": "sector-project", "version": 2, "tables": {},
            "scalars": {"torsion_on": True, "shear_on": True, "shear_links": True,
                        "torsion_stirrup_dia": 12.0, "shear_link_dia": 10.0}}
    _, scalars = project_io.parse_project(json.dumps(proj))
    assert scalars["shear_link_dia"] == 10.0


def test_migrate_when_shear_links_flag_is_stale():
    # shear_links can be left true after shear_on was turned off; the shear check is
    # then inactive, so a torsion-only project's stirrup still migrates.
    import json
    proj = {"format": "sector-project", "version": 2, "tables": {},
            "scalars": {"torsion_on": True, "shear_on": False, "shear_links": True,
                        "torsion_stirrup_dia": 12.0, "shear_link_dia": 10.0}}
    _, scalars = project_io.parse_project(json.dumps(proj))
    assert scalars["shear_link_dia"] == 12.0   # torsion stirrup migrated


def test_migrate_custom_torsion_stirrup_toggled_off_before_save():
    # A custom torsion stirrup saved with the torsion check off is still preserved
    # (it would otherwise be lost when the user re-enables torsion after load).
    import json
    proj = {"format": "sector-project", "version": 2, "tables": {},
            "scalars": {"torsion_on": False, "shear_on": False, "shear_links": False,
                        "torsion_stirrup_dia": 14.0, "shear_link_dia": 10.0}}
    _, scalars = project_io.parse_project(json.dumps(proj))
    assert scalars["shear_link_dia"] == 14.0


def test_migrate_default_torsion_stirrup_does_not_clobber_shear():
    # A dormant (default) torsion stirrup must not overwrite a custom shear stirrup
    # when shear happens to be off at save time.
    import json
    proj = {"format": "sector-project", "version": 2, "tables": {},
            "scalars": {"torsion_on": False, "shear_on": False, "shear_links": False,
                        "torsion_stirrup_dia": 10.0, "shear_link_dia": 16.0}}
    _, scalars = project_io.parse_project(json.dumps(proj))
    assert scalars["shear_link_dia"] == 16.0   # custom shear kept (torsion is default)


def _tables():
    return {
        "corners_base": pd.DataFrame({"x (mm)": [-100.0, 100.0, 100.0, -100.0],
                                      "y (mm)": [-150.0, -150.0, 150.0, 150.0]}),
        "hole_base": pd.DataFrame({"x (mm)": [], "y (mm)": []}),
        "bars_base": rebar_table.table_from_points(
            [(0.0, -120.0, 500.0)], "bar",
        ),
        "tendons_base": rebar_table.empty_table(),
    }


def test_round_trip_tables_and_scalars():
    tables = _tables()
    scalars = {"conc_fck": 55.0, "mode": "Both", "rep_author": "KLA",
               "conc_preset": "DS/EN 1992-1-1:2023", "conc_k_tc": 1.0,
               "label_scale": 1.5, "torsion_subdivide": True,
               "torsion_sub_x0": 0.0, "torsion_sub_y0": -100.0,
               "torsion_sub_b0": 300.0, "torsion_sub_h0": 600.0,
               "sls_wk_limit": 0.25, "sls_conc_limit_pct": 55.0,
               "sls_steel_limit_pct": 75.0, "sls_pre_limit_pct": 70.0,
               "sls_limit_source": "DB section SLS-2",
               "pl_case_id": "PL-17", "pl_case_type": "ALS",
               "pl_case_source": "Load model LM-4",
               "el_case_id": "EL-08", "el_case_type": "FLS",
               "el_case_source": "Combination register C2"}
    text = project_io.dump_project(tables, scalars)
    rt, rs = project_io.parse_project(text)
    expected_scalars = {
        key: value for key, value in scalars.items()
        if key not in load_cases.LEGACY_SCALAR_KEYS
    }
    assert rs == expected_scalars
    assert rt[load_cases.PLASTIC_TABLE_KEY].loc[0, "name"] == "PL-17"
    assert rt[load_cases.PLASTIC_TABLE_KEY].loc[0, "description"] == (
        "ALS | Source: Load model LM-4"
    )
    assert rt[load_cases.ELASTIC_TABLE_KEY].loc[0, "name"] == "EL-08"
    assert project_io.input_sha256(rt, rs) == (
        json.loads(text)["provenance"]["input_sha256"]
    )
    for key, df in tables.items():
        expected = (df if key in project_io.REINFORCEMENT_TABLE_KEYS
                    else df.astype("float64"))
        pd.testing.assert_frame_equal(
            rt[key].reset_index(drop=True),
            expected.reset_index(drop=True), check_dtype=False)


def test_v4_reinforcement_rows_migrate_to_stable_area_based_elements():
    project = {
        "format": "sector-project",
        "version": 4,
        "tables": {
            "bars_base": {
                "columns": ["x (mm)", "y (mm)", "area (mm2)"],
                "rows": [[0.0, -120.0, 314.159265]],
            },
            "tendons_base": {
                "columns": ["x (mm)", "y (mm)", "area (mm2)"],
                "rows": [[0.0, 100.0, 150.0]],
            },
        },
        "scalars": {},
    }

    tables, _ = project_io.parse_project(json.dumps(project))

    bar = tables["bars_base"].iloc[0]
    tendon = tables["tendons_base"].iloc[0]
    assert list(tables["bars_base"].columns) == rebar_table.COLUMNS
    assert (bar["ID"], bar["size mode"], bar["material ID"]) == (
        "R1", "Area", "M1"
    )
    assert bar["diameter (mm)"] == pytest.approx(20.0)
    assert (tendon["ID"], tendon["size mode"], tendon["material ID"]) == (
        "P1", "Area", "P1"
    )


def test_current_round_trip_preserves_size_basis_and_element_assignments():
    tables = _tables()
    tables["bars_base"] = rebar_table.normalise_table([
        {
            "ID": "R7", "x (mm)": 10.0, "y (mm)": -80.0,
            "size mode": "Independent", "area (mm2)": 420.0,
            "diameter (mm)": 25.0, "material ID": "M2",
            "fatigue detail ID": "FD-BENT", "group ID": "B1",
            "spacing group ID": "LAP-1",
        },
        {
            "ID": "R9", "x (mm)": -10.0, "y (mm)": -80.0,
            "size mode": "Diameter", "diameter (mm)": 20.0,
            "material ID": "M1",
        },
    ], "bar")

    text = project_io.dump_project(tables, {"mode": "Both"})
    restored, scalars = project_io.parse_project(text)

    payload = json.loads(text)
    assert payload["version"] == project_io.VERSION
    pd.testing.assert_frame_equal(restored["bars_base"], tables["bars_base"])
    assert restored["bars_base"].iloc[1]["area (mm2)"] == pytest.approx(
        np.pi * 20.0**2 / 4.0
    )
    assert project_io.input_sha256(restored, scalars) == (
        payload["provenance"]["input_sha256"]
    )


def test_current_round_trip_preserves_multiple_materials_without_flat_duplicates():
    mild, material_id = material_catalog.add_entry(
        material_catalog.default_catalog("mild"), "mild"
    )
    mild["items"][1]["name"] = "Existing reinforcement"
    mild["items"][1]["fytk"] = 235.0
    prestress = material_catalog.default_catalog("prestress")

    text = project_io.dump_project({}, {
        material_catalog.MILD_CATALOG_KEY: mild,
        material_catalog.PRESTRESS_CATALOG_KEY: prestress,
        "capacity_steel_material_id": material_id,
        # A stale compatibility alias must not create a second source of truth.
        "mild_fytk": 999.0,
    })
    payload = json.loads(text)
    _, scalars = project_io.parse_project(text)

    assert payload["version"] == project_io.VERSION
    assert "mild_fytk" not in payload["scalars"]
    assert [item["id"] for item in scalars[
        material_catalog.MILD_CATALOG_KEY]["items"]] == ["M1", "M2"]
    assert scalars[material_catalog.MILD_CATALOG_KEY]["items"][1]["fytk"] == 235.0
    assert scalars["capacity_steel_material_id"] == "M2"


def test_v5_material_ids_migrate_to_cloned_laws_without_changing_behaviour():
    project = {
        "format": "sector-project",
        "version": 5,
        "tables": {
            "bars_base": {
                "columns": rebar_table.COLUMNS[:-1],
                "rows": [["R1", 0.0, -100.0, "Area", 500.0, 25.23,
                          "M2", "", ""]],
            },
            "tendons_base": {
                "columns": rebar_table.COLUMNS[:-1],
                "rows": [["P1", 0.0, 100.0, "Area", 150.0, 13.82,
                          "P3", "", ""]],
            },
        },
        "scalars": {
            "mild_fytk": 412.0,
            "pre_fytk": 1500.0,
        },
    }

    _, scalars = project_io.parse_project(json.dumps(project))
    mild = scalars[material_catalog.MILD_CATALOG_KEY]["items"]
    prestress = scalars[material_catalog.PRESTRESS_CATALOG_KEY]["items"]

    assert [item["id"] for item in mild] == ["M1", "M2"]
    assert [item["fytk"] for item in mild] == [412.0, 412.0]
    assert [item["id"] for item in prestress] == ["P1", "P3"]
    assert [item["fytk"] for item in prestress] == [1500.0, 1500.0]


def test_current_round_trip_preserves_multiple_typed_load_cases():
    tables = _tables()
    tables[load_cases.PLASTIC_TABLE_KEY] = load_cases.normalise_table([
        {"name": "PL-01", "description": "Fundamental A",
         "n_ed_kn": -100.0, "mx_ed_knm": 20.0,
         "vx_ed_kn": -12.0, "vy_ed_kn": 8.0,
         "vx_face": "negative", "vy_face": "positive"},
        {"name": "PL-02", "description": "Accidental",
         "n_ed_kn": 50.0, "my_ed_knm": -8.0, "t_ed_knm": 3.5},
    ], load_cases.PLASTIC_TABLE_KEY)
    tables[load_cases.ELASTIC_TABLE_KEY] = load_cases.normalise_table([
        {"name": "EL-CHAR", "description": "Characteristic stresses",
         "mx_long_ed_knm": 30.0, "mx_short_ed_knm": 15.0,
         "check_stress": True, "check_crack_width": False},
        {"name": "EL-FREQ", "description": "Frequent crack width",
         "mx_long_ed_knm": 25.0, "mx_short_ed_knm": 5.0,
         "check_stress": False, "check_crack_width": True},
    ], load_cases.ELASTIC_TABLE_KEY)

    text = project_io.dump_project(tables, {"mode": "Both"})
    payload = json.loads(text)
    restored, scalars = project_io.parse_project(text)

    assert payload["version"] == project_io.VERSION
    assert [row["name"] for row in payload["load_cases"]["plastic"]] == [
        "PL-01", "PL-02"
    ]
    for key in load_cases.CASE_TABLE_KEYS:
        pd.testing.assert_frame_equal(restored[key], tables[key], check_dtype=True)
    assert not any(key in scalars for key in load_cases.LEGACY_SCALAR_KEYS)
    assert project_io.input_sha256(restored, scalars) == (
        payload["provenance"]["input_sha256"]
    )


def test_v9_round_trip_preserves_fatigue_details_and_grouped_spectrum():
    tables = {
        fatigue_inputs.SPECTRUM_TABLE_KEY:
            fatigue_inputs.normalise_spectrum_table([
                {
                    "spectrum": "Traffic",
                    "name": "FAT-01",
                    "description": "Frequent range",
                    "cycles": 2e6,
                    "n_long_ed_kn": -800.0,
                    "mx_long_ed_knm": 120.0,
                    "n_short_ed_kn": 50.0,
                    "mx_short_ed_knm": 80.0,
                },
                {
                    "spectrum": "Traffic",
                    "name": "FAT-02",
                    "cycles": 5e5,
                    "n_long_ed_kn": -800.0,
                    "mx_long_ed_knm": 120.0,
                    "n_short_ed_kn": 120.0,
                    "mx_short_ed_knm": 160.0,
                },
            ])
    }
    catalogue = fatigue_inputs.default_catalog()
    catalogue["items"][0] = fatigue_inputs.apply_preset(
        catalogue["items"][0], fatigue_inputs.PRESET_2023_BARS
    )
    scalars = {
        fatigue_inputs.DETAIL_CATALOG_KEY: catalogue,
        "fatigue_on": True,
        "fatigue_edition": fatigue_inputs.EC2_2023,
        "fatigue_gamma_c": 1.595,
        "fatigue_gamma_s": 1.32,
        "fatigue_gamma_ff": 1.0,
    }

    text = project_io.dump_project(tables, scalars)
    payload = json.loads(text)
    restored, restored_scalars = project_io.parse_project(text)

    assert payload["version"] == 9
    assert [row["name"] for row in payload["fatigue"]["spectrum"]] == [
        "FAT-01", "FAT-02"
    ]
    assert fatigue_inputs.spectrum_records(
        restored[fatigue_inputs.SPECTRUM_TABLE_KEY]
    ) == fatigue_inputs.spectrum_records(
        tables[fatigue_inputs.SPECTRUM_TABLE_KEY]
    )
    assert restored_scalars["fatigue_gamma_c"] == 1.595
    assert (
        restored_scalars[fatigue_inputs.DETAIL_CATALOG_KEY]["items"][0][
            "stress_model"
        ]
        == fatigue_inputs.EC2_2023_BAR_STRESS
    )
    assert project_io.input_sha256(restored, restored_scalars) == (
        project_io.input_sha256(tables, scalars)
    )


def test_v9_rejects_malformed_fatigue_section_and_spectrum_rows():
    malformed_section = json.dumps({
        "format": project_io.FORMAT,
        "version": 9,
        "tables": {},
        "scalars": {},
        "fatigue": [],
    })
    malformed_rows = json.dumps({
        "format": project_io.FORMAT,
        "version": 9,
        "tables": {},
        "scalars": {},
        "fatigue": {"spectrum": [1, 2]},
    })

    with pytest.raises(ValueError, match="malformed 'fatigue' section"):
        project_io.parse_project(malformed_section)
    with pytest.raises(ValueError, match="list of row objects"):
        project_io.parse_project(malformed_rows)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("n_star", "bad", "n_star must be a finite number"),
        ("bend_reduction", "false", "bend_reduction must be true or false"),
    ],
)
def test_v9_rejects_malformed_fatigue_catalogue_values(field, value, message):
    entry = fatigue_inputs.default_entry(
        preset=fatigue_inputs.PRESET_2023_BENT_BARS
    )
    entry[field] = value
    project = {
        "format": project_io.FORMAT,
        "version": 9,
        "tables": {},
        "scalars": {
            fatigue_inputs.DETAIL_CATALOG_KEY: {"items": [entry]}
        },
    }

    with pytest.raises(ValueError, match=message):
        project_io.parse_project(json.dumps(project))


def test_v9_rejects_nonobject_fatigue_catalogue_items():
    project = {
        "format": project_io.FORMAT,
        "version": 9,
        "tables": {},
        "scalars": {
            fatigue_inputs.DETAIL_CATALOG_KEY: {"items": ["bad"]}
        },
    }

    with pytest.raises(ValueError, match="items must contain only objects"):
        project_io.parse_project(json.dumps(project))


@pytest.mark.parametrize("items", [None, {}, []])
def test_v9_rejects_explicit_empty_fatigue_catalogues(items):
    project = {
        "format": project_io.FORMAT,
        "version": 9,
        "tables": {},
        "scalars": {
            fatigue_inputs.DETAIL_CATALOG_KEY: {"items": items}
        },
    }

    with pytest.raises(ValueError, match="items must be a non-empty list"):
        project_io.parse_project(json.dumps(project))


@pytest.mark.parametrize("catalogue", [None, []])
def test_v9_rejects_nonobject_fatigue_catalogues(catalogue):
    project = {
        "format": project_io.FORMAT,
        "version": 9,
        "tables": {},
        "scalars": {
            fatigue_inputs.DETAIL_CATALOG_KEY: catalogue
        },
    }

    with pytest.raises(
        ValueError,
        match="fatigue detail catalogue must be an object",
    ):
        project_io.parse_project(json.dumps(project))


@pytest.mark.parametrize(
    ("axis", "tension", "component", "face", "bw_key", "legs_key"),
    [
        ("Vertical shear (bending about x)", "Bottom / left face",
         "vy", "negative", "shear_vy_bw", "shear_vy_link_legs"),
        ("Horizontal shear (bending about y)", "Top / right face",
         "vx", "positive", "shear_vx_bw", "shear_vx_link_legs"),
    ],
)
def test_v6_shear_direction_migrates_without_changing_the_active_component(
    axis, tension, component, face, bw_key, legs_key
):
    project = {
        "format": project_io.FORMAT,
        "version": 6,
        "tables": {},
        "scalars": {
            "shear_on": True,
            "shear_axis": axis,
            "shear_tension": tension,
            "shear_bw": 275.0,
            "shear_link_legs": 4.0,
        },
        "load_cases": {
            "plastic": [{
                "name": "PL-OLD", "description": "v6",
                "n_ed_kn": 0.0, "mx_ed_knm": 10.0, "my_ed_knm": -5.0,
                "v_ed_kn": -85.0, "t_ed_knm": 0.0,
            }],
            "elastic": [],
        },
    }

    tables, scalars = project_io.parse_project(json.dumps(project))
    row = tables[load_cases.PLASTIC_TABLE_KEY].iloc[0]

    assert row[f"{component}_ed_kn"] == -85.0
    other = "vy" if component == "vx" else "vx"
    assert row[f"{other}_ed_kn"] == 0.0
    assert row[f"{component}_face"] == face
    assert scalars[bw_key] == 275.0
    assert scalars[legs_key] == 4.0
    assert scalars[f"shear_{other}_bw"] == 0.0
    assert scalars[f"shear_{other}_link_legs"] == 2.0


def test_v4_project_rejects_nonfinite_load_case_instead_of_rewriting_it():
    tables = _tables()
    tables[load_cases.PLASTIC_TABLE_KEY] = load_cases.normalise_table([
        {"name": "PL-BAD", "mx_ed_knm": "invalid"},
    ], load_cases.PLASTIC_TABLE_KEY)
    tables[load_cases.ELASTIC_TABLE_KEY] = load_cases.empty_table(
        load_cases.ELASTIC_TABLE_KEY
    )

    with pytest.raises(ValueError, match=r"mx_ed_knm must be a finite number"):
        project_io.dump_project(tables, {"mode": "Plastic"})


def test_v4_partial_case_table_keeps_hash_stable_after_reload():
    tables = _tables()
    tables[load_cases.PLASTIC_TABLE_KEY] = load_cases.normalise_table([
        {"name": "PL-ONLY", "n_ed_kn": -250.0, "mx_ed_knm": 80.0},
    ], load_cases.PLASTIC_TABLE_KEY)

    text = project_io.dump_project(tables, {"mode": "Plastic"})
    payload = json.loads(text)
    restored, scalars = project_io.parse_project(text)

    assert not any(key in scalars for key in load_cases.LEGACY_SCALAR_KEYS)
    assert restored[load_cases.PLASTIC_TABLE_KEY].loc[0, "name"] == "PL-ONLY"
    assert restored[load_cases.PLASTIC_TABLE_KEY].loc[0, "n_ed_kn"] == -250.0
    assert project_io.input_sha256(restored, scalars) == (
        payload["provenance"]["input_sha256"]
    )


def test_v4_partial_project_without_loads_preserves_absence_and_hash():
    tables = {"hole_base": _tables()["hole_base"]}

    text = project_io.dump_project(tables, {})
    payload = json.loads(text)
    restored, scalars = project_io.parse_project(text)

    assert "load_cases" not in payload
    assert not any(key in restored for key in load_cases.CASE_TABLE_KEYS)
    assert project_io.input_sha256(restored, scalars) == (
        payload["provenance"]["input_sha256"]
    )


def test_v3_single_case_scalars_migrate_after_axial_sign_conversion():
    text = json.dumps({
        "format": project_io.FORMAT,
        "version": 1,
        "tables": {},
        "scalars": {
            "pl_case_id": "OLD-PL",
            "pl_P": 1200.0,
            "pl_Mx": 90.0,
            "el_case_id": "OLD-EL",
            "el_long_P": -300.0,
            "sls_cw": True,
        },
    })
    tables, scalars = project_io.parse_project(text)
    plastic = tables[load_cases.PLASTIC_TABLE_KEY]
    elastic = tables[load_cases.ELASTIC_TABLE_KEY]
    assert scalars["pl_P"] == -1200.0
    assert plastic.loc[0, "n_ed_kn"] == -1200.0
    assert elastic.loc[0, "n_long_ed_kn"] == 300.0
    assert bool(elastic.loc[0, "check_crack_width"]) is True


def test_legacy_2023_project_defaults_to_general_k_tc():
    import json

    text = json.dumps({
        "format": project_io.FORMAT,
        "version": project_io.VERSION,
        "tables": {},
        "scalars": {
            "conc_preset": "DS/EN 1992-1-1:2023",
            "conc_fck": 40.0,
            "conc_alpha_cc": 1.0,
        },
    })
    _, scalars = project_io.parse_project(text)
    assert scalars["conc_k_tc"] == pytest.approx(0.85)


def test_v7_project_clears_new_detailing_settings_deterministically():
    text = json.dumps({
        "format": project_io.FORMAT,
        "version": 7,
        "tables": {},
        "scalars": {"mode": "Plastic"},
    })

    _, scalars = project_io.parse_project(text)

    assert scalars["minimum_reinforcement_on"] is False
    assert scalars["clear_spacing_on"] is False
    assert scalars["detailing_edition"] == "DS/EN 1992-1-1:2005 + DK NA:2024"
    assert scalars["detailing_d_upper"] == pytest.approx(16.0)
    assert scalars["detailing_include_tendons"] is False


def test_blank_separator_row_survives_round_trip():
    # A void table with a NaN separator row keeps the NaN (so two voids stay split).
    holes = pd.DataFrame({"x (mm)": [-20.0, 20.0, 0.0, np.nan, 30.0, 50.0, 40.0],
                          "y (mm)": [-10.0, -10.0, 10.0, np.nan, -10.0, -10.0, 10.0]})
    rt, _ = project_io.parse_project(project_io.dump_project({"hole_base": holes}, {}))
    assert int(rt["hole_base"].isna().any(axis=1).sum()) == 1


def test_unknown_scalar_keys_are_dropped():
    text = project_io.dump_project({}, {"conc_fck": 30.0, "secret": 1, "results": "x"})
    _, scalars = project_io.parse_project(text)
    assert scalars == {"conc_fck": 30.0}


def test_project_provenance_records_and_verifies_exact_inputs():
    text = project_io.dump_project(
        _tables(),
        {"mode": "Both", "pl_case_id": "PL-01", "el_case_id": "EL-01"},
        app_version="0.78",
        revision="a" * 40,
    )
    payload = json.loads(text)
    provenance = project_io.project_provenance(text)

    assert payload["version"] == project_io.VERSION
    assert provenance["sector_version"] == "0.78"
    assert provenance["source_revision"] == "a" * 40
    assert provenance["saved_at_utc"].endswith("+00:00")
    assert len(provenance["input_sha256"]) == 64
    assert provenance["input_hash_valid"] is True
    assert provenance["results_included"] is False


def test_project_provenance_detects_tampered_inputs():
    scalars = {"conc_fck": 30.0}
    text = project_io.dump_project(
        {}, scalars,
        calculation={"input_sha256": project_io.input_sha256({}, scalars)},
        app_version="0.78", revision="b" * 40,
    )
    payload = json.loads(text)
    payload["scalars"]["conc_fck"] = 35.0

    provenance = project_io.project_provenance(json.dumps(payload))
    assert provenance["input_hash_valid"] is False
    assert provenance["calculation"]["matches_saved_inputs"] is False


def test_project_records_whether_calculation_matches_saved_inputs():
    scalars = {"mode": "Plastic", "pl_case_id": "PL-01"}
    digest = project_io.input_sha256({}, scalars)
    calculation = {
        "performed_at_utc": "2026-07-20T10:00:00+00:00",
        "sector_version": "0.78",
        "source_revision": "c" * 40,
        "input_sha256": digest,
    }
    matching = json.loads(project_io.dump_project(
        {}, scalars, calculation=calculation,
        app_version="0.78", revision="c" * 40,
    ))
    changed = json.loads(project_io.dump_project(
        {}, {**scalars, "pl_case_id": "PL-02"}, calculation=calculation,
        app_version="0.78", revision="c" * 40,
    ))

    assert matching["calculation"]["matches_saved_inputs"] is True
    assert changed["calculation"]["matches_saved_inputs"] is False


def test_legacy_mpa_moduli_are_rescaled_to_gpa():
    # Files written before the GPa switch stored the steel moduli in MPa; loading one
    # rescales them, so a 200000 MPa modulus reads as 200 GPa.
    text = project_io.dump_project({}, {"mild_Es": 200000.0, "pre_Es": 195000.0})
    _, scalars = project_io.parse_project(text)
    mild = scalars[material_catalog.MILD_CATALOG_KEY]["items"][0]
    prestress = scalars[material_catalog.PRESTRESS_CATALOG_KEY]["items"][0]
    assert mild["Es"] == pytest.approx(200.0)
    assert prestress["Es"] == pytest.approx(195.0)
    assert "mild_Es" not in scalars
    assert "pre_Es" not in scalars


def test_gpa_moduli_load_unchanged():
    # A modern file already stores GPa (a few hundred at most), so loading is a no-op
    # -- the rescale must not fire twice.
    text = project_io.dump_project({}, {"mild_Es": 200.0, "pre_Es": 195.0})
    _, scalars = project_io.parse_project(text)
    mild = scalars[material_catalog.MILD_CATALOG_KEY]["items"][0]
    prestress = scalars[material_catalog.PRESTRESS_CATALOG_KEY]["items"][0]
    assert mild["Es"] == pytest.approx(200.0)
    assert prestress["Es"] == pytest.approx(195.0)


def test_legacy_axial_force_is_flipped_to_tension_positive():
    # N is now tension-positive; a version-1 file stored it compression-positive, so
    # loading it negates the axial values (moments unchanged) to keep the physical
    # loads. A 1500 kN compression (old +1500) loads as -1500 kN.
    import json
    text = json.dumps({"format": project_io.FORMAT, "version": 1, "tables": {},
                       "scalars": {"pl_P": 1500.0, "pl_Mx": 200.0,
                                   "el_long_P": -800.0, "el_short_P": 0.0}})
    _, scalars = project_io.parse_project(text)
    assert scalars["pl_P"] == pytest.approx(-1500.0)
    assert scalars["el_long_P"] == pytest.approx(800.0)
    assert scalars["el_short_P"] == pytest.approx(0.0)
    assert scalars["pl_Mx"] == pytest.approx(200.0)         # moments are unchanged


def test_current_axial_force_loads_unchanged():
    # A current (version-2) file is already tension-positive, so it must not be
    # re-negated on load.
    text = project_io.dump_project({}, {"pl_P": -1500.0, "el_long_P": 800.0})
    tables, scalars = project_io.parse_project(text)
    assert not any(key in scalars for key in load_cases.LEGACY_SCALAR_KEYS)
    assert tables[load_cases.PLASTIC_TABLE_KEY].loc[0, "n_ed_kn"] == pytest.approx(
        -1500.0
    )
    assert tables[load_cases.ELASTIC_TABLE_KEY].loc[
        0, "n_long_ed_kn"
    ] == pytest.approx(800.0)


def test_legacy_quick_section_rebar_settings_migrate():
    # Before the QS rebar rework the interleave diameter was a string ("none"/"16")
    # and there was one shared cover; loading such a file converts the interleave to a
    # number (0 = off) and splits the single cover into a top and bottom cover.
    import json
    text = json.dumps({"format": project_io.FORMAT, "version": 2, "tables": {},
                       "scalars": {"qsv_cover_mm": 45.0, "qsv_bot_off_d": "none",
                                   "qsv_top_off_d": "16"}})
    _, scalars = project_io.parse_project(text)
    assert scalars["qsv_bot_off_d"] == pytest.approx(0.0)     # "none" -> off
    assert scalars["qsv_top_off_d"] == pytest.approx(16.0)    # "16" -> 16 mm
    assert scalars["qsv_bot_c_mm"] == pytest.approx(45.0)     # single cover -> both faces
    assert scalars["qsv_top_c_mm"] == pytest.approx(45.0)
    assert "qsv_cover_mm" not in scalars                      # the old key is gone


def test_dump_handles_numpy_scalars():
    text = project_io.dump_project({}, {"conc_fck": np.float64(42.0),
                                        "mild_active_comp": np.bool_(True)})
    _, scalars = project_io.parse_project(text)
    assert scalars["conc_fck"] == 42.0
    mild = scalars[material_catalog.MILD_CATALOG_KEY]["items"][0]
    assert mild["active_in_compression"] is True


def test_parse_rejects_foreign_or_broken_json():
    with pytest.raises(ValueError):
        project_io.parse_project('{"format": "something-else"}')
    with pytest.raises(ValueError):
        project_io.parse_project("not json at all")


def test_parse_rejects_malformed_table_object():
    # A table entry that is not a {columns, rows} object (here a bare list) must
    # raise ValueError, not an AttributeError that escapes the caller's handling.
    text = ('{"format": "%s", "version": 1, '
            '"tables": {"bars_base": [1, 2, 3]}, "scalars": {}}' % project_io.FORMAT)
    with pytest.raises(ValueError):
        project_io.parse_project(text)


def test_parse_rejects_non_object_sections():
    # 'tables' / 'scalars' that are the wrong JSON type (a list) must raise
    # ValueError rather than crash on a missing .items()/subscript.
    bad_tables = '{"format": "%s", "tables": [1, 2], "scalars": {}}' % project_io.FORMAT
    bad_scalars = '{"format": "%s", "tables": {}, "scalars": [1, 2]}' % project_io.FORMAT
    with pytest.raises(ValueError):
        project_io.parse_project(bad_tables)
    with pytest.raises(ValueError):
        project_io.parse_project(bad_scalars)
    bad_cases = ('{"format": "%s", "tables": {}, "load_cases": [1, 2], '
                 '"scalars": {}}' % project_io.FORMAT)
    with pytest.raises(ValueError):
        project_io.parse_project(bad_cases)


def test_parse_rejects_non_tabular_table_rows():
    # 'rows' that are bare scalars (not a list of rows) against named columns is
    # not tabular -> ValueError from _obj_to_table, not an opaque pandas crash.
    text = ('{"format": "%s", "tables": {"bars_base": '
            '{"columns": ["x (mm)", "y (mm)"], "rows": [1, 2, 3]}}, '
            '"scalars": {}}' % project_io.FORMAT)
    with pytest.raises(ValueError):
        project_io.parse_project(text)
