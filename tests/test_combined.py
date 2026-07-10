"""Tests for the combined bending + shear + torsion (M-V-T) interaction checks."""

from __future__ import annotations

import math
import pathlib
import sys

import pytest

from sector import codes, combined

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
APP = str(ROOT / "app" / "sector_app.py")


# -- engine -----------------------------------------------------------------

def test_ratio_helper():
    assert combined.ratio(1.0, 2.0) == pytest.approx(0.5)
    assert combined.ratio(0.0, 0.0) == 0.0
    assert math.isinf(combined.ratio(1.0, 0.0))


def test_crushing_interaction():
    assert combined.crushing_interaction(40.0, 80.0, 150.0, 600.0) == pytest.approx(0.75)
    assert math.isinf(combined.crushing_interaction(1.0, 0.0, 0.0, 1.0))


def test_dkna_sum_summed_vs_independent():
    assert combined.dkna_sum(0.3, 0.4, 0.2, m_v_independent=False) == pytest.approx(0.9)
    # independent -> max(M+T, V+T) = max(0.5, 0.6) = 0.6
    assert combined.dkna_sum(0.3, 0.4, 0.2, m_v_independent=True) == pytest.approx(0.6)


def test_longitudinal_check_uncapped():
    # No cap needed (bending + shear stays well below MRd): a straight sum.
    #   mv = min(50*0.5, 400-100) = 25; mt = 30*0.5/2 = 7.5; total = 132.5
    r = combined.longitudinal_check(100.0, 400.0, 50.0, 30.0, 0.5)
    assert r["mv"] == pytest.approx(25.0)
    assert r["mt"] == pytest.approx(7.5)          # torsion distributed -> z/2
    assert r["m_total"] == pytest.approx(132.5)
    assert r["util"] == pytest.approx(132.5 / 400.0)
    assert not r["capped"]
    assert r["ok"]


def test_longitudinal_check_shear_shift_capped():
    # The shear shift wants 200*0.5 = 100 kNm but 6.2.3(7) caps it at MRd - MEd = 20.
    r = combined.longitudinal_check(100.0, 120.0, 200.0, 0.0, 0.5)
    assert r["mv"] == pytest.approx(20.0)
    assert r["capped"]
    assert r["m_total"] == pytest.approx(120.0)   # exactly MRd -> util 1.0
    assert r["util"] == pytest.approx(1.0)


def test_longitudinal_check_torsion_uses_half_lever_and_no_cap():
    # Torsion is not subject to the shear cap and acts on z/2 (distributed steel).
    r = combined.longitudinal_check(50.0, 300.0, 0.0, 80.0, 0.6)
    assert r["mv"] == 0.0
    assert r["mt"] == pytest.approx(80.0 * 0.6 / 2.0)
    assert not r["capped"]
    assert r["m_total"] == pytest.approx(74.0)


def test_chord_moment_and_capacity_low_face_agrees_with_moment():
    # Common case: shear tension on the low face, sagging moment tensions it too.
    m_ed, m_rd = combined.chord_moment_and_capacity(100.0, True, 400.0, -300.0)
    assert m_ed == pytest.approx(100.0)
    assert m_rd == pytest.approx(400.0)          # low-face (max) capacity


def test_chord_moment_and_capacity_high_face_uses_high_capacity():
    # Codex's scenario: shear tension on the HIGH face (top/right) but the applied
    # moment is sagging (tensions the LOW face). The moment relieves the high chord, so
    # its contribution floors at 0, and the capacity is the HIGH-face (|min|) value --
    # NOT the larger low-face max, which would understate utilisation on asymmetric steel.
    m_ed, m_rd = combined.chord_moment_and_capacity(100.0, False, 400.0, -300.0)
    assert m_ed == 0.0                           # relief not credited
    assert m_rd == pytest.approx(300.0)          # high-face capacity, not 400


def test_chord_moment_and_capacity_high_face_hogging_adds():
    # High face with a hogging moment that genuinely tensions it -> full contribution.
    m_ed, m_rd = combined.chord_moment_and_capacity(-100.0, False, 400.0, -300.0)
    assert m_ed == pytest.approx(100.0)
    assert m_rd == pytest.approx(300.0)


def test_chord_moment_and_capacity_symmetric():
    m_ed, m_rd = combined.chord_moment_and_capacity(50.0, True, 250.0, -250.0)
    assert (m_ed, m_rd) == (pytest.approx(50.0), pytest.approx(250.0))


def test_longitudinal_check_zero_capacity_is_inf():
    r = combined.longitudinal_check(10.0, 0.0, 5.0, 5.0, 0.5)
    assert math.isinf(r["util"])
    assert not r["ok"]


