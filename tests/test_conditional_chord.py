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


# -- app integration (AppTest) ------------------------------------------------

def _fresh():
    from streamlit.testing.v1 import AppTest
    return AppTest.from_file(APP, default_timeout=120)


def _mvt(at, my=0.0, torsion=True):
    at.number_input(key="pl_Mx").set_value(100.0).run()
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
    at.number_input(key="pl_My").set_value(100.0).run()
    at.button(key="calculate").click().run()
    lg = at.session_state["results"]["combined"]["longitudinal"]
    assert lg["biaxial"] and lg["conditional"]
    assert lg["m_off"] == pytest.approx(100.0)
    assert 0.0 < lg["m_rd"] < m_rd_uni              # capacity consumed by My


def test_app_off_axis_chord_present_with_torsion():
    # Torsion live on a single tube: the off-axis chord is checked -- bending
    # tension about the other axis plus the torsion share, no shear shift.
    at = _fresh(); at.run()
    _mvt(at, my=100.0)
    och = at.session_state["results"]["shear"]["links"]["chord_off"]
    assert och is not None and och["valid"]
    lg = at.session_state["results"]["combined"]["longitudinal"]
    assert och["axis"] != lg["axis"]
    assert och["ftd_v"] == 0.0 and och["mv"] == 0.0  # no shear shift here
    assert och["mt"] > 0.0                           # the torsion share acts
    assert och["m_ed"] == pytest.approx(100.0)       # |My| tensions its face
    assert och["m_off"] == pytest.approx(100.0)      # conditional on Mx
    assert math.isfinite(och["util"]) and och["util"] > 0.0
    # The combined view shows the same payload.
    assert at.session_state["results"]["combined"]["chord_off"] is och


def test_app_off_axis_chord_absent_without_torsion():
    # Without torsion the off-axis chord carries only its bending tension, which
    # the biaxial bending check already covers -- no separate chord check.
    at = _fresh(); at.run()
    _mvt(at, my=100.0, torsion=False)
    links = at.session_state["results"]["shear"]["links"]
    assert links["chord_off"] is None
    # The shear-plane chord itself is still conditional and biaxial-aware
    # (without torsion there is no combined "longitudinal" payload).
    ch = links["chord"]
    assert ch["biaxial"] and not ch["has_torsion"] and ch["conditional"]


def test_app_zero_capacity_chord_does_not_poison_the_scan():
    # An off-axis moment beyond the envelope leaves zero conditional capacity:
    # the chord reports utilisation = inf (honest), but is kept OUT of the
    # strut-angle objective so the other checks still pick a sensible angle.
    at = _fresh(); at.run()
    _mvt(at)
    my_max = at.session_state["results"]["plastic"]["max_my"]
    at.number_input(key="pl_My").set_value(float(my_max) * 1.5).run()
    at.button(key="calculate").click().run()
    assert not at.exception
    res = at.session_state["results"]
    lg = res["combined"]["longitudinal"]
    assert lg["conditional"] and lg["m_rd"] == 0.0
    assert math.isinf(lg["util"])
    lk = res["shear"]["links"]["res"]
    assert lk["valid"] and math.isfinite(lk["cot"])   # the scan still worked
    assert 1.0 <= lk["cot"] <= 2.5


def test_app_off_axis_chord_skipped_on_subdivided_section():
    # Compound section: the torsion steel is per sub-tube, so the off-axis chord
    # is not evaluated -- the payload says why, and no off-chord is reported.
    at = _fresh(); at.run()
    at.checkbox(key="torsion_subdivide").set_value(True).run()
    _mvt(at, my=100.0)
    t = at.session_state["results"]["torsion"]
    assert t["subdivided"]
    lg = at.session_state["results"]["combined"]["longitudinal"]
    assert lg["off_not_evaluated"] == "subdivided"
    assert at.session_state["results"]["shear"]["links"]["chord_off"] is None
