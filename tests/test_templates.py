"""Tests for the parametric section and reinforcement builders."""

from __future__ import annotations

import math

import pytest

from sector import templates
from sector.geometry import signed_area
from sector.section import Section


def test_bar_area():
    assert templates.bar_area(20) == pytest.approx(math.pi / 4 * 400)


def test_rectangle_shape_and_area():
    corners = templates.rectangle(0.4, 0.6)
    assert len(corners) == 4
    assert abs(signed_area(corners)) == pytest.approx(0.4 * 0.6)


def test_slab_strip_is_unit_wide():
    corners = templates.slab_strip(0.3)
    assert abs(signed_area(corners)) == pytest.approx(1.0 * 0.3)


def test_t_section_area():
    bf, hf, bw, hw = 1.2, 0.2, 0.3, 0.6
    corners = templates.t_section(bf, hf, bw, hw)
    expected = bf * hf + bw * hw
    assert abs(signed_area(corners)) == pytest.approx(expected)


def test_circular_area_approaches_circle():
    corners = templates.circular(0.6, segments=200)
    assert abs(signed_area(corners)) == pytest.approx(math.pi * 0.3 ** 2, rel=1e-3)


def test_box_outer_and_hole_net_area():
    outer, holes = templates.box(0.8, 1.0, 0.2)
    assert len(holes) == 1
    net = abs(signed_area(outer)) - abs(signed_area(holes[0]))
    assert net == pytest.approx(0.8 * 1.0 - 0.4 * 0.6)


def test_bar_row_count_spacing_and_area():
    bars = templates.bar_row(0.1, -0.3, 0.3, 4, 25)
    assert len(bars) == 4
    xs = [b[0] for b in bars]
    assert xs[0] == pytest.approx(-0.3) and xs[-1] == pytest.approx(0.3)
    assert all(b[2] == pytest.approx(templates.bar_area(25)) for b in bars)
    # evenly spaced
    gaps = [xs[i + 1] - xs[i] for i in range(3)]
    assert max(gaps) == pytest.approx(min(gaps))


def test_bar_row_single_is_centred():
    bars = templates.bar_row(0.0, -0.3, 0.3, 1, 16)
    assert len(bars) == 1 and bars[0][0] == pytest.approx(0.0)


def test_bar_ring_on_circle():
    bars = templates.bar_ring(0.0, 0.0, 0.25, 8, 20)
    assert len(bars) == 8
    assert all(math.hypot(x, y) == pytest.approx(0.25) for x, y, _ in bars)


def test_edge_layer_faces():
    b, h, c = 0.4, 0.6, 0.05
    bottom = templates.edge_layer(b, h, c, 3, 16, "bottom")
    top = templates.edge_layer(b, h, c, 3, 16, "top")
    assert all(y == pytest.approx(-h / 2 + c) for _, y, _ in bottom)
    assert all(y == pytest.approx(h / 2 - c) for _, y, _ in top)
    with pytest.raises(ValueError):
        templates.edge_layer(b, h, c, 1, 16, "diagonal")


def test_templates_build_a_valid_section():
    # A rectangle template plus two rebar rows must produce a usable Section.
    outer = templates.rectangle(0.4, 0.6)
    bars = templates.merge_bars(
        templates.edge_layer(0.4, 0.6, 0.05, 4, 25, "bottom"),
        templates.edge_layer(0.4, 0.6, 0.05, 2, 16, "top"),
    )
    section = Section.from_polygon(corners=outer, bars_xy_area_mm2=bars)
    assert section.gross_area == pytest.approx(0.24)
    assert len(section.bars) == 6
