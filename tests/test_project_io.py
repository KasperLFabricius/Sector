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
