"""Failure-first boundary replay and independent CT-010a mechanics."""

from __future__ import annotations

import dataclasses
import math
import pathlib
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

from .calculation_trace import TraceValidationError
from .fatigue_trace_contract import INVALID_KEYS, SUCCESS_KEYS


_STATE_CONCRETE = frozenset({
    "concrete_compression_long_mpa", "concrete_compression_total_mpa",
    "concrete_compression_design_total_mpa", "elastic_result",
    "design_elastic_result",
})
_SPECTRUM_CONCRETE = frozenset({
    "concrete", "concrete_search", "fcd_fat_mpa",
    "governing_concrete_fibre", "concrete_method",
})
_SPECTRUM_MIXED = frozenset({"utilisation", "converged", "passed"})
_TOP_CONCRETE = frozenset({
    "concrete_method", "concrete_parameters", "t0_days",
})
_TOP_MIXED = frozenset({
    "governing_spectrum", "utilisation", "converged", "passed",
})


def application_boundary():
    try:
        import fatigue_analysis
    except ImportError:  # pragma: no cover - direct package use
        sys.path.insert(0, str(
            pathlib.Path(__file__).resolve().parent.parent / "app"))
        import fatigue_analysis
    return fatigue_analysis


def fail(message: str) -> None:
    raise TraceValidationError(message)


def scalar_same(actual: Any, expected: Any) -> bool:
    if type(actual) is not type(expected):
        return False
    if type(expected) is float:
        return (
            math.isnan(actual) and math.isnan(expected)
        ) or actual.hex() == expected.hex()
    if isinstance(expected, np.generic):
        return actual.dtype == expected.dtype and scalar_same(
            actual.item(), expected.item())
    return actual == expected


def exact(actual: Any, expected: Any, label: str) -> None:
    if type(actual) is not type(expected):
        fail(f"{label} retained type differs")
    if dataclasses.is_dataclass(expected) and not isinstance(expected, type):
        fields = tuple(field.name for field in dataclasses.fields(expected))
        if tuple(field.name for field in dataclasses.fields(actual)) != fields:
            fail(f"{label} dataclass inventory differs")
        for field in fields:
            exact(
                getattr(actual, field), getattr(expected, field),
                f"{label}.{field}")
        return
    if isinstance(expected, np.ndarray):
        if actual.dtype != expected.dtype or actual.shape != expected.shape:
            fail(f"{label} array identity differs")
        if not np.array_equal(actual, expected, equal_nan=True):
            fail(f"{label} array value differs")
        return
    if type(expected) is dict:
        if tuple(actual) != tuple(expected):
            fail(f"{label} object inventory/order differs")
        for key in expected:
            exact(actual[key], expected[key], f"{label}.{key}")
        return
    if type(expected) in {list, tuple}:
        if len(actual) != len(expected):
            fail(f"{label} cardinality differs")
        for position, (left, right) in enumerate(zip(actual, expected)):
            exact(left, right, f"{label}[{position}]")
        return
    if not scalar_same(actual, expected):
        fail(f"{label} value differs")


def same_structure(actual: Any, expected: Any, label: str) -> None:
    if type(actual) is not type(expected):
        fail(f"{label} excluded type differs")
    if dataclasses.is_dataclass(expected) and not isinstance(expected, type):
        fields = tuple(field.name for field in dataclasses.fields(expected))
        if tuple(field.name for field in dataclasses.fields(actual)) != fields:
            fail(f"{label} excluded inventory differs")
        for field in fields:
            same_structure(
                getattr(actual, field), getattr(expected, field),
                f"{label}.{field}")
        return
    if isinstance(expected, np.ndarray):
        if actual.dtype != expected.dtype or actual.shape != expected.shape:
            fail(f"{label} excluded array shape/type differs")
        return
    if type(expected) is dict:
        if tuple(actual) != tuple(expected):
            fail(f"{label} excluded object inventory/order differs")
        for key in expected:
            same_structure(actual[key], expected[key], f"{label}.{key}")
        return
    if type(expected) in {list, tuple}:
        if len(actual) != len(expected):
            fail(f"{label} excluded cardinality differs")
        for position, (left, right) in enumerate(zip(actual, expected)):
            same_structure(left, right, f"{label}[{position}]")


