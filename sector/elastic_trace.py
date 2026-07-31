"""Solver-owned unpublished CT-005 elastic and first-cracking trace."""

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
from .elastic_trace_contract import (
    COVERAGE_ID,
    METHOD_ID,
    expected_registry,
    expected_step_contract,
)
from .elastic_trace_replay import ReplayEvidence, replay_elastic_evidence
from .trace_registry import audit_trace_registry


def _format(value: float) -> str:
    return format(float(value), ".17g")


def _actual_expression(step_id: str, title: str) -> str:
    """Return the retained mechanics expression for each numerical step class."""

    if step_id == "short-term-modular-ratio":
        return "n_s = E_ref / (1000 E_c,GPa)"
    if step_id == "long-term-modular-ratio":
        return "n_l = E_ref (1 + phi) / (1000 E_c,GPa)"
    if "-plane-q" in step_id:
        if step_id.startswith("long-cracked"):
            return "solve R_cr(q) + R_p0 = [N_l,-Mx_l,-My_l]"
        if step_id.startswith("total-cracked"):
            return "solve R_cr(q) + R_neu + R_p0 = [N_l+N_s,-(Mx_l+Mx_s),-(My_l+My_s)]"
        if step_id.startswith("stage-i-long-total"):
            return "solve K_I(n_l) q = [N_l,-Mx_l,-My_l] - R_p0"
        if step_id.startswith("stage-i-long-external"):
            return "solve K_I(n_l) q = [N_l,-Mx_l,-My_l]"
        if step_id.startswith("stage-i-short-external"):
            return "solve K_I(n_s) q = [N_s,-Mx_s,-My_s]"
    if "-compression-" in step_id and not step_id.endswith("-moments"):
        field = step_id.rsplit("-", 1)[-1]
        return {
            "area": "A_c = integral_active dA",
            "sx": "Sx_c = integral_active x dA",
            "sy": "Sy_c = integral_active y dA",
            "sxx": "Sxx_c = integral_active x^2 dA",
            "syy": "Syy_c = integral_active y^2 dA",
            "sxy": "Sxy_c = integral_active x y dA",
        }.get(field, title)
    if "-concrete-" in step_id and step_id.rsplit("-", 1)[-1] in {"n", "mx", "my"}:
        return {
            "n": "N_c = q0 A_c + qx Sx_c + qy Sy_c",
            "mx": "Mx_c = q0 Sy_c + qx Sxy_c + qy Syy_c",
            "my": "My_c = q0 Sx_c + qx Sxx_c + qy Sxy_c",
        }[step_id.rsplit("-", 1)[-1]]
    if any(token in step_id for token in ("-bar-", "-tendon-", "-prestress-", "-neutralising-")) and step_id.rsplit("-", 1)[-1] in {"n", "mx", "my"}:
        return {
            "n": "N = sum(sigma_i A_i)",
            "mx": "Mx = sum(sigma_i A_i y_i)",
            "my": "My = sum(sigma_i A_i x_i)",
        }[step_id.rsplit("-", 1)[-1]]
    if "equilibrium-residual" in step_id:
        return "residual = sum(internal resultants) - tension-positive external target"
    if step_id.endswith("-long-stress"):
        return "sigma_long = n_l (E_i/E_ref) q_long(x_i,y_i) + sigma_p0,i"
    if step_id.endswith("-rst1-stress"):
        return "sigma_RST1 = n_s (E_i/E_ref) q_RST1(x_i,y_i)"
    if step_id.endswith("-difference-stress"):
        return "sigma_difference = sigma_total - sigma_long"
    if step_id.endswith("-total-stress") and step_id.startswith("element-"):
        return "sigma_total = sigma_long,passive (1 - n_s/n_l) + sigma_RST1 + sigma_p0"
    if step_id.endswith("-total-strain"):
        return "strain_permille = 1000 sigma_total / E_i"
    if step_id.startswith("response-fibre-") and step_id.endswith("-raw-stress"):
        return "q_RST1,f = q0,RST1 + qx,RST1 x_f + qy,RST1 y_f"
    if step_id.startswith("response-fibre-") and step_id.endswith("-strain"):
        return "strain_f,permille = (q_RST1,f + phi q_long,f) / E_c,MPa"
    if step_id.startswith("response-fibre-") and step_id.endswith("-carried-stress"):
        return "sigma_c,f = min(q_RST1,f / 1000, 0)"
    if "properties" in step_id:
        field = step_id.rsplit("-", 1)[-1]
        return {
            "area": "A_t = A_concrete + sum(n_l E_i/E_ref A_i)",
            "cx": "cx = Sx_t / A_t",
            "cy": "cy = Sy_t / A_t",
            "ix": "Ix = Syy_t - A_t cy^2",
            "iy": "Iy = Sxx_t - A_t cx^2",
            "ixy": "Ixy = Sxy_t - A_t cx cy",
        }.get(field, f"Bind {title.lower()}")
    if step_id.startswith("cracking-") and step_id.endswith("-fixed-prestress"):
        return "sigma_pre,f = sigma_long,total,f - sigma_long,external,f"
    if step_id.startswith("cracking-") and step_id.endswith("-external-stress"):
        return "sigma_ext,f = sigma_long,external,f (+ sigma_short,external,f for total path)"
    if step_id.startswith("cracking-") and step_id.endswith("-total-stress"):
        return "sigma_total,f = sigma_pre,f + sigma_ext,f"
    if step_id in {"cracking-long-factor", "cracking-total-factor"}:
        return "lambda_path = min_f(lambda_f)"
    if step_id.startswith("cracking-") and step_id.endswith("-factor"):
        return "lambda_f = max(0, (fctm - sigma_pre,f) / sigma_ext,f) when tensile reach exists; otherwise +infinity"
    if step_id == "governing-cracking-factor":
        return "lambda_cr = min(lambda_long, lambda_total); ties select long"
    if step_id == "retained-cracked-state":
        return "cracked = 1 when lambda_cr < 1, otherwise 0"
    if step_id == "ct-005-elastic-first-cracking-result":
        return "CT-005 result state = authoritative lambda_cr or explicit failure"
    return f"Bind {title.lower()}"


