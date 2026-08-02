"""Build closed CT-010a reinforcement-fatigue calculation traces."""

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
    BOND_2005_SOURCE, BOND_2023_SOURCE, COVERAGE_ID, CUSTOM_SN_SOURCE,
    METHOD_ID, PERFECT_BOND_SOURCE, SN_2005_SOURCE, SN_2023_SOURCE, Leaf,
    aggregate_steps, assessment_steps, bin_prefix, expected_registry,
    invalid_model, invalid_steps, member_prefix, success_model,
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
_LOG10_MAX = math.log10(sys.float_info.max)
_LOG10_MIN = math.log10(float.fromhex("0x0.0000000000001p-1022"))


def _app_modules():
    app_path = str(pathlib.Path(__file__).resolve().parent.parent / "app")
    if app_path not in sys.path:
        sys.path.insert(0, app_path)
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


def _compare_exact(actual, expected, label):
    if type(actual) is not type(expected):
        raise TraceValidationError(f"{label} retained type changed")
    if dataclasses.is_dataclass(expected):
        for field in dataclasses.fields(expected):
            _compare_exact(
                getattr(actual, field.name), getattr(expected, field.name),
                f"{label}.{field.name}",
            )
    elif isinstance(expected, np.ndarray):
        if (
            actual.dtype != expected.dtype
            or actual.shape != expected.shape
            or not np.array_equal(actual, expected, equal_nan=True)
        ):
            raise TraceValidationError(f"{label} retained array changed")
    elif isinstance(expected, Mapping):
        if tuple(actual) != tuple(expected):
            raise TraceValidationError(f"{label} inventory/order changed")
        for key in expected:
            _compare_exact(actual[key], expected[key], f"{label}.{key}")
    elif isinstance(expected, (tuple, list)):
        if len(actual) != len(expected):
            raise TraceValidationError(f"{label} cardinality changed")
        for index, (left, right) in enumerate(zip(actual, expected)):
            _compare_exact(left, right, f"{label}[{index}]")
    elif isinstance(expected, float):
        if actual != expected and not (math.isnan(actual) and math.isnan(expected)):
            raise TraceValidationError(f"{label} value changed")
    elif actual != expected:
        raise TraceValidationError(f"{label} value changed")


def _compare_shape(actual, expected, label):
    if type(actual) is not type(expected):
        raise TraceValidationError(f"{label} retained type changed")
    if dataclasses.is_dataclass(expected):
        for field in dataclasses.fields(expected):
            _compare_shape(
                getattr(actual, field.name), getattr(expected, field.name),
                f"{label}.{field.name}",
            )
    elif isinstance(expected, np.ndarray):
        if actual.dtype != expected.dtype or actual.shape != expected.shape:
            raise TraceValidationError(f"{label} retained array shape changed")
    elif isinstance(expected, Mapping):
        if tuple(actual) != tuple(expected):
            raise TraceValidationError(f"{label} key positions changed")
        for key in expected:
            _compare_shape(actual[key], expected[key], f"{label}.{key}")
    elif isinstance(expected, (tuple, list)):
        if len(actual) != len(expected):
            raise TraceValidationError(f"{label} cardinality changed")
        for index, (left, right) in enumerate(zip(actual, expected)):
            _compare_shape(left, right, f"{label}[{index}]")


def _compare_bin(actual, expected, label):
    if type(actual) is not type(expected):
        raise TraceValidationError(f"{label} retained type changed")
    for field in (
        "name", "description", "cycles", "converged",
        "bar_stress_long_mpa", "bar_stress_total_mpa", "elastic_result",
        "bar_stress_fatigue_total_mpa", "bond_method", "design_action_factor",
        "design_elastic_result", "bar_stress_design_total_mpa",
        "bar_stress_fatigue_design_total_mpa",
    ):
        _compare_exact(
            getattr(actual, field), getattr(expected, field), f"{label}.{field}"
        )
    for field in (
        "concrete_compression_long_mpa", "concrete_compression_total_mpa",
        "concrete_compression_design_total_mpa",
    ):
        _compare_shape(
            getattr(actual, field), getattr(expected, field), f"{label}.{field}"
        )


