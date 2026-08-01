"""Frozen CT-008 identity, retained inventories, sources, and dependency graph."""

from __future__ import annotations

from dataclasses import dataclass

from .calculation_trace import (
    RESULT_FINITE, ROLE_COMPUTED, ROLE_FINAL, ROLE_METHOD_VALUE,
    ROLE_USER_INPUT, SOURCE_INPUT, SOURCE_PROJECT, SOURCE_STANDARD,
    SourceCitation, TraceAxis, TraceSource, TraceUnit, trace_identity_token,
)
from .trace_registry import (
    TraceFamilyContract, TraceMemberContract, TraceRegistryContract,
    TraceSourceContract, TraceStepMetadataContract,
)


COVERAGE_ID = "ct-008"
FAMILY_ID = "ct-008-detailing"
REGISTRY_ID = "sector-ct-008-detailing-v1"
METHOD_ID = "sector-retained-detailing-replay"
CLEAR_MEMBER_ID = "clear-spacing"
TRANSVERSE_MEMBER_ID = "transverse-links"

EDITION_2005 = "EN 1992-1-1:2005"
EDITION_DKNA = "DS/EN 1992-1-1:2005 + DK NA:2024"
EDITION_2023 = "DS/EN 1992-1-1:2023"
EDITIONS = (EDITION_DKNA, EDITION_2005, EDITION_2023)

DOC_2005 = "EN 1992-1-1:2005"
DOC_DK = "DS/EN 1992-1-1 DK NA:2024"
DOC_2023 = "DS/EN 1992-1-1:2023"

# Retained detailing statuses are finite evidence states, encoded exactly.
STATUS_CODES = {
    "PASS": 1.0, "FAIL": 0.0, "REVIEW": 2.0, "NOT ASSESSED": 3.0,
    "NOT APPLICABLE": 4.0, "INVALID": 5.0,
}
DUCTILITY_CLASSES = ("A", "B", "C")

# Frozen retained output inventories (exact key order).
CLEAR_INVALID_KEYS = (
    "status", "edition", "clause", "d_upper_mm", "pairs", "invalid_ids",
    "reason",
)
CLEAR_KEYS = (
    "status", "edition", "clause", "d_upper_mm", "include_tendons", "pairs",
    "governing", "reason", "limitations",
)
PAIR_KEYS = (
    "status", "first_id", "second_id", "first_kind", "second_kind",
    "clear_mm", "required_mm", "margin_mm", "centre_distance_mm",
    "phi_first_mm", "phi_second_mm",
)
TRANSVERSE_INVALID_KEYS = ("status", "edition", "checks", "reason", "limitations")
TRANSVERSE_KEYS = (
    "status", "edition", "member_type", "checks", "governing",
    "governing_utilisation", "reason", "minimum_ratio", "diameter_mm",
    "spacing_mm", "fywk_mpa", "limitations",
)
MINIMUM_RATIO_KEYS = (
    "ratio", "coefficient", "ductility_class", "ductility_factor",
    "ductility_reduction_applied", "clause",
)
TORSION_LIMIT_KEYS = ("u_k/8", "minimum section dimension")

_RATIO_BASE = (
    "kind", "scope", "status", "provided", "limit", "utilisation",
    "criterion", "clause",
)
_REASON_BASE = (*_RATIO_BASE, "reason")
CHECK_ROW_KEYS = {
    "minimum_ratio": (
        (*_RATIO_BASE, "component", "provided_label", "limit_label",
         "bw_mm", "d_mm", "legs"),
        (*_RATIO_BASE, "tube", "provided_label", "limit_label", "tef_mm"),
        (*_REASON_BASE, "component"),
        (*_REASON_BASE, "tube"),
    ),
    "longitudinal_spacing": (
        (*_REASON_BASE, "component", "provided_label", "limit_label", "d_mm"),
        (*_REASON_BASE, "component"),
    ),
    "transverse_leg_spacing": (
        (*_REASON_BASE, "component", "provided_label", "limit_label",
         "spacing_source", "measurement_axis", "d_mm"),
        (*_REASON_BASE, "component"),
    ),
    "torsion_spacing": (
        (*_REASON_BASE, "tube", "provided_label", "limit_label",
         "spacing_limits_mm", "governing_limit"),
        (*_REASON_BASE, "tube"),
    ),
    "required_links": (
        (*_REASON_BASE, "component"),
        (*_REASON_BASE, "component", "requirement"),
    ),
    "minimum_link_applicability": (
        (*_REASON_BASE, "component"),
        (*_REASON_BASE, "component", "d_mm"),
    ),
}

