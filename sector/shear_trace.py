"""Solver-owned unpublished CT-006 capacity-only directional shear trace."""

from __future__ import annotations

import math
import numbers
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from . import capacity, codes, combined
from .calculation_trace import (
    RESULT_FAILED, RESULT_FINITE, TraceBundle, TraceCalculation, TraceDependency,
    TraceResult, TraceStep, TraceValidationError,
    create_bundle, validate_bundle,
)
from .section_trace_blocks import (
    _materials as selected_material_blocks,
    context_axes, context_id, section_trace_blocks,
)
from .shear_trace_contract import (
    AGGREGATE_EXCLUDED, AGGREGATE_KEYS, ANGLE_LIMIT_KEYS, COMPONENT_KEYS,
    CONCRETE_RESULT_KEYS, CORE_INPUT_KEYS, COVERAGE_ID, DIRECTION_SUFFIX_KEYS,
    DIRECTIONS, FACE_WRAPPER_EXCLUDED, FACE_WRAPPER_KEYS, GOVERNING_DOMAIN_EXCLUDED,
    GOVERNING_SHEAR_KEYS, LINK_EXCLUDED, LINK_INPUT_KEYS, LINK_KEYS, LINK_RESULT_KEYS,
    METHOD_ID, PHYSICAL_AXES, SHEAR_EXCLUDED, SHEAR_KEYS, DirectionShape,
    expected_registry, expected_step_contract, material_leaf_id,
)
from .trace_registry import audit_trace_registry


_TOL = 1.0e-9
_FAILURE_REASON = (
    "The authoritative CT-006 core reconstruction did not produce a complete "
    "finite shear state; no resistance, utilisation, or verdict is published."
)
_NOT_APPLICABLE = {
    0: "CT-006 not applicable: retained output has no active shear direction",
    1: "CT-006 not applicable: retained one-active output is the uniaxial shear payload",
}


@dataclass(frozen=True, slots=True)
class FaceEvidence:
    tension_low: bool
    payload: Mapping[str, Any]
    links: Mapping[str, Any] | None
    metric: float
    status: str
    values: dict[str, float]


@dataclass(frozen=True, slots=True)
class DirectionEvidence:
    shape: DirectionShape
    faces: tuple[FaceEvidence, ...]
    values: dict[str, float]
    governing: FaceEvidence | None
    status: str | None
    warnings: tuple[str, ...]
    signed_v_ed: float
    associated_moment: float
    associated_moment_origin: float


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


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TraceValidationError(f"{label} must be a mapping")
    if any(type(key) is not str for key in value):
        raise TraceValidationError(f"{label} keys must be text")
    return value


