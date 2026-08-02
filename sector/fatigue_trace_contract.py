"""Declarative CT-010a reinforcement-fatigue trace contract."""

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
from .section_trace_blocks import GeometryBlock, MaterialBlock
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
INVALID_MEMBER_ID = "invalid"
OUTPUT_MEMBER_ID = "reinforcement-output"

EDITION_2005 = "DS/EN 1992-1-1:2005"
EDITION_2005_DKNA = "DS/EN 1992-1-1:2005 + DK NA:2024"
EDITION_2023 = "DS/EN 1992-1-1:2023"
EDITIONS = (EDITION_2005, EDITION_2005_DKNA, EDITION_2023)
STATUS_CODES = {"PASS": 1.0, "FAIL": 0.0}

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
    "t0_days", "elements", "spectra", "governing_spectrum", "utilisation",
)
CHECK_KEYS = ("reinforcement", "concrete")
FACTOR_KEYS = ("gamma_c", "gamma_s", "gamma_ff")
BASIS_KEYS = ("method", "notes")
CONCRETE_EXCLUDED_KEYS = ("concrete_method", "concrete_parameters")
CONCRETE_EXCLUDED_BIN_FIELDS = (
    "concrete_compression_long_mpa",
    "concrete_compression_total_mpa",
    "concrete_compression_design_total_mpa",
)
CONCRETE_EXCLUDED_RESULT_FIELDS = (
    "concrete", "concrete_search", "fcd_fat_mpa",
    "governing_concrete_fibre", "concrete_method",
)

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
ELASTIC_RESULT_FIELDS = (
    "eps0", "kx", "ky", "bar_stress", "max_concrete_compression",
    "max_concrete_point", "max_concrete_xy", "na_x_intercept",
    "na_y_intercept", "converged", "iterations", "max_concrete_tension",
    "max_concrete_tension_point", "max_concrete_tension_xy",
)
COMBINED_ELASTIC_RESULT_FIELDS = (
    "long", "short_term", "bar_stress_total", "bar_stress_long",
    "bar_stress_dif", "bar_stress_rst1", "max_concrete_compression",
    "max_concrete_point", "na_x_intercept", "na_y_intercept", "converged",
)

INPUT_SOURCE = TraceSource(SOURCE_INPUT, "sector-section-input")
ADAPTER_SOURCE = TraceSource(SOURCE_PROJECT, "sector-fatigue-adapter")
ENGINE_SOURCE = TraceSource(SOURCE_PROJECT, "sector-ct-010-fatigue-engine")
VERDICT_SOURCE = TraceSource(SOURCE_PROJECT, "sector-fatigue-verdict")


def _standard(method, edition, document, clause, locator):
    return TraceSource(
        SOURCE_STANDARD, method, edition,
        SourceCitation(document, clause, locator))


