"""Independent CT-009 replay for the retained 2004 crack-width routes."""

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
    COVERAGE_ID,
    CRACK_ROUTES,
    CRACK_WIDTH,
    CrackRoute,
    DK_CRACK_WIDTH_COARSE,
    DK_EFFECTIVE_AREA_COARSE,
    DK_EFFECTIVE_AREA_FINE,
    DK_SPACING_CLOSE,
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
    METRE,
    MILLIMETRE,
    ONE,
    SELECTION,
    SPACING_CLOSE,
    SPACING_WIDE,
    SQUARE_METRE,
    SQUARE_MILLIMETRE,
    UNDEFINED_STATES,
    MemberShape,
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
_NON_OWNED_ELASTIC_KEYS = (
    "total",
    "long",
    "dif",
    "rst1",
    "max_conc",
    "max_conc_xy",
    "max_conc_point",
    "na_x",
    "na_y",
    "max_steel",
    "max_steel_bar",
    "max_steel_type",
    "max_steel_element",
    "prestress",
    "stress_plane",
    "elements",
    "concrete_corners",
    "stress_outputs",
)
_PROPERTY_NAMES = ("area", "cx", "cy", "Ix", "Iy", "Ixy")
_BASE_CASES = (
    ("long-term", "crack", 0.4, False),
    ("short-term", "crack_short", 0.6, False),
)
_DK_CASES = (
    ("long-term-fine", "crack", 0.4, False),
    ("short-term-fine", "crack_short", 0.6, False),
    ("long-term-coarse", "crack_coarse", 0.4, True),
    ("short-term-coarse", "crack_short_coarse", 0.6, True),
)


@dataclass(frozen=True, slots=True)
class _CaseReplay:
    name: str
    output_key: str
    kt: float
    coarse: bool
    modular_ratio: float
    evaluation: CrackWidthEvaluation
    state: Any | None
    output: Mapping[str, Any] | None


@dataclass(frozen=True, slots=True)
class _SuccessfulReplay:
    route: CrackRoute
    inputs: tuple[tuple[str, Any], ...]
    sibling_shape: Any
    retained: Mapping[str, Any]
    blocks: SectionTraceBlocks
    cases: tuple[_CaseReplay, ...]
    cracked: bool
    cracking_factor: float
    tension_stress: float
    uncracked_properties: Any
    cracked_properties: Any | None


@dataclass(frozen=True, slots=True)
class _FailedReplay:
    route: CrackRoute
    inputs: tuple[tuple[str, Any], ...]
    output_shape: Any


def _mapping(value: Any, label: str, *, exact: bool = False) -> Mapping[str, Any]:
    valid = type(value) is dict if exact else isinstance(value, Mapping)
    if not valid:
        noun = "an exact dict" if exact else "a mapping"
        raise TraceValidationError(f"{label} must be {noun}")
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


def _number(value: Any, label: str, *, positive: bool = False) -> float:
    if type(value) not in {int, float} or type(value) is bool:
        raise TraceValidationError(f"{label} must be a finite non-Boolean number")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0.0):
        requirement = "positive finite" if positive else "finite"
        raise TraceValidationError(f"{label} must be {requirement}")
    return result


def _same_float(actual: Any, expected: Any, label: str) -> None:
    left = _number(actual, label)
    right = _number(expected, f"{label} reference")
    if left.hex() != right.hex():
        raise TraceValidationError(f"{label} is stale relative to its source")


