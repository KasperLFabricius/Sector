"""The point-grid component's Python seam.

The Tabulator frontend is exercised in the browser; here we cover the data
conversion and the default round trip that the rest of the app relies on (and
that keeps the headless tests, which never run the frontend, meaningful).
"""

from __future__ import annotations

import json
import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "app"))

import point_grid as point_grid_module  # noqa: E402
from point_grid import _component_records, _rows_to_df, _versioned_rows  # noqa: E402

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


def test_component_records_replace_every_nonfinite_value_with_json_null():
    df = pd.DataFrame({
        "x (mm)": [0.0, np.nan, np.inf, -np.inf],
        "y (mm)": [25.0, 50.0, 75.0, 100.0],
    })

    records = _component_records(df, _CORNERS)

    assert [row["x (mm)"] for row in records] == [0.0, None, None, None]
    # ``allow_nan=False`` is the strict JSON contract used as the regression gate:
    # this raises if NaN or Infinity can reach Streamlit's component transport.
    assert json.loads(json.dumps(records, allow_nan=False)) == records


def test_component_records_keep_columns_and_half_typed_rows():
    df = pd.DataFrame([
        {"x (mm)": 10.0, "y (mm)": None, "ignored": 99.0},
        {"x (mm)": "not numeric", "y (mm)": 20.0, "ignored": 100.0},
    ])

    records = _component_records(df, _CORNERS)

    assert records == [
        {"x (mm)": 10.0, "y (mm)": None},
        {"x (mm)": None, "y (mm)": 20.0},
    ]


def test_point_grid_sends_only_strict_json_to_streamlit(monkeypatch):
    captured = {}

    def fake_component(**kwargs):
        captured.update(kwargs)
        return kwargs["default"]

    monkeypatch.setattr(point_grid_module, "_component", fake_component)
    df = pd.DataFrame({
        "x (mm)": [10.0, np.nan],
        "y (mm)": [20.0, 30.0],
    })

    result = point_grid_module.point_grid(df, _CORNERS, key="test-grid")

    assert captured["data"]["rows"][1]["x (mm)"] is None
    assert captured["default"]["payload"]["rows"] == captured["data"]["rows"]
    assert callable(captured["on_payload_change"])
    assert captured["width"] == "stretch"
    assert captured["height"] == "content"
    json.dumps({"data": captured["data"], "default": captured["default"]},
               allow_nan=False)
    assert np.isnan(result.iloc[1]["x (mm)"])


def test_component_registration_is_cached_per_streamlit_runtime(monkeypatch):
    class Manager:
        pass

    manager = Manager()
    registrations = []

    def fake_registration(*args, **kwargs):
        registrations.append((args, kwargs))
        return lambda **mount_kwargs: mount_kwargs

    monkeypatch.setattr(point_grid_module, "get_bidi_component_manager",
                        lambda: manager)
    monkeypatch.setattr(point_grid_module.st.components.v2, "component",
                        fake_registration)
    point_grid_module._COMPONENT_RENDERERS.clear()

    first = point_grid_module._component(key="one")
    second = point_grid_module._component(key="two")

    assert first["key"] == "one" and second["key"] == "two"
    assert len(registrations) == 1
    assert registrations[0][0] == ("sector.point_grid",)
    point_grid_module._COMPONENT_RENDERERS.clear()


def test_versioned_rows_rejects_a_stale_reseed_payload():
    rows = [{"x (mm)": 10.0, "y (mm)": 20.0}]
    assert _versioned_rows(
        {"data_version": "4", "rows": rows}, 4
    ) == rows
    assert _versioned_rows(
        {"data_version": "3", "rows": rows}, 4
    ) is None
    assert _versioned_rows(
        {"payload": {"data_version": "4", "rows": rows}}, 4
    ) == rows
    assert _versioned_rows(rows, 4) is None       # old frontend: seed is unknowable


def test_frontend_uses_only_components_v2_state_api():
    frontend = pathlib.Path(point_grid_module.__file__).resolve().parent / "point_grid_frontend"
    renderer = (frontend / "point_grid.js").read_text(encoding="utf-8")
    wrapper = pathlib.Path(point_grid_module.__file__).read_text(encoding="utf-8")

    assert "export default function renderPointGrid" in renderer
    assert "setStateValue(\"payload\"" in renderer
    assert "new WeakMap()" in renderer       # separate state for all four tables
    assert "st.components.v2.component" in wrapper
    for banned in (
        "components.v1",
        "declare_component",
        "Streamlit.setComponentValue",
        "setFrameHeight",
        "componentReady",
        "window.parent",
        "postMessage",
    ):
        assert banned not in renderer
        assert banned not in wrapper


def test_frontend_is_scoped_accessible_and_theme_aware():
    frontend = pathlib.Path(point_grid_module.__file__).resolve().parent / "point_grid_frontend"
    renderer = (frontend / "point_grid.js").read_text(encoding="utf-8")
    markup = (frontend / "point_grid.html").read_text(encoding="utf-8")
    styles = (frontend / "point_grid.css").read_text(encoding="utf-8")

    assert '<button class="pg-add-row"' in markup
    assert 'role="alert"' in markup and 'aria-live="polite"' in markup
    assert 'document.createElement("button")' in renderer
    assert 'className = "pg-delete-button"' in renderer
    assert 'wrap.addEventListener("paste"' in renderer
    assert 'document.addEventListener("paste"' not in renderer
    for token in (
        "--st-background-color",
        "--st-text-color",
        "--st-border-color",
        "--st-primary-color",
        "--st-dataframe-header-background-color",
    ):
        assert token in styles


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
    at.run()  # rebuild the durable input payload from the edited base table
    at.segmented_control(key="_main_page").set_value("Analysis").run()
    at.button(key="calculate").click().run()
    assert not at.exception
    assert "plastic" in at.session_state["results"]
