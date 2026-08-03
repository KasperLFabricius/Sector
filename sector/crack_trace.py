"""Authoritative CT-009 replay for retained 2004 crack-width output."""

from __future__ import annotations

import dataclasses
import hashlib
import math
import numbers
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from .calculation_trace import (
    RESULT_FAILED,
    RESULT_FINITE,
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
    AGGREGATE_KEY,
    AGGREGATE_KEYS,
    AREA,
    BASE_ELASTIC_KEYS,
    CALCULATED_META_KEYS,
    CASE_LABELS,
    CASE_LONG_COARSE,
    CASE_LONG_FINE,
    CASE_ORDER,
    CASE_OUTPUT_KEYS,
    CASE_SHORT_COARSE,
    CASE_SHORT_FINE,
    COARSE_KEYS,
    COVERAGE_ID,
    CRACK_CANDIDATE_KEYS,
    CRACK_RESULT_KEYS,
    CRACK_WIDTH,
    CT005,
    DK_COARSE,
    DK_COVER,
    DK_EFFECTIVE_AREA,
    EFFECTIVE_AREA,
    ELEMENT_KEYS,
    FORCE,
    IDENTITY,
    INPUT,
    LENGTH,
    LONG_REPLAY,
    MEAN_STRAIN,
    METHOD_ID,
    MM,
    MOMENT,
    MemberShape,
    ONE,
    RAW_GRADIENT,
    RAW_STRESS,
    SELECTOR,
    SPACING_CLOSE,
    SPACING_GEOMETRIC,
    STRESS,
    registry_for,
)
from .elastic import solve_elastic_combined, transformed_properties
from .section import Bar, Section
from .section_trace_blocks import (
    SectionTraceBlocks,
    context_axes,
    context_id,
    section_trace_blocks,
)
from .serviceability import (
    _depth_axis,
    analyse_cracking,
    combined_cracking,
    crack_width,
)
from .sls import concrete_corner_rows, crack_outputs, element_rows, stress_outputs
from .trace_registry import audit_trace_registry


_REFERENCE_ES = 200_000.0
_PLASTIC_ACTION_KEYS = frozenset(("P_pl", "Mx_pl", "My_pl"))
_ACTION_KEYS = (
    "P_el_l", "Mx_el_l", "My_el_l", "P_el_s", "Mx_el_s", "My_el_s",
)
_SCALAR_KEYS = (
    "sls_fctm", "sls_phi", "sls_k1", "sls_tendon_xi", "ns", "nl",
)


@dataclass(frozen=True, slots=True)
class _Replay:
    blocks: SectionTraceBlocks
    section: Section
    expected_elastic: dict[str, Any]
    combined: Any
    long_state: Any
    short_state: Any
    cases: tuple[tuple[str, Any | None], ...]
    moduli: np.ndarray
    n_mult: np.ndarray
    locked: np.ndarray | None
    diameters: tuple[float, ...]
    k1_values: tuple[float, ...]
    include_hx: bool
    dk: bool
    cracked: bool
    converged: bool


@dataclass(frozen=True, slots=True)
class _InputGraph:
    final_id: str
    geometry_ids: tuple[str, ...]
    material_ids: tuple[str, ...]
    scalar_ids: dict[str, str]
    action_ids: dict[str, str]
    element_ids: tuple[tuple[str, str, str], ...]
    modulus_ids: tuple[str, ...]
    diameter_ids: tuple[str, ...]


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TraceValidationError(f"{label} must be a mapping")
    return value