def _freeze(value: Any, active: set[int] | None = None) -> Any:
    """Return an exact JSON-safe type/order/cardinality/value identity."""

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
        return ["numpy-scalar", value.dtype.str, _freeze(value.item(), active)]

    identity = id(value)
    if identity in active:
        raise TraceValidationError("cyclic CT-009 identity is unsupported")
    active.add(identity)
    try:
        if isinstance(value, np.ndarray):
            payload = (
                [_freeze(item, active) for item in value.flat]
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
                    [field.name, _freeze(getattr(value, field.name), active)]
                    for field in dataclasses.fields(value)
                ],
            ]
        if isinstance(value, Mapping):
            return [
                "mapping",
                value.__class__.__module__,
                value.__class__.__qualname__,
                [
                    [_freeze(key, active), _freeze(item, active)]
                    for key, item in value.items()
                ],
            ]
        if type(value) in {list, tuple}:
            return [type(value).__name__, [_freeze(item, active) for item in value]]
        if hasattr(value, "__dict__"):
            return [
                "object",
                value.__class__.__module__,
                value.__class__.__qualname__,
                _freeze(vars(value), active),
            ]
        slots = getattr(value.__class__, "__slots__", ())
        if slots:
            names = (slots,) if type(slots) is str else tuple(slots)
            return [
                "slots",
                value.__class__.__module__,
                value.__class__.__qualname__,
                [
                    [name, _freeze(getattr(value, name), active)]
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


def _type_tree(value: Any, active: set[int] | None = None) -> Any:
    """Retain recursive keys/order/cardinality/types without sibling values."""

    if active is None:
        active = set()
    if not isinstance(value, (Mapping, Sequence, np.ndarray)) or isinstance(
        value, (str, bytes)
    ):
        return ["leaf", type(value).__module__, type(value).__qualname__]

    identity = id(value)
    if identity in active:
        raise TraceValidationError("cyclic CT-009 output structure is unsupported")
    active.add(identity)
    try:
        if isinstance(value, Mapping):
            return [
                "mapping",
                type(value).__module__,
                type(value).__qualname__,
                [
                    [_freeze(key), _type_tree(item, active)]
                    for key, item in value.items()
                ],
            ]
        if isinstance(value, np.ndarray):
            return ["ndarray", value.dtype.str, list(value.shape)]
        return [
            "sequence",
            type(value).__module__,
            type(value).__qualname__,
            [_type_tree(item, active) for item in value],
        ]
    finally:
        active.remove(identity)


def _assert_exact(actual: Any, expected: Any, label: str) -> None:
    if _freeze(actual) != _freeze(expected):
        raise TraceValidationError(
            f"{label} differs in value, type, order, or cardinality from replay"
        )


def _digest(value: Any) -> tuple[float, ...]:
    payload = json.dumps(
        _freeze(value),
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    raw = hashlib.sha256(payload).digest()
    return tuple(
        float(int.from_bytes(raw[index:index + 4], "big"))
        for index in range(0, 32, 4)
    )


def _active_route(inp: Mapping[str, Any]) -> CrackRoute | None:
    mode = _required(inp, "mode")
    enabled = _required(inp, "sls_cw")
    if type(mode) is not str:
        raise TraceValidationError("mode must retain text type")
    if type(enabled) is not bool:
        raise TraceValidationError("sls_cw must retain Boolean type")
    if mode not in _MODES or not enabled:
        return None

    code = _required(inp, "sls_code")
    edition = _required(inp, "sls_edition")
    dk_na = _required(inp, "sls_dk_na")
    if type(code) is not str or type(edition) is not str:
        raise TraceValidationError("sls_code and sls_edition must retain text type")
    if type(dk_na) is not bool:
        raise TraceValidationError("sls_dk_na must retain Boolean type")
    if edition != EDITION:
        return None
    route = next(
        (
            item
            for item in CRACK_ROUTES
            if (code, dk_na) == (item.code, item.dk_na)
        ),
        None,
    )
    if route is None:
        return None

    if "sls_crack_limit" in inp:
        raise TraceValidationError("removed sls_crack_limit cannot enter CT-009")
    member = _required(inp, "sls_member")
    if type(member) is not str:
        raise TraceValidationError("sls_member must retain text type")
    if route.dk_na and member not in {"Beam", "Slab"}:
        raise TraceValidationError("DK crack member must be Beam or Slab")
    tendon_xi = _required(inp, "sls_tendon_xi")
    if type(tendon_xi) not in {int, float} or type(tendon_xi) is bool:
        raise TraceValidationError("sls_tendon_xi must retain built-in numeric type")
    return route


def _validate_rings(inp: Mapping[str, Any], blocks: SectionTraceBlocks) -> None:
    raw_holes = _sequence(_required(inp, "holes"), "holes")
    raw_rings = (
        _sequence(_required(inp, "outer"), "outer"),
        *(_sequence(hole, "hole") for hole in raw_holes),
    )
    if len(raw_rings) != len(blocks.geometry.rings):
        raise TraceValidationError("polygon ring count differs from Section")
    for ring_no, (raw_ring, resolved_ring) in enumerate(
        zip(raw_rings, blocks.geometry.rings), start=1
    ):
        if len(raw_ring) != len(resolved_ring):
            raise TraceValidationError(f"polygon ring {ring_no} cardinality differs")
        for point_no, (raw_point, resolved_point) in enumerate(
            zip(raw_ring, resolved_ring), start=1
        ):
            point = _sequence(raw_point, f"ring {ring_no} point {point_no}")
            if len(point) != 2:
                raise TraceValidationError("polygon point requires x and y")
            _same_float(point[0], resolved_point[0], "polygon x")
            _same_float(point[1], resolved_point[1], "polygon y")


def _validate_elements(inp: Mapping[str, Any], blocks: SectionTraceBlocks) -> None:
    families = (
        ("bar", "bars", "bar_elements", blocks.geometry.bars, blocks.bars),
        (
            "tendon",
            "tendons",
            "tendon_elements",
            blocks.geometry.tendons,
            blocks.tendons,
        ),
    )
    for kind, tuple_key, record_key, geometry, materials in families:
        tuples = _sequence(_required(inp, tuple_key), tuple_key)
        records = _sequence(_required(inp, record_key), record_key)
        if len(tuples) != len(geometry) or len(records) != len(geometry):
            raise TraceValidationError(f"{kind} representations must align")
        for position, (raw_value, raw_record, resolved, material) in enumerate(
            zip(tuples, records, geometry, materials)
        ):
            label = f"{record_key}[{position}]"
            raw = _sequence(raw_value, f"{tuple_key}[{position}]")
            record = _mapping(raw_record, label, exact=True)
            if len(raw) != 3:
                raise TraceValidationError(f"{tuple_key}[{position}] needs x, y, area")
            if tuple(record) != _ELEMENT_KEYS:
                raise TraceValidationError(f"{label} must use exact current schema")
            if type(record["kind"]) is not str or record["kind"] != kind:
                raise TraceValidationError(f"{label} kind is invalid")
            if type(record["id"]) is not str or record["id"] != material.element_id:
                raise TraceValidationError(f"{label} element ID is stale")
            if (
                type(record["material_id"]) is not str
                or record["material_id"] != material.material_id
            ):
                raise TraceValidationError(f"{label} material ID is stale")
            if type(record["fatigue_detail_id"]) is not str:
                raise TraceValidationError("fatigue_detail_id must retain text type")
            size_mode = record["size_mode"]
            if type(size_mode) is not str or size_mode not in _SIZE_MODES:
                raise TraceValidationError(f"{label} size_mode is invalid")

            area = _number(record["area_mm2"], f"{label} area_mm2", positive=True)
            diameter = _number(
                record["diameter_mm"], f"{label} diameter_mm", positive=True
            )
            checks = (
                (raw[0], resolved.x, "raw x"),
                (raw[1], resolved.y, "raw y"),
                (raw[2], area, "raw area"),
                (record["x"], resolved.x, "record x"),
                (record["y"], resolved.y, "record y"),
                (record["x"], _number(record["x_mm"], "x_mm") / 1000.0,
                 "record x/x_mm"),
                (record["y"], _number(record["y_mm"], "y_mm") / 1000.0,
                 "record y/y_mm"),
                (resolved.area, area * 1.0e-6, "resolved area"),
            )
            for actual, expected, suffix in checks:
                _same_float(actual, expected, f"{label} {suffix}")
            if size_mode == "Area":
                _same_float(
                    diameter,
                    math.sqrt(4.0 * area / math.pi),
                    f"{label} area-derived diameter",
                )
            elif size_mode == "Diameter":
                _same_float(
                    area,
                    math.pi * diameter * diameter / 4.0,
                    f"{label} diameter-derived area",
                )


def _assignment_identity(inp: Mapping[str, Any], key: str) -> Any:
    original = _required(inp, key)
    sealed = []
    for position, raw in enumerate(_sequence(original, key)):
        record = _mapping(raw, f"{key}[{position}]", exact=True)
        if tuple(record) != _ELEMENT_KEYS:
            raise TraceValidationError(f"{key}[{position}] must use current schema")
        sealed.append(tuple(
            (
                name,
                ("inert-type", type(value).__module__, type(value).__qualname__),
            )
            if name == "fatigue_detail_id"
            else (name, value)
            for name, value in record.items()
        ))
    return (
        type(original).__module__,
        type(original).__qualname__,
        tuple(sealed),
    )


def _input_identity(
    inp: Mapping[str, Any], blocks: SectionTraceBlocks, route: CrackRoute
) -> tuple[tuple[str, Any], ...]:
    geometry = tuple(
        (key, _required(inp, key))
        for key in ("section", "outer", "holes", "bars", "tendons")
    ) + (("resolved", blocks.geometry),)
    concrete_id = _required(inp, "concrete_material_id")
    if (
        type(concrete_id) is not str
        or not concrete_id
        or concrete_id != concrete_id.strip()
        or concrete_id != blocks.concrete.material_id
    ):
        raise TraceValidationError(
            "concrete_material_id must be the exact selected non-blank identity"
        )
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
    ) + (
        ("concrete_material_id", concrete_id),
        ("resolved-concrete", blocks.concrete),
        ("resolved-bars", blocks.bars),
        ("resolved-tendons", blocks.tendons),
    )
    assignments = (
        ("bar_elements", _assignment_identity(inp, "bar_elements")),
        ("tendon_elements", _assignment_identity(inp, "tendon_elements")),
    )
    inert = frozenset(
        {"sls_tendon_xi"}
        | ({"sls_member"} if not route.dk_na else set())
    )
    controls = []
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
        if key in inert:
            value = ("inert-type", type(value).__module__, type(value).__qualname__)
        controls.append((key, value))
    return (
        ("geometry", geometry),
        ("materials", materials),
        ("assignments", assignments),
        ("controls", tuple(controls)),
    )


def _numeric_inputs(inp: Mapping[str, Any]) -> dict[str, float]:
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
    expected_ns = REFERENCE_ES / (values["conc_Ec"] * 1000.0)
    expected_nl = expected_ns * (1.0 + values["el_phi"])
    for key, expected in (("ns", expected_ns), ("nl", expected_nl)):
        if not math.isclose(values[key], expected, rel_tol=1.0e-12, abs_tol=0.0):
            raise TraceValidationError(f"{key} is stale relative to Ec and creep")
    return values


def _material_value(material: Any, key: str, *, positive: bool = False) -> float:
    values = dict(material.values)
    if key not in values:
        raise TraceValidationError(f"{material.kind} material lacks {key}")
    return _number(values[key], f"{material.kind} {key}", positive=positive)


def _elastic_section(blocks: SectionTraceBlocks) -> Section:
    return Section(
        [np.asarray(ring, dtype=float) for ring in blocks.geometry.rings],
        bars=[
            Bar(item.x, item.y, item.area)
            for item in (*blocks.geometry.bars, *blocks.geometry.tendons)
        ],
    )


def _finite_solver(result: Any) -> bool:
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
            bool(np.all(np.isfinite(np.asarray(item, dtype=float))))
            for item in retained
        )
    except (TypeError, ValueError):
        return False


def _element_label(
    blocks: SectionTraceBlocks, index: int
) -> tuple[str, int, str]:
    if index < len(blocks.bars):
        return "Bar", index + 1, blocks.bars[index].element_id
    tendon = index - len(blocks.bars)
    if tendon < 0 or tendon >= len(blocks.tendons):
        raise TraceValidationError("crack result selected an unknown element")
    return "Tendon", tendon + 1, blocks.tendons[tendon].element_id


def _candidate_payload(candidate: Any, blocks: SectionTraceBlocks) -> dict[str, Any]:
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


def _result_payload(result: Any, blocks: SectionTraceBlocks) -> dict[str, Any] | None:
    if result is None:
        return None
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
        "candidates": [
            _candidate_payload(candidate, blocks)
            for candidate in result.candidates
        ],
    }


