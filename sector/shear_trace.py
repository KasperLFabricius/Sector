"""Solver-owned unpublished CT-006 directional shear and chord trace."""

from __future__ import annotations

import functools
import math
import numbers
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from . import capacity, codes, combined, shear
from .calculation_trace import (
    RESULT_FAILED, RESULT_FINITE, TraceBundle, TraceCalculation, TraceDependency,
    TraceResult, TraceStep, TraceValidationError,
    create_bundle, validate_bundle,
)
from .section_trace_blocks import (
    _materials as selected_material_blocks,
    context_axes, context_id, section_trace_blocks,
)
from .plastic_capacity_trace import (
    PlasticCapacityEvidence, replay_plastic_capacity_evidence,
)
from .plastic_capacity_trace_contract import (
    BRANCH_FINITE_SELECTED, SweepPlan, expected_sweep,
)
from .shear_trace_contract import (
    AGGREGATE_EXCLUDED, AGGREGATE_KEYS, ANGLE_LIMIT_KEYS, CHORD_OFF_KEYS,
    CHORD_SHEAR_KEYS, COMPONENT_KEYS, CONCRETE_RESULT_KEYS, CORE_INPUT_KEYS,
    COVERAGE_ID, DIRECTION_SUFFIX_KEYS,
    DIRECTIONS, FACE_WRAPPER_EXCLUDED, FACE_WRAPPER_KEYS, GOVERNING_DOMAIN_EXCLUDED,
    GOVERNING_SHEAR_KEYS, LINK_EXCLUDED, LINK_INPUT_KEYS, LINK_KEYS, LINK_RESULT_KEYS,
    METHOD_ID, PHYSICAL_AXES, PLASTIC_JOIN_INPUT_KEYS, SHEAR_EXCLUDED, SHEAR_KEYS,
    DirectionShape,
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
class PlasticJoin:
    plan: SweepPlan
    requested: bool
    present: bool
    available: bool
    evidence: PlasticCapacityEvidence | None


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


def _exact_bool(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise TraceValidationError(f"{label} must be exact Boolean")
    return value


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


def _retained_list(value: Any, label: str) -> list[Any]:
    if type(value) is not list:
        raise TraceValidationError(f"{label} must retain list type")
    return value


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


def _plastic_join(
    inp: Mapping[str, Any],
    plastic_out: Mapping[str, Any] | None,
    context: Mapping[str, Any],
    *,
    validate_evidence: bool = True,
) -> PlasticJoin:
    """Freeze the CT-002 sweep and its exact capacity-availability branch."""

    for key in ("v_min", "v_max", "v_inc", "mode", "check_util"):
        if key not in inp:
            raise TraceValidationError(
                f"CT-006 chord input inventory missing {key!r}"
            )
    plan = expected_sweep(inp["v_min"], inp["v_max"], inp["v_inc"])
    mode = inp["mode"]
    if type(mode) is not str or mode not in {"Plastic", "Elastic", "Both"}:
        raise TraceValidationError("mode must retain Plastic, Elastic, or Both")
    check_util = inp["check_util"]
    if type(check_util) is not bool:
        raise TraceValidationError("check_util must be exact Boolean")
    requested = mode in {"Plastic", "Both"}
    expected_available = bool(requested and plan.closed and check_util)
    if (plastic_out is not None) is not requested:
        raise TraceValidationError(
            "plastic output presence contradicts the selected analysis mode"
        )
    if plastic_out is None:
        return PlasticJoin(plan, requested, False, False, None)
    retained = _mapping(plastic_out, "plastic capacity join")
    if "util" not in retained:
        raise TraceValidationError(
            "plastic capacity join requires the retained util discriminator"
        )
    available = retained["util"] is not None
    if available != expected_available:
        raise TraceValidationError(
            "plastic capacity availability contradicts original sweep inputs"
        )
    if not available:
        if retained.get("closed") is not plan.closed:
            raise TraceValidationError(
                "unavailable plastic capacity closed state differs from sweep"
            )
        if retained.get("check_util") is not check_util:
            raise TraceValidationError(
                "unavailable plastic capacity check state differs from input"
            )
        return PlasticJoin(plan, requested, True, False, None)
    if not validate_evidence:
        return PlasticJoin(plan, requested, True, True, None)
    evidence = replay_plastic_capacity_evidence(
        inp, {"plastic": retained}, context=context,
    )
    if evidence.shape.branch != BRANCH_FINITE_SELECTED:
        raise TraceValidationError(
            "CT-006 chord join requires finite-selected CT-002 evidence"
        )
    extrema = {
        "max_mx": max(point.Mx for point in evidence.replay),
        "min_mx": min(point.Mx for point in evidence.replay),
        "max_my": max(point.My for point in evidence.replay),
        "min_my": min(point.My for point in evidence.replay),
    }
    for key, expected in extrema.items():
        _compare(retained.get(key), expected, f"plastic capacity join.{key}")
    return PlasticJoin(plan, requested, True, True, evidence)


def _require_input_inventory(inp: Mapping[str, Any], links: bool) -> None:
    required = (
        *CORE_INPUT_KEYS,
        *(LINK_INPUT_KEYS if links else ()),
        *(PLASTIC_JOIN_INPUT_KEYS if links else ()),
    )
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


def _common_values(inp, blocks, demands, direction, links, plastic):
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
    values.update({"aggregate-biaxial": 1.0, "aggregate-note-identity": 1.0})
    if plastic is not None:
        mode_codes = {"Elastic": 0.0, "Plastic": 1.0, "Both": 2.0}
        values.update({
            "input-analysis-mode-code": mode_codes[inp["mode"]],
            "input-check-util": float(inp["check_util"]),
            "input-sweep-min": plastic.plan.requested_min,
            "input-sweep-max": plastic.plan.requested_max,
            "input-sweep-increment": plastic.plan.requested_increment,
            "sweep-solver-min": plastic.plan.solver_min,
            "sweep-solver-max": plastic.plan.solver_max,
            "sweep-solver-increment": plastic.plan.solver_increment,
            "sweep-member-count": float(len(plastic.plan.angles)),
            "sweep-closed": float(plastic.plan.closed),
            "plastic-capacity-requested": float(plastic.requested),
            "plastic-output-present": float(plastic.present),
            "plastic-capacity-available": float(plastic.available),
            "input-shear-dlower": _number(
                inp["shear_dlower"], "shear_dlower", nonnegative=True,
            ),
            "input-torsion-enabled": float(
                _exact_bool(inp["torsion_on"], "torsion_on")
            ),
            "input-combined-enabled": float(
                _exact_bool(inp["combined_on"], "combined_on")
            ),
            "input-combined-mv-independent": float(
                _exact_bool(
                    inp["combined_mv_independent"], "combined_mv_independent",
                )
            ),
        })
        values.update(_torsion_input_values(inp))
    if plastic is not None and plastic.evidence is not None:
        extrema = _plastic_extrema(plastic)
        values.update({
            "plastic-max-mx": extrema["max_mx"],
            "plastic-min-mx": extrema["min_mx"],
            "plastic-max-my": extrema["max_my"],
            "plastic-min-my": extrema["min_my"],
        })
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


def _torsion_input_values(inp: Mapping[str, Any]) -> dict[str, float]:
    method = inp["torsion_method"]
    if type(method) is not str or method not in {
        codes.EC2_2005.label, codes.EC2_2005_DKNA.label,
    }:
        raise TraceValidationError(
            "torsion_method must retain an implemented 2004-family method"
        )
    values = {
        "input-torsion-method-code": (
            1.0 if method == codes.EC2_2005_DKNA.label else 0.0
        ),
        "input-torsion-tef": _number(
            inp["torsion_tef"], "torsion_tef", nonnegative=True,
        ),
        "input-torsion-nu-v": float(
            _exact_bool(inp["torsion_nu_v"], "torsion_nu_v")
        ),
        "input-torsion-gamma-ct": _number(
            inp["torsion_gamma_ct"], "torsion_gamma_ct", positive=True,
        ),
        "input-torsion-demand": _number(
            inp["torsion_T"], "torsion_T", nonnegative=True,
        ),
        "input-torsion-subdivide": float(
            _exact_bool(inp["torsion_subdivide"], "torsion_subdivide")
        ),
    }
    rectangles = _sequence(inp["torsion_subrects"], "torsion_subrects")
    for index, rectangle in enumerate(rectangles):
        rectangle = _sequence(rectangle, f"torsion_subrects[{index}]")
        if len(rectangle) != 4:
            raise TraceValidationError("torsion subrectangles need x, y, b, h")
        for suffix, value in zip(("x", "y", "b", "h"), rectangle):
            values[f"input-torsion-subrect-{index:03d}-{suffix}"] = _number(
                value, f"torsion_subrects[{index}].{suffix}",
                positive=suffix in {"b", "h"},
            )
    values["input-torsion-subrect-vector"] = 1.0
    return values


def _finite_numbers(value: Mapping[str, Any], names: Sequence[str]) -> bool:
    try:
        return all(type(value[name]) in {int, float} and not isinstance(value[name], bool)
                   and math.isfinite(float(value[name])) for name in names)
    except (KeyError, TypeError, ValueError):
        return False


def _direction_input(inp, tension_low, payload, ctx):
    translated = dict(inp)
    translated.update(
        shear_axis=payload["axis"],
        shear_tension=bool(tension_low),
        shear_V=payload["v_ed"],
        shear_bw=payload["bw_user"],
        shear_link_legs=ctx["link_legs"],
    )
    return translated


def _plastic_extrema(join: PlasticJoin) -> dict[str, float]:
    if join.evidence is None:
        raise TraceValidationError("plastic extrema require available CT-002 evidence")
    replay = join.evidence.replay
    return {
        "max_mx": max(point.Mx for point in replay),
        "min_mx": min(point.Mx for point in replay),
        "max_my": max(point.My for point in replay),
        "min_my": min(point.My for point in replay),
    }


def _links_replay(
    inp: Mapping[str, Any],
    payload: Mapping[str, Any],
    ctx: Mapping[str, Any] | None,
    plastic: PlasticJoin,
) -> Mapping[str, Any] | None:
    if ctx is None:
        return None
    probe = ctx["build"](ctx["cot_min"], ctx["cot_min"])
    if not (probe.get("valid") and probe.get("vrd_s", 0.0) > 0.0
            and probe.get("vrd_max", 0.0) > 0.0):
        return None
    v_ed = float(payload["v_ed"])
    translated = _direction_input(
        inp, payload["tension_low"], payload, ctx,
    )
    n_comp = float(payload["n_ed_comp"])
    torsion = capacity.build_torsion_context(translated, n_comp)
    torsion_valid = bool(
        torsion is not None
        and all(tube["valid"] for tube in torsion["subtubes"])
    )
    shear_live = v_ed > 0.0
    torsion_live = bool(
        torsion_valid and float(torsion["t_ed"]) > 0.0
    )

    chord_faces = []
    off_faces = []
    extrema = _plastic_extrema(plastic) if plastic.available else None
    if extrema is not None:
        axis = payload["axis"]
        tension_low = bool(payload["tension_low"])
        m_signed = translated["Mx_pl"] if axis == "x" else translated["My_pl"]
        off_signed = translated["My_pl"] if axis == "x" else translated["Mx_pl"]
        off_max = extrema["max_my"] if axis == "x" else extrema["max_mx"]
        off_min = extrema["min_my"] if axis == "x" else extrema["min_mx"]
        off_cap = off_max if off_signed >= 0.0 else abs(off_min)
        off_util = (
            abs(off_signed) / off_cap
            if off_cap > 0.0 else (math.inf if off_signed else 0.0)
        )
        _, centroid_x, centroid_y = capacity.gross_area_centroid(
            translated["outer"], translated["holes"]
        )
        centroid = centroid_y if axis == "x" else centroid_x
        shear_faces = [(tension_low, True)]
        if torsion_live:
            shear_faces.append((not tension_low, False))
        for face_low, gets_shift in shear_faces:
            m_ed = combined.chord_applied_moment(m_signed, face_low)
            m_rd, conditional = capacity.shear_face_mrd(
                translated, axis, face_low, m_off=off_signed,
            )
            if gets_shift:
                if not conditional and m_rd <= 0.0:
                    maximum = extrema["max_mx"] if axis == "x" else extrema["max_my"]
                    minimum = extrema["min_mx"] if axis == "x" else extrema["min_my"]
                    m_rd = maximum if face_low else abs(minimum)
                if not (m_rd > 0.0 or conditional):
                    continue
                z_mm, z_source = ctx["z_mm"], ctx["z_src"]
            else:
                if not conditional:
                    continue
                _, steel_centroid = shear.tension_reinforcement(
                    translated["bars"], axis, face_low, centroid,
                )
                depth = shear.effective_depth(
                    translated["outer"], axis, face_low, steel_centroid,
                )
                z_mm, z_source = capacity.shear_lever_arm(
                    translated, axis, face_low, depth,
                )
                if z_mm <= 0.0:
                    continue
            chord_faces.append({
                "m_ed": m_ed,
                "m_rd": m_rd,
                "z_m": z_mm / 1000.0,
                "z_src": z_source,
                "axis": axis,
                "tension_low": face_low,
                "off_util": off_util,
                "m_off": off_signed,
                "conditional": conditional,
                "gets_shift": gets_shift,
            })
        if chord_faces and torsion_live and not torsion["subdivide"]:
            off_axis = "y" if axis == "x" else "x"
            off_centroid = centroid_y if off_axis == "x" else centroid_x
            for face_low in (True, False):
                m_ed = combined.chord_applied_moment(off_signed, face_low)
                m_rd, conditional = capacity.shear_face_mrd(
                    translated, off_axis, face_low, m_off=m_signed,
                )
                if not conditional:
                    continue
                _, steel_centroid = shear.tension_reinforcement(
                    translated["bars"], off_axis, face_low, off_centroid,
                )
                depth = shear.effective_depth(
                    translated["outer"], off_axis, face_low, steel_centroid,
                )
                z_mm, z_source = capacity.shear_lever_arm(
                    translated, off_axis, face_low, depth,
                )
                if z_mm <= 0.0:
                    continue
                off_faces.append({
                    "m_ed": m_ed,
                    "m_rd": m_rd,
                    "z_m": z_mm / 1000.0,
                    "z_src": z_source,
                    "axis": off_axis,
                    "tension_low": face_low,
                    "m_off": m_signed,
                    "conditional": True,
                })

    @functools.lru_cache(maxsize=4096)
    def snapshot(cot):
        result = {"links": ctx["build"](cot, cot)}
        if torsion is not None:
            kwargs = dict(torsion["_tk"], cot_min=cot, cot_max=cot)
            result["torsion"] = tuple(
                capacity.tube_torsion(tube, demand, **kwargs)
                for tube, demand in zip(
                    torsion["subtubes"], torsion["ted_parts"]
                )
            )
        return result

    def torsion_force(cot):
        if not torsion_live:
            return 0.0
        web = snapshot(cot)["torsion"][0]
        return web["asl_req"] * torsion["fyd_long"] / 1000.0

    def shear_force(cot):
        return 0.5 * v_ed * cot

    utilities = []
    if shear_live:
        utilities.extend((
            lambda cot: combined.ratio(
                v_ed, snapshot(cot)["links"]["vrd_s"]),
            lambda cot: combined.ratio(
                v_ed, snapshot(cot)["links"]["vrd_max"]),
        ))
    if torsion_live:
        for position in range(len(torsion["subtubes"])):
            utilities.append(
                lambda cot, position=position:
                snapshot(cot)["torsion"][position]["util"]
            )
    if (
        torsion_live
        and torsion["asw_over_s_t"] > 0.0
    ):
        utilities.append(lambda cot: (
            (0.0 if v_ed <= ctx["vrd_c"] else combined.ratio(
                v_ed, snapshot(cot)["links"]["vrd_s"]))
            + combined.ratio(
                snapshot(cot)["torsion"][0]["t_ed"],
                snapshot(cot)["torsion"][0]["trd_s"],
            )
        ))
        utilities.append(lambda cot: combined.crushing_interaction(
            snapshot(cot)["torsion"][0]["t_ed"],
            snapshot(cot)["torsion"][0]["trd_max"],
            v_ed,
            snapshot(cot)["links"]["vrd_max"],
        ))
    for face in chord_faces:
        if face["m_rd"] > 0.0 and (shear_live or torsion_live):
            utilities.append(lambda cot, face=face: combined.longitudinal_check(
                face["m_ed"], face["m_rd"],
                shear_force(cot) if face["gets_shift"] else 0.0,
                torsion_force(cot), face["z_m"],
                cap_shear_force=True,
            )["util"])
    for face in off_faces:
        if face["m_rd"] > 0.0 and torsion_live:
            utilities.append(lambda cot, face=face: combined.longitudinal_check(
                face["m_ed"], face["m_rd"], 0.0,
                torsion_force(cot), face["z_m"],
            )["util"])
    if (
        inp.get("combined_on")
        and plastic.evidence is not None
        and math.isfinite(plastic.evidence.radial.utilisation)
        and torsion_valid
        and (shear_live or torsion_live)
    ):
        independent = inp.get("combined_mv_independent")
        if type(independent) is not bool:
            raise TraceValidationError(
                "combined_mv_independent must be exact Boolean"
            )
        utilities.append(lambda cot: combined.dkna_sum(
            plastic.evidence.radial.utilisation,
            combined.ratio(v_ed, snapshot(cot)["links"]["vrd"]),
            max(item["util"] for item in snapshot(cot)["torsion"]),
            m_v_independent=independent,
        ))
    band = (ctx["cot_min"], ctx["cot_max"]) if shear_live else None
    cot = None
    if band is not None and utilities:
        cot, _ = combined.governing_strut_cot(
            utilities, band[0], band[1], n=1501,
        )
    result = (
        ctx["build"](cot, cot)
        if cot is not None
        else ctx["build"](ctx["cot_min"], ctx["cot_max"])
    )
    if not result.get("valid") or not _finite_numbers(result, (
        "vrd_s", "vrd_max", "vrd", "cot", "theta_deg", "z", "fywd", "nu1",
        "alpha_cw", "sigma_cp", "fcd", "gamma_s", "asw_over_s",
    )) or result["vrd"] <= 0.0:
        return None
    theta_mode = "utilisation" if cot is not None else "resistance"
    longitudinal_force = 0.5 * v_ed * result["cot"]
    torsion_at_result = (
        snapshot(result["cot"])["torsion"] if torsion_live else ()
    )
    torsion_longitudinal = (
        torsion_at_result[0]["asl_req"] * torsion["fyd_long"] / 1000.0
        if torsion_at_result else 0.0
    )
    off_not_evaluated = None
    if chord_faces:
        if torsion_live and torsion["subdivide"]:
            off_not_evaluated = "subdivided"
        elif torsion_live and len(chord_faces) + len(off_faces) < 4:
            off_not_evaluated = "not_solved"
    chord_candidates = []
    for face in chord_faces:
        check = combined.longitudinal_check(
            face["m_ed"], face["m_rd"],
            longitudinal_force if face["gets_shift"] else 0.0,
            torsion_longitudinal, face["z_m"], cap_shear_force=True,
        )
        check.update(
            valid=True,
            role="shear_axis",
            axis=face["axis"],
            tension_low=face["tension_low"],
            off_util=face["off_util"],
            biaxial=bool(face["off_util"] > 0.05),
            m_off=face["m_off"],
            conditional=face["conditional"],
            has_torsion=torsion_live,
            gets_shift=face["gets_shift"],
            off_not_evaluated=off_not_evaluated,
            theta_mode=theta_mode,
        )
        chord_candidates.append(check)
    for face in off_faces:
        check = combined.longitudinal_check(
            face["m_ed"], face["m_rd"], 0.0,
            torsion_longitudinal, face["z_m"],
        )
        check.update(
            valid=True,
            role="off_axis",
            axis=face["axis"],
            tension_low=face["tension_low"],
            m_off=face["m_off"],
            conditional=face["conditional"],
            z_src=face["z_src"],
            theta_mode=theta_mode,
        )
        chord_candidates.append(check)
    shear_candidates = [
        item for item in chord_candidates if item["role"] == "shear_axis"
    ]
    off_candidates = [
        item for item in chord_candidates if item["role"] == "off_axis"
    ]
    chord = max(shear_candidates, key=lambda item: item["util"], default=None)
    chord_off = max(off_candidates, key=lambda item: item["util"], default=None)
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
        "delta_ftd": longitudinal_force,
        "longitudinal_shear_force": longitudinal_force,
        "longitudinal_shear_symbol": "delta_Ftd",
        "longitudinal_shear_clause": "6.2.3(7), Formula (6.18)",
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
        "chord": chord,
        "chord_off": chord_off,
        "chord_candidates": chord_candidates,
        "theta_mode": theta_mode,
    }


def _identity_code(value: str, options: tuple[str, ...], label: str) -> float:
    if type(value) is not str or value not in options:
        raise TraceValidationError(f"{label} has unsupported retained identity")
    return float(options.index(value))


def _chord_values(prefix: str, item: Mapping[str, Any]) -> dict[str, float]:
    values = {
        f"{prefix}-m-ed": _number(item["m_ed"], f"{prefix}.m_ed"),
        f"{prefix}-m-rd": _number(item["m_rd"], f"{prefix}.m_rd", nonnegative=True),
        f"{prefix}-ftd-v": _number(item["ftd_v"], f"{prefix}.ftd_v", nonnegative=True),
        f"{prefix}-ftd-t": _number(item["ftd_t"], f"{prefix}.ftd_t", nonnegative=True),
        f"{prefix}-z": _number(item["z"], f"{prefix}.z", positive=True),
        f"{prefix}-mv": _number(item["mv"], f"{prefix}.mv", nonnegative=True),
        f"{prefix}-mt": _number(item["mt"], f"{prefix}.mt", nonnegative=True),
        f"{prefix}-m-total": _number(item["m_total"], f"{prefix}.m_total", nonnegative=True),
        f"{prefix}-utilisation": _number(item["util"], f"{prefix}.util", nonnegative=True),
        f"{prefix}-verdict": float(_exact_bool(item["ok"], f"{prefix}.ok")),
        f"{prefix}-capped": float(_exact_bool(item["capped"], f"{prefix}.capped")),
        f"{prefix}-cap-shear-force": float(_exact_bool(
            item["cap_shear_force"], f"{prefix}.cap_shear_force",
        )),
        f"{prefix}-valid": float(_exact_bool(item["valid"], f"{prefix}.valid")),
        f"{prefix}-role": _identity_code(
            item["role"], ("shear_axis", "off_axis"), f"{prefix}.role",
        ),
        f"{prefix}-axis": _identity_code(
            item["axis"], ("x", "y"), f"{prefix}.axis",
        ),
        f"{prefix}-tension-low": float(_exact_bool(
            item["tension_low"], f"{prefix}.tension_low",
        )),
        f"{prefix}-theta-mode": _identity_code(
            item["theta_mode"], ("resistance", "utilisation"),
            f"{prefix}.theta_mode",
        ),
    }
    if item["role"] == "shear_axis":
        reason_codes = {None: 0.0, "subdivided": 1.0, "not_solved": 2.0}
        reason = item["off_not_evaluated"]
        if reason not in reason_codes:
            raise TraceValidationError(f"{prefix}.off_not_evaluated differs")
        values.update({
            f"{prefix}-off-utilisation": _number(
                item["off_util"], f"{prefix}.off_util", nonnegative=True,
            ),
            f"{prefix}-biaxial": float(_exact_bool(item["biaxial"], f"{prefix}.biaxial")),
            f"{prefix}-m-off": _number(item["m_off"], f"{prefix}.m_off"),
            f"{prefix}-conditional": float(_exact_bool(
                item["conditional"], f"{prefix}.conditional",
            )),
            f"{prefix}-has-torsion": float(_exact_bool(
                item["has_torsion"], f"{prefix}.has_torsion",
            )),
            f"{prefix}-gets-shift": float(_exact_bool(
                item["gets_shift"], f"{prefix}.gets_shift",
            )),
            f"{prefix}-off-not-evaluated": reason_codes[reason],
        })
    else:
        values.update({
            f"{prefix}-m-off": _number(item["m_off"], f"{prefix}.m_off"),
            f"{prefix}-conditional": float(_exact_bool(
                item["conditional"], f"{prefix}.conditional",
            )),
            f"{prefix}-z-source": _identity_code(
                item["z_src"],
                ("0.9 d (fallback)", "plastic internal lever arm"),
                f"{prefix}.z_src",
            ),
        })
    values[f"{prefix}-evidence"] = 1.0
    return values


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
            f"{p}-longitudinal-shear-force": links["longitudinal_shear_force"],
            f"{p}-longitudinal-shear-identity": 1.0,
        })
        for chord_index, chord in enumerate(links["chord_candidates"]):
            values.update(_chord_values(
                f"{p}-chord-{chord_index:02d}", chord,
            ))
        shear_indices = [
            position for position, item in enumerate(links["chord_candidates"])
            if item["role"] == "shear_axis"
        ]
        off_indices = [
            position for position, item in enumerate(links["chord_candidates"])
            if item["role"] == "off_axis"
        ]
        values[f"{p}-chord-selected-index"] = (
            -1.0 if links["chord"] is None else float(max(
                shear_indices,
                key=lambda position: links["chord_candidates"][position]["util"],
            ))
        )
        values[f"{p}-chord-off-selected-index"] = (
            -1.0 if links["chord_off"] is None else float(max(
                off_indices,
                key=lambda position: links["chord_candidates"][position]["util"],
            ))
        )
        values[f"{p}-links-evidence"] = 1.0
        overall = links["util"]
    values[f"{p}-complete-evidence"] = 1.0
    return values, overall


