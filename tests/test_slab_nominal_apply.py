"""Nominal slab point tables and compatibility with saved density sections."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import sector_app as app
from sector.elastic import transformed_properties
from sector.section import Section


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("spacing", [100.0, 150.0, 250.0])
def test_reconcile_nominal_and_saved_integration_points(legacy, spacing):
    intent = {"qsv_shape": "Slab strip", "qsv_qs_rebar_mode": "By spacing",
              "qsv_bot_s": spacing, "qsv_top_s": spacing}
    layout = app._slab_density_layout_from_state(intent, legacy_analysis_points=legacy)
    table = app._rebar_df(app._pts_to_mm(layout["bars"]),
                         diameters_mm=layout["diameters_mm"])
    outer = app.templates.slab_strip(0.3)
    state = {app._QS_APPLIED_SETTINGS_KEY: intent}
    result = app._slab_density_reconciliation(state, outer, [], table)
    assert result["status"] == "VERIFIED"
    assert len(result["analysis_metadata"]) == len(table)
    assert len(table) == (64 if legacy else 2*int(np.ceil(1000/spacing)))
    assert table[app.rebar_table.AREA].sum() == pytest.approx(
        2 * app.templates.bar_area(20) * 1000/spacing)
    assert sum(x * area for x, _y, area in layout["bars"]) == pytest.approx(0, abs=1e-9)
    table.loc[0, app.rebar_table.X] += 1
    assert app._slab_density_reconciliation(state, outer, [], table)["status"] == "UNVERIFIED"


def test_nominal_points_have_discrete_ten_bar_transformed_inertia():
    intent = {"qsv_shape": "Slab strip", "qsv_qs_rebar_mode": "By spacing",
              "qsv_bot_s": 100.0, "qsv_top_s": 100.0}
    layout = app._slab_density_layout_from_state(intent)
    section = Section.from_polygon(app.templates.slab_strip(0.3), layout["bars"])
    props = transformed_properties(section, 6.0)
    area = np.pi * 20**2/4 * 1e-6
    xs = np.arange(-0.45, 0.451, 0.1)
    assert props.area == pytest.approx(0.3 + 5 * 20 * area)
    assert props.cx == pytest.approx(0, abs=1e-12)
    assert props.Iy == pytest.approx(0.3/12 + 5 * 2 * area * (xs**2).sum())
    assert props.Ix == pytest.approx(0.3**3/12 + 5 * 20 * area * 0.1**2)

@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("top_spacing, expected_clear, expected_status", [
    (100.0, 80.0, "PASS"), (40.0, 20.0, "FAIL"),
])
def test_spacing_diagram_uses_checked_coordinates(legacy, top_spacing, expected_clear, expected_status):
    intent = {"qsv_shape": "Slab strip", "qsv_qs_rebar_mode": "By spacing",
              "qsv_bot_s": 200.0, "qsv_top_s": top_spacing}
    layout = app._slab_density_layout_from_state(intent, legacy_analysis_points=legacy)
    table = app._rebar_df(app._pts_to_mm(layout["bars"]), diameters_mm=layout["diameters_mm"])
    outer = app.templates.slab_strip(0.3)
    state = {app._QS_APPLIED_SETTINGS_KEY: intent}
    density = app._slab_density_reconciliation(state, outer, [], table)
    inp = {"slab_density": density, "detailing_edition": app.detailing.EC2_2005,
           "detailing_d_upper": 32.0}
    result = app._clear_spacing_result(inp)
    assert result["status"] == expected_status
    assert result["governing"]["clear_mm"] == pytest.approx(expected_clear)
    fig = app.viz.detailing_geometry_figure(
        outer, [], layout["bars"], [], slab_density=density,
        spacing_pair=result["governing"],
    )
    bars = next(trace for trace in fig.data if trace.name == "reinforcing bar")
    assert len(bars.x) == 5 + round(1000 / top_spacing)
    assert sorted(bars.x) == pytest.approx(sorted(item["x_mm"] for item in density["physical_elements"]))
    pair = next(trace for trace in fig.data if trace.name == "governing spacing pair")
    assert abs(pair.x[1] - pair.x[0]) == pytest.approx(top_spacing)
    assert any(f"c<sub>clear</sub> = {expected_clear:.1f} mm" in str(a.text) for a in fig.layout.annotations)
    table.loc[0, app.rebar_table.DIAMETER] += 1
    inp["slab_density"] = app._slab_density_reconciliation(state, outer, [], table)
    assert app._clear_spacing_result(inp)["status"] == "NOT ASSESSED"
