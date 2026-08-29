"""Shear resistance of a section without shear reinforcement (VRd,c).

EN 1992-1-1:2005 section 6.2.2(1), with the DK NA:2024 v_min. The design shear
resistance of a member not requiring shear reinforcement is

    VRd,c = [C_Rd,c*k*(100*rho_l*fck)^(1/3) + k1*sigma_cp] * bw * d     (6.2.a)

with a lower bound

    VRd,c = (v_min + k1*sigma_cp) * bw * d                              (6.2.b)

where ``k = 1 + sqrt(200/d) <= 2`` (d in mm), ``rho_l = Asl/(bw*d) <= 0.02`` is the
tension-reinforcement ratio (bars assumed fully anchored past the section),
``sigma_cp = NEd/Ac < 0.2*fcd`` is the axial stress (compression positive), and the
edition supplies ``C_Rd,c = 0.18/gamma_c``, ``k1 = 0.15`` and ``v_min`` (see
:class:`sector.codes.DesignCode`). The section forces, the effective depth ``d``, the
lever arm ``z`` and the tension reinforcement ``Asl`` are quantities Sector derives
from the geometry; ``bw`` (the smallest web width in the tension zone) is an input
that defaults to the derived minimum solid width.

Signs: the code takes NEd compression-positive; Sector's axial force N is
tension-positive, so the caller passes ``-N`` here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

from . import geometry


SHEAR_SECTION_AUTO = "Automatic - solid rectangle only"
SHEAR_SECTION_CONSTANT = "Constant-width web"
SHEAR_SECTION_VARIABLE = "Variable-width web"
SHEAR_SECTION_CIRCULAR = "Circular section"
SHEAR_SECTION_FORMS = (
    SHEAR_SECTION_AUTO,
    SHEAR_SECTION_CONSTANT,
    SHEAR_SECTION_VARIABLE,
    SHEAR_SECTION_CIRCULAR,
)

SHEAR_DUCT_NONE = "No web ducts"
SHEAR_DUCT_GROUTED_STEEL = "Grouted steel ducts"
SHEAR_DUCT_GROUTED_PLASTIC_THIN = (
    "Grouted plastic ducts - confirmed thin wall"
)
SHEAR_DUCT_GROUTED_PLASTIC_THICK = "Grouted plastic ducts - thick wall"
SHEAR_DUCT_UNGROUTED_OR_SOFT = (
    "Not grouted, soft-filled, or unbonded"
)
SHEAR_DUCT_DETAILS_INCOMPLETE = "Duct details not established"
SHEAR_DUCT_CASES = (
    SHEAR_DUCT_NONE,
    SHEAR_DUCT_GROUTED_STEEL,
    SHEAR_DUCT_GROUTED_PLASTIC_THIN,
    SHEAR_DUCT_GROUTED_PLASTIC_THICK,
    SHEAR_DUCT_UNGROUTED_OR_SOFT,
    SHEAR_DUCT_DETAILS_INCOMPLETE,
)

SHEAR_SECTION_GEOMETRY_REASON = (
    "the governing shear section geometry was not established"
)
SHEAR_VARIABLE_WIDTH_REASON = (
    "the variable-width shear geometry was not established"
)
SHEAR_CIRCULAR_REASON = "the circular shear geometry was not established"
SHEAR_SECTION_METHOD_REASON = (
    "the selected shear method does not assess this section form"
)
SHEAR_DUCT_INPUT_REASON = "the web-duct geometry was not established"
SHEAR_NOMINAL_WIDTH_REASON = "the nominal web width is not positive"


def _finite_real(value) -> float | None:
    """Return a finite non-Boolean real, or ``None`` for unavailable input."""

    value_type = type(value)
    is_numpy_bool = (
        value_type.__name__ in {"bool", "bool_"}
        and value_type.__module__.split(".", 1)[0] == "numpy"
    )
    if isinstance(value, bool) or is_numpy_bool or isinstance(value, (str, bytes)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def resolve_circular_shear_geometry(
    *,
    bw_mm,
    hoop_diameter_mm,
    fitted_z_mm,
) -> dict:
    """Validate the circular operands shared by shear and required chords."""

    bw = _finite_real(bw_mm)
    hoop = _finite_real(hoop_diameter_mm)
    fitted_z = _finite_real(fitted_z_mm)
    valid = bool(
        bw is not None
        and hoop is not None
        and fitted_z is not None
        and bw > 0.0
        and hoop > 0.0
        and fitted_z > 0.0
        and bw <= hoop
        and fitted_z <= hoop
    )
    return {
        "valid": valid,
        "reason": None if valid else SHEAR_CIRCULAR_REASON,
        "bw_mm": bw,
        "hoop_diameter_mm": hoop,
        "fitted_z_mm": fitted_z,
        "asw_factor": bw / hoop if valid else None,
    }


def _unavailable_geometry(
    *,
    reason: str,
    section_form: str,
    resolved_form: str | None,
    bw_mm: float | None,
    duct_case: str,
    duct_sum_mm: float | None,
    duct_largest_mm: float | None,
    concrete_valid: bool = False,
    concrete_bw_mm: float | None = None,
) -> dict:
    """Build one fail-closed geometry record without resistance operands."""

    return {
        "valid": False,
        "concrete_valid": bool(concrete_valid),
        "links_valid": False,
        "reason": reason,
        "concrete_reason": None if concrete_valid else reason,
        "links_reason": reason,
        "section_form": section_form,
        "resolved_form": resolved_form,
        "bw_mm": bw_mm,
        "concrete_bw_mm": concrete_bw_mm,
        "links_bw_mm": None,
        "web_inclination_deg": None,
        "asw_factor": None,
        "hoop_diameter_mm": None,
        "fitted_z_mm": None,
        "duct_case": duct_case,
        "duct_sum_mm": duct_sum_mm,
        "duct_largest_mm": duct_largest_mm,
        "duct_factor_concrete": None,
        "duct_factor_links": None,
        "duct_threshold_mm": None,
        "duct_reduction_applied_concrete": False,
        "duct_reduction_applied_links": False,
    }


def resolve_shear_geometry(
    *,
    model_2023: bool,
    solid_rectangle: bool,
    section_form,
    bw_mm,
    bw_user: bool,
    links_present: bool,
    web_inclination_deg=0.0,
    hoop_diameter_mm=0.0,
    fitted_z_mm=0.0,
    duct_case=SHEAR_DUCT_NONE,
    duct_sum_mm=0.0,
    duct_largest_mm=0.0,
) -> dict:
    """Resolve the edition-specific section and duct operands before shear work.

    The function does not infer a variable or circular section from polygon points.
    Automatic treatment is intentionally limited to a solid rectangle.  Other
    sections need the governing web geometry selected by the engineer.  The return
    value keeps the physical web width separate from the nominal compression-field
    width and the effective shear-reinforcement factor.
    """

    form = str(section_form or SHEAR_SECTION_AUTO)
    case = str(duct_case or SHEAR_DUCT_NONE)
    bw = _finite_real(bw_mm)
    duct_sum = _finite_real(duct_sum_mm)
    duct_largest = _finite_real(duct_largest_mm)
    if form not in SHEAR_SECTION_FORMS or case not in SHEAR_DUCT_CASES:
        return _unavailable_geometry(
            reason=SHEAR_SECTION_GEOMETRY_REASON,
            section_form=form,
            resolved_form=None,
            bw_mm=bw,
            duct_case=case,
            duct_sum_mm=duct_sum,
            duct_largest_mm=duct_largest,
        )
    if bw is None or bw <= 0.0:
        return _unavailable_geometry(
            reason=SHEAR_SECTION_GEOMETRY_REASON,
            section_form=form,
            resolved_form=None,
            bw_mm=bw,
            duct_case=case,
            duct_sum_mm=duct_sum,
            duct_largest_mm=duct_largest,
        )

    resolved_form = form
    if form == SHEAR_SECTION_AUTO:
        if not solid_rectangle:
            return _unavailable_geometry(
                reason=SHEAR_SECTION_GEOMETRY_REASON,
                section_form=form,
                resolved_form=None,
                bw_mm=bw,
                duct_case=case,
                duct_sum_mm=duct_sum,
                duct_largest_mm=duct_largest,
            )
        resolved_form = SHEAR_SECTION_CONSTANT
    elif form == SHEAR_SECTION_CONSTANT and not solid_rectangle and not bw_user:
        return _unavailable_geometry(
            reason=SHEAR_SECTION_GEOMETRY_REASON,
            section_form=form,
            resolved_form=form,
            bw_mm=bw,
            duct_case=case,
            duct_sum_mm=duct_sum,
            duct_largest_mm=duct_largest,
        )
    elif resolved_form in {SHEAR_SECTION_VARIABLE, SHEAR_SECTION_CIRCULAR}:
        if not model_2023:
            return _unavailable_geometry(
                reason=SHEAR_SECTION_METHOD_REASON,
                section_form=form,
                resolved_form=resolved_form,
                bw_mm=bw,
                duct_case=case,
                duct_sum_mm=duct_sum,
                duct_largest_mm=duct_largest,
            )
        if not bw_user:
            return _unavailable_geometry(
                reason=(
                    SHEAR_VARIABLE_WIDTH_REASON
                    if resolved_form == SHEAR_SECTION_VARIABLE
                    else SHEAR_CIRCULAR_REASON
                ),
                section_form=form,
                resolved_form=resolved_form,
                bw_mm=bw,
                duct_case=case,
                duct_sum_mm=duct_sum,
                duct_largest_mm=duct_largest,
            )

    concrete_reason = None
    links_reason = None
    inclination = 0.0
    asw_factor = 1.0
    hoop = None
    fitted_z = None
    if links_present and resolved_form == SHEAR_SECTION_VARIABLE:
        inclination_value = _finite_real(web_inclination_deg)
        if (
            inclination_value is None
            or inclination_value < 0.0
            or inclination_value >= 90.0
        ):
            links_reason = SHEAR_VARIABLE_WIDTH_REASON
        else:
            inclination = inclination_value
            asw_factor = math.cos(math.radians(inclination))
            if not math.isfinite(asw_factor) or asw_factor <= 0.0:
                links_reason = SHEAR_VARIABLE_WIDTH_REASON
    elif links_present and resolved_form == SHEAR_SECTION_CIRCULAR:
        circular_geometry = resolve_circular_shear_geometry(
            bw_mm=bw,
            hoop_diameter_mm=hoop_diameter_mm,
            fitted_z_mm=fitted_z_mm,
        )
        hoop = circular_geometry["hoop_diameter_mm"]
        fitted_z = circular_geometry["fitted_z_mm"]
        if not circular_geometry["valid"]:
            links_reason = SHEAR_CIRCULAR_REASON
        else:
            asw_factor = circular_geometry["asw_factor"]

    # The selected case is authoritative; disabled controls may retain stale
    # numbers.  Dimensions are required only for a branch in which they can alter
    # the selected edition's resistance.
    if case == SHEAR_DUCT_NONE:
        duct_sum = 0.0
        duct_largest = 0.0
    threshold = bw / 8.0
    factor_concrete = 0.0
    factor_links = 0.0
    factors_2023 = {
        SHEAR_DUCT_GROUTED_STEEL: 0.5,
        SHEAR_DUCT_GROUTED_PLASTIC_THIN: 0.8,
        SHEAR_DUCT_GROUTED_PLASTIC_THICK: 1.2,
        SHEAR_DUCT_UNGROUTED_OR_SOFT: 1.2,
    }

    if model_2023:
        # Formula (8.54) applies to the compression-field branch.  The no-links
        # branch needs a duct allowance only for ungrouted or soft-filled ducts.
        if case == SHEAR_DUCT_DETAILS_INCOMPLETE:
            if links_present:
                links_reason = links_reason or SHEAR_DUCT_INPUT_REASON
            concrete_reason = SHEAR_DUCT_INPUT_REASON
        elif case == SHEAR_DUCT_UNGROUTED_OR_SOFT:
            if duct_sum is None or duct_sum <= 0.0:
                concrete_reason = SHEAR_DUCT_INPUT_REASON
                if links_present:
                    links_reason = links_reason or SHEAR_DUCT_INPUT_REASON
            elif duct_sum > threshold:
                factor_concrete = 1.2
        if links_present and case not in {
            SHEAR_DUCT_NONE,
            SHEAR_DUCT_DETAILS_INCOMPLETE,
        }:
            if duct_sum is None or duct_sum <= 0.0:
                links_reason = links_reason or SHEAR_DUCT_INPUT_REASON
            elif duct_sum > threshold:
                factor_links = factors_2023[case]
    elif links_present:
        # EN 1992-1-1:2005 6.2.3(6) changes V_Rd,max only.  A grouted
        # steel duct uses the largest-diameter threshold before the sum is needed;
        # plastic/ungrouted cases use the 1.2 sum directly.
        if case == SHEAR_DUCT_DETAILS_INCOMPLETE:
            links_reason = links_reason or SHEAR_DUCT_INPUT_REASON
        elif case == SHEAR_DUCT_GROUTED_STEEL:
            if duct_largest is None or duct_largest <= 0.0:
                links_reason = links_reason or SHEAR_DUCT_INPUT_REASON
            elif duct_largest > threshold:
                if duct_sum is None or duct_sum <= 0.0:
                    links_reason = links_reason or SHEAR_DUCT_INPUT_REASON
                else:
                    factor_links = 0.5
        elif case in {
            SHEAR_DUCT_GROUTED_PLASTIC_THIN,
            SHEAR_DUCT_GROUTED_PLASTIC_THICK,
            SHEAR_DUCT_UNGROUTED_OR_SOFT,
        }:
            if duct_sum is None or duct_sum <= 0.0:
                links_reason = links_reason or SHEAR_DUCT_INPUT_REASON
            else:
                factor_links = 1.2

    if (
        duct_sum is not None
        and duct_sum > 0.0
        and duct_largest is not None
        and (duct_largest < 0.0 or duct_largest > duct_sum)
    ):
        if model_2023 and case == SHEAR_DUCT_UNGROUTED_OR_SOFT:
            concrete_reason = SHEAR_DUCT_INPUT_REASON
        if links_present and case != SHEAR_DUCT_NONE:
            links_reason = links_reason or SHEAR_DUCT_INPUT_REASON

    concrete_bw = bw - factor_concrete * (duct_sum or 0.0)
    links_bw = bw - factor_links * (duct_sum or 0.0)
    if concrete_reason is None and (
        not math.isfinite(concrete_bw) or concrete_bw <= 0.0
    ):
        concrete_reason = SHEAR_NOMINAL_WIDTH_REASON
    if links_reason is None and (
        not math.isfinite(links_bw) or links_bw <= 0.0
    ):
        links_reason = SHEAR_NOMINAL_WIDTH_REASON

    concrete_valid = concrete_reason is None
    links_valid = links_reason is None
    return {
        "valid": bool(concrete_valid and (links_valid or not links_present)),
        "concrete_valid": concrete_valid,
        "links_valid": links_valid,
        "reason": concrete_reason or links_reason,
        "concrete_reason": concrete_reason,
        "links_reason": links_reason,
        "section_form": form,
        "resolved_form": resolved_form,
        "bw_mm": bw,
        "concrete_bw_mm": concrete_bw if concrete_valid else None,
        "links_bw_mm": links_bw if links_valid else None,
        "web_inclination_deg": inclination,
        "asw_factor": asw_factor,
        "hoop_diameter_mm": hoop,
        "fitted_z_mm": fitted_z,
        "duct_case": case,
        "duct_sum_mm": duct_sum,
        "duct_largest_mm": duct_largest,
        "duct_factor_concrete": factor_concrete,
        "duct_factor_links": factor_links,
        "duct_threshold_mm": threshold,
        "duct_reduction_applied_concrete": bool(factor_concrete > 0.0),
        "duct_reduction_applied_links": bool(factor_links > 0.0),
    }


def unassessed_shear_result(*, model: str, reason: str, bw_mm, d_mm, asl_mm2) -> dict:
    """Return the stable no-verdict payload used before a shear kernel is entered."""

    return {
        "vrd_c": None,
        "valid": False,
        "calculation_state": "NOT ASSESSED",
        "reason": reason,
        "model": model,
        "bw": bw_mm,
        "d": d_mm,
        "asl": asl_mm2,
        "z": None,
    }


def unassessed_links_result(
    *, model: str, reason: str, bw_mm, d_mm, asw_over_s, z_mm=None
) -> dict:
    """Return a stable reinforced-shear result with every verdict withheld."""

    return {
        "vrd_s": None,
        "vrd_max": None,
        "vrd": None,
        "cot": None,
        "theta_deg": None,
        "z": z_mm,
        "fywd": None,
        "asw_over_s": asw_over_s,
        "governs": "none",
        "valid": False,
        "calculation_state": "NOT ASSESSED",
        "reason": reason,
        "model": model,
        "bw": bw_mm,
        "d": d_mm,
        "cot_min": None,
        "cot_max": None,
        "tan": None,
        "sin_cos": None,
        "cot_unconstrained": None,
        "angle_selection": "none",
        "angle_a": None,
        "angle_b": None,
    }


STRUT_ANGLE_OUT_OF_RANGE_REASON = (
    "selected strut-angle range is outside the permitted method range"
)


def strut_angle_applicability(
    cot_min,
    cot_max,
    *,
    permitted_min,
    permitted_max,
    method: str,
    basis: str,
    clause: str,
    active: bool = True,
) -> dict:
    """Classify one requested compression-strut interval without tolerance.

    The requested interval is retained separately from any later optimiser or
    member-angle selection. Exact method boundaries are admissible; even the
    immediately adjacent representable value outside a boundary is not.
    """

    if type(active) is not bool:
        raise ValueError("strut-angle activity must be a Boolean")
    values = tuple(
        _finite_real(value)
        for value in (cot_min, cot_max, permitted_min, permitted_max)
    )
    if any(value is None for value in values):
        raise ValueError("strut-angle limits must be finite real numbers")
    cot_a, cot_b, permitted_lo, permitted_hi = tuple(
        value for value in values if value is not None
    )
    requested_lo = min(cot_a, cot_b)
    requested_hi = max(cot_a, cot_b)
    if requested_lo <= 0.0 or permitted_lo <= 0.0 or permitted_hi < permitted_lo:
        raise ValueError("strut-angle limits must form positive ordered intervals")
    outside_lower = requested_lo < permitted_lo
    outside_upper = requested_hi > permitted_hi
    applicable = not (outside_lower or outside_upper)
    return {
        "applicable": applicable,
        "active": active,
        "status": (
            "NOT APPLICABLE"
            if not active
            else "ASSESSED"
            if applicable
            else "NOT ASSESSED"
        ),
        "reason": (
            None
            if not active or applicable
            else STRUT_ANGLE_OUT_OF_RANGE_REASON
        ),
        "requested_min": requested_lo,
        "requested_max": requested_hi,
        "permitted_min": permitted_lo,
        "permitted_max": permitted_hi,
        "outside_lower": outside_lower,
        "outside_upper": outside_upper,
        "method": str(method),
        "basis": str(basis),
        "clause": str(clause),
    }


def unassessed_strut_angle_links_result(
    *,
    model: str,
    applicability: dict,
    bw_mm,
    d_mm,
    asw_over_s,
    z_mm=None,
) -> dict:
    """Return a reinforced-shear payload with no code-domain verdict."""

    result = unassessed_links_result(
        model=model,
        reason=STRUT_ANGLE_OUT_OF_RANGE_REASON,
        bw_mm=bw_mm,
        d_mm=d_mm,
        asw_over_s=asw_over_s,
        z_mm=z_mm,
    )
    result.update(
        cot_min=applicability["requested_min"],
        cot_max=applicability["requested_max"],
        angle_applicability=dict(applicability),
    )
    return result


def validate_gamma_v(value, *, label="gamma_v") -> float:
    """Return a positive factor that yields finite 2023 coefficients."""

    message = (
        f"{label} must be a positive finite real number that produces "
        "finite 2023 shear coefficients"
    )
    value_type = type(value)
    is_numpy_bool = (
        value_type.__name__ in {"bool", "bool_"}
        and value_type.__module__.split(".", 1)[0] == "numpy"
    )
    if isinstance(value, bool) or is_numpy_bool or isinstance(value, (str, bytes)):
        raise ValueError(message)
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(message) from exc
    if not math.isfinite(number) or number <= 0.0:
        raise ValueError(message)
    try:
        coefficients = (0.66 / number, 11.0 / number)
    except OverflowError as exc:
        raise ValueError(message) from exc
    if not all(math.isfinite(coefficient) for coefficient in coefficients):
        raise ValueError(message)
    return number


@dataclass(frozen=True, slots=True)
class StrutAngleSelection:
    """Final analytic variable-strut-angle selection and its direct operands.

    This is deliberately a single accepted state, not an angle-search history.  It
    retains the values needed to explain how the existing resistance optimum was
    selected inside the entered ``cot(theta)`` band.
    """

    cot: float
    tan: float
    theta_deg: float
    sin_cos: float
    cot_min: float
    cot_max: float
    cot_unconstrained: float
    selection: str


def _angle_fields(selection: StrutAngleSelection, a: float, b: float) -> dict:
    """Flatten one family-owned angle selection into a shear result payload."""

    return {
        "cot": selection.cot,
        "tan": selection.tan,
        "theta_deg": selection.theta_deg,
        "sin_cos": selection.sin_cos,
        "cot_min": selection.cot_min,
        "cot_max": selection.cot_max,
        "cot_unconstrained": selection.cot_unconstrained,
        "angle_selection": selection.selection,
        "angle_a": a,
        "angle_b": b,
    }


def _coord(point, axis: str) -> float:
    """The along-shear-axis coordinate of a point: y for vertical shear (axis 'x',
    bending about x), x for horizontal shear (axis 'y')."""
    return point[1] if axis == "x" else point[0]


def tension_reinforcement_selection(bars: Sequence, axis: str, tension_low: bool,
                                    centroid_coord: float):
    """Area, centroid and one-based IDs of the tension-side longitudinal bars.

    ``bars`` are ``(x, y, area_mm2)`` in metres; ``axis`` is the bending axis ('x' =
    vertical shear); ``tension_low`` True when the tension face is the low-coordinate
    side (bottom / left). The tension bars are those on the tension side of the
    section centroid. Returns ``(Asl_mm2, centroid_along_axis_m, bar_ids)``.
    The IDs follow the public bar numbering used in the UI and reports.
    """
    tens = []
    for i, b in enumerate(bars):
        c = _coord(b, axis)
        if (c < centroid_coord) if tension_low else (c > centroid_coord):
            tens.append((i + 1, b))
    area = sum(float(b[2]) for _, b in tens)
    if area <= 0.0:
        return 0.0, None, []
    cg = sum(float(b[2]) * _coord(b, axis) for _, b in tens) / area
    ids = [bar_id for bar_id, _ in tens]
    return area, cg, ids


def tension_reinforcement(bars: Sequence, axis: str, tension_low: bool,
                          centroid_coord: float):
    """Return the ``(area, centroid)`` tension-bar selection."""
    area, cg, _ = tension_reinforcement_selection(
        bars, axis, tension_low, centroid_coord
    )
    return area, cg


def effective_depth(outer: Sequence, axis: str, tension_low: bool,
                    tension_cg_coord: Optional[float]) -> float:
    """Effective depth ``d`` (mm): the distance from the extreme compression fibre
    (opposite the tension face) to the tension-reinforcement centroid, along the
    shear axis. Returns 0 when there is no tension reinforcement."""
    geometry.require_valid_section_topology(outer)
    if tension_cg_coord is None or not len(outer):
        return 0.0
    coords = [_coord(p, axis) for p in outer]
    comp_fibre = max(coords) if tension_low else min(coords)   # opposite the tension face
    return abs(comp_fibre - tension_cg_coord) * 1000.0         # m -> mm


def _line_solid_span(ring: Sequence, level: float, axis: str) -> float:
    """Total length of the ring's interior cut by the line at ``level`` (m).

    For vertical shear (``axis == 'x'``) the cutting line is ``y = level`` and the
    span is measured in x; the crossings of the closed polygon with the line, sorted
    and paired, give the inside intervals.
    """
    xs = []
    n = len(ring)
    for i in range(n):
        p, q = ring[i], ring[(i + 1) % n]
        cp, cq = _coord(p, axis), _coord(q, axis)   # coordinate compared to level
        wp = p[0] if axis == "x" else p[1]           # the width-direction coordinate
        wq = q[0] if axis == "x" else q[1]
        if (cp <= level < cq) or (cq <= level < cp):
            t = (level - cp) / (cq - cp)
            xs.append(wp + t * (wq - wp))
    xs.sort()
    return sum(xs[i + 1] - xs[i] for i in range(0, len(xs) - 1, 2))


def min_web_width(outer: Sequence, holes: Optional[Sequence], axis: str) -> float:
    """Smallest solid width perpendicular to the shear (mm).

    The solid width (outline minus voids) at a scanline is piecewise-linear in the
    scan level, with breakpoints exactly at the vertices of the outline and the voids
    (between two consecutive vertex levels every crossing moves linearly, so the total
    interior width does too). Its minimum over the sampled band is therefore attained
    at one of those breakpoints, so the width is evaluated at every outline / void
    vertex level -- not on a fixed grid, which could step over a thin void or notch and
    overestimate the web width. The band is the middle 80% of the depth, excluding the
    extreme fibres where a curved outline tapers to zero. Correct for the web of
    rectangular / T / box sections; a circular (or otherwise curved) section should
    have ``bw`` entered by hand, and the caller echoes the derived value for review.
    """
    geometry.require_valid_section_topology(outer, holes or [])
    if not len(outer):
        return 0.0
    coords = [_coord(p, axis) for p in outer]
    lo, hi = min(coords), max(coords)
    if hi - lo <= 0.0:
        return 0.0
    margin = 0.10 * (hi - lo)
    band_lo, band_hi = lo + margin, hi - margin
    # Breakpoints: the band edges plus every outline / void vertex level inside it.
    levels = {band_lo, band_hi}
    for ring in [outer, *(holes or [])]:
        for p in ring:
            c = _coord(p, axis)
            if band_lo < c < band_hi:
                levels.add(c)
    # Evaluate just either side of each breakpoint (not exactly on it, where the
    # scanline through a vertex or along a horizontal edge is degenerate); the width
    # is continuous, so this recovers the breakpoint value and hence the true minimum.
    eps = 1e-9 * (hi - lo)
    best = math.inf
    for level in levels:
        for lv in (level - eps, level + eps):
            if not (band_lo - eps <= lv <= band_hi + eps):
                continue
            w = _line_solid_span(outer, lv, axis)
            for hole in holes or []:
                w -= _line_solid_span(hole, lv, axis)
            best = min(best, max(w, 0.0))
    return best * 1000.0 if math.isfinite(best) else 0.0


def vrd_c_2023(fck: float, code, bw_mm: float, d_mm: float, asl_mm2: float,
               fyd_mpa: float, ddg_mm: float, *, n_ed_tension_kn: float = 0.0,
               m_ed_knm: float = 0.0, v_ed_kn: float = 0.0,
               gamma_v: Optional[float] = None) -> dict:
    """Shear resistance without shear reinforcement, EN 1992-1-1:2023 sec. 8.2.2.

    ``tau_Rd,c = (0.66/gamma_v)*(100*rho_l*fck*ddg/d_v)^(1/3) >= tau_Rd,c,min``
    (8.27), where axial force modifies the denominator through
    ``d_v = k_vp*d`` and
    ``k_vp = max(1 + NEd/abs(VEd)*d/(3*a_cs), 0.1)`` (8.31),
    ``a_cs = max(abs(MEd/VEd), d)`` (8.30). The 2023 sign convention is used here:
    ``n_ed_tension_kn`` is positive in tension. ``tau_Rd,c,min`` from (8.20) retains
    the nominal ``d`` because 8.2.2(4) applies ``k_vp`` specifically to the ``d`` in
    (8.27). The resistance is ``VRd,c = tau_Rd,c * bw * z`` with nominal
    ``z = 0.9 d`` (8.18). ``fyd_mpa`` is the design yield of the flexural
    reinforcement; ``ddg_mm`` the aggregate size parameter (8.2.1(4)).
    """
    gv = validate_gamma_v(
        code.shear_gamma_v if gamma_v is None else gamma_v
    )
    z = 0.9 * d_mm
    if d_mm <= 0.0 or bw_mm <= 0.0 or fyd_mpa <= 0.0:
        return dict(vrd_c=0.0, tau_rdc=0.0, tau_basic=0.0, tau_min=0.0, rho_l=0.0,
                    z=z, ddg=ddg_mm, fyd=fyd_mpa, k_vp=1.0,
                    d_kvp=d_mm, a_cs=0.0, n_ed_tension=n_ed_tension_kn,
                    m_ed=m_ed_knm, v_ed=v_ed_kn, axial_applied=False,
                    gamma_v=gv, model="2023", valid=False,
                    fck=fck, bw=bw_mm, d=d_mm, asl=asl_mm2,
                    tau_governs="none")
    rho_l = asl_mm2 / (bw_mm * d_mm)
    v_abs = abs(v_ed_kn)
    if v_abs > 1e-12:
        a_cs = max(abs(m_ed_knm) / v_abs * 1000.0, d_mm)
        k_vp = max(1.0 + n_ed_tension_kn / v_abs * d_mm / (3.0 * a_cs), 0.1)
        axial_applied = abs(n_ed_tension_kn) > 1e-12
    else:
        # No applied shear means there is no Formula (8.31) action ratio to form and
        # the utilisation is zero; retain the neutral factor rather than manufacture
        # an infinite resistance change.
        a_cs = 0.0
        k_vp = 1.0
        axial_applied = False
    d_kvp = k_vp * d_mm
    tau_min = (11.0 / gv) * math.sqrt(fck / fyd_mpa * ddg_mm / d_mm)          # MPa
    tau_basic = (0.66 / gv) * (
        100.0 * rho_l * fck * ddg_mm / d_kvp
    ) ** (1.0 / 3.0)
    tau_rdc = max(tau_basic, tau_min)                                        # MPa
    vrd_c_value = tau_rdc * bw_mm * z / 1000.0                               # kN
    if not all(math.isfinite(value) for value in (
        tau_min,
        tau_basic,
        tau_rdc,
        vrd_c_value,
    )):
        raise ValueError(
            "2023 shear calculation must produce finite resistance values"
        )
    return dict(vrd_c=vrd_c_value,
                 tau_rdc=tau_rdc, tau_basic=tau_basic, tau_min=tau_min, rho_l=rho_l,
                 z=z, ddg=ddg_mm, fyd=fyd_mpa, k_vp=k_vp, d_kvp=d_kvp,
                 a_cs=a_cs, n_ed_tension=n_ed_tension_kn, m_ed=m_ed_knm,
                 v_ed=v_ed_kn, axial_applied=axial_applied,
                 gamma_v=gv, model="2023", valid=True,
                 fck=fck, bw=bw_mm, d=d_mm, asl=asl_mm2,
                 tau_governs=("basic" if tau_basic >= tau_min else "minimum"))


def vrd_c(fck: float, code, bw_mm: float, d_mm: float, asl_mm2: float,
          n_ed_comp_kn: float, ac_m2: float, *, fyd_mpa: float = 0.0,
          ddg_mm: float = 32.0, m_ed_knm: float = 0.0,
          v_ed_kn: float = 0.0, fcd_mpa: Optional[float] = None,
          gamma_c: Optional[float] = None,
          gamma_v: Optional[float] = None) -> dict:
    """Shear resistance without shear reinforcement, VRd,c (kN).

    Dispatches on the code's ``shear_model``: the 2005 variable-strut VRd,c
    (sec. 6.2.2(1)) or the strain-based 2023 tau_Rd,c (sec. 8.2.2, via
    :func:`vrd_c_2023`, using ``fyd_mpa``, ``ddg_mm``, ``m_ed_knm`` and
    ``v_ed_kn``). ``n_ed_comp_kn`` is the axial force compression-positive
    (pass ``-N``); it is converted to the 2023 tension-positive convention for
    Formula (8.31). ``ac_m2`` is the gross concrete area.
    """
    if getattr(code, "shear_model", "2005") == "2023":
        return vrd_c_2023(
            fck, code, bw_mm, d_mm, asl_mm2, fyd_mpa, ddg_mm,
            n_ed_tension_kn=-n_ed_comp_kn, m_ed_knm=m_ed_knm,
            v_ed_kn=v_ed_kn, gamma_v=gamma_v,
        )
    gc = code.gamma_c if gamma_c is None else float(gamma_c)
    if d_mm <= 0.0 or bw_mm <= 0.0:
        return dict(vrd_c=0.0, k=0.0, rho_l=0.0, sigma_cp=0.0, fcd=0.0,
                    v_basic=0.0, v_floor=0.0, crd_c=0.0, vmin=0.0,
                    k1=code.shear_k1, gamma_c=gc, valid=False,
                    fck=fck, bw=bw_mm, d=d_mm, asl=asl_mm2,
                    ac=ac_m2, n_ed_comp=n_ed_comp_kn, rho_l_raw=0.0,
                    rho_l_cap=0.02, sigma_cp_raw=0.0, sigma_cp_cap=0.0,
                    stress=0.0, governs="none", model="2005")
    k = min(1.0 + math.sqrt(200.0 / d_mm), 2.0)
    rho_l_raw = asl_mm2 / (bw_mm * d_mm)
    rho_l = min(rho_l_raw, 0.02)
    fcd = (code.concrete_factor(fck) * fck / gc
           if fcd_mpa is None else float(fcd_mpa))                       # MPa
    sigma_cp_raw = n_ed_comp_kn / ac_m2 / 1000.0 if ac_m2 > 0 else 0.0
    sigma_cp_cap = 0.2 * fcd
    sigma_cp = min(sigma_cp_raw, sigma_cp_cap)                            # MPa
    crd_c = code.shear_crd_c_over_gamma(gc)
    vmin = code.shear_vmin(k, fck, gc)
    basic = crd_c * k * (100.0 * rho_l * fck) ** (1.0 / 3.0) + code.shear_k1 * sigma_cp
    floor = vmin + code.shear_k1 * sigma_cp
    stress = max(basic, floor, 0.0)                                       # MPa
    governs = "basic" if basic >= max(floor, 0.0) else (
        "minimum" if floor >= 0.0 else "zero"
    )
    return dict(vrd_c=stress * bw_mm * d_mm / 1000.0,                     # kN
                k=k, rho_l=rho_l, sigma_cp=sigma_cp, fcd=fcd,
                v_basic=basic, v_floor=floor, crd_c=crd_c, vmin=vmin,
                k1=code.shear_k1, gamma_c=gc, valid=True,
                fck=fck, bw=bw_mm, d=d_mm, asl=asl_mm2,
                ac=ac_m2, n_ed_comp=n_ed_comp_kn, rho_l_raw=rho_l_raw,
                rho_l_cap=0.02, sigma_cp_raw=sigma_cp_raw,
                sigma_cp_cap=sigma_cp_cap, stress=stress,
                governs=governs, model="2005")


def optimum_strut_angle(
    a: float, b: float, cot_min: float, cot_max: float
) -> StrutAngleSelection:
    """Return the accepted analytic strut angle and its publication operands."""

    if a <= 0.0:
        cot = cot_max
        unconstrained = math.inf
        basis = "no transverse reinforcement; upper bound"
    else:
        cot_star = math.sqrt(max(b / a - 1.0, 0.0))
        unconstrained = max(cot_star, 1.0)
        cot = min(max(unconstrained, cot_min), cot_max)
        if cot < unconstrained:
            basis = "upper bound"
        elif cot > unconstrained:
            basis = "lower bound"
        elif cot_star < 1.0:
            basis = "cot(theta) = 1 optimum"
        else:
            basis = "stirrup/crushing crossover"
    tan = 1.0 / cot
    return StrutAngleSelection(
        cot=cot,
        tan=tan,
        theta_deg=math.degrees(math.atan(tan)),
        sin_cos=cot / (1.0 + cot * cot),
        cot_min=cot_min,
        cot_max=cot_max,
        cot_unconstrained=unconstrained,
        selection=basis,
    )


def optimum_cot_theta(a: float, b: float, cot_min: float, cot_max: float) -> float:
    """Strut ``cot(theta)`` that maximises ``VRd = min(VRd,s, VRd,max)`` in the band.

    ``VRd,s = a*z*cot`` rises with ``cot(theta)``; ``VRd,max = b*z/(cot + 1/cot)``
    peaks at ``cot = 1`` (its denominator is minimal there) and falls away on *both*
    sides. So the unconstrained maximiser of ``VRd = min(...)`` is the crossover
    ``cot* = sqrt(b/a - 1)`` (where the two branches meet) when that is ``>= 1``, and
    ``cot = 1`` otherwise -- never below 1, since below it *both* branches fall.
    (``a = (Asw/s)*fywd``, ``b = alpha_cw*bw*nu1*fcd``; the lever arm ``z`` cancels.)
    This numerical helper clamps to the supplied band. Callers that publish a
    design verdict must first establish that the complete requested band is
    permitted for the selected method.
    """
    return optimum_strut_angle(a, b, cot_min, cot_max).cot


def compression_field_limits_2023(
    n_ed_tension_kn: float,
    v_ed_kn: float,
    ductility_class: str = "B",
) -> dict:
    """EN 1992-1-1:2023, 8.2.3(4), compression-field angle limits.

    Sector uses the directly verifiable branch:

    * class B/C, no axial tension: ``1 <= cot(theta) <= 2.5``;
    * axial tension: ``cot(theta)_max = max(2.5 - 0.1 NEd/|VEd|, 1)``;
    * class A: the upper limit is reduced by 20 %.

    The favourable extension towards 3.0 under significant axial compression also
    requires a sectional proof that the compression-chord depth ``x < 0.25 d``.
    Sector's isolated section action does not establish that member condition, so
    the extension is deliberately not credited.
    """
    ductility = str(ductility_class or "B").strip().upper()
    if ductility not in {"A", "B", "C"}:
        raise ValueError("ductility class must be A, B or C")
    n_tension = float(n_ed_tension_kn)
    v_abs = abs(float(v_ed_kn))
    upper = 2.5
    basis = "ordinary member; compression extension not credited"
    axial_tension_applied = bool(n_tension > 0.0 and v_abs > 0.0)
    if axial_tension_applied:
        upper = max(2.5 - 0.1 * n_tension / v_abs, 1.0)
        basis = "axial-tension limit"
    ductility_factor = 0.8 if ductility == "A" else 1.0
    upper = max(upper * ductility_factor, 1.0)
    return {
        "minimum": 1.0,
        "maximum": upper,
        "basis": basis,
        "ductility_class": ductility,
        "ductility_factor": ductility_factor,
        "axial_tension_applied": axial_tension_applied,
        "compression_extension_credited": False,
        "clause": "DS/EN 1992-1-1:2023, 8.2.3(4), Formula (8.41)",
    }


def _explicit_links_lever_arm(z_mm: Optional[float]) -> Optional[float]:
    """Return a positive finite calculated arm; never invent ``0.9 d``."""

    if z_mm is None or isinstance(z_mm, bool):
        return None
    try:
        value = float(z_mm)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) and value > 0.0 else None


LINKS_2023_AXIAL_COMPRESSION_REASON = (
    "2023 axial-compression applicability conditions were not demonstrated"
)


def _links_2023_axial_applicability(
    n_ed_comp_kn: float,
    ac_m2: Optional[float],
) -> dict:
    """Retain the axial-compression applicability evidence for 8.2.3(11).

    Sector's cross-section model retains the total net axial action, but it does
    not select an ``N_Edw`` allocation or establish the action-state compression-
    chord depth. It therefore cannot determine the simplified-method condition,
    the high-axial-force branch, or whether Annex G is required.
    """

    try:
        n_comp = float(n_ed_comp_kn)
        area = None if ac_m2 is None else float(ac_m2)
    except (TypeError, ValueError, OverflowError):
        n_comp = math.nan
        area = None
    input_valid = math.isfinite(n_comp) and (
        area is None or (math.isfinite(area) and area > 0.0)
    )
    compression_present = bool(input_valid and n_comp > 0.0)
    mean_compression = (
        n_comp / area / 1000.0
        if input_valid and area is not None
        else None
    )
    return {
        "input_valid": input_valid,
        "net_axial_compression_kn": n_comp if math.isfinite(n_comp) else None,
        "gross_concrete_area_m2": area if input_valid else None,
        "mean_compression_mpa": mean_compression,
        "compression_present": compression_present,
        "web_force_condition_required": compression_present,
        "web_force_condition_demonstrated": (
            False if compression_present else None
        ),
        "selected_web_force_kn": None,
        "web_force_limit_kn": None,
        "chord_depth_condition_required": (
            None if compression_present else False
        ),
        "chord_depth_condition_demonstrated": (
            False if compression_present else None
        ),
        "action_compression_chord_depth_mm": None,
        "compression_chord_depth_limit_mm": None,
        "simplified_method_applicable": bool(input_valid and not compression_present),
        "separate_member_assessment_required": compression_present,
        "annex_g_requirement_determined": (
            False if compression_present else None
        ),
        "clause": "DS/EN 1992-1-1:2023, 8.2.3(11) and Annex G",
    }


def vrd_links_2023(
    fck: float,
    code,
    bw_mm: float,
    d_mm: float,
    asw_over_s: float,
    fywk: float,
    cot_min: float,
    cot_max: float,
    z_mm: Optional[float] = None,
    *,
    fcd_mpa: Optional[float] = None,
    gamma_s: Optional[float] = None,
    v_ed_kn: float = 0.0,
    n_ed_comp_kn: float = 0.0,
    ac_m2: Optional[float] = None,
    ductility_class: str = "B",
    angle_applicability: Optional[dict] = None,
) -> dict:
    """Shear resistance with vertical links, EN 1992-1-1:2023, 8.2.3.

    The simplified compression-field method uses Formulae (8.42)-(8.44):
    ``tau_Rd,sy = rho_w*f_ywd*cot(theta)`` and
    ``tau_Ed*(cot(theta) + tan(theta)) <= nu*f_cd``, with ``nu = 0.5``
    according to 8.2.3(6). The returned ``V_Rd`` is the smaller of reinforcement
    yielding and compression-field crushing at the resistance-optimal angle inside
    the user-entered range.
    """
    # The simplified 2023 value nu = 0.5 is independent of fck, but retain fck as
    # entered so a worked calculation can show the complete given-data set.
    z = _explicit_links_lever_arm(z_mm)
    axial_applicability = _links_2023_axial_applicability(
        n_ed_comp_kn,
        ac_m2,
    )
    if math.isfinite(float(d_mm)) and float(d_mm) > 0.0:
        axial_applicability["compression_chord_depth_limit_mm"] = 0.25 * float(
            d_mm
        )
    gs = code.gamma_s if gamma_s is None else float(gamma_s)
    # Callers must supply the final user-defined design strength. Reconstructing it
    # from a preset here could silently ignore edited partial factors.
    fcd = 0.0 if fcd_mpa is None else float(fcd_mpa)
    if axial_applicability["compression_present"]:
        return dict(
            vrd_s=None,
            vrd_max=None,
            vrd=None,
            cot=None,
            theta_deg=None,
            z=None,
            fywd=None,
            nu=0.5,
            nu1=0.5,
            alpha_cw=None,
            sigma_cp=axial_applicability["mean_compression_mpa"],
            fcd=fcd,
            gamma_s=gs,
            asw_over_s=asw_over_s,
            rho_w=None,
            tau_ed=None,
            tau_rd_sy=None,
            tau_rd_max=None,
            sigma_cd=None,
            nu_fcd=None,
            governs="none",
            model="2023",
            axial_applicability=axial_applicability,
            valid=False,
            calculation_state="NOT ASSESSED",
            reason=LINKS_2023_AXIAL_COMPRESSION_REASON,
            fck=fck,
            bw=bw_mm,
            d=d_mm,
            fywk=fywk,
            cot_min=cot_min,
            cot_max=cot_max,
            tan=None,
            sin_cos=None,
            cot_unconstrained=None,
            angle_selection="none",
            angle_a=None,
            angle_b=None,
        )
    if (
        z is None
        or d_mm <= 0.0
        or bw_mm <= 0.0
        or asw_over_s <= 0.0
        or fcd <= 0.0
        or gs <= 0.0
        or not axial_applicability["input_valid"]
    ):
        arm_unavailable = z is None
        unavailable_value = None if arm_unavailable else 0.0
        invalid = dict(
            vrd_s=unavailable_value,
            vrd_max=unavailable_value,
            vrd=unavailable_value,
            cot=unavailable_value,
            theta_deg=unavailable_value,
            z=z,
            fywd=0.0,
            nu=0.5,
            nu1=0.5,
            alpha_cw=1.0,
            sigma_cp=0.0,
            fcd=fcd,
            gamma_s=gs,
            asw_over_s=asw_over_s,
            rho_w=0.0,
            tau_ed=0.0,
            tau_rd_sy=0.0,
            tau_rd_max=0.0,
            sigma_cd=0.0,
            nu_fcd=0.5 * max(fcd, 0.0),
            governs="none",
            model="2023",
            axial_applicability=axial_applicability,
            valid=False,
            calculation_state=("NOT ASSESSED" if arm_unavailable else "INVALID"),
            reason=(
                "exact calculated plastic lever arm z is unavailable"
                if arm_unavailable
                else "invalid reinforced-shear input"
            ),
        )
        invalid.update(
            fck=fck,
            bw=bw_mm,
            d=d_mm,
            fywk=fywk,
            cot_min=cot_min,
            cot_max=cot_max,
            tan=0.0,
            sin_cos=0.0,
            cot_unconstrained=0.0,
            angle_selection="none",
            angle_a=0.0,
            angle_b=0.0,
        )
        return invalid
    if angle_applicability is None:
        limits = compression_field_limits_2023(
            -float(n_ed_comp_kn),
            v_ed_kn,
            ductility_class,
        )
        angle_applicability = strut_angle_applicability(
            cot_min,
            cot_max,
            permitted_min=limits["minimum"],
            permitted_max=limits["maximum"],
            method=getattr(code, "label", "DS/EN 1992-1-1:2023"),
            basis=limits["basis"],
            clause=limits["clause"],
            active=abs(float(v_ed_kn)) > 0.0,
        )
    if (
        angle_applicability.get("active", True) is True
        and angle_applicability.get("applicable") is not True
    ):
        return unassessed_strut_angle_links_result(
            model="2023",
            applicability=angle_applicability,
            bw_mm=bw_mm,
            d_mm=d_mm,
            asw_over_s=asw_over_s,
            z_mm=z,
        )
    fywd = fywk / gs
    nu = 0.5
    rho_w = asw_over_s / bw_mm
    a = asw_over_s * fywd
    b = bw_mm * nu * fcd
    angle = optimum_strut_angle(a, b, cot_min, cot_max)
    cot = angle.cot
    tan = angle.tan
    vrd_s = a * z * cot / 1000.0
    vrd_max = b * z / (cot + tan) / 1000.0
    vrd = min(vrd_s, vrd_max)
    tau_ed = abs(float(v_ed_kn)) * 1000.0 / (bw_mm * z)
    tau_rd_sy = rho_w * fywd * cot
    tau_rd_max = nu * fcd / (cot + tan)
    sigma_cd = tau_ed * (cot + tan)
    governs = (
        "links (tau_Rd,sy)" if vrd_s <= vrd_max
        else "compression field (sigma_cd)"
    )
    result = dict(
        vrd_s=vrd_s,
        vrd_max=vrd_max,
        vrd=vrd,
        cot=cot,
        theta_deg=math.degrees(math.atan(tan)),
        z=z,
        fywd=fywd,
        nu=nu,
        nu1=nu,
        alpha_cw=1.0,
        sigma_cp=0.0,
        fcd=fcd,
        gamma_s=gs,
        asw_over_s=asw_over_s,
        rho_w=rho_w,
        tau_ed=tau_ed,
        tau_rd_sy=tau_rd_sy,
        tau_rd_max=tau_rd_max,
        sigma_cd=sigma_cd,
        nu_fcd=nu * fcd,
        governs=governs,
        model="2023",
        axial_applicability=axial_applicability,
        valid=True,
    )
    result.update(
        _angle_fields(angle, a, b),
        fck=fck,
        bw=bw_mm,
        d=d_mm,
        fywk=fywk,
        angle_applicability=dict(angle_applicability),
    )
    return result


def vrd_links(fck: float, code, bw_mm: float, d_mm: float, asw_over_s: float,
              fywk: float, n_ed_comp_kn: float, ac_m2: float, cot_min: float,
              cot_max: float, z_mm: Optional[float] = None, *,
              fcd_mpa: Optional[float] = None,
              gamma_s: Optional[float] = None,
              v_ed_kn: float = 0.0,
              ductility_class: str = "B",
              angle_applicability: Optional[dict] = None) -> dict:
    """Shear resistance of a member with vertical links.

    Dispatches to the EN 1992-1-1:2023 compression-field method (8.2.3) or the
    2005-family variable-strut method (6.2.3). In both cases the resistance is
    ``min(VRd,s, VRd,max)`` at the resistance-optimal angle inside the supplied
    range.
    """
    if getattr(code, "shear_model", "2005") == "2023":
        return vrd_links_2023(
            fck,
            code,
            bw_mm,
            d_mm,
            asw_over_s,
            fywk,
            cot_min,
            cot_max,
            z_mm=z_mm,
            fcd_mpa=fcd_mpa,
            gamma_s=gamma_s,
            v_ed_kn=v_ed_kn,
            n_ed_comp_kn=n_ed_comp_kn,
            ac_m2=ac_m2,
            ductility_class=ductility_class,
            angle_applicability=angle_applicability,
        )
    z = _explicit_links_lever_arm(z_mm)
    gs = code.gamma_s if gamma_s is None else float(gamma_s)
    if z is None or d_mm <= 0.0 or bw_mm <= 0.0 or asw_over_s <= 0.0:
        arm_unavailable = z is None
        unavailable_value = None if arm_unavailable else 0.0
        return dict(vrd_s=unavailable_value, vrd_max=unavailable_value,
                    vrd=unavailable_value, cot=unavailable_value,
                    theta_deg=unavailable_value, z=z,
                    fywd=0.0, nu1=0.0, alpha_cw=0.0, sigma_cp=0.0, fcd=0.0,
                    gamma_s=gs, asw_over_s=asw_over_s, governs="none",
                    valid=False, fck=fck, bw=bw_mm, d=d_mm, fywk=fywk,
                    cot_min=cot_min, cot_max=cot_max, tan=0.0, sin_cos=0.0,
                    cot_unconstrained=0.0, angle_selection="none",
                    angle_a=0.0, angle_b=0.0, model="2005",
                    calculation_state=(
                        "NOT ASSESSED" if arm_unavailable else "INVALID"
                    ),
                    reason=(
                        "exact calculated plastic lever arm z is unavailable"
                        if arm_unavailable
                        else "invalid reinforced-shear input"
                    ))
    if angle_applicability is None:
        angle_applicability = strut_angle_applicability(
            cot_min,
            cot_max,
            permitted_min=code.shear_cot_min_limit,
            permitted_max=code.shear_cot_max_limit,
            method=getattr(code, "label", "EN 1992-1-1:2005"),
            basis="2005-family compression-strut range",
            clause="EN 1992-1-1:2005, 6.2.3(2), Formula (6.7N)",
            active=abs(float(v_ed_kn)) > 0.0,
        )
    if (
        angle_applicability.get("active", True) is True
        and angle_applicability.get("applicable") is not True
    ):
        return unassessed_strut_angle_links_result(
            model="2005",
            applicability=angle_applicability,
            bw_mm=bw_mm,
            d_mm=d_mm,
            asw_over_s=asw_over_s,
            z_mm=z,
        )
    fcd = (code.concrete_factor(fck) * fck / code.gamma_c
           if fcd_mpa is None else float(fcd_mpa))                       # MPa
    fywd = fywk / gs                                                     # MPa
    nu1 = code.shear_nu1(fck)
    # sigma_cp for alpha_cw is the mean axial stress (compression positive), NOT capped
    # at 0.2 fcd (6.11N spans the full 0..fcd range).
    sigma_cp = n_ed_comp_kn / ac_m2 / 1000.0 if ac_m2 > 0.0 else 0.0      # MPa
    alpha_cw = code.shear_alpha_cw(sigma_cp, fcd)
    a = asw_over_s * fywd                                                 # N/mm
    b = alpha_cw * bw_mm * nu1 * fcd                                      # N/mm
    angle = optimum_strut_angle(a, b, cot_min, cot_max)
    cot = angle.cot
    vrd_s = asw_over_s * z * fywd * cot / 1000.0                          # kN
    vrd_max = alpha_cw * bw_mm * z * nu1 * fcd / (cot + 1.0 / cot) / 1000.0  # kN
    vrd = min(vrd_s, vrd_max)
    governs = "stirrups (VRd,s)" if vrd_s <= vrd_max else "crushing (VRd,max)"
    result = dict(vrd_s=vrd_s, vrd_max=vrd_max, vrd=vrd,
                  z=z, fywd=fywd, nu1=nu1, alpha_cw=alpha_cw, sigma_cp=sigma_cp,
                  fcd=fcd, gamma_s=gs, asw_over_s=asw_over_s,
                  governs=governs, valid=True, fck=fck, bw=bw_mm, d=d_mm,
                  fywk=fywk, model="2005")
    result.update(
        _angle_fields(angle, a, b),
        angle_applicability=dict(angle_applicability),
    )
    return result
