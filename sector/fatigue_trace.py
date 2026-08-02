"""CT-010a reinforcement-fatigue trace builder and exact reader."""

from __future__ import annotations

import dataclasses
import math
import pathlib
import sys
from collections.abc import Mapping
import numpy as np

from .calculation_trace import (
    RESULT_FAILED, RESULT_FINITE, RESULT_NEGATIVE_INFINITY,
    RESULT_POSITIVE_INFINITY, RESULT_UNDEFINED, TraceCalculation,
    TraceDependency, TraceResult, TraceStep,
    TraceValidationError, create_bundle, validate_bundle,
)
from .fatigue_trace_contract import (
    BOND05, BOND23, COVERAGE_ID, CUSTOM_SN, METHOD_ID, PERFECT_BOND,
    SN05, SN23, InputLeaf, bin_prefix,
    expected_registry, invalid_steps, make_shape, member_prefix, member_steps,
    output_steps,
)
from .trace_registry import audit_trace_registry


SUCCESS_KEYS = (
    "edition", "checks", "concrete_method", "basis", "method_reference",
    "calculation_references", "warnings", "partial_factors",
    "concrete_parameters", "reinforcement_properties",
    "fatigue_detail_basis", "t0_days", "elements", "spectra",
    "governing_spectrum", "utilisation", "converged", "passed",
)
INVALID_KEYS = (
    "valid", "converged", "passed", "errors", "warnings", "edition",
    "checks", "basis", "method_reference", "calculation_references",
    "partial_factors", "concrete_parameters", "fatigue_detail_basis",
    "t0_days", "elements", "spectra", "governing_spectrum", "utilisation",
)
_MAX_LOG = math.log10(sys.float_info.max)
_MIN_LOG = math.log10(float.fromhex("0x0.0000000000001p-1022"))


def _app():
    path = str(pathlib.Path(__file__).resolve().parent.parent / "app")
    if path not in sys.path:
        sys.path.insert(0, path)
    import fatigue_analysis  # type: ignore
    import fatigue_inputs  # type: ignore
    import material_catalog  # type: ignore
    return fatigue_analysis, fatigue_inputs, material_catalog


def _mapping(value, label):
    if not isinstance(value, Mapping):
        raise TraceValidationError(f"{label} must be a mapping")
    if any(type(key) is not str for key in value):
        raise TraceValidationError(f"{label} keys must be exact strings")
    return value


def _equal(actual, expected, label):
    if type(actual) is not type(expected):
        raise TraceValidationError(f"{label} retained type differs from replay")
    if dataclasses.is_dataclass(expected):
        for field in dataclasses.fields(expected):
            _equal(getattr(actual, field.name), getattr(expected, field.name),
                   f"{label}.{field.name}")
    elif isinstance(expected, np.ndarray):
        if (actual.dtype != expected.dtype or actual.shape != expected.shape
                or not np.array_equal(actual, expected, equal_nan=True)):
            raise TraceValidationError(f"{label} array differs from replay")
    elif isinstance(expected, Mapping):
        if tuple(actual) != tuple(expected):
            raise TraceValidationError(f"{label} inventory/order differs from replay")
        for key in expected:
            _equal(actual[key], expected[key], f"{label}.{key}")
    elif isinstance(expected, (tuple, list)):
        if len(actual) != len(expected):
            raise TraceValidationError(f"{label} cardinality differs from replay")
        for index, (left, right) in enumerate(zip(actual, expected)):
            _equal(left, right, f"{label}[{index}]")
    elif isinstance(expected, float):
        if actual != expected and not (math.isnan(actual) and math.isnan(expected)):
            raise TraceValidationError(f"{label} differs from replay")
    elif actual != expected:
        raise TraceValidationError(f"{label} differs from replay")


