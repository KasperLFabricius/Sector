"""Torsional resistance from the thin-walled tube idealisation (EN 1992-1-1:2005
section 6.3).

A solid (or hollow) section is idealised as a thin-walled closed tube (6.3.2(1)):
the applied torsion ``TEd`` is carried by a constant shear flow ``TEd/(2*Ak)`` round
the walls, where ``Ak`` is the area enclosed by the wall centre-lines. The effective
wall thickness starts from ``tef = A/u`` (``A`` the total area within the outer
perimeter, including any hollow; ``u`` the outer perimeter), must also satisfy the
wall-specific lower bound ``tef >= 2a`` from the assigned longitudinal-bar centres,
and is capped at the real wall thickness for a hollow section. The centre-line is
the outer outline offset inward by ``tef/2``, so ``Ak`` and its perimeter ``uk``
follow from that offset polygon.

Resistances (variable strut angle ``theta``, shared with the shear check):

* Closed stirrups   ``TRd,s   = (Asw/s) * 2*Ak * fywd * cot(theta)``      (6.27 + 6.8)
* Concrete struts   ``TRd,max = 2*nu*alpha_cw*fcd*Ak*tef*sin*cos``        (6.30)
* Cracking          ``TRd,c   = 2*Ak*tef*fctd``                           (tau = fctd)
* Longitudinal steel required ``sum Asl = TEd*uk*cot(theta)/(2*Ak*fyd)``  (6.28)

The closed-stirrup expression follows the torsional wall shear flow in 6.27 and
the transverse-reinforcement equilibrium in 6.8. Formula 6.28 separately defines
the longitudinal torsion reinforcement.

The strut factor ``nu`` is the code's torsion effectiveness factor (recommended
``nu = 0.6(1 - fck/250)``; the DK NA:2024 ``nu_t = 0.7*(0.7 - fck/200)``, 5.104 NA).
The combined shear + torsion concrete-crushing check ``TEd/TRd,max + VEd/VRd,max <= 1``
(6.29) is assembled by the caller from this module's ``TRd,max`` and the shear
``VRd,max``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

from . import geometry


# Classification-only envelope for near-aligned corner rows.  Actual wall distances
# remain in the evidence, automatic selection uses their maximum 2a, and manual
# override limits retain the stricter floating-point tolerance below.
_CORNER_ALIGNMENT_RELATIVE_TOLERANCE = 2.0e-5


class TorsionWallThicknessError(ValueError):
    """A user-entered tube wall is thicker than the physical hollow wall."""


@dataclass(frozen=True, slots=True)
class SubtubeTorqueShare:
    """One accepted stiffness-proportional sub-tube torque share."""

    index: int
    stiffness: float
    fraction: float
    torque: float


@dataclass(frozen=True, slots=True)
class StiffnessDistributionResult:
    """Compact final state of a sub-tube stiffness distribution."""

    applied_torque: float
    positive_stiffness_sum: float
    shares: tuple[SubtubeTorqueShare, ...]

    @property
    def torque_parts(self) -> tuple[float, ...]:
        """Accepted torque carried by each input sub-tube, in input order."""

        return tuple(share.torque for share in self.shares)


@dataclass(frozen=True, slots=True)
class TorsionStirrupResult:
    """Operands and result of the existing closed-stirrup resistance formula."""

    ak_m2: float
    fywd_mpa: float
    asw_over_s: float
    cot: float
    two_ak_m2: float
    trd_s: float


@dataclass(frozen=True, slots=True)
class TorsionStrutResult:
    """Operands and result of the existing torsion strut-resistance formula."""

    fck_mpa: float
    fcd_mpa: float
    nu: float
    alpha_cw: float
    ak_m2: float
    tef_mm: float
    cot: float
    tan: float
    sin_cos: float
    closed_detailing: bool
    trd_max: float


@dataclass(frozen=True, slots=True)
class TorsionCrackingResult:
    """Operands and result of the existing torsional-cracking formula."""

    fctd_mpa: float
    ak_m2: float
    tef_mm: float
    trd_c: float


@dataclass(frozen=True, slots=True)
class TorsionLongitudinalResult:
    """Operands, direct interim terms and result of Formula (6.28)."""

    t_ed_knm: float
    uk_m: float
    ak_m2: float
    fyd_mpa: float
    cot: float
    numerator: float
    denominator: float
    asl_required_mm2: float


@dataclass(frozen=True, slots=True)
class TorsionResistanceSelection:
    """Final governing selection between the existing torsion resistances."""

    trd_s: float
    trd_max: float
    transverse_reinforcement: bool
    resistance: float
    governs: str


@dataclass(frozen=True, slots=True)
class FullTorsionResistanceSelection:
    """Fail-closed full resistance selected under current closed-link authority."""

    trd_s: float
    trd_max: float
    closed_links_present: bool
    asw_over_s: float
    full_resistance_assessed: bool
    resistance: Optional[float]
    governs: Optional[str]
    reason: Optional[str]


def _perimeter(ring: Sequence) -> float:
    """Closed-polygon perimeter (same length units as the vertices)."""
    n = len(ring)
    if n < 2:
        return 0.0
    return sum(math.dist(ring[i], ring[(i + 1) % n]) for i in range(n))


def minimum_caliper_width(ring: Sequence) -> float:
    """Return the rotation-invariant minimum projection width of a polygon.

    The minimum width of a convex polygon occurs normal to one of its edges.
    Sector's single-tube resistance is issued only for convex outlines; evaluating
    every edge normal therefore gives the physical least section dimension without
    tying it to the global x/y axes.  The same calculation remains conservative for
    the generated rectangular sub-tubes.
    """
    pts = [(float(point[0]), float(point[1])) for point in ring]
    if len(pts) < 3:
        return 0.0
    minimum = math.inf
    for index, point in enumerate(pts):
        next_point = pts[(index + 1) % len(pts)]
        dx = next_point[0] - point[0]
        dy = next_point[1] - point[1]
        length = math.hypot(dx, dy)
        if length <= 1.0e-12:
            continue
        nx, ny = -dy / length, dx / length
        projections = [x * nx + y * ny for x, y in pts]
        width = max(projections) - min(projections)
        if width > 1.0e-12:
            minimum = min(minimum, width)
    return 0.0 if not math.isfinite(minimum) else minimum


def _ensure_ccw(ring: Sequence):
    """Return the ring as a list oriented counter-clockwise (positive signed area)."""
    analysis_ring = geometry.ring_without_terminal_closure(ring)
    pts = [(float(p[0]), float(p[1])) for p in analysis_ring]
    if geometry.signed_area(pts) < 0.0:
        pts.reverse()
    return pts


def _finite_reinforcement_bar(bar: object) -> tuple[float, float, float] | None:
    """Return one strict longitudinal-bar record or ``None``.

    The torsion-wall applicability check consumes the actual point-table geometry,
    not a derived steel total.  Keep this boundary deliberately strict so Boolean,
    non-finite and incomplete coordinates cannot become wall-location evidence.
    """

    if type(bar) not in (tuple, list) or len(bar) != 3:
        return None
    values = []
    for value in bar:
        if (
            isinstance(value, (str, bytes))
            or type(value).__name__ in {"bool", "bool_"}
        ):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(number):
            return None
        values.append(number)
    if values[2] <= 0.0:
        return None
    return values[0], values[1], values[2]


def _point_segment_distance(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    """Distance formed in edge-local coordinates to retain translated precision."""

    dx, dy = end[0] - start[0], end[1] - start[1]
    rx, ry = point[0] - start[0], point[1] - start[1]
    length2 = dx * dx + dy * dy
    if length2 <= 0.0:
        return math.hypot(rx, ry)
    fraction = max(0.0, min(1.0, (rx * dx + ry * dy) / length2))
    return math.hypot(rx - fraction * dx, ry - fraction * dy)


def _point_in_wall_endpoint_zone(
    point: tuple[float, float],
    edge: tuple[tuple[float, float], tuple[float, float]],
    *,
    at_start: bool,
    zone: float,
    tolerance: float,
) -> bool:
    """Whether ``point`` belongs to one endpoint zone of a physical wall.

    Corner ownership is established in edge-local coordinates.  Both the distance
    along the wall from the shared endpoint and the perpendicular wall distance must
    lie inside the fixed geometry-derived zone.  This remains continuous when the
    two wall covers are almost, but not exactly, equal and does not turn an ordinary
    mid-wall bar into corner reinforcement.
    """

    endpoint = edge[0] if at_start else edge[1]
    opposite = edge[1] if at_start else edge[0]
    dx = opposite[0] - endpoint[0]
    dy = opposite[1] - endpoint[1]
    length = math.hypot(dx, dy)
    if length <= tolerance:
        return False
    rx = point[0] - endpoint[0]
    ry = point[1] - endpoint[1]
    along = (rx * dx + ry * dy) / length
    perpendicular = abs(rx * dy - ry * dx) / length
    return bool(
        -tolerance <= along <= zone + tolerance
        and perpendicular <= zone + tolerance
    )


def _canonical_wall_edges(
    ring: Sequence,
    tolerance: float,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Return physical walls, merging only representational collinear vertices."""

    points = _ensure_ccw(ring)
    if len(points) < 3:
        return []
    changed = True
    while changed and len(points) > 3:
        changed = False
        reduced = []
        count = len(points)
        for index, point in enumerate(points):
            previous = points[(index - 1) % count]
            following = points[(index + 1) % count]
            incoming = (point[0] - previous[0], point[1] - previous[1])
            outgoing = (following[0] - point[0], following[1] - point[1])
            incoming_length = math.hypot(*incoming)
            outgoing_length = math.hypot(*outgoing)
            cross = incoming[0] * outgoing[1] - incoming[1] * outgoing[0]
            same_direction = incoming[0] * outgoing[0] + incoming[1] * outgoing[1]
            collinear_tolerance = tolerance * max(
                incoming_length,
                outgoing_length,
                tolerance,
            )
            if (
                incoming_length > tolerance
                and outgoing_length > tolerance
                and abs(cross) <= collinear_tolerance
                and same_direction > 0.0
            ):
                changed = True
                continue
            reduced.append(point)
        if len(reduced) < 3:
            break
        points = reduced
    return [
        (points[index], points[(index + 1) % len(points)])
        for index in range(len(points))
    ]


