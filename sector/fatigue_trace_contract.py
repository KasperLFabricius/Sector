"""Registry and dependency contract for CT-010a reinforcement fatigue."""

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

INPUT_SOURCE = TraceSource(SOURCE_INPUT, "sector-fatigue-input")
NORMAL_SOURCE = TraceSource(SOURCE_PROJECT, "sector-fatigue-normalisation")
SOLVER_SOURCE = TraceSource(SOURCE_PROJECT, "sector-fatigue-elastic-replay")
DAMAGE_SOURCE = TraceSource(SOURCE_PROJECT, "sector-fatigue-log-miner")
YIELD_SOURCE = TraceSource(SOURCE_PROJECT, "sector-fatigue-yield-proof")
SELECT_SOURCE = TraceSource(SOURCE_PROJECT, "sector-fatigue-selection")
CUSTOM_SN_SOURCE = TraceSource(SOURCE_PROJECT, "sector-custom-fatigue-detail")
PERFECT_BOND_SOURCE = TraceSource(SOURCE_PROJECT, "sector-perfect-bond")

DOC_2005 = "DS/EN 1992-1-1:2005+A1:2014"
DOC_2023 = "DS/EN 1992-1-1:2023"
SN_2005_SOURCE = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2005-steel-fatigue", DOC_2005,
    SourceCitation(DOC_2005, "6.8.4", "Tables 6.3N and 6.4N"),
)
SN_2023_SOURCE = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2023-steel-fatigue", DOC_2023,
    SourceCitation(DOC_2023, "E.5.2", "Tables E.1 and E.2"),
)
BOND_2005_SOURCE = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2005-bond-correction", DOC_2005,
    SourceCitation(DOC_2005, "6.8.2(2)", "mixed reinforcement bond"),
)
BOND_2023_SOURCE = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2023-equivalent-area", DOC_2023,
    SourceCitation(DOC_2023, "10.3(2)", "equivalent tendon area"),
)

ONE = TraceUnit("1", "scalar")
STRESS = TraceUnit("MPa", "stress")
CYCLES = TraceUnit("cycles", "count")
FINAL_STATES = frozenset({
    RESULT_FINITE, RESULT_FAILED, RESULT_POSITIVE_INFINITY,
    RESULT_NEGATIVE_INFINITY, RESULT_UNDEFINED,
})


@dataclass(frozen=True, slots=True)
class Leaf:
    step_id: str
    title: str
    value: float | None
    absent: bool = False


@dataclass(frozen=True, slots=True)
class BinModel:
    position: int
    name: str
    bond_method: str


@dataclass(frozen=True, slots=True)
class MemberModel:
    member_id: str
    calculation_id: str
    axes: tuple[TraceAxis, ...]
    element_position: int
    spectrum_position: int
    element_id: str
    kind: str
    material_id: str
    detail_id: str
    spectrum_name: str
    bins: tuple[BinModel, ...]
    sn_source: TraceSource
    bond_source: TraceSource


@dataclass(frozen=True, slots=True)
class FamilyModel:
    branch: str
    leaves: tuple[Leaf, ...]
    members: tuple[MemberModel, ...]
    context_token: str
    aggregate_axes: tuple[TraceAxis, ...] | None
    invalid_axes: tuple[TraceAxis, ...] | None
    errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StepModel:
    step_id: str
    title: str
    unit: TraceUnit
    role: str
    source: TraceSource
    dependencies: tuple[str, ...] = ()


class _Graph:
    def __init__(self):
        self.steps: list[StepModel] = []
        self.ids: set[str] = set()

    def add(self, step_id, title, unit, role, source, *dependencies):
        if step_id in self.ids:
            raise ValueError(f"duplicate CT-010a step {step_id}")
        self.ids.add(step_id)
        self.steps.append(StepModel(
            step_id, title, unit, role, source, tuple(dependencies)
        ))
        return step_id


def identity_token(value: str) -> str:
    return trace_identity_token(value)


def member_prefix(member: MemberModel) -> str:
    return (
        f"element-{member.element_position:04d}-{identity_token(member.element_id)}-"
        f"{identity_token(member.kind)}-{identity_token(member.material_id)}-"
        f"{identity_token(member.detail_id)}-spectrum-"
        f"{member.spectrum_position:03d}-{identity_token(member.spectrum_name)}"
    )


def bin_prefix(bin_model: BinModel) -> str:
    return (
        f"bin-{bin_model.position:04d}-{identity_token(bin_model.name)}-"
        f"bond-{identity_token(bin_model.bond_method)}"
    )


