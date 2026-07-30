"""Attach and validate the PI-019 trace at the analysis/publication boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import case_analysis
import trace_coverage_registry
from sector import trace_builders
from sector.calculation_trace import (
    TraceBundle,
    TraceValidationError,
    create_bundle,
    fingerprint_payload,
    trace_identity_token,
    validate_bundle,
)
from sector.trace_registry import audit_trace_registry


TRACE_KEY = "calculation_trace"


def input_fingerprint(inp: Mapping[str, Any]) -> str:
    """Fingerprint the exact freshness signature used by the application."""

    if "signature" not in inp:
        raise TraceValidationError(
            "calculation traces require the current application input signature"
        )
    return fingerprint_payload(inp["signature"], omit_keys=())


def result_fingerprint(result: Mapping[str, Any]) -> str:
    """Fingerprint solver output while excluding its attached trace evidence."""

    return fingerprint_payload(result, omit_keys=(TRACE_KEY,))


def _context(
    family: str,
    case_id: Any,
    description: Any = "",
    *,
    named_case: bool = False,
) -> dict[str, str]:
    case_text = str(case_id)
    context = {
        "family": str(family),
        "case_id": case_text,
    }
    if named_case:
        # The readable slug is not injective (for example, ``A+B`` and ``A B``).
        # Carry the exact UTF-8 bytes as a private ID component so every valid
        # case name has a stable collision-free calculation namespace. Trace
        # builders omit private context keys from the published record.
        context["_case_identity"] = trace_identity_token(case_text)
    if str(description or "").strip():
        context["description"] = str(description).strip()
    return context


def _require_case_trace_coverage(
    inp: Mapping[str, Any],
    result: Mapping[str, Any],
    calculations: Sequence[Any],
    *,
    context: Mapping[str, Any] | None = None,
) -> None:
    """Audit one selected case through the declarative family registry."""

    selected_context = context or _context("direct", "direct")
    audit_trace_registry(
        calculations,
        scope_id=(
            "case:"
            + trace_identity_token(selected_context.get("case_id", "direct"))
        ),
        families=trace_coverage_registry.registered_families(
            trace_coverage_registry.CASE_CALCULATION_FAMILY_REGISTRY,
            inp=inp,
            result=result,
            context=selected_context,
        ),
    )


def _require_global_trace_coverage(
    inp: Mapping[str, Any],
    result: Mapping[str, Any],
    calculations: Sequence[Any],
) -> None:
    """Audit material/global traces through the same registry invariant."""

    audit_trace_registry(
        calculations,
        scope_id="global",
        families=trace_coverage_registry.registered_families(
            trace_coverage_registry.GLOBAL_CALCULATION_FAMILY_REGISTRY,
            inp=inp,
            result=result,
            context=_context("global", "global"),
        ),
    )


def build_bundle(inp: Mapping[str, Any], result: Mapping[str, Any]) -> TraceBundle:
    """Build one immutable trace bundle from current inputs and solver results."""

    material_calculations = trace_builders.material_calculations(
        inp,
        context=_context("global", "materials"),
    )
    calculations = list(material_calculations)

    named = "plastic_cases" in result or "elastic_cases" in result
    if named:
        for entry in result.get("plastic_cases") or ():
            if not isinstance(entry, Mapping):
                continue
            action = entry.get("actions")
            case_result = entry.get("results")
            if not isinstance(action, Mapping) or not isinstance(
                case_result,
                Mapping,
            ):
                continue
            case_inp = case_analysis.plastic_case_input(inp, action)
            case_context = _context(
                "plastic",
                entry.get("name") or action.get("name") or "case",
                entry.get("description"),
                named_case=True,
            )
            case_calculations = trace_builders.case_calculations(
                case_inp,
                case_result,
                context=case_context,
            )
            _require_case_trace_coverage(
                case_inp,
                case_result,
                case_calculations,
                context=case_context,
            )
            calculations.extend(case_calculations)
        for entry in result.get("elastic_cases") or ():
            if not isinstance(entry, Mapping):
                continue
            action = entry.get("actions")
            case_result = entry.get("results")
            if not isinstance(action, Mapping) or not isinstance(
                case_result,
                Mapping,
            ):
                continue
            case_inp = case_analysis.elastic_case_input(inp, action)
            case_context = _context(
                "elastic",
                entry.get("name") or action.get("name") or "case",
                entry.get("description"),
                named_case=True,
            )
            case_calculations = trace_builders.case_calculations(
                case_inp,
                case_result,
                context=case_context,
            )
            _require_case_trace_coverage(
                case_inp,
                case_result,
                case_calculations,
                context=case_context,
            )
            calculations.extend(case_calculations)
    else:
        direct_context = _context("direct", "direct")
        case_calculations = trace_builders.case_calculations(
            inp,
            result,
            context=direct_context,
        )
        _require_case_trace_coverage(
            inp,
            result,
            case_calculations,
            context=direct_context,
        )
        calculations.extend(case_calculations)

    global_calculations = trace_builders.global_calculations(
        inp,
        result,
        context=_context("global", "global"),
    )
    _require_global_trace_coverage(
        inp,
        result,
        (*material_calculations, *global_calculations),
    )
    calculations.extend(global_calculations)
    if not calculations:
        raise TraceValidationError(
            "the solver result contains no calculation that can be traced"
        )
    return create_bundle(
        input_sha256=input_fingerprint(inp),
        result_sha256=result_fingerprint(result),
        calculations=calculations,
    )


def attach_trace(
    inp: Mapping[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    """Attach current trace evidence when the current signature is available."""

    if not result or "signature" not in inp:
        return result
    try:
        bundle = build_bundle(inp, result)
    except TraceValidationError as exc:
        # An active supported calculation must never be silently published with
        # an incomplete trace. Invalid bridge/fatigue input errors are not
        # completed calculations and therefore do not require a bundle.
        completed = any(
            key in result
            for key in (
                "plastic",
                "elastic",
                "shear",
                "torsion",
                "combined",
                "minimum_reinforcement",
                "transverse_reinforcement",
                "clear_spacing",
                "plastic_cases",
                "elastic_cases",
            )
        )
        completed = completed or bool(
            (result.get("fatigue") or {}).get("spectra")
            if isinstance(result.get("fatigue"), Mapping)
            else False
        )
        completed = completed or bool(
            (result.get("bridge") or {}).get("calculations")
            if isinstance(result.get("bridge"), Mapping)
            else False
        )
        if completed:
            raise TraceValidationError(
                f"completed solver output cannot be published: {exc}"
            ) from exc
        return result
    result[TRACE_KEY] = bundle.to_dict()
    return result


def validated_bundle(
    inp: Mapping[str, Any],
    result: Mapping[str, Any],
) -> TraceBundle:
    """Return current, untampered trace evidence or fail closed."""

    payload = result.get(TRACE_KEY)
    if not isinstance(payload, Mapping):
        raise TraceValidationError(
            "current solver output has no calculation-trace bundle"
        )
    return validate_bundle(
        payload,
        expected_input_sha256=input_fingerprint(inp),
        expected_result_sha256=result_fingerprint(result),
    )