def _circular_wall_geometry(
    ring: Sequence,
    tolerance: float,
) -> tuple[float, float, float] | None:
    """Identify a densely sampled circular physical wall.

    Quick Section represents circular and annular faces by regular polygons.  Those
    chords are analysis discretisation, not separate torsion walls.  Recognise only
    a sufficiently dense, tightly cyclic ring so ordinary polygon sides retain their
    independent wall identity.
    """

    points = _ensure_ccw(ring)
    if len(points) < 12:
        return None
    cx = sum(point[0] for point in points) / len(points)
    cy = sum(point[1] for point in points) / len(points)
    radii = [math.hypot(point[0] - cx, point[1] - cy) for point in points]
    radius = sum(radii) / len(radii)
    radial_tolerance = max(
        32.0 * tolerance,
        radius * 1.0e-10,
        32.0 * math.ulp(max(radius, 1.0)),
    )
    if radius <= radial_tolerance:
        return None
    if any(abs(value - radius) > radial_tolerance for value in radii):
        return None
    return cx, cy, radius


def _segment_clearance(
    first: tuple[tuple[float, float], tuple[float, float]],
    second: tuple[tuple[float, float], tuple[float, float]],
) -> float:
    """Minimum clearance between two non-crossing section-boundary segments."""

    return min(
        _point_segment_distance(first[0], *second),
        _point_segment_distance(first[1], *second),
        _point_segment_distance(second[0], *first),
        _point_segment_distance(second[1], *first),
    )


