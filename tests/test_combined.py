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
import result_presentation  # noqa: E402


# -- engine -----------------------------------------------------------------

def test_ratio_helper():
    assert combined.ratio(1.0, 2.0) == pytest.approx(0.5)
    assert combined.ratio(0.0, 0.0) == 0.0
    assert math.isinf(combined.ratio(1.0, 0.0))


def test_crushing_interaction():
    assert combined.crushing_interaction(40.0, 80.0, 150.0, 600.0) == pytest.approx(0.75)
    assert math.isinf(combined.crushing_interaction(1.0, 0.0, 0.0, 1.0))


def test_formula_631_screen_retains_operands_and_exact_existing_verdict():
    result = combined.minimum_reinforcement_screen_result(
        15.0,
        60.0,
        30.0,
        120.0,
        solid_rectangle=True,
        subdivided=False,
        model_2023=False,
        shear_available=True,
    )

    assert result.applicable is True
    assert result.status == "PASS"
    assert result.value == pytest.approx(0.5)
    assert result.torsion_ratio == pytest.approx(0.25)
    assert result.shear_ratio == pytest.approx(0.25)
    assert result.governs == "torsion"
    assert result.ok is True
    assert result.detailing_status == "NOT RUN"
    assert result.detailing_scope_key == "separate_detailing_not_run"


@pytest.mark.parametrize(
    ("kwargs", "status", "scope_key"),
    [
        (
            {"solid_rectangle": False},
            "NOT APPLICABLE",
            "section_geometry",
        ),
        (
            {"subdivided": True},
            "NOT APPLICABLE",
            "subdivided_section",
        ),
        (
            {
                "model_2023": True,
                "shear_available": False,
                "v_ed": None,
                "vrd_c": None,
            },
            "NOT APPLICABLE",
            "selected_2023_route",
        ),
        (
            {"shear_available": False, "v_ed": None, "vrd_c": None},
            "NOT ASSESSED",
            "shear_resistance_unavailable",
        ),
        (
            {"trd_c": 0.0},
            "NOT ASSESSED",
            "positive_resistance_unavailable",
        ),
    ],
    ids=(
        "unsupported-geometry",
        "subdivided",
        "2023-route",
        "missing-shear",
        "nonpositive-resistance",
    ),
)
def test_formula_631_scope_branches_never_publish_a_verdict(
    kwargs,
    status,
    scope_key,
):
    inputs = dict(
        t_ed=15.0,
        trd_c=60.0,
        v_ed=30.0,
        vrd_c=120.0,
        solid_rectangle=True,
        subdivided=False,
        model_2023=False,
        shear_available=True,
    )
    inputs.update(kwargs)

    result = combined.minimum_reinforcement_screen_result(**inputs)

    assert result.applicable is False
    assert result.status == status
    assert result.scope_key == scope_key
    assert result.value is None
    assert result.ok is None


@pytest.mark.parametrize(
    ("action", "value"),
    (
        ("n_ed", -20.0),
        ("n_ed", 20.0),
        ("mx_ed", -15.0),
        ("mx_ed", 15.0),
        ("my_ed", -10.0),
        ("my_ed", 10.0),
    ),
)
def test_dkna_formula_631_scope_rejects_signed_normal_or_moment_actions(
    action,
    value,
):
    kwargs = {action: value}
    result = combined.minimum_reinforcement_screen_result(
        15.0,
        60.0,
        30.0,
        120.0,
        solid_rectangle=True,
        subdivided=False,
        model_2023=False,
        shear_available=True,
        dk_na=True,
        shear_method="DS/EN 1992-1-1:2005 + DK NA:2024",
        torsion_method="DS/EN 1992-1-1:2005 + DK NA:2024",
        **kwargs,
    )

    assert result.applicable is False
    assert result.status == "NOT APPLICABLE"
    assert result.scope_key == "dkna_combined_normal_or_moment"
    assert result.normal_or_moment_active is True
    assert result.value is None and result.ok is None
    assert result.dk_na is True
    assert "DK NA:2024" in result.shear_method
    assert "DK NA:2024" in result.torsion_method


