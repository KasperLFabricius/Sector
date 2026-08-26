"""Verification of the plastic capacity solver.

The headline case is the "Fundamentsbjaelke" production handcalc run (a rectangular
mild-steel section, P = 0, swept through four neutral-axis angles), reproduced
here to the printout precision. A second check confirms the engine agrees with a
Eurocode rectangular-stress-block hand calculation for a slab (the two methods
differ only in the concrete stress shape, so they should be within a couple of
percent).
"""

from __future__ import annotations

import inspect
import math
from dataclasses import FrozenInstanceError, MISSING, fields

import numpy as np
import pytest

from sector import PlasticPoint
from sector.materials import Concrete, MildSteel
from sector.plastic import (
    _band_stresses,
    _governing_curvature,
    plastic_capacity_at_angle,
    solve_plastic,
)
from sector.section import Bar, Section
from sector.shear import effective_depth, tension_reinforcement


# Frozen from d01e6beb040f766985bf5547d99940d649f520c1, before the
# optional solver-diagnostic tail fields.
_LEGACY_PLASTIC_POINT_FIELDS = (
    "V", "Mx", "My", "axial", "U", "R", "na_x_intercept",
    "na_y_intercept", "eps_concrete", "eps_steel", "eps_steel_comp",
    "eps_cable", "curvature", "compression_force", "lever_arm", "dx", "dy",
    "converged",
)
_LEGACY_PLASTIC_POINT_VALUES = tuple(float(i) for i in range(1, 18)) + (True,)
_FINITE_DIAGNOSTIC_FIELDS = (
    "axial_requested", "axial_residual", "axial_tolerance", "compression_depth",
    "neutral_axis_offset", "strain_gradient_x", "strain_gradient_y",
    "strain_offset", "search_lower_depth", "search_upper_depth",
    "search_lower_axial", "search_upper_axial", "concrete_force", "concrete_mx",
    "concrete_my", "bar_force", "bar_mx", "bar_my", "tendon_force",
    "tendon_mx", "tendon_my", "compression_mx", "compression_my",
    "tension_force", "tension_mx", "tension_my",
)


def test_plastic_point_preserves_exact_legacy_positional_contract():
    point = PlasticPoint(*_LEGACY_PLASTIC_POINT_VALUES)
    assert tuple(getattr(point, name) for name in _LEGACY_PLASTIC_POINT_FIELDS) == (
        _LEGACY_PLASTIC_POINT_VALUES
    )

    parameters = tuple(inspect.signature(PlasticPoint).parameters.values())
    legacy_parameters = parameters[:len(_LEGACY_PLASTIC_POINT_FIELDS)]
    assert tuple(parameter.name for parameter in legacy_parameters) == (
        _LEGACY_PLASTIC_POINT_FIELDS
    )
    assert all(
        parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        and parameter.default is inspect.Parameter.empty
        for parameter in legacy_parameters
    )

    point_fields = fields(PlasticPoint)
    assert tuple(field.name for field in point_fields[:len(legacy_parameters)]) == (
        _LEGACY_PLASTIC_POINT_FIELDS
    )
    assert all(
        not field.kw_only and field.default is MISSING
        for field in point_fields[:len(legacy_parameters)]
    )
    assert all(
        field.kw_only and field.default is None
        for field in point_fields[len(legacy_parameters):]
    )


def test_plastic_point_preserves_exact_legacy_keyword_set():
    legacy = dict(zip(_LEGACY_PLASTIC_POINT_FIELDS, _LEGACY_PLASTIC_POINT_VALUES))
    point = PlasticPoint(**legacy)
    assert tuple(getattr(point, name) for name in legacy) == _LEGACY_PLASTIC_POINT_VALUES
    assert all(getattr(point, name) is None for name in _FINITE_DIAGNOSTIC_FIELDS)
    assert point.axial_reachable is None
    assert point.search_iterations is None


