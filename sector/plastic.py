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
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from . import kernels
from .geometry import _clip_pts, _poly_moments
from .materials import Concrete, MildSteel, Prestress
from .section import Section, finite_action

_MN_TO_KN = 1000.0

# The interactive product exposes increments down to one degree, while focused
# engineering references also use 0.1 degree resolution.  A 4,097-point ceiling
# retains those references (including one extra interval when strict represented
# gaps require it), but rejects hostile/unusable requests before allocating an
# angle tuple or entering the solver.
PLASTIC_SWEEP_MAX_POINTS = 4_097
_FULL_TURN_DEGREES = 360

# Use the compiled concrete integrator when Numba is available; otherwise fall
# back to the pure-Python band loop below (correct, just slower).
_USE_KERNEL = kernels.HAS_NUMBA


@dataclass(frozen=True, slots=True)
class PlasticConcreteCornerState:
    """Material response at one concrete vertex of the accepted strain plane.

    ``section_strain`` follows the plastic solver's compression-positive
    convention. ``material_strain`` and ``material_stress`` are the exact
    tension-positive arguments and result of :meth:`Concrete.stress`.
    ``ring_index`` and ``point_index`` are zero-based and preserve input order.
    """

    ring_index: int
    point_index: int
    x: float
    y: float
    section_strain: float
    material_strain: float
    material_stress: float


@dataclass(frozen=True, slots=True)
class PlasticReinforcementState:
    """One bar or tendon contribution at the accepted strain plane.

    ``section_strain`` is compression-positive. ``initial_strain``,
    ``material_strain`` and ``material_stress`` use the material law's
    tension-positive convention. Force and moments use the plastic solver's
    compression-positive resultant convention, so their sums reproduce the
    corresponding fields on :class:`PlasticPoint` without a report-side solve.
    ``element_index`` is zero-based within its bar or tendon family.
    """

    element_index: int
    x: float
    y: float
    area: float
    section_strain: float
    initial_strain: float
    material_strain: float
    material_stress: float
    force: float
    mx: float
    my: float


@dataclass(frozen=True, slots=True)
class PlasticCurvatureCandidate:
    """One existing ultimate-strain limit at the accepted compression depth.

    ``strain_limit`` is the exact effective numerator used by the solver. For a
    reinforcement rupture candidate it therefore includes the existing tiny
    intact-state back-off; for a tendon it is the backed-off remaining strain
    after initial prestrain. ``curvature = strain_limit / distance_from_na``.
    """

    mode: str
    element_index: int | None
    strain_limit: float
    distance_from_na: float
    curvature: float


@dataclass(frozen=True, slots=True)
class PlasticCurvatureSelection:
    """Candidate minimum and governing identity for the accepted strain plane."""

    candidates: tuple[PlasticCurvatureCandidate, ...]
    selected_mode: str
    selected_element_index: int | None
    selected_curvature: float


@dataclass(frozen=True, slots=True)
class PlasticAccumulation:
    """Authoritative material and sign-split resultants at one strain plane."""

    concrete_force: float
    concrete_mx: float
    concrete_my: float
    bar_force: float
    bar_mx: float
    bar_my: float
    tendon_force: float
    tendon_mx: float
    tendon_my: float
    compression_force: float
    compression_mx: float
    compression_my: float
    tension_force: float
    tension_mx: float
    tension_my: float
    min_bar_strain: float
    max_bar_strain: float
    min_tendon_strain: float
    bar_states: tuple[PlasticReinforcementState, ...] = ()
    tendon_states: tuple[PlasticReinforcementState, ...] = ()

    @property
    def axial(self) -> float:
        return self.compression_force + self.tension_force

    @property
    def mx(self) -> float:
        return self.compression_mx + self.tension_mx

    @property
    def my(self) -> float:
        return self.compression_my + self.tension_my


@dataclass
class PlasticPoint:
    """Ultimate capacity at one neutral-axis angle."""

    V: float                  # neutral-axis angle from the Y axis, degrees
    Mx: float                 # capacity moment about X, kNm
    My: float                 # capacity moment about Y, kNm
    axial: float              # achieved net axial force N, kN (compression +)
    U: float                  # angle of the resultant load from the X axis, deg
    R: float                  # distance origin -> resultant load, m
    na_x_intercept: float     # neutral axis intercept with X axis, m
    na_y_intercept: float     # neutral axis intercept with Y axis, m
    eps_concrete: float       # extreme concrete strain, % (compression +)
    eps_steel: float          # extreme (most tensile) mild-steel strain, %
    eps_steel_comp: float     # extreme (most compressed) mild-steel strain, % (comp +)
    eps_cable: float          # extreme (most tensile) tendon strain, % (incl. IS)
    curvature: float          # 1/m
    # The compression force and lever arm are diagnostic. They match the handcalc
    # verification for mild-steel sections; with prestress the resultants are
    # split differently, so they can differ (the capacity and strains do not).
    compression_force: float  # total compression resultant, kN
    lever_arm: float          # internal lever arm L, m
    dx: float                 # Cartesian X component Lx of the lever arm, m
    dy: float                 # Cartesian Y component Ly of the lever arm, m
    converged: bool

    # Solver diagnostics are optional keyword-only tail state. ``None`` preserves
    # the legacy public construction contract; live finite solver results populate
    # the complete diagnostic set.
    axial_requested: float | None = field(default=None, kw_only=True, repr=False, compare=False)
    axial_residual: float | None = field(default=None, kw_only=True, repr=False, compare=False)
    axial_tolerance: float | None = field(default=None, kw_only=True, repr=False, compare=False)
    axial_reachable: bool | None = field(default=None, kw_only=True, repr=False, compare=False)
    compression_depth: float | None = field(default=None, kw_only=True, repr=False, compare=False)
    neutral_axis_offset: float | None = field(default=None, kw_only=True, repr=False, compare=False)
    strain_gradient_x: float | None = field(default=None, kw_only=True, repr=False, compare=False)
    strain_gradient_y: float | None = field(default=None, kw_only=True, repr=False, compare=False)
    strain_offset: float | None = field(default=None, kw_only=True, repr=False, compare=False)
    search_lower_depth: float | None = field(default=None, kw_only=True, repr=False, compare=False)
    search_upper_depth: float | None = field(default=None, kw_only=True, repr=False, compare=False)
    search_lower_axial: float | None = field(default=None, kw_only=True, repr=False, compare=False)
    search_upper_axial: float | None = field(default=None, kw_only=True, repr=False, compare=False)
    search_iterations: int | None = field(default=None, kw_only=True, repr=False, compare=False)
    concrete_force: float | None = field(default=None, kw_only=True, repr=False, compare=False)
    concrete_mx: float | None = field(default=None, kw_only=True, repr=False, compare=False)
    concrete_my: float | None = field(default=None, kw_only=True, repr=False, compare=False)
    bar_force: float | None = field(default=None, kw_only=True, repr=False, compare=False)
    bar_mx: float | None = field(default=None, kw_only=True, repr=False, compare=False)
    bar_my: float | None = field(default=None, kw_only=True, repr=False, compare=False)
    tendon_force: float | None = field(default=None, kw_only=True, repr=False, compare=False)
    tendon_mx: float | None = field(default=None, kw_only=True, repr=False, compare=False)
    tendon_my: float | None = field(default=None, kw_only=True, repr=False, compare=False)
    compression_mx: float | None = field(default=None, kw_only=True, repr=False, compare=False)
    compression_my: float | None = field(default=None, kw_only=True, repr=False, compare=False)
    tension_force: float | None = field(default=None, kw_only=True, repr=False, compare=False)
    tension_mx: float | None = field(default=None, kw_only=True, repr=False, compare=False)
    tension_my: float | None = field(default=None, kw_only=True, repr=False, compare=False)
    concrete_corner_states: tuple[PlasticConcreteCornerState, ...] | None = field(
        default=None, kw_only=True, repr=False, compare=False
    )
    bar_states: tuple[PlasticReinforcementState, ...] | None = field(
        default=None, kw_only=True, repr=False, compare=False
    )
    tendon_states: tuple[PlasticReinforcementState, ...] | None = field(
        default=None, kw_only=True, repr=False, compare=False
    )
    curvature_selection: PlasticCurvatureSelection | None = field(
        default=None, kw_only=True, repr=False, compare=False
    )


