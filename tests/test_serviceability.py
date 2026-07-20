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
from sector.elastic import solve_elastic, transformed_properties
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


def test_crack_width_retains_sorted_per_bar_candidates():
    sec = beam_section()
    result = analyse_cracking(
        sec, 0.0, 150.0, 0.0, 6.0, fctm=fctm(30.0),
        bar_diameter=25.0,
    )
    crack = result.crack
    assert crack is not None
    assert len(crack.candidates) == 3
    assert [c.wk for c in crack.candidates] == sorted(
        (c.wk for c in crack.candidates), reverse=True)
    assert crack.candidates[0].bar_index == crack.gov_bar
    assert crack.candidates[0].area == pytest.approx(491.0)
    assert crack.candidates[0].x == pytest.approx(
        sec.bar_arrays()[0][crack.gov_bar])


def test_auto_per_bar_cover_matches_hand_calc():
    # With no explicit cover, each bar's clear cover is taken from the geometry:
    # the bars sit 0.05 m above the bottom face, so c = 50 - 25/2 = 37.5 mm, which
    # reproduces the worked crack width. The diameter is supplied (25 mm) so only
    # the cover is auto.
    sec = beam_section()
    r = analyse_cracking(sec, 0.0, 150.0, 0.0, 6.0, fctm=fctm(30.0),
                         Es=200_000.0, beta=0.5, kt=0.4, bar_diameter=25.0)
    assert r.crack is not None
    assert r.crack.cover == pytest.approx(37.5, abs=0.1)
    assert r.crack.wk == pytest.approx(0.1975, rel=0.02)


def test_per_bar_k1_lets_a_plain_bar_govern():
    # k1 (bond) may be given per bar -- e.g. mild bars vs prestressing tendons.
    # A plain bar (k1 = 1.6) cracks wider than the identical ribbed bars (k1 = 0.8)
    # around it, so it governs the reported crack width.
    sec = beam_section()
    base = analyse_cracking(sec, 0.0, 150.0, 0.0, 6.0, fctm=fctm(30.0),
                            beta=0.5, kt=0.4, bar_diameter=25.0, k1=0.8)
    mixed = analyse_cracking(sec, 0.0, 150.0, 0.0, 6.0, fctm=fctm(30.0),
                             beta=0.5, kt=0.4, bar_diameter=25.0, k1=[1.6, 0.8, 0.8])
    assert mixed.crack.gov_bar == 0          # the plain (k1 = 1.6) bar
    assert mixed.crack.wk > base.crack.wk


def test_effective_height_uses_neutral_axis_term():
    # A deep, lightly reinforced section where the (h - x)/3 limit governs hc,ef
    # (not 2.5(h-d) or h/2). The corrected limit is (s_tface - s_na)/3 ~ 0.27 m;
    # the old (h - s_na)/3 form would instead let h/2 = 0.5 m govern.
    sec = Section.from_polygon(
        corners=[(0.0, 0.0), (0.3, 0.0), (0.3, 1.0), (0.0, 1.0)],
        bars_xy_area_mm2=[(0.15, 0.2, 1500.0)],
    )
    r = analyse_cracking(sec, 0.0, 300.0, 0.0, 6.0, fctm=fctm(30.0), bar_diameter=25.0)
    assert r.cracked and r.crack is not None
    assert 0.22 < r.crack.hc_ef < 0.33     # ~ (h - x)/3, well below h/2 = 0.5


def test_dk_na_cover_dependent_k3_narrows_cracks():
    # DK NA 7.3.4(3): k3 = 3.4*(25/c)^(2/3). For cover > 25 mm this lowers the
    # crack spacing, so wk is smaller than with the base constant k3 = 3.4. The
    # verification beam's auto cover is ~ 37.5 mm.
    sec = beam_section()
    base = analyse_cracking(sec, 0.0, 150.0, 0.0, 6.0, fctm=fctm(30.0),
                            beta=0.5, kt=0.4, bar_diameter=25.0)
    dkna = analyse_cracking(sec, 0.0, 150.0, 0.0, 6.0, fctm=fctm(30.0),
                            beta=0.5, kt=0.4, bar_diameter=25.0,
                            k3_cover_dependent=True)
    assert dkna.crack.sr_max < base.crack.sr_max
    assert dkna.crack.wk < base.crack.wk


