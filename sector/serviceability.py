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
    ring_without_terminal_closure,
)
from .section import Section

# kN/m^2 per MPa: the solver returns stresses in kN/m^2 for sections built in
# kN/m/m units, so a stress in MPa is 1000x the numeric value.
_KPA_PER_MPA = 1000.0

CRACK_SCOPE_DOMINANT_DIRECTION = "dominant-direction"
CRACK_SCOPE_DIRECT_TENSION = "uniform-direct-tension"
CRACK_DIRECTIONAL_LIMITATION = (
    "The canonical crack response is a one-directional dominant strain-gradient "
    "assessment. Orthogonal or inclined systems are not included in that component "
    "conclusion; only separately selected, in-domain multidirectional evidence can "
    "provide an aggregate conclusion."
)
CRACK_DIRECT_TENSION_SCOPE = (
    "Validated uniform direct-tension branch for a solid rectangular section with "
    "reinforcement assigned to opposed faces."
)
_UNIFORM_TENSION_REL_TOL = 1.0e-8


@dataclass(frozen=True)
class EffectiveReinforcement2023:
    """Auditable EN 1992-1-1:2023 Formula (9.12) reinforcement terms."""

    as_eff: float
    ap_eff: float
    ap_eff_weighted: float
    rho_p_eff: float
    xi1_by_element: tuple[Optional[float], ...]


@dataclass(frozen=True)
class CrackWidthEvaluation:
    """Numerical result plus the public applicability disposition."""

    status: str
    reason: str
    result: Optional["CrackWidthResult"] = None


def _not_assessed(reason: str) -> CrackWidthEvaluation:
    return CrackWidthEvaluation("NOT ASSESSED", reason)


def _not_applicable(reason: str) -> CrackWidthEvaluation:
    return CrackWidthEvaluation("NOT APPLICABLE", reason)


def _calculated(result: "CrackWidthResult") -> CrackWidthEvaluation:
    return CrackWidthEvaluation("CALCULATED", "Crack width calculated.", result)


@dataclass
class CrackWidthCandidate:
    """One reinforcement element considered by the crack-width calculation."""

    bar_index: int       # zero-based index in Section.bar_arrays()
    x: float             # section x coordinate (m)
    y: float             # section y coordinate (m)
    area: float          # element area (mm2)
    wk: float            # crack width (mm)
    sr_max: float        # maximum / calculated mean crack spacing (mm)
    esm_ecm: float       # mean strain difference, dimensionless
    sigma_s: float       # Stage II steel stress (MPa)
    rho_p_eff: float
    ac_eff: float        # effective tension area (m2)
    hc_ef: float         # effective tension height (m)
    phi: float           # equivalent / overridden diameter (mm)
    cover: float         # clear cover (mm)
    coarse: bool = False
    edition: str = "2004"
    kw: float = 1.0
    k1_r: float = 1.0
    kfl: float = 1.0
    sr_max_geometric: bool = False
    as_eff: float = 0.0       # non-prestressed area in Ac,eff (m2)
    ap_eff: float = 0.0       # prestressed area in Ac,eff (m2)
    ap_eff_weighted: float = 0.0  # sum(xi1 * Ap) in Ac,eff (m2)
    xi1: Optional[float] = None
    reinforcement_type: str = "mild"
    bc_ef: float = 0.0        # direct-tension effective width (m)
    direct_tension: bool = False
    scope: str = CRACK_SCOPE_DOMINANT_DIRECTION
    direction_deg: Optional[float] = None


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
    phi: float           # governing reinforcement-element diameter (mm)
    cover: float         # clear cover to that bar's surface (mm)
    gov_bar: int         # index of the governing (largest-wk) bar
    coarse: bool = False  # DK NA coarse crack system (centroid-matched Ac,eff, wk/2)
    edition: str = "2004"  # "2004" (EC2 7.3.4) or "2023" (EC2 9.2.3 refined)
    kw: float = 1.0      # 2023 mean->characteristic factor (9.8); 1.0 for 2004
    k1_r: float = 1.0    # 2023 curvature factor k1/r (9.9); 1.0 for 2004
    kfl: float = 1.0     # 2023 flexural coefficient (9.16/9.17); 1.0 for 2004
    sr_max_geometric: bool = False  # 2004 wide-spacing: sr_max is Eq (7.14) 1.3(h-x), not (7.11)
    candidates: tuple[CrackWidthCandidate, ...] = ()
    as_eff: float = 0.0       # non-prestressed area in Ac,eff (m2)
    ap_eff: float = 0.0       # prestressed area in Ac,eff (m2)
    ap_eff_weighted: float = 0.0  # sum(xi1 * Ap) in Ac,eff (m2)
    xi1_min: Optional[float] = None
    xi1_max: Optional[float] = None
    bc_ef: float = 0.0        # direct-tension effective width (m)
    direct_tension: bool = False
    scope: str = CRACK_SCOPE_DOMINANT_DIRECTION
    direction_deg: Optional[float] = None


def _governing_crack(
    candidates: list[CrackWidthCandidate],
    effective_xi1: Optional[Sequence[float]] = None,
) -> Optional[CrackWidthResult]:
    """Return the largest-``wk`` candidate and retain the full sorted audit set."""
    if not candidates:
        return None
    ordered = tuple(sorted(candidates, key=lambda c: (-c.wk, c.bar_index)))
    c = ordered[0]
    xi1_values = (
        [float(value) for value in effective_xi1]
        if effective_xi1 is not None
        else [item.xi1 for item in ordered if item.xi1 is not None]
    )
    return CrackWidthResult(
        wk=c.wk, sr_max=c.sr_max, esm_ecm=c.esm_ecm, sigma_s=c.sigma_s,
        rho_p_eff=c.rho_p_eff, ac_eff=c.ac_eff, hc_ef=c.hc_ef,
        phi=c.phi, cover=c.cover, gov_bar=c.bar_index, coarse=c.coarse,
        edition=c.edition, kw=c.kw, k1_r=c.k1_r, kfl=c.kfl,
        sr_max_geometric=c.sr_max_geometric, candidates=ordered,
        as_eff=c.as_eff, ap_eff=c.ap_eff,
        ap_eff_weighted=c.ap_eff_weighted,
        xi1_min=min(xi1_values) if xi1_values else None,
        xi1_max=max(xi1_values) if xi1_values else None,
        bc_ef=c.bc_ef, direct_tension=c.direct_tension,
        scope=c.scope, direction_deg=c.direction_deg,
    )


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
    crack_evaluation: Optional[CrackWidthEvaluation] = None

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


