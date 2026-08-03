"""Solver-owned unpublished CT-009 EC2:2004 crack-width trace."""

from __future__ import annotations

import dataclasses
import math
import numbers
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from . import bridge
from .calculation_trace import (
    RESULT_FAILED,
    RESULT_FINITE,
    RESULT_UNDEFINED,
    TraceBundle,
    TraceCalculation,
    TraceDependency,
    TraceResult,
    TraceStep,
    TraceValidationError,
    create_bundle,
    trace_identity_token,
    validate_bundle,
)
from .crack_trace_contract import (
    AGGREGATE_KEYS,
    AREA,
    AREA_MM2,
    BASE_CASES,
    BRANCH_CALCULATED,
    BRANCH_FAILED,
    BRANCH_NOT_APPLICABLE,
    BRANCH_UNCRACKED,
    CANDIDATE_KEYS,
    CATALOG_KEYS,
    CORNER_KEYS,
    CRACK_KEYS,
    DK_CASES,
    ELASTIC_AGGREGATE_KEY,
    ELASTIC_CORE_KEYS,
    ELASTIC_DK_KEYS,
    ELASTIC_META_KEYS,
    ELASTIC_SERVICE_KEYS,
    ELEMENT_INPUT_KEYS,
    ELEMENT_KEYS,
    FORCE,
    LENGTH,
    LENGTH_MM,
    METHOD_ID,
    MILD_CATALOG_ITEM_KEYS,
    MOMENT,
    ONE,
    PRESTRESS_CATALOG_ITEM_KEYS,
    PROPERTY_KEYS,
    STRESS,
    STRESS_CONCRETE_KEYS,
    STRESS_ELEMENT_KEYS,
    STRESS_OUTPUT_KEYS,
    STRAIN,
    LeafSpec,
    TraceShape,
    expected_registry,
    expected_step_contract,
)
from .elastic import solve_elastic_combined, transformed_properties
from .materials import ES as STEEL_REFERENCE_MODULUS
from .section import MM2_TO_M2, Section
from .section_trace_blocks import context_axes, context_id, section_trace_blocks
from .serviceability import analyse_cracking, combined_cracking, crack_width
from . import sls as sls_core
from .trace_registry import audit_trace_registry


_BASE_CODES = frozenset({"EN 1992-1-1:2005", bridge.EN1992_2_BASE})
_DK_CODES = frozenset({"DS/EN 1992-1-1 + DK NA", bridge.EN1992_2_DK_NA})
_MODES = frozenset({"Plastic", "Elastic", "Both"})
_SIZE_MODES = frozenset({"Area", "Diameter", "Independent"})
_METHOD_VALUES = {
    "method-kt-long": 0.4,
    "method-kt-short": 0.6,
    "method-k2": 0.5,
    "method-k4": 0.425,
    "method-coarse-width-scale": 0.5,
}


@dataclass(frozen=True, slots=True)
class ReplayEvidence:
    shape: TraceShape
    values: dict[str, float]
    states: dict[str, TraceResult]
    expected_elastic: dict[str, Any]
    branch: str
    case_payloads: tuple[tuple[str, Mapping[str, Any]], ...]
    warnings: tuple[str, ...]


def _number(value: Any, label: str, *, positive=False, nonnegative=False) -> float:
    if type(value) not in {int, float} or type(value) is bool:
        raise TraceValidationError(f"{label} must be a finite non-Boolean number")
    result = float(value)
    if not math.isfinite(result):
        raise TraceValidationError(f"{label} must be a finite non-Boolean number")
    if positive and result <= 0.0:
        raise TraceValidationError(f"{label} must be positive")
    if nonnegative and result < 0.0:
        raise TraceValidationError(f"{label} must be non-negative")
    return result


def _text(value: Any, label: str, *, allow_blank=False) -> str:
    if type(value) is not str or value != value.strip() or (not value and not allow_blank):
        qualifier = "trimmed text" if allow_blank else "non-blank trimmed text"
        raise TraceValidationError(f"{label} must be {qualifier}")
    return value


