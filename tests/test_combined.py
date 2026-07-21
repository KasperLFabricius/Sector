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

from app_case_inputs import apply_case_changes  # noqa: E402


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


def test_longitudinal_check_zero_capacity_shear_only_is_inf_not_zero():
    # The subtle case: zero conditional capacity, no applied moment on the chord
    # (m_ed = 0, the moment compresses this face) and no torsion, but a real shear
    # shift. The 6.2.3(7) cap max(m_rd - m_ed, 0) = 0 would zero the shift and read
    # 0% OK; the guard makes the UNCAPPED shift fail the zero-capacity chord.
    r = combined.longitudinal_check(0.0, 0.0, ftd_v=200.0, ftd_t=0.0, z=0.5)
    assert math.isinf(r["util"]) and not r["ok"]
    assert r["mv"] == pytest.approx(100.0)          # the real shear shift is shown
    # Genuinely no demand at all -> still zero / OK (not a spurious fail).
    r0 = combined.longitudinal_check(0.0, 0.0, ftd_v=0.0, ftd_t=0.0, z=0.5)
    assert r0["util"] == 0.0 and r0["ok"]


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


def _goto_page(at, page):
    try:
        current = at.session_state["_main_page"]
    except KeyError:
        current = None
    if current != page:
        at.segmented_control(key="_main_page").set_value(page).run()
    return at


def _calculate(at):
    _goto_page(at, "Analysis")
    at.button(key="calculate").click().run()
    return at


def _select_view(at, value):
    _goto_page(at, "Analysis")
    at.selectbox(key="view").set_value(value).run()
    return at


def _set(at, *changes):
    """Stage already-rendered widget changes and perform one Streamlit rerun."""
    changes, case_changed = apply_case_changes(at, changes)
    if case_changed:
        _goto_page(at, "Inputs")
    if changes:
        widget_type, key, _value = changes[0]
        try:
            getattr(at, widget_type)(key=key)
        except KeyError:
            _goto_page(at, "Analysis" if key == "view" else "Inputs")
    for widget_type, key, value in changes:
        getattr(at, widget_type)(key=key).set_value(value)
    return at.run()


def _set_and_click(at, button_key, *changes):
    """Submit inputs, navigate if needed, then click the page-local action."""
    if button_key == "calculate" and changes:
        _set(at, *changes)
        changes = ()
    for widget_type, key, value in changes:
        getattr(at, widget_type)(key=key).set_value(value)
    if button_key == "calculate":
        _goto_page(at, "Analysis")
    at.button(key=button_key).click()
    return at.run()


def _enable_all(at, mv_independent=False):
    _set(
        at,
        ("number_input", "pl_Mx", 100.0),
        ("checkbox", "shear_on", True),
        ("checkbox", "torsion_on", True),
        ("checkbox", "combined_on", True),
    )
    second = [
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 150.0),
        ("number_input", "torsion_T", 40.0),
    ]
    if mv_independent:
        second.append(("checkbox", "combined_mv_independent", True))
    _set_and_click(at, "calculate", *second)
    return at


