"""Shared, calculation-free presentation helpers for fatigue results.

The fatigue engine owns every numerical result and acceptance decision.  This
module only converts its immutable result objects into concise rows used by the
Streamlit UI and the PDF report.
"""

from __future__ import annotations

from collections.abc import Mapping
import math


def value(record, name, default=None):
    """Read a field from either a mapping or a result dataclass."""

    if isinstance(record, Mapping):
        return record.get(name, default)
    return getattr(record, name, default)


def items(record, name):
    """Return a result collection as a tuple."""

    return tuple(value(record, name, ()) or ())


def finite_number(raw):
    """Return a finite float, otherwise ``None``."""

    try:
        number = float(raw)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def evidence_number(raw):
    """Return numeric result evidence, preserving signed infinity.

    The fatigue engine deliberately uses infinity for infinite fatigue life and
    unbounded Miner damage. ``NaN`` and non-numeric values are still invalid, but
    an infinite failure must remain visible in result tables and reports.
    """

    try:
        number = float(raw)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def result_status(result):
    """Return the acceptance status of one computed spectrum/component."""

    if result is None or not bool(value(result, "converged", False)):
        return "INVALID"
    return "PASS" if bool(value(result, "passed", False)) else "FAIL"


def overall_status(payload, *, stale=False):
    """Return the conservative aggregate fatigue status."""

    if payload is None:
        return "NOT RUN"
    status = result_status(payload)
    if status == "PASS" and items(payload, "warnings"):
        status = "REVIEW"
    return "STALE" if stale else status


def overall_note(payload, *, stale=False):
    """Return a compact explanation paired with :func:`overall_status`."""

    if payload is None:
        return "Calculate to assess the grouped spectra"
    status = overall_status(payload)
    if stale:
        return f"Last status: {status}; inputs changed"
    errors = items(payload, "errors")
    if errors:
        suffix = "" if len(errors) == 1 else "s"
        return f"{len(errors)} fatigue input error{suffix}; fatigue not assessed"
    if status == "INVALID":
        return "One or more grouped spectra did not converge"
    if status == "FAIL":
        return "Governing grouped spectrum"
    warnings = items(payload, "warnings")
    if warnings:
        suffix = "" if len(warnings) == 1 else "s"
        return f"{len(warnings)} fatigue-basis warning{suffix}; review Inputs"
    return "Governing grouped spectrum"


def spectrum_by_name(payload, spectrum_name):
    """Return a named spectrum result, or ``None``."""

    target = str(spectrum_name or "")
    return next(
        (
            spectrum
            for spectrum in items(payload, "spectra")
            if str(value(spectrum, "spectrum_name", "")) == target
        ),
        None,
    )


def governing_criterion(spectrum):
    """Describe the solver-retained component controlling a spectrum."""

    domain = str(value(spectrum, "governing_domain", "") or "")
    criterion = str(value(spectrum, "governing_criterion", "") or "")
    if domain == "reinforcement":
        element_id = value(spectrum, "governing_reinforcement_id", "-")
        return f"{element_id} - {criterion or '-'}"
    if domain == "concrete":
        fibre = value(spectrum, "governing_concrete_fibre", "-")
        return f"concrete fibre {fibre} - {criterion or '-'}"
    if domain == "concrete search":
        return criterion or "concrete bounded search"
    return "-"


def spectrum_rows(payload):
    """Return one QA summary row for every independently checked spectrum."""

    rows = []
    for spectrum in items(payload, "spectra"):
        search = value(spectrum, "concrete_search")
        rows.append({
            "spectrum": str(value(spectrum, "spectrum_name", "-")),
            "status": result_status(spectrum),
            "bins": len(items(spectrum, "bins")),
            "reinforcement_elements": len(items(spectrum, "reinforcement")),
            "concrete_fibres": len(items(spectrum, "concrete")),
            "governing": governing_criterion(spectrum),
            "utilisation": evidence_number(value(spectrum, "utilisation")),
            "search_converged": (
                None if search is None else bool(value(search, "converged", False))
            ),
            "search_upper_damage": (
                None if search is None
                else evidence_number(value(search, "upper_damage"))
            ),
        })
    return rows


