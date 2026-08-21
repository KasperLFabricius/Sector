import math
from dataclasses import replace

import numpy as np
import pytest

from app import fatigue_inputs
from sector import fatigue
from sector.design_standards import DesignBasisKey
from sector.section import Section


def _state(
    name,
    cycles,
    *,
    bar_long=(),
    bar_total=(),
    bar_design_total=(),
    concrete_long=(),
    concrete_total=(),
    concrete_design_total=(),
    design_action_factor=1.0,
    converged=True,
):
    return fatigue.FatigueBinState(
        name=name,
        description="",
        cycles=float(cycles),
        converged=converged,
        bar_stress_long_mpa=tuple(bar_long),
        bar_stress_total_mpa=tuple(bar_total),
        bar_stress_design_total_mpa=tuple(bar_design_total),
        bar_stress_fatigue_design_total_mpa=tuple(bar_design_total),
        concrete_compression_long_mpa=tuple(concrete_long),
        concrete_compression_total_mpa=tuple(concrete_total),
        concrete_compression_design_total_mpa=tuple(
            concrete_design_total
        ),
        design_action_factor=float(design_action_factor),
        elastic_result=None,
    )


def _steel_properties(
    element_id="R1",
    *,
    kind=fatigue.MILD,
    detail_id="F1",
    delta_sigma=160.0,
    fytk=500.0,
    fyck=500.0,
    diameter=16.0,
    bond_ratio=None,
    bond_diameter=None,
    screen_rule=None,
):
    return fatigue.ReinforcementFatigueProperties(
        element_id=element_id,
        kind=kind,
        detail_id=detail_id,
        diameter_mm=diameter,
        n_star=2.0e6,
        k1=5.0,
        k2=9.0,
        delta_sigma_rsk_mpa=delta_sigma,
        fytk_mpa=fytk,
        fyck_mpa=fyck,
        bond_ratio_xi=bond_ratio,
        bond_equivalent_diameter_mm=bond_diameter,
        simplified_screen_rule=screen_rule,
    )


def _section():
    return Section.from_polygon(
        corners=[
            (-0.20, -0.30),
            (0.20, -0.30),
            (0.20, 0.30),
            (-0.20, 0.30),
        ],
        bars_xy_area_mm2=[
            (0.0, -0.24, 804.0),
            (0.0, 0.24, 804.0),
        ],
    )


def test_steel_sn_curve_uses_the_correct_slope_on_each_side_of_knee():
    knee = 160.0 / 1.15

    at_knee = fatigue.steel_fatigue_life(
        knee,
        n_star=2.0e6,
        k1=5.0,
        k2=9.0,
        delta_sigma_rsk_mpa=160.0,
        gamma_s=1.15,
        gamma_ff=1.0,
    )
    above = fatigue.steel_fatigue_life(
        2.0 * knee,
        n_star=2.0e6,
        k1=5.0,
        k2=9.0,
        delta_sigma_rsk_mpa=160.0,
        gamma_s=1.15,
        gamma_ff=1.0,
    )
    below = fatigue.steel_fatigue_life(
        0.5 * knee,
        n_star=2.0e6,
        k1=5.0,
        k2=9.0,
        delta_sigma_rsk_mpa=160.0,
        gamma_s=1.15,
        gamma_ff=1.0,
    )

    assert at_knee.exponent == 5.0
    assert at_knee.cycles == pytest.approx(2.0e6)
    assert above.cycles == pytest.approx(2.0e6 / 2.0**5)
    assert below.exponent == 9.0
    assert below.cycles == pytest.approx(2.0e6 * 2.0**9)


def test_steel_sn_curve_applies_gamma_ff_and_handles_zero_range():
    reference = fatigue.steel_fatigue_life(
        80.0,
        n_star=2.0e6,
        k1=5.0,
        k2=9.0,
        delta_sigma_rsk_mpa=160.0,
        gamma_s=1.0,
        gamma_ff=1.0,
    )
    factored = fatigue.steel_fatigue_life(
        80.0,
        n_star=2.0e6,
        k1=5.0,
        k2=9.0,
        delta_sigma_rsk_mpa=160.0,
        gamma_s=1.0,
        gamma_ff=2.0,
    )
    zero = fatigue.steel_fatigue_life(
        0.0,
        n_star=2.0e6,
        k1=5.0,
        k2=9.0,
        delta_sigma_rsk_mpa=160.0,
        gamma_s=1.0,
        gamma_ff=1.0,
    )

    assert reference.cycles == pytest.approx(2.0e6 * 2.0**9)
    assert factored.cycles == pytest.approx(2.0e6)
    assert math.isinf(zero.cycles)
    assert math.isinf(zero.log10_cycles)


def test_steel_sn_curve_retains_extreme_life_without_overflow():
    life = fatigue.steel_fatigue_life(
        1.0e-100,
        n_star=2.0e6,
        k1=5.0,
        k2=9.0,
        delta_sigma_rsk_mpa=160.0,
        gamma_s=1.0,
        gamma_ff=1.0,
    )

    assert math.isinf(life.cycles)
    assert math.isfinite(life.log10_cycles)
    assert life.log10_cycles > 900.0


def test_concrete_fatigue_strength_matches_2005_and_2023_expressions():
    old = fatigue.ConcreteFatigueProperties(
        edition="DS/EN 1992-1-1:2005",
        fck_mpa=40.0,
        gamma_c=1.5,
        beta_cc_t0=0.9,
        alpha_cc=1.0,
        k1=0.85,
    )
    new = fatigue.ConcreteFatigueProperties(
        edition="DS/EN 1992-1-1:2023",
        fck_mpa=40.0,
        gamma_c=1.5,
        beta_cc_t0=0.9,
    )
    high_strength = fatigue.ConcreteFatigueProperties(
        edition="2023",
        fck_mpa=80.0,
        gamma_c=1.5,
        beta_cc_t0=1.0,
    )

    assert fatigue.concrete_fatigue_strength(old) == pytest.approx(
        0.85 * 0.9 * 40.0 / 1.5 * (1.0 - 40.0 / 250.0)
    )
    assert fatigue.concrete_fatigue_strength(new) == pytest.approx(
        0.9 * 40.0 / 1.5 * 0.8
    )
    eta = (40.0 / 80.0) ** (1.0 / 3.0)
    assert fatigue.concrete_fatigue_strength(high_strength) == pytest.approx(
        80.0 / 1.5 * min(0.85 * eta, 0.8)
    )


def test_concrete_fatigue_strength_retains_only_the_selected_edition_operands():
    old = fatigue.concrete_fatigue_strength_result(
        fatigue.ConcreteFatigueProperties(
            edition="2005",
            fck_mpa=40.0,
            gamma_c=1.5,
            beta_cc_t0=0.9,
            alpha_cc=0.95,
            k1=0.85,
        )
    )
    new = fatigue.concrete_fatigue_strength_result(
        fatigue.ConcreteFatigueProperties(
            edition="2023",
            fck_mpa=80.0,
            gamma_c=1.5,
            beta_cc_t0=0.9,
        )
    )
    capped = fatigue.concrete_fatigue_strength_result(
        fatigue.ConcreteFatigueProperties(
            edition="2023",
            fck_mpa=30.0,
            gamma_c=1.5,
            beta_cc_t0=1.0,
        )
    )

    assert old.edition == fatigue.EC2_2005
    assert old.base_strength_mpa == pytest.approx(0.9 * 0.95 * 40.0 / 1.5)
    assert old.high_strength_reduction == pytest.approx(1.0 - 40.0 / 250.0)
    assert old.eta_cc_raw is None
    assert old.eta_cc_cap is None
    assert old.eta_cc is None
    assert old.eta_cc_fat_raw is None
    assert old.eta_cc_fat_cap is None
    assert old.eta_cc_fat is None
    assert old.high_strength_reduction is not None
    assert old.fcd_fat_mpa == pytest.approx(
        0.85 * old.base_strength_mpa * old.high_strength_reduction
    )

    expected_eta = (40.0 / 80.0) ** (1.0 / 3.0)
    assert new.edition == fatigue.EC2_2023
    assert new.base_strength_mpa == pytest.approx(0.9 * 80.0 / 1.5)
    assert new.alpha_cc is None
    assert new.k1 is None
    assert new.high_strength_reduction is None
    assert new.eta_cc_raw == pytest.approx(expected_eta)
    assert new.eta_cc_cap == pytest.approx(1.0)
    assert new.eta_cc == pytest.approx(expected_eta)
    assert new.eta_cc_fat_raw == pytest.approx(0.85 * expected_eta)
    assert new.eta_cc_fat_cap == pytest.approx(0.8)
    assert new.eta_cc_fat == pytest.approx(min(0.85 * expected_eta, 0.8))
    assert new.eta_cc_fat is not None
    assert new.fcd_fat_mpa == pytest.approx(
        new.base_strength_mpa * new.eta_cc_fat
    )
    assert capped.eta_cc_raw is not None
    assert capped.eta_cc_cap is not None
    assert capped.eta_cc_fat_raw is not None
    assert capped.eta_cc_fat_cap is not None
    assert capped.eta_cc_raw > capped.eta_cc_cap
    assert capped.eta_cc == pytest.approx(capped.eta_cc_cap)
    assert capped.eta_cc_fat_raw > capped.eta_cc_fat_cap
    assert capped.eta_cc_fat == pytest.approx(capped.eta_cc_fat_cap)


