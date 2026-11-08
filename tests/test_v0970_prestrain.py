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


def test_two_tendon_cracked_section_matches_the_hand_fixed_point():
    """Lightly stressed top tendon in the zone that prestress alone elongates.

    Hand calculation (no-tension rectangle, legacy area model so that the
    tendons displace no concrete): 400 x 800 mm, Ec = 30 GPa (n = 200/30),
    bottom tendon 1500 mm2 at y = -330 mm with Ep IS = 1100 MPa, top tendon
    300 mm2 at y = +330 mm with Ep IS = 100 MPa, Ep = 195 GPa.

        P = 1650 + 30 = 1680 kN at y_R = (1650 (-330) + 30 (330))/1680 = -318.21 mm
        a = 400 - 318.21 = 81.79 mm from the soffit (outside the kern h/6),
        x = 3a = 245.36 mm, sigma_c = 2P/(b x) = 34.236 MPa,
        eps(y) = -sigma_c/Ec (1 - (y + 400)/x)
        bottom: eps = -8.1561e-4, sigma_0 = 1100 + 195000 x 8.1561e-4 = 1259.04 MPa
        top:    eps = +2.25411e-3, sigma_0 = 100 - 195000 x 2.25411e-3 = -339.55 MPa

    The top locked-in stress is negative: prestress alone elongates the concrete
    at the top tendon by more than its IS.
    """
    ec = 30_000.0
    n = 200_000.0 / ec
    p1, p2 = 1500.0 * 1100.0, 300.0 * 100.0
    y_r = (p1 * -330.0 + p2 * 330.0) / (p1 + p2)
    x = 3.0 * (y_r + 400.0)
    sigma_c = 2.0 * (p1 + p2) / (400.0 * x)

    def strain(y):
        return -sigma_c / ec * (1.0 - (y + 400.0) / x)

    hand = np.asarray([1100.0 - EP * strain(-330.0), 100.0 - EP * strain(330.0)])
    assert hand == pytest.approx([1259.04, -339.55], abs=0.01)
    section = Section.from_polygon(
        corners=[(-0.2, -0.4), (0.2, -0.4), (0.2, 0.4), (-0.2, 0.4)],
        bars_xy_area_mm2=[(0.0, -0.33, 1500.0), (0.0, 0.33, 300.0)],
    )
    n_mult = np.asarray([EP / 200_000.0] * 2)
    effective = np.asarray([1100.0e3, 100.0e3])
    locked = bonded_prestress_stress(
        section, n, effective, n_mult=n_mult, displace_concrete=False
    )
    assert locked / 1000.0 == pytest.approx(hand, rel=1.0e-6)
    state = solve_elastic_combined(
        section, 0.0, 0.0, 0.0, n, 0.0, 0.0, 0.0, n,
        n_mult=n_mult, prestress_stress=locked, displace_concrete=False,
    )
    assert np.asarray(state.bar_stress_total) / 1000.0 == pytest.approx(
        [1100.0, 100.0], rel=1.0e-8
    )


def test_tendon_with_zero_prestrain_has_zero_stress_under_prestress_alone():
    # IS = 0 means no tendon stress under prestress alone (user decision), so
    # the tendon mask, not the effective value, marks the tendons.
    section = Section.from_polygon(
        corners=[(-0.2, -0.4), (0.2, -0.4), (0.2, 0.4), (-0.2, 0.4)],
        bars_xy_area_mm2=[(0.0, -0.33, 1500.0), (0.0, 0.33, 300.0)],
    )
    n_mult = np.asarray([EP / 200_000.0] * 2)
    effective = np.asarray([1100.0e3, 0.0])
    locked = bonded_prestress_stress(
        section, NL, effective, n_mult=n_mult,
        tendon_mask=np.asarray([True, True]),
    )
    state = solve_elastic_combined(
        section, 0.0, 0.0, 0.0, NL, 0.0, 0.0, 0.0, NL,
        n_mult=n_mult, prestress_stress=locked,
    )
    assert np.asarray(state.bar_stress_total) / 1000.0 == pytest.approx(
        [1100.0, 0.0], abs=1.0e-6
    )
