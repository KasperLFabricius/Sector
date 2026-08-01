"""Independent original-input replay and candidate closure for CT-006."""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from . import capacity, codes, combined
from .calculation_trace import (
    RESULT_FAILED,
    RESULT_FINITE,
    TraceResult,
    TraceValidationError,
)
from .plastic import plastic_capacity_at_angle
from .section_trace_blocks import SectionTraceBlocks, section_trace_blocks
from .shear_trace_contract import (
    ANGLE_LIMIT_KEYS,
    BRANCH_FAILED,
    BRANCH_FINITE,
    CHORD_KEYS,
    COMPONENT_KEYS,
    CONCRETE_2005_KEYS,
    CONCRETE_2023_KEYS,
    DIRECTION_ORDER,
    DOMAIN_KEYS,
    FACE_KEYS,
    LINK_KEYS,
    LINK_RESULT_2005_KEYS,
    LINK_RESULT_2023_KEYS,
    PAYLOAD_KEYS,
    PHYSICAL_AXES,
    TOP_BIAXIAL_KEYS,
    TraceShape,
    direction_keys,
    expected_step_contract,
    input_key_inventory,
    material_step_id,
    trace_shape,
)


_TOL = 1.0e-9
_NOTE = (
    "Vx and Vy are calculated independently. Generic cross-direction "
    "interaction is not calculated."
)
_FAILURE_REASON = "Authoritative CT-006 mechanics did not produce complete finite evidence."


@dataclass(frozen=True, slots=True)
class DemandState:
    direction: str
    signed: float | None
    absolute: float | None
    invalid: bool


@dataclass(frozen=True, slots=True)
class FaceEvidence:
    face: str
    candidate: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DirectionEvidence:
    shape: TraceShape
    faces: tuple[FaceEvidence, ...]
    candidate: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class ReplayEvidence:
    directions: tuple[DirectionEvidence, ...]
    warnings: tuple[str, ...]


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise TraceValidationError(f"{label} must be a plain mapping")
    if any(type(key) is not str for key in value):
        raise TraceValidationError(f"{label} keys must be plain text")
    return value


def _inventory(value: Any, keys: tuple[str, ...], label: str) -> dict[str, Any]:
    value = _mapping(value, label)
    actual = tuple(value)
    if actual != keys:
        raise TraceValidationError(
            f"{label} key inventory/order is {actual!r}, expected {keys!r}"
        )
    return value


def _number(value: Any, label: str, *, positive=False, nonnegative=False) -> float:
    if type(value) not in {int, float} or type(value) is bool:
        raise TraceValidationError(f"{label} must be a finite non-Boolean number")
    result = float(value)
    if not math.isfinite(result):
        raise TraceValidationError(f"{label} must be finite")
    if positive and result <= 0.0:
        raise TraceValidationError(f"{label} must be positive")
    if nonnegative and result < 0.0:
        raise TraceValidationError(f"{label} must be non-negative")
    return result


