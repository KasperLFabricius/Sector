"""Independent CT-006 identity, shape, source, and graph declarations."""

from __future__ import annotations

from dataclasses import dataclass

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
from .section_trace_blocks import DOC_2005, DOC_2023, MaterialBlock, SectionTraceBlocks
from .trace_registry import (
    TraceFamilyContract,
    TraceMemberContract,
    TraceRegistryContract,
    TraceSourceContract,
    TraceStepMetadataContract,
)


COVERAGE_ID = "ct-006"
FAMILY_ID = "ct-006-directional-shear"
MEMBER_ID = "directional-shear"
REGISTRY_ID = "sector-ct-006-directional-shear-v1"

BRANCH_FINITE = "finite-directional-shear"
BRANCH_FAILED = "failed-directional-shear"

METHOD_IDS = {
    "EN 1992-1-1:2005": "ec2-2005-directional-shear",
    "DS/EN 1992-1-1:2005 + DK NA:2024": "ec2-2005-dk-na-2024-directional-shear",
    "DS/EN 1992-1-1:2023": "ec2-2023-published-not-implemented-directional-shear",
}

INPUT_SOURCE = TraceSource(SOURCE_INPUT, "sector-section-input")
GEOMETRY_SOURCE = TraceSource(SOURCE_PROJECT, "sector-shear-geometry-selection")
SELECTOR_SOURCE = TraceSource(SOURCE_PROJECT, "sector-minimax-shared-cot-selector")
STATUS_SOURCE = TraceSource(SOURCE_PROJECT, "sector-directional-shear-assessment")
FAILURE_SOURCE = TraceSource(SOURCE_PROJECT, "sector-directional-shear-failure")

BASE_CONCRETE_SOURCE = TraceSource(
    SOURCE_STANDARD,
    "ec2-2005-shear-without-links",
    DOC_2005,
    SourceCitation(DOC_2005, "6.2.2(1)", "Formulae (6.2a)-(6.2b)"),
)
BASE_LINK_SOURCE = TraceSource(
    SOURCE_STANDARD,
    "ec2-2005-variable-strut-shear",
    DOC_2005,
    SourceCitation(DOC_2005, "6.2.3", "Formulae (6.7N)-(6.9)"),
)
DK_VMIN_SOURCE = TraceSource(
    SOURCE_STANDARD,
    "dk-na-2024-shear-vmin",
    "DS/EN 1992-1-1 DK NA:2024",
    SourceCitation("DS/EN 1992-1-1 DK NA:2024", "6.2.2(1)", "v_min"),
)
DK_NU_SOURCE = TraceSource(
    SOURCE_STANDARD,
    "dk-na-2024-shear-nu-v",
    "DS/EN 1992-1-1 DK NA:2024",
    SourceCitation(
        "DS/EN 1992-1-1 DK NA:2024",
        "5.101 NA, 5.103 NA and 6.2.3(3)",
        "nu_v",
    ),
)
SOURCE_2023_CONCRETE = TraceSource(
    SOURCE_STANDARD,
    "ec2-2023-published-not-implemented-shear-without-links",
    DOC_2023,
    SourceCitation(DOC_2023, "8.2.2", "Formulae (8.20), (8.27), (8.30)-(8.31)"),
)
SOURCE_2023_LINK = TraceSource(
    SOURCE_STANDARD,
    "ec2-2023-published-not-implemented-compression-field-shear",
    DOC_2023,
    SourceCitation(DOC_2023, "8.2.3", "Formulae (8.41)-(8.44), (8.50)"),
)

ONE = TraceUnit("1", "scalar")
LENGTH_M = TraceUnit("m", "length")
LENGTH_MM = TraceUnit("mm", "length")
AREA_M2 = TraceUnit("m2", "area")
AREA_MM2 = TraceUnit("mm2", "area")
AREA_RATE = TraceUnit("mm2/mm", "area_rate")
FORCE = TraceUnit("kN", "force")
MOMENT = TraceUnit("kNm", "moment")
STRESS = TraceUnit("MPa", "stress")
ANGLE = TraceUnit("deg", "angle")


