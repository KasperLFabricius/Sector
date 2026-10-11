"""Additional geometric and numerical teaching figures for the user manual.

The plastic trace uses the independent arithmetic in manual_numerics. Slab
positions use the current template. The torsion partition is checked against
the production geometry validator. These figures do not change analysis.
"""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from manual_numerics import plastic_search_example, rectangular_plastic_trial
from sector.geometry import rectangles_partition_concrete
from sector.templates import unit_width_nominal_bar_row

BLUE = "#215B85"
RED = "#AD492F"
GREY = "#667786"
INK = "#263541"


def _finish(fig, height):
    fig.update_layout(
        template="plotly_white", width=920, height=height,
        font=dict(family="Arial", size=18, color=INK),
        margin=dict(l=75, r=35, t=70, b=65), showlegend=False,
        paper_bgcolor="white", plot_bgcolor="white",
    )
    fig.update_annotations(font_size=18)
    return fig


def _line(fig, x, y, row=1, col=1, color=BLUE, dash="solid", **kwargs):
    fig.add_trace(go.Scatter(
        x=x, y=y, mode="lines", line=dict(color=color, width=2.5, dash=dash),
        hoverinfo="skip", **kwargs,
    ), row=row, col=col)


def _note(fig, x, y, text, row=1, col=1, **kwargs):
    fig.add_annotation(x=x, y=y, text=text, showarrow=False,
                       row=row, col=col, **kwargs)


def fig_plastic_bisection():
    """Independent axial residual and the first six retained depth intervals."""
    example = plastic_search_example()
    trace = example["trace"][:6]
    accepted = example["accepted"]
    depths = np.linspace(0.6e-9, 0.6, 301)
    residuals = [rectangular_plastic_trial(float(c))["axial"] for c in depths]
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.53, 0.47], vertical_spacing=0.16,
                        subplot_titles=("Axial equilibrium: P = 0 kN",
                                        "Depth interval before each trial"))
    _line(fig, depths * 1000, residuals)
    _line(fig, [0, 600], [0, 0], color=GREY, dash="dash")
    fig.add_trace(go.Scatter(
        x=[r[3]["depth"] * 1000 for r in trace],
        y=[r[3]["axial"] for r in trace], mode="markers",
        marker=dict(color=RED, size=8, symbol="diamond"),
    ), row=1, col=1)
    fig.add_annotation(
        x=accepted["depth"] * 1000, y=0,
        text=f"Accepted c = {accepted['depth'] * 1000:.3f} mm",
        showarrow=True, ax=90, ay=-125, arrowhead=2, arrowcolor=INK,
        bgcolor="white", row=1, col=1,
    )
    for iteration, low, high, trial in trace:
        _line(fig, [low * 1000, high * 1000], [iteration] * 2, row=2)
        fig.add_trace(go.Scatter(
            x=[low * 1000, high * 1000], y=[iteration] * 2,
            mode="markers", marker=dict(color=BLUE, symbol="line-ns", size=13,
                                        line=dict(width=2, color=BLUE)),
        ), row=2, col=1)
        fig.add_trace(go.Scatter(
            x=[trial["depth"] * 1000], y=[iteration], mode="markers",
            marker=dict(color=RED, size=9, symbol="diamond"),
        ), row=2, col=1)
    _line(fig, [accepted["depth"] * 1000] * 2, [0.5, 6.5], row=2,
          color=GREY, dash="dot")
    fig.update_yaxes(title_text="\u03a3F \u2212 P (kN)", row=1, col=1)
    fig.update_yaxes(title_text="Trial", tickvals=list(range(1, 7)),
                     range=[6.6, 0.4], row=2, col=1)
    fig.update_xaxes(range=[0, 610], row=1, col=1)
    fig.update_xaxes(title_text="Compression depth c (mm)", range=[0, 610], row=2, col=1)
    _note(fig, 430, 5.5, "\u25c6 Evaluated midpoint", row=2)
    return _finish(fig, 670)


