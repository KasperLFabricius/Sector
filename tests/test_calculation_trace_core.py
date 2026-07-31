from __future__ import annotations

import copy
import dataclasses
import math

import pytest

from sector.calculation_trace import (
    RESULT_FAILED,
    RESULT_FINITE,
    RESULT_NEGATIVE_INFINITY,
    RESULT_POSITIVE_INFINITY,
    RESULT_UNDEFINED,
    ROLE_FINAL,
    ROLE_METHOD_VALUE,
    ROLE_USER_INPUT,
    SOURCE_INPUT,
    SOURCE_PROJECT,
    SOURCE_STANDARD,
    SourceCitation,
    TraceAxis,
    TraceBundle,
    TraceCalculation,
    TraceDependency,
    TraceResult,
    TraceSource,
    TraceStep,
    TraceUnit,
    TraceValidationError,
    bundle_from_json,
    bundle_to_json,
    create_bundle,
    seal_bundle,
    trace_identity_token,
    validate_bundle,
)


INPUT_SHA = "1" * 64
RESULT_SHA = "2" * 64
FORCE = TraceUnit("kN", "force")
SCALAR = TraceUnit("1", "dimensionless")
INPUT = TraceSource(SOURCE_INPUT, "user-input")
STANDARD = TraceSource(
    SOURCE_STANDARD,
    "synthetic-standard-method",
    "Synthetic Standard:2026",
    SourceCitation("SYN 1", "3.2", "Eq. (1)"),
)


def _step(
    step_id: str,
    role: str,
    source: TraceSource,
    unit: TraceUnit,
    value: float | None,
    *,
    dependencies: tuple[TraceDependency, ...] = (),
    state: str = RESULT_FINITE,
    reason: str | None = None,
) -> TraceStep:
    return TraceStep(
        step_id=step_id,
        title=step_id.replace("-", " ").title(),
        dependencies=dependencies,
        quantity_role=role,
        source=source,
        symbol=step_id,
        unit=unit,
        actual_expression=f"{step_id} expression",
        substituted_expression=f"{step_id} substitution",
        result=TraceResult(state, value, reason),
        warnings=("synthetic warning",) if role == ROLE_FINAL else (),
        assumptions=("synthetic assumption",) if role == ROLE_FINAL else (),
    )


def _calculation(
    *,
    final_result: TraceResult | None = None,
    steps: tuple[TraceStep, ...] | None = None,
    calculation_id: str = "synthetic.capacity",
) -> TraceCalculation:
    input_step = _step("demand", ROLE_USER_INPUT, INPUT, FORCE, 2.0)
    factor_step = _step("factor", ROLE_METHOD_VALUE, STANDARD, SCALAR, 3.0)
    final_step = _step(
        "resistance",
        ROLE_FINAL,
        STANDARD,
        FORCE,
        6.0,
        dependencies=(
            TraceDependency("demand", FORCE),
            TraceDependency("factor", SCALAR),
        ),
    )
    if final_result is not None:
        final_step = dataclasses.replace(final_step, result=final_result)
    return TraceCalculation(
        calculation_id=calculation_id,
        coverage_id="synthetic-001",
        title="Synthetic capacity",
        method_id="synthetic-capacity",
        axes=(TraceAxis("direction", "x"),),
        final_step_id="resistance",
        steps=steps or (input_step, factor_step, final_step),
        warnings=("calculation warning",),
        assumptions=("calculation assumption",),
    )


def _bundle(calculation: TraceCalculation | None = None) -> TraceBundle:
    return create_bundle(
        input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA,
        calculations=(_calculation() if calculation is None else calculation,),
    )


def _raw(calculation: TraceCalculation) -> TraceBundle:
    return TraceBundle(INPUT_SHA, RESULT_SHA, (calculation,))


def test_schema_is_immutable_complete_data_without_evaluation_api():
    bundle = _bundle()
    final = bundle.calculations[0].steps[-1]
    expected = 2.0 * 3.0

    assert final.result.value == expected
    assert final.actual_expression == "resistance expression"
    assert final.substituted_expression == "resistance substitution"
    assert final.warnings and final.assumptions and final.source.citation
    assert "operator" not in final.to_dict()
    assert "evaluation" not in final.to_dict()
    with pytest.raises(dataclasses.FrozenInstanceError):
        final.title = "changed"