def _shape(
    blocks, direction, demands, faces, links, failed, variant,
    link_steel_material_id, link_steel_source, plastic, chord_roles,
    torsion_subrect_count, context,
):
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
        axis_values.update(
            plastic_capacity=("available" if plastic.available else "unavailable"),
            plastic_requested=str(plastic.requested).lower(),
        )
    axes = context_axes(context, **axis_values)
    return DirectionShape(
        blocks, direction, demands[direction]["face"], faces, links, failed,
        variant, link_steel_material_id, link_steel_source,
        False if plastic is None else plastic.requested,
        False if plastic is None else plastic.available,
        chord_roles,
        torsion_subrect_count,
        f"ct-006-{context_id(context)}-{direction}", axes,
    )


def _replay(inp, shear_out, context, plastic_out=None):
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
    plastic_identity = (
        _plastic_join(
            inp, plastic_out, context, validate_evidence=False,
        )
        if links else None
    )
    plastic_evidence = None
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
        base_validity = []
        for payload, link_ctx in raw_faces:
            result = payload.get("res") or {}
            concrete_valid = bool(
                result.get("valid") and result.get("vrd_c", 0.0) > 0.0
                and _finite_numbers(result, CONCRETE_RESULT_KEYS[:-1])
                and math.isfinite(float(payload.get("util", math.inf)))
            )
            link_valid = True
            if links:
                if link_ctx is None:
                    link_valid = False
                else:
                    probe = link_ctx["build"](
                        link_ctx["cot_min"], link_ctx["cot_min"],
                    )
                    link_valid = bool(
                        probe.get("valid")
                        and probe.get("vrd_s", 0.0) > 0.0
                        and probe.get("vrd_max", 0.0) > 0.0
                    )
            base_validity.append(concrete_valid and link_valid)
        base_failed = not all(base_validity)
        plastic = plastic_identity
        if links and not base_failed and plastic_identity.available:
            if plastic_evidence is None:
                plastic_evidence = _plastic_join(inp, plastic_out, context)
            plastic = plastic_evidence
        common = _common_values(inp, blocks, demands, direction, links, plastic)
        faces = []
        failed = base_failed
        warnings = []
        for index, (payload, link_ctx) in enumerate(raw_faces):
            if base_failed:
                continue
            result = payload.get("res") or {}
            concrete_valid = bool(
                result.get("valid") and result.get("vrd_c", 0.0) > 0.0
                and _finite_numbers(result, CONCRETE_RESULT_KEYS[:-1])
                and math.isfinite(float(payload.get("util", math.inf)))
            )
            linked = (
                _links_replay(inp, payload, link_ctx, plastic)
                if links and concrete_valid else None
            )
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
        chord_roles = (
            tuple(tuple(item["role"] for item in face.links["chord_candidates"])
                  for face in faces)
            if not failed and links else ()
        )
        shape = _shape(
            blocks, direction, demands, face_order, links, bool(failed), variant,
            "" if link_steel is None else link_steel.material_id,
            None if link_steel is None else link_steel.provenance.source,
            plastic, chord_roles,
            len(inp["torsion_subrects"]) if links else 0, context,
        )
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


