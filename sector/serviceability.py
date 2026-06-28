"""Serviceability cracked-section analysis: cracking threshold, tension
stiffening and crack width.

The plain cracked elastic analysis in :mod:`sector.elastic` assumes the section
is *already* fully cracked -- concrete carries no tension anywhere, so it always
reports the fully cracked (Stage II) stresses. That is the right model once a
section has cracked, but it says nothing about *whether* it has cracked, and it
ignores the stiffening contribution of the intact concrete between cracks.

This module adds both, following EN 1992-1-1:

* **Cracking threshold.** The uncracked (Stage I) state is linear, so its peak
  concrete tensile stress scales with the applied load. The load factor that
  first reaches ``f_ctm`` is ``lambda_cr = f_ctm / sigma_ct,I``; ``lambda_cr >= 1``
  means the section has not cracked under the applied load and the Stage I
  stresses govern. This generalises ``M_cr / M`` to combined axial-plus-biaxial
  loading by scaling the whole action vector proportionally.

* **Tension stiffening.** Where cracked, deformation quantities are interpolated
  between the uncracked and fully cracked states with the distribution
  coefficient ``zeta = 1 - beta * lambda_cr^2`` (EC2 7.18; reduces to
  ``1 - beta (M_cr/M)^2`` in pure flexure), ``beta = 1.0`` for short-term and
  ``0.5`` for sustained/repeated loading. The mean strain plane is
  ``u_m = zeta * u_II + (1 - zeta) * u_I``. The *peak* steel stress at a crack is
  unchanged -- it is the Stage II value -- so tension stiffening softens the mean
  response (curvature, mean strain, crack width) but not the governing bar stress.

* **Crack width.** ``w_k = s_r,max * (eps_sm - eps_cm)`` with the mean strain from
  EC2 (7.9) and the maximum crack spacing from (7.11). This part is
  uniaxial-dominant: the effective tension area and crack spacing are defined for
  a single bending direction, so the depth axis is taken along the cracked-state
  strain gradient and the governing (most tensile) bar is used.

Units. The :mod:`sector.elastic` solver works with ``Ec = 1`` and returns
stresses in load-consistent units (kN/m^2 for kN/m/m sections); this module takes
``f_ctm`` and ``Es`` in MPa and works the EC2 formulas in MPa and mm, so
``w_k`` comes out in mm.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence, Union

import numpy as np

from .elastic import ElasticResult, solve_elastic, solve_elastic_uncracked
from .geometry import area_moments, clip_halfplane, distance_to_boundary
from .section import Section

# kN/m^2 per MPa: the solver returns stresses in kN/m^2 for sections built in
# kN/m/m units, so a stress in MPa is 1000x the numeric value.
_KPA_PER_MPA = 1000.0


@dataclass
class CrackWidthResult:
    """EC2 crack-width breakdown for the governing (largest-wk) tension bar."""

    wk: float            # crack width (mm)
    sr_max: float        # maximum crack spacing (mm)
    esm_ecm: float       # mean strain (eps_sm - eps_cm), dimensionless
    sigma_s: float       # Stage II steel stress at the governing bar (MPa)
    rho_p_eff: float     # effective reinforcement ratio As,eff / Ac,eff
    ac_eff: float        # effective tension area (m^2)
    hc_ef: float         # effective tension height (m)
    phi: float           # governing bar diameter (mm)
    cover: float         # clear cover to that bar's surface (mm)
    gov_bar: int         # index of the governing (largest-wk) bar


@dataclass
class CrackingResult:
    """Serviceability state of the section under one action combination.

    Holds the cracking decision, the tension-stiffening coefficient, the
    uncracked and fully cracked solves, the mean (tension-stiffened) strain
    plane, and -- where the section is cracked and the geometry is available --
    the crack width.
    """

    cracked: bool
    lambda_cr: float            # load factor to first cracking (inf if uncracked)
    sigma_ct: float             # Stage I peak concrete tension at the load (MPa)
    fctm: float                 # tensile strength used (MPa)
    zeta: float                 # tension-stiffening distribution coefficient
    uncracked: ElasticResult    # Stage I
    cracked_state: ElasticResult  # Stage II
    eps0_m: float               # mean strain plane (tension-stiffened)
    kx_m: float
    ky_m: float
    crack: Optional[CrackWidthResult] = None

    @property
    def mean_plane(self) -> tuple[float, float, float]:
        return (self.eps0_m, self.kx_m, self.ky_m)

    @property
    def governing(self) -> ElasticResult:
        """The state whose stresses govern: Stage I if uncracked, else Stage II."""
        return self.cracked_state if self.cracked else self.uncracked


def cracking_factor(sigma_ct_mpa: float, fctm: float) -> float:
    """Load factor to first cracking, ``f_ctm / sigma_ct,I``.

    ``sigma_ct_mpa`` is the uncracked peak concrete tensile stress under the
    applied load (MPa). Returns ``inf`` when the section is nowhere in net
    tension (it never cracks under proportional scaling of this load).
    """
    if sigma_ct_mpa <= 0.0:
        return math.inf
    return fctm / sigma_ct_mpa


def tension_stiffening_zeta(lambda_cr: float, beta: float) -> float:
    """EC2 distribution coefficient ``zeta = 1 - beta * lambda_cr^2``.

    Zero (use the uncracked state) when ``lambda_cr >= 1`` (uncracked); clamped
    to ``[0, 1]``. As ``lambda_cr -> 0`` (deeply cracked) ``zeta -> 1`` and the
    mean response approaches the fully cracked state.
    """
    if lambda_cr >= 1.0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - beta * lambda_cr * lambda_cr))


def _depth_axis(kx: float, ky: float) -> tuple[float, float, float]:
    """Unit gradient direction of the strain plane and its magnitude.

    Strain increases along ``(gx, gy)``; ``mag`` is ``|grad eps|`` so that the
    strain at depth coordinate ``s`` is ``eps0 + mag * s``.
    """
    mag = math.hypot(kx, ky)
    if mag < 1.0e-12:
        return 0.0, 0.0, 0.0
    return kx / mag, ky / mag, mag


def _crack_width(
    section: Section,
    cracked_state: ElasticResult,
    n: float,
    fctm: float,
    Es: float,
    cover: float,
    kt: float,
    k1: Union[float, Sequence[float]],
    k2: float,
    k3: float,
    k4: float,
    bar_diameter: Optional[float],
) -> Optional[CrackWidthResult]:
    """EC2 7.3.4 crack width, evaluated per bar, returning the largest-wk bar.

    ``fctm`` and ``Es`` are in MPa. ``bar_diameter`` (mm) overrides the diameter
    derived from each bar's area. ``cover`` (mm), when given, is used for every
    bar; when ``None`` each bar's clear cover is taken from the geometry as the
    distance to the nearest concrete face minus half its diameter. The effective
    tension area, height and reinforcement ratio are section quantities (defined
    for the bending direction); the crack spacing and mean strain are then formed
    per bar (its own cover, diameter and Stage II stress) and the bar with the
    largest ``wk`` governs. Returns ``None`` when there is no tension bar in the
    effective zone or no usable bending gradient (pure axial tension uses a
    different effective-area definition).
    """
    bx, by, ba = section.bar_arrays()
    if not bx.size:
        return None
    sigma = np.asarray(cracked_state.bar_stress, dtype=float) / _KPA_PER_MPA  # MPa
    if float(sigma.max()) <= 0.0:
        return None  # no bar in tension -> no crack to control

    gx, gy, mag = _depth_axis(cracked_state.kx, cracked_state.ky)
    if mag == 0.0:
        return None  # no bending gradient; uniform-strain cracking not handled

    verts = section.concrete_vertices()
    s_vert = verts[:, 0] * gx + verts[:, 1] * gy
    s_tface = float(s_vert.max())
    s_cface = float(s_vert.min())
    h = s_tface - s_cface
    s_na = -cracked_state.eps0 / mag
    s_bars = bx * gx + by * gy
    gov0 = int(np.argmax(sigma))                   # deepest tension fibre
    d = float(s_bars[gov0]) - s_cface              # effective depth
    # EC2 hc,ef = min(2.5(h-d), (h-x)/3, h/2). The neutral-axis depth x is measured
    # from the compression face, so (h-x) = s_tface - s_na (the tension-side depth),
    # not h - s_na (which would only match when the compression face is at s = 0).
    hc_ef = min(2.5 * (h - d), (s_tface - s_na) / 3.0, h / 2.0)
    if hc_ef <= 0.0:
        return None

    # Effective tension area: the concrete band of depth hc_ef at the tension
    # face, i.e. s >= s_tface - hc_ef. Clip each ring to that half-plane.
    c_lo = s_tface - hc_ef
    ac_eff = 0.0
    for ring in section.integration_rings():
        clipped = clip_halfplane(ring, gx, gy, -c_lo)
        ac_eff += area_moments(clipped).area
    if ac_eff <= 0.0:
        return None

    # Reinforcement inside the effective band sets the (shared) ratio rho_p,eff.
    in_band = s_bars >= c_lo
    as_eff = float(ba[in_band].sum())
    if as_eff <= 0.0:
        return None
    rho = as_eff / ac_eff
    alpha_e = n
    # k1 (bond) may be a scalar (all reinforcement) or one value per bar -- e.g.
    # the mild-steel value for ordinary bars and 1.6 for prestressing tendons.
    k1_arr = np.broadcast_to(np.asarray(k1, dtype=float), (bx.size,))

    # Per-bar crack width: each tension bar in the band uses its own cover,
    # diameter and Stage II stress; the largest wk governs.
    rings = list(section.integration_rings())
    best: Optional[CrackWidthResult] = None
    for i in range(bx.size):
        if not in_band[i] or sigma[i] <= 0.0:
            continue
        sigma_s = float(sigma[i])
        if bar_diameter is not None and bar_diameter > 0.0:
            phi = float(bar_diameter)
        else:
            phi = math.sqrt(4.0 * float(ba[i]) * 1.0e6 / math.pi)  # m^2 -> mm
        if cover is not None:
            c_i = float(cover)
        else:
            # Clear cover to the bar surface = distance to the nearest concrete
            # face (m -> mm) minus the bar radius.
            c_i = max(distance_to_boundary(float(bx[i]), float(by[i]), rings)
                      * 1000.0 - phi / 2.0, 0.0)
        # EC2 (7.9): mean strain, with the 0.6 sigma_s/Es lower bound.
        esm_ecm = max((sigma_s - kt * fctm / rho * (1.0 + alpha_e * rho)) / Es,
                      0.6 * sigma_s / Es)
        # EC2 (7.11): maximum crack spacing (cover and phi in mm).
        sr_max = k3 * c_i + float(k1_arr[i]) * k2 * k4 * phi / rho
        wk = sr_max * esm_ecm
        if best is None or wk > best.wk:
            best = CrackWidthResult(
                wk=wk, sr_max=sr_max, esm_ecm=esm_ecm, sigma_s=sigma_s,
                rho_p_eff=rho, ac_eff=ac_eff, hc_ef=hc_ef, phi=phi, cover=c_i,
                gov_bar=i,
            )
    return best


def analyse_cracking(
    section: Section,
    P: float,
    Mx: float,
    My: float,
    n: float,
    *,
    fctm: float,
    Es: float = 200_000.0,
    beta: float = 1.0,
    kt: float = 0.6,
    cover: Optional[float] = None,
    bar_diameter: Optional[float] = None,
    k1: Union[float, Sequence[float]] = 0.8,
    k2: float = 0.5,
    k3: float = 3.4,
    k4: float = 0.425,
) -> CrackingResult:
    """Serviceability analysis of the section under one action combination.

    Parameters
    ----------
    section, P, Mx, My, n:
        As for :func:`sector.elastic.solve_elastic` -- the action combination and
        the (effective, creep-adjusted) modular ratio for the serviceability
        check.
    fctm:
        Concrete mean tensile strength (MPa); use :func:`sector.codes.fctm`.
    Es:
        Reinforcement modulus (MPa).
    beta:
        Tension-stiffening load-duration factor: ``1.0`` short-term / single
        load, ``0.5`` sustained or repeated.
    kt:
        Crack-width load-duration factor (EC2 7.9): ``0.6`` short-term,
        ``0.4`` long-term.
    cover:
        Clear cover override (mm) applied to every bar. When ``None`` (default)
        each bar's clear cover is taken from the geometry (distance to the nearest
        concrete face minus the bar radius). Crack width is computed whenever the
        section is cracked.
    bar_diameter:
        Governing bar diameter (mm); defaults to the equivalent circular
        diameter of the governing bar's area.
    k1, k2, k3, k4:
        EC2 crack-spacing coefficients (recommended values by default). ``k1``
        (the bond coefficient) may be a single value or one per bar -- e.g. the
        mild-steel value for ordinary bars and 1.6 for prestressing tendons.

    Returns
    -------
    CrackingResult
        Cracking decision, ``lambda_cr``, ``zeta``, the Stage I and Stage II
        solves, the mean tension-stiffened strain plane, and the crack width.
    """
    uncr = solve_elastic_uncracked(section, P, Mx, My, n)
    sigma_ct = uncr.max_concrete_tension / _KPA_PER_MPA  # MPa
    lam = cracking_factor(sigma_ct, fctm)
    cracked = lam < 1.0

    crk = solve_elastic(section, P, Mx, My, n)
    zeta = tension_stiffening_zeta(lam, beta) if cracked else 0.0

    # Mean (tension-stiffened) strain plane: interpolate Stage I and Stage II.
    eps0_m = zeta * crk.eps0 + (1.0 - zeta) * uncr.eps0
    kx_m = zeta * crk.kx + (1.0 - zeta) * uncr.kx
    ky_m = zeta * crk.ky + (1.0 - zeta) * uncr.ky

    crack = None
    if cracked:
        crack = _crack_width(
            section, crk, n, fctm, Es, cover, kt, k1, k2, k3, k4, bar_diameter
        )

    return CrackingResult(
        cracked=cracked, lambda_cr=lam, sigma_ct=sigma_ct, fctm=fctm, zeta=zeta,
        uncracked=uncr, cracked_state=crk, eps0_m=eps0_m, kx_m=kx_m, ky_m=ky_m,
        crack=crack,
    )


def crack_width(
    section: Section,
    cracked_state: ElasticResult,
    n: float,
    *,
    fctm: float,
    Es: float = 200_000.0,
    kt: float = 0.6,
    cover: Optional[float] = None,
    bar_diameter: Optional[float] = None,
    k1: Union[float, Sequence[float]] = 0.8,
    k2: float = 0.5,
    k3: float = 3.4,
    k4: float = 0.425,
) -> Optional[CrackWidthResult]:
    """EC2 7.3.4 crack width for an externally supplied cracked-section state.

    Unlike :func:`analyse_cracking`, the cracked state is given rather than solved
    here, so it can carry a steel stress that is not a single linear solve -- e.g.
    the instantaneous (short-term) state of the combined creep analysis, whose
    bar stress is ``s2 + RST1``. ``cracked_state`` supplies the neutral axis /
    strain gradient and the per-bar steel stress; the bar with the largest ``wk``
    governs. See :func:`analyse_cracking` for the remaining parameters.
    """
    return _crack_width(section, cracked_state, n, fctm, Es, cover, kt,
                        k1, k2, k3, k4, bar_diameter)
