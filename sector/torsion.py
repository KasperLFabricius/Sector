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

* Closed stirrups   ``TRd,s   = (Asw/s) * 2*Ak * fywd * cot(theta)``      (6.27 + 6.8)
* Concrete struts   ``TRd,max = 2*nu*alpha_cw*fcd*Ak*tef*sin*cos``        (6.30)
* Cracking          ``TRd,c   = 2*Ak*tef*fctd``                           (tau = fctd)
* Longitudinal steel required ``sum Asl = TEd*uk*cot(theta)/(2*Ak*fyd)``  (6.28)

The closed-stirrup expression follows the torsional wall shear flow in 6.27 and
the transverse-reinforcement equilibrium in 6.8. Formula 6.28 separately defines
the longitudinal torsion reinforcement.

The strut factor ``nu`` is the code's torsion effectiveness factor (recommended
``nu = 0.6(1 - fck/250)``; the DK NA:2024 ``nu_t = 0.7*(0.7 - fck/200)``, 5.104 NA).
The combined shear + torsion concrete-crushing check ``TEd/TRd,max + VEd/VRd,max <= 1``
(6.29) is assembled by the caller from this module's ``TRd,max`` and the shear
``VRd,max``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

from . import geometry


@dataclass(frozen=True, slots=True)
class SubtubeTorqueShare:
    """One accepted stiffness-proportional sub-tube torque share."""

    index: int
    stiffness: float
    fraction: float
    torque: float


@dataclass(frozen=True, slots=True)
class StiffnessDistributionResult:
    """Compact final state of a sub-tube stiffness distribution."""

    applied_torque: float
    positive_stiffness_sum: float
    shares: tuple[SubtubeTorqueShare, ...]

    @property
    def torque_parts(self) -> tuple[float, ...]:
        """Accepted torque carried by each input sub-tube, in input order."""

        return tuple(share.torque for share in self.shares)


@dataclass(frozen=True, slots=True)
class TorsionStirrupResult:
    """Operands and result of the existing closed-stirrup resistance formula."""

    ak_m2: float
    fywd_mpa: float
    asw_over_s: float
    cot: float
    two_ak_m2: float
    trd_s: float


@dataclass(frozen=True, slots=True)
class TorsionStrutResult:
    """Operands and result of the existing torsion strut-resistance formula."""

    fck_mpa: float
    fcd_mpa: float
    nu: float
    alpha_cw: float
    ak_m2: float
    tef_mm: float
    cot: float
    tan: float
    sin_cos: float
    closed_detailing: bool
    trd_max: float


@dataclass(frozen=True, slots=True)
class TorsionCrackingResult:
    """Operands and result of the existing torsional-cracking formula."""

    fctd_mpa: float
    ak_m2: float
    tef_mm: float
    trd_c: float


@dataclass(frozen=True, slots=True)
class TorsionLongitudinalResult:
    """Operands, direct interim terms and result of Formula (6.28)."""

    t_ed_knm: float
    uk_m: float
    ak_m2: float
    fyd_mpa: float
    cot: float
    numerator: float
    denominator: float
    asl_required_mm2: float


@dataclass(frozen=True, slots=True)
class TorsionResistanceSelection:
    """Final governing selection between the existing torsion resistances."""

    trd_s: float
    trd_max: float
    transverse_reinforcement: bool
    resistance: float
    governs: str


def _perimeter(ring: Sequence) -> float:
    """Closed-polygon perimeter (same length units as the vertices)."""
    n = len(ring)
    if n < 2:
        return 0.0
    return sum(math.dist(ring[i], ring[(i + 1) % n]) for i in range(n))