def _wall_evidence_invalid(base: dict, reason: str, evidence: dict) -> dict:
    """Remove authoritative tube quantities from one fail-closed selector result."""

    return dict(
        base,
        tef=0.0,
        Ak=0.0,
        uk=0.0,
        tef_capped=False,
        tef_user=bool(evidence.get("override_mm", 0.0) > 0.0),
        valid=False,
        reason=reason,
        tef_selection="none",
        centreline_method="none",
        wall_evidence=evidence,
        applicability_status="NOT ASSESSED",
    )


def tube_properties_with_reinforcement(
    outer: Sequence,
    holes: Optional[Sequence],
    longitudinal_bars: object,
    tef_override: float = 0.0,
    *,
    longitudinal_bar_positions: object = None,
) -> dict:
    """Select one clause-consistent tube from wall-specific bar locations.

    EN 1992-1-1 6.3.2(1) permits ``A/u`` only together with the lower bound
    ``t_eff,i >= 2*a_i`` and the real-wall upper bound for hollow sections.  Sector's
    current first-generation kernel has one scalar wall thickness, so automatic
    selection is assessed only when every physical wall resolves to that same scalar.
    A positive override is accepted only when it lies in every wall's interval.
    """

    base = tube_properties(outer, holes, tef_override=0.0)
    if not base.get("valid"):
        return base
    topology = geometry.validate_section_topology(outer, holes or [])
    topology.require_valid()
    if (
        isinstance(tef_override, (str, bytes))
        or type(tef_override).__name__ in {"bool", "bool_"}
    ):
        raise ValueError("tef override must be a finite non-negative real number (mm)")
    try:
        override_mm = float(tef_override)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(
            "tef override must be a finite non-negative real number (mm)"
        ) from exc
    if not math.isfinite(override_mm) or override_mm < 0.0:
        raise ValueError("tef override must be a finite non-negative real number (mm)")

    tolerance_m = max(
        topology.floating_point_tolerance,
        topology.length_tolerance,
        8.0 * math.ulp(max(topology.scale, 1.0)),
    )
    outer_walls = _canonical_wall_edges(outer, tolerance_m)
    circular_outer = _circular_wall_geometry(outer, tolerance_m)
    hole_walls = [
        edge
        for hole in (holes or [])
        for edge in _canonical_wall_edges(hole, tolerance_m)
    ]
    circular_real_wall_m = None
    if circular_outer is not None and holes:
        circular_hole = (
            _circular_wall_geometry(holes[0], tolerance_m)
            if len(holes) == 1
            else None
        )
        if circular_hole is not None:
            outer_cx, outer_cy, outer_radius = circular_outer
            hole_cx, hole_cy, hole_radius = circular_hole
            centre_tolerance = max(
                tolerance_m,
                32.0 * math.ulp(max(outer_radius, 1.0)),
            )
            if math.hypot(hole_cx - outer_cx, hole_cy - outer_cy) <= centre_tolerance:
                circular_real_wall_m = outer_radius - hole_radius
        if circular_real_wall_m is None and outer_walls and hole_walls:
            circular_real_wall_m = min(
                _segment_clearance(outer_edge, hole_edge)
                for outer_edge in outer_walls
                for hole_edge in hole_walls
            )
    evidence = {
        "complete": False,
        "reason": None,
        "a_over_u_mm": float(base["tef_auto"]),
        "override_mm": override_mm,
        "selected_tef_mm": None,
        "selection": "none",
        "walls": (),
    }
    if not geometry.polygon_is_convex(outer):
        evidence["reason"] = "compound outline requires subdivision"
        return _wall_evidence_invalid(base, evidence["reason"], evidence)
    physical_wall_count = 1 if circular_outer is not None else len(outer_walls)
    if physical_wall_count == 0:
        evidence["reason"] = "torsion wall reinforcement mapping is incomplete"
        return _wall_evidence_invalid(base, evidence["reason"], evidence)
    if type(longitudinal_bars) not in (tuple, list):
        evidence["reason"] = "torsion wall reinforcement locations are missing"
        return _wall_evidence_invalid(base, evidence["reason"], evidence)
    if longitudinal_bar_positions is None:
        bar_positions = tuple(range(1, len(longitudinal_bars) + 1))
    elif (
        type(longitudinal_bar_positions) not in (tuple, list)
        or len(longitudinal_bar_positions) != len(longitudinal_bars)
        or any(
            type(value) is not int or value <= 0
            for value in longitudinal_bar_positions
        )
        or len(set(longitudinal_bar_positions)) != len(longitudinal_bar_positions)
    ):
        evidence["reason"] = "torsion wall reinforcement locations are invalid"
        return _wall_evidence_invalid(base, evidence["reason"], evidence)
    else:
        bar_positions = tuple(longitudinal_bar_positions)
    bars = []
    for bar_position, item in zip(bar_positions, longitudinal_bars):
        bar = _finite_reinforcement_bar(item)
        if bar is None:
            evidence["reason"] = "torsion wall reinforcement locations are invalid"
            return _wall_evidence_invalid(base, evidence["reason"], evidence)
        bars.append((bar_position, bar))
    if not bars:
        evidence["reason"] = "torsion wall reinforcement locations are missing"
        return _wall_evidence_invalid(base, evidence["reason"], evidence)
    inside = geometry.points_inside_concrete(
        [bar for _index, bar in bars],
        outer,
        holes or [],
        tol=tolerance_m,
    )
    if not all(bool(value) for value in inside):
        evidence["reason"] = "torsion wall reinforcement locations are invalid"
        return _wall_evidence_invalid(base, evidence["reason"], evidence)

    assignments: list[list[tuple[int, float]]] = [
        [] for _wall in range(physical_wall_count)
    ]
    corner_zone_m = float(base["tef_auto"]) / 1000.0
    corner_tolerance = max(
        tolerance_m,
        8.0 * math.ulp(max(corner_zone_m, 1.0)),
    )
    corner_alignment_tolerance = max(
        corner_tolerance,
        _CORNER_ALIGNMENT_RELATIVE_TOLERANCE * corner_zone_m,
    )
    distance_records = []
    for bar_position, (x, y, _area) in bars:
        if circular_outer is not None:
            cx, cy, radius = circular_outer
            distances = [radius - math.hypot(x - cx, y - cy)]
        else:
            distances = [
                _point_segment_distance((x, y), start, end)
                for start, end in outer_walls
            ]
        minimum = min(distances)
        equality_tolerance = max(
            tolerance_m,
            8.0 * math.ulp(max(minimum, 1.0)),
        )
        nearest = [
            index
            for index, distance in enumerate(distances)
            if abs(distance - minimum) <= equality_tolerance
        ]
        corner_pairs = []
        point = (x, y)
        if physical_wall_count > 1:
            for following in range(physical_wall_count):
                previous = (following - 1) % physical_wall_count
                if not (
                    _point_in_wall_endpoint_zone(
                        point,
                        outer_walls[previous],
                        at_start=False,
                        zone=corner_zone_m,
                        tolerance=corner_tolerance,
                    )
                    and _point_in_wall_endpoint_zone(
                        point,
                        outer_walls[following],
                        at_start=True,
                        zone=corner_zone_m,
                        tolerance=corner_tolerance,
                    )
                ):
                    continue
                pair = (previous, following)
                if any(index in pair for index in nearest):
                    endpoint = outer_walls[following][0]
                    corner_pairs.append(
                        (pair, math.hypot(x - endpoint[0], y - endpoint[1]))
                    )
        distance_records.append(
            (bar_position, distances, tuple(nearest), tuple(corner_pairs))
        )

    corner_minimum_distance: dict[tuple[int, int], float] = {}
    for _position, _distances, _nearest, corner_pairs in distance_records:
        for pair, endpoint_distance in corner_pairs:
            corner_minimum_distance[pair] = min(
                endpoint_distance,
                corner_minimum_distance.get(pair, math.inf),
            )

    for bar_position, distances, nearest, corner_pairs in distance_records:
        # A genuinely aligned corner belongs to both adjoining walls even when
        # endpoint thinning retains another row closer to the shared endpoint.
        aligned_corner_pairs = [
            pair
            for pair, _endpoint_distance in corner_pairs
            if abs(distances[pair[0]] - distances[pair[1]])
            <= corner_alignment_tolerance
        ]
        retained_pairs = [
            pair
            for pair, endpoint_distance in corner_pairs
            if endpoint_distance
            <= corner_minimum_distance[pair] + corner_tolerance
        ]
        if physical_wall_count == 1:
            assigned_walls = (0,)
        elif len(aligned_corner_pairs) > 1:
            evidence["reason"] = "torsion wall reinforcement mapping is ambiguous"
            return _wall_evidence_invalid(base, evidence["reason"], evidence)
        elif aligned_corner_pairs:
            assigned_walls = aligned_corner_pairs[0]
            if any(index not in assigned_walls for index in nearest):
                evidence["reason"] = "torsion wall reinforcement mapping is ambiguous"
                return _wall_evidence_invalid(base, evidence["reason"], evidence)
        elif len(retained_pairs) > 1:
            evidence["reason"] = "torsion wall reinforcement mapping is ambiguous"
            return _wall_evidence_invalid(base, evidence["reason"], evidence)
        elif retained_pairs:
            assigned_walls = retained_pairs[0]
            if any(index not in assigned_walls for index in nearest):
                evidence["reason"] = "torsion wall reinforcement mapping is ambiguous"
                return _wall_evidence_invalid(base, evidence["reason"], evidence)
        elif len(nearest) == 1:
            assigned_walls = (nearest[0],)
        else:
            evidence["reason"] = "torsion wall reinforcement mapping is ambiguous"
            return _wall_evidence_invalid(base, evidence["reason"], evidence)
        for wall_index in assigned_walls:
            assignments[wall_index].append((bar_position, distances[wall_index]))

    wall_records = []
    automatic_values = []
    for wall_index, assigned in enumerate(assignments):
        edge = None if circular_outer is not None else outer_walls[wall_index]
        if not assigned:
            evidence["reason"] = "torsion wall reinforcement mapping is incomplete"
            evidence["walls"] = tuple(wall_records)
            return _wall_evidence_invalid(base, evidence["reason"], evidence)
        assigned = sorted(assigned, key=lambda item: item[0])
        distances_mm = tuple(distance * 1000.0 for _index, distance in assigned)
        a_mm = max(distances_mm)
        lower_mm = 2.0 * a_mm
        upper_mm = None
        if circular_outer is not None and circular_real_wall_m is not None:
            upper_mm = circular_real_wall_m * 1000.0
        elif hole_walls and edge is not None:
            upper_mm = min(
                _segment_clearance(edge, hole_edge) for hole_edge in hole_walls
            ) * 1000.0
        comparison_tolerance_mm = max(
            tolerance_m * 1000.0,
            8.0 * math.ulp(max(lower_mm, upper_mm or 0.0, 1.0)),
        )
        if upper_mm is not None and lower_mm > upper_mm + comparison_tolerance_mm:
            wall_records.append({
                "wall": wall_index + 1,
                "start_m": None if edge is None else edge[0],
                "end_m": None if edge is None else edge[1],
                "bar_indices": tuple(index for index, _distance in assigned),
                "bar_distances_mm": distances_mm,
                "a_mm": a_mm,
                "lower_bound_mm": lower_mm,
                "real_wall_mm": upper_mm,
                "automatic_tef_mm": None,
                "automatic_sources": (),
            })
            evidence["reason"] = "torsion wall lower bound exceeds real wall"
            evidence["walls"] = tuple(wall_records)
            return _wall_evidence_invalid(base, evidence["reason"], evidence)
        automatic_mm = max(float(base["tef_auto"]), lower_mm)
        if upper_mm is not None:
            automatic_mm = min(automatic_mm, upper_mm)
        sources = []
        if abs(automatic_mm - float(base["tef_auto"])) <= comparison_tolerance_mm:
            sources.append("A/u")
        if abs(automatic_mm - lower_mm) <= comparison_tolerance_mm:
            sources.append("longitudinal reinforcement lower bound")
        if upper_mm is not None and abs(automatic_mm - upper_mm) <= comparison_tolerance_mm:
            sources.append("real-wall limit")
        wall_records.append({
            "wall": wall_index + 1,
            "start_m": None if edge is None else edge[0],
            "end_m": None if edge is None else edge[1],
            "bar_indices": tuple(index for index, _distance in assigned),
            "bar_distances_mm": distances_mm,
            "a_mm": a_mm,
            "lower_bound_mm": lower_mm,
            "real_wall_mm": upper_mm,
            "automatic_tef_mm": automatic_mm,
            "automatic_sources": tuple(sources),
        })
        automatic_values.append(automatic_mm)

    evidence["walls"] = tuple(wall_records)
    interval_tolerance_mm = max(
        tolerance_m * 1000.0,
        8.0 * math.ulp(max([1.0, override_mm, *automatic_values])),
    )
    automatic_alignment_tolerance_mm = max(
        interval_tolerance_mm,
        2.0 * corner_alignment_tolerance * 1000.0,
    )
    if override_mm > 0.0:
        if any(
            override_mm < wall["lower_bound_mm"] - interval_tolerance_mm
            for wall in wall_records
        ):
            evidence["reason"] = "torsion wall override is below reinforcement lower bound"
            return _wall_evidence_invalid(base, evidence["reason"], evidence)
        if any(
            wall["real_wall_mm"] is not None
            and override_mm > wall["real_wall_mm"] + interval_tolerance_mm
            for wall in wall_records
        ):
            evidence["reason"] = "torsion wall override exceeds real wall"
            return _wall_evidence_invalid(base, evidence["reason"], evidence)
        selected_mm = override_mm
        selection = "user override"
    else:
        selected_mm = max(automatic_values)
        if any(
            selected_mm - value > automatic_alignment_tolerance_mm
            for value in automatic_values
        ) or any(
            wall["real_wall_mm"] is not None
            and selected_mm > wall["real_wall_mm"] + interval_tolerance_mm
            for wall in wall_records
        ):
            evidence["reason"] = "torsion wall automatic thickness varies by wall"
            return _wall_evidence_invalid(base, evidence["reason"], evidence)
        source_union = {
            source
            for wall in wall_records
            for source in wall["automatic_sources"]
        }
        source_labels = {
            "A/u": "A/u",
            "longitudinal reinforcement lower bound": (
                "reinforcement lower bound"
            ),
            "real-wall limit": "real-wall cap",
        }
        selection = " and ".join(
            source_labels[source]
            for source in (
                "A/u",
                "longitudinal reinforcement lower bound",
                "real-wall limit",
            )
            if source in source_union
        ) or "A/u"

    selected = tube_properties(outer, holes, tef_override=selected_mm)
    evidence.update({
        "complete": True,
        "reason": None,
        "selected_tef_mm": selected_mm,
        "selection": selection,
    })
    selected.update({
        "tef_auto": base["tef_auto"],
        "tef_capped": bool(selected_mm < float(base["tef_auto"]) - interval_tolerance_mm),
        "tef_user": bool(override_mm > 0.0),
        "tef_selection": selection,
        "wall_evidence": evidence,
        "applicability_status": "ASSESSED",
    })
    return selected


