"""Verification of the serviceability cracked-section analysis.

The anchor case is a singly reinforced rectangular beam in pure bending whose
cracking load, tension-stiffening coefficient, steel stress and crack width are
all worked independently from EN 1992-1-1 closed forms; the rest exercise the
regime logic (uncracked / deeply cracked), the duration factors and the biaxial
proportional-scaling of the cracking load.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from sector.codes import ecm, fctm
from sector.section import Section
from sector.serviceability import (
    analyse_cracking,
    cracking_factor,
    tension_stiffening_zeta,
)


def beam_section() -> Section:
    """0.3 x 0.6 m beam, 3 bars (491 mm^2 each) at y = 0.05 m (d = 0.55 m)."""
    b, h, a = 0.3, 0.6, 491.0
    return Section.from_polygon(
        corners=[(0.0, 0.0), (b, 0.0), (b, h), (0.0, h)],
        bars_xy_area_mm2=[(0.075, 0.05, a), (0.15, 0.05, a), (0.225, 0.05, a)],
    )


def gov_stress_mpa(res) -> float:
    s = np.asarray(res.bar_stress, dtype=float)
    return float(s.max()) / 1000.0


# ---- helper-function unit tests -------------------------------------------

def test_cracking_factor_no_tension_is_infinite():
    assert math.isinf(cracking_factor(0.0, 3.0))
    assert math.isinf(cracking_factor(-2.0, 3.0))
    assert cracking_factor(6.0, 3.0) == pytest.approx(0.5)


def test_zeta_limits():
    assert tension_stiffening_zeta(1.5, 1.0) == 0.0           # uncracked
    assert tension_stiffening_zeta(1.0, 1.0) == 0.0           # just cracking
    assert tension_stiffening_zeta(0.0, 0.5) == 1.0           # fully cracked
    # beta halves the knock-down for sustained loading.
    assert tension_stiffening_zeta(0.5, 1.0) == pytest.approx(0.75)
    assert tension_stiffening_zeta(0.5, 0.5) == pytest.approx(0.875)


# ---- the worked rectangular-beam anchor -----------------------------------

def test_rectangular_beam_matches_hand_calc():
    # C30/37, n = 6, M = 150 kNm sagging (bottom in tension where the bars are),
    # sustained loading (beta = 0.5, kt = 0.4), cover 37.5 mm to a 25 mm bar.
    sec = beam_section()
    fc = fctm(30.0)
    r = analyse_cracking(sec, 0.0, 150.0, 0.0, 6.0, fctm=fc,
                         Es=200_000.0, beta=0.5, kt=0.4, cover=37.5)
    assert r.cracked
    assert r.lambda_cr == pytest.approx(0.3969, abs=2e-3)
    assert r.zeta == pytest.approx(0.9212, abs=2e-3)
    assert gov_stress_mpa(r.cracked_state) == pytest.approx(204.0, rel=0.01)
    assert r.cracked_state.max_concrete_compression / 1000.0 == pytest.approx(13.10, rel=0.01)

    c = r.crack
    assert c is not None
    assert c.hc_ef == pytest.approx(0.125, abs=1e-3)
    assert c.rho_p_eff == pytest.approx(0.0393, rel=0.01)
    assert c.phi == pytest.approx(25.0, rel=0.01)
    assert c.esm_ecm == pytest.approx(8.38e-4, rel=0.01)
    assert c.sr_max == pytest.approx(235.7, rel=0.01)
    assert c.wk == pytest.approx(0.1975, rel=0.02)


def test_uncracked_below_cracking_load_uses_stage_i():
    # A small moment leaves the section uncracked: lambda_cr >= 1, zeta = 0, the
    # mean plane equals Stage I and no crack width is produced.
    sec = beam_section()
    fc = fctm(30.0)
    r = analyse_cracking(sec, 0.0, 40.0, 0.0, 6.0, fctm=fc, cover=37.5)
    assert not r.cracked
    assert r.lambda_cr > 1.0
    assert r.zeta == 0.0
    assert r.crack is None
    assert r.mean_plane == pytest.approx(r.uncracked.strain_plane)
    assert r.governing is r.uncracked


def test_beta_zero_gives_fully_cracked_mean():
    # No tension stiffening (beta = 0) -> zeta = 1 once cracked, so the mean
    # strain plane collapses onto the fully cracked Stage II solve.
    sec = beam_section()
    r = analyse_cracking(sec, 0.0, 150.0, 0.0, 6.0, fctm=fctm(30.0), beta=0.0)
    assert r.cracked
    assert r.zeta == 1.0
    assert r.mean_plane == pytest.approx(r.cracked_state.strain_plane)


def test_tension_stiffening_softens_mean_curvature():
    # The mean curvature lies between the (stiff) uncracked and (soft) cracked
    # states, i.e. tension stiffening reduces it below the bare cracked value.
    sec = beam_section()
    r = analyse_cracking(sec, 0.0, 150.0, 0.0, 6.0, fctm=fctm(30.0), beta=0.5)
    ky_un = abs(r.uncracked.ky)
    ky_cr = abs(r.cracked_state.ky)
    ky_m = abs(r.ky_m)
    assert ky_un < ky_m < ky_cr


def test_cracking_load_scales_proportionally():
    # Stage I is linear, so doubling the action halves the load factor to
    # cracking -- the biaxial proportional-scaling definition.
    sec = beam_section()
    fc = fctm(30.0)
    r1 = analyse_cracking(sec, 0.0, 100.0, 0.0, 6.0, fctm=fc)
    r2 = analyse_cracking(sec, 0.0, 200.0, 0.0, 6.0, fctm=fc)
    assert r2.lambda_cr == pytest.approx(r1.lambda_cr / 2.0, rel=1e-6)


def test_pure_compression_never_cracks():
    # Concentric axial compression with no net tension anywhere: infinite
    # cracking factor, uncracked, no crack width. The section is centred on the
    # origin so the load (applied about the origin) is truly concentric.
    sec = Section.from_polygon(
        corners=[(-0.15, -0.3), (0.15, -0.3), (0.15, 0.3), (-0.15, 0.3)],
        bars_xy_area_mm2=[],
    )
    r = analyse_cracking(sec, 500.0, 0.0, 0.0, 6.0, fctm=fctm(30.0), cover=37.5)
    assert math.isinf(r.lambda_cr)
    assert not r.cracked
    assert r.crack is None


def test_ecm_and_fctm_table_3_1():
    # Spot-check the EC2 Table 3.1 material defaults.
    assert fctm(30.0) == pytest.approx(2.896, abs=1e-3)
    assert fctm(50.0) == pytest.approx(4.072, abs=1e-3)
    assert ecm(30.0) == pytest.approx(32837.0, rel=1e-3)
