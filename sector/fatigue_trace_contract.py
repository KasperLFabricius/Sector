"""Exact CT-010a registry and dependency declarations."""

from __future__ import annotations

from dataclasses import dataclass

from .calculation_trace import (
    RESULT_FAILED, RESULT_FINITE, RESULT_NEGATIVE_INFINITY,
    RESULT_POSITIVE_INFINITY, RESULT_UNDEFINED, ROLE_COMPUTED, ROLE_FINAL,
    ROLE_METHOD_VALUE, ROLE_USER_INPUT, SOURCE_INPUT, SOURCE_PROJECT,
    SOURCE_STANDARD, SourceCitation, TraceAxis, TraceSource, TraceUnit,
    trace_identity_token,
)
from .section_trace_blocks import context_axes, context_id
from .trace_registry import (
    TraceFamilyContract, TraceMemberContract, TraceRegistryContract,
    TraceSourceContract, TraceStepMetadataContract,
)


COVERAGE_ID = "ct-010"
FAMILY_ID = "ct-010-reinforcement-fatigue"
REGISTRY_ID = "sector-ct-010-reinforcement-fatigue-v1"
METHOD_ID = "sector-independent-spectrum-reinforcement-fatigue"

INPUT = TraceSource(SOURCE_INPUT, "sector-fatigue-input")
NORMALISE = TraceSource(SOURCE_PROJECT, "sector-fatigue-normalisation")
ELASTIC = TraceSource(SOURCE_PROJECT, "sector-fatigue-elastic-replay")
MINER = TraceSource(SOURCE_PROJECT, "sector-log-domain-miner-sum")
YIELD = TraceSource(SOURCE_PROJECT, "sector-fatigue-yield-proof")
SELECT = TraceSource(SOURCE_PROJECT, "sector-fatigue-result-selection")
CUSTOM_SN = TraceSource(SOURCE_PROJECT, "sector-custom-fatigue-detail")

DOC05 = "DS/EN 1992-1-1:2005+A1:2014"
DOC23 = "DS/EN 1992-1-1:2023"
SN05 = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2005-steel-fatigue", DOC05,
    SourceCitation(DOC05, "6.8.4", "Tables 6.3N and 6.4N"),
)
SN23 = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2023-steel-fatigue", DOC23,
    SourceCitation(DOC23, "E.5.2", "Tables E.1 and E.2"),
)
BOND05 = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2005-bond-correction", DOC05,
    SourceCitation(DOC05, "6.8.2(2)", "mixed reinforcement bond correction"),
)
BOND23 = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2023-equivalent-area", DOC23,
    SourceCitation(DOC23, "10.3(2)", "equivalent tendon area"),
)
PERFECT_BOND = TraceSource(SOURCE_PROJECT, "sector-perfect-bond")

ONE = TraceUnit("1", "scalar")
STRESS = TraceUnit("MPa", "stress")
CYCLES = TraceUnit("cycles", "count")

ALL_RESULT_STATES = frozenset({
    RESULT_FINITE, RESULT_FAILED, RESULT_POSITIVE_INFINITY,
    RESULT_NEGATIVE_INFINITY, RESULT_UNDEFINED,
})


@dataclass(frozen=True, slots=True)
class InputLeaf:
    step_id: str
    title: str
    value: float | None
    absent: bool = False


@dataclass(frozen=True, slots=True)
class BinShape:
    index: int
    name: str
    bond_method: str


@dataclass(frozen=True, slots=True)
class MemberShape:
    member_id: str
    calculation_id: str
    axes: tuple[TraceAxis, ...]
    element_index: int
    spectrum_index: int
    element_id: str
    kind: str
    material_id: str
    detail_id: str
    bins: tuple[BinShape, ...]
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
    errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TraceShape:
    leaves: tuple[InputLeaf, ...]
    members: tuple[MemberShape, ...] = ()
    output: OutputShape | None = None
    invalid: InvalidShape | None = None


@dataclass(frozen=True, slots=True)
class StepSpec:
    step_id: str
    title: str
    unit: TraceUnit
    role: str
    source: TraceSource
    dependencies: tuple[str, ...] = ()


class _Rows:
    def __init__(self):
        self.items: list[StepSpec] = []
        self.ids: set[str] = set()

    def add(self, step_id, title, unit, role, source, *dependencies):
        if step_id in self.ids:
            raise ValueError(f"duplicate CT-010a step {step_id}")
        self.ids.add(step_id)
        self.items.append(StepSpec(
            step_id, title, unit, role, source, tuple(dependencies)
        ))
        return step_id


def token(text: str) -> str:
    return trace_identity_token(text)


