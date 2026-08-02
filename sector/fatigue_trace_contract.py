"""CT-010a immutable member, source, step, and registry contracts."""

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


COVERAGE = "ct-010"
FAMILY = "ct-010-reinforcement-fatigue"
REGISTRY = "sector-ct-010-reinforcement-fatigue-v1"
METHOD = "sector-reinforcement-fatigue-independent-spectra"

INP = TraceSource(SOURCE_INPUT, "sector-fatigue-retained-input")
NORM = TraceSource(SOURCE_PROJECT, "sector-fatigue-input-normalisation")
SOLVE = TraceSource(SOURCE_PROJECT, "sector-fatigue-elastic-replay")
MINE = TraceSource(SOURCE_PROJECT, "sector-fatigue-log-miner")
PROOF = TraceSource(SOURCE_PROJECT, "sector-fatigue-yield-screen")
CHOOSE = TraceSource(SOURCE_PROJECT, "sector-fatigue-selector")
CUSTOM = TraceSource(SOURCE_PROJECT, "sector-custom-fatigue-detail")
PERFECT = TraceSource(SOURCE_PROJECT, "sector-perfect-bond")

EC05 = "DS/EN 1992-1-1:2005+A1:2014"
EC23 = "DS/EN 1992-1-1:2023"
SN05 = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2005-reinforcement-fatigue", EC05,
    SourceCitation(EC05, "6.8.4", "Tables 6.3N and 6.4N"),
)
SN23 = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2023-reinforcement-fatigue", EC23,
    SourceCitation(EC23, "E.5.2", "Tables E.1 and E.2"),
)
BOND05 = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2005-bond-correction", EC05,
    SourceCitation(EC05, "6.8.2(2)", "mixed reinforcement bond correction"),
)
BOND23 = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2023-equivalent-tendon-area", EC23,
    SourceCitation(EC23, "10.3(2)", "equivalent tendon area"),
)

U_ONE = TraceUnit("1", "scalar")
U_STRESS = TraceUnit("MPa", "stress")
U_CYCLES = TraceUnit("cycles", "count")
FINAL_STATES = frozenset({
    RESULT_FINITE, RESULT_FAILED, RESULT_POSITIVE_INFINITY,
    RESULT_NEGATIVE_INFINITY, RESULT_UNDEFINED,
})


@dataclass(frozen=True, slots=True)
class Leaf:
    step_id: str
    title: str
    value: float | None
    missing: bool = False


@dataclass(frozen=True, slots=True)
class Bin:
    position: int
    name: str
    bond: str


@dataclass(frozen=True, slots=True)
class Assessment:
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
    bins: tuple[Bin, ...]
    sn_source: TraceSource
    bond_source: TraceSource


@dataclass(frozen=True, slots=True)
class Joint:
    member_id: str
    calculation_id: str
    axes: tuple[TraceAxis, ...]


@dataclass(frozen=True, slots=True)
class Invalid:
    member_id: str
    calculation_id: str
    axes: tuple[TraceAxis, ...]
    errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FamilyShape:
    branch: str
    leaves: tuple[Leaf, ...]
    assessments: tuple[Assessment, ...] = ()
    joint: Joint | None = None
    invalid: Invalid | None = None


@dataclass(frozen=True, slots=True)
class Step:
    step_id: str
    title: str
    unit: TraceUnit
    role: str
    source: TraceSource
    dependencies: tuple[str, ...] = ()


class Steps:
    def __init__(self):
        self.rows: list[Step] = []
        self.ids: set[str] = set()

    def add(self, step_id, title, unit, role, source, *dependencies):
        if step_id in self.ids:
            raise ValueError(f"duplicate CT-010a step {step_id}")
        self.ids.add(step_id)
        self.rows.append(Step(
            step_id, title, unit, role, source, tuple(dependencies)
        ))
        return step_id


def tok(value: str) -> str:
    return trace_identity_token(value)


def assessment_prefix(item: Assessment) -> str:
    return (
        f"element-{item.element_position:04d}-{tok(item.element_id)}-"
        f"{tok(item.kind)}-{tok(item.material_id)}-{tok(item.detail_id)}-"
        f"spectrum-{item.spectrum_position:03d}-{tok(item.spectrum_name)}"
    )


def bin_prefix(item: Bin) -> str:
    return f"bin-{item.position:04d}-{tok(item.name)}-bond-{tok(item.bond)}"