def test_concrete_life_matches_corrected_bridge_and_2023_equation():
    life = fatigue.concrete_fatigue_life(
        10.0,
        4.0,
        fcd_fat_mpa=20.0,
        c=14.0,
    )
    expected_log10 = 14.0 * (1.0 - 10.0 / 20.0) / math.sqrt(1.0 - 0.4)

    assert life.log10_cycles == pytest.approx(expected_log10)
    assert life.cycles == pytest.approx(10.0**expected_log10)


def test_concrete_life_is_infinite_without_a_cyclic_range():
    zero = fatigue.concrete_fatigue_life(
        0.0, 0.0, fcd_fat_mpa=20.0
    )
    constant = fatigue.concrete_fatigue_life(
        8.0, 8.0, fcd_fat_mpa=20.0
    )

    assert math.isinf(zero.cycles)
    assert math.isinf(constant.cycles)


def test_concrete_damage_equivalent_criterion_matches_2005_and_2023_formula():
    utilisation = fatigue.concrete_equivalent_utilisation(
        10.0,
        4.0,
        fcd_fat_mpa=20.0,
    )

    assert utilisation == pytest.approx(
        10.0 / 20.0 + 0.43 * math.sqrt(1.0 - 4.0 / 10.0)
    )


def test_concrete_equivalent_method_ignores_cycles_and_reports_each_pair():
    vertices = np.asarray([(0.0, 0.0)], dtype=float)
    states = (
        _state(
            "EQ1",
            1.0,
            concrete_long=(4.0,),
            concrete_total=(10.0,),
        ),
        _state(
            "EQ2",
            1.0e12,
            concrete_long=(8.0,),
            concrete_total=(9.0,),
        ),
    )
    properties = fatigue.ConcreteFatigueProperties(
        edition="2023",
        fck_mpa=37.5,
        gamma_c=1.5,
        beta_cc_t0=1.0,
        method=fatigue.CONCRETE_EQUIVALENT,
    )

    result = fatigue.assess_concrete_spectrum(
        vertices,
        states,
        properties,
        gamma_ff=1.0,
    )[0]

    expected = [
        fatigue.concrete_equivalent_utilisation(
            max(item.concrete_compression_long_mpa[0],
                item.concrete_compression_total_mpa[0]),
            min(item.concrete_compression_long_mpa[0],
                item.concrete_compression_total_mpa[0]),
            fcd_fat_mpa=fatigue.concrete_fatigue_strength(properties),
        )
        for item in states
    ]
    assert [item.damage for item in result.bins] == [0.0, 0.0]
    assert result.equivalent_utilisation == pytest.approx(max(expected))
    assert result.utilisation == pytest.approx(max(expected))
    assert result.governing_equivalent_bin == (
        states[int(np.argmax(expected))].name
    )
    assert result.governing_criterion == "Equivalent amplitude"
    assert result.governing_bin == result.governing_equivalent_bin
    governing = next(
        item for item in result.bins
        if item.bin_name == result.governing_bin
    )
    assert governing.life_branch == "damage-equivalent criterion"
    assert governing.life_coefficient is None
    assert governing.life_range_term == pytest.approx(
        math.sqrt(1.0 - governing.stress_ratio)
    )


def test_equivalent_method_retains_compressive_stress_when_it_is_larger(
    monkeypatch,
):
    monkeypatch.setattr(
        fatigue,
        "concrete_equivalent_utilisation",
        lambda *_args, **_kwargs: 0.1,
    )
    properties = fatigue.ConcreteFatigueProperties(
        edition="2023",
        fck_mpa=37.5,
        gamma_c=1.5,
        beta_cc_t0=1.0,
        method=fatigue.CONCRETE_EQUIVALENT,
    )

    result = fatigue.assess_concrete_spectrum(
        np.asarray([(0.0, 0.0)]),
        (
            _state(
                "stress governs",
                1.0e6,
                concrete_long=(4.0,),
                concrete_total=(10.0,),
            ),
        ),
        properties,
        gamma_ff=1.0,
    )[0]

    assert result.stress_utilisation == pytest.approx(0.5)
    assert result.equivalent_utilisation == pytest.approx(0.1)
    assert result.utilisation == pytest.approx(0.5)
    assert result.governing_criterion == "compressive stress"
    assert result.governing_bin == "stress governs"


def test_equivalent_criterion_is_selected_on_an_exact_stress_tie():
    properties = fatigue.ConcreteFatigueProperties(
        edition="2023",
        fck_mpa=37.5,
        gamma_c=1.5,
        beta_cc_t0=1.0,
        method=fatigue.CONCRETE_EQUIVALENT,
    )

    result = fatigue.assess_concrete_spectrum(
        np.asarray([(0.0, 0.0)]),
        (
            _state(
                "constant compression",
                1.0e6,
                concrete_long=(8.0,),
                concrete_total=(8.0,),
            ),
        ),
        properties,
        gamma_ff=1.0,
    )[0]

    assert result.equivalent_utilisation == pytest.approx(
        result.stress_utilisation
    )
    assert result.governing_criterion == "Equivalent amplitude"
    assert result.governing_bin == "constant compression"
    tied_bin = result.bins[0]
    assert tied_bin.compression_min_state == "long-term"
    assert tied_bin.compression_max_state == "action-factored total"


def test_reinforcement_damage_and_yield_are_accumulated_per_element():
    states = (
        _state(
            "B1",
            1.0e5,
            bar_long=(100.0, -350.0),
            bar_total=(180.0, -450.0),
        ),
        _state(
            "B2",
            2.0e5,
            bar_long=(100.0, -350.0),
            bar_total=(140.0, -390.0),
        ),
    )
    properties = (
        _steel_properties("R1"),
        _steel_properties("R2", fytk=500.0, fyck=400.0),
    )

    results = fatigue.assess_reinforcement_spectrum(
        properties,
        states,
        gamma_s=1.0,
        gamma_ff=1.0,
    )

    assert len(results) == 2
    assert results[0].damage == pytest.approx(
        sum(item.damage for item in results[0].bins)
    )
    assert results[0].bins[0].stress_range_mpa == 80.0
    tension_bin = results[0].bins[0]
    assert tension_bin.yield_design_total_check is not None
    assert tension_bin.yield_design_total_check.branch == "tension fytk"
    assert tension_bin.yield_design_total_check.characteristic_strength_mpa == 500.0
    assert results[1].yield_utilisation == pytest.approx(450.0 / 400.0)
    assert results[1].governing_yield_bin == "B1"
    assert results[1].governing_criterion == "yield/proof stress"
    assert results[1].governing_bin == "B1"
    compression_bin = results[1].bins[0]
    assert compression_bin.yield_long_check is not None
    assert compression_bin.yield_design_total_check is not None
    assert compression_bin.governing_yield_check is not None
    assert compression_bin.yield_long_check.state == "long-term"
    assert compression_bin.yield_long_check.branch == "compression fyck"
    assert compression_bin.yield_long_check.characteristic_strength_mpa == 400.0
    assert compression_bin.yield_design_total_check.state == "design total"
    assert compression_bin.yield_design_total_check.branch == "compression fyck"
    assert compression_bin.governing_yield_check == (
        compression_bin.yield_design_total_check
    )
    assert results[1].passed is False


def test_reinforcement_result_retains_governing_sn_branch_and_damage_operands():
    states = (
        _state(
            "high range",
            1.0e7,
            bar_long=(0.0,),
            bar_total=(200.0,),
        ),
        _state(
            "low range",
            1.0,
            bar_long=(0.0,),
            bar_total=(80.0,),
        ),
    )

    result = fatigue.assess_reinforcement_spectrum(
        (_steel_properties(),),
        states,
        gamma_s=1.0,
        gamma_ff=1.0,
    )[0]
    high, low = result.bins

    assert result.governing_criterion == "Miner damage"
    assert result.governing_bin == "high range"
    assert high.sn_reference_cycles == pytest.approx(2.0e6)
    assert high.sn_slope_1 == pytest.approx(5.0)
    assert high.sn_slope_2 == pytest.approx(9.0)
    assert high.sn_knee_stress_range_mpa == pytest.approx(160.0)
    assert high.sn_branch == "k1 (at or above knee)"
    assert high.sn_reference_ratio == pytest.approx(160.0 / 200.0)
    assert high.material_factor == pytest.approx(1.0)
    assert low.sn_branch == "k2 (below knee)"
    assert low.sn_reference_ratio == pytest.approx(160.0 / 80.0)