def member_prefix(shape: MemberShape) -> str:
    return (
        f"element-{shape.element_index:04d}-{token(shape.element_id)}-"
        f"{token(shape.kind)}-{token(shape.material_id)}-"
        f"{token(shape.detail_id)}-spectrum-{shape.spectrum_index:03d}-"
        f"{token(next(axis.value for axis in shape.axes if axis.name == 'spectrum'))}"
    )


def bin_prefix(member: MemberShape, row: BinShape) -> str:
    return (
        f"bin-{row.index:04d}-{token(row.name)}-"
        f"bond-{token(row.bond_method)}"
    )


def make_shape(*, leaves, members_data, context, edition, concrete_method_type,
               concrete_parameters_type, invalid_errors=()):
    context_token = context_id(context)
    if invalid_errors:
        return TraceShape(
            tuple(leaves),
            invalid=InvalidShape(
                "invalid", f"fatigue.{context_token}.invalid",
                context_axes(
                    context, branch="invalid",
                    error_cardinality=str(len(invalid_errors)),
                    scope="reinforcement",
                ),
                tuple(invalid_errors),
            ),
        )
    common = dict(
        branch="retained",
        concrete_method_type=concrete_method_type,
        concrete_parameters_type=concrete_parameters_type,
        edition=edition,
        scope="reinforcement",
    )
    members = []
    for data in members_data:
        element_index, spectrum_index, element_id, kind, material_id, detail_id, spectrum_name, bins, sn_source, bond_source = data
        member_id = (
            f"reinforcement-{element_index:04d}-{token(element_id)}-"
            f"spectrum-{spectrum_index:03d}-{token(spectrum_name)}"
        )
        members.append(MemberShape(
            member_id=member_id,
            calculation_id=f"fatigue.{context_token}.{member_id}",
            axes=context_axes(
                context, **common, element=element_id, kind=kind,
                material=material_id, detail=detail_id,
                spectrum=spectrum_name,
            ),
            element_index=element_index,
            spectrum_index=spectrum_index,
            element_id=element_id,
            kind=kind,
            material_id=material_id,
            detail_id=detail_id,
            bins=tuple(BinShape(i, name, bond) for i, name, bond in bins),
            sn_source=sn_source,
            bond_source=bond_source,
        ))
    return TraceShape(
        tuple(leaves), tuple(members),
        OutputShape(
            "reinforcement-output",
            f"fatigue.{context_token}.reinforcement-output",
            context_axes(
                context, **common,
                member="reinforcement-output",
                member_cardinality=str(len(members)),
            ),
        ),
    )


def _inputs(rows: _Rows, shape: TraceShape):
    leaf_ids = [rows.add(
        leaf.step_id, leaf.title, ONE, ROLE_USER_INPUT, INPUT
    ) for leaf in shape.leaves]
    vector = rows.add(
        "fatigue-input-vector", "Complete immutable fatigue input vector", ONE,
        ROLE_COMPUTED, NORMALISE, *leaf_ids,
    )
    gamma_s = rows.add(
        "input-gamma-s", "Reinforcement partial factor", ONE,
        ROLE_USER_INPUT, INPUT,
    )
    gamma_ff = rows.add(
        "input-gamma-ff", "Fatigue action partial factor", ONE,
        ROLE_USER_INPUT, INPUT,
    )
    gamma_c = rows.add(
        "input-gamma-c", "Concrete sibling partial factor", ONE,
        ROLE_USER_INPUT, INPUT,
    )
    normal = rows.add(
        "normalised-fatigue-inputs", "Complete normalised fatigue identity", ONE,
        ROLE_COMPUTED, NORMALISE, vector, gamma_s, gamma_ff, gamma_c,
    )
    return normal


