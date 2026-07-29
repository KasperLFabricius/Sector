"""Typed Danish bridge choices for DS/EN 1992-2 DK NA:2015.

This module contains no UI or persistence code.  It resolves only the Danish
choices evidenced in ``docs/pr05_dk_bridge_decision_map.md`` and deliberately
keeps numerical admissibility separate from standards conformance.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import math
from typing import Any, Mapping

from . import conformance


METHODOLOGY = "DS/EN 1992-2:2005 + DK/NA:2015"
SOURCE = (
    "DS/EN 1992-2:2005 + EN 1992-2:2005/AC:2008 + "
    "DS/EN 1992-2 DK NA:2015"
)

NOT_ESTABLISHED = "Not established - review required"

ASSET_ROAD = "Road bridge"
ASSET_FOOT = "Footbridge"
ASSET_RAIL = "Railway bridge"
ASSET_OTHER = "Other / project-defined bridge"
ASSET_CLASSES = (
    NOT_ESTABLISHED,
    ASSET_ROAD,
    ASSET_FOOT,
    ASSET_RAIL,
    ASSET_OTHER,
)

MANAGER_ROAD_DIRECTORATE = "Danish Road Directorate"
MANAGER_LOCAL_ROAD = "Municipality / local road authority"
MANAGER_BANEDANMARK = "Banedanmark"
MANAGER_REGIONAL_RAIL = "Regional railway infrastructure manager"
MANAGER_OTHER = "Other / project-defined infrastructure manager"
INFRASTRUCTURE_MANAGERS = (
    NOT_ESTABLISHED,
    MANAGER_ROAD_DIRECTORATE,
    MANAGER_LOCAL_ROAD,
    MANAGER_BANEDANMARK,
    MANAGER_REGIONAL_RAIL,
    MANAGER_OTHER,
)

ENVIRONMENT_AGGRESSIVE = "Aggressive"
ENVIRONMENT_EXTRA_AGGRESSIVE = "Extra aggressive"
ENVIRONMENT_MODERATE = "Moderate (not used for bridges)"
ENVIRONMENT_OTHER = "Other / project-defined"
ENVIRONMENT_CLASSES = (
    NOT_ESTABLISHED,
    ENVIRONMENT_AGGRESSIVE,
    ENVIRONMENT_EXTRA_AGGRESSIVE,
    ENVIRONMENT_MODERATE,
    ENVIRONMENT_OTHER,
)

CONTROL_NORMAL = "Normal control"
CONTROL_STRICT = "Strict control"
CONTROL_MODIFIED = "Modified control (not permitted)"
CONTROL_NOT_APPLICABLE = "Not applicable"
CONTROL_CLASSES = (
    NOT_ESTABLISHED,
    CONTROL_NORMAL,
    CONTROL_STRICT,
    CONTROL_MODIFIED,
    CONTROL_NOT_APPLICABLE,
)

CONSEQUENCE_CC1 = "CC1"
CONSEQUENCE_CC2 = "CC2"
CONSEQUENCE_CC3 = "CC3"
CONSEQUENCE_OTHER = "Other / project-defined"
CONSEQUENCE_NOT_APPLICABLE = "Not applicable"
CONSEQUENCE_CLASSES = (
    NOT_ESTABLISHED,
    CONSEQUENCE_CC1,
    CONSEQUENCE_CC2,
    CONSEQUENCE_CC3,
    CONSEQUENCE_OTHER,
    CONSEQUENCE_NOT_APPLICABLE,
)

APPROVAL_APPROVED = "Approved"
APPROVAL_NOT_APPROVED = "Not approved"
APPROVAL_NOT_APPLICABLE = "Not applicable"
APPROVAL_STATES = (
    NOT_ESTABLISHED,
    APPROVAL_APPROVED,
    APPROVAL_NOT_APPROVED,
    APPROVAL_NOT_APPLICABLE,
)

APPLICABILITY_REQUIRED = "Required"
APPLICABILITY_NOT_APPLICABLE = "Not applicable"
APPLICABILITY_OPTIONS = (
    NOT_ESTABLISHED,
    APPLICABILITY_REQUIRED,
    APPLICABILITY_NOT_APPLICABLE,
)

FATIGUE_REQUIRED = APPLICABILITY_REQUIRED
FATIGUE_NOT_APPLICABLE = APPLICABILITY_NOT_APPLICABLE
FATIGUE_APPLICABILITY = APPLICABILITY_OPTIONS

SURFACE_WATERPROOFED = "Waterproofed bridge deck"
SURFACE_THIN_SYNTHETIC = "Thin synthetic wearing course"
SURFACE_DIRECT_DEICING = "Directly exposed to de-icing salts"
SURFACE_RAIL_EDGE = "Railway edge-beam surface"
SURFACE_OTHER = "Other / project-defined"
SURFACE_CONDITIONS = (
    NOT_ESTABLISHED,
    SURFACE_WATERPROOFED,
    SURFACE_THIN_SYNTHETIC,
    SURFACE_DIRECT_DEICING,
    SURFACE_RAIL_EDGE,
    SURFACE_OTHER,
)

COVER_NONPRESTRESSED = "Non-prestressed reinforcement"
COVER_PRETENSIONED = "Pretensioned reinforcement / unbundled tendons"
COVER_POSTTENSION_DUCT = "Post-tensioning duct"
COVER_CATEGORIES = (
    NOT_ESTABLISHED,
    COVER_NONPRESTRESSED,
    COVER_PRETENSIONED,
    COVER_POSTTENSION_DUCT,
)

MEMBER_NONPRESTRESSED = "Non-prestressed member"
MEMBER_PRESTRESSED = "Pre- or post-tensioned member"
MEMBER_CLASSES = (
    NOT_ESTABLISHED,
    MEMBER_NONPRESTRESSED,
    MEMBER_PRESTRESSED,
)

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_INVALID = "INVALID"
STATUS_NOT_ASSESSED = "NOT ASSESSED"
STATUS_NOT_APPLICABLE = "NOT APPLICABLE"
STATUS_REVIEW = "REVIEW"

ALPHA_METHOD = "Danish bridge concrete design coefficients"
ALPHA_SOURCE = "DS/EN 1992-2 DK NA:2015, 3.1.6, PDF page 2"
COVER_SOURCE = "DS/EN 1992-2 DK NA:2015, 4.4.1.2, PDF page 2"
STRENGTH_SOURCE = "DS/EN 1992-2 DK NA:2015, 3.1.2(102), PDF page 2"
AUTHORITY_SOURCE = (
    "DS/EN 1992-2 DK NA:2015, infrastructure-manager definition, PDF page 1"
)
ANNEX_SOURCE = "DS/EN 1992-2 DK NA:2015, Annex applicability, PDF page 5"


@dataclass(frozen=True)
class DanishBridgeBasis:
    """Immutable manager, project-basis, and Danish-choice input snapshot."""

    asset_class: str = NOT_ESTABLISHED
    infrastructure_manager: str = NOT_ESTABLISHED
    manager_source: str = ""
    project_basis_source: str = ""
    authority_approval_reference: str = ""
    traffic_fatigue_applicability: str = NOT_ESTABLISHED
    traffic_fatigue_model: str = ""
    traffic_fatigue_source: str = ""
    reinforcement_fatigue_applicability: str = NOT_ESTABLISHED
    concrete_fatigue_applicability: str = NOT_ESTABLISHED
    reinforcement_fatigue_on: Any = False
    concrete_fatigue_on: Any = False
    environment_class: str = NOT_ESTABLISHED
    environment_source: str = ""
    special_rules: str = ""
    departure_applicability: str = NOT_ESTABLISHED
    departure_source: str = ""
    deviations: str = ""
    control_class: str = NOT_ESTABLISHED
    control_source: str = ""
    consequence_class: str = NOT_ESTABLISHED
    consequence_source: str = ""
    high_strength_approval: str = NOT_ESTABLISHED
    high_strength_approval_reference: str = ""
    execution_conditions_source: str = ""
    surface_condition: str = NOT_ESTABLISHED
    deicing_applicability: str = NOT_ESTABLISHED
    deicing_source: str = ""
    cover_category: str = NOT_ESTABLISHED
    nominal_cover_mm: Any = None
    cover_source: str = ""
    collision_risk_applicability: str = NOT_ESTABLISHED
    alpha_cc: Any = None
    alpha_cc_basis: str = conformance.STANDARD_BASIS
    alpha_cc_custom_methodology: str = ""
    alpha_cc_approval_reference: str = ""
    alpha_ct: Any = 1.0
    alpha_ct_basis: str = conformance.STANDARD_BASIS
    alpha_ct_custom_methodology: str = ""
    alpha_ct_approval_reference: str = ""
    fatigue_on: Any = False
    fatigue_gamma3: Any = None
    torsion_on: Any = False
    torsion_gamma3: Any = None


def _typed_text(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be typed text")
    return value.strip()


def _typed_bool(value: Any, label: str) -> bool:
    if not conformance.is_boolean(value):
        raise ValueError(f"{label} must be Boolean")
    return bool(value)


def _positive(value: Any, label: str) -> float:
    return conformance.positive_real(value, label)


def _nonnegative(value: Any, label: str) -> float:
    if conformance.is_boolean(value) or isinstance(value, str):
        raise ValueError(f"{label} must be a finite real number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite real number") from exc
    if not math.isfinite(number) or number < 0.0:
        raise ValueError(f"{label} must be a finite non-negative number")
    return number


def basis_context(basis: DanishBridgeBasis) -> dict[str, Any]:
    """Return the strict JSON snapshot bound into a Danish bridge result."""

    if not isinstance(basis, DanishBridgeBasis):
        raise ValueError("Danish bridge basis must be typed evidence")
    raw = asdict(basis)
    output: dict[str, Any] = {}
    numeric_optional = {
        "nominal_cover_mm",
        "fatigue_gamma3",
        "torsion_gamma3",
    }
    numeric_positive = {"alpha_cc", "alpha_ct"}
    boolean_fields = {
        "fatigue_on",
        "torsion_on",
        "reinforcement_fatigue_on",
        "concrete_fatigue_on",
    }
    for key, value in raw.items():
        if key in boolean_fields:
            output[key] = _typed_bool(value, key)
        elif key in numeric_positive:
            output[key] = _positive(value, key)
        elif key in numeric_optional:
            if value is None:
                output[key] = None
            elif key == "nominal_cover_mm":
                output[key] = _nonnegative(value, key)
            else:
                output[key] = _positive(value, key)
        else:
            output[key] = _typed_text(value, key)
    return output


def basis_from_context(value: Mapping[str, Any]) -> DanishBridgeBasis:
    """Reconstruct typed basis evidence from an exact canonical snapshot."""

    if not isinstance(value, Mapping):
        raise ValueError("Danish bridge basis context must be an object")
    expected = {field.name for field in fields(DanishBridgeBasis)}
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unknown:
            details.append("unknown " + ", ".join(unknown))
        raise ValueError(
            "Danish bridge basis context fields are incomplete or unknown"
            + (": " + "; ".join(details) if details else "")
        )
    try:
        basis = DanishBridgeBasis(**dict(value))
        canonical = basis_context(basis)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Danish bridge basis context is invalid: {exc}") from exc
    if canonical != dict(value):
        raise ValueError("Danish bridge basis context is not canonical")
    return basis


def _result(
    status: str,
    *,
    result: str = "-",
    criterion: str = "-",
    source: str,
    reason: str,
    utilisation: float | None = None,
    evidence: tuple[Mapping[str, Any], ...] = (),
) -> dict[str, Any]:
    return {
        "status": status,
        "result": result,
        "criterion": criterion,
        "source": source,
        "reason": reason,
        "utilisation": utilisation,
        "evidence": [dict(row) for row in evidence],
    }


def manager_mapping(basis: DanishBridgeBasis) -> tuple[str, str]:
    """Return ``(state, reason)`` without inferring class from manager."""

    asset = basis.asset_class
    manager = basis.infrastructure_manager
    if asset not in ASSET_CLASSES or manager not in INFRASTRUCTURE_MANAGERS:
        return STATUS_INVALID, "Unknown asset-class or infrastructure-manager token."
    if asset == NOT_ESTABLISHED or manager == NOT_ESTABLISHED:
        return (
            STATUS_NOT_ASSESSED,
            "Select the bridge class and infrastructure manager explicitly.",
        )
    if asset == ASSET_OTHER or manager == MANAGER_OTHER:
        return (
            STATUS_REVIEW,
            "The project-defined manager/class has no mapped Sector calculation "
            "effect; retain it as qualified project-basis evidence.",
        )
    mapped = {
        MANAGER_ROAD_DIRECTORATE: {ASSET_ROAD, ASSET_FOOT},
        MANAGER_LOCAL_ROAD: {ASSET_ROAD, ASSET_FOOT},
        MANAGER_BANEDANMARK: {ASSET_RAIL},
        MANAGER_REGIONAL_RAIL: {ASSET_RAIL},
    }
    if asset not in mapped.get(manager, set()):
        return (
            STATUS_REVIEW,
            "The selected infrastructure manager and bridge class conflict; "
            "Sector will not transfer another manager's rules.",
        )
    return STATUS_PASS, "The independently selected manager and bridge class map."


def assess_project_basis(basis: DanishBridgeBasis) -> dict[str, Any]:
    """Assess authority mapping and the mandatory provenance fields."""

    try:
        snapshot = basis_context(basis)
    except ValueError as exc:
        return _result(
            STATUS_INVALID,
            source=AUTHORITY_SOURCE,
            reason=str(exc),
        )
    mapped_snapshot = dict(snapshot)
    state, mapping_reason = manager_mapping(basis)
    missing: list[str] = []
    if not basis.manager_source:
        missing.append("infrastructure-manager document/edition")
    if not basis.project_basis_source:
        missing.append("project design-basis source")
    if basis.environment_class == NOT_ESTABLISHED:
        missing.append("Danish environmental class")
    elif basis.environment_class not in ENVIRONMENT_CLASSES:
        return _result(
            STATUS_INVALID,
            source=AUTHORITY_SOURCE,
            reason="Unknown Danish environmental-class token.",
            evidence=(snapshot,),
        )
    elif not basis.environment_source:
        missing.append("Danish environmental-class source")
    if basis.surface_condition == NOT_ESTABLISHED:
        missing.append("bridge surface condition")
    elif basis.surface_condition not in SURFACE_CONDITIONS:
        return _result(
            STATUS_INVALID,
            source=AUTHORITY_SOURCE,
            reason="Unknown bridge surface-condition token.",
            evidence=(snapshot,),
        )
    if basis.deicing_applicability == NOT_ESTABLISHED:
        missing.append("de-icing-distance applicability")
    elif basis.deicing_applicability not in APPLICABILITY_OPTIONS:
        return _result(
            STATUS_INVALID,
            source=AUTHORITY_SOURCE,
            reason="Unknown de-icing applicability token.",
            evidence=(snapshot,),
        )
    elif basis.deicing_applicability == APPLICABILITY_REQUIRED:
        if not basis.deicing_source:
            missing.append("de-icing applicability source")
        try:
            x_distance, y_distance = deicing_distances(basis.asset_class)
        except ValueError:
            missing.append("road, footbridge, or railway class for de-icing")
        else:
            mapped_snapshot["mapped_deicing_x_m"] = x_distance
            mapped_snapshot["mapped_deicing_y_m"] = y_distance
    if (
        basis.surface_condition
        in {
            SURFACE_THIN_SYNTHETIC,
            SURFACE_DIRECT_DEICING,
            SURFACE_RAIL_EDGE,
        }
        and basis.environment_class != ENVIRONMENT_EXTRA_AGGRESSIVE
    ):
        state = STATUS_INVALID if state == STATUS_INVALID else STATUS_REVIEW
        mapping_reason += (
            " The selected surface requires the extra-aggressive Danish "
            "environmental route; Sector has not silently changed the selected "
            "class."
        )
    if (
        basis.surface_condition == SURFACE_RAIL_EDGE
        and basis.asset_class != ASSET_RAIL
    ):
        state = STATUS_INVALID if state == STATUS_INVALID else STATUS_REVIEW
        mapping_reason += (
            " The railway edge-beam surface conflicts with the selected bridge "
            "class."
        )
    if basis.surface_condition == SURFACE_OTHER:
        state = STATUS_INVALID if state == STATUS_INVALID else STATUS_REVIEW
        mapping_reason += (
            " The project-defined surface has no mapped Sector calculation effect."
        )
    if basis.control_class == NOT_ESTABLISHED:
        missing.append("construction/control class")
    elif basis.control_class not in CONTROL_CLASSES:
        return _result(
            STATUS_INVALID,
            source=AUTHORITY_SOURCE,
            reason="Unknown construction/control-class token.",
            evidence=(snapshot,),
        )
    elif basis.control_class != CONTROL_NOT_APPLICABLE and not basis.control_source:
        missing.append("construction/control-class source")
    if basis.consequence_class == NOT_ESTABLISHED:
        missing.append("consequence class")
    elif basis.consequence_class not in CONSEQUENCE_CLASSES:
        return _result(
            STATUS_INVALID,
            source=AUTHORITY_SOURCE,
            reason="Unknown consequence-class token.",
            evidence=(snapshot,),
        )
    elif (
        basis.consequence_class != CONSEQUENCE_NOT_APPLICABLE
        and not basis.consequence_source
    ):
        missing.append("consequence-class source")
    if basis.traffic_fatigue_applicability not in FATIGUE_APPLICABILITY:
        return _result(
            STATUS_INVALID,
            source=AUTHORITY_SOURCE,
            reason="Unknown traffic/fatigue applicability token.",
            evidence=(snapshot,),
        )
    fatigue_routes = (
        (
            "reinforcement fatigue",
            basis.reinforcement_fatigue_applicability,
            basis.reinforcement_fatigue_on,
        ),
        (
            "concrete fatigue",
            basis.concrete_fatigue_applicability,
            basis.concrete_fatigue_on,
        ),
    )
    for label, applicability, _enabled in fatigue_routes:
        if applicability not in FATIGUE_APPLICABILITY:
            return _result(
                STATUS_INVALID,
                source=AUTHORITY_SOURCE,
                reason=f"Unknown {label} applicability token.",
                evidence=(snapshot,),
            )
    if basis.traffic_fatigue_applicability == NOT_ESTABLISHED:
        missing.append("traffic/fatigue applicability")
    elif basis.traffic_fatigue_applicability == FATIGUE_REQUIRED:
        if not basis.traffic_fatigue_model:
            missing.append("traffic/fatigue model")
        if not basis.traffic_fatigue_source:
            missing.append("traffic/fatigue source")
        for label, applicability, _enabled in fatigue_routes:
            if applicability == NOT_ESTABLISHED:
                missing.append(f"{label} applicability")
        if not basis.fatigue_on:
            missing.append("enabled fatigue analysis")
        required_routes = [
            (label, enabled)
            for label, applicability, enabled in fatigue_routes
            if applicability == FATIGUE_REQUIRED
        ]
        if not required_routes:
            missing.append("at least one required calculated fatigue check")
        for label, enabled in required_routes:
            if not enabled:
                missing.append(f"enabled {label} calculation")
        for label, applicability, enabled in fatigue_routes:
            if applicability == FATIGUE_NOT_APPLICABLE and enabled:
                missing.append(
                    f"{label} calculation conflicts with Not applicable routing"
                )
    if basis.departure_applicability not in APPLICABILITY_OPTIONS:
        return _result(
            STATUS_INVALID,
            source=AUTHORITY_SOURCE,
            reason="Unknown departure / dispensation applicability token.",
            evidence=(snapshot,),
        )
    if basis.departure_applicability == NOT_ESTABLISHED:
        missing.append("departure / dispensation applicability")
    elif basis.departure_applicability == APPLICABILITY_REQUIRED:
        if not basis.deviations:
            missing.append("departure description / methodology")
        if not basis.departure_source:
            missing.append("departure source")
        if not basis.authority_approval_reference:
            missing.append("departure authority approval")
        state = STATUS_INVALID if state == STATUS_INVALID else STATUS_REVIEW
        mapping_reason += (
            " An explicitly applicable project departure is retained as an "
            "authority/project variation and cannot be relabelled as an "
            "unqualified Danish selected-standard PASS."
        )
    elif any(
        (
            basis.deviations,
            basis.departure_source,
            basis.authority_approval_reference,
        )
    ):
        state = STATUS_INVALID if state == STATUS_INVALID else STATUS_REVIEW
        mapping_reason += (
            " Departure applicability is explicitly Not applicable but "
            "departure text/source/approval is present; applicability is not "
            "inferred from free text."
        )
    if basis.control_class == CONTROL_MODIFIED:
        state = STATUS_INVALID if state == STATUS_INVALID else STATUS_REVIEW
        mapping_reason += " Modified control is not a Danish bridge option."

    factor_warnings: list[str] = []
    if (
        basis.infrastructure_manager == MANAGER_BANEDANMARK
        and basis.control_class in {CONTROL_NORMAL, CONTROL_STRICT}
    ):
        expected = 1.00 if basis.control_class == CONTROL_NORMAL else 0.95
        for active, actual, label in (
            (basis.fatigue_on, basis.fatigue_gamma3, "fatigue gamma3"),
            (basis.torsion_on, basis.torsion_gamma3, "torsion gamma3"),
        ):
            if not active:
                continue
            if actual is None:
                factor_warnings.append(f"{label} is missing")
            elif not math.isclose(float(actual), expected, rel_tol=0.0, abs_tol=1e-12):
                factor_warnings.append(
                    f"{label} = {float(actual):g}, expected {expected:g} for "
                    f"the explicitly selected {basis.control_class}"
                )
    if missing:
        return _result(
            STATUS_NOT_ASSESSED,
            result=f"{basis.infrastructure_manager} / {basis.asset_class}",
            criterion="Explicit mapped authority and complete project-basis provenance",
            source=AUTHORITY_SOURCE,
            reason=(
                mapping_reason
                + " Missing: "
                + ", ".join(missing)
                + "."
            ),
            evidence=(mapped_snapshot,),
        )
    if factor_warnings and state == STATUS_PASS:
        state = STATUS_REVIEW
    reason = mapping_reason
    if factor_warnings:
        reason += (
            " Actual positive factors remain calculation inputs; review "
            + "; ".join(factor_warnings)
            + "."
        )
    return _result(
        state,
        result=f"{basis.infrastructure_manager} / {basis.asset_class}",
        criterion="Explicit mapped authority and complete project-basis provenance",
        source=(
            f"{AUTHORITY_SOURCE}; manager source: {basis.manager_source}; "
            f"project basis: {basis.project_basis_source}"
        ),
        reason=reason,
        evidence=(mapped_snapshot,),
    )


def assess_high_strength(fck_mpa: Any, basis: DanishBridgeBasis) -> dict[str, Any]:
    """Assess the `fck > 50 MPa` approval and execution-condition trigger."""

    try:
        fck = _positive(fck_mpa, "Concrete fck")
    except ValueError as exc:
        return _result(STATUS_INVALID, source=STRENGTH_SOURCE, reason=str(exc))
    status = basis.high_strength_approval
    if status not in APPROVAL_STATES:
        return _result(
            STATUS_INVALID,
            source=STRENGTH_SOURCE,
            reason="Unknown high-strength approval token.",
        )
    evidence = ({
        "fck_mpa": fck,
        "approval_status": status,
        "approval_reference": basis.high_strength_approval_reference,
        "execution_conditions_source": basis.execution_conditions_source,
    },)
    if fck <= 50.0:
        return _result(
            STATUS_PASS,
            result=f"fck = {fck:g} MPa",
            criterion="Infrastructure-manager approval required only for fck > 50 MPa",
            source=STRENGTH_SOURCE,
            reason="The Danish high-strength approval trigger is not exceeded.",
            evidence=evidence,
        )
    complete = bool(
        status == APPROVAL_APPROVED
        and basis.high_strength_approval_reference
        and basis.execution_conditions_source
    )
    return _result(
        STATUS_PASS if complete else STATUS_REVIEW,
        result=f"fck = {fck:g} MPa",
        criterion=(
            "fck > 50 MPa requires infrastructure-manager approval and "
            "project-specific execution conditions"
        ),
        source=STRENGTH_SOURCE,
        reason=(
            "Approval and execution-condition evidence are complete."
            if complete
            else (
                "The actual concrete strength remains in the calculation, but "
                "the Danish approval/execution requirement is incomplete or "
                "not approved."
            )
        ),
        evidence=evidence,
    )


def assess_coefficients(basis: DanishBridgeBasis) -> dict[str, Any]:
    """Assess actual `alpha_cc` and `alpha_ct` against the Danish values."""

    records = []
    try:
        records.append(conformance.assess_parameter(
            basis.alpha_cc,
            parameter_id="dk_bridge.alpha_cc",
            label="Danish bridge alpha_cc",
            selected_standard=METHODOLOGY,
            standard_methodology=ALPHA_METHOD,
            normative_source=ALPHA_SOURCE,
            basis=basis.alpha_cc_basis,
            custom_methodology=basis.alpha_cc_custom_methodology,
            approval_reference=basis.alpha_cc_approval_reference,
            prescribed_value=1.0,
        ))
        records.append(conformance.assess_parameter(
            basis.alpha_ct,
            parameter_id="dk_bridge.alpha_ct",
            label="Danish bridge alpha_ct",
            selected_standard=METHODOLOGY,
            standard_methodology=ALPHA_METHOD,
            normative_source=ALPHA_SOURCE,
            basis=basis.alpha_ct_basis,
            custom_methodology=basis.alpha_ct_custom_methodology,
            approval_reference=basis.alpha_ct_approval_reference,
            prescribed_value=1.0,
        ))
    except ValueError as exc:
        return _result(STATUS_INVALID, source=ALPHA_SOURCE, reason=str(exc))
    aggregate = conformance.aggregate(
        records,
        analytical_status=STATUS_PASS,
        selected_standard=METHODOLOGY,
    )
    return _result(
        aggregate["assessment_status"],
        result=(
            f"alpha_cc = {records[0]['actual_value']:g}; "
            f"alpha_ct = {records[1]['actual_value']:g}"
        ),
        criterion="alpha_cc = 1.0 and alpha_ct = 1.0",
        source=ALPHA_SOURCE,
        reason="; ".join(aggregate["messages"]),
        evidence=tuple(records),
    )


def nominal_cover_requirement(
    *,
    environment_class: str,
    cover_category: str,
    control_class: str,
    collision_risk_applicability: str,
    asset_class: str,
) -> tuple[float, dict[str, Any]]:
    """Return the routed Danish nominal-cover minimum in millimetres."""

    if environment_class not in {
        ENVIRONMENT_AGGRESSIVE,
        ENVIRONMENT_EXTRA_AGGRESSIVE,
    }:
        raise ValueError(
            "Danish cover requires Aggressive or Extra aggressive environment"
        )
    if cover_category not in COVER_CATEGORIES[1:]:
        raise ValueError("Select the reinforcement/duct cover category")
    if control_class not in {CONTROL_NORMAL, CONTROL_STRICT}:
        raise ValueError(
            "Danish cover requires explicitly selected normal or strict control"
        )
    if collision_risk_applicability not in APPLICABILITY_OPTIONS:
        raise ValueError("Unknown collision-risk applicability token")
    extra = environment_class == ENVIRONMENT_EXTRA_AGGRESSIVE
    if cover_category == COVER_POSTTENSION_DUCT:
        cmin = 60.0 if extra else 50.0
    else:
        cmin = 50.0 if extra else 40.0
    delta = 5.0
    nominal = cmin + delta
    collision_applies = collision_risk_applicability == APPLICABILITY_REQUIRED
    if collision_applies:
        if (
            asset_class != ASSET_RAIL
            or cover_category
            not in {COVER_PRETENSIONED, COVER_POSTTENSION_DUCT}
        ):
            raise ValueError(
                "The 75 mm collision-risk route requires an explicitly selected "
                "railway prestressing category"
            )
        nominal = max(nominal, 75.0)
    return nominal, {
        "environment_class": environment_class,
        "cover_category": cover_category,
        "control_class": control_class,
        "cmin_dur_mm": cmin,
        "delta_cdev_mm": delta,
        "collision_risk_applicability": collision_risk_applicability,
        "collision_minimum_mm": 75.0 if collision_applies else None,
        "required_nominal_cover_mm": nominal,
    }


def assess_cover(basis: DanishBridgeBasis) -> dict[str, Any]:
    """Compare the actual cover evidence with the exact routed Danish minimum."""

    if basis.cover_category == NOT_ESTABLISHED:
        return _result(
            STATUS_NOT_ASSESSED,
            source=COVER_SOURCE,
            reason="Select the Danish reinforcement/duct cover category.",
        )
    if (
        basis.asset_class == ASSET_RAIL
        and basis.cover_category in {
            COVER_PRETENSIONED,
            COVER_POSTTENSION_DUCT,
        }
        and basis.collision_risk_applicability == NOT_ESTABLISHED
    ):
        return _result(
            STATUS_NOT_ASSESSED,
            source=COVER_SOURCE,
            reason=(
                "Establish whether the Danish 75 mm railway collision-risk "
                "prestressing route applies."
            ),
        )
    try:
        required, route = nominal_cover_requirement(
            environment_class=basis.environment_class,
            cover_category=basis.cover_category,
            control_class=basis.control_class,
            collision_risk_applicability=basis.collision_risk_applicability,
            asset_class=basis.asset_class,
        )
    except ValueError as exc:
        return _result(STATUS_NOT_ASSESSED, source=COVER_SOURCE, reason=str(exc))
    if basis.nominal_cover_mm is None:
        return _result(
            STATUS_NOT_ASSESSED,
            criterion=f"cnom >= {required:g} mm",
            source=COVER_SOURCE,
            reason="Actual nominal-cover evidence is missing.",
            evidence=(route,),
        )
    try:
        actual = _nonnegative(basis.nominal_cover_mm, "Nominal cover")
    except ValueError as exc:
        return _result(STATUS_INVALID, source=COVER_SOURCE, reason=str(exc))
    if not basis.cover_source:
        return _result(
            STATUS_NOT_ASSESSED,
            result=f"cnom = {actual:g} mm",
            criterion=f"cnom >= {required:g} mm",
            source=COVER_SOURCE,
            reason="Nominal-cover evidence requires a model/drawing source.",
            evidence=(route,),
        )
    passed = actual >= required
    utilisation = required / actual if actual > 0.0 else None
    return _result(
        STATUS_PASS if passed else STATUS_FAIL,
        result=f"cnom = {actual:g} mm",
        criterion=f"cnom >= {required:g} mm",
        source=f"{COVER_SOURCE}; evidence source: {basis.cover_source}",
        reason=(
            "Actual cover satisfies the routed Danish minimum."
            if passed
            else "Actual cover is below the routed Danish minimum."
        ),
        utilisation=utilisation,
        evidence=({
            **route,
            "actual_nominal_cover_mm": actual,
            "status": STATUS_PASS if passed else STATUS_FAIL,
        },),
    )


def deicing_distances(asset_class: str) -> tuple[float, float]:
    """Return the Danish `x, y` de-icing extents for an explicit bridge class."""

    if asset_class in {ASSET_ROAD, ASSET_FOOT}:
        return 3.0, 3.0
    if asset_class == ASSET_RAIL:
        return 5.0, 3.0
    raise ValueError("De-icing distances require road, footbridge, or railway class")


def annex_routing() -> tuple[dict[str, str], ...]:
    """Return the immutable DK NA:2015 annex applicability table."""

    return tuple(
        {"annex": annex, "national_status": status}
        for annex, status in (
            ("A", "Not applicable"),
            ("B", "Informative"),
            ("E", "Replaced"),
            ("F", "Not applicable / replaced"),
            ("G", "Not applicable"),
            ("H", "Not applicable"),
            ("I", "Not applicable"),
            ("J", "Applicable"),
            ("KK", "Applicable"),
            ("LL", "Not applicable"),
            ("MM", "Not applicable"),
            ("NN", "Applicable"),
            ("OO", "Applicable"),
            ("PP", "Not applicable"),
            ("QQ", "Not applicable"),
        )
    )
