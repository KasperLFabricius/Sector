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


@dataclass(frozen=True, slots=True)
class AreaMomentBreakdown:
    """Final section properties needed to publish the geometry calculation.

    ``ring_moments`` retains the signed contribution from each input ring in
    input order, while ``total`` is the authoritative net result from
    :func:`area_moments_rings`.  The centroidal fields use the same monomial
    naming as :class:`AreaMoments` and are transferred from the global origin
    with the parallel-axis relations.

    This is deliberately a compact final-state result.  It does not retain
    polygon edges or any calculation history.
    """

    ring_moments: tuple[AreaMoments, ...]
    total: AreaMoments
    centroid: tuple[float, float]
    centroidal_sxx: float
    centroidal_syy: float
    centroidal_sxy: float


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
    # Translate to a local origin before forming cross products. Polygon area is
    # translation invariant, while subtracting two O(origin^2) shoelace sums is
    # numerically fragile for a small section at a large project coordinate.
    x = arr[:, 0] - arr[0, 0]
    y = arr[:, 1] - arr[0, 1]
    x1 = np.roll(x, -1)
    y1 = np.roll(y, -1)
    return 0.5 * float(np.sum(x * y1 - x1 * y))


def ring_without_terminal_closure(verts: Vertices) -> np.ndarray:
    """Return an analysis copy without one exact terminal closure marker.

    A repeated final copy of the first point is accepted as a serialization
    convention. Removing it from calculation copies avoids a zero-length edge
    while leaving the caller's raw coordinates untouched.
    """
    arr = _as_array(verts)
    if len(arr) >= 2 and np.array_equal(arr[0], arr[-1]):
        return arr[:-1].copy()
    return arr.copy()


@dataclass(frozen=True)
class TopologyTolerance:
    """Scale-aware tolerance policy for section-topology validation.

    ``relative_length`` is resolved against the largest section bounding-box
    dimension. ``absolute_length`` is a floor in Sector's model units (metres).
    ``coordinate_ulp_multiplier`` adds a conservative floating-point envelope
    at the largest coordinate magnitude, so translating the same small section
    to project coordinates cannot turn exact contact into a false clearance.
    The resolved length tolerance is used only to classify
    coincident/touching topology; it never alters coordinates or calculation
    geometry. The area tolerance is ``length_tolerance * section_scale`` (with
    the absolute floor squared for a zero-span input).
    """

    relative_length: float = 1.0e-9
    absolute_length: float = 1.0e-12
    coordinate_ulp_multiplier: float = 8.0

    def floating_point_allowance(self, coordinate_magnitude: float) -> float:
        """Roundoff envelope for predicates evaluated at project coordinates."""
        if (
            not math.isfinite(self.coordinate_ulp_multiplier)
            or self.coordinate_ulp_multiplier < 0.0
        ):
            raise ValueError(
                "coordinate ULP multiplier must be finite and non-negative"
            )
        if not math.isfinite(coordinate_magnitude) or coordinate_magnitude < 0.0:
            raise ValueError("coordinate magnitude must be finite and non-negative")
        return self.coordinate_ulp_multiplier * math.ulp(coordinate_magnitude)

    def resolved_length(
        self,
        scale: float,
        coordinate_magnitude: float = 0.0,
    ) -> float:
        if not math.isfinite(self.relative_length) or self.relative_length < 0.0:
            raise ValueError("relative topology tolerance must be finite and non-negative")
        if not math.isfinite(self.absolute_length) or self.absolute_length < 0.0:
            raise ValueError("absolute topology tolerance must be finite and non-negative")
        return max(
            self.absolute_length,
            self.relative_length * max(scale, 0.0),
            self.floating_point_allowance(coordinate_magnitude),
        )


DEFAULT_TOPOLOGY_TOLERANCE = TopologyTolerance()


@dataclass(frozen=True)
class TopologyIssue:
    """One blocking section-topology defect with an auditable location."""

    code: str
    message: str
    ring: str
    point: int | None = None
    edge: int | None = None
    other_ring: str | None = None
    other_edge: int | None = None


