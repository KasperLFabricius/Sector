"""Torsional resistance from the thin-walled tube idealisation (EN 1992-1-1:2005
section 6.3).

A solid (or hollow) section is idealised as a thin-walled closed tube (6.3.2(1)):
the applied torsion ``TEd`` is carried by a constant shear flow ``TEd/(2*Ak)`` round
the walls, where ``Ak`` is the area enclosed by the wall centre-lines. The effective
wall thickness is ``tef = A/u`` (``A`` the total area within the outer perimeter,
including any hollow; ``u`` the outer perimeter), capped at the real wall thickness
for a hollow section. The centre-line is the outer outline offset inward by
``tef/2``, so ``Ak`` and its perimeter ``uk`` follow from that offset polygon.

Resistances (variable strut angle ``theta``, shared with the shear check):

* Closed stirrups   ``TRd,s   = (Asw/s) * 2*Ak * fywd * cot(theta)``      (from 6.28)
* Concrete struts   ``TRd,max = 2*nu*alpha_cw*fcd*Ak*tef*sin*cos``        (6.30)
* Cracking          ``TRd,c   = 2*Ak*tef*fctd``                           (tau = fctd)
* Longitudinal steel required ``sum Asl = TEd*uk*cot(theta)/(2*Ak*fyd)``  (6.28)

The strut factor ``nu`` is the code's torsion effectiveness factor (recommended
``nu = 0.6(1 - fck/250)``; the DK NA:2024 ``nu_t = 0.7*(0.7 - fck/200)``, 5.104 NA).
The combined shear + torsion concrete-crushing check ``TEd/TRd,max + VEd/VRd,max <= 1``
(6.29) is assembled by the caller from this module's ``TRd,max`` and the shear
``VRd,max``.
"""

from __future__ import annotations

import math
from typing import Optional, Sequence

from . import geometry


def _perimeter(ring: Sequence) -> float:
    """Closed-polygon perimeter (same length units as the vertices)."""
    n = len(ring)
    if n < 2:
        return 0.0
    return sum(math.dist(ring[i], ring[(i + 1) % n]) for i in range(n))


def _ensure_ccw(ring: Sequence):
    """Return the ring as a list oriented counter-clockwise (positive signed area)."""
    pts = [(float(p[0]), float(p[1])) for p in ring]
    if geometry.signed_area(pts) < 0.0:
        pts.reverse()
    return pts


def _line_intersect(a, b):
    """Intersection of two lines given as ``(px, py, ux, uy)`` (point + unit dir)."""
    px0, py0, ux0, uy0 = a
    px1, py1, ux1, uy1 = b
    den = ux0 * uy1 - uy0 * ux1
    if abs(den) < 1.0e-12:
        return None                       # parallel (collinear consecutive edges)
    t = ((px1 - px0) * uy1 - (py1 - py0) * ux1) / den
    return (px0 + t * ux0, py0 + t * uy0)


def offset_polygon_inward(ring: Sequence, dist: float):
    """The polygon offset inward (toward the interior) by ``dist`` (miter offset).

    Each edge is moved ``dist`` along its inward normal and consecutive offset edge
    lines are intersected for the new vertices. Returns the offset ring, or ``None``
    when it degenerates (a collinear pair, or the offset eats the section).
    """
    pts = _ensure_ccw(ring)
    n = len(pts)
    if n < 3 or dist <= 0.0:
        return list(pts) if dist == 0.0 else None
    lines = []
    for i in range(n):
        p, q = pts[i], pts[(i + 1) % n]
        dx, dy = q[0] - p[0], q[1] - p[1]
        length = math.hypot(dx, dy)
        if length < 1.0e-12:
            return None
        ux, uy = dx / length, dy / length
        nx, ny = -uy, ux                  # inward (left) normal for a CCW ring
        lines.append((p[0] + nx * dist, p[1] + ny * dist, ux, uy))
    out = []
    for j in range(n):
        v = _line_intersect(lines[(j - 1) % n], lines[j])
        if v is None:
            return None
        out.append(v)
    return out


