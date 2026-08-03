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
    RESULT_FAILED, RESULT_FINITE, RESULT_POSITIVE_INFINITY, RESULT_UNDEFINED,
    ROLE_COMPUTED, ROLE_FINAL, ROLE_METHOD_VALUE, ROLE_USER_INPUT, TraceBundle,
    TraceCalculation, TraceDependency, TraceResult, TraceStep, TraceUnit,
    TraceValidationError, create_bundle, trace_identity_token, validate_bundle,
)
from .crack_trace_contract import (
    AREA, AREA_MM2, BOUNDARY, CODE, COVERAGE_ID, CRACK_WIDTH, EDITION,
    EFFECTIVE_AREA, ELASTIC, FAILURE_STATES, FORCE, GEOMETRY, INPUT, LENGTH,
    LENGTH_MM, MEAN_STRAIN, METHOD_ID, MOMENT, ONE, RAW_GRADIENT, RAW_STRESS,
    SECOND_MOMENT, SELECTION, SPACING_CLOSE, SPACING_WIDE, STRAIN, STRESS,
    SUCCESS_STATES, UNDEFINED_STATES, MemberShape, registry_for,
)
from .elastic import solve_elastic_combined, transformed_properties
from .materials import ES as REFERENCE_ES
from .section import Bar, Section
from .section_trace_blocks import SectionTraceBlocks, context_axes, context_id
from .section_trace_blocks import section_trace_blocks
from .serviceability import (
    CRACK_DIRECTIONAL_LIMITATION, CrackWidthEvaluation, analyse_cracking,
    combined_cracking, evaluate_crack_width,
)
from .sls import crack_outputs
from .trace_registry import audit_trace_registry


_ACTIVE_MODES = frozenset({"Elastic", "Both"})
_CASES = (("long-term", "crack", 0.4), ("short-term", "crack_short", 0.6))
_PROPERTIES = ("area", "cx", "cy", "Ix", "Iy", "Ixy")
_SIZE_MODES = frozenset({"Area", "Diameter", "Independent"})


@dataclass(frozen=True, slots=True)
class Case:
    name: str
    key: str
    kt: float
    modular_ratio: float
    evaluation: CrackWidthEvaluation
    state: Any | None
    payload: Mapping[str, Any] | None


@dataclass(frozen=True, slots=True)
class Replay:
    blocks: SectionTraceBlocks
    cases: tuple[Case, ...]
    inputs: tuple[tuple[str, Any], ...]
    retained: Mapping[str, Any]
    cracked: bool
    factor: float
    sigma_ct: float
    props_un: Any
    props_cr: Any | None


@dataclass(frozen=True, slots=True)
class FailedReplay:
    inputs: tuple[tuple[str, Any], ...]
    output_shape: Any


def _map(value: Any, label: str, *, exact: bool = False) -> Mapping[str, Any]:
    if (type(value) is not dict) if exact else (not isinstance(value, Mapping)):
        qualifier = "an exact dict" if exact else "a mapping"
        raise TraceValidationError(f"{label} must be {qualifier}")
    if any(type(key) is not str for key in value):
        raise TraceValidationError(f"{label} keys must be text")
    return value


def _seq(value: Any, label: str) -> tuple[Any, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TraceValidationError(f"{label} must be an aligned sequence")
    return tuple(value)


def _get(value: Mapping[str, Any], key: str) -> Any:
    if key not in value:
        raise TraceValidationError(f"CT-009 requires {key}")
    return value[key]


def _number(value: Any, label: str, *, positive: bool = False) -> float:
    if type(value) not in {int, float} or type(value) is bool:
        raise TraceValidationError(f"{label} must be a finite non-Boolean number")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0.0):
        kind = "positive finite" if positive else "finite"
        raise TraceValidationError(f"{label} must be {kind}")
    return result


def _same_number(actual: Any, expected: float, label: str) -> None:
    value = _number(actual, label)
    if not math.isclose(value, float(expected), rel_tol=1e-13, abs_tol=1e-14):
        raise TraceValidationError(f"{label} is stale relative to section geometry")


def _typed(value: Any, active: set[int] | None = None) -> Any:
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
                if value.dtype.hasobject else value.tobytes(order="C").hex()
            )
            return ["numpy-array", value.dtype.str, list(value.shape), payload]
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return [
                "dataclass", value.__class__.__module__, value.__class__.__qualname__,
                [[field.name, _typed(getattr(value, field.name), active)]
                 for field in dataclasses.fields(value)],
            ]
        if isinstance(value, Mapping):
            return [
                "mapping", value.__class__.__module__, value.__class__.__qualname__,
                [[_typed(key, active), _typed(item, active)]
                 for key, item in value.items()],
            ]
        if type(value) in {list, tuple}:
            return [type(value).__name__, [_typed(item, active) for item in value]]
        if hasattr(value, "__dict__"):
            return [
                "object", value.__class__.__module__, value.__class__.__qualname__,
                _typed(vars(value), active),
            ]
        slots = getattr(value.__class__, "__slots__", ())
        if slots:
            names = (slots,) if type(slots) is str else tuple(slots)
            return [
                "slots", value.__class__.__module__, value.__class__.__qualname__,
                [[name, _typed(getattr(value, name), active)]
                 for name in names if hasattr(value, name)],
            ]
    finally:
        active.remove(identity)
    raise TraceValidationError(
        f"unsupported CT-009 identity type {type(value).__module__}."
        f"{type(value).__qualname__}"
    )


