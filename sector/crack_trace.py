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
    FAMILY_ID,
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
    SECOND_MOMENT,
    SELECTION,
    SPACING_CLOSE,
    SPACING_WIDE,
    STRESS,
    STRAIN,
    SUCCESS_STATES,
    FAILURE_STATES,
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
_INPUT_GROUPS = (
    "geometry",
    "materials",
    "assignments-and-catalogues",
    "crack-controls-and-actions",
)
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
    section: Section
    cases: tuple[CaseReplay, ...]
    retained: Mapping[str, Any]
    input_groups: tuple[tuple[str, Any], ...]
    cracked: bool
    factor: float
    sigma_ct: float
    props_un: Any
    props_cr: Any | None


def _mapping(value: Any, label: str, *, exact: bool = False) -> Mapping[str, Any]:
    if (type(value) is not dict) if exact else (not isinstance(value, Mapping)):
        adjective = "an exact built-in dict" if exact else "a mapping"
        raise TraceValidationError(f"{label} must be {adjective}")
    if any(type(key) is not str for key in value):
        raise TraceValidationError(f"{label} keys must be text")
    return value


def _sequence(value: Any, label: str) -> tuple[Any, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TraceValidationError(f"{label} must be an aligned sequence")
    return tuple(value)


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
    """Create an exact order/type/float-bit identity tree."""

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
                "dataclass", value.__class__.__module__,
                value.__class__.__qualname__,
                [[field.name, _typed(getattr(value, field.name), active)]
                 for field in dataclasses.fields(value)],
            ]
        if isinstance(value, Mapping):
            return [
                "mapping", value.__class__.__module__,
                value.__class__.__qualname__,
                [[_typed(key, active), _typed(item, active)]
                 for key, item in value.items()],
            ]
        if type(value) in {list, tuple}:
            return [type(value).__name__, [_typed(item, active) for item in value]]
        if hasattr(value, "__dict__"):
            return [
                "object", value.__class__.__module__,
                value.__class__.__qualname__, _typed(vars(value), active),
            ]
        slots = getattr(value.__class__, "__slots__", ())
        if slots:
            names = (slots,) if type(slots) is str else tuple(slots)
            return [
                "slots", value.__class__.__module__,
                value.__class__.__qualname__,
                [[name, _typed(getattr(value, name), active)]
                 for name in names if hasattr(value, name)],
            ]
    finally:
        active.remove(identity)
    raise TraceValidationError(
        "unsupported CT-009 identity type "
        f"{type(value).__module__}.{type(value).__qualname__}"
    )


