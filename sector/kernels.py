"""Compiled inner kernels for the plastic concrete integration.

The plastic capacity sweep spends almost all of its time clipping the concrete
rings into stress bands and integrating each band. That work is a tight loop of
small polygon operations, repeated hundreds of thousands of times per sweep --
exactly what a compiled kernel is for.

:func:`concrete_resultants` fuses the whole concrete integration (the plateau
band plus the midpoint-integrated ascending bands, over every ring) into a
single Numba-compiled function operating on flat arrays, so the inner clips and
moment sums run in native code with no Python-call overhead. The geometry maths
is a faithful port of :func:`sector.geometry.clip_halfplane` (Sutherland-Hodgman)
and :func:`sector.geometry.area_moments` (Green's theorem), so results are
unchanged.

Numba is optional. If it is not installed the same functions run as ordinary
Python (correct, just slower); :data:`HAS_NUMBA` says which is in effect, and the
plastic solver keeps a pure-Python fallback path for that case.
"""

from __future__ import annotations

import numpy as np

try:  # pragma: no cover - exercised by whichever path is installed
    from numba import njit

    HAS_NUMBA = True
except ImportError:  # pragma: no cover
    HAS_NUMBA = False

    def njit(*args, **kwargs):
        """No-op stand-in so the kernels run as plain Python without Numba."""
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]

        def _decorate(func):
            return func

        return _decorate


_MN_TO_KN = 1000.0


@njit(cache=True)
def _clip(src, start, n, a, b, c, dst):
    """Clip a polygon to the half-plane ``a*x + b*y + c >= 0`` (Sutherland-Hodgman).

    Reads ``n`` vertices from ``src[start:start+n]`` and writes the clipped
    polygon into ``dst``, returning its vertex count. Crossing edges are cut on
    the line; this mirrors :func:`sector.geometry.clip_halfplane` with ``eps=0``.
    """
    m = 0
    for i in range(n):
        ii = start + i
        xi = src[ii, 0]
        yi = src[ii, 1]
        d_cur = a * xi + b * yi + c
        jj = start + (i + 1 if i + 1 < n else 0)
        xj = src[jj, 0]
        yj = src[jj, 1]
        d_nxt = a * xj + b * yj + c
        cur_in = d_cur >= 0.0
        nxt_in = d_nxt >= 0.0
        if cur_in:
            dst[m, 0] = xi
            dst[m, 1] = yi
            m += 1
        if cur_in != nxt_in:
            t = d_cur / (d_cur - d_nxt)
            dst[m, 0] = xi + t * (xj - xi)
            dst[m, 1] = yi + t * (yj - yi)
            m += 1
    return m


@njit(cache=True)
def _moments3(p, n):
    """Signed area and first moments (area, Sx, Sy) of ``p[:n]`` via Green's theorem.

    Only the three integrals the plastic forces need; fewer than three vertices
    enclose nothing and return zeros.
    """
    if n < 3:
        return 0.0, 0.0, 0.0
    a2 = 0.0
    sx6 = 0.0
    sy6 = 0.0
    xi = p[n - 1, 0]
    yi = p[n - 1, 1]
    for i in range(n):
        xj = p[i, 0]
        yj = p[i, 1]
        cross = xi * yj - xj * yi
        a2 += cross
        sx6 += (xi + xj) * cross
        sy6 += (yi + yj) * cross
        xi = xj
        yi = yj
    return 0.5 * a2, sx6 / 6.0, sy6 / 6.0


@njit(cache=True)
def concrete_resultants(ring_xy, ring_starts, dx, dy, s_na, s_max, s_peak,
                        n_bands, fcd, sig, buf_a, buf_b):
    """Concrete compression resultants ``(F, Fx, Fy)`` in kN for one strain state.

    ``ring_xy`` is every oriented ring vertex stacked ``(M, 2)`` and
    ``ring_starts`` the per-ring offsets (length ``R + 1``). The strain band
    structure matches the reference integrator: a constant-strength plateau over
    ``[s_peak, s_max]`` plus ``n_bands`` midpoint bands over ``[s_na, min(s_peak,
    s_max)]`` with precomputed stresses ``sig``. ``buf_a`` / ``buf_b`` are
    caller-supplied scratch arrays. Each term is scaled to kN exactly as the
    reference does, so the totals match to floating point.
    """
    n_rings = ring_starts.shape[0] - 1
    comp_f = 0.0
    comp_fx = 0.0
    comp_fy = 0.0

    # Plateau band [s_peak, s_max]: constant design strength fcd.
    if s_peak < s_max:
        for r in range(n_rings):
            start = ring_starts[r]
            n = ring_starts[r + 1] - start
            m = _clip(ring_xy, start, n, dx, dy, -s_peak, buf_a)
            area, sx, sy = _moments3(buf_a, m)
            comp_f += fcd * area * _MN_TO_KN
            comp_fx += fcd * sx * _MN_TO_KN
            comp_fy += fcd * sy * _MN_TO_KN

    # Ascending bands [s_na, s_top]: midpoint integration with sig[i].
    s_top = s_peak if s_peak < s_max else s_max
    if s_top > s_na and n_bands > 0:
        h = (s_top - s_na) / n_bands
        for i in range(n_bands):
            si = sig[i]
            if si == 0.0:
                continue
            sa = s_na + i * h
            sb = sa + h
            for r in range(n_rings):
                start = ring_starts[r]
                n = ring_starts[r + 1] - start
                m1 = _clip(ring_xy, start, n, dx, dy, -sa, buf_a)
                m2 = _clip(buf_a, 0, m1, -dx, -dy, sb, buf_b)
                area, sx, sy = _moments3(buf_b, m2)
                comp_f += si * area * _MN_TO_KN
                comp_fx += si * sx * _MN_TO_KN
                comp_fy += si * sy * _MN_TO_KN

    return comp_f, comp_fx, comp_fy


def warmup() -> bool:
    """Trigger kernel compilation on a trivial section. Returns :data:`HAS_NUMBA`.

    Compiling here (e.g. at app start) keeps the first real Calculate from paying
    the one-off JIT cost. With ``cache=True`` the compiled code is reused across
    later process starts, so this is effectively free after the first ever run.
    """
    ring_xy = np.array([[-0.1, -0.1], [0.1, -0.1], [0.1, 0.1], [-0.1, 0.1]])
    ring_starts = np.array([0, 4], dtype=np.int64)
    buf_a = np.empty((16, 2))
    buf_b = np.empty((16, 2))
    sig = np.full(4, 10.0)
    concrete_resultants(ring_xy, ring_starts, 0.0, 1.0, -0.1, 0.1, 0.0,
                        4, 20.0, sig, buf_a, buf_b)
    return HAS_NUMBA
