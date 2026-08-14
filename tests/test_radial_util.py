"""Unit test for the plastic utilisation helper.

``_radial_util`` rates an applied (Mx, My) point against the M-M capacity
envelope: the applied radius over the distance from the origin to where the load
ray crosses the envelope polygon. The envelope is the closed polygon through the
swept capacity points in sweep order -- the straight chords the M-M diagram
draws -- so the utilisation is measured against the chord, not a radial
interpolation of the vertex radii (which bulges outside the chords and would
understate utilisation).
"""

from __future__ import annotations

import json
import math
import pathlib
import sys
from fractions import Fraction

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "app"))


def _radial_util():
    from sector.combined import radial_util
    return radial_util


def _radial_result():
    from sector.combined import radial_util_result
    return radial_util_result


def _diamond(r=100.0):
    # Four-point envelope with vertices on the axes; the edges are the straight
    # chords between them (the largest chord-vs-radius gap, so the behaviour is
    # unambiguous).
    return [r, 0.0, -r, 0.0], [0.0, r, 0.0, -r]


def test_util_at_a_vertex_is_the_vertex_radius():
    # A load ray that passes through a sweep point sees that vertex radius exactly
    # (chord and radius coincide there). ``_radial_util`` returns (util, gov).
    f = _radial_util()
    mx, my = _diamond(100.0)
    assert f(mx, my, 50.0, 0.0)[0] == pytest.approx(0.5)  # along +Mx -> (100, 0) vertex
    assert f(mx, my, 0.0, 80.0)[0] == pytest.approx(0.8)  # along +My -> (0, 100) vertex
    assert f(mx, my, 0.0, 0.0) == (0.0, None)             # no applied moment -> 0
    assert f(mx, my, 150.0, 0.0)[0] == pytest.approx(1.5)  # outside the envelope


def test_util_follows_the_chord_not_the_radius():
    # Between sweep points the capacity is the chord, not the (larger) radial
    # interpolation of the vertex radii.
    f = _radial_util()
    mx, my = _diamond(100.0)
    # 45 deg: the chord from (100, 0) to (0, 100) is the line Mx + My = 100, which
    # the ray (t, t) crosses at (50, 50) -> capacity radius 50*sqrt(2) ~ 70.71
    # (a radial interpolation would wrongly give 100).
    cap = 50.0 * np.sqrt(2.0)
    assert f(mx, my, 35.0, 35.0)[0] == pytest.approx(35.0 * np.sqrt(2.0) / cap)
    assert f(mx, my, 50.0, 50.0)[0] == pytest.approx(1.0)  # exactly on the chord
    assert f(mx, my, 100.0, 100.0)[0] == pytest.approx(2.0)  # twice the chord distance


def test_util_uses_the_capacity_in_the_applied_direction():
    # A section stronger about x (axis intercepts 100 / 50): the same applied radius
    # gives a different utilisation depending on direction.
    f = _radial_util()
    mx, my = [100.0, 0.0, -100.0, 0.0], [0.0, 50.0, 0.0, -50.0]
    assert f(mx, my, 50.0, 0.0)[0] == pytest.approx(0.5)  # along Mx: 50 / 100
    assert f(mx, my, 0.0, 25.0)[0] == pytest.approx(0.5)  # along My: 25 / 50
    assert f(mx, my, 0.0, 50.0)[0] == pytest.approx(1.0)  # My capacity, on boundary


def test_util_matches_dense_circle_radius():
    # On a finely sampled circular envelope the chord ~ the radius, so a ray through
    # a vertex still reads the radius to good precision.
    f = _radial_util()
    th = np.linspace(0.0, 2.0 * np.pi, 72, endpoint=False)
    mx, my = (100.0 * np.cos(th)).tolist(), (100.0 * np.sin(th)).tolist()
    assert f(mx, my, 50.0, 0.0)[0] == pytest.approx(0.5)  # +Mx is a sample point
    assert f(mx, my, 0.0, 80.0)[0] == pytest.approx(0.8)  # +My is a sample point