def _shape(value: Any) -> Any:
    if isinstance(value, Mapping):
        return ["mapping", type(value).__module__, type(value).__qualname__,
                [[_typed(key), _shape(item)] for key, item in value.items()]]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return ["sequence", type(value).__module__, type(value).__qualname__,
                [_shape(item) for item in value]]
    return ["leaf", type(value).__module__, type(value).__qualname__]


def _words(value: Any) -> tuple[float, ...]:
    raw = json.dumps(
        _typed(value), ensure_ascii=True, separators=(",", ":"), allow_nan=False,
    ).encode("ascii")
    digest = hashlib.sha256(raw).digest()
    return tuple(float(int.from_bytes(digest[i:i + 4], "big"))
                 for i in range(0, 32, 4))


def _same(actual: Any, expected: Any, label: str) -> None:
    if _typed(actual) != _typed(expected):
        raise TraceValidationError(
            f"{label} differs in value, type, order, or cardinality from replay"
        )


def _dispatch(inp: Mapping[str, Any]) -> bool:
    for key in ("mode", "sls_code", "sls_edition", "sls_member"):
        if type(_get(inp, key)) is not str:
            raise TraceValidationError(f"{key} must be text")
    for key in ("sls_cw", "sls_dk_na"):
        if type(_get(inp, key)) is not bool:
            raise TraceValidationError(f"{key} must be a Boolean")
    sibling = _get(inp, "sls_tendon_xi")
    if type(sibling) not in {int, float} or type(sibling) is bool:
        raise TraceValidationError("sls_tendon_xi must retain built-in numeric type")
    if inp["mode"] not in _ACTIVE_MODES or not inp["sls_cw"]:
        return False
    if inp["sls_code"] != CODE:
        return False
    if inp["sls_edition"] != EDITION or inp["sls_dk_na"]:
        raise TraceValidationError("base selector must retain edition=2004 and dk_na=false")
    return True


def _geometry_identity(inp: Mapping[str, Any], blocks: SectionTraceBlocks) -> None:
    raw_rings = (_seq(_get(inp, "outer"), "outer"),
                 *(_seq(item, "hole") for item in _seq(_get(inp, "holes"), "holes")))
    if len(raw_rings) != len(blocks.geometry.rings):
        raise TraceValidationError("polygon ring count differs from Section")
    for raw_ring, resolved_ring in zip(raw_rings, blocks.geometry.rings):
        if len(raw_ring) != len(resolved_ring):
            raise TraceValidationError("polygon ring cardinality differs from Section")
        for raw_point, point in zip(raw_ring, resolved_ring):
            pair = _seq(raw_point, "polygon point")
            if len(pair) != 2:
                raise TraceValidationError("polygon points require x and y")
            _same_number(pair[0], point[0], "polygon x")
            _same_number(pair[1], point[1], "polygon y")

    for kind, raw_key, records_key, resolved in (
        ("bar", "bars", "bar_elements", blocks.geometry.bars),
        ("tendon", "tendons", "tendon_elements", blocks.geometry.tendons),
    ):
        raw_items = _seq(_get(inp, raw_key), raw_key)
        records = _seq(_get(inp, records_key), records_key)
        if len(raw_items) != len(resolved) or len(records) != len(resolved):
            raise TraceValidationError(f"{kind} representations must align")
        for index, (raw_item, record_value, element) in enumerate(
            zip(raw_items, records, resolved)
        ):
            raw = _seq(raw_item, f"{raw_key}[{index}]")
            record = _map(record_value, f"{records_key}[{index}]", exact=True)
            required = (
                "id", "kind", "x_mm", "y_mm", "area_mm2", "diameter_mm",
                "size_mode", "material_id", "fatigue_detail_id", "x", "y",
            )
            if len(raw) != 3 or any(key not in record for key in required):
                raise TraceValidationError(f"{kind} current-schema record is incomplete")
            if record["kind"] != kind or type(record["kind"]) is not str:
                raise TraceValidationError(f"{kind} record kind is invalid")
            if type(record["size_mode"]) is not str or record["size_mode"] not in _SIZE_MODES:
                raise TraceValidationError(f"{kind} size mode is outside current schema")
            if type(record["fatigue_detail_id"]) is not str:
                raise TraceValidationError("fatigue_detail_id must retain text type")
            for actual, expected, label in (
                (raw[0], element.x, "raw x"), (raw[1], element.y, "raw y"),
                (raw[2], element.area * 1e6, "raw area"),
                (record["x"], element.x, "element x"),
                (record["y"], element.y, "element y"),
                (record["x_mm"], element.x * 1000.0, "element x_mm"),
                (record["y_mm"], element.y * 1000.0, "element y_mm"),
                (record["area_mm2"], element.area * 1e6, "element area"),
            ):
                _same_number(actual, expected, f"{records_key}[{index}] {label}")
            diameter = _number(record["diameter_mm"], "diameter", positive=True)
            if record["size_mode"] != "Independent":
                _same_number(
                    record["area_mm2"], math.pi * diameter * diameter / 4.0,
                    f"{records_key}[{index}] area/diameter",
                )