def tube_properties(outer: Sequence, holes: Optional[Sequence],
                    tef_override: float = 0.0) -> dict:
    """Thin-walled tube idealisation of the section (metres in, mm out for lengths).

    Returns ``A`` (m2), ``u`` (m), ``tef`` (mm), ``Ak`` (m2), ``uk`` (m) plus the
    auto ``tef`` and whether it was capped/overridden. ``A`` is the area within the
    outer outline *including* any hollow (6.3.2(1)); for a hollow section ``tef`` is
    capped at the real wall thickness (estimated from the concrete area / centre-line
    perimeter). ``tef_override`` (mm, 0 = auto) forces the wall thickness.
    """
    if not outer or len(outer) < 3:
        return dict(A=0.0, u=0.0, tef=0.0, Ak=0.0, uk=0.0, tef_auto=0.0,
                    tef_capped=False, tef_user=False, valid=False)
    A = abs(geometry.signed_area(outer))            # outer area incl. hollow, m2
    u = _perimeter(outer)                            # outer perimeter, m
    if A <= 0.0 or u <= 0.0:
        return dict(A=A, u=u, tef=0.0, Ak=0.0, uk=0.0, tef_auto=0.0,
                    tef_capped=False, tef_user=False, valid=False)
    tef_auto = A / u                                 # m
    hollow = bool(holes)
    tef = tef_auto
    tef_capped = False
    if hollow:
        # Real wall thickness ~ concrete area / centre-line perimeter (exact for a
        # thin rectangular box); the code caps tef at the real thickness for a hollow
        # section. Use a first-pass centre-line perimeter at tef_auto.
        conc_area = A - sum(abs(geometry.signed_area(h)) for h in holes)
        ring0 = offset_polygon_inward(outer, 0.5 * tef_auto)
        uk0 = _perimeter(ring0) if ring0 else u
        wall = conc_area / uk0 if uk0 > 0.0 else tef_auto
        if wall < tef:
            tef, tef_capped = wall, True
    tef_user = tef_override > 0.0
    if tef_user:
        tef = tef_override / 1000.0                  # mm -> m
    # Centre-line polygon: the outer outline offset inward by tef/2. The input is made
    # CCW inside offset_polygon_inward, so a valid inward offset stays CCW with a
    # *positive* signed area strictly smaller than A and a shorter perimeter. When tef
    # exceeds the section inradius the miter offset flips outside / self-intersects and
    # its signed area goes non-positive or its perimeter grows -- reject it (do NOT take
    # abs(), which would accept the inverted polygon) and fall back to a linear estimate.
    ring = offset_polygon_inward(outer, 0.5 * tef)
    a_ring = geometry.signed_area(ring) if ring else 0.0
    if ring and 0.0 < a_ring < A and _perimeter(ring) < u:
        Ak, uk = a_ring, _perimeter(ring)
    else:                                            # degenerate offset -> linear est.
        Ak = max(A - u * 0.5 * tef, 0.0)             # 0 when the wall eats the section
        uk = u * math.sqrt(Ak / A) if A > 0.0 else 0.0
    return dict(A=A, u=u, tef=tef * 1000.0, Ak=Ak, uk=uk, tef_auto=tef_auto * 1000.0,
                tef_capped=tef_capped, tef_user=tef_user, hollow=hollow, valid=Ak > 0.0)


def trd_s(ak_m2: float, fywd: float, asw_over_s: float, cot: float) -> float:
    """Torsion resistance governed by the closed stirrups (kN.m).

    ``TRd,s = (Asw/s) * 2*Ak * fywd * cot(theta)`` -- each wall carries the shear flow
    with transverse links, and the torque sums to ``2*Ak`` times the link tension.
    Units: ``(Asw/s)[mm2/mm] * Ak[m2] * fywd[MPa]`` already gives kN.m (the m2->mm2
    factor cancels N.mm->kN.m), so no scale factor is applied.
    """
    return asw_over_s * 2.0 * ak_m2 * fywd * cot             # mm2/mm * m2 * MPa -> kN.m


def trd_max(fck: float, code, ak_m2: float, tef_mm: float, alpha_cw: float,
            cot: float) -> float:
    """Torsion resistance limited by the concrete struts (kN.m), 6.30.

    ``TRd,max = 2*nu*alpha_cw*fcd*Ak*tef*sin(theta)*cos(theta)`` with
    ``sin*cos = cot/(1+cot^2)`` and ``nu`` the code torsion effectiveness factor.
    """
    fcd = code.concrete_factor(fck) * fck / code.gamma_c
    nu = code.torsion_nu(fck)
    sin_cos = cot / (1.0 + cot * cot)
    return (2.0 * nu * alpha_cw * fcd * ak_m2 * (tef_mm / 1000.0) * sin_cos
            * 1000.0)                                          # MPa*m2*m -> MN -> kN.m


def trd_c(fctd: float, ak_m2: float, tef_mm: float) -> float:
    """Torsional cracking moment (kN.m): ``TRd,c = 2*Ak*tef*fctd`` (tau_t = fctd)."""
    return 2.0 * ak_m2 * (tef_mm / 1000.0) * fctd * 1000.0    # MPa*m2*m -> MN -> kN.m


def asl_required(t_ed: float, uk_m: float, ak_m2: float, fyd: float,
                 cot: float) -> float:
    """Longitudinal reinforcement required for torsion (mm2), 6.28.

    ``sum Asl = TEd * uk * cot(theta) / (2*Ak*fyd)``.
    """
    if ak_m2 <= 0.0 or fyd <= 0.0:
        return 0.0
    return t_ed * uk_m * cot / (2.0 * ak_m2 * fyd) * 1000.0   # kN.m*m/(m2*MPa) -> mm2
