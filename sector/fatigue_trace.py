"""Build and independently validate CT-010a reinforcement-fatigue traces."""

from __future__ import annotations

import dataclasses
import math
import pathlib
import sys
from collections.abc import Mapping

import numpy as np

from .calculation_trace import (
    RESULT_FAILED,
    RESULT_FINITE,
    RESULT_NEGATIVE_INFINITY,
    RESULT_POSITIVE_INFINITY,
    RESULT_UNDEFINED,
    TraceCalculation,
    TraceDependency,
    TraceResult,
    TraceStep,
    TraceValidationError,
    create_bundle,
    validate_bundle,
)
from .fatigue_trace_contract import (
    BOND_2005_SOURCE,
    BOND_2023_SOURCE,
    COVERAGE_ID,
    CUSTOM_SN_SOURCE,
    METHOD_ID,
    PERFECT_BOND_SOURCE,
    SN_2005_SOURCE,
    SN_2023_SOURCE,
    RootLeaf,
    aggregate_steps,
    assessment_prefix,
    assessment_steps,
    bin_prefix,
    expected_registry,
    invalid_steps,
    make_invalid_spec,
    make_success_spec,
)
from .trace_registry import audit_trace_registry


SUCCESS_KEYS = (
    "edition",
    "checks",
    "concrete_method",
    "basis",
    "method_reference",
    "calculation_references",
    "warnings",
    "partial_factors",
    "concrete_parameters",
    "reinforcement_properties",
    "fatigue_detail_basis",
    "t0_days",
    "elements",
    "spectra",
    "governing_spectrum",
    "utilisation",
    "converged",
    "passed",
)
INVALID_KEYS = (
    "valid",
    "converged",
    "passed",
    "errors",
    "warnings",
    "edition",
    "checks",
    "basis",
    "method_reference",
    "calculation_references",
    "partial_factors",
    "concrete_parameters",
    "fatigue_detail_basis",
    "t0_days",
    "elements",
    "spectra",
    "governing_spectrum",
    "utilisation",
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


def _as_mapping(value, label):
    if not isinstance(value, Mapping):
        raise TraceValidationError(f"{label} must be a mapping")
    if any(type(key) is not str for key in value):
        raise TraceValidationError(f"{label} keys must be exact strings")
    return value


def _same_value(actual, expected, label):
    """Compare the retained value, including every nested concrete type."""

    if type(actual) is not type(expected):
        raise TraceValidationError(f"{label} retained type changed")
    if dataclasses.is_dataclass(expected):
        for field in dataclasses.fields(expected):
            _same_value(getattr(actual, field.name), getattr(expected, field.name),
                        f"{label}.{field.name}")
        return
    if isinstance(expected, np.ndarray):
        if (
            actual.dtype != expected.dtype
            or actual.shape != expected.shape
            or not np.array_equal(actual, expected, equal_nan=True)
        ):
            raise TraceValidationError(f"{label} retained array changed")
        return
    if isinstance(expected, Mapping):
        if tuple(actual) != tuple(expected):
            raise TraceValidationError(f"{label} inventory/order changed")
        for key in expected:
            _same_value(actual[key], expected[key], f"{label}.{key}")
        return
    if isinstance(expected, (tuple, list)):
        if len(actual) != len(expected):
            raise TraceValidationError(f"{label} cardinality changed")
        for index, (left, right) in enumerate(zip(actual, expected)):
            _same_value(left, right, f"{label}[{index}]")
        return
    if isinstance(expected, float):
        if actual == expected or (math.isnan(actual) and math.isnan(expected)):
            return
    elif actual == expected:
        return
    raise TraceValidationError(f"{label} value changed")


def _same_shape(actual, expected, label):
    """Pin an excluded sibling's complete shape while ignoring scalar values."""

    if type(actual) is not type(expected):
        raise TraceValidationError(f"{label} retained type changed")
    if dataclasses.is_dataclass(expected):
        for field in dataclasses.fields(expected):
            _same_shape(getattr(actual, field.name), getattr(expected, field.name),
                        f"{label}.{field.name}")
    elif isinstance(expected, np.ndarray):
        if actual.dtype != expected.dtype or actual.shape != expected.shape:
            raise TraceValidationError(f"{label} retained array shape changed")
    elif isinstance(expected, Mapping):
        if tuple(actual) != tuple(expected):
            raise TraceValidationError(f"{label} key positions changed")
        for key in expected:
            _same_shape(actual[key], expected[key], f"{label}.{key}")
    elif isinstance(expected, (tuple, list)):
        if len(actual) != len(expected):
            raise TraceValidationError(f"{label} cardinality changed")
        for index, (left, right) in enumerate(zip(actual, expected)):
            _same_shape(left, right, f"{label}[{index}]")


def _compare_bin(actual, expected, label):
    exact_fields = (
        "name",
        "description",
        "cycles",
        "converged",
        "bar_stress_long_mpa",
        "bar_stress_total_mpa",
        "elastic_result",
        "bar_stress_fatigue_total_mpa",
        "bond_method",
        "design_action_factor",
        "design_elastic_result",
        "bar_stress_design_total_mpa",
        "bar_stress_fatigue_design_total_mpa",
    )
    if type(actual) is not type(expected):
        raise TraceValidationError(f"{label} retained type changed")
    for field in exact_fields:
        _same_value(getattr(actual, field), getattr(expected, field),
                    f"{label}.{field}")
    for field in (
        "concrete_compression_long_mpa",
        "concrete_compression_total_mpa",
        "concrete_compression_design_total_mpa",
    ):
        _same_shape(getattr(actual, field), getattr(expected, field),
                    f"{label}.{field}")


def _compare_success(actual, replay):
    if tuple(actual) != SUCCESS_KEYS or tuple(replay) != SUCCESS_KEYS:
        raise TraceValidationError("fatigue output inventory changed")
    concrete_enabled = replay["checks"]["concrete"] is True
    excluded_top = {"concrete_method", "concrete_parameters", "t0_days"}
    concrete_aggregate = {"governing_spectrum", "utilisation", "converged", "passed"}
    for key in SUCCESS_KEYS:
        if key == "spectra":
            continue
        if key in excluded_top or (concrete_enabled and key in concrete_aggregate):
            _same_shape(actual[key], replay[key], f"output.{key}")
        else:
            _same_value(actual[key], replay[key], f"output.{key}")
    left_spectra = actual["spectra"]
    right_spectra = replay["spectra"]
    if type(left_spectra) is not tuple or type(right_spectra) is not tuple:
        raise TraceValidationError("fatigue spectra must be retained tuples")
    if len(left_spectra) != len(right_spectra):
        raise TraceValidationError("fatigue spectrum cardinality changed")
    for spectrum_index, (left, right) in enumerate(zip(left_spectra, right_spectra)):
        label = f"spectra[{spectrum_index}]"
        if type(left) is not type(right):
            raise TraceValidationError(f"{label} retained type changed")
        _same_value(left.spectrum_name, right.spectrum_name, f"{label}.name")
        if type(left.bins) is not tuple or len(left.bins) != len(right.bins):
            raise TraceValidationError(f"{label} bin shape changed")
        for bin_index, (left_bin, right_bin) in enumerate(zip(left.bins, right.bins)):
            _compare_bin(left_bin, right_bin, f"{label}.bins[{bin_index}]")
        _same_value(left.reinforcement, right.reinforcement,
                    f"{label}.reinforcement")
        _same_value(left.governing_reinforcement_id,
                    right.governing_reinforcement_id,
                    f"{label}.governing_reinforcement_id")
        for field in (
            "concrete",
            "concrete_search",
            "fcd_fat_mpa",
            "governing_concrete_fibre",
            "concrete_method",
        ):
            _same_shape(getattr(left, field), getattr(right, field),
                        f"{label}.{field}")
        for field in ("utilisation", "converged", "passed"):
            compare = _same_shape if concrete_enabled else _same_value
            compare(getattr(left, field), getattr(right, field), f"{label}.{field}")


def _validate_success_input(inp):
    for key in ("fatigue_on", "fatigue_check_steel", "fatigue_check_concrete"):
        if key not in inp or type(inp[key]) is not bool:
            raise TraceValidationError(f"{key} must be a present exact Boolean")
    if not inp["fatigue_on"] or not inp["fatigue_check_steel"]:
        raise TraceValidationError("CT-010a reinforcement fatigue is disabled")
    for key in (
        "fatigue_gamma_c",
        "fatigue_gamma_s",
        "fatigue_gamma_ff",
        "fatigue_beta_cc_t0",
        "fatigue_t0_days",
        "fatigue_concrete_k1",
        "fatigue_concrete_c",
        "nl",
        "ns",
    ):
        value = inp.get(key)
        if value is not None and (
            type(value) not in {int, float} or not math.isfinite(float(value))
        ):
            raise TraceValidationError(f"{key} must be a finite non-Boolean number")
    for key in (
        "bar_elements",
        "tendon_elements",
        "bar_materials",
        "tendon_materials",
    ):
        if type(inp.get(key)) is not list:
            raise TraceValidationError(f"{key} must be a retained list")


def _type_name(value):
    return type(value).__module__, type(value).__qualname__


def _object_signature(value):
    if dataclasses.is_dataclass(value):
        fields = tuple(
            (field.name, getattr(value, field.name))
            for field in dataclasses.fields(value)
        )
    elif hasattr(value, "__dict__"):
        fields = tuple(sorted(vars(value).items()))
    else:
        raise TraceValidationError("runtime material law is not inspectable")
    return _type_name(value), fields


def _runtime_material_identity(inp):
    if "concrete" not in inp:
        concrete = ("key-absent",)
    elif inp["concrete"] is None:
        concrete = ("present-null",)
    else:
        concrete = ("present-law", _object_signature(inp["concrete"]))
    mild = tuple(
        (index, _object_signature(material))
        for index, material in enumerate(inp["bar_materials"])
    )
    prestress = tuple(
        (index, _object_signature(material))
        for index, material in enumerate(inp["tendon_materials"])
    )
    return concrete, mild, prestress


def _catalog_identity(inp):
    _analysis, fatigue_inputs, material_catalog = _app_modules()
    identities = []
    detail_key = fatigue_inputs.DETAIL_CATALOG_KEY
    if detail_key in inp:
        raw = inp[detail_key]
        if type(raw) is not dict:
            raise TraceValidationError("fatigue detail catalog must be a retained dict")
        normal = fatigue_inputs.normalise_catalog(raw)
        if tuple(raw) != ("version", "next_id", "items"):
            raise TraceValidationError("fatigue detail catalog inventory changed")
        _same_value(raw["version"], normal["version"],
                    "fatigue detail catalog.version")
        _same_value(raw["next_id"], normal["next_id"],
                    "fatigue detail catalog.next_id")
        if type(raw["items"]) is not list or len(raw["items"]) != len(normal["items"]):
            raise TraceValidationError("fatigue detail catalog item shape changed")
        for index, (actual, expected) in enumerate(zip(raw["items"], normal["items"])):
            if type(actual) is not dict or set(actual) != set(expected):
                raise TraceValidationError(
                    f"fatigue detail catalog item {index} inventory changed"
                )
            for field in expected:
                _same_value(actual[field], expected[field],
                            f"fatigue detail catalog.items[{index}].{field}")
        identities.append((detail_key, normal))
    for kind in ("mild", "prestress"):
        key = material_catalog.catalog_key(kind)
        if key not in inp:
            continue
        raw = inp[key]
        if type(raw) is not dict:
            raise TraceValidationError(f"{kind} material catalog must be a retained dict")
        normal = material_catalog.normalise_catalog(raw, kind)
        _same_value(raw, normal, f"{kind} material catalog")
        identities.append((key, normal))
    return tuple(identities)


def _append_identity(value, path, leaves):
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, np.ndarray):
        dtype = str(value.dtype)
        leaves.append(RootLeaf(f"{path}-ndarray-{dtype.encode().hex()}", path,
                               float(value.size)))
        _append_identity(tuple(value.shape), f"{path}-shape", leaves)
        for index, item in enumerate(value.flat):
            _append_identity(item, f"{path}-v{index:05d}", leaves)
        return
    if type(value) in {tuple, list}:
        kind = "tuple" if type(value) is tuple else "list"
        leaves.append(RootLeaf(f"{path}-{kind}", path, float(len(value))))
        for index, item in enumerate(value):
            _append_identity(item, f"{path}-i{index:04d}", leaves)
        return
    if isinstance(value, Mapping):
        kind = "-".join(_type_name(value)).encode("utf-8").hex()
        leaves.append(RootLeaf(f"{path}-mapping-{kind}", path, float(len(value))))
        for index, (key, item) in enumerate(value.items()):
            if type(key) is not str:
                raise TraceValidationError("retained identity keys must be exact strings")
            token = key.encode("utf-8").hex()
            _append_identity(item, f"{path}-k{index:04d}-u{token}", leaves)
        return
    if dataclasses.is_dataclass(value):
        _append_identity(_object_signature(value), f"{path}-dataclass", leaves)
        return
    if type(value) is str:
        leaves.append(RootLeaf(f"{path}-text-u{value.encode('utf-8').hex()}",
                               path, 1.0))
        return
    if type(value) is bool:
        leaves.append(RootLeaf(f"{path}-bool-{'true' if value else 'false'}",
                               path, 1.0 if value else 0.0))
        return
    if value is None:
        leaves.append(RootLeaf(f"{path}-none", path, None, True))
        return
    if type(value) in {int, float}:
        number = float(value)
        if not math.isfinite(number):
            raise TraceValidationError(f"{path} identity must be finite")
        leaves.append(RootLeaf(f"{path}-number-{type(value).__name__}", path, number))
        return
    raise TraceValidationError(f"unsupported retained identity at {path}")


