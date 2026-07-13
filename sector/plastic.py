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

from . import kernels
from .geometry import _clip_pts, _poly_moments
from .materials import Concrete, MildSteel, Prestress
from .section import Section

_MN_TO_KN = 1000.0

# Use the compiled concrete integrator when Numba is available; otherwise fall
# back to the pure-Python band loop below (correct, just slower).
_USE_KERNEL = kernels.HAS_NUMBA


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
    dx: float                 # X component of the lever arm, m
    dy: float                 # Y component of the lever arm, m
    converged: bool


def _governing_curvature(steel, prestress, s_max, c, s_bars, s_tendons, eps_cu):
    """Curvature at ultimate for a trial compression depth ``c`` (s-units).

    The strain profile is scaled until the first material limit is reached:
    concrete crushing (extreme fibre at ``eps_cu``), mild-steel rupture (most
    tensile bar at its ``eut``), or tendon rupture (most tensile cable's total
    strain at its rupture strain). The governing curvature is the smallest of
    these, so no material is ever driven past its limit. ``s_bars`` / ``s_tendons``
    are the bar / tendon depth projections ``x*dx + y*dy`` precomputed once for the
    whole sweep (so the per-bisection-step extremes are just array reductions).
    """
    s_na = s_max - c
    phi = eps_cu / c  # concrete-crushing limit

    # When steel or a tendon governs it sits exactly at its rupture strain, where
    # it is still intact (carrying its rupture force). Back the limiting curvature
    # off by a negligible amount so floating-point rounding cannot tip the strain
    # a hair past rupture (which the material law would read as fractured, zero
    # force). The back-off is far larger than rounding yet physically negligible.
    intact = 1.0 - 1.0e-9

    if s_bars.size:
        s_bar_min = float(s_bars.min())  # most tensile bar
        if s_bar_min < s_na:
            phi = min(phi, intact * steel.eut / (s_na - s_bar_min))
        # The rupture strain is symmetric, so a compression bar must not be driven
        # past eut either. This only bites when eut < the concrete crushing strain
        # (otherwise the concrete fibre, beyond the bars, governs first).
        if steel.active_in_compression:
            s_bar_max = float(s_bars.max())  # most compressed bar
            if s_bar_max > s_na:
                phi = min(phi, intact * steel.eut / (s_bar_max - s_na))

    if prestress is not None and s_tendons.size:
        s_cab_min = float(s_tendons.min())  # most tensile cable
        margin = prestress.rupture_strain - prestress.IS
        if s_cab_min < s_na and margin > 0.0:
            phi = min(phi, intact * margin / (s_na - s_cab_min))

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


