"""Frozen CT-009 contract for the retained EC2:2004 crack-width response."""

from __future__ import annotations

from dataclasses import dataclass

from .calculation_trace import (
    RESULT_FAILED,
    RESULT_FINITE,
    RESULT_UNDEFINED,
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
)
from .trace_registry import (
    TraceFamilyContract,
    TraceMemberContract,
    TraceRegistryContract,
    TraceSourceContract,
    TraceStepMetadataContract,
)


COVERAGE_ID = "ct-009"
FAMILY_ID = "ct-009-crack-width-2004"
MEMBER_ID = "crack-width-2004-base-dk"
REGISTRY_ID = "sector-ct-009-crack-width-2004-v1"
METHOD_ID = "sector-ec2-2004-crack-width-replay"

BRANCH_CALCULATED = "calculated"
BRANCH_UNCRACKED = "uncracked"
BRANCH_NOT_APPLICABLE = "not-applicable"
BRANCH_FAILED = "failed"
BRANCHES = frozenset({
    BRANCH_CALCULATED, BRANCH_UNCRACKED, BRANCH_NOT_APPLICABLE, BRANCH_FAILED,
})

DOC_BASE = "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010"
DOC_DK = "DS/EN 1992-1-1 DK NA:2024, revision 2024-02-01"

INPUT_SOURCE = TraceSource(SOURCE_INPUT, "sector-crack-width-input")
REPLAY_SOURCE = TraceSource(SOURCE_PROJECT, "sector-retained-crack-width-replay")
AGGREGATE_SOURCE = TraceSource(SOURCE_PROJECT, "sector-crack-output-selection")
EFFECTIVE_AREA_SOURCE = TraceSource(
    SOURCE_STANDARD,
    "ec2-2004-effective-tension-area",
    DOC_BASE,
    SourceCitation(DOC_BASE, "7.3.2(3)", "Figure 7.1"),
)
MEAN_STRAIN_SOURCE = TraceSource(
    SOURCE_STANDARD,
    "ec2-2004-mean-strain-difference",
    DOC_BASE,
    SourceCitation(DOC_BASE, "7.3.4", "Equation (7.9)"),
)
SPACING_SOURCE = TraceSource(
    SOURCE_STANDARD,
    "ec2-2004-maximum-crack-spacing",
    DOC_BASE,
    SourceCitation(DOC_BASE, "7.3.4", "Equations (7.11) and (7.14)"),
)
WIDTH_SOURCE = TraceSource(
    SOURCE_STANDARD,
    "ec2-2004-characteristic-crack-width",
    DOC_BASE,
    SourceCitation(DOC_BASE, "7.3.4", "Equation (7.8)"),
)
DK_FINE_SOURCE = TraceSource(
    SOURCE_STANDARD,
    "dk-na-2004-fine-crack-system",
    DOC_DK,
    SourceCitation(DOC_DK, "7.3.4(1)", "Fine crack system"),
)
DK_COARSE_SOURCE = TraceSource(
    SOURCE_STANDARD,
    "dk-na-2004-coarse-crack-system",
    DOC_DK,
    SourceCitation(DOC_DK, "7.3.4(3)", "Figure 7.100"),
)

ONE = TraceUnit("1", "scalar")
LENGTH = TraceUnit("m", "length")
LENGTH_MM = TraceUnit("mm", "length")
AREA = TraceUnit("m2", "area")
AREA_MM2 = TraceUnit("mm2", "area")
FORCE = TraceUnit("kN", "force")
MOMENT = TraceUnit("kNm", "moment")
STRESS = TraceUnit("MPa", "stress")
STRAIN = TraceUnit("1", "strain")

ELASTIC_CORE_KEYS = (
    "total", "long", "dif", "rst1", "max_conc", "max_conc_xy",
    "max_conc_point", "na_x", "na_y", "max_steel", "max_steel_bar",
    "max_steel_type", "max_steel_element", "prestress", "converged",
    "stress_plane", "elements", "concrete_corners", "stress_outputs",
)
ELASTIC_SERVICE_KEYS = (
    "cracked", "lambda_cr", "sigma_ct", "fctm", "show_cw", "props_un",
    "props_cr", "crack", "crack_short",
)
ELASTIC_META_KEYS = ("crack_code", "crack_edition", "crack_member")
ELASTIC_DK_KEYS = ("crack_coarse", "crack_short_coarse")
ELASTIC_AGGREGATE_KEY = "crack_output"