def _material_sequence(default, specific, count, label):
    """Return one material law per element while preserving the scalar API."""
    if specific is not None:
        laws = tuple(specific)
        if len(laws) != count:
            raise ValueError(f"need {count} {label} materials, got {len(laws)}")
        return laws
    if count == 0:
        return ()
    if default is None:
        raise ValueError(f"{label} material is required for {count} element(s)")
    return (default,) * count


def _curvature_at_depth(
    bar_materials: Sequence[MildSteel],
    tendon_materials: Sequence[Prestress],
    s_max: float,
    c: float,
    s_bars: np.ndarray,
    s_tendons: np.ndarray,
    eps_cu: float,
    *,
    retain_selection: bool,
) -> tuple[float, PlasticCurvatureSelection | None]:
    """Apply the sole ultimate-curvature minimum and optionally retain its rows."""

    s_na = s_max - c
    phi = eps_cu / c  # concrete-crushing limit
    selected_mode: str = "concrete_crushing"
    selected_element_index: int | None = None
    candidates: list[PlasticCurvatureCandidate] | None = (
        [PlasticCurvatureCandidate(selected_mode, None, eps_cu, c, phi)]
        if retain_selection else None
    )

    # When steel or a tendon governs it sits exactly at its rupture strain, where
    # it is still intact (carrying its rupture force). Back the limiting curvature
    # off by a negligible amount so floating-point rounding cannot tip the strain
    # a hair past rupture (which the material law would read as fractured, zero
    # force). The back-off is far larger than rounding yet physically negligible.
    intact = 1.0 - 1.0e-9

    for index, (s_bar, material) in enumerate(zip(s_bars, bar_materials)):
        if s_bar < s_na:
            strain_limit = intact * material.eut
            distance = s_na - float(s_bar)
            candidate = strain_limit / distance
            if candidates is not None:
                candidates.append(PlasticCurvatureCandidate(
                    "bar_tension_rupture", index, strain_limit, distance, candidate
                ))
            if candidate < phi:
                phi = candidate
                selected_mode = "bar_tension_rupture"
                selected_element_index = index
        # The rupture strain is symmetric, so a compression bar must not be driven
        # past eut either. This only bites when eut < the concrete crushing strain.
        if (
            material.active_in_compression
            and material.fyck > 0.0
            and s_bar > s_na
        ):
            strain_limit = intact * material.eut
            distance = float(s_bar) - s_na
            candidate = strain_limit / distance
            if candidates is not None:
                candidates.append(PlasticCurvatureCandidate(
                    "bar_compression_rupture",
                    index,
                    strain_limit,
                    distance,
                    candidate,
                ))
            if candidate < phi:
                phi = candidate
                selected_mode = "bar_compression_rupture"
                selected_element_index = index

    for index, (s_tendon, material) in enumerate(zip(s_tendons, tendon_materials)):
        margin = material.rupture_strain - material.IS
        if s_tendon < s_na and margin > 0.0:
            strain_limit = intact * margin
            distance = s_na - float(s_tendon)
            candidate = strain_limit / distance
            if candidates is not None:
                candidates.append(PlasticCurvatureCandidate(
                    "tendon_tension_rupture", index, strain_limit, distance, candidate
                ))
            if candidate < phi:
                phi = candidate
                selected_mode = "tendon_tension_rupture"
                selected_element_index = index

    if candidates is None:
        return phi, None
    return phi, PlasticCurvatureSelection(
        candidates=tuple(candidates),
        selected_mode=selected_mode,
        selected_element_index=selected_element_index,
        selected_curvature=phi,
    )


def _governing_curvature(bar_materials, tendon_materials, s_max, c, s_bars,
                         s_tendons, eps_cu):
    """Curvature at ultimate for a trial compression depth ``c`` (s-units).

    The strain profile is scaled until the first material limit is reached:
    concrete crushing (extreme fibre at ``eps_cu``), mild-steel rupture (most
    tensile bar at its ``eut``), or tendon rupture (most tensile cable's total
    strain at its rupture strain). The governing curvature is the smallest of
    these, so no material is ever driven past its limit. ``s_bars`` / ``s_tendons``
    are the bar / tendon depth projections ``x*dx + y*dy`` precomputed once for the
    whole sweep (so the per-bisection-step extremes are just array reductions).
    """
    # Keep the former private-helper scalar call usable in verification tests.
    if isinstance(bar_materials, MildSteel):
        bar_materials = (bar_materials,) * len(s_bars)
    if isinstance(tendon_materials, Prestress):
        tendon_materials = (tendon_materials,) * len(s_tendons)
    phi, _ = _curvature_at_depth(
        bar_materials,
        tendon_materials or (),
        s_max,
        c,
        s_bars,
        s_tendons,
        eps_cu,
        retain_selection=False,
    )
    return phi


def _band_stresses(concrete, kappa, h, n_bands, memo=None):
    """Design concrete stresses at each ascending-band midpoint (MPa, comp +).

    Band ``i`` spans ``[s_na + i*h, s_na + (i+1)*h]``, so its midpoint strain is
    ``kappa*(i+0.5)*h`` -- the neutral-axis depth ``s_na`` cancels. The whole
    array is therefore a function of the single product ``kappa*h`` (for a fixed
    concrete + ``n_bands``). Across a neutral-axis sweep ``kappa*h`` is constant
    in the plateau-governed regime (``h = eps_c2/(kappa*n_bands)``), so an optional
    per-sweep ``memo`` -- a dict keyed on ``kappa*h`` -- collapses thousands of
    identical recomputations into one, at read-only cost (the kernel never mutates
    the returned array). Results are unchanged bar float rounding: forming the
    midpoint strain as ``kappa*h*(i+0.5)`` avoids the ``0.5*(sa+sb)-s_na``
    cancellation the reference used, so the two differ by ~1e-13 kNm on the moments.
    """
    kh = kappa * h
    if memo is not None:
        key = round(kh, 15)   # collapse float noise; genuine variation is >> 1e-15
        sig = memo.get(key)
        if sig is not None:
            return sig
        kh = key              # fill deterministically, so any call sharing this key
                              # (a neighbouring sweep angle, or a standalone solve)
                              # gets a bit-identical array, not a 1-ULP variant
    sig = np.empty(n_bands)
    for i in range(n_bands):
        sig[i] = -concrete.stress(-kh * (i + 0.5), design=True)
    if memo is not None:
        memo[key] = sig
    return sig