def success_shape(*, leaves, rows, context, edition, concrete_method_type,
                  concrete_parameters_type):
    base = context_id(context)
    common = dict(
        branch="success", edition=edition, scope="reinforcement",
        concrete_method_type=concrete_method_type,
        concrete_parameters_type=concrete_parameters_type,
    )
    assessments = []
    for row in rows:
        (element_position, spectrum_position, element_id, kind, material_id,
         detail_id, spectrum_name, bins, sn_source, bond_source) = row
        member_id = (
            f"reinforcement-{element_position:04d}-{tok(element_id)}-"
            f"spectrum-{spectrum_position:03d}-{tok(spectrum_name)}"
        )
        assessments.append(Assessment(
            member_id, f"fatigue.{base}.{member_id}",
            context_axes(
                context, **common, element=element_id, kind=kind,
                material=material_id, detail=detail_id,
                spectrum=spectrum_name,
            ),
            element_position, spectrum_position, element_id, kind,
            material_id, detail_id, spectrum_name,
            tuple(Bin(*value) for value in bins), sn_source, bond_source,
        ))
    joint = Joint(
        "reinforcement-output", f"fatigue.{base}.reinforcement-output",
        context_axes(
            context, **common, member="reinforcement-output",
            assessment_cardinality=str(len(assessments)),
        ),
    )
    return FamilyShape("success", tuple(leaves), tuple(assessments), joint)


def invalid_shape(*, leaves, errors, context, edition,
                  concrete_parameters_type):
    base = context_id(context)
    invalid = Invalid(
        "invalid", f"fatigue.{base}.invalid",
        context_axes(
            context, branch="invalid", scope="reinforcement",
            edition=edition, error_cardinality=str(len(errors)),
            concrete_parameters_type=concrete_parameters_type,
        ),
        tuple(errors),
    )
    # Branch is explicit. An empty error tuple is still an invalid member.
    return FamilyShape("invalid", tuple(leaves), invalid=invalid)


def _inputs(rows: Steps, shape: FamilyShape):
    leaf_ids = [rows.add(
        leaf.step_id, leaf.title, U_ONE, ROLE_USER_INPUT, INP
    ) for leaf in shape.leaves]
    vector = rows.add(
        "retained-fatigue-input-vector", "Complete retained fatigue input", U_ONE,
        ROLE_COMPUTED, NORM, *leaf_ids,
    )
    gamma_s = rows.add("input-gamma-s", "Reinforcement partial factor", U_ONE,
                       ROLE_USER_INPUT, INP)
    gamma_ff = rows.add("input-gamma-ff", "Fatigue action factor", U_ONE,
                        ROLE_USER_INPUT, INP)
    gamma_c = rows.add("input-gamma-c", "Concrete sibling factor", U_ONE,
                       ROLE_USER_INPUT, INP)
    return rows.add(
        "normalised-fatigue-inputs", "Complete normalised fatigue state", U_ONE,
        ROLE_COMPUTED, NORM, vector, gamma_s, gamma_ff, gamma_c,
    )


