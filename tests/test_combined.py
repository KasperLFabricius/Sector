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


def test_chord_applied_moment_low_face_adds():
    # Common case: shear tension on the low face, a sagging moment tensions it too.
    assert combined.chord_applied_moment(100.0, True) == pytest.approx(100.0)


def test_chord_applied_moment_high_face_relief_floors_to_zero():
    # Codex's scenario: shear tension on the HIGH face but the applied moment is sagging
    # (tensions the LOW face), so it relieves the high chord -> contribution floors at 0
    # (the high chord must still carry the shear + torsion tension on its own).
    assert combined.chord_applied_moment(100.0, False) == 0.0


def test_chord_applied_moment_high_face_hogging_adds():
    # High face with a hogging moment that genuinely tensions it -> full contribution.
    assert combined.chord_applied_moment(-100.0, False) == pytest.approx(100.0)


def test_chord_applied_moment_low_face_hogging_relief():
    assert combined.chord_applied_moment(-80.0, True) == 0.0


def test_longitudinal_check_zero_capacity_is_inf():
    r = combined.longitudinal_check(10.0, 0.0, 5.0, 5.0, 0.5)
    assert math.isinf(r["util"])
    assert not r["ok"]


def test_governing_strut_cot_balances_falling_and_rising_utils():
    # U_stirrup = 4/cot falls, U_chord = 1.0*cot rises: max is minimised at their
    # crossing cot = 2 (util 2.0); the scan must land there (within its resolution).
    cot, gov = combined.governing_strut_cot(
        [lambda c: 4.0 / c, lambda c: 1.0 * c], 1.0, 2.5)
    assert cot == pytest.approx(2.0, abs=2e-3)
    assert gov == pytest.approx(2.0, abs=2e-3)


def test_governing_strut_cot_clamps_to_band():
    # A falling util alone -> the flattest allowed strut (the old resistance-max).
    cot, _ = combined.governing_strut_cot([lambda c: 1.0 / c], 1.0, 2.5)
    assert cot == pytest.approx(2.5)
    # A rising util alone -> the steepest allowed strut.
    cot, _ = combined.governing_strut_cot([lambda c: c], 1.0, 2.5)
    assert cot == pytest.approx(1.0)
    # Crossing outside the band clamps to the edge: 9/cot vs cot cross at 3 > 2.5.
    cot, _ = combined.governing_strut_cot([lambda c: 9.0 / c, lambda c: c], 1.0, 2.5)
    assert cot == pytest.approx(2.5)


def test_governing_strut_cot_flat_objective_prefers_lower_cot():
    # All-constant utilisations (no load): ties break to the steeper strut (less
    # longitudinal steel demand); empty utils return the band's low edge.
    cot, _ = combined.governing_strut_cot([lambda c: 0.5], 1.0, 2.5)
    assert cot == pytest.approx(1.0)
    cot, gov = combined.governing_strut_cot([], 1.0, 2.5)
    assert cot == pytest.approx(1.0) and gov == 0.0


def test_governing_strut_cot_reversed_band():
    cot, _ = combined.governing_strut_cot([lambda c: 1.0 / c], 2.5, 1.0)
    assert cot == pytest.approx(2.5)


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
    # MRd is the pure-axis chord capacity (shear-face angle solve), never above the
    # biaxial M-M sweep extremum about that axis (which can sit at a point with a
    # companion off-axis moment and overstate the uniaxial chord capacity).
    assert 0.0 < lg["m_rd"] <= at.session_state["results"]["plastic"]["max_mx"] + 1e-6


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


