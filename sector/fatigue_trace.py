"""Closed CT-010a reinforcement-fatigue calculation trace."""

from __future__ import annotations

import math
import sys
from typing import Any

from .calculation_trace import (
    RESULT_FAILED,
    RESULT_FINITE,
    RESULT_NEGATIVE_INFINITY,
    RESULT_POSITIVE_INFINITY,
    RESULT_UNDEFINED,
    TraceBundle,
    TraceCalculation,
    TraceDependency,
    TraceResult,
    TraceStep,
    TraceValidationError,
    create_bundle,
    validate_bundle,
)
from .fatigue_trace_contract import (
    COVERAGE_ID,
    METHOD_ID,
    ElementShape,
    FatigueShape,
    StepSpec,
    bin_prefix,
    element_prefix,
    expected_element_steps,
    expected_invalid_steps,
    expected_output_steps,
    expected_registry,
    trace_shape,
)
from .fatigue_trace_reader import FatigueEvidence, read_fatigue_evidence
from .trace_registry import audit_trace_registry


_MAX_LOG10 = math.log10(sys.float_info.max)
_MIN_LOG10 = math.log10(float.fromhex("0x0.0000000000001p-1022"))
_NONFINITE_REASON = (
    "The retained finite operands produce an explicit non-finite engineering "
    "state; no fabricated finite replacement is sealed."
)
_FAILED_REASON = (
    "At least one retained original or equivalent-area Elastic solve did not "
    "converge; reinforcement fatigue cannot pass."
)


def _close(actual: float, expected: float, label: str) -> None:
    if math.isnan(expected):
        matched = math.isnan(actual)
    elif math.isinf(expected):
        matched = actual == expected
    else:
        matched = math.isclose(
            actual, expected, rel_tol=2.0e-12, abs_tol=2.0e-12
        )
    if not matched:
        raise TraceValidationError(
            f"{label} contradicts independent reinforcement-fatigue proof"
        )


def _exact_text(actual: Any, expected: str, label: str) -> None:
    if type(actual) is not str or actual != expected:
        raise TraceValidationError(f"{label} retained identity drifted")


def _exact_bool(actual: Any, expected: bool, label: str) -> None:
    if type(actual) is not bool or actual is not expected:
        raise TraceValidationError(f"{label} retained Boolean drifted")


def _pow10(exponent: float) -> float:
    """Overflow/underflow-safe base-ten exponentiation."""

    if exponent == math.inf or exponent > _MAX_LOG10:
        return math.inf
    if exponent == -math.inf or exponent < _MIN_LOG10:
        return 0.0
    return 10.0 ** exponent


def _sn_life(properties: Any, design_range: float, gamma_s: float) -> tuple[float, float, float]:
    if design_range == 0.0:
        return math.inf, math.inf, 0.0
    knee = properties.delta_sigma_rsk_mpa / gamma_s
    exponent = properties.k1 if design_range >= knee else properties.k2
    log_life = (
        math.log10(properties.n_star)
        + exponent * math.log10(
            properties.delta_sigma_rsk_mpa / (gamma_s * design_range)
        )
    )
    return _pow10(log_life), log_life, float(exponent)


def _damage_from_log(cycles: float, log_life: float) -> float:
    """Reconstruct Miner damage without dividing by an underflowed life."""

    if cycles == 0.0 or log_life == math.inf:
        return 0.0
    return _pow10(math.log10(cycles) - log_life)


def _yield_proof(stress: float, properties: Any, gamma_s: float) -> tuple[float, float]:
    characteristic = (
        properties.fytk_mpa
        if stress >= 0.0
        else (
            properties.fyck_mpa
            if properties.fyck_mpa is not None
            else properties.fytk_mpa
        )
    )
    limit = float(characteristic) / gamma_s
    return limit, abs(stress) / limit