def _try_number(value: Any) -> float | None:
    if type(value) not in {int, float} or type(value) is bool:
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _flag(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise TraceValidationError(f"{label} must be Boolean")
    return value


def _text_choice(value: Any, choices: set[str], label: str) -> str:
    if type(value) is not str or value not in choices:
        raise TraceValidationError(f"{label} must be one of {sorted(choices)}")
    return value


def _close(actual: float, expected: float) -> bool:
    return math.isclose(actual, expected, rel_tol=2.0e-9, abs_tol=2.0e-9)


def _compare(actual: Any, expected: Any, label: str) -> None:
    if type(expected) is dict:
        _inventory(actual, tuple(expected), label)
        for key in expected:
            _compare(actual[key], expected[key], f"{label}.{key}")
        return
    if type(expected) in {list, tuple}:
        if type(actual) is not type(expected) or len(actual) != len(expected):
            raise TraceValidationError(f"{label} sequence shape/order changed")
        for index, (left, right) in enumerate(zip(actual, expected)):
            _compare(left, right, f"{label}[{index}]")
        return
    if type(expected) is bool or expected is None or type(expected) is str:
        if type(actual) is not type(expected) or actual != expected:
            raise TraceValidationError(f"{label} differs from authoritative replay")
        return
    if type(expected) in {int, float} and type(expected) is not bool:
        if type(actual) not in {int, float} or type(actual) is bool:
            raise TraceValidationError(f"{label} must be numerical")
        left, right = float(actual), float(expected)
        if not math.isfinite(left) or not math.isfinite(right) or not _close(left, right):
            raise TraceValidationError(f"{label} differs from authoritative replay")
        return
    if type(actual) is not type(expected) or actual != expected:
        raise TraceValidationError(f"{label} differs from authoritative replay")


def validate_candidate_inventory(actual: Any, expected: Any, label="CT-006 candidate") -> None:
    """Exhaustive ordered candidate comparison used by the publication gate."""

    _compare(actual, expected, label)


def _method_branch(inp: Mapping[str, Any]) -> str:
    label = inp.get("shear_method")
    if label == codes.EC2_2005.label:
        return "base-2005"
    if label == codes.EC2_2005_DKNA.label:
        return "dk-2005"
    if label == codes.EC2_2023.label:
        return "published-2023"
    raise TraceValidationError("CT-006 needs an exact retained shear method")


def _geometry_matches(inp: Mapping[str, Any], blocks: SectionTraceBlocks) -> None:
    raw_rings = (inp.get("outer"), *(inp.get("holes") or ()))
    if len(raw_rings) != len(blocks.geometry.rings):
        raise TraceValidationError("raw and immutable concrete rings diverge")
    for ring_index, (raw, held) in enumerate(zip(raw_rings, blocks.geometry.rings)):
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) != len(held):
            raise TraceValidationError(f"raw concrete ring {ring_index + 1} diverges")
        for point_index, (point, expected) in enumerate(zip(raw, held)):
            if not isinstance(point, Sequence) or len(point) != 2:
                raise TraceValidationError("raw concrete point is malformed")
            for actual, target in zip(point, expected):
                if not _close(_number(actual, "raw concrete coordinate"), target):
                    raise TraceValidationError(
                        f"raw concrete ring {ring_index + 1} point {point_index + 1} diverges"
                    )
    for key, held in (("bars", blocks.geometry.bars), ("tendons", blocks.geometry.tendons)):
        raw = inp.get(key) or ()
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) != len(held):
            raise TraceValidationError(f"raw {key} and immutable section diverge")
        for item, expected in zip(raw, held):
            if not isinstance(item, Sequence) or len(item) != 3:
                raise TraceValidationError(f"raw {key} item is malformed")
            x, y, area_mm2 = (_number(value, f"raw {key} value") for value in item)
            if not (_close(x, expected.x) and _close(y, expected.y)
                    and _close(area_mm2 * 1.0e-6, expected.area)):
                raise TraceValidationError(f"raw {key} and immutable section diverge")


def _demand_states(inp: Mapping[str, Any]) -> tuple[DemandState, ...]:
    components = inp.get("shear_components")
    if components is not None:
        components = _inventory(components, DIRECTION_ORDER, "shear_components")
    states = []
    for direction in DIRECTION_ORDER:
        scalar_key = "shear_Vx" if direction == "vx" else "shear_Vy"
        scalar = _try_number(inp.get(scalar_key))
        face_key = "shear_face_x" if direction == "vx" else "shear_face_y"
        face = _text_choice(inp.get(face_key), {"auto", "negative", "positive"}, face_key)
        invalid = scalar is None
        signed = scalar
        absolute = abs(scalar) if scalar is not None else None
        if components is not None:
            item = components.get(direction)
            if type(item) is not dict or tuple(item) != COMPONENT_KEYS:
                invalid = True
            else:
                component_signed = _try_number(item.get("signed_v_ed"))
                component_absolute = _try_number(item.get("v_ed"))
                component_active = item.get("active")
                invalid = invalid or component_signed is None or component_absolute is None
                invalid = invalid or item.get("axis") != PHYSICAL_AXES[direction]
                invalid = invalid or item.get("face") != face or type(component_active) is not bool
                if component_signed is not None and component_absolute is not None:
                    invalid = invalid or not _close(component_absolute, abs(component_signed))
                    invalid = invalid or scalar is None or not _close(abs(scalar), component_absolute)
                    expected_active = bool(inp.get("shear_on") and component_absolute > 0.0)
                    invalid = invalid or component_active is not expected_active
                    signed, absolute = component_signed, component_absolute
        states.append(DemandState(direction, signed, absolute, bool(invalid)))
    return tuple(states)


