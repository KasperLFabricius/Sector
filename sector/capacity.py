"""Headless orchestration helpers for member shear, torsion and M-V-T checks.

The Streamlit application owns widgets and session state; this module owns the
calculation contexts and result-payload assembly that do not depend on Streamlit.
Keeping that boundary explicit makes the engineering logic directly unit-testable
and prevents UI reruns from becoming the only way to exercise member checks.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from importlib import import_module
from typing import Any

from . import codes

SHEAR_CODES = {c.label: c for c in (codes.EC2_2005_DKNA, codes.EC2_2005)}
SHEAR_METHODS = dict(SHEAR_CODES, **{codes.EC2_2023.label: codes.EC2_2023})
_MISSING = object()


def _module(name: str):
    """Resolve one calculation dependency only when its family is requested."""

    return import_module(f".{name}", __package__)


class CapacityInputError(ValueError):
    """Expected invalid input at a member-capacity boundary."""


class CapacityMethodError(CapacityInputError):
    """An exact selected capacity-method identity is unsupported."""


class CapacityResultError(ArithmeticError):
    """A retained low-level solver violated its published result contract."""


@dataclass(frozen=True, slots=True)
class CombinedInteractionAuthority:
    """Authoritative shared-stirrup applicability and retained evidence state."""

    links_required: bool
    expected_asw_over_s: float | None
    retained_asw_over_s: float | None
    retained_current: bool
    interaction_required: bool


@dataclass(frozen=True, slots=True)
class LockedInPrestressTendon:
    """One tendon's locked-in elastic prestress contribution.

    ``tendon_index`` is the zero-based solver index. Coordinates are in metres,
    area in mm2, strain is dimensionless, modulus and stress are in MPa, force
    is in kN, and moment contributions are in kNm.
    """

    tendon_index: int
    element_id: str
    initial_strain: float
    modulus_mpa: float
    locked_in_stress_mpa: float
    area_mm2: float
    force_kn: float
    x_m: float
    y_m: float
    mx_knm: float
    my_knm: float


@dataclass(frozen=True, slots=True)
class LockedInPrestressResult:
    """Locked-in tendon forces and their resultants about a declared origin."""

    origin_x_m: float
    origin_y_m: float
    tendons: tuple[LockedInPrestressTendon, ...]
    total_n_kn: float
    total_mx_knm: float
    total_my_knm: float

    @property
    def resultants(self) -> tuple[float, float, float]:
        """Return the historical ``(N, Mx, My)`` tuple in kN/kNm."""

        return self.total_n_kn, self.total_mx_knm, self.total_my_knm


def plastic_capacity_at_angle(*args, **kwargs):
    """Resolve the plastic point solver only when a capacity check needs it.

    This named seam deliberately remains on :mod:`sector.capacity`: retained
    tests and callers can replace it independently, while importing the member
    orchestration module no longer imports or compiles the plastic kernels.
    """

    from .plastic import plastic_capacity_at_angle as solve

    return solve(*args, **kwargs)


def conditional_capacity(*args, **kwargs):
    """Resolve the conditional chord solver only at calculation time."""

    from .plastic import conditional_capacity as solve

    return solve(*args, **kwargs)


def _is_boolean_scalar(value):
    """Recognise built-in and common library Boolean scalar types."""
    scalar_type = type(value)
    module_root = scalar_type.__module__.partition(".")[0]
    type_name = scalar_type.__name__.lower().rstrip("_")
    return isinstance(value, bool) or (
        module_root in {"numpy", "pandas"}
        and type_name in {"bool", "boolean"}
    )


def combined_angle_objective_r_m(plastic: object) -> float | None:
    """Return validated bending utilisation for a pre-selection angle scan.

    This non-certifying seam consumes only the already-built plastic result.
    It does not inspect shear, links, torsion, angle selection, or final
    combined-result evidence.
    """

    if not isinstance(plastic, Mapping):
        return None
    if any(
        plastic.get(key, _MISSING) is not True
        for key in ("converged", "closed", "check_util", "util_valid")
    ):
        return None

    value = plastic.get("util", _MISSING)
    if _is_boolean_scalar(value) or isinstance(value, (str, bytes)):
        return None
    try:
        r_m = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return r_m if math.isfinite(r_m) and r_m >= 0.0 else None


def _positive_finite_real(value, label):
    """Return one calculation coefficient, rejecting only malformed values."""
    if _is_boolean_scalar(value) or isinstance(value, (str, bytes)):
        raise CapacityInputError(
            f"{label} must be a positive finite real number"
        )
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CapacityInputError(
            f"{label} must be a positive finite real number"
        ) from exc
    if not math.isfinite(number) or number <= 0.0:
        raise CapacityInputError(
            f"{label} must be a positive finite real number"
        )
    return number


def _nonnegative_finite_real(value: Any, label: str) -> float:
    if _is_boolean_scalar(value) or isinstance(value, (str, bytes)):
        raise CapacityInputError(
            f"{label} must be a non-negative finite real number"
        )
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CapacityInputError(
            f"{label} must be a non-negative finite real number"
        ) from exc
    if not math.isfinite(number) or number < 0.0:
        raise CapacityInputError(
            f"{label} must be a non-negative finite real number"
        )
    return number


def combined_interaction_authority(
    inp: object,
    torsion_out: object,
) -> CombinedInteractionAuthority:
    """Bind shared-interaction applicability to the input stirrup geometry.

    Torsion uses one leg of the closed shear stirrup.  The retained torsion
    reinforcement ratio is evidence only: it cannot turn off the shared 6.29
    interaction when the input declares active links.
    """

    if not isinstance(inp, Mapping):
        raise CapacityInputError("combined input must be a mapping")
    links_required = inp.get("shear_links", _MISSING)
    if type(links_required) is not bool:
        raise CapacityInputError(
            "combined shear-links selection must be a concrete Boolean"
        )
    if not links_required:
        return CombinedInteractionAuthority(
            links_required=False,
            expected_asw_over_s=None,
            retained_asw_over_s=None,
            retained_current=True,
            interaction_required=False,
        )

    diameter = _positive_finite_real(
        inp.get("shear_link_dia", _MISSING),
        "shared stirrup diameter",
    )
    spacing = _positive_finite_real(
        inp.get("shear_link_s", _MISSING),
        "shared stirrup spacing",
    )
    try:
        expected_value = _module("templates").bar_area(diameter) / spacing
    except ArithmeticError as exc:
        raise CapacityInputError(
            "shared stirrup reinforcement ratio must be a positive finite real number"
        ) from exc
    expected = _positive_finite_real(
        expected_value,
        "shared stirrup reinforcement ratio",
    )

    retained = None
    if isinstance(torsion_out, Mapping):
        value = torsion_out.get("asw_over_s", _MISSING)
        if not _is_boolean_scalar(value) and not isinstance(value, (str, bytes)):
            try:
                candidate = float(value)
            except (TypeError, ValueError, OverflowError):
                candidate = math.nan
            if math.isfinite(candidate) and candidate >= 0.0:
                retained = candidate

    return CombinedInteractionAuthority(
        links_required=True,
        expected_asw_over_s=expected,
        retained_asw_over_s=retained,
        retained_current=bool(
            retained is not None
            and math.isclose(retained, expected, rel_tol=1e-12, abs_tol=0.0)
        ),
        interaction_required=True,
    )


def combined_longitudinal_chord_evidence_is_valid(
    links: object,
    *,
    shear_axis: str,
    shear_tension_low: bool,
    shear_live: bool,
    torsion_live: bool,
    torsion_subdivided: bool,
) -> bool:
    """Return whether retained link chords cover every required live face."""

    if (
        type(shear_axis) is not str
        or shear_axis not in {"x", "y"}
        or type(shear_tension_low) is not bool
        or any(
        type(value) is not bool
        for value in (shear_live, torsion_live, torsion_subdivided)
        )
    ):
        return False
    if not shear_live and not torsion_live:
        return True
    if torsion_live and torsion_subdivided:
        return False
    if not isinstance(links, Mapping):
        return False

    candidates = links.get("chord_candidates", _MISSING)
    if not isinstance(candidates, (list, tuple)) or not candidates:
        return False

    face_keys: set[tuple[str, str, bool]] = set()
    shear_candidates: list[Mapping[str, Any]] = []
    off_candidates: list[Mapping[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            return False
        if candidate.get("valid", _MISSING) is not True:
            return False
        if candidate.get("conditional", _MISSING) is not True:
            return False
        role = candidate.get("role", _MISSING)
        axis = candidate.get("axis", _MISSING)
        tension_low = candidate.get("tension_low", _MISSING)
        if (
            type(role) is not str
            or role not in {"shear_axis", "off_axis"}
            or type(axis) is not str
            or axis not in {"x", "y"}
            or type(tension_low) is not bool
        ):
            return False
        utilisation = candidate.get("util", _MISSING)
        if _is_boolean_scalar(utilisation) or isinstance(
            utilisation,
            (str, bytes),
        ):
            return False
        try:
            utilisation_value = float(utilisation)
        except (TypeError, ValueError, OverflowError):
            return False
        if math.isnan(utilisation_value) or utilisation_value < 0.0:
            return False
        if candidate.get("off_not_evaluated", None) is not None:
            return False

        face_key = (role, axis, tension_low)
        if face_key in face_keys:
            return False
        face_keys.add(face_key)
        if role == "shear_axis":
            if (
                "off_not_evaluated" not in candidate
                or candidate.get("off_not_evaluated") is not None
                or candidate.get("has_torsion", _MISSING) is not torsion_live
                or type(candidate.get("gets_shift", _MISSING)) is not bool
            ):
                return False
            shear_candidates.append(candidate)
        else:
            off_candidates.append(candidate)

    if not torsion_live:
        return bool(
            shear_live
            and len(candidates) == 1
            and len(shear_candidates) == 1
            and not off_candidates
            and shear_candidates[0]["axis"] == shear_axis
            and shear_candidates[0]["tension_low"] is shear_tension_low
            and shear_candidates[0]["gets_shift"] is True
        )

    shifted_candidates = [
        item for item in shear_candidates if item["gets_shift"] is True
    ]
    if (
        len(candidates) != 4
        or len(shear_candidates) != 2
        or len(off_candidates) != 2
        or len(shifted_candidates) != 1
    ):
        return False
    off_axis = "y" if shear_axis == "x" else "x"
    return bool(
        {item["axis"] for item in shear_candidates} == {shear_axis}
        and {item["axis"] for item in off_candidates} == {off_axis}
        and shifted_candidates[0]["tension_low"] is shear_tension_low
        and {item["tension_low"] for item in shear_candidates} == {True, False}
        and {item["tension_low"] for item in off_candidates} == {True, False}
    )


def _rings_are_equivalent(left: object, right: object) -> bool:
    """Compare one polygon ring modulo benign serialization differences."""

    geometry = _module("geometry")
    left_ring = geometry.ring_without_terminal_closure(left)
    right_ring = geometry.ring_without_terminal_closure(right)
    if left_ring.shape != right_ring.shape or len(left_ring) < 3:
        return False

    left_points = tuple((float(point[0]), float(point[1])) for point in left_ring)
    right_points = tuple(
        (float(point[0]), float(point[1])) for point in right_ring
    )

    def points_match(
        first: tuple[float, float],
        second: tuple[float, float],
    ) -> bool:
        return first == second

    for candidate in (right_points, tuple(reversed(right_points))):
        for offset in range(len(candidate)):
            if all(
                points_match(
                    left_points[index],
                    candidate[(index + offset) % len(candidate)],
                )
                for index in range(len(candidate))
            ):
                return True
    return False


def _section_and_raw_rings_are_equivalent(
    section: object,
    outer: object,
    holes: object,
) -> bool:
    """Bind a Section's stored rings to the separately retained raw geometry."""

    validator = getattr(section, "require_valid_geometry", None)
    if not callable(validator):
        return True
    concrete = getattr(section, "concrete", _MISSING)
    if not isinstance(concrete, (list, tuple)) or not isinstance(
        holes, (list, tuple)
    ):
        return False
    section_rings = list(concrete)
    raw_holes = list(holes)
    if (
        not section_rings
        or len(section_rings) != len(raw_holes) + 1
        or not _rings_are_equivalent(section_rings[0], outer)
    ):
        return False

    unmatched_holes = list(raw_holes)
    for section_hole in section_rings[1:]:
        for index, raw_hole in enumerate(unmatched_holes):
            if _rings_are_equivalent(section_hole, raw_hole):
                unmatched_holes.pop(index)
                break
        else:
            return False
    return not unmatched_holes


