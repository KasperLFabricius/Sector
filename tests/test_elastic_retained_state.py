"""Focused checks for PR-03's compact elastic final-state publication data."""

from __future__ import annotations

from dataclasses import fields

import numpy as np
import pytest

from sector.elastic import (
    ElasticEquilibrium,
    solve_elastic,
    solve_elastic_combined,
    solve_elastic_uncracked,
)
from sector.section import Section


def _section() -> Section:
    return Section.from_polygon(
        corners=[(-0.5, -0.5), (-0.5, 0.5), (0.5, 0.5), (0.5, -0.5)],
        bars_xy_area_mm2=[
            (-0.45, -0.45, 491.0),
            (-0.45, 0.45, 491.0),
            (0.45, 0.45, 491.0),
            (0.45, -0.45, 491.0),
        ],
    )


def test_cracked_result_retains_only_the_accepted_final_equilibrium_state() -> None:
    result = solve_elastic(_section(), 900.0, 300.0, -100.0, 25.0)
    state = result.equilibrium

    assert result.raw_stress_plane == result.strain_plane
    assert state.target.values == pytest.approx((-900.0, -300.0, 100.0))
    assert np.asarray(state.equilibrium_matrix) @ np.asarray(
        result.raw_stress_plane
    ) == pytest.approx(state.internal.values)
    assert np.asarray(state.internal.values) - np.asarray(
        state.target.values
    ) == pytest.approx(state.residual.values)
    assert state.normalised_residual == pytest.approx(
        max(abs(value) for value in state.residual.values) / state.residual_scale
    )
    # This deliberately reproduces the solver's fixed [kN, kNm, kNm] numeric
    # max convention; it must not be presented as a physical force/moment norm.
    assert state.residual_scale == pytest.approx(900.0)
    assert state.normalised_residual <= state.relative_tolerance

    # The family record is immutable/slotted and contains no raw iteration data.
    assert not hasattr(state, "__dict__")
    assert {field.name for field in fields(ElasticEquilibrium)} == {
        "equilibrium_matrix",
        "target",
        "internal",
        "residual",
        "residual_scale",
        "normalised_residual",
        "relative_tolerance",
    }


def test_max_iteration_exit_retains_state_at_the_plane_actually_returned() -> None:
    result = solve_elastic(
        _section(), 1000.0, 200.0, 200.0, 25.0, max_iter=1
    )

    assert result.iterations == 1
    assert np.asarray(result.equilibrium.equilibrium_matrix) @ np.asarray(
        result.raw_stress_plane
    ) == pytest.approx(result.equilibrium.internal.values)


def test_uncracked_linear_solve_retains_its_equilibrium_basis() -> None:
    result = solve_elastic_uncracked(_section(), 500.0, 40.0, -20.0, 8.0)

    assert result.converged
    assert result.iterations == 0
    assert result.equilibrium.target.values == pytest.approx((-500.0, -40.0, 20.0))
    assert result.equilibrium.normalised_residual == pytest.approx(0.0, abs=1.0e-15)
    assert result.equilibrium.relative_tolerance is None


def test_combined_result_retains_the_existing_superposition_operands() -> None:
    section = _section()
    result = solve_elastic_combined(
        section, 1000.0, 200.0, 200.0, 25.0, 300.0, 60.0, 40.0, 8.0
    )
    bx, by, area = section.bar_arrays()

    factor = 1.0 - 8.0 / 25.0
    assert result.long_term_modular_ratio == pytest.approx(25.0)
    assert result.short_term_modular_ratio == pytest.approx(8.0)
    assert result.long_term_reduction_factor == pytest.approx(factor)
    assert result.bar_stress_reduced_long == pytest.approx(
        result.bar_stress_long_passive * factor
    )

    reduced_force = result.bar_stress_reduced_long * area
    expected_neutralising = (
        float(reduced_force.sum()),
        float((reduced_force * by).sum()),
        float((reduced_force * bx).sum()),
    )
    assert result.neutralising_resultant.values == pytest.approx(
        expected_neutralising
    )
    assert result.combined_target_before_neutralisation.values == pytest.approx(
        (-1300.0, -260.0, -240.0)
    )
    assert result.short_term.equilibrium.target.values == pytest.approx(
        np.asarray(result.combined_target_before_neutralisation.values)
        - np.asarray(result.neutralising_resultant.values)
    )
    assert result.bar_stress_total == pytest.approx(
        result.bar_stress_reduced_long
        + result.bar_stress_rst1
        + result.bar_stress_locked_in
    )
    assert result.bar_stress_locked_in == pytest.approx(np.zeros(4))
    assert result.long.iterations > 0
    assert result.short_term.iterations > 0


def test_combined_result_retains_exact_locked_in_stress_operand() -> None:
    locked_in = np.asarray([0.0, 0.0, 140_000.0, 140_000.0])
    expected_locked_in = locked_in.copy()
    result = solve_elastic_combined(
        _section(),
        1000.0,
        200.0,
        200.0,
        25.0,
        300.0,
        60.0,
        40.0,
        8.0,
        prestress_stress=locked_in,
    )
    locked_in[:] = -1.0

    assert result.bar_stress_locked_in == pytest.approx(expected_locked_in)
    assert result.bar_stress_long == pytest.approx(
        result.bar_stress_long_passive + expected_locked_in
    )
    assert result.bar_stress_total == pytest.approx(
        result.bar_stress_reduced_long
        + result.bar_stress_rst1
        + expected_locked_in
    )
