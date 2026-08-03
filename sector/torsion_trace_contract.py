"""Frozen CT-007 identity, output inventories, sources, and dependency graph."""

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


COVERAGE_ID = "ct-007"
FAMILY_ID = "ct-007-thin-wall-torsion"
REGISTRY_ID = "sector-ct-007-thin-wall-torsion-v1"
METHOD_ID = "sector-thin-wall-torsion-replay"

CORE_INPUT_KEYS = (
    "section", "outer", "holes", "tendons", "concrete", "steel", "concrete_preset",
    "mild_material_catalog", "capacity_steel_material_id", "P_pl",
    "shear_on", "shear_links", "combined_on",
    "torsion_on", "torsion_method", "torsion_nu_v", "torsion_gamma_ct",
    "torsion_T", "torsion_subdivide", "shear_link_dia", "shear_link_s",
    "shear_fywk", "strut_cot_min", "strut_cot_max",
)
TENDON_INPUT_KEYS = (
    "tendons", "tendon_elements", "tendon_materials",
    "prestress_material_catalog",
)

DOC_BASE = "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010"
DOC_DK = "DS/EN 1992-1-1 DK NA:2024"
BASE_EDITION = DOC_BASE
DK_EDITION = f"{DOC_BASE} with {DOC_DK}"

INPUT_SOURCE = TraceSource(SOURCE_INPUT, "sector-section-input")
GEOMETRY_SOURCE = TraceSource(SOURCE_PROJECT, "sector-torsion-geometry")
SELECTOR_SOURCE = TraceSource(SOURCE_PROJECT, "sector-torsion-minimax-selector")
VERDICT_SOURCE = TraceSource(SOURCE_PROJECT, "sector-demand-resistance-verdict")
STIFFNESS_SOURCE = TraceSource(SOURCE_PROJECT, "sector-rectangle-torsion-stiffness")
CRACK_SOURCE = TraceSource(SOURCE_PROJECT, "sector-torsion-cracking-resistance")
TUBE_SOURCE = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2004-thin-wall-torsion-tube", BASE_EDITION,
    SourceCitation(DOC_BASE, "6.3.2(1)", "thin-walled closed-tube idealisation"),
)
DISTRIBUTION_SOURCE = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2004-torsion-distribution", BASE_EDITION,
    SourceCitation(DOC_BASE, "6.3.1(4)", "torsional-stiffness distribution"),
)
TRANSVERSE_SOURCE = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2004-transverse-torsion", BASE_EDITION,
    SourceCitation(
        DOC_BASE,
        "6.3.2(1) and 6.2.3(3)",
        "Formulae (6.27) and (6.8)",
    ),
)
CRUSHING_SOURCE = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2004-torsion-crushing", BASE_EDITION,
    SourceCitation(DOC_BASE, "6.3.2(4)", "Formula (6.30)"),
)
LONGITUDINAL_SOURCE = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2004-longitudinal-torsion", BASE_EDITION,
    SourceCitation(DOC_BASE, "6.3.2(3)", "Formula (6.28)"),
)
TENSILE_SOURCE = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2004-concrete-tensile-strength", BASE_EDITION,
    SourceCitation(DOC_BASE, "3.1.2(6)", "Table 3.1"),
)
ALPHA_SOURCE = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2004-shear-alpha-cw", BASE_EDITION,
    SourceCitation(DOC_BASE, "6.2.3(3)", "Formula (6.11N)"),
)
BASE_NU_SOURCE = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2004-torsion-nu", BASE_EDITION,
    SourceCitation(DOC_BASE, "6.2.2(6)", "Formula (6.6N) used by 6.30"),
)
BASE_ANGLE_SOURCE = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2004-torsion-angle-limits", BASE_EDITION,
    SourceCitation(DOC_BASE, "6.2.3(2)", "Formula (6.7N)"),
)
DK_ANGLE_SOURCE = TraceSource(
    SOURCE_STANDARD, "dk-na-2024-torsion-angle-limits", DK_EDITION,
    SourceCitation(DOC_DK, "6.2.3(2)", "Formula (6.7a NA)"),
)
DK_NU_T_SOURCE = TraceSource(
    SOURCE_STANDARD, "dk-na-2024-pure-torsion-nu-t", DK_EDITION,
    SourceCitation(DOC_DK, "5.104 NA", "nu_t for pure torsion"),
)
DK_NU_DETAIL_SOURCE = TraceSource(
    SOURCE_STANDARD, "dk-na-2024-detailed-torsion-nu-v", DK_EDITION,
    SourceCitation(DOC_DK, "5.103 NA and Figur 5.100 NA", "nu_v detailing allowance"),
)

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
STIFFNESS = TraceUnit("m4", "torsion_stiffness")