def _candidate_state(actual: Any, expected: Any, label: str) -> None:
    if type(actual) is not type(expected) or not dataclasses.is_dataclass(expected):
        fail(f"{label} fatigue state type differs")
    fields = tuple(field.name for field in dataclasses.fields(expected))
    if tuple(field.name for field in dataclasses.fields(actual)) != fields:
        fail(f"{label} fatigue state inventory differs")
    for field in fields:
        comparator = same_structure if field in _STATE_CONCRETE else exact
        comparator(
            getattr(actual, field), getattr(expected, field),
            f"{label}.{field}")


def _candidate_spectrum(
    actual: Any, expected: Any, label: str, concrete_enabled: bool,
) -> None:
    if type(actual) is not type(expected) or not dataclasses.is_dataclass(expected):
        fail(f"{label} spectrum type differs")
    fields = tuple(field.name for field in dataclasses.fields(expected))
    if tuple(field.name for field in dataclasses.fields(actual)) != fields:
        fail(f"{label} spectrum inventory differs")
    for field in fields:
        left, right = getattr(actual, field), getattr(expected, field)
        if field == "bins":
            if type(left) is not tuple or len(left) != len(right):
                fail(f"{label}.bins position/type differs")
            for position, (state, retained) in enumerate(zip(left, right)):
                _candidate_state(
                    state, retained, f"{label}.bins[{position}]")
        elif field in _SPECTRUM_CONCRETE:
            same_structure(left, right, f"{label}.{field}")
        elif concrete_enabled and field in _SPECTRUM_MIXED:
            same_structure(left, right, f"{label}.{field}")
        else:
            exact(left, right, f"{label}.{field}")


def compare_candidate(candidate: Any, replay: Any) -> None:
    if type(candidate) is not dict or type(replay) is not dict:
        fail("successful fatigue output must be an exact built-in dict")
    if tuple(candidate) != SUCCESS_KEYS or tuple(replay) != SUCCESS_KEYS:
        fail("successful fatigue output inventory/order differs")
    concrete_enabled = replay["checks"]["concrete"]
    for key in SUCCESS_KEYS:
        actual, expected = candidate[key], replay[key]
        if key == "spectra":
            if type(actual) is not tuple or len(actual) != len(expected):
                fail("fatigue spectra position/type differs")
            for position, (left, right) in enumerate(zip(actual, expected)):
                _candidate_spectrum(
                    left, right, f"fatigue.spectra[{position}]",
                    concrete_enabled)
        elif key == "partial_factors":
            if type(actual) is not dict or tuple(actual) != tuple(expected):
                fail("fatigue partial-factor inventory differs")
            same_structure(actual["gamma_c"], expected["gamma_c"],
                           "fatigue.partial_factors.gamma_c")
            exact(actual["gamma_s"], expected["gamma_s"],
                  "fatigue.partial_factors.gamma_s")
            exact(actual["gamma_ff"], expected["gamma_ff"],
                  "fatigue.partial_factors.gamma_ff")
        elif key == "calculation_references":
            if type(actual) is not dict or tuple(actual) != tuple(expected):
                fail("fatigue calculation-reference inventory differs")
            for family in expected:
                comparator = same_structure if family == "concrete" else exact
                comparator(actual[family], expected[family],
                           f"fatigue.calculation_references.{family}")
        elif key in _TOP_CONCRETE:
            same_structure(actual, expected, f"fatigue.{key}")
        elif concrete_enabled and key in _TOP_MIXED:
            same_structure(actual, expected, f"fatigue.{key}")
        else:
            exact(actual, expected, f"fatigue.{key}")


def _controls(inp: Mapping[str, Any]) -> tuple[bool, bool, bool]:
    if not isinstance(inp, Mapping):
        fail("fatigue input must be a mapping")
    values = []
    for key in ("fatigue_on", "fatigue_check_steel", "fatigue_check_concrete"):
        if key not in inp or type(inp[key]) is not bool:
            fail(f"{key} must be a required exact built-in Boolean")
        values.append(inp[key])
    return values[0], values[1], values[2]