def _same_shape(actual, expected, label):
    """Pin exact retained container shape and every concrete Python type."""

    if type(actual) is not type(expected):
        raise TraceValidationError(f"{label} retained type differs from replay")
    if dataclasses.is_dataclass(expected):
        for field in dataclasses.fields(expected):
            _same_shape(
                getattr(actual, field.name), getattr(expected, field.name),
                f"{label}.{field.name}",
            )
    elif isinstance(expected, np.ndarray):
        if actual.dtype != expected.dtype or actual.shape != expected.shape:
            raise TraceValidationError(f"{label} retained array shape differs")
    elif isinstance(expected, Mapping):
        if tuple(actual) != tuple(expected):
            raise TraceValidationError(f"{label} retained key positions differ")
        for key in expected:
            _same_shape(actual[key], expected[key], f"{label}.{key}")
    elif isinstance(expected, (tuple, list)):
        if len(actual) != len(expected):
            raise TraceValidationError(f"{label} retained cardinality differs")
        for index, (left, right) in enumerate(zip(actual, expected)):
            _same_shape(left, right, f"{label}[{index}]")


def _compare_state(actual, expected, label):
    if type(actual) is not type(expected):
        raise TraceValidationError(f"{label} retained type differs from replay")
    reinforcement_fields = (
        "name", "description", "cycles", "converged",
        "bar_stress_long_mpa", "bar_stress_total_mpa", "elastic_result",
        "bar_stress_fatigue_total_mpa", "bond_method",
        "design_action_factor", "design_elastic_result",
        "bar_stress_design_total_mpa", "bar_stress_fatigue_design_total_mpa",
    )
    for field in reinforcement_fields:
        _equal(getattr(actual, field), getattr(expected, field),
               f"{label}.{field}")
    for field in (
        "concrete_compression_long_mpa", "concrete_compression_total_mpa",
        "concrete_compression_design_total_mpa",
    ):
        _same_shape(getattr(actual, field), getattr(expected, field),
                    f"{label}.{field}")


def _compare_output(actual, replay):
    if tuple(actual) != SUCCESS_KEYS or tuple(replay) != SUCCESS_KEYS:
        raise TraceValidationError("fatigue output inventory drifted")
    concrete_enabled = replay["checks"]["concrete"] is True
    for key in SUCCESS_KEYS:
        if key in {"concrete_method", "concrete_parameters", "t0_days"}:
            _same_shape(actual[key], replay[key], f"fatigue output {key}")
        elif key == "spectra":
            if type(actual[key]) is not tuple or len(actual[key]) != len(replay[key]):
                raise TraceValidationError("fatigue spectra retained shape differs")
            for spectrum_index, (left, right) in enumerate(zip(actual[key], replay[key])):
                if type(left) is not type(right):
                    raise TraceValidationError("fatigue spectrum type differs")
                _equal(left.spectrum_name, right.spectrum_name,
                       f"spectra[{spectrum_index}].name")
                if len(left.bins) != len(right.bins):
                    raise TraceValidationError("fatigue bin cardinality differs")
                for bin_index, (left_bin, right_bin) in enumerate(zip(left.bins, right.bins)):
                    _compare_state(left_bin, right_bin,
                                   f"spectra[{spectrum_index}].bins[{bin_index}]")
                _equal(left.reinforcement, right.reinforcement,
                       f"spectra[{spectrum_index}].reinforcement")
                _equal(left.governing_reinforcement_id,
                       right.governing_reinforcement_id,
                       f"spectra[{spectrum_index}].governing_reinforcement_id")
                for field in (
                    "concrete", "concrete_search", "fcd_fat_mpa",
                    "governing_concrete_fibre", "concrete_method",
                ):
                    _same_shape(getattr(left, field), getattr(right, field),
                                f"spectra[{spectrum_index}].{field}")
                for field in ("utilisation", "converged", "passed"):
                    comparator = _same_shape if concrete_enabled else _equal
                    comparator(getattr(left, field), getattr(right, field),
                               f"spectra[{spectrum_index}].{field}")
        elif concrete_enabled and key in {
            "governing_spectrum", "utilisation", "converged", "passed",
        }:
            _same_shape(actual[key], replay[key], f"fatigue output {key}")
        else:
            _equal(actual[key], replay[key], f"fatigue output {key}")