TOP_KEYS = (
    "tube", "trd_s", "trd_max", "trd", "trd_c", "cot", "theta_deg",
    "util", "asl_req", "t_ed", "fcd", "fywd", "fyd_long", "nu",
    "alpha_cw", "fctd", "fctk_005", "gamma_c", "gamma_ct", "gamma_s",
    "nu_v_detailing", "sigma_cp", "n_prestress", "asw_t", "asw_over_s",
    "dia", "s", "cot_min", "cot_max", "method", "governs", "valid",
    "reason", "cot_limit_lo", "cot_limit_hi", "out_of_limits", "subdivided",
    "subtubes", "primary", "governing_sub", "compound_detected",
    "subdivision_requested", "subdivision_valid", "subdivision_reason",
    "theta_mode",
)
TOP_EXCLUDED = frozenset((
    "min_reinf", "interaction", "directional_interactions",
    "directional_interaction_status", "directional_governing_face",
    "directional_governing_cot", "directional_min_reinf_status",
    "directional_min_reinf_governing_face",
))
TUBE_KEYS = (
    "A", "u", "tef", "Ak", "uk", "tef_auto", "tef_capped", "tef_user",
    "hollow", "minimum_dimension_mm", "valid", "reason",
)
RESULT_KEYS = (
    "tube", "t_ed", "trd_s", "trd_max", "trd", "trd_c", "cot",
    "theta_deg", "util", "asl_req", "nu", "governs", "valid",
)
SUBTUBE_SUFFIX_KEYS = ("stiffness", "x_mm", "y_mm", "b_mm", "h_mm")


@dataclass(frozen=True, slots=True)
class TorsionShape:
    blocks: SectionTraceBlocks
    capacity_steel: MaterialBlock
    tube_count: int
    subdivided: bool
    zero_demand: bool
    failed: bool
    method_variant: str
    nu_detail_applied: bool
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


