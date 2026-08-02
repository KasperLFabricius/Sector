"""Strict retained-state reader for the CT-010a fatigue trace.

This module is deliberately concerned only with identity.  It replays the
accepted application boundary, rejects normalisation at the trace boundary,
and compares the entire retained solver object graph before numerical trace
evidence is built elsewhere.
"""

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
    "geometry_error",
    "void_error",
    "steel_error",
    "material_error",
)
_FIELD_PINS = {
    ReinforcementFatigueProperties: PROPERTY_FIELDS,
    ReinforcementBinResult: BIN_RESULT_FIELDS,
    ReinforcementFatigueResult: RESULT_FIELDS,
    FatigueBinState: BIN_STATE_FIELDS,
    FatigueSpectrumResult: SPECTRUM_RESULT_FIELDS,
    ElasticResult: ELASTIC_RESULT_FIELDS,
    CombinedElasticResult: COMBINED_ELASTIC_RESULT_FIELDS,
}
_EXCLUDED_FIELDS = {
    FatigueBinState: frozenset(CONCRETE_EXCLUDED_BIN_FIELDS),
    FatigueSpectrumResult: frozenset(CONCRETE_EXCLUDED_RESULT_FIELDS),
}


@dataclass(frozen=True, slots=True)
class ReplayState:
    """Authoritative application replay at the frozen CT-010 boundary."""

    active: bool
    branch: str | None = None
    payload: Mapping[str, Any] | None = None
    prepared: Any = None
    groups: Mapping[str, Any] | None = None


def app_modules():
    """Return the accepted pure application modules without importing UI code."""

    try:
        import fatigue_analysis
        import fatigue_inputs
        import material_catalog
    except ImportError:  # pragma: no cover - direct package use
        sys.path.insert(
            0, str(pathlib.Path(__file__).resolve().parent.parent / "app")
        )
        import fatigue_analysis
        import fatigue_inputs
        import material_catalog
    return fatigue_analysis, fatigue_inputs, material_catalog


def retained_flag(inp: Mapping[str, Any], key: str) -> bool:
    if key not in inp or inp.get(key) is None:
        return False
    return _boolean(inp.get(key), key)


def ordered_sequence(value: Any, label: str) -> tuple[Any, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TraceValidationError(f"{label} must be an ordered sequence")
    return tuple(value)


def _exact(actual: Any, expected: Any, label: str) -> None:
    """Compare a retained value without coercion, omission, or tolerance."""

    if expected is None or type(expected) in {bool, str, int}:
        if type(actual) is not type(expected) or actual != expected:
            raise TraceValidationError(
                f"{label} differs from authoritative replay"
            )
        return
    if type(expected) is float:
        if type(actual) is not float:
            raise TraceValidationError(f"{label} has the wrong retained type")
        if actual != expected and not (
            math.isnan(actual) and math.isnan(expected)
        ):
            raise TraceValidationError(
                f"{label} differs from authoritative replay"
            )
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
                f"{label} differs from authoritative replay"
            )
        return
    if dataclasses.is_dataclass(expected) and not isinstance(expected, type):
        if type(actual) is not type(expected):
            raise TraceValidationError(f"{label} has the wrong retained type")
        names = tuple(
            field.name for field in dataclasses.fields(type(expected))
        )
        if _FIELD_PINS.get(type(expected)) != names:
            raise TraceValidationError(_DRIFT)
        excluded = _EXCLUDED_FIELDS.get(type(expected), frozenset())
        for name in names:
            got = getattr(actual, name)
            wanted = getattr(expected, name)
            if name in excluded:
                if type(got) is not type(wanted):
                    raise TraceValidationError(
                        f"{label}.{name} has the wrong retained type"
                    )
                continue
            _exact(got, wanted, f"{label}.{name}")
        return
    if isinstance(expected, Mapping):
        actual = _mapping(actual, label)
        if tuple(actual) != tuple(expected):
            raise TraceValidationError(
                f"{label} retained keys/order differ: {tuple(actual)!r}"
            )
        for key in expected:
            _exact(actual[key], expected[key], f"{label}.{key}")
        return
    if type(expected) in {tuple, list}:
        if type(actual) is not type(expected) or len(actual) != len(expected):
            raise TraceValidationError(f"{label} cardinality differs")
        for index, (got, wanted) in enumerate(zip(actual, expected)):
            _exact(got, wanted, f"{label}[{index}]")
        return
    raise TraceValidationError(f"{label} has an unsupported retained type")


def _pin_contract(fatigue_inputs: Any) -> None:
    if tuple(fatigue_inputs.EDITIONS) != EDITIONS:
        raise TraceValidationError(_DRIFT)
    for kind, names in _FIELD_PINS.items():
        if tuple(field.name for field in dataclasses.fields(kind)) != names:
            raise TraceValidationError(_DRIFT)