def test_reinforcement_yield_selection_can_retain_the_long_term_endpoint():
    result = fatigue.assess_reinforcement_spectrum(
        (_steel_properties(fyck=400.0),),
        (
            _state(
                "cyclic relief",
                1.0,
                bar_long=(-450.0,),
                bar_total=(-350.0,),
            ),
        ),
        gamma_s=1.0,
        gamma_ff=1.0,
    )[0].bins[0]

    assert result.governing_yield_check == result.yield_long_check
    assert result.governing_yield_check is not None
    assert result.governing_yield_check.state == "long-term"
    assert result.governing_yield_check.branch == "compression fyck"
    assert result.governing_yield_check.characteristic_strength_mpa == 400.0
    assert result.governing_yield_check.design_limit_mpa == pytest.approx(400.0)
    assert result.governing_yield_check.utilisation == pytest.approx(450.0 / 400.0)


def test_concrete_result_retains_governing_life_branch_and_miner_operands():
    properties = fatigue.ConcreteFatigueProperties(
        edition="2023",
        fck_mpa=37.5,
        gamma_c=1.5,
        beta_cc_t0=1.0,
        c=14.0,
    )
    states = (
        _state(
            "governing damage",
            2.0e9,
            concrete_long=(4.0,),
            concrete_total=(10.0,),
        ),
        _state(
            "minor damage",
            1.0,
            concrete_long=(1.0,),
            concrete_total=(6.0,),
        ),
    )

    result = fatigue.assess_concrete_spectrum(
        np.asarray([(0.0, 0.0)]),
        states,
        properties,
        gamma_ff=1.0,
    )[0]
    governing = result.bins[0]

    assert result.governing_criterion == "Miner damage"
    assert result.governing_bin == "governing damage"
    assert governing.life_branch == "variable compression"
    assert governing.life_coefficient == pytest.approx(14.0)
    assert governing.life_range_term == pytest.approx(math.sqrt(1.0 - 0.4))
    assert governing.log10_cycles_to_failure == pytest.approx(
        14.0
        * (1.0 - governing.e_cd_max)
        / governing.life_range_term
    )


def test_concrete_endpoint_identities_follow_reversed_design_compression():
    properties = fatigue.ConcreteFatigueProperties(
        edition="2023",
        fck_mpa=37.5,
        gamma_c=1.5,
        beta_cc_t0=1.0,
    )
    result = fatigue.assess_concrete_spectrum(
        np.asarray([(0.0, 0.0)]),
        (
            _state(
                "unloading",
                1.0e3,
                concrete_long=(10.0,),
                concrete_total=(8.0,),
                concrete_design_total=(6.0,),
                design_action_factor=2.0,
            ),
        ),
        properties,
        gamma_ff=2.0,
    )[0].bins[0]

    assert result.compression_total_mpa == 8.0
    assert result.compression_total_design_mpa == 6.0
    assert result.compression_min_design_mpa == 6.0
    assert result.compression_min_state == "action-factored total"
    assert result.compression_max_design_mpa == 10.0
    assert result.compression_max_state == "long-term"


def test_gamma_ff_is_visible_as_design_range_but_not_hidden_in_raw_stress():
    state = _state(
        "B1",
        1.0e5,
        bar_long=(100.0,),
        bar_total=(150.0,),
        bar_design_total=(160.0,),
        design_action_factor=1.2,
    )

    result = fatigue.assess_reinforcement_spectrum(
        (_steel_properties(),),
        (state,),
        gamma_s=1.0,
        gamma_ff=1.2,
    )[0].bins[0]

    assert result.stress_range_mpa == 50.0
    assert result.design_stress_range_mpa == 60.0
    assert result.stress_total_mpa == 150.0
    assert result.stress_total_design_mpa == 160.0
    assert result.stress_total_design_elastic_mpa == 160.0
    assert result.design_stress_range_elastic_mpa == 60.0
    assert result.governing_stress_mpa == 160.0


def _screen_rule(
    threshold=70.0,
    *,
    range_basis=fatigue.SIMPLIFIED_SCREEN_CHARACTERISTIC_RANGE,
    max_cycles=None,
):
    return fatigue.SimplifiedReinforcementFatigueRule(
        detail_class="test named detail",
        threshold_mpa=threshold,
        range_basis=range_basis,
        source="test source clause",
        max_cycles=max_cycles,
    )


@pytest.mark.parametrize(
    ("stress_range", "expected_status", "screen_passed"),
    [
        (69.999, fatigue.SIMPLIFIED_SCREEN_PASS, True),
        (70.0, fatigue.SIMPLIFIED_SCREEN_PASS, True),
        (70.001, fatigue.SIMPLIFIED_SCREEN_DETAILED, False),
    ],
)
def test_simplified_screen_has_inclusive_limit_and_retains_detailed_damage(
    stress_range, expected_status, screen_passed
):
    cycles = 1.0e12 if screen_passed else 1.0e9
    result = fatigue.assess_reinforcement_spectrum(
        (_steel_properties(screen_rule=_screen_rule()),),
        (
            _state(
                "screen bin",
                cycles,
                bar_long=(10.0,),
                bar_total=(10.0 + stress_range,),
            ),
        ),
        gamma_s=1.0,
        gamma_ff=1.0,
    )[0]

    screen = result.simplified_screen
    assert screen is not None
    assert screen.status == expected_status
    assert screen.passed is screen_passed
    assert screen.governing_range_mpa == pytest.approx(stress_range)
    assert screen.utilisation == pytest.approx(stress_range / 70.0)
    assert result.damage == pytest.approx(sum(item.damage for item in result.bins))
    if screen_passed:
        assert result.damage > 1.0
        assert result.passed is True
        assert result.governing_criterion == "simplified stress-range screen"
        assert result.utilisation == pytest.approx(screen.utilisation)
    else:
        assert result.passed is True
        assert result.governing_criterion == "Miner damage"
        assert result.utilisation == pytest.approx(result.damage)


def test_published_screen_uses_action_factored_design_range():
    result = fatigue.assess_reinforcement_spectrum(
        (_steel_properties(screen_rule=_screen_rule(
            90.0,
            range_basis=fatigue.SIMPLIFIED_SCREEN_DESIGN_RANGE,
            max_cycles=1.0e8,
        )),),
        (
            _state(
                "factored bin",
                1.0,
                bar_long=(10.0,),
                bar_total=(90.0,),
                bar_design_total=(110.0,),
                design_action_factor=1.25,
            ),
        ),
        gamma_s=1.0,
        gamma_ff=1.25,
    )[0]

    screen = result.simplified_screen
    assert screen is not None
    assert result.bins[0].stress_range_mpa == pytest.approx(80.0)
    assert result.bins[0].design_stress_range_mpa == pytest.approx(100.0)
    assert screen.governing_range_mpa == pytest.approx(100.0)
    assert screen.status == fatigue.SIMPLIFIED_SCREEN_DETAILED
    assert screen.passed is False


@pytest.mark.parametrize(
    ("cycles", "applicable", "passed"),
    [(1.0e8, True, True), (1.0e8 + 1.0, False, None)],
)
def test_published_screen_cycle_cap_is_inclusive(cycles, applicable, passed):
    result = fatigue.assess_reinforcement_spectrum(
        (_steel_properties(screen_rule=_screen_rule(
            90.0,
            range_basis=fatigue.SIMPLIFIED_SCREEN_DESIGN_RANGE,
            max_cycles=1.0e8,
        )),),
        (
            _state(
                "cycle cap",
                cycles,
                bar_long=(10.0,),
                bar_total=(40.0,),
                bar_design_total=(50.0,),
            ),
        ),
        gamma_s=1.0,
        gamma_ff=1.0,
    )[0]

    screen = result.simplified_screen
    assert screen is not None
    assert screen.applicable is applicable
    assert screen.passed is passed
    assert screen.total_cycles == cycles
    if not applicable:
        assert screen.status == fatigue.SIMPLIFIED_SCREEN_NOT_APPLICABLE
        assert "exceed" in screen.reason


