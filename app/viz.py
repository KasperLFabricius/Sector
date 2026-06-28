"""Plotly figures for the Sector UI: the section drawing and the N-M diagram."""

from __future__ import annotations

import math

import plotly.graph_objects as go

CONCRETE_FILL = "rgba(120,130,140,0.18)"
CONCRETE_LINE = "#5b6770"
BAR_TENSION = "#1d9e75"
BAR_COMPRESSION = "#c0392b"
BAR_NEUTRAL = "#534ab7"
TENDON = "#0b7285"
NA_LINE = "#e08a1e"
COMP_ZONE_FILL = "rgba(192,57,43,0.22)"   # concrete compression zone
TENS_ZONE_FILL = "rgba(29,158,117,0.12)"  # tension side (no concrete stress)
ENVELOPE = "#534ab7"
LOAD_POINT = "#c0392b"
DESIGN_LINE = "#534ab7"
CHAR_LINE = "#9aa3ab"
GUIDE_LINE = "#b8bdc4"

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
        mode="markers", marker=dict(size=8, color=DESIGN_LINE,
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
                           font=dict(size=12, color=DESIGN_LINE))

    # Stress symbols on the right edge (the numeric stress ticks stay on the
    # left axis), nudged apart so they never overlap one another.
    y_groups = _grouped(pts, "y")
    y_span = (ymax - ymin) or 1.0
    y_lab = _spread([v for v, _ in y_groups], y_span * 0.08)
    for (y0, keys), yl in zip(y_groups, y_lab):
        fig.add_hline(y=y0, line_width=0.8, line_dash="dot", line_color=GUIDE_LINE)
        fig.add_annotation(x=1.0, xref="paper", xshift=6, y=yl, yref="y",
                           xanchor="left", showarrow=False, text=_merge_labels(keys),
                           font=dict(size=12, color=DESIGN_LINE))


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
        font=dict(size=11, color=DESIGN_LINE))


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
            if z0 != z1 and abs(live) > tol:           # a real failure drop
                lo, hi = pe, e
                for _ in range(50):
                    mid = 0.5 * (lo + hi)
                    if (abs(fn(mid)) < 1e-9) == z0:
                        lo = mid
                    else:
                        hi = mid
                ec = 0.5 * (lo + hi) * 1000.0
                xs += [ec, ec]
                ys += [0.0, live] if z0 else [live, 0.0]
        xs.append(e * 1000.0)
        ys.append(s)
        pe, ps = e, s
    return xs, ys


def _curve_figure(material, eps_min, eps_max, title, n=240):
    """Stress-strain diagram of a material law over a strain range (tension +).

    The characteristic curve carries the input labels (the values the user
    enters) and is drawn solid; the partial-factored design curve is shown
    lighter for reference. Points of interest are dotted and labelled at the
    axes. Hard cutoffs (crushing/rupture) render as true verticals. The strain
    axis is in per-mille so compression (negative) and tension (positive) are
    both visible; stress in MPa.
    """
    eps = _linspace(eps_min, eps_max, n)
    design = [material.stress(e, design=True) for e in eps]
    char = [material.stress(e, design=False) for e in eps]
    peak = max((abs(v) for v in design + char), default=0.0) or 1.0
    xd, yd = _trace_xy(lambda e: material.stress(e, design=True), eps, peak)
    xc, yc = _trace_xy(lambda e: material.stress(e, design=False), eps, peak)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=xd, y=yd, mode="lines", name="design",
                             line=dict(color=CHAR_LINE, width=1.5, dash="dot")))
    fig.add_trace(go.Scatter(x=xc, y=yc, mode="lines", name="characteristic",
                             line=dict(color=DESIGN_LINE, width=2.5)))
    # Markers sit on the characteristic curve and are labelled with the input
    # parameters, so editing any input visibly moves a labelled point.
    _apply_markers(fig, material.diagram_markers(design=False), eps_min, eps_max,
                   min(design + char), max(design + char))
    _slope_label(fig, material)
    fig.update_layout(
        title=dict(text=title, font=dict(size=13), y=0.97),
        template="plotly_white", height=340,
        margin=dict(l=58, r=54, t=44, b=96),
        xaxis=dict(title=dict(text="Strain " + _EPS + " [" + _PERMILLE + "]",
                              standoff=10),
                   zeroline=True, zerolinecolor="#c8ccd0", showgrid=True),
        yaxis=dict(title="Stress " + _SIGMA + " [MPa]",
                   zeroline=True, zerolinecolor="#c8ccd0", showgrid=True),
        legend=dict(orientation="h", yanchor="top", y=-0.34, x=0.5,
                    xanchor="center", font=dict(size=10)),
    )
    return fig