def test_solver_points_carry_complete_finite_diagnostics():
    section, concrete, steel = fundamentsbjaelke()
    point = plastic_capacity_at_angle(section, concrete, steel, 0.0, 90.0)

    assert all(
        math.isfinite(float(getattr(point, name)))
        for name in _FINITE_DIAGNOSTIC_FIELDS
    )
    assert type(point.axial_reachable) is bool
    assert type(point.search_iterations) is int and point.search_iterations >= 0


def test_accepted_plastic_state_retains_authoritative_corner_and_bar_rows():
    section, concrete, steel = fundamentsbjaelke()
    point = plastic_capacity_at_angle(section, concrete, steel, 0.0, 90.0)

    assert point.concrete_corner_states is not None
    assert point.bar_states is not None
    assert point.tendon_states == ()
    assert len(point.concrete_corner_states) == sum(map(len, section.concrete))
    assert len(point.bar_states) == len(section.bars)

    corner = point.concrete_corner_states[0]
    assert tuple(field.name for field in fields(corner)) == (
        "ring_index", "point_index", "x", "y", "section_strain",
        "material_strain", "material_stress",
    )
    assert not hasattr(corner, "__dict__")
    with pytest.raises(FrozenInstanceError):
        corner.x = 0.0
    for state in point.concrete_corner_states:
        expected_section_strain = (
            point.strain_gradient_x * state.x
            + point.strain_gradient_y * state.y
            + point.strain_offset
        )
        assert state.section_strain == pytest.approx(expected_section_strain)
        assert state.material_strain == -state.section_strain
        assert state.material_stress == concrete.stress(
            state.material_strain, design=True
        )

    bar = point.bar_states[0]
    assert tuple(field.name for field in fields(bar)) == (
        "element_index", "x", "y", "area", "section_strain",
        "initial_strain", "material_strain", "material_stress", "force",
        "mx", "my",
    )
    assert not hasattr(bar, "__dict__")
    with pytest.raises(FrozenInstanceError):
        bar.force = 0.0
    for index, state in enumerate(point.bar_states):
        assert state.element_index == index
        assert state.initial_strain == 0.0
        assert state.material_strain == -state.section_strain
        assert state.material_stress == steel.stress(state.material_strain, design=True)
        assert state.force == pytest.approx(
            -state.material_stress * state.area * 1000.0
        )
        assert state.mx == pytest.approx(state.force * state.y)
        assert state.my == pytest.approx(state.force * state.x)

    assert sum(state.force for state in point.bar_states) == pytest.approx(
        point.bar_force
    )
    assert sum(state.mx for state in point.bar_states) == pytest.approx(point.bar_mx)
    assert sum(state.my for state in point.bar_states) == pytest.approx(point.bar_my)
    assert min(state.section_strain for state in point.bar_states) * 100.0 == (
        pytest.approx(point.eps_steel)
    )
    assert max(state.section_strain for state in point.bar_states) * 100.0 == (
        pytest.approx(point.eps_steel_comp)
    )


def test_total_compression_resultant_includes_compressive_reinforcement():
    section, concrete, steel = fundamentsbjaelke()
    point = plastic_capacity_at_angle(section, concrete, steel, 0.0, 90.0)

    compressive_bars = sum(
        state.force for state in point.bar_states if state.force > 0.0
    )
    compressive_tendons = sum(
        state.force for state in point.tendon_states if state.force > 0.0
    )

    assert compressive_bars > 0.0
    assert point.compression_force == pytest.approx(
        point.concrete_force + compressive_bars + compressive_tendons
    )
    assert point.compression_force > point.concrete_force


