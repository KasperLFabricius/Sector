"""Exact reinforcement and concrete fatigue trace contracts for CT-010."""

from __future__ import annotations

from dataclasses import dataclass

from .calculation_trace import (
    RESULT_FAILED, RESULT_FINITE, RESULT_POSITIVE_INFINITY, SOURCE_INPUT,
    SOURCE_PROJECT, SOURCE_STANDARD,
    SourceCitation, TraceAxis, TraceSource, TraceUnit,
)
from .trace_registry import (
    TraceFamilyContract, TraceMemberContract, TraceRegistryContract,
    TraceSourceContract, TraceStepMetadataContract,
)


COVERAGE_ID = "ct-010"
FAMILY_ID = "ct-010-reinforcement-fatigue"
CONCRETE_FAMILY_ID = "ct-010-concrete-fatigue"
AGGREGATE_FAMILY_ID = "ct-010-fatigue-aggregate"
METHOD_ID = "sector-retained-reinforcement-fatigue-replay"
CONCRETE_METHOD_ID = "sector-retained-concrete-fatigue-replay"
AGGREGATE_METHOD_ID = "sector-retained-fatigue-aggregate-replay"
REGISTRY_ID = "sector-ct-010a-reinforcement-fatigue-success-v1"
COMBINED_REGISTRY_ID = "sector-ct-010-fatigue-success-v2"
INVALID_REGISTRY_ID = "sector-ct-010a-reinforcement-fatigue-invalid-v1"
CONCRETE_INVALID_REGISTRY_ID = "sector-ct-010b-concrete-fatigue-invalid-v1"

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
CONCRETE_SEARCH = TraceSource(
    SOURCE_PROJECT, "sector-concrete-fatigue-bounded-search"
)
CONCRETE_VERDICT = TraceSource(
    SOURCE_PROJECT, "sector-fatigue-concrete-verdict"
)
FATIGUE_VERDICT = TraceSource(
    SOURCE_PROJECT, "sector-fatigue-combined-verdict"
)
ONE = TraceUnit("1", "scalar")
MPA = TraceUnit("MPa", "stress")
METRE = TraceUnit("m", "length")
DAYS = TraceUnit("days", "time")
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


def selected_concrete_sources(
    edition: str,
    method: str,
) -> tuple[TraceSource, TraceSource]:
    """Return distinct strength and selected-method provenance."""

    current = "2023" in edition
    strength = TraceSource(
        SOURCE_STANDARD,
        (
            "en-1992-concrete-fatigue-strength-2023"
            if current else "en-1992-concrete-fatigue-strength-2005"
        ),
        edition,
        SourceCitation(
            (
                "DS/EN 1992-1-1:2023"
                if current else "DS/EN 1992-1-1:2005+A1:2014"
            ),
            "10.5" if current else "6.8.7",
            "Formula (10.5)" if current else "Formula (6.76)",
        ),
    )
    if method == "User-defined Miner S-N relation":
        fatigue = TraceSource(
            SOURCE_PROJECT, "sector-project-concrete-fatigue-sn"
        )
    elif method == "Damage-equivalent stress amplitude":
        fatigue = TraceSource(
            SOURCE_STANDARD,
            "en-1992-concrete-fatigue-equivalent",
            edition,
            SourceCitation(
                (
                    "DS/EN 1992-1-1:2023"
                    if current else "DS/EN 1992-1-1:2005+A1:2014"
                ),
                "E.4.3" if current else "6.8.7",
                "Formula (E.2)" if current else "Formulae (6.72)-(6.75)",
            ),
        )
    else:
        fatigue = TraceSource(
            SOURCE_STANDARD,
            "en-1992-concrete-fatigue-miner",
            edition,
            SourceCitation(
                (
                    "DS/EN 1992-1-1:2023"
                    if current else "DS/EN 1992-2:2005/AC:2008"
                ),
                "E.5.3" if current else "6.106",
                (
                    "Formulae (E.7)-(E.8)"
                    if current else "corrected concrete compression S-N relation"
                ),
            ),
        )
    return strength, fatigue


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


def _contracts(
    members: tuple[MemberShape, ...],
    method_id: str,
) -> tuple[TraceMemberContract, ...]:
    rows = []
    for member in members:
        rows.append(TraceMemberContract(
            member_id=member.member_id,
            calculation_id=member.calculation_id,
            coverage_id=COVERAGE_ID,
            method_id=method_id,
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
    return tuple(rows)


def registry_for(
    members: tuple[MemberShape, ...],
    *,
    concrete_members: tuple[MemberShape, ...] = (),
    aggregate_members: tuple[MemberShape, ...] = (),
) -> TraceRegistryContract:
    if not (members or concrete_members or aggregate_members):
        raise ValueError("successful CT-010 registry cannot be empty")
    if not concrete_members and not aggregate_members:
        return TraceRegistryContract(
            REGISTRY_ID,
            (TraceFamilyContract(
                FAMILY_ID, _contracts(members, METHOD_ID)),),
        )
    families = []
    if members:
        families.append(TraceFamilyContract(
            FAMILY_ID, _contracts(members, METHOD_ID)))
    if concrete_members:
        families.append(TraceFamilyContract(
            CONCRETE_FAMILY_ID,
            _contracts(concrete_members, CONCRETE_METHOD_ID)))
    if aggregate_members:
        families.append(TraceFamilyContract(
            AGGREGATE_FAMILY_ID,
            _contracts(aggregate_members, AGGREGATE_METHOD_ID)))
    return TraceRegistryContract(COMBINED_REGISTRY_ID, tuple(families))


def invalid_registry(
    member: MemberShape,
    *,
    concrete_only: bool = False,
) -> TraceRegistryContract:
    """Declare the one retained calculation-free CT-010a failure member."""

    contract = TraceMemberContract(
        member_id=member.member_id,
        calculation_id=member.calculation_id,
        coverage_id=COVERAGE_ID,
        method_id=(CONCRETE_METHOD_ID if concrete_only else METHOD_ID),
        axes=member.axes,
        sources=frozenset(
            TraceSourceContract(
                step.source.kind, step.source.method_id, step.source.edition)
            for step in member.steps),
        result_states=frozenset({RESULT_FAILED}),
        step_ids=tuple(step.step_id for step in member.steps),
        step_dependencies=tuple(
            (step.step_id, step.dependencies) for step in member.steps),
        step_metadata=tuple(
            TraceStepMetadataContract(
                step.step_id, step.role, step.source)
            for step in member.steps),
    )
    return TraceRegistryContract(
        (
            CONCRETE_INVALID_REGISTRY_ID
            if concrete_only else INVALID_REGISTRY_ID
        ),
        (TraceFamilyContract(
            CONCRETE_FAMILY_ID if concrete_only else FAMILY_ID,
            (contract,),
        ),),
    )
