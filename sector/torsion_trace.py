"""Solver-owned unpublished CT-007 thin-wall torsion trace."""

from __future__ import annotations

import functools
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from . import capacity, codes, combined
from .calculation_trace import (
    RESULT_FAILED, RESULT_FINITE, TraceBundle, TraceCalculation, TraceDependency,
    TraceResult, TraceStep, TraceValidationError, create_bundle, validate_bundle,
)
from .section import Section
from .section_trace_blocks import (
    _materials as selected_material_blocks, context_axes, context_id,
    section_trace_blocks,
)
from .torsion_trace_contract import (
    CORE_INPUT_KEYS, COVERAGE_ID, METHOD_ID, RESULT_KEYS, SUBTUBE_SUFFIX_KEYS,
    TENDON_INPUT_KEYS, TOP_EXCLUDED, TOP_KEYS, TUBE_KEYS, TorsionShape,
    expected_registry, expected_step_contract, material_leaf_id,
)
from .trace_registry import audit_trace_registry


_TOL = 1.0e-9
_FAILURE_REASON = (
    "The authoritative CT-007 reconstruction did not produce a complete finite "
    "torsion state; no resistance, utilisation, or verdict is published."
)


@dataclass(frozen=True, slots=True)
class TorsionEvidence:
    shape: TorsionShape
    values: dict[str, float]
    expected_output: Mapping[str, Any] | None
    warnings: tuple[str, ...]


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