def _sequence(value: Any, label: str) -> tuple[Any, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TraceValidationError(f"{label} must be an ordered sequence")
    return tuple(value)


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise TraceValidationError(f"{label} must be a text-keyed mapping")
    return value


def _exact_mapping(value: Any, keys: Sequence[str], label: str) -> Mapping[str, Any]:
    candidate = _mapping(value, label)
    if tuple(candidate) != tuple(keys):
        raise TraceValidationError(
            f"{label} field order {tuple(candidate)!r}; expected {tuple(keys)!r}"
        )
    return candidate


def _float_bytes(value: Any) -> bytes:
    try:
        return struct.pack(">d", float(value))
    except (OverflowError, TypeError, ValueError) as exc:
        raise TraceValidationError("value is not an IEEE-754 binary64 number") from exc


def _same_number(actual: Any, expected: Any) -> bool:
    return (
        isinstance(actual, numbers.Real)
        and not isinstance(actual, bool)
        and _float_bytes(actual) == _float_bytes(expected)
    )


def _compare(actual: Any, expected: Any, label: str) -> None:
    if isinstance(expected, Mapping):
        actual = _mapping(actual, label)
        if tuple(actual) != tuple(expected):
            raise TraceValidationError(f"{label} field inventory or order differs")
        for key in expected:
            _compare(actual[key], expected[key], f"{label}.{key}")
        return
    if isinstance(expected, (list, tuple)):
        if type(actual) is not type(expected):
            raise TraceValidationError(f"{label} retained sequence type differs")
        if len(actual) != len(expected):
            raise TraceValidationError(f"{label} cardinality differs")
        for index, (got, wanted) in enumerate(zip(actual, expected)):
            _compare(got, wanted, f"{label}[{index}]")
        return
    if type(expected) is bool or expected is None or type(expected) is str:
        if type(actual) is not type(expected) or actual != expected:
            raise TraceValidationError(f"{label} differs from authoritative replay")
        return
    if type(expected) is int:
        if type(actual) is not int or actual != expected:
            raise TraceValidationError(f"{label} integer identity differs")
        return
    if not _same_number(actual, expected):
        raise TraceValidationError(f"{label} differs from authoritative replay")


def _type_shape(actual: Any, expected: Any, label: str) -> None:
    """Pin failure payload structure while leaving failure-only numerics inert."""

    if isinstance(expected, Mapping):
        actual = _mapping(actual, label)
        if tuple(actual) != tuple(expected):
            raise TraceValidationError(f"{label} field inventory or order differs")
        for key in expected:
            _type_shape(actual[key], expected[key], f"{label}.{key}")
        return
    if isinstance(expected, (list, tuple)):
        if type(actual) is not type(expected) or len(actual) != len(expected):
            raise TraceValidationError(f"{label} retained sequence shape differs")
        for index, (got, wanted) in enumerate(zip(actual, expected)):
            _type_shape(got, wanted, f"{label}[{index}]")
        return
    if expected is None or type(expected) in {bool, str, int}:
        if type(actual) is not type(expected):
            raise TraceValidationError(f"{label} retained type differs")
        return
    if not isinstance(actual, numbers.Real) or isinstance(actual, bool):
        raise TraceValidationError(f"{label} must retain its numerical type")


def _validate_candidate(candidate: Any, expected: Mapping[str, Any], branch: str) -> None:
    """Validate one retained Elastic payload after failure-first replay."""

    if not isinstance(candidate, Mapping):
        raise TraceValidationError("results need the retained elastic payload")
    if branch == BRANCH_FAILED:
        _type_shape(candidate, expected, "elastic")
        _compare(candidate["converged"], False, "elastic.converged")
        _compare(candidate["crack_output"], expected["crack_output"], "elastic.crack_output")
    else:
        _compare(candidate, expected, "elastic")


def crack_trace_applicability(inp: Mapping[str, Any]) -> str:
    """Select CT-009 only from exact original applicability inputs."""

    mode = inp.get("mode")
    if type(mode) is not str or mode not in _MODES:
        raise TraceValidationError("mode must be an exact current analysis mode")
    sls_cw = inp.get("sls_cw")
    if type(sls_cw) is not bool:
        raise TraceValidationError("sls_cw must be Boolean")
    edition = inp.get("sls_edition")
    if type(edition) is not str:
        raise TraceValidationError("sls_edition must be text")
    dk_na = inp.get("sls_dk_na")
    if type(dk_na) is not bool:
        raise TraceValidationError("sls_dk_na must be Boolean")
    if mode not in {"Elastic", "Both"} or not sls_cw or edition != "2004":
        return "not-applicable"
    return "dk" if dk_na else "base"


def _geometry_and_elements(inp: Mapping[str, Any]) -> tuple[Section, tuple, tuple, dict]:
    outer = _sequence(inp.get("outer"), "outer")
    holes = _sequence(inp.get("holes"), "holes")
    bars = _sequence(inp.get("bars"), "bars")
    tendons = _sequence(inp.get("tendons"), "tendons")
    if len(outer) < 3:
        raise TraceValidationError("outer needs at least three vertices")

    def points(value, label, width):
        result = []
        for index, item in enumerate(value):
            item = _sequence(item, f"{label} {index}")
            if len(item) != width:
                raise TraceValidationError(f"{label} {index} has wrong cardinality")
            result.append(tuple(
                _number(component, f"{label} {index} component {position}")
                for position, component in enumerate(item)
            ))
        return tuple(result)

    raw_outer = points(outer, "outer point", 2)
    raw_holes = tuple(
        points(_sequence(ring, f"hole {index}"), f"hole {index} point", 2)
        for index, ring in enumerate(holes)
    )
    raw_bars = points(bars, "bar", 3)
    raw_tendons = points(tendons, "tendon", 3)
    if any(item[2] <= 0.0 for item in (*raw_bars, *raw_tendons)):
        raise TraceValidationError("reinforcement areas must be positive")

    expected = Section.from_polygon(
        raw_outer, raw_bars, raw_holes, raw_tendons
    )
    section = inp.get("section")
    if type(section) is not Section:
        raise TraceValidationError("section must be a Section")
    section.require_valid_geometry()
    if len(section.concrete) != len(expected.concrete):
        raise TraceValidationError("raw and immutable ring cardinality differs")
    for ring_index, (actual, wanted) in enumerate(zip(section.concrete, expected.concrete)):
        if actual.shape != wanted.shape:
            raise TraceValidationError(f"section ring {ring_index} shape differs")
        for actual_value, wanted_value in zip(actual.flat, wanted.flat):
            if not _same_number(actual_value, wanted_value):
                raise TraceValidationError("raw and immutable section geometry differs")
    for kind, actual, wanted in (
        ("bar", section.bars, expected.bars),
        ("tendon", section.tendons, expected.tendons),
    ):
        if len(actual) != len(wanted):
            raise TraceValidationError(f"raw and immutable {kind} cardinality differs")
        raw_items = raw_bars if kind == "bar" else raw_tendons
        for got, target, raw_item in zip(actual, wanted, raw_items):
            # Keep the precise Section constructor path. Division by 1e6 is not
            # binary-identical for every valid custom area (for example 0.1 mm2).
            if not _same_number(target.area, raw_item[2] * MM2_TO_M2):
                raise TraceValidationError(f"{kind} area conversion differs")
            if any(not _same_number(a, b) for a, b in zip(
                (got.x, got.y, got.area), (target.x, target.y, target.area)
            )):
                raise TraceValidationError(f"raw and immutable {kind} geometry differs")

    identities = {}
    for kind, key, raw in (
        ("bar", "bar_elements", raw_bars),
        ("tendon", "tendon_elements", raw_tendons),
    ):
        records = _sequence(inp.get(key), key)
        if len(records) != len(raw):
            raise TraceValidationError(f"{key} cardinality differs from geometry")
        clean = []
        seen = set()
        for index, (record, point) in enumerate(zip(records, raw)):
            record = _exact_mapping(record, ELEMENT_INPUT_KEYS, f"{key}[{index}]")
            element_id = _text(record["id"], f"{key}[{index}].id")
            if element_id in seen:
                raise TraceValidationError(f"duplicate {kind} element ID {element_id}")
            seen.add(element_id)
            if record["kind"] != kind or type(record["kind"]) is not str:
                raise TraceValidationError(f"{key}[{index}].kind differs")
            material_id = _text(record["material_id"], f"{key}[{index}].material_id")
            size_mode = _text(record["size_mode"], f"{key}[{index}].size_mode")
            if size_mode not in _SIZE_MODES:
                raise TraceValidationError(f"{key}[{index}].size_mode is invalid")
            _text(
                record["fatigue_detail_id"],
                f"{key}[{index}].fatigue_detail_id",
                allow_blank=True,
            )
            values = {
                name: _number(record[name], f"{key}[{index}].{name}", positive=(name in {"area_mm2", "diameter_mm"}))
                for name in ("x_mm", "y_mm", "area_mm2", "diameter_mm", "x", "y")
            }
            expected_values = {
                "x_mm": point[0] * 1000.0,
                "y_mm": point[1] * 1000.0,
                "area_mm2": point[2],
                "x": point[0],
                "y": point[1],
            }
            if any(not _same_number(values[name], wanted) for name, wanted in expected_values.items()):
                raise TraceValidationError(f"{key}[{index}] duplicates differ from geometry")
            clean.append({
                "id": element_id,
                "kind": kind,
                **values,
                "size_mode": size_mode,
                "material_id": material_id,
                # Fatigue is deliberately excluded from CT-009 values, but its
                # position and retained string type remain pinned.
                "fatigue_detail_id": "<excluded-ct009-text>",
            })
        identities[key] = clean
    folded = Section.from_polygon(
        raw_outer, (*raw_bars, *raw_tendons), raw_holes
    )
    return folded, raw_bars, raw_tendons, {
        "outer": raw_outer,
        "holes": raw_holes,
        "bars": raw_bars,
        "tendons": raw_tendons,
        **identities,
    }


def _catalog(inp, key, item_keys, selected_ids):
    catalog = _exact_mapping(inp.get(key), CATALOG_KEYS, key)
    if type(catalog["version"]) is not int or type(catalog["next_id"]) is not int:
        raise TraceValidationError(f"{key} version and next_id must be integers")
    items = _sequence(catalog["items"], f"{key}.items")
    selected = []
    for material_id in selected_ids:
        matches = [item for item in items if isinstance(item, Mapping) and item.get("id") == material_id]
        if len(matches) != 1:
            raise TraceValidationError(f"{key} needs one selected item {material_id}")
        item = _exact_mapping(matches[0], item_keys, f"{key}.{material_id}")
        for name in ("id", "name", "description", "preset"):
            _text(item[name], f"{key}.{material_id}.{name}", allow_blank=(name == "description"))
        if type(item["curve"]) is not int:
            raise TraceValidationError(f"{key}.{material_id}.curve must be an integer")
        if "active_in_compression" in item and type(item["active_in_compression"]) is not bool:
            raise TraceValidationError(f"{key}.{material_id}.active_in_compression must be Boolean")
        for name in item_keys:
            if name in {"id", "name", "description", "preset", "curve", "active_in_compression"}:
                continue
            _number(item[name], f"{key}.{material_id}.{name}")
        selected.append(dict(item))
    return dict(catalog), selected


def _material_state(inp, geometry_identity):
    try:
        blocks = section_trace_blocks(inp)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"invalid CT-009 geometry/material identity: {exc}") from exc
    bar_laws = _sequence(inp.get("bar_materials"), "bar_materials")
    tendon_laws = _sequence(inp.get("tendon_materials"), "tendon_materials")
    if len(bar_laws) != len(geometry_identity["bars"]):
        raise TraceValidationError("bar_materials are not aligned")
    if len(tendon_laws) != len(geometry_identity["tendons"]):
        raise TraceValidationError("tendon_materials are not aligned")
    bar_ids = [item["material_id"] for item in geometry_identity["bar_elements"]]
    tendon_ids = [item["material_id"] for item in geometry_identity["tendon_elements"]]
    mild_catalog, mild_selected = _catalog(
        inp, "mild_material_catalog", MILD_CATALOG_ITEM_KEYS,
        tuple(dict.fromkeys(bar_ids)),
    )
    prestress_catalog, prestress_selected = _catalog(
        inp, "prestress_material_catalog", PRESTRESS_CATALOG_ITEM_KEYS,
        tuple(dict.fromkeys(tendon_ids)),
    )
    names = {
        "bar": {item["id"]: item["name"] for item in mild_selected},
        "tendon": {item["id"]: item["name"] for item in prestress_selected},
    }
    identity = {
        "concrete_material_id": _text(
            str(inp.get("concrete_material_id") or blocks.concrete.material_id),
            "concrete material identity",
        ),
        "concrete_preset": _text(
            str(inp.get("concrete_preset") or "project-concrete"),
            "concrete_preset",
        ),
        "concrete_law": dict(blocks.concrete.values),
        "bar_laws": [
            {
                "element_id": item.element_id,
                "material_id": item.material_id,
                "law": dict(item.values),
                "source_kind": item.provenance.source.kind,
                "source_method": item.provenance.source.method_id,
            }
            for item in blocks.bars
        ],
        "tendon_laws": [
            {
                "element_id": item.element_id,
                "material_id": item.material_id,
                "law": dict(item.values),
                "source_kind": item.provenance.source.kind,
                "source_method": item.provenance.source.method_id,
            }
            for item in blocks.tendons
        ],
        "selected_mild_catalog": mild_selected,
        "selected_prestress_catalog": prestress_selected,
        "catalog_shape": {
            "mild_version": mild_catalog["version"],
            "mild_next_id": mild_catalog["next_id"],
            "prestress_version": prestress_catalog["version"],
            "prestress_next_id": prestress_catalog["next_id"],
        },
    }
    return blocks, list(bar_laws), list(tendon_laws), names, identity


