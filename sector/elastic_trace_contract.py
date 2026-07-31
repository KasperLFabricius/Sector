"""Independent CT-005 identity, shape, step, and registry declarations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .calculation_trace import (
    RESULT_FAILED,
    RESULT_FINITE,
    RESULT_POSITIVE_INFINITY,
    ROLE_COMPUTED,
    ROLE_FINAL,
    ROLE_METHOD_VALUE,
    ROLE_USER_INPUT,
    SOURCE_INPUT,
    SOURCE_PROJECT,
    TraceAxis,
    TraceSource,
    TraceUnit,
    trace_identity_token,
)
from .section_trace_blocks import (
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


COVERAGE_ID = "ct-005"
FAMILY_ID = "ct-005-elastic-section-response"
MEMBER_ID = "elastic-section-response-first-cracking"
REGISTRY_ID = "sector-ct-005-elastic-section-response-v1"
METHOD_ID = "sector-transformed-section-equilibrium-first-cracking"

BRANCH_FINITE = "finite-first-cracking"
BRANCH_INFINITE = "no-finite-first-cracking"
BRANCH_FAILED = "failed-elastic-response"
BRANCHES = frozenset({BRANCH_FINITE, BRANCH_INFINITE, BRANCH_FAILED})

INPUT_SOURCE = TraceSource(SOURCE_INPUT, "sector-section-input")
EQUILIBRIUM_SOURCE = TraceSource(
    SOURCE_PROJECT, "sector-transformed-section-equilibrium"
)
CREEP_SOURCE = TraceSource(
    SOURCE_PROJECT, "sector-combined-creep-superposition"
)
CRACKING_SOURCE = TraceSource(
    SOURCE_PROJECT, "sector-fixed-prestress-first-cracking"
)

ONE = TraceUnit("1", "scalar")
LENGTH = TraceUnit("m", "length")
AREA = TraceUnit("m2", "area")
FIRST_MOMENT = TraceUnit("m3", "first_moment")
SECOND_MOMENT = TraceUnit("m4", "second_moment")
FORCE = TraceUnit("kN", "force")
MOMENT = TraceUnit("kNm", "moment")
STRESS = TraceUnit("MPa", "stress")
STRESS_GPA = TraceUnit("GPa", "stress")
RAW_STRESS = TraceUnit("kN/m2", "stress")
RAW_GRADIENT = TraceUnit("kN/m3", "stress_gradient")
STRAIN = TraceUnit("permille", "strain")

ACTION_KEYS = (
    "P_el_l",
    "Mx_el_l",
    "My_el_l",
    "P_el_s",
    "Mx_el_s",
    "My_el_s",
)
INPUT_KEYS = ("conc_Ec", "el_phi", "sls_fctm")
PLANE_COMPONENTS = ("q0", "qx", "qy")
PROPERTY_FIELDS = ("area", "cx", "cy", "Ix", "Iy", "Ixy")
RESULTANT_COMPONENTS = ("n", "mx", "my")


@dataclass(frozen=True, slots=True)
class TraceShape:
    blocks: SectionTraceBlocks
    context_token: str
    axes: tuple[TraceAxis, ...]
    branch: str
    cracked: bool | None

    @property
    def calculation_id(self) -> str:
        return f"elastic.{self.context_token}.section-response-first-cracking"

    @property
    def vertex_count(self) -> int:
        return sum(len(ring) for ring in self.blocks.geometry.rings)

    @property
    def element_count(self) -> int:
        return len(self.blocks.geometry.bars) + len(self.blocks.geometry.tendons)


def trace_shape(
    blocks: SectionTraceBlocks,
    context: Mapping[str, Any],
    branch: str,
    cracked: bool | None,
) -> TraceShape:
    """Select shape from immutable inputs and authoritative replay state only."""

    if branch not in BRANCHES:
        raise ValueError("unknown CT-005 branch")
    if branch == BRANCH_FAILED:
        if cracked is not None:
            raise ValueError("failed CT-005 cannot declare a section state")
        section_state = "unknown"
    else:
        if type(cracked) is not bool:
            raise ValueError("finite CT-005 needs the authoritative cracked state")
        if branch == BRANCH_INFINITE and cracked:
            raise ValueError("positive-infinity first cracking cannot be cracked")
        section_state = "cracked" if cracked else "uncracked"
    axes = context_axes(
        context,
        action_path="long-plus-short",
        bar_cardinality=str(len(blocks.geometry.bars)),
        branch=branch,
        fibre_cardinality=str(sum(len(ring) for ring in blocks.geometry.rings)),
        fibre_set="all-concrete-vertices",
        ring_cardinality=str(len(blocks.geometry.rings)),
        section_state=section_state,
        sign="tension-positive-n",
        tendon_cardinality=str(len(blocks.geometry.tendons)),
    )
    return TraceShape(blocks, context_id(context), axes, branch, cracked)


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

    def add(
        self,
        step_id: str,
        title: str,
        unit: TraceUnit,
        role: str,
        source: TraceSource,
        *dependencies: str,
    ) -> str:
        if step_id in self.ids:
            raise ValueError(f"duplicate CT-005 step {step_id}")
        self.ids.add(step_id)
        self.rows.append(
            StepSpec(step_id, title, unit, role, source, tuple(dependencies))
        )
        return step_id


def _token(value: str) -> str:
    return trace_identity_token(value)


def action_step_id(key: str) -> str:
    return f"input-action-{_token(key)}"


def scalar_step_id(key: str) -> str:
    return f"input-elastic-{_token(key)}"


def geometry_point_ids(
    ring_index: int, point_index: int
) -> tuple[str, str]:
    prefix = f"geometry-ring-{ring_index:03d}-point-{point_index:04d}"
    return f"{prefix}-x", f"{prefix}-y"


def material_prefix(material: MaterialBlock) -> str:
    return (
        f"material-{material.kind}-{_token(material.element_id)}-"
        f"{_token(material.material_id)}"
    )


def _geometry(rows: _Rows, shape: TraceShape) -> str:
    leaves: list[str] = []
    for ring_index, ring in enumerate(shape.blocks.geometry.rings):
        for point_index, _point in enumerate(ring):
            x_id, y_id = geometry_point_ids(ring_index, point_index)
            leaves.append(rows.add(
                x_id, "Concrete vertex x", LENGTH,
                ROLE_USER_INPUT, INPUT_SOURCE,
            ))
            leaves.append(rows.add(
                y_id, "Concrete vertex y", LENGTH,
                ROLE_USER_INPUT, INPUT_SOURCE,
            ))
    for kind, elements in (
        ("bar", shape.blocks.geometry.bars),
        ("tendon", shape.blocks.geometry.tendons),
    ):
        for index, _element in enumerate(elements):
            prefix = f"geometry-{kind}-{index:04d}"
            for suffix, unit in (("x", LENGTH), ("y", LENGTH), ("area", AREA)):
                leaves.append(rows.add(
                    f"{prefix}-{suffix}", f"{kind.title()} {suffix}", unit,
                    ROLE_USER_INPUT, INPUT_SOURCE,
                ))
    return rows.add(
        "geometry-vector", "Immutable elastic section geometry", ONE,
        ROLE_COMPUTED, EQUILIBRIUM_SOURCE, *leaves,
    )


def _materials(rows: _Rows, shape: TraceShape) -> str:
    leaves: list[str] = []
    for material in (*shape.blocks.bars, *shape.blocks.tendons):
        values = dict(material.values)
        prefix = material_prefix(material)
        leaves.append(rows.add(
            f"{prefix}-{_token('Es')}",
            f"{material.kind.title()} assigned elastic modulus",
            STRESS, ROLE_METHOD_VALUE, material.provenance.source,
        ))
        if material.kind == "tendon":
            if "IS" not in values:
                raise ValueError("tendon material needs initial strain")
            leaves.append(rows.add(
                f"{prefix}-{_token('IS')}",
                "Tendon assigned effective initial strain",
                ONE, ROLE_METHOD_VALUE, material.provenance.source,
            ))
    return rows.add(
        "elastic-material-vector", "Aligned elastic material assignments", ONE,
        ROLE_COMPUTED, EQUILIBRIUM_SOURCE,
        *(leaves or ["reference-steel-modulus"]),
    )


def _inputs(rows: _Rows, shape: TraceShape) -> None:
    action_ids: list[str] = []
    for key in ACTION_KEYS:
        action_ids.append(rows.add(
            action_step_id(key), f"Original action {key}",
            FORCE if key.startswith("P_") else MOMENT,
            ROLE_USER_INPUT, INPUT_SOURCE,
        ))
    ec = rows.add(
        scalar_step_id("conc_Ec"), "Concrete elastic modulus input", STRESS_GPA,
        ROLE_USER_INPUT, INPUT_SOURCE,
    )
    phi = rows.add(
        scalar_step_id("el_phi"), "Creep coefficient input", ONE,
        ROLE_USER_INPUT, INPUT_SOURCE,
    )
    fctm = rows.add(
        scalar_step_id("sls_fctm"), "Mean tensile strength input", STRESS,
        ROLE_USER_INPUT, INPUT_SOURCE,
    )
    reference = rows.add(
        "reference-steel-modulus", "Sector reference steel modulus", STRESS,
        ROLE_METHOD_VALUE, EQUILIBRIUM_SOURCE,
    )
    geometry = _geometry(rows, shape)
    materials = _materials(rows, shape)
    ns = rows.add(
        "short-term-modular-ratio", "Short-term reference modular ratio", ONE,
        ROLE_COMPUTED, EQUILIBRIUM_SOURCE, reference, ec,
    )
    nl = rows.add(
        "long-term-modular-ratio", "Long-term reference modular ratio", ONE,
        ROLE_COMPUTED, CREEP_SOURCE, reference, ec, phi,
    )
    rows.add(
        "normalised-elastic-inputs", "Complete CT-005 solver input state", ONE,
        ROLE_COMPUTED, EQUILIBRIUM_SOURCE,
        *action_ids, ec, phi, fctm, reference, geometry, materials, ns, nl,
    )


def _plane(
    rows: _Rows,
    prefix: str,
    title: str,
    source: TraceSource,
    *dependencies: str,
) -> str:
    components = []
    for component in PLANE_COMPONENTS:
        components.append(rows.add(
            f"{prefix}-plane-{component}", f"{title} {component}",
            RAW_STRESS if component == "q0" else RAW_GRADIENT,
            ROLE_COMPUTED, source, *dependencies,
        ))
    return rows.add(
        f"{prefix}-plane-evidence", f"{title} plane evidence", ONE,
        ROLE_COMPUTED, source, *components,
    )


def _compression_moments(
    rows: _Rows, prefix: str, plane: str
) -> str:
    fields = (
        ("area", AREA), ("sx", FIRST_MOMENT), ("sy", FIRST_MOMENT),
        ("sxx", SECOND_MOMENT), ("syy", SECOND_MOMENT),
        ("sxy", SECOND_MOMENT),
    )
    ids = [rows.add(
        f"{prefix}-compression-{name}",
        f"{prefix.title()} concrete compression-zone {name}", unit,
        ROLE_COMPUTED, EQUILIBRIUM_SOURCE,
        plane, "geometry-vector",
    ) for name, unit in fields]
    return rows.add(
        f"{prefix}-compression-moments", f"{prefix.title()} compression moments", ONE,
        ROLE_COMPUTED, EQUILIBRIUM_SOURCE, *ids,
    )


def _equilibrium(
    rows: _Rows,
    prefix: str,
    plane: str,
    moments: str,
    contributions: tuple[str, ...],
) -> str:
    evidence = []
    for contribution in contributions:
        component_ids = []
        source = CREEP_SOURCE if contribution.startswith("neutralising") else EQUILIBRIUM_SOURCE
        for component in RESULTANT_COMPONENTS:
            component_ids.append(rows.add(
                f"{prefix}-{contribution}-{component}",
                f"{prefix.title()} {contribution} {component} resultant",
                FORCE if component == "n" else MOMENT,
                ROLE_COMPUTED, source,
                plane, moments, "normalised-elastic-inputs",
            ))
        evidence.append(rows.add(
            f"{prefix}-{contribution}-resultant",
            f"{prefix.title()} {contribution} resultant", ONE,
            ROLE_COMPUTED, source, *component_ids,
        ))
    residuals = [rows.add(
        f"{prefix}-equilibrium-residual-{component}",
        f"{prefix.title()} equilibrium residual {component}",
        FORCE if component == "n" else MOMENT,
        ROLE_COMPUTED, EQUILIBRIUM_SOURCE,
        *evidence, "normalised-elastic-inputs",
    ) for component in RESULTANT_COMPONENTS]
    return rows.add(
        f"{prefix}-equilibrium-evidence", f"{prefix.title()} exact equilibrium", ONE,
        ROLE_COMPUTED, EQUILIBRIUM_SOURCE, *evidence, *residuals,
    )


def _properties(
    rows: _Rows, prefix: str, title: str, *dependencies: str
) -> str:
    ids = []
    for field in PROPERTY_FIELDS:
        unit = AREA if field == "area" else LENGTH if field in {"cx", "cy"} else SECOND_MOMENT
        ids.append(rows.add(
            f"{prefix}-{field.lower()}", f"{title} {field}", unit,
            ROLE_COMPUTED, EQUILIBRIUM_SOURCE, *dependencies,
        ))
    return rows.add(
        f"{prefix}-evidence", f"{title} evidence", ONE,
        ROLE_COMPUTED, EQUILIBRIUM_SOURCE, *ids,
    )


def _response_contract(rows: _Rows, shape: TraceShape) -> str:
    long_plane = _plane(
        rows, "long-cracked", "Long-term cracked response",
        EQUILIBRIUM_SOURCE, "normalised-elastic-inputs",
    )
    short_plane = _plane(
        rows, "total-cracked", "Combined cracked response",
        CREEP_SOURCE, "normalised-elastic-inputs", long_plane,
    )
    long_moments = _compression_moments(rows, "long", long_plane)
    total_moments = _compression_moments(rows, "total", short_plane)
    long_equilibrium = _equilibrium(
        rows, "long", long_plane, long_moments,
        ("concrete", "bar", "tendon", "prestress"),
    )
    total_equilibrium = _equilibrium(
        rows, "total", short_plane, total_moments,
        (
            "concrete", "bar", "tendon", "prestress",
            "neutralising-bar", "neutralising-tendon",
        ),
    )

    element_evidence = []
    for kind, materials in (("bar", shape.blocks.bars), ("tendon", shape.blocks.tendons)):
        for index, material in enumerate(materials):
            prefix = f"element-{kind}-{index:04d}"
            material_id = f"{material_prefix(material)}-{_token('Es')}"
            values = []
            for field in ("long", "rst1", "difference", "total"):
                values.append(rows.add(
                    f"{prefix}-{field}-stress", f"{kind.title()} {index + 1} {field} stress",
                    STRESS, ROLE_COMPUTED, CREEP_SOURCE,
                    long_plane, short_plane, material_id,
                    long_equilibrium, total_equilibrium,
                ))
            values.append(rows.add(
                f"{prefix}-total-strain", f"{kind.title()} {index + 1} total strain",
                STRAIN, ROLE_COMPUTED, EQUILIBRIUM_SOURCE,
                values[-1], material_id,
            ))
            element_evidence.append(rows.add(
                f"{prefix}-evidence", f"{kind.title()} {index + 1} response evidence",
                ONE, ROLE_COMPUTED, EQUILIBRIUM_SOURCE, *values,
            ))
    elements = rows.add(
        "element-response-evidence", "All reinforcement and tendon responses", ONE,
        ROLE_COMPUTED, EQUILIBRIUM_SOURCE,
        *(element_evidence or (long_equilibrium, total_equilibrium)),
    )

    fibres = []
    global_index = 0
    for ring_index, ring in enumerate(shape.blocks.geometry.rings):
        for point_index, _point in enumerate(ring):
            x_id, y_id = geometry_point_ids(ring_index, point_index)
            prefix = f"response-fibre-{global_index:04d}"
            raw = rows.add(
                f"{prefix}-raw-stress", "Combined cracked concrete fibre stress",
                RAW_STRESS, ROLE_COMPUTED, EQUILIBRIUM_SOURCE,
                short_plane, x_id, y_id,
            )
            strain = rows.add(
                f"{prefix}-strain", "Concrete fibre total compatible strain", STRAIN,
                ROLE_COMPUTED, CREEP_SOURCE,
                raw, long_plane, x_id, y_id,
                scalar_step_id("el_phi"), scalar_step_id("conc_Ec"),
            )
            stress = rows.add(
                f"{prefix}-carried-stress", "Concrete fibre carried stress", STRESS,
                ROLE_COMPUTED, EQUILIBRIUM_SOURCE, raw,
            )
            fibres.append(rows.add(
                f"{prefix}-evidence", "Concrete fibre response evidence", ONE,
                ROLE_COMPUTED, EQUILIBRIUM_SOURCE, raw, strain, stress,
            ))
            global_index += 1
    fibre_evidence = rows.add(
        "concrete-fibre-response-evidence", "All concrete fibre responses", ONE,
        ROLE_COMPUTED, EQUILIBRIUM_SOURCE, *fibres,
    )

    extrema = []
    for step_id, title, unit in (
        ("maximum-concrete-compression", "Maximum concrete compression", STRESS),
        ("maximum-concrete-point", "Governing concrete point number", ONE),
        ("maximum-concrete-x", "Governing concrete point x", LENGTH),
        ("maximum-concrete-y", "Governing concrete point y", LENGTH),
        ("maximum-element-tension", "Maximum reinforcement or tendon tension", STRESS),
        ("maximum-element-index", "Governing element number", ONE),
        ("maximum-element-kind", "Governing element type code", ONE),
        ("maximum-bar-tension", "Maximum reinforcement tension", STRESS),
        ("maximum-bar-index", "Governing reinforcement number", ONE),
        ("maximum-tendon-tension", "Maximum tendon tension", STRESS),
        ("maximum-tendon-index", "Governing tendon number", ONE),
        ("neutral-axis-x", "Neutral-axis x intercept", LENGTH),
        ("neutral-axis-y", "Neutral-axis y intercept", LENGTH),
    ):
        extrema.append(rows.add(
            step_id, title, unit, ROLE_COMPUTED, EQUILIBRIUM_SOURCE,
            fibre_evidence, elements, short_plane,
        ))
    extrema_evidence = rows.add(
        "response-extrema-evidence", "Published response extrema and identities", ONE,
        ROLE_COMPUTED, EQUILIBRIUM_SOURCE, *extrema,
    )

    props_un = _properties(
        rows, "uncracked-properties", "Uncracked transformed property",
        "normalised-elastic-inputs",
    )
    property_evidence = [props_un]
    if shape.cracked:
        property_evidence.append(_properties(
            rows, "cracked-properties", "Cracked transformed property",
            long_plane, short_plane, "normalised-elastic-inputs",
        ))
    properties = rows.add(
        "transformed-properties-evidence", "Retained transformed properties", ONE,
        ROLE_COMPUTED, EQUILIBRIUM_SOURCE, *property_evidence,
    )
    return rows.add(
        "elastic-response-evidence", "Complete retained elastic response", ONE,
        ROLE_COMPUTED, EQUILIBRIUM_SOURCE,
        long_equilibrium, total_equilibrium, elements, fibre_evidence,
        extrema_evidence, properties,
    )


def _cracking_contract(rows: _Rows, shape: TraceShape) -> str:
    long_total = _plane(
        rows, "stage-i-long-total", "Stage-I long total",
        CRACKING_SOURCE, "normalised-elastic-inputs",
    )
    long_external = _plane(
        rows, "stage-i-long-external", "Stage-I long external",
        CRACKING_SOURCE, "normalised-elastic-inputs",
    )
    short_external = _plane(
        rows, "stage-i-short-external", "Stage-I short external",
        CRACKING_SOURCE, "normalised-elastic-inputs",
    )
    path_evidence = []
    for path in ("long", "total"):
        factors = []
        global_index = 0
        for ring_index, ring in enumerate(shape.blocks.geometry.rings):
            for point_index, _point in enumerate(ring):
                x_id, y_id = geometry_point_ids(ring_index, point_index)
                prefix = f"cracking-{path}-fibre-{global_index:04d}"
                pre = rows.add(
                    f"{prefix}-fixed-prestress", "Fixed prestress fibre stress", STRESS,
                    ROLE_COMPUTED, CRACKING_SOURCE,
                    long_total, long_external, x_id, y_id,
                )
                ext_deps = [long_external, x_id, y_id]
                if path == "total":
                    ext_deps.append(short_external)
                ext = rows.add(
                    f"{prefix}-external-stress", "External tensile stress increment", STRESS,
                    ROLE_COMPUTED, CRACKING_SOURCE, *ext_deps,
                )
                total = rows.add(
                    f"{prefix}-total-stress", "Stage-I total fibre stress", STRESS,
                    ROLE_COMPUTED, CRACKING_SOURCE, pre, ext,
                )
                factor = rows.add(
                    f"{prefix}-factor", "Fibre first-cracking load factor", ONE,
                    ROLE_COMPUTED, CRACKING_SOURCE,
                    scalar_step_id("sls_fctm"), pre, ext,
                )
                factors.append(rows.add(
                    f"{prefix}-evidence", "Fibre first-cracking evidence", ONE,
                    ROLE_COMPUTED, CRACKING_SOURCE, pre, ext, total, factor,
                ))
                global_index += 1
        sigma = rows.add(
            f"cracking-{path}-sigma-ct", f"{path.title()} Stage-I peak tension", STRESS,
            ROLE_COMPUTED, CRACKING_SOURCE, *factors,
        )
        factor = rows.add(
            f"cracking-{path}-factor", f"{path.title()} first-cracking factor", ONE,
            ROLE_COMPUTED, CRACKING_SOURCE, *factors,
        )
        fibre = rows.add(
            f"cracking-{path}-governing-fibre", f"{path.title()} governing fibre", ONE,
            ROLE_COMPUTED, CRACKING_SOURCE, *factors,
        )
        path_evidence.append(rows.add(
            f"cracking-{path}-path-evidence", f"{path.title()} action-path evidence", ONE,
            ROLE_COMPUTED, CRACKING_SOURCE, sigma, factor, fibre,
        ))
    governing = []
    for step_id, title, unit in (
        ("governing-cracking-path", "Strict-tie governing action path", ONE),
        ("governing-cracking-fibre", "Governing concrete fibre", ONE),
        ("governing-sigma-ct", "Governing Stage-I tension", STRESS),
        ("governing-cracking-factor", "Governing first-cracking factor", ONE),
        ("retained-cracked-state", "Retained cracked state", ONE),
    ):
        governing.append(rows.add(
            step_id, title, unit, ROLE_COMPUTED, CRACKING_SOURCE,
            *path_evidence,
        ))
    return rows.add(
        "first-cracking-evidence", "Complete first-cracking reconstruction", ONE,
        ROLE_COMPUTED, CRACKING_SOURCE, *path_evidence, *governing,
    )


def _failure_contract(rows: _Rows) -> None:
    flags = []
    for name in ("combined-cracked", "stage-i-long-total", "stage-i-long-external", "stage-i-short-external"):
        source = EQUILIBRIUM_SOURCE if name == "combined-cracked" else CRACKING_SOURCE
        flags.append(rows.add(
            f"authoritative-{name}-converged", f"Authoritative {name} convergence", ONE,
            ROLE_COMPUTED, source, "normalised-elastic-inputs",
        ))
    failure = rows.add(
        "elastic-failure-state", "Explicit elastic reconstruction failure", ONE,
        ROLE_COMPUTED, EQUILIBRIUM_SOURCE, *flags,
    )
    rows.add(
        "ct-005-elastic-first-cracking-result", "CT-005 failed result", ONE,
        ROLE_FINAL, EQUILIBRIUM_SOURCE,
        "normalised-elastic-inputs", failure,
    )


def expected_step_contract(shape: TraceShape) -> tuple[StepSpec, ...]:
    rows = _Rows()
    _inputs(rows, shape)
    if shape.branch == BRANCH_FAILED:
        _failure_contract(rows)
    else:
        response = _response_contract(rows, shape)
        cracking = _cracking_contract(rows, shape)
        rows.add(
            "ct-005-elastic-first-cracking-result",
            "CT-005 elastic response and first-cracking result", ONE,
            ROLE_FINAL, CRACKING_SOURCE,
            "normalised-elastic-inputs", response, cracking,
        )
    return tuple(rows.rows)


def _source_contract(source: TraceSource) -> TraceSourceContract:
    return TraceSourceContract(source.kind, source.method_id, source.edition)


def expected_registry(shape: TraceShape) -> TraceRegistryContract:
    """Declare the complete CT-005 family without inspecting candidate trace data."""

    specs = expected_step_contract(shape)
    final_state = (
        RESULT_FAILED if shape.branch == BRANCH_FAILED
        else RESULT_POSITIVE_INFINITY if shape.branch == BRANCH_INFINITE
        else RESULT_FINITE
    )
    member = TraceMemberContract(
        member_id=MEMBER_ID,
        calculation_id=shape.calculation_id,
        coverage_id=COVERAGE_ID,
        method_id=METHOD_ID,
        axes=shape.axes,
        sources=frozenset(_source_contract(spec.source) for spec in specs),
        result_states=frozenset({final_state}),
        step_ids=tuple(spec.step_id for spec in specs),
        step_dependencies=tuple(
            (spec.step_id, spec.dependencies) for spec in specs
        ),
        step_metadata=tuple(
            TraceStepMetadataContract(
                spec.step_id, spec.quantity_role, spec.source
            )
            for spec in specs
        ),
    )
    return TraceRegistryContract(
        REGISTRY_ID,
        (TraceFamilyContract(FAMILY_ID, (member,)),),
    )