@dataclass(frozen=True, slots=True)
class FaceShape:
    tension_low: bool
    bar_ids: tuple[int, ...]
    chord: bool


@dataclass(frozen=True, slots=True)
class DirectionShape:
    component: str
    axis: str
    faces: tuple[FaceShape, ...]


@dataclass(frozen=True, slots=True)
class TraceShape:
    blocks: SectionTraceBlocks
    context_token: str
    method: str
    links: bool
    branch: str
    directions: tuple[DirectionShape, ...]
    axes: tuple[TraceAxis, ...]

    @property
    def method_id(self) -> str:
        return METHOD_IDS[self.method]

    @property
    def calculation_id(self) -> str:
        return f"shear.{self.context_token}.directional"

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
        self.rows.append(StepSpec(step_id, title, unit, role, source, tuple(dependencies)))
        return step_id


def _token(value: str) -> str:
    return trace_identity_token(value)


def _material_prefix(material: MaterialBlock) -> str:
    return f"material-{material.kind}-{_token(material.element_id)}-{_token(material.material_id)}"


def _material_unit(name: str) -> TraceUnit:
    return STRESS if name in {"fck", "fytk", "fyck", "futk", "Es"} else ONE


SHEAR_INPUTS = (
    ("enabled", ONE),
    ("shear-vx", FORCE), ("shear-vy", FORCE),
    ("face-x", ONE), ("face-y", ONE),
    ("bw-vx", LENGTH_MM), ("bw-vy", LENGTH_MM),
    ("links-enabled", ONE), ("mode-code", ONE), ("check-util", ONE),
)
LINK_INPUTS = (
    ("legs-vx", ONE), ("legs-vy", ONE), ("link-dia", LENGTH_MM),
    ("link-spacing", LENGTH_MM), ("link-fywk", STRESS),
    ("cot-min", ONE), ("cot-max", ONE), ("ductility-code", ONE),
)