def _line_intersect(a, b):
    """Intersection of two lines given as ``(px, py, ux, uy)`` (point + unit dir)."""
    px0, py0, ux0, uy0 = a
    px1, py1, ux1, uy1 = b
    den = ux0 * uy1 - uy0 * ux1
    if abs(den) < 1.0e-12:
        return None                       # parallel (collinear consecutive edges)
    t = ((px1 - px0) * uy1 - (py1 - py0) * ux1) / den
    return (px0 + t * ux0, py0 + t * uy0)


def offset_polygon_inward(ring: Sequence, dist: float):
    """The polygon offset inward (toward the interior) by ``dist`` (miter offset).

    Each edge is moved ``dist`` along its inward normal and consecutive offset edge
    lines are intersected for the new vertices. Returns the offset ring, or ``None``
    when it degenerates (a collinear pair, or the offset eats the section).
    """
    pts = _ensure_ccw(ring)
    n = len(pts)
    if n < 3 or dist <= 0.0:
        return list(pts) if dist == 0.0 else None
    lines = []
    for i in range(n):
        p, q = pts[i], pts[(i + 1) % n]
        dx, dy = q[0] - p[0], q[1] - p[1]
        length = math.hypot(dx, dy)
        if length < 1.0e-12:
            return None
        ux, uy = dx / length, dy / length
        nx, ny = -uy, ux                  # inward (left) normal for a CCW ring
        lines.append((p[0] + nx * dist, p[1] + ny * dist, ux, uy))
    out = []
    for j in range(n):
        v = _line_intersect(lines[(j - 1) % n], lines[j])
        if v is None:
            # The two offset lines are parallel: the original edges are collinear (an
            # extra vertex on a straight edge). The offset of that shared vertex is the
            # vertex itself moved inward along the common edge normal.
            px, py = pts[j]
            _ox, _oy, ux, uy = lines[j]
            v = (px - uy * dist, py + ux * dist)     # inward (left) normal offset
        out.append(v)
    return out