def success_model(*, leaves, rows, context, edition, concrete_method_type,
                  concrete_parameters_type):
    token = context_id(context)
    common = dict(
        branch="success", scope="reinforcement", edition=edition,
        concrete_method_type=concrete_method_type,
        concrete_parameters_type=concrete_parameters_type,
    )
    members = []
    for row in rows:
        (element_position, spectrum_position, element_id, kind, material_id,
         detail_id, spectrum_name, bins, sn_source, bond_source) = row
        member_id = (
            f"reinforcement-{element_position:04d}-{identity_token(element_id)}-"
            f"spectrum-{spectrum_position:03d}-{identity_token(spectrum_name)}"
        )
        members.append(MemberModel(
            member_id=member_id,
            calculation_id=f"fatigue.{token}.{member_id}",
            axes=context_axes(
                context, **common, element=element_id, kind=kind,
                material=material_id, detail=detail_id, spectrum=spectrum_name,
            ),
            element_position=element_position,
            spectrum_position=spectrum_position,
            element_id=element_id,
            kind=kind,
            material_id=material_id,
            detail_id=detail_id,
            spectrum_name=spectrum_name,
            bins=tuple(BinModel(*item) for item in bins),
            sn_source=sn_source,
            bond_source=bond_source,
        ))
    aggregate_axes = context_axes(
        context, **common, member="reinforcement-output",
        assessment_cardinality=str(len(members)),
    )
    return FamilyModel(
        "success", tuple(leaves), tuple(members), token,
        aggregate_axes, None, (),
    )


def invalid_model(*, leaves, errors, context, edition,
                  concrete_parameters_type):
    token = context_id(context)
    axes = context_axes(
        context, branch="invalid", scope="reinforcement", edition=edition,
        error_cardinality=str(len(errors)),
        concrete_parameters_type=concrete_parameters_type,
    )
    return FamilyModel("invalid", tuple(leaves), (), token, None, axes,
                       tuple(errors))


def _input_root(graph: _Graph, family: FamilyModel):
    leaves = tuple(
        graph.add(leaf.step_id, leaf.title, ONE, ROLE_USER_INPUT, INPUT_SOURCE)
        for leaf in family.leaves
    )
    vector = graph.add(
        "fatigue-input-vector", "Complete fatigue input identity", ONE,
        ROLE_COMPUTED, NORMAL_SOURCE, *leaves,
    )
    gamma_s = graph.add(
        "input-gamma-s", "Reinforcement partial factor", ONE,
        ROLE_USER_INPUT, INPUT_SOURCE,
    )
    gamma_ff = graph.add(
        "input-gamma-ff", "Fatigue action factor", ONE,
        ROLE_USER_INPUT, INPUT_SOURCE,
    )
    gamma_c = graph.add(
        "input-gamma-c", "Concrete sibling factor", ONE,
        ROLE_USER_INPUT, INPUT_SOURCE,
    )
    return graph.add(
        "normalised-fatigue-inputs", "Complete normalised fatigue input", ONE,
        ROLE_COMPUTED, NORMAL_SOURCE, vector, gamma_s, gamma_ff, gamma_c,
    )


