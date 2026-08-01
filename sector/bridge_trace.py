"""Solver-owned unpublished CT-011 retained bridge-kernel trace."""

from __future__ import annotations

import math
import pathlib
import sys
from collections.abc import Mapping
from typing import Any

from . import bridge
from .bridge_trace_contract import (
    BOX_KEYS, BOX_MEMBER_ID, BOX_ROW_KEYS, BRITTLE_KEYS, BRITTLE_MEMBER_ID,
    BRITTLE_ROW_KEYS, BoxShape, BridgeShape, BrittleShape, CALCULATION_ORDER,
    COVERAGE_ID, CRACK_KEYS, CRACK_MEMBER_ID, CRACK_ROW_KEYS, CrackShape,
    ERROR_KEYS, ErrorShape, METHOD_ID, SCOPE_ERROR,
    SCOPE_SUCCESS, STATUS_CODES, SUCCESS_KEYS, WALL_COMMON_COT_WARNING,
    WALL_COT_RANGE_WARNING, component_prefix, error_step_id,
    expected_box_steps, expected_brittle_steps, expected_crack_steps,
    expected_error_steps, expected_registry, region_prefix, wall_prefix,
)
from .calculation_trace import (
    RESULT_FAILED, RESULT_FINITE, RESULT_POSITIVE_INFINITY, RESULT_UNDEFINED,
    TraceBundle, TraceCalculation, TraceDependency, TraceResult, TraceStep,
    TraceValidationError, create_bundle, validate_bundle,
    trace_identity_token,
)
from .detailing_trace import _compare_text_list, _compare_value
from .section_trace_blocks import context_axes, context_id
from .torsion_trace import _mapping, _retained_mapping, _sequence
from .trace_registry import audit_trace_registry


_DRIFT = "authoritative CT-011 output inventory drifted"
_INFINITE_REASON = (
    "Retained bridge row value is unbounded: the finite entered operands "
    "overflow the retained product or ratio."
)
_NAN_REASON = (
    "Retained bridge row value is undefined: the finite entered operands "
    "produce a non-numeric retained ratio."
)


def _bridge_inputs():
    """The retained table normalisation is an app-layer module by design."""

    try:
        import bridge_inputs
    except ImportError:  # pragma: no cover - direct sector-only imports
        sys.path.insert(0, str(
            pathlib.Path(__file__).resolve().parent.parent / "app"))
        import bridge_inputs
    return bridge_inputs


def _replay(inp: Mapping[str, Any]) -> dict[str, Any]:
    """Replay the retained adapter exactly (app._run_bridge_or_invalid)."""

    tables = _bridge_inputs()
    standard = str(inp.get("bridge_standard") or bridge.COMPONENT_METHODS).strip()
    try:
        if standard not in bridge.METHODS:
            raise ValueError(f"unknown selected bridge standard: {standard}")
        # The retained calculate() interleaves per table (records -> kernel
        # per member); calling it directly preserves the exact retained
        # cross-table error precedence. All leaf binding derives from the
        # published calculation rows.
        table_values = {key: inp.get(key) for key in tables.TABLE_KEYS}
        calculations = tables.calculate(table_values, standard=standard)
    except (TypeError, ValueError) as exc:
        raw = inp.get("bridge_standard", bridge.COMPONENT_METHODS)
        if raw is not None and type(raw) is not str:
            raise TraceValidationError(
                "bridge_standard must be text or absent"
            ) from exc
        return {
            "error": str(exc), "standard": standard,
            "expected": {
                "selected_standard": raw, "scope": SCOPE_ERROR,
                "calculations": {}, "errors": (str(exc),),
            },
            "calculations": {},
        }
    return {
        "error": None, "standard": standard,
        "calculations": calculations,
        "expected": {
            "selected_standard": standard, "scope": SCOPE_SUCCESS,
            "calculations": calculations,
        },
    }


def _compare_bridge_value(actual, expected, label):
    # Bridge candidates are the byte-identical retained kernel outputs, so
    # numeric closure is EXACT: the shared tolerant comparator would open a
    # reseal window (about 1e299 absolute at 1e308 magnitudes).
    if isinstance(expected, float):
        if type(actual) is not float or (
                actual != expected
                and not (math.isnan(actual) and math.isnan(expected))):
            raise TraceValidationError(
                f"{label} differs from authoritative replay")
        return
    _compare_value(actual, expected, label)


def _check_row_shapes(payload, keys, row_keys):
    if tuple(payload) != keys:
        raise TraceValidationError(_DRIFT)
    for row in payload["rows"]:
        if tuple(row) != row_keys:
            raise TraceValidationError(_DRIFT)


