"""Shared result-presentation helpers for the Streamlit UI and PDF report.

The functions in this module derive display-only assessment state and QA tables
from an already-computed analysis payload. They do not alter or repeat the
engineering solvers.
"""

from __future__ import annotations

from collections.abc import Mapping
import math

import case_analysis
import fatigue_presentation
import viz

from app import modelled_direction
from sector.design_standards import get_design_basis

_DEGREE = chr(0x00B0)
_THETA = chr(0x03B8)
_RHO = chr(0x03C1)

_SINGLE_CASE_ID = "__single__"


def _publication_metric(value, *, allow_positive_infinity=False):
    """Return one eligible retained publication-ranking metric."""
    if value is None:
        return None
    try:
        metric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isfinite(metric):
        return metric
    if allow_positive_infinity and metric == math.inf:
        return metric
    return None


def _publication_cases(out, family):
    """Return ordered named-case result payloads for one analysis family."""
    entries = (out or {}).get(f"{family}_cases")
    if entries is None:
        return [(_SINGLE_CASE_ID, out or {})]
    cases = []
    for entry in entries:
        name = str(entry.get("name") or (entry.get("actions") or {}).get("name") or "")
        if name:
            cases.append((name, entry.get("results") or {}))
    return cases


def _transverse_metric(family, result):
    """Rank an already-computed shear, torsion or combined result."""
    def shear_metric(item):
        links = item.get("links") or {}
        if links:
            if not (links.get("res") or {}).get("valid"):
                return None
            return _publication_metric(
                links.get("util"), allow_positive_infinity=True
            )
        if not (item.get("res") or {}).get("valid"):
            return None
        return _publication_metric(item.get("util"), allow_positive_infinity=True)

    def combined_metric(item):
        if not item.get("valid"):
            return None
        return _publication_metric(
            item.get("dkna_sum"), allow_positive_infinity=True
        )

    directions = result.get("directions") or {}
    if family in {"shear", "combined"}:
        items = [directions[key] for key in ("vx", "vy") if key in directions]
        if not items:
            items = [result]
        extractor = shear_metric if family == "shear" else combined_metric
        values = [metric for item in items if (metric := extractor(item)) is not None]
    else:
        metric = (
            _publication_metric(result.get("util"), allow_positive_infinity=True)
            if result.get("valid") else None
        )
        values = [] if metric is None else [metric]
    return max(values) if values else None


def _transverse_direction(family, result):
    """Return the retained governing direction, with first-direction tie-break."""
    best = None
    for order, component in enumerate(("vx", "vy")):
        item = (result.get("directions") or {}).get(component)
        if not item:
            continue
        metric = _transverse_metric(family, item)
        if metric is None:
            continue
        score = (metric, -order)
        if best is None or score > best[0]:
            best = (score, component)
    return None if best is None else best[1]


def _worked_family_selection(out, family):
    """Select one named case and any required direction for a worked family."""
    context_family = "plastic" if family in {"shear", "torsion", "combined"} else family
    best = None
    for order, (case_id, case_out) in enumerate(_publication_cases(out, context_family)):
        result = case_out.get(family)
        if not result:
            continue
        direction = None
        if family == "plastic":
            if not result.get("converged"):
                continue
            utilisation = _publication_metric(
                result.get("util"), allow_positive_infinity=True
            )
            if utilisation is not None:
                score = (2, utilisation, -order)
            else:
                values = [
                    metric
                    for name in ("max_mx", "min_mx", "max_my", "min_my")
                    if (metric := _publication_metric(result.get(name))) is not None
                ]
                if not values:
                    continue
                score = (1, max(abs(value) for value in values), -order)
        elif family in {"shear", "torsion", "combined"}:
            metric = _transverse_metric(family, result)
            if metric is None:
                continue
            score = (2, metric, -order)
            if family in {"shear", "combined"} and result.get("directions"):
                direction = _transverse_direction(family, result)
                if direction is None:
                    continue
        else:
            if not result.get("converged"):
                continue
            values = [
                metric
                for name in ("max_conc", "max_steel")
                if (metric := _publication_metric(result.get(name))) is not None
            ]
            if not values:
                continue
            score = (1, max(abs(value) for value in values), -order)
        if best is None or score > best[0]:
            best = (score, {"case_id": case_id, "component": direction})
    return None if best is None else best[1]


def _worked_check_selection(out, key):
    """Select one named detailing case from retained check utilisations."""
    best = None
    for order, (case_id, case_out) in enumerate(_publication_cases(out, "plastic")):
        result = case_out.get(key)
        if not result:
            continue
        values = [
            metric
            for check in result.get("checks") or ()
            if check.get("status") in {"PASS", "FAIL"}
            and (metric := _publication_metric(
                check.get("utilisation"), allow_positive_infinity=True
            )) is not None
        ]
        stored = _publication_metric(
            result.get("governing_utilisation"), allow_positive_infinity=True
        )
        if result.get("status") in {"PASS", "FAIL"} and stored is not None:
            values.append(stored)
        if not values:
            continue
        score = (max(values), -order)
        if best is None or score > best[0]:
            best = (score, {"case_id": case_id})
    return None if best is None else best[1]


