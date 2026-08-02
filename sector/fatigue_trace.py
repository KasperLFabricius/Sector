"""Unpublished successful reinforcement-fatigue trace for CT-010a."""

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
    RESULT_FINITE, RESULT_NEGATIVE_INFINITY,
    RESULT_POSITIVE_INFINITY, RESULT_UNDEFINED, ROLE_COMPUTED, ROLE_FINAL,
    ROLE_USER_INPUT, TraceAxis, TraceBundle, TraceCalculation, TraceDependency,
    TraceResult, TraceStep, TraceValidationError, create_bundle,
    trace_identity_token, validate_bundle,
)
from .fatigue_trace_contract import (
    BOUNDARY, COVERAGE_ID, CYCLES, ELASTIC, INPUT, METHOD_ID, MPA,
    ONE, RAW_CONTROLS, SUCCESS_KEYS, VERDICT, MemberSpec, NodeSpec,
    code_sources, registry_for,
)
from .trace_registry import audit_trace_registry


_MISSING = object()
_CONCRETE_STATE_FIELDS = frozenset({
    "concrete_compression_long_mpa",
    "concrete_compression_total_mpa",
    "concrete_compression_design_total_mpa",
    "elastic_result",
    "design_elastic_result",
})
_CONCRETE_SPECTRUM_FIELDS = frozenset({
    "concrete", "concrete_search", "fcd_fat_mpa",
    "governing_concrete_fibre", "concrete_method",
})
_CONCRETE_TOP_FIELDS = frozenset({
    "concrete_method", "concrete_parameters", "t0_days",
})
_SHARED_SPECTRUM_FIELDS = frozenset({"utilisation", "converged", "passed"})
_SHARED_TOP_FIELDS = frozenset({
    "governing_spectrum", "utilisation", "converged", "passed",
})


def _analysis():
    """Load the retained app boundary without making app an installed package."""

    try:
        import fatigue_analysis
    except ImportError:  # pragma: no cover - sector-only import mode
        sys.path.insert(0, str(
            pathlib.Path(__file__).resolve().parent.parent / "app"))
        import fatigue_analysis
    return fatigue_analysis


def _fail(message: str) -> None:
    raise TraceValidationError(message)


def _same_scalar(actual: Any, expected: Any) -> bool:
    if type(actual) is not type(expected):
        return False
    if type(expected) is float:
        return (
            math.isnan(actual) and math.isnan(expected)
        ) or actual.hex() == expected.hex()
    if isinstance(expected, np.generic):
        return (
            actual.dtype == expected.dtype
            and _same_scalar(actual.item(), expected.item())
        )
    return actual == expected


def _exact(actual: Any, expected: Any, label: str) -> None:
    """Compare retained values without bool/number or container coercion."""

    if type(actual) is not type(expected):
        _fail(f"{label} retained type differs")
    if dataclasses.is_dataclass(expected) and not isinstance(expected, type):
        actual_fields = tuple(field.name for field in dataclasses.fields(actual))
        expected_fields = tuple(field.name for field in dataclasses.fields(expected))
        if actual_fields != expected_fields:
            _fail(f"{label} dataclass inventory differs")
        for field in expected_fields:
            _exact(getattr(actual, field), getattr(expected, field),
                   f"{label}.{field}")
        return
    if isinstance(expected, np.ndarray):
        if actual.dtype != expected.dtype or actual.shape != expected.shape:
            _fail(f"{label} array identity differs")
        if not np.array_equal(actual, expected, equal_nan=True):
            _fail(f"{label} array value differs")
        return
    if type(expected) is dict:
        if tuple(actual) != tuple(expected):
            _fail(f"{label} object inventory/order differs")
        for key in expected:
            if type(key) is not type(next(item for item in actual if item == key)):
                _fail(f"{label} key type differs")
            _exact(actual[key], expected[key], f"{label}.{key}")
        return
    if type(expected) in {list, tuple}:
        if len(actual) != len(expected):
            _fail(f"{label} cardinality differs")
        for index, (left, right) in enumerate(zip(actual, expected)):
            _exact(left, right, f"{label}[{index}]")
        return
    if not _same_scalar(actual, expected):
        _fail(f"{label} value differs")


def _shape(actual: Any, expected: Any, label: str) -> None:
    """Fence an excluded sibling's position, cardinality and retained types."""

    if type(actual) is not type(expected):
        _fail(f"{label} excluded sibling type differs")
    if dataclasses.is_dataclass(expected) and not isinstance(expected, type):
        fields = tuple(field.name for field in dataclasses.fields(expected))
        if tuple(field.name for field in dataclasses.fields(actual)) != fields:
            _fail(f"{label} excluded dataclass inventory differs")
        for field in fields:
            _shape(getattr(actual, field), getattr(expected, field),
                   f"{label}.{field}")
        return
    if isinstance(expected, np.ndarray):
        if actual.dtype != expected.dtype or actual.shape != expected.shape:
            _fail(f"{label} excluded array shape/type differs")
        return
    if type(expected) is dict:
        if tuple(actual) != tuple(expected):
            _fail(f"{label} excluded object inventory/order differs")
        for key in expected:
            _shape(actual[key], expected[key], f"{label}.{key}")
        return
    if type(expected) in {list, tuple}:
        if len(actual) != len(expected):
            _fail(f"{label} excluded cardinality differs")
        for index, (left, right) in enumerate(zip(actual, expected)):
            _shape(left, right, f"{label}[{index}]")


