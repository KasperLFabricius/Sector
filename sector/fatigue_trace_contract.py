"""Exact CT-010a reinforcement-fatigue trace contract.

The family owns the retained reinforcement assessment and invalid-input
surfaces. Concrete-fatigue values remain named CT-010b siblings: their
inventory positions and retained types are fenced here, but their values are
not represented as members until PR-08D.3b.
"""

from __future__ import annotations

from dataclasses import dataclass

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
from .section_trace_blocks import MaterialBlock, SectionTraceBlocks
from .trace_registry import (
    TraceFamilyContract,
    TraceMemberContract,
    TraceRegistryContract,
    TraceSourceContract,
    TraceStepMetadataContract,
)


COVERAGE_ID = "ct-010"
FAMILY_ID = "ct-010-fatigue"
REGISTRY_ID = "sector-ct-010-fatigue-v1"
METHOD_ID = "sector-retained-fatigue-replay"
OUTPUT_MEMBER_ID = "reinforcement-output"
INVALID_MEMBER_ID = "invalid"

EDITION_2005 = "DS/EN 1992-1-1:2005"
EDITION_2005_DKNA = "DS/EN 1992-1-1:2005 + DK NA:2024"
EDITION_2023 = "DS/EN 1992-1-1:2023"
EDITIONS = (EDITION_2005, EDITION_2005_DKNA, EDITION_2023)

STATUS_CODES = {"PASS": 1.0, "FAIL": 0.0}

# Retained application payload order. The valid and invalid branches are
# deliberately asymmetric: only INVALID_KEYS contains ``valid``.
VALID_KEYS = (
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
    "t0_days", "elements", "spectra", "governing_spectrum",
    "utilisation",
)
CHECK_KEYS = ("reinforcement", "concrete")
FACTOR_KEYS = ("gamma_c", "gamma_s", "gamma_ff")
BASIS_KEYS = ("method", "notes")

CONCRETE_EXCLUDED_KEYS = ("concrete_method", "concrete_parameters")
CONCRETE_EXCLUDED_RESULT_FIELDS = (
    "concrete", "concrete_search", "fcd_fat_mpa",
    "governing_concrete_fibre", "concrete_method",
)
CONCRETE_EXCLUDED_BIN_FIELDS = (
    "concrete_compression_long_mpa",
    "concrete_compression_total_mpa",
    "concrete_compression_design_total_mpa",
)
RAW_SOLVER_FIELDS = ("elastic_result", "design_elastic_result")

PROPERTY_FIELDS = (
    "element_id", "kind", "detail_id", "diameter_mm", "n_star", "k1",
    "k2", "delta_sigma_rsk_mpa", "fytk_mpa", "fyck_mpa",
    "bond_ratio_xi", "bond_equivalent_diameter_mm",
)
BIN_RESULT_FIELDS = (
    "bin_name", "cycles", "converged", "stress_long_mpa",
    "stress_total_mpa", "stress_total_design_mpa",
    "stress_total_elastic_mpa", "stress_range_mpa",
    "stress_range_elastic_mpa", "bond_adjustment", "bond_method",
    "design_stress_range_mpa", "delta_sigma_rsk_mpa",
    "delta_sigma_rd_mpa", "sn_exponent", "cycles_to_failure",
    "log10_cycles_to_failure", "damage", "governing_stress_mpa",
    "yield_limit_mpa", "yield_utilisation",
)
RESULT_FIELDS = (
    "element_id", "kind", "detail_id", "diameter_mm", "bins", "damage",
    "damage_utilisation", "governing_damage_bin", "yield_utilisation",
    "governing_yield_bin", "utilisation", "converged", "passed",
)
BIN_STATE_FIELDS = (
    "name", "description", "cycles", "converged",
    "bar_stress_long_mpa", "bar_stress_total_mpa",
    "concrete_compression_long_mpa", "concrete_compression_total_mpa",
    "elastic_result", "bar_stress_fatigue_total_mpa", "bond_method",
    "design_action_factor", "design_elastic_result",
    "bar_stress_design_total_mpa",
    "bar_stress_fatigue_design_total_mpa",
    "concrete_compression_design_total_mpa",
)
SPECTRUM_RESULT_FIELDS = (
    "spectrum_name", "bins", "reinforcement", "concrete",
    "concrete_search", "fcd_fat_mpa", "governing_reinforcement_id",
    "governing_concrete_fibre", "utilisation", "converged", "passed",
    "concrete_method",
)