def test_schema_rejects_top_level_and_nested_subclasses_before_sealing():
    class HostileBundle(TraceBundle):
        def to_dict(self):
            return {**super().to_dict(), "invented": True}

    class HostileStep(TraceStep):
        pass

    class PoisonTuple(tuple):
        def __iter__(self):
            raise AssertionError("tuple subclass was iterated")

    class PoisonText(str):
        def __hash__(self):
            raise AssertionError("string subclass was hashed")

        def __ne__(self, other):
            return False

    bundle = _bundle()
    hostile_id = dataclasses.replace(bundle.calculations[0], calculation_id=PoisonText("poison"))
    with pytest.raises(TraceValidationError, match="calculation_id"):
        seal_bundle(_raw(hostile_id))
    with pytest.raises(TraceValidationError, match="expected_input_sha256"):
        validate_bundle(bundle, expected_input_sha256=PoisonText("3" * 64))
    with pytest.raises(TraceValidationError, match="TraceBundle"):
        seal_bundle(HostileBundle(INPUT_SHA, RESULT_SHA, bundle.calculations))
    with pytest.raises(TraceValidationError, match="calculation tuple"):
        seal_bundle(dataclasses.replace(bundle, calculations=PoisonTuple(bundle.calculations)))
    step = bundle.calculations[0].steps[0]
    values = {field.name: getattr(step, field.name) for field in dataclasses.fields(step)}
    calculation = dataclasses.replace(
        bundle.calculations[0],
        steps=(HostileStep(**values), *bundle.calculations[0].steps[1:]),
    )
    with pytest.raises(TraceValidationError, match="TraceStep"):
        seal_bundle(_raw(calculation))
    poisoned = dataclasses.replace(step, warnings=PoisonTuple())
    with pytest.raises(TraceValidationError, match="immutable tuple"):
        seal_bundle(_raw(dataclasses.replace(bundle.calculations[0], steps=(poisoned, *bundle.calculations[0].steps[1:]))))


def test_canonical_round_trip_is_stable_and_preserves_exact_shapes():
    encoded = bundle_to_json(_bundle())
    decoded = bundle_from_json(encoded)

    assert bundle_to_json(decoded) == encoded
    assert decoded == _bundle()
    assert '"dependencies":[' in encoded
    assert ":NaN" not in encoded and ":Infinity" not in encoded


@pytest.mark.parametrize(
    "state",
    [
        RESULT_POSITIVE_INFINITY,
        RESULT_NEGATIVE_INFINITY,
        RESULT_UNDEFINED,
        RESULT_FAILED,
    ],
)
def test_explicit_nonfinite_and_failure_states_use_null_numbers(state):
    result = TraceResult(state, None, "synthetic physical outcome")
    encoded = bundle_to_json(_bundle(_calculation(final_result=result)))

    assert f'"state":"{state}"' in encoded
    assert '"value":null' in encoded
    assert "Infinity" not in encoded and "NaN" not in encoded


@pytest.mark.parametrize("value", [True, math.inf, -math.inf, math.nan, 10**1000])
def test_nonfinite_or_boolean_finite_inputs_are_rejected(value):
    calculation = _calculation()
    hostile = dataclasses.replace(
        calculation.steps[0],
        result=TraceResult(RESULT_FINITE, value),
    )
    calculation = dataclasses.replace(
        calculation, steps=(hostile, *calculation.steps[1:])
    )

    with pytest.raises(TraceValidationError, match="finite value"):
        seal_bundle(_raw(calculation))


