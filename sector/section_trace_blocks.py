"""Immutable geometry and action blocks shared by section trace builders."""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .section import Section


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
        bars = tuple(GeometryElement(float(item.x), float(item.y), float(item.area)) for item in section.bars)
        tendons = tuple(GeometryElement(float(item.x), float(item.y), float(item.area)) for item in section.tendons)
        return cls(rings, bars, tendons)


@dataclass(frozen=True, slots=True)
class ActionBlock:
    values: tuple[tuple[str, float], ...]


@dataclass(frozen=True, slots=True)
class SectionTraceBlocks:
    geometry: GeometryBlock
    plastic_actions: ActionBlock


def section_trace_blocks(inp: Mapping[str, Any]) -> SectionTraceBlocks:
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
    actions = ActionBlock(tuple((key, float(value)) for key, value in raw_actions))
    return SectionTraceBlocks(GeometryBlock.from_section(inp["section"]), actions)