def _validate_chord(candidate, expected, label):
    if expected is None:
        if candidate is not None:
            raise TraceValidationError(f"{label} must be absent for this branch")
        return
    expected = _mapping(expected, f"{label} authoritative replay")
    role = expected.get("role")
    keys = CHORD_SHEAR_KEYS if role == "shear_axis" else CHORD_OFF_KEYS
    candidate = _retained_mapping(candidate, keys, (), label)
    _compare({key: candidate[key] for key in keys},
             {key: expected[key] for key in keys}, label)


def _validate_links(candidate, expected, label):
    candidate = _retained_mapping(candidate, LINK_KEYS, LINK_EXCLUDED, label)
    _compare(candidate["util"], expected["util"], f"{label}.util")
    for key in ("asw", "asw_over_s", "legs", "dia", "s", "fywk", "cot_min",
                "cot_max", "delta_ftd", "longitudinal_shear_force",
                "longitudinal_shear_symbol", "longitudinal_shear_clause",
                "cot_limit_lo", "cot_limit_hi", "model_2023", "z_source",
                "out_of_limits", "required", "theta_mode"):
        _compare(candidate[key], expected[key], f"{label}.{key}")
    angle = _retained_mapping(candidate["angle_limits"], ANGLE_LIMIT_KEYS, (),
                              f"{label}.angle_limits")
    _compare({key: angle[key] for key in ANGLE_LIMIT_KEYS},
             {key: expected["angle_limits"][key] for key in ANGLE_LIMIT_KEYS},
             f"{label}.angle_limits")
    result = _retained_mapping(candidate["res"], LINK_RESULT_KEYS, (), f"{label}.res")
    _compare({key: result[key] for key in LINK_RESULT_KEYS},
             {key: expected["res"][key] for key in LINK_RESULT_KEYS}, f"{label}.res")
    candidates = _retained_list(
        candidate["chord_candidates"], f"{label}.chord_candidates",
    )
    expected_candidates = _sequence(expected["chord_candidates"],
                                    f"{label} authoritative chord candidates")
    if len(candidates) != len(expected_candidates):
        raise TraceValidationError(f"{label} chord candidate cardinality differs")
    for index, (item, wanted) in enumerate(zip(candidates, expected_candidates)):
        _validate_chord(item, wanted, f"{label}.chord_candidates[{index}]")
    _validate_chord(candidate["chord"], expected["chord"], f"{label}.chord")
    _validate_chord(candidate["chord_off"], expected["chord_off"],
                    f"{label}.chord_off")


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
    _compare(aggregate["biaxial"], True, "candidate shear aggregate.biaxial")
    _compare(
        aggregate["note"],
        "Vx and Vy are calculated independently. Generic cross-direction "
        "interaction is not calculated.",
        "candidate shear aggregate.note",
    )
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
        wrappers = _retained_list(
            candidate["face_candidates"],
            f"candidate {direction}.face_candidates",
        )
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
         "Chord candidates reuse the accepted CT-002 sweep and retained low-level mechanics.",
         "Torsion affects the shared selector and chord force only; CT-007 remains separate."),
    )


def _expected_bundle(
    inp, shear_out, input_sha256, result_sha256, context, plastic_out=None,
):
    evidence = _replay(inp, shear_out, context, plastic_out)
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
    plastic_out: Mapping[str, Any] | None = None,
) -> TraceBundle | None:
    """Build and seal the applicable two-active CT-006 core family."""

    try:
        if shear_core_applicability(inp) != "directional":
            return None
        return _expected_bundle(
            inp, shear_out, input_sha256, result_sha256,
            {} if context is None else context, plastic_out,
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
    plastic_out: Mapping[str, Any] | None = None,
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
        {} if context is None else context, plastic_out,
    )
    if candidate.to_dict() != expected.to_dict():
        raise TraceValidationError("CT-006 trace differs from authoritative input replay")
    return candidate