def _reinforcement_type_array(
    reinforcement_types: Optional[Sequence[str]],
    count: int,
) -> np.ndarray:
    if reinforcement_types is None:
        return np.full(count, "mild", dtype=object)
    values = np.asarray(list(reinforcement_types), dtype=object)
    if values.shape != (count,):
        raise ValueError(
            f"need {count} reinforcement-type values, got {values.size}"
        )
    normalised = np.asarray([str(value).strip().lower() for value in values])
    aliases = {
        "bar": "mild",
        "reinforcement": "mild",
        "rebar": "mild",
        "tendon": "prestress",
        "prestressing": "prestress",
    }
    normalised = np.asarray(
        [aliases.get(value, value) for value in normalised],
        dtype=object,
    )
    invalid = sorted(set(normalised) - {"mild", "prestress"})
    if invalid:
        raise ValueError(
            "reinforcement type must be mild or prestress; got "
            + ", ".join(invalid)
        )
    return normalised


def effective_reinforcement_ratio_2023(
    areas_m2: Sequence[float],
    in_effective_area: Sequence[bool],
    diameters_mm: Sequence[float],
    *,
    ac_eff_m2: float,
    reinforcement_types: Optional[Sequence[str]] = None,
    bond_ratio_xi: Optional[Union[float, Sequence[float]]] = None,
) -> EffectiveReinforcement2023:
    """Return Formula (9.12), deriving ``xi1`` from Formula (9.6).

    ``bond_ratio_xi`` is the tendon-to-ribbed-reinforcement bond-strength ratio
    ``xi``. In a mixed section ``xi1 = sqrt(xi * phi_s / phi_p)`` using the
    largest effective mild-bar diameter and each tendon's equivalent diameter.
    Where prestressing steel alone controls cracking, Formula (9.6) sets
    ``xi1 = xi``.
    """

    areas = np.asarray(areas_m2, dtype=float)
    in_area = np.asarray(in_effective_area, dtype=bool)
    diameters = np.asarray(diameters_mm, dtype=float)
    if areas.ndim != 1:
        raise ValueError("reinforcement areas must be one-dimensional")
    count = areas.size
    if in_area.shape != (count,) or diameters.shape != (count,):
        raise ValueError("reinforcement area, mask and diameter arrays must align")
    if not math.isfinite(float(ac_eff_m2)) or float(ac_eff_m2) <= 0.0:
        raise ValueError("Ac,eff must be finite and positive")
    if np.any(~np.isfinite(areas)) or np.any(areas <= 0.0):
        raise ValueError("reinforcement areas must be finite and positive")
    if np.any(~np.isfinite(diameters)) or np.any(diameters <= 0.0):
        raise ValueError("reinforcement diameters must be finite and positive")

    kinds = _reinforcement_type_array(reinforcement_types, count)
    mild = in_area & (kinds == "mild")
    prestress = in_area & (kinds == "prestress")
    as_eff = float(areas[mild].sum())
    ap_eff = float(areas[prestress].sum())

    xi1_values = np.full(count, np.nan, dtype=float)
    weighted_ap = 0.0
    if prestress.any():
        if bond_ratio_xi is None:
            raise ValueError(
                "bond ratio xi is required for prestressing steel in the 2023 "
                "effective reinforcement area"
            )
        boolean_xi = isinstance(bond_ratio_xi, (bool, np.bool_))
        if (
            not boolean_xi
            and isinstance(bond_ratio_xi, np.ndarray)
            and bond_ratio_xi.dtype.kind == "b"
        ):
            boolean_xi = True
        if not boolean_xi and not np.isscalar(bond_ratio_xi):
            try:
                boolean_xi = any(
                    isinstance(value, (bool, np.bool_))
                    for value in bond_ratio_xi
                )
            except TypeError:
                boolean_xi = False
        if boolean_xi:
            raise ValueError(
                "prestressing bond ratio xi must be a real number, not Boolean"
            )
        xi = np.broadcast_to(
            np.asarray(bond_ratio_xi, dtype=float),
            (count,),
        )
        tendon_xi = xi[prestress]
        if (
            np.any(~np.isfinite(tendon_xi))
            or np.any(tendon_xi <= 0.0)
            or np.any(tendon_xi > 1.0)
        ):
            raise ValueError(
                "prestressing bond ratio xi must be finite and in the interval "
                "0 < xi <= 1"
            )
        if mild.any():
            phi_s = float(diameters[mild].max())
            xi1_values[prestress] = np.sqrt(
                tendon_xi * phi_s / diameters[prestress]
            )
        else:
            # EN 1992-1-1:2023 9.2.2(3), Formula (9.6): if prestressing steel
            # alone controls cracking, xi1 equals xi.
            xi1_values[prestress] = tendon_xi
        if np.any(~np.isfinite(xi1_values[prestress])) or np.any(
            xi1_values[prestress] <= 0.0
        ):
            raise ValueError("calculated xi1 must be finite and positive")
        weighted_ap = float(
            np.sum(areas[prestress] * xi1_values[prestress])
        )

    numerator = as_eff + weighted_ap
    if numerator <= 0.0:
        raise ValueError("no effective crack-control reinforcement is present")
    return EffectiveReinforcement2023(
        as_eff=as_eff,
        ap_eff=ap_eff,
        ap_eff_weighted=weighted_ap,
        rho_p_eff=numerator / float(ac_eff_m2),
        xi1_by_element=tuple(
            None if math.isnan(value) else float(value)
            for value in xi1_values
        ),
    )


