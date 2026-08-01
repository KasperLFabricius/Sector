"""Frozen CT-011 identity, retained inventories, sources, and dependency graph."""

from __future__ import annotations

from dataclasses import dataclass

from .calculation_trace import (
    RESULT_FAILED, RESULT_FINITE, ROLE_COMPUTED, ROLE_FINAL, ROLE_USER_INPUT,
    SOURCE_INPUT, SOURCE_PROJECT, SOURCE_STANDARD, SourceCitation, TraceAxis,
    TraceSource, TraceUnit, trace_identity_token,
)
from .trace_registry import (
    TraceFamilyContract, TraceMemberContract, TraceRegistryContract,
    TraceSourceContract, TraceStepMetadataContract,
)


COVERAGE_ID = "ct-011"
FAMILY_ID = "ct-011-bridge"
REGISTRY_ID = "sector-ct-011-bridge-v1"
METHOD_ID = "sector-retained-bridge-replay"
BRITTLE_MEMBER_ID = "brittle-method-b"
BOX_MEMBER_ID = "box-walls"
CRACK_MEMBER_ID = "minimum-crack-reinforcement"
ERROR_MEMBER_ID = "adapter-error"

STATUS_CODES = {"PASS": 1.0, "FAIL": 0.0}

# Frozen retained inventories (exact key order).
SUCCESS_KEYS = ("selected_standard", "scope", "calculations")
ERROR_KEYS = ("selected_standard", "scope", "calculations", "errors")
CALCULATION_ORDER = (
    "brittle_method_b", "box_walls", "minimum_crack_reinforcement",
)
BRITTLE_KEYS = ("method", "equation", "source", "selected_standard",
                "warning", "rows")
BRITTLE_ROW_KEYS = ("region_id", "m_rep_knm", "z_s_m", "f_yk_mpa",
                    "as_required_mm2", "as_provided_mm2", "utilisation",
                    "status")
BOX_KEYS = ("method", "equation", "source", "rows", "warnings")
BOX_ROW_KEYS = ("wall_id", "cot_theta", "v_ed_kn", "v_rd_max_kn",
                "t_ed_equivalent_kn", "t_rd_max_equivalent_kn",
                "utilisation", "status")
CRACK_KEYS = ("method", "equation", "source", "rows")
CRACK_ROW_KEYS = ("component", "act_mm2", "k_c", "k", "fct_eff_mpa",
                  "sigma_s_mpa", "as_provided_mm2", "restrained_shrinkage",
                  "fct_eff_used_mpa", "as_required_mm2", "utilisation",
                  "status")
SCOPE_SUCCESS = ("Independent numerical calculations only; generic "
                 "bridge-code coverage is not calculated.")
SCOPE_ERROR = "Independent numerical bridge calculations."
WALL_COMMON_COT_WARNING = (
    "Box-wall rows use different cot(theta) values; the cited method "
    "expects one common strut angle."
)
WALL_COT_RANGE_WARNING = (
    "One or more supplied cot(theta) values are outside the selected "
    "method's default range 1.0 to 2.5; the actual values were retained."
)

DOC_BASE = "DS/EN 1992-2:2005 + AC:2008"
DOC_DK = "DS/EN 1992-2 DK NA:2015"

INPUT_SOURCE = TraceSource(SOURCE_INPUT, "sector-section-input")
TABLE_SOURCE = TraceSource(SOURCE_PROJECT, "sector-bridge-table-normalisation")
VERDICT_SOURCE = TraceSource(SOURCE_PROJECT, "sector-bridge-verdict")
BRITTLE_SOURCE = TraceSource(
    SOURCE_STANDARD, "en-1992-2-2005-brittle-method-b", DOC_BASE,
    SourceCitation(DOC_BASE, "6.1(109)-(110)", "Method B As,min"),
)
BOX_SOURCE = TraceSource(
    SOURCE_STANDARD, "en-1992-2-2005-box-wall-interaction", DOC_BASE,
    SourceCitation(DOC_BASE, "6.3.2(101)-(104)",
                   "including AC:2008 corrections"),
)
CRACK_SOURCE = TraceSource(
    SOURCE_STANDARD, "en-1992-2-2005-minimum-crack-reinforcement", DOC_BASE,
    SourceCitation(DOC_BASE, "7.3.2(102)-(105)", "Expression (7.1)"),
)
DK_WARNING_SOURCE = TraceSource(
    SOURCE_STANDARD, "dk-na-2015-brittle-method-selection", DOC_DK,
    SourceCitation(DOC_DK, "6.1", "brittle-failure method selection"),
)

