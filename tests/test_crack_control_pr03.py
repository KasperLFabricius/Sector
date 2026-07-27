"""Independent-oracle regressions for PR03 crack-control closure."""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

from sector.codes import fctm
from sector.elastic import ElasticResult, solve_elastic
from sector.section import Section
from sector.serviceability import (
    CRACK_SCOPE_DIRECT_TENSION,
    CRACK_SCOPE_DOMINANT_DIRECTION,
    analyse_cracking,
    effective_reinforcement_ratio_2023,
    evaluate_crack_width,
)
from tools.pr03_crack_oracle import (
    crack_width_2023,
    direct_tension_band_2023,
    effective_ratio_2023,
    rectangular_perimeter_area_2023,
)


def _mixed_bending_section() -> Section:
    return Section.from_polygon(
        corners=[(0.0, 0.0), (0.3, 0.0), (0.3, 0.6), (0.0, 0.6)],
        bars_xy_area_mm2=[
            (0.10, 0.05, 1000.0),
            (0.20, 0.05, 1000.0),
        ],
    )


def _direct_tension_section() -> Section:
    return Section.from_polygon(
        corners=[(-0.15, -0.30), (0.15, -0.30),
                 (0.15, 0.30), (-0.15, 0.30)],
        bars_xy_area_mm2=[
            (-0.075, -0.25, 491.0),
            (0.075, -0.25, 491.0),
            (-0.075, 0.25, 491.0),
            (0.075, 0.25, 491.0),
        ],
    )


def test_frozen_mixed_ratio_benchmark_matches_independent_oracle():
    # Frozen QA benchmark SLS-2023-XI1: As = Ap = 1000 mm2,
    # Ac,eff = 0.105 m2 and xi1 = 0.5.
    oracle = effective_ratio_2023(
        1000.0,
        [(1000.0, 0.25, 16.0)],
        105_000.0,
        mild_diameter_mm=16.0,
    )
    assert oracle.xi1_values == pytest.approx((0.5,))
    assert oracle.rho_p_eff == pytest.approx(0.014285714285714294)

    actual = effective_reinforcement_ratio_2023(
        [0.001, 0.001],
        [True, True],
        [16.0, 16.0],
        ac_eff_m2=0.105,
        reinforcement_types=["mild", "prestress"],
        bond_ratio_xi=[1.0, 0.25],
    )
    assert actual.xi1_by_element == (None, pytest.approx(0.5))
    assert actual.rho_p_eff == pytest.approx(oracle.rho_p_eff, rel=1e-12)
    assert actual.ap_eff_weighted == pytest.approx(0.0005)


def test_2023_mixed_bending_ratio_uses_xi_and_diameters():
    section = _mixed_bending_section()
    state = solve_elastic(section, 0.0, 150.0, 0.0, 6.0)
    evaluation = evaluate_crack_width(
        section,
        state,
        6.0,
        fctm=fctm(30.0),
        kt=0.4,
        bar_diameter=[16.0, 16.0],
        edition="2023",
        reinforcement_types=["mild", "prestress"],
        bond_ratio_xi=[1.0, 0.25],
    )
    assert evaluation.status == "CALCULATED"
    result = evaluation.result
    oracle = effective_ratio_2023(
        1000.0,
        [(1000.0, 0.25, 16.0)],
        result.ac_eff * 1.0e6,
        mild_diameter_mm=16.0,
    )
    assert result.as_eff == pytest.approx(0.001)
    assert result.ap_eff == pytest.approx(0.001)
    assert result.ap_eff_weighted == pytest.approx(0.0005)
    assert result.xi1_min == pytest.approx(0.5)
    assert result.xi1_max == pytest.approx(0.5)
    assert result.rho_p_eff == pytest.approx(oracle.rho_p_eff, rel=1e-12)

    mild_candidate_only = dataclasses.replace(
        state,
        bar_stress=np.asarray(
            [state.bar_stress[0], -abs(state.bar_stress[1])],
            dtype=float,
        ),
    )
    retained_provenance = evaluate_crack_width(
        section,
        mild_candidate_only,
        6.0,
        fctm=fctm(30.0),
        kt=0.4,
        bar_diameter=[16.0, 16.0],
        edition="2023",
        reinforcement_types=["mild", "prestress"],
        bond_ratio_xi=[1.0, 0.25],
    ).result
    assert {item.reinforcement_type for item in retained_provenance.candidates} == {
        "mild"
    }
    assert retained_provenance.ap_eff == pytest.approx(0.001)
    assert retained_provenance.xi1_min == pytest.approx(0.5)
    assert retained_provenance.xi1_max == pytest.approx(0.5)

    larger_tendon = evaluate_crack_width(
        section,
        state,
        6.0,
        fctm=fctm(30.0),
        kt=0.4,
        bar_diameter=[16.0, 64.0],
        edition="2023",
        reinforcement_types=["mild", "prestress"],
        bond_ratio_xi=[1.0, 0.25],
    ).result
    assert larger_tendon.xi1_min == pytest.approx(0.25)
    assert larger_tendon.rho_p_eff < result.rho_p_eff