@pytest.mark.parametrize(
    ("scope_context", "scope_overrides"),
    (
        ("nonrectangular", {"solid_rectangle": False}),
        ("hollow", {"solid_rectangle": False}),
        (
            "subdivided",
            {"solid_rectangle": False, "subdivided": True},
        ),
        (
            "unavailable-shear",
            {"shear_available": False, "v_ed": None, "vrd_c": None},
        ),
        (
            "selected-2023",
            {
                "model_2023": True,
                "shear_method": codes.EC2_2023.label,
                "torsion_method": codes.EC2_2005_DKNA.label,
            },
        ),
    ),
    ids=lambda value: value if isinstance(value, str) else None,
)
@pytest.mark.parametrize(
    ("action", "value"),
    (
        ("n_ed", -20.0),
        ("n_ed", 20.0),
        ("mx_ed", -15.0),
        ("mx_ed", 15.0),
        ("my_ed", -10.0),
        ("my_ed", 10.0),
    ),
)
def test_dkna_formula_631_requirement_outranks_other_scope_limitations(
    scope_context,
    scope_overrides,
    action,
    value,
):
    inputs = dict(
        t_ed=15.0,
        trd_c=60.0,
        v_ed=30.0,
        vrd_c=120.0,
        solid_rectangle=True,
        subdivided=False,
        model_2023=False,
        shear_available=True,
        dk_na=True,
        shear_method=codes.EC2_2005_DKNA.label,
        torsion_method=codes.EC2_2005_DKNA.label,
        n_ed=0.0,
        mx_ed=0.0,
        my_ed=0.0,
    )
    inputs.update(scope_overrides)
    inputs[action] = value

    result = combined.minimum_reinforcement_screen_result(**inputs)

    assert scope_context in {
        "nonrectangular", "hollow", "subdivided", "unavailable-shear",
        "selected-2023",
    }
    assert result.applicable is False
    assert result.status == "NOT APPLICABLE"
    assert result.scope_key == "dkna_combined_normal_or_moment"
    assert result.normal_or_moment_active is True
    assert result.dk_na is True
    assert result.value is None and result.ok is None
    if scope_context == "selected-2023":
        assert result.model_2023 is True
        assert result.shear_method == codes.EC2_2023.label
        assert result.torsion_method == codes.EC2_2005_DKNA.label


def test_dkna_formula_631_scope_accepts_exact_zero_normal_and_moment_actions():
    result = combined.minimum_reinforcement_screen_result(
        15.0,
        60.0,
        30.0,
        120.0,
        solid_rectangle=True,
        subdivided=False,
        model_2023=False,
        shear_available=True,
        dk_na=True,
        n_ed=-0.0,
        mx_ed=0.0,
        my_ed=0.0,
    )

    assert result.applicable is True
    assert result.status == "PASS"
    assert result.normal_or_moment_active is False
    assert result.dk_na is True


def test_formula_631_over_limit_is_fail_and_not_a_sufficiency_result():
    result = combined.minimum_reinforcement_screen_result(
        45.0,
        60.0,
        60.0,
        120.0,
        solid_rectangle=True,
        subdivided=False,
        model_2023=False,
        shear_available=True,
    )

    assert result.value == pytest.approx(1.25)
    assert result.status == "FAIL"
    assert result.ok is False


def test_all_not_applicable_directional_screens_remain_not_applicable():
    assert capacity.aggregate_assessment_status(
        ["NOT APPLICABLE", "NOT APPLICABLE"]
    ) == "NOT APPLICABLE"
    assert capacity.aggregate_assessment_status(
        ["NOT APPLICABLE", "NOT ASSESSED"]
    ) == "NOT ASSESSED"


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


def test_dkna_independent_route_over_limit_fails_even_under_assumption():
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
    assert result.status == "FAIL"
    assert result.ok is False


@pytest.mark.parametrize(
    ("utilisation", "expected_status", "expected_ok"),
    [
        (1.0, "CONDITIONAL", None),
        (math.nextafter(1.0, math.inf), "FAIL", False),
    ],
    ids=["at-limit", "first-representable-value-over-limit"],
)
def test_dkna_separate_route_limit_boundary_is_exact(
    utilisation,
    expected_status,
    expected_ok,
):
    result = combined.dkna_interaction_result(
        0.0,
        None,
        utilisation,
        1.0,
        0.0,
        None,
        0.0,
        None,
        m_v_independent=True,
    )

    assert result.utilisation == utilisation
    assert result.limit_satisfied is (utilisation <= 1.0)
    assert result.status == expected_status
    assert result.ok is expected_ok


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


def test_longitudinal_chord_2023_exact_two_face_review_fixture():
    tension = combined.longitudinal_chord_check_2023(
        90.0,
        100.0,
        250.0,
        0.0,
        0.5,
        tension_low=True,
        flexural_tension_low=True,
    )
    assert tension["chord_formula"] == "8.51"
    assert tension["chord_role"] == "flexural_tension"
    assert tension["face_m_ed_signed"] == pytest.approx(90.0)
    assert tension["mv"] == pytest.approx(125.0)
    assert tension["m_total"] == pytest.approx(215.0)
    assert tension["util"] == pytest.approx(2.15)
    assert tension["status"] == "FAIL"
    assert tension["chord_force_kn"] == pytest.approx(430.0)

    compression = combined.longitudinal_chord_check_2023(
        90.0,
        100.0,
        250.0,
        0.0,
        0.5,
        tension_low=False,
        flexural_tension_low=True,
    )
    assert compression["chord_formula"] == "8.52"
    assert compression["chord_role"] == "flexural_compression"
    assert compression["face_m_ed_signed"] == pytest.approx(-90.0)
    assert compression["mv"] == pytest.approx(125.0)
    assert compression["m_total"] == pytest.approx(35.0)
    assert compression["util"] == pytest.approx(0.35)
    assert compression["chord_force_kn"] == pytest.approx(-70.0)
    assert compression["chord_force_sign"] == "tension"