def _validate_success_types(inp):
    for key in ("fatigue_on", "fatigue_check_steel", "fatigue_check_concrete"):
        if key not in inp or type(inp[key]) is not bool:
            raise TraceValidationError(f"{key} must be a present exact Boolean")
    if not inp["fatigue_on"] or not inp["fatigue_check_steel"]:
        raise TraceValidationError("CT-010a requires reinforcement fatigue")
    for key in (
        "fatigue_gamma_c", "fatigue_gamma_s", "fatigue_gamma_ff",
        "fatigue_beta_cc_t0", "fatigue_t0_days", "fatigue_concrete_k1",
        "fatigue_concrete_c", "nl", "ns",
    ):
        value = inp.get(key)
        if value is not None and (
            type(value) not in {int, float} or type(value) is bool
            or not math.isfinite(float(value))
        ):
            raise TraceValidationError(f"{key} must be a finite non-Boolean number")
    for key in ("bar_elements", "tendon_elements", "bar_materials", "tendon_materials"):
        if type(inp.get(key)) is not list:
            raise TraceValidationError(f"{key} must be a retained list")


def _canonical_catalogs(inp):
    analysis, fatigue_inputs, material_catalog = _app()
    del analysis
    catalogs = []
    detail_key = fatigue_inputs.DETAIL_CATALOG_KEY
    if detail_key in inp:
        raw = _mapping(inp[detail_key], "fatigue detail catalog")
        normal = fatigue_inputs.normalise_catalog(raw)
        if tuple(raw) != ("version", "next_id", "items"):
            raise TraceValidationError("fatigue detail catalog inventory/order drifted")
        if type(raw["items"]) is not list or len(raw["items"]) != len(normal["items"]):
            raise TraceValidationError("fatigue detail catalog shape drifted")
        for index, (left, right) in enumerate(zip(raw["items"], normal["items"])):
            if not isinstance(left, Mapping) or set(left) != set(right):
                raise TraceValidationError(f"fatigue detail item {index} inventory drifted")
            for field in right:
                _equal(left[field], right[field], f"fatigue detail item {index}.{field}")
        catalogs.append((detail_key, normal))
    for kind in ("mild", "prestress"):
        key = material_catalog.catalog_key(kind)
        if key in inp:
            raw = _mapping(inp[key], f"{kind} material catalog")
            normal = material_catalog.normalise_catalog(raw, kind)
            _equal(dict(raw), normal, f"{kind} material catalog")
            catalogs.append((key, normal))
    return tuple(catalogs)


def _flatten(value, path, leaves):
    if isinstance(value, np.generic):
        value = value.item()
    if type(value) in {tuple, list}:
        kind = "tuple" if type(value) is tuple else "list"
        leaves.append(InputLeaf(f"{path}-type-{kind}", path, float(len(value))))
        for index, item in enumerate(value):
            _flatten(item, f"{path}-i{index:04d}", leaves)
    elif isinstance(value, Mapping):
        leaves.append(InputLeaf(f"{path}-type-mapping", path, float(len(value))))
        for index, (key, item) in enumerate(value.items()):
            if type(key) is not str:
                raise TraceValidationError("identity mapping keys must be text")
            _flatten(item, f"{path}-k{index:04d}-u{key.encode('utf-8').hex()}", leaves)
    elif type(value) is str:
        leaves.append(InputLeaf(
            f"{path}-text-u{value.encode('utf-8').hex()}", path, 1.0
        ))
    elif type(value) is bool:
        leaves.append(InputLeaf(
            f"{path}-bool-{'true' if value else 'false'}", path,
            1.0 if value else 0.0,
        ))
    elif value is None:
        leaves.append(InputLeaf(f"{path}-none", path, None, True))
    elif type(value) in {int, float}:
        number = float(value)
        if not math.isfinite(number):
            raise TraceValidationError(f"{path} identity must be finite")
        leaves.append(InputLeaf(
            f"{path}-number-{'int' if type(value) is int else 'float'}",
            path, number,
        ))
    else:
        raise TraceValidationError(f"unsupported identity type at {path}")


def _identity(inp, prepared):
    analysis, _fatigue_inputs, _material_catalog = _app()
    material_identity = (
        inp.get("concrete_material_id", inp.get("concrete_preset", "project-concrete")),
        tuple((record["id"], record["material_id"])
              for record in prepared.element_records),
    )
    raw = (
        analysis.analysis_signature(inp), material_identity,
        _canonical_catalogs(inp),
    )
    leaves = []
    _flatten(raw, "fatigue-input", leaves)
    if len({leaf.step_id for leaf in leaves}) != len(leaves):
        raise TraceValidationError("fatigue input leaves are not injective")
    return tuple(leaves)