@dataclass(frozen=True)
class TopologyValidation:
    """Result of the canonical section-topology validator."""

    issues: tuple[TopologyIssue, ...]
    scale: float
    length_tolerance: float
    area_tolerance: float
    floating_point_tolerance: float = 0.0

    @property
    def valid(self) -> bool:
        return not self.issues

    @property
    def message(self) -> str:
        return "; ".join(issue.message for issue in self.issues)

    def require_valid(self) -> None:
        if not self.valid:
            raise GeometryTopologyError(self)


class GeometryTopologyError(ValueError):
    """Raised before analysis when a section has invalid polygon topology."""

    def __init__(self, validation: TopologyValidation):
        self.validation = validation
        super().__init__(validation.message)


def _ring_label(index: int) -> str:
    return "outer ring" if index == 0 else f"hole {index}"


def _edge_label(index: int, count: int) -> str:
    return (
        f"edge {index + 1} "
        f"(point {index + 1} to point {(index + 1) % count + 1})"
    )


def _topology_scale(arrays: Sequence[np.ndarray]) -> float:
    finite = [arr[np.isfinite(arr).all(axis=1)] for arr in arrays if arr.ndim == 2]
    finite = [arr for arr in finite if len(arr)]
    if not finite:
        return 0.0
    points = np.vstack(finite)
    return max(
        float(np.ptp(points[:, 0])),
        float(np.ptp(points[:, 1])),
    )


def _topology_coordinate_magnitude(arrays: Sequence[np.ndarray]) -> float:
    """Largest finite absolute coordinate used to resolve the ULP envelope."""
    finite = [arr[np.isfinite(arr)] for arr in arrays if arr.ndim == 2]
    finite = [values for values in finite if len(values)]
    if not finite:
        return 0.0
    return max(float(np.max(np.abs(values))) for values in finite)


def _point_segment_distance_xy(
    point: np.ndarray, start: np.ndarray, end: np.ndarray
) -> float:
    dx = end - start
    relative = point - start
    length2 = float(np.dot(dx, dx))
    if length2 <= 0.0:
        return float(np.linalg.norm(relative))
    fraction = float(np.dot(relative, dx) / length2)
    fraction = max(0.0, min(1.0, fraction))
    # Form the residual entirely in edge-local coordinates. Reconstructing a
    # projected global point and subtracting it from ``point`` loses low bits
    # when a small section is translated to a large project coordinate.
    return float(np.linalg.norm(relative - fraction * dx))


def _cross2(a: np.ndarray, b: np.ndarray) -> float:
    return float(a[0] * b[1] - a[1] * b[0])


def _segment_clearance(
    a0: np.ndarray,
    a1: np.ndarray,
    b0: np.ndarray,
    b1: np.ndarray,
    tolerance: float,
) -> float:
    """Minimum segment clearance, with crossings/touches reported as zero."""
    if (
        max(a0[0], a1[0]) + tolerance < min(b0[0], b1[0])
        or max(b0[0], b1[0]) + tolerance < min(a0[0], a1[0])
        or max(a0[1], a1[1]) + tolerance < min(b0[1], b1[1])
        or max(b0[1], b1[1]) + tolerance < min(a0[1], a1[1])
    ):
        return math.inf

    ab = a1 - a0
    cd = b1 - b0
    cross_a0 = _cross2(ab, b0 - a0)
    cross_a1 = _cross2(ab, b1 - a0)
    cross_b0 = _cross2(cd, a0 - b0)
    cross_b1 = _cross2(cd, a1 - b0)
    cross_tol_a = tolerance * max(float(np.linalg.norm(ab)), tolerance)
    cross_tol_b = tolerance * max(float(np.linalg.norm(cd)), tolerance)

    proper_crossing = (
        (cross_a0 < -cross_tol_a and cross_a1 > cross_tol_a)
        or (cross_a0 > cross_tol_a and cross_a1 < -cross_tol_a)
    ) and (
        (cross_b0 < -cross_tol_b and cross_b1 > cross_tol_b)
        or (cross_b0 > cross_tol_b and cross_b1 < -cross_tol_b)
    )
    if proper_crossing:
        return 0.0

    return min(
        _point_segment_distance_xy(a0, b0, b1),
        _point_segment_distance_xy(a1, b0, b1),
        _point_segment_distance_xy(b0, a0, a1),
        _point_segment_distance_xy(b1, a0, a1),
    )