def test_combined_strut_theta():
    # Crossover cot^2 = s/c - 1.
    assert combined.combined_strut_theta(5.0, 1.0, 1.0, 2.5) == pytest.approx(2.0)
    assert combined.combined_strut_theta(50.0, 1.0, 1.0, 2.5) == 2.5   # clamp to max
    assert combined.combined_strut_theta(1.0, 5.0, 1.0, 2.5) == 1.0    # floor at 1
    assert combined.combined_strut_theta(0.0, 1.0, 1.0, 2.5) == 1.0    # no stirrups
    assert combined.combined_strut_theta(5.0, 0.0, 1.0, 2.5) == 2.5    # no crushing
    # A user band wholly below 1 (a warned override) is respected, not forced up to 1.
    assert combined.combined_strut_theta(50.0, 1.0, 0.5, 0.8) == pytest.approx(0.8)
    assert combined.combined_strut_theta(0.0, 1.0, 0.5, 0.8) == pytest.approx(0.8)


# -- app integration (AppTest) ----------------------------------------------

def _fresh():
    from streamlit.testing.v1 import AppTest
    return AppTest.from_file(APP, default_timeout=90)


def _enable_all(at, mv_independent=False):
    at.number_input(key="pl_Mx").set_value(100.0).run()
    at.checkbox(key="shear_on").set_value(True).run()
    at.checkbox(key="shear_links").set_value(True).run()
    at.number_input(key="shear_V").set_value(150.0).run()
    at.checkbox(key="torsion_on").set_value(True).run()
    at.number_input(key="torsion_T").set_value(40.0).run()
    at.checkbox(key="combined_on").set_value(True).run()
    if mv_independent:
        at.checkbox(key="combined_mv_independent").set_value(True).run()
    at.button(key="calculate").click().run()
    return at


def test_app_combined_assembles_all_three():
    at = _fresh()
    at.run()
    _enable_all(at)
    assert not at.exception
    c = at.session_state["results"]["combined"]
    assert c["valid"]
    assert c["dkna_sum"] == pytest.approx(c["r_m"] + c["r_v"] + c["r_t"])
    assert c["crushing"] is not None            # shear links present -> crushing check
    assert c["asl_torsion"] > 0.0


def test_app_combined_longitudinal_check():
    at = _fresh()
    at.run()
    _enable_all(at)
    c = at.session_state["results"]["combined"]
    lg = c["longitudinal"]                       # links are on, so the check is present
    assert lg["valid"]
    assert lg["axis"] in ("x", "y")
    # MEd,total is the applied moment plus the (non-negative) shear + torsion moments.
    assert lg["m_total"] == pytest.approx(lg["m_ed"] + lg["mv"] + lg["mt"])
    assert lg["mt"] > 0.0                         # torsion is acting
    assert lg["util"] == pytest.approx(lg["m_total"] / lg["m_rd"])
    assert math.isfinite(lg["util"])
    assert not lg["biaxial"]                       # default My_pl = 0 -> uniaxial
    assert lg["off_util"] == pytest.approx(0.0)


def test_app_combined_longitudinal_biaxial_flagged():
    at = _fresh()
    at.run()
    _enable_all(at)                                # uniaxial first (My_pl = 0)
    at.number_input(key="pl_My").set_value(100.0).run()   # add an off-axis moment
    at.button(key="calculate").click().run()
    lg = at.session_state["results"]["combined"]["longitudinal"]
    assert lg["biaxial"]                           # off-axis moment now non-negligible
    assert lg["off_util"] > 0.05


def test_app_combined_mv_independent_uses_max():
    at = _fresh()
    at.run()
    _enable_all(at, mv_independent=True)
    c = at.session_state["results"]["combined"]
    assert c["dkna_sum"] == pytest.approx(max(c["r_m"] + c["r_t"], c["r_v"] + c["r_t"]))


def test_app_combined_edition_lock():
    at = _fresh()
    at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    at.checkbox(key="torsion_on").set_value(True).run()
    at.checkbox(key="combined_on").set_value(True).run()
    at.selectbox(key="combined_method").set_value(codes.EC2_2005.label).run()
    at.button(key="calculate").click().run()
    assert not at.exception
    res = at.session_state["results"]
    # both checks follow the shared edition, and their own selectors are locked.
    assert res["shear"]["method"] == codes.EC2_2005.label
    assert res["torsion"]["method"] == codes.EC2_2005.label
    assert at.selectbox(key="shear_method").disabled
    assert at.selectbox(key="torsion_method").disabled


def test_app_combined_incomplete_flags_missing():
    at = _fresh()
    at.run()
    at.checkbox(key="combined_on").set_value(True).run()   # no shear / torsion
    at.button(key="calculate").click().run()
    assert not at.exception
    assert not at.session_state["results"]["combined"]["valid"]
    at.selectbox(key="view").set_value("M-V-T Combined").run()
    assert any("needs all three" in w.value for w in at.warning)