def combined_torsion_subdivision_geometry_is_valid(inp: object) -> bool:
    """Validate both Section-owned and raw subdivision geometry authority.

    A real ``Section`` may own a richer geometry validator, while the retained
    raw outline and holes are still consumed later by the torsion producer.
    Both representations must therefore pass and describe the same concrete
    before a later subdivision-input seam can assess wall thickness or
    rectangle coverage.
    """

    if (
        not isinstance(inp, Mapping)
        or "outer" not in inp
        or "holes" not in inp
    ):
        return False
    retained_holes = inp["holes"]
    if retained_holes is not None and not isinstance(
        retained_holes, (list, tuple)
    ):
        return False
    try:
        section = inp.get("section")
        section_validator = getattr(section, "require_valid_geometry", None)
        if callable(section_validator) and not isinstance(
            getattr(section, "concrete", _MISSING), (list, tuple)
        ):
            return False
        raw_holes = [] if retained_holes is None else retained_holes
        _require_valid_input_geometry(inp)
        _module("geometry").require_valid_section_topology(
            inp["outer"],
            raw_holes,
        )
        if not _section_and_raw_rings_are_equivalent(
            section,
            inp["outer"],
            raw_holes,
        ):
            return False
    except (ArithmeticError, KeyError, TypeError, ValueError, OverflowError):
        return False
    return True


