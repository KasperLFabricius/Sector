"""Plastic (ultimate) capacity of a reinforced-concrete cross-section.

For a given axial force and a neutral-axis orientation, this finds the ultimate
bending capacity: the extreme concrete fibre is taken at the ultimate compressive
strain, the neutral-axis depth is solved so the axial force balances, and the
resulting moments are the section's capacity. Sweeping the neutral-axis angle
traces the biaxial interaction envelope.

Conventions
-----------
* Strain is **compression positive** here (matching the way ultimate strains are
  reported), so the concrete compression zone is where strain > 0. The material
  laws use tension-positive strain, so signs are converted at the boundary.
* The neutral-axis angle ``V`` is measured from the Y axis (degrees); the strain
  gradient (direction of increasing compression) is ``(cos V, sin V)`` and the
  compressed side is the one with the larger projection. ``V = 90`` gives a
  horizontal neutral axis (bending about X); ``V = 0`` a vertical one.
* Axial force ``P`` is positive in compression (kN); moments ``Mx`` / ``My`` are
  about the origin (kNm). Coordinates are in metres and bar areas in m^2, so a
  stress in MPa times an area in m^2 is a force in MN -- converted to kN below.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .geometry import area_moments, clip_halfplane
from .materials import EPS_C_PEAK, EPS_CU, Concrete, MildSteel
from .section import Section

_MN_TO_KN = 1000.0


@dataclass
class PlasticPoint:
    """Ultimate capacity at one neutral-axis angle."""

    V: float                  # neutral-axis angle from the Y axis, degrees
    Mx: float                 # capacity moment about X, kNm
    My: float                 # capacity moment about Y, kNm
    U: float                  # angle of the resultant load from the X axis, deg
    R: float                  # distance origin -> resultant load, m
    na_x_intercept: float     # neutral axis intercept with X axis, m
    na_y_intercept: float     # neutral axis intercept with Y axis, m
    eps_concrete: float       # extreme concrete strain, % (compression +)
    eps_steel: float          # extreme (most tensile) steel strain, %
    curvature: float          # 1/m
    compression_force: float  # total compression resultant, kN
    lever_arm: float          # internal lever arm L, m
    dx: float                 # X component of the lever arm, m
    dy: float                 # Y component of the lever arm, m
    converged: bool


def _accumulate(section, concrete, steel, dx, dy, s_max, c, n_bands):
    """Force resultants for a trial compression depth ``c`` (s-units).

    Returns compression and tension force totals and their first moments, in kN
    and kNm, plus the most tensile steel strain (compression-positive %). The
    neutral axis is at ``s = s_max - c``; the extreme fibre strain is EPS_CU.
    """
    s_na = s_max - c
    kappa = EPS_CU / c

    comp_F = comp_Fx = comp_Fy = 0.0
    ten_F = ten_Fx = ten_Fy = 0.0

    # -- concrete (always compression over the zone s > s_na) --
    rings = section.integration_rings()
    fcd = concrete.fcd
    s_peak = s_na + EPS_C_PEAK / kappa  # strain reaches the 0.2% plateau here

    # Plateau band [s_peak, s_max]: constant design strength.
    if s_peak < s_max:
        for ring in rings:
            clipped = clip_halfplane(ring, dx, dy, -s_peak)  # d.r >= s_peak
            m = area_moments(clipped)
            comp_F += fcd * m.area * _MN_TO_KN
            comp_Fx += fcd * m.sx * _MN_TO_KN
            comp_Fy += fcd * m.sy * _MN_TO_KN

    # Ascending band [s_na, min(s_peak, s_max)]: midpoint integration.
    s_top = min(s_peak, s_max)
    if s_top > s_na and n_bands > 0:
        h = (s_top - s_na) / n_bands
        for i in range(n_bands):
            sa = s_na + i * h
            sb = sa + h
            eps_m = kappa * (0.5 * (sa + sb) - s_na)
            sig = -concrete.stress(-eps_m, design=True)  # compression +, MPa
            if sig == 0.0:
                continue
            for ring in rings:
                band = clip_halfplane(clip_halfplane(ring, dx, dy, -sa),
                                      -dx, -dy, sb)
                m = area_moments(band)
                comp_F += sig * m.area * _MN_TO_KN
                comp_Fx += sig * m.sx * _MN_TO_KN
                comp_Fy += sig * m.sy * _MN_TO_KN

    # -- reinforcement (point areas, both signs) --
    bx, by, ba = section.bar_arrays()
    min_eps = 0.0
    for x, y, a in zip(bx, by, ba):
        eps_c = kappa * (x * dx + y * dy - s_na)  # compression positive
        min_eps = min(min_eps, eps_c)
        sig = -steel.stress(-eps_c, design=True) * _MN_TO_KN  # comp +, per MPa*m2->kN
        f = sig * a
        if f >= 0.0:
            comp_F += f
            comp_Fx += f * x
            comp_Fy += f * y
        else:
            ten_F += f
            ten_Fx += f * x
            ten_Fy += f * y

    return comp_F, comp_Fx, comp_Fy, ten_F, ten_Fx, ten_Fy, min_eps


def plastic_capacity_at_angle(
    section: Section,
    concrete: Concrete,
    steel: MildSteel,
    P: float,
    V_deg: float,
    *,
    n_bands: int = 80,
    max_iter: int = 100,
) -> PlasticPoint:
    """Ultimate capacity for axial force ``P`` (kN) at neutral-axis angle ``V``.

    The extreme concrete fibre is pinned at the ultimate strain and the
    neutral-axis depth solved (by bisection) so the net axial force equals ``P``.
    """
    V = math.radians(V_deg)
    dx, dy = math.cos(V), math.sin(V)

    verts = section.concrete_vertices()
    s = verts[:, 0] * dx + verts[:, 1] * dy
    s_max = float(s.max())
    s_min = float(s.min())
    c_full = s_max - s_min

    def net_axial(c):
        acc = _accumulate(section, concrete, steel, dx, dy, s_max, c, n_bands)
        return acc[0] + acc[3]  # comp_F + ten_F (kN)

    # Lower-bound the compression depth so the most tensile bar does not exceed
    # its rupture strain: below this, very high curvature ruptures the tension
    # steel (a steel-governed failure) and the axial-force function is no longer
    # monotonic. Within [c_min, c_full] the net axial force increases with c.
    bx, by, _ = section.bar_arrays()
    if bx.size:
        s_bar_min = float((bx * dx + by * dy).min())
        c_min = EPS_CU * (s_max - s_bar_min) / (steel.eut + EPS_CU)
    else:
        c_min = 1.0e-6 * c_full
    lo = max(1.0e-6 * c_full, c_min * (1.0 + 1.0e-6))
    hi = c_full
    n_lo, n_hi = net_axial(lo), net_axial(hi)
    converged = n_lo <= P <= n_hi
    if P < n_lo:
        c = lo
    elif P > n_hi:
        c = hi
    else:
        for _ in range(max_iter):
            c = 0.5 * (lo + hi)
            if net_axial(c) < P:
                lo = c
            else:
                hi = c
            if hi - lo < 1.0e-12 * c_full:
                break
        c = 0.5 * (lo + hi)

    comp_F, comp_Fx, comp_Fy, ten_F, ten_Fx, ten_Fy, min_eps = _accumulate(
        section, concrete, steel, dx, dy, s_max, c, n_bands
    )

    Mx = comp_Fy + ten_Fy
    My = comp_Fx + ten_Fx
    kappa = EPS_CU / c
    s_na = s_max - c

    # Resultant load position.
    if abs(P) > 1.0e-9:
        R = math.hypot(Mx, My) / abs(P)
    else:
        R = 0.0
    U = math.degrees(math.atan2(Mx, My)) % 360.0

    # Neutral-axis intercepts (infinite when the axis is parallel to an axis).
    x_int = s_na / dx if abs(dx) > 1.0e-12 else math.inf
    y_int = s_na / dy if abs(dy) > 1.0e-12 else math.inf

    # Internal lever arm between the compression and tension resultants.
    if comp_F != 0.0 and ten_F != 0.0:
        cxc, cyc = comp_Fx / comp_F, comp_Fy / comp_F
        cxt, cyt = ten_Fx / ten_F, ten_Fy / ten_F
        lever_dx, lever_dy = cxc - cxt, cyc - cyt
        lever = math.hypot(lever_dx, lever_dy)
    else:
        lever_dx = lever_dy = lever = 0.0

    return PlasticPoint(
        V=V_deg,
        Mx=Mx,
        My=My,
        U=U,
        R=R,
        na_x_intercept=x_int,
        na_y_intercept=y_int,
        eps_concrete=EPS_CU * 100.0,
        eps_steel=min_eps * 100.0,
        curvature=kappa,
        compression_force=comp_F,
        lever_arm=lever,
        dx=lever_dx,
        dy=lever_dy,
        converged=converged,
    )


def solve_plastic(
    section: Section,
    concrete: Concrete,
    steel: MildSteel,
    P: float,
    v_min: float,
    v_max: float,
    v_inc: float,
    *,
    n_bands: int = 80,
) -> list[PlasticPoint]:
    """Sweep the neutral-axis angle from ``v_min`` to ``v_max`` (inclusive).

    Returns one :class:`PlasticPoint` per angle, the biaxial capacity envelope
    for the axial force ``P``.
    """
    points = []
    v = v_min
    # Step count from the increment, guarding against floating-point drift.
    n = int(round((v_max - v_min) / v_inc)) if v_inc else 0
    for i in range(n + 1):
        v = v_min + i * v_inc
        points.append(
            plastic_capacity_at_angle(section, concrete, steel, P, v, n_bands=n_bands)
        )
    return points