INPUT_SOURCE = TraceSource(SOURCE_INPUT, "sector-section-input")
ADAPTER_SOURCE = TraceSource(SOURCE_PROJECT, "sector-detailing-adapter")
GEOMETRY_SOURCE = TraceSource(SOURCE_PROJECT, "sector-detailing-geometry")
VERDICT_SOURCE = TraceSource(SOURCE_PROJECT, "sector-detailing-verdict")
SHEAR_EVIDENCE_SOURCE = TraceSource(
    SOURCE_PROJECT, "sector-retained-shear-evidence"
)
TORSION_EVIDENCE_SOURCE = TraceSource(
    SOURCE_PROJECT, "sector-retained-torsion-evidence"
)
CLEAR_SOURCE_BASE = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2005-bar-clear-spacing", EDITION_2005,
    SourceCitation(DOC_2005, "8.2(2)", "minimum clear bar distance"),
)
CLEAR_SOURCE_2023 = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2023-bar-clear-spacing", EDITION_2023,
    SourceCitation(DOC_2023, "11.2(2)", "minimum clear bar distance"),
)
RATIO_SOURCE_BASE = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2005-minimum-link-ratio", EDITION_2005,
    SourceCitation(DOC_2005, "9.2.2(5)", "Formulae (9.4)-(9.5)"),
)
RATIO_SOURCE_DK = TraceSource(
    SOURCE_STANDARD, "dk-na-2024-minimum-link-ratio", EDITION_DKNA,
    SourceCitation(DOC_DK, "9.2.2(5)", "rho_w,min coefficient 0.063"),
)
RATIO_SOURCE_2023 = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2023-minimum-link-ratio", EDITION_2023,
    SourceCitation(DOC_2023, "12.2(4)", "Formula (12.4)"),
)
SHEAR_SPACING_BEAM_BASE = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2005-beam-link-spacing", EDITION_2005,
    SourceCitation(DOC_2005, "9.2.2(5)-(8)", "Formulae (9.4)-(9.8)"),
)
SHEAR_SPACING_SLAB_BASE = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2005-slab-link-spacing", EDITION_2005,
    SourceCitation(DOC_2005, "9.3.2(2), (4)-(5)", "slab shear-link spacing"),
)
SHEAR_SPACING_BEAM_2023 = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2023-beam-link-spacing", EDITION_2023,
    SourceCitation(DOC_2023, "12.2(4)", "Table 12.1"),
)
SHEAR_SPACING_SLAB_2023 = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2023-slab-link-spacing", EDITION_2023,
    SourceCitation(DOC_2023, "12.2(4)", "Table 12.2, 12.4.2"),
)
TORSION_SPACING_BASE = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2005-torsion-link-spacing", EDITION_2005,
    SourceCitation(DOC_2005, "9.2.3(3)", "closed torsion-link spacing"),
)
TORSION_SPACING_2023 = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2023-torsion-link-spacing", EDITION_2023,
    SourceCitation(DOC_2023, "12.3.3", "Table 12.1"),
)
REQUIRED_LINKS_BEAM_BASE = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2005-beam-minimum-links", EDITION_2005,
    SourceCitation(DOC_2005, "9.2.2(2), (5)", "minimum beam shear reinforcement"),
)
REQUIRED_LINKS_RES_BASE = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2005-links-where-required", EDITION_2005,
    SourceCitation(DOC_2005, "6.2.2", "members requiring design shear reinforcement"),
)
REQUIRED_LINKS_RES_2023 = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2023-links-where-required", EDITION_2023,
    SourceCitation(DOC_2023, "8.2.2", "members requiring design shear reinforcement"),
)
LINK_APPLICABILITY_2023 = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2023-minimum-link-applicability", EDITION_2023,
    SourceCitation(DOC_2023, "8.2.1(2), 12.2(4)", "minimum-link applicability"),
)

ONE = TraceUnit("1", "scalar")
LENGTH_MM = TraceUnit("mm", "length")
AREA_MM2 = TraceUnit("mm2", "area")
STRESS = TraceUnit("MPa", "stress")