def _compare_success(actual, replay):
    if tuple(actual) != SUCCESS_KEYS or tuple(replay) != SUCCESS_KEYS:
        raise TraceValidationError("fatigue output inventory changed")
    concrete_enabled = replay["checks"]["concrete"] is True
    for key in SUCCESS_KEYS:
        if key in {"concrete_method", "concrete_parameters", "t0_days"}:
            _compare_shape(actual[key], replay[key], f"output.{key}")
        elif key == "spectra":
            continue
        elif concrete_enabled and key in {
            "governing_spectrum", "utilisation", "converged", "passed",
        }:
            _compare_shape(actual[key], replay[key], f"output.{key}")
        else:
            _compare_exact(actual[key], replay[key], f"output.{key}")
    left_spectra, right_spectra = actual["spectra"], replay["spectra"]
    if type(left_spectra) is not tuple or type(right_spectra) is not tuple:
        raise TraceValidationError("fatigue spectra must be retained tuples")
    if len(left_spectra) != len(right_spectra):
        raise TraceValidationError("fatigue spectrum cardinality changed")
    for spectrum_index, (left, right) in enumerate(zip(left_spectra, right_spectra)):
        label = f"spectra[{spectrum_index}]"
        if type(left) is not type(right):
            raise TraceValidationError(f"{label} retained type changed")
        _compare_exact(left.spectrum_name, right.spectrum_name, f"{label}.name")
        if type(left.bins) is not tuple or len(left.bins) != len(right.bins):
            raise TraceValidationError(f"{label} bin shape changed")
        for bin_index, (left_bin, right_bin) in enumerate(zip(left.bins, right.bins)):
            _compare_bin(left_bin, right_bin, f"{label}.bins[{bin_index}]")
        _compare_exact(left.reinforcement, right.reinforcement,
                       f"{label}.reinforcement")
        _compare_exact(left.governing_reinforcement_id,
                       right.governing_reinforcement_id,
                       f"{label}.governing_reinforcement_id")
        for field in (
            "concrete", "concrete_search", "fcd_fat_mpa",
            "governing_concrete_fibre", "concrete_method",
        ):
            _compare_shape(getattr(left, field), getattr(right, field),
                           f"{label}.{field}")
        for field in ("utilisation", "converged", "passed"):
            compare = _compare_shape if concrete_enabled else _compare_exact
            compare(getattr(left, field), getattr(right, field), f"{label}.{field}")


def _validate_success_input(inp):
    for key in ("fatigue_on", "fatigue_check_steel", "fatigue_check_concrete"):
        if key not in inp or type(inp[key]) is not bool:
            raise TraceValidationError(f"{key} must be a present exact Boolean")
    if not inp["fatigue_on"] or not inp["fatigue_check_steel"]:
        raise TraceValidationError("CT-010a reinforcement fatigue is disabled")
    for key in (
        "fatigue_gamma_c", "fatigue_gamma_s", "fatigue_gamma_ff",
        "fatigue_beta_cc_t0", "fatigue_t0_days", "fatigue_concrete_k1",
        "fatigue_concrete_c", "nl", "ns",
    ):
        value = inp.get(key)
        if value is not None and (
            type(value) not in {int, float} or not math.isfinite(float(value))
        ):
            raise TraceValidationError(f"{key} must be a finite non-Boolean number")
    for key in (
        "bar_elements", "tendon_elements", "bar_materials", "tendon_materials",
    ):
        if type(inp.get(key)) is not list:
            raise TraceValidationError(f"{key} must be a retained list")


def _type_identity(value):
    return type(value).__module__, type(value).__qualname__


def _law_identity(value):
    if dataclasses.is_dataclass(value):
        fields = tuple(
            (field.name, getattr(value, field.name))
            for field in dataclasses.fields(value)
        )
    elif hasattr(value, "__dict__"):
        fields = tuple(sorted(vars(value).items()))
    else:
        raise TraceValidationError("runtime material law is not inspectable")
    return _type_identity(value), fields


def _runtime_laws(inp):
    if "concrete" not in inp:
        concrete = ("key-absent",)
    elif inp["concrete"] is None:
        concrete = ("present-null",)
    else:
        concrete = ("present-law", _law_identity(inp["concrete"]))
    mild = tuple(
        (position, _law_identity(material))
        for position, material in enumerate(inp["bar_materials"])
    )
    prestress = tuple(
        (position, _law_identity(material))
        for position, material in enumerate(inp["tendon_materials"])
    )
    return concrete, mild, prestress


