"""Lightweight section drawings and shared presentation constants."""

from __future__ import annotations

from html import escape as _html_escape
import math

import plotly.graph_objects as go
import plotly.io as pio

# --- House palette, grouped by role -------------------------------------------
# Tension and compression use the colour-blind-safe blue / vermillion pair from
# the Okabe-Ito palette. Section markers also use a plain / x pattern, so sign is
# never communicated by colour alone.
# Structure
CONCRETE_FILL = "rgba(120,130,140,0.18)"
CONCRETE_LINE = "#5b6770"
HOLE_FILL = "white"                         # voids punched from the outline
# Reinforcement / strain state
BAR_TENSION = "#0072B2"                      # blue; plain marker
BAR_COMPRESSION = "#D55E00"                  # vermillion; x-pattern marker
BAR_NEUTRAL = "#534ab7"                      # purple (unstressed / plane marker)
TENDON = "#0b7285"                           # teal
COMP_ZONE_FILL = "rgba(213,94,0,0.22)"       # concrete compression zone
TENS_ZONE_FILL = "rgba(0,114,178,0.12)"      # tension side (no concrete stress)
_ZONE_OUTLINE_DASHES = ("solid", "dash", "dot", "dashdot")
NA_LINE = "#E69F00"                          # neutral axis (amber)
# Material stress-strain curves
CURVE_CHAR = "#534ab7"                        # characteristic curve + its input markers
CURVE_DESIGN = "#9aa3ab"                      # partial-factored design curve (grey reference)
# Results (interaction envelopes / schematics)
ENVELOPE = "#534ab7"                          # capacity envelope / limit line (purple)
ENVELOPE_FILL = "rgba(83,74,183,0.08)"        # shaded safe region under the envelope
LOAD_POINT = "#CC79A7"                        # applied-load marker (magenta)
LINK_LINE = "#56B4E9"                         # shear-link ties in the truss schematic
# Annotation
GUIDE_LINE = "#b8bdc4"                        # dotted projection guides
SCHEMATIC_INK = "#2c2c2a"                     # strong schematic lines + labels
SCHEMATIC_FILL = "rgba(120,130,140,0.10)"    # neutral schematic body fill

# One shared layout template, so every figure matches (and matches the PDF report
# typography). Registered as "sector" and layered on plotly_white; each figure uses
# ``template=_TEMPLATE`` and only overrides what is genuinely figure-specific
# (margins, axis titles, legend position).
_FONT_FAMILY = "DejaVu Sans, Arial, sans-serif"
_GRID_COLOR = "#e6e8eb"
_ZERO_COLOR = "#c8ccd0"
pio.templates["sector"] = go.layout.Template(layout=dict(
    font=dict(family=_FONT_FAMILY, size=12, color="#2c2c2a"),
    title=dict(font=dict(size=14)),
    legend=dict(font=dict(size=11)),
    xaxis=dict(gridcolor=_GRID_COLOR, zerolinecolor=_ZERO_COLOR),
    yaxis=dict(gridcolor=_GRID_COLOR, zerolinecolor=_ZERO_COLOR),
))
_TEMPLATE = "plotly_white+sector"

def _ring_xy(ring):
    if len(ring) == 0:
        return [], []
    xs = [p[0] for p in ring] + [ring[0][0]]
    ys = [p[1] for p in ring] + [ring[0][1]]
    return xs, ys


POINT_LABEL = "#2c2c2a"   # reinforcement point numbers


CORNER_LABEL = "#5b6770"  # concrete corner numbers


def _decimate(positions, min_dist):
    """Greedy indices to keep so the kept points are at least ``min_dist`` apart.

    Walks the points in order, keeping one only when it clears every already-kept
    point -- so closely spaced labels thin out (every 2nd, 3rd, ...) while
    well-spaced ones are all kept.
    """
    if min_dist <= 0.0:
        return list(range(len(positions)))
    keep, chosen = [], []
    for i, p in enumerate(positions):
        if all(math.hypot(p[0] - q[0], p[1] - q[1]) >= min_dist for q in chosen):
            keep.append(i)
            chosen.append(p)
    return keep


_LABEL_BASE_SIZE = 11.0   # default point-label font (px), scaled by label_scale