def test_util_reports_the_governing_vertex():
    # The governing index is the swept point in the applied load's direction -- the
    # endpoint of the crossed chord nearest the crossing. This is what the report's
    # worked case and the Plastic view's default state use, so a pure-Mx load lands on
    # the Mx vertex rather than the strongest (about-y) point of the envelope.
    f = _radial_util()
    mx, my = _diamond(100.0)               # vertices 0:+Mx 1:+My 2:-Mx 3:-My
    assert f(mx, my, 50.0, 0.0)[1] == 0    # +Mx load -> the +Mx vertex
    assert f(mx, my, 0.0, 80.0)[1] == 1    # +My load -> the +My vertex
    assert f(mx, my, -30.0, 0.0)[1] == 2   # -Mx load -> the -Mx vertex
    assert f(mx, my, 90.0, 10.0)[1] == 0   # just off +Mx -> the nearer (+Mx) vertex
    assert f(mx, my, 0.0, 0.0)[1] is None  # no applied direction -> no governing index


@pytest.mark.parametrize(
    ("mx", "my", "demand", "governing_index"),
    [
        ([100.0, 0.0, 0.0, -100.0, 0.0],
         [0.0, 100.0, 100.0, 0.0, -100.0], (0.0, 50.0), 1),
        ([1.0, 1.0, 0.0, -1.0, 0.0],
         [0.0, 0.0, 1.0, 0.0, -1.0], (0.5, 0.0), 0),
    ],
)
@pytest.mark.parametrize("reverse", [False, True])
def test_consecutive_duplicate_vertex_is_coalesced_with_original_index_mapping(
    mx, my, demand, governing_index, reverse
):
    if reverse:
        mx = list(reversed(mx))
        my = list(reversed(my))
    result = _radial_result()(mx, my, *demand)

    assert result.valid is True
    assert result.resistance == pytest.approx(max(abs(demand[0]), abs(demand[1])) * 2)
    assert result.utilisation == pytest.approx(0.5)
    expected_index = len(mx) - 2 - governing_index if reverse else governing_index
    assert result.governing_index == expected_index


@pytest.mark.parametrize("demand", [(0.0, 0.0), (5.0e-10, 0.0), (1.0, 0.0)])
def test_result_rejects_origin_outside_before_zero_or_ray_selection(demand):
    result = _radial_result()(
        [9.0, 11.0, 11.0, 9.0],
        [-1.0, -1.0, 1.0, 1.0],
        *demand,
    )

    assert result.valid is False
    assert result.origin_inside_or_on is False
    assert result.utilisation is None
    assert result.resistance is None
    assert result.governing_index is None
    assert "origin" in result.reason.casefold()
    assert _radial_util()(
        [9.0, 11.0, 11.0, 9.0],
        [-1.0, -1.0, 1.0, 1.0],
        *demand,
    ) == (float("inf"), None)


@pytest.mark.parametrize("demand", [(0.0, 0.0), (0.0, -0.5)])
@pytest.mark.parametrize("scale", [1.0e-200, 1.0, 1.0e200])
@pytest.mark.parametrize("reverse", [False, True])
def test_self_intersecting_envelope_is_invalid_before_origin_or_ray_selection(
    reverse, scale, demand
):
    mx = [-2.0 * scale, 2.0 * scale, -2.0 * scale, 2.0 * scale]
    my = [-1.0 * scale, 3.0 * scale, 3.0 * scale, -1.0 * scale]
    if reverse:
        mx.reverse()
        my.reverse()

    scaled_demand = (demand[0] * scale, demand[1] * scale)
    result = _radial_result()(mx, my, *scaled_demand)

    assert result.valid is False
    assert result.origin_inside_or_on is None
    assert result.utilisation is None
    assert result.resistance is None
    assert result.governing_index is None
    assert "self-intersect" in result.reason.casefold()
    assert _radial_util()(mx, my, *scaled_demand) == (float("inf"), None)


@pytest.mark.parametrize("reverse", [False, True])
def test_nonzero_area_proper_crossing_is_invalid(reverse):
    points = [(-4.0, -1.0), (2.0, 3.0), (-2.0, 3.0), (1.0, -1.0)]
    if reverse:
        points.reverse()
    mx, my = zip(*points, strict=True)

    result = _radial_result()(mx, my, 0.0, 0.0)

    assert result.valid is False
    assert result.origin_inside_or_on is None
    assert result.utilisation is None
    assert result.resistance is None
    assert "self-intersect" in result.reason.casefold()