def minimum_caliper_width(ring: Sequence) -> float:
    """Return the rotation-invariant minimum projection width of a polygon.

    The minimum width of a convex polygon occurs normal to one of its edges.
    Sector's single-tube resistance is issued only for convex outlines; evaluating
    every edge normal therefore gives the physical least section dimension without
    tying it to the global x/y axes.  The same calculation remains conservative for
    the generated rectangular sub-tubes.
    """
    pts = [(float(point[0]), float(point[1])) for point in ring]
    if len(pts) < 3:
        return 0.0
    minimum = math.inf
    for index, point in enumerate(pts):
        next_point = pts[(index + 1) % len(pts)]
        dx = next_point[0] - point[0]
        dy = next_point[1] - point[1]
        length = math.hypot(dx, dy)
        if length <= 1.0e-12:
            continue
        nx, ny = -dy / length, dx / length
        projections = [x * nx + y * ny for x, y in pts]
        width = max(projections) - min(projections)
        if width > 1.0e-12:
            minimum = min(minimum, width)
    return 0.0 if not math.isfinite(minimum) else minimum


def _ensure_ccw(ring: Sequence):
    """Return the ring as a list oriented counter-clockwise (positive signed area)."""
    analysis_ring = geometry.ring_without_terminal_closure(ring)
    pts = [(float(p[0]), float(p[1])) for p in analysis_ring]
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
            # The two offset lines are parallel: the original edges are collinear (an
            # extra vertex on a straight edge). The offset of that shared vertex is the
            # vertex itself moved inward along the common edge normal.
            px, py = pts[j]
            _ox, _oy, ux, uy = lines[j]
            v = (px - uy * dist, py + ux * dist)     # inward (left) normal offset
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
    geometry.require_valid_section_topology(outer, holes or [])
    minimum_dimension_mm = minimum_caliper_width(outer) * 1000.0 if outer else 0.0
    if not outer or len(outer) < 3:
        return dict(A=0.0, u=0.0, tef=0.0, Ak=0.0, uk=0.0, tef_auto=0.0,
                    tef_capped=False, tef_user=False, hollow=bool(holes),
                    minimum_dimension_mm=minimum_dimension_mm,
                    valid=False, reason="no outline", tef_selection="none",
                    centreline_method="none")
    # The single-tube idealisation models a solid section or a single-cell hollow box;
    # a multi-cell section (two or more voids) needs sub-division into separate tubes
    # (6.3.2(1)), which is not implemented, so reject it rather than report an
    # unconservative single-tube TRd.
    if holes and len(holes) > 1:
        return dict(A=0.0, u=0.0, tef=0.0, Ak=0.0, uk=0.0, tef_auto=0.0,
                    tef_capped=False, tef_user=False, hollow=True,
                    minimum_dimension_mm=minimum_dimension_mm,
                    valid=False, reason="multi-cell (2+ voids)",
                    tef_selection="none", centreline_method="none")
    A = abs(geometry.signed_area(outer))            # outer area incl. hollow, m2
    u = _perimeter(outer)                            # outer perimeter, m
    if A <= 0.0 or u <= 0.0:
        return dict(A=A, u=u, tef=0.0, Ak=0.0, uk=0.0, tef_auto=0.0,
                    tef_capped=False, tef_user=False, hollow=bool(holes),
                    minimum_dimension_mm=minimum_dimension_mm,
                    valid=False, reason="degenerate outline",
                    tef_selection="none", centreline_method="none")
    tef_auto = A / u                                 # m
    hollow = bool(holes)
    tef = tef_auto
    tef_capped = False
    if hollow:
        # EC2 caps tef at the real wall thickness for a hollow section. Measure it
        # directly as the minimum gap between the outer outline and any void: the
        # closest approach of two convex polygons is a vertex of one to an edge of the
        # other, so check every void vertex against the outer edges and every outer
        # vertex against each void's edges (distance_to_boundary is point-to-edge).
        walls = []
        for h in holes:
            walls += [geometry.distance_to_boundary(p[0], p[1], [outer]) for p in h]
            walls += [geometry.distance_to_boundary(p[0], p[1], [h]) for p in outer]
        wall = min(walls) if walls else tef_auto
        if wall < tef:
            tef, tef_capped = wall, True
    tef_user = tef_override > 0.0
    if tef_user:
        tef = tef_override / 1000.0                  # mm -> m
    tef_selection = (
        "user override" if tef_user else "real-wall cap" if tef_capped else "A/u"
    )
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
        centreline_method = "inward offset"
    else:                                            # degenerate offset -> linear est.
        Ak = max(A - u * 0.5 * tef, 0.0)             # 0 when the wall eats the section
        uk = u * math.sqrt(Ak / A) if A > 0.0 else 0.0
        centreline_method = "linear estimate"
    return dict(A=A, u=u, tef=tef * 1000.0, Ak=Ak, uk=uk, tef_auto=tef_auto * 1000.0,
                tef_capped=tef_capped, tef_user=tef_user, hollow=hollow,
                minimum_dimension_mm=minimum_dimension_mm,
                valid=Ak > 0.0, reason=None if Ak > 0.0 else "wall exceeds section",
                tef_selection=tef_selection, centreline_method=centreline_method)


