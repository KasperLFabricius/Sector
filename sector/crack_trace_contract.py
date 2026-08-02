"""Frozen CT-009 identity, retained inventories, sources, and dependency graph.

Member design: the retained crack surface publishes per-case evidence (the
long-term and short-term crack dicts with their DK NA coarse variants) plus
one governing crack-case selection. The family therefore carries the members
``long-term`` and ``short-term`` - each owning its fine and, under the DK NA
edition, coarse variant - and the ``crack-output`` member owning the retained
governing-case selection, so every published crack surface has exactly one
owner.
"""

from __future__ import annotations

from dataclasses import dataclass

from .calculation_trace import (
    RESULT_FINITE, ROLE_COMPUTED, ROLE_FINAL, ROLE_METHOD_VALUE,
    ROLE_USER_INPUT, SOURCE_INPUT, SOURCE_PROJECT, SOURCE_STANDARD,
    SourceCitation, TraceAxis, TraceSource, TraceUnit, trace_identity_token,
)
# The CT-005 upstream planes keep their retained solver units (the concrete
# reference plane in kN/m2 with kN/m3 gradients). Single-sourced from the
# CT-005 contract so the two families can never silently diverge.
from .elastic_trace_contract import RAW_GRADIENT, RAW_STRESS
from .trace_registry import (
    TraceFamilyContract, TraceMemberContract, TraceRegistryContract,
    TraceSourceContract, TraceStepMetadataContract,
)


COVERAGE_ID = "ct-009"
FAMILY_ID = "ct-009-crack-width"
REGISTRY_ID = "sector-ct-009-crack-width-v1"
METHOD_ID = "sector-retained-crack-width-replay"
LONG_MEMBER_ID = "long-term"
SHORT_MEMBER_ID = "short-term"
OUTPUT_MEMBER_ID = "crack-output"

# Crack widths are output-only quantities (Product Identity): the encoding
# carries retained calculation states, never a PASS/FAIL verdict.
CRACK_STATE_CODES = {
    "CALCULATED": 1.0, "NOT ASSESSED": 3.0, "NOT APPLICABLE": 4.0,
    "INVALID": 5.0,
}

# Frozen retained inventories (exact key order, app _crack_dict flattening).
CRACK_KEYS = (
    "wk", "sr_max", "esm_ecm", "sigma_s", "rho_p_eff", "ac_eff", "hc_ef",
    "phi", "cover", "gov_bar", "element_type", "element_no", "element_id",
    "coarse", "edition", "kw", "k1_r", "kfl", "sr_max_geometric",
    "candidates",
)
CANDIDATE_KEYS = (
    "element_type", "element_no", "element_id", "x_mm", "y_mm", "area_mm2",
    "wk", "sr_max", "esm_ecm", "sigma_s", "rho_p_eff", "ac_eff", "hc_ef",
    "phi", "cover", "coarse", "edition", "kw", "k1_r", "kfl",
    "sr_max_geometric",
)
OUTPUT_KEYS = ("value", "case", "governing", "unit", "calculation_state")
CASE_LABELS_BASE = ("Long-term", "Short-term")
CASE_LABELS_DK = ("Long-term (fine)", "Short-term (fine)",
                  "Long-term (coarse)", "Short-term (coarse)")

DOC_2004 = "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010"
DOC_DK = "DS/EN 1992-1-1 DK NA:2024"

INPUT_SOURCE = TraceSource(SOURCE_INPUT, "sector-section-input")
ADAPTER_SOURCE = TraceSource(SOURCE_PROJECT, "sector-crack-adapter")
VERDICT_SOURCE = TraceSource(SOURCE_PROJECT, "sector-crack-verdict")
# Values genuinely read from the published, CT-005-validated elastic result.
UPSTREAM_SOURCE = TraceSource(SOURCE_PROJECT, "sector-ct-005-elastic-evidence")
# Unpublished operands (the long-case cracked state) re-derived through the
# retained kernels and cross-checked against the published CT-005 surfaces.
REPLAY_SOURCE = TraceSource(SOURCE_PROJECT,
                            "sector-crack-cross-checked-replay")