def _deferred_invalid(inp: Mapping[str, Any], candidate: dict) -> None:
    if tuple(candidate) != INVALID_KEYS:
        fail("retained invalid fatigue output inventory/order differs")
    if candidate["valid"] is not False:
        fail("retained invalid fatigue discriminator must be exact False")
    boundary = application_boundary()
    errors = boundary.validation_errors(inp)
    if not errors:
        fail("valid fatigue input cannot carry a retained invalid payload")
    expected = boundary.invalid_result(inp, errors)
    if type(expected) is not dict or tuple(expected) != INVALID_KEYS:
        fail("authoritative invalid fatigue inventory drifted")
    exact(candidate, expected, "fatigue.invalid")


def classify(inp: Mapping[str, Any], out: Mapping[str, Any]) -> tuple[str, Any]:
    enabled, steel, _concrete = _controls(inp)
    if not isinstance(out, Mapping):
        fail("analysis output must be a mapping")
    candidate = out.get("fatigue")
    if not enabled:
        if candidate is not None:
            fail("disabled fatigue input cannot carry a fatigue payload")
        return "none", None
    if candidate is None:
        return "none", None
    if type(candidate) is not dict:
        fail("fatigue payload must be an exact built-in dict")
    if tuple(candidate) == INVALID_KEYS:
        _deferred_invalid(inp, candidate)
        return ("invalid" if steel else "none"), candidate
    if "valid" in candidate:
        fail("malformed fatigue valid discriminator/inventory")
    return "success", candidate


def close(actual: float, expected: float, label: str) -> None:
    if math.isinf(actual) or math.isinf(expected):
        if actual != expected:
            fail(f"{label} differs from independent reconstruction")
    elif not math.isclose(
        float(actual), float(expected), rel_tol=2.0e-12, abs_tol=2.0e-12,
    ):
        fail(f"{label} differs from independent reconstruction")


def _life(design_range: float, properties: Any, gamma_s: float):
    if design_range == 0.0:
        return math.inf, math.inf, 0.0
    knee = properties.delta_sigma_rsk_mpa / gamma_s
    slope = properties.k1 if design_range >= knee else properties.k2
    log_life = (
        math.log10(properties.n_star)
        + slope * math.log10(
            properties.delta_sigma_rsk_mpa / (gamma_s * design_range)))
    life = (
        math.inf if log_life > math.log10(np.finfo(float).max)
        else 10.0 ** log_life)
    return life, log_life, slope


def _damage(cycles: float, log_life: float) -> float:
    if math.isinf(log_life):
        return 0.0 if log_life > 0.0 else math.inf
    power = math.log10(cycles) - log_life
    if power > math.log10(np.finfo(float).max):
        return math.inf
    if power < math.log10(np.nextafter(0.0, 1.0)):
        return 0.0
    return 10.0 ** power


def _proof(stress: float, properties: Any, gamma_s: float):
    strength = properties.fytk_mpa
    if stress < 0.0 and properties.fyck_mpa is not None:
        strength = properties.fyck_mpa
    limit = strength / gamma_s
    return limit, abs(stress) / limit


@dataclass(frozen=True, slots=True)
class BinReplay:
    input_bin: Any
    state: Any
    reported: Any
    values: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class AssessmentReplay:
    spectrum_name: str
    spectrum_position: int
    element_position: int
    properties: Any
    detail: Mapping[str, Any]
    reported: Any
    bins: tuple[BinReplay, ...]
    damage: float
    governing_damage_bin: str
    proof_utilisation: float
    governing_proof_bin: str
    utilisation: float
    converged: bool
    passed: bool


@dataclass(frozen=True, slots=True)
class SpectrumReplay:
    name: str
    position: int
    reported: Any
    assessments: tuple[AssessmentReplay, ...]


@dataclass(frozen=True, slots=True)
class SuccessfulReplay:
    prepared: Any
    analysis_signature: Any
    output: Mapping[str, Any]
    spectra: tuple[SpectrumReplay, ...]


