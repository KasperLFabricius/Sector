"""Canonical separation of numerical validity and standards conformance.

Sector is an analysis tool.  A finite, mathematically usable value can be used
by a solver even when it is not a prescribed value, or lies outside the
applicability range, of the selected standard.  This module owns the immutable
evidence that makes that distinction explicit.

Callers must validate structural inputs independently.  The helpers here reject
only malformed metadata and numerically unusable parameter values; a standards
deviation is returned as evidence, never as a replacement value.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence


SCHEMA = "sector.parameter-conformance/v1"

STANDARD_BASIS = "Selected-standard prescription"
CUSTOM_BASIS = "Custom design basis"
BASIS_OPTIONS = (STANDARD_BASIS, CUSTOM_BASIS)

STATE_CONFORMS = "CONFORMS"
STATE_APPROVED_CUSTOM = "APPROVED CUSTOM"
STATE_REVIEW = "REVIEW REQUIRED"
STATES = (STATE_CONFORMS, STATE_APPROVED_CUSTOM, STATE_REVIEW)

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_REVIEW = "REVIEW"

_TOL = 1.0e-12


def is_boolean(value: Any) -> bool:
    """Return ``True`` for Python and NumPy Boolean scalars."""

    value_type = type(value)
    return isinstance(value, bool) or (
        value_type.__name__ in {"bool", "bool_"}
        and value_type.__module__.split(".", 1)[0] in {"numpy", "pandas"}
    )


def positive_real(value: Any, label: str) -> float:
    """Return a positive finite real without accepting Boolean/string coercion."""

    if is_boolean(value) or isinstance(value, str):
        raise ValueError(f"{label} must be a finite real number greater than zero")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{label} must be a finite real number greater than zero"
        ) from exc
    if not math.isfinite(number) or number <= 0.0:
        raise ValueError(f"{label} must be a finite real number greater than zero")
    return number


def _typed_text(value: Any, label: str, *, required: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be typed text")
    text = value.strip()
    if required and not text:
        raise ValueError(f"{label} is required")
    return text


def typed_text(value: Any, label: str, *, required: bool = False) -> str:
    """Return stripped typed text without coercing malformed metadata."""

    if value is None and not required:
        value = ""
    return _typed_text(value, label, required=required)


def _normative_requirement(
    *,
    prescribed_value: float | None,
    minimum: float | None,
    maximum: float | None,
) -> tuple[str, bool]:
    exact = prescribed_value is not None
    ranged = minimum is not None or maximum is not None
    if exact == ranged:
        raise ValueError(
            "parameter conformance requires exactly one prescribed value or range"
        )
    if exact:
        prescribed = positive_real(prescribed_value, "prescribed value")
        return f"prescribed value = {prescribed:g}", True
    if minimum is None or maximum is None:
        raise ValueError("parameter conformance range requires both bounds")
    lower = positive_real(minimum, "normative minimum")
    upper = positive_real(maximum, "normative maximum")
    if lower > upper:
        raise ValueError("parameter conformance range is reversed")
    return f"{lower:g} <= value <= {upper:g}", False


def assess_parameter(
    value: Any,
    *,
    parameter_id: str,
    label: str,
    selected_standard: str,
    standard_methodology: str,
    normative_source: str,
    basis: str = STANDARD_BASIS,
    custom_methodology: str = "",
    approval_reference: str = "",
    prescribed_value: float | None = None,
    minimum: float | None = None,
    maximum: float | None = None,
    applicability_conforms: bool = True,
    applicability_note: str = "",
) -> dict[str, Any]:
    """Return immutable, JSON-safe conformance evidence for one value.

    The actual value is returned unchanged as a float.  Deviations and missing
    or contradictory approvals produce ``REVIEW REQUIRED`` rather than a
    numerical error.
    """

    actual = positive_real(value, label)
    parameter = _typed_text(parameter_id, "parameter ID", required=True)
    display_label = _typed_text(label, "parameter label", required=True)
    standard = _typed_text(
        selected_standard,
        "selected standard",
        required=True,
    )
    standard_method = _typed_text(
        standard_methodology,
        "standard methodology",
        required=True,
    )
    source = _typed_text(normative_source, "normative source", required=True)
    basis_value = _typed_text(basis, "parameter basis", required=True)
    if basis_value not in BASIS_OPTIONS:
        raise ValueError(f"unknown parameter basis: {basis_value}")
    custom_method = _typed_text(custom_methodology, "custom methodology")
    approval = _typed_text(approval_reference, "approval reference")
    if not isinstance(applicability_conforms, bool):
        raise ValueError("applicability conformance must be Boolean")
    applicability = _typed_text(
        applicability_note,
        "applicability note",
    )
    requirement, exact = _normative_requirement(
        prescribed_value=prescribed_value,
        minimum=minimum,
        maximum=maximum,
    )

    if exact:
        prescribed = float(prescribed_value)
        within = math.isclose(
            actual,
            prescribed,
            rel_tol=0.0,
            abs_tol=_TOL,
        )
        normative = {
            "kind": "prescribed",
            "prescribed_value": prescribed,
            "minimum": None,
            "maximum": None,
        }
    else:
        lower = float(minimum)
        upper = float(maximum)
        # Applicability bounds are closed mathematical domains.  Even the
        # immediately adjacent representable value must remain a visible
        # deviation rather than being absorbed by a calculation tolerance.
        within = lower <= actual <= upper
        normative = {
            "kind": "range",
            "prescribed_value": None,
            "minimum": lower,
            "maximum": upper,
        }
    prescription_conforms = bool(within)
    standard_conforms = bool(
        prescription_conforms and applicability_conforms
    )

    contradictory_standard_metadata = bool(
        basis_value == STANDARD_BASIS
        and (custom_method or approval)
    )
    custom_complete = bool(custom_method and approval)
    if (
        basis_value == STANDARD_BASIS
        and standard_conforms
        and not contradictory_standard_metadata
    ):
        state = STATE_CONFORMS
        message = (
            f"{display_label} conforms to the selected-standard "
            f"{requirement}."
        )
    elif basis_value == CUSTOM_BASIS and custom_complete:
        state = STATE_APPROVED_CUSTOM
        custom_notes = []
        if not prescription_conforms:
            custom_notes.append(
                f"actual value {actual:g} deviates from {requirement}"
            )
        if not applicability_conforms:
            custom_notes.append(
                applicability or "standard applicability is not met"
            )
        message = (
            f"{display_label} is calculated as approved custom input "
            f"({custom_method}; approval/source: {approval})"
            + (
                "; selected-standard deviation: "
                + "; ".join(dict.fromkeys(custom_notes))
                if custom_notes
                else ""
            )
            + "."
        )
    else:
        state = STATE_REVIEW
        reasons = []
        if not prescription_conforms:
            reasons.append(
                f"actual value {actual:g} does not conform to {requirement}"
            )
        if not applicability_conforms:
            reasons.append(applicability or "standard applicability is not met")
        if contradictory_standard_metadata:
            reasons.append(
                "standard basis conflicts with custom methodology/approval metadata"
            )
        if basis_value == CUSTOM_BASIS and not custom_method:
            reasons.append("custom methodology is missing")
        if basis_value == CUSTOM_BASIS and not approval:
            reasons.append("custom approval/source is missing")
        if not reasons:
            reasons.append("the selected basis is not fully established")
        message = f"{display_label}: " + "; ".join(dict.fromkeys(reasons)) + "."

    return {
        "schema": SCHEMA,
        "parameter_id": parameter,
        "label": display_label,
        "actual_value": actual,
        "selected_standard": standard,
        "standard_methodology": standard_method,
        "normative_source": source,
        "normative_requirement": requirement,
        **normative,
        "basis": basis_value,
        "custom_methodology": custom_method,
        "approval_reference": approval,
        "applicability_conforms": applicability_conforms,
        "applicability_note": applicability,
        "state": state,
        "value_deviation": not prescription_conforms,
        "deviation": not standard_conforms,
        "message": message,
    }


def verify_parameter(
    record: Mapping[str, Any],
    *,
    value: Any,
    parameter_id: str,
    label: str,
    selected_standard: str,
    standard_methodology: str,
    normative_source: str,
    prescribed_value: float | None = None,
    minimum: float | None = None,
    maximum: float | None = None,
    applicability_conforms: bool = True,
    applicability_note: str = "",
) -> tuple[dict[str, Any] | None, tuple[str, ...]]:
    """Recompute and compare a stored parameter record at publication."""

    if not isinstance(record, Mapping):
        return None, (f"{label} conformance evidence is missing or malformed",)
    try:
        expected = assess_parameter(
            value,
            parameter_id=parameter_id,
            label=label,
            selected_standard=selected_standard,
            standard_methodology=standard_methodology,
            normative_source=normative_source,
            basis=record.get("basis"),
            custom_methodology=record.get("custom_methodology"),
            approval_reference=record.get("approval_reference"),
            prescribed_value=prescribed_value,
            minimum=minimum,
            maximum=maximum,
            applicability_conforms=applicability_conforms,
            applicability_note=applicability_note,
        )
    except (TypeError, ValueError) as exc:
        return None, (str(exc),)
    if dict(record) != expected:
        return expected, (
            f"{label} conformance evidence is stale, incomplete, or contradictory",
        )
    return expected, ()


def verify_self_contained(
    record: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, tuple[str, ...]]:
    """Recompute a record using the normative metadata carried inside it."""

    if not isinstance(record, Mapping):
        return None, ("parameter conformance evidence is malformed",)
    kind = record.get("kind")
    common = {
        "value": record.get("actual_value"),
        "parameter_id": record.get("parameter_id"),
        "label": record.get("label"),
        "selected_standard": record.get("selected_standard"),
        "standard_methodology": record.get("standard_methodology"),
        "normative_source": record.get("normative_source"),
        "basis": record.get("basis"),
        "custom_methodology": record.get("custom_methodology"),
        "approval_reference": record.get("approval_reference"),
        "applicability_conforms": record.get("applicability_conforms"),
        "applicability_note": record.get("applicability_note"),
    }
    if kind == "prescribed":
        common["prescribed_value"] = record.get("prescribed_value")
    elif kind == "range":
        common["minimum"] = record.get("minimum")
        common["maximum"] = record.get("maximum")
    else:
        return None, ("parameter conformance normative kind is unknown",)
    try:
        expected = assess_parameter(**common)
    except (TypeError, ValueError) as exc:
        return None, (str(exc),)
    if dict(record) != expected:
        return expected, (
            "parameter conformance evidence is stale, incomplete, or contradictory",
        )
    return expected, ()


def aggregate(
    records: Sequence[Mapping[str, Any]],
    *,
    analytical_status: str,
    selected_standard: str,
) -> dict[str, Any]:
    """Return the qualified verdict for a set of conformance records."""

    if not isinstance(records, (list, tuple)) or not records:
        raise ValueError("parameter conformance records are required")
    analytical = _typed_text(
        analytical_status,
        "analytical status",
        required=True,
    ).upper()
    if analytical not in {STATUS_PASS, STATUS_FAIL}:
        raise ValueError("analytical status must be PASS or FAIL")
    standard = _typed_text(
        selected_standard,
        "selected standard",
        required=True,
    )
    states = []
    for index, record in enumerate(records, start=1):
        if not isinstance(record, Mapping):
            raise ValueError(
                f"parameter conformance record {index} is not an object"
            )
        if record.get("schema") != SCHEMA or record.get("state") not in STATES:
            raise ValueError(
                f"parameter conformance record {index} is malformed"
            )
        if record.get("selected_standard") != standard:
            raise ValueError(
                f"parameter conformance record {index} is bound to another "
                "selected standard"
            )
        states.append(record["state"])
    if STATE_REVIEW in states:
        state = STATE_REVIEW
    elif STATE_APPROVED_CUSTOM in states:
        state = STATE_APPROVED_CUSTOM
    else:
        state = STATE_CONFORMS

    if state == STATE_CONFORMS:
        assessment_status = analytical
        qualified = f"STANDARD {analytical}"
        standard_verdict = analytical
    elif state == STATE_APPROVED_CUSTOM:
        assessment_status = STATUS_REVIEW
        qualified = f"APPROVED CUSTOM {analytical}"
        standard_verdict = "NOT FULLY ASSESSED"
    else:
        assessment_status = STATUS_REVIEW
        qualified = f"REVIEW - analytical {analytical}"
        standard_verdict = "NOT FULLY ASSESSED"
    return {
        "schema": SCHEMA,
        "selected_standard": standard,
        "state": state,
        "analytical_status": analytical,
        "assessment_status": assessment_status,
        "qualified_verdict": qualified,
        "standard_verdict": standard_verdict,
        "messages": tuple(
            str(record.get("message") or "")
            for record in records
            if str(record.get("message") or "")
        ),
    }