def _run_member(
    at,
    *,
    mx=0.0,
    p=0.0,
    v=0.0,
    t=0.0,
    combined_on=True,
    shear_band=None,
    torsion_band=None,
):
    """Configure a complete M-V-T member with only the reruns needed for reveals."""
    _goto_page(at, "Inputs")
    # Once a shared AppTest has revealed every conditional member input, later load
    # cases can update all values and calculate in one rerun. This keeps repeated
    # engineering comparisons independent at result level without rebuilding the
    # same Streamlit controls two extra times per case.
    ready = (
        at.checkbox(key="shear_on").value
        and at.checkbox(key="torsion_on").value
        and at.checkbox(key="shear_links").value
    )
    if ready:
        changes = [
            ("number_input", "pl_Mx", mx),
            ("number_input", "pl_P", p),
            ("checkbox", "combined_on", combined_on),
            ("number_input", "shear_V", v),
            ("number_input", "torsion_T", t),
        ]
        if shear_band is not None:
            changes.extend([
                ("number_input", "shear_cot_min", shear_band[0]),
                ("number_input", "shear_cot_max", shear_band[1]),
            ])
        if torsion_band is not None:
            changes.extend([
                ("number_input", "torsion_cot_min", torsion_band[0]),
                ("number_input", "torsion_cot_max", torsion_band[1]),
            ])
        _set_and_click(at, "calculate", *changes)
        return at

    _set(
        at,
        ("number_input", "pl_Mx", mx),
        ("number_input", "pl_P", p),
        ("checkbox", "shear_on", True),
        ("checkbox", "torsion_on", True),
        ("checkbox", "combined_on", combined_on),
    )
    active = [
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", v),
        ("number_input", "torsion_T", t),
    ]
    if shear_band is None and torsion_band is None:
        _set_and_click(at, "calculate", *active)
        return at
    _set(at, *active)
    bands = []
    if shear_band is not None:
        bands.extend([
            ("number_input", "shear_cot_min", shear_band[0]),
            ("number_input", "shear_cot_max", shear_band[1]),
        ])
    if torsion_band is not None:
        bands.extend([
            ("number_input", "torsion_cot_min", torsion_band[0]),
            ("number_input", "torsion_cot_max", torsion_band[1]),
        ])
    _set_and_click(at, "calculate", *bands)
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
    _set_and_click(
        at, "calculate", ("number_input", "pl_My", 100.0)
    )  # add an off-axis moment
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
    _set(
        at,
        ("checkbox", "shear_on", True),
        ("checkbox", "torsion_on", True),
        ("checkbox", "combined_on", True),
    )
    _set_and_click(
        at,
        "calculate",
        ("selectbox", "combined_method", codes.EC2_2005.label),
        ("number_input", "shear_V", 150.0),
        ("number_input", "torsion_T", 40.0),
    )
    assert not at.exception
    res = at.session_state["results"]
    # both checks follow the shared edition, and their own selectors are locked.
    assert res["shear"]["method"] == codes.EC2_2005.label
    assert res["torsion"]["method"] == codes.EC2_2005.label
    _goto_page(at, "Inputs")
    assert at.selectbox(key="shear_method").disabled
    assert at.selectbox(key="torsion_method").disabled


def test_app_combined_incomplete_flags_missing():
    at = _fresh()
    at.run()
    _set_and_click(
        at, "calculate", ("checkbox", "combined_on", True)
    )  # no shear / torsion
    assert not at.exception
    assert "combined" not in at.session_state["results"]
    _select_view(at, "M-V-T Combined")
    assert any("VEd and TEd are zero" in item.value for item in at.info)


def test_app_combined_view_renders():
    at = _fresh()
    at.run()
    _enable_all(at)
    _select_view(at, "M-V-T Combined")
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


def test_app_combined_out_of_range_withholds_dependent_verdicts():
    at = _fresh()
    at.run()
    at.number_input(key="shear_cot_max").set_value(3.0).run()
    _enable_all(at)
    assert not at.exception
    c = at.session_state["results"]["combined"]
    assert c["code_applicable"] is False
    assert c["crushing"]["code_applicable"] is False
    assert c["longitudinal"]["code_applicable"] is False
    _select_view(at, "M-V-T Combined")
    assert any("NO CODE VERDICT" in w.value for w in at.warning)
    verdict_labels = (
        chr(0x03A3) + "(SEd/SRd)", "Sum", "MEd,total/MRd",
    )
    verdict_metrics = [
        m for m in at.metric
        if m.label in verdict_labels or m.label.startswith("Governing (")
    ]
    assert verdict_metrics
    assert all(not metric.delta for metric in verdict_metrics)