def member_steps(shape: TraceShape, member: MemberShape):
    rows = _Rows()
    normal = _inputs(rows, shape)
    prefix = member_prefix(member)
    nstar = rows.add(f"{prefix}-n-star", "S-N reference cycles", CYCLES,
                     ROLE_METHOD_VALUE, member.sn_source)
    k1 = rows.add(f"{prefix}-k1", "Upper S-N exponent", ONE,
                  ROLE_METHOD_VALUE, member.sn_source)
    k2 = rows.add(f"{prefix}-k2", "Lower S-N exponent", ONE,
                  ROLE_METHOD_VALUE, member.sn_source)
    reference = rows.add(f"{prefix}-reference-range", "Reference stress range",
                         STRESS, ROLE_METHOD_VALUE, member.sn_source)
    tension = rows.add(f"{prefix}-tension-proof", "Tensile proof stress", STRESS,
                       ROLE_USER_INPUT, INPUT)
    compression = rows.add(f"{prefix}-compression-proof",
                           "Compression proof stress", STRESS,
                           ROLE_USER_INPUT, INPUT)
    damage_ids, yield_ids, convergence_ids, proof_ids = [], [], [], []
    for bin_shape in member.bins:
        bp = bin_prefix(member, bin_shape)
        cycles = rows.add(f"{bp}-cycles", "Entered cycles", CYCLES,
                          ROLE_USER_INPUT, INPUT)
        convergence = rows.add(
            f"{bp}-combined-convergence",
            "Combined original and equivalent-area convergence", ONE,
            ROLE_COMPUTED, ELASTIC, normal,
        )
        convergence_ids.append(convergence)
        long = rows.add(f"{bp}-long-stress", "Long stress", STRESS,
                        ROLE_COMPUTED, ELASTIC, normal)
        elastic_total = rows.add(f"{bp}-elastic-total", "Elastic total stress",
                                 STRESS, ROLE_COMPUTED, ELASTIC, normal)
        fatigue_total = rows.add(f"{bp}-fatigue-total", "Fatigue total stress",
                                 STRESS, ROLE_COMPUTED, member.bond_source,
                                 normal, long, elastic_total, convergence)
        design_total = rows.add(f"{bp}-design-total", "Design total stress",
                                STRESS, ROLE_COMPUTED, member.bond_source,
                                normal, long, elastic_total, convergence)
        elastic_range = rows.add(f"{bp}-elastic-range", "Elastic stress range",
                                 STRESS, ROLE_COMPUTED, ELASTIC,
                                 long, elastic_total)
        fatigue_range = rows.add(f"{bp}-fatigue-range", "Fatigue stress range",
                                 STRESS, ROLE_COMPUTED, member.bond_source,
                                 long, fatigue_total)
        design_range = rows.add(f"{bp}-design-range", "Design stress range",
                                STRESS, ROLE_COMPUTED, member.bond_source,
                                long, design_total)
        bond = rows.add(f"{bp}-bond-factor", "Bond adjustment", ONE,
                        ROLE_COMPUTED, member.bond_source,
                        elastic_range, fatigue_range)
        exponent = rows.add(f"{bp}-sn-exponent", "Selected S-N exponent", ONE,
                            ROLE_COMPUTED, member.sn_source,
                            design_range, reference, k1, k2)
        loglife = rows.add(f"{bp}-log10-life", "Logarithmic fatigue life", ONE,
                           ROLE_COMPUTED, member.sn_source,
                           design_range, reference, nstar, exponent,
                           "input-gamma-s")
        life = rows.add(f"{bp}-life", "Cycles to failure", CYCLES,
                        ROLE_COMPUTED, member.sn_source, loglife)
        damage = rows.add(f"{bp}-damage", "Miner damage", ONE,
                          ROLE_COMPUTED, MINER, cycles, loglife, life)
        damage_ids.append(damage)
        stress = rows.add(f"{bp}-governing-stress", "Governing stress", STRESS,
                          ROLE_COMPUTED, YIELD, long, design_total)
        limit = rows.add(f"{bp}-yield-limit", "Yield/proof limit", STRESS,
                         ROLE_COMPUTED, YIELD, stress, tension, compression,
                         "input-gamma-s")
        yutil = rows.add(f"{bp}-yield-utilisation", "Yield utilisation", ONE,
                         ROLE_COMPUTED, YIELD, stress, limit)
        yield_ids.append(yutil)
        proof_ids.append(rows.add(
            f"{bp}-proof", "Complete bin proof", ONE, ROLE_COMPUTED, SELECT,
            normal, cycles, convergence, long, elastic_total, fatigue_total,
            design_total, elastic_range, fatigue_range, design_range, bond,
            exponent, loglife, life, damage, stress, limit, yutil,
        ))
    damage = rows.add(f"{prefix}-damage", "Spectrum damage", ONE,
                      ROLE_COMPUTED, MINER, *damage_ids)
    damage_bin = rows.add(
        f"{prefix}-governing-damage-bin", "Governing damage bin identity", ONE,
        ROLE_COMPUTED, SELECT, *damage_ids,
    )
    yutil = rows.add(f"{prefix}-yield-utilisation", "Spectrum yield utilisation",
                     ONE, ROLE_COMPUTED, YIELD, *yield_ids)
    yield_bin = rows.add(
        f"{prefix}-governing-yield-bin", "Governing yield bin identity", ONE,
        ROLE_COMPUTED, SELECT, *yield_ids,
    )
    convergence = rows.add(f"{prefix}-converged", "Spectrum convergence", ONE,
                           ROLE_COMPUTED, ELASTIC, *convergence_ids)
    utilisation = rows.add(f"{prefix}-utilisation", "Spectrum utilisation", ONE,
                           ROLE_COMPUTED, SELECT, damage, yutil)
    passed = rows.add(f"{prefix}-passed", "Spectrum verdict", ONE,
                      ROLE_COMPUTED, SELECT,
                      convergence, damage, yutil, utilisation)
    rows.add(
        f"ct-010a-{prefix}-result", "CT-010a element-spectrum result", ONE,
        ROLE_FINAL, SELECT, normal, *proof_ids, damage, damage_bin, yutil,
        yield_bin, convergence, utilisation, passed,
    )
    return tuple(rows.items)


