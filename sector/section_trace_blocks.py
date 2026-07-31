"""Immutable input and provenance blocks shared by section trace builders."""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from . import codes, material_presets
from .calculation_trace import (
    SOURCE_PROJECT,
    SOURCE_STANDARD,
    SourceCitation,
    TraceAxis,
    TraceSource,
    trace_identity_token,
)
from .materials import Concrete, MildSteel, Prestress
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

CROSS_EDITION_METHOD = "cross-edition-material-section-solve"
MIXED_PROJECT_METHOD = "mixed-standard-project-material-section-solve"
PROJECT_METHOD = "user-defined-material-section-solve"


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

        def convert(items: Sequence[Any]) -> tuple[GeometryElement, ...]:
            return tuple(
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


def _context_items(context: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    if not isinstance(context, Mapping):
        raise TypeError("context must be a mapping")
    if any(type(key) is not str for key in context):
        raise TypeError("context keys must be text")
    return tuple(sorted((key, str(value)) for key, value in context.items()))


def context_id(context: Mapping[str, Any]) -> str:
    """Return an order-independent, injective calculation-context token."""

    if not context:
        return "section"
    return ".".join(
        f"{trace_identity_token(key)}-{trace_identity_token(value)}"
        for key, value in _context_items(context)
    )


def context_axes(context: Mapping[str, Any], **extra: str) -> tuple[TraceAxis, ...]:
    """Declare encoded context axes plus unchanged family-owned axes."""

    items = _context_items(context)
    if any(type(value) is not str for value in extra.values()):
        raise TypeError("extra axis values must be text")

    raw_context_names = {key for key, _ in items}
    encoded_context_names = {
        trace_identity_token(key): value for key, value in items
    }
    extra_names = set(extra)
    if raw_context_names.intersection(extra_names) or set(
        encoded_context_names
    ).intersection(extra_names):
        raise ValueError("extra axes must not replace context keys")

    context_values = tuple(
        TraceAxis(trace_identity_token(key), value) for key, value in items
    )
    extra_values = tuple(
        TraceAxis(name, value) for name, value in sorted(extra.items())
    )
    return (*context_values, *extra_values)


def _code(preset: Any) -> codes.DesignCode | None:
    if type(preset) is not str:
        return None
    for code in codes.CODES.values():
        if preset in {code.label, code.key}:
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
    if not dataclasses.is_dataclass(law) or isinstance(law, type):
        raise ValueError("material law must be a dataclass instance")
    values = []
    for field in dataclasses.fields(law):
        raw = getattr(law, field.name)
        if type(raw) is bool:
            raw = 1.0 if raw else 0.0
        if type(raw) not in {int, float} or not math.isfinite(float(raw)):
            raise ValueError(
                f"{field.name} must be a finite non-Boolean number"
            )
        values.append((field.name, float(raw)))
    return tuple(values)


def _catalog_law_values(
    kind: str,
    item: Mapping[str, Any],
) -> tuple[tuple[str, float], ...] | None:
    curve = item.get("curve")
    if type(curve) is not int:
        return None
    fields_by_curve = (
        material_presets.MILD_FIELDS_BY_CURVE
        if kind == "bar"
        else material_presets.PRESTRESS_FIELDS_BY_CURVE
    )
    names = fields_by_curve.get(curve)
    if names is None:
        return None

    values: dict[str, float] = {}
    for name in names:
        raw = item.get(name)
        if (
            type(raw) not in {int, float}
            or type(raw) is bool
            or not math.isfinite(float(raw))
        ):
            return None
        values[name] = float(raw)

    try:
        if kind == "bar":
            active = item.get("active_in_compression")
            if type(active) is not bool:
                return None
            law = material_presets.build_mild(
                curve,
                active_in_compression=active,
                **values,
            )
        else:
            law = material_presets.build_prestress(curve, **values)
    except (KeyError, TypeError, ValueError):
        return None
    return _law_values(law)


def _catalog_matches(
    kind: str,
    law: MildSteel | Prestress,
    item: Mapping[str, Any],
) -> bool:
    return _catalog_law_values(kind, item) == _law_values(law)


def _preset_law_values(
    kind: str,
    preset: str,
) -> tuple[tuple[str, float], ...] | None:
    code = _code(preset)
    if code is None:
        return None
    available = (
        material_presets.MILD_PRESETS
        if kind == "bar"
        else material_presets.PRESTRESS_PRESETS
    )
    values = available.get(code.label)
    if values is None:
        return None
    fields = {key: value for key, value in values.items() if key != "curve"}
    law = (
        material_presets.build_mild(values["curve"], **fields)
        if kind == "bar"
        else material_presets.build_prestress(values["curve"], **fields)
    )
    return _law_values(law)


def _standard_law_matches(
    kind: str,
    preset: str,
    law: MildSteel | Prestress,
) -> bool:
    target = _law_values(law)
    if _preset_law_values(kind, preset) == target:
        return True
    code = _code(preset)
    return bool(
        kind == "bar"
        and code is not None
        and _law_values(code.steel(law.fytk)) == target
    )


def _sequence(value: Any, label: str) -> tuple[Any, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{label} must be an aligned sequence")
    return tuple(value)


def _element_records(
    inp: Mapping[str, Any],
    kind: str,
    *,
    strict: bool,
) -> tuple[Mapping[str, Any], ...]:
    key = "bar_elements" if kind == "bar" else "tendon_elements"
    raw = inp.get(key)
    if raw is None:
        return ()
    records = _sequence(raw, key)
    if strict and any(not isinstance(item, Mapping) for item in records):
        raise ValueError(f"{key} must contain material assignment mappings")
    return tuple(item if isinstance(item, Mapping) else {} for item in records)


def _catalog_items(
    inp: Mapping[str, Any],
    kind: str,
    *,
    strict: bool,
) -> tuple[Mapping[str, Any], ...]:
    key = (
        "mild_material_catalog"
        if kind == "bar"
        else "prestress_material_catalog"
    )
    catalog = inp.get(key)
    if not isinstance(catalog, Mapping):
        if strict:
            raise ValueError(f"explicit {kind} laws need an aligned catalog")
        return ()
    raw = catalog.get("items")
    if raw is None:
        if strict:
            raise ValueError(f"explicit {kind} laws need catalog items")
        return ()
    items = _sequence(raw, f"{key} items")
    if strict and any(not isinstance(item, Mapping) for item in items):
        raise ValueError(f"{key} items must be mappings")
    return tuple(item for item in items if isinstance(item, Mapping))


def _exact_catalog_item(
    items: tuple[Mapping[str, Any], ...],
    material_id: str,
) -> Mapping[str, Any] | None:
    matches = [
        item
        for item in items
        if type(item.get("id")) is str and item.get("id") == material_id
    ]
    if len(matches) > 1:
        raise ValueError(f"duplicate catalog material ID {material_id}")
    return matches[0] if matches else None


def _materials(
    inp: Mapping[str, Any],
    *,
    kind: str,
    count: int,
    default: MildSteel | Prestress | None,
) -> tuple[MaterialBlock, ...]:
    law_key = "bar_materials" if kind == "bar" else "tendon_materials"
    raw_specific = inp.get(law_key)
    explicit = raw_specific is not None
    laws = (
        _sequence(raw_specific, law_key)
        if explicit
        else (default,) * count
    )
    expected_type = MildSteel if kind == "bar" else Prestress
    if len(laws) != count or any(type(law) is not expected_type for law in laws):
        raise ValueError(f"need {count} aligned {kind} material laws")

    records = _element_records(inp, kind, strict=explicit)
    items = _catalog_items(inp, kind, strict=explicit) if explicit else ()
    if explicit and len(records) != count:
        raise ValueError(f"need {count} aligned {kind} element assignments")

    element_ids: set[str] = set()
    blocks = []
    for index, law in enumerate(laws):
        record = records[index] if index < len(records) else {}
        raw_element_id = record.get("id")
        raw_material_id = record.get("material_id")

        if explicit:
            if (
                type(raw_element_id) is not str
                or not raw_element_id
                or raw_element_id != raw_element_id.strip()
            ):
                raise ValueError(
                    f"explicit {kind} laws need non-blank element IDs"
                )
            if (
                type(raw_material_id) is not str
                or not raw_material_id
                or raw_material_id != raw_material_id.strip()
            ):
                raise ValueError(
                    f"explicit {kind} laws need non-blank material IDs"
                )
            element_id = raw_element_id
            material_id = raw_material_id
            catalog_item = _exact_catalog_item(items, material_id)
            if catalog_item is None:
                raise ValueError(
                    f"assigned {kind} laws need aligned catalog provenance"
                )
        else:
            element_id = (
                raw_element_id
                if type(raw_element_id) is str and raw_element_id.strip()
                else f"{kind}-{index + 1:03d}"
            )
            selected_id = (
                raw_material_id
                if type(raw_material_id) is str and raw_material_id.strip()
                else str(inp.get("capacity_steel_material_id") or "")
                if kind == "bar"
                else ""
            )
            legacy_items = _catalog_items(inp, kind, strict=False)
            catalog_item = (
                _exact_catalog_item(legacy_items, selected_id)
                if selected_id
                else None
            )
            fallback = (
                inp.get("mild_preset")
                if kind == "bar"
                else inp.get("prestress_preset")
            )
            material_id = selected_id or str(fallback or element_id)

        if element_id in element_ids:
            raise ValueError(f"duplicate {kind} element ID {element_id}")
        element_ids.add(element_id)

        preset = (
            catalog_item.get("preset")
            if catalog_item is not None
            else inp.get("mild_preset")
            if kind == "bar"
            else inp.get("prestress_preset")
        )
        if catalog_item is not None and not _catalog_matches(
            kind, law, catalog_item
        ):
            raise ValueError(
                f"{kind} law does not match its catalog provenance"
            )
        if _code(preset) is not None and not _standard_law_matches(
            kind, preset, law
        ):
            preset = None

        blocks.append(
            MaterialBlock(
                kind=kind,
                element_id=element_id,
                material_id=material_id,
                values=_law_values(law),
                provenance=_provenance(kind, preset),
            )
        )
    return tuple(blocks)


def _concrete_block(inp: Mapping[str, Any]) -> MaterialBlock:
    concrete = inp.get("concrete")
    if type(concrete) is not Concrete:
        raise ValueError("concrete material law is required")

    preset = inp.get("concrete_preset")
    code = _code(preset)
    if (
        code is not None
        and _law_values(concrete) != _law_values(code.concrete(concrete.fck))
    ):
        preset = None

    raw_material_id = inp.get("concrete_material_id")
    if raw_material_id is not None and (
        type(raw_material_id) is not str
        or not raw_material_id
        or raw_material_id != raw_material_id.strip()
    ):
        raise ValueError("concrete_material_id must be non-blank text")
    material_id = (
        raw_material_id
        if raw_material_id is not None
        else inp.get("concrete_preset") or "project-concrete"
    )
    return MaterialBlock(
        kind="concrete",
        element_id="concrete",
        material_id=str(material_id),
        values=_law_values(concrete),
        provenance=_provenance("concrete", preset),
    )


def _material_method(materials: tuple[MaterialBlock, ...]) -> str:
    standards = {
        item.provenance.standard_key
        for item in materials
        if item.provenance.standard_key is not None
    }
    project_count = sum(
        item.provenance.standard_key is None for item in materials
    )
    if not project_count:
        if len(standards) == 1:
            return next(iter(standards))
        return CROSS_EDITION_METHOD
    if project_count == len(materials):
        return PROJECT_METHOD
    return MIXED_PROJECT_METHOD


def section_trace_blocks(inp: Mapping[str, Any]) -> SectionTraceBlocks:
    """Build exact immutable geometry, action, material, and provenance inputs."""

    geometry = GeometryBlock.from_section(inp["section"])
    raw_actions = tuple(
        (key, inp.get(key, 0.0)) for key in ("P_pl", "Mx_pl", "My_pl")
    )
    if any(
        type(value) not in {int, float}
        or type(value) is bool
        or not math.isfinite(float(value))
        for _, value in raw_actions
    ):
        raise ValueError("section actions must be finite non-Boolean numbers")
    actions = ActionBlock(
        tuple((key, float(value)) for key, value in raw_actions)
    )

    concrete = _concrete_block(inp)
    bars = _materials(
        inp,
        kind="bar",
        count=len(geometry.bars),
        default=inp.get("steel"),
    )
    tendons = _materials(
        inp,
        kind="tendon",
        count=len(geometry.tendons),
        default=inp.get("prestress"),
    )
    method = _material_method((concrete, *bars, *tendons))
    return SectionTraceBlocks(
        geometry=geometry,
        plastic_actions=actions,
        concrete=concrete,
        bars=bars,
        tendons=tendons,
        plastic_method_id=method,
    )
