"""Shear resistance of a section without shear reinforcement (VRd,c).

EN 1992-1-1:2005 section 6.2.2(1), with the DK NA:2024 v_min. The design shear
resistance of a member not requiring shear reinforcement is

    VRd,c = [C_Rd,c*k*(100*rho_l*fck)^(1/3) + k1*sigma_cp] * bw * d     (6.2.a)

with a lower bound

    VRd,c = (v_min + k1*sigma_cp) * bw * d                              (6.2.b)

where ``k = 1 + sqrt(200/d) <= 2`` (d in mm), ``rho_l = Asl/(bw*d) <= 0.02`` is the
tension-reinforcement ratio (bars assumed fully anchored past the section),
``sigma_cp = NEd/Ac < 0.2*fcd`` is the axial stress (compression positive), and the
edition supplies ``C_Rd,c = 0.18/gamma_c``, ``k1 = 0.15`` and ``v_min`` (see
:class:`sector.codes.DesignCode`). The section forces, the effective depth ``d``, the
lever arm ``z`` and the tension reinforcement ``Asl`` are quantities Sector derives
from the geometry; ``bw`` (the smallest web width in the tension zone) is an input
that defaults to the derived minimum solid width.

Signs: the code takes NEd compression-positive; Sector's axial force N is
tension-positive, so the caller passes ``-N`` here.
"""

from __future__ import annotations

import math
from typing import Optional, Sequence


def _coord(point, axis: str) -> float:
    """The along-shear-axis coordinate of a point: y for vertical shear (axis 'x',
    bending about x), x for horizontal shear (axis 'y')."""
    return point[1] if axis == "x" else point[0]


def tension_reinforcement(bars: Sequence, axis: str, tension_low: bool,
                          centroid_coord: float):
    """Total area and centroid of the tension-side longitudinal bars.

    ``bars`` are ``(x, y, area_mm2)`` in metres; ``axis`` is the bending axis ('x' =
    vertical shear); ``tension_low`` True when the tension face is the low-coordinate
    side (bottom / left). The tension bars are those on the tension side of the
    section centroid. Returns ``(Asl_mm2, centroid_along_axis_m)`` or ``(0.0, None)``.
    """
    tens = []
    for b in bars:
        c = _coord(b, axis)
        if (c < centroid_coord) if tension_low else (c > centroid_coord):
            tens.append(b)
    area = sum(float(b[2]) for b in tens)
    if area <= 0.0:
        return 0.0, None
    cg = sum(float(b[2]) * _coord(b, axis) for b in tens) / area
    return area, cg


def effective_depth(outer: Sequence, axis: str, tension_low: bool,
                    tension_cg_coord: Optional[float]) -> float:
    """Effective depth ``d`` (mm): the distance from the extreme compression fibre
    (opposite the tension face) to the tension-reinforcement centroid, along the
    shear axis. Returns 0 when there is no tension reinforcement."""
    if tension_cg_coord is None or not len(outer):
        return 0.0
    coords = [_coord(p, axis) for p in outer]
    comp_fibre = max(coords) if tension_low else min(coords)   # opposite the tension face
    return abs(comp_fibre - tension_cg_coord) * 1000.0         # m -> mm


def _line_solid_span(ring: Sequence, level: float, axis: str) -> float:
    """Total length of the ring's interior cut by the line at ``level`` (m).

    For vertical shear (``axis == 'x'``) the cutting line is ``y = level`` and the
    span is measured in x; the crossings of the closed polygon with the line, sorted
    and paired, give the inside intervals.
    """
    xs = []
    n = len(ring)
    for i in range(n):
        p, q = ring[i], ring[(i + 1) % n]
        cp, cq = _coord(p, axis), _coord(q, axis)   # coordinate compared to level
        wp = p[0] if axis == "x" else p[1]           # the width-direction coordinate
        wq = q[0] if axis == "x" else q[1]
        if (cp <= level < cq) or (cq <= level < cp):
            t = (level - cp) / (cq - cp)
            xs.append(wp + t * (wq - wp))
    xs.sort()
    return sum(xs[i + 1] - xs[i] for i in range(0, len(xs) - 1, 2))