def _digest_words(value: Any) -> tuple[float, ...]:
    encoded = json.dumps(
        _typed(value), ensure_ascii=True, separators=(",", ":"),
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
    records = _sequence(inp.get(key), key)
    sealed = []
    for position, raw in enumerate(records, start=1):
        record = _mapping(raw, f"{key}[{position - 1}]", exact=True)
        if "fatigue_detail_id" not in record:
            raise TraceValidationError(
                f"{key}[{position - 1}] must retain fatigue_detail_id"
            )
        if type(record["fatigue_detail_id"]) is not str:
            raise TraceValidationError(
                f"{key}[{position - 1}].fatigue_detail_id must retain text type"
            )
        sealed.append(tuple(
            (name, ["inert-text", "fatigue-detail-value-excluded"])
            if name == "fatigue_detail_id" else (name, value)
            for name, value in record.items()
        ))
    return tuple(sealed)


def _input_identity(
    inp: Mapping[str, Any], blocks: SectionTraceBlocks,
) -> tuple[tuple[str, Any], ...]:
    """Freeze every base-method input while keeping fatigue IDs value-inert."""

    geometry = {
        "section": inp["section"],
        "outer": inp.get("outer"),
        "holes": inp.get("holes"),
        "bars": inp.get("bars"),
        "tendons": inp.get("tendons"),
        "resolved": blocks.geometry,
    }
    materials = {
        "concrete": inp.get("concrete"),
        "steel": inp.get("steel"),
        "prestress": inp.get("prestress"),
        "bar_materials": inp.get("bar_materials"),
        "tendon_materials": inp.get("tendon_materials"),
        "concrete_material_id": (
            inp["concrete_material_id"]
            if "concrete_material_id" in inp else ["missing"]
        ),
        "concrete_preset": inp.get("concrete_preset"),
        "mild_preset": inp.get("mild_preset"),
        "prestress_preset": inp.get("prestress_preset"),
        "resolved": (blocks.concrete, blocks.bars, blocks.tendons),
    }
    assignments = {
        "bar_elements": _element_identity(inp, "bar_elements"),
        "tendon_elements": _element_identity(inp, "tendon_elements"),
        "mild_material_catalog": inp.get("mild_material_catalog"),
        "prestress_material_catalog": inp.get("prestress_material_catalog"),
    }
    controls = tuple(
        (
            key,
            ["inert-sibling-type", type(inp[key]).__module__,
             type(inp[key]).__qualname__]
            if key in {"sls_tendon_xi", "sls_member"}
            else inp[key],
        )
        for key in (
            "mode", "P_el_l", "Mx_el_l", "My_el_l", "P_el_s",
            "Mx_el_s", "My_el_s", "conc_Ec", "el_phi", "nl", "ns",
            "sls_fctm", "sls_cw", "sls_phi", "sls_k1",
            "sls_tendon_xi", "sls_code", "sls_edition", "sls_dk_na",
            "sls_member",
        )
    )
    return tuple(zip(
        _INPUT_GROUPS,
        (geometry, materials, assignments, controls),
    ))


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


def _crack_payload(result: Any, blocks: SectionTraceBlocks) -> dict[str, Any] | None:
    """Reconstruct the retained app serializer without trusting its selection."""

    if result is None:
        return None
    bar_ids = [item.element_id for item in blocks.bars]
    tendon_ids = [item.element_id for item in blocks.tendons]
    n_bars = len(bar_ids)

    def identity(index: int) -> tuple[str, int, str]:
        if index < n_bars:
            return "Bar", index + 1, bar_ids[index]
        tendon_index = index - n_bars
        return "Tendon", tendon_index + 1, tendon_ids[tendon_index]

    def candidate(item: Any) -> dict[str, Any]:
        kind, number, element_id = identity(item.bar_index)
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
            np.all(np.isfinite(np.asarray(value, dtype=float)))
            for value in values
        )
    except (TypeError, ValueError):
        return False


def _validate_dispatch(inp: Mapping[str, Any]) -> bool:
    for key in ("mode", "sls_code", "sls_edition", "sls_member"):
        if key not in inp:
            raise TraceValidationError(f"CT-009 requires {key}")
        _text(inp[key], key)
    for key in ("sls_cw", "sls_dk_na"):
        if key not in inp:
            raise TraceValidationError(f"CT-009 requires {key}")
        _bool(inp[key], key)
    if "sls_tendon_xi" not in inp:
        raise TraceValidationError("CT-009 requires sls_tendon_xi")
    if type(inp["sls_tendon_xi"]) not in {int, float}:
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


def _validate_numerical_inputs(inp: Mapping[str, Any]) -> dict[str, float]:
    values = {
        key: _number(inp[key], key)
        for key in (
            "P_el_l", "Mx_el_l", "My_el_l", "P_el_s", "Mx_el_s",
            "My_el_s",
        )
    }
    for key in ("conc_Ec", "nl", "ns", "sls_fctm", "sls_k1"):
        values[key] = _number(inp[key], key, positive=True)
    values["el_phi"] = _number(inp["el_phi"], "el_phi")
    values["sls_phi"] = _number(inp["sls_phi"], "sls_phi")
    if values["el_phi"] < 0.0 or values["sls_phi"] < 0.0:
        raise TraceValidationError("creep and diameter overrides must be non-negative")
    expected_ns = STEEL_REFERENCE_MODULUS / (values["conc_Ec"] * 1000.0)
    expected_nl = expected_ns * (1.0 + values["el_phi"])
    for key, expected in (("ns", expected_ns), ("nl", expected_nl)):
        if not math.isclose(values[key], expected, rel_tol=1.0e-12, abs_tol=0.0):
            raise TraceValidationError(
                f"{key} is stale relative to conc_Ec and el_phi"
            )
    return values


def _retained_candidate(out: Mapping[str, Any]) -> Mapping[str, Any]:
    elastic = _mapping(out.get("elastic"), "CT-009 elastic output", exact=True)
    return elastic


