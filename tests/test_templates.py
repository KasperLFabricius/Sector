"""Tests for the parametric section and reinforcement builders."""

from __future__ import annotations

import math

import pytest

from sector import templates
from sector.geometry import (
    area_moments_rings,
    orient,
    signed_area,
    validate_section_topology,
)
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


def _net_properties(outer, holes=()):
    rings = [orient(outer, ccw=True)]
    rings.extend(orient(hole, ccw=False) for hole in holes)
    moments = area_moments_rings(rings)
    return moments.area, moments.centroid


def _assert_valid_template(outer, holes=()):
    validation = validate_section_topology(outer, holes)
    assert validation.valid, validation.message


def test_inverted_t_is_a_vertical_reflection_with_equal_area():
    upright = templates.t_section(1.2, 0.2, 0.3, 0.6)
    inverted = templates.t_section(
        1.2, 0.2, 0.3, 0.6, orientation="inverted"
    )
    area_up, centroid_up = _net_properties(upright)
    area_down, centroid_down = _net_properties(inverted)

    _assert_valid_template(inverted)
    assert area_down == pytest.approx(area_up)
    assert centroid_down[0] == pytest.approx(centroid_up[0])
    assert centroid_down[1] == pytest.approx(-centroid_up[1])
    assert inverted == [(x, -y) for x, y in upright]


def test_trapezoid_exact_area_centroid_and_topology():
    bottom, top, height = 1.2, 0.6, 0.8
    outer = templates.trapezoid(bottom, top, height)
    area, centroid = _net_properties(outer)
    expected_y_from_bottom = height * (bottom + 2.0 * top) / (
        3.0 * (bottom + top)
    )

    _assert_valid_template(outer)
    assert len(outer) == 4
    assert (min(x for x, _y in outer), max(x for x, _y in outer)) == pytest.approx(
        (-bottom / 2.0, bottom / 2.0)
    )
    assert (min(y for _x, y in outer), max(y for _x, y in outer)) == pytest.approx(
        (-height / 2.0, height / 2.0)
    )
    assert area == pytest.approx(0.5 * (bottom + top) * height)
    assert centroid == pytest.approx(
        (0.0, -height / 2.0 + expected_y_from_bottom)
    )


def test_l_section_exact_area_centroid_and_topology():
    width, height, web, flange = 1.0, 1.2, 0.2, 0.25
    outer = templates.l_section(width, height, web, flange)
    area, centroid = _net_properties(outer)
    web_area = web * height
    flange_extension_area = (width - web) * flange
    expected_area = web_area + flange_extension_area
    extension_x = web / 2.0
    extension_y = -height / 2.0 + flange / 2.0

    _assert_valid_template(outer)
    assert len(outer) == 6
    assert area == pytest.approx(expected_area)
    assert centroid == pytest.approx(
        (
            (
                web_area * (-width / 2.0 + web / 2.0)
                + flange_extension_area * extension_x
            )
            / expected_area,
            flange_extension_area * extension_y / expected_area,
        )
    )


def test_i_section_exact_area_centroid_and_topology():
    flange_width, flange_thickness = 1.0, 0.2
    web_width, web_height = 0.25, 0.8
    outer = templates.i_section(
        flange_width, flange_thickness, web_width, web_height
    )
    area, centroid = _net_properties(outer)

    _assert_valid_template(outer)
    assert len(outer) == 12
    assert area == pytest.approx(
        2.0 * flange_width * flange_thickness + web_width * web_height
    )
    assert centroid == pytest.approx((0.0, 0.0))