def _props_dict(value):
    return {
        "area": value.area, "cx": value.cx, "cy": value.cy,
        "Ix": value.Ix, "Iy": value.Iy, "Ixy": value.Ixy,
    }


def _crack_payload(cw, bar_ids, tendon_ids):
    if cw is None:
        return None
    n_bars = len(bar_ids)

    def element(index):
        if index < n_bars:
            return "Bar", index + 1, bar_ids[index]
        tendon_index = index - n_bars
        return "Tendon", tendon_index + 1, tendon_ids[tendon_index]

    def candidate(item):
        kind, number, element_id = element(item.bar_index)
        return {
            "element_type": kind, "element_no": number,
            "element_id": element_id, "x_mm": item.x * 1000.0,
            "y_mm": item.y * 1000.0, "area_mm2": item.area,
            "wk": item.wk, "sr_max": item.sr_max,
            "esm_ecm": item.esm_ecm, "sigma_s": item.sigma_s,
            "rho_p_eff": item.rho_p_eff, "ac_eff": item.ac_eff,
            "hc_ef": item.hc_ef, "phi": item.phi, "cover": item.cover,
            "coarse": item.coarse, "edition": item.edition, "kw": item.kw,
            "k1_r": item.k1_r, "kfl": item.kfl,
            "sr_max_geometric": item.sr_max_geometric,
        }

    kind, number, element_id = element(cw.gov_bar)
    return {
        "wk": cw.wk, "sr_max": cw.sr_max, "esm_ecm": cw.esm_ecm,
        "sigma_s": cw.sigma_s, "rho_p_eff": cw.rho_p_eff,
        "ac_eff": cw.ac_eff, "hc_ef": cw.hc_ef, "phi": cw.phi,
        "cover": cw.cover, "gov_bar": cw.gov_bar + 1,
        "element_type": kind, "element_no": number, "element_id": element_id,
        "coarse": cw.coarse, "edition": cw.edition, "kw": cw.kw,
        "k1_r": cw.k1_r, "kfl": cw.kfl,
        "sr_max_geometric": cw.sr_max_geometric,
        "candidates": [candidate(item) for item in cw.candidates],
    }


