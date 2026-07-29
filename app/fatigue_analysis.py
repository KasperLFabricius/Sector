"""Pure application boundary for Sector's grouped fatigue engine.

The Streamlit layer owns widgets and presentation.  This module validates the
complete application input, resolves per-element material and fatigue-detail
assignments, converts the UI's tension-positive normal force exactly once, and
calls :mod:`sector.fatigue`.

Authority selections are retained as provenance and QA warnings only. No
traffic, dynamic or concurrence factor is inferred. Material-factor presets are
resolved only from the selected edition and explicit gamma0/gamma3 inputs; a
user-approved final override is passed through unchanged and reported.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import math

import numpy as np

import fatigue_inputs
import load_cases
import material_catalog as mat_catalog
from sector import bridge, conformance
from sector.fatigue import (
    CONCRETE_EQUIVALENT,
    CONCRETE_METHODS,
    CONCRETE_MINER,
    CONCRETE_MINER_METHODS,
    CONCRETE_PROJECT_MINER,
    ConcreteFatigueProperties,
    FatigueSpectrumResult,
    ReinforcementFatigueProperties,
    SpectrumBin,
    analyse_grouped_spectra,
)
from sector.geometry import GeometryTopologyError
from sector.section import Section


STEEL_REFERENCE_MODULUS_MPA = 200_000.0
FATIGUE_CONFORMANCE_SCHEMA = "sector.fatigue-conformance-evidence/v2"
_FATIGUE_CONFORMANCE_FIELDS = (
    "valid",
    "converged",
    "passed",
    "errors",
    "edition",
    "design_methodology",
    "checks",
    "concrete_method",
    "concrete_miner_basis",
    "concrete_miner_source",
    "basis",
    "partial_factors",
    "factor_basis",
    "parameter_conformance",
    "conformance",
    "assessment_status",
    "qualified_verdict",
    "standard_passed",
    "concrete_parameters",
)


def _json_equivalent(left, right) -> bool:
    """Compare evidence by its canonical JSON representation."""

    try:
        return json.dumps(
            left,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ) == json.dumps(
            right,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError):
        return False


def _numeric_equivalent(left, right) -> bool:
    """Compare finite real evidence without equating Booleans to numbers."""

    if conformance.is_boolean(left) or conformance.is_boolean(right):
        return False
    try:
        left_value = float(left)
        right_value = float(right)
    except (TypeError, ValueError):
        return False
    return (
        math.isfinite(left_value)
        and math.isfinite(right_value)
        and math.isclose(
            left_value,
            right_value,
            rel_tol=0.0,
            abs_tol=1.0e-12,
        )
    )


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
    factor_basis: Mapping
    warnings: tuple[str, ...]
    design_methodology: str
    concrete_method: str | None
    concrete_miner_basis: str | None
    concrete_miner_source: str
    parameter_conformance: tuple[Mapping, ...]


def _positive(value, label: str, errors: list[str]) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        errors.append(f"{label} must be a finite number greater than zero")
        return None
    if not math.isfinite(number) or number <= 0:
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


def concrete_miner_parameter_errors(
    *,
    edition: str,
    concrete_method: str,
    miner_basis: str,
    miner_source: str,
    coefficient_c,
    design_methodology: str,
) -> list[str]:
    """Return only malformed/numerically unusable Miner input errors."""

    if concrete_method not in CONCRETE_MINER_METHODS:
        return []
    errors: list[str] = []
    if conformance.is_boolean(coefficient_c):
        errors.append("Concrete fatigue C must be a finite number greater than zero")
    else:
        _positive(coefficient_c, "Concrete fatigue C", errors)
    basis = str(miner_basis or "").strip()
    if basis not in fatigue_inputs.MINER_BASES:
        errors.append("Select a valid concrete Miner method applicability")
    try:
        conformance.typed_text(
            miner_source,
            "Concrete Miner approval/source",
        )
    except ValueError as exc:
        errors.append(str(exc))
    return list(dict.fromkeys(errors))


def concrete_miner_conformance(
    *,
    edition: str,
    concrete_method: str,
    miner_basis: str,
    miner_source: str,
    coefficient_c,
    design_methodology: str,
) -> dict:
    """Return the actual concrete-Miner coefficient's authority evidence."""

    numerical_errors = concrete_miner_parameter_errors(
        edition=edition,
        concrete_method=concrete_method,
        miner_basis=miner_basis,
        miner_source=miner_source,
        coefficient_c=coefficient_c,
        design_methodology=design_methodology,
    )
    if numerical_errors:
        raise ValueError("; ".join(numerical_errors))
    basis = str(miner_basis or "").strip()
    source = conformance.typed_text(
        miner_source,
        "Concrete Miner approval/source",
    )
    bridge_standard = bool(
        concrete_method == CONCRETE_MINER
        and edition == fatigue_inputs.EC2_2_2005_AC
        and bridge.is_bridge_methodology(design_methodology)
        and basis == fatigue_inputs.MINER_BASIS_BRIDGE_STANDARD
    )
    standard_2023 = bool(
        concrete_method == CONCRETE_MINER
        and edition == fatigue_inputs.EC2_2023
        and design_methodology == bridge.COMPONENT_METHODS
        and basis == fatigue_inputs.MINER_BASIS_2023_STANDARD
    )
    project_relation = bool(
        concrete_method == CONCRETE_PROJECT_MINER
        and basis == fatigue_inputs.MINER_BASIS_PROJECT_SN_RELATION
    )
    project_adoption = bool(
        concrete_method == CONCRETE_MINER
        and basis == fatigue_inputs.MINER_BASIS_PROJECT_ADOPTION
        and design_methodology == bridge.COMPONENT_METHODS
    )
    if bridge_standard or standard_2023:
        parameter_basis = conformance.STANDARD_BASIS
        custom_methodology = ""
        approval_reference = source
        applicability_conforms = True
        applicability_note = ""
    elif project_relation:
        parameter_basis = conformance.CUSTOM_BASIS
        custom_methodology = CONCRETE_PROJECT_MINER
        approval_reference = source
        applicability_conforms = False
        applicability_note = (
            "A project S-N relation is not the selected-standard C = 14 route"
        )
    elif project_adoption:
        parameter_basis = conformance.CUSTOM_BASIS
        custom_methodology = (
            "Project-basis adoption of the corrected bridge Miner relation"
        )
        approval_reference = source
        applicability_conforms = False
        applicability_note = (
            "The bridge Miner relation is used outside its standard methodology"
        )
    else:
        # Preserve a contradictory or incomplete selection as visible REVIEW
        # evidence; do not reinterpret it as an approved custom method.
        parameter_basis = conformance.STANDARD_BASIS
        custom_methodology = (
            concrete_method
            if concrete_method == CONCRETE_PROJECT_MINER
            else (
                "Project-basis adoption"
                if basis == fatigue_inputs.MINER_BASIS_PROJECT_ADOPTION
                else ""
            )
        )
        approval_reference = source
        applicability_conforms = False
        applicability_note = (
            "Concrete Miner method, edition, whole-calculation methodology, "
            "and applicability basis are missing or contradictory"
        )
    return conformance.assess_parameter(
        coefficient_c,
        parameter_id="concrete_fatigue.miner_c",
        label="Concrete fatigue Miner coefficient C",
        selected_standard=edition,
        standard_methodology=(
            "EN 1992-1-1:2023 concrete compression Miner relation"
            if edition == fatigue_inputs.EC2_2023
            else bridge.CONCRETE_MINER_STANDARD_METHOD
        ),
        normative_source=(
            "DS/EN 1992-1-1:2023 E.5.3"
            if edition == fatigue_inputs.EC2_2023
            else bridge.CONCRETE_MINER_STANDARD_SOURCE
        ),
        basis=parameter_basis,
        custom_methodology=custom_methodology,
        approval_reference=approval_reference,
        prescribed_value=fatigue_inputs.STANDARD_CONCRETE_MINER_C,
        applicability_conforms=applicability_conforms,
        applicability_note=applicability_note,
    )


