"""TA-04: the tendon prestrain IS is the strain difference after all losses.

User decision for Sector 0.97.0: under prestress alone the tendon stress equals
Ep*IS. Sector adds no elastic-shortening or creep loss and derives the bond
strain difference eps_p(0) (EN 1992-1-1 Figure 6.1) internally.

Hand calculation (independent of Sector output): 400 x 800 mm, one concentric
tendon Ap = 1500 mm2, Ep = 195 GPa, IS = 1100/195000, nl = 18 with the steel
reference modulus 200 GPa (Ec,eff = 200000/18 = 11111.1 MPa). The tendon area
displaces concrete, so the concrete area is 320000 - 1500 = 318500 mm2.

    P = 1500 * 1100 = 1.650 MN
    eps_c,p = -P / (Ec,eff * 318500) = -4.6626e-4
    eps_p(0) = IS - eps_c,p = 5.6410e-3 + 4.6626e-4 = 6.1073e-3
    sigma_0 = Ep * eps_p(0) = 1190.92 MPa
    concrete stress = -P / 318500 = -5.1805 MPa
"""

from __future__ import annotations

import numpy as np
import pytest

from sector.elastic import bonded_prestress_stress, solve_elastic_combined
from sector.section import Section

EP = 195_000.0
IS = 1100.0 / EP
NL = 18.0
AP = 1500.0
P_MN = AP * 1100.0 / 1.0e6
EC_EFF = 200_000.0 / NL
A_NET = 400.0 * 800.0 - AP
EPS_C = -P_MN * 1.0e6 / (EC_EFF * A_NET)
EPS_P0 = IS - EPS_C


def _section():
    return Section.from_polygon(
        corners=[(-0.2, -0.4), (0.2, -0.4), (0.2, 0.4), (-0.2, 0.4)],
        bars_xy_area_mm2=[(0.0, 0.0, AP)],
    )


def test_hand_values():
    assert EPS_C == pytest.approx(-4.6626e-4, rel=1.0e-4)
    assert EP * EPS_P0 == pytest.approx(1190.92, abs=0.01)


def test_bond_strain_difference_matches_hand_calculation():
    n_mult = np.asarray([EP / 200_000.0])
    effective = np.asarray([EP * IS * 1000.0])
    locked = bonded_prestress_stress(_section(), NL, effective, n_mult=n_mult)
    assert locked[0] / 1000.0 == pytest.approx(EP * EPS_P0, rel=1.0e-6)


def test_tendon_stress_under_prestress_alone_is_ep_times_is():
    n_mult = np.asarray([EP / 200_000.0])
    effective = np.asarray([EP * IS * 1000.0])
    locked = bonded_prestress_stress(_section(), NL, effective, n_mult=n_mult)
    for short_n in (NL, 6.0):
        state = solve_elastic_combined(
            _section(), 0.0, 0.0, 0.0, NL, 0.0, 0.0, 0.0, short_n,
            n_mult=n_mult, prestress_stress=locked,
        )
        assert state.bar_stress_total[0] / 1000.0 == pytest.approx(1100.0, rel=1.0e-6)
        assert state.max_concrete_compression / 1000.0 == pytest.approx(
            P_MN * 1.0e6 / A_NET, rel=1.0e-6
        )


def test_without_tendons_the_stress_is_unchanged():
    effective = np.asarray([0.0])
    locked = bonded_prestress_stress(_section(), NL, effective)
    assert locked[0] == 0.0