def _text(value: Any, label: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise TraceValidationError(f"{label} must be non-empty trimmed text")
    return value


def _boolean(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise TraceValidationError(f"{label} must be an exact built-in Boolean")
    return value


def _number(value: Any, label: str, *, positive: bool = False) -> float:
    if type(value) not in {int, float} or type(value) is bool:
        raise TraceValidationError(f"{label} must be a finite non-Boolean number")
    converted = float(value)
    if not math.isfinite(converted) or (positive and converted <= 0.0):
        qualifier = "positive " if positive else ""
        raise TraceValidationError(
            f"{label} must be a finite {qualifier}non-Boolean number")
    return converted


def _sequence(value: Any, label: str) -> tuple[Any, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TraceValidationError(f"{label} must be an aligned sequence")
    return tuple(value)


def _float_equal(left: Any, right: Any) -> bool:
    if not isinstance(left, numbers.Real) or isinstance(left, (bool, np.bool_)):
        return False
    a, b = float(left), float(right)
    if math.isnan(b):
        return math.isnan(a)
    return struct.pack(">d", a) == struct.pack(">d", b)


def _compare_exact(actual: Any, expected: Any, label: str) -> None:
    """Require exact inventory, retained type, order, and float identity."""

    if isinstance(expected, Mapping):
        if type(actual) is not dict:
            raise TraceValidationError(f"{label} must be an exact object")
        if tuple(actual) != tuple(expected):
            raise TraceValidationError(f"{label} has a different ordered inventory")
        for key, value in expected.items():
            _compare_exact(actual[key], value, f"{label}.{key}")
        return
    if type(expected) is list:
        if type(actual) is not list or len(actual) != len(expected):
            raise TraceValidationError(f"{label} must be an exact aligned list")
        for index, (got, wanted) in enumerate(zip(actual, expected)):
            _compare_exact(got, wanted, f"{label}[{index}]")
        return
    if type(expected) is tuple:
        if type(actual) is not tuple or len(actual) != len(expected):
            raise TraceValidationError(f"{label} must be an exact aligned tuple")
        for index, (got, wanted) in enumerate(zip(actual, expected)):
            _compare_exact(got, wanted, f"{label}[{index}]")
        return
    if type(expected) is bool:
        if type(actual) is not bool or actual is not expected:
            raise TraceValidationError(f"{label} differs from authoritative replay")
        return
    if type(expected) is int:
        if type(actual) is not int or type(actual) is bool or actual != expected:
            raise TraceValidationError(f"{label} differs from authoritative replay")
        return
    if expected is None or type(expected) is str:
        if type(actual) is not type(expected) or actual != expected:
            raise TraceValidationError(f"{label} differs from authoritative replay")
        return
    if not _float_equal(actual, expected):
        raise TraceValidationError(f"{label} differs from exact authoritative replay")


def _compare_shape(actual: Any, expected: Any, label: str) -> None:
    """Pin failure-only inventory, position, cardinality, and retained type."""

    if isinstance(expected, Mapping):
        if type(actual) is not dict or tuple(actual) != tuple(expected):
            raise TraceValidationError(f"{label} has a different ordered inventory")
        for key, value in expected.items():
            _compare_shape(actual[key], value, f"{label}.{key}")
        return
    if type(expected) in {list, tuple}:
        if type(actual) is not type(expected) or len(actual) != len(expected):
            raise TraceValidationError(f"{label} has a different retained shape")
        for index, (got, wanted) in enumerate(zip(actual, expected)):
            _compare_shape(got, wanted, f"{label}[{index}]")
        return
    if expected is None:
        if actual is not None:
            raise TraceValidationError(f"{label} must remain null")
        return
    if type(expected) is bool:
        if type(actual) is not bool:
            raise TraceValidationError(f"{label} must remain Boolean")
        return
    if type(expected) is int:
        if type(actual) is not int or type(actual) is bool:
            raise TraceValidationError(f"{label} must remain an integer")
        return
    if type(expected) is str:
        if type(actual) is not str:
            raise TraceValidationError(f"{label} must remain text")
        return
    if not isinstance(actual, numbers.Real) or isinstance(actual, (bool, np.bool_)):
        raise TraceValidationError(f"{label} must retain numerical type")


def _law_value(material: Any, name: str) -> float:
    values = dict(material.values)
    if name not in values:
        raise TraceValidationError(
            f"assigned {material.kind} law lacks {name}")
    return _number(values[name], f"{material.kind} {material.element_id} {name}")


def _folded_section(blocks: SectionTraceBlocks) -> Section:
    return Section(
        [np.asarray(ring, dtype=float) for ring in blocks.geometry.rings],
        bars=[
            Bar(element.x, element.y, element.area)
            for element in (*blocks.geometry.bars, *blocks.geometry.tendons)
        ],
    )


def _catalog_names(inp: Mapping[str, Any], key: str) -> dict[str, str]:
    catalog = _mapping(inp.get(key), key)
    items = _sequence(catalog.get("items"), f"{key}.items")
    names: dict[str, str] = {}
    for index, item in enumerate(items):
        item = _mapping(item, f"{key}.items[{index}]")
        material_id = _text(item.get("id"), f"{key}.items[{index}].id")
        name = _text(item.get("name"), f"{key}.items[{index}].name")
        if material_id in names:
            raise TraceValidationError(f"{key} has duplicate material ID")
        names[material_id] = name
    return names


def _element_records(inp: Mapping[str, Any], key: str) -> tuple[Mapping[str, Any], ...]:
    records = _sequence(inp.get(key, ()), key)
    values = []
    for index, record in enumerate(records):
        values.append(_mapping(record, f"{key}[{index}]"))
    return tuple(values)


def _element_ids(
    records: tuple[Mapping[str, Any], ...], label: str,
) -> tuple[str, ...]:
    return tuple(
        _text(record.get("id"), f"{label}[{index}].id")
        for index, record in enumerate(records)
    )


def _material_ids(
    records: tuple[Mapping[str, Any], ...], label: str,
) -> tuple[str, ...]:
    return tuple(
        _text(record.get("material_id"), f"{label}[{index}].material_id")
        for index, record in enumerate(records)
    )


def _original_reinforcement_rows(
    inp: Mapping[str, Any],
    key: str,
    geometry: Sequence[Any],
) -> tuple[tuple[float, float, float], ...]:
    """Retain the app's original mm2 area representation for output rows."""

    rows = _sequence(inp.get(key, ()), key)
    if len(rows) != len(geometry):
        raise TraceValidationError(f"{key} must align with section geometry")
    original = []
    for index, (row, element) in enumerate(zip(rows, geometry)):
        values = _sequence(row, f"{key}[{index}]")
        if len(values) != 3:
            raise TraceValidationError(
                f"{key}[{index}] must contain x, y and area")
        x = _number(values[0], f"{key}[{index}].x")
        y = _number(values[1], f"{key}[{index}].y")
        area_mm2 = _number(
            values[2], f"{key}[{index}].area_mm2", positive=True)
        if (
            not _float_equal(x, element.x)
            or not _float_equal(y, element.y)
            or not _float_equal(area_mm2 / 1.0e6, element.area)
        ):
            raise TraceValidationError(
                f"{key}[{index}] differs from section geometry")
        original.append((x, y, area_mm2))
    return tuple(original)


def _diameters(
    inp: Mapping[str, Any], records: tuple[Mapping[str, Any], ...],
) -> tuple[float, ...]:
    override = _number(inp.get("sls_phi"), "sls_phi")
    if override > 0.0:
        return (override,) * len(records)
    return tuple(
        _number(
            record.get("diameter_mm"),
            f"crack element {index}.diameter_mm",
            positive=True,
        )
        for index, record in enumerate(records)
    )


def _props_dict(value: Any) -> dict[str, float]:
    return {
        "area": value.area,
        "cx": value.cx,
        "cy": value.cy,
        "Ix": value.Ix,
        "Iy": value.Iy,
        "Ixy": value.Ixy,
    }


def _crack_dict(
    result: Any | None,
    bar_ids: tuple[str, ...],
    tendon_ids: tuple[str, ...],
) -> dict[str, Any] | None:
    if result is None:
        return None
    n_bars = len(bar_ids)

    def identity(index: int) -> tuple[str, int, str]:
        if index < n_bars:
            return "Bar", index + 1, bar_ids[index]
        tendon_index = index - n_bars
        return "Tendon", tendon_index + 1, tendon_ids[tendon_index]

    def candidate(value: Any) -> dict[str, Any]:
        kind, number, element_id = identity(value.bar_index)
        return {
            "element_type": kind,
            "element_no": number,
            "element_id": element_id,
            "x_mm": value.x * 1000.0,
            "y_mm": value.y * 1000.0,
            "area_mm2": value.area,
            "wk": value.wk,
            "sr_max": value.sr_max,
            "esm_ecm": value.esm_ecm,
            "sigma_s": value.sigma_s,
            "rho_p_eff": value.rho_p_eff,
            "ac_eff": value.ac_eff,
            "hc_ef": value.hc_ef,
            "phi": value.phi,
            "cover": value.cover,
            "coarse": value.coarse,
            "edition": value.edition,
            "kw": value.kw,
            "k1_r": value.k1_r,
            "kfl": value.kfl,
            "sr_max_geometric": value.sr_max_geometric,
        }

    kind, number, element_id = identity(result.gov_bar)
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
        "candidates": [candidate(value) for value in result.candidates],
    }


def _validate_payload_inventories(elastic: Mapping[str, Any], dk: bool) -> None:
    expected = list(BASE_ELASTIC_KEYS)
    calculated = "crack_code" in elastic
    if calculated:
        expected.extend(CALCULATED_META_KEYS)
        if dk:
            expected.extend(COARSE_KEYS)
    expected.append(AGGREGATE_KEY)
    if type(elastic) is not dict or tuple(elastic) != tuple(expected):
        raise TraceValidationError(
            "CT-009 candidate elastic result has a different ordered inventory")
    for key in ("crack", "crack_short", *COARSE_KEYS):
        if key not in elastic or elastic[key] is None:
            continue
        result = elastic[key]
        if type(result) is not dict or tuple(result) != CRACK_RESULT_KEYS:
            raise TraceValidationError(f"elastic.{key} has a different inventory")
        candidates = result["candidates"]
        if type(candidates) is not list:
            raise TraceValidationError(f"elastic.{key}.candidates must be a list")
        for index, candidate in enumerate(candidates):
            if type(candidate) is not dict or tuple(candidate) != CRACK_CANDIDATE_KEYS:
                raise TraceValidationError(
                    f"elastic.{key}.candidates[{index}] has a different inventory")
    aggregate = elastic[AGGREGATE_KEY]
    if type(aggregate) is not dict or tuple(aggregate) != AGGREGATE_KEYS:
        raise TraceValidationError("elastic.crack_output has a different inventory")
    elements = elastic["elements"]
    if type(elements) is not list:
        raise TraceValidationError("elastic.elements must be a list")
    for index, element in enumerate(elements):
        if type(element) is not dict or tuple(element) != ELEMENT_KEYS:
            raise TraceValidationError(
                f"elastic.elements[{index}] has a different inventory")


def _replay(inp: Mapping[str, Any], out: Mapping[str, Any]) -> _Replay:
    filtered = {key: value for key, value in inp.items() if key not in _PLASTIC_ACTION_KEYS}
    blocks = section_trace_blocks(filtered)
    section = _folded_section(blocks)
    bar_records = _element_records(inp, "bar_elements")
    tendon_records = _element_records(inp, "tendon_elements")
    records = (*bar_records, *tendon_records)
    if len(records) != len(blocks.geometry.bars) + len(blocks.geometry.tendons):
        raise TraceValidationError("crack element records must align with geometry")
    bar_ids = _element_ids(bar_records, "bar_elements")
    tendon_ids = _element_ids(tendon_records, "tendon_elements")
    bar_material_ids = _material_ids(bar_records, "bar_elements")
    tendon_material_ids = _material_ids(tendon_records, "tendon_elements")
    mild_names = _catalog_names(inp, "mild_material_catalog")
    prestress_names = _catalog_names(inp, "prestress_material_catalog")
    moduli = np.asarray(
        [_law_value(item, "Es") for item in (*blocks.bars, *blocks.tendons)],
        dtype=float,
    )
    if np.any(moduli <= 0.0):
        raise TraceValidationError("crack reinforcement moduli must be positive")
    n_mult = moduli / _REFERENCE_ES
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
    actions = {key: _number(inp.get(key), key) for key in _ACTION_KEYS}
    scalars = {
        key: _number(inp.get(key), key, positive=key in {"sls_fctm", "ns", "nl"})
        for key in _SCALAR_KEYS
    }
    if scalars["sls_k1"] <= 0.0:
        raise TraceValidationError("sls_k1 must be positive")
    dk = _boolean(inp.get("sls_dk_na"), "sls_dk_na")
    member = _text(inp.get("sls_member"), "sls_member")
    diameters = _diameters(inp, records)
    k1_values = (
        (scalars["sls_k1"],) * len(blocks.bars)
        + (1.6,) * len(blocks.tendons)
    )
    include_hx = (not dk) or member == "Slab" or bool(blocks.tendons)
    kinds = ("mild",) * len(blocks.bars) + ("prestress",) * len(blocks.tendons)
    tendon_xi = (
        None
        if not blocks.tendons or scalars["sls_tendon_xi"] <= 0.0
        else (1.0,) * len(blocks.bars)
        + (scalars["sls_tendon_xi"],) * len(blocks.tendons)
    )
    p_l, p_s = -actions["P_el_l"], -actions["P_el_s"]
    combined = solve_elastic_combined(
        section,
        p_l, actions["Mx_el_l"], actions["My_el_l"], scalars["nl"],
        p_s, actions["Mx_el_s"], actions["My_el_s"], scalars["ns"],
        n_mult=n_mult if n_mult.size else None,
        prestress_stress=locked,
    )
    long_analysis = analyse_cracking(
        section,
        p_l, actions["Mx_el_l"], actions["My_el_l"], scalars["nl"],
        fctm=scalars["sls_fctm"],
        Es=moduli,
        beta=0.5,
        kt=0.4,
        bar_diameter=diameters,
        k1=k1_values,
        k3_cover_dependent=dk,
        include_hx_term=include_hx,
        edition="2004",
        n_mult=n_mult if n_mult.size else None,
        prestress_stress=locked,
    )
    converged = bool(
        combined.converged
        and long_analysis.uncracked.converged
        and long_analysis.cracked_state.converged
    )
    combined_cracked, total_factor, total_sigma = combined_cracking(
        section,
        p_l, actions["Mx_el_l"], actions["My_el_l"], scalars["nl"],
        p_s, actions["Mx_el_s"], actions["My_el_s"], scalars["ns"],
        fctm=scalars["sls_fctm"],
        n_mult=n_mult if n_mult.size else None,
        prestress_stress=locked,
    )
    if total_factor < long_analysis.lambda_cr:
        cracked = combined_cracked
        factor = total_factor
        sigma_ct = total_sigma
        governing_state = combined.short_term
    else:
        cracked = long_analysis.cracked
        factor = long_analysis.lambda_cr
        sigma_ct = long_analysis.sigma_ct
        governing_state = long_analysis.cracked_state

    total = np.asarray(combined.bar_stress_total, dtype=float) / 1000.0
    long = np.asarray(combined.bar_stress_long, dtype=float) / 1000.0
    dif = np.asarray(combined.bar_stress_dif, dtype=float) / 1000.0
    rst1 = np.asarray(combined.bar_stress_rst1, dtype=float) / 1000.0
    # element_rows receives the app's original mm2 values. Reversing the
    # Section's mm2 -> m2 conversion can move non-binary areas by one ULP.
    bars_mm2 = _original_reinforcement_rows(
        inp, "bars", blocks.geometry.bars)
    tendons_mm2 = _original_reinforcement_rows(
        inp, "tendons", blocks.geometry.tendons)
    rows = element_rows(
        bars_mm2,
        tendons_mm2,
        total=total,
        long=long,
        dif=dif,
        rst1=rst1,
        es_mpa=list(moduli[:len(blocks.bars)]),
        ep_mpa=list(moduli[len(blocks.bars):]) if blocks.tendons else None,
        bar_ids=bar_ids,
        tendon_ids=tendon_ids,
        bar_material_ids=bar_material_ids,
        tendon_material_ids=tendon_material_ids,
        bar_material_names=[mild_names[value] for value in bar_material_ids],
        tendon_material_names=[prestress_names[value] for value in tendon_material_ids],
    )
    governing = max(rows, key=lambda row: row["total_mpa"]) if rows else None
    if governing is not None and governing["total_mpa"] <= 0.0:
        governing = None
    if locked is None:
        pre_resultant = None
    else:
        bx, by, ba = section.bar_arrays()
        forces = locked * ba
        pre_resultant = (
            float(forces.sum()),
            float((forces * by).sum()),
            float((forces * bx).sum()),
        )
    props_un = transformed_properties(
        section, scalars["nl"], cracked=False,
        n_mult=n_mult if n_mult.size else None,
    )
    props_cr = (
        transformed_properties(
            section,
            scalars["nl"],
            eps0=governing_state.eps0,
            kx=governing_state.kx,
            ky=governing_state.ky,
            cracked=True,
            n_mult=n_mult if n_mult.size else None,
        )
        if cracked else None
    )
    expected: dict[str, Any] = {
        "total": list(total),
        "long": list(long),
        "dif": list(dif),
        "rst1": list(rst1),
        "max_conc": combined.max_concrete_compression / 1000.0,
        "max_conc_xy": tuple(combined.short_term.max_concrete_xy),
        "max_conc_point": int(combined.max_concrete_point) + 1,
        "na_x": combined.na_x_intercept,
        "na_y": combined.na_y_intercept,
        "max_steel": governing["total_mpa"] if governing else 0.0,
        "max_steel_bar": int(np.argmax(total)) + 1 if governing else 0,
        "max_steel_type": governing["element_type"] if governing else None,
        "max_steel_element": governing["element_id"] if governing else None,
        "prestress": pre_resultant,
        "converged": converged,
        "stress_plane": tuple(combined.short_term.strain_plane),
        "elements": rows,
        "concrete_corners": concrete_corner_rows(
            blocks.geometry.rings[0],
            blocks.geometry.rings[1:],
            stress_plane=combined.short_term.strain_plane,
            ec_mpa=_number(inp.get("conc_Ec"), "conc_Ec", positive=True) * 1000.0,
        ),
        "stress_outputs": stress_outputs(
            total,
            n_bars=len(blocks.bars),
            max_concrete_compression=combined.max_concrete_compression / 1000.0,
            valid=converged,
            bar_ids=bar_ids,
            tendon_ids=tendon_ids,
        ),
        "cracked": cracked,
        "lambda_cr": factor,
        "sigma_ct": sigma_ct,
        "fctm": scalars["sls_fctm"],
        "show_cw": True,
        "props_un": _props_dict(props_un),
        "props_cr": _props_dict(props_cr) if props_cr is not None else None,
        "crack": None,
        "crack_short": None,
    }

    cw_stress = np.asarray(combined.bar_stress_total, dtype=float)
    if locked is not None:
        cw_stress = cw_stress - locked
    short_state = dataclasses.replace(combined.short_term, bar_stress=cw_stress)
    results: dict[str, Any | None] = {}
    if cracked:
        def evaluate(state: Any, ratio: float, kt: float, coarse: bool) -> Any | None:
            return crack_width(
                section,
                state,
                ratio,
                fctm=scalars["sls_fctm"],
                Es=moduli,
                kt=kt,
                bar_diameter=diameters,
                k1=k1_values,
                k3_cover_dependent=dk,
                include_hx_term=include_hx,
                coarse=coarse,
                edition="2004",
                n_mult=n_mult if n_mult.size else None,
                reinforcement_types=kinds,
                bond_ratio_xi=tendon_xi,
            )

        results[CASE_LONG_FINE] = evaluate(
            long_analysis.cracked_state, scalars["nl"], 0.4, False)
        results[CASE_SHORT_FINE] = evaluate(
            short_state, scalars["ns"], 0.6, False)
        expected["crack"] = _crack_dict(
            results[CASE_LONG_FINE], bar_ids, tendon_ids)
        expected["crack_short"] = _crack_dict(
            results[CASE_SHORT_FINE], bar_ids, tendon_ids)
        expected.update({
            "crack_code": _text(inp.get("sls_code"), "sls_code"),
            "crack_edition": "2004",
            "crack_member": member if dk else None,
        })
        if dk:
            results[CASE_LONG_COARSE] = evaluate(
                long_analysis.cracked_state, scalars["nl"], 0.4, True)
            results[CASE_SHORT_COARSE] = evaluate(
                short_state, scalars["ns"], 0.6, True)
            expected["crack_coarse"] = _crack_dict(
                results[CASE_LONG_COARSE], bar_ids, tendon_ids)
            expected["crack_short_coarse"] = _crack_dict(
                results[CASE_SHORT_COARSE], bar_ids, tendon_ids)
    case_pairs = tuple(
        (case_id, results.get(case_id))
        for case_id in CASE_ORDER
        if case_id in results
    )
    if (
        expected.get("crack_coarse") is not None
        or expected.get("crack_short_coarse") is not None
    ):
        aggregate_cases = {
            CASE_LABELS[case_id]: expected.get(CASE_OUTPUT_KEYS[case_id])
            for case_id in CASE_ORDER
        }
    else:
        aggregate_cases = {
            "Long-term": expected.get("crack"),
            "Short-term": expected.get("crack_short"),
        }
    expected[AGGREGATE_KEY] = crack_outputs(aggregate_cases, valid=converged)
    candidate = _mapping(out.get("elastic"), "CT-009 candidate elastic result")
    _validate_payload_inventories(candidate, dk)
    if converged:
        _compare_exact(candidate, expected, "elastic")
    else:
        _compare_shape(candidate, expected, "elastic")
        if candidate["converged"] is not False:
            raise TraceValidationError(
                "non-converged CT-009 replay needs candidate converged=false")
        _compare_exact(
            candidate[AGGREGATE_KEY], expected[AGGREGATE_KEY],
            "elastic.crack_output")
    return _Replay(
        blocks=blocks,
        section=section,
        expected_elastic=expected,
        combined=combined,
        long_state=long_analysis.cracked_state,
        short_state=short_state,
        cases=case_pairs,
        moduli=moduli,
        n_mult=n_mult,
        locked=locked,
        diameters=diameters,
        k1_values=k1_values,
        include_hx=include_hx,
        dk=dk,
        cracked=bool(cracked),
        converged=converged,
    )


def _freeze(value: Any, active: set[int] | None = None) -> Any:
    """Return an injective typed identity for retained JSON-like input values."""

    active = set() if active is None else active
    if value is None:
        return ("none",)
    if type(value) is bool:
        return ("bool", value)
    if type(value) is int:
        return ("int", str(value))
    if type(value) is float:
        return ("float", value.hex())
    if type(value) is str:
        return ("str", value)
    marker = id(value)
    if marker in active:
        raise TraceValidationError("cyclic CT-009 identity value")
    if isinstance(value, Mapping):
        active.add(marker)
        try:
            return (
                "mapping",
                tuple((_freeze(key, active), _freeze(item, active))
                      for key, item in value.items()),
            )
        finally:
            active.remove(marker)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        active.add(marker)
        try:
            return ("sequence", tuple(_freeze(item, active) for item in value))
        finally:
            active.remove(marker)
    raise TraceValidationError(
        f"unsupported CT-009 identity type {type(value).__qualname__}")


def _identity_words(value: Any) -> tuple[float, ...]:
    payload = repr(_freeze(value)).encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return tuple(float(int.from_bytes(digest[index:index + 4], "big"))
                 for index in range(0, 32, 4))


class _Builder:
    def __init__(self) -> None:
        self.steps: list[TraceStep] = []
        self.units: dict[str, Any] = {}

    def add(
        self,
        step_id: str,
        title: str,
        value: float | None,
        unit: Any,
        role: str,
        source: Any,
        dependencies: Sequence[str] = (),
        *,
        expression: str,
        result: TraceResult | None = None,
        assumptions: tuple[str, ...] = (),
    ) -> str:
        if step_id in self.units:
            raise TraceValidationError(f"duplicate internal CT-009 step {step_id}")
        dependencies = tuple(dict.fromkeys(dependencies))
        if result is None:
            if value is None or not math.isfinite(float(value)):
                raise TraceValidationError(
                    f"finite CT-009 step {step_id} lacks a finite value")
            result = TraceResult(RESULT_FINITE, float(value))
            substituted = f"{step_id} = {format(float(value), '.17g')} {unit.symbol}"
        else:
            substituted = f"{step_id} = {result.state}"
        self.steps.append(TraceStep(
            step_id=step_id,
            title=title,
            dependencies=tuple(
                TraceDependency(dep, self.units[dep]) for dep in dependencies
            ),
            quantity_role=role,
            source=source,
            symbol=step_id,
            unit=unit,
            actual_expression=expression,
            substituted_expression=substituted,
            result=result,
            assumptions=assumptions,
        ))
        self.units[step_id] = unit
        return step_id

    def identity(
        self, prefix: str, title: str, value: Any, source: Any = INPUT,
    ) -> tuple[str, ...]:
        ids = []
        for index, word in enumerate(_identity_words(value), start=1):
            ids.append(self.add(
                f"{prefix}-sha256-{index:02d}",
                f"{title} identity word {index}",
                word,
                ONE,
                ROLE_USER_INPUT if source == INPUT else ROLE_METHOD_VALUE,
                source,
                expression="SHA-256 word over exact typed ordered identity",
            ))
        return tuple(ids)


def _selected_catalog_items(
    inp: Mapping[str, Any], key: str, selected_ids: set[str],
) -> tuple[Mapping[str, Any], ...]:
    catalog = _mapping(inp.get(key), key)
    items = _sequence(catalog.get("items"), f"{key}.items")
    selected = tuple(
        _mapping(item, f"{key}.items")
        for item in items
        if isinstance(item, Mapping) and item.get("id") in selected_ids
    )
    if {item.get("id") for item in selected} != selected_ids:
        raise TraceValidationError(f"{key} lacks a selected material identity")
    return selected


def _input_graph(
    builder: _Builder, inp: Mapping[str, Any], replay: _Replay,
) -> _InputGraph:
    controls = []
    for key, numeric in (
        ("mode-elastic-active", 1.0),
        ("crack-width-requested", 1.0),
        ("dk-na-selected", 1.0 if replay.dk else 0.0),
        ("include-hx-term", 1.0 if replay.include_hx else 0.0),
    ):
        controls.append(builder.add(
            key, key.replace("-", " ").title(), numeric, ONE,
            ROLE_USER_INPUT, INPUT,
            expression="Exact CT-009 dispatch input",
        ))
    identities = []
    for prefix, label, value in (
        ("input-mode", "Analysis mode", inp["mode"]),
        ("input-edition", "Crack method edition", inp["sls_edition"]),
        ("input-code", "Project-selected crack code", inp["sls_code"]),
        ("input-member", "Project-selected member type", inp["sls_member"]),
        ("input-concrete-material-id", "Concrete material ID",
         inp.get("concrete_material_id")),
        ("input-bars", "Original bar x/y/area records", inp.get("bars", ())),
        ("input-tendons", "Original tendon x/y/area records",
         inp.get("tendons", ())),
    ):
        identities.extend(builder.identity(prefix, label, value))

    scalar_ids: dict[str, str] = {}
    for key in _SCALAR_KEYS:
        scalar_ids[key] = builder.add(
            f"input-{key.replace('_', '-')}",
            key,
            _number(inp.get(key), key),
            STRESS if key == "sls_fctm" else MM if key == "sls_phi" else ONE,
            ROLE_USER_INPUT,
            INPUT,
            expression="Exact retained crack-width scalar input",
        )
    action_ids: dict[str, str] = {}
    for key in _ACTION_KEYS:
        unit = FORCE if key.startswith("P_") else MOMENT
        action_ids[key] = builder.add(
            f"input-{key.lower().replace('_', '-')}",
            key,
            _number(inp.get(key), key),
            unit,
            ROLE_USER_INPUT,
            INPUT,
            expression="Exact retained elastic action input in app units",
        )
    ec_id = builder.add(
        "input-concrete-modulus", "Concrete elastic modulus",
        _number(inp.get("conc_Ec"), "conc_Ec", positive=True),
        TraceUnit("GPa", "stress"), ROLE_USER_INPUT, INPUT,
        expression="Exact retained concrete elastic modulus",
    )

    geometry_ids = []
    for ring_index, ring in enumerate(replay.blocks.geometry.rings):
        for point_index, (x, y) in enumerate(ring):
            geometry_ids.append(builder.add(
                f"geometry-ring-{ring_index:03d}-point-{point_index:04d}-x",
                "Concrete ring vertex x", x, LENGTH, ROLE_USER_INPUT, INPUT,
                expression="Exact immutable concrete-ring coordinate",
            ))
            geometry_ids.append(builder.add(
                f"geometry-ring-{ring_index:03d}-point-{point_index:04d}-y",
                "Concrete ring vertex y", y, LENGTH, ROLE_USER_INPUT, INPUT,
                expression="Exact immutable concrete-ring coordinate",
            ))
    element_ids = []
    for kind, elements in (
        ("bar", replay.blocks.geometry.bars),
        ("tendon", replay.blocks.geometry.tendons),
    ):
        for index, element in enumerate(elements):
            x_id = builder.add(
                f"geometry-{kind}-{index:04d}-x", f"{kind} x",
                element.x, LENGTH, ROLE_USER_INPUT, INPUT,
                expression="Exact immutable reinforcement coordinate",
            )
            y_id = builder.add(
                f"geometry-{kind}-{index:04d}-y", f"{kind} y",
                element.y, LENGTH, ROLE_USER_INPUT, INPUT,
                expression="Exact immutable reinforcement coordinate",
            )
            area_id = builder.add(
                f"geometry-{kind}-{index:04d}-area", f"{kind} area",
                element.area, AREA, ROLE_USER_INPUT, INPUT,
                expression="Exact immutable reinforcement area",
            )
            geometry_ids.extend((x_id, y_id, area_id))
            element_ids.append((x_id, y_id, area_id))
    geometry_vector = builder.add(
        "immutable-geometry-vector", "Complete immutable section geometry",
        1.0, ONE, ROLE_COMPUTED, IDENTITY, geometry_ids,
        expression="Bind every ring vertex and reinforcement x/y/area leaf",
    )

    all_materials = (
        replay.blocks.concrete, *replay.blocks.bars, *replay.blocks.tendons)
    material_ids = []
    modulus_ids = []
    for index, material in enumerate(all_materials):
        prefix = f"material-{material.kind}-{index:04d}"
        material_ids.extend(builder.identity(
            f"{prefix}-element-id", f"{material.kind} element ID",
            material.element_id))
        material_ids.extend(builder.identity(
            f"{prefix}-material-id", f"{material.kind} material ID",
            material.material_id))
        for name, value in material.values:
            unit = STRESS if name == "Es" or name.startswith("f") else ONE
            value_id = builder.add(
                f"{prefix}-law-{trace_identity_token(name)}",
                f"{material.kind} law {name}", value, unit,
                ROLE_METHOD_VALUE, material.provenance.source,
                expression="Exact aligned selected material-law value",
            )
            material_ids.append(value_id)
            if material.kind in {"bar", "tendon"} and name == "Es":
                modulus_ids.append(value_id)
    material_vector = builder.add(
        "immutable-material-vector", "Complete aligned material identity and laws",
        1.0, ONE, ROLE_COMPUTED, IDENTITY, material_ids,
        expression="Bind selected material IDs and every aligned law leaf",
    )

    records = (
        *_element_records(inp, "bar_elements"),
        *_element_records(inp, "tendon_elements"),
    )
    identities.extend(builder.identity(
        "input-element-records", "Complete crack element records", records))
    selected_bar_ids = {item.material_id for item in replay.blocks.bars}
    selected_tendon_ids = {item.material_id for item in replay.blocks.tendons}
    identities.extend(builder.identity(
        "input-selected-mild-catalog", "Selected mild catalog records",
        _selected_catalog_items(inp, "mild_material_catalog", selected_bar_ids)))
    identities.extend(builder.identity(
        "input-selected-prestress-catalog", "Selected prestress catalog records",
        _selected_catalog_items(
            inp, "prestress_material_catalog", selected_tendon_ids)))
    diameter_ids = []
    for index, diameter in enumerate(replay.diameters):
        diameter_ids.append(builder.add(
            f"input-element-{index:04d}-diameter", "Element diameter",
            diameter, MM, ROLE_USER_INPUT, INPUT,
            expression="Exact override or retained per-element diameter",
        ))
    final_deps = (
        *controls, *identities, *scalar_ids.values(), *action_ids.values(),
        ec_id, geometry_vector, material_vector, *diameter_ids,
    )
    final_id = builder.add(
        "complete-crack-input-vector", "Complete CT-009 input identity",
        1.0, ONE, ROLE_COMPUTED, IDENTITY, final_deps,
        expression="Bind complete branch-specific crack-width input inventory",
    )
    return _InputGraph(
        final_id,
        tuple(geometry_ids),
        tuple(material_ids),
        scalar_ids,
        action_ids,
        tuple(element_ids),
        tuple(modulus_ids),
        tuple(diameter_ids),
    )


def _case_calculation(
    inp: Mapping[str, Any], replay: _Replay, case_id: str, result: Any,
    context: Mapping[str, Any],
) -> TraceCalculation:
    builder = _Builder()
    graph = _input_graph(builder, inp, replay)
    short = case_id in {CASE_SHORT_FINE, CASE_SHORT_COARSE}
    coarse = case_id in {CASE_LONG_COARSE, CASE_SHORT_COARSE}
    state = replay.short_state if short else replay.long_state
    plane_source = CT005 if short else LONG_REPLAY
    plane_ids = (
        builder.add(
            f"{case_id}-state-eps0", "Cracked state plane offset",
            state.eps0, RAW_STRESS, ROLE_COMPUTED, plane_source,
            (graph.final_id,),
            expression="Accepted cracked-state stress-plane component",
        ),
        builder.add(
            f"{case_id}-state-kx", "Cracked state x gradient",
            state.kx, RAW_GRADIENT, ROLE_COMPUTED, plane_source,
            (graph.final_id,),
            expression="Accepted cracked-state stress-plane component",
        ),
        builder.add(
            f"{case_id}-state-ky", "Cracked state y gradient",
            state.ky, RAW_GRADIENT, ROLE_COMPUTED, plane_source,
            (graph.final_id,),
            expression="Accepted cracked-state stress-plane component",
        ),
    )
    gx, gy, magnitude = _depth_axis(state.kx, state.ky)
    gx_id = builder.add(
        f"{case_id}-depth-axis-x", "Tension depth-axis x component",
        gx, ONE, ROLE_COMPUTED, plane_source, plane_ids[1:],
        expression="gx = kx / hypot(kx, ky)",
    )
    gy_id = builder.add(
        f"{case_id}-depth-axis-y", "Tension depth-axis y component",
        gy, ONE, ROLE_COMPUTED, plane_source, plane_ids[1:],
        expression="gy = ky / hypot(kx, ky)",
    )
    mag_id = builder.add(
        f"{case_id}-depth-axis-magnitude", "Stress-gradient magnitude",
        magnitude, RAW_GRADIENT, ROLE_COMPUTED, plane_source, plane_ids[1:],
        expression="magnitude = hypot(kx, ky)",
    )
    vertices = replay.section.concrete_vertices()
    projections = vertices[:, 0] * gx + vertices[:, 1] * gy
    tension_id = builder.add(
        f"{case_id}-tension-face", "Tension-face depth coordinate",
        float(projections.max()), LENGTH, ROLE_COMPUTED, plane_source,
        (*graph.geometry_ids, gx_id, gy_id),
        expression="s_t = max_vertices(x gx + y gy)",
    )
    compression_id = builder.add(
        f"{case_id}-compression-face", "Compression-face depth coordinate",
        float(projections.min()), LENGTH, ROLE_COMPUTED, plane_source,
        (*graph.geometry_ids, gx_id, gy_id),
        expression="s_c = min_vertices(x gx + y gy)",
    )
    depth_id = builder.add(
        f"{case_id}-section-depth", "Section depth on crack axis",
        float(projections.max() - projections.min()), LENGTH,
        ROLE_COMPUTED, plane_source, (tension_id, compression_id),
        expression="h = s_t - s_c",
    )
    neutral_id = builder.add(
        f"{case_id}-neutral-axis", "Neutral-axis depth coordinate",
        -state.eps0 / magnitude, LENGTH, ROLE_COMPUTED, plane_source,
        (plane_ids[0], mag_id),
        expression="s_na = -eps0 / magnitude",
    )
    area_source = DK_COARSE if coarse else (
        DK_EFFECTIVE_AREA if replay.dk and not replay.include_hx else EFFECTIVE_AREA)
    hc_id = builder.add(
        f"{case_id}-effective-height", "Effective tension height",
        result.hc_ef, LENGTH, ROLE_COMPUTED, area_source,
        (depth_id, tension_id, neutral_id, graph.final_id),
        expression=(
            "Centroid-matched tension band from actual rings"
            if coarse else
            "hc,ef = min(2.5(h-d), (h-x)/3 when applicable, h/2)"
        ),
    )
    ac_id = builder.add(
        f"{case_id}-effective-concrete-area", "Effective concrete tension area",
        result.ac_eff, AREA, ROLE_COMPUTED, area_source,
        (*graph.geometry_ids, gx_id, gy_id, hc_id),
        expression="Clip every actual concrete ring to the effective tension band",
    )
    rho_id = builder.add(
        f"{case_id}-effective-reinforcement-ratio",
        "Effective reinforcement ratio", result.rho_p_eff, ONE,
        ROLE_COMPUTED, area_source,
        (ac_id, *[item[2] for item in graph.element_ids]),
        expression="rho_p,eff = sum(A_s in actual effective band) / Ac,eff",
    )
    candidate_ids = []
    for position, candidate in enumerate(result.candidates):
        prefix = f"{case_id}-candidate-{position:04d}"
        element_index = candidate.bar_index
        x_id, y_id, area_id = graph.element_ids[element_index]
        sigma_id = builder.add(
            f"{prefix}-steel-stress", "Candidate Stage II steel stress",
            candidate.sigma_s, STRESS, ROLE_COMPUTED, plane_source,
            (*plane_ids, x_id, y_id, graph.final_id),
            expression=(
                "CT-005 total stress minus locked tendon prestress"
                if short else "Long-term cracked-state stress replay"
            ),
        )
        phi_id = builder.add(
            f"{prefix}-diameter", "Candidate diameter", candidate.phi, MM,
            ROLE_COMPUTED, IDENTITY,
            (graph.diameter_ids[element_index], area_id),
            expression="Retained positive diameter or area-equivalent diameter",
        )
        cover_id = builder.add(
            f"{prefix}-cover", "Candidate clear cover", candidate.cover, MM,
            ROLE_COMPUTED, SELECTOR,
            (*graph.geometry_ids, x_id, y_id, phi_id),
            expression="Nearest actual concrete boundary distance minus bar radius",
        )
        strain_id = builder.add(
            f"{prefix}-mean-strain-difference",
            "Mean reinforcement-concrete strain difference",
            candidate.esm_ecm, ONE, ROLE_COMPUTED, MEAN_STRAIN,
            (
                sigma_id, rho_id, graph.scalar_ids["sls_fctm"],
                graph.modulus_ids[element_index], graph.final_id,
            ),
            expression=(
                "max((sigma_s - kt fctm/rho (1 + alpha_e rho))/Es, "
                "0.6 sigma_s/Es)"
            ),
        )
        branch_id = builder.add(
            f"{prefix}-geometric-spacing-branch",
            "Geometric crack-spacing branch selected",
            1.0 if candidate.sr_max_geometric else 0.0,
            ONE, ROLE_COMPUTED, SELECTOR,
            (cover_id, phi_id, *graph.geometry_ids),
            expression="Nearest in-band neighbour exceeds 5(c + phi/2)",
        )
        spacing_source = (
            SPACING_GEOMETRIC if candidate.sr_max_geometric else SPACING_CLOSE)
        if replay.dk and not candidate.sr_max_geometric:
            k3_id = builder.add(
                f"{prefix}-dk-cover-coefficient",
                "DK cover-dependent k3 coefficient",
                3.4 * (25.0 / candidate.cover) ** (2.0 / 3.0)
                if candidate.cover > 0.0 else 3.4,
                ONE, ROLE_COMPUTED, DK_COVER, (cover_id,),
                expression="k3 = 3.4 (25/c)^(2/3)",
            )
            spacing_deps = (branch_id, cover_id, phi_id, rho_id, k3_id)
        else:
            spacing_deps = (branch_id, cover_id, phi_id, rho_id)
        spacing_id = builder.add(
            f"{prefix}-crack-spacing", "Candidate crack spacing",
            candidate.sr_max, MM, ROLE_COMPUTED, spacing_source,
            spacing_deps,
            expression=(
                "sr,max = 1.3(h-x)" if candidate.sr_max_geometric
                else "sr,max = k3 c + k1 k2 k4 phi / rho_p,eff"
            ),
        )
        if coarse:
            coarse_id = builder.add(
                f"{prefix}-coarse-factor", "DK coarse crack-width factor",
                0.5, ONE, ROLE_COMPUTED, DK_COARSE,
                (ac_id, rho_id), expression="coarse-system wk factor = 0.5",
            )
            width_deps = (spacing_id, strain_id, coarse_id)
        else:
            width_deps = (spacing_id, strain_id)
        width_id = builder.add(
            f"{prefix}-crack-width", "Candidate crack width",
            candidate.wk, MM, ROLE_COMPUTED, CRACK_WIDTH,
            width_deps, expression="wk = sr,max (epsilon_sm - epsilon_cm)",
        )
        candidate_ids.append(builder.add(
            f"{prefix}-result", "Complete candidate crack-width result",
            candidate.wk, MM, ROLE_COMPUTED, SELECTOR,
            (
                width_id, sigma_id, phi_id, cover_id, rho_id, ac_id, hc_id,
                x_id, y_id, area_id, graph.final_id,
            ),
            expression="Bind complete independently reconstructed candidate",
        ))
    final_id = f"{case_id}-crack-width-result"
    builder.add(
        final_id,
        f"{CASE_LABELS[case_id]} crack width",
        result.wk,
        MM,
        ROLE_FINAL,
        SELECTOR,
        (*candidate_ids, graph.final_id, ac_id, rho_id),
        expression="Select maximum wk; ties use lowest original element index",
        assumptions=(
            "This crack width is an output quantity only; no allowable-width or compliance verdict is implied.",
            "The dominant-direction retained method does not publish a multidirectional crack overlay.",
        ),
    )
    return TraceCalculation(
        calculation_id=f"ct-009-{context_id(context)}-{case_id}",
        coverage_id=COVERAGE_ID,
        title=f"CT-009 {CASE_LABELS[case_id]} crack width",
        method_id=METHOD_ID,
        axes=context_axes(
            context,
            crack_case=case_id,
            edition="2004",
            national_annex="dk" if replay.dk else "base",
        ),
        final_step_id=final_id,
        steps=tuple(builder.steps),
        assumptions=(
            "Long-term Stage II mechanics are replayed from original inputs; short-term combined response is bound as CT-005 upstream evidence.",
            "Concrete rings, voids and every reinforcement element are retained in their exact insertion order.",
        ),
    )


def _aggregate_calculation(
    inp: Mapping[str, Any], replay: _Replay, context: Mapping[str, Any],
) -> tuple[TraceCalculation, str]:
    builder = _Builder()
    graph = _input_graph(builder, inp, replay)
    aggregate = replay.expected_elastic[AGGREGATE_KEY]
    state = aggregate["calculation_state"]
    if state == "INVALID":
        result_state = RESULT_FAILED
        reason = "The retained elastic/crack analysis is non-converged."
    elif state == "NOT APPLICABLE":
        result_state = RESULT_UNDEFINED
        reason = "No calculated crack width is applicable to the retained state."
    elif state == "CALCULATED":
        result_state = RESULT_FINITE
        reason = None
    else:
        raise TraceValidationError("unknown retained crack calculation state")
    case_ids = []
    for case_id, result in replay.cases:
        if result is None:
            continue
        case_ids.append(builder.add(
            f"aggregate-{case_id}-width", f"{CASE_LABELS[case_id]} width",
            result.wk, MM, ROLE_COMPUTED, SELECTOR,
            (graph.final_id,),
            expression="Independently reconstructed CT-009 case final",
        ))
    identity_ids = builder.identity(
        "aggregate-retained-output", "Exact retained aggregate output",
        aggregate, IDENTITY)
    final_id = "aggregate-crack-width-result"
    value = float(aggregate["value"]) if result_state == RESULT_FINITE else None
    builder.add(
        final_id,
        "Aggregate retained crack-width output",
        value,
        MM,
        ROLE_FINAL,
        SELECTOR,
        (graph.final_id, *case_ids, *identity_ids),
        expression="Select maximum available case width in retained insertion order",
        result=(
            None if result_state == RESULT_FINITE
            else TraceResult(result_state, None, reason)
        ),
        assumptions=(
            "The aggregate is an output quantity only and is not an engineering compliance verdict.",
        ),
    )
    calculation = TraceCalculation(
        calculation_id=f"ct-009-{context_id(context)}-aggregate",
        coverage_id=COVERAGE_ID,
        title="CT-009 aggregate crack-width output",
        method_id=METHOD_ID,
        axes=context_axes(
            context,
            crack_case="aggregate",
            edition="2004",
            national_annex="dk" if replay.dk else "base",
        ),
        final_step_id=final_id,
        steps=tuple(builder.steps),
    )
    return calculation, result_state


def _expected_bundle(
    inp: Mapping[str, Any], out: Mapping[str, Any], *,
    input_sha256: str, result_sha256: str,
    context: Mapping[str, Any] | None,
) -> TraceBundle | None:
    inp = _mapping(inp, "CT-009 input")
    out = _mapping(out, "analysis result")
    mode = _text(inp.get("mode"), "mode")
    enabled = _boolean(inp.get("sls_cw"), "sls_cw")
    edition = _text(inp.get("sls_edition"), "sls_edition")
    _boolean(inp.get("sls_dk_na"), "sls_dk_na")
    if mode not in {"Elastic", "Both"} or not enabled:
        return None
    if edition != "2004":
        return None
    trace_context = {} if context is None else _mapping(context, "CT-009 context")
    replay = _replay(inp, out)
    calculations = []
    shapes = []
    if replay.converged and replay.cracked:
        for case_id, result in replay.cases:
            if result is None:
                continue
            calculation = _case_calculation(
                inp, replay, case_id, result, trace_context)
            calculations.append(calculation)
            shapes.append(MemberShape(case_id, calculation, RESULT_FINITE))
    aggregate, aggregate_state = _aggregate_calculation(inp, replay, trace_context)
    calculations.append(aggregate)
    shapes.append(MemberShape("aggregate", aggregate, aggregate_state))
    bundle = create_bundle(
        input_sha256=input_sha256,
        result_sha256=result_sha256,
        calculations=tuple(calculations),
    )
    audit_trace_registry(bundle, registry_for(tuple(shapes)))
    return bundle


def build_crack_trace_family(
    inp: Mapping[str, Any], out: Mapping[str, Any], *,
    input_sha256: str, result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle | None:
    """Build one sealed exact CT-009 family, or ``None`` when inactive."""

    try:
        return _expected_bundle(
            inp, out, input_sha256=input_sha256,
            result_sha256=result_sha256, context=context)
    except TraceValidationError:
        raise
    except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"invalid CT-009 evidence: {exc}") from exc


def validate_crack_trace_family(
    bundle: TraceBundle | dict[str, Any],
    inp: Mapping[str, Any], out: Mapping[str, Any], *,
    input_sha256: str, result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle:
    """Reject stale, incomplete, reordered, or coherently resealed CT-009 data."""

    candidate = validate_bundle(
        bundle,
        expected_input_sha256=input_sha256,
        expected_result_sha256=result_sha256,
    )
    expected = _expected_bundle(
        inp, out, input_sha256=input_sha256,
        result_sha256=result_sha256, context=context)
    if expected is None:
        raise TraceValidationError("CT-009 trace is not applicable")
    shapes = tuple(
        MemberShape(
            "aggregate" if calculation.calculation_id.endswith("-aggregate")
            else next(
                case_id for case_id in CASE_ORDER
                if calculation.calculation_id.endswith(f"-{case_id}")
            ),
            calculation,
            calculation.steps[-1].result.state,
        )
        for calculation in expected.calculations
    )
    audit_trace_registry(candidate, registry_for(shapes))
    if candidate.to_dict() != expected.to_dict():
        raise TraceValidationError(
            "CT-009 trace differs from authoritative input/output replay")
    return candidate