def _material_id(record, kind):
    if not isinstance(record, Mapping):
        raise TraceValidationError("element record must be a mapping")
    value = record.get("material_id")
    if type(value) is not str or not value.strip():
        raise TraceValidationError(f"{kind} material identity is missing")
    return value.strip()


def _sources(prepared, element_index, detail_id):
    detail = next(item for item in prepared.detail_records if item["id"] == detail_id)
    sn = CUSTOM_SN if detail["custom"] else (SN23 if "2023" in prepared.edition else SN05)
    mixed = bool(prepared.section.bars and prepared.section.tendons)
    bond = (BOND23 if "2023" in prepared.edition else BOND05) if mixed else PERFECT_BOND
    return sn, bond


def _read(inp, out, context):
    inp = _mapping(inp, "fatigue input")
    out = _mapping(out, "fatigue output")
    context = {} if context is None else _mapping(context, "trace context")
    analysis, _fatigue_inputs, _material_catalog = _app()
    for key in ("fatigue_on", "fatigue_check_steel", "fatigue_check_concrete"):
        if key not in inp or type(inp[key]) is not bool:
            raise TraceValidationError(f"{key} must be a present exact Boolean")
    if out.get("valid") is False:
        if tuple(out) != INVALID_KEYS:
            raise TraceValidationError("invalid fatigue inventory drifted")
        expected = analysis.invalid_result(inp)
        _equal(dict(out), expected, "invalid fatigue output")
        leaves = []
        _flatten((tuple(expected["errors"]), tuple(out)), "invalid-input", leaves)
        shape = make_shape(
            leaves=leaves, members_data=(), context=context,
            edition=str(expected["edition"]),
            concrete_method_type="none",
            concrete_parameters_type=type(out["concrete_parameters"]).__name__,
            invalid_errors=tuple(expected["errors"]),
        )
        return shape, None, out
    _validate_success_types(inp)
    try:
        prepared = analysis.prepare(inp)
        replay = analysis.run_analysis(inp)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"invalid CT-010a input: {exc}") from exc
    _compare_output(out, replay)
    members = []
    for spectrum_index, spectrum in enumerate(out["spectra"]):
        for element_index, (record, properties) in enumerate(zip(
            prepared.element_records, prepared.reinforcement
        )):
            matches = tuple(item for item in spectrum.reinforcement
                            if item.element_id == properties.element_id)
            if len(matches) != 1:
                raise TraceValidationError("element-spectrum result identity drifted")
            result = matches[0]
            if len(result.bins) != len(spectrum.bins):
                raise TraceValidationError("element-spectrum bin cardinality drifted")
            sn, bond = _sources(prepared, element_index, properties.detail_id)
            members.append((
                element_index, spectrum_index, properties.element_id,
                str(properties.kind).strip().lower(),
                _material_id(record, str(properties.kind)), properties.detail_id,
                spectrum.spectrum_name,
                tuple((index, row.bin_name, row.bond_method)
                      for index, row in enumerate(result.bins)),
                sn, bond,
            ))
    shape = make_shape(
        leaves=_identity(inp, prepared), members_data=members, context=context,
        edition=prepared.edition,
        concrete_method_type=type(out["concrete_method"]).__name__,
        concrete_parameters_type=type(out["concrete_parameters"]).__name__,
    )
    return shape, prepared, out


def _pow10(value):
    if value == math.inf or value > _MAX_LOG:
        return math.inf
    if value == -math.inf or value < _MIN_LOG:
        return 0.0
    return 10.0 ** value


def _sn(properties, stress_range, gamma_s):
    if stress_range == 0.0:
        return math.inf, math.inf, 0.0
    exponent = properties.k1 if stress_range >= properties.delta_sigma_rsk_mpa / gamma_s else properties.k2
    loglife = math.log10(properties.n_star) + exponent * math.log10(
        properties.delta_sigma_rsk_mpa / (gamma_s * stress_range)
    )
    return _pow10(loglife), loglife, float(exponent)


def _damage(cycles, loglife):
    if cycles == 0.0 or loglife == math.inf:
        return 0.0
    return _pow10(math.log10(cycles) - loglife)