DOC_2005 = "DS/EN 1992-1-1:2005 + A1:2014"
DOC_DKNA = "DS/EN 1992-1-1:2005 + A1:2014 + DK NA:2024"
DOC_2023 = "DS/EN 1992-1-1:2023"

INPUT_SOURCE = TraceSource(SOURCE_INPUT, "sector-section-input")
ADAPTER_SOURCE = TraceSource(SOURCE_PROJECT, "sector-fatigue-adapter")
ENGINE_SOURCE = TraceSource(SOURCE_PROJECT, "sector-ct-010-fatigue-engine")
VERDICT_SOURCE = TraceSource(SOURCE_PROJECT, "sector-fatigue-verdict")

SN_SOURCES = {
    EDITION_2005: TraceSource(
        SOURCE_STANDARD, "en-1992-1-1-2005-steel-sn-curve", EDITION_2005,
        SourceCitation(DOC_2005, "6.8.4",
                       "Tables 6.3N/6.4N two-slope S-N"),
    ),
    EDITION_2005_DKNA: TraceSource(
        SOURCE_STANDARD, "en-1992-1-1-2005-dkna-steel-sn-curve",
        EDITION_2005_DKNA,
        SourceCitation(DOC_DKNA, "6.8.4",
                       "Tables 6.3N/6.4N with DK NA input factors"),
    ),
    EDITION_2023: TraceSource(
        SOURCE_STANDARD, "en-1992-1-1-2023-steel-sn-curve", EDITION_2023,
        SourceCitation(DOC_2023, "E.5.2",
                       "Tables E.1/E.2 two-slope S-N"),
    ),
}
MINER_SOURCES = {
    EDITION_2005: TraceSource(
        SOURCE_STANDARD, "en-1992-1-1-2005-palmgren-miner", EDITION_2005,
        SourceCitation(DOC_2005, "6.8.4(2)", "Palmgren-Miner damage sum"),
    ),
    EDITION_2005_DKNA: TraceSource(
        SOURCE_STANDARD, "en-1992-1-1-2005-dkna-palmgren-miner",
        EDITION_2005_DKNA,
        SourceCitation(DOC_DKNA, "6.8.4(2)",
                       "Palmgren-Miner damage sum with DK NA inputs"),
    ),
    EDITION_2023: TraceSource(
        SOURCE_STANDARD, "en-1992-1-1-2023-palmgren-miner", EDITION_2023,
        SourceCitation(DOC_2023, "E.5.2", "Palmgren-Miner damage sum"),
    ),
}
BOND_SOURCES = {
    EDITION_2005: TraceSource(
        SOURCE_STANDARD, "en-1992-1-1-2005-mixed-bond-correction",
        EDITION_2005,
        SourceCitation(DOC_2005, "6.8.2(2)",
                       "reinforcing-steel bond correction eta"),
    ),
    EDITION_2005_DKNA: TraceSource(
        SOURCE_STANDARD, "en-1992-1-1-2005-dkna-mixed-bond-correction",
        EDITION_2005_DKNA,
        SourceCitation(DOC_DKNA, "6.8.2(2)",
                       "reinforcing-steel bond correction eta"),
    ),
    EDITION_2023: TraceSource(
        SOURCE_STANDARD, "en-1992-1-1-2023-mixed-bond-correction",
        EDITION_2023,
        SourceCitation(DOC_2023, "10.3(2)", "equivalent tendon area"),
    ),
}

