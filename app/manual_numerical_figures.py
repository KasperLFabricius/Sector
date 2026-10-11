"""Reproducible diagrams for polygon clipping and duration calculations."""

from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots


def clipping_figure_data():
    """Illustrative millimeter geometry and reference stress in MPa."""
    from app.manual_numerics import clip_polygon

    outer = [(0., 0.), (400., 0.), (400., 600.), (0., 600.)]
    void = [(140., 200.), (260., 200.), (260., 400.), (140., 400.)]
    plane = (0.24, 0.0002, -0.001)
    return dict(outer=outer, void=void, plane=plane,
                retained=clip_polygon(outer, plane),
                removed_void=clip_polygon(void, plane),
                qa=0.32, qb=-0.28, fraction=0.32 / 0.60)


def fig_polygon_clipping():
    """Connect the clipped net area to one exact edge intersection."""
    data = clipping_figure_data()
    fig = make_subplots(rows=1, cols=2, horizontal_spacing=0.18,
                        subplot_titles=("1. Keep the compressed region", "2. Locate an edge intersection"))
    for ring, fill, color, width, dash in (
        (data["outer"], None, "#73818B", 2, "solid"),
        (data["retained"], "#E8D5CB", "#AD492F", 2, "solid"),
        (data["void"], "white", "#73818B", 2, "dot"),
        (data["removed_void"], "white", "#263541", 2, "solid"),
    ):
        closed = ring + ring[:1]
        fig.add_trace(go.Scatter(x=[p[0] for p in closed], y=[p[1] for p in closed],
            mode="lines", fill="toself" if fill else None, fillcolor=fill,
            line=dict(color=color, width=width, dash=dash)), row=1, col=1)
    fig.add_trace(go.Scatter(x=[0, 400], y=[240, 320], mode="lines",
                            line=dict(color="#263541", width=2, dash="dash")), row=1, col=1)
    fig.add_trace(go.Scatter(x=[400, 400, 400], y=[0, 320, 600], mode="markers+text",
        text=["a", "c", "b"], textposition=["bottom left", "top right", "top left"],
        marker=dict(color="#263541", size=9)), row=1, col=1)
    for x, y, label in [(130, 510, "Retained concrete"),
                         (120, 125, "Concrete stress = 0"), (68, 277, "q = 0")]:
        fig.add_annotation(x=x, y=y, text=label, showarrow=False, row=1, col=1)
    fig.add_annotation(x=210, y=350, ax=85, ay=-100, text="Subtract<br>clipped void",
                       showarrow=True, arrowhead=2, arrowcolor="#263541", row=1, col=1)
    t = data["fraction"]
    fig.add_trace(go.Scatter(x=[0, 1], y=[data["qa"], data["qb"]], mode="lines+markers",
        line=dict(color="#AD492F", width=3), marker=dict(size=9)), row=1, col=2)
    fig.add_trace(go.Scatter(x=[0, 1], y=[0, 0], mode="lines",
        line=dict(color="#73818B", width=1)), row=1, col=2)
    fig.add_trace(go.Scatter(x=[t, t], y=[-0.36, 0], mode="lines",
        line=dict(color="#263541", width=1, dash="dash")), row=1, col=2)
    fig.add_trace(go.Scatter(x=[t], y=[0], mode="markers",
        marker=dict(size=10, color="#263541")), row=1, col=2)
    for x, y, text in [(0.17, 0.34, "q<sub>a</sub> = 0.32 MPa"),
                        (.78, -.31, "q<sub>b</sub> = -0.28 MPa"),
                        (.61, .105, "c: t = 8/15<br>(400, 320) mm")]:
        fig.add_annotation(x=x, y=y, text=text, showarrow=False, row=1, col=2)
    fig.update_xaxes(title_text="x (mm)", range=[-40, 450], row=1, col=1)
    fig.update_yaxes(title_text="y (mm)", range=[-50, 650], scaleanchor="x", scaleratio=1, row=1, col=1)
    fig.update_xaxes(title_text="Fraction along edge a to b", range=[-.06, 1.06],
                     tickvals=[0, t, 1], ticktext=["0", "8/15", "1"], row=1, col=2)
    fig.update_yaxes(title_text="Reference stress q (MPa)", range=[-.36, .40], row=1, col=2)
    fig.update_layout(template="plotly_white", width=1100, height=670, showlegend=False,
        font=dict(family="Arial", size=18, color="#263541"),
        margin=dict(l=75, r=35, t=70, b=85))
    return fig