def _validate_nested_inventory(elastic, *, calculated, dk_na):
    expected_keys = (*ELASTIC_CORE_KEYS, *ELASTIC_SERVICE_KEYS)
    if calculated:
        expected_keys += ELASTIC_META_KEYS
        if dk_na:
            expected_keys += ELASTIC_DK_KEYS
    expected_keys += (ELASTIC_AGGREGATE_KEY,)
    _exact_mapping(elastic, expected_keys, "elastic")
    for name in ("props_un", "props_cr"):
        if elastic[name] is not None:
            _exact_mapping(elastic[name], PROPERTY_KEYS, f"elastic.{name}")
    for index, row in enumerate(_sequence(elastic["elements"], "elastic.elements")):
        _exact_mapping(row, ELEMENT_KEYS, f"elastic.elements[{index}]")
    for index, row in enumerate(_sequence(elastic["concrete_corners"], "elastic.concrete_corners")):
        _exact_mapping(row, CORNER_KEYS, f"elastic.concrete_corners[{index}]")
    stress = _exact_mapping(elastic["stress_outputs"], STRESS_OUTPUT_KEYS, "elastic.stress_outputs")
    _exact_mapping(stress["concrete"], STRESS_CONCRETE_KEYS, "elastic.stress_outputs.concrete")
    for name in ("reinforcement", "prestress"):
        _exact_mapping(stress[name], STRESS_ELEMENT_KEYS, f"elastic.stress_outputs.{name}")
    for name in ("crack", "crack_short", *ELASTIC_DK_KEYS):
        if name not in elastic or elastic[name] is None:
            continue
        crack = _exact_mapping(elastic[name], CRACK_KEYS, f"elastic.{name}")
        for index, row in enumerate(_sequence(crack["candidates"], f"elastic.{name}.candidates")):
            _exact_mapping(row, CANDIDATE_KEYS, f"elastic.{name}.candidates[{index}]")
    _exact_mapping(elastic[ELASTIC_AGGREGATE_KEY], AGGREGATE_KEYS, "elastic.crack_output")


