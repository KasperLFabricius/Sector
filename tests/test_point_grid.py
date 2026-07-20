"""The point-grid component's Python seam.

The Tabulator frontend is exercised in the browser; here we cover the data
conversion and the default round trip that the rest of the app relies on (and
that keeps the headless tests, which never run the frontend, meaningful).
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "app"))

from point_grid import _rows_to_df, _versioned_rows  # noqa: E402

_CORNERS = ["x (mm)", "y (mm)"]
_REBAR = ["x (mm)", "y (mm)", "area (mm2)"]


def test_rows_to_df_empty_is_typed_and_columned():
    df = _rows_to_df([], _CORNERS)
    assert list(df.columns) == _CORNERS
    assert len(df) == 0
    assert all(str(df[c].dtype) == "float64" for c in _CORNERS)


def test_rows_to_df_keeps_order_and_blanks_as_nan():
    rows = [{"x (mm)": 0.0, "y (mm)": 0.0},
            {"x (mm)": None, "y (mm)": 25.0},     # a void separator / half-typed row
            {"x (mm)": 100.0, "y (mm)": 50.0}]
    df = _rows_to_df(rows, _CORNERS)
    assert df["x (mm)"].tolist()[0] == 0.0 and df["x (mm)"].tolist()[2] == 100.0
    assert np.isnan(df["x (mm)"].tolist()[1])     # blank cell -> NaN, row kept
    assert all(str(df[c].dtype) == "float64" for c in _CORNERS)


def test_rows_to_df_coerces_nonnumeric_and_fills_missing_columns():
    # A stray paste (text) becomes NaN; an absent column is added as NaN -- the
    # downstream point parsing then simply skips those rows.
    rows = [{"x (mm)": "oops", "y (mm)": 10.0}]   # no area column at all
    df = _rows_to_df(rows, _REBAR)
    assert list(df.columns) == _REBAR
    assert np.isnan(df["x (mm)"].iloc[0])
    assert np.isnan(df["area (mm2)"].iloc[0])


def test_versioned_rows_rejects_a_stale_reseed_payload():
    rows = [{"x (mm)": 10.0, "y (mm)": 20.0}]
    assert _versioned_rows(
        {"data_version": "4", "rows": rows}, 4
    ) == rows
    assert _versioned_rows(
        {"data_version": "3", "rows": rows}, 4
    ) is None
    assert _versioned_rows(rows, 4) is None       # old frontend: seed is unknowable


def test_app_feeds_grid_points_to_the_analysis():
    # Under AppTest (and before the frontend first reports) the component returns
    # its default -- the seeded base -- so the grid's points flow straight into the
    # analysis. Seeding a known rectangle through the base must analyse cleanly.
    from streamlit.testing.v1 import AppTest

    app = pathlib.Path(__file__).resolve().parent.parent / "app" / "sector_app.py"
    at = AppTest.from_file(str(app), default_timeout=90)
    at.run()
    assert not at.exception
    at.session_state["corners_base"] = pd.DataFrame(
        {"x (mm)": [-200.0, -200.0, 200.0, 200.0],
         "y (mm)": [-300.0, 300.0, 300.0, -300.0]})
    at.button(key="calculate").click().run()
    assert not at.exception
    assert "plastic" in at.session_state["results"]