@pytest.mark.parametrize(
    ("mx", "my"),
    [
        (
            [-2.0, 2.0, 0.0, 2.0, -2.0, 0.0],
            [-2.0, -2.0, 0.0, 2.0, 2.0, 0.0],
        ),
        ([-2.0, 2.0, 1.0, 2.0, -2.0], [-1.0, -1.0, -1.0, 2.0, 2.0]),
        (
            [-2.0, 2.0, 2.0, 1.0, -1.0, -2.0],
            [0.0, 0.0, 2.0, 0.0, 0.0, 2.0],
        ),
    ],
    ids=["non-adjacent-touch", "adjacent-backtrack", "non-adjacent-overlap"],
)
@pytest.mark.parametrize("reverse", [False, True])
def test_self_touching_and_overlapping_envelopes_fail_closed(mx, my, reverse):
    if reverse:
        mx = list(reversed(mx))
        my = list(reversed(my))

    result = _radial_result()(mx, my, 0.0, 0.0)

    assert result.valid is False
    assert result.origin_inside_or_on is None
    assert result.utilisation is None
    assert result.resistance is None
    assert "self-" in result.reason.casefold()


@pytest.mark.parametrize("reverse", [False, True])
def test_same_direction_collinear_boundary_vertices_remain_valid(reverse):
    mx = [-2.0, 0.0, 2.0, 2.0, -2.0]
    my = [-1.0, -1.0, -1.0, 1.0, 1.0]
    if reverse:
        mx.reverse()
        my.reverse()

    result = _radial_result()(mx, my, 1.0, 0.0)

    assert result.valid is True
    assert result.origin_inside_or_on is True
    assert result.resistance == pytest.approx(2.0)
    assert result.utilisation == pytest.approx(0.5)


@pytest.mark.parametrize("reverse", [False, True])
def test_closing_seam_collinear_continuation_remains_valid(reverse):
    points = [(0.0, -1.0), (2.0, -1.0), (2.0, 1.0),
              (-2.0, 1.0), (-2.0, -1.0)]
    if reverse:
        points = [points[0], *reversed(points[1:])]
    mx, my = zip(*points, strict=True)

    result = _radial_result()(mx, my, 1.0, 0.0)

    assert result.valid is True
    assert result.origin_inside_or_on is True
    assert result.resistance == pytest.approx(2.0)
    assert result.utilisation == pytest.approx(0.5)


@pytest.mark.parametrize(
    "outer_y",
    [pytest.param(2.0, id="counterclockwise"),
     pytest.param(-4.0, id="clockwise")],
)
def test_closing_seam_collinear_backtrack_is_invalid(outer_y):
    points = [(2.0, -1.0), (1.0, -1.0), (2.0, outer_y),
              (-2.0, outer_y), (-2.0, -1.0)]
    mx, my = zip(*points, strict=True)

    result = _radial_result()(mx, my, 0.0, 0.0)

    assert result.valid is False
    assert result.origin_inside_or_on is None
    assert result.utilisation is None
    assert result.resistance is None
    assert "self-" in result.reason.casefold()


@pytest.mark.parametrize("reverse", [False, True])
def test_multi_point_collapsed_line_contract_is_retained(reverse):
    mx = [-2.0, -1.0, 0.0, 1.0, 2.0]
    my = [0.0] * len(mx)
    if reverse:
        mx.reverse()
        my.reverse()

    result = _radial_result()(mx, my, 1.0, 0.0)

    assert result.valid is True
    assert result.origin_inside_or_on is True
    assert result.resistance == pytest.approx(2.0)
    assert result.utilisation == pytest.approx(0.5)


def test_origin_on_boundary_accepts_zero_and_inward_but_rejects_outward_ray():
    result = _radial_result()
    mx = [0.0, 2.0, 2.0]
    my = [0.0, -1.0, 1.0]

    zero = result(mx, my, 0.0, 0.0)
    inward = result(mx, my, 1.0, 0.0)
    outward = result(mx, my, -1.0, 0.0)

    assert zero.valid is True
    assert zero.origin_inside_or_on is True
    assert zero.utilisation == 0.0
    assert inward.valid is True
    assert inward.resistance == pytest.approx(2.0)
    assert inward.utilisation == pytest.approx(0.5)
    assert outward.valid is False
    assert outward.origin_inside_or_on is True
    assert outward.utilisation is None


