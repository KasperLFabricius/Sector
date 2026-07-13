"""Conditional chord capacity under biaxial bending (sector.plastic.conditional_capacity).

The longitudinal chord check compares its demand against the bending capacity about
the shear axis. Under biaxial bending the pure-axis capacity overstates what the
chord can lean on -- the section cannot deliver its full uniaxial MRd while also
carrying the off-axis moment -- so the capacity is CONDITIONAL: the point on the
plastic M-M envelope branch (chosen face in tension) whose companion moment equals
the acting off-axis moment. These tests pin the root-find engine helper and the
app wiring (chord MRd, the new off-axis chord check, and the strut-angle scan).
"""

from __future__ import annotations

import math
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import manual  # noqa: E402  (real app preset materials + example sections)
from sector import combined  # noqa: E402
from sector.plastic import (  # noqa: E402
    conditional_capacity,
    plastic_capacity_at_angle,
    solve_plastic,
)

APP = str(ROOT / "app" / "sector_app.py")


def _beam():
    ex = manual.example_beam()
    return manual._section_of(ex), ex["concrete"], ex["steel"]


# -- engine ------------------------------------------------------------------

def test_conditional_equals_pure_axis_when_companion_matches():
    # The pure-axis angle is probed first: when the companion moment there already
    # equals the target (a section symmetric about the off axis under a uniaxial
    # load), the result is the SAME solve at the SAME angle -- bit-identical, so
    # every pre-conditional uniaxial result is reproduced exactly.
    sec, c, s = _beam()
    p90 = plastic_capacity_at_angle(sec, c, s, 0.0, 90.0)
    assert abs(p90.My) < 1e-9                  # symmetric about y: no companion
    mrd, exact = conditional_capacity(sec, c, s, 0.0, "x", True, 0.0)
    assert exact
    assert mrd == abs(p90.Mx)                  # exact equality, not approx


def test_conditional_decreases_with_off_moment():
    # A growing off-axis moment consumes envelope: the conditional capacity about
    # the shear axis must fall monotonically from the pure-axis value.
    sec, c, s = _beam()
    my_pure = plastic_capacity_at_angle(sec, c, s, 0.0, 0.0).My
    vals = []
    for frac in (0.0, 0.3, 0.6, 0.9):
        mrd, exact = conditional_capacity(sec, c, s, 0.0, "x", True, frac * my_pure)
        assert exact
        vals.append(mrd)
    assert all(vals[i] > vals[i + 1] for i in range(len(vals) - 1))


def test_conditional_point_lies_on_envelope():
    # The (mrd, m_off) pair is a point ON the M-M envelope: its radial utilisation
    # against a fine sweep must be ~1 (small tolerance for the sweep's chords).
    sec, c, s = _beam()
    pts = solve_plastic(sec, c, s, 0.0, 0.0, 359.0, 1.0)
    mx, my = [p.Mx for p in pts], [p.My for p in pts]
    m_off = 0.5 * plastic_capacity_at_angle(sec, c, s, 0.0, 0.0).My
    mrd, exact = conditional_capacity(sec, c, s, 0.0, "x", True, m_off)
    assert exact
    util, _ = combined.radial_util(mx, my, mrd, m_off)
    assert util == pytest.approx(1.0, abs=0.02)


def test_conditional_beyond_envelope_is_honest_zero():
    # An off-axis moment the branch cannot carry at all leaves NO capacity about
    # the shear axis: (0.0, True) -- a genuine zero, not a solver failure.
    sec, c, s = _beam()
    my_pure = plastic_capacity_at_angle(sec, c, s, 0.0, 0.0).My
    mrd, exact = conditional_capacity(sec, c, s, 0.0, "x", True, 1.5 * my_pure)
    assert exact
    assert mrd == 0.0


def test_conditional_high_face_and_negative_off_moment():
    # The high face (V0 = 270) with a hogging companion: the branch brackets
    # [180, 360] and the returned capacity is the face's magnitude.
    sec, c, s = _beam()
    p270 = plastic_capacity_at_angle(sec, c, s, 0.0, 270.0)
    mrd0, exact0 = conditional_capacity(sec, c, s, 0.0, "x", False, 0.0)
    assert exact0 and mrd0 == abs(p270.Mx)     # symmetric: early-out, exact
    my_pure = plastic_capacity_at_angle(sec, c, s, 0.0, 0.0).My
    mrd, exact = conditional_capacity(sec, c, s, 0.0, "x", False, -0.5 * my_pure)
    assert exact
    assert 0.0 < mrd < mrd0


