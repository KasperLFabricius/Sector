"""Authoritative input replay and candidate-output checks for CT-005."""

from __future__ import annotations

import math
import numbers
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from .calculation_trace import (
    RESULT_FAILED,
    RESULT_NEGATIVE_INFINITY,
    RESULT_POSITIVE_INFINITY,
    RESULT_UNDEFINED,
    TraceResult,
    TraceValidationError,
    trace_identity_token,
)
from .elastic import (
    _concrete_moments,
    solve_elastic_combined,
    solve_elastic_uncracked,
    transformed_properties,
)
from .elastic_trace_contract import (
    ACTION_KEYS,
    BRANCH_FAILED,
    BRANCH_FINITE,
    BRANCH_INFINITE,
    PROPERTY_FIELDS,
    action_step_id,
    expected_step_contract,
    geometry_point_ids,
    material_prefix,
    scalar_step_id,
    trace_shape,
)
from .section import Bar, Section
from .section_trace_blocks import SectionTraceBlocks, section_trace_blocks
from .sls import concrete_corner_rows, element_rows, stress_outputs


STEEL_REFERENCE_MODULUS = 200_000.0
_TENSION_TOLERANCE_MPA = 1.0e-9
_PLASTIC_ACTION_KEYS = frozenset(("P_pl", "Mx_pl", "My_pl"))
_FAILURE_REASON = (
    "The authoritative elastic reconstruction did not produce a complete finite "
    "solver state; no numerical response or cracking factor is published."
)


def _ct005_blocks(inp: Mapping[str, Any]) -> SectionTraceBlocks:
    """Build shared blocks without reading actions outside the CT-005 family."""

    elastic_input = {
        key: value for key, value in inp.items() if key not in _PLASTIC_ACTION_KEYS
    }
    return section_trace_blocks(elastic_input)


@dataclass(frozen=True, slots=True)
class ReplayEvidence:
    blocks: SectionTraceBlocks
    shape: Any
    values: dict[str, float]
    states: dict[str, TraceResult]
    warnings: tuple[str, ...]


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TraceValidationError(f"{label} must be a mapping")
    return value


