"""Frozen CT-006 core identity, payload inventories, and trace registry."""

from __future__ import annotations

from dataclasses import dataclass

from .calculation_trace import (
    RESULT_FAILED, RESULT_FINITE, ROLE_COMPUTED, ROLE_FINAL, ROLE_METHOD_VALUE,
    ROLE_USER_INPUT, SOURCE_INPUT, SOURCE_PROJECT, SOURCE_STANDARD, SourceCitation,
    TraceAxis, TraceSource, TraceUnit, trace_identity_token,
)
from .section_trace_blocks import MaterialBlock, SectionTraceBlocks
from .trace_registry import (
    TraceFamilyContract, TraceMemberContract, TraceRegistryContract,
    TraceSourceContract, TraceStepMetadataContract,
)


COVERAGE_ID = "ct-006"
FAMILY_ID = "ct-006-directional-shear-core"
REGISTRY_ID = "sector-ct-006-directional-shear-core-v1"
METHOD_ID = "sector-directional-shear-core-replay"
DIRECTIONS = ("vx", "vy")
PHYSICAL_AXES = {"vx": "y", "vy": "x"}
CORE_INPUT_KEYS = (
    "section", "outer", "holes", "bars", "tendons", "concrete", "steel", "prestress",
    "bar_elements", "bar_materials", "mild_material_catalog",
    "P_pl", "Mx_pl", "My_pl", "shear_on", "shear_method", "shear_Vx", "shear_Vy",
    "shear_components", "shear_face_x", "shear_face_y", "shear_vx_bw", "shear_vy_bw",
    "shear_links")
LINK_INPUT_KEYS = (
    "shear_vx_link_legs", "shear_vy_link_legs", "shear_link_dia", "shear_link_s",
    "shear_fywk", "strut_cot_min", "strut_cot_max", "capacity_steel_material_id")

DOC_BASE = "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010"
DOC_DK = "DS/EN 1992-1-1 DK NA:2024"
BASE_EDITION = DOC_BASE
DK_EDITION = f"{DOC_BASE} with {DOC_DK}"

INPUT_SOURCE = TraceSource(SOURCE_INPUT, "sector-section-input")
GEOMETRY_SOURCE = TraceSource(SOURCE_PROJECT, "sector-shear-geometry")
SELECTOR_SOURCE = TraceSource(SOURCE_PROJECT, "sector-shear-minimax-selector")
VERDICT_SOURCE = TraceSource(SOURCE_PROJECT, "sector-demand-resistance-verdict")
BASE_CONCRETE_SOURCE = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2004-shear-without-links", BASE_EDITION,
    SourceCitation(DOC_BASE, "6.2.2(1)", "Formulae (6.2.a) and (6.2.b)"))
BASE_LINK_SOURCE = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2004-variable-strut-shear", BASE_EDITION,
    SourceCitation(DOC_BASE, "6.2.3", "Formulae (6.8) and (6.9)"))
BASE_VMIN_SOURCE = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2004-shear-vmin", BASE_EDITION,
    SourceCitation(DOC_BASE, "6.2.2(1)", "Formula (6.3N)"))
BASE_NU_SOURCE = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2004-shear-nu1", BASE_EDITION,
    SourceCitation(DOC_BASE, "6.2.2(6)", "Formula (6.6N)"))
BASE_ALPHA_SOURCE = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2004-shear-alpha-cw", BASE_EDITION,
    SourceCitation(DOC_BASE, "6.2.3(3)", "Formula (6.11N)"))
DK_VMIN_SOURCE = TraceSource(
    SOURCE_STANDARD, "dk-na-2024-shear-vmin", DK_EDITION,
    SourceCitation(DOC_DK, "6.2.2(1)", "national v_min value"))
DK_NU_SOURCE = TraceSource(
    SOURCE_STANDARD, "dk-na-2024-pure-shear-nu-v", DK_EDITION,
    SourceCitation(DOC_DK, "5.101 NA and 5.103 NA", "nu_v for truss struts"))