def test_2023_prestress_only_sets_xi1_equal_to_xi():
    actual = effective_reinforcement_ratio_2023(
        [0.0012],
        [True],
        [12.5],
        ac_eff_m2=0.05,
        reinforcement_types=["prestress"],
        bond_ratio_xi=0.7,
    )
    oracle = effective_ratio_2023(
        0.0,
        [(1200.0, 0.7, 12.5)],
        50_000.0,
        mild_diameter_mm=None,
    )
    assert actual.xi1_by_element == pytest.approx((0.7,))
    assert actual.rho_p_eff == pytest.approx(oracle.rho_p_eff)


@pytest.mark.parametrize("xi", [0.0, -0.1, 1.01, math.nan])
def test_2023_invalid_bond_ratio_fails_closed(xi):
    with pytest.raises(ValueError, match="0 < xi <= 1"):
        effective_reinforcement_ratio_2023(
            [0.001, 0.001],
            [True, True],
            [16.0, 16.0],
            ac_eff_m2=0.05,
            reinforcement_types=["mild", "prestress"],
            bond_ratio_xi=[1.0, xi],
        )

    section = _mixed_bending_section()
    state = solve_elastic(section, 0.0, 150.0, 0.0, 6.0)
    evaluation = evaluate_crack_width(
        section,
        state,
        6.0,
        fctm=fctm(30.0),
        bar_diameter=[16.0, 16.0],
        edition="2023",
        reinforcement_types=["mild", "prestress"],
        bond_ratio_xi=[1.0, xi],
    )
    assert evaluation.status == "NOT ASSESSED"
    assert "bond ratio xi" in evaluation.reason


def test_2023_zero_effective_diameter_is_rejected_by_ratio_kernel():
    with pytest.raises(ValueError, match="diameters"):
        effective_reinforcement_ratio_2023(
            [0.001, 0.001],
            [True, True],
            [16.0, 0.0],
            ac_eff_m2=0.05,
            reinforcement_types=["mild", "prestress"],
            bond_ratio_xi=[1.0, 0.5],
        )


