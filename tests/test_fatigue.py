import math

import numpy as np
import pytest

from sector import fatigue
from sector.section import Section


def _state(
    name,
    cycles,
    *,
    bar_long=(),
    bar_total=(),
    concrete_long=(),
    concrete_total=(),
    converged=True,
):
    return fatigue.FatigueBinState(
        name=name,
        description="",
        cycles=float(cycles),
        converged=converged,
        bar_stress_long_mpa=tuple(bar_long),
        bar_stress_total_mpa=tuple(bar_total),
        concrete_compression_long_mpa=tuple(concrete_long),
        concrete_compression_total_mpa=tuple(concrete_total),
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
):
    return fatigue.ReinforcementFatigueProperties(
        element_id=element_id,
        kind=kind,
        detail_id=detail_id,
        diameter_mm=16.0,
        n_star=2.0e6,
        k1=5.0,
        k2=9.0,
        delta_sigma_rsk_mpa=delta_sigma,
        fytk_mpa=fytk,
        fyck_mpa=fyck,
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
    assert results[1].yield_utilisation == pytest.approx(450.0 / 400.0)
    assert results[1].governing_yield_bin == "B1"
    assert results[1].passed is False


def test_gamma_ff_is_visible_as_design_range_but_not_hidden_in_raw_stress():
    state = _state(
        "B1",
        1.0e5,
        bar_long=(100.0,),
        bar_total=(150.0,),
    )

    result = fatigue.assess_reinforcement_spectrum(
        (_steel_properties(),),
        (state,),
        gamma_s=1.0,
        gamma_ff=1.2,
    )[0].bins[0]

    assert result.stress_range_mpa == 50.0
    assert result.design_stress_range_mpa == 60.0
    assert result.governing_stress_mpa == 150.0


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

    assert result.compression_min_design_mpa == 6.25
    assert result.compression_max_design_mpa == 10.0
    assert result.stress_utilisation == pytest.approx(
        10.0 / fatigue.concrete_fatigue_strength(properties)
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
    assert result.governing_concrete_fibre == corner_count
    assert result.concrete[corner_count].damage == pytest.approx(
        result.concrete_search.damage
    )
    assert result.passed is False


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