def _yield(stress, properties, gamma_s):
    characteristic = properties.fytk_mpa if stress >= 0.0 else (
        properties.fyck_mpa if properties.fyck_mpa is not None
        else properties.fytk_mpa
    )
    limit = float(characteristic) / gamma_s
    return limit, abs(stress) / limit


def _close(actual, expected, label):
    if math.isnan(expected):
        matched = math.isnan(actual)
    elif math.isinf(expected):
        matched = actual == expected
    else:
        matched = math.isclose(actual, expected, rel_tol=2e-12, abs_tol=2e-12)
    if not matched:
        raise TraceValidationError(f"{label} contradicts independent proof")


def _common(shape, prepared):
    values = {}
    for leaf in shape.leaves:
        values[leaf.step_id] = (
            TraceResult(RESULT_UNDEFINED, None, "Retained optional input is absent")
            if leaf.absent else float(leaf.value)
        )
    values["fatigue-input-vector"] = 1.0
    if prepared is None:
        for key in ("input-gamma-s", "input-gamma-ff", "input-gamma-c"):
            values[key] = TraceResult(RESULT_UNDEFINED, None,
                                      "Invalid boundary has no usable factor")
    else:
        values["input-gamma-s"] = float(prepared.gamma_s)
        values["input-gamma-ff"] = float(prepared.gamma_ff)
        values["input-gamma-c"] = (
            TraceResult(RESULT_UNDEFINED, None, "Concrete sibling is disabled")
            if prepared.gamma_c is None else float(prepared.gamma_c)
        )
    values["normalised-fatigue-inputs"] = 1.0
    return values