def test_u_section_exact_area_centroid_and_topology():
    width, height, web, base = 1.0, 1.2, 0.2, 0.25
    outer = templates.u_section(width, height, web, base)
    area, centroid = _net_properties(outer)
    base_area = width * base
    upright_web_area = web * (height - base)
    expected_area = base_area + 2.0 * upright_web_area
    base_y = -height / 2.0 + base / 2.0
    upright_web_y = base / 2.0

    _assert_valid_template(outer)
    assert len(outer) == 8
    assert area == pytest.approx(expected_area)
    assert centroid == pytest.approx(
        (
            0.0,
            (
                base_area * base_y
                + 2.0 * upright_web_area * upright_web_y
            )
            / expected_area,
        )
    )


def test_annulus_exact_polygon_area_centroid_and_topology():
    outer_diameter, inner_diameter, segments = 0.8, 0.4, 96
    outer, holes = templates.annulus(
        outer_diameter, inner_diameter, segments=segments
    )
    area, centroid = _net_properties(outer, holes)
    factor = 0.5 * segments * math.sin(2.0 * math.pi / segments)
    expected_area = factor * (
        (outer_diameter / 2.0) ** 2 - (inner_diameter / 2.0) ** 2
    )

    _assert_valid_template(outer, holes)
    assert len(outer) == segments
    assert len(holes[0]) == segments
    assert len(holes) == 1
    assert area == pytest.approx(expected_area)
    assert centroid == pytest.approx((0.0, 0.0), abs=1.0e-12)


@pytest.mark.parametrize(
    ("builder", "args", "match"),
    [
        (templates.trapezoid, (1.0, 0.0, 0.8), "top width"),
        (templates.l_section, (1.0, 1.2, 1.0, 0.2), "web thickness"),
        (templates.l_section, (1.0, 1.2, 0.2, 1.2), "flange thickness"),
        (templates.i_section, (1.0, 0.2, 1.0, 0.8), "web width"),
        (templates.u_section, (1.0, 1.2, 0.5, 0.2), "twice"),
        (templates.u_section, (1.0, 1.2, 0.2, 1.2), "base thickness"),
        (templates.annulus, (0.8, 0.8), "inner diameter"),
        (templates.t_section, (1.0, 0.2, 1.0, 0.8), "web width"),
    ],
)
def test_expanded_templates_reject_invalid_dimensions(builder, args, match):
    with pytest.raises(ValueError, match=match):
        builder(*args)


@pytest.mark.parametrize("bad", (0.0, -1.0, math.inf, math.nan))
def test_expanded_templates_reject_nonpositive_or_nonfinite_dimensions(bad):
    with pytest.raises(ValueError):
        templates.trapezoid(1.0, 0.8, bad)


def test_t_section_rejects_unknown_orientation():
    with pytest.raises(ValueError, match="orientation"):
        templates.t_section(1.2, 0.2, 0.3, 0.6, orientation="sideways")


@pytest.mark.parametrize(
    ("builder", "args", "returns_holes"),
    [
        (templates.trapezoid, (1.2, 0.6, 0.8), False),
        (templates.l_section, (1.0, 1.2, 0.2, 0.25), False),
        (templates.i_section, (1.0, 0.2, 0.25, 0.8), False),
        (templates.u_section, (1.0, 1.2, 0.2, 0.25), False),
        (templates.annulus, (0.8, 0.4), True),
    ],
)
def test_expanded_templates_build_a_section(builder, args, returns_holes):
    generated = builder(*args)
    outer, holes = generated if returns_holes else (generated, [])
    section = Section.from_polygon(corners=outer, holes=holes)
    assert section.gross_area > 0.0


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


def test_bar_layers_n_extra_sets_the_upper_layer_count():
    # The first layer keeps n_per; the stacked layers above it take n_extra, so an
    # upper layer can hold a different bar count than the main row.
    bars = templates.bar_layers(-0.25, 1.0, 3, 0.06, -0.15, 0.15, 6, 16, n_extra=3)
    by_y = {}
    for x, y, _a in bars:
        by_y.setdefault(round(y, 6), []).append(x)
    ys = sorted(by_y)
    assert len(by_y[ys[0]]) == 6            # first (bottom) layer -> n_per
    assert len(by_y[ys[1]]) == 3            # upper layers -> n_extra
    assert len(by_y[ys[2]]) == 3
    # Without n_extra every layer keeps n_per (unchanged behaviour).
    same = templates.bar_layers(-0.25, 1.0, 2, 0.06, -0.15, 0.15, 6, 16)
    assert sum(1 for _ in same) == 12


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


