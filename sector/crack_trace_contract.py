"""Exact CT-009 crack-width member, source, and payload contracts."""

from __future__ import annotations

from dataclasses import dataclass

from .calculation_trace import (
    RESULT_FAILED,
    RESULT_FINITE,
    RESULT_UNDEFINED,
    SOURCE_INPUT,
    SOURCE_PROJECT,
    SOURCE_STANDARD,
    SourceCitation,
    TraceCalculation,
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
METHOD_ID = "sector-retained-ec2-2004-crack-width-replay"
REGISTRY_ID = "sector-ct-009-crack-width-2004-v1"

CASE_LONG_FINE = "long-fine"
CASE_SHORT_FINE = "short-fine"
CASE_LONG_COARSE = "long-coarse"
CASE_SHORT_COARSE = "short-coarse"
CASE_ORDER = (
    CASE_LONG_FINE,
    CASE_SHORT_FINE,
    CASE_LONG_COARSE,
    CASE_SHORT_COARSE,
)
CASE_OUTPUT_KEYS = {
    CASE_LONG_FINE: "crack",
    CASE_SHORT_FINE: "crack_short",
    CASE_LONG_COARSE: "crack_coarse",
    CASE_SHORT_COARSE: "crack_short_coarse",
}
CASE_LABELS = {
    CASE_LONG_FINE: "Long-term (fine)",
    CASE_SHORT_FINE: "Short-term (fine)",
    CASE_LONG_COARSE: "Long-term (coarse)",
    CASE_SHORT_COARSE: "Short-term (coarse)",
}

BASE_ELASTIC_KEYS = (
    "total", "long", "dif", "rst1", "max_conc", "max_conc_xy",
    "max_conc_point", "na_x", "na_y", "max_steel", "max_steel_bar",
    "max_steel_type", "max_steel_element", "prestress", "converged",
    "stress_plane", "elements", "concrete_corners", "stress_outputs",
    "cracked", "lambda_cr", "sigma_ct", "fctm", "show_cw", "props_un",
    "props_cr", "crack", "crack_short",
)
CALCULATED_META_KEYS = ("crack_code", "crack_edition", "crack_member")
COARSE_KEYS = ("crack_coarse", "crack_short_coarse")
AGGREGATE_KEY = "crack_output"

CRACK_RESULT_KEYS = (
    "wk", "sr_max", "esm_ecm", "sigma_s", "rho_p_eff", "ac_eff",
    "hc_ef", "phi", "cover", "gov_bar", "element_type", "element_no",
    "element_id", "coarse", "edition", "kw", "k1_r", "kfl",
    "sr_max_geometric", "candidates",
)
CRACK_CANDIDATE_KEYS = (
    "element_type", "element_no", "element_id", "x_mm", "y_mm",
    "area_mm2", "wk", "sr_max", "esm_ecm", "sigma_s", "rho_p_eff",
    "ac_eff", "hc_ef", "phi", "cover", "coarse", "edition", "kw",
    "k1_r", "kfl", "sr_max_geometric",
)
AGGREGATE_KEYS = ("value", "case", "governing", "unit", "calculation_state")
ELEMENT_KEYS = (
    "element_type", "element_no", "element_id", "material_id",
    "material_name", "x_mm", "y_mm", "area_mm2", "strain_permille",
    "total_mpa", "long_mpa", "dif_mpa", "rst1_mpa",
)

INPUT = TraceSource(SOURCE_INPUT, "sector-crack-width-input")
IDENTITY = TraceSource(SOURCE_PROJECT, "sector-crack-width-identity")
CT005 = TraceSource(SOURCE_PROJECT, "ct-005-elastic-response")
LONG_REPLAY = TraceSource(
    SOURCE_PROJECT, "sector-long-term-cracked-state-replay")
SELECTOR = TraceSource(SOURCE_PROJECT, "sector-crack-width-selector")

DOC_BASE = "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010"
DOC_DK = "DS/EN 1992-1-1 DK NA:2024, revision 2024-02-01"


def _standard(method: str, clause: str, locator: str) -> TraceSource:
    return TraceSource(
        SOURCE_STANDARD,
        method,
        DOC_BASE,
        SourceCitation(DOC_BASE, clause, locator),
    )


def _dk(method: str, clause: str, locator: str) -> TraceSource:
    return TraceSource(
        SOURCE_STANDARD,
        method,
        DOC_DK,
        SourceCitation(DOC_DK, clause, locator),
    )


EFFECTIVE_AREA = _standard(
    "en1992-1-1-2004-effective-tension-area", "7.3.2(3)", "Figure 7.1")
MEAN_STRAIN = _standard(
    "en1992-1-1-2004-mean-strain-difference", "7.3.4", "Equation (7.9)")
SPACING_CLOSE = _standard(
    "en1992-1-1-2004-close-crack-spacing", "7.3.4", "Equation (7.11)")
SPACING_GEOMETRIC = _standard(
    "en1992-1-1-2004-geometric-crack-spacing", "7.3.4", "Equation (7.14)")
CRACK_WIDTH = _standard(
    "en1992-1-1-2004-crack-width", "7.3.4", "Equation (7.8)")
DK_EFFECTIVE_AREA = _dk(
    "dk-na-2024-effective-tension-area", "7.3.2(3)", "ordinary beam rule")
DK_COVER = _dk(
    "dk-na-2024-cover-dependent-k3", "7.3.4(3)", "cover coefficient")
DK_COARSE = _dk(
    "dk-na-2024-coarse-crack-system", "7.3.4(1)", "Figure 7.100 NA")

ONE = TraceUnit("1", "scalar")
LENGTH = TraceUnit("m", "length")
MM = TraceUnit("mm", "length")
AREA = TraceUnit("m2", "area")
AREA_MM2 = TraceUnit("mm2", "area")
STRESS = TraceUnit("MPa", "stress")
FORCE = TraceUnit("kN", "force")
MOMENT = TraceUnit("kNm", "moment")
RAW_STRESS = TraceUnit("kN/m2", "stress")
RAW_GRADIENT = TraceUnit("kN/m3", "stress_gradient")
ANGLE = TraceUnit("deg", "angle")


@dataclass(frozen=True, slots=True)
class MemberShape:
    member_id: str
    calculation: TraceCalculation
    final_state: str


def registry_for(members: tuple[MemberShape, ...]) -> TraceRegistryContract:
    """Declare exact CT-009 members from authoritative reconstructed shapes."""

    rows = []
    for member in members:
        calculation = member.calculation
        rows.append(TraceMemberContract(
            member_id=member.member_id,
            calculation_id=calculation.calculation_id,
            coverage_id=COVERAGE_ID,
            method_id=METHOD_ID,
            axes=calculation.axes,
            sources=frozenset(
                TraceSourceContract(
                    step.source.kind, step.source.method_id,
                    step.source.edition,
                )
                for step in calculation.steps
            ),
            result_states=frozenset({member.final_state}),
            step_ids=tuple(step.step_id for step in calculation.steps),
            step_dependencies=tuple(
                (step.step_id, tuple(dep.step_id for dep in step.dependencies))
                for step in calculation.steps
            ),
            step_metadata=tuple(
                TraceStepMetadataContract(
                    step.step_id, step.quantity_role, step.source)
                for step in calculation.steps
            ),
        ))
    return TraceRegistryContract(
        REGISTRY_ID,
        (TraceFamilyContract(FAMILY_ID, tuple(rows)),),
    )


FINAL_STATES = frozenset({RESULT_FINITE, RESULT_UNDEFINED, RESULT_FAILED})
