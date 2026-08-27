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
  checks are made (``N + M + T`` and ``N + V + T``) and the governing one taken.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction

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
class MinimumReinforcementScreenResult:
    """Applicability, operands and verdict for EN 1992-1-1 Formula (6.31)."""

    applicable: bool
    status: str
    scope_key: str
    value: float | None
    ok: bool | None
    t_ed: float
    trd_c: float | None
    v_ed: float | None
    vrd_c: float | None
    torsion_ratio: float | None
    shear_ratio: float | None
    governs: str | None
    solid: bool
    model_2023: bool
    dk_na: bool
    shear_method: str
    torsion_method: str
    n_ed: float
    mx_ed: float
    my_ed: float
    normal_or_moment_active: bool
    detailing_status: str
    detailing_scope_key: str


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
class DknaActionTerm:
    """One retained ``SEd/SRd`` term for DK NA 6.3.2(6).

    ``demand`` retains the entered sign while ``demand_abs`` is the magnitude used
    by the interaction.  An exactly zero action is inactive and therefore does not
    require a resistance.  An acting term without a finite positive action-alone
    resistance is retained as invalid instead of being turned into a finite ratio.
    """

    symbol: str
    demand: float | None
    demand_abs: float | None
    resistance: float | None
    ratio: float | None
    active: bool
    valid: bool
    reason: str | None


@dataclass(frozen=True, slots=True)
class DknaInteractionResult:
    """Retained action-alone terms, inclusion rule and governing branch."""

    n: DknaActionTerm
    m: DknaActionTerm
    v: DknaActionTerm
    t: DknaActionTerm

    r_n: float | None
    r_m: float | None
    r_v: float | None
    r_t: float | None
    m_plus_t: float | None
    v_plus_t: float | None
    all_sum: float | None
    n_m_plus_t: float | None
    n_v_plus_t: float | None
    m_v_independent: bool
    inclusion_rule: str
    governing_chord: str | None
    utilisation: float | None
    valid: bool
    reason: str | None
    conditional: bool
    limit_satisfied: bool | None
    status: str
    ok: bool | None


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