def test_published_screen_cycle_cap_uses_the_sum_of_all_retained_bins():
    result = fatigue.assess_reinforcement_spectrum(
        (_steel_properties(screen_rule=_screen_rule(
            90.0,
            range_basis=fatigue.SIMPLIFIED_SCREEN_DESIGN_RANGE,
            max_cycles=1.0e8,
        )),),
        (
            _state("first", 6.0e7, bar_long=(10.0,), bar_total=(40.0,)),
            _state("second", 4.0e7 + 1.0, bar_long=(10.0,), bar_total=(40.0,)),
        ),
        gamma_s=1.0,
        gamma_ff=1.0,
    )[0]

    assert result.simplified_screen is not None
    assert result.simplified_screen.total_cycles == 1.0e8 + 1.0
    assert result.simplified_screen.status == (
        fatigue.SIMPLIFIED_SCREEN_NOT_APPLICABLE
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("stress_range_mpa", "not-a-number"),
        ("stress_range_mpa", True),
        ("stress_range_mpa", 1.0),
        ("stress_total_mpa", math.nan),
    ],
)
def test_simplified_screen_fails_closed_on_malformed_retained_evidence(
    field,
    value,
):
    baseline = fatigue.assess_reinforcement_spectrum(
        (_steel_properties(screen_rule=_screen_rule()),),
        (_state("screen", 1.0, bar_long=(10.0,), bar_total=(60.0,)),),
        gamma_s=1.0,
        gamma_ff=1.0,
    )[0]
    malformed = replace(baseline.bins[0], **{field: value})

    screen = fatigue.assess_simplified_reinforcement_fatigue(
        _screen_rule(),
        (malformed,),
    )

    assert screen.status == fatigue.SIMPLIFIED_SCREEN_INVALID
    assert screen.passed is None
    assert screen.utilisation is None


def test_simplified_screen_falls_back_for_compression_only_or_unconverged_bin():
    properties = (_steel_properties(screen_rule=_screen_rule()),)
    compression = fatigue.assess_reinforcement_spectrum(
        properties,
        (
            _state(
                "compression",
                1.0,
                bar_long=(-100.0,),
                bar_total=(-50.0,),
            ),
        ),
        gamma_s=1.0,
        gamma_ff=1.0,
    )[0]
    unconverged = fatigue.assess_reinforcement_spectrum(
        properties,
        (
            _state(
                "unconverged",
                1.0,
                bar_long=(10.0,),
                bar_total=(20.0,),
                converged=False,
            ),
        ),
        gamma_s=1.0,
        gamma_ff=1.0,
    )[0]

    assert compression.simplified_screen is not None
    assert compression.simplified_screen.status == (
        fatigue.SIMPLIFIED_SCREEN_NOT_APPLICABLE
    )
    assert "no tensile endpoint" in compression.simplified_screen.reason
    assert unconverged.simplified_screen is not None
    assert unconverged.simplified_screen.status == fatigue.SIMPLIFIED_SCREEN_INVALID
    assert unconverged.converged is False
    assert unconverged.passed is False


@pytest.mark.parametrize("bad_kind", ["compression", "unconverged"])
@pytest.mark.parametrize("reverse_order", [False, True])
def test_one_ineligible_bin_disables_screen_for_the_complete_spectrum(
    bad_kind,
    reverse_order,
):
    eligible = _state(
        "eligible",
        5.0e11,
        bar_long=(10.0,),
        bar_total=(60.0,),
    )
    if bad_kind == "compression":
        ineligible = _state(
            "compression",
            5.0e11,
            bar_long=(-100.0,),
            bar_total=(-50.0,),
        )
        expected_status = fatigue.SIMPLIFIED_SCREEN_NOT_APPLICABLE
        expected_reason = "no tensile endpoint"
    else:
        ineligible = _state(
            "unconverged",
            5.0e11,
            bar_long=(10.0,),
            bar_total=(60.0,),
            converged=False,
        )
        expected_status = fatigue.SIMPLIFIED_SCREEN_INVALID
        expected_reason = "did not converge"
    states = (ineligible, eligible) if reverse_order else (eligible, ineligible)

    result = fatigue.assess_reinforcement_spectrum(
        (_steel_properties(screen_rule=_screen_rule()),),
        states,
        gamma_s=1.0,
        gamma_ff=1.0,
    )[0]

    assert result.simplified_screen is not None
    assert result.simplified_screen.status == expected_status
    assert expected_reason in result.simplified_screen.reason
    assert result.simplified_screen.passed is None
    assert result.damage > 1.0
    assert result.governing_criterion == "Miner damage"
    assert result.utilisation == pytest.approx(result.damage)
    assert result.passed is False


def test_passing_screen_cannot_override_independent_yield_failure():
    result = fatigue.assess_reinforcement_spectrum(
        (_steel_properties(fytk=50.0, screen_rule=_screen_rule()),),
        (
            _state(
                "yield",
                1.0,
                bar_long=(10.0,),
                bar_total=(60.0,),
            ),
        ),
        gamma_s=1.0,
        gamma_ff=1.0,
    )[0]

    assert result.simplified_screen is not None
    assert result.simplified_screen.passed is True
    assert result.yield_utilisation > 1.0
    assert result.governing_criterion == "yield/proof stress"
    assert result.passed is False


@pytest.mark.parametrize(
    ("preset", "basis"),
    [
        (fatigue_inputs.PRESET_2005_COUPLERS, DesignBasisKey.FIRST_GEN_BASE),
        (fatigue_inputs.PRESET_2005_PRETENSION,
         DesignBasisKey.FIRST_GEN_DK_NA_2024),
        (fatigue_inputs.PRESET_2023_PRESTRESS_COUPLER,
         DesignBasisKey.PUBLISHED_2023),
    ],
)
def test_unsupported_screen_rules_keep_miner_as_the_range_criterion(
    preset,
    basis,
):
    entry = fatigue_inputs.default_entry(preset=preset)
    rule = fatigue.SimplifiedReinforcementFatigueRule(
        **fatigue_inputs.simplified_reinforcement_screen_rule(
            entry,
            16.0,
            basis,
        )
    )
    result = fatigue.assess_reinforcement_spectrum(
        (_steel_properties(screen_rule=rule),),
        (
            _state(
                "unsupported shortcut",
                1.0e12,
                bar_long=(10.0,),
                bar_total=(60.0,),
            ),
        ),
        gamma_s=1.0,
        gamma_ff=1.0,
    )[0]

    assert rule.threshold_mpa is None
    assert result.simplified_screen is not None
    assert result.simplified_screen.status == (
        fatigue.SIMPLIFIED_SCREEN_NOT_APPLICABLE
    )
    assert result.simplified_screen.applicable is False
    assert result.simplified_screen.passed is None
    assert result.damage > 1.0
    assert result.governing_criterion == "Miner damage"
    assert result.utilisation == pytest.approx(result.damage)
    assert result.passed is False


def test_exact_screen_and_yield_tie_retains_the_screen_range_criterion():
    result = fatigue.assess_reinforcement_spectrum(
        (
            _steel_properties(
                fytk=100.0,
                screen_rule=_screen_rule(50.0),
            ),
        ),
        (
            _state(
                "exact tie",
                1.0,
                bar_long=(25.0,),
                bar_total=(50.0,),
            ),
        ),
        gamma_s=1.0,
        gamma_ff=1.0,
    )[0]

    assert result.simplified_screen is not None
    assert result.simplified_screen.passed is True
    assert result.simplified_screen.utilisation == 0.5
    assert result.yield_utilisation == 0.5
    assert result.utilisation == 0.5
    assert result.governing_criterion == "simplified stress-range screen"
    assert result.governing_bin == "exact tie"
    assert result.passed is True


def test_simplified_screen_tie_retains_first_bin_order():
    result = fatigue.assess_reinforcement_spectrum(
        (_steel_properties(screen_rule=_screen_rule()),),
        (
            _state("first", 1.0, bar_long=(10.0,), bar_total=(60.0,)),
            _state("second", 1.0, bar_long=(20.0,), bar_total=(70.0,)),
        ),
        gamma_s=1.0,
        gamma_ff=1.0,
    )[0]

    assert result.simplified_screen is not None
    assert result.simplified_screen.governing_bin == "first"


def test_nonconverged_bin_cannot_pass_reinforcement_fatigue():
    state = _state(
        "B1",
        1.0e3,
        bar_long=(0.0,),
        bar_total=(1.0,),
        converged=False,
    )

    result = fatigue.assess_reinforcement_spectrum(
        (_steel_properties(),),
        (state,),
        gamma_s=1.0,
        gamma_ff=1.0,
    )[0]

    assert result.converged is False
    assert result.passed is False


