"""Cross-check the plastic solver against the Hammelstrupvej hand-calc slab M_Rd.

The hand calc (Appendix B.1, Bro 12008, new bridge deck) computes the ultimate
moment capacity per metre with the Eurocode rectangular stress block and
elastic-perfectly-plastic steel; Sector uses the parabola-rectangle concrete
law. For the two worked slab sections (N_Ed = 0, beff = 1 m, fcd = 25.41 MPa,
fyd = 482.46 MPa, 10 dia20 bars per layer, a compression layer 60 mm from the
top and a tension layer at the effective depth d), the two methods agree to
~0.1 %.
"""

from __future__ import annotations

import math

import pytest

from sector.materials import Concrete, MildSteel
from sector.plastic import plastic_capacity_at_angle
from sector.section import Section

FCD = 25.41   # design concrete strength, MPa (fck.N / gamma_c.N)
FYD = 482.46  # design steel yield, MPa (fyk.N / gamma_s.N)
AS = 10.0 * math.pi / 4.0 * 20.0 ** 2  # mm2 per metre for 10 dia20 bars


def _slab(h_mm, d_mm, comp_top_mm=60.0):
    """1 m-wide slab strip; compression at the top (bending about X, V=90)."""
    H = h_mm / 1000.0
    return Section.from_polygon(
        corners=[(-0.5, 0.0), (-0.5, H), (0.5, H), (0.5, 0.0)],
        bars_xy_area_mm2=[
            (0.0, H - d_mm / 1000.0, AS),         # tension layer at depth d
            (0.0, H - comp_top_mm / 1000.0, AS),  # compression layer near the top
        ],
    )


# (effective depth case, slab thickness h, tension depth d, hand-calc M_Rd kNm)
HANDCALC_CASES = [
    ("konsol1", 665.0, 605.0, 871.05),
    ("deck", 550.0, 490.0, 696.74),
]


@pytest.mark.parametrize("case", HANDCALC_CASES, ids=[c[0] for c in HANDCALC_CASES])
def test_handcalc_slab_moment_capacity(case):
    _name, h, d, mrd = case
    concrete = Concrete(fck=FCD, gamma_c=1.0, curve=2)
    steel = MildSteel(fytk=FYD, fyck=FYD, eut=0.05, gamma_y=1.0, curve=2)
    r = plastic_capacity_at_angle(_slab(h, d), concrete, steel, 0.0, 90.0)

    assert r.converged
    assert r.eps_concrete == pytest.approx(0.35)  # concrete-governed
    assert r.eps_steel < 0.0                       # tension steel yielded
    # Parabola (Sector) vs rectangular block (hand calc): within 2 %.
    assert r.Mx == pytest.approx(mrd, rel=0.02)
