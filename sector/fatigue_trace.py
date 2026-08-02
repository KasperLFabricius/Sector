"""Strict CT-010a reader, independent proof, and trace construction."""

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
    TraceDependency, TraceResult, TraceStep, TraceValidationError,
    create_bundle, validate_bundle,
)
from .fatigue_trace_contract import (
    BOND05, BOND23, COVERAGE, CUSTOM, PERFECT, SN05, SN23, FamilyShape,
    Leaf, assessment_prefix, assessment_steps, bin_prefix, expected_registry,
    invalid_shape, invalid_steps, joint_steps, success_shape,
)
from .trace_registry import audit_trace_registry


SUCCESS_FIELDS = (
    "edition", "checks", "concrete_method", "basis", "method_reference",
    "calculation_references", "warnings", "partial_factors",
    "concrete_parameters", "reinforcement_properties",
    "fatigue_detail_basis", "t0_days", "elements", "spectra",
    "governing_spectrum", "utilisation", "converged", "passed",
)
INVALID_FIELDS = (
    "valid", "converged", "passed", "errors", "warnings", "edition",
    "checks", "basis", "method_reference", "calculation_references",
    "partial_factors", "concrete_parameters", "fatigue_detail_basis",
    "t0_days", "elements", "spectra", "governing_spectrum", "utilisation",
)
_LOG_MAX = math.log10(sys.float_info.max)
_LOG_MIN = math.log10(float.fromhex("0x0.0000000000001p-1022"))


def _modules():
    app = str(pathlib.Path(__file__).resolve().parent.parent / "app")
    if app not in sys.path:
        sys.path.insert(0, app)
    import fatigue_analysis  # type: ignore
    import fatigue_inputs  # type: ignore
    import material_catalog  # type: ignore
    return fatigue_analysis, fatigue_inputs, material_catalog


def _as_mapping(value, name):
    if not isinstance(value, Mapping):
        raise TraceValidationError(f"{name} must be a mapping")
    if any(type(key) is not str for key in value):
        raise TraceValidationError(f"{name} keys must be exact strings")
    return value


def _exact(left, right, name):
    if type(left) is not type(right):
        raise TraceValidationError(f"{name} retained type changed")
    if dataclasses.is_dataclass(right):
        for field in dataclasses.fields(right):
            _exact(getattr(left, field.name), getattr(right, field.name),
                   f"{name}.{field.name}")
        return
    if isinstance(right, np.ndarray):
        if (left.dtype != right.dtype or left.shape != right.shape
                or not np.array_equal(left, right, equal_nan=True)):
            raise TraceValidationError(f"{name} retained array changed")
        return
    if isinstance(right, Mapping):
        if tuple(left) != tuple(right):
            raise TraceValidationError(f"{name} inventory/order changed")
        for key in right:
            _exact(left[key], right[key], f"{name}.{key}")
        return
    if isinstance(right, (tuple, list)):
        if len(left) != len(right):
            raise TraceValidationError(f"{name} cardinality changed")
        for index, (a, b) in enumerate(zip(left, right)):
            _exact(a, b, f"{name}[{index}]")
        return
    if isinstance(right, float):
        if left != right and not (math.isnan(left) and math.isnan(right)):
            raise TraceValidationError(f"{name} value changed")
        return
    if left != right:
        raise TraceValidationError(f"{name} value changed")


def _shape(left, right, name):
    """Compare complete container/cardinality/member types, never values."""

    if type(left) is not type(right):
        raise TraceValidationError(f"{name} retained type changed")
    if dataclasses.is_dataclass(right):
        for field in dataclasses.fields(right):
            _shape(getattr(left, field.name), getattr(right, field.name),
                   f"{name}.{field.name}")
    elif isinstance(right, np.ndarray):
        if left.dtype != right.dtype or left.shape != right.shape:
            raise TraceValidationError(f"{name} retained array shape changed")
    elif isinstance(right, Mapping):
        if tuple(left) != tuple(right):
            raise TraceValidationError(f"{name} key positions changed")
        for key in right:
            _shape(left[key], right[key], f"{name}.{key}")
    elif isinstance(right, (tuple, list)):
        if len(left) != len(right):
            raise TraceValidationError(f"{name} cardinality changed")
        for index, (a, b) in enumerate(zip(left, right)):
            _shape(a, b, f"{name}[{index}]")