COMMON_FACE_FIELDS = (
    ("v-ed", FORCE), ("bw", LENGTH_MM),
    ("bw-auto", LENGTH_MM), ("bw-user", ONE), ("d", LENGTH_MM),
    ("asl", AREA_MM2), ("asl-cg", LENGTH_M), ("asl-bar-count", ONE),
    ("ac", AREA_M2), ("fck", STRESS), ("n-ed", FORCE),
    ("n-prestress", FORCE), ("n-ed-comp", FORCE), ("m-ed-2023", MOMENT),
    ("m-prestress", MOMENT), ("centroid-x", LENGTH_M),
    ("centroid-y", LENGTH_M), ("model-2023", ONE), ("ddg", LENGTH_MM),
    ("fyd-flex", STRESS),
)
CONCRETE_2005_FIELDS = (
    ("k", ONE), ("rho-l", ONE), ("sigma-cp", STRESS), ("fcd", STRESS),
    ("crd-c", ONE), ("vmin", STRESS), ("v-basic", STRESS),
    ("v-floor", STRESS), ("k1", ONE), ("gamma-c", ONE),
    ("valid", ONE), ("vrd-c", FORCE),
)
CONCRETE_2023_FIELDS = (
    ("rho-l", ONE), ("z", LENGTH_MM), ("ddg", LENGTH_MM),
    ("fyd", STRESS), ("k-vp", ONE),
    ("d-kvp", LENGTH_MM), ("a-cs", LENGTH_MM), ("n-ed-tension", FORCE),
    ("m-ed", MOMENT), ("v-ed", FORCE), ("axial-applied", ONE),
    ("tau-basic", STRESS), ("tau-min", STRESS), ("tau-rdc", STRESS),
    ("gamma-v", ONE), ("valid", ONE), ("vrd-c", FORCE),
)
LINK_WRAPPER_FIELDS = (
    ("util", ONE), ("asw", AREA_MM2), ("asw-over-s", AREA_RATE),
    ("legs", ONE), ("dia", LENGTH_MM), ("spacing", LENGTH_MM),
    ("fywk", STRESS), ("cot-min", ONE), ("cot-max", ONE),
    ("longitudinal-force", FORCE), ("cot-limit-lo", ONE),
    ("cot-limit-hi", ONE), ("model-2023", ONE), ("out-of-limits", ONE),
    ("required", ONE), ("theta-mode", ONE),
)
LINK_2005_FIELDS = (
    ("cot", ONE), ("theta-deg", ANGLE), ("z", LENGTH_MM), ("fywd", STRESS),
    ("nu1", ONE), ("alpha-cw", ONE), ("sigma-cp", STRESS),
    ("fcd", STRESS), ("gamma-s", ONE), ("asw-over-s", AREA_RATE),
    ("vrd-s", FORCE), ("vrd-max", FORCE), ("vrd", FORCE),
    ("governs", ONE), ("valid", ONE),
)
LINK_2023_FIELDS = (
    ("cot", ONE), ("theta-deg", ANGLE), ("z", LENGTH_MM), ("fywd", STRESS),
    ("nu", ONE), ("nu1", ONE), ("alpha-cw", ONE), ("sigma-cp", STRESS),
    ("fcd", STRESS), ("gamma-s", ONE), ("asw-over-s", AREA_RATE),
    ("rho-w", ONE), ("tau-ed", STRESS), ("tau-rd-sy", STRESS),
    ("tau-rd-max", STRESS), ("sigma-cd", STRESS), ("nu-fcd", STRESS),
    ("vrd-s", FORCE), ("vrd-max", FORCE), ("vrd", FORCE),
    ("governs", ONE), ("valid", ONE),
)
CHORD_CONTEXT_FIELDS = (
    ("m-ed", MOMENT), ("m-rd", MOMENT), ("z", LENGTH_M),
    ("m-off", MOMENT), ("conditional", ONE), ("gets-shift", ONE),
)
CHORD_RESULT_FIELDS = (
    ("ftd-v", FORCE), ("ftd-t", FORCE), ("mv", MOMENT), ("mt", MOMENT),
    ("m-total", MOMENT), ("util", ONE), ("ok", ONE), ("capped", ONE),
    ("cap-shear-force", ONE), ("valid", ONE),
)
LINK_2005_EXTRA_FIELDS = (("delta-ftd", FORCE),)
ANGLE_LIMIT_FIELDS = (
    ("minimum", ONE), ("maximum", ONE), ("ductility-factor", ONE),
    ("axial-tension-applied", ONE), ("compression-extension-credited", ONE),
)


def _shared_inputs(rows: _Rows, shape: TraceShape) -> str:
    leaves: list[str] = []
    for ring_index, ring in enumerate(shape.blocks.geometry.rings):
        for point_index, _point in enumerate(ring):
            for suffix in ("x", "y"):
                leaves.append(rows.add(
                    f"geometry-ring-{ring_index:03d}-point-{point_index:04d}-{suffix}",
                    f"Concrete vertex {suffix}", LENGTH_M,
                    ROLE_USER_INPUT, INPUT_SOURCE,
                ))
    for kind, elements in (("bar", shape.blocks.geometry.bars), ("tendon", shape.blocks.geometry.tendons)):
        for index, _element in enumerate(elements):
            for suffix, unit in (("x", LENGTH_M), ("y", LENGTH_M), ("area", AREA_M2)):
                leaves.append(rows.add(
                    f"geometry-{kind}-{index:04d}-{suffix}", f"{kind.title()} {suffix}",
                    unit, ROLE_USER_INPUT, INPUT_SOURCE,
                ))
    for key, _value in shape.blocks.plastic_actions.values:
        leaves.append(rows.add(
            f"input-action-{_token(key)}", f"Original action {key}",
            FORCE if key == "P_pl" else MOMENT, ROLE_USER_INPUT, INPUT_SOURCE,
        ))
    shear_inputs = list(SHEAR_INPUTS)
    if shape.method.endswith(":2023"):
        shear_inputs.append(("aggregate-lower-size", LENGTH_MM))
    if shape.links:
        shear_inputs.extend(LINK_INPUTS)
    for name, unit in shear_inputs:
        leaves.append(rows.add(
            f"input-shear-{name}", f"Original shear input {name}", unit,
            ROLE_USER_INPUT, INPUT_SOURCE,
        ))
    for material in (shape.blocks.concrete, *shape.blocks.bars, *shape.blocks.tendons):
        prefix = _material_prefix(material)
        for name, _value in material.values:
            leaves.append(rows.add(
                f"{prefix}-{_token(name)}", f"Assigned {material.kind} {name}",
                _material_unit(name), ROLE_METHOD_VALUE, material.provenance.source,
            ))
    return rows.add(
        "normalised-shear-inputs", "Complete immutable CT-006 input state", ONE,
        ROLE_COMPUTED, GEOMETRY_SOURCE, *leaves,
    )


