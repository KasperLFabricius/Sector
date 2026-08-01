"""Independent CT-006 identity, operand graph, and provenance contract."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from . import codes
from .calculation_trace import (
    RESULT_FAILED, RESULT_FINITE, ROLE_COMPUTED, ROLE_FINAL,
    ROLE_METHOD_VALUE, ROLE_USER_INPUT, SOURCE_INPUT, SOURCE_PROJECT,
    SOURCE_STANDARD, SourceCitation, TraceAxis, TraceSource, TraceUnit,
    trace_identity_token,
)
from .section_trace_blocks import (
    DOC_2005, MaterialBlock, SectionTraceBlocks, context_axes, context_id,
)
from .trace_registry import (
    TraceFamilyContract, TraceMemberContract, TraceRegistryContract,
    TraceSourceContract, TraceStepMetadataContract,
)


COVERAGE_ID = "ct-006"
REGISTRY_ID = "sector-ct-006-directional-shear-v1"
METHOD_ID = "sector-directional-shear-original-input-replay"
BRANCH_FINITE = "finite"
BRANCH_FAILED = "failed"

DOC_DK = "DS/EN 1992-1-1 DK NA:2024"
INPUT_SOURCE = TraceSource(SOURCE_INPUT, "sector-section-input")
SOLVER_SOURCE = TraceSource(SOURCE_PROJECT, "sector-retained-shear-kernels")
SELECTOR_SOURCE = TraceSource(SOURCE_PROJECT, "sector-1501-point-minimax-cot-selector")
CHORD_SOURCE = TraceSource(SOURCE_PROJECT, "sector-conditional-longitudinal-chord")
BASE_CONCRETE_SOURCE = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2004-a1-ac-shear-without-links", DOC_2005,
    SourceCitation(DOC_2005, "6.2.2(1)", "Formulae (6.2.a) and (6.2.b)"),
)
BASE_LINK_SOURCE = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2004-a1-ac-variable-angle-truss", DOC_2005,
    SourceCitation(DOC_2005, "6.2.3", "Formulae (6.8), (6.9), and (6.18)"),
)
BASE_VMIN_SOURCE = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2004-a1-ac-recommended-vmin", DOC_2005,
    SourceCitation(DOC_2005, "6.2.2(1)", "Formula (6.3N)"),
)
BASE_NU_SOURCE = TraceSource(
    SOURCE_STANDARD, "en-1992-1-1-2004-a1-ac-recommended-nu1", DOC_2005,
    SourceCitation(DOC_2005, "6.2.2(6)", "Formula (6.6N)"),
)
DK_VMIN_SOURCE = TraceSource(
    SOURCE_STANDARD, "dk-na-2024-shear-vmin", DOC_DK,
    SourceCitation(DOC_DK, "6.2.2(1)", "Danish v_min value"),
)
DK_NU_SOURCE = TraceSource(
    SOURCE_STANDARD, "dk-na-2024-shear-nu-v", DOC_DK,
    SourceCitation(DOC_DK, "5.101 NA and 5.103 NA", "nu_v for truss compression struts"),
)
PUBLISHED_2023_SOURCE = TraceSource(
    SOURCE_PROJECT, "sector-2023-shear-published-not-implemented"
)

ONE = TraceUnit("1", "scalar")
LENGTH = TraceUnit("m", "length")
LENGTH_MM = TraceUnit("mm", "length")
AREA = TraceUnit("m2", "area")
AREA_MM2 = TraceUnit("mm2", "area")
FORCE = TraceUnit("kN", "force")
FORCE_PER_LENGTH = TraceUnit("mm2/mm", "area_per_length")
MOMENT = TraceUnit("kNm", "moment")
STRESS = TraceUnit("MPa", "stress")
ANGLE = TraceUnit("deg", "angle")


@dataclass(frozen=True, slots=True)
class DirectionShape:
    blocks: SectionTraceBlocks
    context_token: str
    component: str
    axis: str
    faces: tuple[bool, ...]
    method: str
    links: bool
    chord: bool
    branch: str
    axes: tuple[TraceAxis, ...]

    @property
    def calculation_id(self) -> str:
        return f"shear.{self.context_token}.{self.component}.directional"


def trace_shape(
    blocks: SectionTraceBlocks,
    context: Mapping[str, Any],
    component: str,
    axis: str,
    faces: tuple[bool, ...],
    method: str,
    links: bool,
    chord: bool,
    branch: str,
) -> DirectionShape:
    if component not in {"vx", "vy"} or axis != {"vx": "y", "vy": "x"}[component]:
        raise ValueError("CT-006 physical direction/axis mismatch")
    if not faces or any(type(face) is not bool for face in faces):
        raise ValueError("CT-006 needs an ordered Boolean face tuple")
    if faces not in {(True,), (False,), (True, False)}:
        raise ValueError("CT-006 face order is not canonical")
    if branch not in {BRANCH_FINITE, BRANCH_FAILED}:
        raise ValueError("unknown CT-006 branch")
    face_order = ",".join("negative" if item else "positive" for item in faces)
    axes = context_axes(
        context, branch=branch, component=component,
        direction_cardinality="1", face_cardinality=str(len(faces)),
        face_order=face_order, links="present" if links else "absent",
        longitudinal_chord="present" if chord else "absent",
        method=method, physical_axis=axis,
        sign="signed-v-input-absolute-demand",
    )
    return DirectionShape(
        blocks, context_id(context), component, axis, faces, method,
        links, chord, branch, axes,
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

    def add(self, step_id, title, unit, role, source, *dependencies):
        if step_id in self.ids:
            raise ValueError(f"duplicate CT-006 step {step_id}")
        self.ids.add(step_id)
        self.rows.append(StepSpec(step_id, title, unit, role, source, tuple(dependencies)))
        return step_id


def _token(value: str) -> str:
    return trace_identity_token(value)


def _material_unit(name: str) -> TraceUnit:
    if name in {"fck", "fytk", "fyck", "futk", "Es"}:
        return STRESS
    return ONE


def material_step_id(material: MaterialBlock, name: str) -> str:
    return (
        f"material-{material.kind}-{_token(material.element_id)}-"
        f"{_token(material.material_id)}-{_token(name)}"
    )


def _shared(rows: _Rows, shape: DirectionShape) -> dict[str, str]:
    geometry = []
    for ri, ring in enumerate(shape.blocks.geometry.rings):
        for pi, _point in enumerate(ring):
            for suffix in ("x", "y"):
                geometry.append(rows.add(
                    f"geometry-ring-{ri:03d}-point-{pi:04d}-{suffix}",
                    f"Concrete vertex {suffix}", LENGTH,
                    ROLE_USER_INPUT, INPUT_SOURCE,
                ))
    for kind, elements in (("bar", shape.blocks.geometry.bars), ("tendon", shape.blocks.geometry.tendons)):
        for index, _element in enumerate(elements):
            for suffix, unit in (("x", LENGTH), ("y", LENGTH), ("area", AREA_MM2)):
                geometry.append(rows.add(
                    f"geometry-{kind}-{index:04d}-{suffix}",
                    f"{kind.title()} {suffix}", unit,
                    ROLE_USER_INPUT, INPUT_SOURCE,
                ))
    geometry_state = rows.add(
        "geometry-state", "Immutable section geometry", ONE,
        ROLE_COMPUTED, SOLVER_SOURCE, *geometry,
    )

    material = []
    for block in (shape.blocks.concrete, *shape.blocks.bars, *shape.blocks.tendons):
        for name, _value in block.values:
            material.append(rows.add(
                material_step_id(block, name), f"Assigned {block.kind} {name}",
                _material_unit(name), ROLE_METHOD_VALUE,
                block.provenance.source,
            ))
    material_state = rows.add(
        "material-state", "Aligned immutable material laws", ONE,
        ROLE_COMPUTED, SOLVER_SOURCE, *material,
    )
    actions = {}
    for name, _value in shape.blocks.plastic_actions.values:
        actions[name] = rows.add(
            f"input-action-{_token(name)}", f"Original action {name}",
            FORCE if name == "P_pl" else MOMENT,
            ROLE_USER_INPUT, INPUT_SOURCE,
        )
    demand = rows.add(
        f"input-{shape.component}-signed-demand", "Original signed shear action",
        FORCE, ROLE_USER_INPUT, INPUT_SOURCE,
    )
    bw_override = rows.add(
        "input-web-width-override", "Directional web-width override",
        LENGTH_MM, ROLE_USER_INPUT, INPUT_SOURCE,
    )
    common = {
        "geometry": geometry_state, "material": material_state,
        "P": actions["P_pl"], "Mx": actions["Mx_pl"], "My": actions["My_pl"],
        "demand": demand, "bw_override": bw_override,
    }
    concrete_values = dict(shape.blocks.concrete.values)
    for name in ("fck", "gamma_c", "alpha_cc"):
        if name in concrete_values:
            common[name.replace("_", "-")] = material_step_id(shape.blocks.concrete, name)
    if shape.blocks.bars:
        bar_values = dict(shape.blocks.bars[0].values)
        for name in ("fytk", "gamma_y"):
            if name in bar_values:
                common[name.replace("_", "-")] = material_step_id(shape.blocks.bars[0], name)
    if shape.links:
        for name, unit in (
            ("link-legs", ONE), ("link-diameter", LENGTH_MM),
            ("link-spacing", LENGTH_MM), ("link-yield", STRESS),
            ("cot-min", ONE), ("cot-max", ONE),
        ):
            common[name] = rows.add(
                f"input-{name}", name.replace("-", " ").title(), unit,
                ROLE_USER_INPUT, INPUT_SOURCE,
            )
        if shape.method == codes.EC2_2023.label:
            common["aggregate-lower"] = rows.add(
                "input-aggregate-lower", "Lower aggregate sieve size", LENGTH_MM,
                ROLE_USER_INPUT, INPUT_SOURCE,
            )
        if shape.chord:
            common["chord-plan"] = rows.add(
                "chord-extrema-plan", "CT-006 canonical 15 degree chord extrema plan",
                ANGLE, ROLE_METHOD_VALUE, CHORD_SOURCE,
            )
    common["area"] = rows.add(
        "section-area", "Gross concrete area", AREA, ROLE_COMPUTED,
        SOLVER_SOURCE, geometry_state,
    )
    common["cx"] = rows.add(
        "section-centroid-x", "Concrete centroid x", LENGTH, ROLE_COMPUTED,
        SOLVER_SOURCE, geometry_state,
    )
    common["cy"] = rows.add(
        "section-centroid-y", "Concrete centroid y", LENGTH, ROLE_COMPUTED,
        SOLVER_SOURCE, geometry_state,
    )
    for component, unit in (("n", FORCE), ("mx", MOMENT), ("my", MOMENT)):
        common[f"prestress-{component}"] = rows.add(
            f"prestress-{component}", f"Locked-in prestress {component}", unit,
            ROLE_COMPUTED, SOLVER_SOURCE, geometry_state, material_state,
        )
    common["n-comp"] = rows.add(
        "compression-positive-axial", "Compression-positive axial action", FORCE,
        ROLE_COMPUTED, SOLVER_SOURCE, common["P"], common["prestress-n"],
    )
    moment = common["My"] if shape.axis == "y" else common["Mx"]
    centroid = common["cx"] if shape.axis == "y" else common["cy"]
    prestress_m = common["prestress-my"] if shape.axis == "y" else common["prestress-mx"]
    common["moment-origin"] = rows.add(
        "associated-moment-origin", "Associated bending action at origin", MOMENT,
        ROLE_COMPUTED, SOLVER_SOURCE, moment,
    )
    common["moment"] = rows.add(
        "associated-moment-centroid", "Associated bending action at centroid", MOMENT,
        ROLE_COMPUTED, SOLVER_SOURCE, moment, common["P"], centroid, prestress_m,
    )
    common["demand-abs"] = rows.add(
        "absolute-shear-demand", "Absolute directional shear demand", FORCE,
        ROLE_COMPUTED, SOLVER_SOURCE, demand,
    )
    shared_steps = tuple(spec.step_id for spec in rows.rows)
    common["evidence"] = rows.add(
        "direction-shared-evidence", "Complete shared CT-006 input evidence", ONE,
        ROLE_COMPUTED, SOLVER_SOURCE, *shared_steps,
    )
    return common


def _face(rows: _Rows, shape: DirectionShape, common: dict[str, str], tension_low: bool) -> str:
    face_start = len(rows.rows)
    name = "negative" if tension_low else "positive"
    p = f"face-{name}"
    face = rows.add(
        f"{p}-identity", f"{name.title()} face identity", ONE,
        ROLE_COMPUTED, SOLVER_SOURCE, common["moment"],
    )
    asl = rows.add(f"{p}-asl", "Tension reinforcement area", AREA_MM2,
                   ROLE_COMPUTED, SOLVER_SOURCE, common["geometry"], face, common["cx"], common["cy"])
    depth = rows.add(f"{p}-d", "Effective shear depth", LENGTH_MM,
                     ROLE_COMPUTED, SOLVER_SOURCE, common["geometry"], face, asl)
    bw_auto = rows.add(f"{p}-bw-auto", "Derived minimum web width", LENGTH_MM,
                       ROLE_COMPUTED, SOLVER_SOURCE, common["geometry"])
    bw = rows.add(f"{p}-bw", "Effective web width", LENGTH_MM,
                  ROLE_COMPUTED, SOLVER_SOURCE, common["bw_override"], bw_auto)
    concrete_source = PUBLISHED_2023_SOURCE if shape.method == codes.EC2_2023.label else BASE_CONCRETE_SOURCE
    fck = rows.add(f"{p}-fck", "Concrete characteristic strength", STRESS,
                   ROLE_COMPUTED, shape.blocks.concrete.provenance.source,
                   common["fck"])
    fcd = rows.add(f"{p}-fcd", "Concrete design strength", STRESS,
                   ROLE_COMPUTED, shape.blocks.concrete.provenance.source,
                   common["fck"], common["gamma-c"], common.get("alpha-cc", common["material"]))
    if shape.method == codes.EC2_2023.label:
        fyd = rows.add(f"{p}-fyd-flex", "Flexural reinforcement design yield", STRESS,
                       ROLE_COMPUTED, PUBLISHED_2023_SOURCE, common["fytk"], common["gamma-y"])
        ddg = rows.add(f"{p}-ddg", "Aggregate size parameter", LENGTH_MM,
                       ROLE_COMPUTED, PUBLISHED_2023_SOURCE, fck, common["aggregate-lower"])
        gamma_v = rows.add(f"{p}-gamma-v", "Shear partial factor", ONE,
                           ROLE_METHOD_VALUE, PUBLISHED_2023_SOURCE)
        acs = rows.add(f"{p}-a-cs", "Shear span proxy", LENGTH_MM,
                       ROLE_COMPUTED, PUBLISHED_2023_SOURCE, common["moment"], common["demand-abs"], depth)
        kvp = rows.add(f"{p}-k-vp", "Axial action factor", ONE,
                       ROLE_COMPUTED, PUBLISHED_2023_SOURCE, common["n-comp"], common["demand-abs"], depth, acs)
        dkvp = rows.add(f"{p}-d-kvp", "Axial-adjusted depth", LENGTH_MM,
                        ROLE_COMPUTED, PUBLISHED_2023_SOURCE, kvp, depth)
        rho = rows.add(f"{p}-rho-l", "Longitudinal reinforcement ratio", ONE,
                       ROLE_COMPUTED, PUBLISHED_2023_SOURCE, asl, bw, depth)
        tau_basic = rows.add(f"{p}-tau-basic", "Basic concrete shear stress", STRESS,
                             ROLE_COMPUTED, PUBLISHED_2023_SOURCE, rho, fck, ddg, dkvp, gamma_v)
        tau_min = rows.add(f"{p}-tau-min", "Minimum concrete shear stress", STRESS,
                           ROLE_COMPUTED, PUBLISHED_2023_SOURCE, fck, fyd, ddg, depth, gamma_v)
        tau = rows.add(f"{p}-tau-rdc", "Governing concrete shear stress", STRESS,
                       ROLE_COMPUTED, PUBLISHED_2023_SOURCE, tau_basic, tau_min)
        vrdc = rows.add(f"{p}-vrd-c", "Concrete shear resistance", FORCE,
                        ROLE_COMPUTED, PUBLISHED_2023_SOURCE, tau, bw, depth)
    else:
        k = rows.add(f"{p}-k", "Depth factor k", ONE, ROLE_COMPUTED,
                     BASE_CONCRETE_SOURCE, depth)
        rho = rows.add(f"{p}-rho-l", "Longitudinal reinforcement ratio", ONE,
                       ROLE_COMPUTED, BASE_CONCRETE_SOURCE, asl, bw, depth)
        sigma = rows.add(f"{p}-sigma-cp", "Concrete compression stress", STRESS,
                         ROLE_COMPUTED, BASE_CONCRETE_SOURCE, common["n-comp"], common["area"], fcd)
        crd = rows.add(f"{p}-crd-c", "Concrete shear coefficient", ONE,
                       ROLE_COMPUTED, BASE_CONCRETE_SOURCE, common["gamma-c"])
        k1 = rows.add(f"{p}-k1", "Axial stress coefficient", ONE,
                      ROLE_METHOD_VALUE, BASE_CONCRETE_SOURCE)
        vmin_source = DK_VMIN_SOURCE if shape.method == codes.EC2_2005_DKNA.label else BASE_VMIN_SOURCE
        vmin = rows.add(f"{p}-vmin", "Minimum concrete shear stress", STRESS,
                        ROLE_COMPUTED, vmin_source, k, fck, common["gamma-c"])
        basic = rows.add(f"{p}-v-basic", "Basic concrete shear stress", STRESS,
                         ROLE_COMPUTED, BASE_CONCRETE_SOURCE, crd, k, rho, fck, k1, sigma)
        floor = rows.add(f"{p}-v-floor", "Concrete shear stress floor", STRESS,
                         ROLE_COMPUTED, BASE_CONCRETE_SOURCE, vmin, k1, sigma)
        vrdc = rows.add(f"{p}-vrd-c", "Concrete shear resistance", FORCE,
                        ROLE_COMPUTED, BASE_CONCRETE_SOURCE, basic, floor, bw, depth)
    cutil = rows.add(f"{p}-concrete-utilisation", "Concrete-only utilisation", ONE,
                     ROLE_COMPUTED, SOLVER_SOURCE, common["demand-abs"], vrdc)
    cstatus = rows.add(f"{p}-concrete-verdict", "Concrete-only PASS/FAIL", ONE,
                       ROLE_COMPUTED, SOLVER_SOURCE, cutil)
    metric, verdict = cutil, cstatus

    if shape.links:
        asw = rows.add(f"{p}-asw", "Link area", AREA_MM2, ROLE_COMPUTED,
                       SOLVER_SOURCE, common["link-legs"], common["link-diameter"])
        asws = rows.add(f"{p}-asw-over-s", "Link area per spacing", FORCE_PER_LENGTH,
                        ROLE_COMPUTED, SOLVER_SOURCE, asw, common["link-spacing"])
        z = rows.add(f"{p}-z", "Retained shear lever arm", LENGTH_MM,
                     ROLE_COMPUTED, SOLVER_SOURCE, common["geometry"], common["material"], common["P"], face, depth)
        fywd = rows.add(f"{p}-fywd", "Link design yield", STRESS, ROLE_COMPUTED,
                        SOLVER_SOURCE, common["link-yield"], common["gamma-y"])
        if shape.method == codes.EC2_2023.label:
            nu = rows.add(f"{p}-nu1", "Compression-field effectiveness", ONE,
                          ROLE_METHOD_VALUE, PUBLISHED_2023_SOURCE)
            alpha = rows.add(f"{p}-alpha-cw", "Compression chord factor", ONE,
                             ROLE_METHOD_VALUE, PUBLISHED_2023_SOURCE)
        else:
            nu_source = DK_NU_SOURCE if shape.method == codes.EC2_2005_DKNA.label else BASE_NU_SOURCE
            nu = rows.add(f"{p}-nu1", "Concrete strut effectiveness", ONE,
                          ROLE_COMPUTED, nu_source, fck)
            alpha = rows.add(f"{p}-alpha-cw", "Compression chord factor", ONE,
                             ROLE_COMPUTED, BASE_LINK_SOURCE, common["n-comp"], common["area"], fcd)
        cot_deps = [common["cot-min"], common["cot-max"], common["demand-abs"], asws, fywd, z, bw, nu, alpha, fcd]
        if shape.chord:
            cot_deps.extend((common["geometry"], common["P"], common["Mx"], common["My"], common["chord-plan"], face))
        cot = rows.add(f"{p}-cot", "Solver-owned minimax cot(theta)", ONE,
                       ROLE_COMPUTED, SELECTOR_SOURCE, *cot_deps)
        theta = rows.add(f"{p}-theta", "Compression-field angle", ANGLE,
                         ROLE_COMPUTED, SELECTOR_SOURCE, cot)
        link_source = PUBLISHED_2023_SOURCE if shape.method == codes.EC2_2023.label else BASE_LINK_SOURCE
        vrds = rows.add(f"{p}-vrd-s", "Link yielding resistance", FORCE,
                        ROLE_COMPUTED, link_source, asws, fywd, z, cot)
        vrdmax = rows.add(f"{p}-vrd-max", "Concrete strut resistance", FORCE,
                          ROLE_COMPUTED, link_source, alpha, bw, z, nu, fcd, cot)
        vrd = rows.add(f"{p}-vrd", "Linked shear resistance", FORCE,
                       ROLE_COMPUTED, link_source, vrds, vrdmax)
        lutil = rows.add(f"{p}-linked-utilisation", "Linked shear utilisation", ONE,
                         ROLE_COMPUTED, SOLVER_SOURCE, common["demand-abs"], vrd)
        rows.add(f"{p}-links-required", "Links required by concrete resistance", ONE,
                 ROLE_COMPUTED, SOLVER_SOURCE, common["demand-abs"], vrdc)
        lstatus = rows.add(f"{p}-linked-verdict", "Linked shear PASS/FAIL", ONE,
                           ROLE_COMPUTED, SOLVER_SOURCE, lutil)
        metric, verdict = lutil, lstatus
        if shape.chord:
            off = rows.add(f"{p}-chord-off-moment", "Off-axis chord moment", MOMENT,
                           ROLE_COMPUTED, CHORD_SOURCE, common["Mx"], common["My"])
            offcap = rows.add(f"{p}-chord-off-capacity", "Off-axis sweep capacity", MOMENT,
                              ROLE_COMPUTED, CHORD_SOURCE, common["geometry"], common["material"], common["P"], common["chord-plan"])
            offutil = rows.add(f"{p}-chord-off-util", "Off-axis utilisation", ONE,
                               ROLE_COMPUTED, CHORD_SOURCE, off, offcap)
            rows.add(f"{p}-chord-biaxial", "Derived biaxial flag", ONE,
                     ROLE_COMPUTED, CHORD_SOURCE, offutil)
            med = rows.add(f"{p}-chord-m-ed", "Chord bending demand", MOMENT,
                           ROLE_COMPUTED, CHORD_SOURCE, common["Mx"], common["My"], face)
            mrd = rows.add(f"{p}-chord-m-rd", "Conditional chord resistance", MOMENT,
                           ROLE_COMPUTED, CHORD_SOURCE, common["geometry"], common["material"], common["P"], off, face)
            ftd = rows.add(f"{p}-longitudinal-shear-force", "Longitudinal shear force", FORCE,
                           ROLE_COMPUTED, link_source, common["demand-abs"], cot)
            mv = rows.add(f"{p}-chord-mv", "Chord shear-shift moment", MOMENT,
                          ROLE_COMPUTED, CHORD_SOURCE, ftd, z, med, mrd)
            total = rows.add(f"{p}-chord-total-moment", "Total chord moment", MOMENT,
                             ROLE_COMPUTED, CHORD_SOURCE, med, mv)
            chutil = rows.add(f"{p}-chord-utilisation", "Longitudinal chord utilisation", ONE,
                              ROLE_COMPUTED, CHORD_SOURCE, total, mrd)
            rows.add(f"{p}-chord-verdict", "Longitudinal chord PASS/FAIL", ONE,
                     ROLE_COMPUTED, CHORD_SOURCE, chutil)
    emitted = tuple(spec.step_id for spec in rows.rows[face_start:])
    evidence = rows.add(
        f"{p}-complete-evidence", "Complete face evidence", ONE,
        ROLE_COMPUTED, SOLVER_SOURCE, *emitted,
    )
    return evidence


def expected_step_contract(shape: DirectionShape) -> tuple[StepSpec, ...]:
    rows = _Rows()
    if shape.branch == BRANCH_FAILED:
        failure = rows.add(
            "direction-failure-state", "Authoritative CT-006 failure", ONE,
            ROLE_METHOD_VALUE, SOLVER_SOURCE,
        )
        rows.add("direction-shear-verdict", "Directional shear failed", ONE,
                 ROLE_FINAL, SOLVER_SOURCE, failure)
        return tuple(rows.rows)
    common = _shared(rows, shape)
    faces = [_face(rows, shape, common, item) for item in shape.faces]
    governing = rows.add(
        "direction-governing-face", "Governing required face", ONE,
        ROLE_COMPUTED, SOLVER_SOURCE, *faces,
    )
    metric = rows.add(
        "direction-shear-metric", "Governing directional utilisation", ONE,
        ROLE_COMPUTED, SOLVER_SOURCE, governing, *faces,
    )
    rows.add(
        "direction-shear-verdict", "Directional shear PASS/FAIL", ONE,
        ROLE_FINAL, SOLVER_SOURCE, common["evidence"], metric, *faces,
    )
    return tuple(rows.rows)


def _source_contract(source: TraceSource) -> TraceSourceContract:
    return TraceSourceContract(source.kind, source.method_id, source.edition)


def expected_registry(shapes: tuple[DirectionShape, ...]) -> TraceRegistryContract:
    expected = tuple(item for item in ("vx", "vy") if any(s.component == item for s in shapes))
    if tuple(shape.component for shape in shapes) != expected:
        raise ValueError("CT-006 directions must be declared in vx then vy order")
    if any(shape.blocks != shapes[0].blocks for shape in shapes[1:]):
        raise ValueError("CT-006 directions must share immutable input blocks")
    families = []
    for shape in shapes:
        specs = expected_step_contract(shape)
        member = TraceMemberContract(
            member_id=f"directional-shear-{shape.component}",
            calculation_id=shape.calculation_id,
            coverage_id=COVERAGE_ID,
            method_id=METHOD_ID,
            axes=shape.axes,
            sources=frozenset(_source_contract(spec.source) for spec in specs),
            result_states=frozenset({RESULT_FINITE if shape.branch == BRANCH_FINITE else RESULT_FAILED}),
            step_ids=tuple(spec.step_id for spec in specs),
            step_dependencies=tuple((spec.step_id, spec.dependencies) for spec in specs),
            step_metadata=tuple(TraceStepMetadataContract(spec.step_id, spec.quantity_role, spec.source) for spec in specs),
        )
        families.append(TraceFamilyContract(f"ct-006-directional-shear-{shape.component}", (member,)))
    return TraceRegistryContract(REGISTRY_ID, tuple(families))