def _rectangle_frame(section: Section):
    """Return a rotation-invariant local frame for a solid rectangle."""

    if len(section.concrete) != 1:
        return None
    ring = ring_without_terminal_closure(section.concrete[0])
    if len(ring) != 4:
        return None
    p0, p1, p2, p3 = (np.asarray(point, dtype=float) for point in ring)
    ex = p1 - p0
    ey = p2 - p1
    width = float(np.linalg.norm(ex))
    height = float(np.linalg.norm(ey))
    scale = max(width, height, 1.0)
    if width <= 1.0e-12 or height <= 1.0e-12:
        return None
    ux, uy = ex / width, ey / height
    if abs(float(np.dot(ux, uy))) > 1.0e-8:
        return None
    tol = 1.0e-8 * scale
    if (
        np.linalg.norm(p3 - (p0 + ey)) > tol
        or np.linalg.norm(p2 - (p0 + ex + ey)) > tol
    ):
        return None
    return p0, ux, uy, width, height


def _uniform_tension_regime(
    section: Section,
    cracked_state: ElasticResult,
) -> tuple[bool, bool]:
    """Return ``(all_tension, near_uniform)`` for the cracked strain plane."""

    vertices = section.concrete_vertices()
    values = (
        cracked_state.eps0
        + cracked_state.kx * vertices[:, 0]
        + cracked_state.ky * vertices[:, 1]
    )
    scale = max(
        float(np.max(np.abs(values))),
        float(np.max(np.abs(cracked_state.bar_stress)))
        if np.asarray(cracked_state.bar_stress).size else 0.0,
        1.0,
    )
    tol = _UNIFORM_TENSION_REL_TOL * scale
    all_tension = float(values.min()) > tol
    near_uniform = float(values.max() - values.min()) <= tol
    return all_tension, near_uniform


def _direct_tension_effective_area_2023(
    section: Section,
    phi_arr: np.ndarray,
) -> tuple[np.ndarray, float, float, float] | str:
    """Figure 9.3 direct-tension effective perimeter area for a rectangle."""

    frame = _rectangle_frame(section)
    if frame is None:
        return (
            "Uniform direct tension is validated only for a solid rectangular "
            "section; this geometry is outside that scope."
        )
    origin, ux, uy, width, height = frame
    bx, by, ba = section.bar_arrays()
    points = np.column_stack((bx, by))
    local = points - origin
    u = local @ ux
    v = local @ uy
    distances = np.column_stack((u, width - u, v, height - v))
    if np.any(distances < -1.0e-9):
        return "Reinforcement lies outside the validated direct-tension rectangle."

    nearest = distances.min(axis=1)
    assignment_tol = max(width, height) * 1.0e-8 + 1.0e-10
    assigned = [
        np.flatnonzero(
            np.abs(distances[:, face] - nearest) <= assignment_tol
        )
        for face in range(4)
    ]
    opposed = (
        assigned[0].size
        and assigned[1].size
        and set(assigned[0]).isdisjoint(set(assigned[1]))
    ) or (
        assigned[2].size
        and assigned[3].size
        and set(assigned[2]).isdisjoint(set(assigned[3]))
    )
    if not opposed:
        return (
            "Uniform direct tension requires reinforcement assigned to distinct "
            "opposed faces of the rectangular section."
        )

    normal_dimensions = (width, width, height, height)
    bands = np.zeros(4, dtype=float)
    for face, indices in enumerate(assigned):
        if not indices.size:
            continue
        face_distances = distances[indices, face]
        layer_tol = max(0.0005, normal_dimensions[face] * 1.0e-4)
        if float(face_distances.max() - face_distances.min()) > layer_tol:
            return (
                "Uniform direct-tension reinforcement assigned to one face must "
                "form a single validated layer."
            )
        area_sum = float(ba[indices].sum())
        a_face = float(np.sum(ba[indices] * face_distances) / area_sum)
        phi_face = float(phi_arr[indices].max()) / 1000.0
        bands[face] = min(
            a_face + 5.0 * phi_face,
            10.0 * phi_face,
            3.5 * a_face,
            0.5 * normal_dimensions[face],
        )
        if bands[face] <= 0.0:
            return "Calculated direct-tension effective band is not positive."

    left, right, bottom, top = bands
    inner_width = max(width - left - right, 0.0)
    inner_height = max(height - bottom - top, 0.0)
    ac_eff = width * height - inner_width * inner_height
    in_area = (
        (u <= left + assignment_tol)
        | (width - u <= right + assignment_tol)
        | (v <= bottom + assignment_tol)
        | (height - v <= top + assignment_tol)
    )
    if not np.all(in_area):
        return (
            "At least one reinforcement element lies outside the validated "
            "direct-tension effective perimeter area."
        )
    return in_area, ac_eff, max(bottom, top), max(left, right)


