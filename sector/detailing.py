"""Longitudinal and transverse reinforcement-detailing checks.

The functions in this module are independent of Streamlit.  They consume the
same explicit section and reinforcement records as the solvers and return plain
dictionaries suitable for the UI, report and project evidence.

The two Eurocode generations deliberately use different minimum-reinforcement
models:

* EN 1992-1-1:2004/2005, 9.2.1.1(1), Formula (9.1N), is an area check for the
  longitudinal tension reinforcement of a beam or slab strip.
* EN 1992-1-1:2023, 12.2(2), is a section-strength check.  The nominal moment
  resistance with reinforcement limited to characteristic yield is compared
  with the cracking moment in the presence of the case axial force.

Neither path applies hidden control-, construction- or consequence-category
factors.  The concrete law supplied by the caller contains the final effective
material factors selected by the user.

The transverse checks cover the minimum ratio and maximum link spacing for
vertical shear links and closed torsion links.  They deliberately consume plain
geometry records rather than a solver result, so the engineering rules remain
independently unit-testable and the UI/report can present the same evidence.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

import numpy as np

from . import combined, geometry
from .elastic import solve_elastic_uncracked
from .materials import MildSteel
from .plastic import FACE_ANGLE, plastic_capacity_at_angle, solve_plastic
from .section import Bar, Section


EC2_2005 = "EN 1992-1-1:2005"
EC2_2005_DKNA = "DS/EN 1992-1-1:2005 + DK NA:2024"
EC2_2023 = "DS/EN 1992-1-1:2023"
EDITIONS = (EC2_2005_DKNA, EC2_2005, EC2_2023)
MEMBER_BEAM = "Beam"
MEMBER_SLAB = "Slab"
MEMBER_TYPES = (MEMBER_BEAM, MEMBER_SLAB)
CUT_TRANSVERSE = "Transverse cut"
CUT_LONGITUDINAL = "Longitudinal cut"
CUT_DIRECTIONS = (CUT_TRANSVERSE, CUT_LONGITUDINAL)

_TOL = 1.0e-9


def _status(statuses: Sequence[str]) -> str:
    values = {str(value).upper() for value in statuses}
    for value in ("INVALID", "FAIL", "REVIEW", "NOT ASSESSED", "PASS"):
        if value in values:
            return value
    return "NOT ASSESSED"


def _moments(section: Section):
    return geometry.area_moments_rings(section.integration_rings())


def _centroid(section: Section) -> tuple[float, float]:
    moments = _moments(section)
    if moments.area <= 0.0:
        raise ValueError("section has no positive concrete area")
    return moments.centroid


def _coord(point, axis: str) -> float:
    if axis == "x":
        return float(point[1])
    if axis == "y":
        return float(point[0])
    raise ValueError("axis must be 'x' or 'y'")


def _face_name(axis: str, tension_low: bool) -> str:
    if axis == "x":
        return "bottom" if tension_low else "top"
    return "left" if tension_low else "right"


def _centroid_moments(
    section: Section,
    n_ed_tension_kn: float,
    mx_origin_knm: float,
    my_origin_knm: float,
) -> tuple[float, float]:
    """Actions about the concrete centroid, using Sector's public signs."""
    cx, cy = _centroid(section)
    # Sector exposes N as tension-positive while its engineering bending moments
    # are the negatives of the tension-positive internal first moments.  Moving
    # the reference point from the origin to (cx, cy) therefore adds N times the
    # offset: M_C = M_O + N_tension * c.
    return (
        float(mx_origin_knm) + float(n_ed_tension_kn) * cy,
        float(my_origin_knm) + float(n_ed_tension_kn) * cx,
    )


def tension_zone_mean_width(
    section: Section, axis: str, tension_low: bool
) -> tuple[float, float]:
    """Return ``(b_t, h_t)`` in mm for the gross-centroid tension half.

    ``b_t`` is the exact net concrete area on the selected side of the gross
    centroid divided by that side's depth.  This reproduces the width of a
    rectangle and the web width of a T-section when its flange is in compression,
    while retaining an auditable automatic value for polygonal sections.
    """
    section.require_valid_geometry()
    moments = _moments(section)
    if moments.area <= 0.0:
        return 0.0, 0.0
    cx, cy = moments.centroid
    cut = cy if axis == "x" else cx
    a, b = ((0.0, -1.0) if axis == "x" else (-1.0, 0.0)) if tension_low else (
        (0.0, 1.0) if axis == "x" else (1.0, 0.0)
    )
    # Keep coord <= cut for a low face, coord >= cut for a high face.
    c = cut if tension_low else -cut
    clipped_area = 0.0
    for ring in section.integration_rings():
        clipped = geometry.clip_halfplane(ring, a, b, c)
        clipped_area += geometry.area_moments(clipped).area
    coords = [_coord(point, axis) for point in section.concrete[0]]
    depth = cut - min(coords) if tension_low else max(coords) - cut
    if depth <= 0.0 or clipped_area <= 0.0:
        return 0.0, max(depth, 0.0) * 1000.0
    return clipped_area / depth * 1000.0, depth * 1000.0