def _boundary_fields(boundary: Any, prepared: Any, replay: Mapping[str, Any]) -> None:
    exact(replay["edition"], prepared.edition, "fatigue.edition")
    exact(
        replay["checks"],
        {"reinforcement": prepared.check_reinforcement,
         "concrete": prepared.check_concrete},
        "fatigue.checks")
    exact(replay["basis"], dict(prepared.basis), "fatigue.basis")
    expected_method = boundary.fatigue_inputs.METHOD_REFERENCES[
        prepared.basis["method"]]
    exact(replay["method_reference"], expected_method,
          "fatigue.method_reference")
    references = boundary.calculation_references(
        prepared.edition, prepared.concrete_method or boundary.CONCRETE_MINER)
    if (
        prepared.check_reinforcement
        and any(record["custom"] for record in prepared.detail_records)
    ):
        references["reinforcement"] += (
            "; assigned custom/imported S-N resistance sources are listed "
            "separately")
    expected_references = {
        key: value for key, value in references.items()
        if ((key == "reinforcement" and prepared.check_reinforcement)
            or (key == "concrete" and prepared.check_concrete))
    }
    if type(replay["calculation_references"]) is not dict or (
        tuple(replay["calculation_references"]) != tuple(expected_references)
    ):
        fail("fatigue calculation-reference boundary inventory differs")
    if "reinforcement" in expected_references:
        exact(
            replay["calculation_references"]["reinforcement"],
            expected_references["reinforcement"],
            "fatigue.calculation_references.reinforcement")
    if "concrete" in expected_references:
        same_structure(
            replay["calculation_references"]["concrete"],
            expected_references["concrete"],
            "fatigue.calculation_references.concrete")
    exact(replay["warnings"], prepared.warnings, "fatigue.warnings")
    factors = replay["partial_factors"]
    if type(factors) is not dict or tuple(factors) != (
        "gamma_c", "gamma_s", "gamma_ff"):
        fail("fatigue partial-factor boundary inventory differs")
    same_structure(factors["gamma_c"], prepared.gamma_c,
                   "fatigue.partial_factors.gamma_c")
    exact(factors["gamma_s"], prepared.gamma_s,
          "fatigue.partial_factors.gamma_s")
    exact(factors["gamma_ff"], prepared.gamma_ff,
          "fatigue.partial_factors.gamma_ff")
    exact(replay["reinforcement_properties"], prepared.reinforcement,
          "fatigue.reinforcement_properties")
    exact(replay["fatigue_detail_basis"], prepared.detail_records,
          "fatigue.fatigue_detail_basis")
    exact(replay["elements"], prepared.element_records, "fatigue.elements")


