"""Exact successful reinforcement-fatigue trace contract for CT-010a."""

from __future__ import annotations

from dataclasses import dataclass

from .calculation_trace import (
    RESULT_FINITE, RESULT_POSITIVE_INFINITY, SOURCE_INPUT, SOURCE_PROJECT,
    SOURCE_STANDARD,
    SourceCitation, TraceAxis, TraceSource, TraceUnit,
)
from .trace_registry import (
    TraceFamilyContract, TraceMemberContract, TraceRegistryContract,
    TraceSourceContract, TraceStepMetadataContract,
)


COVERAGE_ID = "ct-010"
FAMILY_ID = "ct-010-reinforcement-fatigue"
METHOD_ID = "sector-retained-reinforcement-fatigue-replay"
REGISTRY_ID = "sector-ct-010a-reinforcement-fatigue-success-v1"

SUCCESS_KEYS = (
    "edition", "checks", "concrete_method", "basis", "method_reference",
    "calculation_references", "warnings", "partial_factors",
    "concrete_parameters", "reinforcement_properties",
    "fatigue_detail_basis", "t0_days", "elements", "spectra",
    "governing_spectrum", "utilisation", "converged", "passed",
)
INVALID_KEYS = (
    "valid", "converged", "passed", "errors", "warnings", "edition",
    "checks", "basis", "method_reference", "calculation_references",
    "partial_factors", "concrete_parameters", "fatigue_detail_basis",
    "t0_days", "elements", "spectra", "governing_spectrum", "utilisation",
)
RAW_INPUT_KEYS = (
    "fatigue_on", "fatigue_check_steel", "fatigue_check_concrete",
    "fatigue_edition", "fatigue_concrete_method", "fatigue_gamma_c",
    "fatigue_gamma_s", "fatigue_gamma_ff", "fatigue_beta_cc_t0",
    "fatigue_t0_days", "fatigue_concrete_k1", "fatigue_concrete_c",
    "nl", "ns", "concrete_material_id", "concrete_preset",
)

INPUT = TraceSource(SOURCE_INPUT, "sector-fatigue-input")
BOUNDARY = TraceSource(SOURCE_PROJECT, "sector-fatigue-boundary-replay")
ELASTIC = TraceSource(SOURCE_PROJECT, "sector-fatigue-elastic-state-replay")
VERDICT = TraceSource(SOURCE_PROJECT, "sector-fatigue-reinforcement-verdict")
ONE = TraceUnit("1", "scalar")
MPA = TraceUnit("MPa", "stress")
CYCLES = TraceUnit("cycles", "cycle_count")


def selected_sources(
    edition: str, kind: str, custom_detail: bool,
) -> tuple[TraceSource, TraceSource]:
    if kind not in {"mild", "prestress"}:
        raise ValueError("reinforcement kind must be mild or prestress")
    if type(custom_detail) is not bool:
        raise TypeError("custom detail flag must be exact Boolean")
    current = "2023" in edition
    document = (
        "DS/EN 1992-1-1:2023" if current
        else "DS/EN 1992-1-1:2005+A1:2014")
    sn = (
        TraceSource(SOURCE_PROJECT, "sector-custom-reinforcement-fatigue-sn")
        if custom_detail else
        TraceSource(
            SOURCE_STANDARD, "en-1992-reinforcement-fatigue-sn", edition,
            SourceCitation(
                document, "Annex E.5" if current else "6.8.4",
                ("Tables E.1/E.2" if current else "Tables 6.3N/6.4N")
                + " and two-slope S-N relationship"),
        )
    )
    tendon = kind == "prestress"
    proof = TraceSource(
        SOURCE_STANDARD,
        ("en-1992-prestress-fatigue-proof" if tendon
         else "en-1992-reinforcement-fatigue-proof"),
        edition,
        SourceCitation(
            document,
            (("5.3.3" if tendon else "5.2.4") + " and Annex E.5")
            if current else
            (("3.3.6" if tendon else "3.2") + " and 6.8"),
            "design proof stress and absolute stress utilisation"),
    )
    return sn, proof


@dataclass(frozen=True, slots=True)
class StepShape:
    step_id: str
    title: str
    unit: TraceUnit
    role: str
    source: TraceSource
    dependencies: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MemberShape:
    member_id: str
    calculation_id: str
    axes: tuple[TraceAxis, ...]
    steps: tuple[StepShape, ...]


def registry_for(members: tuple[MemberShape, ...]) -> TraceRegistryContract:
    if not members:
        raise ValueError("successful CT-010a registry cannot be empty")
    rows = []
    for member in members:
        rows.append(TraceMemberContract(
            member_id=member.member_id,
            calculation_id=member.calculation_id,
            coverage_id=COVERAGE_ID,
            method_id=METHOD_ID,
            axes=member.axes,
            sources=frozenset(
                TraceSourceContract(
                    step.source.kind, step.source.method_id,
                    step.source.edition)
                for step in member.steps),
            result_states=frozenset({
                RESULT_FINITE, RESULT_POSITIVE_INFINITY,
            }),
            step_ids=tuple(step.step_id for step in member.steps),
            step_dependencies=tuple(
                (step.step_id, step.dependencies) for step in member.steps),
            step_metadata=tuple(
                TraceStepMetadataContract(
                    step.step_id, step.role, step.source)
                for step in member.steps),
        ))
    return TraceRegistryContract(
        REGISTRY_ID,
        (TraceFamilyContract(FAMILY_ID, tuple(rows)),),
    )