def _accumulate(concrete, bar_materials, tendon_materials, dx, dy, s_max, c, phi,
                n_bands,
                rings, bar_data, tendon_data, ring_xy=None, ring_starts=None,
                buf_a=None, buf_b=None, band_memo=None, *,
                retain_element_states=False) -> PlasticAccumulation:
    """Force resultants for a trial compression depth ``c`` (s-units).

    Returns the concrete, bar, and tendon force/Mx/My totals as well as the
    compression/tension split and extreme reinforcement strains. The neutral axis
    is at ``s = s_max - c`` and the curvature is ``phi``. ``rings`` are oriented
    concrete rings; ``bar_data`` / ``tendon_data`` are ``(x, y, area, s)`` arrays.

    When ``ring_xy`` (the stacked ring vertices) is supplied the concrete
    integration runs in the compiled kernel; otherwise it uses the pure-Python
    band loop. Both produce the same resultants.
    """
    s_na = s_max - c
    kappa = phi

    concrete_F = concrete_Fx = concrete_Fy = 0.0
    bar_F = bar_Fx = bar_Fy = 0.0
    tendon_F = tendon_Fx = tendon_Fy = 0.0
    comp_F = comp_Fx = comp_Fy = 0.0
    ten_F = ten_Fx = ten_Fy = 0.0
    bar_states: tuple[PlasticReinforcementState, ...] = ()
    tendon_states: tuple[PlasticReinforcementState, ...] = ()

    # -- concrete (always compression over the zone s > s_na) --
    fcd = concrete.fcd
    s_peak = s_na + concrete.eps_c2 / kappa  # strain reaches the peak plateau here
    s_top = min(s_peak, s_max)

    if ring_xy is not None:
        # Compiled path: precompute the band stresses, integrate in the kernel.
        if s_top > s_na and n_bands > 0:
            sig = _band_stresses(concrete, kappa, (s_top - s_na) / n_bands, n_bands,
                                 memo=band_memo)
        else:
            sig = np.empty(0)
        concrete_F, concrete_Fx, concrete_Fy = kernels.concrete_resultants(
            ring_xy, ring_starts, dx, dy, s_na, s_max, s_peak,
            sig.shape[0], fcd, sig, buf_a, buf_b)
    else:
        # Pure-Python path. Plateau band [s_peak, s_max]: constant strength.
        if s_peak < s_max:
            for ring in rings:
                m = _poly_moments(_clip_pts(ring, dx, dy, -s_peak))  # d.r >= s_peak
                concrete_F += fcd * m.area * _MN_TO_KN
                concrete_Fx += fcd * m.sx * _MN_TO_KN
                concrete_Fy += fcd * m.sy * _MN_TO_KN
        # Ascending band [s_na, s_top]: midpoint integration.
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
                    band = _clip_pts(_clip_pts(ring, dx, dy, -sa), -dx, -dy, sb)
                    m = _poly_moments(band)
                    concrete_F += sig * m.area * _MN_TO_KN
                    concrete_Fx += sig * m.sx * _MN_TO_KN
                    concrete_Fy += sig * m.sy * _MN_TO_KN

    comp_F += concrete_F
    comp_Fx += concrete_Fx
    comp_Fy += concrete_Fy

    # -- reinforcement (point areas, both signs) --
    bx, by, ba, s_bars = bar_data
    min_eps = max_eps = 0.0
    if bx.size:
        eps_b = kappa * (s_bars - s_na)                     # compression positive
        min_eps = float(eps_b.min())                        # most tensile bar strain
        max_eps = float(eps_b.max())                        # most compressed bar strain
        # The material law is a branchy scalar; evaluate it per bar, then form the
        # forces and split compression / tension with array reductions.
        sig_b = np.array([
            -material.stress(-e, design=True)
            for e, material in zip(eps_b, bar_materials)
        ])  # comp +, MPa
        fb = sig_b * ba * _MN_TO_KN                          # kN, comp +
        if retain_element_states:
            bar_states = tuple(
                PlasticReinforcementState(
                    element_index=index,
                    x=float(x),
                    y=float(y),
                    area=float(area),
                    section_strain=float(section_strain),
                    initial_strain=0.0,
                    material_strain=-float(section_strain),
                    material_stress=-float(stress),
                    force=float(force),
                    mx=float(force * y),
                    my=float(force * x),
                )
                for index, (x, y, area, section_strain, stress, force) in enumerate(
                    zip(bx, by, ba, eps_b, sig_b, fb)
                )
            )
        bar_F = float(fb.sum())
        bar_Fx = float((fb * bx).sum())
        bar_Fy = float((fb * by).sum())
        comp = fb >= 0.0
        comp_F += float(fb[comp].sum())
        comp_Fx += float((fb[comp] * bx[comp]).sum())
        comp_Fy += float((fb[comp] * by[comp]).sum())
        ten_F += float(fb[~comp].sum())
        ten_Fx += float((fb[~comp] * bx[~comp]).sum())
        ten_Fy += float((fb[~comp] * by[~comp]).sum())

    # -- prestressing tendons (tension only; stress at IS + section strain) --
    tx, ty, ta, s_tendons = tendon_data
    min_eps_cable = 0.0
    if tendon_materials and tx.size:
        eps_c = kappa * (s_tendons - s_na)                  # section, compression +
        e_total = np.array([
            material.IS - e
            for e, material in zip(eps_c, tendon_materials)
        ])                                                   # tension positive
        min_eps_cable = -float(e_total.max())                # compression-positive report
        sig_t = np.array([
            material.stress(e, design=True)
            for e, material in zip(e_total, tendon_materials)
        ])  # tension +, MPa
        ft = -sig_t * ta * _MN_TO_KN                        # tension -> negative (comp +)
        if retain_element_states:
            tendon_states = tuple(
                PlasticReinforcementState(
                    element_index=index,
                    x=float(x),
                    y=float(y),
                    area=float(area),
                    section_strain=float(section_strain),
                    initial_strain=float(material.IS),
                    material_strain=float(total_strain),
                    material_stress=float(stress),
                    force=float(force),
                    mx=float(force * y),
                    my=float(force * x),
                )
                for index, (
                    x,
                    y,
                    area,
                    section_strain,
                    total_strain,
                    stress,
                    force,
                    material,
                ) in enumerate(
                    zip(tx, ty, ta, eps_c, e_total, sig_t, ft, tendon_materials)
                )
            )
        tendon_F = float(ft.sum())
        tendon_Fx = float((ft * tx).sum())
        tendon_Fy = float((ft * ty).sum())
        comp = ft >= 0.0
        comp_F += float(ft[comp].sum())
        comp_Fx += float((ft[comp] * tx[comp]).sum())
        comp_Fy += float((ft[comp] * ty[comp]).sum())
        ten_F += float(ft[~comp].sum())
        ten_Fx += float((ft[~comp] * tx[~comp]).sum())
        ten_Fy += float((ft[~comp] * ty[~comp]).sum())

    return PlasticAccumulation(
        concrete_force=concrete_F,
        concrete_mx=concrete_Fy,
        concrete_my=concrete_Fx,
        bar_force=bar_F,
        bar_mx=bar_Fy,
        bar_my=bar_Fx,
        tendon_force=tendon_F,
        tendon_mx=tendon_Fy,
        tendon_my=tendon_Fx,
        compression_force=comp_F,
        compression_mx=comp_Fy,
        compression_my=comp_Fx,
        tension_force=ten_F,
        tension_mx=ten_Fy,
        tension_my=ten_Fx,
        min_bar_strain=min_eps,
        max_bar_strain=max_eps,
        min_tendon_strain=min_eps_cable,
        bar_states=bar_states,
        tendon_states=tendon_states,
    )


@dataclass
class _SectionPrep:
    """Angle-independent per-section arrays reused across a neutral-axis sweep."""

    bx: np.ndarray
    by: np.ndarray
    ba: np.ndarray
    tx: np.ndarray
    ty: np.ndarray
    ta: np.ndarray
    verts: np.ndarray
    rings: "list | None"
    ring_xy: "np.ndarray | None"
    ring_starts: "np.ndarray | None"
    buf_a: "np.ndarray | None"
    buf_b: "np.ndarray | None"


def _prep_section(section: Section, include_tendons: bool) -> _SectionPrep:
    """Build the angle-independent plastic-solver prep for ``section``.

    The oriented rings, the bar/tendon arrays, the concrete vertices and (on the
    compiled path) the stacked ring vertices plus clip scratch buffers do not depend
    on the neutral-axis angle. A sweep builds them once here and reuses them for
    every angle; only the depth projection ``s = x*dx + y*dy`` is re-formed per angle.
    The pure-Python ring point-lists are built only when the kernel is unavailable --
    the compiled path never reads them.
    """
    section.require_valid_analysis_inputs()
    int_rings = section.integration_rings()
    bx, by, ba = section.bar_arrays()
    if include_tendons:
        tx, ty, ta = section.tendon_arrays()
    else:
        _empty = np.empty(0)
        tx = ty = ta = _empty
    verts = section.concrete_vertices()
    if _USE_KERNEL:
        ring_xy = np.ascontiguousarray(np.vstack(int_rings), dtype=np.float64)
        ring_starts = np.zeros(len(int_rings) + 1, dtype=np.int64)
        for k, r in enumerate(int_rings):
            ring_starts[k + 1] = ring_starts[k] + len(r)
        cap = 4 * max(len(r) for r in int_rings) + 16  # generous clip headroom
        buf_a = np.empty((cap, 2))
        buf_b = np.empty((cap, 2))
        rings = None
    else:
        ring_xy = ring_starts = buf_a = buf_b = None
        rings = [r.tolist() for r in int_rings]
    return _SectionPrep(bx=bx, by=by, ba=ba, tx=tx, ty=ty, ta=ta, verts=verts,
                        rings=rings, ring_xy=ring_xy, ring_starts=ring_starts,
                        buf_a=buf_a, buf_b=buf_b)


def _accepted_concrete_corner_states(
    section: Section,
    concrete: Concrete,
    direction_x: float,
    direction_y: float,
    neutral_axis_offset: float,
    curvature: float,
) -> tuple[PlasticConcreteCornerState, ...]:
    """Evaluate each input-order concrete corner once at the accepted plane."""

    states: list[PlasticConcreteCornerState] = []
    for ring_index, ring in enumerate(section.concrete):
        for point_index, vertex in enumerate(ring):
            x, y = float(vertex[0]), float(vertex[1])
            section_strain = curvature * (
                x * direction_x + y * direction_y - neutral_axis_offset
            )
            material_strain = -section_strain
            states.append(PlasticConcreteCornerState(
                ring_index=ring_index,
                point_index=point_index,
                x=x,
                y=y,
                section_strain=section_strain,
                material_strain=material_strain,
                material_stress=concrete.stress(material_strain, design=True),
            ))
    return tuple(states)


