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


def test_t_section_centred_on_total_depth():
    # The outline must span -H/2 .. H/2 so the app's bottom rebar (placed at
    # -(hf+hw)/2 + cover) lands inside the concrete, not below it.
    bf, hf, bw, hw = 1.2, 0.2, 0.3, 0.6
    corners = templates.t_section(bf, hf, bw, hw)
    ys = [y for _, y in corners]
    height = hf + hw
    assert max(ys) == pytest.approx(height / 2)
    assert min(ys) == pytest.approx(-height / 2)
    # flange/web junction sits hf below the top
    assert max(ys) - (height / 2 - hf) == pytest.approx(hf)


def test_circular_area_approaches_circle():
    corners = templates.circular(0.6, segments=200)
    assert abs(signed_area(corners)) == pytest.approx(math.pi * 0.3 ** 2, rel=1e-3)


def test_box_outer_and_hole_net_area():
    outer, holes = templates.box(0.8, 1.0, 0.2)
    assert len(holes) == 1
    net = abs(signed_area(outer)) - abs(signed_area(holes[0]))
    assert net == pytest.approx(0.8 * 1.0 - 0.4 * 0.6)


def test_box_rejects_overthick_wall():
    # A wall that fills (or exceeds) half the section leaves no valid cavity.
    with pytest.raises(ValueError):
        templates.box(0.4, 0.4, 0.2)   # 2*wall == b
    with pytest.raises(ValueError):
        templates.box(0.4, 0.4, 0.3)   # 2*wall > b
    with pytest.raises(ValueError):
        templates.box(0.4, 0.4, 0.0)   # non-positive wall


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


def test_count_for_spacing():
    # phi @ 150 over a 0.90 m face -> 6 gaps of exactly 150 mm = 7 bars.
    assert templates.count_for_spacing(0.90, 0.15) == 7
    # A face that does not divide evenly gets an extra bar (a tighter actual gap,
    # never wider than the target): 0.50 m -> ceil(3.33)+1 = 5 bars (125 mm), not 4.
    assert templates.count_for_spacing(0.50, 0.15) == 5
    # Degenerate spans give a single bar; a positive span never gives fewer than 2.
    assert templates.count_for_spacing(0.0, 0.15) == 1
    assert templates.count_for_spacing(0.10, 0.15) == 2
    # The actual centre-to-centre spacing never exceeds the target, for any face.
    for span in (0.30, 0.50, 0.77, 0.90, 1.23):
        n = templates.count_for_spacing(span, 0.15)
        bars = templates.bar_row(0.0, -span / 2, span / 2, n, 12)
        gaps = [bars[i + 1][0] - bars[i][0] for i in range(n - 1)]
        assert max(gaps) <= 0.15 + 1e-9, span


def test_bar_ring_on_circle():
    bars = templates.bar_ring(0.0, 0.0, 0.25, 8, 20)
    assert len(bars) == 8
    assert all(math.hypot(x, y) == pytest.approx(0.25) for x, y, _ in bars)


def test_point_row_count_spacing_and_area():
    pts = templates.point_row(-0.2, -0.3, 0.3, 4, 150.0)
    assert len(pts) == 4
    xs = [p[0] for p in pts]
    assert xs[0] == pytest.approx(-0.3) and xs[-1] == pytest.approx(0.3)
    assert all(p[1] == pytest.approx(-0.2) for p in pts)
    assert all(p[2] == pytest.approx(150.0) for p in pts)  # area given directly
    gaps = [xs[i + 1] - xs[i] for i in range(3)]
    assert max(gaps) == pytest.approx(min(gaps))


def test_point_row_single_is_centred_and_empty_for_zero():
    assert templates.point_row(0.0, -0.3, 0.3, 1, 100.0)[0][0] == pytest.approx(0.0)
    assert templates.point_row(0.0, -0.3, 0.3, 0, 100.0) == []


def test_point_ring_on_circle_with_given_area():
    pts = templates.point_ring(0.0, 0.0, 0.25, 6, 140.0)
    assert len(pts) == 6
    assert all(math.hypot(x, y) == pytest.approx(0.25) for x, y, _ in pts)
    assert all(a == pytest.approx(140.0) for _, _, a in pts)


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
