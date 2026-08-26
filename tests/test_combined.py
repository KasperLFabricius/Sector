"""Tests for the combined bending + shear + torsion (M-V-T) interaction checks."""

from __future__ import annotations

import copy
import math
import pathlib
import sys

import numpy as np
import pytest

from sector import capacity, codes, combined

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
APP = str(ROOT / "app" / "sector_app.py")

from app_case_inputs import apply_widget_changes  # noqa: E402


# -- engine -----------------------------------------------------------------

def test_ratio_helper():
    assert combined.ratio(1.0, 2.0) == pytest.approx(0.5)
    assert combined.ratio(0.0, 0.0) == 0.0
    assert math.isinf(combined.ratio(1.0, 0.0))


def test_crushing_interaction():
    assert combined.crushing_interaction(40.0, 80.0, 150.0, 600.0) == pytest.approx(0.75)
    assert math.isinf(combined.crushing_interaction(1.0, 0.0, 0.0, 1.0))


def test_dkna_sum_summed_vs_independent():
    assert combined.dkna_sum(
        0.3, 0.4, 0.2, r_n=0.1, m_v_independent=False
    ) == pytest.approx(1.0)
    # independent -> N + max(M+T, V+T) = 0.1 + max(0.5, 0.6) = 0.7
    assert combined.dkna_sum(
        0.3, 0.4, 0.2, r_n=0.1, m_v_independent=True
    ) == pytest.approx(0.7)


def test_dkna_axial_term_is_not_folded_into_bending():
    result = combined.dkna_interaction_result(
        950.0,
        1000.0,
        0.0,
        None,
        5.0,
        100.0,
        5.0,
        100.0,
        m_v_independent=False,
    )
    assert result.valid
    assert result.r_n == pytest.approx(0.95)
    assert result.r_m == pytest.approx(0.0)
    assert result.utilisation == pytest.approx(1.05)
    assert result.ok is False


@pytest.mark.parametrize("n_ed", [-950.0, 950.0])
def test_dkna_retains_axial_sign_and_uses_matching_magnitude(n_ed):
    result = combined.dkna_interaction_result(
        n_ed,
        1000.0,
        0.0,
        None,
        0.0,
        None,
        0.0,
        None,
        m_v_independent=False,
    )
    assert result.valid
    assert result.n.demand == pytest.approx(n_ed)
    assert result.n.demand_abs == pytest.approx(950.0)
    assert result.r_n == pytest.approx(0.95)


def test_dkna_active_action_without_resistance_fails_closed():
    result = combined.dkna_interaction_result(
        0.0,
        None,
        10.0,
        None,
        0.0,
        None,
        0.0,
        None,
        m_v_independent=False,
    )
    assert not result.valid
    assert result.utilisation is None
    assert result.ok is None
    assert result.m.active and not result.m.valid
    assert "acting alone" in result.reason


def test_dkna_independent_route_keeps_n_and_t_in_both_checks():
    result = combined.dkna_interaction_result(
        20.0,
        100.0,
        30.0,
        100.0,
        40.0,
        100.0,
        10.0,
        100.0,
        m_v_independent=True,
    )
    assert result.n_m_plus_t == pytest.approx(0.6)
    assert result.n_v_plus_t == pytest.approx(0.7)
    assert result.utilisation == pytest.approx(0.7)
    assert result.governing_chord == "N+V+T"
    assert result.conditional is True
    assert result.limit_satisfied is True
    assert result.status == "CONDITIONAL"
    assert result.ok is None


def test_dkna_independent_route_over_limit_remains_conditional():
    result = combined.dkna_interaction_result(
        0.0,
        None,
        80.0,
        100.0,
        10.0,
        100.0,
        30.0,
        100.0,
        m_v_independent=True,
    )

    assert result.valid is True
    assert result.utilisation == pytest.approx(1.10)
    assert result.limit_satisfied is False
    assert result.conditional is True
    assert result.status == "CONDITIONAL"
    assert result.ok is None