def _accumulate_at_depth(
    section: Section,
    concrete: Concrete,
    steel: MildSteel,
    V_deg: float,
    compression_depth: float,
    curvature: float,
    *,
    prestress: "Prestress | None" = None,
    bar_materials: "Sequence[MildSteel] | None" = None,
    tendon_materials: "Sequence[Prestress] | None" = None,
    n_bands: int = 80,
    prep: "_SectionPrep | None" = None,
    band_memo: "dict | None" = None,
) -> PlasticAccumulation:
    """Re-accumulate one supplied strain plane through the solver's sole kernel."""

    angle = math.radians(V_deg)
    direction_x, direction_y = math.cos(angle), math.sin(angle)
    n_bar = len(section.bar_arrays()[2])
    n_tendon = len(section.tendon_arrays()[2])
    bar_laws = _material_sequence(steel, bar_materials, n_bar, "bar")
    tendon_laws = _material_sequence(
        prestress, tendon_materials, n_tendon, "tendon"
    ) if (prestress is not None or tendon_materials is not None) else ()
    if prep is None:
        prep = _prep_section(section, bool(tendon_laws))
    bx, by, ba = prep.bx, prep.by, prep.ba
    tx, ty, ta = prep.tx, prep.ty, prep.ta
    bar_data = (bx, by, ba, bx * direction_x + by * direction_y)
    tendon_data = (tx, ty, ta, tx * direction_x + ty * direction_y)
    projection = (
        prep.verts[:, 0] * direction_x + prep.verts[:, 1] * direction_y
    )
    return _accumulate(
        concrete,
        bar_laws,
        tendon_laws,
        direction_x,
        direction_y,
        float(projection.max()),
        compression_depth,
        curvature,
        n_bands,
        prep.rings,
        bar_data,
        tendon_data,
        prep.ring_xy,
        prep.ring_starts,
        prep.buf_a,
        prep.buf_b,
        {} if band_memo is None else band_memo,
    )


def plastic_capacity_at_angle(
    section: Section,
    concrete: Concrete,
    steel: MildSteel,
    P: float,
    V_deg: float,
    *,
    prestress: "Prestress | None" = None,
    bar_materials: "Sequence[MildSteel] | None" = None,
    tendon_materials: "Sequence[Prestress] | None" = None,
    n_bands: int = 80,
    max_iter: int = 100,
    prep: "_SectionPrep | None" = None,
    band_memo: "dict | None" = None,
) -> PlasticPoint:
    """Ultimate capacity for axial force ``P`` (kN) at neutral-axis angle ``V``.

    The strain profile is taken to its ultimate (the first material limit --
    concrete crushing or steel/tendon rupture -- governs the curvature) and the
    neutral-axis depth solved (by bisection) so the net axial force equals ``P``.
    Pass ``bar_materials`` / ``tendon_materials`` for element-specific laws. When
    omitted, the scalar ``steel`` / ``prestress`` law is repeated for every
    corresponding element, preserving the original API.
    """
    section.require_valid_analysis_inputs()
    P = finite_action(P, "axial force P")
    V_deg = finite_action(V_deg, "neutral-axis angle")
    V = math.radians(V_deg)
    dx, dy = math.cos(V), math.sin(V)

    # The oriented rings, reinforcement arrays and kernel scratch buffers do not
    # depend on the angle, so a sweep builds them once (``prep``) and passes them in;
    # a standalone call builds them here. Only the depth projection ``s = x*dx + y*dy``
    # changes with the angle, formed per angle below so the bisection just reduces it.
    n_bar = len(section.bar_arrays()[2])
    n_tendon = len(section.tendon_arrays()[2])
    bar_laws = _material_sequence(steel, bar_materials, n_bar, "bar")
    tendon_laws = _material_sequence(
        prestress, tendon_materials, n_tendon, "tendon"
    ) if (prestress is not None or tendon_materials is not None) else ()
    if prep is None:
        prep = _prep_section(section, bool(tendon_laws))
    bx, by, ba = prep.bx, prep.by, prep.ba
    tx, ty, ta = prep.tx, prep.ty, prep.ta
    bar_data = (bx, by, ba, bx * dx + by * dy)
    tendon_data = (tx, ty, ta, tx * dx + ty * dy)
    s_bars, s_tendons = bar_data[3], tendon_data[3]
    rings = prep.rings
    ring_xy, ring_starts = prep.ring_xy, prep.ring_starts
    buf_a, buf_b = prep.buf_a, prep.buf_b

    verts = prep.verts
    s = verts[:, 0] * dx + verts[:, 1] * dy
    s_max = float(s.max())
    s_min = float(s.min())
    c_full = s_max - s_min

    # Concrete band stresses depend only on kappa*h, which is constant across the
    # bisection (and the whole sweep) in the plateau-governed regime; a shared memo
    # -- passed in by a sweep, created here for a standalone call -- avoids repeating
    # that scalar band loop on every bisection step.
    if band_memo is None:
        band_memo = {}

    def net_axial(c):
        phi = _governing_curvature(bar_laws, tendon_laws, s_max, c, s_bars,
                                   s_tendons, concrete.eps_cu2)
        acc = _accumulate(concrete, bar_laws, tendon_laws, dx, dy, s_max, c, phi,
                          n_bands, rings, bar_data, tendon_data,
                          ring_xy, ring_starts, buf_a, buf_b, band_memo)
        return acc.axial

    # The governing-curvature formulation never drives a material past its limit,
    # so the net axial force increases monotonically with the compression depth c
    # and a plain bracket suffices.
    lo = 1.0e-9 * c_full
    n_lo = net_axial(lo)

    # Grow the upper bound past c_full so axial-compression states are reachable:
    # at c = c_full the neutral axis sits on the far fibre (section just fully
    # compressed); larger c pushes it beyond the section (whole section in
    # compression) up towards the squash load. Without this the compression side
    # of the N-M envelope would be clamped to the full-depth neutral axis. Net
    # axial increases monotonically with c throughout, so bisection still holds.
    hi = c_full
    n_hi = net_axial(hi)
    grow = 0
    while n_hi < P and grow < 80:
        hi *= 2.0
        n_hi = net_axial(hi)
        grow += 1

    # Residual tolerance alone cannot distinguish a genuine root from an endpoint
    # clamp: a request just outside the achievable range can lie within that
    # tolerance of the returned endpoint.  Keep reachability as explicit solver
    # state so only an in-range request can converge.  Equality deliberately counts
    # as reachable; the exact tension and compression endpoints are valid roots.
    axial_reachable = n_lo <= P <= n_hi
    search_lower_depth = lo
    search_upper_depth = hi
    search_lower_axial = n_lo
    search_upper_axial = n_hi
    search_iterations = 0

    if P < n_lo:
        c = lo              # requested axial below the pure-tension state (unreachable)
    elif P > n_hi:
        c = hi              # requested axial above the squash load (unreachable)
    else:
        for _ in range(max_iter):
            search_iterations += 1
            c = 0.5 * (lo + hi)
            if net_axial(c) < P:
                lo = c
            else:
                hi = c
            if hi - lo < 1.0e-12 * c_full:
                break
        c = 0.5 * (lo + hi)

    phi, curvature_selection = _curvature_at_depth(
        bar_laws,
        tendon_laws,
        s_max,
        c,
        s_bars,
        s_tendons,
        concrete.eps_cu2,
        retain_selection=True,
    )
    assert curvature_selection is not None
    accumulation = _accumulate(
        concrete, bar_laws, tendon_laws, dx, dy, s_max, c, phi, n_bands,
        rings, bar_data, tendon_data, ring_xy, ring_starts, buf_a, buf_b, band_memo,
        retain_element_states=True,
    )

    # A valid root must be reachable by the endpoint responses *and* satisfy axial
    # equilibrium.  The residual remains an independent guard for a failed search
    # or an unexpected monotonicity violation inside an otherwise valid bracket.
    axial_residual = accumulation.axial - P
    axial_tolerance = 1.0e-6 * max(1.0, abs(P))
    axial_residual_ok = abs(axial_residual) <= axial_tolerance
    converged = axial_reachable and axial_residual_ok

    Mx = accumulation.mx
    My = accumulation.my
    kappa = phi
    s_na = s_max - c
    concrete_corner_states = _accepted_concrete_corner_states(
        section,
        concrete,
        dx,
        dy,
        s_na,
        kappa,
    )
    eps_concrete = phi * c  # extreme concrete strain (<= eps_cu2; less if steel governs)

    # Resultant load position. R is signed (Mx = P*R*sin U, My = P*R*cos U), so a
    # tensile axial force (P < 0) gives a negative R.
    if abs(P) > 1.0e-9:
        R = math.hypot(Mx, My) / P
    else:
        R = 0.0
    U = math.degrees(math.atan2(Mx, My)) % 360.0

    # Neutral-axis intercepts (infinite when the axis is parallel to an axis).
    x_int = s_na / dx if abs(dx) > 1.0e-12 else math.inf
    y_int = s_na / dy if abs(dy) > 1.0e-12 else math.inf

    # Internal lever arm between the compression and tension resultants.
    if accumulation.compression_force != 0.0 and accumulation.tension_force != 0.0:
        cxc = accumulation.compression_my / accumulation.compression_force
        cyc = accumulation.compression_mx / accumulation.compression_force
        cxt = accumulation.tension_my / accumulation.tension_force
        cyt = accumulation.tension_mx / accumulation.tension_force
        lever_dx, lever_dy = cxc - cxt, cyc - cyt
        lever = math.hypot(lever_dx, lever_dy)
    else:
        lever_dx = lever_dy = lever = 0.0

    return PlasticPoint(
        V=V_deg,
        Mx=Mx,
        My=My,
        axial=accumulation.axial,
        U=U,
        R=R,
        na_x_intercept=x_int,
        na_y_intercept=y_int,
        eps_concrete=eps_concrete * 100.0,
        eps_steel=accumulation.min_bar_strain * 100.0,
        eps_steel_comp=accumulation.max_bar_strain * 100.0,
        eps_cable=accumulation.min_tendon_strain * 100.0,
        curvature=kappa,
        compression_force=accumulation.compression_force,
        lever_arm=lever,
        dx=lever_dx,
        dy=lever_dy,
        axial_requested=P,
        axial_residual=axial_residual,
        axial_tolerance=axial_tolerance,
        axial_reachable=axial_reachable,
        compression_depth=c,
        neutral_axis_offset=s_na,
        strain_gradient_x=kappa * dx,
        strain_gradient_y=kappa * dy,
        strain_offset=-kappa * s_na,
        search_lower_depth=search_lower_depth,
        search_upper_depth=search_upper_depth,
        search_lower_axial=search_lower_axial,
        search_upper_axial=search_upper_axial,
        search_iterations=search_iterations,
        concrete_force=accumulation.concrete_force,
        concrete_mx=accumulation.concrete_mx,
        concrete_my=accumulation.concrete_my,
        bar_force=accumulation.bar_force,
        bar_mx=accumulation.bar_mx,
        bar_my=accumulation.bar_my,
        tendon_force=accumulation.tendon_force,
        tendon_mx=accumulation.tendon_mx,
        tendon_my=accumulation.tendon_my,
        compression_mx=accumulation.compression_mx,
        compression_my=accumulation.compression_my,
        tension_force=accumulation.tension_force,
        tension_mx=accumulation.tension_mx,
        tension_my=accumulation.tension_my,
        concrete_corner_states=concrete_corner_states,
        bar_states=accumulation.bar_states,
        tendon_states=accumulation.tendon_states,
        curvature_selection=curvature_selection,
        converged=converged,
    )


