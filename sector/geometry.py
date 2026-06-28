"""Exact polygon geometry kernels for cross-section integration.

Everything Sector computes about a cross-section reduces to integrating a
*linear* field (a strain plane, and hence -- in the elastic range -- a linear
stress field) over a polygonal region. For a linear integrand the required
area integrals are exact closed-form functions of the polygon vertices, via
Green's theorem (the "shoelace" moment formulas). No meshing or numerical
quadrature is needed, which keeps results exact and reproducible.

Two operations live here:

* :func:`area_moments` -- the area integrals of 1, x, y, x^2, y^2 and xy over
  a polygon. These are everything needed to form a section's axial force and
  biaxial moment from a linear stress field.
* :func:`clip_halfplane` -- intersect a polygon with a half-plane. The concrete
  compression zone is the part of the section on the compressive side of the
  neutral axis, i.e. the polygon clipped by a half-plane; clipping it and then
  integrating gives the concrete contribution exactly.

Conventions
-----------
* A polygon is a sequence of ``(x, y)`` vertices, not repeated at the end
  (the closing edge from the last vertex back to the first is implied).
* Signed area is positive for counter-clockwise (CCW) vertex order. A region
  with holes is represented by a CCW outer ring and CW hole rings; because all
  the integrals here are *signed*, summing per-ring results subtracts the holes
  automatically (see :func:`area_moments_rings`).
* Units are arbitrary but must be consistent; Sector uses metres.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np

Vertices = Sequence[Sequence[float]]


@dataclass(frozen=True)
class AreaMoments:
    """Signed area integrals of a polygonal region.

    Each field is the integral of the named monomial over the region:

    ===========  =====================
    attribute    integral
    ===========  =====================
    ``area``     :math:`\\int \\mathrm{d}A`
    ``sx``       :math:`\\int x \\, \\mathrm{d}A`
    ``sy``       :math:`\\int y \\, \\mathrm{d}A`
    ``sxx``      :math:`\\int x^2 \\, \\mathrm{d}A`
    ``syy``      :math:`\\int y^2 \\, \\mathrm{d}A`
    ``sxy``      :math:`\\int x y \\, \\mathrm{d}A`
    ===========  =====================

    Values are *signed* by vertex orientation (CCW positive). The first moments
    are about the global origin, not the centroid.
    """

    area: float
    sx: float
    sy: float
    sxx: float
    syy: float
    sxy: float

    def __add__(self, other: "AreaMoments") -> "AreaMoments":
        return AreaMoments(
            self.area + other.area,
            self.sx + other.sx,
            self.sy + other.sy,
            self.sxx + other.sxx,
            self.syy + other.syy,
            self.sxy + other.sxy,
        )

    @property
    def centroid(self) -> tuple[float, float]:
        """Area centroid ``(x_c, y_c)``.

        Raises :class:`ZeroDivisionError`-free ``ValueError`` on a degenerate
        (zero-area) region, where a centroid is undefined.
        """
        if self.area == 0.0:
            raise ValueError("centroid undefined for a zero-area region")
        return (self.sx / self.area, self.sy / self.area)


def _as_array(verts: Vertices) -> np.ndarray:
    arr = np.asarray(verts, dtype=float)
    if arr.size == 0:
        # An empty vertex list is a valid degenerate (zero-area) polygon.
        return np.empty((0, 2), dtype=float)
    if arr.ndim != 2 or arr.shape[1] != 2:
        raise ValueError("vertices must be an (N, 2) sequence of (x, y) points")
    return arr


def signed_area(verts: Vertices) -> float:
    """Signed area of a polygon (CCW positive) via the shoelace formula.

    Fewer than three vertices enclose no area and return ``0.0``.
    """
    arr = _as_array(verts)
    if arr.shape[0] < 3:
        return 0.0
    x = arr[:, 0]
    y = arr[:, 1]
    x1 = np.roll(x, -1)
    y1 = np.roll(y, -1)
    return 0.5 * float(np.sum(x * y1 - x1 * y))


_ZERO_MOMENTS = AreaMoments(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


def _poly_moments(pts) -> AreaMoments:
    """Green's-theorem area moments of a polygon given as ``(x, y)`` pairs.

    A plain scalar loop (no NumPy). The polygons integrated here have only a
    handful of vertices, where NumPy's per-call overhead -- temporary arrays,
    ``roll``, reduction dispatch -- dwarfs the arithmetic; iterating in Python
    is several times faster. The formulas are identical to the vectorised form,
    so results match to floating-point.
    """
    n = len(pts)
    if n < 3:
        return _ZERO_MOMENTS
    a2 = sx6 = sy6 = sxx12 = syy12 = sxy24 = 0.0
    xi, yi = pts[-1]
    for xj, yj in pts:
        cross = xi * yj - xj * yi
        a2 += cross
        sx6 += (xi + xj) * cross
        sy6 += (yi + yj) * cross
        sxx12 += (xi * xi + xi * xj + xj * xj) * cross
        syy12 += (yi * yi + yi * yj + yj * yj) * cross
        sxy24 += (xi * yj + 2.0 * xi * yi + 2.0 * xj * yj + xj * yi) * cross
        xi, yi = xj, yj
    return AreaMoments(0.5 * a2, sx6 / 6.0, sy6 / 6.0,
                       sxx12 / 12.0, syy12 / 12.0, sxy24 / 24.0)


def area_moments(verts: Vertices) -> AreaMoments:
    """Exact signed area integrals of 1, x, y, x^2, y^2, xy over a polygon.

    Derived from Green's theorem; for each edge from ``(x_i, y_i)`` to
    ``(x_{i+1}, y_{i+1})`` let ``cross = x_i*y_{i+1} - x_{i+1}*y_i``. Then the
    integrals are weighted sums of ``cross`` over the edges. The results are
    exact for any simple polygon (convex or concave) and signed by orientation.

    A polygon with fewer than three vertices returns all-zero moments.
    """
    arr = _as_array(verts)
    if arr.shape[0] < 3:
        return _ZERO_MOMENTS
    return _poly_moments(arr.tolist())


def area_moments_rings(rings: Iterable[Vertices]) -> AreaMoments:
    """Sum the signed moments of several rings (outer ring plus holes).

    The caller supplies each ring with the orientation that encodes its role:
    a CCW outer ring contributes positively and a CW hole ring contributes
    negatively, so the net is the solid area minus the holes. Pass rings in any
    order; only their individual orientations matter.
    """
    total = AreaMoments(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    for ring in rings:
        total = total + area_moments(ring)
    return total


def _segment_distance(px, py, ax, ay, bx, by) -> float:
    """Distance from point ``(px, py)`` to the segment ``(ax,ay)-(bx,by)``."""
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    if length2 <= 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / length2
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def distance_to_boundary(px: float, py: float, rings: Iterable[Vertices]) -> float:
    """Smallest distance from a point to the edges of any ring (outer + holes).

    Used to find a bar's clear cover: the distance to the nearest concrete face.
    """
    best = math.inf
    for ring in rings:
        arr = _as_array(ring)
        m = len(arr)
        for i in range(m):
            ax, ay = float(arr[i, 0]), float(arr[i, 1])
            bx, by = float(arr[(i + 1) % m, 0]), float(arr[(i + 1) % m, 1])
            d = _segment_distance(px, py, ax, ay, bx, by)
            if d < best:
                best = d
    return best


def _points_in_polygon(px: np.ndarray, py: np.ndarray, poly: np.ndarray) -> np.ndarray:
    """Even-odd (ray-casting) point-in-polygon test, vectorised over the points.

    ``px``/``py`` are arrays of query coordinates; ``poly`` is an ``(M, 2)`` ring.
    Loops over the few polygon edges (not the many points), so it stays fast for a
    dense grid of samples. Returns a boolean array, True where the point is inside.
    """
    inside = np.zeros(px.shape, dtype=bool)
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i, 0], poly[i, 1]
        xj, yj = poly[j, 0], poly[j, 1]
        straddles = (yi > py) != (yj > py)        # edge crosses the point's row
        with np.errstate(divide="ignore", invalid="ignore"):
            x_cross = (xj - xi) * (py - yi) / (yj - yi) + xi
        inside ^= straddles & (px < x_cross)      # toggle on each crossing to the left
        j = i
    return inside


def concrete_is_connected(outer: Vertices, holes: Iterable[Vertices] = ()) -> bool:
    """Whether the concrete (``outer`` minus ``holes``) is a single connected region.

    A void must not split the concrete in two -- e.g. a slot reaching across the
    section -- because a disconnected cross-section has no valid meaning. The region
    is rasterised onto a grid sized by the section's larger dimension (so the cell
    count is bounded) and the filled cells are checked for 4-connectivity: cells
    touching only at a corner count as separated, matching the physical reality that
    a point contact carries no force. A solid outline (no holes) is always connected.

    The test is exact at the grid resolution (about 1/240 of the larger dimension);
    a ligament thinner than a cell -- far below any real concrete web -- could be
    missed, which is acceptable for input validation.
    """
    arr = _as_array(outer)
    holes = [h for h in (_as_array(r) for r in holes) if h.shape[0] >= 3]
    if arr.shape[0] < 3 or not holes:
        return True
    x0, y0 = float(arr[:, 0].min()), float(arr[:, 1].min())
    x1, y1 = float(arr[:, 0].max()), float(arr[:, 1].max())
    span = max(x1 - x0, y1 - y0)
    if span <= 0.0:
        return True
    grid = 240
    cell = span / grid
    nx = max(1, int(round((x1 - x0) / cell)))
    ny = max(1, int(round((y1 - y0) / cell)))
    # Sample at cell centres so the boundary is never sampled ambiguously.
    xs = x0 + (np.arange(nx) + 0.5) * (x1 - x0) / nx
    ys = y0 + (np.arange(ny) + 0.5) * (y1 - y0) / ny
    gx, gy = np.meshgrid(xs, ys)
    fx, fy = gx.ravel(), gy.ravel()
    mask = _points_in_polygon(fx, fy, arr)
    for hole in holes:
        mask &= ~_points_in_polygon(fx, fy, hole)
    mask = mask.reshape(ny, nx)
    return _single_component(mask)


def _single_component(mask: np.ndarray) -> bool:
    """True if the filled cells of a boolean grid form one 4-connected region."""
    filled = np.argwhere(mask)
    if filled.shape[0] == 0:
        return True                       # nothing filled -> not "split"
    ny, nx = mask.shape
    seen = np.zeros_like(mask)
    si, sj = int(filled[0, 0]), int(filled[0, 1])
    seen[si, sj] = True
    stack = [(si, sj)]
    reached = 0
    while stack:
        i, j = stack.pop()
        reached += 1
        for ni, nj in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
            if 0 <= ni < ny and 0 <= nj < nx and mask[ni, nj] and not seen[ni, nj]:
                seen[ni, nj] = True
                stack.append((ni, nj))
    return reached == filled.shape[0]


def orient(verts: Vertices, ccw: bool = True) -> np.ndarray:
    """Return the vertices reordered to the requested orientation.

    Useful for normalising input of mixed/unknown winding before integration
    or clipping. A degenerate polygon (zero area) is returned unchanged.
    """
    arr = _as_array(verts)
    a = signed_area(arr)
    if a == 0.0:
        return arr.copy()
    is_ccw = a > 0.0
    return arr.copy() if is_ccw == ccw else arr[::-1].copy()


def clip_halfplane(
    verts: Vertices, a: float, b: float, c: float, eps: float = 0.0
) -> np.ndarray:
    """Clip a polygon to the half-plane ``a*x + b*y + c >= 0``.

    Implements the Sutherland-Hodgman algorithm against a single line
    ``a*x + b*y + c = 0``. The returned polygon is the part of the input lying
    on the side where ``a*x + b*y + c >= 0`` (the "inside"); edges that cross
    the line are split at the exact intersection point. The result preserves
    the input orientation.

    This is how the concrete *compression zone* is extracted: with the neutral
    axis written as ``a*x + b*y + c = 0`` and the coefficients signed so that
    the compressive side is positive, the clipped polygon is exactly the part
    of the section carrying concrete stress.

    Returns an ``(M, 2)`` array, or an empty ``(0, 2)`` array if the polygon
    lies entirely outside the half-plane. ``eps`` shifts the kept region's
    boundary outward to the line ``a*x + b*y + c = -eps`` (points with value
    ``>= -eps`` are inside, and crossing edges are cut on that same line so the
    result is unbiased); the default ``0.0`` cuts exactly on the line.
    """
    arr = _as_array(verts)
    if arr.shape[0] == 0:
        return np.empty((0, 2), dtype=float)
    out = _clip_pts(arr.tolist(), a, b, c, eps)
    if not out:
        return np.empty((0, 2), dtype=float)
    return np.asarray(out, dtype=float)


def _clip_pts(pts, a: float, b: float, c: float, eps: float = 0.0):
    """Sutherland-Hodgman clip of a polygon (list of ``(x, y)``) to a half-plane.

    Returns a list of ``(x, y)`` tuples on the side ``a*x + b*y + c >= -eps``;
    crossing edges are cut on that same line. A plain scalar loop, for the same
    reason as :func:`_poly_moments`: the polygons are tiny and NumPy's overhead
    dominates. The edge signed distances are evaluated once each and reused.
    """
    n = len(pts)
    if n == 0:
        return []
    vals = [a * x + b * y + c for x, y in pts]
    out = []
    for i in range(n):
        d_cur = vals[i]
        j = i + 1 if i + 1 < n else 0
        d_nxt = vals[j]
        cur_in = d_cur >= -eps
        nxt_in = d_nxt >= -eps
        xi, yi = pts[i]
        if cur_in:
            out.append((xi, yi))
        if cur_in != nxt_in:
            # Edge crosses the inside boundary a*x + b*y + c = -eps. Solve for
            # the crossing on that SAME line the inside predicate uses, so the
            # cut and the kept vertices stay consistent and the area/moments are
            # unbiased when eps != 0. The denominator cannot be zero here
            # because the endpoints lie on opposite sides, so d_cur != d_nxt.
            t = (d_cur + eps) / (d_cur - d_nxt)
            xj, yj = pts[j]
            out.append((xi + t * (xj - xi), yi + t * (yj - yi)))
    return out