def _resultant_tension_zone(
    section: Section,
    elements: Sequence[Mapping],
    materials: Sequence[MildSteel],
    mx_centroid_knm: float,
    my_centroid_knm: float,
) -> dict:
    """Derive the gross-concrete tension half-plane for resultant bending.

    The uncracked, concrete-only strain plane accounts for biaxial bending and
    product-of-inertia coupling.  Its zero-strain line defines the actual
    resultant tension zone; bars on a separate Cartesian face are not credited.
    """
    if len(elements) != len(section.bars) or len(materials) != len(section.bars):
        raise ValueError("one element record and material are required per bar")
    plain = Section([np.asarray(ring, dtype=float).copy()
                     for ring in section.concrete])
    bending = solve_elastic_uncracked(
        plain, 0.0, float(mx_centroid_knm), float(my_centroid_knm), 1.0
    )
    gradient = np.array([bending.kx, bending.ky], dtype=float)
    norm = float(np.linalg.norm(gradient))
    if not bending.converged or not math.isfinite(norm) or norm <= _TOL:
        return {
            "valid": False,
            "reason": "gross-concrete resultant tension plane could not be derived",
        }

    direction = gradient / norm
    neutral_c = float(bending.eps0) / norm
    vertices = section.concrete_vertices()
    signed_vertices = vertices @ direction + neutral_c
    tension_depth = float(np.max(signed_vertices))
    compression_extreme = float(np.min(signed_vertices))
    clipped_area = 0.0
    for ring in section.integration_rings():
        clipped = geometry.clip_halfplane(
            ring, float(direction[0]), float(direction[1]), neutral_c
        )
        clipped_area += geometry.area_moments(clipped).area

    indices = [
        index
        for index, bar in enumerate(section.bars)
        if (
            float(direction[0]) * bar.x
            + float(direction[1]) * bar.y
            + neutral_c
        ) > _TOL
    ]
    areas = [section.bars[index].area * 1.0e6 for index in indices]
    area = sum(areas)
    if area > 0.0:
        bar_level = sum(
            areas[position]
            * (
                float(direction[0]) * section.bars[index].x
                + float(direction[1]) * section.bars[index].y
                + neutral_c
            )
            for position, index in enumerate(indices)
        ) / area
        d_mm = (bar_level - compression_extreme) * 1000.0
    else:
        bar_level = None
        d_mm = 0.0
    bt_mm = (
        clipped_area / tension_depth * 1000.0
        if clipped_area > 0.0 and tension_depth > _TOL
        else 0.0
    )
    return {
        "valid": bool(
            clipped_area > 0.0
            and tension_depth > _TOL
            and compression_extreme < -_TOL
        ),
        "reason": None,
        "indices": indices,
        "bar_ids": [
            str(elements[index].get("id") or index + 1) for index in indices
        ],
        "material_ids": [
            str(elements[index].get("material_id") or "") for index in indices
        ],
        "fyk_values_mpa": [float(materials[index].fytk) for index in indices],
        "as_provided_mm2": area,
        "bar_level_m": bar_level,
        "bt_mm": bt_mm,
        "tension_zone_depth_mm": tension_depth * 1000.0,
        "d_mm": d_mm,
        "tension_direction": [float(direction[0]), float(direction[1])],
        "neutral_c_m": neutral_c,
        "neutral_point_m": [
            -neutral_c * float(direction[0]),
            -neutral_c * float(direction[1]),
        ],
    }


def minimum_reinforcement_2005(
    section: Section,
    elements: Sequence[Mapping],
    materials: Sequence[MildSteel],
    *,
    fctm_mpa: float,
    n_ed_tension_kn: float,
    mx_ed_knm: float,
    my_ed_knm: float,
    edition: str = EC2_2005,
) -> dict:
    """Check Formula (9.1N) in the resultant bending tension zone."""
    section.require_valid_geometry()
    if edition not in {EC2_2005, EC2_2005_DKNA}:
        raise ValueError("a 2005-family edition is required")
    mx_c, my_c = _centroid_moments(
        section, n_ed_tension_kn, mx_ed_knm, my_ed_knm
    )
    if math.hypot(mx_c, my_c) <= _TOL:
        rows = []
        status = "NOT ASSESSED"
        reason = (
            "Formula (9.1N) needs a bending tension face; the selected case has "
            "no moment about the concrete centroid"
        )
    else:
        zone = _resultant_tension_zone(
            section, elements, materials, mx_c, my_c
        )
        fyk = min(zone.get("fyk_values_mpa") or [], default=0.0)
        valid = bool(
            zone.get("valid")
            and zone.get("as_provided_mm2", 0.0) > 0.0
            and zone.get("d_mm", 0.0) > 0.0
            and zone.get("bt_mm", 0.0) > 0.0
            and fyk > 0.0
            and fctm_mpa > 0.0
        )
        as_min = (
            max(0.26 * float(fctm_mpa) / fyk, 0.0013)
            * float(zone["bt_mm"])
            * float(zone["d_mm"])
            if valid
            else None
        )
        utilisation = (
            as_min / float(zone["as_provided_mm2"])
            if as_min is not None and zone.get("as_provided_mm2", 0.0) > 0.0
            else math.inf
        )
        biaxial = abs(mx_c) > _TOL and abs(my_c) > _TOL
        if biaxial:
            axis = "xy"
            face_name = "resultant tension zone"
            tension_low = None
        else:
            axis = "x" if abs(mx_c) > _TOL else "y"
            direction_component = (
                zone["tension_direction"][1]
                if axis == "x" else zone["tension_direction"][0]
            )
            tension_low = direction_component < 0.0
            face_name = _face_name(axis, tension_low)
        row_status = "PASS" if valid and utilisation <= 1.0 + _TOL else "FAIL"
        rows = [{
            "type": "minimum area",
            "status": row_status,
            "axis": axis,
            "face": face_name,
            "tension_low": tension_low,
            "moment_centroid_knm": math.hypot(mx_c, my_c),
            "mx_centroid_knm": mx_c,
            "my_centroid_knm": my_c,
            "as_provided_mm2": zone.get("as_provided_mm2", 0.0),
            "as_min_mm2": as_min,
            "utilisation": utilisation if math.isfinite(utilisation) else None,
            "bt_mm": zone.get("bt_mm"),
            "tension_zone_depth_mm": zone.get("tension_zone_depth_mm"),
            "d_mm": zone.get("d_mm"),
            "fctm_mpa": float(fctm_mpa),
            "fyk_mpa": fyk if fyk > 0.0 else None,
            "bar_ids": zone.get("bar_ids") or [],
            "material_ids": zone.get("material_ids") or [],
            "tension_direction": zone.get("tension_direction"),
            "neutral_c_m": zone.get("neutral_c_m"),
            "neutral_point_m": zone.get("neutral_point_m"),
            "model": "gross-concrete resultant tension half-plane",
            "reason": (
                None if valid
                else zone.get("reason") or "no usable tension reinforcement or geometry"
            ),
        }]
        status = row_status
        reason = None if valid else rows[0]["reason"]
    limitations = [
        "The resultant gross-concrete uncracked strain plane defines the tension half; bt is its exact mean width.",
        "Prestressing tendons are not credited in this ordinary-reinforcement check.",
        "Ordinary reinforcement is assumed anchored to develop the entered fyk; reduce fyk where it cannot.",
    ]
    if edition == EC2_2005_DKNA:
        limitations.append(
            "DK NA 9.2.1.1(1) side-face reinforcement for high beam webs is not "
            "included in Formula (9.1N) and requires a separate detailing review."
        )
    return {
        "status": status,
        "edition": edition,
        "clause": "9.2.1.1(1), Formula (9.1N)",
        "n_ed_tension_kn": float(n_ed_tension_kn),
        "mx_ed_centroid_knm": mx_c,
        "my_ed_centroid_knm": my_c,
        "checks": rows,
        "reason": reason,
        "limitations": limitations,
    }


