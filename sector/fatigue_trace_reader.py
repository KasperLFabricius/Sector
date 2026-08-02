"""Strict retained-boundary reader for CT-010 reinforcement fatigue traces."""

from __future__ import annotations

import dataclasses
import math
import pathlib
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

from .calculation_trace import TraceValidationError, trace_identity_token


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


@dataclass(frozen=True, slots=True)
class IdentityLeaf:
    step_id: str
    title: str
    value: float | None
    absent: bool = False


@dataclass(frozen=True, slots=True)
class ElementEvidence:
    index: int
    element_id: str
    kind: str
    material_id: str
    detail_id: str
    properties: Any
    results: tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class FatigueEvidence:
    valid: bool
    prepared: Any | None
    output: Mapping[str, Any]
    input_leaves: tuple[IdentityLeaf, ...]
    elements: tuple[ElementEvidence, ...]
    spectra: tuple[Any, ...]
    errors: tuple[str, ...]
    context: Mapping[str, Any]


def _app_modules():
    app_path = pathlib.Path(__file__).resolve().parent.parent / "app"
    app_text = str(app_path)
    if app_text not in sys.path:
        sys.path.insert(0, app_text)
    import fatigue_analysis  # type: ignore
    import fatigue_inputs  # type: ignore
    import material_catalog  # type: ignore
    return fatigue_analysis, fatigue_inputs, material_catalog


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TraceValidationError(f"{label} must be a mapping")
    if any(type(key) is not str for key in value):
        raise TraceValidationError(f"{label} keys must be exact strings")
    return value


def _same_float(actual: float, expected: float) -> bool:
    return actual == expected or (
        math.isnan(actual) and math.isnan(expected)
    )


def _compare_exact(actual: Any, expected: Any, label: str) -> None:
    """Compare retained values without coercion or tolerance laundering."""

    if type(actual) is not type(expected):
        raise TraceValidationError(
            f"{label} retained type differs from authoritative replay"
        )
    if dataclasses.is_dataclass(expected):
        for field in dataclasses.fields(expected):
            _compare_exact(
                getattr(actual, field.name), getattr(expected, field.name),
                f"{label}.{field.name}",
            )
        return
    if isinstance(expected, np.ndarray):
        if (
            actual.dtype != expected.dtype
            or actual.shape != expected.shape
            or not np.array_equal(actual, expected, equal_nan=True)
        ):
            raise TraceValidationError(
                f"{label} array differs from authoritative replay"
            )
        return
    if isinstance(expected, Mapping):
        if tuple(actual) != tuple(expected):
            raise TraceValidationError(
                f"{label} retained inventory/order differs from replay"
            )
        for key in expected:
            _compare_exact(actual[key], expected[key], f"{label}.{key}")
        return
    if isinstance(expected, (tuple, list)):
        if len(actual) != len(expected):
            raise TraceValidationError(
                f"{label} retained cardinality differs from replay"
            )
        for index, (actual_item, expected_item) in enumerate(
            zip(actual, expected)
        ):
            _compare_exact(actual_item, expected_item, f"{label}[{index}]")
        return
    if isinstance(expected, float):
        if not _same_float(actual, expected):
            raise TraceValidationError(
                f"{label} differs from authoritative replay"
            )
        return
    if actual != expected:
        raise TraceValidationError(f"{label} differs from authoritative replay")


def _pin_type(actual: Any, expected: Any, label: str) -> None:
    """Pin an excluded sibling's retained shape and concrete Python types."""

    if type(actual) is not type(expected):
        raise TraceValidationError(f"{label} retained type changed")
    if isinstance(expected, Mapping):
        if tuple(actual) != tuple(expected):
            raise TraceValidationError(f"{label} retained key position changed")
        for key in expected:
            _pin_type(actual[key], expected[key], f"{label}.{key}")
    elif isinstance(expected, (tuple, list)):
        if len(actual) != len(expected):
            raise TraceValidationError(f"{label} retained position changed")
        for index, (a_item, e_item) in enumerate(zip(actual, expected)):
            _pin_type(a_item, e_item, f"{label}[{index}]")