def _element_identity(inp: Mapping[str, Any], key: str) -> Any:
    raw = _get(inp, key)
    records = _seq(raw, key)
    sealed = []
    for index, value in enumerate(records):
        record = _map(value, f"{key}[{index}]", exact=True)
        sealed.append(tuple(
            (name, ("inert-fatigue-detail", type(item).__module__, type(item).__qualname__))
            if name == "fatigue_detail_id" else (name, item)
            for name, item in record.items()
        ))
    return (type(raw).__module__, type(raw).__qualname__, tuple(sealed))


def _input_groups(inp: Mapping[str, Any], blocks: SectionTraceBlocks) -> tuple[tuple[str, Any], ...]:
    geometry = tuple((key, _get(inp, key)) for key in
                     ("section", "outer", "holes", "bars", "tendons"))
    geometry += (("resolved", blocks.geometry),)
    material_keys = (
        "concrete", "steel", "prestress", "bar_materials", "tendon_materials",
        "concrete_preset", "mild_preset", "prestress_preset",
        "mild_material_catalog", "prestress_material_catalog",
    )
    materials = tuple((key, _get(inp, key)) for key in material_keys)
    materials += (("concrete_material_id",
                   inp["concrete_material_id"] if "concrete_material_id" in inp
                   else ("missing-key", "concrete_material_id")),
                  ("resolved-concrete", blocks.concrete),
                  ("resolved-bars", blocks.bars),
                  ("resolved-tendons", blocks.tendons))
    assignments = (("bar_elements", _element_identity(inp, "bar_elements")),
                   ("tendon_elements", _element_identity(inp, "tendon_elements")))
    controls = []
    for key in (
        "mode", "P_el_l", "Mx_el_l", "My_el_l", "P_el_s", "Mx_el_s",
        "My_el_s", "conc_Ec", "el_phi", "nl", "ns", "sls_fctm", "sls_cw",
        "sls_phi", "sls_k1", "sls_tendon_xi", "sls_code", "sls_edition",
        "sls_dk_na", "sls_member",
    ):
        value = _get(inp, key)
        if key in {"sls_tendon_xi", "sls_member"}:
            value = ("inert-sibling-type", type(value).__module__, type(value).__qualname__)
        controls.append((key, value))
    return (("geometry", geometry), ("materials", materials),
            ("assignments", assignments), ("controls", tuple(controls)))


def _numbers(inp: Mapping[str, Any]) -> dict[str, float]:
    result = {key: _number(_get(inp, key), key) for key in
              ("P_el_l", "Mx_el_l", "My_el_l", "P_el_s", "Mx_el_s", "My_el_s")}
    for key in ("conc_Ec", "nl", "ns", "sls_fctm", "sls_k1"):
        result[key] = _number(_get(inp, key), key, positive=True)
    for key in ("el_phi", "sls_phi"):
        result[key] = _number(_get(inp, key), key)
        if result[key] < 0.0:
            raise TraceValidationError(f"{key} must be non-negative")
    expected_ns = REFERENCE_ES / (result["conc_Ec"] * 1000.0)
    expected_nl = expected_ns * (1.0 + result["el_phi"])
    for key, expected in (("ns", expected_ns), ("nl", expected_nl)):
        if not math.isclose(result[key], expected, rel_tol=1e-12, abs_tol=0.0):
            raise TraceValidationError(f"{key} is stale relative to Ec and creep")
    return result


def _law(material: Any, key: str) -> float:
    values = dict(material.values)
    if key not in values:
        raise TraceValidationError(f"{material.kind} law lacks {key}")
    return _number(values[key], f"{material.kind} {key}")


def _section(blocks: SectionTraceBlocks) -> Section:
    return Section(
        [np.asarray(ring, dtype=float) for ring in blocks.geometry.rings],
        bars=[Bar(item.x, item.y, item.area)
              for item in (*blocks.geometry.bars, *blocks.geometry.tendons)],
    )


def _finite_solver(result: Any) -> bool:
    values = (
        result.long.strain_plane, result.short_term.strain_plane,
        result.bar_stress_total, result.bar_stress_long, result.bar_stress_dif,
        result.bar_stress_rst1, result.max_concrete_compression,
    )
    try:
        return bool(result.converged) and all(
            np.all(np.isfinite(np.asarray(value, dtype=float))) for value in values
        )
    except (TypeError, ValueError):
        return False