def _state(left, right, name):
    reinforcement = (
        "name", "description", "cycles", "converged",
        "bar_stress_long_mpa", "bar_stress_total_mpa", "elastic_result",
        "bar_stress_fatigue_total_mpa", "bond_method",
        "design_action_factor", "design_elastic_result",
        "bar_stress_design_total_mpa", "bar_stress_fatigue_design_total_mpa",
    )
    if type(left) is not type(right):
        raise TraceValidationError(f"{name} retained type changed")
    for field in reinforcement:
        _exact(getattr(left, field), getattr(right, field), f"{name}.{field}")
    for field in (
        "concrete_compression_long_mpa", "concrete_compression_total_mpa",
        "concrete_compression_design_total_mpa",
    ):
        _shape(getattr(left, field), getattr(right, field), f"{name}.{field}")


def _output_matches(candidate, replay):
    if tuple(candidate) != SUCCESS_FIELDS or tuple(replay) != SUCCESS_FIELDS:
        raise TraceValidationError("fatigue output inventory changed")
    concrete = replay["checks"]["concrete"] is True
    for key in SUCCESS_FIELDS:
        if key in {"concrete_method", "concrete_parameters", "t0_days"}:
            _shape(candidate[key], replay[key], f"fatigue output {key}")
            continue
        if key != "spectra":
            if concrete and key in {
                "governing_spectrum", "utilisation", "converged", "passed",
            }:
                _shape(candidate[key], replay[key], f"fatigue output {key}")
            else:
                _exact(candidate[key], replay[key], f"fatigue output {key}")
            continue
        if type(candidate[key]) is not tuple or len(candidate[key]) != len(replay[key]):
            raise TraceValidationError("fatigue spectra shape changed")
        for si, (actual_spectrum, expected_spectrum) in enumerate(
            zip(candidate[key], replay[key])
        ):
            if type(actual_spectrum) is not type(expected_spectrum):
                raise TraceValidationError("fatigue spectrum type changed")
            _exact(actual_spectrum.spectrum_name, expected_spectrum.spectrum_name,
                   f"spectra[{si}].name")
            if len(actual_spectrum.bins) != len(expected_spectrum.bins):
                raise TraceValidationError("fatigue bin cardinality changed")
            for bi, (actual_bin, expected_bin) in enumerate(zip(
                actual_spectrum.bins, expected_spectrum.bins
            )):
                _state(actual_bin, expected_bin, f"spectra[{si}].bins[{bi}]")
            _exact(actual_spectrum.reinforcement,
                   expected_spectrum.reinforcement,
                   f"spectra[{si}].reinforcement")
            _exact(actual_spectrum.governing_reinforcement_id,
                   expected_spectrum.governing_reinforcement_id,
                   f"spectra[{si}].governing_reinforcement")
            for field in (
                "concrete", "concrete_search", "fcd_fat_mpa",
                "governing_concrete_fibre", "concrete_method",
            ):
                _shape(getattr(actual_spectrum, field),
                       getattr(expected_spectrum, field),
                       f"spectra[{si}].{field}")
            for field in ("utilisation", "converged", "passed"):
                compare = _shape if concrete else _exact
                compare(getattr(actual_spectrum, field),
                        getattr(expected_spectrum, field),
                        f"spectra[{si}].{field}")


def _success_input_types(inp):
    for key in ("fatigue_on", "fatigue_check_steel", "fatigue_check_concrete"):
        if key not in inp or type(inp[key]) is not bool:
            raise TraceValidationError(f"{key} must be a present exact Boolean")
    if not inp["fatigue_on"] or not inp["fatigue_check_steel"]:
        raise TraceValidationError("CT-010a reinforcement fatigue is not enabled")
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


