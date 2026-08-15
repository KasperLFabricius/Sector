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


@dataclass(frozen=True, slots=True)
class CombinedPrerequisiteAssessment:
    """Normalized evidence required before a combined M-V-T assessment."""

    method: str
    m_v_independent: bool
    valid: bool
    r_m: float | None
    r_v: float | None
    r_t: float | None
    have_m: bool
    have_v: bool
    have_t: bool
    plastic_valid: bool
    shear_valid: bool
    links_required: bool
    links_valid: bool
    torsion_valid: bool
    reasons: tuple[str, ...]



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


def _optional_finite_result(value: Any) -> float | None:
    """Normalize non-negative finite utilisation without accepting Booleans."""

    if _is_boolean_scalar(value) or isinstance(value, (str, bytes)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number >= 0.0 else None


def _optional_positive_finite_result(value: Any) -> float | None:
    number = _optional_finite_result(value)
    return number if number is not None and number > 0.0 else None


def _combined_member_angle_selection_cot(value: object) -> float | None:
    """Return the cotangent from one minimally complete retained angle scan."""

    if not isinstance(value, Mapping):
        return None
    cot = _optional_positive_finite_result(value.get("cot"))
    theta_deg = _optional_finite_result(value.get("theta_deg"))
    utilisation = _optional_finite_result(value.get("utilisation"))
    cot_min = _optional_positive_finite_result(value.get("cot_min"))
    cot_max = _optional_positive_finite_result(value.get("cot_max"))
    step = _optional_finite_result(value.get("step"))
    samples = value.get("samples")
    selected_index = value.get("selected_index")
    objective_count = value.get("objective_count")
    labels = value.get("objective_labels")
    governing_indices = value.get("governing_component_indices")
    governing_labels = value.get("governing_objectives")
    runner_up = value.get("runner_up_utilisation")
    runner_up_value = (
        _optional_finite_result(runner_up)
        if runner_up is not None
        else None
    )
    if (
        cot is None
        or theta_deg is None
        or utilisation is None
        or cot_min is None
        or cot_max is None
        or step is None
        or type(samples) is not int
        or samples < 2
        or type(selected_index) is not int
        or not 0 <= selected_index < samples
        or type(objective_count) is not int
        or objective_count <= 0
        or not isinstance(labels, (list, tuple))
        or len(labels) != objective_count
        or any(type(label) is not str or not label for label in labels)
        or not isinstance(governing_indices, (list, tuple))
        or not governing_indices
        or any(
            type(index) is not int or not 0 <= index < objective_count
            for index in governing_indices
        )
        or len(set(governing_indices)) != len(governing_indices)
        or tuple(governing_indices) != tuple(sorted(governing_indices))
        or not isinstance(governing_labels, (list, tuple))
        or any(
            type(label) is not str or not label for label in governing_labels
        )
        or tuple(governing_labels)
        != tuple(labels[index] for index in governing_indices)
        or cot_max < cot_min
        or not math.isclose(
            step,
            (cot_max - cot_min) / (samples - 1),
            rel_tol=1.0e-12,
            abs_tol=1.0e-12,
        )
        or not math.isclose(
            cot,
            cot_min + step * selected_index,
            rel_tol=1.0e-12,
            abs_tol=1.0e-12,
        )
        or (
            len(governing_indices) == objective_count
            and runner_up is not None
        )
        or (
            len(governing_indices) < objective_count
            and (
                runner_up_value is None
                or runner_up_value >= utilisation
            )
        )
        or not math.isclose(
            theta_deg,
            math.degrees(math.atan2(1.0, cot)),
            rel_tol=1.0e-12,
            abs_tol=1.0e-12,
        )
    ):
        return None
    return cot


def _combined_plastic_prerequisite(
    plastic: object,
) -> tuple[bool, float | None, tuple[str, ...]]:
    reasons: list[str] = []
    r_m = _optional_finite_result(
        plastic.get("util") if isinstance(plastic, Mapping) else None
    )
    valid = isinstance(plastic, Mapping)
    if not valid:
        reasons.append("plastic result is missing or malformed")
    else:
        for key, reason in (
            ("converged", "plastic result is not converged"),
            ("closed", "plastic envelope is not closed"),
            ("check_util", "plastic utilisation was not checked"),
            ("util_valid", "plastic utilisation is not valid"),
        ):
            if plastic.get(key) is not True:
                valid = False
                reasons.append(reason)
        if r_m is None:
            valid = False
            reasons.append("plastic utilisation is not finite")
    return valid, r_m, tuple(reasons)


def combined_plastic_prerequisite_is_valid(plastic: object) -> bool:
    """Return whether bending evidence may influence a combined M-V-T check."""

    valid, _utilisation, _reasons = _combined_plastic_prerequisite(plastic)
    return valid


def _evaluate_combined_prerequisites(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    require_final_evidence: bool,
) -> CombinedPrerequisiteAssessment:
    """Evaluate component evidence, optionally including post-scan evidence.

    Link authority comes only from ``inp['shear_links']``.  A retained links
    payload is therefore ignored when links are inactive, while an active links
    check must own its own valid result and finite utilisation.
    """

    method = selected_combined_code(inp.get("combined_method")).label
    for key, family in (
        ("shear_method", "shear"),
        ("torsion_method", "torsion"),
    ):
        component_method = inp.get(key)
        if type(component_method) is not str or component_method != method:
            raise CapacityInputError(
                f"combined {family} method must equal the combined method"
            )
    m_v_independent = inp.get("combined_mv_independent")
    if type(m_v_independent) is not bool:
        raise CapacityInputError(
            "combined M-V independence must be a concrete Boolean"
        )
    links_required = inp.get("shear_links")
    if type(links_required) is not bool:
        raise CapacityInputError(
            "combined shear-links authority must be a concrete Boolean"
        )

    reasons: list[str] = []

    plastic_valid, r_m, plastic_reasons = _combined_plastic_prerequisite(
        out.get("plastic")
    )
    reasons.extend(plastic_reasons)

    shear_out = out.get("shear")
    shear_valid = (
        isinstance(shear_out, Mapping)
        and isinstance(shear_out.get("res"), Mapping)
        and shear_out["res"].get("valid") is True
    )
    if not isinstance(shear_out, Mapping):
        reasons.append("shear result is missing or malformed")
    else:
        if not shear_valid:
            reasons.append("shear resistance result is not valid")
        if type(shear_out.get("method")) is not str or shear_out.get(
            "method"
        ) != method:
            shear_valid = False
            reasons.append("shear method is missing or inconsistent")

    links_valid = not links_required
    r_v: float | None = None
    if links_required:
        links = shear_out.get("links") if isinstance(shear_out, Mapping) else None
        links_valid = (
            isinstance(links, Mapping)
            and isinstance(links.get("res"), Mapping)
            and links["res"].get("valid") is True
        )
        if not isinstance(links, Mapping):
            reasons.append("active shear-links result is missing or malformed")
        elif not links_valid:
            reasons.append("active shear-links resistance result is not valid")
        r_v = _optional_finite_result(
            links.get("util") if isinstance(links, Mapping) else None
        )
        if r_v is None:
            links_valid = False
            reasons.append("active shear-links utilisation is not finite")
        if isinstance(links, Mapping):
            link_res = links.get("res")
            delta_ftd = _optional_finite_result(links.get("delta_ftd", _MISSING))
            v_ed = _optional_finite_result(
                shear_out.get("v_ed") if isinstance(shear_out, Mapping) else None
            )
            cot = _optional_positive_finite_result(
                link_res.get("cot") if isinstance(link_res, Mapping) else None
            )
            if (
                delta_ftd is None
                or v_ed is None
                or cot is None
                or not math.isclose(
                    delta_ftd,
                    0.5 * v_ed * cot,
                    rel_tol=1.0e-12,
                    abs_tol=1.0e-12,
                )
            ):
                links_valid = False
                reasons.append(
                    "active shear-links force increment is malformed or inconsistent"
                )
    else:
        r_v = _optional_finite_result(
            shear_out.get("util") if isinstance(shear_out, Mapping) else None
        )
        if r_v is None:
            shear_valid = False
            reasons.append("shear utilisation is not finite")

    torsion_out = out.get("torsion")
    r_t = _optional_finite_result(
        torsion_out.get("util") if isinstance(torsion_out, Mapping) else None
    )
    torsion_valid = (
        isinstance(torsion_out, Mapping)
        and torsion_out.get("valid") is True
        and r_t is not None
    )
    torsion_asl = None
    torsion_asw_over_s = None
    torsion_t_ed = None
    torsion_subdivided = None
    if not isinstance(torsion_out, Mapping):
        reasons.append("torsion result is missing or malformed")
    else:
        if torsion_out.get("valid") is not True:
            reasons.append("torsion result is not valid")
        if r_t is None:
            reasons.append("torsion utilisation is not finite")
        torsion_asl = _optional_finite_result(torsion_out.get("asl_req"))
        torsion_asw_over_s = _optional_finite_result(
            torsion_out.get("asw_over_s")
        )
        torsion_t_ed = _optional_finite_result(torsion_out.get("t_ed"))
        torsion_subdivided = torsion_out.get("subdivided")
        if torsion_asl is None:
            torsion_valid = False
            reasons.append("torsion longitudinal reinforcement result is malformed")
        if torsion_asw_over_s is None:
            torsion_valid = False
            reasons.append("torsion stirrup result is malformed")
        if torsion_t_ed is None:
            torsion_valid = False
            reasons.append("torsion design action is missing or malformed")
        if type(torsion_subdivided) is not bool:
            torsion_valid = False
            reasons.append("torsion subdivision state is missing or malformed")
        if type(torsion_out.get("method")) is not str or torsion_out.get(
            "method"
        ) != method:
            torsion_valid = False
            reasons.append("torsion method is missing or inconsistent")

    if require_final_evidence:
        links = shear_out.get("links") if isinstance(shear_out, Mapping) else None
        primary = (
            torsion_out.get("primary")
            if isinstance(torsion_out, Mapping)
            else None
        )
        primary_t_ed = _optional_finite_result(
            primary.get("t_ed") if isinstance(primary, Mapping) else None
        )
        v_ed = _optional_finite_result(
            shear_out.get("v_ed") if isinstance(shear_out, Mapping) else None
        )
        shear_live = links_required and v_ed is not None and v_ed > 0.0
        top_level_torsion_live = (
            torsion_t_ed is not None and torsion_t_ed > 0.0
        )
        primary_torsion_live = primary_t_ed is not None and primary_t_ed > 0.0
        torsion_live = top_level_torsion_live or primary_torsion_live

        chord_candidates = (
            links.get("chord_candidates")
            if isinstance(links, Mapping)
            else None
        )
        chord_evidence = links_required and isinstance(links, Mapping) and (
            any(
                isinstance(links.get(key), Mapping)
                for key in (
                    "chord",
                    "chord_off",
                    "governing_longitudinal",
                    "longitudinal_fallback",
                )
            )
            or (
                isinstance(chord_candidates, (list, tuple))
                and bool(chord_candidates)
            )
        )

        if torsion_subdivided is False and isinstance(primary, Mapping):
            if (
                torsion_t_ed is None
                or primary_t_ed is None
                or not math.isclose(
                    torsion_t_ed,
                    primary_t_ed,
                    rel_tol=1.0e-12,
                    abs_tol=1.0e-12,
                )
            ):
                torsion_valid = False
                reasons.append(
                    "non-subdivided torsion primary action is inconsistent"
                )
        if primary_torsion_live and not top_level_torsion_live:
            torsion_valid = False
            reasons.append("torsion primary action exceeds the retained total")
        if (
            torsion_subdivided is True
            and primary_t_ed is not None
            and torsion_t_ed is not None
            and primary_t_ed > torsion_t_ed + 1.0e-12
        ):
            torsion_valid = False
            reasons.append("torsion primary action exceeds the retained total")

        if torsion_subdivided is False and (torsion_live or chord_evidence):
            primary_asl = _optional_finite_result(
                primary.get("asl_req")
                if isinstance(primary, Mapping)
                else None
            )
            if (
                torsion_asl is None
                or primary_asl is None
                or not math.isclose(
                    torsion_asl,
                    primary_asl,
                    rel_tol=1.0e-12,
                    abs_tol=1.0e-12,
                )
            ):
                torsion_valid = False
                reasons.append(
                    "non-subdivided torsion longitudinal force is inconsistent"
                )
        if shear_live or torsion_live:
            torsion_selection = (
                torsion_out.get("member_angle_selection")
                if isinstance(torsion_out, Mapping)
                else None
            )
            torsion_selection_cot = _combined_member_angle_selection_cot(
                torsion_selection
            )
            input_cot_a = _optional_positive_finite_result(
                inp.get("strut_cot_min")
            )
            input_cot_b = _optional_positive_finite_result(
                inp.get("strut_cot_max")
            )
            selection_cot_min = _optional_positive_finite_result(
                torsion_selection.get("cot_min")
                if isinstance(torsion_selection, Mapping)
                else None
            )
            selection_cot_max = _optional_positive_finite_result(
                torsion_selection.get("cot_max")
                if isinstance(torsion_selection, Mapping)
                else None
            )
            link_res = links.get("res") if isinstance(links, Mapping) else None
            link_cot = _optional_positive_finite_result(
                link_res.get("cot") if isinstance(link_res, Mapping) else None
            )
            primary_cot = _optional_positive_finite_result(
                primary.get("cot") if isinstance(primary, Mapping) else None
            )
            selections_match = bool(
                torsion_selection_cot is not None
                and input_cot_a is not None
                and input_cot_b is not None
                and selection_cot_min is not None
                and selection_cot_max is not None
                and math.isclose(
                    selection_cot_min,
                    min(input_cot_a, input_cot_b),
                    rel_tol=1.0e-12,
                    abs_tol=1.0e-12,
                )
                and math.isclose(
                    selection_cot_max,
                    max(input_cot_a, input_cot_b),
                    rel_tol=1.0e-12,
                    abs_tol=1.0e-12,
                )
            )
            if links_required:
                link_selection = (
                    links.get("member_angle_selection")
                    if isinstance(links, Mapping)
                    else None
                )
                link_selection_cot = _combined_member_angle_selection_cot(
                    link_selection
                )
                selections_match = bool(
                    selections_match
                    and link_selection_cot is not None
                    and isinstance(link_selection, Mapping)
                    and isinstance(torsion_selection, Mapping)
                    and dict(link_selection) == dict(torsion_selection)
                    and "DK NA governing interaction"
                    in tuple(torsion_selection.get("objective_labels", ()))
                )
            if shear_live:
                selections_match = bool(
                    selections_match
                    and link_cot is not None
                    and math.isclose(
                        torsion_selection_cot,
                        link_cot,
                        rel_tol=1.0e-12,
                        abs_tol=1.0e-12,
                    )
                )
            if torsion_live:
                selections_match = bool(
                    selections_match
                    and primary_t_ed is not None
                    and primary_t_ed > 0.0
                    and primary_cot is not None
                    and (
                        torsion_subdivided is True
                        or (
                            torsion_t_ed is not None
                            and math.isclose(
                                primary_t_ed,
                                torsion_t_ed,
                                rel_tol=1.0e-12,
                                abs_tol=1.0e-12,
                            )
                        )
                    )
                    and math.isclose(
                        torsion_selection_cot,
                        primary_cot,
                        rel_tol=1.0e-12,
                        abs_tol=1.0e-12,
                    )
                )
            selection_utilisation = _optional_finite_result(
                torsion_selection.get("utilisation")
                if isinstance(torsion_selection, Mapping)
                else None
            )
            if not selections_match or selection_utilisation is None:
                selections_match = False
            elif links_required:
                if r_m is None or r_v is None or r_t is None:
                    selections_match = False
                else:
                    dkna_utilisation = _module("combined").dkna_sum(
                        r_m,
                        r_v,
                        r_t,
                        m_v_independent=m_v_independent,
                    )
                    governing_labels = (
                        tuple(torsion_selection.get("governing_objectives", ()))
                        if isinstance(torsion_selection, Mapping)
                        else ()
                    )
                    runner_up_utilisation = _optional_finite_result(
                        torsion_selection.get("runner_up_utilisation")
                        if isinstance(torsion_selection, Mapping)
                        else None
                    )
                    dkna_governs = (
                        "DK NA governing interaction" in governing_labels
                    )
                    dkna_matches = math.isclose(
                        selection_utilisation,
                        dkna_utilisation,
                        rel_tol=1.0e-12,
                        abs_tol=1.0e-12,
                    )
                    if (
                        selection_utilisation + 1.0e-12 < dkna_utilisation
                        or (dkna_governs and not dkna_matches)
                        or (
                            not dkna_governs
                            and selection_utilisation == dkna_utilisation
                        )
                        or (
                            not dkna_governs
                            and (
                                runner_up_utilisation is None
                                or runner_up_utilisation < dkna_utilisation
                            )
                        )
                    ):
                        selections_match = False
            elif (
                r_t is None
                or not math.isclose(
                    selection_utilisation,
                    r_t,
                    rel_tol=1.0e-12,
                    abs_tol=1.0e-12,
                )
            ):
                selections_match = False
            if not selections_match:
                if links_required:
                    links_valid = False
                torsion_valid = False
                reasons.append(
                    "live common member-angle selection is missing or inconsistent"
                )

    if links_required and torsion_asw_over_s is not None and torsion_asw_over_s > 0.0:
        links = shear_out.get("links") if isinstance(shear_out, Mapping) else None
        link_res = links.get("res") if isinstance(links, Mapping) else None
        shear_res = shear_out.get("res") if isinstance(shear_out, Mapping) else None
        if (
            _optional_finite_result(
                shear_out.get("v_ed") if isinstance(shear_out, Mapping) else None
            )
            is None
            or _optional_finite_result(
                shear_res.get("vrd_c") if isinstance(shear_res, Mapping) else None
            )
            is None
        ):
            shear_valid = False
            reasons.append("shear transverse-interaction evidence is malformed")
        if (
            not isinstance(link_res, Mapping)
            or _optional_positive_finite_result(link_res.get("cot")) is None
            or any(
                _optional_finite_result(link_res.get(key)) is None
                for key in ("vrd_s", "vrd_max")
            )
        ):
            links_valid = False
            reasons.append("shear-links transverse-interaction evidence is malformed")
        primary = torsion_out.get("primary") if isinstance(torsion_out, Mapping) else None
        if not isinstance(primary, Mapping) or any(
            _optional_finite_result(primary.get(key)) is None
            for key in ("t_ed", "trd_s")
        ):
            torsion_valid = False
            reasons.append("torsion transverse-interaction evidence is malformed")

    if links_required and isinstance(torsion_out, Mapping):
        interaction = torsion_out.get("interaction", _MISSING)
        interaction_required = (
            torsion_asw_over_s is not None and torsion_asw_over_s > 0.0
        )
        if interaction is _MISSING or interaction is None:
            interaction_malformed = interaction_required
        else:
            links = shear_out.get("links") if isinstance(shear_out, Mapping) else None
            link_res = links.get("res") if isinstance(links, Mapping) else None
            primary = torsion_out.get("primary")
            interaction_values = {
                key: _optional_finite_result(interaction.get(key))
                if isinstance(interaction, Mapping)
                else None
                for key in ("theta_deg", "t_ed", "v_ed", "value")
            }
            interaction_cot = _optional_positive_finite_result(
                interaction.get("cot") if isinstance(interaction, Mapping) else None
            )
            interaction_trd_max = _optional_positive_finite_result(
                interaction.get("trd_max")
                if isinstance(interaction, Mapping)
                else None
            )
            interaction_vrd_max = _optional_positive_finite_result(
                interaction.get("vrd_max")
                if isinstance(interaction, Mapping)
                else None
            )
            source_values = {
                "v_ed": _optional_finite_result(
                    shear_out.get("v_ed")
                    if isinstance(shear_out, Mapping)
                    else None
                ),
                "cot": _optional_positive_finite_result(
                    link_res.get("cot") if isinstance(link_res, Mapping) else None
                ),
                "vrd_max": _optional_positive_finite_result(
                    link_res.get("vrd_max")
                    if isinstance(link_res, Mapping)
                    else None
                ),
                "t_ed": _optional_finite_result(
                    primary.get("t_ed") if isinstance(primary, Mapping) else None
                ),
                "primary_trd_max": _optional_positive_finite_result(
                    primary.get("trd_max") if isinstance(primary, Mapping) else None
                ),
                "primary_cot": _optional_positive_finite_result(
                    primary.get("cot") if isinstance(primary, Mapping) else None
                ),
            }
            operands_complete = (
                interaction_cot is not None
                and interaction_trd_max is not None
                and interaction_vrd_max is not None
                and all(value is not None for value in interaction_values.values())
                and all(
                    source_values[key] is not None
                    for key in ("v_ed", "cot", "vrd_max", "t_ed")
                )
            )
            operands_coherent = False
            if operands_complete:
                source_t_ed = source_values["t_ed"]
                source_v_ed = source_values["v_ed"]
                source_cot = source_values["cot"]
                source_vrd_max = source_values["vrd_max"]
                interaction_theta = interaction_values["theta_deg"]
                interaction_t_ed = interaction_values["t_ed"]
                interaction_v_ed = interaction_values["v_ed"]
                interaction_value = interaction_values["value"]
                assert (
                    source_t_ed is not None
                    and source_v_ed is not None
                    and source_cot is not None
                    and source_vrd_max is not None
                    and interaction_theta is not None
                    and interaction_t_ed is not None
                    and interaction_v_ed is not None
                    and interaction_value is not None
                    and interaction_cot is not None
                    and interaction_trd_max is not None
                    and interaction_vrd_max is not None
                )
                expected_value = (
                    source_t_ed / interaction_trd_max
                    + source_v_ed / interaction_vrd_max
                )
                torsion_live = source_t_ed > 0.0
                shear_live = source_v_ed > 0.0
                primary_angle_matches = not torsion_live or (
                    source_values["primary_trd_max"] is not None
                    and source_values["primary_cot"] is not None
                    and math.isclose(
                        interaction_trd_max,
                        source_values["primary_trd_max"],
                        rel_tol=1.0e-12,
                        abs_tol=1.0e-12,
                    )
                    and math.isclose(
                        interaction_cot,
                        source_values["primary_cot"],
                        rel_tol=1.0e-12,
                        abs_tol=1.0e-12,
                    )
                )
                shear_angle_matches = not shear_live or (
                    math.isclose(
                        interaction_cot,
                        source_cot,
                        rel_tol=1.0e-12,
                        abs_tol=1.0e-12,
                    )
                    and math.isclose(
                        interaction_vrd_max,
                        source_vrd_max,
                        rel_tol=1.0e-12,
                        abs_tol=1.0e-12,
                    )
                )
                operands_coherent = (
                    primary_angle_matches
                    and shear_angle_matches
                    and math.isclose(
                        interaction_t_ed,
                        source_t_ed,
                        rel_tol=1.0e-12,
                        abs_tol=1.0e-12,
                    )
                    and math.isclose(
                        interaction_v_ed,
                        source_v_ed,
                        rel_tol=1.0e-12,
                        abs_tol=1.0e-12,
                    )
                    and math.isclose(
                        interaction_theta,
                        math.degrees(math.atan2(1.0, interaction_cot)),
                        rel_tol=1.0e-12,
                        abs_tol=1.0e-12,
                    )
                    and math.isclose(
                        interaction_value,
                        expected_value,
                        rel_tol=1.0e-12,
                        abs_tol=1.0e-12,
                    )
                )
            interaction_malformed = (
                not isinstance(interaction, Mapping)
                or interaction.get("valid") is not True
                or not operands_coherent
            )
        if interaction_malformed:
            torsion_valid = False
            reasons.append("shared strut-interaction evidence is malformed")

    have_m = plastic_valid
    have_v = shear_valid and links_valid and r_v is not None
    have_t = torsion_valid
    valid = have_m and have_v and have_t
    return CombinedPrerequisiteAssessment(
        method=method,
        m_v_independent=m_v_independent,
        valid=valid,
        r_m=r_m,
        r_v=r_v,
        r_t=r_t,
        have_m=have_m,
        have_v=have_v,
        have_t=have_t,
        plastic_valid=plastic_valid,
        shear_valid=shear_valid,
        links_required=links_required,
        links_valid=links_valid,
        torsion_valid=torsion_valid,
        reasons=tuple(reasons),
    )


def evaluate_combined_prerequisites(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
) -> CombinedPrerequisiteAssessment:
    """Evaluate the fail-closed final prerequisite contract for combined M-V-T."""

    return _evaluate_combined_prerequisites(
        inp,
        out,
        require_final_evidence=True,
    )


def combined_angle_objective_r_m(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
) -> float | None:
    """Return validated bending utilisation for the pre-selection angle scan.

    The scan necessarily precedes retained member-angle evidence.  This narrow
    helper therefore exposes only a scalar and cannot issue a final certificate.
    """

    assessment = _evaluate_combined_prerequisites(
        inp,
        out,
        require_final_evidence=False,
    )
    return assessment.r_m if assessment.valid else None




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
    nu_t = tcode.torsion_nu(fck, closed_detailing=nu_detail)
    a_t = asw_over_s * fywd
    b_t = nu_t * alpha_cw * fcd * tube["tef"]
    shear = _module("shear")
    if a_t > 0.0:
        angle = shear.optimum_strut_angle(a_t, b_t, cot_min, cot_max)
        cot = angle.cot
        angle_selection = asdict(angle)
    else:
        cot = max(cot_min, 1.0)
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
        closed_detailing=nu_detail, fcd_mpa=fcd,
    )
    selection = torsion.select_torsion_resistance(
        steel.trd_s, strut.trd_max, asw_over_s=asw_over_s
    )
    cracking = torsion.trd_c_result(fctd, tube["Ak"], tube["tef"])
    util = t_ed / selection.resistance if selection.resistance > 0.0 else math.inf
    longitudinal = torsion.asl_required_result(
        t_ed, tube["uk"], tube["Ak"], fyd_long, cot
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
        "valid": tube["valid"],
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
    if not inp.get("shear_links"):
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


def build_directional_shear_contexts(inp, n_prestress, n_ed_comp):
    """Return every required face candidate for active Vx,Ed and Vy,Ed checks.

    The result maps ``vx``/``vy`` to a candidate list. No interaction between the
    two components is introduced here or elsewhere; each candidate remains a
    normal uniaxial shear calculation in its physical plane.
    """
    if not inp.get("shear_on"):
        return {}
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
    fywd = inp["shear_fywk"] / gamma_s
    fyd_long = design_yield(inp["steel"])
    asw = _module("templates").bar_area(inp["shear_link_dia"])
    asw_over_s = asw / inp["shear_link_s"] if inp["shear_link_s"] > 0.0 else 0.0
    cot_min = min(inp["strut_cot_min"], inp["strut_cot_max"])
    cot_max = max(inp["strut_cot_min"], inp["strut_cot_max"])
    nu_detail = inp["torsion_nu_v"]
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