def _strictly_inside(point: np.ndarray, polygon: np.ndarray) -> bool:
    return bool(
        _points_in_polygon(
            np.asarray([point[0]], dtype=float),
            np.asarray([point[1]], dtype=float),
            polygon,
        )[0]
    )


def validate_section_topology(
    outer: Vertices,
    holes: Iterable[Vertices] = (),
    *,
    tolerance: TopologyTolerance = DEFAULT_TOPOLOGY_TOLERANCE,
) -> TopologyValidation:
    """Validate one outer polygon and zero or more void rings before analysis.

    This is Sector's canonical topology gate. It rejects:

    * malformed, non-finite, short, repeated, or zero-area rings;
    * self-crossing, self-touching, overlapping, or backtracking ring edges;
    * holes outside, touching, or crossing the outer boundary; and
    * holes that touch, cross, overlap, or nest inside one another.

    Concave simple polygons and intentional intermediate collinear points remain
    valid. One terminal point exactly equal to the first is accepted as a common
    serialisation closure marker and ignored only for topology classification;
    near-duplicate closure points remain invalid under the tolerance policy.
    Ring winding is a representation convention, not topology, and is normalised
    separately by :meth:`sector.section.Section.integration_rings`. The validator
    returns the first causal defect so UI/API messages name the relevant one-based
    ring point and/or edge without overwhelming the user.
    """
    raw_rings = [outer, *list(holes)]
    arrays: list[np.ndarray] = []
    for index, ring in enumerate(raw_rings):
        label = _ring_label(index)
        try:
            arr = np.asarray(ring, dtype=float)
        except (TypeError, ValueError) as exc:
            issue = TopologyIssue(
                "malformed-ring",
                f"{label} is not a numeric (N, 2) sequence of points",
                label,
            )
            return TopologyValidation((issue,), 0.0, 0.0, 0.0)
        if arr.ndim != 2 or arr.shape[1:] != (2,):
            issue = TopologyIssue(
                "malformed-ring",
                f"{label} must be an (N, 2) sequence of (x, y) points",
                label,
            )
            return TopologyValidation((issue,), 0.0, 0.0, 0.0)
        arrays.append(arr)

    scale = _topology_scale(arrays)
    coordinate_magnitude = _topology_coordinate_magnitude(arrays)
    floating_point_tol = tolerance.floating_point_allowance(coordinate_magnitude)
    length_tol = tolerance.resolved_length(scale, coordinate_magnitude)
    area_tol = max(tolerance.absolute_length ** 2, length_tol * max(scale, length_tol))
    arrays = [ring_without_terminal_closure(arr) for arr in arrays]

    def invalid(issue: TopologyIssue) -> TopologyValidation:
        return TopologyValidation(
            (issue,),
            scale,
            length_tol,
            area_tol,
            floating_point_tol,
        )

    # Shape and finiteness must be established before translating predicate
    # copies to a local origin.
    for index, arr in enumerate(arrays):
        label = _ring_label(index)
        count = len(arr)
        if count < 3:
            return invalid(TopologyIssue(
                "too-few-points",
                f"{label} has {count} points; at least 3 are required",
                label,
            ))
        nonfinite = np.argwhere(~np.isfinite(arr))
        if len(nonfinite):
            point_index = int(nonfinite[0, 0])
            return invalid(TopologyIssue(
                "non-finite-point",
                f"{label} point {point_index + 1} contains a non-finite coordinate",
                label,
                point=point_index + 1,
            ))

    # All topology predicates operate on copies translated by one common
    # section origin. This preserves relative geometry and raw point identity
    # while avoiding global-coordinate cancellation in cross products,
    # projections, bounding boxes, and the containment ray cast.
    origin = arrays[0][0].copy()
    arrays = [arr - origin for arr in arrays]

    for index, arr in enumerate(arrays):
        label = _ring_label(index)
        count = len(arr)
        for first in range(count):
            for second in range(first + 1, count):
                if float(np.linalg.norm(arr[first] - arr[second])) <= length_tol:
                    edge_index = first if second == (first + 1) % count else None
                    if first == 0 and second == count - 1:
                        edge_index = count - 1
                    location = (
                        f"{_edge_label(edge_index, count)} has coincident endpoints"
                        if edge_index is not None
                        else f"points {first + 1} and {second + 1} are repeated"
                    )
                    return invalid(TopologyIssue(
                        "repeated-point",
                        f"{label} {location} within the topology tolerance "
                        f"({length_tol:.3g} model units)",
                        label,
                        point=first + 1,
                        edge=(edge_index + 1 if edge_index is not None else None),
                    ))

        area = signed_area(arr)
        if abs(area) <= area_tol:
            anchor = arr[0]
            distances = np.linalg.norm(arr - anchor, axis=1)
            farthest = arr[int(np.argmax(distances))]
            if all(
                _point_segment_distance_xy(point, anchor, farthest) <= length_tol
                for point in arr
            ):
                return invalid(TopologyIssue(
                    "degenerate-area",
                    f"{label} is degenerate or collinear: |area|={abs(area):.6g} "
                    f"is not greater than the topology area tolerance {area_tol:.6g}",
                    label,
                ))

        for vertex in range(count):
            previous = arr[vertex - 1]
            current = arr[vertex]
            following = arr[(vertex + 1) % count]
            incoming = current - previous
            outgoing = following - current
            cross = abs(_cross2(incoming, outgoing))
            collinear_tol = length_tol * max(
                float(np.linalg.norm(incoming)),
                float(np.linalg.norm(outgoing)),
                length_tol,
            )
            if cross <= collinear_tol and float(np.dot(incoming, outgoing)) < 0.0:
                return invalid(TopologyIssue(
                    "backtracking-edge",
                    f"{label} edges {vertex or count} and {vertex + 1} overlap or "
                    f"backtrack at point {vertex + 1}",
                    label,
                    point=vertex + 1,
                    edge=vertex + 1,
                ))

        for first in range(count):
            a0 = arr[first]
            a1 = arr[(first + 1) % count]
            for second in range(first + 1, count):
                if second == first + 1 or (first == 0 and second == count - 1):
                    continue
                b0 = arr[second]
                b1 = arr[(second + 1) % count]
                clearance = _segment_clearance(a0, a1, b0, b1, length_tol)
                if clearance <= length_tol:
                    return invalid(TopologyIssue(
                        "self-intersection",
                        f"{label} {_edge_label(first, count)} intersects or touches "
                        f"{_edge_label(second, count)} (clearance "
                        f"{clearance:.6g} <= tolerance {length_tol:.6g})",
                        label,
                        edge=first + 1,
                        other_ring=label,
                        other_edge=second + 1,
                    ))
        if abs(area) <= area_tol:
            return invalid(TopologyIssue(
                "degenerate-area",
                f"{label} has indeterminate orientation: |area|={abs(area):.6g} "
                f"is not greater than the topology area tolerance {area_tol:.6g}",
                label,
            ))

    outer_arr = arrays[0]
    outer_count = len(outer_arr)
    for hole_index, hole in enumerate(arrays[1:], start=1):
        hole_label = _ring_label(hole_index)
        hole_count = len(hole)
        for hole_edge in range(hole_count):
            h0 = hole[hole_edge]
            h1 = hole[(hole_edge + 1) % hole_count]
            for outer_edge in range(outer_count):
                o0 = outer_arr[outer_edge]
                o1 = outer_arr[(outer_edge + 1) % outer_count]
                clearance = _segment_clearance(h0, h1, o0, o1, length_tol)
                if clearance <= length_tol:
                    return invalid(TopologyIssue(
                        "hole-boundary-contact",
                        f"{hole_label} {_edge_label(hole_edge, hole_count)} touches "
                        f"or crosses outer ring {_edge_label(outer_edge, outer_count)} "
                        f"(clearance {clearance:.6g} <= tolerance "
                        f"{length_tol:.6g}); this invalid boundary contact can "
                        "create disconnected concrete",
                        hole_label,
                        edge=hole_edge + 1,
                        other_ring="outer ring",
                        other_edge=outer_edge + 1,
                    ))
        if not _strictly_inside(hole[0], outer_arr):
            return invalid(TopologyIssue(
                "hole-outside",
                f"{hole_label} is outside the outer ring (point 1 is not inside)",
                hole_label,
                point=1,
                other_ring="outer ring",
            ))

    for first_index, first_hole in enumerate(arrays[1:], start=1):
        first_label = _ring_label(first_index)
        first_count = len(first_hole)
        for second_index in range(first_index + 1, len(arrays)):
            second_hole = arrays[second_index]
            second_label = _ring_label(second_index)
            second_count = len(second_hole)
            for first_edge in range(first_count):
                a0 = first_hole[first_edge]
                a1 = first_hole[(first_edge + 1) % first_count]
                for second_edge in range(second_count):
                    b0 = second_hole[second_edge]
                    b1 = second_hole[(second_edge + 1) % second_count]
                    clearance = _segment_clearance(a0, a1, b0, b1, length_tol)
                    if clearance <= length_tol:
                        return invalid(TopologyIssue(
                            "hole-overlap",
                            f"{first_label} {_edge_label(first_edge, first_count)} "
                            f"touches or crosses {second_label} "
                            f"{_edge_label(second_edge, second_count)} (clearance "
                            f"{clearance:.6g} <= tolerance {length_tol:.6g})",
                            first_label,
                            edge=first_edge + 1,
                            other_ring=second_label,
                            other_edge=second_edge + 1,
                        ))
            if _strictly_inside(second_hole[0], first_hole):
                return invalid(TopologyIssue(
                    "nested-hole",
                    f"{second_label} is nested inside {first_label}; nested void "
                    "rings are not a valid concrete topology",
                    second_label,
                    point=1,
                    other_ring=first_label,
                ))
            if _strictly_inside(first_hole[0], second_hole):
                return invalid(TopologyIssue(
                    "nested-hole",
                    f"{first_label} is nested inside {second_label}; nested void "
                    "rings are not a valid concrete topology",
                    first_label,
                    point=1,
                    other_ring=second_label,
                ))

    return TopologyValidation(
        (),
        scale,
        length_tol,
        area_tol,
        floating_point_tol,
    )


