"""Solver-owned unpublished CT-006 directional shear trace."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .calculation_trace import (
    RESULT_FINITE, TraceBundle, TraceCalculation, TraceDependency, TraceResult,
    TraceStep, TraceValidationError, create_bundle, validate_bundle,
)
from .shear_trace_contract import (
    COVERAGE_ID, METHOD_ID, expected_registry, expected_step_contract,
)
from .shear_trace_replay import DirectionEvidence, replay_shear_evidence
from .trace_registry import audit_trace_registry


def _expression(step_id: str) -> str:
    suffixes = {
        "-v-basic": "v_basic = CRd,c k (100 rho_l fck)^(1/3) + k1 sigma_cp",
        "-v-floor": "v_floor = v_min + k1 sigma_cp",
        "-vrd-c": "VRd,c = governing concrete stress bw d",
        "-vrd-s": "VRd,s = (Asw/s) z fywd cot(theta)",
        "-vrd-max": "VRd,max = alpha_cw bw z nu1 fcd / (cot(theta) + 1/cot(theta))",
        "-vrd": "VRd = min(VRd,s, VRd,max)",
        "-concrete-utilisation": "u_c = abs(VEd) / VRd,c",
        "-linked-utilisation": "u_links = abs(VEd) / VRd",
        "-chord-off-util": "u_off = abs(Moff,Ed) / Moff,Rd",
        "-chord-biaxial": "biaxial = (u_off > 0.05)",
        "-chord-total-moment": "MEd,total = MEd + delta_Ftd z",
        "-chord-utilisation": "u_chord = MEd,total / MRd,conditional",
    }
    for suffix, expression in suffixes.items():
        if step_id.endswith(suffix):
            return expression
    if step_id.endswith("-cot"):
        return "argmin over 1501 inclusive band points of (max utilisations, sum utilisations, cot)"
    if step_id.endswith("-verdict"):
        return "PASS = 1 iff the reconstructed applicable utilisation <= 1 + 1e-9; otherwise FAIL = 0"
    if step_id.startswith("input-") or step_id.startswith("geometry-") or step_id.startswith("material-"):
        return "Read exact immutable original-input value"
    return "Evaluate the named retained CT-006 kernel from exactly the listed operands"


def _calculation(evidence: DirectionEvidence) -> TraceCalculation:
    specs = expected_step_contract(evidence.shape)
    units = {spec.step_id: spec.unit for spec in specs}
    steps = []
    for spec in specs:
        state = evidence.states.get(spec.step_id)
        result = state if state is not None else TraceResult(
            RESULT_FINITE, float(evidence.values[spec.step_id])
        )
        substituted = (
            result.reason if result.state != RESULT_FINITE
            else f"{spec.step_id} = {format(result.value, '.17g')} {spec.unit.symbol}"
        )
        steps.append(TraceStep(
            step_id=spec.step_id, title=spec.title,
            dependencies=tuple(TraceDependency(item, units[item]) for item in spec.dependencies),
            quantity_role=spec.quantity_role, source=spec.source,
            symbol=spec.step_id, unit=spec.unit,
            actual_expression=_expression(spec.step_id),
            substituted_expression=substituted, result=result,
        ))
    return TraceCalculation(
        calculation_id=evidence.shape.calculation_id,
        coverage_id=COVERAGE_ID,
        title=f"Directional shear {evidence.shape.component}",
        method_id=METHOD_ID,
        axes=evidence.shape.axes,
        final_step_id="direction-shear-verdict",
        steps=tuple(steps), warnings=evidence.warnings,
        assumptions=(
            "Vx and Vy are independent physical shear directions; no cross-direction interaction is inferred.",
            "The input shear sign is retained for audit and its absolute magnitude is the resistance demand.",
            "The longitudinal chord and 1501-point minimax selector are uncited Sector project methods.",
        ),
    )


def _expected_bundle(inp, out, input_sha256, result_sha256, context):
    replay = replay_shear_evidence(inp, out, context)
    bundle = create_bundle(
        input_sha256=input_sha256, result_sha256=result_sha256,
        calculations=tuple(_calculation(item) for item in replay.directions),
    )
    audit_trace_registry(bundle, expected_registry(tuple(item.shape for item in replay.directions)))
    return bundle


def build_shear_trace_family(
    inp: Mapping[str, Any], out: Mapping[str, Any], *,
    input_sha256: str, result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle:
    """Build and exact-registry audit the unpublished CT-006 families."""

    try:
        return _expected_bundle(
            inp, out, input_sha256, result_sha256,
            {} if context is None else context,
        )
    except TraceValidationError:
        raise
    except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"invalid CT-006 evidence: {exc}") from exc


def validate_shear_trace_family(
    bundle: TraceBundle | dict[str, Any],
    inp: Mapping[str, Any], out: Mapping[str, Any], *,
    input_sha256: str, result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle:
    """Reject resealed identity, graph, provenance, value, and verdict tampering."""

    candidate = validate_bundle(
        bundle, expected_input_sha256=input_sha256,
        expected_result_sha256=result_sha256,
    )
    expected = _expected_bundle(
        inp, out, input_sha256, result_sha256,
        {} if context is None else context,
    )
    replay = replay_shear_evidence(inp, out, {} if context is None else context)
    audit_trace_registry(candidate, expected_registry(tuple(item.shape for item in replay.directions)))
    if candidate.to_dict() != expected.to_dict():
        raise TraceValidationError("CT-006 trace differs from authoritative original-input replay")
    return candidate
