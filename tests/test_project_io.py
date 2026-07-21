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

import load_cases  # noqa: E402
import project_io  # noqa: E402


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
        "bars_base": pd.DataFrame({"x (mm)": [0.0], "y (mm)": [-120.0],
                                   "area (mm2)": [500.0]}),
        "tendons_base": pd.DataFrame({"x (mm)": [], "y (mm)": [], "area (mm2)": []}),
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
        pd.testing.assert_frame_equal(
            rt[key].reset_index(drop=True),
            df.astype("float64").reset_index(drop=True), check_dtype=False)


def test_v4_round_trip_preserves_multiple_typed_load_cases():
    tables = _tables()
    tables[load_cases.PLASTIC_TABLE_KEY] = load_cases.normalise_table([
        {"name": "PL-01", "description": "Fundamental A",
         "n_ed_kn": -100.0, "mx_ed_knm": 20.0, "v_ed_kn": -12.0},
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

    assert payload["version"] == 4
    assert [row["name"] for row in payload["load_cases"]["plastic"]] == [
        "PL-01", "PL-02"
    ]
    for key in load_cases.CASE_TABLE_KEYS:
        pd.testing.assert_frame_equal(restored[key], tables[key], check_dtype=True)
    assert not any(key in scalars for key in load_cases.LEGACY_SCALAR_KEYS)
    assert project_io.input_sha256(restored, scalars) == (
        payload["provenance"]["input_sha256"]
    )


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

    assert payload["version"] == 4
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
    assert scalars["mild_Es"] == pytest.approx(200.0)
    assert scalars["pre_Es"] == pytest.approx(195.0)


def test_gpa_moduli_load_unchanged():
    # A modern file already stores GPa (a few hundred at most), so loading is a no-op
    # -- the rescale must not fire twice.
    text = project_io.dump_project({}, {"mild_Es": 200.0, "pre_Es": 195.0})
    _, scalars = project_io.parse_project(text)
    assert scalars["mild_Es"] == pytest.approx(200.0)
    assert scalars["pre_Es"] == pytest.approx(195.0)


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
    assert scalars["mild_active_comp"] is True


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