def _inputs(rows: _Rows, shape: TorsionShape) -> str:
    leaves = []
    for step_id, title, unit in (
        ("input-torsion-enabled", "Torsion check enabled", ONE),
        ("input-method-code", "Selected torsion method", ONE),
        ("input-demand", "Absolute torsion demand", MOMENT),
        ("input-axial-force", "Original axial action", FORCE),
        ("input-nu-detailing", "Entered closed-detailing allowance", ONE),
        ("input-gamma-ct", "Entered tensile partial factor", ONE),
        ("input-link-diameter", "Entered closed-link diameter", LENGTH_MM),
        ("input-link-spacing", "Entered closed-link spacing", LENGTH_MM),
        ("input-link-fywk", "Entered link characteristic yield", STRESS),
        ("input-cot-min", "Entered first cotangent bound", ONE),
        ("input-cot-max", "Entered second cotangent bound", ONE),
        ("input-subdivision-enabled", "Entered subdivision switch", ONE),
        ("input-shear-enabled", "Retained shear check enabled", ONE),
        ("input-shear-links-enabled", "Retained shear links enabled", ONE),
        ("input-combined-enabled", "Retained combined check enabled", ONE),
    ):
        leaves.append(rows.add(step_id, title, unit, ROLE_USER_INPUT, INPUT_SOURCE))
    if not shape.subdivided:
        leaves.append(rows.add(
            "input-tef-override", "Entered effective-thickness override",
            LENGTH_MM, ROLE_USER_INPUT, INPUT_SOURCE,
        ))
    if shape.subdivided:
        for index in range(shape.tube_count):
            for suffix, unit in (("x", LENGTH_MM), ("y", LENGTH_MM),
                                 ("b", LENGTH_MM), ("h", LENGTH_MM)):
                leaves.append(rows.add(
                    f"input-tube-{index:02d}-{suffix}",
                    f"Entered sub-tube {index + 1} {suffix}", unit,
                    ROLE_USER_INPUT, INPUT_SOURCE,
                ))

    geometry_leaves = []
    for ring_index, ring in enumerate(shape.blocks.geometry.rings):
        for point_index, _ in enumerate(ring):
            prefix = f"geometry-ring-{ring_index:03d}-point-{point_index:04d}"
            geometry_leaves.extend((
                rows.add(f"{prefix}-x", "Concrete vertex x", LENGTH,
                         ROLE_USER_INPUT, INPUT_SOURCE),
                rows.add(f"{prefix}-y", "Concrete vertex y", LENGTH,
                         ROLE_USER_INPUT, INPUT_SOURCE),
            ))
    for index, _ in enumerate(shape.blocks.geometry.tendons):
        prefix = f"geometry-tendon-{index:04d}"
        geometry_leaves.extend((
            rows.add(f"{prefix}-x", "Tendon x", LENGTH, ROLE_USER_INPUT, INPUT_SOURCE),
            rows.add(f"{prefix}-y", "Tendon y", LENGTH, ROLE_USER_INPUT, INPUT_SOURCE),
            rows.add(f"{prefix}-area", "Tendon area", AREA, ROLE_USER_INPUT, INPUT_SOURCE),
        ))
    geometry = rows.add("geometry-vector", "Immutable torsion geometry", ONE,
                        ROLE_COMPUTED, GEOMETRY_SOURCE, *geometry_leaves)

    materials = (shape.blocks.concrete, shape.capacity_steel, *shape.blocks.tendons)
    material_leaves = []
    for material in materials:
        for name, _ in material.values:
            material_leaves.append(rows.add(
                material_leaf_id(material, name), f"Assigned {material.kind} {name}",
                STRESS if name.startswith("f") or name == "Es" else ONE,
                ROLE_METHOD_VALUE, material.provenance.source,
            ))
    material_vector = rows.add(
        "material-vector", "Immutable torsion material assignments", ONE,
        ROLE_COMPUTED, GEOMETRY_SOURCE, *material_leaves,
    )
    return rows.add(
        "normalised-torsion-inputs", "Complete CT-007 input identity", ONE,
        ROLE_COMPUTED, SELECTOR_SOURCE, *leaves, geometry, material_vector,
    )


