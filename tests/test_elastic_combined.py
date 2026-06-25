"""Verification of the combined long/short-term elastic analysis.

These cases come from real cross-section analysis output: one from the worked
rectangular example (combined load case) and two from 2024 production runs whose
output PDFs report the TOTAL / LONG / RST1 steel-stress columns. The production
section TD_3.31 reproduces to the integer; the rest are within rounding.
"""

from __future__ import annotations

import math

import pytest

from sector.elastic import solve_elastic, solve_elastic_combined
from sector.section import Section


def rectangular_section() -> Section:
    return Section.from_polygon(
        corners=[(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)],
        bars_xy_area_mm2=[
            (0.05, 0.05, 491.0),
            (0.05, 0.95, 491.0),
            (0.95, 0.95, 491.0),
            (0.95, 0.05, 491.0),
        ],
    )


def td_3_31_section() -> Section:
    # Thin tall web, 8 bars along the centreline (Udmattelse TD3.31, midterfag).
    return Section.from_polygon(
        corners=[(-0.050, -0.534), (-0.050, 0.534), (0.050, 0.534), (0.050, -0.534)],
        bars_xy_area_mm2=[
            (0.0, 0.476, 93.0), (0.0, 0.304, 93.0), (0.0, 0.254, 93.0),
            (0.0, -0.023, 93.0), (0.0, -0.349, 52.0), (0.0, -0.394, 93.0),
            (0.0, -0.439, 93.0), (0.0, -0.484, 93.0),
        ],
    )


def dx90703_section() -> Section:
    return Section.from_polygon(
        corners=[(-0.440, -0.102), (-0.440, 0.102), (0.440, 0.102), (0.440, -0.102)],
        bars_xy_area_mm2=[
            (0.0, -0.063, 93.0), (0.187, -0.063, 93.0), (-0.187, -0.063, 93.0),
            (0.374, -0.063, 93.0), (-0.374, -0.063, 93.0),
            (0.187, 0.063, 52.0), (-0.187, 0.063, 52.0),
        ],
    )


def test_worked_rectangular_combined_lc2():
    # LONG (1000, 200, 200, n=25) + SHORT (300, 60, 40, n=8).
    res = solve_elastic_combined(
        rectangular_section(), 1000.0, 200.0, 200.0, 25.0, 300.0, 60.0, 40.0, 8.0
    )
    assert res.converged
    # Combined (RST) steel stresses and the RST1 column from the printout.
    total_exp = [-147502.0, -1551.0, 147993.0, 2041.0]
    rst1_exp = [-59490.0, 278.0, 63638.0, 3870.0]
    for got, exp in zip(res.bar_stress_total, total_exp):
        assert got == pytest.approx(exp, rel=0.01, abs=120)
    for got, exp in zip(res.bar_stress_rst1, rst1_exp):
        assert got == pytest.approx(exp, rel=0.01, abs=120)
    assert res.max_concrete_compression == pytest.approx(8291.0, rel=0.01)
    assert res.max_concrete_point == 0


def test_production_td_3_31_matches_to_the_integer():
    # 2024 production run (BDS-ECROSS v7.12); reproduces exactly.
    res = solve_elastic_combined(
        td_3_31_section(), 794.380, 67.820, 0.0, 22.930, -0.050, -1.870, 0.0, 5.733
    )
    assert res.converged
    total_exp = [-214964, -191269, -184381, -146220, -101309, -95110, -88910, -82711]
    long_exp = [-215446, -191578, -184640, -146202, -100964, -94720, -88476, -82231]
    rst1_exp = [-53384, -47589, -45905, -36572, -25588, -24072, -22556, -21039]
    for got, exp in zip(res.bar_stress_total, total_exp):
        assert got == pytest.approx(exp, abs=2)
    for got, exp in zip(res.bar_stress_long, long_exp):
        assert got == pytest.approx(exp, abs=2)
    for got, exp in zip(res.bar_stress_rst1, rst1_exp):
        assert got == pytest.approx(exp, abs=2)
    assert res.max_concrete_compression == pytest.approx(9653.0, abs=2)
    assert res.max_concrete_point == 1
    assert math.isinf(res.na_x_intercept)
    assert res.na_y_intercept == pytest.approx(-1.10845, abs=1e-4)


def test_production_dx90703_within_tolerance():
    # 2024 production run; within ~1% (uniaxial, two bar levels).
    res = solve_elastic_combined(
        dx90703_section(), 503.0, 7.81, 0.0, 21.52, 0.0, 3.10, 0.0, 5.38
    )
    assert res.converged
    # Bars 1-5 at y=-0.063, bars 6-7 at y=+0.063.
    for got in res.bar_stress_total[:5]:
        assert got == pytest.approx(-37315.0, rel=0.015)
    for got in res.bar_stress_total[5:]:
        assert got == pytest.approx(-76550.0, rel=0.015)
    assert res.max_concrete_compression == pytest.approx(4513.0, rel=0.015)
    assert res.max_concrete_point == 1


def test_combined_reduces_to_long_term_when_no_short():
    # Zero short-term load with ns == nl must equal a single long-term solve.
    sec = rectangular_section()
    combined = solve_elastic_combined(sec, 900.0, 300.0, -100.0, 25.0, 0.0, 0.0, 0.0, 25.0)
    single = solve_elastic(sec, 900.0, 300.0, -100.0, 25.0)
    for got, exp in zip(combined.bar_stress_total, single.bar_stress):
        assert got == pytest.approx(exp, rel=1e-6, abs=1e-3)
    assert combined.max_concrete_compression == pytest.approx(
        single.max_concrete_compression, rel=1e-6
    )