def _sequence(value: Any, label: str) -> tuple[Any, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TraceValidationError(f"{label} must be an ordered sequence")
    return tuple(value)


def _retained_mapping(value, keys, excluded, label) -> Mapping[str, Any]:
    candidate = _mapping(value, label)
    allowed = set(keys) | set(excluded)
    unknown = [key for key in candidate if key not in allowed]
    if unknown:
        raise TraceValidationError(f"{label} has unexpected fields {', '.join(unknown)}")
    retained = tuple(key for key in candidate if key in keys)
    if retained != tuple(keys):
        raise TraceValidationError(
            f"{label} retained field order {retained!r}; expected {tuple(keys)!r}"
        )
    return candidate


def _close(actual: float, expected: float) -> bool:
    return abs(actual - expected) <= _TOL * max(1.0, abs(expected))


def _compare(actual: Any, expected: Any, label: str) -> None:
    if isinstance(expected, Mapping):
        actual = _mapping(actual, label)
        if tuple(actual) != tuple(expected):
            raise TraceValidationError(f"{label} field inventory differs")
        for key in expected:
            _compare(actual[key], expected[key], f"{label}.{key}")
        return
    if isinstance(expected, (tuple, list)):
        actual = _sequence(actual, label)
        if len(actual) != len(expected):
            raise TraceValidationError(f"{label} cardinality differs")
        for index, (got, wanted) in enumerate(zip(actual, expected)):
            _compare(got, wanted, f"{label}[{index}]")
        return
    if expected is None or type(expected) in {bool, str}:
        if type(actual) is not type(expected) or actual != expected:
            raise TraceValidationError(f"{label} differs from authoritative replay")
        return
    if not isinstance(actual, numbers.Real) or isinstance(actual, bool):
        raise TraceValidationError(f"{label} must be numerical")
    got, wanted = float(actual), float(expected)
    if not math.isfinite(got) or not _close(got, wanted):
        raise TraceValidationError(f"{label} differs from authoritative replay")


def _validated_demands(inp: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    shear_on = inp.get("shear_on")
    if type(shear_on) is not bool:
        raise TraceValidationError("shear_on must be Boolean")
    components = _retained_mapping(
        inp.get("shear_components"), DIRECTIONS, (), "shear_components"
    )
    result = {}
    for direction in DIRECTIONS:
        scalar_key = "shear_Vx" if direction == "vx" else "shear_Vy"
        face_key = "shear_face_x" if direction == "vx" else "shear_face_y"
        scalar = _number(inp.get(scalar_key), scalar_key)
        component = _retained_mapping(
            components[direction], COMPONENT_KEYS, (), f"shear_components.{direction}"
        )
        signed = _number(component["signed_v_ed"], f"{direction} signed_v_ed")
        magnitude = _number(component["v_ed"], f"{direction} v_ed", nonnegative=True)
        if scalar != signed:
            raise TraceValidationError(f"{direction} scalar and component signed demands differ")
        if magnitude != abs(signed):
            raise TraceValidationError(f"{direction} magnitude differs from signed demand")
        axis = component["axis"]
        if type(axis) is not str or axis != PHYSICAL_AXES[direction]:
            raise TraceValidationError(f"{direction} physical axis differs")
        face = inp.get(face_key)
        if type(face) is not str or face not in {"auto", "negative", "positive"}:
            raise TraceValidationError(f"{direction} face selector is invalid")
        if component["face"] != face or type(component["face"]) is not str:
            raise TraceValidationError(f"{direction} component face differs")
        active = bool(shear_on and magnitude > 0.0)
        if type(component["active"]) is not bool or component["active"] is not active:
            raise TraceValidationError(f"{direction} active flag differs")
        result[direction] = dict(
            scalar=scalar, signed=signed, magnitude=magnitude, axis=axis,
            face=face, active=active,
        )
    return result


def shear_core_applicability(inp: Mapping[str, Any]) -> str:
    """Return the retained branch after validating all signed/absolute demands."""

    directions = _validated_demands(inp)
    count = sum(item["active"] for item in directions.values())
    return "directional" if count == 2 else f"not-applicable-{count}-active"


def _require_input_inventory(inp: Mapping[str, Any], links: bool) -> None:
    required = (*CORE_INPUT_KEYS, *(LINK_INPUT_KEYS if links else ()))
    missing = tuple(key for key in required if key not in inp)
    if missing:
        raise TraceValidationError(f"CT-006 input inventory missing {missing!r}")


def _link_steel_block(inp):
    material_id = inp.get("capacity_steel_material_id")
    if (type(material_id) is not str or not material_id
            or material_id != material_id.strip()):
        raise TraceValidationError("capacity_steel_material_id must be non-blank text")
    aligned = dict(
        inp,
        bar_materials=(inp.get("steel"),),
        bar_elements=({"id": "capacity-link-steel", "material_id": material_id},),
    )
    return selected_material_blocks(
        aligned, kind="bar", count=1, default=inp.get("steel")
    )[0]


def _reject_2023_sources(blocks, link_steel_source=None) -> None:
    sources = tuple(material.provenance.source for material in (
        blocks.concrete, *blocks.bars, *blocks.tendons
    )) + ((link_steel_source,) if link_steel_source is not None else ())
    for source in sources:
        citation = source.citation
        if citation is not None and "2023" in citation.document:
            raise TraceValidationError(
                "2023 material provenance is published but not implemented for CT-006"
            )


def _geometry_values(inp, blocks) -> dict[str, float]:
    values: dict[str, float] = {}
    raw_rings = (_sequence(inp.get("outer"), "outer"),
                 *(_sequence(inp.get("holes", ()), "holes")))
    if len(raw_rings) != len(blocks.geometry.rings):
        raise TraceValidationError("raw and immutable ring cardinality differs")
    for ring_index, (raw, retained) in enumerate(zip(raw_rings, blocks.geometry.rings)):
        raw = _sequence(raw, f"ring {ring_index}")
        if len(raw) != len(retained):
            raise TraceValidationError("raw and immutable point cardinality differs")
        for point_index, (point, expected) in enumerate(zip(raw, retained)):
            point = _sequence(point, "section point")
            if len(point) != 2:
                raise TraceValidationError("section points need x and y")
            for suffix, raw_value, wanted in zip(("x", "y"), point, expected):
                value = _number(raw_value, f"ring {ring_index} point {point_index} {suffix}")
                if value != wanted:
                    raise TraceValidationError("raw and immutable section geometry differs")
                values[f"geometry-ring-{ring_index:03d}-point-{point_index:04d}-{suffix}"] = value
    for kind, raw_key, retained in (
        ("bar", "bars", blocks.geometry.bars),
        ("tendon", "tendons", blocks.geometry.tendons),
    ):
        raw_items = _sequence(inp.get(raw_key, ()), raw_key)
        if len(raw_items) != len(retained):
            raise TraceValidationError(f"raw and immutable {kind} cardinality differs")
        for index, (raw, expected) in enumerate(zip(raw_items, retained)):
            raw = _sequence(raw, f"{kind} {index}")
            if len(raw) != 3:
                raise TraceValidationError(f"{kind} entries need x, y, area")
            wanted = (expected.x, expected.y, expected.area * 1.0e6)
            for suffix, raw_value, expected_value in zip(("x", "y", "area"), raw, wanted):
                value = _number(raw_value, f"{kind} {index} {suffix}")
                if not _close(value, expected_value):
                    raise TraceValidationError(f"raw and immutable {kind} geometry differs")
                values[f"geometry-{kind}-{index:04d}-{suffix}"] = (
                    value / 1.0e6 if suffix == "area" else value
                )
    values["geometry-vector"] = 1.0
    return values


def _common_values(inp, blocks, demands, direction, links):
    values = {}
    for name in ("P_pl", "Mx_pl", "My_pl"):
        values[f"input-action-u{name.encode().hex()}"] = _number(inp.get(name), name)
    face_codes = {"auto": 0.0, "negative": -1.0, "positive": 1.0}
    for name in DIRECTIONS:
        item = demands[name]
        values.update({
            f"input-{name}-scalar-signed": item["scalar"],
            f"input-{name}-component-signed": item["signed"],
            f"input-{name}-component-absolute": item["magnitude"],
            f"input-{name}-active": 1.0 if item["active"] else 0.0,
            f"input-{name}-axis-code": 0.0 if item["axis"] == "x" else 1.0,
            f"input-{name}-face-code": face_codes[item["face"]],
        })
    values["input-shear-enabled"] = 1.0
    values["input-method-code"] = 1.0 if inp["shear_method"] == codes.EC2_2005_DKNA.label else 0.0
    values["input-links-enabled"] = 1.0 if links else 0.0
    width_key = "shear_vx_bw" if direction == "vx" else "shear_vy_bw"
    values["input-width-override"] = _number(inp.get(width_key), width_key, nonnegative=True)
    values.update(_geometry_values(inp, blocks))
    for material in (blocks.concrete, *blocks.bars, *blocks.tendons):
        for name, value in material.values:
            values[material_leaf_id(material, name)] = value
    values["material-vector"] = 1.0
    if links:
        leg_key = "shear_vx_link_legs" if direction == "vx" else "shear_vy_link_legs"
        values.update({
            "input-link-legs": _number(inp.get(leg_key), leg_key, positive=True),
            "input-link-diameter": _number(inp.get("shear_link_dia"), "shear_link_dia", positive=True),
            "input-link-spacing": _number(inp.get("shear_link_s"), "shear_link_s", positive=True),
            "input-link-fywk": _number(inp.get("shear_fywk"), "shear_fywk", positive=True),
            "input-cot-min": _number(inp.get("strut_cot_min"), "strut_cot_min", positive=True),
            "input-cot-max": _number(inp.get("strut_cot_max"), "strut_cot_max", positive=True),
            "input-link-steel-gamma-y": _number(
                getattr(inp.get("steel"), "gamma_y", None),
                "steel gamma_y", positive=True,
            ),
        })
    values["normalised-shear-inputs"] = 1.0
    return values


def _finite_numbers(value: Mapping[str, Any], names: Sequence[str]) -> bool:
    try:
        return all(type(value[name]) in {int, float} and not isinstance(value[name], bool)
                   and math.isfinite(float(value[name])) for name in names)
    except (KeyError, TypeError, ValueError):
        return False


def _links_replay(payload, ctx) -> Mapping[str, Any] | None:
    if ctx is None:
        return None
    probe = ctx["build"](ctx["cot_min"], ctx["cot_min"])
    if not (probe.get("valid") and probe.get("vrd_s", 0.0) > 0.0
            and probe.get("vrd_max", 0.0) > 0.0):
        return None
    v_ed = float(payload["v_ed"])
    utilities = (
        lambda cot: combined.ratio(v_ed, ctx["build"](cot, cot)["vrd_s"]),
        lambda cot: combined.ratio(v_ed, ctx["build"](cot, cot)["vrd_max"]),
    )
    cot, _ = combined.governing_strut_cot(
        utilities, ctx["cot_min"], ctx["cot_max"], n=1501
    )
    result = ctx["build"](cot, cot)
    if not result.get("valid") or not _finite_numbers(result, (
        "vrd_s", "vrd_max", "vrd", "cot", "theta_deg", "z", "fywd", "nu1",
        "alpha_cw", "sigma_cp", "fcd", "gamma_s", "asw_over_s",
    )) or result["vrd"] <= 0.0:
        return None
    limits = ctx["angle_limits"]
    return {
        "res": result,
        "util": v_ed / result["vrd"],
        "asw": ctx["asw"],
        "asw_over_s": ctx["asw_over_s"],
        "legs": ctx["link_legs"],
        "dia": None,
        "s": None,
        "fywk": None,
        "cot_min": ctx["cot_min"],
        "cot_max": ctx["cot_max"],
        "cot_limit_lo": limits["minimum"],
        "cot_limit_hi": limits["maximum"],
        "angle_limits": limits,
        "model_2023": False,
        "z_source": ctx["z_src"],
        "out_of_limits": bool(
            ctx["cot_min"] < limits["minimum"] - _TOL
            or ctx["cot_max"] > limits["maximum"] + _TOL
        ),
        "required": bool(v_ed > ctx["vrd_c"]),
        "theta_mode": "utilisation",
    }


def _face_values(common, payload, links, index):
    values = dict(common)
    p = f"face-{index:02d}"
    res = payload["res"]
    values.update({
        f"{p}-identity": 1.0 if payload["tension_low"] else 0.0,
        f"{p}-area": payload["ac"],
        f"{p}-centroid-x": payload["centroid"][0],
        f"{p}-centroid-y": payload["centroid"][1],
        f"{p}-prestress": payload["n_prestress"],
        f"{p}-m-prestress": payload["m_prestress"],
        f"{p}-associated-moment": payload["m_ed_2023"],
        f"{p}-bw-auto": payload["bw_auto"],
        f"{p}-bw-effective": payload["bw"],
        f"{p}-asl": payload["asl"],
        f"{p}-effective-depth": payload["d"],
        f"{p}-compression-positive-axial": payload["n_ed_comp"],
        f"{p}-fcd": res["fcd"], f"{p}-k": res["k"],
        f"{p}-rho-l": res["rho_l"], f"{p}-sigma-cp": res["sigma_cp"],
        f"{p}-crd-c": res["crd_c"], f"{p}-k1": res["k1"],
        f"{p}-vmin": res["vmin"], f"{p}-v-basic": res["v_basic"],
        f"{p}-v-floor": res["v_floor"], f"{p}-vrd-c": res["vrd_c"],
    })
    cutil = payload["v_ed"] / res["vrd_c"]
    values[f"{p}-concrete-utilisation"] = cutil
    values[f"{p}-concrete-verdict"] = 1.0 if cutil <= 1.0 + _TOL else 0.0
    values[f"{p}-concrete-evidence"] = 1.0
    overall = cutil
    if links is not None:
        lr = links["res"]
        values.update({
            f"{p}-asw": links["asw"], f"{p}-asw-over-s": links["asw_over_s"],
            f"{p}-z": lr["z"], f"{p}-fywd": lr["fywd"], f"{p}-nu1": lr["nu1"],
            f"{p}-link-sigma-cp": lr["sigma_cp"], f"{p}-alpha-cw": lr["alpha_cw"],
            f"{p}-selector-operands": 1.0, f"{p}-cot": lr["cot"],
            f"{p}-theta": lr["theta_deg"], f"{p}-vrd-s": lr["vrd_s"],
            f"{p}-vrd-max": lr["vrd_max"], f"{p}-vrd-links": lr["vrd"],
            f"{p}-links-utilisation": links["util"],
            f"{p}-links-verdict": 1.0 if links["util"] <= 1.0 + _TOL else 0.0,
            f"{p}-links-required": 1.0 if links["required"] else 0.0,
            f"{p}-links-evidence": 1.0,
        })
        overall = links["util"]
    values[f"{p}-complete-evidence"] = 1.0
    return values, overall


def _shape(blocks, direction, demands, faces, links, failed, variant,
           link_steel_material_id, link_steel_source, context):
    face_order = ",".join("negative" if item else "positive" for item in faces)
    axis_values = dict(
        direction=direction,
        face_order=face_order,
        face_selector=demands[direction]["face"],
        physical_axis=PHYSICAL_AXES[direction],
        shear_method=variant,
    )
    if links:
        axis_values["capacity_steel_material_id"] = link_steel_material_id
    axes = context_axes(context, **axis_values)
    return DirectionShape(
        blocks, direction, demands[direction]["face"], faces, links, failed,
        variant, link_steel_material_id, link_steel_source,
        f"ct-006-{context_id(context)}-{direction}", axes,
    )


def _replay(inp, shear_out, context):
    demands = _validated_demands(inp)
    active = tuple(name for name in DIRECTIONS if demands[name]["active"])
    if len(active) != 2:
        raise TraceValidationError(_NOT_APPLICABLE[len(active)])
    method = inp.get("shear_method")
    if method not in {codes.EC2_2005.label, codes.EC2_2005_DKNA.label}:
        raise TraceValidationError(
            "CT-006 finite publication supports only the implemented 2004+A1/AC base and DK methods"
        )
    links = inp.get("shear_links")
    if type(links) is not bool:
        raise TraceValidationError("shear_links must be Boolean")
    _require_input_inventory(inp, links)
    blocks = section_trace_blocks(inp)
    link_steel = _link_steel_block(inp) if links else None
    _reject_2023_sources(
        blocks, None if link_steel is None else link_steel.provenance.source
    )
    variant = "dk" if method == codes.EC2_2005_DKNA.label else "base"
    n_prestress = capacity.prestress_axial(inp)
    n_comp = -_number(inp.get("P_pl"), "P_pl") + n_prestress
    contexts = capacity.build_directional_shear_contexts(inp, n_prestress, n_comp)
    if tuple(contexts) != DIRECTIONS:
        raise TraceValidationError("authoritative directional context order differs")

    specs = capacity.shear_direction_specs(inp)
    if tuple(specs) != DIRECTIONS:
        raise TraceValidationError("authoritative direction specification order differs")
    directions = []
    for direction in DIRECTIONS:
        raw_faces = contexts[direction]["candidates"]
        face_order = tuple(bool(payload["tension_low"]) for payload, _ in raw_faces)
        spec = specs[direction]
        _compare(spec["signed_v_ed"], demands[direction]["signed"],
                 f"authoritative {direction} signed demand")
        _compare(spec["v_ed"], demands[direction]["magnitude"],
                 f"authoritative {direction} absolute demand")
        _compare(spec["axis"], demands[direction]["axis"],
                 f"authoritative {direction} axis")
        _compare(spec["face"], demands[direction]["face"],
                 f"authoritative {direction} face mode")
        common = _common_values(inp, blocks, demands, direction, links)
        faces = []
        failed = False
        warnings = []
        for index, (payload, link_ctx) in enumerate(raw_faces):
            result = payload.get("res") or {}
            concrete_valid = bool(
                result.get("valid") and result.get("vrd_c", 0.0) > 0.0
                and _finite_numbers(result, CONCRETE_RESULT_KEYS[:-1])
                and math.isfinite(float(payload.get("util", math.inf)))
            )
            linked = _links_replay(payload, link_ctx) if links and concrete_valid else None
            finite = concrete_valid and (not links or linked is not None)
            if not finite:
                failed = True
                continue
            if linked is not None:
                linked = dict(linked, dia=common["input-link-diameter"],
                              s=common["input-link-spacing"],
                              fywk=common["input-link-fywk"])
                if linked["out_of_limits"]:
                    warnings.append(f"{direction} face {index + 1} cotangent bounds are outside the method range")
            values, metric = _face_values(common, payload, linked, index)
            if not all(math.isfinite(value) for value in values.values()):
                failed = True
                continue
            faces.append(FaceEvidence(
                bool(payload["tension_low"]), payload, linked, metric,
                "PASS" if metric <= 1.0 + _TOL else "FAIL", values,
            ))
        if failed or len(faces) != len(raw_faces):
            faces = []
        shape = _shape(blocks, direction, demands, face_order, links, bool(failed),
                       variant, "" if link_steel is None else link_steel.material_id,
                       None if link_steel is None else link_steel.provenance.source,
                       context)
        values = dict(common)
        governing = None
        status = None
        if failed:
            values["authoritative-failure-state"] = 1.0
        else:
            governing = max(faces, key=lambda item: capacity.assessment_key(item.status, item.metric))
            status = capacity.aggregate_assessment_status(item.status for item in faces)
            for face in faces:
                values.update(face.values)
            values["direction-governing-face"] = 1.0 if governing.tension_low else 0.0
            values["direction-utilisation"] = governing.metric
            values["direction-verdict"] = 1.0 if status == "PASS" else 0.0
            values["ct-006-direction-result"] = values["direction-verdict"]
        directions.append(DirectionEvidence(
            shape, tuple(faces), values, governing, status, tuple(warnings),
            float(spec["signed_v_ed"]), float(spec["moment"]),
            float(spec["moment_origin"]),
        ))

    _validate_candidate(shear_out, tuple(directions))
    return tuple(directions)


def _validate_result(candidate, expected, label):
    candidate = _retained_mapping(candidate, CONCRETE_RESULT_KEYS, (), label)
    _compare({key: candidate[key] for key in CONCRETE_RESULT_KEYS},
             {key: expected[key] for key in CONCRETE_RESULT_KEYS}, label)


def _validate_links(candidate, expected, label):
    candidate = _retained_mapping(candidate, LINK_KEYS, LINK_EXCLUDED, label)
    _compare(candidate["util"], expected["util"], f"{label}.util")
    for key in ("asw", "asw_over_s", "legs", "dia", "s", "fywk", "cot_min",
                "cot_max", "cot_limit_lo", "cot_limit_hi", "model_2023",
                "z_source", "out_of_limits", "required", "theta_mode"):
        _compare(candidate[key], expected[key], f"{label}.{key}")
    angle = _retained_mapping(candidate["angle_limits"], ANGLE_LIMIT_KEYS, (),
                              f"{label}.angle_limits")
    _compare({key: angle[key] for key in ANGLE_LIMIT_KEYS},
             {key: expected["angle_limits"][key] for key in ANGLE_LIMIT_KEYS},
             f"{label}.angle_limits")
    result = _retained_mapping(candidate["res"], LINK_RESULT_KEYS, (), f"{label}.res")
    _compare({key: result[key] for key in LINK_RESULT_KEYS},
             {key: expected["res"][key] for key in LINK_RESULT_KEYS}, f"{label}.res")


def _validate_shear(candidate, face, label, *, direction=False, selected_face=False):
    expected_keys = (*SHEAR_KEYS, *(("links",) if face.links is not None else ()),
                     *(DIRECTION_SUFFIX_KEYS if direction else ()))
    candidate = _retained_mapping(candidate, expected_keys, SHEAR_EXCLUDED, label)
    payload = face.payload
    _validate_result(candidate["res"], payload["res"], f"{label}.res")
    for key in SHEAR_KEYS[1:]:
        expected = "selected" if selected_face and key == "face_mode" else payload[key]
        _compare(candidate[key], expected, f"{label}.{key}")
    if face.links is not None:
        _validate_links(candidate["links"], face.links, f"{label}.links")
    return candidate


def _validate_candidate(shear_out, directions):
    aggregate = _retained_mapping(shear_out, AGGREGATE_KEYS, AGGREGATE_EXCLUDED,
                                  "candidate shear aggregate")
    mapping = _mapping(aggregate["directions"], "candidate directions")
    if tuple(mapping) != DIRECTIONS:
        raise TraceValidationError("candidate directions must be exactly vx then vy")
    active = aggregate["active_directions"]
    if type(active) is not list or tuple(active) != DIRECTIONS:
        raise TraceValidationError("candidate active_directions must be exactly vx then vy")
    for evidence in directions:
        if evidence.shape.failed:
            continue
        direction = evidence.shape.direction
        governing = evidence.governing
        candidate = _validate_shear(mapping[direction], governing,
                                    f"candidate {direction}", direction=True)
        _compare(candidate["both_faces_evaluated"], len(evidence.faces) == 2,
                 f"candidate {direction}.both_faces_evaluated")
        _compare(candidate["governing_face"],
                 "negative" if governing.tension_low else "positive",
                 f"candidate {direction}.governing_face")
        _compare(candidate["associated_moment"], evidence.associated_moment,
                 f"candidate {direction}.associated_moment")
        _compare(candidate["associated_moment_origin"], evidence.associated_moment_origin,
                 f"candidate {direction}.associated_moment_origin")
        _compare(candidate["signed_v_ed"], evidence.signed_v_ed,
                 f"candidate {direction}.signed_v_ed")
        if candidate["status"] != evidence.status:
            raise TraceValidationError(f"candidate {direction}.status differs")
        domains = _retained_mapping(candidate["governing_domains"], ("shear",),
                                    GOVERNING_DOMAIN_EXCLUDED,
                                    f"candidate {direction}.governing_domains")
        shear_domain = _retained_mapping(domains["shear"], GOVERNING_SHEAR_KEYS, (),
                                         f"candidate {direction}.governing_domains.shear")
        expected_domain = {
            "face": "negative" if governing.tension_low else "positive",
            "cot": None if governing.links is None else governing.links["res"]["cot"],
            "status": evidence.status,
            "util": governing.metric,
        }
        _compare({key: shear_domain[key] for key in GOVERNING_SHEAR_KEYS},
                 expected_domain, f"candidate {direction}.governing_domains.shear")
        wrappers = _sequence(candidate["face_candidates"],
                             f"candidate {direction}.face_candidates")
        if len(wrappers) != len(evidence.faces):
            raise TraceValidationError(f"candidate {direction} face cardinality differs")
        for index, (wrapper, face) in enumerate(zip(wrappers, evidence.faces)):
            label = f"candidate {direction}.face_candidates[{index}]"
            wrapper = _retained_mapping(wrapper, FACE_WRAPPER_KEYS,
                                        FACE_WRAPPER_EXCLUDED, label)
            _compare(wrapper["tension_low"], face.tension_low, f"{label}.tension_low")
            _compare(wrapper["shear_status"], face.status, f"{label}.shear_status")
            _compare(wrapper["shear_metric"], face.metric, f"{label}.shear_metric")
            _validate_shear(wrapper["shear"], face, f"{label}.shear",
                            selected_face=True)


def _actual_expression(step_id: str, title: str) -> str:
    expressions = {
        "k": "k = min(1 + sqrt(200/d), 2)",
        "rho-l": "rho_l = min(Asl/(bw*d), 0.02)",
        "sigma-cp": "sigma_cp = min(NEd/Ac, 0.2*fcd)",
        "vmin": "v_min = selected base or DK national value",
        "v-basic": "v_basic = C_Rd,c*k*(100*rho_l*fck)^(1/3) + k1*sigma_cp",
        "v-floor": "v_floor = v_min + k1*sigma_cp",
        "vrd-c": "VRd,c = max(v_basic,v_floor,0)*bw*d",
        "asw": "Asw = legs*pi*diameter^2/4",
        "asw-over-s": "Asw/s = Asw/spacing",
        "fywd": "fywd = fywk/gamma_s",
        "vrd-s": "VRd,s = (Asw/s)*z*fywd*cot(theta)",
        "vrd-max": "VRd,max = alpha_cw*bw*z*nu1*fcd/(cot+1/cot)",
        "vrd-links": "VRd = min(VRd,s,VRd,max)",
        "cot": "argmin_1501 max(VEd/VRd,s,VEd/VRd,max)",
    }
    for suffix, expression in expressions.items():
        if step_id.endswith(f"-{suffix}"):
            return expression
    if step_id.endswith("utilisation"):
        return "utilisation = demand/resistance"
    if step_id.endswith("verdict") or step_id == "ct-006-direction-result":
        return "PASS = 1 when utilisation <= 1 + 1e-9, otherwise FAIL = 0"
    return f"Bind {title.lower()}"


def _calculation(evidence: DirectionEvidence) -> TraceCalculation:
    specs = expected_step_contract(evidence.shape)
    units = {item.step_id: item.unit for item in specs}
    steps = []
    for spec in specs:
        failed_final = evidence.shape.failed and spec.step_id == "ct-006-direction-result"
        result = (TraceResult(RESULT_FAILED, None, _FAILURE_REASON) if failed_final
                  else TraceResult(RESULT_FINITE, float(evidence.values[spec.step_id])))
        substituted = (f"{spec.step_id} = {result.state}" if failed_final else
                       f"{spec.step_id} = {float(result.value):.17g} {spec.unit.symbol}")
        steps.append(TraceStep(
            spec.step_id, spec.title,
            tuple(TraceDependency(name, units[name]) for name in spec.dependencies),
            spec.quantity_role, spec.source, spec.step_id, spec.unit,
            _actual_expression(spec.step_id, spec.title), substituted, result,
        ))
    return TraceCalculation(
        evidence.shape.calculation_id, COVERAGE_ID,
        f"Directional shear core {evidence.shape.direction}", METHOD_ID,
        evidence.shape.axes, "ct-006-direction-result", tuple(steps),
        evidence.warnings,
        ("Vx and Vy are independent resistance checks; no cross-direction interaction is inferred.",
         "Chord, off-axis utilisation, biaxial bending and plastic sweep state are outside CT-006."),
    )


def _expected_bundle(inp, shear_out, input_sha256, result_sha256, context):
    evidence = _replay(inp, shear_out, context)
    bundle = create_bundle(
        input_sha256=input_sha256,
        result_sha256=result_sha256,
        calculations=tuple(_calculation(item) for item in evidence),
    )
    audit_trace_registry(bundle, expected_registry(tuple(item.shape for item in evidence)))
    return bundle


def build_shear_trace_family(
    inp: Mapping[str, Any],
    shear_out: Mapping[str, Any],
    *,
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle | None:
    """Build and seal the applicable two-active CT-006 core family."""

    try:
        if shear_core_applicability(inp) != "directional":
            return None
        return _expected_bundle(
            inp, shear_out, input_sha256, result_sha256,
            {} if context is None else context,
        )
    except TraceValidationError:
        raise
    except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"invalid CT-006 core evidence: {exc}") from exc


def validate_shear_trace_family(
    bundle: TraceBundle | dict[str, Any] | None,
    inp: Mapping[str, Any],
    shear_out: Mapping[str, Any],
    *,
    input_sha256: str,
    result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle | None:
    """Reject coherently resealed value, graph, source, and verdict tampering."""

    if shear_core_applicability(inp) != "directional":
        if bundle is not None:
            raise TraceValidationError("not-applicable CT-006 input cannot carry a trace")
        return None
    candidate = validate_bundle(
        bundle,
        expected_input_sha256=input_sha256,
        expected_result_sha256=result_sha256,
    )
    expected = _expected_bundle(
        inp, shear_out, input_sha256, result_sha256,
        {} if context is None else context,
    )
    if candidate.to_dict() != expected.to_dict():
        raise TraceValidationError("CT-006 trace differs from authoritative input replay")
    return candidate