def _crack_width(
    section: Section,
    cracked_state: ElasticResult,
    n: float,
    fctm: float,
    Es: Union[float, Sequence[float]],
    cover: float,
    kt: float,
    k1: Union[float, Sequence[float]],
    k2: float,
    k3: float,
    k4: float,
    bar_diameter: Optional[Union[float, Sequence[float]]],
    k3_cover_dependent: bool = False,
    include_hx_term: bool = True,
    coarse: bool = False,
    edition: str = "2004",
    n_mult: Optional[np.ndarray] = None,
    reinforcement_types: Optional[Sequence[str]] = None,
    bond_ratio_xi: Optional[Union[float, Sequence[float]]] = None,
) -> CrackWidthEvaluation:
    """Evaluate EC2 crack width and retain an explicit scope disposition.

    ``fctm`` and ``Es`` are in MPa. ``bar_diameter`` (mm) can be one override for
    every element or one value per element; otherwise diameter follows area.
    ``cover`` (mm), when given, is used for every
    bar; when ``None`` each bar's clear cover is taken from the geometry as the
    distance to the nearest concrete face minus half its diameter. The effective
    tension area, height and reinforcement ratio are section quantities (defined
    for the bending direction); the crack spacing and mean strain are then formed
    per bar (its own cover, diameter and Stage II stress); candidates are sorted by
    ``wk`` and the largest governs. Unsupported or incomplete inputs return a
    blocking ``NOT ASSESSED`` disposition instead of silently omitting a result.

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
    bx, by, ba = section.bar_arrays()
    if not bx.size:
        return _not_assessed(
            "The cracked section has no reinforcement; crack width is not assessed."
        )
    try:
        es_arr = np.broadcast_to(np.asarray(Es, dtype=float), (bx.size,))
        mult_arr = (
            np.ones(bx.size)
            if n_mult is None
            else np.broadcast_to(np.asarray(n_mult, dtype=float), (bx.size,))
        )
        kinds = _reinforcement_type_array(reinforcement_types, bx.size)
    except (TypeError, ValueError) as exc:
        return _not_assessed(f"Crack-width reinforcement inputs are invalid: {exc}.")
    if np.any(~np.isfinite(es_arr)) or np.any(es_arr <= 0.0):
        return _not_assessed(
            "Every crack-control reinforcement modulus must be finite and positive."
        )
    sigma = np.asarray(cracked_state.bar_stress, dtype=float) / _KPA_PER_MPA
    if sigma.shape != (bx.size,) or np.any(~np.isfinite(sigma)):
        return _not_assessed(
            "The cracked-state reinforcement stress array is invalid."
        )
    if float(sigma.max()) <= 0.0:
        return _not_applicable(
            "The load state has no reinforcement in tension, so no crack "
            "opening is applicable."
        )

    derived_phi = np.sqrt(4.0 * ba * 1.0e6 / math.pi)
    if bar_diameter is None:
        phi_arr = derived_phi
    else:
        try:
            supplied_phi = np.broadcast_to(
                np.asarray(bar_diameter, dtype=float), (bx.size,),
            )
        except (TypeError, ValueError) as exc:
            return _not_assessed(
                f"Crack-width element diameters are invalid: {exc}."
            )
        phi_arr = np.where(
            np.isfinite(supplied_phi) & (supplied_phi > 0.0),
            supplied_phi,
            derived_phi,
        )

    if edition == "2023":
        return _crack_width_2023(
            section, cracked_state, n, fctm, es_arr, cover, kt,
            k1, phi_arr, n_mult=mult_arr,
            reinforcement_types=kinds, bond_ratio_xi=bond_ratio_xi,
        )

    all_tension, near_uniform = _uniform_tension_regime(section, cracked_state)
    if all_tension:
        return _not_assessed(
            "Uniform/direct tension is outside the validated 2005 crack-width "
            "branch; select the 2023 direct-tension method or provide a separate "
            "project-basis assessment."
        )
    if near_uniform:
        return _not_assessed(
            "The strain gradient is too small to establish the 2005 bending "
            "effective area, but the section is not in validated uniform tension."
        )
    gx, gy, mag = _depth_axis(cracked_state.kx, cracked_state.ky)
    if mag == 0.0:
        return _not_assessed(
            "No usable bending gradient is available for the 2005 crack-width method."
        )

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
        return _not_assessed(
            "The 2005 effective tension area is not positive."
        )

    # Reinforcement inside the effective band sets the (shared) ratio rho_p,eff.
    in_band = s_bars >= c_lo
    as_eff = float(ba[in_band].sum())
    if as_eff <= 0.0:
        return _not_assessed(
            "No reinforcement lies inside the 2005 effective tension area."
        )
    rho = as_eff / ac_eff
    # k1 (bond) may be a scalar (all reinforcement) or one value per bar -- e.g.
    # the mild-steel value for ordinary bars and 1.6 for prestressing tendons.
    k1_arr = np.broadcast_to(np.asarray(k1, dtype=float), (bx.size,))
    mild_area = float(ba[in_band & (kinds == "mild")].sum())
    prestress_area = float(ba[in_band & (kinds == "prestress")].sum())
    direction_deg = math.degrees(math.atan2(gy, gx)) % 180.0

    # Per-bar crack width: each tension bar in the band uses its own cover,
    # diameter and Stage II stress; the largest wk governs.
    wk_factor = 0.5 if coarse else 1.0   # DK NA coarse system halves wk (7.3.4(1))
    band_tens = in_band & (sigma > 0.0)  # tension bars that set the crack spacing
    candidates: list[CrackWidthCandidate] = []
    for i in range(bx.size):
        if not in_band[i] or sigma[i] <= 0.0:
            continue
        sigma_s = float(sigma[i])
        es_i = float(es_arr[i])
        alpha_e_i = float(n) * float(mult_arr[i])
        phi = float(phi_arr[i])
        if cover is not None:
            c_i = float(cover)
        else:
            # Clear cover to the bar surface = distance to the nearest concrete
            # face (m -> mm) minus the bar radius.
            c_i = max(distance_to_boundary(float(bx[i]), float(by[i]), rings)
                      * 1000.0 - phi / 2.0, 0.0)
        # EC2 (7.9): mean strain, with the 0.6 sigma_s/Es lower bound.
        esm_ecm = max(
            (sigma_s - kt * fctm / rho * (1.0 + alpha_e_i * rho)) / es_i,
            0.6 * sigma_s / es_i,
        )
        # EC2 (7.11): maximum crack spacing (cover and phi in mm). Under the DK NA
        # (7.3.4(3)) the cover term coefficient is k3*(25/c)^(2/3) instead of k3.
        k3_i = k3 * (25.0 / c_i) ** (2.0 / 3.0) if k3_cover_dependent and c_i > 0.0 else k3
        # EC2 (7.11) applies where the bonded bars are fixed at close centres, i.e.
        # the spacing does not exceed 5(c+phi/2) (7.3.4(3)); otherwise (7.14) gives
        # the crack spacing directly as the geometric estimate 1.3*(h-x). Select the
        # branch per bar from its nearest in-band tension neighbour along the width
        # axis, so a closely spaced but shallow tension zone (bending with axial
        # compression -> small h-x) keeps its real (7.11) spacing, while a wide or
        # isolated bar takes (7.14) as the assigned value -- not merely a cap, so it
        # is used even where (7.11) would be smaller (high rho / deep tension zone).
        # A lone bar (no neighbour) counts as wide. (h-x) = s_tface - s_na; widths in
        # m, cover/phi in mm.
        neigh = band_tens.copy()
        neigh[i] = False
        nn = float(np.min(np.abs(w_bars[neigh] - w_bars[i]))) if neigh.any() else math.inf
        geometric = nn * 1000.0 > 5.0 * (c_i + phi / 2.0)
        if geometric:
            sr_max = 1.3 * (s_tface - s_na) * 1000.0                       # (7.14)
        else:
            sr_max = k3_i * c_i + float(k1_arr[i]) * k2 * k4 * phi / rho    # (7.11)
        wk = wk_factor * sr_max * esm_ecm
        candidates.append(CrackWidthCandidate(
            bar_index=i, x=float(bx[i]), y=float(by[i]),
            area=float(ba[i]) * 1.0e6,
            wk=wk, sr_max=sr_max, esm_ecm=esm_ecm, sigma_s=sigma_s,
            rho_p_eff=rho, ac_eff=ac_eff, hc_ef=hc_ef, phi=phi, cover=c_i,
            coarse=coarse, sr_max_geometric=geometric,
            as_eff=mild_area, ap_eff=prestress_area,
            ap_eff_weighted=prestress_area,
            reinforcement_type=str(kinds[i]),
            scope=CRACK_SCOPE_DOMINANT_DIRECTION,
            direction_deg=direction_deg,
        ))
    result = _governing_crack(candidates)
    if result is None:
        return _not_assessed(
            "No tension reinforcement candidate remains in the effective area."
        )
    return _calculated(result)


_KW_2023 = 1.7   # EN 1992-1-1:2023 (9.8) NOTE 1: mean -> calculated crack width


def _crack_width_2023_direct(
    section: Section,
    sigma: np.ndarray,
    n: float,
    fctm: float,
    es_arr: np.ndarray,
    cover: Optional[float],
    kt: float,
    k1_arr: np.ndarray,
    phi_arr: np.ndarray,
    mult_arr: np.ndarray,
    kinds: np.ndarray,
    bond_ratio_xi: Optional[Union[float, Sequence[float]]],
) -> CrackWidthEvaluation:
    """Uniform direct-tension implementation of 9.2.3 and Figure 9.3."""

    bx, by, ba = section.bar_arrays()
    effective = _direct_tension_effective_area_2023(section, phi_arr)
    if isinstance(effective, str):
        return _not_assessed(effective)
    in_area, ac_eff, hc_ef, bc_ef = effective
    try:
        rho_info = effective_reinforcement_ratio_2023(
            ba,
            in_area,
            phi_arr,
            ac_eff_m2=ac_eff,
            reinforcement_types=kinds,
            bond_ratio_xi=bond_ratio_xi,
        )
    except ValueError as exc:
        return _not_assessed(f"2023 effective reinforcement ratio: {exc}.")

    rho = rho_info.rho_p_eff
    rings = list(section.integration_rings())
    candidates: list[CrackWidthCandidate] = []
    for i in range(bx.size):
        if not in_area[i] or sigma[i] <= 0.0:
            continue
        sigma_s = float(sigma[i])
        es_i = float(es_arr[i])
        alpha_e_i = float(n) * float(mult_arr[i])
        phi = float(phi_arr[i])
        if cover is not None:
            c_i = float(cover)
        else:
            c_i = max(
                distance_to_boundary(float(bx[i]), float(by[i]), rings)
                * 1000.0
                - phi / 2.0,
                0.0,
            )
        esm_ecm = max(
            (sigma_s - kt * fctm / rho * (1.0 + alpha_e_i * rho)) / es_i,
            (1.0 - kt) * sigma_s / es_i,
        )
        kb = 0.9 if float(k1_arr[i]) <= 1.0 else 1.2
        # Formula (9.20): kfl = 1.00 for pure tension. In the uniform-tension
        # limit k1/r = 1.00 and the (h-x) cap tends to infinity.
        sr = 1.5 * c_i + kb / 7.2 * phi / rho
        wk = _KW_2023 * sr * esm_ecm
        candidates.append(
            CrackWidthCandidate(
                bar_index=i,
                x=float(bx[i]),
                y=float(by[i]),
                area=float(ba[i]) * 1.0e6,
                wk=wk,
                sr_max=sr,
                esm_ecm=esm_ecm,
                sigma_s=sigma_s,
                rho_p_eff=rho,
                ac_eff=ac_eff,
                hc_ef=hc_ef,
                phi=phi,
                cover=c_i,
                edition="2023",
                kw=_KW_2023,
                k1_r=1.0,
                kfl=1.0,
                as_eff=rho_info.as_eff,
                ap_eff=rho_info.ap_eff,
                ap_eff_weighted=rho_info.ap_eff_weighted,
                xi1=rho_info.xi1_by_element[i],
                reinforcement_type=str(kinds[i]),
                bc_ef=bc_ef,
                direct_tension=True,
                scope=CRACK_SCOPE_DIRECT_TENSION,
            )
        )
    result = _governing_crack(
        candidates,
        [
            value
            for index, value in enumerate(rho_info.xi1_by_element)
            if in_area[index] and value is not None
        ],
    )
    if result is None:
        return _not_assessed(
            "No tension reinforcement candidate remains in the direct-tension "
            "effective area."
        )
    return _calculated(result)


def _crack_width_2023(
    section: Section,
    cracked_state: ElasticResult,
    n: float,
    fctm: float,
    Es: np.ndarray,
    cover: Optional[float],
    kt: float,
    k1: Union[float, Sequence[float]],
    bar_diameter: np.ndarray,
    n_mult: np.ndarray,
    *,
    reinforcement_types: np.ndarray,
    bond_ratio_xi: Optional[Union[float, Sequence[float]]],
) -> CrackWidthEvaluation:
    """EN 1992-1-1:2023 refined crack width (9.2.3), per bar, largest-wk governs.

    Implements the bending case of Formula (9.8)::

        wk,cal = kw * k1/r * sr,m,cal * (eps_sm - eps_cm)

    with ``kw = 1.7`` (9.8 NOTE 1); the per-bar curvature factor ``k1/r`` (9.9); the
    mean crack spacing ``sr,m,cal`` (9.15) with the flexural coefficient ``kfl``
    (9.17) and bond factor ``kb`` (9.18); the effective height ``hc,eff`` (figure
    9.3); Formula (9.12), including the ``xi1``-weighted prestressing term; and
    the mean strain (9.11). Uniform direct tension is routed to the separately
    validated Figure 9.3 perimeter-area branch.
    """
    bx, by, ba = section.bar_arrays()
    sigma = np.asarray(cracked_state.bar_stress, dtype=float) / _KPA_PER_MPA
    es_arr = np.asarray(Es, dtype=float)
    mult_arr = np.asarray(n_mult, dtype=float)
    phi_arr = np.asarray(bar_diameter, dtype=float)
    kinds = np.asarray(reinforcement_types, dtype=object)
    try:
        k1_arr = np.broadcast_to(np.asarray(k1, dtype=float), (bx.size,))
    except (TypeError, ValueError) as exc:
        return _not_assessed(f"Crack-width bond-condition inputs are invalid: {exc}.")
    if np.any(~np.isfinite(k1_arr)) or np.any(k1_arr <= 0.0):
        return _not_assessed(
            "Every crack-width bond-condition coefficient must be finite and positive."
        )

    all_tension, near_uniform = _uniform_tension_regime(section, cracked_state)
    if all_tension and near_uniform:
        return _crack_width_2023_direct(
            section,
            sigma,
            n,
            fctm,
            es_arr,
            cover,
            kt,
            k1_arr,
            phi_arr,
            mult_arr,
            kinds,
            bond_ratio_xi,
        )
    if all_tension:
        return _not_assessed(
            "The entire section is in tension but the strain gradient is not "
            "uniform. The validated direct-tension branch does not cover this "
            "combined tension-and-bending state."
        )
    if near_uniform:
        return _not_assessed(
            "The near-zero strain gradient is a transition state that is neither "
            "validated uniform direct tension nor a stable bending effective area."
        )

    gx, gy, mag = _depth_axis(cracked_state.kx, cracked_state.ky)
    if mag == 0.0:
        return _not_assessed(
            "No usable strain-gradient direction is available for crack width."
        )

    verts = section.concrete_vertices()
    s_vert = verts[:, 0] * gx + verts[:, 1] * gy
    s_tface = float(s_vert.max())
    s_cface = float(s_vert.min())
    h = s_tface - s_cface
    s_na = -cracked_state.eps0 / mag
    hx = s_tface - s_na                 # (h - x): tension-zone depth at the cracked NA
    if hx <= 0.0:
        return _not_assessed(
            "The 2023 bending tension-zone depth (h - x) is not positive."
        )
    s_bars = bx * gx + by * gy
    ay = s_tface - s_bars               # distance from the tension face to each bar (m)
    # Effective layers: bars that are in tension (Stage II stress) AND geometrically
    # below the neutral axis. An externally supplied combined-creep state can leave a
    # bar above the NA with a small positive residual stress; the per-bar loop skips
    # it (denom <= 0), so it must not expand hc,eff / dilute rho_p,eff either.
    tens = (sigma > 0.0) & (ay < hx)
    if not tens.any():
        return _not_assessed(
            "No tension reinforcement lies below the cracked neutral axis."
        )

    def _phi(i):
        return float(phi_arr[i])

    # hc,eff (figure 9.3, bending): the single-layer band min{ay+5phi, 10phi, 3.5ay}
    # (phi in mm -> m) is built from the reinforcement nearest the tension face, then
    # extended by the depth spread of the tension bars so a section reinforced in
    # several layers is covered -- the general form of the n-layer +(n-1)*sy term
    # (which is zero for a single layer). The result is capped at h-x and h/2. The
    # phi terms use the NEAR-FACE layer's diameter (the ay used), not the governing-
    # stress bar's, so mixed bar sizes / external stress states pick the right bar.
    near = int(np.where(tens, ay, np.inf).argmin())   # tension bar nearest the face
    phi_near_m = _phi(near) / 1000.0
    ay_near = float(ay[near])                    # near-face layer depth
    ay_far = float(ay[tens].max())              # deepest tension bars
    base = min(ay_near + 5.0 * phi_near_m, 10.0 * phi_near_m, 3.5 * ay_near)
    hc_ef = min(base + (ay_far - ay_near), hx, h / 2.0)
    if hc_ef <= 0.0:
        return _not_assessed(
            "The 2023 bending effective tension height is not positive."
        )
    c_lo = s_tface - hc_ef
    rings = list(section.integration_rings())
    ac_eff = sum(area_moments(clip_halfplane(r, gx, gy, -c_lo)).area for r in rings)
    if ac_eff <= 0.0:
        return _not_assessed(
            "The 2023 bending effective tension area is not positive."
        )
    in_band = s_bars >= c_lo
    try:
        rho_info = effective_reinforcement_ratio_2023(
            ba,
            in_band,
            phi_arr,
            ac_eff_m2=ac_eff,
            reinforcement_types=kinds,
            bond_ratio_xi=bond_ratio_xi,
        )
    except ValueError as exc:
        return _not_assessed(f"2023 effective reinforcement ratio: {exc}.")
    rho = rho_info.rho_p_eff

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

    sr_cap = 1.3 / _KW_2023 * hx * 1000.0   # (1.3/kw)*(h-x), m -> mm
    direction_deg = math.degrees(math.atan2(gy, gx)) % 180.0
    candidates: list[CrackWidthCandidate] = []
    for i in range(bx.size):
        if not in_band[i] or sigma[i] <= 0.0:
            continue
        denom = hx - float(ay[i])      # (h - x) - ay,i ; the bar must be below the NA
        if denom <= 1.0e-9:
            continue
        sigma_s = float(sigma[i])
        es_i = float(es_arr[i])
        alpha_e_i = float(n) * float(mult_arr[i])
        phi = _phi(i)
        if cover is not None:
            c_i = float(cover)
        else:
            c_i = max(distance_to_boundary(float(bx[i]), float(by[i]), rings)
                      * 1000.0 - phi / 2.0, 0.0)
        # (9.11): mean strain; lower bound (1 - kt)*sigma_s/Es (was a fixed 0.6 in 2004).
        esm_ecm = max(
            (sigma_s - kt * fctm / rho * (1.0 + alpha_e_i * rho)) / es_i,
            (1.0 - kt) * sigma_s / es_i,
        )
        # (9.18) bond factor: good bond (ribbed, k1<=1.0) -> 0.9, poor (plain) -> 1.2.
        kb = 0.9 if float(k1_arr[i]) <= 1.0 else 1.2
        # (9.15) mean crack spacing = 1.5c + (kfl*kb/7.2)*(phi/rho), capped at
        # (1.3/kw)*(h-x). Cover and phi in mm.
        sr = min(1.5 * c_i + kfl * kb / 7.2 * phi / rho, sr_cap)
        k1r = hx / denom               # (9.9) curvature factor, >= 1
        wk = _KW_2023 * k1r * sr * esm_ecm
        candidates.append(CrackWidthCandidate(
            bar_index=i, x=float(bx[i]), y=float(by[i]),
            area=float(ba[i]) * 1.0e6,
            wk=wk, sr_max=sr, esm_ecm=esm_ecm, sigma_s=sigma_s,
            rho_p_eff=rho, ac_eff=ac_eff, hc_ef=hc_ef, phi=phi, cover=c_i,
            edition="2023", kw=_KW_2023, k1_r=k1r, kfl=kfl,
            as_eff=rho_info.as_eff, ap_eff=rho_info.ap_eff,
            ap_eff_weighted=rho_info.ap_eff_weighted,
            xi1=rho_info.xi1_by_element[i],
            reinforcement_type=str(kinds[i]),
            scope=CRACK_SCOPE_DOMINANT_DIRECTION,
            direction_deg=direction_deg,
        ))
    result = _governing_crack(
        candidates,
        [
            value
            for index, value in enumerate(rho_info.xi1_by_element)
            if in_band[index] and value is not None
        ],
    )
    if result is None:
        return _not_assessed(
            "No tension reinforcement candidate remains in the 2023 effective area."
        )
    return _calculated(result)


def analyse_cracking(
    section: Section,
    P: float,
    Mx: float,
    My: float,
    n: float,
    *,
    fctm: float,
    Es: Union[float, Sequence[float]] = 200_000.0,
    beta: float = 1.0,
    kt: float = 0.6,
    cover: Optional[float] = None,
    bar_diameter: Optional[Union[float, Sequence[float]]] = None,
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
    reinforcement_types: Optional[Sequence[str]] = None,
    bond_ratio_xi: Optional[Union[float, Sequence[float]]] = None,
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
        Reinforcement modulus (MPa), either one value or one per element.
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
        One governing diameter (mm), or one diameter per element. Missing or
        non-positive entries default to the equivalent circular area diameter.
    k1, k2, k3, k4:
        EC2 crack-spacing coefficients (recommended values by default). ``k1``
        (the bond coefficient) may be a single value or one per bar -- e.g. the
        mild-steel value for ordinary bars and 1.6 for prestressing tendons.
    reinforcement_types, bond_ratio_xi:
        Per-element ``mild``/``prestress`` classification and the 2023 tendon
        bond-strength ratio ``xi`` used to derive ``xi1``. If no types are
        supplied, all elements remain mild reinforcement for compatibility.

    Returns
    -------
    CrackingResult
        Cracking decision, ``lambda_cr``, ``zeta``, the Stage I and Stage II
        solves, the mean tension-stiffened strain plane, and the crack width.
    """
    section.require_valid_geometry()
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

    evaluation = _not_applicable("The section is uncracked.")
    if cracked:
        evaluation = _crack_width(
            section, crk, n, fctm, Es, cover, kt, k1, k2, k3, k4, bar_diameter,
            k3_cover_dependent=k3_cover_dependent, include_hx_term=include_hx_term,
            coarse=coarse, edition=edition, n_mult=n_mult,
            reinforcement_types=reinforcement_types,
            bond_ratio_xi=bond_ratio_xi,
        )
    crack = evaluation.result

    return CrackingResult(
        cracked=cracked, lambda_cr=lam, sigma_ct=sigma_ct, fctm=fctm, zeta=zeta,
        uncracked=uncr, cracked_state=crk, eps0_m=eps0_m, kx_m=kx_m, ky_m=ky_m,
        crack=crack, crack_evaluation=evaluation,
    )