def _authoritative_elastic(inp, folded, bars, tendons, bar_laws, tendon_laws, names):
    p_l = -_number(inp.get("P_el_l"), "P_el_l")
    p_s = -_number(inp.get("P_el_s"), "P_el_s")
    mx_l = _number(inp.get("Mx_el_l"), "Mx_el_l")
    my_l = _number(inp.get("My_el_l"), "My_el_l")
    mx_s = _number(inp.get("Mx_el_s"), "Mx_el_s")
    my_s = _number(inp.get("My_el_s"), "My_el_s")
    nl = _number(inp.get("nl"), "nl", positive=True)
    ns = _number(inp.get("ns"), "ns", positive=True)
    ec = _number(inp.get("conc_Ec"), "conc_Ec", positive=True)
    creep = _number(inp.get("el_phi"), "el_phi", nonnegative=True)
    expected_ns = STEEL_REFERENCE_MODULUS / (ec * 1000.0)
    expected_nl = STEEL_REFERENCE_MODULUS * (1.0 + creep) / (ec * 1000.0)
    if not _same_number(ns, expected_ns) or not _same_number(nl, expected_nl):
        raise TraceValidationError("nl/ns contradict conc_Ec and el_phi")
    fctm = _number(inp.get("sls_fctm"), "sls_fctm", positive=True)
    sls_phi = _number(inp.get("sls_phi"), "sls_phi", nonnegative=True)
    sls_k1 = _number(inp.get("sls_k1"), "sls_k1", positive=True)
    tendon_xi_input = _number(inp.get("sls_tendon_xi"), "sls_tendon_xi", nonnegative=True)
    all_laws = [*bar_laws, *tendon_laws]
    moduli = np.asarray([law.Es for law in all_laws], dtype=float)
    n_mult = moduli / STEEL_REFERENCE_MODULUS if len(moduli) else None
    locked = None
    pre_resultant = None
    if tendons:
        locked = np.asarray(
            [0.0] * len(bars) + [law.Es * law.IS * 1000.0 for law in tendon_laws],
            dtype=float,
        )
        x, y, area = folded.bar_arrays()
        force = locked * area
        pre_resultant = (
            float(force.sum()), float((force * y).sum()), float((force * x).sum())
        )

    result = solve_elastic_combined(
        folded, p_l, mx_l, my_l, nl, p_s, mx_s, my_s, ns,
        n_mult=n_mult, prestress_stress=locked,
    )
    mpa = lambda values: [value / 1000.0 for value in values]
    total, long, dif, rst1 = (
        mpa(result.bar_stress_total), mpa(result.bar_stress_long),
        mpa(result.bar_stress_dif), mpa(result.bar_stress_rst1),
    )
    bar_records = list(inp["bar_elements"])
    tendon_records = list(inp["tendon_elements"])
    bar_ids = [item["id"] for item in bar_records]
    tendon_ids = [item["id"] for item in tendon_records]
    elements = sls_core.element_rows(
        list(inp["bars"]), list(inp["tendons"]),
        total=total, long=long, dif=dif, rst1=rst1,
        es_mpa=[law.Es for law in bar_laws],
        ep_mpa=[law.Es for law in tendon_laws] if tendon_laws else None,
        bar_ids=bar_ids, tendon_ids=tendon_ids,
        bar_material_ids=[item["material_id"] for item in bar_records],
        tendon_material_ids=[item["material_id"] for item in tendon_records],
        bar_material_names=[names["bar"][item["material_id"]] for item in bar_records],
        tendon_material_names=[names["tendon"][item["material_id"]] for item in tendon_records],
    )
    corners = sls_core.concrete_corner_rows(
        list(inp["outer"]), list(inp["holes"]),
        stress_plane=(result.short_term.eps0, result.short_term.kx, result.short_term.ky),
        ec_mpa=ec * 1000.0,
    )
    governing = max(elements, key=lambda row: row["total_mpa"]) if elements else None
    if governing is not None and governing["total_mpa"] <= 0.0:
        governing = None
    stress_outputs = sls_core.stress_outputs(
        total, n_bars=len(bars),
        max_concrete_compression=result.max_concrete_compression / 1000.0,
        valid=result.converged, bar_ids=bar_ids, tendon_ids=tendon_ids,
    )
    elastic = {
        "total": total, "long": long, "dif": dif, "rst1": rst1,
        "max_conc": result.max_concrete_compression / 1000.0,
        "max_conc_xy": tuple(result.short_term.max_concrete_xy),
        "max_conc_point": int(result.max_concrete_point) + 1,
        "na_x": result.na_x_intercept, "na_y": result.na_y_intercept,
        "max_steel": governing["total_mpa"] if governing else 0.0,
        "max_steel_bar": int(np.argmax(total)) + 1 if governing else 0,
        "max_steel_type": governing["element_type"] if governing else None,
        "max_steel_element": governing["element_id"] if governing else None,
        "prestress": pre_resultant, "converged": result.converged,
        "stress_plane": (result.short_term.eps0, result.short_term.kx, result.short_term.ky),
        "elements": elements, "concrete_corners": corners,
        "stress_outputs": stress_outputs,
    }

    phi = (
        sls_phi if sls_phi > 0.0
        else [
            _number(item["diameter_mm"], f"diameter {item['id']}", positive=True)
            for item in (*bar_records, *tendon_records)
        ]
    )
    k1 = [sls_k1] * len(bars) + [1.6] * len(tendons)
    dk_na = inp["sls_dk_na"]
    member = inp["sls_member"]
    include_hx = (not dk_na) or member == "Slab" or bool(tendons)
    cr_l = analyse_cracking(
        folded, p_l, mx_l, my_l, nl, fctm=fctm,
        Es=[law.Es for law in all_laws], beta=0.5, kt=0.4,
        bar_diameter=phi, k1=k1, k3_cover_dependent=dk_na,
        include_hx_term=include_hx, edition="2004", n_mult=n_mult,
        prestress_stress=locked,
    )
    converged = (
        result.converged and cr_l.uncracked.converged and cr_l.cracked_state.converged
    )
    elastic["converged"] = converged
    if not converged:
        for output in elastic["stress_outputs"].values():
            output.update(value=None, calculation_state="INVALID")
    cracked_t, lambda_t, sigma_t = combined_cracking(
        folded, p_l, mx_l, my_l, nl, p_s, mx_s, my_s, ns,
        fctm=fctm, n_mult=n_mult, prestress_stress=locked,
    )
    if lambda_t < cr_l.lambda_cr:
        cracked, lambda_cr, sigma_ct, governing_state = (
            cracked_t, lambda_t, sigma_t, result.short_term
        )
    else:
        cracked, lambda_cr, sigma_ct, governing_state = (
            cr_l.cracked, cr_l.lambda_cr, cr_l.sigma_ct, cr_l.cracked_state
        )
    props_un = transformed_properties(folded, nl, cracked=False, n_mult=n_mult)
    props_cr = (
        transformed_properties(
            folded, nl, eps0=governing_state.eps0, kx=governing_state.kx,
            ky=governing_state.ky, cracked=True, n_mult=n_mult,
        ) if cracked else None
    )
    elastic.update({
        "cracked": cracked, "lambda_cr": lambda_cr, "sigma_ct": sigma_ct,
        "fctm": fctm, "show_cw": True, "props_un": _props_dict(props_un),
        "props_cr": _props_dict(props_cr) if props_cr is not None else None,
        "crack": None, "crack_short": None,
    })

    if cracked:
        cw_stress = np.asarray(result.bar_stress_total, dtype=float)
        if locked is not None:
            cw_stress = cw_stress - locked
        short_state = dataclasses.replace(result.short_term, bar_stress=cw_stress)
        reinforcement_types = ["mild"] * len(bars) + ["prestress"] * len(tendons)
        tendon_xi = (
            None if not tendons or tendon_xi_input <= 0.0
            else [1.0] * len(bars) + [tendon_xi_input] * len(tendons)
        )

        def calculate(state, ratio, kt, coarse):
            return crack_width(
                folded, state, ratio, fctm=fctm, Es=[law.Es for law in all_laws],
                kt=kt, bar_diameter=phi, k1=k1, k3_cover_dependent=dk_na,
                include_hx_term=include_hx, coarse=coarse, edition="2004",
                n_mult=n_mult, reinforcement_types=reinforcement_types,
                bond_ratio_xi=tendon_xi,
            )

        long_fine = calculate(cr_l.cracked_state, nl, 0.4, False)
        short_fine = calculate(short_state, ns, 0.6, False)
        elastic.update({
            "crack": _crack_payload(long_fine, bar_ids, tendon_ids),
            "crack_short": _crack_payload(short_fine, bar_ids, tendon_ids),
            "crack_code": inp["sls_code"], "crack_edition": "2004",
            "crack_member": member if dk_na else None,
        })
        if dk_na:
            elastic.update({
                "crack_coarse": _crack_payload(
                    calculate(cr_l.cracked_state, nl, 0.4, True), bar_ids, tendon_ids
                ),
                "crack_short_coarse": _crack_payload(
                    calculate(short_state, ns, 0.6, True), bar_ids, tendon_ids
                ),
            })

    if dk_na and cracked:
        case_map = {
            "Long-term (fine)": elastic.get("crack"),
            "Short-term (fine)": elastic.get("crack_short"),
            "Long-term (coarse)": elastic.get("crack_coarse"),
            "Short-term (coarse)": elastic.get("crack_short_coarse"),
        }
    else:
        case_map = {
            "Long-term": elastic.get("crack"),
            "Short-term": elastic.get("crack_short"),
        }
    elastic["crack_output"] = sls_core.crack_outputs(case_map, valid=converged)
    _validate_nested_inventory(elastic, calculated=cracked, dk_na=dk_na)
    return elastic