def test_accepted_curvature_selection_retains_candidates_and_stable_governor():
    section = Section.from_polygon(
        corners=[(-0.15, -0.3), (-0.15, 0.3), (0.15, 0.3), (0.15, -0.3)],
        bars_xy_area_mm2=[(0.0, -0.25, 200.0)],
    )
    concrete = Concrete(fck=35.0, gamma_c=1.5, curve=2)
    steel = MildSteel(
        fytk=500.0, fyck=500.0, eut=0.01, futk=540.0,
        gamma_y=1.15, gamma_u=1.15, gamma_E=1.0, curve=1,
    )

    point = plastic_capacity_at_angle(section, concrete, steel, 0.0, 90.0)
    selection = point.curvature_selection
    assert selection is not None
    assert not hasattr(selection, "__dict__")
    assert selection.selected_mode == "bar_tension_rupture"
    assert selection.selected_element_index == 0
    assert selection.selected_curvature == point.curvature
    assert selection.candidates[0].mode == "concrete_crushing"
    assert selection.candidates[0].element_index is None
    assert all(
        candidate.curvature
        == pytest.approx(candidate.strain_limit / candidate.distance_from_na)
        for candidate in selection.candidates
    )
    assert any(
        candidate.mode == "bar_tension_rupture"
        and candidate.element_index == 0
        and candidate.curvature == selection.selected_curvature
        for candidate in selection.candidates
    )
    assert all(not hasattr(candidate, "__dict__") for candidate in selection.candidates)


def fundamentsbjaelke():
    section = Section.from_polygon(
        corners=[(-0.150, -0.300), (-0.150, 0.300), (0.150, 0.300), (0.150, -0.300)],
        bars_xy_area_mm2=[
            (-0.10, -0.244, 201.0), (-0.06, -0.244, 201.0), (-0.02, -0.244, 201.0),
            (0.02, -0.244, 201.0), (0.06, -0.244, 201.0), (0.10, -0.244, 201.0),
            (0.10, 0.244, 201.0), (-0.10, 0.244, 201.0),
        ],
    )
    concrete = Concrete(fck=33.0, gamma_c=1.31, curve=1)
    steel = MildSteel(fytk=550.0, fyck=550.0, eut=0.05, futk=550.0,
                      gamma_y=1.08, gamma_u=1.08, gamma_E=1.08, curve=1)
    return section, concrete, steel


# V, Mx, My, U, compress, curvature, steel%, L, |DX|, |DY|, x_int, y_int
FUND_CASES = [
    (0.0, 99.9, 99.8, 45.0, 615.8, 0.07043, -1.41, 0.229, 0.162, 0.162, 0.100, math.inf),
    (90.0, 310.4, 0.0, 90.0, 614.2, 0.04126, -1.89, 0.505, 0.000, 0.505, math.inf, 0.215),
    (180.0, 99.9, -99.8, 135.0, 615.8, 0.07043, -1.41, 0.229, 0.162, 0.162, -0.100, math.inf),
    (270.0, -110.7, 0.0, 270.0, 306.9, 0.07067, -3.49, 0.361, 0.000, 0.361, math.inf, -0.250),
]


@pytest.mark.parametrize("case", FUND_CASES, ids=[f"V{int(c[0])}" for c in FUND_CASES])
def test_fundamentsbjaelke_matches_handcalc(case):
    V, Mx, My, U, comp, curv, steel_pct, L, dxa, dya, x_int, y_int = case
    section, concrete, steel = fundamentsbjaelke()
    r = plastic_capacity_at_angle(section, concrete, steel, 0.0, V)

    assert r.converged
    assert r.Mx == pytest.approx(Mx, abs=0.6)
    assert r.My == pytest.approx(My, abs=0.6)
    assert r.U == pytest.approx(U, abs=0.3)
    assert r.compression_force == pytest.approx(comp, abs=1.0)
    assert r.curvature == pytest.approx(curv, abs=5e-5)
    assert r.eps_concrete == pytest.approx(0.35)
    assert r.eps_steel == pytest.approx(steel_pct, abs=0.02)
    assert r.lever_arm == pytest.approx(L, abs=0.003)
    # Lever-arm component magnitudes match (the handcalc component sign convention
    # is direction-dependent; L and the magnitudes are the meaningful values).
    assert abs(r.dx) == pytest.approx(dxa, abs=0.003)
    assert abs(r.dy) == pytest.approx(dya, abs=0.003)
    if math.isinf(x_int):
        assert math.isinf(r.na_x_intercept)
    else:
        assert r.na_x_intercept == pytest.approx(x_int, abs=0.002)
    if math.isinf(y_int):
        assert math.isinf(r.na_y_intercept)
    else:
        assert r.na_y_intercept == pytest.approx(y_int, abs=0.002)


