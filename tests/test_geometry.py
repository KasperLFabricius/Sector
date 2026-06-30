"""Unit tests for the exact polygon geometry kernels.

The integrals are closed-form, so these tests assert against analytically known
values (rectangles, triangles, circles, sections with holes) to tight
tolerances rather than approximate convergence.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from sector.geometry import (
    AreaMoments,
    _clip_pts,
    _poly_moments,
    area_moments,
    area_moments_rings,
    clip_halfplane,
    concrete_is_connected,
    distance_to_boundary,
    orient,
    points_inside_concrete,
    signed_area,
)

_RECT = [(-0.2, -0.3), (0.2, -0.3), (0.2, 0.3), (-0.2, 0.3)]


def test_solid_outline_is_connected():
    assert concrete_is_connected(_RECT, []) is True


def test_interior_void_keeps_concrete_connected():
    hole = [(-0.05, -0.05), (0.05, -0.05), (0.05, 0.05), (-0.05, 0.05)]
    assert concrete_is_connected(_RECT, [hole]) is True


def test_two_interior_voids_keep_concrete_connected():
    left = [(-0.15, -0.05), (-0.05, -0.05), (-0.05, 0.05), (-0.15, 0.05)]
    right = [(0.05, -0.05), (0.15, -0.05), (0.15, 0.05), (0.05, 0.05)]
    assert concrete_is_connected(_RECT, [left, right]) is True


def test_slot_spanning_the_width_disconnects_the_concrete():
    # A thin slot reaching across the full width cuts the section in two.
    slot = [(-0.3, -0.02), (0.3, -0.02), (0.3, 0.02), (-0.3, 0.02)]
    assert concrete_is_connected(_RECT, [slot]) is False


def test_high_aspect_slot_is_detected():
    # A very wide, thin section (10 m x 50 mm): sizing the grid by the long side
    # alone would collapse the short axis to one row and miss a horizontal slot.
    wide = [(-5.0, -0.025), (5.0, -0.025), (5.0, 0.025), (-5.0, 0.025)]
    slot = [(-6.0, -0.005), (6.0, -0.005), (6.0, 0.005), (-6.0, 0.005)]
    assert concrete_is_connected(wide, [slot]) is False


def test_degenerate_outline_is_treated_as_connected():
    assert concrete_is_connected([(0.0, 0.0), (1.0, 0.0)], []) is True


def test_distance_to_boundary_rectangle_and_hole():
    # A 0.3 x 0.6 rectangle: a point 0.05 above the bottom face is 0.05 from the
    # nearest edge (the bottom), not the further side faces.
    outer = [(0.0, 0.0), (0.3, 0.0), (0.3, 0.6), (0.0, 0.6)]
    assert distance_to_boundary(0.075, 0.05, [outer]) == pytest.approx(0.05)
    assert distance_to_boundary(0.15, 0.30, [outer]) == pytest.approx(0.15)
    # With a central hole the nearest face can be the hole edge.
    hole = [(0.12, 0.27), (0.18, 0.27), (0.18, 0.33), (0.12, 0.33)]
    assert distance_to_boundary(0.15, 0.20, [outer, hole]) == pytest.approx(0.07)


# ---------------------------------------------------------------------------
# points_inside_concrete
# ---------------------------------------------------------------------------

def test_points_inside_solid_section():
    pts = [(0.0, 0.0), (0.1, 0.2), (-0.15, -0.25)]   # all well inside _RECT
    assert points_inside_concrete(pts, _RECT).tolist() == [True, True, True]


def test_point_outside_outline_is_flagged():
    # Above the top face and beyond the right face -> outside the concrete.
    pts = [(0.0, 0.0), (0.0, 0.5), (0.5, 0.0)]
    assert points_inside_concrete(pts, _RECT).tolist() == [True, False, False]


def test_point_inside_a_void_is_flagged():
    hole = [(-0.05, -0.05), (0.05, -0.05), (0.05, 0.05), (-0.05, 0.05)]
    pts = [(0.0, 0.0),      # in the void -> not in concrete
           (0.1, 0.1)]      # in concrete, clear of the void
    assert points_inside_concrete(pts, _RECT, [hole]).tolist() == [False, True]


def test_point_on_a_face_counts_as_inside():
    # A bar at the top face (zero cover) and one hard against a void edge are valid.
    hole = [(-0.05, -0.05), (0.05, -0.05), (0.05, 0.05), (-0.05, 0.05)]
    pts = [(0.0, 0.3),      # exactly on the outer top edge
           (0.05, 0.0)]     # exactly on the void's right edge
    assert points_inside_concrete(pts, _RECT, [hole]).tolist() == [True, True]


def test_points_inside_concrete_empty_and_no_outline():
    assert points_inside_concrete([], _RECT).tolist() == []
    # With no valid outline nothing can be inside it.
    assert points_inside_concrete([(0.0, 0.0)], [(0.0, 0.0), (1.0, 0.0)]).tolist() == [False]


# ---------------------------------------------------------------------------
# signed_area
# ---------------------------------------------------------------------------


def test_signed_area_unit_square_ccw():
    sq = [(0, 0), (1, 0), (1, 1), (0, 1)]  # CCW
    assert signed_area(sq) == pytest.approx(1.0)


def test_signed_area_sign_flips_with_winding():
    sq_ccw = [(0, 0), (1, 0), (1, 1), (0, 1)]
    sq_cw = list(reversed(sq_ccw))
    assert signed_area(sq_cw) == pytest.approx(-1.0)


def test_signed_area_degenerate_is_zero():
    assert signed_area([(0, 0), (1, 1)]) == 0.0
    assert signed_area([(0, 0)]) == 0.0


def test_signed_area_translation_invariant():
    tri = [(0, 0), (2, 0), (0, 3)]
    shifted = [(x + 10.0, y - 5.0) for x, y in tri]
    assert signed_area(shifted) == pytest.approx(signed_area(tri))


# ---------------------------------------------------------------------------
# area_moments -- against analytic values
# ---------------------------------------------------------------------------


def _centered_rect(w: float, h: float):
    """Rectangle centred on the origin, CCW."""
    return [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]


def test_area_moments_centered_rectangle():
    w, h = 2.0, 3.0
    m = area_moments(_centered_rect(w, h))
    assert m.area == pytest.approx(w * h)
    # Centred on origin: first moments vanish.
    assert m.sx == pytest.approx(0.0)
    assert m.sy == pytest.approx(0.0)
    # Second moments about the centroidal axes for a rectangle.
    assert m.syy == pytest.approx(w * h ** 3 / 12.0)  # integral y^2
    assert m.sxx == pytest.approx(h * w ** 3 / 12.0)  # integral x^2
    assert m.sxy == pytest.approx(0.0)  # symmetric


def test_area_moments_offset_rectangle_first_moments():
    # Unit square with lower-left corner at the origin: centroid at (0.5, 0.5).
    sq = [(0, 0), (1, 0), (1, 1), (0, 1)]
    m = area_moments(sq)
    assert m.area == pytest.approx(1.0)
    assert m.sx == pytest.approx(0.5)  # integral x = area * x_centroid
    assert m.sy == pytest.approx(0.5)
    # integral x^2 over [0,1]x[0,1] = 1/3
    assert m.sxx == pytest.approx(1.0 / 3.0)
    assert m.syy == pytest.approx(1.0 / 3.0)
    # integral xy = 1/4
    assert m.sxy == pytest.approx(0.25)


def test_area_moments_right_triangle():
    # Right triangle with legs along the axes, vertices (0,0),(b,0),(0,h).
    b, h = 4.0, 6.0
    tri = [(0, 0), (b, 0), (0, h)]
    m = area_moments(tri)
    assert m.area == pytest.approx(b * h / 2.0)
    # Centroid of a right triangle at (b/3, h/3).
    assert m.sx / m.area == pytest.approx(b / 3.0)
    assert m.sy / m.area == pytest.approx(h / 3.0)
    # integral y^2 over this triangle = b * h^3 / 12
    assert m.syy == pytest.approx(b * h ** 3 / 12.0)
    assert m.sxx == pytest.approx(h * b ** 3 / 12.0)


def test_area_moments_orientation_flips_sign():
    sq = [(0, 0), (1, 0), (1, 1), (0, 1)]
    m_ccw = area_moments(sq)
    m_cw = area_moments(list(reversed(sq)))
    assert m_cw.area == pytest.approx(-m_ccw.area)
    assert m_cw.sxx == pytest.approx(-m_ccw.sxx)
    assert m_cw.sxy == pytest.approx(-m_ccw.sxy)


def test_area_moments_polygon_approximates_circle():
    # A finely sampled circle should match area pi r^2 and I = pi r^4 / 4.
    r = 2.0
    n = 2000
    th = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    verts = np.column_stack([r * np.cos(th), r * np.sin(th)])
    m = area_moments(verts)
    assert m.area == pytest.approx(math.pi * r ** 2, rel=1e-4)
    assert m.sxx == pytest.approx(math.pi * r ** 4 / 4.0, rel=1e-4)
    assert m.syy == pytest.approx(math.pi * r ** 4 / 4.0, rel=1e-4)
    assert m.sxy == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# AreaMoments dataclass behaviour
# ---------------------------------------------------------------------------


def test_area_moments_addition():
    a = AreaMoments(1, 2, 3, 4, 5, 6)
    b = AreaMoments(10, 20, 30, 40, 50, 60)
    s = a + b
    assert (s.area, s.sx, s.sy, s.sxx, s.syy, s.sxy) == (11, 22, 33, 44, 55, 66)


def test_centroid_property():
    sq = [(0, 0), (2, 0), (2, 2), (0, 2)]
    assert area_moments(sq).centroid == pytest.approx((1.0, 1.0))


def test_centroid_zero_area_raises():
    with pytest.raises(ValueError):
        AreaMoments(0, 0, 0, 0, 0, 0).centroid


# ---------------------------------------------------------------------------
# area_moments_rings -- section with a hole
# ---------------------------------------------------------------------------


def test_rings_square_with_central_hole():
    # 4x4 solid (CCW) with a 2x2 hole (CW), both centred on the origin.
    outer = _centered_rect(4.0, 4.0)  # CCW, area +16
    hole = list(reversed(_centered_rect(2.0, 2.0)))  # CW, area -4
    m = area_moments_rings([outer, hole])
    assert m.area == pytest.approx(16.0 - 4.0)
    # Net second moment = outer I minus hole I (both centroidal here).
    expected_syy = (4.0 * 4.0 ** 3 / 12.0) - (2.0 * 2.0 ** 3 / 12.0)
    assert m.syy == pytest.approx(expected_syy)
    assert m.sx == pytest.approx(0.0)
    assert m.sy == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# orient
# ---------------------------------------------------------------------------


def test_orient_to_ccw_and_cw():
    sq_cw = [(0, 0), (0, 1), (1, 1), (1, 0)]  # CW
    ccw = orient(sq_cw, ccw=True)
    assert signed_area(ccw) > 0.0
    cw = orient(sq_cw, ccw=False)
    assert signed_area(cw) < 0.0


def test_orient_preserves_vertex_set():
    sq = [(0, 0), (1, 0), (1, 1), (0, 1)]
    out = orient(sq, ccw=False)
    # Same points, possibly reordered.
    assert {tuple(p) for p in out} == {tuple(map(float, p)) for p in sq}


# ---------------------------------------------------------------------------
# clip_halfplane
# ---------------------------------------------------------------------------


def test_clip_keeps_right_half_of_square():
    # Unit square [0,1]^2; keep x >= 0.5  ->  a=1, b=0, c=-0.5.
    sq = [(0, 0), (1, 0), (1, 1), (0, 1)]
    clipped = clip_halfplane(sq, 1.0, 0.0, -0.5)
    m = area_moments(clipped)
    assert abs(m.area) == pytest.approx(0.5)
    # The retained strip x in [0.5, 1] has centroid x = 0.75.
    assert m.sx / m.area == pytest.approx(0.75)


def test_clip_whole_polygon_inside():
    sq = [(0, 0), (1, 0), (1, 1), (0, 1)]
    clipped = clip_halfplane(sq, 0.0, 1.0, 1.0)  # y >= -1 : all inside
    assert area_moments(clipped).area == pytest.approx(1.0)
    assert clipped.shape[0] == 4


def test_clip_whole_polygon_outside_is_empty():
    sq = [(0, 0), (1, 0), (1, 1), (0, 1)]
    clipped = clip_halfplane(sq, 0.0, 1.0, -5.0)  # y >= 5 : nothing
    assert clipped.shape == (0, 2)
    assert area_moments(clipped).area == 0.0


def test_clip_diagonal_cut_triangle_area():
    # Keep the half of the unit square below the diagonal y <= x, i.e.
    # x - y >= 0  ->  a=1, b=-1, c=0. That retained region is a triangle of
    # area 1/2.
    sq = [(0, 0), (1, 0), (1, 1), (0, 1)]
    clipped = clip_halfplane(sq, 1.0, -1.0, 0.0)
    assert abs(area_moments(clipped).area) == pytest.approx(0.5)


def test_clip_preserves_orientation_sign():
    sq_ccw = [(0, 0), (1, 0), (1, 1), (0, 1)]
    clipped = clip_halfplane(sq_ccw, 1.0, 0.0, -0.5)
    assert signed_area(clipped) > 0.0  # stayed CCW


def test_clip_empty_input():
    assert clip_halfplane([], 1.0, 0.0, 0.0).shape == (0, 2)


def test_clip_eps_shifts_cut_line_consistently():
    # Square [-1, 1] x [0, 1], keep x >= 0 with a tolerance eps = 0.1. The kept
    # region's boundary shifts outward to x = -0.1, and crossing edges must be
    # cut on that same line (not at x = 0), so the area is unbiased.
    sq = [(-1, 0), (1, 0), (1, 1), (-1, 1)]
    clipped = clip_halfplane(sq, 1.0, 0.0, 0.0, eps=0.1)
    m = area_moments(clipped)
    # Retained region x in [-0.1, 1], y in [0, 1]: width 1.1, height 1.
    assert m.area == pytest.approx(1.1)
    assert m.sx / m.area == pytest.approx((-0.1 + 1.0) / 2.0)  # centroid x = 0.45
    # The left edge is cut exactly at x = -0.1.
    assert clipped[:, 0].min() == pytest.approx(-0.1)


# ---------------------------------------------------------------------------
# internal scalar kernels (the fast path the plastic solver calls directly)
# ---------------------------------------------------------------------------


def test_internal_kernels_match_public_path():
    # The list-based kernels back the public NumPy API and are called directly
    # in the hot loop; they must agree with the public path to floating point.
    sq = [(-1.0, -0.5), (2.0, -0.5), (2.0, 1.5), (-1.0, 1.5)]
    a, b, c = 1.0, 0.3, -0.4  # an oblique cut through the polygon

    pub = area_moments(clip_halfplane(sq, a, b, c))

    pts = _clip_pts(sq, a, b, c)
    assert isinstance(pts, list)
    assert all(isinstance(p, tuple) and len(p) == 2 for p in pts)
    intern = _poly_moments(pts)

    assert intern.area == pytest.approx(pub.area)
    assert intern.sx == pytest.approx(pub.sx)
    assert intern.sy == pytest.approx(pub.sy)
    assert intern.sxx == pytest.approx(pub.sxx)
    assert intern.syy == pytest.approx(pub.syy)
    assert intern.sxy == pytest.approx(pub.sxy)


def test_internal_kernels_degenerate_cases():
    # Fewer than three points enclose no area; an all-outside clip is empty.
    assert _poly_moments([(0.0, 0.0), (1.0, 1.0)]) == AreaMoments(0, 0, 0, 0, 0, 0)
    sq = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    assert _clip_pts(sq, 0.0, 1.0, -5.0) == []  # y >= 5 keeps nothing