def test_dkna_independent_route_with_incomplete_resistance_is_not_assessed():
    result = combined.dkna_interaction_result(
        0.0,
        None,
        10.0,
        None,
        0.0,
        None,
        0.0,
        None,
        m_v_independent=True,
    )

    assert result.valid is False
    assert result.conditional is True
    assert result.limit_satisfied is None
    assert result.status == "NOT ASSESSED"
    assert result.ok is None


def test_dkna_rejects_numpy_booleans_as_actions_or_route_selection():
    result = combined.dkna_interaction_result(
        np.bool_(True),
        100.0,
        0.0,
        None,
        0.0,
        None,
        0.0,
        None,
        m_v_independent=False,
    )
    assert not result.valid
    assert result.n.demand is None
    with pytest.raises(TypeError, match="must be a Boolean"):
        combined.dkna_sum(
            0.1, 0.2, 0.3, m_v_independent=np.bool_(True)
        )


def test_retained_combined_results_are_compact_and_reconstruct_scalars():
    crushing = combined.crushing_interaction_result(
        40.0, 80.0, 150.0, 600.0
    )
    assert crushing.torsion_ratio == pytest.approx(0.5)
    assert crushing.shear_ratio == pytest.approx(0.25)
    assert crushing.utilisation == pytest.approx(
        combined.crushing_interaction(40.0, 80.0, 150.0, 600.0)
    )
    dk = combined.dkna_interaction_result(
        0.1,
        1.0,
        0.3,
        1.0,
        0.4,
        1.0,
        0.2,
        1.0,
        m_v_independent=True,
    )
    assert dk.m_plus_t == pytest.approx(0.5)
    assert dk.v_plus_t == pytest.approx(0.6)
    assert dk.n_m_plus_t == pytest.approx(0.6)
    assert dk.n_v_plus_t == pytest.approx(0.7)
    assert dk.governing_chord == "N+V+T"
    assert dk.conditional is True
    assert dk.limit_satisfied is True
    assert dk.status == "CONDITIONAL"
    assert dk.ok is None
    assert dk.utilisation == pytest.approx(
        combined.dkna_sum(
            0.3, 0.4, 0.2, r_n=0.1, m_v_independent=True
        )
    )
    assert not hasattr(dk, "__dict__")
    with pytest.raises(AttributeError):
        dk.utilisation = 0.0


def test_retained_governing_strut_has_only_final_scan_certificate():
    functions = [lambda cot: 1.0 / cot, lambda cot: cot / 2.0]
    result = combined.governing_strut_result(functions, 1.0, 2.5, n=151)
    legacy_cot, legacy_util = combined.governing_strut_cot(
        functions, 1.0, 2.5, n=151
    )
    assert result.cot == pytest.approx(legacy_cot)
    assert result.utilisation == pytest.approx(legacy_util)
    assert result.samples == 151
    assert result.step == pytest.approx((2.5 - 1.0) / 150.0)
    assert result.selected_index == pytest.approx(
        (result.cot - 1.0) / result.step
    )
    assert result.objective_count == 2
    assert not hasattr(result, "candidates")
    assert not hasattr(result, "iterations")
    assert not hasattr(result, "history")


def test_empty_governing_strut_certificate_handles_zero_lower_bound():
    result = combined.governing_strut_result([], 0.0, 2.5, n=2)
    assert result.cot == 0.0
    assert result.theta_deg == pytest.approx(90.0)


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


def test_longitudinal_check_2023_shear_force_is_not_peak_moment_capped():
    # Sector does not establish the direct-support / concentrated-load condition
    # required for the favourable 2023 Formula (8.53) relief.
    r = combined.longitudinal_check(
        100.0,
        120.0,
        200.0,
        0.0,
        0.5,
        cap_shear_force=False,
    )
    assert r["mv"] == pytest.approx(100.0)
    assert not r["capped"]
    assert not r["cap_shear_force"]
    assert r["m_total"] == pytest.approx(200.0)
    assert r["util"] == pytest.approx(200.0 / 120.0)


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
    return apply_widget_changes(at, changes)


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


