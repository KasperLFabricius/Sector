"""The compiled concrete kernel must agree with the pure-Python path.

When Numba is installed the plastic solver integrates the concrete in a compiled
kernel; without it, the same work runs in Python. These tests pin the two paths
together so the acceleration can never silently change a result. (With Numba
absent both paths are the Python one, and the parity check is trivially true.)
"""

from __future__ import annotations

import pytest

import sector.plastic as plastic
from sector import kernels, templates
from sector.materials import Concrete, MildSteel
from sector.plastic import solve_plastic
from sector.section import Section


def _box_section():
    outer, holes = templates.box(0.8, 1.0, 0.15)
    bars = templates.merge_bars(
        templates.bar_row(-0.45, -0.35, 0.35, 6, 25),
        templates.bar_row(0.45, -0.35, 0.35, 4, 20),
    )
    return Section.from_polygon(corners=outer, bars_xy_area_mm2=bars, holes=holes)


def _materials():
    conc = Concrete(fck=35.0, gamma_c=1.5, curve=2)
    steel = MildSteel(fytk=500.0, fyck=500.0, eut=0.05, gamma_y=1.15, curve=2)
    return conc, steel


def test_warmup_runs_and_reports_backend():
    assert isinstance(kernels.warmup(), bool)
    assert kernels.warmup() is kernels.HAS_NUMBA


def test_kernel_matches_pure_python(monkeypatch):
    sec = _box_section()
    conc, steel = _materials()

    # As configured (compiled when Numba is present).
    pts_fast = solve_plastic(sec, conc, steel, 1500.0, 0.0, 180.0, 30.0)

    # Force the pure-Python concrete path.
    monkeypatch.setattr(plastic, "_USE_KERNEL", False)
    pts_ref = solve_plastic(sec, conc, steel, 1500.0, 0.0, 180.0, 30.0)

    assert len(pts_fast) == len(pts_ref)
    for a, b in zip(pts_fast, pts_ref):
        assert a.Mx == pytest.approx(b.Mx, rel=1e-9, abs=1e-6)
        assert a.My == pytest.approx(b.My, rel=1e-9, abs=1e-6)
        assert a.curvature == pytest.approx(b.curvature, rel=1e-9)
        assert a.eps_concrete == pytest.approx(b.eps_concrete, rel=1e-9, abs=1e-9)


def test_kernel_matches_pure_python_with_axial_tension(monkeypatch):
    # A different load (net tension) exercises the deep-compression branch.
    sec = _box_section()
    conc, steel = _materials()

    pts_fast = solve_plastic(sec, conc, steel, -800.0, 90.0, 90.0, 45.0)
    monkeypatch.setattr(plastic, "_USE_KERNEL", False)
    pts_ref = solve_plastic(sec, conc, steel, -800.0, 90.0, 90.0, 45.0)

    for a, b in zip(pts_fast, pts_ref):
        assert a.Mx == pytest.approx(b.Mx, rel=1e-9, abs=1e-6)
        assert a.My == pytest.approx(b.My, rel=1e-9, abs=1e-6)
