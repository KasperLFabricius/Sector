"""TA-08: N-M diagrams hold the companion moment at the case value.

Oracle: at a fixed axial force, the plastic capacity points of all neutral-axis
angles form the M-M envelope. A fine full-circle scan of the angle with a linear
interpolation of the crossings "companion moment = m_off" gives the smallest and
the largest own moment at that companion moment, independently of the
conditional search. The fixed-angle trace (V = 90 degrees) gives a larger Mx
together with a non-zero My, which is the defect.
"""

from __future__ import annotations

import numpy as np
import pytest

from sector import plastic
from sector.materials import Concrete, MildSteel
from sector.section import Section


def _l_section():
    corners = [(0.0, 0.0), (0.6, 0.0), (0.6, 0.15), (0.15, 0.15), (0.15, 0.6), (0.0, 0.6)]
    bars = [(0.05, 0.05, 314.0), (0.3, 0.05, 314.0), (0.55, 0.05, 314.0),
            (0.05, 0.3, 314.0), (0.05, 0.55, 314.0), (0.1, 0.55, 314.0)]
    return Section.from_polygon(corners=corners, bars_xy_area_mm2=bars)


def _materials():
    concrete = Concrete(fck=30.0, gamma_c=1.45, curve=2)
    steel = MildSteel(fytk=550.0, fyck=550.0, futk=550.0, eut=0.05, gamma_y=1.2,
                      gamma_u=1.2, gamma_E=1.0, curve=3, k=1.0, ey0t=0.0, ey0c=0.0)
    return concrete, steel


def _scan_range(section, concrete, steel, axial, axis, m_off, step=0.5, **kw):
    """Smallest and largest own moment at companion ``m_off`` (or None)."""
    angles = np.arange(0.0, 360.0 + step, step)
    states = [plastic.plastic_capacity_at_angle(section, concrete, steel, axial, a, **kw)
              for a in angles]

    def own(state):
        return state.Mx if axis == "x" else state.My

    def companion(state):
        return state.My if axis == "x" else state.Mx

    values = []
    for first, second in zip(states, states[1:]):
        c1, c2 = companion(first) - m_off, companion(second) - m_off
        if c1 == 0.0:
            values.append(own(first))
        elif c1 * c2 < 0.0:
            weight = c1 / (c1 - c2)
            values.append(own(first) + weight * (own(second) - own(first)))
    return (min(values), max(values)) if values else None


def _branches(section, concrete, steel, axis, m_off, n_points=8):
    upper_angle, lower_angle = (90.0, 270.0) if axis == "x" else (0.0, 180.0)
    upper = plastic.uniaxial_interaction(section, concrete, steel, upper_angle, axis,
                                         m_off=m_off, n_points=n_points)
    lower = plastic.uniaxial_interaction(section, concrete, steel, lower_angle, axis,
                                         m_off=m_off, n_points=n_points)
    return upper, lower


def test_uniaxial_branch_matches_scanned_zero_companion_point():
    section = _l_section()
    concrete, steel = _materials()
    fixed = plastic.solve_interaction(section, concrete, steel, 90.0, n_points=8)
    uniaxial = plastic.uniaxial_interaction(section, concrete, steel, 90.0, "x",
                                            n_points=8)
    # The point nearest N = 0 on each trace.
    fixed_zero = min(fixed, key=lambda point: abs(point.axial))
    uniaxial_zero = min(uniaxial, key=lambda point: abs(point.axial))
    assert abs(fixed_zero.My) > 0.05 * abs(fixed_zero.Mx)
    assert uniaxial_zero.My == 0.0
    oracle = _scan_range(section, concrete, steel, uniaxial_zero.axial, "x", 0.0)
    assert oracle is not None
    assert uniaxial_zero.Mx == pytest.approx(oracle[1], rel=0.01)
    assert uniaxial_zero.Mx < fixed_zero.Mx