def test_missing_duplicate_and_cyclic_dependencies_fail_closed():
    base = _calculation()
    final = base.steps[-1]
    invalid_dependencies = (
        (TraceDependency("missing", FORCE),),
        (
            TraceDependency("demand", FORCE),
            TraceDependency("demand", FORCE),
        ),
    )
    for dependencies in invalid_dependencies:
        changed = dataclasses.replace(final, dependencies=dependencies)
        with pytest.raises(TraceValidationError, match="dependency"):
            seal_bundle(
                _raw(dataclasses.replace(base, steps=(*base.steps[:-1], changed)))
            )

    cyclic = dataclasses.replace(
        base.steps[0],
        quantity_role=ROLE_FINAL,
        source=STANDARD,
        dependencies=(TraceDependency("resistance", FORCE),),
    )
    with pytest.raises(TraceValidationError, match="forward, or cyclic"):
        seal_bundle(
            _raw(dataclasses.replace(base, final_step_id="demand", steps=(cyclic,)))
        )


def test_duplicate_step_and_calculation_ids_are_rejected():
    calculation = _calculation()
    duplicate_step = dataclasses.replace(
        calculation.steps[-1], step_id="factor", dependencies=()
    )
    with pytest.raises(TraceValidationError, match="duplicate step ID"):
        seal_bundle(
            _raw(
                dataclasses.replace(
                    calculation, steps=(*calculation.steps, duplicate_step)
                )
            )
        )
    with pytest.raises(TraceValidationError, match="duplicate calculation ID"):
        create_bundle(
            input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA,
            calculations=(calculation, calculation),
        )


def test_dependency_unit_mismatch_is_rejected_even_with_same_dimension():
    calculation = _calculation()
    final = dataclasses.replace(
        calculation.steps[-1],
        dependencies=(
            TraceDependency("demand", TraceUnit("N", "force")),
            TraceDependency("factor", SCALAR),
        ),
    )
    with pytest.raises(TraceValidationError, match="unit mismatch"):
        seal_bundle(
            _raw(
                dataclasses.replace(
                    calculation, steps=(*calculation.steps[:-1], final)
                )
            )
        )


def test_unknown_shape_shifted_and_duplicate_serialized_fields_are_rejected():
    payload = _bundle().to_dict()
    unknown = copy.deepcopy(payload)
    unknown["calculations"][0]["steps"][0]["invented"] = True
    with pytest.raises(TraceValidationError, match="unexpected invented"):
        validate_bundle(unknown)

    shifted = copy.deepcopy(payload)
    shifted["calculations"][0]["steps"][2]["dependencies"] = {}
    with pytest.raises(TraceValidationError, match="JSON list"):
        validate_bundle(shifted)

    with pytest.raises(TraceValidationError, match="duplicate JSON field"):
        bundle_from_json('{"schema":"one","schema":"two"}')
    with pytest.raises(TraceValidationError, match="non-finite JSON number"):
        bundle_from_json('{"value":NaN}')


def test_tamper_stale_fingerprints_and_invented_project_citations_are_rejected():
    bundle = _bundle()
    tampered = bundle.to_dict()
    tampered["calculations"][0]["steps"][-1]["result"]["value"] = 7.0
    with pytest.raises(TraceValidationError, match="content seal"):
        validate_bundle(tampered)
    with pytest.raises(TraceValidationError, match="input fingerprint"):
        validate_bundle(bundle, expected_input_sha256="3" * 64)
    with pytest.raises(TraceValidationError, match="result fingerprint"):
        validate_bundle(bundle, expected_result_sha256="4" * 64)

    citation = SourceCitation("Invented Standard", "1", "Eq. (1)")
    project = TraceSource(SOURCE_PROJECT, "project-method", citation=citation)
    calculation = _calculation()
    hostile = dataclasses.replace(calculation.steps[1], source=project)
    with pytest.raises(TraceValidationError, match="cannot carry"):
        seal_bundle(
            _raw(
                dataclasses.replace(
                    calculation,
                    steps=(calculation.steps[0], hostile, calculation.steps[2]),
                )
            )
        )


def test_identity_tokens_are_injective_for_colliding_display_slugs():
    labels = ("A+B", "A B", "Traffic+A", "Traffic A", "\u00e5", "a")
    tokens = tuple(trace_identity_token(item) for item in labels)

    assert len(set(tokens)) == len(labels)
    assert all(token.startswith("u") for token in tokens)