PROPERTY_KEYS = ("area", "cx", "cy", "Ix", "Iy", "Ixy")
ELEMENT_KEYS = (
    "element_type", "element_no", "element_id", "material_id",
    "material_name", "x_mm", "y_mm", "area_mm2", "strain_permille",
    "total_mpa", "long_mpa", "dif_mpa", "rst1_mpa",
)
CORNER_KEYS = (
    "point_no", "ring", "ring_point_no", "x_mm", "y_mm",
    "strain_permille", "stress_mpa",
)
STRESS_OUTPUT_KEYS = ("concrete", "reinforcement", "prestress")
STRESS_CONCRETE_KEYS = ("value", "quantity", "unit", "calculation_state")
STRESS_ELEMENT_KEYS = (
    "value", "quantity", "unit", "governing", "element_no",
    "calculation_state",
)
CRACK_KEYS = (
    "wk", "sr_max", "esm_ecm", "sigma_s", "rho_p_eff", "ac_eff",
    "hc_ef", "phi", "cover", "gov_bar", "element_type", "element_no",
    "element_id", "coarse", "edition", "kw", "k1_r", "kfl",
    "sr_max_geometric", "candidates",
)
CANDIDATE_KEYS = (
    "element_type", "element_no", "element_id", "x_mm", "y_mm",
    "area_mm2", "wk", "sr_max", "esm_ecm", "sigma_s", "rho_p_eff",
    "ac_eff", "hc_ef", "phi", "cover", "coarse", "edition", "kw",
    "k1_r", "kfl", "sr_max_geometric",
)
AGGREGATE_KEYS = ("value", "case", "governing", "unit", "calculation_state")

ELEMENT_INPUT_KEYS = (
    "id", "kind", "x_mm", "y_mm", "area_mm2", "diameter_mm",
    "size_mode", "material_id", "fatigue_detail_id", "x", "y",
)
CATALOG_KEYS = ("version", "next_id", "items")
MILD_CATALOG_ITEM_KEYS = (
    "id", "name", "description", "preset", "curve",
    "active_in_compression", "fytk", "fyck", "futk", "eut", "gamma_y",
    "gamma_u", "gamma_E", "k", "ey0t", "ey0c", "Es",
)
PRESTRESS_CATALOG_ITEM_KEYS = (
    "id", "name", "description", "preset", "curve", "IS", "fytk",
    "futk", "eut", "gamma_y", "gamma_u", "gamma_E", "k", "ey0t", "Es",
)

BASE_CASES = ("long", "short")
DK_CASES = ("long-fine", "short-fine", "long-coarse", "short-coarse")
CASE_LABELS = {
    "long": "Long-term",
    "short": "Short-term",
    "long-fine": "Long-term (fine)",
    "short-fine": "Short-term (fine)",
    "long-coarse": "Long-term (coarse)",
    "short-coarse": "Short-term (coarse)",
}


@dataclass(frozen=True, slots=True)
class LeafSpec:
    step_id: str
    title: str
    unit: TraceUnit


@dataclass(frozen=True, slots=True)
class TraceShape:
    calculation_id: str
    axes: tuple[TraceAxis, ...]
    branch: str
    input_leaves: tuple[LeafSpec, ...]
    output_leaves: tuple[LeafSpec, ...]
    case_candidate_counts: tuple[tuple[str, int], ...]
    dk_na: bool


@dataclass(frozen=True, slots=True)
class StepSpec:
    step_id: str
    title: str
    unit: TraceUnit
    quantity_role: str
    source: TraceSource
    dependencies: tuple[str, ...] = ()


class _Rows:
    def __init__(self) -> None:
        self.rows: list[StepSpec] = []
        self.ids: set[str] = set()

    def add(self, step_id, title, unit, role, source, *dependencies):
        if step_id in self.ids:
            raise ValueError(f"duplicate CT-009 step {step_id}")
        self.ids.add(step_id)
        self.rows.append(StepSpec(
            step_id, title, unit, role, source, tuple(dependencies)
        ))
        return step_id