def test_uniaxial_lever_component_is_not_effective_depth():
    section, concrete, steel = fundamentsbjaelke()
    result = plastic_capacity_at_angle(section, concrete, steel, 0.0, 90.0)
    outer = [tuple(point) for point in section.concrete[0]]
    bars = [(bar.x, bar.y, bar.area) for bar in section.bars]
    _area, tension_cg = tension_reinforcement(
        bars, "x", tension_low=True, centroid_coord=0.0
    )
    depth_mm = effective_depth(outer, "x", True, tension_cg)

    assert result.dx == pytest.approx(0.0, abs=1.0e-12)
    assert result.lever_arm == pytest.approx(abs(result.dy), abs=1.0e-12)
    assert result.lever_arm == pytest.approx(
        math.hypot(result.dx, result.dy), abs=1.0e-12
    )
    assert depth_mm == pytest.approx(544.0)
    assert result.lever_arm * 1000.0 == pytest.approx(505.0, abs=3.0)
    assert abs(result.lever_arm * 1000.0 - depth_mm) > 30.0


def test_eps_steel_comp_is_the_most_compressed_bar_strain():
    # The solver reports both mild-steel strain extremes (compression-positive): the
    # most tensile (eps_steel) and the most compressed (eps_steel_comp). At V = 90 the
    # top and bottom bars strain differently, so the two extremes differ.
    section, concrete, steel = fundamentsbjaelke()
    r = plastic_capacity_at_angle(section, concrete, steel, 0.0, 90.0)
    assert r.eps_steel_comp >= r.eps_steel          # max >= min, by definition
    assert r.eps_steel_comp != r.eps_steel          # a distinct extreme, not a copy


def test_solve_plastic_sweep_returns_all_angles():
    section, concrete, steel = fundamentsbjaelke()
    pts = solve_plastic(section, concrete, steel, 0.0, 0.0, 360.0, 90.0)
    assert [p.V for p in pts] == [0.0, 90.0, 180.0, 270.0, 360.0]
    # 0 and 360 degrees are the same state.
    assert pts[0].Mx == pytest.approx(pts[4].Mx, abs=1e-6)


def test_slab_matches_eurocode_rectangular_block():
    # A singly-reinforced 1 m slab strip; compare the plastic engine (parabola)
    # with the Eurocode rectangular-stress-block hand-calc method.
    b, h, cover, As_mm2 = 1.0, 0.30, 0.04, 2000.0
    d = h - cover
    fck, gc, fyk, gs = 30.0, 1.5, 500.0, 1.15
    fcd, fyd = fck / gc, fyk / gs
    T = As_mm2 * 1e-6 * fyd
    a = T / (fcd * b)                       # rectangular block depth
    mrd_block = T * (d - a / 2.0) * 1000.0  # kNm

    slab = Section.from_polygon(
        corners=[(-b / 2, 0.0), (-b / 2, h), (b / 2, h), (b / 2, 0.0)],
        bars_xy_area_mm2=[(0.0, cover, As_mm2)],
    )
    concrete = Concrete(fck=fck, gamma_c=gc, curve=2)
    steel = MildSteel(fytk=fyk, fyck=fyk, eut=0.05, gamma_y=gs, curve=2)
    r = plastic_capacity_at_angle(slab, concrete, steel, 0.0, 90.0)

    assert r.converged
    assert r.Mx == pytest.approx(mrd_block, rel=0.02)  # within ~2%