def _method_contract(rows: _Rows, shape: TraceShape) -> str:
    is_2023 = shape.method.endswith(":2023")
    is_dk = "DK NA:2024" in shape.method
    concrete_source = SOURCE_2023_CONCRETE if is_2023 else BASE_CONCRETE_SOURCE
    link_source = SOURCE_2023_LINK if is_2023 else BASE_LINK_SOURCE
    vmin_source = SOURCE_2023_CONCRETE if is_2023 else DK_VMIN_SOURCE if is_dk else BASE_CONCRETE_SOURCE
    nu_source = SOURCE_2023_LINK if is_2023 else DK_NU_SOURCE if is_dk else BASE_LINK_SOURCE
    method_steps = [
        rows.add("method-concrete-rule", "Concrete shear rule identity", ONE, ROLE_METHOD_VALUE, concrete_source),
        rows.add("method-vmin-rule", "Minimum concrete shear rule", ONE, ROLE_METHOD_VALUE, vmin_source),
    ]
    if shape.links:
        method_steps.extend((
            rows.add("method-link-rule", "Linked shear rule identity", ONE, ROLE_METHOD_VALUE, link_source),
            rows.add("method-nu-rule", "Compression-strut reduction rule", ONE, ROLE_METHOD_VALUE, nu_source),
            rows.add("method-selector-cardinality", "Minimax selector point count", ONE, ROLE_METHOD_VALUE, SELECTOR_SOURCE),
        ))
    return rows.add(
        "shear-method-vector", "Complete CT-006 method identity", ONE,
        ROLE_COMPUTED, SELECTOR_SOURCE, *method_steps,
    )