ONE = TraceUnit("1", "scalar")
M = TraceUnit("m", "length")
M2 = TraceUnit("m2", "area")
MM = TraceUnit("mm", "length")
MPA = TraceUnit("MPa", "stress")
KN = TraceUnit("kN", "force")
KNM = TraceUnit("kNm", "moment")

BIN_ACTIONS = (
    ("n-long", "Entered long-term axial action N_Ed", KN),
    ("mx-long", "Entered long-term Mx_Ed", KNM),
    ("my-long", "Entered long-term My_Ed", KNM),
    ("n-short", "Entered cyclic axial increment N_Ed", KN),
    ("mx-short", "Entered cyclic Mx_Ed increment", KNM),
    ("my-short", "Entered cyclic My_Ed increment", KNM),
)


@dataclass(frozen=True, slots=True)
class ElementShape:
    spectrum_index: int
    spectrum_name: str
    element_index: int
    kind: str
    element_id: str
    material_id: str
    detail_id: str
    bin_names: tuple[str, ...]
    bin_descriptions: tuple[str, ...]
    blocks: SectionTraceBlocks
    has_fyck: bool
    has_bond_xi: bool
    has_bond_diameter: bool
    mixed: bool
    edition: str
    calculation_id: str
    axes: tuple[TraceAxis, ...]


@dataclass(frozen=True, slots=True)
class SpectrumShape:
    name: str
    element_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OutputShape:
    joint: bool
    spectra: tuple[SpectrumShape, ...]
    calculation_id: str
    axes: tuple[TraceAxis, ...]


@dataclass(frozen=True, slots=True)
class InvalidShape:
    errors: tuple[str, ...]
    calculation_id: str
    axes: tuple[TraceAxis, ...]


@dataclass(frozen=True, slots=True)
class FamilyShape:
    elements: tuple[ElementShape, ...]
    output: OutputShape | None
    invalid: InvalidShape | None


@dataclass(frozen=True, slots=True)
class StepSpec:
    step_id: str
    title: str
    unit: TraceUnit
    quantity_role: str
    source: TraceSource
    dependencies: tuple[str, ...]


class _Plan:
    def __init__(self) -> None:
        self.specs: list[StepSpec] = []
        self.ids: set[str] = set()

    def add(self, step_id, title, unit, role, source, *dependencies) -> str:
        if step_id in self.ids:
            raise ValueError(f"duplicate CT-010 step {step_id}")
        self.ids.add(step_id)
        self.specs.append(StepSpec(
            step_id, title, unit, role, source, tuple(dependencies)))
        return step_id


def bin_prefix(index: int, name: str) -> str:
    return f"bin-{index:02d}-{trace_identity_token(name)}"


def description_step_id(index: int, name: str, description: str) -> str:
    return (f"{bin_prefix(index, name)}-description-"
            f"{trace_identity_token(description)}")


def material_prefix(material: MaterialBlock) -> str:
    return (f"material-{material.kind}-"
            f"{trace_identity_token(material.element_id)}-"
            f"{trace_identity_token(material.material_id)}")


def material_step_id(material: MaterialBlock, field: str) -> str:
    return f"{material_prefix(material)}-{trace_identity_token(field)}"


def material_unit(field: str) -> TraceUnit:
    return MPA if field in {"fck", "fytk", "fyck", "futk", "Es"} else ONE


def element_member_id(shape: ElementShape) -> str:
    return (
        f"reinforcement-s{shape.spectrum_index:02d}-"
        f"{trace_identity_token(shape.spectrum_name)}-"
        f"e{shape.element_index:02d}-"
        f"{trace_identity_token(shape.element_id)}-"
        f"{trace_identity_token(shape.material_id)}-"
        f"{trace_identity_token(shape.detail_id)}"
    )


def spectrum_prefix(index: int, name: str) -> str:
    return f"s{index:02d}-{trace_identity_token(name)}"


def output_element_prefix(si: int, spectrum: str, ei: int,
                          element_id: str) -> str:
    return (f"{spectrum_prefix(si, spectrum)}-e{ei:02d}-"
            f"{trace_identity_token(element_id)}")