def _validated_input(inp: dict[str, Any]):
    method_branch = _method_branch(inp)
    shear_on = _flag(inp.get("shear_on"), "shear_on")
    links = _flag(inp.get("shear_links"), "shear_links")
    missing = tuple(key for key in input_key_inventory(inp, method_branch, links) if key not in inp)
    if missing:
        raise TraceValidationError(f"CT-006 input inventory omitted {', '.join(missing)}")
    states = _demand_states(inp)  # before any active-direction filtering
    for key in ("P_pl", "Mx_pl", "My_pl"):
        _number(inp.get(key), key)
    for direction in DIRECTION_ORDER:
        _number(inp.get("shear_vx_bw" if direction == "vx" else "shear_vy_bw"),
                f"{direction} web-width override", nonnegative=True)
    concrete, steel = inp.get("concrete"), inp.get("steel")
    _number(getattr(concrete, "fck", None), "concrete fck", positive=True)
    _number(getattr(concrete, "fcd", None), "concrete fcd", positive=True)
    _number(getattr(concrete, "gamma_c", None), "concrete gamma_c", positive=True)
    _number(getattr(steel, "fytk", None), "steel fytk", positive=True)
    _number(getattr(steel, "gamma_y", None), "steel gamma_y", positive=True)
    if method_branch == "published-2023":
        _number(inp.get("shear_dlower"), "aggregate lower size", positive=True)
    if links:
        for direction in DIRECTION_ORDER:
            _number(inp.get("shear_vx_link_legs" if direction == "vx" else "shear_vy_link_legs"),
                    f"{direction} link legs", positive=True)
        cot_min = _number(inp.get("strut_cot_min"), "minimum cotangent", positive=True)
        cot_max = _number(inp.get("strut_cot_max"), "maximum cotangent", positive=True)
        if cot_min > cot_max:
            raise TraceValidationError("minimum cotangent exceeds maximum cotangent")
        _number(inp.get("shear_link_dia"), "link diameter", positive=True)
        _number(inp.get("shear_link_s"), "link spacing", positive=True)
        _number(inp.get("shear_fywk"), "link yield", positive=True)
        _text_choice(inp.get("transverse_ductility_class"), {"A", "B", "C"},
                     "transverse ductility class")
    blocks = section_trace_blocks(inp)
    _geometry_matches(inp, blocks)
    return blocks, method_branch, shear_on, links, states


def _sanitised_specs(inp: dict[str, Any], states: tuple[DemandState, ...]):
    clone = dict(inp)
    if inp.get("shear_components") is not None:
        clone["shear_components"] = {
            state.direction: {"signed_v_ed": state.signed if not state.invalid else 0.0}
            for state in states
        }
    else:
        clone["shear_Vx"] = states[0].signed if not states[0].invalid else 0.0
        clone["shear_Vy"] = states[1].signed if not states[1].invalid else 0.0
    specs = capacity.shear_direction_specs(clone)
    for state in states:
        if not state.invalid:
            specs[state.direction]["signed_v_ed"] = state.signed
            specs[state.direction]["v_ed"] = state.absolute
    return specs


def _canonical_extrema(inp: Mapping[str, Any]) -> dict[str, float]:
    section = inp["section"]
    prestress = inp.get("prestress") if section.tendons else None
    points = tuple(
        plastic_capacity_at_angle(
            section, inp["concrete"], inp["steel"], -float(inp["P_pl"]), angle,
            prestress=prestress,
            bar_materials=inp.get("bar_materials"),
            tendon_materials=inp.get("tendon_materials"),
        )
        for angle in range(0, 360, 15)
    )
    if not points or any(
        not point.converged or not math.isfinite(point.Mx) or not math.isfinite(point.My)
        for point in points
    ):
        raise ArithmeticError("canonical chord capacity sweep failed")
    return {
        "max_mx": max(point.Mx for point in points),
        "min_mx": min(point.Mx for point in points),
        "max_my": max(point.My for point in points),
        "min_my": min(point.My for point in points),
    }


def _status(payload: Mapping[str, Any], links: bool) -> tuple[str, float]:
    if not payload["res"]["valid"]:
        return "INVALID", math.inf
    if links:
        linked = payload.get("links")
        if linked is None or not linked["res"]["valid"]:
            return "NOT ASSESSED", 0.0
        util = float(linked["util"])
    else:
        util = float(payload["util"])
    if not math.isfinite(util):
        return "INVALID", math.inf
    return ("PASS" if util <= 1.0 + _TOL else "FAIL"), util