def _object_fields(value):
    """Snapshot every retained runtime law field with its concrete class."""

    identity = (type(value).__module__, type(value).__qualname__)
    if dataclasses.is_dataclass(value):
        fields = tuple(
            (field.name, getattr(value, field.name))
            for field in dataclasses.fields(value)
        )
    elif hasattr(value, "__dict__"):
        fields = tuple(sorted(vars(value).items()))
    else:
        raise TraceValidationError("runtime material law is not inspectable")
    return identity, fields


def _runtime_materials(inp):
    rows = [("concrete", _object_fields(inp["concrete"]))]
    for position, material in enumerate(inp.get("bar_materials") or ()):
        rows.append(("mild", position, _object_fields(material)))
    for position, material in enumerate(inp.get("tendon_materials") or ()):
        rows.append(("prestress", position, _object_fields(material)))
    return tuple(rows)


def _catalogs(inp):
    _analysis, fatigue_inputs, material_catalog = _modules()
    output = []
    detail_key = fatigue_inputs.DETAIL_CATALOG_KEY
    if detail_key in inp:
        raw = _as_mapping(inp[detail_key], "fatigue detail catalog")
        canonical = fatigue_inputs.normalise_catalog(raw)
        if tuple(raw) != ("version", "next_id", "items"):
            raise TraceValidationError("fatigue detail catalog inventory/order changed")
        if type(raw["items"]) is not list or len(raw["items"]) != len(canonical["items"]):
            raise TraceValidationError("fatigue detail catalog cardinality changed")
        for index, (actual, expected) in enumerate(zip(raw["items"], canonical["items"])):
            if not isinstance(actual, Mapping) or set(actual) != set(expected):
                raise TraceValidationError(f"fatigue detail item {index} inventory changed")
            for field in expected:
                _exact(actual[field], expected[field],
                       f"fatigue detail item {index}.{field}")
        output.append((detail_key, canonical))
    for kind in ("mild", "prestress"):
        key = material_catalog.catalog_key(kind)
        if key in inp:
            raw = _as_mapping(inp[key], f"{kind} material catalog")
            canonical = material_catalog.normalise_catalog(raw, kind)
            _exact(dict(raw), canonical, f"{kind} material catalog")
            output.append((key, canonical))
    return tuple(output)


def _flatten(value, path, leaves):
    if isinstance(value, np.generic):
        value = value.item()
    if type(value) in {tuple, list}:
        kind = "tuple" if type(value) is tuple else "list"
        leaves.append(Leaf(f"{path}-type-{kind}", path, float(len(value))))
        for index, item in enumerate(value):
            _flatten(item, f"{path}-i{index:04d}", leaves)
    elif isinstance(value, Mapping):
        leaves.append(Leaf(f"{path}-type-mapping", path, float(len(value))))
        for index, (key, item) in enumerate(value.items()):
            if type(key) is not str:
                raise TraceValidationError("identity keys must be text")
            _flatten(item, f"{path}-k{index:04d}-u{key.encode('utf-8').hex()}", leaves)
    elif type(value) is str:
        leaves.append(Leaf(f"{path}-text-u{value.encode('utf-8').hex()}", path, 1.0))
    elif type(value) is bool:
        leaves.append(Leaf(f"{path}-bool-{'true' if value else 'false'}", path,
                           1.0 if value else 0.0))
    elif value is None:
        leaves.append(Leaf(f"{path}-none", path, None, True))
    elif type(value) in {int, float}:
        number = float(value)
        if not math.isfinite(number):
            raise TraceValidationError(f"{path} identity must be finite")
        leaves.append(Leaf(
            f"{path}-number-{'int' if type(value) is int else 'float'}",
            path, number,
        ))
    else:
        raise TraceValidationError(f"unsupported retained identity at {path}")


