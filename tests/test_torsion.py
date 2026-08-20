"""Tests for the torsional resistance (EN 1992-1-1:2005 section 6.3).

Reference hand calculation: a 300 x 600 mm solid rectangle, C35, DK NA:2024, with a
closed phi10 stirrup at s = 150 mm (fywk = 500). The tube idealisation gives
A = 0.18 m2, u = 1.8 m, tef = 100 mm, Ak = 0.1 m2, uk = 1.4 m; at the optimum strut
cot(theta) = 1.751 the stirrups and the struts meet at TRd ~ 76.4 kN.m.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from sector import codes, shear, torsion


def _rect(b, h):
    """Corner-origin rectangle b x h (metres)."""
    return [(0.0, 0.0), (b, 0.0), (b, h), (0.0, h)]


def _f095_box():
    """Exact centred 600 mm box and 400 mm void from F095-003."""
    outer = [(-0.3, -0.3), (0.3, -0.3), (0.3, 0.3), (-0.3, 0.3)]
    hole = [(-0.2, -0.2), (-0.2, 0.2), (0.2, 0.2), (0.2, -0.2)]
    return outer, hole


# -- tube idealisation ------------------------------------------------------

def test_tube_properties_solid_rectangle():
    t = torsion.tube_properties(_rect(0.3, 0.6), None)
    assert t["valid"]
    assert t["A"] == pytest.approx(0.18)
    assert t["u"] == pytest.approx(1.8)
    assert t["tef"] == pytest.approx(100.0)           # A/u = 0.1 m -> 100 mm
    assert t["Ak"] == pytest.approx(0.1)              # (0.3-0.1)(0.6-0.1)
    assert t["uk"] == pytest.approx(1.4)              # 2(0.2 + 0.5)
    assert t["minimum_dimension_mm"] == pytest.approx(300.0)
    assert not t["tef_capped"] and not t["tef_user"]


def test_exact_terminal_closure_marker_preserves_tube_properties():
    open_ring = _rect(0.3, 0.6)
    closed_ring = [*open_ring, open_ring[0]]
    reference = torsion.tube_properties(open_ring, None)
    closed = torsion.tube_properties(closed_ring, None)
    for key in ("A", "u", "tef", "Ak", "uk", "minimum_dimension_mm"):
        assert closed[key] == pytest.approx(reference[key])


def test_tube_minimum_dimension_is_rotation_invariant():
    angle = math.radians(45.0)
    cosine, sine = math.cos(angle), math.sin(angle)
    rotated = [
        (x * cosine - y * sine, x * sine + y * cosine)
        for x, y in _rect(0.1, 1.0)
    ]
    tube = torsion.tube_properties(rotated, None)
    assert tube["valid"]
    assert tube["minimum_dimension_mm"] == pytest.approx(100.0)


def test_tube_tef_override():
    outer = _rect(0.3, 0.6)
    default = torsion.tube_properties(outer, None)
    assert torsion.tube_properties(outer, None, tef_override=0.0) == default

    t = torsion.tube_properties(outer, None, tef_override=80.0)
    assert t["tef"] == pytest.approx(80.0)
    assert t["tef_user"]
    assert t["tef_selection"] == "user override"
    # Centre-line offset by 40 mm -> (0.3-0.08)(0.6-0.08).
    assert t["Ak"] == pytest.approx((0.3 - 0.08) * (0.6 - 0.08))


def test_tube_hollow_caps_tef_at_the_wall():
    # A thin box: outer 0.6 x 0.6, a 0.4 x 0.4 void -> 0.1 m walls. A/u = 0.36/2.4 =
    # 0.15 m, but the real wall is 0.1 m, so tef is capped to the actual wall.
    outer = _rect(0.6, 0.6)
    hole = [(0.1, 0.1), (0.5, 0.1), (0.5, 0.5), (0.1, 0.5)]
    t = torsion.tube_properties(outer, [hole])
    assert t["hollow"] and t["tef_capped"]
    assert t["tef_auto"] == pytest.approx(150.0)
    assert t["tef"] == pytest.approx(100.0)             # the actual 100 mm wall


@pytest.mark.parametrize("override_mm", [80.0, 100.0])
def test_tube_hollow_accepts_override_at_or_below_the_real_wall(override_mm):
    outer = _rect(0.6, 0.6)
    hole = [(0.1, 0.1), (0.5, 0.1), (0.5, 0.5), (0.1, 0.5)]
    tube = torsion.tube_properties(outer, [hole], tef_override=override_mm)
    assert tube["valid"]
    assert tube["tef"] == pytest.approx(override_mm)
    assert tube["tef_user"] is True
    assert tube["tef_selection"] == "user override"


def test_f095_box_rejects_inflating_override_before_resistance():
    outer, hole = _f095_box()
    automatic = torsion.tube_properties(outer, [hole])
    assert automatic["tef"] == pytest.approx(100.0)
    assert automatic["Ak"] == pytest.approx(0.25)
    assert automatic["tef_selection"] == "real-wall cap"
    assert torsion.trd_c(2.0, automatic["Ak"], automatic["tef"]) == (
        pytest.approx(100.0)
    )

    with pytest.raises(ValueError, match=(
        r"tef override 150 mm exceeds the nearest real wall thickness 100 mm"
    )):
        torsion.tube_properties(outer, [hole], tef_override=150.0)


def test_tube_hollow_uses_the_nearest_asymmetric_wall_for_override_limit():
    outer = _rect(0.6, 0.6)
    # Clear walls are 50, 150, 100 and 100 mm; the 50 mm wall governs.
    hole = [(0.05, 0.1), (0.45, 0.1), (0.45, 0.5), (0.05, 0.5)]
    with pytest.raises(ValueError, match=(
        r"tef override 60 mm exceeds the nearest real wall thickness 50 mm"
    )):
        torsion.tube_properties(outer, [hole], tef_override=60.0)


def test_tube_hollow_tolerance_never_increases_tef_beyond_real_wall():
    from sector import geometry

    outer = _rect(0.6, 0.6)
    hole = [(0.1, 0.1), (0.5, 0.1), (0.5, 0.5), (0.1, 0.5)]
    tolerance_mm = (
        geometry.validate_section_topology(outer, [hole]).floating_point_tolerance
        * 1000.0
    )
    tube = torsion.tube_properties(
        outer,
        [hole],
        tef_override=100.0 + 0.5 * tolerance_mm,
    )
    assert tube["valid"]
    assert tube["tef"] == pytest.approx(100.0, rel=0.0, abs=1.0e-12)
    assert tube["tef_user"] is True

    with pytest.raises(ValueError, match=r"exceeds the nearest real wall thickness"):
        torsion.tube_properties(
            outer,
            [hole],
            tef_override=100.0 + 2.0 * tolerance_mm,
        )


def test_tube_hollow_override_tolerance_does_not_scale_with_section_width():
    # A 1e9 m wide section has a 1 m topology-relative tolerance, but its nearest
    # real wall is a separately represented 2 m engineering dimension. A 2.5 m
    # override is materially above that wall and must not be treated as equality.
    outer = _rect(1.0e9, 10.0)
    hole = [(2.0, 3.0), (1.0e9 - 2.0, 3.0),
            (1.0e9 - 2.0, 7.0), (2.0, 7.0)]
    with pytest.raises(ValueError, match=(
        r"tef override 2500 mm exceeds the nearest real wall thickness 2000 mm"
    )):
        torsion.tube_properties(outer, [hole], tef_override=2500.0)


@pytest.mark.parametrize(
    "override",
    [
        -1.0,
        math.nan,
        math.inf,
        -math.inf,
        True,
        False,
        np.bool_(True),
        np.bool_(False),
        "80",
        b"80",
        None,
    ],
)
def test_tube_rejects_invalid_tef_override_scalars(override):
    with pytest.raises(
        ValueError,
        match=r"tef override must be a finite non-negative real number \(mm\)",
    ):
        torsion.tube_properties(_rect(0.3, 0.6), None, tef_override=override)


def test_tube_thin_box_wall_is_not_overestimated():
    # Codex P1: a 1.0 x 1.0 box with a centered 0.9 x 0.9 void has 50 mm walls; the
    # cap must be the real wall, not the ~63 mm the concrete-area/perimeter estimate
    # gave (which inflated TRd,max / TRd,c by ~20%).
    outer = _rect(1.0, 1.0)
    hole = [(0.05, 0.05), (0.95, 0.05), (0.95, 0.95), (0.05, 0.95)]
    t = torsion.tube_properties(outer, [hole])
    assert t["tef_auto"] == pytest.approx(250.0)        # A/u = 1.0/4.0
    assert t["tef"] == pytest.approx(50.0)              # the actual 50 mm wall


def test_tube_rejects_too_large_tef_override():
    # A tef larger than the section can support inverts the inward offset; it must be
    # rejected (not accepted via abs() as a spurious Ak), leaving an invalid tube.
    t = torsion.tube_properties(_rect(0.3, 0.6), None, tef_override=400.0)
    assert not t["valid"]
    assert t["Ak"] == 0.0


def test_tube_multi_cell_is_invalid():
    # Codex P2: two or more voids -> the single-tube idealisation does not model the
    # internal webs, so it is rejected rather than reporting an unconservative TRd.
    outer = _rect(1.0, 1.0)
    h1 = [(0.1, 0.1), (0.4, 0.1), (0.4, 0.9), (0.1, 0.9)]
    h2 = [(0.6, 0.1), (0.9, 0.1), (0.9, 0.9), (0.6, 0.9)]
    t = torsion.tube_properties(outer, [h1, h2])
    assert not t["valid"]
    assert "multi-cell" in (t.get("reason") or "")


def test_offset_polygon_inward_square():
    ring = torsion.offset_polygon_inward([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0),
                                          (0.0, 1.0)], 0.1)
    from sector import geometry
    assert abs(geometry.signed_area(ring)) == pytest.approx(0.64)   # 0.8 x 0.8


def test_tube_tolerates_collinear_outline_vertices():
    # Codex P2: an extra vertex on a straight edge must not collapse the offset (which
    # would drop to the coarse linear estimate). The tube matches the clean rectangle.
    clean = torsion.tube_properties(_rect(0.3, 0.6), None)
    withpt = torsion.tube_properties(
        [(0.0, 0.0), (0.15, 0.0), (0.3, 0.0), (0.3, 0.6), (0.0, 0.6)], None)  # mid-edge pt
    assert withpt["Ak"] == pytest.approx(clean["Ak"])
    assert withpt["uk"] == pytest.approx(clean["uk"])


# -- resistances (hand-calc anchor) -----------------------------------------

def _tube():
    return torsion.tube_properties(_rect(0.3, 0.6), None)


# -- sub-tube (compound section) primitives ---------------------------------

def test_rectangle_torsion_constant_square():
    # Square a x a: C ~ 0.1406 a^4 (the exact St Venant value; the Roark closed-form
    # used here gives 0.1408, ~0.2% high -- acceptable for a stiffness-share weight).
    assert torsion.rectangle_torsion_constant(0.4, 0.4) == pytest.approx(
        0.1406 * 0.4 ** 4, rel=3e-3)


def test_rectangle_torsion_constant_thin_tends_to_third():
    # Thin strip (s << h): C -> h*s^3/3.
    b, h = 0.02, 1.0
    assert torsion.rectangle_torsion_constant(b, h) == pytest.approx(
        h * b ** 3 / 3.0, rel=0.02)


def test_rectangle_torsion_constant_is_orientation_independent():
    assert (torsion.rectangle_torsion_constant(0.3, 0.7)
            == pytest.approx(torsion.rectangle_torsion_constant(0.7, 0.3)))


def test_rectangle_torsion_constant_degenerate_is_zero():
    assert torsion.rectangle_torsion_constant(0.0, 0.5) == 0.0


def test_rectangle_ring_matches_tube_properties():
    # The centred rectangle ring must give the same tube props as a corner rectangle.
    ring = torsion.rectangle_ring(0.3, 0.6)
    t = torsion.tube_properties(ring, None)
    assert t["A"] == pytest.approx(0.18)
    assert t["tef"] == pytest.approx(100.0)
    assert t["Ak"] == pytest.approx(0.1)


def test_distribute_by_stiffness_proportional_and_conserves():
    parts = torsion.distribute_by_stiffness(100.0, [3.0, 1.0])
    assert parts == [pytest.approx(75.0), pytest.approx(25.0)]
    assert sum(parts) == pytest.approx(100.0)


def test_distribute_by_stiffness_skips_nonpositive():
    parts = torsion.distribute_by_stiffness(80.0, [0.0, 2.0, 2.0])
    assert parts == [0.0, pytest.approx(40.0), pytest.approx(40.0)]


def test_distribute_by_stiffness_all_zero_is_zeros():
    assert torsion.distribute_by_stiffness(50.0, [0.0, 0.0]) == [0.0, 0.0]


def test_retained_stiffness_distribution_is_compact_and_exact():
    result = torsion.stiffness_distribution_result(90.0, [1.0, 2.0, -1.0])
    assert result.positive_stiffness_sum == pytest.approx(3.0)
    assert result.torque_parts == pytest.approx((30.0, 60.0, 0.0))
    assert sum(result.torque_parts) == pytest.approx(result.applied_torque)
    assert [share.fraction for share in result.shares] == pytest.approx(
        [1.0 / 3.0, 2.0 / 3.0, 0.0]
    )
    assert not hasattr(result, "__dict__")
    with pytest.raises(AttributeError):
        result.applied_torque = 1.0


def test_retained_torsion_formula_results_match_legacy_scalars():
    code = codes.EC2_2005_DKNA
    steel = torsion.trd_s_result(0.08, 435.0, 2.1, 1.75)
    assert steel.trd_s == pytest.approx(
        torsion.trd_s(0.08, 435.0, 2.1, 1.75)
    )
    strut = torsion.trd_max_result(
        35.0, code, 0.08, 80.0, 1.0, 1.75, fcd_mpa=23.0
    )
    assert strut.trd_max == pytest.approx(
        torsion.trd_max(
            35.0, code, 0.08, 80.0, 1.0, 1.75, fcd_mpa=23.0
        )
    )
    assert strut.tan == pytest.approx(1.0 / 1.75)
    assert strut.sin_cos == pytest.approx(1.75 / (1.0 + 1.75**2))
    cracking = torsion.trd_c_result(1.9, 0.08, 80.0)
    assert cracking.trd_c == pytest.approx(torsion.trd_c(1.9, 0.08, 80.0))
    longitudinal = torsion.asl_required_result(
        40.0, 1.2, 0.08, 435.0, 1.75
    )
    assert longitudinal.asl_required_mm2 == pytest.approx(
        torsion.asl_required(40.0, 1.2, 0.08, 435.0, 1.75)
    )
    selected = torsion.select_torsion_resistance(
        steel.trd_s, strut.trd_max, asw_over_s=2.1
    )
    assert selected.resistance == pytest.approx(
        min(steel.trd_s, strut.trd_max)
    )


@pytest.mark.parametrize(
    ("trd_s_value", "trd_max_value", "resistance", "governs"),
    [
        (40.0, 60.0, 40.0, "stirrups (TRd,s)"),
        (60.0, 40.0, 40.0, "crushing (TRd,max)"),
        (40.0, 40.0, 40.0, "stirrups (TRd,s)"),
        (0.0, 60.0, 0.0, "stirrups (TRd,s)"),
        (60.0, 0.0, 0.0, "crushing (TRd,max)"),
    ],
)
def test_full_torsion_resistance_selects_only_under_current_closed_links(
    trd_s_value, trd_max_value, resistance, governs
):
    selected = torsion.select_full_torsion_resistance(
        trd_s_value,
        trd_max_value,
        closed_links_present=True,
        asw_over_s=0.5,
    )
    assert selected.full_resistance_assessed is True
    assert selected.trd_s == pytest.approx(trd_s_value)
    assert selected.trd_max == pytest.approx(trd_max_value)
    assert selected.closed_links_present is True
    assert selected.asw_over_s == pytest.approx(0.5)
    assert selected.resistance == pytest.approx(resistance)
    assert selected.governs == governs
    assert selected.reason is None


@pytest.mark.parametrize(
    ("asw_over_s", "trd_s_value"),
    [(0.0, 0.0), (0.5, 40.0)],
)
def test_full_torsion_resistance_never_infers_absent_link_authority(
    asw_over_s, trd_s_value
):
    selected = torsion.select_full_torsion_resistance(
        trd_s_value,
        60.0,
        closed_links_present=False,
        asw_over_s=asw_over_s,
    )
    assert selected.full_resistance_assessed is False
    assert selected.trd_s == pytest.approx(trd_s_value)
    assert selected.trd_max == pytest.approx(60.0)
    assert selected.closed_links_present is False
    assert selected.asw_over_s == pytest.approx(asw_over_s)
    assert selected.resistance is None
    assert selected.governs is None
    assert selected.reason == "closed_links_not_present"


def test_full_torsion_resistance_rejects_zero_current_link_reinforcement():
    selected = torsion.select_full_torsion_resistance(
        0.0,
        60.0,
        closed_links_present=True,
        asw_over_s=0.0,
    )
    assert selected.full_resistance_assessed is False
    assert selected.trd_s == pytest.approx(0.0)
    assert selected.trd_max == pytest.approx(60.0)
    assert selected.closed_links_present is True
    assert selected.asw_over_s == pytest.approx(0.0)
    assert selected.resistance is None
    assert selected.governs is None
    assert selected.reason == "closed_link_reinforcement_not_positive"


@pytest.mark.parametrize(
    "authority",
    [None, 0, 1, "", "true", np.bool_(False), np.bool_(True), object()],
)
def test_full_torsion_resistance_requires_exact_boolean_authority(authority):
    with pytest.raises(ValueError, match="built-in Boolean"):
        torsion.select_full_torsion_resistance(
            40.0,
            60.0,
            closed_links_present=authority,
            asw_over_s=0.5,
        )


class _FloatRaisesValueError:
    def __float__(self):
        raise ValueError("hostile numeric evidence")


@pytest.mark.parametrize("field", ["trd_s", "trd_max", "asw_over_s"])
@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        "0.5",
        b"0.5",
        object(),
        _FloatRaisesValueError(),
        10**400,
        -0.1,
        math.nan,
        math.inf,
        -math.inf,
    ],
)
def test_full_torsion_resistance_rejects_malformed_numeric_evidence(field, value):
    values = {"trd_s": 40.0, "trd_max": 60.0, "asw_over_s": 0.5}
    values[field] = value
    with pytest.raises(ValueError, match="finite non-negative real number"):
        torsion.select_full_torsion_resistance(
            values["trd_s"],
            values["trd_max"],
            closed_links_present=True,
            asw_over_s=values["asw_over_s"],
        )


def test_full_torsion_resistance_normalizes_and_freezes_retained_selection():
    trd_s_value = np.float64(40.0)
    trd_max_value = np.int64(60)
    asw_over_s = np.float64(0.5)
    selected = torsion.select_full_torsion_resistance(
        trd_s_value,
        trd_max_value,
        closed_links_present=True,
        asw_over_s=asw_over_s,
    )
    assert type(selected.trd_s) is float
    assert type(selected.trd_max) is float
    assert type(selected.asw_over_s) is float
    assert type(selected.resistance) is float
    assert not hasattr(selected, "__dict__")
    with pytest.raises(AttributeError):
        selected.resistance = 1.0
    assert trd_s_value == np.float64(40.0)
    assert trd_max_value == np.int64(60)
    assert asw_over_s == np.float64(0.5)


def test_full_torsion_resistance_authority_is_a_required_keyword():
    with pytest.raises(TypeError):
        torsion.select_full_torsion_resistance(40.0, 60.0, asw_over_s=0.5)
    with pytest.raises(TypeError):
        torsion.select_full_torsion_resistance(40.0, 60.0, True, 0.5)


def test_retained_torsion_wrappers_preserve_invalid_legacy_boundaries():
    result = torsion.asl_required_result(10.0, 1.0, -0.1, -500.0, 1.0)
    assert result.asl_required_mm2 == 0.0
    zero_angle = torsion.trd_max_result(
        35.0, codes.EC2_2005, 0.08, 80.0, 1.0, 0.0
    )
    assert math.isinf(zero_angle.tan)
    assert zero_angle.trd_max == 0.0


def test_torsion_nu_closed_detailing_only_changes_dk_na():
    # The nu_t->nu_v allowance changes nu ONLY on the DK NA edition; the recommended
    # edition ignores closed_detailing. This underpins gating the display flag.
    fck = 35.0
    dk = codes.EC2_2005_DKNA
    assert (dk.torsion_nu(fck, closed_detailing=True)
            != dk.torsion_nu(fck, closed_detailing=False))
    rec = codes.EC2_2005
    assert (rec.torsion_nu(fck, closed_detailing=True)
            == rec.torsion_nu(fck, closed_detailing=False))


def test_app_nu_v_detailing_flag_gated_to_dk_na():
    at = _fresh()
    at.run()
    at.checkbox(key="torsion_on").set_value(True).run()
    _enable_shared_links(at)
    _set_and_click(
        at,
        "calculate",
        ("number_input", "torsion_T", 40.0),
        ("checkbox", "torsion_nu_v", True),
    )
    assert at.session_state["results"]["torsion"]["nu_v_detailing"] is True   # DK NA
    _set(at, ("selectbox", "torsion_method", codes.EC2_2005.label))
    _set_and_click(
        at, "calculate", ("number_input", "torsion_T", 40.0)
    )
    # Recommended edition: the allowance did not apply, so the flag must be False.
    assert at.session_state["results"]["torsion"]["nu_v_detailing"] is False


def test_torsion_nu_edition_dependent():
    assert codes.EC2_2005.torsion_nu(35.0) == pytest.approx(0.6 * (1 - 35.0 / 250.0))
    assert codes.EC2_2005_DKNA.torsion_nu(35.0) == pytest.approx(0.7 * (0.7 - 35.0 / 200.0))


def test_torsion_nu_has_no_floor_above_c50():
    # DK NA:2024 5.104 NA: nu_t = 0.7*(0.7 - fck/200) with NO lower bound -- the
    # 0.45 floor of 5.103 NA belongs to nu_v ONLY. Above C50 nu_t keeps falling
    # (C60: 0.28); carrying the nu_v floor into nu_t (0.7*0.45 = 0.315) would be
    # unconservative. (User-verified against the DK NA text, p. 33-34.)
    assert codes.EC2_2005_DKNA.shear_nu1(60.0) == pytest.approx(0.45)   # nu_v floored
    assert codes.EC2_2005_DKNA.torsion_nu(60.0) == pytest.approx(0.28)  # unfloored
    assert codes.EC2_2005_DKNA.torsion_nu(60.0) < 0.7 * 0.45
    # Very high fck cannot drive nu_t negative.
    assert codes.EC2_2005_DKNA.torsion_nu(150.0) == 0.0


def test_trd_s_and_trd_max_meet_at_the_optimum():
    code = codes.EC2_2005_DKNA
    t = _tube()
    fcd = code.concrete_factor(35.0) * 35.0 / code.gamma_c
    fywd = 500.0 / code.gamma_s
    nu = code.torsion_nu(35.0)
    asw_over_s = math.pi / 4 * 10.0 ** 2 / 150.0        # 1 closed phi10 leg / 150 mm
    # The torsion optimum reuses the shear crossover with a = (Asw/s)*fywd,
    # b = nu*alpha_cw*fcd*tef (tef in mm).
    a = asw_over_s * fywd
    b = nu * 1.0 * fcd * t["tef"]
    cot = shear.optimum_cot_theta(a, b, 1.0, 2.5)
    assert cot == pytest.approx(1.751, abs=1e-3)
    vs = torsion.trd_s(t["Ak"], fywd, asw_over_s, cot)
    vmax = torsion.trd_max(35.0, code, t["Ak"], t["tef"], 1.0, cot)
    assert vs == pytest.approx(76.4, abs=0.3)
    assert vmax == pytest.approx(76.4, abs=0.3)
    assert vs == pytest.approx(vmax, rel=1e-3)          # crossover


def test_trd_max_peaks_at_cot_one():
    code = codes.EC2_2005_DKNA
    t = _tube()
    peak = torsion.trd_max(35.0, code, t["Ak"], t["tef"], 1.0, 1.0)
    flatter = torsion.trd_max(35.0, code, t["Ak"], t["tef"], 1.0, 2.0)
    assert peak > flatter
    assert peak == pytest.approx(88.7, abs=0.5)


def test_trd_max_accepts_final_user_fcd():
    code = codes.EC2_2005_DKNA
    t = _tube()
    preset = torsion.trd_max(35.0, code, t["Ak"], t["tef"], 1.0, 1.0)
    custom_fcd = 0.8 * code.concrete_factor(35.0) * 35.0 / code.gamma_c
    custom = torsion.trd_max(
        35.0, code, t["Ak"], t["tef"], 1.0, 1.0, fcd_mpa=custom_fcd,
    )
    assert custom == pytest.approx(0.8 * preset)


def test_trd_c_cracking_moment():
    code = codes.EC2_2005_DKNA
    t = _tube()
    fctm = codes.fctm(35.0)
    fctd = 0.7 * fctm / code.gamma_ct                # fctk,0.05 / gamma_ct
    tc = torsion.trd_c(fctd, t["Ak"], t["tef"])
    assert tc == pytest.approx(2.0 * t["Ak"] * (t["tef"] / 1000.0) * fctd * 1000.0)
    assert tc == pytest.approx(26.434984813960778)


def test_asl_required_longitudinal_steel():
    code = codes.EC2_2005_DKNA
    t = _tube()
    fyd = 500.0 / code.gamma_s
    asl = torsion.asl_required(50.0, t["uk"], t["Ak"], fyd, 1.751)
    assert asl == pytest.approx(1471.0, abs=5.0)


# -- app integration (AppTest) ----------------------------------------------

import pathlib  # noqa: E402
import sys  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
APP = str(ROOT / "app" / "sector_app.py")

from app_case_inputs import (  # noqa: E402
    apply_widget_changes,
    discard_retired_qs_fragment,
    first_case_value,
    goto_input_stage,
)


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
    """Submit a group of existing inputs with one button-triggered rerun."""
    if button_key in {"qs_apply", "qs_back"} and changes:
        _set(at, *changes)
        changes = ()
    elif button_key == "calculate" and changes:
        _set(at, *changes)
        changes = ()
    for widget_type, key, value in changes:
        getattr(at, widget_type)(key=key).set_value(value)
    if button_key == "calculate":
        _goto_page(at, "Analysis")
    at.button(key=button_key).click()
    at.run()
    if button_key in {"qs_apply", "qs_back"}:
        discard_retired_qs_fragment(at)
    return at


def _apply_t_section(at, bf=1000.0, hf=200.0, bw=300.0, hw=600.0):
    at.session_state["_qs_open"] = True
    at.run()
    _set(at, ("selectbox", "shape", "T-section"))
    _set_and_click(
        at,
        "qs_apply",
        ("number_input", "bf_mm", bf),
        ("number_input", "hf_mm", hf),
        ("number_input", "bw_mm", bw),
        ("number_input", "hw_mm", hw),
    )
    return at


def _apply_box_section(at, b=600.0, h=600.0, wall=100.0):
    at.session_state["_qs_open"] = True
    at.run()
    _set(at, ("selectbox", "shape", "Box girder"))
    _set_and_click(
        at,
        "qs_apply",
        ("number_input", "b_mm", b),
        ("number_input", "h_mm", h),
        ("number_input", "wall_mm", wall),
    )
    return at


def _enable_shared_links(at):
    _set(at, ("checkbox", "shear_links", True))
    return at


def test_app_torsion_without_current_closed_links_is_not_assessed():
    at = _fresh()
    at.run()
    at.checkbox(key="torsion_on").set_value(True).run()
    _set_and_click(at, "calculate", ("number_input", "torsion_T", 40.0))
    assert not at.exception
    t = at.session_state["results"]["torsion"]
    assert t["tube_valid"] is True
    assert t["closed_links_present"] is False
    assert t["full_resistance_assessed"] is False
    assert t["assessment_reason"] == "closed_links_not_present"
    assert t["valid"] is False
    assert t["asw_over_s"] == 0.0
    assert t["trd_s"] == 0.0
    assert t["trd"] is None
    assert t["util"] is None
    assert t["governs"] is None
    assert t["trd_max"] > 0.0
    assert t["trd_c"] > 0.0
    assert t["asl_req"] > 0.0
    assert t["theta_mode"] == "transparency"
    _select_view(at, "Torsion")
    assert any("NOT ASSESSED" in item.value for item in at.warning)
    labels = [metric.label for metric in at.metric]
    assert r"Concrete cap $T_{Rd,max}$" in labels
    assert not any("Utilisation" in label for label in labels)


def test_app_retains_but_does_not_apply_nu_v_request_without_current_links():
    at = _fresh()
    at.run()
    at.checkbox(key="torsion_on").set_value(True).run()
    _enable_shared_links(at)
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "torsion_nu_v", True),
        ("number_input", "torsion_T", 40.0),
    )
    with_links = at.session_state["results"]["torsion"]
    assert with_links["nu_v_detailing"] is True

    _set_and_click(at, "calculate", ("checkbox", "shear_links", False))
    without_links = at.session_state["results"]["torsion"]

    assert at.session_state["torsion_nu_v"] is True
    assert without_links["closed_links_present"] is False
    assert without_links["nu_v_detailing"] is False
    assert without_links["nu"] < with_links["nu"]
    assert without_links["trd"] is None


def test_app_torsion_produces_a_resistance_with_current_closed_links():
    at = _fresh()
    at.run()
    at.checkbox(key="torsion_on").set_value(True).run()
    _enable_shared_links(at)
    _set_and_click(at, "calculate", ("number_input", "torsion_T", 40.0))
    assert not at.exception
    t = at.session_state["results"]["torsion"]
    assert t["tube_valid"] is True
    assert t["closed_links_present"] is True
    assert t["full_resistance_assessed"] is True
    assert t["valid"] and t["trd"] > 0.0
    assert t["trd"] == pytest.approx(min(t["trd_s"], t["trd_max"]))
    assert 1.0 <= t["cot"] <= 2.5
    assert t["util"] == pytest.approx(40.0 / t["trd"])
    assert t["asl_req"] > 0.0                       # torsion needs longitudinal steel


def test_app_combined_without_links_withholds_torsion_dependent_verdicts():
    at = _fresh()
    at.run()
    _set(
        at,
        ("checkbox", "shear_on", True),
        ("checkbox", "torsion_on", True),
        ("checkbox", "combined_on", True),
        ("number_input", "shear_V", 30.0),
        ("number_input", "torsion_T", 20.0),
    )
    _calculate(at)

    assert not at.exception
    results = at.session_state["results"]
    torsion_result = results["torsion"]
    assert torsion_result["closed_links_present"] is False
    assert torsion_result["full_resistance_assessed"] is False
    assert torsion_result.get("interaction") is None

    combined_result = results["combined"]
    assert set(combined_result) == {
        "valid",
        "have_m",
        "have_v",
        "have_t",
        "method",
        "component",
        "governing_face",
        "governing_cot",
    }
    assert combined_result["valid"] is False
    assert combined_result["have_m"] is True
    assert combined_result["have_v"] is True
    assert combined_result["have_t"] is False
    assert combined_result["method"] == at.session_state["combined_method"]
    assert "dkna_sum" not in combined_result
    assert "crushing" not in combined_result
    assert "transverse" not in combined_result


def test_app_hollow_override_above_real_wall_preserves_completed_result():
    import copy
    import project_io

    at = _fresh()
    at.run()
    _apply_box_section(at)
    _set(
        at,
        ("checkbox", "torsion_on", True),
        ("number_input", "torsion_T", 40.0),
    )
    _enable_shared_links(at)
    _calculate(at)
    assert not at.exception
    baseline = at.session_state["results"]["torsion"]
    assert baseline["valid"] is True
    assert baseline["tube"]["hollow"] is True
    assert baseline["tube"]["tef"] == pytest.approx(100.0)
    assert baseline["tube"]["tef_selection"] == "real-wall cap"
    baseline_result_hash = project_io.result_sha256(at.session_state["results"])
    baseline_signature = at.session_state["result_sig"]
    baseline_calculation = copy.deepcopy(at.session_state["calculation_record"])

    # Keep the PR-04 real-wall regression single-tube. PR-04B separately owns the
    # subdivision/global-override conflict and its error precedence.
    _set(at, ("number_input", "torsion_tef", 150.0))
    _calculate(at)

    assert not at.exception
    assert project_io.result_sha256(at.session_state["results"]) == (
        baseline_result_hash
    )
    assert at.session_state["result_sig"] == baseline_signature
    assert at.session_state["calculation_record"] == baseline_calculation
    assert at.session_state["_latest_inputs"]["signature"] != baseline_signature
    assert at.session_state["_latest_inputs"]["torsion_tef"] == pytest.approx(150.0)
    assert at.session_state["result_input_snapshot"]["torsion_tef"] == pytest.approx(
        0.0
    )
    assert (
        at.session_state["results"]["torsion"]["tube"]["tef_selection"]
        == "real-wall cap"
    )
    assert (
        at.session_state["_case_error"]
        == "Calculation blocked: tef override 150 mm exceeds the nearest real wall "
        "thickness 100 mm."
    )
    assert any(
        "exceeds the nearest real wall thickness" in item.value
        for item in at.error
    )


def test_app_torsion_gamma_ct_defaults_follow_method_until_user_edit():
    at = _fresh()
    at.run()
    assert at.session_state["torsion_gamma_ct"] == pytest.approx(1.70)

    _set(at, ("selectbox", "torsion_method", codes.EC2_2005.label))
    assert at.session_state["torsion_gamma_ct"] == pytest.approx(1.50)

    _set(at, ("number_input", "torsion_gamma_ct", 2.0))
    _set(at, ("selectbox", "torsion_method", codes.EC2_2005_DKNA.label))
    assert at.session_state["torsion_gamma_ct"] == pytest.approx(2.0)


def test_app_torsion_rejects_injected_numpy_boolean_gamma_ct():
    at = _fresh()
    at.session_state["torsion_on"] = True
    at.session_state["_torsion_gamma_ct_default_method"] = (
        codes.EC2_2005_DKNA.label
    )
    at.session_state["_torsion_gamma_ct_uses_method_default"] = True
    at.session_state["torsion_method"] = codes.EC2_2005.label
    at.session_state["torsion_gamma_ct"] = np.bool_(True)

    at.run()

    assert not at.exception
    assert at.session_state["torsion_gamma_ct"] is None
    assert (
        at.session_state["_torsion_gamma_ct_default_method"]
        == codes.EC2_2005.label
    )
    assert at.session_state["_torsion_gamma_ct_uses_method_default"] is False
    assert any(
        "gamma_ct must be a positive finite real number" in item.value
        for item in at.error
    )


def test_app_torsion_uses_final_material_factors():
    at = _fresh()
    at.run()
    _set(
        at,
        ("number_input", "conc_gamma_c", 1.80),
        ("number_input", "mild_gamma_y", 1.35),
        ("checkbox", "torsion_on", True),
        ("number_input", "torsion_gamma_ct", 2.0),
        ("number_input", "torsion_T", 40.0),
    )
    _enable_shared_links(at)
    _calculate(at)
    assert not at.exception
    t = at.session_state["results"]["torsion"]
    assert t["gamma_c"] == pytest.approx(1.80)
    assert t["fcd"] == pytest.approx(
        at.session_state["conc_alpha_cc"]
        * at.session_state["conc_fck"] / 1.80
    )
    assert t["gamma_s"] == pytest.approx(1.35)
    assert t["fywd"] == pytest.approx(at.session_state["shear_fywk"] / 1.35)
    assert t["gamma_ct"] == pytest.approx(2.0)
    assert t["fctd"] == pytest.approx(t["fctk_005"] / 2.0)


def test_torsion_gamma_ct_change_marks_results_stale_and_recalculates():
    at = _fresh()
    at.run()
    _set(
        at,
        ("checkbox", "torsion_on", True),
        ("number_input", "torsion_T", 28.0),
    )
    _enable_shared_links(at)
    _calculate(at)
    old_signature = at.session_state["result_sig"]
    initial = at.session_state["results"]["torsion"]
    assert initial["gamma_ct"] == pytest.approx(1.70)
    assert initial["trd_c"] == pytest.approx(
        2.0 * initial["tube"]["Ak"] * (initial["tube"]["tef"] / 1000.0)
        * initial["fctd"] * 1000.0
    )

    _goto_page(at, "Inputs")
    _set(at, ("number_input", "torsion_gamma_ct", 2.0))
    assert at.session_state["_latest_inputs"]["signature"] != old_signature
    assert at.session_state["result_sig"] == old_signature

    _calculate(at)
    result = at.session_state["results"]["torsion"]
    assert result["gamma_ct"] == pytest.approx(2.0)
    assert result["trd_c"] == pytest.approx(
        2.0 * result["tube"]["Ak"] * (result["tube"]["tef"] / 1000.0)
        * result["fctd"] * 1000.0
    )


def test_shared_link_authority_change_marks_torsion_stale_and_recalculates():
    at = _fresh()
    at.run()
    _set(
        at,
        ("checkbox", "torsion_on", True),
        ("number_input", "torsion_T", 28.0),
    )
    _enable_shared_links(at)
    _calculate(at)
    old_signature = at.session_state["result_sig"]
    assert at.session_state["results"]["torsion"][
        "full_resistance_assessed"
    ] is True

    _goto_page(at, "Inputs")
    _set(at, ("checkbox", "shear_links", False))
    assert at.session_state["_latest_inputs"]["signature"] != old_signature
    assert at.session_state["result_sig"] == old_signature
    assert at.session_state["results"]["torsion"][
        "full_resistance_assessed"
    ] is True

    _calculate(at)
    result = at.session_state["results"]["torsion"]
    assert result["closed_links_present"] is False
    assert result["full_resistance_assessed"] is False
    assert result["assessment_reason"] == "closed_links_not_present"
    assert result["trd"] is None
    assert result["util"] is None


def test_app_torsion_view_renders():
    at = _fresh()
    at.run()
    at.checkbox(key="torsion_on").set_value(True).run()
    _enable_shared_links(at)
    _set_and_click(at, "calculate", ("number_input", "torsion_T", 30.0))
    _select_view(at, "Torsion")
    assert not at.exception
    labels = [m.label for m in at.metric]
    assert any("Utilisation" in lbl for lbl in labels)
    assert any("T_{Rd" in lbl for lbl in labels)
    captions = " ".join(item.value for item in at.caption)
    assert "actual direct gamma_ct input is used" in captions
    assert "1.700" in captions


def _subdivided(at, b0=300.0, h0=600.0, b1=1000.0, h1=200.0, T=40.0):
    _apply_t_section(at, bf=b1, hf=h1, bw=b0, hw=h0)
    _set(at, ("checkbox", "torsion_on", True))
    _enable_shared_links(at)
    _set(
        at,
        ("number_input", "torsion_T", T),
        ("checkbox", "torsion_subdivide", True),
    )  # subdivision reveals the positioned sub-rectangle inputs
    _set(
        at,
        ("number_input", "torsion_sub_x0", 0.0),
        ("number_input", "torsion_sub_y0", -h1 / 2.0),
        ("number_input", "torsion_sub_b0", b0),
        ("number_input", "torsion_sub_h0", h0),
        ("number_input", "torsion_sub_x1", 0.0),
        ("number_input", "torsion_sub_y1", h0 / 2.0),
        ("number_input", "torsion_sub_b1", b1),
        ("number_input", "torsion_sub_h1", h1),
    )
    return at


def test_app_torsion_subdivided_sums_capacities():
    at = _fresh(); at.run(); _subdivided(at)
    _calculate(at)
    assert not at.exception
    t = at.session_state["results"]["torsion"]
    assert t["subdivided"] and len(t["subtubes"]) == 2
    assert t["trd"] == pytest.approx(sum(s["trd"] for s in t["subtubes"]))
    assert sum(s["t_ed"] for s in t["subtubes"]) == pytest.approx(40.0)   # TEd conserved
    # P1: TEd is split by stiffness not capacity, so the governing utilisation is the
    # WORST sub-tube (max TEd_i/TRd_i), never the pooled TEd/sum(TRd_i).
    assert t["util"] == pytest.approx(max(s["util"] for s in t["subtubes"]))
    assert t["util"] >= 40.0 / t["trd"] - 1e-9
    assert t["governing_sub"] == max(range(len(t["subtubes"])),
                                     key=lambda i: t["subtubes"][i]["util"])
    assert t["primary"]["t_ed"] == t["subtubes"][0]["t_ed"]              # web is primary


def test_app_torsion_subdivided_without_links_withholds_capacity_sum():
    at = _fresh()
    at.run()
    _subdivided(at)
    _set(at, ("checkbox", "shear_links", False))
    _calculate(at)

    assert not at.exception
    torsion_result = at.session_state["results"]["torsion"]
    assert torsion_result["subdivided"] is True
    assert len(torsion_result["subtubes"]) == 2
    assert torsion_result["tube_valid"] is True
    assert torsion_result["closed_links_present"] is False
    assert torsion_result["full_resistance_assessed"] is False
    assert torsion_result["assessment_reason"] == "closed_links_not_present"
    assert torsion_result["valid"] is False
    assert torsion_result["trd"] is None
    assert torsion_result["util"] is None
    assert torsion_result["governing_sub"] is None
    assert sum(
        sub["t_ed"] for sub in torsion_result["subtubes"]
    ) == pytest.approx(40.0)
    assert all(
        sub["tube_valid"] is True
        and sub["full_resistance_assessed"] is False
        and sub["trd"] is None
        and sub["util"] is None
        and sub["governs"] is None
        and sub["trd_max"] > 0.0
        and sub["trd_c"] > 0.0
        for sub in torsion_result["subtubes"]
    )

    _select_view(at, "Torsion")
    assert any("NOT ASSESSED" in item.value for item in at.warning)
    assert not any("Utilisation" in metric.label for metric in at.metric)
    assert any(
        "No sum of full capacities" in item.value for item in at.caption
    )


def test_app_subdivision_override_blocks_and_preserves_completed_result():
    import copy
    import project_io

    at = _fresh()
    at.run()
    _subdivided(at)
    _calculate(at)
    assert not at.exception
    baseline = at.session_state["results"]["torsion"]
    assert baseline["valid"] is True
    assert all(not item["tube"]["tef_user"] for item in baseline["subtubes"])
    baseline_result_hash = project_io.result_sha256(at.session_state["results"])
    baseline_signature = at.session_state["result_sig"]
    baseline_input_snapshot_hash = project_io.result_sha256(
        at.session_state["result_input_snapshot"]
    )
    baseline_calculation = copy.deepcopy(at.session_state["calculation_record"])

    _set(at, ("number_input", "torsion_tef", 25.0))
    _calculate(at)

    assert not at.exception
    assert project_io.result_sha256(at.session_state["results"]) == (
        baseline_result_hash
    )
    assert at.session_state["result_sig"] == baseline_signature
    assert project_io.result_sha256(
        at.session_state["result_input_snapshot"]
    ) == baseline_input_snapshot_hash
    assert at.session_state["calculation_record"] == baseline_calculation
    assert at.session_state["_latest_inputs"]["signature"] != baseline_signature
    assert at.session_state["result_input_snapshot"]["torsion_tef"] == 0.0
    assert at.session_state["_latest_inputs"]["torsion_tef"] == 25.0
    assert at.session_state["_case_error"] == (
        "Calculation blocked: torsion wall-thickness override must be 0 "
        "(automatic per sub-tube) when torsion subdivision is enabled."
    )
    assert any("automatic per sub-tube" in item.value for item in at.error)


def test_app_compound_torsion_requires_subdivision():
    at = _fresh()
    at.run()
    _apply_t_section(at)
    at.checkbox(key="torsion_on").set_value(True).run()
    _enable_shared_links(at)
    _set_and_click(at, "calculate", ("number_input", "torsion_T", 20.0))
    assert not at.exception
    t = at.session_state["results"]["torsion"]
    assert t["compound_detected"] is True
    assert t["valid"] is False
    assert t["reason"] == "compound outline requires subdivision"
    _select_view(at, "Torsion")
    assert any("compound" in w.value and "Subdivide" in w.value
               for w in at.warning)


def test_app_compound_torsion_is_valid_after_subdivision():
    at = _fresh()
    at.run()
    _subdivided(at)
    _calculate(at)
    assert not at.exception
    t = at.session_state["results"]["torsion"]
    assert t["compound_detected"] is True
    assert t["subdivided"] is True
    assert t["valid"] is True


def test_app_invalid_subtube_partition_withholds_torsion_verdict():
    at = _fresh()
    at.run()
    _subdivided(at)
    # Shift the web so part of it lies outside the actual T-section.
    _set_and_click(
        at, "calculate", ("number_input", "torsion_sub_x0", 100.0)
    )
    assert not at.exception
    t = at.session_state["results"]["torsion"]
    assert t["subdivision_requested"] is True
    assert t["subdivision_valid"] is False
    assert t["subdivided"] is False
    assert t["valid"] is False
    assert t["subtubes"] is None
    assert t["reason"].startswith("invalid sub-tube partition:")
    _select_view(at, "Torsion")
    assert any("do not form the concrete section" in w.value for w in at.warning)
    assert not any(
        m.label == r"Utilisation $T_{Ed}/T_{Rd}$" for m in at.metric
    )


def test_app_torsion_subdivided_distributes_by_stiffness():
    at = _fresh(); at.run(); _subdivided(at)
    _calculate(at)
    t = at.session_state["results"]["torsion"]
    cw = torsion.rectangle_torsion_constant(0.3, 0.6)
    cf = torsion.rectangle_torsion_constant(1.0, 0.2)
    web, flange = t["subtubes"]
    assert web["t_ed"] / flange["t_ed"] == pytest.approx(cw / cf, rel=1e-6)


def test_app_torsion_subdivided_view_renders():
    at = _fresh(); at.run(); _subdivided(at)
    _calculate(at)
    _select_view(at, "Torsion")
    assert not at.exception
    labels = [m.label for m in at.metric]
    assert any("T_{Rd" in lbl for lbl in labels)


def test_app_torsion_subdivided_uses_the_shared_member_angle():
    # One physical compression-strut band applies to the live shear and every
    # torsion sub-tube, so all reported sub-tubes use the selected member angle.
    at = _fresh(); at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    at.checkbox(key="shear_links").set_value(True).run()
    _set(at, ("number_input", "shear_V", 150.0))
    _subdivided(at, T=40.0)
    _set_and_click(
        at,
        "calculate",
        ("number_input", "strut_cot_min", 1.35),
        ("number_input", "strut_cot_max", 2.0),
    )
    assert not at.exception
    t = at.session_state["results"]["torsion"]
    assert t["theta_mode"] == "utilisation"
    cots = [s["cot"] for s in t["subtubes"]]
    assert all(cot == pytest.approx(t["cot"]) for cot in cots)
    _select_view(at, "Torsion")
    caps = " ".join(c.value for c in at.caption)
    assert "ONE member strut angle" in caps
    assert "each sub-tube is at its OWN" not in caps


def test_app_torsion_subdivided_combined_pairs_web():
    # The combined V+T crushing must use the WEB sub-tube's torsion SHARE, not full TEd.
    at = _fresh(); at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    _set(
        at,
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 150.0),
    )
    _subdivided(at)
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "combined_on", True),
        ("number_input", "pl_Mx", 100.0),
    )
    assert not at.exception
    to = at.session_state["results"]["torsion"]
    inter = to["interaction"]
    assert inter["t_ed"] == pytest.approx(to["subtubes"][0]["t_ed"])     # web share
    assert inter["t_ed"] < to["t_ed"]                                    # < full TEd


def test_app_combined_shear_torsion_interaction():
    # With both shear links and torsion on, the 6.29 crushing interaction appears.
    at = _fresh()
    at.run()
    _set(
        at,
        ("checkbox", "shear_on", True),
        ("checkbox", "torsion_on", True),
    )
    _set_and_click(
        at,
        "calculate",
        ("checkbox", "shear_links", True),
        ("number_input", "shear_V", 150.0),
        ("number_input", "torsion_T", 40.0),
    )
    assert not at.exception
    inter = at.session_state["results"]["torsion"]["interaction"]
    assert inter["value"] == pytest.approx(
        inter["t_ed"] / inter["trd_max"] + inter["v_ed"] / inter["vrd_max"])
    assert inter["value"] == pytest.approx(
        inter["torsion_ratio"] + inter["shear_ratio"]
    )
    # ONE member strut angle (6.3.2(2)) applies within each mandatory face
    # candidate. Different check domains may independently govern on different
    # faces, so their aggregate representatives need not have the same angle.
    r = at.session_state["results"]
    primary = r["torsion"]["primary"]
    assert primary["steel_resistance"]["trd_s"] == pytest.approx(
        primary["trd_s"]
    )
    assert primary["strut_resistance"]["trd_max"] == pytest.approx(
        primary["trd_max"]
    )
    assert primary["resistance_selection"]["resistance"] == pytest.approx(
        primary["trd"]
    )
    assert primary["longitudinal_reinforcement"]["asl_required_mm2"] == (
        pytest.approx(primary["asl_req"])
    )
    assert r["torsion"]["torque_distribution"]["applied_torque"] == (
        pytest.approx(r["torsion"]["t_ed"])
    )
    assert r["shear"]["links"]["res"]["tan"] == pytest.approx(
        1.0 / r["shear"]["links"]["res"]["cot"]
    )
    assert r["shear"]["links"]["member_angle_selection"]["samples"] == 1501
    checked = 0
    for candidate in r["shear"]["face_candidates"]:
        candidate_torsion = candidate["torsion"]
        candidate_inter = candidate_torsion.get("interaction") or {}
        if not candidate_inter.get("valid"):
            continue
        checked += 1
        assert candidate_inter["cot"] == pytest.approx(
            candidate["shear"]["links"]["res"]["cot"]
        )
        assert candidate_inter["cot"] == pytest.approx(candidate_torsion["cot"])
    assert checked == 2

    domains = r["shear"]["governing_domains"]
    assert domains["shear"]["face"] == r["shear"]["governing_face"]
    assert domains["vt"]["face"] == r["torsion"]["directional_governing_face"]
    assert domains["vt"]["cot"] == pytest.approx(inter["cot"])
    assert "combined" not in domains


def test_combined_vrdmax_uses_shear_method_not_torsion():
    # The combined VRd,max must follow the SHEAR method and lever arm, not the torsion
    # code / 0.9d. Changing only the torsion method moves TRd,max but leaves VRd,max.
    # The shared strut-angle range is pinned to one cot so the member angle cannot move
    # between the two runs (the torsion method shifts nu_t and hence the chosen
    # angle, which would move VRd,max through theta rather than through the method).
    def inter(torsion_method):
        at = _fresh()
        at.run()
        _set(
            at,
            ("checkbox", "shear_on", True),
            ("checkbox", "torsion_on", True),
        )
        _set(
            at,
            ("checkbox", "shear_links", True),
            ("number_input", "shear_V", 150.0),
            ("number_input", "torsion_T", 40.0),
        )
        pinned = [
            ("number_input", "strut_cot_min", 2.0),
            ("number_input", "strut_cot_max", 2.0),
        ]
        pinned.append(("selectbox", "torsion_method", torsion_method))
        _set_and_click(at, "calculate", *pinned)
        assert not at.exception
        return at.session_state["results"]["torsion"]["interaction"]

    a = inter(codes.EC2_2005_DKNA.label)
    b = inter(codes.EC2_2005.label)
    assert a["cot"] == pytest.approx(2.0) and b["cot"] == pytest.approx(2.0)
    assert a["vrd_max"] == pytest.approx(b["vrd_max"])   # shear-driven, unchanged
    assert a["trd_max"] != pytest.approx(b["trd_max"])   # torsion-driven, changed


def test_app_torsion_only_axial_input_enabled():
    # In an Elastic-only torsion check the Plastic case table remains editable because
    # its axial force drives alpha_cw. Compression must raise TRd,max.
    at = _fresh()
    at.run()
    _set(
        at,
        ("radio", "mode", "Elastic"),
        ("checkbox", "torsion_on", True),
    )
    _enable_shared_links(at)
    _set(at, ("number_input", "torsion_T", 30.0))
    goto_input_stage(at, "Loads")
    assert any(frame.key == "plastic_cases_editor" for frame in at.dataframe)
    _calculate(at)
    base = at.session_state["results"]["torsion"]["trd_max"]
    _set_and_click(
        at, "calculate", ("number_input", "pl_P", -1500.0)
    )  # compression (N tension +)
    assert not at.exception
    t = at.session_state["results"]["torsion"]
    assert t["alpha_cw"] > 1.0                              # compression -> alpha_cw up
    assert t["trd_max"] > base


def test_app_torsion_multi_void_rejected():
    import pandas as pd
    at = _fresh()
    at.run()
    # two separate triangular voids in the default rectangle (blank-row separated)
    at.session_state["hole_base"] = pd.DataFrame({
        "x (mm)": [-100.0, -40.0, -70.0, None, 40.0, 100.0, 70.0],
        "y (mm)": [-50.0, -50.0, 50.0, None, -50.0, -50.0, 50.0]})
    at.checkbox(key="torsion_on").set_value(True).run()
    _enable_shared_links(at)
    _set_and_click(at, "calculate", ("number_input", "torsion_T", 20.0))
    assert not at.exception
    assert not at.session_state["results"]["torsion"]["valid"]
    _select_view(at, "Torsion")
    assert any("multi-cell" in w.value for w in at.warning)


def test_app_torsion_uses_the_shared_stirrup():
    # The torsion tube reads the shared Links/stirrups definition (shear_link_*), not
    # its own inputs; the stirrup field is enabled for a torsion-only run and a bigger
    # bar raises TRd,s.
    at = _fresh()
    at.run()
    at.checkbox(key="torsion_on").set_value(True).run()
    assert at.number_input(key="shear_link_dia").disabled
    assert at.number_input(key="shear_link_s").disabled
    _enable_shared_links(at)
    assert not at.number_input(key="shear_link_dia").disabled
    assert not at.number_input(key="shear_link_s").disabled
    assert at.number_input(key="shear_vx_link_legs").disabled
    assert at.number_input(key="shear_vy_link_legs").disabled
    _set_and_click(
        at,
        "calculate",
        ("number_input", "torsion_T", 40.0),
        ("number_input", "shear_link_dia", 10.0),
    )
    t10 = at.session_state["results"]["torsion"]
    assert t10["dia"] == pytest.approx(10.0)
    _set_and_click(
        at, "calculate", ("number_input", "shear_link_dia", 16.0)
    )
    t16 = at.session_state["results"]["torsion"]
    assert t16["dia"] == pytest.approx(16.0)
    assert t16["trd_s"] > t10["trd_s"]                          # bigger stirrup


def test_app_torsion_longitudinal_uses_mild_fyd():
    at = _fresh()
    at.run()
    at.checkbox(key="torsion_on").set_value(True).run()
    _enable_shared_links(at)
    _set_and_click(at, "calculate", ("number_input", "torsion_T", 40.0))
    t = at.session_state["results"]["torsion"]
    fytk = at.session_state["mild_fytk"]
    gy = at.session_state["mild_gamma_y"]
    assert t["fyd_long"] == pytest.approx(fytk / gy)


def test_app_torsion_prestress_raises_alpha_cw():
    # F1: the tendon precompression enters sigma_cp, so alpha_cw rises above 1.0
    # (EN 1992-1-1 6.11N) and TRd,max (6.30) with it.
    at = _fresh()
    at.run()
    at.session_state["_qs_open"] = True
    at.run()
    _set_and_click(
        at,
        "qs_apply",
        ("number_input", "tnd_n", 4),
        ("number_input", "tnd_a", 1000.0),
    )
    _set(
        at,
        ("number_input", "pre_IS", 3.0),
        ("checkbox", "torsion_on", True),
    )
    _enable_shared_links(at)
    _set_and_click(at, "calculate", ("number_input", "torsion_T", 20.0))
    assert not at.exception
    t = at.session_state["results"]["torsion"]
    assert t["n_prestress"] > 0.0
    assert t["sigma_cp"] > 0.0
    assert t["alpha_cw"] > 1.0                          # prestress credit (was 1.0)


def test_app_min_reinf_screen_evaluated():
    # F7: EN 1992-1-1 6.3.2(5) Eq 6.31 screen TEd/TRd,c + VEd/VRd,c <= 1, evaluated
    # when both the shear and torsion checks are on (needs VRd,c).
    at = _fresh()
    at.run()
    _set(
        at,
        ("checkbox", "shear_on", True),
        ("checkbox", "torsion_on", True),
    )
    _set_and_click(
        at,
        "calculate",
        ("number_input", "shear_V", 30.0),
        ("number_input", "torsion_T", 15.0),
    )
    assert not at.exception
    mr = at.session_state["results"]["torsion"]["min_reinf"]
    assert mr["applicable"] is True
    assert mr["value"] == pytest.approx(mr["t_ed"] / mr["trd_c"]
                                        + mr["v_ed"] / mr["vrd_c"])
    assert mr["ok"] is (mr["value"] <= 1.0 + 1e-9)
    assert mr["solid"] is True                          # default section has no void
    _select_view(at, "Torsion")
    assert not at.exception


def test_app_min_reinf_screen_needs_shear():
    # Without the shear check there is no VRd,c, so the screen is not applicable.
    at = _fresh()
    at.run()
    at.checkbox(key="torsion_on").set_value(True).run()
    _set_and_click(at, "calculate", ("number_input", "torsion_T", 15.0))
    mr = at.session_state["results"]["torsion"]["min_reinf"]
    assert mr["applicable"] is False
    _select_view(at, "Torsion")
    assert not at.exception


def test_app_min_reinf_screen_over_limit():
    # A large VEd + TEd pushes the sum above 1: designed reinforcement is required.
    at = _fresh()
    at.run()
    _set(
        at,
        ("checkbox", "shear_on", True),
        ("checkbox", "torsion_on", True),
    )
    _set_and_click(
        at,
        "calculate",
        ("number_input", "shear_V", 200.0),
        ("number_input", "torsion_T", 60.0),
    )
    mr = at.session_state["results"]["torsion"]["min_reinf"]
    assert mr["applicable"] is True
    assert mr["value"] > 1.0
    assert mr["ok"] is False


def test_biaxial_torsion_retains_and_presents_directional_631_screens():
    at = _fresh()
    at.run()
    _set(
        at,
        ("checkbox", "shear_on", True),
        ("checkbox", "torsion_on", True),
    )
    _enable_shared_links(at)
    _set_and_click(
        at,
        "calculate",
        ("number_input", "shear_Vx", 20.0),
        ("number_input", "shear_Vy", 30.0),
        ("number_input", "torsion_T", 15.0),
    )

    assert not at.exception
    directional = at.session_state["results"]["torsion"][
        "directional_interactions"
    ]
    assert set(directional) == {"vx", "vy"}
    for item in directional.values():
        mr = item["min_reinf"]
        assert mr["applicable"] is True
        assert mr["value"] == pytest.approx(
            mr["t_ed"] / mr["trd_c"] + mr["v_ed"] / mr["vrd_c"]
        )
        assert item["directional_min_reinf_governing_face"] in {
            "negative", "positive"
        }

    _select_view(at, "Torsion")
    table = next(
        frame.value for frame in at.dataframe
        if "Directional 6.31 screen" in frame.value.columns
    )
    assert set(table["Directional 6.31 screen"]) == {
        "Vx,Ed + TEd", "Vy,Ed + TEd"
    }
    assert set(table["Outcome"]) <= {
        "minimum sufficient", "designed reinforcement required"
    }


def test_app_torsion_is_saved_and_restored():
    import project_io
    at = _fresh()
    at.run()
    at.checkbox(key="torsion_on").set_value(True).run()
    _set(
        at,
        ("number_input", "torsion_T", 55.0),
        ("number_input", "torsion_gamma_ct", 2.0),
    )
    scalars = {k: at.session_state[k] for k in project_io.SCALAR_KEYS
               if k in at.session_state}
    tables = {k: at.session_state[k] for k in project_io.PROJECT_TABLE_KEYS
              if k in at.session_state}
    assert scalars["torsion_on"] is True and "torsion_T" not in scalars
    assert first_case_value(at, "torsion_T") == pytest.approx(55.0)
    at2 = _fresh()
    at2.run()
    at2.session_state["_pending_project"] = project_io.dump_project(tables, scalars)
    at2.run()
    assert not at2.exception
    assert at2.session_state["torsion_on"] is True
    assert at2.session_state["torsion_gamma_ct"] == pytest.approx(2.0)
    assert first_case_value(at2, "torsion_T") == pytest.approx(55.0)


def test_torsion_nu_v_detailing_allowance():
    # v0.64 / DK NA Figur 5.100 NA: with closed stirrups + distributed longitudinal
    # steel the torsion strut factor may be raised from nu_t to nu_v (floored).
    c = codes.EC2_2005_DKNA
    assert c.torsion_nu(35.0, closed_detailing=True) == pytest.approx(c.shear_nu1(35.0))
    assert c.torsion_nu(35.0, closed_detailing=True) > c.torsion_nu(35.0)   # raised
    # the recommended edition has a single nu; the flag is a no-op there.
    r = codes.EC2_2005
    assert r.torsion_nu(35.0, closed_detailing=True) == pytest.approx(r.torsion_nu(35.0))


def test_trd_max_respects_closed_detailing():
    from sector import torsion
    base = torsion.trd_max(35.0, codes.EC2_2005_DKNA, 0.1, 100.0, 1.0, 1.0)
    raised = torsion.trd_max(35.0, codes.EC2_2005_DKNA, 0.1, 100.0, 1.0, 1.0,
                             closed_detailing=True)
    assert raised > base


def test_app_torsion_nu_v_toggle_raises_trd_max():
    at = _fresh()
    at.run()
    at.checkbox(key="torsion_on").set_value(True).run()
    _enable_shared_links(at)
    _set_and_click(at, "calculate", ("number_input", "torsion_T", 30.0))
    base = at.session_state["results"]["torsion"]["trd_max"]
    _set_and_click(at, "calculate", ("checkbox", "torsion_nu_v", True))
    t = at.session_state["results"]["torsion"]
    assert t["nu_v_detailing"] is True
    assert t["trd_max"] > base


def test_app_torsion_out_of_default_range_warns_and_retains_verdict():
    at = _fresh()
    at.run()
    at.checkbox(key="torsion_on").set_value(True).run()
    _enable_shared_links(at)
    _set_and_click(
        at,
        "calculate",
        ("number_input", "torsion_T", 30.0),
        ("number_input", "strut_cot_max", 3.0),
    )
    assert not at.exception
    t = at.session_state["results"]["torsion"]
    assert t["out_of_limits"] is True
    assert "code_applicable" not in t
    _select_view(at, "Torsion")
    assert any("actual values are retained" in w.value.lower() for w in at.warning)
    util_metric = next(
        m for m in at.metric
        if m.label == r"Utilisation $T_{Ed}/T_{Rd}$"
    )
    assert util_metric.delta in {"PASS", "FAIL"}
