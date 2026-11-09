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
        if not (first.converged and second.converged):
            continue
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


def test_prestressed_branches_stay_converged_when_tension_limits_differ():
    # Review R3-01: with a prestrain the tension limits of the two pure-axis
    # angles can differ by more than one grid step. No interior point may be
    # clamped at the end of one branch, and every point must converge.
    from sector.materials import Prestress

    bars = [(x, -0.25, 314.16) for x in (-0.15, -0.09, -0.03, 0.03, 0.09, 0.15)]
    bars += [(-0.15, 0.25, 314.16), (0.15, 0.25, 314.16)]
    section = Section.from_polygon(
        corners=[(-0.2, -0.3), (0.2, -0.3), (0.2, 0.3), (-0.2, 0.3)],
        bars_xy_area_mm2=bars, tendons_xy_area_mm2=[(0.0, 0.2, 600.0)],
    )
    concrete, steel = _materials()
    strand = Prestress(fytk=1640.0, futk=1860.0, eut=0.035, gamma_y=1.15,
                       gamma_u=1.15, gamma_E=1.0, Es=195000.0)
    upper_ends = plastic.solve_interaction(section, concrete, steel, 90.0,
                                           prestress=strand, n_points=1)
    lower_ends = plastic.solve_interaction(section, concrete, steel, 270.0,
                                           prestress=strand, n_points=1)
    loop = plastic.uniaxial_interaction_loop(section, concrete, steel, "x",
                                             prestress=strand, n_points=32)
    assert all(p.converged for p in loop.upper + loop.lower)
    assert loop.n_t == pytest.approx(min(upper_ends[0].axial, lower_ends[0].axial))
    assert loop.n_c == pytest.approx(max(upper_ends[-1].axial, lower_ends[-1].axial))
    for branch in (loop.upper, loop.lower):
        axials = [p.axial for p in branch]
        assert all(b > a for a, b in zip(axials, axials[1:]))
        assert loop.n_t - 1.0e-6 <= axials[0] and axials[-1] <= loop.n_c + 1.0e-6


def test_held_moment_near_its_largest_value_is_found_between_grid_points():
    # Codex review of PR #578: near its largest value the held moment can be
    # carried only in an axial band narrower than one grid interval. The
    # diagram must then sample that band and not report "no diagram".
    section = _l_section()
    concrete, steel = _materials()
    n_t, n_c = plastic.axial_limits(section, concrete, steel, 90.0)
    grid = [n_t + (n_c - n_t) * i / 8 for i in range(1, 8)]

    def my_pure(P):
        return plastic.plastic_capacity_at_angle(section, concrete, steel, P, 0.0).My

    grid_best = max(my_pure(P) for P in grid)
    fine_best = max(my_pure(P) for P in np.linspace(n_t, n_c, 321)[1:-1])
    assert fine_best > grid_best + 2.0
    m_off = 0.5 * (grid_best + fine_best)
    # Setup check with the independent scan: no grid point carries m_off.
    assert all(
        _scan_range(section, concrete, steel, P, "x", m_off, step=1.0) is None
        for P in grid
    )
    loop = plastic.uniaxial_interaction_loop(section, concrete, steel, "x",
                                             m_off=m_off, n_points=8)
    assert loop.upper and loop.lower
    for high, low in zip(loop.upper, loop.lower):
        assert high.converged and low.converged
        oracle = _scan_range(section, concrete, steel, high.axial, "x", m_off)
        assert oracle is not None
        assert (low.Mx, high.Mx) == pytest.approx(oracle, abs=1.0)
    beyond = plastic.uniaxial_interaction_loop(section, concrete, steel, "x",
                                               m_off=1.05 * fine_best, n_points=8)
    assert beyond.upper == [] and beyond.lower == []


