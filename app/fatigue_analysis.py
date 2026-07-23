"""Pure application boundary for Sector's grouped fatigue engine.

The Streamlit layer owns widgets and presentation.  This module validates the
complete application input, resolves per-element material and fatigue-detail
assignments, converts the UI's tension-positive normal force exactly once, and
calls :mod:`sector.fatigue`.

Authority selections are retained as provenance and QA warnings only.  No
traffic, dynamic, concurrence, control-class, construction-category or
consequence-class factor is applied here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import math

import numpy as np

import fatigue_inputs
import load_cases
from sector.fatigue import (
    ConcreteFatigueProperties,
    FatigueSpectrumResult,
    ReinforcementFatigueProperties,
    SpectrumBin,
    analyse_grouped_spectra,
)
from sector.section import Section


STEEL_REFERENCE_MODULUS_MPA = 200_000.0


@dataclass(frozen=True)
class PreparedFatigueAnalysis:
    """Validated, solver-ready fatigue input in canonical element order."""

    section: Section
    spectra: Mapping[str, tuple[SpectrumBin, ...]]
    nl: float
    ns: float
    reinforcement: tuple[ReinforcementFatigueProperties, ...]
    concrete: ConcreteFatigueProperties | None
    edition: str
    solver_element_ids: tuple[str, ...]
    element_records: tuple[Mapping, ...]
    gamma_c: float | None
    gamma_s: float | None
    gamma_ff: float
    check_reinforcement: bool
    check_concrete: bool
    n_mult: np.ndarray | None
    prestress_stress: np.ndarray | None
    t0_days: float | None
    basis: Mapping
    warnings: tuple[str, ...]


def _positive(value, label: str, errors: list[str]) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        errors.append(f"{label} must be a finite number greater than zero")
        return None
    if not math.isfinite(number) or number <= 0.0:
        errors.append(f"{label} must be a finite number greater than zero")
        return None
    return number


def _finite_attribute(value, label: str, errors: list[str], *, positive=False):
    try:
        number = float(value)
    except (TypeError, ValueError):
        errors.append(f"{label} must be a finite number")
        return None
    if not math.isfinite(number):
        errors.append(f"{label} must be a finite number")
        return None
    if positive and number <= 0.0:
        errors.append(f"{label} must be greater than zero")
        return None
    return number


def _edition(value) -> str:
    text = str(value or "").strip()
    if text in fatigue_inputs.EDITIONS:
        return text
    if "2023" in text:
        return fatigue_inputs.EC2_2023
    if "2005" in text or "2004" in text:
        return fatigue_inputs.EC2_2005
    raise ValueError(
        "fatigue edition must identify DS/EN 1992-1-1:2005, "
        "DK NA:2024 or DS/EN 1992-1-1:2023"
    )


def calculation_references(edition: str) -> dict[str, str]:
    """Return the explicit steel and concrete fatigue-method references."""

    selected = _edition(edition)
    if "2023" in selected:
        return {
            "reinforcement": (
                "DS/EN 1992-1-1:2023, Annex E.5 and Tables E.1/E.2"
            ),
            "concrete": "DS/EN 1992-1-1:2023, Annex E.7-E.8",
        }
    national = (
        " with DK NA:2024 explicit input factors"
        if selected == fatigue_inputs.EC2_2005_DKNA
        else ""
    )
    return {
        "reinforcement": (
            "DS/EN 1992-1-1:2005+A1:2014, clause 6.8.4 and "
            f"Tables 6.3N/6.4N{national}"
        ),
        "concrete": (
            "DS/EN 1992-2:2005/AC:2008, corrected clause 6.106"
            f"{national}"
        ),
    }


def _case_names(inp: Mapping) -> list[str]:
    names = []
    for value_key, table_key in (
        ("plastic_cases", load_cases.PLASTIC_TABLE_KEY),
        ("elastic_cases", load_cases.ELASTIC_TABLE_KEY),
    ):
        value = inp.get(value_key)
        if value is None:
            continue
        try:
            frame = load_cases.active_table(value, table_key)
        except (TypeError, ValueError):
            continue
        names.extend(
            str(value).strip()
            for value in frame[load_cases.NAME].tolist()
            if str(value).strip()
        )
    return names


def _records(inp: Mapping) -> tuple[list[Mapping], list[Mapping]]:
    bars = list(inp.get("bar_elements") or [])
    tendons = list(inp.get("tendon_elements") or [])
    return bars, tendons


def _validate_element_geometry(
    records: Sequence[Mapping],
    solver_elements,
    label: str,
    errors: list[str],
) -> None:
    if len(records) != len(solver_elements):
        errors.append(
            f"{label} element table has {len(records)} rows but the section "
            f"contains {len(solver_elements)} elements"
        )
        return
    for index, (record, element) in enumerate(
        zip(records, solver_elements), start=1
    ):
        if not isinstance(record, Mapping):
            continue
        element_id = str(record.get("id") or f"{label} {index}").strip()
        comparisons = (
            ("x", record.get("x_mm"), float(element.x) * 1000.0),
            ("y", record.get("y_mm"), float(element.y) * 1000.0),
            ("area", record.get("area_mm2"), float(element.area) * 1.0e6),
        )
        for field, raw, expected in comparisons:
            try:
                actual = float(raw)
            except (TypeError, ValueError):
                errors.append(f"{element_id}: {field} must be a finite number")
                continue
            if not math.isfinite(actual):
                errors.append(f"{element_id}: {field} must be a finite number")
            elif not math.isclose(
                actual,
                expected,
                rel_tol=1.0e-9,
                abs_tol=1.0e-9,
            ):
                errors.append(
                    f"{element_id}: {field} does not match the solver section"
                )


def _validate_materials(
    records: Sequence[Mapping],
    materials: Sequence,
    label: str,
    errors: list[str],
    *,
    require_strength: bool,
) -> None:
    if len(materials) != len(records):
        errors.append(
            f"{label} material mapping has {len(materials)} values for "
            f"{len(records)} elements"
        )
        return
    for record, material in zip(records, materials):
        if not isinstance(record, Mapping):
            continue
        element_id = str(record.get("id") or label).strip()
        if material is None:
            errors.append(f"{element_id}: assigned material is unavailable")
            continue
        _finite_attribute(
            getattr(material, "Es", None),
            f"{element_id}: elastic modulus",
            errors,
            positive=True,
        )
        if require_strength:
            _finite_attribute(
                getattr(material, "fytk", None),
                f"{element_id}: characteristic yield/proof stress",
                errors,
                positive=True,
            )
        if label == "Mild reinforcement" and require_strength:
            _finite_attribute(
                getattr(material, "fyck", None),
                f"{element_id}: characteristic compression yield stress",
                errors,
                positive=True,
            )
        elif label == "Prestressing":
            _finite_attribute(
                getattr(material, "IS", None),
                f"{element_id}: initial prestress strain",
                errors,
            )


def _detail_data(inp: Mapping, errors: list[str]) -> tuple[dict, dict]:
    try:
        catalog = fatigue_inputs.normalise_catalog(
            inp.get(fatigue_inputs.DETAIL_CATALOG_KEY)
        )
    except (TypeError, ValueError) as exc:
        errors.append(str(exc))
        return {}, fatigue_inputs.default_catalog()
    errors.extend(fatigue_inputs.catalog_errors(catalog))
    return fatigue_inputs.entry_map(catalog), catalog


def validation_errors(inp: Mapping) -> list[str]:
    """Return deterministic errors for an enabled fatigue calculation."""

    if not bool(inp.get("fatigue_on")):
        return []
    errors: list[str] = []
    section = inp.get("section")
    if not isinstance(section, Section):
        errors.append("A valid section is required for fatigue analysis")
        section = None
    for key in ("void_error", "steel_error", "material_error"):
        if inp.get(key):
            errors.append(str(inp[key]))

    try:
        edition = _edition(inp.get("fatigue_edition"))
    except ValueError as exc:
        errors.append(str(exc))
        edition = ""

    check_reinforcement = bool(inp.get("fatigue_check_steel"))
    check_concrete = bool(inp.get("fatigue_check_concrete"))
    if not check_reinforcement and not check_concrete:
        errors.append("Enable the reinforcement and/or concrete fatigue check")
    if (
        check_reinforcement
        and section is not None
        and not section.bars
        and not section.tendons
    ):
        errors.append(
            "Reinforcement fatigue check requires at least one bar or tendon"
        )

    _positive(inp.get("nl"), "Long-term modular ratio", errors)
    _positive(inp.get("ns"), "Short-term modular ratio", errors)
    _positive(inp.get("fatigue_gamma_ff"), "gamma_Ff", errors)
    if check_reinforcement:
        _positive(inp.get("fatigue_gamma_s"), "gamma_s", errors)
    if check_concrete:
        _positive(inp.get("fatigue_gamma_c"), "gamma_c,fat", errors)
        _positive(inp.get("fatigue_beta_cc_t0"), "beta_cc(t0)", errors)
        _positive(inp.get("fatigue_t0_days"), "Concrete age t0", errors)
        _positive(inp.get("fatigue_concrete_c"), "Concrete fatigue C", errors)
        concrete = inp.get("concrete")
        if concrete is None:
            errors.append("Concrete material is required for concrete fatigue")
        else:
            _finite_attribute(
                getattr(concrete, "fck", None),
                "Concrete fck",
                errors,
                positive=True,
            )
            if "2023" not in edition:
                _finite_attribute(
                    getattr(concrete, "alpha_cc", None),
                    "Concrete alpha_cc",
                    errors,
                    positive=True,
                )
        if "2023" not in edition:
            _positive(
                inp.get("fatigue_concrete_k1"),
                "Concrete fatigue k1",
                errors,
            )

    spectrum_value = inp.get(fatigue_inputs.SPECTRUM_TABLE_KEY)
    try:
        errors.extend(
            fatigue_inputs.spectrum_errors(
                spectrum_value,
                existing_case_names=_case_names(inp),
                require_rows=True,
            )
        )
        groups = fatigue_inputs.spectrum_groups(spectrum_value)
    except (TypeError, ValueError) as exc:
        errors.append(str(exc))
        groups = {}

    try:
        basis = fatigue_inputs.normalise_basis(
            inp.get(fatigue_inputs.BASIS_KEY)
        )
    except (TypeError, ValueError) as exc:
        errors.append(str(exc))
        basis = fatigue_inputs.default_basis()
    if fatigue_inputs.method_requires_single_bin(basis["method"]):
        for name, rows in groups.items():
            if len(rows) != 1:
                errors.append(
                    f"{name}: {basis['method']} requires one "
                    "constant-amplitude bin"
                )

    bars, tendons = _records(inp)
    all_records = bars + tendons
    ids: dict[str, str] = {}
    for index, record in enumerate(all_records, start=1):
        if not isinstance(record, Mapping):
            errors.append(f"Reinforcement element {index} must be an object")
            continue
        element_id = str(record.get("id") or "").strip()
        if not element_id:
            errors.append(f"Reinforcement element {index}: ID is required")
            continue
        folded = element_id.casefold()
        if folded in ids:
            errors.append(
                f"Reinforcement element ID '{element_id}' duplicates "
                f"'{ids[folded]}'"
            )
        else:
            ids[folded] = element_id
        _positive(
            record.get("diameter_mm"),
            f"{element_id}: diameter",
            errors,
        )

    if section is not None:
        _validate_element_geometry(
            bars, section.bars, "Mild reinforcement", errors
        )
        _validate_element_geometry(
            tendons, section.tendons, "Prestressing", errors
        )

    bar_materials = list(inp.get("bar_materials") or [])
    tendon_materials = list(inp.get("tendon_materials") or [])
    _validate_materials(
        bars,
        bar_materials,
        "Mild reinforcement",
        errors,
        require_strength=check_reinforcement,
    )
    _validate_materials(
        tendons,
        tendon_materials,
        "Prestressing",
        errors,
        require_strength=check_reinforcement,
    )

    details, _catalog = _detail_data(inp, errors)
    if check_reinforcement:
        for expected_kind, records in (
            (fatigue_inputs.MILD, bars),
            (fatigue_inputs.PRESTRESS, tendons),
        ):
            for record in records:
                if not isinstance(record, Mapping):
                    continue
                element_id = str(record.get("id") or expected_kind).strip()
                detail_id = str(
                    record.get("fatigue_detail_id") or ""
                ).strip()
                if not detail_id:
                    errors.append(
                        f"{element_id}: fatigue detail ID is required"
                    )
                    continue
                detail = details.get(detail_id)
                if detail is None:
                    errors.append(
                        f"{element_id}: fatigue detail '{detail_id}' "
                        "is unavailable"
                    )
                elif detail["kind"] != expected_kind:
                    errors.append(
                        f"{element_id}: fatigue detail '{detail_id}' "
                        f"must be {expected_kind}"
                    )
        if bars and tendons:
            for record in tendons:
                if not isinstance(record, Mapping):
                    continue
                element_id = str(record.get("id") or "Tendon").strip()
                detail = details.get(
                    str(record.get("fatigue_detail_id") or "").strip()
                )
                if detail is None:
                    continue
                for field in (
                    "bond_ratio_xi",
                    "bond_equivalent_diameter_mm",
                ):
                    if float(detail[field]) <= 0.0:
                        errors.append(
                            f"{element_id}: {field} is required when mild "
                            "reinforcement and bonded tendons are combined"
                        )
    return list(dict.fromkeys(errors))


def validation_warnings(inp: Mapping) -> list[str]:
    """Return non-numerical provenance gaps for an enabled calculation."""

    if not bool(inp.get("fatigue_on")):
        return []
    warnings = []
    try:
        warnings.extend(
            fatigue_inputs.basis_warnings(
                inp.get(fatigue_inputs.BASIS_KEY)
            )
        )
    except (TypeError, ValueError):
        # The same malformed basis is a blocking validation error.
        pass
    try:
        details = fatigue_inputs.entry_map(
            inp.get(fatigue_inputs.DETAIL_CATALOG_KEY)
        )
    except (TypeError, ValueError):
        details = {}
    if bool(inp.get("fatigue_check_steel")):
        assigned = {
            str(record.get("fatigue_detail_id") or "").strip()
            for records in _records(inp)
            for record in records
            if isinstance(record, Mapping)
        }
        for detail_id in sorted(assigned):
            detail = details.get(detail_id)
            if detail is not None and not str(detail.get("source") or "").strip():
                warnings.append(
                    f"{detail_id}: fatigue resistance source is not stated"
                )
    return list(dict.fromkeys(warnings))


def _reinforcement_properties(
    records: Sequence[Mapping],
    materials: Sequence,
    details: Mapping[str, Mapping],
    kind: str,
) -> list[ReinforcementFatigueProperties]:
    output = []
    for record, material in zip(records, materials):
        detail = details[str(record["fatigue_detail_id"]).strip()]
        diameter = float(record["diameter_mm"])
        reference_range = fatigue_inputs.characteristic_stress_range(
            detail, diameter
        )
        reference_range *= fatigue_inputs.bend_reduction_factor(
            detail, diameter
        )
        bond_ratio = float(detail["bond_ratio_xi"])
        bond_diameter = float(detail["bond_equivalent_diameter_mm"])
        output.append(ReinforcementFatigueProperties(
            element_id=str(record["id"]).strip(),
            kind=kind,
            detail_id=str(detail["id"]),
            diameter_mm=diameter,
            n_star=float(detail["n_star"]),
            k1=float(detail["k1"]),
            k2=float(detail["k2"]),
            delta_sigma_rsk_mpa=reference_range,
            fytk_mpa=float(material.fytk),
            fyck_mpa=(
                float(material.fyck)
                if kind == fatigue_inputs.MILD
                else None
            ),
            bond_ratio_xi=(bond_ratio if bond_ratio > 0.0 else None),
            bond_equivalent_diameter_mm=(
                bond_diameter if bond_diameter > 0.0 else None
            ),
        ))
    return output


def _spectra(value) -> dict[str, tuple[SpectrumBin, ...]]:
    output = {}
    for spectrum_name, rows in fatigue_inputs.spectrum_groups(value).items():
        output[spectrum_name] = tuple(
            SpectrumBin(
                name=row[fatigue_inputs.NAME],
                description=row[fatigue_inputs.DESCRIPTION],
                cycles=float(row[fatigue_inputs.CYCLES]),
                # UI/project N is tension-positive.  Elastic's P is
                # compression-positive; this is the only sign conversion.
                p_long_kn=-float(row["n_long_ed_kn"]),
                mx_long_knm=float(row["mx_long_ed_knm"]),
                my_long_knm=float(row["my_long_ed_knm"]),
                p_short_kn=-float(row["n_short_ed_kn"]),
                mx_short_knm=float(row["mx_short_ed_knm"]),
                my_short_knm=float(row["my_short_ed_knm"]),
            )
            for row in rows
        )
    return output


def prepare(inp: Mapping) -> PreparedFatigueAnalysis:
    """Validate and resolve an enabled application input for the core engine."""

    if not bool(inp.get("fatigue_on")):
        raise ValueError("fatigue analysis is not enabled")
    errors = validation_errors(inp)
    if errors:
        raise ValueError("; ".join(errors))

    section = inp["section"]
    bars, tendons = _records(inp)
    bar_materials = list(inp.get("bar_materials") or [])
    tendon_materials = list(inp.get("tendon_materials") or [])
    catalog = fatigue_inputs.normalise_catalog(
        inp.get(fatigue_inputs.DETAIL_CATALOG_KEY)
    )
    details = fatigue_inputs.entry_map(catalog)
    check_reinforcement = bool(inp.get("fatigue_check_steel"))
    check_concrete = bool(inp.get("fatigue_check_concrete"))
    gamma_c = (
        float(inp["fatigue_gamma_c"]) if check_concrete else None
    )
    gamma_s = (
        float(inp["fatigue_gamma_s"]) if check_reinforcement else None
    )
    reinforcement = (
        _reinforcement_properties(
            bars,
            bar_materials,
            details,
            fatigue_inputs.MILD,
        )
        + _reinforcement_properties(
            tendons,
            tendon_materials,
            details,
            fatigue_inputs.PRESTRESS,
        )
        if check_reinforcement
        else []
    )

    edition = _edition(inp.get("fatigue_edition"))
    is_2023 = "2023" in edition
    concrete = (
        ConcreteFatigueProperties(
            edition=edition,
            fck_mpa=float(inp["concrete"].fck),
            gamma_c=gamma_c,
            beta_cc_t0=float(inp["fatigue_beta_cc_t0"]),
            # alpha_cc and k1 occur only in the 2005 bridge expression.
            alpha_cc=(
                1.0 if is_2023 else float(inp["concrete"].alpha_cc)
            ),
            k1=(
                1.0 if is_2023 else float(inp["fatigue_concrete_k1"])
            ),
            c=float(inp["fatigue_concrete_c"]),
        )
        if check_concrete
        else None
    )

    all_materials = bar_materials + tendon_materials
    n_mult = (
        np.asarray(
            [
                float(material.Es) / STEEL_REFERENCE_MODULUS_MPA
                for material in all_materials
            ],
            dtype=float,
        )
        if all_materials
        else None
    )
    prestress_stress = None
    if tendons:
        prestress_stress = np.asarray(
            [0.0] * len(bars)
            + [
                float(material.Es) * float(material.IS) * 1000.0
                for material in tendon_materials
            ],
            dtype=float,
        )
    basis = fatigue_inputs.normalise_basis(
        inp.get(fatigue_inputs.BASIS_KEY)
    )
    return PreparedFatigueAnalysis(
        section=section,
        spectra=_spectra(inp[fatigue_inputs.SPECTRUM_TABLE_KEY]),
        nl=float(inp["nl"]),
        ns=float(inp["ns"]),
        reinforcement=tuple(reinforcement),
        concrete=concrete,
        edition=edition,
        solver_element_ids=tuple(
            str(record["id"]).strip() for record in bars + tendons
        ),
        element_records=tuple(dict(record) for record in bars + tendons),
        gamma_c=gamma_c,
        gamma_s=gamma_s,
        gamma_ff=float(inp["fatigue_gamma_ff"]),
        check_reinforcement=check_reinforcement,
        check_concrete=check_concrete,
        n_mult=n_mult,
        prestress_stress=prestress_stress,
        t0_days=(
            float(inp["fatigue_t0_days"]) if check_concrete else None
        ),
        basis=basis,
        warnings=tuple(validation_warnings(inp)),
    )


def analysis_signature(inp: Mapping) -> tuple:
    """Stable signature of every value passed across the fatigue boundary."""

    prepared = prepare(inp)
    section = prepared.section
    section_signature = (
        tuple(
            tuple((float(x), float(y)) for x, y in ring)
            for ring in section.concrete
        ),
        tuple((bar.x, bar.y, bar.area) for bar in section.bars),
        tuple((bar.x, bar.y, bar.area) for bar in section.tendons),
    )
    reinforcement_signature = tuple(
        (
            item.element_id,
            item.kind,
            item.detail_id,
            item.diameter_mm,
            item.n_star,
            item.k1,
            item.k2,
            item.delta_sigma_rsk_mpa,
            item.fytk_mpa,
            item.fyck_mpa,
            item.bond_ratio_xi,
            item.bond_equivalent_diameter_mm,
        )
        for item in prepared.reinforcement
    )
    concrete_signature = (
        None
        if prepared.concrete is None
        else (
            prepared.concrete.edition,
            prepared.concrete.fck_mpa,
            prepared.concrete.gamma_c,
            prepared.concrete.beta_cc_t0,
            prepared.concrete.alpha_cc,
            prepared.concrete.k1,
            prepared.concrete.c,
        )
    )
    return (
        section_signature,
        tuple(
            (
                name,
                tuple(
                    (
                        item.name,
                        item.description,
                        item.cycles,
                        item.p_long_kn,
                        item.mx_long_knm,
                        item.my_long_knm,
                        item.p_short_kn,
                        item.mx_short_knm,
                        item.my_short_knm,
                    )
                    for item in bins
                ),
            )
            for name, bins in prepared.spectra.items()
        ),
        reinforcement_signature,
        concrete_signature,
        prepared.edition,
        prepared.solver_element_ids,
        prepared.nl,
        prepared.ns,
        prepared.gamma_c,
        prepared.gamma_s,
        prepared.gamma_ff,
        prepared.check_reinforcement,
        prepared.check_concrete,
        tuple(prepared.n_mult) if prepared.n_mult is not None else None,
        (
            tuple(prepared.prestress_stress)
            if prepared.prestress_stress is not None
            else None
        ),
        prepared.t0_days,
        fatigue_inputs.basis_signature(prepared.basis),
    )


def run_analysis(
    inp: Mapping,
    *,
    engine: Callable | None = None,
) -> dict:
    """Run all independent spectra and return a concise presentation payload."""

    prepared = prepare(inp)
    solver = engine or analyse_grouped_spectra
    results: tuple[FatigueSpectrumResult, ...] = tuple(solver(
        prepared.section,
        prepared.spectra,
        prepared.nl,
        prepared.ns,
        reinforcement=prepared.reinforcement,
        concrete=prepared.concrete,
        fatigue_edition=prepared.edition,
        solver_element_ids=prepared.solver_element_ids,
        gamma_s=(
            prepared.gamma_s if prepared.gamma_s is not None else 1.0
        ),
        gamma_ff=prepared.gamma_ff,
        check_reinforcement=prepared.check_reinforcement,
        check_concrete=prepared.check_concrete,
        n_mult=prepared.n_mult,
        prestress_stress=prepared.prestress_stress,
    ))
    governing = max(results, key=lambda result: result.utilisation)
    return {
        "edition": prepared.edition,
        "checks": {
            "reinforcement": prepared.check_reinforcement,
            "concrete": prepared.check_concrete,
        },
        "basis": dict(prepared.basis),
        "authority_reference": fatigue_inputs.METHOD_REFERENCES[
            prepared.basis["method"]
        ],
        "calculation_references": {
            key: value
            for key, value in calculation_references(
                prepared.edition
            ).items()
            if (
                (key == "reinforcement" and prepared.check_reinforcement)
                or (key == "concrete" and prepared.check_concrete)
            )
        },
        "warnings": prepared.warnings,
        "partial_factors": {
            "gamma_c": prepared.gamma_c,
            "gamma_s": prepared.gamma_s,
            "gamma_ff": prepared.gamma_ff,
        },
        "concrete_parameters": (
            {
                "fck_mpa": prepared.concrete.fck_mpa,
                "beta_cc_t0": prepared.concrete.beta_cc_t0,
                "alpha_cc": prepared.concrete.alpha_cc,
                "k1": prepared.concrete.k1,
                "c": prepared.concrete.c,
            }
            if prepared.concrete is not None
            else None
        ),
        "reinforcement_properties": prepared.reinforcement,
        "t0_days": prepared.t0_days,
        "elements": prepared.element_records,
        "spectra": results,
        "governing_spectrum": governing.spectrum_name,
        "utilisation": governing.utilisation,
        "converged": all(result.converged for result in results),
        "passed": all(result.passed for result in results),
    }
