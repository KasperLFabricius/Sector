"""Plotly figures for the Sector UI: the section drawing and the N-M diagram."""

from __future__ import annotations

import math

import plotly.graph_objects as go
import plotly.io as pio

from sector import geometry

# --- House palette, grouped by role -------------------------------------------
# Green = tension, red = compression, everywhere (bars, strain wedges, chords).
# A hue is reused across figures only where the two roles never share a plot
# (e.g. the red applied-load marker and a red compression bar).
# Structure
CONCRETE_FILL = "rgba(120,130,140,0.18)"
CONCRETE_LINE = "#5b6770"
HOLE_FILL = "white"                         # voids punched from the outline
# Reinforcement / strain state
BAR_TENSION = "#1d9e75"                      # green
BAR_COMPRESSION = "#c0392b"                  # red
BAR_NEUTRAL = "#534ab7"                      # purple (unstressed / plane marker)
TENDON = "#0b7285"                           # teal
COMP_ZONE_FILL = "rgba(192,57,43,0.22)"      # concrete compression zone (red)
TENS_ZONE_FILL = "rgba(29,158,117,0.12)"     # tension side (green, no concrete stress)
NA_LINE = "#e08a1e"                          # neutral axis (amber)
# Material stress-strain curves
CURVE_CHAR = "#534ab7"                        # characteristic curve + its input markers
CURVE_DESIGN = "#9aa3ab"                      # partial-factored design curve (grey reference)
# Results (interaction envelopes / schematics)
ENVELOPE = "#534ab7"                          # capacity envelope / limit line (purple)
ENVELOPE_FILL = "rgba(83,74,183,0.08)"        # shaded safe region under the envelope
LOAD_POINT = "#c0392b"                        # applied-load marker (red)
LINK_LINE = "#e08a1e"                         # shear-link ties in the truss schematic
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

# Greek glyphs are written as ASCII escapes so the source stays ASCII (these are
# Basic-Multilingual-Plane code points, so they never form surrogate pairs).
_EPS = chr(0x3B5)       # epsilon
_SIGMA = chr(0x3C3)     # sigma
_PERMILLE = chr(0x2030)  # per-mille sign

_MID = chr(0x00B7)  # middle dot, for products like k*fytk (BMP, surrogate-safe)

# Map a material's ASCII marker key to its display symbol (subscripts via <sub>).
# The keys are the *input* parameters, so editing any of them moves a labelled
# point on the diagram. Derived/design quantities (f1, f2, fyd, fud) are not shown.
_MARKER_LABELS = {
    "fcd": "f<sub>cd</sub>",
    "fck": "f<sub>ck</sub>",
    "eps_c2": _EPS + "<sub>c2</sub>",
    "eps_cu2": _EPS + "<sub>cu2</sub>",
    # mild steel inputs
    "fytk": "f<sub>ytk</sub>",
    "fyck": "f<sub>yck</sub>",
    "futk": "f<sub>utk</sub>",
    "k_fytk": "k" + _MID + "f<sub>ytk</sub>",
    "k_fyck": "k" + _MID + "f<sub>yck</sub>",
    "eut": _EPS + "<sub>ut</sub>",
    "ey0t": _EPS + "<sub>0t</sub>",
    "ey0c": _EPS + "<sub>0c</sub>",
    # prestressing-steel inputs
    "fp01k": "f<sub>p0.1k</sub>",
    "fpk": "f<sub>pk</sub>",
    "k_fp01k": "k" + _MID + "f<sub>p0.1k</sub>",
    "IS": "I<sub>S</sub>",
}


def _linspace(a, b, n):
    if n < 2:
        return [a]
    step = (b - a) / (n - 1)
    return [a + step * i for i in range(n)]


def _merge_labels(keys):
    """Join the symbols for values that share an axis position (e.g. f_yd/f_ud)."""
    seen = []
    for k in keys:
        sym = _MARKER_LABELS.get(k, k)
        if sym not in seen:
            seen.append(sym)
    return "/".join(seen)


def _spread(values, min_gap):
    """Push label anchor positions apart to at least ``min_gap``, keeping order.

    ``values`` are the true positions (sorted ascending); returns adjusted label
    positions so adjacent labels do not collide. The guide line still marks the
    true value, so a small label offset stays unambiguous.
    """
    out = list(values)
    for i in range(1, len(out)):
        if out[i] - out[i - 1] < min_gap:
            out[i] = out[i - 1] + min_gap
    shift = (values[-1] - out[-1]) / 2.0 if out else 0.0  # re-centre the stack
    return [v + shift for v in out]


def _grouped(pts, axis):
    """Group points by axis position -> ordered list of (value, [keys])."""
    groups = {}
    for s, sig, ek, sk in pts:
        value, key = (round(s * 1000.0, 2), ek) if axis == "x" else (round(sig, 1), sk)
        if key is not None:
            groups.setdefault(value, []).append(key)
    return sorted(groups.items())


