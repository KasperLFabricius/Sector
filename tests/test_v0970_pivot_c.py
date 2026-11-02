"""Pivot C (EN 1992-1-1 6.1(5) and Figure 6.1) in the plastic solver.

The expected values are hand calculations from the clause text, independent of
Sector output. Section: 400 x 400 mm, C30 with gamma_c = 1.45 and alpha_cc = 1.0
(fcd = 20.690 MPa), four bars of 400 mm2 (As = 1 %), B550 with gamma_s = 1.20
(fyd = 458.33 MPa), Es = 200 GPa, eps_c2 = 2.0 per mille, eps_cu2 = 3.5 per mille.

Squash load with pivot C: the whole section is at eps_c2, so the bar stress is
Es * eps_c2 = 400 MPa < fyd:
    N = fcd * Ac + 400 * As = 20.690 * 160000 + 400 * 1600 = 3950.3 kN.
Squash load without pivot C (uniform eps_cu2, bars at fyd):
    N = 20.690 * 160000 + 458.33 * 1600 = 4043.7 kN.
"""

from __future__ import annotations

import pytest

from sector import plastic
from sector.materials import Concrete, MildSteel
from sector.section import Section

FCD = 30.0 / 1.45
AC = 400.0 * 400.0
AS = 1600.0
N_PIVOT_C = (FCD * AC + 200000.0 * 0.002 * AS) / 1000.0
N_LEGACY = (FCD * AC + 550.0 / 1.20 * AS) / 1000.0


def _section():
    return Section.from_polygon(
        corners=[(-0.2, -0.2), (0.2, -0.2), (0.2, 0.2), (-0.2, 0.2)],
        bars_xy_area_mm2=[
            (-0.15, -0.15, 400.0),
            (0.15, -0.15, 400.0),
            (0.15, 0.15, 400.0),
            (-0.15, 0.15, 400.0),
        ],
    )


def _steel():
    # The Eurocode preset law: unfactored Es, flat design plateau at fyk/gamma_s.
    return MildSteel(
        fytk=550.0, fyck=550.0, futk=550.0, eut=0.05, gamma_y=1.20,
        gamma_u=1.20, gamma_E=1.0, curve=3, k=1.0, ey0t=0.0, ey0c=0.0,
    )


def _squash(pivot_c: bool) -> float:
    concrete = Concrete(fck=30.0, gamma_c=1.45, curve=2, pivot_c=pivot_c)
    probe = 2.0 * N_LEGACY
    point = plastic.plastic_capacity_at_angle(
        _section(), concrete, _steel(), probe, 90.0
    )
    return point.axial


def test_hand_values():
    assert N_PIVOT_C == pytest.approx(3950.3, abs=0.05)
    assert N_LEGACY == pytest.approx(4043.7, abs=0.05)


def test_pivot_c_squash_load_matches_hand_calculation():
    assert _squash(True) == pytest.approx(N_PIVOT_C, rel=2.0e-3)


def test_legacy_option_keeps_uniform_crushing_strain():
    assert _squash(False) == pytest.approx(N_LEGACY, rel=2.0e-3)


def test_pivot_c_candidate_is_continuous_at_full_depth():
    depth = 0.4
    eps_c2, eps_cu2 = 0.002, 0.0035
    empty = ()
    import numpy as np

    at_depth, _ = plastic._curvature_at_depth(
        empty, empty, 0.2, depth, np.empty(0), np.empty(0), eps_cu2,
        retain_selection=False, pivot_c=(eps_c2, depth),
    )
    assert at_depth == pytest.approx(eps_cu2 / depth, rel=1.0e-12)
    c = 1.5 * depth
    phi, selection = plastic._curvature_at_depth(
        empty, empty, 0.2, c, np.empty(0), np.empty(0), eps_cu2,
        retain_selection=True, pivot_c=(eps_c2, depth),
    )
    # The strain at pivot C, (1 - eps_c2/eps_cu2) * h from the compressed fibre,
    # equals eps_c2.
    pivot_distance = c - (1.0 - eps_c2 / eps_cu2) * depth
    assert phi * pivot_distance == pytest.approx(eps_c2, rel=1.0e-12)
    assert phi < eps_cu2 / c
    assert selection.selected_mode == "concrete_concentric_compression"


def test_neutral_axis_inside_section_is_unchanged():
    on = Concrete(fck=30.0, gamma_c=1.45, curve=2, pivot_c=True)
    off = Concrete(fck=30.0, gamma_c=1.45, curve=2, pivot_c=False)
    for axial in (0.0, 1000.0, 2000.0):
        a = plastic.plastic_capacity_at_angle(_section(), on, _steel(), axial, 90.0)
        b = plastic.plastic_capacity_at_angle(_section(), off, _steel(), axial, 90.0)
        assert a.Mx == pytest.approx(b.Mx, rel=1.0e-12, abs=1.0e-9)


def test_fully_compressed_state_has_pivot_strain():
    concrete = Concrete(fck=30.0, gamma_c=1.45, curve=2, pivot_c=True)
    point = plastic.plastic_capacity_at_angle(
        _section(), concrete, _steel(), 3800.0, 90.0
    )
    selection = point.curvature_selection
    assert selection.selected_mode == "concrete_concentric_compression"
    assert point.converged