@pytest.mark.parametrize("reverse", [False, True])
def test_tiny_nonzero_demand_is_assessed_against_tiny_capacity(reverse):
    mx = [1.0e-12, 0.0, -1.0e-12, 0.0]
    my = [0.0, 1.0e-12, 0.0, -1.0e-12]
    if reverse:
        mx.reverse()
        my.reverse()

    result = _radial_result()(mx, my, 5.0e-10, 0.0)

    assert result.valid is True
    assert result.origin_inside_or_on is True
    assert result.resistance == pytest.approx(1.0e-12)
    assert result.utilisation == pytest.approx(500.0)


@pytest.mark.parametrize("reverse", [False, True])
def test_sub_tolerance_outward_boundary_demand_is_not_zeroed(reverse):
    mx = [0.0, 2.0, 2.0]
    my = [0.0, -1.0, 1.0]
    if reverse:
        mx.reverse()
        my.reverse()

    result = _radial_result()(mx, my, -5.0e-10, 0.0)

    assert result.valid is False
    assert result.origin_inside_or_on is True
    assert result.resistance is None
    assert result.utilisation is None


@pytest.mark.parametrize(
    ("mx", "my"),
    [
        ([2.0, 0.0, -2.0, 0.0], [0.0, 2.0, 0.0, -2.0]),
        ([0.0, 2.0], [0.0, 0.0]),
    ],
)
def test_nonzero_demand_with_unrepresentable_utilisation_fails_closed(mx, my):
    result = _radial_result()(mx, my, math.ulp(0.0), 0.0)

    assert result.valid is False
    assert result.origin_inside_or_on is True
    assert result.resistance is None
    assert result.utilisation is None
    assert "finite and positive" in result.reason


@pytest.mark.parametrize(
    ("mx", "my", "expected_resistance", "expected_utilisation"),
    [
        (
            [2.0, 0.0, -2.0, 0.0],
            [0.0, 2.0, 0.0, -2.0],
            math.sqrt(2.0),
            math.ulp(0.0),
        ),
        (
            [0.0, 0.5],
            [0.0, 0.5],
            math.sqrt(0.5),
            2.0 * math.ulp(0.0),
        ),
        (
            [math.ulp(0.0), 0.0, -math.ulp(0.0), 0.0],
            [0.0, math.ulp(0.0), 0.0, -math.ulp(0.0)],
            math.ulp(0.0),
            2.0,
        ),
    ],
)
def test_two_component_subnormal_demand_preserves_capacity_norm(
    mx, my, expected_resistance, expected_utilisation
):
    minimum = math.ulp(0.0)
    result = _radial_result()(mx, my, minimum, minimum)

    assert result.valid is True
    assert result.origin_inside_or_on is True
    if expected_resistance == math.ulp(0.0):
        assert result.resistance == expected_resistance
    else:
        assert result.resistance == pytest.approx(expected_resistance)
    assert result.utilisation == expected_utilisation


@pytest.mark.parametrize(
    ("mx", "my", "governing_index"),
    [
        ([0.0, 0.0, 2.0, 2.0], [0.0, -1.0, -1.0, 0.0], 3),
        ([2.0, 2.0, 0.0, 0.0], [0.0, -1.0, -1.0, 0.0], 0),
    ],
)
def test_ray_may_follow_an_admissible_boundary_to_capacity(
    mx, my, governing_index
):
    result = _radial_result()(mx, my, 1.0, 0.0)

    assert result.valid is True
    assert result.origin_inside_or_on is True
    assert result.resistance == pytest.approx(2.0)
    assert result.utilisation == pytest.approx(0.5)
    assert result.governing_index == governing_index


@pytest.mark.parametrize(
    ("mx", "my", "governing_index"),
    [
        ([-3.0, 3.0, 3.0, 1.0, -3.0], [-3.0, -3.0, 3.0, 0.0, 3.0], 1),
        ([-3.0, 1.0, 3.0, 3.0, -3.0], [3.0, 0.0, 3.0, -3.0, -3.0], 2),
    ],
)
def test_reflex_vertex_tangency_is_not_mistaken_for_the_radial_exit(
    mx, my, governing_index
):
    result = _radial_result()(mx, my, 1.0, 0.0)

    assert result.valid is True
    assert result.resistance == pytest.approx(3.0)
    assert result.utilisation == pytest.approx(1.0 / 3.0)
    assert result.governing_index == governing_index


