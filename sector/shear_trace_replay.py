"""Original-input replay and candidate closure for unpublished CT-006."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from . import capacity, combined
from .calculation_trace import (
    RESULT_FAILED,
    TraceResult,
    TraceValidationError,
    trace_identity_token,
)
from .section_trace_blocks import context_axes, context_id, section_trace_blocks
from .shear_trace_contract import (
    ANGLE_LIMIT_FIELDS,
    BRANCH_FAILED,
    BRANCH_FINITE,
    CHORD_CONTEXT_FIELDS,
    CHORD_RESULT_FIELDS,
    COMMON_FACE_FIELDS,
    CONCRETE_2005_FIELDS,
    CONCRETE_2023_FIELDS,
    LINK_2005_FIELDS,
    LINK_2005_EXTRA_FIELDS,
    LINK_2023_FIELDS,
    LINK_WRAPPER_FIELDS,
    DirectionShape,
    FaceShape,
    TraceShape,
)


@dataclass(frozen=True, slots=True)
class ReplayEvidence:
    shape: TraceShape
    values: dict[str, float]
    states: dict[str, TraceResult]
    warnings: tuple[str, ...]


@dataclass(slots=True)
class _Face:
    tension_low: bool
    payload: dict[str, Any]
    link_context: dict[str, Any] | None
    link_result: dict[str, Any] | None = None
    link_wrapper: dict[str, Any] | None = None
    chord_context: dict[str, Any] | None = None
    chord_result: dict[str, Any] | None = None
    metric: float = 0.0
    status: str = "INVALID"


@dataclass(slots=True)
class _Direction:
    component: str
    axis: str
    spec: dict[str, Any]
    faces: list[_Face]
    governing: int = 0
    status: str = "INVALID"


def _number(value: Any, label: str) -> float:
    if type(value) not in {int, float} or not math.isfinite(float(value)):
        raise ValueError(f"{label} must be a finite non-Boolean number")
    return float(value)


def _positive(value: Any, label: str) -> float:
    result = _number(value, label)
    if result <= 0.0:
        raise ValueError(f"{label} must be positive")
    return result


def _boolean(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{label} must be Boolean")
    return value


def _face_code(value: str) -> float:
    try:
        return float({"auto": 0, "negative": 1, "positive": 2}[value])
    except KeyError as exc:
        raise ValueError("shear face must be auto, negative or positive") from exc


def _mode_code(value: Any) -> float:
    try:
        return float({"Elastic": 0, "Plastic": 1, "Both": 2}[value])
    except KeyError as exc:
        raise ValueError("analysis mode must be Elastic, Plastic or Both") from exc


def _status_code(status: str) -> float:
    return 1.0 if status == "PASS" else 0.0


def _finite_mapping(
    mapping: Mapping[str, Any], keys, label: str, *, boolean_keys=(), text_keys=()
) -> None:
    for key, _unit in keys:
        normalised = key.replace("-", "_")
        value = mapping[normalised]
        if key in boolean_keys:
            _boolean(value, f"{label}.{key}")
        elif key in text_keys:
            if type(value) is not str or not value:
                raise ValueError(f"{label}.{key} must be non-empty text")
        else:
            _number(value, f"{label}.{key}")


def _original_inputs(inp: Mapping[str, Any]):
    if not isinstance(inp, Mapping):
        raise ValueError("CT-006 input must be a mapping")
    if not _boolean(inp.get("shear_on"), "shear_on"):
        raise ValueError("CT-006 requires an active shear check")
    method = inp.get("shear_method")
    if type(method) is not str or method not in capacity.SHEAR_METHODS:
        raise ValueError("unknown retained shear method")
    links = _boolean(inp.get("shear_links"), "shear_links")
    _mode_code(inp.get("mode"))
    _boolean(inp.get("check_util", True), "check_util")
    for key in ("shear_vx_bw", "shear_vy_bw"):
        if _number(inp.get(key, 0.0), key) < 0.0:
            raise ValueError(f"{key} cannot be negative")
    for key in ("shear_face_x", "shear_face_y"):
        _face_code(str(inp.get(key, "auto")))
    if method.endswith(":2023"):
        _positive(inp.get("shear_dlower"), "shear_dlower")
    if links:
        for key in (
            "shear_vx_link_legs", "shear_vy_link_legs", "shear_link_dia",
            "shear_link_s", "shear_fywk", "strut_cot_min", "strut_cot_max",
        ):
            _positive(inp.get(key), key)
        ductility = str(inp.get("transverse_ductility_class", "B")).upper()
        if ductility not in {"A", "B", "C"}:
            raise ValueError("transverse ductility class must be A, B or C")

    blocks = section_trace_blocks(inp)
    n_prestress = capacity.prestress_axial(inp)
    n_ed_comp = -_number(inp.get("P_pl", 0.0), "P_pl") + n_prestress
    specs = capacity.shear_direction_specs(inp)
    active = tuple(
        component for component in ("vx", "vy")
        if _number(specs[component]["v_ed"], f"{component} demand") > 0.0
    )
    if not active:
        raise ValueError("CT-006 requires at least one positive directional demand")
    contexts = capacity.build_directional_shear_contexts(inp, n_prestress, n_ed_comp)
    directions: list[_Direction] = []
    for component in active:
        direction_context = contexts.get(component)
        if direction_context is None:
            raise ValueError(f"authoritative {component} context is missing")
        faces = [
            _Face(bool(tension_low), payload, link_context)
            for tension_low, (payload, link_context) in zip(
                capacity.shear_face_candidates(
                    specs[component]["face"], specs[component]["moment"]
                ),
                direction_context["candidates"],
                strict=True,
            )
        ]
        directions.append(_Direction(component, specs[component]["axis"], specs[component], faces))
    return blocks, method, links, tuple(directions)


def _chord_context(inp: Mapping[str, Any], face: _Face):
    mode = inp.get("mode")
    if mode not in {"Plastic", "Both"} or not inp.get("check_util", True):
        return None
    context = face.link_context
    assert context is not None
    axis = context["axis"]
    m_signed = _number(inp["Mx_pl" if axis == "x" else "My_pl"], "shear-axis moment")
    m_off = _number(inp["My_pl" if axis == "x" else "Mx_pl"], "off-axis moment")
    m_ed = combined.chord_applied_moment(m_signed, face.tension_low)
    m_rd, _conditional = capacity.shear_face_mrd(
        inp, axis, face.tension_low, m_off=m_off
    )
    if not math.isfinite(float(m_rd)) or m_rd <= 0.0:
        return None
    z_m = _positive(context["z_mm"], "shear lever arm") / 1000.0
    return {
        "m_ed": m_ed, "m_rd": m_rd, "z": z_m, "m_off": m_off,
        "conditional": bool(_conditional), "gets_shift": True,
        "axis": axis, "tension_low": face.tension_low,
    }


def _chord_at(face: _Face, cot: float) -> dict[str, Any]:
    context = face.link_context
    chord = face.chord_context
    assert context is not None and chord is not None
    factor = 1.0 if context.get("model_2023") else 0.5
    result = combined.longitudinal_check(
        chord["m_ed"], chord["m_rd"], factor * context["v_ed"] * cot,
        0.0, chord["z"], cap_shear_force=not context.get("model_2023"),
    )
    result.update(valid=True)
    return result


def _solve_face(inp: Mapping[str, Any], face: _Face) -> None:
    payload = face.payload
    concrete = payload.get("res")
    if not isinstance(concrete, Mapping) or concrete.get("valid") is not True:
        raise ArithmeticError("invalid concrete shear resistance")
    concrete_fields = (
        CONCRETE_2023_FIELDS if payload.get("model_2023")
        else CONCRETE_2005_FIELDS
    )
    _finite_mapping(
        concrete,
        concrete_fields,
        "concrete",
        boolean_keys={"valid", "axial-applied"},
    )
    _finite_mapping(
        {
            "v_ed": payload["v_ed"], "bw": payload["bw"],
            "bw_auto": payload["bw_auto"], "bw_user": float(payload["bw_user"]),
            "d": payload["d"], "asl": payload["asl"], "asl_cg": payload["asl_cg"],
            "asl_bar_count": len(payload["asl_bar_ids"]), "ac": payload["ac"],
            "fck": payload["fck"], "n_ed": payload["n_ed"],
            "n_prestress": payload["n_prestress"], "n_ed_comp": payload["n_ed_comp"],
            "m_ed_2023": payload["m_ed_2023"], "m_prestress": payload["m_prestress"],
            "centroid_x": payload["centroid"][0], "centroid_y": payload["centroid"][1],
            "model_2023": float(payload["model_2023"]), "ddg": payload["ddg"],
            "fyd_flex": payload["fyd_flex"],
        },
        COMMON_FACE_FIELDS,
        "face",
    )
    concrete_util = payload["v_ed"] / concrete["vrd_c"] if concrete["vrd_c"] > 0.0 else math.inf
    _number(concrete_util, "concrete utilisation")
    if face.link_context is None:
        face.metric = concrete_util
        face.status = "PASS" if concrete_util <= 1.0 + 1.0e-9 else "FAIL"
        return

    context = face.link_context
    low, high = context["cot_min"], context["cot_max"]
    probe = context["build"](low, low)
    if (
        probe.get("valid") is not True
        or probe.get("vrd_s", 0.0) <= 0.0
        or probe.get("vrd_max", 0.0) <= 0.0
    ):
        raise ArithmeticError("invalid linked shear resistance")
    demand = context["v_ed"]
    objectives = [
        lambda cot: combined.ratio(demand, context["build"](cot, cot)["vrd_s"]),
        lambda cot: combined.ratio(demand, context["build"](cot, cot)["vrd_max"]),
    ]
    face.chord_context = _chord_context(inp, face)
    if face.chord_context is not None:
        objectives.append(lambda cot: _chord_at(face, cot)["util"])
    cot, governing = combined.governing_strut_cot(objectives, low, high)
    _number(cot, "authoritative cot")
    _number(governing, "authoritative cot objective")
    result = context["build"](cot, cot)
    link_fields = LINK_2023_FIELDS if context.get("model_2023") else LINK_2005_FIELDS
    _finite_mapping(
        result,
        link_fields,
        "linked result",
        boolean_keys={"valid"},
        text_keys={"governs"},
    )
    if result.get("valid") is not True:
        raise ArithmeticError("invalid linked result at authoritative cot")
    utilisation = demand / result["vrd"] if result["vrd"] > 0.0 else math.inf
    _number(utilisation, "linked utilisation")
    factor = 1.0 if context.get("model_2023") else 0.5
    longitudinal = factor * demand * result["cot"]
    angle_limits = context["angle_limits"]
    low_limit, high_limit = angle_limits["minimum"], angle_limits["maximum"]
    wrapper = {
        "util": utilisation,
        "asw": context["asw"],
        "asw_over_s": context["asw_over_s"],
        "legs": context["link_legs"],
        "dia": inp["shear_link_dia"],
        "spacing": inp["shear_link_s"],
        "fywk": inp["shear_fywk"],
        "cot_min": low,
        "cot_max": high,
        "longitudinal_force": longitudinal,
        "cot_limit_lo": low_limit,
        "cot_limit_hi": high_limit,
        "model_2023": float(context.get("model_2023", False)),
        "out_of_limits": float(low < low_limit - 1.0e-9 or high > high_limit + 1.0e-9),
        "required": float(demand > context["vrd_c"]),
        "theta_mode": 1.0,
    }
    if not context.get("model_2023"):
        wrapper["delta_ftd"] = longitudinal
    _finite_mapping(wrapper, LINK_WRAPPER_FIELDS, "linked wrapper")
    if not context.get("model_2023"):
        _finite_mapping(wrapper, LINK_2005_EXTRA_FIELDS, "2005 linked wrapper")
    _finite_mapping({
        "minimum": angle_limits["minimum"],
        "maximum": angle_limits["maximum"],
        "ductility_factor": angle_limits["ductility_factor"],
        "axial_tension_applied": float(angle_limits["axial_tension_applied"]),
        "compression_extension_credited": float(angle_limits["compression_extension_credited"]),
    }, ANGLE_LIMIT_FIELDS, "angle limits")
    face.link_result = dict(result)
    face.link_wrapper = wrapper
    if face.chord_context is not None:
        face.chord_result = _chord_at(face, cot)
    face.metric = utilisation
    face.status = "PASS" if utilisation <= 1.0 + 1.0e-9 else "FAIL"


def _shape(blocks, method, links, branch, directions, context) -> TraceShape:
    members = tuple(
        DirectionShape(
            direction.component,
            direction.axis,
            tuple(FaceShape(
                face.tension_low, tuple(face.payload["asl_bar_ids"]),
                face.chord_result is not None,
            ) for face in direction.faces),
        )
        for direction in directions
    )
    order = ",".join(item.component for item in members)
    face_order = ";".join(
        f"{item.component}:" + ",".join(
            "negative" if face.tension_low else "positive" for face in item.faces
        )
        for item in members
    )
    axes = context_axes(
        context,
        branch=branch,
        direction_cardinality=str(len(members)),
        direction_axes=",".join(f"{item.component}:{item.axis}" for item in members),
        direction_order=order,
        face_order=face_order,
        links="enabled" if links else "disabled",
        local_lifecycle=("published-not-implemented" if method.endswith(":2023") else "current"),
    )
    return TraceShape(blocks, context_id(context), method, links, branch, members, axes)


def _put_shared(values: dict[str, float], shape: TraceShape, inp, directions) -> None:
    for ring_index, ring in enumerate(shape.blocks.geometry.rings):
        for point_index, point in enumerate(ring):
            values[f"geometry-ring-{ring_index:03d}-point-{point_index:04d}-x"] = point[0]
            values[f"geometry-ring-{ring_index:03d}-point-{point_index:04d}-y"] = point[1]
    for kind, elements in (("bar", shape.blocks.geometry.bars), ("tendon", shape.blocks.geometry.tendons)):
        for index, element in enumerate(elements):
            prefix = f"geometry-{kind}-{index:04d}"
            values[f"{prefix}-x"] = element.x
            values[f"{prefix}-y"] = element.y
            values[f"{prefix}-area"] = element.area
    for key, value in shape.blocks.plastic_actions.values:
        values[f"input-action-{trace_identity_token(key)}"] = value
    specs = {direction.component: direction.spec for direction in directions}
    all_specs = capacity.shear_direction_specs(inp)
    values.update({
        "input-shear-enabled": 1.0,
        "input-shear-shear-vx": specs.get("vx", all_specs["vx"])["signed_v_ed"],
        "input-shear-shear-vy": specs.get("vy", all_specs["vy"])["signed_v_ed"],
        "input-shear-face-x": _face_code(str(inp.get("shear_face_x", "auto"))),
        "input-shear-face-y": _face_code(str(inp.get("shear_face_y", "auto"))),
        "input-shear-bw-vx": float(inp.get("shear_vx_bw", 0.0)),
        "input-shear-bw-vy": float(inp.get("shear_vy_bw", 0.0)),
        "input-shear-links-enabled": float(shape.links),
        "input-shear-mode-code": _mode_code(inp.get("mode")),
        "input-shear-check-util": float(inp.get("check_util", True)),
    })
    if shape.method.endswith(":2023"):
        values["input-shear-aggregate-lower-size"] = float(inp["shear_dlower"])
    if shape.links:
        values.update({
            "input-shear-legs-vx": float(inp["shear_vx_link_legs"]),
            "input-shear-legs-vy": float(inp["shear_vy_link_legs"]),
            "input-shear-link-dia": float(inp["shear_link_dia"]),
            "input-shear-link-spacing": float(inp["shear_link_s"]),
            "input-shear-link-fywk": float(inp["shear_fywk"]),
            "input-shear-cot-min": float(inp["strut_cot_min"]),
            "input-shear-cot-max": float(inp["strut_cot_max"]),
            "input-shear-ductility-code": float({"A": 0, "B": 1, "C": 2}[str(inp.get("transverse_ductility_class", "B")).upper()]),
        })
    for material in (shape.blocks.concrete, *shape.blocks.bars, *shape.blocks.tendons):
        prefix = f"material-{material.kind}-{trace_identity_token(material.element_id)}-{trace_identity_token(material.material_id)}"
        for name, value in material.values:
            values[f"{prefix}-{trace_identity_token(name)}"] = value
    values["normalised-shear-inputs"] = 1.0
    is_2023 = shape.method.endswith(":2023")
    is_dk = "DK NA:2024" in shape.method
    values["method-concrete-rule"] = 2023.0 if is_2023 else 2005.0
    values["method-vmin-rule"] = 2.0 if is_2023 else 1.0 if is_dk else 0.0
    if shape.links:
        values["method-link-rule"] = 2023.0 if is_2023 else 2005.0
        values["method-nu-rule"] = 2.0 if is_2023 else 1.0 if is_dk else 0.0
        values["method-selector-cardinality"] = 1501.0
    values["shear-method-vector"] = 1.0


def _face_values(values: dict[str, float], shape: TraceShape, direction: _Direction, face_index: int) -> None:
    face = direction.faces[face_index]
    payload = face.payload
    prefix = f"{direction.component}-face-{face_index:02d}"
    values[f"{prefix}-identity"] = 0.0 if face.tension_low else 1.0
    common = {
        "v-ed": payload["v_ed"], "bw": payload["bw"], "bw-auto": payload["bw_auto"],
        "bw-user": float(payload["bw_user"]), "d": payload["d"], "asl": payload["asl"],
        "asl-cg": payload["asl_cg"], "asl-bar-count": len(payload["asl_bar_ids"]),
        "ac": payload["ac"], "fck": payload["fck"], "n-ed": payload["n_ed"],
        "n-prestress": payload["n_prestress"], "n-ed-comp": payload["n_ed_comp"],
        "m-ed-2023": payload["m_ed_2023"], "m-prestress": payload["m_prestress"],
        "centroid-x": payload["centroid"][0], "centroid-y": payload["centroid"][1],
        "model-2023": float(payload["model_2023"]), "ddg": payload["ddg"],
        "fyd-flex": payload["fyd_flex"],
    }
    for name, _unit in COMMON_FACE_FIELDS:
        values[f"{prefix}-{name}"] = float(common[name])
    for index, bar_id in enumerate(payload["asl_bar_ids"]):
        values[f"{prefix}-asl-bar-{index:03d}"] = float(bar_id)
    concrete_fields = CONCRETE_2023_FIELDS if payload["model_2023"] else CONCRETE_2005_FIELDS
    for name, _unit in concrete_fields:
        values[f"{prefix}-concrete-{name}"] = float(payload["res"][name.replace("-", "_")])
    concrete_util = payload["v_ed"] / payload["res"]["vrd_c"]
    values[f"{prefix}-concrete-util"] = concrete_util
    if shape.links:
        assert face.link_result is not None and face.link_wrapper is not None
        link_fields = LINK_2023_FIELDS if payload["model_2023"] else LINK_2005_FIELDS
        for name, _unit in link_fields:
            key = name.replace("-", "_")
            if name == "governs":
                value = 0.0 if "stirrup" in face.link_result["governs"] or "links" in face.link_result["governs"] else 1.0
            else:
                value = face.link_result[key]
            values[f"{prefix}-link-result-{name}"] = float(value)
        for name, _unit in LINK_WRAPPER_FIELDS:
            values[f"{prefix}-link-{name}"] = float(face.link_wrapper[name.replace("-", "_")])
        if not payload["model_2023"]:
            values[f"{prefix}-link-delta-ftd"] = float(face.link_wrapper["delta_ftd"])
        limits = face.link_context["angle_limits"]
        angle_values = {
            "minimum": limits["minimum"], "maximum": limits["maximum"],
            "ductility-factor": limits["ductility_factor"],
            "axial-tension-applied": float(limits["axial_tension_applied"]),
            "compression-extension-credited": float(limits["compression_extension_credited"]),
        }
        for name, _unit in ANGLE_LIMIT_FIELDS:
            values[f"{prefix}-angle-limit-{name}"] = float(angle_values[name])
        if face.chord_result is not None:
            assert face.chord_context is not None
            for name, _unit in CHORD_CONTEXT_FIELDS:
                values[f"{prefix}-chord-{name}"] = float(
                    face.chord_context[name.replace("-", "_")]
                )
            for name, _unit in CHORD_RESULT_FIELDS:
                values[f"{prefix}-chord-result-{name}"] = float(
                    face.chord_result[name.replace("-", "_")]
                )
    values[f"{prefix}-shear-metric"] = face.metric
    values[f"{prefix}-shear-status"] = _status_code(face.status)
    values[f"{prefix}-evidence"] = 1.0


def _assert_close(actual: Any, expected: Any, label: str) -> None:
    actual_number = _number(actual, label)
    if not math.isclose(actual_number, float(expected), rel_tol=2.0e-12, abs_tol=2.0e-12):
        raise TraceValidationError(f"{label} differs from authoritative replay")


def _assert_value(actual: Any, expected: Any, label: str) -> None:
    if type(expected) is bool:
        if actual is not expected:
            raise TraceValidationError(f"{label} differs from authoritative replay")
    elif type(expected) is str:
        if actual != expected:
            raise TraceValidationError(f"{label} differs from authoritative replay")
    else:
        _assert_close(actual, expected, label)


def _assert_fields(actual, expected, fields, label, aliases=None) -> None:
    if not isinstance(actual, Mapping):
        raise TraceValidationError(f"{label} is missing")
    aliases = aliases or {}
    for name, _unit in fields:
        key = name.replace("-", "_")
        _assert_value(actual.get(aliases.get(key, key)), expected[key], f"{label} {key}")


def _check_shear_payload(candidate: Mapping[str, Any], face: _Face, *, face_mode: str) -> None:
    expected = face.payload
    if not isinstance(candidate, Mapping):
        raise TraceValidationError("finite shear payload is missing")
    for key in ("component", "axis", "method", "tension_low"):
        _assert_value(candidate.get(key), expected[key], f"finite shear {key}")
    if candidate.get("face_mode") != face_mode:
        raise TraceValidationError("finite shear face mode differs from replay")
    if candidate.get("asl_bar_ids") != expected["asl_bar_ids"]:
        raise TraceValidationError("finite shear tension-bar identity differs from replay")
    if tuple(candidate.get("centroid", ())) != tuple(expected["centroid"]):
        raise TraceValidationError("finite shear centroid differs from replay")
    candidate_fields = tuple(
        field for field in COMMON_FACE_FIELDS
        if field[0] not in {"asl-bar-count", "centroid-x", "centroid-y"}
    )
    _assert_fields(candidate, expected, candidate_fields, "finite shear")
    concrete_fields = CONCRETE_2023_FIELDS if expected["model_2023"] else CONCRETE_2005_FIELDS
    candidate_res = candidate.get("res")
    _assert_fields(candidate_res, expected["res"], concrete_fields, "finite concrete")
    if expected["model_2023"] and candidate_res.get("model") != "2023":
        raise TraceValidationError("finite concrete model identity differs from replay")
    concrete_util = expected["v_ed"] / expected["res"]["vrd_c"]
    _assert_close(candidate.get("util"), concrete_util, "finite concrete utilisation")
    if face.link_context is None:
        if candidate.get("links") is not None:
            raise TraceValidationError("unexpected linked shear payload")
        return
    links = candidate.get("links")
    if not isinstance(links, Mapping):
        raise TraceValidationError("finite linked shear payload is missing")
    result = links.get("res")
    assert face.link_result is not None and face.link_wrapper is not None
    link_fields = LINK_2023_FIELDS if expected["model_2023"] else LINK_2005_FIELDS
    _assert_fields(result, face.link_result, link_fields, "finite linked")
    if expected["model_2023"] and result.get("model") != "2023":
        raise TraceValidationError("finite linked model identity differs from replay")
    wrapper_keys = {
        "spacing": "s", "longitudinal_force": "longitudinal_shear_force",
    }
    wrapper_expected = dict(face.link_wrapper)
    for key in ("model_2023", "out_of_limits", "required"):
        wrapper_expected[key] = bool(wrapper_expected[key])
    wrapper_expected["theta_mode"] = "utilisation"
    _assert_fields(links, wrapper_expected, LINK_WRAPPER_FIELDS, "finite linked", wrapper_keys)
    model_2023 = bool(expected["model_2023"])
    expected_delta = None if model_2023 else face.link_wrapper["longitudinal_force"]
    if expected_delta is None:
        if links.get("delta_ftd") is not None:
            raise TraceValidationError("2023 linked delta_Ftd must be absent")
    else:
        _assert_close(links.get("delta_ftd"), expected_delta, "finite linked delta_Ftd")
    expected_symbol = "NVd" if model_2023 else "delta_Ftd"
    expected_clause = "8.2.3(8), Formula (8.50)" if model_2023 else "6.2.3(7), Formula (6.18)"
    if links.get("longitudinal_shear_symbol") != expected_symbol or links.get("longitudinal_shear_clause") != expected_clause:
        raise TraceValidationError("linked longitudinal-force identity differs from replay")
    limits = face.link_context["angle_limits"]
    candidate_limits = links.get("angle_limits")
    _assert_fields(candidate_limits, limits, ANGLE_LIMIT_FIELDS, "linked angle limit")
    for key in ("basis", "ductility_class", "clause"):
        if candidate_limits.get(key) != limits[key]:
            raise TraceValidationError(f"angle limit {key} differs from replay")
    if links.get("z_source") != face.link_context["z_src"]:
        raise TraceValidationError("linked lever-arm source differs from replay")
    chord = links.get("chord")
    candidates = links.get("chord_candidates")
    if face.chord_result is None:
        if chord is not None or candidates not in (None, []):
            raise TraceValidationError("unexpected longitudinal chord evidence")
        return
    if not isinstance(chord, Mapping) or type(candidates) is not list or len(candidates) != 1:
        raise TraceValidationError("longitudinal chord evidence is incomplete")
    assert face.chord_context is not None
    for item in (chord, candidates[0]):
        _assert_fields(item, face.chord_context, CHORD_CONTEXT_FIELDS, "longitudinal chord")
        _assert_fields(item, face.chord_result, CHORD_RESULT_FIELDS, "longitudinal chord")
        for key in ("axis", "tension_low"):
            if item.get(key) != face.chord_context[key]:
                raise TraceValidationError(f"longitudinal chord {key} differs from replay")
        if item.get("role") != "shear_axis" or item.get("gets_shift") is not True:
            raise TraceValidationError("longitudinal chord identity differs from replay")
        if (
            item.get("has_torsion") is not False
            or item.get("off_not_evaluated") is not None
            or item.get("theta_mode") != "utilisation"
        ):
            raise TraceValidationError("longitudinal chord scope differs from replay")
    if links.get("chord_off") is not None:
        raise TraceValidationError("shear-only trace cannot contain an off-axis torsion chord")


def _check_candidate(out: Mapping[str, Any], directions: tuple[_Direction, ...]) -> None:
    shear_out = out.get("shear") if isinstance(out.get("shear"), Mapping) else out
    order = tuple(direction.component for direction in directions)
    if len(order) == 2:
        candidate_directions = shear_out.get("directions")
        if not isinstance(candidate_directions, dict) or tuple(candidate_directions) != ("vx", "vy"):
            raise TraceValidationError("candidate direction insertion order must be exactly ('vx', 'vy')")
        if type(shear_out.get("active_directions")) is not list or tuple(shear_out["active_directions"]) != order:
            raise TraceValidationError("candidate active-direction order differs from replay")
        if shear_out.get("biaxial") is not True or "status" in shear_out:
            raise TraceValidationError("candidate cross-direction state is invalid")
        roots = candidate_directions
    else:
        if "directions" in shear_out:
            raise TraceValidationError("single-direction candidate cannot contain a direction map")
        roots = {order[0]: shear_out}
    for direction in directions:
        root = roots.get(direction.component)
        if not isinstance(root, Mapping):
            raise TraceValidationError(f"candidate {direction.component} is missing")
        candidates = root.get("face_candidates")
        if type(candidates) is not list or len(candidates) != len(direction.faces):
            raise TraceValidationError(f"candidate {direction.component} face cardinality differs from replay")
        if root.get("both_faces_evaluated") is not (len(direction.faces) == 2):
            raise TraceValidationError(f"candidate {direction.component} face-cardinality flag differs from replay")
        for index, (candidate, face) in enumerate(zip(candidates, direction.faces, strict=True)):
            if candidate.get("tension_low") is not face.tension_low:
                raise TraceValidationError(f"candidate {direction.component} face order differs from replay")
            if candidate.get("shear_status") != face.status:
                raise TraceValidationError("candidate face verdict differs from replay")
            _assert_close(candidate.get("shear_metric"), face.metric, "candidate face shear metric")
            _check_shear_payload(candidate.get("shear"), face, face_mode="selected")
        selected = direction.governing
        selected_face = direction.faces[selected]
        _check_shear_payload(root, selected_face, face_mode=str(direction.spec["face"]))
        expected_face = "negative" if selected_face.tension_low else "positive"
        if root.get("governing_face") != expected_face or root.get("status") != direction.status:
            raise TraceValidationError("candidate governing face or aggregate status differs from replay")
        for key in ("associated_moment", "associated_moment_origin", "signed_v_ed"):
            expected_key = "moment" if key == "associated_moment" else "moment_origin" if key == "associated_moment_origin" else "signed_v_ed"
            _assert_close(root.get(key), direction.spec[expected_key], f"candidate {key}")
        domain = (root.get("governing_domains") or {}).get("shear")
        if not isinstance(domain, Mapping):
            raise TraceValidationError("candidate governing shear domain is missing")
        if domain.get("face") != expected_face or domain.get("status") != direction.status:
            raise TraceValidationError("candidate governing shear domain differs from replay")
        _assert_close(domain.get("util"), selected_face.metric, "candidate governing shear utilisation")
        expected_cot = selected_face.link_result["cot"] if selected_face.link_result is not None else None
        if expected_cot is None:
            if domain.get("cot") is not None:
                raise TraceValidationError("unlinked governing shear cannot declare cot")
        else:
            _assert_close(domain.get("cot"), expected_cot, "candidate governing shear cot")


def replay_shear_evidence(
    inp: Mapping[str, Any],
    out: Mapping[str, Any],
    context: Mapping[str, Any],
) -> ReplayEvidence:
    """Choose branch from original inputs, then close finite candidate evidence."""

    try:
        blocks, method, links, directions = _original_inputs(inp)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"invalid CT-006 input: {exc}") from exc
    failure = None
    try:
        for direction in directions:
            for face in direction.faces:
                _solve_face(inp, face)
            direction.governing = max(
                range(len(direction.faces)),
                key=lambda index: capacity.assessment_key(
                    direction.faces[index].status, direction.faces[index].metric
                ),
            )
            direction.status = capacity.aggregate_assessment_status(
                face.status for face in direction.faces
            )
    except (ArithmeticError, KeyError, TypeError, ValueError, OverflowError) as exc:
        failure = str(exc)
    branch = BRANCH_FAILED if failure is not None else BRANCH_FINITE
    shape = _shape(blocks, method, links, branch, directions, context)
    if failure is not None:
        reason = "authoritative CT-006 mechanics are invalid or non-finite"
        return ReplayEvidence(
            shape,
            {"authoritative-shear-failure": 1.0},
            {"ct-006-directional-shear-result": TraceResult(RESULT_FAILED, None, reason)},
            (reason,),
        )
    if not isinstance(out, Mapping):
        raise TraceValidationError("finite CT-006 candidate must be a mapping")
    _check_candidate(out, directions)
    values: dict[str, float] = {}
    _put_shared(values, shape, inp, directions)
    for direction, direction_shape in zip(directions, shape.directions, strict=True):
        for index, _face_shape in enumerate(direction_shape.faces):
            _face_values(values, shape, direction, index)
        prefix = direction.component
        selected_face = direction.faces[direction.governing]
        values[f"{prefix}-governing-face"] = float(direction.governing)
        values[f"{prefix}-aggregate-status"] = _status_code(direction.status)
        values[f"{prefix}-governing-metric"] = selected_face.metric
        values[f"{prefix}-direction-evidence"] = 1.0
    values["ct-006-directional-shear-result"] = 1.0
    warnings = (
        "The local DS/EN 1992-1-1:2023 source is published-not-implemented and is not promoted to Danish project applicability.",
    ) if method.endswith(":2023") else ()
    return ReplayEvidence(shape, values, {}, warnings)