def test_annulus_ring_radius_stays_outside_void_and_fails_closed():
    radius = templates.annulus_ring_radius(0.8, 0.4, 0.05)
    assert radius == pytest.approx(0.35)
    outer, holes = templates.annulus(0.8, 0.4)
    bars = templates.bar_ring(0.0, 0.0, radius, 12, 20.0)
    from sector.geometry import points_inside_concrete

    assert points_inside_concrete(
        [(x, y) for x, y, _area in bars], outer, holes
    ).all()
    assert templates.annulus_ring_radius(0.8, 0.4, 0.20) == pytest.approx(0.20)
    with pytest.raises(ValueError, match="annulus void"):
        templates.annulus_ring_radius(0.8, 0.4, 0.25)


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


def test_point_layers_span_at_keeps_stepped_rows_in_the_web():
    def span(y):
        return (-0.5, 0.5) if y <= -0.2 else (-0.1, 0.1)

    tendons = templates.point_layers(
        -0.35, 1.0, 2, 0.25, -0.5, 0.5, 3, 150.0, span_at=span
    )
    lower = [point for point in tendons if point[1] < -0.2]
    upper = [point for point in tendons if point[1] > -0.2]
    assert max(abs(point[0]) for point in lower) == pytest.approx(0.5)
    assert max(abs(point[0]) for point in upper) == pytest.approx(0.1)


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


def test_unit_width_t20_at_200_is_exactly_five_bar_equivalents():
    row = templates.unit_width_bar_row(0.10, 1.0, 0.20, 20.0)
    nominal = templates.unit_width_nominal_bar_row(0.10, 1.0, 0.20, 20.0)

    assert templates.unit_width_bar_equivalents(1.0, 0.20) == pytest.approx(5.0)
    assert templates.count_for_unit_width(1.0, 0.20) == 5
    assert len(row) == 32
    assert [point[0] for point in nominal] == pytest.approx(
        [-0.40, -0.20, 0.0, 0.20, 0.40]
    )
    assert all(point[1] == pytest.approx(0.10) for point in row)
    assert sum(point[2] for point in row) == pytest.approx(
        5.0 * templates.bar_area(20.0)
    )
    assert sum(point[2] for point in row) == pytest.approx(1570.7963267948965)
    assert sum(point[2] for point in nominal) == pytest.approx(1570.7963267948965)
    assert sum(point[0] * point[2] for point in row) == pytest.approx(0.0, abs=1e-12)
    assert sum(point[0] * point[2] for point in nominal) == pytest.approx(
        0.0, abs=1e-12
    )


def test_non_divisible_unit_width_keeps_exact_density_not_four_full_bars():
    row = templates.unit_width_bar_row(-0.10, 1.0, 0.30, 20.0)
    nominal = templates.unit_width_nominal_bar_row(-0.10, 1.0, 0.30, 20.0)
    nominal_interleave = templates.unit_width_nominal_bar_row(
        -0.10, 1.0, 0.30, 16.0, staggered=True
    )

    assert templates.unit_width_bar_equivalents(1.0, 0.30) == pytest.approx(10.0 / 3.0)
    assert len(row) == 32
    assert [point[0] for point in nominal] == pytest.approx(
        [-0.45, -0.15, 0.15, 0.45]
    )
    assert [nominal[i + 1][0] - nominal[i][0] for i in range(3)] == pytest.approx(
        [0.30, 0.30, 0.30]
    )
    assert sum(point[2] for point in row) == pytest.approx(
        templates.bar_area(20.0) / 0.30
    )
    assert sum(point[2] for point in nominal) == pytest.approx(
        templates.bar_area(20.0) / 0.30
    )
    assert sum(point[0] * point[2] for point in nominal) == pytest.approx(
        0.0, abs=1e-12
    )
    assert nominal[0][2] == pytest.approx(2.0 / 3.0 * templates.bar_area(20.0))
    assert [point[0] for point in nominal_interleave] == pytest.approx(
        [-0.30, 0.0, 0.30]
    )
    assert [point[0] for point in nominal_interleave] == pytest.approx(
        [0.5 * (nominal[index][0] + nominal[index + 1][0]) for index in range(3)]
    )
    assert sum(point[2] for point in nominal_interleave) == pytest.approx(
        templates.bar_area(16.0) / 0.30
    )
    assert sum(
        point[0] * point[2] for point in nominal_interleave
    ) == pytest.approx(0.0, abs=1e-12)


