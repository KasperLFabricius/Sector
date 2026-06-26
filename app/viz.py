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