@dataclass(frozen=True, slots=True)
class RecordShape:
    is_bar: bool
    included: bool
    geometry_ok: bool
    element_id: str = ""
    kind: str = "bar"


@dataclass(frozen=True, slots=True)
class ClearShape:
    records: tuple[RecordShape, ...]
    pairs: tuple[tuple[int, int], ...]
    invalid: bool
    edition: str
    calculation_id: str
    axes: tuple[TraceAxis, ...]


@dataclass(frozen=True, slots=True)
class DirectionShape:
    component: str
    has_bw: bool
    has_vrd_c: bool
    has_v_ed: bool
    legs_from: str  # "links", "fallback", or "" when no legs step exists
    depth_count: int
    has_fallback_legs: bool
    has_fallback_spacing: bool


@dataclass(frozen=True, slots=True)
class TubeShape:
    has_uk: bool
    has_tef: bool
    has_minimum_dimension: bool
    valid: bool = True
    reason: str = ""


@dataclass(frozen=True, slots=True)
class RowShape:
    index: int
    kind: str
    family: str  # "shear" or "torsion"
    ref: str  # component name or zero-based two-digit tube token
    variant: str
    util: str  # "finite", "infinite", or "absent"
    has_limit: bool = False
    src_tag: str = ""
    demoted: bool = False
    model_2023: bool = False


@dataclass(frozen=True, slots=True)
class TransverseShape:
    concrete_values: tuple[tuple[str, float], ...]
    concrete_source: TraceSource
    concrete_material_id: str
    edition: str
    member: str
    invalid: bool
    directions: tuple[DirectionShape, ...]
    tubes: tuple[TubeShape, ...]
    rows: tuple[RowShape, ...]
    governing_present: bool
    calculation_id: str
    axes: tuple[TraceAxis, ...]


@dataclass(frozen=True, slots=True)
class DetailingShape:
    clear: ClearShape | None
    transverse: TransverseShape | None


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


def clear_source(edition: str) -> TraceSource:
    return CLEAR_SOURCE_2023 if edition == EDITION_2023 else CLEAR_SOURCE_BASE


def ratio_source(edition: str) -> TraceSource:
    if edition == EDITION_DKNA:
        return RATIO_SOURCE_DK
    if edition == EDITION_2023:
        return RATIO_SOURCE_2023
    return RATIO_SOURCE_BASE


def shear_spacing_source(edition: str, member: str) -> TraceSource:
    if edition == EDITION_2023:
        return (SHEAR_SPACING_SLAB_2023 if member == "Slab"
                else SHEAR_SPACING_BEAM_2023)
    return (SHEAR_SPACING_SLAB_BASE if member == "Slab"
            else SHEAR_SPACING_BEAM_BASE)


def torsion_spacing_source(edition: str) -> TraceSource:
    return (TORSION_SPACING_2023 if edition == EDITION_2023
            else TORSION_SPACING_BASE)


def concrete_leaf_id(material_id: str, name: str) -> str:
    """Tokenize the selected concrete assignment into each material leaf id.

    Mirrors the accepted CT-007 material_prefix idiom so two same-law
    assignments under different retained material IDs seal differently.
    """

    return (f"material-concrete-{trace_identity_token(material_id)}-"
            f"{trace_identity_token(name)}")


def record_identity_id(index: int, element_id: str, kind: str) -> str:
    """Tokenize the exact retained record id and kind into the evidence identity."""

    return (f"element-{index:03d}-identity-"
            f"{trace_identity_token(element_id)}-{trace_identity_token(kind)}")


def tube_reason_id(index: int, reason: str) -> str:
    """Tokenize the retained invalid-tube validity reason into the identity."""

    return (f"upstream-torsion-tube-{index:02d}-reason-"
            f"{trace_identity_token(reason)}")