def _worked_crack_selection(out):
    """Select the global ordinary or fine/coarse crack-width branches."""
    cases = _publication_cases(out, "elastic")
    has_coarse = any(
        (case_out.get("elastic") or {}).get(key) is not None
        for _, case_out in cases
        for key in ("crack_coarse", "crack_short_coarse")
    )
    systems = (
        (
            ("fine", (("crack", "long-term (fine)"),
                      ("crack_short", "short-term (fine)"))),
            ("coarse", (("crack_coarse", "long-term (coarse)"),
                        ("crack_short_coarse", "short-term (coarse)"))),
        )
        if has_coarse else
        (("governing", (("crack", "long-term"),
                        ("crack_short", "short-term"))),)
    )
    selected = []
    for system, branches in systems:
        best = None
        for case_order, (case_id, case_out) in enumerate(cases):
            elastic = case_out.get("elastic") or {}
            if not elastic.get("converged"):
                continue
            for branch_order, (branch, label) in enumerate(branches):
                crack = elastic.get(branch)
                value = _publication_metric((crack or {}).get("wk"))
                if value is None or value < 0.0:
                    continue
                score = (value, -case_order, -branch_order)
                if best is None or score > best[0]:
                    best = (score, {
                        "case_id": case_id,
                        "system": system,
                        "branch": branch,
                        "label": label,
                    })
        if best is not None:
            selected.append(best[1])
    return selected


def _worked_crack_comparison_selection(out):
    """Select one user-limit example by largest retained crack width.

    The optional comparison must not change which physical crack result is
    critical.  In particular, a smaller width paired with a tighter user limit
    must not displace the largest calculated width.
    """
    best = None
    assessed_states = {
        "WITHIN USER-SPECIFIED LIMIT",
        "EXCEEDS USER-SPECIFIED LIMIT",
    }
    for order, (case_id, case_out) in enumerate(_publication_cases(out, "elastic")):
        elastic = case_out.get("elastic") or {}
        output = elastic.get("crack_output") or {}
        value = _publication_metric(output.get("value"))
        if output.get("calculation_state") not in assessed_states:
            continue
        if value is None or value < 0.0:
            continue
        score = (value, -order)
        if best is None or score > best[0]:
            best = (score, {"case_id": case_id})
    return None if best is None else best[1]


def _cracking_threshold_selection(out):
    best = None
    for order, (case_id, case_out) in enumerate(_publication_cases(out, "elastic")):
        elastic = case_out.get("elastic") or {}
        value = _publication_metric(elastic.get("lambda_cr"))
        if not elastic.get("converged") or value is None or value < 0.0:
            continue
        score = (-value, -order)
        if best is None or score > best[0]:
            best = (score, {"case_id": case_id})
    return None if best is None else best[1]


def _torsion_subcheck_selection(out):
    """Select each valid retained torsion subcheck, accepting governing +inf."""
    selected = {}
    for case_order, (case_id, case_out) in enumerate(_publication_cases(out, "plastic")):
        torsion = case_out.get("torsion") or {}
        directional = torsion.get("directional_interactions") or {}
        items = [(key, directional[key]) for key in ("vx", "vy") if key in directional]
        if not items:
            items = [(None, torsion)]
        for direction_order, (component, item) in enumerate(items):
            for key, payload_key, eligible in (
                ("interaction", "interaction", lambda value: value.get("valid")),
                ("minimum_reinforcement", "min_reinf",
                 lambda value: value.get("applicable")),
            ):
                payload = item.get(payload_key) or {}
                value = _publication_metric(
                    payload.get("value"), allow_positive_infinity=True
                )
                if not eligible(payload) or value is None:
                    continue
                score = (value, -case_order, -direction_order)
                if key not in selected or score > selected[key][0]:
                    selected[key] = (score, {
                        "case_id": case_id,
                        "component": component,
                    })
    return {key: item[1] for key, item in selected.items()}


def worked_example_selection(inp, out):
    """Build the bounded, family-specific worked-example publication contract.

    This is called once after analysis assembly. It selects identities only and
    never changes or recomputes an engineering result.
    """
    del inp  # reserved for future publication options; results own all rankings
    families = {
        family: _worked_family_selection(out, family)
        for family in ("plastic", "elastic", "shear", "torsion", "combined")
    }
    families.update({
        key: _worked_check_selection(out, key)
        for key in ("minimum_reinforcement", "transverse_reinforcement")
    })
    return {
        "schema": 1,
        "families": {key: value for key, value in families.items() if value is not None},
        "crack_examples": _worked_crack_selection(out),
        "crack_comparison": _worked_crack_comparison_selection(out),
        "cracking_threshold": _cracking_threshold_selection(out),
        "torsion_subchecks": _torsion_subcheck_selection(out),
        "heightened_crack_control": (
            {"result_key": "heightened_crack_control"}
            if isinstance((out or {}).get("heightened_crack_control"), Mapping)
            else None
        ),
    }


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
        detail = "Neutral-axis sweep did not converge; values are diagnostic only"
    elif not checked:
        status = "NOT ASSESSED"
        detail = "Capacity only; applied-moment check disabled"
    elif not complete or util is None:
        status = "NOT ASSESSED"
        detail = (
            f"Open arc; close the 360{_DEGREE} envelope to assess utilisation"
        )
    elif not math.isfinite(util):
        status = "FAIL"
        detail = "No finite capacity intersection"
    elif viz.util_ok(util):
        status = "PASS"
        detail = ""
    else:
        status = "FAIL"
        detail = ""

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