@pytest.mark.parametrize("root_search", ["bisection", "illinois"])
def test_crossing_search_keeps_an_exact_zero_bracket_end(root_search):
    # Review R3-03: a synthetic companion curve with its maximum exactly at the
    # target on a plateau (101 to 105 degrees). Each returned point must carry
    # the target; before the correction one search returned a point with a
    # residual of -13 or -23.
    from types import SimpleNamespace

    def cap(angle):
        return SimpleNamespace(converged=True, axial_reachable=True, angle=angle)

    def companion(point):
        a = point.angle % 360.0
        return -max(0.0, 101.0 - a, a - 105.0)

    points, scan_failed, solve_failed = plastic._companion_crossings(
        cap, companion, 0.0, n_scan=36, tol_deg=0.005, root_search=root_search,
    )
    assert points and not scan_failed and not solve_failed
    assert all(companion(point) == 0.0 for point in points)


def _hardening_steel():
    return MildSteel(fytk=500.0, fyck=500.0, futk=575.0, eut=0.025, gamma_y=1.15,
                     gamma_u=1.15, gamma_E=1.0, curve=1)


def _strand():
    from sector.materials import Prestress

    return Prestress(fytk=1640.0, futk=1860.0, eut=0.035, gamma_y=1.15,
                     gamma_u=1.15, gamma_E=1.0, Es=195000.0)


def _rc_rectangle(bars, tendons=()):
    return Section.from_polygon(
        corners=[(-0.2, -0.3), (0.2, -0.3), (0.2, 0.3), (-0.2, 0.3)],
        bars_xy_area_mm2=list(bars), tendons_xy_area_mm2=list(tendons),
    )


def _shifted_l_section():
    # The L-section of _l_section with its origin moved by (0.2, 0.2) m.
    corners = [(0.0, 0.0), (0.6, 0.0), (0.6, 0.15), (0.15, 0.15), (0.15, 0.6), (0.0, 0.6)]
    bars = [(0.05, 0.05, 314.0), (0.3, 0.05, 314.0), (0.55, 0.05, 314.0),
            (0.05, 0.3, 314.0), (0.05, 0.55, 314.0), (0.1, 0.55, 314.0)]
    return Section.from_polygon(
        corners=[(x - 0.2, y - 0.2) for x, y in corners],
        bars_xy_area_mm2=[(x - 0.2, y - 0.2, a) for x, y, a in bars],
    )


def _check_against_scan(loop, section, concrete, steel, axis, m_off, *, tol=1.0,
                        count=4, **kw):
    """Each branch is not empty, all its points converge, and a sample of its
    points agrees with the independent scan."""
    own = (lambda q: q.Mx) if axis == "x" else (lambda q: q.My)
    for branch, side in ((loop.upper, 1), (loop.lower, 0)):
        assert branch and all(q.converged for q in branch)
        picks = sorted({round(i * (len(branch) - 1) / max(count - 1, 1))
                        for i in range(count)})
        for q in (branch[i] for i in picks):
            oracle = _scan_range(section, concrete, steel, q.axial, axis, m_off, **kw)
            assert oracle is not None
            assert own(q) == pytest.approx(oracle[side], abs=tol)


def test_branch_with_the_more_tensile_end_keeps_its_tension_range():
    # Review R4-01: prestressed section, hardening bars, held My = 0. The
    # tension limits of the two fixed-angle traces differ. Each branch must
    # reach the most tensile axial force at which the independent scan finds
    # My = 0 attainable, within one grid step.
    concrete, _steel = _materials()
    steel, strand = _hardening_steel(), _strand()
    section = _rc_rectangle(
        [(-0.15, 0.25, 314.0), (0.15, 0.25, 314.0), (-0.15, -0.25, 201.0),
         (0.15, -0.25, 201.0)],
        [(-0.1, -0.24, 600.0), (0.12, -0.2, 300.0)],
    )
    loop = plastic.uniaxial_interaction_loop(section, concrete, steel, "x",
                                             prestress=strand, n_points=32)
    grid_step = (loop.n_c - loop.n_t) / 32

    def attainable(n):
        return _scan_range(section, concrete, steel, n, "x", 0.0, step=1.0,
                           prestress=strand) is not None

    # Most tensile attainable axial force by bisection on the scan oracle.
    reach, miss = 0.0, loop.n_t
    assert attainable(reach)
    for _ in range(8):
        mid = 0.5 * (reach + miss)
        if attainable(mid):
            reach = mid
        else:
            miss = mid
    for branch in (loop.upper, loop.lower):
        assert all(q.converged for q in branch)
        assert branch[0].axial <= reach + grid_step + 1.0e-6
    _check_against_scan(loop, section, concrete, steel, "x", 0.0, prestress=strand)


