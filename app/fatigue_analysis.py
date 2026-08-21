"""Pure application boundary for Sector's grouped fatigue engine.

The Streamlit layer owns widgets and presentation.  This module validates the
complete application input, resolves per-element material and fatigue-detail
assignments, converts the UI's tension-positive normal force exactly once, and
calls :mod:`sector.fatigue`.

Every grouped action and cycle count is supplied by the user. No traffic model,
authority route or code-completeness decision is inferred here.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import fatigue_inputs
import load_cases
import material_catalog as mat_catalog
import numpy as np

from sector.design_standards import (
    Capability,
    CapabilityBinding,
    DesignBasisKey,
    capability_binding,
    get_design_basis,
    parse_design_basis_key,
)
from sector.fatigue import (
    CONCRETE_EQUIVALENT,
    CONCRETE_METHODS,
    CONCRETE_MINER,
    CONCRETE_MINER_METHODS,
    CONCRETE_PROJECT_MINER,
    ConcreteFatigueProperties,
    FatigueSpectrumResult,
    ReinforcementFatigueProperties,
    SimplifiedReinforcementFatigueRule,
    SpectrumBin,
    analyse_grouped_spectra,
)
from sector.geometry import GeometryTopologyError
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
    basis_key: DesignBasisKey
    basis_label: str
    basis_disclosure: str
    solver_edition: str
    solver_element_ids: tuple[str, ...]
    element_records: tuple[Mapping, ...]
    detail_records: tuple[Mapping, ...]
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
    concrete_method: str | None


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


def _concrete_capability(concrete_method: str) -> Capability:
    if concrete_method == CONCRETE_EQUIVALENT:
        return Capability.CONCRETE_FATIGUE_EQUIVALENT
    if concrete_method in CONCRETE_MINER_METHODS:
        return Capability.CONCRETE_FATIGUE_DAMAGE_SUM
    raise ValueError("Select a valid concrete fatigue method")


def _selected_capability_bindings(
    basis_key: DesignBasisKey,
    *,
    check_reinforcement: bool,
    check_concrete: bool,
    concrete_method: str | None,
) -> dict[str, CapabilityBinding]:
    """Resolve every requested solver route through the typed catalogue."""

    bindings = {}
    if check_reinforcement:
        bindings["reinforcement"] = capability_binding(
            basis_key,
            Capability.REINFORCEMENT_FATIGUE,
        )
    if check_concrete:
        bindings["concrete"] = capability_binding(
            basis_key,
            _concrete_capability(str(concrete_method or "")),
        )
    return bindings


def _solver_edition(bindings: Mapping[str, CapabilityBinding]) -> str:
    editions = {binding.solver_edition for binding in bindings.values()}
    if len(editions) != 1:
        raise ValueError(
            "selected fatigue capabilities do not share one solver edition"
        )
    return next(iter(editions))


def calculation_references(
    fatigue_edition: object,
    concrete_method: str = CONCRETE_MINER,
) -> dict[str, str]:
    """Return the explicit steel and concrete fatigue-method references."""

    basis_key = parse_design_basis_key(fatigue_edition)
    reinforcement = capability_binding(
        basis_key,
        Capability.REINFORCEMENT_FATIGUE,
    )
    project_miner = concrete_method == CONCRETE_PROJECT_MINER
    if project_miner:
        concrete_reference = (
            "Project-defined concrete Miner S-N relation (uncited)"
        )
    else:
        concrete_reference = capability_binding(
            basis_key,
            _concrete_capability(concrete_method),
        ).source
    return {
        "reinforcement": reinforcement.source,
        "concrete": concrete_reference,
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


def _proof_stresses(
    inp: Mapping,
    records: Sequence[Mapping],
    materials: Sequence,
    kind: str,
    errors: list[str],
) -> list[float | None]:
    """Resolve explicit characteristic yield/proof stress per element.

    Built-in prestressing curves 1-5 intentionally do not use ``fytk`` in their
    polynomial material law. Their material-catalogue entry nevertheless carries
    the editable ``f_p0.1k`` needed by the independent fatigue yield assessment.
    """

    catalog_entries = {}
    catalog_key = mat_catalog.catalog_key(kind)
    if inp.get(catalog_key) is not None:
        catalog_entries = mat_catalog.entry_map(inp[catalog_key], kind)

    output: list[float | None] = []
    for index, record in enumerate(records):
        material = materials[index] if index < len(materials) else None
        if not isinstance(record, Mapping) or material is None:
            output.append(None)
            continue
        element_id = str(record.get("id") or kind).strip()
        strength = getattr(material, "fytk", None)
        if kind == fatigue_inputs.PRESTRESS:
            material_id = str(record.get("material_id") or "").strip()
            entry = catalog_entries.get(material_id)
            if entry is not None:
                catalog_strength = entry.get("fytk")
                try:
                    if (
                        math.isfinite(float(catalog_strength))
                        and float(catalog_strength) > 0.0
                    ):
                        strength = catalog_strength
                except (TypeError, ValueError):
                    pass
        output.append(_finite_attribute(
            strength,
            f"{element_id}: characteristic yield/proof stress",
            errors,
            positive=True,
        ))
    return output


def _assigned_detail_records(
    records: Sequence[Mapping],
    details: Mapping[str, Mapping],
) -> tuple[Mapping, ...]:
    """Return each assigned fatigue detail once, in solver-element order."""

    output = []
    seen = set()
    for record in records:
        if not isinstance(record, Mapping):
            continue
        detail_id = str(record.get("fatigue_detail_id") or "").strip()
        if not detail_id or detail_id in seen or detail_id not in details:
            continue
        seen.add(detail_id)
        detail = details[detail_id]
        output.append({
            **{field: detail[field] for field in fatigue_inputs.DETAIL_FIELDS},
            "edition": fatigue_inputs.preset_edition(detail["preset"]),
            "custom": detail["preset"] == fatigue_inputs.CUSTOM_PRESET,
        })
    return tuple(output)


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
    else:
        try:
            section.require_valid_geometry()
        except GeometryTopologyError as exc:
            errors.append(f"Invalid section geometry: {exc}")
            section = None
    for key in ("geometry_error", "void_error", "steel_error", "material_error"):
        if inp.get(key):
            errors.append(str(inp[key]))

    check_reinforcement = bool(inp.get("fatigue_check_steel"))
    check_concrete = bool(inp.get("fatigue_check_concrete"))
    concrete_method = str(
        inp.get("fatigue_concrete_method") or CONCRETE_MINER
    )
    concrete_method_valid = concrete_method in CONCRETE_METHODS
    try:
        basis_key = parse_design_basis_key(inp.get("fatigue_edition"))
    except ValueError as exc:
        errors.append(str(exc))
        basis_key = None
    solver_edition = ""
    if basis_key is not None and (
        check_reinforcement or (check_concrete and concrete_method_valid)
    ):
        try:
            solver_edition = _solver_edition(
                _selected_capability_bindings(
                    basis_key,
                    check_reinforcement=check_reinforcement,
                    check_concrete=check_concrete,
                    concrete_method=concrete_method,
                )
            )
        except ValueError as exc:
            errors.append(str(exc))
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
        if not concrete_method_valid:
            errors.append("Select a valid concrete fatigue method")
        _positive(inp.get("fatigue_gamma_c"), "gamma_c,fat", errors)
        _positive(inp.get("fatigue_beta_cc_t0"), "beta_cc(t0)", errors)
        _positive(inp.get("fatigue_t0_days"), "Concrete age t0", errors)
        if concrete_method in CONCRETE_MINER_METHODS:
            _positive(
                inp.get("fatigue_concrete_c"),
                "Concrete fatigue C",
                errors,
            )
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
            if solver_edition and solver_edition != fatigue_inputs.EC2_2023:
                _finite_attribute(
                    getattr(concrete, "alpha_cc", None),
                    "Concrete alpha_cc",
                    errors,
                    positive=True,
                )
        if solver_edition and solver_edition != fatigue_inputs.EC2_2023:
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
        # Built-in curves 1-5 obtain the fatigue proof stress from the assigned
        # material-catalogue entry rather than the polynomial material object.
        require_strength=False,
    )
    if check_reinforcement:
        _proof_stresses(
            inp,
            tendons,
            tendon_materials,
            fatigue_inputs.PRESTRESS,
            errors,
        )

    details, _catalog = _detail_data(inp, errors)
    if check_reinforcement:
        selected_family = (
            fatigue_inputs.EC2_2023
            if solver_edition == fatigue_inputs.EC2_2023
            else fatigue_inputs.EC2_2005 if solver_edition else None
        )
        basis_label = (
            get_design_basis(basis_key).label
            if basis_key is not None
            else "unregistered fatigue basis"
        )
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
                else:
                    detail_edition = fatigue_inputs.preset_edition(
                        detail["preset"]
                    )
                    if (
                        detail_edition is not None
                        and selected_family is not None
                        and detail_edition != selected_family
                    ):
                        errors.append(
                            f"{element_id}: fatigue detail '{detail_id}' uses "
                            f"{detail_edition} resistance with {basis_label}; "
                            "select an edition-aligned preset or identify the "
                            "detail as Custom / imported"
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
    if (
        bool(inp.get("fatigue_check_concrete"))
        and inp.get("fatigue_concrete_method") == CONCRETE_PROJECT_MINER
    ):
        warnings.append(
            "Project-defined concrete Miner S-N relation is used (uncited)"
        )
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
            if detail is None:
                continue
            source = str(detail.get("source") or "").strip()
            if not source:
                warnings.append(
                    f"{detail_id}: fatigue resistance source is not stated"
                )
            if detail.get("preset") == fatigue_inputs.CUSTOM_PRESET:
                warnings.append(
                    f"{detail_id}: custom/imported fatigue resistance is used"
                    + (f" (source: {source})" if source else "")
                )
    return list(dict.fromkeys(warnings))


def invalid_result(
    inp: Mapping,
    errors: Sequence[str] | None = None,
) -> dict:
    """Return a calculation-free INVALID payload without changing ``inp``.

    Fatigue input is allowed to be incomplete while the engineer develops the
    section.  The application can still calculate independent results and use
    this payload to preserve a visible, reportable failure of the fatigue
    preflight instead of blocking the complete calculation.
    """

    unique_errors = tuple(dict.fromkeys(
        str(error).strip()
        for error in (errors if errors is not None else validation_errors(inp))
        if str(error).strip()
    ))
    try:
        basis = fatigue_inputs.normalise_basis(
            inp.get(fatigue_inputs.BASIS_KEY)
        )
    except (TypeError, ValueError):
        basis = fatigue_inputs.default_basis()
    raw_basis_key = inp.get("fatigue_edition")
    try:
        basis_key = parse_design_basis_key(raw_basis_key)
        design_basis = get_design_basis(basis_key)
    except ValueError:
        basis_key = None
        design_basis = None
    solver_edition = None
    if basis_key is not None:
        try:
            selected_bindings = _selected_capability_bindings(
                basis_key,
                check_reinforcement=bool(inp.get("fatigue_check_steel")),
                check_concrete=bool(inp.get("fatigue_check_concrete")),
                concrete_method=str(
                    inp.get("fatigue_concrete_method") or CONCRETE_MINER
                ),
            )
            if selected_bindings:
                solver_edition = _solver_edition(selected_bindings)
        except ValueError:
            pass
    method = str(basis.get("method") or "")
    return {
        "valid": False,
        "converged": False,
        "passed": False,
        "errors": unique_errors,
        "warnings": tuple(validation_warnings(inp)),
        "basis_key": (
            basis_key.value
            if basis_key is not None
            else str(raw_basis_key or "-")
        ),
        "basis_label": design_basis.label if design_basis is not None else "-",
        "basis_disclosure": (
            design_basis.disclosure if design_basis is not None else ""
        ),
        "edition": design_basis.label if design_basis is not None else "-",
        "solver_edition": solver_edition,
        "checks": {
            "reinforcement": bool(inp.get("fatigue_check_steel")),
            "concrete": bool(inp.get("fatigue_check_concrete")),
        },
        "basis": dict(basis),
        "method_reference": fatigue_inputs.METHOD_REFERENCES.get(
            method, "-"
        ),
        "calculation_references": {},
        "capability_bindings": {},
        "partial_factors": {
            "gamma_c": inp.get("fatigue_gamma_c"),
            "gamma_s": inp.get("fatigue_gamma_s"),
            "gamma_ff": inp.get("fatigue_gamma_ff"),
        },
        "concrete_parameters": None,
        "fatigue_detail_basis": (),
        "t0_days": inp.get("fatigue_t0_days"),
        "elements": tuple(dict(record) for records in _records(inp)
                          for record in records if isinstance(record, Mapping)),
        "spectra": (),
        "governing_spectrum": None,
        "utilisation": None,
    }


def _reinforcement_properties(
    records: Sequence[Mapping],
    materials: Sequence,
    proof_stresses: Sequence[float],
    details: Mapping[str, Mapping],
    kind: str,
    basis_key: DesignBasisKey,
) -> list[ReinforcementFatigueProperties]:
    output = []
    for record, material, proof_stress in zip(
        records,
        materials,
        proof_stresses,
    ):
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
        screen_rule = SimplifiedReinforcementFatigueRule(
            **fatigue_inputs.simplified_reinforcement_screen_rule(
                detail,
                diameter,
                basis_key,
            )
        )
        output.append(ReinforcementFatigueProperties(
            element_id=str(record["id"]).strip(),
            kind=kind,
            detail_id=str(detail["id"]),
            diameter_mm=diameter,
            n_star=float(detail["n_star"]),
            k1=float(detail["k1"]),
            k2=float(detail["k2"]),
            delta_sigma_rsk_mpa=reference_range,
            fytk_mpa=float(proof_stress),
            fyck_mpa=(
                float(material.fyck)
                if kind == fatigue_inputs.MILD
                else None
            ),
            bond_ratio_xi=(bond_ratio if bond_ratio > 0.0 else None),
            bond_equivalent_diameter_mm=(
                bond_diameter if bond_diameter > 0.0 else None
            ),
            simplified_screen_rule=screen_rule,
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
    basis_key = parse_design_basis_key(inp.get("fatigue_edition"))
    check_reinforcement = bool(inp.get("fatigue_check_steel"))
    check_concrete = bool(inp.get("fatigue_check_concrete"))
    concrete_method = (
        str(inp.get("fatigue_concrete_method") or CONCRETE_MINER)
        if check_concrete
        else None
    )
    proof_errors: list[str] = []
    bar_proof_stresses = (
        _proof_stresses(
            inp,
            bars,
            bar_materials,
            fatigue_inputs.MILD,
            proof_errors,
        )
        if check_reinforcement
        else []
    )
    tendon_proof_stresses = (
        _proof_stresses(
            inp,
            tendons,
            tendon_materials,
            fatigue_inputs.PRESTRESS,
            proof_errors,
        )
        if check_reinforcement
        else []
    )
    if proof_errors:
        # ``validation_errors`` has already checked these values. Keep this
        # defensive guard at the preparation boundary for custom integrations.
        raise ValueError("; ".join(proof_errors))
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
            bar_proof_stresses,
            details,
            fatigue_inputs.MILD,
            basis_key,
        )
        + _reinforcement_properties(
            tendons,
            tendon_materials,
            tendon_proof_stresses,
            details,
            fatigue_inputs.PRESTRESS,
            basis_key,
        )
        if check_reinforcement
        else []
    )

    design_basis = get_design_basis(basis_key)
    selected_bindings = _selected_capability_bindings(
        basis_key,
        check_reinforcement=check_reinforcement,
        check_concrete=check_concrete,
        concrete_method=concrete_method,
    )
    solver_edition = _solver_edition(selected_bindings)
    is_2023 = solver_edition == fatigue_inputs.EC2_2023
    concrete = (
        ConcreteFatigueProperties(
            edition=solver_edition,
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
            c=float(inp.get("fatigue_concrete_c") or 14.0),
            method=concrete_method,
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
        basis_key=basis_key,
        basis_label=design_basis.label,
        basis_disclosure=design_basis.disclosure,
        solver_edition=solver_edition,
        solver_element_ids=tuple(
            str(record["id"]).strip() for record in bars + tendons
        ),
        element_records=tuple(dict(record) for record in bars + tendons),
        detail_records=_assigned_detail_records(bars + tendons, details),
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
        concrete_method=concrete_method,
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
    element_signature = tuple(
        tuple(
            (str(key), record[key])
            for key in sorted(record)
        )
        for record in prepared.element_records
    )
    detail_signature = tuple(
        tuple(
            (str(key), record[key])
            for key in sorted(record)
        )
        for record in prepared.detail_records
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
            (
                None
                if item.simplified_screen_rule is None
                else (
                    item.simplified_screen_rule.detail_class,
                    item.simplified_screen_rule.threshold_mpa,
                    item.simplified_screen_rule.range_basis,
                    item.simplified_screen_rule.source,
                    item.simplified_screen_rule.max_cycles,
                    item.simplified_screen_rule.reason,
                )
            ),
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
            prepared.concrete.method,
        )
    )
    return (
        section_signature,
        element_signature,
        detail_signature,
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
        prepared.basis_key.value,
        prepared.solver_edition,
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
        prepared.warnings,
        prepared.concrete_method,
    )


def _worked_example_metric(value: object) -> float | None:
    """Return an eligible retained utilisation for publication selection."""

    try:
        metric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(metric) or metric == -math.inf or metric < 0.0:
        return None
    return metric


def _global_reinforcement_example(results: Sequence[object]) -> dict | None:
    """Select one authoritative reinforcement example across all spectra."""

    best = None
    for spectrum_order, spectrum in enumerate(results):
        states = tuple(getattr(spectrum, "bins", ()) or ())
        if not states or not all(
            bool(getattr(state, "converged", False)) for state in states
        ):
            continue
        element_id = getattr(spectrum, "governing_reinforcement_id", None)
        if element_id is None:
            continue
        selected = next(
            (
                item
                for item in tuple(getattr(spectrum, "reinforcement", ()) or ())
                if getattr(item, "element_id", None) == element_id
            ),
            None,
        )
        if selected is None or not bool(getattr(selected, "converged", False)):
            continue
        metric = _worked_example_metric(getattr(selected, "utilisation", None))
        if metric is None:
            continue
        score = (metric, -spectrum_order)
        if best is None or score > best[0]:
            best = (score, spectrum, selected)
    if best is None:
        return None
    score, spectrum, selected = best
    return {
        "spectrum_name": str(getattr(spectrum, "spectrum_name")),
        "element_id": str(getattr(selected, "element_id")),
        "utilisation": score[0],
        "criterion": str(getattr(selected, "governing_criterion", "")),
        "bin_name": str(getattr(selected, "governing_bin", "")),
    }


def _global_concrete_example(results: Sequence[object]) -> dict | None:
    """Select one authoritative concrete example across all spectra."""

    best = None
    for spectrum_order, spectrum in enumerate(results):
        states = tuple(getattr(spectrum, "bins", ()) or ())
        if not states or not all(
            bool(getattr(state, "converged", False)) for state in states
        ):
            continue
        fibre_index = getattr(spectrum, "governing_concrete_fibre", None)
        if fibre_index is None:
            continue
        selected = next(
            (
                item
                for item in tuple(getattr(spectrum, "concrete", ()) or ())
                if getattr(item, "fibre_index", None) == fibre_index
            ),
            None,
        )
        if selected is None or not bool(getattr(selected, "converged", False)):
            continue
        fixed_metric = _worked_example_metric(
            getattr(selected, "utilisation", None)
        )
        if fixed_metric is None:
            continue
        search = getattr(spectrum, "concrete_search", None)
        if search is not None and not bool(getattr(search, "converged", False)):
            continue
        search_metric = (
            _worked_example_metric(getattr(search, "upper_damage", None))
            if search is not None else None
        )
        if search is not None and search_metric is None:
            continue
        search_governs = bool(
            search_metric is not None and search_metric > fixed_metric
        )
        metric = search_metric if search_governs else fixed_metric
        score = (metric, -spectrum_order)
        if best is None or score > best[0]:
            best = (score, spectrum, selected, search_governs)
    if best is None:
        return None
    score, spectrum, selected, search_governs = best
    method = str(getattr(spectrum, "concrete_method", ""))
    if search_governs:
        criterion = (
            "Equivalent amplitude upper bound"
            if method == CONCRETE_EQUIVALENT
            else "Miner damage upper bound"
        )
    else:
        criterion = str(getattr(selected, "governing_criterion", ""))
    return {
        "spectrum_name": str(getattr(spectrum, "spectrum_name")),
        "fibre_index": int(getattr(selected, "fibre_index")),
        "utilisation": score[0],
        "criterion": criterion,
        "bin_name": str(getattr(selected, "governing_bin", "")),
        "search_upper_bound_governs": search_governs,
    }


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
        fatigue_edition=prepared.solver_edition,
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
    miner_values = [
        float(value)
        for result in results
        if (value := getattr(result, "miner_damage", None)) is not None
    ]
    miner_damage = max(miner_values) if miner_values else None
    yield_values = [
        float(value)
        for result in results
        if (value := getattr(result, "yield_utilisation", None)) is not None
    ]
    governing_reinforcement_example = _global_reinforcement_example(results)
    governing_concrete_example = _global_concrete_example(results)
    references = calculation_references(
        prepared.basis_key,
        prepared.concrete_method or CONCRETE_MINER,
    )
    selected_bindings = _selected_capability_bindings(
        prepared.basis_key,
        check_reinforcement=prepared.check_reinforcement,
        check_concrete=prepared.check_concrete,
        concrete_method=prepared.concrete_method,
    )
    standard_evidence_bindings = dict(selected_bindings)
    if prepared.concrete_method == CONCRETE_PROJECT_MINER:
        # The selected basis still controls the shared concrete-strength solver
        # edition. The user-defined S-N relation is not, however, evidence of a
        # registered Eurocode damage-sum implementation.
        standard_evidence_bindings.pop("concrete", None)
    if (
        prepared.check_reinforcement
        and any(record["custom"] for record in prepared.detail_records)
    ):
        references["reinforcement"] += (
            "; assigned custom/imported S-N resistance sources are listed "
            "separately"
        )
    return {
        "basis_key": prepared.basis_key.value,
        "basis_label": prepared.basis_label,
        "basis_disclosure": prepared.basis_disclosure,
        "edition": prepared.basis_label,
        "solver_edition": prepared.solver_edition,
        "checks": {
            "reinforcement": prepared.check_reinforcement,
            "concrete": prepared.check_concrete,
        },
        "concrete_method": prepared.concrete_method,
        "basis": dict(prepared.basis),
        "method_reference": fatigue_inputs.METHOD_REFERENCES[
            prepared.basis["method"]
        ],
        "calculation_references": {
            key: value
            for key, value in references.items()
            if (
                (key == "reinforcement" and prepared.check_reinforcement)
                or (key == "concrete" and prepared.check_concrete)
            )
        },
        "capability_bindings": {
            key: {
                "capability": binding.capability.value,
                "source": references[key],
                "disclosure": binding.disclosure,
            }
            for key, binding in standard_evidence_bindings.items()
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
                "method": prepared.concrete.method,
            }
            if prepared.concrete is not None
            else None
        ),
        "reinforcement_properties": prepared.reinforcement,
        "fatigue_detail_basis": prepared.detail_records,
        "t0_days": prepared.t0_days,
        "elements": prepared.element_records,
        "spectra": results,
        "governing_spectrum": governing.spectrum_name,
        "governing_domain": getattr(governing, "governing_domain", None),
        "governing_criterion": getattr(governing, "governing_criterion", None),
        "governing_reinforcement_id": getattr(
            governing,
            "governing_reinforcement_id",
            None,
        ),
        "governing_concrete_fibre": getattr(
            governing,
            "governing_concrete_fibre",
            None,
        ),
        "governing_reinforcement_example": governing_reinforcement_example,
        "governing_concrete_example": governing_concrete_example,
        "miner_damage": miner_damage,
        "yield_utilisation": max(yield_values) if yield_values else None,
        "utilisation": governing.utilisation,
        "converged": all(result.converged for result in results),
        "passed": all(result.passed for result in results),
    }