def test_scale_tolerance_does_not_skip_a_resolvable_exit_and_reentry():
    result = _radial_result()(
        [-8.0, 8.0, 8.0, 5.0, 5.0, 2.0, 2.0, -8.0],
        [-1.0e9, -1.0e9, 1.0e9, 1.0e9, -5.0e8, -5.0e8, 1.0e9, 1.0e9],
        6.0,
        0.0,
    )

    assert result.valid is True
    assert result.resistance == pytest.approx(2.0)
    assert result.utilisation == pytest.approx(3.0)
    assert result.governing_index == 5


def test_crossing_grouping_keeps_resolvable_large_distance_events_distinct():
    result = _radial_result()(
        [-1.0, 2.0e9, 2.0e9, 1_000_000_000.5,
         1_000_000_000.5, 1.0e9, 1.0e9, -1.0],
        [-10.0, -10.0, 10.0, 10.0, -5.0, -5.0, 10.0, 10.0],
        1.5e9,
        0.0,
    )

    assert result.valid is True
    assert result.resistance == pytest.approx(1.0e9)
    assert result.utilisation == pytest.approx(1.5)


def test_crossing_grouping_uses_the_local_small_distance_ulp_scale():
    first_exit = 1.0e-6
    reentry = first_exit + 5.0e-15
    result = _radial_result()(
        [-2.0e-6, 2.0e-6, 2.0e-6, reentry,
         reentry, first_exit, first_exit, -2.0e-6],
        [-2.0e-6, -2.0e-6, 2.0e-6, 2.0e-6,
         -1.0e-6, -1.0e-6, 2.0e-6, 2.0e-6],
        1.5e-6,
        0.0,
    )

    assert result.valid is True
    assert result.resistance == pytest.approx(first_exit)
    assert result.utilisation == pytest.approx(1.5)


def test_distinct_crossings_within_64_ulps_are_not_merged_as_one_vertex():
    first_exit = 1.0
    reentry = first_exit + 32.0 * np.spacing(first_exit)
    result = _radial_result()(
        [-2.0, 2.0, 2.0, reentry, reentry, first_exit, first_exit, -2.0],
        [-2.0, -2.0, 2.0, 2.0, -1.0, -1.0, 2.0, 2.0],
        1.5,
        0.0,
    )

    assert result.valid is True
    assert result.resistance == pytest.approx(first_exit)
    assert result.utilisation == pytest.approx(1.5)


def test_nonzero_shallow_edge_determinant_retains_the_first_exit():
    result = _radial_result()(
        [-100.0, 2.0e9, 2.0e9, 1_000_000_010.0, 1_000_000_010.0,
         1.0e9, 1_000_000_001.0, 1_000_000_001.0, -100.0],
        [-100.0, -100.0, 100.0, 100.0, -0.0005,
         -0.0005, 0.0005, 100.0, 100.0],
        1.5e9,
        0.0,
    )

    assert result.valid is True
    assert result.resistance == pytest.approx(1_000_000_000.5)
    assert result.utilisation == pytest.approx(1.5e9 / 1_000_000_000.5)
    assert result.governing_index == 5


def test_near_origin_exit_is_not_removed_by_zero_demand_tolerance():
    result = _radial_result()(
        [-1.0, 2.0e9, 2.0e9, 1.0, 1.0, 0.001, 0.001, -1.0],
        [-10.0, -10.0, 10.0, 10.0, -5.0, -5.0, 10.0, 10.0],
        6.0,
        0.0,
    )

    assert result.valid is True
    assert result.resistance == pytest.approx(0.001)
    assert result.utilisation == pytest.approx(6000.0)
    assert result.governing_index == 5


def test_strict_crossing_parity_does_not_mask_a_slanted_resolvable_exit():
    result = _radial_result()(
        [-100.0, 100.0, 100.0, 13.5, 13.5, 7.401923788646684,
         12.598076211353316, 12.598076211353316, -100.0],
        [-100.0, -100.0, 1.0e9, 1.0e9, -1.5, -1.5,
         1.5, 1.0e9, 1.0e9],
        20.0,
        0.0,
    )

    assert result.valid is True
    assert result.resistance == pytest.approx(10.0)
    assert result.utilisation == pytest.approx(2.0)
    assert result.governing_index == 5


def test_unrelated_large_axis_does_not_move_origin_onto_remote_boundary():
    result = _radial_result()(
        [0.5, 8.0, 8.0, 0.5],
        [-1.0e12, -1.0e12, 1.0e12, 1.0e12],
        0.0,
        0.0,
    )

    assert result.valid is False
    assert result.origin_inside_or_on is False
    assert result.resistance is None
    assert result.utilisation is None
    assert "origin" in result.reason.casefold()


