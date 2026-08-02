"""Solver-owned unpublished CT-010a reinforcement-fatigue trace."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import pathlib
import sys
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from .calculation_trace import (
    RESULT_FAILED,
    RESULT_FINITE,
    RESULT_NEGATIVE_INFINITY,
    RESULT_POSITIVE_INFINITY,
    RESULT_UNDEFINED,
    ROLE_COMPUTED,
    ROLE_FINAL,
    ROLE_USER_INPUT,
    TraceBundle,
    TraceCalculation,
    TraceDependency,
    TraceResult,
    TraceStep,
    TraceValidationError,
    create_bundle,
    trace_identity_token,
    validate_bundle,
)
from .fatigue import (
    FatigueBinState,
    FatigueSpectrumResult,
    ReinforcementBinResult,
    ReinforcementFatigueProperties,
    ReinforcementFatigueResult,
    steel_fatigue_life,
)
from .fatigue_trace_contract import (
    BOUNDARY_SOURCE,
    COVERAGE_ID,
    CYCLES,
    DAMAGE,
    FINAL_STATES,
    INPUT_SOURCE,
    INVALID_KEYS,
    INVALID_MEMBER_ID,
    METHOD_ID,
    NORMAL_SUCCESS_KEYS,
    ONE,
    OUTPUT_MEMBER_ID,
    RAW_INPUT_KEYS,
    REPLAY_SOURCE,
    STRESS,
    VERDICT_SOURCE,
    MemberPlan,
    StepRows,
    expected_registry,
    standard_sources,
)
from .section_trace_blocks import context_axes, context_id
from .trace_registry import audit_trace_registry


_DRIFT = "authoritative CT-010a output inventory drifted"
_NONFINITE_REASON = (
    "The retained reinforcement-fatigue quantity is non-finite; its exact "
    "signed numerical state is published instead of a finite substitute."
)
_UNDEFINED_REASON = (
    "The retained reinforcement-fatigue quantity is undefined; no numerical "
    "substitute is published."
)
_FAILED_REASON = (
    "The retained reinforcement-fatigue solve did not converge; no finite "
    "assessment result is asserted."
)


def _analysis_module():
    """Load the retained application boundary without importing Streamlit."""

    try:
        import fatigue_analysis
    except ImportError:  # pragma: no cover - direct sector-only imports
        sys.path.insert(
            0,
            str(pathlib.Path(__file__).resolve().parent.parent / "app"),
        )
        import fatigue_analysis
    return fatigue_analysis


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TraceValidationError(f"{label} must be a mapping")
    if any(type(key) is not str for key in value):
        raise TraceValidationError(f"{label} keys must be text")
    return value


def _sequence(value: Any, label: str) -> tuple[Any, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TraceValidationError(f"{label} must be an ordered sequence")
    return tuple(value)


def _ordered_mapping(value: Any, keys: tuple[str, ...], label: str):
    value = _mapping(value, label)
    if tuple(value) != keys:
        raise TraceValidationError(f"{label} keys/order differ from contract")
    return value


def _float_equal(actual: float, expected: float) -> bool:
    return actual == expected or (
        math.isnan(actual) and math.isnan(expected)
    )


def _compare_exact(actual: Any, expected: Any, label: str) -> None:
    """Compare retained Python values without numerical reseal tolerance."""

    if type(actual) is not type(expected):
        raise TraceValidationError(f"{label} retained type differs")
    if dataclasses.is_dataclass(expected) and not isinstance(expected, type):
        for field in dataclasses.fields(expected):
            _compare_exact(
                getattr(actual, field.name),
                getattr(expected, field.name),
                f"{label}.{field.name}",
            )
        return
    if isinstance(expected, np.ndarray):
        if (
            actual.dtype != expected.dtype
            or actual.shape != expected.shape
            or not np.array_equal(actual, expected, equal_nan=True)
        ):
            raise TraceValidationError(f"{label} differs from replay")
        return
    if isinstance(expected, Mapping):
        if tuple(actual) != tuple(expected):
            raise TraceValidationError(f"{label} keys/order differ")
        for key in expected:
            _compare_exact(actual[key], expected[key], f"{label}.{key}")
        return
    if isinstance(expected, (tuple, list)):
        if len(actual) != len(expected):
            raise TraceValidationError(f"{label} cardinality differs")
        for index, (item, wanted) in enumerate(zip(actual, expected)):
            _compare_exact(item, wanted, f"{label}[{index}]")
        return
    if isinstance(expected, float):
        if not _float_equal(actual, expected):
            raise TraceValidationError(f"{label} differs from replay")
        return
    if actual != expected:
        raise TraceValidationError(f"{label} differs from replay")


def _shape_fence(actual: Any, expected: Any, label: str) -> None:
    """Pin excluded sibling presence, order, type, and cardinality only."""

    if type(actual) is not type(expected):
        raise TraceValidationError(f"{label} retained type differs")
    if dataclasses.is_dataclass(expected) and not isinstance(expected, type):
        if tuple(field.name for field in dataclasses.fields(actual)) != tuple(
            field.name for field in dataclasses.fields(expected)
        ):
            raise TraceValidationError(f"{label} dataclass shape differs")
        for field in dataclasses.fields(expected):
            _shape_fence(
                getattr(actual, field.name),
                getattr(expected, field.name),
                f"{label}.{field.name}",
            )
        return
    if isinstance(expected, np.ndarray):
        if actual.dtype != expected.dtype or actual.shape != expected.shape:
            raise TraceValidationError(f"{label} array shape differs")
        return
    if isinstance(expected, Mapping):
        if tuple(actual) != tuple(expected):
            raise TraceValidationError(f"{label} keys/order differ")
        for key in expected:
            _shape_fence(actual[key], expected[key], f"{label}.{key}")
        return
    if isinstance(expected, (tuple, list)):
        if len(actual) != len(expected):
            raise TraceValidationError(f"{label} cardinality differs")
        for index, (item, wanted) in enumerate(zip(actual, expected)):
            _shape_fence(item, wanted, f"{label}[{index}]")


def _validate_bin_state(actual: Any, expected: FatigueBinState, label: str):
    if type(actual) is not FatigueBinState:
        raise TraceValidationError(f"{label} retained type differs")
    concrete_fields = {
        "concrete_compression_long_mpa",
        "concrete_compression_total_mpa",
        "concrete_compression_design_total_mpa",
    }
    for field in dataclasses.fields(expected):
        check = _shape_fence if field.name in concrete_fields else _compare_exact
        check(
            getattr(actual, field.name),
            getattr(expected, field.name),
            f"{label}.{field.name}",
        )


def _validate_spectrum(
    actual: Any,
    expected: FatigueSpectrumResult,
    *,
    concrete_enabled: bool,
    label: str,
) -> None:
    if type(actual) is not FatigueSpectrumResult:
        raise TraceValidationError(f"{label} retained type differs")
    _compare_exact(actual.spectrum_name, expected.spectrum_name,
                   f"{label}.spectrum_name")
    if type(actual.bins) is not tuple or len(actual.bins) != len(expected.bins):
        raise TraceValidationError(f"{label}.bins shape differs")
    for index, (item, wanted) in enumerate(zip(actual.bins, expected.bins)):
        _validate_bin_state(item, wanted, f"{label}.bins[{index}]")
    _compare_exact(actual.reinforcement, expected.reinforcement,
                   f"{label}.reinforcement")
    for field in (
        "concrete",
        "concrete_search",
        "fcd_fat_mpa",
        "governing_concrete_fibre",
        "concrete_method",
    ):
        _shape_fence(
            getattr(actual, field),
            getattr(expected, field),
            f"{label}.{field}",
        )
    _compare_exact(
        actual.governing_reinforcement_id,
        expected.governing_reinforcement_id,
        f"{label}.governing_reinforcement_id",
    )
    for field in ("utilisation", "converged", "passed"):
        check = _shape_fence if concrete_enabled else _compare_exact
        check(
            getattr(actual, field),
            getattr(expected, field),
            f"{label}.{field}",
        )


def _validate_success(candidate: Any, expected: Mapping[str, Any]) -> None:
    candidate = _ordered_mapping(
        candidate, NORMAL_SUCCESS_KEYS, "candidate fatigue result"
    )
    if tuple(expected) != NORMAL_SUCCESS_KEYS:
        raise TraceValidationError(_DRIFT)
    concrete_enabled = expected["checks"]["concrete"]
    excluded = {
        "concrete_method",
        "concrete_parameters",
    }
    aggregate = {
        "governing_spectrum",
        "utilisation",
        "converged",
        "passed",
    }
    for key in NORMAL_SUCCESS_KEYS:
        if key == "spectra":
            if type(candidate[key]) is not type(expected[key]):
                raise TraceValidationError(
                    "candidate spectra retained type differs"
                )
            actual_spectra = _sequence(candidate[key], "candidate spectra")
            expected_spectra = tuple(expected[key])
            if len(actual_spectra) != len(expected_spectra):
                raise TraceValidationError("candidate spectra cardinality differs")
            for index, (item, wanted) in enumerate(
                zip(actual_spectra, expected_spectra)
            ):
                _validate_spectrum(
                    item,
                    wanted,
                    concrete_enabled=concrete_enabled,
                    label=f"candidate spectra[{index}]",
                )
        elif key == "calculation_references":
            actual = _mapping(candidate[key], "calculation references")
            wanted = expected[key]
            if tuple(actual) != tuple(wanted):
                raise TraceValidationError(
                    "calculation reference keys/order differ"
                )
            for name in wanted:
                check = (
                    _shape_fence
                    if name == "concrete"
                    else _compare_exact
                )
                check(actual[name], wanted[name],
                      f"calculation_references.{name}")
        elif key in excluded or (concrete_enabled and key in aggregate):
            _shape_fence(candidate[key], expected[key], f"candidate.{key}")
        else:
            _compare_exact(candidate[key], expected[key], f"candidate.{key}")


def _validate_invalid(candidate: Any, inp: Mapping[str, Any]) -> Mapping[str, Any]:
    candidate = _ordered_mapping(
        candidate, INVALID_KEYS, "candidate invalid fatigue result"
    )
    if type(candidate["valid"]) is not bool or candidate["valid"] is not False:
        raise TraceValidationError("invalid fatigue result must retain valid=False")
    errors = _sequence(candidate["errors"], "candidate invalid errors")
    if any(type(error) is not str for error in errors):
        raise TraceValidationError("candidate invalid errors must be text")
    # Retain the caller-supplied sequence. Recomputing validation_errors(inp)
    # here would discard externally caught failures and even an explicit empty
    # sequence, which is part of invalid_result's supported boundary.
    expected = _analysis_module().invalid_result(inp, errors=errors)
    if tuple(expected) != INVALID_KEYS:
        raise TraceValidationError(_DRIFT)
    _compare_exact(candidate, expected, "candidate invalid fatigue result")
    return expected


def _identity_tree(value: Any) -> Any:
    """Return a JSON-safe exact-type identity tree for retained inputs."""

    type_id = f"{type(value).__module__}.{type(value).__qualname__}"
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return [
            "dataclass",
            type_id,
            [
                [field.name, _identity_tree(getattr(value, field.name))]
                for field in dataclasses.fields(value)
            ],
        ]
    if isinstance(value, np.ndarray):
        return [
            "ndarray",
            type_id,
            str(value.dtype),
            list(value.shape),
            _identity_tree(value.tolist()),
        ]
    if type_id == "pandas.core.frame.DataFrame":
        return [
            "dataframe",
            type_id,
            _identity_tree(tuple(value.columns)),
            _identity_tree(tuple(value.index)),
            _identity_tree(tuple(str(dtype) for dtype in value.dtypes)),
            _identity_tree(tuple(
                tuple(row)
                for row in value.itertuples(index=False, name=None)
            )),
        ]
    if isinstance(value, Mapping):
        return [
            "mapping",
            type_id,
            [
                [_identity_tree(key), _identity_tree(item)]
                for key, item in value.items()
            ],
        ]
    if isinstance(value, (tuple, list)):
        return [
            "sequence",
            type_id,
            [_identity_tree(item) for item in value],
        ]
    if isinstance(value, float):
        if math.isnan(value):
            body = "nan"
        elif math.isinf(value):
            body = "+inf" if value > 0.0 else "-inf"
        else:
            body = value.hex()
        return ["float", type_id, body]
    if value is None or isinstance(value, (bool, int, str)):
        return ["scalar", type_id, value]
    if hasattr(value, "__dict__"):
        return [
            "object",
            type_id,
            [
                [name, _identity_tree(item)]
                for name, item in vars(value).items()
            ],
        ]
    return ["repr", type_id, repr(value)]


def _digest(value: Any) -> str:
    encoded = json.dumps(
        _identity_tree(value),
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _section_identity(section: Any) -> Any:
    if section is None:
        return None
    return (
        tuple(
            tuple((float(x), float(y)) for x, y in ring)
            for ring in section.concrete
        ),
        tuple((float(item.x), float(item.y), float(item.area))
              for item in section.bars),
        tuple((float(item.x), float(item.y), float(item.area))
              for item in section.tendons),
    )


def _identity_groups(inp: Mapping[str, Any], *, success: bool):
    missing = ("missing",)
    groups: list[tuple[str, Any]] = []
    for key in RAW_INPUT_KEYS:
        groups.append((
            f"raw-{key.replace('_', '-')}",
            ("present", inp[key]) if key in inp else missing,
        ))
    groups.extend((
        ("section-geometry", _section_identity(inp.get("section"))),
        ("bar-element-table", inp.get("bar_elements", missing)),
        ("tendon-element-table", inp.get("tendon_elements", missing)),
        ("bar-material-vector", inp.get("bar_materials", missing)),
        ("tendon-material-vector", inp.get("tendon_materials", missing)),
        ("concrete-material", inp.get("concrete", missing)),
        ("fatigue-detail-catalog", inp.get("fatigue_detail_catalog", missing)),
        ("mild-material-catalog", inp.get("mild_material_catalog", missing)),
        ("prestress-material-catalog",
         inp.get("prestress_material_catalog", missing)),
        ("fatigue-basis", inp.get("fatigue_basis", missing)),
        ("fatigue-spectrum-table",
         inp.get("fatigue_spectrum_base", missing)),
    ))
    if success:
        groups.append((
            "analysis-signature",
            _analysis_module().analysis_signature(inp),
        ))
    return tuple(groups)


def _input_steps(
    rows: StepRows,
    values: dict[str, Any],
    inp: Mapping[str, Any],
    *,
    success: bool,
) -> str:
    leaves = []
    for label, value in _identity_groups(inp, success=success):
        step_id = f"{label}-{_digest(value)}"
        leaves.append(rows.add(
            step_id,
            f"Exact retained {label.replace('-', ' ')} identity",
            ONE,
            ROLE_USER_INPUT,
            INPUT_SOURCE,
        ))
        values[step_id] = 1.0
    normal = rows.add(
        "normalised-fatigue-inputs",
        "Complete retained fatigue input identity",
        ONE,
        ROLE_COMPUTED,
        BOUNDARY_SOURCE,
        *leaves,
    )
    values[normal] = 1.0
    return normal


def _number_equal(actual: Any, expected: Any, label: str) -> None:
    if type(actual) is not float:
        raise TraceValidationError(f"{label} retained type differs")
    if not _float_equal(actual, float(expected)):
        raise TraceValidationError(f"{label} differs from independent proof")


def _damage_proof(cycles: float, log10_life: float) -> float:
    if math.isinf(log10_life):
        return 0.0 if log10_life > 0.0 else math.inf
    exponent = math.log10(cycles) - log10_life
    if exponent > math.log10(sys.float_info.max):
        return math.inf
    if exponent < math.log10(sys.float_info.min * sys.float_info.epsilon):
        return 0.0
    return 10.0 ** exponent


def _yield_proof(
    stress: float,
    properties: ReinforcementFatigueProperties,
    gamma_s: float,
) -> tuple[float, float]:
    characteristic = (
        properties.fytk_mpa
        if stress >= 0.0 or properties.fyck_mpa is None
        else properties.fyck_mpa
    )
    limit = float(characteristic) / gamma_s
    return limit, abs(stress) / limit


def _result(value: Any, *, failed_reason: str | None = None) -> TraceResult:
    if failed_reason is not None:
        return TraceResult(RESULT_FAILED, None, failed_reason)
    if value is None:
        return TraceResult(RESULT_UNDEFINED, None, _UNDEFINED_REASON)
    numeric = float(value)
    if math.isnan(numeric):
        return TraceResult(RESULT_UNDEFINED, None, _UNDEFINED_REASON)
    if math.isinf(numeric):
        return TraceResult(
            RESULT_POSITIVE_INFINITY
            if numeric > 0.0
            else RESULT_NEGATIVE_INFINITY,
            None,
            _NONFINITE_REASON,
        )
    return TraceResult(RESULT_FINITE, numeric)


def _calculation(
    plan: MemberPlan,
    values: Mapping[str, Any],
    *,
    title: str,
    final_failed_reason: str | None = None,
    warnings: tuple[str, ...] = (),
    assumptions: tuple[str, ...] = (),
) -> TraceCalculation:
    units = {spec.step_id: spec.unit for spec in plan.specs}
    steps = []
    final_id = plan.specs[-1].step_id
    for spec in plan.specs:
        result = _result(
            values[spec.step_id],
            failed_reason=(
                final_failed_reason if spec.step_id == final_id else None
            ),
        )
        rendered = result.state
        if result.state == RESULT_FINITE:
            rendered = f"{result.value:.17g} {spec.unit.symbol}"
        steps.append(TraceStep(
            spec.step_id,
            spec.title,
            tuple(
                TraceDependency(dependency, units[dependency])
                for dependency in spec.dependencies
            ),
            spec.quantity_role,
            spec.source,
            spec.step_id,
            spec.unit,
            "Retained authoritative value with declared dependency closure",
            f"{spec.step_id} = {rendered}",
            result,
        ))
    return TraceCalculation(
        plan.calculation_id,
        COVERAGE_ID,
        title,
        METHOD_ID,
        plan.axes,
        final_id,
        tuple(steps),
        warnings,
        assumptions,
    )


def _factor_steps(
    rows: StepRows,
    values: dict[str, Any],
    inp: Mapping[str, Any],
) -> tuple[str, str, str]:
    factors = []
    for step_id, key, title in (
        ("entered-gamma-s", "fatigue_gamma_s", "Entered gamma_s"),
        ("entered-gamma-ff", "fatigue_gamma_ff", "Entered gamma_Ff"),
        ("entered-gamma-c", "fatigue_gamma_c", "Entered gamma_c"),
    ):
        factors.append(rows.add(
            step_id, title, ONE, ROLE_USER_INPUT, INPUT_SOURCE
        ))
        raw = inp.get(key)
        values[step_id] = (
            float(raw)
            if type(raw) in {int, float} and type(raw) is not bool
            else None
        )
    return tuple(factors)


def _bin_proof(
    rows: StepRows,
    values: dict[str, Any],
    prefix: str,
    item: ReinforcementBinResult,
    properties: ReinforcementFatigueProperties,
    *,
    normal: str,
    gamma_s_step: str,
    gamma_ff_step: str,
    gamma_s: float,
    sn_source,
    yield_source,
) -> tuple[str, str, str]:
    cycles = rows.add(
        f"{prefix}-cycles", "Applied cycles", CYCLES,
        ROLE_COMPUTED, REPLAY_SOURCE, normal,
    )
    long_stress = rows.add(
        f"{prefix}-stress-long", "Long-state reinforcement stress", STRESS,
        ROLE_COMPUTED, REPLAY_SOURCE, normal,
    )
    total_stress = rows.add(
        f"{prefix}-stress-total", "Fatigue total reinforcement stress", STRESS,
        ROLE_COMPUTED, REPLAY_SOURCE, normal,
    )
    design_total = rows.add(
        f"{prefix}-stress-total-design",
        "Action-factored fatigue total reinforcement stress", STRESS,
        ROLE_COMPUTED, REPLAY_SOURCE, normal, gamma_ff_step,
    )
    elastic_total = rows.add(
        f"{prefix}-stress-total-elastic",
        "Perfect-bond total reinforcement stress", STRESS,
        ROLE_COMPUTED, REPLAY_SOURCE, normal,
    )
    converged = rows.add(
        f"{prefix}-converged", "Elastic-bin convergence", ONE,
        ROLE_COMPUTED, REPLAY_SOURCE, normal,
    )
    bond_id = rows.add(
        f"{prefix}-bond-method-{_digest(item.bond_method)}",
        "Exact retained bond method identity", ONE,
        ROLE_COMPUTED, REPLAY_SOURCE, normal,
    )
    stress_range = rows.add(
        f"{prefix}-stress-range", "Bond-adjusted stress range", STRESS,
        ROLE_COMPUTED, REPLAY_SOURCE, total_stress, long_stress, bond_id,
    )
    elastic_range = rows.add(
        f"{prefix}-stress-range-elastic", "Perfect-bond stress range", STRESS,
        ROLE_COMPUTED, REPLAY_SOURCE, elastic_total, long_stress,
    )
    bond_factor = rows.add(
        f"{prefix}-bond-adjustment", "Retained bond adjustment", ONE,
        ROLE_COMPUTED, REPLAY_SOURCE, stress_range, elastic_range, bond_id,
    )
    design_range = rows.add(
        f"{prefix}-design-stress-range", "Design stress range", STRESS,
        ROLE_COMPUTED, REPLAY_SOURCE, design_total, long_stress,
        stress_range, bond_factor, gamma_ff_step,
    )
    reference = rows.add(
        f"{prefix}-delta-sigma-rsk", "Characteristic reference range", STRESS,
        ROLE_COMPUTED, sn_source, normal,
    )
    design_reference = rows.add(
        f"{prefix}-delta-sigma-rd", "Design reference range", STRESS,
        ROLE_COMPUTED, sn_source, reference, gamma_s_step,
    )
    exponent = rows.add(
        f"{prefix}-sn-exponent", "Selected S-N exponent", ONE,
        ROLE_COMPUTED, sn_source, design_range, reference, gamma_s_step,
    )
    log_life = rows.add(
        f"{prefix}-log10-cycles-to-failure",
        "Logarithmic cycles to failure", ONE,
        ROLE_COMPUTED, sn_source, design_range, design_reference, exponent,
        gamma_s_step,
    )
    life = rows.add(
        f"{prefix}-cycles-to-failure", "Cycles to failure", CYCLES,
        ROLE_COMPUTED, sn_source, log_life,
    )
    damage = rows.add(
        f"{prefix}-damage", "Palmgren-Miner bin damage", DAMAGE,
        ROLE_COMPUTED, sn_source, cycles, log_life, life,
    )
    governing_stress = rows.add(
        f"{prefix}-governing-stress", "Governing absolute stress state", STRESS,
        ROLE_COMPUTED, yield_source, long_stress, design_total,
    )
    yield_limit = rows.add(
        f"{prefix}-yield-limit", "Design proof-stress limit", STRESS,
        ROLE_COMPUTED, yield_source, governing_stress, gamma_s_step,
    )
    yield_utilisation = rows.add(
        f"{prefix}-yield-utilisation", "Yield utilisation", ONE,
        ROLE_COMPUTED, yield_source, governing_stress, yield_limit,
    )

    values.update({
        cycles: item.cycles,
        long_stress: item.stress_long_mpa,
        total_stress: item.stress_total_mpa,
        design_total: item.stress_total_design_mpa,
        elastic_total: item.stress_total_elastic_mpa,
        converged: float(item.converged),
        bond_id: 1.0,
        stress_range: item.stress_range_mpa,
        elastic_range: item.stress_range_elastic_mpa,
        bond_factor: item.bond_adjustment,
        design_range: item.design_stress_range_mpa,
        reference: item.delta_sigma_rsk_mpa,
        design_reference: item.delta_sigma_rd_mpa,
        exponent: item.sn_exponent,
        log_life: item.log10_cycles_to_failure,
        life: item.cycles_to_failure,
        damage: item.damage,
        governing_stress: item.governing_stress_mpa,
        yield_limit: item.yield_limit_mpa,
        yield_utilisation: item.yield_utilisation,
    })

    expected_range = abs(item.stress_total_mpa - item.stress_long_mpa)
    expected_elastic_range = abs(
        item.stress_total_elastic_mpa - item.stress_long_mpa
    )
    expected_design_range = abs(
        item.stress_total_design_mpa - item.stress_long_mpa
    )
    _number_equal(item.stress_range_mpa, expected_range,
                  f"{prefix} stress range")
    _number_equal(item.stress_range_elastic_mpa, expected_elastic_range,
                  f"{prefix} elastic stress range")
    _number_equal(item.design_stress_range_mpa, expected_design_range,
                  f"{prefix} design stress range")
    expected_bond = (
        item.stress_range_mpa / item.stress_range_elastic_mpa
        if item.stress_range_elastic_mpa > 0.0
        else math.inf if item.stress_range_mpa > 0.0 else 1.0
    )
    _number_equal(item.bond_adjustment, expected_bond,
                  f"{prefix} bond adjustment")
    _number_equal(
        item.delta_sigma_rd_mpa,
        properties.delta_sigma_rsk_mpa / gamma_s,
        f"{prefix} design reference range",
    )
    life_proof = steel_fatigue_life(
        item.design_stress_range_mpa,
        n_star=properties.n_star,
        k1=properties.k1,
        k2=properties.k2,
        delta_sigma_rsk_mpa=properties.delta_sigma_rsk_mpa,
        gamma_s=gamma_s,
        gamma_ff=1.0,
    )
    _number_equal(item.sn_exponent, life_proof.exponent,
                  f"{prefix} S-N exponent")
    _number_equal(item.log10_cycles_to_failure, life_proof.log10_cycles,
                  f"{prefix} logarithmic life")
    _number_equal(item.cycles_to_failure, life_proof.cycles,
                  f"{prefix} life")
    _number_equal(
        item.damage,
        _damage_proof(item.cycles, item.log10_cycles_to_failure),
        f"{prefix} damage",
    )
    long_limit, long_util = _yield_proof(
        item.stress_long_mpa, properties, gamma_s
    )
    total_limit, total_util = _yield_proof(
        item.stress_total_design_mpa, properties, gamma_s
    )
    if total_util >= long_util:
        proof_stress, proof_limit, proof_util = (
            item.stress_total_design_mpa,
            total_limit,
            total_util,
        )
    else:
        proof_stress, proof_limit, proof_util = (
            item.stress_long_mpa,
            long_limit,
            long_util,
        )
    _number_equal(item.governing_stress_mpa, proof_stress,
                  f"{prefix} governing stress")
    _number_equal(item.yield_limit_mpa, proof_limit,
                  f"{prefix} yield limit")
    _number_equal(item.yield_utilisation, proof_util,
                  f"{prefix} yield utilisation")
    return damage, yield_utilisation, converged


def _element_evidence(
    inp: Mapping[str, Any],
    spectrum: FatigueSpectrumResult,
    item: ReinforcementFatigueResult,
    properties: ReinforcementFatigueProperties,
    spectrum_index: int,
    element_index: int,
    context: Mapping[str, Any],
) -> tuple[MemberPlan, TraceCalculation]:
    rows = StepRows()
    values: dict[str, Any] = {}
    normal = _input_steps(rows, values, inp, success=True)
    gamma_s_step, gamma_ff_step, gamma_c_step = _factor_steps(
        rows, values, inp
    )
    property_id = rows.add(
        f"reinforcement-property-{_digest(properties)}",
        "Exact resolved reinforcement fatigue properties",
        ONE,
        ROLE_COMPUTED,
        BOUNDARY_SOURCE,
        normal,
    )
    values[property_id] = 1.0
    edition = _analysis_module().prepare(inp).edition
    sn_source, yield_source = standard_sources(edition)
    damages, yields, convergences = [], [], []
    if len(item.bins) != len(spectrum.bins):
        raise TraceValidationError(
            "reinforcement assessment bin cardinality differs from solve"
        )
    for bin_index, bin_item in enumerate(item.bins):
        if bin_item.bin_name != spectrum.bins[bin_index].name:
            raise TraceValidationError(
                "reinforcement assessment bin order differs from solve"
            )
        prefix = (
            f"bin-{bin_index:02d}-"
            f"{trace_identity_token(bin_item.bin_name)}"
        )
        damage, yield_util, converged = _bin_proof(
            rows,
            values,
            prefix,
            bin_item,
            properties,
            normal=normal,
            gamma_s_step=gamma_s_step,
            gamma_ff_step=gamma_ff_step,
            gamma_s=float(inp["fatigue_gamma_s"]),
            sn_source=sn_source,
            yield_source=yield_source,
        )
        damages.append(damage)
        yields.append(yield_util)
        convergences.append(converged)
    total_damage = rows.add(
        "element-total-damage", "Element Palmgren-Miner damage", DAMAGE,
        ROLE_COMPUTED, sn_source, *damages,
    )
    damage_utilisation = rows.add(
        "element-damage-utilisation",
        "Element damage utilisation",
        ONE,
        ROLE_COMPUTED,
        sn_source,
        total_damage,
    )
    governing_damage = rows.add(
        f"governing-damage-bin-{trace_identity_token(item.governing_damage_bin)}",
        "Exact governing damage-bin identity",
        ONE,
        ROLE_COMPUTED,
        REPLAY_SOURCE,
        *damages,
    )
    max_yield = rows.add(
        "element-yield-utilisation", "Governing element yield utilisation",
        ONE, ROLE_COMPUTED, yield_source, *yields,
    )
    governing_yield = rows.add(
        f"governing-yield-bin-{trace_identity_token(item.governing_yield_bin)}",
        "Exact governing yield-bin identity",
        ONE,
        ROLE_COMPUTED,
        REPLAY_SOURCE,
        *yields,
    )
    converged = rows.add(
        "element-converged", "All element bins converged", ONE,
        ROLE_COMPUTED, REPLAY_SOURCE, *convergences,
    )
    status = rows.add(
        "element-status", "Element PASS or FAIL", ONE,
        ROLE_COMPUTED, VERDICT_SOURCE, total_damage, max_yield, converged,
    )
    final = rows.add(
        "ct-010-reinforcement-assessment-result",
        "CT-010a reinforcement assessment utilisation",
        ONE,
        ROLE_FINAL,
        VERDICT_SOURCE,
        normal,
        gamma_c_step,
        property_id,
        total_damage,
        damage_utilisation,
        governing_damage,
        max_yield,
        governing_yield,
        converged,
        status,
    )
    values.update({
        total_damage: item.damage,
        damage_utilisation: item.damage_utilisation,
        governing_damage: 1.0,
        max_yield: item.yield_utilisation,
        governing_yield: 1.0,
        converged: float(item.converged),
        status: float(item.passed),
        final: item.utilisation,
    })
    _number_equal(item.damage, sum(bin_item.damage for bin_item in item.bins),
                  "element damage")
    _number_equal(item.damage_utilisation, item.damage,
                  "element damage utilisation")
    damage_governing = max(item.bins, key=lambda row: row.damage)
    if item.governing_damage_bin != damage_governing.bin_name:
        raise TraceValidationError("governing damage-bin identity differs")
    expected_yield = max(bin_item.yield_utilisation for bin_item in item.bins)
    _number_equal(item.yield_utilisation, expected_yield,
                  "element yield utilisation")
    yield_governing = max(item.bins, key=lambda row: row.yield_utilisation)
    if item.governing_yield_bin != yield_governing.bin_name:
        raise TraceValidationError("governing yield-bin identity differs")
    _number_equal(item.utilisation, max(item.damage, item.yield_utilisation),
                  "element utilisation")
    expected_passed = bool(
        item.converged
        and item.damage <= 1.0
        and item.yield_utilisation <= 1.0
    )
    if type(item.passed) is not bool or item.passed != expected_passed:
        raise TraceValidationError("element verdict differs from proof")
    axes = context_axes(
        context,
        fatigue_spectrum=spectrum.spectrum_name,
        reinforcement_element=item.element_id,
        reinforcement_kind=item.kind,
        fatigue_detail=item.detail_id,
    )
    member_id = (
        f"reinforcement-{spectrum_index:02d}-{element_index:02d}-"
        f"{trace_identity_token(spectrum.spectrum_name)}-"
        f"{trace_identity_token(item.element_id)}"
    )
    plan = MemberPlan(
        member_id,
        (
            f"ct-010-{context_id(context)}-reinforcement-"
            f"{spectrum_index:02d}-{element_index:02d}-"
            f"{trace_identity_token(spectrum.spectrum_name)}-"
            f"{trace_identity_token(item.element_id)}"
        ),
        axes,
        tuple(rows.rows),
        FINAL_STATES,
    )
    calculation = _calculation(
        plan,
        values,
        title=(
            f"Reinforcement fatigue: {spectrum.spectrum_name} / "
            f"{item.element_id}"
        ),
        final_failed_reason=None if item.converged else _FAILED_REASON,
        assumptions=(
            "Reinforcement damage and proof-stress checks are independent "
            "per spectrum and solver element.",
        ),
    )
    return plan, calculation


def _output_evidence(
    inp: Mapping[str, Any],
    spectra: tuple[FatigueSpectrumResult, ...],
    context: Mapping[str, Any],
) -> tuple[MemberPlan, TraceCalculation]:
    rows = StepRows()
    values: dict[str, Any] = {}
    normal = _input_steps(rows, values, inp, success=True)
    gamma_s, gamma_ff, gamma_c = _factor_steps(rows, values, inp)
    assessment_steps = []
    summary_identity_steps = []
    all_results = []
    for spectrum_index, spectrum in enumerate(spectra):
        spectrum_steps = []
        for element_index, item in enumerate(spectrum.reinforcement):
            step_id = rows.add(
                (
                    f"assessment-{spectrum_index:02d}-{element_index:02d}-"
                    f"{trace_identity_token(spectrum.spectrum_name)}-"
                    f"{trace_identity_token(item.element_id)}"
                ),
                "Retained reinforcement assessment utilisation",
                ONE,
                ROLE_COMPUTED,
                REPLAY_SOURCE,
                normal,
            )
            values[step_id] = item.utilisation
            assessment_steps.append(step_id)
            spectrum_steps.append(step_id)
            all_results.append(item)
        if not spectrum.reinforcement:
            raise TraceValidationError(
                "reinforcement spectrum needs at least one assessment"
            )
        governing_item = max(
            spectrum.reinforcement,
            key=lambda result: result.utilisation,
        )
        if spectrum.governing_reinforcement_id != governing_item.element_id:
            raise TraceValidationError(
                "governing reinforcement identity differs from proof"
            )
        governing_identity = rows.add(
            (
                f"spectrum-{spectrum_index:02d}-governing-reinforcement-"
                f"{trace_identity_token(spectrum.governing_reinforcement_id)}"
            ),
            "Exact governing reinforcement identity",
            ONE,
            ROLE_COMPUTED,
            VERDICT_SOURCE,
            *spectrum_steps,
        )
        values[governing_identity] = 1.0
        summary_identity_steps.append(governing_identity)
    governing = rows.add(
        "governing-reinforcement-utilisation",
        "Governing reinforcement utilisation",
        ONE,
        ROLE_COMPUTED,
        VERDICT_SOURCE,
        *assessment_steps,
    )
    status = rows.add(
        "reinforcement-output-status",
        "Worst-first reinforcement output status",
        ONE,
        ROLE_COMPUTED,
        VERDICT_SOURCE,
        *assessment_steps,
    )
    final = rows.add(
        "ct-010-reinforcement-output-result",
        "CT-010a reinforcement output",
        ONE,
        ROLE_FINAL,
        VERDICT_SOURCE,
        normal,
        gamma_s,
        gamma_ff,
        gamma_c,
        *assessment_steps,
        *summary_identity_steps,
        governing,
        status,
    )
    if not all_results:
        raise TraceValidationError(
            "enabled reinforcement fatigue needs at least one assessment"
        )
    governing_value = max(item.utilisation for item in all_results)
    passed = all(item.passed for item in all_results)
    converged = all(item.converged for item in all_results)
    values.update({
        governing: governing_value,
        status: float(passed),
        final: governing_value,
    })
    plan = MemberPlan(
        OUTPUT_MEMBER_ID,
        f"ct-010-{context_id(context)}-reinforcement-output",
        context_axes(
            context,
            fatigue_branch="reinforcement-output",
            assessment_count=str(len(all_results)),
        ),
        tuple(rows.rows),
        FINAL_STATES,
    )
    return plan, _calculation(
        plan,
        values,
        title="Reinforcement fatigue output",
        final_failed_reason=None if converged else _FAILED_REASON,
    )


def _invalid_evidence(
    inp: Mapping[str, Any],
    candidate: Mapping[str, Any],
    context: Mapping[str, Any],
) -> tuple[MemberPlan, TraceCalculation]:
    rows = StepRows()
    values: dict[str, Any] = {}
    normal = _input_steps(rows, values, inp, success=False)
    output_identity = rows.add(
        f"invalid-output-{_digest(candidate)}",
        "Exact retained invalid fatigue output identity",
        ONE,
        ROLE_COMPUTED,
        REPLAY_SOURCE,
        normal,
    )
    values[output_identity] = 1.0
    error_steps = []
    for index, error in enumerate(candidate["errors"]):
        step_id = rows.add(
            f"error-{index:02d}-{trace_identity_token(error)}",
            "Retained fatigue invalid error",
            ONE,
            ROLE_COMPUTED,
            REPLAY_SOURCE,
            output_identity,
        )
        values[step_id] = 1.0
        error_steps.append(step_id)
    final = rows.add(
        "ct-010-invalid-result",
        "CT-010 invalid fatigue state",
        ONE,
        ROLE_FINAL,
        VERDICT_SOURCE,
        normal,
        output_identity,
        *error_steps,
    )
    values[final] = 0.0
    plan = MemberPlan(
        INVALID_MEMBER_ID,
        f"ct-010-{context_id(context)}-invalid",
        context_axes(
            context,
            fatigue_branch="invalid",
            error_count=str(len(error_steps)),
        ),
        tuple(rows.rows),
        frozenset({RESULT_FAILED}),
    )
    reason = "Retained fatigue invalid result."
    if candidate["errors"]:
        reason += " " + " | ".join(candidate["errors"])
    return plan, _calculation(
        plan,
        values,
        title="Invalid fatigue input",
        final_failed_reason=reason,
    )


def _candidate(out: Mapping[str, Any]) -> Any:
    out = _mapping(out, "retained result mapping")
    return out.get("fatigue")


def _expected_bundle(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any],
) -> TraceBundle | None:
    candidate = _candidate(out)
    enabled = inp.get("fatigue_on")
    if type(enabled) is bool and not enabled:
        if candidate is not None:
            raise TraceValidationError(
                "disabled CT-010 fatigue input cannot carry a candidate"
            )
        return None
    if candidate is None:
        if enabled is None:
            return None
        raise TraceValidationError(
            "active or invalid CT-010 fatigue input needs a candidate"
        )
    candidate_mapping = _mapping(candidate, "candidate fatigue result")
    if "valid" in candidate_mapping:
        expected_invalid = _validate_invalid(candidate_mapping, inp)
        plan, calculation = _invalid_evidence(
            inp, expected_invalid, context
        )
        plans = (plan,)
        calculations = (calculation,)
    else:
        if type(enabled) is not bool or not enabled:
            raise TraceValidationError(
                "successful fatigue result requires fatigue_on=True"
            )
        check_steel = inp.get("fatigue_check_steel")
        if type(check_steel) is not bool:
            raise TraceValidationError(
                "fatigue_check_steel must retain Boolean type"
            )
        if not check_steel:
            # A valid concrete-only result is intentionally outside CT-010a.
            return None
        analysis = _analysis_module()
        expected = analysis.run_analysis(inp)
        _validate_success(candidate_mapping, expected)
        prepared = analysis.prepare(inp)
        properties = {
            item.element_id: item for item in prepared.reinforcement
        }
        plans_list = []
        calculations_list = []
        spectra = tuple(expected["spectra"])
        for spectrum_index, spectrum in enumerate(spectra):
            for element_index, item in enumerate(spectrum.reinforcement):
                if item.element_id not in properties:
                    raise TraceValidationError(
                        "reinforcement result has no resolved properties"
                    )
                plan, calculation = _element_evidence(
                    inp,
                    spectrum,
                    item,
                    properties[item.element_id],
                    spectrum_index,
                    element_index,
                    context,
                )
                plans_list.append(plan)
                calculations_list.append(calculation)
        output_plan, output_calculation = _output_evidence(
            inp, spectra, context
        )
        plans_list.append(output_plan)
        calculations_list.append(output_calculation)
        plans = tuple(plans_list)
        calculations = tuple(calculations_list)
    bundle = create_bundle(
        input_sha256=input_sha256,
        result_sha256=result_sha256,
        calculations=calculations,
    )
    audit_trace_registry(bundle, expected_registry(plans))
    return bundle


def build_fatigue_trace_family(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle | None:
    """Build and seal the applicable CT-010a trace family."""

    try:
        return _expected_bundle(
            _mapping(inp, "fatigue input mapping"),
            _mapping(out, "retained result mapping"),
            input_sha256,
            result_sha256,
            {} if context is None else _mapping(context, "trace context"),
        )
    except TraceValidationError:
        raise
    except (
        ArithmeticError,
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise TraceValidationError(
            f"invalid CT-010a fatigue evidence: {exc}"
        ) from exc


def validate_fatigue_trace_family(
    bundle: TraceBundle | dict[str, Any] | None,
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle | None:
    """Reject stale or coherently resealed CT-010a graph/value tampering."""

    expected = build_fatigue_trace_family(
        inp,
        out,
        input_sha256=input_sha256,
        result_sha256=result_sha256,
        context=context,
    )
    if expected is None:
        if bundle is not None:
            raise TraceValidationError(
                "inapplicable CT-010a input cannot carry a trace"
            )
        return None
    candidate = validate_bundle(
        bundle,
        expected_input_sha256=input_sha256,
        expected_result_sha256=result_sha256,
    )
    if candidate.to_dict() != expected.to_dict():
        raise TraceValidationError(
            "CT-010a trace differs from authoritative input replay"
        )
    return candidate