def _property_payload(properties: Any) -> dict[str, float]:
    return {name: float(getattr(properties, name)) for name in _PROPERTY_NAMES}


def _elastic_candidate(out: Mapping[str, Any]) -> Mapping[str, Any]:
    if "elastic" not in out:
        raise TraceValidationError("active CT-009 input requires elastic output")
    return _mapping(out["elastic"], "elastic output", exact=True)


def _is_owned(key: str) -> bool:
    stems = ("cracked", "lambda_cr", "sigma_ct", "fctm", "show_cw", "props_")
    return (
        key == "converged"
        or key in {"sls_limit_source", "wk_limit", "crack_limit_source"}
        or key.startswith("sls_crack_")
        or key.startswith("crack")
        or any(key == stem or key.startswith(stem) for stem in stems)
    )


def _sibling_shape(out: Mapping[str, Any], candidate: Mapping[str, Any]) -> Any:
    non_owned = tuple((key, value) for key, value in candidate.items() if not _is_owned(key))
    if tuple(key for key, _value in non_owned) != _NON_OWNED_ELASTIC_KEYS:
        raise TraceValidationError(
            "CT-009 non-owned elastic sibling inventory/order differs from current output"
        )
    projected = []
    for key, value in out.items():
        projected.append(
            (key, non_owned) if key == "elastic" else (key, value)
        )
    return _type_tree(tuple(projected))


