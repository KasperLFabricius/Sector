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
from .engineer_message import EngineerMessage

SHEAR_CODES = {c.label: c for c in (codes.EC2_2005_DKNA, codes.EC2_2005)}
SHEAR_METHODS = dict(SHEAR_CODES, **{codes.EC2_2023.label: codes.EC2_2023})
TORSION_RESISTANCE_EXCEEDED = "torsion_resistance_exceeded"
_MISSING = object()
_TORSION_GAMMA_CT_INPUT = EngineerMessage(
    "TORSION-GAMMA-CT",
    "Enter a positive finite concrete tensile partial factor gamma_ct",
)
_TORSION_WALL_INPUT = EngineerMessage(
    "TORSION-WALL-INPUT",
    "Enter a non-negative finite torsion wall thickness in millimetres",
)
_TORSION_HOLLOW_WALL_INPUT = EngineerMessage(
    "TORSION-HOLLOW-WALL",
    "Enter a torsion wall thickness no greater than the nearest real wall thickness",
)
_TORSION_SUBDIVISION_WALL_INPUT = EngineerMessage(
    "TORSION-SUBDIVISION-WALL",
    "Set the torsion wall-thickness override to 0 mm when sub-tube subdivision is enabled",
)


def _module(name: str):
    """Resolve one calculation dependency only when its family is requested."""

    return import_module(f".{name}", __package__)


class CapacityInputError(ValueError):
    """Expected invalid input at a member-capacity boundary."""

    def __init__(
        self,
        *args: object,
        engineer_message: EngineerMessage | None = None,
    ) -> None:
        super().__init__(*args)
        if engineer_message is not None and not isinstance(
            engineer_message, EngineerMessage
        ):
            raise TypeError("engineer_message must be an EngineerMessage")
        self.engineer_message = engineer_message


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
class NominalShearResistanceSelection:
    """Authoritative nominal shear-resistance route for one direction.

    The concrete route remains applicable through ``VEd == VRd,c``.  Valid
    designed links become the nominal resistance route only above that exact
    boundary.  Link detailing is intentionally outside this record.
    """

    valid: bool
    route: str | None
    resistance: float | None
    utilisation: float | None
    status: str
    ok: bool | None
    concrete_applicable: bool | None
    links_selected: bool
    links_required: bool | None
    reason: str | None


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


def solve_plastic(*args, **kwargs):
    """Resolve the plastic sweep only when an action-alone check needs it."""

    from .plastic import solve_plastic as solve

    return solve(*args, **kwargs)


def solve_interaction(*args, **kwargs):
    """Resolve the axial interaction trace only when an axial check needs it."""

    from .plastic import solve_interaction as solve

    return solve(*args, **kwargs)


def solve_zero_moment_axial_capacity(*args, **kwargs):
    """Resolve the dedicated pure-axial boundary only when it is requested."""

    from .plastic import solve_zero_moment_axial_capacity as solve

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


def _positive_finite_real(
    value,
    label,
    *,
    engineer_message: EngineerMessage | None = None,
):
    """Return one calculation coefficient, rejecting only malformed values."""
    if _is_boolean_scalar(value) or isinstance(value, (str, bytes)):
        raise CapacityInputError(
            f"{label} must be a positive finite real number",
            engineer_message=engineer_message,
        )
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CapacityInputError(
            f"{label} must be a positive finite real number",
            engineer_message=engineer_message,
        ) from exc
    if not math.isfinite(number) or number <= 0.0:
        raise CapacityInputError(
            f"{label} must be a positive finite real number",
            engineer_message=engineer_message,
        )
    return number


def _nonnegative_finite_real(
    value: Any,
    label: str,
    *,
    engineer_message: EngineerMessage | None = None,
) -> float:
    if _is_boolean_scalar(value) or isinstance(value, (str, bytes)):
        raise CapacityInputError(
            f"{label} must be a non-negative finite real number",
            engineer_message=engineer_message,
        )
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CapacityInputError(
            f"{label} must be a non-negative finite real number",
            engineer_message=engineer_message,
        ) from exc
    if not math.isfinite(number) or number < 0.0:
        raise CapacityInputError(
            f"{label} must be a non-negative finite real number",
            engineer_message=engineer_message,
        )
    return number


def select_nominal_shear_resistance(
    shear_result: object,
    *,
    links_selected: bool,
) -> NominalShearResistanceSelection:
    """Select the nominal resistance without conflating link detailing.

    A selected but unavailable link route remains fail-closed so the H03-H06
    geometry and applicability boundaries cannot be bypassed by a finite
    concrete-only value retained for context.
    """

    if type(links_selected) is not bool:
        raise CapacityInputError("links-selected authority must be a Boolean")

    def unavailable(status: str, reason: object) -> NominalShearResistanceSelection:
        return NominalShearResistanceSelection(
            valid=False,
            route=None,
            resistance=None,
            utilisation=None,
            status=status,
            ok=None,
            concrete_applicable=None,
            links_selected=links_selected,
            links_required=None,
            reason=str(reason or "shear resistance is unavailable"),
        )

    if not isinstance(shear_result, Mapping):
        return unavailable("INVALID", "shear result is unavailable")
    concrete = shear_result.get("res")
    if not isinstance(concrete, Mapping):
        return unavailable("INVALID", "concrete shear resistance is unavailable")
    concrete_state = str(concrete.get("calculation_state") or "").upper()
    if concrete.get("valid") is not True:
        return unavailable(
            "NOT ASSESSED" if concrete_state == "NOT ASSESSED" else "INVALID",
            concrete.get("reason"),
        )
    try:
        demand = _nonnegative_finite_real(
            shear_result.get("v_ed", _MISSING), "shear demand"
        )
        concrete_resistance = _positive_finite_real(
            concrete.get("vrd_c", _MISSING), "concrete shear resistance"
        )
    except CapacityInputError as exc:
        return unavailable("INVALID", exc)

    concrete_applicable = demand <= concrete_resistance
    links_required = not concrete_applicable
    link_resistance = None
    if links_selected:
        links = shear_result.get("links")
        link_result = links.get("res") if isinstance(links, Mapping) else None
        angle_applicability = (
            link_result.get("angle_applicability")
            if isinstance(link_result, Mapping)
            else None
        )
        if (
            concrete_applicable
            and isinstance(angle_applicability, Mapping)
            and angle_applicability.get("active", True) is True
            and angle_applicability.get("applicable") is False
        ):
            # This link interval is outside its permitted method range while the
            # concrete route applies.
            # Geometry and other method failures remain fail-closed; only this
            # explicit angle-domain state may leave VRd,c authoritative.
            link_result = None
        elif not isinstance(link_result, Mapping) or link_result.get("valid") is not True:
            reason = None
            if isinstance(links, Mapping):
                reason = links.get("assessment_reason")
            if isinstance(link_result, Mapping):
                reason = reason or link_result.get("reason")
            return unavailable(
                "NOT ASSESSED",
                reason or "the selected links resistance is unavailable",
            )
        if link_result is not None:
            try:
                link_resistance = _positive_finite_real(
                    link_result.get("vrd", _MISSING), "links shear resistance"
                )
            except CapacityInputError as exc:
                return unavailable("NOT ASSESSED", exc)

    if concrete_applicable or not links_selected:
        route = "concrete"
        resistance = concrete_resistance
    else:
        route = "links"
        resistance = link_resistance
    if resistance is None:
        return unavailable(
            "NOT ASSESSED", "the selected shear resistance is unavailable"
        )
    utilisation = demand / resistance
    ok = utilisation <= 1.0
    return NominalShearResistanceSelection(
        valid=True,
        route=route,
        resistance=resistance,
        utilisation=utilisation,
        status="PASS" if ok else "FAIL",
        ok=ok,
        concrete_applicable=concrete_applicable,
        links_selected=links_selected,
        links_required=links_required,
        reason=None,
    )


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
    model_2023 = links.get("model_2023", False)
    if type(model_2023) is not bool:
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
            if model_2023 and (
                candidate.get("chord_role")
                not in {"flexural_tension", "flexural_compression"}
                or candidate.get("chord_formula") not in {"8.51", "8.52"}
                or type(candidate.get("flexural_tension_low", _MISSING))
                is not bool
                or (
                    candidate.get("chord_role") == "flexural_tension"
                )
                is not (
                    tension_low is candidate.get("flexural_tension_low")
                )
                or (
                    candidate.get("chord_role") == "flexural_tension"
                    and candidate.get("chord_formula") != "8.51"
                )
                or (
                    candidate.get("chord_role") == "flexural_compression"
                    and candidate.get("chord_formula") != "8.52"
                )
            ):
                return False
            shear_candidates.append(candidate)
        else:
            off_candidates.append(candidate)

    if not torsion_live:
        if model_2023:
            return bool(
                shear_live
                and len(candidates) == 2
                and len(shear_candidates) == 2
                and not off_candidates
                and {item["axis"] for item in shear_candidates} == {shear_axis}
                and {item["tension_low"] for item in shear_candidates}
                == {True, False}
                and all(item["gets_shift"] is True for item in shear_candidates)
                and {item["chord_role"] for item in shear_candidates}
                == {"flexural_tension", "flexural_compression"}
                and {item["chord_formula"] for item in shear_candidates}
                == {"8.51", "8.52"}
                and len({
                    item["flexural_tension_low"] for item in shear_candidates
                }) == 1
            )
        return bool(
            shear_live
            and len(candidates) == 1
            and len(shear_candidates) == 1
            and not off_candidates
            and shear_candidates[0]["axis"] == shear_axis
            and shear_candidates[0]["tension_low"] is shear_tension_low
            and shear_candidates[0]["gets_shift"] is True
        )

    shifted_candidates = [item for item in shear_candidates if item["gets_shift"]]
    if (
        len(candidates) != 4
        or len(shear_candidates) != 2
        or len(off_candidates) != 2
        or len(shifted_candidates) != (2 if model_2023 else 1)
    ):
        return False
    off_axis = "y" if shear_axis == "x" else "x"
    return bool(
        {item["axis"] for item in shear_candidates} == {shear_axis}
        and {item["axis"] for item in off_candidates} == {off_axis}
        and (
            model_2023
            or shifted_candidates[0]["tension_low"] is shear_tension_low
        )
        and {item["tension_low"] for item in shear_candidates} == {True, False}
        and {item["tension_low"] for item in off_candidates} == {True, False}
        and (
            not model_2023
            or {item["chord_role"] for item in shear_candidates}
            == {"flexural_tension", "flexural_compression"}
        )
        and (
            not model_2023
            or {item["chord_formula"] for item in shear_candidates}
            == {"8.51", "8.52"}
        )
        and (
            not model_2023
            or len({
                item["flexural_tension_low"] for item in shear_candidates
            }) == 1
        )
    )