def combined_cracking(section, P_l, Mx_l, My_l, n_l, P_s, Mx_s, My_s, n_s, *,
                      fctm, n_mult=None, prestress_stress=None):
    """Cracking check under the combined creep (peak instantaneous) state.

    The peak uncracked concrete tension is the long-term action at the long-term
    modular ratio ``n_l`` superposed with the short-term action at the short-term
    ratio ``n_s`` -- the effective-modulus treatment used by
    :func:`sector.elastic.solve_elastic_combined`, so the decision is consistent
    with the reported Total/RST1 stresses (rather than solving the raw summed load
    at a single ratio). Returns ``(cracked, lambda_cr, sigma_ct)``: ``sigma_ct`` is
    the peak concrete tension (MPa) and ``lambda_cr = f_ctm/sigma_ct`` (or the
    decompression factor with prestress), mirroring :func:`analyse_cracking`.
    """
    section.require_valid_geometry()
    verts = section.concrete_vertices()

    def _sig(P, Mx, My, n, pre):
        u = solve_elastic_uncracked(section, P, Mx, My, n, n_mult=n_mult,
                                    prestress_stress=pre)
        return (u.eps0 + u.kx * verts[:, 0] + u.ky * verts[:, 1]) / _KPA_PER_MPA

    sig_l = _sig(P_l, Mx_l, My_l, n_l, prestress_stress)   # long total (ext + prestress)
    sig_s = _sig(P_s, Mx_s, My_s, n_s, None)               # short external increment
    sigma_ct = float((sig_l + sig_s).max())                # peak tension, MPa
    if prestress_stress is None:
        lam = cracking_factor(sigma_ct, fctm)
    else:
        # Decompression: only the external actions are factored (the prestress is a
        # fixed permanent action). Matches analyse_cracking's prestress branch, with
        # the external part taken as long@n_l + short@n_s.
        sig_l_ext = _sig(P_l, Mx_l, My_l, n_l, None)
        sig_pre = sig_l - sig_l_ext                        # prestress alone
        sig_ext = sig_l_ext + sig_s                        # total external
        loaded = sig_ext > 1.0e-9
        lam = (float(np.min((fctm - sig_pre[loaded]) / sig_ext[loaded]))
               if np.any(loaded) else math.inf)
    cracked = lam < 1.0
    lam = max(0.0, lam) if math.isfinite(lam) else lam
    return cracked, lam, sigma_ct


