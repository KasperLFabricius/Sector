"""Successful reinforcement-fatigue trace, reconstructed from accepted inputs."""

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
    RESULT_FINITE, RESULT_NEGATIVE_INFINITY, RESULT_POSITIVE_INFINITY,
    RESULT_UNDEFINED, ROLE_COMPUTED, ROLE_FINAL, ROLE_USER_INPUT, TraceAxis,
    TraceBundle, TraceCalculation, TraceDependency, TraceResult, TraceStep,
    TraceValidationError, create_bundle, trace_identity_token, validate_bundle,
)
from .fatigue_trace_contract import (
    BOUNDARY_SOURCE, CONTROL_KEYS, COVERAGE_ID, CYCLES, ELASTIC_SOURCE,
    INPUT_SOURCE, INVALID_KEYS, METHOD_ID, MPA, ONE, SUCCESS_KEYS,
    VERDICT_SOURCE, CalculationContract, StepContract, fatigue_sources,
    registry_for,
)
from .trace_registry import audit_trace_registry


_ABSENT = object()
_STATE_EXCLUSIONS = frozenset({
    "concrete_compression_long_mpa", "concrete_compression_total_mpa",
    "concrete_compression_design_total_mpa", "elastic_result",
    "design_elastic_result",
})
_SPECTRUM_EXCLUSIONS = frozenset({
    "concrete", "concrete_search", "fcd_fat_mpa",
    "governing_concrete_fibre", "concrete_method",
})
_SPECTRUM_MIXED = frozenset({"utilisation", "converged", "passed"})
_TOP_EXCLUSIONS = frozenset({
    "concrete_method", "concrete_parameters", "t0_days",
})
_TOP_MIXED = frozenset({
    "governing_spectrum", "utilisation", "converged", "passed",
})


def _adapter():
    try:
        import fatigue_analysis
    except ImportError:  # pragma: no cover - direct package import
        sys.path.insert(0, str(
            pathlib.Path(__file__).resolve().parent.parent / "app"))
        import fatigue_analysis
    return fatigue_analysis


def _error(message: str) -> None:
    raise TraceValidationError(message)