def tube_properties(outer: Sequence, holes: Optional[Sequence],
                    tef_override: float = 0.0) -> dict:
    """Thin-walled tube idealisation of the section (metres in, mm out for lengths).

    Returns ``A`` (m2), ``u`` (m), ``tef`` (mm), ``Ak`` (m2), ``uk`` (m) plus the
    auto ``tef`` and whether it was capped/overridden. ``A`` is the area within the
    outer outline *including* any hollow (6.3.2(1)); for a hollow section ``tef`` is
    capped at the nearest measured real wall thickness. ``tef_override`` (mm,
    0 = auto) selects an explicit wall thickness; a supported single-cell hollow
    override above the nearest real wall is rejected before any resistance is
    evaluated.
    """
    topology = geometry.validate_section_topology(outer, holes or [])
    topology.require_valid()
    if (
        isinstance(tef_override, (str, bytes))
        or type(tef_override).__name__ in {"bool", "bool_"}
    ):
        raise ValueError("tef override must be a finite non-negative real number (mm)")
    try:
        tef_override_mm = float(tef_override)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(
            "tef override must be a finite non-negative real number (mm)"
        ) from exc
    if not math.isfinite(tef_override_mm) or tef_override_mm < 0.0:
        raise ValueError("tef override must be a finite non-negative real number (mm)")
    minimum_dimension_mm = minimum_caliper_width(outer) * 1000.0 if outer else 0.0
    if not outer or len(outer) < 3:
        return dict(A=0.0, u=0.0, tef=0.0, Ak=0.0, uk=0.0, tef_auto=0.0,
                    tef_capped=False, tef_user=False, hollow=bool(holes),
                    minimum_dimension_mm=minimum_dimension_mm,
                    valid=False, reason="no outline", tef_selection="none",
                    centreline_method="none")
    # The single-tube idealisation models a solid section or a single-cell hollow box;
    # a multi-cell section (two or more voids) needs sub-division into separate tubes
    # (6.3.2(1)), which is not implemented, so reject it rather than report an
    # unconservative single-tube TRd. Relating a user override to internal multi-cell
    # walls likewise needs that separate sub-tube mechanics contract; do not infer it
    # from the single-cell nearest-wall rule here.
    if holes and len(holes) > 1:
        return dict(A=0.0, u=0.0, tef=0.0, Ak=0.0, uk=0.0, tef_auto=0.0,
                    tef_capped=False, tef_user=False, hollow=True,
                    minimum_dimension_mm=minimum_dimension_mm,
                    valid=False, reason="multi-cell (2+ voids)",
                    tef_selection="none", centreline_method="none")
    A = abs(geometry.signed_area(outer))            # outer area incl. hollow, m2
    u = _perimeter(outer)                            # outer perimeter, m
    if A <= 0.0 or u <= 0.0:
        return dict(A=A, u=u, tef=0.0, Ak=0.0, uk=0.0, tef_auto=0.0,
                    tef_capped=False, tef_user=False, hollow=bool(holes),
                    minimum_dimension_mm=minimum_dimension_mm,
                    valid=False, reason="degenerate outline",
                    tef_selection="none", centreline_method="none")
    tef_auto = A / u                                 # m
    hollow = bool(holes)
    tef = tef_auto
    tef_capped = False
    if hollow:
        # EC2 caps tef at the real wall thickness for a hollow section. Measure it
        # directly as the minimum gap between the outer outline and any void: the
        # closest approach of two convex polygons is a vertex of one to an edge of the
        # other, so check every void vertex against the outer edges and every outer
        # vertex against each void's edges (distance_to_boundary is point-to-edge).
        walls = []
        for h in holes:
            walls += [geometry.distance_to_boundary(p[0], p[1], [outer]) for p in h]
            walls += [geometry.distance_to_boundary(p[0], p[1], [h]) for p in outer]
        wall = min(walls) if walls else tef_auto
        if wall < tef:
            tef, tef_capped = wall, True
    tef_user = tef_override_mm > 0.0
    if tef_user:
        tef_override_m = tef_override_mm / 1000.0    # mm -> m
        wall_equality_tolerance = max(
            topology.floating_point_tolerance,
            math.ulp(wall) if hollow else 0.0,
            math.ulp(tef_override_m),
        )
        if hollow and tef_override_m > wall + wall_equality_tolerance:
            raise TorsionWallThicknessError(
                f"tef override {tef_override_mm:.12g} mm exceeds the nearest real "
                f"wall thickness {wall * 1000.0:.12g} mm"
            )
        # Only representation-scale slack is an equality case. The topology policy's
        # relative section-scale tolerance is intentionally not used here: on a very
        # wide section it could otherwise admit a materially thicker physical wall.
        tef = min(tef_override_m, wall) if hollow else tef_override_m
    tef_selection = (
        "user override" if tef_user else "real-wall cap" if tef_capped else "A/u"
    )
    # Centre-line polygon: the outer outline offset inward by tef/2. The input is made
    # CCW inside offset_polygon_inward, so a valid inward offset stays CCW with a
    # *positive* signed area strictly smaller than A and a shorter perimeter. When tef
    # exceeds the section inradius the miter offset flips outside / self-intersects and
    # its signed area goes non-positive or its perimeter grows -- reject it (do NOT take
    # abs(), which would accept the inverted polygon) and fall back to a linear estimate.
    ring = offset_polygon_inward(outer, 0.5 * tef)
    a_ring = geometry.signed_area(ring) if ring else 0.0
    if ring and 0.0 < a_ring < A and _perimeter(ring) < u:
        Ak, uk = a_ring, _perimeter(ring)
        centreline_method = "inward offset"
    else:                                            # degenerate offset -> linear est.
        Ak = max(A - u * 0.5 * tef, 0.0)             # 0 when the wall eats the section
        uk = u * math.sqrt(Ak / A) if A > 0.0 else 0.0
        centreline_method = "linear estimate"
    return dict(A=A, u=u, tef=tef * 1000.0, Ak=Ak, uk=uk, tef_auto=tef_auto * 1000.0,
                tef_capped=tef_capped, tef_user=tef_user, hollow=hollow,
                minimum_dimension_mm=minimum_dimension_mm,
                valid=Ak > 0.0, reason=None if Ak > 0.0 else "wall exceeds section",
                tef_selection=tef_selection, centreline_method=centreline_method)