ONE = TraceUnit("1", "scalar")
LENGTH = TraceUnit("m", "length")
LENGTH_MM = TraceUnit("mm", "length")
AREA = TraceUnit("m2", "area")
AREA_MM2 = TraceUnit("mm2", "area")
FORCE = TraceUnit("kN", "force")
MOMENT = TraceUnit("kNm", "moment")
STRESS = TraceUnit("MPa", "stress")
LINE_AREA = TraceUnit("mm2/mm", "length")
ANGLE = TraceUnit("degrees", "angle")

# Ordered raw-input and candidate-output inventories. Excluded keys may be absent
# or carry arbitrary values; they are removed before the retained-order check.
COMPONENT_KEYS = ("signed_v_ed", "v_ed", "axis", "face", "active")
AGGREGATE_KEYS = ("directions", "active_directions")
AGGREGATE_EXCLUDED = frozenset(("biaxial", "note"))
SHEAR_KEYS = (
    "res", "v_ed", "util", "component", "axis", "tension_low", "face_mode",
    "bw", "bw_auto", "bw_user", "d", "asl", "asl_bar_ids", "asl_cg", "ac",
    "fck", "n_ed", "n_prestress", "n_ed_comp", "m_prestress", "centroid",
    "method", "model_2023")
SHEAR_EXCLUDED = frozenset(("m_ed_2023", "ddg", "fyd_flex"))
DIRECTION_SUFFIX_KEYS = (
    "both_faces_evaluated", "governing_face", "associated_moment",
    "associated_moment_origin", "signed_v_ed", "status", "governing_domains",
    "face_candidates")
CONCRETE_RESULT_KEYS = (
    "vrd_c", "k", "rho_l", "sigma_cp", "fcd", "v_basic", "v_floor",
    "crd_c", "vmin", "k1", "gamma_c", "valid")
LINK_KEYS = (
    "res", "util", "asw", "asw_over_s", "legs", "dia", "s", "fywk",
    "cot_min", "cot_max", "cot_limit_lo", "cot_limit_hi", "angle_limits",
    "model_2023", "z_source", "out_of_limits", "required", "theta_mode")
LINK_EXCLUDED = frozenset((
    "delta_ftd", "longitudinal_shear_force", "longitudinal_shear_symbol",
    "longitudinal_shear_clause", "chord", "chord_off", "chord_candidates"))
LINK_RESULT_KEYS = (
    "vrd_s", "vrd_max", "vrd", "cot", "theta_deg", "z", "fywd", "nu1",
    "alpha_cw", "sigma_cp", "fcd", "gamma_s", "asw_over_s", "governs",
    "valid")
ANGLE_LIMIT_KEYS = (
    "minimum", "maximum", "basis", "ductility_class", "ductility_factor",
    "axial_tension_applied", "compression_extension_credited", "clause")
FACE_WRAPPER_KEYS = ("tension_low", "shear_status", "shear_metric", "shear")
FACE_WRAPPER_EXCLUDED = frozenset((
    "torsion_status", "torsion_metric", "min_reinf_status", "min_reinf_metric",
    "combined_status", "combined_metric", "torsion", "combined"))
GOVERNING_SHEAR_KEYS = ("face", "cot", "status", "util")
GOVERNING_DOMAIN_EXCLUDED = frozenset(("vt", "minimum_reinforcement", "combined"))


@dataclass(frozen=True, slots=True)
class DirectionShape:
    blocks: SectionTraceBlocks
    direction: str
    face_mode: str
    faces: tuple[bool, ...]
    links: bool
    failed: bool
    method_variant: str
    link_steel_material_id: str
    link_steel_source: TraceSource | None
    calculation_id: str
    axes: tuple[TraceAxis, ...]

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

def _token(value: str) -> str:
    return trace_identity_token(value)

def material_prefix(material: MaterialBlock) -> str:
    return f"material-{material.kind}-{_token(material.element_id)}-{_token(material.material_id)}"

def material_leaf_id(material: MaterialBlock, name: str) -> str:
    return f"{material_prefix(material)}-{_token(name)}"