def _calculation(calculation_id, title, axes, specs, values, assumptions,
                 *, failed_reason=None):
    units = {spec.step_id: spec.unit for spec in specs}
    steps = []
    for spec in specs:
        final = spec.quantity_role == "final_result"
        if failed_reason is not None and final:
            result = TraceResult(RESULT_FAILED, None, failed_reason)
            substituted = f"{spec.step_id} = failed"
        else:
            numeric = float(values[spec.step_id])
            if math.isnan(numeric):
                result = TraceResult(RESULT_UNDEFINED, None, _NAN_REASON)
                substituted = f"{spec.step_id} = undefined"
            elif math.isinf(numeric):
                result = TraceResult(RESULT_POSITIVE_INFINITY, None,
                                     _INFINITE_REASON)
                substituted = f"{spec.step_id} = positive_infinity"
            else:
                result = TraceResult(RESULT_FINITE, numeric)
                substituted = (
                    f"{spec.step_id} = {numeric:.17g} {spec.unit.symbol}")
        expression = {
            "as-required": "As,min = Mrep/(zs fyk) or kc k fct,eff Act/sigma_s",
            "utilisation": "utilisation = required/provided or interaction sum",
            "fct-eff-used": "fct,eff used = max(fct,eff, 2.9) when restrained",
            "status": "PASS = 1 when utilisation <= 1 + 1e-9, else FAIL = 0",
        }
        member_status = {
            "brittle-method-b-status", "box-walls-status",
            "minimum-crack-reinforcement-status",
        }
        if spec.step_id in member_status:
            actual = ("worst-first over row statuses: FAIL = 0 when any row "
                      "fails, else PASS = 1")
        else:
            actual = next((text for suffix, text in expression.items()
                           if spec.step_id.endswith(suffix)),
                          f"Bind {spec.title.lower()}")
        steps.append(TraceStep(
            spec.step_id, spec.title,
            tuple(TraceDependency(name, units[name])
                  for name in spec.dependencies),
            spec.quantity_role, spec.source, spec.step_id, spec.unit,
            actual, substituted, result,
        ))
    return TraceCalculation(
        calculation_id, COVERAGE_ID, title, METHOD_ID, axes,
        steps[-1].step_id, tuple(steps), (), assumptions,
    )


_ASSUMPTIONS = (
    "Independent numerical bridge calculations only; no generic bridge-code "
    "coverage is established.",
)


def _worst_first(rows):
    return "FAIL" if any(row["status"] == "FAIL" for row in rows) else "PASS"


def _member_values(member, final):
    return {"normalised-bridge-inputs": 1.0,
            f"{member}-status": STATUS_CODES[final],
            f"ct-011-{member}-result": STATUS_CODES[final]}


def _brittle_evidence(replay, context):
    payload = replay["calculations"]["brittle_method_b"]
    _check_row_shapes(payload, BRITTLE_KEYS, BRITTLE_ROW_KEYS)
    standard = replay["standard"]
    region_ids = tuple(row["region_id"] for row in payload["rows"])
    shape = BrittleShape(
        standard, standard == bridge.EN1992_2_DK_NA, region_ids,
        f"ct-011-{context_id(context)}-brittle-method-b",
        context_axes(context, bridge_standard=standard,
                     row_count=str(len(region_ids))),
    )
    values = {
        "input-selected-standard": float(bridge.METHODS.index(standard)),
        "dk-method-warning": float(bool(payload["warning"])),
    }
    for index, row in enumerate(payload["rows"]):
        prefix = region_prefix(index, row["region_id"])
        values.update({
            f"{prefix}-m-rep": row["m_rep_knm"], f"{prefix}-z-s": row["z_s_m"],
            f"{prefix}-f-yk": row["f_yk_mpa"],
            f"{prefix}-as-provided": row["as_provided_mm2"],
            f"{prefix}-as-required": row["as_required_mm2"],
            f"{prefix}-utilisation": row["utilisation"],
            f"{prefix}-status": STATUS_CODES[row["status"]],
        })
    values.update(_member_values(BRITTLE_MEMBER_ID,
                                 _worst_first(payload["rows"])))
    return shape, _calculation(
        shape.calculation_id, "Bridge brittle Method B", shape.axes,
        expected_brittle_steps(shape), values, _ASSUMPTIONS)