def reinforcement_rows(spectrum):
    """Return element-level S-N/Miner and yield evidence."""

    rows = []
    for result in items(spectrum, "reinforcement"):
        rows.append({
            "element_id": str(value(result, "element_id", "-")),
            "kind": str(value(result, "kind", "-")),
            "detail_id": str(value(result, "detail_id", "-")),
            "diameter_mm": evidence_number(value(result, "diameter_mm")),
            "damage": evidence_number(value(result, "damage")),
            "damage_utilisation": evidence_number(
                value(result, "damage_utilisation")
            ),
            "governing_damage_bin": str(
                value(result, "governing_damage_bin", "-")
            ),
            "yield_utilisation": evidence_number(
                value(result, "yield_utilisation")
            ),
            "governing_yield_bin": str(
                value(result, "governing_yield_bin", "-")
            ),
            "governing": str(
                value(result, "governing_criterion", "-") or "-"
            ),
            "governing_bin": str(
                value(result, "governing_bin", "-") or "-"
            ),
            "utilisation": evidence_number(value(result, "utilisation")),
            "status": result_status(result),
        })
    return rows


def reinforcement_bin_rows(result):
    """Return complete bin evidence for one reinforcement element."""

    rows = []
    for item in items(result, "bins"):
        rows.append({
            "bin": str(value(item, "bin_name", "-")),
            "cycles": evidence_number(value(item, "cycles")),
            "status": (
                "OK" if bool(value(item, "converged", False)) else "INVALID"
            ),
            "stress_long_mpa": evidence_number(value(item, "stress_long_mpa")),
            "stress_total_mpa": evidence_number(value(item, "stress_total_mpa")),
            "stress_total_design_mpa": evidence_number(
                value(item, "stress_total_design_mpa")
            ),
            "stress_total_elastic_mpa": evidence_number(
                value(item, "stress_total_elastic_mpa")
            ),
            "stress_range_mpa": evidence_number(value(item, "stress_range_mpa")),
            "stress_range_elastic_mpa": evidence_number(
                value(item, "stress_range_elastic_mpa")
            ),
            "bond_adjustment": evidence_number(value(item, "bond_adjustment")),
            "bond_method": str(value(item, "bond_method", "-")),
            "design_stress_range_mpa": evidence_number(
                value(item, "design_stress_range_mpa")
            ),
            "delta_sigma_rsk_mpa": evidence_number(
                value(item, "delta_sigma_rsk_mpa")
            ),
            "delta_sigma_rd_mpa": evidence_number(
                value(item, "delta_sigma_rd_mpa")
            ),
            "sn_exponent": evidence_number(value(item, "sn_exponent")),
            "cycles_to_failure": evidence_number(
                value(item, "cycles_to_failure")
            ),
            "log10_cycles_to_failure": evidence_number(
                value(item, "log10_cycles_to_failure")
            ),
            "damage": evidence_number(value(item, "damage")),
            "governing_stress_mpa": evidence_number(
                value(item, "governing_stress_mpa")
            ),
            "yield_limit_mpa": evidence_number(value(item, "yield_limit_mpa")),
            "yield_utilisation": evidence_number(
                value(item, "yield_utilisation")
            ),
            "sn_reference_cycles": evidence_number(
                value(item, "sn_reference_cycles")
            ),
            "sn_slope_1": evidence_number(value(item, "sn_slope_1")),
            "sn_slope_2": evidence_number(value(item, "sn_slope_2")),
            "sn_knee_stress_range_mpa": evidence_number(
                value(item, "sn_knee_stress_range_mpa")
            ),
            "sn_branch": str(value(item, "sn_branch", "") or ""),
            "sn_reference_ratio": evidence_number(
                value(item, "sn_reference_ratio")
            ),
            "material_factor": evidence_number(
                value(item, "material_factor")
            ),
            "stress_total_design_elastic_mpa": evidence_number(
                value(item, "stress_total_design_elastic_mpa")
            ),
            "design_stress_range_elastic_mpa": evidence_number(
                value(item, "design_stress_range_elastic_mpa")
            ),
            "yield_long_check": value(item, "yield_long_check"),
            "yield_design_total_check": value(
                item, "yield_design_total_check"
            ),
            "governing_yield_check": value(item, "governing_yield_check"),
        })
    return rows


