"""Shared result-presentation helpers for the Streamlit UI and PDF report.

The functions in this module derive display-only assessment state and QA tables
from an already-computed analysis payload. They do not alter or repeat the
engineering solvers.
"""

from __future__ import annotations

import math

import viz

_MM = 1000.0


def plastic_action_assessment(pl):
    """Return the semantic status for a plastic M-M applied-action result.

    A utilisation verdict is valid only for a converged, closed envelope with the
    applied-action check enabled. Capacity-only and partial-sweep results remain
    useful capacity evidence, but are explicitly not assessments.
    """
    checked = bool(pl.get("check_util", True))
    complete = bool(pl.get("closed", True))
    converged = bool(pl.get("converged", True))
    util = pl.get("util")

    if not converged:
        status = "INVALID"
        detail = ("One or more neutral-axis sweep points did not converge; "
                  "the displayed values are diagnostic only")
    elif not checked:
        status = "NOT ASSESSED"
        detail = ("Capacity-only run; enable the applied-moment utilisation "
                  "check to issue a verdict")
    elif not complete or util is None:
        status = "NOT ASSESSED"
        detail = ("The neutral-axis sweep is an open arc; a closed 360 degree "
                  "envelope is required for an applied-action verdict")
    elif not math.isfinite(util):
        status = "FAIL"
        detail = "The applied action has no finite capacity intersection"
    elif viz.util_ok(util):
        status = "PASS"
        detail = "Applied-action utilisation does not exceed the 100 % limit"
    else:
        status = "FAIL"
        detail = "Applied-action utilisation exceeds the 100 % limit"

    assessed = status in {"PASS", "FAIL"}
    margin = (1.0 - util
              if assessed and util is not None and math.isfinite(util)
              else None)
    gov_i = pl.get("util_gov")
    points = pl.get("points") or []
    gov_angle = (
        points[gov_i].get("V")
        if isinstance(gov_i, int) and 0 <= gov_i < len(points)
        else None
    )
    return {
        "status": status,
        "detail": detail,
        "util": util if assessed else None,
        "margin": margin,
        "governing_angle": gov_angle,
        "assessed": assessed,
    }


def plastic_state_evidence(inp, point):
    """Build concrete-corner and reinforcement evidence at one plastic state.

    Strain and stress are tension-positive. Reinforcement force is derived only
    for presentation from the solver-consistent material law:
    ``F [kN] = sigma [MPa] * A [mm2] / 1000``.
    """
    hp = viz.plastic_halfplane(
        point["V"], point["na_x"], point["na_y"],
    )
    a, b, c = hp
    kappa = float(point["kappa"])

    concrete_rows = []
    point_no = 0
    rings = [("Outer", inp.get("outer") or [])]
    rings.extend(
        (f"Hole {index}", ring)
        for index, ring in enumerate(inp.get("holes") or [], start=1)
    )
    concrete = inp.get("concrete")
    for ring_name, ring in rings:
        for ring_point_no, vertex in enumerate(ring, start=1):
            point_no += 1
            x, y = float(vertex[0]), float(vertex[1])
            strain = -kappa * (a * x + b * y + c)
            stress = concrete.stress(strain, design=True) if concrete is not None else 0.0
            concrete_rows.append({
                "point_no": point_no,
                "ring": ring_name,
                "ring_point_no": ring_point_no,
                "x_mm": x * _MM,
                "y_mm": y * _MM,
                "strain_permille": strain * _MM,
                "stress_mpa": stress,
            })

    element_rows = []

    def append_elements(points, element_type, material, prestrain=0.0):
        if material is None:
            return
        for element_no, element in enumerate(points or [], start=1):
            x, y = float(element[0]), float(element[1])
            area = float(element[2]) if len(element) > 2 else 0.0
            strain = prestrain - kappa * (a * x + b * y + c)
            stress = material.stress(strain, design=True)
            state = ("Tension" if strain > 1e-12 else
                     "Compression" if strain < -1e-12 else "Neutral")
            element_rows.append({
                "element_type": element_type,
                "element_no": element_no,
                "element_id": f"{element_type.lower()} {element_no}",
                "state": state,
                "x_mm": x * _MM,
                "y_mm": y * _MM,
                "area_mm2": area,
                "strain_permille": strain * _MM,
                "stress_mpa": stress,
                "force_kn": stress * area / _MM,
            })

    append_elements(inp.get("bars"), "Bar", inp.get("steel"))
    prestress = inp.get("prestress")
    append_elements(
        inp.get("tendons"),
        "Tendon",
        prestress,
        float(getattr(prestress, "IS", 0.0)) if prestress is not None else 0.0,
    )
    return {
        "halfplane": hp,
        "concrete": concrete_rows,
        "elements": element_rows,
    }