def test_governing_curvature_caps_compression_steel_rupture():
    # The symmetric rupture must also cap the curvature for a compression bar: with
    # eut below the concrete crushing strain, a compression bar reaches eut first.
    # s_na = s_max - c = 0.1. A bar 0.09 past the NA on the compression side
    # (s = 0.19) reaches the valid post-yield rupture strain eut = 3 permille
    # before the concrete crushes. s_bars are the projections.
    s_bars = np.array([0.19, 0.099])
    empty = np.empty(0)
    low = MildSteel(fytk=500.0, fyck=500.0, eut=0.003, gamma_y=1.0, curve=2)
    phi = _governing_curvature(low, None, 0.2, 0.1, s_bars, empty, 0.0035)
    assert phi == pytest.approx(0.003 / 0.09, rel=1e-6)    # compression bar governs
    # With a large eut the concrete crushing limit governs instead (no cap effect).
    high = MildSteel(fytk=500.0, fyck=500.0, eut=0.05, gamma_y=1.0, curve=2)
    phi2 = _governing_curvature(high, None, 0.2, 0.1, s_bars, empty, 0.0035)
    assert phi2 == pytest.approx(0.0035 / 0.1, rel=1e-6)   # concrete governs


def test_governing_curvature_ignores_zero_capacity_compression_rupture():
    # fyck=0 owns no compression branch even when the explicit toggle remains on.
    # The ignored bar therefore cannot cap curvature at its nominal eut.
    s_bars = np.array([0.19, 0.099])
    empty = np.empty(0)
    zero_compression = MildSteel(
        fytk=500.0,
        fyck=0.0,
        eut=0.003,
        gamma_y=1.0,
        curve=2,
        active_in_compression=True,
    )

    phi = _governing_curvature(
        zero_compression,
        None,
        0.2,
        0.1,
        s_bars,
        empty,
        0.0035,
    )

    assert phi == pytest.approx(0.0035 / 0.1, rel=1e-6)


def test_zero_fyck_toggle_does_not_change_plastic_capacity_or_governor():
    section = _rect_with_top_and_bottom_bars()
    values = dict(
        fytk=500.0,
        fyck=0.0,
        eut=0.003,
        gamma_y=1.0,
        curve=2,
    )
    sentinel = MildSteel(**values, active_in_compression=True)
    tension_only = MildSteel(**values, active_in_compression=False)

    sentinel_result = plastic_capacity_at_angle(
        section, _C30, sentinel, 0.0, 90.0
    )
    tension_only_result = plastic_capacity_at_angle(
        section, _C30, tension_only, 0.0, 90.0
    )

    assert sentinel_result.Mx == pytest.approx(tension_only_result.Mx)
    assert sentinel_result.My == pytest.approx(tension_only_result.My)
    assert sentinel_result.curvature == pytest.approx(
        tension_only_result.curvature
    )
    assert sentinel_result.curvature_selection.selected_mode == (
        tension_only_result.curvature_selection.selected_mode
    )
    assert not any(
        candidate.mode == "bar_compression_rupture"
        for candidate in sentinel_result.curvature_selection.candidates
    )


def test_plastic_capacity_responds_to_ultimate_strain():
    # The solver must use the concrete's own eps_cu2/eps_c2: with the steel forced
    # to govern by yield (no rupture), changing the crushing strain reshapes the
    # compression stress block, so the ultimate moment changes.
    b, h, cover, As_mm2 = 1.0, 0.30, 0.04, 2000.0
    slab = Section.from_polygon(
        corners=[(-b / 2, 0.0), (-b / 2, h), (b / 2, h), (b / 2, 0.0)],
        bars_xy_area_mm2=[(0.0, cover, As_mm2)],
    )
    steel = MildSteel(fytk=500.0, fyck=500.0, eut=1.0, gamma_y=1.15, curve=2)
    full = Concrete(fck=30.0, gamma_c=1.5, curve=2)                  # eps_cu2 = 3.5 permille
    short = Concrete(fck=30.0, gamma_c=1.5, curve=2, eps_cu2=0.0022)  # almost no plateau
    m_full = plastic_capacity_at_angle(slab, full, steel, 0.0, 90.0).Mx
    m_short = plastic_capacity_at_angle(slab, short, steel, 0.0, 90.0).Mx
    assert abs(m_full - m_short) / m_full > 0.003   # eps_cu2 visibly changes Mrd


