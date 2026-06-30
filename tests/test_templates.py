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


def test_bar_layers_stacks_rows_into_the_section():
    # Two bottom layers (6 bars each), the first at the cover line y0 and the next
    # one layer_spacing further up. direction = +1 for a bottom face.
    y0, ls = -0.27, 0.06
    bars = templates.bar_layers(y0, 1.0, 2, ls, -0.15, 0.15, 6, 16)
    assert len(bars) == 12
    ys = sorted({round(b[1], 6) for b in bars})
    assert ys == [pytest.approx(y0), pytest.approx(y0 + ls)]   # two distinct rows
    # A single layer is just a bar_row at the face.
    one = templates.bar_layers(y0, 1.0, 1, ls, -0.15, 0.15, 6, 16)
    assert one == templates.bar_row(y0, -0.15, 0.15, 6, 16)


def test_bar_layers_span_at_follows_a_width_step():
    # span_at(y) sets each row's span from its depth, so a top row narrows once it
    # drops below a width step (a T-section flange -> web).
    def span(y):
        return (-0.6, 0.6) if y >= 0.2 else (-0.15, 0.15)
    bars = templates.bar_layers(0.35, -1.0, 3, 0.1, -0.6, 0.6, 2, 16, span_at=span)
    by_y = {}
    for x, y, _a in bars:
        by_y.setdefault(round(y, 6), []).append(x)
    assert max(by_y[0.35]) == pytest.approx(0.6)     # in the flange -> wide span
    assert max(by_y[0.15]) == pytest.approx(0.15)    # below the step -> web span


def test_bar_layers_n_at_recomputes_count_per_row():
    # By spacing the bar count follows each row's span: a narrowed row gets fewer bars
    # (the fixed n_per is ignored when n_at is given).
    def span(y):
        return (-0.55, 0.55) if y >= 0.2 else (-0.10, 0.10)
    def count(xs, xe):
        return templates.count_for_spacing(xe - xs, 0.15)
    bars = templates.bar_layers(0.35, -1.0, 2, 0.25, -0.55, 0.55, 99, 16,
                                span_at=span, n_at=count)
    by_y = {}
    for x, y, _a in bars:
        by_y.setdefault(round(y, 6), []).append(x)
    assert len(by_y[0.35]) == templates.count_for_spacing(1.1, 0.15)    # wide row
    assert len(by_y[0.10]) == templates.count_for_spacing(0.20, 0.15)   # narrow row
    assert len(by_y[0.10]) < len(by_y[0.35])


def test_bar_layers_direction_moves_top_rows_down():
    # direction = -1 (top face): later layers move toward the section interior (down).
    y0, ls = 0.27, 0.05
    bars = templates.bar_layers(y0, -1.0, 3, ls, -0.15, 0.15, 4, 20)
    ys = sorted({round(b[1], 6) for b in bars})
    assert ys == [pytest.approx(y0 - 2 * ls), pytest.approx(y0 - ls), pytest.approx(y0)]


def test_ring_radius_caps_at_the_polygon_apothem():
    # Zero cover -> the inscribed N-gon's apothem (just inside the polygon), not the
    # full radius, so a bar between two vertices is not left outside the outline.
    r = templates.ring_radius(0.6, 0.0)
    assert r == pytest.approx(0.3 * math.cos(math.pi / templates.CIRCLE_SEGMENTS))
    assert r < 0.3
    assert templates.ring_radius(0.6, 0.05) == pytest.approx(0.25)   # a real cover: as-is


def test_box_row_xs_full_width_in_wall_split_in_hollow():
    # b=0.8, h=1.0, wall=0.2, cover=0.05. Bottom wall spans y in [-0.5, -0.3].
    full = templates.box_row_xs(-0.45, 0.8, 1.0, 0.2, 0.05, 3)     # in the bottom wall
    assert full == [pytest.approx(-0.35), pytest.approx(0.0), pytest.approx(0.35)]
    split = templates.box_row_xs(-0.1, 0.8, 1.0, 0.2, 0.05, 3)     # in the hollow
    assert len(split) == 3                                         # count preserved
    assert all(abs(x) >= 0.2 for x in split)                       # in the side walls


def test_box_layers_stacks_rows_and_carries_area():
    rows = templates.box_layers(-0.45, 1.0, 2, 0.35, 0.8, 1.0, 0.2, 0.05, 3, 314.0)
    assert len(rows) == 6                                          # 2 layers x 3
    assert all(r[2] == 314.0 for r in rows)
    # Layer 1 (y=-0.45, bottom wall) full width; layer 2 (y=-0.10, hollow) in the walls.
    assert all(abs(x) >= 0.2 for x, y, _a in rows if y > -0.2)


def test_point_layers_stacks_tendon_rows():
    # The tendon analogue of bar_layers: stack rows of point areas from a face.
    y0, ls = -0.27, 0.06
    tendons = templates.point_layers(y0, 1.0, 3, ls, -0.15, 0.15, 4, 150.0)
    assert len(tendons) == 12                                  # 3 rows x 4
    ys = sorted({round(t[1], 6) for t in tendons})
    assert ys == [pytest.approx(y0), pytest.approx(y0 + ls), pytest.approx(y0 + 2 * ls)]
    assert all(t[2] == 150.0 for t in tendons)                 # area carried through
    one = templates.point_layers(y0, 1.0, 1, ls, -0.15, 0.15, 4, 150.0)
    assert one == templates.point_row(y0, -0.15, 0.15, 4, 150.0)


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