def _linked_payload(inp, spec, payload, ctx, extrema):
    probe = ctx["build"](ctx["cot_min"], ctx["cot_min"])
    if not (probe["valid"] and probe["vrd_s"] > 0.0 and probe["vrd_max"] > 0.0):
        raise ArithmeticError("invalid linked shear mechanics")
    axis, tension_low = ctx["axis"], ctx["tension_low"]
    m_signed = float(inp["Mx_pl"] if axis == "x" else inp["My_pl"])
    off_signed = float(inp["My_pl"] if axis == "x" else inp["Mx_pl"])
    off_max = extrema["max_my" if axis == "x" else "max_mx"]
    off_min = extrema["min_my" if axis == "x" else "min_mx"]
    off_cap = off_max if off_signed >= 0.0 else abs(off_min)
    off_util = abs(off_signed) / off_cap if off_cap > 0.0 else (
        math.inf if off_signed else 0.0
    )
    m_ed = combined.chord_applied_moment(m_signed, tension_low)
    m_rd, conditional = capacity.shear_face_mrd(
        inp, axis, tension_low, m_off=off_signed
    )
    if not conditional and m_rd <= 0.0:
        maximum = extrema["max_mx" if axis == "x" else "max_my"]
        minimum = extrema["min_mx" if axis == "x" else "min_my"]
        m_rd = maximum if tension_low else abs(minimum)
    if not m_rd > 0.0:
        raise ArithmeticError("longitudinal chord resistance unavailable")
    z_m = ctx["z_mm"] / 1000.0
    model_2023 = bool(ctx.get("model_2023"))
    factor = 1.0 if model_2023 else 0.5

    def chord_util(cot):
        return combined.longitudinal_check(
            m_ed, m_rd, factor * spec["v_ed"] * cot, 0.0, z_m,
            cap_shear_force=not model_2023,
        )["util"]

    utils = [
        lambda cot: combined.ratio(spec["v_ed"], ctx["build"](cot, cot)["vrd_s"]),
        lambda cot: combined.ratio(spec["v_ed"], ctx["build"](cot, cot)["vrd_max"]),
        chord_util,
    ]
    cot, _governing = combined.governing_strut_cot(
        utils, ctx["cot_min"], ctx["cot_max"], n=1501
    )
    result = ctx["build"](cot, cot)
    if not result["valid"]:
        raise ArithmeticError("linked shear replay failed at governing cotangent")
    util = spec["v_ed"] / result["vrd"] if result["vrd"] > 0.0 else math.inf
    force = factor * spec["v_ed"] * result["cot"]
    chord = combined.longitudinal_check(
        m_ed, m_rd, force, 0.0, z_m,
        cap_shear_force=not model_2023,
    )
    chord.update(
        valid=True, role="shear_axis", axis=axis, tension_low=tension_low,
        off_util=off_util, biaxial=bool(off_util > 0.05), m_off=off_signed,
        conditional=bool(conditional), has_torsion=False, gets_shift=True,
        off_not_evaluated=None, theta_mode="utilisation",
    )
    limits = copy.deepcopy(ctx["angle_limits"])
    out_of_limits = bool(
        ctx["cot_min"] < limits["minimum"] - _TOL
        or ctx["cot_max"] > limits["maximum"] + _TOL
    )
    return {
        "res": result,
        "util": util,
        "asw": ctx["asw"],
        "asw_over_s": ctx["asw_over_s"],
        "legs": spec["legs"],
        "dia": inp["shear_link_dia"],
        "s": inp["shear_link_s"],
        "fywk": inp["shear_fywk"],
        "cot_min": ctx["cot_min"],
        "cot_max": ctx["cot_max"],
        "delta_ftd": None if model_2023 else force,
        "longitudinal_shear_force": force,
        "longitudinal_shear_symbol": "NVd" if model_2023 else "delta_Ftd",
        "longitudinal_shear_clause": (
            "8.2.3(8), Formula (8.50)" if model_2023
            else "6.2.3(7), Formula (6.18)"
        ),
        "cot_limit_lo": limits["minimum"],
        "cot_limit_hi": limits["maximum"],
        "angle_limits": limits,
        "model_2023": model_2023,
        "z_source": ctx["z_src"],
        "out_of_limits": out_of_limits,
        "required": bool(spec["v_ed"] > ctx["vrd_c"]),
        "chord": chord,
        "chord_off": None,
        "chord_candidates": [copy.deepcopy(chord)],
        "theta_mode": "utilisation",
    }


def _candidate_inventory(direction: dict[str, Any], method_branch: str, links: bool) -> None:
    _inventory(direction, direction_keys(links), "directional shear result")
    _inventory(direction["res"], CONCRETE_2023_KEYS if method_branch == "published-2023" else CONCRETE_2005_KEYS,
               "directional concrete result")
    _inventory(direction["governing_domains"], ("shear",), "governing domains")
    _inventory(direction["governing_domains"]["shear"], DOMAIN_KEYS, "governing shear domain")
    for index, face in enumerate(direction["face_candidates"]):
        _inventory(face, FACE_KEYS, f"face candidate {index + 1}")
        shear = _inventory(face["shear"], PAYLOAD_KEYS + (("links",) if links else ()),
                           f"face {index + 1} shear")
        _inventory(shear["res"], CONCRETE_2023_KEYS if method_branch == "published-2023" else CONCRETE_2005_KEYS,
                   f"face {index + 1} concrete")
        if links:
            linked = _inventory(shear["links"], LINK_KEYS, f"face {index + 1} links")
            _inventory(linked["res"], LINK_RESULT_2023_KEYS if method_branch == "published-2023" else LINK_RESULT_2005_KEYS,
                       f"face {index + 1} link result")
            _inventory(linked["angle_limits"], ANGLE_LIMIT_KEYS, f"face {index + 1} angle limits")
            _inventory(linked["chord"], CHORD_KEYS, f"face {index + 1} chord")
            if linked["chord_off"] is not None or len(linked["chord_candidates"]) != 1:
                raise TraceValidationError("CT-007 chord siblings are not neutral/excluded")
            _inventory(linked["chord_candidates"][0], CHORD_KEYS, f"face {index + 1} candidate chord")
        if not (
            face["torsion_status"] == "NOT RUN" and face["torsion_metric"] == 0.0
            and face["min_reinf_status"] == "NOT RUN" and face["min_reinf_metric"] == 0.0
            and face["combined_status"] == "NOT RUN" and face["combined_metric"] == 0.0
            and face["torsion"] is None and face["combined"] is None
        ):
            raise TraceValidationError("excluded face-family siblings are not neutral")