def _success_roots(inp, prepared):
    analysis, _fatigue_inputs, _material_catalog = _app_modules()
    if "concrete" not in inp:
        concrete_id = ("key-absent",)
    elif inp["concrete"] is None:
        concrete_id = ("present-null",)
    else:
        concrete_id = (
            "present-law",
            inp.get("concrete_material_id",
                    inp.get("concrete_preset", "project-concrete")),
        )
    material_ids = tuple(
        (record["id"], record["material_id"])
        for record in prepared.element_records
    )
    identity = (
        analysis.analysis_signature(inp),
        concrete_id,
        material_ids,
        _runtime_material_identity(inp),
        _catalog_identity(inp),
    )
    leaves = []
    _append_identity(identity, "fatigue-input", leaves)
    if len({leaf.step_id for leaf in leaves}) != len(leaves):
        raise TraceValidationError("fatigue input identity is not injective")
    return tuple(leaves)


def _invalid_roots(inp, out):
    raw = (
        tuple(out),
        tuple(out["errors"]),
        tuple(
            (key, type(inp.get(key)).__name__, repr(inp.get(key)))
            for key in (
                "fatigue_on",
                "fatigue_check_steel",
                "fatigue_check_concrete",
                "fatigue_edition",
                "fatigue_gamma_c",
                "fatigue_gamma_s",
                "fatigue_gamma_ff",
                "fatigue_concrete_method",
            )
        ),
    )
    leaves = []
    _append_identity(raw, "invalid-fatigue-input", leaves)
    return tuple(leaves)