def _face_contract(rows: _Rows, shape: TraceShape, direction: DirectionShape, face_index: int, face: FaceShape) -> str:
    prefix = f"{direction.component}-face-{face_index:02d}"
    is_2023 = shape.method.endswith(":2023")
    concrete_source = SOURCE_2023_CONCRETE if is_2023 else BASE_CONCRETE_SOURCE
    link_source = SOURCE_2023_LINK if is_2023 else BASE_LINK_SOURCE
    field_ids: list[str] = []
    identity = rows.add(
        f"{prefix}-identity", f"{direction.component} face identity", ONE,
        ROLE_COMPUTED, GEOMETRY_SOURCE, "normalised-shear-inputs", "shear-method-vector",
    )
    for name, unit in COMMON_FACE_FIELDS:
        field_ids.append(rows.add(
            f"{prefix}-{name}", f"{direction.component} face {name}", unit,
            ROLE_COMPUTED, GEOMETRY_SOURCE, identity,
        ))
    for bar_index, _bar_id in enumerate(face.bar_ids):
        field_ids.append(rows.add(
            f"{prefix}-asl-bar-{bar_index:03d}", "Selected tension bar identity", ONE,
            ROLE_COMPUTED, GEOMETRY_SOURCE, identity,
        ))
    concrete_ids: dict[str, str] = {}
    concrete_fields = CONCRETE_2023_FIELDS if is_2023 else CONCRETE_2005_FIELDS
    for name, unit in concrete_fields:
        dependencies = [identity, "method-concrete-rule"]
        if name == "vmin":
            dependencies.append("method-vmin-rule")
        elif name == "v-floor" and "vmin" in concrete_ids:
            dependencies.append(concrete_ids["vmin"])
        elif name == "vrd-c":
            dependencies.extend(
                concrete_ids[key]
                for key in (("tau-rdc",) if is_2023 else ("v-basic", "v-floor"))
            )
        concrete_ids[name] = rows.add(
            f"{prefix}-concrete-{name}", f"{direction.component} concrete {name}", unit,
            ROLE_COMPUTED, concrete_source, *dependencies,
        )
        field_ids.append(concrete_ids[name])
    concrete_util = rows.add(
        f"{prefix}-concrete-util", f"{direction.component} concrete utilisation", ONE,
        ROLE_COMPUTED, STATUS_SOURCE, identity, concrete_ids["vrd-c"],
    )
    field_ids.append(concrete_util)
    if shape.links:
        chord_ids: dict[str, str] = {}
        if face.chord:
            for name, unit in CHORD_CONTEXT_FIELDS:
                chord_ids[name] = rows.add(
                    f"{prefix}-chord-{name}", f"{direction.component} chord {name}", unit,
                    ROLE_COMPUTED, SELECTOR_SOURCE, identity,
                )
                field_ids.append(chord_ids[name])
        link_ids: dict[str, str] = {}
        link_fields = LINK_2023_FIELDS if is_2023 else LINK_2005_FIELDS
        for name, unit in link_fields:
            dependencies = [identity, "method-link-rule"]
            if name in {"nu", "nu1"}:
                dependencies.append("method-nu-rule")
            elif name == "vrd-s":
                dependencies.append(link_ids["cot"])
            elif name == "vrd-max" and ("nu1" in link_ids or "nu" in link_ids):
                dependencies.extend((
                    link_ids["cot"],
                    link_ids.get("nu1", link_ids.get("nu")),
                ))
            elif name == "vrd":
                dependencies.extend(link_ids[key] for key in ("vrd-s", "vrd-max"))
            elif name == "cot":
                dependencies.append("method-selector-cardinality")
                dependencies.extend(chord_ids.values())
            result_source = SELECTOR_SOURCE if name in {"cot", "governs", "valid"} else link_source
            link_ids[name] = rows.add(
                f"{prefix}-link-result-{name}", f"{direction.component} linked result {name}", unit,
                ROLE_COMPUTED, result_source, *dependencies,
            )
            field_ids.append(link_ids[name])
        for name, unit in LINK_WRAPPER_FIELDS:
            dependencies = [identity, link_ids["vrd"]]
            if name == "longitudinal-force":
                dependencies.append(link_ids["cot"])
            elif name == "required":
                dependencies.append(concrete_ids["vrd-c"])
            wrapper_source = link_source if name == "longitudinal-force" else SELECTOR_SOURCE
            field_ids.append(rows.add(
                f"{prefix}-link-{name}", f"{direction.component} linked {name}", unit,
                ROLE_COMPUTED, wrapper_source, *dependencies,
            ))
        if not is_2023:
            field_ids.append(rows.add(
                f"{prefix}-link-delta-ftd", "Additional longitudinal shear force",
                FORCE, ROLE_COMPUTED, BASE_LINK_SOURCE,
                identity, link_ids["cot"], f"{prefix}-link-longitudinal-force",
            ))
        for name, unit in ANGLE_LIMIT_FIELDS:
            field_ids.append(rows.add(
                f"{prefix}-angle-limit-{name}", f"{direction.component} angle limit {name}", unit,
                ROLE_COMPUTED, link_source, identity,
            ))
        if face.chord:
            for name, unit in CHORD_RESULT_FIELDS:
                dependencies = [identity, link_ids["cot"], *chord_ids.values()]
                if name == "ftd-v":
                    dependencies.append(f"{prefix}-link-longitudinal-force")
                chord_ids[name] = rows.add(
                    f"{prefix}-chord-result-{name}",
                    f"{direction.component} chord result {name}", unit,
                    ROLE_COMPUTED, SELECTOR_SOURCE, *dependencies,
                )
                field_ids.append(chord_ids[name])
    applicable_util = (
        f"{prefix}-link-util" if shape.links else concrete_util
    )
    metric = rows.add(
        f"{prefix}-shear-metric", "Applicable face shear utilisation", ONE,
        ROLE_COMPUTED, STATUS_SOURCE, applicable_util,
    )
    status = rows.add(
        f"{prefix}-shear-status", "Genuine face PASS or FAIL", ONE,
        ROLE_COMPUTED, STATUS_SOURCE, metric,
    )
    return rows.add(
        f"{prefix}-evidence", f"Complete {direction.component} face evidence", ONE,
        ROLE_COMPUTED, STATUS_SOURCE, identity, *field_ids, metric, status,
    )