def _identity(blocks: SectionTraceBlocks, index: int) -> tuple[str, int, str]:
    if index < len(blocks.bars):
        return "Bar", index + 1, blocks.bars[index].element_id
    tendon = index - len(blocks.bars)
    return "Tendon", tendon + 1, blocks.tendons[tendon].element_id


def _payload(result: Any, blocks: SectionTraceBlocks) -> dict[str, Any] | None:
    if result is None:
        return None
    def row(item: Any) -> dict[str, Any]:
        kind, number, element_id = _identity(blocks, item.bar_index)
        return {
            "element_type": kind, "element_no": number, "element_id": element_id,
            "x_mm": item.x * 1000.0, "y_mm": item.y * 1000.0,
            "area_mm2": item.area, "wk": item.wk, "sr_max": item.sr_max,
            "esm_ecm": item.esm_ecm, "sigma_s": item.sigma_s,
            "rho_p_eff": item.rho_p_eff, "ac_eff": item.ac_eff,
            "hc_ef": item.hc_ef, "phi": item.phi, "cover": item.cover,
            "coarse": item.coarse, "edition": item.edition, "kw": item.kw,
            "k1_r": item.k1_r, "kfl": item.kfl,
            "sr_max_geometric": item.sr_max_geometric,
        }
    kind, number, element_id = _identity(blocks, result.gov_bar)
    return {
        "wk": result.wk, "sr_max": result.sr_max, "esm_ecm": result.esm_ecm,
        "sigma_s": result.sigma_s, "rho_p_eff": result.rho_p_eff,
        "ac_eff": result.ac_eff, "hc_ef": result.hc_ef, "phi": result.phi,
        "cover": result.cover, "gov_bar": result.gov_bar + 1,
        "element_type": kind, "element_no": number, "element_id": element_id,
        "coarse": result.coarse, "edition": result.edition, "kw": result.kw,
        "k1_r": result.k1_r, "kfl": result.kfl,
        "sr_max_geometric": result.sr_max_geometric,
        "candidates": [row(item) for item in result.candidates],
    }


def _props(value: Any) -> dict[str, float]:
    return {key: float(getattr(value, key)) for key in _PROPERTIES}


def _candidate(out: Mapping[str, Any]) -> Mapping[str, Any]:
    if "elastic" not in out:
        raise TraceValidationError("active CT-009 input requires elastic output")
    return _map(out["elastic"], "elastic output", exact=True)


