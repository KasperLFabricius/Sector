"""Headless orchestration helpers for member shear, torsion and M-V-T checks.

The Streamlit application owns widgets and session state; this module owns the
calculation contexts and result-payload assembly that do not depend on Streamlit.
Keeping that boundary explicit makes the engineering logic directly unit-testable
and prevents UI reruns from becoming the only way to exercise member checks.
"""

from __future__ import annotations

import math

from . import codes, combined, geometry, shear, templates, torsion
from .plastic import FACE_ANGLE, conditional_capacity, plastic_capacity_at_angle


SHEAR_CODES = {c.label: c for c in (codes.EC2_2005_DKNA, codes.EC2_2005)}
SHEAR_METHODS = dict(SHEAR_CODES, **{codes.EC2_2023.label: codes.EC2_2023})


def gross_area_centroid(outer, holes):
    """Return net concrete area (m2) and centroid ``(cx, cy)`` in metres."""
    mo = geometry.area_moments(outer)
    area = abs(mo.area)
    if area <= 0.0:
        return 0.0, 0.0, 0.0
    cx, cy = mo.sx / mo.area, mo.sy / mo.area
    net_area, mx, my = area, cx * area, cy * area
    for hole in holes or []:
        mh = geometry.area_moments(hole)
        hole_area = abs(mh.area)
        if hole_area <= 0.0:
            continue
        net_area -= hole_area
        mx -= (mh.sx / mh.area) * hole_area
        my -= (mh.sy / mh.area) * hole_area
    if net_area <= 0.0:
        return area, cx, cy
    return net_area, mx / net_area, my / net_area


def design_yield(material):
    """Design yield ``f_yd = f_ytk / gamma_y`` from material parameters."""
    gamma_y = getattr(material, "gamma_y", 0.0)
    return material.fytk / gamma_y if gamma_y > 0.0 else material.fytk


def prestress_resultants(inp, cx=0.0, cy=0.0):
    """Return locked-in tendon ``(P, Mx, My)`` about ``(cx, cy)`` in kN/kNm."""
    prestress = inp.get("prestress")
    tendons = inp.get("tendons")
    materials = inp.get("tendon_materials")
    if not tendons or (prestress is None and not materials):
        return 0.0, 0.0, 0.0
    materials = materials or [prestress] * len(tendons)
    if len(materials) != len(tendons):
        raise ValueError("one prestressing material is required per tendon")
    forces = [material.Es * material.IS * 1000.0 * tendon[2] / 1.0e6
              for material, tendon in zip(materials, tendons)]
    axial = sum(forces)
    mx = sum(force * (tendon[1] - cy)
             for force, tendon in zip(forces, tendons))
    my = sum(force * (tendon[0] - cx)
             for force, tendon in zip(forces, tendons))
    return axial, mx, my


def prestress_axial(inp):
    """Tendon precompression in kN."""
    return prestress_resultants(inp)[0]


def shear_lever_arm(inp, axis, tension_low, d_mm):
    """Return the plastic internal shear lever arm in mm, or the ``0.9 d`` fallback."""
    fallback = (0.9 * d_mm, "0.9 d (fallback)")
    if inp["section"] is None:
        return fallback
    angle = FACE_ANGLE[(axis, tension_low)]
    prestress = inp["prestress"] if inp["tendons"] else None
    try:
        point = plastic_capacity_at_angle(
            inp["section"], inp["concrete"], inp["steel"], -inp["P_pl"],
            angle, prestress=prestress,
            bar_materials=inp.get("bar_materials"),
            tendon_materials=inp.get("tendon_materials"),
        )
    except Exception:
        return fallback
    lever = abs(point.dy) if axis == "x" else abs(point.dx)
    if not point.converged or lever <= 1e-6:
        return fallback
    return lever * 1000.0, "plastic internal lever arm"