def rectangle_torsion_constant(b: float, h: float) -> float:
    """St. Venant torsion constant of a solid rectangle (length unit ^4).

    ``C = h*s^3 * (1/3 - 0.21*(s/h)*(1 - (s/h)^4/12))`` with ``s`` the short side and
    ``h`` the long side (the Roark / Timoshenko series approximation): ``C -> h*s^3/3``
    for a thin rectangle and ``0.141*a^4`` for a square. Used to split the applied torque
    over the sub-sections of a compound section in proportion to their uncracked
    torsional stiffness (EN 1992-1-1 6.3.1(4)); the shear modulus is common to every
    part and cancels in the share.
    """
    if b <= 0.0 or h <= 0.0:
        return 0.0
    s, lo = (b, h) if b <= h else (h, b)            # short side, long side
    r = s / lo
    return lo * s ** 3 * (1.0 / 3.0 - 0.21 * r * (1.0 - r ** 4 / 12.0))


def rectangle_ring(b: float, h: float):
    """A CCW rectangle outline (metres) centred at the origin.

    Position is irrelevant to the tube idealisation (``tef``, ``Ak``, ``uk`` depend only
    on the shape), so a sub-rectangle is fed to :func:`tube_properties` centred at the
    origin.
    """
    return [(-b / 2.0, -h / 2.0), (b / 2.0, -h / 2.0),
            (b / 2.0, h / 2.0), (-b / 2.0, h / 2.0)]