def assessment_steps(family: FamilyModel, member: MemberModel):
    graph = _Graph()
    normal = _input_root(graph, family)
    prefix = member_prefix(member)
    nstar = graph.add(f"{prefix}-nstar", "S-N reference cycles", CYCLES,
                      ROLE_METHOD_VALUE, member.sn_source)
    k1 = graph.add(f"{prefix}-k1", "Upper S-N exponent", ONE,
                   ROLE_METHOD_VALUE, member.sn_source)
    k2 = graph.add(f"{prefix}-k2", "Lower S-N exponent", ONE,
                   ROLE_METHOD_VALUE, member.sn_source)
    reference = graph.add(f"{prefix}-reference", "Reference stress range", STRESS,
                          ROLE_METHOD_VALUE, member.sn_source)
    tension = graph.add(f"{prefix}-tension-proof", "Tensile proof stress", STRESS,
                        ROLE_USER_INPUT, INPUT_SOURCE)
    compression = graph.add(
        f"{prefix}-compression-proof", "Compression proof stress", STRESS,
        ROLE_USER_INPUT, INPUT_SOURCE,
    )
    damages, yields, convergences, proofs = [], [], [], []
    for bin_model in member.bins:
        bp = bin_prefix(bin_model)
        cycles = graph.add(f"{bp}-cycles", "Entered cycles", CYCLES,
                           ROLE_USER_INPUT, INPUT_SOURCE)
        converged = graph.add(f"{bp}-converged", "Combined solve convergence", ONE,
                              ROLE_COMPUTED, SOLVER_SOURCE, normal)
        long = graph.add(f"{bp}-long", "Long stress", STRESS,
                         ROLE_COMPUTED, SOLVER_SOURCE, normal)
        elastic = graph.add(f"{bp}-elastic", "Elastic total stress", STRESS,
                            ROLE_COMPUTED, SOLVER_SOURCE, normal)
        fatigue = graph.add(
            f"{bp}-fatigue", "Bond-adjusted total stress", STRESS,
            ROLE_COMPUTED, member.bond_source, normal, long, elastic, converged,
        )
        design = graph.add(
            f"{bp}-design", "Design total stress", STRESS,
            ROLE_COMPUTED, member.bond_source, normal, long, elastic, converged,
        )
        erange = graph.add(f"{bp}-elastic-range", "Elastic stress range", STRESS,
                           ROLE_COMPUTED, SOLVER_SOURCE, long, elastic)
        frange = graph.add(f"{bp}-fatigue-range", "Fatigue stress range", STRESS,
                           ROLE_COMPUTED, member.bond_source, long, fatigue)
        drange = graph.add(f"{bp}-design-range", "Design stress range", STRESS,
                           ROLE_COMPUTED, member.bond_source, long, design)
        bond = graph.add(f"{bp}-bond-factor", "Bond adjustment", ONE,
                         ROLE_COMPUTED, member.bond_source, erange, frange)
        exponent = graph.add(
            f"{bp}-exponent", "Selected S-N exponent", ONE,
            ROLE_COMPUTED, member.sn_source, drange, reference, k1, k2,
        )
        loglife = graph.add(
            f"{bp}-loglife", "Logarithmic fatigue life", ONE,
            ROLE_COMPUTED, member.sn_source,
            drange, reference, nstar, exponent, "input-gamma-s",
        )
        life = graph.add(f"{bp}-life", "Cycles to failure", CYCLES,
                         ROLE_COMPUTED, member.sn_source, loglife)
        damage = graph.add(f"{bp}-damage", "Miner damage", ONE,
                           ROLE_COMPUTED, DAMAGE_SOURCE, cycles, loglife, life)
        stress = graph.add(f"{bp}-governing-stress", "Governing stress", STRESS,
                           ROLE_COMPUTED, YIELD_SOURCE, long, design)
        limit = graph.add(
            f"{bp}-yield-limit", "Yield or proof limit", STRESS,
            ROLE_COMPUTED, YIELD_SOURCE,
            stress, tension, compression, "input-gamma-s",
        )
        yutil = graph.add(f"{bp}-yield-utilisation", "Yield utilisation", ONE,
                          ROLE_COMPUTED, YIELD_SOURCE, stress, limit)
        proof = graph.add(
            f"{bp}-proof", "Complete bin proof", ONE,
            ROLE_COMPUTED, SELECT_SOURCE, normal, cycles, converged, long,
            elastic, fatigue, design, erange, frange, drange, bond, exponent,
            loglife, life, damage, stress, limit, yutil,
        )
        damages.append(damage)
        yields.append(yutil)
        convergences.append(converged)
        proofs.append(proof)
    damage = graph.add(f"{prefix}-damage", "Spectrum damage", ONE,
                       ROLE_COMPUTED, DAMAGE_SOURCE, *damages)
    damage_bin = graph.add(f"{prefix}-damage-bin", "Governing damage-bin index", ONE,
                           ROLE_COMPUTED, SELECT_SOURCE, *damages)
    yutil = graph.add(f"{prefix}-yield-utilisation", "Spectrum yield utilisation", ONE,
                      ROLE_COMPUTED, YIELD_SOURCE, *yields)
    yield_bin = graph.add(f"{prefix}-yield-bin", "Governing yield-bin index", ONE,
                          ROLE_COMPUTED, SELECT_SOURCE, *yields)
    converged = graph.add(f"{prefix}-converged", "Spectrum convergence", ONE,
                          ROLE_COMPUTED, SOLVER_SOURCE, *convergences)
    utilisation = graph.add(f"{prefix}-utilisation", "Spectrum utilisation", ONE,
                            ROLE_COMPUTED, SELECT_SOURCE, damage, yutil)
    passed = graph.add(f"{prefix}-passed", "Spectrum verdict", ONE,
                       ROLE_COMPUTED, SELECT_SOURCE,
                       converged, damage, yutil, utilisation)
    graph.add(
        f"ct-010a-{prefix}-result", "CT-010a assessment", ONE,
        ROLE_FINAL, SELECT_SOURCE, normal, *proofs, damage, damage_bin,
        yutil, yield_bin, converged, utilisation, passed,
    )
    return tuple(graph.steps)