def _box_evidence(replay, context):
    payload = replay["calculations"]["box_walls"]
    _check_row_shapes(payload, BOX_KEYS, BOX_ROW_KEYS)
    if any(text not in {WALL_COMMON_COT_WARNING, WALL_COT_RANGE_WARNING}
           for text in payload["warnings"]):
        raise TraceValidationError(_DRIFT)
    wall_ids = tuple(row["wall_id"] for row in payload["rows"])
    shape = BoxShape(
        wall_ids, f"ct-011-{context_id(context)}-box-walls",
        context_axes(context, bridge_standard=replay["standard"],
                     row_count=str(len(wall_ids))),
    )
    values = {
        "common-cot-warning": float(
            WALL_COMMON_COT_WARNING in payload["warnings"]),
        "cot-range-warning": float(
            WALL_COT_RANGE_WARNING in payload["warnings"]),
    }
    for index, row in enumerate(payload["rows"]):
        prefix = wall_prefix(index, row["wall_id"])
        values.update({
            f"{prefix}-cot-theta": row["cot_theta"],
            f"{prefix}-v-ed": row["v_ed_kn"],
            f"{prefix}-v-rd-max": row["v_rd_max_kn"],
            f"{prefix}-t-ed-eq": row["t_ed_equivalent_kn"],
            f"{prefix}-t-rd-max-eq": row["t_rd_max_equivalent_kn"],
            f"{prefix}-utilisation": row["utilisation"],
            f"{prefix}-status": STATUS_CODES[row["status"]],
        })
    values.update(_member_values(BOX_MEMBER_ID,
                                 _worst_first(payload["rows"])))
    return shape, _calculation(
        shape.calculation_id, "Bridge box-wall interaction", shape.axes,
        expected_box_steps(shape), values, _ASSUMPTIONS)


def _crack_evidence(replay, context):
    payload = replay["calculations"]["minimum_crack_reinforcement"]
    _check_row_shapes(payload, CRACK_KEYS, CRACK_ROW_KEYS)
    components = tuple(row["component"] for row in payload["rows"])
    shape = CrackShape(
        components, f"ct-011-{context_id(context)}-minimum-crack-reinforcement",
        context_axes(context, bridge_standard=replay["standard"],
                     row_count=str(len(components))),
    )
    values = {}
    for index, row in enumerate(payload["rows"]):
        prefix = component_prefix(index, row["component"])
        values.update({
            f"{prefix}-act": row["act_mm2"], f"{prefix}-k-c": row["k_c"],
            f"{prefix}-k": row["k"], f"{prefix}-fct-eff": row["fct_eff_mpa"],
            f"{prefix}-sigma-s": row["sigma_s_mpa"],
            f"{prefix}-as-provided": row["as_provided_mm2"],
            f"{prefix}-restrained": float(row["restrained_shrinkage"]),
            f"{prefix}-fct-eff-used": row["fct_eff_used_mpa"],
            f"{prefix}-as-required": row["as_required_mm2"],
            f"{prefix}-utilisation": row["utilisation"],
            f"{prefix}-status": STATUS_CODES[row["status"]],
        })
    values.update(_member_values(CRACK_MEMBER_ID,
                                 _worst_first(payload["rows"])))
    return shape, _calculation(
        shape.calculation_id, "Bridge minimum crack reinforcement",
        shape.axes, expected_crack_steps(shape), values, _ASSUMPTIONS)


def _error_evidence(replay, context):
    shape = ErrorShape(
        replay["standard"], replay["error"],
        f"ct-011-{context_id(context)}-adapter-error",
        # The normalized standard can be empty on this branch; tokenize it
        # so the axis identity stays exact and non-blank.
        context_axes(context, bridge_branch="adapter-error",
                     bridge_standard=trace_identity_token(replay["standard"])),
    )
    standard_index = (bridge.METHODS.index(replay["standard"])
                      if replay["standard"] in bridge.METHODS else -1.0)
    values = {
        "input-selected-standard": float(standard_index),
        error_step_id(replay["error"]): 1.0,
        "ct-011-adapter-error-result": 0.0,
    }
    # The exact (possibly untrimmed) retained message identity is bound in
    # the tokenized error step id and the candidate closure; the sealed
    # reason carries a trimmed presentation of it.
    return shape, _calculation(
        shape.calculation_id, "Bridge adapter error state", shape.axes,
        expected_error_steps(shape), values, _ASSUMPTIONS,
        failed_reason=("Retained bridge adapter error: "
                       + replay["error"]).strip())


def _validate_rows(candidate_rows, expected_rows, row_keys, label):
    items = _sequence(candidate_rows, label)
    if len(items) != len(expected_rows):
        raise TraceValidationError(f"{label} cardinality differs")
    for index, (actual, wanted) in enumerate(zip(items, expected_rows)):
        actual = _retained_mapping(actual, row_keys, (), f"{label}[{index}]")
        for key in row_keys:
            _compare_bridge_value(actual[key], wanted[key], f"{label}[{index}].{key}")


