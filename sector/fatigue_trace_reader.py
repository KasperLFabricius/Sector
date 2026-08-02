"""Strict application replay and retained identity checks for CT-010a."""

from __future__ import annotations

import dataclasses
import math
import pathlib
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from .calculation_trace import TraceValidationError
from .elastic import CombinedElasticResult, ElasticResult
from .fatigue import (
    FatigueBinState,
    FatigueSpectrumResult,
    ReinforcementBinResult,
    ReinforcementFatigueProperties,
    ReinforcementFatigueResult,
)
from .fatigue_trace_contract import (
    BASIS_KEYS,
    BIN_RESULT_FIELDS,
    BIN_STATE_FIELDS,
    CHECK_KEYS,
    COMBINED_ELASTIC_RESULT_FIELDS,
    CONCRETE_EXCLUDED_BIN_FIELDS,
    CONCRETE_EXCLUDED_KEYS,
    CONCRETE_EXCLUDED_RESULT_FIELDS,
    EDITIONS,
    ELASTIC_RESULT_FIELDS,
    FACTOR_KEYS,
    INVALID_KEYS,
    PROPERTY_FIELDS,
    RESULT_FIELDS,
    SPECTRUM_RESULT_FIELDS,
    VALID_KEYS,
)
from .torsion_trace import _boolean, _mapping, _number, _retained_mapping


_DRIFT = "authoritative CT-010 retained inventory drifted"
_SECTION_ERRORS = (
    "geometry_error", "void_error", "steel_error", "material_error")
_FIELD_PINS = {
    ReinforcementFatigueProperties: PROPERTY_FIELDS,
    ReinforcementBinResult: BIN_RESULT_FIELDS,
    ReinforcementFatigueResult: RESULT_FIELDS,
    FatigueBinState: BIN_STATE_FIELDS,
    FatigueSpectrumResult: SPECTRUM_RESULT_FIELDS,
    ElasticResult: ELASTIC_RESULT_FIELDS,
    CombinedElasticResult: COMBINED_ELASTIC_RESULT_FIELDS,
}
_VALUE_EXCLUSIONS = {
    FatigueBinState: frozenset(CONCRETE_EXCLUDED_BIN_FIELDS),
    FatigueSpectrumResult: frozenset(CONCRETE_EXCLUDED_RESULT_FIELDS),
}


@dataclass(frozen=True, slots=True)
class ReplayState:
    active: bool
    branch: str | None = None
    payload: Mapping[str, Any] | None = None
    prepared: Any = None
    groups: Mapping[str, Any] | None = None


def app_modules():
    try:
        import fatigue_analysis
        import fatigue_inputs
        import material_catalog
    except ImportError:  # pragma: no cover - direct package use
        sys.path.insert(
            0, str(pathlib.Path(__file__).resolve().parent.parent / "app"))
        import fatigue_analysis
        import fatigue_inputs
        import material_catalog
    return fatigue_analysis, fatigue_inputs, material_catalog


def retained_flag(inp, key):
    if key not in inp or inp.get(key) is None:
        return False
    return _boolean(inp.get(key), key)


def ordered_sequence(value, label):
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TraceValidationError(f"{label} must be an ordered sequence")
    return tuple(value)


def exact_retained(actual, expected, label):
    """Compare an authoritative object graph without coercion or tolerance."""

    if expected is None or type(expected) in {bool, str, int}:
        if type(actual) is not type(expected) or actual != expected:
            raise TraceValidationError(
                f"{label} differs from authoritative replay")
        return
    if type(expected) is float:
        if type(actual) is not float:
            raise TraceValidationError(f"{label} has the wrong retained type")
        if actual != expected and not (
            math.isnan(actual) and math.isnan(expected)
        ):
            raise TraceValidationError(
                f"{label} differs from authoritative replay")
        return
    if type(expected) is np.ndarray:
        if type(actual) is not np.ndarray:
            raise TraceValidationError(f"{label} has the wrong retained type")
        if (
            actual.dtype != expected.dtype
            or actual.shape != expected.shape
            or not np.array_equal(actual, expected, equal_nan=True)
        ):
            raise TraceValidationError(
                f"{label} differs from authoritative replay")
        return
    if dataclasses.is_dataclass(expected) and not isinstance(expected, type):
        if type(actual) is not type(expected):
            raise TraceValidationError(f"{label} has the wrong retained type")
        names = tuple(
            field.name for field in dataclasses.fields(type(expected)))
        if _FIELD_PINS.get(type(expected)) != names:
            raise TraceValidationError(_DRIFT)
        excluded = _VALUE_EXCLUSIONS.get(type(expected), frozenset())
        for name in names:
            got = getattr(actual, name)
            wanted = getattr(expected, name)
            if name in excluded:
                if type(got) is not type(wanted):
                    raise TraceValidationError(
                        f"{label}.{name} has the wrong retained type")
                continue
            exact_retained(got, wanted, f"{label}.{name}")
        return
    if isinstance(expected, Mapping):
        actual = _mapping(actual, label)
        if tuple(actual) != tuple(expected):
            raise TraceValidationError(
                f"{label} retained keys/order differ: {tuple(actual)!r}")
        for key in expected:
            exact_retained(actual[key], expected[key], f"{label}.{key}")
        return
    if type(expected) in {tuple, list}:
        if type(actual) is not type(expected) or len(actual) != len(expected):
            raise TraceValidationError(f"{label} cardinality differs")
        for index, (got, wanted) in enumerate(zip(actual, expected)):
            exact_retained(got, wanted, f"{label}[{index}]")
        return
    raise TraceValidationError(f"{label} has an unsupported retained type")


