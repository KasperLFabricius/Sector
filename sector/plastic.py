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


def _band_stresses(concrete, kappa, s_na, h, n_bands):
    """Design concrete stresses at each ascending-band midpoint (MPa, comp +)."""
    sig = np.empty(n_bands)
    for i in range(n_bands):
        sa = s_na + i * h
        sb = sa + h
        eps_m = kappa * (0.5 * (sa + sb) - s_na)
        sig[i] = -concrete.stress(-eps_m, design=True)
    return sig


def _accumulate(concrete, steel, prestress, dx, dy, s_max, c, phi, n_bands,
                rings, bar_data, tendon_data, ring_xy=None, ring_starts=None,
                buf_a=None, buf_b=None):
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
            sig = _band_stresses(concrete, kappa, s_na, (s_top - s_na) / n_bands, n_bands)
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

    def net_axial(c):
        phi = _governing_curvature(steel, prestress, s_max, c, s_bars, s_tendons,
                                   concrete.eps_cu2)
        acc = _accumulate(concrete, steel, prestress, dx, dy, s_max, c, phi,
                          n_bands, rings, bar_data, tendon_data,
                          ring_xy, ring_starts, buf_a, buf_b)
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
        rings, bar_data, tendon_data, ring_xy, ring_starts, buf_a, buf_b
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
    points = []
    # Step count from the increment, guarding against floating-point drift.
    n = int(round((v_max - v_min) / v_inc)) if v_inc else 0
    for i in range(n + 1):
        v = v_min + i * v_inc
        points.append(
            plastic_capacity_at_angle(section, concrete, steel, P, v,
                                      prestress=prestress, n_bands=n_bands, prep=prep)
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
    def _cap(P):
        return plastic_capacity_at_angle(section, concrete, steel, P, V_deg,
                                         prestress=prestress, n_bands=n_bands, prep=prep)

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