def minimum_reinforcement_screen_result(
    t_ed: float,
    trd_c: float | None,
    v_ed: float | None,
    vrd_c: float | None,
    *,
    solid_rectangle: bool,
    subdivided: bool,
    model_2023: bool,
    shear_available: bool,
    dk_na: bool = False,
    shear_method: str = "",
    torsion_method: str = "",
    n_ed: float = 0.0,
    mx_ed: float = 0.0,
    my_ed: float = 0.0,
) -> MinimumReinforcementScreenResult:
    """Return the bounded Formula (6.31) scope and numerical screen.

    Formula (6.31) is retained only for an approximately solid rectangular
    section using the first-generation ``V_Rd,c`` route. Other geometry and the
    2023 method keep their complete shear-and-torsion results without receiving
    this low-action condition result.
    """

    n_ed = float(n_ed)
    mx_ed = float(mx_ed)
    my_ed = float(my_ed)
    normal_or_moment_active = any(
        value != 0.0 for value in (n_ed, mx_ed, my_ed)
    )
    common = dict(
        value=None,
        ok=None,
        t_ed=float(t_ed),
        trd_c=None if trd_c is None else float(trd_c),
        v_ed=None if v_ed is None else float(v_ed),
        vrd_c=None if vrd_c is None else float(vrd_c),
        torsion_ratio=None,
        shear_ratio=None,
        governs=None,
        solid=bool(solid_rectangle),
        model_2023=bool(model_2023),
        dk_na=bool(dk_na),
        shear_method=str(shear_method or ""),
        torsion_method=str(torsion_method or ""),
        n_ed=n_ed,
        mx_ed=mx_ed,
        my_ed=my_ed,
        normal_or_moment_active=normal_or_moment_active,
        detailing_status="NOT RUN",
        detailing_scope_key="separate_detailing_not_run",
    )
    if model_2023:
        return MinimumReinforcementScreenResult(
            applicable=False,
            status="NOT APPLICABLE",
            scope_key="selected_2023_route",
            **common,
        )
    if subdivided:
        return MinimumReinforcementScreenResult(
            applicable=False,
            status="NOT APPLICABLE",
            scope_key="subdivided_section",
            **common,
        )
    if not solid_rectangle:
        return MinimumReinforcementScreenResult(
            applicable=False,
            status="NOT APPLICABLE",
            scope_key="section_geometry",
            **common,
        )
    if dk_na and normal_or_moment_active:
        return MinimumReinforcementScreenResult(
            applicable=False,
            status="NOT APPLICABLE",
            scope_key="dkna_combined_normal_or_moment",
            **common,
        )
    if not shear_available or v_ed is None or vrd_c is None:
        return MinimumReinforcementScreenResult(
            applicable=False,
            status="NOT ASSESSED",
            scope_key="shear_resistance_unavailable",
            **common,
        )
    if trd_c is None or trd_c <= 0.0 or vrd_c <= 0.0:
        return MinimumReinforcementScreenResult(
            applicable=False,
            status="NOT ASSESSED",
            scope_key="positive_resistance_unavailable",
            **common,
        )

    torsion_ratio = float(t_ed) / float(trd_c)
    shear_ratio = float(v_ed) / float(vrd_c)
    value = torsion_ratio + shear_ratio
    ok = bool(value <= 1.0 + 1.0e-9)
    return MinimumReinforcementScreenResult(
        applicable=True,
        status="PASS" if ok else "FAIL",
        scope_key="applicable_first_generation_rectangle",
        value=value,
        ok=ok,
        t_ed=float(t_ed),
        trd_c=float(trd_c),
        v_ed=float(v_ed),
        vrd_c=float(vrd_c),
        torsion_ratio=torsion_ratio,
        shear_ratio=shear_ratio,
        governs="torsion" if torsion_ratio >= shear_ratio else "shear",
        solid=True,
        model_2023=False,
        dk_na=bool(dk_na),
        shear_method=str(shear_method or ""),
        torsion_method=str(torsion_method or ""),
        n_ed=n_ed,
        mx_ed=mx_ed,
        my_ed=my_ed,
        normal_or_moment_active=normal_or_moment_active,
        detailing_status="NOT RUN",
        detailing_scope_key="separate_detailing_not_run",
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


def _dkna_number(value) -> float | None:
    """Return one finite non-Boolean real, or ``None`` when it is malformed."""

    if isinstance(value, (bool, np.bool_, str, bytes)):
        return None
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def dkna_action_term(
    symbol: str,
    demand,
    resistance,
) -> DknaActionTerm:
    """Build one fail-closed action-alone interaction term."""

    demand_value = _dkna_number(demand)
    if demand_value is None:
        return DknaActionTerm(
            symbol=symbol,
            demand=None,
            demand_abs=None,
            resistance=None,
            ratio=None,
            active=True,
            valid=False,
            reason=f"{symbol}Ed is not a finite action",
        )
    demand_abs = abs(demand_value)
    if demand_abs == 0.0:
        resistance_value = _dkna_number(resistance)
        return DknaActionTerm(
            symbol=symbol,
            demand=demand_value,
            demand_abs=0.0,
            resistance=(
                resistance_value
                if resistance_value is not None and resistance_value > 0.0
                else None
            ),
            ratio=0.0,
            active=False,
            valid=True,
            reason=None,
        )
    resistance_value = _dkna_number(resistance)
    if resistance_value is None or resistance_value <= 0.0:
        return DknaActionTerm(
            symbol=symbol,
            demand=demand_value,
            demand_abs=demand_abs,
            resistance=None,
            ratio=None,
            active=True,
            valid=False,
            reason=(
                f"Resistance to {symbol}Ed acting alone could not be determined"
            ),
        )
    ratio_value = demand_abs / resistance_value
    if not math.isfinite(ratio_value):
        return DknaActionTerm(
            symbol=symbol,
            demand=demand_value,
            demand_abs=demand_abs,
            resistance=resistance_value,
            ratio=None,
            active=True,
            valid=False,
            reason=(
                f"Resistance ratio for {symbol}Ed acting alone could not be determined"
            ),
        )
    return DknaActionTerm(
        symbol=symbol,
        demand=demand_value,
        demand_abs=demand_abs,
        resistance=resistance_value,
        ratio=ratio_value,
        active=True,
        valid=True,
        reason=None,
    )


def dkna_interaction_result(
    n_ed,
    n_rd,
    m_ed,
    m_rd,
    v_ed,
    v_rd,
    t_ed,
    t_rd,
    *,
    m_v_independent: bool,
) -> DknaInteractionResult:
    """Apply DK NA 6.3.2(6) to action-alone demands and resistances.

    ``N`` retains its tension-positive sign for evidence; every ratio uses the
    magnitude of the matching action and its resistance in that same direction.
    Selecting the optional M/V separation produces the two numerical checks
    ``N+M+T`` and ``N+V+T``.  This Boolean does not establish the required extra
    longitudinal-reinforcement capacity, distribution or anchorage.  A value within
    the numerical limit is therefore retained as conditional and cannot return an
    unconditional ``ok``.  A value above the limit is a definite failure even under
    that favourable assumption.
    """

    if type(m_v_independent) is not bool:
        raise TypeError("m_v_independent must be a Boolean")
    n = dkna_action_term("N", n_ed, n_rd)
    m = dkna_action_term("M", m_ed, m_rd)
    v = dkna_action_term("V", v_ed, v_rd)
    t = dkna_action_term("T", t_ed, t_rd)
    terms = (n, m, v, t)
    valid = all(term.valid for term in terms)
    r_n, r_m, r_v, r_t = (term.ratio for term in terms)
    if not valid:
        reason = next(term.reason for term in terms if not term.valid)
        return DknaInteractionResult(
            n=n,
            m=m,
            v=v,
            t=t,
            r_n=r_n,
            r_m=r_m,
            r_v=r_v,
            r_t=r_t,
            m_plus_t=None,
            v_plus_t=None,
            all_sum=None,
            n_m_plus_t=None,
            n_v_plus_t=None,
            m_v_independent=m_v_independent,
            inclusion_rule=(
                "N, M, V and T assessed from their action-alone resistances"
            ),
            governing_chord=None,
            utilisation=None,
            valid=False,
            reason=reason,
            conditional=m_v_independent,
            limit_satisfied=None,
            status="NOT ASSESSED",
            ok=None,
        )

    # The preceding validity check proves every retained ratio is a float.
    r_n_f, r_m_f, r_v_f, r_t_f = (
        float(r_n),
        float(r_m),
        float(r_v),
        float(r_t),
    )
    m_plus_t = r_m_f + r_t_f
    v_plus_t = r_v_f + r_t_f
    all_sum = r_n_f + r_m_f + r_v_f + r_t_f
    n_m_plus_t = r_n_f + m_plus_t
    n_v_plus_t = r_n_f + v_plus_t
    if m_v_independent:
        if n_m_plus_t >= n_v_plus_t:
            utilisation = n_m_plus_t
            governing = "N+M+T"
        else:
            utilisation = n_v_plus_t
            governing = "N+V+T"
        inclusion_rule = (
            "N and T included in both independent M and V assessments"
        )
    else:
        utilisation = all_sum
        governing = "N+M+V+T"
        inclusion_rule = "N, M, V and T summed"
    limit_satisfied = utilisation <= 1.0
    conditional = m_v_independent
    status = (
        "FAIL"
        if not limit_satisfied
        else "CONDITIONAL"
        if conditional
        else "PASS"
    )
    ok = False if not limit_satisfied else None if conditional else True
    return DknaInteractionResult(
        n=n,
        m=m,
        v=v,
        t=t,
        r_n=r_n_f,
        r_m=r_m_f,
        r_v=r_v_f,
        r_t=r_t_f,
        m_plus_t=m_plus_t,
        v_plus_t=v_plus_t,
        all_sum=all_sum,
        n_m_plus_t=n_m_plus_t,
        n_v_plus_t=n_v_plus_t,
        m_v_independent=m_v_independent,
        inclusion_rule=inclusion_rule,
        governing_chord=governing,
        utilisation=utilisation,
        valid=True,
        reason=None,
        conditional=conditional,
        limit_satisfied=limit_satisfied,
        status=status,
        ok=ok,
    )


def dkna_sum(
    r_m: float,
    r_v: float,
    r_t: float,
    *,
    r_n: float = 0.0,
    m_v_independent: bool,
) -> float:
    """Ratio-only convenience for DK NA 6.3.2(6).

    Production calculation uses :func:`dkna_interaction_result` so every operand
    and action-alone resistance is retained.  This helper remains useful for
    deterministic formula comparisons where the four validated ratios are already
    known.
    """

    if type(m_v_independent) is not bool:
        raise TypeError("m_v_independent must be a Boolean")
    ratios = tuple(_dkna_number(value) for value in (r_n, r_m, r_v, r_t))
    if any(value is None or value < 0.0 for value in ratios):
        raise ValueError("DK NA component ratios must be finite and non-negative")
    r_n_f, r_m_f, r_v_f, r_t_f = (float(value) for value in ratios)
    if m_v_independent:
        return r_n_f + max(r_m_f + r_t_f, r_v_f + r_t_f)
    return r_n_f + r_m_f + r_v_f + r_t_f


@dataclass(frozen=True, slots=True)
class RadialUtilResult:
    """Complete authoritative result of one applied-ray envelope selection."""

    demand: float
    resistance: float | None
    utilisation: float | None
    governing_index: int | None
    valid: bool
    reason: str | None
    origin_inside_or_on: bool | None


_RADIAL_POINT_OUTSIDE = -1
_RADIAL_POINT_BOUNDARY = 0
_RADIAL_POINT_INSIDE = 1


def _invalid_radial_result(
    demand: float,
    reason: str,
    *,
    origin_inside_or_on: bool | None,
) -> RadialUtilResult:
    """Return one explicit fail-closed radial assessment."""

    return RadialUtilResult(
        demand=demand,
        resistance=None,
        utilisation=None,
        governing_index=None,
        valid=False,
        reason=reason,
        origin_inside_or_on=origin_inside_or_on,
    )


def _radial_capacity_points(mx, my):
    """Return finite envelope arrays and their retained original indices."""

    try:
        px = np.asarray(mx, dtype=float)
        py = np.asarray(my, dtype=float)
    except (OverflowError, TypeError, ValueError):
        return None
    if px.ndim != 1 or py.ndim != 1 or len(px) != len(py) or len(px) == 0:
        return None
    if not np.all(np.isfinite(px)) or not np.all(np.isfinite(py)):
        return None
    original_indices = np.arange(len(px), dtype=int)
    # One exact terminal copy is a harmless serialization closure marker. The
    # physical swept-point indices remain unchanged when that final copy is removed.
    while len(px) >= 2 and px[0] == px[-1] and py[0] == py[-1]:
        px = px[:-1]
        py = py[:-1]
        original_indices = original_indices[:-1]
    if len(px) == 0:
        return None
    if len(px) >= 2:
        keep = np.ones(len(px), dtype=bool)
        keep[1:] = (px[1:] != px[:-1]) | (py[1:] != py[:-1])
        px = px[keep]
        py = py[keep]
        original_indices = original_indices[keep]
    return px, py, original_indices


def _fraction_coordinates(values: np.ndarray) -> tuple[Fraction, ...]:
    """Return exact rational values for the represented binary64 coordinates."""

    return tuple(Fraction.from_float(float(value)) for value in values)


def _fraction_orientation(
    ax: Fraction,
    ay: Fraction,
    bx: Fraction,
    by: Fraction,
    cx: Fraction,
    cy: Fraction,
) -> Fraction:
    """Return the exact orientation determinant for three represented points."""

    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def _fraction_point_on_segment(
    qx: Fraction,
    qy: Fraction,
    ax: Fraction,
    ay: Fraction,
    bx: Fraction,
    by: Fraction,
) -> bool:
    """Return whether one exact point lies on the closed represented segment."""

    return (
        min(ax, bx) <= qx <= max(ax, bx)
        and min(ay, by) <= qy <= max(ay, by)
        and _fraction_orientation(ax, ay, bx, by, qx, qy) == 0
    )


def _fraction_segments_intersect(
    ax: Fraction,
    ay: Fraction,
    bx: Fraction,
    by: Fraction,
    cx: Fraction,
    cy: Fraction,
    dx: Fraction,
    dy: Fraction,
) -> bool:
    """Return whether two closed represented segments intersect or touch."""

    if (
        max(ax, bx) < min(cx, dx)
        or max(cx, dx) < min(ax, bx)
        or max(ay, by) < min(cy, dy)
        or max(cy, dy) < min(ay, by)
    ):
        return False
    o1 = _fraction_orientation(ax, ay, bx, by, cx, cy)
    o2 = _fraction_orientation(ax, ay, bx, by, dx, dy)
    o3 = _fraction_orientation(cx, cy, dx, dy, ax, ay)
    o4 = _fraction_orientation(cx, cy, dx, dy, bx, by)
    if o1 == 0 and _fraction_point_on_segment(cx, cy, ax, ay, bx, by):
        return True
    if o2 == 0 and _fraction_point_on_segment(dx, dy, ax, ay, bx, by):
        return True
    if o3 == 0 and _fraction_point_on_segment(ax, ay, cx, cy, dx, dy):
        return True
    if o4 == 0 and _fraction_point_on_segment(bx, by, cx, cy, dx, dy):
        return True
    return o1 * o2 < 0 and o3 * o4 < 0


def _fraction_envelope_is_collinear(
    px: tuple[Fraction, ...],
    py: tuple[Fraction, ...],
) -> bool:
    """Return whether every retained point lies on one represented line."""

    if len(px) < 3:
        return True
    return all(
        _fraction_orientation(px[0], py[0], px[1], py[1], px[index], py[index])
        == 0
        for index in range(2, len(px))
    )


def _fraction_envelope_has_simple_topology(
    px: tuple[Fraction, ...],
    py: tuple[Fraction, ...],
) -> bool:
    """Validate a simple 2-D ring while retaining the collapsed-line contract."""

    count = len(px)
    if count < 3 or _fraction_envelope_is_collinear(px, py):
        return True
    twice_area = sum(
        px[index] * py[(index + 1) % count]
        - py[index] * px[(index + 1) % count]
        for index in range(count)
    )
    if twice_area == 0:
        return False
    for first in range(count):
        first_next = (first + 1) % count
        for second in range(first + 1, count):
            second_next = (second + 1) % count
            adjacent = first_next == second or second_next == first
            if adjacent:
                if first_next == second:
                    shared = first_next
                    first_other = first
                    second_other = second_next
                else:
                    shared = first
                    first_other = first_next
                    second_other = second
                if (
                    _fraction_orientation(
                        px[first_other],
                        py[first_other],
                        px[shared],
                        py[shared],
                        px[second_other],
                        py[second_other],
                    )
                    == 0
                ):
                    first_dx = px[first_other] - px[shared]
                    first_dy = py[first_other] - py[shared]
                    second_dx = px[second_other] - px[shared]
                    second_dy = py[second_other] - py[shared]
                    # Collinear sides may continue through their common vertex, but
                    # must not reverse and overlap an already traversed segment.
                    if first_dx * second_dx + first_dy * second_dy >= 0:
                        return False
                continue
            if _fraction_segments_intersect(
                px[first],
                py[first],
                px[first_next],
                py[first_next],
                px[second],
                py[second],
                px[second_next],
                py[second_next],
            ):
                return False
    return True


def _fraction_point_location(
    qx: Fraction,
    qy: Fraction,
    px: tuple[Fraction, ...],
    py: tuple[Fraction, ...],
) -> int:
    """Classify one exact represented point as outside, boundary, or inside."""

    count = len(px)
    for index in range(count):
        nxt = (index + 1) % count
        ax, ay = px[index], py[index]
        bx, by = px[nxt], py[nxt]
        if (
            min(ax, bx) <= qx <= max(ax, bx)
            and min(ay, by) <= qy <= max(ay, by)
            and (qx - ax) * (by - ay) == (qy - ay) * (bx - ax)
        ):
            return _RADIAL_POINT_BOUNDARY
    if count < 3:
        return _RADIAL_POINT_OUTSIDE
    inside = False
    previous = count - 1
    for index in range(count):
        xi, yi = px[index], py[index]
        xj, yj = px[previous], py[previous]
        if (yi > qy) != (yj > qy):
            crossing_x = (xj - xi) * (qy - yi) / (yj - yi) + xi
            if qx < crossing_x:
                inside = not inside
        previous = index
    return _RADIAL_POINT_INSIDE if inside else _RADIAL_POINT_OUTSIDE


def _fraction_interval_location(
    lower: Fraction,
    upper: Fraction,
    demand_x: Fraction,
    demand_y: Fraction,
    px: tuple[Fraction, ...],
    py: tuple[Fraction, ...],
) -> int | None:
    """Classify the exact open ray interval between two boundary events."""

    if lower >= upper:
        return None
    midpoint = (lower + upper) / 2
    return _fraction_point_location(
        demand_x * midpoint,
        demand_y * midpoint,
        px,
        py,
    )


def _fraction_crossings_share_vertex(
    prior_edges: list[int],
    edge: int,
    distance: Fraction,
    demand_x: Fraction,
    demand_y: Fraction,
    px: tuple[Fraction, ...],
    py: tuple[Fraction, ...],
) -> bool:
    """Return whether equal hits are the same adjacent polygon-vertex event."""

    count = len(px)
    demand_norm_sq = demand_x * demand_x + demand_y * demand_y
    for prior_edge in prior_edges:
        if (prior_edge + 1) % count == edge:
            vertex = edge
        elif (edge + 1) % count == prior_edge:
            vertex = prior_edge
        else:
            continue
        vx, vy = px[vertex], py[vertex]
        if demand_x * vy != demand_y * vx:
            continue
        vertex_parameter = (demand_x * vx + demand_y * vy) / demand_norm_sq
        if vertex_parameter == distance:
            return True
    return False


def _finite_fraction_float(value: Fraction) -> float:
    """Convert an exact rational to binary64, using infinity as invalid sentinel."""

    try:
        converted = float(value)
    except OverflowError:
        return math.inf
    return converted if math.isfinite(converted) else math.inf


def _finite_fraction_hypot(x_value: Fraction, y_value: Fraction) -> float:
    """Return a guarded binary64 norm without pre-rounding tiny components."""

    scale = max(abs(x_value), abs(y_value))
    if scale == 0:
        return 0.0
    numerator = scale.numerator
    denominator = scale.denominator
    exponent = numerator.bit_length() - denominator.bit_length()
    if exponent >= 0:
        if numerator < denominator << exponent:
            exponent -= 1
    elif numerator << -exponent < denominator:
        exponent -= 1
    if exponent >= 0:
        factor = Fraction(1, 1 << exponent)
    else:
        factor = Fraction(1 << -exponent, 1)
    scaled = math.hypot(float(x_value * factor), float(y_value * factor))
    try:
        converted = math.ldexp(scaled, exponent)
    except OverflowError:
        return math.inf
    return converted if math.isfinite(converted) else math.inf


def radial_util_result(mx, my, ax, ay) -> RadialUtilResult:
    """Select and rate an applied ``(Mx, My)`` against the plastic M-M envelope.

    The envelope is the closed polygon through the swept capacity points *in sweep
    order* -- the straight chords the M-M diagram actually draws. Utilisation is the
    applied radius over the distance from the origin to where the applied load ray
    crosses that polygon. Measuring against the drawn chords (not a radial
    interpolation of the vertex radii, which bulges outside the chords) keeps the
    check on the conservative side and consistent with the plotted envelope.

    The global moment origin must lie inside or on the accepted closed envelope
    before either the zero-demand special case or a forward ray crossing can own a
    utilisation. The result retains that classification and an explicit invalid
    reason; no finite substitute is fabricated when the prerequisite fails.
    """
    points = _radial_capacity_points(mx, my)
    try:
        ax_value, ay_value = float(ax), float(ay)
        a_rad = float(math.hypot(ax_value, ay_value))
    except (OverflowError, TypeError, ValueError):
        a_rad = math.nan
        ax_value = ay_value = math.nan
    if points is None:
        return _invalid_radial_result(
            a_rad,
            "M-M envelope coordinates are malformed or non-finite",
            origin_inside_or_on=None,
        )
    px, py, original_indices = points
    fraction_px = _fraction_coordinates(px)
    fraction_py = _fraction_coordinates(py)
    if not _fraction_envelope_has_simple_topology(fraction_px, fraction_py):
        return _invalid_radial_result(
            a_rad,
            "M-M envelope is self-intersecting, self-touching, or self-overlapping",
            origin_inside_or_on=None,
        )
    origin_location = _fraction_point_location(
        Fraction(0),
        Fraction(0),
        fraction_px,
        fraction_py,
    )
    if origin_location == _RADIAL_POINT_OUTSIDE:
        return _invalid_radial_result(
            a_rad,
            "Global moment origin lies outside the closed M-M envelope",
            origin_inside_or_on=False,
        )
    if not math.isfinite(a_rad):
        return _invalid_radial_result(
            a_rad,
            "Applied moment components are non-finite",
            origin_inside_or_on=True,
        )
    if a_rad == 0.0:
        return RadialUtilResult(
            demand=a_rad,
            resistance=None,
            utilisation=0.0,
            governing_index=None,
            valid=True,
            reason=None,
            origin_inside_or_on=True,
        )
    demand_x = Fraction.from_float(ax_value)
    demand_y = Fraction.from_float(ay_value)
    hits: list[tuple[Fraction, int]] = []
    count = len(fraction_px)
    for edge in range(count):
        nxt = (edge + 1) % count
        edge_x = fraction_px[nxt] - fraction_px[edge]
        edge_y = fraction_py[nxt] - fraction_py[edge]
        determinant = demand_x * edge_y - demand_y * edge_x
        if determinant == 0:
            continue
        distance = (
            edge_y * fraction_px[edge] - edge_x * fraction_py[edge]
        ) / determinant
        edge_parameter = (
            demand_y * fraction_px[edge] - demand_x * fraction_py[edge]
        ) / determinant
        if distance > 0 and 0 <= edge_parameter <= 1:
            hits.append((distance, edge))
    if not hits:
        # A legitimate axial-limit envelope may collapse to a line through the
        # origin. In that special case, use the farthest positive swept point in
        # the applied direction rather than inventing polygon area.
        if all(
            demand_x * y_value == demand_y * x_value
            for x_value, y_value in zip(fraction_px, fraction_py, strict=True)
        ):
            demand_norm_sq = demand_x * demand_x + demand_y * demand_y
            parameters = tuple(
                (demand_x * x_value + demand_y * y_value) / demand_norm_sq
                for x_value, y_value in zip(fraction_px, fraction_py, strict=True)
            )
            positive = tuple(
                index for index, parameter in enumerate(parameters) if parameter > 0
            )
            if positive:
                governing = max(positive, key=parameters.__getitem__)
                capacity_parameter = parameters[governing]
                capacity = _finite_fraction_hypot(
                    fraction_px[governing], fraction_py[governing]
                )
                utilisation = _finite_fraction_float(1 / capacity_parameter)
                if (
                    not math.isfinite(capacity)
                    or capacity <= 0.0
                    or not math.isfinite(utilisation)
                    or utilisation <= 0.0
                ):
                    return _invalid_radial_result(
                        a_rad,
                        "Collapsed M-M envelope resistance is not finite and positive",
                        origin_inside_or_on=True,
                    )
                return RadialUtilResult(
                    demand=a_rad,
                    resistance=capacity,
                    utilisation=utilisation,
                    governing_index=int(original_indices[governing]),
                    valid=True,
                    reason=None,
                    origin_inside_or_on=True,
                )
        return _invalid_radial_result(
            a_rad,
            "No admissible positive M-M envelope intersection in the applied direction",
            origin_inside_or_on=True,
        )
    hits.sort()
    crossing_groups: list[tuple[Fraction, list[int]]] = []
    for distance, edge_index in hits:
        if crossing_groups:
            previous_distance = crossing_groups[-1][0]
            if (
                distance == previous_distance
                and _fraction_crossings_share_vertex(
                    crossing_groups[-1][1],
                    edge_index,
                    distance,
                    demand_x,
                    demand_y,
                    fraction_px,
                    fraction_py,
                )
            ):
                crossing_groups[-1][1].append(edge_index)
                continue
        crossing_groups.append((distance, [edge_index]))

    first_location = _fraction_interval_location(
        Fraction(0),
        crossing_groups[0][0],
        demand_x,
        demand_y,
        fraction_px,
        fraction_py,
    )
    if first_location is None:
        return _invalid_radial_result(
            a_rad,
            "Initial M-M envelope crossing interval is not numerically resolvable",
            origin_inside_or_on=True,
        )
    if first_location == _RADIAL_POINT_OUTSIDE:
        return _invalid_radial_result(
            a_rad,
            "Applied ray initially leaves the admissible M-M envelope",
            origin_inside_or_on=True,
        )
    selected_crossing: tuple[Fraction, list[int]] | None = None
    for group_index, (distance, edge_indices) in enumerate(crossing_groups):
        if group_index + 1 < len(crossing_groups):
            next_distance = crossing_groups[group_index + 1][0]
            after_location = _fraction_interval_location(
                distance,
                next_distance,
                demand_x,
                demand_y,
                fraction_px,
                fraction_py,
            )
            if after_location is None:
                return _invalid_radial_result(
                    a_rad,
                    "M-M envelope crossing interval is not numerically resolvable",
                    origin_inside_or_on=True,
                )
        else:
            # A finite polygon is outside beyond its last positive ray event.
            after_location = _RADIAL_POINT_OUTSIDE
        if after_location == _RADIAL_POINT_OUTSIDE:
            selected_crossing = (distance, edge_indices)
            break
    if selected_crossing is None:
        return _invalid_radial_result(
            a_rad,
            "No verified inside-to-outside M-M envelope crossing in the applied "
            "direction",
            origin_inside_or_on=True,
        )
    capacity_parameter, edge_indices = selected_crossing
    edge = edge_indices[0]
    # The governing swept state is the endpoint of that chord nearest the crossing --
    # the computed neutral-axis angle closest to the applied load's direction.
    n = len(fraction_px)
    cx = demand_x * capacity_parameter
    cy = demand_y * capacity_parameter
    nxt = (edge + 1) % n
    d0_sq = (fraction_px[edge] - cx) ** 2 + (fraction_py[edge] - cy) ** 2
    d1_sq = (fraction_px[nxt] - cx) ** 2 + (fraction_py[nxt] - cy) ** 2
    gov = edge if d0_sq <= d1_sq else nxt
    cap = _finite_fraction_hypot(cx, cy)
    utilisation = _finite_fraction_float(1 / capacity_parameter)
    if (
        not math.isfinite(cap)
        or cap <= 0.0
        or not math.isfinite(utilisation)
        or utilisation <= 0.0
    ):
        return _invalid_radial_result(
            a_rad,
            "M-M envelope intersection is not finite and positive",
            origin_inside_or_on=True,
        )
    return RadialUtilResult(
        demand=a_rad,
        resistance=cap,
        utilisation=utilisation,
        governing_index=int(original_indices[gov]),
        valid=True,
        reason=None,
        origin_inside_or_on=True,
    )


def radial_util(mx, my, ax, ay):
    """Compatibility tuple ``(utilisation, governing_index)`` for the selector."""

    result = radial_util_result(mx, my, ax, ay)
    if not result.valid or result.utilisation is None:
        return math.inf, None
    return result.utilisation, result.governing_index