def test_app_strut_angle_responds_to_loads():
    # The user-reported defect: the auto strut angle sat at cot = 2.5 regardless of
    # VEd/MEd/NEd because it maximised the shear RESISTANCE alone. The member angle
    # now minimises the governing utilisation, so it must respond to the loads.
    at = _fresh()
    at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    at.checkbox(key="shear_links").set_value(True).run()

    def run(v, mx, p):
        at.number_input(key="shear_V").set_value(v).run()
        at.number_input(key="pl_Mx").set_value(mx).run()
        at.number_input(key="pl_P").set_value(p).run()
        at.button(key="calculate").click().run()
        assert not at.exception
        return at.session_state["results"]["shear"]["links"]

    # Pure shear: nothing trades against the stirrups -> flattest strut (as before).
    lk = run(500.0, 0.0, 0.0)
    assert lk["res"]["cot"] == pytest.approx(2.5)
    # Bending near MRd: the chord governs, the strut steepens to relieve delta_Ftd.
    lk = run(150.0, 400.0, 0.0)
    assert lk["res"]["cot"] < 1.2
    assert lk["chord"]["util"] > 0.9
    # Moderate bending: an interior optimum where stirrup and chord utils BALANCE.
    lk = run(150.0, 100.0, 0.0)
    assert 1.2 < lk["res"]["cot"] < 2.4
    assert lk["util"] == pytest.approx(lk["chord"]["util"], rel=0.02)
    # Axial compression raises MRd -> the chord relaxes and the angle flattens again.
    cot_n0 = lk["res"]["cot"]
    lk = run(150.0, 100.0, -800.0)
    assert lk["res"]["cot"] > cot_n0


def test_app_chord_check_in_shear_payload_without_torsion():
    # The longitudinal chord check (B1) is now available for V + M without torsion
    # (torsion term = 0) and shown from the shear links payload.
    at = _fresh()
    at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    at.checkbox(key="shear_links").set_value(True).run()
    at.number_input(key="shear_V").set_value(150.0).run()
    at.number_input(key="pl_Mx").set_value(100.0).run()
    at.button(key="calculate").click().run()
    ch = at.session_state["results"]["shear"]["links"]["chord"]
    assert ch is not None and ch["valid"]
    assert ch["mt"] == pytest.approx(0.0)            # no torsion contribution
    assert ch["m_total"] == pytest.approx(ch["m_ed"] + ch["mv"])
    assert not ch["has_torsion"]
    # Capacity-only run (utilisation check off): no chord; the scan over the shear
    # utils alone reproduces the resistance-maximising angle (2.5 here).
    at.checkbox(key="pl_check_util").set_value(False).run()
    at.button(key="calculate").click().run()
    lk = at.session_state["results"]["shear"]["links"]
    assert lk["chord"] is None
    assert lk["res"]["cot"] == pytest.approx(2.5)
    # With NO load at all there is no utilisation to scan -> legacy resistance mode.
    at.number_input(key="shear_V").set_value(0.0).run()
    at.button(key="calculate").click().run()
    lk = at.session_state["results"]["shear"]["links"]
    assert lk["theta_mode"] == "resistance"
    assert lk["res"]["cot"] == pytest.approx(2.5)


def test_app_invalid_tube_does_not_poison_the_member_angle():
    # Workflow finding: an INVALID torsion tube (util = inf at every angle) must not
    # constrain the member angle -- previously it tied the scan and pinned the links
    # at band-low, flipping a passing shear check to FAIL.
    at = _fresh()
    at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    at.checkbox(key="shear_links").set_value(True).run()
    at.number_input(key="shear_V").set_value(500.0).run()
    at.button(key="calculate").click().run()
    base = at.session_state["results"]["shear"]["links"]
    assert base["res"]["cot"] == pytest.approx(2.5) and base["util"] < 1.0
    at.checkbox(key="torsion_on").set_value(True).run()
    at.number_input(key="torsion_T").set_value(40.0).run()
    at.number_input(key="torsion_tef").set_value(400.0).run()   # tef > section: invalid
    at.button(key="calculate").click().run()
    r = at.session_state["results"]
    assert not r["torsion"]["valid"]                             # tube rejected
    lk = r["shear"]["links"]
    assert lk["res"]["cot"] == pytest.approx(2.5)                # angle unaffected
    assert lk["util"] == pytest.approx(base["util"])             # verdict unchanged