def _case_source(case_id: str, dk_na: bool) -> TraceSource:
    if not dk_na:
        return WIDTH_SOURCE
    return DK_COARSE_SOURCE if case_id.endswith("coarse") else DK_FINE_SOURCE


def expected_step_contract(shape: TraceShape) -> tuple[StepSpec, ...]:
    if shape.branch not in BRANCHES:
        raise ValueError("unknown CT-009 branch")
    rows = _Rows()
    inputs = [
        rows.add(leaf.step_id, leaf.title, leaf.unit, ROLE_USER_INPUT, INPUT_SOURCE)
        for leaf in shape.input_leaves
    ]
    normalised = rows.add(
        "normalised-crack-inputs",
        "Complete CT-009 original input identity",
        ONE,
        ROLE_COMPUTED,
        REPLAY_SOURCE,
        *inputs,
    )
    outputs = [
        rows.add(
            leaf.step_id, leaf.title, leaf.unit, ROLE_COMPUTED, REPLAY_SOURCE,
            normalised,
        )
        for leaf in shape.output_leaves
    ]
    output_vector = rows.add(
        "retained-elastic-output-vector",
        "Complete retained Elastic crack payload",
        ONE,
        ROLE_COMPUTED,
        REPLAY_SOURCE,
        normalised,
        *outputs,
    )

    if shape.branch == BRANCH_FAILED:
        failure = rows.add(
            "crack-reconstruction-failure",
            "Explicit non-converged crack reconstruction",
            ONE,
            ROLE_COMPUTED,
            REPLAY_SOURCE,
            normalised,
            output_vector,
        )
        rows.add(
            "ct-009-crack-width-result",
            "CT-009 failed result",
            LENGTH_MM,
            ROLE_FINAL,
            REPLAY_SOURCE,
            normalised,
            output_vector,
            failure,
        )
        return tuple(rows.rows)

    if shape.branch in {BRANCH_UNCRACKED, BRANCH_NOT_APPLICABLE}:
        state_id = (
            "uncracked-section-state"
            if shape.branch == BRANCH_UNCRACKED
            else "no-crack-candidate-state"
        )
        uncracked = rows.add(
            state_id,
            (
                "Authoritative uncracked section state"
                if shape.branch == BRANCH_UNCRACKED
                else "No applicable tension reinforcement candidate"
            ),
            ONE,
            ROLE_COMPUTED,
            REPLAY_SOURCE,
            normalised,
            output_vector,
        )
        rows.add(
            "ct-009-crack-width-result",
            "CT-009 crack width not applicable",
            LENGTH_MM,
            ROLE_FINAL,
            AGGREGATE_SOURCE,
            normalised,
            output_vector,
            uncracked,
        )
        return tuple(rows.rows)

    kt_long = rows.add(
        "method-kt-long", "Long-term load-duration coefficient kt", ONE,
        ROLE_METHOD_VALUE, MEAN_STRAIN_SOURCE,
    )
    kt_short = rows.add(
        "method-kt-short", "Short-term load-duration coefficient kt", ONE,
        ROLE_METHOD_VALUE, MEAN_STRAIN_SOURCE,
    )
    k2 = rows.add(
        "method-k2", "Bending strain-distribution coefficient k2", ONE,
        ROLE_METHOD_VALUE, SPACING_SOURCE,
    )
    k4 = rows.add(
        "method-k4", "Crack-spacing coefficient k4", ONE,
        ROLE_METHOD_VALUE, SPACING_SOURCE,
    )
    method_dependencies = [kt_long, kt_short, k2, k4]
    if shape.dk_na:
        method_dependencies.append(rows.add(
            "method-coarse-width-scale",
            "DK NA coarse-system crack-width scale",
            ONE,
            ROLE_METHOD_VALUE,
            DK_COARSE_SOURCE,
        ))

    cases = []
    for case_id, candidate_count in shape.case_candidate_counts:
        candidate_steps = []
        for index in range(candidate_count):
            prefix = f"case-{case_id}-candidate-{index:04d}"
            sigma = rows.add(
                f"{prefix}-sigma-s", "Stage II reinforcement stress", STRESS,
                ROLE_COMPUTED, REPLAY_SOURCE, normalised, output_vector,
            )
            ac_eff = rows.add(
                f"{prefix}-ac-eff", "Effective concrete tension area", AREA,
                ROLE_COMPUTED, EFFECTIVE_AREA_SOURCE, normalised, output_vector,
            )
            hc_eff = rows.add(
                f"{prefix}-hc-eff", "Effective tension height", LENGTH,
                ROLE_COMPUTED, EFFECTIVE_AREA_SOURCE, ac_eff,
            )
            rho = rows.add(
                f"{prefix}-rho-p-eff", "Effective reinforcement ratio", ONE,
                ROLE_COMPUTED, EFFECTIVE_AREA_SOURCE, ac_eff, normalised,
            )
            spacing = rows.add(
                f"{prefix}-sr-max", "Maximum crack spacing", LENGTH_MM,
                ROLE_COMPUTED, SPACING_SOURCE, hc_eff, rho, normalised,
            )
            strain = rows.add(
                f"{prefix}-esm-ecm", "Mean reinforcement-concrete strain difference",
                STRAIN, ROLE_COMPUTED, MEAN_STRAIN_SOURCE, sigma, rho,
                kt_long if case_id.startswith("long") else kt_short,
            )
            width = rows.add(
                f"{prefix}-wk", "Candidate characteristic crack width", LENGTH_MM,
                ROLE_COMPUTED, _case_source(case_id, shape.dk_na), spacing, strain,
                *method_dependencies,
            )
            candidate_steps.append(rows.add(
                f"{prefix}-complete", "Complete candidate crack evidence", ONE,
                ROLE_COMPUTED, REPLAY_SOURCE, normalised, output_vector, sigma,
                ac_eff, hc_eff, rho, spacing, strain, width,
            ))
        cases.append(rows.add(
            f"case-{case_id}-governing-width",
            f"{CASE_LABELS[case_id]} governing crack width",
            LENGTH_MM,
            ROLE_COMPUTED,
            _case_source(case_id, shape.dk_na),
            normalised,
            output_vector,
            *candidate_steps,
        ))

    aggregate = rows.add(
        "governing-crack-output",
        "Governing retained crack output",
        LENGTH_MM,
        ROLE_COMPUTED,
        AGGREGATE_SOURCE,
        output_vector,
        *cases,
    )
    rows.add(
        "ct-009-crack-width-result",
        "CT-009 EC2:2004 crack-width result",
        LENGTH_MM,
        ROLE_FINAL,
        AGGREGATE_SOURCE,
        normalised,
        output_vector,
        aggregate,
    )
    return tuple(rows.rows)