def invalid_error_id(index: int, message: str) -> str:
    return f"invalid-error-{index:02d}-{trace_identity_token(message)}"


def _geometry(plan: _Plan, shape: ElementShape) -> str:
    leaves: list[str] = []
    for ri, ring in enumerate(shape.blocks.geometry.rings):
        for pi, _point in enumerate(ring):
            prefix = f"geometry-ring-{ri:03d}-point-{pi:04d}"
            leaves.extend((
                plan.add(f"{prefix}-x", "Concrete vertex x", M,
                         ROLE_USER_INPUT, INPUT_SOURCE),
                plan.add(f"{prefix}-y", "Concrete vertex y", M,
                         ROLE_USER_INPUT, INPUT_SOURCE),
            ))
    for kind, elements in (
        ("bar", shape.blocks.geometry.bars),
        ("tendon", shape.blocks.geometry.tendons),
    ):
        for index, _element in enumerate(elements):
            prefix = f"geometry-{kind}-{index:04d}"
            leaves.extend((
                plan.add(f"{prefix}-x", f"{kind.title()} x", M,
                         ROLE_USER_INPUT, INPUT_SOURCE),
                plan.add(f"{prefix}-y", f"{kind.title()} y", M,
                         ROLE_USER_INPUT, INPUT_SOURCE),
                plan.add(f"{prefix}-area", f"{kind.title()} area", M2,
                         ROLE_USER_INPUT, INPUT_SOURCE),
            ))
    return plan.add("geometry-vector", "Immutable section geometry", ONE,
                    ROLE_COMPUTED, ADAPTER_SOURCE, *leaves)


def _materials(plan: _Plan, shape: ElementShape) -> str:
    leaves: list[str] = []
    for material in (
        shape.blocks.concrete,
        *shape.blocks.bars,
        *shape.blocks.tendons,
    ):
        for field, _value in material.values:
            leaves.append(plan.add(
                material_step_id(material, field),
                f"{material.kind.title()} law {field}",
                material_unit(field), ROLE_METHOD_VALUE,
                material.provenance.source))
    return plan.add("material-vector", "Immutable material assignments", ONE,
                    ROLE_COMPUTED, ADAPTER_SOURCE, *leaves)