def _calculation(evidence: ReplayEvidence) -> TraceCalculation:
    specs = expected_step_contract(evidence.shape)
    units = {spec.step_id: spec.unit for spec in specs}
    steps = []
    for spec in specs:
        result = evidence.states.get(spec.step_id)
        if result is None:
            if spec.step_id not in evidence.values:
                raise TraceValidationError(
                    f"internal CT-005 value omitted {spec.step_id}"
                )
            value = evidence.values[spec.step_id]
            result = TraceResult(RESULT_FINITE, float(value))
            substituted = f"{spec.step_id} = {_format(value)} {spec.unit.symbol}"
        else:
            substituted = f"{spec.step_id} = {result.state}"
        assumptions = ()
        if spec.step_id == "ct-005-elastic-first-cracking-result":
            assumptions = (
                "Stress, strain and first-cracking values are output quantities only; no limit or compliance verdict is implied.",
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
                actual_expression=_actual_expression(spec.step_id, spec.title),
                substituted_expression=substituted,
                result=result,
                assumptions=assumptions,
            )
        )
    return TraceCalculation(
        calculation_id=evidence.shape.calculation_id,
        coverage_id=COVERAGE_ID,
        title="Elastic section response and first cracking",
        method_id=METHOD_ID,
        axes=evidence.shape.axes,
        final_step_id="ct-005-elastic-first-cracking-result",
        steps=tuple(steps),
        warnings=evidence.warnings,
        assumptions=(
            "User normal force is tension-positive; the solver boundary converts it once to compression-positive P.",
            "The numerical plane q0+qx*x+qy*y is the solver's concrete-reference stress plane in kN/m2; physical strain is obtained with the exact input concrete modulus.",
            "The transformed-section equilibrium, creep superposition and first-cracking selector are Sector project methods.",
        ),
    )


def _expected_bundle(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any] | None,
) -> TraceBundle:
    trace_context = {} if context is None else context
    evidence = replay_elastic_evidence(inp, out, trace_context)
    bundle = create_bundle(
        input_sha256=input_sha256,
        result_sha256=result_sha256,
        calculations=(_calculation(evidence),),
    )
    audit_trace_registry(bundle, expected_registry(evidence.shape))
    return bundle


def build_elastic_trace_family(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle:
    """Build, seal, and exact-registry audit one solver-owned CT-005 family."""

    try:
        return _expected_bundle(
            inp,
            out,
            input_sha256=input_sha256,
            result_sha256=result_sha256,
            context=context,
        )
    except TraceValidationError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"invalid CT-005 evidence: {exc}") from exc


def validate_elastic_trace_family(
    bundle: TraceBundle | dict[str, Any],
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle:
    """Reject even coherently resealed CT-005 value/expression/source tampering."""

    candidate = validate_bundle(
        bundle,
        expected_input_sha256=input_sha256,
        expected_result_sha256=result_sha256,
    )
    expected = _expected_bundle(
        inp,
        out,
        input_sha256=input_sha256,
        result_sha256=result_sha256,
        context=context,
    )
    # The registry protects identity, shape, graph, role and complete provenance;
    # equality with an independently replayed bundle additionally binds every
    # numerical result, expression, warning and assumption after resealing.
    audit_trace_registry(candidate, expected_registry(
        replay_elastic_evidence(
            inp, out, {} if context is None else context
        ).shape
    ))
    if candidate.to_dict() != expected.to_dict():
        raise TraceValidationError(
            "CT-005 trace differs from authoritative input replay"
        )
    return candidate
