"""Longitudinal minimum-reinforcement and clear-spacing checks.

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


def _face_bar_indices(
    section: Section, axis: str, tension_low: bool
) -> list[int]:
    cx, cy = _centroid(section)
    cut = cy if axis == "x" else cx
    return [
        index
        for index, bar in enumerate(section.bars)
        if (
            _coord((bar.x, bar.y), axis) < cut
            if tension_low
            else _coord((bar.x, bar.y), axis) > cut
        )
    ]


def _face_bar_data(
    section: Section,
    elements: Sequence[Mapping],
    materials: Sequence[MildSteel],
    axis: str,
    tension_low: bool,
) -> dict:
    if len(elements) != len(section.bars) or len(materials) != len(section.bars):
        raise ValueError("one element record and material are required per bar")
    indices = _face_bar_indices(section, axis, tension_low)
    areas = [section.bars[index].area * 1.0e6 for index in indices]
    area = sum(areas)
    if area > 0.0:
        cg = sum(
            areas[pos]
            * _coord((section.bars[index].x, section.bars[index].y), axis)
            for pos, index in enumerate(indices)
        ) / area
        outer_coords = [_coord(point, axis) for point in section.concrete[0]]
        compression_fibre = max(outer_coords) if tension_low else min(outer_coords)
        d_mm = abs(compression_fibre - cg) * 1000.0
    else:
        cg = None
        d_mm = 0.0
    return {
        "indices": indices,
        "bar_ids": [str(elements[index].get("id") or index + 1) for index in indices],
        "as_provided_mm2": area,
        "centroid_m": cg,
        "d_mm": d_mm,
        "fyk_values_mpa": [float(materials[index].fytk) for index in indices],
        "material_ids": [
            str(elements[index].get("material_id") or "") for index in indices
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
    """Check Formula (9.1N) on every tension face active in the case."""
    if edition not in {EC2_2005, EC2_2005_DKNA}:
        raise ValueError("a 2005-family edition is required")
    mx_c, my_c = _centroid_moments(
        section, n_ed_tension_kn, mx_ed_knm, my_ed_knm
    )
    actions = (("x", mx_c), ("y", my_c))
    rows = []
    for axis, moment in actions:
        if abs(moment) <= _TOL:
            continue
        tension_low = moment > 0.0
        face = _face_bar_data(
            section, elements, materials, axis, tension_low
        )
        bt_mm, tension_depth_mm = tension_zone_mean_width(
            section, axis, tension_low
        )
        fyk = min(face["fyk_values_mpa"], default=0.0)
        valid = bool(
            face["as_provided_mm2"] > 0.0
            and face["d_mm"] > 0.0
            and bt_mm > 0.0
            and fyk > 0.0
            and fctm_mpa > 0.0
        )
        as_min = (
            max(0.26 * float(fctm_mpa) / fyk, 0.0013)
            * bt_mm
            * face["d_mm"]
            if valid
            else None
        )
        utilisation = (
            as_min / face["as_provided_mm2"]
            if as_min is not None and face["as_provided_mm2"] > 0.0
            else math.inf
        )
        row_status = "PASS" if valid and utilisation <= 1.0 + _TOL else "FAIL"
        rows.append({
            "status": row_status,
            "axis": axis,
            "face": _face_name(axis, tension_low),
            "tension_low": tension_low,
            "moment_centroid_knm": moment,
            "as_provided_mm2": face["as_provided_mm2"],
            "as_min_mm2": as_min,
            "utilisation": utilisation if math.isfinite(utilisation) else None,
            "bt_mm": bt_mm,
            "tension_zone_depth_mm": tension_depth_mm,
            "d_mm": face["d_mm"],
            "fctm_mpa": float(fctm_mpa),
            "fyk_mpa": fyk if fyk > 0.0 else None,
            "bar_ids": face["bar_ids"],
            "material_ids": face["material_ids"],
            "reason": None if valid else "no usable tension reinforcement or geometry",
        })
    if rows:
        status = _status([row["status"] for row in rows])
        reason = None
    else:
        status = "NOT ASSESSED"
        reason = (
            "Formula (9.1N) needs a bending tension face; the selected case has "
            "no moment about the concrete centroid"
        )
    limitations = [
        "The automatic bt is the exact mean width of the gross-centroid tension half.",
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
) -> dict:
    """Dispatch one selected case to its edition-specific check."""
    if edition == EC2_2023:
        return minimum_reinforcement_2023(
            section,
            elements,
            materials,
            concrete,
            fctm_mpa=fctm_mpa,
            n_ed_tension_kn=n_ed_tension_kn,
            mx_ed_knm=mx_ed_knm,
            my_ed_knm=my_ed_knm,
        )
    return minimum_reinforcement_2005(
        section,
        elements,
        materials,
        fctm_mpa=fctm_mpa,
        n_ed_tension_kn=n_ed_tension_kn,
        mx_ed_knm=mx_ed_knm,
        my_ed_knm=my_ed_knm,
        edition=edition,
    )


def clear_spacing(
    elements: Sequence[Mapping],
    *,
    d_upper_mm: float,
    edition: str,
    include_tendons: bool = False,
) -> dict:
    """Check pairwise clear distance between parallel reinforcement elements.

    A shared nonblank ``spacing_group_id`` declares a lap/bundle exception.  The
    geometric shortfall is still reported and receives ``REVIEW`` rather than a
    silent pass because the cross-section alone cannot verify the longitudinal
    lap length, bundle arrangement, bond or equivalent bundle diameter.
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
            group_1 = str(first.get("spacing_group_id") or "").strip()
            group_2 = str(second.get("spacing_group_id") or "").strip()
            declared_exception = bool(group_1 and group_1 == group_2)
            if clear + _TOL >= required:
                pair_status = "PASS"
            elif declared_exception:
                pair_status = "REVIEW"
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
                "spacing_group_id": group_1 if declared_exception else "",
                "declared_exception": declared_exception,
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
            "A declared lap/bundle group requires engineering review and is not an automatic pass.",
            "For included post-tensioning tendons, the entered diameter must be the detailing envelope or duct diameter.",
        ],
    }