def _validate_member(candidate, expected, keys, row_keys, label):
    candidate = _retained_mapping(candidate, keys, (), label)
    for key in keys:
        if key == "rows":
            _validate_rows(candidate[key], expected[key], row_keys,
                           f"{label}.rows")
        elif key == "warnings":
            _compare_text_list(candidate[key], expected[key],
                               f"{label}.warnings")
        else:
            _compare_bridge_value(candidate[key], expected[key],
                                  f"{label}.{key}")


def _validate_candidate(candidate, replay):
    expected = replay["expected"]
    candidate = _retained_mapping(
        candidate, ERROR_KEYS if replay["error"] is not None else SUCCESS_KEYS,
        (), "candidate bridge result")
    _compare_value(candidate["selected_standard"],
                   expected["selected_standard"],
                   "candidate bridge result.selected_standard")
    _compare_value(candidate["scope"], expected["scope"],
                   "candidate bridge result.scope")
    if replay["error"] is not None:
        _retained_mapping(candidate["calculations"], (), (),
                          "candidate bridge calculations")
        _compare_text_list(candidate["errors"], expected["errors"],
                           "candidate bridge result.errors")
        return
    order = tuple(key for key in CALCULATION_ORDER
                  if key in expected["calculations"])
    calculations = _retained_mapping(candidate["calculations"], order, (),
                                     "candidate bridge calculations")
    member_shapes = {
        "brittle_method_b": (BRITTLE_KEYS, BRITTLE_ROW_KEYS),
        "box_walls": (BOX_KEYS, BOX_ROW_KEYS),
        "minimum_crack_reinforcement": (CRACK_KEYS, CRACK_ROW_KEYS),
    }
    for key in order:
        keys, row_keys = member_shapes[key]
        _validate_member(calculations[key], expected["calculations"][key],
                         keys, row_keys, f"candidate {key}")


def _expected_bundle(inp, out, input_sha256, result_sha256, context):
    replay = _replay(inp)
    active = bool(replay["calculations"] or replay["error"])
    candidate = out.get("bridge")
    if not active:
        if candidate is not None:
            raise TraceValidationError(
                "inactive CT-011 bridge input cannot carry a candidate"
            )
        return None
    _validate_candidate(candidate, replay)
    shape_parts: dict[str, Any] = {}
    calculations = []
    if replay["error"] is not None:
        shape_parts["error"], calculation = _error_evidence(replay, context)
        calculations.append(calculation)
    else:
        builders = (("brittle_method_b", "brittle", _brittle_evidence),
                    ("box_walls", "box", _box_evidence),
                    ("minimum_crack_reinforcement", "crack", _crack_evidence))
        for key, field, builder in builders:
            if key in replay["calculations"]:
                shape_parts[field], calculation = builder(replay, context)
                calculations.append(calculation)
    bundle = create_bundle(
        input_sha256=input_sha256, result_sha256=result_sha256,
        calculations=tuple(calculations),
    )
    audit_trace_registry(bundle, expected_registry(BridgeShape(**shape_parts)))
    return bundle


def build_bridge_trace_family(
    inp: Mapping[str, Any], out: Mapping[str, Any], *,
    input_sha256: str, result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle | None:
    """Build and seal the applicable CT-011 bridge family."""

    try:
        out = _mapping(out, "retained result mapping")
        return _expected_bundle(inp, out, input_sha256, result_sha256,
                                {} if context is None else context)
    except TraceValidationError:
        raise
    except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"invalid CT-011 bridge evidence: {exc}") from exc


def validate_bridge_trace_family(
    bundle: TraceBundle | dict[str, Any] | None,
    inp: Mapping[str, Any], out: Mapping[str, Any], *,
    input_sha256: str, result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle | None:
    """Reject stale or coherently resealed CT-011 value/graph/source tampering."""

    try:
        out = _mapping(out, "retained result mapping")
        replay = _replay(inp)
        if not (replay["calculations"] or replay["error"]):
            if bundle is not None:
                raise TraceValidationError(
                    "inactive CT-011 bridge input cannot carry a trace"
                )
            if out.get("bridge") is not None:
                raise TraceValidationError(
                    "inactive CT-011 bridge input cannot carry a candidate"
                )
            return None
    except TraceValidationError:
        raise
    except (ArithmeticError, AttributeError, KeyError, TypeError,
            ValueError) as exc:
        raise TraceValidationError(
            f"invalid CT-011 bridge evidence: {exc}") from exc
    candidate = validate_bundle(
        bundle, expected_input_sha256=input_sha256,
        expected_result_sha256=result_sha256,
    )
    expected = build_bridge_trace_family(
        inp, out, input_sha256=input_sha256, result_sha256=result_sha256,
        context=context,
    )
    if candidate.to_dict() != expected.to_dict():
        raise TraceValidationError(
            "CT-011 trace differs from authoritative input replay"
        )
    return candidate

