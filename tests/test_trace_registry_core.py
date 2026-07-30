from __future__ import annotations

import dataclasses

import pytest

from sector.calculation_trace import (
    RESULT_FINITE,
    RESULT_POSITIVE_INFINITY,
    ROLE_FINAL,
    ROLE_METHOD_VALUE,
    ROLE_USER_INPUT,
    SOURCE_INPUT,
    SOURCE_PROJECT,
    SOURCE_STANDARD,
    SourceCitation,
    TraceAxis,
    TraceCalculation,
    TraceDependency,
    TraceResult,
    TraceSource,
    TraceStep,
    TraceUnit,
    TraceValidationError,
    create_bundle,
)
from sector.trace_registry import (
    TraceFamilyContract,
    TraceMemberContract,
    TraceRegistryContract,
    TraceSourceContract,
    audit_trace_registry,
)


UNIT = TraceUnit("1", "dimensionless")
INPUT = TraceSource(SOURCE_INPUT, "user-input")
CONCRETE = TraceSource(
    SOURCE_STANDARD,
    "concrete-model",
    "EN 1992-1-1:2004",
    SourceCitation("EN 1992-1-1", "3.1", "Table 3.1"),
)
STEEL = TraceSource(
    SOURCE_STANDARD,
    "reinforcement-model",
    "EN 1992-1-1:2023",
    SourceCitation("EN 1992-1-1", "5.2", "Eq. (5.2)"),
)
TENDON = TraceSource(SOURCE_PROJECT, "project-tendon-model")
COMBINATION = TraceSource(SOURCE_PROJECT, "mixed-section-solver")


def _step(
    step_id: str,
    role: str,
    source: TraceSource,
    value: float | None,
    dependencies: tuple[TraceDependency, ...] = (),
    state: str = RESULT_FINITE,
) -> TraceStep:
    return TraceStep(
        step_id,
        step_id,
        dependencies,
        role,
        source,
        step_id,
        UNIT,
        f"{step_id} expression",
        f"{step_id} substitution",
        TraceResult(
            state,
            value,
            None if state == RESULT_FINITE else "unbounded physical outcome",
        ),
    )


def _bundle(state: str = RESULT_FINITE):
    leaves = (
        _step("demand", ROLE_USER_INPUT, INPUT, 10.0),
        _step("concrete", ROLE_METHOD_VALUE, CONCRETE, 1.0),
        _step("steel", ROLE_METHOD_VALUE, STEEL, 2.0),
        _step("tendon", ROLE_METHOD_VALUE, TENDON, 3.0),
    )
    final = _step(
        "result",
        ROLE_FINAL,
        COMBINATION,
        42.0 if state == RESULT_FINITE else None,
        tuple(TraceDependency(item.step_id, UNIT) for item in leaves),
        state,
    )
    calculation = TraceCalculation(
        "mixed.capacity",
        "synthetic-mixed",
        "Mixed local provenance",
        "mixed-section-solver",
        (TraceAxis("direction", "x"), TraceAxis("method", "direct")),
        "result",
        (*leaves, final),
    )
    return create_bundle(
        input_sha256="a" * 64,
        result_sha256="b" * 64,
        calculations=(calculation,),
    )


def _registry(*states: str) -> TraceRegistryContract:
    sources = frozenset(
        TraceSourceContract(item.kind, item.method_id, item.edition)
        for item in (INPUT, CONCRETE, STEEL, TENDON, COMBINATION)
    )
    member = TraceMemberContract(
        "mixed-member",
        "mixed.capacity",
        "synthetic-mixed",
        "mixed-section-solver",
        (TraceAxis("direction", "x"), TraceAxis("method", "direct")),
        sources,
        frozenset(states),
    )
    return TraceRegistryContract(
        "synthetic-registry",
        (TraceFamilyContract("synthetic-family", (member,)),),
    )


def _with_member(
    registry: TraceRegistryContract, member: TraceMemberContract
) -> TraceRegistryContract:
    family = dataclasses.replace(registry.families[0], members=(member,))
    return dataclasses.replace(registry, families=(family,))


def test_mixed_standard_editions_and_project_method_are_local_and_exact():
    bundle = _bundle()
    registry = _registry(RESULT_FINITE)

    assert audit_trace_registry(bundle, registry) is bundle
    member = registry.families[0].members[0]
    concrete_only = frozenset(
        source
        for source in member.sources
        if source.edition != "EN 1992-1-1:2023"
    )
    hostile_registry = _with_member(
        registry, dataclasses.replace(member, sources=concrete_only)
    )
    with pytest.raises(TraceValidationError, match="sources"):
        audit_trace_registry(bundle, hostile_registry)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("coverage_id", "wrong-family", "coverage"),
        ("method_id", "wrong-method", "method"),
        ("axes", (TraceAxis("direction", "y"),), "axes"),
    ],
)
def test_registry_requires_exact_family_method_and_axes(field, value, message):
    registry = _registry(RESULT_FINITE)
    member = dataclasses.replace(
        registry.families[0].members[0], **{field: value}
    )
    registry = _with_member(registry, member)

    with pytest.raises(TraceValidationError, match=message):
        audit_trace_registry(_bundle(), registry)


def test_registry_requires_exact_members_and_explicit_result_state():
    infinite = _bundle(RESULT_POSITIVE_INFINITY)
    assert audit_trace_registry(
        infinite, _registry(RESULT_POSITIVE_INFINITY)
    ) is infinite
    with pytest.raises(TraceValidationError, match="result state"):
        audit_trace_registry(infinite, _registry(RESULT_FINITE))

    registry = _registry(RESULT_FINITE)
    member = dataclasses.replace(
        registry.families[0].members[0], calculation_id="missing.member"
    )
    registry = _with_member(registry, member)
    with pytest.raises(TraceValidationError, match="missing missing.member"):
        audit_trace_registry(_bundle(), registry)