def expected_step_contract(shape: TraceShape) -> tuple[StepSpec, ...]:
    rows = _Rows()
    if shape.branch == BRANCH_FAILED:
        failure = rows.add(
            "authoritative-shear-failure", "Original-input CT-006 failure", ONE,
            ROLE_METHOD_VALUE, FAILURE_SOURCE,
        )
        rows.add(
            "ct-006-directional-shear-result", "CT-006 failed result", ONE,
            ROLE_FINAL, FAILURE_SOURCE, failure,
        )
        return tuple(rows.rows)
    normalised = _shared_inputs(rows, shape)
    method = _method_contract(rows, shape)
    direction_evidence = []
    for direction in shape.directions:
        faces = [
            _face_contract(rows, shape, direction, index, face)
            for index, face in enumerate(direction.faces)
        ]
        prefix = direction.component
        selected = rows.add(
            f"{prefix}-governing-face", f"{prefix} governing face", ONE,
            ROLE_COMPUTED, STATUS_SOURCE, *faces,
        )
        status = rows.add(
            f"{prefix}-aggregate-status", f"{prefix} aggregate status", ONE,
            ROLE_COMPUTED, STATUS_SOURCE, *faces,
        )
        metric = rows.add(
            f"{prefix}-governing-metric", f"{prefix} governing metric", ONE,
            ROLE_COMPUTED, STATUS_SOURCE, selected, status,
        )
        direction_evidence.append(rows.add(
            f"{prefix}-direction-evidence", f"Complete {prefix} direction evidence", ONE,
            ROLE_COMPUTED, STATUS_SOURCE, *faces, selected, status, metric,
        ))
    rows.add(
        "ct-006-directional-shear-result", "Complete CT-006 directional shear result", ONE,
        ROLE_FINAL, STATUS_SOURCE, normalised, method, *direction_evidence,
    )
    return tuple(rows.rows)


def _source_contract(source: TraceSource) -> TraceSourceContract:
    return TraceSourceContract(source.kind, source.method_id, source.edition)


def expected_registry(shape: TraceShape) -> TraceRegistryContract:
    specs = expected_step_contract(shape)
    member = TraceMemberContract(
        member_id=MEMBER_ID,
        calculation_id=shape.calculation_id,
        coverage_id=COVERAGE_ID,
        method_id=shape.method_id,
        axes=shape.axes,
        sources=frozenset(_source_contract(spec.source) for spec in specs),
        result_states=frozenset({RESULT_FAILED if shape.branch == BRANCH_FAILED else RESULT_FINITE}),
        step_ids=tuple(spec.step_id for spec in specs),
        step_dependencies=tuple((spec.step_id, spec.dependencies) for spec in specs),
        step_metadata=tuple(
            TraceStepMetadataContract(spec.step_id, spec.quantity_role, spec.source)
            for spec in specs
        ),
    )
    return TraceRegistryContract(REGISTRY_ID, (TraceFamilyContract(FAMILY_ID, (member,)),))