def test_concrete_miner_damage_stays_on_each_fixed_fibre():
    vertices = np.asarray([(0.0, 0.0), (1.0, 0.0)], dtype=float)
    states = (
        _state(
            "B1",
            1.0e3,
            concrete_long=(0.0, 0.0),
            concrete_total=(12.0, 1.0),
        ),
        _state(
            "B2",
            1.0e3,
            concrete_long=(0.0, 0.0),
            concrete_total=(1.0, 12.0),
        ),
    )
    properties = fatigue.ConcreteFatigueProperties(
        edition="2023",
        fck_mpa=37.5,
        gamma_c=1.5,
        beta_cc_t0=1.0,
    )

    results = fatigue.assess_concrete_spectrum(
        vertices,
        states,
        properties,
        gamma_ff=1.0,
    )

    assert results[0].damage == pytest.approx(
        sum(item.damage for item in results[0].bins)
    )
    assert results[1].damage == pytest.approx(
        sum(item.damage for item in results[1].bins)
    )
    independent_bin_maxima = sum(
        max(results[fibre].bins[index].damage for fibre in range(2))
        for index in range(2)
    )
    assert max(result.damage for result in results) < independent_bin_maxima


def test_concrete_gamma_ff_and_strength_utilisation_are_explicit():
    vertices = np.asarray([(0.0, 0.0)], dtype=float)
    state = _state(
        "B1",
        1.0e3,
        concrete_long=(5.0,),
        concrete_total=(8.0,),
        concrete_design_total=(8.75,),
        design_action_factor=1.25,
    )
    properties = fatigue.ConcreteFatigueProperties(
        edition="2023",
        fck_mpa=37.5,
        gamma_c=1.5,
        beta_cc_t0=1.0,
    )

    result = fatigue.assess_concrete_spectrum(
        vertices,
        (state,),
        properties,
        gamma_ff=1.25,
    )[0].bins[0]

    assert result.compression_min_design_mpa == 5.0
    assert result.compression_max_design_mpa == 8.75
    assert result.compression_total_design_mpa == 8.75
    assert result.compression_min_state == "long-term"
    assert result.compression_max_state == "action-factored total"
    assert result.stress_utilisation == pytest.approx(
        8.75 / fatigue.concrete_fatigue_strength(properties)
    )


def test_nonunit_gamma_ff_requires_action_level_design_endpoint():
    state = _state(
        "B1",
        1.0e5,
        concrete_long=(10.0,),
        concrete_total=(12.0,),
    )
    properties = fatigue.ConcreteFatigueProperties(
        edition="2023",
        fck_mpa=40.0,
        gamma_c=1.5,
        beta_cc_t0=1.0,
    )

    with pytest.raises(ValueError, match="action-level design stresses"):
        fatigue.assess_concrete_spectrum(
            np.asarray([(0.0, 0.0)]),
            (state,),
            properties,
            gamma_ff=2.0,
        )


def test_constant_concrete_overload_fails_strength_even_with_zero_damage():
    vertices = np.asarray([(0.0, 0.0)], dtype=float)
    state = _state(
        "B1",
        1.0e3,
        concrete_long=(25.0,),
        concrete_total=(25.0,),
    )
    properties = fatigue.ConcreteFatigueProperties(
        edition="2023",
        fck_mpa=37.5,
        gamma_c=1.5,
        beta_cc_t0=1.0,
    )

    result = fatigue.assess_concrete_spectrum(
        vertices,
        (state,),
        properties,
        gamma_ff=1.0,
    )[0]

    assert result.damage == 0.0
    assert result.stress_utilisation > 1.0
    assert result.passed is False


def test_passing_reinforcement_screen_cannot_override_concrete_failure(
    monkeypatch,
):
    section = _section()
    state = _state(
        "independent materials",
        1.0,
        bar_long=(10.0, 10.0),
        bar_total=(20.0, 20.0),
        concrete_long=(0.0,),
        concrete_total=(0.0,),
    )
    failed_concrete = fatigue.ConcreteFibreFatigueResult(
        fibre_index=0,
        x_m=0.0,
        y_m=0.0,
        bins=(),
        fcd_fat_mpa=20.0,
        damage=0.0,
        damage_utilisation=0.0,
        governing_damage_bin="independent materials",
        stress_utilisation=1.2,
        governing_stress_bin="independent materials",
        utilisation=1.2,
        converged=True,
        passed=False,
        governing_criterion="compressive stress",
        governing_bin="independent materials",
    )
    search = fatigue.ConcreteFibreSearch(
        x_m=0.0,
        y_m=0.0,
        damage=0.0,
        upper_damage=0.25,
        divisions=4,
        boxes_evaluated=1,
        points_evaluated=1,
        absolute_gap=0.25,
        relative_gap=1.0,
        converged=True,
    )
    monkeypatch.setattr(
        fatigue,
        "solve_fatigue_bin",
        lambda *_args, **_kwargs: state,
    )
    monkeypatch.setattr(
        fatigue,
        "locate_governing_concrete_fibre",
        lambda *_args, **_kwargs: search,
    )
    monkeypatch.setattr(
        fatigue,
        "_states_at_concrete_fibres",
        lambda states, _fibres: tuple(states),
    )
    monkeypatch.setattr(
        fatigue,
        "assess_concrete_spectrum",
        lambda *_args, **_kwargs: (failed_concrete,),
    )

    result = fatigue.analyse_fatigue_spectrum(
        "Independent checks",
        section,
        (fatigue.SpectrumBin("independent materials", 1.0),),
        nl=10.0,
        ns=10.0,
        reinforcement=(
            _steel_properties("R1", screen_rule=_screen_rule()),
            _steel_properties("R2", screen_rule=_screen_rule()),
        ),
        concrete=fatigue.ConcreteFatigueProperties(
            edition="2005",
            fck_mpa=40.0,
            gamma_c=1.5,
            beta_cc_t0=1.0,
        ),
        fatigue_edition="2005",
        gamma_s=1.0,
        gamma_ff=1.0,
    )

    assert all(
        item.simplified_screen is not None
        and item.simplified_screen.passed is True
        for item in result.reinforcement
    )
    assert result.concrete == (failed_concrete,)
    assert result.governing_domain == "concrete"
    assert result.governing_criterion == "compressive stress"
    assert result.passed is False


def test_integrated_spectrum_uses_existing_elastic_long_short_solution():
    section = _section()
    properties = (
        _steel_properties("R1"),
        _steel_properties("R2"),
    )
    concrete = fatigue.ConcreteFatigueProperties(
        edition="2005",
        fck_mpa=40.0,
        gamma_c=1.5,
        beta_cc_t0=1.0,
    )
    bin_input = fatigue.SpectrumBin(
        name="FAT-01",
        cycles=2.0e4,
        p_long_kn=800.0,
        mx_long_knm=25.0,
        p_short_kn=200.0,
        mx_short_knm=15.0,
    )

    result = fatigue.analyse_fatigue_spectrum(
        "Traffic",
        section,
        (bin_input,),
        nl=18.0,
        ns=7.0,
        reinforcement=properties,
        concrete=concrete,
        gamma_s=1.15,
        gamma_ff=1.0,
    )

    assert result.converged is True
    assert len(result.bins) == 1
    assert len(result.reinforcement) == 2
    assert len(result.concrete) == len(section.concrete_vertices())
    assert result.reinforcement[0].bins[0].stress_range_mpa == pytest.approx(
        abs(
            result.bins[0].bar_stress_total_mpa[0]
            - result.bins[0].bar_stress_long_mpa[0]
        )
    )
    assert result.governing_reinforcement_id in {"R1", "R2"}
    assert result.governing_concrete_fibre in range(
        len(section.concrete_vertices())
    )


def test_gamma_ff_is_applied_to_actions_before_cracked_solution():
    section = _section()
    bin_input = fatigue.SpectrumBin(
        "Cracking transition",
        1.0e4,
        p_long_kn=100.0,
        mx_short_knm=80.0,
    )

    state = fatigue.solve_fatigue_bin(
        section,
        bin_input,
        12.0,
        7.0,
        gamma_ff=1.5,
    )
    expected = fatigue.solve_elastic_combined(
        section,
        100.0,
        0.0,
        0.0,
        12.0,
        0.0,
        120.0,
        0.0,
        7.0,
    )

    assert state.design_action_factor == pytest.approx(1.5)
    assert state.bar_stress_design_total_mpa == pytest.approx(
        np.asarray(expected.bar_stress_total) / 1000.0
    )
    affine_stress_scaling = np.asarray(state.bar_stress_long_mpa) + 1.5 * (
        np.asarray(state.bar_stress_total_mpa)
        - np.asarray(state.bar_stress_long_mpa)
    )
    assert np.max(np.abs(
        np.asarray(state.bar_stress_design_total_mpa)
        - affine_stress_scaling
    )) > 20.0