def _reconstruct_direction(inp, blocks, context, spec, direction, method_branch, links, extrema):
    n_prestress = capacity.prestress_axial(inp)
    n_ed_comp = -float(inp["P_pl"]) + n_prestress
    faces_bool = capacity.shear_face_candidates(spec["face"], spec["moment"])
    faces = []
    for tension_low in faces_bool:
        payload, ctx = capacity._build_shear_face_context(
            inp, n_prestress, n_ed_comp,
            component=direction, axis=spec["axis"], tension_low=tension_low,
            v_ed=spec["v_ed"], bw_override=spec["bw"], link_legs=spec["legs"],
            face_mode="selected",
        )
        if not payload["res"]["valid"]:
            raise ArithmeticError("concrete-only shear replay is invalid")
        if links:
            if ctx is None:
                raise ArithmeticError("linked shear context is missing")
            payload["links"] = _linked_payload(inp, spec, payload, ctx, extrema)
        status, metric = _status(payload, links)
        candidate = {
            "tension_low": bool(tension_low),
            "shear_status": status,
            "shear_metric": metric,
            "torsion_status": "NOT RUN",
            "torsion_metric": 0.0,
            "min_reinf_status": "NOT RUN",
            "min_reinf_metric": 0.0,
            "combined_status": "NOT RUN",
            "combined_metric": 0.0,
            "shear": payload,
            "torsion": None,
            "combined": None,
        }
        faces.append(FaceEvidence("negative" if tension_low else "positive", candidate))
    governing = max(
        faces,
        key=lambda item: capacity.assessment_key(
            item.candidate["shear_status"], item.candidate["shear_metric"]
        ),
    )
    direction_out = dict(governing.candidate["shear"])
    aggregate = capacity.aggregate_assessment_status(
        item.candidate["shear_status"] for item in faces
    )
    cot = (
        governing.candidate["shear"]["links"]["res"]["cot"] if links else None
    )
    direction_out.update(
        face_mode=str(spec["face"]),
        both_faces_evaluated=len(faces) == 2,
        governing_face=governing.face,
        associated_moment=spec["moment"],
        associated_moment_origin=spec["moment_origin"],
        signed_v_ed=spec["signed_v_ed"],
        status=aggregate,
        governing_domains={
            "shear": {
                "face": governing.face,
                "cot": cot,
                "status": aggregate,
                "util": governing.candidate["shear_metric"],
            }
        },
        face_candidates=[item.candidate for item in faces],
    )
    _candidate_inventory(direction_out, method_branch, links)
    if not _all_engineering_finite(direction_out):
        raise ArithmeticError("CT-006 finite replay contains a non-finite intermediate")
    shape = trace_shape(
        blocks, context, direction=direction, face_selector=spec["face"],
        face_order=tuple(item.face for item in faces),
        face_bar_ids=tuple(tuple(item.candidate["shear"]["asl_bar_ids"]) for item in faces),
        method_branch=method_branch, method_label=inp["shear_method"], links=links,
        branch=BRANCH_FINITE,
    )
    return DirectionEvidence(shape, tuple(faces), direction_out)


def _all_engineering_finite(value: Any) -> bool:
    if type(value) is dict:
        return all(_all_engineering_finite(item) for item in value.values())
    if type(value) in {list, tuple}:
        return all(_all_engineering_finite(item) for item in value)
    if type(value) in {int, float} and type(value) is not bool:
        return math.isfinite(float(value))
    return True