def longitudinal_chord_assessment(
    links: object,
    *,
    shear_axis: str,
    shear_tension_low: bool,
    shear_live: bool,
    torsion_live: bool,
    torsion_subdivided: bool,
) -> dict[str, Any]:
    """Return one conservative status for every required chord face.

    A valid failed conditional face is a definite failure even if another required
    face is unavailable. Otherwise incomplete or substitute-only coverage remains
    not assessed. This retained object is shared by the standalone shear and M-V-T
    publication paths so they cannot assign different verdicts to the same chords.
    """

    if not shear_live and not torsion_live:
        return {
            "status": "NOT APPLICABLE",
            "ok": None,
            "util": None,
            "reason": "no_longitudinal_chord_action",
            "coverage_complete": True,
            "governing": None,
        }

    candidates = (
        links.get("chord_candidates")
        if isinstance(links, Mapping)
        else None
    )
    retained: list[tuple[float, Mapping[str, Any]]] = []
    if isinstance(candidates, (list, tuple)):
        for candidate in candidates:
            if (
                not isinstance(candidate, Mapping)
                or candidate.get("valid") is not True
                or candidate.get("conditional") is not True
            ):
                continue
            utilisation = candidate.get("util")
            if _is_boolean_scalar(utilisation) or isinstance(
                utilisation, (str, bytes)
            ):
                continue
            try:
                value = float(utilisation)
            except (OverflowError, TypeError, ValueError):
                continue
            if math.isnan(value) or value < 0.0:
                continue
            retained.append((value, candidate))

    governing_pair = max(retained, key=lambda item: item[0]) if retained else None
    governing = governing_pair[1] if governing_pair is not None else None
    utilisation = governing_pair[0] if governing_pair is not None else None
    complete = combined_longitudinal_chord_evidence_is_valid(
        links,
        shear_axis=shear_axis,
        shear_tension_low=shear_tension_low,
        shear_live=shear_live,
        torsion_live=torsion_live,
        torsion_subdivided=torsion_subdivided,
    )
    if any(value > 1.0 + 1.0e-9 for value, _candidate in retained):
        return {
            "status": "FAIL",
            "ok": False,
            "util": utilisation,
            "reason": "required_longitudinal_chord_failed",
            "coverage_complete": complete,
            "governing": governing,
        }
    if not complete:
        return {
            "status": "NOT ASSESSED",
            "ok": None,
            "util": utilisation,
            "reason": "required_longitudinal_chord_coverage_incomplete",
            "coverage_complete": False,
            "governing": governing,
        }
    return {
        "status": "PASS",
        "ok": True,
        "util": utilisation,
        "reason": "required_longitudinal_chords_satisfied",
        "coverage_complete": True,
        "governing": governing,
    }


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


def plastic_effective_depths(inp):
    """Return the four existing face-specific mild-steel effective depths.

    Plastic states are not generally aligned with a section face.  The result
    presentation therefore publishes the same x/y, low/high-face ``d`` values
    already used by the shear routes instead of inventing a state-normal depth.
    """

    _, cx, cy = gross_area_centroid(inp["outer"], inp.get("holes") or [])
    shear = _module("shear")
    rows = []
    for axis, centroid_coord in (("x", cy), ("y", cx)):
        for tension_low in (True, False):
            area, cg, bar_ids = shear.tension_reinforcement_selection(
                inp.get("bars") or [], axis, tension_low, centroid_coord
            )
            rows.append({
                "axis": axis,
                "tension_low": tension_low,
                "d_mm": shear.effective_depth(
                    inp["outer"], axis, tension_low, cg
                ),
                "asl_mm2": area,
                "asl_bar_ids": tuple(bar_ids),
                "asl_cg_m": cg,
                "coordinate": "y" if axis == "x" else "x",
                "arm_component": "z_y" if axis == "x" else "z_x",
            })
    return tuple(rows)


def design_yield(material):
    """Design yield ``f_yd = f_ytk / gamma_y`` from material parameters."""
    gamma_y = getattr(material, "gamma_y", 0.0)
    return material.fytk / gamma_y if gamma_y > 0.0 else material.fytk