def _apply_markers(fig, points, eps_min, eps_max, ymin, ymax):
    """Annotate a material's points of interest, journal-style.

    ``points`` are ``(strain, stress, eps_key, sigma_key)`` from
    ``material.diagram_markers``. Each in-view point gets a dot on the curve and
    thin projection guides to the axes; the strain symbols sit on the strain
    axis and the stress symbols on the stress axis, so labels never touch the
    curve. Symbols sharing an axis position are merged (e.g. ``f_yd/f_ud``), and
    near-coincident labels are nudged apart so they never overlap one another.
    """
    pts = [(s, sig, ek, sk) for (s, sig, ek, sk) in points
           if eps_min <= s <= eps_max]
    if not pts:
        return

    fig.add_trace(go.Scatter(
        x=[s * 1000.0 for s, _, _, _ in pts], y=[sig for _, sig, _, _ in pts],
        mode="markers", marker=dict(size=8, color=CURVE_CHAR,
                                    line=dict(color="white", width=1.5)),
        hoverinfo="skip", showlegend=False))

    # Strain symbols above the plot (the numeric strain ticks stay on the bottom
    # axis, so the symbols and the values do not collide).
    x_groups = _grouped(pts, "x")
    x_span = (eps_max - eps_min) * 1000.0
    x_lab = _spread([v for v, _ in x_groups], x_span * 0.11)
    for (x0, keys), xl in zip(x_groups, x_lab):
        fig.add_vline(x=x0, line_width=0.8, line_dash="dot", line_color=GUIDE_LINE)
        fig.add_annotation(x=xl, xref="x", y=1.0, yref="paper", yshift=6,
                           yanchor="bottom", showarrow=False, text=_merge_labels(keys),
                           font=dict(size=12, color=CURVE_CHAR))

    # Stress symbols on the right edge (the numeric stress ticks stay on the
    # left axis), nudged apart so they never overlap one another.
    y_groups = _grouped(pts, "y")
    y_span = (ymax - ymin) or 1.0
    y_lab = _spread([v for v, _ in y_groups], y_span * 0.08)
    for (y0, keys), yl in zip(y_groups, y_lab):
        fig.add_hline(y=y0, line_width=0.8, line_dash="dot", line_color=GUIDE_LINE)
        fig.add_annotation(x=1.0, xref="paper", xshift=6, y=yl, yref="y",
                           xanchor="left", showarrow=False, text=_merge_labels(keys),
                           font=dict(size=12, color=CURVE_CHAR))


def _slope_label(fig, material):
    """Label the elastic-branch slope with the input modulus (steel only).

    Shows the characteristic modulus the user entered -- ``Es`` for mild steel,
    ``Ep`` for prestressing steel -- not the partial-factored design slope.
    """
    es = getattr(material, "Es", None)
    if not es:
        return
    pos = [(s, sig) for s, sig, _, _ in material.diagram_markers(design=False)
           if s > 0.0]
    if not pos:
        return
    e_yield = min(s for s, _ in pos)
    e_mid = 0.45 * e_yield
    sym = "E<sub>p</sub>" if type(material).__name__ == "Prestress" else "E<sub>s</sub>"
    fig.add_annotation(
        x=e_mid * 1000.0, y=es * e_mid, ax=-36, ay=-22, showarrow=True,
        arrowhead=0, arrowwidth=0.8, arrowcolor=GUIDE_LINE,
        text="%s = %.0f GPa" % (sym, es / 1000.0),
        font=dict(size=11, color=CURVE_CHAR))


_ORIGIN_EPS = 1.0e-4   # strain within this of zero is the origin, not a cutoff


def _trace_xy(fn, grid, peak):
    """Sample a material law, inserting a true vertical at each hard cutoff.

    A failure (concrete crushing at ``eps_cu2``, steel/tendon rupture at
    ``eut``) is an instantaneous drop to zero stress, but it falls between two
    samples and would otherwise be drawn as a slanted line across the gap. Where
    consecutive samples jump to/from zero, bisect to the exact cutoff strain and
    emit two points at that strain so the drop renders vertical. ``peak`` guards
    against treating the continuous pass through zero at the origin as a cutoff.
    """
    xs, ys = [], []
    pe = ps = None
    tol = 0.02 * peak
    for e in grid:
        s = fn(e)
        if ps is not None:
            z0, z1 = abs(ps) < 1e-9, abs(s) < 1e-9
            live = s if z0 else ps
            if z0 != z1 and abs(live) > tol:           # a candidate failure drop
                lo, hi = pe, e
                for _ in range(50):
                    mid = 0.5 * (lo + hi)
                    if (abs(fn(mid)) < 1e-9) == z0:
                        lo = mid
                    else:
                        hi = mid
                ec_strain = 0.5 * (lo + hi)
                # A genuine cutoff (rupture/crushing) is at a finite failure strain.
                # A one-sided law (zero in compression, elastic in tension) crosses
                # zero *at the origin*, where it is continuous -- not a drop -- so
                # the elastic branch ramps from zero rather than stepping up.
                if abs(ec_strain) > _ORIGIN_EPS:
                    ec = ec_strain * 1000.0
                    xs += [ec, ec]
                    ys += [0.0, live] if z0 else [live, 0.0]
        xs.append(e * 1000.0)
        ys.append(s)
        pe, ps = e, s
    return xs, ys


def _with_corners(grid, markers, lo, hi):
    """Add a law's corner strains to a uniform sampling grid.

    A piecewise-linear law (e.g. the elastic-then-yield steel branches) changes
    slope at its corners. On a uniform grid a corner almost never lands on a
    sample, so the single segment spanning it averages the two slopes and draws
    the kink as a shallow ramp -- looking like a spurious second yield. Injecting
    the corner strains (from ``diagram_markers``) and the origin as exact grid
    points puts a true vertex at every slope change, so each branch keeps its own
    slope right up to the corner.
    """
    pts = set(grid)
    pts.add(0.0 if lo <= 0.0 <= hi else lo)
    pts.update(m[0] for m in markers if lo <= m[0] <= hi)
    return sorted(pts)