def _check_state(actual: Any, expected: Any, label: str) -> None:
    if type(actual) is not type(expected) or not dataclasses.is_dataclass(expected):
        _fail(f"{label} fatigue-bin state type differs")
    fields = tuple(field.name for field in dataclasses.fields(expected))
    if tuple(field.name for field in dataclasses.fields(actual)) != fields:
        _fail(f"{label} fatigue-bin state inventory differs")
    for field in fields:
        checker = _shape if field in _CONCRETE_STATE_FIELDS else _exact
        checker(getattr(actual, field), getattr(expected, field),
                f"{label}.{field}")


def _check_spectrum(
    actual: Any, expected: Any, label: str, *, concrete_enabled: bool,
) -> None:
    if type(actual) is not type(expected) or not dataclasses.is_dataclass(expected):
        _fail(f"{label} spectrum type differs")
    fields = tuple(field.name for field in dataclasses.fields(expected))
    if tuple(field.name for field in dataclasses.fields(actual)) != fields:
        _fail(f"{label} spectrum inventory differs")
    for field in fields:
        left, right = getattr(actual, field), getattr(expected, field)
        if field == "bins":
            if type(left) is not tuple or len(left) != len(right):
                _fail(f"{label}.bins position/type differs")
            for index, (state, expected_state) in enumerate(zip(left, right)):
                _check_state(state, expected_state, f"{label}.bins[{index}]")
        elif field in _CONCRETE_SPECTRUM_FIELDS:
            _shape(left, right, f"{label}.{field}")
        elif field in _SHARED_SPECTRUM_FIELDS and concrete_enabled:
            _shape(left, right, f"{label}.{field}")
        else:
            _exact(left, right, f"{label}.{field}")


def _check_success(candidate: Any, expected: Any) -> None:
    if type(candidate) is not dict or type(expected) is not dict:
        _fail("successful fatigue payload must be an exact built-in dict")
    if tuple(candidate) != SUCCESS_KEYS or tuple(expected) != SUCCESS_KEYS:
        _fail("successful fatigue output inventory/order differs")
    concrete_enabled = expected["checks"]["concrete"]
    for key in SUCCESS_KEYS:
        actual, retained = candidate[key], expected[key]
        if key == "spectra":
            if type(actual) is not tuple or len(actual) != len(retained):
                _fail("fatigue spectra position/type differs")
            for index, (left, right) in enumerate(zip(actual, retained)):
                _check_spectrum(
                    left, right, f"fatigue.spectra[{index}]",
                    concrete_enabled=concrete_enabled,
                )
        elif key == "checks":
            _exact(actual, retained, "fatigue.checks")
        elif key == "partial_factors":
            if type(actual) is not dict or tuple(actual) != tuple(retained):
                _fail("fatigue.partial_factors inventory differs")
            _shape(actual["gamma_c"], retained["gamma_c"],
                   "fatigue.partial_factors.gamma_c")
            _exact(actual["gamma_s"], retained["gamma_s"],
                   "fatigue.partial_factors.gamma_s")
            _exact(actual["gamma_ff"], retained["gamma_ff"],
                   "fatigue.partial_factors.gamma_ff")
        elif key == "calculation_references":
            if type(actual) is not dict or tuple(actual) != tuple(retained):
                _fail("fatigue calculation-reference inventory differs")
            for reference in retained:
                checker = _shape if reference == "concrete" else _exact
                checker(actual[reference], retained[reference],
                        f"fatigue.calculation_references.{reference}")
        elif key in _CONCRETE_TOP_FIELDS:
            _shape(actual, retained, f"fatigue.{key}")
        elif key in _SHARED_TOP_FIELDS and concrete_enabled:
            _shape(actual, retained, f"fatigue.{key}")
        else:
            _exact(actual, retained, f"fatigue.{key}")


def _typed(value: Any, active: set[int] | None = None) -> Any:
    """Return strict JSON data that preserves concrete Python/numpy identities."""

    if active is None:
        active = set()
    if value is _MISSING:
        return ["missing"]
    if value is None or type(value) in {bool, int, str}:
        return [type(value).__module__, type(value).__qualname__, value]
    if type(value) is float:
        return ["builtins", "float", value.hex()]
    if isinstance(value, np.generic):
        return ["numpy", str(value.dtype), _typed(value.item(), active)]
    identity = id(value)
    if identity in active:
        _fail("cyclic fatigue input identity is unsupported")
    active.add(identity)
    try:
        if isinstance(value, np.ndarray):
            return [
                type(value).__module__, type(value).__qualname__, str(value.dtype),
                list(value.shape),
                [_typed(item, active) for item in value.reshape(-1)],
            ]
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return [
                type(value).__module__, type(value).__qualname__,
                [[field.name, _typed(getattr(value, field.name), active)]
                 for field in dataclasses.fields(value)],
            ]
        if isinstance(value, Mapping):
            return [
                type(value).__module__, type(value).__qualname__,
                [[_typed(key, active), _typed(item, active)]
                 for key, item in value.items()],
            ]
        if type(value).__module__.startswith("pandas"):
            columns = list(value.columns)
            index = list(value.index)
            return [
                type(value).__module__, type(value).__qualname__,
                [_typed(item, active) for item in columns],
                [_typed(item, active) for item in index],
                [str(item) for item in value.dtypes],
                [[_typed(item, active) for item in row]
                 for row in value.itertuples(index=False, name=None)],
            ]
        if isinstance(value, (list, tuple)):
            return [
                type(value).__module__, type(value).__qualname__,
                [_typed(item, active) for item in value],
            ]
        if isinstance(value, (set, frozenset)):
            items = [_typed(item, active) for item in value]
            items.sort(key=lambda item: json.dumps(item, sort_keys=True))
            return [type(value).__module__, type(value).__qualname__, items]
        if hasattr(value, "__dict__"):
            return [
                type(value).__module__, type(value).__qualname__,
                [[key, _typed(item, active)]
                 for key, item in vars(value).items()],
            ]
        return [type(value).__module__, type(value).__qualname__, repr(value)]
    finally:
        active.remove(identity)


