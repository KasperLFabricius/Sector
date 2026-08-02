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
    ALL_FINAL_STATES,
    BOUNDARY,
    COVERAGE_ID,
    CYCLES,
    ELASTIC,
    INPUT,
    INVALID_KEYS,
    METHOD_ID,
    MPA,
    ONE,
    RAW_CONTROLS,
    SUCCESS_KEYS,
    VERDICT,
    MemberSpec,
    NodeSpec,
    code_sources,
    registry_for,
)
from .section_trace_blocks import context_axes, context_id
from .trace_registry import audit_trace_registry


_FAILED = (
    "The retained reinforcement-fatigue solve did not converge; no finite "
    "assessment result is asserted."
)
_UNDEFINED = (
    "The retained reinforcement-fatigue value is undefined; no numerical "
    "substitute is published."
)
_UNBOUNDED = (
    "The retained reinforcement-fatigue value is unbounded; its signed state "
    "is published without a finite substitute."
)


def _analysis():
    try:
        import fatigue_analysis
    except ImportError:  # pragma: no cover - direct sector-only import
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


def _plain_dict(value: Any, label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise TraceValidationError(f"{label} retained type must be dict")
    if any(type(key) is not str for key in value):
        raise TraceValidationError(f"{label} keys must be text")
    return value


def _items(value: Any, label: str) -> tuple[Any, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TraceValidationError(f"{label} must be an ordered sequence")
    return tuple(value)


def _float_same(first: float, second: float) -> bool:
    return first == second or (math.isnan(first) and math.isnan(second))


def _exact(actual: Any, expected: Any, label: str) -> None:
    if type(actual) is not type(expected):
        raise TraceValidationError(f"{label} retained type differs")
    if dataclasses.is_dataclass(expected) and not isinstance(expected, type):
        for field in dataclasses.fields(expected):
            _exact(
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
            _exact(actual[key], expected[key], f"{label}.{key}")
        return
    if isinstance(expected, (tuple, list)):
        if len(actual) != len(expected):
            raise TraceValidationError(f"{label} cardinality differs")
        for index, (item, wanted) in enumerate(zip(actual, expected)):
            _exact(item, wanted, f"{label}[{index}]")
        return
    if isinstance(expected, float):
        if not _float_same(actual, expected):
            raise TraceValidationError(f"{label} differs from replay")
        return
    if actual != expected:
        raise TraceValidationError(f"{label} differs from replay")


def _shape(actual: Any, expected: Any, label: str) -> None:
    """Compare recursive retained structure and types, but not leaf values."""

    if type(actual) is not type(expected):
        raise TraceValidationError(f"{label} retained type differs")
    if dataclasses.is_dataclass(expected) and not isinstance(expected, type):
        for field in dataclasses.fields(expected):
            _shape(
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
            _shape(actual[key], expected[key], f"{label}.{key}")
        return
    if isinstance(expected, (tuple, list)):
        if len(actual) != len(expected):
            raise TraceValidationError(f"{label} cardinality differs")
        for index, (item, wanted) in enumerate(zip(actual, expected)):
            _shape(item, wanted, f"{label}[{index}]")


def _check_state(actual: Any, expected: FatigueBinState, label: str) -> None:
    if type(actual) is not FatigueBinState:
        raise TraceValidationError(f"{label} retained type differs")
    concrete_fields = {
        "concrete_compression_long_mpa",
        "concrete_compression_total_mpa",
        "concrete_compression_design_total_mpa",
    }
    for field in dataclasses.fields(expected):
        compare = _shape if field.name in concrete_fields else _exact
        compare(
            getattr(actual, field.name),
            getattr(expected, field.name),
            f"{label}.{field.name}",
        )


def _check_spectrum(
    actual: Any,
    expected: FatigueSpectrumResult,
    *,
    concrete_enabled: bool,
    label: str,
) -> None:
    if type(actual) is not FatigueSpectrumResult:
        raise TraceValidationError(f"{label} retained type differs")
    _exact(actual.spectrum_name, expected.spectrum_name,
           f"{label}.spectrum_name")
    if type(actual.bins) is not tuple or len(actual.bins) != len(expected.bins):
        raise TraceValidationError(f"{label}.bins shape differs")
    for index, (state, wanted) in enumerate(zip(actual.bins, expected.bins)):
        _check_state(state, wanted, f"{label}.bins[{index}]")
    _exact(actual.reinforcement, expected.reinforcement,
           f"{label}.reinforcement")
    _exact(
        actual.governing_reinforcement_id,
        expected.governing_reinforcement_id,
        f"{label}.governing_reinforcement_id",
    )
    for name in (
        "concrete",
        "concrete_search",
        "fcd_fat_mpa",
        "governing_concrete_fibre",
        "concrete_method",
    ):
        _shape(getattr(actual, name), getattr(expected, name), f"{label}.{name}")
    for name in ("utilisation", "converged", "passed"):
        compare = _shape if concrete_enabled else _exact
        compare(getattr(actual, name), getattr(expected, name), f"{label}.{name}")


def _check_success(candidate: Any, expected: Mapping[str, Any]) -> dict[str, Any]:
    candidate = _plain_dict(candidate, "candidate successful fatigue result")
    if type(expected) is not dict:
        raise TraceValidationError("authoritative fatigue result type drifted")
    if tuple(candidate) != SUCCESS_KEYS or tuple(expected) != SUCCESS_KEYS:
        raise TraceValidationError("successful fatigue keys/order differ")
    concrete_enabled = expected["checks"]["concrete"]
    concrete_values = {"concrete_method", "concrete_parameters"}
    concrete_aggregates = {
        "governing_spectrum", "utilisation", "converged", "passed",
    }
    for key in SUCCESS_KEYS:
        if key == "spectra":
            if type(candidate[key]) is not type(expected[key]):
                raise TraceValidationError("candidate spectra retained type differs")
            if len(candidate[key]) != len(expected[key]):
                raise TraceValidationError("candidate spectra cardinality differs")
            for index, (item, wanted) in enumerate(
                zip(candidate[key], expected[key])
            ):
                _check_spectrum(
                    item,
                    wanted,
                    concrete_enabled=concrete_enabled,
                    label=f"candidate.spectra[{index}]",
                )
        elif key == "calculation_references":
            actual_refs = candidate[key]
            wanted_refs = expected[key]
            if type(actual_refs) is not type(wanted_refs):
                raise TraceValidationError(
                    "calculation references retained type differs"
                )
            if tuple(actual_refs) != tuple(wanted_refs):
                raise TraceValidationError(
                    "calculation reference keys/order differ"
                )
            for name in wanted_refs:
                compare = _shape if name == "concrete" else _exact
                compare(
                    actual_refs[name],
                    wanted_refs[name],
                    f"candidate.calculation_references.{name}",
                )
        elif key in concrete_values or (
            concrete_enabled and key in concrete_aggregates
        ):
            _shape(candidate[key], expected[key], f"candidate.{key}")
        else:
            _exact(candidate[key], expected[key], f"candidate.{key}")
    return candidate


def _check_invalid(candidate: Any, inp: Mapping[str, Any]) -> dict[str, Any]:
    candidate = _plain_dict(candidate, "candidate invalid fatigue result")
    if tuple(candidate) != INVALID_KEYS:
        raise TraceValidationError("invalid fatigue keys/order differ")
    if type(candidate["valid"]) is not bool or candidate["valid"] is not False:
        raise TraceValidationError("invalid fatigue result must retain valid=False")
    errors = _items(candidate["errors"], "candidate invalid errors")
    if any(type(error) is not str for error in errors):
        raise TraceValidationError("candidate invalid errors must be text")
    expected = _analysis().invalid_result(inp, errors=errors)
    if tuple(expected) != INVALID_KEYS:
        raise TraceValidationError("authoritative invalid inventory drifted")
    _exact(candidate, expected, "candidate invalid fatigue result")
    return candidate


def _identity(value: Any) -> Any:
    kind = f"{type(value).__module__}.{type(value).__qualname__}"
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return [
            "dataclass",
            kind,
            [
                [field.name, _identity(getattr(value, field.name))]
                for field in dataclasses.fields(value)
            ],
        ]
    if isinstance(value, np.ndarray):
        return [
            "ndarray",
            kind,
            str(value.dtype),
            list(value.shape),
            _identity(value.tolist()),
        ]
    if kind == "pandas.core.frame.DataFrame":
        return [
            "dataframe",
            kind,
            _identity(tuple(value.columns)),
            _identity(tuple(value.index)),
            _identity(tuple(str(dtype) for dtype in value.dtypes)),
            _identity(tuple(tuple(row) for row in value.itertuples(
                index=False, name=None
            ))),
        ]
    if isinstance(value, Mapping):
        return [
            "mapping",
            kind,
            [[_identity(key), _identity(item)] for key, item in value.items()],
        ]
    if isinstance(value, (tuple, list)):
        return ["sequence", kind, [_identity(item) for item in value]]
    if isinstance(value, float):
        if math.isnan(value):
            body = "nan"
        elif math.isinf(value):
            body = "+inf" if value > 0.0 else "-inf"
        else:
            body = value.hex()
        return ["float", kind, body]
    if value is None or isinstance(value, (bool, int, str)):
        return ["scalar", kind, value]
    if hasattr(value, "__dict__"):
        return [
            "object",
            kind,
            [[name, _identity(item)] for name, item in vars(value).items()],
        ]
    return ["repr", kind, repr(value)]


def _fingerprint(value: Any) -> str:
    data = json.dumps(
        _identity(value),
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(data).hexdigest()


def _section_vector(section: Any) -> Any:
    """Return original section leaves without erasing retained scalar types."""

    if section is None:
        return None
    return (
        tuple(
            tuple((point[0], point[1]) for point in ring)
            for ring in section.concrete
        ),
        tuple((item.x, item.y, item.area) for item in section.bars),
        tuple((item.x, item.y, item.area) for item in section.tendons),
    )


def _identity_groups(inp: Mapping[str, Any], success: bool):
    absent = ("absent",)
    groups = [
        (
            f"raw-{key.replace('_', '-')}",
            ("present", inp[key]) if key in inp else absent,
        )
        for key in RAW_CONTROLS
    ]
    groups.extend((
        ("section-geometry", _section_vector(inp.get("section"))),
        ("bar-element-table", inp.get("bar_elements", absent)),
        ("tendon-element-table", inp.get("tendon_elements", absent)),
        ("bar-material-vector", inp.get("bar_materials", absent)),
        ("tendon-material-vector", inp.get("tendon_materials", absent)),
        ("concrete-material", inp.get("concrete", absent)),
        ("fatigue-detail-catalog", inp.get("fatigue_detail_catalog", absent)),
        ("mild-material-catalog", inp.get("mild_material_catalog", absent)),
        (
            "prestress-material-catalog",
            inp.get("prestress_material_catalog", absent),
        ),
        ("fatigue-basis", inp.get("fatigue_basis", absent)),
        ("fatigue-spectrum-table", inp.get("fatigue_spectrum_base", absent)),
    ))
    if success:
        groups.append(("analysis-signature", _analysis().analysis_signature(inp)))
    return tuple(groups)


class _Graph:
    def __init__(self) -> None:
        self.nodes: list[NodeSpec] = []
        self.values: dict[str, Any] = {}

    def add(
        self,
        step_id,
        title,
        unit,
        role,
        source,
        *dependencies,
        value=1.0,
    ):
        self.nodes.append(NodeSpec(
            step_id,
            title,
            unit,
            role,
            source,
            tuple(dependencies),
        ))
        self.values[step_id] = value
        return step_id

    def inputs(self, inp: Mapping[str, Any], success: bool) -> str:
        leaves = [
            self.add(
                f"{label}-{_fingerprint(identity)}",
                f"Exact retained {label.replace('-', ' ')} identity",
                ONE,
                ROLE_USER_INPUT,
                INPUT,
            )
            for label, identity in _identity_groups(inp, success)
        ]
        return self.add(
            "normalised-fatigue-inputs",
            "Closed normalised fatigue input identity",
            ONE,
            ROLE_COMPUTED,
            BOUNDARY,
            *leaves,
        )

    def factors(self, inp: Mapping[str, Any]):
        values = []
        for key, title in (
            ("fatigue_gamma_s", "Raw reinforcement material factor"),
            ("fatigue_gamma_ff", "Raw fatigue action factor"),
            ("fatigue_gamma_c", "Raw concrete material factor"),
        ):
            identity = ("present", inp[key]) if key in inp else ("absent",)
            values.append(self.add(
                f"factor-{key.replace('_', '-')}-{_fingerprint(identity)}",
                title,
                ONE,
                ROLE_USER_INPUT,
                INPUT,
            ))
        return tuple(values)


def _same_number(actual: Any, expected: float, label: str) -> None:
    wanted = float(expected)
    if type(actual) is not float or not _float_same(actual, wanted):
        raise TraceValidationError(f"{label} differs from independent proof")


def _damage(cycles: float, log_life: float) -> float:
    if math.isinf(log_life):
        return 0.0 if log_life > 0.0 else math.inf
    exponent = math.log10(cycles) - log_life
    if exponent > math.log10(sys.float_info.max):
        return math.inf
    if exponent < math.log10(sys.float_info.min * sys.float_info.epsilon):
        return 0.0
    return 10.0 ** exponent


def _yield(
    stress: float,
    prop: ReinforcementFatigueProperties,
    gamma_s: float,
):
    characteristic = (
        prop.fytk_mpa
        if stress >= 0.0
        else (
            prop.fyck_mpa
            if prop.fyck_mpa is not None
            else prop.fytk_mpa
        )
    )
    limit = float(characteristic) / gamma_s
    return limit, abs(stress) / limit


def _trace_result(value: Any, failed: str | None = None) -> TraceResult:
    if failed is not None:
        return TraceResult(RESULT_FAILED, None, failed)
    numeric = float(value)
    if math.isnan(numeric):
        return TraceResult(RESULT_UNDEFINED, None, _UNDEFINED)
    if math.isinf(numeric):
        state = (
            RESULT_POSITIVE_INFINITY
            if numeric > 0.0
            else RESULT_NEGATIVE_INFINITY
        )
        return TraceResult(state, None, _UNBOUNDED)
    return TraceResult(RESULT_FINITE, numeric)


def _calculation(
    member: MemberSpec,
    graph: _Graph,
    title: str,
    *,
    failed: str | None,
) -> TraceCalculation:
    units = {node.step_id: node.unit for node in member.nodes}
    steps = []
    for node in member.nodes:
        is_final = node.role == ROLE_FINAL
        result = _trace_result(
            graph.values[node.step_id],
            failed if is_final else None,
        )
        state = result.state
        substituted = f"{node.step_id} = {state}"
        if result.value is not None:
            substituted = (
                f"{node.step_id} = {result.value:.17g} {node.unit.symbol}"
            )
        steps.append(TraceStep(
            node.step_id,
            node.title,
            tuple(TraceDependency(item, units[item])
                  for item in node.dependencies),
            node.role,
            node.source,
            node.step_id,
            node.unit,
            f"Bind or independently derive {node.title.lower()}",
            substituted,
            result,
        ))
    return TraceCalculation(
        member.calculation_id,
        COVERAGE_ID,
        title,
        METHOD_ID,
        member.axes,
        steps[-1].step_id,
        tuple(steps),
    )


def _state_vectors(state: FatigueBinState, element_index: int):
    fatigue_total = (
        state.bar_stress_fatigue_total_mpa
        or state.bar_stress_total_mpa
    )
    design_total = (
        state.bar_stress_fatigue_design_total_mpa
        or fatigue_total
    )
    try:
        return (
            float(state.bar_stress_long_mpa[element_index]),
            float(fatigue_total[element_index]),
            float(design_total[element_index]),
            float(state.bar_stress_total_mpa[element_index]),
        )
    except IndexError as exc:
        raise TraceValidationError(
            "matched Elastic state does not contain the assessment element"
        ) from exc


def _bin_nodes(
    graph: _Graph,
    prefix: str,
    assessment: ReinforcementBinResult,
    state: FatigueBinState,
    prop: ReinforcementFatigueProperties,
    element_index: int,
    normal: str,
    gamma_s_id: str,
    gamma_ff_id: str,
    gamma_s: float,
    gamma_ff: float,
    sn_source,
    yield_source,
):
    if type(state.converged) is not bool:
        raise TraceValidationError("matched Elastic convergence must be Boolean")
    if type(assessment.converged) is not bool:
        raise TraceValidationError("assessment convergence must be Boolean")
    if assessment.converged != state.converged:
        raise TraceValidationError(
            f"{prefix} convergence differs from matched Elastic state"
        )
    _same_number(assessment.cycles, state.cycles, f"{prefix} cycles")
    if type(assessment.bond_method) is not str:
        raise TraceValidationError(f"{prefix} bond method must be text")
    if assessment.bond_method != state.bond_method:
        raise TraceValidationError(
            f"{prefix} bond method differs from matched Elastic state"
        )
    if not _float_same(float(state.design_action_factor), gamma_ff):
        raise TraceValidationError(
            f"{prefix} design factor differs from retained gamma_Ff"
        )

    long_stress, total_stress, design_total, perfect_total = _state_vectors(
        state, element_index
    )
    perfect_range = abs(perfect_total - long_stress)
    stress_range = abs(total_stress - long_stress)
    design_range = abs(design_total - long_stress)
    if perfect_range > 0.0:
        bond_factor = stress_range / perfect_range
    elif stress_range > 0.0:
        bond_factor = math.inf
    else:
        bond_factor = 1.0

    comparisons = (
        (assessment.stress_long_mpa, long_stress, "long stress"),
        (assessment.stress_total_mpa, total_stress, "fatigue-total stress"),
        (
            assessment.stress_total_design_mpa,
            design_total,
            "design fatigue-total stress",
        ),
        (
            assessment.stress_total_elastic_mpa,
            perfect_total,
            "perfect-bond stress",
        ),
        (assessment.stress_range_mpa, stress_range, "stress range"),
        (
            assessment.stress_range_elastic_mpa,
            perfect_range,
            "perfect-bond range",
        ),
        (assessment.bond_adjustment, bond_factor, "bond adjustment"),
        (
            assessment.design_stress_range_mpa,
            design_range,
            "design stress range",
        ),
    )
    for actual, wanted, label in comparisons:
        _same_number(actual, wanted, f"{prefix} {label}")

    bin_identity = graph.add(
        f"{prefix}-identity-{_fingerprint((state.name, state.description))}",
        "Exact fatigue-bin name and description identity",
        ONE,
        ROLE_COMPUTED,
        ELASTIC,
        normal,
    )
    cycles = graph.add(
        f"{prefix}-cycles",
        "Retained applied cycles",
        CYCLES,
        ROLE_COMPUTED,
        ELASTIC,
        normal,
        bin_identity,
        value=float(state.cycles),
    )
    convergence = graph.add(
        f"{prefix}-converged",
        "Matched Elastic-bin convergence",
        ONE,
        ROLE_COMPUTED,
        ELASTIC,
        normal,
        bin_identity,
        value=float(state.converged),
    )
    bond_identity = graph.add(
        f"{prefix}-bond-method-{_fingerprint(state.bond_method)}",
        "Exact retained bond-method identity",
        ONE,
        ROLE_COMPUTED,
        ELASTIC,
        normal,
        bin_identity,
    )
    long_id = graph.add(
        f"{prefix}-long-stress",
        "Matched long-term reinforcement stress",
        MPA,
        ROLE_COMPUTED,
        ELASTIC,
        normal,
        bin_identity,
        value=long_stress,
    )
    total_id = graph.add(
        f"{prefix}-fatigue-total-stress",
        "Matched bond-adjusted fatigue-total stress",
        MPA,
        ROLE_COMPUTED,
        ELASTIC,
        normal,
        bin_identity,
        value=total_stress,
    )
    design_id = graph.add(
        f"{prefix}-design-fatigue-total-stress",
        "Matched design fatigue-total stress",
        MPA,
        ROLE_COMPUTED,
        ELASTIC,
        normal,
        bin_identity,
        gamma_ff_id,
        value=design_total,
    )
    perfect_id = graph.add(
        f"{prefix}-perfect-bond-total-stress",
        "Matched perfect-bond total stress",
        MPA,
        ROLE_COMPUTED,
        ELASTIC,
        normal,
        bin_identity,
        value=perfect_total,
    )
    range_id = graph.add(
        f"{prefix}-stress-range",
        "Bond-adjusted stress range",
        MPA,
        ROLE_COMPUTED,
        ELASTIC,
        total_id,
        long_id,
        bond_identity,
        value=stress_range,
    )
    perfect_range_id = graph.add(
        f"{prefix}-perfect-bond-range",
        "Perfect-bond stress range",
        MPA,
        ROLE_COMPUTED,
        ELASTIC,
        perfect_id,
        long_id,
        value=perfect_range,
    )
    bond_factor_id = graph.add(
        f"{prefix}-bond-adjustment",
        "Bond adjustment",
        ONE,
        ROLE_COMPUTED,
        ELASTIC,
        range_id,
        perfect_range_id,
        bond_identity,
        value=bond_factor,
    )
    design_range_id = graph.add(
        f"{prefix}-design-stress-range",
        "Design stress range",
        MPA,
        ROLE_COMPUTED,
        ELASTIC,
        design_id,
        long_id,
        range_id,
        bond_factor_id,
        gamma_ff_id,
        value=design_range,
    )

    reference_value = float(prop.delta_sigma_rsk_mpa)
    design_reference_value = reference_value / gamma_s
    _same_number(
        assessment.delta_sigma_rsk_mpa,
        reference_value,
        f"{prefix} characteristic reference",
    )
    _same_number(
        assessment.delta_sigma_rd_mpa,
        design_reference_value,
        f"{prefix} design reference",
    )
    reference = graph.add(
        f"{prefix}-delta-sigma-rsk",
        "Characteristic reference range",
        MPA,
        ROLE_COMPUTED,
        sn_source,
        normal,
        value=reference_value,
    )
    design_reference = graph.add(
        f"{prefix}-delta-sigma-rd",
        "Design reference range",
        MPA,
        ROLE_COMPUTED,
        sn_source,
        reference,
        gamma_s_id,
        value=design_reference_value,
    )
    life = steel_fatigue_life(
        design_range,
        n_star=prop.n_star,
        k1=prop.k1,
        k2=prop.k2,
        delta_sigma_rsk_mpa=prop.delta_sigma_rsk_mpa,
        gamma_s=gamma_s,
        gamma_ff=1.0,
    )
    for actual, wanted, label in (
        (assessment.sn_exponent, life.exponent, "S-N exponent"),
        (assessment.log10_cycles_to_failure, life.log10_cycles, "log life"),
        (assessment.cycles_to_failure, life.cycles, "life"),
    ):
        _same_number(actual, wanted, f"{prefix} {label}")
    exponent = graph.add(
        f"{prefix}-sn-exponent",
        "Selected S-N exponent",
        ONE,
        ROLE_COMPUTED,
        sn_source,
        design_range_id,
        design_reference,
        value=life.exponent,
    )
    log_life = graph.add(
        f"{prefix}-log10-cycles-to-failure",
        "Logarithmic fatigue life",
        ONE,
        ROLE_COMPUTED,
        sn_source,
        design_range_id,
        design_reference,
        exponent,
        gamma_s_id,
        value=life.log10_cycles,
    )
    life_id = graph.add(
        f"{prefix}-cycles-to-failure",
        "Cycles to failure",
        CYCLES,
        ROLE_COMPUTED,
        sn_source,
        log_life,
        value=life.cycles,
    )
    damage_value = _damage(float(state.cycles), life.log10_cycles)
    _same_number(assessment.damage, damage_value, f"{prefix} damage")
    damage = graph.add(
        f"{prefix}-damage",
        "Palmgren-Miner bin damage",
        ONE,
        ROLE_COMPUTED,
        sn_source,
        cycles,
        log_life,
        life_id,
        value=damage_value,
    )

    long_limit, long_util = _yield(long_stress, prop, gamma_s)
    total_limit, total_util = _yield(design_total, prop, gamma_s)
    if total_util >= long_util:
        governing_stress_value = design_total
        yield_limit_value = total_limit
        yield_utilisation_value = total_util
    else:
        governing_stress_value = long_stress
        yield_limit_value = long_limit
        yield_utilisation_value = long_util
    for actual, wanted, label in (
        (
            assessment.governing_stress_mpa,
            governing_stress_value,
            "governing stress",
        ),
        (assessment.yield_limit_mpa, yield_limit_value, "yield limit"),
        (
            assessment.yield_utilisation,
            yield_utilisation_value,
            "yield utilisation",
        ),
    ):
        _same_number(actual, wanted, f"{prefix} {label}")
    governing_stress = graph.add(
        f"{prefix}-governing-stress",
        "Governing absolute stress",
        MPA,
        ROLE_COMPUTED,
        yield_source,
        long_id,
        design_id,
        value=governing_stress_value,
    )
    yield_limit = graph.add(
        f"{prefix}-yield-limit",
        "Design proof-stress limit",
        MPA,
        ROLE_COMPUTED,
        yield_source,
        governing_stress,
        gamma_s_id,
        value=yield_limit_value,
    )
    yield_utilisation = graph.add(
        f"{prefix}-yield-utilisation",
        "Yield utilisation",
        ONE,
        ROLE_COMPUTED,
        yield_source,
        governing_stress,
        yield_limit,
        value=yield_utilisation_value,
    )
    return damage, yield_utilisation, convergence


def _assessment_member(
    inp,
    spectrum: FatigueSpectrumResult,
    assessment: ReinforcementFatigueResult,
    prop: ReinforcementFatigueProperties,
    spectrum_index: int,
    element_index: int,
    context,
):
    if (
        assessment.element_id != prop.element_id
        or assessment.kind != prop.kind
        or assessment.detail_id != prop.detail_id
    ):
        raise TraceValidationError(
            "reinforcement assessment identity differs from resolved properties"
        )
    _same_number(
        assessment.diameter_mm,
        prop.diameter_mm,
        "reinforcement diameter",
    )
    graph = _Graph()
    normal = graph.inputs(inp, True)
    gamma_s_id, gamma_ff_id, gamma_c_id = graph.factors(inp)
    gamma_s = float(inp["fatigue_gamma_s"])
    gamma_ff = float(inp["fatigue_gamma_ff"])
    property_identity = graph.add(
        f"reinforcement-property-{_fingerprint(prop)}",
        "Exact resolved reinforcement fatigue properties",
        ONE,
        ROLE_COMPUTED,
        BOUNDARY,
        normal,
    )
    sn_source, yield_source = code_sources(_analysis().prepare(inp).edition)
    if len(assessment.bins) != len(spectrum.bins):
        raise TraceValidationError(
            "assessment bin cardinality differs from matched Elastic spectrum"
        )
    damages = []
    yields = []
    convergences = []
    for bin_index, (item, state) in enumerate(
        zip(assessment.bins, spectrum.bins)
    ):
        if item.bin_name != state.name:
            raise TraceValidationError(
                "assessment bin identity differs from matched Elastic spectrum"
            )
        prefix = f"bin-{bin_index:02d}-{trace_identity_token(state.name)}"
        damage, yield_util, convergence = _bin_nodes(
            graph,
            prefix,
            item,
            state,
            prop,
            element_index,
            normal,
            gamma_s_id,
            gamma_ff_id,
            gamma_s,
            gamma_ff,
            sn_source,
            yield_source,
        )
        damages.append(damage)
        yields.append(yield_util)
        convergences.append(convergence)

    total_damage = sum(item.damage for item in assessment.bins)
    max_yield = max(item.yield_utilisation for item in assessment.bins)
    _same_number(assessment.damage, total_damage, "element total damage")
    _same_number(
        assessment.damage_utilisation,
        total_damage,
        "element damage utilisation",
    )
    _same_number(
        assessment.yield_utilisation,
        max_yield,
        "element yield utilisation",
    )
    damage_row = max(assessment.bins, key=lambda item: item.damage)
    yield_row = max(
        assessment.bins,
        key=lambda item: item.yield_utilisation,
    )
    if assessment.governing_damage_bin != damage_row.bin_name:
        raise TraceValidationError("governing damage-bin identity differs")
    if assessment.governing_yield_bin != yield_row.bin_name:
        raise TraceValidationError("governing yield-bin identity differs")
    damage_total = graph.add(
        "element-total-damage",
        "Element Palmgren-Miner damage",
        ONE,
        ROLE_COMPUTED,
        sn_source,
        *damages,
        value=total_damage,
    )
    damage_utilisation = graph.add(
        "element-damage-utilisation",
        "Element damage utilisation",
        ONE,
        ROLE_COMPUTED,
        sn_source,
        damage_total,
        value=assessment.damage_utilisation,
    )
    damage_identity = graph.add(
        f"governing-damage-bin-{trace_identity_token(damage_row.bin_name)}",
        "Exact governing damage-bin identity",
        ONE,
        ROLE_COMPUTED,
        VERDICT,
        *damages,
    )
    yield_max = graph.add(
        "element-yield-utilisation",
        "Element yield utilisation",
        ONE,
        ROLE_COMPUTED,
        yield_source,
        *yields,
        value=max_yield,
    )
    yield_identity = graph.add(
        f"governing-yield-bin-{trace_identity_token(yield_row.bin_name)}",
        "Exact governing yield-bin identity",
        ONE,
        ROLE_COMPUTED,
        VERDICT,
        *yields,
    )
    converged = all(item.converged for item in assessment.bins)
    if type(assessment.converged) is not bool or assessment.converged != converged:
        raise TraceValidationError("element convergence differs from proof")
    convergence = graph.add(
        "element-converged",
        "All matched Elastic bins converged",
        ONE,
        ROLE_COMPUTED,
        ELASTIC,
        *convergences,
        value=float(converged),
    )
    utilisation = max(total_damage, max_yield)
    _same_number(assessment.utilisation, utilisation, "element utilisation")
    passed = bool(converged and total_damage <= 1.0 and max_yield <= 1.0)
    if type(assessment.passed) is not bool or assessment.passed != passed:
        raise TraceValidationError("element verdict differs from proof")
    status = graph.add(
        "element-status",
        "Element PASS or FAIL",
        ONE,
        ROLE_COMPUTED,
        VERDICT,
        damage_total,
        yield_max,
        convergence,
        value=float(passed),
    )
    graph.add(
        "ct-010-reinforcement-assessment-result",
        "CT-010a reinforcement assessment utilisation",
        ONE,
        ROLE_FINAL,
        VERDICT,
        normal,
        gamma_s_id,
        gamma_ff_id,
        gamma_c_id,
        property_identity,
        damage_total,
        damage_utilisation,
        damage_identity,
        yield_max,
        yield_identity,
        convergence,
        status,
        value=utilisation,
    )
    member = MemberSpec(
        (
            f"reinforcement-{spectrum_index:02d}-{element_index:02d}-"
            f"{trace_identity_token(spectrum.spectrum_name)}-"
            f"{trace_identity_token(assessment.element_id)}"
        ),
        (
            f"ct-010-{context_id(context)}-reinforcement-"
            f"{spectrum_index:02d}-{element_index:02d}-"
            f"{trace_identity_token(spectrum.spectrum_name)}-"
            f"{trace_identity_token(assessment.element_id)}"
        ),
        context_axes(
            context,
            fatigue_spectrum=spectrum.spectrum_name,
            reinforcement_element=assessment.element_id,
            reinforcement_kind=assessment.kind,
            fatigue_detail=assessment.detail_id,
        ),
        tuple(graph.nodes),
        ALL_FINAL_STATES,
    )
    return member, _calculation(
        member,
        graph,
        (
            f"Reinforcement fatigue: {spectrum.spectrum_name} / "
            f"{assessment.element_id}"
        ),
        failed=None if converged else _FAILED,
    )


def _aggregate_member(inp, spectra, context):
    graph = _Graph()
    normal = graph.inputs(inp, True)
    gamma_s, gamma_ff, gamma_c = graph.factors(inp)
    assessment_ids = []
    governing_ids = []
    results = []
    for spectrum_index, spectrum in enumerate(spectra):
        spectrum_ids = []
        for element_index, item in enumerate(spectrum.reinforcement):
            step_id = graph.add(
                (
                    f"assessment-{spectrum_index:02d}-{element_index:02d}-"
                    f"{trace_identity_token(spectrum.spectrum_name)}-"
                    f"{trace_identity_token(item.element_id)}"
                ),
                "Retained reinforcement assessment utilisation",
                ONE,
                ROLE_COMPUTED,
                VERDICT,
                normal,
                value=item.utilisation,
            )
            spectrum_ids.append(step_id)
            assessment_ids.append(step_id)
            results.append(item)
        if not spectrum.reinforcement:
            raise TraceValidationError(
                "reinforcement spectrum needs at least one assessment"
            )
        governing = max(
            spectrum.reinforcement,
            key=lambda item: item.utilisation,
        )
        if spectrum.governing_reinforcement_id != governing.element_id:
            raise TraceValidationError(
                "spectrum governing reinforcement identity differs"
            )
        governing_ids.append(graph.add(
            (
                f"spectrum-{spectrum_index:02d}-governing-reinforcement-"
                f"{trace_identity_token(governing.element_id)}"
            ),
            "Exact governing reinforcement identity",
            ONE,
            ROLE_COMPUTED,
            VERDICT,
            *spectrum_ids,
        ))
    if not results:
        raise TraceValidationError("reinforcement output needs assessments")
    utilisation = max(item.utilisation for item in results)
    passed = all(item.passed for item in results)
    converged = all(item.converged for item in results)
    governing = graph.add(
        "governing-reinforcement-utilisation",
        "Governing reinforcement utilisation",
        ONE,
        ROLE_COMPUTED,
        VERDICT,
        *assessment_ids,
        value=utilisation,
    )
    status = graph.add(
        "reinforcement-output-status",
        "Worst-first reinforcement status",
        ONE,
        ROLE_COMPUTED,
        VERDICT,
        *assessment_ids,
        value=float(passed),
    )
    graph.add(
        "ct-010-reinforcement-output-result",
        "CT-010a reinforcement output",
        ONE,
        ROLE_FINAL,
        VERDICT,
        normal,
        gamma_s,
        gamma_ff,
        gamma_c,
        *assessment_ids,
        *governing_ids,
        governing,
        status,
        value=utilisation,
    )
    member = MemberSpec(
        "reinforcement-output",
        f"ct-010-{context_id(context)}-reinforcement-output",
        context_axes(
            context,
            fatigue_branch="reinforcement-output",
            assessment_count=str(len(results)),
        ),
        tuple(graph.nodes),
        ALL_FINAL_STATES,
    )
    return member, _calculation(
        member,
        graph,
        "Reinforcement fatigue output",
        failed=None if converged else _FAILED,
    )


def _invalid_member(inp, candidate, context):
    graph = _Graph()
    normal = graph.inputs(inp, False)
    payload = graph.add(
        f"invalid-output-{_fingerprint(candidate)}",
        "Exact retained invalid fatigue output identity",
        ONE,
        ROLE_COMPUTED,
        ELASTIC,
        normal,
    )
    errors = [
        graph.add(
            f"error-{index:02d}-{trace_identity_token(error)}",
            "Retained invalid fatigue error",
            ONE,
            ROLE_COMPUTED,
            ELASTIC,
            payload,
        )
        for index, error in enumerate(candidate["errors"])
    ]
    graph.add(
        "ct-010-invalid-result",
        "CT-010 invalid fatigue state",
        ONE,
        ROLE_FINAL,
        VERDICT,
        normal,
        payload,
        *errors,
        value=0.0,
    )
    member = MemberSpec(
        "invalid",
        f"ct-010-{context_id(context)}-invalid",
        context_axes(
            context,
            fatigue_branch="invalid",
            error_count=str(len(errors)),
        ),
        tuple(graph.nodes),
        frozenset({RESULT_FAILED}),
    )
    reason = "Retained fatigue invalid result."
    if candidate["errors"]:
        reason += " " + " | ".join(candidate["errors"])
    return member, _calculation(
        member,
        graph,
        "Invalid fatigue input",
        failed=reason,
    )


def _build_expected(inp, out, input_sha256, result_sha256, context):
    candidate = _mapping(out, "retained result mapping").get("fatigue")
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
    candidate = _plain_dict(candidate, "candidate fatigue result")
    if "valid" in candidate:
        retained = _check_invalid(candidate, inp)
        member, calculation = _invalid_member(inp, retained, context)
        members = (member,)
        calculations = (calculation,)
    else:
        if type(enabled) is not bool or not enabled:
            raise TraceValidationError(
                "successful fatigue result requires fatigue_on=True"
            )
        analysis = _analysis()
        expected = analysis.run_analysis(inp)
        _check_success(candidate, expected)
        check_steel = inp.get("fatigue_check_steel")
        if type(check_steel) is not bool:
            raise TraceValidationError(
                "fatigue_check_steel must retain Boolean type"
            )
        if not check_steel:
            return None
        prepared = analysis.prepare(inp)
        properties = {item.element_id: item for item in prepared.reinforcement}
        member_list = []
        calculation_list = []
        spectra = tuple(expected["spectra"])
        for spectrum_index, spectrum in enumerate(spectra):
            for element_index, assessment in enumerate(spectrum.reinforcement):
                prop = properties.get(assessment.element_id)
                if prop is None:
                    raise TraceValidationError(
                        "reinforcement assessment lacks resolved properties"
                    )
                member, calculation = _assessment_member(
                    inp,
                    spectrum,
                    assessment,
                    prop,
                    spectrum_index,
                    element_index,
                    context,
                )
                member_list.append(member)
                calculation_list.append(calculation)
        member, calculation = _aggregate_member(inp, spectra, context)
        member_list.append(member)
        calculation_list.append(calculation)
        members = tuple(member_list)
        calculations = tuple(calculation_list)
    bundle = create_bundle(
        input_sha256=input_sha256,
        result_sha256=result_sha256,
        calculations=calculations,
    )
    audit_trace_registry(bundle, registry_for(members))
    return bundle


def build_fatigue_trace_family(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle | None:
    """Build and seal the applicable CT-010a fatigue family."""

    try:
        return _build_expected(
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
    """Reject stale or coherently resealed CT-010a evidence."""

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