def _proof_element(shape: ElementShape, evidence: FatigueEvidence) -> dict[str, float]:
    item = shape.evidence
    properties = item.properties
    gamma_s = float(evidence.prepared.gamma_s)
    values: dict[str, float] = {}
    prefix = element_prefix(item)
    values[f"{prefix}-n-star"] = float(properties.n_star)
    values[f"{prefix}-k1"] = float(properties.k1)
    values[f"{prefix}-k2"] = float(properties.k2)
    values[f"{prefix}-delta-sigma-rsk"] = float(
        properties.delta_sigma_rsk_mpa
    )
    values[f"{prefix}-proof-tension"] = float(properties.fytk_mpa)
    values[f"{prefix}-proof-compression"] = float(
        properties.fyck_mpa
        if properties.fyck_mpa is not None
        else properties.fytk_mpa
    )

    spectrum_damage_values = []
    spectrum_yield_values = []
    spectrum_convergence_values = []
    spectrum_utilisation_values = []
    spectrum_verdict_values = []
    for spectrum_index, (spectrum, result) in enumerate(
        zip(evidence.spectra, item.results)
    ):
        if len(spectrum.bins) != len(result.bins):
            raise TraceValidationError("reinforcement bin cardinality drifted")
        spectrum_damage = []
        spectrum_yield = []
        spectrum_converged = []
        for bin_index, (state, row) in enumerate(zip(spectrum.bins, result.bins)):
            bp = bin_prefix(spectrum_index, spectrum, bin_index, row)
            _exact_text(row.bin_name, state.name, f"{bp} bin name")
            _close(float(row.cycles), float(state.cycles), f"{bp} cycles")
            _exact_bool(row.converged, state.converged, f"{bp} convergence")
            _exact_text(row.bond_method, state.bond_method, f"{bp} bond method")

            long_stress = float(state.bar_stress_long_mpa[item.index])
            total_elastic = float(state.bar_stress_total_mpa[item.index])
            fatigue_total = (
                state.bar_stress_fatigue_total_mpa
                or state.bar_stress_total_mpa
            )
            fatigue_design = (
                state.bar_stress_fatigue_design_total_mpa
                or fatigue_total
            )
            total = float(fatigue_total[item.index])
            total_design = float(fatigue_design[item.index])
            range_elastic = abs(total_elastic - long_stress)
            stress_range = abs(total - long_stress)
            design_range = abs(total_design - long_stress)
            bond = (
                stress_range / range_elastic
                if range_elastic > 0.0
                else (math.inf if stress_range > 0.0 else 1.0)
            )
            life, log_life, exponent = _sn_life(
                properties, design_range, gamma_s
            )
            damage = _damage_from_log(float(state.cycles), log_life)
            long_limit, long_util = _yield_proof(
                long_stress, properties, gamma_s
            )
            total_limit, total_util = _yield_proof(
                total_design, properties, gamma_s
            )
            if total_util >= long_util:
                governing_stress = total_design
                yield_limit = total_limit
                yield_util = total_util
            else:
                governing_stress = long_stress
                yield_limit = long_limit
                yield_util = long_util

            checks = {
                "stress_long_mpa": long_stress,
                "stress_total_elastic_mpa": total_elastic,
                "stress_total_mpa": total,
                "stress_total_design_mpa": total_design,
                "stress_range_elastic_mpa": range_elastic,
                "stress_range_mpa": stress_range,
                "design_stress_range_mpa": design_range,
                "bond_adjustment": bond,
                "sn_exponent": exponent,
                "cycles_to_failure": life,
                "log10_cycles_to_failure": log_life,
                "damage": damage,
                "governing_stress_mpa": governing_stress,
                "yield_limit_mpa": yield_limit,
                "yield_utilisation": yield_util,
                "delta_sigma_rsk_mpa": float(properties.delta_sigma_rsk_mpa),
                "delta_sigma_rd_mpa": float(properties.delta_sigma_rsk_mpa) / gamma_s,
            }
            for field, expected in checks.items():
                _close(float(getattr(row, field)), expected, f"{bp}.{field}")

            values.update({
                f"{bp}-cycles": float(state.cycles),
                f"{bp}-combined-convergence": 1.0 if state.converged else 0.0,
                f"{bp}-stress-long": long_stress,
                f"{bp}-stress-total-elastic": total_elastic,
                f"{bp}-stress-total-fatigue": total,
                f"{bp}-stress-total-design": total_design,
                f"{bp}-range-elastic": range_elastic,
                f"{bp}-range-fatigue": stress_range,
                f"{bp}-range-design": design_range,
                f"{bp}-bond-adjustment": bond,
                f"{bp}-sn-exponent": exponent,
                f"{bp}-log10-life": log_life,
                f"{bp}-cycles-to-failure": life,
                f"{bp}-damage": damage,
                f"{bp}-governing-stress": governing_stress,
                f"{bp}-yield-limit": yield_limit,
                f"{bp}-yield-utilisation": yield_util,
                f"{bp}-bin-proof": 1.0,
            })
            spectrum_damage.append(damage)
            spectrum_yield.append(yield_util)
            spectrum_converged.append(state.converged)

        expected_damage = sum(spectrum_damage)
        governing_damage_index = max(
            range(len(spectrum_damage)), key=spectrum_damage.__getitem__
        )
        governing_yield_index = max(
            range(len(spectrum_yield)), key=spectrum_yield.__getitem__
        )
        expected_yield = spectrum_yield[governing_yield_index]
        expected_converged = all(spectrum_converged)
        expected_utilisation = max(expected_damage, expected_yield)
        expected_passed = bool(
            expected_converged
            and expected_damage <= 1.0
            and expected_yield <= 1.0
        )
        _close(float(result.damage), expected_damage, "element damage")
        _close(float(result.damage_utilisation), expected_damage, "damage utilisation")
        _exact_text(
            result.governing_damage_bin,
            result.bins[governing_damage_index].bin_name,
            "governing damage bin",
        )
        _close(float(result.yield_utilisation), expected_yield, "yield utilisation")
        _exact_text(
            result.governing_yield_bin,
            result.bins[governing_yield_index].bin_name,
            "governing yield bin",
        )
        _close(float(result.utilisation), expected_utilisation, "element utilisation")
        _exact_bool(result.converged, expected_converged, "element convergence")
        _exact_bool(result.passed, expected_passed, "element verdict")
        spectrum_token = f"u{spectrum.spectrum_name.encode('utf-8').hex()}"
        spectrum_prefix = (
            f"{prefix}-spectrum-{spectrum_index:03d}-{spectrum_token}"
        )
        damage_token = (
            f"u{result.governing_damage_bin.encode('utf-8').hex()}"
        )
        yield_token = f"u{result.governing_yield_bin.encode('utf-8').hex()}"
        values.update({
            f"{spectrum_prefix}-damage-sum": expected_damage,
            f"{spectrum_prefix}-governing-damage-bin-{damage_token}": 1.0,
            f"{spectrum_prefix}-yield-maximum": expected_yield,
            f"{spectrum_prefix}-governing-yield-bin-{yield_token}": 1.0,
            f"{spectrum_prefix}-converged": (
                1.0 if expected_converged else 0.0
            ),
            f"{spectrum_prefix}-utilisation": expected_utilisation,
            f"{spectrum_prefix}-passed": 1.0 if expected_passed else 0.0,
            f"{spectrum_prefix}-proof": 1.0,
        })
        spectrum_damage_values.append(expected_damage)
        spectrum_yield_values.append(expected_yield)
        spectrum_convergence_values.append(expected_converged)
        spectrum_utilisation_values.append(expected_utilisation)
        spectrum_verdict_values.append(expected_passed)

    maximum_damage = max(spectrum_damage_values)
    max_yield = max(spectrum_yield_values)
    converged = all(spectrum_convergence_values)
    utilisation = max(spectrum_utilisation_values)
    passed = all(spectrum_verdict_values)
    values.update({
        f"{prefix}-damage-maximum": maximum_damage,
        f"{prefix}-yield-maximum": max_yield,
        f"{prefix}-converged": 1.0 if converged else 0.0,
        f"{prefix}-utilisation": utilisation,
        f"{prefix}-passed": 1.0 if passed else 0.0,
        f"ct-010a-{prefix}-result": utilisation,
    })
    return values