class PlasticSweepResolutionError(ValueError):
    """A sweep cannot be represented safely at the requested resolution."""


class PlasticSweepSpanError(PlasticSweepResolutionError):
    """A sweep's finite endpoints have an unrepresentable separation."""


def plastic_sweep_is_full_turn(v_min: float, v_max: float) -> bool:
    """Return whether the represented endpoints are separated by exactly 360 deg.

    The comparison uses the exact rational values represented by both floats, so
    a partial endpoint immediately below a full turn is never absorbed by a
    tolerance intended for ordinary numerical calculations.
    """

    start = finite_action(v_min, "minimum neutral-axis angle")
    end = finite_action(v_max, "maximum neutral-axis angle")
    start_numerator, start_denominator = start.as_integer_ratio()
    end_numerator, end_denominator = end.as_integer_ratio()
    exact_span_numerator = (
        end_numerator * start_denominator
        - start_numerator * end_denominator
    )
    exact_span_denominator = end_denominator * start_denominator
    return exact_span_numerator == _FULL_TURN_DEGREES * exact_span_denominator


def plastic_sweep_angles(
    v_min: float,
    v_max: float,
    v_inc: float,
) -> tuple[float, ...]:
    """Return an inclusive neutral-axis sweep with ``v_inc`` as a maximum step.

    Both endpoints are retained.  When the requested maximum increment does not
    divide the span, the span is divided into the smallest whole number of equal
    intervals whose actual step does not exceed ``v_inc``.  A zero span therefore
    contains one angle.  Reversed bounds and non-positive increments are invalid.
    Requests above :data:`PLASTIC_SWEEP_MAX_POINTS`, or whose adjacent angles
    cannot be represented as distinct floats within the maximum step, fail before
    the tuple is allocated.
    """

    start = finite_action(v_min, "minimum neutral-axis angle")
    end = finite_action(v_max, "maximum neutral-axis angle")
    maximum_step = finite_action(v_inc, "neutral-axis angle increment")
    if end < start:
        raise ValueError(
            "maximum neutral-axis angle must be greater than or equal to the minimum"
        )
    if maximum_step <= 0.0:
        raise ValueError("neutral-axis angle increment must be positive")
    span = end - start
    if not math.isfinite(span):
        raise PlasticSweepSpanError(
            "neutral-axis angle span cannot be represented safely"
        )
    if span == 0.0:
        return (start,)

    ratio = span / maximum_step
    if not math.isfinite(ratio):
        raise PlasticSweepResolutionError(
            "neutral-axis angle increment is too small for the span"
        )
    intervals = max(1, math.ceil(ratio))
    if intervals + 1 > PLASTIC_SWEEP_MAX_POINTS:
        raise PlasticSweepResolutionError(
            "neutral-axis sweep requests too many angles; increase the maximum "
            "increment"
        )

    # Validate the represented angle sequence before allocating its tuple.  A
    # large coordinate offset can otherwise round adjacent requested angles to
    # the same float, followed by a terminal gap larger than ``maximum_step``.
    while True:
        actual_step = span / intervals
        previous = start
        gap_too_large = False
        for index in range(1, intervals + 1):
            current = end if index == intervals else start + index * actual_step
            if current <= previous:
                raise PlasticSweepResolutionError(
                    "neutral-axis sweep angles are not distinct at this numerical "
                    "scale; use a larger maximum increment or smaller angle values"
                )
            if current - previous > maximum_step:
                gap_too_large = True
                break
            previous = current
        if not gap_too_large:
            break
        intervals += 1
        if intervals + 1 > PLASTIC_SWEEP_MAX_POINTS:
            raise PlasticSweepResolutionError(
                "neutral-axis sweep requests too many angles; increase the maximum "
                "increment"
            )
    return tuple(
        start
        if index == 0
        else end
        if index == intervals
        else start + index * actual_step
        for index in range(intervals + 1)
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
    prestress: "Prestress | None" = None,
    bar_materials: "Sequence[MildSteel] | None" = None,
    tendon_materials: "Sequence[Prestress] | None" = None,
    n_bands: int = 80,
) -> list[PlasticPoint]:
    """Sweep the neutral-axis angle from ``v_min`` to ``v_max`` (inclusive).

    Returns one :class:`PlasticPoint` per angle, the biaxial capacity envelope
    for the axial force ``P``.
    """
    sweep_angles = plastic_sweep_angles(v_min, v_max, v_inc)
    section.require_valid_analysis_inputs()
    P = finite_action(P, "axial force P")
    n_bar = len(section.bar_arrays()[2])
    n_tendon = len(section.tendon_arrays()[2])
    bar_laws = _material_sequence(steel, bar_materials, n_bar, "bar")
    tendon_laws = _material_sequence(
        prestress, tendon_materials, n_tendon, "tendon"
    ) if (prestress is not None or tendon_materials is not None) else ()
    prep = _prep_section(section, bool(tendon_laws))   # angle-independent, built once
    band_memo: dict = {}                        # shared across all angles of the sweep
    points = []
    for v in sweep_angles:
        points.append(
            plastic_capacity_at_angle(section, concrete, steel, P, v,
                                      prestress=prestress,
                                      bar_materials=bar_laws,
                                      tendon_materials=tendon_laws or None,
                                      n_bands=n_bands, prep=prep,
                                      band_memo=band_memo)
        )
    return points