def test_conditional_y_axis_asymmetric_companion():
    # The example beam is asymmetric about x: at the pure-y-face angle (V0 = 0)
    # the capacity point carries a companion Mx != 0, so the legacy "pure-axis"
    # value was itself conditional on an unrequested Mx. Asking for Mx = 0 finds
    # the angle where the companion truly vanishes -- an on-envelope point that
    # differs from the V0 solve. This is the asymmetric-section refinement.
    sec, c, s = _beam()
    p0 = plastic_capacity_at_angle(sec, c, s, 0.0, 0.0)
    assert abs(p0.Mx) > 1.0                    # a real companion moment at V0
    mrd, exact = conditional_capacity(sec, c, s, 0.0, "y", True, 0.0)
    assert exact
    assert 0.0 < mrd
    assert mrd != pytest.approx(abs(p0.My), rel=1e-6)   # differs from legacy
    pts = solve_plastic(sec, c, s, 0.0, 0.0, 359.0, 1.0)
    util, _ = combined.radial_util([p.Mx for p in pts], [p.My for p in pts],
                                   0.0, mrd)
    assert util == pytest.approx(1.0, abs=0.02)          # on the envelope


def _brute_slice(sec, c, s, P, axis, tension_low, m_off, pre=None):
    """Reference: a fine full-circle envelope scan, taking the correct-face own
    moment where the companion crosses ``m_off`` (linear-interpolated). Independent
    of conditional_capacity's own bisection -- the ground truth it must match."""
    import numpy as np
    comp = (lambda p: p.My) if axis == "x" else (lambda p: p.Mx)
    own = (lambda p: p.Mx) if axis == "x" else (lambda p: p.My)
    pts = [plastic_capacity_at_angle(sec, c, s, P, v, prestress=pre)
           for v in np.arange(0.0, 360.2, 0.2)]
    caps = []
    for a, b in zip(pts, pts[1:]):
        if not (a.converged and b.converged):
            continue
        if (comp(a) - m_off < 0.0) != (comp(b) - m_off < 0.0):
            span = comp(b) - comp(a)
            t = (m_off - comp(a)) / span if span else 0.0
            o = own(a) + t * (own(b) - own(a))
            if (o > 0.0) if tension_low else (o < 0.0):
                caps.append(abs(o))
    return max(caps) if caps else 0.0


def _asym_section():
    # Diagonally asymmetric (broken about BOTH axes): a bottom-left bar cluster.
    # This is the regime where the companion is non-monotone over a face's branch
    # and the own moment can take the wrong sign near a branch endpoint.
    from sector.section import Section
    outer = [(-0.15, -0.30), (0.15, -0.30), (0.15, 0.30), (-0.15, 0.30)]
    bars = [(-0.11, -0.26, 804), (-0.05, -0.26, 804), (-0.11, -0.15, 509),
            (0.11, -0.26, 201), (0.11, 0.26, 201), (-0.11, 0.26, 113)]
    return Section.from_polygon(outer, bars)


def test_conditional_matches_envelope_slice_on_asymmetric_section():
    # The correctness pin for the full-circle rewrite: on a section asymmetric about
    # BOTH axes (where the old fixed-bracket root-find could return a wrong-face
    # capacity or a false honest-zero), conditional_capacity must equal the
    # independent brute-force envelope slice for every axis/face/off-moment -- and
    # must NEVER return a capacity from the wrong face (the nonconservative bug).
    ex = _beam(); _, c, s = ex
    sec = _asym_section()
    for axis in ("x", "y"):
        comp = (lambda p: p.My) if axis == "x" else (lambda p: p.Mx)
        cmax = max(abs(comp(plastic_capacity_at_angle(sec, c, s, 0.0, v)))
                   for v in range(0, 360, 3))
        for tl in (True, False):
            for frac in (0.0, 0.35, 0.7, 1.1):     # 1.1 -> beyond the branch
                m_off = (frac if tl else -frac) * cmax
                mrd, exact = conditional_capacity(sec, c, s, 0.0, axis, tl, m_off)
                ref = _brute_slice(sec, c, s, 0.0, axis, tl, m_off)
                assert exact
                assert mrd == pytest.approx(ref, abs=2.5)