def _pin_contract(fatigue_inputs):
    if tuple(fatigue_inputs.EDITIONS) != EDITIONS:
        raise TraceValidationError(_DRIFT)
    for kind, names in _FIELD_PINS.items():
        if tuple(field.name for field in dataclasses.fields(kind)) != names:
            raise TraceValidationError(_DRIFT)


def replay_input(inp):
    if "fatigue_on" not in inp or inp.get("fatigue_on") is None:
        return ReplayState(False)
    if not _boolean(inp.get("fatigue_on"), "fatigue_on"):
        return ReplayState(False)
    if inp.get("section") is None or any(inp.get(key) for key in _SECTION_ERRORS):
        return ReplayState(False)

    fatigue_analysis, fatigue_inputs, _material_catalog = app_modules()
    _pin_contract(fatigue_inputs)
    check_steel = retained_flag(inp, "fatigue_check_steel")
    retained_flag(inp, "fatigue_check_concrete")
    errors = tuple(fatigue_analysis.validation_errors(inp))
    if errors:
        return ReplayState(
            True, "invalid", fatigue_analysis.invalid_result(inp, errors))

    edition = inp.get("fatigue_edition")
    if type(edition) is not str or edition not in EDITIONS:
        raise TraceValidationError(
            "fatigue_edition must be one exact retained edition string")
    for key in ("nl", "ns", "fatigue_gamma_ff"):
        _number(inp.get(key), key, positive=True)
    if check_steel:
        _number(inp.get("fatigue_gamma_s"), "fatigue_gamma_s", positive=True)

    payload = fatigue_analysis.run_analysis(inp)
    prepared = fatigue_analysis.prepare(inp)
    groups = fatigue_inputs.spectrum_groups(
        inp[fatigue_inputs.SPECTRUM_TABLE_KEY])
    return ReplayState(True, "finite", payload, prepared, groups)


def validate_candidate(candidate, replay):
    if not replay.active:
        if candidate is not None:
            raise TraceValidationError(
                "inactive fatigue state cannot carry a candidate result")
        return
    if candidate is None or replay.payload is None:
        raise TraceValidationError("active fatigue state requires a result")
    expected = replay.payload
    if replay.branch == "invalid":
        if tuple(expected) != INVALID_KEYS:
            raise TraceValidationError(_DRIFT)
        retained = _retained_mapping(
            candidate, INVALID_KEYS, (), "candidate invalid fatigue result")
        if retained["valid"] is not False or expected["valid"] is not False:
            raise TraceValidationError(
                "invalid fatigue result.valid must be False")
        for key in INVALID_KEYS:
            exact_retained(
                retained[key], expected[key], f"candidate invalid {key}")
        return
    if replay.branch != "finite":
        raise TraceValidationError("unknown retained fatigue replay branch")
    if tuple(expected) != VALID_KEYS:
        raise TraceValidationError(_DRIFT)
    mapped = _mapping(candidate, "candidate fatigue result")
    if "valid" in mapped:
        raise TraceValidationError(
            "finite fatigue result cannot carry invalid-branch valid")
    retained = _retained_mapping(
        mapped, VALID_KEYS, (), "candidate fatigue result")
    for key, names in (
        ("checks", CHECK_KEYS),
        ("partial_factors", FACTOR_KEYS),
        ("basis", BASIS_KEYS),
    ):
        if tuple(expected[key]) != names:
            raise TraceValidationError(_DRIFT)
    for key in VALID_KEYS:
        if key in CONCRETE_EXCLUDED_KEYS:
            if type(retained[key]) is not type(expected[key]):
                raise TraceValidationError(
                    f"candidate fatigue {key} retained type differs")
            continue
        exact_retained(retained[key], expected[key], f"candidate fatigue {key}")