ONE = TraceUnit("1", "scalar")
AREA_MM2 = TraceUnit("mm2", "area")
MOMENT_KNM = TraceUnit("kNm", "moment")
FORCE_KN = TraceUnit("kN", "force")
STRESS = TraceUnit("MPa", "stress")
LENGTH_M = TraceUnit("m", "length")


@dataclass(frozen=True, slots=True)
class BrittleShape:
    standard: str
    dk_selected: bool
    region_ids: tuple[str, ...]
    calculation_id: str
    axes: tuple[TraceAxis, ...]


@dataclass(frozen=True, slots=True)
class BoxShape:
    wall_ids: tuple[str, ...]
    calculation_id: str
    axes: tuple[TraceAxis, ...]


@dataclass(frozen=True, slots=True)
class CrackShape:
    components: tuple[str, ...]
    calculation_id: str
    axes: tuple[TraceAxis, ...]


@dataclass(frozen=True, slots=True)
class ErrorShape:
    standard: str
    message: str
    calculation_id: str
    axes: tuple[TraceAxis, ...]


@dataclass(frozen=True, slots=True)
class BridgeShape:
    brittle: BrittleShape | None = None
    box: BoxShape | None = None
    crack: CrackShape | None = None
    error: ErrorShape | None = None


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


def region_prefix(index: int, region_id: str) -> str:
    return f"region-{index:02d}-{trace_identity_token(region_id)}"


def wall_prefix(index: int, wall_id: str) -> str:
    return f"wall-{index:02d}-{trace_identity_token(wall_id)}"


def component_prefix(index: int, component: str) -> str:
    return f"component-{index:02d}-{trace_identity_token(component)}"


def error_step_id(message: str) -> str:
    return f"adapter-error-{trace_identity_token(message)}"


def _row_leaves(rows, prefix, fields):
    return [rows.add(f"{prefix}-{suffix}", title, unit, ROLE_USER_INPUT,
                     INPUT_SOURCE)
            for suffix, title, unit in fields]


def _member_tail(rows, member, normalised, statuses, extra):
    status = rows.add(f"{member}-status", "Worst-first member status", ONE,
                      ROLE_COMPUTED, VERDICT_SOURCE, *statuses)
    rows.add(f"ct-011-{member}-result", "CT-011 member status", ONE,
             ROLE_FINAL, VERDICT_SOURCE, normalised, *extra, status)