def _material_id(record):
    if not isinstance(record, Mapping):
        raise TraceValidationError("element record must be a mapping")
    value = record.get("material_id")
    if type(value) is not str or not value.strip():
        raise TraceValidationError("element material identity is missing")
    return value.strip()


def _method_sources(prepared, detail_id):
    detail = next(
        record for record in prepared.detail_records
        if record["id"] == detail_id
    )
    if detail["custom"]:
        sn_source = CUSTOM_SN_SOURCE
    elif "2023" in prepared.edition:
        sn_source = SN_2023_SOURCE
    else:
        sn_source = SN_2005_SOURCE
    if prepared.section.bars and prepared.section.tendons:
        bond_source = (
            BOND_2023_SOURCE if "2023" in prepared.edition else BOND_2005_SOURCE
        )
    else:
        bond_source = PERFECT_BOND_SOURCE
    return sn_source, bond_source


def _read_family(inp, out, context):
    inp = _as_mapping(inp, "fatigue input")
    out = _as_mapping(out, "fatigue output")
    context = {} if context is None else _as_mapping(context, "trace context")
    analysis, _fatigue_inputs, _material_catalog = _app_modules()
    for key in ("fatigue_on", "fatigue_check_steel", "fatigue_check_concrete"):
        if key not in inp or type(inp[key]) is not bool:
            raise TraceValidationError(f"{key} must be a present exact Boolean")
    if out.get("valid") is False:
        if tuple(out) != INVALID_KEYS:
            raise TraceValidationError("invalid fatigue output inventory changed")
        expected = analysis.invalid_result(inp)
        _same_value(dict(out), expected, "invalid fatigue output")
        return (
            make_invalid_spec(
                roots=_invalid_roots(inp, out),
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
    for spectrum_index, spectrum in enumerate(out["spectra"]):
        for element_index, (record, properties) in enumerate(
            zip(prepared.element_records, prepared.reinforcement)
        ):
            matches = tuple(
                result for result in spectrum.reinforcement
                if result.element_id == properties.element_id
            )
            if len(matches) != 1:
                raise TraceValidationError("element-spectrum identity changed")
            result = matches[0]
            if len(result.bins) != len(spectrum.bins):
                raise TraceValidationError("element-spectrum bin shape changed")
            sn_source, bond_source = _method_sources(prepared, properties.detail_id)
            rows.append(
                (
                    element_index,
                    spectrum_index,
                    properties.element_id,
                    str(properties.kind).strip().lower(),
                    _material_id(record),
                    properties.detail_id,
                    spectrum.spectrum_name,
                    tuple(
                        (index, bin_result.bin_name, bin_result.bond_method)
                        for index, bin_result in enumerate(result.bins)
                    ),
                    sn_source,
                    bond_source,
                )
            )
    return (
        make_success_spec(
            roots=_success_roots(inp, prepared),
            rows=rows,
            context=context,
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


def _sn_proof(properties, stress_range, gamma_s):
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


def _assert_close(actual, expected, label):
    if math.isnan(expected):
        valid = math.isnan(actual)
    elif math.isinf(expected):
        valid = actual == expected
    else:
        valid = math.isclose(actual, expected, rel_tol=2.0e-12, abs_tol=2.0e-12)
    if not valid:
        raise TraceValidationError(f"{label} contradicts independent proof")


def _root_values(family, prepared):
    values = {}
    for root in family.roots:
        values[root.step_id] = (
            TraceResult(RESULT_UNDEFINED, None, "Optional input is absent")
            if root.is_absent
            else float(root.value)
        )
    values["fatigue-input-vector"] = 1.0
    if prepared is None:
        absent = TraceResult(
            RESULT_UNDEFINED,
            None,
            "Invalid input has no usable partial factor",
        )
        values["input-gamma-s"] = absent
        values["input-gamma-ff"] = absent
        values["input-gamma-c"] = absent
    else:
        values["input-gamma-s"] = float(prepared.gamma_s)
        values["input-gamma-ff"] = float(prepared.gamma_ff)
        values["input-gamma-c"] = (
            TraceResult(RESULT_UNDEFINED, None, "Concrete sibling is disabled")
            if prepared.gamma_c is None
            else float(prepared.gamma_c)
        )
    values["normalised-fatigue-inputs"] = 1.0
    return values


def _nonempty_vector(primary, fallback):
    return primary if len(primary) else fallback


def _assessment_values(family, spec, prepared, out):
    values = _root_values(family, prepared)
    properties = prepared.reinforcement[spec.element_position]
    spectrum = out["spectra"][spec.spectrum_position]
    result = next(
        row for row in spectrum.reinforcement
        if row.element_id == spec.element_id
    )
    prefix = assessment_prefix(spec)
    values.update(
        {
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
        }
    )
    damages, yields, convergences = [], [], []
    for bin_spec, state, row in zip(spec.bins, spectrum.bins, result.bins):
        bp = bin_prefix(bin_spec)
        position = spec.element_position
        long_stress = float(state.bar_stress_long_mpa[position])
        elastic_stress = float(state.bar_stress_total_mpa[position])
        fatigue_vector = _nonempty_vector(
            state.bar_stress_fatigue_total_mpa,
            state.bar_stress_total_mpa,
        )
        design_vector = _nonempty_vector(
            state.bar_stress_fatigue_design_total_mpa,
            fatigue_vector,
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
        life, loglife, exponent = _sn_proof(
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
        proof = {
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
        for field, expected in proof.items():
            _assert_close(float(getattr(row, field)), expected, f"{bp}.{field}")
        if type(row.converged) is not bool or row.converged is not state.converged:
            raise TraceValidationError(f"{bp} combined convergence changed")
        values.update(
            {
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
            }
        )
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
    for field, expected in {
        "damage": total_damage,
        "damage_utilisation": total_damage,
        "yield_utilisation": maximum_yield,
        "utilisation": utilisation,
    }.items():
        _assert_close(float(getattr(result, field)), expected, f"{prefix}.{field}")
    if result.governing_damage_bin != result.bins[damage_index].bin_name:
        raise TraceValidationError("governing damage-bin identity changed")
    if result.governing_yield_bin != result.bins[yield_index].bin_name:
        raise TraceValidationError("governing yield-bin identity changed")
    if type(result.converged) is not bool or result.converged is not converged:
        raise TraceValidationError("assessment convergence changed")
    if type(result.passed) is not bool or result.passed is not passed:
        raise TraceValidationError("assessment verdict changed")
    values.update(
        {
            f"{prefix}-damage": total_damage,
            f"{prefix}-damage-bin": float(damage_index),
            f"{prefix}-yield-utilisation": maximum_yield,
            f"{prefix}-yield-bin": float(yield_index),
            f"{prefix}-converged": 1.0 if converged else 0.0,
            f"{prefix}-utilisation": utilisation,
            f"{prefix}-passed": 1.0 if passed else 0.0,
            f"ct-010a-{prefix}-result": utilisation,
        }
    )
    return values, converged


def _aggregate_values(family, prepared, out):
    values = _root_values(family, prepared)
    results = []
    for spec in family.assessments:
        result = next(
            row
            for row in out["spectra"][spec.spectrum_position].reinforcement
            if row.element_id == spec.element_id
        )
        prefix = f"published-{assessment_prefix(spec)}"
        values.update(
            {
                f"{prefix}-damage": float(result.damage),
                f"{prefix}-yield-utilisation": float(result.yield_utilisation),
                f"{prefix}-converged": 1.0 if result.converged else 0.0,
                f"{prefix}-utilisation": float(result.utilisation),
                f"{prefix}-passed": 1.0 if result.passed else 0.0,
            }
        )
        results.append(result)
    converged = all(result.converged for result in results)
    utilisation = max(
        (float(result.utilisation) for result in results),
        default=0.0,
    )
    passed = all(result.passed for result in results)
    values.update(
        {
            "reinforcement-output-converged": 1.0 if converged else 0.0,
            "reinforcement-output-utilisation": utilisation,
            "reinforcement-output-passed": 1.0 if passed else 0.0,
            "ct-010a-reinforcement-output-result": utilisation,
        }
    )
    return values, converged


def _trace_result(value):
    if isinstance(value, TraceResult):
        return value
    number = float(value)
    if math.isnan(number):
        return TraceResult(RESULT_UNDEFINED, None, "Retained result is undefined")
    if number == math.inf:
        return TraceResult(
            RESULT_POSITIVE_INFINITY,
            None,
            "Retained result overflowed",
        )
    if number == -math.inf:
        return TraceResult(
            RESULT_NEGATIVE_INFINITY,
            None,
            "Retained result is negative infinity",
        )
    return TraceResult(RESULT_FINITE, number)


def _make_calculation(calculation_id, title, axes, contracts, values,
                      converged, failed_reason=None):
    units = {contract.step_id: contract.unit for contract in contracts}
    final_step_id = contracts[-1].step_id
    steps = []
    for contract in contracts:
        if contract.step_id not in values:
            raise TraceValidationError(
                f"internal CT-010a value omitted: {contract.step_id}"
            )
        result = _trace_result(values[contract.step_id])
        if contract.step_id == final_step_id and (
            failed_reason is not None or not converged
        ):
            result = TraceResult(
                RESULT_FAILED,
                None,
                failed_reason or "An original or equivalent-area solve failed",
            )
        steps.append(
            TraceStep(
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
                    f"{contract.step_id} = {result.value:.17g} "
                    f"{contract.unit.symbol}"
                    if result.state == RESULT_FINITE
                    else f"{contract.step_id} = {result.state}"
                ),
                result,
            )
        )
    return TraceCalculation(
        calculation_id,
        COVERAGE_ID,
        title,
        METHOD_ID,
        axes,
        final_step_id,
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
        return (
            _make_calculation(
                f"fatigue.{family.context_token}.invalid",
                "Invalid fatigue boundary",
                family.invalid_axes,
                contracts,
                values,
                False,
                "; ".join(family.errors) or "Retained fatigue payload is invalid",
            ),
        )
    calculations = []
    for spec in family.assessments:
        values, converged = _assessment_values(family, spec, prepared, out)
        calculations.append(
            _make_calculation(
                spec.calculation_id,
                f"Reinforcement fatigue: {spec.element_id}",
                spec.axes,
                assessment_steps(family, spec),
                values,
                converged,
            )
        )
    values, converged = _aggregate_values(family, prepared, out)
    calculations.append(
        _make_calculation(
            f"fatigue.{family.context_token}.reinforcement-output",
            "Reinforcement fatigue output",
            family.aggregate_axes,
            aggregate_steps(family),
            values,
            converged,
        )
    )
    return tuple(calculations)


def _expected_bundle(inp, out, input_sha256, result_sha256, context):
    family, prepared, retained = _read_family(inp, out, context)
    bundle = create_bundle(
        input_sha256=input_sha256,
        result_sha256=result_sha256,
        calculations=_calculations(family, prepared, retained),
    )
    audit_trace_registry(bundle, expected_registry(family))
    return bundle


def build_fatigue_trace_family(inp, out, *, input_sha256, result_sha256,
                               context=None):
    """Build a sealed CT-010a bundle from authoritative fatigue evidence."""

    try:
        return _expected_bundle(inp, out, input_sha256, result_sha256, context)
    except TraceValidationError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"invalid CT-010a evidence: {exc}") from exc


def validate_fatigue_trace_family(bundle, inp, out, *, input_sha256,
                                  result_sha256, context=None):
    """Reject any candidate differing from a fresh authoritative replay."""

    candidate = validate_bundle(
        bundle,
        expected_input_sha256=input_sha256,
        expected_result_sha256=result_sha256,
    )
    expected = _expected_bundle(inp, out, input_sha256, result_sha256, context)
    if candidate.to_dict() != expected.to_dict():
        raise TraceValidationError("CT-010a trace differs from independent replay")
    return candidate