def _common_values(evidence: FatigueEvidence) -> dict[str, float | TraceResult]:
    values: dict[str, float | TraceResult] = {}
    for leaf in evidence.input_leaves:
        values[leaf.step_id] = (
            TraceResult(
                RESULT_UNDEFINED,
                None,
                "The retained optional input is absent at this boundary.",
            )
            if leaf.absent
            else float(leaf.value)
        )
    values["geometry-material-spectrum-vector"] = 1.0
    if evidence.valid:
        values["input-gamma-s"] = float(evidence.prepared.gamma_s)
        values["input-gamma-ff"] = float(evidence.prepared.gamma_ff)
        values["input-gamma-c"] = (
            TraceResult(
                RESULT_UNDEFINED,
                None,
                "Concrete partial factor is absent because the concrete sibling is disabled.",
            )
            if evidence.prepared.gamma_c is None
            else float(evidence.prepared.gamma_c)
        )
        values["normalised-fatigue-inputs"] = 1.0
    return values


def _element_values(shape: ElementShape, evidence: FatigueEvidence) -> tuple[dict[str, Any], bool]:
    values = _common_values(evidence)
    values.update(_proof_element(shape, evidence))
    converged = all(result.converged for result in shape.evidence.results)
    return values, converged


def _output_values(evidence: FatigueEvidence) -> tuple[dict[str, Any], bool]:
    values = _common_values(evidence)
    summaries = []
    for element in evidence.elements:
        for spectrum_index, (spectrum, result) in enumerate(
            zip(evidence.spectra, element.results)
        ):
            prefix = element_prefix(element)
            sp = (
                f"output-{prefix}-spectrum-{spectrum_index:03d}-"
                f"u{spectrum.spectrum_name.encode('utf-8').hex()}"
            )
            values.update({
                f"{sp}-damage": float(result.damage),
                f"{sp}-yield-utilisation": float(result.yield_utilisation),
                f"{sp}-convergence": 1.0 if result.converged else 0.0,
                f"{sp}-utilisation": float(result.utilisation),
                f"{sp}-passed": 1.0 if result.passed else 0.0,
            })
            summaries.append(result)
    converged = all(result.converged for result in summaries)
    utilisation = max((float(result.utilisation) for result in summaries), default=0.0)
    passed = all(result.passed for result in summaries)
    values.update({
        "reinforcement-output-converged": 1.0 if converged else 0.0,
        "reinforcement-output-utilisation": utilisation,
        "reinforcement-output-passed": 1.0 if passed else 0.0,
        "ct-010a-reinforcement-output-result": utilisation,
    })
    return values, converged