def stiffness_distribution_result(
    t_ed: float, constants
) -> StiffnessDistributionResult:
    """Return the accepted sub-tube shares and the retained distribution basis."""

    stiffnesses = tuple(float(c) for c in constants)
    total = sum(c for c in stiffnesses if c > 0.0)
    shares = tuple(
        SubtubeTorqueShare(
            index=i,
            stiffness=c,
            fraction=(c / total if c > 0.0 and total > 0.0 else 0.0),
            torque=(t_ed * c / total if c > 0.0 and total > 0.0 else 0.0),
        )
        for i, c in enumerate(stiffnesses)
    )
    return StiffnessDistributionResult(float(t_ed), total, shares)


def distribute_by_stiffness(t_ed: float, constants):
    """Split ``t_ed`` over sub-sections in proportion to torsional stiffness constants.

    ``TEd_i = t_ed * C_i / sum(C)`` (EN 1992-1-1 6.3.1(4)). A non-positive constant takes
    no share; if every constant is non-positive the whole torque is returned as zeros.
    """
    return list(stiffness_distribution_result(t_ed, constants).torque_parts)


def trd_s_result(
    ak_m2: float, fywd: float, asw_over_s: float, cot: float
) -> TorsionStirrupResult:
    """Return the retained operands and result of the existing stirrup formula."""

    two_ak = 2.0 * ak_m2
    value = asw_over_s * two_ak * fywd * cot
    return TorsionStirrupResult(ak_m2, fywd, asw_over_s, cot, two_ak, value)


def trd_s(ak_m2: float, fywd: float, asw_over_s: float, cot: float) -> float:
    """Torsion resistance governed by the closed stirrups (kN.m).

    ``TRd,s = (Asw/s) * 2*Ak * fywd * cot(theta)`` -- each wall carries the shear flow
    with transverse links, and the torque sums to ``2*Ak`` times the link tension.
    Units: ``(Asw/s)[mm2/mm] * Ak[m2] * fywd[MPa]`` already gives kN.m (the m2->mm2
    factor cancels N.mm->kN.m), so no scale factor is applied.
    """
    return trd_s_result(ak_m2, fywd, asw_over_s, cot).trd_s


def trd_max_result(
    fck: float,
    code,
    ak_m2: float,
    tef_mm: float,
    alpha_cw: float,
    cot: float,
    closed_detailing: bool = False,
    fcd_mpa: float | None = None,
) -> TorsionStrutResult:
    """Return retained operands and result of the existing strut formula."""

    fcd = (code.concrete_factor(fck) * fck / code.gamma_c
           if fcd_mpa is None else float(fcd_mpa))
    nu = code.torsion_nu(fck, closed_detailing=closed_detailing)
    tan = math.inf if cot == 0.0 else 1.0 / cot
    sin_cos = cot / (1.0 + cot * cot)
    value = (2.0 * nu * alpha_cw * fcd * ak_m2 * (tef_mm / 1000.0) * sin_cos
             * 1000.0)
    return TorsionStrutResult(
        fck, fcd, nu, alpha_cw, ak_m2, tef_mm, cot, tan, sin_cos,
        bool(closed_detailing), value,
    )