def assessment_steps(shape: FamilyShape, item: Assessment):
    rows = Steps()
    normal = _inputs(rows, shape)
    prefix = assessment_prefix(item)
    nstar = rows.add(f"{prefix}-nstar", "Reference cycles", U_CYCLES,
                     ROLE_METHOD_VALUE, item.sn_source)
    k1 = rows.add(f"{prefix}-k1", "Upper S-N exponent", U_ONE,
                  ROLE_METHOD_VALUE, item.sn_source)
    k2 = rows.add(f"{prefix}-k2", "Lower S-N exponent", U_ONE,
                  ROLE_METHOD_VALUE, item.sn_source)
    reference = rows.add(f"{prefix}-reference-range", "Reference stress range",
                         U_STRESS, ROLE_METHOD_VALUE, item.sn_source)
    tension = rows.add(f"{prefix}-tension-proof", "Tensile proof stress",
                       U_STRESS, ROLE_USER_INPUT, INP)
    compression = rows.add(f"{prefix}-compression-proof",
                           "Compression proof stress", U_STRESS,
                           ROLE_USER_INPUT, INP)
    damages, yields, convergence, proofs = [], [], [], []
    for bin_item in item.bins:
        bp = bin_prefix(bin_item)
        cycles = rows.add(f"{bp}-cycles", "Entered cycles", U_CYCLES,
                          ROLE_USER_INPUT, INP)
        converged = rows.add(f"{bp}-converged", "Combined solve convergence",
                             U_ONE, ROLE_COMPUTED, SOLVE, normal)
        convergence.append(converged)
        long = rows.add(f"{bp}-long", "Long stress", U_STRESS,
                        ROLE_COMPUTED, SOLVE, normal)
        elastic = rows.add(f"{bp}-elastic-total", "Elastic total stress",
                           U_STRESS, ROLE_COMPUTED, SOLVE, normal)
        fatigue = rows.add(f"{bp}-fatigue-total", "Bond-adjusted total stress",
                           U_STRESS, ROLE_COMPUTED, item.bond_source,
                           normal, long, elastic, converged)
        design = rows.add(f"{bp}-design-total", "Design total stress", U_STRESS,
                          ROLE_COMPUTED, item.bond_source,
                          normal, long, elastic, converged)
        erange = rows.add(f"{bp}-elastic-range", "Elastic range", U_STRESS,
                          ROLE_COMPUTED, SOLVE, long, elastic)
        frange = rows.add(f"{bp}-fatigue-range", "Fatigue range", U_STRESS,
                          ROLE_COMPUTED, item.bond_source, long, fatigue)
        drange = rows.add(f"{bp}-design-range", "Design range", U_STRESS,
                          ROLE_COMPUTED, item.bond_source, long, design)
        bond = rows.add(f"{bp}-bond-factor", "Bond factor", U_ONE,
                        ROLE_COMPUTED, item.bond_source, erange, frange)
        exponent = rows.add(f"{bp}-exponent", "Selected S-N exponent", U_ONE,
                            ROLE_COMPUTED, item.sn_source,
                            drange, reference, k1, k2)
        loglife = rows.add(f"{bp}-loglife", "Logarithmic cycles to failure",
                           U_ONE, ROLE_COMPUTED, item.sn_source,
                           drange, reference, nstar, exponent, "input-gamma-s")
        life = rows.add(f"{bp}-life", "Cycles to failure", U_CYCLES,
                        ROLE_COMPUTED, item.sn_source, loglife)
        damage = rows.add(f"{bp}-damage", "Miner damage", U_ONE,
                          ROLE_COMPUTED, MINE, cycles, loglife, life)
        damages.append(damage)
        stress = rows.add(f"{bp}-governing-stress", "Governing stress", U_STRESS,
                          ROLE_COMPUTED, PROOF, long, design)
        limit = rows.add(f"{bp}-proof-limit", "Yield or proof limit", U_STRESS,
                         ROLE_COMPUTED, PROOF, stress, tension, compression,
                         "input-gamma-s")
        yutil = rows.add(f"{bp}-yield-utilisation", "Yield utilisation", U_ONE,
                         ROLE_COMPUTED, PROOF, stress, limit)
        yields.append(yutil)
        proofs.append(rows.add(
            f"{bp}-proof", "Complete bin reconstruction", U_ONE,
            ROLE_COMPUTED, CHOOSE, normal, cycles, converged, long, elastic,
            fatigue, design, erange, frange, drange, bond, exponent, loglife,
            life, damage, stress, limit, yutil,
        ))
    damage = rows.add(f"{prefix}-damage", "Spectrum damage", U_ONE,
                      ROLE_COMPUTED, MINE, *damages)
    damage_bin = rows.add(f"{prefix}-damage-bin", "Governing damage-bin index",
                          U_ONE, ROLE_COMPUTED, CHOOSE, *damages)
    yutil = rows.add(f"{prefix}-yield-utilisation", "Spectrum yield utilisation",
                     U_ONE, ROLE_COMPUTED, PROOF, *yields)
    yield_bin = rows.add(f"{prefix}-yield-bin", "Governing yield-bin index",
                         U_ONE, ROLE_COMPUTED, CHOOSE, *yields)
    converged = rows.add(f"{prefix}-converged", "Spectrum convergence", U_ONE,
                         ROLE_COMPUTED, SOLVE, *convergence)
    utilisation = rows.add(f"{prefix}-utilisation", "Spectrum utilisation", U_ONE,
                           ROLE_COMPUTED, CHOOSE, damage, yutil)
    passed = rows.add(f"{prefix}-passed", "Spectrum verdict", U_ONE,
                      ROLE_COMPUTED, CHOOSE,
                      converged, damage, yutil, utilisation)
    rows.add(f"ct-010a-{prefix}-result", "CT-010a assessment", U_ONE,
             ROLE_FINAL, CHOOSE, normal, *proofs, damage, damage_bin, yutil,
             yield_bin, converged, utilisation, passed)
    return tuple(rows.rows)