def test_conditional_capacity_recovers_the_under_sampled_peak():
    # Codex P2: when the requested companion equals a companion extremum, the coarse
    # scan's samples all sit just short of it, so a sign-change-only search would miss
    # the crossing and falsely report an honest zero. Sweeping the target right up to
    # the true peak must keep matching the fine brute slice (no gap, no false zero),
    # and stepping just past the peak must give the honest zero.
    import numpy as np
    sec = _asym_section()
    _, c, s = _beam()
    peak = max(plastic_capacity_at_angle(sec, c, s, 0.0, v).My
               for v in np.arange(0.0, 360.0, 0.1))
    for moff in (peak - 8.0, peak - 2.0, peak - 0.3):
        mrd, exact = conditional_capacity(sec, c, s, 0.0, "x", True, float(moff))
        assert exact and mrd > 0.0                        # capacity NOT lost near peak
        assert mrd == pytest.approx(
            _brute_slice(sec, c, s, 0.0, "x", True, float(moff)), abs=2.5)
    beyond, ex_b = conditional_capacity(sec, c, s, 0.0, "x", True, peak + 5.0)
    assert ex_b and beyond == 0.0                          # past the peak -> honest zero


def test_conditional_capacity_with_axial_and_prestress():
    # The app always calls at the applied N and with prestress; axial compression
    # reshapes the envelope and prestress shifts it asymmetrically, so pin both:
    # exact, on-envelope, and monotone-decreasing there too.
    exc = manual.example_circular()
    sec, c, s, pre = (manual._section_of(exc), exc["concrete"], exc["steel"],
                      exc["prestress"])
    P = 500.0
    my_pure = plastic_capacity_at_angle(sec, c, s, P, 0.0, prestress=pre).My
    m0, e0 = conditional_capacity(sec, c, s, P, "x", True, 0.0, prestress=pre)
    m1, e1 = conditional_capacity(sec, c, s, P, "x", True, 0.5 * my_pure,
                                  prestress=pre)
    assert e0 and e1
    assert 0.0 < m1 < m0                                  # capacity consumed by My
    for moff in (0.0, 0.5 * my_pure):
        mrd, _ = conditional_capacity(sec, c, s, P, "x", True, moff, prestress=pre)
        assert mrd == pytest.approx(
            _brute_slice(sec, c, s, P, "x", True, moff, pre=pre), abs=3.0)


# -- app integration (AppTest) ------------------------------------------------

def _fresh():
    from streamlit.testing.v1 import AppTest
    return AppTest.from_file(APP, default_timeout=120)


# Distinct Mx/My magnitudes so an axis/argument transposition changes the numbers
# (a symmetric 100/100 would let m_signed<->off_signed swaps pass silently).
_MX, _MY = 100.0, 60.0


def _mvt(at, my=0.0, torsion=True):
    at.number_input(key="pl_Mx").set_value(_MX).run()
    if my:
        at.number_input(key="pl_My").set_value(my).run()
    at.checkbox(key="shear_on").set_value(True).run()
    at.checkbox(key="shear_links").set_value(True).run()
    at.number_input(key="shear_V").set_value(150.0).run()
    if torsion:
        at.checkbox(key="torsion_on").set_value(True).run()
        at.number_input(key="torsion_T").set_value(40.0).run()
    at.checkbox(key="combined_on").set_value(True).run()
    at.button(key="calculate").click().run()
    return at


def test_app_chord_mrd_conditional_under_biaxial():
    # Biaxial run: the chord MRd is the conditional capacity -- strictly below the
    # uniaxial value -- the payload records the acting off moment, and the verdict
    # is honest (conditional=True, no fallback warning path).
    at = _fresh(); at.run()
    _mvt(at)                                        # uniaxial first (My = 0)
    lg_uni = at.session_state["results"]["combined"]["longitudinal"]
    assert lg_uni["conditional"] and lg_uni["m_off"] == 0.0
    m_rd_uni = lg_uni["m_rd"]
    at.number_input(key="pl_My").set_value(_MY).run()
    at.button(key="calculate").click().run()
    lg = at.session_state["results"]["combined"]["longitudinal"]
    assert lg["biaxial"] and lg["conditional"]
    assert lg["axis"] == "x"                        # vertical shear -> chord about x
    assert lg["m_off"] == pytest.approx(_MY)        # conditioned on My, NOT Mx
    assert 0.0 < lg["m_rd"] < m_rd_uni              # capacity consumed by My


