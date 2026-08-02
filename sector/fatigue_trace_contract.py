"""Frozen CT-010a identity, source, and dependency contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .calculation_trace import (
    RESULT_FAILED,
    RESULT_FINITE,
    ROLE_COMPUTED,
    ROLE_FINAL,
    ROLE_METHOD_VALUE,
    ROLE_USER_INPUT,
    SOURCE_INPUT,
    SOURCE_PROJECT,
    SOURCE_STANDARD,
    SourceCitation,
    TraceAxis,
    TraceSource,
    TraceUnit,
    trace_identity_token,
)
from .fatigue_trace_reader import ElementEvidence, FatigueEvidence, IdentityLeaf
from .section_trace_blocks import context_axes, context_id
from .trace_registry import (
    TraceFamilyContract,
    TraceMemberContract,
    TraceRegistryContract,
    TraceSourceContract,
    TraceStepMetadataContract,
)


COVERAGE_ID = "ct-010"
FAMILY_ID = "ct-010-reinforcement-fatigue"
REGISTRY_ID = "sector-ct-010-reinforcement-fatigue-v1"
METHOD_ID = "sector-grouped-reinforcement-fatigue-proof"
OUTPUT_MEMBER_ID = "reinforcement-output"
INVALID_MEMBER_ID = "invalid"

INPUT_SOURCE = TraceSource(SOURCE_INPUT, "sector-fatigue-input")
NORMALISATION_SOURCE = TraceSource(
    SOURCE_PROJECT, "sector-fatigue-boundary-normalisation"
)
ELASTIC_SOURCE = TraceSource(
    SOURCE_PROJECT, "sector-fatigue-retained-elastic-response"
)
BOND_PROJECT_SOURCE = TraceSource(
    SOURCE_PROJECT, "sector-fatigue-bond-response"
)
ACCUMULATION_SOURCE = TraceSource(
    SOURCE_PROJECT, "sector-miner-damage-accumulation"
)
YIELD_SOURCE = TraceSource(
    SOURCE_PROJECT, "sector-fatigue-yield-screen"
)
VERDICT_SOURCE = TraceSource(
    SOURCE_PROJECT, "sector-fatigue-reinforcement-verdict"
)
INVALID_SOURCE = TraceSource(
    SOURCE_PROJECT, "sector-fatigue-invalid-boundary"
)

DOC_2005 = "DS/EN 1992-1-1:2005+A1:2014"
DOC_2023 = "DS/EN 1992-1-1:2023"
SN_2005_SOURCE = TraceSource(
    SOURCE_STANDARD,
    "en-1992-1-1-2005-reinforcement-fatigue",
    DOC_2005,
    SourceCitation(DOC_2005, "6.8.4", "Tables 6.3N and 6.4N"),
)
SN_2023_SOURCE = TraceSource(
    SOURCE_STANDARD,
    "en-1992-1-1-2023-reinforcement-fatigue",
    DOC_2023,
    SourceCitation(DOC_2023, "E.5.2", "Tables E.1 and E.2"),
)
BOND_2005_SOURCE = TraceSource(
    SOURCE_STANDARD,
    "en-1992-1-1-2005-mixed-bond-correction",
    DOC_2005,
    SourceCitation(DOC_2005, "6.8.2(2)", "mixed reinforcement bond factor"),
)
BOND_2023_SOURCE = TraceSource(
    SOURCE_STANDARD,
    "en-1992-1-1-2023-equivalent-tendon-area",
    DOC_2023,
    SourceCitation(DOC_2023, "10.3(2)", "equivalent tendon area"),
)

ONE = TraceUnit("1", "scalar")
CYCLES = TraceUnit("cycles", "count")
STRESS = TraceUnit("MPa", "stress")


@dataclass(frozen=True, slots=True)
class StepSpec:
    step_id: str
    title: str
    unit: TraceUnit
    quantity_role: str
    source: TraceSource
    dependencies: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ElementShape:
    evidence: ElementEvidence
    member_id: str
    calculation_id: str
    axes: tuple[TraceAxis, ...]
    sn_source: TraceSource
    bond_source: TraceSource


@dataclass(frozen=True, slots=True)
class OutputShape:
    member_id: str
    calculation_id: str
    axes: tuple[TraceAxis, ...]


@dataclass(frozen=True, slots=True)
class InvalidShape:
    member_id: str
    calculation_id: str
    axes: tuple[TraceAxis, ...]


@dataclass(frozen=True, slots=True)
class FatigueShape:
    evidence: FatigueEvidence
    elements: tuple[ElementShape, ...] = ()
    output: OutputShape | None = None
    invalid: InvalidShape | None = None


class _Rows:
    def __init__(self) -> None:
        self.rows: list[StepSpec] = []
        self.ids: set[str] = set()

    def add(
        self,
        step_id: str,
        title: str,
        unit: TraceUnit,
        role: str,
        source: TraceSource,
        *dependencies: str,
    ) -> str:
        if step_id in self.ids:
            raise ValueError(f"duplicate CT-010a step {step_id}")
        self.ids.add(step_id)
        self.rows.append(StepSpec(
            step_id, title, unit, role, source, tuple(dependencies)
        ))
        return step_id


def _token(value: str) -> str:
    return trace_identity_token(value)


def element_prefix(element: ElementEvidence) -> str:
    return (
        f"element-{element.index:04d}-{_token(element.element_id)}-"
        f"{_token(element.kind)}-{_token(element.material_id)}-"
        f"{_token(element.detail_id)}"
    )


def bin_prefix(spectrum_index: int, spectrum: Any, bin_index: int, row: Any) -> str:
    return (
        f"spectrum-{spectrum_index:03d}-{_token(spectrum.spectrum_name)}-"
        f"bin-{bin_index:04d}-{_token(row.bin_name)}-"
        f"bond-{_token(row.bond_method)}"
    )


def _sn_source(evidence: FatigueEvidence, element: ElementEvidence) -> TraceSource:
    detail = next(
        item for item in evidence.prepared.detail_records
        if item["id"] == element.detail_id
    )
    if detail["custom"]:
        return TraceSource(SOURCE_PROJECT, "sector-user-fatigue-detail")
    return SN_2023_SOURCE if "2023" in evidence.prepared.edition else SN_2005_SOURCE


def _bond_source(evidence: FatigueEvidence) -> TraceSource:
    section = evidence.prepared.section
    if not section.bars or not section.tendons:
        return BOND_PROJECT_SOURCE
    return BOND_2023_SOURCE if "2023" in evidence.prepared.edition else BOND_2005_SOURCE


def trace_shape(evidence: FatigueEvidence) -> FatigueShape:
    context = evidence.context
    token = context_id(context)
    if not evidence.valid:
        axes = context_axes(
            context,
            branch="invalid",
            error_cardinality=str(len(evidence.errors)),
            scope="reinforcement",
        )
        return FatigueShape(
            evidence,
            invalid=InvalidShape(
                INVALID_MEMBER_ID,
                f"fatigue.{token}.invalid",
                axes,
            ),
        )
    concrete_method = evidence.output["concrete_method"]
    concrete_parameters = evidence.output["concrete_parameters"]
    common = {
        "branch": "finite",
        "concrete_method_type": type(concrete_method).__name__.lower(),
        "concrete_parameters_type": type(concrete_parameters).__name__.lower(),
        "edition": evidence.prepared.edition,
        "element_cardinality": str(len(evidence.elements)),
        "scope": "reinforcement",
        "spectrum_cardinality": str(len(evidence.spectra)),
    }
    elements = []
    bond_source = _bond_source(evidence)
    for element in evidence.elements:
        member_id = f"reinforcement-{element.index:04d}-{_token(element.element_id)}"
        axes = context_axes(
            context,
            **common,
            detail=element.detail_id,
            element=element.element_id,
            kind=element.kind,
            material=element.material_id,
        )
        elements.append(ElementShape(
            element,
            member_id,
            f"fatigue.{token}.{member_id}",
            axes,
            _sn_source(evidence, element),
            bond_source,
        ))
    output = OutputShape(
        OUTPUT_MEMBER_ID,
        f"fatigue.{token}.reinforcement-output",
        context_axes(context, **common, member="reinforcement-output"),
    )
    return FatigueShape(evidence, tuple(elements), output=output)


def _identity_steps(rows: _Rows, leaves: tuple[IdentityLeaf, ...]) -> str:
    ids = []
    for leaf in leaves:
        ids.append(rows.add(
            leaf.step_id,
            leaf.title,
            ONE,
            ROLE_USER_INPUT,
            INPUT_SOURCE,
        ))
    vector = rows.add(
        "geometry-material-spectrum-vector",
        "Immutable geometry, material, spectrum and catalogue identity",
        ONE,
        ROLE_COMPUTED,
        NORMALISATION_SOURCE,
        *ids,
    )
    return vector


def _normalised_inputs(rows: _Rows, evidence: FatigueEvidence) -> str:
    vector = _identity_steps(rows, evidence.input_leaves)
    gamma_s = rows.add(
        "input-gamma-s", "Reinforcement partial factor", ONE,
        ROLE_USER_INPUT, INPUT_SOURCE,
    )
    gamma_ff = rows.add(
        "input-gamma-ff", "Fatigue action partial factor", ONE,
        ROLE_USER_INPUT, INPUT_SOURCE,
    )
    gamma_c = rows.add(
        "input-gamma-c", "Concrete partial-factor sibling", ONE,
        ROLE_USER_INPUT, INPUT_SOURCE,
    )
    return rows.add(
        "normalised-fatigue-inputs",
        "Complete retained fatigue input identity",
        ONE,
        ROLE_COMPUTED,
        NORMALISATION_SOURCE,
        vector,
        gamma_s,
        gamma_ff,
        gamma_c,
    )


def expected_element_steps(shape: ElementShape, evidence: FatigueEvidence) -> tuple[StepSpec, ...]:
    rows = _Rows()
    normalised = _normalised_inputs(rows, evidence)
    item = shape.evidence
    prefix = element_prefix(item)
    n_star = rows.add(
        f"{prefix}-n-star", "S-N reference cycles", CYCLES,
        ROLE_METHOD_VALUE, shape.sn_source,
    )
    k1 = rows.add(
        f"{prefix}-k1", "S-N upper-branch exponent", ONE,
        ROLE_METHOD_VALUE, shape.sn_source,
    )
    k2 = rows.add(
        f"{prefix}-k2", "S-N lower-branch exponent", ONE,
        ROLE_METHOD_VALUE, shape.sn_source,
    )
    delta_rsk = rows.add(
        f"{prefix}-delta-sigma-rsk", "Characteristic reference stress range",
        STRESS, ROLE_METHOD_VALUE, shape.sn_source,
    )
    proof_tension = rows.add(
        f"{prefix}-proof-tension", "Tensile proof or yield stress", STRESS,
        ROLE_USER_INPUT, INPUT_SOURCE,
    )
    proof_compression = rows.add(
        f"{prefix}-proof-compression", "Compression proof or yield stress",
        STRESS, ROLE_USER_INPUT, INPUT_SOURCE,
    )
    spectrum_damage_ids = []
    spectrum_yield_ids = []
    spectrum_convergence_ids = []
    spectrum_utilisation_ids = []
    spectrum_verdict_ids = []
    proof_ids = []
    for spectrum_index, (spectrum, result) in enumerate(
        zip(evidence.spectra, item.results)
    ):
        damage_ids = []
        yield_ids = []
        convergence_ids = []
        for bin_index, (state, bin_result) in enumerate(
            zip(spectrum.bins, result.bins)
        ):
            bp = bin_prefix(spectrum_index, spectrum, bin_index, bin_result)
            cycles = rows.add(
                f"{bp}-cycles", "Entered bin cycles", CYCLES,
                ROLE_USER_INPUT, INPUT_SOURCE,
            )
            converged = rows.add(
                f"{bp}-combined-convergence",
                "Retained combined original/equivalent solve convergence",
                ONE, ROLE_COMPUTED, ELASTIC_SOURCE, normalised,
            )
            convergence_ids.append(converged)
            long_stress = rows.add(
                f"{bp}-stress-long", "Long-term element stress", STRESS,
                ROLE_COMPUTED, ELASTIC_SOURCE, normalised,
            )
            total_elastic = rows.add(
                f"{bp}-stress-total-elastic",
                "Uncorrected total element stress", STRESS,
                ROLE_COMPUTED, ELASTIC_SOURCE, normalised,
            )
            total = rows.add(
                f"{bp}-stress-total-fatigue", "Bond-corrected total stress",
                STRESS, ROLE_COMPUTED, shape.bond_source,
                normalised, long_stress, total_elastic, converged,
            )
            total_design = rows.add(
                f"{bp}-stress-total-design",
                "Action-factored bond-corrected total stress", STRESS,
                ROLE_COMPUTED, shape.bond_source,
                normalised, long_stress, total_elastic, converged,
            )
            range_elastic = rows.add(
                f"{bp}-range-elastic", "Uncorrected stress range", STRESS,
                ROLE_COMPUTED, ELASTIC_SOURCE, long_stress, total_elastic,
            )
            stress_range = rows.add(
                f"{bp}-range-fatigue", "Bond-corrected stress range", STRESS,
                ROLE_COMPUTED, shape.bond_source, long_stress, total,
            )
            design_range = rows.add(
                f"{bp}-range-design", "Design stress range", STRESS,
                ROLE_COMPUTED, shape.bond_source, long_stress, total_design,
            )
            bond = rows.add(
                f"{bp}-bond-adjustment", "Retained bond adjustment", ONE,
                ROLE_COMPUTED, shape.bond_source, range_elastic, stress_range,
            )
            exponent = rows.add(
                f"{bp}-sn-exponent", "Selected S-N exponent", ONE,
                ROLE_COMPUTED, shape.sn_source,
                design_range, delta_rsk, k1, k2,
            )
            log_life = rows.add(
                f"{bp}-log10-life", "Logarithmic cycles to failure", ONE,
                ROLE_COMPUTED, shape.sn_source,
                design_range, delta_rsk, n_star, exponent, "input-gamma-s",
            )
            life = rows.add(
                f"{bp}-cycles-to-failure", "Cycles to failure", CYCLES,
                ROLE_COMPUTED, shape.sn_source, log_life,
            )
            damage = rows.add(
                f"{bp}-damage", "Miner damage", ONE,
                ROLE_COMPUTED, ACCUMULATION_SOURCE, cycles, log_life, life,
            )
            damage_ids.append(damage)
            governing_stress = rows.add(
                f"{bp}-governing-stress", "Governing absolute stress", STRESS,
                ROLE_COMPUTED, YIELD_SOURCE, long_stress, total_design,
            )
            yield_limit = rows.add(
                f"{bp}-yield-limit", "Signed-state yield/proof limit", STRESS,
                ROLE_COMPUTED, YIELD_SOURCE,
                governing_stress, proof_tension, proof_compression,
                "input-gamma-s",
            )
            yield_util = rows.add(
                f"{bp}-yield-utilisation", "Yield/proof utilisation", ONE,
                ROLE_COMPUTED, YIELD_SOURCE, governing_stress, yield_limit,
            )
            yield_ids.append(yield_util)
            proof_ids.append(rows.add(
                f"{bp}-bin-proof", "Complete independent bin proof", ONE,
                ROLE_COMPUTED, VERDICT_SOURCE,
                normalised, converged, cycles, long_stress, total_elastic,
                total, total_design, range_elastic, stress_range,
                design_range, bond, exponent, log_life, life, damage,
                governing_stress, yield_limit, yield_util,
            ))
        spectrum_prefix = (
            f"{prefix}-spectrum-{spectrum_index:03d}-"
            f"{_token(spectrum.spectrum_name)}"
        )
        damage_sum = rows.add(
            f"{spectrum_prefix}-damage-sum",
            "Accumulated damage in this independent spectrum", ONE,
            ROLE_COMPUTED, ACCUMULATION_SOURCE, *damage_ids,
        )
        damage_governing = rows.add(
            f"{spectrum_prefix}-governing-damage-bin-"
            f"{_token(result.governing_damage_bin)}",
            "Governing damage-bin identity", ONE,
            ROLE_COMPUTED, VERDICT_SOURCE, *damage_ids,
        )
        yield_maximum = rows.add(
            f"{spectrum_prefix}-yield-maximum",
            "Maximum yield utilisation in this independent spectrum", ONE,
            ROLE_COMPUTED, YIELD_SOURCE, *yield_ids,
        )
        yield_governing = rows.add(
            f"{spectrum_prefix}-governing-yield-bin-"
            f"{_token(result.governing_yield_bin)}",
            "Governing yield-bin identity", ONE,
            ROLE_COMPUTED, VERDICT_SOURCE, *yield_ids,
        )
        spectrum_converged = rows.add(
            f"{spectrum_prefix}-converged",
            "All-bin convergence in this independent spectrum", ONE,
            ROLE_COMPUTED, ELASTIC_SOURCE, *convergence_ids,
        )
        spectrum_utilisation = rows.add(
            f"{spectrum_prefix}-utilisation",
            "Independent spectrum element utilisation", ONE,
            ROLE_COMPUTED, VERDICT_SOURCE, damage_sum, yield_maximum,
        )
        spectrum_passed = rows.add(
            f"{spectrum_prefix}-passed",
            "Independent spectrum element verdict", ONE,
            ROLE_COMPUTED, VERDICT_SOURCE,
            spectrum_converged, damage_sum, yield_maximum,
            spectrum_utilisation,
        )
        proof_ids.append(rows.add(
            f"{spectrum_prefix}-proof", "Complete spectrum selector proof", ONE,
            ROLE_COMPUTED, VERDICT_SOURCE,
            damage_sum, damage_governing, yield_maximum, yield_governing,
            spectrum_converged, spectrum_utilisation, spectrum_passed,
        ))
        spectrum_damage_ids.append(damage_sum)
        spectrum_yield_ids.append(yield_maximum)
        spectrum_convergence_ids.append(spectrum_converged)
        spectrum_utilisation_ids.append(spectrum_utilisation)
        spectrum_verdict_ids.append(spectrum_passed)
    damage_maximum = rows.add(
        f"{prefix}-damage-maximum", "Maximum independent-spectrum damage", ONE,
        ROLE_COMPUTED, ACCUMULATION_SOURCE, *spectrum_damage_ids,
    )
    yield_max = rows.add(
        f"{prefix}-yield-maximum", "Maximum element yield utilisation", ONE,
        ROLE_COMPUTED, YIELD_SOURCE, *spectrum_yield_ids,
    )
    converged = rows.add(
        f"{prefix}-converged", "All-spectrum combined convergence", ONE,
        ROLE_COMPUTED, ELASTIC_SOURCE, *spectrum_convergence_ids,
    )
    utilisation = rows.add(
        f"{prefix}-utilisation", "Element fatigue utilisation", ONE,
        ROLE_COMPUTED, VERDICT_SOURCE, *spectrum_utilisation_ids,
    )
    passed = rows.add(
        f"{prefix}-passed", "Element reinforcement fatigue verdict", ONE,
        ROLE_COMPUTED, VERDICT_SOURCE,
        converged, damage_maximum, yield_max, utilisation,
        *spectrum_verdict_ids,
    )
    rows.add(
        f"ct-010a-{prefix}-result",
        "CT-010a reinforcement element result",
        ONE,
        ROLE_FINAL,
        VERDICT_SOURCE,
        normalised,
        *proof_ids,
        damage_maximum,
        yield_max,
        converged,
        utilisation,
        passed,
    )
    return tuple(rows.rows)


def expected_output_steps(shape: OutputShape, evidence: FatigueEvidence) -> tuple[StepSpec, ...]:
    rows = _Rows()
    normalised = _normalised_inputs(rows, evidence)
    summaries = []
    for element in evidence.elements:
        prefix = element_prefix(element)
        for spectrum_index, (spectrum, result) in enumerate(
            zip(evidence.spectra, element.results)
        ):
            sp = f"output-{prefix}-spectrum-{spectrum_index:03d}-{_token(spectrum.spectrum_name)}"
            damage = rows.add(
                f"{sp}-damage", "Published element damage", ONE,
                ROLE_COMPUTED, ACCUMULATION_SOURCE, normalised,
            )
            yield_util = rows.add(
                f"{sp}-yield-utilisation", "Published element yield utilisation",
                ONE, ROLE_COMPUTED, YIELD_SOURCE, normalised,
            )
            convergence = rows.add(
                f"{sp}-convergence", "Published combined convergence", ONE,
                ROLE_COMPUTED, ELASTIC_SOURCE, normalised,
            )
            utilisation = rows.add(
                f"{sp}-utilisation", "Published element utilisation", ONE,
                ROLE_COMPUTED, VERDICT_SOURCE, damage, yield_util,
            )
            verdict = rows.add(
                f"{sp}-passed", "Published element verdict", ONE,
                ROLE_COMPUTED, VERDICT_SOURCE,
                convergence, damage, yield_util, utilisation,
            )
            summaries.extend((damage, yield_util, convergence, utilisation, verdict))
    output_converged = rows.add(
        "reinforcement-output-converged",
        "All reinforcement elements converged",
        ONE, ROLE_COMPUTED, VERDICT_SOURCE, normalised, *summaries,
    )
    output_utilisation = rows.add(
        "reinforcement-output-utilisation",
        "Governing reinforcement utilisation",
        ONE, ROLE_COMPUTED, VERDICT_SOURCE, normalised, *summaries,
    )
    output_passed = rows.add(
        "reinforcement-output-passed",
        "Overall reinforcement fatigue verdict",
        ONE, ROLE_COMPUTED, VERDICT_SOURCE,
        normalised, output_converged, output_utilisation, *summaries,
    )
    rows.add(
        "ct-010a-reinforcement-output-result",
        "CT-010a reinforcement output",
        ONE, ROLE_FINAL, VERDICT_SOURCE,
        normalised, "input-gamma-c", output_converged,
        output_utilisation, output_passed, *summaries,
    )
    return tuple(rows.rows)


def expected_invalid_steps(shape: InvalidShape, evidence: FatigueEvidence) -> tuple[StepSpec, ...]:
    rows = _Rows()
    identity = _identity_steps(rows, evidence.input_leaves)
    error_ids = []
    for index, error in enumerate(evidence.errors):
        error_ids.append(rows.add(
            f"invalid-error-{index:03d}-{_token(error)}",
            "Retained fatigue validation error",
            ONE, ROLE_COMPUTED, INVALID_SOURCE, identity,
        ))
    rows.add(
        "ct-010a-invalid-result", "CT-010a invalid fatigue boundary", ONE,
        ROLE_FINAL, INVALID_SOURCE, identity, *error_ids,
    )
    return tuple(rows.rows)


def _source_contract(source: TraceSource) -> TraceSourceContract:
    return TraceSourceContract(source.kind, source.method_id, source.edition)


def _member(member_id: str, calculation_id: str, axes: tuple[TraceAxis, ...], specs: tuple[StepSpec, ...]) -> TraceMemberContract:
    return TraceMemberContract(
        member_id=member_id,
        calculation_id=calculation_id,
        coverage_id=COVERAGE_ID,
        method_id=METHOD_ID,
        axes=axes,
        sources=frozenset(_source_contract(spec.source) for spec in specs),
        result_states=frozenset({RESULT_FINITE, RESULT_FAILED}),
        step_ids=tuple(spec.step_id for spec in specs),
        step_dependencies=tuple(
            (spec.step_id, spec.dependencies) for spec in specs
        ),
        step_metadata=tuple(
            TraceStepMetadataContract(
                spec.step_id, spec.quantity_role, spec.source
            )
            for spec in specs
        ),
    )


def expected_registry(shape: FatigueShape) -> TraceRegistryContract:
    members = []
    if shape.invalid is not None:
        specs = expected_invalid_steps(shape.invalid, shape.evidence)
        members.append(_member(
            shape.invalid.member_id, shape.invalid.calculation_id,
            shape.invalid.axes, specs,
        ))
    else:
        for element in shape.elements:
            specs = expected_element_steps(element, shape.evidence)
            members.append(_member(
                element.member_id, element.calculation_id,
                element.axes, specs,
            ))
        assert shape.output is not None
        specs = expected_output_steps(shape.output, shape.evidence)
        members.append(_member(
            shape.output.member_id, shape.output.calculation_id,
            shape.output.axes, specs,
        ))
    return TraceRegistryContract(
        REGISTRY_ID,
        (TraceFamilyContract(FAMILY_ID, tuple(members)),),
    )
