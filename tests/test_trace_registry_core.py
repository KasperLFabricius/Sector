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
    TraceStepMetadataContract,
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


def _reseal_metadata(
    replacements: dict[str, tuple[str, TraceSource]],
):
    bundle = _bundle()
    calculation = bundle.calculations[0]
    steps = tuple(
        dataclasses.replace(
            step,
            quantity_role=replacements[step.step_id][0],
            source=replacements[step.step_id][1],
        )
        if step.step_id in replacements
        else step
        for step in calculation.steps
    )
    return create_bundle(
        input_sha256=bundle.input_sha256,
        result_sha256=bundle.result_sha256,
        calculations=(dataclasses.replace(calculation, steps=steps),),
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


def _with_member(registry: TraceRegistryContract, member: TraceMemberContract) -> TraceRegistryContract:
    family = dataclasses.replace(registry.families[0], members=(member,))
    return dataclasses.replace(registry, families=(family,))


def test_mixed_standard_editions_and_project_method_are_local_and_exact():
    bundle = _bundle()
    registry = _registry(RESULT_FINITE)

    assert audit_trace_registry(bundle, registry) is bundle
    member = registry.families[0].members[0]
    concrete_only = frozenset(
        source for source in member.sources if source.edition != "EN 1992-1-1:2023"
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
    member = dataclasses.replace(registry.families[0].members[0], **{field: value})
    registry = _with_member(registry, member)

    with pytest.raises(TraceValidationError, match=message):
        audit_trace_registry(_bundle(), registry)


def test_registry_requires_exact_members_and_explicit_result_state():
    infinite = _bundle(RESULT_POSITIVE_INFINITY)
    assert audit_trace_registry(infinite, _registry(RESULT_POSITIVE_INFINITY)) is infinite
    with pytest.raises(TraceValidationError, match="result state"):
        audit_trace_registry(infinite, _registry(RESULT_FINITE))

    registry = _registry(RESULT_FINITE)
    member = dataclasses.replace(registry.families[0].members[0], calculation_id="missing.member")
    registry = _with_member(registry, member)
    with pytest.raises(TraceValidationError, match="missing missing.member"):
        audit_trace_registry(_bundle(), registry)


STEP_IDS = ("demand", "concrete", "steel", "tendon", "result")
STEP_DEPENDENCIES = (
    ("demand", ()),
    ("concrete", ()),
    ("steel", ()),
    ("tendon", ()),
    ("result", ("demand", "concrete", "steel", "tendon")),
)
STEP_METADATA = (
    TraceStepMetadataContract("demand", ROLE_USER_INPUT, INPUT),
    TraceStepMetadataContract("concrete", ROLE_METHOD_VALUE, CONCRETE),
    TraceStepMetadataContract("steel", ROLE_METHOD_VALUE, STEEL),
    TraceStepMetadataContract("tendon", ROLE_METHOD_VALUE, TENDON),
    TraceStepMetadataContract("result", ROLE_FINAL, COMBINATION),
)


def _step_registry(
    *,
    step_ids: tuple[str, ...] = (),
    step_dependencies: tuple[tuple[str, tuple[str, ...]], ...] = (),
    step_metadata: tuple[TraceStepMetadataContract, ...] = (),
) -> TraceRegistryContract:
    registry = _registry(RESULT_FINITE)
    member = dataclasses.replace(
        registry.families[0].members[0],
        step_ids=step_ids,
        step_dependencies=step_dependencies,
        step_metadata=step_metadata,
    )
    return _with_member(registry, member)


def test_step_order_dependency_and_metadata_contracts_are_independently_optional():
    bundle = _bundle()

    assert audit_trace_registry(bundle, _registry(RESULT_FINITE)) is bundle
    assert (
        audit_trace_registry(
            bundle,
            _step_registry(step_ids=STEP_IDS),
        )
        is bundle
    )
    assert (
        audit_trace_registry(
            bundle,
            _step_registry(step_dependencies=STEP_DEPENDENCIES),
        )
        is bundle
    )
    assert (
        audit_trace_registry(
            bundle,
            _step_registry(step_metadata=STEP_METADATA),
        )
        is bundle
    )
    assert (
        audit_trace_registry(
            bundle,
            _step_registry(
                step_ids=STEP_IDS,
                step_dependencies=STEP_DEPENDENCIES,
                step_metadata=STEP_METADATA,
            ),
        )
        is bundle
    )


def test_step_contracts_reject_wrong_order_and_graph_drift():
    wrong_order = ("demand", "steel", "concrete", "tendon", "result")
    with pytest.raises(TraceValidationError, match="step IDs"):
        audit_trace_registry(
            _bundle(),
            _step_registry(step_ids=wrong_order),
        )

    missing_edge = (
        *STEP_DEPENDENCIES[:-1],
        ("result", ("demand", "concrete", "steel")),
    )
    with pytest.raises(TraceValidationError, match="dependency graph"):
        audit_trace_registry(
            _bundle(),
            _step_registry(step_dependencies=missing_edge),
        )


def test_action_material_swap_passes_legacy_checks_but_fails_step_metadata():
    hostile = _reseal_metadata(
        {
            "demand": (ROLE_METHOD_VALUE, CONCRETE),
            "concrete": (ROLE_USER_INPUT, INPUT),
        }
    )

    legacy_contract = _step_registry(step_dependencies=STEP_DEPENDENCIES)
    assert audit_trace_registry(hostile, legacy_contract) is hostile

    with pytest.raises(TraceValidationError) as raised:
        audit_trace_registry(
            hostile,
            _step_registry(
                step_dependencies=STEP_DEPENDENCIES,
                step_metadata=STEP_METADATA,
            ),
        )
    message = str(raised.value)
    for expected in (
        "step demand quantity role",
        "step demand source",
        "step concrete quantity role",
        "step concrete source",
    ):
        assert expected in message


@pytest.mark.parametrize(
    ("left_id", "right_id"),
    [
        pytest.param("concrete", "steel", id="same-kind-standard-sources"),
        pytest.param("concrete", "tendon", id="standard-project-sources"),
    ],
)
def test_resealed_material_source_swaps_fail_exact_step_identity(
    left_id,
    right_id,
):
    steps = {step.step_id: step for step in _bundle().calculations[0].steps}
    hostile = _reseal_metadata(
        {
            left_id: (steps[left_id].quantity_role, steps[right_id].source),
            right_id: (steps[right_id].quantity_role, steps[left_id].source),
        }
    )

    assert (
        audit_trace_registry(
            hostile,
            _step_registry(step_dependencies=STEP_DEPENDENCIES),
        )
        is hostile
    )
    with pytest.raises(TraceValidationError) as raised:
        audit_trace_registry(
            hostile,
            _step_registry(step_metadata=STEP_METADATA),
        )
    message = str(raised.value)
    assert f"step {left_id} source" in message
    assert f"step {right_id} source" in message


@pytest.mark.parametrize(
    ("step_id", "source", "legacy_accepts"),
    [
        pytest.param(
            "concrete",
            dataclasses.replace(CONCRETE, edition="EN 1992-1-1:2005"),
            False,
            id="edition",
        ),
        pytest.param(
            "concrete",
            dataclasses.replace(
                CONCRETE,
                citation=dataclasses.replace(
                    CONCRETE.citation,
                    document="EN 1992-1-1 Corrigendum",
                ),
            ),
            True,
            id="citation-document",
        ),
        pytest.param(
            "concrete",
            dataclasses.replace(
                CONCRETE,
                citation=dataclasses.replace(CONCRETE.citation, clause="3.2"),
            ),
            True,
            id="clause",
        ),
        pytest.param(
            "concrete",
            dataclasses.replace(
                CONCRETE,
                citation=dataclasses.replace(
                    CONCRETE.citation,
                    locator="Table 3.2",
                ),
            ),
            True,
            id="table",
        ),
        pytest.param(
            "steel",
            dataclasses.replace(
                STEEL,
                citation=dataclasses.replace(STEEL.citation, locator="Eq. (5.3)"),
            ),
            True,
            id="equation",
        ),
    ],
)
def test_standard_identity_drift_fails_exact_step_metadata(
    step_id,
    source,
    legacy_accepts,
):
    step = next(
        item for item in _bundle().calculations[0].steps if item.step_id == step_id
    )
    hostile = _reseal_metadata({step_id: (step.quantity_role, source)})

    if legacy_accepts:
        assert audit_trace_registry(hostile, _registry(RESULT_FINITE)) is hostile
    with pytest.raises(TraceValidationError, match=rf"step {step_id} source"):
        audit_trace_registry(
            hostile,
            _step_registry(step_metadata=STEP_METADATA),
        )


@pytest.mark.parametrize(
    ("metadata", "message"),
    [
        pytest.param(STEP_METADATA[:-1], "missing step metadata", id="missing"),
        pytest.param(
            (*STEP_METADATA, STEP_METADATA[0]),
            "duplicate metadata step",
            id="duplicate",
        ),
        pytest.param(
            (*STEP_METADATA[:-1], dataclasses.replace(STEP_METADATA[-1], step_id="unknown")),
            "unknown/extra step metadata",
            id="unknown",
        ),
        pytest.param(
            (*STEP_METADATA, dataclasses.replace(STEP_METADATA[0], step_id="extra")),
            "unknown/extra step metadata",
            id="extra",
        ),
        pytest.param(
            (STEP_METADATA[0], STEP_METADATA[2], STEP_METADATA[1], *STEP_METADATA[3:]),
            "step metadata rows differ",
            id="reordered",
        ),
    ],
)
def test_malformed_metadata_declarations_fail_closed(metadata, message):
    with pytest.raises(TraceValidationError, match=message):
        audit_trace_registry(
            _bundle(),
            _step_registry(step_metadata=metadata),
        )


@pytest.mark.parametrize(
    ("source", "message"),
    [
        pytest.param(
            dataclasses.replace(CONCRETE, edition=None),
            "source edition",
            id="missing-edition",
        ),
        pytest.param(
            dataclasses.replace(CONCRETE, citation=None),
            "exact standards citation",
            id="missing-citation",
        ),
        pytest.param(
            dataclasses.replace(
                CONCRETE,
                citation=dataclasses.replace(CONCRETE.citation, document=""),
            ),
            "citation document",
            id="missing-document",
        ),
        pytest.param(
            dataclasses.replace(
                CONCRETE,
                citation=dataclasses.replace(CONCRETE.citation, clause=""),
            ),
            "citation clause",
            id="missing-clause",
        ),
        pytest.param(
            dataclasses.replace(
                CONCRETE,
                citation=dataclasses.replace(CONCRETE.citation, locator=""),
            ),
            "citation locator",
            id="missing-locator",
        ),
    ],
)
def test_incomplete_metadata_source_declarations_fail_closed(source, message):
    metadata = tuple(
        dataclasses.replace(item, source=source)
        if item.step_id == "concrete"
        else item
        for item in STEP_METADATA
    )
    with pytest.raises(TraceValidationError, match=message):
        audit_trace_registry(
            _bundle(),
            _step_registry(step_metadata=metadata),
        )


def test_simple_context_free_registry_remains_valid_without_metadata_opt_in():
    value = _step("value", ROLE_USER_INPUT, INPUT, 2.0)
    result = _step(
        "result",
        ROLE_FINAL,
        COMBINATION,
        4.0,
        (TraceDependency("value", UNIT),),
    )
    calculation = TraceCalculation(
        "simple.result",
        "simple",
        "Simple context-free result",
        "mixed-section-solver",
        (),
        "result",
        (value, result),
    )
    bundle = create_bundle(
        input_sha256="c" * 64,
        result_sha256="d" * 64,
        calculations=(calculation,),
    )
    member = TraceMemberContract(
        "simple-member",
        "simple.result",
        "simple",
        "mixed-section-solver",
        (),
        frozenset(
            TraceSourceContract(item.kind, item.method_id, item.edition)
            for item in (INPUT, COMBINATION)
        ),
        frozenset({RESULT_FINITE}),
    )
    registry = TraceRegistryContract(
        "simple-registry",
        (TraceFamilyContract("simple-family", (member,)),),
    )

    assert member.step_metadata == ()
    assert audit_trace_registry(bundle, registry) is bundle


@pytest.mark.parametrize(
    ("step_ids", "dependencies", "message"),
    [
        (
            ("demand", "demand"),
            (),
            "duplicate step ID",
        ),
        (
            (),
            (("demand", ()), ("demand", ())),
            "duplicate dependency step",
        ),
        (
            (),
            (
                ("demand", ()),
                ("result", ("missing",)),
            ),
            "missing dependency",
        ),
        (
            STEP_IDS,
            (
                ("concrete", ()),
                ("demand", ()),
                *STEP_DEPENDENCIES[2:],
            ),
            "exact step order",
        ),
        (
            (),
            (
                ("demand", ("result",)),
                ("result", ()),
            ),
            "forward dependency",
        ),
        (
            (),
            (
                ("demand", ()),
                ("result", ("demand", "demand")),
            ),
            "duplicate dependency",
        ),
    ],
)
def test_malformed_step_contract_declarations_fail_closed(
    step_ids,
    dependencies,
    message,
):
    with pytest.raises(TraceValidationError, match=message):
        audit_trace_registry(
            _bundle(),
            _step_registry(
                step_ids=step_ids,
                step_dependencies=dependencies,
            ),
        )