def _rect_with_top_and_bottom_bars():
    return Section.from_polygon(
        corners=[(0.0, 0.0), (0.3, 0.0), (0.3, 0.6), (0.0, 0.6)],
        bars_xy_area_mm2=[(0.15, 0.05, 500.0), (0.15, 0.55, 500.0)],
    )


_C30 = Concrete(fck=30.0, gamma_c=1.5, curve=2)
_B500 = MildSteel(fytk=500.0, fyck=500.0, futk=500.0, eut=0.05,
                  gamma_y=1.15, gamma_u=1.15, gamma_E=1.0, curve=1)


def test_all_compressed_section_reports_the_bar_strain():
    # Under high axial compression every bar is compressed; the reported most-tensile
    # steel strain is the least-compressed bar's actual (positive) strain, not a
    # floor of zero.
    r = plastic_capacity_at_angle(_rect_with_top_and_bottom_bars(), _C30, _B500,
                                  3500.0, 90.0)
    assert r.converged
    assert r.eps_steel > 0.0


def test_unreachable_axial_is_flagged_not_converged():
    # An axial force above the squash load cannot be balanced: the point is flagged
    # not-converged (non-zero equilibrium residual), while a reachable one converges.
    sec = _rect_with_top_and_bottom_bars()
    assert not plastic_capacity_at_angle(sec, _C30, _B500, 1.0e6, 90.0).converged
    assert plastic_capacity_at_angle(sec, _C30, _B500, 0.0, 90.0).converged


def test_shared_prep_matches_standalone_solve():
    # solve_plastic builds the angle-independent prep once and reuses it across the
    # sweep (and shares the kernel scratch buffers). Each swept point must be bit-for-
    # bit identical to a standalone plastic_capacity_at_angle (prep=None) at the same
    # angle -- the hoist is a pure speed-up, not a change of result.
    section, concrete, steel = fundamentsbjaelke()
    swept = solve_plastic(section, concrete, steel, 150.0, 0.0, 360.0, 12.0)
    for p in swept:
        d = plastic_capacity_at_angle(section, concrete, steel, 150.0, p.V)
        assert p.Mx == d.Mx and p.My == d.My and p.axial == d.axial
        assert p.compression_force == d.compression_force
        assert p.curvature == d.curvature and p.lever_arm == d.lever_arm


def test_band_stress_memo_collapses_equal_kappa_h_and_preserves_values():
    # The band-midpoint strain is kappa*(i+0.5)*h -- the neutral-axis depth cancels --
    # so the band stresses are a function of the product kappa*h alone. The per-sweep
    # memo (v0.71) exploits that: two calls with the same kappa*h but different splits
    # collapse to one cached array, and memoization does not change the values a
    # no-memo call produces.
    conc = Concrete(fck=35.0, gamma_c=1.5, curve=2)
    memo: dict = {}
    a = _band_stresses(conc, 0.020, 0.0010, 40, memo=memo)   # kappa*h = 2.0e-5
    b = _band_stresses(conc, 0.040, 0.0005, 40, memo=memo)   # kappa*h = 2.0e-5
    assert a is b and len(memo) == 1                          # one cached array, reused
    assert np.allclose(a, _band_stresses(conc, 0.020, 0.0010, 40),
                       rtol=0.0, atol=1e-12)                  # memo preserves the values