def evaluate_crack_width(
    section: Section,
    cracked_state: ElasticResult,
    n: float,
    *,
    fctm: float,
    Es: Union[float, Sequence[float]] = 200_000.0,
    kt: float = 0.6,
    cover: Optional[float] = None,
    bar_diameter: Optional[Union[float, Sequence[float]]] = None,
    k1: Union[float, Sequence[float]] = 0.8,
    k2: float = 0.5,
    k3: float = 3.4,
    k4: float = 0.425,
    k3_cover_dependent: bool = False,
    include_hx_term: bool = True,
    coarse: bool = False,
    edition: str = "2004",
    n_mult: Optional[np.ndarray] = None,
    reinforcement_types: Optional[Sequence[str]] = None,
    bond_ratio_xi: Optional[Union[float, Sequence[float]]] = None,
) -> CrackWidthEvaluation:
    """Evaluate crack width for an externally supplied cracked-section state.

    Unlike :func:`analyse_cracking`, the cracked state is given rather than solved
    here, so it can carry a steel stress that is not a single linear solve -- e.g.
    the instantaneous (short-term) state of the combined creep analysis, whose
    bar stress is ``s2 + RST1``. ``cracked_state`` supplies the neutral axis /
    strain gradient and the per-bar steel stress; the bar with the largest ``wk``
    governs. See :func:`analyse_cracking` for the remaining parameters.
    """
    section.require_valid_geometry()
    return _crack_width(section, cracked_state, n, fctm, Es, cover, kt,
                        k1, k2, k3, k4, bar_diameter,
                        k3_cover_dependent=k3_cover_dependent,
                        include_hx_term=include_hx_term, coarse=coarse,
                        edition=edition, n_mult=n_mult,
                        reinforcement_types=reinforcement_types,
                        bond_ratio_xi=bond_ratio_xi)