def test_concrete_search_catches_governing_edge_fibre_missed_by_corners():
    section = Section.from_polygon(
        corners=[
            (-0.5, -0.5),
            (0.5, -0.5),
            (0.5, 0.5),
            (-0.5, 0.5),
        ],
        bars_xy_area_mm2=[
            (0.0, -0.42, 1000.0),
            (0.0, 0.42, 1000.0),
        ],
    )
    bin_input = fatigue.SpectrumBin(
        name="Rotating stress planes",
        cycles=1.0e7,
        p_long_kn=260.59468685,
        mx_long_knm=52.14636107,
        my_long_knm=-324.57696939,
        p_short_kn=-45.05153404,
        mx_short_knm=390.75603827,
        my_short_knm=338.45754694,
    )

    result = fatigue.analyse_fatigue_spectrum(
        "Traffic",
        section,
        (bin_input,),
        nl=10.0,
        ns=6.0,
        check_reinforcement=False,
        concrete=fatigue.ConcreteFatigueProperties(
            edition="2023",
            fck_mpa=37.5,
            gamma_c=1.5,
            beta_cc_t0=1.0,
        ),
        gamma_ff=1.0,
    )

    corner_count = len(section.concrete_vertices())
    assert max(item.damage for item in result.concrete[:corner_count]) < 1.0
    assert len(result.concrete) == corner_count + 1
    assert result.concrete_search is not None
    assert result.concrete_search.converged is True
    assert result.concrete_search.divisions >= 96
    assert result.concrete_search.x_m == pytest.approx(-0.5)
    assert 0.34 < result.concrete_search.y_m < 0.39
    assert result.concrete_search.damage > 4.0
    assert result.concrete_search.absolute_gap == pytest.approx(
        result.concrete_search.upper_damage
        - result.concrete_search.damage
    )
    assert result.concrete_search.relative_gap >= 0.0
    assert result.governing_concrete_fibre == corner_count
    assert result.concrete[corner_count].damage == pytest.approx(
        result.concrete_search.damage
    )
    assert result.passed is False