def _outputs(candidate: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    stems = {"converged", "cracked", "lambda_cr", "sigma_ct", "fctm", "show_cw"}
    owned = tuple(key for key in candidate if
                  any(key == stem or key.startswith(stem + "_") for stem in stems)
                  or key.startswith("crack") or key.startswith("props_"))
    if owned != tuple(expected):
        raise TraceValidationError("CT-009 output inventory/order differs from replay")
    for key, value in expected.items():
        _same(candidate[key], value, f"elastic.{key}")


def _replay(inp: Mapping[str, Any], out: Mapping[str, Any]) -> Replay | FailedReplay:
    numbers = _numbers(inp)
    try:
        blocks = section_trace_blocks(inp)
        _geometry_identity(inp, blocks)
        section = _section(blocks)
    except TraceValidationError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"invalid CT-009 section identity: {exc}") from exc
    inputs = _input_groups(inp, blocks)
    moduli = np.asarray([_law(item, "Es") for item in (*blocks.bars, *blocks.tendons)],
                        dtype=float)
    if np.any(~np.isfinite(moduli)) or np.any(moduli <= 0.0):
        raise TraceValidationError("reinforcement moduli must be positive finite")
    multipliers = moduli / REFERENCE_ES
    locked = None
    if blocks.tendons:
        locked = np.asarray(
            [0.0] * len(blocks.bars) +
            [_law(item, "Es") * _law(item, "IS") * 1000.0 for item in blocks.tendons],
            dtype=float,
        )
    p_long, p_short = -numbers["P_el_l"], -numbers["P_el_s"]
    combined = solve_elastic_combined(
        section, p_long, numbers["Mx_el_l"], numbers["My_el_l"], numbers["nl"],
        p_short, numbers["Mx_el_s"], numbers["My_el_s"], numbers["ns"],
        n_mult=multipliers, prestress_stress=locked,
    )
    records = (*_seq(_get(inp, "bar_elements"), "bar_elements"),
               *_seq(_get(inp, "tendon_elements"), "tendon_elements"))
    diameter: float | list[float] = numbers["sls_phi"]
    if not diameter:
        diameter = [_number(_map(item, "element")["diameter_mm"], "diameter", positive=True)
                    for item in records]
    k1 = [numbers["sls_k1"]] * len(blocks.bars) + [1.6] * len(blocks.tendons)
    long = analyse_cracking(
        section, p_long, numbers["Mx_el_l"], numbers["My_el_l"], numbers["nl"],
        fctm=numbers["sls_fctm"], Es=moduli, beta=0.5, kt=0.4,
        bar_diameter=diameter, k1=k1, edition=EDITION,
        n_mult=multipliers, prestress_stress=locked,
    )
    peak_cracked, peak_factor, peak_sigma = combined_cracking(
        section, p_long, numbers["Mx_el_l"], numbers["My_el_l"], numbers["nl"],
        p_short, numbers["Mx_el_s"], numbers["My_el_s"], numbers["ns"],
        fctm=numbers["sls_fctm"], n_mult=multipliers, prestress_stress=locked,
    )
    candidate = _candidate(out)
    converged = (_finite_solver(combined) and bool(long.uncracked.converged)
                 and bool(long.cracked_state.converged))
    if not converged:
        if candidate.get("converged") is not False or "crack_output" not in candidate:
            raise TraceValidationError("failed replay requires converged=false and crack_output")
        aggregate = _map(candidate["crack_output"], "failed crack_output", exact=True)
        _same(aggregate, {
            "value": None, "case": None, "governing": None, "unit": "mm",
            "calculation_state": "INVALID",
        }, "failed crack_output")
        return FailedReplay(inputs, _shape(candidate))
    if peak_factor < long.lambda_cr:
        cracked, factor, sigma_ct, governing = (
            bool(peak_cracked), float(peak_factor), float(peak_sigma), combined.short_term)
    else:
        cracked, factor, sigma_ct, governing = (
            bool(long.cracked), float(long.lambda_cr), float(long.sigma_ct),
            long.cracked_state)
    props_un = transformed_properties(section, numbers["nl"], cracked=False,
                                      n_mult=multipliers)
    props_cr = (transformed_properties(
        section, numbers["nl"], eps0=governing.eps0, kx=governing.kx,
        ky=governing.ky, cracked=True, n_mult=multipliers,
    ) if cracked else None)
    ratios = (numbers["nl"], numbers["ns"])
    if cracked:
        short_stress = np.asarray(combined.bar_stress_total, dtype=float)
        if locked is not None:
            short_stress = short_stress - locked
        states = (long.cracked_state,
                  dataclasses.replace(combined.short_term, bar_stress=short_stress))
        types = ["mild"] * len(blocks.bars) + ["prestress"] * len(blocks.tendons)
        evaluations = tuple(evaluate_crack_width(
            section, state, ratio, fctm=numbers["sls_fctm"], Es=moduli, kt=kt,
            bar_diameter=diameter, k1=k1, edition=EDITION, n_mult=multipliers,
            reinforcement_types=types, bond_ratio_xi=None,
        ) for state, ratio, (_name, _key, kt) in zip(states, ratios, _CASES))
    else:
        states = (None, None)
        evaluations = (
            CrackWidthEvaluation("NOT APPLICABLE", "The section is uncracked."),
            CrackWidthEvaluation("NOT APPLICABLE", "The section is uncracked."),
        )
    cases = tuple(Case(name, key, kt, ratio, evaluation, state,
                       _payload(evaluation.result, blocks))
                  for (name, key, kt), ratio, evaluation, state in
                  zip(_CASES, ratios, evaluations, states))
    expected: dict[str, Any] = {
        "converged": True, "cracked": cracked, "lambda_cr": factor,
        "sigma_ct": sigma_ct, "fctm": numbers["sls_fctm"], "show_cw": True,
        "props_un": _props(props_un),
        "props_cr": None if props_cr is None else _props(props_cr),
        "crack": cases[0].payload, "crack_short": cases[1].payload,
    }
    if cracked:
        expected.update(crack_code=CODE, crack_edition=EDITION, crack_member=None)
    expected["crack_output"] = crack_outputs(
        {"Long-term": cases[0].payload, "Short-term": cases[1].payload}, valid=True)
    _outputs(candidate, expected)
    return Replay(blocks, cases, inputs, expected, cracked, factor, sigma_ct,
                  props_un, props_cr)


def _trace_result(value: float) -> TraceResult:
    number = float(value)
    if math.isfinite(number):
        return TraceResult(RESULT_FINITE, number)
    if number > 0.0:
        return TraceResult(RESULT_POSITIVE_INFINITY, None, "Positive infinity")
    return TraceResult(RESULT_UNDEFINED, None, "Undefined reconstructed value")


def _step(
    step_id: str, title: str, value: float, unit: TraceUnit, role: str, source: Any,
    dependencies: Sequence[TraceStep] = (), *, expression: str = "Independent replay",
    result: TraceResult | None = None,
) -> TraceStep:
    return TraceStep(
        step_id=step_id, title=title,
        dependencies=tuple(TraceDependency(item.step_id, item.unit)
                           for item in dependencies),
        quantity_role=role, source=source, symbol=step_id, unit=unit,
        actual_expression=expression,
        substituted_expression=(format(float(value), ".17g")
                                if math.isfinite(float(value)) else str(value)),
        result=_trace_result(value) if result is None else result,
    )


def _digest_steps(
    groups: Sequence[tuple[str, Any]], *, source: Any, role: str,
    dependencies: Sequence[TraceStep] = (), prefix: str = "input",
) -> list[TraceStep]:
    result = []
    for label, value in groups:
        token = trace_identity_token(label)
        for index, word in enumerate(_words(value), start=1):
            result.append(_step(
                f"{prefix}-{token}-sha256-{index}",
                f"Sealed {label} identity word {index}", word, ONE, role, source,
                dependencies, expression="SHA-256 word over exact retained identity",
            ))
    return result