def nm_boundary_rows(interaction):
    """Return a point-by-point table for both numerical N-M boundaries."""
    x_data = (interaction or {}).get("x") or {}
    y_data = (interaction or {}).get("y") or {}
    x_n, x_m = list(x_data.get("N") or []), list(x_data.get("M") or [])
    y_n, y_m = list(y_data.get("N") or []), list(y_data.get("M") or [])
    count = max(len(x_n), len(x_m), len(y_n), len(y_m))

    def at(values, index):
        return values[index] if index < len(values) else None

    return [
        {
            "Point": index + 1,
            "N, Mx boundary (kN)": at(x_n, index),
            "Mx (kNm)": at(x_m, index),
            "N, My boundary (kN)": at(y_n, index),
            "My (kNm)": at(y_m, index),
        }
        for index in range(count)
    ]


def action_set(inp, family):
    """Return one normalised action-set record from a current input payload."""
    key = "elastic_case" if family == "elastic" else "plastic_case"
    record = (inp or {}).get(key) or {}
    return {
        "id": str(record.get("id") or "").strip(),
        "type": str(record.get("type") or "").strip(),
        "source": str(record.get("source") or "").strip(),
    }


def action_set_text(inp, family, *, include_source=True):
    record = action_set(inp, family)
    text = record["id"] or "ID NOT SET"
    if record["type"]:
        text += f" | {record['type']}"
    if include_source and record["source"]:
        text += f" | Source: {record['source']}"
    return text


def required_action_set_errors(inp):
    """Return missing required Plastic/Elastic action-set identifiers."""
    mode = str((inp or {}).get("mode") or "")
    plastic_active = (
        mode in {"Plastic", "Both"}
        or bool((inp or {}).get("shear_on"))
        or bool((inp or {}).get("torsion_on"))
        or bool((inp or {}).get("combined_on"))
    )
    elastic_active = mode in {"Elastic", "Both"}
    errors = []
    if plastic_active and not action_set(inp, "plastic")["id"]:
        errors.append("Plastic action-set ID is required")
    if elastic_active and not action_set(inp, "elastic")["id"]:
        errors.append("Elastic action-set ID is required")
    return errors


def _summary_row(check, family, status, result="-", criterion="-", util=None,
                 view="-", note="", inp=None):
    case = action_set(inp, family)
    return {
        "check": check,
        "family": family,
        "case": case["id"] or "-",
        "case_type": case["type"] or "-",
        "source": case["source"] or "-",
        "status": status,
        "result": result,
        "criterion": criterion,
        "util": util,
        "view": view,
        "note": note,
    }


def _util_summary_status(util, *, valid=True, applicable=True):
    if not valid:
        return "INVALID"
    if not applicable or util is None:
        return "NOT ASSESSED"
    if not math.isfinite(util):
        return "FAIL"
    return "PASS" if viz.util_ok(util) else "FAIL"


def _map_assessment_status(status):
    return {
        "OK": "PASS",
        "EXCEEDED": "FAIL",
        "PASS": "PASS",
        "FAIL": "FAIL",
        "INVALID": "INVALID",
        "NOT ASSESSED": "NOT ASSESSED",
        "NOT APPLICABLE": "NOT APPLICABLE",
    }.get(str(status or "").upper(), "NOT ASSESSED")


def _percent(util):
    if util is None:
        return "-"
    return "infinite" if not math.isfinite(util) else f"{util * 100:.1f} %"