def shear_face_mrd(inp, axis, tension_low, m_off=0.0):
    """Return chord ``M_Rd`` conditional on the coexisting off-axis moment."""
    if inp["section"] is None:
        return 0.0, False
    prestress = inp["prestress"] if inp["tendons"] else None
    try:
        mrd, exact = conditional_capacity(
            inp["section"], inp["concrete"], inp["steel"], -inp["P_pl"],
            axis, tension_low, m_off, prestress=prestress,
            bar_materials=inp.get("bar_materials"),
            tendon_materials=inp.get("tendon_materials"),
        )
    except Exception:
        mrd, exact = 0.0, False
    if exact:
        return mrd, True
    angle = FACE_ANGLE[(axis, tension_low)]
    try:
        point = plastic_capacity_at_angle(
            inp["section"], inp["concrete"], inp["steel"], -inp["P_pl"],
            angle, prestress=prestress,
            bar_materials=inp.get("bar_materials"),
            tendon_materials=inp.get("tendon_materials"),
        )
    except Exception:
        return 0.0, False
    if not point.converged:
        return 0.0, False
    return (abs(point.Mx) if axis == "x" else abs(point.My)), False


def tube_torsion(
    tube,
    t_ed,
    *,
    tcode,
    fck,
    fcd,
    alpha_cw,
    fywd,
    asw_over_s,
    cot_min,
    cot_max,
    nu_detail,
    fctd,
    fyd_long,
):
    """Build the resistance/utilisation payload for one thin-walled tube."""
    nu_t = tcode.torsion_nu(fck, closed_detailing=nu_detail)
    a_t = asw_over_s * fywd
    b_t = nu_t * alpha_cw * fcd * tube["tef"]
    cot = (
        shear.optimum_cot_theta(a_t, b_t, cot_min, cot_max)
        if a_t > 0.0 else max(cot_min, 1.0)
    )
    trd_s = torsion.trd_s(tube["Ak"], fywd, asw_over_s, cot)
    trd_max = torsion.trd_max(
        fck, tcode, tube["Ak"], tube["tef"], alpha_cw, cot,
        closed_detailing=nu_detail, fcd_mpa=fcd,
    )
    trd = min(trd_s, trd_max) if asw_over_s > 0.0 else trd_max
    trd_c = torsion.trd_c(fctd, tube["Ak"], tube["tef"])
    util = t_ed / trd if trd > 0.0 else math.inf
    asl = torsion.asl_required(t_ed, tube["uk"], tube["Ak"], fyd_long, cot)
    governs = (
        "stirrups (TRd,s)"
        if asw_over_s > 0.0 and trd_s <= trd_max
        else "crushing (TRd,max)"
    )
    return {
        "tube": tube,
        "t_ed": t_ed,
        "trd_s": trd_s,
        "trd_max": trd_max,
        "trd": trd,
        "trd_c": trd_c,
        "cot": cot,
        "theta_deg": math.degrees(math.atan(1.0 / cot)) if cot > 0.0 else 0.0,
        "util": util,
        "asl_req": asl,
        "nu": nu_t,
        "governs": governs,
        "valid": tube["valid"],
    }


def shear_face_candidates(face, associated_moment, *, zero_tolerance=1.0e-9):
    """Return the low/high-coordinate faces required by one directional check.

    Positive Mx tensions the bottom (negative-y) face and positive My tensions the
    left (negative-x) face.  An automatic selection at effectively zero associated
    moment checks both faces because shear sign alone cannot identify the tension
    reinforcement.
    """
    token = str(face or "auto").strip().casefold()
    if token == "negative":
        return (True,)
    if token == "positive":
        return (False,)
    if token != "auto":
        raise ValueError("shear face must be auto, negative or positive")
    moment = float(associated_moment)
    if moment > zero_tolerance:
        return (True,)
    if moment < -zero_tolerance:
        return (False,)
    return (True, False)


def assessment_key(status, utilisation):
    """Conservative ordering shared by mandatory directional candidates."""
    priority = {
        "INVALID": 4,
        "FAIL": 3,
        "NOT ASSESSED": 2,
        "NOT RUN": 2,
        "PASS": 1,
        "NOT APPLICABLE": 0,
    }.get(str(status or "").upper(), 2)
    value = float(utilisation or 0.0)
    if not math.isfinite(value):
        value = math.inf
    return priority, value


def aggregate_assessment_status(statuses):
    """Return the conservative status across every required candidate."""
    values = {str(status or "").upper() for status in statuses}
    for status in ("INVALID", "FAIL", "NOT ASSESSED", "NOT RUN", "PASS"):
        if status in values:
            return status
    return "NOT ASSESSED"