def fig_directional_shear_faces():
    """Equal-scale section views for positive adjusted bending moments."""
    fig = make_subplots(rows=1, cols=2, horizontal_spacing=0.12,
                        subplot_titles=("V<sub>y</sub> with adjusted M<sub>x</sub> > 0",
                                        "V<sub>x</sub> with adjusted M<sub>y</sub> > 0"))
    bars = [(-100, -250), (100, -250), (100, 250), (-100, 250)]
    for col in (1, 2):
        _line(fig, [-150, 150, 150, -150, -150], [-300, -300, 300, 300, -300], col=col)
        selected = [y < 0 if col == 1 else x < 0 for x, y in bars]
        fig.add_trace(go.Scatter(
            x=[p[0] for p in bars], y=[p[1] for p in bars], mode="markers",
            marker=dict(size=12, color=[RED if s else GREY for s in selected],
                        symbol=["circle" if s else "circle-open" for s in selected],
                        line=dict(width=2)),
        ), row=1, col=col)
        fig.update_xaxes(title_text="x (mm)", range=[-255, 255], tickvals=[-150, 0, 150],
                         row=1, col=col)
        fig.update_yaxes(title_text="y (mm)" if col == 1 else None,
                         range=[-420, 410], tickvals=[-300, 0, 300],
                         scaleanchor="x" if col == 1 else "x2", scaleratio=1,
                         row=1, col=col)
    _line(fig, [-150, 150], [300, 300], color=INK)
    _note(fig, 0, 360, "Compression edge")
    _line(fig, [-100, 100], [-250, -250], color=RED, dash="dot")
    _note(fig, 0, -365, "Bottom bars: A<sub>sl,y</sub>", font=dict(color=RED))
    _line(fig, [-200, -200], [-250, 300], color=GREY)
    for y in (-250, 300):
        _line(fig, [-210, -175], [y, y], color=GREY)
    _note(fig, -225, 25, "d<sub>y</sub> = 550", textangle=-90)
    _note(fig, 0, 100, "b<sub>w,y</sub> = 300 mm")
    fig.add_annotation(x=0, y=-80, ax=0, ay=70, text="V<sub>y</sub>",
                       showarrow=True, arrowhead=2, arrowwidth=2, row=1, col=1)
    _line(fig, [150, 150], [-300, 300], col=2, color=INK)
    _note(fig, 207, 0, "Compression edge", col=2, textangle=-90)
    _line(fig, [-100, -100], [-250, 250], col=2, color=RED, dash="dot")
    _note(fig, -208, 0, "Left bars: A<sub>sl,x</sub>", col=2, textangle=-90,
          font=dict(color=RED))
    _line(fig, [-100, 150], [-350, -350], col=2, color=GREY)
    for x in (-100, 150):
        _line(fig, [x, x], [-365, -325], col=2, color=GREY)
    _note(fig, 25, -390, "d<sub>x</sub> = 250 mm", col=2)
    _note(fig, 0, 355, "b<sub>w,x</sub> = 600 mm", col=2)
    fig.add_annotation(x=80, y=0, ax=-75, ay=0, text="V<sub>x</sub>",
                       showarrow=True, arrowhead=2, arrowwidth=2, row=1, col=2)
    return _finish(fig, 690)


def slab_figure_data():
    """Nominal axes and tributary factors for the displayed slab series."""
    primary = unit_width_nominal_bar_row(0.0, 1.0, 0.2, 20.0)
    interleaved = unit_width_nominal_bar_row(0.0, 1.0, 0.2, 16.0, staggered=True)
    return primary, interleaved


def fig_slab_spacing_cover():
    """Nominal strip axes and two equal-scale cover details."""
    primary, interleaved = slab_figure_data()
    fig = make_subplots(
        rows=2, cols=2, specs=[[{"colspan": 2}, None], [{}, {}]],
        row_heights=[0.48, 0.52], vertical_spacing=0.24, horizontal_spacing=0.13,
        subplot_titles=("1 m strip: series shown separately",
                        "Edge cover: 20 mm", "Center cover: 30 mm"),
    )
    for series, y, color in ((primary, 1, BLUE), (interleaved, 0, RED)):
        xs = [p[0] * 1000 for p in series]
        _line(fig, [-500, 500], [y, y], color=GREY)
        fig.add_trace(go.Scatter(x=xs, y=[y] * len(xs), mode="markers",
                                marker=dict(size=12, color=color)), row=1, col=1)
    for x in (-500, 500):
        _line(fig, [x, x], [-0.45, 1.55], color=GREY, dash="dash")
        _note(fig, x, -0.48, "\xbd area", font=dict(color=RED))
        _note(fig, x, 1.76, "Strip cut")
    for x in (-400, -200):
        _line(fig, [x, x], [1.12, 1.42], color=BLUE)
    _line(fig, [-400, -200], [1.35, 1.35])
    _note(fig, -300, 1.60, "s = 200 mm")
    for x in (-400, -200, 0, 200, 400):
        _line(fig, [x, x], [-0.14, 0.14], color=RED, dash="dot")
    _note(fig, 185, 1.60, "Interleaved shift: 100 mm")
    fig.update_xaxes(title_text="x (mm)", range=[-560, 560],
                     tickvals=[-500, -400, -200, 0, 200, 400, 500], row=1, col=1)
    fig.update_yaxes(range=[-0.75, 1.9], tickvals=[0, 1],
                     ticktext=["16 mm bars", "20 mm bars"], showgrid=False, zeroline=False, row=1, col=1)
    for col in (1, 2):
        _line(fig, [-25, 110], [0, 0], row=2, col=col, color=INK)
        for x, diameter in ((10, 20), (80, 16)):
            centre = 20 + diameter / 2 if col == 1 else 30
            axis = "x2" if col == 1 else "x3"
            yaxis = "y2" if col == 1 else "y3"
            fig.add_shape(type="circle", x0=x-diameter/2, x1=x+diameter/2,
                          y0=centre-diameter/2, y1=centre+diameter/2,
                          xref=axis, yref=yaxis, line=dict(color=BLUE, width=2),
                          fillcolor="#E5EFF5")
            _note(fig, x, 56, f"{diameter} mm bar", row=2, col=col)
            limit = 20 if col == 1 else centre
            _line(fig, [x, x], [0, limit], row=2, col=col, color=GREY, dash="dot")
            fig.add_trace(go.Scatter(x=[x], y=[centre], mode="markers",
                                    marker=dict(size=4, color=INK)), row=2, col=col)
        if col == 1:
            _note(fig, 45, 85, "Centers: 30 and 28 mm", row=2, col=col)
        else:
            _line(fig, [-10, 100], [30, 30], row=2, col=col, color=GREY, dash="dash")
            _note(fig, 45, 85, "Clear cover: 20 and 22 mm", row=2, col=col)
        _note(fig, 45, -14, "Concrete face", row=2, col=col)
        fig.update_xaxes(range=[-30, 120], visible=False, row=2, col=col)
        fig.update_yaxes(range=[105, -25], visible=False,
                         scaleanchor="x2" if col == 1 else "x3", scaleratio=1,
                         row=2, col=col)
    return _finish(fig, 780).update_layout(margin=dict(l=120, r=35, t=70, b=65))