def _shared_inputs(rows: _Rows, shape: DirectionShape) -> str:
    leaves: list[str] = []
    for name in ("P_pl", "Mx_pl", "My_pl"):
        leaves.append(rows.add(
            f"input-action-{_token(name)}", f"Original action {name}",
            FORCE if name == "P_pl" else MOMENT, ROLE_USER_INPUT, INPUT_SOURCE,
        ))
    for direction in DIRECTIONS:
        for suffix, unit in (("scalar-signed", FORCE), ("component-signed", FORCE),
                             ("component-absolute", FORCE), ("active", ONE),
                             ("axis-code", ONE), ("face-code", ONE)):
            leaves.append(rows.add(
                f"input-{direction}-{suffix}", f"{direction} {suffix}", unit,
                ROLE_USER_INPUT, INPUT_SOURCE,
            ))
    leaves.extend((
        rows.add("input-shear-enabled", "Directional shear enabled", ONE,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        rows.add("input-method-code", "Selected shear method", ONE,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        rows.add("input-links-enabled", "Shear links enabled", ONE,
                 ROLE_USER_INPUT, INPUT_SOURCE),
        rows.add("input-width-override", "Entered directional web-width override",
                 LENGTH_MM, ROLE_USER_INPUT, INPUT_SOURCE),
    ))

    geometry_leaves: list[str] = []
    for ring_index, ring in enumerate(shape.blocks.geometry.rings):
        for point_index, _ in enumerate(ring):
            prefix = f"geometry-ring-{ring_index:03d}-point-{point_index:04d}"
            geometry_leaves.extend((
                rows.add(f"{prefix}-x", "Concrete vertex x", LENGTH,
                         ROLE_USER_INPUT, INPUT_SOURCE),
                rows.add(f"{prefix}-y", "Concrete vertex y", LENGTH,
                         ROLE_USER_INPUT, INPUT_SOURCE),
            ))
    for kind, elements in (("bar", shape.blocks.geometry.bars),
                           ("tendon", shape.blocks.geometry.tendons)):
        for index, _ in enumerate(elements):
            prefix = f"geometry-{kind}-{index:04d}"
            geometry_leaves.extend((
                rows.add(f"{prefix}-x", f"{kind} x", LENGTH, ROLE_USER_INPUT, INPUT_SOURCE),
                rows.add(f"{prefix}-y", f"{kind} y", LENGTH, ROLE_USER_INPUT, INPUT_SOURCE),
                rows.add(f"{prefix}-area", f"{kind} area", AREA, ROLE_USER_INPUT, INPUT_SOURCE),
            ))
    geometry = rows.add("geometry-vector", "Immutable section geometry", ONE,
                        ROLE_COMPUTED, GEOMETRY_SOURCE, *geometry_leaves)

    material_leaves: list[str] = []
    for material in (shape.blocks.concrete, *shape.blocks.bars, *shape.blocks.tendons):
        for name, _ in material.values:
            material_leaves.append(rows.add(
                material_leaf_id(material, name), f"Assigned {material.kind} {name}",
                STRESS if name.startswith("f") or name == "Es" else ONE,
                ROLE_METHOD_VALUE, material.provenance.source,
            ))
    if shape.links:
        material_leaves.append(rows.add(
            "input-link-steel-gamma-y", "Link steel yield partial factor", ONE,
            ROLE_METHOD_VALUE, shape.link_steel_source,
        ))
    materials = rows.add("material-vector", "Immutable material assignments", ONE,
                         ROLE_COMPUTED, GEOMETRY_SOURCE, *material_leaves)

    if shape.links:
        for step_id, title, unit in (
            ("input-link-legs", "Entered directional link legs", ONE),
            ("input-link-diameter", "Entered link diameter", LENGTH_MM),
            ("input-link-spacing", "Entered link spacing", LENGTH_MM),
            ("input-link-fywk", "Entered link characteristic yield", STRESS),
            ("input-cot-min", "Entered minimum cotangent", ONE),
            ("input-cot-max", "Entered maximum cotangent", ONE),
        ):
            leaves.append(rows.add(step_id, title, unit, ROLE_USER_INPUT, INPUT_SOURCE))
    return rows.add(
        "normalised-shear-inputs", "Complete CT-006 core input identity", ONE,
        ROLE_COMPUTED, SELECTOR_SOURCE, *leaves, geometry, materials,
    )

def _face_contract(rows: _Rows, shape: DirectionShape, index: int) -> str:
    p = f"face-{index:02d}"
    axis_step = f"input-{shape.direction}-axis-code"
    area = rows.add(f"{p}-area", "Gross concrete area", AREA, ROLE_COMPUTED,
                    GEOMETRY_SOURCE, "geometry-vector")
    cx = rows.add(f"{p}-centroid-x", "Concrete centroid x", LENGTH, ROLE_COMPUTED,
                  GEOMETRY_SOURCE, "geometry-vector")
    cy = rows.add(f"{p}-centroid-y", "Concrete centroid y", LENGTH, ROLE_COMPUTED,
                  GEOMETRY_SOURCE, "geometry-vector")
    prestress = rows.add(f"{p}-prestress", "Locked tendon axial force", FORCE,
                         ROLE_COMPUTED, GEOMETRY_SOURCE, "geometry-vector", "material-vector")
    m_prestress = rows.add(f"{p}-m-prestress", "Locked tendon associated moment", MOMENT,
                           ROLE_COMPUTED, GEOMETRY_SOURCE, axis_step, "geometry-vector", "material-vector")
    action_m = "input-action-u4d795f706c" if shape.direction == "vx" else "input-action-u4d785f706c"
    centroid = cx if shape.direction == "vx" else cy
    moment = rows.add(f"{p}-associated-moment", "Centroidal associated moment", MOMENT,
                      ROLE_COMPUTED, GEOMETRY_SOURCE, action_m,
                      "input-action-u505f706c", centroid, m_prestress)
    face = rows.add(f"{p}-identity", "Resolved physical shear face", ONE,
                    ROLE_COMPUTED, GEOMETRY_SOURCE,
                    axis_step, f"input-{shape.direction}-face-code", moment)
    bw_auto = rows.add(f"{p}-bw-auto", "Derived minimum solid web width", LENGTH_MM,
                       ROLE_COMPUTED, GEOMETRY_SOURCE, axis_step, "geometry-vector")
    bw = rows.add(f"{p}-bw-effective", "Effective web width", LENGTH_MM,
                  ROLE_COMPUTED, GEOMETRY_SOURCE, "input-width-override", bw_auto)
    asl = rows.add(f"{p}-asl", "Selected longitudinal tension steel", AREA_MM2,
                   ROLE_COMPUTED, GEOMETRY_SOURCE, axis_step, "geometry-vector", face, centroid)
    depth = rows.add(f"{p}-effective-depth", "Effective shear depth", LENGTH_MM,
                     ROLE_COMPUTED, GEOMETRY_SOURCE, axis_step, "geometry-vector", face, asl)
    n_comp = rows.add(f"{p}-compression-positive-axial", "Compression-positive axial force",
                      FORCE, ROLE_COMPUTED, GEOMETRY_SOURCE,
                      "input-action-u505f706c", prestress)

    concrete = shape.blocks.concrete
    fck = material_leaf_id(concrete, "fck")
    gamma_c = material_leaf_id(concrete, "gamma_c")
    alpha_cc = material_leaf_id(concrete, "alpha_cc")
    fcd = rows.add(f"{p}-fcd", "Concrete design strength", STRESS, ROLE_COMPUTED,
                   concrete.provenance.source, fck, gamma_c, alpha_cc)
    k = rows.add(f"{p}-k", "Shear size factor", ONE, ROLE_COMPUTED,
                 BASE_CONCRETE_SOURCE, depth)
    rho = rows.add(f"{p}-rho-l", "Longitudinal reinforcement ratio", ONE,
                   ROLE_COMPUTED, BASE_CONCRETE_SOURCE, asl, bw, depth)
    sigma = rows.add(f"{p}-sigma-cp", "Capped axial compression stress", STRESS,
                     ROLE_COMPUTED, BASE_CONCRETE_SOURCE, n_comp, area, fcd)
    crdc = rows.add(f"{p}-crd-c", "Concrete shear coefficient", ONE,
                    ROLE_COMPUTED, BASE_CONCRETE_SOURCE, gamma_c)
    k1 = rows.add(f"{p}-k1", "Axial shear coefficient", ONE, ROLE_METHOD_VALUE,
                  BASE_CONCRETE_SOURCE)
    vmin_source = DK_VMIN_SOURCE if shape.method_variant == "dk" else BASE_VMIN_SOURCE
    vmin = rows.add(f"{p}-vmin", "Minimum concrete shear stress", STRESS,
                    ROLE_COMPUTED, vmin_source, k, fck, gamma_c)
    basic = rows.add(f"{p}-v-basic", "Basic concrete shear stress", STRESS,
                     ROLE_COMPUTED, BASE_CONCRETE_SOURCE, crdc, k, rho, fck, k1, sigma)
    floor = rows.add(f"{p}-v-floor", "Minimum concrete shear stress with axial term", STRESS,
                     ROLE_COMPUTED, BASE_CONCRETE_SOURCE, vmin, k1, sigma)
    vrdc = rows.add(f"{p}-vrd-c", "Concrete shear resistance", FORCE,
                    ROLE_COMPUTED, BASE_CONCRETE_SOURCE, basic, floor, bw, depth)
    cutil = rows.add(f"{p}-concrete-utilisation", "Concrete-only utilisation", ONE,
                     ROLE_COMPUTED, VERDICT_SOURCE,
                     f"input-{shape.direction}-component-absolute", vrdc)
    cverdict = rows.add(f"{p}-concrete-verdict", "Concrete-only PASS or FAIL", ONE,
                        ROLE_COMPUTED, VERDICT_SOURCE, face, cutil)
    concrete_evidence = rows.add(f"{p}-concrete-evidence", "Complete concrete shear evidence",
                                 ONE, ROLE_COMPUTED, VERDICT_SOURCE,
                                 k, rho, sigma, crdc, k1, vmin, basic, floor, vrdc,
                                 cutil, cverdict, moment)

    overall = concrete_evidence
    if shape.links:
        asw = rows.add(f"{p}-asw", "Link area", AREA_MM2, ROLE_COMPUTED,
                       GEOMETRY_SOURCE, "input-link-legs", "input-link-diameter")
        asw_s = rows.add(f"{p}-asw-over-s", "Link area per spacing", LINE_AREA,
                         ROLE_COMPUTED, GEOMETRY_SOURCE, asw, "input-link-spacing")
        z = rows.add(f"{p}-z", "Retained shear lever arm", LENGTH_MM, ROLE_COMPUTED,
                     GEOMETRY_SOURCE, axis_step, depth, face, "geometry-vector", "material-vector",
                     "input-action-u505f706c")
        fywd = rows.add(f"{p}-fywd", "Link design yield", STRESS, ROLE_COMPUTED,
                        shape.link_steel_source, "input-link-fywk", "input-link-steel-gamma-y")
        nu_source = DK_NU_SOURCE if shape.method_variant == "dk" else BASE_NU_SOURCE
        nu = rows.add(f"{p}-nu1", "Compression-strut effectiveness", ONE,
                      ROLE_COMPUTED, nu_source, fck)
        link_sigma = rows.add(f"{p}-link-sigma-cp", "Mean axial compression stress", STRESS,
                              ROLE_COMPUTED, BASE_ALPHA_SOURCE, n_comp, area)
        alpha = rows.add(f"{p}-alpha-cw", "Compression-chord coefficient", ONE,
                         ROLE_COMPUTED, BASE_ALPHA_SOURCE, link_sigma, fcd)
        selector_operands = rows.add(
            f"{p}-selector-operands", "Complete shear-only selector operands", ONE,
            ROLE_COMPUTED, SELECTOR_SOURCE,
            f"input-{shape.direction}-component-absolute",
            asw_s, z, fywd, nu, alpha, bw,
            fcd, "input-cot-min", "input-cot-max",
        )
        cot = rows.add(f"{p}-cot", "1,501-point minimax cotangent", ONE,
                       ROLE_COMPUTED, SELECTOR_SOURCE, selector_operands)
        theta = rows.add(f"{p}-theta", "Compression-strut angle", ANGLE,
                         ROLE_COMPUTED, SELECTOR_SOURCE, cot)
        vrds = rows.add(f"{p}-vrd-s", "Link yielding resistance", FORCE,
                        ROLE_COMPUTED, BASE_LINK_SOURCE, asw_s, z, fywd, cot)
        vrdmax = rows.add(f"{p}-vrd-max", "Compression-strut resistance", FORCE,
                          ROLE_COMPUTED, BASE_LINK_SOURCE, alpha, bw, z, nu, fcd, cot)
        vrd = rows.add(f"{p}-vrd-links", "Governing linked shear resistance", FORCE,
                       ROLE_COMPUTED, BASE_LINK_SOURCE, vrds, vrdmax)
        util = rows.add(f"{p}-links-utilisation", "Linked shear utilisation", ONE,
                        ROLE_COMPUTED, VERDICT_SOURCE,
                        f"input-{shape.direction}-component-absolute", vrd)
        verdict = rows.add(f"{p}-links-verdict", "Linked shear PASS or FAIL", ONE,
                           ROLE_COMPUTED, VERDICT_SOURCE, face, util)
        required = rows.add(f"{p}-links-required", "Links required by concrete screen", ONE,
                            ROLE_COMPUTED, VERDICT_SOURCE,
                            f"input-{shape.direction}-component-absolute", vrdc)
        overall = rows.add(f"{p}-links-evidence", "Complete linked shear evidence", ONE,
                           ROLE_COMPUTED, VERDICT_SOURCE, asw, asw_s, z, fywd, nu,
                           link_sigma, alpha, cot, theta, vrds, vrdmax, vrd, util,
                           verdict, required, concrete_evidence)
    evidence = (overall,) if overall == concrete_evidence else (overall, concrete_evidence)
    return rows.add(f"{p}-complete-evidence", "Complete face evidence", ONE,
                    ROLE_COMPUTED, VERDICT_SOURCE, face, cx, cy, *evidence)

def expected_step_contract(shape: DirectionShape) -> tuple[StepSpec, ...]:
    rows = _Rows()
    normal = _shared_inputs(rows, shape)
    if shape.failed:
        failure = rows.add("authoritative-failure-state", "Explicit shear reconstruction failure",
                           ONE, ROLE_COMPUTED, SELECTOR_SOURCE, normal)
        rows.add("ct-006-direction-result", "CT-006 failed direction result", ONE,
                 ROLE_FINAL, VERDICT_SOURCE, normal, failure)
        return tuple(rows.rows)
    faces = tuple(_face_contract(rows, shape, index) for index in range(len(shape.faces)))
    governing = rows.add("direction-governing-face", "Independently governing face", ONE,
                         ROLE_COMPUTED, VERDICT_SOURCE, *faces)
    util = rows.add("direction-utilisation", "Governing directional utilisation", ONE,
                    ROLE_COMPUTED, VERDICT_SOURCE, *faces)
    verdict = rows.add("direction-verdict", "Directional PASS or FAIL", ONE,
                       ROLE_COMPUTED, VERDICT_SOURCE, *faces)
    rows.add("ct-006-direction-result", "Complete CT-006 direction result", ONE,
             ROLE_FINAL, VERDICT_SOURCE, normal, *faces, governing, util, verdict)
    return tuple(rows.rows)

def expected_registry(shapes: tuple[DirectionShape, ...]) -> TraceRegistryContract:
    members = []
    for shape in shapes:
        specs = expected_step_contract(shape)
        members.append(TraceMemberContract(
            member_id=shape.direction,
            calculation_id=shape.calculation_id,
            coverage_id=COVERAGE_ID,
            method_id=METHOD_ID,
            axes=shape.axes,
            sources=frozenset(TraceSourceContract(s.source.kind, s.source.method_id,
                                                  s.source.edition) for s in specs),
            result_states=frozenset({RESULT_FAILED if shape.failed else RESULT_FINITE}),
            step_ids=tuple(s.step_id for s in specs),
            step_dependencies=tuple((s.step_id, s.dependencies) for s in specs),
            step_metadata=tuple(TraceStepMetadataContract(
                s.step_id, s.quantity_role, s.source
            ) for s in specs),
        ))
    return TraceRegistryContract(
        REGISTRY_ID, (TraceFamilyContract(FAMILY_ID, tuple(members)),)
    )