def require_valid_section_topology(
    outer: Vertices,
    holes: Iterable[Vertices] = (),
    *,
    tolerance: TopologyTolerance = DEFAULT_TOPOLOGY_TOLERANCE,
) -> None:
    """Raise :class:`GeometryTopologyError` for invalid section topology."""
    validate_section_topology(outer, holes, tolerance=tolerance).require_valid()


def polygon_is_convex(verts: Vertices, tol: float = 1e-12) -> bool:
    """Whether a simple polygon has no re-entrant (concave) corner.

    Collinear edge points are ignored, so a rectangle with intermediate points
    remains convex. An exact terminal copy of the first point is a serialization
    marker, not a second corner, and is removed from this analysis copy. Fewer
    than three vertices and zero-area rings are not valid convex polygons.
    Sector uses this as a conservative compound-section screen: a concave
    T/L/I/flanged outline must be explicitly subdivided before the thin-walled
    torsion model may issue a resistance verdict.
    """
    arr = ring_without_terminal_closure(verts)
    n = arr.shape[0]
    area = signed_area(arr)
    if n < 3 or abs(area) <= tol:
        return False
    orientation = 1.0 if area > 0.0 else -1.0
    for i in range(n):
        a = arr[i - 1]
        b = arr[i]
        c = arr[(i + 1) % n]
        cross = ((b[0] - a[0]) * (c[1] - b[1])
                 - (b[1] - a[1]) * (c[0] - b[0]))
        if orientation * cross < -tol:
            return False
    return True


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