def torsion_longitudinal_assessment(
    inp,
    required_by_tube_mm2,
    *,
    resistance_assessed,
):
    """Compare Formula (6.28) demand with modelled passive reinforcement.

    The section model can establish a conservative upper bound on the available
    longitudinal tensile resistance by summing every modelled passive bar.  It
    cannot establish how much remains after bending, whether it is distributed
    around every torsion-tube side, or whether it is anchored along the member.
    Consequently, a shortfall is a definite failure, while an apparently
    sufficient total remains not assessed for non-zero torsion.
    """

    requirements = tuple(float(value) for value in required_by_tube_mm2)
    requirement_valid = bool(
        requirements
        and all(math.isfinite(value) and value >= 0.0 for value in requirements)
    )
    required_asl = math.fsum(requirements) if requirement_valid else None

    bars = tuple(inp.get("bars") or ())
    materials = inp.get("bar_materials")
    if materials is None:
        materials = (inp.get("steel"),) * len(bars)
    else:
        materials = tuple(materials)
    assignments_valid = len(materials) == len(bars)

    provided_area = 0.0
    provided_force = 0.0
    if assignments_valid:
        for bar, material in zip(bars, materials):
            if (
                type(bar) not in (tuple, list)
                or len(bar) != 3
                or material is None
            ):
                assignments_valid = False
                break
            try:
                area = float(bar[2])
                fyd = float(design_yield(material))
            except (AttributeError, TypeError, ValueError, ZeroDivisionError):
                assignments_valid = False
                break
            if (
                not math.isfinite(area)
                or area <= 0.0
                or not math.isfinite(fyd)
                or fyd <= 0.0
            ):
                assignments_valid = False
                break
            provided_area += area
            provided_force += area * fyd / 1000.0

    try:
        reference_fyd = float(design_yield(inp.get("steel")))
    except (AttributeError, TypeError, ValueError, ZeroDivisionError):
        reference_fyd = math.nan
    reference_valid = math.isfinite(reference_fyd) and reference_fyd > 0.0
    evidence_valid = bool(
        resistance_assessed is True
        and requirement_valid
        and assignments_valid
        and reference_valid
        and math.isfinite(provided_area)
        and math.isfinite(provided_force)
    )

    required_force = (
        required_asl * reference_fyd / 1000.0
        if evidence_valid and required_asl is not None
        else None
    )
    equivalent_area = (
        provided_force * 1000.0 / reference_fyd
        if evidence_valid
        else None
    )
    demand_ratio = None
    area_sufficient = None
    if evidence_valid and required_force is not None:
        demand_ratio = (
            required_force / provided_force
            if provided_force > 0.0
            else (0.0 if required_force == 0.0 else math.inf)
        )
        area_sufficient = bool(
            provided_force >= required_force
            or math.isclose(
                provided_force,
                required_force,
                rel_tol=1.0e-12,
                abs_tol=0.0,
            )
        )

    if not evidence_valid:
        status = "NOT ASSESSED"
        ok = None
        reason = "longitudinal_torsion_reinforcement_evidence_unavailable"
    elif required_force == 0.0:
        status = "PASS"
        ok = True
        reason = "no_longitudinal_torsion_demand"
    elif area_sufficient is not True:
        status = "FAIL"
        ok = False
        reason = "longitudinal_torsion_reinforcement_insufficient"
    else:
        status = "NOT ASSESSED"
        ok = None
        reason = "longitudinal_torsion_reinforcement_not_verified"

    return {
        "status": status,
        "ok": ok,
        "reason": reason,
        "required_asl_mm2": required_asl,
        "required_by_tube_mm2": requirements,
        "required_design_force_kn": required_force,
        "provided_gross_area_mm2": (
            provided_area if assignments_valid else None
        ),
        "provided_design_force_kn": (
            provided_force if assignments_valid else None
        ),
        "provided_equivalent_area_mm2": equivalent_area,
        "reference_fyd_mpa": reference_fyd if reference_valid else None,
        "demand_ratio": demand_ratio,
        "area_sufficient": area_sufficient,
        "distribution_verified": False,
        "all_perimeter_sides_verified": False,
        "bending_reserve_verified": False,
        "anchorage_verified": False,
        "tube_allocation_verified": False,
    }


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
    """Return the exact face-aligned Plastic shear arm or why it is unavailable.

    Reinforced-shear checks use the component of the calculated
    tension-compression resultant arm for their selected axis and face.  A
    nominal ``0.9 d`` value is not substituted when that state is unavailable;
    callers must retain the links check as not assessed instead.
    """
    _nonnegative_finite_real(d_mm, "effective depth d")
    if inp["section"] is None:
        return None, (
            "calculated plastic lever arm unavailable: section model is not "
            "available"
        )
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
        return None, (
            "calculated plastic lever arm unavailable: the exact face-aligned "
            "Plastic solve did not converge"
        )
    lever = abs(_finite_solver_result(
        _solver_member(
            point,
            "dy" if axis == "x" else "dx",
            "plastic point",
        ),
        "plastic internal lever arm",
    ))
    if lever <= 1e-6:
        return None, (
            "calculated plastic lever arm unavailable: the face-aligned "
            "tension-compression resultant arm is zero or degenerate"
        )
    return lever * 1000.0, "plastic internal lever arm"


def shear_face_mrd(
    inp,
    axis,
    tension_low,
    m_off=0.0,
    *,
    moment_reference_shift=0.0,
):
    """Return chord ``M_Rd`` conditional on the coexisting off-axis moment.

    ``moment_reference_shift`` translates the own-axis resistance from the
    plastic solver's coordinate origin to the section reference used by the
    applied chord moment. The off-axis target remains in the origin frame because
    applying the same translation to its demand and envelope cancels exactly.
    """
    if inp["section"] is None:
        return 0.0, False
    angle = _face_angle(axis, tension_low)
    _require_valid_input_geometry(inp)
    reference_shift = _finite_solver_result(
        moment_reference_shift,
        "chord moment reference shift",
    )
    prestress = inp["prestress"] if inp["tendons"] else None
    conditional = conditional_capacity(
        inp["section"], inp["concrete"], inp["steel"], -inp["P_pl"],
        axis, tension_low, m_off,
        own_moment_offset=reference_shift,
        prestress=prestress,
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
    referenced_moment = moment + reference_shift
    if reference_shift == 0.0:
        return abs(moment), False
    correct_face = (
        referenced_moment > 0.0
        if tension_low
        else referenced_moment < 0.0
    )
    return (
        (abs(referenced_moment), False)
        if correct_face
        else (0.0, False)
    )


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
    angle_applicability=None,
):
    """Build the resistance/utilisation payload for one thin-walled tube."""
    wall_evidence = (
        tube.get("wall_evidence") if isinstance(tube, dict) else None
    )
    wall_geometry_assessed = bool(
        isinstance(tube, dict)
        and tube.get("valid") is True
        and tube.get("applicability_status") == "ASSESSED"
        and isinstance(wall_evidence, dict)
        and wall_evidence.get("complete") is True
    )
    if not wall_geometry_assessed:
        unchecked_tube = dict(tube) if isinstance(tube, dict) else {}
        unchecked_tube.update({
            "valid": False,
            "reason": (
                unchecked_tube.get("reason")
                or "torsion wall reinforcement locations are missing"
            ),
            "applicability_status": "NOT ASSESSED",
        })
        return unassessed_tube_torsion(
            unchecked_tube,
            t_ed,
            closed_links_present=closed_links_present,
        )
    shear = _module("shear")
    if angle_applicability is None:
        angle_applicability = shear.strut_angle_applicability(
            cot_min,
            cot_max,
            permitted_min=tcode.shear_cot_min_limit,
            permitted_max=tcode.shear_cot_max_limit,
            method=getattr(tcode, "label", "EN 1992-1-1:2005"),
            basis="first-generation torsion compression-strut range",
            clause="EN 1992-1-1:2005, 6.3.2(2)",
            active=abs(float(t_ed)) > 0.0,
        )
    if (
        angle_applicability.get("active", True) is True
        and angle_applicability.get("applicable") is not True
    ):
        torsion = _module("torsion")
        cracking = torsion.trd_c_result(fctd, tube["Ak"], tube["tef"])
        return unassessed_tube_torsion(
            tube,
            t_ed,
            closed_links_present=closed_links_present,
            tube_valid=True,
            trd_c=cracking.trd_c,
            cracking_resistance=asdict(cracking),
            reason=shear.STRUT_ANGLE_OUT_OF_RANGE_REASON,
            angle_applicability=angle_applicability,
        )
    closed_detailing_applied = bool(
        closed_links_present is True and nu_detail is True
    )
    nu_t = tcode.torsion_nu(
        fck,
        closed_detailing=closed_detailing_applied,
    )
    a_t = asw_over_s * fywd
    b_t = nu_t * alpha_cw * fcd * tube["tef"]
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
    transverse_resistance_assessed = bool(
        selection.full_resistance_assessed
    )
    valid = bool(tube_valid and transverse_resistance_assessed)
    assessment_reason = (
        None
        if transverse_resistance_assessed
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
        "transverse_resistance_assessed": transverse_resistance_assessed,
        # Retained for current project/result consumers; this field now means
        # only that the transverse-steel/concrete-strut component is available.
        "full_resistance_assessed": transverse_resistance_assessed,
        "assessment_reason": assessment_reason,
        "angle_selection": angle_selection,
        "angle_applicability": dict(angle_applicability),
        "steel_resistance": asdict(steel),
        "strut_resistance": asdict(strut),
        "resistance_selection": asdict(selection),
        "cracking_resistance": asdict(cracking),
        "longitudinal_reinforcement": asdict(longitudinal),
    }