def replay_shear_evidence(inp, out, context=None) -> ReplayEvidence:
    """Choose state from original inputs, then validate the retained candidate."""

    inp = _mapping(inp, "CT-006 input")
    out = _mapping(out, "analysis result")
    context = {} if context is None else _mapping(context, "CT-006 context")
    blocks, method_branch, shear_on, links, states = _validated_input(inp)
    specs = _sanitised_specs(inp, states)
    finite_active = [
        state.direction for state in states
        if shear_on and not state.invalid and state.absolute > 0.0
    ]
    required = [
        state.direction for state in states
        if state.invalid or (shear_on and state.absolute > 0.0)
    ]
    if not required:
        raise TraceValidationError("CT-006 has no active or failed direction")

    reconstructed: dict[str, DirectionEvidence] = {}
    mechanics_failed: set[str] = set()
    extrema = None
    if links and finite_active:
        try:
            extrema = _canonical_extrema(inp)
        except (ArithmeticError, KeyError, TypeError, ValueError):
            mechanics_failed.update(finite_active)
    for state in states:
        if state.direction not in required:
            continue
        spec = specs[state.direction]
        faces = tuple(
            "negative" if value else "positive"
            for value in capacity.shear_face_candidates(spec["face"], spec["moment"])
        )
        if state.invalid:
            mechanics_failed.add(state.direction)
        elif state.direction not in mechanics_failed:
            try:
                reconstructed[state.direction] = _reconstruct_direction(
                    inp, blocks, context, spec, state.direction, method_branch,
                    links, extrema,
                )
            except (ArithmeticError, KeyError, TypeError, ValueError):
                mechanics_failed.add(state.direction)
        if state.direction in mechanics_failed:
            shape = trace_shape(
                blocks, context, direction=state.direction,
                face_selector=spec["face"], face_order=faces,
                face_bar_ids=tuple(() for _ in faces), method_branch=method_branch,
                method_label=inp["shear_method"], links=links, branch=BRANCH_FAILED,
            )
            reconstructed[state.direction] = DirectionEvidence(shape, (), None)

    finite_replayed = [
        direction for direction in finite_active if direction not in mechanics_failed
    ]
    if finite_replayed:
        candidate = out.get("shear")
        if len(finite_active) == 2:
            top = _inventory(candidate, TOP_BIAXIAL_KEYS, "biaxial CT-006 candidate")
            directions = _mapping(top["directions"], "candidate directions")
            if tuple(directions) != tuple(finite_active):
                raise TraceValidationError("candidate directions insertion order/cardinality changed")
            if type(top["active_directions"]) is not list or top["active_directions"] != finite_active:
                raise TraceValidationError("candidate active_directions is missing, reordered or stale")
            if top["biaxial"] is not True or top["note"] != _NOTE:
                raise TraceValidationError("candidate biaxial identity changed")
            for direction in finite_replayed:
                validate_candidate_inventory(
                    directions[direction], reconstructed[direction].candidate,
                    f"candidate {direction}",
                )
        elif len(finite_active) == 1:
            direction = finite_active[0]
            if direction in finite_replayed:
                validate_candidate_inventory(
                    candidate, reconstructed[direction].candidate,
                    f"candidate {direction}",
                )

    ordered = tuple(reconstructed[key] for key in DIRECTION_ORDER if key in reconstructed)
    warnings = (
        ("DS/EN 1992-1-1:2023 is published but not implemented for Sector publication.",)
        if method_branch == "published-2023" else ()
    )
    return ReplayEvidence(ordered, warnings)


def _shared_values(values, blocks):
    for ring_index, ring in enumerate(blocks.geometry.rings):
        for point_index, point in enumerate(ring):
            values[f"geometry-ring-{ring_index:03d}-point-{point_index:04d}-x"] = point[0]
            values[f"geometry-ring-{ring_index:03d}-point-{point_index:04d}-y"] = point[1]
    for kind, elements in (("bar", blocks.geometry.bars), ("tendon", blocks.geometry.tendons)):
        for index, element in enumerate(elements):
            values[f"geometry-{kind}-{index:04d}-x"] = element.x
            values[f"geometry-{kind}-{index:04d}-y"] = element.y
            values[f"geometry-{kind}-{index:04d}-area"] = element.area
    for key, value in blocks.plastic_actions.values:
        values[f"input-action-u{key.encode('utf-8').hex()}"] = value
    for material in (blocks.concrete, *blocks.bars, *blocks.tendons):
        for name, value in material.values:
            values[material_step_id(material, name)] = value
    values["shared-section-evidence"] = 1.0