def result_summary_rows(inp, results, *, stale=False):
    """Build the shared UI/PDF overview without rerunning any solver."""
    inp = inp or {}
    results = results or {}
    rows = []
    mode = str(inp.get("mode") or "")
    plastic_requested = mode in {"Plastic", "Both"}
    elastic_requested = mode in {"Elastic", "Both"}

    pl = results.get("plastic")
    if pl is not None:
        assessment = plastic_action_assessment(pl)
        rows.append(_summary_row(
            "Plastic bending",
            "plastic",
            assessment["status"],
            _percent(assessment["util"]),
            "<= 100 %",
            assessment["util"],
            "Plastic Results",
            assessment["detail"],
            inp,
        ))
    elif plastic_requested:
        rows.append(_summary_row(
            "Plastic bending", "plastic", "NOT RUN",
            view="Plastic Results", note="Calculate required", inp=inp,
        ))

    elastic = results.get("elastic")
    if elastic is None and elastic_requested:
        rows.append(_summary_row(
            "Elastic stresses", "elastic", "NOT RUN",
            view="Elastic Results", note="Calculate required", inp=inp,
        ))
        if inp.get("sls_cw"):
            rows.append(_summary_row(
                "Crack width", "elastic", "NOT RUN",
                view="Elastic Results", note="Calculate required", inp=inp,
            ))
    elif elastic is not None:
        converged = bool(elastic.get("converged", True))
        assessments = elastic.get("stress_assessments") or {}
        names = [
            ("Concrete stress", "concrete"),
            ("Reinforcement stress", "reinforcement"),
        ]
        if inp.get("tendons"):
            names.append(("Tendon stress", "prestress"))
        if not assessments:
            rows.append(_summary_row(
                "Elastic stresses",
                "elastic",
                "INVALID" if not converged else "NOT ASSESSED",
                view="Elastic Results",
                note=("Solver did not converge" if not converged
                      else "No stress criteria supplied"),
                inp=inp,
            ))
        else:
            for label, key in names:
                assessment = assessments.get(key) or {}
                status = (
                    "INVALID" if not converged
                    else _map_assessment_status(assessment.get("status"))
                )
                value, limit = assessment.get("value"), assessment.get("limit")
                result = "-" if value is None else f"{value:.3f} MPa"
                criterion = (
                    "not supplied"
                    if limit is None or limit <= 0.0
                    else f"<= {limit:.3f} MPa"
                )
                rows.append(_summary_row(
                    label, "elastic", status, result, criterion,
                    assessment.get("util"), "Elastic Results",
                    assessment.get("criterion") or "", inp,
                ))
        if elastic.get("show_cw") or inp.get("sls_cw"):
            assessment = elastic.get("crack_assessment") or {}
            status = (
                "INVALID" if not converged
                else _map_assessment_status(assessment.get("status"))
            )
            value, limit = assessment.get("value"), assessment.get("limit")
            result = "-" if value is None else f"{value:.3f} mm"
            criterion = (
                "not supplied"
                if limit is None or limit <= 0.0
                else f"<= {limit:.3f} mm"
            )
            rows.append(_summary_row(
                "Crack width", "elastic", status, result, criterion,
                assessment.get("util"), "Elastic Results",
                assessment.get("governing") or "", inp,
            ))

    shear = results.get("shear")
    if shear is None and inp.get("shear_on"):
        rows.append(_summary_row(
            "Shear", "plastic", "NOT RUN",
            view="Shear", note="Calculate required", inp=inp,
        ))
    elif shear is not None:
        resistance = (shear.get("res") or {}).get("vrd_c")
        result = (
            f"{_percent(shear.get('util'))} (VEd / VRd,c)"
            if resistance is not None else "-"
        )
        rows.append(_summary_row(
            "Shear without links",
            "plastic",
            _util_summary_status(
                shear.get("util"),
                valid=bool((shear.get("res") or {}).get("valid")),
            ),
            result,
            "<= 100 %",
            shear.get("util"),
            "Shear",
            str(shear.get("method") or ""),
            inp,
        ))
        if inp.get("shear_links"):
            links = shear.get("links")
            if links is None:
                rows.append(_summary_row(
                    "Shear with links", "plastic", "NOT ASSESSED",
                    view="Shear", note="Selected method does not evaluate links",
                    inp=inp,
                ))
            else:
                rows.append(_summary_row(
                    "Shear with links",
                    "plastic",
                    _util_summary_status(
                        links.get("util"),
                        valid=bool((links.get("res") or {}).get("valid")),
                        applicable=bool(links.get("code_applicable", True)),
                    ),
                    _percent(links.get("util")),
                    "<= 100 %",
                    links.get("util"),
                    "Shear",
                    str((links.get("res") or {}).get("governs") or ""),
                    inp,
                ))

    torsion = results.get("torsion")
    if torsion is None and inp.get("torsion_on"):
        rows.append(_summary_row(
            "Torsion", "plastic", "NOT RUN",
            view="Torsion", note="Calculate required", inp=inp,
        ))
    elif torsion is not None:
        rows.append(_summary_row(
            "Torsion",
            "plastic",
            _util_summary_status(
                torsion.get("util"),
                valid=bool(torsion.get("valid")),
                applicable=bool(torsion.get("code_applicable", True)),
            ),
            _percent(torsion.get("util")),
            "<= 100 %",
            torsion.get("util"),
            "Torsion",
            str(torsion.get("governs") or torsion.get("reason") or ""),
            inp,
        ))

    combined = results.get("combined")
    if combined is None and inp.get("combined_on"):
        rows.append(_summary_row(
            "Combined M-V-T", "plastic", "NOT RUN",
            view="M-V-T Combined", note="Calculate required", inp=inp,
        ))
    elif combined is not None:
        valid = bool(combined.get("valid"))
        applicable = bool(combined.get("code_applicable", True))
        util = combined.get("dkna_sum")
        if valid:
            combined_note = str(combined.get("method") or "")
        else:
            missing = [
                label
                for key, label in (
                    ("have_m", "M"),
                    ("have_v", "V"),
                    ("have_t", "T"),
                )
                if not combined.get(key)
            ]
            combined_note = "Missing prerequisite: " + ", ".join(missing)
        rows.append(_summary_row(
            "Combined M-V-T - DK NA sum",
            "plastic",
            _util_summary_status(
                util,
                valid=valid,
                applicable=applicable,
            ),
            _percent(util),
            "<= 100 %",
            util,
            "M-V-T Combined",
            combined_note,
            inp,
        ))
        if valid:
            crushing = combined.get("crushing")
            if crushing is None:
                rows.append(_summary_row(
                    "Combined V-T crushing", "plastic", "NOT ASSESSED",
                    view="M-V-T Combined",
                    note="Shear links are required for this check", inp=inp,
                ))
            else:
                crushing_valid = bool(crushing.get("valid"))
                crushing_applicable = bool(
                    crushing.get("code_applicable", applicable)
                )
                crushing_util = crushing.get("value")
                rows.append(_summary_row(
                    "Combined V-T crushing",
                    "plastic",
                    _util_summary_status(
                        crushing_util,
                        valid=crushing_valid,
                        applicable=crushing_applicable,
                    ),
                    _percent(crushing_util),
                    "<= 100 %",
                    crushing_util,
                    "M-V-T Combined",
                    (
                        "No common strut angle"
                        if not crushing_valid
                        else f"cot(theta) = {crushing.get('cot', 0.0):.2f}"
                    ),
                    inp,
                ))

            transverse = combined.get("transverse")
            if transverse is None:
                rows.append(_summary_row(
                    "Combined transverse reinforcement",
                    "plastic",
                    "NOT ASSESSED",
                    view="M-V-T Combined",
                    note="Shear links are required for this check",
                    inp=inp,
                ))
            else:
                transverse_valid = bool(transverse.get("valid"))
                transverse_util = transverse.get("governing")
                rows.append(_summary_row(
                    "Combined transverse reinforcement",
                    "plastic",
                    _util_summary_status(
                        transverse_util,
                        valid=transverse_valid,
                        applicable=applicable,
                    ),
                    _percent(transverse_util),
                    "<= 100 %",
                    transverse_util,
                    "M-V-T Combined",
                    (
                        str(transverse.get("governs") or "")
                        if transverse_valid else "No common strut angle"
                    ),
                    inp,
                ))

            longitudinal = combined.get("longitudinal")
            if longitudinal is None:
                rows.append(_summary_row(
                    "Combined longitudinal reinforcement",
                    "plastic",
                    "NOT ASSESSED",
                    view="M-V-T Combined",
                    note="Shear links are required for this check",
                    inp=inp,
                ))
            else:
                longitudinal_valid = bool(longitudinal.get("valid"))
                longitudinal_util = longitudinal.get("util")
                conditional = (
                    not longitudinal.get("biaxial", False)
                    or bool(longitudinal.get("conditional", True))
                )
                rows.append(_summary_row(
                    "Combined longitudinal reinforcement",
                    "plastic",
                    _util_summary_status(
                        longitudinal_util,
                        valid=longitudinal_valid,
                        applicable=applicable and conditional,
                    ),
                    _percent(longitudinal_util),
                    "<= 100 %",
                    longitudinal_util,
                    "M-V-T Combined",
                    (
                        "Pure-axis fallback; no code verdict"
                        if longitudinal_valid and not conditional
                        else str(longitudinal.get("axis") or "")
                    ),
                    inp,
                ))

            chord_off = combined.get("chord_off")
            if chord_off is not None:
                chord_valid = bool(chord_off.get("valid"))
                chord_util = chord_off.get("util")
                rows.append(_summary_row(
                    "Combined off-axis chord",
                    "plastic",
                    _util_summary_status(
                        chord_util,
                        valid=chord_valid,
                        applicable=applicable,
                    ),
                    _percent(chord_util),
                    "<= 100 %",
                    chord_util,
                    "M-V-T Combined",
                    str(chord_off.get("axis") or ""),
                    inp,
                ))

    if stale and results:
        for row in rows:
            if row["status"] not in {"NOT RUN", "NOT APPLICABLE"}:
                previous = row["status"]
                row["status"] = "STALE"
                row["note"] = f"Last status: {previous}; inputs changed"
    return rows


def overall_summary_status(rows):
    """Return the most conservative state represented in a summary table."""
    states = {row.get("status") for row in rows}
    for status in (
        "INVALID", "FAIL", "STALE", "NOT ASSESSED", "NOT RUN", "PASS",
        "NOT APPLICABLE",
    ):
        if status in states:
            return status
    return "NOT RUN"