def min_web_width(outer: Sequence, holes: Optional[Sequence], axis: str) -> float:
    """Smallest solid width perpendicular to the shear (mm).

    The solid width (outline minus voids) at a scanline is piecewise-linear in the
    scan level, with breakpoints exactly at the vertices of the outline and the voids
    (between two consecutive vertex levels every crossing moves linearly, so the total
    interior width does too). Its minimum over the sampled band is therefore attained
    at one of those breakpoints, so the width is evaluated at every outline / void
    vertex level -- not on a fixed grid, which could step over a thin void or notch and
    overestimate the web width. The band is the middle 80% of the depth, excluding the
    extreme fibres where a curved outline tapers to zero. Correct for the web of
    rectangular / T / box sections; a circular (or otherwise curved) section should
    have ``bw`` entered by hand, and the caller echoes the derived value for review.
    """
    if not len(outer):
        return 0.0
    coords = [_coord(p, axis) for p in outer]
    lo, hi = min(coords), max(coords)
    if hi - lo <= 0.0:
        return 0.0
    margin = 0.10 * (hi - lo)
    band_lo, band_hi = lo + margin, hi - margin
    # Breakpoints: the band edges plus every outline / void vertex level inside it.
    levels = {band_lo, band_hi}
    for ring in [outer, *(holes or [])]:
        for p in ring:
            c = _coord(p, axis)
            if band_lo < c < band_hi:
                levels.add(c)
    # Evaluate just either side of each breakpoint (not exactly on it, where the
    # scanline through a vertex or along a horizontal edge is degenerate); the width
    # is continuous, so this recovers the breakpoint value and hence the true minimum.
    eps = 1e-9 * (hi - lo)
    best = math.inf
    for level in levels:
        for lv in (level - eps, level + eps):
            if not (band_lo - eps <= lv <= band_hi + eps):
                continue
            w = _line_solid_span(outer, lv, axis)
            for hole in holes or []:
                w -= _line_solid_span(hole, lv, axis)
            best = min(best, max(w, 0.0))
    return best * 1000.0 if math.isfinite(best) else 0.0


def vrd_c(fck: float, code, bw_mm: float, d_mm: float, asl_mm2: float,
          n_ed_comp_kn: float, ac_m2: float) -> dict:
    """Shear resistance without shear reinforcement, VRd,c (kN), sec. 6.2.2(1).

    ``n_ed_comp_kn`` is the axial force compression-positive (pass ``-N`` for
    Sector's tension-positive N); ``ac_m2`` the gross concrete area. Returns the
    resistance and the intermediate quantities for reporting.
    """
    if d_mm <= 0.0 or bw_mm <= 0.0:
        return dict(vrd_c=0.0, k=0.0, rho_l=0.0, sigma_cp=0.0, fcd=0.0,
                    v_basic=0.0, v_floor=0.0, crd_c=0.0, vmin=0.0,
                    k1=code.shear_k1, valid=False)
    k = min(1.0 + math.sqrt(200.0 / d_mm), 2.0)
    rho_l = min(asl_mm2 / (bw_mm * d_mm), 0.02)
    fcd = code.concrete_factor(fck) * fck / code.gamma_c                  # MPa
    sigma_cp = min(n_ed_comp_kn / ac_m2 / 1000.0 if ac_m2 > 0 else 0.0,   # kN/m2 -> MPa
                   0.2 * fcd)
    crd_c = code.shear_crd_c_over_gamma()
    vmin = code.shear_vmin(k, fck)
    basic = crd_c * k * (100.0 * rho_l * fck) ** (1.0 / 3.0) + code.shear_k1 * sigma_cp
    floor = vmin + code.shear_k1 * sigma_cp
    stress = max(basic, floor, 0.0)                                       # MPa
    return dict(vrd_c=stress * bw_mm * d_mm / 1000.0,                     # kN
                k=k, rho_l=rho_l, sigma_cp=sigma_cp, fcd=fcd,
                v_basic=basic, v_floor=floor, crd_c=crd_c, vmin=vmin,
                k1=code.shear_k1, valid=True)