def shear_direction_specs(inp):
    """Canonical mapping from Vx/Vy inputs to the existing bending-axis model."""
    _, cx, cy = gross_area_centroid(
        inp.get("outer", []), inp.get("holes", [])
    )
    _, mx_prestress, my_prestress = prestress_resultants(inp, cx, cy)
    axial = float(inp.get("P_pl", 0.0))
    mx_origin = float(inp.get("Mx_pl", 0.0))
    my_origin = float(inp.get("My_pl", 0.0))
    # Section forces are entered about the coordinate origin. Face selection must
    # follow the bending at the physical concrete centroid, including the locked-in
    # tendon moment, exactly like the action-dependent shear calculation below.
    mx_centroid = mx_origin - axial * cy - mx_prestress
    my_centroid = my_origin - axial * cx - my_prestress
    components = inp.get("shear_components") or {}
    vx_signed = float(
        (components.get("vx") or {}).get(
            "signed_v_ed", inp.get("shear_Vx", 0.0)
        )
    )
    vy_signed = float(
        (components.get("vy") or {}).get(
            "signed_v_ed", inp.get("shear_Vy", 0.0)
        )
    )
    return {
        "vx": {
            "axis": "y",
            "moment": my_centroid,
            "moment_origin": my_origin,
            "v_ed": abs(vx_signed),
            "signed_v_ed": vx_signed,
            "face": inp.get("shear_face_x", "auto"),
            "bw": float(inp.get("shear_vx_bw", 0.0)),
            "legs": float(inp.get("shear_vx_link_legs", 2.0)),
        },
        "vy": {
            "axis": "x",
            "moment": mx_centroid,
            "moment_origin": mx_origin,
            "v_ed": abs(vy_signed),
            "signed_v_ed": vy_signed,
            "face": inp.get("shear_face_y", "auto"),
            "bw": float(inp.get("shear_vy_bw", 0.0)),
            "legs": float(inp.get("shear_vy_link_legs", 2.0)),
        },
    }


def _build_shear_face_context(
    inp,
    n_prestress,
    n_ed_comp,
    *,
    component,
    axis,
    tension_low,
    v_ed,
    bw_override,
    link_legs,
    face_mode,
):
    """Build one face candidate for one physical shear component."""
    code = SHEAR_METHODS.get(inp["shear_method"], codes.EC2_2005_DKNA)
    model_2023 = getattr(code, "shear_model", "2005") == "2023"
    area, cx, cy = gross_area_centroid(inp["outer"], inp["holes"])
    _, mx_prestress, my_prestress = prestress_resultants(inp, cx, cy)
    centroid_coord = cy if axis == "x" else cx
    asl, cg, asl_bar_ids = shear.tension_reinforcement_selection(
        inp["bars"], axis, tension_low, centroid_coord
    )
    d_mm = shear.effective_depth(inp["outer"], axis, tension_low, cg)
    bw_auto = shear.min_web_width(inp["outer"], inp["holes"], axis)
    bw_mm = bw_override if bw_override > 0.0 else bw_auto
    fck = inp["concrete"].fck
    fyd_flex = design_yield(inp["steel"])
    ddg = code.shear_ddg(fck, inp["shear_dlower"]) if model_2023 else 0.0
    if axis == "x":
        m_ed_2023 = inp["Mx_pl"] - inp["P_pl"] * cy - mx_prestress
        m_prestress = mx_prestress
    else:
        m_ed_2023 = inp["My_pl"] - inp["P_pl"] * cx - my_prestress
        m_prestress = my_prestress
    result = shear.vrd_c(
        fck, code, bw_mm, d_mm, asl, n_ed_comp, area,
        fyd_mpa=fyd_flex, ddg_mm=(ddg or 32.0),
        m_ed_knm=m_ed_2023, v_ed_kn=v_ed,
        fcd_mpa=inp["concrete"].fcd,
        gamma_c=inp["concrete"].gamma_c,
    )
    util = v_ed / result["vrd_c"] if result["vrd_c"] > 0.0 else math.inf
    payload = {
        "res": result,
        "v_ed": v_ed,
        "util": util,
        "component": component,
        "axis": axis,
        "tension_low": tension_low,
        "face_mode": face_mode,
        "bw": bw_mm,
        "bw_auto": bw_auto,
        "bw_user": bool(bw_override > 0.0),
        "d": d_mm,
        "asl": asl,
        "asl_bar_ids": asl_bar_ids,
        "asl_cg": cg,
        "ac": area,
        "fck": fck,
        "n_ed": inp["P_pl"],
        "n_prestress": n_prestress,
        "n_ed_comp": n_ed_comp,
        "m_ed_2023": m_ed_2023,
        "m_prestress": m_prestress,
        "centroid": (cx, cy),
        "method": inp["shear_method"],
        "model_2023": model_2023,
        "ddg": ddg,
        "fyd_flex": fyd_flex,
    }
    if not inp.get("shear_links") or model_2023:
        return payload, None

    cot_min = min(inp["shear_cot_min"], inp["shear_cot_max"])
    cot_max = max(inp["shear_cot_min"], inp["shear_cot_max"])
    asw = link_legs * templates.bar_area(inp["shear_link_dia"])
    asw_over_s = asw / inp["shear_link_s"] if inp["shear_link_s"] > 0.0 else 0.0
    z_mm, z_source = shear_lever_arm(inp, axis, tension_low, d_mm)

    def links_at(
        cot_lo,
        cot_hi,
        _fck=fck,
        _code=code,
        _bw=bw_mm,
        _d=d_mm,
        _asw_over_s=asw_over_s,
        _area=area,
        _z=z_mm,
    ):
        return shear.vrd_links(
            _fck, _code, _bw, _d, _asw_over_s, inp["shear_fywk"],
            n_ed_comp, _area, cot_lo, cot_hi, z_mm=_z,
            fcd_mpa=inp["concrete"].fcd,
            gamma_s=inp["steel"].gamma_y,
        )

    context = {
        "build": links_at,
        "cot_min": cot_min,
        "cot_max": cot_max,
        "asw": asw,
        "asw_over_s": asw_over_s,
        "z_mm": z_mm,
        "z_src": z_source,
        "code": code,
        "v_ed": v_ed,
        "vrd_c": result["vrd_c"],
        "axis": axis,
        "tension_low": tension_low,
        "component": component,
        "link_legs": link_legs,
    }
    return payload, context