def test_2023_uniform_direct_tension_matches_independent_oracle():
    section = _direct_tension_section()
    state = solve_elastic(section, -100.0, 0.0, 0.0, 6.0)
    evaluation = evaluate_crack_width(
        section,
        state,
        6.0,
        fctm=fctm(30.0),
        kt=0.4,
        bar_diameter=16.0,
        k1=0.8,
        edition="2023",
    )
    assert evaluation.status == "CALCULATED"
    result = evaluation.result
    assert result.direct_tension is True
    assert result.scope == CRACK_SCOPE_DIRECT_TENSION
    assert result.kfl == pytest.approx(1.0)
    assert result.k1_r == pytest.approx(1.0)

    band = direct_tension_band_2023(50.0, 16.0, 600.0)
    ac_eff_mm2 = rectangular_perimeter_area_2023(
        300.0, 600.0, bottom_mm=band, top_mm=band
    )
    rho = 4.0 * 491.0 / ac_eff_mm2
    assert band == pytest.approx(130.0)
    assert result.hc_ef * 1000.0 == pytest.approx(band)
    assert result.bc_ef == pytest.approx(0.0)
    assert result.ac_eff * 1.0e6 == pytest.approx(ac_eff_mm2)
    assert result.rho_p_eff == pytest.approx(rho)

    sigma_s = float(state.bar_stress[0]) / 1000.0
    strain, spacing, width = crack_width_2023(
        sigma_s_mpa=sigma_s,
        es_mpa=200_000.0,
        fct_eff_mpa=fctm(30.0),
        rho_p_eff=rho,
        alpha_e=6.0,
        kt=0.4,
        cover_mm=42.0,
        diameter_mm=16.0,
        kb=0.9,
        kfl=1.0,
        k1_r=1.0,
    )
    assert result.esm_ecm == pytest.approx(strain)
    assert result.sr_max == pytest.approx(spacing)
    assert result.wk == pytest.approx(width)


def test_2023_direct_tension_good_and_poor_bond_bracket_width():
    section = _direct_tension_section()
    state = solve_elastic(section, -100.0, 0.0, 0.0, 6.0)
    good = evaluate_crack_width(
        section, state, 6.0, fctm=fctm(30.0), bar_diameter=16.0,
        k1=0.8, edition="2023",
    ).result
    poor = evaluate_crack_width(
        section, state, 6.0, fctm=fctm(30.0), bar_diameter=16.0,
        k1=1.6, edition="2023",
    ).result
    assert poor.sr_max > good.sr_max
    assert poor.wk > good.wk


def test_fixed_prestress_delays_decompression_cracking_threshold():
    section = _direct_tension_section()
    plain = analyse_cracking(
        section,
        -1000.0,
        0.0,
        0.0,
        6.0,
        fctm=fctm(30.0),
        bar_diameter=16.0,
    )
    prestressed = analyse_cracking(
        section,
        -1000.0,
        0.0,
        0.0,
        6.0,
        fctm=fctm(30.0),
        bar_diameter=16.0,
        prestress_stress=np.full(4, 500_000.0),
    )

    assert prestressed.sigma_ct < plain.sigma_ct
    assert prestressed.lambda_cr > plain.lambda_cr


def test_zero_and_near_zero_curvature_have_explicit_dispositions():
    section = _direct_tension_section()
    state = solve_elastic(section, -100.0, 0.0, 0.0, 6.0)
    near_uniform = dataclasses.replace(
        state,
        kx=state.eps0 * 1.0e-10,
    )
    evaluation = evaluate_crack_width(
        section, near_uniform, 6.0, fctm=fctm(30.0),
        bar_diameter=16.0, edition="2023",
    )
    assert evaluation.status == "CALCULATED"
    assert evaluation.result.direct_tension

    nonuniform = dataclasses.replace(
        state,
        kx=state.eps0 * 1.0e-4 / 0.30,
    )
    evaluation = evaluate_crack_width(
        section, nonuniform, 6.0, fctm=fctm(30.0),
        bar_diameter=16.0, edition="2023",
    )
    assert evaluation.status == "NOT ASSESSED"
    assert "entire section is in tension" in evaluation.reason

    transition = dataclasses.replace(state, eps0=0.0, kx=1.0e-6)
    evaluation = evaluate_crack_width(
        section, transition, 6.0, fctm=fctm(30.0),
        bar_diameter=16.0, edition="2023",
    )
    assert evaluation.status == "NOT ASSESSED"
    assert "near-zero strain gradient" in evaluation.reason