def element_steps(shape: ElementShape) -> tuple[StepSpec, ...]:
    if len(shape.bin_names) != len(shape.bin_descriptions):
        raise ValueError("fatigue bin identities must align")
    plan = _Plan()
    scalars = [
        plan.add("input-check-steel", "Reinforcement check enabled", ONE,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        plan.add("input-edition", "Selected fatigue edition", ONE,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        plan.add("input-gamma-s", "Entered gamma_s", ONE,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        plan.add("input-gamma-ff", "Entered gamma_Ff", ONE,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        plan.add("input-nl", "Entered long-term modular ratio", ONE,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        plan.add("input-ns", "Entered short-term modular ratio", ONE,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        plan.add("input-diameter", "Entered element diameter", MM,
                 ROLE_USER_INPUT, INPUT_SOURCE),
    ]
    for index, (name, description) in enumerate(
            zip(shape.bin_names, shape.bin_descriptions)):
        prefix = bin_prefix(index, name)
        scalars.append(plan.add(
            description_step_id(index, name, description),
            "Retained fatigue-bin description", ONE,
            ROLE_USER_INPUT, INPUT_SOURCE))
        scalars.append(plan.add(
            f"{prefix}-cycles", "Entered applied cycles", ONE,
            ROLE_USER_INPUT, INPUT_SOURCE))
        for suffix, title, unit in BIN_ACTIONS:
            scalars.append(plan.add(
                f"{prefix}-{suffix}", title, unit,
                ROLE_USER_INPUT, INPUT_SOURCE))

    details = [
        plan.add("detail-n-star", "Resolved S-N knee cycles N*", ONE,
                 ROLE_METHOD_VALUE, ADAPTER_SOURCE),
        plan.add("detail-k1", "Resolved S-N first slope", ONE,
                 ROLE_METHOD_VALUE, ADAPTER_SOURCE),
        plan.add("detail-k2", "Resolved S-N second slope", ONE,
                 ROLE_METHOD_VALUE, ADAPTER_SOURCE),
        plan.add("detail-delta-sigma-rsk",
                 "Resolved characteristic stress range", MPA,
                 ROLE_METHOD_VALUE, ADAPTER_SOURCE),
        plan.add("detail-fytk", "Resolved characteristic proof stress", MPA,
                 ROLE_METHOD_VALUE, ADAPTER_SOURCE),
    ]
    if shape.has_fyck:
        details.append(plan.add(
            "detail-fyck", "Resolved compression proof stress", MPA,
            ROLE_METHOD_VALUE, ADAPTER_SOURCE))
    if shape.has_bond_xi:
        details.append(plan.add(
            "detail-bond-xi", "Resolved bond ratio xi", ONE,
            ROLE_METHOD_VALUE, ADAPTER_SOURCE))
    if shape.has_bond_diameter:
        details.append(plan.add(
            "detail-bond-eq-diameter", "Resolved bond diameter", MM,
            ROLE_METHOD_VALUE, ADAPTER_SOURCE))
    details.append(plan.add(
        "element-es", "Assigned element modulus", MPA,
        ROLE_METHOD_VALUE, ADAPTER_SOURCE))

    normalised = plan.add(
        "normalised-fatigue-inputs", "Complete fatigue input identity", ONE,
        ROLE_COMPUTED, ADAPTER_SOURCE, *scalars, *details,
        _geometry(plan, shape), _materials(plan, shape))

    sn_source = SN_SOURCES[shape.edition]
    miner_source = MINER_SOURCES[shape.edition]
    bond_source = BOND_SOURCES[shape.edition] if shape.mixed else ADAPTER_SOURCE
    damages: list[str] = []
    yields: list[str] = []
    convergence: list[str] = []
    bond_evidence: list[str] = []
    for index, name in enumerate(shape.bin_names):
        prefix = bin_prefix(index, name)
        convergence.append(plan.add(
            f"{prefix}-upstream-converged", "Engine convergence state", ONE,
            ROLE_METHOD_VALUE, ENGINE_SOURCE))
        long = plan.add(
            f"{prefix}-upstream-stress-long", "Engine long-term stress", MPA,
            ROLE_METHOD_VALUE, ENGINE_SOURCE)
        total = plan.add(
            f"{prefix}-upstream-stress-total", "Engine fatigue total stress",
            MPA, ROLE_METHOD_VALUE, ENGINE_SOURCE)
        elastic = plan.add(
            f"{prefix}-upstream-stress-total-elastic",
            "Engine uncorrected total stress", MPA,
            ROLE_METHOD_VALUE, ENGINE_SOURCE)
        design = plan.add(
            f"{prefix}-upstream-stress-total-design",
            "Engine design total stress", MPA,
            ROLE_METHOD_VALUE, ENGINE_SOURCE)
        stress_range = plan.add(
            f"{prefix}-stress-range", "Characteristic stress range", MPA,
            ROLE_COMPUTED, ADAPTER_SOURCE, normalised, long, total)
        bond_evidence.append(plan.add(
            f"{prefix}-bond-adjustment", "Bond adjustment factor", ONE,
            ROLE_COMPUTED, bond_source, stress_range, long, elastic))
        design_range = plan.add(
            f"{prefix}-design-stress-range", "Design stress range", MPA,
            ROLE_COMPUTED, ADAPTER_SOURCE, long, design, "input-gamma-ff")
        exponent = plan.add(
            f"{prefix}-sn-exponent", "Governing S-N exponent", ONE,
            ROLE_COMPUTED, sn_source, design_range, "detail-k1", "detail-k2",
            "detail-delta-sigma-rsk", "input-gamma-s")
        life = plan.add(
            f"{prefix}-log10-cycles-to-failure", "S-N life log10 N", ONE,
            ROLE_COMPUTED, sn_source, exponent, design_range, "detail-n-star",
            "detail-delta-sigma-rsk", "input-gamma-s")
        damages.append(plan.add(
            f"{prefix}-damage", "Palmgren-Miner bin damage", ONE,
            ROLE_COMPUTED, miner_source, f"{prefix}-cycles", life))
        limit_dependencies = ["detail-fytk"]
        if shape.has_fyck:
            limit_dependencies.append("detail-fyck")
        limit = plan.add(
            f"{prefix}-yield-limit", "Sign-dependent proof limit", MPA,
            ROLE_COMPUTED, ADAPTER_SOURCE, *limit_dependencies,
            "input-gamma-s", long, design)
        yields.append(plan.add(
            f"{prefix}-yield-utilisation", "Bin yield utilisation", ONE,
            ROLE_COMPUTED, VERDICT_SOURCE, limit, long, design))

    damage = plan.add("damage-total", "Element Miner damage", ONE,
                      ROLE_COMPUTED, miner_source, *damages)
    damage_bin = plan.add(
        "governing-damage-bin", "Governing damage-bin index", ONE,
        ROLE_COMPUTED, VERDICT_SOURCE, *damages)
    yield_util = plan.add("yield-utilisation", "Element yield utilisation",
                          ONE, ROLE_COMPUTED, VERDICT_SOURCE, *yields)
    yield_bin = plan.add(
        "governing-yield-bin", "Governing yield-bin index", ONE,
        ROLE_COMPUTED, VERDICT_SOURCE, *yields)
    utilisation = plan.add(
        "utilisation", "Element fatigue utilisation", ONE,
        ROLE_COMPUTED, VERDICT_SOURCE, damage, yield_util)
    converged = plan.add(
        "converged", "Element convergence state", ONE,
        ROLE_COMPUTED, VERDICT_SOURCE, *convergence)
    passed = plan.add(
        "passed", "Element PASS or FAIL", ONE,
        ROLE_COMPUTED, VERDICT_SOURCE, converged, damage, yield_util)
    plan.add(
        "ct-010-element-result", "CT-010 reinforcement element status", ONE,
        ROLE_FINAL, VERDICT_SOURCE, normalised, *bond_evidence,
        damage_bin, yield_bin, utilisation, passed)
    return tuple(plan.specs)


def output_steps(shape: OutputShape) -> tuple[StepSpec, ...]:
    plan = _Plan()
    steel = plan.add("input-check-steel", "Reinforcement check enabled", ONE,
                     ROLE_USER_INPUT, INPUT_SOURCE)
    concrete = plan.add("input-check-concrete", "Concrete check enabled", ONE,
                        ROLE_USER_INPUT, INPUT_SOURCE)
    converged_inputs: list[str] = []
    passed_inputs: list[str] = []
    governing: list[str] = []
    spectrum_utils: list[str] = []
    for si, spectrum in enumerate(shape.spectra):
        utils: list[str] = []
        for ei, element_id in enumerate(spectrum.element_ids):
            prefix = output_element_prefix(si, spectrum.name, ei, element_id)
            utils.append(plan.add(
                f"{prefix}-utilisation", "Engine element utilisation", ONE,
                ROLE_METHOD_VALUE, ENGINE_SOURCE))
            converged_inputs.append(plan.add(
                f"{prefix}-converged", "Engine element convergence", ONE,
                ROLE_METHOD_VALUE, ENGINE_SOURCE))
            passed_inputs.append(plan.add(
                f"{prefix}-passed", "Engine element status", ONE,
                ROLE_METHOD_VALUE, ENGINE_SOURCE))
        prefix = spectrum_prefix(si, spectrum.name)
        governing.append(plan.add(
            f"{prefix}-governing-element", "Governing element index", ONE,
            ROLE_COMPUTED, VERDICT_SOURCE, *utils))
        if not shape.joint:
            spectrum_utils.append(plan.add(
                f"{prefix}-utilisation", "Spectrum utilisation", ONE,
                ROLE_COMPUTED, VERDICT_SOURCE, *utils))
    converged = plan.add(
        "reinforcement-converged", "Reinforcement convergence", ONE,
        ROLE_COMPUTED, VERDICT_SOURCE, steel, concrete, *converged_inputs)
    passed = plan.add(
        "reinforcement-passed", "Reinforcement PASS or FAIL", ONE,
        ROLE_COMPUTED, VERDICT_SOURCE, converged, *passed_inputs)
    tail: list[str] = []
    if not shape.joint:
        tail.append(plan.add(
            "governing-spectrum", "Governing spectrum index", ONE,
            ROLE_COMPUTED, VERDICT_SOURCE, *spectrum_utils))
        tail.append(plan.add(
            "family-utilisation", "Family fatigue utilisation", ONE,
            ROLE_COMPUTED, VERDICT_SOURCE, *spectrum_utils,
            "governing-spectrum"))
    plan.add(
        "ct-010-reinforcement-output-result",
        "CT-010 reinforcement family status", ONE,
        ROLE_FINAL, VERDICT_SOURCE, *governing, *tail, passed)
    return tuple(plan.specs)


def invalid_steps(shape: InvalidShape) -> tuple[StepSpec, ...]:
    plan = _Plan()
    inputs = [
        plan.add("input-fatigue-on", "Fatigue analysis enabled", ONE,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        plan.add("input-check-steel", "Reinforcement check enabled", ONE,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        plan.add("input-check-concrete", "Concrete check enabled", ONE,
                 ROLE_USER_INPUT, INPUT_SOURCE),
    ]
    errors = [
        plan.add(invalid_error_id(index, message),
                 "Retained fatigue preflight error", ONE,
                 ROLE_COMPUTED, ADAPTER_SOURCE, *inputs)
        for index, message in enumerate(shape.errors)
    ]
    plan.add("ct-010-invalid-result", "CT-010 invalid fatigue state", ONE,
             ROLE_FINAL, VERDICT_SOURCE, *inputs, *errors)
    return tuple(plan.specs)


def _member(member_id, calculation_id, axes, specs, states):
    return TraceMemberContract(
        member_id=member_id,
        calculation_id=calculation_id,
        coverage_id=COVERAGE_ID,
        method_id=METHOD_ID,
        axes=axes,
        sources=frozenset(
            TraceSourceContract(spec.source.kind, spec.source.method_id,
                                spec.source.edition)
            for spec in specs
        ),
        result_states=frozenset(states),
        step_ids=tuple(spec.step_id for spec in specs),
        step_dependencies=tuple(
            (spec.step_id, spec.dependencies) for spec in specs),
        step_metadata=tuple(
            TraceStepMetadataContract(
                spec.step_id, spec.quantity_role, spec.source)
            for spec in specs
        ),
    )


def expected_registry(shape: FamilyShape) -> TraceRegistryContract:
    members: list[TraceMemberContract] = []
    if shape.invalid is not None:
        specs = invalid_steps(shape.invalid)
        members.append(_member(
            INVALID_MEMBER_ID, shape.invalid.calculation_id,
            shape.invalid.axes, specs, {RESULT_FAILED}))
    for element in shape.elements:
        specs = element_steps(element)
        members.append(_member(
            element_member_id(element), element.calculation_id,
            element.axes, specs, {RESULT_FINITE}))
    if shape.output is not None:
        specs = output_steps(shape.output)
        members.append(_member(
            OUTPUT_MEMBER_ID, shape.output.calculation_id,
            shape.output.axes, specs, {RESULT_FINITE}))
    if not members:
        raise ValueError("CT-010 registry requires an applicable member")
    return TraceRegistryContract(
        REGISTRY_ID, (TraceFamilyContract(FAMILY_ID, tuple(members)),))
