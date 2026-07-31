"""Immutable input/provenance blocks shared by section trace builders."""
from __future__ import annotations
import dataclasses
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from . import codes
from .calculation_trace import (
    SOURCE_PROJECT,
    SOURCE_STANDARD,
    SourceCitation,
    TraceAxis,
    TraceSource,
    trace_identity_token,
)
from .section import Section
DOC_2005 = "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010"
DOC_2023 = "DS/EN 1992-1-1:2023"
_CITATIONS = {
    "concrete": {
        "2005": SourceCitation(DOC_2005, "3.1.7", "constitutive law"),
        "2023": SourceCitation(DOC_2023, "5.1.6", "constitutive law"),
    },
    "bar": {
        "2005": SourceCitation(DOC_2005, "3.2.7", "design stress-strain law"),
        "2023": SourceCitation(DOC_2023, "5.2.4", "design stress-strain law"),
    },
    "tendon": {
        "2005": SourceCitation(DOC_2005, "3.3.6", "design stress-strain law"),
        "2023": SourceCitation(DOC_2023, "5.3.3", "design stress-strain law"),
    },
}
@dataclass(frozen=True, slots=True)
class GeometryElement:
    x: float
    y: float
    area: float
@dataclass(frozen=True, slots=True)
class GeometryBlock:
    rings: tuple[tuple[tuple[float, float], ...], ...]
    bars: tuple[GeometryElement, ...]
    tendons: tuple[GeometryElement, ...]
    @classmethod
    def from_section(cls, section: Section) -> "GeometryBlock":
        section.require_valid_geometry()
        rings = tuple(
            tuple((float(point[0]), float(point[1])) for point in ring)
            for ring in section.concrete
        )
        convert = lambda items: tuple(  # noqa: E731 - compact immutable conversion
            GeometryElement(float(item.x), float(item.y), float(item.area))
            for item in items
        )
        return cls(rings, convert(section.bars), convert(section.tendons))
@dataclass(frozen=True, slots=True)
class ProvenanceBlock:
    source: TraceSource
    standard_key: str | None
@dataclass(frozen=True, slots=True)
class ActionBlock:
    values: tuple[tuple[str, float], ...]
@dataclass(frozen=True, slots=True)
class MaterialBlock:
    kind: str
    element_id: str
    material_id: str
    values: tuple[tuple[str, float], ...]
    provenance: ProvenanceBlock
@dataclass(frozen=True, slots=True)
class SectionTraceBlocks:
    geometry: GeometryBlock
    plastic_actions: ActionBlock
    concrete: MaterialBlock
    bars: tuple[MaterialBlock, ...]
    tendons: tuple[MaterialBlock, ...]
    plastic_method_id: str
def _slug(value: Any) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")
    return text or "item"
def context_id(context: Mapping[str, Any]) -> str:
    if not context:
        return "section"
    return ".".join(
        f"{_slug(key)}-{trace_identity_token(str(value))}"
        for key, value in sorted(context.items())
    )
def context_axes(context: Mapping[str, Any], **extra: str) -> tuple[TraceAxis, ...]:
    values = {str(key): str(value) for key, value in context.items()}
    values.update(extra)
    return tuple(TraceAxis(_slug(key), value) for key, value in sorted(values.items()))
def _code(preset: Any) -> codes.DesignCode | None:
    value = str(preset or "")
    for code in codes.CODES.values():
        if value in {code.label, code.key}:
            return code
    return None
def _provenance(kind: str, preset: Any) -> ProvenanceBlock:
    code = _code(preset)
    if code is None:
        return ProvenanceBlock(
            TraceSource(SOURCE_PROJECT, f"project-{kind}-law"),
            None,
        )
    key = code.key.lower()
    family = "2023" if code is codes.EC2_2023 else "2005"
    return ProvenanceBlock(
        TraceSource(
            SOURCE_STANDARD,
            f"{key}-{kind}-law",
            code.label,
            _CITATIONS[kind][family],
        ),
        key,
    )