def replay_input(inp: Mapping[str, Any]) -> ReplayState:
    """Replay the authoritative result and classify the retained branch."""

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
            True,
            "invalid",
            fatigue_analysis.invalid_result(inp, errors),
        )

    edition = inp.get("fatigue_edition")
    if type(edition) is not str or edition not in EDITIONS:
        raise TraceValidationError(
            "fatigue_edition must be one exact retained edition string"
        )
    for key in ("nl", "ns", "fatigue_gamma_ff"):
        _number(inp.get(key), key, positive=True)
    if check_steel:
        _number(inp.get("fatigue_gamma_s"), "fatigue_gamma_s", positive=True)

    payload = fatigue_analysis.run_analysis(inp)
    prepared = fatigue_analysis.prepare(inp)
    groups = fatigue_inputs.spectrum_groups(
        inp[fatigue_inputs.SPECTRUM_TABLE_KEY]
    )
    return ReplayState(True, "finite", payload, prepared, groups)


def validate_candidate(
    candidate: Mapping[str, Any] | None,
    replay: ReplayState,
) -> None:
    """Require exact candidate ownership for the replayed branch."""

    if not replay.active:
        if candidate is not None:
            raise TraceValidationError(
                "inactive fatigue state cannot carry a candidate result"
            )
        return
    if candidate is None or replay.payload is None:
        raise TraceValidationError("active fatigue state requires a result")
    if replay.branch == "invalid":
        expected = replay.payload
        if tuple(expected) != INVALID_KEYS:
            raise TraceValidationError(_DRIFT)
        retained = _retained_mapping(
            candidate,
            INVALID_KEYS,
            (),
            "candidate invalid fatigue result",
        )
        if retained["valid"] is not False or expected["valid"] is not False:
            raise TraceValidationError(
                "invalid fatigue result.valid must be False"
            )
        for key in INVALID_KEYS:
            _exact(retained[key], expected[key], f"candidate invalid {key}")
        return
    if replay.branch != "finite":
        raise TraceValidationError("unknown retained fatigue replay branch")

    expected = replay.payload
    if tuple(expected) != VALID_KEYS:
        raise TraceValidationError(_DRIFT)
    mapped = _mapping(candidate, "candidate fatigue result")
    if "valid" in mapped:
        raise TraceValidationError(
            "finite fatigue result cannot carry invalid-branch valid"
        )
    retained = _retained_mapping(
        mapped, VALID_KEYS, (), "candidate fatigue result"
    )
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
                    f"candidate fatigue {key} retained type differs"
                )
            continue
        _exact(retained[key], expected[key], f"candidate fatigue {key}")


def _catalog_scalar(value: Any, label: str, expected_type: type) -> None:
    if type(value) is not expected_type:
        raise TraceValidationError(f"{label} has the wrong retained type")
    if expected_type is float and not math.isfinite(value):
        raise TraceValidationError(f"{label} must be finite")


def validate_present_material_catalog(
    inp: Mapping[str, Any],
    material_kind: str,
    material_catalog: Any | None = None,
) -> bool:
    """Validate every item of a present mild/prestress material catalogue.

    The application normaliser is intentionally forgiving for project import.
    A standards-carrying trace boundary cannot be: the raw catalogue must
    already be its complete canonical representation, including unassigned
    siblings and top-level metadata.
    """

    if material_catalog is None:
        _analysis, _inputs, material_catalog = app_modules()
    key = material_catalog.catalog_key(material_kind)
    if key not in inp:
        return False
    raw = inp[key]
    if type(raw) is not dict or tuple(raw) != ("version", "next_id", "items"):
        raise TraceValidationError(
            f"{key} must be a complete canonical catalogue object"
        )
    if type(raw["version"]) is not int or raw["version"] != material_catalog.VERSION:
        raise TraceValidationError(f"{key}.version is not the current schema")
    if type(raw["next_id"]) is not int or raw["next_id"] <= 0:
        raise TraceValidationError(f"{key}.next_id must be a positive integer")
    if type(raw["items"]) is not list or not raw["items"]:
        raise TraceValidationError(f"{key}.items must be a non-empty list")

    expected_keys = tuple(material_catalog.default_entry(material_kind))
    text_fields = {"id", "name", "description", "preset"}
    for index, item in enumerate(raw["items"]):
        label = f"{key}.items[{index}]"
        if type(item) is not dict or tuple(item) != expected_keys:
            raise TraceValidationError(
                f"{label} must contain the exact material field inventory"
            )
        for field in text_fields:
            _catalog_scalar(item[field], f"{label}.{field}", str)
            if item[field] != item[field].strip():
                raise TraceValidationError(f"{label}.{field} is not canonical")
        _catalog_scalar(item["curve"], f"{label}.curve", int)
        if material_kind == "mild":
            _catalog_scalar(
                item["active_in_compression"],
                f"{label}.active_in_compression",
                bool,
            )
        for field in material_catalog.fields(material_kind):
            _catalog_scalar(item[field], f"{label}.{field}", float)

    try:
        canonical = material_catalog.normalise_catalog(raw, material_kind)
    except (TypeError, ValueError, OverflowError) as exc:
        raise TraceValidationError(f"{key} is not a valid material catalogue") from exc
    _exact(raw, canonical, key)
    return True


__all__ = [
    "ReplayState",
    "app_modules",
    "ordered_sequence",
    "replay_input",
    "retained_flag",
    "validate_candidate",
    "validate_present_material_catalog",
]