def combined_torsion_subdivision_input_is_valid(inp: object) -> bool:
    """Validate one requested subdivision's partition and wall-override input.

    Retained sub-tube results are deliberately outside this dormant seam. A
    later assessment may compare them only after the exact geometry authority,
    automatic wall-thickness choice, and rectangle partition pass here.
    """

    def finite_number(value: object) -> float | None:
        if _is_boolean_scalar(value) or isinstance(value, (str, bytes)):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return number if math.isfinite(number) else None

    def millimetres_to_metres(value: object) -> float | None:
        if _is_boolean_scalar(value) or isinstance(value, (str, bytes)):
            return None
        try:
            metres = value / 1000.0  # type: ignore[operator]
            number = float(metres)
        except (TypeError, ValueError, OverflowError):
            return None
        return number if math.isfinite(number) else None

    if (
        not isinstance(inp, Mapping)
        or inp.get("torsion_subdivide", _MISSING) is not True
        or not combined_torsion_subdivision_geometry_is_valid(inp)
    ):
        return False

    wall_override = finite_number(inp.get("torsion_tef", _MISSING))
    raw_rectangles = inp.get("torsion_subrects", _MISSING)
    if (
        wall_override is None
        or wall_override != 0.0
        or not isinstance(raw_rectangles, (list, tuple))
        or not raw_rectangles
    ):
        return False

    rectangles_m: list[tuple[float, float, float, float]] = []
    total_rectangle_area_m2 = 0.0
    for raw_rectangle in raw_rectangles:
        if not isinstance(raw_rectangle, (list, tuple)) or len(raw_rectangle) != 4:
            return False
        x_m = millimetres_to_metres(raw_rectangle[0])
        y_m = millimetres_to_metres(raw_rectangle[1])
        b_m = millimetres_to_metres(raw_rectangle[2])
        h_m = millimetres_to_metres(raw_rectangle[3])
        if (
            x_m is None
            or y_m is None
            or b_m is None
            or h_m is None
            or b_m <= 0.0
            or h_m <= 0.0
        ):
            return False
        rectangle_m = (x_m, y_m, b_m, h_m)
        rectangle_area_m2 = rectangle_m[2] * rectangle_m[3]
        total_rectangle_area_m2 += rectangle_area_m2
        if (
            not all(math.isfinite(value) for value in rectangle_m)
            or rectangle_area_m2 <= 0.0
            or not math.isfinite(rectangle_area_m2)
            or not math.isfinite(total_rectangle_area_m2)
        ):
            return False
        rectangles_m.append(rectangle_m)

    raw_holes = [] if inp["holes"] is None else inp["holes"]
    try:
        partition_valid, _reason = _module(
            "geometry"
        ).rectangles_partition_concrete(
            inp["outer"],
            raw_holes,
            rectangles_m,
        )
    except (ArithmeticError, KeyError, TypeError, ValueError, OverflowError):
        return False
    return partition_valid is True


def _selected_code(
    methods: Mapping[str, codes.DesignCode],
    value: object,
    label: str,
) -> codes.DesignCode:
    if type(value) is not str or value not in methods:
        raise CapacityMethodError(f"unsupported {label}: {value!r}")
    return methods[value]


def selected_shear_code(value: object) -> codes.DesignCode:
    """Resolve one exact supported shear-method identity without a default."""
    return _selected_code(SHEAR_METHODS, value, "shear method")


def selected_torsion_code(value: object) -> codes.DesignCode:
    """Resolve one exact supported torsion-method identity."""
    return _selected_code(SHEAR_CODES, value, "torsion method")


def selected_combined_code(value: object) -> codes.DesignCode:
    """Resolve one exact supported combined-method identity."""
    return _selected_code(SHEAR_CODES, value, "combined method")


def _finite_solver_result(value: Any, label: str) -> float:
    if _is_boolean_scalar(value) or isinstance(value, (str, bytes)):
        raise CapacityResultError(f"{label} must be a finite real result")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CapacityResultError(
            f"{label} must be a finite real result"
        ) from exc
    if not math.isfinite(number):
        raise CapacityResultError(f"{label} must be a finite real result")
    return number


