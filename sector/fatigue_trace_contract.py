"""Frozen CT-010a reinforcement-fatigue trace contract."""

from __future__ import annotations

from dataclasses import dataclass

from .calculation_trace import (
    RESULT_FAILED,
    RESULT_FINITE,
    RESULT_NEGATIVE_INFINITY,
    RESULT_POSITIVE_INFINITY,
    RESULT_UNDEFINED,
    SOURCE_INPUT,
    SOURCE_PROJECT,
    SOURCE_STANDARD,
    SourceCitation,
    TraceAxis,
    TraceSource,
    TraceUnit,
)
from .trace_registry import (
    TraceFamilyContract,
    TraceMemberContract,
    TraceRegistryContract,
    TraceSourceContract,
    TraceStepMetadataContract,
)


COVERAGE_ID = "ct-010"
FAMILY_ID = "ct-010-reinforcement-fatigue"
REGISTRY_ID = "sector-ct-010a-reinforcement-fatigue-v1"
METHOD_ID = "sector-retained-reinforcement-fatigue-replay"

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
RAW_CONTROLS = (
    "fatigue_on", "fatigue_check_steel", "fatigue_check_concrete",
    "fatigue_edition", "fatigue_concrete_method", "fatigue_gamma_c",
    "fatigue_gamma_s", "fatigue_gamma_ff", "fatigue_beta_cc_t0",
    "fatigue_t0_days", "fatigue_concrete_k1", "fatigue_concrete_c",
    "nl", "ns", "concrete_material_id", "concrete_preset",
)

INPUT = TraceSource(SOURCE_INPUT, "sector-fatigue-input")
BOUNDARY = TraceSource(SOURCE_PROJECT, "sector-fatigue-boundary-normalisation")
ELASTIC = TraceSource(SOURCE_PROJECT, "sector-fatigue-elastic-bin-replay")
VERDICT = TraceSource(SOURCE_PROJECT, "sector-fatigue-reinforcement-verdict")

ONE = TraceUnit("1", "scalar")
MPA = TraceUnit("MPa", "stress")
CYCLES = TraceUnit("cycles", "cycle_count")


@dataclass(frozen=True, slots=True)
class NodeSpec:
    step_id: str
    title: str
    unit: TraceUnit
    role: str
    source: TraceSource
    dependencies: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MemberSpec:
    member_id: str
    calculation_id: str
    axes: tuple[TraceAxis, ...]
    nodes: tuple[NodeSpec, ...]
    states: frozenset[str]


ALL_FINAL_STATES = frozenset({
    RESULT_FINITE,
    RESULT_POSITIVE_INFINITY,
    RESULT_NEGATIVE_INFINITY,
    RESULT_UNDEFINED,
    RESULT_FAILED,
})


def code_sources(edition: str, reinforcement_kind: str):
    """Return S-N and kind-correct proof-stress sources."""

    if reinforcement_kind not in {"mild", "prestress"}:
        raise ValueError("reinforcement kind must be mild or prestress")
    tendon = reinforcement_kind == "prestress"
    if "2023" in edition:
        document = "DS/EN 1992-1-1:2023"
        sn_clause = "Annex E.5"
        proof_clause = (
            "5.3.3 and Annex E.5" if tendon else "5.2.4 and Annex E.5"
        )
        locator = "Tables E.1/E.2 and two-slope S-N relationship"
    else:
        document = "DS/EN 1992-1-1:2005+A1:2014"
        sn_clause = "6.8.4"
        proof_clause = "3.3.6 and 6.8" if tendon else "3.2 and 6.8"
        locator = "Tables 6.3N/6.4N and two-slope S-N relationship"
    sn = TraceSource(
        SOURCE_STANDARD,
        "en-1992-reinforcement-fatigue-sn",
        document,
        SourceCitation(document, sn_clause, locator),
    )
    proof = TraceSource(
        SOURCE_STANDARD,
        (
            "en-1992-prestress-fatigue-yield"
            if tendon
            else "en-1992-reinforcement-fatigue-yield"
        ),
        document,
        SourceCitation(
            document,
            proof_clause,
            "design proof stress and absolute stress utilisation",
        ),
    )
    return sn, proof


def _member_contract(member: MemberSpec) -> TraceMemberContract:
    return TraceMemberContract(
        member_id=member.member_id,
        calculation_id=member.calculation_id,
        coverage_id=COVERAGE_ID,
        method_id=METHOD_ID,
        axes=member.axes,
        sources=frozenset(
            TraceSourceContract(
                node.source.kind,
                node.source.method_id,
                node.source.edition,
            )
            for node in member.nodes
        ),
        result_states=member.states,
        step_ids=tuple(node.step_id for node in member.nodes),
        step_dependencies=tuple(
            (node.step_id, node.dependencies) for node in member.nodes
        ),
        step_metadata=tuple(
            TraceStepMetadataContract(node.step_id, node.role, node.source)
            for node in member.nodes
        ),
    )


def registry_for(members: tuple[MemberSpec, ...]) -> TraceRegistryContract:
    if not members:
        raise ValueError("CT-010a registry needs at least one member")
    return TraceRegistryContract(
        REGISTRY_ID,
        (
            TraceFamilyContract(
                FAMILY_ID,
                tuple(_member_contract(member) for member in members),
            ),
        ),
    )