def _unit_for_path(path: tuple[Any, ...]) -> Any:
    text = ".".join(str(item).lower() for item in path)
    tail = str(path[-1]).lower() if path else ""
    if tail in {"p_el_l", "p_el_s"}:
        return FORCE
    if tail in {"mx_el_l", "my_el_l", "mx_el_s", "my_el_s"}:
        return MOMENT
    if "area_mm2" in text:
        return AREA_MM2
    if tail in {"area", "ac_eff"} or tail.endswith(".area"):
        return AREA
    if tail.endswith("_mm") or tail in {"wk", "sr_max", "phi", "cover"}:
        return LENGTH_MM
    if tail in {"x", "y", "cx", "cy", "hc_ef", "na_x", "na_y"}:
        return LENGTH
    if any(token in tail for token in ("stress", "sigma", "fctm", "_mpa")):
        return STRESS
    if "strain" in tail or tail == "esm_ecm":
        return STRAIN
    return ONE


def _encoded_path(path):
    return "-".join(
        f"i{item:04d}" if type(item) is int else trace_identity_token(str(item))
        for item in path
    ) or "root"


def _leaf_inventory(prefix: str, value: Any):
    specs: list[LeafSpec] = []
    values: dict[str, float] = {}

    def add(path, suffix, title, number, unit=ONE):
        step_id = f"{prefix}-{_encoded_path(path)}-{suffix}"
        specs.append(LeafSpec(step_id, title, unit))
        values[step_id] = float(number)

    def visit(item, path):
        if isinstance(item, Mapping):
            order = "-".join(trace_identity_token(str(key)) for key in item)
            add(path, f"mapping-{order or 'empty'}", f"{prefix} mapping shape", len(item))
            for key in item:
                visit(item[key], (*path, key))
            return
        if isinstance(item, (list, tuple)):
            kind = "tuple" if isinstance(item, tuple) else "list"
            add(path, f"{kind}-n{len(item):04d}", f"{prefix} sequence shape", len(item))
            for index, child in enumerate(item):
                visit(child, (*path, index))
            return
        unit = _unit_for_path(path)
        if item is None:
            add(path, "none", f"{prefix} null identity", 0.0)
        elif type(item) is bool:
            add(path, f"bool-{int(item)}", f"{prefix} Boolean identity", int(item))
        elif type(item) is str:
            add(path, f"text-{trace_identity_token(item)}", f"{prefix} text identity", 0.0)
        elif isinstance(item, numbers.Real) and not isinstance(item, bool):
            number = float(item)
            if math.isfinite(number):
                add(path, "number", f"{prefix} numerical identity", number, unit)
            else:
                bits = struct.pack(">d", number).hex()
                add(path, f"nonfinite-{bits}", f"{prefix} non-finite identity", 0.0)
        else:
            raise TraceValidationError(f"{prefix} identity contains unsupported {type(item).__name__}")

    visit(value, ())
    return tuple(specs), values


