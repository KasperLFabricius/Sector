"""Build and validate unpublished solver-owned CT-006 trace families."""

from __future__ import annotations

from typing import Any, Mapping

from .calculation_trace import (
    TraceBundle, TraceCalculation, TraceDependency, TraceStep,
    TraceValidationError, create_bundle, validate_bundle,
)
from .shear_trace_contract import (
    BRANCH_FAILED, COVERAGE_ID, expected_registry, expected_step_contract,
    method_id,
)
from .shear_trace_replay import (
    DirectionEvidence, replay_shear_evidence, trace_result, trace_values,
)
from .trace_registry import audit_trace_registry


def _calculation(evidence: DirectionEvidence, inp: Mapping[str, Any]) -> TraceCalculation:
    shape = evidence.shape
    specs = expected_step_contract(shape)
    values = trace_values(evidence, inp)
    units = {spec.step_id: spec.unit for spec in specs}
    failed = shape.branch == BRANCH_FAILED
    steps = []
    for spec in specs:
        value = values.get(spec.step_id)
        warning = (
            ("Authoritative CT-006 mechanics failed; no numerical result is published.",)
            if failed and spec.step_id == "ct-006-direction-result"
            else ()
        )
        steps.append(
            TraceStep(
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
                actual_expression=f"authoritative {spec.title.lower()}",
                substituted_expression=(
                    f"{spec.title} = " + ("failed" if value is None else repr(value))
                ),
                result=trace_result(shape, spec.step_id, value),
                warnings=warning,
            )
        )
    warnings = (
        ("Authoritative CT-006 mechanics failed; candidate numerical fields were not parsed.",)
        if failed else ()
    )
    if shape.method_branch == "published-2023":
        warnings += (
            "DS/EN 1992-1-1:2023 is published but not implemented for Sector publication.",
        )
    return TraceCalculation(
        calculation_id=shape.calculation_id,
        coverage_id=COVERAGE_ID,
        title=f"{shape.direction} directional shear",
        method_id=method_id(shape),
        axes=shape.axes,
        final_step_id="ct-006-direction-result",
        steps=tuple(steps),
        warnings=warnings,
        assumptions=(
            "Vx and Vy are independent retained shear planes; no cross-direction interaction is inferred.",
            "The original face selector is identity-distinct from the resulting required face order.",
            "Sector's minimax selector and conditional chord solve are uncited project methods.",
        ),
    )


def _expected_bundle(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any] | None,
) -> tuple[TraceBundle, object]:
    replay = replay_shear_evidence(inp, out, context)
    bundle = create_bundle(
        input_sha256=input_sha256,
        result_sha256=result_sha256,
        calculations=tuple(_calculation(item, inp) for item in replay.directions),
        warnings=replay.warnings,
    )
    registry = expected_registry(tuple(item.shape for item in replay.directions))
    audit_trace_registry(bundle, registry)
    return bundle, registry


def build_shear_trace_families(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle:
    """Reconstruct, seal and exact-registry-audit all required CT-006 directions."""

    try:
        return _expected_bundle(
            inp, out, input_sha256=input_sha256,
            result_sha256=result_sha256, context=context,
        )[0]
    except TraceValidationError:
        raise
    except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"invalid CT-006 evidence: {exc}") from exc


def validate_shear_trace_families(
    bundle: TraceBundle | dict[str, Any],
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle:
    """Reject coherently resealed value, graph, source, identity or seal tampering."""

    candidate = validate_bundle(
        bundle,
        expected_input_sha256=input_sha256,
        expected_result_sha256=result_sha256,
    )
    expected, registry = _expected_bundle(
        inp, out, input_sha256=input_sha256,
        result_sha256=result_sha256, context=context,
    )
    audit_trace_registry(candidate, registry)
    if candidate.to_dict() != expected.to_dict():
        raise TraceValidationError("CT-006 trace differs from authoritative input replay")
    return candidate