def crack_width(
    section: Section,
    cracked_state: ElasticResult,
    n: float,
    *,
    fctm: float,
    Es: Union[float, Sequence[float]] = 200_000.0,
    kt: float = 0.6,
    cover: Optional[float] = None,
    bar_diameter: Optional[Union[float, Sequence[float]]] = None,
    k1: Union[float, Sequence[float]] = 0.8,
    k2: float = 0.5,
    k3: float = 3.4,
    k4: float = 0.425,
    k3_cover_dependent: bool = False,
    include_hx_term: bool = True,
    coarse: bool = False,
    edition: str = "2004",
    n_mult: Optional[np.ndarray] = None,
    reinforcement_types: Optional[Sequence[str]] = None,
    bond_ratio_xi: Optional[Union[float, Sequence[float]]] = None,
) -> Optional[CrackWidthResult]:
    """Compatibility wrapper returning only the numerical crack-width result."""

    return evaluate_crack_width(
        section,
        cracked_state,
        n,
        fctm=fctm,
        Es=Es,
        kt=kt,
        cover=cover,
        bar_diameter=bar_diameter,
        k1=k1,
        k2=k2,
        k3=k3,
        k4=k4,
        k3_cover_dependent=k3_cover_dependent,
        include_hx_term=include_hx_term,
        coarse=coarse,
        edition=edition,
        n_mult=n_mult,
        reinforcement_types=reinforcement_types,
        bond_ratio_xi=bond_ratio_xi,
    ).result