def _success_leaves(inp, prepared):
    analysis, _fatigue_inputs, _material_catalog = _modules()
    material_ids = tuple(
        (record["id"], record["material_id"])
        for record in prepared.element_records
    )
    identity = (
        analysis.analysis_signature(inp),
        inp.get("concrete_material_id", inp.get("concrete_preset", "project-concrete")),
        material_ids,
        _runtime_materials(inp),
        _catalogs(inp),
    )
    leaves = []
    _flatten(identity, "fatigue-input", leaves)
    if len({leaf.step_id for leaf in leaves}) != len(leaves):
        raise TraceValidationError("fatigue input leaves are not injective")
    return tuple(leaves)


def _invalid_leaves(inp, out):
    """Retain invalid identity without laundering unsupported live objects."""

    primitive = (
        tuple(out), tuple(out["errors"]),
        tuple((key, type(inp.get(key)).__name__, repr(inp.get(key))) for key in (
            "fatigue_on", "fatigue_check_steel", "fatigue_check_concrete",
            "fatigue_edition", "fatigue_gamma_c", "fatigue_gamma_s",
            "fatigue_gamma_ff", "fatigue_concrete_method",
        )),
    )
    leaves = []
    _flatten(primitive, "invalid-fatigue-input", leaves)
    return tuple(leaves)


def _material_id(record):
    if not isinstance(record, Mapping):
        raise TraceValidationError("element record must be a mapping")
    value = record.get("material_id")
    if type(value) is not str or not value.strip():
        raise TraceValidationError("element material identity is missing")
    return value.strip()


def _method_sources(prepared, detail_id):
    detail = next(row for row in prepared.detail_records if row["id"] == detail_id)
    sn = CUSTOM if detail["custom"] else (SN23 if "2023" in prepared.edition else SN05)
    if prepared.section.bars and prepared.section.tendons:
        bond = BOND23 if "2023" in prepared.edition else BOND05
    else:
        bond = PERFECT
    return sn, bond


def _read(inp, out, context):
    inp = _as_mapping(inp, "fatigue input")
    out = _as_mapping(out, "fatigue output")
    context = {} if context is None else _as_mapping(context, "trace context")
    analysis, _fatigue_inputs, _material_catalog = _modules()
    for key in ("fatigue_on", "fatigue_check_steel", "fatigue_check_concrete"):
        if key not in inp or type(inp[key]) is not bool:
            raise TraceValidationError(f"{key} must be a present exact Boolean")
    if out.get("valid") is False:
        if tuple(out) != INVALID_FIELDS:
            raise TraceValidationError("invalid fatigue output inventory changed")
        expected = analysis.invalid_result(inp)
        _exact(dict(out), expected, "invalid fatigue output")
        return (
            invalid_shape(
                leaves=_invalid_leaves(inp, out), errors=tuple(out["errors"]),
                context=context, edition=str(out["edition"]),
                concrete_parameters_type=type(out["concrete_parameters"]).__name__,
            ),
            None,
            out,
        )
    _success_input_types(inp)
    try:
        prepared = analysis.prepare(inp)
        replay = analysis.run_analysis(inp)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"invalid CT-010a input: {exc}") from exc
    _output_matches(out, replay)
    shape_rows = []
    for spectrum_position, spectrum in enumerate(out["spectra"]):
        for element_position, (record, properties) in enumerate(zip(
            prepared.element_records, prepared.reinforcement
        )):
            found = tuple(result for result in spectrum.reinforcement
                          if result.element_id == properties.element_id)
            if len(found) != 1:
                raise TraceValidationError("element-spectrum result identity changed")
            result = found[0]
            if len(result.bins) != len(spectrum.bins):
                raise TraceValidationError("element-spectrum bin cardinality changed")
            sn, bond = _method_sources(prepared, properties.detail_id)
            shape_rows.append((
                element_position, spectrum_position, properties.element_id,
                str(properties.kind).strip().lower(), _material_id(record),
                properties.detail_id, spectrum.spectrum_name,
                tuple((index, row.bin_name, row.bond_method)
                      for index, row in enumerate(result.bins)),
                sn, bond,
            ))
    return (
        success_shape(
            leaves=_success_leaves(inp, prepared), rows=shape_rows,
            context=context, edition=prepared.edition,
            concrete_method_type=type(out["concrete_method"]).__name__,
            concrete_parameters_type=type(out["concrete_parameters"]).__name__,
        ),
        prepared,
        out,
    )