def _catalogs(inp):
    _analysis, fatigue_inputs, material_catalog = _app_modules()
    result = []
    detail_key = fatigue_inputs.DETAIL_CATALOG_KEY
    if detail_key in inp:
        raw = inp[detail_key]
        if type(raw) is not dict:
            raise TraceValidationError("fatigue detail catalog must be a retained dict")
        normal = fatigue_inputs.normalise_catalog(raw)
        if tuple(raw) != ("version", "next_id", "items"):
            raise TraceValidationError("fatigue detail catalog inventory changed")
        _compare_exact(raw["version"], normal["version"], "detail version")
        _compare_exact(raw["next_id"], normal["next_id"], "detail next ID")
        if type(raw["items"]) is not list or len(raw["items"]) != len(normal["items"]):
            raise TraceValidationError("fatigue detail catalog item shape changed")
        for index, (actual, expected) in enumerate(zip(raw["items"], normal["items"])):
            if type(actual) is not dict or set(actual) != set(expected):
                raise TraceValidationError(f"fatigue detail {index} inventory changed")
            for field in expected:
                _compare_exact(actual[field], expected[field],
                               f"fatigue detail {index}.{field}")
        result.append((detail_key, normal))
    for kind in ("mild", "prestress"):
        key = material_catalog.catalog_key(kind)
        if key not in inp:
            continue
        raw = inp[key]
        if type(raw) is not dict:
            raise TraceValidationError(f"{kind} catalog must be a retained dict")
        normal = material_catalog.normalise_catalog(raw, kind)
        _compare_exact(raw, normal, f"{kind} material catalog")
        result.append((key, normal))
    return tuple(result)


def _flatten(value, path, leaves):
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, np.ndarray):
        dtype = str(value.dtype).encode("utf-8").hex()
        leaves.append(Leaf(f"{path}-ndarray-{dtype}", path, float(value.size)))
        _flatten(tuple(value.shape), f"{path}-shape", leaves)
        for index, item in enumerate(value.flat):
            _flatten(item, f"{path}-v{index:05d}", leaves)
    elif type(value) in {tuple, list}:
        kind = "tuple" if type(value) is tuple else "list"
        leaves.append(Leaf(f"{path}-{kind}", path, float(len(value))))
        for index, item in enumerate(value):
            _flatten(item, f"{path}-i{index:04d}", leaves)
    elif isinstance(value, Mapping):
        mapping_type = "-".join(_type_identity(value)).encode("utf-8").hex()
        leaves.append(Leaf(f"{path}-mapping-{mapping_type}", path,
                           float(len(value))))
        for index, (key, item) in enumerate(value.items()):
            if type(key) is not str:
                raise TraceValidationError("retained identity keys must be strings")
            _flatten(item, f"{path}-k{index:04d}-u{key.encode('utf-8').hex()}",
                     leaves)
    elif dataclasses.is_dataclass(value):
        _flatten(_law_identity(value), f"{path}-dataclass", leaves)
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
        leaves.append(Leaf(f"{path}-number-{type(value).__name__}", path, number))
    else:
        raise TraceValidationError(f"unsupported retained identity at {path}")


def _success_leaves(inp, prepared):
    analysis, _fatigue_inputs, _material_catalog = _app_modules()
    if "concrete" not in inp:
        concrete_identity = ("key-absent",)
    elif inp["concrete"] is None:
        concrete_identity = ("present-null",)
    else:
        concrete_identity = (
            "present-law",
            inp.get("concrete_material_id",
                    inp.get("concrete_preset", "project-concrete")),
        )
    material_ids = tuple(
        (record["id"], record["material_id"])
        for record in prepared.element_records
    )
    identity = (
        analysis.analysis_signature(inp), concrete_identity, material_ids,
        _runtime_laws(inp), _catalogs(inp),
    )
    leaves = []
    _flatten(identity, "fatigue-input", leaves)
    if len({leaf.step_id for leaf in leaves}) != len(leaves):
        raise TraceValidationError("fatigue input identity is not injective")
    return tuple(leaves)


def _invalid_leaves(inp, out):
    raw = (
        tuple(out),
        tuple(out["errors"]),
        tuple(
            (key, type(inp.get(key)).__name__, repr(inp.get(key)))
            for key in (
                "fatigue_on", "fatigue_check_steel", "fatigue_check_concrete",
                "fatigue_edition", "fatigue_gamma_c", "fatigue_gamma_s",
                "fatigue_gamma_ff", "fatigue_concrete_method",
            )
        ),
    )
    leaves = []
    _flatten(raw, "invalid-fatigue-input", leaves)
    return tuple(leaves)