def build_directional_shear_contexts(inp, n_prestress, n_ed_comp):
    """Return every required face candidate for active Vx,Ed and Vy,Ed checks.

    The result maps ``vx``/``vy`` to a candidate list. No interaction between the
    two components is introduced here or elsewhere; each candidate remains a
    normal uniaxial shear calculation in its physical plane.
    """
    if not inp.get("shear_on"):
        return {}
    definitions = shear_direction_specs(inp)
    contexts = {}
    for component, definition in definitions.items():
        if definition["v_ed"] <= 0.0:
            continue
        faces = shear_face_candidates(definition["face"], definition["moment"])
        candidates = [
            _build_shear_face_context(
                inp,
                n_prestress,
                n_ed_comp,
                component=component,
                axis=definition["axis"],
                tension_low=tension_low,
                v_ed=definition["v_ed"],
                bw_override=definition["bw"],
                link_legs=definition["legs"],
                face_mode=str(definition["face"]),
            )
            for tension_low in faces
        ]
        contexts[component] = {
            "component": component,
            "axis": definition["axis"],
            "associated_moment": definition["moment"],
            "face_mode": str(definition["face"]),
            "both_faces_evaluated": len(candidates) == 2,
            "candidates": candidates,
        }
    return contexts


def build_shear_context(inp, n_prestress, n_ed_comp):
    """Backward-compatible one-direction context builder.

    The application reuses :func:`shear_direction_specs` while passing each face
    through the complete verified uniaxial pipeline. This wrapper preserves the
    v6 headless API for callers and migration-equivalence tests.
    """
    if not inp.get("shear_on"):
        return None, None
    axis = inp["shear_axis"]
    return _build_shear_face_context(
        inp,
        n_prestress,
        n_ed_comp,
        component="vy" if axis == "x" else "vx",
        axis=axis,
        tension_low=bool(inp["shear_tension"]),
        v_ed=float(inp["shear_V"]),
        bw_override=float(inp["shear_bw"]),
        link_legs=float(inp["shear_link_legs"]),
        face_mode="legacy",
    )