def fig_duration_sequence():
    """Order of operations for passive and locked reinforcement stresses."""
    fig = go.Figure()
    ink = "#263541"

    def box(x0, y0, x1, y1, text, fill="#F3F5F6"):
        fig.add_shape(type="rect", x0=x0, y0=y0, x1=x1, y1=y1,
                      line=dict(color="#A1ABB2", width=1), fillcolor=fill)
        fig.add_annotation(x=(x0+x1)/2, y=(y0+y1)/2, text=text,
                           showarrow=False, align="center", font=dict(size=20))

    def arrow(x0, y0, x1, y1):
        fig.add_annotation(x=x1, y=y1, ax=x0, ay=y0, xref="x", yref="y", axref="x", ayref="y",
                           text="", showarrow=True, arrowhead=2, arrowsize=1, arrowwidth=1.5,
                           arrowcolor=ink)

    box(0, 8.2, 6.4, 9.6, "<b>1. Sustained equilibrium</b><br>Target: L - P<br>Use sustained ratios n<sub>l</sub><br>Output: passive stress s<sub>l</sub>")
    box(0, 6.2, 6.4, 7.6, "<b>2. Retain passive stress</b><br>s<sub>r</sub> = s<sub>l</sub>(1 - n<sub>s</sub>/n<sub>l</sub>)<br>For each bar and tendon")
    box(0, 4.2, 6.4, 5.6, "<b>3. Sum retained resultants</b><br>R = \u03a3 s<sub>r</sub>A(1, y, x)<br>Use each element's area and position")
    box(0, 2.2, 6.4, 3.6, "<b>4. Instantaneous equilibrium</b><br>Target: C - P - R<br>Use instantaneous ratios n<sub>s</sub><br>Output: passive stress s<sub>i</sub> (RST1)")
    for high, low in ((8.2, 7.6), (6.2, 5.6), (4.2, 3.6)):
        arrow(3.2, high, 3.2, low)
    box(7.1, 8.2, 10, 9.6, "<b>LONG</b><br>s<sub>l</sub> + p", "#E8D5CB")
    box(7.1, 2.2, 10, 3.6, "<b>TOTAL</b><br>s<sub>r</sub> + s<sub>i</sub> + p", "#E8D5CB")
    arrow(6.4, 8.9, 7.1, 8.9)
    arrow(6.4, 2.9, 7.1, 2.9)
    box(7.1, .25, 10, 1.55, "<b>DIF</b><br>TOTAL - LONG")
    arrow(8.55, 2.2, 8.55, 1.55)
    fig.add_shape(type="path", path="M 10,8.9 L 10.45,8.9 L 10.45,0.9",
                  line=dict(color=ink, width=1.5))
    arrow(10.45, .9, 10, .9)
    fig.add_annotation(x=0, y=-1.0, xanchor="left", text=
        "L: sustained actions. C: combined actions. Components: (N, -M<sub>x</sub>, -M<sub>y</sub>).<br>"
        "N is tension-positive. P contains the locked-prestress resultants in the same order.<br>"
        "p is the locked stress in one element. For ordinary bars, p = 0.<br>"
        "The same locked stress cancels in DIF.",
        showarrow=False, align="left", font=dict(size=18))
    fig.update_xaxes(visible=False, range=[-.15, 10.6])
    fig.update_yaxes(visible=False, range=[-1.9, 9.85])
    fig.update_layout(template="plotly_white", width=1100, height=1050, showlegend=False,
        font=dict(family="Arial", size=20, color=ink), margin=dict(l=30, r=30, t=20, b=20))
    return fig