@dataclass
class InteractionPoint:
    """One point on the N-M interaction diagram at a fixed neutral-axis angle."""

    axial: float              # net axial force N, kN (compression +)
    Mx: float                 # capacity moment about X, kNm
    My: float                 # capacity moment about Y, kNm
    converged: bool


@dataclass(frozen=True, slots=True)
class ZeroMomentAxialCapacity:
    """One bounded pure-axial boundary solve about the section origin.

    ``axial`` follows the plastic solver convention (compression positive).  The
    evaluation count covers every ultimate-capacity point used by this solve and
    is retained so callers can prove that the axial-only check did not rebuild a
    complete neutral-axis sweep during an outer bisection.
    """

    axial: float | None
    converged: bool
    endpoint_axial: float | None
    neutral_axis_angle_deg: float | None
    moment_residual_knm: float | None
    moment_tolerance_knm: float | None
    point_evaluations: int
    iterations: int


def solve_zero_moment_axial_capacity(
    section: Section,
    concrete: Concrete,
    steel: MildSteel,
    *,
    tension: bool,
    prestress: "Prestress | None" = None,
    bar_materials: "Sequence[MildSteel] | None" = None,
    tendon_materials: "Sequence[Prestress] | None" = None,
    n_bands: int = 80,
    max_evaluations: int = 192,
    max_iterations: int = 18,
) -> ZeroMomentAxialCapacity:
    """Resolve the tension or compression boundary with ``Mx = My = 0``.

    The previous member-check path tested each axial bisection candidate by
    rebuilding a complete M-M sweep.  This dedicated two-variable solve instead
    reuses one prepared section and searches the ultimate surface directly in
    axial-force fraction and neutral-axis angle.  A strict point-evaluation
    ceiling and residual check make failure explicit.
    """

    if type(tension) is not bool:
        raise TypeError("tension must be a Boolean")
    if max_evaluations < 16:
        raise ValueError("max_evaluations must be at least 16")
    if max_iterations < 1:
        raise ValueError("max_iterations must be at least 1")

    section.require_valid_analysis_inputs()
    bx, by, ba = section.bar_arrays()
    tx, ty, ta = section.tendon_arrays()
    bar_laws = _material_sequence(steel, bar_materials, len(ba), "bar")
    tendon_laws = _material_sequence(
        prestress, tendon_materials, len(ta), "tendon"
    ) if (prestress is not None or tendon_materials is not None) else ()
    prep = _prep_section(section, bool(tendon_laws))
    band_memo: dict = {}
    evaluations = 0
    iterations = 0

    def _result(
        *,
        axial: float | None = None,
        converged: bool = False,
        endpoint: float | None = None,
        angle: float | None = None,
        residual: float | None = None,
        tolerance: float | None = None,
    ) -> ZeroMomentAxialCapacity:
        return ZeroMomentAxialCapacity(
            axial=axial,
            converged=converged,
            endpoint_axial=endpoint,
            neutral_axis_angle_deg=angle,
            moment_residual_knm=residual,
            moment_tolerance_knm=tolerance,
            point_evaluations=evaluations,
            iterations=iterations,
        )

    def _cap(axial: float, angle: float) -> PlasticPoint:
        nonlocal evaluations
        if evaluations >= max_evaluations:
            raise ArithmeticError("zero-moment axial evaluation limit reached")
        evaluations += 1
        return plastic_capacity_at_angle(
            section,
            concrete,
            steel,
            axial,
            angle % 360.0,
            prestress=prestress,
            bar_materials=bar_laws,
            tendon_materials=tendon_laws or None,
            n_bands=n_bands,
            prep=prep,
            band_memo=band_memo,
        )

    # Match the established interaction-boundary endpoint construction while
    # evaluating only the requested axial sign.  The deliberately unreachable
    # probe returns the clamped physical endpoint in ``point.axial``.
    area = sum(
        _poly_moments(ring.tolist()).area
        for ring in section.integration_rings()
    )
    steel_force = sum(
        max(
            abs(material.stress(material.eut * 0.99, design=True)),
            abs(material.stress(-material.eut * 0.99, design=True)),
        ) * reinforcement_area
        for material, reinforcement_area in zip(bar_laws, ba, strict=True)
    )
    steel_force += sum(
        abs(material.stress(material.rupture_strain * 0.99, design=True))
        * reinforcement_area
        for material, reinforcement_area in zip(
            tendon_laws, ta, strict=True
        )
    )
    probe = (
        -1.5 * steel_force * _MN_TO_KN - 1.0
        if tension
        else 1.5 * (concrete.fcd * area + steel_force) * _MN_TO_KN + 1.0
    )
    try:
        endpoint = float(_cap(probe, 0.0).axial)
    except (ArithmeticError, TypeError, ValueError, OverflowError):
        return _result()
    if (
        not math.isfinite(endpoint)
        or endpoint == 0.0
        or (tension and endpoint >= 0.0)
        or (not tension and endpoint <= 0.0)
    ):
        return _result(endpoint=endpoint if math.isfinite(endpoint) else None)

    extent_x = float(np.ptp(prep.verts[:, 0]))
    extent_y = float(np.ptp(prep.verts[:, 1]))
    lever_scale = max(extent_x, extent_y, 1.0e-3)
    moment_tolerance = max(
        1.0e-7,
        1.0e-8 * max(1.0, abs(endpoint) * lever_scale),
    )
    cache: dict[tuple[float, float], tuple[PlasticPoint, np.ndarray] | None] = {}

    def _evaluate(
        fraction: float,
        angle: float,
    ) -> tuple[PlasticPoint, np.ndarray] | None:
        fraction = min(1.0, max(1.0e-6, float(fraction)))
        angle = float(angle) % 360.0
        key = (round(fraction, 14), round(angle, 12))
        if key in cache:
            return cache[key]
        try:
            point = _cap(endpoint * fraction, angle)
        except (ArithmeticError, TypeError, ValueError, OverflowError):
            cache[key] = None
            return None
        values = np.asarray((point.Mx, point.My), dtype=float)
        if not point.converged or not np.all(np.isfinite(values)):
            cache[key] = None
            return None
        cache[key] = point, values
        return cache[key]

    candidates: list[tuple[float, float, float, PlasticPoint, np.ndarray]] = []
    # A modest deterministic seed grid makes the local solve insensitive to the
    # chosen coordinate origin without approaching a complete product sweep.
    for fraction in (1.0, 0.9, 0.75, 0.5, 0.25):
        for angle in range(0, 360, 45):
            evaluated = _evaluate(fraction, float(angle))
            if evaluated is None:
                continue
            point, residual = evaluated
            norm = float(np.linalg.norm(residual))
            candidates.append((norm, fraction, float(angle), point, residual))
            if norm <= moment_tolerance:
                return _result(
                    axial=point.axial,
                    converged=True,
                    endpoint=endpoint,
                    angle=point.V,
                    residual=norm,
                    tolerance=moment_tolerance,
                )

    if not candidates:
        return _result(endpoint=endpoint, tolerance=moment_tolerance)

    best = min(candidates, key=lambda item: item[0])
    # Use several distinct basins when the section is strongly asymmetric.  Each
    # local solve is still subject to the shared point-evaluation ceiling.
    seeds: list[tuple[float, float]] = []
    for _norm, fraction, angle, _point, _residual in sorted(candidates):
        if all(
            abs(fraction - old_fraction) > 0.05
            or abs(((angle - old_angle + 180.0) % 360.0) - 180.0) > 30.0
            for old_fraction, old_angle in seeds
        ):
            seeds.append((fraction, angle))
        if len(seeds) == 4:
            break

    for seed_fraction, seed_angle in seeds:
        fraction = seed_fraction
        angle = seed_angle
        evaluated = _evaluate(fraction, angle)
        if evaluated is None:
            continue
        point, residual = evaluated
        for _ in range(max_iterations):
            iterations += 1
            norm = float(np.linalg.norm(residual))
            if norm < best[0]:
                best = (norm, fraction, angle, point, residual)
            if norm <= moment_tolerance:
                return _result(
                    axial=point.axial,
                    converged=True,
                    endpoint=endpoint,
                    angle=point.V,
                    residual=norm,
                    tolerance=moment_tolerance,
                )

            fraction_step = max(1.0e-5, 1.0e-4 * fraction)
            angle_step = 0.05
            fraction_probe = (
                fraction - fraction_step
                if fraction + fraction_step > 1.0
                else fraction + fraction_step
            )
            fraction_eval = _evaluate(fraction_probe, angle)
            angle_eval = _evaluate(fraction, angle + angle_step)
            if fraction_eval is None or angle_eval is None:
                break
            fraction_delta = fraction_probe - fraction
            jacobian = np.column_stack((
                (fraction_eval[1] - residual) / fraction_delta,
                (angle_eval[1] - residual) / angle_step,
            ))
            try:
                step = np.linalg.lstsq(jacobian, -residual, rcond=None)[0]
            except np.linalg.LinAlgError:
                break
            if not np.all(np.isfinite(step)):
                break
            step[0] = float(np.clip(step[0], -0.20, 0.20))
            step[1] = float(np.clip(step[1], -30.0, 30.0))

            accepted = None
            for scale in (1.0, 0.5, 0.25, 0.125):
                next_fraction = min(
                    1.0, max(1.0e-6, fraction + scale * step[0])
                )
                next_angle = (angle + scale * step[1]) % 360.0
                if next_fraction == fraction and next_angle == angle:
                    continue
                trial = _evaluate(next_fraction, next_angle)
                if trial is None:
                    continue
                trial_norm = float(np.linalg.norm(trial[1]))
                if trial_norm < norm:
                    accepted = (
                        next_fraction,
                        next_angle,
                        trial[0],
                        trial[1],
                    )
                    break
            if accepted is None:
                break
            fraction, angle, point, residual = accepted

    return _result(
        axial=None,
        converged=False,
        endpoint=endpoint,
        angle=best[3].V,
        residual=best[0],
        tolerance=moment_tolerance,
    )