def _member_values(shape, member, prepared, out):
    values = _common(shape, prepared)
    properties = prepared.reinforcement[member.element_index]
    spectrum = out["spectra"][member.spectrum_index]
    result = next(item for item in spectrum.reinforcement
                  if item.element_id == member.element_id)
    prefix = member_prefix(member)
    values.update({
        f"{prefix}-n-star": float(properties.n_star),
        f"{prefix}-k1": float(properties.k1),
        f"{prefix}-k2": float(properties.k2),
        f"{prefix}-reference-range": float(properties.delta_sigma_rsk_mpa),
        f"{prefix}-tension-proof": float(properties.fytk_mpa),
        f"{prefix}-compression-proof": float(
            properties.fyck_mpa if properties.fyck_mpa is not None
            else properties.fytk_mpa
        ),
    })
    damages, yields, convergences = [], [], []
    for bin_shape, state, row in zip(member.bins, spectrum.bins, result.bins):
        bp = bin_prefix(member, bin_shape)
        long = float(state.bar_stress_long_mpa[member.element_index])
        elastic_total = float(state.bar_stress_total_mpa[member.element_index])
        fatigue_vector = state.bar_stress_fatigue_total_mpa or state.bar_stress_total_mpa
        design_vector = state.bar_stress_fatigue_design_total_mpa or fatigue_vector
        fatigue_total = float(fatigue_vector[member.element_index])
        design_total = float(design_vector[member.element_index])
        elastic_range = abs(elastic_total - long)
        fatigue_range = abs(fatigue_total - long)
        design_range = abs(design_total - long)
        bond = fatigue_range / elastic_range if elastic_range > 0.0 else (
            math.inf if fatigue_range > 0.0 else 1.0
        )
        life, loglife, exponent = _sn(properties, design_range,
                                      float(prepared.gamma_s))
        damage = _damage(float(state.cycles), loglife)
        long_limit, long_util = _yield(long, properties, float(prepared.gamma_s))
        design_limit, design_util = _yield(design_total, properties,
                                           float(prepared.gamma_s))
        if design_util >= long_util:
            governing_stress, limit, yutil = design_total, design_limit, design_util
        else:
            governing_stress, limit, yutil = long, long_limit, long_util
        expected = dict(
            cycles=float(state.cycles), stress_long_mpa=long,
            stress_total_elastic_mpa=elastic_total,
            stress_total_mpa=fatigue_total,
            stress_total_design_mpa=design_total,
            stress_range_elastic_mpa=elastic_range,
            stress_range_mpa=fatigue_range,
            design_stress_range_mpa=design_range, bond_adjustment=bond,
            sn_exponent=exponent, cycles_to_failure=life,
            log10_cycles_to_failure=loglife, damage=damage,
            governing_stress_mpa=governing_stress, yield_limit_mpa=limit,
            yield_utilisation=yutil,
            delta_sigma_rsk_mpa=float(properties.delta_sigma_rsk_mpa),
            delta_sigma_rd_mpa=float(properties.delta_sigma_rsk_mpa) / float(prepared.gamma_s),
        )
        for field, expected_value in expected.items():
            _close(float(getattr(row, field)), expected_value, f"{bp}.{field}")
        if type(row.converged) is not bool or row.converged is not state.converged:
            raise TraceValidationError(f"{bp} combined convergence drifted")
        values.update({
            f"{bp}-cycles": float(state.cycles),
            f"{bp}-combined-convergence": 1.0 if state.converged else 0.0,
            f"{bp}-long-stress": long, f"{bp}-elastic-total": elastic_total,
            f"{bp}-fatigue-total": fatigue_total,
            f"{bp}-design-total": design_total,
            f"{bp}-elastic-range": elastic_range,
            f"{bp}-fatigue-range": fatigue_range,
            f"{bp}-design-range": design_range,
            f"{bp}-bond-factor": bond, f"{bp}-sn-exponent": exponent,
            f"{bp}-log10-life": loglife, f"{bp}-life": life,
            f"{bp}-damage": damage, f"{bp}-governing-stress": governing_stress,
            f"{bp}-yield-limit": limit, f"{bp}-yield-utilisation": yutil,
            f"{bp}-proof": 1.0,
        })
        damages.append(damage); yields.append(yutil); convergences.append(state.converged)
    damage = sum(damages)
    yutil = max(yields)
    convergence = all(convergences)
    utilisation = max(damage, yutil)
    passed = bool(convergence and damage <= 1.0 and yutil <= 1.0)
    damage_index = max(range(len(damages)), key=damages.__getitem__)
    yield_index = max(range(len(yields)), key=yields.__getitem__)
    checks = {
        "damage": damage, "damage_utilisation": damage,
        "yield_utilisation": yutil, "utilisation": utilisation,
    }
    for field, expected_value in checks.items():
        _close(float(getattr(result, field)), expected_value, f"{prefix}.{field}")
    if result.governing_damage_bin != result.bins[damage_index].bin_name:
        raise TraceValidationError("governing damage-bin identity drifted")
    if result.governing_yield_bin != result.bins[yield_index].bin_name:
        raise TraceValidationError("governing yield-bin identity drifted")
    if type(result.converged) is not bool or result.converged is not convergence:
        raise TraceValidationError("spectrum convergence drifted")
    if type(result.passed) is not bool or result.passed is not passed:
        raise TraceValidationError("spectrum verdict drifted")
    values.update({
        f"{prefix}-damage": damage,
        f"{prefix}-governing-damage-bin": float(damage_index),
        f"{prefix}-yield-utilisation": yutil,
        f"{prefix}-governing-yield-bin": float(yield_index),
        f"{prefix}-converged": 1.0 if convergence else 0.0,
        f"{prefix}-utilisation": utilisation,
        f"{prefix}-passed": 1.0 if passed else 0.0,
        f"ct-010a-{prefix}-result": utilisation,
    })
    return values, convergence, result


def _output_values(shape, prepared, out):
    values = _common(shape, prepared)
    results = []
    for member in shape.members:
        result = next(item for item in out["spectra"][member.spectrum_index].reinforcement
                      if item.element_id == member.element_id)
        prefix = f"output-{member_prefix(member)}"
        values.update({
            f"{prefix}-damage": float(result.damage),
            f"{prefix}-yield-utilisation": float(result.yield_utilisation),
            f"{prefix}-converged": 1.0 if result.converged else 0.0,
            f"{prefix}-utilisation": float(result.utilisation),
            f"{prefix}-passed": 1.0 if result.passed else 0.0,
        })
        results.append(result)
    convergence = all(item.converged for item in results)
    utilisation = max((float(item.utilisation) for item in results), default=0.0)
    passed = all(item.passed for item in results)
    values.update({
        "reinforcement-output-converged": 1.0 if convergence else 0.0,
        "reinforcement-output-utilisation": utilisation,
        "reinforcement-output-passed": 1.0 if passed else 0.0,
        "ct-010a-reinforcement-output-result": utilisation,
    })
    return values, convergence


