"""Exact polygon geometry kernels for cross-section integration.

Everything Sector computes about a cross-section reduces to integrating a
*linear* field (a strain plane, and hence — in the elastic range — a linear
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
        return AreaMoments(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    x = arr[:, 0]
    y = arr[:, 1]
    x1 = np.roll(x, -1)
    y1 = np.roll(y, -1)
    cross = x * y1 - x1 * y

    area = 0.5 * np.sum(cross)
    sx = np.sum((x + x1) * cross) / 6.0
    sy = np.sum((y + y1) * cross) / 6.0
    sxx = np.sum((x * x + x * x1 + x1 * x1) * cross) / 12.0
    syy = np.sum((y * y + y * y1 + y1 * y1) * cross) / 12.0
    sxy = np.sum((x * y1 + 2.0 * x * y + 2.0 * x1 * y1 + x1 * y) * cross) / 24.0

    return AreaMoments(
        float(area), float(sx), float(sy), float(sxx), float(syy), float(sxy)
    )


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
    lies entirely outside the half-plane. ``eps`` shifts the cut line outward
    by treating points with value ``>= -eps`` as inside; the default ``0.0``
    keeps points exactly on the line.
    """
    arr = _as_array(verts)
    n = arr.shape[0]
    if n == 0:
        return np.empty((0, 2), dtype=float)

    def value(p: np.ndarray) -> float:
        return a * p[0] + b * p[1] + c

    out: list[np.ndarray] = []
    for i in range(n):
        cur = arr[i]
        nxt = arr[(i + 1) % n]
        d_cur = value(cur)
        d_nxt = value(nxt)
        cur_in = d_cur >= -eps
        nxt_in = d_nxt >= -eps

        if cur_in:
            out.append(cur)
        if cur_in != nxt_in:
            # Edge crosses the line: add the intersection point. The
            # denominator cannot be zero here because the endpoints lie on
            # opposite sides, so d_cur != d_nxt.
            t = d_cur / (d_cur - d_nxt)
            out.append(cur + t * (nxt - cur))

    if not out:
        return np.empty((0, 2), dtype=float)
    return np.asarray(out, dtype=float)
