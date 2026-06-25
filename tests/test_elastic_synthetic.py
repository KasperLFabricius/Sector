"""Property / sanity checks of the elastic solver on varied synthetic sections.

There are only a handful of legacy ECROSS examples, so these complement them by
exercising the solver on a range of geometries (including voids) and loads and
asserting that the results behave correctly. The central check is *equilibrium*:
the resultant of the stresses Sector computes, re-derived independently from the
public geometry primitives, must equal the applied load. That validates the
whole pipeline on arbitrary shapes.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from sector.elastic import solve_elastic
from sector.geometry import area_moments, clip_halfplane
from sector.section import Section


def internal_resultants(section: Section, res, n: float):
    """Re-derive [N, Mx, My] (tension positive) from the solved strain plane.

    Computed only from the public geometry helpers, independently of the
    solver's own internals, so agreement with the applied load is a genuine
    equilibrium check.
    """
    eps0, kx, ky = res.strain_plane
    n_, mx, my = 0.0, 0.0, 0.0
    for ring in section.integration_rings():
        clipped = clip_halfplane(ring, -kx, -ky, -eps0)  # compression zone
        m = area_moments(clipped)
        n_ += eps0 * m.area + kx * m.sx + ky * m.sy
        mx += eps0 * m.sy + kx * m.sxy + ky * m.syy
        my += eps0 * m.sx + kx * m.sxx + ky * m.sxy
    x, y, a = section.bar_arrays()
    if x.size:
        f = n * (eps0 + kx * x + ky * y) * a
        n_ += f.sum()
        mx += (f * y).sum()
        my += (f * x).sum()
    return n_, mx, my


# -- a library of varied synthetic sections ---------------------------------


def t_section() -> Section:
    # T-beam: 1.2 m wide x 0.2 m flange over a 0.3 m x 0.6 m web.
    corners = [
        (-0.60, 0.20), (0.60, 0.20), (0.60, 0.0), (0.15, 0.0),
        (0.15, -0.60), (-0.15, -0.60), (-0.15, 0.0), (-0.60, 0.0),
    ]
    bars = [
        (-0.10, -0.55, 314.0), (0.10, -0.55, 314.0),
        (-0.45, 0.15, 201.0), (0.45, 0.15, 201.0),
    ]
    return Section.from_polygon(corners=corners, bars_xy_area_mm2=bars)


def box_with_void() -> Section:
    # 0.8 m x 1.0 m box girder with a 0.4 m x 0.6 m internal void.
    outer = [(-0.40, -0.50), (0.40, -0.50), (0.40, 0.50), (-0.40, 0.50)]
    void = [(-0.20, -0.30), (0.20, -0.30), (0.20, 0.30), (-0.20, 0.30)]
    bars = [
        (-0.33, -0.43, 314.0), (0.33, -0.43, 314.0),
        (-0.33, 0.43, 314.0), (0.33, 0.43, 314.0),
    ]
    sec = Section.from_polygon(corners=outer, bars_xy_area_mm2=bars, holes=[void])
    return sec


def prestress_like_section() -> Section:
    # In elastic analysis a tendon is just a bonded bar (its prestress force is
    # applied as part of the load); the distinct prestress material belongs to
    # the plastic analysis. Here a low tendon acts as ordinary reinforcement.
    corners = [(-0.30, -0.40), (0.30, -0.40), (0.30, 0.40), (-0.30, 0.40)]
    bars = [(-0.20, 0.33, 201.0), (0.20, 0.33, 201.0), (0.0, -0.34, 1000.0)]
    return Section.from_polygon(corners=corners, bars_xy_area_mm2=bars)


SECTIONS = {
    "t_section": t_section,
    "box_with_void": box_with_void,
    "prestress_like": prestress_like_section,
}

LOADS = [
    (2000.0, 150.0, 0.0, 15.0),     # mostly axial + uniaxial bending
    (500.0, 400.0, 250.0, 12.0),    # biaxial bending, moderate axial
    (100.0, 600.0, -300.0, 18.0),   # bending dominated, biaxial
    (-50.0, 200.0, 0.0, 10.0),      # slight tension + bending
]


@pytest.mark.parametrize("name", list(SECTIONS), ids=list(SECTIONS))
@pytest.mark.parametrize("load", LOADS, ids=[f"P{int(l[0])}" for l in LOADS])
def test_equilibrium_holds(name, load):
    P, Mx, My, n = load
    sec = SECTIONS[name]()
    res = solve_elastic(sec, P, Mx, My, n)
    assert res.converged
    N_int, Mx_int, My_int = internal_resultants(sec, res, n)
    # Internal resultants must equal the applied load (tension-positive: -P etc).
    scale = max(1.0, abs(P), abs(Mx), abs(My))
    assert N_int == pytest.approx(-P, abs=1e-6 * scale)
    assert Mx_int == pytest.approx(-Mx, abs=1e-6 * scale)
    assert My_int == pytest.approx(-My, abs=1e-6 * scale)


def test_void_increases_stress_versus_solid():
    # Removing material (a void) makes the section more flexible, so under the
    # same bending the extreme concrete compression is larger than for the solid.
    solid = Section.from_polygon(
        corners=[(-0.40, -0.50), (0.40, -0.50), (0.40, 0.50), (-0.40, 0.50)],
        bars_xy_area_mm2=[(-0.33, -0.43, 314.0), (0.33, -0.43, 314.0),
                          (-0.33, 0.43, 314.0), (0.33, 0.43, 314.0)],
    )
    holed = box_with_void()
    load = (300.0, 500.0, 0.0, 15.0)
    s = solve_elastic(solid, *load)
    h = solve_elastic(holed, *load)
    assert h.converged and s.converged
    assert h.max_concrete_compression > s.max_concrete_compression


def test_symmetric_section_no_cross_curvature_under_uniaxial_moment():
    # Doubly-symmetric box about the origin, uniaxial moment about X (My=0):
    # the strain plane must not tilt in x.
    sec = box_with_void()
    res = solve_elastic(sec, 400.0, 300.0, 0.0, 15.0)
    assert res.kx == pytest.approx(0.0, abs=1e-6 * abs(res.ky))
    # And with My=0 the neutral axis is horizontal -> no finite x-intercept.
    assert math.isinf(res.na_x_intercept)


def test_max_compression_grows_with_moment():
    sec = t_section()
    comps = [
        solve_elastic(sec, 300.0, m, 0.0, 15.0).max_concrete_compression
        for m in (0.0, 200.0, 400.0, 600.0)
    ]
    assert all(b > a for a, b in zip(comps, comps[1:]))


def test_tension_face_steel_goes_into_tension():
    # Strong bending about X on the box: the bottom bars (tension face) must end
    # up in tension (positive), the top bars in compression.
    sec = box_with_void()
    res = solve_elastic(sec, 100.0, 700.0, 0.0, 15.0)
    bottom = res.bar_stress[:2]  # y = -0.43
    top = res.bar_stress[2:]     # y = +0.43
    assert np.all(bottom > 0.0)
    assert np.all(top < 0.0)
