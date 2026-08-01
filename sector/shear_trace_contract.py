"""Exact unpublished CT-006 directional-shear trace contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

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
from .section_trace_blocks import (
    DOC_2005,
    MaterialBlock,
    SectionTraceBlocks,
    context_axes,
    context_id,
)
from .trace_registry import (
    TraceFamilyContract,
    TraceMemberContract,
    TraceRegistryContract,
    TraceSourceContract,
    TraceStepMetadataContract,
)


COVERAGE_ID = "ct-006"
REGISTRY_ID = "sector-ct-006-directional-shear-v1"
FAMILY_IDS = {
    "vx": "ct-006-directional-shear-vx",
    "vy": "ct-006-directional-shear-vy",
}
MEMBER_IDS = {key: f"directional-shear-{key}" for key in FAMILY_IDS}

BRANCH_FINITE = "finite"
BRANCH_FAILED = "failed"
BRANCHES = frozenset({BRANCH_FINITE, BRANCH_FAILED})
DIRECTION_ORDER = ("vx", "vy")
PHYSICAL_AXES = {"vx": "y", "vy": "x"}

DK_DOC = "DS/EN 1992-1-1 DK NA:2024"
DOC_2023 = "DS/EN 1992-1-1:2023"

INPUT_SOURCE = TraceSource(SOURCE_INPUT, "sector-section-input")
BASE_SHEAR_SOURCE = TraceSource(
    SOURCE_STANDARD,
    "ec2-2004-concrete-shear-resistance",
    DOC_2005,
    SourceCitation(DOC_2005, "6.2.2(1)", "Expressions (6.2.a) and (6.2.b)"),
)
BASE_LINK_SOURCE = TraceSource(
    SOURCE_STANDARD, "ec2-2004-linked-shear-resistance", DOC_2005,
    SourceCitation(DOC_2005, "6.2.3", "Expressions (6.8) and (6.9)"),
)
BASE_ANGLE_SOURCE = TraceSource(
    SOURCE_STANDARD, "ec2-2004-shear-angle-limits", DOC_2005,
    SourceCitation(DOC_2005, "6.2.3(2)", "Expression (6.7N)"),
)
BASE_LONGITUDINAL_SOURCE = TraceSource(
    SOURCE_STANDARD, "ec2-2004-longitudinal-shear-force", DOC_2005,
    SourceCitation(DOC_2005, "6.2.3(7)", "Expression (6.18)"),
)
BASE_VMIN_SOURCE = TraceSource(
    SOURCE_STANDARD,
    "ec2-2004-shear-vmin",
    DOC_2005,
    SourceCitation(DOC_2005, "6.2.2(1)", "recommended v_min"),
)
BASE_NU_SOURCE = TraceSource(
    SOURCE_STANDARD,
    "ec2-2004-shear-nu1",
    DOC_2005,
    SourceCitation(DOC_2005, "6.2.2(6)", "recommended nu1"),
)
DK_VMIN_SOURCE = TraceSource(
    SOURCE_STANDARD,
    "dk-na-2024-shear-vmin",
    DK_DOC,
    SourceCitation(DK_DOC, "6.2.2(1)", "national v_min value"),
)
DK_NU_SOURCE = TraceSource(
    SOURCE_STANDARD,
    "dk-na-2024-shear-nu-v",
    DK_DOC,
    SourceCitation(
        DK_DOC,
        "5.101 NA, 5.103 NA and 6.2.3(3)",
        "pure-shear effectiveness in truss struts",
    ),
)
# The document is locally held under published-not-implemented.  This project
# source deliberately carries neither an edition nor a standards citation.
PUBLISHED_2023_SOURCE = TraceSource(
    SOURCE_PROJECT, "published-not-implemented-2023-shear-replay"
)
SELECTOR_SOURCE = TraceSource(
    SOURCE_PROJECT, "sector-1501-point-minimax-strut-selector"
)
CHORD_SOURCE = TraceSource(
    SOURCE_PROJECT, "sector-conditional-longitudinal-chord-check"
)
VERDICT_SOURCE = TraceSource(SOURCE_PROJECT, "sector-shear-verdict")

ONE = TraceUnit("1", "scalar")
LENGTH = TraceUnit("m", "length")
LENGTH_MM = TraceUnit("mm", "length")
AREA = TraceUnit("m2", "area")
AREA_MM2 = TraceUnit("mm2", "area")
FORCE = TraceUnit("kN", "force")
MOMENT = TraceUnit("kNm", "moment")
STRESS = TraceUnit("MPa", "stress")
ANGLE = TraceUnit("degrees", "angle")
RATIO = TraceUnit("1", "utilisation")

# Exact retained candidate inventories.  Tuple order is part of CT-006 identity.
TOP_BIAXIAL_KEYS = ("directions", "active_directions", "biaxial", "note")
PAYLOAD_KEYS = (
    "res", "v_ed", "util", "component", "axis", "tension_low", "face_mode",
    "bw", "bw_auto", "bw_user", "d", "asl", "asl_bar_ids", "asl_cg", "ac",
    "fck", "n_ed", "n_prestress", "n_ed_comp", "m_ed_2023", "m_prestress",
    "centroid", "method", "model_2023", "ddg", "fyd_flex",
)
DIRECTION_SUFFIX_KEYS = (
    "both_faces_evaluated", "governing_face", "associated_moment",
    "associated_moment_origin", "signed_v_ed", "status", "governing_domains",
    "face_candidates",
)
FACE_KEYS = (
    "tension_low", "shear_status", "shear_metric", "torsion_status",
    "torsion_metric", "min_reinf_status", "min_reinf_metric", "combined_status",
    "combined_metric", "shear", "torsion", "combined",
)
CONCRETE_2005_KEYS = (
    "vrd_c", "k", "rho_l", "sigma_cp", "fcd", "v_basic", "v_floor",
    "crd_c", "vmin", "k1", "gamma_c", "valid",
)
CONCRETE_2023_KEYS = (
    "vrd_c", "tau_rdc", "tau_basic", "tau_min", "rho_l", "z", "ddg", "fyd",
    "k_vp", "d_kvp", "a_cs", "n_ed_tension", "m_ed", "v_ed", "axial_applied",
    "gamma_v", "model", "valid",
)
LINK_KEYS = (
    "res", "util", "asw", "asw_over_s", "legs", "dia", "s", "fywk",
    "cot_min", "cot_max", "delta_ftd", "longitudinal_shear_force",
    "longitudinal_shear_symbol", "longitudinal_shear_clause", "cot_limit_lo",
    "cot_limit_hi", "angle_limits", "model_2023", "z_source", "out_of_limits",
    "required", "chord", "chord_off", "chord_candidates", "theta_mode",
)
LINK_RESULT_2005_KEYS = (
    "vrd_s", "vrd_max", "vrd", "cot", "theta_deg", "z", "fywd", "nu1",
    "alpha_cw", "sigma_cp", "fcd", "gamma_s", "asw_over_s", "governs", "valid",
)
LINK_RESULT_2023_KEYS = (
    "vrd_s", "vrd_max", "vrd", "cot", "theta_deg", "z", "fywd", "nu", "nu1",
    "alpha_cw", "sigma_cp", "fcd", "gamma_s", "asw_over_s", "rho_w", "tau_ed",
    "tau_rd_sy", "tau_rd_max", "sigma_cd", "nu_fcd", "governs", "model", "valid",
)
ANGLE_LIMIT_KEYS = (
    "minimum", "maximum", "basis", "ductility_class", "ductility_factor",
    "axial_tension_applied", "compression_extension_credited", "clause",
)
CHORD_KEYS = (
    "m_ed", "m_rd", "ftd_v", "ftd_t", "z", "mv", "mt", "m_total", "util",
    "ok", "capped", "cap_shear_force", "valid", "role", "axis", "tension_low",
    "off_util", "biaxial", "m_off", "conditional", "has_torsion", "gets_shift",
    "off_not_evaluated", "theta_mode",
)
DOMAIN_KEYS = ("face", "cot", "status", "util")
CORE_INPUT_KEYS = (
    "section", "outer", "holes", "bars", "tendons", "concrete", "steel",
    "prestress", "P_pl", "Mx_pl", "My_pl", "shear_on", "shear_method",
    "shear_Vx", "shear_Vy", "shear_face_x", "shear_face_y", "shear_vx_bw",
    "shear_vy_bw", "shear_links",
)
COMPONENT_KEYS = ("signed_v_ed", "v_ed", "axis", "face", "active")
LINK_INPUT_KEYS = (
    "shear_vx_link_legs", "shear_vy_link_legs", "strut_cot_min",
    "strut_cot_max", "shear_link_dia", "shear_link_s", "shear_fywk",
    "transverse_ductility_class",
)
PUBLISHED_2023_INPUT_KEYS = ("shear_dlower",)
OPTIONAL_PROVENANCE_KEYS = (
    "concrete_preset", "mild_preset", "prestress_preset", "concrete_material_id",
    "capacity_steel_material_id", "bar_materials", "tendon_materials", "bar_elements",
    "tendon_elements", "mild_material_catalog", "prestress_material_catalog",
)


def input_key_inventory(inp: Mapping[str, object], method_branch: str, links: bool) -> tuple[str, ...]:
    keys = (*CORE_INPUT_KEYS, *(key for key in OPTIONAL_PROVENANCE_KEYS if key in inp))
    if "shear_components" in inp:
        keys += ("shear_components",)
    if links:
        keys += LINK_INPUT_KEYS
    if method_branch == "published-2023":
        keys += PUBLISHED_2023_INPUT_KEYS
    return keys


def direction_keys(links: bool) -> tuple[str, ...]:
    return PAYLOAD_KEYS + (("links",) if links else ()) + DIRECTION_SUFFIX_KEYS


@dataclass(frozen=True, slots=True)
class TraceShape:
    blocks: SectionTraceBlocks
    direction: str
    face_order: tuple[str, ...]
    face_bar_ids: tuple[tuple[int, ...], ...]
    method_branch: str
    links: bool
    branch: str
    calculation_id: str
    axes: tuple[TraceAxis, ...]


def trace_shape(
    blocks: SectionTraceBlocks,
    context: Mapping[str, object],
    *,
    direction: str,
    face_selector: str,
    face_order: tuple[str, ...],
    face_bar_ids: tuple[tuple[int, ...], ...],
    method_branch: str,
    method_label: str,
    links: bool,
    branch: str,
) -> TraceShape:
    if direction not in DIRECTION_ORDER or branch not in BRANCHES:
        raise ValueError("invalid CT-006 direction or branch")
    if face_selector not in {"auto", "negative", "positive"}:
        raise ValueError("invalid CT-006 face selector")
    if not face_order or len(face_order) != len(face_bar_ids):
        raise ValueError("CT-006 faces and selected bars must align")
    if any(face not in {"negative", "positive"} for face in face_order):
        raise ValueError("invalid CT-006 face order")
    token = context_id(context)
    axes = (
        *context_axes(context),
        TraceAxis("direction", direction),
        TraceAxis("physical-axis", PHYSICAL_AXES[direction]),
        TraceAxis("face-selector", face_selector),
        TraceAxis("face-order", "+".join(face_order)),
        TraceAxis("links", "with-links" if links else "concrete-only"),
        TraceAxis("method", method_label),
        TraceAxis("branch", branch),
    )
    return TraceShape(
        blocks=blocks,
        direction=direction,
        face_order=face_order,
        face_bar_ids=face_bar_ids,
        method_branch=method_branch,
        links=links,
        branch=branch,
        calculation_id=f"ct-006-{direction}-{token}-{branch}",
        axes=axes,
    )


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

    def add(self, step_id, title, unit, role, source, *dependencies) -> str:
        if step_id in self.ids:
            raise ValueError(f"duplicate CT-006 step {step_id}")
        self.ids.add(step_id)
        self.rows.append(
            StepSpec(step_id, title, unit, role, source, tuple(dependencies))
        )
        return step_id


def _token(value: str) -> str:
    return trace_identity_token(value)


def _material_prefix(material: MaterialBlock) -> str:
    return f"material-{material.kind}-{_token(material.element_id)}-{_token(material.material_id)}"


def material_step_id(material: MaterialBlock, name: str) -> str:
    return f"{_material_prefix(material)}-{_token(name)}"


def _material_unit(name: str) -> TraceUnit:
    if name in {"fck", "fytk", "fyck", "futk", "Es"}:
        return STRESS
    return ONE


def _shared(rows: _Rows, blocks: SectionTraceBlocks) -> str:
    leaves: list[str] = []
    for ring_index, ring in enumerate(blocks.geometry.rings):
        for point_index, _point in enumerate(ring):
            for component in ("x", "y"):
                leaves.append(rows.add(
                    f"geometry-ring-{ring_index:03d}-point-{point_index:04d}-{component}",
                    f"Geometry ring {ring_index + 1} point {point_index + 1} {component}",
                    LENGTH, ROLE_USER_INPUT, INPUT_SOURCE,
                ))
    for kind, elements in (("bar", blocks.geometry.bars), ("tendon", blocks.geometry.tendons)):
        for index, _element in enumerate(elements):
            for field, unit in (("x", LENGTH), ("y", LENGTH), ("area", AREA)):
                leaves.append(rows.add(
                    f"geometry-{kind}-{index:04d}-{field}",
                    f"{kind.title()} {index + 1} {field}", unit,
                    ROLE_USER_INPUT, INPUT_SOURCE,
                ))
    for key, _value in blocks.plastic_actions.values:
        leaves.append(rows.add(
            f"input-action-{_token(key)}", f"Requested {key}",
            FORCE if key == "P_pl" else MOMENT,
            ROLE_USER_INPUT, INPUT_SOURCE,
        ))
    for material in (blocks.concrete, *blocks.bars, *blocks.tendons):
        for name, _value in material.values:
            leaves.append(rows.add(
                material_step_id(material, name),
                f"{material.kind} {material.element_id} {name}",
                _material_unit(name), ROLE_METHOD_VALUE,
                material.provenance.source,
            ))
    return rows.add(
        "shared-section-evidence", "Immutable section input evidence", ONE,
        ROLE_COMPUTED, CHORD_SOURCE, *leaves,
    )


def _edition_source(shape: TraceShape, base: TraceSource) -> TraceSource:
    return PUBLISHED_2023_SOURCE if shape.method_branch == "published-2023" else base


def _vmin_source(shape: TraceShape) -> TraceSource:
    return DK_VMIN_SOURCE if shape.method_branch == "dk-2005" else BASE_VMIN_SOURCE


def _nu_source(shape: TraceShape) -> TraceSource:
    return DK_NU_SOURCE if shape.method_branch == "dk-2005" else BASE_NU_SOURCE


def _failure_contract(rows: _Rows, shape: TraceShape) -> None:
    ordinal = rows.add(
        "input-direction-ordinal", "Direction ordinal", ONE,
        ROLE_USER_INPUT, INPUT_SOURCE,
    )
    rows.add(
        "ct-006-direction-result", "CT-006 failed directional shear result", ONE,
        ROLE_FINAL, VERDICT_SOURCE, ordinal,
    )


def _finite_contract(rows: _Rows, shape: TraceShape) -> None:
    shared = _shared(rows, shape.blocks)
    inputs: list[str] = [shared]
    for step_id, title, unit in (
        ("input-shear-on", "Shear calculation enabled", ONE),
        ("input-signed-demand", "Original signed shear demand", FORCE),
        ("absolute-demand", "Absolute shear demand", FORCE),
        ("input-face-selector", "Original face selector code", ONE),
        ("input-width-override", "Directional web-width override", LENGTH_MM),
    ):
        inputs.append(rows.add(step_id, title, unit, ROLE_USER_INPUT, INPUT_SOURCE))
    if shape.method_branch == "published-2023":
        inputs.append(rows.add(
            "input-aggregate-lower-size", "Lower aggregate sieve size", LENGTH_MM,
            ROLE_USER_INPUT, INPUT_SOURCE,
        ))
    if shape.links:
        for step_id, title, unit in (
            ("input-link-legs", "Directional link legs", ONE),
            ("input-cot-min", "Minimum entered cotangent", ONE),
            ("input-cot-max", "Maximum entered cotangent", ONE),
            ("input-link-diameter", "Link diameter", LENGTH_MM),
            ("input-link-spacing", "Link spacing", LENGTH_MM),
            ("input-link-yield", "Characteristic link yield", STRESS),
        ):
            inputs.append(rows.add(step_id, title, unit, ROLE_USER_INPUT, INPUT_SOURCE))
        inputs.append(rows.add(
            "input-ductility-class", "Transverse ductility class code", ONE,
            ROLE_USER_INPUT, INPUT_SOURCE,
        ))
    input_evidence = rows.add(
        "direction-input-evidence", "Complete directional input evidence", ONE,
        ROLE_COMPUTED, CHORD_SOURCE, *inputs,
    )

    concrete = shape.blocks.concrete
    concrete_values = tuple(material_step_id(concrete, name) for name, _ in concrete.values)
    bar_values = tuple(
        material_step_id(item, name)
        for item in shape.blocks.bars for name, _ in item.values
    )
    method = _edition_source(shape, BASE_SHEAR_SOURCE)
    face_complete: list[str] = []
    for face_index, (face, bar_ids) in enumerate(zip(shape.face_order, shape.face_bar_ids)):
        p = f"face-{face}"
        local: list[str] = []

        def add(field, title, unit=ONE, source=CHORD_SOURCE, *deps):
            step = rows.add(f"{p}-{field}", title, unit, ROLE_COMPUTED, source, *deps)
            local.append(step)
            return step

        tlow = add("tension-low", f"{face} face identity", ONE, CHORD_SOURCE, input_evidence)
        bw_auto = add("bw-auto", "Derived minimum web width", LENGTH_MM, CHORD_SOURCE, shared)
        bw = add("bw", "Effective web width", LENGTH_MM, CHORD_SOURCE, bw_auto, "input-width-override")
        d = add("d", "Effective shear depth", LENGTH_MM, CHORD_SOURCE, shared, tlow)
        asl = add("asl", "Selected longitudinal tension steel", AREA_MM2, CHORD_SOURCE, shared, tlow)
        for selected_index, _bar_id in enumerate(bar_ids):
            add(f"asl-bar-{selected_index:03d}", "Selected longitudinal bar ID", ONE, CHORD_SOURCE, asl)
        asl_cg = add("asl-cg", "Selected tension steel centroid", LENGTH, CHORD_SOURCE, shared, tlow)
        ac = add("ac", "Gross concrete area", AREA, CHORD_SOURCE, shared)
        cx = add("centroid-x", "Concrete centroid x", LENGTH, CHORD_SOURCE, shared)
        cy = add("centroid-y", "Concrete centroid y", LENGTH, CHORD_SOURCE, shared)
        fck = add("fck", "Concrete characteristic strength", STRESS, method, *concrete_values)
        fcd = add("fcd", "Concrete design strength", STRESS, method, *concrete_values)
        gamma_c = add("gamma-c", "Final concrete factor", ONE, method, *concrete_values)
        fyd_flex = add("fyd-flex", "Flexural reinforcement design yield", STRESS, CHORD_SOURCE, *bar_values)
        n_ed = add("n-ed", "Original axial action", FORCE, CHORD_SOURCE, input_evidence)
        n_pre = add("n-prestress", "Prestress axial resultant", FORCE, CHORD_SOURCE, shared)
        n_comp = add("n-ed-comp", "Compression-positive axial action", FORCE, CHORD_SOURCE, n_ed, n_pre)
        moment = add("associated-moment", "Centroidal associated moment", MOMENT, CHORD_SOURCE, input_evidence, shared)
        moment_origin = add("moment-origin", "Origin associated moment", MOMENT, CHORD_SOURCE, input_evidence)
        m_pre = add("m-prestress", "Prestress associated moment", MOMENT, CHORD_SOURCE, shared)
        m_2023 = add("m-ed-2023", "Action-dependent shear moment", MOMENT, method, moment_origin, n_ed, cx, cy, m_pre)
        ddg = add("ddg", "Aggregate size parameter", LENGTH_MM, method, input_evidence, fck)
        add("bw-user", "User web width selected", ONE, CHORD_SOURCE, "input-width-override")
        add("model-2023", "Published 2023 method flag", ONE, method, input_evidence)

        if shape.method_branch == "published-2023":
            rho = add("rho-l", "Longitudinal reinforcement ratio", ONE, method, asl, bw, d)
            z = add("concrete-z", "Concrete shear lever arm", LENGTH_MM, method, d)
            kvp = add("k-vp", "Axial action shear factor", ONE, method, n_comp, "absolute-demand", m_2023, d)
            dkvp = add("d-kvp", "Modified shear depth", LENGTH_MM, method, kvp, d)
            acs = add("a-cs", "Action shear span", LENGTH_MM, method, m_2023, "absolute-demand", d)
            tau_basic = add("tau-basic", "Basic concrete shear stress", STRESS, method, rho, fck, ddg, dkvp, fyd_flex)
            tau_min = add("tau-min", "Minimum concrete shear stress", STRESS, method, fck, fyd_flex, ddg, d, gamma_c)
            tau = add("tau-rdc", "Governing concrete shear stress", STRESS, method, tau_basic, tau_min)
            vrd_c = add("vrd-c", "Concrete-only shear resistance", FORCE, method, tau, bw, z)
            add("gamma-v", "Published shear factor", ONE, method, input_evidence)
            add("axial-applied", "Axial action factor applied", ONE, method, n_comp, "absolute-demand")
        else:
            k = add("k", "Shear size factor", ONE, BASE_SHEAR_SOURCE, d)
            rho = add("rho-l", "Longitudinal reinforcement ratio", ONE, BASE_SHEAR_SOURCE, asl, bw, d)
            sigma = add("sigma-cp", "Capped axial concrete stress", STRESS, BASE_SHEAR_SOURCE, n_comp, ac, fcd)
            crd = add("crd-c", "Concrete shear coefficient", ONE, BASE_SHEAR_SOURCE, gamma_c)
            k1 = rows.add(
                f"{p}-k1", "Axial stress coefficient", ONE,
                ROLE_METHOD_VALUE, BASE_SHEAR_SOURCE,
            )
            local.append(k1)
            vmin = add("vmin", "Minimum shear stress", STRESS, _vmin_source(shape), k, fck, gamma_c)
            basic = add("v-basic", "Basic concrete shear stress", STRESS, BASE_SHEAR_SOURCE, crd, k, rho, fck, k1, sigma)
            floor = add("v-floor", "Minimum concrete shear branch", STRESS, BASE_SHEAR_SOURCE, vmin, k1, sigma)
            vrd_c = add("vrd-c", "Concrete-only shear resistance", FORCE, BASE_SHEAR_SOURCE, basic, floor, bw, d)
        concrete_util = add("concrete-util", "Concrete-only utilisation", RATIO, VERDICT_SOURCE, "absolute-demand", vrd_c)
        concrete_verdict = add("concrete-verdict", "Concrete-only PASS or FAIL", ONE, VERDICT_SOURCE, concrete_util)

        governing_util = concrete_util
        governing_verdict = concrete_verdict
        if shape.links:
            asw = add("asw", "Link area per spacing set", AREA_MM2, CHORD_SOURCE, "input-link-legs", "input-link-diameter")
            asw_s = add("asw-over-s", "Link area per spacing", LENGTH_MM, CHORD_SOURCE, asw, "input-link-spacing")
            z = add("links-z", "Link shear lever arm", LENGTH_MM, CHORD_SOURCE, shared, tlow, d)
            fywd = add("fywd", "Link design yield", STRESS, CHORD_SOURCE, "input-link-yield", *bar_values)
            link_method = _edition_source(shape, BASE_LINK_SOURCE)
            angle_method = _edition_source(shape, BASE_ANGLE_SOURCE)
            sigma = add("links-sigma-cp", "Mean axial concrete stress", STRESS, link_method, n_comp, ac)
            alpha = add("alpha-cw", "Compression chord factor", ONE, link_method, sigma, fcd)
            nu = add("nu1", "Compression-strut effectiveness", ONE,
                     PUBLISHED_2023_SOURCE if shape.method_branch == "published-2023" else _nu_source(shape), fck)
            cot = add("cot", "Governing shared strut cotangent", ONE, SELECTOR_SOURCE,
                      "input-cot-min", "input-cot-max", "absolute-demand", asw_s,
                      fywd, alpha, bw, z, nu, fcd, moment, shared)
            theta = add("theta", "Governing strut angle", ANGLE, SELECTOR_SOURCE, cot)
            vrd_s = add("vrd-s", "Link yielding resistance", FORCE, link_method, asw_s, fywd, z, cot)
            vrd_max = add("vrd-max", "Compression-field resistance", FORCE, link_method, alpha, bw, z, nu, fcd, cot)
            vrd = add("vrd", "Governing linked shear resistance", FORCE, link_method, vrd_s, vrd_max)
            links_util = add("links-util", "Linked shear utilisation", RATIO, VERDICT_SOURCE, "absolute-demand", vrd)
            links_verdict = add("links-verdict", "Linked shear PASS or FAIL", ONE, VERDICT_SOURCE, links_util)
            force = add("longitudinal-shear-force", "Longitudinal shear chord force", FORCE, _edition_source(shape, BASE_LONGITUDINAL_SOURCE), "absolute-demand", cot)
            required = add("links-required", "Links required by concrete resistance", ONE, VERDICT_SOURCE, "absolute-demand", vrd_c)
            add("out-of-limits", "Entered cotangent band outside assigned limits", ONE, VERDICT_SOURCE, "input-cot-min", "input-cot-max")
            add("theta-mode", "Utilisation-driven selector mode", ONE, SELECTOR_SOURCE, cot)
            add("link-legs", "Published link legs", ONE, CHORD_SOURCE, "input-link-legs")
            add("link-diameter", "Published link diameter", LENGTH_MM, CHORD_SOURCE, "input-link-diameter")
            add("link-spacing", "Published link spacing", LENGTH_MM, CHORD_SOURCE, "input-link-spacing")
            add("link-yield", "Published characteristic link yield", STRESS, CHORD_SOURCE, "input-link-yield")
            add("cot-min", "Published minimum cotangent", ONE, SELECTOR_SOURCE, "input-cot-min")
            add("cot-max", "Published maximum cotangent", ONE, SELECTOR_SOURCE, "input-cot-max")
            add("cot-limit-lo", "Assigned lower cotangent limit", ONE, angle_method, input_evidence)
            add("cot-limit-hi", "Assigned upper cotangent limit", ONE, angle_method, input_evidence)
            if shape.method_branch == "published-2023":
                rho_w = add("rho-w", "Transverse reinforcement ratio", ONE, method, asw_s, bw)
                tau_ed = add("tau-ed", "Applied shear stress", STRESS, method, "absolute-demand", bw, z)
                tau_sy = add("tau-rd-sy", "Link yielding shear stress", STRESS, method, rho_w, fywd, cot)
                tau_max = add("tau-rd-max", "Compression-field shear stress", STRESS, method, nu, fcd, cot)
                add("sigma-cd", "Compression-field demand", STRESS, method, tau_ed, cot)
                add("nu-fcd", "Compression-field strength", STRESS, method, nu, fcd)
                add("angle-min", "Assigned angle lower limit", ONE, angle_method, input_evidence)
                add("angle-max", "Assigned angle upper limit", ONE, angle_method, input_evidence)
                add("angle-ductility-factor", "Ductility angle factor", ONE, angle_method, input_evidence)
                add("angle-axial-tension", "Axial tension angle reduction", ONE, angle_method, n_comp, "absolute-demand")
                add("angle-compression-extension", "Compression extension credited", ONE, angle_method, input_evidence)
            else:
                add("angle-min", "Assigned angle lower limit", ONE, angle_method, input_evidence)
                add("angle-max", "Assigned angle upper limit", ONE, angle_method, input_evidence)
                add("angle-ductility-factor", "Ductility angle factor", ONE, angle_method, input_evidence)
                add("angle-axial-tension", "Axial tension angle reduction", ONE, angle_method, input_evidence)
                add("angle-compression-extension", "Compression extension credited", ONE, angle_method, input_evidence)

            chord_m_ed = add("chord-m-ed", "Chord bending demand", MOMENT, CHORD_SOURCE, moment, tlow)
            chord_m_rd = add("chord-m-rd", "Conditional chord bending resistance", MOMENT, CHORD_SOURCE, shared, moment, tlow)
            off_util = add("chord-off-util", "Off-axis bending utilisation", RATIO, CHORD_SOURCE, shared, moment_origin)
            biaxial = add("chord-biaxial", "Biaxial chord flag", ONE, CHORD_SOURCE, off_util)
            chord_mv = add("chord-mv", "Shear chord moment", MOMENT, CHORD_SOURCE, force, z, chord_m_ed, chord_m_rd)
            chord_total = add("chord-m-total", "Total chord moment", MOMENT, CHORD_SOURCE, chord_m_ed, chord_mv)
            chord_util = add("chord-util", "Longitudinal chord utilisation", RATIO, CHORD_SOURCE, chord_total, chord_m_rd)
            chord_verdict = add("chord-verdict", "Longitudinal chord PASS or FAIL", ONE, VERDICT_SOURCE, chord_util)
            add("chord-ftd-v", "Published chord shear force", FORCE, CHORD_SOURCE, force)
            add("chord-ftd-t", "Published zero torsion chord force", FORCE, CHORD_SOURCE, input_evidence)
            add("chord-z", "Published chord lever arm", LENGTH, CHORD_SOURCE, z)
            add("chord-mt", "Published zero torsion moment", MOMENT, CHORD_SOURCE, input_evidence)
            add("chord-capped", "Chord shear cap applied", ONE, CHORD_SOURCE, chord_mv, chord_m_rd)
            add("chord-cap-enabled", "Chord shear cap method flag", ONE, CHORD_SOURCE, input_evidence)
            add("chord-valid", "Chord solve valid", ONE, CHORD_SOURCE, chord_m_rd)
            add("chord-tension-low", "Chord face identity", ONE, CHORD_SOURCE, tlow)
            add("chord-m-off", "Chord off-axis moment", MOMENT, CHORD_SOURCE, moment_origin)
            add("chord-conditional", "Conditional chord solve flag", ONE, CHORD_SOURCE, chord_m_rd)
            add("chord-has-torsion", "Torsion excluded flag", ONE, CHORD_SOURCE, input_evidence)
            add("chord-gets-shift", "Chord receives shear shift", ONE, CHORD_SOURCE, tlow)
            add("chord-candidate-evidence", "Candidate chord representation", ONE, CHORD_SOURCE,
                chord_m_ed, chord_m_rd, off_util, biaxial, chord_util, chord_verdict)
            governing_util = links_util
            governing_verdict = links_verdict

        face_metric = add("shear-metric", "Face shear metric", RATIO, VERDICT_SOURCE, governing_util)
        face_status = add("shear-status", "Face shear verdict", ONE, VERDICT_SOURCE, governing_verdict)
        # Consume every emitted face field, including concrete-only verdict,
        # chord verdict, links-required and the linked candidate representation.
        complete = rows.add(
            f"{p}-complete-evidence", f"Complete {face} face evidence", ONE,
            ROLE_COMPUTED, VERDICT_SOURCE, *local,
        )
        face_complete.append(complete)

    direction_metric = rows.add(
        "direction-shear-metric", "Governing directional shear metric", RATIO,
        ROLE_COMPUTED, VERDICT_SOURCE, *face_complete,
    )
    governing_face = rows.add(
        "direction-governing-face", "Governing directional face", ONE,
        ROLE_COMPUTED, VERDICT_SOURCE, *face_complete,
    )
    aggregate = rows.add(
        "direction-aggregate-verdict", "Aggregate directional PASS or FAIL", ONE,
        ROLE_COMPUTED, VERDICT_SOURCE, *face_complete, direction_metric,
    )
    complete = rows.add(
        "direction-complete-evidence", "Complete directional evidence", ONE,
        ROLE_COMPUTED, VERDICT_SOURCE,
        input_evidence, *face_complete, direction_metric, governing_face, aggregate,
    )
    rows.add(
        "ct-006-direction-result", "CT-006 directional shear result", RATIO,
        ROLE_FINAL, VERDICT_SOURCE, complete, aggregate, direction_metric,
    )


def expected_step_contract(shape: TraceShape) -> tuple[StepSpec, ...]:
    rows = _Rows()
    if shape.branch == BRANCH_FAILED:
        _failure_contract(rows, shape)
    else:
        _finite_contract(rows, shape)
    return tuple(rows.rows)


def method_id(shape: TraceShape) -> str:
    if shape.method_branch == "published-2023":
        return "sector-published-not-implemented-2023-shear-replay"
    if shape.method_branch == "dk-2005":
        return "sector-ec2-2005-dkna-shear-replay"
    return "sector-ec2-2005-shear-replay"


def expected_registry(shapes: tuple[TraceShape, ...]) -> TraceRegistryContract:
    directions = tuple(shape.direction for shape in shapes)
    if directions != tuple(key for key in DIRECTION_ORDER if key in directions):
        raise ValueError("CT-006 shapes must follow exact vx then vy order")
    if len(set(directions)) != len(directions):
        raise ValueError("duplicate CT-006 direction shape")
    families = []
    for shape in shapes:
        specs = expected_step_contract(shape)
        member = TraceMemberContract(
            member_id=MEMBER_IDS[shape.direction],
            calculation_id=shape.calculation_id,
            coverage_id=COVERAGE_ID,
            method_id=method_id(shape),
            axes=shape.axes,
            sources=frozenset(
                TraceSourceContract(spec.source.kind, spec.source.method_id, spec.source.edition)
                for spec in specs
            ),
            result_states=frozenset({
                RESULT_FAILED if shape.branch == BRANCH_FAILED else RESULT_FINITE
            }),
            step_ids=tuple(spec.step_id for spec in specs),
            step_dependencies=tuple((spec.step_id, spec.dependencies) for spec in specs),
            step_metadata=tuple(
                TraceStepMetadataContract(spec.step_id, spec.quantity_role, spec.source)
                for spec in specs
            ),
        )
        families.append(TraceFamilyContract(FAMILY_IDS[shape.direction], (member,)))
    return TraceRegistryContract(REGISTRY_ID, tuple(families))