@pytest.mark.parametrize("m_off", [0.0, 100.0])
def test_unreachable_angles_inside_the_search_do_not_fail_the_diagram(m_off):
    # Review R3-02 (rest): two tendon levels; near the tension end the axial
    # force is unreachable round 90 degrees, inside the extremum and the root
    # search of the y diagram. The diagram must stay converged.
    concrete, steel = _materials()
    strand = _strand()
    section = _rc_rectangle(
        [(-0.15, 0.25, 201.0), (0.15, 0.25, 201.0)],
        [(0.0, -0.25, 1000.0), (0.0, 0.25, 300.0)],
    )
    loop = plastic.uniaxial_interaction_loop(section, concrete, steel, "y",
                                             m_off=m_off, prestress=strand,
                                             n_points=32)
    _check_against_scan(loop, section, concrete, steel, "y", m_off,
                        prestress=strand)


def test_symmetric_section_finds_the_held_moment_near_the_peak():
    # Review R4-02: on a section symmetric about the y axis the samples at 80
    # and 100 degrees were equal, so the search missed the peak at 90 degrees.
    # Held Mx = 564.19 kNm, 98 % of the pure-axis peak.
    concrete, steel = _materials()
    section = _rc_rectangle([(x, y, 314.0) for x in (-0.15, 0.0, 0.15) for y in (-0.25, 0.25)])
    loop = plastic.uniaxial_interaction_loop(section, concrete, steel, "y",
                                             m_off=564.19, n_points=32)
    assert len(loop.upper) >= 3 and len(loop.lower) >= 3
    _check_against_scan(loop, section, concrete, steel, "y", 564.19, tol=0.5)
    # Review R5-02: at the grid value N = 2064.5 kN, 18 scan samples (20-degree
    # step) give equal samples at 80 and 100 degrees. The scan carries the held
    # moment there, so each branch must have a point at this grid value.
    grid = [loop.n_t + (loop.n_c - loop.n_t) * i / 32 for i in range(1, 32)]
    tie = min(grid, key=lambda n: abs(n - 2064.476))
    assert tie == pytest.approx(2064.476, abs=0.01)
    assert _scan_range(section, concrete, steel, tie, "y", 564.19) is not None
    for branch in (loop.upper, loop.lower):
        assert any(abs(q.axial - tie) < 1.0e-6 for q in branch)


def test_band_above_the_pure_axis_peak_is_found():
    # Review R4-03: the largest My (349.5 kNm by an angle scan) is not at a
    # pure-axis angle. Held My = 349.35 kNm is above the largest pure-axis My
    # (342.7 kNm); the scan finds it attainable near N = 740 kN.
    concrete, _steel = _materials()
    steel = _hardening_steel()
    section = _shifted_l_section()
    assert _scan_range(section, concrete, steel, 740.0, "x", 349.35) is not None
    loop = plastic.uniaxial_interaction_loop(section, concrete, steel, "x",
                                             m_off=349.35, n_points=32)
    _check_against_scan(loop, section, concrete, steel, "x", 349.35, tol=0.5)


def test_short_diagram_gets_the_band_points():
    # Review R4-04: one grid point in the band gave a one-point diagram.
    concrete, _steel = _materials()
    steel = _hardening_steel()
    section = _shifted_l_section()
    loop = plastic.uniaxial_interaction_loop(section, concrete, steel, "y",
                                             m_off=-399.22, n_points=32)
    assert len(loop.upper) >= 3 and len(loop.lower) >= 3
    for branch in (loop.upper, loop.lower):
        axials = [q.axial for q in branch]
        assert all(b > a for a, b in zip(axials, axials[1:]))
    _check_against_scan(loop, section, concrete, steel, "y", -399.22, tol=0.5)