def expected_registry(shape: TraceShape) -> TraceRegistryContract:
    specs = expected_step_contract(shape)
    sources = frozenset(
        TraceSourceContract(item.source.kind, item.source.method_id, item.source.edition)
        for item in specs
    )
    result_states = {
        BRANCH_CALCULATED: frozenset({RESULT_FINITE}),
        BRANCH_UNCRACKED: frozenset({RESULT_FINITE, RESULT_UNDEFINED}),
        BRANCH_NOT_APPLICABLE: frozenset({RESULT_FINITE, RESULT_UNDEFINED}),
        BRANCH_FAILED: frozenset({RESULT_FINITE, RESULT_FAILED}),
    }[shape.branch]
    member = TraceMemberContract(
        member_id=MEMBER_ID,
        calculation_id=shape.calculation_id,
        coverage_id=COVERAGE_ID,
        method_id=METHOD_ID,
        axes=shape.axes,
        sources=sources,
        result_states=result_states,
        step_ids=tuple(item.step_id for item in specs),
        step_dependencies=tuple(
            (item.step_id, item.dependencies) for item in specs
        ),
        step_metadata=tuple(
            TraceStepMetadataContract(
                item.step_id, item.quantity_role, item.source
            )
            for item in specs
        ),
    )
    return TraceRegistryContract(
        REGISTRY_ID,
        (TraceFamilyContract(FAMILY_ID, (member,)),),
    )
