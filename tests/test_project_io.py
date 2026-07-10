"""Round-trip tests for the project save/load serialisation (pure, no Streamlit)."""

from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

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


def test_migrate_keeps_shear_stirrup_when_both_present():
    # With shear links too, the shear stirrup is the shared one (two cannot survive).
    import json
    proj = {"format": "sector-project", "version": 2, "tables": {},
            "scalars": {"torsion_on": True, "shear_links": True,
                        "torsion_stirrup_dia": 12.0, "shear_link_dia": 10.0}}
    _, scalars = project_io.parse_project(json.dumps(proj))
    assert scalars["shear_link_dia"] == 10.0


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
               "conc_preset": "Curve 2 (parabola-rectangle)", "label_scale": 1.5}
    rt, rs = project_io.parse_project(project_io.dump_project(tables, scalars))
    assert rs == scalars
    for key, df in tables.items():
        pd.testing.assert_frame_equal(
            rt[key].reset_index(drop=True),
            df.astype("float64").reset_index(drop=True), check_dtype=False)


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
    _, scalars = project_io.parse_project(text)
    assert scalars["pl_P"] == pytest.approx(-1500.0)
    assert scalars["el_long_P"] == pytest.approx(800.0)


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


def test_parse_rejects_non_tabular_table_rows():
    # 'rows' that are bare scalars (not a list of rows) against named columns is
    # not tabular -> ValueError from _obj_to_table, not an opaque pandas crash.
    text = ('{"format": "%s", "tables": {"bars_base": '
            '{"columns": ["x (mm)", "y (mm)"], "rows": [1, 2, 3]}}, '
            '"scalars": {}}' % project_io.FORMAT)
    with pytest.raises(ValueError):
        project_io.parse_project(text)