STRAIN_SOURCE = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2004-crack-mean-strain", DOC_2004,
    SourceCitation(DOC_2004, "7.3.4(1)-(2)", "Formulae (7.8)-(7.9)"),
)
SPACING_SOURCE = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2004-crack-spacing", DOC_2004,
    SourceCitation(DOC_2004, "7.3.4(3)", "Formula (7.11)"),
)
WIDE_SPACING_SOURCE = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2004-wide-crack-spacing", DOC_2004,
    SourceCitation(DOC_2004, "7.3.4(3)", "Formula (7.14)"),
)
EFFECTIVE_AREA_SOURCE = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2004-effective-tension-area", DOC_2004,
    SourceCitation(DOC_2004, "7.3.2(3)", "hc,ef effective tension zone"),
)
DK_K3_SOURCE = TraceSource(
    SOURCE_STANDARD, "dk-na-2024-cover-dependent-k3", DOC_DK,
    SourceCitation(DOC_DK, "7.3.4(3)", "k3 (25/c)^(2/3)"),
)
DK_HX_SOURCE = TraceSource(
    SOURCE_STANDARD, "dk-na-2024-hx-term-scope", DOC_DK,
    SourceCitation(DOC_DK, "7.3.2(3)", "(h-x)/3 slab/prestress scope"),
)
DK_COARSE_SOURCE = TraceSource(
    SOURCE_STANDARD, "dk-na-2024-coarse-crack-system", DOC_DK,
    SourceCitation(DOC_DK, "7.3.4(1)", "Figur 7.100 NA, wk/2"),
)

ONE = TraceUnit("1", "scalar")
MM = TraceUnit("mm", "length")
M = TraceUnit("m", "length")
M2 = TraceUnit("m2", "area")
MPA = TraceUnit("MPa", "stress")
KN = TraceUnit("kN", "force")
KNM = TraceUnit("kNm", "moment")


@dataclass(frozen=True, slots=True)
class ElementShape:
    kind: str
    element_id: str
    material_id: str


@dataclass(frozen=True, slots=True)
class CandidateShape:
    index: int  # zero-based retained bar index
    geometric: bool  # (7.14) wide-spacing branch selected


@dataclass(frozen=True, slots=True)
class VariantShape:
    coarse: bool
    status: str
    reason: str
    candidates: tuple[CandidateShape, ...]


@dataclass(frozen=True, slots=True)
class CaseShape:
    name: str  # "long-term" or "short-term"
    variants: tuple[VariantShape, ...]
    calculation_id: str
    axes: tuple[TraceAxis, ...]


@dataclass(frozen=True, slots=True)
class OutputShape:
    labels: tuple[str, ...]
    available: tuple[bool, ...]
    state: str
    calculation_id: str
    axes: tuple[TraceAxis, ...]


@dataclass(frozen=True, slots=True)
class CrackShape:
    dk: bool
    slab: bool
    has_tendons: bool
    elements: tuple[ElementShape, ...]
    cases: tuple[CaseShape, ...]
    output: OutputShape


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


def element_prefix(index: int, element: ElementShape) -> str:
    return (f"element-{index:02d}-{trace_identity_token(element.kind)}-"
            f"{trace_identity_token(element.element_id)}-"
            f"{trace_identity_token(element.material_id)}")


def disposition_id(variant: str, reason: str) -> str:
    return f"{variant}-disposition-{trace_identity_token(reason)}"


def case_label_token(label: str) -> str:
    return trace_identity_token(label)