def test_unit_width_layers_preserve_each_face_area_and_allow_distinct_rows():
    main = templates.unit_width_bar_layers(
        -0.12, 1.0, 2, 0.04, 1.0, 0.20, 20.0
    )
    interleaved = templates.unit_width_bar_layers(
        -0.12, 1.0, 1, 0.04, 1.0, 0.20, 16.0, staggered=True
    )

    assert len(main) == 64
    assert len(interleaved) == 33
    assert sum(point[2] for point in main) == pytest.approx(
        2.0 * 5.0 * templates.bar_area(20.0)
    )
    assert sum(point[2] for point in interleaved) == pytest.approx(
        5.0 * templates.bar_area(16.0)
    )
    assert {point[0] for point in main[:32]}.isdisjoint(
        {point[0] for point in interleaved}
    )
    assert [point[0] for point in interleaved[1:-1]] == pytest.approx(
        [0.5 * (main[i][0] + main[i + 1][0]) for i in range(31)]
    )
    assert sum(point[0] * point[2] for point in main) == pytest.approx(0.0, abs=1e-12)
    assert sum(point[0] * point[2] for point in interleaved) == pytest.approx(
        0.0, abs=1e-12
    )

    nominal_main = templates.unit_width_nominal_bar_row(
        -0.12, 1.0, 0.20, 20.0
    )
    nominal_interleave = templates.unit_width_nominal_bar_row(
        -0.12, 1.0, 0.20, 16.0, staggered=True
    )
    assert [point[0] for point in nominal_main] == pytest.approx(
        [-0.4, -0.2, 0.0, 0.2, 0.4]
    )
    assert [point[0] for point in nominal_interleave] == pytest.approx(
        [-0.5, -0.3, -0.1, 0.1, 0.3, 0.5]
    )
    assert sum(point[2] for point in nominal_interleave) == pytest.approx(
        5.0 * templates.bar_area(16.0)
    )
    assert sum(point[0] * point[2] for point in nominal_interleave) == pytest.approx(
        0.0, abs=1e-12
    )

    boundary_primary = templates.unit_width_nominal_bar_row(
        0.12, 1.0, 0.50, 20.0
    )
    boundary_interleave = templates.unit_width_nominal_bar_row(
        0.12, 1.0, 0.50, 16.0, staggered=True
    )
    assert [point[0] for point in boundary_primary] == pytest.approx([-0.25, 0.25])
    assert [point[0] for point in boundary_interleave] == pytest.approx(
        [-0.50, 0.0, 0.50]
    )
    assert boundary_interleave[0][2] == pytest.approx(
        0.5 * templates.bar_area(16.0)
    )
    assert boundary_interleave[-1][2] == pytest.approx(
        0.5 * templates.bar_area(16.0)
    )
    assert sum(point[2] for point in boundary_interleave) == pytest.approx(
        2.0 * templates.bar_area(16.0)
    )
    assert sum(
        point[0] * point[2] for point in boundary_interleave
    ) == pytest.approx(0.0, abs=1e-12)