def _resolved_concrete_miner_basis(
    inp: Mapping,
    *,
    edition: str,
    design_methodology: str,
    concrete_method: str,
) -> str:
    """Resolve only absent compatibility metadata; preserve explicit choices."""

    raw_basis = inp.get("fatigue_concrete_miner_basis")
    if raw_basis not in (None, ""):
        return str(raw_basis).strip()
    if concrete_method == CONCRETE_PROJECT_MINER:
        return fatigue_inputs.MINER_BASIS_PROJECT_SN_RELATION
    if (
        edition == fatigue_inputs.EC2_2_2005_AC
        and bridge.is_bridge_methodology(design_methodology)
    ):
        return fatigue_inputs.MINER_BASIS_BRIDGE_STANDARD
    if edition == fatigue_inputs.EC2_2023:
        return fatigue_inputs.MINER_BASIS_2023_STANDARD
    return fatigue_inputs.MINER_BASIS_NOT_ESTABLISHED


def _edition(value) -> str:
    text = str(value or "").strip()
    if text in fatigue_inputs.EDITIONS:
        return text
    if "2023" in text:
        return fatigue_inputs.EC2_2023
    if "1992-2" in text and ("2005" in text or "2004" in text):
        return fatigue_inputs.EC2_2_2005_AC
    if "2005" in text or "2004" in text:
        return fatigue_inputs.EC2_2005
    raise ValueError(
        "fatigue edition must identify DS/EN 1992-1-1:2005, "
        "DK NA:2024, DS/EN 1992-2:2005 + AC:2008, or "
        "DS/EN 1992-1-1:2023"
    )


def _design_methodology(value, *, allow_default: bool = True) -> str:
    if value is None and allow_default:
        return bridge.COMPONENT_METHODS
    if not isinstance(value, str):
        raise ValueError("Select a valid whole-calculation design methodology")
    methodology = value.strip()
    if not methodology and allow_default:
        return bridge.COMPONENT_METHODS
    if methodology not in bridge.METHODOLOGIES:
        raise ValueError("Select a valid whole-calculation design methodology")
    return methodology


def _factor_mode(inp: Mapping) -> tuple[str, bool]:
    """Return ``(mode, explicit)`` with a compatibility path for API callers."""
    raw = inp.get("fatigue_factor_mode")
    if raw in (None, ""):
        # Before project v15 the numeric controls were already complete user
        # inputs, but they carried no factor-specific approval. Treat them as
        # legacy/review-required unless a headless integration now supplies the
        # dedicated approval source. Project migration applies the same rule to
        # saved values.
        if (
            inp.get("fatigue_gamma_s") is not None
            or inp.get("fatigue_gamma_c") is not None
        ):
            return (
                fatigue_inputs.FACTOR_MODE_OVERRIDE
                if str(inp.get("fatigue_factor_approval") or "").strip()
                else fatigue_inputs.FACTOR_MODE_LEGACY
            ), False
        return fatigue_inputs.FACTOR_MODE_PRESET, False
    return str(raw), True


def _resolved_factor_basis(inp: Mapping, edition: str) -> tuple[float, float, dict]:
    mode, explicit = _factor_mode(inp)
    gamma0 = inp.get("fatigue_gamma0", 1.0)
    gamma3 = inp.get("fatigue_gamma3", 1.0)
    gamma_s = inp.get("fatigue_gamma_s")
    gamma_c = inp.get("fatigue_gamma_c")
    if mode in {
        fatigue_inputs.FACTOR_MODE_OVERRIDE,
        fatigue_inputs.FACTOR_MODE_LEGACY,
    }:
        # Single-check integrations only need the factor that is used. Supply
        # the inactive side from the edition preset so that compatibility path
        # remains valid after project serialization makes the mode explicit.
        # Enabling that check later still requires its own supplied factor.
        preset = fatigue_inputs.fatigue_factor_preset(
            edition,
            gamma0=gamma0,
            gamma3=gamma3,
        )
        if gamma_s is None and not bool(inp.get("fatigue_check_steel")):
            gamma_s = preset["gamma_s"]
        if gamma_c is None and not bool(inp.get("fatigue_check_concrete")):
            gamma_c = preset["gamma_c"]
    approval_reference = (
        inp.get("fatigue_factor_approval")
        if mode == fatigue_inputs.FACTOR_MODE_OVERRIDE
        else ""
    )
    gamma_s, gamma_c, basis = fatigue_inputs.resolve_fatigue_factors(
        edition,
        mode=mode,
        gamma_s=gamma_s,
        gamma_c=gamma_c,
        gamma0=gamma0,
        gamma3=gamma3,
        approval_reference=approval_reference,
    )
    basis["mode_explicit"] = explicit
    return gamma_s, gamma_c, basis