@pytest.mark.parametrize(("axis", "m_off"), [("x", 0.0), ("x", 150.0), ("y", 100.0)])
def test_both_branches_match_the_scanned_range(axis, m_off):
    # Review R1-02: where the attainable range does not include zero, the inner
    # branch is the smaller own moment (not 0). At N = 1629.3 kN with My = 0 the
    # scan gives Mx in [516.0, 655.7] kNm.
    section = _l_section()
    concrete, steel = _materials()
    upper, lower = _branches(section, concrete, steel, axis, m_off)
    assert upper and lower
    assert [p.axial for p in upper] == pytest.approx([p.axial for p in lower], rel=1.0e-9)
    for high, low in zip(upper, lower):
        assert high.converged and low.converged
        own_high = high.Mx if axis == "x" else high.My
        own_low = low.Mx if axis == "x" else low.My
        held = (high.My, low.My) if axis == "x" else (high.Mx, low.Mx)
        oracle = _scan_range(section, concrete, steel, high.axial, axis, m_off)
        assert oracle is not None
        if held != (m_off, m_off):
            # A kept fixed-angle point: its companion is m_off within rel_tol.
            assert all(abs(value - m_off) <= 1.0e-3 * max(abs(own_high), abs(own_low), 1.0)
                       for value in held)
        assert own_low == pytest.approx(oracle[0], abs=1.0)
        assert own_high == pytest.approx(oracle[1], abs=1.0)


def test_inner_branch_point_from_the_review():
    section = _l_section()
    concrete, steel = _materials()
    _upper, lower = _branches(section, concrete, steel, "x", 0.0)
    point = min(lower, key=lambda p: abs(p.axial - 1629.3))
    assert point.axial == pytest.approx(1629.3, abs=0.1)
    assert point.Mx == pytest.approx(516.03, abs=0.5)


def test_branch_ends_where_the_companion_moment_cannot_be_carried():
    # Review R1-11 and R1-12: no point may be plotted at an axial force where no
    # state has My = 0. With the moment reference at the outer corner of the
    # L-section, My = 0 cannot be carried near the squash load or the tension
    # limit, so the branch ends before both, and every point is converged.
    section = _l_section()
    concrete, steel = _materials()
    n_t, n_c = plastic.axial_limits(section, concrete, steel, 90.0)
    upper, lower = _branches(section, concrete, steel, "x", 0.0, n_points=32)
    assert all(p.converged for p in upper + lower)
    assert len(upper) < 33
    for point in upper:
        assert n_t < point.axial < n_c
        assert _scan_range(section, concrete, steel, point.axial, "x", 0.0) is not None
    beyond = max(p.axial for p in upper) + (n_c - n_t) / 32.0
    if beyond < n_c:
        assert _scan_range(section, concrete, steel, beyond, "x", 0.0) is None


def test_companion_moment_beyond_the_capacity_gives_no_points():
    section = _l_section()
    concrete, steel = _materials()
    upper, lower = _branches(section, concrete, steel, "x", 5000.0)
    assert upper == [] and lower == []
    low, high, status = plastic.companion_moment_range(
        section, concrete, steel, 0.0, "x", 5000.0
    )
    assert status == "unattainable"


def test_axial_limits_are_the_trace_end_points():
    # Hand values, elastic-perfectly plastic steel (futk = fytk): pure tension
    # N_t = -6 x 314 x 550/1.2 = -863.5 kN. Squash load without the pivot C
    # limit: fcd Ac + As fyd = (30/1.45) x 157500 + 863500 N = 4122.12 kN, with
    # Ac = 0.6 x 0.15 + 0.15 x 0.45 = 0.1575 m2.
    section = _l_section()
    concrete, steel = _materials()
    fixed = plastic.solve_interaction(section, concrete, steel, 90.0, n_points=4)
    n_t, n_c = plastic.axial_limits(section, concrete, steel, 90.0)
    assert n_t == pytest.approx(fixed[0].axial, rel=1.0e-9)
    assert n_c == pytest.approx(fixed[-1].axial, rel=1.0e-9)
    assert n_t == pytest.approx(-6.0 * 314.0 * 550.0 / 1.2 / 1000.0, rel=1.0e-6)
    squash = (30.0 / 1.45 * 157500.0 + 6.0 * 314.0 * 550.0 / 1.2) / 1000.0
    assert n_c == pytest.approx(squash, rel=1.0e-6)