def test_unit_width_representation_stays_bounded_and_rejects_nonfinite_area():
    dense = templates.unit_width_bar_row(0.0, 1.0, 1.0e-6, 20.0)

    assert len(dense) == 32
    assert sum(point[2] for point in dense) == pytest.approx(
        templates.bar_area(20.0) * 1.0e6
    )
    with pytest.raises(ValueError, match="too many nominal positions"):
        templates.unit_width_nominal_bar_row(0.0, 1.0, 1.0e-6, 20.0)
    with pytest.raises(ValueError, match="reinforcement area must be finite"):
        templates.unit_width_bar_row(0.0, 1.0, 0.20, 1.0e308)


def test_t32_at_65_retains_nominal_clear_spacing_and_passes_boundary():
    from sector import detailing

    row = templates.unit_width_nominal_bar_row(0.0, 1.0, 0.065, 32.0)
    elements = [
        {
            "id": f"R{index}",
            "kind": "bar",
            "x_mm": x * 1000.0,
            "y_mm": y * 1000.0,
            "diameter_mm": 32.0,
        }
        for index, (x, y, _area) in enumerate(row, start=1)
    ]

    result = detailing.clear_spacing(
        elements,
        d_upper_mm=16.0,
        edition=detailing.EC2_2005,
    )

    assert result["status"] == "PASS"
    assert result["governing"]["centre_distance_mm"] == pytest.approx(65.0)
    assert result["governing"]["clear_mm"] == pytest.approx(33.0)


def test_t20_at_41_uses_entered_clear_spacing_not_quadrature_gap():
    from sector import detailing

    def elements(row):
        return [
            {
                "id": f"R{index}",
                "kind": "bar",
                "x_mm": x * 1000.0,
                "y_mm": y * 1000.0,
                "diameter_mm": 20.0,
            }
            for index, (x, y, _area) in enumerate(row, start=1)
        ]

    nominal = detailing.clear_spacing(
        elements(templates.unit_width_nominal_bar_row(0.0, 1.0, 0.041, 20.0)),
        d_upper_mm=16.0,
        edition=detailing.EC2_2005,
    )
    represented = detailing.clear_spacing(
        elements(templates.unit_width_bar_row(0.0, 1.0, 0.041, 20.0)),
        d_upper_mm=16.0,
        edition=detailing.EC2_2005,
    )

    assert nominal["status"] == "PASS"
    assert nominal["governing"]["centre_distance_mm"] == pytest.approx(41.0)
    assert nominal["governing"]["clear_mm"] == pytest.approx(21.0)
    assert represented["status"] == "FAIL"
    assert represented["governing"]["centre_distance_mm"] == pytest.approx(31.25)
    assert represented["governing"]["clear_mm"] == pytest.approx(11.25)


def test_interleaved_nominal_series_retains_half_spacing_for_detailing():
    from sector import detailing

    rows = []
    for role, diameter, staggered in (
        ("primary", 20.0, False),
        ("interleave", 16.0, True),
    ):
        for index, (x, y, area) in enumerate(
            templates.unit_width_nominal_bar_row(
                0.0, 1.0, 0.20, diameter, staggered=staggered
            ),
            start=1,
        ):
            rows.append(
                {
                    "id": f"{role} {index}",
                    "kind": "bar",
                    "x_mm": x * 1000.0,
                    "y_mm": y * 1000.0,
                    "area_mm2": area,
                    "diameter_mm": diameter,
                }
            )

    result = detailing.clear_spacing(
        rows,
        d_upper_mm=16.0,
        edition=detailing.EC2_2005,
    )

    assert result["status"] == "PASS"
    assert result["governing"]["centre_distance_mm"] == pytest.approx(100.0)
    assert result["governing"]["clear_mm"] == pytest.approx(82.0)