def _material_id(record):
    if not isinstance(record, Mapping):
        raise TraceValidationError("element record must be a mapping")
    value = record.get("material_id")
    if type(value) is not str or not value.strip():
        raise TraceValidationError("element material identity is missing")
    return value.strip()


def _sources(prepared, detail_id):
    detail = next(
        record for record in prepared.detail_records if record["id"] == detail_id
    )
    sn_source = CUSTOM_SN_SOURCE if detail["custom"] else (
        SN_2023_SOURCE if "2023" in prepared.edition else SN_2005_SOURCE
    )
    if prepared.section.bars and prepared.section.tendons:
        bond_source = (
            BOND_2023_SOURCE if "2023" in prepared.edition else BOND_2005_SOURCE
        )
    else:
        bond_source = PERFECT_BOND_SOURCE
    return sn_source, bond_source


def _read(inp, out, context):
    inp = _mapping(inp, "fatigue input")
    out = _mapping(out, "fatigue output")
    context = {} if context is None else _mapping(context, "trace context")
    analysis, _fatigue_inputs, _material_catalog = _app_modules()

    # Deliberately select the retained invalid branch before success-only typing.
    # The application supports incomplete inputs and invalid_result must remain
    # traceable even when flags are absent or malformed.
    if out.get("valid") is False:
        if tuple(out) != INVALID_KEYS:
            raise TraceValidationError("invalid fatigue output inventory changed")
        expected = analysis.invalid_result(inp)
        _compare_exact(dict(out), expected, "invalid fatigue output")
        return (
            invalid_model(
                leaves=_invalid_leaves(inp, out),
                errors=tuple(out["errors"]),
                context=context,
                edition=str(out["edition"]),
                concrete_parameters_type=type(out["concrete_parameters"]).__name__,
            ),
            None,
            out,
        )

    _validate_success_input(inp)
    try:
        prepared = analysis.prepare(inp)
        replay = analysis.run_analysis(inp)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"invalid CT-010a input: {exc}") from exc
    _compare_success(out, replay)
    rows = []
    for spectrum_position, spectrum in enumerate(out["spectra"]):
        for element_position, (record, properties) in enumerate(zip(
            prepared.element_records, prepared.reinforcement
        )):
            matches = tuple(
                result for result in spectrum.reinforcement
                if result.element_id == properties.element_id
            )
            if len(matches) != 1:
                raise TraceValidationError("element-spectrum identity changed")
            result = matches[0]
            if len(result.bins) != len(spectrum.bins):
                raise TraceValidationError("element-spectrum bin shape changed")
            sn_source, bond_source = _sources(prepared, properties.detail_id)
            rows.append((
                element_position,
                spectrum_position,
                properties.element_id,
                str(properties.kind).strip().lower(),
                _material_id(record),
                properties.detail_id,
                spectrum.spectrum_name,
                tuple(
                    (index, row.bin_name, row.bond_method)
                    for index, row in enumerate(result.bins)
                ),
                sn_source,
                bond_source,
            ))
    return (
        success_model(
            leaves=_success_leaves(inp, prepared), rows=rows, context=context,
            edition=prepared.edition,
            concrete_method_type=type(out["concrete_method"]).__name__,
            concrete_parameters_type=type(out["concrete_parameters"]).__name__,
        ),
        prepared,
        out,
    )


def _pow10(exponent):
    if exponent == math.inf or exponent > _LOG10_MAX:
        return math.inf
    if exponent == -math.inf or exponent < _LOG10_MIN:
        return 0.0
    return 10.0 ** exponent


def _sn_life(properties, stress_range, gamma_s):
    if stress_range == 0.0:
        return math.inf, math.inf, 0.0
    transition = properties.delta_sigma_rsk_mpa / gamma_s
    exponent = properties.k1 if stress_range >= transition else properties.k2
    logarithm = (
        math.log10(properties.n_star)
        + exponent * math.log10(transition / stress_range)
    )
    return _pow10(logarithm), logarithm, float(exponent)


def _damage_from_log(cycles, loglife):
    if cycles == 0.0 or loglife == math.inf:
        return 0.0
    return _pow10(math.log10(cycles) - loglife)


def _yield_proof(stress, properties, gamma_s):
    strength = properties.fytk_mpa
    if stress < 0.0 and properties.fyck_mpa is not None:
        strength = properties.fyck_mpa
    limit = float(strength) / gamma_s
    return limit, abs(stress) / limit