def _common(rows: _Rows, shape: TorsionShape) -> dict[str, str]:
    concrete, steel = shape.blocks.concrete, shape.capacity_steel
    fck = material_leaf_id(concrete, "fck")
    gamma_c = material_leaf_id(concrete, "gamma_c")
    alpha_cc = material_leaf_id(concrete, "alpha_cc")
    gamma_s = material_leaf_id(steel, "gamma_y")
    fytk = material_leaf_id(steel, "fytk")
    fcd = rows.add("concrete-fcd", "Concrete design strength", STRESS,
                   ROLE_COMPUTED, concrete.provenance.source, fck, gamma_c, alpha_cc)
    fctm = rows.add("concrete-fctm", "Mean concrete tensile strength", STRESS,
                    ROLE_COMPUTED, TENSILE_SOURCE, fck)
    fctk = rows.add("concrete-fctk-005", "Five-percent tensile strength", STRESS,
                    ROLE_COMPUTED, TENSILE_SOURCE, fctm)
    fctd = rows.add("concrete-fctd", "Concrete design tensile strength", STRESS,
                    ROLE_COMPUTED, TENSILE_SOURCE, fctk, "input-gamma-ct")
    fywd = rows.add("link-fywd", "Closed-link design yield", STRESS,
                    ROLE_COMPUTED, steel.provenance.source,
                    "input-link-fywk", gamma_s)
    fyd = rows.add("longitudinal-fyd", "Longitudinal design yield", STRESS,
                   ROLE_COMPUTED, steel.provenance.source, fytk, gamma_s)
    asw = rows.add("closed-link-area", "One closed-link leg area", AREA_MM2,
                   ROLE_COMPUTED, GEOMETRY_SOURCE, "input-link-diameter")
    asw_s = rows.add("closed-link-ratio", "Closed-link area per spacing", LINE_AREA,
                     ROLE_COMPUTED, GEOMETRY_SOURCE, asw, "input-link-spacing")

    tendon_forces = []
    for index, material in enumerate(shape.blocks.tendons):
        tendon_forces.append(rows.add(
            f"tendon-{index:02d}-locked-force", "Locked tendon force", FORCE,
            ROLE_COMPUTED, GEOMETRY_SOURCE,
            f"geometry-tendon-{index:04d}-area",
            material_leaf_id(material, "Es"), material_leaf_id(material, "IS"),
        ))
    prestress = rows.add(
        "prestress-axial", "Locked tendon axial force", FORCE,
        ROLE_COMPUTED, GEOMETRY_SOURCE,
        *(tendon_forces if tendon_forces else ("geometry-vector",)),
    )
    n_comp = rows.add("compression-positive-axial", "Compression-positive axial force",
                      FORCE, ROLE_COMPUTED, GEOMETRY_SOURCE,
                      "input-axial-force", prestress)
    area = rows.add("net-concrete-area", "Net concrete area", AREA,
                    ROLE_COMPUTED, GEOMETRY_SOURCE, "geometry-vector")
    sigma = rows.add("mean-compression-stress", "Mean compression stress", STRESS,
                     ROLE_COMPUTED, ALPHA_SOURCE, n_comp, area)
    alpha = rows.add("alpha-cw", "Compression-chord coefficient", ONE,
                     ROLE_COMPUTED, ALPHA_SOURCE, sigma, fcd)
    detail_applied = rows.add(
        "nu-detailing-applied", "DK closed-detailing allowance applied", ONE,
        ROLE_COMPUTED, SELECTOR_SOURCE, "input-method-code", "input-nu-detailing",
    )
    if shape.method_variant == "dk":
        nu_source = DK_NU_DETAIL_SOURCE if shape.nu_detail_applied else DK_NU_T_SOURCE
    else:
        nu_source = BASE_NU_SOURCE
    nu = rows.add("torsion-nu", "Torsion strut effectiveness", ONE,
                  ROLE_COMPUTED, nu_source, fck, detail_applied)
    lo = rows.add("cot-band-low", "Normalised lower cotangent bound", ONE,
                  ROLE_COMPUTED, SELECTOR_SOURCE, "input-cot-min", "input-cot-max")
    hi = rows.add("cot-band-high", "Normalised upper cotangent bound", ONE,
                  ROLE_COMPUTED, SELECTOR_SOURCE, "input-cot-min", "input-cot-max")
    angle_source = DK_ANGLE_SOURCE if shape.method_variant == "dk" else BASE_ANGLE_SOURCE
    limit_lo = rows.add("method-cot-limit-low", "Method lower cotangent limit", ONE,
                        ROLE_METHOD_VALUE, angle_source)
    limit_hi = rows.add("method-cot-limit-high", "Method upper cotangent limit", ONE,
                        ROLE_METHOD_VALUE, angle_source)
    outside = rows.add("cot-outside-method-range", "Bounds outside method range", ONE,
                       ROLE_COMPUTED, SELECTOR_SOURCE, lo, hi, limit_lo, limit_hi)
    rectangle_inputs = tuple(
        f"input-tube-{index:02d}-{suffix}"
        for index in range(shape.tube_count) for suffix in ("x", "y", "b", "h")
    ) if shape.subdivided else ()
    compound = rows.add("compound-outline", "Compound concrete outline detected", ONE,
                        ROLE_COMPUTED, GEOMETRY_SOURCE, "geometry-vector")
    subdivision_valid = rows.add(
        "subdivision-valid", "Sub-tubes exactly partition concrete", ONE,
        ROLE_COMPUTED, GEOMETRY_SOURCE, "geometry-vector",
        "input-subdivision-enabled", *rectangle_inputs,
    )
    subdivision_applied = rows.add(
        "subdivision-applied", "Validated subdivision applied", ONE,
        ROLE_COMPUTED, GEOMETRY_SOURCE,
        "input-subdivision-enabled", subdivision_valid,
    )
    return dict(fck=fck, fcd=fcd, fctd=fctd, fctk=fctk, fywd=fywd, fyd=fyd,
                asw=asw, asw_s=asw_s, prestress=prestress, area=area, sigma=sigma,
                alpha=alpha, detail_applied=detail_applied, nu=nu, lo=lo, hi=hi,
                outside=outside, compound=compound,
                subdivision_valid=subdivision_valid,
                subdivision_applied=subdivision_applied)