def _member_shape(member_id: str, calculation: TraceCalculation,
                  states: frozenset[str]) -> MemberShape:
    return MemberShape(
        member_id, calculation.calculation_id, calculation.axes,
        tuple((step.step_id, step.quantity_role, step.source,
               tuple(dep.step_id for dep in step.dependencies))
              for step in calculation.steps), states,
    )


def _candidate_steps(item: Any, position: int,
                     roots: Sequence[TraceStep]) -> tuple[list[TraceStep], TraceStep]:
    prefix = f"candidate-{position:04d}"
    fields = (
        ("index", item.bar_index + 1, ONE, SELECTION),
        ("x", item.x, LENGTH, GEOMETRY), ("y", item.y, LENGTH, GEOMETRY),
        ("area", item.area, AREA_MM2, GEOMETRY),
        ("sigma-s", item.sigma_s, STRESS, ELASTIC),
        ("hc-eff", item.hc_ef, LENGTH, EFFECTIVE_AREA),
        ("ac-eff", item.ac_eff, AREA, EFFECTIVE_AREA),
        ("as-eff", item.as_eff, AREA, EFFECTIVE_AREA),
        ("ap-eff", item.ap_eff, AREA, EFFECTIVE_AREA),
        ("ap-eff-weighted", item.ap_eff_weighted, AREA, EFFECTIVE_AREA),
        ("rho-p-eff", item.rho_p_eff, ONE, EFFECTIVE_AREA),
        ("phi", item.phi, LENGTH_MM, GEOMETRY),
        ("cover", item.cover, LENGTH_MM, GEOMETRY),
        ("esm-ecm", item.esm_ecm, STRAIN, MEAN_STRAIN),
        ("sr-max", item.sr_max, LENGTH_MM,
         SPACING_WIDE if item.sr_max_geometric else SPACING_CLOSE),
    )
    steps = [_step(f"{prefix}-{name}", name.replace("-", " ").title(), value,
                   unit, ROLE_COMPUTED, source, roots)
             for name, value, unit, source in fields]
    categories = (
        item.reinforcement_type, item.scope, item.coarse, item.edition, item.kw,
        item.k1_r, item.kfl, item.sr_max_geometric, item.direction_deg, item.xi1,
        item.bc_ef, item.direct_tension,
    )
    categorical = _step(
        f"{prefix}-categorical", "Candidate categorical identity",
        _words(categories)[0], ONE, ROLE_COMPUTED, BOUNDARY, (*roots, *steps),
        expression="SHA-256 word over categorical candidate identity",
    )
    steps.append(categorical)
    width = _step(
        f"{prefix}-wk", "Candidate characteristic crack width", item.wk,
        LENGTH_MM, ROLE_COMPUTED, CRACK_WIDTH, tuple(steps),
        expression="w_k = s_r,max * (epsilon_sm - epsilon_cm)",
    )
    steps.append(width)
    return steps, width