def test_plastic_capacity_uses_each_bars_assigned_material():
    # Positive Mx puts the lower bar in tension. Swapping a 300 MPa and 600 MPa
    # material between the two positions must therefore change the capacity; the
    # scalar API remains exactly equivalent to repeating one material per element.
    section = Section.from_polygon(
        corners=[(0.0, 0.0), (0.3, 0.0), (0.3, 0.6), (0.0, 0.6)],
        bars_xy_area_mm2=[(0.15, 0.05, 1000.0), (0.15, 0.55, 1000.0)],
    )
    low = MildSteel(fytk=300.0, fyck=300.0, futk=300.0, eut=0.05,
                    gamma_y=1.15, gamma_u=1.15, curve=1)
    high = MildSteel(fytk=600.0, fyck=600.0, futk=600.0, eut=0.05,
                     gamma_y=1.15, gamma_u=1.15, curve=1)

    weak_tension = plastic_capacity_at_angle(
        section, _C30, low, 0.0, 90.0, bar_materials=[low, high]
    )
    strong_tension = plastic_capacity_at_angle(
        section, _C30, low, 0.0, 90.0, bar_materials=[high, low]
    )
    scalar = plastic_capacity_at_angle(section, _C30, high, 0.0, 90.0)
    repeated = plastic_capacity_at_angle(
        section, _C30, low, 0.0, 90.0, bar_materials=[high, high]
    )

    assert weak_tension.converged and strong_tension.converged
    assert strong_tension.Mx > 1.8 * weak_tension.Mx
    assert repeated.Mx == scalar.Mx
    assert repeated.My == scalar.My


def test_plastic_capacity_rejects_incomplete_material_assignment(monkeypatch):
    import sector.plastic as plastic_core

    section = _rect_with_top_and_bottom_bars()
    calls = []

    def forbidden_accumulation(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("material-count mismatch reached plastic iteration")

    monkeypatch.setattr(plastic_core, "_accumulate", forbidden_accumulation)
    with pytest.raises(ValueError, match="need 2 bar materials, got 1"):
        plastic_capacity_at_angle(
            section, _C30, _B500, 0.0, 90.0, bar_materials=[_B500]
        )
    assert calls == []


@pytest.mark.parametrize(
    ("label", "material_assignment"),
    (
        ("bar", {"bar_materials": [_B500]}),
        ("tendon", {"tendon_materials": [object()]}),
    ),
)
def test_plastic_capacity_rejects_material_for_empty_element_family(
    monkeypatch,
    label,
    material_assignment,
):
    import sector.plastic as plastic_core

    section = Section.from_polygon(
        corners=[(0.0, 0.0), (0.3, 0.0), (0.3, 0.6), (0.0, 0.6)],
    )
    calls = []

    def forbidden_accumulation(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("zero-count material mismatch reached plastic iteration")

    monkeypatch.setattr(plastic_core, "_accumulate", forbidden_accumulation)
    with pytest.raises(ValueError, match=f"need 0 {label} materials, got 1"):
        plastic_capacity_at_angle(
            section,
            _C30,
            _B500,
            0.0,
            90.0,
            **material_assignment,
        )
    assert calls == []


@pytest.mark.parametrize(
    ("P", "V_deg"),
    (
        (float("nan"), 90.0),
        (0.0, float("inf")),
        (np.bool_(True), 90.0),
        (0.0, np.bool_(False)),
    ),
)
def test_invalid_actions_are_rejected_before_plastic_iteration(
    monkeypatch,
    P,
    V_deg,
):
    import sector.plastic as plastic_core

    calls = []

    def forbidden_accumulation(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("invalid action reached plastic iteration")

    monkeypatch.setattr(plastic_core, "_accumulate", forbidden_accumulation)

    with pytest.raises(ValueError, match="finite"):
        plastic_capacity_at_angle(
            _rect_with_top_and_bottom_bars(),
            _C30,
            _B500,
            P,
            V_deg,
        )
    assert calls == []


@pytest.mark.parametrize(
    "invalid_tendon",
    (
        Bar(0.0, 0.0, 0.0),
        Bar(np.bool_(True), 0.0, 1.0e-6),
        Bar(0.0, 0.0, True),
    ),
)
def test_mutated_invalid_tendon_is_rejected_before_plastic_iteration(
    monkeypatch,
    invalid_tendon,
):
    import sector.plastic as plastic_core

    section = _rect_with_top_and_bottom_bars()
    section.tendons = [invalid_tendon]
    calls = []

    def forbidden_accumulation(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("invalid tendon reached plastic iteration")

    monkeypatch.setattr(plastic_core, "_accumulate", forbidden_accumulation)

    with pytest.raises(ValueError, match="tendon 1"):
        plastic_capacity_at_angle(section, _C30, _B500, 0.0, 90.0)
    assert calls == []