def test_app_off_axis_chord_present_with_torsion():
    # Torsion live on a single tube: the off-axis chord is checked -- bending
    # tension about the other axis plus the torsion share, no shear shift.
    at = _fresh(); at.run()
    _mvt(at, my=_MY)
    och = at.session_state["results"]["shear"]["links"]["chord_off"]
    assert och is not None and och["valid"]
    lg = at.session_state["results"]["combined"]["longitudinal"]
    assert lg["axis"] == "x" and och["axis"] == "y"
    assert och["ftd_v"] == 0.0 and och["mv"] == 0.0  # no shear shift here
    assert och["mt"] > 0.0                           # the torsion share acts
    # Distinct magnitudes pin which moment plays which role (a swap would fail):
    assert och["m_ed"] == pytest.approx(_MY)         # |My| tensions the y-face
    assert och["m_off"] == pytest.approx(_MX)        # conditioned on Mx
    assert math.isfinite(och["util"]) and och["util"] > 0.0
    # The combined view shows the same payload.
    assert at.session_state["results"]["combined"]["chord_off"] is och


def test_app_off_axis_chord_absent_without_torsion():
    # Without torsion the off-axis chord carries only its bending tension, which
    # the biaxial bending check already covers -- no separate chord check.
    at = _fresh(); at.run()
    _mvt(at, my=_MY, torsion=False)
    links = at.session_state["results"]["shear"]["links"]
    assert links["chord_off"] is None
    # The shear-plane chord itself is still conditional and biaxial-aware
    # (without torsion there is no combined "longitudinal" payload).
    ch = links["chord"]
    assert ch["biaxial"] and not ch["has_torsion"] and ch["conditional"]


def test_app_zero_capacity_chord_does_not_poison_the_scan():
    # An off-axis moment beyond the envelope leaves zero conditional capacity: the
    # chord reports utilisation = inf (honest), but is kept OUT of the strut-angle
    # objective. If it leaked in, governing_strut_cot would see inf at every angle
    # and tie to the band LOW edge (cot = 1.0); the healthy finite optimum here is
    # well above it, so cot >> 1.0 pins that the guard actually excludes the chord.
    at = _fresh(); at.run()
    _mvt(at)
    my_max = at.session_state["results"]["plastic"]["max_my"]
    at.number_input(key="pl_My").set_value(float(my_max) * 1.5).run()
    at.button(key="calculate").click().run()
    assert not at.exception
    res = at.session_state["results"]
    lg = res["combined"]["longitudinal"]
    assert lg["conditional"] and lg["m_rd"] == 0.0
    assert math.isinf(lg["util"])                     # zero capacity, real demand
    lk = res["shear"]["links"]["res"]
    assert lk["valid"] and math.isfinite(lk["cot"])
    assert lk["cot"] > 1.5                            # NOT pinned to the band low edge


def test_app_off_axis_chord_skipped_on_subdivided_section():
    # Compound section: the torsion steel is per sub-tube, so the off-axis chord
    # is not evaluated -- the payload says why, and no off-chord is reported.
    at = _fresh(); at.run()
    at.checkbox(key="torsion_subdivide").set_value(True).run()
    _mvt(at, my=_MY)
    t = at.session_state["results"]["torsion"]
    assert t["subdivided"]
    lg = at.session_state["results"]["combined"]["longitudinal"]
    assert lg["off_not_evaluated"] == "subdivided"
    assert at.session_state["results"]["shear"]["links"]["chord_off"] is None


def test_shear_face_mrd_falls_back_to_pure_axis_on_solve_failure(monkeypatch):
    # The fallback chain has to be exercised on the real code, not a hand-built
    # payload: when the conditional solve fails (raises, or returns (0.0, False)),
    # _shear_face_mrd returns the LEGACY pure-axis capacity with conditional=False,
    # which drives the UI/report biaxial warning.
    import sector_app
    ex = manual.example_beam()
    inp = dict(section=manual._section_of(ex), concrete=ex["concrete"],
               steel=ex["steel"], P_pl=0.0, tendons=False, prestress=None)
    legacy = abs(plastic_capacity_at_angle(inp["section"], inp["concrete"],
                                           inp["steel"], 0.0, 90.0).Mx)
    monkeypatch.setattr(sector_app, "conditional_capacity",
                        lambda *a, **k: (0.0, False))
    mrd, cond = sector_app._shear_face_mrd(inp, "x", True, m_off=50.0)
    assert cond is False and mrd == pytest.approx(legacy)

    def _boom(*a, **k):
        raise RuntimeError("solve blew up")
    monkeypatch.setattr(sector_app, "conditional_capacity", _boom)
    mrd2, cond2 = sector_app._shear_face_mrd(inp, "x", True, m_off=50.0)
    assert cond2 is False and mrd2 == pytest.approx(legacy)