def _identity_vector(value: Any) -> tuple[float, ...]:
    payload = json.dumps(
        _typed(value), ensure_ascii=True, sort_keys=False,
        separators=(",", ":"), allow_nan=False,
    ).encode("ascii")
    digest = hashlib.sha256(payload).digest()
    # Eight exact uint32-sized numerical leaves retain the full digest. This is
    # an immutable vector, not a truncated display hash.
    return tuple(float(int.from_bytes(digest[start:start + 4], "big"))
                 for start in range(0, 32, 4))


def _identity_number(value: Any) -> float:
    """Stable compact selector token; complete identities use the vector."""

    return _identity_vector(value)[0]


def _section_vector(section: Any) -> Any:
    """Seal every geometry coordinate/area without numerical coercion."""

    rings = getattr(section, "concrete")
    bars = getattr(section, "bars")
    tendons = getattr(section, "tendons")
    return {
        "type": (type(section).__module__, type(section).__qualname__),
        "concrete": tuple(
            tuple((point[0], point[1]) for point in ring) for ring in rings),
        "bars": tuple((item.x, item.y, item.area) for item in bars),
        "tendons": tuple((item.x, item.y, item.area) for item in tendons),
    }


def _identity_groups(inp: Mapping[str, Any], prepared: Any) -> tuple[tuple[str, Any], ...]:
    groups = (
        # This first vector prevents an application-boundary validation input
        # from becoming invisible merely because it is not forwarded to the
        # low-level solver. The named groups below keep engineering identities
        # independently inspectable as well.
        ("complete-fatigue-input", inp),
        ("raw-controls", tuple(
            (key, inp[key] if key in inp else _MISSING) for key in RAW_CONTROLS)),
        ("section-geometry", _section_vector(inp["section"])),
        ("bar-elements", inp.get("bar_elements", _MISSING)),
        ("tendon-elements", inp.get("tendon_elements", _MISSING)),
        ("bar-material-laws", inp.get("bar_materials", _MISSING)),
        ("tendon-material-laws", inp.get("tendon_materials", _MISSING)),
        ("concrete-material", inp.get("concrete", _MISSING)),
        ("mild-material-catalog", inp.get("mild_material_catalog", _MISSING)),
        ("prestress-material-catalog",
         inp.get("prestress_material_catalog", _MISSING)),
        ("fatigue-detail-catalog", inp.get("fatigue_detail_catalog", _MISSING)),
        ("fatigue-basis", inp.get("fatigue_basis", _MISSING)),
        ("fatigue-spectrum-table", inp.get("fatigue_spectrum_base", _MISSING)),
        ("analysis-signature", _analysis().analysis_signature(inp)),
    )
    # Also bind the exact resolved element/material alignment, independently of
    # numerical-law equality between two catalogue entries.
    return groups + (("resolved-preparation", prepared),)


def _result(value: float) -> TraceResult:
    number = float(value)
    if math.isfinite(number):
        return TraceResult(RESULT_FINITE, number)
    if math.isinf(number):
        state = RESULT_POSITIVE_INFINITY if number > 0 else RESULT_NEGATIVE_INFINITY
        return TraceResult(state, None, "independent fatigue reconstruction is unbounded")
    return TraceResult(RESULT_UNDEFINED, None,
                       "independent fatigue reconstruction is undefined")


