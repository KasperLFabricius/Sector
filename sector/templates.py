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


CIRCLE_SEGMENTS = 48   # N-gon used to approximate a circular outline


def circular(diameter: float, segments: int = CIRCLE_SEGMENTS):
    """Circular section of the given diameter, approximated by an N-gon."""
    r = diameter / 2.0
    return [(r * math.cos(2 * math.pi * k / segments),
             r * math.sin(2 * math.pi * k / segments)) for k in range(segments)]


def ring_radius(diameter: float, cover: float, segments: int = CIRCLE_SEGMENTS):
    """Radius for reinforcement on a circular section: ``diameter/2 - cover``, but
    never outside the inscribed N-gon's apothem, so a bar between two polygon
    vertices is not left just outside the outline (e.g. at zero cover)."""
    apothem = (diameter / 2.0) * math.cos(math.pi / segments)
    return max(min(diameter / 2.0 - cover, apothem), 0.0)


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
    """Number of evenly-spaced bars to place across ``span`` so the centre-to-centre
    gap does not exceed the target ``spacing`` (same units for both).

    ``spacing`` is a *maximum* (slab-style ``phi @ s``): the bars are spread evenly
    over the whole face, so the count is ``ceil(span / spacing) + 1`` -- enough gaps
    that each is ``<= spacing``. A face that is not an exact multiple of the spacing
    gets an extra bar (a tighter actual spacing) rather than one too few. A
    collapsed or non-positive span gives a single bar; a positive span never gives
    fewer than two, so a by-spacing row always spans the face.
    """
    if span <= 0 or spacing <= 0:
        return 1
    # The 1e-9 slack keeps an exact multiple (e.g. 0.90 m at 150 mm -> 6 gaps) from
    # rounding up to an extra gap on a floating-point 6.0000001.
    return max(2, int(math.ceil(span / spacing - 1e-9)) + 1)


def bar_row(y: float, x_start: float, x_end: float, n: int, diameter_mm: float):
    """``n`` bars of the given diameter evenly spaced from ``x_start`` to ``x_end``."""
    if n <= 0:
        return []
    a = bar_area(diameter_mm)
    if n == 1:
        return [(0.5 * (x_start + x_end), y, a)]
    step = (x_end - x_start) / (n - 1)
    return [(x_start + k * step, y, a) for k in range(n)]


def bar_layers(y_face: float, direction: float, n_layers: int, layer_spacing: float,
               x_start: float, x_end: float, n_per: int, diameter_mm: float,
               span_at=None, n_at=None, n_extra=None):
    """Stack ``n_layers`` rows of bars.

    The first row sits at ``y_face`` (the cover line at a face) and each further
    layer is ``layer_spacing`` deeper into the section: ``direction`` is ``+1`` for
    a bottom face (layers move up) or ``-1`` for a top face (layers move down).
    ``n_layers = 1`` is a single :func:`bar_row`. ``span_at(y) -> (x_start, x_end)``,
    when given, sets each row's span from its depth, so a row can follow a width
    step (e.g. a T-section top row narrowing to the web below the flange).
    ``n_at(x_start, x_end) -> int`` overrides the bar count from the (possibly
    narrowed) span, so a row placed by spacing keeps the target spacing on its own
    width instead of reusing a count sized for a wider row. ``n_extra``, when given,
    is the bar count for the stacked layers above the first (the first keeps
    ``n_per``), so an upper layer can hold a different count than the main row.
    """
    rows = []
    for j in range(max(0, int(n_layers))):
        y = y_face + direction * j * layer_spacing
        xs, xe = span_at(y) if span_at is not None else (x_start, x_end)
        if n_at is not None:
            n = int(n_at(xs, xe))
        elif j > 0 and n_extra is not None:
            n = int(n_extra)
        else:
            n = n_per
        rows.extend(bar_row(y, xs, xe, n, diameter_mm))
    return rows


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


def point_layers(y_face: float, direction: float, n_layers: int, layer_spacing: float,
                 x_start: float, x_end: float, n_per: int, area_mm2: float):
    """Stack ``n_layers`` rows of ``n_per`` point areas (the tendon analogue of
    :func:`bar_layers`): the first row at ``y_face`` and each next ``layer_spacing``
    further in ``direction`` (``+1`` up from a bottom face). ``n_layers = 1`` is a
    single :func:`point_row`."""
    rows = []
    for j in range(max(0, int(n_layers))):
        rows.extend(point_row(y_face + direction * j * layer_spacing,
                              x_start, x_end, n_per, area_mm2))
    return rows


def _even_span(x0: float, x1: float, n: int):
    """``n`` x-positions evenly spaced from ``x0`` to ``x1``; a non-positive span
    (the cover exceeds the available width) collapses to the centre."""
    if n <= 0:
        return []
    if x1 < x0:
        x0 = x1 = 0.5 * (x0 + x1)
    if n == 1:
        return [0.5 * (x0 + x1)]
    step = (x1 - x0) / (n - 1)
    return [x0 + k * step for k in range(n)]


def box_row_xs(y: float, b: float, h: float, wall: float, cover: float, n: int):
    """x-positions of ``n`` points across a box girder's concrete at depth ``y``:
    the full width in a top/bottom wall, and split between the two side walls in the
    hollow (so a row that rises into the cavity keeps its count in the webs rather
    than placing points in the void)."""
    if n <= 0:
        return []
    if not (-h / 2 + wall) < y < (h / 2 - wall):          # in a top/bottom wall
        return _even_span(-b / 2 + cover, b / 2 - cover, n)
    n_left = (n + 1) // 2                                 # split between the side walls
    return (_even_span(-b / 2 + cover, -b / 2 + wall - cover, n_left)
            + _even_span(b / 2 - wall + cover, b / 2 - cover, n - n_left))


def box_layers(y_face: float, direction: float, n_layers: int, layer_spacing: float,
               b: float, h: float, wall: float, cover: float, n_per: int,
               area_mm2: float, n_extra=None):
    """Stack ``n_layers`` rows of points for a box girder, each row placed by
    :func:`box_row_xs` (full width in a wall, split into the side walls in the
    hollow). ``area_mm2`` is the per-point area (a bar or tendon area). ``n_extra``,
    when given, is the point count for the layers above the first (which keeps
    ``n_per``)."""
    rows = []
    for j in range(max(0, int(n_layers))):
        y = y_face + direction * j * layer_spacing
        n = int(n_extra) if (j > 0 and n_extra is not None) else int(n_per)
        rows.extend((x, y, area_mm2) for x in box_row_xs(y, b, h, wall, cover, n))
    return rows


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