def build_torsion_context(inp, n_ed_comp):
    """Return the angle-independent context for the active torsion check."""
    if not inp.get("torsion_on") or inp["section"] is None:
        return None
    tcode = SHEAR_CODES.get(inp["torsion_method"], codes.EC2_2005_DKNA)
    fck = inp["concrete"].fck
    fcd = inp["concrete"].fcd
    area, _cx, _cy = gross_area_centroid(inp["outer"], inp["holes"])
    sigma_cp = n_ed_comp / area / 1000.0 if area > 0.0 else 0.0
    alpha_cw = tcode.shear_alpha_cw(sigma_cp, fcd)
    tube = torsion.tube_properties(
        inp["outer"], inp["holes"], tef_override=inp["torsion_tef"]
    )
    gamma_s = inp["steel"].gamma_y
    fywd = inp["shear_fywk"] / gamma_s
    fyd_long = design_yield(inp["steel"])
    asw = templates.bar_area(inp["shear_link_dia"])
    asw_over_s = asw / inp["shear_link_s"] if inp["shear_link_s"] > 0.0 else 0.0
    cot_min = min(inp["torsion_cot_min"], inp["torsion_cot_max"])
    cot_max = max(inp["torsion_cot_min"], inp["torsion_cot_max"])
    nu_detail = inp["torsion_nu_v"]
    nu_detail_applied = bool(
        nu_detail
        and tcode.torsion_nu(fck, closed_detailing=True)
        != tcode.torsion_nu(fck, closed_detailing=False)
    )
    gamma_c = inp["concrete"].gamma_c
    fctd = 0.7 * codes.fctm(fck) / gamma_c
    t_ed = inp["torsion_T"]
    tube_kwargs = {
        "tcode": tcode,
        "fck": fck,
        "fcd": fcd,
        "alpha_cw": alpha_cw,
        "fywd": fywd,
        "asw_over_s": asw_over_s,
        "cot_min": cot_min,
        "cot_max": cot_max,
        "nu_detail": nu_detail,
        "fctd": fctd,
        "fyd_long": fyd_long,
    }

    subrects = inp.get("torsion_subrects") or []
    subdivision_requested = bool(inp.get("torsion_subdivide"))
    subdivision_valid = False
    subdivision_reason = ""
    if subdivision_requested:
        rectangles_m = [
            (x_mm / 1000.0, y_mm / 1000.0,
             b_mm / 1000.0, h_mm / 1000.0)
            for x_mm, y_mm, b_mm, h_mm in subrects
        ]
        subdivision_valid, subdivision_reason = (
            geometry.rectangles_partition_concrete(
                inp["outer"], inp.get("holes") or [], rectangles_m
            )
        )
    subdivide = subdivision_requested and subdivision_valid
    compound_detected = not geometry.polygon_is_convex(inp["outer"])
    if subdivision_requested and not subdivision_valid:
        tube = dict(
            tube,
            valid=False,
            reason=f"invalid sub-tube partition: {subdivision_reason}",
        )
    elif compound_detected and not subdivide:
        tube = dict(
            tube, valid=False, reason="compound outline requires subdivision"
        )

    if subdivide:
        subtubes, stiffnesses, dimensions = [], [], []
        for x_mm, y_mm, b_mm, h_mm in subrects:
            b_m, h_m = b_mm / 1000.0, h_mm / 1000.0
            subtubes.append(
                torsion.tube_properties(torsion.rectangle_ring(b_m, h_m), None)
            )
            stiffnesses.append(torsion.rectangle_torsion_constant(b_m, h_m))
            dimensions.append((x_mm, y_mm, b_mm, h_mm))
        torque_parts = torsion.distribute_by_stiffness(t_ed, stiffnesses)
    else:
        subtubes = [tube]
        stiffnesses = [1.0]
        dimensions = [None]
        torque_parts = [t_ed]

    return {
        "_tk": tube_kwargs,
        "tube": tube,
        "subdivide": subdivide,
        "subtubes": subtubes,
        "consts": stiffnesses,
        "ted_parts": torque_parts,
        "sub_dims": dimensions,
        "t_ed": t_ed,
        "tcode": tcode,
        "fck": fck,
        "fcd": fcd,
        "alpha_cw": alpha_cw,
        "fywd_t": fywd,
        "fyd_long": fyd_long,
        "asw_t": asw,
        "asw_over_s_t": asw_over_s,
        "tcot_min": cot_min,
        "tcot_max": cot_max,
        "nu_detail": nu_detail,
        "nu_detail_applied": nu_detail_applied,
        "fctd": fctd,
        "sigma_cp": sigma_cp,
        "gamma_c": gamma_c,
        "gamma_s": gamma_s,
        "compound_detected": compound_detected,
        "subdivision_requested": subdivision_requested,
        "subdivision_valid": subdivision_valid,
        "subdivision_reason": subdivision_reason,
    }