def test_dk_na_beam_drops_hx_term_in_effective_height():
    # DK NA 7.3.2(3): the (h-x)/3 limit applies only to slabs / prestressed
    # members. For an ordinary beam (include_hx_term=False) hc,ef = min(2.5(h-d),
    # h/2); on the deep section whose (h-x)/3 ~ 0.27 governed, it now uses h/2.
    sec = Section.from_polygon(
        corners=[(0.0, 0.0), (0.3, 0.0), (0.3, 1.0), (0.0, 1.0)],
        bars_xy_area_mm2=[(0.15, 0.2, 1500.0)],
    )
    beam = analyse_cracking(sec, 0.0, 300.0, 0.0, 6.0, fctm=fctm(30.0),
                            bar_diameter=25.0, include_hx_term=False)
    slab = analyse_cracking(sec, 0.0, 300.0, 0.0, 6.0, fctm=fctm(30.0),
                            bar_diameter=25.0, include_hx_term=True)
    assert beam.crack.hc_ef == pytest.approx(0.5, abs=0.02)   # h/2
    assert slab.crack.hc_ef < 0.35                            # (h-x)/3 ~ 0.27


def test_dk_na_coarse_crack_system_band_and_half_width():
    # DK NA 7.3.4(1) coarse crack system: the effective tension area is the band at
    # the tension face whose centroid matches the reinforcement (figure 7.100 NA) --
    # for this rectangle, 2*(h-d) = 0.10 m high, area b*0.10 = 0.03 m^2 -- and the
    # crack width (7.8) is halved. The 3 bars sit 0.05 m from the tension face.
    sec = beam_section()
    fc = fctm(30.0)
    fine = analyse_cracking(sec, 0.0, 150.0, 0.0, 6.0, fctm=fc, bar_diameter=25.0,
                            k3_cover_dependent=True)
    coarse = analyse_cracking(sec, 0.0, 150.0, 0.0, 6.0, fctm=fc, bar_diameter=25.0,
                              k3_cover_dependent=True, coarse=True)
    assert coarse.crack.coarse is True
    assert coarse.crack.hc_ef == pytest.approx(0.10, abs=1e-4)        # 2*(h-d)
    assert coarse.crack.ac_eff == pytest.approx(0.3 * 0.10, rel=1e-3)  # b * band
    # wk = 1/2 * sr_max * (eps_sm - eps_cm) with the coarse effective ratio.
    assert coarse.crack.wk == pytest.approx(
        0.5 * coarse.crack.sr_max * coarse.crack.esm_ecm, rel=1e-9)
    # The fine system keeps the EC2 hc,ef band (0.125 m here) and the full width.
    assert fine.crack.coarse is False
    assert fine.crack.hc_ef == pytest.approx(0.125, abs=1e-3)
    assert fine.crack.wk == pytest.approx(
        fine.crack.sr_max * fine.crack.esm_ecm, rel=1e-9)


def test_ec2_2023_refined_crack_width_hand_calc():
    # EN 1992-1-1:2023 (9.2.3): wk,cal = kw * k1/r * sr,m,cal * (eps_sm - eps_cm),
    # verified term by term for the 0.3x0.6 beam (3 x 491 mm2 bars at ay = 0.05 m),
    # phi = 16 mm, n = 6, long-term (kt = 0.4).
    sec = beam_section()
    fc = fctm(30.0)
    r = analyse_cracking(sec, 0.0, 150.0, 0.0, 6.0, fctm=fc, bar_diameter=16.0,
                         beta=0.5, kt=0.4, edition="2023")
    cw = r.crack
    assert cw.edition == "2023" and cw.kw == 1.7
    # hc,eff = min(ay+5phi, 10phi, 3.5ay, h-x, h/2) = ay + 5phi = 0.05 + 0.08 = 0.13 m.
    assert cw.hc_ef == pytest.approx(0.13, abs=1e-4)
    assert cw.rho_p_eff == pytest.approx(3 * 491e-6 / (0.3 * 0.13), rel=1e-3)
    assert cw.cover == pytest.approx(42.0, abs=0.5)             # 50 mm - 16/2
    assert cw.k1_r > 1.0                                        # curvature factor (9.9)
    # (9.11) lower bound is (1 - kt)*sigma_s/Es, not the 2004 fixed 0.6*sigma_s/Es.
    num = (cw.sigma_s - 0.4 * fc / cw.rho_p_eff * (1 + 6 * cw.rho_p_eff)) / 200_000.0
    assert cw.esm_ecm == pytest.approx(max(num, (1 - 0.4) * cw.sigma_s / 200_000.0),
                                       rel=1e-6)
    # (9.15) mean spacing = 1.5c + (kfl*kb/7.2)*(phi/rho); kb = 0.9 (good bond, k1=0.8).
    expect_sr = 1.5 * cw.cover + cw.kfl * 0.9 / 7.2 * cw.phi / cw.rho_p_eff
    assert cw.sr_max == pytest.approx(expect_sr, rel=1e-6)   # matches => below the cap
    # (9.8) assembly.
    assert cw.wk == pytest.approx(cw.kw * cw.k1_r * cw.sr_max * cw.esm_ecm, rel=1e-9)