def _accumulate(concrete, steel, prestress, dx, dy, s_max, c, phi, n_bands,
                rings, bar_data, tendon_data, ring_xy=None, ring_starts=None,
                buf_a=None, buf_b=None, band_memo=None):
    """Force resultants for a trial compression depth ``c`` (s-units).

    Returns compression and tension force totals and their first moments, in kN
    and kNm, plus the extreme mild-steel strains (most tensile ``min_eps`` and most
    compressed ``max_eps``) and the most tensile tendon strain (compression-positive
    fractions). The neutral axis is at ``s = s_max - c`` and the
    curvature is ``phi`` (the governing ultimate curvature). ``rings`` are the
    oriented concrete rings as ``(x, y)`` point lists; ``bar_data`` /
    ``tendon_data`` are ``(x, y, area, s)`` arrays (``s = x*dx + y*dy`` the depth
    projection) precomputed once for the whole sweep. Tendons (if any) carry
    tension only, and their stress is taken at the total strain ``IS + section
    strain``.

    When ``ring_xy`` (the stacked ring vertices) is supplied the concrete
    integration runs in the compiled kernel; otherwise it uses the pure-Python
    band loop. Both produce the same resultants.
    """
    s_na = s_max - c
    kappa = phi

    comp_F = comp_Fx = comp_Fy = 0.0
    ten_F = ten_Fx = ten_Fy = 0.0

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
        cF, cFx, cFy = kernels.concrete_resultants(
            ring_xy, ring_starts, dx, dy, s_na, s_max, s_peak,
            sig.shape[0], fcd, sig, buf_a, buf_b)
        comp_F += cF
        comp_Fx += cFx
        comp_Fy += cFy
    else:
        # Pure-Python path. Plateau band [s_peak, s_max]: constant strength.
        if s_peak < s_max:
            for ring in rings:
                m = _poly_moments(_clip_pts(ring, dx, dy, -s_peak))  # d.r >= s_peak
                comp_F += fcd * m.area * _MN_TO_KN
                comp_Fx += fcd * m.sx * _MN_TO_KN
                comp_Fy += fcd * m.sy * _MN_TO_KN
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
                    comp_F += sig * m.area * _MN_TO_KN
                    comp_Fx += sig * m.sx * _MN_TO_KN
                    comp_Fy += sig * m.sy * _MN_TO_KN

    # -- reinforcement (point areas, both signs) --
    bx, by, ba, s_bars = bar_data
    min_eps = max_eps = 0.0
    if bx.size:
        eps_b = kappa * (s_bars - s_na)                     # compression positive
        min_eps = float(eps_b.min())                        # most tensile bar strain
        max_eps = float(eps_b.max())                        # most compressed bar strain
        # The material law is a branchy scalar; evaluate it per bar, then form the
        # forces and split compression / tension with array reductions.
        sig_b = np.array([-steel.stress(-e, design=True) for e in eps_b])  # comp +, MPa
        fb = sig_b * ba * _MN_TO_KN                          # kN, comp +
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
    if prestress is not None and tx.size:
        eps_c = kappa * (s_tendons - s_na)                  # section, compression +
        min_eps_cable = float((eps_c - prestress.IS).min())  # reported strain, incl. IS
        e_total = prestress.IS - eps_c                      # total tendon strain (tension +)
        sig_t = np.array([prestress.stress(e, design=True) for e in e_total])  # tension +, MPa
        ft = -sig_t * ta * _MN_TO_KN                        # tension -> negative (comp +)
        comp = ft >= 0.0
        comp_F += float(ft[comp].sum())
        comp_Fx += float((ft[comp] * tx[comp]).sum())
        comp_Fy += float((ft[comp] * ty[comp]).sum())
        ten_F += float(ft[~comp].sum())
        ten_Fx += float((ft[~comp] * tx[~comp]).sum())
        ten_Fy += float((ft[~comp] * ty[~comp]).sum())

    return (comp_F, comp_Fx, comp_Fy, ten_F, ten_Fx, ten_Fy,
            min_eps, max_eps, min_eps_cable)


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


def _prep_section(section: Section, prestress: "Prestress | None") -> _SectionPrep:
    """Build the angle-independent plastic-solver prep for ``section``.

    The oriented rings, the bar/tendon arrays, the concrete vertices and (on the
    compiled path) the stacked ring vertices plus clip scratch buffers do not depend
    on the neutral-axis angle. A sweep builds them once here and reuses them for
    every angle; only the depth projection ``s = x*dx + y*dy`` is re-formed per angle.
    The pure-Python ring point-lists are built only when the kernel is unavailable --
    the compiled path never reads them.
    """
    int_rings = section.integration_rings()
    bx, by, ba = section.bar_arrays()
    if prestress is not None:
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