def _result(value: float | TraceResult) -> TraceResult:
    if isinstance(value, TraceResult):
        return value
    numeric = float(value)
    if math.isnan(numeric):
        return TraceResult(RESULT_UNDEFINED, None, _NONFINITE_REASON)
    if numeric == math.inf:
        return TraceResult(RESULT_POSITIVE_INFINITY, None, _NONFINITE_REASON)
    if numeric == -math.inf:
        return TraceResult(RESULT_NEGATIVE_INFINITY, None, _NONFINITE_REASON)
    return TraceResult(RESULT_FINITE, numeric)


def _expression(step_id: str) -> str:
    if step_id.endswith("-log10-life"):
        return "log10(N) = log10(N*) + k log10(delta_sigma_Rsk/(gamma_s delta_sigma))"
    if step_id.endswith("-damage"):
        return "D_i = 10^(log10(n_i) - log10(N_i))"
    if step_id.endswith("-damage-sum"):
        return "D = sum_i D_i"
    if step_id.endswith("-range-design"):
        return "delta_sigma_design = abs(sigma_design - sigma_long)"
    if step_id.endswith("-yield-utilisation"):
        return "eta_y = abs(sigma_governing)/(f_y/gamma_s)"
    if step_id.endswith("-utilisation"):
        return "eta = max(D, eta_y)"
    if step_id.endswith("-passed"):
        return "PASS = converged and D <= 1 and eta_y <= 1"
    return f"Bind {step_id}"