def test_transformed_properties_use_per_bar_modular_ratio():
    # n_mult scales each bar's modular ratio (Ep/Es for tendons): a stiffer bar pulls
    # the transformed centroid toward it, so xg differs from the all-equal-n case.
    from sector.elastic import transformed_properties
    sec = Section.from_polygon(
        corners=[(0.0, 0.0), (0.3, 0.0), (0.3, 0.6), (0.0, 0.6)],
        bars_xy_area_mm2=[(0.15, 0.05, 1000.0)],         # one bar near the bottom
    )
    base = transformed_properties(sec, 6.0, cracked=False)
    stiffer = transformed_properties(sec, 6.0, cracked=False, n_mult=np.array([2.5]))
    assert stiffer.cy < base.cy                          # stiffer bottom bar pulls cy down


def test_ec2_2023_kfl_responds_to_n_mult():
    # With a fixed cracked state, n_mult enters the 2023 result only through kfl (the
    # uncracked transformed NA xg). A higher per-bar ratio shifts xg, so kfl -- and the
    # crack spacing it feeds -- move; this is the prestress-aware path Codex flagged.
    from sector.elastic import solve_elastic
    from sector.serviceability import crack_width
    sec = beam_section()
    fc = fctm(30.0)
    state = solve_elastic(sec, 0.0, 150.0, 0.0, 6.0)
    base = crack_width(sec, state, 6.0, fctm=fc, bar_diameter=16.0, kt=0.4,
                       edition="2023")
    mult = crack_width(sec, state, 6.0, fctm=fc, bar_diameter=16.0, kt=0.4,
                       edition="2023", n_mult=np.full(3, 3.0))
    assert base.kfl != pytest.approx(mult.kfl, rel=1e-6)
    assert base.sr_max != pytest.approx(mult.sr_max, rel=1e-6)   # kfl feeds sr,m,cal
    assert base.sigma_s == pytest.approx(mult.sigma_s)           # state fixed -> sigma_s same


def test_ec2_2004_wide_spacing_assigns_geometric_spacing():
    # A single bar in a wide section (not at close centres): EC2 (7.14) assigns the
    # crack spacing as 1.3*(h-x) directly. Here (7.11) is the larger value, so the
    # assignment reads as a reduction from the close-centre formula.
    from sector.serviceability import _depth_axis
    sec = Section.from_polygon(
        corners=[(0.0, 0.0), (0.5, 0.0), (0.5, 0.6), (0.0, 0.6)],
        bars_xy_area_mm2=[(0.25, 0.05, 314.0)],
    )
    r = analyse_cracking(sec, 0.0, 120.0, 0.0, 6.0, fctm=fctm(30.0), bar_diameter=20.0)
    assert r.cracked
    cw = r.crack
    eq711 = 3.4 * cw.cover + 0.8 * 0.5 * 0.425 * cw.phi / cw.rho_p_eff  # Eq (7.11)
    assert cw.sr_max < eq711                                   # (7.14) is smaller here
    gx, gy, mag = _depth_axis(r.cracked_state.kx, r.cracked_state.ky)
    verts = sec.concrete_vertices()
    s_tface = float((verts[:, 0] * gx + verts[:, 1] * gy).max())
    hx = s_tface - (-r.cracked_state.eps0 / mag)               # h - x, m
    assert cw.sr_max == pytest.approx(1.3 * hx * 1000.0, rel=1e-6)
    assert cw.sr_max_geometric is True