def _case_calculation(replay: Replay, case: Case, context: Mapping[str, Any]
                      ) -> tuple[MemberShape, TraceCalculation]:
    steps = _digest_steps(replay.inputs, source=INPUT, role=ROLE_USER_INPUT)
    input_roots = tuple(steps)
    output = _digest_steps(
        ((f"{case.name}-output", case.payload),), source=BOUNDARY,
        role=ROLE_COMPUTED, dependencies=input_roots, prefix="output",
    )
    steps.extend(output)
    controls = dict(dict(replay.inputs)["controls"])
    suffix = "l" if case.name == "long-term" else "s"
    actions = [_step(f"input-{key.lower()}", key, float(controls[key]), unit,
                     ROLE_USER_INPUT, INPUT)
               for key, unit in ((f"P_el_{suffix}", FORCE),
                                 (f"Mx_el_{suffix}", MOMENT),
                                 (f"My_el_{suffix}", MOMENT))]
    methods = [
        _step("case-modular-ratio", "Case modular ratio", case.modular_ratio,
              ONE, ROLE_METHOD_VALUE, ELASTIC),
        _step("case-kt", "Load-duration coefficient", case.kt, ONE,
              ROLE_METHOD_VALUE, MEAN_STRAIN),
    ]
    steps.extend(actions)
    steps.extend(methods)
    roots = (*input_roots, *output, *actions, *methods)
    if case.evaluation.result is None:
        final = _step(
            "crack-width-result", "Characteristic crack width", 0.0, LENGTH_MM,
            ROLE_FINAL, SELECTION, roots,
            expression="Publish explicit undefined/not-applicable disposition",
            result=TraceResult(RESULT_UNDEFINED, None, case.evaluation.reason),
        )
        steps.append(final)
        states, branch = UNDEFINED_STATES, "not-applicable"
    else:
        plane = [_step(
            f"cracked-state-{name}", f"Concrete-reference plane {name}", value,
            RAW_STRESS if name == "q0" else RAW_GRADIENT, ROLE_COMPUTED, ELASTIC,
            roots,
        ) for name, value in zip(("q0", "qx", "qy"),
                                 (case.state.eps0, case.state.kx, case.state.ky))]
        steps.extend(plane)
        stresses = [_step(
            f"element-{index:04d}-stress", f"Element {index} stress",
            float(value) / 1000.0, STRESS, ROLE_COMPUTED, ELASTIC, plane,
        ) for index, value in enumerate(np.asarray(case.state.bar_stress), start=1)]
        steps.extend(stresses)
        finals = []
        for index, item in enumerate(case.evaluation.result.candidates, start=1):
            created, width = _candidate_steps(item, index, (*roots, *plane, *stresses))
            steps.extend(created)
            finals.append(width)
        final = _step(
            "crack-width-result", "Governing characteristic crack width",
            case.evaluation.result.wk, LENGTH_MM, ROLE_FINAL, SELECTION,
            (*roots, *finals), expression="Select largest candidate crack width",
        )
        steps.append(final)
        states, branch = SUCCESS_STATES, "calculated"
    axes = context_axes(
        context, crack_branch=branch, crack_case=case.name,
        crack_code=trace_identity_token(CODE),
        crack_direction="dominant-strain-gradient", crack_edition=EDITION,
        crack_system="fine",
    )
    calculation = TraceCalculation(
        calculation_id=f"ct-009-{context_id(context)}-{case.name}-base-crack-width",
        coverage_id=COVERAGE_ID,
        title=f"EN 1992-1-1:2004 {case.name} crack width",
        method_id=METHOD_ID, axes=axes, final_step_id=final.step_id,
        steps=tuple(steps), warnings=(CRACK_DIRECTIONAL_LIMITATION,),
        assumptions=(
            "No crack limit, utilisation, verdict, DK rule, or bridge rule is inferred.",
        ),
    )
    return _member_shape(case.name, calculation, states), calculation


def _aggregate(replay: Replay, cases: tuple[TraceCalculation, ...],
               context: Mapping[str, Any]) -> tuple[MemberShape, TraceCalculation]:
    steps = _digest_steps(replay.inputs, source=INPUT, role=ROLE_USER_INPUT)
    roots = tuple(steps)
    output = _digest_steps(
        (("retained-output", replay.retained),), source=BOUNDARY,
        role=ROLE_COMPUTED, dependencies=roots, prefix="output",
    )
    steps.extend(output)
    evidence_roots = (*roots, *output)
    state_steps = [
        _step("retained-converged", "Retained convergence", 1.0, ONE,
              ROLE_COMPUTED, ELASTIC, evidence_roots),
        _step("retained-cracked", "Retained cracked state",
              1.0 if replay.cracked else 0.0, ONE, ROLE_COMPUTED, ELASTIC,
              evidence_roots),
        _step("governing-sigma-ct", "Governing Stage I tension", replay.sigma_ct,
              STRESS, ROLE_COMPUTED, ELASTIC, evidence_roots),
        _step("governing-cracking-factor", "Governing cracking factor",
              replay.factor, ONE, ROLE_COMPUTED, ELASTIC, evidence_roots),
    ]
    steps.extend(state_steps)
    property_steps = []
    for prefix, props in (("uncracked", replay.props_un), ("cracked", replay.props_cr)):
        if props is None:
            continue
        for name in _PROPERTIES:
            unit = AREA if name == "area" else LENGTH if name in {"cx", "cy"} else SECOND_MOMENT
            property_steps.append(_step(
                f"{prefix}-property-{name.lower()}", f"{prefix} property {name}",
                float(getattr(props, name)), unit, ROLE_COMPUTED, ELASTIC,
                (*evidence_roots, *state_steps),
            ))
    steps.extend(property_steps)
    case_steps = []
    for index, calculation in enumerate(cases, start=1):
        result = next(step.result for step in calculation.steps
                      if step.step_id == calculation.final_step_id)
        case_steps.append(_step(
            f"case-{index}-final", f"Ordered case {index} disposition",
            result.value or 0.0, LENGTH_MM, ROLE_COMPUTED, SELECTION,
            (*evidence_roots, *state_steps, *property_steps), result=result,
        ))
    steps.extend(case_steps)
    finite = [step.result.value for step in case_steps
              if step.result.state == RESULT_FINITE and step.result.value is not None]
    infinite = any(step.result.state == RESULT_POSITIVE_INFINITY for step in case_steps)
    if finite or infinite:
        value = math.inf if infinite else max(finite)
        final = _step(
            "crack-width-aggregate-result", "Governing retained crack width", value,
            LENGTH_MM, ROLE_FINAL, SELECTION, tuple(steps),
            expression="Select largest calculated case crack width",
        )
        states, branch = SUCCESS_STATES, "calculated"
    else:
        final = _step(
            "crack-width-aggregate-result", "Governing retained crack width", 0.0,
            LENGTH_MM, ROLE_FINAL, SELECTION, tuple(steps),
            result=TraceResult(RESULT_UNDEFINED, None,
                               "No retained crack-width case is applicable."),
        )
        states, branch = UNDEFINED_STATES, "not-applicable"
    steps.append(final)
    axes = context_axes(
        context, crack_branch=branch, crack_case="aggregate",
        crack_code=trace_identity_token(CODE), crack_edition=EDITION,
        crack_member_cardinality=str(len(cases)),
    )
    calculation = TraceCalculation(
        calculation_id=f"ct-009-{context_id(context)}-base-crack-width-aggregate",
        coverage_id=COVERAGE_ID, title="EN 1992-1-1:2004 crack-width aggregate",
        method_id=METHOD_ID, axes=axes, final_step_id=final.step_id,
        steps=tuple(steps), warnings=(CRACK_DIRECTIONAL_LIMITATION,),
        assumptions=("Case order is long-term then short-term; no verdict is implied.",),
    )
    return _member_shape("aggregate", calculation, states), calculation


