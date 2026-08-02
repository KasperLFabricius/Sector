"""Frozen CT-010 identity, retained inventories, sources, and dependency graph.

Member design (PR-08D.3a, reinforcement slice): the retained fatigue adapter
publishes one payload per run (case-table independent). This slice carries

* one ``reinforcement`` member per retained (spectrum, element) assignment,
  owning that element's complete per-bin S-N damage and yield screening;
* one ``reinforcement-output`` member owning the retained reinforcement
  governing selections (per-spectrum governing element and, on the
  steel-only branch, the family governing spectrum and verdict); and
* the ``invalid`` member: the retained invalid-input branch selected from
  validated direct inputs before candidate numerics, sealed as an explicit
  failed evidence state.

The concrete fatigue members (fcd,fat, the Miner/equivalent concrete methods
and the adaptive fibre search) are the named PR-08D.3b siblings: their
retained payload keys are pinned in the inventories below but carry no
members in this slice.
"""

from __future__ import annotations

from dataclasses import dataclass

from .calculation_trace import (
    RESULT_FAILED, RESULT_FINITE, ROLE_COMPUTED, ROLE_FINAL,
    ROLE_METHOD_VALUE, ROLE_USER_INPUT, SOURCE_INPUT, SOURCE_PROJECT,
    SOURCE_STANDARD, SourceCitation, TraceAxis, TraceSource, TraceUnit,
    trace_identity_token,
)
from .section_trace_blocks import MaterialBlock, SectionTraceBlocks
from .trace_registry import (
    TraceFamilyContract, TraceMemberContract, TraceRegistryContract,
    TraceSourceContract, TraceStepMetadataContract,
)


COVERAGE_ID = "ct-010"
FAMILY_ID = "ct-010-fatigue"
REGISTRY_ID = "sector-ct-010-fatigue-v1"
METHOD_ID = "sector-retained-fatigue-replay"
OUTPUT_MEMBER_ID = "reinforcement-output"
INVALID_MEMBER_ID = "invalid"

# Genuine retained demand-versus-resistance decisions exist in this family
# (Palmgren-Miner damage limit 1.0 and the yield screen); the literal
# retained encoding is replayed exactly.
STATUS_CODES = {"PASS": 1.0, "FAIL": 0.0}

# Retained fatigue editions, in the retained selector order (the sealed
# ``input-edition`` leaf is this tuple's index).
EDITION_2005 = "DS/EN 1992-1-1:2005"
EDITION_2005_DKNA = "DS/EN 1992-1-1:2005 + DK NA:2024"
EDITION_2023 = "DS/EN 1992-1-1:2023"
EDITIONS = (EDITION_2005, EDITION_2005_DKNA, EDITION_2023)