def _assert_near(actual, expected, label):
    if math.isnan(expected):
        valid = math.isnan(actual)
    elif math.isinf(expected):
        valid = actual == expected
    else:
        valid = math.isclose(actual, expected, rel_tol=2e-12, abs_tol=2e-12)
    if not valid:
        raise TraceValidationError(f"{label} contradicts independent proof")


def _root_values(family, prepared):
    values = {}
    for leaf in family.leaves:
        values[leaf.step_id] = (
            TraceResult(RESULT_UNDEFINED, None, "Optional input is absent")
            if leaf.absent else float(leaf.value)
        )
    values["fatigue-input-vector"] = 1.0
    if prepared is None:
        absent = TraceResult(
            RESULT_UNDEFINED, None, "Invalid input has no usable partial factor"
        )
        values.update({
            "input-gamma-s": absent,
            "input-gamma-ff": absent,
            "input-gamma-c": absent,
        })
    else:
        values["input-gamma-s"] = float(prepared.gamma_s)
        values["input-gamma-ff"] = float(prepared.gamma_ff)
        values["input-gamma-c"] = (
            TraceResult(RESULT_UNDEFINED, None, "Concrete sibling is disabled")
            if prepared.gamma_c is None else float(prepared.gamma_c)
        )
    values["normalised-fatigue-inputs"] = 1.0
    return values


def _select_vector(primary, fallback):
    return primary if len(primary) else fallback