def unassessed_tube_torsion(
    tube,
    t_ed,
    *,
    closed_links_present,
    tube_valid=False,
    trd_c=None,
    cracking_resistance=None,
    reason=None,
    angle_applicability=None,
):
    """Retain one invalid tube without entering any angle or resistance kernel."""

    reason = reason or tube.get("reason") or "torsion tube evidence is invalid"
    return {
        "tube": tube,
        "t_ed": t_ed,
        "trd_s": None,
        "trd_max": None,
        "trd": None,
        "trd_c": trd_c,
        "cot": None,
        "theta_deg": None,
        "util": None,
        "asl_req": None,
        "nu": None,
        "governs": None,
        "valid": False,
        "tube_valid": bool(tube_valid),
        "closed_links_present": bool(closed_links_present),
        "transverse_resistance_assessed": False,
        "full_resistance_assessed": False,
        "assessment_reason": reason,
        "angle_selection": None,
        "angle_applicability": (
            None
            if angle_applicability is None
            else dict(angle_applicability)
        ),
        "steel_resistance": None,
        "strut_resistance": None,
        "resistance_selection": None,
        "cracking_resistance": cracking_resistance,
        "longitudinal_reinforcement": None,
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
        "INVALID": 5,
        "FAIL": 4,
        "NOT ASSESSED": 3,
        "NOT RUN": 3,
        "CONDITIONAL": 2,
        "PASS": 1,
        "NOT APPLICABLE": 0,
    }.get(str(status or "").upper(), 3)
    value = float(utilisation or 0.0)
    if not math.isfinite(value):
        value = math.inf
    return priority, value