def _check_output_inventory(
    candidate: Mapping[str, Any], expected: Mapping[str, Any],
) -> None:
    expected_order = tuple(expected)
    owned_scalars = {
        "converged", "cracked", "lambda_cr", "sigma_ct", "fctm", "show_cw",
    }
    actual_order = tuple(
        key for key in candidate
        if key in owned_scalars
        or key.startswith("crack")
        or key.startswith("props_")
    )
    if actual_order != expected_order:
        raise TraceValidationError(
            "CT-009 retained output inventory/order differs from replay"
        )
    for key, value in expected.items():
        _same_exact(candidate[key], value, f"elastic.{key}")


def _replay(inp: Mapping[str, Any], out: Mapping[str, Any]) -> CrackReplay:
    numbers = _validate_numerical_inputs(inp)
    try:
        blocks = section_trace_blocks(inp)
        section = _folded_section(blocks)
    except TraceValidationError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"invalid CT-009 section identity: {exc}") from exc

    moduli = np.asarray(
        [_law_value(item, "Es") for item in (*blocks.bars, *blocks.tendons)],
        dtype=float,
    )
    if not moduli.size:
        raise TraceValidationError("CT-009 needs crack-control reinforcement")
    if np.any(moduli <= 0.0) or np.any(~np.isfinite(moduli)):
        raise TraceValidationError("assigned reinforcement moduli must be positive")
    n_mult = moduli / STEEL_REFERENCE_MODULUS
    locked = None
    if blocks.tendons:
        locked = np.asarray(
            [0.0] * len(blocks.bars) + [
                _law_value(item, "Es") * _law_value(item, "IS") * 1000.0
                for item in blocks.tendons
            ],
            dtype=float,
        )

    p_long = -numbers["P_el_l"]
    p_short = -numbers["P_el_s"]
    combined = solve_elastic_combined(
        section,
        p_long, numbers["Mx_el_l"], numbers["My_el_l"], numbers["nl"],
        p_short, numbers["Mx_el_s"], numbers["My_el_s"], numbers["ns"],
        n_mult=n_mult,
        prestress_stress=locked,
    )
    long = analyse_cracking(
        section,
        p_long, numbers["Mx_el_l"], numbers["My_el_l"], numbers["nl"],
        fctm=numbers["sls_fctm"],
        Es=moduli,
        beta=0.5,
        kt=0.4,
        bar_diameter=(
            numbers["sls_phi"] if numbers["sls_phi"] > 0.0 else [
                _number(item["diameter_mm"], "element diameter", positive=True)
                for item in (
                    list(_sequence(inp["bar_elements"], "bar_elements"))
                    + list(_sequence(inp["tendon_elements"], "tendon_elements"))
                )
            ]
        ),
        k1=(
            [numbers["sls_k1"]] * len(blocks.bars)
            + [1.6] * len(blocks.tendons)
        ),
        edition=EDITION,
        n_mult=n_mult,
        prestress_stress=locked,
    )
    peak_cracked, peak_factor, peak_sigma = combined_cracking(
        section,
        p_long, numbers["Mx_el_l"], numbers["My_el_l"], numbers["nl"],
        p_short, numbers["Mx_el_s"], numbers["My_el_s"], numbers["ns"],
        fctm=numbers["sls_fctm"],
        n_mult=n_mult,
        prestress_stress=locked,
    )
    converged = (
        _finite_solver(combined)
        and bool(long.uncracked.converged)
        and bool(long.cracked_state.converged)
    )
    candidate = _retained_candidate(out)
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
        expected_aggregate = {
            "value": None,
            "case": None,
            "governing": None,
            "unit": "mm",
            "calculation_state": "INVALID",
        }
        _same_exact(
            aggregate,
            expected_aggregate,
            "failed CT-009 crack_output",
        )
        raise TraceValidationError(
            "CT-009 numerical replay failed; use build failure path"
        )

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
        if cracked else None
    )

    diameter = (
        numbers["sls_phi"] if numbers["sls_phi"] > 0.0 else [
            _number(item["diameter_mm"], "element diameter", positive=True)
            for item in (
                list(_sequence(inp["bar_elements"], "bar_elements"))
                + list(_sequence(inp["tendon_elements"], "tendon_elements"))
            )
        ]
    )
    k1 = [numbers["sls_k1"]] * len(blocks.bars) + [1.6] * len(blocks.tendons)
    reinforcement_types = (
        ["mild"] * len(blocks.bars) + ["prestress"] * len(blocks.tendons)
    )
    if cracked:
        short_stress = np.asarray(combined.bar_stress_total, dtype=float)
        if locked is not None:
            short_stress = short_stress - locked
        short_state = dataclasses.replace(
            combined.short_term, bar_stress=short_stress
        )
        states = (long.cracked_state, short_state)
        ratios = (numbers["nl"], numbers["ns"])
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
        ratios = (numbers["nl"], numbers["ns"])
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
        section=section,
        cases=cases,
        retained=expected,
        input_groups=_input_identity(inp, blocks),
        cracked=cracked,
        factor=factor,
        sigma_ct=sigma_ct,
        props_un=props_un,
        props_cr=props_cr,
    )