def bridge_publication_context(inp: Mapping | None) -> dict:
    """Reconstruct the bridge-fatigue authority context from current inputs.

    Bridge result evidence is stored separately from the live calculation input
    snapshot.  Publication compares its nested records with this canonical
    reconstruction so a self-consistent stale body cannot establish current
    factor, method, source, or approval authority.
    """

    errors: list[str] = []
    source = inp if isinstance(inp, Mapping) else {}
    if not isinstance(inp, Mapping):
        errors.append("current calculation inputs are missing or malformed")

    def current_bool(key: str, *, default: bool = False) -> bool:
        value = source.get(key, default)
        if not isinstance(value, bool):
            errors.append(f"current fatigue input {key} is not typed Boolean")
            return False
        return value

    fatigue_on = current_bool("fatigue_on")
    reinforcement_on = current_bool("fatigue_check_steel")
    concrete_on = current_bool("fatigue_check_concrete")
    checks = {
        "reinforcement": fatigue_on and reinforcement_on,
        "concrete": fatigue_on and concrete_on,
    }
    try:
        raw_basis = source.get(fatigue_inputs.BASIS_KEY)
        basis = (
            fatigue_inputs.default_basis()
            if raw_basis is None and not any(checks.values())
            else fatigue_inputs.canonical_basis(raw_basis)
        )
    except (TypeError, ValueError) as exc:
        basis = fatigue_inputs.default_basis()
        errors.append(f"current fatigue calculation basis is invalid: {exc}")
    try:
        design_methodology = _design_methodology(
            source.get("design_methodology"),
            allow_default=False,
        )
    except ValueError as exc:
        design_methodology = ""
        errors.append(str(exc))

    edition = ""
    factor_mode = ""
    factor_approval = ""
    concrete_method = ""
    concrete_miner_basis = ""
    concrete_miner_source = ""
    gamma_ff = None
    parameter_records: list[Mapping] = []
    if any(checks.values()):
        raw_gamma_ff = source.get("fatigue_gamma_ff")
        if conformance.is_boolean(raw_gamma_ff):
            errors.append(
                "current fatigue action factor gamma_Ff must be a finite "
                "number greater than zero"
            )
        else:
            gamma_ff_errors: list[str] = []
            gamma_ff = _positive(
                raw_gamma_ff,
                "current fatigue action factor gamma_Ff",
                gamma_ff_errors,
            )
            errors.extend(gamma_ff_errors)
        try:
            edition = _edition(source.get("fatigue_edition"))
            _gamma_s, _gamma_c, factor_basis = _resolved_factor_basis(
                source,
                edition,
            )
            factor_mode = str(factor_basis.get("mode") or "")
            factor_approval = str(
                factor_basis.get("approval_reference") or ""
            )
            factor_records = factor_basis.get("parameter_conformance")
            if not isinstance(factor_records, Mapping):
                raise ValueError(
                    "current fatigue factor conformance is malformed"
                )
            if checks["reinforcement"]:
                parameter_records.append(factor_records["gamma_s"])
            if checks["concrete"]:
                parameter_records.append(factor_records["gamma_c"])
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"current fatigue factor context is invalid: {exc}")
    if checks["concrete"]:
        concrete_method = str(
            source.get("fatigue_concrete_method") or CONCRETE_MINER
        ).strip()
        concrete_miner_source = (
            source.get("fatigue_concrete_miner_source")
        )
        try:
            concrete_miner_source = conformance.typed_text(
                concrete_miner_source,
                "Concrete Miner approval/source",
            )
            concrete_miner_basis = _resolved_concrete_miner_basis(
                source,
                edition=edition,
                design_methodology=design_methodology,
                concrete_method=concrete_method,
            )
            if concrete_method not in CONCRETE_MINER_METHODS:
                raise ValueError(
                    "bridge concrete fatigue requires an explicit Miner/S-N "
                    "method"
                )
            parameter_records.append(concrete_miner_conformance(
                edition=edition,
                concrete_method=concrete_method,
                miner_basis=concrete_miner_basis,
                miner_source=concrete_miner_source,
                coefficient_c=source.get("fatigue_concrete_c"),
                design_methodology=design_methodology,
            ))
        except (TypeError, ValueError) as exc:
            errors.append(
                f"current concrete-fatigue context is invalid: {exc}"
            )
    return {
        "schema": bridge.FATIGUE_PUBLICATION_CONTEXT_SCHEMA,
        "design_methodology": design_methodology,
        "edition": edition,
        "checks": checks,
        "factor_mode": factor_mode,
        "factor_approval": factor_approval,
        "gamma_ff": gamma_ff,
        "concrete_method": concrete_method,
        "concrete_miner_basis": concrete_miner_basis,
        "concrete_miner_source": concrete_miner_source,
        "parameter_conformance": list(parameter_records),
        "basis": dict(basis),
        "errors": list(dict.fromkeys(errors)),
    }


def bridge_result_context_errors(
    payload: Mapping | None,
    context: Mapping | None,
    *,
    check_key: str,
) -> tuple[str, ...]:
    """Correlate calculated fatigue evidence with current bridge inputs.

    The fatigue payload is independently self-validating, but that cannot prove
    that it was calculated from the inputs which are current now. This adapter
    gate binds the complete active factor/method record set to the same
    canonical context used by bridge publication.
    """

    if check_key not in {"reinforcement", "concrete"}:
        return ("bridge fatigue adapter check is missing or unknown",)
    current, context_errors = bridge.validate_fatigue_publication_context(
        context,
        design_methodology=(
            context.get("design_methodology")
            if isinstance(context, Mapping)
            else None
        ),
    )
    errors = list(context_errors)
    if not isinstance(payload, Mapping):
        errors.append("calculated fatigue evidence is missing or malformed")
        return tuple(dict.fromkeys(errors))
    if current is None:
        return tuple(dict.fromkeys(errors))

    payload_checks = payload.get("checks")
    if (
        not isinstance(payload_checks, Mapping)
        or set(payload_checks) != {"reinforcement", "concrete"}
        or not all(
            isinstance(payload_checks.get(key), bool)
            for key in ("reinforcement", "concrete")
        )
    ):
        errors.append(
            "calculated fatigue check selection is missing or malformed"
        )
    elif not _json_equivalent(
        dict(payload_checks),
        current["checks"],
    ):
        errors.append(
            "calculated fatigue check selection conflicts with current "
            "fatigue inputs"
        )
    current_enabled = current["checks"].get(check_key)
    payload_enabled = (
        payload_checks.get(check_key)
        if isinstance(payload_checks, Mapping)
        else None
    )
    if current_enabled is not True and payload_enabled is True:
        errors.append(
            f"current bridge inputs do not enable {check_key} fatigue"
        )
    if (
        payload.get("design_methodology")
        != current["design_methodology"]
    ):
        errors.append(
            "calculated fatigue evidence is not bound to the current "
            "EN 1992-2 whole-calculation methodology"
        )
    if payload.get("edition") != current["edition"]:
        errors.append(
            "calculated fatigue edition conflicts with current fatigue inputs"
        )
    payload_basis = payload.get("basis")
    if (
        not isinstance(payload_basis, Mapping)
        or set(payload_basis) != set(fatigue_inputs.BASIS_FIELDS)
    ):
        errors.append(
            "calculated fatigue basis is missing, malformed, or incomplete"
        )
    elif not _json_equivalent(
        dict(payload_basis),
        current["basis"],
    ):
        errors.append(
            "calculated fatigue basis conflicts with current fatigue inputs"
        )

    expected_ids = []
    if current["checks"]["reinforcement"]:
        expected_ids.append("fatigue.gamma_s")
    if current["checks"]["concrete"]:
        expected_ids.extend((
            "fatigue.gamma_c",
            "concrete_fatigue.miner_c",
        ))
    expected_records = [
        current["records_by_id"][parameter_id]
        for parameter_id in expected_ids
    ]
    if not _json_equivalent(
        payload.get("parameter_conformance"),
        expected_records,
    ):
        errors.append(
            "calculated fatigue parameter records conflict with current "
            "fatigue factor/method conformance"
        )

    factor_basis = payload.get("factor_basis")
    partial_factors = payload.get("partial_factors")
    if not isinstance(factor_basis, Mapping):
        errors.append("calculated fatigue factor basis is malformed")
    if not isinstance(partial_factors, Mapping):
        errors.append("calculated fatigue partial factors are malformed")
    elif not _numeric_equivalent(
        partial_factors.get("gamma_ff"),
        current["gamma_ff"],
    ):
        errors.append(
            "calculated fatigue action factor gamma_Ff conflicts with current "
            "fatigue inputs"
        )
    if isinstance(factor_basis, Mapping):
        if factor_basis.get("mode") != current["factor_mode"]:
            errors.append(
                "calculated fatigue factor mode conflicts with current "
                "fatigue factor mode"
            )
        if (
            factor_basis.get("approval_reference")
            != current["factor_approval"]
        ):
            errors.append(
                "calculated fatigue factor approval conflicts with current "
                "fatigue factor approval"
            )
        factor_records = factor_basis.get("parameter_conformance")
        if not isinstance(factor_records, Mapping):
            errors.append(
                "calculated fatigue factor conformance is malformed"
            )
        else:
            for factor_key, parameter_id in (
                ("gamma_s", "fatigue.gamma_s"),
                ("gamma_c", "fatigue.gamma_c"),
            ):
                if parameter_id not in current["records_by_id"]:
                    continue
                expected_record = current["records_by_id"][parameter_id]
                if not _json_equivalent(
                    factor_records.get(factor_key),
                    expected_record,
                ):
                    errors.append(
                        f"calculated fatigue {factor_key} conformance "
                        "conflicts with current fatigue factor conformance"
                    )
                expected_value = expected_record.get("actual_value")
                if not _numeric_equivalent(
                    factor_basis.get(factor_key),
                    expected_value,
                ):
                    errors.append(
                        f"calculated fatigue {factor_key} conflicts with "
                        "current fatigue factor value"
                    )
                if (
                    isinstance(partial_factors, Mapping)
                    and not _numeric_equivalent(
                        partial_factors.get(factor_key),
                        expected_value,
                    )
                ):
                    errors.append(
                        f"calculated fatigue partial factor {factor_key} "
                        "conflicts with current fatigue factor value"
                    )

    if current["checks"]["concrete"]:
        for payload_key, current_key, label in (
            ("concrete_method", "concrete_method", "method"),
            (
                "concrete_miner_basis",
                "concrete_miner_basis",
                "Miner basis conformance",
            ),
            (
                "concrete_miner_source",
                "concrete_miner_source",
                "Miner source/approval",
            ),
        ):
            if payload.get(payload_key) != current[current_key]:
                errors.append(
                    f"calculated concrete-fatigue {label} conflicts with "
                    "current fatigue inputs"
                )
        concrete_parameters = payload.get("concrete_parameters")
        expected_miner = current["records_by_id"].get(
            "concrete_fatigue.miner_c"
        )
        if not isinstance(concrete_parameters, Mapping):
            errors.append(
                "calculated concrete-fatigue parameters are malformed"
            )
        else:
            if (
                concrete_parameters.get("method")
                != current["concrete_method"]
            ):
                errors.append(
                    "calculated concrete-fatigue parameter method conflicts "
                    "with current fatigue inputs"
                )
            if not _numeric_equivalent(
                concrete_parameters.get("c"),
                (
                    expected_miner.get("actual_value")
                    if isinstance(expected_miner, Mapping)
                    else None
                ),
            ):
                errors.append(
                    "current and calculated concrete Miner coefficients "
                    "conflict"
                )
            if not _json_equivalent(
                concrete_parameters.get("parameter_conformance"),
                expected_miner,
            ):
                errors.append(
                    "calculated concrete Miner conformance conflicts with "
                    "current fatigue inputs"
                )
    return tuple(dict.fromkeys(errors))