def joint_steps(shape: FamilyShape):
    rows = Steps()
    normal = _inputs(rows, shape)
    all_rows = []
    for item in shape.assessments:
        prefix = f"published-{assessment_prefix(item)}"
        damage = rows.add(f"{prefix}-damage", "Published spectrum damage", U_ONE,
                          ROLE_COMPUTED, MINE, normal)
        yutil = rows.add(f"{prefix}-yield-utilisation",
                         "Published yield utilisation", U_ONE,
                         ROLE_COMPUTED, PROOF, normal)
        converged = rows.add(f"{prefix}-converged", "Published convergence",
                             U_ONE, ROLE_COMPUTED, SOLVE, normal)
        utilisation = rows.add(f"{prefix}-utilisation",
                               "Published spectrum utilisation", U_ONE,
                               ROLE_COMPUTED, CHOOSE, damage, yutil)
        passed = rows.add(f"{prefix}-passed", "Published spectrum verdict",
                          U_ONE, ROLE_COMPUTED, CHOOSE,
                          converged, damage, yutil, utilisation)
        all_rows.extend((damage, yutil, converged, utilisation, passed))
    converged = rows.add("reinforcement-output-converged",
                         "All assessments converged", U_ONE,
                         ROLE_COMPUTED, CHOOSE, normal, *all_rows)
    utilisation = rows.add("reinforcement-output-utilisation",
                           "Governing reinforcement utilisation", U_ONE,
                           ROLE_COMPUTED, CHOOSE, normal, *all_rows)
    passed = rows.add("reinforcement-output-passed", "Overall verdict", U_ONE,
                      ROLE_COMPUTED, CHOOSE,
                      normal, converged, utilisation, *all_rows)
    rows.add("ct-010a-reinforcement-output-result", "CT-010a output", U_ONE,
             ROLE_FINAL, CHOOSE, normal, "input-gamma-c", converged,
             utilisation, passed, *all_rows)
    return tuple(rows.rows)


def invalid_steps(shape: FamilyShape):
    rows = Steps()
    normal = _inputs(rows, shape)
    error_rows = [rows.add(
        f"invalid-error-{index:03d}-{tok(error)}", "Retained validation error",
        U_ONE, ROLE_COMPUTED, CHOOSE, normal,
    ) for index, error in enumerate(shape.invalid.errors)]
    rows.add("ct-010a-invalid-result", "Invalid CT-010a boundary", U_ONE,
             ROLE_FINAL, CHOOSE, normal, *error_rows)
    return tuple(rows.rows)


def _contract(member_id, calculation_id, axes, steps):
    return TraceMemberContract(
        member_id, calculation_id, COVERAGE, METHOD, axes,
        frozenset(TraceSourceContract(
            row.source.kind, row.source.method_id, row.source.edition
        ) for row in steps), FINAL_STATES,
        tuple(row.step_id for row in steps),
        tuple((row.step_id, row.dependencies) for row in steps),
        tuple(TraceStepMetadataContract(
            row.step_id, row.role, row.source
        ) for row in steps),
    )


def expected_registry(shape: FamilyShape):
    members = []
    if shape.branch == "invalid":
        steps = invalid_steps(shape)
        members.append(_contract(
            shape.invalid.member_id, shape.invalid.calculation_id,
            shape.invalid.axes, steps,
        ))
    elif shape.branch == "success":
        for item in shape.assessments:
            steps = assessment_steps(shape, item)
            members.append(_contract(
                item.member_id, item.calculation_id, item.axes, steps,
            ))
        steps = joint_steps(shape)
        members.append(_contract(
            shape.joint.member_id, shape.joint.calculation_id,
            shape.joint.axes, steps,
        ))
    else:
        raise ValueError("unknown CT-010a branch")
    return TraceRegistryContract(
        REGISTRY, (TraceFamilyContract(FAMILY, tuple(members)),)
    )