def _add_point_labels(fig, outer, holes, bars, tendons, label_scale=1.0,
                      label_min_gap=0.04, bar_ids=None, tendon_ids=None):
    """Number the reinforcement (bars then tendons, continuously) and the
    concrete corners, so the drawing cross-references the result tables.

    Reinforcement numbering matches the elastic per-bar table (tendons follow the
    bars); corner numbering matches ``Section.concrete_vertices`` order (outer
    ring then holes), which is the "corner N" reported with the peak concrete
    stress. ``label_scale`` scales the font; ``label_min_gap`` is the minimum
    label spacing as a fraction of the section size -- labels closer than that
    thin out, independently of the font size (0 keeps every label).
    """
    xs = [v[0] for v in outer] or [0.0]
    ys = [v[1] for v in outer] or [0.0]
    span = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    size = _LABEL_BASE_SIZE * label_scale
    min_dist = label_min_gap * span           # below this, labels are thinned out

    rebar = list(bars or []) + list(tendons or [])
    if rebar:
        labels = (list(bar_ids or []) + list(tendon_ids or []))
        if len(labels) != len(rebar):
            labels = [str(i + 1) for i in range(len(rebar))]
        keep = _decimate(rebar, min_dist)
        fig.add_trace(go.Scatter(
            x=[rebar[i][0] for i in keep], y=[rebar[i][1] for i in keep], mode="text",
            text=[labels[i] for i in keep], textposition="top center",
            textfont=dict(size=size, color=POINT_LABEL),
            hoverinfo="skip", showlegend=False))

    verts = [v for ring in [outer, *(holes or [])] for v in ring]
    if not verts:
        return
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)
    off = 0.05 * span * label_scale
    lx, ly, txt = [], [], []
    for i in _decimate(verts, min_dist):      # nudge each kept label outward
        v = verts[i]
        dx, dy = v[0] - cx, v[1] - cy
        d = math.hypot(dx, dy) or 1.0
        lx.append(v[0] + off * dx / d)
        ly.append(v[1] + off * dy / d)
        txt.append(str(i + 1))
    fig.add_trace(go.Scatter(
        x=lx, y=ly, mode="text", text=txt,
        textfont=dict(size=size, color=CORNER_LABEL), hoverinfo="skip",
        showlegend=False))


_LEGEND_TOP_M, _LEGEND_BOT_M = 40, 96


_LEGEND_GAP_PX = 68.0


def _legend_y(height: float) -> float:
    plot_h = max(height - _LEGEND_TOP_M - _LEGEND_BOT_M, 1.0)
    return -_LEGEND_GAP_PX / plot_h


def _point_hover(
    points,
    first_number,
    kind,
    unit,
    extra=None,
    ids=None,
    *,
    include_geometry=True,
):
    """Per-point hover strings ``'Kind N<br>x, y[<br>area][<br>extra]'`` for the
    section drawing.

    Numbering continues from ``first_number`` so it matches the drawn labels and the
    result tables (bars 1..n, tendons n+1.., concrete corners 1..). Coordinates are
    the already-scaled display values, shown in ``unit`` (0 decimals for mm, 3 for
    m). A reinforcement ``area`` (a 3rd tuple element, always in mm2) is shown when
    present; concrete corners are 2-tuples and carry none. ``extra`` is an optional
    per-point string (e.g. a stress/strain read-out) appended on its own line.
    ``include_geometry=False`` retains the identity and extra response only.
    """
    dec = 3 if unit == "m" else 0
    lines = []
    for i, p in enumerate(points):
        point_id = _html_escape(
            str(ids[i]) if ids is not None and i < len(ids)
            else str(first_number + i),
            quote=True,
        )
        s = f"{kind} {point_id}"
        if include_geometry:
            s += (
                f"<br>x = {p[0]:.{dec}f} {unit}, "
                f"y = {p[1]:.{dec}f} {unit}"
            )
            if len(p) > 2 and p[2] is not None:
                s += f"<br>area = {p[2]:.0f} mm<sup>2</sup>"
        if extra is not None and i < len(extra) and extra[i]:
            s += f"<br>{extra[i]}"
        lines.append(s)
    return lines