def _failure(replay: FailedReplay, context: Mapping[str, Any]
             ) -> tuple[MemberShape, TraceCalculation]:
    steps = _digest_steps(replay.inputs, source=INPUT, role=ROLE_USER_INPUT)
    roots = tuple(steps)
    output = _digest_steps(
        (("failure-output-shape", replay.output_shape),), source=BOUNDARY,
        role=ROLE_COMPUTED, dependencies=roots, prefix="output",
    )
    steps.extend(output)
    final = _step(
        "crack-width-failed-result", "Crack-width replay failure", 0.0, ONE,
        ROLE_FINAL, BOUNDARY, (*roots, *output),
        result=TraceResult(RESULT_FAILED, None,
                           "Elastic/crack reconstruction did not converge; no value or verdict."),
    )
    steps.append(final)
    axes = context_axes(
        context, crack_branch="failed", crack_case="aggregate",
        crack_code=trace_identity_token(CODE), crack_edition=EDITION,
    )
    calculation = TraceCalculation(
        calculation_id=f"ct-009-{context_id(context)}-base-crack-width-failed",
        coverage_id=COVERAGE_ID, title="EN 1992-1-1:2004 crack-width failure",
        method_id=METHOD_ID, axes=axes, final_step_id=final.step_id,
        steps=tuple(steps), assumptions=(
            "Failure-only candidate numerics are not traversed; no verdict is implied.",
        ),
    )
    return _member_shape("failed", calculation, FAILURE_STATES), calculation


def _expected(
    inp: Mapping[str, Any], out: Mapping[str, Any], *, input_sha256: str,
    result_sha256: str, context: Mapping[str, Any] | None,
) -> TraceBundle | None:
    inp = _map(inp, "CT-009 input")
    out = _map(out, "analysis result")
    trace_context = {} if context is None else _map(context, "CT-009 context")
    if not _dispatch(inp):
        return None
    if _get(inp, "section") is None:
        return None
    replay = _replay(inp, out)
    if isinstance(replay, FailedReplay):
        shape, calculation = _failure(replay, trace_context)
        bundle = create_bundle(input_sha256=input_sha256, result_sha256=result_sha256,
                               calculations=(calculation,))
        return audit_trace_registry(bundle, registry_for((shape,)))
    pairs = tuple(_case_calculation(replay, case, trace_context) for case in replay.cases)
    shapes, calculations = tuple(item[0] for item in pairs), tuple(item[1] for item in pairs)
    aggregate_shape, aggregate = _aggregate(replay, calculations, trace_context)
    bundle = create_bundle(
        input_sha256=input_sha256, result_sha256=result_sha256,
        calculations=(*calculations, aggregate), warnings=(CRACK_DIRECTIONAL_LIMITATION,),
    )
    return audit_trace_registry(bundle, registry_for((*shapes, aggregate_shape)))


def build_crack_trace_family(
    inp: Mapping[str, Any], out: Mapping[str, Any], *, input_sha256: str,
    result_sha256: str, context: Mapping[str, Any] | None = None,
) -> TraceBundle | None:
    return _expected(inp, out, input_sha256=input_sha256,
                     result_sha256=result_sha256, context=context)


def validate_crack_trace_family(
    bundle: TraceBundle | Mapping[str, Any] | None, inp: Mapping[str, Any],
    out: Mapping[str, Any], *, input_sha256: str, result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle | None:
    expected = _expected(inp, out, input_sha256=input_sha256,
                         result_sha256=result_sha256, context=context)
    if expected is None:
        if bundle is not None:
            raise TraceValidationError("inactive CT-009 selector cannot retain a trace")
        return None
    if bundle is None:
        raise TraceValidationError("active CT-009 result requires a trace")
    candidate = validate_bundle(
        bundle, expected_input_sha256=input_sha256,
        expected_result_sha256=result_sha256,
    )
    if candidate != expected:
        raise TraceValidationError("CT-009 trace differs from independent reconstruction")
    return candidate


__all__ = ("build_crack_trace_family", "validate_crack_trace_family")