def _result(value: float) -> TraceResult:
    number = float(value)
    if math.isinf(number):
        return TraceResult(
            RESULT_POSITIVE_INFINITY,
            None,
            "The independently replayed value is positive infinity.",
        )
    if not math.isfinite(number):
        return TraceResult(
            RESULT_UNDEFINED,
            None,
            "The independently replayed value is undefined.",
        )
    return TraceResult(RESULT_FINITE, number)


def _format(value: float) -> str:
    return format(float(value), ".17g")


def _step(
    step_id: str,
    title: str,
    value: float,
    unit: TraceUnit,
    role: str,
    source: Any,
    dependencies: Sequence[TraceStep] = (),
    *,
    expression: str = "Retain independently replayed value",
    state: TraceResult | None = None,
) -> TraceStep:
    result = _result(value) if state is None else state
    shown = (
        _format(value) if result.state == RESULT_FINITE else result.state
    )
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
        substituted_expression=f"{step_id} = {shown} {unit.symbol}",
        result=result,
    )


def _identity_steps(
    groups: tuple[tuple[str, Any], ...],
    retained: Any,
) -> list[TraceStep]:
    steps: list[TraceStep] = []
    payloads = (*groups, ("retained-output", retained))
    for name, payload in payloads:
        for position, word in enumerate(_digest_words(payload), start=1):
            retained_output = name == "retained-output"
            steps.append(_step(
                f"identity-{name}-sha256-{position}",
                f"{name.replace('-', ' ').title()} identity word {position}",
                word,
                ONE,
                ROLE_COMPUTED if retained_output else ROLE_USER_INPUT,
                BOUNDARY if retained_output else INPUT,
                tuple(steps) if retained_output else (),
                expression="SHA-256 word over exact typed ordered identity",
            ))
    return steps


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
                step.title,
                step.unit,
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
    steps = _identity_steps(replay.input_groups, case.output)
    identity = tuple(steps)
    action_suffix = "l" if case.name == "long-term" else "s"
    action_steps = []
    for key, title, unit in (
        (f"P_el_{action_suffix}", "Axial action", FORCE),
        (f"Mx_el_{action_suffix}", "Bending action Mx", MOMENT),
        (f"My_el_{action_suffix}", "Bending action My", MOMENT),
    ):
        value = dict(replay.input_groups)["crack-controls-and-actions"]
        raw = dict(value)[key]
        action_steps.append(_step(
            f"input-{trace_identity_token(key)}",
            title,
            float(raw),
            unit,
            ROLE_USER_INPUT,
            INPUT,
        ))
    scalar_steps = [
        _step("case-modular-ratio", "Case modular ratio", case.n, ONE,
              ROLE_METHOD_VALUE, ELASTIC),
        _step("case-kt", "Load-duration coefficient", case.kt, ONE,
              ROLE_METHOD_VALUE, MEAN_STRAIN),
    ]
    steps.extend(action_steps)
    steps.extend(scalar_steps)
    roots = (*identity, *action_steps, *scalar_steps)

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
            state=TraceResult(
                RESULT_UNDEFINED,
                None,
                case.evaluation.reason,
            ),
        )
        steps.append(final)
        states = NOT_APPLICABLE_STATES
    else:
        result = case.evaluation.result
        state = case.state
        for component, value in zip(
            ("q0", "qx", "qy"),
            (state.eps0, state.kx, state.ky),
        ):
            steps.append(_step(
                f"cracked-state-{component}",
                f"Cracked-state plane {component}",
                value,
                ONE,
                ROLE_COMPUTED,
                ELASTIC,
                roots,
            ))
        plane_steps = tuple(steps[-3:])
        for index, stress in enumerate(np.asarray(state.bar_stress), start=1):
            steps.append(_step(
                f"element-{index:04d}-stress",
                f"Element {index} load-induced tension stress",
                float(stress) / 1000.0,
                STRESS,
                ROLE_COMPUTED,
                ELASTIC,
                plane_steps,
            ))
        stress_steps = tuple(steps[-len(np.asarray(state.bar_stress)):])

        candidate_finals = []
        for position, item in enumerate(result.candidates, start=1):
            prefix = f"candidate-{position:04d}"
            candidate_root = (*roots, *plane_steps, *stress_steps)
            fields = (
                ("bar-index", "Element solver index", item.bar_index + 1,
                 ONE, ROLE_COMPUTED, SELECTION),
                ("x", "Element x coordinate", item.x, LENGTH,
                 ROLE_USER_INPUT, INPUT),
                ("y", "Element y coordinate", item.y, LENGTH,
                 ROLE_USER_INPUT, INPUT),
                ("area", "Element area", item.area, AREA_MM2,
                 ROLE_USER_INPUT, INPUT),
                ("sigma-s", "Steel stress", item.sigma_s, STRESS,
                 ROLE_COMPUTED, ELASTIC),
                ("hc-eff", "Effective tension height", item.hc_ef, LENGTH,
                 ROLE_COMPUTED, EFFECTIVE_AREA),
                ("ac-eff", "Effective concrete tension area", item.ac_eff, AREA,
                 ROLE_COMPUTED, EFFECTIVE_AREA),
                ("as-eff", "Effective mild reinforcement area", item.as_eff, AREA,
                 ROLE_COMPUTED, EFFECTIVE_AREA),
                ("ap-eff", "Effective prestressing area", item.ap_eff, AREA,
                 ROLE_COMPUTED, EFFECTIVE_AREA),
                ("ap-eff-weighted", "Weighted prestressing area",
                 item.ap_eff_weighted, AREA, ROLE_COMPUTED, EFFECTIVE_AREA),
                ("rho-p-eff", "Effective reinforcement ratio", item.rho_p_eff,
                 ONE, ROLE_COMPUTED, EFFECTIVE_AREA),
                ("phi", "Element diameter", item.phi, LENGTH_MM,
                 ROLE_COMPUTED, GEOMETRY),
                ("cover", "Element clear cover", item.cover, LENGTH_MM,
                 ROLE_COMPUTED, GEOMETRY),
                ("esm-ecm", "Mean strain difference", item.esm_ecm, STRAIN,
                 ROLE_COMPUTED, MEAN_STRAIN),
                ("sr-max", "Maximum crack spacing", item.sr_max, LENGTH_MM,
                 ROLE_COMPUTED,
                 SPACING_WIDE if item.sr_max_geometric else SPACING_CLOSE),
            )
            created = []
            for suffix, title, value, unit, role, source in fields:
                dependencies = () if role == ROLE_USER_INPUT else candidate_root
                created.append(_step(
                    f"{prefix}-{suffix}",
                    title,
                    value,
                    unit,
                    role,
                    source,
                    dependencies,
                ))
            steps.extend(created)
            categorical = (
                item.reinforcement_type,
                item.scope,
                item.coarse,
                item.edition,
                item.sr_max_geometric,
                item.direction_deg,
                item.xi1,
                item.bc_ef,
                item.direct_tension,
            )
            category = _step(
                f"{prefix}-categorical-identity",
                "Candidate categorical and branch identity",
                _digest_words(categorical)[0],
                ONE,
                ROLE_COMPUTED,
                BOUNDARY,
                (*candidate_root, *created),
                expression="SHA-256 word over omitted retained candidate fields",
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
        states = SUCCESS_STATES

    axes = context_axes(
        context,
        crack_branch=("calculated" if case.evaluation.result is not None
                      else "not-applicable"),
        crack_case=case.name,
        crack_code=trace_identity_token(CODE),
        crack_direction="dominant-strain-gradient",
        crack_edition=EDITION,
        crack_system="fine",
    )
    calculation_id = (
        f"ct-009-{context_id(context)}-{case.name}-base-crack-width"
    )
    calculation = TraceCalculation(
        calculation_id=calculation_id,
        coverage_id=COVERAGE_ID,
        title=f"EN 1992-1-1:2004 {case.name} crack width",
        method_id=METHOD_ID,
        axes=axes,
        final_step_id=final.step_id,
        steps=tuple(steps),
        warnings=(CRACK_DIRECTIONAL_LIMITATION,),
        assumptions=(
            "This member replays only the selected EN 1992-1-1:2004 base method.",
            "No crack-width limit, utilisation, compliance verdict or DK/bridge rule is inferred.",
        ),
    )
    return _shape(case.name, calculation, states), calculation


def _aggregate_member(
    replay: CrackReplay,
    case_calculations: tuple[TraceCalculation, ...],
    context: Mapping[str, Any],
) -> tuple[MemberShape, TraceCalculation]:
    steps = _identity_steps(replay.input_groups, replay.retained)
    roots = tuple(steps)
    state_steps = [
        _step("retained-converged", "Retained convergence state", 1.0, ONE,
              ROLE_COMPUTED, ELASTIC, roots),
        _step("retained-cracked", "Retained cracked state",
              1.0 if replay.cracked else 0.0, ONE,
              ROLE_COMPUTED, ELASTIC, roots),
        _step("governing-sigma-ct", "Governing Stage I concrete tension",
              replay.sigma_ct, STRESS, ROLE_COMPUTED, ELASTIC, roots),
    ]
    factor_state = None
    if math.isinf(replay.factor):
        factor_state = TraceResult(
            RESULT_POSITIVE_INFINITY,
            None,
            "No retained action path reaches first cracking finitely.",
        )
    state_steps.append(_step(
        "governing-cracking-factor",
        "Governing first-cracking factor",
        replay.factor if math.isfinite(replay.factor) else 0.0,
        ONE,
        ROLE_COMPUTED,
        ELASTIC,
        roots,
        state=factor_state,
    ))
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
                AREA if name == "area" else
                LENGTH if name in {"cx", "cy"} else
                SECOND_MOMENT
            )
            property_steps.append(_step(
                f"{prefix}-property-{name.lower()}",
                f"{prefix.title()} transformed property {name}",
                float(getattr(props, name)),
                unit,
                ROLE_COMPUTED,
                ELASTIC,
                (*roots, *state_steps),
            ))
    steps.extend(property_steps)
    case_words = []
    for position, calculation in enumerate(case_calculations, start=1):
        final = calculation.steps[-1]
        value = final.result.value if final.result.value is not None else 0.0
        case_words.append(_step(
            f"case-{position}-final",
            f"Ordered case {position} final disposition",
            value,
            LENGTH_MM,
            ROLE_COMPUTED,
            SELECTION,
            (*roots, *state_steps, *property_steps),
            state=final.result,
        ))
    steps.extend(case_words)
    calculated = [
        item.result.value for item in case_words
        if item.result.state == RESULT_FINITE
    ]
    if calculated:
        final = _step(
            "crack-width-aggregate-result",
            "Governing retained crack width",
            max(calculated),
            LENGTH_MM,
            ROLE_FINAL,
            SELECTION,
            tuple(steps),
            expression="Select largest calculated case crack width",
        )
        states = SUCCESS_STATES
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
            state=TraceResult(
                RESULT_UNDEFINED,
                None,
                "No retained crack-width case is applicable.",
            ),
        )
        states = NOT_APPLICABLE_STATES
    steps.append(final)
    axes = context_axes(
        context,
        crack_branch="calculated" if calculated else "not-applicable",
        crack_case="aggregate",
        crack_code=trace_identity_token(CODE),
        crack_edition=EDITION,
        crack_member_cardinality=str(len(case_calculations)),
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
            "Transformed properties are evidence, not crack-width resistance or compliance limits.",
        ),
    )
    return _shape("aggregate", calculation, states), calculation