def expected_clear_steps(shape: ClearShape) -> tuple[StepSpec, ...]:
    rows = _Rows()
    scalars = (
        rows.add("input-clear-spacing-enabled", "Clear-spacing check enabled",
                 ONE, ROLE_USER_INPUT, INPUT_SOURCE),
        rows.add("input-d-upper", "Entered upper aggregate size", LENGTH_MM,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        rows.add("input-edition", "Selected detailing edition", ONE,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        rows.add("input-include-tendons", "Entered tendon-envelope switch",
                 ONE, ROLE_USER_INPUT, INPUT_SOURCE),
    )
    record_steps = []
    for index, record in enumerate(shape.records):
        prefix = f"element-{index:03d}"
        is_bar = rows.add(f"{prefix}-is-bar", "Entered element kind identity",
                          ONE, ROLE_USER_INPUT, INPUT_SOURCE)
        if record.included:
            record_steps.append(rows.add(
                record_identity_id(index, record.element_id, record.kind),
                "Entered element id and kind identity", ONE,
                ROLE_USER_INPUT, INPUT_SOURCE,
            ))
        if record.included and record.geometry_ok:
            for suffix, title, unit in (
                ("x", "Entered element x", LENGTH_MM),
                ("y", "Entered element y", LENGTH_MM),
                ("diameter", "Entered element diameter", LENGTH_MM),
            ):
                record_steps.append(rows.add(
                    f"{prefix}-{suffix}", title, unit,
                    ROLE_USER_INPUT, INPUT_SOURCE,
                ))
        record_steps.append(rows.add(
            f"{prefix}-included", "Element included in clear-spacing set",
            ONE, ROLE_COMPUTED, ADAPTER_SOURCE, is_bar, "input-include-tendons",
        ))
    elements = rows.add(
        "elements-vector", "Immutable ordered reinforcement records", ONE,
        ROLE_COMPUTED, GEOMETRY_SOURCE,
        *(record_steps if record_steps else ("input-include-tendons",)),
    )
    normalised = rows.add(
        "normalised-clear-spacing-inputs", "Complete clear-spacing input identity",
        ONE, ROLE_COMPUTED, ADAPTER_SOURCE, *scalars, elements,
    )
    source = clear_source(shape.edition)
    if shape.invalid:
        state = rows.add("invalid-geometry-state",
                         "Retained invalid reinforcement geometry", ONE,
                         ROLE_COMPUTED, VERDICT_SOURCE, normalised)
        rows.add("ct-008-clear-spacing-result", "CT-008 clear-spacing status",
                 ONE, ROLE_FINAL, VERDICT_SOURCE, normalised, state)
        return tuple(rows.rows)
    if not shape.pairs:
        state = rows.add("no-pairs-state",
                         "Fewer than two included reinforcement elements", ONE,
                         ROLE_COMPUTED, VERDICT_SOURCE, normalised)
        rows.add("ct-008-clear-spacing-result", "CT-008 clear-spacing status",
                 ONE, ROLE_FINAL, VERDICT_SOURCE, normalised, state)
        return tuple(rows.rows)
    margins, verdicts = [], []
    for first, second in shape.pairs:
        pair = f"pair-{first:03d}-{second:03d}"
        a, b = f"element-{first:03d}", f"element-{second:03d}"
        centre = rows.add(f"{pair}-centre-distance", "Pair centre distance",
                          LENGTH_MM, ROLE_COMPUTED, GEOMETRY_SOURCE,
                          f"{a}-x", f"{a}-y", f"{b}-x", f"{b}-y")
        clear = rows.add(f"{pair}-clear", "Pair clear distance", LENGTH_MM,
                         ROLE_COMPUTED, source, centre,
                         f"{a}-diameter", f"{b}-diameter")
        required = rows.add(f"{pair}-required", "Pair required clear distance",
                            LENGTH_MM, ROLE_COMPUTED, source,
                            f"{a}-diameter", f"{b}-diameter", "input-d-upper")
        margins.append(rows.add(f"{pair}-margin", "Pair spacing margin",
                                LENGTH_MM, ROLE_COMPUTED, source,
                                clear, required))
        verdicts.append(rows.add(f"{pair}-verdict", "Pair PASS or FAIL", ONE,
                                 ROLE_COMPUTED, source, clear, required))
    governing_margin = rows.add("governing-margin", "Smallest pair margin",
                                LENGTH_MM, ROLE_COMPUTED, VERDICT_SOURCE,
                                *margins)
    governing_pair = rows.add("governing-pair", "Governing pair index", ONE,
                              ROLE_COMPUTED, VERDICT_SOURCE, *margins)
    status = rows.add("clear-spacing-status", "Retained clear-spacing status",
                      ONE, ROLE_COMPUTED, VERDICT_SOURCE, *verdicts)
    rows.add("ct-008-clear-spacing-result", "CT-008 clear-spacing status", ONE,
             ROLE_FINAL, VERDICT_SOURCE, normalised, governing_margin,
             governing_pair, status)
    return tuple(rows.rows)


def _direction_steps(rows: _Rows, direction: DirectionShape) -> None:
    c = direction.component
    leaves = []
    if direction.has_bw:
        leaves.append(rows.add(f"upstream-shear-{c}-bw", "Retained web width",
                               LENGTH_MM, ROLE_METHOD_VALUE,
                               SHEAR_EVIDENCE_SOURCE))
    leaves.append(rows.add(f"upstream-shear-{c}-resistance-valid",
                           "Retained no-link resistance validity", ONE,
                           ROLE_METHOD_VALUE, SHEAR_EVIDENCE_SOURCE))
    if direction.has_vrd_c:
        leaves.append(rows.add(f"upstream-shear-{c}-vrd-c",
                               "Retained no-link shear resistance",
                               TraceUnit("kN", "force"), ROLE_METHOD_VALUE,
                               SHEAR_EVIDENCE_SOURCE))
    if direction.has_v_ed:
        leaves.append(rows.add(f"upstream-shear-{c}-v-ed",
                               "Retained shear demand",
                               TraceUnit("kN", "force"), ROLE_METHOD_VALUE,
                               SHEAR_EVIDENCE_SOURCE))
    leaves.append(rows.add(f"upstream-shear-{c}-model-2023",
                           "Retained 2023 shear-model flag", ONE,
                           ROLE_METHOD_VALUE, SHEAR_EVIDENCE_SOURCE))
    if direction.legs_from == "links":
        leaves.append(rows.add(f"upstream-shear-{c}-links-legs",
                               "Retained effective link legs", ONE,
                               ROLE_METHOD_VALUE, SHEAR_EVIDENCE_SOURCE))
    for depth in range(direction.depth_count):
        leaves.append(rows.add(f"upstream-shear-{c}-depth-{depth:02d}",
                               "Retained candidate effective depth", LENGTH_MM,
                               ROLE_METHOD_VALUE, SHEAR_EVIDENCE_SOURCE))
    evidence = rows.add(f"shear-{c}-evidence",
                        "Complete retained shear-direction evidence", ONE,
                        ROLE_COMPUTED, SHEAR_EVIDENCE_SOURCE, *leaves)
    required_deps = [f"upstream-shear-{c}-resistance-valid"]
    if direction.has_vrd_c:
        required_deps.append(f"upstream-shear-{c}-vrd-c")
    if direction.has_v_ed:
        required_deps.append(f"upstream-shear-{c}-v-ed")
    rows.add(f"shear-{c}-links-required", "Links-required tri-state", ONE,
             ROLE_COMPUTED, ADAPTER_SOURCE, *required_deps)
    if direction.legs_from == "links":
        rows.add(f"shear-{c}-legs", "Effective legs used for detailing", ONE,
                 ROLE_COMPUTED, ADAPTER_SOURCE,
                 f"upstream-shear-{c}-links-legs")
    elif direction.legs_from == "fallback":
        rows.add(f"shear-{c}-legs", "Effective legs used for detailing", ONE,
                 ROLE_COMPUTED, ADAPTER_SOURCE, f"input-{c}-fallback-legs")
    depth_deps = tuple(f"upstream-shear-{c}-depth-{k:02d}"
                       for k in range(direction.depth_count)) or (evidence,)
    rows.add(f"shear-{c}-detailing-depth", "Smallest retained face depth",
             LENGTH_MM, ROLE_COMPUTED, ADAPTER_SOURCE, *depth_deps)


def _tube_steps(rows: _Rows, index: int, tube: TubeShape) -> None:
    prefix = f"torsion-tube-{index:02d}"
    leaves = []
    if tube.has_uk:
        leaves.append(rows.add(f"upstream-{prefix}-uk",
                               "Retained tube centre-line perimeter",
                               LENGTH_MM, ROLE_METHOD_VALUE,
                               TORSION_EVIDENCE_SOURCE))
    if tube.has_tef:
        leaves.append(rows.add(f"upstream-{prefix}-tef",
                               "Retained effective tube thickness", LENGTH_MM,
                               ROLE_METHOD_VALUE, TORSION_EVIDENCE_SOURCE))
    if tube.has_minimum_dimension:
        leaves.append(rows.add(f"upstream-{prefix}-minimum-dimension",
                               "Retained minimum tube dimension", LENGTH_MM,
                               ROLE_METHOD_VALUE, TORSION_EVIDENCE_SOURCE))
    leaves.append(rows.add(f"upstream-{prefix}-valid",
                           "Retained tube validity", ONE, ROLE_METHOD_VALUE,
                           TORSION_EVIDENCE_SOURCE))
    if not tube.valid:
        leaves.append(rows.add(
            tube_reason_id(index, tube.reason),
            "Retained tube validity reason identity", ONE,
            ROLE_METHOD_VALUE, TORSION_EVIDENCE_SOURCE,
        ))
    rows.add(f"{prefix}-evidence", "Complete retained torsion-tube evidence",
             ONE, ROLE_COMPUTED, TORSION_EVIDENCE_SOURCE, *leaves)


def _row_steps(rows, shape, row):
    check = f"check-{row.index:02d}"
    r_source = ratio_source(shape.edition)
    s_source = shear_spacing_source(shape.edition, shape.member)
    t_source = torsion_spacing_source(shape.edition)
    util_id = None
    if row.family == "torsion":
        evidence = f"torsion-tube-{row.ref}-evidence"
    else:
        evidence = f"shear-{row.ref}-evidence"
        depth = f"shear-{row.ref}-detailing-depth"
        legs = f"shear-{row.ref}-legs"
        links_required = f"shear-{row.ref}-links-required"
    if row.variant == "ratio":
        if row.family == "shear":
            provided = rows.add(f"{check}-provided", "Provided link ratio", ONE,
                                ROLE_COMPUTED, GEOMETRY_SOURCE, legs,
                                "link-leg-area", "input-link-spacing",
                                f"upstream-shear-{row.ref}-bw")
        else:
            provided = rows.add(f"{check}-provided", "Provided link ratio", ONE,
                                ROLE_COMPUTED, GEOMETRY_SOURCE,
                                "link-leg-area", "input-link-spacing",
                                f"upstream-torsion-tube-{row.ref}-tef")
        util_id = rows.add(f"{check}-utilisation", "Ratio-check utilisation",
                           ONE, ROLE_COMPUTED, r_source, provided,
                           "minimum-ratio")
        status_deps, status_source = (provided, "minimum-ratio"), r_source
    elif row.variant == "ratio-na":
        status_deps, status_source = (evidence,), r_source
    elif row.variant == "long":
        limit = rows.add(f"{check}-limit", "Longitudinal spacing limit",
                         LENGTH_MM, ROLE_COMPUTED, s_source, depth)
        util_id = rows.add(f"{check}-utilisation", "Spacing-check utilisation",
                           ONE, ROLE_COMPUTED, s_source,
                           "input-link-spacing", limit)
        status_deps, status_source = ("input-link-spacing", limit), s_source
    elif row.variant == "long-na":
        status_deps, status_source = (depth,), s_source
    elif row.variant == "leg":
        provided_deps = ((f"input-{row.ref}-fallback-transverse-spacing",)
                         if row.src_tag == "user"
                         else (f"upstream-shear-{row.ref}-bw", legs))
        provided = rows.add(f"{check}-provided", "Transverse leg spacing",
                            LENGTH_MM, ROLE_COMPUTED,
                            GEOMETRY_SOURCE if row.src_tag == "user"
                            else ADAPTER_SOURCE, *provided_deps)
        if row.has_limit:
            limit = rows.add(f"{check}-limit", "Transverse leg spacing limit",
                             LENGTH_MM, ROLE_COMPUTED, s_source, depth,
                             "input-member-type")
        else:
            limit = depth
        if row.util != "absent":
            util_id = rows.add(f"{check}-utilisation",
                               "Spacing-check utilisation", ONE, ROLE_COMPUTED,
                               s_source, provided, limit)
        status_deps = (provided, limit)
        status_source = ADAPTER_SOURCE if row.demoted else s_source
    elif row.variant == "leg-na":
        status_deps, status_source = (evidence, depth), s_source
    elif row.variant == "torsion-spacing":
        limit_deps = [f"upstream-torsion-tube-{row.ref}-uk",
                      f"upstream-torsion-tube-{row.ref}-minimum-dimension"]
        limit = rows.add(f"{check}-limit", "Closed-link spacing limit",
                         LENGTH_MM, ROLE_COMPUTED, t_source, *limit_deps)
        util_id = rows.add(f"{check}-utilisation", "Spacing-check utilisation",
                           ONE, ROLE_COMPUTED, t_source,
                           "input-link-spacing", limit)
        status_deps, status_source = ("input-link-spacing", limit), t_source
    elif row.variant == "torsion-spacing-na":
        status_deps, status_source = (evidence,), t_source
    elif row.variant == "slab-na":
        status_deps = (evidence, "input-member-type")
        status_source = VERDICT_SOURCE
    elif row.variant == "links-forced":
        deps = (links_required, "input-member-type", "input-edition")
        util_id = rows.add(f"{check}-utilisation", "Required-links utilisation",
                           ONE, ROLE_COMPUTED, REQUIRED_LINKS_BEAM_BASE, *deps)
        status_deps, status_source = deps, REQUIRED_LINKS_BEAM_BASE
    elif row.variant == "links-required":
        source = (REQUIRED_LINKS_RES_2023 if row.model_2023
                  else REQUIRED_LINKS_RES_BASE)
        util_id = rows.add(f"{check}-utilisation", "Required-links utilisation",
                           ONE, ROLE_COMPUTED, source, links_required)
        status_deps, status_source = (links_required,), source
    elif row.variant == "links-na":
        source = (REQUIRED_LINKS_RES_2023 if row.model_2023
                  else REQUIRED_LINKS_RES_BASE)
        status_deps, status_source = (links_required,), source
    elif row.variant == "applicability":
        status_deps = (links_required, depth)
        status_source = LINK_APPLICABILITY_2023
    else:
        raise ValueError(f"unknown CT-008 row variant {row.variant!r}")
    status_id = rows.add(f"{check}-status", "Retained check-row status", ONE,
                         ROLE_COMPUTED, status_source, *status_deps)
    return status_id, util_id


def expected_transverse_steps(shape: TransverseShape) -> tuple[StepSpec, ...]:
    rows = _Rows()
    scalars = [
        rows.add("input-transverse-enabled", "Transverse detailing enabled",
                 ONE, ROLE_USER_INPUT, INPUT_SOURCE),
        rows.add("input-edition", "Selected detailing edition", ONE,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        rows.add("input-member-type", "Selected member type", ONE,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        rows.add("input-ductility-class", "Selected ductility class", ONE,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        rows.add("input-apply-ductility-reduction",
                 "Entered ductility-reduction opt-in", ONE,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        rows.add("input-link-fywk", "Entered link characteristic yield",
                 STRESS, ROLE_USER_INPUT, INPUT_SOURCE),
        rows.add("input-link-diameter", "Entered link diameter", LENGTH_MM,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        rows.add("input-link-spacing", "Entered link spacing", LENGTH_MM,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        rows.add("input-shear-enabled", "Retained shear check enabled", ONE,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        rows.add("input-shear-links", "Retained shear links enabled", ONE,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        rows.add("input-torsion-enabled", "Retained torsion check enabled",
                 ONE, ROLE_USER_INPUT, INPUT_SOURCE),
    ]
    for direction in shape.directions:
        c = direction.component
        if direction.has_fallback_legs:
            scalars.append(rows.add(f"input-{c}-fallback-legs",
                                    "Entered fallback link legs", ONE,
                                    ROLE_USER_INPUT, INPUT_SOURCE))
        if direction.has_fallback_spacing:
            scalars.append(rows.add(
                f"input-{c}-fallback-transverse-spacing",
                "Entered transverse leg spacing", LENGTH_MM,
                ROLE_USER_INPUT, INPUT_SOURCE,
            ))
    material_leaves = [
        rows.add(concrete_leaf_id(shape.concrete_material_id, name),
                 f"Assigned concrete {name}",
                 STRESS if name.startswith("f") else ONE,
                 ROLE_METHOD_VALUE, shape.concrete_source)
        for name, _ in shape.concrete_values
    ]
    material_vector = rows.add(
        "material-vector", "Immutable concrete material assignment", ONE,
        ROLE_COMPUTED, GEOMETRY_SOURCE, *material_leaves,
    )
    normalised = rows.add(
        "normalised-transverse-inputs", "Complete transverse input identity",
        ONE, ROLE_COMPUTED, ADAPTER_SOURCE, *scalars, material_vector,
    )
    if shape.invalid:
        state = rows.add("invalid-input-state",
                         "Retained invalid transverse input", ONE,
                         ROLE_COMPUTED, VERDICT_SOURCE, normalised)
        rows.add("ct-008-transverse-links-result",
                 "CT-008 transverse-link status", ONE, ROLE_FINAL,
                 VERDICT_SOURCE, normalised, state)
        return tuple(rows.rows)
    r_source = ratio_source(shape.edition)
    leg_area = rows.add("link-leg-area", "One link leg area", AREA_MM2,
                        ROLE_COMPUTED, GEOMETRY_SOURCE, "input-link-diameter")
    coefficient = rows.add("minimum-ratio-coefficient",
                           "Minimum-ratio coefficient", ONE,
                           ROLE_METHOD_VALUE, r_source)
    factor = rows.add("ductility-factor", "Ductility reduction factor", ONE,
                      ROLE_COMPUTED, r_source, "input-edition",
                      "input-ductility-class",
                      "input-apply-ductility-reduction")
    minimum = rows.add("minimum-ratio", "Minimum transverse ratio", ONE,
                       ROLE_COMPUTED, r_source, coefficient,
                       concrete_leaf_id(shape.concrete_material_id, "fck"),
                       "input-link-fywk", factor)
    adapter_steps = []
    for direction in shape.directions:
        c = direction.component
        _direction_steps(rows, direction)
        adapter_steps.extend((
            f"shear-{c}-evidence", f"shear-{c}-links-required",
            f"shear-{c}-detailing-depth",
        ))
        if direction.legs_from:
            adapter_steps.append(f"shear-{c}-legs")
    for index, tube in enumerate(shape.tubes):
        _tube_steps(rows, index, tube)
        adapter_steps.append(f"torsion-tube-{index:02d}-evidence")
    status_ids, util_ids = [], []
    for row in shape.rows:
        status_id, util_id = _row_steps(rows, shape, row)
        status_ids.append(status_id)
        if util_id is not None:
            util_ids.append(util_id)
    status = rows.add(
        "transverse-status", "Retained transverse detailing status", ONE,
        ROLE_COMPUTED, VERDICT_SOURCE,
        *(status_ids if status_ids else (normalised, minimum)),
    )
    governing = []
    if shape.governing_present:
        governing.append(rows.add("governing-utilisation",
                                  "Governing check utilisation", ONE,
                                  ROLE_COMPUTED, VERDICT_SOURCE, *util_ids))
        governing.append(rows.add("governing-check", "Governing check index",
                                  ONE, ROLE_COMPUTED, VERDICT_SOURCE,
                                  *util_ids))
    rows.add("ct-008-transverse-links-result", "CT-008 transverse-link status",
             ONE, ROLE_FINAL, VERDICT_SOURCE, normalised, minimum, leg_area,
             *adapter_steps, status, *governing)
    return tuple(rows.rows)


def _member(member_id, calculation_id, axes, specs):
    return TraceMemberContract(
        member_id=member_id, calculation_id=calculation_id,
        coverage_id=COVERAGE_ID, method_id=METHOD_ID, axes=axes,
        sources=frozenset(TraceSourceContract(s.source.kind, s.source.method_id,
                                              s.source.edition) for s in specs),
        result_states=frozenset({RESULT_FINITE}),
        step_ids=tuple(s.step_id for s in specs),
        step_dependencies=tuple((s.step_id, s.dependencies) for s in specs),
        step_metadata=tuple(TraceStepMetadataContract(
            s.step_id, s.quantity_role, s.source
        ) for s in specs),
    )


def expected_registry(shape: DetailingShape) -> TraceRegistryContract:
    members = []
    if shape.clear is not None:
        members.append(_member(
            CLEAR_MEMBER_ID, shape.clear.calculation_id, shape.clear.axes,
            expected_clear_steps(shape.clear),
        ))
    if shape.transverse is not None:
        members.append(_member(
            TRANSVERSE_MEMBER_ID, shape.transverse.calculation_id,
            shape.transverse.axes, expected_transverse_steps(shape.transverse),
        ))
    if not members:
        raise ValueError("CT-008 registry needs at least one applicable member")
    return TraceRegistryContract(
        REGISTRY_ID, (TraceFamilyContract(FAMILY_ID, tuple(members)),)
    )