def concrete_rows(spectrum):
    """Return same-fibre concrete fatigue results."""

    search = value(spectrum, "concrete_search")
    search_x = finite_number(value(search, "x_m")) if search else None
    search_y = finite_number(value(search, "y_m")) if search else None
    rows = []
    for result in items(spectrum, "concrete"):
        method = str(value(result, "method", "Explicit Palmgren-Miner spectrum"))
        equivalent = evidence_number(
            value(result, "equivalent_utilisation")
        )
        x_m = finite_number(value(result, "x_m"))
        y_m = finite_number(value(result, "y_m"))
        is_search = bool(
            search is not None
            and x_m is not None
            and y_m is not None
            and search_x is not None
            and search_y is not None
            and math.isclose(x_m, search_x, abs_tol=1.0e-12)
            and math.isclose(y_m, search_y, abs_tol=1.0e-12)
        )
        rows.append({
            "fibre_index": value(result, "fibre_index", "-"),
            "source": "Adaptive search" if is_search else "Section vertex",
            "x_mm": None if x_m is None else x_m * 1000.0,
            "y_mm": None if y_m is None else y_m * 1000.0,
            "fcd_fat_mpa": evidence_number(value(result, "fcd_fat_mpa")),
            "damage": evidence_number(value(result, "damage")),
            "damage_utilisation": evidence_number(
                value(result, "damage_utilisation")
            ),
            "governing_damage_bin": str(
                value(result, "governing_damage_bin", "-")
            ),
            "stress_utilisation": evidence_number(
                value(result, "stress_utilisation")
            ),
            "method": method,
            "equivalent_utilisation": equivalent,
            "governing_equivalent_bin": str(
                value(result, "governing_equivalent_bin", "-") or "-"
            ),
            "governing_stress_bin": str(
                value(result, "governing_stress_bin", "-")
            ),
            "governing": str(
                value(result, "governing_criterion", "-") or "-"
            ),
            "governing_bin": str(
                value(result, "governing_bin", "-") or "-"
            ),
            "utilisation": evidence_number(value(result, "utilisation")),
            "status": result_status(result),
        })
    return rows


def concrete_bin_rows(result):
    """Return complete bin evidence for one concrete fibre."""

    rows = []
    for item in items(result, "bins"):
        rows.append({
            "bin": str(value(item, "bin_name", "-")),
            "cycles": evidence_number(value(item, "cycles")),
            "status": (
                "OK" if bool(value(item, "converged", False)) else "INVALID"
            ),
            "compression_long_mpa": evidence_number(
                value(item, "compression_long_mpa")
            ),
            "compression_total_mpa": evidence_number(
                value(item, "compression_total_mpa")
            ),
            "compression_min_design_mpa": evidence_number(
                value(item, "compression_min_design_mpa")
            ),
            "compression_max_design_mpa": evidence_number(
                value(item, "compression_max_design_mpa")
            ),
            "stress_ratio": evidence_number(value(item, "stress_ratio")),
            "e_cd_min": evidence_number(value(item, "e_cd_min")),
            "e_cd_max": evidence_number(value(item, "e_cd_max")),
            "cycles_to_failure": evidence_number(
                value(item, "cycles_to_failure")
            ),
            "log10_cycles_to_failure": evidence_number(
                value(item, "log10_cycles_to_failure")
            ),
            "damage": evidence_number(value(item, "damage")),
            "stress_utilisation": evidence_number(
                value(item, "stress_utilisation")
            ),
            "equivalent_utilisation": evidence_number(
                value(item, "equivalent_utilisation")
            ),
            "life_branch": str(value(item, "life_branch", "") or ""),
            "life_coefficient": evidence_number(
                value(item, "life_coefficient")
            ),
            "life_range_term": evidence_number(
                value(item, "life_range_term")
            ),
            "compression_total_design_mpa": evidence_number(
                value(item, "compression_total_design_mpa")
            ),
            "compression_min_state": str(
                value(item, "compression_min_state", "") or ""
            ),
            "compression_max_state": str(
                value(item, "compression_max_state", "") or ""
            ),
        })
    return rows


def spectrum_bin_rows(spectrum):
    """Return retained solver-state identity for every grouped-spectrum bin."""

    rows = []
    for index, state in enumerate(items(spectrum, "bins")):
        rows.append({
            "index": index + 1,
            "bin": str(value(state, "name", "-")),
            "description": str(value(state, "description", "") or ""),
            "cycles": evidence_number(value(state, "cycles")),
            "status": (
                "OK" if bool(value(state, "converged", False)) else "INVALID"
            ),
            "gamma_ff": evidence_number(value(state, "design_action_factor")),
            "bond_method": str(value(state, "bond_method", "-")),
        })
    return rows


def result_by_element(spectrum, element_id):
    """Return one reinforcement result by its stable element ID."""

    target = str(element_id or "")
    return next(
        (
            result
            for result in items(spectrum, "reinforcement")
            if str(value(result, "element_id", "")) == target
        ),
        None,
    )


def result_by_fibre(spectrum, fibre_index):
    """Return one concrete result by its stable fibre index."""

    return next(
        (
            result
            for result in items(spectrum, "concrete")
            if value(result, "fibre_index") == fibre_index
        ),
        None,
    )


def reinforcement_property(payload, element_id):
    """Return the S-N properties assigned to one stable element ID."""

    target = str(element_id or "")
    return next(
        (
            record
            for record in items(payload, "reinforcement_properties")
            if str(value(record, "element_id", "")) == target
        ),
        None,
    )