def _input_identity(inp, geometry, material):
    mode = inp["mode"]
    code = _text(inp.get("sls_code"), "sls_code")
    member = _text(inp.get("sls_member"), "sls_member")
    if member not in {"Beam", "Slab"}:
        raise TraceValidationError("sls_member must be Beam or Slab")
    dk_na = inp["sls_dk_na"]
    expected_codes = _DK_CODES if dk_na else _BASE_CODES
    if code not in expected_codes:
        raise TraceValidationError("sls_code contradicts sls_dk_na")
    scalars = {
        "mode": mode, "sls_cw": inp["sls_cw"], "sls_edition": inp["sls_edition"],
        "sls_dk_na": dk_na, "sls_code": code, "sls_member": member,
    }
    for key, options in (
        ("sls_fctm", {"positive": True}), ("sls_phi", {"nonnegative": True}),
        ("sls_k1", {"positive": True}), ("sls_tendon_xi", {"nonnegative": True}),
        ("ns", {"positive": True}), ("nl", {"positive": True}),
        ("conc_Ec", {"positive": True}), ("el_phi", {"nonnegative": True}),
    ):
        scalars[key] = _number(inp.get(key), key, **options)
    for key in ("P_el_l", "Mx_el_l", "My_el_l", "P_el_s", "Mx_el_s", "My_el_s"):
        scalars[key] = _number(inp.get(key), key)
    return {"scalars": scalars, "geometry": geometry, "materials": material}


def _replay(inp: Mapping[str, Any], out: Mapping[str, Any], context):
    variant = crack_trace_applicability(inp)
    if variant == "not-applicable":
        return None
    folded, bars, tendons, geometry = _geometry_and_elements(inp)
    blocks, bar_laws, tendon_laws, names, material_identity = _material_state(inp, geometry)
    identity = _input_identity(inp, geometry, material_identity)
    elastic = _authoritative_elastic(
        inp, folded, bars, tendons, bar_laws, tendon_laws, names
    )
    candidate_out = _mapping(out, "results")
    candidate = candidate_out.get("elastic")

    if not elastic["converged"]:
        branch = BRANCH_FAILED
        _validate_candidate(candidate, elastic, branch)
        output_identity = {
            "converged": False, "crack_output": elastic["crack_output"]
        }
    else:
        output_identity = elastic
        if not elastic["cracked"]:
            branch = BRANCH_UNCRACKED
        elif elastic["crack_output"]["calculation_state"] != "CALCULATED":
            branch = BRANCH_NOT_APPLICABLE
        else:
            branch = BRANCH_CALCULATED
        _validate_candidate(candidate, elastic, branch)

    input_specs, input_values = _leaf_inventory("input", identity)
    output_specs, output_values = _leaf_inventory("output", output_identity)
    case_ids = DK_CASES if inp["sls_dk_na"] else BASE_CASES
    crack_keys = (
        ("crack", "crack_short", "crack_coarse", "crack_short_coarse")
        if inp["sls_dk_na"] else ("crack", "crack_short")
    )
    cases = tuple(
        (case_id, elastic.get(key))
        for case_id, key in zip(case_ids, crack_keys)
        if elastic.get(key) is not None
    )
    counts = tuple((case_id, len(payload["candidates"])) for case_id, payload in cases)
    axes = context_axes(
        context,
        branch=branch,
        case_order=",".join(case_ids),
        concrete_material_id=material_identity["concrete_material_id"],
        crack_code=inp["sls_code"],
        dk_na="true" if inp["sls_dk_na"] else "false",
        edition="2004",
        member=inp["sls_member"],
        sign="tension-positive-n",
    )
    shape = TraceShape(
        f"crack.{context_id(context)}.ec2-2004",
        axes,
        branch,
        input_specs,
        output_specs,
        counts,
        inp["sls_dk_na"],
    )
    values = {**input_values, **output_values, **_METHOD_VALUES}
    values["normalised-crack-inputs"] = 1.0
    values["retained-elastic-output-vector"] = 1.0
    states: dict[str, TraceResult] = {}
    for case_id, payload in cases:
        for index, candidate_payload in enumerate(payload["candidates"]):
            prefix = f"case-{case_id}-candidate-{index:04d}"
            values.update({
                f"{prefix}-sigma-s": candidate_payload["sigma_s"],
                f"{prefix}-ac-eff": candidate_payload["ac_eff"],
                f"{prefix}-hc-eff": candidate_payload["hc_ef"],
                f"{prefix}-rho-p-eff": candidate_payload["rho_p_eff"],
                f"{prefix}-sr-max": candidate_payload["sr_max"],
                f"{prefix}-esm-ecm": candidate_payload["esm_ecm"],
                f"{prefix}-wk": candidate_payload["wk"],
                f"{prefix}-complete": 1.0,
            })
        values[f"case-{case_id}-governing-width"] = payload["wk"]

    if branch == BRANCH_CALCULATED:
        values["governing-crack-output"] = elastic["crack_output"]["value"]
        values["ct-009-crack-width-result"] = elastic["crack_output"]["value"]
    elif branch in {BRANCH_UNCRACKED, BRANCH_NOT_APPLICABLE}:
        state_id = (
            "uncracked-section-state" if branch == BRANCH_UNCRACKED
            else "no-crack-candidate-state"
        )
        values[state_id] = 1.0
        states["ct-009-crack-width-result"] = TraceResult(
            RESULT_UNDEFINED,
            None,
            "The retained 2004 crack-width output is not applicable.",
        )
    else:
        values["crack-reconstruction-failure"] = 1.0
        states["ct-009-crack-width-result"] = TraceResult(
            RESULT_FAILED,
            None,
            "The authoritative CT-009 reconstruction did not converge; no crack width or engineering verdict is published.",
        )
    warnings = (
        "Crack width is a numerical output only; no allowable width, utilisation, or compliance verdict is included.",
        "The retained 2004 method is a one-directional dominant strain-gradient calculation.",
    )
    return ReplayEvidence(shape, values, states, elastic, branch, cases, warnings)


