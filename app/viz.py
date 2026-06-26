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
    "eps_c2": _EPS + "<sub>c2</sub>",
    "eps_cu2": _EPS + "<sub>cu2</sub>",
    "eps_yd": _EPS + "<sub>yd</sub>",
    "fyd": "f<sub>yd</sub>",
    "eps_ud": _EPS + "<sub>ud</sub>",
    "eps_y1": _EPS + "<sub>y1</sub>",
    "f1": "f<sub>1</sub>",
    "f2": "f<sub>2</sub>",
}


def _linspace(a, b, n):
    if n < 2:
        return [a]
    step = (b - a) / (n - 1)
    return [a + step * i for i in range(n)]


def _apply_markers(fig, markers):
    """Draw labelled guide lines at a material's points of interest.

    ``markers`` are ``(kind, value, key)`` from ``material.diagram_markers``:
    a ``"strain"`` marker is a vertical guide (its value scaled to per-mille),
    a ``"stress"`` marker a horizontal one. Each carries its symbol as a label.
    """
    for kind, value, key in markers:
        label = _MARKER_LABELS.get(key, key)
        if kind == "strain":
            fig.add_vline(x=value * 1000.0, line_width=1, line_dash="dot",
                          line_color=GUIDE_LINE, annotation_text=label,
                          annotation_position="top",
                          annotation_font=dict(size=12, color=DESIGN_LINE))
        else:
            fig.add_hline(y=value, line_width=1, line_dash="dot",
                          line_color=GUIDE_LINE, annotation_text=label,
                          annotation_position="right",
                          annotation_font=dict(size=12, color=DESIGN_LINE))


def _curve_figure(material, eps_min, eps_max, title, n=240):
    """Stress-strain diagram of a material law over a strain range (tension +).

    Plots the design curve and, lighter, the characteristic curve, with labelled
    guide lines at the points of interest. The strain axis is in per-mille so
    compression (negative) and tension (positive) are both visible; stress in MPa.
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
    _apply_markers(fig, material.diagram_markers(design=True))
    fig.update_layout(
        title=dict(text=title, font=dict(size=13)),
        template="plotly_white", height=240,
        margin=dict(l=10, r=10, t=30, b=10),
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
    """Stress-strain diagram for a reinforcement law (tension and compression)."""
    top = min(eps_max, steel.eut) if steel.eut > 0 else eps_max
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