DOC_2005 = "DS/EN 1992-1-1:2005 + A1:2014"
DOC_DKNA = "DS/EN 1992-1-1:2005 + A1:2014 + DK NA:2024"
DOC_2023 = "DS/EN 1992-1-1:2023"
SN_SOURCES = {
    EDITION_2005: _standard(
        "en-1992-1-1-2005-steel-sn-curve", EDITION_2005, DOC_2005,
        "6.8.4", "Tables 6.3N/6.4N two-slope S-N"),
    EDITION_2005_DKNA: _standard(
        "en-1992-1-1-2005-dkna-steel-sn-curve", EDITION_2005_DKNA,
        DOC_DKNA, "6.8.4", "Tables 6.3N/6.4N with DK NA factors"),
    EDITION_2023: _standard(
        "en-1992-1-1-2023-steel-sn-curve", EDITION_2023, DOC_2023,
        "E.5.2", "Tables E.1/E.2 two-slope S-N"),
}
MINER_SOURCES = {
    EDITION_2005: _standard(
        "en-1992-1-1-2005-palmgren-miner", EDITION_2005, DOC_2005,
        "6.8.4(2)", "Palmgren-Miner damage sum"),
    EDITION_2005_DKNA: _standard(
        "en-1992-1-1-2005-dkna-palmgren-miner", EDITION_2005_DKNA,
        DOC_DKNA, "6.8.4(2)", "Palmgren-Miner sum with DK NA inputs"),
    EDITION_2023: _standard(
        "en-1992-1-1-2023-palmgren-miner", EDITION_2023, DOC_2023,
        "E.5.2", "Palmgren-Miner damage sum"),
}
BOND_SOURCES = {
    EDITION_2005: _standard(
        "en-1992-1-1-2005-mixed-bond-correction", EDITION_2005, DOC_2005,
        "6.8.2(2)", "reinforcing-steel bond correction eta"),
    EDITION_2005_DKNA: _standard(
        "en-1992-1-1-2005-dkna-mixed-bond-correction",
        EDITION_2005_DKNA, DOC_DKNA, "6.8.2(2)",
        "reinforcing-steel bond correction eta"),
    EDITION_2023: _standard(
        "en-1992-1-1-2023-mixed-bond-correction", EDITION_2023, DOC_2023,
        "10.3(2)", "equivalent tendon area"),
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
class InputBlocks:
    geometry: GeometryBlock
    concrete: MaterialBlock | None
    bars: tuple[MaterialBlock, ...]
    tendons: tuple[MaterialBlock, ...]


@dataclass(frozen=True, slots=True)
class ElementShape:
    spectrum_index: int
    spectrum_name: str
    element_index: int
    element_id: str
    material_id: str
    detail_id: str
    bin_names: tuple[str, ...]
    bin_descriptions: tuple[str, ...]
    blocks: InputBlocks
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
    role: str
    source: TraceSource
    dependencies: tuple[str, ...]


class _Plan:
    def __init__(self):
        self.specs = []
        self.ids = set()

    def add(self, step_id, title, unit, role, source, *dependencies):
        if step_id in self.ids:
            raise ValueError(f"duplicate CT-010 step {step_id}")
        self.ids.add(step_id)
        self.specs.append(StepSpec(
            step_id, title, unit, role, source, tuple(dependencies)))
        return step_id


def bin_prefix(index, name):
    return f"bin-{index:02d}-{trace_identity_token(name)}"


def description_step_id(index, name, description):
    return (f"{bin_prefix(index, name)}-description-"
            f"{trace_identity_token(description)}")


def material_step_id(material, field):
    return (
        f"material-{material.kind}-"
        f"{trace_identity_token(material.element_id)}-"
        f"{trace_identity_token(material.material_id)}-"
        f"{trace_identity_token(field)}")


def material_unit(field):
    return MPA if field in {"fck", "fytk", "fyck", "futk", "Es"} else ONE


def element_member_id(shape):
    return (
        f"reinforcement-s{shape.spectrum_index:02d}-"
        f"{trace_identity_token(shape.spectrum_name)}-"
        f"e{shape.element_index:02d}-"
        f"{trace_identity_token(shape.element_id)}-"
        f"{trace_identity_token(shape.material_id)}-"
        f"{trace_identity_token(shape.detail_id)}")


def spectrum_prefix(index, name):
    return f"s{index:02d}-{trace_identity_token(name)}"


def output_element_prefix(si, spectrum, ei, element_id):
    return (f"{spectrum_prefix(si, spectrum)}-e{ei:02d}-"
            f"{trace_identity_token(element_id)}")


def invalid_error_id(index, message):
    return f"invalid-error-{index:02d}-{trace_identity_token(message)}"


def _geometry_steps(plan, shape):
    leaves = []
    for ring_index, ring in enumerate(shape.blocks.geometry.rings):
        for point_index, _point in enumerate(ring):
            prefix = (
                f"geometry-ring-{ring_index:03d}-point-{point_index:04d}")
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
            for suffix, title, unit in (
                ("x", f"{kind.title()} x", M),
                ("y", f"{kind.title()} y", M),
                ("area", f"{kind.title()} area", M2),
            ):
                leaves.append(plan.add(
                    f"{prefix}-{suffix}", title, unit,
                    ROLE_USER_INPUT, INPUT_SOURCE))
    return plan.add("geometry-vector", "Immutable section geometry", ONE,
                    ROLE_COMPUTED, ADAPTER_SOURCE, *leaves)


def _material_steps(plan, shape):
    leaves = [plan.add(
        "input-concrete-material-present", "Concrete material law present",
        ONE, ROLE_USER_INPUT, INPUT_SOURCE)]
    materials = (
        (() if shape.blocks.concrete is None else (shape.blocks.concrete,))
        + shape.blocks.bars + shape.blocks.tendons)
    for material in materials:
        for field, _value in material.values:
            leaves.append(plan.add(
                material_step_id(material, field),
                f"{material.kind.title()} law {field}", material_unit(field),
                ROLE_METHOD_VALUE, material.provenance.source))
    return plan.add("material-vector", "Immutable material assignments", ONE,
                    ROLE_COMPUTED, ADAPTER_SOURCE, *leaves)


def element_steps(shape):
    if len(shape.bin_names) != len(shape.bin_descriptions):
        raise ValueError("fatigue bin identities must align")
    plan = _Plan()
    normal_inputs = [
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
        normal_inputs.append(plan.add(
            description_step_id(index, name, description),
            "Retained fatigue-bin description", ONE,
            ROLE_USER_INPUT, INPUT_SOURCE))
        normal_inputs.append(plan.add(
            f"{prefix}-cycles", "Entered applied cycles", ONE,
            ROLE_USER_INPUT, INPUT_SOURCE))
        for suffix, title, unit in BIN_ACTIONS:
            normal_inputs.append(plan.add(
                f"{prefix}-{suffix}", title, unit,
                ROLE_USER_INPUT, INPUT_SOURCE))
    method_inputs = [
        plan.add("detail-n-star", "Resolved S-N knee cycles N*", ONE,
                 ROLE_METHOD_VALUE, ADAPTER_SOURCE),
        plan.add("detail-k1", "Resolved S-N first slope", ONE,
                 ROLE_METHOD_VALUE, ADAPTER_SOURCE),
        plan.add("detail-k2", "Resolved S-N second slope", ONE,
                 ROLE_METHOD_VALUE, ADAPTER_SOURCE),
        plan.add("detail-delta-sigma-rsk", "Characteristic stress range", MPA,
                 ROLE_METHOD_VALUE, ADAPTER_SOURCE),
        plan.add("detail-fytk", "Characteristic proof stress", MPA,
                 ROLE_METHOD_VALUE, ADAPTER_SOURCE),
    ]
    if shape.has_fyck:
        method_inputs.append(plan.add(
            "detail-fyck", "Compression proof stress", MPA,
            ROLE_METHOD_VALUE, ADAPTER_SOURCE))
    if shape.has_bond_xi:
        method_inputs.append(plan.add(
            "detail-bond-xi", "Resolved bond ratio xi", ONE,
            ROLE_METHOD_VALUE, ADAPTER_SOURCE))
    if shape.has_bond_diameter:
        method_inputs.append(plan.add(
            "detail-bond-eq-diameter", "Resolved bond diameter", MM,
            ROLE_METHOD_VALUE, ADAPTER_SOURCE))
    method_inputs.append(plan.add(
        "element-es", "Assigned element modulus", MPA,
        ROLE_METHOD_VALUE, ADAPTER_SOURCE))
    normalised = plan.add(
        "normalised-fatigue-inputs", "Complete fatigue input identity", ONE,
        ROLE_COMPUTED, ADAPTER_SOURCE, *normal_inputs, *method_inputs,
        _geometry_steps(plan, shape), _material_steps(plan, shape))

    sn_source = SN_SOURCES[shape.edition]
    miner_source = MINER_SOURCES[shape.edition]
    bond_source = BOND_SOURCES[shape.edition] if shape.mixed else ADAPTER_SOURCE
    damages, yields, convergence, bonds = [], [], [], []
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
        elastic_total = plan.add(
            f"{prefix}-upstream-stress-total-elastic",
            "Engine uncorrected total stress", MPA,
            ROLE_METHOD_VALUE, ENGINE_SOURCE)
        design_total = plan.add(
            f"{prefix}-upstream-stress-total-design",
            "Engine design total stress", MPA,
            ROLE_METHOD_VALUE, ENGINE_SOURCE)
        stress_range = plan.add(
            f"{prefix}-stress-range", "Characteristic stress range", MPA,
            ROLE_COMPUTED, ADAPTER_SOURCE, normalised, long, total)
        bonds.append(plan.add(
            f"{prefix}-bond-adjustment", "Bond adjustment factor", ONE,
            ROLE_COMPUTED, bond_source, stress_range, long, elastic_total))
        design_range = plan.add(
            f"{prefix}-design-stress-range", "Design stress range", MPA,
            ROLE_COMPUTED, ADAPTER_SOURCE, long, design_total,
            "input-gamma-ff")
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
        proof = ["detail-fytk"]
        if shape.has_fyck:
            proof.append("detail-fyck")
        limit = plan.add(
            f"{prefix}-yield-limit", "Sign-dependent proof limit", MPA,
            ROLE_COMPUTED, ADAPTER_SOURCE, *proof,
            "input-gamma-s", long, design_total)
        yields.append(plan.add(
            f"{prefix}-yield-utilisation", "Bin yield utilisation", ONE,
            ROLE_COMPUTED, VERDICT_SOURCE, limit, long, design_total))

    damage = plan.add("damage-total", "Element Miner damage", ONE,
                      ROLE_COMPUTED, miner_source, *damages)
    damage_bin = plan.add(
        "governing-damage-bin", "Governing damage-bin index", ONE,
        ROLE_COMPUTED, VERDICT_SOURCE, *damages)
    yield_util = plan.add(
        "yield-utilisation", "Element yield utilisation", ONE,
        ROLE_COMPUTED, VERDICT_SOURCE, *yields)
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
        ROLE_FINAL, VERDICT_SOURCE, normalised, *bonds,
        damage_bin, yield_bin, utilisation, passed)
    return tuple(plan.specs)


def output_steps(shape):
    plan = _Plan()
    steel = plan.add("input-check-steel", "Reinforcement check enabled", ONE,
                     ROLE_USER_INPUT, INPUT_SOURCE)
    concrete = plan.add("input-check-concrete", "Concrete check enabled", ONE,
                        ROLE_USER_INPUT, INPUT_SOURCE)
    converged, passed, governing, spectrum_utils = [], [], [], []
    for si, spectrum in enumerate(shape.spectra):
        element_utils = []
        for ei, element_id in enumerate(spectrum.element_ids):
            prefix = output_element_prefix(si, spectrum.name, ei, element_id)
            element_utils.append(plan.add(
                f"{prefix}-utilisation", "Engine element utilisation", ONE,
                ROLE_METHOD_VALUE, ENGINE_SOURCE))
            converged.append(plan.add(
                f"{prefix}-converged", "Engine element convergence", ONE,
                ROLE_METHOD_VALUE, ENGINE_SOURCE))
            passed.append(plan.add(
                f"{prefix}-passed", "Engine element status", ONE,
                ROLE_METHOD_VALUE, ENGINE_SOURCE))
        prefix = spectrum_prefix(si, spectrum.name)
        governing.append(plan.add(
            f"{prefix}-governing-element", "Governing element index", ONE,
            ROLE_COMPUTED, VERDICT_SOURCE, *element_utils))
        if not shape.joint:
            spectrum_utils.append(plan.add(
                f"{prefix}-utilisation", "Spectrum utilisation", ONE,
                ROLE_COMPUTED, VERDICT_SOURCE, *element_utils))
    all_converged = plan.add(
        "reinforcement-converged", "Reinforcement convergence", ONE,
        ROLE_COMPUTED, VERDICT_SOURCE, steel, concrete, *converged)
    all_passed = plan.add(
        "reinforcement-passed", "Reinforcement PASS or FAIL", ONE,
        ROLE_COMPUTED, VERDICT_SOURCE, all_converged, *passed)
    tail = []
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
        ROLE_FINAL, VERDICT_SOURCE, *governing, *tail, all_passed)
    return tuple(plan.specs)


def invalid_steps(shape):
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
        for index, message in enumerate(shape.errors)]
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
            TraceSourceContract(
                spec.source.kind, spec.source.method_id, spec.source.edition)
            for spec in specs),
        result_states=frozenset(states),
        step_ids=tuple(spec.step_id for spec in specs),
        step_dependencies=tuple(
            (spec.step_id, spec.dependencies) for spec in specs),
        step_metadata=tuple(
            TraceStepMetadataContract(spec.step_id, spec.role, spec.source)
            for spec in specs))


def expected_registry(shape):
    members = []
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