def test_app_objective_matches_reported_chord_cap():
    # Workflow finding: the objective must scan the SAME capped chord utilisation the
    # app reports. Here the cap saturates (MEd ~ MRd), so steepening cannot improve
    # the reported chord -- the angle must NOT sacrifice the stirrups (the old
    # uncapped objective dragged cot to 1.0 and failed them).
    at = _fresh()
    at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    at.checkbox(key="shear_links").set_value(True).run()
    at.number_input(key="shear_V").set_value(500.0).run()
    at.number_input(key="pl_Mx").set_value(430.0).run()          # ~0.97 MRd
    at.button(key="calculate").click().run()
    lk = at.session_state["results"]["shear"]["links"]
    assert lk["res"]["cot"] == pytest.approx(2.5, abs=0.05)
    assert lk["util"] < 1.0                                      # stirrups still pass
    assert lk["chord"]["capped"]                                 # cap is active


def test_app_zero_torsion_does_not_constrain_the_shear_band():
    # Workflow finding: a companion with ZERO load must not constrain the member
    # angle -- torsion enabled with TEd = 0 and a narrow torsion band previously
    # forced the shear angle into the intersection.
    at = _fresh()
    at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    at.checkbox(key="shear_links").set_value(True).run()
    at.number_input(key="shear_V").set_value(500.0).run()
    at.checkbox(key="torsion_on").set_value(True).run()
    at.number_input(key="torsion_T").set_value(0.0).run()        # enabled, no load
    at.number_input(key="torsion_cot_min").set_value(1.0).run()
    at.number_input(key="torsion_cot_max").set_value(1.2).run()  # narrow band
    at.button(key="calculate").click().run()
    lk = at.session_state["results"]["shear"]["links"]
    assert lk["res"]["cot"] == pytest.approx(2.5)                # shear band governs


def test_app_no_load_with_combined_keeps_resistance_mode():
    # Workflow finding: with V = 0 and T = 0 the constant DK NA term must not defeat
    # the documented no-load fallback (capacities at the resistance-max angles).
    at = _fresh()
    at.run()
    at.number_input(key="pl_Mx").set_value(100.0).run()
    at.checkbox(key="shear_on").set_value(True).run()
    at.checkbox(key="shear_links").set_value(True).run()
    at.number_input(key="shear_V").set_value(0.0).run()
    at.checkbox(key="torsion_on").set_value(True).run()
    at.number_input(key="torsion_T").set_value(0.0).run()
    at.checkbox(key="combined_on").set_value(True).run()
    at.button(key="calculate").click().run()
    lk = at.session_state["results"]["shear"]["links"]
    assert lk["theta_mode"] == "resistance"
    assert lk["res"]["cot"] == pytest.approx(2.5)


def test_app_combined_longitudinal_matches_shear_chord():
    # The combined view's longitudinal check and the shear view's chord check are the
    # SAME computation (one member angle) -- the payloads must agree.
    at = _fresh()
    at.run()
    _enable_all(at)
    r = at.session_state["results"]
    lg = r["combined"]["longitudinal"]
    ch = r["shear"]["links"]["chord"]
    assert lg["util"] == pytest.approx(ch["util"])
    assert lg["m_total"] == pytest.approx(ch["m_total"])


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
    # With the shear credited the stirrup serves torsion alone; the governing value
    # is still max(stirrup, crushing) AT THE MEMBER ANGLE, where the crushing sum
    # (6.29, no VRd,c credit) may control.
    assert tr["u_stirrup"] == pytest.approx(tr["torsion_fraction"], rel=1e-6)
    assert tr["governing"] == pytest.approx(max(tr["u_stirrup"], tr["u_crush"]))
    assert tr["governs"] == ("crushing" if tr["u_crush"] > tr["u_stirrup"]
                             else "stirrups")
    # One member strut angle: the transverse check sits at the links/torsion cot.
    r = at.session_state["results"]
    assert tr["cot"] == pytest.approx(r["shear"]["links"]["res"]["cot"])
    assert tr["cot"] == pytest.approx(r["torsion"]["cot"])


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
    # Disjoint bands fall back to each action's own resistance angle, so the chord
    # captions must NOT claim a shared minimising angle (theta_mode drives that).
    assert at.session_state["results"]["shear"]["links"]["theta_mode"] == "resistance"
    assert c["longitudinal"]["theta_mode"] == "resistance"
    at.selectbox(key="view").set_value("M-V-T Combined").run()
    assert any("do not overlap" in w.value for w in at.warning)
    caps = " ".join(cap.value for cap in at.caption)
    assert "bands do not overlap" in caps and "minimise the governing" not in caps


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