def rectangle_torsion_constant(b: float, h: float) -> float:
    """St. Venant torsion constant of a solid rectangle (length unit ^4).

    ``C = h*s^3 * (1/3 - 0.21*(s/h)*(1 - (s/h)^4/12))`` with ``s`` the short side and
    ``h`` the long side (the Roark / Timoshenko series approximation): ``C -> h*s^3/3``
    for a thin rectangle and ``0.141*a^4`` for a square. Used to split the applied torque
    over the sub-sections of a compound section in proportion to their uncracked
    torsional stiffness (EN 1992-1-1 6.3.1(4)); the shear modulus is common to every
    part and cancels in the share.
    """
    if b <= 0.0 or h <= 0.0:
        return 0.0
    s, lo = (b, h) if b <= h else (h, b)            # short side, long side
    r = s / lo
    return lo * s ** 3 * (1.0 / 3.0 - 0.21 * r * (1.0 - r ** 4 / 12.0))


def rectangle_ring(b: float, h: float):
    """A CCW rectangle outline (metres) centred at the origin.

    Position is irrelevant to the tube idealisation (``tef``, ``Ak``, ``uk`` depend only
    on the shape), so a sub-rectangle is fed to :func:`tube_properties` centred at the
    origin.
    """
    return [(-b / 2.0, -h / 2.0), (b / 2.0, -h / 2.0),
            (b / 2.0, h / 2.0), (-b / 2.0, h / 2.0)]


def stiffness_distribution_result(
    t_ed: float, constants
) -> StiffnessDistributionResult:
    """Return the accepted sub-tube shares and the retained distribution basis."""

    stiffnesses = tuple(float(c) for c in constants)
    total = sum(c for c in stiffnesses if c > 0.0)
    shares = tuple(
        SubtubeTorqueShare(
            index=i,
            stiffness=c,
            fraction=(c / total if c > 0.0 and total > 0.0 else 0.0),
            torque=(t_ed * c / total if c > 0.0 and total > 0.0 else 0.0),
        )
        for i, c in enumerate(stiffnesses)
    )
    return StiffnessDistributionResult(float(t_ed), total, shares)


def distribute_by_stiffness(t_ed: float, constants):
    """Split ``t_ed`` over sub-sections in proportion to torsional stiffness constants.

    ``TEd_i = t_ed * C_i / sum(C)`` (EN 1992-1-1 6.3.1(4)). A non-positive constant takes
    no share; if every constant is non-positive the whole torque is returned as zeros.
    """
    return list(stiffness_distribution_result(t_ed, constants).torque_parts)


def trd_s_result(
    ak_m2: float, fywd: float, asw_over_s: float, cot: float
) -> TorsionStirrupResult:
    """Return the retained operands and result of the existing stirrup formula."""

    two_ak = 2.0 * ak_m2
    value = asw_over_s * two_ak * fywd * cot
    return TorsionStirrupResult(ak_m2, fywd, asw_over_s, cot, two_ak, value)


def trd_s(ak_m2: float, fywd: float, asw_over_s: float, cot: float) -> float:
    """Torsion resistance governed by the closed stirrups (kN.m).

    ``TRd,s = (Asw/s) * 2*Ak * fywd * cot(theta)`` -- each wall carries the shear flow
    with transverse links, and the torque sums to ``2*Ak`` times the link tension.
    Units: ``(Asw/s)[mm2/mm] * Ak[m2] * fywd[MPa]`` already gives kN.m (the m2->mm2
    factor cancels N.mm->kN.m), so no scale factor is applied.
    """
    return trd_s_result(ak_m2, fywd, asw_over_s, cot).trd_s