def _actual_expression(step_id):
    if step_id.startswith("input-"):
        return "Retain exact original input identity leaf"
    if step_id.startswith("output-"):
        return "Reconstruct exact retained Elastic output leaf from original inputs"
    if step_id.endswith("-rho-p-eff"):
        return "rho_p,eff = A_s,eff / A_c,eff"
    if step_id.endswith("-esm-ecm"):
        return "eps_sm - eps_cm per EC2 Equation (7.9)"
    if step_id.endswith("-sr-max"):
        return "s_r,max per EC2 Equation (7.11), or Equation (7.14) where geometric spacing governs"
    if step_id.endswith("-wk"):
        return "w_k = s_r,max (eps_sm - eps_cm)"
    if step_id == "governing-crack-output":
        return "Select the largest calculated retained case width"
    return "Bind complete CT-009 replay evidence"


def _calculation(evidence: ReplayEvidence) -> TraceCalculation:
    specs = expected_step_contract(evidence.shape)
    units = {item.step_id: item.unit for item in specs}
    steps = []
    for spec in specs:
        state = evidence.states.get(spec.step_id)
        if state is None:
            if spec.step_id not in evidence.values:
                raise TraceValidationError(f"internal CT-009 value omitted {spec.step_id}")
            value = evidence.values[spec.step_id]
            state = TraceResult(RESULT_FINITE, float(value))
            substituted = f"{spec.step_id} = {float(value):.17g} {spec.unit.symbol}"
        else:
            substituted = f"{spec.step_id} = {state.state}"
        assumptions = ()
        if spec.step_id == "ct-009-crack-width-result":
            assumptions = (
                "This trace reports no allowable crack width, utilisation, acceptance limit, or compliance verdict.",
            )
        steps.append(TraceStep(
            step_id=spec.step_id,
            title=spec.title,
            dependencies=tuple(
                TraceDependency(dependency, units[dependency])
                for dependency in spec.dependencies
            ),
            quantity_role=spec.quantity_role,
            source=spec.source,
            symbol=spec.step_id,
            unit=spec.unit,
            actual_expression=_actual_expression(spec.step_id),
            substituted_expression=substituted,
            result=state,
            assumptions=assumptions,
        ))
    return TraceCalculation(
        calculation_id=evidence.shape.calculation_id,
        coverage_id="ct-009",
        title="EC2:2004 crack width, base and Danish NA",
        method_id=METHOD_ID,
        axes=evidence.shape.axes,
        final_step_id="ct-009-crack-width-result",
        steps=tuple(steps),
        warnings=evidence.warnings,
        assumptions=(
            "User normal force is tension-positive; the retained elastic solver receives its compression-positive opposite.",
            "Long-term width uses the retained Stage II sustained state and kt=0.4; short-term width uses the combined creep total stress with locked tendon prestress removed and kt=0.6.",
            "The Danish NA branch publishes ordered fine and coarse systems for both durations.",
        ),
    )


def _expected_bundle(inp, out, *, input_sha256, result_sha256, context):
    evidence = _replay(inp, out, {} if context is None else context)
    if evidence is None:
        return None
    bundle = create_bundle(
        input_sha256=input_sha256,
        result_sha256=result_sha256,
        calculations=(_calculation(evidence),),
    )
    audit_trace_registry(bundle, expected_registry(evidence.shape))
    return bundle


def build_crack_trace_family(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle | None:
    """Build the exact unpublished CT-009 family, or ``None`` when inapplicable."""

    try:
        return _expected_bundle(
            inp, out, input_sha256=input_sha256, result_sha256=result_sha256,
            context=context,
        )
    except TraceValidationError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"invalid CT-009 evidence: {exc}") from exc


def validate_crack_trace_family(
    bundle: TraceBundle | dict[str, Any] | None,
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle | None:
    """Reject stale, reshaped, resealed, or coherently altered CT-009 evidence."""

    expected = _expected_bundle(
        inp, out, input_sha256=input_sha256, result_sha256=result_sha256,
        context=context,
    )
    if expected is None:
        if bundle is not None:
            raise TraceValidationError("CT-009 trace is present outside its applicability")
        return None
    if bundle is None:
        raise TraceValidationError("applicable CT-009 trace is missing")
    candidate = validate_bundle(
        bundle,
        expected_input_sha256=input_sha256,
        expected_result_sha256=result_sha256,
    )
    evidence = _replay(inp, out, {} if context is None else context)
    assert evidence is not None
    audit_trace_registry(candidate, expected_registry(evidence.shape))
    if candidate.to_dict() != expected.to_dict():
        raise TraceValidationError("CT-009 trace differs from authoritative input replay")
    return candidate