def test_app_combined_view_renders():
    at = _fresh()
    at.run()
    _enable_all(at)
    at.selectbox(key="view").set_value("M-V-T Combined").run()
    assert not at.exception
    labels = [m.label for m in at.metric]
    assert any("Bending" in lbl for lbl in labels)
    assert any("SEd/SRd" in lbl for lbl in labels)
    # The shared-stirrup transverse check reports steel demand and crushing
    # separately, and the OK/Over verdict rides a mechanism-labelled metric so a
    # crushing-controlled angle is never mislabelled as stirrup demand (Codex).
    assert any("Stirrup utilisation" in lbl for lbl in labels)
    assert any("Crushing utilisation" in lbl for lbl in labels)
    assert any(lbl.startswith("Governing (") for lbl in labels)


def test_app_combined_transverse_shear_credit():
    # VEd <= VRd,c: the concrete carries the shear, so the shared stirrup's shear
    # share is 0 and the whole stirrup serves torsion (Q2).
    at = _fresh()
    at.run()
    at.number_input(key="pl_Mx").set_value(100.0).run()
    at.checkbox(key="shear_on").set_value(True).run()
    at.checkbox(key="shear_links").set_value(True).run()
    at.number_input(key="shear_V").set_value(10.0).run()      # well below VRd,c
    at.checkbox(key="torsion_on").set_value(True).run()
    at.number_input(key="torsion_T").set_value(40.0).run()
    at.checkbox(key="combined_on").set_value(True).run()
    at.button(key="calculate").click().run()
    assert not at.exception
    tr = at.session_state["results"]["combined"]["transverse"]
    assert tr["shear_credited"] is True
    assert tr["shear_fraction"] == pytest.approx(0.0)
    assert tr["torsion_fraction"] > 0.0
    assert tr["governing"] == pytest.approx(tr["torsion_fraction"], rel=1e-6)
    # governing = max(stirrup, crushing); the label follows whichever controls.
    assert tr["governing"] == pytest.approx(max(tr["u_stirrup"], tr["u_crush"]))
    assert tr["governs"] == ("crushing" if tr["u_crush"] > tr["u_stirrup"]
                             else "stirrups")


def test_app_combined_transverse_no_credit_when_shear_high():
    # VEd > VRd,c: the stirrup carries both, so the shear share is > 0 and adds.
    at = _fresh()
    at.run()
    at.number_input(key="pl_Mx").set_value(100.0).run()
    at.checkbox(key="shear_on").set_value(True).run()
    at.checkbox(key="shear_links").set_value(True).run()
    at.number_input(key="shear_V").set_value(300.0).run()     # above VRd,c
    at.checkbox(key="torsion_on").set_value(True).run()
    at.number_input(key="torsion_T").set_value(40.0).run()
    at.checkbox(key="combined_on").set_value(True).run()
    at.button(key="calculate").click().run()
    assert not at.exception
    tr = at.session_state["results"]["combined"]["transverse"]
    assert tr["shear_credited"] is False
    assert tr["shear_fraction"] > 0.0


def test_app_combined_non_overlapping_cot_bands_are_rejected():
    # Codex: when the shear and torsion strut-angle bands do not overlap there is no
    # common angle, so the crushing and shared-stirrup checks are flagged invalid.
    at = _fresh()
    at.run()
    at.number_input(key="pl_Mx").set_value(100.0).run()
    at.checkbox(key="shear_on").set_value(True).run()
    at.checkbox(key="shear_links").set_value(True).run()
    at.number_input(key="shear_V").set_value(100.0).run()
    at.number_input(key="shear_cot_min").set_value(2.0).run()
    at.number_input(key="shear_cot_max").set_value(2.5).run()
    at.checkbox(key="torsion_on").set_value(True).run()
    at.number_input(key="torsion_T").set_value(40.0).run()
    at.number_input(key="torsion_cot_min").set_value(0.5).run()
    at.number_input(key="torsion_cot_max").set_value(1.5).run()
    at.checkbox(key="combined_on").set_value(True).run()
    at.button(key="calculate").click().run()
    assert not at.exception
    c = at.session_state["results"]["combined"]
    assert c["transverse"]["valid"] is False
    assert c["crushing"]["valid"] is False
    at.selectbox(key="view").set_value("M-V-T Combined").run()
    assert any("do not overlap" in w.value for w in at.warning)


def test_app_combined_is_saved_and_restored():
    import project_io
    at = _fresh()
    at.run()
    at.checkbox(key="combined_on").set_value(True).run()
    at.selectbox(key="combined_method").set_value(codes.EC2_2005.label).run()
    scalars = {k: at.session_state[k] for k in project_io.SCALAR_KEYS
               if k in at.session_state}
    assert scalars["combined_on"] is True
    at2 = _fresh()
    at2.run()
    at2.session_state["_pending_project"] = project_io.dump_project({}, scalars)
    at2.run()
    assert not at2.exception
    assert at2.session_state["combined_on"] is True
    assert at2.session_state["combined_method"] == codes.EC2_2005.label