def plastic_assessment_text(assessment):
    """Return one compact, solver-neutral plastic-bending verdict."""
    parts = [f"{assessment.get('status', 'NOT ASSESSED')} - Plastic bending"]
    util = assessment.get("util")
    if assessment.get("assessed"):
        if util is not None and math.isfinite(util):
            parts.append(f"utilisation {util * 100:.1f} %")
        else:
            parts.append("utilisation not finite")
    if assessment.get("detail"):
        parts.append(str(assessment["detail"]))
    return " | ".join(parts)


def plastic_state_rows(point):
    """Return retained rows for one accepted plastic state.

    The calculation family has already evaluated every material response.  This
    helper only exposes those immutable rows and reconstructs the neutral-axis
    line used for drawing; it never calls a material law or repeats a solver.
    """

    return {
        "halfplane": viz.plastic_halfplane(
            point["V"], point["na_x"], point["na_y"],
        ),
        "concrete": list(point.get("concrete_corner_states") or ()),
        "elements": list(point.get("reinforcement_states") or ()),
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


def _ordinary_crack_summary_row(inp, output):
    """Format one retained ordinary crack output without deriving a verdict."""
    status = str(output.get("calculation_state") or "NOT ASSESSED")
    value = _publication_metric(output.get("value"))
    criterion = _publication_metric(output.get("criterion_mm"))
    ratio = _publication_metric(output.get("ratio"))
    result = "-" if value is None else f"{value:.3f} mm"
    if criterion is None:
        criterion_text = "User criterion not specified"
    else:
        criterion_text = f"User-specified limit {criterion:.3f} mm"
    note_parts = [
        str(output.get(key) or "").strip()
        for key in ("reason", "case", "governing", "criterion_source")
    ]
    if ratio is not None:
        note_parts.append(f"w_k / w_k,criterion = {ratio:.3f}")
    return _summary_row(
        "Crack width",
        "elastic",
        status,
        result,
        criterion_text,
        None,
        "Elastic Results",
        "; ".join(part for part in note_parts if part),
        inp,
    )


def _heightened_crack_summary_row(inp, result):
    """Format the singleton retained Formula 7.100 NA area comparison."""
    required = _publication_metric(result.get("required_reinforcement_area_mm2"))
    provided = _publication_metric(result.get("provided_reinforcement_area_mm2"))
    ratio = _publication_metric(result.get("comparison_ratio"))
    result_text = (
        f"As,req {required:.1f} mm2; As,prov {provided:.1f} mm2"
        if required is not None and provided is not None
        else "-"
    )
    note = str(result.get("disclosure") or result.get("source") or "")
    if ratio is not None:
        note = f"As,req / As,prov = {ratio:.3f}; {note}".rstrip("; ")
    return _summary_row(
        "DK heightened crack-control minimum",
        "elastic",
        str(result.get("status") or "NOT ASSESSED"),
        result_text,
        "User-declared Formula 7.100 NA applicability",
        None,
        "Elastic Results",
        note,
        inp,
    )


def _util_summary_status(util, *, valid=True):
    if not valid:
        return "INVALID"
    if util is None:
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
        "NOT CALCULATED": "NOT CALCULATED",
        "CALCULATED": "CALCULATED",
        "REVIEW": "REVIEW",
    }.get(str(status or "").upper(), "NOT ASSESSED")


def assessment_status_label(status):
    """Map solver-specific acceptance states to the UI/report vocabulary."""
    return _map_assessment_status(status)


def minimum_area_check(minimum, check):
    """Identify a 2005-family Formula (9.1N) result, including failed rows."""
    return bool(
        str((check or {}).get("type") or "").casefold() == "minimum area"
        or "9.1n" in str((minimum or {}).get("clause") or "").casefold()
    )


def interaction_assessment_status(interaction):
    """Acceptance state for a mathematically valid V+T interaction."""
    interaction = interaction or {}
    value = interaction.get("value")
    if not interaction.get("valid") or value is None:
        return "NOT ASSESSED"
    value = float(value)
    if not math.isfinite(value):
        return "FAIL"
    return "PASS" if value <= 1.0 + 1.0e-9 else "FAIL"


def _percent(util):
    if util is None:
        return "-"
    return "infinite" if not math.isfinite(util) else f"{util * 100:.1f} %"


def required_chord_candidates(payload):
    """Return every retained longitudinal chord needed for a code verdict."""
    payload = payload or {}
    preserved = payload.get("longitudinal_candidates")
    if preserved is None:
        preserved = payload.get("chord_candidates")
    if isinstance(preserved, (list, tuple)) and preserved:
        return [
            item for item in preserved
            if item is not None and item.get("valid")
        ]
    return [
        item for item in (
            payload.get("longitudinal") or payload.get("chord"),
            payload.get("chord_off"),
        )
        if item is not None and item.get("valid")
    ]


def required_chord_fallback(payload):
    """Return the retained required face using a pure-axis fallback, if any."""
    payload = payload or {}
    fallback = payload.get("longitudinal_fallback")
    return fallback if isinstance(fallback, dict) else None