def optimum_cot_theta(a: float, b: float, cot_min: float, cot_max: float) -> float:
    """Strut ``cot(theta)`` that maximises ``VRd = min(VRd,s, VRd,max)`` in the band.

    ``VRd,s = a*z*cot`` rises with ``cot(theta)``; ``VRd,max = b*z/(cot + 1/cot)``
    peaks at ``cot = 1`` (its denominator is minimal there) and falls away on *both*
    sides. So the unconstrained maximiser of ``VRd = min(...)`` is the crossover
    ``cot* = sqrt(b/a - 1)`` (where the two branches meet) when that is ``>= 1``, and
    ``cot = 1`` otherwise -- never below 1, since below it *both* branches fall.
    (``a = (Asw/s)*fywd``, ``b = alpha_cw*bw*nu1*fcd``; the lever arm ``z`` cancels.)
    The result is clamped to the user band ``[cot_min, cot_max]``, which may be
    widened past the code's ``1..2.5`` (the UI warns rather than blocks).
    """
    if a <= 0.0:
        return cot_max
    cot_star = math.sqrt(max(b / a - 1.0, 0.0))
    cot_opt = max(cot_star, 1.0)                 # the optimum is never below cot = 1
    return min(max(cot_opt, cot_min), cot_max)


def vrd_links(fck: float, code, bw_mm: float, d_mm: float, asw_over_s: float,
              fywk: float, n_ed_comp_kn: float, ac_m2: float, cot_min: float,
              cot_max: float, z_mm: Optional[float] = None) -> dict:
    """Shear resistance of a member with vertical links, sec. 6.2.3 (variable strut).

    Returns ``VRd,s`` (6.8) and ``VRd,max`` (6.9) at the strut angle ``theta`` that
    maximises ``VRd = min(VRd,s, VRd,max)`` over ``cot(theta)`` in
    ``[cot_min, cot_max]``; the resistance is that minimum. ``asw_over_s`` is the link
    area per unit length (mm2/mm), ``fywk`` the link characteristic yield (MPa),
    ``n_ed_comp_kn`` the axial force compression-positive (pass ``-N``), and
    ``ac_m2`` the gross concrete area (for ``sigma_cp``). ``z`` defaults to ``0.9 d``.
    """
    z = z_mm if (z_mm and z_mm > 0.0) else 0.9 * d_mm
    if d_mm <= 0.0 or bw_mm <= 0.0 or asw_over_s <= 0.0 or z <= 0.0:
        return dict(vrd_s=0.0, vrd_max=0.0, vrd=0.0, cot=0.0, theta_deg=0.0, z=z,
                    fywd=0.0, nu1=0.0, alpha_cw=0.0, sigma_cp=0.0, fcd=0.0,
                    asw_over_s=asw_over_s, governs="none", valid=False)
    fcd = code.concrete_factor(fck) * fck / code.gamma_c                  # MPa
    fywd = fywk / code.gamma_s                                            # MPa
    nu1 = code.shear_nu1(fck)
    # sigma_cp for alpha_cw is the mean axial stress (compression positive), NOT capped
    # at 0.2 fcd (6.11N spans the full 0..fcd range).
    sigma_cp = n_ed_comp_kn / ac_m2 / 1000.0 if ac_m2 > 0.0 else 0.0      # MPa
    alpha_cw = code.shear_alpha_cw(sigma_cp, fcd)
    a = asw_over_s * fywd                                                 # N/mm
    b = alpha_cw * bw_mm * nu1 * fcd                                      # N/mm
    cot = optimum_cot_theta(a, b, cot_min, cot_max)
    vrd_s = asw_over_s * z * fywd * cot / 1000.0                          # kN
    vrd_max = alpha_cw * bw_mm * z * nu1 * fcd / (cot + 1.0 / cot) / 1000.0  # kN
    vrd = min(vrd_s, vrd_max)
    governs = "stirrups (VRd,s)" if vrd_s <= vrd_max else "crushing (VRd,max)"
    theta_deg = math.degrees(math.atan(1.0 / cot))
    return dict(vrd_s=vrd_s, vrd_max=vrd_max, vrd=vrd, cot=cot, theta_deg=theta_deg,
                z=z, fywd=fywd, nu1=nu1, alpha_cw=alpha_cw, sigma_cp=sigma_cp,
                fcd=fcd, asw_over_s=asw_over_s, governs=governs, valid=True)
