"""Combined bending + shear + torsion (M-V-T) interaction checks.

Sector computes each action's resistance separately (the plastic M-M envelope, the
shear ``VRd``, the torsion ``TRd``); the combined check ties them together under one
consistent code edition.

Two interaction rules are provided:

* Concrete-strut crushing (EN 1992-1-1 6.3.2(4), Expression 6.29):
  ``TEd/TRd,max + VEd/VRd,max <= 1`` -- shear and torsion crush the same web struts,
  evaluated at a common strut angle.
* The DK NA:2024 general combined rule (6.3.2(6)): ``sum(SEd/SRd) <= 1`` over the
  acting sectional forces, each ``SRd`` the resistance to that force acting alone.
  When the longitudinal reinforcement provided for shear (beyond what bending needs)
  is present, ``M`` and ``V`` are not summed simultaneously; instead two independent
  checks are made (``M`` with ``T``, and ``V`` with ``T``) and the governing one
  taken. The axial force ``N`` is folded into the bending utilisation ``r_m`` (the
  plastic M-M envelope is traced at the applied ``N``), so it is not summed again.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class CrushingInteractionResult:
    """Retained component ratios and result of Expression (6.29)."""

    t_ed: float
    trd_max: float
    torsion_ratio: float
    v_ed: float
    vrd_max: float
    shear_ratio: float
    utilisation: float
    ok: bool


@dataclass(frozen=True, slots=True)
class GoverningStrutResult:
    """Compact accepted state of the existing common-angle minimax scan.

    No angle array or per-step history is retained.  ``selected_index`` identifies
    the accepted point in the declared uniform band; component indices identify the
    checks governing at that point.
    """

    cot: float
    theta_deg: float
    utilisation: float
    cot_min: float
    cot_max: float
    samples: int
    step: float
    selected_index: int
    objective_count: int
    governing_component_indices: tuple[int, ...]
    runner_up_utilisation: float | None


@dataclass(frozen=True, slots=True)
class DknaInteractionResult:
    """Retained DK NA component ratios, inclusion rule and governing chord."""

    r_m: float
    r_v: float
    r_t: float
    m_plus_t: float
    v_plus_t: float
    all_sum: float
    m_v_independent: bool
    inclusion_rule: str
    governing_chord: str
    utilisation: float
    ok: bool


def ratio(demand: float, resistance: float) -> float:
    """Utilisation ``demand / resistance``; ``inf`` when a demand has no resistance."""
    if resistance > 0.0:
        return demand / resistance
    return math.inf if demand > 0.0 else 0.0


def crushing_interaction_result(
    t_ed: float, trd_max: float, v_ed: float, vrd_max: float
) -> CrushingInteractionResult:
    """Return the two retained component ratios and final interaction result."""

    torsion_ratio = ratio(t_ed, trd_max)
    shear_ratio = ratio(v_ed, vrd_max)
    utilisation = torsion_ratio + shear_ratio
    return CrushingInteractionResult(
        t_ed=t_ed,
        trd_max=trd_max,
        torsion_ratio=torsion_ratio,
        v_ed=v_ed,
        vrd_max=vrd_max,
        shear_ratio=shear_ratio,
        utilisation=utilisation,
        ok=utilisation <= 1.0 + 1e-9,
    )


def crushing_interaction(t_ed: float, trd_max: float, v_ed: float,
                         vrd_max: float) -> float:
    """EN 1992-1-1 (6.29): ``TEd/TRd,max + VEd/VRd,max``."""
    return crushing_interaction_result(t_ed, trd_max, v_ed, vrd_max).utilisation


def governing_strut_result(
    utils, cot_min: float, cot_max: float, n: int = 1501
) -> GoverningStrutResult:
    """Return the accepted common angle without retaining the raw angle scan."""

    lo, hi = min(cot_min, cot_max), max(cot_min, cot_max)
    samples = max(int(n), 2)
    step = (hi - lo) / (samples - 1)
    if not utils:
        return GoverningStrutResult(
            cot=lo,
            theta_deg=math.degrees(math.atan2(1.0, lo)),
            utilisation=0.0,
            cot_min=lo,
            cot_max=hi,
            samples=samples,
            step=step,
            selected_index=0,
            objective_count=0,
            governing_component_indices=(),
            runner_up_utilisation=None,
        )
    best = None
    for i in range(samples):
        cot = lo + step * i
        vals = tuple(u(cot) for u in utils)
        worst = max(vals)
        key = (worst, sum(vals), cot)
        if best is None or key < best[0]:
            best = (key, i, cot, worst, vals)
    _key, selected_index, cot, worst, vals = best
    governing = tuple(i for i, value in enumerate(vals) if value == worst)
    below_worst = sorted((value for value in vals if value < worst), reverse=True)
    runner_up = below_worst[0] if below_worst else None
    return GoverningStrutResult(
        cot=cot,
        theta_deg=math.degrees(math.atan2(1.0, cot)),
        utilisation=worst,
        cot_min=lo,
        cot_max=hi,
        samples=samples,
        step=step,
        selected_index=selected_index,
        objective_count=len(utils),
        governing_component_indices=governing,
        runner_up_utilisation=runner_up,
    )


def governing_strut_cot(utils, cot_min: float, cot_max: float, n: int = 1501):
    """The strut ``cot(theta)`` minimising the GOVERNING utilisation in the band.

    EN 1992-1-1 6.3.2(2) uses one strut angle for the member (the same web struts
    carry shear and torsion), and the designer may choose it freely inside the code
    band. The best single angle is the one that minimises the worst of every check
    that depends on it: ``utils`` is a list of callables ``cot -> utilisation`` (the
    stirrup checks fall with ``cot``, the crushing and longitudinal-chord demands
    rise), and the returned angle is the argmin of ``max(utils)`` over a uniform scan
    of the band (the objective is piecewise monotone, so a fine scan is exact to its
    resolution). Ties break toward the smallest SUM of utilisations, then the lower
    ``cot`` (less longitudinal steel demand). Returns ``(cot, governing_util)``;
    with no callables the band's low edge is returned with utilisation 0.
    """
    result = governing_strut_result(utils, cot_min, cot_max, n)
    return result.cot, result.utilisation


def chord_applied_moment(m_signed: float, tension_low: bool) -> float:
    """Applied moment that ADDS tension to the shear tension chord (kNm).

    The shear shift, the torsion longitudinal force and the lever arm ``z`` are all
    defined on the shear tension face -- the ``tension_low`` face (the low-coordinate
    side when ``True``) -- so the bending moment paired with them is the one that
    tensions THAT chord, not the moment implied by its own sign on the other face.

    The plastic sign convention tensions the low face under a POSITIVE moment (``+Mx``
    tensions the bottom, ``+My`` the left), so the tensioning moment is ``+m_signed``
    for the low face and ``-m_signed`` for the high face. A moment of the opposite sense
    compresses the chord; that relief is not credited (it would understate the steel the
    chord still needs for shear + torsion), so the contribution floors at zero. The
    matching capacity ``MRd`` is the pure-axis bending capacity at the shear-face
    neutral-axis angle, supplied separately by the caller.
    """
    m_face = m_signed if tension_low else -m_signed
    return max(m_face, 0.0)


def longitudinal_check(
    m_ed: float,
    m_rd: float,
    ftd_v: float,
    ftd_t: float,
    z: float,
    *,
    cap_shear_force: bool = True,
) -> dict:
    """Longitudinal-steel utilisation on the tension chord under combined M + V + T.

    The tension chord about the shear axis carries the bending tension plus the shear
    shift ``delta_Ftd = 0.5*VEd*cot(theta)`` (6.18) and the torsion longitudinal force
    ``Ftd,T = TEd*uk*cot(theta)/(2*Ak)`` (6.28). Each extra force is turned into an
    equivalent moment on the lever arm ``z`` and added to the applied moment, then
    checked against the uniaxial bending capacity ``m_rd`` about that axis::

        MEd,total = MEd + min(delta_Ftd*z, MRd - MEd) + Ftd,T*z/2

    ``cap_shear_force`` applies the 2005 peak-moment cap from 6.2.3(7). It is false
    for the EN 1992-1-1:2023 additional chord force ``NVd`` from Formula (8.50);
    Sector does not claim the support/load-specific relief in Formula (8.53).
    The torsion force is distributed round the perimeter, so only half of it acts
    on this one chord (hence ``z/2``). All moments are in the same units (kNm);
    ``ftd_v``/``ftd_t`` are in kN and ``z`` in m.
    """
    mv_uncapped = ftd_v * z
    mt = ftd_t * z / 2.0
    shear_headroom = max(m_rd - m_ed, 0.0)
    if m_rd <= 0.0:
        # No bending capacity about this axis remains -- the coexisting off-axis
        # moment exhausts the M-M envelope on this face. The 6.2.3(7) cap would
        # zero the shear shift against zero headroom and hide a real demand, so
        # here the UNCAPPED shear-plus-torsion tension has nothing to carry it and
        # the chord fails outright (util = inf) whenever any demand acts.
        demand = m_ed + mv_uncapped + mt
        util = math.inf if demand > 0.0 else 0.0
        return dict(m_ed=m_ed, m_rd=m_rd, ftd_v=ftd_v, ftd_t=ftd_t, z=z,
                    mv=mv_uncapped, mt=mt, m_total=demand, util=util,
                    ok=util <= 1.0 + 1e-9, capped=False,
                    cap_shear_force=cap_shear_force,
                    mv_uncapped=mv_uncapped, shear_headroom=shear_headroom,
                    shear_term_selection="zero-capacity uncapped demand",
                    status="PASS" if util <= 1.0 + 1e-9 else "FAIL")
    mv = (
        min(mv_uncapped, shear_headroom)
        if cap_shear_force else mv_uncapped
    )
    m_total = m_ed + mv + mt
    util = ratio(m_total, m_rd)
    return dict(m_ed=m_ed, m_rd=m_rd, ftd_v=ftd_v, ftd_t=ftd_t, z=z,
                mv=mv, mt=mt, m_total=m_total, util=util,
                ok=util <= 1.0 + 1e-9,
                capped=cap_shear_force and mv_uncapped > mv + 1e-9,
                cap_shear_force=cap_shear_force,
                mv_uncapped=mv_uncapped, shear_headroom=shear_headroom,
                shear_term_selection=(
                    "capacity headroom cap"
                    if cap_shear_force and mv_uncapped > mv + 1e-9
                    else "uncapped"
                ),
                status="PASS" if util <= 1.0 + 1e-9 else "FAIL")


def dkna_interaction_result(
    r_m: float, r_v: float, r_t: float, *, m_v_independent: bool
) -> DknaInteractionResult:
    """Return the retained component sums and final DK NA inclusion branch."""

    m_plus_t = r_m + r_t
    v_plus_t = r_v + r_t
    all_sum = r_m + r_v + r_t
    if m_v_independent:
        if m_plus_t >= v_plus_t:
            utilisation = m_plus_t
            governing = "M+T"
        else:
            utilisation = v_plus_t
            governing = "V+T"
        inclusion_rule = "M and V assessed independently; torsion included in both"
    else:
        utilisation = all_sum
        governing = "M+V+T"
        inclusion_rule = "M, V and T summed"
    return DknaInteractionResult(
        r_m=r_m,
        r_v=r_v,
        r_t=r_t,
        m_plus_t=m_plus_t,
        v_plus_t=v_plus_t,
        all_sum=all_sum,
        m_v_independent=m_v_independent,
        inclusion_rule=inclusion_rule,
        governing_chord=governing,
        utilisation=utilisation,
        ok=utilisation <= 1.0 + 1e-9,
    )


def dkna_sum(r_m: float, r_v: float, r_t: float, *, m_v_independent: bool) -> float:
    """DK NA:2024 6.3.2(6) ``sum(SEd/SRd)``, the governing value.

    ``r_m`` / ``r_v`` / ``r_t`` are the bending / shear / torsion utilisations (each
    the demand over the resistance to that action alone; ``N`` is folded into
    ``r_m``). With ``m_v_independent`` the bending and shear terms are not added
    together -- the governing of ``(r_m + r_t)`` and ``(r_v + r_t)`` is returned --
    otherwise all three are summed.
    """
    return dkna_interaction_result(
        r_m, r_v, r_t, m_v_independent=m_v_independent
    ).utilisation


@dataclass(frozen=True, slots=True)
class RadialUtilResult:
    """Complete authoritative result of one applied-ray envelope selection."""

    demand: float
    resistance: float | None
    utilisation: float
    governing_index: int | None


def radial_util_result(mx, my, ax, ay) -> RadialUtilResult:
    """Select and rate an applied ``(Mx, My)`` against the plastic M-M envelope.

    The envelope is the closed polygon through the swept capacity points *in sweep
    order* -- the straight chords the M-M diagram actually draws. Utilisation is the
    applied radius over the distance from the origin to where the applied load ray
    crosses that polygon. Measuring against the drawn chords (not a radial
    interpolation of the vertex radii, which bulges outside the chords) keeps the
    check on the conservative side and consistent with the plotted envelope.

    The result owns radial demand, resistance, utilisation, and the governing swept
    member. ``governing_index`` is ``None`` when there is no applied direction or
    the ray misses the envelope.
    """
    a_rad = float(np.hypot(ax, ay))
    if a_rad < 1e-9:
        return RadialUtilResult(a_rad, None, 0.0, None)
    ux, uy = ax / a_rad, ay / a_rad                 # applied load ray direction
    px, py = np.asarray(mx, dtype=float), np.asarray(my, dtype=float)
    ex, ey = np.roll(px, -1) - px, np.roll(py, -1) - py   # edge vectors (polygon closed)
    # Intersect the ray t*u (t >= 0) with each edge P + s*e (s in [0, 1]):
    # solving t*u = P + s*e gives t and s from the ray x edge cross product D.
    D = ux * ey - uy * ex
    with np.errstate(divide="ignore", invalid="ignore"):
        t = (ey * px - ex * py) / D                 # ray distance to the edge line
        s = (uy * px - ux * py) / D                 # edge parameter
    hit = (np.abs(D) > 1e-12) & (s >= -1e-9) & (s <= 1.0 + 1e-9) & (t > 1e-9)
    if not hit.any():
        return RadialUtilResult(a_rad, None, math.inf, None)
    idx = np.nonzero(hit)[0]
    edge = int(idx[np.argmin(t[idx])])              # nearest forward boundary crossing
    cap = float(t[edge])
    # The governing swept state is the endpoint of that chord nearest the crossing --
    # the computed neutral-axis angle closest to the applied load's direction.
    n = len(px)
    cx, cy = ux * cap, uy * cap
    nxt = (edge + 1) % n
    d0 = math.hypot(float(px[edge]) - cx, float(py[edge]) - cy)
    d1 = math.hypot(float(px[nxt]) - cx, float(py[nxt]) - cy)
    gov = edge if d0 <= d1 else nxt
    return RadialUtilResult(a_rad, cap, a_rad / cap, gov)


def radial_util(mx, my, ax, ay):
    """Compatibility tuple ``(utilisation, governing_index)`` for the selector."""

    result = radial_util_result(mx, my, ax, ay)
    return result.utilisation, result.governing_index