def _validate_success(
    candidate: Mapping[str, Any], expected: Mapping[str, Any]
) -> None:
    owned = tuple(key for key in candidate if _is_owned(key))
    if owned != tuple(expected):
        raise TraceValidationError("CT-009 success output inventory/order differs")
    for key, value in expected.items():
        _assert_exact(candidate[key], value, f"elastic.{key}")


def _validate_failure(
    out: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    cracked: bool,
    route: CrackRoute,
) -> Any:
    owned = tuple(key for key in candidate if _is_owned(key))
    expected = (
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
            (
                "crack_code",
                "crack_edition",
                "crack_member",
                *(("crack_coarse", "crack_short_coarse") if route.dk_na else ()),
            )
            if cracked
            else ()
        ),
        "crack_output",
    )
    if owned != expected:
        raise TraceValidationError("failed CT-009 crack-owned inventory/order differs")
    _sibling_shape(out, candidate)
    if candidate["converged"] is not False:
        raise TraceValidationError("failed CT-009 output requires converged is False")
    _assert_exact(
        candidate["crack_output"],
        {
            "value": None,
            "case": None,
            "governing": None,
            "unit": "mm",
            "calculation_state": "INVALID",
        },
        "failed crack_output",
    )
    return _type_tree(out)


def _reconstruct(
    inp: Mapping[str, Any], out: Mapping[str, Any], route: CrackRoute
) -> _SuccessfulReplay | _FailedReplay:
    values = _numeric_inputs(inp)
    try:
        blocks = section_trace_blocks(inp)
        _validate_rings(inp, blocks)
        _validate_elements(inp, blocks)
        section = _elastic_section(blocks)
    except TraceValidationError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"invalid CT-009 section identity: {exc}") from exc

    identity = _input_identity(inp, blocks, route)
    materials = (*blocks.bars, *blocks.tendons)
    moduli = np.asarray(
        [_material_value(item, "Es", positive=True) for item in materials],
        dtype=float,
    )
    multipliers = moduli / REFERENCE_ES
    locked_stress = None
    if blocks.tendons:
        locked_stress = np.asarray(
            [0.0] * len(blocks.bars)
            + [
                _material_value(item, "Es", positive=True)
                * _material_value(item, "IS")
                * 1000.0
                for item in blocks.tendons
            ],
            dtype=float,
        )

    long_force = -values["P_el_l"]
    short_force = -values["P_el_s"]
    combined = solve_elastic_combined(
        section,
        long_force,
        values["Mx_el_l"],
        values["My_el_l"],
        values["nl"],
        short_force,
        values["Mx_el_s"],
        values["My_el_s"],
        values["ns"],
        n_mult=multipliers,
        prestress_stress=locked_stress,
    )
    records = (
        *_sequence(_required(inp, "bar_elements"), "bar_elements"),
        *_sequence(_required(inp, "tendon_elements"), "tendon_elements"),
    )
    diameter: float | list[float] = values["sls_phi"]
    if diameter == 0.0:
        diameter = [
            _number(
                _mapping(item, "element record", exact=True)["diameter_mm"],
                "diameter_mm",
                positive=True,
            )
            for item in records
        ]
    k1 = [values["sls_k1"]] * len(blocks.bars) + [1.6] * len(blocks.tendons)
    include_hx = (
        not route.dk_na
        or _required(inp, "sls_member") == "Slab"
        or bool(blocks.tendons)
    )
    sustained = analyse_cracking(
        section,
        long_force,
        values["Mx_el_l"],
        values["My_el_l"],
        values["nl"],
        fctm=values["sls_fctm"],
        Es=moduli,
        beta=0.5,
        kt=0.4,
        bar_diameter=diameter,
        k1=k1,
        k3_cover_dependent=route.dk_na,
        include_hx_term=include_hx,
        edition=EDITION,
        n_mult=multipliers,
        prestress_stress=locked_stress,
    )
    peak_cracked, peak_factor, peak_tension = combined_cracking(
        section,
        long_force,
        values["Mx_el_l"],
        values["My_el_l"],
        values["nl"],
        short_force,
        values["Mx_el_s"],
        values["My_el_s"],
        values["ns"],
        fctm=values["sls_fctm"],
        n_mult=multipliers,
        prestress_stress=locked_stress,
    )
    if peak_factor < sustained.lambda_cr:
        cracked = bool(peak_cracked)
        cracking_factor = float(peak_factor)
        tension_stress = float(peak_tension)
        property_state = combined.short_term
    else:
        cracked = bool(sustained.cracked)
        cracking_factor = float(sustained.lambda_cr)
        tension_stress = float(sustained.sigma_ct)
        property_state = sustained.cracked_state

    candidate = _elastic_candidate(out)
    converged = (
        _finite_solver(combined)
        and bool(sustained.uncracked.converged)
        and bool(sustained.cracked_state.converged)
    )
    if not converged:
        return _FailedReplay(
            route,
            identity,
            _validate_failure(
                out,
                candidate,
                cracked=cracked,
                route=route,
            ),
        )

    uncracked_properties = transformed_properties(
        section, values["nl"], cracked=False, n_mult=multipliers
    )
    cracked_properties = (
        transformed_properties(
            section,
            values["nl"],
            eps0=property_state.eps0,
            kx=property_state.kx,
            ky=property_state.ky,
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
            sustained.cracked_state,
            dataclasses.replace(combined.short_term, bar_stress=short_stress),
        )
        reinforcement_types = (
            ["mild"] * len(blocks.bars)
            + ["prestress"] * len(blocks.tendons)
        )
        case_specs = _DK_CASES if route.dk_na else _BASE_CASES
        evaluations = tuple(
            evaluate_crack_width(
                section,
                states[0 if name.startswith("long-term") else 1],
                values["nl" if name.startswith("long-term") else "ns"],
                fctm=values["sls_fctm"],
                Es=moduli,
                kt=kt,
                bar_diameter=diameter,
                k1=k1,
                k3_cover_dependent=route.dk_na,
                include_hx_term=include_hx,
                coarse=coarse,
                edition=EDITION,
                n_mult=multipliers,
                reinforcement_types=reinforcement_types,
                bond_ratio_xi=None,
            )
            for name, _key, kt, coarse in case_specs
        )
    else:
        case_specs = _DK_CASES if route.dk_na else _BASE_CASES
        evaluations = tuple(
            CrackWidthEvaluation("NOT APPLICABLE", "The section is uncracked.")
            for _item in case_specs
        )

    cases = tuple(
        _CaseReplay(
            name=name,
            output_key=key,
            kt=kt,
            coarse=coarse,
            modular_ratio=values[
                "nl" if name.startswith("long-term") else "ns"
            ],
            evaluation=evaluation,
            state=(
                None
                if not cracked
                else states[0 if name.startswith("long-term") else 1]
            ),
            output=_result_payload(evaluation.result, blocks),
        )
        for (name, key, kt, coarse), evaluation in zip(
            case_specs,
            evaluations,
        )
    )
    expected: dict[str, Any] = {
        "converged": True,
        "cracked": cracked,
        "lambda_cr": cracking_factor,
        "sigma_ct": tension_stress,
        "fctm": values["sls_fctm"],
        "show_cw": True,
        "props_un": _property_payload(uncracked_properties),
        "props_cr": (
            None
            if cracked_properties is None
            else _property_payload(cracked_properties)
        ),
        "crack": cases[0].output,
        "crack_short": cases[1].output,
    }
    if cracked:
        expected.update(
            crack_code=route.code,
            crack_edition=EDITION,
            crack_member=(
                _required(inp, "sls_member") if route.dk_na else None
            ),
        )
        if route.dk_na:
            expected.update(
                crack_coarse=cases[2].output,
                crack_short_coarse=cases[3].output,
            )
    labels = (
        (
            "Long-term (fine)",
            "Short-term (fine)",
            "Long-term (coarse)",
            "Short-term (coarse)",
        )
        if route.dk_na
        else ("Long-term", "Short-term")
    )
    expected["crack_output"] = crack_outputs(
        {label: case.output for label, case in zip(labels, cases)},
        valid=True,
    )
    sibling_shape = _sibling_shape(out, candidate)
    _validate_success(candidate, expected)
    return _SuccessfulReplay(
        route=route,
        inputs=identity,
        sibling_shape=sibling_shape,
        retained=expected,
        blocks=blocks,
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
    expression: str = "Independent reconstruction",
    result: TraceResult | None = None,
) -> TraceStep:
    number = _trace_number(value, f"{step_id} value")
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
    prefix: str,
) -> list[TraceStep]:
    steps = []
    for name, payload in groups:
        token = trace_identity_token(name)
        for position, word in enumerate(_digest(payload), start=1):
            steps.append(_step(
                f"{prefix}-{token}-sha256-{position}",
                f"Sealed {name} identity word {position}",
                word,
                ONE,
                role,
                source,
                dependencies,
                expression="SHA-256 word over retained exact identity",
            ))
    return steps