def _failure_member(
    inp: Mapping[str, Any], out: Mapping[str, Any], context: Mapping[str, Any],
) -> tuple[MemberShape, TraceCalculation]:
    candidate = _retained_candidate(out)
    if candidate.get("converged") is not False:
        raise TraceValidationError(
            "failed CT-009 evidence requires retained converged=false"
        )
    safe_shape = tuple(
        (key, type(candidate[key]).__module__, type(candidate[key]).__qualname__)
        for key in candidate
    )
    steps = []
    controls = (
        ("elastic-mode-enabled", inp["mode"] in _ACTIVE_MODES),
        ("crack-width-requested", inp["sls_cw"]),
        ("base-code-selected", inp["sls_code"] == CODE),
    )
    for step_id, value in controls:
        steps.append(_step(
            step_id,
            step_id.replace("-", " ").title(),
            1.0 if value else 0.0,
            ONE,
            ROLE_USER_INPUT,
            INPUT,
        ))
    control_steps = tuple(steps)
    for position, word in enumerate(_digest_words(safe_shape), start=1):
        steps.append(_step(
            f"failure-shape-sha256-{position}",
            f"Failure payload shape word {position}",
            word,
            ONE,
            ROLE_COMPUTED,
            BOUNDARY,
            control_steps,
            expression="SHA-256 word over failure inventory and retained types",
        ))
    final = _step(
        "crack-width-failed-result",
        "Crack-width replay failure",
        0.0,
        ONE,
        ROLE_FINAL,
        BOUNDARY,
        tuple(steps),
        expression="Publish calculation-free failure state",
        state=TraceResult(
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
            "Failure-only numerical fields are deliberately not traversed.",
            "No resistance, utilisation, crack-width value or engineering verdict is implied.",
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
    if inp.get("section") is None:
        return None
    if "elastic" not in out:
        raise TraceValidationError(
            "active CT-009 input is missing the retained elastic output"
        )
    try:
        replay = _replay(inp, out)
    except TraceValidationError as exc:
        if "numerical replay failed" not in str(exc):
            raise
        shape, calculation = _failure_member(inp, out, trace_context)
        bundle = create_bundle(
            input_sha256=input_sha256,
            result_sha256=result_sha256,
            calculations=(calculation,),
        )
        audit_trace_registry(bundle, registry_for((shape,)))
        return bundle

    case_members = tuple(
        _case_member(replay, case, trace_context) for case in replay.cases
    )
    case_calculations = tuple(item[1] for item in case_members)
    aggregate = _aggregate_member(replay, case_calculations, trace_context)
    shapes = tuple(item[0] for item in case_members) + (aggregate[0],)
    calculations = case_calculations + (aggregate[1],)
    bundle = create_bundle(
        input_sha256=input_sha256,
        result_sha256=result_sha256,
        calculations=calculations,
    )
    audit_trace_registry(bundle, registry_for(shapes))
    return bundle


def build_crack_trace_family(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    *,
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle | None:
    """Build the CT-009 base trace after independent input/output replay."""

    try:
        return _expected_bundle(
            inp,
            out,
            input_sha256=input_sha256,
            result_sha256=result_sha256,
            context=context,
        )
    except TraceValidationError:
        raise
    except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError) as exc:
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
    """Reject stale, incomplete, reordered, or coherently resealed evidence."""

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
                "inactive/non-base crack method cannot carry CT-009 base evidence"
            )
        return None
    if bundle is None:
        raise TraceValidationError("active CT-009 base trace is missing")
    candidate = validate_bundle(
        bundle,
        expected_input_sha256=input_sha256,
        expected_result_sha256=result_sha256,
    )
    shapes = tuple(
        _shape(
            f"expected-{position}",
            calculation,
            frozenset({calculation.steps[-1].result.state}),
        )
        for position, calculation in enumerate(expected.calculations, start=1)
    )
    audit_trace_registry(candidate, registry_for(shapes))
    if candidate.to_dict() != expected.to_dict():
        raise TraceValidationError(
            "CT-009 trace differs from authoritative input replay"
        )
    return candidate


__all__ = (
    "FAMILY_ID",
    "build_crack_trace_family",
    "validate_crack_trace_family",
)