def area_moment_breakdown(rings: Iterable[Vertices]) -> AreaMomentBreakdown:
    """Return signed ring contributions and final net section properties.

    The established :func:`area_moments` and :func:`area_moments_rings`
    kernels remain the only source of polygon moments.  A zero-net-area set of
    rings has no defined centroid and therefore raises :class:`ValueError`,
    consistently with :attr:`AreaMoments.centroid`.
    """
    ring_list = tuple(rings)
    ring_moments = tuple(area_moments(ring) for ring in ring_list)
    total = area_moments_rings(ring_list)
    cx, cy = total.centroid
    return AreaMomentBreakdown(
        ring_moments=ring_moments,
        total=total,
        centroid=(cx, cy),
        centroidal_sxx=total.sxx - total.area * cx * cx,
        centroidal_syy=total.syy - total.area * cy * cy,
        centroidal_sxy=total.sxy - total.area * cx * cy,
    )


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


def points_inside_concrete(
    points: Iterable[Sequence[float]],
    outer: Vertices,
    holes: Iterable[Vertices] = (),
    tol: float = 1e-9,
) -> np.ndarray:
    """Boolean mask: whether each point lies in the concrete (inside ``outer`` and
    not inside any void in ``holes``).

    Used to reject reinforcement placed outside the section or buried in a void. A
    point within ``tol`` of a boundary edge counts as inside, so a bar sitting
    exactly on a concrete face (zero cover) or hard against a void edge is accepted;
    only steel clearly beyond the outline -- or strictly within a void -- is flagged.
    The boundary tolerance also sidesteps the ray-cast test's ambiguity for a point
    that happens to fall exactly on an edge.
    """
    pts = list(points)
    if not pts:
        return np.zeros(0, dtype=bool)
    px = np.array([float(p[0]) for p in pts])
    py = np.array([float(p[1]) for p in pts])
    outer_arr = _as_array(outer)
    if outer_arr.shape[0] < 3:
        return np.zeros(len(pts), dtype=bool)     # no outline -> nothing is "inside"
    inside = _points_in_polygon(px, py, outer_arr)
    on_outer = np.array(
        [distance_to_boundary(x, y, (outer_arr,)) <= tol for x, y in zip(px, py)]
    )
    inside |= on_outer                            # a point on the outer face is in
    for ring in holes:
        harr = _as_array(ring)
        if harr.shape[0] < 3:
            continue
        in_hole = _points_in_polygon(px, py, harr)
        on_hole = np.array(
            [distance_to_boundary(x, y, (harr,)) <= tol for x, y in zip(px, py)]
        )
        inside &= ~(in_hole & ~on_hole)           # strictly inside a void -> not in
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
    w, h = x1 - x0, y1 - y0
    if w <= 0.0 or h <= 0.0:
        return True                          # degenerate outline encloses no area
    # Resolve EACH axis to its own ``grid`` cells. Sizing both axes by the larger
    # dimension would collapse the short axis of a high-aspect section to a single
    # row, so a slot cutting across the short direction could fall between samples
    # and be missed; per-axis cells (anisotropic, which is fine for a connectivity
    # test) keep enough rows and columns either way.
    grid = 240
    nx = ny = grid
    # Sample at cell centres so the boundary is never sampled ambiguously.
    xs = x0 + (np.arange(nx) + 0.5) * w / nx
    ys = y0 + (np.arange(ny) + 0.5) * h / ny
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