@pytest.mark.parametrize(
    ("moment", "flexural_tension_low"),
    ((90.0, True), (-90.0, False)),
)
def test_longitudinal_chord_2023_signed_moment_swaps_physical_faces(
    moment,
    flexural_tension_low,
):
    faces = {
        tension_low: combined.longitudinal_chord_check_2023(
            moment,
            100.0,
            250.0,
            0.0,
            0.5,
            tension_low=tension_low,
            flexural_tension_low=flexural_tension_low,
        )
        for tension_low in (True, False)
    }
    assert faces[flexural_tension_low]["m_total"] == pytest.approx(215.0)
    assert faces[flexural_tension_low]["chord_formula"] == "8.51"
    assert faces[not flexural_tension_low]["m_total"] == pytest.approx(35.0)
    assert faces[not flexural_tension_low]["chord_formula"] == "8.52"


def test_longitudinal_chord_2023_retains_axial_operand_without_double_counting():
    compression = combined.longitudinal_chord_check_2023(
        90.0,
        100.0,
        250.0,
        0.0,
        0.5,
        tension_low=False,
        flexural_tension_low=True,
        n_ed=-60.0,
    )
    tension = combined.longitudinal_chord_check_2023(
        90.0,
        100.0,
        250.0,
        0.0,
        0.5,
        tension_low=False,
        flexural_tension_low=True,
        n_ed=60.0,
    )
    assert compression["n_ed"] == pytest.approx(-60.0)
    assert tension["n_ed"] == pytest.approx(60.0)
    assert compression["chord_force_kn"] == pytest.approx(-100.0)
    assert tension["chord_force_kn"] == pytest.approx(-40.0)
    assert compression["m_total"] == pytest.approx(tension["m_total"])
    assert compression["util"] == pytest.approx(tension["util"])
    assert compression["axial_force_conditioned_in_m_rd"] is True
    reversed_tension_chord = combined.longitudinal_chord_check_2023(
        10.0,
        100.0,
        5.0,
        0.0,
        0.5,
        tension_low=True,
        flexural_tension_low=True,
        n_ed=-100.0,
    )
    assert reversed_tension_chord["chord_formula"] == "8.51"
    assert reversed_tension_chord["chord_force_kn"] == pytest.approx(-25.0)
    assert reversed_tension_chord["chord_force_sign"] == "compression"


@pytest.mark.parametrize(
    ("args", "kwargs"),
    (
        ((math.nan, 100.0, 250.0, 0.0, 0.5), {}),
        ((90.0, math.inf, 250.0, 0.0, 0.5), {}),
        ((90.0, 100.0, -1.0, 0.0, 0.5), {}),
        ((90.0, 100.0, 250.0, 0.0, 0.0), {}),
        ((90.0, 100.0, 250.0, 0.0, 0.5), {"n_ed": True}),
        (
            (90.0, 100.0, 250.0, 0.0, 0.5),
            {"flexural_tension_low": np.bool_(True)},
        ),
    ),
)
def test_longitudinal_chord_2023_rejects_invalid_operands(args, kwargs):
    options = {"tension_low": True, "flexural_tension_low": True}
    options.update(kwargs)
    with pytest.raises(ValueError, match="finite|positive|non-negative|Boolean"):
        combined.longitudinal_chord_check_2023(*args, **options)


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


def _translate_section_y(at, offset_mm):
    """Translate every section point while reseeding the rendered editors."""
    _goto_page(at, "Inputs")
    editors = {
        "corners_base": "ed_corners",
        "hole_base": "ed_hole",
        "bars_base": "ed_bars",
        "tendons_base": "ed_tendons",
    }
    for base_key, editor_key in editors.items():
        table = at.session_state[base_key].copy(deep=True)
        if "y (mm)" in table.columns:
            table["y (mm)"] = table["y (mm)"] + offset_mm
        try:
            version = at.session_state[editor_key + "_ver"]
        except KeyError:
            version = 0
        at.session_state[base_key] = table
        at.session_state[editor_key + "_ver"] = version + 1
        try:
            del at.session_state[editor_key]
        except KeyError:
            pass
    at.run()
    return at


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


def test_biaxial_combined_reuses_one_lazy_normal_bending_action_solve(
    monkeypatch,
):
    original = capacity.dkna_normal_bending_action_alone
    calls = 0

    def counted(inp):
        nonlocal calls
        calls += 1
        return original(inp)

    monkeypatch.setattr(
        capacity, "dkna_normal_bending_action_alone", counted
    )
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
    assert calls == 1
    aggregate = at.session_state["results"]["combined"]
    assert set(aggregate["directions"]) == {"vx", "vy"}
    assert all(
        set(direction["action_alone"]) == {"n", "m", "v", "t"}
        for direction in aggregate["directions"].values()
    )


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
        direction["resistance_status"] == "PASS"
        and direction["status"] == "FAIL"
        and direction["links"]["longitudinal_assessment"]["status"] == "FAIL"
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