def _compare_spectrum(actual: Any, expected: Any, *, concrete: bool) -> None:
    if type(actual) is not type(expected):
        raise TraceValidationError("fatigue spectrum retained type changed")
    for field in ("spectrum_name", "reinforcement", "governing_reinforcement_id"):
        _compare_exact(
            getattr(actual, field), getattr(expected, field),
            f"spectrum.{field}",
        )
    if type(actual.bins) is not tuple or len(actual.bins) != len(expected.bins):
        raise TraceValidationError("fatigue bin retained shape changed")
    for index, (actual_state, expected_state) in enumerate(
        zip(actual.bins, expected.bins)
    ):
        if type(actual_state) is not type(expected_state):
            raise TraceValidationError("fatigue bin retained type changed")
        for field in (
            "name", "description", "cycles", "converged",
            "bar_stress_long_mpa", "bar_stress_total_mpa",
            "elastic_result", "bar_stress_fatigue_total_mpa",
            "bond_method", "design_action_factor", "design_elastic_result",
            "bar_stress_design_total_mpa",
            "bar_stress_fatigue_design_total_mpa",
        ):
            _compare_exact(
                getattr(actual_state, field), getattr(expected_state, field),
                f"spectrum.bins[{index}].{field}",
            )
    # CT-010b owns concrete values. CT-010a nevertheless pins their exact
    # presence, position and retained types so incompatible replacements cannot
    # hide behind the excluded sibling boundary.
    if type(actual.concrete) is not tuple:
        raise TraceValidationError("spectrum.concrete retained type changed")
    if actual.concrete_search is not None and not dataclasses.is_dataclass(
        actual.concrete_search
    ):
        raise TraceValidationError("spectrum.concrete_search retained type changed")
    if type(actual.fcd_fat_mpa) not in {float, type(None)}:
        raise TraceValidationError("spectrum.fcd_fat_mpa retained type changed")
    if type(actual.governing_concrete_fibre) not in {int, type(None)}:
        raise TraceValidationError(
            "spectrum.governing_concrete_fibre retained type changed"
        )
    if type(actual.concrete_method) not in {str, type(None)}:
        raise TraceValidationError("spectrum.concrete_method retained type changed")
    if concrete:
        for field in ("utilisation", "converged", "passed"):
            _pin_type(
                getattr(actual, field), getattr(expected, field),
                f"spectrum.{field}",
            )
    else:
        for field in ("utilisation", "converged", "passed"):
            _compare_exact(
                getattr(actual, field), getattr(expected, field),
                f"spectrum.{field}",
            )