def expected_brittle_steps(shape: BrittleShape) -> tuple[StepSpec, ...]:
    rows = _Rows()
    standard = rows.add("input-selected-standard", "Selected bridge standard",
                        ONE, ROLE_USER_INPUT, INPUT_SOURCE)
    leaves, statuses = [], []
    row_steps = []
    for index, region_id in enumerate(shape.region_ids):
        prefix = region_prefix(index, region_id)
        leaves.extend(_row_leaves(rows, prefix, (
            ("m-rep", "Entered representative moment", MOMENT_KNM),
            ("z-s", "Entered lever arm", LENGTH_M),
            ("f-yk", "Entered characteristic yield", STRESS),
            ("as-provided", "Entered provided reinforcement", AREA_MM2),
        )))
        row_steps.append(prefix)
    normalised = rows.add("normalised-bridge-inputs",
                          "Complete retained table identity", ONE,
                          ROLE_COMPUTED, TABLE_SOURCE, standard, *leaves)
    warning = rows.add(
        "dk-method-warning", "DK NA brittle-method scope warning", ONE,
        ROLE_COMPUTED,
        DK_WARNING_SOURCE if shape.dk_selected else TABLE_SOURCE, standard,
    )
    for prefix in row_steps:
        required = rows.add(f"{prefix}-as-required", "Method B As,min",
                            AREA_MM2, ROLE_COMPUTED, BRITTLE_SOURCE,
                            f"{prefix}-m-rep", f"{prefix}-z-s",
                            f"{prefix}-f-yk")
        util = rows.add(f"{prefix}-utilisation", "Row utilisation", ONE,
                        ROLE_COMPUTED, BRITTLE_SOURCE, required,
                        f"{prefix}-as-provided")
        statuses.append(rows.add(f"{prefix}-status", "Row PASS or FAIL", ONE,
                                 ROLE_COMPUTED, VERDICT_SOURCE, util))
    _member_tail(rows, BRITTLE_MEMBER_ID, normalised, statuses, (warning,))
    return tuple(rows.rows)


def expected_box_steps(shape: BoxShape) -> tuple[StepSpec, ...]:
    rows = _Rows()
    leaves, statuses, cots = [], [], []
    row_steps = []
    for index, wall_id in enumerate(shape.wall_ids):
        prefix = wall_prefix(index, wall_id)
        leaves.extend(_row_leaves(rows, prefix, (
            ("cot-theta", "Entered strut cotangent", ONE),
            ("v-ed", "Entered wall shear demand", FORCE_KN),
            ("v-rd-max", "Entered wall shear resistance", FORCE_KN),
            ("t-ed-eq", "Entered torsion-equivalent action", FORCE_KN),
            ("t-rd-max-eq", "Entered torsion-equivalent resistance", FORCE_KN),
        )))
        cots.append(f"{prefix}-cot-theta")
        row_steps.append(prefix)
    normalised = rows.add("normalised-bridge-inputs",
                          "Complete retained table identity", ONE,
                          ROLE_COMPUTED, TABLE_SOURCE, *leaves)
    common = rows.add("common-cot-warning", "Common strut-angle warning", ONE,
                      ROLE_COMPUTED, BOX_SOURCE, *cots)
    banded = rows.add("cot-range-warning", "Default cot-theta range warning",
                      ONE, ROLE_COMPUTED, BOX_SOURCE, *cots)
    for prefix in row_steps:
        util = rows.add(f"{prefix}-utilisation",
                        "Wall shear-plus-torsion utilisation", ONE,
                        ROLE_COMPUTED, BOX_SOURCE, f"{prefix}-v-ed",
                        f"{prefix}-v-rd-max", f"{prefix}-t-ed-eq",
                        f"{prefix}-t-rd-max-eq")
        statuses.append(rows.add(f"{prefix}-status", "Row PASS or FAIL", ONE,
                                 ROLE_COMPUTED, VERDICT_SOURCE, util))
    _member_tail(rows, BOX_MEMBER_ID, normalised, statuses, (common, banded))
    return tuple(rows.rows)