def _sequence(value: Any, label: str) -> tuple[Any, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TraceValidationError(f"{label} must be an aligned sequence")
    return tuple(value)


def _number(value: Any, label: str) -> float:
    if type(value) not in {int, float} or type(value) is bool:
        raise TraceValidationError(f"{label} must be a finite non-Boolean number")
    converted = float(value)
    if not math.isfinite(converted):
        raise TraceValidationError(f"{label} must be a finite non-Boolean number")
    return converted


def _close(actual: float, expected: float) -> bool:
    return abs(actual - expected) <= 1.0e-9 * max(1.0, abs(expected))


def _compare(actual: Any, expected: Any, label: str) -> None:
    """Compare the retained output subset without trusting candidate selections."""

    if isinstance(expected, Mapping):
        candidate = _mapping(actual, label)
        missing = [key for key in expected if key not in candidate]
        if missing:
            raise TraceValidationError(
                f"{label} is missing {', '.join(str(key) for key in missing)}"
            )
        for key, value in expected.items():
            _compare(candidate[key], value, f"{label}.{key}")
        return
    if isinstance(expected, (tuple, list)):
        candidate = _sequence(actual, label)
        if len(candidate) != len(expected):
            raise TraceValidationError(
                f"{label} has {len(candidate)} entries; expected {len(expected)}"
            )
        for index, (got, wanted) in enumerate(zip(candidate, expected)):
            _compare(got, wanted, f"{label}[{index}]")
        return
    if expected is None or type(expected) in {bool, str}:
        if actual != expected or type(actual) is not type(expected):
            raise TraceValidationError(f"{label} differs from authoritative replay")
        return
    if type(expected) is int:
        if type(actual) is not int or type(actual) is bool or actual != expected:
            raise TraceValidationError(f"{label} differs from authoritative replay")
        return
    if not isinstance(actual, numbers.Real) or isinstance(actual, (bool, np.bool_)):
        raise TraceValidationError(f"{label} must be numerical")
    got = float(actual)
    wanted = float(expected)
    if math.isnan(got):
        raise TraceValidationError(f"{label} must not be NaN")
    if math.isinf(wanted):
        if not math.isinf(got) or math.copysign(1.0, got) != math.copysign(1.0, wanted):
            raise TraceValidationError(f"{label} has the wrong explicit infinity")
    elif not math.isfinite(got) or not _close(got, wanted):
        raise TraceValidationError(f"{label} differs from authoritative replay")


def _law_value(material: Any, name: str) -> float:
    values = dict(material.values)
    if name not in values:
        raise TraceValidationError(
            f"assigned {material.kind} law lacks elastic value {name}"
        )
    return _number(values[name], f"{material.kind} {material.element_id} {name}")


def _folded_section(blocks: SectionTraceBlocks) -> Section:
    bars = [
        Bar(item.x, item.y, item.area)
        for item in (*blocks.geometry.bars, *blocks.geometry.tendons)
    ]
    return Section(
        [np.asarray(ring, dtype=float) for ring in blocks.geometry.rings],
        bars=bars,
    )


def _input_state(
    inp: Mapping[str, Any], blocks: SectionTraceBlocks
) -> tuple[dict[str, float], float, float, np.ndarray, np.ndarray | None]:
    values: dict[str, float] = {}
    actions = {key: _number(inp.get(key, 0.0), key) for key in ACTION_KEYS}
    for key, value in actions.items():
        values[action_step_id(key)] = value

    ec_gpa = _number(inp.get("conc_Ec"), "conc_Ec")
    phi = _number(inp.get("el_phi", 0.0), "el_phi")
    fctm = _number(inp.get("sls_fctm"), "sls_fctm")
    if ec_gpa <= 0.0:
        raise TraceValidationError("conc_Ec must be positive")
    if phi < 0.0:
        raise TraceValidationError("el_phi must be non-negative")
    if fctm < 0.0:
        raise TraceValidationError("sls_fctm must be non-negative")
    values[scalar_step_id("conc_Ec")] = ec_gpa
    values[scalar_step_id("el_phi")] = phi
    values[scalar_step_id("sls_fctm")] = fctm
    values["reference-steel-modulus"] = STEEL_REFERENCE_MODULUS

    for ring_index, ring in enumerate(blocks.geometry.rings):
        for point_index, (x, y) in enumerate(ring):
            x_id, y_id = geometry_point_ids(ring_index, point_index)
            values[x_id] = x
            values[y_id] = y
    for kind, elements in (
        ("bar", blocks.geometry.bars),
        ("tendon", blocks.geometry.tendons),
    ):
        for index, element in enumerate(elements):
            prefix = f"geometry-{kind}-{index:04d}"
            values[f"{prefix}-x"] = element.x
            values[f"{prefix}-y"] = element.y
            values[f"{prefix}-area"] = element.area
    values["geometry-vector"] = 1.0

    moduli = []
    initial = []
    for material in (*blocks.bars, *blocks.tendons):
        prefix = material_prefix(material)
        modulus = _law_value(material, "Es")
        if modulus <= 0.0:
            raise TraceValidationError("assigned elastic moduli must be positive")
        values[f"{prefix}-{trace_identity_token('Es')}"] = modulus
        moduli.append(modulus)
        if material.kind == "tendon":
            strain = _law_value(material, "IS")
            values[f"{prefix}-{trace_identity_token('IS')}"] = strain
            initial.append(strain)
    values["elastic-material-vector"] = 1.0
    values["short-term-modular-ratio"] = STEEL_REFERENCE_MODULUS / (ec_gpa * 1000.0)
    values["long-term-modular-ratio"] = (
        STEEL_REFERENCE_MODULUS * (1.0 + phi) / (ec_gpa * 1000.0)
    )
    values["normalised-elastic-inputs"] = 1.0
    for key in ("ns", "nl"):
        if key in inp:
            expected = values[
                "short-term-modular-ratio" if key == "ns" else "long-term-modular-ratio"
            ]
            supplied = _number(inp[key], key)
            if not _close(supplied, expected):
                raise TraceValidationError(
                    f"{key} is stale relative to conc_Ec and el_phi"
                )

    n_mult = np.asarray(moduli, dtype=float) / STEEL_REFERENCE_MODULUS
    if blocks.geometry.tendons:
        locked = np.asarray(
            [0.0] * len(blocks.geometry.bars)
            + [
                _law_value(material, "Es") * strain * 1000.0
                for material, strain in zip(blocks.tendons, initial)
            ],
            dtype=float,
        )
    else:
        locked = None
    return values, ec_gpa, fctm, n_mult, locked


def _finite_array(value: Any) -> bool:
    try:
        return bool(np.all(np.isfinite(np.asarray(value, dtype=float))))
    except (TypeError, ValueError):
        return False


def _resultant_from_stress(
    stress: np.ndarray, x: np.ndarray, y: np.ndarray, area: np.ndarray
) -> np.ndarray:
    force = stress * area
    return np.asarray(
        [float(force.sum()), float((force * y).sum()), float((force * x).sum())]
    )


def _concrete_resultant(moments: Any, plane: tuple[float, float, float]) -> np.ndarray:
    q0, qx, qy = plane
    return np.asarray(
        [
            q0 * moments.area + qx * moments.sx + qy * moments.sy,
            q0 * moments.sy + qx * moments.sxy + qy * moments.syy,
            q0 * moments.sx + qx * moments.sxx + qy * moments.sxy,
        ],
        dtype=float,
    )


def _put_plane(values: dict[str, float], prefix: str, result: Any) -> None:
    values[f"{prefix}-plane-q0"] = float(result.eps0)
    values[f"{prefix}-plane-qx"] = float(result.kx)
    values[f"{prefix}-plane-qy"] = float(result.ky)
    values[f"{prefix}-plane-evidence"] = 1.0


def _put_moments(values: dict[str, float], prefix: str, moments: Any) -> None:
    for name in ("area", "sx", "sy", "sxx", "syy", "sxy"):
        values[f"{prefix}-compression-{name}"] = float(getattr(moments, name))
    values[f"{prefix}-compression-moments"] = 1.0


def _put_resultant(
    values: dict[str, float], prefix: str, name: str, resultant: np.ndarray
) -> None:
    for component, value in zip(("n", "mx", "my"), resultant):
        values[f"{prefix}-{name}-{component}"] = float(value)
    values[f"{prefix}-{name}-resultant"] = 1.0


def _props_dict(props: Any) -> dict[str, float]:
    return {field: float(getattr(props, field)) for field in PROPERTY_FIELDS}


def _output_ids(inp: Mapping[str, Any], key: str) -> list[Any]:
    raw = inp.get(key, ())
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    return list(raw)


def _catalog_names(inp: Mapping[str, Any], key: str) -> dict[str, str]:
    catalog = inp.get(key)
    if not isinstance(catalog, Mapping):
        return {}
    items = catalog.get("items", ())
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        return {}
    return {
        str(item["id"]): str(item.get("name", ""))
        for item in items
        if isinstance(item, Mapping) and type(item.get("id")) is str
    }


def _expected_output(
    inp: Mapping[str, Any],
    blocks: SectionTraceBlocks,
    section: Section,
    combined: Any,
    total_mpa: np.ndarray,
    long_mpa: np.ndarray,
    dif_mpa: np.ndarray,
    rst1_mpa: np.ndarray,
    ec_gpa: float,
    moduli: np.ndarray,
    locked: np.ndarray | None,
    cracked: bool,
    factor: float,
    sigma_ct: float,
    props_un: Any,
    props_cr: Any | None,
) -> dict[str, Any]:
    bar_records = _output_ids(inp, "bar_elements")
    tendon_records = _output_ids(inp, "tendon_elements")
    bar_ids = [item.get("id") for item in bar_records if isinstance(item, Mapping)]
    tendon_ids = [item.get("id") for item in tendon_records if isinstance(item, Mapping)]
    bar_material_ids = [
        item.get("material_id") for item in bar_records if isinstance(item, Mapping)
    ]
    tendon_material_ids = [
        item.get("material_id") for item in tendon_records if isinstance(item, Mapping)
    ]
    mild_names = _catalog_names(inp, "mild_material_catalog")
    tendon_names = _catalog_names(inp, "prestress_material_catalog")
    bar_names = [mild_names.get(str(value), "") for value in bar_material_ids]
    prestress_names = [tendon_names.get(str(value), "") for value in tendon_material_ids]
    bars_mm2 = [(item.x, item.y, item.area * 1.0e6) for item in blocks.geometry.bars]
    tendons_mm2 = [
        (item.x, item.y, item.area * 1.0e6) for item in blocks.geometry.tendons
    ]
    nb = len(blocks.geometry.bars)
    rows = element_rows(
        bars_mm2,
        tendons_mm2,
        total=total_mpa,
        long=long_mpa,
        dif=dif_mpa,
        rst1=rst1_mpa,
        es_mpa=list(moduli[:nb]),
        ep_mpa=list(moduli[nb:]) if len(blocks.geometry.tendons) else None,
        bar_ids=bar_ids,
        tendon_ids=tendon_ids,
        bar_material_ids=bar_material_ids,
        tendon_material_ids=tendon_material_ids,
        bar_material_names=bar_names,
        tendon_material_names=prestress_names,
    )
    corners = concrete_corner_rows(
        blocks.geometry.rings[0],
        blocks.geometry.rings[1:],
        stress_plane=combined.short_term.strain_plane,
        ec_mpa=ec_gpa * 1000.0,
    )
    governing = max(rows, key=lambda row: row["total_mpa"]) if rows else None
    if governing is not None and governing["total_mpa"] <= 0.0:
        governing = None
    output_stresses = stress_outputs(
        total_mpa,
        n_bars=nb,
        max_concrete_compression=combined.max_concrete_compression / 1000.0,
        valid=True,
        bar_ids=bar_ids,
        tendon_ids=tendon_ids,
    )
    if locked is None:
        prestress = None
    else:
        x, y, area = section.bar_arrays()
        prestress = tuple(_resultant_from_stress(locked, x, y, area))
    return {
        "total": list(total_mpa),
        "long": list(long_mpa),
        "dif": list(dif_mpa),
        "rst1": list(rst1_mpa),
        "max_conc": combined.max_concrete_compression / 1000.0,
        "max_conc_xy": tuple(float(v) for v in combined.short_term.max_concrete_xy),
        "max_conc_point": int(combined.max_concrete_point) + 1,
        "na_x": float(combined.na_x_intercept),
        "na_y": float(combined.na_y_intercept),
        "max_steel": float(governing["total_mpa"]) if governing else 0.0,
        "max_steel_bar": int(np.argmax(total_mpa)) + 1 if governing else 0,
        "max_steel_type": governing["element_type"] if governing else None,
        "max_steel_element": governing["element_id"] if governing else None,
        "prestress": prestress,
        "converged": True,
        "stress_plane": tuple(float(v) for v in combined.short_term.strain_plane),
        "elements": rows,
        "concrete_corners": corners,
        "stress_outputs": output_stresses,
        "cracked": cracked,
        "lambda_cr": factor,
        "sigma_ct": sigma_ct,
        "fctm": float(inp["sls_fctm"]),
        "props_un": _props_dict(props_un),
        "props_cr": None if props_cr is None else _props_dict(props_cr),
    }


def _failure_evidence(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    context: Mapping[str, Any],
    blocks: SectionTraceBlocks,
    values: dict[str, float],
    flags: tuple[bool, bool, bool, bool],
) -> ReplayEvidence:
    elastic = _mapping(out.get("elastic"), "CT-005 candidate elastic result")
    if elastic.get("converged") is not False:
        raise TraceValidationError(
            "authoritative failed CT-005 state needs candidate converged=false"
        )
    shape = trace_shape(blocks, context, BRANCH_FAILED, None)
    for name, flag in zip(
        (
            "combined-cracked",
            "stage-i-long-total",
            "stage-i-long-external",
            "stage-i-short-external",
        ),
        flags,
    ):
        values[f"authoritative-{name}-converged"] = 1.0 if flag else 0.0
    states = {
        "elastic-failure-state": TraceResult(RESULT_FAILED, None, _FAILURE_REASON),
        "ct-005-elastic-first-cracking-result": TraceResult(
            RESULT_FAILED, None, _FAILURE_REASON
        ),
    }
    for spec in expected_step_contract(shape):
        if spec.step_id not in values and spec.step_id not in states:
            raise TraceValidationError(
                f"internal CT-005 failure evidence omitted {spec.step_id}"
            )
    return ReplayEvidence(blocks, shape, values, states, (_FAILURE_REASON,))


def replay_elastic_evidence(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    context: Mapping[str, Any],
) -> ReplayEvidence:
    """Recompute CT-005 from original inputs and verify retained output fields."""

    inp = _mapping(inp, "CT-005 input")
    out = _mapping(out, "analysis result")
    context = _mapping(context, "CT-005 context")
    try:
        blocks = _ct005_blocks(inp)
        values, ec_gpa, fctm, n_mult, locked = _input_state(inp, blocks)
        section = _folded_section(blocks)
        ns = values["short-term-modular-ratio"]
        nl = values["long-term-modular-ratio"]
        actions = {key: values[action_step_id(key)] for key in ACTION_KEYS}
        combined = solve_elastic_combined(
            section,
            -actions["P_el_l"], actions["Mx_el_l"], actions["My_el_l"], nl,
            -actions["P_el_s"], actions["Mx_el_s"], actions["My_el_s"], ns,
            n_mult=n_mult if n_mult.size else None,
            prestress_stress=locked,
        )
        stage_long_total = solve_elastic_uncracked(
            section, -actions["P_el_l"], actions["Mx_el_l"], actions["My_el_l"], nl,
            n_mult=n_mult if n_mult.size else None, prestress_stress=locked,
        )
        stage_long_external = solve_elastic_uncracked(
            section, -actions["P_el_l"], actions["Mx_el_l"], actions["My_el_l"], nl,
            n_mult=n_mult if n_mult.size else None,
        )
        stage_short_external = solve_elastic_uncracked(
            section, -actions["P_el_s"], actions["Mx_el_s"], actions["My_el_s"], ns,
            n_mult=n_mult if n_mult.size else None,
        )
    except TraceValidationError:
        raise
    except (ArithmeticError, np.linalg.LinAlgError, TypeError, ValueError) as exc:
        if "blocks" not in locals() or "values" not in locals():
            raise TraceValidationError(f"invalid CT-005 input: {exc}") from exc
        return _failure_evidence(
            inp, out, context, blocks, values, (False, False, False, False)
        )

    flags = (
        bool(combined.converged),
        bool(stage_long_total.converged),
        bool(stage_long_external.converged),
        bool(stage_short_external.converged),
    )
    basic_values = (
        combined.long.strain_plane,
        combined.short_term.strain_plane,
        combined.bar_stress_total,
        combined.bar_stress_long,
        combined.bar_stress_dif,
        combined.bar_stress_rst1,
        combined.max_concrete_compression,
        combined.short_term.max_concrete_xy,
        stage_long_total.strain_plane,
        stage_long_external.strain_plane,
        stage_short_external.strain_plane,
    )
    intercepts_ok = all(
        not math.isnan(float(value))
        for value in (combined.na_x_intercept, combined.na_y_intercept)
    )
    if not all(flags) or not all(_finite_array(value) for value in basic_values) or not intercepts_ok:
        return _failure_evidence(inp, out, context, blocks, values, flags)

    vertices = section.concrete_vertices()
    long_total_sigma = (
        stage_long_total.eps0
        + stage_long_total.kx * vertices[:, 0]
        + stage_long_total.ky * vertices[:, 1]
    ) / 1000.0
    long_external_sigma = (
        stage_long_external.eps0
        + stage_long_external.kx * vertices[:, 0]
        + stage_long_external.ky * vertices[:, 1]
    ) / 1000.0
    short_external_sigma = (
        stage_short_external.eps0
        + stage_short_external.kx * vertices[:, 0]
        + stage_short_external.ky * vertices[:, 1]
    ) / 1000.0
    fixed_sigma = long_total_sigma - long_external_sigma
    path_external = {
        "long": long_external_sigma,
        "total": long_external_sigma + short_external_sigma,
    }
    path_total = {
        "long": long_total_sigma,
        "total": long_total_sigma + short_external_sigma,
    }
    factors: dict[str, float] = {}
    governing_fibres: dict[str, int | None] = {}
    sigma_cts = {
        "long": max(0.0, float(long_total_sigma.max())),
        "total": float(path_total["total"].max()),
    }
    factor_by_path: dict[str, np.ndarray] = {}
    has_prestress = locked is not None
    for path in ("long", "total"):
        ext = path_external[path]
        loaded = ext > (_TENSION_TOLERANCE_MPA if has_prestress else 0.0)
        candidates = np.full(len(vertices), math.inf, dtype=float)
        if np.any(loaded):
            candidates[loaded] = np.maximum(
                0.0, (fctm - fixed_sigma[loaded]) / ext[loaded]
            )
        factor_by_path[path] = candidates
        if np.any(np.isfinite(candidates)):
            index = int(np.argmin(candidates))
            factors[path] = float(candidates[index])
            governing_fibres[path] = index
        else:
            factors[path] = math.inf
            governing_fibres[path] = None
    governing_path = "total" if factors["total"] < factors["long"] else "long"
    factor = factors[governing_path]
    sigma_ct = sigma_cts[governing_path]
    cracked = factor < 1.0
    branch = BRANCH_INFINITE if math.isinf(factor) else BRANCH_FINITE
    shape = trace_shape(blocks, context, branch, cracked)
    states: dict[str, TraceResult] = {}

    _put_plane(values, "long-cracked", combined.long)
    _put_plane(values, "total-cracked", combined.short_term)
    rings = section.integration_rings()
    long_moments = _concrete_moments(rings, *combined.long.strain_plane)
    total_moments = _concrete_moments(rings, *combined.short_term.strain_plane)
    _put_moments(values, "long", long_moments)
    _put_moments(values, "total", total_moments)

    x, y, area = section.bar_arrays()
    passive_long = nl * n_mult * (
        combined.long.eps0 + combined.long.kx * x + combined.long.ky * y
    )
    rst1 = ns * n_mult * (
        combined.short_term.eps0
        + combined.short_term.kx * x
        + combined.short_term.ky * y
    )
    neutralising = passive_long * (1.0 - ns / nl)
    locked_array = np.zeros_like(passive_long) if locked is None else locked
    nb = len(blocks.geometry.bars)
    long_concrete = _concrete_resultant(long_moments, combined.long.strain_plane)
    total_concrete = _concrete_resultant(total_moments, combined.short_term.strain_plane)
    zero = np.zeros(3, dtype=float)
    long_bar = _resultant_from_stress(passive_long[:nb], x[:nb], y[:nb], area[:nb]) if nb else zero
    long_tendon = _resultant_from_stress(passive_long[nb:], x[nb:], y[nb:], area[nb:]) if len(x) > nb else zero
    rst1_bar = _resultant_from_stress(rst1[:nb], x[:nb], y[:nb], area[:nb]) if nb else zero
    rst1_tendon = _resultant_from_stress(rst1[nb:], x[nb:], y[nb:], area[nb:]) if len(x) > nb else zero
    neutral_bar = _resultant_from_stress(neutralising[:nb], x[:nb], y[:nb], area[:nb]) if nb else zero
    neutral_tendon = _resultant_from_stress(neutralising[nb:], x[nb:], y[nb:], area[nb:]) if len(x) > nb else zero
    prestress = _resultant_from_stress(locked_array, x, y, area) if len(x) else zero
    for prefix, contributions in (
        ("long", {
            "concrete": long_concrete, "bar": long_bar,
            "tendon": long_tendon, "prestress": prestress,
        }),
        ("total", {
            "concrete": total_concrete, "bar": rst1_bar,
            "tendon": rst1_tendon, "prestress": prestress,
            "neutralising-bar": neutral_bar,
            "neutralising-tendon": neutral_tendon,
        }),
    ):
        for name, resultant in contributions.items():
            _put_resultant(values, prefix, name, resultant)
        target = np.asarray(
            [
                actions["P_el_l"] + (actions["P_el_s"] if prefix == "total" else 0.0),
                -(actions["Mx_el_l"] + (actions["Mx_el_s"] if prefix == "total" else 0.0)),
                -(actions["My_el_l"] + (actions["My_el_s"] if prefix == "total" else 0.0)),
            ]
        )
        residual = sum(contributions.values(), start=np.zeros(3)) - target
        for component, value in zip(("n", "mx", "my"), residual):
            values[f"{prefix}-equilibrium-residual-{component}"] = float(value)
        values[f"{prefix}-equilibrium-evidence"] = 1.0

    total_kpa = neutralising + rst1 + locked_array
    long_kpa = passive_long + locked_array
    dif_kpa = total_kpa - long_kpa
    for kind, start, count, materials in (
        ("bar", 0, nb, blocks.bars),
        ("tendon", nb, len(blocks.geometry.tendons), blocks.tendons),
    ):
        for local_index in range(count):
            global_index = start + local_index
            prefix = f"element-{kind}-{local_index:04d}"
            values[f"{prefix}-long-stress"] = float(long_kpa[global_index] / 1000.0)
            values[f"{prefix}-rst1-stress"] = float(rst1[global_index] / 1000.0)
            values[f"{prefix}-difference-stress"] = float(dif_kpa[global_index] / 1000.0)
            values[f"{prefix}-total-stress"] = float(total_kpa[global_index] / 1000.0)
            values[f"{prefix}-total-strain"] = float(
                total_kpa[global_index] / 1000.0 / _law_value(materials[local_index], "Es") * 1000.0
            )
            values[f"{prefix}-evidence"] = 1.0
    values["element-response-evidence"] = 1.0

    raw_fibres = (
        combined.short_term.eps0
        + combined.short_term.kx * vertices[:, 0]
        + combined.short_term.ky * vertices[:, 1]
    )
    sustained_fibres = (
        combined.long.eps0
        + combined.long.kx * vertices[:, 0]
        + combined.long.ky * vertices[:, 1]
    )
    phi = values[scalar_step_id("el_phi")]
    compatible_strains = (
        raw_fibres + phi * sustained_fibres
    ) / (ec_gpa * 1000.0)
    for index, (raw, strain) in enumerate(zip(raw_fibres, compatible_strains)):
        prefix = f"response-fibre-{index:04d}"
        values[f"{prefix}-raw-stress"] = float(raw)
        values[f"{prefix}-strain"] = float(strain)
        values[f"{prefix}-carried-stress"] = min(float(raw / 1000.0), 0.0)
        values[f"{prefix}-evidence"] = 1.0
    values["concrete-fibre-response-evidence"] = 1.0

    total_mpa = total_kpa / 1000.0
    long_mpa = long_kpa / 1000.0
    dif_mpa = dif_kpa / 1000.0
    rst1_mpa = rst1 / 1000.0
    values["maximum-concrete-compression"] = float(combined.max_concrete_compression / 1000.0)
    values["maximum-concrete-point"] = float(combined.max_concrete_point + 1)
    values["maximum-concrete-x"] = float(combined.short_term.max_concrete_xy[0])
    values["maximum-concrete-y"] = float(combined.short_term.max_concrete_xy[1])
    if total_mpa.size and float(total_mpa.max()) > 0.0:
        maximum_index = int(np.argmax(total_mpa))
        values["maximum-element-tension"] = float(total_mpa[maximum_index])
        values["maximum-element-index"] = float(maximum_index + 1)
        values["maximum-element-kind"] = 1.0 if maximum_index < nb else 2.0
    else:
        values["maximum-element-tension"] = 0.0
        values["maximum-element-index"] = 0.0
        values["maximum-element-kind"] = 0.0
    for segment, value_key, index_key in (
        (total_mpa[:nb], "maximum-bar-tension", "maximum-bar-index"),
        (total_mpa[nb:], "maximum-tendon-tension", "maximum-tendon-index"),
    ):
        if segment.size:
            tension = np.maximum(segment, 0.0)
            local_index = int(np.argmax(tension))
            values[value_key] = float(tension[local_index])
            values[index_key] = float(local_index + 1)
        else:
            values[value_key] = 0.0
            values[index_key] = 0.0
    for step_id, intercept in (
        ("neutral-axis-x", float(combined.na_x_intercept)),
        ("neutral-axis-y", float(combined.na_y_intercept)),
    ):
        if math.isfinite(intercept):
            values[step_id] = intercept
        else:
            states[step_id] = TraceResult(
                RESULT_POSITIVE_INFINITY if intercept > 0.0 else RESULT_NEGATIVE_INFINITY,
                None,
                "The solved plane is parallel to this coordinate axis.",
            )
    values["response-extrema-evidence"] = 1.0

    props_un = transformed_properties(
        section, nl, cracked=False, n_mult=n_mult if n_mult.size else None
    )
    governing_state = combined.short_term if governing_path == "total" else combined.long
    props_cr = (
        transformed_properties(
            section, nl,
            eps0=governing_state.eps0,
            kx=governing_state.kx,
            ky=governing_state.ky,
            cracked=True,
            n_mult=n_mult if n_mult.size else None,
        )
        if cracked else None
    )
    for prefix, props in (("uncracked-properties", props_un), ("cracked-properties", props_cr)):
        if props is None:
            continue
        for field in PROPERTY_FIELDS:
            values[f"{prefix}-{field.lower()}"] = float(getattr(props, field))
        values[f"{prefix}-evidence"] = 1.0
    values["transformed-properties-evidence"] = 1.0
    values["elastic-response-evidence"] = 1.0

    _put_plane(values, "stage-i-long-total", stage_long_total)
    _put_plane(values, "stage-i-long-external", stage_long_external)
    _put_plane(values, "stage-i-short-external", stage_short_external)
    for path in ("long", "total"):
        for index in range(len(vertices)):
            prefix = f"cracking-{path}-fibre-{index:04d}"
            values[f"{prefix}-fixed-prestress"] = float(fixed_sigma[index])
            values[f"{prefix}-external-stress"] = float(path_external[path][index])
            values[f"{prefix}-total-stress"] = float(path_total[path][index])
            candidate_factor = float(factor_by_path[path][index])
            if math.isinf(candidate_factor):
                states[f"{prefix}-factor"] = TraceResult(
                    RESULT_POSITIVE_INFINITY,
                    None,
                    "This fibre has no retained positive tensile action reach.",
                )
            else:
                values[f"{prefix}-factor"] = candidate_factor
            values[f"{prefix}-evidence"] = 1.0
        values[f"cracking-{path}-sigma-ct"] = float(sigma_cts[path])
        if math.isinf(factors[path]):
            states[f"cracking-{path}-factor"] = TraceResult(
                RESULT_POSITIVE_INFINITY,
                None,
                "No concrete fibre on this action path has finite tensile reach.",
            )
            states[f"cracking-{path}-governing-fibre"] = TraceResult(
                RESULT_UNDEFINED,
                None,
                "No finite first-cracking fibre exists on this action path.",
            )
        else:
            values[f"cracking-{path}-factor"] = float(factors[path])
            values[f"cracking-{path}-governing-fibre"] = float(
                governing_fibres[path] + 1
            )
        values[f"cracking-{path}-path-evidence"] = 1.0
    values["governing-cracking-path"] = 2.0 if governing_path == "total" else 1.0
    if governing_fibres[governing_path] is None:
        states["governing-cracking-fibre"] = TraceResult(
            RESULT_UNDEFINED, None,
            "The governing action path has no finite first-cracking fibre.",
        )
    else:
        values["governing-cracking-fibre"] = float(
            governing_fibres[governing_path] + 1
        )
    values["governing-sigma-ct"] = float(sigma_ct)
    if math.isinf(factor):
        states["governing-cracking-factor"] = TraceResult(
            RESULT_POSITIVE_INFINITY, None,
            "The retained actions cannot reach first cracking at a finite factor.",
        )
    else:
        values["governing-cracking-factor"] = float(factor)
    values["retained-cracked-state"] = 1.0 if cracked else 0.0
    values["first-cracking-evidence"] = 1.0

    if not all(math.isfinite(float(value)) for value in values.values()):
        return _failure_evidence(inp, out, context, blocks, values, flags)

    expected_output = _expected_output(
        inp, blocks, section, combined,
        total_mpa, long_mpa, dif_mpa, rst1_mpa,
        ec_gpa, np.asarray([_law_value(item, "Es") for item in (*blocks.bars, *blocks.tendons)]),
        locked, cracked, factor, sigma_ct, props_un, props_cr,
    )
    candidate = _mapping(out.get("elastic"), "CT-005 candidate elastic result")
    _compare(candidate, expected_output, "elastic")

    if branch == BRANCH_INFINITE:
        states["ct-005-elastic-first-cracking-result"] = TraceResult(
            RESULT_POSITIVE_INFINITY,
            None,
            "No retained concrete fibre/action path reaches first cracking finitely.",
        )
        warnings = (
            "The first-cracking factor is genuinely positive infinity; no finite substitute is used.",
        )
    else:
        values["ct-005-elastic-first-cracking-result"] = float(factor)
        warnings = ()

    for spec in expected_step_contract(shape):
        if spec.step_id in values or spec.step_id in states:
            continue
        if (
            "evidence" in spec.step_id
            or spec.step_id.endswith("-vector")
            or spec.step_id == "normalised-elastic-inputs"
        ):
            values[spec.step_id] = 1.0
            continue
        raise TraceValidationError(
            f"internal CT-005 reconstruction omitted {spec.step_id}"
        )
    return ReplayEvidence(blocks, shape, values, states, warnings)