def _calculation(
    *,
    calculation_id: str,
    title: str,
    axes: tuple[Any, ...],
    specs: tuple[StepSpec, ...],
    values: dict[str, Any],
    converged: bool,
    invalid_reason: str | None = None,
) -> TraceCalculation:
    units = {spec.step_id: spec.unit for spec in specs}
    final_id = specs[-1].step_id
    steps = []
    for spec in specs:
        if spec.step_id not in values and invalid_reason is None:
            raise TraceValidationError(f"internal CT-010a value omitted {spec.step_id}")
        if spec.step_id == final_id and (invalid_reason is not None or not converged):
            result = TraceResult(
                RESULT_FAILED,
                None,
                invalid_reason or _FAILED_REASON,
            )
        else:
            result = _result(values.get(spec.step_id, 1.0))
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
            actual_expression=_expression(spec.step_id),
            substituted_expression=(
                f"{spec.step_id} = {result.value:.17g} {spec.unit.symbol}"
                if result.state == RESULT_FINITE
                else f"{spec.step_id} = {result.state}"
            ),
            result=result,
        ))
    return TraceCalculation(
        calculation_id=calculation_id,
        coverage_id=COVERAGE_ID,
        title=title,
        method_id=METHOD_ID,
        axes=axes,
        final_step_id=final_id,
        steps=tuple(steps),
        assumptions=(
            "Every spectrum bin is independent and Miner damage is accumulated per reinforcement element.",
            "Combined convergence retains the original and, where applicable, equivalent-tendon-area solve evidence.",
            "Concrete-fatigue values remain outside CT-010a while their retained presence, position and types are fenced.",
        ),
    )


def _calculations(shape: FatigueShape) -> tuple[TraceCalculation, ...]:
    evidence = shape.evidence
    if shape.invalid is not None:
        specs = expected_invalid_steps(shape.invalid, evidence)
        values = _common_values(evidence)
        values["geometry-material-spectrum-vector"] = 1.0
        for spec in specs:
            values.setdefault(spec.step_id, 1.0)
        return (_calculation(
            calculation_id=shape.invalid.calculation_id,
            title="Invalid reinforcement fatigue boundary",
            axes=shape.invalid.axes,
            specs=specs,
            values=values,
            converged=False,
            invalid_reason="; ".join(evidence.errors),
        ),)
    calculations = []
    for element in shape.elements:
        values, converged = _element_values(element, evidence)
        calculations.append(_calculation(
            calculation_id=element.calculation_id,
            title=f"Reinforcement fatigue: {element.evidence.element_id}",
            axes=element.axes,
            specs=expected_element_steps(element, evidence),
            values=values,
            converged=converged,
        ))
    assert shape.output is not None
    values, converged = _output_values(evidence)
    calculations.append(_calculation(
        calculation_id=shape.output.calculation_id,
        title="Reinforcement fatigue output",
        axes=shape.output.axes,
        specs=expected_output_steps(shape.output, evidence),
        values=values,
        converged=converged,
    ))
    return tuple(calculations)


def _expected_bundle(
    inp,
    out,
    *,
    input_sha256: str,
    result_sha256: str,
    context=None,
) -> TraceBundle:
    evidence = read_fatigue_evidence(inp, out, context)
    shape = trace_shape(evidence)
    bundle = create_bundle(
        input_sha256=input_sha256,
        result_sha256=result_sha256,
        calculations=_calculations(shape),
    )
    audit_trace_registry(bundle, expected_registry(shape))
    return bundle


def build_fatigue_trace_family(
    inp,
    out,
    *,
    input_sha256: str,
    result_sha256: str,
    context=None,
) -> TraceBundle:
    """Build and exact-registry audit the retained CT-010a family."""

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
        raise TraceValidationError(f"invalid CT-010a evidence: {exc}") from exc


def validate_fatigue_trace_family(
    bundle,
    inp,
    out,
    *,
    input_sha256: str,
    result_sha256: str,
    context=None,
) -> TraceBundle:
    """Reject malformed, stale, or coherently resealed CT-010a traces."""

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
    if candidate.to_dict() != expected.to_dict():
        raise TraceValidationError(
            "CT-010a trace differs from the independently reconstructed family"
        )
    return candidate