def _scalar_equal(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if type(right) is float:
        return (
            math.isnan(left) and math.isnan(right)
        ) or left.hex() == right.hex()
    if isinstance(right, np.generic):
        return left.dtype == right.dtype and _scalar_equal(
            left.item(), right.item())
    return left == right


def _strict(left: Any, right: Any, path: str) -> None:
    """Exact recursive comparison with no container or numeric coercion."""

    if type(left) is not type(right):
        _error(f"{path} retained type differs")
    if dataclasses.is_dataclass(right) and not isinstance(right, type):
        names = tuple(field.name for field in dataclasses.fields(right))
        if tuple(field.name for field in dataclasses.fields(left)) != names:
            _error(f"{path} dataclass inventory differs")
        for name in names:
            _strict(getattr(left, name), getattr(right, name), f"{path}.{name}")
        return
    if isinstance(right, np.ndarray):
        if left.dtype != right.dtype or left.shape != right.shape:
            _error(f"{path} array identity differs")
        if not np.array_equal(left, right, equal_nan=True):
            _error(f"{path} array value differs")
        return
    if type(right) is dict:
        if tuple(left) != tuple(right):
            _error(f"{path} object inventory/order differs")
        for key in right:
            _strict(left[key], right[key], f"{path}.{key}")
        return
    if type(right) in {tuple, list}:
        if len(left) != len(right):
            _error(f"{path} cardinality differs")
        for index, (actual, expected) in enumerate(zip(left, right)):
            _strict(actual, expected, f"{path}[{index}]")
        return
    if not _scalar_equal(left, right):
        _error(f"{path} value differs")


def _structure(left: Any, right: Any, path: str) -> None:
    """Pin the retained shape/type of one intentionally excluded value."""

    if type(left) is not type(right):
        _error(f"{path} excluded type differs")
    if dataclasses.is_dataclass(right) and not isinstance(right, type):
        names = tuple(field.name for field in dataclasses.fields(right))
        if tuple(field.name for field in dataclasses.fields(left)) != names:
            _error(f"{path} excluded inventory differs")
        for name in names:
            _structure(
                getattr(left, name), getattr(right, name), f"{path}.{name}")
        return
    if isinstance(right, np.ndarray):
        if left.dtype != right.dtype or left.shape != right.shape:
            _error(f"{path} excluded array shape/type differs")
        return
    if type(right) is dict:
        if tuple(left) != tuple(right):
            _error(f"{path} excluded object inventory/order differs")
        for key in right:
            _structure(left[key], right[key], f"{path}.{key}")
        return
    if type(right) in {tuple, list}:
        if len(left) != len(right):
            _error(f"{path} excluded cardinality differs")
        for index, (actual, expected) in enumerate(zip(left, right)):
            _structure(actual, expected, f"{path}[{index}]")


def _compare_state(left: Any, right: Any, path: str) -> None:
    if type(left) is not type(right) or not dataclasses.is_dataclass(right):
        _error(f"{path} fatigue state type differs")
    names = tuple(field.name for field in dataclasses.fields(right))
    if tuple(field.name for field in dataclasses.fields(left)) != names:
        _error(f"{path} fatigue state inventory differs")
    for name in names:
        comparison = _structure if name in _STATE_EXCLUSIONS else _strict
        comparison(getattr(left, name), getattr(right, name), f"{path}.{name}")


def _compare_spectrum(
    left: Any, right: Any, path: str, *, concrete_enabled: bool,
) -> None:
    if type(left) is not type(right) or not dataclasses.is_dataclass(right):
        _error(f"{path} fatigue spectrum type differs")
    names = tuple(field.name for field in dataclasses.fields(right))
    if tuple(field.name for field in dataclasses.fields(left)) != names:
        _error(f"{path} fatigue spectrum inventory differs")
    for name in names:
        actual, expected = getattr(left, name), getattr(right, name)
        if name == "bins":
            if type(actual) is not tuple or len(actual) != len(expected):
                _error(f"{path}.bins position/type differs")
            for index, (state, expected_state) in enumerate(
                    zip(actual, expected)):
                _compare_state(
                    state, expected_state, f"{path}.bins[{index}]")
        elif name in _SPECTRUM_EXCLUSIONS:
            _structure(actual, expected, f"{path}.{name}")
        elif concrete_enabled and name in _SPECTRUM_MIXED:
            _structure(actual, expected, f"{path}.{name}")
        else:
            _strict(actual, expected, f"{path}.{name}")


def _compare_success(candidate: Any, replay: Any) -> None:
    if type(candidate) is not dict or type(replay) is not dict:
        _error("successful fatigue output must be an exact built-in dict")
    if tuple(candidate) != SUCCESS_KEYS or tuple(replay) != SUCCESS_KEYS:
        _error("successful fatigue output inventory/order differs")
    concrete_enabled = replay["checks"]["concrete"]
    for key in SUCCESS_KEYS:
        actual, expected = candidate[key], replay[key]
        if key == "spectra":
            if type(actual) is not tuple or len(actual) != len(expected):
                _error("fatigue spectra position/type differs")
            for position, (spectrum, retained) in enumerate(
                    zip(actual, expected)):
                _compare_spectrum(
                    spectrum, retained, f"fatigue.spectra[{position}]",
                    concrete_enabled=concrete_enabled)
        elif key == "partial_factors":
            if type(actual) is not dict or tuple(actual) != tuple(expected):
                _error("fatigue partial-factor inventory differs")
            _structure(actual["gamma_c"], expected["gamma_c"],
                       "fatigue.partial_factors.gamma_c")
            _strict(actual["gamma_s"], expected["gamma_s"],
                    "fatigue.partial_factors.gamma_s")
            _strict(actual["gamma_ff"], expected["gamma_ff"],
                    "fatigue.partial_factors.gamma_ff")
        elif key == "calculation_references":
            if type(actual) is not dict or tuple(actual) != tuple(expected):
                _error("fatigue calculation-reference inventory differs")
            for method in expected:
                comparison = _structure if method == "concrete" else _strict
                comparison(actual[method], expected[method],
                           f"fatigue.calculation_references.{method}")
        elif key in _TOP_EXCLUSIONS:
            _structure(actual, expected, f"fatigue.{key}")
        elif concrete_enabled and key in _TOP_MIXED:
            _structure(actual, expected, f"fatigue.{key}")
        else:
            _strict(actual, expected, f"fatigue.{key}")


def _controls(inp: Mapping[str, Any]) -> tuple[bool, bool, bool]:
    if not isinstance(inp, Mapping):
        _error("fatigue input must be a mapping")
    values = []
    for key in ("fatigue_on", "fatigue_check_steel", "fatigue_check_concrete"):
        if key not in inp or type(inp[key]) is not bool:
            _error(f"{key} must be a required exact built-in Boolean")
        values.append(inp[key])
    return values[0], values[1], values[2]


def _payload(out: Mapping[str, Any]) -> Any:
    if not isinstance(out, Mapping):
        _error("analysis output must be a mapping")
    return out.get("fatigue")


def _replay_deferred_invalid(inp: Mapping[str, Any], candidate: dict) -> None:
    """Fence the deferred invalid branch without reading successful geometry."""

    if tuple(candidate) != INVALID_KEYS:
        _error("retained invalid fatigue output inventory/order differs")
    if candidate["valid"] is not False:
        _error("retained invalid fatigue discriminator must be exact False")
    analysis = _adapter()
    errors = analysis.validation_errors(inp)
    if not errors:
        _error("valid fatigue input cannot carry a retained invalid payload")
    replay = analysis.invalid_result(inp, errors)
    if type(replay) is not dict or tuple(replay) != INVALID_KEYS:
        _error("authoritative invalid fatigue inventory drifted")
    _strict(candidate, replay, "fatigue.invalid")


def _classify(inp: Mapping[str, Any], out: Mapping[str, Any]) -> tuple[str, Any]:
    enabled, steel_enabled, _concrete_enabled = _controls(inp)
    candidate = _payload(out)
    if not enabled:
        if candidate is not None:
            _error("disabled fatigue input cannot carry a fatigue payload")
        return "none", None
    if candidate is None:
        return "none", None
    if type(candidate) is not dict:
        _error("fatigue payload must be an exact built-in dict")
    if tuple(candidate) == INVALID_KEYS:
        _replay_deferred_invalid(inp, candidate)
        return ("deferred-invalid" if steel_enabled else "none"), candidate
    if "valid" in candidate:
        _error("malformed fatigue valid discriminator/inventory")
    return "success", candidate


def _typed(value: Any, visiting: set[int] | None = None) -> Any:
    if visiting is None:
        visiting = set()
    if value is _ABSENT:
        return ["absent"]
    if value is None or type(value) in {bool, int, str}:
        return [type(value).__module__, type(value).__qualname__, value]
    if type(value) is float:
        return ["builtins", "float", value.hex()]
    if isinstance(value, np.generic):
        return ["numpy", str(value.dtype), _typed(value.item(), visiting)]
    marker = id(value)
    if marker in visiting:
        _error("cyclic fatigue input identity is unsupported")
    visiting.add(marker)
    try:
        if isinstance(value, np.ndarray):
            return [
                type(value).__module__, type(value).__qualname__,
                str(value.dtype), list(value.shape),
                [_typed(item, visiting) for item in value.reshape(-1)],
            ]
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return [
                type(value).__module__, type(value).__qualname__,
                [[field.name, _typed(getattr(value, field.name), visiting)]
                 for field in dataclasses.fields(value)],
            ]
        if isinstance(value, Mapping):
            return [
                type(value).__module__, type(value).__qualname__,
                [[_typed(key, visiting), _typed(item, visiting)]
                 for key, item in value.items()],
            ]
        if type(value).__module__.startswith("pandas"):
            return [
                type(value).__module__, type(value).__qualname__,
                [_typed(item, visiting) for item in value.columns],
                [_typed(item, visiting) for item in value.index],
                [str(item) for item in value.dtypes],
                [[_typed(item, visiting) for item in row]
                 for row in value.itertuples(index=False, name=None)],
            ]
        if type(value) in {tuple, list}:
            return [
                type(value).__module__, type(value).__qualname__,
                [_typed(item, visiting) for item in value],
            ]
        if type(value) in {set, frozenset}:
            items = [_typed(item, visiting) for item in value]
            items.sort(key=lambda item: json.dumps(item, sort_keys=True))
            return [type(value).__module__, type(value).__qualname__, items]
        if hasattr(value, "__dict__"):
            return [
                type(value).__module__, type(value).__qualname__,
                [[key, _typed(item, visiting)]
                 for key, item in vars(value).items()],
            ]
        return [type(value).__module__, type(value).__qualname__, repr(value)]
    finally:
        visiting.remove(marker)


def _digest_vector(value: Any) -> tuple[float, ...]:
    encoded = json.dumps(
        _typed(value), ensure_ascii=True, sort_keys=False,
        separators=(",", ":"), allow_nan=False).encode("ascii")
    digest = hashlib.sha256(encoded).digest()
    return tuple(
        float(int.from_bytes(digest[offset:offset + 4], "big"))
        for offset in range(0, len(digest), 4)
    )


def _selector(value: Any) -> float:
    return _digest_vector(value)[0]


def _geometry(section: Any) -> Any:
    return {
        "class": (type(section).__module__, type(section).__qualname__),
        "rings": tuple(tuple((point[0], point[1]) for point in ring)
                       for ring in section.concrete),
        "bars": tuple((bar.x, bar.y, bar.area) for bar in section.bars),
        "tendons": tuple(
            (bar.x, bar.y, bar.area) for bar in section.tendons),
    }


def _identity_inventory(
    inp: Mapping[str, Any], prepared: Any,
) -> tuple[tuple[str, Any], ...]:
    return (
        ("complete-original-input", inp),
        ("raw-controls", tuple(
            (key, inp[key] if key in inp else _ABSENT)
            for key in CONTROL_KEYS)),
        ("section-geometry", _geometry(inp["section"])),
        ("bar-elements", inp.get("bar_elements", _ABSENT)),
        ("tendon-elements", inp.get("tendon_elements", _ABSENT)),
        ("bar-material-laws", inp.get("bar_materials", _ABSENT)),
        ("tendon-material-laws", inp.get("tendon_materials", _ABSENT)),
        ("concrete-material", inp.get("concrete", _ABSENT)),
        ("mild-material-catalog", inp.get("mild_material_catalog", _ABSENT)),
        ("prestress-material-catalog",
         inp.get("prestress_material_catalog", _ABSENT)),
        ("fatigue-detail-catalog",
         inp.get("fatigue_detail_catalog", _ABSENT)),
        ("fatigue-spectrum-table",
         inp.get("fatigue_spectrum_base", _ABSENT)),
        ("fatigue-basis", inp.get("fatigue_basis", _ABSENT)),
        ("adapter-signature", _adapter().analysis_signature(inp)),
        ("aligned-preparation", prepared),
    )


def _trace_result(value: float) -> TraceResult:
    number = float(value)
    if math.isfinite(number):
        return TraceResult(RESULT_FINITE, number)
    if math.isinf(number):
        return TraceResult(
            RESULT_POSITIVE_INFINITY if number > 0 else RESULT_NEGATIVE_INFINITY,
            None, "independent fatigue reconstruction is unbounded")
    return TraceResult(
        RESULT_UNDEFINED, None,
        "independent fatigue reconstruction is undefined")


class _TraceGraph:
    def __init__(self, inp: Mapping[str, Any], prepared: Any) -> None:
        self.contracts: list[StepContract] = []
        self.results: dict[str, TraceResult] = {}
        leaves = []
        for label, identity in _identity_inventory(inp, prepared):
            for chunk, value in enumerate(_digest_vector(identity), start=1):
                leaves.append(self.add(
                    f"identity-{label}-{chunk}",
                    f"{label.replace('-', ' ').title()} chunk {chunk}",
                    ONE, ROLE_USER_INPUT, INPUT_SOURCE, (), value))
        self.normal = self.add(
            "normalised-input-identity", "Complete fatigue input identity",
            ONE, ROLE_COMPUTED, BOUNDARY_SOURCE, tuple(leaves),
            _selector(tuple(self.results[name].value for name in leaves)))

    def add(
        self, step_id: str, title: str, unit: Any, role: str, source: Any,
        dependencies: Sequence[str], value: float,
    ) -> str:
        if step_id in self.results:
            _error(f"duplicate fatigue trace step {step_id}")
        dependency_ids = tuple(dependencies)
        if any(name not in self.results for name in dependency_ids):
            _error(f"fatigue step {step_id} has a forward dependency")
        self.contracts.append(StepContract(
            step_id, title, unit, role, source, dependency_ids))
        self.results[step_id] = _trace_result(value)
        return step_id

    def finish(self, step_id: str, title: str, value: float) -> str:
        # The final directly owns all prior nodes; semantic intermediate edges
        # still prove each mechanics and convergence relationship separately.
        return self.add(
            step_id, title, ONE, ROLE_FINAL, VERDICT_SOURCE,
            tuple(self.results), value)


def _near(actual: float, expected: float, label: str) -> None:
    if math.isinf(actual) or math.isinf(expected):
        if actual != expected:
            _error(f"{label} differs from independent reconstruction")
    elif not math.isclose(
        float(actual), float(expected), rel_tol=2e-12, abs_tol=2e-12,
    ):
        _error(f"{label} differs from independent reconstruction")


def _sn_life(design_range: float, props: Any, gamma_s: float):
    if design_range == 0.0:
        return math.inf, math.inf, 0.0
    knee = props.delta_sigma_rsk_mpa / gamma_s
    slope = props.k1 if design_range >= knee else props.k2
    log_life = (
        math.log10(props.n_star)
        + slope * math.log10(
            props.delta_sigma_rsk_mpa / (gamma_s * design_range)))
    life = (
        math.inf if log_life > math.log10(np.finfo(float).max)
        else 10.0 ** log_life)
    return life, log_life, slope


def _miner(cycles: float, log_life: float) -> float:
    if math.isinf(log_life):
        return 0.0 if log_life > 0 else math.inf
    exponent = math.log10(cycles) - log_life
    if exponent > math.log10(np.finfo(float).max):
        return math.inf
    if exponent < math.log10(np.nextafter(0.0, 1.0)):
        return 0.0
    return 10.0 ** exponent


def _proof(stress: float, props: Any, gamma_s: float):
    strength = props.fytk_mpa
    if stress < 0.0 and props.fyck_mpa is not None:
        strength = props.fyck_mpa
    limit = strength / gamma_s
    return limit, abs(stress) / limit


def _make_calculation(
    graph: _TraceGraph, calculation_id: str, title: str,
    axes: tuple[TraceAxis, ...], final_id: str, *, warnings: tuple[str, ...] = (),
) -> tuple[TraceCalculation, CalculationContract]:
    units = {row.step_id: row.unit for row in graph.contracts}
    steps = []
    for row in graph.contracts:
        result = graph.results[row.step_id]
        display = (
            result.state if result.state != RESULT_FINITE
            else f"{result.value:.17g} {row.unit.symbol}")
        steps.append(TraceStep(
            step_id=row.step_id,
            title=row.title,
            dependencies=tuple(
                TraceDependency(name, units[name]) for name in row.dependencies),
            quantity_role=row.role,
            source=row.source,
            symbol=row.step_id,
            unit=row.unit,
            actual_expression=f"Reconstruct {row.title.lower()}",
            substituted_expression=f"{row.step_id} = {display}",
            result=result,
        ))
    calculation = TraceCalculation(
        calculation_id=calculation_id,
        coverage_id=COVERAGE_ID,
        title=title,
        method_id=METHOD_ID,
        axes=axes,
        final_step_id=final_id,
        steps=tuple(steps),
        warnings=warnings,
        assumptions=(
            "Only successful reinforcement fatigue is proved by this slice.",
            "Concrete values are excluded while their retained position and type remain fenced.",
        ),
    )
    return calculation, CalculationContract(
        f"member-{calculation_id}", calculation_id, axes,
        tuple(graph.contracts))


def _assessment_calculation(
    inp: Mapping[str, Any], prepared: Any, spectrum: Any, props: Any,
    assessment: Any, detail: Mapping[str, Any], spectrum_position: int,
    element_position: int,
):
    graph = _TraceGraph(inp, prepared)
    prefix = f"s{spectrum_position}-e{element_position}"
    properties = []
    for name, value, unit in (
        ("n-star", props.n_star, CYCLES),
        ("slope-one", props.k1, ONE),
        ("slope-two", props.k2, ONE),
        ("reference-range", props.delta_sigma_rsk_mpa, MPA),
        ("tension-proof", props.fytk_mpa, MPA),
        ("compression-proof", props.fyck_mpa or props.fytk_mpa, MPA),
        ("gamma-s", prepared.gamma_s, ONE),
    ):
        properties.append(graph.add(
            f"{prefix}-{name}", name.replace("-", " ").title(), unit,
            ROLE_COMPUTED, BOUNDARY_SOURCE, (graph.normal,), value))
    custom = detail.get("custom")
    if type(custom) is not bool:
        _error(f"{props.detail_id} custom detail flag must be exact Boolean")
    if custom and detail.get("edition") is not None:
        _error(f"{props.detail_id} custom detail cannot carry an edition")
    sn_source, proof_source = fatigue_sources(
        prepared.edition, props.kind, custom_detail=custom)
    if len(assessment.bins) != len(spectrum.bins):
        _error(f"{assessment.element_id} bin cardinality differs")
    reconstructed = []
    damage_nodes, yield_nodes, convergence_nodes = [], [], []
    for bin_position, (reported, state) in enumerate(
            zip(assessment.bins, spectrum.bins)):
        if reported.bin_name != state.name:
            _error("reinforcement bin is not aligned with its solver state")
        if type(reported.converged) is not bool or type(state.converged) is not bool:
            _error("fatigue-bin convergence must be exact Boolean")
        base = f"{prefix}-b{bin_position}"
        matched = graph.add(
            f"{base}-matched-state", "Matched Elastic fatigue state", ONE,
            ROLE_COMPUTED, ELASTIC_SOURCE, (graph.normal,), _selector(state))
        cycles_node = graph.add(
            f"{base}-cycles", "Applied cycles", CYCLES, ROLE_COMPUTED,
            ELASTIC_SOURCE, (matched,), state.cycles)
        convergence_nodes.append(graph.add(
            f"{base}-convergence", "Matched-state convergence", ONE,
            ROLE_COMPUTED, ELASTIC_SOURCE, (matched,), float(state.converged)))
        long_stress = state.bar_stress_long_mpa[element_position]
        elastic_total = state.bar_stress_total_mpa[element_position]
        fatigue_values = (
            state.bar_stress_fatigue_total_mpa or state.bar_stress_total_mpa)
        design_values = (
            state.bar_stress_fatigue_design_total_mpa or fatigue_values)
        fatigue_total = fatigue_values[element_position]
        design_total = design_values[element_position]
        long_node = graph.add(
            f"{base}-long-stress", "Long-term reinforcement stress", MPA,
            ROLE_COMPUTED, ELASTIC_SOURCE, (matched,), long_stress)
        elastic_node = graph.add(
            f"{base}-perfect-bond-total", "Perfect-bond total stress", MPA,
            ROLE_COMPUTED, ELASTIC_SOURCE, (matched,), elastic_total)
        fatigue_node = graph.add(
            f"{base}-fatigue-total", "Bond-adjusted fatigue total stress", MPA,
            ROLE_COMPUTED, ELASTIC_SOURCE, (matched,), fatigue_total)
        design_node = graph.add(
            f"{base}-design-total", "Design fatigue total stress", MPA,
            ROLE_COMPUTED, ELASTIC_SOURCE, (matched,), design_total)
        stress_range = abs(fatigue_total - long_stress)
        elastic_range = abs(elastic_total - long_stress)
        design_range = abs(design_total - long_stress)
        bond_factor = (
            stress_range / elastic_range if elastic_range > 0.0
            else math.inf if stress_range > 0.0 else 1.0)
        range_node = graph.add(
            f"{base}-stress-range", "Fatigue stress range", MPA,
            ROLE_COMPUTED, ELASTIC_SOURCE, (long_node, fatigue_node),
            stress_range)
        elastic_range_node = graph.add(
            f"{base}-perfect-bond-range", "Perfect-bond stress range", MPA,
            ROLE_COMPUTED, ELASTIC_SOURCE, (long_node, elastic_node),
            elastic_range)
        bond_node = graph.add(
            f"{base}-bond-factor", "Bond adjustment factor", ONE,
            ROLE_COMPUTED, ELASTIC_SOURCE,
            (range_node, elastic_range_node), bond_factor)
        design_range_node = graph.add(
            f"{base}-design-range", "Design stress range", MPA,
            ROLE_COMPUTED, ELASTIC_SOURCE,
            (long_node, design_node, bond_node), design_range)
        life, log_life, slope = _sn_life(
            design_range, props, prepared.gamma_s)
        slope_node = graph.add(
            f"{base}-sn-slope", "Selected S-N slope", ONE, ROLE_COMPUTED,
            sn_source, (design_range_node, *properties[:4]), slope)
        log_node = graph.add(
            f"{base}-log-life", "Log cycles to failure", ONE, ROLE_COMPUTED,
            sn_source, (design_range_node, slope_node, *properties[:4]),
            log_life)
        life_node = graph.add(
            f"{base}-life", "Cycles to failure", CYCLES, ROLE_COMPUTED,
            sn_source, (log_node,), life)
        damage = _miner(state.cycles, log_life)
        damage_nodes.append(graph.add(
            f"{base}-damage", "Miner damage", ONE, ROLE_COMPUTED,
            sn_source,
            (cycles_node, log_node, life_node, convergence_nodes[-1]), damage))
        long_limit, long_util = _proof(
            long_stress, props, prepared.gamma_s)
        total_limit, total_util = _proof(
            design_total, props, prepared.gamma_s)
        if total_util >= long_util:
            governing_stress, proof_limit, proof_util = (
                design_total, total_limit, total_util)
        else:
            governing_stress, proof_limit, proof_util = (
                long_stress, long_limit, long_util)
        limit_node = graph.add(
            f"{base}-proof-limit", "Design proof stress", MPA,
            ROLE_COMPUTED, proof_source,
            (long_node, design_node, *properties[4:]), proof_limit)
        yield_nodes.append(graph.add(
            f"{base}-proof-utilisation", "Absolute stress utilisation", ONE,
            ROLE_COMPUTED, proof_source,
            (long_node, design_node, limit_node), proof_util))
        expected_values = (
            (reported.cycles, state.cycles, "cycles"),
            (reported.stress_long_mpa, long_stress, "long stress"),
            (reported.stress_total_mpa, fatigue_total, "fatigue total"),
            (reported.stress_total_design_mpa, design_total, "design total"),
            (reported.stress_total_elastic_mpa, elastic_total, "elastic total"),
            (reported.stress_range_mpa, stress_range, "stress range"),
            (reported.stress_range_elastic_mpa, elastic_range, "elastic range"),
            (reported.bond_adjustment, bond_factor, "bond factor"),
            (reported.design_stress_range_mpa, design_range, "design range"),
            (reported.delta_sigma_rsk_mpa, props.delta_sigma_rsk_mpa,
             "reference range"),
            (reported.delta_sigma_rd_mpa,
             props.delta_sigma_rsk_mpa / prepared.gamma_s, "design resistance"),
            (reported.sn_exponent, slope, "S-N slope"),
            (reported.cycles_to_failure, life, "cycles to failure"),
            (reported.log10_cycles_to_failure, log_life, "log life"),
            (reported.damage, damage, "damage"),
            (reported.governing_stress_mpa, governing_stress,
             "governing stress"),
            (reported.yield_limit_mpa, proof_limit, "proof limit"),
            (reported.yield_utilisation, proof_util, "proof utilisation"),
        )
        for actual, expected, label in expected_values:
            _near(actual, expected, f"{assessment.element_id}/{state.name} {label}")
        if reported.bond_method != state.bond_method:
            _error("reported bond method differs from matched solver state")
        reconstructed.append((state.name, damage, proof_util, state.converged))

    damage_total = sum(item[1] for item in reconstructed)
    damage_governing = max(reconstructed, key=lambda item: item[1])
    proof_governing = max(reconstructed, key=lambda item: item[2])
    converged = all(item[3] for item in reconstructed)
    utilisation = max(damage_total, proof_governing[2])
    passed = bool(converged and damage_total <= 1.0 and proof_governing[2] <= 1.0)
    damage_total_node = graph.add(
        f"{prefix}-total-damage", "Total Miner damage", ONE,
        ROLE_COMPUTED, VERDICT_SOURCE, tuple(damage_nodes), damage_total)
    graph.add(
        f"{prefix}-governing-damage-bin", "Governing damage bin", ONE,
        ROLE_COMPUTED, VERDICT_SOURCE, tuple(damage_nodes),
        _selector(damage_governing[0]))
    graph.add(
        f"{prefix}-governing-proof-bin", "Governing proof-stress bin", ONE,
        ROLE_COMPUTED, VERDICT_SOURCE, tuple(yield_nodes),
        _selector(proof_governing[0]))
    convergence_node = graph.add(
        f"{prefix}-convergence", "Assessment convergence", ONE,
        ROLE_COMPUTED, VERDICT_SOURCE, tuple(convergence_nodes), float(converged))
    utilisation_node = graph.add(
        f"{prefix}-utilisation", "Assessment utilisation", ONE,
        ROLE_COMPUTED, VERDICT_SOURCE,
        (damage_total_node, *yield_nodes), utilisation)
    graph.add(
        f"{prefix}-status", "Assessment PASS or FAIL", ONE,
        ROLE_COMPUTED, VERDICT_SOURCE,
        (damage_total_node, utilisation_node, convergence_node), float(passed))
    final_id = graph.finish(
        f"{prefix}-result", "Reinforcement fatigue result", float(passed))
    for actual, expected, label in (
        (assessment.damage, damage_total, "damage"),
        (assessment.damage_utilisation, damage_total, "damage utilisation"),
        (assessment.yield_utilisation, proof_governing[2], "proof utilisation"),
        (assessment.utilisation, utilisation, "utilisation"),
    ):
        _near(actual, expected, f"{assessment.element_id} {label}")
    if assessment.governing_damage_bin != damage_governing[0]:
        _error("governing damage-bin identity differs")
    if assessment.governing_yield_bin != proof_governing[0]:
        _error("governing proof-bin identity differs")
    if type(assessment.converged) is not bool or assessment.converged != converged:
        _error("assessment convergence differs")
    if type(assessment.passed) is not bool or assessment.passed != passed:
        _error("assessment verdict differs")
    axes = (
        TraceAxis("family", "reinforcement-fatigue"),
        TraceAxis("spectrum", spectrum.spectrum_name),
        TraceAxis("member", assessment.element_id),
        TraceAxis("kind", assessment.kind),
    )
    calculation_id = (
        f"ct-010a-{trace_identity_token(spectrum.spectrum_name)}-"
        f"{trace_identity_token(assessment.element_id)}")
    source_text = str(detail.get("source") or "").strip()
    warnings = (
        ((f"Custom/imported S-N resistance source: {source_text}",)
         if source_text else
         ("Custom/imported S-N resistance source is not stated.",))
        if custom else ()
    )
    calculation, contract = _make_calculation(
        graph, calculation_id,
        f"Reinforcement fatigue {assessment.element_id} in {spectrum.spectrum_name}",
        axes, final_id, warnings=warnings)
    return calculation, contract, {
        "spectrum": spectrum.spectrum_name,
        "element": assessment.element_id,
        "utilisation": utilisation,
        "converged": converged,
        "passed": passed,
    }


def _aggregate_calculation(
    inp: Mapping[str, Any], prepared: Any, evidence: Sequence[dict[str, Any]],
):
    if not evidence:
        _error("successful reinforcement fatigue has no assessments")
    graph = _TraceGraph(inp, prepared)
    utilisation_nodes, convergence_nodes, status_nodes = [], [], []
    spectra: dict[str, list[tuple[dict[str, Any], str]]] = {}
    for position, item in enumerate(evidence):
        util = graph.add(
            f"assessment-{position}-utilisation", "Assessment utilisation", ONE,
            ROLE_COMPUTED, VERDICT_SOURCE, (graph.normal,), item["utilisation"])
        convergence = graph.add(
            f"assessment-{position}-convergence", "Assessment convergence", ONE,
            ROLE_COMPUTED, VERDICT_SOURCE, (graph.normal, util),
            float(item["converged"]))
        status = graph.add(
            f"assessment-{position}-status", "Assessment PASS or FAIL", ONE,
            ROLE_COMPUTED, VERDICT_SOURCE, (util, convergence),
            float(item["passed"]))
        utilisation_nodes.append(util)
        convergence_nodes.append(convergence)
        status_nodes.append(status)
        spectra.setdefault(item["spectrum"], []).append((item, util))
    spectrum_nodes = []
    for position, rows in enumerate(spectra.values()):
        governing = max(rows, key=lambda row: row[0]["utilisation"])
        spectrum_nodes.append(graph.add(
            f"spectrum-{position}-governing-member",
            "Spectrum governing reinforcement identity", ONE,
            ROLE_COMPUTED, VERDICT_SOURCE,
            tuple(row[1] for row in rows), _selector(governing[0]["element"])))
    governing = max(evidence, key=lambda item: item["utilisation"])
    global_util = graph.add(
        "global-utilisation", "Global reinforcement utilisation", ONE,
        ROLE_COMPUTED, VERDICT_SOURCE, tuple(utilisation_nodes),
        governing["utilisation"])
    graph.add(
        "global-governing-spectrum", "Governing reinforcement spectrum", ONE,
        ROLE_COMPUTED, VERDICT_SOURCE, tuple(spectrum_nodes),
        _selector(governing["spectrum"]))
    converged = all(item["converged"] for item in evidence)
    convergence = graph.add(
        "global-convergence", "All reinforcement assessments converged", ONE,
        ROLE_COMPUTED, VERDICT_SOURCE, tuple(convergence_nodes), float(converged))
    passed = bool(converged and all(item["passed"] for item in evidence))
    graph.add(
        "global-status", "Global reinforcement PASS or FAIL", ONE,
        ROLE_COMPUTED, VERDICT_SOURCE,
        (*status_nodes, convergence, global_util), float(passed))
    final_id = graph.finish(
        "ct-010a-aggregate-result", "Reinforcement fatigue aggregate result",
        float(passed))
    axes = (
        TraceAxis("family", "reinforcement-fatigue"),
        TraceAxis("scope", "aggregate"),
    )
    return _make_calculation(
        graph, "ct-010a-reinforcement-aggregate",
        "Reinforcement fatigue aggregate", axes, final_id)


def _successful_bundle(
    inp: Mapping[str, Any], candidate: dict, *,
    input_sha256: str, result_sha256: str,
):
    analysis = _adapter()
    replay = analysis.run_analysis(inp)
    _compare_success(candidate, replay)
    prepared = analysis.prepare(inp)
    details = {record["id"]: record for record in prepared.detail_records}
    if len(replay["spectra"]) != len(prepared.spectra):
        _error("prepared/output spectrum cardinality differs")
    calculations, contracts, all_evidence = [], [], []
    for spectrum_position, spectrum in enumerate(replay["spectra"]):
        if len(spectrum.reinforcement) != len(prepared.reinforcement):
            _error("reinforcement assessment cardinality differs")
        spectrum_evidence = []
        for element_position, (props, assessment) in enumerate(
                zip(prepared.reinforcement, spectrum.reinforcement)):
            if (
                props.element_id != assessment.element_id
                or props.kind != assessment.kind
                or props.detail_id != assessment.detail_id
            ):
                _error("assessment and prepared element identities differ")
            detail = details.get(props.detail_id)
            if detail is None:
                _error("assigned fatigue-detail provenance is unavailable")
            calculation, contract, evidence = _assessment_calculation(
                inp, prepared, spectrum, props, assessment, detail,
                spectrum_position, element_position)
            calculations.append(calculation)
            contracts.append(contract)
            spectrum_evidence.append(evidence)
            all_evidence.append(evidence)
        governing = max(
            spectrum_evidence, key=lambda item: item["utilisation"])
        if spectrum.governing_reinforcement_id != governing["element"]:
            _error("spectrum governing reinforcement identity differs")
        if not prepared.check_concrete:
            _near(spectrum.utilisation, governing["utilisation"],
                  "reinforcement-only spectrum utilisation")
            if (
                type(spectrum.converged) is not bool
                or spectrum.converged
                != all(item["converged"] for item in spectrum_evidence)
                or type(spectrum.passed) is not bool
                or spectrum.passed
                != all(item["passed"] for item in spectrum_evidence)
            ):
                _error("reinforcement-only spectrum aggregate state differs")
    if not prepared.check_concrete:
        governing = max(all_evidence, key=lambda item: item["utilisation"])
        _near(replay["utilisation"], governing["utilisation"],
              "reinforcement-only global utilisation")
        if replay["governing_spectrum"] != governing["spectrum"]:
            _error("reinforcement-only governing spectrum differs")
        if (
            type(replay["converged"]) is not bool
            or replay["converged"]
            != all(item["converged"] for item in all_evidence)
            or type(replay["passed"]) is not bool
            or replay["passed"] != all(item["passed"] for item in all_evidence)
        ):
            _error("reinforcement-only global aggregate state differs")
    aggregate, aggregate_contract = _aggregate_calculation(
        inp, prepared, all_evidence)
    calculations.append(aggregate)
    contracts.append(aggregate_contract)
    bundle = create_bundle(
        input_sha256=input_sha256,
        result_sha256=result_sha256,
        calculations=tuple(calculations))
    audit_trace_registry(bundle, registry_for(tuple(contracts)))
    return bundle, tuple(contracts)


def _expected(
    inp: Mapping[str, Any], out: Mapping[str, Any], *,
    input_sha256: str, result_sha256: str,
):
    branch, candidate = _classify(inp, out)
    if branch != "success":
        return None, ()
    if inp["fatigue_check_steel"] is False:
        # Concrete-only success is still replayed exactly before being excluded.
        _compare_success(candidate, _adapter().run_analysis(inp))
        return None, ()
    return _successful_bundle(
        inp, candidate,
        input_sha256=input_sha256, result_sha256=result_sha256)


def build_fatigue_trace_family(
    inp: Mapping[str, Any], out: Mapping[str, Any], *,
    input_sha256: str, result_sha256: str,
) -> TraceBundle | None:
    try:
        return _expected(
            inp, out, input_sha256=input_sha256,
            result_sha256=result_sha256)[0]
    except TraceValidationError:
        raise
    except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(
            f"invalid CT-010a successful evidence: {exc}") from exc


def validate_fatigue_trace_family(
    bundle: TraceBundle | dict[str, Any] | None,
    inp: Mapping[str, Any], out: Mapping[str, Any], *,
    input_sha256: str, result_sha256: str,
) -> TraceBundle | None:
    expected, contracts = _expected(
        inp, out, input_sha256=input_sha256,
        result_sha256=result_sha256)
    if expected is None:
        if bundle is not None:
            _error("inapplicable CT-010a success branch cannot carry evidence")
        return None
    candidate = validate_bundle(
        bundle, expected_input_sha256=input_sha256,
        expected_result_sha256=result_sha256)
    audit_trace_registry(candidate, registry_for(contracts))
    if candidate.to_dict() != expected.to_dict():
        _error("CT-010a trace differs from authoritative independent replay")
    return candidate