def _bin_replay(
    input_bin: Any, state: Any, reported: Any, properties: Any,
    element_position: int, gamma_s: float,
) -> BinReplay:
    exact(state.name, input_bin.name, "fatigue state/input bin name")
    exact(state.description, input_bin.description,
          "fatigue state/input bin description")
    close(state.cycles, input_bin.cycles, "fatigue state/input cycles")
    exact(reported.bin_name, state.name, "reported/state bin name")
    if type(state.converged) is not bool or type(reported.converged) is not bool:
        fail("fatigue bin convergence must be exact Boolean")
    if reported.converged != state.converged:
        fail("reported bin convergence differs from matched solver state")
    long_stress = state.bar_stress_long_mpa[element_position]
    elastic_total = state.bar_stress_total_mpa[element_position]
    fatigue_vector = (
        state.bar_stress_fatigue_total_mpa or state.bar_stress_total_mpa)
    design_vector = (
        state.bar_stress_fatigue_design_total_mpa or fatigue_vector)
    fatigue_total = fatigue_vector[element_position]
    design_total = design_vector[element_position]
    range_value = abs(fatigue_total - long_stress)
    elastic_range = abs(elastic_total - long_stress)
    design_range = abs(design_total - long_stress)
    bond_factor = (
        range_value / elastic_range if elastic_range > 0.0
        else math.inf if range_value > 0.0 else 1.0)
    life, log_life, slope = _life(design_range, properties, gamma_s)
    damage = _damage(state.cycles, log_life)
    long_limit, long_util = _proof(long_stress, properties, gamma_s)
    total_limit, total_util = _proof(design_total, properties, gamma_s)
    if total_util >= long_util:
        governing_stress, proof_limit, proof_util = (
            design_total, total_limit, total_util)
    else:
        governing_stress, proof_limit, proof_util = (
            long_stress, long_limit, long_util)
    values = {
        "cycles": state.cycles,
        "converged": float(state.converged),
        "long_stress": long_stress,
        "elastic_total": elastic_total,
        "fatigue_total": fatigue_total,
        "design_total": design_total,
        "stress_range": range_value,
        "elastic_range": elastic_range,
        "bond_factor": bond_factor,
        "design_range": design_range,
        "sn_slope": slope,
        "log_life": log_life,
        "life": life,
        "damage": damage,
        "governing_stress": governing_stress,
        "proof_limit": proof_limit,
        "proof_utilisation": proof_util,
    }
    comparisons = (
        (reported.cycles, state.cycles, "reported cycles"),
        (reported.stress_long_mpa, long_stress, "long stress"),
        (reported.stress_total_mpa, fatigue_total, "fatigue total"),
        (reported.stress_total_design_mpa, design_total, "design total"),
        (reported.stress_total_elastic_mpa, elastic_total, "elastic total"),
        (reported.stress_range_mpa, range_value, "stress range"),
        (reported.stress_range_elastic_mpa, elastic_range, "elastic range"),
        (reported.bond_adjustment, bond_factor, "bond factor"),
        (reported.design_stress_range_mpa, design_range, "design range"),
        (reported.delta_sigma_rsk_mpa, properties.delta_sigma_rsk_mpa,
         "reference range"),
        (reported.delta_sigma_rd_mpa,
         properties.delta_sigma_rsk_mpa / gamma_s, "design resistance"),
        (reported.sn_exponent, slope, "S-N slope"),
        (reported.cycles_to_failure, life, "cycles to failure"),
        (reported.log10_cycles_to_failure, log_life, "log life"),
        (reported.damage, damage, "damage"),
        (reported.governing_stress_mpa, governing_stress, "governing stress"),
        (reported.yield_limit_mpa, proof_limit, "proof limit"),
        (reported.yield_utilisation, proof_util, "proof utilisation"),
    )
    for actual, expected, label in comparisons:
        close(actual, expected, label)
    exact(reported.bond_method, state.bond_method, "reported/state bond method")
    return BinReplay(input_bin, state, reported, values)


def _assessment_replay(
    input_bins: tuple[Any, ...], spectrum: Any, properties: Any,
    detail: Mapping[str, Any], assessment: Any, spectrum_position: int,
    element_position: int, gamma_s: float,
) -> AssessmentReplay:
    exact(assessment.element_id, properties.element_id, "assessment element ID")
    exact(assessment.kind, properties.kind, "assessment kind")
    exact(assessment.detail_id, properties.detail_id, "assessment detail ID")
    close(assessment.diameter_mm, properties.diameter_mm,
          "assessment diameter")
    if len(assessment.bins) != len(input_bins) or len(spectrum.bins) != len(input_bins):
        fail("assessment/state/input bin cardinality differs")
    bins = tuple(
        _bin_replay(
            input_bin, state, reported, properties, element_position, gamma_s)
        for input_bin, state, reported in zip(
            input_bins, spectrum.bins, assessment.bins)
    )
    damage = sum(item.values["damage"] for item in bins)
    governing_damage = max(bins, key=lambda item: item.values["damage"])
    governing_proof = max(
        bins, key=lambda item: item.values["proof_utilisation"])
    converged = all(item.state.converged for item in bins)
    proof_util = governing_proof.values["proof_utilisation"]
    utilisation = max(damage, proof_util)
    passed = bool(converged and damage <= 1.0 and proof_util <= 1.0)
    for actual, expected, label in (
        (assessment.damage, damage, "assessment damage"),
        (assessment.damage_utilisation, damage, "assessment damage utilisation"),
        (assessment.yield_utilisation, proof_util,
         "assessment proof utilisation"),
        (assessment.utilisation, utilisation, "assessment utilisation"),
    ):
        close(actual, expected, label)
    exact(assessment.governing_damage_bin, governing_damage.state.name,
          "governing damage-bin identity")
    exact(assessment.governing_yield_bin, governing_proof.state.name,
          "governing proof-bin identity")
    if type(assessment.converged) is not bool or assessment.converged != converged:
        fail("assessment convergence differs")
    if type(assessment.passed) is not bool or assessment.passed != passed:
        fail("assessment verdict differs")
    return AssessmentReplay(
        spectrum.spectrum_name, spectrum_position, element_position,
        properties, detail, assessment, bins, damage,
        governing_damage.state.name, proof_util, governing_proof.state.name,
        utilisation, converged, passed)