def test_biaxial_shear_with_torsion_keeps_two_screens_and_no_three_way_claim():
    at = _fresh()
    at.run()
    _set(
        at,
        ("number_input", "pl_Mx", 40.0),
        ("number_input", "pl_My", 30.0),
        ("checkbox", "shear_on", True),
        ("checkbox", "torsion_on", True),
        ("checkbox", "combined_on", True),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_Vx", 10.0),
        ("number_input", "shear_Vy", 12.0),
        ("number_input", "torsion_T", 5.0),
    )

    assert not at.exception
    results = at.session_state["results"]
    assert "generic_cross_direction_interaction_calculated" not in results["shear"]
    assert "status" not in results["shear"]
    assert "interaction_assessed" not in results["shear"]
    assert set(results["combined"]["directions"]) == {"vx", "vy"}
    assert "generic_cross_direction_interaction_calculated" not in results["combined"]
    assert "status" not in results["combined"]
    assert "interaction_status" not in results["combined"]
    assert set(results["torsion"]["directional_interactions"]) == {"vx", "vy"}
    for item in results["combined"]["directions"].values():
        assert item["governing_face"] in {"negative", "positive"}
        assert item["governing_cot"] is not None

    _select_view(at, "M-V-T Combined")
    assert not at.exception
    assert any(
        "generic simultaneous" in item.value.lower()
        and "not calculated" in item.value.lower()
        for item in at.info
    )
    table = next(
        frame.value for frame in at.dataframe
        if "Bending util." in frame.value.columns
    )
    assert "Governing face" in table.columns
    assert f"cot {chr(0x03B8)}" in table.columns


def test_biaxial_combined_keeps_directional_failure_without_aggregate_verdict():
    at = _fresh()
    at.run()
    _set(
        at,
        ("number_input", "pl_Mx", 1.0),
        ("number_input", "pl_My", 1.0),
        ("checkbox", "shear_on", True),
        ("checkbox", "torsion_on", True),
        ("checkbox", "combined_on", True),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_Vx", 1.0),
        ("number_input", "shear_Vy", 1.0),
        ("number_input", "torsion_T", 500.0),
    )

    assert not at.exception
    results = at.session_state["results"]
    assert all(
        direction["status"] == "PASS"
        for direction in results["shear"]["directions"].values()
    )
    combined = results["combined"]
    assert any(
        not direction["dkna_ok"]
        for direction in combined["directions"].values()
    )
    assert all(
        "status" not in direction and "governing_util" not in direction
        for direction in combined["directions"].values()
    )
    assert "generic_cross_direction_interaction_calculated" not in combined
    assert "status" not in combined
    assert "governing_component" not in combined


def test_biaxial_directional_vt_table_retains_out_of_default_range_verdicts():
    at = _fresh()
    at.run()
    _set(
        at,
        ("number_input", "pl_Mx", 20.0),
        ("number_input", "pl_My", 15.0),
        ("checkbox", "shear_on", True),
        ("checkbox", "torsion_on", True),
        ("checkbox", "combined_on", True),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "strut_cot_max", 3.0),
        ("number_input", "shear_Vx", 10.0),
        ("number_input", "shear_Vy", 12.0),
        ("number_input", "torsion_T", 5.0),
    )

    assert not at.exception
    interactions = at.session_state["results"]["torsion"][
        "directional_interactions"
    ]
    assert all(
        "code_applicable" not in item["interaction"]
        for item in interactions.values()
    )
    _select_view(at, "Torsion")
    table = next(
        frame.value for frame in at.dataframe
        if "Directional screen" in frame.value.columns
    )
    assert "NOT ASSESSED" not in set(table["Status"])
    assert set(table["Status"]) <= {"PASS", "FAIL"}