def _marker_sizes(points, base, lo, hi):
    """Per-point marker sizes (px) scaled by RELATIVE bar diameter.

    Each point is ``(x, y, area)``; the marker diameter scales with ``sqrt(area)``
    (i.e. the true bar diameter) normalised by the median, so a mixed layout shows
    which bars are the big ones (an O25 next to an O16 reads ~1.6x wider). ``base``
    is the size at the median diameter; sizes are clamped to ``[lo, hi]`` so dense
    layouts stay legible and a single huge tendon cannot dwarf the drawing. A layout
    of equal areas (or missing areas) degrades to ``base`` for every point.
    """
    try:
        dias = [math.sqrt(max(float(p[2]), 0.0)) for p in points]
    except (IndexError, TypeError, ValueError):
        return base
    finite = sorted(d for d in dias if d > 0.0)
    if not finite:
        return base
    med = finite[len(finite) // 2]
    if med <= 0.0:
        return base
    return [min(max(base * (d / med), lo), hi) if d > 0.0 else base for d in dias]


def section_figure(outer, holes=None, bars=None, bar_colors=None,
                   na_line=None, title="Section", tendons=None, tendon_colors=None,
                   zones=None, show_labels=False, label_scale=1.0, label_min_gap=0.04,
                   height=440, scale=1.0, unit="m", bar_hover=None, tendon_hover=None,
                   bar_ids=None, tendon_ids=None, corner_hover=None,
                   geometry_hover=True):
    """Draw the section: concrete outline, holes, reinforcement and neutral axis.

    Reinforcement is drawn consistently across the views: bars are circles and
    tendons are diamonds, each coloured by ``bar_colors`` / ``tendon_colors``
    (e.g. by stress sign) when given, else a neutral colour. Compression-state
    markers receive an x pattern and tension-state markers remain plain, with
    explicit legend entries, so the state remains readable without colour.
    ``outer`` / ``holes`` / ``bars`` / ``na_line`` / ``zones`` are all given in
    metres; ``scale`` (and the matching axis ``unit`` label) converts them for
    display -- e.g. ``1000`` / ``"mm"`` draws the section in millimetres.
    ``geometry_hover`` keeps coordinates and reinforcement area in input previews;
    analysis-result callers disable it and provide response-only hover strings.
    ``show_labels`` numbers the reinforcement and concrete corners; ``label_scale``
    scales the label font and ``label_min_gap`` is the minimum label spacing
    (fraction of the section size) below which labels are thinned out -- the two
    are independent.
    """
    # Scale every geometry input once, up front, so the traces and the labels are
    # all drawn in the display units. Guard with ``is None`` rather than a truth
    # test so NumPy vertex arrays (whose truth value is ambiguous) pass through.
    outer = [] if outer is None else [(p[0] * scale, p[1] * scale) for p in outer]
    holes = [] if holes is None else [[(p[0] * scale, p[1] * scale) for p in ring] for ring in holes]
    bars = [] if bars is None else [(b[0] * scale, b[1] * scale) + tuple(b[2:]) for b in bars]
    tendons = [] if tendons is None else [(t[0] * scale, t[1] * scale) + tuple(t[2:]) for t in tendons]
    if na_line is not None:
        na_line = tuple(v * scale for v in na_line)
    zones = [] if zones is None else [([(p[0] * scale, p[1] * scale) for p in verts], color, name)
                                      for verts, color, name in zones]

    fig = go.Figure()
    xs, ys = _ring_xy(outer)
    fig.add_trace(go.Scatter(x=xs, y=ys, fill="toself", mode="lines",
                             fillcolor=CONCRETE_FILL, line=dict(color=CONCRETE_LINE),
                             hoverinfo="skip", showlegend=False))
    for zone_index, (verts, color, name) in enumerate(zones or []):
        if len(verts) >= 3:
            zx, zy = _ring_xy(verts)
            fig.add_trace(go.Scatter(x=zx, y=zy, fill="toself", mode="lines",
                                     fillcolor=color,
                                     line=dict(
                                         color=CONCRETE_LINE,
                                         width=1.3,
                                         dash=_ZONE_OUTLINE_DASHES[
                                             zone_index
                                             % len(_ZONE_OUTLINE_DASHES)
                                         ],
                                     ),
                                     hoverinfo="skip", name=name))
    for hole in holes or []:
        hx, hy = _ring_xy(hole)
        fig.add_trace(go.Scatter(x=hx, y=hy, fill="toself", mode="lines",
                                 fillcolor=HOLE_FILL, line=dict(color=CONCRETE_LINE, dash="dot"),
                                 hoverinfo="skip", showlegend=False))
    # Invisible hover targets on the concrete corners (outer ring then holes, the
    # numbering used for the corner labels and the peak-stress "corner N"): the fill
    # polygons skip hover, so these markers report each corner's coordinates without
    # drawing anything over the outline.
    corner_verts = [v for ring in [outer, *(holes or [])] for v in ring]
    if corner_verts and (geometry_hover or corner_hover):
        fig.add_trace(go.Scatter(
            x=[v[0] for v in corner_verts], y=[v[1] for v in corner_verts],
            mode="markers", marker=dict(size=12, color="rgba(0,0,0,0)"),
            customdata=_point_hover(
                corner_verts,
                1,
                "Corner",
                unit,
                corner_hover,
                include_geometry=geometry_hover,
            ),
            hovertemplate="%{customdata}<extra></extra>", showlegend=False))
    if bars:
        bx = [b[0] for b in bars]
        by = [b[1] for b in bars]
        colors = bar_colors or [BAR_NEUTRAL] * len(bars)
        symbols = (["circle-x" if color == BAR_COMPRESSION else "circle"
                    for color in colors] if bar_colors else "circle")
        fig.add_trace(go.Scatter(x=bx, y=by, mode="markers", name="reinforcing bar",
                                 marker=dict(size=_marker_sizes(bars, 9.0, 6.5, 14.0),
                                             symbol=symbols, color=colors,
                                             line=dict(color="white", width=1)),
                                 customdata=_point_hover(
                                     bars, 1, "Bar", unit, bar_hover, bar_ids,
                                     include_geometry=geometry_hover),
                                 hovertemplate="%{customdata}<extra></extra>",
                                 showlegend=True))
    if tendons:
        tx = [t[0] for t in tendons]
        ty = [t[1] for t in tendons]
        colors = tendon_colors or [TENDON] * len(tendons)
        symbols = (["diamond-x" if color == BAR_COMPRESSION else "diamond"
                    for color in colors] if tendon_colors else "diamond")
        fig.add_trace(go.Scatter(x=tx, y=ty, mode="markers", name="tendon",
                                 marker=dict(size=_marker_sizes(tendons, 11.0, 8.0, 16.0),
                                             symbol=symbols, color=colors,
                                             line=dict(color="white", width=1)),
                                 customdata=_point_hover(
                                     tendons, len(bars) + 1, "Tendon", unit,
                                     tendon_hover, tendon_ids,
                                     include_geometry=geometry_hover),
                                 hovertemplate="%{customdata}<extra></extra>",
                                 showlegend=True))
    state_colors = list(bar_colors or []) + list(tendon_colors or [])
    if BAR_TENSION in state_colors:
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers", name="tension (+): plain marker",
            marker=dict(size=9, symbol="square", color=BAR_TENSION,
                        line=dict(color="white", width=1)),
            hoverinfo="skip", showlegend=True,
        ))
    if BAR_COMPRESSION in state_colors:
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers", name="compression (-): x marker",
            marker=dict(size=9, symbol="square-x", color=BAR_COMPRESSION,
                        line=dict(color="white", width=1)),
            hoverinfo="skip", showlegend=True,
        ))
    if na_line:
        x0, y0, x1, y1 = na_line
        fig.add_trace(go.Scatter(x=[x0, x1], y=[y0, y1], mode="lines",
                                 line=dict(color=NA_LINE, width=2, dash="dash"),
                                 hoverinfo=(None if geometry_hover else "skip"),
                                 name="neutral axis"))
    if show_labels:
        _add_point_labels(
            fig, outer, holes, bars, tendons, label_scale, label_min_gap,
            bar_ids, tendon_ids,
        )
    fig.update_layout(
        title=title, template=_TEMPLATE, height=height,
        margin=dict(l=10, r=10, t=_LEGEND_TOP_M, b=_LEGEND_BOT_M),
        xaxis=dict(title=dict(text=f"x ({unit})", standoff=10), zeroline=True),
        yaxis=dict(title=f"y ({unit})", scaleanchor="x", scaleratio=1, zeroline=True),
        showlegend=bool(na_line) or bool(zones) or bool(bars) or bool(tendons),
        # Below the plot and below the x-axis title, clear of the plotly modebar
        # (which the above-the-plot position collided with). A height-scaled y keeps
        # a constant gap below the title without spilling past the bottom margin.
        legend=dict(orientation="h", yanchor="top", y=_legend_y(height), x=0.5,
                    xanchor="center"),
    )
    return fig


