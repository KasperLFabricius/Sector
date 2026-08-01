"""Solver-owned unpublished CT-006 directional-shear trace."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .calculation_trace import (
    RESULT_FINITE,
    TraceBundle,
    TraceCalculation,
    TraceDependency,
    TraceResult,
    TraceStep,
    TraceValidationError,
    create_bundle,
    validate_bundle,
)
from .shear_trace_contract import COVERAGE_ID, expected_registry, expected_step_contract
from .shear_trace_replay import ReplayEvidence, replay_shear_evidence
from .trace_registry import audit_trace_registry


def _format(value: float) -> str:
    return format(float(value), ".17g")


def _actual_expression(step_id: str) -> str:
    if step_id.startswith(("geometry-", "input-")):
        return "Original immutable solver input"
    if step_id.startswith("material-"):
        return "Exact assigned solver-law value"
    if step_id == "normalised-shear-inputs":
        return "One shared geometry/action/material/provenance vector"
    if step_id.startswith("method-"):
        return "Selected retained method rule"
    if step_id.endswith("-concrete-vmin"):
        return "v_min from the selected base or DK method rule"
    if step_id.endswith("-concrete-v-basic"):
        return "v_basic = C_Rd,c k (100 rho_l f_ck)^(1/3) + k1 sigma_cp"
    if step_id.endswith("-concrete-v-floor"):
        return "v_floor = v_min + k1 sigma_cp"
    if step_id.endswith("-concrete-tau-rdc"):
        return "tau_Rd,c = max(tau_basic, tau_min)"
    if step_id.endswith("-concrete-vrd-c"):
        return "V_Rd,c from the retained edition-specific concrete shear kernel"
    if step_id.endswith("-concrete-util"):
        return "u_c = |V_Ed| / V_Rd,c"
    if step_id.endswith("-link-result-cot"):
        return "cot(theta) = retained 1501-point minimax selector from original objectives"
    if step_id.endswith("-link-result-nu1") or step_id.endswith("-link-result-nu"):
        return "Compression-strut factor from the selected base, DK, or 2023 rule"
    if step_id.endswith("-link-result-vrd-s"):
        return "V_Rd,s from the retained linked-shear kernel at replayed cot(theta)"
    if step_id.endswith("-link-result-vrd-max"):
        return "V_Rd,max from the retained strut kernel at replayed cot(theta)"
    if step_id.endswith("-link-result-vrd"):
        return "V_Rd = min(V_Rd,s, V_Rd,max)"
    if step_id.endswith("-link-util"):
        return "u_links = |V_Ed| / V_Rd"
    if step_id.endswith("-shear-metric"):
        return "Applicable face metric = linked utilisation when links are enabled, otherwise concrete utilisation"
    if step_id.endswith(("-shear-status", "-aggregate-status")):
        return "PASS when applicable finite utilisation <= 1 + 1e-9, otherwise FAIL"
    if step_id.endswith("-governing-face"):
        return "Conservative retained face selector over every mandatory face"
    if step_id == "authoritative-shear-failure":
        return "Original-input mechanics selected the explicit failed branch"
    if step_id == "ct-006-directional-shear-result":
        return "Complete CT-006 result state from all mandatory direction chains"
    return "Bind retained CT-006 intermediate"


def _calculation(evidence: ReplayEvidence) -> TraceCalculation:
    specs = expected_step_contract(evidence.shape)
    units = {spec.step_id: spec.unit for spec in specs}
    steps = []
    for spec in specs:
        result = evidence.states.get(spec.step_id)
        if result is None:
            if spec.step_id not in evidence.values:
                raise TraceValidationError(f"internal CT-006 value omitted {spec.step_id}")
            value = evidence.values[spec.step_id]
            result = TraceResult(RESULT_FINITE, float(value))
            substituted = f"{spec.step_id} = {_format(value)} {spec.unit.symbol}"
        else:
            substituted = f"{spec.step_id} = {result.state}"
        assumptions = ()
        if spec.step_id == "ct-006-directional-shear-result":
            assumptions = (
                "Vx and Vy are independent directional checks; no generic cross-direction utilisation or verdict is inferred.",
            )
        steps.append(TraceStep(
            step_id=spec.step_id,
            title=spec.title,
            dependencies=tuple(
                TraceDependency(dependency, units[dependency])
                for dependency in spec.dependencies
            ),
            quantity_role=spec.quantity_role,
            source=spec.source,
            symbol=spec.step_id,
            unit=spec.unit,
            actual_expression=_actual_expression(spec.step_id),
            substituted_expression=substituted,
            result=result,
            assumptions=assumptions,
        ))
    return TraceCalculation(
        calculation_id=evidence.shape.calculation_id,
        coverage_id=COVERAGE_ID,
        title="Directional shear",
        method_id=evidence.shape.method_id,
        axes=evidence.shape.axes,
        final_step_id="ct-006-directional-shear-result",
        steps=tuple(steps),
        warnings=evidence.warnings,
        assumptions=(
            "User normal force is tension-positive; retained shear mechanics use compression-positive NEd after the single solver-boundary conversion.",
            "Signed Vx/Vy actions retain their sign identity while each independent resistance check uses the demand magnitude.",
            "Sector geometry selection, face selection, minimax cot selection, and aggregation are uncited project methods.",
        ),
    )


def _expected_bundle(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any] | None,
) -> tuple[TraceBundle, ReplayEvidence]:
    evidence = replay_shear_evidence(inp, out, {} if context is None else context)
    bundle = create_bundle(
        input_sha256=input_sha256,
        result_sha256=result_sha256,
        calculations=(_calculation(evidence),),
    )
    audit_trace_registry(bundle, expected_registry(evidence.shape))
    return bundle, evidence


def build_shear_trace_family(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle:
    """Build, seal, and exact-registry audit one CT-006 family."""

    try:
        return _expected_bundle(
            inp,
            out,
            input_sha256=input_sha256,
            result_sha256=result_sha256,
            context=context,
        )[0]
    except TraceValidationError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"invalid CT-006 evidence: {exc}") from exc


def validate_shear_trace_family(
    bundle: TraceBundle | dict[str, Any],
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle:
    """Reject graph, source, and coherently resealed numerical tampering."""

    candidate = validate_bundle(
        bundle,
        expected_input_sha256=input_sha256,
        expected_result_sha256=result_sha256,
    )
    expected, evidence = _expected_bundle(
        inp,
        out,
        input_sha256=input_sha256,
        result_sha256=result_sha256,
        context=context,
    )
    audit_trace_registry(candidate, expected_registry(evidence.shape))
    if candidate.to_dict() != expected.to_dict():
        raise TraceValidationError("CT-006 trace differs from authoritative input replay")
    return candidate
