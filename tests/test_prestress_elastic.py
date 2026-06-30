"""Prestress in the elastic / serviceability analysis.

The tendon initial strain is applied as a locked-in prestress force, so the
external ``N`` means the same thing as in the plastic solver. These tests pin the
sign and structure: applying the prestress through ``prestress_stress`` must equal
applying the equivalent force (axial + eccentric moment) to the load by hand, and
the prestress must delay cracking.
"""

from __future__ import annotations

import numpy as np
import pytest

from sector.elastic import _steel_resultant, solve_elastic_combined
from sector.section import Section
from sector.serviceability import analyse_cracking


def _section():
    # 0.3 x 0.6 m rectangle: two mild bars near the top, one tendon near the
    # bottom (eccentric), folded as bars + tendon.
    return Section.from_polygon(
        corners=[(-0.15, -0.3), (-0.15, 0.3), (0.15, 0.3), (0.15, -0.3)],
        bars_xy_area_mm2=[(-0.1, 0.25, 500.0), (0.1, 0.25, 500.0),
                          (0.0, -0.25, 1000.0)])


@pytest.mark.parametrize("sigma_ps", [0.8e6, 1.4e6])
def test_prestress_force_equals_manual_axial_plus_moment(sigma_ps):
    # Applying the tendon prestress via prestress_stress must give the same
    # concrete state as adding its force (axial + eccentric moment) to the load by
    # hand, and the tendon's reported stress is the passive increment + Ep*IS.
    sec = _section()
    n_mild = 6.0
    n_mult = np.array([1.0, 1.0, 6.2 / 6.0])           # tendon Ep/Es
    ps = np.array([0.0, 0.0, sigma_ps])
    n_ext, mx_ext = 100.0, 80.0

    auto = solve_elastic_combined(sec, n_ext, mx_ext, 0.0, n_mild, 0.0, 0.0, 0.0,
                                  n_mild, n_mult=n_mult, prestress_stress=ps)
    bx, by, ba = sec.bar_arrays()
    pre = _steel_resultant(ps, bx, by, ba)             # [N, Mx, My] of the prestress
    manual = solve_elastic_combined(sec, n_ext + pre[0], mx_ext + pre[1], pre[2],
                                    n_mild, 0.0, 0.0, 0.0, n_mild, n_mult=n_mult)

    # Same concrete state (the net target is identical).
    assert auto.max_concrete_compression == pytest.approx(
        manual.max_concrete_compression, rel=1e-9)
    for a, m in ((auto.na_x_intercept, manual.na_x_intercept),
                 (auto.na_y_intercept, manual.na_y_intercept)):
        assert a == m if not np.isfinite(a) else a == pytest.approx(m, rel=1e-9)
    # Mild bars unchanged; the tendon carries the extra locked-in prestress.
    assert np.allclose(auto.bar_stress_total[:2], manual.bar_stress_total[:2])
    assert auto.bar_stress_total[2] == pytest.approx(manual.bar_stress_total[2] + sigma_ps)
    # The prestress cancels out of the long->total difference.
    assert np.allclose(auto.bar_stress_dif, manual.bar_stress_dif)


def test_no_prestress_array_is_a_no_op():
    # Omitting prestress_stress (no tendons) reproduces the plain analysis exactly.
    sec = _section()
    base = solve_elastic_combined(sec, 100.0, 80.0, 0.0, 6.0, 0.0, 0.0, 0.0, 6.0)
    same = solve_elastic_combined(sec, 100.0, 80.0, 0.0, 6.0, 0.0, 0.0, 0.0, 6.0,
                                  prestress_stress=None, n_mult=None)
    assert np.allclose(base.bar_stress_total, same.bar_stress_total)


def test_prestress_delays_cracking():
    # A concentric tendon's prestress is pure axial compression, which lowers the
    # peak concrete tension: a section that cracks under a moment stays uncracked
    # once the prestress is applied.
    sec = Section.from_polygon(
        corners=[(-0.15, -0.3), (-0.15, 0.3), (0.15, 0.3), (0.15, -0.3)],
        bars_xy_area_mm2=[(-0.1, 0.25, 500.0), (0.1, 0.25, 500.0),
                          (0.0, 0.0, 1000.0)])          # concentric tendon
    n = 6.0
    n_mult = np.array([1.0, 1.0, 1.0])
    ps = np.array([0.0, 0.0, 2.0e6])                    # tendon prestress (axial)
    common = dict(fctm=3.2, Es=200000.0, beta=0.5, kt=0.4)

    cracked_no_ps = analyse_cracking(sec, 0.0, 80.0, 0.0, n, **common)
    uncracked_ps = analyse_cracking(sec, 0.0, 80.0, 0.0, n, n_mult=n_mult,
                                    prestress_stress=ps, **common)

    assert cracked_no_ps.cracked          # cracks without prestress
    assert not uncracked_ps.cracked       # prestress keeps it uncracked
    assert uncracked_ps.lambda_cr >= 1.0