def test_ec2_2004_wide_spacing_uses_geometric_even_when_711_smaller():
    # For a wide/isolated bar EC2 (7.14) is the ASSIGNED spacing, not merely an upper
    # cap: an isolated bar in a deep tension zone with a high reinforcement ratio has
    # (7.11) far below 1.3*(h-x), yet the wide-spacing case must still report 1.3*(h-x)
    # (the old min() branch under-reported wk here).
    from sector.serviceability import _depth_axis
    sec = Section.from_polygon(
        corners=[(0.0, 0.0), (0.4, 0.0), (0.4, 1.2), (0.0, 1.2)],
        bars_xy_area_mm2=[(0.20, 0.06, 4000.0)],
    )
    r = analyse_cracking(sec, 0.0, 400.0, 0.0, 6.0, fctm=fctm(30.0),
                         bar_diameter=16.0, cover=30.0)
    assert r.cracked
    cw = r.crack
    eq711 = 3.4 * cw.cover + 0.8 * 0.5 * 0.425 * cw.phi / cw.rho_p_eff  # Eq (7.11)
    gx, gy, mag = _depth_axis(r.cracked_state.kx, r.cracked_state.ky)
    verts = sec.concrete_vertices()
    s_tface = float((verts[:, 0] * gx + verts[:, 1] * gy).max())
    hx = s_tface - (-r.cracked_state.eps0 / mag)               # h - x, m
    assert eq711 < 1.3 * hx * 1000.0                           # (7.11) is the smaller value
    assert cw.sr_max == pytest.approx(1.3 * hx * 1000.0, rel=1e-6)   # yet (7.14) is assigned
    assert cw.sr_max_geometric is True


def test_ec2_2004_close_spacing_keeps_full_crack_spacing():
    # EC2 (7.14)'s 1.3*(h-x) bound is the ALTERNATIVE for bars NOT at close centres
    # (7.3.4(3)). Two closely-spaced bars (40 mm apart) with a large cover in a
    # shallow-tension section give a large (7.11) spacing while 1.3*(h-x) is small;
    # the bound must NOT clip the close-spaced spacing (that was the mis-cap).
    from sector.serviceability import _depth_axis
    sec = Section.from_polygon(
        corners=[(0.0, 0.0), (1.2, 0.0), (1.2, 0.25), (0.0, 0.25)],
        bars_xy_area_mm2=[(0.58, 0.05, 201.0), (0.62, 0.05, 201.0)],
    )
    r = analyse_cracking(sec, 0.0, 40.0, 0.0, 6.0, fctm=fctm(30.0),
                         bar_diameter=16.0, cover=80.0)
    assert r.cracked
    cw = r.crack
    uncapped = 3.4 * cw.cover + 0.8 * 0.5 * 0.425 * cw.phi / cw.rho_p_eff  # Eq (7.11)
    gx, gy, mag = _depth_axis(r.cracked_state.kx, r.cracked_state.ky)
    verts = sec.concrete_vertices()
    s_tface = float((verts[:, 0] * gx + verts[:, 1] * gy).max())
    hx = s_tface - (-r.cracked_state.eps0 / mag)                # h - x, m
    assert 1.3 * hx * 1000.0 < uncapped                        # cap WOULD bite if applied
    assert cw.sr_max == pytest.approx(uncapped, rel=1e-6)      # but close spacing keeps (7.11)
    assert cw.sr_max_geometric is False


def test_ec2_2023_hc_eff_covers_multiple_tension_layers():
    # Two tension layers (y = 0.05 and 0.10 m): hc,eff extends past the single-layer
    # band by the layer spread, per the n-layer form of figure 9.3.
    two = Section.from_polygon(
        corners=[(0.0, 0.0), (0.3, 0.0), (0.3, 0.6), (0.0, 0.6)],
        bars_xy_area_mm2=[(0.075, 0.05, 491.0), (0.225, 0.05, 491.0),
                          (0.075, 0.10, 491.0), (0.225, 0.10, 491.0)],
    )
    one = Section.from_polygon(
        corners=[(0.0, 0.0), (0.3, 0.0), (0.3, 0.6), (0.0, 0.6)],
        bars_xy_area_mm2=[(0.075, 0.05, 491.0), (0.225, 0.05, 491.0)],
    )
    cw2 = analyse_cracking(two, 0.0, 150.0, 0.0, 6.0, fctm=fctm(30.0),
                           bar_diameter=16.0, edition="2023").crack
    cw1 = analyse_cracking(one, 0.0, 150.0, 0.0, 6.0, fctm=fctm(30.0),
                           bar_diameter=16.0, edition="2023").crack
    assert cw1.hc_ef == pytest.approx(0.13, abs=1e-3)          # single layer: ay+5phi
    assert cw2.hc_ef == pytest.approx(0.18, abs=1e-3)          # + 0.05 m layer spread
    assert cw2.hc_ef > cw1.hc_ef


