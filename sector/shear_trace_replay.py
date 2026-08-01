"""Original-input replay and candidate closure for unpublished CT-006."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from . import capacity, codes, combined
from .calculation_trace import RESULT_FAILED, TraceResult, TraceValidationError
from .plastic import solve_plastic
from .section_trace_blocks import SectionTraceBlocks, section_trace_blocks
from .shear_trace_contract import (
    BRANCH_FAILED, BRANCH_FINITE, DirectionShape, expected_step_contract,
    material_step_id, trace_shape,
)


_FAILURE_REASON = "Authoritative CT-006 shear reconstruction is not finite and complete."
_TOL = 1.0e-9


@dataclass(frozen=True, slots=True)
class DirectionEvidence:
    shape: DirectionShape
    values: dict[str, float]
    states: dict[str, TraceResult]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReplayEvidence:
    blocks: SectionTraceBlocks
    directions: tuple[DirectionEvidence, ...]


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TraceValidationError(f"{label} must be a mapping")
    return value


def _number(value: Any, label: str) -> float:
    if type(value) not in {int, float} or type(value) is bool:
        raise TraceValidationError(f"{label} must be a finite non-Boolean number")
    result = float(value)
    if not math.isfinite(result):
        raise TraceValidationError(f"{label} must be finite")
    return result


def _finite_tree(value: Any) -> bool:
    if type(value) in {int, float} and type(value) is not bool:
        return math.isfinite(float(value))
    if isinstance(value, Mapping):
        return all(_finite_tree(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return all(_finite_tree(item) for item in value)
    return True


def _compare(candidate: Any, expected: Any, label: str) -> None:
    """Compare every required retained field while permitting unrelated extras."""

    if isinstance(expected, Mapping):
        candidate = _mapping(candidate, label)
        missing = [key for key in expected if key not in candidate]
        if missing:
            raise TraceValidationError(f"{label} is missing {', '.join(missing)}")
        for key, value in expected.items():
            _compare(candidate[key], value, f"{label}.{key}")
        return
    if isinstance(expected, (list, tuple)):
        if not isinstance(candidate, type(expected)) or len(candidate) != len(expected):
            raise TraceValidationError(f"{label} has wrong order or cardinality")
        for index, value in enumerate(expected):
            _compare(candidate[index], value, f"{label}[{index}]")
        return
    if type(expected) is bool or expected is None or isinstance(expected, str):
        if candidate != expected or type(candidate) is not type(expected):
            raise TraceValidationError(f"{label} differs from authoritative replay")
        return
    expected_number = _number(expected, f"expected {label}")
    candidate_number = _number(candidate, label)
    if not math.isclose(candidate_number, expected_number, rel_tol=2.0e-9, abs_tol=2.0e-9):
        raise TraceValidationError(f"{label} differs from authoritative replay")


def _candidate_directions(out: Mapping[str, Any], active: tuple[str, ...]) -> tuple[Mapping[str, Any], ...]:
    shear = _mapping(out.get("shear"), "CT-006 candidate shear result")
    if len(active) == 1:
        if "directions" in shear or shear.get("component") != active[0]:
            raise TraceValidationError("single CT-006 direction identity is wrong")
        return (shear,)
    directions = _mapping(shear.get("directions"), "CT-006 candidate directions")
    if tuple(directions) != active:
        raise TraceValidationError("candidate direction order/cardinality must be exactly vx, vy")
    return tuple(_mapping(directions[item], f"candidate {item}") for item in active)


def _plastic_extrema(inp: Mapping[str, Any]) -> dict[str, float] | None:
    """Canonical CT-006 chord extrema, independent of CT-002 sweep inputs/results."""

    if inp.get("mode", "Plastic") not in {"Plastic", "Both"} or not inp.get("check_util", True):
        return None
    section = inp["section"]
    prestress = inp.get("prestress") if section.tendons else None
    points = solve_plastic(
        section, inp["concrete"], inp["steel"], -_number(inp["P_pl"], "P_pl"),
        0.0, 345.0, 15.0, prestress=prestress,
        bar_materials=inp.get("bar_materials"),
        tendon_materials=inp.get("tendon_materials"),
    )
    if not points or not all(point.converged for point in points):
        return None
    mx = [float(point.Mx) for point in points]
    my = [float(point.My) for point in points]
    if not _finite_tree((mx, my)):
        return None
    return {"max_mx": max(mx), "min_mx": min(mx), "max_my": max(my), "min_my": min(my)}


def _chord(inp, link, extrema, axis, tension_low):
    if extrema is None:
        return None
    m_signed = _number(inp["Mx_pl" if axis == "x" else "My_pl"], "chord moment")
    off_signed = _number(inp["My_pl" if axis == "x" else "Mx_pl"], "off-axis moment")
    off_max = extrema["max_my" if axis == "x" else "max_mx"]
    off_min = extrema["min_my" if axis == "x" else "min_mx"]
    off_cap = off_max if off_signed >= 0.0 else abs(off_min)
    off_util = abs(off_signed) / off_cap if off_cap > 0.0 else (math.inf if off_signed else 0.0)
    m_ed = combined.chord_applied_moment(m_signed, tension_low)
    m_rd, conditional = capacity.shear_face_mrd(inp, axis, tension_low, m_off=off_signed)
    if not conditional and m_rd <= 0.0:
        m_rd = extrema["max_mx" if axis == "x" else "max_my"] if tension_low else abs(
            extrema["min_mx" if axis == "x" else "min_my"]
        )
    if m_rd <= 0.0:
        return None
    return {
        "m_ed": m_ed, "m_rd": float(m_rd), "off_signed": off_signed,
        "off_cap": float(off_cap), "off_util": float(off_util),
        "conditional": bool(conditional), "z_m": link["z_mm"] / 1000.0,
    }


def _authoritative_face(inp, payload, link, extrema):
    concrete = payload["res"]
    if not concrete.get("valid") or concrete.get("vrd_c", 0.0) <= 0.0 or not _finite_tree(payload):
        return None, "INVALID"
    concrete_util = payload["v_ed"] / concrete["vrd_c"]
    # Each mandatory directional face is translated onto the retained uniaxial
    # kernel, whose candidate payload records that face as explicitly selected.
    expected = dict(payload, util=concrete_util, face_mode="selected")
    if link is None:
        status = "PASS" if concrete_util <= 1.0 + _TOL else "FAIL"
        return {"shear": expected, "metric": concrete_util, "status": status,
                "concrete_status": status, "chord": None}, status

    probe = link["build"](link["cot_min"], link["cot_min"])
    if not (probe.get("valid") and probe.get("vrd_s", 0.0) > 0.0 and probe.get("vrd_max", 0.0) > 0.0):
        return None, "NOT ASSESSED"
    chord = _chord(inp, link, extrema, payload["axis"], payload["tension_low"])

    def snap(cot):
        return link["build"](cot, cot)

    utils = [
        lambda cot: combined.ratio(payload["v_ed"], snap(cot)["vrd_s"]),
        lambda cot: combined.ratio(payload["v_ed"], snap(cot)["vrd_max"]),
    ]
    if chord is not None:
        factor = 1.0 if link.get("model_2023") else 0.5
        utils.append(lambda cot: combined.longitudinal_check(
            chord["m_ed"], chord["m_rd"], factor * payload["v_ed"] * cot,
            0.0, chord["z_m"], cap_shear_force=not link.get("model_2023"),
        )["util"])
    cot, _ = combined.governing_strut_cot(utils, link["cot_min"], link["cot_max"], n=1501)
    result = snap(cot)
    util = combined.ratio(payload["v_ed"], result["vrd"])
    longitudinal_force = (1.0 if link.get("model_2023") else 0.5) * payload["v_ed"] * cot
    chord_result = None
    if chord is not None:
        chord_result = combined.longitudinal_check(
            chord["m_ed"], chord["m_rd"], longitudinal_force, 0.0,
            chord["z_m"], cap_shear_force=not link.get("model_2023"),
        )
        chord_result.update(
            valid=True, role="shear_axis", axis=payload["axis"],
            tension_low=payload["tension_low"], off_util=chord["off_util"],
            biaxial=bool(chord["off_util"] > 0.05), m_off=chord["off_signed"],
            conditional=chord["conditional"], has_torsion=False,
            gets_shift=True, off_not_evaluated=None, theta_mode="utilisation",
        )
    angle_limits = link["angle_limits"]
    links = {
        "res": result, "util": util, "asw": link["asw"],
        "asw_over_s": link["asw_over_s"], "legs": link["link_legs"],
        "dia": inp["shear_link_dia"], "s": inp["shear_link_s"],
        "fywk": inp["shear_fywk"], "cot_min": link["cot_min"],
        "cot_max": link["cot_max"],
        "delta_ftd": None if link.get("model_2023") else longitudinal_force,
        "longitudinal_shear_force": longitudinal_force,
        "longitudinal_shear_symbol": "NVd" if link.get("model_2023") else "delta_Ftd",
        "longitudinal_shear_clause": "8.2.3(8), Formula (8.50)" if link.get("model_2023") else "6.2.3(7), Formula (6.18)",
        "cot_limit_lo": angle_limits["minimum"], "cot_limit_hi": angle_limits["maximum"],
        "angle_limits": angle_limits, "model_2023": bool(link.get("model_2023")),
        "z_source": link["z_src"],
        "out_of_limits": bool(link["cot_min"] < angle_limits["minimum"] - _TOL or link["cot_max"] > angle_limits["maximum"] + _TOL),
        "required": bool(payload["v_ed"] > concrete["vrd_c"]),
        "chord": chord_result, "chord_off": None,
        "chord_candidates": [] if chord_result is None else [chord_result],
        "theta_mode": "utilisation",
    }
    expected["links"] = links
    if not _finite_tree(expected) or not math.isfinite(util):
        return None, "INVALID"
    status = "PASS" if util <= 1.0 + _TOL else "FAIL"
    concrete_status = "PASS" if concrete_util <= 1.0 + _TOL else "FAIL"
    return {"shear": expected, "metric": util, "status": status,
            "concrete_status": concrete_status, "chord": chord}, status


def _populate_shared(values, shape, inp, spec, n_prestress, n_comp):
    blocks = shape.blocks
    for ri, ring in enumerate(blocks.geometry.rings):
        for pi, (x, y) in enumerate(ring):
            values[f"geometry-ring-{ri:03d}-point-{pi:04d}-x"] = x
            values[f"geometry-ring-{ri:03d}-point-{pi:04d}-y"] = y
    for kind, elements in (("bar", blocks.geometry.bars), ("tendon", blocks.geometry.tendons)):
        for index, item in enumerate(elements):
            values[f"geometry-{kind}-{index:04d}-x"] = item.x
            values[f"geometry-{kind}-{index:04d}-y"] = item.y
            values[f"geometry-{kind}-{index:04d}-area"] = item.area
    values["geometry-state"] = 1.0
    for block in (blocks.concrete, *blocks.bars, *blocks.tendons):
        for name, value in block.values:
            values[material_step_id(block, name)] = value
    values["material-state"] = 1.0
    actions = dict(blocks.plastic_actions.values)
    for name, value in actions.items():
        values[f"input-action-u{name.encode('utf-8').hex()}"] = value
    values[f"input-{shape.component}-signed-demand"] = spec["signed_v_ed"]
    values["input-web-width-override"] = spec["bw"]
    if shape.links:
        values.update({
            "input-link-legs": spec["legs"],
            "input-link-diameter": _number(inp["shear_link_dia"], "link diameter"),
            "input-link-spacing": _number(inp["shear_link_s"], "link spacing"),
            "input-link-yield": _number(inp["shear_fywk"], "link yield"),
            "input-cot-min": _number(inp["strut_cot_min"], "cot min"),
            "input-cot-max": _number(inp["strut_cot_max"], "cot max"),
        })
        if shape.method == codes.EC2_2023.label:
            values["input-aggregate-lower"] = _number(inp["shear_dlower"], "aggregate lower size")
        if shape.chord:
            values["chord-extrema-plan"] = 15.0
    area, cx, cy = capacity.gross_area_centroid(inp["outer"], inp["holes"])
    pre_n, pre_mx, pre_my = capacity.prestress_resultants(inp, cx, cy)
    values.update({
        "section-area": area, "section-centroid-x": cx,
        "section-centroid-y": cy, "prestress-n": pre_n,
        "prestress-mx": pre_mx, "prestress-my": pre_my,
        "compression-positive-axial": n_comp,
        "associated-moment-origin": spec["moment_origin"],
        "associated-moment-centroid": spec["moment"],
        "absolute-shear-demand": spec["v_ed"],
        "direction-shared-evidence": 1.0,
    })


def _populate_face(values, shape, item):
    payload, link = item["payload"], item["link"]
    replay = item["replay"]
    name = "negative" if payload["tension_low"] else "positive"
    p = f"face-{name}"
    res = payload["res"]
    values.update({
        f"{p}-identity": 1.0, f"{p}-asl": payload["asl"],
        f"{p}-d": payload["d"], f"{p}-bw-auto": payload["bw_auto"],
        f"{p}-bw": payload["bw"], f"{p}-fck": payload["fck"],
        f"{p}-fcd": item["fcd"],
        f"{p}-concrete-utilisation": payload["util"],
        f"{p}-concrete-verdict": 1.0 if replay["concrete_status"] == "PASS" else 0.0,
    })
    if shape.method == codes.EC2_2023.label:
        values.update({
            f"{p}-fyd-flex": payload["fyd_flex"], f"{p}-ddg": payload["ddg"],
            f"{p}-gamma-v": res["gamma_v"], f"{p}-a-cs": res["a_cs"],
            f"{p}-k-vp": res["k_vp"], f"{p}-d-kvp": res["d_kvp"],
            f"{p}-rho-l": res["rho_l"], f"{p}-tau-basic": res["tau_basic"],
            f"{p}-tau-min": res["tau_min"], f"{p}-tau-rdc": res["tau_rdc"],
            f"{p}-vrd-c": res["vrd_c"],
        })
    else:
        values.update({
            f"{p}-k": res["k"], f"{p}-rho-l": res["rho_l"],
            f"{p}-sigma-cp": res["sigma_cp"], f"{p}-crd-c": res["crd_c"],
            f"{p}-k1": res["k1"], f"{p}-vmin": res["vmin"],
            f"{p}-v-basic": res["v_basic"], f"{p}-v-floor": res["v_floor"],
            f"{p}-vrd-c": res["vrd_c"],
        })
    if link is not None:
        links, lr = replay["shear"]["links"], replay["shear"]["links"]["res"]
        values.update({
            f"{p}-asw": links["asw"], f"{p}-asw-over-s": links["asw_over_s"],
            f"{p}-z": lr["z"], f"{p}-fywd": lr["fywd"],
            f"{p}-nu1": lr["nu1"], f"{p}-alpha-cw": lr["alpha_cw"],
            f"{p}-cot": lr["cot"], f"{p}-theta": lr["theta_deg"],
            f"{p}-vrd-s": lr["vrd_s"], f"{p}-vrd-max": lr["vrd_max"],
            f"{p}-vrd": lr["vrd"], f"{p}-linked-utilisation": links["util"],
            f"{p}-links-required": 1.0 if links["required"] else 0.0,
            f"{p}-linked-verdict": 1.0 if replay["status"] == "PASS" else 0.0,
        })
        chord = replay["chord"]
        if chord is not None:
            chk = links["chord"]
            values.update({
                f"{p}-chord-off-moment": chord["off_signed"],
                f"{p}-chord-off-capacity": chord["off_cap"],
                f"{p}-chord-off-util": chord["off_util"],
                f"{p}-chord-biaxial": 1.0 if chk["biaxial"] else 0.0,
                f"{p}-chord-m-ed": chk["m_ed"], f"{p}-chord-m-rd": chk["m_rd"],
                f"{p}-longitudinal-shear-force": links["longitudinal_shear_force"],
                f"{p}-chord-mv": chk["mv"], f"{p}-chord-total-moment": chk["m_total"],
                f"{p}-chord-utilisation": chk["util"],
                f"{p}-chord-verdict": 1.0 if chk["ok"] else 0.0,
            })
    values[f"{p}-complete-evidence"] = 1.0


def _failed(shape, candidate, statuses):
    faces = candidate.get("face_candidates")
    if type(faces) is not list:
        raise TraceValidationError("failed CT-006 face candidates must be a list")
    if len(faces) != len(shape.faces):
        raise TraceValidationError("failed CT-006 face cardinality differs")
    for index, (face, expected_face, status) in enumerate(zip(faces, shape.faces, statuses)):
        face = _mapping(face, f"failed face {index}")
        if face.get("tension_low") is not expected_face or face.get("shear_status") != status:
            raise TraceValidationError("failed CT-006 face identity/state differs")
    expected_status = capacity.aggregate_assessment_status(statuses)
    if candidate.get("status") != expected_status:
        raise TraceValidationError("candidate promotes or demotes authoritative CT-006 failure")
    state = TraceResult(RESULT_FAILED, None, _FAILURE_REASON)
    return DirectionEvidence(
        shape, {}, {"direction-failure-state": state, "direction-shear-verdict": state},
        (_FAILURE_REASON,),
    )


def replay_shear_evidence(inp, out, context) -> ReplayEvidence:
    """Reconstruct CT-006 before parsing finite candidate result numbers."""

    inp = _mapping(inp, "CT-006 input")
    out = _mapping(out, "analysis result")
    context = _mapping(context, "CT-006 context")
    try:
        blocks = section_trace_blocks(inp)
        method = inp["shear_method"]
        if method not in capacity.SHEAR_METHODS:
            raise TraceValidationError("unsupported retained CT-006 shear method")
        specs = capacity.shear_direction_specs(inp)
        active = tuple(name for name in ("vx", "vy") if inp.get("shear_on") and specs[name]["v_ed"] > 0.0)
        if not active:
            raise TraceValidationError("CT-006 needs at least one active direction")
        candidates = _candidate_directions(out, active)
        n_prestress = capacity.prestress_axial(inp)
        n_comp = -_number(inp["P_pl"], "P_pl") + n_prestress
        contexts = capacity.build_directional_shear_contexts(inp, n_prestress, n_comp)
        extrema = _plastic_extrema(inp) if inp.get("shear_links") else None
    except TraceValidationError:
        raise
    except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"invalid CT-006 input: {exc}") from exc

    evidence = []
    for component, candidate in zip(active, candidates):
        spec = specs[component]
        faces = capacity.shear_face_candidates(spec["face"], spec["moment"])
        context_faces = contexts[component]["candidates"]
        if tuple(payload["tension_low"] for payload, _link in context_faces) != faces:
            raise TraceValidationError("retained CT-006 face order diverged")
        provisional = []
        statuses = []
        for payload, link in context_faces:
            replay, status = _authoritative_face(inp, payload, link, extrema)
            provisional.append({
                "payload": payload, "link": link, "replay": replay,
                "fcd": float(inp["concrete"].fcd),
            })
            statuses.append(status)
        chord = bool(inp.get("shear_links") and extrema is not None and all(
            item["replay"] is not None and item["replay"]["chord"] is not None
            for item in provisional
        ))
        finite = all(item["replay"] is not None for item in provisional) and (
            not inp.get("shear_links") or extrema is None or chord
        )
        shape = trace_shape(
            blocks, context, component, spec["axis"], faces, method,
            bool(inp.get("shear_links")), chord,
            BRANCH_FINITE if finite else BRANCH_FAILED,
        )
        if not finite:
            evidence.append(_failed(shape, candidate, tuple(statuses)))
            continue

        face_expected = []
        for tension_low, item in zip(faces, provisional):
            replay = item["replay"]
            face_expected.append({
                "tension_low": tension_low, "shear_status": replay["status"],
                "shear_metric": replay["metric"], "shear": replay["shear"],
            })
        governing_index = max(
            range(len(face_expected)),
            key=lambda index: capacity.assessment_key(
                face_expected[index]["shear_status"], face_expected[index]["shear_metric"]
            ),
        )
        governing = face_expected[governing_index]
        aggregate = capacity.aggregate_assessment_status(item["shear_status"] for item in face_expected)
        expected_direction = dict(governing["shear"])
        expected_direction.update(
            face_mode=str(spec["face"]), both_faces_evaluated=len(faces) == 2,
            governing_face="negative" if governing["tension_low"] else "positive",
            associated_moment=spec["moment"], associated_moment_origin=spec["moment_origin"],
            signed_v_ed=spec["signed_v_ed"], status=aggregate,
            governing_domains={"shear": {
                "face": "negative" if governing["tension_low"] else "positive",
                "cot": ((governing["shear"].get("links") or {}).get("res") or {}).get("cot"),
                "status": aggregate, "util": governing["shear_metric"],
            }},
            face_candidates=face_expected,
        )
        _compare(candidate, expected_direction, f"candidate {component}")

        values = {}
        _populate_shared(values, shape, inp, spec, n_prestress, n_comp)
        for item in provisional:
            _populate_face(values, shape, item)
        values["direction-governing-face"] = float(governing_index + 1)
        values["direction-shear-metric"] = governing["shear_metric"]
        values["direction-shear-verdict"] = 1.0 if aggregate == "PASS" else 0.0
        if not all(math.isfinite(float(value)) for value in values.values()):
            raise TraceValidationError("authoritative CT-006 finite evidence is non-finite")
        missing = [spec.step_id for spec in expected_step_contract(shape) if spec.step_id not in values]
        if missing:
            raise TraceValidationError(f"internal CT-006 replay omitted {', '.join(missing)}")
        warnings = (
            ("The retained 2023 shear method is locally published-not-implemented and carries no standards citation.",)
            if method == codes.EC2_2023.label else ()
        )
        evidence.append(DirectionEvidence(shape, values, {}, warnings))
    return ReplayEvidence(blocks, tuple(evidence))
