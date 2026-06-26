"""Property / sanity checks for the plastic solver on synthetic sections."""

from __future__ import annotations

import pytest

from sector.materials import Concrete, MildSteel
from sector.plastic import plastic_capacity_at_angle
from sector.section import Section


def column(side_x=0.4, side_y=0.6):
    """A doubly-symmetric column: rectangle centred on the origin, 8 bars."""
    hx, hy = side_x / 2, side_y / 2
    c = 0.05
    bars = [
        (-hx + c, -hy + c, 314.0), (hx - c, -hy + c, 314.0),
        (-hx + c, hy - c, 314.0), (hx - c, hy - c, 314.0),
        (0.0, -hy + c, 314.0), (0.0, hy - c, 314.0),
        (-hx + c, 0.0, 314.0), (hx - c, 0.0, 314.0),
    ]
    section = Section.from_polygon(
        corners=[(-hx, -hy), (-hx, hy), (hx, hy), (hx, -hy)],
        bars_xy_area_mm2=bars,
    )
    concrete = Concrete(fck=35.0, gamma_c=1.5, curve=2)
    steel = MildSteel(fytk=500.0, fyck=500.0, eut=0.05, gamma_y=1.15, curve=2)
    return section, concrete, steel


def test_symmetric_section_has_no_off_axis_moment():
    section, concrete, steel = column()
    # Bending about X (V=90) on an x-symmetric section -> no My.
    r90 = plastic_capacity_at_angle(section, concrete, steel, 0.0, 90.0)
    assert r90.My == pytest.approx(0.0, abs=1e-6 * max(1.0, abs(r90.Mx)))
    # Bending about Y (V=0) -> no Mx.
    r0 = plastic_capacity_at_angle(section, concrete, steel, 0.0, 0.0)
    assert r0.Mx == pytest.approx(0.0, abs=1e-6 * max(1.0, abs(r0.My)))


def test_integration_converges_with_more_bands():
    section, concrete, steel = column()
    coarse = plastic_capacity_at_angle(section, concrete, steel, 0.0, 90.0, n_bands=20)
    fine = plastic_capacity_at_angle(section, concrete, steel, 0.0, 90.0, n_bands=300)
    assert coarse.Mx == pytest.approx(fine.Mx, rel=3e-3)


def test_compression_force_exceeds_axial_in_bending():
    # Under axial compression P, the internal compression resultant must exceed
    # P (it also balances the tension steel): comp_F = P + tension.
    section, concrete, steel = column()
    P = 800.0
    r = plastic_capacity_at_angle(section, concrete, steel, P, 90.0)
    assert r.converged
    assert r.compression_force >= P


def test_axial_compression_raises_bending_capacity_then_falls():
    # Classic N-M interaction: moderate compression increases the bending
    # capacity above the pure-bending value; near squash it collapses. The
    # high-compression point needs a neutral axis beyond the section (the whole
    # section compressed, c > c_full) -- it must still converge and be traced.
    section, concrete, steel = column()
    m0 = plastic_capacity_at_angle(section, concrete, steel, 0.0, 90.0).Mx
    m_mid = plastic_capacity_at_angle(section, concrete, steel, 1500.0, 90.0).Mx
    high = plastic_capacity_at_angle(section, concrete, steel, 5000.0, 90.0)
    assert m_mid > m0          # compression boosts capacity below balanced
    assert high.converged      # compression side is reachable (not clamped)
    assert 0.0 < high.Mx < m_mid  # past balanced the capacity falls again


def test_strain_limits_are_reported():
    section, concrete, steel = column()
    r = plastic_capacity_at_angle(section, concrete, steel, 0.0, 90.0)
    # Concrete extreme fibre is at the ultimate strain; steel is in tension.
    assert r.eps_concrete == pytest.approx(0.35)
    assert r.eps_steel < 0.0
    assert r.curvature > 0.0


def test_steel_rupture_governs_below_concrete_crushing():
    # A lightly reinforced deep section with a low steel rupture strain: the
    # tension steel reaches its rupture strain before the concrete crushes, so
    # the governing curvature keeps the concrete strain below 0.35 %.
    sec = Section.from_polygon(
        corners=[(-.15, -.3), (-.15, .3), (.15, .3), (.15, -.3)],
        bars_xy_area_mm2=[(0.0, -0.25, 200.0)],
    )
    conc = Concrete(fck=35.0, gamma_c=1.5, curve=2)
    steel = MildSteel(fytk=500.0, fyck=500.0, eut=0.01, futk=540.0,
                      gamma_y=1.15, gamma_u=1.15, gamma_E=1.0, curve=1)
    r = plastic_capacity_at_angle(sec, conc, steel, 0.0, 90.0)
    assert r.converged
    assert r.eps_concrete < 0.35                      # concrete not crushed
    assert r.eps_steel == pytest.approx(-1.0, abs=0.02)  # steel at its 1% rupture strain


def test_tensile_axial_force_gives_negative_R():
    # R is signed (Mx = P*R*sin U): a tensile axial force (P < 0) yields R < 0.
    section, concrete, steel = column()
    r = plastic_capacity_at_angle(section, concrete, steel, -400.0, 90.0)
    assert r.converged
    assert r.R < 0.0