def _tube_geometry(rows: _Rows, shape: TorsionShape, index: int,
                   subdivision_applied: str) -> dict[str, str]:
    p = f"tube-{index:02d}"
    if shape.subdivided:
        x, y = f"input-{p}-x", f"input-{p}-y"
        b, h = f"input-{p}-b", f"input-{p}-h"
        stiffness = rows.add(f"{p}-stiffness", "Rectangle torsion constant", STIFFNESS,
                             ROLE_COMPUTED, STIFFNESS_SOURCE, b, h)
        geometry_dep = rows.add(f"{p}-entered-geometry", "Ordered sub-tube geometry", ONE,
                                ROLE_COMPUTED, GEOMETRY_SOURCE,
                                "geometry-vector", subdivision_applied, x, y, b, h)
        override = None
    else:
        stiffness = None
        geometry_dep = "geometry-vector"
        override = "input-tef-override"
    area = rows.add(f"{p}-outer-area", "Tube outer area", AREA, ROLE_COMPUTED,
                    TUBE_SOURCE, geometry_dep)
    perimeter = rows.add(f"{p}-outer-perimeter", "Tube outer perimeter", LENGTH,
                         ROLE_COMPUTED, TUBE_SOURCE, geometry_dep)
    auto = rows.add(f"{p}-tef-auto", "Automatic effective thickness", LENGTH_MM,
                    ROLE_COMPUTED, TUBE_SOURCE, area, perimeter)
    tef_deps = (geometry_dep, auto) if override is None else (geometry_dep, auto, override)
    tef = rows.add(f"{p}-tef", "Effective tube thickness", LENGTH_MM,
                   ROLE_COMPUTED, TUBE_SOURCE, *tef_deps)
    capped = rows.add(f"{p}-tef-capped", "Hollow thickness cap applied", ONE,
                      ROLE_COMPUTED, TUBE_SOURCE, geometry_dep, auto, tef)
    user = rows.add(f"{p}-tef-user", "Entered thickness applied", ONE,
                    ROLE_COMPUTED, TUBE_SOURCE, *((override,) if override else (tef,)))
    hollow = rows.add(f"{p}-hollow", "Hollow tube identity", ONE,
                      ROLE_COMPUTED, TUBE_SOURCE, geometry_dep)
    minimum = rows.add(f"{p}-minimum-dimension", "Minimum caliper dimension", LENGTH_MM,
                       ROLE_COMPUTED, GEOMETRY_SOURCE, geometry_dep)
    ak = rows.add(f"{p}-ak", "Area enclosed by tube centre-line", AREA,
                  ROLE_COMPUTED, TUBE_SOURCE, geometry_dep, tef)
    uk = rows.add(f"{p}-uk", "Tube centre-line perimeter", LENGTH,
                  ROLE_COMPUTED, TUBE_SOURCE, geometry_dep, tef)
    valid = rows.add(f"{p}-geometry-valid", "Tube geometry validity", ONE,
                     ROLE_COMPUTED, GEOMETRY_SOURCE, area, perimeter, tef, ak, uk)
    return dict(p=p, stiffness=stiffness, geometry=geometry_dep, area=area,
                perimeter=perimeter, auto=auto, tef=tef, capped=capped, user=user,
                hollow=hollow, minimum=minimum, ak=ak, uk=uk, valid=valid)


