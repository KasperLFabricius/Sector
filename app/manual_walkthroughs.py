"""Worked explanations and reproducible figures for the Sector manual.

The examples call the existing numerical core. The rectangular elastic check
is independent arithmetic in mm, N and MPa. No production solver is changed.
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from sector.elastic import solve_elastic, solve_elastic_combined
from sector.plastic import plastic_capacity_at_angle

BLUE = "#215B85"
RED = "#AD492F"
GREY = "#667786"
PALE = "#E5EFF5"


@lru_cache(maxsize=1)
def beam_example():
    """Return native example states plus an independent rectangular check."""
    from manual import _section_of, example_beam

    ex = example_beam()
    section = _section_of(ex)
    elastic = solve_elastic(section, 0, 150, 0, 6)
    plastic = plastic_capacity_at_angle(section, ex["concrete"], ex["steel"], 0, 90)
    combined = solve_elastic_combined(section, 0, 100, 0, 18, 0, 50, 0, 6)
    b, d, a, n = 300.0, 550.0, 50.0, 6.0
    bottom = 3 * math.pi * 25**2 / 4
    top = 2 * math.pi * 16**2 / 4
    linear = (n - 1) * top + n * bottom
    constant = -(n - 1) * top * a - n * bottom * d
    x = (-linear + math.sqrt(linear**2 - 2 * b * constant)) / b
    inertia = b * x**3 / 3 + (n - 1) * top * (x - a) ** 2 + n * bottom * (d - x) ** 2
    hand = {
        "x": x,
        "inertia": inertia,
        "bottom_area": bottom,
        "top_area": top,
        "bottom_stress": n * 150e6 * (d - x) / inertia,
        "top_stress": -n * 150e6 * (x - a) / inertia,
        "concrete_stress": 150e6 * x / inertia,
    }
    refinement = tuple(
        (
            bands,
            plastic_capacity_at_angle(
                section, ex["concrete"], ex["steel"], 0, 90, n_bands=bands
            ).Mx,
        )
        for bands in (20, 40, 80, 160)
    )
    # Reconstruct every midpoint band for this rectangle in the core's units.
    # Each entry is (area m2, centroid y m, compression stress MPa, force kN, Mx kNm).
    low = plastic.neutral_axis_offset
    peak = low + ex["concrete"].eps_c2 / plastic.curvature
    high = min(peak, 0.3)
    band_rows = []
    for index in range(80):
        ya = low + index * (high - low) / 80
        yb = low + (index + 1) * (high - low) / 80
        yc = (ya + yb) / 2
        stress = -ex["concrete"].stress(-plastic.curvature * (yc - low), design=True)
        area = 0.3 * (yb - ya)
        force = stress * area * 1000
        band_rows.append((area, yc, stress, force, force * yc))
    plateau_area = 0.3 * max(0.3 - peak, 0)
    plateau_y = (peak + 0.3) / 2
    plateau_force = plateau_area * ex["concrete"].fcd * 1000
    plateau = (
        plateau_area,
        plateau_y,
        ex["concrete"].fcd,
        plateau_force,
        plateau_force * plateau_y,
    )
    return {
        "ex": ex,
        "section": section,
        "elastic": elastic,
        "plastic": plastic,
        "combined": combined,
        "hand": hand,
        "refinement": refinement,
        "bands": tuple(band_rows),
        "plateau": plateau,
    }


def _finish(fig, height=440):
    fig.update_layout(
        template="plotly_white",
        width=920,
        height=height,
        font={"family": "Arial", "size": 15, "color": "#263541"},
        margin={"l": 65, "r": 35, "t": 65, "b": 60},
        showlegend=False,
        paper_bgcolor="white",
        plot_bgcolor="white",
    )
    fig.update_annotations(font_size=16)
    return fig


def _line(fig, x, y, *, row=1, col=1, color=BLUE, dash="solid", name="", **kwargs):
    fig.add_trace(
        go.Scatter(
            x=x,
            y=y,
            mode="lines",
            name=name,
            line={"color": color, "width": 2.5, "dash": dash},
            **kwargs,
        ),
        row=row,
        col=col,
    )


def fig_discretization():
    fig = make_subplots(
        rows=1,
        cols=3,
        subplot_titles=(
            "Polygon boundary",
            "Plastic stress bands",
            "Sampled orientations",
        ),
    )
    angle = np.linspace(0, 2 * math.pi, 49)
    _line(fig, np.cos(angle), np.sin(angle), col=1)
    _line(fig, 0.45 * np.cos(angle), 0.45 * np.sin(angle), col=1)
    fig.add_trace(
        go.Scatter(
            x=0.73 * np.cos(angle[::4]),
            y=0.73 * np.sin(angle[::4]),
            mode="markers",
            marker={"size": 9, "color": RED},
        ),
        row=1,
        col=1,
    )
    _line(fig, [-1, 1, 1, -1, -1], [-1, -1, 1, 1, -1], col=2)
    for y in np.linspace(0.1, 0.8, 9):
        _line(fig, [-1, 1], [y, y], col=2, color=GREY)
    fig.add_annotation(
        x=0,
        y=-0.45,
        text="8 bands shown<br>80 used in calculation",
        showarrow=False,
        row=1,
        col=2,
    )
    for a in (0, 30, 60, 90, 120, 150):
        r = math.radians(a)
        _line(fig, [-math.cos(r), math.cos(r)], [-math.sin(r), math.sin(r)], col=3)
    for col in (1, 2, 3):
        fig.update_xaxes(range=[-1.3, 1.3], visible=False, row=1, col=col)
        fig.update_yaxes(range=[-1.3, 1.3], visible=False, row=1, col=col)
    return _finish(fig, 360)


def fig_elastic_fields():
    h = beam_example()["hand"]
    x = h["x"]
    fig = make_subplots(
        rows=1,
        cols=3,
        shared_yaxes=True,
        subplot_titles=("Section and neutral axis", "Concrete stress", "Steel stress"),
    )
    _line(fig, [-150, 150, 150, -150, -150], [0, 0, 600, 600, 0])
    _line(fig, [-150, 150], [x, x], dash="dash", color=GREY)
    fig.add_trace(
        go.Scatter(
            x=[-100, 100, -100, 0, 100],
            y=[50, 50, 550, 550, 550],
            mode="markers",
            marker={"size": [9, 9, 14, 14, 14], "color": RED},
        ),
        row=1,
        col=1,
    )
    _line(fig, [-h["concrete_stress"], 0, 0], [0, x, 600], col=2)
    _line(fig, [0, 0], [0, 600], col=3, color=GREY)
    for y, stress in [(50, h["top_stress"]), (550, h["bottom_stress"])]:
        _line(fig, [0, stress], [y, y], col=3, color=RED)
        fig.add_annotation(
            x=stress,
            y=y,
            text=f"{stress:+.1f}",
            showarrow=False,
            yshift=-20,
            row=1,
            col=3,
        )
    fig.update_yaxes(range=[625, -25], title_text="Depth from top (mm)", row=1, col=1)
    fig.update_xaxes(title_text="x (mm)", row=1, col=1)
    fig.update_xaxes(title_text="Stress (MPa)", range=[-16, 2], row=1, col=2)
    fig.update_xaxes(title_text="Stress (MPa)", range=[-90, 250], row=1, col=3)
    return _finish(fig, 510)


def fig_elastic_balance():
    v = beam_example()["hand"]
    depths = np.linspace(70, 230, 161)
    area_moment = (
        300 * depths**2 / 2
        + 5 * v["top_area"] * (depths - 50)
        - 6 * v["bottom_area"] * (550 - depths)
    )
    fig = make_subplots(rows=1, cols=1)
    _line(fig, depths, area_moment / 1e6)
    _line(fig, [70, 230], [0, 0], color=GREY)
    fig.add_trace(
        go.Scatter(
            x=[v["x"]], y=[0], mode="markers", marker={"size": 10, "color": RED}
        ),
        row=1,
        col=1,
    )
    fig.add_annotation(
        x=v["x"], y=0, text=f"Balanced at x = {v['x']:.3f} mm", ax=70, ay=-50
    )
    fig.update_xaxes(title_text="Trial compression depth x (mm)")
    fig.update_yaxes(
        title_text="Signed transformed first moment (10<sup>6</sup> mm<sup>3</sup>)"
    )
    return _finish(fig, 380)


def fig_duration_components():
    r = beam_example()["combined"]
    labels = ["LONG", "Retained", "RST1", "TOTAL", "DIF"]
    values = [
        r.bar_stress_long[0],
        r.bar_stress_reduced_long[0],
        r.bar_stress_rst1[0],
        r.bar_stress_total[0],
        r.bar_stress_dif[0],
    ]
    fig = go.Figure(
        go.Bar(
            x=labels,
            y=np.array(values) / 1000,
            text=[f"{v / 1000:.1f}" for v in values],
            textposition="outside",
            marker_color=[BLUE, GREY, GREY, BLUE, RED],
        )
    )
    fig.update_yaxes(title_text="Bottom-bar tensile stress (MPa)", rangemode="tozero")
    fig.update_layout(
        title="100 kNm sustained + 50 kNm additional; creep coefficient 2"
    )
    return _finish(fig, 390)


def fig_plastic_bands():
    v = beam_example()
    p = v["plastic"]
    depth = p.compression_depth * 1000
    levels = np.linspace(0, depth, 200)
    strains = p.curvature * (p.compression_depth - levels / 1000)
    stresses = [-v["ex"]["concrete"].stress(-e, design=True) for e in strains]
    fig = make_subplots(
        rows=1,
        cols=2,
        shared_yaxes=True,
        subplot_titles=("Compression zone", "Concrete stress magnitude"),
    )
    _line(fig, [-150, 150, 150, -150, -150], [0, 0, depth, depth, 0])
    peak_depth = (
        300 - (p.neutral_axis_offset + v["ex"]["concrete"].eps_c2 / p.curvature) * 1000
    )
    for y in np.linspace(peak_depth, depth, 9):
        _line(fig, [-150, 150], [y, y], color=GREY)
    fig.add_annotation(
        x=0,
        y=peak_depth / 2,
        text="Constant-stress plateau",
        showarrow=False,
        row=1,
        col=1,
    )
    fig.add_annotation(
        x=0,
        y=(peak_depth + depth) / 2,
        text="Rising region<br>8 groups of 10 bands",
        showarrow=False,
        row=1,
        col=1,
    )
    _line(fig, stresses, levels, col=2)
    _line(
        fig,
        [0, max(stresses)],
        [peak_depth, peak_depth],
        col=2,
        color=GREY,
        dash="dash",
    )
    fig.update_yaxes(
        range=[depth + 7, -7], title_text="Depth from top (mm)", row=1, col=1
    )
    fig.update_xaxes(title_text="x (mm)", row=1, col=1)
    fig.update_xaxes(title_text="Compression stress (MPa)", row=1, col=2)
    return _finish(fig, 430)


def fig_capacity_limits():
    fig = make_subplots(
        rows=1,
        cols=2,
        shared_yaxes=True,
        subplot_titles=("Concrete limit reached", "Steel limit reached first"),
    )
    # Illustrative compatible linear fields; these are explicitly not capacity examples.
    for col, strain in [(1, [-3.5, 0, 19.5]), (2, [-2.0, 0, 10.0])]:
        bottom = 600
        zero = bottom * abs(strain[0]) / (abs(strain[0]) + strain[2])
        _line(fig, [strain[0], 0, strain[2]], [0, zero, bottom], col=col)
        _line(fig, [0, 0], [0, 600], col=col, color=GREY, dash="dash")
        fig.add_annotation(
            x=strain[0],
            y=0,
            text=f"{strain[0]:.1f}",
            yshift=20,
            showarrow=False,
            row=1,
            col=col,
        )
        fig.add_annotation(
            x=strain[2],
            y=600,
            text=f"{strain[2]:.1f}",
            yshift=18,
            xshift=10,
            showarrow=False,
            row=1,
            col=col,
        )
        fig.update_xaxes(
            range=[-6, 23],
            title_text="Tension-positive strain (\u2030)",
            row=1,
            col=col,
        )
    fig.update_yaxes(
        range=[635, -35], title_text="Illustrative depth (mm)", row=1, col=1
    )
    return _finish(fig, 460)


def fig_envelope_ray():
    from sector.combined import radial_util
    from sector.plastic import solve_plastic

    v = beam_example()
    ex = v["ex"]
    pts = solve_plastic(v["section"], ex["concrete"], ex["steel"], 0, 0, 360, 15)
    mx, my = [p.Mx for p in pts], [p.My for p in pts]
    applied = (180.0, 30.0)
    util, _ = radial_util(mx, my, *applied)
    fig = go.Figure(
        go.Scatter(
            x=mx,
            y=my,
            mode="lines+markers",
            line_color=BLUE,
            marker={"size": 5, "color": BLUE},
            name="Solved points",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[0, applied[0] / util],
            y=[0, applied[1] / util],
            mode="lines",
            line={"color": RED, "width": 2},
            name="Demand ray",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[applied[0]],
            y=[applied[1]],
            mode="markers",
            marker={"size": 11, "color": RED},
            name="Applied moment",
        )
    )
    fig.add_annotation(
        x=applied[0],
        y=applied[1],
        text=f"Applied: (180, 30)<br>Utilization {util:.3f}",
        ax=-65,
        ay=-55,
    )
    fig.update_xaxes(title_text="Mx (kNm)", zeroline=True, zerolinecolor=GREY)
    fig.update_yaxes(title_text="My (kNm)", zeroline=True, zerolinecolor=GREY)
    return _finish(fig, 450)


def fig_crack_geometry():
    # Existing manual examples define these four effective heights.
    heights = [125, 125, 100, 175]
    fig = make_subplots(
        rows=1,
        cols=4,
        shared_yaxes=True,
        subplot_titles=("EN 2005", "DK fine", "DK coarse", "EN 2023"),
    )
    for col, height in enumerate(heights, 1):
        _line(fig, [-150, 150, 150, -150, -150], [0, 0, 600, 600, 0], col=col)
        fig.add_trace(
            go.Scatter(
                x=[-150, 150, 150, -150, -150],
                y=[600 - height, 600 - height, 600, 600, 600 - height],
                fill="toself",
                fillcolor=PALE,
                line_color=BLUE,
                mode="lines",
            ),
            row=1,
            col=col,
        )
        fig.add_trace(
            go.Scatter(
                x=[-100, 0, 100],
                y=[550] * 3,
                mode="markers",
                marker={"size": 9, "color": RED},
            ),
            row=1,
            col=col,
        )
        fig.add_annotation(
            x=0,
            y=600 - height - 30,
            text=f"h = {height} mm",
            showarrow=False,
            row=1,
            col=col,
        )
        fig.update_xaxes(range=[-190, 190], visible=False, row=1, col=col)
    fig.update_yaxes(range=[630, -30], title_text="Depth from top (mm)", row=1, col=1)
    return _finish(fig, 480)


def fig_shear_truss():
    fig = make_subplots(
        rows=1,
        cols=2,
        subplot_titles=("Truss force path (schematic)", "Competing shear resistances"),
    )
    _line(fig, [0, 3], [0, 0])
    _line(fig, [0, 3], [1, 1])
    for x in (0, 1, 2):
        _line(fig, [x, x + 1], [1, 0], color=BLUE)
        _line(fig, [x + 1, x + 1], [0, 1], color=RED)
    fig.add_annotation(
        x=1.5, y=1.25, text="Compression chord", showarrow=False, row=1, col=1
    )
    fig.add_annotation(
        x=1.5, y=-0.25, text="Tension chord", showarrow=False, row=1, col=1
    )
    fig.add_annotation(x=1.5, y=0.5, text="Concrete strut", ax=-30, ay=40, row=1, col=1)
    fig.add_annotation(x=2, y=0.7, text="Link", ax=35, ay=-10, row=1, col=1)
    q = np.linspace(1, 2.5, 100)
    links = 555.4 * q / 2.5
    crush = 667.5 * (2.5 + 1 / 2.5) / (q + 1 / q)
    _line(fig, q, links, col=2, color=RED)
    _line(fig, q, crush, col=2)
    fig.add_annotation(
        x=2.3, y=float(links[-1]) - 75, text="Links", showarrow=False, row=1, col=2
    )
    fig.add_annotation(
        x=1.5,
        y=float(crush[33]) + 60,
        text="Concrete struts",
        showarrow=False,
        row=1,
        col=2,
    )
    fig.update_xaxes(visible=False, range=[-0.3, 3.4], row=1, col=1)
    fig.update_yaxes(visible=False, range=[-0.5, 1.5], row=1, col=1)
    fig.update_xaxes(title_text="cot(theta)", row=1, col=2)
    fig.update_yaxes(title_text="Resistance (kN)", range=[0, 1100], row=1, col=2)
    return _finish(fig, 440)


def fig_torsion_tube():
    fig = make_subplots(rows=1, cols=1)
    _line(fig, [-150, 150, 150, -150, -150], [-300, -300, 300, 300, -300])
    _line(fig, [-100, 100, 100, -100, -100], [-250, -250, 250, 250, -250], dash="dash")
    fig.add_annotation(
        x=180,
        y=-180,
        text="A<sub>k</sub> = 100,000 mm<sup>2</sup><br>u<sub>k</sub> = 1,400 mm",
        xanchor="left",
        showarrow=False,
    )
    for x, y, ax, ay in [
        (60, 250, -60, 0),
        (100, -60, 0, -60),
        (-60, -250, 60, 0),
        (-100, 60, 0, 60),
    ]:
        fig.add_annotation(
            x=x, y=y, ax=ax, ay=ay, text="", arrowhead=2, arrowcolor=RED, arrowwidth=2
        )
    fig.add_annotation(x=125, y=100, text="tef / 2 = 50 mm", ax=135, ay=0)
    fig.add_annotation(x=0, y=250, text="Effective tube centerline", ax=0, ay=-65)
    fig.update_xaxes(title_text="x (mm)", range=[-260, 360], constrain="domain")
    fig.update_yaxes(
        title_text="y (mm)", range=[-350, 350], scaleanchor="x", scaleratio=1
    )
    return _finish(fig, 500)


def fig_combined_paths():
    fig = make_subplots(
        rows=1,
        cols=2,
        subplot_titles=("Longitudinal chord faces", "Shared closed stirrup"),
    )
    for col in (1, 2):
        _line(
            fig,
            [-1.35, 1.35, 1.35, -1.35, -1.35],
            [-1.6, -1.6, 1.6, 1.6, -1.6],
            col=col,
        )
        fig.update_xaxes(visible=False, range=[-2.5, 2.5], row=1, col=col)
        fig.update_yaxes(visible=False, range=[-2.4, 2.4], row=1, col=col)
    for x, y, text in [
        (0, 1.85, "Top"),
        (0, -1.85, "Bottom"),
        (-1.95, 0, "Left"),
        (1.95, 0, "Right"),
    ]:
        fig.add_annotation(x=x, y=y, text=text, showarrow=False, row=1, col=1)
    fig.add_annotation(
        x=0,
        y=0,
        text="Bending: tension face<br>Shear: chord demand<br>Torsion: all faces",
        showarrow=False,
        row=1,
        col=1,
    )
    _line(
        fig,
        [-1.1, 1.1, 1.1, -1.1, -1.1],
        [-1.3, -1.3, 1.3, 1.3, -1.3],
        col=2,
        color=RED,
    )
    fig.add_annotation(
        x=0,
        y=0,
        text="Shear demand<br>+<br>Torsion demand<br><br>Common strut angle",
        showarrow=False,
        row=1,
        col=2,
    )
    return _finish(fig, 440)


def fig_fatigue_actions():
    fig = make_subplots(rows=1, cols=1)
    time = np.arange(9)
    _line(fig, time, [100] * 9, color=GREY, dash="dash")
    _line(fig, time, [100, 150, 100, 150, 100, 150, 100, 150, 100])
    fig.add_annotation(x=4, y=100, text="Sustained/basic: 100 kNm", ax=0, ay=45)
    fig.add_annotation(x=5, y=150, text="Peak: 150 kNm", ax=0, ay=-30)
    fig.update_xaxes(title_text="Illustrative repeated cycles", showticklabels=False)
    fig.update_yaxes(title_text="Mx (kNm)", range=[70, 180])
    return _finish(fig, 340)


def _md(text):
    return ("md", text)


def _heading(text):
    return ("h2", text)


def _figure(factory, caption, alternative):
    return ("figure", factory, caption, alternative)


def _table(headers, rows):
    return ("table", headers, rows)


def common_blocks():
    return [
        _heading("From section geometry to equilibrium"),
        _md(
            "A plane cross-section represents the concrete outline, its voids, and the reinforcement at the chosen location. "
            "The supplied axial force and moments act about the section origin. Plane sections remain plane, so three coefficients define the strain field. "
            "Perfect bond makes each reinforcement element follow the section strain at its coordinates. A tendon also has its entered initial strain."
        ),
        _md(
            "For each trial strain field, the material laws give stresses. Concrete stresses act over an area. "
            "Each bar or tendon contributes its stress multiplied by its area. Their forces and moments must balance the supplied actions. "
            "For a uniaxial rectangle, a calculator can find this balance. A general biaxial section requires repeated trials or a spreadsheet solution."
        ),
        _figure(
            fig_discretization,
            "Three distinct approximations: polygon geometry, plastic stress bands, and capacity orientations. Geometry is schematic.",
            "An annular polygon with discrete reinforcement, a rectangle divided into illustrative stress bands, and several sampled line orientations distinguish the three numerical choices.",
        ),
        _md(
            "Concrete is represented by straight polygon edges. The circular builder uses 48 segments. Each bar and tendon is a discrete area at its coordinates. "
            "The elastic solver integrates the clipped polygon analytically. The plastic solver uses 80 midpoint stress bands in the rising concrete-law region. "
            "The plastic envelope also samples the chosen orientations. These three resolutions affect different parts of the calculation."
        ),
        _md(
            "Moments use the entered origin. For a shift from origin O to O' = (a, b), the reported moments become "
            "$M'_x=M_x+bN$ and $M'_y=M_y+aN$ with Sector's tension-positive axial force. "
            "Keep coordinates and force units consistent. A shift matters whenever the axial force is nonzero."
        ),
        _md(
            "The local coordinate $s=x\\cos\\varphi_{NA}+y\\sin\\varphi_{NA}$ increases towards the compressed face. "
            "The sweep angle identifies the strain-gradient normal from +x, equivalently the neutral-axis line from +y. "
            "The line direction has a 180-degree ambiguity; the compressed side resolves it. "
            "A positive $M_x$ compresses the upper face of the centered beam. A positive $M_y$ compresses its right face."
        ),
        _md(
            "Use mm, N, N mm and MPa together for the worked arithmetic. Convert kN to N by multiplying by 1000. "
            "Convert kNm to N mm by multiplying by 10^6. A curvature stated in 1/m is 1000 times its value in 1/mm. "
            "The material laws use dimensionless strain; multiply by 1000 to express strain in \u2030."
        ),
    ]


def elastic_blocks():
    v = beam_example()
    h = v["hand"]
    r = v["combined"]
    return [
        _heading("Reproduce the rectangular elastic example"),
        _md(
            "Use the existing 300 x 600 mm beam at $N=0$, $M_x=150$ kNm and $M_y=0$. "
            "Use Es = 200000 MPa and Ec = 33333.333333 MPa with zero creep to obtain modular ratio 6. "
            "Enter these elastic moduli for this teaching example. The bottom layer has three 25 mm bars at depth 550 mm. "
            "The top layer has two 16 mm bars at depth 50 mm. Measure the compression depth x downwards from the top face."
        ),
        _table(
            ["Input", "Value", "Meaning"],
            [
                ["b / h", "300 / 600 mm", "Section width / height"],
                ["d / a", "550 / 50 mm", "Bottom / top bar depth from top"],
                [
                    "As / As'",
                    f"{h['bottom_area']:.3f} / {h['top_area']:.3f} mm2",
                    "Bottom / top reinforcement area",
                ],
                ["n", "6", "Steel modulus divided by concrete modulus"],
                ["Mx", "150,000,000 N mm", "Positive bending about the section origin"],
            ],
        ),
        _figure(
            fig_elastic_fields,
            "Rectangular elastic example: matching geometry, concrete stress and reinforcement stresses. Tension is positive.",
            "The compression zone ends 149.251 mm below the top. Concrete has a triangular compression stress distribution; top steel is compressed and bottom steel is in tension.",
        ),
        _md(
            "1. **Find the neutral axis.** Zero axial force requires zero signed first moment of the transformed section about that axis. "
            "The compression block is triangular in stress. The top steel displaces concrete, so its added transformed area is $(n-1)A'_s$. "
            "The tension concrete carries zero stress, so the bottom steel contributes $nA_s$."
        ),
        _md(
            "Solve $bx^2/2+(n-1)A'_s(x-a)-nA_s(d-x)=0$. "
            f"The positive root is **x = {h['x']:.3f} mm**. Confirm that the top bars lie inside the compression zone."
        ),
        _figure(
            fig_elastic_balance,
            "The neutral-axis equation crosses zero at the balanced compression depth. The curve evaluates the equation at a range of trial depths.",
            "The signed transformed first moment changes from negative to positive and crosses zero at compression depth 149.251 mm.",
        ),
        _md(
            "2. **Calculate the transformed second moment.** Use "
            "$I_{tr}=bx^3/3+(n-1)A'_s(x-a)^2+nA_s(d-x)^2$. "
            f"The result is **{h['inertia']:.3f} mm4**."
        ),
        _md(
            "3. **Calculate stresses.** The concrete compression magnitude is $M_x x/I_{tr}$. "
            "The bottom steel stress is $nM_x(d-x)/I_{tr}$. The top steel stress is $-nM_x(x-a)/I_{tr}$. "
            "Use the full modular ratio for actual steel stress. The subtraction of displaced concrete affects the section stiffness."
        ),
        _table(
            ["Result", "Independent calculation", "Native calculation"],
            [
                [
                    "Compression depth",
                    f"{h['x']:.6f} mm",
                    f"{300 - v['elastic'].na_y_intercept * 1000:.6f} mm",
                ],
                [
                    "Bottom steel stress",
                    f"{h['bottom_stress']:.6f} MPa",
                    f"{v['elastic'].bar_stress[0] / 1000:.6f} MPa",
                ],
                [
                    "Top steel stress",
                    f"{h['top_stress']:.6f} MPa",
                    f"{v['elastic'].bar_stress[-1] / 1000:.6f} MPa",
                ],
                [
                    "Concrete compression magnitude",
                    f"{h['concrete_stress']:.6f} MPa",
                    f"{v['elastic'].max_concrete_compression / 1000:.6f} MPa",
                ],
            ],
        ),
        _heading("General axial force and biaxial bending"),
        _md(
            "The general solver uses a reference-stress plane $q(x,y)=q_0+g_x x+g_y y$. "
            "Compression has q < 0. Clip the outer polygon and each void to that half-plane. "
            "Subtract the clipped void contributions. Calculate area A, first moments Sx and Sy, and second moments Sxx, Syy and Sxy. "
            "Here Sx is the integral of x over area, and Sxx is the integral of x squared over area."
        ),
        _table(
            [
                "Equilibrium row",
                "Coefficients of (q0, gx, gy)",
                "Tension-positive internal target",
            ],
            [
                ["Axial force", "(A, Sx, Sy)", "N"],
                ["Moment from y lever arm", "(Sy, Sxy, Syy)", "-Mx"],
                ["Moment from x lever arm", "(Sx, Sxx, Sxy)", "-My"],
            ],
        ),
        _md(
            "For each reinforcement element, add $w_i[1,x_i,y_i]$ to the axial row, "
            "$w_i y_i[1,x_i,y_i]$ to the second row, and $w_i x_i[1,x_i,y_i]$ to the third row. "
            "Use $w_i=(n_i-1)A_i$ in compression and $w_i=n_i A_i$ in the cracked tension region. "
            "Subtract the constant prestress resultants from the external target before solving."
        ),
        _md(
            "Start with the uncracked solution. Calculate the compressed polygon, its stiffness matrix, and the internal resultants. "
            "Subtract the target to obtain the residual vector r. Solve $J\\Delta q=-r$, then add the correction to the plane. "
            "Repeat the clipping and equilibrium calculation. The core allows 100 iterations and uses a relative residual threshold of 10^-9. "
            "Its residual scale is the largest absolute target component, with a minimum scale of 1 in core units (kN and kNm)."
        ),
        _md(
            "The reference plane has stress units. Divide q by the concrete modulus in consistent units to obtain physical strain. "
            "For the uncracked state, concrete acts over the whole net polygon and all reinforcement uses $(n_i-1)A_i$. "
            "That state requires one linear solution. The cracked state updates the compression boundary through iteration."
        ),
        _heading("Sustained and additional short-term actions"),
        _md(
            "Enter the sustained action in the long-term columns. Enter the additional action in the short-term columns. "
            "For this example, 100 kNm sustained plus 50 kNm additional gives a peak moment of 150 kNm. "
            "A creep coefficient of 2 gives $n_l=18$ and $n_s=6$."
        ),
        _md(
            "First solve the sustained action with $n_l$ to obtain passive steel stress s1. "
            "Retain $s2=s1(1-n_s/n_l)$. Calculate the axial force and moments from s2 in every reinforcement element. "
            "Subtract these resultants from the combined external target. Solve that target with $n_s$ to obtain RST1. "
            "Then TOTAL = s2 + RST1 and DIF = TOTAL - LONG."
        ),
        _figure(
            fig_duration_components,
            "Bottom-bar stress components for the sustained-plus-additional example. TOTAL equals the retained component plus RST1.",
            "Five bars compare LONG, retained stress, RST1, TOTAL and DIF for the same bottom reinforcement element and one specified action history.",
        ),
        _table(
            ["Bottom-bar quantity", "Calculation", "Stress (MPa)"],
            [
                [
                    "LONG",
                    "Sustained solve at nl = 18",
                    f"{r.bar_stress_long[0] / 1000:.6f}",
                ],
                [
                    "Retained",
                    "LONG x (1 - 6/18)",
                    f"{r.bar_stress_reduced_long[0] / 1000:.6f}",
                ],
                [
                    "RST1",
                    "Instantaneous solve after force adjustment",
                    f"{r.bar_stress_rst1[0] / 1000:.6f}",
                ],
                ["TOTAL", "Retained + RST1", f"{r.bar_stress_total[0] / 1000:.6f}"],
                ["DIF", "TOTAL - LONG", f"{r.bar_stress_dif[0] / 1000:.6f}"],
            ],
        ),
        _md(
            "The adjustment preserves the sustained steel response as the concrete modulus changes. "
            "Locked-in tendon prestress stays outside the retained passive-stress step and is added to the reported tendon stress. "
            "At zero creep, the retained component is zero. A counteracting additional action can reduce TOTAL below LONG. "
            "Review both entered states when you interpret the cracking classification."
        ),
    ]


def plastic_blocks():
    v = beam_example()
    p = v["plastic"]
    grouped = []
    for start in range(0, 80, 10):
        group = v["bands"][start : start + 10]
        grouped.append(
            [
                f"Bands {start + 1}-{start + 10}",
                f"{sum(t[0] for t in group) * 1e6:.3f}",
                f"{sum(t[3] for t in group):.6f}",
                f"{sum(t[4] for t in group):.6f}",
            ]
        )
    q = v["plateau"]
    grouped.append(["Plateau", f"{q[0] * 1e6:.3f}", f"{q[3]:.6f}", f"{q[4]:.6f}"])
    force_rows = [["Concrete", f"{p.concrete_force:.6f}", f"{p.concrete_mx:.6f}"]]
    for i, s in enumerate(p.bar_states, 1):
        force_rows.append([f"Bar {i}", f"{s.force:.6f}", f"{s.mx:.6f}"])
    force_rows.append(["Sum", f"{p.axial:.6f}", f"{p.Mx:.6f}"])
    return [
        _heading("Reproduce one plastic capacity point"),
        _md(
            "Use the existing 300 x 600 mm C40/50 beam with its B550 DK design preset. "
            "Set N = 0 and select a 90-degree sweep orientation, which compresses the top face. "
            "Concrete has fcd = 40/1.45 MPa, peak strain 0.002, and ultimate strain 0.0035. "
            "The complete material inputs and reinforcement positions follow. Coordinates use the section center as origin."
        ),
        _table(
            ["Input", "Value", "Meaning"],
            [
                [
                    "Concrete law",
                    "Curve 2; exponent 2",
                    "Parabola followed by a constant plateau",
                ],
                [
                    "fck / gamma_c / alpha_cc",
                    "40 MPa / 1.45 / 1",
                    "fcd = 27.586206897 MPa",
                ],
                [
                    "eps_c2 / eps_cu2",
                    "0.002 / 0.0035",
                    "Peak and ultimate compression strains",
                ],
                [
                    "Steel law",
                    "Curve 3; active in compression",
                    "Same law for all five bars",
                ],
                [
                    "fytk / fyck / futk",
                    "550 / 550 / 550 MPa",
                    "Tensile yield, compressive yield and ultimate strength",
                ],
                [
                    "gamma_y / gamma_u / gamma_E",
                    "1.20 / 1.20 / 1.00",
                    "Strength and modulus factors",
                ],
                [
                    "Es / k / eut",
                    "200000 MPa / 1 / 0.05",
                    "Modulus, first-yield ratio and ultimate tensile strain",
                ],
                ["ey0t / ey0c", "0 / 0", "Tensile and compressive yield offsets"],
                [
                    "Bars 1, 2, 3: (x, y)",
                    "(-100, -250), (0, -250), (100, -250) mm",
                    "Each area = pi x 25 squared / 4 mm2",
                ],
                [
                    "Bars 4, 5: (x, y)",
                    "(-100, 250), (100, 250) mm",
                    "Each area = pi x 16 squared / 4 mm2",
                ],
            ],
        ),
        _md(
            "For these inputs, the concrete compression magnitude is "
            "$f_{cd}[1-(1-\\varepsilon/0.002)^2]$ up to strain 0.002, then fcd up to 0.0035. "
            "Steel stress is Es times strain up to magnitude 458.333333333 MPa, then stays at that magnitude. "
            "Its yield strain is 0.002291666667. Use the tensile strain limit 0.05 when selecting the governing curvature."
        ),
        _md(
            "1. **Choose a trial depth c.** The neutral-axis coordinate is $s_{na}=s_{max}-c$. "
            "Calculate each admissible curvature from the governing-curvature equation. Select the smallest candidate. "
            "The trial strain is $\\varepsilon=\\kappa(s-s_{na})$, compression positive in this calculation."
        ),
        _figure(
            fig_capacity_limits,
            "Illustrative strain-limit comparison. The right panel assumes a tensile steel limit of 10 \u2030; it represents a different material from the worked beam.",
            "Two compatible straight strain lines illustrate concrete reaching 3.5 \u2030 compression and steel reaching its own illustrative tension limit while concrete remains below crushing.",
        ),
        _md(
            "2. **Calculate concrete forces.** The plateau begins at $s_{peak}=s_{na}+\\varepsilon_{c2}/\\kappa$. "
            "Divide the interval from sna to the smaller of speak and smax into 80 equal bands. "
            "For band i, use the strain at its depth midpoint to obtain the stress. "
            "Clip the polygon and voids to that band. Multiply stress by signed area for force and by signed first moments for moments."
        ),
        _figure(
            fig_plastic_bands,
            "Worked plastic compression zone. The eight displayed groups each contain ten integration bands. The plateau is integrated separately.",
            "The upper part carries constant design compression stress; the lower part follows the rising law down to zero stress at the neutral axis.",
        ),
        _md(
            "For this rectangle, each band has area $A_i=b\\Delta s$ and centroid $y_i=(y_{lower}+y_{upper})/2$. "
            "Its contributions are $F_i=\\sigma_i A_i$ and $M_{x,i}=F_i y_i$. "
            "Use MPa and mm2 for force in N, then divide by 1000 for kN. "
            "The plateau carries fcd throughout its area. The plastic calculation uses the gross net concrete polygon and adds reinforcement forces."
        ),
        _md(
            "3. **Calculate reinforcement forces.** Evaluate each bar at the strain plane and its assigned design law. "
            "For each tendon, combine its tension-positive section strain with its initial strain before evaluating its law. "
            "Multiply the stress by the element area. Use its x and y coordinates as moment arms."
        ),
        _md(
            "4. **Balance axial force.** Compare the sum of compression-positive forces with -N from the input table. "
            "If the trial force is too small, increase c. If it is too large, decrease c. "
            "Sector brackets the target and repeatedly halves the depth interval. "
            "The bracket can extend beyond the full section depth, which permits whole-section compression."
        ),
        _md(
            "The lower depth starts at 10^-9 times the projected section depth. The upper depth starts at the full projected depth. "
            "The upper bound can double up to 80 times to bracket axial compression. Bisection allows 100 iterations. "
            "The depth interval closes below 10^-12 times the projected depth. Acceptance also requires a reachable target and "
            "an axial residual no greater than $10^{-6}\\max(1,|N|)$ kN, with N in kN."
        ),
        _md(
            f"5. **Sum the accepted state.** The beam balances at **c = {p.compression_depth * 1000:.6f} mm**. "
            f"Its curvature is **{p.curvature:.9f} 1/m**. Concrete reaches its compression strain limit. "
            "The tension reinforcement has yielded. The tables use compression-positive force, with the section origin at mid-depth."
        ),
        _table(["Concrete region", "Area (mm2)", "Force (kN)", "Mx (kNm)"], grouped),
        _table(["Contribution", "Force (kN)", "Mx (kNm)"], force_rows),
        _md(
            f"The moment resistance is **{p.Mx:.6f} kNm**. The axial residual is **{p.axial_residual:.3e} kN**. "
            "The moment contribution of a band uses its area centroid and midpoint stress. "
            "This is a numerical approximation to the varying stress within that band."
        ),
        _heading("Resolution and envelope interpretation"),
        _table(
            ["Rising-region bands", "Beam resistance Mx (kNm)"],
            [[str(n), f"{m:.6f}"] for n, m in v["refinement"]],
        ),
        _md(
            "The refinement table changes only the number of stress bands. The section, material laws, axial force and orientation remain fixed. "
            "The small change demonstrates convergence for this beam. Irregular outlines, small compressed regions and different material laws need their own sensitivity check. "
            "Equilibrium convergence and integration accuracy describe separate properties of the result."
        ),
        _figure(
            fig_envelope_ray,
            "A fixed-N envelope from 15-degree orientation steps. The applied biaxial moment lies on a ray from the origin to the boundary.",
            "Discrete capacity points define a closed moment polygon. A ray through the applied pair Mx = 180 kNm and My = 30 kNm intersects that polygon to define utilization.",
        ),
        _md(
            "Each accepted orientation supplies one capacity pair at the selected N. Sector intersects the demand ray with segments between capacity points. "
            "Utilization is the applied radial distance divided by the boundary distance. "
            "The sweep angle and the direction of the resulting moment generally differ. Refine the angular step to assess interpolation sensitivity. "
            "A partial sweep provides capacity points over its selected range; a closed envelope is required for radial utilization."
        ),
        _md(
            "An N-M diagram varies axial force and shows its associated moment boundaries. "
            "A conditional bending resistance also preserves the simultaneous orthogonal moment. "
            "Use that conditional resistance when a chord check must carry both bending components. "
            "A capacity point with an unreachable axial target retains its convergence status for interpretation."
        ),
    ]


def other_blocks():
    return {
        "Serviceability: cracking and crack width": [
            _heading("Follow the crack-width calculation"),
            _md(
                "Begin with the uncracked tensile stress and the selected concrete tensile strength. "
                "The cracking factor identifies the action level at first cracking. Permanent tendon prestress remains fixed while external actions scale. "
                "Review both sustained and peak states because either can establish the cracked classification."
            ),
            _figure(
                fig_crack_geometry,
                "Effective tension areas in the manual's four worked method/system results. Each panel uses the stated example assumptions; heights are not universal defaults.",
                "Four aligned rectangles show effective heights of 125, 125, 100 and 175 mm above the same bottom tension face for EN 2005, DK fine, DK coarse and EN 2023.",
            ),
            _md(
                "For the selected duration, identify the tensile reinforcement and effective concrete area. "
                "Calculate the reinforcement ratio from those areas. Determine crack spacing from the selected method, cover, diameter and spacing condition. "
                "Calculate the mean strain difference with the applicable lower bound. Multiply spacing by strain difference, with the selected method's additional factors. "
                "Compare the resulting width with the criterion for that duration."
            ),
            _md(
                "Use the effective-area rules of the selected method. The DK coarse system locates an area whose centroid matches the tension reinforcement. "
                "The 2023 model constructs layers from the tension-face reinforcement. For biaxial response, Sector uses the resultant strain-gradient direction. "
                "The reported governing bar identifies the location used by the width calculation."
            ),
        ],
        "Shear resistance without shear reinforcement": [
            _heading("Read the shear force path"),
            _figure(
                fig_shear_truss,
                "Shear truss and resistance trade-off. Curves use the rounded values of the C35 linked-beam example; the force-path sketch is schematic.",
                "Inclined concrete struts transfer load between the chords while vertical links carry tension. Link resistance rises with cotangent theta and concrete crushing resistance falls over the plotted range.",
            ),
            _md(
                "Identify the active shear direction and its tension face first. Measure d to the centroid of the corresponding tension reinforcement. "
                "The web width represents the concrete that transfers shear. The internal lever arm connects the compression and tension resultants. "
                "For biaxial states, use the lever-arm component associated with that bending axis."
            ),
            _md(
                "Increasing cotangent theta engages more links over the load-transfer length. It also increases the longitudinal force demand and changes concrete strut stress. "
                "The governing resistance is the smaller of the link and strut values. "
                "The permitted angle range and any applicability condition belong to the selected method."
            ),
        ],
        "Torsion (thin-walled tube)": [
            _heading("Construct the effective torsion tube"),
            _figure(
                fig_torsion_tube,
                "Effective tube for the 300 x 600 mm torsion example. The dashed centerline is 50 mm inside the concrete boundary.",
                "The outer rectangle encloses a dashed 200 by 500 mm tube centerline. Arrows circulate around that line; its enclosed area is 100000 mm2 and its perimeter is 1400 mm.",
            ),
            _md(
                "A torque produces a circulating shear flow around a closed tube. The flow is $q=T/(2A_k)$. "
                "The wall stress follows from flow divided by effective wall thickness. Closed links carry transverse tension and perimeter reinforcement carries longitudinal tension. "
                "Concrete struts provide the compression path."
            ),
            _md(
                "For the worked rectangle, the centerline dimensions are 200 x 500 mm. "
                "Their product gives Ak = 100000 mm2, and twice their sum gives uk = 1400 mm. "
                "At T = 20 kNm, the flow is 100 N/mm. With effective thickness 100 mm, the wall shear stress is 1 MPa. "
                "Use these values to check the geometry before calculating each resistance."
            ),
        ],
        "Combined M-V-T interaction": [
            _heading("Trace the concurrent demands"),
            _figure(
                fig_combined_paths,
                "Schematic force paths for concurrent longitudinal and transverse demands.",
                "All four chord faces surround the section. A separate closed stirrup carries the sum of applicable shear and torsion demands at one common strut angle.",
            ),
            _md(
                "Start from one named action row. Bending establishes the section force state. "
                "Shear adds longitudinal chord demand, and torsion adds tension around the perimeter. "
                "The common-angle calculation must satisfy the applicable strut, stirrup and chord checks together. "
                "A maximum resistance from another angle cannot be substituted into that state."
            ),
            _md(
                "Read the physical checks and the selected edition's aggregate rule separately. "
                "The DK aggregate rule uses resistances to actions acting alone. The shared-angle checks use the concurrent force path. "
                "A conditional result identifies an assumption that requires supporting project evidence. "
                "A not-assessed result identifies the missing basis needed before a complete comparison is available."
            ),
        ],
        "Grouped fatigue": [
            _heading("From actions to repeated stress range"),
            _figure(
                fig_fatigue_actions,
                "Illustrative fatigue actions: a 100 kNm basic moment and a repeated additional 50 kNm. Cycle count is entered separately.",
                "Repeated moment peaks rise from a sustained 100 kNm baseline to 150 kNm. The vertical increment is the cyclic action component.",
            ),
            _md(
                "Define the sustained/basic action and the cyclic increment for each bin. "
                "Compare stresses at the same element or concrete location in the two states. "
                "Apply the selected fatigue action factor as specified by the method. Use the resulting stress range to obtain the allowable cycles. "
                "For Miner assessment, each bin contributes entered cycles divided by allowable cycles. Sum contributions within the named spectrum."
            ),
            _md(
                "Keep different spectra separate. A bar's peak stress in one state and another bar's stress in the second state do not form one physical stress range. "
                "Use element IDs and the governing-bin table to trace the reported damage."
            ),
        ],
        "Reinforcement detailing": [
            _heading("Relate analysis areas to physical reinforcement"),
            _md(
                "An analysis point supplies area and position for section equilibrium. Its detailing diameter supplies a physical size for spacing and crack geometry. "
                "When one point represents several bars, document the physical layout separately and use the supported layout controls for spacing checks. "
                "For two individual circular bars, clear spacing is their center distance minus half the sum of their diameters."
            ),
            _md(
                "For example, two 25 mm bars at 100 mm centers have 75 mm clear spacing. "
                "The governing spacing requirement also depends on aggregate size and the selected rule. "
                "Minimum longitudinal reinforcement uses the modeled tension region and section cut direction. "
                "Read the selected case and supplied reinforcement alongside its required area or resistance."
            ),
        ],
        "Reading the results": [
            _heading("Trace one reported result"),
            _md(
                "Select the case and identify the reported quantity, units and location. "
                "Read its method and criterion before interpreting the status. A stress percentage compares stress magnitude with characteristic material strength. "
                "A capacity utilization compares an action with the resistance defined by that check. "
                "A crack-width status compares the calculated width with the entered duration-specific limit."
            ),
            _md(
                "Use the detailed result and Audit report to follow inputs, intermediate quantities and the governing condition. "
                "Keep the case, direction, duration and element identity together. "
                "For a not-assessed result, follow the stated missing-input or applicability message. Recalculate after a calculation input changes."
            ),
        ],
        "Material laws": [
            _heading("Choose the law used by the calculation"),
            _md(
                "The elastic calculation uses the assigned modulus of each bar or tendon. "
                "The plastic calculation uses its assigned design stress-strain law and strain limits. "
                "The Active in compression (plastic) switch changes the plastic reinforcement response. Elastic steel remains linear in tension and compression."
            ),
            _md(
                "For a tendon with initial strain 0.005 and tension-positive section strain 0.001, the total material strain is 0.006. "
                "Evaluate the selected tendon law at that total strain. If the section strain is -0.001, the total becomes 0.004. "
                "The initial strain is an input after the assumed losses. Each tendon can have its own assigned law and initial strain."
            ),
        ],
    }


def extend_manual(blocks):
    """Append worked subsections without renumbering existing method chapters."""
    additions = other_blocks()
    additions["Conventions and sign convention"] = common_blocks()
    additions["Plastic capacity analysis"] = plastic_blocks()
    additions["Cracked-section elastic analysis"] = elastic_blocks()
    result = []
    part = None
    section = None
    for block in blocks:
        if block[0] in ("h1", "part") and section is not None:
            if (
                part == "Part C - Theory & methodology"
                or section == "Reading the results"
            ):
                result.extend(additions.get(section, []))
            section = None
        if block[0] == "part":
            part = block[1]
        elif block[0] == "h1":
            section = block[1]
        result.append(block)
    return result
