"""Tests for the Section model and its construction/geometry helpers."""

from __future__ import annotations

import numpy as np
import pytest

from sector.geometry import signed_area
from sector.section import MM2_TO_M2, Bar, Section


def test_from_polygon_converts_bar_area_to_m2():
    sec = Section.from_polygon(
        corners=[(0, 0), (1, 0), (1, 1), (0, 1)],
        bars_xy_area_mm2=[(0.5, 0.5, 491.0)],
    )
    assert len(sec.bars) == 1
    assert sec.bars[0].area == pytest.approx(491.0 * MM2_TO_M2)
    assert sec.bars[0].x == pytest.approx(0.5)


def test_integration_rings_orient_outer_ccw_holes_cw():
    outer = [(0, 0), (4, 0), (4, 4), (0, 4)]  # CCW already
    hole = [(1, 1), (3, 1), (3, 3), (1, 3)]   # CCW (a "wrong" winding for a hole)
    sec = Section([np.array(outer, float), np.array(hole, float)])
    rings = sec.integration_rings()
    assert signed_area(rings[0]) > 0.0  # outer CCW
    assert signed_area(rings[1]) < 0.0  # hole flipped to CW


def test_gross_area_subtracts_holes():
    outer = [(0, 0), (4, 0), (4, 4), (0, 4)]
    hole = [(1, 1), (3, 1), (3, 3), (1, 3)]
    sec = Section([np.array(outer, float), np.array(hole, float)])
    assert sec.gross_area == pytest.approx(16.0 - 4.0)


def test_gross_area_independent_of_input_winding():
    cw = [(0, 0), (0, 1), (1, 1), (1, 0)]  # clockwise (required convention)
    sec = Section([np.array(cw, float)])
    assert sec.gross_area == pytest.approx(1.0)


def test_concrete_vertices_preserve_input_order():
    corners = [(0, 0), (0, 1), (1, 1), (1, 0)]
    sec = Section.from_polygon(corners=corners)
    verts = sec.concrete_vertices()
    assert np.allclose(verts, corners)


def test_empty_concrete_rejected():
    with pytest.raises(ValueError):
        Section([])


def test_degenerate_ring_rejected():
    with pytest.raises(ValueError):
        Section([np.array([(0, 0), (1, 1)], float)])


def test_bar_arrays_shapes():
    sec = Section.from_polygon(
        corners=[(0, 0), (1, 0), (1, 1), (0, 1)],
        bars_xy_area_mm2=[(0.1, 0.2, 100.0), (0.3, 0.4, 200.0)],
    )
    x, y, a = sec.bar_arrays()
    assert x.shape == y.shape == a.shape == (2,)
    assert a[1] == pytest.approx(200.0 * MM2_TO_M2)


@pytest.mark.parametrize("kind", ("bar", "tendon"))
@pytest.mark.parametrize(
    "point",
    (
        (float("nan"), 0.2, 100.0),
        (0.1, float("inf"), 100.0),
        (0.1, 0.2, 0.0),
        (0.1, 0.2, -100.0),
        (0.1, 0.2, float("nan")),
        (0.1, 0.2, float("inf")),
    ),
)
def test_section_rejects_invalid_bar_and_tendon_coordinates_or_area(
    kind,
    point,
):
    reinforcement = {
        "bars_xy_area_mm2": [point],
        "tendons_xy_area_mm2": [point],
    }
    selected = {kind + "s_xy_area_mm2": reinforcement[kind + "s_xy_area_mm2"]}

    with pytest.raises(ValueError):
        Section.from_polygon(
            corners=[(0, 0), (1, 0), (1, 1), (0, 1)],
            **selected,
        )


@pytest.mark.parametrize("kind", ("bar", "tendon"))
@pytest.mark.parametrize(
    "point",
    (
        (True, 0.2, 100.0),
        (np.bool_(True), 0.2, 100.0),
        (0.1, False, 100.0),
        (0.1, 0.2, True),
        (0.1, 0.2, np.bool_(True)),
    ),
)
def test_section_factory_rejects_boolean_reinforcement_fields(kind, point):
    selected = {kind + "s_xy_area_mm2": [point]}

    with pytest.raises(ValueError, match="finite number"):
        Section.from_polygon(
            corners=[(0, 0), (1, 0), (1, 1), (0, 1)],
            **selected,
        )


@pytest.mark.parametrize("kind", ("bar", "tendon"))
@pytest.mark.parametrize(
    "element",
    (
        Bar(True, 0.2, 100.0e-6),
        Bar(np.bool_(True), 0.2, 100.0e-6),
        Bar(0.1, False, 100.0e-6),
        Bar(0.1, 0.2, True),
        Bar(0.1, 0.2, np.bool_(True)),
    ),
)
def test_direct_section_rejects_boolean_reinforcement_fields(kind, element):
    reinforcement = {kind + "s": [element]}

    with pytest.raises(ValueError, match="finite coordinates and a positive area"):
        Section(
            concrete=[np.array([(0, 0), (1, 0), (1, 1), (0, 1)])],
            **reinforcement,
        )
