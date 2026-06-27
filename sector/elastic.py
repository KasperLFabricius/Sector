"""Elastic analysis of a cracked reinforced-concrete cross-section.

Given a section under an eccentric axial load (an axial force combined with
biaxial bending), this finds the linear strain plane that puts the section in
equilibrium, then reports the resulting concrete and reinforcement stresses.

Model
-----
* The strain over the section is a plane: ``eps(x, y) = eps0 + kx*x + ky*y``,
  with **tension positive**.
* Concrete is linear elastic in compression only -- its tensile strength is
  taken as zero, so it carries stress solely where ``eps < 0`` (the compression
  zone, extracted by clipping each ring with the neutral-axis line).
* Reinforcement is linear elastic in both tension and compression. Steel and
  concrete are coupled through the modular ratio ``n = Es / Ec``, supplied per
  load case. A bar sitting inside the compression zone displaces concrete that
  the gross concrete integral already counts, so its effective contribution
  there is ``(n - 1)`` times the concrete stiffness rather than ``n``.

Scale invariance
----------------
For a given load and modular ratio the *stresses* do not depend on the absolute
value of ``Ec`` (doubling all moduli halves the strains and leaves the stresses
unchanged). The solver therefore fixes ``Ec = 1`` and works in load-consistent
units: with forces in kN, moments in kNm, coordinates in m and areas in m^2,
the returned stresses are in kN/m^2 (1 MPa = 1000 kN/m^2).

Sign convention for loads
-------------------------
Loads are given the way the section results are stated by engineers: ``P`` is an
axial force positive in **compression**, and ``Mx`` / ``My`` are the bending
moments about the X and Y axes (taken about the coordinate origin). Internally
these map to the tension-positive resultant targets the strain plane must meet.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .geometry import AreaMoments, area_moments, clip_halfplane
from .section import Section

# Treat |value| below this (in the load-consistent stress*area sense) as zero
# when deciding convergence of the resultant residual.
_DEFAULT_TOL = 1.0e-9


@dataclass
class ElasticResult:
    """Outcome of an elastic cracked-section analysis for one load.

    Stresses are in load-consistent units (kN/m^2 for kN/m/mm-built sections),
    tension positive for steel; ``max_concrete_compression`` is reported as a
    positive magnitude.
    """

    eps0: float
    kx: float
    ky: float
    bar_stress: np.ndarray
    max_concrete_compression: float
    max_concrete_point: int
    max_concrete_xy: tuple[float, float]
    na_x_intercept: float
    na_y_intercept: float
    converged: bool
    iterations: int
    # Peak concrete *tensile* stress and its location. Zero on a fully cracked
    # solve (concrete carries no tension there); the meaningful value comes from
    # an uncracked (Stage I) solve, where it drives the cracking check.
    max_concrete_tension: float = 0.0
    max_concrete_tension_point: int = 0
    max_concrete_tension_xy: tuple[float, float] = (0.0, 0.0)

    @property
    def strain_plane(self) -> tuple[float, float, float]:
        return (self.eps0, self.kx, self.ky)


def _concrete_moments(rings: list[np.ndarray], eps0: float, kx: float, ky: float) -> AreaMoments:
    """Signed area moments of the concrete *compression* zone.

    The compression zone is where ``eps0 + kx*x + ky*y < 0``; equivalently the
    half-plane ``(-kx)*x + (-ky)*y + (-eps0) >= 0``. Each ring is clipped to it
    and the per-ring moments summed, so holes (clockwise) subtract.
    """
    total = AreaMoments(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    for ring in rings:
        clipped = clip_halfplane(ring, -kx, -ky, -eps0)
        total = total + area_moments(clipped)
    return total


def _resultants_and_jacobian(
    rings: list[np.ndarray],
    bx: np.ndarray,
    by: np.ndarray,
    ba: np.ndarray,
    u: np.ndarray,
    n: float,
    displace_concrete: bool,
    cracked: bool,
) -> tuple[np.ndarray, np.ndarray]:
    """Internal resultants ``[N, Mx, My]`` and the 3x3 Jacobian d(res)/d u.

    With ``Ec = 1`` the concrete stress is ``eps`` and a bar's is ``n*eps``. The
    resultants are linear in ``u`` for a fixed compression zone, so the Jacobian
    is just the (transformed, cracked) section stiffness; the moving-boundary
    term vanishes because the stress is zero on the neutral axis.
    """
    eps0, kx, ky = u

    # -- concrete contribution --
    if cracked:
        cm = _concrete_moments(rings, eps0, kx, ky)
    else:
        cm = AreaMoments(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        for ring in rings:
            cm = cm + area_moments(ring)
    A, Sx, Sy, Sxx, Syy, Sxy = cm.area, cm.sx, cm.sy, cm.sxx, cm.syy, cm.sxy

    # Jacobian rows are [N, Mx, My] vs [eps0, kx, ky]. Mx couples to y, My to x.
    J = np.array(
        [
            [A, Sx, Sy],
            [Sy, Sxy, Syy],
            [Sx, Sxx, Sxy],
        ],
        dtype=float,
    )
    res = J @ u  # concrete resultants (sigma = eps over the zone)

    # -- reinforcement contribution --
    if bx.size:
        eps_b = eps0 + kx * bx + ky * by
        coef = np.full(bx.shape, float(n))
        if displace_concrete:
            # Compression bars sit in concrete already integrated above; net
            # stiffness there is (n - 1) instead of n.
            coef = np.where(eps_b < 0.0, n - 1.0, n)
        g = coef * ba  # stiffness weight per bar
        f = g * eps_b  # bar force (tension positive)
        res = res + np.array([f.sum(), (f * by).sum(), (f * bx).sum()])
        # Jacobian additions: d[N,Mx,My]/du from sum_i g_i * eps_i * {1, y_i, x_i}
        Jb = np.array(
            [
                [g.sum(), (g * bx).sum(), (g * by).sum()],
                [(g * by).sum(), (g * bx * by).sum(), (g * by * by).sum()],
                [(g * bx).sum(), (g * bx * bx).sum(), (g * bx * by).sum()],
            ],
            dtype=float,
        )
        J = J + Jb

    return res, J


def _newton_solve(
    rings: list[np.ndarray],
    bx: np.ndarray,
    by: np.ndarray,
    ba: np.ndarray,
    target: np.ndarray,
    n: float,
    displace_concrete: bool,
    max_iter: int,
    tol: float,
) -> tuple[np.ndarray, bool, int]:
    """Find the strain plane whose internal resultants equal ``target``.

    Returns the strain plane ``u = [eps0, kx, ky]`` and convergence info. The
    initial guess is the uncracked linear solution; each iteration re-clips the
    compression zone, so the active (cracked) set settles in a few steps.
    """
    _, J0 = _resultants_and_jacobian(
        rings, bx, by, ba, np.zeros(3), n, displace_concrete=False, cracked=False
    )
    try:
        u = np.linalg.solve(J0, target)
    except np.linalg.LinAlgError:
        u = np.zeros(3)

    scale = max(1.0, float(np.abs(target).max()))
    converged = False
    iterations = 0
    for iterations in range(1, max_iter + 1):
        res, J = _resultants_and_jacobian(
            rings, bx, by, ba, u, n, displace_concrete, cracked=True
        )
        r = res - target
        if np.max(np.abs(r)) <= tol * scale:
            converged = True
            break
        try:
            du = np.linalg.solve(J, -r)
        except np.linalg.LinAlgError:
            break
        u = u + du
    return u, converged, iterations


def _steel_resultant(
    stress: np.ndarray, bx: np.ndarray, by: np.ndarray, ba: np.ndarray
) -> np.ndarray:
    """Resultant ``[N, Mx, My]`` of a set of bar stresses (tension positive)."""
    if not stress.size:
        return np.zeros(3)
    f = stress * ba
    return np.array([f.sum(), (f * by).sum(), (f * bx).sum()])


def _bar_stress(u: np.ndarray, bx: np.ndarray, by: np.ndarray, n: float) -> np.ndarray:
    """Steel stress ``sigma = n * eps`` at each bar (Ec = 1)."""
    if not bx.size:
        return np.empty(0)
    return n * (u[0] + u[1] * bx + u[2] * by)


def _result_from_plane(
    section: Section, u: np.ndarray, bx: np.ndarray, by: np.ndarray, n: float,
    converged: bool, iterations: int,
) -> "ElasticResult":
    """Assemble an :class:`ElasticResult` from a solved strain plane."""
    eps0, kx, ky = float(u[0]), float(u[1]), float(u[2])
    bar_stress = _bar_stress(u, bx, by, n)

    # Maximum concrete compression: the most negative strain over the concrete
    # vertices (that extreme fibre is necessarily inside the compression zone).
    # Ties resolve to the lowest-indexed point (the "POINT n" convention).
    verts = section.concrete_vertices()
    eps_v = eps0 + kx * verts[:, 0] + ky * verts[:, 1]
    min_eps = float(eps_v.min())
    tie = 1.0e-9 * max(1.0, abs(min_eps))
    point = int(np.argmax(eps_v <= min_eps + tie))
    max_comp = -min_eps if min_eps < 0.0 else 0.0

    # Maximum concrete tension: the most positive strain over the concrete
    # vertices (with Ec = 1 the stress equals the strain). Meaningful on an
    # uncracked solve; on a cracked solve the tension zone carries no stress.
    max_eps = float(eps_v.max())
    tie_t = 1.0e-9 * max(1.0, abs(max_eps))
    t_point = int(np.argmax(eps_v >= max_eps - tie_t))
    max_tens = max_eps if max_eps > 0.0 else 0.0

    # Neutral-axis intercepts; infinite when the gradient is parallel to an axis.
    grad = max(abs(kx), abs(ky))
    x_int = -eps0 / kx if abs(kx) > 1.0e-9 * grad else np.inf
    y_int = -eps0 / ky if abs(ky) > 1.0e-9 * grad else np.inf

    return ElasticResult(
        eps0=eps0,
        kx=kx,
        ky=ky,
        bar_stress=bar_stress,
        max_concrete_compression=max_comp,
        max_concrete_point=point,
        max_concrete_xy=(float(verts[point, 0]), float(verts[point, 1])),
        na_x_intercept=float(x_int),
        na_y_intercept=float(y_int),
        converged=converged,
        iterations=iterations,
        max_concrete_tension=max_tens,
        max_concrete_tension_point=t_point,
        max_concrete_tension_xy=(float(verts[t_point, 0]), float(verts[t_point, 1])),
    )


def solve_elastic(
    section: Section,
    P: float,
    Mx: float,
    My: float,
    n: float,
    *,
    displace_concrete: bool = False,
    max_iter: int = 100,
    tol: float = _DEFAULT_TOL,
) -> ElasticResult:
    """Solve the cracked elastic section for an axial force and biaxial moments.

    Parameters
    ----------
    section:
        The cross-section.
    P:
        Axial force, positive in compression.
    Mx, My:
        Bending moments about the X and Y axes (about the origin).
    n:
        Modular ratio ``Es / Ec`` for this load.
    displace_concrete:
        Subtract the concrete displaced by bars in the compression zone
        (the ``(n - 1)`` treatment). Default ``False`` -- the fully cracked
        transformed section uses ``n*A`` for every bar and counts the gross
        concrete compression block, which is what Sector reproduces.

    Returns
    -------
    ElasticResult
        Strain plane, per-bar stresses, the maximum concrete compression and
        its location, the neutral-axis intercepts, and convergence info.
    """
    rings = section.integration_rings()
    bx, by, ba = section.bar_arrays()

    # Target resultants in the tension-positive convention. A compressive P maps
    # to a negative axial resultant; the applied moments enter with the sign
    # that places the compression zone consistently with the moments.
    target = np.array([-float(P), -float(Mx), -float(My)], dtype=float)
    u, converged, iterations = _newton_solve(
        rings, bx, by, ba, target, n, displace_concrete, max_iter, tol
    )
    return _result_from_plane(section, u, bx, by, n, converged, iterations)


def solve_elastic_uncracked(
    section: Section,
    P: float,
    Mx: float,
    My: float,
    n: float,
) -> ElasticResult:
    """Solve the *uncracked* (Stage I) elastic section.

    Concrete is linear elastic in both tension and compression over the whole
    section, so equilibrium is a single linear solve -- no neutral-axis
    iteration. This is the state before cracking; the returned
    ``max_concrete_tension`` is the peak concrete tensile stress that the
    serviceability cracking check compares against ``f_ctm``.

    The bars enter the uncracked transformed section at ``n*A`` (consistent with
    the cracked solver); the ``(n - 1)`` displaced-concrete refinement is not
    applied, a sub-percent effect on the cracking load.
    """
    rings = section.integration_rings()
    bx, by, ba = section.bar_arrays()
    target = np.array([-float(P), -float(Mx), -float(My)], dtype=float)
    _, J = _resultants_and_jacobian(
        rings, bx, by, ba, np.zeros(3), n, displace_concrete=False, cracked=False
    )
    try:
        u = np.linalg.solve(J, target)
        converged = True
    except np.linalg.LinAlgError:
        u = np.zeros(3)
        converged = False
    return _result_from_plane(section, u, bx, by, n, converged, iterations=0)


@dataclass
class CombinedElasticResult:
    """Result of a combined long- and short-term elastic analysis.

    Steel stresses are given as four columns, tension positive:

    * ``bar_stress_long`` -- long-term load alone, at the long-term modular
      ratio ``nl``.
    * ``bar_stress_rst1`` -- the instantaneous response to the combined load
      with the long-term concrete stresses neutralised, at the short-term ratio
      ``ns``.
    * ``bar_stress_total`` -- the combined long+short result,
      ``long*(1 - ns/nl) + rst1``.
    * ``bar_stress_dif`` -- ``total - long``.

    The concrete compression and neutral-axis intercepts are those of the
    instantaneous (short-term) state, which is what the concrete actually
    experiences under the combined load.
    """

    long: ElasticResult
    short_term: ElasticResult
    bar_stress_total: np.ndarray
    bar_stress_long: np.ndarray
    bar_stress_dif: np.ndarray
    bar_stress_rst1: np.ndarray
    max_concrete_compression: float
    max_concrete_point: int
    na_x_intercept: float
    na_y_intercept: float
    converged: bool


def solve_elastic_combined(
    section: Section,
    P_long: float,
    Mx_long: float,
    My_long: float,
    nl: float,
    P_short: float,
    Mx_short: float,
    My_short: float,
    ns: float,
    *,
    displace_concrete: bool = False,
    max_iter: int = 100,
    tol: float = _DEFAULT_TOL,
) -> CombinedElasticResult:
    """Elastic analysis under combined long- and short-term load.

    Concrete's effective modulus under sustained load is lower (modular ratio
    ``nl``) than under instantaneous load (``ns``). The combined steel stress is
    built in the three-step way:

    1. Solve the long-term load at ``nl`` -> the long-term steel stress ``s1``.
    2. Reduce it: ``s2 = s1*(1 - ns/nl)``; the resultant of these reduced steel
       stresses is the fictitious force ``(N_neu, M_neu)`` that neutralises the
       long-term concrete stresses.
    3. Solve the *combined* load minus ``(N_neu, M_neu)`` at ``ns`` -> the
       instantaneous steel stress ``RST1`` (and the concrete state).
    4. Combine: ``total = s2 + RST1``.

    Pass the short-term parts as zero (and ``ns`` equal to ``nl``) to recover a
    pure long-term analysis.
    """
    rings = section.integration_rings()
    bx, by, ba = section.bar_arrays()

    # 1. Long-term state at nl.
    t_long = np.array([-float(P_long), -float(Mx_long), -float(My_long)])
    u_long, c1, _ = _newton_solve(rings, bx, by, ba, t_long, nl, displace_concrete, max_iter, tol)
    long_res = _result_from_plane(section, u_long, bx, by, nl, c1, 0)
    s1 = long_res.bar_stress

    # 2. Reduced steel stress and its resultant (the neutralising force).
    s2 = s1 * (1.0 - ns / nl) if s1.size else s1
    neu = _steel_resultant(s2, bx, by, ba)

    # 3. Instantaneous state: combined load minus the neutralising force, at ns.
    t_comb = np.array(
        [-(float(P_long) + float(P_short)),
         -(float(Mx_long) + float(Mx_short)),
         -(float(My_long) + float(My_short))]
    )
    u_st, c2, _ = _newton_solve(rings, bx, by, ba, t_comb - neu, ns, displace_concrete, max_iter, tol)
    st_res = _result_from_plane(section, u_st, bx, by, ns, c2, 0)
    rst1 = st_res.bar_stress

    # 4. Combine.
    total = s2 + rst1 if s1.size else rst1
    dif = total - s1 if s1.size else total

    return CombinedElasticResult(
        long=long_res,
        short_term=st_res,
        bar_stress_total=total,
        bar_stress_long=s1,
        bar_stress_dif=dif,
        bar_stress_rst1=rst1,
        max_concrete_compression=st_res.max_concrete_compression,
        max_concrete_point=st_res.max_concrete_point,
        na_x_intercept=st_res.na_x_intercept,
        na_y_intercept=st_res.na_y_intercept,
        converged=c1 and c2,
    )