def _case_inputs(rows, shape: CrackShape, long_case: bool):
    scalars = [
        rows.add("input-cw-enabled", "Crack-width reporting enabled", ONE,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        rows.add("input-dk-na", "DK NA crack rules selected", ONE,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        rows.add("input-edition-2004", "Retained 2004 crack edition", ONE,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        rows.add("input-fctm", "Entered SLS mean tensile strength", MPA,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        rows.add("input-phi-override", "Entered governing diameter override",
                 MM, ROLE_USER_INPUT, INPUT_SOURCE),
        rows.add("input-k1", "Entered bond coefficient", ONE,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        rows.add("input-modular-ratio", "Case modular ratio", ONE,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        rows.add("input-axial-long", "Entered long-term axial action", KN,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        rows.add("input-mx-long", "Entered long-term Mx", KNM,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        rows.add("input-my-long", "Entered long-term My", KNM,
                 ROLE_USER_INPUT, INPUT_SOURCE),
    ]
    if shape.dk:
        scalars.append(rows.add("input-member-type", "Selected SLS member type",
                                ONE, ROLE_USER_INPUT, INPUT_SOURCE))
    if shape.has_tendons:
        scalars.append(rows.add("input-tendon-xi", "Entered tendon bond ratio",
                                ONE, ROLE_USER_INPUT, INPUT_SOURCE))
    if not long_case:
        for suffix, title, unit in (("axial-short", "Entered short-term axial",
                                     KN), ("mx-short", "Entered short-term Mx",
                                           KNM),
                                    ("my-short", "Entered short-term My", KNM)):
            scalars.append(rows.add(f"input-{suffix}", title, unit,
                                    ROLE_USER_INPUT, INPUT_SOURCE))
    element_leaves = []
    for index, element in enumerate(shape.elements):
        prefix = element_prefix(index, element)
        for suffix, title, unit in (("es", "Assigned reinforcement modulus",
                                     MPA), ("diameter", "Crack diameter used",
                                            MM),
                                    ("k1", "Element bond coefficient", ONE)):
            element_leaves.append(rows.add(f"{prefix}-{suffix}", title, unit,
                                           ROLE_METHOD_VALUE, ADAPTER_SOURCE))
        if element.kind == "tendon":
            element_leaves.append(rows.add(
                f"{prefix}-is", "Assigned tendon initial strain", ONE,
                ROLE_METHOD_VALUE, ADAPTER_SOURCE))
    # Upstream binding: the short-term case reads the PUBLISHED CT-005
    # surfaces (stress_plane, total element stresses) and carries the
    # upstream-evidence source. The long-term cracked state at nl/beta 0.5 is
    # not published; it is re-derived through the retained kernels,
    # cross-checked against every published CT-005 surface, and truthfully
    # labeled as project replay - never as upstream evidence.
    plane_source = REPLAY_SOURCE if long_case else UPSTREAM_SOURCE
    plane_title = ("Cross-checked long-case cracked-plane"
                   if long_case else "CT-005 published cracked-plane")
    stress_title = ("Cross-checked long-case element stress"
                    if long_case else "CT-005 published element stress")
    upstream = [
        rows.add(f"upstream-plane-{name}", f"{plane_title} {name}",
                 unit, ROLE_METHOD_VALUE, plane_source)
        for name, unit in (("eps0", RAW_STRESS), ("kx", RAW_GRADIENT),
                           ("ky", RAW_GRADIENT))
    ]
    for index, element in enumerate(shape.elements):
        upstream.append(rows.add(
            f"upstream-{element_prefix(index, element)}-stress",
            stress_title, MPA, ROLE_METHOD_VALUE, plane_source))
    normalised = rows.add("normalised-crack-inputs",
                          "Complete crack-case input identity", ONE,
                          ROLE_COMPUTED, ADAPTER_SOURCE, *scalars,
                          *element_leaves, *upstream)
    return normalised


def _variant_steps(rows, shape: CrackShape, variant: VariantShape,
                   normalised: str, long_case: bool):
    v = "coarse" if variant.coarse else "fine"
    area_source = DK_COARSE_SOURCE if variant.coarse else (
        DK_HX_SOURCE if shape.dk and not shape.slab and not shape.has_tendons
        else EFFECTIVE_AREA_SOURCE)
    planes = ("upstream-plane-eps0", "upstream-plane-kx", "upstream-plane-ky")
    stress_leaves = tuple(
        f"upstream-{element_prefix(index, element)}-stress"
        for index, element in enumerate(shape.elements))
    if variant.status != "CALCULATED":
        state = rows.add(disposition_id(v, variant.reason),
                         "Retained crack-scope disposition", ONE,
                         ROLE_COMPUTED, VERDICT_SOURCE, normalised, *planes)
        return rows.add(f"{v}-state", "Retained variant calculation state",
                        ONE, ROLE_COMPUTED, VERDICT_SOURCE, state)
    # hc,ef derives from the section geometry (normalised inputs), the
    # bending plane and the effective-depth operands: the deepest tension
    # element selected from the retained upstream element stresses.
    hc = rows.add(f"{v}-hc-ef", "Effective tension height", M, ROLE_COMPUTED,
                  area_source, normalised, *planes, *stress_leaves)
    # Ac,eff clips and sums the section rings: on non-rectangular or holed
    # sections hc,ef alone does not determine it, so the normalised section
    # geometry is a direct operand.
    ac = rows.add(f"{v}-ac-eff", "Effective tension area", M2, ROLE_COMPUTED,
                  area_source, normalised, hc)
    # rho_p,eff = As,eff / Ac,eff: the in-band reinforcement set comes from
    # the normalised element inventory, the band from Ac,eff.
    rho = rows.add(f"{v}-rho-p-eff", "Effective reinforcement ratio", ONE,
                   ROLE_COMPUTED, area_source, normalised, ac)
    wks = []
    for candidate in variant.candidates:
        element = shape.elements[candidate.index]
        prefix = element_prefix(candidate.index, element)
        c = f"{v}-candidate-{candidate.index:02d}"
        # The short case forms the load-induced stress from the PUBLISHED
        # total: for tendons the locked-in prestress (Es * IS) is stripped,
        # so the assigned modulus and initial strain are true operands.
        sigma_deps = [f"upstream-{prefix}-stress"]
        if not long_case and element.kind == "tendon":
            sigma_deps += [f"{prefix}-es", f"{prefix}-is"]
        sigma = rows.add(f"{c}-sigma-s", "Stage II steel stress", MPA,
                         ROLE_COMPUTED, STRAIN_SOURCE, *sigma_deps)
        # Clear cover derives from the section geometry (normalised inputs)
        # and the used diameter (element diameter or the global override).
        cover = rows.add(f"{c}-cover", "Clear cover used", MM, ROLE_COMPUTED,
                         ADAPTER_SOURCE, normalised, f"{prefix}-diameter",
                         "input-phi-override")
        esm = rows.add(f"{c}-esm-ecm", "Mean strain difference", ONE,
                       ROLE_COMPUTED, STRAIN_SOURCE, sigma, rho,
                       "input-fctm", "input-modular-ratio", f"{prefix}-es")
        spacing_source = WIDE_SPACING_SOURCE if candidate.geometric else (
            DK_K3_SOURCE if shape.dk else SPACING_SOURCE)
        spacing_deps = ((cover, normalised, *planes) if candidate.geometric
                        else (cover, f"{prefix}-diameter", f"{prefix}-k1",
                              rho))
        sr = rows.add(f"{c}-sr-max", "Maximum crack spacing", MM,
                      ROLE_COMPUTED, spacing_source, *spacing_deps)
        wk_source = DK_COARSE_SOURCE if variant.coarse else STRAIN_SOURCE
        wks.append(rows.add(f"{c}-wk", "Candidate crack width", MM,
                            ROLE_COMPUTED, wk_source, sr, esm))
    governing = rows.add(f"{v}-governing", "Governing candidate index", ONE,
                         ROLE_COMPUTED, VERDICT_SOURCE, *wks)
    wk = rows.add(f"{v}-wk", "Variant governing crack width", MM,
                  ROLE_COMPUTED, VERDICT_SOURCE, governing, *wks)
    return rows.add(f"{v}-state", "Retained variant calculation state", ONE,
                    ROLE_COMPUTED, VERDICT_SOURCE, wk)


def expected_case_steps(shape: CrackShape, case: CaseShape) -> tuple[StepSpec, ...]:
    rows = _Rows()
    long_case = case.name == "long-term"
    normalised = _case_inputs(rows, shape, long_case)
    states = [_variant_steps(rows, shape, variant, normalised, long_case)
              for variant in case.variants]
    rows.add(f"ct-009-{case.name}-result", "CT-009 crack-case state", ONE,
             ROLE_FINAL, VERDICT_SOURCE, normalised, *states)
    return tuple(rows.rows)


def expected_output_steps(shape: CrackShape) -> tuple[StepSpec, ...]:
    rows = _Rows()
    scalars = [
        rows.add("input-cw-enabled", "Crack-width reporting enabled", ONE,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        rows.add("input-dk-na", "DK NA crack rules selected", ONE,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        rows.add("upstream-converged", "CT-005 SLS convergence state", ONE,
                 ROLE_METHOD_VALUE, UPSTREAM_SOURCE),
    ]
    available_leaves, wk_steps = [], []
    for label, available in zip(shape.output.labels, shape.output.available):
        token = case_label_token(label)
        leaf = rows.add(f"case-{token}-available", "Retained case availability",
                        ONE, ROLE_COMPUTED, ADAPTER_SOURCE, *scalars)
        available_leaves.append(leaf)
        if available:
            wk_steps.append(rows.add(f"case-{token}-wk",
                                     "Retained case crack width", MM,
                                     ROLE_COMPUTED, ADAPTER_SOURCE, leaf))
    governing = rows.add("governing-case", "Retained governing crack case",
                         ONE, ROLE_COMPUTED, VERDICT_SOURCE,
                         *(wk_steps if wk_steps else available_leaves))
    rows.add("ct-009-crack-output-result", "CT-009 crack output state", ONE,
             ROLE_FINAL, VERDICT_SOURCE, *scalars, *available_leaves,
             *wk_steps, governing)
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


def expected_registry(shape: CrackShape) -> TraceRegistryContract:
    members = []
    for case in shape.cases:
        member_id = (LONG_MEMBER_ID if case.name == "long-term"
                     else SHORT_MEMBER_ID)
        members.append(_member(member_id, case.calculation_id, case.axes,
                               expected_case_steps(shape, case)))
    members.append(_member(OUTPUT_MEMBER_ID, shape.output.calculation_id,
                           shape.output.axes, expected_output_steps(shape)))
    return TraceRegistryContract(
        REGISTRY_ID, (TraceFamilyContract(FAMILY_ID, tuple(members)),)
    )