def test_app_strut_angle_responds_to_loads():
    # The user-reported defect: the auto strut angle sat at cot = 2.5 regardless of
    # VEd/MEd/NEd because it maximised the shear RESISTANCE alone. The member angle
    # now minimises the governing utilisation, so it must respond to the loads.
    at = _fresh()
    at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    at.checkbox(key="shear_links").set_value(True).run()

    def run(v, mx, p):
        _set_and_click(
            at,
            "calculate",
            ("number_input", "shear_V", v),
            ("number_input", "pl_Mx", mx),
            ("number_input", "pl_P", p),
        )
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
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 150.0),
        ("number_input", "pl_Mx", 100.0),
    )
    ch = at.session_state["results"]["shear"]["links"]["chord"]
    assert ch is not None and ch["valid"]
    assert ch["mt"] == pytest.approx(0.0)            # no torsion contribution
    assert ch["m_total"] == pytest.approx(ch["m_ed"] + ch["mv"])
    assert not ch["has_torsion"]
    # Capacity-only run (utilisation check off): no chord; the scan over the shear
    # utils alone reproduces the resistance-maximising angle (2.5 here).
    _set_and_click(
        at, "calculate", ("checkbox", "pl_check_util", False)
    )
    lk = at.session_state["results"]["shear"]["links"]
    assert lk["chord"] is None
    assert lk["res"]["cot"] == pytest.approx(2.5)
    # A zero action is not evaluated for that load case.
    _set_and_click(at, "calculate", ("number_input", "shear_V", 0.0))
    assert "shear" not in at.session_state["results"]
    _select_view(at, "Shear")
    assert any("VEd = 0" in item.value for item in at.info)


def test_app_invalid_tube_does_not_poison_the_member_angle():
    # Workflow finding: an INVALID torsion tube (util = inf at every angle) must not
    # constrain the member angle -- previously it tied the scan and pinned the links
    # at band-low, flipping a passing shear check to FAIL.
    at = _fresh()
    at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 500.0),
    )
    base = at.session_state["results"]["shear"]["links"]
    assert base["res"]["cot"] == pytest.approx(2.5) and base["util"] < 1.0
    _set(at, ("checkbox", "torsion_on", True))
    _set_and_click(
        at,
        "calculate",
        ("number_input", "torsion_T", 40.0),
        ("number_input", "torsion_tef", 400.0),
    )  # tef > section: invalid
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
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 500.0),
        ("number_input", "pl_Mx", 430.0),
    )  # ~0.97 MRd
    lk = at.session_state["results"]["shear"]["links"]
    assert lk["res"]["cot"] == pytest.approx(2.5, abs=0.05)
    assert lk["util"] < 1.0                                      # stirrups still pass
    assert lk["chord"]["capped"]                                 # cap is active


def test_app_zero_torsion_does_not_constrain_the_shear_band():
    # A zero torsion action is skipped and therefore cannot constrain shear.
    at = _fresh()
    at.run()
    _run_member(
        at,
        v=500.0,
        t=0.0,
        combined_on=False,
        torsion_band=(1.0, 1.2),
    )
    r = at.session_state["results"]
    lk = r["shear"]["links"]
    assert lk["res"]["cot"] == pytest.approx(2.5)                # shear band governs
    assert "torsion" not in r


def test_app_dead_shear_companion_stays_in_its_own_band():
    # Mirror of the T=0 case: zero shear is skipped while torsion remains live.
    at = _fresh()
    at.run()
    _run_member(
        at,
        mx=80.0,
        v=0.0,
        t=40.0,
        combined_on=False,
        shear_band=(2.3, 2.5),
        torsion_band=(1.0, 1.2),
    )
    r = at.session_state["results"]
    assert "shear" not in r
    assert 1.0 - 1e-9 <= r["torsion"]["cot"] <= 1.2 + 1e-9


def test_app_infinite_bending_util_does_not_poison_the_member_angle():
    # Workflow finding: an INFINITE plastic (bending) utilisation -- the applied N/M
    # ray misses the plastic M-M envelope -- must not poison the strut-angle objective
    # via the constant DK NA term. Guard mirrors the invalid-tube inf guard: with an
    # inf r_m the member angle is chosen by the FINITE terms exactly as if the combined
    # check were off, instead of being pinned to the band edge by the inf.
    def run(combined):
        at = _fresh()
        at.run()
        _run_member(
            at,
            mx=120.0,
            p=8000.0,
            v=300.0,
            t=60.0,
            combined_on=combined,
        )
        return at.session_state["results"]
    r_on = run(True)
    r_off = run(False)
    assert not math.isfinite(r_on["plastic"]["util"])            # inf bending util
    assert not math.isfinite(r_on["combined"]["dkna_sum"])       # verdict still FAIL
    cot_on = r_on["shear"]["links"]["res"]["cot"]
    cot_off = r_off["shear"]["links"]["res"]["cot"]
    assert cot_on == pytest.approx(cot_off)                      # inf did not move the angle
    assert cot_on > 1.05                                          # NOT pinned to the band edge