def _catalog_header(raw, key, version):
    if type(raw) is not dict or tuple(raw) != ("version", "next_id", "items"):
        raise TraceValidationError(
            f"{key} must be a complete canonical catalogue object")
    if type(raw["version"]) is not int or raw["version"] != version:
        raise TraceValidationError(f"{key}.version is not the current schema")
    if type(raw["next_id"]) is not int or raw["next_id"] <= 0:
        raise TraceValidationError(f"{key}.next_id must be a positive integer")
    if type(raw["items"]) is not list or not raw["items"]:
        raise TraceValidationError(f"{key}.items must be a non-empty list")


def _text(value, label):
    if type(value) is not str or value != value.strip():
        raise TraceValidationError(f"{label} must be canonical text")


def _finite_float(value, label):
    if type(value) is not float or not math.isfinite(value):
        raise TraceValidationError(f"{label} must be a canonical finite float")


def validate_present_material_catalog(inp, material_kind, module=None):
    if module is None:
        _analysis, _inputs, module = app_modules()
    key = module.catalog_key(material_kind)
    if key not in inp:
        return False
    raw = inp[key]
    _catalog_header(raw, key, module.VERSION)
    expected_keys = tuple(module.default_entry(material_kind))
    for index, item in enumerate(raw["items"]):
        label = f"{key}.items[{index}]"
        if type(item) is not dict or tuple(item) != expected_keys:
            raise TraceValidationError(
                f"{label} must contain the exact material field inventory")
        for field in ("id", "name", "description", "preset"):
            _text(item[field], f"{label}.{field}")
        if type(item["curve"]) is not int:
            raise TraceValidationError(f"{label}.curve must be an integer")
        if material_kind == "mild" and type(
            item["active_in_compression"]
        ) is not bool:
            raise TraceValidationError(
                f"{label}.active_in_compression must be Boolean")
        for field in module.fields(material_kind):
            _finite_float(item[field], f"{label}.{field}")
    try:
        canonical = module.normalise_catalog(raw, material_kind)
    except (TypeError, ValueError, OverflowError) as exc:
        raise TraceValidationError(
            f"{key} is not a valid material catalogue") from exc
    exact_retained(raw, canonical, key)
    return True


def validate_fatigue_detail_catalog(inp, module=None):
    if module is None:
        _analysis, module, _materials = app_modules()
    key = module.DETAIL_CATALOG_KEY
    if key not in inp:
        raise TraceValidationError(
            "reinforcement fatigue requires a retained detail catalogue")
    raw = inp[key]
    _catalog_header(raw, key, module.VERSION)
    default_order = tuple(module.default_entry())
    normalised_order = tuple(
        module.normalise_catalog(module.default_catalog())["items"][0])
    allowed_orders = {default_order, normalised_order}
    text_fields = (
        "id", "name", "description", "preset", "kind",
        "stress_model", "source",
    )
    numeric_fields = (
        "n_star", "k1", "k2", "delta_sigma_rsk_mpa",
        "mandrel_diameter_mm", "bond_ratio_xi",
        "bond_equivalent_diameter_mm",
    )
    for index, item in enumerate(raw["items"]):
        label = f"{key}.items[{index}]"
        if type(item) is not dict or tuple(item) not in allowed_orders:
            raise TraceValidationError(
                f"{label} must contain the exact fatigue-detail inventory")
        for field in text_fields:
            _text(item[field], f"{label}.{field}")
        if type(item["bend_reduction"]) is not bool:
            raise TraceValidationError(
                f"{label}.bend_reduction must be Boolean")
        for field in numeric_fields:
            _finite_float(item[field], f"{label}.{field}")
    try:
        canonical = module.normalise_catalog(raw)
    except (TypeError, ValueError, OverflowError) as exc:
        raise TraceValidationError(
            f"{key} is not a valid fatigue-detail catalogue") from exc
    exact_retained(raw["version"], canonical["version"], f"{key}.version")
    exact_retained(raw["next_id"], canonical["next_id"], f"{key}.next_id")
    if len(raw["items"]) != len(canonical["items"]):
        raise TraceValidationError(f"{key}.items cardinality differs")
    for index, (item, normalised) in enumerate(
        zip(raw["items"], canonical["items"])
    ):
        for field in default_order:
            exact_retained(
                item[field], normalised[field],
                f"{key}.items[{index}].{field}")


__all__ = [
    "ReplayState",
    "app_modules",
    "exact_retained",
    "ordered_sequence",
    "replay_input",
    "retained_flag",
    "validate_candidate",
    "validate_fatigue_detail_catalog",
    "validate_present_material_catalog",
]