# Frozen retained inventories (exact key order of app run_analysis /
# invalid_result). The invalid payload carries the leading ``valid`` key that
# the valid payload does NOT carry: the asymmetry is pinned, never normalised.
VALID_KEYS = (
    "edition", "checks", "concrete_method", "basis", "method_reference",
    "calculation_references", "warnings", "partial_factors",
    "concrete_parameters", "reinforcement_properties", "fatigue_detail_basis",
    "t0_days", "elements", "spectra", "governing_spectrum", "utilisation",
    "converged", "passed",
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
# Named excluded concrete siblings (PR-08D.3b): presence and position are
# pinned by the key inventories; their values carry no members here.
CONCRETE_EXCLUDED_KEYS = ("concrete_method", "concrete_parameters")
CONCRETE_EXCLUDED_RESULT_FIELDS = (
    "concrete", "concrete_search", "fcd_fat_mpa", "governing_concrete_fibre",
    "concrete_method",
)
CONCRETE_EXCLUDED_BIN_FIELDS = (
    "concrete_compression_long_mpa", "concrete_compression_total_mpa",
    "concrete_compression_design_total_mpa",
)
# Raw retained solver states inside the published bin states: bound by type
# and presence; their numeric surfaces are owned by CT-005.
RAW_SOLVER_FIELDS = ("elastic_result", "design_elastic_result")

# Frozen retained dataclass field orders (sector.fatigue).
PROPERTY_FIELDS = (
    "element_id", "kind", "detail_id", "diameter_mm", "n_star", "k1", "k2",
    "delta_sigma_rsk_mpa", "fytk_mpa", "fyck_mpa", "bond_ratio_xi",
    "bond_equivalent_diameter_mm",
)
BIN_RESULT_FIELDS = (
    "bin_name", "cycles", "converged", "stress_long_mpa", "stress_total_mpa",
    "stress_total_design_mpa", "stress_total_elastic_mpa", "stress_range_mpa",
    "stress_range_elastic_mpa", "bond_adjustment", "bond_method",
    "design_stress_range_mpa", "delta_sigma_rsk_mpa", "delta_sigma_rd_mpa",
    "sn_exponent", "cycles_to_failure", "log10_cycles_to_failure", "damage",
    "governing_stress_mpa", "yield_limit_mpa", "yield_utilisation",
)
RESULT_FIELDS = (
    "element_id", "kind", "detail_id", "diameter_mm", "bins", "damage",
    "damage_utilisation", "governing_damage_bin", "yield_utilisation",
    "governing_yield_bin", "utilisation", "converged", "passed",
)
BIN_STATE_FIELDS = (
    "name", "description", "cycles", "converged", "bar_stress_long_mpa",
    "bar_stress_total_mpa", "concrete_compression_long_mpa",
    "concrete_compression_total_mpa", "elastic_result",
    "bar_stress_fatigue_total_mpa", "bond_method", "design_action_factor",
    "design_elastic_result", "bar_stress_design_total_mpa",
    "bar_stress_fatigue_design_total_mpa",
    "concrete_compression_design_total_mpa",
)
SPECTRUM_RESULT_FIELDS = (
    "spectrum_name", "bins", "reinforcement", "concrete", "concrete_search",
    "fcd_fat_mpa", "governing_reinforcement_id", "governing_concrete_fibre",
    "utilisation", "converged", "passed", "concrete_method",
)

DOC_2005 = "DS/EN 1992-1-1:2005 + A1:2014"
DOC_DKNA = "DS/EN 1992-1-1:2005 + A1:2014 + DK NA:2024"
DOC_2023 = "DS/EN 1992-1-1:2023"

INPUT_SOURCE = TraceSource(SOURCE_INPUT, "sector-section-input")
ADAPTER_SOURCE = TraceSource(SOURCE_PROJECT, "sector-fatigue-adapter")
ENGINE_SOURCE = TraceSource(SOURCE_PROJECT, "sector-ct-010-fatigue-engine")
VERDICT_SOURCE = TraceSource(SOURCE_PROJECT, "sector-fatigue-verdict")

# Per-edition retained method identities: the same two-slope S-N mechanics
# carry edition-specific sources (2023 E.5.2 versus 2004+A1 6.8.4 with
# Tables 6.3N/6.4N; the DK NA edition is the 2005 mechanics with explicit
# DK NA:2024 input factors and its own standards identity).
SN_SOURCES = {
    EDITION_2005: TraceSource(
        SOURCE_STANDARD, "en-1992-1-1-2005-steel-sn-curve", EDITION_2005,
        SourceCitation(DOC_2005, "6.8.4", "Tables 6.3N/6.4N two-slope S-N"),
    ),
    EDITION_2005_DKNA: TraceSource(
        SOURCE_STANDARD, "en-1992-1-1-2005-dkna-steel-sn-curve",
        EDITION_2005_DKNA,
        SourceCitation(DOC_DKNA, "6.8.4",
                       "Tables 6.3N/6.4N with DK NA:2024 explicit factors"),
    ),
    EDITION_2023: TraceSource(
        SOURCE_STANDARD, "en-1992-1-1-2023-steel-sn-curve", EDITION_2023,
        SourceCitation(DOC_2023, "E.5.2", "Tables E.1/E.2 two-slope S-N"),
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
        SourceCitation(DOC_DKNA, "6.8.4(2)", "Palmgren-Miner damage sum"),
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

_BIN_ACTION_FIELDS = (
    ("n-long", "Entered long-term axial action N_Ed", KN),
    ("mx-long", "Entered long-term Mx_Ed", KNM),
    ("my-long", "Entered long-term My_Ed", KNM),
    ("n-short", "Entered cyclic axial increment N_Ed", KN),
    ("mx-short", "Entered cyclic Mx_Ed increment", KNM),
    ("my-short", "Entered cyclic My_Ed increment", KNM),
)


@dataclass(frozen=True, slots=True)
class ElementMemberShape:
    """One retained (spectrum, element) reinforcement fatigue assessment."""

    spectrum_index: int
    spectrum_name: str
    element_index: int  # global retained solver order (mild then tendons)
    kind: str
    element_id: str
    material_id: str
    detail_id: str
    bins: tuple[str, ...]
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
class SpectrumOutputShape:
    name: str
    element_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OutputShape:
    joint: bool  # concrete check enabled: family verdict is a joint sibling
    spectra: tuple[SpectrumOutputShape, ...]
    calculation_id: str
    axes: tuple[TraceAxis, ...]


@dataclass(frozen=True, slots=True)
class InvalidShape:
    errors: tuple[str, ...]
    calculation_id: str
    axes: tuple[TraceAxis, ...]


@dataclass(frozen=True, slots=True)
class FatigueShape:
    elements: tuple[ElementMemberShape, ...]
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


class _Rows:
    def __init__(self) -> None:
        self.rows: list[StepSpec] = []

    def add(self, step_id, title, unit, role, source, *dependencies) -> str:
        self.rows.append(StepSpec(
            step_id, title, unit, role, source, tuple(dependencies)
        ))
        return step_id


def bin_prefix(index: int, name: str) -> str:
    return f"bin-{index:02d}-{trace_identity_token(name)}"


def bin_description_id(index: int, name: str, description: str) -> str:
    return (f"{bin_prefix(index, name)}-description-"
            f"{trace_identity_token(description)}")


def material_prefix(material: MaterialBlock) -> str:
    return (f"material-{material.kind}-"
            f"{trace_identity_token(material.element_id)}-"
            f"{trace_identity_token(material.material_id)}")


def material_leaf_id(material: MaterialBlock, name: str) -> str:
    return f"{material_prefix(material)}-{trace_identity_token(name)}"


def _material_unit(name: str) -> TraceUnit:
    if name in {"fck", "fytk", "fyck", "futk", "Es"}:
        return MPA
    return ONE


def _geometry(rows: _Rows, shape: ElementMemberShape) -> str:
    leaves: list[str] = []
    for ring_index, ring in enumerate(shape.blocks.geometry.rings):
        for point_index, _point in enumerate(ring):
            prefix = f"geometry-ring-{ring_index:03d}-point-{point_index:04d}"
            leaves.extend((
                rows.add(f"{prefix}-x", "Concrete vertex x", M,
                         ROLE_USER_INPUT, INPUT_SOURCE),
                rows.add(f"{prefix}-y", "Concrete vertex y", M,
                         ROLE_USER_INPUT, INPUT_SOURCE),
            ))
    for kind, elements in (
        ("bar", shape.blocks.geometry.bars),
        ("tendon", shape.blocks.geometry.tendons),
    ):
        for index, _element in enumerate(elements):
            prefix = f"geometry-{kind}-{index:04d}"
            leaves.extend((
                rows.add(f"{prefix}-x", f"{kind.title()} x", M,
                         ROLE_USER_INPUT, INPUT_SOURCE),
                rows.add(f"{prefix}-y", f"{kind.title()} y", M,
                         ROLE_USER_INPUT, INPUT_SOURCE),
                rows.add(f"{prefix}-area", f"{kind.title()} area", M2,
                         ROLE_USER_INPUT, INPUT_SOURCE),
            ))
    return rows.add(
        "geometry-vector", "Immutable section geometry", ONE,
        ROLE_COMPUTED, ADAPTER_SOURCE, *leaves)


def _materials(rows: _Rows, shape: ElementMemberShape) -> str:
    leaves: list[str] = []
    for material in (
        shape.blocks.concrete,
        *shape.blocks.bars,
        *shape.blocks.tendons,
    ):
        for name, _value in material.values:
            leaves.append(rows.add(
                material_leaf_id(material, name),
                f"{material.kind.title()} law {name}",
                _material_unit(name), ROLE_METHOD_VALUE,
                material.provenance.source))
    return rows.add(
        "material-vector", "Immutable assigned material laws", ONE,
        ROLE_COMPUTED, ADAPTER_SOURCE, *leaves)


def element_member_id(shape: ElementMemberShape) -> str:
    # Spectrum, element, MATERIAL and detail identities are all tokenized:
    # same-law different-ID assignments seal differently on every axis.
    return (f"reinforcement-s{shape.spectrum_index:02d}-"
            f"{trace_identity_token(shape.spectrum_name)}-"
            f"e{shape.element_index:02d}-"
            f"{trace_identity_token(shape.element_id)}-"
            f"{trace_identity_token(shape.material_id)}-"
            f"{trace_identity_token(shape.detail_id)}")


def spectrum_prefix(index: int, name: str) -> str:
    return f"s{index:02d}-{trace_identity_token(name)}"


def output_element_prefix(spectrum_index: int, spectrum_name: str,
                          element_index: int, element_id: str) -> str:
    return (f"{spectrum_prefix(spectrum_index, spectrum_name)}-"
            f"e{element_index:02d}-{trace_identity_token(element_id)}")


def invalid_error_id(index: int, message: str) -> str:
    return f"invalid-error-{index:02d}-{trace_identity_token(message)}"


def expected_element_steps(shape: ElementMemberShape) -> tuple[StepSpec, ...]:
    rows = _Rows()
    if len(shape.bins) != len(shape.bin_descriptions):
        raise ValueError("fatigue bin names and descriptions must align")
    sn = SN_SOURCES[shape.edition]
    miner = MINER_SOURCES[shape.edition]
    bond = BOND_SOURCES[shape.edition] if shape.mixed else ADAPTER_SOURCE
    scalars = [
        rows.add("input-check-steel", "Reinforcement fatigue check enabled",
                 ONE, ROLE_USER_INPUT, INPUT_SOURCE),
        rows.add("input-edition", "Selected fatigue edition", ONE,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        rows.add("input-gamma-s", "Entered gamma_s", ONE, ROLE_USER_INPUT,
                 INPUT_SOURCE),
        rows.add("input-gamma-ff", "Entered gamma_Ff", ONE, ROLE_USER_INPUT,
                 INPUT_SOURCE),
        rows.add("input-nl", "Entered long-term modular ratio", ONE,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        rows.add("input-ns", "Entered short-term modular ratio", ONE,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        rows.add("input-diameter", "Entered element diameter", MM,
                 ROLE_USER_INPUT, INPUT_SOURCE),
    ]
    for index, (name, description) in enumerate(
            zip(shape.bins, shape.bin_descriptions)):
        prefix = bin_prefix(index, name)
        scalars.append(rows.add(
            bin_description_id(index, name, description),
            "Retained bin description identity", ONE,
            ROLE_USER_INPUT, INPUT_SOURCE))
        scalars.append(rows.add(f"{prefix}-cycles", "Entered applied cycles",
                                ONE, ROLE_USER_INPUT, INPUT_SOURCE))
        for suffix, title, unit in _BIN_ACTION_FIELDS:
            scalars.append(rows.add(f"{prefix}-{suffix}", title, unit,
                                    ROLE_USER_INPUT, INPUT_SOURCE))
    details = [
        rows.add("detail-n-star", "Resolved S-N knee cycle count N*", ONE,
                 ROLE_METHOD_VALUE, ADAPTER_SOURCE),
        rows.add("detail-k1", "Resolved S-N first slope k1", ONE,
                 ROLE_METHOD_VALUE, ADAPTER_SOURCE),
        rows.add("detail-k2", "Resolved S-N second slope k2", ONE,
                 ROLE_METHOD_VALUE, ADAPTER_SOURCE),
        rows.add("detail-delta-sigma-rsk",
                 "Resolved characteristic stress range", MPA,
                 ROLE_METHOD_VALUE, ADAPTER_SOURCE),
        rows.add("detail-fytk", "Resolved characteristic yield/proof stress",
                 MPA, ROLE_METHOD_VALUE, ADAPTER_SOURCE),
    ]
    if shape.has_fyck:
        details.append(rows.add(
            "detail-fyck", "Resolved compression yield stress", MPA,
            ROLE_METHOD_VALUE, ADAPTER_SOURCE))
    if shape.has_bond_xi:
        details.append(rows.add(
            "detail-bond-xi", "Resolved bond ratio xi", ONE,
            ROLE_METHOD_VALUE, ADAPTER_SOURCE))
    if shape.has_bond_diameter:
        details.append(rows.add(
            "detail-bond-eq-diameter", "Resolved bond equivalent diameter",
            MM, ROLE_METHOD_VALUE, ADAPTER_SOURCE))
    details.append(rows.add("element-es", "Assigned reinforcement modulus",
                            MPA, ROLE_METHOD_VALUE, ADAPTER_SOURCE))
    geometry = _geometry(rows, shape)
    materials = _materials(rows, shape)
    normalised = rows.add(
        "normalised-fatigue-inputs", "Complete fatigue input identity", ONE,
        ROLE_COMPUTED, ADAPTER_SOURCE, *scalars, *details, geometry, materials)

    damages, yields, converged_leaves, bond_steps = [], [], [], []
    for index, name in enumerate(shape.bins):
        prefix = bin_prefix(index, name)
        converged_leaves.append(rows.add(
            f"{prefix}-upstream-converged", "Engine bin convergence state",
            ONE, ROLE_METHOD_VALUE, ENGINE_SOURCE))
        long = rows.add(f"{prefix}-upstream-stress-long",
                        "Engine long-term steel stress", MPA,
                        ROLE_METHOD_VALUE, ENGINE_SOURCE)
        total = rows.add(f"{prefix}-upstream-stress-total",
                         "Engine bond-corrected total steel stress", MPA,
                         ROLE_METHOD_VALUE, ENGINE_SOURCE)
        elastic = rows.add(f"{prefix}-upstream-stress-total-elastic",
                           "Engine uncorrected total steel stress", MPA,
                           ROLE_METHOD_VALUE, ENGINE_SOURCE)
        design = rows.add(f"{prefix}-upstream-stress-total-design",
                          "Engine gamma_Ff-factored total steel stress", MPA,
                          ROLE_METHOD_VALUE, ENGINE_SOURCE)
        rng = rows.add(f"{prefix}-stress-range", "Characteristic stress range",
                       MPA, ROLE_COMPUTED, ADAPTER_SOURCE, normalised, long,
                       total)
        bond_steps.append(rows.add(
            f"{prefix}-bond-adjustment", "Edition bond adjustment factor",
            ONE, ROLE_COMPUTED, bond, rng, long, elastic))
        design_range = rows.add(
            f"{prefix}-design-stress-range", "Design stress range", MPA,
            ROLE_COMPUTED, ADAPTER_SOURCE, long, design, "input-gamma-ff")
        exponent = rows.add(
            f"{prefix}-sn-exponent", "Governing S-N slope", ONE,
            ROLE_COMPUTED, sn, design_range, "detail-k1", "detail-k2",
            "detail-delta-sigma-rsk", "input-gamma-s")
        life = rows.add(
            f"{prefix}-log10-cycles-to-failure", "S-N life log10 N", ONE,
            ROLE_COMPUTED, sn, exponent, design_range, "detail-n-star",
            "detail-delta-sigma-rsk", "input-gamma-s")
        damages.append(rows.add(
            f"{prefix}-damage", "Bin Palmgren-Miner damage", ONE,
            ROLE_COMPUTED, miner, f"{prefix}-cycles", life))
        limit_deps = ["detail-fytk"]
        if shape.has_fyck:
            limit_deps.append("detail-fyck")
        limit = rows.add(
            f"{prefix}-yield-limit", "Sign-dependent yield limit", MPA,
            ROLE_COMPUTED, ADAPTER_SOURCE, *limit_deps, "input-gamma-s",
            long, design)
        yields.append(rows.add(
            f"{prefix}-yield-utilisation", "Bin yield utilisation", ONE,
            ROLE_COMPUTED, VERDICT_SOURCE, limit, long, design))
    damage_total = rows.add("damage-total", "Element Miner damage sum", ONE,
                            ROLE_COMPUTED, miner, *damages)
    governing_damage = rows.add(
        "governing-damage-bin", "Governing damage bin index", ONE,
        ROLE_COMPUTED, VERDICT_SOURCE, *damages)
    yield_util = rows.add("yield-utilisation", "Element yield utilisation",
                          ONE, ROLE_COMPUTED, VERDICT_SOURCE, *yields)
    governing_yield = rows.add(
        "governing-yield-bin", "Governing yield bin index", ONE,
        ROLE_COMPUTED, VERDICT_SOURCE, *yields)
    utilisation = rows.add("utilisation", "Element fatigue utilisation", ONE,
                           ROLE_COMPUTED, VERDICT_SOURCE, damage_total,
                           yield_util)
    converged = rows.add("converged", "Element convergence state", ONE,
                         ROLE_COMPUTED, VERDICT_SOURCE, *converged_leaves)
    passed = rows.add("passed", "Element PASS or FAIL", ONE, ROLE_COMPUTED,
                      VERDICT_SOURCE, converged, damage_total, yield_util)
    rows.add("ct-010-element-result", "CT-010 reinforcement element status",
             ONE, ROLE_FINAL, VERDICT_SOURCE, normalised, *bond_steps,
             governing_damage, governing_yield, utilisation, passed)
    return tuple(rows.rows)


def expected_output_steps(shape: OutputShape) -> tuple[StepSpec, ...]:
    rows = _Rows()
    check_steel = rows.add("input-check-steel",
                           "Reinforcement fatigue check enabled", ONE,
                           ROLE_USER_INPUT, INPUT_SOURCE)
    check_concrete = rows.add("input-check-concrete",
                              "Concrete fatigue check enabled", ONE,
                              ROLE_USER_INPUT, INPUT_SOURCE)
    all_converged, all_passed, governing, spectrum_utils = [], [], [], []
    for spectrum_index, spectrum in enumerate(shape.spectra):
        utils = []
        for element_index, element_id in enumerate(spectrum.element_ids):
            prefix = output_element_prefix(
                spectrum_index, spectrum.name, element_index, element_id)
            utils.append(rows.add(
                f"{prefix}-utilisation", "Engine element utilisation", ONE,
                ROLE_METHOD_VALUE, ENGINE_SOURCE))
            all_converged.append(rows.add(
                f"{prefix}-converged", "Engine element convergence", ONE,
                ROLE_METHOD_VALUE, ENGINE_SOURCE))
            all_passed.append(rows.add(
                f"{prefix}-passed", "Engine element status", ONE,
                ROLE_METHOD_VALUE, ENGINE_SOURCE))
        prefix = spectrum_prefix(spectrum_index, spectrum.name)
        governing.append(rows.add(
            f"{prefix}-governing-element", "Governing reinforcement element",
            ONE, ROLE_COMPUTED, VERDICT_SOURCE, *utils))
        if not shape.joint:
            spectrum_utils.append(rows.add(
                f"{prefix}-utilisation", "Spectrum reinforcement utilisation",
                ONE, ROLE_COMPUTED, VERDICT_SOURCE, *utils))
    converged = rows.add(
        "reinforcement-converged", "Reinforcement convergence state", ONE,
        ROLE_COMPUTED, VERDICT_SOURCE, check_steel, check_concrete,
        *all_converged)
    passed = rows.add(
        "reinforcement-passed", "Reinforcement PASS or FAIL", ONE,
        ROLE_COMPUTED, VERDICT_SOURCE, converged, *all_passed)
    tail = []
    if not shape.joint:
        tail.append(rows.add(
            "governing-spectrum", "Governing spectrum index", ONE,
            ROLE_COMPUTED, VERDICT_SOURCE, *spectrum_utils))
        tail.append(rows.add(
            "family-utilisation", "Family fatigue utilisation", ONE,
            ROLE_COMPUTED, VERDICT_SOURCE, *spectrum_utils,
            "governing-spectrum"))
    rows.add("ct-010-reinforcement-output-result",
             "CT-010 reinforcement family status", ONE, ROLE_FINAL,
             VERDICT_SOURCE, *governing, *tail, passed)
    return tuple(rows.rows)


def expected_invalid_steps(shape: InvalidShape) -> tuple[StepSpec, ...]:
    rows = _Rows()
    scalars = [
        rows.add("input-fatigue-on", "Fatigue analysis enabled", ONE,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        rows.add("input-check-steel", "Reinforcement fatigue check enabled",
                 ONE, ROLE_USER_INPUT, INPUT_SOURCE),
        rows.add("input-check-concrete", "Concrete fatigue check enabled",
                 ONE, ROLE_USER_INPUT, INPUT_SOURCE),
    ]
    error_steps = [
        rows.add(invalid_error_id(index, message),
                 "Retained fatigue validation error", ONE, ROLE_COMPUTED,
                 ADAPTER_SOURCE, *scalars)
        for index, message in enumerate(shape.errors)
    ]
    rows.add("ct-010-invalid-result", "CT-010 invalid fatigue input state",
             ONE, ROLE_FINAL, VERDICT_SOURCE, *scalars, *error_steps)
    return tuple(rows.rows)


def _member(member_id, calculation_id, axes, specs, states):
    return TraceMemberContract(
        member_id=member_id, calculation_id=calculation_id,
        coverage_id=COVERAGE_ID, method_id=METHOD_ID, axes=axes,
        sources=frozenset(TraceSourceContract(s.source.kind,
                                              s.source.method_id,
                                              s.source.edition)
                          for s in specs),
        result_states=frozenset(states),
        step_ids=tuple(s.step_id for s in specs),
        step_dependencies=tuple((s.step_id, s.dependencies) for s in specs),
        step_metadata=tuple(TraceStepMetadataContract(
            s.step_id, s.quantity_role, s.source
        ) for s in specs),
    )


def expected_registry(shape: FatigueShape) -> TraceRegistryContract:
    members = []
    if shape.invalid is not None:
        members.append(_member(
            INVALID_MEMBER_ID, shape.invalid.calculation_id,
            shape.invalid.axes, expected_invalid_steps(shape.invalid),
            {RESULT_FAILED},
        ))
    for element in shape.elements:
        members.append(_member(
            element_member_id(element), element.calculation_id, element.axes,
            expected_element_steps(element), {RESULT_FINITE},
        ))
    if shape.output is not None:
        members.append(_member(
            OUTPUT_MEMBER_ID, shape.output.calculation_id, shape.output.axes,
            expected_output_steps(shape.output), {RESULT_FINITE},
        ))
    if not members:
        raise ValueError("CT-010 registry needs at least one applicable member")
    return TraceRegistryContract(
        REGISTRY_ID, (TraceFamilyContract(FAMILY_ID, tuple(members)),)
    )