def trd_max_result(
    fck: float,
    code,
    ak_m2: float,
    tef_mm: float,
    alpha_cw: float,
    cot: float,
    closed_detailing: bool = False,
    fcd_mpa: float | None = None,
) -> TorsionStrutResult:
    """Return retained operands and result of the existing strut formula."""

    fcd = (code.concrete_factor(fck) * fck / code.gamma_c
           if fcd_mpa is None else float(fcd_mpa))
    nu = code.torsion_nu(fck, closed_detailing=closed_detailing)
    tan = math.inf if cot == 0.0 else 1.0 / cot
    sin_cos = cot / (1.0 + cot * cot)
    value = (2.0 * nu * alpha_cw * fcd * ak_m2 * (tef_mm / 1000.0) * sin_cos
             * 1000.0)
    return TorsionStrutResult(
        fck, fcd, nu, alpha_cw, ak_m2, tef_mm, cot, tan, sin_cos,
        bool(closed_detailing), value,
    )


def trd_max(fck: float, code, ak_m2: float, tef_mm: float, alpha_cw: float,
            cot: float, closed_detailing: bool = False,
            fcd_mpa: float | None = None) -> float:
    """Torsion resistance limited by the concrete struts (kN.m), 6.30.

    ``TRd,max = 2*nu*alpha_cw*fcd*Ak*tef*sin(theta)*cos(theta)`` with
    ``sin*cos = cot/(1+cot^2)`` and ``nu`` the code torsion effectiveness factor.
    ``closed_detailing`` raises ``nu_t`` to ``nu_v`` under DK NA Figur 5.100 NA
    (closed stirrups round the periphery + distributed longitudinal steel).
    """
    return trd_max_result(
        fck, code, ak_m2, tef_mm, alpha_cw, cot,
        closed_detailing=closed_detailing, fcd_mpa=fcd_mpa,
    ).trd_max


def trd_c_result(fctd: float, ak_m2: float, tef_mm: float) -> TorsionCrackingResult:
    """Return retained operands and result of the existing cracking formula."""

    value = 2.0 * ak_m2 * (tef_mm / 1000.0) * fctd * 1000.0
    return TorsionCrackingResult(fctd, ak_m2, tef_mm, value)


def trd_c(fctd: float, ak_m2: float, tef_mm: float) -> float:
    """Torsional cracking moment (kN.m): ``TRd,c = 2*Ak*tef*fctd`` (tau_t = fctd)."""
    return trd_c_result(fctd, ak_m2, tef_mm).trd_c


def asl_required_result(
    t_ed: float, uk_m: float, ak_m2: float, fyd: float, cot: float
) -> TorsionLongitudinalResult:
    """Return retained operands and direct interim terms of Formula (6.28)."""

    numerator = t_ed * uk_m * cot
    denominator = 2.0 * ak_m2 * fyd
    value = (
        numerator / denominator * 1000.0
        if ak_m2 > 0.0 and fyd > 0.0
        else 0.0
    )
    return TorsionLongitudinalResult(
        t_ed, uk_m, ak_m2, fyd, cot, numerator, denominator, value
    )


def asl_required(t_ed: float, uk_m: float, ak_m2: float, fyd: float,
                 cot: float) -> float:
    """Longitudinal reinforcement required for torsion (mm2), 6.28.

    ``sum Asl = TEd * uk * cot(theta) / (2*Ak*fyd)``.
    """
    return asl_required_result(t_ed, uk_m, ak_m2, fyd, cot).asl_required_mm2


def select_torsion_resistance(
    trd_s_value: float, trd_max_value: float, *, asw_over_s: float
) -> TorsionResistanceSelection:
    """Retain the existing min/maximum branch and its governing identity."""

    with_stirrups = asw_over_s > 0.0
    if with_stirrups and trd_s_value <= trd_max_value:
        resistance = trd_s_value
        governs = "stirrups (TRd,s)"
    else:
        resistance = trd_max_value
        governs = "crushing (TRd,max)"
    return TorsionResistanceSelection(
        trd_s_value, trd_max_value, with_stirrups, resistance, governs
    )