class _Graph:
    def __init__(self, inp: Mapping[str, Any], prepared: Any) -> None:
        self.specs: list[NodeSpec] = []
        self.values: dict[str, float] = {}
        self.results: dict[str, TraceResult] = {}
        leaves = []
        for name, value in _identity_groups(inp, prepared):
            for position, chunk in enumerate(_identity_vector(value)):
                step_id = f"input-{name}-{position}"
                self.add(
                    step_id,
                    f"{name.replace('-', ' ').title()} identity chunk {position + 1}",
                    ONE, ROLE_USER_INPUT, INPUT, (), chunk,
                )
                leaves.append(step_id)
        self.add("input-normalised", "Complete successful fatigue input identity",
                 ONE, ROLE_COMPUTED, BOUNDARY, tuple(leaves),
                 _identity_number(tuple(self.values[item] for item in leaves)))

    def add(self, step_id: str, title: str, unit: Any, role: str, source: Any,
            dependencies: Sequence[str], value: float) -> str:
        if step_id in self.values:
            _fail(f"duplicate internal fatigue step {step_id}")
        deps = tuple(dependencies)
        if any(item not in self.values for item in deps):
            _fail(f"fatigue step {step_id} has a missing/forward dependency")
        self.specs.append(NodeSpec(step_id, title, unit, role, source, deps))
        self.values[step_id] = float(value)
        self.results[step_id] = _result(value)
        return step_id

    def final(self, step_id: str, title: str, dependencies: Sequence[str],
              value: float) -> str:
        # Directly bind every earlier step so no identity, intermediate or
        # convergence/status leaf can fall outside the member final closure.
        complete = tuple(dict.fromkeys((*dependencies, *self.values)))
        return self.add(step_id, title, ONE, ROLE_FINAL, VERDICT, complete, value)


def _close(actual: float, expected: float, label: str) -> None:
    if math.isinf(actual) or math.isinf(expected):
        if actual != expected:
            _fail(f"{label} differs from independent reconstruction")
    elif not math.isclose(float(actual), float(expected),
                          rel_tol=2.0e-12, abs_tol=2.0e-12):
        _fail(f"{label} differs from independent reconstruction")


def _damage(cycles: float, log_life: float) -> float:
    if math.isinf(log_life):
        return 0.0 if log_life > 0 else math.inf
    exponent = math.log10(cycles) - log_life
    if exponent > math.log10(np.finfo(float).max):
        return math.inf
    if exponent < math.log10(np.nextafter(0.0, 1.0)):
        return 0.0
    return 10.0 ** exponent


def _life(design_range: float, properties: Any, gamma_s: float) -> tuple[float, float, float]:
    if design_range == 0.0:
        return math.inf, math.inf, 0.0
    knee = properties.delta_sigma_rsk_mpa / gamma_s
    exponent = properties.k1 if design_range >= knee else properties.k2
    log_life = (
        math.log10(properties.n_star)
        + exponent * math.log10(
            properties.delta_sigma_rsk_mpa / (gamma_s * design_range))
    )
    life = 10.0 ** log_life if log_life <= math.log10(np.finfo(float).max) else math.inf
    return life, log_life, exponent


def _proof_limit(stress: float, properties: Any, gamma_s: float) -> tuple[float, float]:
    characteristic = properties.fytk_mpa
    if stress < 0.0 and properties.fyck_mpa is not None:
        characteristic = properties.fyck_mpa
    limit = characteristic / gamma_s
    return limit, abs(stress) / limit


def _calculation(graph: _Graph, calculation_id: str, title: str,
                 axes: tuple[TraceAxis, ...], final_step: str,
                 warnings: tuple[str, ...] = ()) -> TraceCalculation:
    units = {spec.step_id: spec.unit for spec in graph.specs}
    steps = []
    for spec in graph.specs:
        result = graph.results[spec.step_id]
        substituted = (
            f"{spec.step_id} = {result.state}"
            if result.state != RESULT_FINITE
            else f"{spec.step_id} = {result.value:.17g} {spec.unit.symbol}"
        )
        steps.append(TraceStep(
            step_id=spec.step_id,
            title=spec.title,
            dependencies=tuple(
                TraceDependency(item, units[item]) for item in spec.dependencies),
            quantity_role=spec.role,
            source=spec.source,
            symbol=spec.step_id,
            unit=spec.unit,
            actual_expression=f"Reconstruct {spec.title.lower()}",
            substituted_expression=substituted,
            result=result,
        ))
    return TraceCalculation(
        calculation_id=calculation_id,
        coverage_id=COVERAGE_ID,
        title=title,
        method_id=METHOD_ID,
        axes=axes,
        final_step_id=final_step,
        steps=tuple(steps),
        warnings=warnings,
        assumptions=(
            "This unpublished family proves successful reinforcement fatigue only.",
            "Concrete fatigue values remain excluded but their retained position and type are fenced.",
        ),
    )