def test_app_biaxial_unavailable_prerequisite_retains_selected_separate_route(
    monkeypatch,
):
    def unavailable(_inp):
        return {
            "n": capacity._dkna_action_record("N", 0.0, None, valid=True),
            "m": capacity._dkna_action_record(
                "M",
                50.0,
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
        ("checkbox", "combined_mv_independent", True),
        ("number_input", "shear_Vx", 10.0),
        ("number_input", "shear_Vy", 12.0),
        ("number_input", "torsion_T", 5.0),
    )

    assert not at.exception
    aggregate = at.session_state["results"]["combined"]
    assert aggregate["biaxial"] is True
    assert aggregate["m_v_independent"] is True
    assert aggregate["m_v_separation_condition"]["declared"] is True
    assert set(aggregate["directions"]) == {"vx", "vy"}
    assert all(
        direction["m_v_independent"] is True
        and direction["dkna_valid"] is False
        for direction in aggregate["directions"].values()
    )
    assert result_presentation.combined_dkna_screen_label(aggregate) == (
        "max(N+M+T, N+V+T)"
    )

    _select_view(at, "M-V-T Combined")
    assert not at.exception
    visible = " ".join(
        str(item.value)
        for family in (at.caption, at.warning, at.info)
        for item in family
    )
    assert "NOT ASSESSED" in visible
    assert "action-alone" in visible


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
    assert "within the numerical limit is CONDITIONAL" in route.help
    assert "above the limit is FAIL even under" in route.help
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
    assert row["Status"] == "NOT ASSESSED"


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

    _set_and_click(
        at,
        "calculate",
        ("number_input", "pl_Mx", 400.0),
    )
    over_limit = at.session_state["results"]["combined"]
    assert over_limit["m_v_independent"] is True
    assert over_limit["dkna_sum"] > 1.0
    assert over_limit["dkna_limit_satisfied"] is False
    assert over_limit["dkna_conditional"] is True
    assert over_limit["dkna_status"] == "FAIL"
    assert over_limit["dkna_ok"] is False

    _select_view(at, "M-V-T Combined")
    visible = " ".join(
        str(item.value)
        for family in (at.markdown, at.warning)
        for item in family
    )
    assert "FAIL" in visible
    assert "even under the favourable" in visible
    assert "failed numerical check governs" in visible

    _select_view(at, "Results Overview")
    overview = at.table[0].value
    row = overview.loc[
        overview["Check"] == "Combined M-V-T - DK NA sum"
    ].iloc[0]
    assert row["Status"] == "FAIL"


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


def test_app_combined_incomplete_flags_missing(monkeypatch):
    monkeypatch.setattr(
        capacity,
        "dkna_normal_bending_action_alone",
        lambda _inp: pytest.fail(
            "action-alone resistance entered for an incomplete combined check"
        ),
    )
    at = _fresh()
    at.run()
    _set_and_click(
        at, "calculate", ("checkbox", "combined_on", True)
    )  # no shear / torsion
    assert not at.exception
    assert "combined" not in at.session_state["results"]
    _select_view(at, "M-V-T Combined")
    assert any("Vx,Ed = Vy,Ed = TEd = 0" in item.value for item in at.info)

    _set(at, ("checkbox", "shear_on", True))
    _set_and_click(
        at,
        "calculate",
        ("number_input", "shear_V", 50.0),
    )
    assert not at.exception
    assert "shear" in at.session_state["results"]
    assert "torsion" not in at.session_state["results"]
    assert "combined" not in at.session_state["results"]


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
    dkna_sum_metrics = [
        metric for metric in verdict_metrics
        if metric.label == r"$\sum(S_{Ed}/S_{Rd})$"
    ]
    assert dkna_sum_metrics
    assert all(not metric.delta for metric in dkna_sum_metrics)
    for component_label in ("Sum", "Closed-stirrup utilisation"):
        component_metrics = [
            metric for metric in verdict_metrics
            if metric.label == component_label
        ]
        assert component_metrics
        assert all(
            metric.delta in {"PASS", "FAIL"}
            for metric in component_metrics
        )


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


@pytest.mark.parametrize(
    ("moment", "flexural_tension_low"),
    ((100.0, True), (-100.0, False)),
)
def test_app_2023_shear_retains_both_signed_longitudinal_chords(
    moment,
    flexural_tension_low,
):
    at = _fresh().run()
    _set(
        at,
        ("checkbox", "shear_on", True),
        ("selectbox", "shear_method", codes.EC2_2023.label),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 150.0),
        ("number_input", "pl_Mx", moment),
    )

    assert not at.exception
    links = at.session_state["results"]["shear"]["links"]
    assert links["model_2023"] is True
    candidates = [
        candidate
        for candidate in links["chord_candidates"]
        if candidate["role"] == "shear_axis"
    ]
    assert len(candidates) == 2
    assert {candidate["tension_low"] for candidate in candidates} == {True, False}
    assert {candidate["chord_formula"] for candidate in candidates} == {
        "8.51",
        "8.52",
    }
    assert all(candidate["gets_shift"] is True for candidate in candidates)
    assert all(candidate["conditional"] is True for candidate in candidates)
    by_role = {candidate["chord_role"]: candidate for candidate in candidates}
    assert by_role["flexural_tension"]["tension_low"] is flexural_tension_low
    assert by_role["flexural_tension"]["face_m_ed_signed"] > 0.0
    assert by_role["flexural_compression"]["tension_low"] is not flexural_tension_low
    assert by_role["flexural_compression"]["face_m_ed_signed"] < 0.0
    assert links["longitudinal_assessment"]["coverage_complete"] is True
    assert links["longitudinal_assessment"]["status"] in {"PASS", "FAIL"}