def combined_physical_components(combined):
    """Return the three auditable physical M-V-T component assessments.

    The solver keeps a maximum across mechanisms for angle optimisation and the
    overall case status. Presentation must not call that maximum a transverse-
    reinforcement utilisation: concrete strut crushing, closed-stirrup demand and
    longitudinal-chord demand are different physical checks.
    """
    combined = combined or {}
    transverse = combined.get("transverse")
    if transverse is None:
        missing_note = "Shear links are required for the combined component checks"
        concrete = {
            "key": "concrete",
            "label": "Concrete compression strut",
            "status": "NOT ASSESSED",
            "util": None,
            "valid": False,
            "note": missing_note,
        }
        stirrup = {
            "key": "stirrup",
            "label": "Closed stirrup",
            "status": "NOT ASSESSED",
            "util": None,
            "valid": False,
            "note": missing_note,
        }
    else:
        transverse_valid = bool(transverse.get("valid"))
        concrete_util = transverse.get("u_crush")
        stirrup_util = transverse.get("u_stirrup")
        try:
            cot = float(transverse.get("cot"))
        except (TypeError, ValueError):
            cot = None
        concrete = {
            "key": "concrete",
            "label": "Concrete compression strut",
            "status": _util_summary_status(
                concrete_util,
                valid=transverse_valid,
            ),
            "util": concrete_util,
            "valid": transverse_valid,
            "note": (
                f"V-T crushing at cot {_THETA} = {cot:.2f}"
                if transverse_valid and cot is not None
                else "V-T crushing at the shared member angle"
                if transverse_valid
                else "Combined strut check is invalid"
            ),
        }
        stirrup = {
            "key": "stirrup",
            "label": "Closed stirrup",
            "status": _util_summary_status(
                stirrup_util,
                valid=transverse_valid,
            ),
            "util": stirrup_util,
            "valid": transverse_valid,
            "note": (
                f"Shear {_percent(transverse.get('shear_fraction'))} + "
                f"torsion {_percent(transverse.get('torsion_fraction'))}"
                if transverse_valid else "Combined stirrup check is invalid"
            ),
        }

    longitudinal = combined.get("longitudinal")
    chord_off = combined.get("chord_off")

    governing = combined.get("governing_longitudinal")
    if not isinstance(governing, dict) or not governing.get("valid"):
        governing = None
    coverage = (
        longitudinal.get("off_not_evaluated")
        if longitudinal is not None else None
    )
    conditional = bool(combined.get("longitudinal_all_conditional"))
    main_valid = bool(longitudinal is not None and longitudinal.get("valid"))
    long_valid = governing is not None and main_valid
    long_util = governing.get("util") if governing is not None else None
    if not main_valid:
        long_status = "NOT ASSESSED"
        long_note = "No valid shear-axis longitudinal chord check"
    elif not long_valid:
        long_status = "NOT ASSESSED"
        long_note = "No valid longitudinal chord check"
    elif coverage:
        long_status = "NOT ASSESSED"
        long_note = (
            "Incomplete chord coverage for a subdivided section"
            if coverage == "subdivided"
            else "One or more torsion-tensioned chord faces were not solved"
        )
    elif not conditional:
        long_status = "NOT ASSESSED"
        fallback = required_chord_fallback(combined) or {}
        face = "negative" if fallback.get("tension_low", True) else "positive"
        long_note = (
            f"Required {fallback.get('axis', '?')}-axis {face} face uses "
            "a pure-axis fallback; no demand-versus-resistance verdict"
        )
    else:
        long_status = _util_summary_status(
            long_util,
            valid=long_valid,
        )
        face = "negative" if governing.get("tension_low", True) else "positive"
        long_note = f"Governing {governing.get('axis', '?')}-axis {face} face"
    longitudinal_component = {
        "key": "longitudinal",
        "label": "Longitudinal reinforcement",
        "status": long_status,
        "util": long_util,
        "valid": long_valid,
        "note": long_note,
        "governing": governing,
        "coverage": coverage,
    }
    return [concrete, stirrup, longitudinal_component]


def _registered_fatigue_basis_label(value):
    try:
        return get_design_basis(value).label
    except ValueError:
        return None