def aggregate_assessment_status(statuses):
    """Return the conservative status across every required candidate."""
    values = {str(status or "").upper() for status in statuses}
    for status in (
        "INVALID",
        "FAIL",
        "NOT ASSESSED",
        "NOT RUN",
        "CONDITIONAL",
        "PASS",
        "NOT APPLICABLE",
    ):
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
    shared_links_present = _shared_links_present(inp)
    component_prefix = f"shear_{component}_"
    shear_geometry = shear.resolve_shear_geometry(
        model_2023=model_2023,
        solid_rectangle=_module("geometry").section_is_approximately_solid_rectangle(
            inp["outer"], inp.get("holes") or ()
        ),
        section_form=inp.get("shear_section_form", shear.SHEAR_SECTION_AUTO),
        bw_mm=bw_mm,
        bw_user=bool(bw_override > 0.0),
        links_present=shared_links_present,
        web_inclination_deg=inp.get(
            component_prefix + "web_inclination_deg",
            inp.get("shear_web_inclination_deg", 0.0),
        ),
        hoop_diameter_mm=inp.get("shear_hoop_diameter", 0.0),
        fitted_z_mm=inp.get(
            component_prefix + "fitted_z",
            inp.get("shear_fitted_z", 0.0),
        ),
        duct_case=inp.get("shear_duct_case", shear.SHEAR_DUCT_NONE),
        duct_sum_mm=inp.get(
            component_prefix + "duct_sum",
            inp.get("shear_duct_sum", 0.0),
        ),
        duct_largest_mm=inp.get(
            component_prefix + "duct_largest",
            inp.get("shear_duct_largest", 0.0),
        ),
    )
    fck = inp["concrete"].fck
    fyd_flex = design_yield(inp["steel"])
    ddg = code.shear_ddg(fck, inp["shear_dlower"]) if model_2023 else 0.0
    if model_2023:
        try:
            gamma_v = shear.validate_gamma_v(
                inp.get("shear_gamma_v", _MISSING),
                label="gamma_V",
            )
        except ValueError as exc:
            raise CapacityInputError(
                "gamma_V must be a positive finite real number",
                engineer_message=EngineerMessage(
                    "SHEAR-GAMMA-V",
                    "gamma_V must be a positive finite real number",
                ),
            ) from exc
    else:
        gamma_v = None
    if axis == "x":
        moment_reference_shift = inp["P_pl"] * cy - mx_prestress
        m_ed_2023 = inp["Mx_pl"] + moment_reference_shift
        m_prestress = mx_prestress
    else:
        moment_reference_shift = inp["P_pl"] * cx - my_prestress
        m_ed_2023 = inp["My_pl"] + moment_reference_shift
        m_prestress = my_prestress
    if shear_geometry["concrete_valid"]:
        result = shear.vrd_c(
            fck,
            code,
            shear_geometry["concrete_bw_mm"],
            d_mm,
            asl,
            n_ed_comp,
            area,
            fyd_mpa=fyd_flex,
            ddg_mm=(ddg or 32.0),
            m_ed_knm=m_ed_2023,
            v_ed_kn=v_ed,
            fcd_mpa=inp["concrete"].fcd,
            gamma_c=inp["concrete"].gamma_c,
            gamma_v=gamma_v,
        )
    else:
        result = shear.unassessed_shear_result(
            model="2023" if model_2023 else "2005",
            reason=shear_geometry["concrete_reason"],
            bw_mm=bw_mm,
            d_mm=d_mm,
            asl_mm2=asl,
        )
    resistance = result.get("vrd_c")
    util = (
        v_ed / float(resistance)
        if result.get("valid") and resistance is not None and resistance > 0.0
        else None
        if result.get("calculation_state") == "NOT ASSESSED"
        else math.inf
    )
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
        "shear_geometry": shear_geometry,
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
        "moment_reference_shift": moment_reference_shift,
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
    angle_applicability = shear.strut_angle_applicability(
        cot_min,
        cot_max,
        permitted_min=angle_limits["minimum"],
        permitted_max=angle_limits["maximum"],
        method=str(inp["shear_method"]),
        basis=angle_limits["basis"],
        clause=angle_limits["clause"],
        active=abs(float(v_ed)) > 0.0,
    )
    asw = link_legs * _module("templates").bar_area(inp["shear_link_dia"])
    asw_over_s = asw / inp["shear_link_s"] if inp["shear_link_s"] > 0.0 else 0.0
    # Sector does not retain a selected N_Edw allocation or the action-state
    # compression-chord depth needed to determine the applicable 8.2.3(11) branch.
    # Under positive net compression, stop before the face-aligned Plastic lever-
    # arm solve: that capacity-boundary state is not a substitute for the missing
    # action-state evidence.
    if not shear_geometry["links_valid"]:
        z_mm = shear_geometry.get("fitted_z_mm")
        z_source = shear_geometry["links_reason"]
    elif shear_geometry.get("fitted_z_mm") is not None:
        z_mm = shear_geometry["fitted_z_mm"]
        z_source = "circular_fitted_section"
    elif model_2023 and n_ed_comp > 0.0:
        z_mm = None
        z_source = shear.LINKS_2023_AXIAL_COMPRESSION_REASON
    else:
        z_mm, z_source = shear_lever_arm(inp, axis, tension_low, d_mm)

    effective_asw_over_s = asw_over_s * float(
        shear_geometry.get("asw_factor") or 0.0
    )

    def links_at(
        cot_lo,
        cot_hi,
        angle_applicability_override=None,
        _fck=fck,
        _code=code,
        _bw=shear_geometry.get("links_bw_mm"),
        _d=d_mm,
        _asw_over_s=effective_asw_over_s,
        _area=area,
        _z=z_mm,
    ):
        if not shear_geometry["links_valid"]:
            return shear.unassessed_links_result(
                model="2023" if model_2023 else "2005",
                reason=shear_geometry["links_reason"],
                bw_mm=bw_mm,
                d_mm=_d,
                asw_over_s=_asw_over_s,
                z_mm=_z,
            )
        return shear.vrd_links(
            _fck, _code, _bw, _d, _asw_over_s, inp["shear_fywk"],
            n_ed_comp, _area, cot_lo, cot_hi, z_mm=_z,
            fcd_mpa=inp["concrete"].fcd,
            gamma_s=inp["steel"].gamma_y,
            v_ed_kn=v_ed,
            ductility_class=inp.get("transverse_ductility_class", "B"),
            angle_applicability=(
                angle_applicability
                if angle_applicability_override is None
                else angle_applicability_override
            ),
        )

    context = {
        "build": links_at,
        "cot_min": cot_min,
        "cot_max": cot_max,
        "asw": asw,
        "asw_over_s": asw_over_s,
        "effective_asw_over_s": effective_asw_over_s,
        "asw_factor": shear_geometry.get("asw_factor"),
        "shear_geometry": shear_geometry,
        "z_mm": z_mm,
        "z_src": z_source,
        "z_component": "z_y" if axis == "x" else "z_x",
        "z_source_angle_deg": _face_angle(axis, tension_low),
        "z_source_case": str(
            (inp.get("plastic_case") or {}).get("id") or ""
        ).strip(),
        "z_source_axial_kn": float(inp["P_pl"]),
        "code": code,
        "v_ed": v_ed,
        "vrd_c": result.get("vrd_c"),
        "axis": axis,
        "tension_low": tension_low,
        "component": component,
        "link_legs": link_legs,
        "model_2023": model_2023,
        "m_ed_2023": m_ed_2023,
        "moment_reference_shift": moment_reference_shift,
        "m_prestress": m_prestress,
        "centroid": (cx, cy),
        "angle_limits": angle_limits,
        "angle_applicability": angle_applicability,
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
    tef_override_mm = _nonnegative_finite_real(
        inp["torsion_tef"],
        "torsion wall-thickness override",
        engineer_message=_TORSION_WALL_INPUT,
    )
    if subdivision_requested:
        if tef_override_mm > 0.0:
            raise CapacityInputError(
                "torsion wall-thickness override must be 0 (automatic per sub-tube) "
                "when torsion subdivision is enabled",
                engineer_message=_TORSION_SUBDIVISION_WALL_INPUT,
            )
    torsion = _module("torsion")
    try:
        tube = torsion.tube_properties_with_reinforcement(
            inp["outer"],
            inp["holes"],
            inp.get("bars"),
            tef_override=tef_override_mm,
        )
    except torsion.TorsionWallThicknessError as exc:
        raise CapacityInputError(
            *exc.args,
            engineer_message=_TORSION_HOLLOW_WALL_INPUT,
        ) from exc
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
    angle_limits = {
        "minimum": tcode.shear_cot_min_limit,
        "maximum": tcode.shear_cot_max_limit,
        "basis": "first-generation torsion compression-strut range",
        "clause": "EN 1992-1-1:2005, 6.3.2(2)",
    }
    # The entered torsion sign identifies the applied sense; every resistance,
    # reinforcement-demand and interaction equation consumes its magnitude.  The
    # case-table adapter already performs this conversion, but the public direct
    # analysis path reaches this shared boundary without that adapter.
    t_ed = abs(
        _finite_solver_result(inp.get("torsion_T"), "entered torsion action")
    )
    angle_applicability = _module("shear").strut_angle_applicability(
        cot_min,
        cot_max,
        permitted_min=angle_limits["minimum"],
        permitted_max=angle_limits["maximum"],
        method=str(inp["torsion_method"]),
        basis=angle_limits["basis"],
        clause=angle_limits["clause"],
        active=abs(float(t_ed)) > 0.0,
    )
    nu_detail = bool(closed_links_present and nu_detail_requested)
    nu_detail_applied = bool(
        nu_detail
        and tcode.torsion_nu(fck, closed_detailing=True)
        != tcode.torsion_nu(fck, closed_detailing=False)
    )
    gamma_c = inp["concrete"].gamma_c
    gamma_ct = _positive_finite_real(
        inp["torsion_gamma_ct"],
        "gamma_ct",
        engineer_message=_TORSION_GAMMA_CT_INPUT,
    )
    fctk_005 = 0.7 * codes.fctm(fck)
    fctd = fctk_005 / gamma_ct
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
        "angle_applicability": angle_applicability,
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
        rectangles_m = [
            (
                x_mm / 1000.0,
                y_mm / 1000.0,
                b_mm / 1000.0,
                h_mm / 1000.0,
            )
            for x_mm, y_mm, b_mm, h_mm in subrects
        ]
        local_bar_sets: list[list[tuple[float, float, float]]] | None = [
            [] for _rectangle in rectangles_m
        ]
        local_bar_positions: list[list[int]] | None = [
            [] for _rectangle in rectangles_m
        ]
        assignment_reason = None
        raw_bars = inp.get("bars")
        if type(raw_bars) not in (tuple, list):
            local_bar_sets = None
            local_bar_positions = None
            assignment_reason = "torsion sub-tube reinforcement locations are missing"
        else:
            scale = max(
                [1.0, *[max(abs(x), abs(y), b, h) for x, y, b, h in rectangles_m]]
            )
            membership_tolerance = max(1.0e-12 * scale, 8.0 * math.ulp(scale))
            for bar_position, raw_bar in enumerate(raw_bars, start=1):
                if type(raw_bar) not in (tuple, list) or len(raw_bar) != 3:
                    local_bar_sets = None
                    local_bar_positions = None
                    assignment_reason = (
                        "torsion sub-tube reinforcement locations are invalid"
                    )
                    break
                coordinates = []
                malformed = False
                for value in raw_bar:
                    if (
                        isinstance(value, (str, bytes))
                        or type(value).__name__ in {"bool", "bool_"}
                    ):
                        malformed = True
                        break
                    try:
                        number = float(value)
                    except (TypeError, ValueError, OverflowError):
                        malformed = True
                        break
                    if not math.isfinite(number):
                        malformed = True
                        break
                    coordinates.append(number)
                if malformed or coordinates[2] <= 0.0:
                    local_bar_sets = None
                    local_bar_positions = None
                    assignment_reason = (
                        "torsion sub-tube reinforcement locations are invalid"
                    )
                    break
                x_bar, y_bar, area_bar = coordinates
                memberships = [
                    index
                    for index, (x, y, b, h) in enumerate(rectangles_m)
                    if (
                        x - b / 2.0 - membership_tolerance
                        <= x_bar
                        <= x + b / 2.0 + membership_tolerance
                        and y - h / 2.0 - membership_tolerance
                        <= y_bar
                        <= y + h / 2.0 + membership_tolerance
                    )
                ]
                if len(memberships) != 1:
                    local_bar_sets = None
                    local_bar_positions = None
                    assignment_reason = (
                        "torsion sub-tube reinforcement assignment is ambiguous"
                        if len(memberships) > 1
                        else "torsion sub-tube reinforcement mapping is incomplete"
                    )
                    break
                rectangle_index = memberships[0]
                rectangle_x, rectangle_y, _b, _h = rectangles_m[rectangle_index]
                local_bar_sets[rectangle_index].append((
                    x_bar - rectangle_x,
                    y_bar - rectangle_y,
                    area_bar,
                ))
                local_bar_positions[rectangle_index].append(bar_position)
        for index, (x_mm, y_mm, b_mm, h_mm) in enumerate(subrects):
            b_m, h_m = b_mm / 1000.0, h_mm / 1000.0
            selected = torsion.tube_properties_with_reinforcement(
                torsion.rectangle_ring(b_m, h_m),
                None,
                None if local_bar_sets is None else local_bar_sets[index],
                longitudinal_bar_positions=(
                    None
                    if local_bar_positions is None
                    else local_bar_positions[index]
                ),
            )
            if assignment_reason is not None:
                selected = dict(selected, reason=assignment_reason)
                selected["wall_evidence"] = dict(
                    selected.get("wall_evidence") or {},
                    complete=False,
                    reason=assignment_reason,
                )
            subtubes.append(selected)
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
        "angle_limits": angle_limits,
        "angle_applicability": angle_applicability,
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


_DKNA_CLAUSE = "DS/EN 1992-1-1 DK NA:2024, 6.3.2(6)"
_DKNA_ACTION_ALONE_GUIDANCE = (
    "An action-alone resistance could not be determined. Check the section, "
    "materials and complete Plastic bending sweep before using the combined result."
)


def _dkna_action_record(
    symbol,
    demand,
    resistance,
    *,
    valid,
    direction=None,
    evidence=None,
    reason=None,
):
    """Return one compact retained action-alone resistance record."""

    return {
        "symbol": symbol,
        "demand": demand,
        "resistance": resistance,
        "valid": bool(valid),
        "direction": direction,
        "evidence": evidence or {},
        "reason": reason,
        "source_clause": _DKNA_CLAUSE,
    }


def _dkna_plastic_envelope(inp, axial_solver_kn):
    """Return one full Plastic M-M envelope at the specified solver axial force."""

    plastic = _module("plastic")
    angles = plastic.plastic_sweep_angles(
        inp["v_min"], inp["v_max"], inp["v_inc"]
    )
    if not plastic.plastic_sweep_is_full_turn(angles[0], angles[-1]):
        return None, "A complete Plastic bending sweep is required"
    prestress = inp["prestress"] if inp.get("tendons") else None
    points = solve_plastic(
        inp["section"],
        inp["concrete"],
        inp["steel"],
        axial_solver_kn,
        angles[0],
        angles[-1],
        inp["v_inc"],
        prestress=prestress,
        bar_materials=inp.get("bar_materials"),
        tendon_materials=inp.get("tendon_materials"),
    )
    if not points or not all(
        _solver_flag(
            _solver_member(point, "converged", "Plastic action-alone point"),
            "Plastic action-alone point converged",
        )
        for point in points
    ):
        return None, "The action-alone Plastic bending sweep did not converge"
    return points, None


def _dkna_zero_moment_is_resisted(inp, axial_solver_kn):
    """Return whether the action-alone M-M envelope contains the zero-moment point."""

    points, reason = _dkna_plastic_envelope(inp, axial_solver_kn)
    if points is None:
        return False, reason
    radial = _module("combined").radial_util_result(
        [point.Mx for point in points],
        [point.My for point in points],
        0.0,
        0.0,
    )
    return bool(radial.valid), (
        None if radial.valid else "The zero-moment axial state was not resolved"
    )


def _dkna_axial_action_alone(inp):
    """Determine ``NRd`` for the entered axial sign with M, V and T absent."""

    n_ed = _finite_solver_result(inp.get("P_pl"), "entered axial action")
    direction = "tension" if n_ed > 0.0 else "compression" if n_ed < 0.0 else None
    if n_ed == 0.0:
        return _dkna_action_record(
            "N", n_ed, None, valid=True, direction=direction,
            evidence={"iterations": 0},
        )
    prestress = inp["prestress"] if inp.get("tendons") else None
    try:
        boundary = solve_zero_moment_axial_capacity(
            inp["section"],
            inp["concrete"],
            inp["steel"],
            tension=n_ed > 0.0,
            prestress=prestress,
            bar_materials=inp.get("bar_materials"),
            tendon_materials=inp.get("tendon_materials"),
        )
    except (ArithmeticError, TypeError, ValueError, OverflowError):
        return _dkna_action_record(
            "N", n_ed, None, valid=False, direction=direction,
            reason=_DKNA_ACTION_ALONE_GUIDANCE,
        )
    if boundary.converged is not True or boundary.axial is None:
        return _dkna_action_record(
            "N", n_ed, None, valid=False, direction=direction,
            reason=_DKNA_ACTION_ALONE_GUIDANCE,
        )
    accepted = _finite_solver_result(
        boundary.axial, "zero-moment axial resistance"
    )
    if (n_ed > 0.0 and accepted >= 0.0) or (
        n_ed < 0.0 and accepted <= 0.0
    ):
        return _dkna_action_record(
            "N", n_ed, None, valid=False, direction=direction,
            reason=_DKNA_ACTION_ALONE_GUIDANCE,
        )
    resistance = abs(accepted)
    if not math.isfinite(resistance) or resistance <= 0.0:
        return _dkna_action_record(
            "N", n_ed, None, valid=False, direction=direction,
            reason=_DKNA_ACTION_ALONE_GUIDANCE,
        )
    return _dkna_action_record(
        "N",
        n_ed,
        resistance,
        valid=True,
        direction=direction,
        evidence={
            "solver_axial_kn": accepted,
            "endpoint_axial_kn": boundary.endpoint_axial,
            "iterations": boundary.iterations,
            "point_evaluations": boundary.point_evaluations,
            "neutral_axis_angle_deg": boundary.neutral_axis_angle_deg,
            "moment_residual_knm": boundary.moment_residual_knm,
            "moment_tolerance_knm": boundary.moment_tolerance_knm,
            "zero_moment": True,
        },
    )


def _dkna_bending_action_alone(inp):
    """Determine ``MRd`` on the entered biaxial ray with N, V and T absent."""

    mx_ed = _finite_solver_result(inp.get("Mx_pl"), "entered Mx action")
    my_ed = _finite_solver_result(inp.get("My_pl"), "entered My action")
    m_ed = math.hypot(mx_ed, my_ed)
    direction_deg = (
        math.degrees(math.atan2(my_ed, mx_ed)) % 360.0 if m_ed > 0.0 else None
    )
    if m_ed == 0.0:
        return _dkna_action_record(
            "M",
            m_ed,
            None,
            valid=True,
            direction=direction_deg,
            evidence={"mx_ed": mx_ed, "my_ed": my_ed},
        )
    try:
        points, reason = _dkna_plastic_envelope(inp, 0.0)
    except (ArithmeticError, TypeError, ValueError, OverflowError):
        points, reason = None, _DKNA_ACTION_ALONE_GUIDANCE
    if points is None:
        return _dkna_action_record(
            "M", m_ed, None, valid=False, direction=direction_deg,
            evidence={"mx_ed": mx_ed, "my_ed": my_ed},
            reason=_DKNA_ACTION_ALONE_GUIDANCE if reason else reason,
        )
    radial = _module("combined").radial_util_result(
        [point.Mx for point in points],
        [point.My for point in points],
        mx_ed,
        my_ed,
    )
    if not radial.valid or radial.resistance is None:
        return _dkna_action_record(
            "M", m_ed, None, valid=False, direction=direction_deg,
            evidence={"mx_ed": mx_ed, "my_ed": my_ed},
            reason=_DKNA_ACTION_ALONE_GUIDANCE,
        )
    resistance = _positive_finite_real(radial.resistance, "action-alone MRd")
    return _dkna_action_record(
        "M",
        m_ed,
        resistance,
        valid=True,
        direction=direction_deg,
        evidence={
            "mx_ed": mx_ed,
            "my_ed": my_ed,
            "governing_index": radial.governing_index,
            "axial_action_kn": 0.0,
        },
    )


def dkna_normal_bending_action_alone(inp):
    """Return reusable action-alone N and M resistance evidence."""

    return {
        "n": _dkna_axial_action_alone(inp),
        "m": _dkna_bending_action_alone(inp),
    }


def _dkna_shear_action_alone(inp):
    """Determine ``VRd`` for the selected shear direction with N, M and T absent.

    An automatic tension-face selection cannot be inherited from the acting
    bending moment because that moment is absent in this action-alone state.
    Both physical faces are therefore required and the lower valid resistance
    governs.  An explicitly selected face remains authoritative.
    """

    v_ed = abs(_finite_solver_result(inp.get("shear_V"), "entered shear action"))
    if v_ed == 0.0:
        return _dkna_action_record("V", 0.0, None, valid=True)
    isolated = dict(
        inp,
        P_pl=0.0,
        Mx_pl=0.0,
        My_pl=0.0,
        torsion_T=0.0,
    )
    axis = isolated.get("shear_axis")
    face_key = {"x": "shear_face_y", "y": "shear_face_x"}.get(axis)
    if face_key is not None and face_key in isolated:
        face_mode = isolated.get(face_key)
        try:
            faces = shear_face_candidates(face_mode, 0.0)
        except (TypeError, ValueError):
            return _dkna_action_record(
                "V", v_ed, None, valid=False,
                reason=_DKNA_ACTION_ALONE_GUIDANCE,
            )
    else:
        # Current projects always retain the directional face selector.  This
        # compatibility path preserves the explicitly translated legacy input.
        face_mode = "selected"
        faces = (bool(isolated.get("shear_tension")),)

    try:
        n_prestress = prestress_axial(isolated)
    except (ArithmeticError, TypeError, ValueError, OverflowError):
        return _dkna_action_record(
            "V", v_ed, None, valid=False,
            reason=_DKNA_ACTION_ALONE_GUIDANCE,
        )

    candidates = []
    for tension_low in faces:
        face_input = dict(isolated, shear_tension=bool(tension_low))
        try:
            shear_payload, link_context = build_shear_context(
                face_input, n_prestress, n_prestress
            )
            if (
                shear_payload is None
                or not (shear_payload.get("res") or {}).get("valid")
            ):
                raise CapacityResultError("action-alone shear face is unavailable")
            shear_payload = dict(shear_payload, v_ed=v_ed)
            if link_context is None:
                selection = select_nominal_shear_resistance(
                    shear_payload, links_selected=False
                )
            else:
                links = link_context["build"](
                    link_context["cot_min"], link_context["cot_max"]
                )
                if not links.get("valid"):
                    raise CapacityResultError(
                        "action-alone reinforced shear face is unavailable"
                    )
                shear_payload = dict(
                    shear_payload,
                    links={"res": links, "util": links.get("util")},
                )
                selection = select_nominal_shear_resistance(
                    shear_payload, links_selected=True
                )
            if not selection.valid:
                raise CapacityResultError("action-alone shear resistance is unavailable")
            resistance = selection.resistance
            cot = (
                (shear_payload.get("links") or {}).get("res", {}).get("cot")
                if selection.route == "links"
                else None
            )
            resistance_kind = (
                "concrete shear resistance"
                if selection.route == "concrete"
                else "reinforced shear resistance"
            )
            resistance_value = _positive_finite_real(
                resistance, "action-alone VRd"
            )
        except (ArithmeticError, TypeError, ValueError, OverflowError):
            return _dkna_action_record(
                "V", v_ed, None, valid=False,
                reason=_DKNA_ACTION_ALONE_GUIDANCE,
            )
        candidates.append({
            "tension_low": bool(tension_low),
            "resistance": resistance_value,
            "cot": cot,
            "resistance_kind": resistance_kind,
        })

    governing = min(candidates, key=lambda item: item["resistance"])
    return _dkna_action_record(
        "V",
        v_ed,
        governing["resistance"],
        valid=True,
        direction=isolated.get("shear_axis"),
        evidence={
            "axis": isolated.get("shear_axis"),
            "face_mode": str(face_mode),
            "both_faces_evaluated": len(candidates) == 2,
            "faces_evaluated": [
                "negative" if item["tension_low"] else "positive"
                for item in candidates
            ],
            "governing_face": (
                "negative" if governing["tension_low"] else "positive"
            ),
            "cot": governing["cot"],
            "resistance_kind": governing["resistance_kind"],
            "nominal_route": (
                "concrete"
                if governing["resistance_kind"] == "concrete shear resistance"
                else "links"
            ),
            "face_resistances": candidates,
            "external_axial_action_kn": 0.0,
            "external_moment_knm": 0.0,
        },
    )


def _dkna_torsion_action_alone(inp):
    """Determine ``TRd`` with external N, M and V absent."""

    t_ed = abs(_finite_solver_result(inp.get("torsion_T"), "entered torsion action"))
    if t_ed == 0.0:
        return _dkna_action_record("T", 0.0, None, valid=True)
    isolated = dict(
        inp,
        P_pl=0.0,
        Mx_pl=0.0,
        My_pl=0.0,
        shear_V=0.0,
        shear_Vx=0.0,
        shear_Vy=0.0,
        torsion_T=t_ed,
    )
    n_prestress = prestress_axial(isolated)
    context = build_torsion_context(isolated, n_prestress)
    if context is None:
        return _dkna_action_record(
            "T", t_ed, None, valid=False,
            reason=_DKNA_ACTION_ALONE_GUIDANCE,
        )
    results = [
        tube_torsion(
            tube,
            torque,
            **context["_tk"],
        )
        for tube, torque in zip(
            context["subtubes"], context["ted_parts"], strict=True
        )
    ]
    if not results or not all(result.get("valid") for result in results):
        return _dkna_action_record(
            "T", t_ed, None, valid=False,
            reason=_DKNA_ACTION_ALONE_GUIDANCE,
        )
    governing_index = max(
        range(len(results)), key=lambda index: results[index]["util"]
    )
    governing_util = results[governing_index]["util"]
    if governing_util is None or governing_util <= 0.0:
        return _dkna_action_record(
            "T", t_ed, None, valid=False,
            reason=_DKNA_ACTION_ALONE_GUIDANCE,
        )
    try:
        resistance = _positive_finite_real(
            t_ed / governing_util, "action-alone TRd"
        )
    except CapacityInputError:
        return _dkna_action_record(
            "T", t_ed, None, valid=False,
            reason=_DKNA_ACTION_ALONE_GUIDANCE,
        )
    return _dkna_action_record(
        "T",
        t_ed,
        resistance,
        valid=True,
        evidence={
            "governing_subtube": governing_index + 1,
            "cot": results[governing_index].get("cot"),
            "subtube_count": len(results),
            "external_axial_action_kn": 0.0,
        },
    )


def finalize_combined(inp, out):
    """Build the final combined M-V-T payload from completed component checks."""
    if not inp.get("combined_on"):
        return
    selected_code = selected_combined_code(inp.get("combined_method"))
    dkna_basis = selected_code.key == codes.EC2_2005_DKNA.key
    independent_mv = (
        _solver_flag(
            inp["combined_mv_independent"],
            "independent M/V longitudinal-reinforcement condition",
        )
        if dkna_basis
        else False
    )
    separation_condition = None
    if dkna_basis:
        separation_condition = {
            "confirmed": False,
            "declared": independent_mv,
            "mechanically_verified": False,
            "verification_state": (
                "design assumption" if independent_mv else "not selected"
            ),
            "condition": (
                "Additional longitudinal reinforcement required for shear "
                "beyond that required for bending is provided"
            ),
            "limitation": (
                "This section calculation does not verify the additional "
                "reinforcement capacity, distribution or anchorage"
            ),
            "source_clause": _DKNA_CLAUSE,
        }
    plastic = out.get("plastic")
    shear_out = out.get("shear")
    torsion_out = out.get("torsion")
    torsion_assessment_status = None
    torsion_assessment_reason = None
    if torsion_out is not None:
        torsion_assessment_status = str(
            torsion_out.get("assessment_status", "NOT ASSESSED")
        ).upper()
        if torsion_assessment_status not in {
            "PASS", "FAIL", "NOT ASSESSED"
        }:
            torsion_assessment_status = "NOT ASSESSED"
        torsion_assessment_reason = torsion_out.get("overall_reason")
    r_m = plastic.get("util") if plastic else None
    have_m = r_m is not None
    links = shear_out.get("links") if shear_out is not None else None
    links_selected = inp.get("shear_links") is True or links is not None
    shear_selection_input = dict(shear_out or {})
    demand = shear_selection_input.get("v_ed")
    if demand is None:
        demand = abs(
            _finite_solver_result(inp.get("shear_V"), "entered shear action")
        )
        shear_selection_input["v_ed"] = demand
    concrete_result = dict(shear_selection_input.get("res") or {})
    if concrete_result.get("vrd_c") is None:
        concrete_util = shear_selection_input.get("util")
        if (
            not _is_boolean_scalar(concrete_util)
            and isinstance(concrete_util, (int, float))
            and math.isfinite(float(concrete_util))
            and float(concrete_util) > 0.0
        ):
            concrete_result["vrd_c"] = float(demand) / float(concrete_util)
    shear_selection_input["res"] = concrete_result
    if isinstance(links, Mapping):
        link_payload = dict(links)
        link_result = dict(link_payload.get("res") or {})
        if link_result.get("vrd") is None:
            link_candidates = []
            for key in ("vrd_s", "vrd_max"):
                value = link_result.get(key)
                if value is None or _is_boolean_scalar(value):
                    continue
                try:
                    candidate = float(value)
                except (TypeError, ValueError, OverflowError):
                    continue
                if math.isfinite(candidate) and candidate > 0.0:
                    link_candidates.append(candidate)
            if link_candidates:
                link_result["vrd"] = min(link_candidates)
            else:
                link_util = link_payload.get("util")
                if (
                    not _is_boolean_scalar(link_util)
                    and isinstance(link_util, (int, float))
                    and math.isfinite(float(link_util))
                    and float(link_util) > 0.0
                ):
                    link_result["vrd"] = float(demand) / float(link_util)
        link_payload["res"] = link_result
        shear_selection_input["links"] = link_payload
    shear_selection = select_nominal_shear_resistance(
        shear_selection_input,
        links_selected=links_selected,
    )
    chord_assessment = (
        links.get("longitudinal_assessment")
        if isinstance(links, Mapping)
        else None
    )
    have_v = shear_selection.valid
    have_t = torsion_out is not None and torsion_out["valid"]
    if not (have_m and have_v and have_t):
        angle_applicability = None
        if isinstance(torsion_out, Mapping):
            angle_applicability = torsion_out.get("angle_applicability")
        if angle_applicability is None and isinstance(links, Mapping):
            angle_applicability = links.get("angle_applicability") or (
                (links.get("res") or {}).get("angle_applicability")
            )
        shear_reason = None
        if not shear_selection.valid:
            shear_reason = (
                shear_selection.reason
                or (links or {}).get("assessment_reason")
                or ((links or {}).get("res") or {}).get("reason")
                or "the selected shear resistance was not assessed"
            )
        payload = {
            "valid": False,
            "have_m": have_m,
            "have_v": have_v,
            "have_t": have_t,
            "method": inp["combined_method"],
        }
        if dkna_basis:
            payload.update(
                m_v_independent=independent_mv,
                m_v_separation_condition=separation_condition,
            )
        if isinstance(links, Mapping) and links.get("model_2023") is True:
            payload["longitudinal_model_2023"] = True
        if torsion_assessment_status is not None:
            payload["torsion_assessment_status"] = torsion_assessment_status
            payload["torsion_assessment_reason"] = torsion_assessment_reason
        if (
            isinstance(angle_applicability, Mapping)
            and angle_applicability.get("active", True) is True
            and angle_applicability.get("applicable") is False
        ):
            payload["outside_default_range"] = True
            payload["angle_applicability"] = dict(angle_applicability)
        if shear_reason is not None:
            payload["reason"] = shear_reason
        elif torsion_assessment_reason == (
            _module("shear").STRUT_ANGLE_OUT_OF_RANGE_REASON
        ):
            payload["reason"] = torsion_assessment_reason
        out["combined"] = payload
        return

    combined = _module("combined")
    outside_default_range = bool(
        torsion_out.get("out_of_limits")
        or (links is not None and links.get("out_of_limits"))
    )
    component_statuses = [torsion_assessment_status or "NOT ASSESSED"]
    if isinstance(chord_assessment, Mapping):
        component_statuses.append(
            str(chord_assessment.get("status") or "NOT ASSESSED").upper()
        )
    payload = {
        "valid": True,
        "method": inp["combined_method"],
        "torsion_assessment_status": (
            torsion_assessment_status or "NOT ASSESSED"
        ),
        "torsion_assessment_reason": torsion_assessment_reason,
        "torsion_longitudinal_assessment": torsion_out.get(
            "longitudinal_assessment"
        ),
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
    if dkna_basis:
        retained_nm = inp.get("_dkna_nm_action_alone")
        if not isinstance(retained_nm, Mapping) or not all(
            isinstance(retained_nm.get(key), Mapping) for key in ("n", "m")
        ):
            retained_nm = dkna_normal_bending_action_alone(inp)
        n_action = dict(retained_nm["n"])
        m_action = dict(retained_nm["m"])
        v_action = _dkna_shear_action_alone(inp)
        t_action = _dkna_torsion_action_alone(inp)
        dk_selection = combined.dkna_interaction_result(
            n_action["demand"],
            n_action["resistance"],
            m_action["demand"],
            m_action["resistance"],
            v_action["demand"],
            v_action["resistance"],
            t_action["demand"],
            t_action["resistance"],
            m_v_independent=independent_mv,
        )
        payload.update(
            source_clause=_DKNA_CLAUSE,
            r_n=dk_selection.r_n,
            r_m=dk_selection.r_m,
            r_v=dk_selection.r_v,
            r_t=dk_selection.r_t,
            m_v_independent=independent_mv,
            m_v_separation_condition=separation_condition,
            dkna_sum=dk_selection.utilisation,
            dkna_valid=dk_selection.valid,
            dkna_reason=dk_selection.reason,
            dkna_conditional=dk_selection.conditional,
            dkna_limit_satisfied=dk_selection.limit_satisfied,
            dkna_status=dk_selection.status,
            dkna_ok=dk_selection.ok,
            assessment_status=aggregate_assessment_status((
                *component_statuses,
                dk_selection.status,
            )),
            dkna_selection=asdict(dk_selection),
            action_alone={
                "n": n_action,
                "m": m_action,
                "v": v_action,
                "t": t_action,
            },
        )
    if isinstance(links, Mapping) and links.get("model_2023") is True:
        payload["longitudinal_model_2023"] = True
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
            "longitudinal_assessment",
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