def test_app_combined_angle_minimises_the_dkna_governing_sum():
    # v0.69 requirement: theta minimises the LARGEST applicable utilisation. In a
    # combined M+V+T run the governing utilisation is the DK NA sum(SEd/SRd) (a sum of
    # ratios, so >= every component), which has a load-dependent INTERIOR optimum.
    # Pin the strut to fixed cots across the band and confirm the auto-selected angle
    # beats every one of them -- i.e. the chosen cot actually minimises the governing
    # combined utilisation, not just some component. A regression that drops the DK NA
    # objective term would move theta off this minimum and this test would catch it.
    at = _fresh()
    at.run()

    def dkna(pin=None):
        band = (pin, pin) if pin is not None else None
        _run_member(
            at,
            mx=150.0,
            v=280.0,
            t=100.0,
            shear_band=band,
            torsion_band=band,
        )
        r = at.session_state["results"]
        return r["shear"]["links"]["res"]["cot"], r["combined"]["dkna_sum"]
    cot_star, dk_star = dkna()
    # A load-dependent interior optimum, NOT the pre-v0.69 clamp to the band edge.
    assert 1.8 < cot_star < 2.4
    # It beats every fixed strut angle across the band, including the resistance-max
    # edge cot = 2.5 that the old code always returned.
    for pin in (1.0, 1.6, 2.0, 2.4, 2.5):
        _, dk_pin = dkna(pin=pin)
        assert dk_star < dk_pin, f"cot*={cot_star} dkna*={dk_star} !< pin {pin}: {dk_pin}"


def test_app_combined_is_skipped_when_shear_is_zero():
    # VEd = 0 disables the shear and dependent combined checks for this case.
    at = _fresh()
    at.run()
    _run_member(
        at,
        mx=90.0,
        v=0.0,
        t=60.0,
        shear_band=(2.3, 2.5),
        torsion_band=(1.0, 1.4),
    )
    r = at.session_state["results"]
    assert "shear" not in r
    assert "combined" not in r
    assert "torsion" in r


def test_app_no_transverse_load_skips_capacity_and_combined_checks():
    # VEd = TEd = 0 means neither transverse check is evaluated for this case.
    at = _fresh()
    at.run()
    _run_member(at, mx=100.0, v=0.0, t=0.0)
    r = at.session_state["results"]
    assert "shear" not in r
    assert "torsion" not in r
    assert "combined" not in r
    _select_view(at, "M-V-T Combined")
    assert any("VEd and TEd are zero" in item.value for item in at.info)


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
    _run_member(at, mx=100.0, v=10.0, t=40.0)  # V well below VRd,c
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
    _run_member(at, mx=100.0, v=300.0, t=40.0)  # V above VRd,c
    assert not at.exception
    tr = at.session_state["results"]["combined"]["transverse"]
    assert tr["shear_credited"] is False
    assert tr["shear_fraction"] > 0.0


def test_app_combined_non_overlapping_cot_bands_are_rejected():
    # Codex: when the shear and torsion strut-angle bands do not overlap there is no
    # common angle, so the crushing and shared-stirrup checks are flagged invalid.
    at = _fresh()
    at.run()
    _run_member(
        at,
        mx=100.0,
        v=100.0,
        t=40.0,
        shear_band=(2.0, 2.5),
        torsion_band=(0.5, 1.5),
    )
    assert not at.exception
    c = at.session_state["results"]["combined"]
    assert c["transverse"]["valid"] is False
    assert c["crushing"]["valid"] is False
    # Disjoint bands fall back to each action's own resistance angle, so the chord
    # captions must NOT claim a shared minimising angle (theta_mode drives that).
    assert at.session_state["results"]["shear"]["links"]["theta_mode"] == "disjoint"
    assert c["longitudinal"]["theta_mode"] == "disjoint"
    # The chord note is actually rendered in this state, so the report wording matters.
    assert c["longitudinal"]["valid"] is True
    _select_view(at, "M-V-T Combined")
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