def calculation_references(
    edition: str,
    concrete_method: str = CONCRETE_MINER,
    concrete_miner_basis: str | None = None,
    concrete_miner_source: str = "",
) -> dict[str, str]:
    """Return the explicit steel and concrete fatigue-method references."""

    selected = _edition(edition)
    project_relation = concrete_method == CONCRETE_PROJECT_MINER
    equivalent = concrete_method == CONCRETE_EQUIVALENT
    national = (
        " with DK NA:2024 resolved final factors"
        if selected == fatigue_inputs.EC2_2005_DKNA
        else ""
    )
    if project_relation:
        return {
            "reinforcement": (
                "DS/EN 1992-1-1:2023, Annex E.5 and Tables E.1/E.2"
                if "2023" in selected
                else (
                    "DS/EN 1992-1-1:2005+A1:2014, clause 6.8.4 and "
                    f"Tables 6.3N/6.4N{national}"
                )
            ),
            "concrete": (
                "Approved project concrete fatigue S-N relation; source: "
                + str(concrete_miner_source or "").strip()
            ),
        }
    if "2023" in selected:
        return {
            "reinforcement": (
                "DS/EN 1992-1-1:2023, Annex E.5 and Tables E.1/E.2"
            ),
            "concrete": (
                "DS/EN 1992-1-1:2023, E.4.3, Formula (E.2)"
                if equivalent
                else "DS/EN 1992-1-1:2023, E.5.3, Formulae (E.7)-(E.8)"
            ),
        }
    bridge_standard = (
        selected == fatigue_inputs.EC2_2_2005_AC
        and concrete_miner_basis
        == fatigue_inputs.MINER_BASIS_BRIDGE_STANDARD
    )
    return {
        "reinforcement": (
            "DS/EN 1992-1-1:2005+A1:2014, clause 6.8.4 and "
            f"Tables 6.3N/6.4N{national}"
        ),
        "concrete": (
            (
                "DS/EN 1992-1-1:2005+A1:2014, clause 6.8.7, "
                "Formula (6.72)"
            )
            if equivalent
            else (
                "DS/EN 1992-2:2005/AC:2008, corrected Expression (6.106)"
                if bridge_standard
                else (
                    "Approved project-basis adoption of DS/EN 1992-2:2005/"
                    "AC:2008 corrected Expression (6.106); source: "
                    + str(concrete_miner_source or "").strip()
                )
            )
        ) + national,
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
    factor_keys = {
        "fatigue_gamma0",
        "fatigue_gamma3",
        "fatigue_gamma_s",
        "fatigue_gamma_c",
    }
    rejected_factor_keys = sorted(
        {
            key
            for key in (inp.get("invalid_factor_input_keys") or ())
            if key in factor_keys
        }
    )
    if rejected_factor_keys:
        errors.append(
            "Boolean/non-numeric values are not accepted for fatigue material "
            f"factors ({', '.join(rejected_factor_keys)}); enter explicit "
            "positive numeric values"
        )
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

    try:
        design_methodology = _design_methodology(
            inp.get("design_methodology")
        )
    except ValueError as exc:
        errors.append(str(exc))
        design_methodology = ""
    try:
        edition = _edition(inp.get("fatigue_edition"))
    except ValueError as exc:
        errors.append(str(exc))
        edition = ""
    resolved_gamma_s = resolved_gamma_c = None
    factor_basis = None
    if edition:
        try:
            resolved_gamma_s, resolved_gamma_c, factor_basis = (
                _resolved_factor_basis(inp, edition)
            )
        except (TypeError, ValueError) as exc:
            errors.append(str(exc))
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
    if check_reinforcement and resolved_gamma_s is not None:
        _positive(resolved_gamma_s, "gamma_s", errors)
    if check_concrete:
        concrete_method = str(
            inp.get("fatigue_concrete_method") or CONCRETE_MINER
        )
        if concrete_method not in CONCRETE_METHODS:
            errors.append("Select a valid concrete fatigue method")
        if resolved_gamma_c is not None:
            _positive(resolved_gamma_c, "gamma_c,fat", errors)
        _positive(inp.get("fatigue_beta_cc_t0"), "beta_cc(t0)", errors)
        _positive(inp.get("fatigue_t0_days"), "Concrete age t0", errors)
        if concrete_method in CONCRETE_MINER_METHODS:
            miner_basis = _resolved_concrete_miner_basis(
                inp,
                edition=edition,
                design_methodology=design_methodology,
                concrete_method=concrete_method,
            )
            miner_source = inp.get("fatigue_concrete_miner_source")
            errors.extend(concrete_miner_parameter_errors(
                edition=edition,
                concrete_method=concrete_method,
                miner_basis=miner_basis,
                miner_source=miner_source,
                coefficient_c=inp.get("fatigue_concrete_c"),
                design_methodology=design_methodology,
            ))
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
        basis = fatigue_inputs.canonical_basis(
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
            if "2023" in edition
            else fatigue_inputs.EC2_2005 if edition else None
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
                            f"{detail_edition} resistance with {edition}; select "
                            "an edition-aligned preset or identify the detail as "
                            "Custom / imported"
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
        edition = _edition(inp.get("fatigue_edition"))
    except ValueError:
        edition = ""
    try:
        design_methodology = _design_methodology(
            inp.get("design_methodology")
        )
    except ValueError:
        design_methodology = ""
    concrete_method = str(
        inp.get("fatigue_concrete_method") or CONCRETE_MINER
    )
    try:
        _gamma_s, _gamma_c, factor_basis = _resolved_factor_basis(
            inp,
            edition,
        )
        factor_records = factor_basis.get("parameter_conformance")
        if isinstance(factor_records, Mapping):
            active_factor_keys = []
            if bool(inp.get("fatigue_check_steel")):
                active_factor_keys.append("gamma_s")
            if bool(inp.get("fatigue_check_concrete")):
                active_factor_keys.append("gamma_c")
            for key in active_factor_keys:
                record = factor_records.get(key)
                if (
                    isinstance(record, Mapping)
                    and record.get("state") != conformance.STATE_CONFORMS
                ):
                    warnings.append(str(record.get("message") or ""))
    except (TypeError, ValueError):
        # Numerical factor failures are blocking validation errors.
        pass
    if bool(inp.get("fatigue_check_concrete")):
        if concrete_method in CONCRETE_MINER_METHODS and edition:
            miner_basis = _resolved_concrete_miner_basis(
                inp,
                edition=edition,
                design_methodology=design_methodology,
                concrete_method=concrete_method,
            )
            try:
                miner_record = concrete_miner_conformance(
                    edition=edition,
                    concrete_method=concrete_method,
                    miner_basis=miner_basis,
                    miner_source=inp.get(
                        "fatigue_concrete_miner_source"
                    ),
                    coefficient_c=inp.get("fatigue_concrete_c"),
                    design_methodology=design_methodology,
                )
                if (
                    miner_record["state"]
                    != conformance.STATE_CONFORMS
                ):
                    warnings.append(miner_record["message"])
            except ValueError:
                # Numerical/malformed Miner failures are validation errors.
                pass
        if concrete_method == CONCRETE_PROJECT_MINER:
            warnings.append(
                "A separately approved project concrete fatigue S-N relation "
                "is used instead of a standard-derived Miner life relation"
            )
        elif (
            concrete_method == CONCRETE_MINER
            and edition
            and edition != fatigue_inputs.EC2_2023
            and not (
                edition == fatigue_inputs.EC2_2_2005_AC
                and bridge.is_bridge_methodology(design_methodology)
            )
            and inp.get("fatigue_concrete_miner_basis")
            == fatigue_inputs.MINER_BASIS_PROJECT_ADOPTION
        ):
            warnings.append(
                "EN 1992-2 corrected Expression (6.106) is used by explicit "
                "project-basis adoption outside the bridge methodology"
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
    return list(dict.fromkeys(
        warning for warning in warnings if str(warning).strip()
    ))


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
        basis = fatigue_inputs.canonical_basis(
            inp.get(fatigue_inputs.BASIS_KEY)
        )
    except (TypeError, ValueError):
        basis = fatigue_inputs.default_basis()
    raw_edition = str(inp.get("fatigue_edition") or "").strip()
    try:
        edition = _edition(raw_edition)
    except ValueError:
        edition = raw_edition or "-"
    try:
        design_methodology = _design_methodology(
            inp.get("design_methodology")
        )
    except ValueError:
        design_methodology = None
    method = str(basis.get("method") or "")
    try:
        resolved_gamma_s, resolved_gamma_c, factor_basis = (
            _resolved_factor_basis(inp, edition)
        )
    except (TypeError, ValueError):
        resolved_gamma_s = inp.get("fatigue_gamma_s")
        resolved_gamma_c = inp.get("fatigue_gamma_c")
        factor_mode, explicit = _factor_mode(inp)
        factor_basis = {
            "edition": edition,
            "mode": factor_mode,
            "mode_explicit": explicit,
            "gamma0": inp.get("fatigue_gamma0", 1.0),
            "gamma3": inp.get("fatigue_gamma3", 1.0),
            "gamma_s": resolved_gamma_s,
            "gamma_c": resolved_gamma_c,
            "reference": "-",
            "approval_reference": (
                str(inp.get("fatigue_factor_approval") or "").strip()
                if factor_mode == fatigue_inputs.FACTOR_MODE_OVERRIDE
                else ""
            ),
        }
    return {
        "valid": False,
        "converged": False,
        "passed": False,
        "errors": unique_errors,
        "warnings": tuple(validation_warnings(inp)),
        "edition": edition,
        "design_methodology": design_methodology,
        "checks": {
            "reinforcement": bool(inp.get("fatigue_check_steel")),
            "concrete": bool(inp.get("fatigue_check_concrete")),
        },
        "concrete_method": (
            str(inp.get("fatigue_concrete_method") or CONCRETE_MINER)
            if bool(inp.get("fatigue_check_concrete"))
            else None
        ),
        "concrete_miner_basis": inp.get("fatigue_concrete_miner_basis"),
        "concrete_miner_source": str(
            inp.get("fatigue_concrete_miner_source") or ""
        ).strip(),
        "basis": dict(basis),
        "authority_reference": fatigue_inputs.METHOD_REFERENCES.get(
            method, "-"
        ),
        "calculation_references": {},
        "partial_factors": {
            "gamma_c": resolved_gamma_c,
            "gamma_s": resolved_gamma_s,
            "gamma_ff": inp.get("fatigue_gamma_ff"),
        },
        "factor_basis": factor_basis,
        "concrete_parameters": None,
        "fatigue_detail_basis": (),
        "t0_days": inp.get("fatigue_t0_days"),
        "elements": tuple(dict(record) for records in _records(inp)
                          for record in records if isinstance(record, Mapping)),
        "spectra": (),
        "governing_spectrum": None,
        "utilisation": None,
    }


def publication_safe_result(
    payload: Mapping | None,
    *,
    design_methodology: str | None,
    current_basis: Mapping | None,
) -> dict | None:
    """Return fatigue evidence correlated with the current input snapshot."""

    if not isinstance(payload, Mapping):
        return None
    result = dict(payload)
    raw_errors = payload.get("errors")
    errors: list[str] = []
    malformed_errors = False
    if raw_errors is not None:
        if not isinstance(raw_errors, (list, tuple)):
            malformed_errors = True
        else:
            for error in raw_errors:
                if not isinstance(error, str) or not error.strip():
                    malformed_errors = True
                else:
                    errors.append(error.strip())
    if malformed_errors:
        errors.append(
            "Published fatigue errors are not a structured list of typed messages"
        )
    raw_valid = payload.get("valid")
    if not isinstance(raw_valid, bool):
        errors.append("Published fatigue validity is not typed Boolean")
    raw_converged = payload.get("converged")
    if not isinstance(raw_converged, bool):
        errors.append("Published fatigue convergence is not typed Boolean")
    try:
        stored_methodology = _design_methodology(
            payload.get("design_methodology"),
            allow_default=False,
        )
    except ValueError:
        stored_methodology = ""
        errors.append(
            "Published fatigue evidence is missing its typed design-methodology "
            "binding"
        )
    try:
        current_methodology = _design_methodology(
            design_methodology,
            allow_default=False,
        )
    except ValueError:
        current_methodology = ""
        errors.append(
            "Current fatigue design methodology is unavailable for publication "
            "correlation"
        )
    if (
        stored_methodology
        and current_methodology
        and stored_methodology != current_methodology
    ):
        errors.append(
            "Published fatigue design methodology conflicts with the calculation "
            "input snapshot"
        )
    try:
        published_basis = fatigue_inputs.canonical_basis(
            payload.get("basis")
        )
    except (TypeError, ValueError) as exc:
        published_basis = None
        errors.append(f"Published fatigue basis is invalid: {exc}")
    else:
        result["basis"] = dict(published_basis)
    try:
        correlated_basis = fatigue_inputs.canonical_basis(current_basis)
    except (TypeError, ValueError) as exc:
        correlated_basis = None
        errors.append(
            f"Current fatigue basis is invalid for publication correlation: {exc}"
        )
    if (
        published_basis is not None
        and correlated_basis is not None
        and published_basis != correlated_basis
    ):
        errors.append(
            "Published fatigue basis conflicts with the calculation input snapshot"
        )
    checks = payload.get("checks")
    if not isinstance(checks, Mapping):
        errors.append("Published fatigue check selection is not structured")
        reinforcement_checked = False
        concrete_checked = False
    else:
        raw_reinforcement_checked = checks.get("reinforcement")
        if not isinstance(raw_reinforcement_checked, bool):
            errors.append(
                "Published reinforcement fatigue enablement is not typed Boolean"
            )
            reinforcement_checked = False
        else:
            reinforcement_checked = raw_reinforcement_checked
        raw_concrete_checked = checks.get("concrete")
        if not isinstance(raw_concrete_checked, bool):
            errors.append(
                "Published concrete fatigue enablement is not typed Boolean"
            )
            concrete_checked = False
        else:
            concrete_checked = raw_concrete_checked
    method = payload.get("concrete_method")
    parameters = payload.get("concrete_parameters")
    has_concrete_result = parameters is not None
    if concrete_checked and method not in CONCRETE_METHODS:
        errors.append("Published concrete fatigue method is unknown")
    if not concrete_checked and has_concrete_result:
        errors.append(
            "Published concrete fatigue parameters conflict with a disabled check"
        )
    if (
        method in CONCRETE_METHODS
        and (concrete_checked or has_concrete_result)
    ):
        if not isinstance(parameters, Mapping):
            errors.append(
                "Published concrete fatigue result is missing its typed parameters"
            )
        elif parameters.get("method") != method:
            errors.append(
                "Published concrete fatigue method conflicts with its "
                "calculation parameters"
            )
    if (
        method in CONCRETE_MINER_METHODS
        and (concrete_checked or has_concrete_result)
        and isinstance(parameters, Mapping)
    ):
        basis = payload.get("concrete_miner_basis")
        source = payload.get("concrete_miner_source")
        edition = str(payload.get("edition") or "").strip()
        errors.extend(concrete_miner_parameter_errors(
            edition=edition,
            concrete_method=str(method),
            miner_basis=str(basis or ""),
            miner_source=source,
            coefficient_c=parameters.get("c"),
            design_methodology=stored_methodology,
        ))
    expected_parameter_records: list[dict] = []
    factor_basis = payload.get("factor_basis")
    partial_factors = payload.get("partial_factors")
    if not isinstance(factor_basis, Mapping):
        errors.append("Published fatigue factor basis is not structured")
    elif not isinstance(partial_factors, Mapping):
        errors.append("Published fatigue partial factors are not structured")
    else:
        try:
            factor_mode = factor_basis.get("mode")
            expected_s, expected_c, expected_factor_basis = (
                fatigue_inputs.resolve_fatigue_factors(
                    str(payload.get("edition") or ""),
                    mode=factor_mode,
                    gamma_s=factor_basis.get("gamma_s"),
                    gamma_c=factor_basis.get("gamma_c"),
                    gamma0=factor_basis.get("gamma0", 1.0),
                    gamma3=factor_basis.get("gamma3", 1.0),
                    approval_reference=factor_basis.get(
                        "approval_reference"
                    ),
                )
            )
            for key, expected_value in (
                ("gamma_s", expected_s),
                ("gamma_c", expected_c),
            ):
                stored_value = factor_basis.get(key)
                if (
                    conformance.is_boolean(stored_value)
                    or not math.isclose(
                        float(stored_value),
                        expected_value,
                        rel_tol=0.0,
                        abs_tol=1.0e-12,
                    )
                ):
                    errors.append(
                        f"Published fatigue {key} conflicts with its factor basis"
                    )
            stored_factor_records = factor_basis.get(
                "parameter_conformance"
            )
            if not isinstance(stored_factor_records, Mapping):
                errors.append(
                    "Published fatigue factor conformance is missing or malformed"
                )
            else:
                for key in ("gamma_s", "gamma_c"):
                    expected_record = expected_factor_basis[
                        "parameter_conformance"
                    ][key]
                    if stored_factor_records.get(key) != expected_record:
                        errors.append(
                            f"Published fatigue {key} conformance is stale, "
                            "incomplete, or contradictory"
                        )
                if reinforcement_checked:
                    expected_parameter_records.append(
                        expected_factor_basis["parameter_conformance"]["gamma_s"]
                    )
                if concrete_checked:
                    expected_parameter_records.append(
                        expected_factor_basis["parameter_conformance"]["gamma_c"]
                    )
            for key, enabled, expected_value in (
                ("gamma_s", reinforcement_checked, expected_s),
                ("gamma_c", concrete_checked, expected_c),
            ):
                if enabled:
                    actual = partial_factors.get(key)
                    if (
                        conformance.is_boolean(actual)
                        or not math.isclose(
                            float(actual),
                            expected_value,
                            rel_tol=0.0,
                            abs_tol=1.0e-12,
                        )
                    ):
                        errors.append(
                            f"Published fatigue {key} conflicts with the "
                            "calculated input"
                        )
        except (TypeError, ValueError, KeyError) as exc:
            errors.append(f"Published fatigue factor evidence is invalid: {exc}")
    if (
        concrete_checked
        and method in CONCRETE_MINER_METHODS
        and isinstance(parameters, Mapping)
    ):
        try:
            expected_miner_record = concrete_miner_conformance(
                edition=str(payload.get("edition") or "").strip(),
                concrete_method=str(method),
                miner_basis=str(
                    payload.get("concrete_miner_basis") or ""
                ).strip(),
                miner_source=payload.get("concrete_miner_source"),
                coefficient_c=parameters.get("c"),
                design_methodology=stored_methodology,
            )
            if (
                parameters.get("parameter_conformance")
                != expected_miner_record
            ):
                errors.append(
                    "Published concrete Miner conformance is stale, "
                    "incomplete, or contradictory"
                )
            expected_parameter_records.append(expected_miner_record)
        except (TypeError, ValueError) as exc:
            errors.append(f"Published concrete Miner evidence is invalid: {exc}")
    stored_parameter_records = payload.get("parameter_conformance")
    if not isinstance(stored_parameter_records, (list, tuple)):
        errors.append(
            "Published fatigue parameter conformance is not a structured list"
        )
    elif [dict(record) for record in stored_parameter_records
          if isinstance(record, Mapping)] != expected_parameter_records or not all(
              isinstance(record, Mapping)
              for record in stored_parameter_records
          ):
        errors.append(
            "Published fatigue parameter conformance is stale, incomplete, "
            "or reordered"
        )
    raw_passed = payload.get("passed")
    if not isinstance(raw_passed, bool):
        errors.append("Published analytical fatigue verdict is not typed Boolean")
        raw_passed = False
    if raw_passed and raw_converged is not True:
        errors.append(
            "Published analytical fatigue PASS conflicts with convergence evidence"
        )
    if raw_valid is False and not errors:
        errors.append(
            "Published fatigue result is marked invalid without typed errors"
        )
    expected_conformance = None
    if expected_parameter_records:
        try:
            expected_conformance = conformance.aggregate(
                expected_parameter_records,
                analytical_status=(
                    conformance.STATUS_PASS
                    if raw_passed
                    else conformance.STATUS_FAIL
                ),
                selected_standard=str(payload.get("edition") or "").strip(),
            )
        except ValueError as exc:
            errors.append(str(exc))
    if (
        expected_conformance is not None
        and not _json_equivalent(
            payload.get("conformance"),
            expected_conformance,
        )
    ):
        errors.append(
            "Published fatigue aggregate conformance is stale or contradictory"
        )
    if expected_conformance is not None:
        expected_assessment = expected_conformance["assessment_status"]
        expected_qualified = expected_conformance["qualified_verdict"]
        expected_standard_passed = bool(
            raw_passed
            and expected_conformance["state"]
            == conformance.STATE_CONFORMS
        )
        if payload.get("assessment_status") != expected_assessment:
            errors.append(
                "Published fatigue assessment status is stale or contradictory"
            )
        if payload.get("qualified_verdict") != expected_qualified:
            errors.append(
                "Published fatigue qualified verdict is stale or contradictory"
            )
        if payload.get("standard_passed") is not expected_standard_passed:
            errors.append(
                "Published fatigue selected-standard verdict is stale or "
                "contradictory"
            )
    unique_errors = tuple(dict.fromkeys(errors))
    result["errors"] = unique_errors
    if unique_errors:
        result["valid"] = False
        result["converged"] = False
        result["passed"] = False
        result["standard_passed"] = False
        result["assessment_status"] = "INVALID"
        result["qualified_verdict"] = "INVALID - fatigue not assessed"
    elif expected_conformance is not None:
        result["conformance"] = expected_conformance
        result["assessment_status"] = expected_conformance[
            "assessment_status"
        ]
        result["qualified_verdict"] = expected_conformance[
            "qualified_verdict"
        ]
        result["standard_passed"] = bool(
            raw_passed
            and expected_conformance["state"]
            == conformance.STATE_CONFORMS
        )
    return result


def _canonical_fatigue_conformance_body(payload: Mapping) -> dict:
    """Return the JSON-canonical compact fatigue evidence body."""

    body = {
        key: payload.get(key)
        for key in _FATIGUE_CONFORMANCE_FIELDS
    }
    return json.loads(json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ))


def _fatigue_conformance_digest(body: Mapping) -> str:
    canonical = json.dumps(
        {
            "schema": FATIGUE_CONFORMANCE_SCHEMA,
            **dict(body),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def calculation_conformance_record(
    payload: Mapping | None,
    *,
    design_methodology: str | None,
    current_basis: Mapping | None,
) -> dict | None:
    """Build immutable, compact fatigue conformance evidence for a project."""

    safe = publication_safe_result(
        payload,
        design_methodology=design_methodology,
        current_basis=current_basis,
    )
    if (
        not isinstance(safe, Mapping)
        or safe.get("valid") is not True
        or safe.get("errors")
    ):
        return None
    try:
        body = _canonical_fatigue_conformance_body(safe)
        digest = _fatigue_conformance_digest(body)
    except (TypeError, ValueError):
        return None
    return {
        "schema": FATIGUE_CONFORMANCE_SCHEMA,
        **body,
        "evidence_sha256": digest,
    }


def publication_safe_conformance_record(
    record: Mapping | None,
    *,
    design_methodology: str | None,
    current_basis: Mapping | None,
) -> dict | None:
    """Revalidate saved fatigue evidence and reject mutation or relabelling."""

    if not isinstance(record, Mapping):
        return None
    expected_keys = {
        "schema",
        "evidence_sha256",
        *_FATIGUE_CONFORMANCE_FIELDS,
    }
    if set(record) != expected_keys:
        return None
    if record.get("schema") != FATIGUE_CONFORMANCE_SCHEMA:
        return None
    try:
        body = _canonical_fatigue_conformance_body(record)
        if record.get("evidence_sha256") != _fatigue_conformance_digest(body):
            return None
        rebuilt = calculation_conformance_record(
            body,
            design_methodology=design_methodology,
            current_basis=current_basis,
        )
    except (TypeError, ValueError):
        return None
    if rebuilt is None:
        return None
    canonical_record = json.loads(json.dumps(
        dict(record),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ))
    return rebuilt if rebuilt == canonical_record else None


def _reinforcement_properties(
    records: Sequence[Mapping],
    materials: Sequence,
    proof_stresses: Sequence[float],
    details: Mapping[str, Mapping],
    kind: str,
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
    design_methodology = _design_methodology(
        inp.get("design_methodology")
    )
    bars, tendons = _records(inp)
    bar_materials = list(inp.get("bar_materials") or [])
    tendon_materials = list(inp.get("tendon_materials") or [])
    catalog = fatigue_inputs.normalise_catalog(
        inp.get(fatigue_inputs.DETAIL_CATALOG_KEY)
    )
    details = fatigue_inputs.entry_map(catalog)
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
    edition = _edition(inp.get("fatigue_edition"))
    concrete_miner_basis = None
    concrete_miner_source = ""
    concrete_miner_record = None
    if check_concrete and concrete_method in CONCRETE_MINER_METHODS:
        concrete_miner_basis = _resolved_concrete_miner_basis(
            inp,
            edition=edition,
            design_methodology=design_methodology,
            concrete_method=concrete_method,
        )
        concrete_miner_source = conformance.typed_text(
            inp.get("fatigue_concrete_miner_source"),
            "Concrete Miner approval/source",
        )
    resolved_gamma_s, resolved_gamma_c, factor_basis = (
        _resolved_factor_basis(inp, edition)
    )
    gamma_c = (
        resolved_gamma_c if check_concrete else None
    )
    gamma_s = (
        resolved_gamma_s if check_reinforcement else None
    )
    reinforcement = (
        _reinforcement_properties(
            bars,
            bar_materials,
            bar_proof_stresses,
            details,
            fatigue_inputs.MILD,
        )
        + _reinforcement_properties(
            tendons,
            tendon_materials,
            tendon_proof_stresses,
            details,
            fatigue_inputs.PRESTRESS,
        )
        if check_reinforcement
        else []
    )

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
            method=concrete_method,
        )
        if check_concrete
        else None
    )
    if (
        concrete is not None
        and concrete_method in CONCRETE_MINER_METHODS
        and concrete_miner_basis is not None
    ):
        concrete_miner_record = concrete_miner_conformance(
            edition=edition,
            concrete_method=concrete_method,
            miner_basis=concrete_miner_basis,
            miner_source=concrete_miner_source,
            coefficient_c=concrete.c,
            design_methodology=design_methodology,
        )
    factor_records = factor_basis.get("parameter_conformance")
    parameter_records = []
    if isinstance(factor_records, Mapping):
        if check_reinforcement and isinstance(
            factor_records.get("gamma_s"),
            Mapping,
        ):
            parameter_records.append(factor_records["gamma_s"])
        if check_concrete and isinstance(
            factor_records.get("gamma_c"),
            Mapping,
        ):
            parameter_records.append(factor_records["gamma_c"])
    if concrete_miner_record is not None:
        parameter_records.append(concrete_miner_record)

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
    basis = fatigue_inputs.canonical_basis(
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
        factor_basis=factor_basis,
        warnings=tuple(validation_warnings(inp)),
        design_methodology=design_methodology,
        concrete_method=concrete_method,
        concrete_miner_basis=concrete_miner_basis,
        concrete_miner_source=concrete_miner_source,
        parameter_conformance=tuple(parameter_records),
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
        tuple(
            (key, prepared.factor_basis.get(key))
            for key in (
                "edition",
                "mode",
                "mode_explicit",
                "gamma0",
                "gamma3",
                "gamma_s_base",
                "gamma_c_base",
                "fatigue_multiplier",
                "gamma_s",
                "gamma_c",
                "reference",
                "approval_reference",
            )
        ),
        prepared.warnings,
        prepared.design_methodology,
        prepared.concrete_method,
        prepared.concrete_miner_basis,
        prepared.concrete_miner_source,
        json.dumps(
            prepared.parameter_conformance,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ),
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
    references = calculation_references(
        prepared.edition,
        prepared.concrete_method or CONCRETE_MINER,
        prepared.concrete_miner_basis,
        prepared.concrete_miner_source,
    )
    if (
        prepared.check_reinforcement
        and any(record["custom"] for record in prepared.detail_records)
    ):
        references["reinforcement"] += (
            "; assigned custom/imported S-N resistance sources are listed "
            "separately"
        )
    analytical_passed = all(result.passed for result in results)
    conformance_assessment = conformance.aggregate(
        list(prepared.parameter_conformance),
        analytical_status=(
            conformance.STATUS_PASS
            if analytical_passed
            else conformance.STATUS_FAIL
        ),
        selected_standard=prepared.edition,
    )
    miner_record = next(
        (
            record
            for record in prepared.parameter_conformance
            if record.get("parameter_id") == "concrete_fatigue.miner_c"
        ),
        None,
    )
    if (
        prepared.check_concrete
        and isinstance(miner_record, Mapping)
        and miner_record.get("state") != conformance.STATE_CONFORMS
    ):
        if (
            miner_record.get("state")
            == conformance.STATE_APPROVED_CUSTOM
        ):
            references["concrete"] = (
                "Approved custom concrete Miner/S-N methodology; "
                f"C = {miner_record['actual_value']:g}; "
                "approval/source: "
                f"{miner_record.get('approval_reference') or '-'}"
            )
        else:
            references["concrete"] = (
                "Custom/deviating concrete Miner analysis; this is not an "
                "unqualified selected-standard Miner check; "
                f"C = {miner_record['actual_value']:g}; "
                f"{miner_record.get('message') or ''}"
            )
    return {
        "valid": True,
        "edition": prepared.edition,
        "design_methodology": prepared.design_methodology,
        "checks": {
            "reinforcement": prepared.check_reinforcement,
            "concrete": prepared.check_concrete,
        },
        "concrete_method": prepared.concrete_method,
        "concrete_miner_basis": prepared.concrete_miner_basis,
        "concrete_miner_source": prepared.concrete_miner_source,
        "basis": dict(prepared.basis),
        "authority_reference": fatigue_inputs.METHOD_REFERENCES[
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
        "warnings": prepared.warnings,
        "partial_factors": {
            "gamma_c": prepared.gamma_c,
            "gamma_s": prepared.gamma_s,
            "gamma_ff": prepared.gamma_ff,
        },
        "factor_basis": dict(prepared.factor_basis),
        "parameter_conformance": tuple(
            dict(record) for record in prepared.parameter_conformance
        ),
        "conformance": conformance_assessment,
        "assessment_status": conformance_assessment["assessment_status"],
        "qualified_verdict": conformance_assessment["qualified_verdict"],
        "standard_passed": bool(
            analytical_passed
            and conformance_assessment["state"]
            == conformance.STATE_CONFORMS
        ),
        "concrete_parameters": (
            {
                "fck_mpa": prepared.concrete.fck_mpa,
                "beta_cc_t0": prepared.concrete.beta_cc_t0,
                "alpha_cc": prepared.concrete.alpha_cc,
                "k1": prepared.concrete.k1,
                "c": prepared.concrete.c,
                "method": prepared.concrete.method,
                "parameter_conformance": (
                    dict(miner_record)
                    if isinstance(miner_record, Mapping)
                    else None
                ),
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
        "utilisation": governing.utilisation,
        "converged": all(result.converged for result in results),
        "passed": analytical_passed,
    }