def test_app_2023_chords_are_invariant_to_section_reference_translation():
    at = _fresh().run()
    _set(
        at,
        ("checkbox", "shear_on", True),
        ("selectbox", "shear_method", codes.EC2_2023.label),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "pl_P", 100.0),
        ("number_input", "pl_Mx", 20.0),
        ("number_input", "shear_V", 150.0),
    )
    assert not at.exception
    centred_links = at.session_state["results"]["shear"]["links"]
    centred = {
        candidate["tension_low"]: candidate
        for candidate in centred_links["chord_candidates"]
        if candidate["role"] == "shear_axis"
    }

    _translate_section_y(at, 300.0)
    _set_and_click(
        at,
        "calculate",
        ("number_input", "pl_Mx", -10.0),
    )

    assert not at.exception
    shifted_links = at.session_state["results"]["shear"]["links"]
    shifted = {
        candidate["tension_low"]: candidate
        for candidate in shifted_links["chord_candidates"]
        if candidate["role"] == "shear_axis"
    }
    assert shifted_links["m_ed_2023"] == pytest.approx(20.0)
    assert shifted_links["moment_reference_shift"] == pytest.approx(30.0)
    assert set(shifted) == {True, False}
    assert shifted[True]["chord_role"] == "flexural_tension"
    assert shifted[False]["chord_role"] == "flexural_compression"
    for tension_low in (True, False):
        assert shifted[tension_low]["m_ed_origin_signed"] == pytest.approx(
            -10.0
        )
        assert shifted[tension_low]["moment_reference_shift"] == pytest.approx(
            30.0
        )
        assert shifted[tension_low]["face_m_ed_signed"] == pytest.approx(
            centred[tension_low]["face_m_ed_signed"]
        )
        assert shifted[tension_low]["m_rd"] == pytest.approx(
            centred[tension_low]["m_rd"],
            rel=2.0e-6,
        )
        assert shifted[tension_low]["util"] == pytest.approx(
            centred[tension_low]["util"],
            rel=2.0e-6,
        )


def test_app_2023_shear_with_torsion_retains_complete_shifted_chords():
    at = _fresh().run()
    _set(
        at,
        ("checkbox", "shear_on", True),
        ("selectbox", "shear_method", codes.EC2_2023.label),
        ("checkbox", "torsion_on", True),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 150.0),
        ("number_input", "pl_Mx", 90.0),
        ("number_input", "torsion_T", 40.0),
    )

    assert not at.exception
    links = at.session_state["results"]["shear"]["links"]
    shear_faces = [
        candidate
        for candidate in links["chord_candidates"]
        if candidate["role"] == "shear_axis"
    ]
    off_axis_faces = [
        candidate
        for candidate in links["chord_candidates"]
        if candidate["role"] == "off_axis"
    ]
    assert len(shear_faces) == 2
    assert len(off_axis_faces) == 2
    assert {candidate["chord_formula"] for candidate in shear_faces} == {
        "8.51",
        "8.52",
    }
    assert all(candidate["gets_shift"] is True for candidate in shear_faces)
    assert all(candidate["ftd_t"] > 0.0 for candidate in shear_faces)
    assert links["longitudinal_assessment"]["coverage_complete"] is True
    assert links["longitudinal_assessment"]["status"] in {"PASS", "FAIL"}


def _install_exact_2023_chord_review_fixture(monkeypatch):
    original = combined.longitudinal_chord_check_2023

    def controlled_review_fixture(
        _m_ed_signed,
        _m_rd,
        _n_vd,
        _ftd_t,
        _z,
        *,
        tension_low,
        flexural_tension_low,
        n_ed=0.0,
    ):
        return original(
            90.0,
            100.0,
            250.0,
            0.0,
            0.5,
            tension_low=tension_low,
            flexural_tension_low=flexural_tension_low,
            n_ed=n_ed,
        )

    monkeypatch.setattr(
        combined,
        "longitudinal_chord_check_2023",
        controlled_review_fixture,
    )


def _app_with_failed_2023_chord(monkeypatch):
    _install_exact_2023_chord_review_fixture(monkeypatch)
    at = _fresh().run()
    _set(
        at,
        ("checkbox", "shear_on", True),
        ("selectbox", "shear_method", codes.EC2_2023.label),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 150.0),
        ("number_input", "pl_Mx", 90.0),
    )
    return at