def _recentred_without_tendons(section: Section) -> Section:
    cx, cy = _centroid(section)
    rings = [
        np.asarray(ring, dtype=float) - np.array([cx, cy], dtype=float)
        for ring in section.concrete
    ]
    bars = [Bar(bar.x - cx, bar.y - cy, bar.area) for bar in section.bars]
    return Section(rings, bars=bars)


def _characteristic_plateau(material: MildSteel) -> MildSteel:
    """Characteristic-yield plateau used by EN 1992-1-1:2023, 12.2(2)."""
    return MildSteel(
        fytk=float(material.fytk),
        fyck=float(material.fytk),
        eut=1.0,
        futk=0.0,
        gamma_y=1.0,
        gamma_u=1.0,
        gamma_E=1.0,
        curve=2,
        Es=float(material.Es),
        active_in_compression=bool(material.active_in_compression),
    )


def _cracking_action(
    section: Section,
    *,
    n_ed_tension_kn: float,
    mx_centroid_knm: float,
    my_centroid_knm: float,
    fctm_mpa: float,
) -> dict:
    """Cracking action in the direction of the supplied centroidal moment."""
    plain = Section([ring.copy() for ring in section.concrete])
    axial = solve_elastic_uncracked(
        plain, -float(n_ed_tension_kn), 0.0, 0.0, 1.0
    )
    bending = solve_elastic_uncracked(
        plain, 0.0, float(mx_centroid_knm), float(my_centroid_knm), 1.0
    )
    if not axial.converged or not bending.converged:
        return {"valid": False, "reason": "uncracked section solve did not converge"}
    vertices = plain.concrete_vertices()
    sigma_n = axial.eps0 + axial.kx * vertices[:, 0] + axial.ky * vertices[:, 1]
    sigma_m = (
        bending.eps0 + bending.kx * vertices[:, 0] + bending.ky * vertices[:, 1]
    )
    limit = float(fctm_mpa) * 1000.0
    if float(np.max(sigma_n)) >= limit - _TOL:
        factor = 0.0
    else:
        candidates = [
            (limit - float(base)) / float(delta)
            for base, delta in zip(sigma_n, sigma_m)
            if delta > _TOL and (limit - float(base)) >= -_TOL
        ]
        if not candidates:
            return {"valid": False, "reason": "moment direction creates no tension"}
        factor = max(min(candidates), 0.0)
    mx_cr = factor * float(mx_centroid_knm)
    my_cr = factor * float(my_centroid_knm)
    return {
        "valid": True,
        "factor": factor,
        "mx_cr_knm": mx_cr,
        "my_cr_knm": my_cr,
        "m_cr_knm": math.hypot(mx_cr, my_cr),
        "axial_peak_tension_mpa": float(np.max(sigma_n)) / 1000.0,
    }


def _origin_inside_polygon(points: Sequence[tuple[float, float]]) -> bool:
    """Return whether the zero-moment point lies inside or on a capacity polygon."""
    if len(points) < 3:
        return False
    scale = max(
        max((abs(x) for x, _y in points), default=0.0),
        max((abs(y) for _x, y in points), default=0.0),
        1.0,
    )
    tol = 1.0e-9 * scale
    inside = False
    for index, (x1, y1) in enumerate(points):
        x2, y2 = points[(index + 1) % len(points)]
        cross = x1 * y2 - y1 * x2
        if abs(cross) <= tol * scale and x1 * x2 + y1 * y2 <= tol * tol:
            return True
        if (y1 > 0.0) != (y2 > 0.0):
            crossing_x = x1 - y1 * (x2 - x1) / (y2 - y1)
            if crossing_x >= -tol:
                inside = not inside
    return inside


def _nominal_capacity_utilisation(
    section: Section,
    concrete,
    materials: Sequence[MildSteel],
    *,
    n_ed_tension_kn: float,
    mx_cr_knm: float,
    my_cr_knm: float,
) -> dict:
    if len(materials) != len(section.bars):
        raise ValueError("one material is required per bar")
    characteristic = [_characteristic_plateau(material) for material in materials]
    nominal_axial_resistance_kn = sum(
        bar.area * float(material.fytk) * 1000.0
        for bar, material in zip(section.bars, materials)
    )
    if (
        float(n_ed_tension_kn) > nominal_axial_resistance_kn + _TOL
        and float(n_ed_tension_kn) > 0.0
    ):
        return {
            "valid": True,
            "utilisation": math.inf,
            "mr_nom_knm": 0.0,
            "axial_feasible": False,
            "nominal_axial_resistance_kn": nominal_axial_resistance_kn,
            "reason": "nominal reinforcement tension resistance is below NEd,min",
        }
    if not section.bars:
        return {
            "valid": True,
            "utilisation": math.inf,
            "mr_nom_knm": 0.0,
            "axial_feasible": False,
            "nominal_axial_resistance_kn": 0.0,
            "reason": "no ordinary reinforcement",
        }
    reference = characteristic[0]
    p_comp = -float(n_ed_tension_kn)
    mx = float(mx_cr_knm)
    my = float(my_cr_knm)
    if abs(mx) <= _TOL and abs(my) <= _TOL:
        points = solve_plastic(
            section,
            concrete,
            reference,
            p_comp,
            0.0,
            345.0,
            15.0,
            bar_materials=characteristic,
        )
        if not all(point.converged for point in points):
            return {
                "valid": False,
                "utilisation": None,
                "mr_nom_knm": None,
                "axial_feasible": None,
                "nominal_axial_resistance_kn": nominal_axial_resistance_kn,
                "reason": "nominal axial-moment envelope did not converge",
            }
        polygon = [(float(point.Mx), float(point.My)) for point in points]
        axial_feasible = _origin_inside_polygon(polygon)
        return {
            "valid": True,
            "utilisation": 0.0 if axial_feasible else math.inf,
            "mr_nom_knm": 0.0,
            "axial_feasible": axial_feasible,
            "nominal_axial_resistance_kn": nominal_axial_resistance_kn,
            "model": "zero cracking moment; nominal axial-moment envelope",
            "reason": (
                None
                if axial_feasible
                else "zero moment lies outside the nominal envelope at NEd,min"
            ),
        }
    if abs(my) <= _TOL:
        angle = FACE_ANGLE[("x", mx > 0.0)]
        point = plastic_capacity_at_angle(
            section,
            concrete,
            reference,
            p_comp,
            angle,
            bar_materials=characteristic,
        )
        resistance = abs(point.Mx)
        util = abs(mx) / resistance if resistance > 0.0 else math.inf
        return {
            "valid": bool(point.converged),
            "utilisation": util,
            "mr_nom_knm": resistance,
            "model": "uniaxial x",
        }
    if abs(mx) <= _TOL:
        angle = FACE_ANGLE[("y", my > 0.0)]
        point = plastic_capacity_at_angle(
            section,
            concrete,
            reference,
            p_comp,
            angle,
            bar_materials=characteristic,
        )
        resistance = abs(point.My)
        util = abs(my) / resistance if resistance > 0.0 else math.inf
        return {
            "valid": bool(point.converged),
            "utilisation": util,
            "mr_nom_knm": resistance,
            "model": "uniaxial y",
        }
    points = solve_plastic(
        section,
        concrete,
        reference,
        p_comp,
        0.0,
        345.0,
        15.0,
        bar_materials=characteristic,
    )
    if not all(point.converged for point in points):
        return {"valid": False, "utilisation": None, "mr_nom_knm": None}
    util, governing = combined.radial_util(
        [point.Mx for point in points],
        [point.My for point in points],
        mx,
        my,
    )
    resistance = math.hypot(mx, my) / util if util and util > 0.0 else math.inf
    return {
        "valid": True,
        "utilisation": util,
        "mr_nom_knm": resistance,
        "model": "biaxial 15-degree envelope",
        "governing": governing,
    }