def test_concrete_search_cannot_certify_a_hidden_narrow_damage_peak():
    section = Section.from_polygon(
        corners=[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    )
    bins = (
        fatigue.SpectrumBin(
            "narrow",
            2.0,
            p_long_kn=12999.95,
            mx_long_knm=6499.975,
            my_long_knm=5333.3166666666675,
            p_short_kn=1000.0,
            mx_short_knm=500.0,
            my_short_knm=666.6666666666661,
        ),
        fatigue.SpectrumBin(
            "broad",
            316.227766,
            p_short_kn=7500.0,
            mx_short_knm=3750.0,
            my_short_knm=5000.0,
        ),
    )

    result = fatigue.analyse_fatigue_spectrum(
        "Adversarial peak",
        section,
        bins,
        nl=1.0,
        ns=1.0,
        check_reinforcement=False,
        concrete=fatigue.ConcreteFatigueProperties(
            edition="2023",
            fck_mpa=37.5,
            gamma_c=1.5,
            beta_cc_t0=1.0,
        ),
    )

    assert result.concrete_search is not None
    assert result.concrete_search.damage > 1.3
    assert (
        result.concrete_search.upper_damage
        >= result.concrete_search.damage
    )
    assert result.utilisation >= result.concrete_search.upper_damage
    assert result.passed is False


def test_bounded_search_kernel_matches_reported_fibre_damage_kernel():
    section = _section()
    properties = fatigue.ConcreteFatigueProperties(
        edition="2023",
        fck_mpa=37.5,
        gamma_c=1.5,
        beta_cc_t0=1.0,
    )
    states = tuple(
        fatigue.solve_fatigue_bin(
            section,
            item,
            12.0,
            7.0,
            gamma_ff=1.1,
        )
        for item in (
            fatigue.SpectrumBin(
                "F1", 2.0e4, 800.0, 25.0, -10.0, 200.0, 15.0, 8.0
            ),
            fatigue.SpectrumBin(
                "F2", 5.0e5, 300.0, -15.0, 20.0, -100.0, 6.0, -12.0
            ),
        )
    )
    points = np.asarray([
        (-0.20, -0.30),
        (0.20, 0.30),
        (0.0, 0.0),
        (-0.10, 0.15),
    ])

    reference = fatigue._concrete_damage_field(
        points,
        states,
        properties,
        1.1,
    )
    search_values = fatigue._search_damage_field(
        points,
        fatigue._concrete_search_data(states, properties, 1.1),
    )

    assert search_values == pytest.approx(reference)


def test_uniform_compression_matches_transformed_section_hand_calculation():
    section = _section()
    n_ratio = 10.0
    long_force = 1000.0
    short_force = 200.0
    transformed_area = section.gross_area + n_ratio * sum(
        bar.area for bar in section.bars
    )
    expected_concrete_long = long_force / transformed_area / 1000.0
    expected_concrete_total = (
        (long_force + short_force) / transformed_area / 1000.0
    )
    expected_steel_range = n_ratio * (
        expected_concrete_total - expected_concrete_long
    )
    bin_input = fatigue.SpectrumBin(
        name="FAT-01",
        cycles=1.0e4,
        p_long_kn=long_force,
        p_short_kn=short_force,
    )

    result = fatigue.analyse_fatigue_spectrum(
        "Uniform compression",
        section,
        (bin_input,),
        nl=n_ratio,
        ns=n_ratio,
        reinforcement=(
            _steel_properties("R1"),
            _steel_properties("R2"),
        ),
        concrete=fatigue.ConcreteFatigueProperties(
            edition="2005",
            fck_mpa=40.0,
            gamma_c=1.5,
            beta_cc_t0=1.0,
        ),
        gamma_s=1.0,
        gamma_ff=1.0,
    )

    state = result.bins[0]
    assert state.concrete_compression_long_mpa == pytest.approx(
        (expected_concrete_long,) * 4
    )
    assert state.concrete_compression_total_mpa == pytest.approx(
        (expected_concrete_total,) * 4
    )
    assert state.bar_stress_long_mpa == pytest.approx(
        (-n_ratio * expected_concrete_long,) * 2
    )
    assert result.reinforcement[0].bins[0].stress_range_mpa == pytest.approx(
        expected_steel_range
    )
    assert result.concrete_search is not None
    assert result.concrete_search.converged is True
    assert result.concrete_search.upper_damage == pytest.approx(
        result.concrete_search.damage
    )
    assert result.passed is True


def test_equivalent_concrete_search_matches_the_fixed_fibre_criterion():
    section = _section()
    properties = fatigue.ConcreteFatigueProperties(
        edition="2023",
        fck_mpa=37.5,
        gamma_c=1.5,
        beta_cc_t0=1.0,
        method=fatigue.CONCRETE_EQUIVALENT,
    )
    result = fatigue.analyse_fatigue_spectrum(
        "Equivalent compression",
        section,
        (
            fatigue.SpectrumBin(
                "EQ-1",
                9.0e9,
                p_long_kn=1000.0,
                p_short_kn=200.0,
            ),
        ),
        nl=10.0,
        ns=10.0,
        check_reinforcement=False,
        concrete=properties,
        gamma_ff=1.0,
    )

    state = result.bins[0]
    expected = fatigue.concrete_equivalent_utilisation(
        max(
            state.concrete_compression_long_mpa[0],
            state.concrete_compression_total_mpa[0],
        ),
        min(
            state.concrete_compression_long_mpa[0],
            state.concrete_compression_total_mpa[0],
        ),
        fcd_fat_mpa=fatigue.concrete_fatigue_strength(properties),
    )
    assert result.concrete_method == fatigue.CONCRETE_EQUIVALENT
    assert result.concrete_search is not None
    assert result.concrete_search.method == fatigue.CONCRETE_EQUIVALENT
    assert result.concrete_search.converged is True
    assert result.concrete_search.damage == pytest.approx(expected)
    assert result.concrete_search.upper_damage == pytest.approx(expected)
    assert result.utilisation == pytest.approx(expected)
    assert result.concrete[0].equivalent_utilisation == pytest.approx(expected)
    assert result.concrete_strength is not None
    assert result.fcd_fat_mpa == pytest.approx(
        result.concrete_strength.fcd_fat_mpa
    )
    assert result.concrete_strength.edition == fatigue.EC2_2023
    assert result.governing_domain == "concrete"
    assert result.governing_criterion == "Equivalent amplitude"
    assert result.miner_damage is None


def test_tendon_only_section_is_included_in_fatigue_solver_order():
    section = Section.from_polygon(
        corners=[
            (-0.20, -0.30),
            (0.20, -0.30),
            (0.20, 0.30),
            (-0.20, 0.30),
        ],
        tendons_xy_area_mm2=[(0.0, -0.20, 600.0)],
    )

    result = fatigue.analyse_fatigue_spectrum(
        "Tendon only",
        section,
        (fatigue.SpectrumBin("F1", 1.0e4, 500.0, 0.0, 0.0, 50.0),),
        nl=10.0,
        ns=10.0,
        reinforcement=(
            _steel_properties("P1", kind=fatigue.PRESTRESS),
        ),
        check_concrete=False,
        n_mult=np.asarray([0.95]),
        prestress_stress=np.asarray([900000.0]),
    )

    assert len(result.bins[0].bar_stress_long_mpa) == 1
    assert len(result.reinforcement) == 1
    assert result.reinforcement[0].element_id == "P1"
    assert result.reinforcement[0].kind == fatigue.PRESTRESS


def _mixed_section():
    return Section.from_polygon(
        corners=[
            (-0.20, -0.30),
            (0.20, -0.30),
            (0.20, 0.30),
            (-0.20, 0.30),
        ],
        bars_xy_area_mm2=[(0.0, -0.20, 1000.0)],
        tendons_xy_area_mm2=[(0.0, 0.20, 1000.0)],
    )


def _mixed_properties():
    return (
        _steel_properties("R1", diameter=16.0),
        _steel_properties(
            "P1",
            kind=fatigue.PRESTRESS,
            diameter=16.0,
            bond_ratio=0.25,
            bond_diameter=16.0,
        ),
    )


def test_exact_zero_cyclic_action_reuses_long_term_state_and_zero_damage():
    section = Section.from_polygon(
        corners=[
            (-0.20, -0.30),
            (0.20, -0.30),
            (0.20, 0.30),
            (-0.20, 0.30),
        ],
        bars_xy_area_mm2=[(0.0, -0.20, 1000.0)],
        tendons_xy_area_mm2=[(0.045, 0.0, 100.0)],
    )
    properties = (
        _steel_properties("R1"),
        _steel_properties(
            "P1",
            kind=fatigue.PRESTRESS,
            fytk=1426.087,
            bond_ratio=0.25,
            bond_diameter=10.0,
        ),
    )

    result = fatigue.analyse_fatigue_spectrum(
        "Zero range",
        section,
        (
            fatigue.SpectrumBin(
                "F1",
                365_000.0,
                mx_long_knm=15.0,
            ),
        ),
        nl=18.0,
        ns=7.0,
        reinforcement=properties,
        concrete=fatigue.ConcreteFatigueProperties(
            edition="2023",
            fck_mpa=40.0,
            gamma_c=1.5,
            beta_cc_t0=1.0,
        ),
        fatigue_edition="2023",
        gamma_s=1.0,
        gamma_ff=1.1,
        n_mult=np.asarray([1.0, 0.95]),
        prestress_stress=np.asarray([0.0, 1_355_142.0]),
    )

    state = result.bins[0]
    assert state.zero_cyclic_action is True
    assert state.bar_stress_total_mpa == state.bar_stress_long_mpa
    assert state.bar_stress_design_total_mpa == state.bar_stress_long_mpa
    assert (
        state.concrete_compression_total_mpa
        == state.concrete_compression_long_mpa
    )
    assert (
        state.concrete_compression_design_total_mpa
        == state.concrete_compression_long_mpa
    )
    for element in result.reinforcement:
        bin_result = element.bins[0]
        assert bin_result.zero_cyclic_range is True
        assert bin_result.stress_range_mpa == 0.0
        assert bin_result.stress_range_elastic_mpa == 0.0
        assert bin_result.design_stress_range_mpa == 0.0
        assert bin_result.design_stress_range_elastic_mpa == 0.0
        assert math.isinf(bin_result.cycles_to_failure)
        assert math.isinf(bin_result.log10_cycles_to_failure)
        assert bin_result.damage == 0.0
    assert all(item.damage == 0.0 for item in result.concrete)
    assert result.concrete_search is not None
    assert result.concrete_search.damage == 0.0
    assert result.concrete_search.upper_damage == 0.0
    assert result.miner_damage == 0.0
    assert result.yield_utilisation == pytest.approx(
        max(item.yield_utilisation for item in result.reinforcement)
    )
    assert result.utilisation == result.yield_utilisation
    assert result.governing_domain == "reinforcement"
    assert result.governing_criterion == "yield/proof stress"


def test_concrete_search_bound_is_not_reported_as_evaluated_miner_damage(
    monkeypatch,
):
    section = _section()

    def bounded_search(candidate, states, _properties, **_kwargs):
        assert candidate is section
        assert all(state.zero_cyclic_action for state in states)
        x, y = candidate.concrete_vertices()[0]
        return fatigue.ConcreteFibreSearch(
            x_m=float(x),
            y_m=float(y),
            damage=0.0,
            upper_damage=0.25,
            divisions=4,
            boxes_evaluated=1,
            points_evaluated=4,
            absolute_gap=0.25,
            relative_gap=1.0,
            converged=True,
            method=fatigue.CONCRETE_MINER,
        )

    monkeypatch.setattr(
        fatigue,
        "locate_governing_concrete_fibre",
        bounded_search,
    )
    result = fatigue.analyse_fatigue_spectrum(
        "Bounded zero range",
        section,
        (fatigue.SpectrumBin("F1", 100_000.0, p_long_kn=100.0),),
        nl=10.0,
        ns=10.0,
        check_reinforcement=False,
        concrete=fatigue.ConcreteFatigueProperties(
            edition="2023",
            fck_mpa=40.0,
            gamma_c=1.5,
            beta_cc_t0=1.0,
        ),
    )

    assert result.miner_damage == 0.0
    assert max(item.damage for item in result.concrete) == 0.0
    assert result.concrete_search is not None
    assert result.concrete_search.upper_damage == pytest.approx(0.25)
    assert result.utilisation == pytest.approx(0.25)
    assert result.governing_criterion == "Miner damage upper bound"


def test_nonzero_uniform_cyclic_action_matches_independent_damage_oracle():
    section = _section()
    modular_ratio = 10.0
    long_force = 1000.0
    cyclic_force = 200.0
    action_factor = 1.25
    cycles = 100_000.0
    material_factor = 1.15
    transformed_area = section.gross_area + modular_ratio * sum(
        bar.area for bar in section.bars
    )
    expected_range = (
        modular_ratio * cyclic_force / transformed_area / 1000.0
    )
    expected_design_range = action_factor * expected_range
    design_knee = 160.0 / material_factor
    expected_life = 2.0e6 * (
        design_knee / expected_design_range
    ) ** 9.0
    expected_damage = cycles / expected_life

    result = fatigue.analyse_fatigue_spectrum(
        "Nonzero range",
        section,
        (
            fatigue.SpectrumBin(
                "F1",
                cycles,
                p_long_kn=long_force,
                p_short_kn=cyclic_force,
            ),
        ),
        nl=modular_ratio,
        ns=modular_ratio,
        reinforcement=(
            _steel_properties("R1"),
            _steel_properties("R2"),
        ),
        check_concrete=False,
        gamma_s=material_factor,
        gamma_ff=action_factor,
    )

    assert result.bins[0].zero_cyclic_action is False
    for element in result.reinforcement:
        bin_result = element.bins[0]
        assert bin_result.zero_cyclic_range is False
        assert bin_result.stress_range_mpa == pytest.approx(expected_range)
        assert bin_result.design_stress_range_mpa == pytest.approx(
            expected_design_range
        )
        assert bin_result.cycles_to_failure == pytest.approx(expected_life)
        assert bin_result.damage == pytest.approx(expected_damage)
    assert result.miner_damage == pytest.approx(expected_damage)


def test_2005_mixed_bond_correction_applies_eta_to_rebar_only():
    result = fatigue.analyse_fatigue_spectrum(
        "Mixed 2005",
        _mixed_section(),
        (fatigue.SpectrumBin("F1", 1.0e4, 700.0, 0.0, 0.0, 100.0),),
        nl=10.0,
        ns=10.0,
        reinforcement=_mixed_properties(),
        fatigue_edition="2005",
        check_concrete=False,
        n_mult=np.ones(2),
        prestress_stress=np.zeros(2),
    )

    beta = 0.5
    eta = 2.0 / (1.0 + beta)
    mild = result.reinforcement[0].bins[0]
    tendon = result.reinforcement[1].bins[0]
    assert mild.bond_adjustment == pytest.approx(eta)
    assert tendon.bond_adjustment == pytest.approx(1.0)
    assert "6.8.2(2)" in mild.bond_method
    assert "tendon range unadjusted" in tendon.bond_method
    assert mild.stress_total_elastic_mpa != mild.stress_long_mpa
    state = result.bins[0]
    assert mild.stress_total_design_elastic_mpa == pytest.approx(
        state.bar_stress_design_total_mpa[0]
    )
    assert mild.design_stress_range_elastic_mpa == pytest.approx(
        abs(
            state.bar_stress_design_total_mpa[0]
            - state.bar_stress_long_mpa[0]
        )
    )
    assert mild.stress_total_design_mpa != pytest.approx(
        mild.stress_total_design_elastic_mpa
    )


def test_2023_mixed_bond_correction_uses_equivalent_tendon_area():
    section = Section.from_polygon(
        corners=[
            (-0.20, -0.30),
            (0.20, -0.30),
            (0.20, 0.30),
            (-0.20, 0.30),
        ],
        bars_xy_area_mm2=[(0.0, 0.0, 1000.0)],
        tendons_xy_area_mm2=[(0.0, 0.0, 1000.0)],
    )
    n_ratio = 10.0
    short_force = 100.0
    beta = 0.5
    actual_area = section.gross_area + n_ratio * 0.002
    equivalent_area = section.gross_area + n_ratio * 0.0015
    expected_elastic = n_ratio * short_force / actual_area / 1000.0
    expected_equivalent = (
        n_ratio * short_force / equivalent_area / 1000.0
    )

    result = fatigue.analyse_fatigue_spectrum(
        "Mixed 2023",
        section,
        (fatigue.SpectrumBin("F1", 1.0e4, p_short_kn=short_force),),
        nl=n_ratio,
        ns=n_ratio,
        reinforcement=_mixed_properties(),
        fatigue_edition="2023",
        check_concrete=False,
        n_mult=np.ones(2),
        prestress_stress=np.zeros(2),
    )

    mild = result.reinforcement[0].bins[0]
    tendon = result.reinforcement[1].bins[0]
    assert mild.stress_range_elastic_mpa == pytest.approx(expected_elastic)
    assert mild.stress_range_mpa == pytest.approx(expected_equivalent)
    assert tendon.stress_range_mpa == pytest.approx(
        beta * expected_equivalent
    )
    assert "10.3(2)" in mild.bond_method


def test_mixed_bond_data_and_solver_mapping_are_mandatory():
    section = _mixed_section()
    one_bin = (fatigue.SpectrumBin("F1", 1.0e4, p_short_kn=10.0),)
    missing_bond = (
        _steel_properties("R1"),
        _steel_properties("P1", kind=fatigue.PRESTRESS),
    )

    with pytest.raises(ValueError, match="bond_ratio_xi"):
        fatigue.analyse_fatigue_spectrum(
            "Missing bond",
            section,
            one_bin,
            nl=10.0,
            ns=10.0,
            reinforcement=missing_bond,
            fatigue_edition="2023",
            check_concrete=False,
        )
    with pytest.raises(ValueError, match="expected 'P1'"):
        fatigue.analyse_fatigue_spectrum(
            "Wrong ID",
            section,
            one_bin,
            nl=10.0,
            ns=10.0,
            reinforcement=(
                _steel_properties("R1"),
                _steel_properties(
                    "T1",
                    kind=fatigue.PRESTRESS,
                    bond_ratio=0.25,
                    bond_diameter=16.0,
                ),
            ),
            fatigue_edition="2023",
            check_concrete=False,
        )
    with pytest.raises(ValueError, match="kind must be 'prestress'"):
        fatigue.analyse_fatigue_spectrum(
            "Wrong kind",
            section,
            one_bin,
            nl=10.0,
            ns=10.0,
            reinforcement=(
                _steel_properties("R1"),
                _steel_properties(
                    "P1",
                    kind=fatigue.MILD,
                    bond_ratio=0.25,
                    bond_diameter=16.0,
                ),
            ),
            fatigue_edition="2023",
            check_concrete=False,
        )


def test_explicit_solver_element_ids_support_stable_project_ids():
    properties = (
        _steel_properties("BAR-A"),
        _steel_properties(
            "PT-07",
            kind=fatigue.PRESTRESS,
            bond_ratio=0.25,
            bond_diameter=16.0,
        ),
    )

    result = fatigue.analyse_fatigue_spectrum(
        "Stable IDs",
        _mixed_section(),
        (fatigue.SpectrumBin("F1", 1.0e4, p_short_kn=10.0),),
        nl=10.0,
        ns=10.0,
        reinforcement=properties,
        fatigue_edition="2005",
        solver_element_ids=("BAR-A", "PT-07"),
        check_concrete=False,
    )

    assert [item.element_id for item in result.reinforcement] == [
        "BAR-A",
        "PT-07",
    ]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("n_mult", np.asarray([1.0]), r"shape \(2,\)"),
        ("n_mult", np.asarray([1.0, math.inf]), "must be finite"),
        ("n_mult", np.asarray([1.0, 0.0]), "greater than zero"),
        ("prestress_stress", np.asarray([[0.0, 0.0]]), r"shape \(2,\)"),
        ("prestress_stress", np.asarray([0.0, math.nan]), "must be finite"),
    ],
)
def test_solver_vectors_reject_broadcasting_and_nonfinite_values(
    field,
    value,
    message,
):
    kwargs = {
        "n_mult": np.ones(2),
        "prestress_stress": np.zeros(2),
    }
    kwargs[field] = value

    with pytest.raises(ValueError, match=message):
        fatigue.analyse_fatigue_spectrum(
            "Bad vector",
            _mixed_section(),
            (fatigue.SpectrumBin("F1", 1.0e4, p_short_kn=10.0),),
            nl=10.0,
            ns=10.0,
            reinforcement=_mixed_properties(),
            fatigue_edition="2005",
            check_concrete=False,
            **kwargs,
        )