def _trace_result(value):
    if isinstance(value, TraceResult):
        return value
    value = float(value)
    if math.isnan(value):
        return TraceResult(RESULT_UNDEFINED, None, "Retained result is undefined")
    if value == math.inf:
        return TraceResult(RESULT_POSITIVE_INFINITY, None, "Retained result overflowed")
    if value == -math.inf:
        return TraceResult(RESULT_NEGATIVE_INFINITY, None, "Retained result is negative infinity")
    return TraceResult(RESULT_FINITE, value)


def _calculation(calculation_id, title, axes, specs, values, converged,
                 failure_reason=None):
    units = {item.step_id: item.unit for item in specs}
    final_id = specs[-1].step_id
    steps = []
    for spec in specs:
        if spec.step_id not in values:
            raise TraceValidationError(f"internal value omitted {spec.step_id}")
        result = _trace_result(values[spec.step_id])
        if spec.step_id == final_id and (failure_reason is not None or not converged):
            result = TraceResult(RESULT_FAILED, None, failure_reason or
                                 "A retained original or equivalent-area solve failed")
        steps.append(TraceStep(
            spec.step_id, spec.title,
            tuple(TraceDependency(item, units[item]) for item in spec.dependencies),
            spec.role, spec.source, spec.step_id, spec.unit,
            f"Bind {spec.title.lower()}",
            (f"{spec.step_id} = {result.value:.17g} {spec.unit.symbol}"
             if result.state == RESULT_FINITE else f"{spec.step_id} = {result.state}"),
            result,
        ))
    return TraceCalculation(
        calculation_id, COVERAGE_ID, title, METHOD_ID, axes, final_id,
        tuple(steps),
        assumptions=(
            "Spectrum groups are independent; damage is summed only within one spectrum.",
            "Combined convergence preserves the original and equivalent-area solve outcome.",
            "Concrete values are excluded while their complete retained shape is pinned.",
        ),
    )


def _calculations(shape, prepared, out):
    if shape.invalid is not None:
        values = _common(shape, None)
        for spec in invalid_steps(shape):
            values.setdefault(spec.step_id, 1.0)
        reason = "; ".join(shape.invalid.errors)
        return (_calculation(shape.invalid.calculation_id, "Invalid fatigue boundary",
                             shape.invalid.axes, invalid_steps(shape), values,
                             False, reason),)
    calculations = []
    for member in shape.members:
        values, converged, _result = _member_values(shape, member, prepared, out)
        calculations.append(_calculation(
            member.calculation_id,
            f"Reinforcement fatigue: {member.element_id}", member.axes,
            member_steps(shape, member), values, converged,
        ))
    values, converged = _output_values(shape, prepared, out)
    calculations.append(_calculation(
        shape.output.calculation_id, "Reinforcement fatigue output",
        shape.output.axes, output_steps(shape), values, converged,
    ))
    return tuple(calculations)


def _expected(inp, out, input_sha256, result_sha256, context):
    shape, prepared, retained = _read(inp, out, context)
    bundle = create_bundle(
        input_sha256=input_sha256, result_sha256=result_sha256,
        calculations=_calculations(shape, prepared, retained),
    )
    audit_trace_registry(bundle, expected_registry(shape))
    return bundle


def build_fatigue_trace_family(inp, out, *, input_sha256, result_sha256,
                               context=None):
    try:
        return _expected(inp, out, input_sha256, result_sha256, context)
    except TraceValidationError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"invalid CT-010a evidence: {exc}") from exc


def validate_fatigue_trace_family(bundle, inp, out, *, input_sha256,
                                  result_sha256, context=None):
    candidate = validate_bundle(
        bundle, expected_input_sha256=input_sha256,
        expected_result_sha256=result_sha256,
    )
    expected = _expected(inp, out, input_sha256, result_sha256, context)
    if candidate.to_dict() != expected.to_dict():
        raise TraceValidationError("CT-010a trace differs from independent replay")
    return candidate