def _power10(exponent):
    if exponent == math.inf or exponent > _LOG_MAX:
        return math.inf
    if exponent == -math.inf or exponent < _LOG_MIN:
        return 0.0
    return 10.0 ** exponent


def _life(properties, stress_range, gamma_s):
    if stress_range == 0.0:
        return math.inf, math.inf, 0.0
    exponent = properties.k1 if stress_range >= properties.delta_sigma_rsk_mpa / gamma_s else properties.k2
    loglife = math.log10(properties.n_star) + exponent * math.log10(
        properties.delta_sigma_rsk_mpa / (gamma_s * stress_range)
    )
    return _power10(loglife), loglife, float(exponent)


def _log_damage(cycles, loglife):
    if cycles == 0.0 or loglife == math.inf:
        return 0.0
    return _power10(math.log10(cycles) - loglife)


def _yield_limit(stress, properties, gamma_s):
    strength = properties.fytk_mpa if stress >= 0.0 else (
        properties.fyck_mpa if properties.fyck_mpa is not None
        else properties.fytk_mpa
    )
    limit = float(strength) / gamma_s
    return limit, abs(stress) / limit


def _near(actual, expected, name):
    if math.isnan(expected):
        valid = math.isnan(actual)
    elif math.isinf(expected):
        valid = actual == expected
    else:
        valid = math.isclose(actual, expected, rel_tol=2e-12, abs_tol=2e-12)
    if not valid:
        raise TraceValidationError(f"{name} contradicts independent proof")


def _base_values(shape, prepared):
    values = {}
    for leaf in shape.leaves:
        values[leaf.step_id] = (
            TraceResult(RESULT_UNDEFINED, None, "Optional retained input is absent")
            if leaf.missing else float(leaf.value)
        )
    values["retained-fatigue-input-vector"] = 1.0
    if prepared is None:
        missing = TraceResult(RESULT_UNDEFINED, None,
                              "Invalid input has no usable partial factor")
        values.update({"input-gamma-s": missing, "input-gamma-ff": missing,
                       "input-gamma-c": missing})
    else:
        values["input-gamma-s"] = float(prepared.gamma_s)
        values["input-gamma-ff"] = float(prepared.gamma_ff)
        values["input-gamma-c"] = (
            TraceResult(RESULT_UNDEFINED, None, "Concrete sibling is disabled")
            if prepared.gamma_c is None else float(prepared.gamma_c)
        )
    values["normalised-fatigue-inputs"] = 1.0
    return values