def minimum_reinforcement_2023(
    section: Section,
    elements: Sequence[Mapping],
    materials: Sequence[MildSteel],
    concrete,
    *,
    fctm_mpa: float,
    n_ed_tension_kn: float,
    mx_ed_knm: float,
    my_ed_knm: float,
) -> dict:
    """Check EN 1992-1-1:2023, 12.2(2), for one selected case."""
    section.require_valid_geometry()
    if len(elements) != len(section.bars) or len(materials) != len(section.bars):
        raise ValueError("one element record and material are required per bar")
    centred = _recentred_without_tendons(section)
    mx_c, my_c = _centroid_moments(
        section, n_ed_tension_kn, mx_ed_knm, my_ed_knm
    )
    area_m2 = centred.gross_area
    compression_kn = max(-float(n_ed_tension_kn), 0.0)
    compression_limit_kn = 0.5 * area_m2 * float(concrete.fcd) * 1000.0
    limitations = [
        "Prestressing tendons are not credited; bonded-tendon contribution requires a separate review.",
        "The nominal resistance uses the entered design concrete law and limits every mild bar to its characteristic fyk.",
        "Ordinary reinforcement is assumed anchored to develop the entered fyk; reduce fyk where it cannot.",
    ]
    if compression_kn >= compression_limit_kn - _TOL and compression_limit_kn > 0.0:
        return {
            "status": "NOT APPLICABLE",
            "edition": EC2_2023,
            "clause": "12.2(2)(a), Formula (12.1)",
            "n_ed_tension_kn": float(n_ed_tension_kn),
            "mx_ed_centroid_knm": mx_c,
            "my_ed_centroid_knm": my_c,
            "compression_limit_kn": compression_limit_kn,
            "reason": "compressive NEd is not less than 0.5 Ac fcd",
            "checks": [],
            "limitations": limitations,
        }

    # Pure tension has its own direct force-equilibrium expression (12.2).
    if abs(mx_c) <= _TOL and abs(my_c) <= _TOL:
        if n_ed_tension_kn <= 0.0:
            return {
                "status": "NOT APPLICABLE",
                "edition": EC2_2023,
                "clause": "12.2(5)",
                "n_ed_tension_kn": float(n_ed_tension_kn),
                "mx_ed_centroid_knm": mx_c,
                "my_ed_centroid_knm": my_c,
                "reason": "case is compression-only and brittle tensile failure is excluded",
                "checks": [],
                "limitations": limitations,
            }
        demand_kn = area_m2 * float(fctm_mpa) * 1000.0
        resistance_kn = sum(
            bar.area * float(material.fytk) * 1000.0
            for bar, material in zip(centred.bars, materials)
        )
        util = demand_kn / resistance_kn if resistance_kn > 0.0 else math.inf
        check = {
            "type": "pure tension",
            "status": "PASS" if util <= 1.0 + _TOL else "FAIL",
            "demand_kn": demand_kn,
            "resistance_kn": resistance_kn,
            "utilisation": util if math.isfinite(util) else None,
            "as_provided_mm2": sum(bar.area for bar in centred.bars) * 1.0e6,
            "bar_ids": [str(item.get("id") or index + 1)
                        for index, item in enumerate(elements)],
        }
        return {
            "status": check["status"],
            "edition": EC2_2023,
            "clause": "12.2(2)(b), Formula (12.2)",
            "n_ed_tension_kn": float(n_ed_tension_kn),
            "mx_ed_centroid_knm": mx_c,
            "my_ed_centroid_knm": my_c,
            "checks": [check],
            "reason": None,
            "limitations": limitations,
        }

    cracking = _cracking_action(
        centred,
        n_ed_tension_kn=n_ed_tension_kn,
        mx_centroid_knm=mx_c,
        my_centroid_knm=my_c,
        fctm_mpa=fctm_mpa,
    )
    if not cracking.get("valid"):
        return {
            "status": "INVALID",
            "edition": EC2_2023,
            "clause": "12.2(2)(a), Formula (12.1)",
            "n_ed_tension_kn": float(n_ed_tension_kn),
            "mx_ed_centroid_knm": mx_c,
            "my_ed_centroid_knm": my_c,
            "checks": [],
            "reason": cracking.get("reason"),
            "limitations": limitations,
        }
    capacity = _nominal_capacity_utilisation(
        centred,
        concrete,
        materials,
        n_ed_tension_kn=n_ed_tension_kn,
        mx_cr_knm=cracking["mx_cr_knm"],
        my_cr_knm=cracking["my_cr_knm"],
    )
    util = capacity.get("utilisation")
    if not capacity.get("valid") or util is None:
        status = "INVALID"
    else:
        status = "PASS" if float(util) <= 1.0 + _TOL else "FAIL"
    check = {
        "type": "bending with axial force",
        "status": status,
        "utilisation": util if util is not None and math.isfinite(float(util)) else None,
        "m_cr_knm": cracking["m_cr_knm"],
        "mx_cr_knm": cracking["mx_cr_knm"],
        "my_cr_knm": cracking["my_cr_knm"],
        "mr_nom_knm": capacity.get("mr_nom_knm"),
        "cracking_factor": cracking["factor"],
        "axial_peak_tension_mpa": cracking["axial_peak_tension_mpa"],
        "model": capacity.get("model"),
        "axial_feasible": capacity.get("axial_feasible"),
        "nominal_axial_resistance_kn": capacity.get(
            "nominal_axial_resistance_kn"
        ),
        "reason": capacity.get("reason"),
        "as_provided_mm2": sum(bar.area for bar in centred.bars) * 1.0e6,
        "bar_ids": [str(item.get("id") or index + 1)
                    for index, item in enumerate(elements)],
    }
    return {
        "status": status,
        "edition": EC2_2023,
        "clause": "12.2(2)(a), Formula (12.1)",
        "n_ed_tension_kn": float(n_ed_tension_kn),
        "mx_ed_centroid_knm": mx_c,
        "my_ed_centroid_knm": my_c,
        "compression_limit_kn": compression_limit_kn,
        "checks": [check],
        "reason": (
            capacity.get("reason")
            if status in {"FAIL", "INVALID"}
            else None
        ),
        "limitations": limitations,
    }


