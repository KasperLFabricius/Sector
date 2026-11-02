"""TA-08: N-M diagrams hold the companion moment at the case value.

Oracle: for an L-section the uniaxial capacity Mx at N = 0 is the point of the
plastic envelope where My = 0. A fine scan of the neutral-axis angle with a
linear interpolation of the My zero crossing gives it independently of the
conditional-capacity search. The fixed-angle trace (V = 90 degrees) gives a
larger Mx together with a non-zero My, which is the defect.
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


def _scan_mx_at_zero_my(section, concrete, steel, axial):
    angles = np.linspace(30.0, 150.0, 241)
    states = [plastic.plastic_capacity_at_angle(section, concrete, steel, axial, a)
              for a in angles]
    best = None
    for first, second in zip(states, states[1:]):
        if first.My == 0.0 or first.My * second.My < 0.0:
            weight = first.My / (first.My - second.My) if first.My != second.My else 0.0
            mx = first.Mx + weight * (second.Mx - first.Mx)
            if mx > 0.0 and (best is None or mx > best):
                best = mx
    return best


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
    # Same axial force, so compare at the axial force of that sample.
    exact = plastic.conditional_capacity(section, concrete, steel,
                                         uniaxial_zero.axial, "x", True, 0.0)
    assert uniaxial_zero.Mx == pytest.approx(exact[0], rel=1.0e-9)
    oracle = _scan_mx_at_zero_my(section, concrete, steel, uniaxial_zero.axial)
    assert oracle is not None
    assert uniaxial_zero.Mx == pytest.approx(oracle, rel=0.01)
    assert uniaxial_zero.Mx < fixed_zero.Mx


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