def test_2005_direct_tension_and_unsupported_geometry_fail_closed():
    section = _direct_tension_section()
    state = solve_elastic(section, -100.0, 0.0, 0.0, 6.0)
    old = evaluate_crack_width(
        section, state, 6.0, fctm=fctm(30.0), bar_diameter=16.0,
        edition="2004",
    )
    assert old.status == "NOT ASSESSED"
    assert "2005" in old.reason

    non_rectangular = Section.from_polygon(
        corners=[(-0.15, -0.30), (0.15, -0.30), (0.15, 0.10),
                 (0.05, 0.30), (-0.15, 0.30)],
        bars_xy_area_mm2=[
            (-0.075, -0.25, 491.0), (0.075, -0.25, 491.0),
            (-0.075, 0.25, 491.0), (0.075, 0.20, 491.0),
        ],
    )
    non_rect_state = solve_elastic(non_rectangular, -100.0, 0.0, 0.0, 6.0)
    non_rect_state = dataclasses.replace(
        non_rect_state,
        eps0=max(non_rect_state.eps0, 1.0),
        kx=0.0,
        ky=0.0,
        bar_stress=np.full(4, 50_000.0),
    )
    unsupported = evaluate_crack_width(
        non_rectangular, non_rect_state, 6.0, fctm=fctm(30.0),
        bar_diameter=16.0, edition="2023",
    )
    assert unsupported.status == "NOT ASSESSED"
    assert "solid rectangular" in unsupported.reason


def test_zero_reinforcement_is_blocking_not_assessed():
    section = Section.from_polygon(
        corners=[(-0.15, -0.30), (0.15, -0.30),
                 (0.15, 0.30), (-0.15, 0.30)],
    )
    state = ElasticResult(
        eps0=1.0,
        kx=0.0,
        ky=0.0,
        bar_stress=np.empty(0),
        max_concrete_compression=0.0,
        max_concrete_point=0,
        max_concrete_xy=(0.0, 0.0),
        na_x_intercept=math.inf,
        na_y_intercept=math.inf,
        converged=False,
        iterations=0,
    )
    evaluation = evaluate_crack_width(
        section, state, 6.0, fctm=fctm(30.0), edition="2023",
    )
    assert evaluation.status == "NOT ASSESSED"
    assert "no reinforcement" in evaluation.reason


def test_rotated_asymmetric_section_retains_value_and_reports_direction():
    corners = [
        (0.0, 0.0), (0.40, 0.0), (0.40, 0.15),
        (0.15, 0.15), (0.15, 0.60), (0.0, 0.60),
    ]
    bars = [(0.04, 0.04, 491.0), (0.11, 0.04, 314.0)]
    section = Section.from_polygon(corners=corners, bars_xy_area_mm2=bars)
    state = solve_elastic(section, 0.0, 120.0, 0.0, 6.0)
    original = evaluate_crack_width(
        section, state, 6.0, fctm=fctm(30.0),
        bar_diameter=[25.0, 20.0], edition="2023",
    ).result
    assert original.scope == CRACK_SCOPE_DOMINANT_DIRECTION

    angle = math.radians(37.0)
    c, s = math.cos(angle), math.sin(angle)

    def rotate(point):
        x, y = point
        return (c * x - s * y, s * x + c * y)

    rotated = Section.from_polygon(
        corners=[rotate(point) for point in corners],
        bars_xy_area_mm2=[
            (*rotate((x, y)), area) for x, y, area in bars
        ],
    )
    rotated_state = dataclasses.replace(
        state,
        kx=c * state.kx - s * state.ky,
        ky=s * state.kx + c * state.ky,
    )
    result = evaluate_crack_width(
        rotated, rotated_state, 6.0, fctm=fctm(30.0),
        bar_diameter=[25.0, 20.0], edition="2023",
    ).result
    assert result.wk == pytest.approx(original.wk, rel=1e-10)
    assert result.ac_eff == pytest.approx(original.ac_eff, rel=1e-10)
    assert result.rho_p_eff == pytest.approx(original.rho_p_eff, rel=1e-10)
    assert (result.direction_deg - original.direction_deg) % 180.0 == pytest.approx(
        37.0
    )