def minimum_reinforcement(
    section: Section,
    elements: Sequence[Mapping],
    materials: Sequence[MildSteel],
    concrete,
    *,
    edition: str,
    fctm_mpa: float,
    n_ed_tension_kn: float,
    mx_ed_knm: float,
    my_ed_knm: float,
    member_type: str = MEMBER_BEAM,
    cut_direction: str = CUT_TRANSVERSE,
) -> dict:
    """Dispatch one selected case to its edition-specific check."""
    section.require_valid_geometry()
    if edition not in EDITIONS:
        raise ValueError("unknown detailing edition")
    member = str(member_type or MEMBER_BEAM).strip().title()
    if member not in MEMBER_TYPES:
        raise ValueError("member_type must be Beam or Slab")
    cut = str(cut_direction or CUT_TRANSVERSE).strip()
    if cut not in CUT_DIRECTIONS:
        raise ValueError("unknown section cut direction")
    modelled_direction = (
        "longitudinal" if cut == CUT_TRANSVERSE else "transverse"
    )
    if member == MEMBER_SLAB and cut == CUT_LONGITUDINAL:
        return {
            "status": "NOT ASSESSED",
            "edition": edition,
            "member_type": member,
            "cut_direction": cut,
            "modelled_reinforcement_direction": modelled_direction,
            "clause": (
                "Table 12.2, item 3"
                if edition == EC2_2023
                else "9.3.1.1(2)"
            ),
            "n_ed_tension_kn": float(n_ed_tension_kn),
            "mx_ed_centroid_knm": None,
            "my_ed_centroid_knm": None,
            "checks": [],
            "reason": (
                "the minimum secondary reinforcement is defined relative to "
                "orthogonal primary reinforcement, which is not represented in "
                "this section cut"
            ),
            "limitations": [
                "Only reinforcement acting normal to the modelled section is assessed."
            ],
        }
    if edition == EC2_2023:
        result = minimum_reinforcement_2023(
            section,
            elements,
            materials,
            concrete,
            fctm_mpa=fctm_mpa,
            n_ed_tension_kn=n_ed_tension_kn,
            mx_ed_knm=mx_ed_knm,
            my_ed_knm=my_ed_knm,
        )
    else:
        result = minimum_reinforcement_2005(
            section,
            elements,
            materials,
            fctm_mpa=fctm_mpa,
            n_ed_tension_kn=n_ed_tension_kn,
            mx_ed_knm=mx_ed_knm,
            my_ed_knm=my_ed_knm,
            edition=edition,
        )
    result["member_type"] = member
    result["cut_direction"] = cut
    result["modelled_reinforcement_direction"] = modelled_direction
    if member == MEMBER_SLAB:
        result["clause"] = (
            "Table 12.2, item 1; 12.2(2)(a), Formula (12.1)"
            if edition == EC2_2023
            else "9.3.1.1(1); 9.2.1.1(1), Formula (9.1N)"
        )
    return result