def expected_crack_steps(shape: CrackShape) -> tuple[StepSpec, ...]:
    rows = _Rows()
    leaves, statuses = [], []
    row_steps = []
    for index, component in enumerate(shape.components):
        prefix = component_prefix(index, component)
        leaves.extend(_row_leaves(rows, prefix, (
            ("act", "Entered tension-zone concrete area", AREA_MM2),
            ("k-c", "Entered stress-distribution coefficient", ONE),
            ("k", "Entered non-uniformity coefficient", ONE),
            ("fct-eff", "Entered effective tensile strength", STRESS),
            ("sigma-s", "Entered permitted steel stress", STRESS),
            ("as-provided", "Entered provided reinforcement", AREA_MM2),
            ("restrained", "Entered restrained-shrinkage switch", ONE),
        )))
        row_steps.append(prefix)
    normalised = rows.add("normalised-bridge-inputs",
                          "Complete retained table identity", ONE,
                          ROLE_COMPUTED, TABLE_SOURCE, *leaves)
    for prefix in row_steps:
        used = rows.add(f"{prefix}-fct-eff-used",
                        "Effective tensile strength with restrained floor",
                        STRESS, ROLE_COMPUTED, CRACK_SOURCE,
                        f"{prefix}-fct-eff", f"{prefix}-restrained")
        required = rows.add(f"{prefix}-as-required", "Expression (7.1) As,min",
                            AREA_MM2, ROLE_COMPUTED, CRACK_SOURCE,
                            f"{prefix}-act", f"{prefix}-k-c", f"{prefix}-k",
                            used, f"{prefix}-sigma-s")
        util = rows.add(f"{prefix}-utilisation", "Row utilisation", ONE,
                        ROLE_COMPUTED, CRACK_SOURCE, required,
                        f"{prefix}-as-provided")
        statuses.append(rows.add(f"{prefix}-status", "Row PASS or FAIL", ONE,
                                 ROLE_COMPUTED, VERDICT_SOURCE, util))
    _member_tail(rows, CRACK_MEMBER_ID, normalised, statuses, ())
    return tuple(rows.rows)


def expected_error_steps(shape: ErrorShape) -> tuple[StepSpec, ...]:
    rows = _Rows()
    standard = rows.add("input-selected-standard", "Selected bridge standard",
                        ONE, ROLE_USER_INPUT, INPUT_SOURCE)
    state = rows.add(error_step_id(shape.message),
                     "Retained bridge adapter error", ONE, ROLE_COMPUTED,
                     TABLE_SOURCE, standard)
    rows.add("ct-011-adapter-error-result", "CT-011 adapter error state", ONE,
             ROLE_FINAL, VERDICT_SOURCE, standard, state)
    return tuple(rows.rows)


def _member(member_id, calculation_id, axes, specs, states):
    return TraceMemberContract(
        member_id=member_id, calculation_id=calculation_id,
        coverage_id=COVERAGE_ID, method_id=METHOD_ID, axes=axes,
        sources=frozenset(TraceSourceContract(s.source.kind, s.source.method_id,
                                              s.source.edition) for s in specs),
        result_states=frozenset(states),
        step_ids=tuple(s.step_id for s in specs),
        step_dependencies=tuple((s.step_id, s.dependencies) for s in specs),
        step_metadata=tuple(TraceStepMetadataContract(
            s.step_id, s.quantity_role, s.source
        ) for s in specs),
    )


def expected_registry(shape: BridgeShape) -> TraceRegistryContract:
    members = []
    if shape.error is not None:
        members.append(_member(
            ERROR_MEMBER_ID, shape.error.calculation_id, shape.error.axes,
            expected_error_steps(shape.error), {RESULT_FAILED},
        ))
    if shape.brittle is not None:
        members.append(_member(
            BRITTLE_MEMBER_ID, shape.brittle.calculation_id,
            shape.brittle.axes, expected_brittle_steps(shape.brittle),
            {RESULT_FINITE},
        ))
    if shape.box is not None:
        members.append(_member(
            BOX_MEMBER_ID, shape.box.calculation_id, shape.box.axes,
            expected_box_steps(shape.box), {RESULT_FINITE},
        ))
    if shape.crack is not None:
        members.append(_member(
            CRACK_MEMBER_ID, shape.crack.calculation_id, shape.crack.axes,
            expected_crack_steps(shape.crack), {RESULT_FINITE},
        ))
    if not members:
        raise ValueError("CT-011 registry needs at least one applicable member")
    return TraceRegistryContract(
        REGISTRY_ID, (TraceFamilyContract(FAMILY_ID, tuple(members)),)
    )
