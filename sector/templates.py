"""Parametric builders for common cross-section shapes and reinforcement.

These turn a handful of dimensions into the polygon corners (and any holes) and
the reinforcement bar positions that :class:`~sector.section.Section` consumes,
so the user defines a section by its shape and a few numbers rather than typing
coordinates. All coordinates are in metres; bar diameters and areas in mm.
"""

from __future__ import annotations

import math
from typing import Sequence

# Standard reinforcement bar diameters (mm).
BAR_DIAMETERS = (8, 10, 12, 16, 20, 25, 32, 40)


def bar_area(diameter_mm: float) -> float:
    """Cross-sectional area (mm^2) of a round bar of the given diameter (mm)."""
    return math.pi / 4.0 * diameter_mm ** 2


# ---------------------------------------------------------------------------
# Section outlines (centred on the origin); each returns a list of (x, y) in m
# ---------------------------------------------------------------------------


def rectangle(b: float, h: float):
    """Solid rectangle ``b`` wide by ``h`` tall, centred on the origin."""
    return [(-b / 2, -h / 2), (-b / 2, h / 2), (b / 2, h / 2), (b / 2, -h / 2)]


def slab_strip(h: float, width: float = 1.0):
    """A unit-width slab strip (default 1 m), thickness ``h``."""
    return rectangle(width, h)


def t_section(bf: float, hf: float, bw: float, hw: float):
    """T-section: flange ``bf`` x ``hf`` on a web ``bw`` x ``hw``.

    Symmetric about the Y axis, centred on the total depth ``H = hf + hw`` so the
    outline spans ``-H/2`` to ``H/2`` (consistent with the other shapes). The
    flange is at the top; vertices are clockwise from its top-left corner.
    """
    height = hf + hw
    top = height / 2          # top of flange
    yj = height / 2 - hf      # flange/web junction
    bot = -height / 2         # bottom of web
    return [
        (-bf / 2, top), (bf / 2, top), (bf / 2, yj),
        (bw / 2, yj), (bw / 2, bot), (-bw / 2, bot), (-bw / 2, yj), (-bf / 2, yj),
    ]


def circular(diameter: float, segments: int = 48):
    """Circular section of the given diameter, approximated by an N-gon."""
    r = diameter / 2.0
    return [(r * math.cos(2 * math.pi * k / segments),
             r * math.sin(2 * math.pi * k / segments)) for k in range(segments)]


def box(b: float, h: float, wall: float):
    """Hollow box ``b`` x ``h`` with a uniform wall thickness ``wall``.

    Returns ``(outer, [hole])`` -- the outer outline and one rectangular void.
    ``wall`` must leave a positive cavity: ``2 * wall`` strictly less than both
    ``b`` and ``h``, otherwise the void would be empty or larger than the outline.
    """
    if wall <= 0:
        raise ValueError("wall thickness must be positive")
    if 2 * wall >= b or 2 * wall >= h:
        raise ValueError(
            "wall thickness too large: 2*wall must be less than both b and h"
        )
    return rectangle(b, h), [rectangle(b - 2 * wall, h - 2 * wall)]


# ---------------------------------------------------------------------------
# Reinforcement layouts; each returns a list of (x, y, area_mm2)
# ---------------------------------------------------------------------------


def count_for_spacing(span: float, spacing: float) -> int:
    """Number of evenly-spaced bars to place across ``span`` at a target centre-to-
    centre ``spacing`` (same units for both).

    The most bars whose centres are no more than ``spacing`` apart, i.e.
    ``floor(span / spacing) + 1`` (slab-style ``phi @ s``). A collapsed or
    non-positive span gives a single bar; a positive span never gives fewer than
    two, so a by-spacing row always spans the face.
    """
    if span <= 0 or spacing <= 0:
        return 1
    return max(2, int(math.floor(span / spacing + 1e-9)) + 1)


def bar_row(y: float, x_start: float, x_end: float, n: int, diameter_mm: float):
    """``n`` bars of the given diameter evenly spaced from ``x_start`` to ``x_end``."""
    if n <= 0:
        return []
    a = bar_area(diameter_mm)
    if n == 1:
        return [(0.5 * (x_start + x_end), y, a)]
    step = (x_end - x_start) / (n - 1)
    return [(x_start + k * step, y, a) for k in range(n)]


def bar_ring(cx: float, cy: float, radius: float, n: int, diameter_mm: float):
    """``n`` bars of the given diameter on a circle (for circular sections)."""
    if n <= 0:
        return []
    a = bar_area(diameter_mm)
    return [(cx + radius * math.cos(2 * math.pi * k / n),
             cy + radius * math.sin(2 * math.pi * k / n), a) for k in range(n)]


def edge_layer(b: float, h: float, cover: float, n: int, diameter_mm: float,
               face: str = "bottom"):
    """A row of ``n`` bars along one face of a ``b`` x ``h`` rectangle.

    ``cover`` is the clear distance from the face to the bar centres (m).
    ``face`` is one of ``bottom``, ``top``, ``left``, ``right``.
    """
    if face in ("bottom", "top"):
        y = -h / 2 + cover if face == "bottom" else h / 2 - cover
        return bar_row(y, -b / 2 + cover, b / 2 - cover, n, diameter_mm)
    if face in ("left", "right"):
        x = -b / 2 + cover if face == "left" else b / 2 - cover
        a = bar_area(diameter_mm)
        if n == 1:
            return [(x, 0.0, a)]
        y0, y1 = -h / 2 + cover, h / 2 - cover
        step = (y1 - y0) / (n - 1)
        return [(x, y0 + k * step, a) for k in range(n)]
    raise ValueError("face must be bottom, top, left or right")


def point_row(y: float, x_start: float, x_end: float, n: int, area_mm2: float):
    """``n`` point areas (e.g. tendons) evenly spaced from ``x_start`` to ``x_end``.

    Like :func:`bar_row` but the area (mm2) is given directly rather than via a
    diameter, as tendons are specified by their cross-sectional area.
    """
    if n <= 0:
        return []
    if n == 1:
        return [(0.5 * (x_start + x_end), y, area_mm2)]
    step = (x_end - x_start) / (n - 1)
    return [(x_start + k * step, y, area_mm2) for k in range(n)]


def point_ring(cx: float, cy: float, radius: float, n: int, area_mm2: float):
    """``n`` point areas (e.g. tendons) on a circle, area (mm2) given directly."""
    if n <= 0:
        return []
    return [(cx + radius * math.cos(2 * math.pi * k / n),
             cy + radius * math.sin(2 * math.pi * k / n), area_mm2) for k in range(n)]


def merge_bars(*groups: Sequence[Sequence[float]]):
    """Concatenate several bar groups into one list."""
    out = []
    for g in groups:
        out.extend(g)
    return out