def clear_spacing(
    elements: Sequence[Mapping],
    *,
    d_upper_mm: float,
    edition: str,
    include_tendons: bool = False,
) -> dict:
    """Check pairwise clear distance between parallel reinforcement elements.

    The section-plane geometry cannot verify lap length, bundle arrangement,
    bond or an equivalent bundle diameter; those remain separate checks.
    """
    if edition not in EDITIONS:
        raise ValueError("unknown detailing edition")
    if not math.isfinite(float(d_upper_mm)) or float(d_upper_mm) < 0.0:
        raise ValueError("Dupper must be a non-negative finite number")
    included = [
        dict(item)
        for item in elements
        if str(item.get("kind") or "bar") == "bar" or include_tendons
    ]
    pairs = []
    invalid_ids = []
    for item in included:
        try:
            values = (
                float(item["x_mm"]),
                float(item["y_mm"]),
                float(item["diameter_mm"]),
            )
        except (KeyError, TypeError, ValueError):
            invalid_ids.append(str(item.get("id") or "?"))
            continue
        if not all(math.isfinite(value) for value in values) or values[2] <= 0.0:
            invalid_ids.append(str(item.get("id") or "?"))
    if invalid_ids:
        return {
            "status": "INVALID",
            "edition": edition,
            "clause": "8.2(2)" if edition != EC2_2023 else "11.2(2)",
            "d_upper_mm": float(d_upper_mm),
            "pairs": [],
            "invalid_ids": invalid_ids,
            "reason": "missing or invalid reinforcement geometry",
        }
    for index, first in enumerate(included):
        for second in included[index + 1:]:
            dx = float(second["x_mm"]) - float(first["x_mm"])
            dy = float(second["y_mm"]) - float(first["y_mm"])
            centre = math.hypot(dx, dy)
            phi_1 = float(first["diameter_mm"])
            phi_2 = float(second["diameter_mm"])
            clear = centre - 0.5 * (phi_1 + phi_2)
            required = max(max(phi_1, phi_2), float(d_upper_mm) + 5.0, 20.0)
            if clear + _TOL >= required:
                pair_status = "PASS"
            else:
                pair_status = "FAIL"
            pairs.append({
                "status": pair_status,
                "first_id": str(first.get("id") or index + 1),
                "second_id": str(second.get("id") or index + 2),
                "first_kind": str(first.get("kind") or "bar"),
                "second_kind": str(second.get("kind") or "bar"),
                "clear_mm": clear,
                "required_mm": required,
                "margin_mm": clear - required,
                "centre_distance_mm": centre,
                "phi_first_mm": phi_1,
                "phi_second_mm": phi_2,
            })
    if not pairs:
        status = "NOT ASSESSED"
        reason = "fewer than two included reinforcement elements"
        governing = None
    else:
        status = _status([pair["status"] for pair in pairs])
        reason = None
        governing = min(pairs, key=lambda pair: pair["margin_mm"])
    return {
        "status": status,
        "edition": edition,
        "clause": "8.2(2)" if edition != EC2_2023 else "11.2(2)",
        "d_upper_mm": float(d_upper_mm),
        "include_tendons": bool(include_tendons),
        "pairs": pairs,
        "governing": governing,
        "reason": reason,
        "limitations": [
            "Pairwise edge-to-edge distance is checked in the section plane.",
            "Lap length, bundle arrangement, bond and equivalent bundle diameter are not verified.",
            "For included post-tensioning tendons, the entered diameter must be the detailing envelope or duct diameter.",
        ],
    }


def minimum_transverse_ratio(
    fck_mpa: float,
    fywk_mpa: float,
    *,
    edition: str,
    ductility_class: str = "B",
    apply_ductility_reduction: bool = False,
) -> dict:
    """Return the edition-specific minimum transverse-reinforcement ratio.

    The returned ratio is dimensionless.  The optional 2023 ductility-class
    reduction is favourable and is therefore applied only after an explicit user
    selection; class B reduces the base value by 10 %, class C by 20 %, and class A
    does not reduce it.
    """
    if edition not in EDITIONS:
        raise ValueError("unknown detailing edition")
    fck = float(fck_mpa)
    fywk = float(fywk_mpa)
    if not math.isfinite(fck) or fck <= 0.0:
        raise ValueError("fck must be a positive finite number")
    if not math.isfinite(fywk) or fywk <= 0.0:
        raise ValueError("fywk must be a positive finite number")
    ductility = str(ductility_class or "B").strip().upper()
    if ductility not in {"A", "B", "C"}:
        raise ValueError("ductility class must be A, B or C")

    coefficient = 0.063 if edition == EC2_2005_DKNA else 0.08
    reduction = 1.0
    reduction_applied = bool(apply_ductility_reduction and edition == EC2_2023)
    if reduction_applied:
        reduction = {"A": 1.0, "B": 0.90, "C": 0.80}[ductility]
    ratio = coefficient * math.sqrt(fck) / fywk * reduction
    return {
        "ratio": ratio,
        "coefficient": coefficient,
        "ductility_class": ductility,
        "ductility_factor": reduction,
        "ductility_reduction_applied": reduction_applied,
        "clause": (
            "12.2(4), Formula (12.4)"
            if edition == EC2_2023
            else "9.2.2(5), Formulae (9.4)-(9.5)"
        ),
    }


def _ratio_check(scope: str, provided: float, required: float, clause: str, **extra):
    valid = all(math.isfinite(value) and value >= 0.0
                for value in (provided, required))
    if not valid:
        status, utilisation = "INVALID", None
    elif provided <= _TOL:
        status, utilisation = "FAIL", math.inf
    else:
        utilisation = required / provided
        status = "PASS" if provided + _TOL >= required else "FAIL"
    return {
        "kind": "minimum_ratio",
        "scope": scope,
        "status": status,
        "provided": provided,
        "limit": required,
        "utilisation": utilisation,
        "criterion": "provided ratio >= minimum ratio",
        "clause": clause,
        **extra,
    }


def _spacing_check(
    scope: str,
    kind: str,
    provided_mm: float | None,
    maximum_mm: float | None,
    clause: str,
    *,
    reason: str | None = None,
    **extra,
):
    if (
        provided_mm is None
        or maximum_mm is None
        or not math.isfinite(float(provided_mm))
        or not math.isfinite(float(maximum_mm))
        or float(provided_mm) < 0.0
        or float(maximum_mm) <= 0.0
    ):
        status, utilisation = "NOT ASSESSED", None
    else:
        utilisation = float(provided_mm) / float(maximum_mm)
        status = (
            "PASS"
            if float(provided_mm) <= float(maximum_mm) + _TOL
            else "FAIL"
        )
    return {
        "kind": kind,
        "scope": scope,
        "status": status,
        "provided": provided_mm,
        "limit": maximum_mm,
        "utilisation": utilisation,
        "criterion": "provided spacing <= maximum spacing",
        "clause": clause,
        "reason": reason,
        **extra,
    }


def _not_assessed_check(
    scope: str,
    kind: str,
    clause: str,
    reason: str,
    **extra,
):
    return {
        "kind": kind,
        "scope": scope,
        "status": "NOT ASSESSED",
        "provided": None,
        "limit": None,
        "utilisation": None,
        "criterion": None,
        "clause": clause,
        "reason": reason,
        **extra,
    }


def _required_links_check(
    scope: str,
    clause: str,
    *,
    reason: str = "shear resistance without links is insufficient",
    criterion: str = "shear links provided where required",
    **extra,
):
    return {
        "kind": "required_links",
        "scope": scope,
        "status": "FAIL",
        "provided": 0.0,
        "limit": 1.0,
        "utilisation": math.inf,
        "criterion": criterion,
        "clause": clause,
        "reason": reason,
        **extra,
    }