def test_app_2023_failed_required_chord_propagates_to_shear_and_overview(
    monkeypatch,
):
    at = _app_with_failed_2023_chord(monkeypatch)

    assert not at.exception
    links = at.session_state["results"]["shear"]["links"]
    assessment = links["longitudinal_assessment"]
    assert at.session_state["results"]["shear"]["assessment_status"] == "FAIL"
    assert at.session_state["results"]["shear"]["assessment_ok"] is False
    assert assessment["status"] == "FAIL"
    assert assessment["ok"] is False
    assert assessment["coverage_complete"] is True
    assert assessment["util"] == pytest.approx(2.15)
    assert assessment["governing"]["m_total"] == pytest.approx(215.0)

    _select_view(at, "Shear")
    visible = " ".join(
        str(item.value) for item in (*at.warning, *at.caption, *at.markdown)
    )
    assert "Overall reinforced shear assessment: FAIL" in visible
    assert "required longitudinal chords exceed" in visible
    face_table = next(
        frame.value
        for frame in at.dataframe
        if "Formula" in frame.value.columns
        and "Signed Mface" in frame.value.columns
    )
    assert set(face_table["Formula"]) == {"(8.51)", "(8.52)"}
    assert set(face_table["Status"]) == {"FAIL", "PASS"}

    _select_view(at, "Results Overview")
    overview = at.table[0].value
    row = overview.loc[
        overview["Check"] == "Shear longitudinal chords"
    ].iloc[0]
    assert row["Status"] == "FAIL"
    assert row["Result"] == "215.0 %"
    overall_row = overview.loc[
        overview["Check"] == "Shear with links"
    ].iloc[0]
    assert overall_row["Status"] == "FAIL"
    assert overall_row["Result"] == "215.0 %"


@pytest.mark.parametrize("profile", ("Brief", "Standard", "Audit"))
def test_failed_2023_chord_reaches_every_report_profile(monkeypatch, profile):
    import io

    import pypdf

    import sector_report

    at = _app_with_failed_2023_chord(monkeypatch)
    assert not at.exception
    inputs = at.session_state["_latest_inputs"]
    results = at.session_state["results"]
    results["worked_example_selection"] = (
        result_presentation.worked_example_selection(inputs, results)
    )
    pdf = sector_report.build_report(
        {},
        inputs,
        results,
        figures=False,
        profile=profile,
    )
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    text = " ".join(
        " ".join((page.extract_text() or "").split())
        for page in reader.pages
    )

    assert "Shear longitudinal chords" in text
    assert "215.0 %" in text
    assert "FAIL" in text
    assert "required longitudinal chords exceed" in text
    assert "SHEAR-LONGITUDINAL" not in text
    if profile in {"Standard", "Audit"}:
        assert "Required 2023 longitudinal chord faces" in text
        assert "(8.51)" in text and "(8.52)" in text
        assert "215.0 kNm" in text


def _app_with_incomplete_2023_chord(monkeypatch):
    original = capacity.shear_face_mrd

    def one_face_unavailable(
        inp,
        axis,
        tension_low,
        m_off=0.0,
        **kwargs,
    ):
        if tension_low is False:
            return 0.0, False
        return original(inp, axis, tension_low, m_off=m_off, **kwargs)

    monkeypatch.setattr(capacity, "shear_face_mrd", one_face_unavailable)
    at = _fresh().run()
    _set(
        at,
        ("checkbox", "shear_on", True),
        ("selectbox", "shear_method", codes.EC2_2023.label),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 150.0),
        ("number_input", "pl_Mx", 90.0),
    )
    return at


def test_app_2023_incomplete_chord_coverage_is_not_assessed(monkeypatch):
    at = _app_with_incomplete_2023_chord(monkeypatch)
    assert not at.exception
    shear = at.session_state["results"]["shear"]
    assessment = shear["links"]["longitudinal_assessment"]
    assert len(shear["links"]["chord_candidates"]) == 1
    assert assessment["status"] == "NOT ASSESSED"
    assert assessment["ok"] is None
    assert assessment["coverage_complete"] is False
    assert shear["assessment_status"] == "NOT ASSESSED"
    assert shear["assessment_ok"] is None

    _select_view(at, "Shear")
    visible = " ".join(
        str(item.value) for item in (*at.warning, *at.caption, *at.markdown)
    )
    assert "Overall reinforced shear assessment: NOT ASSESSED" in visible
    assert "Complete both required longitudinal chord checks" in visible

    _select_view(at, "Results Overview")
    overview = at.table[0].value
    for check in ("Shear with links", "Shear longitudinal chords"):
        row = overview.loc[overview["Check"] == check].iloc[0]
        assert row["Status"] == "NOT ASSESSED"


@pytest.mark.parametrize("profile", ("Brief", "Standard", "Audit"))
def test_incomplete_2023_chord_is_not_assessed_in_every_report_profile(
    monkeypatch,
    profile,
):
    import io

    import pypdf

    import sector_report

    at = _app_with_incomplete_2023_chord(monkeypatch)
    assert not at.exception
    inputs = at.session_state["_latest_inputs"]
    results = at.session_state["results"]
    results["worked_example_selection"] = (
        result_presentation.worked_example_selection(inputs, results)
    )
    pdf = sector_report.build_report(
        {}, inputs, results, figures=False, profile=profile
    )
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    text = " ".join(
        " ".join((page.extract_text() or "").split())
        for page in reader.pages
    )

    assert "Shear longitudinal chords" in text
    assert "NOT ASSESSED" in text
    assert "Complete both required longitudinal chord checks" in text
    assert "SHEAR-LONGITUDINAL" not in text
    if profile in {"Standard", "Audit"}:
        assert "Required 2023 longitudinal chord faces" in text
        assert "(8.51)" in text
        assert "Flexural tension" in text