def solve_interaction(
    section: Section,
    concrete: Concrete,
    steel: MildSteel,
    V_deg: float,
    *,
    prestress: "Prestress | None" = None,
    bar_materials: "Sequence[MildSteel] | None" = None,
    tendon_materials: "Sequence[Prestress] | None" = None,
    n_points: int = 32,
    n_bands: int = 80,
) -> list[InteractionPoint]:
    """Trace the N-M interaction boundary at neutral-axis angle ``V_deg``.

    The ultimate axial capacity runs from pure tension (all steel yielding, ``N_t``)
    to the squash load (``N_c``). Sampling the axial force uniformly across
    ``[N_t, N_c]`` and taking the ultimate moment at each traces one boundary of the
    diagram -- the ``+M`` side for this ``V``; call again at ``V + 180`` for the
    ``-M`` side. Returns ``InteractionPoint``s ordered from tension to compression.
    """
    if n_points < 1:
        raise ValueError("n_points must be at least 1")

    section.require_valid_analysis_inputs()
    V_deg = finite_action(V_deg, "neutral-axis angle")
    bx, by, ba = section.bar_arrays()
    tx, ty, ta = section.tendon_arrays()
    bar_laws = _material_sequence(steel, bar_materials, len(ba), "bar")
    tendon_laws = _material_sequence(
        prestress, tendon_materials, len(ta), "tendon"
    ) if (prestress is not None or tendon_materials is not None) else ()
    prep = _prep_section(section, bool(tendon_laws))   # angle-independent, built once
    band_memo: dict = {}                        # shared across all axial samples
    def _cap(P):
        return plastic_capacity_at_angle(section, concrete, steel, P, V_deg,
                                         prestress=prestress,
                                         bar_materials=bar_laws,
                                         tendon_materials=tendon_laws or None,
                                         n_bands=n_bands, prep=prep,
                                         band_memo=band_memo)

    # Axial extremes: probe just past the range (a squash / tension over-estimate)
    # and read back the clamped equilibrium, so the diagram spans the true range. The
    # steel force uses each material's own design stress -- tendons yield far above the
    # mild bars, so folding their area in at the mild stress would leave the probe
    # inside the true tension range and the diagram short of the tension limit.
    Ac = sum(_poly_moments(r.tolist()).area for r in section.integration_rings())
    steel_force = sum(
        max(abs(material.stress(material.eut * 0.99, design=True)),
            abs(material.stress(-material.eut * 0.99, design=True))) * area
        for material, area in zip(bar_laws, ba)
    )
    steel_force += sum(
        abs(material.stress(material.rupture_strain * 0.99, design=True)) * area
        for material, area in zip(tendon_laws, ta)
    )
    squash = (concrete.fcd * Ac + steel_force) * _MN_TO_KN   # kN, an upper bound on N_c
    tension = steel_force * _MN_TO_KN                         # kN, |N_t| upper bound
    N_c = _cap(1.5 * squash + 1.0).axial
    N_t = _cap(-1.5 * tension - 1.0).axial

    pts = []
    for i in range(n_points + 1):
        # Retain the probed limits exactly at the inclusive endpoints. Rebuilding
        # N_c as N_t + (N_c - N_t) can round one ulp past the reachable squash
        # load, correctly causing the strict reachability guard to reject it.
        if i == 0:
            P = N_t
        elif i == n_points:
            P = N_c
        else:
            P = N_t + (N_c - N_t) * (i / n_points)
        p = _cap(P)
        pts.append(InteractionPoint(axial=p.axial, Mx=p.Mx, My=p.My,
                                    converged=p.converged))
    return pts


# Neutral-axis angle whose bending is purely about the given axis with the chosen
# face in tension (the solver's convention: V=90 -> +Mx, tension at the bottom;
# V=0 -> +My, tension on the left). Shared with the app's shear lever-arm and
# chord-capacity solves so every per-face solve uses the same angle.
FACE_ANGLE = {("x", True): 90.0, ("x", False): 270.0,
              ("y", True): 0.0, ("y", False): 180.0}