def trd_max(fck: float, code, ak_m2: float, tef_mm: float, alpha_cw: float,
            cot: float, closed_detailing: bool = False,
            fcd_mpa: float | None = None) -> float:
    """Torsion resistance limited by the concrete struts (kN.m), 6.30.

    ``TRd,max = 2*nu*alpha_cw*fcd*Ak*tef*sin(theta)*cos(theta)`` with
    ``sin*cos = cot/(1+cot^2)`` and ``nu`` the code torsion effectiveness factor.
    ``closed_detailing`` raises ``nu_t`` to ``nu_v`` under DK NA Figur 5.100 NA
    (closed stirrups round the periphery + distributed longitudinal steel).
    """
    return trd_max_result(
        fck, code, ak_m2, tef_mm, alpha_cw, cot,
        closed_detailing=closed_detailing, fcd_mpa=fcd_mpa,
    ).trd_max


def trd_c_result(fctd: float, ak_m2: float, tef_mm: float) -> TorsionCrackingResult:
    """Return retained operands and result of the existing cracking formula."""

    value = 2.0 * ak_m2 * (tef_mm / 1000.0) * fctd * 1000.0
    return TorsionCrackingResult(fctd, ak_m2, tef_mm, value)


def trd_c(fctd: float, ak_m2: float, tef_mm: float) -> float:
    """Torsional cracking moment (kN.m): ``TRd,c = 2*Ak*tef*fctd`` (tau_t = fctd)."""
    return trd_c_result(fctd, ak_m2, tef_mm).trd_c


def asl_required_result(
    t_ed: float, uk_m: float, ak_m2: float, fyd: float, cot: float
) -> TorsionLongitudinalResult:
    """Return retained operands and direct interim terms of Formula (6.28)."""

    numerator = t_ed * uk_m * cot
    denominator = 2.0 * ak_m2 * fyd
    value = (
        numerator / denominator * 1000.0
        if ak_m2 > 0.0 and fyd > 0.0
        else 0.0
    )
    return TorsionLongitudinalResult(
        t_ed, uk_m, ak_m2, fyd, cot, numerator, denominator, value
    )


def asl_required(t_ed: float, uk_m: float, ak_m2: float, fyd: float,
                 cot: float) -> float:
    """Longitudinal reinforcement required for torsion (mm2), 6.28.

    ``sum Asl = TEd * uk * cot(theta) / (2*Ak*fyd)``.
    """
    return asl_required_result(t_ed, uk_m, ak_m2, fyd, cot).asl_required_mm2


def select_torsion_resistance(
    trd_s_value: float, trd_max_value: float, *, asw_over_s: float
) -> TorsionResistanceSelection:
    """Retain the existing min/maximum branch and its governing identity."""

    with_stirrups = asw_over_s > 0.0
    if with_stirrups and trd_s_value <= trd_max_value:
        resistance = trd_s_value
        governs = "stirrups (TRd,s)"
    else:
        resistance = trd_max_value
        governs = "crushing (TRd,max)"
    return TorsionResistanceSelection(
        trd_s_value, trd_max_value, with_stirrups, resistance, governs
    )


def _nonnegative_finite_selection_operand(value: object, name: str) -> float:
    """Normalize one full-resistance operand without accepting Boolean or text."""

    if (
        type(value) is bool
        or type(value).__name__ == "bool_"
        or isinstance(value, (str, bytes))
    ):
        raise ValueError(f"{name} must be a finite non-negative real number")
    try:
        normalized = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(
            f"{name} must be a finite non-negative real number"
        ) from exc
    if not math.isfinite(normalized) or normalized < 0.0:
        raise ValueError(f"{name} must be a finite non-negative real number")
    return normalized


def select_full_torsion_resistance(
    trd_s_value: object,
    trd_max_value: object,
    *,
    closed_links_present: object,
    asw_over_s: object,
) -> FullTorsionResistanceSelection:
    """Select full torsion resistance only under explicit current link authority.

    ``TRd,max`` is the concrete-strut maximum, not a standalone torsion
    resistance. A full resistance therefore requires both an exact current
    closed-link authority and positive current transverse reinforcement.
    """

    if type(closed_links_present) is not bool:
        raise ValueError("closed_links_present must be a built-in Boolean")
    trd_s_value = _nonnegative_finite_selection_operand(trd_s_value, "trd_s")
    trd_max_value = _nonnegative_finite_selection_operand(
        trd_max_value, "trd_max"
    )
    asw_over_s = _nonnegative_finite_selection_operand(asw_over_s, "asw_over_s")

    if not closed_links_present:
        return FullTorsionResistanceSelection(
            trd_s=trd_s_value,
            trd_max=trd_max_value,
            closed_links_present=False,
            asw_over_s=asw_over_s,
            full_resistance_assessed=False,
            resistance=None,
            governs=None,
            reason="closed_links_not_present",
        )
    if asw_over_s == 0.0:
        return FullTorsionResistanceSelection(
            trd_s=trd_s_value,
            trd_max=trd_max_value,
            closed_links_present=True,
            asw_over_s=asw_over_s,
            full_resistance_assessed=False,
            resistance=None,
            governs=None,
            reason="closed_link_reinforcement_not_positive",
        )

    if trd_s_value <= trd_max_value:
        resistance = trd_s_value
        governs = "stirrups (TRd,s)"
    else:
        resistance = trd_max_value
        governs = "crushing (TRd,max)"
    return FullTorsionResistanceSelection(
        trd_s=trd_s_value,
        trd_max=trd_max_value,
        closed_links_present=True,
        asw_over_s=asw_over_s,
        full_resistance_assessed=True,
        resistance=resistance,
        governs=governs,
        reason=None,
    )