def test_range_with_a_failed_solve_is_failed(monkeypatch):
    # Codex review of PR #578: when a reachable solve fails, the crossings found
    # can be incomplete. The range is then "failed" (the diagram is INVALID),
    # also when some crossings were found.
    section = _l_section()
    concrete, steel = _materials()
    real = plastic._companion_crossings

    def one_crossing_and_a_failed_solve(*args, **kwargs):
        points, scan_failed, _solve_failed = real(*args, **kwargs)
        return points[:1], scan_failed, True

    low, high, status = plastic.companion_moment_range(
        section, concrete, steel, 500.0, "x", 0.0)
    assert status == "ok" and high > low
    monkeypatch.setattr(plastic, "_companion_crossings", one_crossing_and_a_failed_solve)
    low, high, status = plastic.companion_moment_range(
        section, concrete, steel, 500.0, "x", 0.0)
    assert status == "failed" and low == high
    loop = plastic.uniaxial_interaction_loop(section, concrete, steel, "x",
                                             m_off=50.0, n_points=4)
    assert not all(q.converged for q in loop.upper + loop.lower)


@pytest.mark.parametrize("root_search", ["bisection", "illinois"])
def test_crossing_near_the_edge_of_a_reachable_arc_is_found(root_search):
    # Codex review of PR #578: the axial force is reachable only from 0 to 25
    # degrees, and the companion crossing is at 20 degrees. The scan samples
    # at 0 and 18 degrees are below the target and the sample at 36 degrees
    # is unreachable, so the crossing lies between 18 degrees and the arc edge.
    from types import SimpleNamespace

    def cap(angle):
        reachable = 0.0 <= angle % 360.0 <= 25.0
        return SimpleNamespace(converged=reachable, axial_reachable=reachable,
                               angle=angle)

    def companion(point):
        return point.angle % 360.0 - 20.0

    points, scan_failed, solve_failed = plastic._companion_crossings(
        cap, companion, 0.0, n_scan=20, tol_deg=0.005, root_search=root_search,
        skip_unreachable=True,
    )
    assert not scan_failed and not solve_failed
    assert points and all(abs(companion(point)) < 0.01 for point in points)


def _external_offaxis_rows():
    # External program results (legacy ECROSS/PCROSS output PDFs). The source
    # files and their SHA-256 are in tests/fixtures/handcalc_source_manifest.json
    # (tests/test_plastic_handcalc.py). Only rows without tendons, with both
    # moments not zero, and with a fixed-angle point that Sector reproduces
    # within the comparison limit (tests/fixtures/handcalc_comparison.json).
    import json
    import pathlib

    from tools import compare_handcalc_fixtures as comparison

    root = pathlib.Path(__file__).resolve().parents[1]
    retained = {
        case["name"]: case for case in json.loads(
            (root / "tests" / "fixtures" / "handcalc_comparison.json").read_text(
                encoding="utf-8"))["cases"]
    }
    rows = []
    for case in comparison.load_cases():
        if case.get("tendons"):
            continue
        for index, row in enumerate(case["rows"]):
            axial, _angle, mx, my = row[:4]
            record = retained[case["name"]]["rows"][index]
            if abs(mx) > 1.0 and abs(my) > 1.0 and record["within_tolerance"]:
                rows.append(pytest.param(
                    case, axial, mx, my, record["metrics"]["mx"]["limit"],
                    record["metrics"]["my"]["limit"],
                    id=f"{case['name']}-{index}",
                ))
    return rows


@pytest.mark.parametrize("case, axial, mx, my, mx_limit, my_limit",
                         _external_offaxis_rows())
def test_held_moment_range_reproduces_external_offaxis_points(
        case, axial, mx, my, mx_limit, my_limit):
    # Oracle independent of Sector: an external program point (N, Mx, My) at a
    # fixed neutral-axis angle lies on the M-M envelope at N (EN 1992-1-1:2004,
    # 6.1). With My held at the external value, one end of the Mx range is the
    # external Mx, and with Mx held, one end of the My range is the external My.
    from tools import compare_handcalc_fixtures as comparison

    section, concrete, mild, _prestress = comparison.build_case(case)
    low, high, status = plastic.companion_moment_range(
        section, concrete, mild, axial, "x", my, n_bands=50)
    assert status == "ok"
    assert min(abs(low - mx), abs(high - mx)) <= mx_limit
    low, high, status = plastic.companion_moment_range(
        section, concrete, mild, axial, "y", mx, n_bands=50)
    assert status == "ok"
    assert min(abs(low - my), abs(high - my)) <= my_limit