def test_grouped_spectra_are_assessed_independently():
    section = _section()
    properties = (
        _steel_properties("R1"),
        _steel_properties("R2"),
    )
    common = dict(
        p_long_kn=800.0,
        mx_long_knm=25.0,
        p_short_kn=100.0,
        mx_short_knm=10.0,
    )
    groups = {
        "Traffic A": (
            fatigue.SpectrumBin("A-01", cycles=1.0e4, **common),
        ),
        "Traffic B": (
            fatigue.SpectrumBin("B-01", cycles=2.0e4, **common),
        ),
    }

    results = fatigue.analyse_grouped_spectra(
        section,
        groups,
        nl=18.0,
        ns=7.0,
        reinforcement=properties,
        check_concrete=False,
        gamma_s=1.0,
        gamma_ff=1.0,
    )

    assert [result.spectrum_name for result in results] == [
        "Traffic A",
        "Traffic B",
    ]
    assert results[1].reinforcement[0].damage == pytest.approx(
        2.0 * results[0].reinforcement[0].damage
    )


def test_grouped_spectra_reject_case_only_name_collisions():
    section = _section()

    with pytest.raises(ValueError, match="differs only by case"):
        fatigue.analyse_grouped_spectra(
            section,
            {
                "Traffic": (fatigue.SpectrumBin("A", 1.0),),
                "traffic": (fatigue.SpectrumBin("B", 1.0),),
            },
            nl=18.0,
            ns=7.0,
            reinforcement=(
                _steel_properties("R1"),
                _steel_properties("R2"),
            ),
            check_concrete=False,
        )


def test_grouped_spectra_reject_duplicate_bin_names_across_groups():
    section = _section()

    with pytest.raises(ValueError, match="fatigue bin name 'bin' duplicates"):
        fatigue.analyse_grouped_spectra(
            section,
            {
                "Traffic A": (fatigue.SpectrumBin("BIN", 1.0),),
                "Traffic B": (fatigue.SpectrumBin("bin", 1.0),),
            },
            nl=18.0,
            ns=7.0,
            reinforcement=(
                _steel_properties("R1"),
                _steel_properties("R2"),
            ),
            check_concrete=False,
        )


def test_integrated_analysis_rejects_incomplete_check_inputs():
    section = _section()
    one_bin = (fatigue.SpectrumBin("A", 1.0),)

    with pytest.raises(ValueError, match="2 solver bars"):
        fatigue.analyse_fatigue_spectrum(
            "S",
            section,
            one_bin,
            nl=18.0,
            ns=7.0,
            reinforcement=(_steel_properties("R1"),),
            check_concrete=False,
        )
    no_bar_section = Section.from_polygon(
        corners=[
            (-0.20, -0.30),
            (0.20, -0.30),
            (0.20, 0.30),
            (-0.20, 0.30),
        ]
    )
    with pytest.raises(ValueError, match="requires at least one"):
        fatigue.analyse_fatigue_spectrum(
            "S",
            no_bar_section,
            one_bin,
            nl=18.0,
            ns=7.0,
            check_concrete=False,
        )
    with pytest.raises(ValueError, match="concrete fatigue properties"):
        fatigue.analyse_fatigue_spectrum(
            "S",
            section,
            one_bin,
            nl=18.0,
            ns=7.0,
            reinforcement=(
                _steel_properties("R1"),
                _steel_properties("R2"),
            ),
        )
    with pytest.raises(ValueError, match="at least one fatigue material"):
        fatigue.analyse_fatigue_spectrum(
            "S",
            section,
            one_bin,
            nl=18.0,
            ns=7.0,
            check_reinforcement=False,
            check_concrete=False,
        )