def successful_replay(
    inp: Mapping[str, Any], candidate: dict,
) -> SuccessfulReplay:
    boundary = application_boundary()
    authoritative = boundary.run_analysis(inp)
    compare_candidate(candidate, authoritative)
    prepared = boundary.prepare(inp)
    _boundary_fields(boundary, prepared, authoritative)
    prepared_spectra = tuple(prepared.spectra.items())
    if len(authoritative["spectra"]) != len(prepared_spectra):
        fail("prepared/output spectrum cardinality differs")
    details = {record["id"]: record for record in prepared.detail_records}
    spectra = []
    all_assessments = []
    for spectrum_position, (reported_spectrum, prepared_row) in enumerate(
            zip(authoritative["spectra"], prepared_spectra)):
        prepared_name, input_bins = prepared_row
        exact(reported_spectrum.spectrum_name, prepared_name,
              "output/prepared spectrum name")
        if len(reported_spectrum.bins) != len(input_bins):
            fail("output/prepared spectrum bin cardinality differs")
        for state, input_bin in zip(reported_spectrum.bins, input_bins):
            exact(state.name, input_bin.name, "state/prepared bin name")
            exact(state.description, input_bin.description,
                  "state/prepared bin description")
            close(state.cycles, input_bin.cycles, "state/prepared bin cycles")
            close(state.design_action_factor, prepared.gamma_ff,
                  "state/prepared design action factor")
        if len(reported_spectrum.reinforcement) != len(prepared.reinforcement):
            fail("output/prepared assessment cardinality differs")
        assessments = []
        for element_position, (properties, assessment) in enumerate(
                zip(prepared.reinforcement, reported_spectrum.reinforcement)):
            detail = details.get(properties.detail_id)
            if detail is None:
                fail("assigned fatigue-detail provenance is unavailable")
            replay = _assessment_replay(
                input_bins, reported_spectrum, properties, detail, assessment,
                spectrum_position, element_position, prepared.gamma_s)
            assessments.append(replay)
            all_assessments.append(replay)
        if not prepared.check_reinforcement:
            spectra.append(SpectrumReplay(
                prepared_name, spectrum_position, reported_spectrum, ()))
            continue
        governing = max(assessments, key=lambda item: item.utilisation)
        exact(reported_spectrum.governing_reinforcement_id,
              governing.properties.element_id,
              "spectrum governing reinforcement identity")
        if not prepared.check_concrete:
            close(reported_spectrum.utilisation, governing.utilisation,
                  "reinforcement-only spectrum utilisation")
            if (
                type(reported_spectrum.converged) is not bool
                or reported_spectrum.converged
                != all(item.converged for item in assessments)
                or type(reported_spectrum.passed) is not bool
                or reported_spectrum.passed != all(item.passed for item in assessments)
            ):
                fail("reinforcement-only spectrum aggregate state differs")
        spectra.append(SpectrumReplay(
            prepared_name, spectrum_position, reported_spectrum,
            tuple(assessments)))
    if not prepared.check_concrete:
        governing = max(all_assessments, key=lambda item: item.utilisation)
        close(authoritative["utilisation"], governing.utilisation,
              "reinforcement-only global utilisation")
        exact(authoritative["governing_spectrum"], governing.spectrum_name,
              "reinforcement-only governing spectrum")
        if (
            type(authoritative["converged"]) is not bool
            or authoritative["converged"]
            != all(item.converged for item in all_assessments)
            or type(authoritative["passed"]) is not bool
            or authoritative["passed"] != all(item.passed for item in all_assessments)
        ):
            fail("reinforcement-only global aggregate state differs")
    return SuccessfulReplay(
        prepared, boundary.analysis_signature(inp), authoritative,
        tuple(spectra))