def fatigue_summary_rows(inp, results, *, stale=False):
    """Return one conservative aggregate row for an enabled fatigue analysis."""

    inp = inp or {}
    results = results or {}
    if not bool(inp.get("fatigue_on")):
        return []
    fatigue = results.get("fatigue")
    basis = inp.get("fatigue_basis") or {}
    edition = _registered_fatigue_basis_label(
        inp.get("fatigue_edition")
    ) or "-"
    case = "-"
    status = "NOT RUN"
    result_text = "-"
    util = None
    note = "Calculate to assess the grouped spectra"
    if fatigue is not None:
        # The result payload owns the basis that was actually calculated. This
        # remains true when the live inputs have since changed and the row is stale.
        basis = fatigue.get("basis") or basis
        edition = str(
            fatigue.get("basis_label")
            or fatigue.get("edition")
            or _registered_fatigue_basis_label(fatigue.get("basis_key"))
            or edition
        )
        case = str(fatigue.get("governing_spectrum") or "-")
        try:
            util = float(fatigue.get("utilisation"))
        except (TypeError, ValueError):
            util = None
        result_text = _percent(util)
        status = fatigue_presentation.overall_status(
            fatigue, stale=stale
        )
        note = fatigue_presentation.overall_note(fatigue, stale=stale)
    return [{
        "check": "Fatigue",
        "family": "fatigue",
        "case": case,
        "case_type": edition,
        "source": str(
            basis.get("spectrum_source") or basis.get("method") or "-"
        ),
        "status": status,
        "result": result_text,
        "criterion": "<= 100 %",
        "util": util,
        "view": "Fatigue Results",
        "note": note,
    }]


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
        outputs = elastic.get("stress_outputs") or {}
        names = [
            ("Concrete stress", "concrete"),
            ("Reinforcement stress", "reinforcement"),
        ]
        if inp.get("tendons"):
            names.append(("Tendon stress", "prestress"))
        if not outputs:
            rows.append(_summary_row(
                "Elastic stresses",
                "elastic",
                "INVALID" if not converged else "NOT RUN",
                view="Elastic Results",
                note=("Solver did not converge" if not converged
                      else "No stress output returned"),
                inp=inp,
            ))
        else:
            for label, key in names:
                output = outputs.get(key) or {}
                status = (
                    "INVALID" if not converged
                    else str(
                        output.get("calculation_state") or "NOT CALCULATED"
                    )
                )
                value = output.get("value")
                result = "-" if value is None else f"{value:.3f} MPa"
                rows.append(_summary_row(
                    label, "elastic", status, result, "Output only",
                    None, "Elastic Results",
                    output.get("governing") or output.get("quantity") or "", inp,
                ))
        try:
            lambda_cr = float(elastic.get("lambda_cr"))
        except (TypeError, ValueError):
            lambda_cr = None
        if lambda_cr is not None and not math.isfinite(lambda_cr):
            lambda_cr = None
        if not converged:
            cracking_status = "INVALID"
            cracking_result = "-"
            cracking_note = "Solver did not converge"
        elif lambda_cr is None:
            cracking_status = "NOT CALCULATED"
            cracking_result = "-"
            cracking_note = "No cracking-threshold result returned"
        else:
            cracking_status = "CALCULATED"
            cracking_state = (
                "cracked" if elastic.get("cracked") else "uncracked"
            )
            cracking_result = f"lambda_cr {lambda_cr:.3f}; {cracking_state}"
            cracking_note = "Stage-I cracking threshold/state"
        rows.append(_summary_row(
            "Cracking threshold/state", "elastic", cracking_status,
            cracking_result, "Output only", None, "Elastic Results",
            cracking_note, inp,
        ))
        output = elastic.get("crack_output")
        if isinstance(output, Mapping):
            rows.append(_ordinary_crack_summary_row(inp, output))
        elif elastic.get("show_cw") or inp.get("sls_cw"):
            rows.append(_summary_row(
                "Crack width", "elastic", "NOT ASSESSED",
                view="Elastic Results",
                note="No authoritative crack-width output was retained",
                inp=inp,
            ))

    minimum = results.get("minimum_reinforcement")
    minimum_direction = modelled_direction.resolved_label(
        minimum,
        cut_direction=inp.get("detailing_cut_direction"),
        alias=inp.get(modelled_direction.ALIAS_KEY),
    )
    minimum_label = f"{minimum_direction} minimum reinforcement"
    if minimum is None and inp.get("minimum_reinforcement_on"):
        rows.append(_summary_row(
            minimum_label, "plastic", "NOT RUN",
            view="Detailing", note="Calculate required", inp=inp,
        ))
    elif minimum is not None:
        checks = minimum.get("checks") or []
        if not checks:
            rows.append(_summary_row(
                minimum_label,
                "plastic",
                _map_assessment_status(minimum.get("status")),
                view="Detailing",
                note=str(minimum.get("reason") or minimum.get("clause") or ""),
                inp=inp,
            ))
        for check in checks:
            util = check.get("utilisation")
            face = check.get("face")
            axis = check.get("axis")
            suffix = (
                " Mx+My resultant"
                if axis == "xy"
                else f" M{axis} {face}" if axis and face else ""
            )
            if minimum_area_check(minimum, check):
                required = check.get("as_min_mm2")
                result_text = (
                    f"As,prov {check.get('as_provided_mm2', 0.0):.1f} mm2; "
                    "As,min "
                    + ("-" if required is None else f"{float(required):.1f} mm2")
                )
                criterion = "As,prov >= As,min"
            elif check.get("type") == "pure tension":
                resistance = check.get("resistance_kn")
                demand = check.get("demand_kn")
                result_text = (
                    "Rnom "
                    + ("-" if resistance is None else f"{float(resistance):.1f}")
                    + " kN; Rcr "
                    + ("-" if demand is None else f"{float(demand):.1f}")
                    + " kN"
                )
                criterion = "Rnom >= Rcr"
            else:
                resistance = check.get("mr_nom_knm")
                demand = check.get("m_cr_knm")
                result_text = (
                    "MR,nom "
                    + ("-" if resistance is None else f"{float(resistance):.1f}")
                    + " kNm; Mcr "
                    + ("-" if demand is None else f"{float(demand):.1f}")
                    + " kNm"
                )
                criterion = "MR,nom >= Mcr"
            note_parts = [str(minimum.get("clause") or "")]
            if check.get("axial_feasible") is not None:
                note_parts.append(
                    "nominal axial equilibrium verified"
                    if check.get("axial_feasible")
                    else "nominal axial equilibrium not available"
                )
            if check.get("reason"):
                note_parts.append(str(check["reason"]))
            rows.append(_summary_row(
                f"{minimum_label}{suffix}",
                "plastic",
                _map_assessment_status(check.get("status")),
                result_text,
                criterion,
                util,
                "Detailing",
                "; ".join(part for part in note_parts if part),
                inp,
            ))

    transverse = results.get("transverse_reinforcement")
    if transverse is None and inp.get("transverse_detailing_on"):
        rows.append(_summary_row(
            "Shear/torsion link detailing",
            "plastic",
            "NOT RUN",
            view="Detailing",
            note="Calculate required",
            inp=inp,
        ))
    elif transverse is not None:
        checks = transverse.get("checks") or []
        if not checks:
            rows.append(_summary_row(
                "Shear/torsion link detailing",
                "plastic",
                _map_assessment_status(transverse.get("status")),
                view="Detailing",
                note=str(
                    transverse.get("reason")
                    or transverse.get("edition")
                    or ""
                ),
                inp=inp,
            ))
        labels = {
            "minimum_ratio": "minimum ratio",
            "longitudinal_spacing": "longitudinal spacing",
            "transverse_leg_spacing": "transverse leg spacing",
            "torsion_spacing": "closed-link spacing",
            "required_links": "required links",
            "minimum_link_applicability": "minimum-link applicability",
        }
        for check in checks:
            kind = str(check.get("kind") or "")
            check_label = labels.get(kind, kind)
            if kind == "transverse_leg_spacing" and check.get("measurement_axis"):
                check_label += f" along {check['measurement_axis']}"
            provided = check.get("provided")
            limit = check.get("limit")
            if kind == "required_links":
                result_text = "No links defined"
                criterion = "Links required"
            elif kind == "minimum_ratio":
                result_text = (
                    "-"
                    if provided is None
                    else f"{_RHO}w,prov = {float(provided):.5f}"
                )
                criterion = (
                    "-"
                    if limit is None
                    else f"{_RHO}w,prov >= {_RHO}w,min = {float(limit):.5f}"
                )
            else:
                result_text = (
                    "-"
                    if provided is None
                    else f"sprov = {float(provided):.1f} mm"
                )
                criterion = (
                    "-"
                    if limit is None
                    else f"sprov <= smax = {float(limit):.1f} mm"
                )
            note = "; ".join(
                part for part in (
                    str(check.get("clause") or ""),
                    str(check.get("reason") or ""),
                    (
                        "spacing " + str(check.get("spacing_source"))
                        if check.get("spacing_source") else ""
                    ),
                )
                if part
            )
            rows.append(_summary_row(
                f"{check.get('scope', 'Shear/torsion links')} "
                f"{check_label}",
                "plastic",
                _map_assessment_status(check.get("status")),
                result_text,
                criterion,
                check.get("utilisation"),
                "Detailing",
                note,
                inp,
            ))

    spacing = results.get("clear_spacing")
    if spacing is None and inp.get("clear_spacing_on"):
        rows.append(_summary_row(
            "Reinforcement clear spacing", "section", "NOT RUN",
            view="Detailing", note="Calculate required", inp=inp,
        ))
    elif spacing is not None:
        governing = spacing.get("governing") or {}
        clear = governing.get("clear_mm")
        required = governing.get("required_mm")
        util = (
            float(required) / float(clear)
            if required is not None and clear is not None and float(clear) > 0.0
            else math.inf if governing and required is not None else None
        )
        result_text = (
            f"{clear:.1f} mm ({governing.get('first_id', '?')}-"
            f"{governing.get('second_id', '?')})"
            if clear is not None else "-"
        )
        criterion = f">= {required:.1f} mm" if required is not None else "-"
        rows.append(_summary_row(
            "Reinforcement clear spacing",
            "section",
            _map_assessment_status(spacing.get("status")),
            result_text,
            criterion,
            util,
            "Detailing",
            str(spacing.get("clause") or ""),
            inp,
        ))

    shear = results.get("shear")
    if shear is None and inp.get("shear_on"):
        rows.append(_summary_row(
            "Shear", "plastic", "NOT RUN",
            view="Shear", note="Calculate required", inp=inp,
        ))
    elif shear is not None:
        links_selected = bool(inp.get("shear_links"))

        def append_direction(component, direction):
            suffix = {"vx": " Vx", "vy": " Vy"}.get(component, "")
            action_label = {"vx": "Vx,Ed", "vy": "Vy,Ed"}.get(component, "VEd")
            resistance = (direction.get("res") or {}).get("vrd_c")
            result = (
                f"{_percent(direction.get('util'))} "
                f"({action_label} / VRd,c)"
                if resistance is not None else "-"
            )
            rows.append(_summary_row(
                f"Shear{suffix} without links",
                "plastic",
                (
                    "NOT APPLICABLE"
                    if links_selected
                    else _util_summary_status(
                        direction.get("util"),
                        valid=bool((direction.get("res") or {}).get("valid")),
                    )
                ),
                result,
                "<= 100 %",
                direction.get("util"),
                "Shear",
                (
                    "Links present; use the reinforced shear check"
                    if links_selected else str(direction.get("method") or "")
                ),
                inp,
            ))
            if not links_selected:
                return
            links = direction.get("links")
            if links is None:
                rows.append(_summary_row(
                    f"Shear{suffix} with links", "plastic", "NOT ASSESSED",
                    view="Shear", note="Selected method does not evaluate links",
                    inp=inp,
                ))
            else:
                rows.append(_summary_row(
                    f"Shear{suffix} with links",
                    "plastic",
                    _util_summary_status(
                        links.get("util"),
                        valid=bool((links.get("res") or {}).get("valid")),
                    ),
                    _percent(links.get("util")),
                    "<= 100 %",
                    links.get("util"),
                    "Shear",
                    str((links.get("res") or {}).get("governs") or ""),
                    inp,
                ))

        directions = shear.get("directions") or {}
        if directions:
            for component in ("vx", "vy"):
                if component in directions:
                    append_direction(component, directions[component])
            if shear.get("biaxial"):
                rows.append(_summary_row(
                    "Generic cross-direction shear interaction",
                    "plastic",
                    "NOT CALCULATED",
                    result="Independent Vx and Vy calculations",
                    criterion="Not calculated",
                    view="Shear",
                    note="No aggregate cross-direction verdict",
                    inp=inp,
                ))
        else:
            append_direction("", shear)

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
        directions = combined.get("directions") or {}
        if combined.get("biaxial") and directions:
            for component in ("vx", "vy"):
                direction = directions.get(component)
                if not direction:
                    continue
                label = "Vx+T" if component == "vx" else "Vy+T"
                util = direction.get("dkna_sum")
                status = (
                    "NOT ASSESSED"
                    if not direction.get("valid")
                    else "PASS" if direction.get("dkna_ok") else "FAIL"
                )
                rows.append(_summary_row(
                    f"Combined {label} - DK NA sum",
                    "plastic",
                    status,
                    _percent(util),
                    "<= 100 %",
                    util,
                    "M-V-T Combined",
                    str(direction.get("method") or ""),
                    inp,
                ))
                if direction.get("valid"):
                    for physical in combined_physical_components(direction):
                        rows.append(_summary_row(
                            f"Combined {label} {physical['label'].lower()}",
                            "plastic",
                            physical["status"],
                            _percent(physical["util"]),
                            "<= 100 %",
                            physical["util"],
                            "M-V-T Combined",
                            physical["note"],
                            inp,
                        ))
            rows.append(_summary_row(
                "Generic Vx-Vy-T interaction",
                "plastic",
                "NOT CALCULATED",
                result="Independent Vx+T and Vy+T calculations",
                criterion="Not calculated",
                view="M-V-T Combined",
                note="No aggregate cross-direction verdict",
                inp=inp,
            ))
            if stale and results:
                for row in rows:
                    if row["status"] not in {"NOT RUN", "NOT APPLICABLE"}:
                        previous = row["status"]
                        row["status"] = "STALE"
                        row["note"] = f"Last status: {previous}; inputs changed"
            return rows
        valid = bool(combined.get("valid"))
        util = combined.get("dkna_sum")
        missing = [
            label
            for key, label in (
                ("have_m", "M"),
                ("have_v", "V"),
                ("have_t", "T"),
            )
            if key in combined and not combined.get(key)
        ]
        if valid:
            combined_note = str(combined.get("method") or "")
        elif missing:
            combined_note = "Missing prerequisite: " + ", ".join(missing)
        else:
            combined_note = str(
                combined.get("reason") or "Combined calculation is invalid"
            )
        combined_status = (
            "NOT ASSESSED"
            if not valid and missing
            else _util_summary_status(
                util,
                valid=valid,
            )
        )
        rows.append(_summary_row(
            "Combined M-V-T - DK NA sum",
            "plastic",
            combined_status,
            _percent(util),
            "<= 100 %",
            util,
            "M-V-T Combined",
            combined_note,
            inp,
        ))
        if valid:
            for component in combined_physical_components(combined):
                rows.append(_summary_row(
                    f"Combined {component['label'].lower()}",
                    "plastic",
                    component["status"],
                    _percent(component["util"]),
                    "<= 100 %",
                    component["util"],
                    "M-V-T Combined",
                    component["note"],
                    inp,
                ))

    heightened = results.get("heightened_crack_control")
    if isinstance(heightened, Mapping):
        rows.append(_heightened_crack_summary_row(inp, heightened))

    if stale and results:
        for row in rows:
            if row["status"] not in {"NOT RUN", "NOT APPLICABLE"}:
                previous = row["status"]
                row["status"] = "STALE"
                row["note"] = f"Last status: {previous}; inputs changed"
    return rows