def test_ec2_2023_hc_eff_uses_near_face_layer_diameter():
    # The hc,eff phi terms (ay+5phi, 10phi) must use the NEAR-FACE layer's diameter,
    # not the maximum-stress bar's. With a small bar near the tension face and a large
    # bar deeper, an externally supplied state where the deep bar carries the higher
    # stress must still size hc,eff from the small near-face bar.
    import dataclasses
    from sector.serviceability import _depth_axis, crack_width
    sec = Section.from_polygon(
        corners=[(0.0, 0.0), (0.3, 0.0), (0.3, 0.6), (0.0, 0.6)],
        bars_xy_area_mm2=[(0.15, 0.04, 113.0), (0.15, 0.14, 804.0)],  # ~12 mm near, ~32 mm deep
    )
    st = analyse_cracking(sec, 0.0, 120.0, 0.0, 6.0, fctm=fctm(30.0),
                          edition="2023").cracked_state
    bs = st.bar_stress.copy()
    bs[1] = bs[0] * 1.5                         # force the deep large bar to govern by stress
    st2 = dataclasses.replace(st, bar_stress=bs)
    auto = crack_width(sec, st2, 6.0, fctm=fctm(30.0), edition="2023")
    near = crack_width(sec, st2, 6.0, fctm=fctm(30.0), edition="2023", bar_diameter=12.0)
    deep = crack_width(sec, st2, 6.0, fctm=fctm(30.0), edition="2023", bar_diameter=32.0)
    assert auto.hc_ef == pytest.approx(near.hc_ef, abs=1e-3)    # near-face (small) diameter
    assert auto.hc_ef < deep.hc_ef                             # NOT the deep max-stress bar


def test_ec2_2023_hc_eff_ignores_bars_above_the_neutral_axis():
    # An externally supplied combined-creep state can leave a compression-side bar
    # (above the NA) with a small positive residual stress. That bar must not be
    # counted as an effective tension layer: hc,eff and rho_p,eff must be identical
    # whether its stress is left compressive or forced positive (the per-bar loop
    # skips it either way, so the layer set must too).
    import dataclasses
    from sector.serviceability import _depth_axis, crack_width
    sec = Section.from_polygon(
        corners=[(0.0, 0.0), (0.3, 0.0), (0.3, 0.6), (0.0, 0.6)],
        bars_xy_area_mm2=[(0.10, 0.05, 491.0), (0.20, 0.05, 491.0),
                          (0.15, 0.55, 491.0)],   # third bar near the compression face
    )
    r = analyse_cracking(sec, 0.0, 150.0, 0.0, 6.0, fctm=fctm(30.0),
                         bar_diameter=16.0, edition="2023")
    st = r.cracked_state
    gx, gy, mag = _depth_axis(st.kx, st.ky)
    bx, by, _ = sec.bar_arrays()
    verts = sec.concrete_vertices()
    s_tface = float((verts[:, 0] * gx + verts[:, 1] * gy).max())
    ay = s_tface - (bx * gx + by * gy)
    hx = s_tface - (-st.eps0 / mag)
    top = int(np.argmax(ay))
    assert ay[top] > hx                       # the third bar really is above the NA

    ref = crack_width(sec, st, 6.0, fctm=fctm(30.0), bar_diameter=16.0, edition="2023")
    bs = st.bar_stress.copy()
    bs[top] = +50_000.0                        # +50 MPa spurious residual (kN/m^2 units)
    pos = crack_width(sec, dataclasses.replace(st, bar_stress=bs), 6.0,
                      fctm=fctm(30.0), bar_diameter=16.0, edition="2023")
    assert pos.hc_ef == pytest.approx(ref.hc_ef)
    assert pos.rho_p_eff == pytest.approx(ref.rho_p_eff)