def output_steps(shape: TraceShape):
    rows = _Rows()
    normal = _inputs(rows, shape)
    summaries = []
    for member in shape.members:
        prefix = f"output-{member_prefix(member)}"
        damage = rows.add(f"{prefix}-damage", "Published spectrum damage", ONE,
                          ROLE_COMPUTED, MINER, normal)
        yutil = rows.add(f"{prefix}-yield-utilisation",
                         "Published spectrum yield utilisation", ONE,
                         ROLE_COMPUTED, YIELD, normal)
        convergence = rows.add(f"{prefix}-converged",
                               "Published spectrum convergence", ONE,
                               ROLE_COMPUTED, ELASTIC, normal)
        utilisation = rows.add(f"{prefix}-utilisation",
                               "Published spectrum utilisation", ONE,
                               ROLE_COMPUTED, SELECT, damage, yutil)
        passed = rows.add(f"{prefix}-passed", "Published spectrum verdict", ONE,
                          ROLE_COMPUTED, SELECT,
                          convergence, damage, yutil, utilisation)
        summaries.extend((damage, yutil, convergence, utilisation, passed))
    convergence = rows.add("reinforcement-output-converged",
                           "All reinforcement results converged", ONE,
                           ROLE_COMPUTED, SELECT, normal, *summaries)
    utilisation = rows.add("reinforcement-output-utilisation",
                           "Governing reinforcement utilisation", ONE,
                           ROLE_COMPUTED, SELECT, normal, *summaries)
    passed = rows.add("reinforcement-output-passed",
                      "Overall reinforcement verdict", ONE,
                      ROLE_COMPUTED, SELECT,
                      normal, convergence, utilisation, *summaries)
    rows.add("ct-010a-reinforcement-output-result",
             "CT-010a reinforcement output", ONE, ROLE_FINAL, SELECT,
             normal, "input-gamma-c", convergence, utilisation, passed,
             *summaries)
    return tuple(rows.items)


def invalid_steps(shape: TraceShape):
    rows = _Rows()
    normal = _inputs(rows, shape)
    errors = [rows.add(
        f"invalid-error-{index:03d}-{token(error)}", "Validation error", ONE,
        ROLE_COMPUTED, SELECT, normal,
    ) for index, error in enumerate(shape.invalid.errors)]
    rows.add("ct-010a-invalid-result", "Invalid CT-010a boundary", ONE,
             ROLE_FINAL, SELECT, normal, *errors)
    return tuple(rows.items)


def _member_contract(member_id, calculation_id, axes, specs):
    return TraceMemberContract(
        member_id, calculation_id, COVERAGE_ID, METHOD_ID, axes,
        frozenset(TraceSourceContract(
            spec.source.kind, spec.source.method_id, spec.source.edition
        ) for spec in specs),
        ALL_RESULT_STATES,
        tuple(spec.step_id for spec in specs),
        tuple((spec.step_id, spec.dependencies) for spec in specs),
        tuple(TraceStepMetadataContract(
            spec.step_id, spec.role, spec.source
        ) for spec in specs),
    )


def expected_registry(shape: TraceShape):
    contracts = []
    if shape.invalid is not None:
        specs = invalid_steps(shape)
        contracts.append(_member_contract(
            shape.invalid.member_id, shape.invalid.calculation_id,
            shape.invalid.axes, specs,
        ))
    else:
        for member in shape.members:
            specs = member_steps(shape, member)
            contracts.append(_member_contract(
                member.member_id, member.calculation_id, member.axes, specs,
            ))
        specs = output_steps(shape)
        contracts.append(_member_contract(
            shape.output.member_id, shape.output.calculation_id,
            shape.output.axes, specs,
        ))
    return TraceRegistryContract(
        REGISTRY_ID,
        (TraceFamilyContract(FAMILY_ID, tuple(contracts)),),
    )