def _compare_success(actual: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    if tuple(actual) != SUCCESS_KEYS or tuple(expected) != SUCCESS_KEYS:
        raise TraceValidationError("authoritative fatigue output inventory drifted")
    checks = _mapping(expected["checks"], "fatigue checks")
    concrete = checks.get("concrete") is True
    for key in SUCCESS_KEYS:
        if key in {"concrete_method", "concrete_parameters", "t0_days"}:
            _pin_type(actual[key], expected[key], f"fatigue output {key}")
        elif key == "spectra":
            if type(actual[key]) is not tuple or type(expected[key]) is not tuple:
                raise TraceValidationError("fatigue spectra must remain a tuple")
            if len(actual[key]) != len(expected[key]):
                raise TraceValidationError("fatigue spectrum cardinality changed")
            for a_item, e_item in zip(actual[key], expected[key]):
                _compare_spectrum(a_item, e_item, concrete=concrete)
        elif concrete and key in {
            "governing_spectrum", "utilisation", "converged", "passed",
        }:
            _pin_type(actual[key], expected[key], f"fatigue output {key}")
        else:
            _compare_exact(actual[key], expected[key], f"fatigue output {key}")


def _validate_catalogs(inp: Mapping[str, Any]) -> tuple[Any, ...]:
    """Validate and retain complete catalogue inventories, not assignments only."""

    _analysis, fatigue_inputs, material_catalog = _app_modules()
    retained: list[Any] = []
    if fatigue_inputs.DETAIL_CATALOG_KEY in inp:
        raw = _mapping(
            inp[fatigue_inputs.DETAIL_CATALOG_KEY], "fatigue detail catalog"
        )
        normal = fatigue_inputs.normalise_catalog(raw)
        if tuple(raw) != ("version", "next_id", "items"):
            raise TraceValidationError(
                "fatigue detail catalog inventory/order must be canonical"
            )
        if type(raw["items"]) is not list:
            raise TraceValidationError("fatigue detail catalog items must be a list")
        if len(raw["items"]) != len(normal["items"]):
            raise TraceValidationError("fatigue detail catalog cardinality drifted")
        for position, (actual, expected) in enumerate(
            zip(raw["items"], normal["items"])
        ):
            actual = _mapping(actual, f"fatigue detail item {position}")
            if set(actual) != set(expected):
                raise TraceValidationError(
                    f"fatigue detail item {position} inventory drifted"
                )
            for key in expected:
                _compare_exact(
                    actual[key], expected[key],
                    f"fatigue detail item {position}.{key}",
                )
        retained.append((fatigue_inputs.DETAIL_CATALOG_KEY, normal))
    for kind in ("mild", "prestress"):
        key = material_catalog.catalog_key(kind)
        if key not in inp:
            continue
        raw = _mapping(inp[key], f"{kind} material catalog")
        normal = material_catalog.normalise_catalog(raw, kind)
        if tuple(raw) != ("version", "next_id", "items"):
            raise TraceValidationError(
                f"{kind} material catalog inventory/order must be canonical"
            )
        _compare_exact(dict(raw), normal, f"{kind} material catalog")
        retained.append((key, normal))
    return tuple(retained)


def _validate_success_input_types(inp: Mapping[str, Any]) -> None:
    numeric_keys = (
        "fatigue_gamma_c", "fatigue_gamma_s", "fatigue_gamma_ff",
        "fatigue_beta_cc_t0", "fatigue_t0_days", "fatigue_concrete_k1",
        "fatigue_concrete_c", "nl", "ns",
    )
    for key in numeric_keys:
        value = inp.get(key)
        if value is None:
            continue
        if type(value) not in {int, float} or type(value) is bool:
            raise TraceValidationError(f"{key} must be a finite non-Boolean number")
        if not math.isfinite(float(value)):
            raise TraceValidationError(f"{key} must be finite")
    for key in ("fatigue_edition", "fatigue_concrete_method"):
        value = inp.get(key)
        if value is not None and type(value) is not str:
            raise TraceValidationError(f"{key} must be exact text or absent")
    for table_key in ("bar_elements", "tendon_elements"):
        records = inp.get(table_key)
        if type(records) is not list:
            raise TraceValidationError(f"{table_key} must be a retained list")
        for position, record in enumerate(records):
            if type(record) is not dict:
                raise TraceValidationError(
                    f"{table_key}[{position}] must be an exact mapping"
                )
            for key in ("id", "kind", "material_id", "fatigue_detail_id"):
                if key not in record or type(record[key]) is not str:
                    raise TraceValidationError(
                        f"{table_key}[{position}].{key} must be exact text"
                    )
            for key in ("x_mm", "y_mm", "area_mm2", "diameter_mm"):
                value = record.get(key)
                if type(value) not in {int, float} or type(value) is bool:
                    raise TraceValidationError(
                        f"{table_key}[{position}].{key} must be a finite number"
                    )
                if not math.isfinite(float(value)):
                    raise TraceValidationError(
                        f"{table_key}[{position}].{key} must be finite"
                    )
    for key in ("bar_materials", "tendon_materials"):
        if type(inp.get(key)) is not list:
            raise TraceValidationError(f"{key} must be a retained list")


def _law_signature(value: Any) -> tuple[Any, ...]:
    if dataclasses.is_dataclass(value):
        return tuple(
            (field.name, getattr(value, field.name))
            for field in dataclasses.fields(value)
        )
    if hasattr(value, "__dict__"):
        return tuple(sorted(vars(value).items()))
    raise TraceValidationError("fatigue material law has no inspectable identity")


def _block_signature(inp: Mapping[str, Any], prepared: Any) -> tuple[Any, ...]:
    """Retain concrete and every aligned reinforcement material identity."""

    section = prepared.section
    concrete_id = inp.get(
        "concrete_material_id",
        inp.get("concrete_preset", "project-concrete"),
    )
    if type(concrete_id) is not str or not concrete_id.strip():
        raise TraceValidationError("concrete material identity must be text")
    material_laws = (
        (
            "concrete", "concrete", concrete_id,
            _law_signature(inp["concrete"]),
        ),
        *tuple(
            (
                "mild", prepared.element_records[index]["id"],
                prepared.element_records[index]["material_id"],
                _law_signature(material),
            )
            for index, material in enumerate(inp.get("bar_materials") or ())
        ),
        *tuple(
            (
                "prestress",
                prepared.element_records[len(inp.get("bar_materials") or ()) + index]["id"],
                prepared.element_records[len(inp.get("bar_materials") or ()) + index]["material_id"],
                _law_signature(material),
            )
            for index, material in enumerate(inp.get("tendon_materials") or ())
        ),
    )
    geometry = (
        tuple(
            tuple((float(x), float(y)) for x, y in ring)
            for ring in section.concrete
        ),
        tuple((item.x, item.y, item.area) for item in section.bars),
        tuple((item.x, item.y, item.area) for item in section.tendons),
    )
    return geometry, material_laws


def _leaf_token(value: str) -> str:
    # Identity is injective and remains visible in the immutable step ID.
    return trace_identity_token(value)


def _flatten(value: Any, path: str, output: list[IdentityLeaf]) -> None:
    if isinstance(value, np.generic):
        value = value.item()
    if type(value) is tuple or type(value) is list:
        marker = "tuple" if type(value) is tuple else "list"
        output.append(IdentityLeaf(f"{path}-type-{marker}", path, float(len(value))))
        for index, item in enumerate(value):
            _flatten(item, f"{path}-i{index:04d}", output)
        return
    if isinstance(value, Mapping):
        output.append(IdentityLeaf(f"{path}-type-mapping", path, float(len(value))))
        for index, (key, item) in enumerate(value.items()):
            if type(key) is not str:
                raise TraceValidationError("fatigue identity mapping keys must be text")
            token = _leaf_token(key)
            _flatten(item, f"{path}-k{index:04d}-{token}", output)
        return
    if type(value) is bool:
        output.append(IdentityLeaf(
            f"{path}-bool-{'true' if value else 'false'}", path,
            1.0 if value else 0.0,
        ))
        return
    if value is None:
        output.append(IdentityLeaf(f"{path}-none", path, None, True))
        return
    if type(value) is str:
        output.append(IdentityLeaf(
            f"{path}-text-{_leaf_token(value)}", path, 1.0,
        ))
        return
    if type(value) in {int, float}:
        number = float(value)
        if not math.isfinite(number):
            raise TraceValidationError(f"{path} input identity must be finite")
        output.append(IdentityLeaf(
            f"{path}-number-{'int' if type(value) is int else 'float'}",
            path, number,
        ))
        return
    raise TraceValidationError(
        f"{path} has unsupported retained type {type(value).__name__}"
    )


def _input_leaves(inp: Mapping[str, Any], prepared: Any) -> tuple[IdentityLeaf, ...]:
    analysis, _fatigue_inputs, _material_catalog = _app_modules()
    identity = (
        analysis.analysis_signature(inp),
        _block_signature(inp, prepared),
        _validate_catalogs(inp),
    )
    leaves: list[IdentityLeaf] = []
    _flatten(identity, "fatigue-input", leaves)
    ids = [leaf.step_id for leaf in leaves]
    if len(ids) != len(set(ids)):
        raise TraceValidationError("fatigue input identity leaves are not injective")
    return tuple(leaves)


def _material_id(record: Mapping[str, Any], kind: str) -> str:
    keys = (
        ("material_id", "mild_material_id", "bar_material_id")
        if kind == "mild"
        else ("material_id", "prestress_material_id", "tendon_material_id")
    )
    for key in keys:
        if key in record and type(record[key]) is str and record[key].strip():
            return record[key].strip()
    raise TraceValidationError("reinforcement element material identity is missing")


def _check_convergence(state: Any, label: str) -> None:
    """Validate only implications valid with the extra equivalent-area solve."""

    if type(state.converged) is not bool:
        raise TraceValidationError(f"{label} convergence must be an exact Boolean")
    retained = [state.elastic_result, state.design_elastic_result]
    for result in retained:
        if result is None:
            continue
        if type(result.converged) is not bool:
            raise TraceValidationError(
                f"{label} Elastic convergence must be an exact Boolean"
            )
        if state.converged and not result.converged:
            raise TraceValidationError(
                f"{label} combined convergence contradicts an original solve"
            )
        if not result.converged and state.converged:
            raise TraceValidationError(
                f"{label} failed original solve cannot yield convergence"
            )
    # Deliberately do not infer False -> original failure. In a mixed 2023
    # section the equivalent-tendon-area solve is an additional failure source.


def read_fatigue_evidence(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    context: Mapping[str, Any] | None = None,
) -> FatigueEvidence:
    """Read and independently cross-check the retained CT-010a boundary."""

    inp = _mapping(inp, "fatigue input")
    out = _mapping(out, "fatigue output")
    if context is not None:
        _mapping(context, "trace context")
    trace_context = {} if context is None else context
    analysis, _fatigue_inputs, _material_catalog = _app_modules()

    for key in ("fatigue_on", "fatigue_check_steel", "fatigue_check_concrete"):
        if key not in inp or type(inp[key]) is not bool:
            raise TraceValidationError(f"{key} must be a present exact Boolean")

    if out.get("valid") is False:
        if tuple(out) != INVALID_KEYS:
            raise TraceValidationError("invalid fatigue output inventory drifted")
        expected = analysis.invalid_result(inp)
        _compare_exact(dict(out), expected, "invalid fatigue output")
        leaves: list[IdentityLeaf] = []
        _flatten(
            (tuple(expected["errors"]), tuple(out), tuple(type(out[k]).__name__ for k in out)),
            "fatigue-invalid-input", leaves,
        )
        return FatigueEvidence(
            False, None, out, tuple(leaves), (), (),
            tuple(expected["errors"]), trace_context,
        )

    if not inp["fatigue_on"] or not inp["fatigue_check_steel"]:
        raise TraceValidationError("CT-010a requires enabled reinforcement fatigue")

    _validate_success_input_types(inp)

    try:
        prepared = analysis.prepare(inp)
        def reinforcement_engine(section, spectra, nl, ns, **kwargs):
            kwargs["concrete"] = None
            kwargs["check_concrete"] = False
            return analysis.analyse_grouped_spectra(
                section, spectra, nl, ns, **kwargs
            )

        replay = analysis.run_analysis(inp, engine=reinforcement_engine)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"invalid CT-010a input: {exc}") from exc
    _compare_success(out, replay)

    spectra = tuple(out["spectra"])
    for spectrum in spectra:
        for state in spectrum.bins:
            _check_convergence(state, f"{spectrum.spectrum_name}/{state.name}")

    if len(prepared.element_records) != len(prepared.reinforcement):
        raise TraceValidationError("reinforcement evidence cardinality drifted")
    elements: list[ElementEvidence] = []
    for index, (record, properties) in enumerate(zip(
        prepared.element_records, prepared.reinforcement
    )):
        if not isinstance(record, Mapping):
            raise TraceValidationError("reinforcement element record must be a mapping")
        kind = str(properties.kind).strip().lower()
        results = []
        for spectrum in spectra:
            matches = tuple(
                result for result in spectrum.reinforcement
                if result.element_id == properties.element_id
            )
            if len(matches) != 1:
                raise TraceValidationError(
                    f"{properties.element_id}: each spectrum needs one result"
                )
            results.append(matches[0])
        elements.append(ElementEvidence(
            index=index,
            element_id=str(properties.element_id),
            kind=kind,
            material_id=_material_id(record, kind),
            detail_id=str(properties.detail_id),
            properties=properties,
            results=tuple(results),
        ))

    return FatigueEvidence(
        True, prepared, out, _input_leaves(inp, prepared), tuple(elements),
        spectra, (), trace_context,
    )