def test_slab_density_quadrature_controls_cross_axis_capacity_over_spacing_range():
    from sector.materials import Concrete, MildSteel
    from sector.plastic import solve_plastic
    from sector.section import Section

    outer = [(-0.5, -0.15), (0.5, -0.15), (0.5, 0.15), (-0.5, 0.15)]
    concrete = Concrete(fck=35.0, gamma_c=1.5, curve=2)
    steel = MildSteel(
        fytk=500.0,
        fyck=500.0,
        futk=500.0,
        eut=0.05,
        gamma_y=1.15,
        gamma_u=1.15,
        gamma_E=1.0,
        curve=1,
    )
    full_area = templates.bar_area(20.0)

    def capacities(row):
        section = Section.from_polygon(
            corners=outer,
            bars_xy_area_mm2=[
                (x, y, area)
                for y in (-0.1, 0.1)
                for x, _row_y, area in row
            ],
        )
        points = solve_plastic(
            section, concrete, steel, 0.0, 0.0, 270.0, 90.0
        )
        return (
            max(point.Mx for point in points),
            min(point.Mx for point in points),
            max(point.My for point in points),
            min(point.My for point in points),
        )

    t20_at_300 = None
    spacing_values_mm = sorted(
        {float(value) for value in range(10, 1001, 5)}
        | {41.0, 333.333, 999.999}
    )
    for spacing in (value / 1000.0 for value in spacing_values_mm):
        candidate = templates.unit_width_bar_row(0.0, 1.0, spacing, 20.0)
        equivalents = 1.0 / spacing
        reference = [
            (
                -0.5 + (index + 0.5) / 200.0,
                0.0,
                full_area * equivalents / 200.0,
            )
            for index in range(200)
        ]
        mx_max, mx_min, my_max, my_min = capacities(candidate)
        ref_mx_max, _ref_mx_min, ref_my_max, _ref_my_min = capacities(reference)
        assert mx_max == pytest.approx(ref_mx_max, rel=1.0e-12)
        assert my_max == pytest.approx(ref_my_max, rel=1.0e-3)
        assert mx_max == pytest.approx(abs(mx_min), rel=2.0e-5)
        assert my_max == pytest.approx(abs(my_min), rel=2.0e-5)
        if spacing == 0.30:
            t20_at_300 = (mx_max, my_max, ref_my_max)

    assert t20_at_300 == pytest.approx(
        (115.3594814553832, 405.2314311357419, 405.2429397303871),
        rel=1.0e-8,
    )


def test_interleaved_density_layers_keep_symmetric_section_capacity():
    from sector.materials import Concrete, MildSteel
    from sector.plastic import solve_plastic
    from sector.section import Section

    bars = []
    for y in (-0.10, 0.10):
        bars.extend(templates.unit_width_bar_row(y, 1.0, 0.30, 20.0))
        bars.extend(
            templates.unit_width_bar_row(
                y, 1.0, 0.30, 16.0, staggered=True
            )
        )
    section = Section.from_polygon(
        corners=[(-0.5, -0.15), (0.5, -0.15), (0.5, 0.15), (-0.5, 0.15)],
        bars_xy_area_mm2=bars,
    )
    concrete = Concrete(fck=35.0, gamma_c=1.5, curve=2)
    steel = MildSteel(
        fytk=500.0,
        fyck=500.0,
        futk=500.0,
        eut=0.05,
        gamma_y=1.15,
        gamma_u=1.15,
        gamma_E=1.0,
        curve=1,
    )

    points = solve_plastic(
        section, concrete, steel, 0.0, 0.0, 270.0, 90.0
    )
    mx_values = [point.Mx for point in points]
    my_values = [point.My for point in points]

    assert max(mx_values) == pytest.approx(abs(min(mx_values)), rel=2.0e-5)
    assert max(my_values) == pytest.approx(abs(min(my_values)), rel=2.0e-5)
    assert sum(x * area for x, _y, area in bars) == pytest.approx(0.0, abs=1e-10)


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