def _assessment_values(family, member, prepared, out):
    values = _root_values(family, prepared)
    properties = prepared.reinforcement[member.element_position]
    spectrum = out["spectra"][member.spectrum_position]
    result = next(
        row for row in spectrum.reinforcement if row.element_id == member.element_id
    )
    prefix = member_prefix(member)
    values.update({
        f"{prefix}-nstar": float(properties.n_star),
        f"{prefix}-k1": float(properties.k1),
        f"{prefix}-k2": float(properties.k2),
        f"{prefix}-reference": float(properties.delta_sigma_rsk_mpa),
        f"{prefix}-tension-proof": float(properties.fytk_mpa),
        f"{prefix}-compression-proof": float(
            properties.fyck_mpa
            if properties.fyck_mpa is not None
            else properties.fytk_mpa
        ),
    })
    damages, yields, convergences = [], [], []
    for bin_model, state, row in zip(member.bins, spectrum.bins, result.bins):
        bp = bin_prefix(bin_model)
        position = member.element_position
        long_stress = float(state.bar_stress_long_mpa[position])
        elastic_stress = float(state.bar_stress_total_mpa[position])
        fatigue_vector = _select_vector(
            state.bar_stress_fatigue_total_mpa, state.bar_stress_total_mpa
        )
        design_vector = _select_vector(
            state.bar_stress_fatigue_design_total_mpa, fatigue_vector
        )
        fatigue_stress = float(fatigue_vector[position])
        design_stress = float(design_vector[position])
        elastic_range = abs(elastic_stress - long_stress)
        fatigue_range = abs(fatigue_stress - long_stress)
        design_range = abs(design_stress - long_stress)
        if elastic_range > 0.0:
            bond_factor = fatigue_range / elastic_range
        elif fatigue_range > 0.0:
            bond_factor = math.inf
        else:
            bond_factor = 1.0
        life, loglife, exponent = _sn_life(
            properties, design_range, float(prepared.gamma_s)
        )
        damage = _damage_from_log(float(state.cycles), loglife)
        long_limit, long_util = _yield_proof(
            long_stress, properties, float(prepared.gamma_s)
        )
        design_limit, design_util = _yield_proof(
            design_stress, properties, float(prepared.gamma_s)
        )
        if design_util >= long_util:
            governing_stress, yield_limit, yield_util = (
                design_stress, design_limit, design_util
            )
        else:
            governing_stress, yield_limit, yield_util = (
                long_stress, long_limit, long_util
            )
        expected = {
            "cycles": float(state.cycles),
            "stress_long_mpa": long_stress,
            "stress_total_elastic_mpa": elastic_stress,
            "stress_total_mpa": fatigue_stress,
            "stress_total_design_mpa": design_stress,
            "stress_range_elastic_mpa": elastic_range,
            "stress_range_mpa": fatigue_range,
            "design_stress_range_mpa": design_range,
            "bond_adjustment": bond_factor,
            "sn_exponent": exponent,
            "cycles_to_failure": life,
            "log10_cycles_to_failure": loglife,
            "damage": damage,
            "governing_stress_mpa": governing_stress,
            "yield_limit_mpa": yield_limit,
            "yield_utilisation": yield_util,
            "delta_sigma_rsk_mpa": float(properties.delta_sigma_rsk_mpa),
            "delta_sigma_rd_mpa": (
                float(properties.delta_sigma_rsk_mpa) / float(prepared.gamma_s)
            ),
        }
        for field, expected_value in expected.items():
            _assert_near(float(getattr(row, field)), expected_value,
                         f"{bp}.{field}")
        if type(row.converged) is not bool or row.converged is not state.converged:
            raise TraceValidationError(f"{bp} combined convergence changed")
        values.update({
            f"{bp}-cycles": float(state.cycles),
            f"{bp}-converged": 1.0 if state.converged else 0.0,
            f"{bp}-long": long_stress,
            f"{bp}-elastic": elastic_stress,
            f"{bp}-fatigue": fatigue_stress,
            f"{bp}-design": design_stress,
            f"{bp}-elastic-range": elastic_range,
            f"{bp}-fatigue-range": fatigue_range,
            f"{bp}-design-range": design_range,
            f"{bp}-bond-factor": bond_factor,
            f"{bp}-exponent": exponent,
            f"{bp}-loglife": loglife,
            f"{bp}-life": life,
            f"{bp}-damage": damage,
            f"{bp}-governing-stress": governing_stress,
            f"{bp}-yield-limit": yield_limit,
            f"{bp}-yield-utilisation": yield_util,
            f"{bp}-proof": 1.0,
        })
        damages.append(damage)
        yields.append(yield_util)
        convergences.append(state.converged)
    total_damage = sum(damages)
    maximum_yield = max(yields)
    converged = all(convergences)
    utilisation = max(total_damage, maximum_yield)
    passed = bool(converged and total_damage <= 1.0 and maximum_yield <= 1.0)
    damage_index = max(range(len(damages)), key=damages.__getitem__)
    yield_index = max(range(len(yields)), key=yields.__getitem__)
    for field, expected_value in {
        "damage": total_damage,
        "damage_utilisation": total_damage,
        "yield_utilisation": maximum_yield,
        "utilisation": utilisation,
    }.items():
        _assert_near(float(getattr(result, field)), expected_value,
                     f"{prefix}.{field}")
    if result.governing_damage_bin != result.bins[damage_index].bin_name:
        raise TraceValidationError("governing damage-bin identity changed")
    if result.governing_yield_bin != result.bins[yield_index].bin_name:
        raise TraceValidationError("governing yield-bin identity changed")
    if type(result.converged) is not bool or result.converged is not converged:
        raise TraceValidationError("assessment convergence changed")
    if type(result.passed) is not bool or result.passed is not passed:
        raise TraceValidationError("assessment verdict changed")
    values.update({
        f"{prefix}-damage": total_damage,
        f"{prefix}-damage-bin": float(damage_index),
        f"{prefix}-yield-utilisation": maximum_yield,
        f"{prefix}-yield-bin": float(yield_index),
        f"{prefix}-converged": 1.0 if converged else 0.0,
        f"{prefix}-utilisation": utilisation,
        f"{prefix}-passed": 1.0 if passed else 0.0,
        f"ct-010a-{prefix}-result": utilisation,
    })
    return values, converged


def _aggregate_values(family, prepared, out):
    values = _root_values(family, prepared)
    results = []
    for member in family.members:
        result = next(
            row for row in out["spectra"][member.spectrum_position].reinforcement
            if row.element_id == member.element_id
        )
        prefix = f"published-{member_prefix(member)}"
        values.update({
            f"{prefix}-damage": float(result.damage),
            f"{prefix}-yield-utilisation": float(result.yield_utilisation),
            f"{prefix}-converged": 1.0 if result.converged else 0.0,
            f"{prefix}-utilisation": float(result.utilisation),
            f"{prefix}-passed": 1.0 if result.passed else 0.0,
        })
        results.append(result)
    converged = all(result.converged for result in results)
    utilisation = max(
        (float(result.utilisation) for result in results), default=0.0
    )
    passed = all(result.passed for result in results)
    values.update({
        "reinforcement-output-converged": 1.0 if converged else 0.0,
        "reinforcement-output-utilisation": utilisation,
        "reinforcement-output-passed": 1.0 if passed else 0.0,
        "ct-010a-reinforcement-output-result": utilisation,
    })
    return values, converged