def _run_member(
    at,
    *,
    mx=0.0,
    p=0.0,
    v=0.0,
    t=0.0,
    combined_on=True,
    strut_band=None,
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
        if strut_band is not None:
            changes.extend([
                ("number_input", "strut_cot_min", strut_band[0]),
                ("number_input", "strut_cot_max", strut_band[1]),
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
    if strut_band is None:
        _set_and_click(at, "calculate", *active)
        return at
    _set(at, *active)
    bands = [
        ("number_input", "strut_cot_min", strut_band[0]),
        ("number_input", "strut_cot_max", strut_band[1]),
    ]
    _set_and_click(at, "calculate", *bands)
    return at


def test_app_combined_assembles_all_three():
    at = _fresh()
    at.run()
    _enable_all(at)
    assert not at.exception
    c = at.session_state["results"]["combined"]
    assert c["valid"]
    assert c["dkna_valid"]
    assert c["dkna_sum"] == pytest.approx(
        c["r_n"] + c["r_m"] + c["r_v"] + c["r_t"]
    )
    assert c["dkna_selection"]["utilisation"] == pytest.approx(c["dkna_sum"])
    assert c["dkna_selection"]["all_sum"] == pytest.approx(
        c["r_n"] + c["r_m"] + c["r_v"] + c["r_t"]
    )
    assert c["dkna_selection"]["governing_chord"] == "N+M+V+T"
    assert set(c["action_alone"]) == {"n", "m", "v", "t"}
    for action in c["action_alone"].values():
        assert action["valid"]
        assert action["source_clause"].endswith("6.3.2(6)")
    v_evidence = c["action_alone"]["v"]["evidence"]
    assert v_evidence["both_faces_evaluated"] is True
    assert v_evidence["faces_evaluated"] == ["negative", "positive"]
    assert c["member_angle_selection"]["selected_index"] >= 0
    assert c["member_angle_selection"]["samples"] == 1501
    assert c["crushing"] is not None            # shear links present -> crushing check
    assert c["crushing"]["value"] == pytest.approx(
        c["crushing"]["torsion_ratio"] + c["crushing"]["shear_ratio"]
    )
    assert c["asl_torsion"] > 0.0


def test_app_dkna_publishes_signed_n_biaxial_m_and_action_alone_resistances():
    at = _fresh()
    at.run()
    _set(
        at,
        ("number_input", "pl_P", 100.0),
        ("number_input", "pl_Mx", 80.0),
        ("number_input", "pl_My", -40.0),
        ("checkbox", "shear_on", True),
        ("checkbox", "torsion_on", True),
        ("checkbox", "combined_on", True),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 120.0),
        ("number_input", "torsion_T", 30.0),
    )
    assert not at.exception
    c = at.session_state["results"]["combined"]
    assert c["dkna_valid"]
    n = c["action_alone"]["n"]
    m = c["action_alone"]["m"]
    assert n["demand"] == pytest.approx(100.0)
    assert n["direction"] == "tension"
    assert n["evidence"]["zero_moment"] is True
    assert c["r_n"] == pytest.approx(abs(n["demand"]) / n["resistance"])
    assert m["demand"] == pytest.approx(math.hypot(80.0, -40.0))
    assert m["direction"] == pytest.approx(
        math.degrees(math.atan2(-40.0, 80.0)) % 360.0
    )
    assert m["evidence"]["axial_action_kn"] == pytest.approx(0.0)
    assert c["r_m"] == pytest.approx(m["demand"] / m["resistance"])

    _select_view(at, "M-V-T Combined")
    assert not at.exception
    labels = {metric.label for metric in at.metric}
    assert {r"Axial $N$", r"Bending $M$", r"Shear $V$", r"Torsion $T$"} <= labels
    visible = " ".join(
        str(item.value) for item in (*at.caption, *at.warning, *at.info)
    ).lower()
    assert "acting alone" in visible
    assert "biaxial moment direction" in visible
    assert "does not replace" in visible
    assert "annex f" in visible
    assert "folded" not in visible

    _set_and_click(
        at,
        "calculate",
        ("number_input", "pl_P", -100.0),
    )
    assert not at.exception
    compression = at.session_state["results"]["combined"]
    compression_n = compression["action_alone"]["n"]
    assert compression_n["demand"] == pytest.approx(-100.0)
    assert compression_n["direction"] == "compression"
    assert compression_n["evidence"]["zero_moment"] is True
    assert compression["r_n"] == pytest.approx(
        abs(compression_n["demand"]) / compression_n["resistance"]
    )


def test_app_dkna_unavailable_action_alone_resistance_is_not_assessed(
    monkeypatch,
):
    def unavailable(_inp):
        return {
            "n": capacity._dkna_action_record("N", 0.0, None, valid=True),
            "m": capacity._dkna_action_record(
                "M",
                100.0,
                None,
                valid=False,
                reason=(
                    "An action-alone resistance could not be determined. Check "
                    "the section, materials and complete Plastic bending sweep."
                ),
            ),
        }

    monkeypatch.setattr(
        capacity, "dkna_normal_bending_action_alone", unavailable
    )
    at = _fresh()
    at.run()
    _enable_all(at)
    assert not at.exception
    c = at.session_state["results"]["combined"]
    assert c["valid"]
    assert not c["dkna_valid"]
    assert c["dkna_sum"] is None
    assert c["dkna_ok"] is None

    _select_view(at, "M-V-T Combined")
    assert not at.exception
    combined_metric = next(
        metric for metric in at.metric
        if metric.label == r"$\sum(S_{Ed}/S_{Rd})$"
    )
    assert combined_metric.value == "-"
    assert combined_metric.delta in {None, ""}
    assert any("NOT ASSESSED" in warning.value for warning in at.warning)
    assert {
        "Concrete compression strut",
        "Closed stirrup",
        "Longitudinal reinforcement",
    } <= {metric.label for metric in at.metric}


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
    _goto_page(at, "Inputs")
    route = at.checkbox(key="combined_mv_independent")
    assert route.label == r"Apply separate $M$/$V$ route as a design assumption"
    assert "capacity, distribution and anchorage" in route.help
    assert "result remains CONDITIONAL" in route.help
    c = at.session_state["results"]["combined"]
    assert c["dkna_sum"] == pytest.approx(
        c["r_n"] + max(c["r_m"] + c["r_t"], c["r_v"] + c["r_t"])
    )
    assert c["dkna_selection"]["governing_chord"] in {"N+M+T", "N+V+T"}
    assert c["dkna_status"] == "CONDITIONAL"
    assert c["dkna_conditional"] is True
    assert c["dkna_ok"] is None
    assert c["dkna_limit_satisfied"] is (
        c["dkna_sum"] <= 1.0 + 1e-9
    )
    assert c["m_v_separation_condition"]["declared"] is True
    assert c["m_v_separation_condition"]["confirmed"] is False
    assert c["m_v_separation_condition"]["mechanically_verified"] is False
    assert "beyond" in c["m_v_separation_condition"]["condition"]
    _select_view(at, "M-V-T Combined")
    visible = " ".join(
        str(item.value) for item in (*at.caption, *at.warning, *at.info)
    )
    assert "CONDITIONAL" in visible
    assert "design assumption" in visible
    assert "area, distribution and anchorage" in visible
    assert "is confirmed" not in visible
    assert "N + M + T and N + V + T" in visible

    _select_view(at, "Results Overview")
    overview = at.table[0].value
    row = overview.loc[
        overview["Check"] == "Combined M-V-T - DK NA sum"
    ].iloc[0]
    assert row["Status"] == "CONDITIONAL"


def test_app_separate_mv_toggle_cannot_turn_same_actions_into_pass():
    at = _fresh()
    at.run()
    _set(
        at,
        ("number_input", "pl_Mx", 275.0),
        ("checkbox", "shear_on", True),
        ("checkbox", "torsion_on", True),
        ("checkbox", "combined_on", True),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 100.0),
        ("number_input", "torsion_T", 40.0),
    )
    simultaneous = copy.deepcopy(at.session_state["results"]["combined"])

    _set_and_click(
        at,
        "calculate",
        ("checkbox", "combined_mv_independent", True),
    )
    separate = at.session_state["results"]["combined"]

    assert simultaneous["action_alone"] == separate["action_alone"]
    assert simultaneous["dkna_sum"] > 1.0
    assert simultaneous["dkna_status"] == "FAIL"
    assert simultaneous["dkna_ok"] is False
    assert separate["dkna_sum"] < 1.0
    assert separate["dkna_limit_satisfied"] is True
    assert separate["dkna_status"] == "CONDITIONAL"
    assert separate["dkna_ok"] is None


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
    assert any("Vx,Ed = Vy,Ed = TEd = 0" in item.value for item in at.info)


def test_app_combined_view_renders():
    at = _fresh()
    at.run()
    _enable_all(at)
    links = at.session_state["results"]["shear"]["links"]
    assert len(links["chord_candidates"]) == 4
    assert {item["role"] for item in links["chord_candidates"]} == {
        "shear_axis", "off_axis",
    }
    assert links["governing_longitudinal"]["util"] == pytest.approx(
        max(item["util"] for item in links["chord_candidates"])
    )
    assert links["longitudinal_all_conditional"] is (
        links["longitudinal_fallback"] is None
    )
    combined = at.session_state["results"]["combined"]
    assert combined["governing_longitudinal"] == links["governing_longitudinal"]
    assert combined["longitudinal_fallback"] == links["longitudinal_fallback"]
    assert (
        combined["longitudinal_all_conditional"]
        is links["longitudinal_all_conditional"]
    )
    _select_view(at, "M-V-T Combined")
    assert not at.exception
    labels = [m.label for m in at.metric]
    assert any("Bending" in lbl for lbl in labels)
    assert any("S_{Ed}/S_{Rd}" in lbl for lbl in labels)
    # The summary exposes physical mechanisms, not an artificial maximum labelled
    # as transverse-reinforcement utilisation.
    for expected in (
        "Concrete compression strut",
        "Closed stirrup",
        "Longitudinal reinforcement",
    ):
        assert expected in labels
    assert "Closed-stirrup utilisation" in labels
    assert not any("Crushing utilisation" in lbl for lbl in labels)
    assert not any(lbl.startswith("Governing (") for lbl in labels)


def test_app_combined_out_of_default_range_warns_and_retains_verdicts():
    at = _fresh()
    at.run()
    at.number_input(key="strut_cot_max").set_value(3.0).run()
    _enable_all(at)
    assert not at.exception
    c = at.session_state["results"]["combined"]
    assert c["outside_default_range"] is True
    assert "code_applicable" not in c
    assert "code_applicable" not in c["crushing"]
    assert "code_applicable" not in c["longitudinal"]
    _select_view(at, "M-V-T Combined")
    assert any(
        "actual values are used in every combined calculation"
        in w.value.lower()
        for w in at.warning
    )
    verdict_labels = (
        r"$\sum(S_{Ed}/S_{Rd})$", "Sum",
        r"$M_{Ed,\mathrm{total}}/M_{Rd}$",
        "Concrete compression strut", "Closed stirrup",
        "Longitudinal reinforcement", "Closed-stirrup utilisation",
    )
    verdict_metrics = [
        m for m in at.metric
        if m.label in verdict_labels
    ]
    assert verdict_metrics
    assert all(metric.delta in {"PASS", "FAIL"} for metric in verdict_metrics)


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
    assert any("Vx,Ed = Vy,Ed = 0" in item.value for item in at.info)


def test_app_invalid_tube_does_not_poison_the_member_angle():
    # Workflow finding: an INVALID torsion tube (util = inf at every angle) must not
    # constrain the member angle -- previously it tied the scan and pinned the links
    # at band-low, changing the shear result.
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
    assert base["res"]["cot"] == pytest.approx(2.5)
    assert math.isfinite(base["util"])
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


def test_app_zero_torsion_is_skipped_with_the_shared_strut_band():
    # A zero torsion action is skipped; the live shear check uses the shared band.
    at = _fresh()
    at.run()
    _run_member(
        at,
        v=500.0,
        t=0.0,
        combined_on=False,
        strut_band=(1.0, 2.5),
    )
    r = at.session_state["results"]
    lk = r["shear"]["links"]
    assert lk["res"]["cot"] == pytest.approx(2.5)                # shear band governs
    assert "torsion" not in r


def test_app_dead_shear_companion_uses_the_shared_strut_band():
    # Mirror of the T=0 case: zero shear is skipped while torsion remains live.
    at = _fresh()
    at.run()
    _run_member(
        at,
        mx=80.0,
        v=0.0,
        t=40.0,
        combined_on=False,
        strut_band=(1.0, 1.2),
    )
    r = at.session_state["results"]
    assert "shear" not in r
    assert 1.0 - 1e-9 <= r["torsion"]["cot"] <= 1.2 + 1e-9


def test_app_invalid_bending_evidence_does_not_poison_the_member_angle():
    # An unreachable N/M request produces invalid plastic evidence, not an invented
    # infinite utilisation. The combined check must fail closed while the independent
    # V/T member-angle selection remains the same as when combined interaction is off.
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
    assert r_on["plastic"]["util"] is None
    assert r_on["plastic"]["util_valid"] is False
    assert r_on["combined"]["valid"] is False
    assert r_on["combined"]["have_m"] is False
    cot_on = r_on["shear"]["links"]["res"]["cot"]
    cot_off = r_off["shear"]["links"]["res"]["cot"]
    assert cot_on == pytest.approx(cot_off)


def test_app_dkna_action_alone_resistances_are_not_evaluated_at_common_angle():
    # DK NA 6.3.2(6) uses each resistance for its action acting ALONE. The selected
    # common angle remains authoritative for the physical shared-strut/stirrup/chord
    # checks, but it must not condition the action-alone V or T denominator.
    at = _fresh()
    at.run()

    _run_member(at, mx=150.0, v=280.0, t=100.0)
    result = at.session_state["results"]
    c = result["combined"]
    cot_star = result["shear"]["links"]["res"]["cot"]
    labels = c["member_angle_selection"]["objective_labels"]
    assert "DK NA governing interaction" not in labels
    v_action = c["action_alone"]["v"]
    t_action = c["action_alone"]["t"]
    assert c["r_v"] == pytest.approx(
        v_action["demand"] / v_action["resistance"]
    )
    assert c["r_t"] == pytest.approx(
        t_action["demand"] / t_action["resistance"]
    )
    # The action-alone capacities optimise their own resistance within the same
    # declared admissible band; the common physical angle remains separate.
    assert v_action["evidence"]["cot"] != pytest.approx(cot_star)
    assert t_action["evidence"]["cot"] != pytest.approx(cot_star)


def test_app_combined_is_skipped_when_shear_is_zero():
    # VEd = 0 disables the shear and dependent combined checks for this case.
    at = _fresh()
    at.run()
    _run_member(
        at,
        mx=90.0,
        v=0.0,
        t=60.0,
        strut_band=(1.0, 1.4),
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
    assert any("Vx,Ed = Vy,Ed = TEd = 0" in item.value for item in at.info)


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


def test_app_combined_uses_one_shared_strut_band():
    # Shear and torsion use one physical compression-strut range and therefore
    # report the same member angle for every live combined check.
    at = _fresh()
    at.run()
    _run_member(
        at,
        mx=100.0,
        v=100.0,
        t=40.0,
        strut_band=(1.4, 1.8),
    )
    assert not at.exception
    c = at.session_state["results"]["combined"]
    assert c["transverse"]["valid"] is True
    assert c["crushing"]["valid"] is True
    shared_cot = c["transverse"]["cot"]
    assert 1.4 <= shared_cot <= 1.8
    assert at.session_state["results"]["shear"]["links"]["res"]["cot"] == pytest.approx(
        shared_cot
    )
    assert at.session_state["results"]["torsion"]["cot"] == pytest.approx(shared_cot)


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