def trace_values(evidence: DirectionEvidence, inp: Mapping[str, Any]) -> dict[str, float]:
    shape = evidence.shape
    if shape.branch == BRANCH_FAILED:
        return {"input-direction-ordinal": float(DIRECTION_ORDER.index(shape.direction) + 1)}
    values: dict[str, float] = {}
    _shared_values(values, shape.blocks)
    direction = evidence.candidate
    if direction is None:
        raise TraceValidationError("finite CT-006 direction evidence is missing")
    values.update({
        "input-shear-on": 1.0,
        "input-signed-demand": float(direction["signed_v_ed"]),
        "absolute-demand": float(direction["v_ed"]),
        "input-face-selector": float({"auto": 0, "negative": 1, "positive": 2}[direction["face_mode"]]),
        "input-width-override": float(direction["bw"]),
    })
    if shape.method_branch == "published-2023":
        values["input-aggregate-lower-size"] = float(inp["shear_dlower"])
    if shape.links:
        values.update({
            "input-link-legs": float(direction["links"]["legs"]),
            "input-cot-min": float(inp["strut_cot_min"]),
            "input-cot-max": float(inp["strut_cot_max"]),
            "input-link-diameter": float(inp["shear_link_dia"]),
            "input-link-spacing": float(inp["shear_link_s"]),
            "input-link-yield": float(inp["shear_fywk"]),
        })
        values["input-ductility-class"] = float(
            {"A": 1, "B": 2, "C": 3}[inp["transverse_ductility_class"]]
        )
    values["direction-input-evidence"] = 1.0

    for face in evidence.faces:
        p = f"face-{face.face}"
        s, r = face.candidate["shear"], face.candidate["shear"]["res"]
        values.update({
            f"{p}-tension-low": 1.0 if s["tension_low"] else 0.0,
            f"{p}-bw-auto": s["bw_auto"], f"{p}-bw": s["bw"],
            f"{p}-d": s["d"], f"{p}-asl": s["asl"], f"{p}-asl-cg": s["asl_cg"],
            f"{p}-ac": s["ac"], f"{p}-centroid-x": s["centroid"][0],
            f"{p}-centroid-y": s["centroid"][1], f"{p}-fck": s["fck"],
            f"{p}-fcd": r.get("fcd", getattr(inp["concrete"], "fcd")),
            f"{p}-gamma-c": r.get("gamma_c", getattr(inp["concrete"], "gamma_c")),
            f"{p}-fyd-flex": s["fyd_flex"], f"{p}-n-ed": s["n_ed"],
            f"{p}-n-prestress": s["n_prestress"], f"{p}-n-ed-comp": s["n_ed_comp"],
            f"{p}-associated-moment": direction["associated_moment"], f"{p}-moment-origin": direction["associated_moment_origin"],
            f"{p}-m-prestress": s["m_prestress"], f"{p}-m-ed-2023": s["m_ed_2023"],
            f"{p}-ddg": s["ddg"], f"{p}-bw-user": 1.0 if s["bw_user"] else 0.0,
            f"{p}-model-2023": 1.0 if s["model_2023"] else 0.0,
            f"{p}-rho-l": r["rho_l"], f"{p}-vrd-c": r["vrd_c"],
            f"{p}-concrete-util": s["util"],
            f"{p}-concrete-verdict": 1.0 if s["util"] <= 1.0 + _TOL else 0.0,
        })
        for index, bar_id in enumerate(s["asl_bar_ids"]):
            values[f"{p}-asl-bar-{index:03d}"] = float(bar_id)
        if shape.method_branch == "published-2023":
            values.update({
                f"{p}-concrete-z": r["z"], f"{p}-k-vp": r["k_vp"],
                f"{p}-d-kvp": r["d_kvp"], f"{p}-a-cs": r["a_cs"],
                f"{p}-tau-basic": r["tau_basic"], f"{p}-tau-min": r["tau_min"],
                f"{p}-tau-rdc": r["tau_rdc"], f"{p}-gamma-v": r["gamma_v"],
                f"{p}-axial-applied": 1.0 if r["axial_applied"] else 0.0,
            })
        else:
            values.update({
                f"{p}-k": r["k"], f"{p}-sigma-cp": r["sigma_cp"],
                f"{p}-crd-c": r["crd_c"], f"{p}-k1": r["k1"],
                f"{p}-vmin": r["vmin"], f"{p}-v-basic": r["v_basic"],
                f"{p}-v-floor": r["v_floor"],
            })
        if shape.links:
            l, lr, chord = s["links"], s["links"]["res"], s["links"]["chord"]
            values.update({
                f"{p}-asw": l["asw"], f"{p}-asw-over-s": l["asw_over_s"],
                f"{p}-links-z": lr["z"], f"{p}-fywd": lr["fywd"],
                f"{p}-links-sigma-cp": lr["sigma_cp"], f"{p}-alpha-cw": lr["alpha_cw"],
                f"{p}-nu1": lr["nu1"], f"{p}-cot": lr["cot"],
                f"{p}-theta": lr["theta_deg"], f"{p}-vrd-s": lr["vrd_s"],
                f"{p}-vrd-max": lr["vrd_max"], f"{p}-vrd": lr["vrd"],
                f"{p}-links-util": l["util"], f"{p}-links-verdict": 1.0 if l["util"] <= 1.0 + _TOL else 0.0,
                f"{p}-longitudinal-shear-force": l["longitudinal_shear_force"],
                f"{p}-links-required": 1.0 if l["required"] else 0.0,
                f"{p}-out-of-limits": 1.0 if l["out_of_limits"] else 0.0,
                f"{p}-theta-mode": 1.0, f"{p}-link-legs": l["legs"],
                f"{p}-link-diameter": l["dia"], f"{p}-link-spacing": l["s"],
                f"{p}-link-yield": l["fywk"], f"{p}-cot-min": l["cot_min"],
                f"{p}-cot-max": l["cot_max"], f"{p}-cot-limit-lo": l["cot_limit_lo"],
                f"{p}-cot-limit-hi": l["cot_limit_hi"],
                f"{p}-angle-min": l["angle_limits"]["minimum"],
                f"{p}-angle-max": l["angle_limits"]["maximum"],
                f"{p}-angle-ductility-factor": l["angle_limits"]["ductility_factor"],
                f"{p}-angle-axial-tension": 1.0 if l["angle_limits"]["axial_tension_applied"] else 0.0,
                f"{p}-angle-compression-extension": 1.0 if l["angle_limits"]["compression_extension_credited"] else 0.0,
                f"{p}-chord-m-ed": chord["m_ed"], f"{p}-chord-m-rd": chord["m_rd"],
                f"{p}-chord-off-util": chord["off_util"], f"{p}-chord-biaxial": 1.0 if chord["biaxial"] else 0.0,
                f"{p}-chord-mv": chord["mv"], f"{p}-chord-m-total": chord["m_total"],
                f"{p}-chord-util": chord["util"], f"{p}-chord-verdict": 1.0 if chord["ok"] else 0.0,
                f"{p}-chord-ftd-v": chord["ftd_v"], f"{p}-chord-ftd-t": chord["ftd_t"],
                f"{p}-chord-z": chord["z"], f"{p}-chord-mt": chord["mt"],
                f"{p}-chord-capped": 1.0 if chord["capped"] else 0.0,
                f"{p}-chord-cap-enabled": 1.0 if chord["cap_shear_force"] else 0.0,
                f"{p}-chord-valid": 1.0 if chord["valid"] else 0.0,
                f"{p}-chord-tension-low": 1.0 if chord["tension_low"] else 0.0,
                f"{p}-chord-m-off": chord["m_off"], f"{p}-chord-conditional": 1.0 if chord["conditional"] else 0.0,
                f"{p}-chord-has-torsion": 1.0 if chord["has_torsion"] else 0.0,
                f"{p}-chord-gets-shift": 1.0 if chord["gets_shift"] else 0.0,
                f"{p}-chord-candidate-evidence": 1.0,
            })
            if shape.method_branch == "published-2023":
                values.update({
                    f"{p}-rho-w": lr["rho_w"], f"{p}-tau-ed": lr["tau_ed"],
                    f"{p}-tau-rd-sy": lr["tau_rd_sy"], f"{p}-tau-rd-max": lr["tau_rd_max"],
                    f"{p}-sigma-cd": lr["sigma_cd"], f"{p}-nu-fcd": lr["nu_fcd"],
                })
        status, metric = _status(s, shape.links)
        values[f"{p}-shear-metric"] = metric
        values[f"{p}-shear-status"] = 1.0 if status == "PASS" else 0.0
        values[f"{p}-complete-evidence"] = 1.0
    governing_face = direction["governing_face"]
    metric = direction["governing_domains"]["shear"]["util"]
    values.update({
        "direction-shear-metric": float(metric),
        "direction-governing-face": 1.0 if governing_face == "negative" else 2.0,
        "direction-aggregate-verdict": 1.0 if direction["status"] == "PASS" else 0.0,
        "direction-complete-evidence": 1.0,
        "ct-006-direction-result": float(metric),
    })
    missing = [spec.step_id for spec in expected_step_contract(shape) if spec.step_id not in values]
    if missing:
        raise TraceValidationError(f"internal CT-006 evidence omitted {', '.join(missing)}")
    return values


def trace_result(shape: TraceShape, step_id: str, value: float | None) -> TraceResult:
    if shape.branch == BRANCH_FAILED and step_id == "ct-006-direction-result":
        return TraceResult(RESULT_FAILED, None, _FAILURE_REASON)
    if value is None or not math.isfinite(float(value)):
        raise TraceValidationError(f"finite CT-006 step {step_id} is non-finite")
    return TraceResult(RESULT_FINITE, value)