def multi_case_summary_rows(inp, results, *, stale=False):
    """Build one ordered result register across every canonical case row."""
    inp = inp or {}
    results = results or {}
    if "plastic_cases" not in inp and "elastic_cases" not in inp:
        return (
            result_summary_rows(inp, results, stale=stale)
            + fatigue_summary_rows(inp, results, stale=stale)
        )

    mode = str(inp.get("mode") or "")
    requested = {
        "plastic": (
            mode in {"Plastic", "Both"}
            or bool(inp.get("shear_on"))
            or bool(inp.get("torsion_on"))
            or bool(inp.get("combined_on"))
            or bool(inp.get("minimum_reinforcement_on"))
            or bool(inp.get("transverse_detailing_on"))
        ),
        "elastic": mode in {"Elastic", "Both"},
    }
    rows = []
    for family in ("plastic", "elastic"):
        if not requested[family]:
            continue
        result_key = f"{family}_cases"
        entries = results.get(result_key)
        if entries is None:
            entries = [
                {
                    "actions": record,
                    "results": {},
                    "evaluated": False,
                }
                for record in case_analysis.case_records(inp, family)
            ]
        for entry in entries:
            actions = entry.get("actions") or {}
            if family == "plastic":
                case_inp = case_analysis.plastic_case_input(inp, actions)
                # Clear spacing is section-wide and is appended once below.
                case_inp["clear_spacing_on"] = False
            else:
                case_inp = case_analysis.elastic_case_input(inp, actions)
            case_results = entry.get("results") or {}
            rows.extend(
                result_summary_rows(case_inp, case_results, stale=stale)
            )
            if family != "plastic":
                continue

            vx_zero = abs(float(actions.get("vx_ed_kn", 0.0))) <= 0.0
            vy_zero = abs(float(actions.get("vy_ed_kn", 0.0))) <= 0.0
            v_zero = vx_zero and vy_zero
            t_zero = abs(float(actions.get("t_ed_knm", 0.0))) <= 0.0
            if inp.get("shear_on"):
                for component, is_zero in (("Vx", vx_zero), ("Vy", vy_zero)):
                    if is_zero:
                        rows.append(_summary_row(
                            f"Shear {component}", "plastic", "NOT APPLICABLE",
                            result=f"{component},Ed = 0", view="Shear",
                            note="Zero component; not evaluated", inp=case_inp,
                        ))
            if inp.get("torsion_on") and t_zero:
                rows.append(_summary_row(
                    "Torsion", "plastic", "NOT APPLICABLE",
                    result="TEd = 0", view="Torsion",
                    note="Zero action; not evaluated", inp=case_inp,
                ))
            if inp.get("combined_on") and (v_zero or t_zero):
                zero = (
                    "Vx,Ed = Vy,Ed = TEd = 0"
                    if v_zero and t_zero
                    else "Vx,Ed = Vy,Ed = 0" if v_zero else "TEd = 0"
                )
                rows.append(_summary_row(
                    "Combined M-V-T", "plastic", "NOT APPLICABLE",
                    result=zero, view="M-V-T Combined",
                    note="Zero action; not evaluated", inp=case_inp,
                ))
            shear_action_live = not v_zero and bool(inp.get("shear_on"))
            torsion_action_live = not t_zero and bool(inp.get("torsion_on"))
            transverse_live = shear_action_live or torsion_action_live
            if inp.get("transverse_detailing_on") and not transverse_live:
                rows.append(_summary_row(
                    "Shear/torsion link detailing",
                    "plastic",
                    "NOT APPLICABLE",
                    result="No active non-zero VEd or TEd",
                    view="Detailing",
                    note="Zero relevant action; not evaluated",
                    inp=case_inp,
                ))
    # Clear spacing is a section-wide result, not a load-case result. Add it once
    # after the case loops rather than repeating it for every Plastic row.
    if inp.get("clear_spacing_on"):
        spacing_only_inp = dict(
            inp,
            mode="",
            plastic_case={},
            elastic_case={},
            minimum_reinforcement_on=False,
            transverse_detailing_on=False,
            shear_on=False,
            torsion_on=False,
            combined_on=False,
        )
        rows.extend(result_summary_rows(
            spacing_only_inp,
            {"clear_spacing": results.get("clear_spacing")}
            if results.get("clear_spacing") is not None else {},
            stale=stale,
        ))
    heightened = results.get("heightened_crack_control")
    if isinstance(heightened, Mapping):
        row = _heightened_crack_summary_row(inp, heightened)
        if stale:
            previous = row["status"]
            row["status"] = "STALE"
            row["note"] = f"Last status: {previous}; inputs changed"
        rows.append(row)
    rows.extend(fatigue_summary_rows(inp, results, stale=stale))
    return rows


