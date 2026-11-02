"""Concrete fatigue fibre search: the box bound is an upper bound (review TA-01).

The bound of a box splits into the part where both stress states are in
compression (R takes its minimum at a vertex) and the part where only one is
(R = 0). The tests check the bound against a dense sample of the damage field
and check that a case which the former bound could not resolve converges.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from sector import fatigue as F
from sector.section import Section


def _random_case(rng, trial):
    count = int(rng.integers(1, 4))
    method = (
        F.CONCRETE_EQUIVALENT
        if trial % 2
        else sorted(F.CONCRETE_MINER_METHODS)[0]
    )
    long_planes, total_planes = [], []
    for _ in range(count):
        # Compression-positive planes in MPa: c0 + cx x + cy y. The ranges make
        # the zero lines cross many boxes.
        long_plane = (
            rng.uniform(-5.0, 12.0), rng.uniform(-40.0, 40.0),
            rng.uniform(-40.0, 40.0),
        )
        total_plane = (
            long_plane[0] + rng.uniform(-6.0, 6.0),
            long_plane[1] + rng.uniform(-20.0, 20.0),
            long_plane[2] + rng.uniform(-20.0, 20.0),
        )
        long_planes.append(long_plane)
        total_planes.append(total_plane)
    data = F._ConcreteSearchData(
        long_planes=np.asarray(long_planes, float),
        total_planes=np.asarray(total_planes, float),
        log10_cycles=np.log10(rng.uniform(1.0e4, 1.0e9, count)),
        strength_mpa=20.0,
        coefficient_c=14.0,
        method=method,
    )
    x0, y0 = rng.uniform(-0.3, 0.2, 2)
    width, height = rng.uniform(0.005, 0.3, 2)
    return data, (x0, x0 + width, y0, y0 + height)


def test_box_bound_is_not_below_the_sampled_damage():
    rng = np.random.default_rng(12345)
    checked = 0
    for trial in range(400):
        data, box = _random_case(rng, trial)
        bound = F._box_damage_upper_bound(box, data)
        if math.isinf(bound):
            continue
        xs = np.linspace(box[0], box[1], 41)
        ys = np.linspace(box[2], box[3], 41)
        grid_x, grid_y = np.meshgrid(xs, ys)
        points = np.column_stack((grid_x.ravel(), grid_y.ravel()))
        sampled = float(np.max(F._search_damage_field(points, data)))
        assert sampled <= bound * (1.0 + 1.0e-9) + 1.0e-300
        checked += 1
    assert checked > 300


def test_search_converges_where_one_state_is_in_tension():
    # 300 x 600 mm beam, three 25 mm bars, 1e7 cycles. The bending moments put
    # the neutral axes inside the section, so many boxes have one state in
    # compression and one in tension. The former bound did not converge here.
    section = Section.from_polygon(
        corners=[(0.0, 0.0), (0.3, 0.0), (0.3, 0.6), (0.0, 0.6)],
        bars_xy_area_mm2=[(0.05, 0.05, 491.0), (0.15, 0.05, 491.0),
                          (0.25, 0.05, 491.0)],
    )
    concrete = F.ConcreteFatigueProperties(
        edition="2004", fck_mpa=30.0, gamma_c=1.5, beta_cc_t0=1.0,
        method=F.CONCRETE_PROJECT_MINER, c=10.0,
    )
    bins = [F.SpectrumBin("b1", 1.0e7, mx_long_knm=20.0, mx_short_knm=10.0)]
    result = F.analyse_fatigue_spectrum(
        "S", section, bins, 6.0, 6.0, concrete=concrete,
        check_reinforcement=False,
    )
    search = result.concrete_search
    assert search.converged is True
    assert search.upper_damage >= search.damage
    assert search.upper_damage - search.damage <= 1.0e-4 + 1.0e-3 * search.damage
    assert result.passed is True
    assert search.boxes_evaluated < 1000


@pytest.mark.parametrize("value", (0.0, -1.0e-4, math.nan))
def test_search_tolerance_must_be_positive(value):
    section = Section.from_polygon(
        corners=[(0.0, 0.0), (0.3, 0.0), (0.3, 0.6), (0.0, 0.6)],
        bars_xy_area_mm2=[(0.15, 0.05, 491.0)],
    )
    concrete = F.ConcreteFatigueProperties(
        edition="2004", fck_mpa=30.0, gamma_c=1.5, beta_cc_t0=1.0,
        method=F.CONCRETE_PROJECT_MINER, c=10.0,
    )
    bins = [F.SpectrumBin("b1", 1.0e6, mx_long_knm=5.0, mx_short_knm=5.0)]
    with pytest.raises(ValueError):
        F.analyse_fatigue_spectrum(
            "S", section, bins, 6.0, 6.0, concrete=concrete,
            check_reinforcement=False,
            concrete_search_absolute_tolerance=value,
        )
