"""Independent CT-009 replay for the EN 1992-1-1:2004 base crack method."""

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
    AREA,
    AREA_MM2,
    BOUNDARY,
    CODE,
    COVERAGE_ID,
    CRACK_WIDTH,
    EDITION,
    EFFECTIVE_AREA,
    ELASTIC,
    FAILURE_STATES,
    FORCE,
    GEOMETRY,
    INPUT,
    LENGTH,
    LENGTH_MM,
    MEAN_STRAIN,
    METHOD_ID,
    MOMENT,
    NOT_APPLICABLE_STATES,
    ONE,
    RAW_GRADIENT,
    RAW_STRESS,
    SECOND_MOMENT,
    SELECTION,
    SPACING_CLOSE,
    SPACING_WIDE,
    STRAIN,
    STRESS,
    SUCCESS_STATES,
    MemberShape,
    StepShape,
    registry_for,
)
from .elastic import solve_elastic_combined, transformed_properties
from .materials import ES as STEEL_REFERENCE_MODULUS
from .section import Bar, Section
from .section_trace_blocks import SectionTraceBlocks, context_axes, context_id
from .section_trace_blocks import section_trace_blocks
from .serviceability import (
    CRACK_DIRECTIONAL_LIMITATION,
    CrackWidthEvaluation,
    analyse_cracking,
    combined_cracking,
    evaluate_crack_width,
)
from .sls import crack_outputs
from .trace_registry import audit_trace_registry


_ACTIVE_MODES = frozenset({"Elastic", "Both"})
_CASES = (
    ("long-term", "crack", 0.4),
    ("short-term", "crack_short", 0.6),
)
_PROPERTY_FIELDS = ("area", "cx", "cy", "Ix", "Iy", "Ixy")
_HASH_WORDS = 8


@dataclass(frozen=True, slots=True)
class CaseReplay:
    name: str
    output_key: str
    kt: float
    n: float
    evaluation: CrackWidthEvaluation
    output: Mapping[str, Any] | None
    state: Any | None


@dataclass(frozen=True, slots=True)
class CrackReplay:
    blocks: SectionTraceBlocks
    cases: tuple[CaseReplay, ...]
    retained: Mapping[str, Any]
    input_groups: tuple[tuple[str, Any], ...]
    cracked: bool
    factor: float
    sigma_ct: float
    props_un: Any
    props_cr: Any | None


@dataclass(frozen=True, slots=True)
class FailureReplay:
    input_groups: tuple[tuple[str, Any], ...]
    output_shape: Any


def _mapping(value: Any, label: str, *, exact: bool = False) -> Mapping[str, Any]:
    invalid = type(value) is not dict if exact else not isinstance(value, Mapping)
    if invalid:
        kind = "an exact built-in dict" if exact else "a mapping"
        raise TraceValidationError(f"{label} must be {kind}")
    if any(type(key) is not str for key in value):
        raise TraceValidationError(f"{label} keys must be text")
    return value


def _sequence(value: Any, label: str) -> tuple[Any, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TraceValidationError(f"{label} must be an aligned sequence")
    return tuple(value)


def _required(inp: Mapping[str, Any], key: str) -> Any:
    if key not in inp:
        raise TraceValidationError(f"CT-009 requires {key}")
    return inp[key]


def _present_or_missing(inp: Mapping[str, Any], key: str) -> Any:
    return inp[key] if key in inp else ("missing-key", key)


def _number(value: Any, label: str, *, positive: bool = False) -> float:
    if type(value) not in {int, float} or type(value) is bool:
        raise TraceValidationError(f"{label} must be a finite non-Boolean number")
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0.0):
        qualifier = "positive finite" if positive else "finite"
        raise TraceValidationError(f"{label} must be a {qualifier} number")
    return number