def conditional_capacity(
    section: Section,
    concrete: Concrete,
    steel: MildSteel,
    P: float,
    axis: str,
    tension_low: bool,
    m_off: float,
    *,
    own_moment_offset: float = 0.0,
    prestress: "Prestress | None" = None,
    bar_materials: "Sequence[MildSteel] | None" = None,
    tendon_materials: "Sequence[Prestress] | None" = None,
    n_bands: int = 80,
    n_scan: int = 36,
    tol_deg: float = 0.005,
) -> tuple[float, bool]:
    """Bending capacity about ``axis`` conditional on a coexisting off-axis moment.

    The pure-axis capacity overstates what a chord check can lean on under biaxial
    bending: the section cannot deliver its full uniaxial ``MRd`` while also
    carrying the acting moment about the other axis. This returns the capacity that
    IS available -- the point on the plastic M-M envelope, on the branch that
    tensions the chosen face, where the companion moment equals ``m_off`` (kNm,
    signed, in the solver's convention) -- as the magnitude of the moment about
    ``axis`` there. ``own_moment_offset`` translates that own-axis envelope moment
    to a declared section reference before branch selection and publication; the
    default preserves the solver's global-origin convention.

    The envelope is found by a full-circle neutral-axis scan (not a fixed
    quarter-turn bracket): every angle where the companion moment crosses ``m_off``
    is bracketed between adjacent scan samples and bisected, and the capacity is the
    outermost crossing whose OWN moment has the sign of the chosen tension face
    (``+`` for a low face, ``-`` for a high face). This makes no assumption that the
    companion is monotone or that its extremes sit at the pure-axis angle +/- 90 deg
    -- both false on a section asymmetric about the chord axis (unequal top/bottom
    steel, an L/T outline, an eccentric tendon), where the own moment can even take
    the wrong sign near an endpoint. Checking the own sign is what keeps the result
    conservative there: a crossing on the opposite face is not a capacity for this
    chord. The pure-axis angle is probed first, so a section symmetric about the
    chord axis under a uniaxial companion returns EXACTLY the pure-axis solve.

    Returns ``(mrd, exact)``. ``(value, True)`` is the conditional capacity;
    ``(0.0, True)`` is an honest zero -- the off-axis moment leaves no correct-face
    envelope point (it exhausts this chord's capacity). ``(0.0, False)`` means a
    solve failed to converge where a crossing could hide, so the caller should fall
    back to the pure-axis capacity.
    """
    section.require_valid_analysis_inputs()
    P = finite_action(P, "axial force P")
    m_off = finite_action(m_off, "coexisting bending moment")
    own_moment_offset = finite_action(
        own_moment_offset,
        "own-axis moment reference offset",
    )
    n_bar = len(section.bar_arrays()[2])
    n_tendon = len(section.tendon_arrays()[2])
    bar_laws = _material_sequence(steel, bar_materials, n_bar, "bar")
    tendon_laws = _material_sequence(
        prestress, tendon_materials, n_tendon, "tendon"
    ) if (prestress is not None or tendon_materials is not None) else ()
    v0 = FACE_ANGLE[(axis, tension_low)]
    prep = _prep_section(section, bool(tendon_laws))
    band_memo: dict = {}

    def _cap(v):
        return plastic_capacity_at_angle(section, concrete, steel, P, v,
                                         prestress=prestress,
                                         bar_materials=bar_laws,
                                         tendon_materials=tendon_laws or None,
                                         n_bands=n_bands,
                                         prep=prep, band_memo=band_memo)

    def _companion(pt):
        return pt.My if axis == "x" else pt.Mx

    def _own(pt):
        return pt.Mx if axis == "x" else pt.My

    def _face_own(pt):
        """Return the referenced own-moment magnitude on the selected face."""
        if not pt.converged:
            return None
        referenced = _own(pt) + own_moment_offset
        return (
            abs(referenced)
            if (
                (referenced > 0.0)
                if want_positive
                else (referenced < 0.0)
            )
            else None
        )

    target = m_off
    want_positive = tension_low        # the chosen face carries own of this sign

    # Pure-axis probe: if the companion there already equals the target (any
    # section symmetric about the chord axis under a uniaxial load), this IS the
    # answer -- the same solve at the same angle as the pure-axis capacity,
    # bit-identical to it.
    p0 = _cap(v0)
    if not p0.converged:
        return 0.0, False
    scale = max(
        1.0,
        abs(_own(p0) + own_moment_offset),
        abs(target),
    )
    if abs(_companion(p0) - target) <= 1.0e-9 * scale:
        if own_moment_offset == 0.0:
            return abs(_own(p0)), True
        face_capacity = _face_own(p0)
        if face_capacity is not None:
            return face_capacity, True

    # Set by _refine/_extremum when a solve INSIDE a bracketed crossing fails to
    # converge (as opposed to a crossing legitimately landing on the wrong face).
    # The coarse-scan `any_fail` cannot see these, so an empty `caps` must fall back
    # to the caller (0.0, False), not be asserted as an honest zero (0.0, True).
    solve_failed = [False]

    def _refine(v_lo, v_hi, c_lo):
        """Bisect [v_lo, v_hi] (which brackets a companion == target crossing) and
        return the correct-face |own| there, or None if it lands on the opposite
        face (not a failure) or a solve fails to converge (flags solve_failed)."""
        f_lo = c_lo - target
        while v_hi - v_lo > tol_deg:
            mid = 0.5 * (v_lo + v_hi)
            pm = _cap(mid)
            if not pm.converged:
                solve_failed[0] = True
                return None
            fm = _companion(pm) - target
            if (fm > 0.0) == (f_lo > 0.0):
                v_lo, f_lo = mid, fm
            else:
                v_hi = mid
        pt = _cap(0.5 * (v_lo + v_hi))
        if not pt.converged:
            solve_failed[0] = True
            return None
        return _face_own(pt)

    def _extremum(v_lo, v_hi, maximize):
        """Golden-section search for the companion extremum in [v_lo, v_hi]; returns
        (angle, point) of the extremal companion, or (None, None) if a solve fails
        to converge (flags solve_failed)."""
        gr = 0.6180339887498949
        c = v_hi - gr * (v_hi - v_lo)
        d = v_lo + gr * (v_hi - v_lo)
        pc, pd = _cap(c), _cap(d)
        for _ in range(60):
            if not (pc.converged and pd.converged):
                solve_failed[0] = True
                return None, None
            if v_hi - v_lo <= tol_deg:
                break
            fc = _companion(pc) if maximize else -_companion(pc)
            fd = _companion(pd) if maximize else -_companion(pd)
            if fc >= fd:
                v_hi, d, pd = d, c, pc
                c = v_hi - gr * (v_hi - v_lo)
                pc = _cap(c)
            else:
                v_lo, c, pc = c, d, pd
                d = v_lo + gr * (v_hi - v_lo)
                pd = _cap(d)
        v = 0.5 * (v_lo + v_hi)
        pt = _cap(v)
        if not pt.converged:
            solve_failed[0] = True
            return None, None
        return v, pt

    # Full-circle scan: sample the companion moment round the neutral-axis angle.
    step = 360.0 / n_scan
    pts = [_cap(i * step) for i in range(n_scan + 1)]
    angs = [i * step for i in range(n_scan + 1)]
    any_fail = any(not p.converged for p in pts)

    # Keep the correct-face capacity wherever the companion equals `target`.
    caps = []
    band = 1.0e-9 * max(1.0, abs(target))
    # (a) A sample sitting ON `target` (e.g. the user pastes a reported envelope
    #     value) IS the crossing -- take its own directly. Handling it here keeps it
    #     out of (b), where a zero endpoint residual (f_lo == 0) would send the
    #     bisection walking away from the true crossing to a different companion.
    for pt in pts:
        if pt.converged and abs(_companion(pt) - target) <= band:
            r = _face_own(pt)
            if r is not None:
                caps.append(r)
    # (b) A crossing STRICTLY between two samples (companion residuals of opposite
    #     sign) is bracketed and bisected.
    for j in range(n_scan):
        a, b = pts[j], pts[j + 1]
        if not (a.converged and b.converged):
            continue
        da, db = _companion(a) - target, _companion(b) - target
        if da * db < 0.0:
            r = _refine(angs[j], angs[j + 1], _companion(a))
            if r is not None:
                caps.append(r)

    # Tangent touches: on a non-convex/asymmetric envelope the companion can reach
    # `target` at a LOCAL EXTREMUM whose sampled peak sits just short of it, so the
    # sign-change loop (which only sees the below-`target` samples) misses the true
    # crossing(s) and the correct-face capacity there would be lost (a false
    # honest-zero). Refine each such same-side local extremum: if its true peak
    # overshoots `target`, bisect the two crossings it exposes; if it only touches,
    # take the tangent point itself.
    # The centre runs over every distinct sample angle INCLUDING the 0/360 seam
    # (j = 0 wraps: neighbours at the last sample and the second, with the window
    # carried past 360 deg -- _cap is periodic in the angle), so a peak straddling
    # the seam is not missed.
    band = 1.0e-6 * max(1.0, abs(target))
    for j in range(n_scan):
        if j == 0:
            a, m, b = pts[n_scan - 1], pts[0], pts[1]
            lo_ang, hi_ang = angs[n_scan - 1], 360.0 + angs[1]
        else:
            a, m, b = pts[j - 1], pts[j], pts[j + 1]
            lo_ang, hi_ang = angs[j - 1], angs[j + 1]
        if not (a.converged and m.converged and b.converged):
            continue
        ca, cm, cb = _companion(a), _companion(m), _companion(b)
        is_max = cm > ca and cm > cb
        is_min = cm < ca and cm < cb
        # Only a local extremum whose sampled value is on the near side of `target`
        # can hide a crossing (an under-sampled true peak/trough).
        if not ((is_max and cm < target) or (is_min and cm > target)):
            continue
        v_ext, p_ext = _extremum(lo_ang, hi_ang, is_max)
        if p_ext is None:
            continue
        c_ext = _companion(p_ext)
        if (c_ext >= target) if is_max else (c_ext <= target):
            # The true extremum overshoots `target`: two crossings flank it.
            for a0, a1, c0 in ((lo_ang, v_ext, ca), (v_ext, hi_ang, c_ext)):
                r = _refine(a0, a1, c0)
                if r is not None:
                    caps.append(r)
        elif abs(c_ext - target) <= band:
            r = _face_own(p_ext)                  # a true tangent: the curve touches
            if r is not None:
                caps.append(r)

    if caps:
        return max(caps), True
    # No correct-face crossing. A clean scan means the off moment genuinely leaves
    # no capacity (honest zero); a failed solve -- either a coarse scan sample
    # (any_fail) or a solve inside a bracketed crossing's refinement (solve_failed)
    # -- could have hidden a crossing, so defer to the caller's pure-axis fallback
    # instead of asserting zero.
    return (0.0, False) if (any_fail or solve_failed[0]) else (0.0, True)