def _assessment(
    inp: Mapping[str, Any], prepared: Any, spectrum: Any, properties: Any,
    detail_record: Mapping[str, Any], assessment: Any, element_position: int,
    spectrum_position: int,
) -> tuple[TraceCalculation, MemberSpec, dict[str, Any]]:
    graph = _Graph(inp, prepared)
    token = trace_identity_token(assessment.element_id)
    spectrum_token = trace_identity_token(spectrum.spectrum_name)
    prefix = f"s{spectrum_position}-e{element_position}"
    normal = "input-normalised"
    property_ids = []
    for name, value, unit in (
        ("n-star", properties.n_star, CYCLES),
        ("slope-1", properties.k1, ONE),
        ("slope-2", properties.k2, ONE),
        ("reference-range", properties.delta_sigma_rsk_mpa, MPA),
        ("proof-tension", properties.fytk_mpa, MPA),
        ("proof-compression", properties.fyck_mpa or properties.fytk_mpa, MPA),
        ("gamma-s", prepared.gamma_s, ONE),
    ):
        property_ids.append(graph.add(
            f"{prefix}-{name}", name.replace("-", " ").title(), unit,
            ROLE_COMPUTED, BOUNDARY, (normal,), value))

    if len(assessment.bins) != len(spectrum.bins):
        _fail(f"{assessment.element_id} bin cardinality differs")
    damage_ids, yield_ids, convergence_ids = [], [], []
    independent_bins = []
    custom_detail = detail_record.get("custom")
    if type(custom_detail) is not bool:
        _fail(f"{assessment.detail_id} custom provenance must be an exact Boolean")
    if custom_detail and detail_record.get("edition") is not None:
        _fail(f"{assessment.detail_id} custom provenance cannot carry an edition")
    sn_source, proof_source = code_sources(
        prepared.edition, assessment.kind, custom_detail=custom_detail)
    for bin_position, (row, state) in enumerate(zip(assessment.bins, spectrum.bins)):
        label = f"{spectrum.spectrum_name}/{assessment.element_id}/{row.bin_name}"
        if row.bin_name != state.name:
            _fail(f"{label} is not aligned with its solver bin")
        if type(row.converged) is not bool or type(state.converged) is not bool:
            _fail(f"{label} convergence must remain an exact Boolean")
        base = f"{prefix}-b{bin_position}"
        matched = graph.add(
            f"{base}-matched-state", "Matched solver state", ONE,
            ROLE_COMPUTED, ELASTIC, (normal,), _identity_number(state))
        cycles = graph.add(f"{base}-cycles", "Applied cycles", CYCLES,
                           ROLE_COMPUTED, ELASTIC, (matched,), state.cycles)
        converged = graph.add(
            f"{base}-converged", "Solver convergence", ONE,
            ROLE_COMPUTED, ELASTIC, (matched,), float(state.converged))
        convergence_ids.append(converged)
        long_stress = state.bar_stress_long_mpa[element_position]
        elastic_total = state.bar_stress_total_mpa[element_position]
        fatigue_total_vector = (
            state.bar_stress_fatigue_total_mpa or state.bar_stress_total_mpa)
        design_total_vector = (
            state.bar_stress_fatigue_design_total_mpa or fatigue_total_vector)
        fatigue_total = fatigue_total_vector[element_position]
        design_total = design_total_vector[element_position]
        long_id = graph.add(f"{base}-long-stress", "Long-term stress", MPA,
                            ROLE_COMPUTED, ELASTIC, (matched,), long_stress)
        elastic_id = graph.add(
            f"{base}-elastic-total-stress", "Perfect-bond total stress", MPA,
            ROLE_COMPUTED, ELASTIC, (matched,), elastic_total)
        total_id = graph.add(f"{base}-fatigue-total-stress", "Fatigue total stress", MPA,
                             ROLE_COMPUTED, ELASTIC, (matched,), fatigue_total)
        design_id = graph.add(
            f"{base}-design-total-stress", "Design fatigue total stress", MPA,
            ROLE_COMPUTED, ELASTIC, (matched,), design_total)
        stress_range = abs(fatigue_total - long_stress)
        elastic_range = abs(elastic_total - long_stress)
        design_range = abs(design_total - long_stress)
        adjustment = (
            stress_range / elastic_range if elastic_range > 0.0
            else (math.inf if stress_range > 0.0 else 1.0))
        range_id = graph.add(f"{base}-stress-range", "Retained stress range", MPA,
                             ROLE_COMPUTED, ELASTIC, (long_id, total_id), stress_range)
        elastic_range_id = graph.add(
            f"{base}-elastic-range", "Perfect-bond stress range", MPA,
            ROLE_COMPUTED, ELASTIC, (long_id, elastic_id), elastic_range)
        adjustment_id = graph.add(
            f"{base}-bond-adjustment", "Bond adjustment", ONE,
            ROLE_COMPUTED, ELASTIC, (range_id, elastic_range_id), adjustment)
        design_range_id = graph.add(
            f"{base}-design-range", "Design stress range", MPA,
            ROLE_COMPUTED, ELASTIC, (long_id, design_id, adjustment_id),
            design_range)
        life, log_life, exponent = _life(design_range, properties, prepared.gamma_s)
        exponent_id = graph.add(
            f"{base}-sn-exponent", "Selected S-N exponent", ONE,
            ROLE_COMPUTED, sn_source,
            (design_range_id, *property_ids[:4]), exponent)
        log_id = graph.add(
            f"{base}-log-life", "Log cycles to failure", ONE,
            ROLE_COMPUTED, sn_source, (design_range_id, exponent_id, *property_ids[:4]),
            log_life)
        life_id = graph.add(
            f"{base}-life", "Cycles to failure", CYCLES,
            ROLE_COMPUTED, sn_source, (log_id,), life)
        damage = _damage(state.cycles, log_life)
        damage_id = graph.add(
            f"{base}-damage", "Miner damage", ONE, ROLE_COMPUTED, sn_source,
            (cycles, log_id, life_id, converged), damage)
        damage_ids.append(damage_id)
        long_limit, long_util = _proof_limit(
            long_stress, properties, prepared.gamma_s)
        total_limit, total_util = _proof_limit(
            design_total, properties, prepared.gamma_s)
        if total_util >= long_util:
            governing_stress, limit, yield_util = design_total, total_limit, total_util
        else:
            governing_stress, limit, yield_util = long_stress, long_limit, long_util
        limit_id = graph.add(
            f"{base}-proof-limit", "Design proof stress limit", MPA,
            ROLE_COMPUTED, proof_source,
            (long_id, design_id, *property_ids[4:]), limit)
        yield_id = graph.add(
            f"{base}-yield-utilisation", "Absolute stress utilisation", ONE,
            ROLE_COMPUTED, proof_source, (long_id, design_id, limit_id), yield_util)
        yield_ids.append(yield_id)

        for actual, expected, field in (
            (row.cycles, state.cycles, "cycles"),
            (row.stress_long_mpa, long_stress, "long stress"),
            (row.stress_total_mpa, fatigue_total, "fatigue total stress"),
            (row.stress_total_design_mpa, design_total, "design total stress"),
            (row.stress_total_elastic_mpa, elastic_total, "elastic total stress"),
            (row.stress_range_mpa, stress_range, "stress range"),
            (row.stress_range_elastic_mpa, elastic_range, "elastic range"),
            (row.bond_adjustment, adjustment, "bond adjustment"),
            (row.design_stress_range_mpa, design_range, "design range"),
            (row.sn_exponent, exponent, "S-N exponent"),
            (row.cycles_to_failure, life, "cycles to failure"),
            (row.log10_cycles_to_failure, log_life, "log life"),
            (row.damage, damage, "damage"),
            (row.governing_stress_mpa, governing_stress, "governing stress"),
            (row.yield_limit_mpa, limit, "proof limit"),
            (row.yield_utilisation, yield_util, "yield utilisation"),
        ):
            _close(actual, expected, f"{label} {field}")
        if row.bond_method != state.bond_method:
            _fail(f"{label} bond method differs from matched solver state")
        independent_bins.append((row.bin_name, damage, yield_util, state.converged))

    damage = sum(item[1] for item in independent_bins)
    damage_governing = max(independent_bins, key=lambda item: item[1])
    yield_governing = max(independent_bins, key=lambda item: item[2])
    converged_value = all(item[3] for item in independent_bins)
    utilisation = max(damage, yield_governing[2])
    status = bool(converged_value and damage <= 1.0 and yield_governing[2] <= 1.0)
    total_damage_id = graph.add(
        f"{prefix}-total-damage", "Total Miner damage", ONE,
        ROLE_COMPUTED, VERDICT, tuple(damage_ids), damage)
    damage_governing_id = graph.add(
        f"{prefix}-governing-damage-bin", "Governing damage bin", ONE,
        ROLE_COMPUTED, VERDICT, tuple(damage_ids),
        _identity_number(damage_governing[0]))
    yield_governing_id = graph.add(
        f"{prefix}-governing-yield-bin", "Governing proof-stress bin", ONE,
        ROLE_COMPUTED, VERDICT, tuple(yield_ids),
        _identity_number(yield_governing[0]))
    convergence_id = graph.add(
        f"{prefix}-converged", "Assessment convergence", ONE,
        ROLE_COMPUTED, VERDICT, tuple(convergence_ids), float(converged_value))
    utilisation_id = graph.add(
        f"{prefix}-utilisation", "Assessment utilisation", ONE,
        ROLE_COMPUTED, VERDICT,
        (total_damage_id, yield_governing_id, *yield_ids), utilisation)
    status_id = graph.add(
        f"{prefix}-status", "Assessment PASS or FAIL", ONE,
        ROLE_COMPUTED, VERDICT,
        (total_damage_id, utilisation_id, convergence_id), float(status))
    final_id = f"{prefix}-result"
    graph.final(final_id, "Reinforcement fatigue result",
                (damage_governing_id, yield_governing_id, status_id), float(status))

    for actual, expected, field in (
        (assessment.damage, damage, "total damage"),
        (assessment.damage_utilisation, damage, "damage utilisation"),
        (assessment.yield_utilisation, yield_governing[2], "yield utilisation"),
        (assessment.utilisation, utilisation, "utilisation"),
    ):
        _close(actual, expected, f"{spectrum.spectrum_name}/{assessment.element_id} {field}")
    if assessment.governing_damage_bin != damage_governing[0]:
        _fail(f"{assessment.element_id} governing damage bin differs")
    if assessment.governing_yield_bin != yield_governing[0]:
        _fail(f"{assessment.element_id} governing yield bin differs")
    if type(assessment.converged) is not bool or assessment.converged != converged_value:
        _fail(f"{assessment.element_id} convergence differs")
    if type(assessment.passed) is not bool or assessment.passed != status:
        _fail(f"{assessment.element_id} verdict differs")

    axes = (
        TraceAxis("family", "reinforcement-fatigue"),
        TraceAxis("spectrum", spectrum.spectrum_name),
        TraceAxis("member", assessment.element_id),
        TraceAxis("kind", assessment.kind),
    )
    calculation_id = f"ct-010a-{spectrum_token}-{token}"
    calculation = _calculation(
        graph, calculation_id,
        f"Reinforcement fatigue {assessment.element_id} in {spectrum.spectrum_name}",
        axes, final_id,
        warnings=(
            (
                "Custom/imported S-N resistance source: "
                + str(detail_record.get("source") or "").strip()
            )
            if custom_detail and str(detail_record.get("source") or "").strip()
            else "Custom/imported S-N resistance source is not stated."
        ,) if custom_detail else (),
    )
    spec = MemberSpec(
        f"member-{spectrum_token}-{token}", calculation_id, axes,
        tuple(graph.specs), frozenset({RESULT_FINITE}),
    )
    evidence = {
        "spectrum": spectrum.spectrum_name,
        "element": assessment.element_id,
        "utilisation": utilisation,
        "converged": converged_value,
        "status": status,
        "calculation": calculation_id,
    }
    return calculation, spec, evidence