def torsion_partition_data():
    """Validated T-section in mm: non-overlapping web and flange rectangles."""
    outer = [(-100, -300), (100, -300), (100, 100), (300, 100),
             (300, 300), (-300, 300), (-300, 100), (-100, 100)]
    rectangles = [(0, -100, 200, 400), (0, 200, 600, 200)]
    valid, reason = rectangles_partition_concrete(outer, [], rectangles)
    if not valid:
        raise ValueError(f"The manual torsion partition is invalid: {reason}")
    return outer, rectangles


def fig_torsion_partition():
    """An exact geometric partition and its positioned rectangle inputs."""
    outer, rectangles = torsion_partition_data()
    fig = make_subplots(rows=1, cols=2, column_widths=[0.58, 0.42],
                        specs=[[{"type": "xy"}, {"type": "table"}]],
                        horizontal_spacing=0.07,
                        subplot_titles=("Full T-section partition", "Rectangle inputs (mm)"))
    for index, (cx, cy, b, h) in enumerate(rectangles, 1):
        xs = [cx-b/2, cx+b/2, cx+b/2, cx-b/2, cx-b/2]
        ys = [cy-h/2, cy-h/2, cy+h/2, cy+h/2, cy-h/2]
        _line(fig, xs, ys, color=BLUE if index == 1 else GREY, fill="toself",
              fillcolor="#E5EFF5" if index == 1 else "#F1E9DE")
        fig.add_trace(go.Scatter(x=[cx], y=[cy], mode="markers",
                                marker=dict(symbol="cross", size=10, color=INK)), row=1, col=1)
        _note(fig, cx, cy+55, f"Rectangle {index}")
    closed = outer + outer[:1]
    _line(fig, [p[0] for p in closed], [p[1] for p in closed], color=INK)
    _line(fig, [-100, 100], [100, 100], color=GREY, dash="dash")
    fig.add_trace(go.Table(
        columnwidth=[1.1, 1, 1],
        header=dict(values=["Input", "Web 1", "Flange 2"], fill_color="#E5EFF5",
                    align="center", font=dict(size=17, color=INK), height=40),
        cells=dict(values=[["x<sub>i</sub>", "y<sub>i</sub>", "b<sub>i</sub>", "h<sub>i</sub>"],
                           [0, -100, 200, 400], [0, 200, 600, 200]],
                   fill_color="white", align="center", font=dict(size=18, color=INK), height=40),
    ), row=1, col=2)
    fig.add_annotation(x=0.79, y=0.35, xref="paper", yref="paper", showarrow=False,
                       text="Web 1 is paired with shear.<br><br>Total area: 200,000 mm\xb2",
                       align="left")
    fig.update_xaxes(title_text="x (mm)", range=[-340, 340], tickvals=[-300, 0, 300])
    fig.update_yaxes(title_text="y (mm)", range=[-340, 340], tickvals=[-300, 0, 100, 300],
                     scaleanchor="x", scaleratio=1)
    return _finish(fig, 555)
