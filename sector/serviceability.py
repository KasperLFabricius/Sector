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

from .elastic import (
    ElasticResult,
    solve_elastic,
    solve_elastic_uncracked,
    transformed_properties,
)
from .geometry import (
    AreaMoments,
    area_moments,
    clip_halfplane,
    distance_to_boundary,
)
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
    coarse: bool = False  # DK NA coarse crack system (centroid-matched Ac,eff, wk/2)
    edition: str = "2004"  # "2004" (EC2 7.3.4) or "2023" (EC2 9.2.3 refined)
    kw: float = 1.0      # 2023 mean->characteristic factor (9.8); 1.0 for 2004
    k1_r: float = 1.0    # 2023 curvature factor k1/r (9.9); 1.0 for 2004
    kfl: float = 1.0     # 2023 flexural coefficient (9.16/9.17); 1.0 for 2004


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


def _band_moments(rings, gx: float, gy: float, c_lo: float) -> AreaMoments:
    """Area moments of the section clipped to the tension band ``s >= c_lo``
    (``s`` measured along the depth axis ``(gx, gy)``)."""
    total = AreaMoments(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    for ring in rings:
        total = total + area_moments(clip_halfplane(ring, gx, gy, -c_lo))
    return total


def _centroid_matched_lo(rings, gx: float, gy: float, s_tface: float,
                         s_cface: float, s_target: float) -> float:
    """Lower bound ``c_lo`` of the tension band ``[c_lo, s_tface]`` whose
    area-centroid (along the depth axis) coincides with ``s_target``.

    This is the DK NA coarse-system effective area (figure 7.100 NA): the largest
    concrete area at the tension face whose centroid matches the tension
    reinforcement's centroid. The band centroid falls monotonically as ``c_lo``
    drops (the band grows inward from the tension face), so a bisection converges;
    ``s_target`` lies between the full-section centroid and ``s_tface``.
    """
    lo, hi = s_cface, s_tface
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        m = _band_moments(rings, gx, gy, mid)
        too_high = m.area <= 0.0 or (m.sx * gx + m.sy * gy) / m.area > s_target
        if too_high:
            hi = mid                 # centroid too near the tension face -> grow band
        else:
            lo = mid                 # band too deep -> shrink it (raise c_lo)
        if hi - lo < 1.0e-9:
            break
    return 0.5 * (lo + hi)


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
    k3_cover_dependent: bool = False,
    include_hx_term: bool = True,
    coarse: bool = False,
    edition: str = "2004",
    n_mult: Optional[np.ndarray] = None,
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

    Three flags select the DK NA crack-width rules. ``k3_cover_dependent`` replaces
    the cover-term coefficient ``k3`` by ``k3*(25/c)^(2/3)`` (DK NA 7.3.4(3)).
    ``include_hx_term`` (default ``True``) keeps the ``(h-x)/3`` limit in
    ``hc,ef``; set it ``False`` for an ordinary beam under the DK NA, where that
    limit applies only to slabs and prestressed members (7.3.2(3)). ``coarse``
    selects the DK NA coarse crack system (7.3.4(1)): the effective tension area
    becomes the band at the tension face whose centroid matches the tension
    reinforcement (figure 7.100 NA) instead of the EC2 ``hc,ef`` band, and the
    crack width is halved. ``include_hx_term`` is then irrelevant. ``edition``
    ``"2023"`` switches to the EN 1992-1-1:2023 refined model (9.2.3), a different
    formula handled by :func:`_crack_width_2023`; the DK NA flags then do not apply.
    """
    if edition == "2023":
        return _crack_width_2023(section, cracked_state, n, fctm, Es, cover, kt,
                                 k1, bar_diameter, n_mult=n_mult)
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
    w_bars = -gy * bx + gx * by                    # in-plane width coord (m)
    gov0 = int(np.argmax(sigma))                   # deepest tension fibre
    d = float(s_bars[gov0]) - s_cface              # effective depth
    rings = list(section.integration_rings())
    if coarse:
        # DK NA coarse crack system (7.3.4(1)): the effective tension area is the
        # band at the tension face whose area-centroid matches the tension
        # reinforcement's centroid (figure 7.100 NA); for a rectangle this is the
        # 2*b*(h-d) band. The crack width (7.8) is then halved (applied below).
        tens = sigma > 0.0
        s_rc = float(np.sum(ba[tens] * s_bars[tens]) / np.sum(ba[tens]))
        c_lo = _centroid_matched_lo(rings, gx, gy, s_tface, s_cface, s_rc)
        hc_ef = s_tface - c_lo
        ac_eff = _band_moments(rings, gx, gy, c_lo).area
    else:
        # EC2 hc,ef = min(2.5(h-d), (h-x)/3, h/2). The neutral-axis depth x is
        # measured from the compression face, so (h-x) = s_tface - s_na (the
        # tension-side depth), not h - s_na (which would only match when the
        # compression face is at s = 0). The (h-x)/3 limit can be dropped (DK NA
        # 7.3.2(3): it applies only to slabs and prestressed members).
        if include_hx_term:
            hc_ef = min(2.5 * (h - d), (s_tface - s_na) / 3.0, h / 2.0)
        else:
            hc_ef = min(2.5 * (h - d), h / 2.0)
        # Effective tension area: the concrete band of depth hc_ef at the tension
        # face, i.e. s >= s_tface - hc_ef. Clip each ring to that half-plane.
        c_lo = s_tface - hc_ef
        ac_eff = sum(area_moments(clip_halfplane(r, gx, gy, -c_lo)).area
                     for r in rings)
    if hc_ef <= 0.0 or ac_eff <= 0.0:
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
    wk_factor = 0.5 if coarse else 1.0   # DK NA coarse system halves wk (7.3.4(1))
    band_tens = in_band & (sigma > 0.0)  # tension bars that set the crack spacing
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
        # EC2 (7.11): maximum crack spacing (cover and phi in mm). Under the DK NA
        # (7.3.4(3)) the cover term coefficient is k3*(25/c)^(2/3) instead of k3.
        k3_i = k3 * (25.0 / c_i) ** (2.0 / 3.0) if k3_cover_dependent and c_i > 0.0 else k3
        sr_max = k3_i * c_i + float(k1_arr[i]) * k2 * k4 * phi / rho
        # EC2 (7.14): the geometric bound 1.3*(h-x) is the ALTERNATIVE spacing for
        # bars NOT fixed at close centres. Clause 7.3.4(3) applies (7.11) only where
        # the bar spacing does not exceed 5(c+phi/2); beyond that the bound governs.
        # Apply it as a cap only for a bar whose nearest in-band tension neighbour is
        # farther than 5(c+phi/2), so a closely spaced but shallow tension zone
        # (bending with axial compression -> small h-x) is not clipped below its real
        # (7.11) spacing. A lone bar (no neighbour) counts as wide. (h-x) = s_tface -
        # s_na; widths are in m, cover/phi in mm.
        neigh = band_tens.copy()
        neigh[i] = False
        nn = float(np.min(np.abs(w_bars[neigh] - w_bars[i]))) if neigh.any() else math.inf
        if nn * 1000.0 > 5.0 * (c_i + phi / 2.0):
            sr_max = min(sr_max, 1.3 * (s_tface - s_na) * 1000.0)
        wk = wk_factor * sr_max * esm_ecm
        if best is None or wk > best.wk:
            best = CrackWidthResult(
                wk=wk, sr_max=sr_max, esm_ecm=esm_ecm, sigma_s=sigma_s,
                rho_p_eff=rho, ac_eff=ac_eff, hc_ef=hc_ef, phi=phi, cover=c_i,
                gov_bar=i, coarse=coarse,
            )
    return best


_KW_2023 = 1.7   # EN 1992-1-1:2023 (9.8) NOTE 1: mean -> calculated crack width


def _crack_width_2023(
    section: Section,
    cracked_state: ElasticResult,
    n: float,
    fctm: float,
    Es: float,
    cover: Optional[float],
    kt: float,
    k1: Union[float, Sequence[float]],
    bar_diameter: Optional[float],
    n_mult: Optional[np.ndarray] = None,
) -> Optional[CrackWidthResult]:
    """EN 1992-1-1:2023 refined crack width (9.2.3), per bar, largest-wk governs.

    Implements the bending case of Formula (9.8)::

        wk,cal = kw * k1/r * sr,m,cal * (eps_sm - eps_cm)

    with ``kw = 1.7`` (9.8 NOTE 1); the per-bar curvature factor ``k1/r`` (9.9); the
    mean crack spacing ``sr,m,cal`` (9.15) with the flexural coefficient ``kfl``
    (9.17) and bond factor ``kb`` (9.18); the effective height ``hc,eff`` (figure
    9.3, single layer); and the mean strain (9.11) whose lower bound is now
    ``(1 - kt) * sigma_s / Es``. ``bar_diameter`` (mm) overrides the area-derived
    diameter; ``cover`` (mm) overrides the per-bar geometric cover. The ``k1`` bond
    values map to ``kb`` (good bond -> 0.9, poor -> 1.2). Returns ``None`` when no
    tension bar sits in the effective zone or there is no bending gradient.
    """
    bx, by, ba = section.bar_arrays()
    if not bx.size:
        return None
    sigma = np.asarray(cracked_state.bar_stress, dtype=float) / _KPA_PER_MPA  # MPa
    if float(sigma.max()) <= 0.0:
        return None
    gx, gy, mag = _depth_axis(cracked_state.kx, cracked_state.ky)
    if mag == 0.0:
        return None

    verts = section.concrete_vertices()
    s_vert = verts[:, 0] * gx + verts[:, 1] * gy
    s_tface = float(s_vert.max())
    s_cface = float(s_vert.min())
    h = s_tface - s_cface
    s_na = -cracked_state.eps0 / mag
    hx = s_tface - s_na                 # (h - x): tension-zone depth at the cracked NA
    if hx <= 0.0:
        return None
    s_bars = bx * gx + by * gy
    ay = s_tface - s_bars               # distance from the tension face to each bar (m)
    # Effective layers: bars that are in tension (Stage II stress) AND geometrically
    # below the neutral axis. An externally supplied combined-creep state can leave a
    # bar above the NA with a small positive residual stress; the per-bar loop skips
    # it (denom <= 0), so it must not expand hc,eff / dilute rho_p,eff either.
    tens = (sigma > 0.0) & (ay < hx)
    if not tens.any():
        return None
    gov0 = int(np.argmax(np.where(tens, sigma, -np.inf)))   # governing tension bar

    def _phi(i):
        if bar_diameter is not None and bar_diameter > 0.0:
            return float(bar_diameter)
        return math.sqrt(4.0 * float(ba[i]) * 1.0e6 / math.pi)   # m^2 -> mm

    # hc,eff (figure 9.3, bending): the single-layer band min{ay+5phi, 10phi, 3.5ay}
    # (phi in mm -> m) is built from the reinforcement nearest the tension face, then
    # extended by the depth spread of the tension bars so a section reinforced in
    # several layers is covered -- the general form of the n-layer +(n-1)*sy term
    # (which is zero for a single layer). The result is capped at h-x and h/2.
    phi_gov_m = _phi(gov0) / 1000.0
    ay_near = float(ay[tens].min())             # bars nearest the tension face
    ay_far = float(ay[tens].max())              # deepest tension bars
    base = min(ay_near + 5.0 * phi_gov_m, 10.0 * phi_gov_m, 3.5 * ay_near)
    hc_ef = min(base + (ay_far - ay_near), hx, h / 2.0)
    if hc_ef <= 0.0:
        return None
    c_lo = s_tface - hc_ef
    rings = list(section.integration_rings())
    ac_eff = sum(area_moments(clip_halfplane(r, gx, gy, -c_lo)).area for r in rings)
    if ac_eff <= 0.0:
        return None
    in_band = s_bars >= c_lo
    as_eff = float(ba[in_band].sum())
    if as_eff <= 0.0:
        return None
    rho = as_eff / ac_eff
    alpha_e = n

    # kfl (9.17, general; reduces to (9.16) for a rectangle): needs xg, the uncracked
    # transformed-section neutral axis (its centroid), projected on the depth axis.
    # n_mult carries the per-bar modular ratio (Ep/Es for tendons) so a prestressed
    # section's transformed centroid is correct.
    props = transformed_properties(section, n, cracked=False, n_mult=n_mult)
    h_minus_xg = s_tface - (props.cx * gx + props.cy * gy)
    if h_minus_xg > 1.0e-9:
        kfl = 0.5 * (1.0 + (h_minus_xg - hc_ef) / h_minus_xg)
    else:
        kfl = (h - hc_ef) / h          # degenerate fallback
    kfl = max(0.0, kfl)

    k1_arr = np.broadcast_to(np.asarray(k1, dtype=float), (bx.size,))
    sr_cap = 1.3 / _KW_2023 * hx * 1000.0   # (1.3/kw)*(h-x), m -> mm
    best: Optional[CrackWidthResult] = None
    for i in range(bx.size):
        if not in_band[i] or sigma[i] <= 0.0:
            continue
        denom = hx - float(ay[i])      # (h - x) - ay,i ; the bar must be below the NA
        if denom <= 1.0e-9:
            continue
        sigma_s = float(sigma[i])
        phi = _phi(i)
        if cover is not None:
            c_i = float(cover)
        else:
            c_i = max(distance_to_boundary(float(bx[i]), float(by[i]), rings)
                      * 1000.0 - phi / 2.0, 0.0)
        # (9.11): mean strain; lower bound (1 - kt)*sigma_s/Es (was a fixed 0.6 in 2004).
        esm_ecm = max((sigma_s - kt * fctm / rho * (1.0 + alpha_e * rho)) / Es,
                      (1.0 - kt) * sigma_s / Es)
        # (9.18) bond factor: good bond (ribbed, k1<=1.0) -> 0.9, poor (plain) -> 1.2.
        kb = 0.9 if float(k1_arr[i]) <= 1.0 else 1.2
        # (9.15) mean crack spacing = 1.5c + (kfl*kb/7.2)*(phi/rho), capped at
        # (1.3/kw)*(h-x). Cover and phi in mm.
        sr = min(1.5 * c_i + kfl * kb / 7.2 * phi / rho, sr_cap)
        k1r = hx / denom               # (9.9) curvature factor, >= 1
        wk = _KW_2023 * k1r * sr * esm_ecm
        if best is None or wk > best.wk:
            best = CrackWidthResult(
                wk=wk, sr_max=sr, esm_ecm=esm_ecm, sigma_s=sigma_s,
                rho_p_eff=rho, ac_eff=ac_eff, hc_ef=hc_ef, phi=phi, cover=c_i,
                gov_bar=i, edition="2023", kw=_KW_2023, k1_r=k1r, kfl=kfl,
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
    k3_cover_dependent: bool = False,
    include_hx_term: bool = True,
    coarse: bool = False,
    edition: str = "2004",
    n_mult: Optional[np.ndarray] = None,
    prestress_stress: Optional[np.ndarray] = None,
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
    uncr = solve_elastic_uncracked(section, P, Mx, My, n, n_mult=n_mult,
                                   prestress_stress=prestress_stress)
    sigma_ct = uncr.max_concrete_tension / _KPA_PER_MPA  # MPa, peak total tension
    if prestress_stress is None:
        lam = cracking_factor(sigma_ct, fctm)
    else:
        # The tendon prestress is a fixed (permanent) action; only the external
        # P/M are factored. Decompression: cracking when sigma_pre + lam*sigma_ext
        # = fctm at some fibre, i.e. lam = min_i (fctm - sigma_pre,i)/sigma_ext,i
        # over fibres the external load puts into tension. (Reduces to
        # fctm/sigma_ct when there is no prestress, since then sigma_pre = 0.)
        ext = solve_elastic_uncracked(section, P, Mx, My, n, n_mult=n_mult)
        verts = section.concrete_vertices()
        sig_tot = (uncr.eps0 + uncr.kx * verts[:, 0]
                   + uncr.ky * verts[:, 1]) / _KPA_PER_MPA
        sig_ext = (ext.eps0 + ext.kx * verts[:, 0]
                   + ext.ky * verts[:, 1]) / _KPA_PER_MPA
        sig_pre = sig_tot - sig_ext                          # prestress alone
        loaded = sig_ext > 1.0e-9                            # external puts in tension
        lam = (float(np.min((fctm - sig_pre[loaded]) / sig_ext[loaded]))
               if np.any(loaded) else math.inf)
    cracked = lam < 1.0
    lam = max(0.0, lam) if math.isfinite(lam) else lam       # no negative load factor

    crk = solve_elastic(section, P, Mx, My, n, n_mult=n_mult,
                        prestress_stress=prestress_stress)
    zeta = tension_stiffening_zeta(lam, beta) if cracked else 0.0

    # Mean (tension-stiffened) strain plane: interpolate Stage I and Stage II.
    eps0_m = zeta * crk.eps0 + (1.0 - zeta) * uncr.eps0
    kx_m = zeta * crk.kx + (1.0 - zeta) * uncr.kx
    ky_m = zeta * crk.ky + (1.0 - zeta) * uncr.ky

    crack = None
    if cracked:
        crack = _crack_width(
            section, crk, n, fctm, Es, cover, kt, k1, k2, k3, k4, bar_diameter,
            k3_cover_dependent=k3_cover_dependent, include_hx_term=include_hx_term,
            coarse=coarse, edition=edition, n_mult=n_mult,
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
    k3_cover_dependent: bool = False,
    include_hx_term: bool = True,
    coarse: bool = False,
    edition: str = "2004",
    n_mult: Optional[np.ndarray] = None,
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
                        k1, k2, k3, k4, bar_diameter,
                        k3_cover_dependent=k3_cover_dependent,
                        include_hx_term=include_hx_term, coarse=coarse,
                        edition=edition, n_mult=n_mult)