def _aggregate(
    inp: Mapping[str, Any], prepared: Any, evidence: Sequence[dict[str, Any]],
) -> tuple[TraceCalculation, MemberSpec]:
    if not evidence:
        _fail("successful reinforcement fatigue needs assessment evidence")
    graph = _Graph(inp, prepared)
    normal = "input-normalised"
    utilisations, convergences, statuses = [], [], []
    by_spectrum: dict[str, list[tuple[dict[str, Any], str]]] = {}
    for position, item in enumerate(evidence):
        prefix = f"assessment-{position}"
        util_id = graph.add(
            f"{prefix}-utilisation", "Assessment utilisation", ONE,
            ROLE_COMPUTED, VERDICT, (normal,), item["utilisation"])
        convergence_id = graph.add(
            f"{prefix}-converged", "Assessment convergence", ONE,
            ROLE_COMPUTED, VERDICT, (normal, util_id), float(item["converged"]))
        status_id = graph.add(
            f"{prefix}-status", "Assessment PASS or FAIL", ONE,
            ROLE_COMPUTED, VERDICT, (util_id, convergence_id), float(item["status"]))
        utilisations.append(util_id)
        convergences.append(convergence_id)
        statuses.append(status_id)
        by_spectrum.setdefault(item["spectrum"], []).append((item, util_id))

    spectrum_ids = []
    for position, (_name, items) in enumerate(by_spectrum.items()):
        governing = max(items, key=lambda row: row[0]["utilisation"])
        spectrum_ids.append(graph.add(
            f"spectrum-{position}-governing-member",
            "Spectrum governing reinforcement identity", ONE,
            ROLE_COMPUTED, VERDICT, tuple(row[1] for row in items),
            _identity_number(governing[0]["element"])))
    global_governing = max(evidence, key=lambda item: item["utilisation"])
    governing_spectrum_id = graph.add(
        "global-governing-spectrum", "Governing reinforcement spectrum", ONE,
        ROLE_COMPUTED, VERDICT, tuple(spectrum_ids),
        _identity_number(global_governing["spectrum"]))
    global_utilisation = graph.add(
        "global-utilisation", "Governing reinforcement utilisation", ONE,
        ROLE_COMPUTED, VERDICT, tuple(utilisations), global_governing["utilisation"])
    global_converged_value = all(item["converged"] for item in evidence)
    global_converged = graph.add(
        "global-converged", "All reinforcement assessments converged", ONE,
        ROLE_COMPUTED, VERDICT, tuple(convergences), float(global_converged_value))
    global_status_value = bool(
        global_converged_value and all(item["status"] for item in evidence))
    global_status = graph.add(
        "global-status", "Global reinforcement PASS or FAIL", ONE,
        ROLE_COMPUTED, VERDICT,
        (*statuses, global_converged, global_utilisation), float(global_status_value))
    final_id = "ct-010a-aggregate-result"
    graph.final(final_id, "Reinforcement fatigue aggregate result",
                (*spectrum_ids, governing_spectrum_id, global_utilisation,
                 global_converged, global_status), float(global_status_value))
    axes = (TraceAxis("family", "reinforcement-fatigue"),
            TraceAxis("scope", "aggregate"))
    calculation_id = "ct-010a-reinforcement-aggregate"
    calculation = _calculation(
        graph, calculation_id, "Reinforcement fatigue aggregate", axes, final_id)
    spec = MemberSpec(
        "member-reinforcement-aggregate", calculation_id, axes,
        tuple(graph.specs), frozenset({RESULT_FINITE}),
    )
    return calculation, spec