def _app_with_no_2023_chord_candidate(monkeypatch):
    monkeypatch.setattr(
        capacity,
        "shear_face_mrd",
        lambda *args, **kwargs: (0.0, False),
    )
    at = _fresh().run()
    _set(
        at,
        ("checkbox", "shear_on", True),
        ("checkbox", "torsion_on", True),
    )
    _set(
        at,
        ("selectbox", "shear_method", codes.EC2_2023.label),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 150.0),
        ("number_input", "pl_Mx", 90.0),
        ("number_input", "torsion_T", 40.0),
    )
    return at


def test_app_2023_zero_chord_candidates_remain_visibly_not_assessed(
    monkeypatch,
):
    at = _app_with_no_2023_chord_candidate(monkeypatch)

    assert not at.exception
    results = at.session_state["results"]
    links = results["shear"]["links"]
    assert links["model_2023"] is True
    assert links["chord"] is None
    assert links["chord_candidates"] == []
    assert links["longitudinal_assessment"]["status"] == "NOT ASSESSED"

    _select_view(at, "Shear")
    visible = " ".join(
        str(item.value)
        for item in (*at.warning, *at.info, *at.caption, *at.markdown)
    )
    assert "Complete both required longitudinal chord checks" in visible

    _select_view(at, "Results Overview")
    overview = at.table[0].value
    row = overview.loc[
        overview["Check"] == "Shear longitudinal chords"
    ].iloc[0]
    assert row["Status"] == "NOT ASSESSED"


@pytest.mark.parametrize("profile", ("Brief", "Standard", "Audit"))
def test_zero_2023_chord_candidates_publish_assessment_without_legacy_copy(
    monkeypatch,
    profile,
):
    import io

    import pypdf

    import sector_report

    at = _app_with_no_2023_chord_candidate(monkeypatch)
    assert not at.exception
    inputs = at.session_state["_latest_inputs"]
    results = at.session_state["results"]
    results["worked_example_selection"] = (
        result_presentation.worked_example_selection(inputs, results)
    )
    pdf = sector_report.build_report(
        {},
        inputs,
        results,
        figures=False,
        profile=profile,
    )
    text = " ".join(
        " ".join((page.extract_text() or "").split())
        for page in pypdf.PdfReader(io.BytesIO(pdf)).pages
    )

    assert "Shear longitudinal chords" in text
    assert "NOT ASSESSED" in text
    assert "Complete both required longitudinal chord checks" in text
    assert "SHEAR-LONGITUDINAL" not in text
    if profile in {"Standard", "Audit"}:
        assert "Required 2023 longitudinal chord faces" in text
        assert "Enable shear links for the full utilisation check" not in text
        assert "both beyond the bending steel" not in text


def test_mvt_view_zero_2023_chord_candidates_uses_retained_assessment():
    at = _fresh().run()
    _enable_all(at)
    assert not at.exception

    retained = copy.deepcopy(at.session_state["results"])
    combined_result = retained["combined"]
    combined_result.pop("longitudinal", None)
    combined_result.pop("longitudinal_candidates", None)
    combined_result.pop("governing_longitudinal", None)
    combined_result["longitudinal_model_2023"] = True
    combined_result["longitudinal_assessment"] = {
        "status": "NOT ASSESSED",
        "ok": None,
        "util": None,
        "reason": "required_longitudinal_chord_coverage_incomplete",
        "coverage_complete": False,
        "governing": None,
    }
    at.session_state["results"] = retained

    _select_view(at, "M-V-T Combined")

    assert not at.exception
    visible = " ".join(
        str(item.value)
        for family in (at.markdown, at.warning, at.info, at.caption)
        for item in family
    )
    assert "Required 2023 longitudinal chord faces" in visible
    assert "Longitudinal chord assessment: NOT ASSESSED" in visible
    assert "Complete both required longitudinal chord checks" in visible
    assert "Enable links for the full utilisation check" not in visible
    assert "(6.18)" not in visible
    assert r"\Delta Ftd" not in visible
    assert "ΔFtd" not in visible