def test_angle_must_be_a_pure_axis_angle():
    section = _l_section()
    concrete, steel = _materials()
    with pytest.raises(ValueError):
        plastic.uniaxial_interaction(section, concrete, steel, 0.0, "x")


def test_symmetric_section_keeps_fixed_angle_trace():
    section = Section.from_polygon(
        corners=[(-0.15, -0.3), (0.15, -0.3), (0.15, 0.3), (-0.15, 0.3)],
        bars_xy_area_mm2=[(-0.1, -0.25, 314.0), (0.1, -0.25, 314.0),
                          (-0.1, 0.25, 314.0), (0.1, 0.25, 314.0)],
    )
    concrete, steel = _materials()
    fixed = plastic.solve_interaction(section, concrete, steel, 90.0, n_points=8)
    uniaxial = plastic.uniaxial_interaction(section, concrete, steel, 90.0, "x",
                                            n_points=8)
    assert [p.Mx for p in uniaxial] == pytest.approx([p.Mx for p in fixed])


def _rectangle():
    return Section.from_polygon(
        corners=[(-0.2, -0.3), (0.2, -0.3), (0.2, 0.3), (-0.2, 0.3)],
        bars_xy_area_mm2=[(-0.15, -0.25, 314.0), (0.0, -0.25, 314.0),
                          (0.15, -0.25, 314.0), (-0.15, 0.25, 314.0),
                          (0.15, 0.25, 314.0)],
    )


def test_negative_held_moment_matches_the_scanned_range():
    section = _rectangle()
    concrete, steel = _materials()
    upper, lower = _branches(section, concrete, steel, "x", -60.0)
    assert upper and lower
    for high, low in zip(upper, lower):
        assert high.My == low.My == -60.0
        oracle = _scan_range(section, concrete, steel, high.axial, "x", -60.0)
        assert oracle is not None
        assert (low.Mx, high.Mx) == pytest.approx(oracle, abs=1.0)


def test_prestressed_section_matches_the_scanned_range():
    from sector.materials import Prestress

    section = Section.from_polygon(
        corners=[(-0.2, -0.3), (0.2, -0.3), (0.2, 0.3), (-0.2, 0.3)],
        bars_xy_area_mm2=[(-0.15, 0.25, 314.0), (0.15, 0.25, 314.0)],
        tendons_xy_area_mm2=[(-0.1, -0.24, 600.0), (0.12, -0.2, 300.0)],
    )
    concrete, steel = _materials()
    strand = Prestress(fytk=1640.0, futk=1860.0, eut=0.035, gamma_y=1.2,
                       gamma_u=1.2, gamma_E=1.0, Es=195000.0)
    loop = plastic.uniaxial_interaction_loop(section, concrete, steel, "x",
                                             m_off=40.0, prestress=strand,
                                             n_points=8)
    assert loop.upper and loop.lower
    for high, low in zip(loop.upper, loop.lower):
        assert high.converged and low.converged
        if high.My != 40.0:
            continue
        oracle = _scan_range(section, concrete, steel, high.axial, "x", 40.0,
                             prestress=strand)
        assert oracle is not None
        assert (low.Mx, high.Mx) == pytest.approx(oracle, abs=1.0)


def test_loop_equals_the_single_branches_and_gives_the_trace_ends():
    section = _l_section()
    concrete, steel = _materials()
    loop = plastic.uniaxial_interaction_loop(section, concrete, steel, "y",
                                             m_off=100.0, n_points=8)
    upper, lower = _branches(section, concrete, steel, "y", 100.0)
    def flat(points):
        return [value for p in points for value in (p.axial, p.Mx, p.My)]

    assert flat(loop.upper) == pytest.approx(flat(upper), abs=1.0e-6)
    assert flat(loop.lower) == pytest.approx(flat(lower), abs=1.0e-6)
    n_t, n_c = plastic.axial_limits(section, concrete, steel, 0.0)
    assert (loop.n_t, loop.n_c) == pytest.approx((n_t, n_c), rel=1.0e-9)