def _validate_controls(inp: Mapping[str, Any]) -> tuple[bool, bool, bool]:
    if not isinstance(inp, Mapping):
        _fail("fatigue input must be a mapping")
    values = []
    for key in ("fatigue_on", "fatigue_check_steel", "fatigue_check_concrete"):
        if key not in inp or type(inp[key]) is not bool:
            _fail(f"{key} must be a required exact built-in Boolean")
        values.append(inp[key])
    return tuple(values)  # type: ignore[return-value]


def _candidate(out: Mapping[str, Any]) -> Any:
    if not isinstance(out, Mapping):
        _fail("analysis output must be a mapping")
    return out.get("fatigue")


def _expected(
    inp: Mapping[str, Any], out: Mapping[str, Any], input_sha256: str,
    result_sha256: str,
) -> tuple[TraceBundle | None, tuple[MemberSpec, ...]]:
    fatigue_on, steel_on, _concrete_on = _validate_controls(inp)
    candidate = _candidate(out)
    if not fatigue_on:
        if candidate is not None:
            _fail("disabled fatigue input cannot carry a fatigue payload")
        return None, ()
    if candidate is None:
        return None, ()
    if type(candidate) is not dict:
        _fail("fatigue payload must be an exact built-in dict")
    # Retained invalid evidence is PR-08D.3a.2. Select it before touching any
    # section/material geometry so malformed invalid inputs remain failure-first.
    if "valid" in candidate:
        return None, ()

    analysis = _analysis()
    authoritative = analysis.run_analysis(inp)
    _check_success(candidate, authoritative)
    if not steel_on:
        return None, ()
    prepared = analysis.prepare(inp)
    detail_records = {
        record["id"]: record for record in prepared.detail_records
    }
    calculations, specs, assessment_evidence = [], [], []
    if len(authoritative["spectra"]) != len(prepared.spectra):
        _fail("fatigue spectrum cardinality differs from prepared inputs")
    for spectrum_position, spectrum in enumerate(authoritative["spectra"]):
        properties = prepared.reinforcement
        if len(spectrum.reinforcement) != len(properties):
            _fail("reinforcement assessment cardinality differs")
        spectrum_evidence = []
        for element_position, (prop, assessment) in enumerate(
                zip(properties, spectrum.reinforcement)):
            if (
                assessment.element_id != prop.element_id
                or assessment.kind != prop.kind
                or assessment.detail_id != prop.detail_id
            ):
                _fail("reinforcement assessment/material identity is misaligned")
            detail_record = detail_records.get(prop.detail_id)
            if detail_record is None:
                _fail("assigned fatigue-detail provenance is unavailable")
            calculation, spec, evidence = _assessment(
                inp, prepared, spectrum, prop, detail_record, assessment,
                element_position, spectrum_position)
            calculations.append(calculation)
            specs.append(spec)
            assessment_evidence.append(evidence)
            spectrum_evidence.append(evidence)
        governing = max(spectrum_evidence,
                        key=lambda item: item["utilisation"])
        if spectrum.governing_reinforcement_id != governing["element"]:
            _fail(
                f"{spectrum.spectrum_name} governing reinforcement identity "
                "differs from independent reconstruction"
            )
        if not prepared.check_concrete:
            _close(
                spectrum.utilisation, governing["utilisation"],
                f"{spectrum.spectrum_name} reinforcement-only utilisation",
            )
            expected_convergence = all(
                item["converged"] for item in spectrum_evidence)
            expected_status = all(item["status"] for item in spectrum_evidence)
            if (
                type(spectrum.converged) is not bool
                or spectrum.converged != expected_convergence
                or type(spectrum.passed) is not bool
                or spectrum.passed != expected_status
            ):
                _fail(
                    f"{spectrum.spectrum_name} reinforcement-only aggregate "
                    "state differs from independent reconstruction"
                )
    if not prepared.check_concrete:
        global_governing = max(
            assessment_evidence, key=lambda item: item["utilisation"])
        _close(
            authoritative["utilisation"], global_governing["utilisation"],
            "reinforcement-only global utilisation",
        )
        if authoritative["governing_spectrum"] != global_governing["spectrum"]:
            _fail("reinforcement-only governing spectrum differs")
        if (
            type(authoritative["converged"]) is not bool
            or authoritative["converged"]
            != all(item["converged"] for item in assessment_evidence)
            or type(authoritative["passed"]) is not bool
            or authoritative["passed"]
            != all(item["status"] for item in assessment_evidence)
        ):
            _fail("reinforcement-only global aggregate state differs")
    aggregate, aggregate_spec = _aggregate(inp, prepared, assessment_evidence)
    calculations.append(aggregate)
    specs.append(aggregate_spec)
    bundle = create_bundle(
        input_sha256=input_sha256,
        result_sha256=result_sha256,
        calculations=tuple(calculations),
    )
    audit_trace_registry(bundle, registry_for(tuple(specs)))
    return bundle, tuple(specs)