def aggregate_steps(family: FamilyModel):
    graph = _Graph()
    normal = _input_root(graph, family)
    summaries = []
    for member in family.members:
        prefix = f"published-{member_prefix(member)}"
        damage = graph.add(f"{prefix}-damage", "Published spectrum damage", ONE,
                           ROLE_COMPUTED, DAMAGE_SOURCE, normal)
        yutil = graph.add(f"{prefix}-yield-utilisation",
                          "Published yield utilisation", ONE,
                          ROLE_COMPUTED, YIELD_SOURCE, normal)
        converged = graph.add(f"{prefix}-converged", "Published convergence", ONE,
                              ROLE_COMPUTED, SOLVER_SOURCE, normal)
        utilisation = graph.add(f"{prefix}-utilisation",
                                "Published spectrum utilisation", ONE,
                                ROLE_COMPUTED, SELECT_SOURCE, damage, yutil)
        passed = graph.add(f"{prefix}-passed", "Published spectrum verdict", ONE,
                           ROLE_COMPUTED, SELECT_SOURCE,
                           converged, damage, yutil, utilisation)
        summaries.extend((damage, yutil, converged, utilisation, passed))
    converged = graph.add(
        "reinforcement-output-converged", "All assessments converged", ONE,
        ROLE_COMPUTED, SELECT_SOURCE, normal, *summaries,
    )
    utilisation = graph.add(
        "reinforcement-output-utilisation", "Governing reinforcement utilisation",
        ONE, ROLE_COMPUTED, SELECT_SOURCE, normal, *summaries,
    )
    passed = graph.add(
        "reinforcement-output-passed", "Overall verdict", ONE,
        ROLE_COMPUTED, SELECT_SOURCE, normal, converged, utilisation, *summaries,
    )
    graph.add(
        "ct-010a-reinforcement-output-result", "CT-010a output", ONE,
        ROLE_FINAL, SELECT_SOURCE, normal, "input-gamma-c", converged,
        utilisation, passed, *summaries,
    )
    return tuple(graph.steps)


def invalid_steps(family: FamilyModel):
    graph = _Graph()
    normal = _input_root(graph, family)
    errors = tuple(
        graph.add(
            f"invalid-error-{index:03d}-{identity_token(error)}",
            "Retained validation error", ONE, ROLE_COMPUTED, SELECT_SOURCE, normal,
        )
        for index, error in enumerate(family.errors)
    )
    graph.add(
        "ct-010a-invalid-result", "Invalid CT-010a boundary", ONE,
        ROLE_FINAL, SELECT_SOURCE, normal, *errors,
    )
    return tuple(graph.steps)


def _member_contract(member_id, calculation_id, axes, steps):
    return TraceMemberContract(
        member_id, calculation_id, COVERAGE_ID, METHOD_ID, axes,
        frozenset(
            TraceSourceContract(step.source.kind, step.source.method_id,
                                step.source.edition)
            for step in steps
        ),
        FINAL_STATES,
        tuple(step.step_id for step in steps),
        tuple((step.step_id, step.dependencies) for step in steps),
        tuple(
            TraceStepMetadataContract(step.step_id, step.role, step.source)
            for step in steps
        ),
    )


def expected_registry(family: FamilyModel):
    contracts = []
    if family.branch == "success":
        for member in family.members:
            steps = assessment_steps(family, member)
            contracts.append(_member_contract(
                member.member_id, member.calculation_id, member.axes, steps
            ))
        steps = aggregate_steps(family)
        contracts.append(_member_contract(
            "reinforcement-output",
            f"fatigue.{family.context_token}.reinforcement-output",
            family.aggregate_axes,
            steps,
        ))
    elif family.branch == "invalid":
        steps = invalid_steps(family)
        contracts.append(_member_contract(
            "invalid", f"fatigue.{family.context_token}.invalid",
            family.invalid_axes, steps,
        ))
    else:
        raise ValueError("unknown CT-010a branch")
    return TraceRegistryContract(
        REGISTRY_ID, (TraceFamilyContract(FAMILY_ID, tuple(contracts)),)
    )