def _clip_to_axis_aligned_rectangle(
    verts: Vertices, xmin: float, xmax: float, ymin: float, ymax: float
) -> np.ndarray:
    """Clip a polygon to an axis-aligned rectangle.

    Four exact half-plane clips are used rather than a sampling grid. The signed
    area of the result is therefore suitable for proving that a proposed torsion
    sub-rectangle lies wholly inside a concrete polygon.
    """
    clipped = clip_halfplane(verts, 1.0, 0.0, -xmin)   # x >= xmin
    clipped = clip_halfplane(clipped, -1.0, 0.0, xmax)  # x <= xmax
    clipped = clip_halfplane(clipped, 0.0, 1.0, -ymin)  # y >= ymin
    return clip_halfplane(clipped, 0.0, -1.0, ymax)     # y <= ymax


def rectangles_partition_concrete(
    outer: Vertices,
    holes: Iterable[Vertices],
    rectangles: Iterable[Sequence[float]],
    rel_tol: float = 1e-6,
) -> tuple[bool, str]:
    """Validate an axis-aligned rectangular partition of a concrete section.

    ``rectangles`` contains ``(centre_x, centre_y, width, height)`` in the same
    units as ``outer``. A valid partition satisfies three geometry-backed
    conditions:

    * every rectangle lies wholly inside the outer ring and outside every void;
    * rectangle interiors do not overlap (shared boundaries are allowed); and
    * the sum of their areas equals the concrete net area.

    Exact polygon/rectangle clipping supplies the containment areas. Together
    with the non-overlap and equal-area checks, containment proves that the
    rectangle union covers the concrete section (up to zero-area boundaries).
    The explanatory string is empty for a valid partition and suitable for the
    UI/report when invalid.
    """
    outer_arr = _as_array(outer)
    hole_arrs = [
        arr for arr in (_as_array(ring) for ring in holes)
        if arr.shape[0] >= 3
    ]
    raw_rects = list(rectangles)
    if outer_arr.shape[0] < 3 or abs(signed_area(outer_arr)) <= 0.0:
        return False, "the concrete outline is degenerate"
    if not raw_rects:
        return False, "no sub-rectangles are defined"

    net_area = abs(signed_area(outer_arr)) - sum(
        abs(signed_area(ring)) for ring in hole_arrs
    )
    if net_area <= 0.0:
        return False, "the concrete net area is zero"

    bounds: list[tuple[float, float, float, float, float]] = []
    for i, raw in enumerate(raw_rects):
        if len(raw) != 4:
            return False, f"sub-rectangle {i + 1} needs centre x/y, width and height"
        cx, cy, width, height = (float(v) for v in raw)
        if not all(math.isfinite(v) for v in (cx, cy, width, height)):
            return False, f"sub-rectangle {i + 1} contains a non-finite value"
        if width <= 0.0 or height <= 0.0:
            return False, f"sub-rectangle {i + 1} has a non-positive dimension"
        bounds.append((
            cx - width / 2.0,
            cx + width / 2.0,
            cy - height / 2.0,
            cy + height / 2.0,
            width * height,
        ))

    total_rect_area = sum(item[4] for item in bounds)
    area_scale = max(net_area, total_rect_area, 1e-12)
    area_tol = max(1e-12, abs(float(rel_tol)) * area_scale)

    for i, (xmin, xmax, ymin, ymax, rect_area) in enumerate(bounds):
        outer_part = _clip_to_axis_aligned_rectangle(
            outer_arr, xmin, xmax, ymin, ymax
        )
        contained_area = abs(signed_area(outer_part))
        for hole in hole_arrs:
            hole_part = _clip_to_axis_aligned_rectangle(
                hole, xmin, xmax, ymin, ymax
            )
            contained_area -= abs(signed_area(hole_part))
        missing = rect_area - max(0.0, contained_area)
        if missing > area_tol:
            return (
                False,
                f"sub-rectangle {i + 1} extends outside the concrete or into a void "
                f"by {missing * 1e6:.1f} mm2",
            )

    for i, a in enumerate(bounds):
        for j, b in enumerate(bounds[i + 1:], start=i + 1):
            overlap_w = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
            overlap_h = max(0.0, min(a[3], b[3]) - max(a[2], b[2]))
            overlap = overlap_w * overlap_h
            if overlap > area_tol:
                return (
                    False,
                    f"sub-rectangles {i + 1} and {j + 1} overlap by "
                    f"{overlap * 1e6:.1f} mm2",
                )

    area_difference = total_rect_area - net_area
    if abs(area_difference) > area_tol:
        relation = "exceeds" if area_difference > 0.0 else "is below"
        return (
            False,
            "the total sub-rectangle area "
            f"{relation} the concrete net area by "
            f"{abs(area_difference) * 1e6:.1f} mm2",
        )
    return True, ""


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