def concrete_curve_figure(concrete, title="Concrete"):
    """Stress-strain diagram for a concrete law (compression is negative)."""
    # Slightly past the ultimate strain on the compression side, a little tension.
    return _curve_figure(concrete, -0.0042, 0.0006, title)


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

    The tension side extends to the rupture strain when that is finite and not
    far off (so the ultimate point shows); a no-strain-limit law just uses the
    default window. Compression does not rupture, so it keeps the base range.
    """
    top = steel.eut if 0.0 < steel.eut <= 0.06 else eps_max
    top = max(top, 0.01)
    return _curve_figure(steel, -eps_max, top, title)


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


def section_figure(outer, holes=None, bars=None, bar_colors=None,
                   na_line=None, title="Section", tendons=None, tendon_colors=None,
                   zones=None, show_labels=False, label_scale=1.0, label_min_gap=0.04,
                   height=440):
    """Draw the section: concrete outline, holes, reinforcement and neutral axis.

    Reinforcement is drawn consistently across the views: bars are circles and
    tendons are diamonds, each coloured by ``bar_colors`` / ``tendon_colors``
    (e.g. by stress sign) when given, else a neutral colour. ``outer`` / ``holes``
    are vertex lists (m). ``na_line`` is ``(x0, y0, x1, y1)`` for the neutral
    axis. ``zones`` (optional) is a list of ``(vertices, fillcolor, name)``
    regions shaded beneath the holes. ``show_labels`` numbers the reinforcement
    and concrete corners; ``label_scale`` scales the label font and
    ``label_min_gap`` is the minimum label spacing (fraction of the section size)
    below which labels are thinned out -- the two are independent.
    """
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
                                 fillcolor="white", line=dict(color=CONCRETE_LINE, dash="dot"),
                                 hoverinfo="skip", showlegend=False))
    if bars:
        bx = [b[0] for b in bars]
        by = [b[1] for b in bars]
        colors = bar_colors or [BAR_NEUTRAL] * len(bars)
        fig.add_trace(go.Scatter(x=bx, y=by, mode="markers", name="reinforcing bar",
                                 marker=dict(size=9, symbol="circle", color=colors,
                                             line=dict(color="white", width=1)),
                                 hoverinfo="skip", showlegend=True))
    if tendons:
        tx = [t[0] for t in tendons]
        ty = [t[1] for t in tendons]
        colors = tendon_colors or [TENDON] * len(tendons)
        fig.add_trace(go.Scatter(x=tx, y=ty, mode="markers", name="tendon",
                                 marker=dict(size=11, symbol="diamond", color=colors,
                                             line=dict(color="white", width=1)),
                                 hoverinfo="skip", showlegend=True))
    if na_line:
        x0, y0, x1, y1 = na_line
        fig.add_trace(go.Scatter(x=[x0, x1], y=[y0, y1], mode="lines",
                                 line=dict(color=NA_LINE, width=2, dash="dash"),
                                 name="neutral axis"))
    if show_labels:
        _add_point_labels(fig, outer, holes, bars, tendons, label_scale, label_min_gap)
    fig.update_layout(
        title=title, template="plotly_white", height=height,
        margin=dict(l=10, r=10, t=40, b=10),
        xaxis=dict(title="x (m)", zeroline=True),
        yaxis=dict(title="y (m)", scaleanchor="x", scaleratio=1, zeroline=True),
        showlegend=bool(na_line) or bool(zones) or bool(bars) or bool(tendons),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, font=dict(size=10)),
    )
    return fig


def interaction_figure(mx, my, applied=None, title="M-M interaction"):
    """Biaxial moment capacity envelope, with an optional applied-load point.

    Drawn to match the section's orientation: ``Mx`` is bending *about* the
    x-axis (its stress varies with y), so it is the **vertical** axis here, and
    ``My`` (about the y-axis) is the **horizontal** axis. A section that is strong
    about x then gives a tall envelope, consistent with the section drawing,
    rather than a wide one. ``applied`` is given as ``(Mx, My)`` and placed
    accordingly.
    """
    fig = go.Figure()
    # My on the horizontal axis, Mx on the vertical -- see the note above.
    fig.add_trace(go.Scatter(x=my + my[:1], y=mx + mx[:1], mode="lines",
                             line=dict(color=ENVELOPE, width=2), name="capacity"))
    if applied is not None:
        a_mx, a_my = applied
        fig.add_trace(go.Scatter(x=[a_my], y=[a_mx], mode="markers",
                                 marker=dict(size=11, color=LOAD_POINT, symbol="x"),
                                 name="applied"))
    fig.update_layout(
        title=title, template="plotly_white", height=440,
        margin=dict(l=10, r=10, t=40, b=10),
        xaxis=dict(title="My - about the y-axis (kNm)", zeroline=True),
        yaxis=dict(title="Mx - about the x-axis (kNm)", scaleanchor="x",
                   scaleratio=1, zeroline=True),
        legend=dict(orientation="h", yanchor="bottom", y=1.0),
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