def _solver_flag(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise CapacityResultError(f"{label} must be a concrete Boolean result")
    return value


def _solver_member(result: object, name: str, label: str) -> object:
    value = getattr(result, name, _MISSING)
    if value is _MISSING:
        raise CapacityResultError(f"{label} is missing returned member {name}")
    return value


def _face_angle(axis: object, tension_low: object) -> float:
    if (
        not isinstance(axis, str)
        or axis not in ("x", "y")
        or type(tension_low) is not bool
    ):
        raise CapacityInputError(
            "capacity face identity requires axis x or y and a Boolean face"
        )
    from .plastic import FACE_ANGLE

    return FACE_ANGLE[(axis, tension_low)]


def _require_valid_input_geometry(inp):
    """Validate either a real Section or the raw headless geometry payload."""
    section = inp.get("section")
    validator = getattr(section, "require_valid_geometry", None)
    if callable(validator):
        validator()
        return
    _module("geometry").require_valid_section_topology(
        inp["outer"], inp.get("holes") or []
    )


def gross_area_centroid(outer, holes):
    """Return net concrete area (m2) and centroid ``(cx, cy)`` in metres."""
    geometry = _module("geometry")
    geometry.require_valid_section_topology(outer, holes or [])
    mo = geometry.area_moments(outer)
    area = abs(mo.area)
    if area <= 0.0:
        return 0.0, 0.0, 0.0
    cx, cy = mo.sx / mo.area, mo.sy / mo.area
    net_area, mx, my = area, cx * area, cy * area
    for hole in holes or []:
        mh = geometry.area_moments(hole)
        hole_area = abs(mh.area)
        if hole_area <= 0.0:
            continue
        net_area -= hole_area
        mx -= (mh.sx / mh.area) * hole_area
        my -= (mh.sy / mh.area) * hole_area
    if net_area <= 0.0:
        return area, cx, cy
    return net_area, mx / net_area, my / net_area


def design_yield(material):
    """Design yield ``f_yd = f_ytk / gamma_y`` from material parameters."""
    gamma_y = getattr(material, "gamma_y", 0.0)
    return material.fytk / gamma_y if gamma_y > 0.0 else material.fytk


def _tendon_element_id(elements: object, index: int) -> str:
    """Return retained UI identity without making it a solver prerequisite."""

    fallback = f"tendon {index + 1}"
    if not isinstance(elements, (list, tuple)) or index >= len(elements):
        return fallback
    element = elements[index]
    if not isinstance(element, Mapping):
        return fallback
    element_id = element.get("id")
    if type(element_id) is not str or not element_id.strip():
        return fallback
    return element_id.strip()


def locked_in_prestress_result(
    inp,
    cx=0.0,
    cy=0.0,
) -> LockedInPrestressResult:
    """Retain the existing locked-in tendon calculation for publication.

    The calculation is unchanged: ``sigma_p0 = E_p * IS``,
    ``P_i = sigma_p0 * A_i``, ``Mx_i = P_i * (y_i - cy)`` and
    ``My_i = P_i * (x_i - cx)``. Only the accepted per-tendon terms and totals
    are retained; there is no solver history or generic trace representation.
    """

    prestress = inp.get("prestress")
    tendons = inp.get("tendons")
    materials = inp.get("tendon_materials")
    if not tendons or (prestress is None and not materials):
        return LockedInPrestressResult(
            origin_x_m=cx,
            origin_y_m=cy,
            tendons=(),
            total_n_kn=0.0,
            total_mx_knm=0.0,
            total_my_knm=0.0,
        )
    materials = materials or [prestress] * len(tendons)
    if len(materials) != len(tendons):
        raise ValueError("one prestressing material is required per tendon")
    forces = [
        material.Es * material.IS * 1000.0 * tendon[2] / 1.0e6
        for material, tendon in zip(materials, tendons)
    ]
    element_records = inp.get("tendon_elements")
    states = tuple(
        LockedInPrestressTendon(
            tendon_index=index,
            element_id=_tendon_element_id(element_records, index),
            initial_strain=material.IS,
            modulus_mpa=material.Es,
            locked_in_stress_mpa=material.Es * material.IS,
            area_mm2=tendon[2],
            force_kn=force,
            x_m=tendon[0],
            y_m=tendon[1],
            mx_knm=force * (tendon[1] - cy),
            my_knm=force * (tendon[0] - cx),
        )
        for index, (material, tendon, force) in enumerate(
            zip(materials, tendons, forces)
        )
    )
    return LockedInPrestressResult(
        origin_x_m=cx,
        origin_y_m=cy,
        tendons=states,
        total_n_kn=sum(forces),
        total_mx_knm=sum(state.mx_knm for state in states),
        total_my_knm=sum(state.my_knm for state in states),
    )


def prestress_resultants(inp, cx=0.0, cy=0.0):
    """Return locked-in tendon ``(P, Mx, My)`` about ``(cx, cy)`` in kN/kNm."""

    return locked_in_prestress_result(inp, cx, cy).resultants


def prestress_axial(inp):
    """Tendon precompression in kN."""
    return prestress_resultants(inp)[0]


def shear_lever_arm(inp, axis, tension_low, d_mm):
    """Return the plastic internal shear lever arm in mm, or the ``0.9 d`` fallback."""
    depth = _nonnegative_finite_real(d_mm, "effective depth d")
    fallback = (0.9 * depth, "0.9 d (fallback)")
    if inp["section"] is None:
        return fallback
    angle = _face_angle(axis, tension_low)
    _require_valid_input_geometry(inp)
    prestress = inp["prestress"] if inp["tendons"] else None
    point = plastic_capacity_at_angle(
        inp["section"], inp["concrete"], inp["steel"], -inp["P_pl"],
        angle, prestress=prestress,
        bar_materials=inp.get("bar_materials"),
        tendon_materials=inp.get("tendon_materials"),
    )
    if not _solver_flag(
        _solver_member(point, "converged", "plastic point"),
        "plastic-point converged",
    ):
        return fallback
    lever = abs(_finite_solver_result(
        _solver_member(
            point,
            "dy" if axis == "x" else "dx",
            "plastic point",
        ),
        "plastic internal lever arm",
    ))
    if lever <= 1e-6:
        return fallback
    return lever * 1000.0, "plastic internal lever arm"


def shear_face_mrd(inp, axis, tension_low, m_off=0.0):
    """Return chord ``M_Rd`` conditional on the coexisting off-axis moment."""
    if inp["section"] is None:
        return 0.0, False
    angle = _face_angle(axis, tension_low)
    _require_valid_input_geometry(inp)
    prestress = inp["prestress"] if inp["tendons"] else None
    conditional = conditional_capacity(
        inp["section"], inp["concrete"], inp["steel"], -inp["P_pl"],
        axis, tension_low, m_off, prestress=prestress,
        bar_materials=inp.get("bar_materials"),
        tendon_materials=inp.get("tendon_materials"),
    )
    if type(conditional) is not tuple or len(conditional) != 2:
        raise CapacityResultError(
            "conditional capacity must return a two-item tuple"
        )
    mrd = _finite_solver_result(conditional[0], "conditional capacity")
    exact = _solver_flag(conditional[1], "conditional-capacity exact")
    if mrd < 0.0:
        raise CapacityResultError(
            "conditional capacity must be a non-negative finite result"
        )
    if exact:
        return mrd, True
    if mrd != 0.0:
        raise CapacityResultError(
            "a non-exact conditional capacity must use the zero placeholder"
        )
    point = plastic_capacity_at_angle(
        inp["section"], inp["concrete"], inp["steel"], -inp["P_pl"],
        angle, prestress=prestress,
        bar_materials=inp.get("bar_materials"),
        tendon_materials=inp.get("tendon_materials"),
    )
    if not _solver_flag(
        _solver_member(point, "converged", "pure-axis plastic point"),
        "pure-axis plastic-point converged",
    ):
        return 0.0, False
    moment = _finite_solver_result(
        _solver_member(
            point,
            "Mx" if axis == "x" else "My",
            "pure-axis plastic point",
        ),
        "pure-axis chord resistance",
    )
    return abs(moment), False


def tube_torsion(
    tube,
    t_ed,
    *,
    closed_links_present,
    tcode,
    fck,
    fcd,
    alpha_cw,
    fywd,
    asw_over_s,
    cot_min,
    cot_max,
    nu_detail,
    fctd,
    fyd_long,
):
    """Build the resistance/utilisation payload for one thin-walled tube."""
    closed_detailing_applied = bool(
        closed_links_present is True and nu_detail is True
    )
    nu_t = tcode.torsion_nu(
        fck,
        closed_detailing=closed_detailing_applied,
    )
    a_t = asw_over_s * fywd
    b_t = nu_t * alpha_cw * fcd * tube["tef"]
    shear = _module("shear")
    if a_t > 0.0:
        angle = shear.optimum_strut_angle(a_t, b_t, cot_min, cot_max)
        cot = angle.cot
        angle_selection = asdict(angle)
    else:
        cot = min(max(cot_min, 1.0), cot_max)
        angle_selection = {
            "cot": cot,
            "tan": (math.inf if cot == 0.0 else 1.0 / cot),
            "theta_deg": math.degrees(math.atan2(1.0, cot)),
            "sin_cos": cot / (1.0 + cot * cot),
            "cot_min": cot_min,
            "cot_max": cot_max,
            "cot_unconstrained": 1.0,
            "selection": "no transverse reinforcement; crushing optimum",
        }
    torsion = _module("torsion")
    steel = torsion.trd_s_result(tube["Ak"], fywd, asw_over_s, cot)
    strut = torsion.trd_max_result(
        fck, tcode, tube["Ak"], tube["tef"], alpha_cw, cot,
        closed_detailing=closed_detailing_applied, fcd_mpa=fcd,
    )
    selection = torsion.select_full_torsion_resistance(
        steel.trd_s,
        strut.trd_max,
        closed_links_present=closed_links_present,
        asw_over_s=asw_over_s,
    )
    cracking = torsion.trd_c_result(fctd, tube["Ak"], tube["tef"])
    util = (
        t_ed / selection.resistance
        if selection.full_resistance_assessed and selection.resistance > 0.0
        else (
            math.inf
            if selection.full_resistance_assessed
            else None
        )
    )
    longitudinal = torsion.asl_required_result(
        t_ed, tube["uk"], tube["Ak"], fyd_long, cot
    )
    tube_valid = bool(tube["valid"])
    full_resistance_assessed = bool(
        selection.full_resistance_assessed
    )
    valid = bool(tube_valid and full_resistance_assessed)
    assessment_reason = (
        None
        if full_resistance_assessed
        else selection.reason
    )
    return {
        "tube": tube,
        "t_ed": t_ed,
        "trd_s": steel.trd_s,
        "trd_max": strut.trd_max,
        "trd": selection.resistance,
        "trd_c": cracking.trd_c,
        "cot": cot,
        "theta_deg": math.degrees(math.atan2(1.0, cot)),
        "util": util,
        "asl_req": longitudinal.asl_required_mm2,
        "nu": nu_t,
        "governs": selection.governs,
        "valid": valid,
        "tube_valid": tube_valid,
        "closed_links_present": selection.closed_links_present,
        "full_resistance_assessed": full_resistance_assessed,
        "assessment_reason": assessment_reason,
        "angle_selection": angle_selection,
        "steel_resistance": asdict(steel),
        "strut_resistance": asdict(strut),
        "resistance_selection": asdict(selection),
        "cracking_resistance": asdict(cracking),
        "longitudinal_reinforcement": asdict(longitudinal),
    }


def shear_face_candidates(face, associated_moment, *, zero_tolerance=1.0e-9):
    """Return the low/high-coordinate faces required by one directional check.

    Positive Mx tensions the bottom (negative-y) face and positive My tensions the
    left (negative-x) face.  An automatic selection at effectively zero associated
    moment checks both faces because shear sign alone cannot identify the tension
    reinforcement.
    """
    token = str(face or "auto").strip().casefold()
    if token == "negative":
        return (True,)
    if token == "positive":
        return (False,)
    if token != "auto":
        raise ValueError("shear face must be auto, negative or positive")
    moment = float(associated_moment)
    if moment > zero_tolerance:
        return (True,)
    if moment < -zero_tolerance:
        return (False,)
    return (True, False)


def assessment_key(status, utilisation):
    """Conservative ordering shared by mandatory directional candidates."""
    priority = {
        "INVALID": 4,
        "FAIL": 3,
        "NOT ASSESSED": 2,
        "NOT RUN": 2,
        "PASS": 1,
        "NOT APPLICABLE": 0,
    }.get(str(status or "").upper(), 2)
    value = float(utilisation or 0.0)
    if not math.isfinite(value):
        value = math.inf
    return priority, value


def aggregate_assessment_status(statuses):
    """Return the conservative status across every required candidate."""
    values = {str(status or "").upper() for status in statuses}
    for status in ("INVALID", "FAIL", "NOT ASSESSED", "NOT RUN", "PASS"):
        if status in values:
            return status
    return "NOT ASSESSED"


def shear_direction_specs(inp):
    """Canonical mapping from Vx/Vy inputs to the existing bending-axis model."""
    _, cx, cy = gross_area_centroid(
        inp.get("outer", []), inp.get("holes", [])
    )
    _, mx_prestress, my_prestress = prestress_resultants(inp, cx, cy)
    axial = float(inp.get("P_pl", 0.0))
    mx_origin = float(inp.get("Mx_pl", 0.0))
    my_origin = float(inp.get("My_pl", 0.0))
    # Section forces are entered about the coordinate origin. Face selection must
    # follow the bending at the physical concrete centroid, including the locked-in
    # tendon moment, exactly like the action-dependent shear calculation below.
    # N is tension-positive, hence M_C = M_O + N*c before prestress is deducted.
    mx_centroid = mx_origin + axial * cy - mx_prestress
    my_centroid = my_origin + axial * cx - my_prestress
    components = inp.get("shear_components") or {}
    vx_signed = float(
        (components.get("vx") or {}).get(
            "signed_v_ed", inp.get("shear_Vx", 0.0)
        )
    )
    vy_signed = float(
        (components.get("vy") or {}).get(
            "signed_v_ed", inp.get("shear_Vy", 0.0)
        )
    )
    return {
        "vx": {
            "axis": "y",
            "moment": my_centroid,
            "moment_origin": my_origin,
            "v_ed": abs(vx_signed),
            "signed_v_ed": vx_signed,
            "face": inp.get("shear_face_x", "auto"),
            "bw": float(inp.get("shear_vx_bw", 0.0)),
            "legs": float(inp.get("shear_vx_link_legs", 2.0)),
        },
        "vy": {
            "axis": "x",
            "moment": mx_centroid,
            "moment_origin": mx_origin,
            "v_ed": abs(vy_signed),
            "signed_v_ed": vy_signed,
            "face": inp.get("shear_face_y", "auto"),
            "bw": float(inp.get("shear_vy_bw", 0.0)),
            "legs": float(inp.get("shear_vy_link_legs", 2.0)),
        },
    }


def _build_shear_face_context(
    inp,
    n_prestress,
    n_ed_comp,
    *,
    component,
    axis,
    tension_low,
    v_ed,
    bw_override,
    link_legs,
    face_mode,
    code,
):
    """Build one face candidate for one physical shear component."""
    model_2023 = getattr(code, "shear_model", "2005") == "2023"
    area, cx, cy = gross_area_centroid(inp["outer"], inp["holes"])
    _, mx_prestress, my_prestress = prestress_resultants(inp, cx, cy)
    centroid_coord = cy if axis == "x" else cx
    shear = _module("shear")
    asl, cg, asl_bar_ids = shear.tension_reinforcement_selection(
        inp["bars"], axis, tension_low, centroid_coord
    )
    d_mm = shear.effective_depth(inp["outer"], axis, tension_low, cg)
    bw_auto = shear.min_web_width(inp["outer"], inp["holes"], axis)
    bw_mm = bw_override if bw_override > 0.0 else bw_auto
    fck = inp["concrete"].fck
    fyd_flex = design_yield(inp["steel"])
    ddg = code.shear_ddg(fck, inp["shear_dlower"]) if model_2023 else 0.0
    shared_links_present = _shared_links_present(inp)
    if model_2023 and not shared_links_present:
        try:
            gamma_v = shear.validate_gamma_v(
                inp.get("shear_gamma_v", _MISSING),
                label="shear_gamma_v",
            )
        except ValueError as exc:
            raise CapacityInputError(str(exc)) from exc
    else:
        gamma_v = None
    if axis == "x":
        m_ed_2023 = inp["Mx_pl"] + inp["P_pl"] * cy - mx_prestress
        m_prestress = mx_prestress
    else:
        m_ed_2023 = inp["My_pl"] + inp["P_pl"] * cx - my_prestress
        m_prestress = my_prestress
    result = shear.vrd_c(
        fck, code, bw_mm, d_mm, asl, n_ed_comp, area,
        fyd_mpa=fyd_flex, ddg_mm=(ddg or 32.0),
        m_ed_knm=m_ed_2023, v_ed_kn=v_ed,
        fcd_mpa=inp["concrete"].fcd,
        gamma_c=inp["concrete"].gamma_c,
        gamma_v=gamma_v,
    )
    util = v_ed / result["vrd_c"] if result["vrd_c"] > 0.0 else math.inf
    payload = {
        "res": result,
        "v_ed": v_ed,
        "util": util,
        "component": component,
        "axis": axis,
        "tension_low": tension_low,
        "face_mode": face_mode,
        "bw": bw_mm,
        "bw_auto": bw_auto,
        "bw_user": bool(bw_override > 0.0),
        "d": d_mm,
        "asl": asl,
        "asl_bar_ids": asl_bar_ids,
        "asl_cg": cg,
        "ac": area,
        "fck": fck,
        "n_ed": inp["P_pl"],
        "n_prestress": n_prestress,
        "n_ed_comp": n_ed_comp,
        "m_ed_2023": m_ed_2023,
        "m_prestress": m_prestress,
        "centroid": (cx, cy),
        "method": inp["shear_method"],
        "model_2023": model_2023,
        "ddg": ddg,
        "fyd_flex": fyd_flex,
    }
    if not shared_links_present:
        return payload, None

    cot_min = min(inp["strut_cot_min"], inp["strut_cot_max"])
    cot_max = max(inp["strut_cot_min"], inp["strut_cot_max"])
    if model_2023:
        angle_limits = shear.compression_field_limits_2023(
            -n_ed_comp,
            v_ed,
            inp.get("transverse_ductility_class", "B"),
        )
    else:
        angle_limits = {
            "minimum": code.shear_cot_min_limit,
            "maximum": code.shear_cot_max_limit,
            "basis": "2005-family fixed range",
            "ductility_class": str(
                inp.get("transverse_ductility_class", "B")
            ).upper(),
            "ductility_factor": 1.0,
            "axial_tension_applied": False,
            "compression_extension_credited": False,
            "clause": "EN 1992-1-1:2005, 6.2.3(2), Formula (6.7N)",
        }
    asw = link_legs * _module("templates").bar_area(inp["shear_link_dia"])
    asw_over_s = asw / inp["shear_link_s"] if inp["shear_link_s"] > 0.0 else 0.0
    z_mm, z_source = shear_lever_arm(inp, axis, tension_low, d_mm)

    def links_at(
        cot_lo,
        cot_hi,
        _fck=fck,
        _code=code,
        _bw=bw_mm,
        _d=d_mm,
        _asw_over_s=asw_over_s,
        _area=area,
        _z=z_mm,
    ):
        return shear.vrd_links(
            _fck, _code, _bw, _d, _asw_over_s, inp["shear_fywk"],
            n_ed_comp, _area, cot_lo, cot_hi, z_mm=_z,
            fcd_mpa=inp["concrete"].fcd,
            gamma_s=inp["steel"].gamma_y,
            v_ed_kn=v_ed,
        )

    context = {
        "build": links_at,
        "cot_min": cot_min,
        "cot_max": cot_max,
        "asw": asw,
        "asw_over_s": asw_over_s,
        "z_mm": z_mm,
        "z_src": z_source,
        "code": code,
        "v_ed": v_ed,
        "vrd_c": result["vrd_c"],
        "axis": axis,
        "tension_low": tension_low,
        "component": component,
        "link_legs": link_legs,
        "model_2023": model_2023,
        "angle_limits": angle_limits,
    }
    return payload, context


def _shared_links_present(inp):
    """Return the exact shared-link selection or reject malformed evidence."""

    authority = inp.get("shear_links", _MISSING)
    if type(authority) is not bool:
        raise CapacityInputError(
            "shared links / closed torsion stirrups must be a Boolean"
        )
    return authority


def build_directional_shear_contexts(inp, n_prestress, n_ed_comp):
    """Return every required face candidate for active Vx,Ed and Vy,Ed checks.

    The result maps ``vx``/``vy`` to a candidate list. No interaction between the
    two components is introduced here or elsewhere; each candidate remains a
    normal uniaxial shear calculation in its physical plane.
    """
    if not inp.get("shear_on"):
        return {}
    _shared_links_present(inp)
    code = selected_shear_code(inp.get("shear_method"))
    _require_valid_input_geometry(inp)
    definitions = shear_direction_specs(inp)
    contexts = {}
    for component, definition in definitions.items():
        if definition["v_ed"] <= 0.0:
            continue
        faces = shear_face_candidates(definition["face"], definition["moment"])
        candidates = [
            _build_shear_face_context(
                inp,
                n_prestress,
                n_ed_comp,
                component=component,
                axis=definition["axis"],
                tension_low=tension_low,
                v_ed=definition["v_ed"],
                bw_override=definition["bw"],
                link_legs=definition["legs"],
                face_mode=str(definition["face"]),
                code=code,
            )
            for tension_low in faces
        ]
        contexts[component] = {
            "component": component,
            "axis": definition["axis"],
            "associated_moment": definition["moment"],
            "face_mode": str(definition["face"]),
            "both_faces_evaluated": len(candidates) == 2,
            "candidates": candidates,
        }
    return contexts


def build_shear_context(inp, n_prestress, n_ed_comp):
    """Build the current one-direction shear calculation context.

    The application reuses the same verified kernel for a direct one-direction
    calculation and for each independently evaluated directional component.
    """
    if not inp.get("shear_on"):
        return None, None
    _shared_links_present(inp)
    code = selected_shear_code(inp.get("shear_method"))
    _require_valid_input_geometry(inp)
    axis = inp["shear_axis"]
    return _build_shear_face_context(
        inp,
        n_prestress,
        n_ed_comp,
        component="vy" if axis == "x" else "vx",
        axis=axis,
        tension_low=bool(inp["shear_tension"]),
        v_ed=float(inp["shear_V"]),
        bw_override=float(inp["shear_bw"]),
        link_legs=float(inp["shear_link_legs"]),
        face_mode="selected",
        code=code,
    )


def build_torsion_context(inp, n_ed_comp):
    """Return the angle-independent context for the active torsion check."""
    if not inp.get("torsion_on"):
        return None
    closed_links_present = _shared_links_present(inp)
    nu_detail_requested = inp.get("torsion_nu_v", _MISSING)
    if type(nu_detail_requested) is not bool:
        raise CapacityInputError(
            "torsion closed-detailing allowance must be a Boolean"
        )
    tcode = selected_torsion_code(inp.get("torsion_method"))
    if inp["section"] is None:
        return None
    _require_valid_input_geometry(inp)
    fck = inp["concrete"].fck
    fcd = inp["concrete"].fcd
    area, _cx, _cy = gross_area_centroid(inp["outer"], inp["holes"])
    sigma_cp = n_ed_comp / area / 1000.0 if area > 0.0 else 0.0
    alpha_cw = tcode.shear_alpha_cw(sigma_cp, fcd)
    subdivision_requested = bool(inp.get("torsion_subdivide"))
    if subdivision_requested:
        tef_override_mm = _nonnegative_finite_real(
            inp["torsion_tef"], "torsion wall-thickness override"
        )
        if tef_override_mm > 0.0:
            raise CapacityInputError(
                "torsion wall-thickness override must be 0 (automatic per sub-tube) "
                "when torsion subdivision is enabled"
            )
    torsion = _module("torsion")
    tube = torsion.tube_properties(
        inp["outer"], inp["holes"], tef_override=inp["torsion_tef"]
    )
    gamma_s = inp["steel"].gamma_y
    fywd = (
        inp["shear_fywk"] / gamma_s
        if closed_links_present
        else 0.0
    )
    fyd_long = design_yield(inp["steel"])
    asw = (
        _module("templates").bar_area(inp["shear_link_dia"])
        if closed_links_present
        else 0.0
    )
    asw_over_s = (
        asw / inp["shear_link_s"]
        if closed_links_present and inp["shear_link_s"] > 0.0
        else 0.0
    )
    cot_min = min(inp["strut_cot_min"], inp["strut_cot_max"])
    cot_max = max(inp["strut_cot_min"], inp["strut_cot_max"])
    nu_detail = bool(closed_links_present and nu_detail_requested)
    nu_detail_applied = bool(
        nu_detail
        and tcode.torsion_nu(fck, closed_detailing=True)
        != tcode.torsion_nu(fck, closed_detailing=False)
    )
    gamma_c = inp["concrete"].gamma_c
    gamma_ct = _positive_finite_real(inp["torsion_gamma_ct"], "gamma_ct")
    fctk_005 = 0.7 * codes.fctm(fck)
    fctd = fctk_005 / gamma_ct
    t_ed = inp["torsion_T"]
    tube_kwargs = {
        "closed_links_present": closed_links_present,
        "tcode": tcode,
        "fck": fck,
        "fcd": fcd,
        "alpha_cw": alpha_cw,
        "fywd": fywd,
        "asw_over_s": asw_over_s,
        "cot_min": cot_min,
        "cot_max": cot_max,
        "nu_detail": nu_detail,
        "fctd": fctd,
        "fyd_long": fyd_long,
    }

    subrects = inp.get("torsion_subrects") or []
    subdivision_valid = False
    subdivision_reason = ""
    if subdivision_requested:
        rectangles_m = [
            (x_mm / 1000.0, y_mm / 1000.0,
             b_mm / 1000.0, h_mm / 1000.0)
            for x_mm, y_mm, b_mm, h_mm in subrects
        ]
        subdivision_valid, subdivision_reason = (
            _module("geometry").rectangles_partition_concrete(
                inp["outer"], inp.get("holes") or [], rectangles_m
            )
        )
    subdivide = subdivision_requested and subdivision_valid
    compound_detected = not _module("geometry").polygon_is_convex(inp["outer"])
    if subdivision_requested and not subdivision_valid:
        tube = dict(
            tube,
            valid=False,
            reason=f"invalid sub-tube partition: {subdivision_reason}",
        )
    elif compound_detected and not subdivide:
        tube = dict(
            tube, valid=False, reason="compound outline requires subdivision"
        )

    if subdivide:
        subtubes, stiffnesses, dimensions = [], [], []
        for x_mm, y_mm, b_mm, h_mm in subrects:
            b_m, h_m = b_mm / 1000.0, h_mm / 1000.0
            subtubes.append(
                torsion.tube_properties(torsion.rectangle_ring(b_m, h_m), None)
            )
            stiffnesses.append(torsion.rectangle_torsion_constant(b_m, h_m))
            dimensions.append((x_mm, y_mm, b_mm, h_mm))
        distribution = torsion.stiffness_distribution_result(t_ed, stiffnesses)
        torque_parts = list(distribution.torque_parts)
    else:
        subtubes = [tube]
        stiffnesses = [1.0]
        dimensions = [None]
        distribution = torsion.stiffness_distribution_result(t_ed, stiffnesses)
        torque_parts = list(distribution.torque_parts)

    return {
        "_tk": tube_kwargs,
        "tube": tube,
        "subdivide": subdivide,
        "subtubes": subtubes,
        "consts": stiffnesses,
        "ted_parts": torque_parts,
        "torque_distribution": asdict(distribution),
        "sub_dims": dimensions,
        "t_ed": t_ed,
        "tcode": tcode,
        "fck": fck,
        "fcd": fcd,
        "alpha_cw": alpha_cw,
        "fywd_t": fywd,
        "fyd_long": fyd_long,
        "asw_t": asw,
        "asw_over_s_t": asw_over_s,
        "tcot_min": cot_min,
        "tcot_max": cot_max,
        "nu_detail": nu_detail,
        "nu_detail_applied": nu_detail_applied,
        "fctk_005": fctk_005,
        "fctd": fctd,
        "sigma_cp": sigma_cp,
        "gamma_c": gamma_c,
        "gamma_ct": gamma_ct,
        "gamma_s": gamma_s,
        "closed_links_present": closed_links_present,
        "nu_detail_requested": nu_detail_requested,
        "compound_detected": compound_detected,
        "subdivision_requested": subdivision_requested,
        "subdivision_valid": subdivision_valid,
        "subdivision_reason": subdivision_reason,
    }


def finalize_combined(inp, out):
    """Build the final combined M-V-T payload from completed component checks."""
    if not inp.get("combined_on"):
        return
    selected_combined_code(inp.get("combined_method"))
    plastic = out.get("plastic")
    shear_out = out.get("shear")
    torsion_out = out.get("torsion")
    r_m = plastic.get("util") if plastic else None
    have_m = r_m is not None
    have_v = shear_out is not None and shear_out["res"]["valid"]
    have_t = torsion_out is not None and torsion_out["valid"]
    if not (have_m and have_v and have_t):
        out["combined"] = {
            "valid": False,
            "have_m": have_m,
            "have_v": have_v,
            "have_t": have_t,
            "method": inp["combined_method"],
        }
        return

    links = shear_out.get("links")
    r_v = links["util"] if links is not None else shear_out["util"]
    r_t = torsion_out["util"]
    independent_mv = bool(inp["combined_mv_independent"])
    combined = _module("combined")
    dk_selection = combined.dkna_interaction_result(
        r_m, r_v, r_t, m_v_independent=independent_mv
    )
    dk_sum = dk_selection.utilisation
    outside_default_range = bool(
        torsion_out.get("out_of_limits")
        or (links is not None and links.get("out_of_limits"))
    )
    payload = {
        "valid": True,
        "method": inp["combined_method"],
        "r_m": r_m,
        "r_v": r_v,
        "r_t": r_t,
        "m_v_independent": independent_mv,
        "dkna_sum": dk_sum,
        "dkna_ok": dk_sum <= 1.0 + 1e-9,
        "dkna_selection": asdict(dk_selection),
        "outside_default_range": outside_default_range,
        "crushing": torsion_out.get("interaction"),
        "asl_torsion": torsion_out["asl_req"],
        "delta_ftd": links["delta_ftd"] if links is not None else 0.0,
        "links": links is not None,
        "member_angle_selection": (
            links.get("member_angle_selection")
            if links is not None
            else torsion_out.get("member_angle_selection")
        ),
    }
    longitudinal = links.get("chord") if links is not None else None
    if longitudinal is not None:
        payload["longitudinal"] = longitudinal
    chord_off = links.get("chord_off") if links is not None else None
    if chord_off is not None:
        payload["chord_off"] = chord_off
    if links is not None and links.get("chord_candidates") is not None:
        payload["longitudinal_candidates"] = links["chord_candidates"]
    if links is not None:
        for retained_key in (
            "governing_longitudinal",
            "longitudinal_fallback",
            "longitudinal_all_conditional",
        ):
            if retained_key in links:
                payload[retained_key] = links[retained_key]

    if (
        links is not None
        and links["res"]["valid"]
        and torsion_out["asw_over_s"] > 0.0
    ):
        interaction = torsion_out.get("interaction")
        if interaction is not None and not interaction.get("valid"):
            payload["transverse"] = {
                "valid": False,
                "reason": "shared member-angle calculation is invalid",
            }
        else:
            v_ed = shear_out["v_ed"]
            t_ed_web = torsion_out["primary"]["t_ed"]
            vrd_c = shear_out["res"]["vrd_c"]
            cot = (
                interaction["cot"]
                if interaction is not None
                else links["res"]["cot"]
            )
            shear_credited = v_ed <= vrd_c
            shear_fraction = (
                0.0
                if shear_credited
                else combined.ratio(v_ed, links["res"]["vrd_s"])
            )
            torsion_fraction = combined.ratio(
                t_ed_web, torsion_out["primary"]["trd_s"]
            )
            stirrup_util = shear_fraction + torsion_fraction
            crushing_util = (
                interaction["value"]
                if interaction is not None
                else combined.ratio(v_ed, links["res"]["vrd_max"])
            )
            governing = max(stirrup_util, crushing_util)
            payload["transverse"] = {
                "valid": True,
                "cot": cot,
                "tan": math.inf if cot == 0.0 else 1.0 / cot,
                "sin_cos": cot / (1.0 + cot * cot),
                "theta_deg": math.degrees(math.atan2(1.0, cot)),
                "u_stirrup": stirrup_util,
                "u_crush": crushing_util,
                "governing": governing,
                "governs": (
                    "crushing" if crushing_util > stirrup_util else "stirrups"
                ),
                "ok": bool(governing <= 1.0 + 1e-9),
                "shear_fraction": shear_fraction,
                "torsion_fraction": torsion_fraction,
                "shear_credited": shear_credited,
                "vrd_c": vrd_c,
                "v_ed": v_ed,
            }
    out["combined"] = payload