def _curve_figure(material, eps_min, eps_max, title, n=240):
    """Stress-strain diagram of a material law over a strain range (tension +).

    The characteristic curve carries the input labels (the values the user
    enters) and is drawn solid; the partial-factored design curve is shown
    lighter for reference. Points of interest are dotted and labelled at the
    axes. Hard cutoffs (crushing/rupture) render as true verticals. The strain
    axis is in per-mille so compression (negative) and tension (positive) are
    both visible; stress in MPa.
    """
    base = _linspace(eps_min, eps_max, n)
    # The design and characteristic curves have their corners at different strains
    # (the partial factors shift the yield strain), so each gets its own grid.
    eps_d = _with_corners(base, material.diagram_markers(design=True), eps_min, eps_max)
    eps_c = _with_corners(base, material.diagram_markers(design=False), eps_min, eps_max)
    design = [material.stress(e, design=True) for e in eps_d]
    char = [material.stress(e, design=False) for e in eps_c]
    peak = max((abs(v) for v in design + char), default=0.0) or 1.0
    xd, yd = _trace_xy(lambda e: material.stress(e, design=True), eps_d, peak)
    xc, yc = _trace_xy(lambda e: material.stress(e, design=False), eps_c, peak)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=xd, y=yd, mode="lines", name="design",
                             line=dict(color=CURVE_DESIGN, width=1.5, dash="dot")))
    fig.add_trace(go.Scatter(x=xc, y=yc, mode="lines", name="characteristic",
                             line=dict(color=CURVE_CHAR, width=2.5)))
    # Markers sit on the characteristic curve and are labelled with the input
    # parameters, so editing any input visibly moves a labelled point.
    _apply_markers(fig, material.diagram_markers(design=False), eps_min, eps_max,
                   min(design + char), max(design + char))
    _slope_label(fig, material)
    fig.update_layout(
        title=dict(text=title, y=0.97),
        template=_TEMPLATE, height=340,
        margin=dict(l=58, r=54, t=44, b=96),
        xaxis=dict(title=dict(text="Strain " + _EPS + " [" + _PERMILLE + "]",
                              standoff=10),
                   zeroline=True, showgrid=True),
        yaxis=dict(title="Stress " + _SIGMA + " [MPa]",
                   zeroline=True, showgrid=True),
        legend=dict(orientation="h", yanchor="top", y=-0.34, x=0.5,
                    xanchor="center"),
    )
    return fig


def concrete_curve_figure(concrete, title="Concrete"):
    """Stress-strain diagram for a concrete law (compression is negative)."""
    # Slightly past the ultimate strain on the compression side, a little tension
    # (the default eps_cu2 = 0.0035 gives the usual -0.0042 window).
    return _curve_figure(concrete, -(concrete.eps_cu2 + 0.0007), 0.0006, title)


def prestress_curve_figure(prestress, title="Prestressing steel"):
    """Stress-strain diagram for a prestressing-steel law (tension only).

    Tendons carry tension only, so the strain window starts just below zero and
    runs a little past the rupture strain (so the ultimate point shows). The
    strain axis is the *total* tendon strain -- the effective prestrain plus the
    section strain at the tendon.
    """
    top = prestress.rupture_strain
    top = top if 0.0 < top <= 0.06 else 0.035
    return _curve_figure(prestress, -0.001, top * 1.02, title)