@pytest.mark.parametrize("reverse", [False, True])
def test_mixed_cross_axis_scale_preserves_remote_origin_topology(reverse):
    mx = [1.0e-100, 2.0e-100, 2.0e-100, 1.0e-100]
    my = [-1.0e308, -1.0e308, 1.0e308, 1.0e308]
    if reverse:
        mx.reverse()
        my.reverse()

    result = _radial_result()(mx, my, 0.0, 0.0)

    assert result.valid is False
    assert result.origin_inside_or_on is False
    assert result.resistance is None
    assert result.utilisation is None
    assert "origin" in result.reason.casefold()


@pytest.mark.parametrize("reverse", [False, True])
def test_far_endpoint_ulp_scale_does_not_extend_a_segment_over_origin(reverse):
    epsilon = 1.0e-15
    mx = [-3.0 * epsilon, 0.0, -2.0]
    my = [-3.0 * epsilon, epsilon, -2.0]
    if reverse:
        mx.reverse()
        my.reverse()

    result = _radial_result()(mx, my, 0.0, 0.0)

    assert result.valid is False
    assert result.origin_inside_or_on is False
    assert result.utilisation is None


@pytest.mark.parametrize("reverse", [False, True])
def test_subnormal_nonzero_determinant_is_not_collinear(reverse):
    length = math.ldexp(1.0, 1023)
    height = math.ldexp(1.0, -50)
    mx = [-length / 2.0, length, length, -length / 2.0]
    my = [height, height, 4.0 * height, 4.0 * height]
    if reverse:
        mx.reverse()
        my.reverse()

    result = _radial_result()(mx, my, 1.0, 0.0)

    assert result.valid is False
    assert result.origin_inside_or_on is False
    assert result.resistance is None
    assert result.utilisation is None


@pytest.mark.parametrize("reverse", [False, True])
def test_thin_offset_strip_is_not_tolerance_promoted_to_ray_boundary(reverse):
    offset = math.ldexp(1.0, -50)
    mx = [-1.0, 1.0, 1.0, -1.0]
    my = [-1.0 + offset, 1.0 + offset, 1.0 + 2.0 * offset,
          -1.0 + 2.0 * offset]
    if reverse:
        mx.reverse()
        my.reverse()

    result = _radial_result()(mx, my, 0.5, 0.5)

    assert result.valid is False
    assert result.origin_inside_or_on is False
    assert result.resistance is None
    assert result.utilisation is None


@pytest.mark.parametrize("reverse", [False, True])
def test_subnormal_parity_interpolation_is_orientation_independent(reverse):
    minimum = math.ulp(0.0)
    mx = [0.8, 0.2, -0.05]
    my = [minimum, -minimum, minimum]
    if reverse:
        mx.reverse()
        my.reverse()

    result = _radial_result()(mx, my, 0.0, 0.0)

    assert result.valid is False
    assert result.origin_inside_or_on is False
    assert result.resistance is None
    assert result.utilisation is None


@pytest.mark.parametrize("epsilon", [1.0e-16, 1.0e-17])
@pytest.mark.parametrize("reverse", [False, True])
def test_mixed_scale_intersection_is_orientation_independent(epsilon, reverse):
    mx = [epsilon, 1.0, -1.0]
    my = [-epsilon, 1.0, 1.0]
    if reverse:
        mx.reverse()
        my.reverse()

    result = _radial_result()(mx, my, 0.5, 0.0)
    represented_epsilon = Fraction.from_float(epsilon)
    expected = float(2 * represented_epsilon / (1 + represented_epsilon))

    assert result.valid is True
    assert result.origin_inside_or_on is True
    assert result.resistance == pytest.approx(expected)
    assert result.utilisation == pytest.approx(0.5 / expected)


