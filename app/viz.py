"""Plotly figures for the Sector UI: the section drawing and the N-M diagram."""

from __future__ import annotations

import math

import plotly.graph_objects as go

CONCRETE_FILL = "rgba(120,130,140,0.18)"
CONCRETE_LINE = "#5b6770"
BAR_TENSION = "#1d9e75"
BAR_COMPRESSION = "#c0392b"
BAR_NEUTRAL = "#534ab7"
NA_LINE = "#e08a1e"
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

# Map a material's ASCII marker key to its display symbol (subscripts via <sub>).
_MARKER_LABELS = {
    "fcd": "f<sub>cd</sub>",
    "fck": "f<sub>ck</sub>",
    "fyd": "f<sub>yd</sub>",
    "fud": "f<sub>ud</sub>",
    "f1": "f<sub>1</sub>",
    "f2": "f<sub>2</sub>",
    "eps_c2": _EPS + "<sub>c2</sub>",
    "eps_cu2": _EPS + "<sub>cu2</sub>",
    "eps_yd": _EPS + "<sub>yd</sub>",
    "eps_ud": _EPS + "<sub>ud</sub>",
    "eps_y1": _EPS + "<sub>y1</sub>",
    "eps_y2": _EPS + "<sub>y2</sub>",
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

    # Strain symbols on the strain (x) axis.
    x_groups = _grouped(pts, "x")
    x_span = (eps_max - eps_min) * 1000.0
    x_lab = _spread([v for v, _ in x_groups], x_span * 0.11)
    for (x0, keys), xl in zip(x_groups, x_lab):
        fig.add_vline(x=x0, line_width=0.8, line_dash="dot", line_color=GUIDE_LINE)
        fig.add_annotation(x=xl, xref="x", y=0.0, yref="paper", yshift=-7,
                           yanchor="top", showarrow=False, text=_merge_labels(keys),
                           font=dict(size=12, color=DESIGN_LINE))

    # Stress symbols on the stress (y) axis.
    y_groups = _grouped(pts, "y")
    y_span = (ymax - ymin) or 1.0
    y_lab = _spread([v for v, _ in y_groups], y_span * 0.08)
    for (y0, keys), yl in zip(y_groups, y_lab):
        fig.add_hline(y=y0, line_width=0.8, line_dash="dot", line_color=GUIDE_LINE)
        fig.add_annotation(x=1.0, xref="paper", xshift=6, y=yl, yref="y",
                           xanchor="left", showarrow=False, text=_merge_labels(keys),
                           font=dict(size=12, color=DESIGN_LINE))


def _curve_figure(material, eps_min, eps_max, title, n=240):
    """Stress-strain diagram of a material law over a strain range (tension +).

    Plots the design curve and, lighter, the characteristic curve, with the
    points of interest dotted and labelled at the axes. The strain axis is in
    per-mille so compression (negative) and tension (positive) are both visible;
    stress in MPa.
    """
    eps = _linspace(eps_min, eps_max, n)
    x = [e * 1000.0 for e in eps]  # per-mille
    design = [material.stress(e, design=True) for e in eps]
    char = [material.stress(e, design=False) for e in eps]

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=char, mode="lines", name="characteristic",
                             line=dict(color=CHAR_LINE, width=1.5, dash="dot")))
    fig.add_trace(go.Scatter(x=x, y=design, mode="lines", name="design",
                             line=dict(color=DESIGN_LINE, width=2.5)))
    _apply_markers(fig, material.diagram_markers(design=True), eps_min, eps_max,
                   min(design + char), max(design + char))
    fig.update_layout(
        title=dict(text=title, font=dict(size=13)),
        template="plotly_white", height=260,
        margin=dict(l=58, r=58, t=30, b=46),
        xaxis=dict(title="Strain " + _EPS + " [" + _PERMILLE + "]",
                   zeroline=True, zerolinecolor="#c8ccd0"),
        yaxis=dict(title="Stress " + _SIGMA + " [MPa]",
                   zeroline=True, zerolinecolor="#c8ccd0"),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0.0,
                    font=dict(size=10)),
    )
    return fig


def concrete_curve_figure(concrete, title="Concrete"):
    """Stress-strain diagram for a concrete law (compression is negative)."""
    # Slightly past the ultimate strain on the compression side, a little tension.
    return _curve_figure(concrete, -0.0042, 0.0006, title)


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
    xs = [p[0] for p in ring] + [ring[0][0]]
    ys = [p[1] for p in ring] + [ring[0][1]]
    return xs, ys


def section_figure(outer, holes=None, bars=None, bar_colors=None,
                   na_line=None, title="Section"):
    """Draw the section: concrete outline, holes, reinforcement and neutral axis.

    ``outer`` / ``holes`` are vertex lists (m). ``bars`` is a list of (x, y).
    ``bar_colors`` (optional) one colour per bar. ``na_line`` is
    ``(x0, y0, x1, y1)`` for the neutral axis.
    """
    fig = go.Figure()
    xs, ys = _ring_xy(outer)
    fig.add_trace(go.Scatter(x=xs, y=ys, fill="toself", mode="lines",
                             fillcolor=CONCRETE_FILL, line=dict(color=CONCRETE_LINE),
                             hoverinfo="skip", showlegend=False))
    for hole in holes or []:
        hx, hy = _ring_xy(hole)
        fig.add_trace(go.Scatter(x=hx, y=hy, fill="toself", mode="lines",
                                 fillcolor="white", line=dict(color=CONCRETE_LINE, dash="dot"),
                                 hoverinfo="skip", showlegend=False))
    if bars:
        bx = [b[0] for b in bars]
        by = [b[1] for b in bars]
        colors = bar_colors or [BAR_NEUTRAL] * len(bars)
        fig.add_trace(go.Scatter(x=bx, y=by, mode="markers",
                                 marker=dict(size=9, color=colors,
                                             line=dict(color="white", width=1)),
                                 hoverinfo="skip", showlegend=False))
    if na_line:
        x0, y0, x1, y1 = na_line
        fig.add_trace(go.Scatter(x=[x0, x1], y=[y0, y1], mode="lines",
                                 line=dict(color=NA_LINE, width=2, dash="dash"),
                                 name="neutral axis"))
    fig.update_layout(
        title=title, template="plotly_white", height=440,
        margin=dict(l=10, r=10, t=40, b=10),
        xaxis=dict(title="x (m)", zeroline=True),
        yaxis=dict(title="y (m)", scaleanchor="x", scaleratio=1, zeroline=True),
        showlegend=bool(na_line),
    )
    return fig


def interaction_figure(mx, my, applied=None, title="M-M interaction"):
    """Biaxial Mx-My capacity envelope, with an optional applied-load point."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=mx + mx[:1], y=my + my[:1], mode="lines",
                             line=dict(color=ENVELOPE, width=2), name="capacity"))
    if applied is not None:
        ax, ay = applied
        fig.add_trace(go.Scatter(x=[ax], y=[ay], mode="markers",
                                 marker=dict(size=11, color=LOAD_POINT, symbol="x"),
                                 name="applied"))
    fig.update_layout(
        title=title, template="plotly_white", height=440,
        margin=dict(l=10, r=10, t=40, b=10),
        xaxis=dict(title="Mx (kNm)", zeroline=True),
        yaxis=dict(title="My (kNm)", scaleanchor="x", scaleratio=1, zeroline=True),
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