def transverse_reinforcement(
    *,
    edition: str,
    fck_mpa: float,
    fywk_mpa: float,
    diameter_mm: float,
    spacing_mm: float,
    shear_directions: Sequence[Mapping] = (),
    torsion_tubes: Sequence[Mapping] = (),
    ductility_class: str = "B",
    apply_ductility_reduction: bool = False,
    member_type: str = MEMBER_BEAM,
) -> dict:
    """Check minimum ratio and spacing of vertical/closed transverse links.

    ``shear_directions`` records require ``component``, ``bw_mm`` and ``d_mm``.
    ``links_present`` and ``links_required`` retain the verified resistance
    decision when links are omitted.  For defined links, ``legs`` is required and
    ``transverse_leg_spacing_mm`` may be zero, in which case the full web width
    is used as an upper-bound screen when at least two effective legs are present.
    That bound can prove compliance, but cannot prove non-compliance because the
    actual largest gap may be smaller.

    ``torsion_tubes`` records require ``tef_mm``, ``uk_mm`` and the
    rotation-invariant ``minimum_dimension_mm`` derived from the tube outline.
    Beam torsion-link detailing is not applied to slabs.
    """
    if edition not in EDITIONS:
        raise ValueError("unknown detailing edition")
    member = str(member_type or MEMBER_BEAM).strip().title()
    if member not in MEMBER_TYPES:
        raise ValueError("member_type must be Beam or Slab")
    values = {
        "fck": float(fck_mpa),
        "fywk": float(fywk_mpa),
        "diameter": float(diameter_mm),
        "spacing": float(spacing_mm),
    }
    invalid = [
        name for name, value in values.items()
        if not math.isfinite(value) or value <= 0.0
    ]
    if invalid:
        return {
            "status": "INVALID",
            "edition": edition,
            "checks": [],
            "reason": "invalid " + ", ".join(invalid),
            "limitations": [],
        }

    minimum = minimum_transverse_ratio(
        values["fck"],
        values["fywk"],
        edition=edition,
        ductility_class=ductility_class,
        apply_ductility_reduction=apply_ductility_reduction,
    )
    leg_area = math.pi * values["diameter"] ** 2 / 4.0
    checks = []
    if member == MEMBER_SLAB:
        shear_clause = (
            "12.2(4), Table 12.2, 12.4.2"
            if edition == EC2_2023
            else "9.3.2(2), (4)-(5)"
        )
    else:
        shear_clause = (
            "12.2(4), Table 12.1"
            if edition == EC2_2023
            else "9.2.2(5)-(8), Formulae (9.4)-(9.8)"
        )
    torsion_clause = (
        "Table 12.1, 12.3.3"
        if edition == EC2_2023
        else "9.2.3(3)"
    )
    beam_link_requirement_clause = (
        "12.2(4), Table 12.1"
        if edition == EC2_2023
        else "9.2.2(2), (5)"
    )

    for direction in shear_directions:
        component = str(direction.get("component") or "?").lower()
        scope = f"Shear {component.upper()}"
        links_present = bool(direction.get("links_present", True))
        links_required = direction.get("links_required", False)
        if not links_present:
            if member == MEMBER_BEAM and edition != EC2_2023:
                checks.append(_required_links_check(
                    scope,
                    beam_link_requirement_clause,
                    component=component,
                    requirement="minimum beam shear reinforcement",
                    reason="minimum shear reinforcement is required for this beam",
                    criterion="minimum beam shear reinforcement provided",
                ))
            elif links_required is True:
                checks.append(_required_links_check(
                    scope,
                    str(direction.get("requirement_clause") or shear_clause),
                    component=component,
                ))
            elif links_required is None:
                checks.append(_not_assessed_check(
                    scope,
                    "required_links",
                    str(direction.get("requirement_clause") or shear_clause),
                    "shear resistance without links is invalid",
                    component=component,
                ))
            elif member == MEMBER_BEAM and edition == EC2_2023:
                try:
                    depth = float(direction.get("d_mm"))
                except (TypeError, ValueError):
                    depth = math.nan
                if not math.isfinite(depth) or depth <= 0.0:
                    checks.append(_not_assessed_check(
                        scope,
                        "minimum_link_applicability",
                        "8.2.1(2), 12.2(4)",
                        "effective depth is unavailable for the 2023 "
                        "minimum-link applicability check",
                        component=component,
                    ))
                elif depth > 500.0:
                    checks.append(_not_assessed_check(
                        scope,
                        "minimum_link_applicability",
                        "8.2.1(2), 12.2(4)",
                        "the 2023 minimum-link requirement for statically "
                        "determinate beams with d > 500 mm cannot be decided "
                        "because the structural system is not declared by the "
                        "section model",
                        component=component,
                        d_mm=depth,
                    ))
            continue
        try:
            bw = float(direction["bw_mm"])
            depth = float(direction["d_mm"])
            legs = float(direction["legs"])
            entered_transverse = float(
                direction.get("transverse_leg_spacing_mm", 0.0)
            )
        except (KeyError, TypeError, ValueError):
            for kind in (
                "minimum_ratio",
                "longitudinal_spacing",
                "transverse_leg_spacing",
            ):
                checks.append(_not_assessed_check(
                    scope,
                    kind,
                    shear_clause,
                    "missing shear-link geometry",
                    component=component,
                ))
            continue

        bw_valid = math.isfinite(bw) and bw > 0.0
        depth_valid = math.isfinite(depth) and depth > 0.0
        legs_valid = math.isfinite(legs) and legs > 0.0
        if bw_valid and legs_valid:
            provided_ratio = legs * leg_area / (values["spacing"] * bw)
            checks.append(_ratio_check(
                scope,
                provided_ratio,
                minimum["ratio"],
                minimum["clause"],
                component=component,
                provided_label="rho_w",
                limit_label="rho_w,min",
                bw_mm=bw,
                d_mm=depth if depth_valid else None,
                legs=legs,
            ))
        else:
            checks.append(_not_assessed_check(
                scope,
                "minimum_ratio",
                minimum["clause"],
                "web width or effective leg count is unavailable",
                component=component,
            ))

        if depth_valid:
            checks.append(_spacing_check(
                scope,
                "longitudinal_spacing",
                values["spacing"],
                0.75 * depth,
                shear_clause,
                component=component,
                provided_label="s_l",
                limit_label="s_l,max",
                d_mm=depth,
            ))
        else:
            checks.append(_not_assessed_check(
                scope,
                "longitudinal_spacing",
                shear_clause,
                "effective depth is unavailable",
                component=component,
            ))

        if math.isfinite(entered_transverse) and entered_transverse > 0.0:
            transverse_spacing = entered_transverse
            source = "user"
            spacing_reason = None
        elif bw_valid and legs_valid and legs >= 2.0:
            # Without entered leg coordinates or an explicit equal-spacing
            # declaration, the full web width is the only defensible upper bound
            # on the largest gap.  Dividing by (legs - 1) would assume uniform
            # distribution and can be unconservative for clustered legs.
            transverse_spacing = bw
            source = "gross-web upper-bound screen"
            spacing_reason = None
        else:
            transverse_spacing = None
            source = "unavailable"
            spacing_reason = (
                "enter the maximum transverse distance between legs or define "
                "at least two effective legs"
            )
        transverse_check = _spacing_check(
            scope,
            "transverse_leg_spacing",
            transverse_spacing,
            (
                1.5 * depth
                if depth_valid and member == MEMBER_SLAB
                else min(0.75 * depth, 600.0) if depth_valid else None
            ),
            shear_clause,
            reason=(
                spacing_reason
                or (None if depth_valid else "effective depth is unavailable")
            ),
            component=component,
            provided_label="s_t",
            limit_label="s_t,max",
            spacing_source=source,
            measurement_axis=str(
                direction.get("measurement_axis") or ""
            ).lower() or None,
            d_mm=depth,
        )
        if (
            source == "gross-web upper-bound screen"
            and transverse_check["status"] == "FAIL"
        ):
            # An upper bound that is below the limit proves PASS.  An upper bound
            # above the limit does not prove FAIL: the actual legs may be closer.
            transverse_check.update(
                status="NOT ASSESSED",
                utilisation=None,
                reason=(
                    "gross web breadth exceeds the spacing limit; enter the "
                    "actual maximum centre-to-centre leg spacing for a "
                    "definitive assessment"
                ),
            )
        checks.append(transverse_check)

    for index, tube in enumerate(torsion_tubes, start=1):
        label = str(tube.get("label") or f"Tube {index}")
        scope = f"Torsion {label}"
        if member == MEMBER_SLAB:
            for kind in ("minimum_ratio", "torsion_spacing"):
                checks.append(_not_assessed_check(
                    scope,
                    kind,
                    "No slab torsion-link detailing provision selected",
                    "beam torsion-link detailing is not applied to slabs",
                    tube=index,
                ))
            continue
        if not bool(tube.get("valid", True)):
            reason = str(tube.get("reason") or "invalid torsion tube")
            for kind, clause in (
                ("minimum_ratio", minimum["clause"]),
                ("torsion_spacing", torsion_clause),
            ):
                checks.append(_not_assessed_check(
                    scope, kind, clause, reason, tube=index
                ))
            continue
        try:
            tef = float(tube["tef_mm"])
            uk = float(tube["uk_mm"])
            minimum_dimension = float(tube["minimum_dimension_mm"])
        except (KeyError, TypeError, ValueError):
            for kind, clause in (
                ("minimum_ratio", minimum["clause"]),
                ("torsion_spacing", torsion_clause),
            ):
                checks.append(_not_assessed_check(
                    scope,
                    kind,
                    clause,
                    "missing torsion-link geometry",
                    tube=index,
                ))
            continue
        if not all(math.isfinite(value) and value > 0.0
                   for value in (tef, uk, minimum_dimension)):
            for kind, clause in (
                ("minimum_ratio", minimum["clause"]),
                ("torsion_spacing", torsion_clause),
            ):
                checks.append(_not_assessed_check(
                    scope,
                    kind,
                    clause,
                    "invalid torsion-link geometry",
                    tube=index,
                ))
            continue

        provided_ratio = leg_area / (values["spacing"] * tef)
        checks.append(_ratio_check(
            scope,
            provided_ratio,
            minimum["ratio"],
            minimum["clause"],
            tube=index,
            provided_label="rho_w,T",
            limit_label="rho_w,min",
            tef_mm=tef,
        ))
        spacing_limits = {
            "u_k/8": uk / 8.0,
            "minimum section dimension": minimum_dimension,
        }
        maximum = min(spacing_limits.values())
        checks.append(_spacing_check(
            scope,
            "torsion_spacing",
            values["spacing"],
            maximum,
            torsion_clause,
            tube=index,
            provided_label="s",
            limit_label="s_max",
            spacing_limits_mm=spacing_limits,
            governing_limit=min(spacing_limits, key=spacing_limits.get),
        ))

    if not checks:
        status = "NOT APPLICABLE"
        reason = "no active shear or torsion action requiring link-detailing checks"
    else:
        status = _status([check["status"] for check in checks])
        reason = None
    governing = (
        max(
            (
                check for check in checks
                if check.get("utilisation") is not None
            ),
            key=lambda check: (
                math.inf
                if not math.isfinite(float(check["utilisation"]))
                else float(check["utilisation"])
            ),
        )
        if any(check.get("utilisation") is not None for check in checks)
        else None
    )
    limitations = [
        "All entered shear reinforcement is modelled as vertical stirrups; "
        "alternative bent-up reinforcement is not represented.",
        "All entered torsion reinforcement is modelled as closed stirrups.",
        "Stirrup anchorage is assumed. Reduce fywk when full anchorage is not "
        "available.",
        "The section model does not verify cover, bends, mandrel diameter, "
        "anchorage length or construction access.",
        "BN1-59-5 and Danish Road Directorate owner provisions are not "
        "applied automatically.",
    ]
    if edition != EC2_2023 and member == MEMBER_BEAM and torsion_tubes:
        limitations.append(
            "The 350 mm value in 9.2.3(4) limits longitudinal torsion-bar "
            "spacing around the link perimeter; it is not a closed-link "
            "spacing limit and is outside this check."
        )
    return {
        "status": status,
        "edition": edition,
        "member_type": member,
        "checks": checks,
        "governing": governing,
        "governing_utilisation": (
            float(governing["utilisation"]) if governing is not None else None
        ),
        "reason": reason,
        "minimum_ratio": minimum,
        "diameter_mm": values["diameter"],
        "spacing_mm": values["spacing"],
        "fywk_mpa": values["fywk"],
        "limitations": limitations,
    }