def _boolean(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise TraceValidationError(f"{label} must be Boolean")
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


def _retained_mapping(value, keys, excluded, label) -> Mapping[str, Any]:
    value = _mapping(value, label)
    retained = tuple(key for key in value if key not in excluded)
    if retained != tuple(keys):
        raise TraceValidationError(
            f"{label} retained keys/order differ: {retained!r}"
        )
    return value


def _close(actual: float, expected: float) -> bool:
    return math.isclose(actual, expected, rel_tol=1.0e-9, abs_tol=1.0e-9)


def _compare(actual: Any, expected: Any, label: str) -> None:
    if expected is None or type(expected) in {bool, str, int}:
        if type(actual) is not type(expected) or actual != expected:
            raise TraceValidationError(f"{label} differs from authoritative replay")
        return
    if type(actual) not in {int, float} or type(actual) is bool:
        raise TraceValidationError(f"{label} must be numerical")
    value = float(actual)
    if not math.isfinite(value) or not _close(value, float(expected)):
        raise TraceValidationError(f"{label} differs from authoritative replay")


def torsion_trace_applicability(inp: Mapping[str, Any]) -> str:
    """Return the retained CT-007 branch without touching unrelated inputs."""

    enabled = _boolean(inp.get("torsion_on"), "torsion_on")
    if not enabled:
        return "not-applicable-disabled"
    if inp.get("section") is None:
        return "not-applicable-no-section"
    combined = _boolean(inp.get("combined_on"), "combined_on")
    shear_enabled = _boolean(inp.get("shear_on"), "shear_on")
    shear_links = _boolean(inp.get("shear_links"), "shear_links")
    if combined:
        return "not-applicable-combined-shared-angle"
    if shear_enabled and shear_links:
        return "not-applicable-reinforced-shear-shared-angle"
    return "torsion"


def _input_state(inp: Mapping[str, Any]) -> dict[str, Any]:
    subdivision = _boolean(inp.get("torsion_subdivide"), "torsion_subdivide")
    required = (*CORE_INPUT_KEYS,
                *(("torsion_subrects",) if subdivision else ("torsion_tef",)))
    missing = tuple(key for key in required if key not in inp)
    if missing:
        raise TraceValidationError(f"CT-007 input inventory missing {missing!r}")
    method = inp.get("torsion_method")
    if method not in {codes.EC2_2005.label, codes.EC2_2005_DKNA.label}:
        raise TraceValidationError(
            "CT-007 supports only the implemented 2004+A1/AC base and DK methods; "
            "the 2023 standard is published but not implemented"
        )
    tendons = _sequence(inp.get("tendons"), "tendons")
    if tendons:
        missing = tuple(key for key in TENDON_INPUT_KEYS if key not in inp)
        if missing:
            raise TraceValidationError(f"CT-007 tendon inventory missing {missing!r}")
    state = dict(
        subdivision=subdivision,
        method=method,
        demand=_number(inp.get("torsion_T"), "torsion_T", nonnegative=True),
        axial=_number(inp.get("P_pl"), "P_pl"),
        detailing=_boolean(inp.get("torsion_nu_v"), "torsion_nu_v"),
        gamma_ct=_number(inp.get("torsion_gamma_ct"), "torsion_gamma_ct", positive=True),
        diameter=_number(inp.get("shear_link_dia"), "shear_link_dia", positive=True),
        spacing=_number(inp.get("shear_link_s"), "shear_link_s", positive=True),
        fywk=_number(inp.get("shear_fywk"), "shear_fywk", positive=True),
        cot_first=_number(inp.get("strut_cot_min"), "strut_cot_min", positive=True),
        cot_second=_number(inp.get("strut_cot_max"), "strut_cot_max", positive=True),
        tendons=tendons,
        shear_enabled=_boolean(inp.get("shear_on"), "shear_on"),
        shear_links=_boolean(inp.get("shear_links"), "shear_links"),
        combined=_boolean(inp.get("combined_on"), "combined_on"),
    )
    if subdivision:
        rectangles = _sequence(inp.get("torsion_subrects"), "torsion_subrects")
        if not rectangles:
            raise TraceValidationError("torsion_subrects must contain at least one tube")
        checked = []
        for index, raw in enumerate(rectangles):
            values = _sequence(raw, f"torsion_subrects[{index}]")
            if len(values) != 4:
                raise TraceValidationError("each torsion sub-tube needs x, y, b, h")
            x = _number(values[0], f"sub-tube {index} x")
            y = _number(values[1], f"sub-tube {index} y")
            b = _number(values[2], f"sub-tube {index} b", positive=True)
            h = _number(values[3], f"sub-tube {index} h", positive=True)
            checked.append((x, y, b, h))
        state["rectangles"] = tuple(checked)
    else:
        state["tef"] = _number(inp.get("torsion_tef"), "torsion_tef", nonnegative=True)
        state["rectangles"] = ()
    return state


def _capacity_steel_block(inp):
    material_id = inp.get("capacity_steel_material_id")
    if (type(material_id) is not str or not material_id
            or material_id != material_id.strip()):
        raise TraceValidationError("capacity_steel_material_id must be non-blank text")
    aligned = dict(
        inp,
        bar_materials=(inp.get("steel"),),
        bar_elements=({"id": "capacity-torsion-steel", "material_id": material_id},),
    )
    return selected_material_blocks(
        aligned, kind="bar", count=1, default=inp.get("steel")
    )[0]


def _scoped_blocks(inp, state):
    outer = _sequence(inp.get("outer"), "outer")
    holes = _sequence(inp.get("holes"), "holes")
    section = inp.get("section")
    validator = getattr(section, "require_valid_geometry", None)
    if not callable(validator):
        raise TraceValidationError("CT-007 needs a retained Section")
    validator()
    raw_rings = (outer, *holes)
    stored_rings = tuple(tuple(tuple(float(v) for v in point) for point in ring)
                         for ring in section.concrete)
    checked_rings = tuple(tuple(tuple(_number(v, "concrete coordinate") for v in
                                      _sequence(point, "concrete point"))
                                for point in _sequence(ring, "concrete ring"))
                          for ring in raw_rings)
    if stored_rings != checked_rings:
        raise TraceValidationError("raw and retained concrete geometry differ")
    raw_tendons = []
    for index, raw in enumerate(state["tendons"]):
        values = _sequence(raw, f"tendon {index}")
        if len(values) != 3:
            raise TraceValidationError("tendon entries need x, y, area")
        raw_tendons.append(tuple(_number(value, f"tendon {index}") for value in values))
    stored_tendons = tuple((float(item.x), float(item.y), float(item.area) * 1.0e6)
                           for item in section.tendons)
    # The stored area is the entered mm2 value through a lossy unit round-trip;
    # tolerate it exactly like the accepted CT-006 sibling comparison.
    if len(stored_tendons) != len(raw_tendons) or not all(
            _close(stored, raw)
            for stored_item, raw_item in zip(stored_tendons, raw_tendons)
            for stored, raw in zip(stored_item, raw_item)):
        raise TraceValidationError("raw and retained tendon geometry differ")

    scoped = dict(inp)
    scoped.update(
        section=Section.from_polygon(outer, (), holes, raw_tendons),
        bars=[], bar_elements=[], bar_materials=None,
        P_pl=state["axial"], Mx_pl=0.0, My_pl=0.0,
    )
    if not raw_tendons:
        scoped.update(prestress=None, tendon_elements=[], tendon_materials=None)
    blocks = section_trace_blocks(scoped)
    steel = _capacity_steel_block(inp)
    sources = (blocks.concrete.provenance.source, steel.provenance.source,
               *(item.provenance.source for item in blocks.tendons))
    if any(source.citation is not None and "2023" in source.citation.document
           for source in sources):
        raise TraceValidationError(
            "2023 material provenance is published but not implemented for CT-007"
        )
    return blocks, steel


def _identity_values(inp, state, blocks, steel) -> dict[str, float]:
    values = {
        "input-torsion-enabled": 1.0,
        "input-method-code": 1.0 if state["method"] == codes.EC2_2005_DKNA.label else 0.0,
        "input-demand": state["demand"], "input-axial-force": state["axial"],
        "input-nu-detailing": float(state["detailing"]),
        "input-gamma-ct": state["gamma_ct"],
        "input-link-diameter": state["diameter"],
        "input-link-spacing": state["spacing"], "input-link-fywk": state["fywk"],
        "input-cot-min": state["cot_first"], "input-cot-max": state["cot_second"],
        "input-subdivision-enabled": float(state["subdivision"]),
        "input-shear-enabled": float(state["shear_enabled"]),
        "input-shear-links-enabled": float(state["shear_links"]),
        "input-combined-enabled": float(state["combined"]),
    }
    if state["subdivision"]:
        for index, rectangle in enumerate(state["rectangles"]):
            for suffix, value in zip(("x", "y", "b", "h"), rectangle):
                values[f"input-tube-{index:02d}-{suffix}"] = value
    else:
        values["input-tef-override"] = state["tef"]
    for ring_index, ring in enumerate(blocks.geometry.rings):
        for point_index, point in enumerate(ring):
            prefix = f"geometry-ring-{ring_index:03d}-point-{point_index:04d}"
            values[f"{prefix}-x"], values[f"{prefix}-y"] = point
    for index, tendon in enumerate(blocks.geometry.tendons):
        prefix = f"geometry-tendon-{index:04d}"
        values.update({f"{prefix}-x": tendon.x, f"{prefix}-y": tendon.y,
                       f"{prefix}-area": tendon.area})
    values["geometry-vector"] = 1.0
    for material in (blocks.concrete, steel, *blocks.tendons):
        for name, value in material.values:
            values[material_leaf_id(material, name)] = value
    values["material-vector"] = values["normalised-torsion-inputs"] = 1.0
    return values


def _finite_result(result: Mapping[str, Any], *, subdivided: bool) -> bool:
    names = RESULT_KEYS[1:10] + ("nu",)
    if not result.get("valid") or not result.get("tube", {}).get("valid"):
        return False
    try:
        if not all(type(result[name]) in {int, float} and type(result[name]) is not bool
                   and math.isfinite(float(result[name])) for name in names):
            return False
        if result["trd"] <= 0.0 or result["trd_max"] <= 0.0:
            return False
        if subdivided:
            return all(math.isfinite(float(result[name])) for name in SUBTUBE_SUFFIX_KEYS)
        return True
    except (KeyError, TypeError, ValueError):
        return False


def _selected_results(ctx, state):
    if not all(tube.get("valid") for tube in ctx["subtubes"]):
        return None
    if state["subdivision"] and not ctx["subdivide"]:
        return None

    @functools.lru_cache(maxsize=4096)
    def pinned(cot):
        kwargs = dict(ctx["_tk"], cot_min=cot, cot_max=cot)
        return tuple(capacity.tube_torsion(tube, demand, **kwargs)
                     for tube, demand in zip(ctx["subtubes"], ctx["ted_parts"]))

    if state["demand"] > 0.0:
        utilities = [lambda cot, index=index: pinned(cot)[index]["util"]
                     for index in range(len(ctx["subtubes"]))]
        cot, _ = combined.governing_strut_cot(
            utilities, ctx["tcot_min"], ctx["tcot_max"], n=1501
        )
        raw = list(pinned(cot))
        mode = "utilisation"
    else:
        raw = [capacity.tube_torsion(tube, demand, **ctx["_tk"])
               for tube, demand in zip(ctx["subtubes"], ctx["ted_parts"])]
        mode = "resistance"
    results = []
    for index, result in enumerate(raw):
        result = dict(result)
        if state["subdivision"]:
            result["stiffness"] = ctx["consts"][index]
            (result["x_mm"], result["y_mm"], result["b_mm"],
             result["h_mm"]) = ctx["sub_dims"][index]
        if not _finite_result(result, subdivided=state["subdivision"]):
            return None
        results.append(result)
    return results, mode


def _expected_output(ctx, state, results, mode, n_prestress):
    primary = results[0]
    if state["subdivision"]:
        total_resistance = sum(result["trd"] for result in results)
        total_asl = sum(result["asl_req"] for result in results)
        governing = max(range(len(results)), key=lambda index: results[index]["util"])
        utilisation = results[governing]["util"]
        subtubes = results
    else:
        total_resistance, total_asl = primary["trd"], primary["asl_req"]
        governing, utilisation, subtubes = None, primary["util"], None
    code = ctx["tcode"]
    outside = bool(ctx["tcot_min"] < code.shear_cot_min_limit - _TOL
                   or ctx["tcot_max"] > code.shear_cot_max_limit + _TOL)
    result = dict(
        tube=primary["tube"], trd_s=primary["trd_s"], trd_max=primary["trd_max"],
        trd=total_resistance, trd_c=primary["trd_c"], cot=primary["cot"],
        theta_deg=primary["theta_deg"], util=utilisation, asl_req=total_asl,
        t_ed=ctx["t_ed"], fcd=ctx["fcd"], fywd=ctx["fywd_t"],
        fyd_long=ctx["fyd_long"], nu=primary["nu"], alpha_cw=ctx["alpha_cw"],
        fctd=ctx["fctd"], fctk_005=ctx["fctk_005"], gamma_c=ctx["gamma_c"],
        gamma_ct=ctx["gamma_ct"], gamma_s=ctx["gamma_s"],
        nu_v_detailing=ctx["nu_detail_applied"], sigma_cp=ctx["sigma_cp"],
        n_prestress=n_prestress, asw_t=ctx["asw_t"],
        asw_over_s=ctx["asw_over_s_t"], dia=state["diameter"], s=state["spacing"],
        cot_min=ctx["tcot_min"], cot_max=ctx["tcot_max"], method=state["method"],
        governs=primary["governs"], valid=True, reason=primary["tube"].get("reason"),
        cot_limit_lo=code.shear_cot_min_limit, cot_limit_hi=code.shear_cot_max_limit,
        out_of_limits=outside, subdivided=state["subdivision"], subtubes=subtubes,
        primary=primary, governing_sub=governing,
        compound_detected=ctx["compound_detected"],
        subdivision_requested=ctx["subdivision_requested"],
        subdivision_valid=ctx["subdivision_valid"],
        subdivision_reason=ctx["subdivision_reason"], theta_mode=mode,
    )
    if tuple(result) != TOP_KEYS:
        raise TraceValidationError("authoritative CT-007 output inventory drifted")
    return result


def _mechanics_values(values, state, blocks, steel, ctx, results, mode):
    fck = dict(blocks.concrete.values)["fck"]
    values.update({
        "concrete-fcd": ctx["fcd"], "concrete-fctm": codes.fctm(fck),
        "concrete-fctk-005": ctx["fctk_005"], "concrete-fctd": ctx["fctd"],
        "link-fywd": ctx["fywd_t"], "longitudinal-fyd": ctx["fyd_long"],
        "closed-link-area": ctx["asw_t"], "closed-link-ratio": ctx["asw_over_s_t"],
    })
    tendon_forces = []
    for index, (material, tendon) in enumerate(zip(blocks.tendons, blocks.geometry.tendons)):
        law = dict(material.values)
        force = law["Es"] * law["IS"] * 1000.0 * tendon.area
        values[f"tendon-{index:02d}-locked-force"] = force
        tendon_forces.append(force)
    values["prestress-axial"] = sum(tendon_forces)
    values["compression-positive-axial"] = -state["axial"] + values["prestress-axial"]
    values.update({
        "net-concrete-area": capacity.gross_area_centroid(
            tuple(tuple(point) for point in blocks.geometry.rings[0]),
            tuple(tuple(tuple(point) for point in ring) for ring in blocks.geometry.rings[1:]),
        )[0],
        "mean-compression-stress": ctx["sigma_cp"], "alpha-cw": ctx["alpha_cw"],
        "nu-detailing-applied": float(ctx["nu_detail_applied"]),
        "torsion-nu": results[0]["nu"], "cot-band-low": ctx["tcot_min"],
        "cot-band-high": ctx["tcot_max"],
        "method-cot-limit-low": ctx["tcode"].shear_cot_min_limit,
        "method-cot-limit-high": ctx["tcode"].shear_cot_max_limit,
        "cot-outside-method-range": float(
            ctx["tcot_min"] < ctx["tcode"].shear_cot_min_limit - _TOL
            or ctx["tcot_max"] > ctx["tcode"].shear_cot_max_limit + _TOL
        ),
        "compound-outline": float(ctx["compound_detected"]),
        "subdivision-valid": float(ctx["subdivision_valid"]),
        "subdivision-applied": float(ctx["subdivide"]),
    })
    if state["subdivision"]:
        values["total-torsion-stiffness"] = sum(ctx["consts"])
    if state["demand"] > 0.0:
        values["selector-operands"] = 1.0
        values["selector-cot"] = results[0]["cot"]
        values["selector-theta"] = results[0]["theta_deg"]
    for index, result in enumerate(results):
        p, tube = f"tube-{index:02d}", result["tube"]
        if state["subdivision"]:
            values[f"{p}-stiffness"] = result["stiffness"]
            values[f"{p}-entered-geometry"] = 1.0
        values.update({
            f"{p}-outer-area": tube["A"], f"{p}-outer-perimeter": tube["u"],
            f"{p}-tef-auto": tube["tef_auto"], f"{p}-tef": tube["tef"],
            f"{p}-tef-capped": float(tube["tef_capped"]),
            f"{p}-tef-user": float(tube["tef_user"]),
            f"{p}-hollow": float(tube["hollow"]),
            f"{p}-minimum-dimension": tube["minimum_dimension_mm"],
            f"{p}-ak": tube["Ak"], f"{p}-uk": tube["uk"],
            f"{p}-geometry-valid": float(tube["valid"]),
            f"{p}-demand": result["t_ed"], f"{p}-trd-s": result["trd_s"],
            f"{p}-trd-max": result["trd_max"], f"{p}-trd": result["trd"],
            f"{p}-trd-c": result["trd_c"],
            f"{p}-asl-required": result["asl_req"],
            f"{p}-utilisation": result["util"],
            f"{p}-governing-mode": float(result["governs"].startswith("stirrups")),
            f"{p}-verdict": float(result["util"] <= 1.0 + _TOL),
            f"{p}-complete-evidence": 1.0,
        })
        if state["demand"] == 0.0:
            values[f"{p}-resistance-selector-operands"] = 1.0
            values[f"{p}-cot"] = result["cot"]
            values[f"{p}-theta"] = result["theta_deg"]
    governing = max(range(len(results)), key=lambda index: results[index]["util"])
    values.update({
        "aggregate-demand": sum(result["t_ed"] for result in results),
        "aggregate-resistance": sum(result["trd"] for result in results),
        "aggregate-asl-required": sum(result["asl_req"] for result in results),
        "aggregate-utilisation": results[governing]["util"],
        "aggregate-governing-tube": float(governing),
        "aggregate-verdict": float(results[governing]["util"] <= 1.0 + _TOL),
        "selector-mode": float(mode == "utilisation"),
        "ct-007-torsion-result": float(results[governing]["util"] <= 1.0 + _TOL),
    })
    return values


def _shape(inp, state, blocks, steel, ctx, failed, context):
    variant = "dk" if state["method"] == codes.EC2_2005_DKNA.label else "base"
    tube_count = len(state["rectangles"]) if state["subdivision"] else 1
    axes = context_axes(
        context,
        capacity_steel_material_id=steel.material_id,
        demand_branch="zero" if state["demand"] == 0.0 else "positive",
        load_convention="absolute-capacity-magnitude",
        method_variant=variant,
        tube_count=str(tube_count),
        tube_mode="subdivided" if state["subdivision"] else "single",
        torsion_method=state["method"],
    )
    return TorsionShape(
        blocks, steel, tube_count, state["subdivision"], state["demand"] == 0.0,
        failed, variant, bool(ctx["nu_detail_applied"]),
        f"ct-007-{context_id(context)}-torsion", axes,
    )


def _validate_tube(candidate, expected, label):
    candidate = _retained_mapping(candidate, TUBE_KEYS, (), label)
    for key in TUBE_KEYS:
        _compare(candidate[key], expected[key], f"{label}.{key}")


def _validate_result(candidate, expected, label, *, subdivided):
    keys = (*RESULT_KEYS, *(SUBTUBE_SUFFIX_KEYS if subdivided else ()))
    candidate = _retained_mapping(candidate, keys, (), label)
    _validate_tube(candidate["tube"], expected["tube"], f"{label}.tube")
    for key in keys[1:]:
        _compare(candidate[key], expected[key], f"{label}.{key}")


def _validate_candidate(candidate, expected):
    candidate = _retained_mapping(candidate, TOP_KEYS, TOP_EXCLUDED,
                                  "candidate torsion aggregate")
    _validate_tube(candidate["tube"], expected["tube"], "candidate torsion.tube")
    subdivided = expected["subdivided"]
    _validate_result(candidate["primary"], expected["primary"],
                     "candidate torsion.primary", subdivided=subdivided)
    if subdivided:
        items = _sequence(candidate["subtubes"], "candidate torsion.subtubes")
        if len(items) != len(expected["subtubes"]):
            raise TraceValidationError("candidate sub-tube cardinality differs")
        for index, (actual, wanted) in enumerate(zip(items, expected["subtubes"])):
            _validate_result(actual, wanted, f"candidate torsion.subtubes[{index}]",
                             subdivided=True)
    elif candidate["subtubes"] is not None:
        raise TraceValidationError("single-tube candidate must have null subtubes")
    for key in TOP_KEYS:
        if key not in {"tube", "primary", "subtubes"}:
            _compare(candidate[key], expected[key], f"candidate torsion.{key}")


def _replay(inp, torsion_out, context):
    state = _input_state(inp)
    blocks, steel = _scoped_blocks(inp, state)
    n_prestress = capacity.prestress_axial(inp)
    n_comp = -state["axial"] + n_prestress
    mechanics_input = dict(inp)
    if state["subdivision"]:
        # The retained sub-tube path discards the single-tube override. Keep that
        # excluded sibling inert while still entering the unchanged low-level API.
        mechanics_input["torsion_tef"] = 0.0
    ctx = capacity.build_torsion_context(mechanics_input, n_comp)
    if ctx is None:
        raise TraceValidationError("active CT-007 input produced no torsion context")
    selected = _selected_results(ctx, state)
    failed = selected is None
    shape = _shape(inp, state, blocks, steel, ctx, failed, context)
    values = _identity_values(inp, state, blocks, steel)
    warnings = []
    if failed:
        values["authoritative-failure-state"] = 1.0
        values["ct-007-torsion-result"] = 0.0
        return TorsionEvidence(shape, values, None, ())
    results, mode = selected
    expected = _expected_output(ctx, state, results, mode, n_prestress)
    _validate_candidate(torsion_out, expected)
    _mechanics_values(values, state, blocks, steel, ctx, results, mode)
    if expected["out_of_limits"]:
        warnings.append("Entered cotangent bounds are outside the retained method range.")
    return TorsionEvidence(shape, values, expected, tuple(warnings))


def _expression(step_id: str, title: str) -> str:
    expressions = {
        "tef-auto": "tef,auto = A/u", "trd-s": "TRd,s = (Asw/s)*2*Ak*fywd*cot(theta)",
        "trd-max": "TRd,max = 2*nu*alpha_cw*fcd*Ak*tef*cot/(1+cot^2)",
        "trd-c": "TRd,c = 2*Ak*tef*fctd", "asl-required": "Asl,req = TEd*uk*cot/(2*Ak*fyd)",
        "utilisation": "utilisation = demand/resistance",
    }
    for suffix, expression in expressions.items():
        if step_id.endswith(suffix):
            return expression
    if step_id in {"selector-cot"}:
        return "argmin_1501 (max tube utilisation, sum tube utilisations, cot)"
    if step_id.endswith("-cot"):
        return "retained resistance-optimum cotangent in the original band"
    if step_id.endswith("verdict") or step_id == "ct-007-torsion-result":
        return "PASS = 1 when utilisation <= 1 + 1e-9, otherwise FAIL = 0"
    return f"Bind {title.lower()}"


def _calculation(evidence: TorsionEvidence) -> TraceCalculation:
    specs = expected_step_contract(evidence.shape)
    units = {spec.step_id: spec.unit for spec in specs}
    steps = []
    for spec in specs:
        failed_final = evidence.shape.failed and spec.step_id == "ct-007-torsion-result"
        result = (TraceResult(RESULT_FAILED, None, _FAILURE_REASON) if failed_final
                  else TraceResult(RESULT_FINITE, float(evidence.values[spec.step_id])))
        substituted = (f"{spec.step_id} = {result.state}" if failed_final else
                       f"{spec.step_id} = {float(result.value):.17g} {spec.unit.symbol}")
        steps.append(TraceStep(
            spec.step_id, spec.title,
            tuple(TraceDependency(name, units[name]) for name in spec.dependencies),
            spec.quantity_role, spec.source, spec.step_id, spec.unit,
            _expression(spec.step_id, spec.title), substituted, result,
        ))
    return TraceCalculation(
        evidence.shape.calculation_id, COVERAGE_ID, "Thin-wall torsion aggregate",
        METHOD_ID, evidence.shape.axes, "ct-007-torsion-result", tuple(steps),
        evidence.warnings,
        ("Shear-torsion interaction and minimum-reinforcement/detailing checks are outside CT-007.",
         "Longitudinal Asl is a required quantity; retained main has no provided-steel verdict."),
    )


def _expected_bundle(inp, torsion_out, input_sha256, result_sha256, context):
    evidence = _replay(inp, torsion_out, context)
    bundle = create_bundle(
        input_sha256=input_sha256, result_sha256=result_sha256,
        calculations=(_calculation(evidence),),
    )
    audit_trace_registry(bundle, expected_registry(evidence.shape))
    return bundle


def build_torsion_trace_family(
    inp: Mapping[str, Any], torsion_out: Mapping[str, Any], *,
    input_sha256: str, result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle | None:
    """Build and seal the applicable CT-007 torsion family."""

    try:
        if torsion_trace_applicability(inp) != "torsion":
            return None
        return _expected_bundle(inp, torsion_out, input_sha256, result_sha256,
                                {} if context is None else context)
    except TraceValidationError:
        raise
    except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError) as exc:
        raise TraceValidationError(f"invalid CT-007 torsion evidence: {exc}") from exc


def validate_torsion_trace_family(
    bundle: TraceBundle | dict[str, Any] | None,
    inp: Mapping[str, Any], torsion_out: Mapping[str, Any], *,
    input_sha256: str, result_sha256: str,
    context: Mapping[str, Any] | None = None,
) -> TraceBundle | None:
    """Reject stale or coherently resealed CT-007 value/graph/source tampering."""

    if torsion_trace_applicability(inp) != "torsion":
        if bundle is not None:
            raise TraceValidationError("not-applicable CT-007 input cannot carry a trace")
        return None
    candidate = validate_bundle(
        bundle, expected_input_sha256=input_sha256,
        expected_result_sha256=result_sha256,
    )
    expected = _expected_bundle(inp, torsion_out, input_sha256, result_sha256,
                                {} if context is None else context)
    if candidate.to_dict() != expected.to_dict():
        raise TraceValidationError("CT-007 trace differs from authoritative input replay")
    return candidate