def steel_curve_figure(steel, title="Mild steel", eps_max=0.025):
    """Stress-strain diagram for a reinforcement law (tension and compression).

    The window is scaled to the largest visible strain -- the rupture strain
    ``eut`` when it is finite and not extreme -- and is symmetric, because the
    rupture applies in both tension and compression. A no-strain-limit law (very
    large ``eut``) falls back to the default window.
    """
    top = steel.eut if 0.0 < steel.eut <= 0.1 else eps_max
    top = max(top, 0.01) * 1.06   # a little past eut so the rupture drop is visible
    return _curve_figure(steel, -top, top, title)


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
                      label_min_gap=0.04):
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
        keep = _decimate(rebar, min_dist)
        fig.add_trace(go.Scatter(
            x=[rebar[i][0] for i in keep], y=[rebar[i][1] for i in keep], mode="text",
            text=[str(i + 1) for i in keep], textposition="top center",
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


# The section / interaction plots put a horizontal legend below the x-axis title.
# ``legend.y`` is in paper coordinates (a fraction of the plot *area*, which grows
# with the figure height), so a constant y would sit a larger pixel distance below
# a taller plot and spill past the fixed bottom margin. Scale y inversely with the
# plot-area height so the legend keeps a constant pixel gap below the axis title
# (matching the stress-strain figure) and stays inside the margin at any height.
_LEGEND_TOP_M, _LEGEND_BOT_M = 40, 96
_LEGEND_GAP_PX = 68.0


def _legend_y(height: float) -> float:
    plot_h = max(height - _LEGEND_TOP_M - _LEGEND_BOT_M, 1.0)
    return -_LEGEND_GAP_PX / plot_h


def _point_hover(points, first_number, kind, unit, extra=None):
    """Per-point hover strings ``'Kind N<br>x, y[<br>area][<br>extra]'`` for the
    section drawing.

    Numbering continues from ``first_number`` so it matches the drawn labels and the
    result tables (bars 1..n, tendons n+1.., concrete corners 1..). Coordinates are
    the already-scaled display values, shown in ``unit`` (0 decimals for mm, 3 for
    m). A reinforcement ``area`` (a 3rd tuple element, always in mm2) is shown when
    present; concrete corners are 2-tuples and carry none. ``extra`` is an optional
    per-point string (e.g. a stress/strain read-out) appended on its own line.
    """
    dec = 3 if unit == "m" else 0
    lines = []
    for i, p in enumerate(points):
        s = (f"{kind} {first_number + i}<br>"
             f"x = {p[0]:.{dec}f} {unit}, y = {p[1]:.{dec}f} {unit}")
        if len(p) > 2 and p[2] is not None:
            s += f"<br>area = {p[2]:.0f} mm<sup>2</sup>"
        if extra is not None and i < len(extra) and extra[i]:
            s += f"<br>{extra[i]}"
        lines.append(s)
    return lines


def section_figure(outer, holes=None, bars=None, bar_colors=None,
                   na_line=None, title="Section", tendons=None, tendon_colors=None,
                   zones=None, show_labels=False, label_scale=1.0, label_min_gap=0.04,
                   height=440, scale=1.0, unit="m", bar_hover=None, tendon_hover=None):
    """Draw the section: concrete outline, holes, reinforcement and neutral axis.

    Reinforcement is drawn consistently across the views: bars are circles and
    tendons are diamonds, each coloured by ``bar_colors`` / ``tendon_colors``
    (e.g. by stress sign) when given, else a neutral colour. ``outer`` / ``holes``
    / ``bars`` / ``na_line`` / ``zones`` are all given in metres; ``scale`` (and
    the matching axis ``unit`` label) converts them for display -- e.g. ``1000`` /
    ``"mm"`` draws the section in millimetres. ``show_labels`` numbers the
    reinforcement and concrete corners; ``label_scale`` scales the label font and
    ``label_min_gap`` is the minimum label spacing (fraction of the section size)
    below which labels are thinned out -- the two are independent.
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
    for verts, color, name in zones or []:
        if len(verts) >= 3:
            zx, zy = _ring_xy(verts)
            fig.add_trace(go.Scatter(x=zx, y=zy, fill="toself", mode="lines",
                                     fillcolor=color, line=dict(width=0),
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
    if corner_verts:
        fig.add_trace(go.Scatter(
            x=[v[0] for v in corner_verts], y=[v[1] for v in corner_verts],
            mode="markers", marker=dict(size=12, color="rgba(0,0,0,0)"),
            customdata=_point_hover(corner_verts, 1, "Corner", unit),
            hovertemplate="%{customdata}<extra></extra>", showlegend=False))
    if bars:
        bx = [b[0] for b in bars]
        by = [b[1] for b in bars]
        colors = bar_colors or [BAR_NEUTRAL] * len(bars)
        fig.add_trace(go.Scatter(x=bx, y=by, mode="markers", name="reinforcing bar",
                                 marker=dict(size=9, symbol="circle", color=colors,
                                             line=dict(color="white", width=1)),
                                 customdata=_point_hover(bars, 1, "Bar", unit, bar_hover),
                                 hovertemplate="%{customdata}<extra></extra>",
                                 showlegend=True))
    if tendons:
        tx = [t[0] for t in tendons]
        ty = [t[1] for t in tendons]
        colors = tendon_colors or [TENDON] * len(tendons)
        fig.add_trace(go.Scatter(x=tx, y=ty, mode="markers", name="tendon",
                                 marker=dict(size=11, symbol="diamond", color=colors,
                                             line=dict(color="white", width=1)),
                                 customdata=_point_hover(tendons, len(bars) + 1, "Tendon",
                                                         unit, tendon_hover),
                                 hovertemplate="%{customdata}<extra></extra>",
                                 showlegend=True))
    if na_line:
        x0, y0, x1, y1 = na_line
        fig.add_trace(go.Scatter(x=[x0, x1], y=[y0, y1], mode="lines",
                                 line=dict(color=NA_LINE, width=2, dash="dash"),
                                 name="neutral axis"))
    if show_labels:
        _add_point_labels(fig, outer, holes, bars, tendons, label_scale, label_min_gap)
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


def interaction_figure(mx, my, applied=None, angles=None, util=None,
                       closed=True, title="M-M interaction"):
    """Biaxial moment capacity envelope, with an optional applied-load point.

    Drawn to match the section's orientation: ``Mx`` is bending *about* the
    x-axis (its stress varies with y), so it is the **vertical** axis here, and
    ``My`` (about the y-axis) is the **horizontal** axis. The two axes share a
    common scale (equal aspect), so the envelope keeps its true shape. ``applied``
    is ``(Mx, My)``. ``angles`` (the swept neutral-axis angle at each envelope
    vertex, aligned with ``mx``/``my``) is shown on hover. When ``util`` (the
    radial utilisation) is given with ``applied``, a dotted ray from the origin
    through the applied point marks the capacity in that load direction, so the
    utilisation reads off the figure.
    """
    # Snap the floating-point noise at the apexes to zero: a pure-Mx (or pure-My)
    # point should sit on the axis, but the solver leaves a tiny residual that the
    # hover would otherwise show as e.g. "(333.9551, 0.0007)". Round it to 0 so the
    # apex reads cleanly; the threshold is relative to the envelope size.
    scale = max((abs(v) for v in list(mx) + list(my)), default=1.0) or 1.0
    snap = lambda v: 0.0 if abs(v) <= scale * 1e-4 else v
    mx = [snap(v) for v in mx]
    my = [snap(v) for v in my]

    fig = go.Figure()
    # My on the horizontal axis, Mx on the vertical -- see the note above. A full 360
    # sweep is a CLOSED envelope: repeat the first vertex and fill it so it reads as an
    # enclosed capacity region. A partial sweep is an OPEN arc, drawn as a bare line (no
    # closing chord, no fill) -- filling it would shade a capacity area across the
    # artificial closing chord that was never computed.
    if closed:
        cap = go.Scatter(x=my + my[:1], y=mx + mx[:1], mode="lines", fill="toself",
                         fillcolor=ENVELOPE_FILL, line=dict(color=ENVELOPE, width=2),
                         name="capacity")
        cap_angles = (list(angles) + list(angles[:1])) if angles is not None else None
    else:
        cap = go.Scatter(x=list(my), y=list(mx), mode="lines",
                         line=dict(color=ENVELOPE, width=2),
                         name="capacity (partial arc)")
        cap_angles = list(angles) if angles is not None else None
    if angles is not None and len(angles) == len(mx):
        cap.customdata = cap_angles
        cap.hovertemplate = ("V = %{customdata:.0f} deg<br>My = %{x:.1f} kNm"
                             "<br>Mx = %{y:.1f} kNm<extra></extra>")
    else:
        cap.hovertemplate = "My = %{x:.1f} kNm<br>Mx = %{y:.1f} kNm<extra></extra>"
    fig.add_trace(cap)

    if applied is not None:
        a_mx, a_my = snap(applied[0]), snap(applied[1])
        # Utilisation ray: origin -> applied -> the envelope crossing in that same
        # direction (capacity = applied / util). The applied point then sits at the
        # fraction ``util`` of the way out to the capacity, so the ratio is visual.
        if util is not None and math.isfinite(util) and util > 1e-9:
            gx, gy = a_my / util, a_mx / util
            fig.add_trace(go.Scatter(
                x=[0.0, gx], y=[0.0, gy], mode="lines",
                line=dict(color=GUIDE_LINE, width=1, dash="dot"),
                name="load direction", hoverinfo="skip"))
            fig.add_trace(go.Scatter(
                x=[gx], y=[gy], mode="markers", name="capacity (this direction)",
                marker=dict(size=11, color=ENVELOPE, symbol="circle-open",
                            line=dict(width=2)),
                hovertemplate="My = %{x:.1f} kNm<br>Mx = %{y:.1f} kNm<extra></extra>"))
        fig.add_trace(go.Scatter(
            x=[a_my], y=[a_mx], mode="markers",
            marker=dict(size=11, color=LOAD_POINT, symbol="x"), name="applied",
            hovertemplate="My = %{x:.1f} kNm<br>Mx = %{y:.1f} kNm<extra></extra>"))
        if util is not None and math.isfinite(util):
            # Below-right of the applied point, clear of the (up-and-out) load ray.
            fig.add_annotation(x=a_my, y=a_mx, text=f"util = {util:.2f}",
                               showarrow=True, arrowhead=2, arrowsize=0.7,
                               arrowwidth=1, arrowcolor=GUIDE_LINE, ax=32, ay=26,
                               font=dict(size=11, color=LOAD_POINT))
    fig.update_layout(
        title=title, template=_TEMPLATE, height=440,
        margin=dict(l=10, r=10, t=_LEGEND_TOP_M, b=_LEGEND_BOT_M),
        xaxis=dict(title=dict(text="My - about the y-axis (kNm)", standoff=10),
                   zeroline=True),
        yaxis=dict(title="Mx - about the x-axis (kNm)", zeroline=True,
                   scaleanchor="x", scaleratio=1),
        # Below the plot and below the x-axis title, clear of the plotly modebar.
        legend=dict(orientation="h", yanchor="top", y=_legend_y(440), x=0.5,
                    xanchor="center"),
    )
    return fig


def interaction_nm_figure(N, M, axis="x", applied=None, title="N-M interaction"):
    """Axial-moment (N-M) capacity diagram: N vertical, M horizontal.

    ``N`` (kN, tension positive) and ``M`` (kNm, about ``axis``) trace the closed
    capacity boundary -- the ``+M`` branch from pure tension to the squash load then
    the ``-M`` branch back. ``applied`` is ``(N, M)`` and marked on the diagram.
    """
    mlabel = "M_x" if axis == "x" else "M_y"
    scale = max((abs(v) for v in list(N) + list(M)), default=1.0) or 1.0
    snap = lambda v: 0.0 if abs(v) <= scale * 1e-4 else v
    Ms = [snap(v) for v in M]
    hover = ("M = %{x:.1f} kNm<br>N = %{y:.1f} kN<extra></extra>")

    fig = go.Figure()
    # Close the polyline (repeat the first vertex) so the boundary is drawn all the
    # way round, not just filled: without this the outline has a gap between the two
    # tension apexes.
    Ns = list(N)
    fig.add_trace(go.Scatter(x=Ms + Ms[:1], y=Ns + Ns[:1], mode="lines", fill="toself",
                             line=dict(color=ENVELOPE, width=2), name="capacity",
                             fillcolor=ENVELOPE_FILL, hovertemplate=hover))
    # Landmark points (derived from the boundary): the squash load (most
    # compression), the tension limit (most tension) and the max-moment apex. They
    # make the figure readable on its own.
    if Ns:
        i_sq = min(range(len(Ns)), key=lambda i: Ns[i])     # min N = squash
        i_te = max(range(len(Ns)), key=lambda i: Ns[i])     # max N = tension limit
        # SIGNED maximum (not abs): the "max Mx/My" label must sit on the positive
        # branch to match the signed "Max Mx/My" reported in the metrics. On an
        # asymmetric section the negative branch can have a larger |M|, so abs() would
        # place the label on the wrong side and contradict the numeric result.
        i_mm = max(range(len(Ms)), key=lambda i: Ms[i])       # positive max moment
        fig.add_trace(go.Scatter(
            x=[Ms[i_sq], Ms[i_te], Ms[i_mm]], y=[Ns[i_sq], Ns[i_te], Ns[i_mm]],
            mode="markers", marker=dict(size=7, color=ENVELOPE, symbol="diamond"),
            name="landmarks", hovertemplate=hover))
        # Short descriptors (the exact values are in the metrics row and on hover),
        # placed so they never clip the frame in the half-width side-by-side view:
        # squash below its apex, tension above its apex, max-moment just left of the
        # right-most apex.
        fig.add_annotation(x=Ms[i_sq], y=Ns[i_sq], text="squash", showarrow=False,
                           yshift=-11, yanchor="top", font=dict(size=11, color=ENVELOPE))
        fig.add_annotation(x=Ms[i_te], y=Ns[i_te], text="tension", showarrow=False,
                           yshift=11, yanchor="bottom", font=dict(size=11, color=ENVELOPE))
        fig.add_annotation(x=Ms[i_mm], y=Ns[i_mm], text="max " + mlabel.replace("_", ""),
                           showarrow=False, xshift=-8, xanchor="right",
                           font=dict(size=11, color=ENVELOPE))
    if applied is not None:
        fig.add_trace(go.Scatter(x=[snap(applied[1])], y=[applied[0]], mode="markers",
                                 marker=dict(size=11, color=LOAD_POINT, symbol="x"),
                                 name="applied", hovertemplate=hover))
    fig.update_layout(
        title=title, template=_TEMPLATE, height=460,
        margin=dict(l=10, r=10, t=_LEGEND_TOP_M, b=_LEGEND_BOT_M),
        xaxis=dict(title=dict(text=f"{mlabel.replace('_', '')} (kNm)", standoff=10),
                   zeroline=True),
        yaxis=dict(title="N (kN, tension +)", zeroline=True),
        legend=dict(orientation="h", yanchor="top", y=_legend_y(460), x=0.5,
                    xanchor="center"),
    )
    return fig


def vt_interaction_figure(vrd_max, trd_max, v_ed, t_ed,
                          title="V-T interaction (crushing)"):
    """Shear-torsion concrete-crushing envelope (EN 1992-1-1 6.29).

    The limit ``VEd/VRd,max + TEd/TRd,max = 1`` is the straight line from
    ``(VRd,max, 0)`` to ``(0, TRd,max)``; the safe region is below it. ``V`` is
    horizontal (kN), ``T`` vertical (kNm); the applied ``(VEd, TEd)`` is marked.
    """
    fig = go.Figure()
    if vrd_max > 0.0 and trd_max > 0.0:
        fig.add_trace(go.Scatter(
            x=[vrd_max, 0.0], y=[0.0, trd_max], mode="lines", fill="tozeroy",
            line=dict(color=ENVELOPE, width=2), name="limit (= 1)",
            fillcolor=ENVELOPE_FILL,
            hovertemplate="V = %{x:.1f} kN<br>T = %{y:.1f} kNm<extra></extra>"))
        # Interaction sum V/VRd,max + T/TRd,max: the applied point sits at that
        # fraction along the ray from the origin to the limit line, so draw the ray
        # to the crossing and annotate the sum (<= 1 is safe).
        s = v_ed / vrd_max + t_ed / trd_max
        if s > 1e-9:
            fig.add_trace(go.Scatter(
                x=[0.0, v_ed / s], y=[0.0, t_ed / s], mode="lines",
                line=dict(color=GUIDE_LINE, width=1, dash="dot"),
                name="load direction", hoverinfo="skip"))
            ok = s <= 1.0 + 1e-9
            fig.add_annotation(
                x=v_ed, y=t_ed, ax=30, ay=26, showarrow=True, arrowhead=2,
                arrowsize=0.7, arrowwidth=1, arrowcolor=GUIDE_LINE,
                text=f"sum = {s:.2f} ({'OK' if ok else 'over'})",
                font=dict(size=11, color=(ENVELOPE if ok else LOAD_POINT)))
    fig.add_trace(go.Scatter(
        x=[v_ed], y=[t_ed], mode="markers",
        marker=dict(size=11, color=LOAD_POINT, symbol="x"), name="applied",
        hovertemplate="V_Ed = %{x:.1f} kN<br>T_Ed = %{y:.1f} kNm<extra></extra>"))
    fig.update_layout(
        title=title, template=_TEMPLATE, height=460,
        margin=dict(l=10, r=10, t=_LEGEND_TOP_M, b=_LEGEND_BOT_M),
        xaxis=dict(title=dict(text="V_Ed (kN)", standoff=10), zeroline=True,
                   rangemode="tozero"),
        yaxis=dict(title="T_Ed (kNm)", zeroline=True, rangemode="tozero"),
        legend=dict(orientation="h", yanchor="top", y=_legend_y(460), x=0.5,
                    xanchor="center"),
    )
    return fig


def tube_figure(outer, holes=None, tef_mm=0.0, ak_m2=None,
                title="Torsion tube", scale=1000.0, unit="mm"):
    """Thin-walled torsion tube (EN 1992-1-1 6.3.2): the concrete outline, the
    effective wall of thickness ``tef`` and the wall centre-line that encloses the
    torsion area ``Ak``. Geometry in metres; ``scale`` / ``unit`` draw it in mm by
    default. The centre-line and inner face reuse the engine's inward offset, so
    they match the tube the resistance was computed on.
    """
    from sector import torsion   # local import keeps viz free of a load-order cycle
    fig = go.Figure()
    # Guard with ``is None`` rather than a truth test: the section model stores rings
    # as NumPy arrays, whose truth value is ambiguous (as in section_figure).
    outer = [] if outer is None else list(outer)
    holes = [] if holes is None else list(holes)
    if len(outer) >= 3:
        ox, oy = _ring_xy([(p[0] * scale, p[1] * scale) for p in outer])
        fig.add_trace(go.Scatter(x=ox, y=oy, fill="toself", mode="lines",
                                 fillcolor=CONCRETE_FILL, line=dict(color=CONCRETE_LINE),
                                 name="outline", hoverinfo="skip"))
    for hole in holes:
        hx, hy = _ring_xy([(p[0] * scale, p[1] * scale) for p in hole])
        fig.add_trace(go.Scatter(x=hx, y=hy, fill="toself", mode="lines",
                                 fillcolor=HOLE_FILL, line=dict(color=CONCRETE_LINE, dash="dot"),
                                 name="void", hoverinfo="skip", showlegend=False))
    tef_m = (tef_mm or 0.0) / 1000.0
    have_tube = tef_m > 0.0 and len(outer) >= 3
    centre = torsion.offset_polygon_inward(outer, tef_m / 2.0) if have_tube else None
    inner = torsion.offset_polygon_inward(outer, tef_m) if have_tube else None
    if inner:
        ix, iy = _ring_xy([(p[0] * scale, p[1] * scale) for p in inner])
        fig.add_trace(go.Scatter(x=ix, y=iy, mode="lines",
                                 line=dict(color=CONCRETE_LINE, width=1, dash="dot"),
                                 name=f"inner wall face (tef = {tef_mm:.0f} mm)"))
    if centre:
        cx, cy = _ring_xy([(p[0] * scale, p[1] * scale) for p in centre])
        ak_txt = f" (Ak = {ak_m2 * 1.0e6:,.0f} mm2)" if ak_m2 else ""
        fig.add_trace(go.Scatter(x=cx, y=cy, mode="lines",
                                 line=dict(color=ENVELOPE, width=2, dash="dash"),
                                 name="wall centre-line" + ak_txt))
    fig.update_layout(
        title=title, template=_TEMPLATE, height=440,
        margin=dict(l=10, r=10, t=_LEGEND_TOP_M, b=_LEGEND_BOT_M),
        xaxis=dict(title=dict(text=f"x ({unit})", standoff=10), zeroline=True),
        yaxis=dict(title=f"y ({unit})", scaleanchor="x", scaleratio=1, zeroline=True),
        legend=dict(orientation="h", yanchor="top", y=_legend_y(440), x=0.5,
                    xanchor="center"),
    )
    return fig


def subtube_figure(subtubes, title="Torsion sub-tubes (6.3.1(3))"):
    """Component rectangles of a subdivided (compound) torsion section.

    Each sub-tube is drawn at its true ``b x h`` (mm) with its wall centre-line, laid
    out left to right (the web first), and labelled with its torsion share ``TEd,i`` /
    capacity ``TRd,i`` and utilisation. A schematic of the decomposition (EN 1992-1-1
    6.3.1(3)), not the assembled section.
    """
    fig = go.Figure()
    subtubes = list(subtubes or [])
    if not subtubes:
        fig.update_layout(title=title, template=_TEMPLATE, height=340)
        return fig
    gap = 0.12 * max(max(s["b_mm"], s["h_mm"]) for s in subtubes)
    x0 = 0.0
    for i, s in enumerate(subtubes):
        b, h, tef = s["b_mm"], s["h_mm"], s["tube"]["tef"]
        role = "web" if i == 0 else f"part {i + 1}"
        fig.add_trace(go.Scatter(
            x=[x0, x0 + b, x0 + b, x0, x0], y=[-h / 2, -h / 2, h / 2, h / 2, -h / 2],
            fill="toself", mode="lines", fillcolor=CONCRETE_FILL,
            line=dict(color=CONCRETE_LINE, width=2), name=role, hoverinfo="skip",
            showlegend=False))
        if 0.0 < tef < min(b, h):            # wall centre-line, inset by tef/2
            fig.add_trace(go.Scatter(
                x=[x0 + tef / 2, x0 + b - tef / 2, x0 + b - tef / 2, x0 + tef / 2,
                   x0 + tef / 2],
                y=[-h / 2 + tef / 2, -h / 2 + tef / 2, h / 2 - tef / 2, h / 2 - tef / 2,
                   -h / 2 + tef / 2],
                mode="lines", line=dict(color=ENVELOPE, width=1.5, dash="dash"),
                hoverinfo="skip", showlegend=False))
        util_txt = "inf" if not math.isfinite(s["util"]) else f"{s['util'] * 100:.0f}%"
        fig.add_annotation(
            x=x0 + b / 2, y=-h / 2, yshift=-12, showarrow=False,
            text=(f"<b>{role}</b><br>{b:.0f} x {h:.0f} mm<br>"
                  f"TEd {s['t_ed']:.1f} / TRd {s['trd']:.1f} kNm<br>util {util_txt}"),
            font=dict(size=11, color=SCHEMATIC_INK), align="center")
        x0 += b + gap
    fig.update_layout(
        title=title, template=_TEMPLATE, height=380,
        margin=dict(l=10, r=10, t=40, b=76),
        xaxis=dict(title="", showticklabels=False, zeroline=False),
        yaxis=dict(title="mm", scaleanchor="x", scaleratio=1, zeroline=False),
        showlegend=False)
    return fig


def truss_figure(theta_deg, z_mm, legs=2.0, dia_mm=0.0, s_mm=0.0,
                 title="Variable-strut truss"):
    """Schematic of the variable-angle truss (EN 1992-1-1 6.2.3): the compression
    chord and the tension chord a lever arm ``z`` apart, an inclined concrete strut
    at angle ``theta``, and the vertical link ties at spacing ``s``. A schematic
    (equal aspect so the strut angle reads true), not drawn to section scale.
    """
    fig = go.Figure()
    z = max(z_mm or 0.0, 1.0)
    th = math.radians(theta_deg) if theta_deg else math.radians(45.0)
    cot = (1.0 / math.tan(th)) if math.tan(th) > 1.0e-9 else 1.0
    panel = z * cot                        # horizontal run of one strut
    L = panel * 1.3                        # a little chord beyond one strut panel
    fig.add_trace(go.Scatter(x=[0, L], y=[z, z], mode="lines",
                             line=dict(color=BAR_COMPRESSION, width=3),
                             name="compression chord"))
    fig.add_trace(go.Scatter(x=[0, L], y=[0, 0], mode="lines",
                             line=dict(color=BAR_TENSION, width=3),
                             name="tension chord"))
    fig.add_trace(go.Scatter(x=[0, panel], y=[0, z], mode="lines",
                             line=dict(color=CONCRETE_LINE, width=7), opacity=0.55,
                             name=f"strut theta = {theta_deg:.1f} deg"))
    # Vertical link ties at spacing s (capped so a very small s stays legible).
    step = s_mm if (s_mm and s_mm > 0.0) else (L / 4.0)
    xs, x = [], 0.0
    while x <= L + 1.0e-6 and len(xs) < 30:
        xs.append(x)
        x += step
    tie_name = f"links (s = {s_mm:.0f} mm)" if s_mm else "links"
    for k, xv in enumerate(xs):
        fig.add_trace(go.Scatter(x=[xv, xv], y=[0, z], mode="lines",
                                 line=dict(color=LINK_LINE, width=1.5),
                                 name=tie_name, showlegend=(k == 0)))
    # Angle arc at the strut base (between the tension chord and the strut) so the
    # strut angle theta reads directly off the figure.
    ar = 0.34 * z
    t_arc = [th * i / 24.0 for i in range(25)]
    fig.add_trace(go.Scatter(x=[ar * math.cos(t) for t in t_arc],
                             y=[ar * math.sin(t) for t in t_arc], mode="lines",
                             line=dict(color=SCHEMATIC_INK, width=1.2),
                             hoverinfo="skip", showlegend=False))
    fig.add_annotation(x=ar * 1.3 * math.cos(th / 2.0), y=ar * 1.3 * math.sin(th / 2.0),
                       text=chr(0x3B8), showarrow=False,
                       font=dict(size=13, color=SCHEMATIC_INK))
    # z as a dimension arrow (double-headed) just right of the panel, not floating text.
    zx = L * 1.06
    for y_end, y_in in ((z, z * 0.82), (0.0, z * 0.18)):
        fig.add_annotation(x=zx, y=y_end, ax=zx, ay=y_in, axref="x", ayref="y",
                           showarrow=True, arrowhead=2, arrowsize=1.0, arrowwidth=1,
                           arrowcolor=SCHEMATIC_INK, text="")
    fig.add_annotation(x=zx, y=z / 2.0, text=f"z = {z:.0f} mm", showarrow=False,
                       xanchor="left", xshift=7, font=dict(size=11, color=SCHEMATIC_INK))
    fig.update_layout(
        title=title, template=_TEMPLATE, height=320,
        margin=dict(l=10, r=10, t=_LEGEND_TOP_M, b=_LEGEND_BOT_M),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False, scaleanchor="x", scaleratio=1),
        legend=dict(orientation="h", yanchor="top", y=_legend_y(320), x=0.5,
                    xanchor="center"),
    )
    return fig


def na_endpoints(x_int, y_int, extent):
    """Two points spanning the neutral axis from its axis intercepts.

    Returns ``(x0, y0, x1, y1)`` clipped to +/- ``extent``, or ``None`` if the
    axis is not well defined (both intercepts infinite).
    """
    fx = math.isfinite(x_int)
    fy = math.isfinite(y_int)
    if fx and fy:
        return (x_int, 0.0, 0.0, y_int)
    if fx and not fy:  # vertical line x = x_int
        return (x_int, -extent, x_int, extent)
    if fy and not fx:  # horizontal line y = y_int
        return (-extent, y_int, extent, y_int)
    return None


def na_line_at(a, b, c, extent):
    """Endpoints of the line ``a*x + b*y + c = 0`` spanning +/- ``extent``.

    ``(a, b)`` is the (unit) normal. The line's closest point to the origin is
    ``-c*(a, b)``; the segment runs along the line direction ``(-b, a)``.
    """
    px, py = -c * a, -c * b
    return (px - extent * b, py + extent * a, px + extent * b, py - extent * a)


def plastic_halfplane(V_deg, na_x, na_y):
    """Compression half-plane (a*x + b*y + c >= 0) for a plastic NA angle.

    The compression gradient is ``(cos V, sin V)``; the NA is ``a*x + b*y = s_na``
    with ``s_na`` recovered from whichever axis intercept is finite.
    """
    v = math.radians(V_deg)
    a, b = math.cos(v), math.sin(v)
    if math.isfinite(na_x) and abs(a) > 1e-9:
        s_na = na_x * a
    elif math.isfinite(na_y) and abs(b) > 1e-9:
        s_na = na_y * b
    else:
        s_na = 0.0
    return a, b, -s_na


def elastic_halfplane(na_x, na_y, inside_xy):
    """Compression half-plane from the NA axis intercepts, oriented so the point
    of maximum concrete compression lies on the positive (compression) side."""
    fx, fy = math.isfinite(na_x), math.isfinite(na_y)
    if fx and fy:
        a, b, c = na_y, na_x, -na_x * na_y      # line through (na_x,0) and (0,na_y)
    elif fx:
        a, b, c = 1.0, 0.0, -na_x               # vertical x = na_x
    elif fy:
        a, b, c = 0.0, 1.0, -na_y               # horizontal y = na_y
    else:
        return None
    n = math.hypot(a, b) or 1.0
    a, b, c = a / n, b / n, c / n
    if a * inside_xy[0] + b * inside_xy[1] + c < 0.0:
        a, b, c = -a, -b, -c
    return a, b, c


def compression_zones(outer, halfplane):
    """Compression and tension zone polygons for a section split by a half-plane."""
    if halfplane is None:
        return None
    a, b, c = halfplane
    comp = geometry.clip_halfplane(outer, a, b, c)
    tens = geometry.clip_halfplane(outer, -a, -b, -c)
    zones = []
    if len(comp) >= 3:
        zones.append((comp.tolist(), COMP_ZONE_FILL, "compression zone"))
    if len(tens) >= 3:
        zones.append((tens.tolist(), TENS_ZONE_FILL, "tension side"))
    return zones or None


def halfplane_bar_colors(points, halfplane, kappa=0.0, prestrain=0.0):
    """Colour reinforcement by tension/compression at a plastic neutral-axis state.

    ``halfplane`` is the compression half-plane ``(a, b, c)`` from
    :func:`plastic_halfplane` (``a*x + b*y + c >= 0`` is the compression side, with
    ``(a, b)`` unit-norm so ``a*x + b*y + c`` is the signed distance ``d`` from the
    neutral axis). The section strain at a point (compression positive) is
    ``kappa*d``, so a bar's net strain (tension positive) is ``prestrain - kappa*d``.
    A non-negative net strain is tension (green), the rest compression (red) --
    matching the elastic view's stress-sign colouring.

    Mild bars pass ``prestrain = 0`` (their colour is just the neutral-axis side);
    tendons pass their locked-in prestrain ``IS`` so a tendon on the compression
    side still reads as tension when the prestrain dominates. ``points`` are given
    in the same (metre) units as the half-plane. Returns ``None`` for no half-plane.
    """
    if halfplane is None:
        return None
    a, b, c = halfplane
    return [BAR_TENSION if prestrain - kappa * (a * p[0] + b * p[1] + c) >= 0.0
            else BAR_COMPRESSION for p in points]