def test_ec2_2023_and_2004_crack_widths_are_the_same_order():
    # The 2023 refined model gives a crack width in the same range as the 2004 model
    # (a different formula, not a different answer by an order of magnitude).
    sec = beam_section()
    fc = fctm(30.0)
    w04 = analyse_cracking(sec, 0.0, 150.0, 0.0, 6.0, fctm=fc, bar_diameter=16.0,
                           beta=0.5, kt=0.4, edition="2004").crack.wk
    w23 = analyse_cracking(sec, 0.0, 150.0, 0.0, 6.0, fctm=fc, bar_diameter=16.0,
                           beta=0.5, kt=0.4, edition="2023").crack.wk
    assert 0.5 * w04 < w23 < 1.5 * w04


def test_dk_na_coarse_band_centroid_matches_reinforcement():
    # The coarse effective band is solved by a centroid match, not a fixed 2*(h-d)
    # for a rectangle only: its area-centroid along the depth axis must coincide
    # with the tension reinforcement's centroid even when the width varies. A wide
    # bottom flange (area bunched at the tension face) forces a taller band than the
    # prismatic 2*(h-d) = 0.24 m to lift the centroid up to the bars.
    from sector.serviceability import _band_moments, _depth_axis
    sec = Section.from_polygon(
        corners=[(0.0, 0.0), (0.6, 0.0), (0.6, 0.08), (0.2, 0.08),
                 (0.2, 0.6), (0.0, 0.6)],                    # wide flange, y < 0.08
        bars_xy_area_mm2=[(0.1, 0.12, 800.0), (0.15, 0.12, 800.0)],  # bars above the step
    )
    r = analyse_cracking(sec, 0.0, 200.0, 0.0, 6.0, fctm=fctm(30.0),
                         bar_diameter=20.0, coarse=True)
    assert r.cracked
    cw = r.crack
    assert cw is not None and cw.coarse is True
    gx, gy, _ = _depth_axis(r.cracked_state.kx, r.cracked_state.ky)
    verts = sec.concrete_vertices()
    s_tface = float((verts[:, 0] * gx + verts[:, 1] * gy).max())
    band = _band_moments(list(sec.integration_rings()), gx, gy, s_tface - cw.hc_ef)
    band_centroid = (band.sx * gx + band.sy * gy) / band.area
    bx, by, ba = sec.bar_arrays()
    s_rc = float(np.sum(ba * (bx * gx + by * gy)) / np.sum(ba))
    assert band_centroid == pytest.approx(s_rc, abs=1e-4)
    assert cw.hc_ef > 0.24                                    # taller than a prism


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
    # Stage I and Stage II differ substantially here, so anything that plots the
    # governing state (the crack-control view) must use the uncracked solve, not
    # the cracked one.
    assert r.uncracked.na_y_intercept != pytest.approx(
        r.cracked_state.na_y_intercept, abs=1e-3)


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


def test_transformed_section_properties_match_hand_calc():
    # The uncracked transformed section and the cracked transformed section
    # (compression block + n*As) reproduce the hand-worked area, centroid and
    # second moment about the bending (x) axis.
    sec = beam_section()
    pu = transformed_properties(sec, 6.0, cracked=False)
    assert pu.area == pytest.approx(0.18884, rel=1e-3)
    assert pu.cy == pytest.approx(0.28830, abs=1e-4)
    assert pu.Ix == pytest.approx(0.0059265, rel=1e-3)

    r = solve_elastic(sec, 0.0, 150.0, 0.0, 6.0)
    pc = transformed_properties(sec, 6.0, eps0=r.eps0, kx=r.kx, ky=r.ky, cracked=True)
    assert pc.Ix == pytest.approx(0.0017511, rel=1e-3)
    assert pc.area < pu.area          # cracked section drops the tension concrete
    # For pure bending the cracked centroid sits on the neutral axis.
    assert pc.cy == pytest.approx(r.na_y_intercept, abs=1e-3)


def test_ecm_and_fctm_table_3_1():
    # Spot-check the EC2 Table 3.1 material defaults.
    assert fctm(30.0) == pytest.approx(2.896, abs=1e-3)
    assert fctm(50.0) == pytest.approx(4.072, abs=1e-3)
    assert ecm(30.0) == pytest.approx(32837.0, rel=1e-3)