def _trace_result(value):
    if isinstance(value, TraceResult):
        return value
    number = float(value)
    if math.isnan(number):
        return TraceResult(RESULT_UNDEFINED, None, "Retained result is undefined")
    if number == math.inf:
        return TraceResult(RESULT_POSITIVE_INFINITY, None,
                           "Retained result overflowed")
    if number == -math.inf:
        return TraceResult(RESULT_NEGATIVE_INFINITY, None,
                           "Retained result is negative infinity")
    return TraceResult(RESULT_FINITE, number)


def _calculation(calculation_id, title, axes, contracts, values, converged,
                 failed_reason=None):
    units = {contract.step_id: contract.unit for contract in contracts}
    final_id = contracts[-1].step_id
    steps = []
    for contract in contracts:
        if contract.step_id not in values:
            raise TraceValidationError(f"internal value omitted {contract.step_id}")
        result = _trace_result(values[contract.step_id])
        if contract.step_id == final_id and (
            failed_reason is not None or not converged
        ):
            result = TraceResult(
                RESULT_FAILED, None,
                failed_reason or "An original or equivalent-area solve failed",
            )
        steps.append(TraceStep(
            contract.step_id,
            contract.title,
            tuple(
                TraceDependency(dependency, units[dependency])
                for dependency in contract.dependencies
            ),
            contract.role,
            contract.source,
            contract.step_id,
            contract.unit,
            f"Bind {contract.title.lower()}",
            (
                f"{contract.step_id} = {result.value:.17g} {contract.unit.symbol}"
                if result.state == RESULT_FINITE
                else f"{contract.step_id} = {result.state}"
            ),
            result,
        ))
    return TraceCalculation(
        calculation_id, COVERAGE_ID, title, METHOD_ID, axes, final_id,
        tuple(steps),
        assumptions=(
            "Spectrum groups are independent.",
            "Combined convergence retains the equivalent-area solve outcome.",
            "Concrete values are excluded while their complete shape is pinned.",
        ),
    )


def _calculations(family, prepared, out):
    if family.branch == "invalid":
        contracts = invalid_steps(family)
        values = _root_values(family, None)
        for contract in contracts:
            values.setdefault(contract.step_id, 1.0)
        return (_calculation(
            f"fatigue.{family.context_token}.invalid",
            "Invalid fatigue boundary",
            family.invalid_axes,
            contracts,
            values,
            False,
            "; ".join(family.errors) or "Retained fatigue payload is invalid",
        ),)
    calculations = []
    for member in family.members:
        values, converged = _assessment_values(family, member, prepared, out)
        calculations.append(_calculation(
            member.calculation_id,
            f"Reinforcement fatigue: {member.element_id}",
            member.axes,
            assessment_steps(family, member),
            values,
            converged,
        ))
    values, converged = _aggregate_values(family, prepared, out)
    calculations.append(_calculation(
        f"fatigue.{family.context_token}.reinforcement-output",
        "Reinforcement fatigue output",
        family.aggregate_axes,
        aggregate_steps(family),
        values,
        converged,
    ))
    return tuple(calculations)


def _expected_bundle(inp, out, input_sha256, result_sha256, context):
    family, prepared, retained = _read(inp, out, context)
    bundle = create_bundle(
        input_sha256=input_sha256,
        result_sha256=result_sha256,
        calculations=_calculations(family, prepared, retained),
    )
    audit_trace_registry(bundle, expected_registry(family))
    return bundle


def build_fatigue_trace_family(inp, out, *, input_sha256, result_sha256,
                               context=None):
    """Build and seal the complete CT-010a family."""

    try:
        return _expected_bundle(inp, out, input_sha256, result_sha256, context)
    except TraceValidationError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"invalid CT-010a evidence: {exc}") from exc


def validate_fatigue_trace_family(bundle, inp, out, *, input_sha256,
                                  result_sha256, context=None):
    """Reject stale or coherently resealed CT-010a tampering."""

    candidate = validate_bundle(
        bundle,
        expected_input_sha256=input_sha256,
        expected_result_sha256=result_sha256,
    )
    expected = _expected_bundle(inp, out, input_sha256, result_sha256, context)
    if candidate.to_dict() != expected.to_dict():
        raise TraceValidationError("CT-010a trace differs from independent replay")
    return candidate