def _bool(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise TraceValidationError(f"{label} must be an exact built-in Boolean")
    return value


def _text(value: Any, label: str) -> str:
    if type(value) is not str:
        raise TraceValidationError(f"{label} must be text")
    return value


def _typed(value: Any, active: set[int] | None = None) -> Any:
    """Return an exact type, order, cardinality, and float-bit identity tree."""

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
        return ["numpy-scalar", value.dtype.str, _typed(value.item(), active)]

    identity = id(value)
    if identity in active:
        raise TraceValidationError("cyclic CT-009 identity is unsupported")
    active.add(identity)
    try:
        if isinstance(value, np.ndarray):
            payload = (
                [_typed(item, active) for item in value.flat]
                if value.dtype.hasobject
                else value.tobytes(order="C").hex()
            )
            return ["numpy-array", value.dtype.str, list(value.shape), payload]
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return [
                "dataclass",
                value.__class__.__module__,
                value.__class__.__qualname__,
                [
                    [field.name, _typed(getattr(value, field.name), active)]
                    for field in dataclasses.fields(value)
                ],
            ]
        if isinstance(value, Mapping):
            return [
                "mapping",
                value.__class__.__module__,
                value.__class__.__qualname__,
                [
                    [_typed(key, active), _typed(item, active)]
                    for key, item in value.items()
                ],
            ]
        if type(value) in {list, tuple}:
            return [type(value).__name__, [_typed(item, active) for item in value]]
        if hasattr(value, "__dict__"):
            return [
                "object",
                value.__class__.__module__,
                value.__class__.__qualname__,
                _typed(vars(value), active),
            ]
        slots = getattr(value.__class__, "__slots__", ())
        if slots:
            names = (slots,) if type(slots) is str else tuple(slots)
            return [
                "slots",
                value.__class__.__module__,
                value.__class__.__qualname__,
                [
                    [name, _typed(getattr(value, name), active)]
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


def _shape_tree(value: Any) -> Any:
    """Retain failure-payload presence, order, type, and cardinality, not values."""

    if isinstance(value, Mapping):
        return [
            "mapping",
            value.__class__.__module__,
            value.__class__.__qualname__,
            [[_typed(key), _shape_tree(item)] for key, item in value.items()],
        ]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [
            "sequence",
            value.__class__.__module__,
            value.__class__.__qualname__,
            [_shape_tree(item) for item in value],
        ]
    return ["leaf", type(value).__module__, type(value).__qualname__]


def _digest_words(value: Any) -> tuple[float, ...]:
    encoded = json.dumps(
        _typed(value),
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    digest = hashlib.sha256(encoded).digest()
    return tuple(
        float(int.from_bytes(digest[index:index + 4], "big"))
        for index in range(0, 32, 4)
    )


def _same_exact(actual: Any, expected: Any, label: str) -> None:
    if _typed(actual) != _typed(expected):
        raise TraceValidationError(
            f"{label} differs in value, type, cardinality, or insertion order "
            "from authoritative replay"
        )


def _element_identity(inp: Mapping[str, Any], key: str) -> tuple[Any, ...]:
    raw_records = _required(inp, key)
    records = _sequence(raw_records, key)
    sealed = []
    for index, raw in enumerate(records):
        record = _mapping(raw, f"{key}[{index}]", exact=True)
        if "fatigue_detail_id" not in record:
            raise TraceValidationError(f"{key}[{index}] must retain fatigue_detail_id")
        if type(record["fatigue_detail_id"]) is not str:
            raise TraceValidationError(
                f"{key}[{index}].fatigue_detail_id must retain text type"
            )
        sealed.append(
            tuple(
                (name, ["inert-text", "fatigue-detail-value-excluded"])
                if name == "fatigue_detail_id"
                else (name, item)
                for name, item in record.items()
            )
        )
    return (
        "sequence-type",
        type(raw_records).__module__,
        type(raw_records).__qualname__,
        tuple(sealed),
    )


def _same_number(actual: Any, expected: float, label: str) -> None:
    number = _number(actual, label)
    if not math.isclose(number, float(expected), rel_tol=1.0e-13, abs_tol=1.0e-14):
        raise TraceValidationError(f"{label} is stale relative to section geometry")


def _validate_geometry_duplicates(
    inp: Mapping[str, Any],
    blocks: SectionTraceBlocks,
) -> None:
    """Reject stale raw/element/Section representations before branch replay."""

    outer = _sequence(_required(inp, "outer"), "outer")
    holes = _sequence(_required(inp, "holes"), "holes")
    raw_rings = (outer, *(_sequence(item, "hole") for item in holes))
    if len(raw_rings) != len(blocks.geometry.rings):
        raise TraceValidationError("raw polygon ring count differs from section")
    for ring_index, (raw_ring, resolved_ring) in enumerate(
        zip(raw_rings, blocks.geometry.rings)
    ):
        if len(raw_ring) != len(resolved_ring):
            raise TraceValidationError(
                f"raw polygon ring {ring_index} cardinality differs from section"
            )
        for point_index, (raw_point, resolved_point) in enumerate(
            zip(raw_ring, resolved_ring)
        ):
            point = _sequence(raw_point, f"ring {ring_index} point {point_index}")
            if len(point) != 2:
                raise TraceValidationError("polygon points must contain x and y")
            _same_number(point[0], resolved_point[0], "polygon x")
            _same_number(point[1], resolved_point[1], "polygon y")

    for kind, raw_key, element_key, resolved in (
        ("bar", "bars", "bar_elements", blocks.geometry.bars),
        ("tendon", "tendons", "tendon_elements", blocks.geometry.tendons),
    ):
        raw_items = _sequence(_required(inp, raw_key), raw_key)
        records = _sequence(_required(inp, element_key), element_key)
        if len(raw_items) != len(resolved) or len(records) != len(resolved):
            raise TraceValidationError(
                f"{kind} raw, element, and section cardinalities must align"
            )
        for index, (raw_item, record_value, block) in enumerate(
            zip(raw_items, records, resolved)
        ):
            raw = _sequence(raw_item, f"{raw_key}[{index}]")
            if len(raw) != 3:
                raise TraceValidationError(
                    f"{raw_key}[{index}] must contain x, y, and area"
                )
            record = _mapping(
                record_value, f"{element_key}[{index}]", exact=True
            )
            for key in (
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
            ):
                if key not in record:
                    raise TraceValidationError(
                        f"{element_key}[{index}] must retain {key}"
                    )
            if record["kind"] != kind or type(record["kind"]) is not str:
                raise TraceValidationError(
                    f"{element_key}[{index}].kind must be {kind!r}"
                )
            if type(record["size_mode"]) is not str or record["size_mode"] not in {
                "Area",
                "Diameter",
                "Independent",
            }:
                raise TraceValidationError(
                    f"{element_key}[{index}].size_mode is outside current schema"
                )
            for actual, expected, label in (
                (raw[0], block.x, f"{raw_key}[{index}] x"),
                (raw[1], block.y, f"{raw_key}[{index}] y"),
                (raw[2], block.area * 1.0e6, f"{raw_key}[{index}] area"),
                (record["x"], block.x, f"{element_key}[{index}].x"),
                (record["y"], block.y, f"{element_key}[{index}].y"),
                (record["x_mm"], block.x * 1000.0,
                 f"{element_key}[{index}].x_mm"),
                (record["y_mm"], block.y * 1000.0,
                 f"{element_key}[{index}].y_mm"),
                (record["area_mm2"], block.area * 1.0e6,
                 f"{element_key}[{index}].area_mm2"),
            ):
                _same_number(actual, expected, label)
            diameter = _number(
                record["diameter_mm"],
                f"{element_key}[{index}].diameter_mm",
                positive=True,
            )
            if record["size_mode"] != "Independent":
                equivalent_area = math.pi * diameter * diameter / 4.0
                _same_number(
                    record["area_mm2"],
                    equivalent_area,
                    f"{element_key}[{index}] area/diameter",
                )


def _input_identity(
    inp: Mapping[str, Any],
    blocks: SectionTraceBlocks,
) -> tuple[tuple[str, Any], ...]:
    """Freeze every base-branch input and its resolved immutable material blocks."""

    geometry = tuple(
        (key, _required(inp, key))
        for key in ("section", "outer", "holes", "bars", "tendons")
    ) + (("resolved", blocks.geometry),)
    materials = tuple(
        (
            key,
            _present_or_missing(inp, key)
            if key == "concrete_material_id"
            else _required(inp, key),
        )
        for key in (
            "concrete",
            "steel",
            "prestress",
            "bar_materials",
            "tendon_materials",
            "concrete_material_id",
            "concrete_preset",
            "mild_preset",
            "prestress_preset",
            "mild_material_catalog",
            "prestress_material_catalog",
        )
    ) + (
        ("resolved-concrete", blocks.concrete),
        ("resolved-bars", blocks.bars),
        ("resolved-tendons", blocks.tendons),
    )
    assignments = (
        ("bar_elements", _element_identity(inp, "bar_elements")),
        ("tendon_elements", _element_identity(inp, "tendon_elements")),
    )
    controls = tuple(
        (
            key,
            [
                "inert-sibling-type",
                type(_required(inp, key)).__module__,
                type(inp[key]).__qualname__,
            ]
            if key in {"sls_tendon_xi", "sls_member"}
            else _required(inp, key),
        )
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
        )
    )
    return (
        ("geometry", geometry),
        ("materials-and-catalogues", materials),
        ("element-assignments", assignments),
        ("crack-controls-and-actions", controls),
    )


def _law_value(material: Any, name: str) -> float:
    values = dict(material.values)
    if name not in values:
        raise TraceValidationError(
            f"assigned {material.kind} law lacks {name}"
        )
    return _number(values[name], f"{material.kind} {material.element_id} {name}")


def _folded_section(blocks: SectionTraceBlocks) -> Section:
    return Section(
        [np.asarray(ring, dtype=float) for ring in blocks.geometry.rings],
        bars=[
            Bar(item.x, item.y, item.area)
            for item in (*blocks.geometry.bars, *blocks.geometry.tendons)
        ],
    )


def _element_ids(blocks: SectionTraceBlocks, index: int) -> tuple[str, int, str]:
    if index < len(blocks.bars):
        return "Bar", index + 1, blocks.bars[index].element_id
    tendon_index = index - len(blocks.bars)
    return "Tendon", tendon_index + 1, blocks.tendons[tendon_index].element_id


def _crack_payload(result: Any, blocks: SectionTraceBlocks) -> dict[str, Any] | None:
    """Reconstruct the exact retained app serializer without trusting it."""

    if result is None:
        return None

    def candidate(item: Any) -> dict[str, Any]:
        kind, number, element_id = _element_ids(blocks, item.bar_index)
        return {
            "element_type": kind,
            "element_no": number,
            "element_id": element_id,
            "x_mm": item.x * 1000.0,
            "y_mm": item.y * 1000.0,
            "area_mm2": item.area,
            "wk": item.wk,
            "sr_max": item.sr_max,
            "esm_ecm": item.esm_ecm,
            "sigma_s": item.sigma_s,
            "rho_p_eff": item.rho_p_eff,
            "ac_eff": item.ac_eff,
            "hc_ef": item.hc_ef,
            "phi": item.phi,
            "cover": item.cover,
            "coarse": item.coarse,
            "edition": item.edition,
            "kw": item.kw,
            "k1_r": item.k1_r,
            "kfl": item.kfl,
            "sr_max_geometric": item.sr_max_geometric,
        }

    kind, number, element_id = _element_ids(blocks, result.gov_bar)
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
        "candidates": [candidate(item) for item in result.candidates],
    }


def _properties(item: Any) -> dict[str, float]:
    return {name: float(getattr(item, name)) for name in _PROPERTY_FIELDS}


def _finite_solver(result: Any) -> bool:
    values = (
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
            np.all(np.isfinite(np.asarray(value, dtype=float))) for value in values
        )
    except (TypeError, ValueError):
        return False


def _validate_dispatch(inp: Mapping[str, Any]) -> bool:
    for key in ("mode", "sls_code", "sls_edition", "sls_member"):
        _text(_required(inp, key), key)
    for key in ("sls_cw", "sls_dk_na"):
        _bool(_required(inp, key), key)
    sibling = _required(inp, "sls_tendon_xi")
    if type(sibling) not in {int, float} or type(sibling) is bool:
        raise TraceValidationError(
            "sls_tendon_xi excluded sibling must retain built-in numeric type"
        )

    if inp["mode"] not in _ACTIVE_MODES or not inp["sls_cw"]:
        return False
    if inp["sls_code"] != CODE:
        return False
    if inp["sls_edition"] != EDITION or inp["sls_dk_na"]:
        raise TraceValidationError(
            "EN 1992-1-1:2005 must retain edition=2004 and dk_na=false"
        )
    return True


def _validate_numbers(inp: Mapping[str, Any]) -> dict[str, float]:
    values = {
        key: _number(_required(inp, key), key)
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
        values[key] = _number(_required(inp, key), key, positive=True)
    for key in ("el_phi", "sls_phi"):
        values[key] = _number(_required(inp, key), key)
        if values[key] < 0.0:
            raise TraceValidationError(f"{key} must be non-negative")

    expected_ns = STEEL_REFERENCE_MODULUS / (values["conc_Ec"] * 1000.0)
    expected_nl = expected_ns * (1.0 + values["el_phi"])
    for key, expected in (("ns", expected_ns), ("nl", expected_nl)):
        if not math.isclose(values[key], expected, rel_tol=1.0e-12, abs_tol=0.0):
            raise TraceValidationError(
                f"{key} is stale relative to conc_Ec and el_phi"
            )
    return values


def _retained_candidate(out: Mapping[str, Any]) -> Mapping[str, Any]:
    if "elastic" not in out:
        raise TraceValidationError(
            "active CT-009 input requires the retained elastic output"
        )
    return _mapping(out["elastic"], "CT-009 elastic output", exact=True)


def _check_output_inventory(
    candidate: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> None:
    owned_scalars = {
        "converged",
        "cracked",
        "lambda_cr",
        "sigma_ct",
        "fctm",
        "show_cw",
    }
    actual_order = tuple(
        key
        for key in candidate
        if any(key == stem or key.startswith(f"{stem}_") for stem in owned_scalars)
        or key.startswith("crack")
        or key.startswith("props_")
    )
    if actual_order != tuple(expected):
        raise TraceValidationError(
            "CT-009 retained output inventory/order differs from replay"
        )
    for key, value in expected.items():
        _same_exact(candidate[key], value, f"elastic.{key}")


def _replay(inp: Mapping[str, Any], out: Mapping[str, Any]) -> CrackReplay | FailureReplay:
    numbers = _validate_numbers(inp)
    try:
        blocks = section_trace_blocks(inp)
        _validate_geometry_duplicates(inp, blocks)
        section = _folded_section(blocks)
    except TraceValidationError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"invalid CT-009 section identity: {exc}") from exc

    input_groups = _input_identity(inp, blocks)
    moduli = np.asarray(
        [_law_value(item, "Es") for item in (*blocks.bars, *blocks.tendons)],
        dtype=float,
    )
    if not moduli.size:
        raise TraceValidationError("CT-009 needs crack-control reinforcement")
    if np.any(~np.isfinite(moduli)) or np.any(moduli <= 0.0):
        raise TraceValidationError("assigned reinforcement moduli must be positive")
    n_mult = moduli / STEEL_REFERENCE_MODULUS
    locked = None
    if blocks.tendons:
        locked = np.asarray(
            [0.0] * len(blocks.bars)
            + [
                _law_value(item, "Es") * _law_value(item, "IS") * 1000.0
                for item in blocks.tendons
            ],
            dtype=float,
        )

    p_long = -numbers["P_el_l"]
    p_short = -numbers["P_el_s"]
    combined = solve_elastic_combined(
        section,
        p_long,
        numbers["Mx_el_l"],
        numbers["My_el_l"],
        numbers["nl"],
        p_short,
        numbers["Mx_el_s"],
        numbers["My_el_s"],
        numbers["ns"],
        n_mult=n_mult,
        prestress_stress=locked,
    )
    diameter = (
        numbers["sls_phi"]
        if numbers["sls_phi"] > 0.0
        else [
            _number(item["diameter_mm"], "element diameter", positive=True)
            for item in (
                list(_sequence(_required(inp, "bar_elements"), "bar_elements"))
                + list(
                    _sequence(
                        _required(inp, "tendon_elements"), "tendon_elements"
                    )
                )
            )
        ]
    )
    k1 = [numbers["sls_k1"]] * len(blocks.bars) + [1.6] * len(blocks.tendons)
    long = analyse_cracking(
        section,
        p_long,
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
        n_mult=n_mult,
        prestress_stress=locked,
    )
    peak_cracked, peak_factor, peak_sigma = combined_cracking(
        section,
        p_long,
        numbers["Mx_el_l"],
        numbers["My_el_l"],
        numbers["nl"],
        p_short,
        numbers["Mx_el_s"],
        numbers["My_el_s"],
        numbers["ns"],
        fctm=numbers["sls_fctm"],
        n_mult=n_mult,
        prestress_stress=locked,
    )
    candidate = _retained_candidate(out)
    converged = (
        _finite_solver(combined)
        and bool(long.uncracked.converged)
        and bool(long.cracked_state.converged)
    )
    if not converged:
        if candidate.get("converged") is not False:
            raise TraceValidationError(
                "failed CT-009 replay requires retained converged=false"
            )
        if "crack_output" not in candidate:
            raise TraceValidationError(
                "failed CT-009 requires retained INVALID crack_output"
            )
        aggregate = _mapping(
            candidate["crack_output"],
            "failed CT-009 crack_output",
            exact=True,
        )
        _same_exact(
            aggregate,
            {
                "value": None,
                "case": None,
                "governing": None,
                "unit": "mm",
                "calculation_state": "INVALID",
            },
            "failed CT-009 crack_output",
        )
        return FailureReplay(input_groups, _shape_tree(candidate))

    if peak_factor < long.lambda_cr:
        cracked = bool(peak_cracked)
        factor = float(peak_factor)
        sigma_ct = float(peak_sigma)
        governing_state = combined.short_term
    else:
        cracked = bool(long.cracked)
        factor = float(long.lambda_cr)
        sigma_ct = float(long.sigma_ct)
        governing_state = long.cracked_state

    props_un = transformed_properties(
        section, numbers["nl"], cracked=False, n_mult=n_mult
    )
    props_cr = (
        transformed_properties(
            section,
            numbers["nl"],
            eps0=governing_state.eps0,
            kx=governing_state.kx,
            ky=governing_state.ky,
            cracked=True,
            n_mult=n_mult,
        )
        if cracked
        else None
    )
    ratios = (numbers["nl"], numbers["ns"])
    states: tuple[Any | None, ...]
    evaluations: tuple[CrackWidthEvaluation, ...]
    if cracked:
        short_stress = np.asarray(combined.bar_stress_total, dtype=float)
        if locked is not None:
            short_stress = short_stress - locked
        states = (
            long.cracked_state,
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
                n_mult=n_mult,
                reinforcement_types=reinforcement_types,
                bond_ratio_xi=None,
            )
            for state, ratio, (_name, _key, kt) in zip(states, ratios, _CASES)
        )
    else:
        states = (None, None)
        evaluations = (
            CrackWidthEvaluation("NOT APPLICABLE", "The section is uncracked."),
            CrackWidthEvaluation("NOT APPLICABLE", "The section is uncracked."),
        )

    cases = tuple(
        CaseReplay(
            name=name,
            output_key=key,
            kt=kt,
            n=ratio,
            evaluation=evaluation,
            output=_crack_payload(evaluation.result, blocks),
            state=state,
        )
        for (name, key, kt), ratio, evaluation, state in zip(
            _CASES, ratios, evaluations, states
        )
    )
    expected: dict[str, Any] = {
        "converged": True,
        "cracked": cracked,
        "lambda_cr": factor,
        "sigma_ct": sigma_ct,
        "fctm": numbers["sls_fctm"],
        "show_cw": True,
        "props_un": _properties(props_un),
        "props_cr": None if props_cr is None else _properties(props_cr),
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
    _check_output_inventory(candidate, expected)
    return CrackReplay(
        blocks=blocks,
        cases=cases,
        retained=expected,
        input_groups=input_groups,
        cracked=cracked,
        factor=factor,
        sigma_ct=sigma_ct,
        props_un=props_un,
        props_cr=props_cr,
    )


def _numeric_result(value: float) -> TraceResult:
    number = float(value)
    if math.isfinite(number):
        return TraceResult(RESULT_FINITE, number)
    if number > 0.0:
        return TraceResult(
            RESULT_POSITIVE_INFINITY,
            None,
            "The reconstructed value is positive infinity.",
        )
    return TraceResult(
        RESULT_UNDEFINED,
        None,
        "The reconstructed value is not a finite or positive-infinite result.",
    )


def _format(value: float) -> str:
    number = float(value)
    return format(number, ".17g") if math.isfinite(number) else str(number)


def _step(
    step_id: str,
    title: str,
    value: float,
    unit: TraceUnit,
    role: str,
    source: Any,
    dependencies: Sequence[TraceStep] = (),
    *,
    expression: str = "Replay the independently reconstructed retained value",
    result: TraceResult | None = None,
) -> TraceStep:
    return TraceStep(
        step_id=step_id,
        title=title,
        dependencies=tuple(
            TraceDependency(item.step_id, item.unit) for item in dependencies
        ),
        quantity_role=role,
        source=source,
        symbol=step_id,
        unit=unit,
        actual_expression=expression,
        substituted_expression=_format(value),
        result=_numeric_result(value) if result is None else result,
    )


def _input_steps(groups: tuple[tuple[str, Any], ...]) -> list[TraceStep]:
    steps = []
    for group, value in groups:
        token = trace_identity_token(group)
        for position, word in enumerate(_digest_words(value), start=1):
            steps.append(
                _step(
                    f"input-{token}-sha256-{position}",
                    f"Sealed {group} identity word {position}",
                    word,
                    ONE,
                    ROLE_USER_INPUT,
                    INPUT,
                    expression=(
                        "SHA-256 word over exact input type, order, cardinality, "
                        "and float-bit identity"
                    ),
                )
            )
    return steps


def _sealed_steps(
    label: str,
    value: Any,
    dependencies: Sequence[TraceStep],
) -> list[TraceStep]:
    token = trace_identity_token(label)
    return [
        _step(
            f"{token}-sha256-{position}",
            f"Sealed {label} word {position}",
            word,
            ONE,
            ROLE_COMPUTED,
            BOUNDARY,
            dependencies,
            expression="SHA-256 word over independently reconstructed evidence",
        )
        for position, word in enumerate(_digest_words(value), start=1)
    ]


def _shape(
    member_id: str,
    calculation: TraceCalculation,
    states: frozenset[str],
) -> MemberShape:
    return MemberShape(
        member_id=member_id,
        calculation_id=calculation.calculation_id,
        axes=calculation.axes,
        steps=tuple(
            StepShape(
                step.step_id,
                step.quantity_role,
                step.source,
                tuple(item.step_id for item in step.dependencies),
            )
            for step in calculation.steps
        ),
        result_states=states,
    )


def _case_member(
    replay: CrackReplay,
    case: CaseReplay,
    context: Mapping[str, Any],
) -> tuple[MemberShape, TraceCalculation]:
    steps = _input_steps(replay.input_groups)
    input_roots = tuple(steps)
    output_steps = _sealed_steps(
        f"{case.name}-retained-output",
        case.output,
        input_roots,
    )
    steps.extend(output_steps)
    controls = dict(dict(replay.input_groups)["crack-controls-and-actions"])
    suffix = "l" if case.name == "long-term" else "s"
    action_steps = [
        _step(
            f"input-{trace_identity_token(key)}",
            title,
            float(controls[key]),
            unit,
            ROLE_USER_INPUT,
            INPUT,
        )
        for key, title, unit in (
            (f"P_el_{suffix}", "Axial action", FORCE),
            (f"Mx_el_{suffix}", "Bending action Mx", MOMENT),
            (f"My_el_{suffix}", "Bending action My", MOMENT),
        )
    ]
    method_steps = [
        _step(
            "case-modular-ratio",
            "Case modular ratio",
            case.n,
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

    if case.evaluation.result is None:
        final = _step(
            "crack-width-result",
            "Characteristic crack width",
            0.0,
            LENGTH_MM,
            ROLE_FINAL,
            SELECTION,
            roots,
            expression="Publish explicit non-applicable crack-width disposition",
            result=TraceResult(
                RESULT_UNDEFINED,
                None,
                case.evaluation.reason,
            ),
        )
        steps.append(final)
        result_states = NOT_APPLICABLE_STATES
        branch = "not-applicable"
    else:
        result = case.evaluation.result
        state = case.state
        plane_steps = [
            _step(
                f"cracked-state-{component}",
                f"Cracked-state concrete-reference plane {component}",
                float(value),
                RAW_STRESS if component == "q0" else RAW_GRADIENT,
                ROLE_COMPUTED,
                ELASTIC,
                roots,
            )
            for component, value in zip(
                ("q0", "qx", "qy"),
                (state.eps0, state.kx, state.ky),
            )
        ]
        steps.extend(plane_steps)
        stress_steps = [
            _step(
                f"element-{position:04d}-stress",
                f"Element {position} load-induced tension stress",
                float(stress) / 1000.0,
                STRESS,
                ROLE_COMPUTED,
                ELASTIC,
                plane_steps,
            )
            for position, stress in enumerate(
                np.asarray(state.bar_stress), start=1
            )
        ]
        steps.extend(stress_steps)

        candidate_finals = []
        for position, item in enumerate(result.candidates, start=1):
            prefix = f"candidate-{position:04d}"
            candidate_roots = (*roots, *plane_steps, *stress_steps)
            fields = (
                ("element-index", "Element solver index", item.bar_index + 1,
                 ONE, SELECTION),
                ("x", "Element x coordinate", item.x, LENGTH, GEOMETRY),
                ("y", "Element y coordinate", item.y, LENGTH, GEOMETRY),
                ("area", "Element area", item.area, AREA_MM2, GEOMETRY),
                ("sigma-s", "Steel stress", item.sigma_s, STRESS, ELASTIC),
                ("hc-eff", "Effective tension height", item.hc_ef, LENGTH,
                 EFFECTIVE_AREA),
                ("ac-eff", "Effective concrete tension area", item.ac_eff, AREA,
                 EFFECTIVE_AREA),
                ("as-eff", "Effective mild reinforcement area", item.as_eff, AREA,
                 EFFECTIVE_AREA),
                ("ap-eff", "Effective prestressing area", item.ap_eff, AREA,
                 EFFECTIVE_AREA),
                ("ap-eff-weighted", "Weighted prestressing area",
                 item.ap_eff_weighted, AREA, EFFECTIVE_AREA),
                ("rho-p-eff", "Effective reinforcement ratio", item.rho_p_eff,
                 ONE, EFFECTIVE_AREA),
                ("phi", "Element diameter", item.phi, LENGTH_MM, GEOMETRY),
                ("cover", "Element clear cover", item.cover, LENGTH_MM, GEOMETRY),
                ("esm-ecm", "Mean strain difference", item.esm_ecm, STRAIN,
                 MEAN_STRAIN),
                ("sr-max", "Maximum crack spacing", item.sr_max, LENGTH_MM,
                 SPACING_WIDE if item.sr_max_geometric else SPACING_CLOSE),
            )
            created = [
                _step(
                    f"{prefix}-{suffix_name}",
                    title,
                    float(value),
                    unit,
                    ROLE_COMPUTED,
                    source,
                    candidate_roots,
                )
                for suffix_name, title, value, unit, source in fields
            ]
            steps.extend(created)
            hidden = (
                item.reinforcement_type,
                item.scope,
                item.coarse,
                item.edition,
                item.kw,
                item.k1_r,
                item.kfl,
                item.sr_max_geometric,
                item.direction_deg,
                item.xi1,
                item.bc_ef,
                item.direct_tension,
            )
            category = _step(
                f"{prefix}-categorical-identity",
                "Candidate categorical and branch identity",
                _digest_words(hidden)[0],
                ONE,
                ROLE_COMPUTED,
                BOUNDARY,
                (*candidate_roots, *created),
                expression="SHA-256 word over retained categorical fields",
            )
            steps.append(category)
            width = _step(
                f"{prefix}-wk",
                "Candidate characteristic crack width",
                item.wk,
                LENGTH_MM,
                ROLE_COMPUTED,
                CRACK_WIDTH,
                (*created, category),
                expression="w_k = s_r,max * (epsilon_sm - epsilon_cm)",
            )
            steps.append(width)
            candidate_finals.append(width)

        final = _step(
            "crack-width-result",
            "Governing characteristic crack width",
            result.wk,
            LENGTH_MM,
            ROLE_FINAL,
            SELECTION,
            (*roots, *candidate_finals),
            expression="Select largest candidate w_k; tie-break by solver index",
        )
        steps.append(final)
        result_states = SUCCESS_STATES
        branch = "calculated"

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
            "Only the selected EN 1992-1-1:2004 base method is replayed.",
            "No limit, utilisation, compliance verdict, DK rule, or bridge rule is inferred.",
        ),
    )
    return _shape(case.name, calculation, result_states), calculation


def _aggregate_member(
    replay: CrackReplay,
    cases: tuple[TraceCalculation, ...],
    context: Mapping[str, Any],
) -> tuple[MemberShape, TraceCalculation]:
    steps = _input_steps(replay.input_groups)
    input_roots = tuple(steps)
    output_steps = _sealed_steps("retained-output", replay.retained, input_roots)
    steps.extend(output_steps)
    roots = (*input_roots, *output_steps)
    state_steps = [
        _step(
            "retained-converged",
            "Retained convergence state",
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
            "Governing Stage I concrete tension",
            replay.sigma_ct,
            STRESS,
            ROLE_COMPUTED,
            ELASTIC,
            roots,
        ),
        _step(
            "governing-cracking-factor",
            "Governing first-cracking factor",
            replay.factor,
            ONE,
            ROLE_COMPUTED,
            ELASTIC,
            roots,
        ),
    ]
    steps.extend(state_steps)
    property_steps = []
    for prefix, props in (
        ("uncracked", replay.props_un),
        ("cracked", replay.props_cr),
    ):
        if props is None:
            continue
        for name in _PROPERTY_FIELDS:
            unit = (
                AREA
                if name == "area"
                else LENGTH
                if name in {"cx", "cy"}
                else SECOND_MOMENT
            )
            property_steps.append(
                _step(
                    f"{prefix}-property-{name.lower()}",
                    f"{prefix.title()} transformed property {name}",
                    float(getattr(props, name)),
                    unit,
                    ROLE_COMPUTED,
                    ELASTIC,
                    (*roots, *state_steps),
                )
            )
    steps.extend(property_steps)
    case_steps = []
    for position, calculation in enumerate(cases, start=1):
        case_final = next(
            item for item in calculation.steps if item.step_id == calculation.final_step_id
        )
        case_steps.append(
            _step(
                f"case-{position}-final",
                f"Ordered case {position} final disposition",
                case_final.result.value or 0.0,
                LENGTH_MM,
                ROLE_COMPUTED,
                SELECTION,
                (*roots, *state_steps, *property_steps),
                result=case_final.result,
            )
        )
    steps.extend(case_steps)
    values = [
        item.result.value
        for item in case_steps
        if item.result.state == RESULT_FINITE and item.result.value is not None
    ]
    has_infinity = any(
        item.result.state == RESULT_POSITIVE_INFINITY for item in case_steps
    )
    if has_infinity or values:
        value = math.inf if has_infinity else max(values)
        final = _step(
            "crack-width-aggregate-result",
            "Governing retained crack width",
            value,
            LENGTH_MM,
            ROLE_FINAL,
            SELECTION,
            tuple(steps),
            expression="Select largest calculated case crack width",
        )
        result_states = SUCCESS_STATES
        branch = "calculated"
    else:
        final = _step(
            "crack-width-aggregate-result",
            "Governing retained crack width",
            0.0,
            LENGTH_MM,
            ROLE_FINAL,
            SELECTION,
            tuple(steps),
            expression="Publish no fabricated value when no case is applicable",
            result=TraceResult(
                RESULT_UNDEFINED,
                None,
                "No retained crack-width case is applicable.",
            ),
        )
        result_states = NOT_APPLICABLE_STATES
        branch = "not-applicable"
    steps.append(final)
    axes = context_axes(
        context,
        crack_branch=branch,
        crack_case="aggregate",
        crack_code=trace_identity_token(CODE),
        crack_edition=EDITION,
        crack_member_cardinality=str(len(cases)),
    )
    calculation = TraceCalculation(
        calculation_id=f"ct-009-{context_id(context)}-base-crack-width-aggregate",
        coverage_id=COVERAGE_ID,
        title="EN 1992-1-1:2004 crack-width aggregate",
        method_id=METHOD_ID,
        axes=axes,
        final_step_id=final.step_id,
        steps=tuple(steps),
        warnings=(CRACK_DIRECTIONAL_LIMITATION,),
        assumptions=(
            "Case order is long-term then short-term.",
            "Transformed properties are evidence, not resistance or compliance limits.",
        ),
    )
    return _shape("aggregate", calculation, result_states), calculation


def _failure_member(
    replay: FailureReplay,
    context: Mapping[str, Any],
) -> tuple[MemberShape, TraceCalculation]:
    steps = _input_steps(replay.input_groups)
    roots = tuple(steps)
    shape_steps = _sealed_steps("failure-output-shape", replay.output_shape, roots)
    steps.extend(shape_steps)
    final = _step(
        "crack-width-failed-result",
        "Crack-width replay failure",
        0.0,
        ONE,
        ROLE_FINAL,
        BOUNDARY,
        (*roots, *shape_steps),
        expression="Publish calculation-free failure state",
        result=TraceResult(
            RESULT_FAILED,
            None,
            "The authoritative elastic/crack reconstruction did not converge; no crack width or verdict is published.",
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
            "Failure-only candidate numerical values are not traversed.",
            "No resistance, utilisation, crack-width value, or engineering verdict is implied.",
        ),
    )
    return _shape("failed", calculation, FAILURE_STATES), calculation


def _expected_bundle(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any] | None,
) -> TraceBundle | None:
    inp = _mapping(inp, "CT-009 input")
    out = _mapping(out, "analysis result")
    trace_context = {} if context is None else _mapping(context, "CT-009 context")
    if not _validate_dispatch(inp):
        return None
    if _required(inp, "section") is None:
        return None
    replay = _replay(inp, out)
    if isinstance(replay, FailureReplay):
        shape, calculation = _failure_member(replay, trace_context)
        bundle = create_bundle(
            input_sha256=input_sha256,
            result_sha256=result_sha256,
            calculations=(calculation,),
        )
        return audit_trace_registry(bundle, registry_for((shape,)))

    pairs = tuple(_case_member(replay, case, trace_context) for case in replay.cases)
    case_shapes = tuple(item[0] for item in pairs)
    calculations = tuple(item[1] for item in pairs)
    aggregate_shape, aggregate = _aggregate_member(
        replay, calculations, trace_context
    )
    shapes = (*case_shapes, aggregate_shape)
    bundle = create_bundle(
        input_sha256=input_sha256,
        result_sha256=result_sha256,
        calculations=(*calculations, aggregate),
        warnings=(CRACK_DIRECTIONAL_LIMITATION,),
    )
    return audit_trace_registry(bundle, registry_for(shapes))


def build_crack_trace_family(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle | None:
    """Build the selected base crack trace, or ``None`` when it is inactive."""

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
    """Validate exact current-input reconstruction, graph, sources, and seal."""

    expected = _expected_bundle(
        inp,
        out,
        input_sha256=input_sha256,
        result_sha256=result_sha256,
        context=context,
    )
    if expected is None:
        if bundle is not None:
            raise TraceValidationError(
                "inactive CT-009 selector cannot retain a crack trace"
            )
        return None
    if bundle is None:
        raise TraceValidationError("active CT-009 result requires a crack trace")
    candidate = validate_bundle(
        bundle,
        expected_input_sha256=input_sha256,
        expected_result_sha256=result_sha256,
    )
    if candidate != expected:
        raise TraceValidationError(
            "CT-009 trace differs from independent current-input reconstruction"
        )
    return candidate


__all__ = (
    "build_crack_trace_family",
    "validate_crack_trace_family",
)