def finalize_combined(inp, out):
    """Build the final combined M-V-T payload from completed component checks."""
    if not inp.get("combined_on"):
        return
    plastic = out.get("plastic")
    shear_out = out.get("shear")
    torsion_out = out.get("torsion")
    r_m = plastic.get("util") if plastic else None
    have_m = r_m is not None
    have_v = shear_out is not None and shear_out["res"]["valid"]
    have_t = torsion_out is not None and torsion_out["valid"]
    if not (have_m and have_v and have_t):
        out["combined"] = {
            "valid": False,
            "have_m": have_m,
            "have_v": have_v,
            "have_t": have_t,
            "method": inp["combined_method"],
        }
        return

    links = shear_out.get("links")
    r_v = links["util"] if links is not None else shear_out["util"]
    r_t = torsion_out["util"]
    independent_mv = bool(inp["combined_mv_independent"])
    dk_sum = combined.dkna_sum(
        r_m, r_v, r_t, m_v_independent=independent_mv
    )
    code_applicable = bool(
        torsion_out.get("code_applicable", True)
        and (links is None or links.get("code_applicable", True))
    )
    payload = {
        "valid": True,
        "method": inp["combined_method"],
        "r_m": r_m,
        "r_v": r_v,
        "r_t": r_t,
        "m_v_independent": independent_mv,
        "dkna_sum": dk_sum,
        "dkna_ok": dk_sum <= 1.0 + 1e-9,
        "code_applicable": code_applicable,
        "crushing": torsion_out.get("interaction"),
        "asl_torsion": torsion_out["asl_req"],
        "delta_ftd": links["delta_ftd"] if links is not None else 0.0,
        "links": links is not None,
    }
    longitudinal = links.get("chord") if links is not None else None
    if longitudinal is not None:
        payload["longitudinal"] = longitudinal
    chord_off = links.get("chord_off") if links is not None else None
    if chord_off is not None:
        payload["chord_off"] = chord_off

    if (
        links is not None
        and links["res"]["valid"]
        and torsion_out["asw_over_s"] > 0.0
    ):
        interaction = torsion_out.get("interaction")
        if interaction is not None and not interaction.get("valid"):
            payload["transverse"] = {
                "valid": False,
                "reason": "no common strut angle",
                "cot_shear": interaction.get("cot_shear"),
                "cot_torsion": interaction.get("cot_torsion"),
            }
        else:
            v_ed = shear_out["v_ed"]
            t_ed_web = torsion_out["primary"]["t_ed"]
            vrd_c = shear_out["res"]["vrd_c"]
            cot = (
                interaction["cot"]
                if interaction is not None
                else links["res"]["cot"]
            )
            shear_credited = v_ed <= vrd_c
            shear_fraction = (
                0.0
                if shear_credited
                else combined.ratio(v_ed, links["res"]["vrd_s"])
            )
            torsion_fraction = combined.ratio(
                t_ed_web, torsion_out["primary"]["trd_s"]
            )
            stirrup_util = shear_fraction + torsion_fraction
            crushing_util = (
                interaction["value"]
                if interaction is not None
                else combined.ratio(v_ed, links["res"]["vrd_max"])
            )
            governing = max(stirrup_util, crushing_util)
            payload["transverse"] = {
                "valid": True,
                "cot": cot,
                "theta_deg": math.degrees(math.atan(1.0 / cot)),
                "u_stirrup": stirrup_util,
                "u_crush": crushing_util,
                "governing": governing,
                "governs": (
                    "crushing" if crushing_util > stirrup_util else "stirrups"
                ),
                "ok": bool(governing <= 1.0 + 1e-9),
                "shear_fraction": shear_fraction,
                "torsion_fraction": torsion_fraction,
                "shear_credited": shear_credited,
                "vrd_c": vrd_c,
                "v_ed": v_ed,
            }
    out["combined"] = payload