def overall_summary_status(rows):
    """Return the most conservative state represented in a summary table."""
    states = {row.get("status") for row in rows}
    for status in (
        "INVALID", "FAIL", "STALE", "REVIEW", "NOT ASSESSED", "NOT RUN",
        "PASS", "CALCULATED", "NOT CALCULATED", "NOT APPLICABLE",
    ):
        if status in states:
            return status
    return "NOT RUN"


def summary_governing_flags(rows):
    """Mark the largest utilisation among rows that carry acceptance verdicts."""
    def eligible(row):
        util = row.get("util")
        return bool(
            row.get("status") in {"PASS", "FAIL"}
            and util is not None
            and (math.isfinite(util) or util == math.inf)
        )

    candidates = [row["util"] for row in rows if eligible(row)]
    governing = max(candidates) if candidates else None
    return [
        bool(
            governing is not None
            and eligible(row)
            and (
                row["util"] == governing
                if governing == math.inf
                else math.isclose(
                    row["util"], governing, rel_tol=1e-12, abs_tol=1e-12
                )
            )
        )
        for row in rows
    ]


def summary_governing_case_flags(rows):
    """Mark the highest accepted utilisation for each check across cases."""
    eligible = {}
    for row in rows:
        util = row.get("util")
        if (
            row.get("status") in {"PASS", "FAIL"}
            and util is not None
            and (math.isfinite(util) or util == math.inf)
        ):
            eligible.setdefault(row.get("check"), []).append(util)
    governing = {
        check: max(values) for check, values in eligible.items() if values
    }
    flags = []
    for row in rows:
        value = governing.get(row.get("check"))
        util = row.get("util")
        flags.append(bool(
            value is not None
            and row.get("status") in {"PASS", "FAIL"}
            and util is not None
            and (
                util == value
                if value == math.inf
                else math.isclose(util, value, rel_tol=1e-12, abs_tol=1e-12)
            )
        ))
    return flags
