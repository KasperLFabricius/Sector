"""Independent CT-009 replay for the retained 2004 base crack method."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from .calculation_trace import (
    RESULT_FAILED,
    RESULT_FINITE,
    RESULT_POSITIVE_INFINITY,
    RESULT_UNDEFINED,
    ROLE_COMPUTED,
    ROLE_FINAL,
    ROLE_METHOD_VALUE,
    ROLE_USER_INPUT,
    TraceBundle,
    TraceCalculation,
    TraceDependency,
    TraceResult,
    TraceStep,
    TraceUnit,
    TraceValidationError,
    create_bundle,
    trace_identity_token,
    validate_bundle,
)
from .crack_trace_contract import (
    BOUNDARY,
    CODE,
    COVERAGE_ID,
    CRACK_WIDTH,
    EDITION,
    EFFECTIVE_AREA,
    ELASTIC,
    FAILED_STATES,
    FINITE_STATES,
    FOURTH_METRE,
    GEOMETRY,
    INPUT,
    KILONEWTON,
    KILONEWTON_METRE,
    KILONEWTON_PER_CUBIC_METRE,
    KILONEWTON_PER_SQUARE_METRE,
    MEAN_STRAIN,
    MEGAPASCAL,
    METHOD_ID,
    METRE,
    MILLIMETRE,
    ONE,
    SELECTION,
    SPACING_CLOSE,
    SPACING_WIDE,
    SQUARE_METRE,
    SQUARE_MILLIMETRE,
    UNDEFINED_STATES,
    MemberContractShape,
    registry_for,
)
from .elastic import solve_elastic_combined, transformed_properties
from .materials import ES as REFERENCE_ES
from .section import Bar, Section
from .section_trace_blocks import (
    SectionTraceBlocks,
    context_axes,
    context_id,
    section_trace_blocks,
)
from .serviceability import (
    CRACK_DIRECTIONAL_LIMITATION,
    CrackWidthEvaluation,
    analyse_cracking,
    combined_cracking,
    evaluate_crack_width,
)
from .sls import crack_outputs
from .trace_registry import audit_trace_registry


_MODES = frozenset({"Elastic", "Both"})
_SIZE_MODES = frozenset({"Area", "Diameter", "Independent"})
_PROPERTY_NAMES = ("area", "cx", "cy", "Ix", "Iy", "Ixy")
_ELEMENT_KEYS = (
    "id",
    "kind",
    "x_mm",
    "y_mm",
    "area_mm2",
    "diameter_mm",
    "size_mode",
    "material_id",
    "fatigue_detail_id",
    "x",
    "y",
)
_CASES = (
    ("long-term", "crack", 0.4),
    ("short-term", "crack_short", 0.6),
)


@dataclass(frozen=True, slots=True)
class ReplayedCase:
    name: str
    output_key: str
    kt: float
    modular_ratio: float
    evaluation: CrackWidthEvaluation
    state: Any | None
    output: Mapping[str, Any] | None


@dataclass(frozen=True, slots=True)
class Reconstructed:
    blocks: SectionTraceBlocks
    inputs: tuple[tuple[str, Any], ...]
    retained: Mapping[str, Any]
    cases: tuple[ReplayedCase, ...]
    cracked: bool
    cracking_factor: float
    tension_stress: float
    uncracked_properties: Any
    cracked_properties: Any | None


@dataclass(frozen=True, slots=True)
class NonConverged:
    inputs: tuple[tuple[str, Any], ...]
    candidate_structure: Any


def _mapping(value: Any, label: str, *, exact: bool = False) -> Mapping[str, Any]:
    valid = type(value) is dict if exact else isinstance(value, Mapping)
    if not valid:
        qualifier = "an exact dict" if exact else "a mapping"
        raise TraceValidationError(f"{label} must be {qualifier}")
    if any(type(key) is not str for key in value):
        raise TraceValidationError(f"{label} keys must be text")
    return value


def _sequence(value: Any, label: str) -> tuple[Any, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TraceValidationError(f"{label} must be an aligned sequence")
    return tuple(value)


def _required(value: Mapping[str, Any], key: str) -> Any:
    if key not in value:
        raise TraceValidationError(f"CT-009 requires {key}")
    return value[key]


def _finite(value: Any, label: str, *, positive: bool = False) -> float:
    if type(value) not in {int, float} or type(value) is bool:
        raise TraceValidationError(f"{label} must be a finite non-Boolean number")
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0.0):
        requirement = "positive finite" if positive else "finite"
        raise TraceValidationError(f"{label} must be {requirement}")
    return number


def _close(actual: Any, expected: float, label: str) -> None:
    number = _finite(actual, label)
    target = _finite(expected, f"{label} target")
    if number.hex() != target.hex():
        raise TraceValidationError(f"{label} is stale relative to the Section")


def _exact_form(value: Any, active: set[int] | None = None) -> Any:
    """Return a JSON-safe, exact type/order/cardinality/value representation."""

    if active is None:
        active = set()
    if value is None:
        return ["none"]
    if type(value) is bool:
        return ["bool", value]
    if type(value) is int:
        return ["int", str(value)]
    if type(value) is float:
        return ["float", value.hex()]
    if type(value) is str:
        return ["str", value]
    if type(value) is bytes:
        return ["bytes", value.hex()]
    if isinstance(value, np.generic):
        return ["numpy-scalar", value.dtype.str, _exact_form(value.item(), active)]

    identity = id(value)
    if identity in active:
        raise TraceValidationError("cyclic CT-009 identity is unsupported")
    active.add(identity)
    try:
        if isinstance(value, np.ndarray):
            payload = (
                [_exact_form(item, active) for item in value.flat]
                if value.dtype.hasobject
                else value.tobytes(order="C").hex()
            )
            return ["ndarray", value.dtype.str, list(value.shape), payload]
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return [
                "dataclass",
                value.__class__.__module__,
                value.__class__.__qualname__,
                [
                    [field.name, _exact_form(getattr(value, field.name), active)]
                    for field in dataclasses.fields(value)
                ],
            ]
        if isinstance(value, Mapping):
            return [
                "mapping",
                value.__class__.__module__,
                value.__class__.__qualname__,
                [
                    [_exact_form(key, active), _exact_form(item, active)]
                    for key, item in value.items()
                ],
            ]
        if type(value) in {list, tuple}:
            return [type(value).__name__, [_exact_form(item, active) for item in value]]
        if hasattr(value, "__dict__"):
            return [
                "object",
                value.__class__.__module__,
                value.__class__.__qualname__,
                _exact_form(vars(value), active),
            ]
        slots = getattr(value.__class__, "__slots__", ())
        if slots:
            names = (slots,) if type(slots) is str else tuple(slots)
            return [
                "slots",
                value.__class__.__module__,
                value.__class__.__qualname__,
                [
                    [name, _exact_form(getattr(value, name), active)]
                    for name in names
                    if hasattr(value, name)
                ],
            ]
    finally:
        active.remove(identity)
    raise TraceValidationError(
        "unsupported CT-009 identity type "
        f"{type(value).__module__}.{type(value).__qualname__}"
    )


def _structure(value: Any) -> Any:
    if isinstance(value, Mapping):
        return [
            "mapping",
            type(value).__module__,
            type(value).__qualname__,
            [[_exact_form(key), _structure(item)] for key, item in value.items()],
        ]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [
            "sequence",
            type(value).__module__,
            type(value).__qualname__,
            [_structure(item) for item in value],
        ]
    return ["leaf", type(value).__module__, type(value).__qualname__]


def _assert_exact(actual: Any, expected: Any, label: str) -> None:
    if _exact_form(actual) != _exact_form(expected):
        raise TraceValidationError(
            f"{label} differs in value, type, order, or cardinality from replay"
        )


def _digest_words(value: Any) -> tuple[float, ...]:
    encoded = json.dumps(
        _exact_form(value),
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    digest = hashlib.sha256(encoded).digest()
    return tuple(
        float(int.from_bytes(digest[offset:offset + 4], "big"))
        for offset in range(0, len(digest), 4)
    )


def _is_active(inp: Mapping[str, Any]) -> bool:
    mode = _required(inp, "mode")
    enabled = _required(inp, "sls_cw")
    if type(mode) is not str:
        raise TraceValidationError("mode must be text")
    if type(enabled) is not bool:
        raise TraceValidationError("sls_cw must be a Boolean")
    if mode not in _MODES or not enabled:
        return False

    code = _required(inp, "sls_code")
    edition = _required(inp, "sls_edition")
    dk_na = _required(inp, "sls_dk_na")
    if type(code) is not str or type(edition) is not str:
        raise TraceValidationError("sls_code and sls_edition must be text")
    if type(dk_na) is not bool:
        raise TraceValidationError("sls_dk_na must be a Boolean")
    if (code, edition, dk_na) != (CODE, EDITION, False):
        return False

    if "sls_crack_limit" in inp:
        raise TraceValidationError("removed sls_crack_limit cannot enter CT-009")

    if type(_required(inp, "sls_member")) is not str:
        raise TraceValidationError("sls_member must retain text type")
    tendon_xi = _required(inp, "sls_tendon_xi")
    if type(tendon_xi) not in {int, float} or type(tendon_xi) is bool:
        raise TraceValidationError("sls_tendon_xi must retain built-in numeric type")
    return True


def _validate_geometry(inp: Mapping[str, Any], blocks: SectionTraceBlocks) -> None:
    raw_rings = (
        _sequence(_required(inp, "outer"), "outer"),
        *(
            _sequence(hole, "hole")
            for hole in _sequence(_required(inp, "holes"), "holes")
        ),
    )
    if len(raw_rings) != len(blocks.geometry.rings):
        raise TraceValidationError("polygon ring count differs from the Section")
    for raw_ring, resolved_ring in zip(raw_rings, blocks.geometry.rings):
        if len(raw_ring) != len(resolved_ring):
            raise TraceValidationError("polygon ring cardinality differs from the Section")
        for raw_point, point in zip(raw_ring, resolved_ring):
            pair = _sequence(raw_point, "polygon point")
            if len(pair) != 2:
                raise TraceValidationError("polygon points require x and y")
            _close(pair[0], point[0], "polygon x")
            _close(pair[1], point[1], "polygon y")

    for kind, tuple_key, record_key, resolved_elements in (
        ("bar", "bars", "bar_elements", blocks.geometry.bars),
        ("tendon", "tendons", "tendon_elements", blocks.geometry.tendons),
    ):
        tuples = _sequence(_required(inp, tuple_key), tuple_key)
        records = _sequence(_required(inp, record_key), record_key)
        if len(tuples) != len(resolved_elements) or len(records) != len(resolved_elements):
            raise TraceValidationError(f"{kind} representations must align")
        for position, (raw_value, record_value, resolved) in enumerate(
            zip(tuples, records, resolved_elements)
        ):
            raw = _sequence(raw_value, f"{tuple_key}[{position}]")
            record = _mapping(record_value, f"{record_key}[{position}]", exact=True)
            if tuple(record) != _ELEMENT_KEYS:
                raise TraceValidationError(
                    f"{record_key}[{position}] must use the exact current schema"
                )
            if len(raw) != 3:
                raise TraceValidationError(f"{tuple_key}[{position}] requires x, y, area")
            if type(record["kind"]) is not str or record["kind"] != kind:
                raise TraceValidationError(f"{record_key}[{position}] kind is invalid")
            size_mode = record["size_mode"]
            if type(size_mode) is not str or size_mode not in _SIZE_MODES:
                raise TraceValidationError(f"{record_key}[{position}] size mode is invalid")
            if type(record["fatigue_detail_id"]) is not str:
                raise TraceValidationError("fatigue_detail_id must retain text type")
            area = _finite(
                record["area_mm2"],
                f"{record_key}[{position}] area_mm2",
                positive=True,
            )
            for actual, expected, label in (
                (raw[0], resolved.x, "raw x"),
                (raw[1], resolved.y, "raw y"),
                (raw[2], area, "raw area"),
                (record["x"], resolved.x, "record x"),
                (record["y"], resolved.y, "record y"),
                (record["x"], _finite(record["x_mm"], "x_mm") / 1000.0,
                 "record x/x_mm"),
                (record["y"], _finite(record["y_mm"], "y_mm") / 1000.0,
                 "record y/y_mm"),
                (resolved.area, area * 1.0e-6, "resolved area"),
            ):
                _close(actual, expected, f"{record_key}[{position}] {label}")
            diameter = _finite(record["diameter_mm"], "diameter_mm", positive=True)
            if size_mode == "Area":
                _close(
                    diameter,
                    math.sqrt(4.0 * area / math.pi),
                    f"{record_key}[{position}] area-derived diameter",
                )
            elif size_mode == "Diameter":
                _close(
                    area,
                    math.pi * diameter * diameter / 4.0,
                    f"{record_key}[{position}] area/diameter",
                )


def _assignment_identity(inp: Mapping[str, Any], key: str) -> Any:
    original = _required(inp, key)
    records = _sequence(original, key)
    sealed = []
    for position, raw in enumerate(records):
        record = _mapping(raw, f"{key}[{position}]", exact=True)
        if tuple(record) != _ELEMENT_KEYS:
            raise TraceValidationError(f"{key}[{position}] must use the exact current schema")
        sealed.append(tuple(
            (
                name,
                ("inert-fatigue-detail", type(value).__module__, type(value).__qualname__),
            )
            if name == "fatigue_detail_id"
            else (name, value)
            for name, value in record.items()
        ))
    return (type(original).__module__, type(original).__qualname__, tuple(sealed))


def _input_identity(
    inp: Mapping[str, Any], blocks: SectionTraceBlocks,
) -> tuple[tuple[str, Any], ...]:
    geometry = tuple(
        (key, _required(inp, key))
        for key in ("section", "outer", "holes", "bars", "tendons")
    ) + (("resolved", blocks.geometry),)
    materials = tuple(
        (key, _required(inp, key))
        for key in (
            "concrete",
            "steel",
            "prestress",
            "bar_materials",
            "tendon_materials",
            "concrete_preset",
            "mild_preset",
            "prestress_preset",
            "mild_material_catalog",
            "prestress_material_catalog",
        )
    )
    concrete_id = (
        inp["concrete_material_id"]
        if "concrete_material_id" in inp
        else ("missing-key", "concrete_material_id")
    )
    materials += (
        ("concrete_material_id", concrete_id),
        ("resolved-concrete", blocks.concrete),
        ("resolved-bars", blocks.bars),
        ("resolved-tendons", blocks.tendons),
    )
    assignments = (
        ("bar_elements", _assignment_identity(inp, "bar_elements")),
        ("tendon_elements", _assignment_identity(inp, "tendon_elements")),
    )
    controls = []
    inert_values = {"sls_member", "sls_tendon_xi"}
    for key in (
        "mode",
        "P_el_l",
        "Mx_el_l",
        "My_el_l",
        "P_el_s",
        "Mx_el_s",
        "My_el_s",
        "conc_Ec",
        "el_phi",
        "nl",
        "ns",
        "sls_fctm",
        "sls_cw",
        "sls_phi",
        "sls_k1",
        "sls_tendon_xi",
        "sls_code",
        "sls_edition",
        "sls_dk_na",
        "sls_member",
    ):
        value = _required(inp, key)
        if key in inert_values:
            value = ("inert-current-type", type(value).__module__, type(value).__qualname__)
        controls.append((key, value))
    return (
        ("geometry", geometry),
        ("materials", materials),
        ("assignments", assignments),
        ("controls", tuple(controls)),
    )


def _numeric_inputs(inp: Mapping[str, Any]) -> dict[str, float]:
    values = {
        key: _finite(_required(inp, key), key)
        for key in (
            "P_el_l",
            "Mx_el_l",
            "My_el_l",
            "P_el_s",
            "Mx_el_s",
            "My_el_s",
        )
    }
    for key in ("conc_Ec", "nl", "ns", "sls_fctm", "sls_k1"):
        values[key] = _finite(_required(inp, key), key, positive=True)
    for key in ("el_phi", "sls_phi"):
        values[key] = _finite(_required(inp, key), key)
        if values[key] < 0.0:
            raise TraceValidationError(f"{key} must be non-negative")
    expected_ns = REFERENCE_ES / (values["conc_Ec"] * 1000.0)
    expected_nl = expected_ns * (1.0 + values["el_phi"])
    for key, expected in (("ns", expected_ns), ("nl", expected_nl)):
        if not math.isclose(values[key], expected, rel_tol=1e-12, abs_tol=0.0):
            raise TraceValidationError(f"{key} is stale relative to Ec and creep")
    return values


def _material_value(material: Any, key: str, *, positive: bool = False) -> float:
    values = dict(material.values)
    if key not in values:
        raise TraceValidationError(f"{material.kind} law lacks {key}")
    return _finite(values[key], f"{material.kind} {key}", positive=positive)


def _section(blocks: SectionTraceBlocks) -> Section:
    return Section(
        [np.asarray(ring, dtype=float) for ring in blocks.geometry.rings],
        bars=[
            Bar(element.x, element.y, element.area)
            for element in (*blocks.geometry.bars, *blocks.geometry.tendons)
        ],
    )


def _solver_is_finite(result: Any) -> bool:
    retained = (
        result.long.strain_plane,
        result.short_term.strain_plane,
        result.bar_stress_total,
        result.bar_stress_long,
        result.bar_stress_dif,
        result.bar_stress_rst1,
        result.max_concrete_compression,
    )
    try:
        return bool(result.converged) and all(
            np.all(np.isfinite(np.asarray(value, dtype=float)))
            for value in retained
        )
    except (TypeError, ValueError):
        return False


def _element_label(
    blocks: SectionTraceBlocks, index: int,
) -> tuple[str, int, str]:
    if index < len(blocks.bars):
        return "Bar", index + 1, blocks.bars[index].element_id
    tendon_index = index - len(blocks.bars)
    if tendon_index < 0 or tendon_index >= len(blocks.tendons):
        raise TraceValidationError("crack result selects an unknown reinforcement element")
    return "Tendon", tendon_index + 1, blocks.tendons[tendon_index].element_id


def _result_payload(result: Any, blocks: SectionTraceBlocks) -> dict[str, Any] | None:
    if result is None:
        return None

    def candidate_payload(candidate: Any) -> dict[str, Any]:
        kind, number, element_id = _element_label(blocks, candidate.bar_index)
        return {
            "element_type": kind,
            "element_no": number,
            "element_id": element_id,
            "x_mm": candidate.x * 1000.0,
            "y_mm": candidate.y * 1000.0,
            "area_mm2": candidate.area,
            "wk": candidate.wk,
            "sr_max": candidate.sr_max,
            "esm_ecm": candidate.esm_ecm,
            "sigma_s": candidate.sigma_s,
            "rho_p_eff": candidate.rho_p_eff,
            "ac_eff": candidate.ac_eff,
            "hc_ef": candidate.hc_ef,
            "phi": candidate.phi,
            "cover": candidate.cover,
            "coarse": candidate.coarse,
            "edition": candidate.edition,
            "kw": candidate.kw,
            "k1_r": candidate.k1_r,
            "kfl": candidate.kfl,
            "sr_max_geometric": candidate.sr_max_geometric,
        }

    kind, number, element_id = _element_label(blocks, result.gov_bar)
    return {
        "wk": result.wk,
        "sr_max": result.sr_max,
        "esm_ecm": result.esm_ecm,
        "sigma_s": result.sigma_s,
        "rho_p_eff": result.rho_p_eff,
        "ac_eff": result.ac_eff,
        "hc_ef": result.hc_ef,
        "phi": result.phi,
        "cover": result.cover,
        "gov_bar": result.gov_bar + 1,
        "element_type": kind,
        "element_no": number,
        "element_id": element_id,
        "coarse": result.coarse,
        "edition": result.edition,
        "kw": result.kw,
        "k1_r": result.k1_r,
        "kfl": result.kfl,
        "sr_max_geometric": result.sr_max_geometric,
        "candidates": [candidate_payload(item) for item in result.candidates],
    }


def _property_payload(properties: Any) -> dict[str, float]:
    return {
        name: float(getattr(properties, name))
        for name in _PROPERTY_NAMES
    }


def _elastic_candidate(out: Mapping[str, Any]) -> Mapping[str, Any]:
    if "elastic" not in out:
        raise TraceValidationError("active CT-009 input requires elastic output")
    return _mapping(out["elastic"], "elastic output", exact=True)


def _is_crack_owned(key: str) -> bool:
    stems = ("cracked", "lambda_cr", "sigma_ct", "fctm", "show_cw")
    return (
        key == "converged"
        or key in {"sls_limit_source", "wk_limit", "crack_limit_source"}
        or key.startswith("sls_crack_")
        or key.startswith("crack")
        or key.startswith("props_")
        or any(key == stem or key.startswith(stem + "_") for stem in stems)
    )


def _validate_success_candidate(
    candidate: Mapping[str, Any], expected: Mapping[str, Any],
) -> None:
    owned = tuple(key for key in candidate if _is_crack_owned(key))
    if owned != tuple(expected):
        raise TraceValidationError("CT-009 success output inventory/order differs from replay")
    for key, value in expected.items():
        _assert_exact(candidate[key], value, f"elastic.{key}")


def _validate_failed_candidate(
    candidate: Mapping[str, Any], *, cracked: bool,
) -> Any:
    owned = tuple(key for key in candidate if _is_crack_owned(key))
    expected_owned = (
        "converged",
        "cracked",
        "lambda_cr",
        "sigma_ct",
        "fctm",
        "show_cw",
        "props_un",
        "props_cr",
        "crack",
        "crack_short",
        *(
            ("crack_code", "crack_edition", "crack_member")
            if cracked else ()
        ),
        "crack_output",
    )
    if owned != expected_owned:
        raise TraceValidationError(
            "failed CT-009 crack-owned inventory/order differs from the "
            "current retained failure surface"
        )
    if candidate["converged"] is not False:
        raise TraceValidationError("failed CT-009 output requires exact converged=false")
    aggregate = _mapping(candidate["crack_output"], "failed crack_output", exact=True)
    _assert_exact(
        aggregate,
        {
            "value": None,
            "case": None,
            "governing": None,
            "unit": "mm",
            "calculation_state": "INVALID",
        },
        "failed crack_output",
    )
    return _structure(candidate)


def _reconstruct(
    inp: Mapping[str, Any], out: Mapping[str, Any],
) -> Reconstructed | NonConverged:
    numbers = _numeric_inputs(inp)
    try:
        blocks = section_trace_blocks(inp)
        _validate_geometry(inp, blocks)
        section = _section(blocks)
    except TraceValidationError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"invalid CT-009 section identity: {exc}") from exc

    input_identity = _input_identity(inp, blocks)
    materials = (*blocks.bars, *blocks.tendons)
    moduli = np.asarray(
        [_material_value(material, "Es", positive=True) for material in materials],
        dtype=float,
    )
    multipliers = moduli / REFERENCE_ES
    locked_stress = None
    if blocks.tendons:
        locked_stress = np.asarray(
            [0.0] * len(blocks.bars)
            + [
                _material_value(material, "Es", positive=True)
                * _material_value(material, "IS")
                * 1000.0
                for material in blocks.tendons
            ],
            dtype=float,
        )

    long_force = -numbers["P_el_l"]
    short_force = -numbers["P_el_s"]
    combined = solve_elastic_combined(
        section,
        long_force,
        numbers["Mx_el_l"],
        numbers["My_el_l"],
        numbers["nl"],
        short_force,
        numbers["Mx_el_s"],
        numbers["My_el_s"],
        numbers["ns"],
        n_mult=multipliers,
        prestress_stress=locked_stress,
    )
    records = (
        *_sequence(_required(inp, "bar_elements"), "bar_elements"),
        *_sequence(_required(inp, "tendon_elements"), "tendon_elements"),
    )
    diameter: float | list[float] = numbers["sls_phi"]
    if diameter == 0.0:
        diameter = [
            _finite(
                _mapping(record, "element record", exact=True)["diameter_mm"],
                "diameter_mm",
                positive=True,
            )
            for record in records
        ]
    k1 = [numbers["sls_k1"]] * len(blocks.bars) + [1.6] * len(blocks.tendons)
    long_analysis = analyse_cracking(
        section,
        long_force,
        numbers["Mx_el_l"],
        numbers["My_el_l"],
        numbers["nl"],
        fctm=numbers["sls_fctm"],
        Es=moduli,
        beta=0.5,
        kt=0.4,
        bar_diameter=diameter,
        k1=k1,
        edition=EDITION,
        n_mult=multipliers,
        prestress_stress=locked_stress,
    )
    peak_cracked, peak_factor, peak_tension = combined_cracking(
        section,
        long_force,
        numbers["Mx_el_l"],
        numbers["My_el_l"],
        numbers["nl"],
        short_force,
        numbers["Mx_el_s"],
        numbers["My_el_s"],
        numbers["ns"],
        fctm=numbers["sls_fctm"],
        n_mult=multipliers,
        prestress_stress=locked_stress,
    )
    if peak_factor < long_analysis.lambda_cr:
        cracked = bool(peak_cracked)
        cracking_factor = float(peak_factor)
        tension_stress = float(peak_tension)
        governing_state = combined.short_term
    else:
        cracked = bool(long_analysis.cracked)
        cracking_factor = float(long_analysis.lambda_cr)
        tension_stress = float(long_analysis.sigma_ct)
        governing_state = long_analysis.cracked_state

    candidate = _elastic_candidate(out)
    converged = (
        _solver_is_finite(combined)
        and bool(long_analysis.uncracked.converged)
        and bool(long_analysis.cracked_state.converged)
    )
    if not converged:
        return NonConverged(
            input_identity,
            _validate_failed_candidate(candidate, cracked=cracked),
        )

    uncracked_properties = transformed_properties(
        section, numbers["nl"], cracked=False, n_mult=multipliers,
    )
    cracked_properties = (
        transformed_properties(
            section,
            numbers["nl"],
            eps0=governing_state.eps0,
            kx=governing_state.kx,
            ky=governing_state.ky,
            cracked=True,
            n_mult=multipliers,
        )
        if cracked
        else None
    )

    if cracked:
        short_stress = np.asarray(combined.bar_stress_total, dtype=float)
        if locked_stress is not None:
            short_stress = short_stress - locked_stress
        states = (
            long_analysis.cracked_state,
            dataclasses.replace(combined.short_term, bar_stress=short_stress),
        )
        reinforcement_types = (
            ["mild"] * len(blocks.bars)
            + ["prestress"] * len(blocks.tendons)
        )
        evaluations = tuple(
            evaluate_crack_width(
                section,
                state,
                ratio,
                fctm=numbers["sls_fctm"],
                Es=moduli,
                kt=kt,
                bar_diameter=diameter,
                k1=k1,
                edition=EDITION,
                n_mult=multipliers,
                reinforcement_types=reinforcement_types,
                bond_ratio_xi=None,
            )
            for state, ratio, (_name, _output_key, kt) in zip(
                states, (numbers["nl"], numbers["ns"]), _CASES
            )
        )
    else:
        states = (None, None)
        evaluations = (
            CrackWidthEvaluation("NOT APPLICABLE", "The section is uncracked."),
            CrackWidthEvaluation("NOT APPLICABLE", "The section is uncracked."),
        )

    cases = tuple(
        ReplayedCase(
            name,
            output_key,
            kt,
            ratio,
            evaluation,
            state,
            _result_payload(evaluation.result, blocks),
        )
        for (name, output_key, kt), ratio, evaluation, state in zip(
            _CASES,
            (numbers["nl"], numbers["ns"]),
            evaluations,
            states,
        )
    )
    expected: dict[str, Any] = {
        "converged": True,
        "cracked": cracked,
        "lambda_cr": cracking_factor,
        "sigma_ct": tension_stress,
        "fctm": numbers["sls_fctm"],
        "show_cw": True,
        "props_un": _property_payload(uncracked_properties),
        "props_cr": (
            None if cracked_properties is None
            else _property_payload(cracked_properties)
        ),
        "crack": cases[0].output,
        "crack_short": cases[1].output,
    }
    if cracked:
        expected.update(
            crack_code=CODE,
            crack_edition=EDITION,
            crack_member=None,
        )
    expected["crack_output"] = crack_outputs(
        {"Long-term": cases[0].output, "Short-term": cases[1].output},
        valid=True,
    )
    _validate_success_candidate(candidate, expected)
    return Reconstructed(
        blocks=blocks,
        inputs=input_identity,
        retained=expected,
        cases=cases,
        cracked=cracked,
        cracking_factor=cracking_factor,
        tension_stress=tension_stress,
        uncracked_properties=uncracked_properties,
        cracked_properties=cracked_properties,
    )


def _trace_number(value: Any, label: str) -> float:
    if type(value) not in {int, float} or type(value) is bool:
        raise TraceValidationError(f"{label} must be numeric")
    number = float(value)
    if math.isnan(number) or number == -math.inf:
        raise TraceValidationError(f"{label} cannot be NaN or negative infinity")
    return number


def _trace_result(value: Any) -> TraceResult:
    number = _trace_number(value, "trace value")
    if number == math.inf:
        return TraceResult(RESULT_POSITIVE_INFINITY, None, "Positive infinity")
    return TraceResult(RESULT_FINITE, number)


def _step(
    step_id: str,
    title: str,
    value: Any,
    unit: TraceUnit,
    role: str,
    source: Any,
    dependencies: Sequence[TraceStep] = (),
    *,
    expression: str = "Independent replay",
    result: TraceResult | None = None,
) -> TraceStep:
    number = _trace_number(value, f"{step_id} value")
    return TraceStep(
        step_id=step_id,
        title=title,
        dependencies=tuple(
            TraceDependency(dependency.step_id, dependency.unit)
            for dependency in dependencies
        ),
        quantity_role=role,
        source=source,
        symbol=step_id,
        unit=unit,
        actual_expression=expression,
        substituted_expression=(
            format(number, ".17g") if math.isfinite(number) else "inf"
        ),
        result=_trace_result(number) if result is None else result,
    )


def _identity_steps(
    groups: Sequence[tuple[str, Any]],
    *,
    source: Any,
    role: str,
    dependencies: Sequence[TraceStep] = (),
    prefix: str = "input",
) -> list[TraceStep]:
    steps = []
    for label, value in groups:
        token = trace_identity_token(label)
        for position, word in enumerate(_digest_words(value), start=1):
            steps.append(_step(
                f"{prefix}-{token}-sha256-{position}",
                f"Sealed {label} identity word {position}",
                word,
                ONE,
                role,
                source,
                dependencies,
                expression="SHA-256 word over exact retained identity",
            ))
    return steps


def _shape_for(
    member_id: str,
    calculation: TraceCalculation,
    result_states: frozenset[str],
) -> MemberContractShape:
    return MemberContractShape(
        member_id=member_id,
        calculation_id=calculation.calculation_id,
        axes=calculation.axes,
        steps=tuple(
            (
                step.step_id,
                step.quantity_role,
                step.source,
                tuple(dependency.step_id for dependency in step.dependencies),
            )
            for step in calculation.steps
        ),
        result_states=result_states,
    )


def _candidate_steps(
    candidate: Any,
    position: int,
    dependencies: Sequence[TraceStep],
) -> tuple[list[TraceStep], TraceStep]:
    prefix = f"candidate-{position:04d}"
    quantities = (
        ("position", candidate.bar_index + 1, ONE, SELECTION),
        ("x", candidate.x, METRE, GEOMETRY),
        ("y", candidate.y, METRE, GEOMETRY),
        ("area", candidate.area, SQUARE_MILLIMETRE, GEOMETRY),
        ("sigma-s", candidate.sigma_s, MEGAPASCAL, ELASTIC),
        ("hc-eff", candidate.hc_ef, METRE, EFFECTIVE_AREA),
        ("ac-eff", candidate.ac_eff, SQUARE_METRE, EFFECTIVE_AREA),
        ("as-eff", candidate.as_eff, SQUARE_METRE, EFFECTIVE_AREA),
        ("ap-eff", candidate.ap_eff, SQUARE_METRE, EFFECTIVE_AREA),
        (
            "ap-eff-weighted",
            candidate.ap_eff_weighted,
            SQUARE_METRE,
            EFFECTIVE_AREA,
        ),
        ("rho-p-eff", candidate.rho_p_eff, ONE, EFFECTIVE_AREA),
        ("phi", candidate.phi, MILLIMETRE, GEOMETRY),
        ("cover", candidate.cover, MILLIMETRE, GEOMETRY),
        ("esm-ecm", candidate.esm_ecm, ONE, MEAN_STRAIN),
        (
            "sr-max",
            candidate.sr_max,
            MILLIMETRE,
            SPACING_WIDE if candidate.sr_max_geometric else SPACING_CLOSE,
        ),
    )
    steps = [
        _step(
            f"{prefix}-{name}",
            name.replace("-", " ").title(),
            value,
            unit,
            ROLE_COMPUTED,
            source,
            dependencies,
        )
        for name, value, unit, source in quantities
    ]
    categorical_values = (
        candidate.reinforcement_type,
        candidate.scope,
        candidate.coarse,
        candidate.edition,
        candidate.kw,
        candidate.k1_r,
        candidate.kfl,
        candidate.sr_max_geometric,
        candidate.direction_deg,
        candidate.xi1,
        candidate.bc_ef,
        candidate.direct_tension,
    )
    category_steps = _identity_steps(
        ((f"{prefix}-categorical", categorical_values),),
        source=BOUNDARY,
        role=ROLE_COMPUTED,
        dependencies=(*dependencies, *steps),
        prefix=prefix,
    )
    steps.extend(category_steps)
    width = _step(
        f"{prefix}-wk",
        "Candidate characteristic crack width",
        candidate.wk,
        MILLIMETRE,
        ROLE_COMPUTED,
        CRACK_WIDTH,
        steps,
        expression="w_k = s_r,max * (epsilon_sm - epsilon_cm)",
    )
    steps.append(width)
    return steps, width


def _case_member(
    replay: Reconstructed,
    case: ReplayedCase,
    context: Mapping[str, Any],
) -> tuple[MemberContractShape, TraceCalculation]:
    steps = _identity_steps(replay.inputs, source=INPUT, role=ROLE_USER_INPUT)
    input_roots = tuple(steps)
    output_steps = _identity_steps(
        ((f"{case.name}-retained-output", case.output),),
        source=BOUNDARY,
        role=ROLE_COMPUTED,
        dependencies=input_roots,
        prefix="output",
    )
    steps.extend(output_steps)
    controls = dict(dict(replay.inputs)["controls"])
    suffix = "l" if case.name == "long-term" else "s"
    action_steps = [
        _step(
            f"input-{key.lower()}",
            key,
            controls[key],
            unit,
            ROLE_USER_INPUT,
            INPUT,
        )
        for key, unit in (
            (f"P_el_{suffix}", KILONEWTON),
            (f"Mx_el_{suffix}", KILONEWTON_METRE),
            (f"My_el_{suffix}", KILONEWTON_METRE),
        )
    ]
    method_steps = [
        _step(
            "case-modular-ratio",
            "Case modular ratio",
            case.modular_ratio,
            ONE,
            ROLE_METHOD_VALUE,
            ELASTIC,
        ),
        _step(
            "case-kt",
            "Load-duration coefficient",
            case.kt,
            ONE,
            ROLE_METHOD_VALUE,
            MEAN_STRAIN,
        ),
    ]
    steps.extend(action_steps)
    steps.extend(method_steps)
    roots = (*input_roots, *output_steps, *action_steps, *method_steps)

    plane_steps: list[TraceStep] = []
    stress_steps: list[TraceStep] = []
    if case.state is not None:
        plane_steps = [
            _step(
                f"cracked-state-{name}",
                f"Concrete-reference plane {name}",
                value,
                (
                    KILONEWTON_PER_SQUARE_METRE
                    if name == "q0"
                    else KILONEWTON_PER_CUBIC_METRE
                ),
                ROLE_COMPUTED,
                ELASTIC,
                roots,
            )
            for name, value in zip(
                ("q0", "qx", "qy"),
                (case.state.eps0, case.state.kx, case.state.ky),
            )
        ]
        steps.extend(plane_steps)
        stress_steps = [
            _step(
                f"element-{position:04d}-stress",
                f"Element {position} stress",
                float(value) / 1000.0,
                MEGAPASCAL,
                ROLE_COMPUTED,
                ELASTIC,
                plane_steps,
            )
            for position, value in enumerate(
                np.asarray(case.state.bar_stress, dtype=float), start=1
            )
        ]
        steps.extend(stress_steps)

    mechanics_roots = (*roots, *plane_steps, *stress_steps)
    if case.evaluation.result is None:
        final = _step(
            "crack-width-result",
            "Characteristic crack width",
            0.0,
            MILLIMETRE,
            ROLE_FINAL,
            SELECTION,
            mechanics_roots,
            expression="Publish explicit undefined/not-applicable disposition",
            result=TraceResult(
                RESULT_UNDEFINED,
                None,
                case.evaluation.reason,
            ),
        )
        states = UNDEFINED_STATES
        branch = "not-applicable"
    else:
        candidate_finals = []
        for position, candidate in enumerate(
            case.evaluation.result.candidates, start=1
        ):
            created, candidate_final = _candidate_steps(
                candidate, position, mechanics_roots
            )
            steps.extend(created)
            candidate_finals.append(candidate_final)
        final = _step(
            "crack-width-result",
            "Governing characteristic crack width",
            case.evaluation.result.wk,
            MILLIMETRE,
            ROLE_FINAL,
            SELECTION,
            (*mechanics_roots, *candidate_finals),
            expression="Select largest reconstructed candidate crack width",
        )
        states = FINITE_STATES
        branch = "calculated"
    steps.append(final)
    axes = context_axes(
        context,
        crack_branch=branch,
        crack_case=case.name,
        crack_code=trace_identity_token(CODE),
        crack_direction="dominant-strain-gradient",
        crack_edition=EDITION,
        crack_system="fine",
    )
    calculation = TraceCalculation(
        calculation_id=(
            f"ct-009-{context_id(context)}-{case.name}-base-crack-width"
        ),
        coverage_id=COVERAGE_ID,
        title=f"EN 1992-1-1:2004 {case.name} crack width",
        method_id=METHOD_ID,
        axes=axes,
        final_step_id=final.step_id,
        steps=tuple(steps),
        warnings=(CRACK_DIRECTIONAL_LIMITATION,),
        assumptions=(
            "No crack limit, utilisation, verdict, DK rule, or bridge rule is inferred.",
        ),
    )
    return _shape_for(case.name, calculation, states), calculation


def _aggregate_member(
    replay: Reconstructed,
    case_calculations: tuple[TraceCalculation, ...],
    context: Mapping[str, Any],
) -> tuple[MemberContractShape, TraceCalculation]:
    steps = _identity_steps(replay.inputs, source=INPUT, role=ROLE_USER_INPUT)
    input_roots = tuple(steps)
    output_steps = _identity_steps(
        (("retained-output", replay.retained),),
        source=BOUNDARY,
        role=ROLE_COMPUTED,
        dependencies=input_roots,
        prefix="output",
    )
    steps.extend(output_steps)
    roots = (*input_roots, *output_steps)
    state_steps = [
        _step(
            "retained-converged",
            "Retained convergence",
            1.0,
            ONE,
            ROLE_COMPUTED,
            ELASTIC,
            roots,
        ),
        _step(
            "retained-cracked",
            "Retained cracked state",
            1.0 if replay.cracked else 0.0,
            ONE,
            ROLE_COMPUTED,
            ELASTIC,
            roots,
        ),
        _step(
            "governing-sigma-ct",
            "Governing Stage I tension",
            replay.tension_stress,
            MEGAPASCAL,
            ROLE_COMPUTED,
            ELASTIC,
            roots,
        ),
        _step(
            "governing-cracking-factor",
            "Governing cracking factor",
            replay.cracking_factor,
            ONE,
            ROLE_COMPUTED,
            ELASTIC,
            roots,
        ),
    ]
    steps.extend(state_steps)
    property_steps = []
    for prefix, properties in (
        ("uncracked", replay.uncracked_properties),
        ("cracked", replay.cracked_properties),
    ):
        if properties is None:
            continue
        for name in _PROPERTY_NAMES:
            if name == "area":
                unit = SQUARE_METRE
            elif name in {"cx", "cy"}:
                unit = METRE
            else:
                unit = FOURTH_METRE
            property_steps.append(_step(
                f"{prefix}-property-{name.lower()}",
                f"{prefix} property {name}",
                getattr(properties, name),
                unit,
                ROLE_COMPUTED,
                ELASTIC,
                (*roots, *state_steps),
            ))
    steps.extend(property_steps)
    case_steps = []
    for position, calculation in enumerate(case_calculations, start=1):
        result = next(
            step.result
            for step in calculation.steps
            if step.step_id == calculation.final_step_id
        )
        case_steps.append(_step(
            f"case-{position}-final",
            f"Ordered case {position} disposition",
            result.value if result.value is not None else 0.0,
            MILLIMETRE,
            ROLE_COMPUTED,
            SELECTION,
            (*roots, *state_steps, *property_steps),
            result=result,
        ))
    steps.extend(case_steps)
    finite_values = [
        step.result.value
        for step in case_steps
        if step.result.state == RESULT_FINITE and step.result.value is not None
    ]
    if finite_values:
        final = _step(
            "crack-width-aggregate-result",
            "Governing retained crack width",
            max(finite_values),
            MILLIMETRE,
            ROLE_FINAL,
            SELECTION,
            tuple(steps),
            expression="Select largest calculated case crack width",
        )
        states = FINITE_STATES
        branch = "calculated"
    else:
        final = _step(
            "crack-width-aggregate-result",
            "Governing retained crack width",
            0.0,
            MILLIMETRE,
            ROLE_FINAL,
            SELECTION,
            tuple(steps),
            result=TraceResult(
                RESULT_UNDEFINED,
                None,
                "No retained crack-width case is applicable.",
            ),
        )
        states = UNDEFINED_STATES
        branch = "not-applicable"
    steps.append(final)
    axes = context_axes(
        context,
        crack_branch=branch,
        crack_case="aggregate",
        crack_code=trace_identity_token(CODE),
        crack_edition=EDITION,
        crack_member_cardinality=str(len(case_calculations)),
    )
    calculation = TraceCalculation(
        calculation_id=(
            f"ct-009-{context_id(context)}-base-crack-width-aggregate"
        ),
        coverage_id=COVERAGE_ID,
        title="EN 1992-1-1:2004 crack-width aggregate",
        method_id=METHOD_ID,
        axes=axes,
        final_step_id=final.step_id,
        steps=tuple(steps),
        warnings=(CRACK_DIRECTIONAL_LIMITATION,),
        assumptions=(
            "Case order is long-term then short-term; no verdict is implied.",
        ),
    )
    return _shape_for("aggregate", calculation, states), calculation


def _failed_member(
    replay: NonConverged,
    context: Mapping[str, Any],
) -> tuple[MemberContractShape, TraceCalculation]:
    steps = _identity_steps(replay.inputs, source=INPUT, role=ROLE_USER_INPUT)
    roots = tuple(steps)
    output_steps = _identity_steps(
        (("failure-output-structure", replay.candidate_structure),),
        source=BOUNDARY,
        role=ROLE_COMPUTED,
        dependencies=roots,
        prefix="output",
    )
    steps.extend(output_steps)
    final = _step(
        "crack-width-failed-result",
        "Crack-width replay failure",
        0.0,
        MILLIMETRE,
        ROLE_FINAL,
        BOUNDARY,
        (*roots, *output_steps),
        result=TraceResult(
            RESULT_FAILED,
            None,
            "Elastic/crack reconstruction did not converge; no value or verdict.",
        ),
    )
    steps.append(final)
    axes = context_axes(
        context,
        crack_branch="failed",
        crack_case="aggregate",
        crack_code=trace_identity_token(CODE),
        crack_edition=EDITION,
    )
    calculation = TraceCalculation(
        calculation_id=f"ct-009-{context_id(context)}-base-crack-width-failed",
        coverage_id=COVERAGE_ID,
        title="EN 1992-1-1:2004 crack-width failure",
        method_id=METHOD_ID,
        axes=axes,
        final_step_id=final.step_id,
        steps=tuple(steps),
        assumptions=(
            "Failure-only candidate numerics are not traversed; no verdict is implied.",
        ),
    )
    return _shape_for("failed", calculation, FAILED_STATES), calculation


def _expected_bundle(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any] | None,
) -> TraceBundle | None:
    input_mapping = _mapping(inp, "CT-009 input")
    output_mapping = _mapping(out, "analysis result")
    trace_context = {} if context is None else _mapping(context, "CT-009 context")
    if not _is_active(input_mapping):
        return None
    if _required(input_mapping, "section") is None:
        return None

    replay = _reconstruct(input_mapping, output_mapping)
    if isinstance(replay, NonConverged):
        shape, calculation = _failed_member(replay, trace_context)
        bundle = create_bundle(
            input_sha256=input_sha256,
            result_sha256=result_sha256,
            calculations=(calculation,),
        )
        return audit_trace_registry(bundle, registry_for((shape,)))

    pairs = tuple(
        _case_member(replay, case, trace_context)
        for case in replay.cases
    )
    case_shapes = tuple(pair[0] for pair in pairs)
    case_calculations = tuple(pair[1] for pair in pairs)
    aggregate_shape, aggregate = _aggregate_member(
        replay, case_calculations, trace_context
    )
    bundle = create_bundle(
        input_sha256=input_sha256,
        result_sha256=result_sha256,
        calculations=(*case_calculations, aggregate),
        warnings=(CRACK_DIRECTIONAL_LIMITATION,),
    )
    return audit_trace_registry(
        bundle,
        registry_for((*case_shapes, aggregate_shape)),
    )


def build_crack_trace_family(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle | None:
    """Build the exact CT-009 base trace, or return ``None`` if inactive."""

    return _expected_bundle(
        inp,
        out,
        input_sha256=input_sha256,
        result_sha256=result_sha256,
        context=context,
    )


def validate_crack_trace_family(
    bundle: TraceBundle | Mapping[str, Any] | None,
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle | None:
    """Validate a CT-009 trace against a fresh independent reconstruction."""

    expected = _expected_bundle(
        inp,
        out,
        input_sha256=input_sha256,
        result_sha256=result_sha256,
        context=context,
    )
    if expected is None:
        if bundle is not None:
            raise TraceValidationError("inactive CT-009 selector cannot retain a trace")
        return None
    if bundle is None:
        raise TraceValidationError("active CT-009 result requires a trace")
    candidate = validate_bundle(
        bundle,
        expected_input_sha256=input_sha256,
        expected_result_sha256=result_sha256,
    )
    if candidate != expected:
        raise TraceValidationError("CT-009 trace differs from independent reconstruction")
    return candidate


__all__ = ("build_crack_trace_family", "validate_crack_trace_family")