@pytest.mark.parametrize(
    ("mx", "my", "demand"),
    [
        ([0.0, 1.0e-10, 1.0e-10, 0.0],
         [0.0, 0.0, 1.0e308, 1.0e308], (-2.0e-16, 1.0e308)),
        ([0.0, 0.0, 1.0e308, 1.0e308],
         [0.0, 1.0e-10, 1.0e-10, 0.0], (1.0e308, -2.0e-16)),
    ],
)
@pytest.mark.parametrize("reverse", [False, True])
def test_nonzero_outward_demand_component_is_not_normalized_away(
    mx, my, demand, reverse
):
    if reverse:
        mx = list(reversed(mx))
        my = list(reversed(my))

    result = _radial_result()(mx, my, *demand)

    assert result.valid is False
    assert result.origin_inside_or_on is True
    assert result.resistance is None
    assert result.utilisation is None


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("scale", [1.0e-200, 1.0e200])
def test_extreme_finite_scales_do_not_overflow_or_underflow_origin_parity(
    reverse, scale
):
    mx = [-2.0 * scale, -2.0 * scale, -1.0 * scale]
    my = [-3.0 * scale, -2.0 * scale, 3.0 * scale]
    if reverse:
        mx.reverse()
        my.reverse()

    result = _radial_result()(mx, my, 0.0, 0.0)

    assert result.valid is False
    assert result.origin_inside_or_on is False
    assert result.utilisation is None
    assert result.resistance is None


@pytest.mark.parametrize("reverse", [False, True])
def test_extreme_scale_boundary_classification_is_orientation_independent(reverse):
    scale = 1.0e200
    mx = [-scale, scale, scale]
    my = [-scale, scale, -scale]
    if reverse:
        mx.reverse()
        my.reverse()

    result = _radial_result()(mx, my, 0.0, 0.0)

    assert result.valid is True
    assert result.origin_inside_or_on is True
    assert result.utilisation == 0.0


def test_collapsed_line_overflow_is_invalid_not_zero_utilisation():
    maximum = float.fromhex("0x1.fffffffffffffp+1023")
    result = _radial_result()([0.0, maximum], [0.0, maximum], 1.0, 1.0)

    assert result.valid is False
    assert result.origin_inside_or_on is True
    assert result.resistance is None
    assert result.utilisation is None
    assert "finite" in result.reason.casefold()


@pytest.mark.parametrize(
    ("mx", "my", "ax", "ay"),
    [
        ([], [], 0.0, 0.0),
        ([1.0], [1.0, 2.0], 0.0, 0.0),
        ([float("nan")], [0.0], 0.0, 0.0),
        ([10**1_000], [0.0], 0.0, 0.0),
        ([0.0], [0.0], 10**1_000, 0.0),
    ],
)
def test_malformed_nonfinite_and_overflow_inputs_fail_closed(mx, my, ax, ay):
    result = _radial_result()(mx, my, ax, ay)

    assert result.valid is False
    assert result.utilisation is None
    assert result.resistance is None


def test_frozen_offset_section_reproduction_is_invalid_not_zero_utilisation():
    from sector.materials import Concrete, MildSteel
    from sector.plastic import solve_plastic
    from sector.section import Section

    fixture_path = pathlib.Path(__file__).parent / "fixtures" / "v095_review_cases.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    case = next(row for row in fixture["findings"] if row["id"] == "F095-001")
    replay = case["reproduction"]
    section = Section.from_polygon(
        corners=replay["outer_m"],
        bars_xy_area_mm2=[
            (row["x_m"], row["y_m"], row["area_mm2"])
            for row in replay["reinforcement"]
        ],
    )
    concrete = Concrete(
        fck=replay["concrete"]["fck_mpa"],
        gamma_c=replay["concrete"]["gamma_c"],
        curve=replay["concrete"]["curve"],
    )
    steel = MildSteel(
        fytk=replay["mild_steel"]["fytk_mpa"],
        fyck=replay["mild_steel"]["fyck_mpa"],
        gamma_y=replay["mild_steel"]["gamma_y"],
        curve=replay["mild_steel"]["curve"],
    )
    sweep = replay["sweep_deg"]
    points = solve_plastic(
        section,
        concrete,
        steel,
        replay["axial_force_kn"],
        sweep["start"],
        sweep["stop"],
        sweep["increment"],
    )

    assert len(points) == 24
    assert all(point.converged for point in points)
    assert min(point.My for point in points) == pytest.approx(
        replay["observed_my_capacity_knm"]["minimum"], abs=1.0e-3
    )
    assert max(point.My for point in points) == pytest.approx(
        replay["observed_my_capacity_knm"]["maximum"], abs=1.0e-3
    )
    demand = replay["demand_knm"]
    result = _radial_result()(
        [point.Mx for point in points],
        [point.My for point in points],
        demand["mx"],
        demand["my"],
    )

    assert result.valid is False
    assert result.origin_inside_or_on is False
    assert result.utilisation is None