def plastic_capacity_at_angle(
    section: Section,
    concrete: Concrete,
    steel: MildSteel,
    P: float,
    V_deg: float,
    *,
    prestress: "Prestress | None" = None,
    n_bands: int = 80,
    max_iter: int = 100,
    prep: "_SectionPrep | None" = None,
    band_memo: "dict | None" = None,
) -> PlasticPoint:
    """Ultimate capacity for axial force ``P`` (kN) at neutral-axis angle ``V``.

    The strain profile is taken to its ultimate (the first material limit --
    concrete crushing or steel/tendon rupture -- governs the curvature) and the
    neutral-axis depth solved (by bisection) so the net axial force equals ``P``.
    Pass ``prestress`` (a :class:`~sector.materials.Prestress`) to include the
    section's tendons.
    """
    V = math.radians(V_deg)
    dx, dy = math.cos(V), math.sin(V)

    # The oriented rings, reinforcement arrays and kernel scratch buffers do not
    # depend on the angle, so a sweep builds them once (``prep``) and passes them in;
    # a standalone call builds them here. Only the depth projection ``s = x*dx + y*dy``
    # changes with the angle, formed per angle below so the bisection just reduces it.
    if prep is None:
        prep = _prep_section(section, prestress)
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
        phi = _governing_curvature(steel, prestress, s_max, c, s_bars, s_tendons,
                                   concrete.eps_cu2)
        acc = _accumulate(concrete, steel, prestress, dx, dy, s_max, c, phi,
                          n_bands, rings, bar_data, tendon_data,
                          ring_xy, ring_starts, buf_a, buf_b, band_memo)
        return acc[0] + acc[3]  # comp_F + ten_F (kN)

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

    if P < n_lo:
        c = lo              # requested axial below the pure-tension state (unreachable)
    elif P > n_hi:
        c = hi              # requested axial above the squash load (unreachable)
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

    phi = _governing_curvature(steel, prestress, s_max, c, s_bars, s_tendons,
                               concrete.eps_cu2)
    (comp_F, comp_Fx, comp_Fy, ten_F, ten_Fx, ten_Fy,
     min_eps, max_eps, min_eps_cable) = _accumulate(
        concrete, steel, prestress, dx, dy, s_max, c, phi, n_bands,
        rings, bar_data, tendon_data, ring_xy, ring_starts, buf_a, buf_b, band_memo
    )

    # Convergence is judged on the actual axial equilibrium at the returned depth,
    # not merely on P having been bracketed: a monotonicity failure or a clamped
    # (out-of-range) P leaves a residual that this catches, where the old
    # "bracketable" test would have reported success.
    converged = abs((comp_F + ten_F) - P) <= 1.0e-6 * max(1.0, abs(P))

    Mx = comp_Fy + ten_Fy
    My = comp_Fx + ten_Fx
    kappa = phi
    s_na = s_max - c
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
        axial=comp_F + ten_F,
        U=U,
        R=R,
        na_x_intercept=x_int,
        na_y_intercept=y_int,
        eps_concrete=eps_concrete * 100.0,
        eps_steel=min_eps * 100.0,
        eps_steel_comp=max_eps * 100.0,
        eps_cable=min_eps_cable * 100.0,
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
    prestress: "Prestress | None" = None,
    n_bands: int = 80,
) -> list[PlasticPoint]:
    """Sweep the neutral-axis angle from ``v_min`` to ``v_max`` (inclusive).

    Returns one :class:`PlasticPoint` per angle, the biaxial capacity envelope
    for the axial force ``P``.
    """
    prep = _prep_section(section, prestress)   # angle-independent, built once
    band_memo: dict = {}                        # shared across all angles of the sweep
    points = []
    # Step count from the increment, guarding against floating-point drift.
    n = int(round((v_max - v_min) / v_inc)) if v_inc else 0
    for i in range(n + 1):
        v = v_min + i * v_inc
        points.append(
            plastic_capacity_at_angle(section, concrete, steel, P, v,
                                      prestress=prestress, n_bands=n_bands, prep=prep,
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


def solve_interaction(
    section: Section,
    concrete: Concrete,
    steel: MildSteel,
    V_deg: float,
    *,
    prestress: "Prestress | None" = None,
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
    prep = _prep_section(section, prestress)   # angle-independent, built once
    band_memo: dict = {}                        # shared across all axial samples
    def _cap(P):
        return plastic_capacity_at_angle(section, concrete, steel, P, V_deg,
                                         prestress=prestress, n_bands=n_bands, prep=prep,
                                         band_memo=band_memo)

    # Axial extremes: probe just past the range (a squash / tension over-estimate)
    # and read back the clamped equilibrium, so the diagram spans the true range. The
    # steel force uses each material's own design stress -- tendons yield far above the
    # mild bars, so folding their area in at the mild stress would leave the probe
    # inside the true tension range and the diagram short of the tension limit.
    Ac = sum(_poly_moments(r.tolist()).area for r in section.integration_rings())
    fy = abs(steel.stress(steel.eut * 0.99, design=True))    # mild design stress, MPa
    steel_force = fy * float(section.bar_arrays()[2].sum())  # MN.m^-2 * m^2 = MN
    if prestress is not None:
        fp = abs(prestress.stress(prestress.rupture_strain * 0.99, design=True))
        steel_force += fp * float(section.tendon_arrays()[2].sum())
    squash = (concrete.fcd * Ac + steel_force) * _MN_TO_KN   # kN, an upper bound on N_c
    tension = steel_force * _MN_TO_KN                         # kN, |N_t| upper bound
    N_c = _cap(1.5 * squash + 1.0).axial
    N_t = _cap(-1.5 * tension - 1.0).axial

    pts = []
    for i in range(n_points + 1):
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
    prestress: "Prestress | None" = None,
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
    ``axis`` there.

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
    v0 = FACE_ANGLE[(axis, tension_low)]
    prep = _prep_section(section, prestress)
    band_memo: dict = {}

    def _cap(v):
        return plastic_capacity_at_angle(section, concrete, steel, P, v,
                                         prestress=prestress, n_bands=n_bands,
                                         prep=prep, band_memo=band_memo)

    def _companion(pt):
        return pt.My if axis == "x" else pt.Mx

    def _own(pt):
        return pt.Mx if axis == "x" else pt.My

    target = float(m_off)
    want_positive = tension_low        # the chosen face carries own of this sign

    # Pure-axis probe: if the companion there already equals the target (any
    # section symmetric about the chord axis under a uniaxial load), this IS the
    # answer -- the same solve at the same angle as the pure-axis capacity,
    # bit-identical to it.
    p0 = _cap(v0)
    if not p0.converged:
        return 0.0, False
    scale = max(1.0, abs(_own(p0)), abs(target))
    if abs(_companion(p0) - target) <= 1.0e-9 * scale:
        return abs(_own(p0)), True

    def _face_own(pt):
        """|own| if ``pt`` is on the chosen tension face (own of the wanted sign),
        else None."""
        if not pt.converged:
            return None
        o = _own(pt)
        return abs(o) if ((o > 0.0) if want_positive else (o < 0.0)) else None

    def _refine(v_lo, v_hi, c_lo):
        """Bisect [v_lo, v_hi] (which brackets a companion == target crossing) and
        return the correct-face |own| there, or None if it lands on the opposite
        face or a solve fails."""
        f_lo = c_lo - target
        while v_hi - v_lo > tol_deg:
            mid = 0.5 * (v_lo + v_hi)
            pm = _cap(mid)
            if not pm.converged:
                return None
            fm = _companion(pm) - target
            if (fm > 0.0) == (f_lo > 0.0):
                v_lo, f_lo = mid, fm
            else:
                v_hi = mid
        return _face_own(_cap(0.5 * (v_lo + v_hi)))

    def _extremum(v_lo, v_hi, maximize):
        """Golden-section search for the companion extremum in [v_lo, v_hi]; returns
        (angle, point) of the extremal companion, or (None, None) if a solve fails."""
        gr = 0.6180339887498949
        c = v_hi - gr * (v_hi - v_lo)
        d = v_lo + gr * (v_hi - v_lo)
        pc, pd = _cap(c), _cap(d)
        for _ in range(60):
            if not (pc.converged and pd.converged):
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
        return (v, pt) if pt.converged else (None, None)

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
    # no capacity (honest zero); a failed solve could have hidden a crossing, so
    # defer to the caller's pure-axis fallback instead of asserting zero.
    return (0.0, False) if any_fail else (0.0, True)