def _assessment_values(shape, item, prepared, out):
    values = _base_values(shape, prepared)
    properties = prepared.reinforcement[item.element_position]
    spectrum = out["spectra"][item.spectrum_position]
    result = next(row for row in spectrum.reinforcement
                  if row.element_id == item.element_id)
    prefix = assessment_prefix(item)
    values.update({
        f"{prefix}-nstar": float(properties.n_star),
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
    for contract_bin, state, row in zip(item.bins, spectrum.bins, result.bins):
        bp = bin_prefix(contract_bin)
        long = float(state.bar_stress_long_mpa[item.element_position])
        elastic = float(state.bar_stress_total_mpa[item.element_position])
        fatigue_vector = state.bar_stress_fatigue_total_mpa or state.bar_stress_total_mpa
        design_vector = state.bar_stress_fatigue_design_total_mpa or fatigue_vector
        fatigue = float(fatigue_vector[item.element_position])
        design = float(design_vector[item.element_position])
        erange, frange, drange = (
            abs(elastic - long), abs(fatigue - long), abs(design - long)
        )
        bond = frange / erange if erange > 0.0 else (math.inf if frange > 0.0 else 1.0)
        life, loglife, exponent = _life(properties, drange, float(prepared.gamma_s))
        damage = _log_damage(float(state.cycles), loglife)
        long_limit, long_util = _yield_limit(long, properties, float(prepared.gamma_s))
        design_limit, design_util = _yield_limit(design, properties, float(prepared.gamma_s))
        if design_util >= long_util:
            stress, limit, yutil = design, design_limit, design_util
        else:
            stress, limit, yutil = long, long_limit, long_util
        expected = {
            "cycles": float(state.cycles), "stress_long_mpa": long,
            "stress_total_elastic_mpa": elastic,
            "stress_total_mpa": fatigue, "stress_total_design_mpa": design,
            "stress_range_elastic_mpa": erange,
            "stress_range_mpa": frange, "design_stress_range_mpa": drange,
            "bond_adjustment": bond, "sn_exponent": exponent,
            "cycles_to_failure": life, "log10_cycles_to_failure": loglife,
            "damage": damage, "governing_stress_mpa": stress,
            "yield_limit_mpa": limit, "yield_utilisation": yutil,
            "delta_sigma_rsk_mpa": float(properties.delta_sigma_rsk_mpa),
            "delta_sigma_rd_mpa": float(properties.delta_sigma_rsk_mpa) / float(prepared.gamma_s),
        }
        for field, expected_value in expected.items():
            _near(float(getattr(row, field)), expected_value, f"{bp}.{field}")
        if type(row.converged) is not bool or row.converged is not state.converged:
            raise TraceValidationError(f"{bp} combined convergence changed")
        values.update({
            f"{bp}-cycles": float(state.cycles),
            f"{bp}-converged": 1.0 if state.converged else 0.0,
            f"{bp}-long": long, f"{bp}-elastic-total": elastic,
            f"{bp}-fatigue-total": fatigue, f"{bp}-design-total": design,
            f"{bp}-elastic-range": erange, f"{bp}-fatigue-range": frange,
            f"{bp}-design-range": drange, f"{bp}-bond-factor": bond,
            f"{bp}-exponent": exponent, f"{bp}-loglife": loglife,
            f"{bp}-life": life, f"{bp}-damage": damage,
            f"{bp}-governing-stress": stress, f"{bp}-proof-limit": limit,
            f"{bp}-yield-utilisation": yutil, f"{bp}-proof": 1.0,
        })
        damages.append(damage); yields.append(yutil); convergences.append(state.converged)
    damage, yutil, converged = sum(damages), max(yields), all(convergences)
    utilisation = max(damage, yutil)
    passed = bool(converged and damage <= 1.0 and yutil <= 1.0)
    damage_index = max(range(len(damages)), key=damages.__getitem__)
    yield_index = max(range(len(yields)), key=yields.__getitem__)
    for field, expected_value in {
        "damage": damage, "damage_utilisation": damage,
        "yield_utilisation": yutil, "utilisation": utilisation,
    }.items():
        _near(float(getattr(result, field)), expected_value, f"{prefix}.{field}")
    if result.governing_damage_bin != result.bins[damage_index].bin_name:
        raise TraceValidationError("governing damage-bin identity changed")
    if result.governing_yield_bin != result.bins[yield_index].bin_name:
        raise TraceValidationError("governing yield-bin identity changed")
    if type(result.converged) is not bool or result.converged is not converged:
        raise TraceValidationError("assessment convergence changed")
    if type(result.passed) is not bool or result.passed is not passed:
        raise TraceValidationError("assessment verdict changed")
    values.update({
        f"{prefix}-damage": damage, f"{prefix}-damage-bin": float(damage_index),
        f"{prefix}-yield-utilisation": yutil,
        f"{prefix}-yield-bin": float(yield_index),
        f"{prefix}-converged": 1.0 if converged else 0.0,
        f"{prefix}-utilisation": utilisation,
        f"{prefix}-passed": 1.0 if passed else 0.0,
        f"ct-010a-{prefix}-result": utilisation,
    })
    return values, converged


def _joint_values(shape, prepared, out):
    values = _base_values(shape, prepared)
    results = []
    for item in shape.assessments:
        result = next(row for row in out["spectra"][item.spectrum_position].reinforcement
                      if row.element_id == item.element_id)
        prefix = f"published-{assessment_prefix(item)}"
        values.update({
            f"{prefix}-damage": float(result.damage),
            f"{prefix}-yield-utilisation": float(result.yield_utilisation),
            f"{prefix}-converged": 1.0 if result.converged else 0.0,
            f"{prefix}-utilisation": float(result.utilisation),
            f"{prefix}-passed": 1.0 if result.passed else 0.0,
        })
        results.append(result)
    converged = all(row.converged for row in results)
    utilisation = max((float(row.utilisation) for row in results), default=0.0)
    passed = all(row.passed for row in results)
    values.update({
        "reinforcement-output-converged": 1.0 if converged else 0.0,
        "reinforcement-output-utilisation": utilisation,
        "reinforcement-output-passed": 1.0 if passed else 0.0,
        "ct-010a-reinforcement-output-result": utilisation,
    })
    return values, converged


def _result(value):
    if isinstance(value, TraceResult):
        return value
    number = float(value)
    if math.isnan(number):
        return TraceResult(RESULT_UNDEFINED, None, "Retained result is undefined")
    if number == math.inf:
        return TraceResult(RESULT_POSITIVE_INFINITY, None, "Retained result overflowed")
    if number == -math.inf:
        return TraceResult(RESULT_NEGATIVE_INFINITY, None,
                           "Retained result is negative infinity")
    return TraceResult(RESULT_FINITE, number)


def _calculation(calculation_id, title, axes, step_contract, values,
                 converged, failed_reason=None):
    units = {step.step_id: step.unit for step in step_contract}
    final_id = step_contract[-1].step_id
    steps = []
    for contract in step_contract:
        if contract.step_id not in values:
            raise TraceValidationError(f"internal value omitted {contract.step_id}")
        result = _result(values[contract.step_id])
        if contract.step_id == final_id and (failed_reason is not None or not converged):
            result = TraceResult(
                RESULT_FAILED, None,
                failed_reason or "An original or equivalent-area solve failed",
            )
        steps.append(TraceStep(
            contract.step_id, contract.title,
            tuple(TraceDependency(dependency, units[dependency])
                  for dependency in contract.dependencies),
            contract.role, contract.source, contract.step_id, contract.unit,
            f"Bind {contract.title.lower()}",
            (f"{contract.step_id} = {result.value:.17g} {contract.unit.symbol}"
             if result.state == RESULT_FINITE
             else f"{contract.step_id} = {result.state}"),
            result,
        ))
    return TraceCalculation(
        calculation_id, COVERAGE, title,
        "sector-reinforcement-fatigue-independent-spectra", axes,
        final_id, tuple(steps),
        assumptions=(
            "Spectrum groups remain independent.",
            "Combined convergence includes any equivalent-tendon-area solve.",
            "Concrete values are excluded but their complete shape is pinned.",
        ),
    )


def _calculations(shape: FamilyShape, prepared, out):
    if shape.branch == "invalid":
        contracts = invalid_steps(shape)
        values = _base_values(shape, None)
        for contract in contracts:
            values.setdefault(contract.step_id, 1.0)
        return (_calculation(
            shape.invalid.calculation_id, "Invalid fatigue boundary",
            shape.invalid.axes, contracts, values, False,
            "; ".join(shape.invalid.errors) or "Retained fatigue payload is invalid",
        ),)
    calculations = []
    for item in shape.assessments:
        values, converged = _assessment_values(shape, item, prepared, out)
        calculations.append(_calculation(
            item.calculation_id, f"Reinforcement fatigue: {item.element_id}",
            item.axes, assessment_steps(shape, item), values, converged,
        ))
    values, converged = _joint_values(shape, prepared, out)
    calculations.append(_calculation(
        shape.joint.calculation_id, "Reinforcement fatigue output",
        shape.joint.axes, joint_steps(shape), values, converged,
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
        raise TraceValidationError("CT-010a candidate differs from independent replay")
    return candidate