def expected_step_contract(shape: TorsionShape) -> tuple[StepSpec, ...]:
    rows = _Rows()
    normal = _inputs(rows, shape)
    if shape.failed:
        failure = rows.add("authoritative-failure-state", "Explicit torsion failure",
                           ONE, ROLE_COMPUTED, SELECTOR_SOURCE, normal)
        rows.add("ct-007-torsion-result", "CT-007 failed torsion result", ONE,
                 ROLE_FINAL, VERDICT_SOURCE, normal, failure)
        return tuple(rows.rows)

    common = _common(rows, shape)
    tubes = [_tube_geometry(rows, shape, index, common["subdivision_applied"])
             for index in range(shape.tube_count)]
    if shape.subdivided:
        total_stiffness = rows.add(
            "total-torsion-stiffness", "Total sub-tube torsion stiffness", STIFFNESS,
            ROLE_COMPUTED, STIFFNESS_SOURCE,
            *(tube["stiffness"] for tube in tubes),
        )
        for tube in tubes:
            tube["demand"] = rows.add(
                f"{tube['p']}-demand", "Stiffness-distributed torsion demand", MOMENT,
                ROLE_COMPUTED, DISTRIBUTION_SOURCE,
                "input-demand", tube["stiffness"], total_stiffness,
            )
    else:
        total_stiffness = None
        tubes[0]["demand"] = rows.add(
            "tube-00-demand", "Single-tube torsion demand", MOMENT,
            ROLE_COMPUTED, DISTRIBUTION_SOURCE, "input-demand",
        )

    if shape.zero_demand:
        for tube in tubes:
            operands = rows.add(
                f"{tube['p']}-resistance-selector-operands",
                "Complete zero-demand resistance selector operands", ONE,
                ROLE_COMPUTED, SELECTOR_SOURCE, common["asw_s"], common["fywd"],
                common["nu"], common["alpha"], common["fcd"], tube["tef"],
                common["lo"], common["hi"],
            )
            tube["cot"] = rows.add(
                f"{tube['p']}-cot", "Resistance-optimum cotangent", ONE,
                ROLE_COMPUTED, SELECTOR_SOURCE, operands,
            )
            tube["theta"] = rows.add(
                f"{tube['p']}-theta", "Compression-strut angle", ANGLE,
                ROLE_COMPUTED, SELECTOR_SOURCE, tube["cot"],
            )
    else:
        operands = rows.add(
            "selector-operands", "Complete 1,501-point minimax operands", ONE,
            ROLE_COMPUTED, SELECTOR_SOURCE, common["asw_s"], common["fywd"],
            common["nu"], common["alpha"], common["fcd"], common["lo"],
            common["hi"],
            *(item for tube in tubes for item in
              (tube["demand"], tube["ak"], tube["tef"])),
        )
        cot = rows.add("selector-cot", "1,501-point minimax cotangent", ONE,
                       ROLE_COMPUTED, SELECTOR_SOURCE, operands)
        theta = rows.add("selector-theta", "Compression-strut angle", ANGLE,
                         ROLE_COMPUTED, SELECTOR_SOURCE, cot)
        for tube in tubes:
            tube["cot"], tube["theta"] = cot, theta

    complete_tubes = []
    for tube in tubes:
        p = tube["p"]
        trds = rows.add(f"{p}-trd-s", "Closed-link torsion resistance", MOMENT,
                        ROLE_COMPUTED, TRANSVERSE_SOURCE, tube["ak"], common["fywd"],
                        common["asw_s"], tube["cot"])
        trdmax = rows.add(f"{p}-trd-max", "Concrete-strut torsion resistance", MOMENT,
                          ROLE_COMPUTED, CRUSHING_SOURCE, common["nu"], common["alpha"],
                          common["fcd"], tube["ak"], tube["tef"], tube["cot"])
        trd = rows.add(f"{p}-trd", "Governing tube resistance", MOMENT,
                       ROLE_COMPUTED, VERDICT_SOURCE, trds, trdmax, common["asw_s"])
        trdc = rows.add(f"{p}-trd-c", "Torsion cracking resistance", MOMENT,
                        ROLE_COMPUTED, CRACK_SOURCE, common["fctd"], tube["ak"],
                        tube["tef"])
        asl = rows.add(f"{p}-asl-required", "Required longitudinal torsion steel",
                       AREA_MM2, ROLE_COMPUTED, LONGITUDINAL_SOURCE, tube["demand"],
                       tube["uk"], tube["ak"], common["fyd"], tube["cot"])
        util = rows.add(f"{p}-utilisation", "Tube torsion utilisation", ONE,
                        ROLE_COMPUTED, VERDICT_SOURCE, tube["demand"], trd)
        mode = rows.add(f"{p}-governing-mode", "Tube governing resistance identity", ONE,
                        ROLE_COMPUTED, VERDICT_SOURCE, trds, trdmax, common["asw_s"])
        verdict = rows.add(f"{p}-verdict", "Tube torsion PASS or FAIL", ONE,
                           ROLE_COMPUTED, VERDICT_SOURCE, util)
        tube.update(trds=trds, trdmax=trdmax, trd=trd, trdc=trdc, asl=asl,
                    util=util, mode=mode, verdict=verdict)
        geometry_fields = (tube["area"], tube["perimeter"], tube["auto"], tube["tef"],
                           tube["capped"], tube["user"], tube["hollow"], tube["minimum"],
                           tube["ak"], tube["uk"], tube["valid"])
        complete_tubes.append(rows.add(
            f"{p}-complete-evidence", "Complete torsion tube evidence", ONE,
            ROLE_COMPUTED, VERDICT_SOURCE, *geometry_fields,
            *((tube["stiffness"], tube["geometry"]) if shape.subdivided else ()),
            tube["demand"], tube["cot"], tube["theta"], trds, trdmax, trd, trdc,
            asl, util, mode, verdict,
        ))

    aggregate_demand = rows.add(
        "aggregate-demand", "Conserved aggregate torsion demand", MOMENT,
        ROLE_COMPUTED, DISTRIBUTION_SOURCE, *(tube["demand"] for tube in tubes),
    )
    aggregate_trd = rows.add(
        "aggregate-resistance", "Aggregate torsion resistance", MOMENT,
        ROLE_COMPUTED, VERDICT_SOURCE, *(tube["trd"] for tube in tubes),
    )
    aggregate_asl = rows.add(
        "aggregate-asl-required", "Aggregate longitudinal torsion steel demand",
        AREA_MM2, ROLE_COMPUTED, VERDICT_SOURCE,
        *(tube["asl"] for tube in tubes),
    )
    aggregate_util = rows.add(
        "aggregate-utilisation", "Governing torsion utilisation", ONE,
        ROLE_COMPUTED, VERDICT_SOURCE, *(tube["util"] for tube in tubes),
    )
    governing = rows.add(
        "aggregate-governing-tube", "Governing tube index", ONE,
        ROLE_COMPUTED, VERDICT_SOURCE, *(tube["util"] for tube in tubes),
    )
    verdict = rows.add("aggregate-verdict", "Aggregate torsion PASS or FAIL", ONE,
                       ROLE_COMPUTED, VERDICT_SOURCE, aggregate_util)
    mode = rows.add("selector-mode", "Utilisation or resistance selector mode", ONE,
                    ROLE_COMPUTED, SELECTOR_SOURCE, "input-demand")
    rows.add(
        "ct-007-torsion-result", "Complete CT-007 torsion result", ONE,
        ROLE_FINAL, VERDICT_SOURCE, normal, *complete_tubes, aggregate_demand,
        aggregate_trd, aggregate_asl, aggregate_util, governing, verdict, mode,
        common["outside"], common["detail_applied"], common["compound"],
        common["subdivision_valid"], common["subdivision_applied"],
        *((total_stiffness,) if total_stiffness else ()),
    )
    return tuple(rows.rows)


def expected_registry(shape: TorsionShape) -> TraceRegistryContract:
    specs = expected_step_contract(shape)
    member = TraceMemberContract(
        member_id="torsion-aggregate", calculation_id=shape.calculation_id,
        coverage_id=COVERAGE_ID, method_id=METHOD_ID, axes=shape.axes,
        sources=frozenset(TraceSourceContract(s.source.kind, s.source.method_id,
                                              s.source.edition) for s in specs),
        result_states=frozenset({RESULT_FAILED if shape.failed else RESULT_FINITE}),
        step_ids=tuple(s.step_id for s in specs),
        step_dependencies=tuple((s.step_id, s.dependencies) for s in specs),
        step_metadata=tuple(TraceStepMetadataContract(
            s.step_id, s.quantity_role, s.source
        ) for s in specs),
    )
    return TraceRegistryContract(
        REGISTRY_ID, (TraceFamilyContract(FAMILY_ID, (member,)),)
    )
