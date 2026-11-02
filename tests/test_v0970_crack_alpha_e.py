"""TA-03: the mean strain of Formula (7.9) uses alpha_e = Es/Ecm.

EN 1992-1-1 7.3.4(2) defines alpha_e as the ratio Es/Ecm. The long-term cracked
state uses the creep modular ratio nl for the steel stress, but the concrete
term of (7.9) keeps alpha_e = Es/Ecm. The expected values follow from a hand
calculation of the cracked rectangular section and from the clause text: with
the first branch of (7.9) in both cases, the mean strain changes by
kt fct,eff (nl - ns)/Es, independent of rho_p,eff.
"""

from __future__ import annotations

import pytest

from sector.codes import fctm
from sector.section import Section
from sector.serviceability import analyse_cracking, evaluate_crack_width

NS = 6.0          # Es/Ecm
NL = 18.0         # Es(1 + phi)/Ecm with phi = 2
ES = 200_000.0
KT = 0.4


def _beam() -> Section:
    b, h, a = 0.3, 0.6, 491.0
    return Section.from_polygon(
        corners=[(0.0, 0.0), (b, 0.0), (b, h), (0.0, h)],
        bars_xy_area_mm2=[(0.075, 0.05, a), (0.15, 0.05, a), (0.225, 0.05, a)],
    )


@pytest.mark.parametrize("edition", ("2004", "2023"))
def test_long_term_mean_strain_uses_short_term_modular_ratio(edition):
    section = _beam()
    fct = fctm(30.0)
    cracked = analyse_cracking(
        section, 0.0, 150.0, 0.0, NL, fctm=fct, Es=ES, beta=0.5, kt=KT,
        cover=37.5,
    ).cracked_state
    corrected = evaluate_crack_width(
        section, cracked, NL, alpha_e_ratio=NS, fctm=fct, Es=ES, kt=KT,
        cover=37.5, edition=edition,
    ).result
    legacy = evaluate_crack_width(
        section, cracked, NL, fctm=fct, Es=ES, kt=KT, cover=37.5,
        edition=edition,
    ).result
    assert corrected is not None and legacy is not None
    # Hand calculation, cracked rectangle with n = nl: b x^2/2 = n As (d - x),
    # Icr = b x^3/3 + n As (d - x)^2, sigma_s = n M (d - x)/Icr.
    b, d, area = 300.0, 550.0, 3.0 * 491.0
    n_as = NL * area
    x = (-n_as + (n_as**2 + 2.0 * b * n_as * d) ** 0.5) / b
    i_cr = b * x**3 / 3.0 + n_as * (d - x) ** 2
    sigma_hand = NL * 150.0e6 * (d - x) / i_cr
    assert sigma_hand == pytest.approx(216.0, abs=0.1)
    governing = max(corrected.candidates, key=lambda item: item.wk)
    assert governing.sigma_s == pytest.approx(sigma_hand, rel=1.0e-4)
    old_bar = next(
        item for item in legacy.candidates if item.bar_index == governing.bar_index
    )
    # (7.9), first branch: esm - ecm = (sigma_s - kt fct/rho (1 + alpha_e rho))/Es.
    assert governing.esm_ecm - old_bar.esm_ecm == pytest.approx(
        KT * fct * (NL - NS) / ES, rel=1.0e-9
    )
    # alpha_e = nl reduces the mean strain, so the former width was too small.
    assert corrected.wk > legacy.wk


def test_review_screening_values():
    # phi = 2, rho_p,eff = 0.02, sigma_s = 250 MPa, fct,eff = 2.9 MPa, kt = 0.4:
    # the concrete term is 65.0 MPa with alpha_e = 6.06 and 79.1 MPa with nl.
    term_ns = KT * 2.9 / 0.02 * (1.0 + (200.0 / 33.0) * 0.02)
    term_nl = KT * 2.9 / 0.02 * (1.0 + 3.0 * (200.0 / 33.0) * 0.02)
    assert term_ns == pytest.approx(65.0, abs=0.05)
    assert term_nl == pytest.approx(79.1, abs=0.05)