def _law_values(law: Any) -> tuple[tuple[str, float], ...]:
    values = []
    for field in dataclasses.fields(law):
        raw = getattr(law, field.name)
        if type(raw) is bool:
            raw = 1.0 if raw else 0.0
        if type(raw) not in {int, float} or not math.isfinite(float(raw)):
            raise ValueError(f"{field.name} must be a finite non-Boolean number")
        values.append((field.name, float(raw)))
    return tuple(values)
def _catalog_preset(inp: Mapping[str, Any], kind: str, index: int) -> tuple[str, str, bool]:
    element_key = "bar_elements" if kind == "bar" else "tendon_elements"
    catalog_key = "mild_material_catalog" if kind == "bar" else "prestress_material_catalog"
    elements = tuple(inp.get(element_key) or ())
    element = elements[index] if index < len(elements) and isinstance(elements[index], Mapping) else {}
    element_id = str(element.get("id") or f"{kind}-{index + 1:03d}")
    material_id = str(element.get("material_id") or "")
    catalog = inp.get(catalog_key)
    items = catalog.get("items", ()) if isinstance(catalog, Mapping) else ()
    selected_id = material_id or (
        str(inp.get("capacity_steel_material_id") or "") if kind == "bar" else ""
    )
    for item in items:
        if isinstance(item, Mapping) and str(item.get("id") or "") == selected_id:
            return element_id, str(item.get("preset") or ""), True
    fallback = inp.get("mild_preset") if kind == "bar" else inp.get("prestress_preset")
    return element_id, str(fallback or ""), False
def _materials(
    inp: Mapping[str, Any],
    *,
    kind: str,
    count: int,
    default: Any,
) -> tuple[MaterialBlock, ...]:
    specific = inp.get("bar_materials" if kind == "bar" else "tendon_materials")
    laws: Sequence[Any] = tuple(specific) if specific is not None else (default,) * count
    if len(laws) != count or any(law is None for law in laws):
        raise ValueError(f"need {count} aligned {kind} material laws")
    heterogeneous = specific is not None and len({_law_values(law) for law in laws}) > 1
    blocks = []
    for index, law in enumerate(laws):
        element_id, preset, aligned = _catalog_preset(inp, kind, index)
        if heterogeneous and not aligned:
            raise ValueError(f"heterogeneous {kind} laws need aligned catalog provenance")
        elements = tuple(inp.get("bar_elements" if kind == "bar" else "tendon_elements") or ())
        element = elements[index] if index < len(elements) and isinstance(elements[index], Mapping) else {}
        blocks.append(
            MaterialBlock(
                kind,
                element_id,
                str(element.get("material_id") or preset or element_id),
                _law_values(law),
                _provenance(kind, preset),
            )
        )
    return tuple(blocks)
def section_trace_blocks(inp: Mapping[str, Any]) -> SectionTraceBlocks:
    geometry = GeometryBlock.from_section(inp["section"])
    action_values = tuple(
        (key, float(inp.get(key, 0.0))) for key in ("P_pl", "Mx_pl", "My_pl")
    )
    if any(type(inp.get(key, 0.0)) is bool or not math.isfinite(value) for key, value in action_values):
        raise ValueError("section actions must be finite non-Boolean numbers")
    plastic_actions = ActionBlock(action_values)
    concrete = inp.get("concrete")
    if concrete is None:
        raise ValueError("concrete material law is required")
    concrete_block = MaterialBlock(
        "concrete",
        "concrete",
        str(inp.get("concrete_preset") or "project-concrete"),
        _law_values(concrete),
        _provenance("concrete", inp.get("concrete_preset")),
    )
    bars = _materials(
        inp, kind="bar", count=len(geometry.bars), default=inp.get("steel")
    )
    tendons = _materials(
        inp, kind="tendon", count=len(geometry.tendons), default=inp.get("prestress")
    )
    all_materials = (concrete_block, *bars, *tendons)
    standards = {
        item.provenance.standard_key
        for item in all_materials
        if item.provenance.standard_key is not None
    }
    project_count = sum(item.provenance.standard_key is None for item in all_materials)
    method = (
        next(iter(standards))
        if project_count == 0 and len(standards) == 1
        else "user-defined-material-section-solve"
        if project_count == len(all_materials)
        else "mixed-standard-project-material-section-solve"
    )
    return SectionTraceBlocks(geometry, plastic_actions, concrete_block, bars, tendons, method)