def _route_steps(
    route: CrackRoute,
    dependencies: Sequence[TraceStep],
) -> list[TraceStep]:
    if route.route_id == "building-base":
        return []
    controls_prefix = f"input-{trace_identity_token('controls')}-sha256-"
    selector_dependencies = tuple(
        step
        for step in dependencies
        if step.step_id.startswith(controls_prefix)
    )
    if not selector_dependencies:
        raise TraceValidationError(
            "CT-009 route binding requires the sealed selector controls"
        )
    return [
        _step(
            f"method-route-{position}",
            f"Selected standards route {position}",
            1.0,
            ONE,
            ROLE_COMPUTED,
            source,
            selector_dependencies,
            expression=f"Exact selected route: {route.code}",
        )
        for position, source in enumerate(route.route_sources, start=1)
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
            (
                item.step_id,
                item.quantity_role,
                item.source,
                tuple(dependency.step_id for dependency in item.dependencies),
            )
            for item in calculation.steps
        ),
        states=states,
    )


def _candidate_steps(
    candidate: Any,
    position: int,
    dependencies: Sequence[TraceStep],
    route: CrackRoute,
) -> tuple[list[TraceStep], TraceStep]:
    prefix = f"candidate-{position:04d}"
    effective_area_source = (
        DK_EFFECTIVE_AREA_COARSE
        if candidate.coarse
        else DK_EFFECTIVE_AREA_FINE
        if route.dk_na
        else EFFECTIVE_AREA
    )
    spacing_source = (
        SPACING_WIDE
        if candidate.sr_max_geometric
        else DK_SPACING_CLOSE
        if route.dk_na
        else SPACING_CLOSE
    )
    width_source = DK_CRACK_WIDTH_COARSE if candidate.coarse else CRACK_WIDTH
    quantities = (
        ("position", candidate.bar_index + 1, ONE, SELECTION),
        ("x", candidate.x, METRE, GEOMETRY),
        ("y", candidate.y, METRE, GEOMETRY),
        ("area", candidate.area, SQUARE_MILLIMETRE, GEOMETRY),
        ("sigma-s", candidate.sigma_s, MEGAPASCAL, ELASTIC),
        ("hc-eff", candidate.hc_ef, METRE, effective_area_source),
        ("ac-eff", candidate.ac_eff, SQUARE_METRE, effective_area_source),
        ("as-eff", candidate.as_eff, SQUARE_METRE, effective_area_source),
        ("ap-eff", candidate.ap_eff, SQUARE_METRE, effective_area_source),
        (
            "ap-eff-weighted",
            candidate.ap_eff_weighted,
            SQUARE_METRE,
            effective_area_source,
        ),
        ("rho-p-eff", candidate.rho_p_eff, ONE, effective_area_source),
        ("phi", candidate.phi, MILLIMETRE, GEOMETRY),
        ("cover", candidate.cover, MILLIMETRE, GEOMETRY),
        ("esm-ecm", candidate.esm_ecm, ONE, MEAN_STRAIN),
        (
            "sr-max",
            candidate.sr_max,
            MILLIMETRE,
            spacing_source,
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
    if route.route_id != "building-base" and not candidate.sr_max_geometric:
        k3 = (
            3.4 * (25.0 / candidate.cover) ** (2.0 / 3.0)
            if route.dk_na and candidate.cover > 0.0
            else 3.4
        )
        steps.append(_step(
            f"{prefix}-spacing-cover-coefficient",
            "Crack spacing cover coefficient",
            k3,
            ONE,
            ROLE_METHOD_VALUE,
            spacing_source,
            expression=(
                "k3 = 3.4(25/c)^(2/3)"
                if route.dk_na and candidate.cover > 0.0
                else "k3 = 3.4"
            ),
        ))
    categorical = (
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
    steps.extend(_identity_steps(
        ((f"{prefix}-categorical", categorical),),
        source=BOUNDARY,
        role=ROLE_COMPUTED,
        dependencies=(*dependencies, *steps),
        prefix=prefix,
    ))
    width = _step(
        f"{prefix}-wk",
        "Candidate characteristic crack width",
        candidate.wk,
        MILLIMETRE,
        ROLE_COMPUTED,
        width_source,
        steps,
        expression=(
            "w_k = 0.5 * s_r,max * (epsilon_sm - epsilon_cm)"
            if candidate.coarse
            else "w_k = s_r,max * (epsilon_sm - epsilon_cm)"
        ),
    )
    steps.append(width)
    return steps, width


def _case_member(
    replay: _SuccessfulReplay,
    case: _CaseReplay,
    context: Mapping[str, Any],
) -> tuple[MemberShape, TraceCalculation]:
    steps = _identity_steps(
        replay.inputs,
        source=INPUT,
        role=ROLE_USER_INPUT,
        prefix="input",
    )
    input_roots = tuple(steps)
    route_steps = _route_steps(replay.route, input_roots)
    steps.extend(route_steps)
    boundary_steps = _identity_steps(
        (
            (f"{case.name}-retained-output", case.output),
            ("successful-sibling-structure", replay.sibling_shape),
        ),
        source=BOUNDARY,
        role=ROLE_COMPUTED,
        dependencies=(*input_roots, *route_steps),
        prefix="output",
    )
    steps.extend(boundary_steps)
    controls = dict(dict(replay.inputs)["controls"])
    suffix = "l" if case.name.startswith("long-term") else "s"
    actions = [
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
    methods = [
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
    if replay.route.route_id != "building-base":
        methods.append(_step(
            "case-crack-system-factor",
            "Crack system width factor",
            0.5 if case.coarse else 1.0,
            ONE,
            ROLE_METHOD_VALUE,
            DK_CRACK_WIDTH_COARSE if case.coarse else CRACK_WIDTH,
            expression=(
                "DK coarse system factor"
                if case.coarse
                else "Fine crack system factor"
            ),
        ))
    if replay.route.dk_na and not case.coarse:
        include_hx = (
            controls["sls_member"] == "Slab" or bool(replay.blocks.tendons)
        )
        methods.append(_step(
            "case-include-hx-term",
            "Fine-system effective-height member rule",
            1.0 if include_hx else 0.0,
            ONE,
            ROLE_METHOD_VALUE,
            DK_EFFECTIVE_AREA_FINE,
            expression=(
                "Include (h-x)/3 for slab or prestressed member"
                if include_hx
                else "Omit (h-x)/3 for ordinary beam"
            ),
        ))
    steps.extend(actions)
    steps.extend(methods)
    roots = (
        *input_roots,
        *route_steps,
        *boundary_steps,
        *actions,
        *methods,
    )

    planes: list[TraceStep] = []
    stresses: list[TraceStep] = []
    if case.state is not None:
        planes = [
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
        steps.extend(planes)
        stresses = [
            _step(
                f"element-{position:04d}-stress",
                f"Element {position} stress",
                float(value) / 1000.0,
                MEGAPASCAL,
                ROLE_COMPUTED,
                ELASTIC,
                planes,
            )
            for position, value in enumerate(
                np.asarray(case.state.bar_stress, dtype=float), start=1
            )
        ]
        steps.extend(stresses)

    mechanics_roots = (*roots, *planes, *stresses)
    if case.evaluation.result is None:
        final = _step(
            "crack-width-result",
            "Characteristic crack width",
            0.0,
            MILLIMETRE,
            ROLE_FINAL,
            SELECTION,
            mechanics_roots,
            expression="Publish explicit undefined disposition",
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
        for position, candidate in enumerate(case.evaluation.result.candidates, start=1):
            created, candidate_final = _candidate_steps(
                candidate,
                position,
                mechanics_roots,
                replay.route,
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
            expression="Select largest independently reconstructed candidate",
        )
        states = FINITE_STATES
        branch = "calculated"
    steps.append(final)
    axes_values = dict(
        crack_branch=branch,
        crack_case=case.name,
        crack_code=trace_identity_token(replay.route.code),
        crack_direction="dominant-strain-gradient",
        crack_edition=EDITION,
        crack_system="coarse" if case.coarse else "fine",
    )
    if replay.route.route_id != "building-base":
        axes_values["crack_route"] = replay.route.route_id
    axes = context_axes(context, **axes_values)
    calculation_id = (
        f"ct-009-{context_id(context)}-{case.name}-base-crack-width"
        if replay.route.route_id == "building-base"
        else (
            f"ct-009-{context_id(context)}-{case.name}-"
            f"{replay.route.route_id}-crack-width"
        )
    )
    calculation = TraceCalculation(
        calculation_id=calculation_id,
        coverage_id=COVERAGE_ID,
        title=(
            f"EN 1992-1-1:2004 {case.name} crack width"
            if replay.route.route_id == "building-base"
            else f"{replay.route.title} {case.name} crack width"
        ),
        method_id=replay.route.method_id,
        axes=axes,
        final_step_id=final.step_id,
        steps=tuple(steps),
        warnings=(CRACK_DIRECTIONAL_LIMITATION,),
        assumptions=(
            (
                "No crack limit, utilisation, verdict, DK rule, or bridge rule "
                "is inferred."
                if replay.route.route_id == "building-base"
                else "No crack limit, utilisation, resistance, or verdict is inferred."
            ),
        ),
    )
    return _shape(case.name, calculation, states), calculation


def _aggregate_member(
    replay: _SuccessfulReplay,
    cases: tuple[TraceCalculation, ...],
    context: Mapping[str, Any],
) -> tuple[MemberShape, TraceCalculation]:
    steps = _identity_steps(
        replay.inputs,
        source=INPUT,
        role=ROLE_USER_INPUT,
        prefix="input",
    )
    inputs = tuple(steps)
    route_steps = _route_steps(replay.route, inputs)
    steps.extend(route_steps)
    boundary = _identity_steps(
        (
            ("retained-output", replay.retained),
            ("successful-sibling-structure", replay.sibling_shape),
        ),
        source=BOUNDARY,
        role=ROLE_COMPUTED,
        dependencies=(*inputs, *route_steps),
        prefix="output",
    )
    steps.extend(boundary)
    roots = (*inputs, *route_steps, *boundary)
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
    properties = []
    for prefix, values in (
        ("uncracked", replay.uncracked_properties),
        ("cracked", replay.cracked_properties),
    ):
        if values is None:
            continue
        for name in _PROPERTY_NAMES:
            unit = (
                SQUARE_METRE
                if name == "area"
                else METRE
                if name in {"cx", "cy"}
                else FOURTH_METRE
            )
            properties.append(_step(
                f"{prefix}-property-{name.lower()}",
                f"{prefix} property {name}",
                getattr(values, name),
                unit,
                ROLE_COMPUTED,
                ELASTIC,
                (*roots, *state_steps),
            ))
    steps.extend(properties)
    case_steps = []
    for position, calculation in enumerate(cases, start=1):
        result = next(
            item.result
            for item in calculation.steps
            if item.step_id == calculation.final_step_id
        )
        case_steps.append(_step(
            f"case-{position}-final",
            f"Ordered case {position} disposition",
            result.value if result.value is not None else 0.0,
            MILLIMETRE,
            ROLE_COMPUTED,
            SELECTION,
            (*roots, *state_steps, *properties),
            result=result,
        ))
    steps.extend(case_steps)
    finite_values = [
        item.result.value
        for item in case_steps
        if item.result.state == RESULT_FINITE and item.result.value is not None
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
            expression="Select largest reconstructed case crack width",
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
    axes_values = dict(
        crack_branch=branch,
        crack_case="aggregate",
        crack_code=trace_identity_token(replay.route.code),
        crack_edition=EDITION,
        crack_member_cardinality=str(len(cases)),
    )
    if replay.route.route_id != "building-base":
        axes_values["crack_route"] = replay.route.route_id
    axes = context_axes(context, **axes_values)
    calculation_id = (
        f"ct-009-{context_id(context)}-base-crack-width-aggregate"
        if replay.route.route_id == "building-base"
        else (
            f"ct-009-{context_id(context)}-{replay.route.route_id}-"
            "crack-width-aggregate"
        )
    )
    calculation = TraceCalculation(
        calculation_id=calculation_id,
        coverage_id=COVERAGE_ID,
        title=(
            "EN 1992-1-1:2004 crack-width aggregate"
            if replay.route.route_id == "building-base"
            else f"{replay.route.title} crack-width aggregate"
        ),
        method_id=replay.route.method_id,
        axes=axes,
        final_step_id=final.step_id,
        steps=tuple(steps),
        warnings=(CRACK_DIRECTIONAL_LIMITATION,),
        assumptions=(
            (
                "Case order is long-term then short-term; no verdict is implied."
                if replay.route.route_id == "building-base"
                else "Case order is exact retained insertion order; no verdict is implied."
            ),
        ),
    )
    return _shape("aggregate", calculation, states), calculation


def _failed_member(
    replay: _FailedReplay,
    context: Mapping[str, Any],
) -> tuple[MemberShape, TraceCalculation]:
    steps = _identity_steps(
        replay.inputs,
        source=INPUT,
        role=ROLE_USER_INPUT,
        prefix="input",
    )
    inputs = tuple(steps)
    route_steps = _route_steps(replay.route, inputs)
    steps.extend(route_steps)
    output = _identity_steps(
        (("failure-output-structure", replay.output_shape),),
        source=BOUNDARY,
        role=ROLE_COMPUTED,
        dependencies=(*inputs, *route_steps),
        prefix="output",
    )
    steps.extend(output)
    final = _step(
        "crack-width-failed-result",
        "Crack-width replay failure",
        0.0,
        MILLIMETRE,
        ROLE_FINAL,
        BOUNDARY,
        (*inputs, *route_steps, *output),
        result=TraceResult(
            RESULT_FAILED,
            None,
            "Elastic/crack reconstruction did not converge; no value or verdict.",
        ),
    )
    steps.append(final)
    calculation_id = (
        f"ct-009-{context_id(context)}-base-crack-width-failed"
        if replay.route.route_id == "building-base"
        else (
            f"ct-009-{context_id(context)}-{replay.route.route_id}-"
            "crack-width-failed"
        )
    )
    failed_axes = dict(
        crack_branch="failed",
        crack_case="aggregate",
        crack_code=trace_identity_token(replay.route.code),
        crack_edition=EDITION,
    )
    if replay.route.route_id != "building-base":
        failed_axes["crack_route"] = replay.route.route_id
    calculation = TraceCalculation(
        calculation_id=calculation_id,
        coverage_id=COVERAGE_ID,
        title=(
            "EN 1992-1-1:2004 crack-width failure"
            if replay.route.route_id == "building-base"
            else f"{replay.route.title} crack-width failure"
        ),
        method_id=replay.route.method_id,
        axes=context_axes(context, **failed_axes),
        final_step_id=final.step_id,
        steps=tuple(steps),
        assumptions=(
            "Failure-only candidate numerics are not traversed; no verdict is implied.",
        ),
    )
    return _shape("failed", calculation, FAILED_STATES), calculation


def _expected_bundle(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any] | None,
) -> TraceBundle | None:
    input_mapping = _mapping(inp, "CT-009 input")
    trace_context = {} if context is None else _mapping(context, "CT-009 context")
    route = _active_route(input_mapping)
    if route is None:
        return None
    if _required(input_mapping, "section") is None:
        return None
    output_mapping = _mapping(out, "analysis output", exact=True)

    replay = _reconstruct(input_mapping, output_mapping, route)
    if isinstance(replay, _FailedReplay):
        shape, calculation = _failed_member(replay, trace_context)
        bundle = create_bundle(
            input_sha256=input_sha256,
            result_sha256=result_sha256,
            calculations=(calculation,),
        )
        return audit_trace_registry(bundle, registry_for((shape,), route))

    pairs = tuple(
        _case_member(replay, case, trace_context) for case in replay.cases
    )
    case_shapes = tuple(item[0] for item in pairs)
    case_calculations = tuple(item[1] for item in pairs)
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
        registry_for((*case_shapes, aggregate_shape), route),
    )


def build_crack_trace_family(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle | None:
    """Build the exact CT-009 base trace, or ``None`` when inactive."""

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
    """Validate CT-009 against a fresh independent reconstruction."""

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