def build_fatigue_trace_family(
    inp: Mapping[str, Any], out: Mapping[str, Any], *,
    input_sha256: str, result_sha256: str,
) -> TraceBundle | None:
    """Build the applicable successful reinforcement-fatigue family."""

    try:
        return _expected(inp, out, input_sha256, result_sha256)[0]
    except TraceValidationError:
        raise
    except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"invalid CT-010a successful evidence: {exc}") from exc


def validate_fatigue_trace_family(
    bundle: TraceBundle | dict[str, Any] | None,
    inp: Mapping[str, Any], out: Mapping[str, Any], *,
    input_sha256: str, result_sha256: str,
) -> TraceBundle | None:
    """Reject stale, inapplicable, coherently resealed, or incomplete evidence."""

    expected, specs = _expected(inp, out, input_sha256, result_sha256)
    if expected is None:
        if bundle is not None:
            _fail("inapplicable CT-010a successful branch cannot carry a trace")
        return None
    candidate = validate_bundle(
        bundle,
        expected_input_sha256=input_sha256,
        expected_result_sha256=result_sha256,
    )
    audit_trace_registry(candidate, registry_for(specs))
    if candidate.to_dict() != expected.to_dict():
        _fail("CT-010a trace differs from authoritative independent replay")
    return candidate