def test_failed_2023_chord_propagates_to_retained_mvt_component_and_overview():
    assessment = {
        "status": "FAIL",
        "ok": False,
        "util": 2.15,
        "reason": "required_longitudinal_chord_failed",
        "coverage_complete": True,
        "governing": {"valid": True, "util": 2.15},
    }
    combined_result = {
        "valid": True,
        "method": codes.EC2_2005_DKNA.label,
        "dkna_valid": True,
        "dkna_sum": 0.60,
        "dkna_limit_satisfied": True,
        "dkna_status": "PASS",
        "dkna_ok": True,
        "torsion_assessment_status": "PASS",
        "torsion_longitudinal_assessment": {
            "status": "NOT ASSESSED",
            "demand_ratio": 0.40,
            "reason": "longitudinal_torsion_reinforcement_not_verified",
        },
        "longitudinal_assessment": assessment,
        "transverse": {
            "valid": True,
            "u_crush": 0.40,
            "u_stirrup": 0.50,
            "cot": 1.5,
            "shear_fraction": 0.25,
            "torsion_fraction": 0.25,
        },
    }

    assert result_presentation.combined_dkna_status(combined_result) == "FAIL"
    note = result_presentation.combined_governing_assessment_note(
        combined_result
    )
    assert "required longitudinal chords exceed" in note
    assert "not an overall M-V-T verdict" in note
    components = {
        item["key"]: item
        for item in result_presentation.combined_physical_components(
            combined_result
        )
    }
    assert components["longitudinal"]["status"] == "FAIL"
    assert components["longitudinal"]["util"] == pytest.approx(2.15)
    assert "required longitudinal chords exceed" in (
        components["longitudinal"]["note"]
    )
    assert "distributed around every torsion-tube side" in (
        components["longitudinal"]["note"]
    )

    rows = result_presentation.result_summary_rows(
        {"combined_on": True},
        {"combined": combined_result},
    )
    by_check = {row["check"]: row for row in rows}
    assert by_check["Combined M-V-T - DK NA sum"]["status"] == "FAIL"
    longitudinal = by_check["Combined longitudinal reinforcement"]
    assert longitudinal["status"] == "FAIL"
    assert longitudinal["result"] == "215.0 %"


def test_incomplete_2023_chord_keeps_retained_mvt_not_assessed():
    combined_result = {
        "valid": True,
        "dkna_valid": True,
        "dkna_sum": 0.60,
        "dkna_limit_satisfied": True,
        "dkna_status": "PASS",
        "dkna_ok": True,
        "torsion_assessment_status": "PASS",
        "torsion_longitudinal_assessment": {
            "status": "NOT ASSESSED",
            "demand_ratio": 0.40,
            "reason": "longitudinal_torsion_reinforcement_not_verified",
        },
        "longitudinal_assessment": {
            "status": "NOT ASSESSED",
            "ok": None,
            "util": 0.50,
            "reason": "required_longitudinal_chord_coverage_incomplete",
            "coverage_complete": False,
            "governing": {"valid": True, "util": 0.50},
        },
    }

    assert (
        result_presentation.combined_dkna_status(combined_result)
        == "NOT ASSESSED"
    )
    components = {
        item["key"]: item
        for item in result_presentation.combined_physical_components(
            combined_result
        )
    }
    assert components["longitudinal"]["status"] == "NOT ASSESSED"
    assert components["longitudinal"]["coverage"] == "incomplete"
    assert "Complete both required longitudinal chord checks" in (
        components["longitudinal"]["note"]
    )
    assert "distributed around every torsion-tube side" in (
        components["longitudinal"]["note"]
    )


def test_incomplete_torsion_wall_evidence_blocks_stale_mvt_verdicts():
    raw_reason = "torsion wall reinforcement mapping is incomplete"
    torsion_result = {
        "valid": False,
        "tube_valid": False,
        "closed_links_present": True,
        "transverse_resistance_assessed": False,
        "full_resistance_assessed": False,
        "reason": raw_reason,
        "trd": 999.123,
        "util": 0.42,
    }
    stale_combined = {
        "valid": True,
        "dkna_valid": True,
        "dkna_sum": 0.72,
        "dkna_limit_satisfied": True,
        "dkna_status": "PASS",
        "dkna_ok": True,
    }
    results = {"torsion": torsion_result, "combined": stale_combined}

    blocker = result_presentation.combined_bending_assessment_blocker(results)
    assert blocker == (
        "Torsion prerequisite is not assessed: Torsion is not assessed because "
        "longitudinal reinforcement has not been established for every "
        "equivalent-tube wall"
    )
    assert raw_reason not in blocker
    rows = result_presentation.result_summary_rows(
        {"torsion_on": True, "combined_on": True, "shear_links": True},
        results,
    )
    combined_row = next(
        row for row in rows if row["check"] == "Combined M-V-T - DK NA sum"
    )
    assert combined_row["status"] == "NOT ASSESSED"
    assert combined_row["result"] == "-"
    assert combined_row["util"] is None
    assert (
        result_presentation.worked_example_selection({}, results)["families"].get(
            "combined"
        )
        is None
    )


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


def test_app_combined_is_skipped_when_shear_is_zero(monkeypatch):
    # VEd = 0 disables the shear and dependent combined checks for this case.
    monkeypatch.setattr(
        capacity,
        "dkna_normal_bending_action_alone",
        lambda _inp: pytest.fail(
            "action-alone resistance entered for a zero-shear combined check"
        ),
    )
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
    # The link comparison is not a live nominal route, so its resistance-optimum
    # angle does not constrain the torsion-led combined check.
    r = at.session_state["results"]
    assert r["shear"]["nominal_resistance"]["route"] == "concrete"
    assert r["shear"]["links"]["longitudinal_shear_force"] == pytest.approx(0.0)
    assert r["combined"]["action_alone"]["v"]["evidence"][
        "nominal_route"
    ] == "concrete"
    assert r["combined"]["r_v"] == pytest.approx(
        r["combined"]["action_alone"]["v"]["demand"]
        / r["combined"]["action_alone"]["v"]["resistance"]
    )
    assert r["shear"]["links"]["theta_mode"] == "resistance"
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
