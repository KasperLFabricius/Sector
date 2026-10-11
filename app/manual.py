"""Sector user manual.

Single source of truth for the manual content. The content is authored as a
list of structured blocks (headings, markdown, callouts, figures, tables) so it
can be rendered both in the app (:func:`render_manual_streamlit`) and as a
downloadable PDF over the same blocks.

Two worked examples are threaded through the manual and their section drawings
are generated live from the same plotting code the app uses, so they always
match the current version:

* a rectangular beam reinforced with mild steel only, and
* a circular hollow section (with a central void) carrying both mild steel and
  prestressing tendons.

Source is kept ASCII-only (an app-wide invariant, guarded by
``tests/test_ascii_only.py``): callout icons are Streamlit emoji shortcodes
(e.g. ``:bulb:``) and mathematics is LaTeX (``$...$``), never literal non-ASCII
glyphs. The LaTeX renders with KaTeX in the app; the later PDF renderer converts
the same small subset to its own markup.
"""

from __future__ import annotations

import html
import io
import logging
import re

import plotly.graph_objects as go
import streamlit as st

from manual_equation_publication import (
    EQUATION_BLOCK,
    dependency_numbers,
    manual_publication_blocks,
    source_kind_label,
)
import publication_image_export
from publication_items import publish_manual_blocks, published_manual_parts
from publication_notation import normalize_trusted_markup
import publication_theme
from app import manual_information_architecture as manual_ia
from app import report_profiles
from app import table_field_definitions as table_fields
from sector import __author__ as APP_AUTHOR
from sector import __licensee__ as APP_LICENSEE
from sector import __version__ as APP_VERSION
from sector import design_standards, material_presets, templates
from sector.codes import fctm
from sector.fatigue import steel_fatigue_life
from sector.materials import Concrete, Prestress
from sector.plastic import solve_plastic
from sector.section import Section
from sector.serviceability import analyse_cracking

import viz
from manual_section_fields import (
    fig_elastic_strain_map, fig_elastic_stress_map,
    fig_plastic_strain_map, fig_plastic_stress_map,
)
from manual_additional_figures import (
    fig_directional_shear_faces, fig_slab_spacing_cover, fig_torsion_partition,
)

# Display scale for the section drawings: the geometry is in metres, drawn in mm.
_MM = 1000.0
_PERMILLE = chr(0x2030)
_LOGGER = logging.getLogger(__name__)


def _manual_input_source(basis_key, guidance_key) -> str:
    """Return the registry-owned source published in the reference table."""

    return design_standards.input_guidance(basis_key, guidance_key).source


# ==========================================================================
# WORKED EXAMPLES
# ==========================================================================
# Each example returns a plain dict: the geometry (metres, engine units), the
# materials, and the action combination. Later parts of the manual run analyses
# on these same dicts, so every worked number and figure comes from one model.

def example_beam() -> dict:
    """Rectangular beam, mild steel only: 300 x 600 mm, C40/50, B550.

    Three 25 mm bars near the bottom (tension) face and two 16 mm bars near the
    top, under an axial force plus uniaxial bending. This is the simplest case
    that exercises the plastic capacity, the cracked-elastic stresses and a crack
    width, so it anchors most of the worked derivations.
    """
    b, h = 0.30, 0.60
    outer = templates.rectangle(b, h)                 # centred on the origin
    a25 = templates.bar_area(25.0)
    a16 = templates.bar_area(16.0)
    bars = [(-0.10, -0.25, a25), (0.0, -0.25, a25), (0.10, -0.25, a25),
            (-0.10, 0.25, a16), (0.10, 0.25, a16)]
    concrete = Concrete(fck=40.0, gamma_c=1.45, curve=2)
    mild_preset = "DS/EN 1992-1-1:2005 + DK NA:2024"
    steel = material_presets.build_mild(
        **material_presets.MILD_PRESETS[mild_preset]
    )
    return {
        "name": "Rectangular beam (mild steel)",
        "outer": outer, "holes": [], "bars": bars, "tendons": [],
        "concrete": concrete, "steel": steel, "prestress": None,
        "mild_preset": mild_preset,
        "P": 0.0, "Mx": 300.0, "My": 0.0,
        "note": "300 x 600 mm, C40/50, B550; 3 x 25 mm bottom, 2 x 16 mm top.",
    }


def example_circular() -> dict:
    """Circular hollow section, mild steel + prestress: 800/400 mm annulus.

    An 800 mm outer diameter with a 400 mm central void, a ring of twelve 20 mm
    mild bars and a ring of eight tendons, under axial compression plus bending.
    This exercises the void handling, the biaxial (ring) reinforcement layout and
    the prestress law.
    """
    d_out, d_void = 0.80, 0.40
    outer = templates.circular(d_out)
    hole = templates.circular(d_void)
    r_bar = templates.ring_radius(d_out, 0.06)        # mild-bar circle
    bars = templates.bar_ring(0.0, 0.0, r_bar, 12, 20.0)
    r_tnd = 0.5 * (d_void / 2.0 + r_bar)              # tendons between void and bars
    tendons = templates.point_ring(0.0, 0.0, r_tnd, 8, 150.0)
    concrete = Concrete(fck=40.0, gamma_c=1.45, curve=2)
    mild_preset = "DS/EN 1992-1-1:2005 + DK NA:2024"
    steel = material_presets.build_mild(
        **material_presets.MILD_PRESETS[mild_preset]
    )
    prestress = Prestress(curve=6, IS=0.005, fytk=1600.0, futk=1860.0, eut=0.035,
                          gamma_y=1.15, gamma_u=1.15, gamma_E=1.15, Es=195000.0)
    return {
        "name": "Circular hollow section (mild + prestress)",
        "outer": outer, "holes": [hole], "bars": bars, "tendons": tendons,
        "concrete": concrete, "steel": steel, "prestress": prestress,
        "mild_preset": mild_preset,
        "P": 1500.0, "Mx": 600.0, "My": 0.0,
        "note": "800/400 mm annulus, C40/50; 12 x 20 mm mild ring + 8 tendons.",
    }


# ==========================================================================
# FIGURES -- live section drawings from the worked examples (reuse app viz)
# ==========================================================================

def _manual_native_plot(figure, height=520):
    """Keep reused application plots readable at the manual's 170 mm width."""
    figure.update_layout(
        width=920, height=height,
        font=dict(family="Arial", size=18),
        title_font_size=20,
        margin=dict(l=85, r=80, t=80, b=105),
        legend=dict(font_size=17, orientation="h", y=-0.22, x=0.5,
                    xanchor="center", yanchor="top"),
    )
    figure.update_xaxes(tickfont_size=17, title_font_size=18, automargin=True)
    figure.update_yaxes(tickfont_size=17, title_font_size=18, automargin=True)
    figure.update_annotations(font_size=17)
    for trace in figure.data:
        if hasattr(trace, "textfont"):
            trace.update(textfont_size=17)
    return figure


def _section_fig(ex: dict, title: str, labels=True):
    # Pass the full (x, y, area) points so the drawing scales markers by relative
    # bar diameter, matching the app's section views.
    figure = viz.section_figure(
        ex["outer"], ex["holes"], ex["bars"], tendons=ex["tendons"], title=title,
        show_labels=labels, height=460, scale=_MM, unit="mm")
    _manual_native_plot(figure, height=720)
    xs = [point[0] * _MM for point in ex["outer"]]
    ys = [point[1] * _MM for point in ex["outer"]]
    padding = 0.12 * max(max(xs) - min(xs), max(ys) - min(ys))
    figure.update_xaxes(range=[min(xs) - padding, max(xs) + padding], constrain="domain")
    figure.update_yaxes(range=[min(ys) - padding, max(ys) + padding], constrain="domain")
    return figure


def fig_workspace_overview():
    """A reproducible workspace schematic; it is not a screenshot."""
    fig = go.Figure()
    panels = (
        ("Inputs", "Input stage:<br>Analysis settings<br>Section<br>Material parameters<br>Loads / Project"),
        ("Analysis", "Calculate<br>Results Overview<br>Result details<br>Open selected result<br>Read criterion and reason"),
        ("Report", "Document details<br>Project/action references<br>Brief / Standard / Audit<br>Generate report<br>Download PDF"),
    )
    for index, (title, text) in enumerate(panels):
        fig.add_shape(type="rect", x0=index + 0.04, x1=index + 0.94,
                      y0=0.08, y1=0.88, fillcolor="#EEF2F7", line_color="#9FB3C8")
        fig.add_annotation(x=index + 0.49, y=0.78, text=f"<b>{title}</b>",
                           showarrow=False, font=dict(size=27, color="#1F3B66"))
        fig.add_annotation(x=index + 0.49, y=0.43, text=text, showarrow=False,
                           font=dict(size=22, color="#2C2C2A"), align="center")
        if index < 2:
            fig.add_annotation(x=index + 1.025, y=0.51, ax=index + 0.95, ay=0.51,
                               xref="x", yref="y", axref="x", ayref="y",
                               text="", showarrow=True, arrowhead=2, arrowwidth=2)
    fig.update_layout(width=1080, height=480, margin=dict(l=5, r=5, t=45, b=5),
                      title=dict(text=f"Sector v{APP_VERSION} - workspace schematic", font_size=23),
                      paper_bgcolor="white", plot_bgcolor="white")
    fig.update_xaxes(range=[0, 3], visible=False)
    fig.update_yaxes(range=[0, 1], visible=False)
    return fig


def fig_beam_section():
    return _section_fig(example_beam(), "Rectangular beam")


def fig_circular_section():
    # Labels OFF: the two 48-gon circles carry ~96 corner numbers that ring the
    # section and collide with the bar/tendon numbers -- pure noise for an example
    # figure. The rectangular beam above already demonstrates the numbering.
    return _section_fig(example_circular(), "Circular hollow section", labels=False)


def _section_of(ex: dict) -> Section:
    return Section.from_polygon(corners=ex["outer"], holes=ex["holes"],
                                bars_xy_area_mm2=ex["bars"],
                                tendons_xy_area_mm2=ex["tendons"])


def fig_beam_concrete_law():
    return _manual_native_plot(viz.concrete_curve_figure(example_beam()["concrete"]))


def fig_beam_steel_law():
    return _manual_native_plot(viz.steel_curve_figure(example_beam()["steel"]))


def fig_circular_prestress_law():
    return _manual_native_plot(viz.prestress_curve_figure(example_circular()["prestress"]))


def fig_beam_envelope():
    """The rectangular example's M-M interaction envelope with its applied load."""
    ex = example_beam()
    pts = solve_plastic(_section_of(ex), ex["concrete"], ex["steel"], ex["P"],
                        0.0, 360.0, 15.0)
    mx = [p.Mx for p in pts]
    my = [p.My for p in pts]
    figure = viz.interaction_figure(mx, my, applied=(ex["Mx"], ex["My"]))
    _manual_native_plot(figure, height=610)
    figure.update_xaxes(title_text="M<sub>y</sub> about the y-axis (kNm)")
    figure.update_yaxes(title_text="M<sub>x</sub> about the x-axis (kNm)")
    for annotation in figure.layout.annotations:
        annotation.text = annotation.text.replace("+Mx", "+M<sub>x</sub>").replace("+My", "+M<sub>y</sub>")
    return figure


# The service moment used for the crack-width derivations (a realistic SLS value,
# distinct from the higher moment that drives the plastic utilisation figure).
_BEAM_SLS_MX = 150.0


def fig_beam_cracked():
    """The rectangular example's cracked (Stage II) state: neutral axis and the
    concrete compression zone under the service moment."""
    ex = example_beam()
    cr = analyse_cracking(_section_of(ex), 0.0, _BEAM_SLS_MX, 0.0, 6.0,
                          fctm=fctm(ex["concrete"].fck), bar_diameter=25.0)
    st_ = cr.cracked_state
    hp = viz.elastic_halfplane(st_.na_x_intercept, st_.na_y_intercept,
                               st_.max_concrete_xy)
    zones = viz.compression_zones(ex["outer"], hp)
    # Clip the NA to the section bounds: an unclipped +/-1 m span forces the axis
    # range wide and shrinks the section (the NA is the horizontal dashes anyway).
    xs, ys = [p[0] for p in ex["outer"]], [p[1] for p in ex["outer"]]
    na = viz.na_line_at(hp[0], hp[1], hp[2], 1.0,
                        bbox=(min(xs), min(ys), max(xs), max(ys)))
    figure = viz.section_figure(ex["outer"], ex["holes"], ex["bars"], na_line=na,
                              zones=zones, title="Cracked section (Stage II)",
                              show_labels=False, height=460, scale=_MM, unit="mm")
    # Publish coordinates to 1e-9 mm. This removes CPU-kernel last-bit noise
    # while preserving the native cracked state and its displayed geometry.
    for trace in figure.data:
        for axis in ("x", "y"):
            coordinates = getattr(trace, axis, None)
            if coordinates is not None:
                rounded = [round(float(value), 9) if value is not None else None
                           for value in coordinates]
                trace.update({axis: [0.0 if value == 0 else value for value in rounded]})
    _manual_native_plot(figure, height=720)
    figure.update_xaxes(range=[-225, 225], constrain="domain")
    figure.update_yaxes(range=[-375, 375], constrain="domain")
    return figure


def example_fatigue_reinforcement() -> tuple[dict, dict, float]:
    """A compact grouped-spectrum example for the fatigue methodology figures."""

    properties = {
        "n_star": 2.0e6,
        "k1": 5.0,
        "k2": 9.0,
        "delta_sigma_rsk_mpa": 160.0,
    }
    gamma_s = 1.15
    inputs = (
        ("Heavy", 1.0e5, 155.0),
        ("Medium", 1.0e6, 110.0),
        ("Frequent", 5.0e6, 70.0),
    )
    bins = []
    for name, cycles, design_range in inputs:
        life = steel_fatigue_life(
            design_range,
            n_star=properties["n_star"],
            k1=properties["k1"],
            k2=properties["k2"],
            delta_sigma_rsk_mpa=properties["delta_sigma_rsk_mpa"],
            gamma_s=gamma_s,
            # The example range already comes from the action-level
            # long + gamma_Ff * short solve.
            gamma_ff=1.0,
        )
        bins.append({
            "bin_name": name,
            "cycles": cycles,
            "design_stress_range_mpa": design_range,
            "cycles_to_failure": life.cycles,
            "damage": cycles / life.cycles,
        })
    return {"element_id": "R1", "bins": tuple(bins)}, properties, gamma_s


def fig_fatigue_sn():
    result, properties, gamma_s = example_fatigue_reinforcement()
    figure = viz.fatigue_sn_figure(
        result,
        properties,
        gamma_s,
        title="Reinforcement fatigue: S-N assessment",
    )
    figure.update_yaxes(tickmode="array", tickvals=[70, 100, 200, 500],
                        ticktext=["70", "100", "200", "500"], minorloglabels="none")
    return _manual_native_plot(figure, height=610)


def fig_fatigue_damage():
    result, _properties, _gamma_s = example_fatigue_reinforcement()
    figure = viz.fatigue_damage_figure(
        result,
        title="Reinforcement fatigue: Miner damage",
    )
    for trace in figure.data:
        if trace.type == "bar":
            trace.update(text=[f"{value:.4f}" for value in trace.y], textposition="outside")
        elif trace.type == "scatter" and "lines" in (trace.mode or ""):
            # The first cumulative point equals the first bar; label it once.
            trace.update(mode="lines+markers+text", text=[""]+[f"{value:.4f}" for value in trace.y[1:]],
                         textposition="top center")
    return _manual_native_plot(figure, height=610)


def _schematic():
    """A blank figure for hand-drawn schematics (axes hidden, equal aspect)."""
    fig = go.Figure()
    fig.update_xaxes(visible=False, showgrid=False, zeroline=False)
    fig.update_yaxes(visible=False, showgrid=False, zeroline=False,
                     scaleanchor="x", scaleratio=1)
    fig.update_layout(height=340, margin=dict(l=10, r=10, t=10, b=10),
                      showlegend=False, plot_bgcolor="white")
    return fig


def _curved_arrow(fig, cx, cy, r, a0, a1, color):
    """A circular arc from angle a0 to a1 (radians) with an arrowhead at the end,
    for drawing a moment's rotational sense."""
    import math
    ts = [a0 + (a1 - a0) * i / 48.0 for i in range(49)]
    xs = [cx + r * math.cos(t) for t in ts]
    ys = [cy + r * math.sin(t) for t in ts]
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines",
                             line=dict(color=color, width=2.5), hoverinfo="skip"))
    # Arrowhead: a short straight arrow tangent to the arc at its end point.
    # Use a filled triangle so raster export retains a visible arrowhead.
    dx, dy = xs[-1] - xs[-4], ys[-1] - ys[-4]
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length
    head_length, half_width = 0.18, 0.075
    bx, by = xs[-1] - head_length * ux, ys[-1] - head_length * uy
    fig.add_trace(go.Scatter(
        x=[xs[-1], bx - half_width * uy, bx + half_width * uy, xs[-1]],
        y=[ys[-1], by + half_width * ux, by - half_width * ux, ys[-1]],
        mode="lines", fill="toself", fillcolor=color,
        line=dict(color=color, width=1), hoverinfo="skip"))


def fig_sign_convention():
    """Centroidal axes, action signs and the neutral-axis sweep angle."""
    import math
    fig = _schematic()
    ink = viz.SCHEMATIC_INK
    # The section (a concrete rectangle centred on the centroidal axes).
    fig.add_shape(type="rect", x0=-1.0, y0=-1.4, x1=1.0, y1=1.4,
                  line=dict(color=viz.CONCRETE_LINE, width=1.5),
                  fillcolor=viz.CONCRETE_FILL)
    # Centroidal x (right) and y (up) axes, arrowheads at the ends.
    for (hx, hy, lab) in ((2.15, 0.0, "x"), (0.0, 2.25, "y")):
        fig.add_annotation(x=hx, y=hy, ax=0.0, ay=0.0, axref="x", ayref="y",
                           showarrow=True, arrowhead=2, arrowwidth=1.5,
                           arrowcolor=ink, text="")
        fig.add_annotation(x=hx, y=hy, text=lab, showarrow=False,
                           xshift=(12 if lab == "x" else 0),
                           yshift=(0 if lab == "x" else 12),
                           font=dict(size=13, color=ink))
    # N is out of the page (tension +): the standard dot-in-circle symbol.
    fig.add_shape(type="circle", x0=-0.16, y0=-0.16, x1=0.16, y1=0.16,
                  line=dict(color=viz.BAR_TENSION, width=2))
    fig.add_trace(go.Scatter(x=[0.0], y=[0.0], mode="markers",
                             marker=dict(size=6, color=viz.BAR_TENSION),
                             hoverinfo="skip"))
    # Put the axial-force label below the moment arc, with a leader to its symbol.
    fig.add_annotation(x=0, y=0, ax=1.2, ay=-0.85, axref="x", ayref="y",
                       text="N: tension (+)<br>out of page", showarrow=True,
                       arrowhead=0, arrowwidth=1, arrowcolor=ink,
                       xanchor="left", font=dict(size=11, color=ink))
    # Moments as curved arrows about their axes (right-hand rule, positive sense):
    # Mx about x on the right, My about y on the top.
    _curved_arrow(fig, 2.15, 0.0, 0.55, math.radians(55), math.radians(-55),
                  viz.LOAD_POINT)
    fig.add_annotation(x=2.7, y=0.0, text="M<sub>x</sub>", showarrow=False,
                       xanchor="left", font=dict(size=13, color=viz.LOAD_POINT))
    _curved_arrow(fig, 0.0, 2.25, 0.55, math.radians(35), math.radians(145),
                  viz.LOAD_POINT)
    fig.add_annotation(x=0.0, y=2.85, text="M<sub>y</sub>", showarrow=False,
                       yanchor="bottom", font=dict(size=13, color=viz.LOAD_POINT))
    # The sweep angle phi_NA: a neutral axis at that angle from the +y axis. The
    # solver stores the value internally as V and uses the compression-gradient
    # direction (cos V, sin V), so the neutral axis is perpendicular to it, at angle
    # (90 + V) from +x. Drawing it at 90 - V would mirror the line and teach the
    # wrong sweep sense for intermediate V (the 0 / 90 deg endpoints coincide
    # either way).
    vdeg = 35.0
    vr = math.radians(90.0 + vdeg)   # measured from +x for the geometry
    fig.add_shape(type="line", x0=-1.7 * math.cos(vr), y0=-1.7 * math.sin(vr),
                  x1=1.7 * math.cos(vr), y1=1.7 * math.sin(vr),
                  line=dict(color=viz.NA_LINE, width=1.5, dash="dash"))
    ts = [math.radians(90.0) - math.radians(90.0 - vr * 180.0 / math.pi) * i / 20.0
          for i in range(21)]
    fig.add_trace(go.Scatter(
        x=[0.9 * math.cos(t) for t in ts], y=[0.9 * math.sin(t) for t in ts],
        mode="lines", line=dict(color=viz.NA_LINE, width=1.2), hoverinfo="skip"))
    fig.add_annotation(x=-0.42, y=1.08, text="&#966;<sub>NA</sub>", showarrow=False,
                       font=dict(size=12, color=viz.NA_LINE))
    # Label the line's LOWER-RIGHT end (open space): the upper-left end sits over the
    # +y axis and the section, so the caption would cross them.
    fig.add_annotation(x=-1.55 * math.cos(vr), y=-1.55 * math.sin(vr),
                       text="neutral axis (angle &#966;<sub>NA</sub> from +y)",
                       showarrow=False,
                       xanchor="left", xshift=6, font=dict(size=11, color=viz.NA_LINE))
    fig.update_annotations(font_size=15)
    return fig


def fig_strain_plane():
    """Schematic of the ultimate strain plane: strain is linear across the depth (a
    single straight line), zero at the neutral axis. Tension-positive: compression
    above the NA reads negative, tension below reads positive. The section is drawn on
    the left; the strain diagram, sharing the same depth axis, on the right against a
    vertical zero-strain reference."""
    fig = _schematic()
    eps = chr(0x3B5)             # epsilon glyph (BMP, surrogate-safe; source stays ASCII)
    y_na = 0.62
    xb0, xb1 = -1.35, -1.05      # the slim concrete depth bar, well clear of the strains
    # Section depth bar (top edge = compression face, bottom edge = tension face),
    # drawn as concrete so it matches the section figures.
    fig.add_shape(type="rect", x0=xb0, y0=0.0, x1=xb1, y1=1.0,
                  line=dict(color=viz.CONCRETE_LINE, width=1.5),
                  fillcolor=viz.CONCRETE_FILL)
    # The neutral axis (horizontal, carried across the section) and the zero-strain
    # vertical reference, both where the strain is zero.
    fig.add_shape(type="line", x0=xb0, y0=y_na, x1=1.0, y1=y_na,
                  line=dict(color=viz.GUIDE_LINE, width=1, dash="dot"))
    fig.add_shape(type="line", x0=0.0, y0=0.0, x1=0.0, y1=1.0,
                  line=dict(color=viz.GUIDE_LINE, width=1, dash="dot"))
    # The strain: ONE straight line through (0, y_na). Tension-positive, so the
    # compression above the NA is left of the zero line (negative) and the tension
    # below is right of it (positive). x is linear in depth, so x_bot is set to make
    # the line pass through zero exactly at the NA.
    x_top = -0.50
    x_bot = -x_top * y_na / (1.0 - y_na)
    # Shade the wedges between the zero line and the strain line, app-wide semantics:
    # Vermillion = compression (top), blue = tension (bottom).
    fig.add_trace(go.Scatter(x=[0.0, 0.0, x_top], y=[y_na, 1.0, 1.0],
                             fill="toself", mode="none", fillcolor=viz.COMP_ZONE_FILL))
    fig.add_trace(go.Scatter(x=[0.0, 0.0, x_bot], y=[y_na, 0.0, 0.0],
                             fill="toself", mode="none", fillcolor=viz.TENS_ZONE_FILL))
    fig.add_trace(go.Scatter(x=[x_bot, x_top], y=[0.0, 1.0], mode="lines",
                             line=dict(color=viz.SCHEMATIC_INK, width=2)))
    # Faces labelled directly above / below the concrete bar (clear of everything).
    x_bar = 0.5 * (xb0 + xb1)
    fig.add_annotation(x=x_bar, y=1.0, yshift=13, yanchor="bottom", showarrow=False,
                       text="compression face", font=dict(size=11, color=viz.CONCRETE_LINE))
    fig.add_annotation(x=x_bar, y=0.0, yshift=-13, yanchor="top", showarrow=False,
                       text="tension face", font=dict(size=11, color=viz.CONCRETE_LINE))
    # Strain endpoints labelled with leader arrows into clear space (up-left for the
    # compression fibre, down-right for the tension steel), so nothing overlaps.
    # The faces (on the bar) carry the compression / tension words; the strain
    # endpoints just carry the signed symbol, placed clear of the face labels.
    fig.add_annotation(x=x_top, y=1.0, ax=26, ay=-22, showarrow=True, arrowhead=2,
                       arrowsize=0.8, arrowwidth=1, arrowcolor=viz.GUIDE_LINE,
                       xanchor="left", text=eps + "<sub>cu</sub> (-)",
                       font=dict(size=11))
    fig.add_annotation(x=x_bot, y=0.0, ax=26, ay=22, showarrow=True, arrowhead=2,
                       arrowsize=0.8, arrowwidth=1, arrowcolor=viz.GUIDE_LINE,
                       xanchor="left", text=eps + "<sub>s</sub> (+)",
                       font=dict(size=11))
    # NA label at the right end of its line, in the right margin (clear of the wedges).
    fig.add_annotation(x=1.0, y=y_na, xshift=8, xanchor="left", showarrow=False,
                       text="neutral axis (" + eps + " = 0)", font=dict(size=11))
    fig.update_layout(margin=dict(l=20, r=125, t=48, b=48))
    fig.update_annotations(font_size=15)
    return fig


# ==========================================================================
# CONTENT -- structured blocks (single source for app + PDF)
# ==========================================================================
# Block types:
#   ('part', text)
#   ('h1'|'h2'|'h3', text)
#   ('md', markdown_text)
#   ('callout', kind, text)      kind in concept|theory|standard|tip|limit
#   ('figure', fig_callable, caption)
#   ('table', headers, rows)

_CALLOUT = {
    "concept":  (":large_blue_diamond:", "In plain terms"),
    "theory":   (":triangular_ruler:", "Theory"),
    "standard": (":blue_book:", "Standards"),
    "tip":      (":bulb:", "Tip"),
    "limit":    (":warning:", "Assumption / limitation"),
}


def _manual_field_notation(definition) -> str:
    """Return one compact field label backed by the shared table registry."""

    text = definition.label
    if definition.math_symbol != "-":
        text += f" ${definition.math_symbol}$"
    if definition.unit != "-":
        text += f" [${table_fields.latex_unit(definition.unit)}$]"
    return text


def _manual_blank_summary(table_key: str) -> str:
    """Summarise every field's registry-owned blank/default contract."""

    grouped: dict[str, list[str]] = {}
    for definition in table_fields.table_fields(table_key):
        rule = table_fields.input_rule(definition)
        if rule == "Blank = False":
            rule = "Blank = off"
        elif rule == "Blank = True":
            rule = "Blank = on"
        grouped.setdefault(rule, []).append(definition.label)

    return "; ".join(
        f"{rule}: {', '.join(labels)}" for rule, labels in grouped.items()
    )


def editable_table_reference_rows() -> list[list[str]]:
    """Build the seven-row manual matrix from the canonical field registry."""

    rows = []
    for table_key in table_fields.TABLE_KEYS:
        fields = table_fields.table_fields(table_key)
        rows.append([
            table_fields.TABLE_TITLES[table_key],
            "; ".join(_manual_field_notation(field) for field in fields),
            _manual_blank_summary(table_key),
        ])
    return rows


def editable_field_reference_rows() -> list[list[str]]:
    """Build the complete field-by-field input reference from shared metadata."""

    rows = []
    for table_key in table_fields.TABLE_KEYS:
        for definition in table_fields.table_fields(table_key):
            rows.append([
                table_fields.TABLE_TITLES[table_key],
                _manual_field_notation(definition),
                f"{definition.definition} Sign: {definition.sign}",
                (
                    f"{table_fields.input_rule(definition)}. "
                    f"{table_fields.validation_rule(definition)}"
                ),
                table_fields.method_dependency(table_key, definition),
            ])
    return rows


def editable_field_publication_rows(table_key: str) -> list[list[str]]:
    """Compact the canonical metadata without repeating a table's shared scope."""
    rows = []
    fields = table_fields.table_fields(table_key)
    common_dependency = table_fields.method_dependency(table_key, fields[0])
    for field in fields:
        meaning = field.definition
        if field.sign not in {
            "Identifiers carry no physical sign.", "Names carry no physical sign.",
            "Not applicable.",
        }:
            meaning += " " + field.sign
        if field.source != "User input":
            meaning += " Source: " + field.source + "."
        dependency = table_fields.method_dependency(table_key, field)
        if dependency != common_dependency:
            meaning += " Used by: " + dependency + "."
        rule = table_fields.input_rule(field).replace("Blank = False", "Blank = off")
        rule = rule.replace("Blank = True", "Blank = on")
        validation = table_fields.validation_rule(field)
        if validation == "Enter a finite decimal value. Use the sign convention in this table.":
            validation = ""  # The shared numeric requirement appears once above.
        elif field.key == "ID":
            validation = 'Read-only. Generated by Sector.'
        elif field.key == "size mode":
            validation = "Area, Diameter or Independent."
        elif field.key == "material ID":
            validation = "Required ID of a material in the matching material catalog."
        elif field.key == "fatigue detail ID":
            validation = "Assigned fatigue detail required for reinforcement fatigue."
        elif field.key in {"vx_face", "vy_face"}:
            validation = "auto, negative or positive."
        elif field.key == "check_minimum_reinforcement":
            validation = "On requests the check. Off leaves it unrequested."
        if validation.startswith("Required. ") and rule == "Required":
            validation = validation.removeprefix("Required. ")
        rows.append([_manual_field_notation(field), meaning,
                     rule + (". " + validation if validation else "")])
    return rows


def _strip_num(text: str) -> str:
    """Drop a leading hardcoded section number so headings can be auto-numbered
    (lets a section be inserted without renumbering every following heading)."""
    return re.sub(r"^\s*\d+(?:\.\d+)*\.?\s+", "", text)


def manual_blocks() -> list:
    """The whole manual as a flat list of typed blocks (see the module header)."""
    blocks: list = []
    part = lambda t: blocks.append(("part", t))
    def heading(kind, text):
        blocks.append((kind, text))
        anchor = manual_ia.heading_anchor(text, 1 if kind == "h1" else 2)
        for workflow in manual_ia.WORKFLOWS:
            if anchor != manual_ia.destination(workflow.destination_key).anchor:
                continue
            steps = "\n".join(
                f"{index}. {sentence}"
                for index, sentence in enumerate(
                    re.split(r"(?<=\.)\s+", workflow.action), 1
                )
            )
            blocks.append(("md", f"**{workflow.label}**\n\n**Before:** {workflow.prerequisite}.\n\n"
                           f"{steps}\n\n"
                           f"**Expected:** {workflow.expected_state}.\n\n"
                           "[Status and next action](#manual-status-reference)\n\n"
                           "[Troubleshooting](#manual-limitations-troubleshooting)"))
    h1 = lambda t: heading("h1", t)
    h2 = lambda t: heading("h2", t)
    md = lambda t: blocks.append(("md", t))
    call = lambda kind, t: blocks.append(("callout", kind, t))
    fig = lambda fn, cap, alt: blocks.append(("figure", fn, cap, alt))
    table = lambda hdr, rows: blocks.append(("table", hdr, rows))
    def field_guides(keys):
        for table_key in keys:
            h2(table_fields.TABLE_TITLES[table_key] + " fields")
            definitions = table_fields.table_fields(table_key)
            dependencies = dict.fromkeys(
                table_fields.method_dependency(table_key, definition)
                for definition in definitions)
            md(" ".join(dependencies))
            table(["Field / unit", "Meaning / sign", "Default / validation"],
                  editable_field_publication_rows(table_key))

    # =====================================================================
    # PART A - GET STARTED
    # =====================================================================
    part("Part A - Get started")

    h1("Introduction & purpose")
    md("**Sector** calculates the response and resistance of reinforced and "
       "prestressed concrete cross-sections. A model contains a concrete outline, "
       "optional voids, reinforcing bars, tendons, material definitions and named actions. "
       "The results include stresses, strains, resistance diagrams, selected engineering "
       "checks and a calculation report.")
    h2("Who this manual is for")
    md('This manual serves engineers who define section geometry, reinforcement and design actions. The operating chapters give information about the controls and results. The method chapters give information about the physical models. The numerical procedures give the arithmetic needed for an independent calculation.')
    md('**Open and export the manual**\n\n1. Open **Inputs > Project**.\n2. Expand **About**.\n3. Select **User manual**.\n4. Select a **Manual part** to read it in the application.\n5. Select **Generate PDF** to prepare the full PDF and HTML manuals.\n6. Select **Download PDF** or **Download accessible HTML**.\n\nThe HTML file opens in a browser for offline reading. The two exports contain all manual parts. **Close** returns to the application. **About** also shows the installed Sector version.')
    md('Prepare the section dimensions, reinforcement layout, material properties and action combinations before calculation. Also select the project design basis, partial factors, creep coefficient and the applicable acceptance criteria. Sector calculates the section properties and responses from those inputs.')
    h2("The section model")
    md('Sector represents concrete by polygons and reinforcement by discrete areas at specified coordinates. Voids remove concrete from the section. Plane sections stay plane, so section strain varies linearly with position. Bonded reinforcement follows that strain field. Tendon strain also includes the entered initial strain.')
    md('The project supplies the section actions, with the applicable member-level effects. Shear and torsion checks use the entered member assumptions and the selected section method. Examine the applicable assumptions beside each calculation.')
    h2("Available calculations")
    table(["Calculation", "Purpose and principal output", "Read next"], [
        ["Plastic capacity", 'Bending resistance at a specified axial force. Biaxial envelope and demand utilization.',
         "[Plastic capacity](#manual-method-plastic)"],
        ["N-M interaction", 'Additional axial-force sweeps. Axial force versus bending resistance about each axis.',
         "[N-M results](#manual-n-m-interaction)"],
        ["Elastic response", 'Concrete, bar and tendon stresses. Neutral axis, section properties and duration states.',
         "[Elastic analysis](#manual-method-elastic)"],
        ["Cracking and crack width", 'Cracking threshold and requested crack widths. Comparison with entered duration limits.',
         "[Crack calculations](#manual-method-cracking)"],
        ["Grouped fatigue", 'Element and concrete stress ranges, fatigue life and damage in each named spectrum.',
         "[Fatigue](#manual-method-fatigue)"],
        ["Directional shear", "Resistance in each active shear direction, with the applicable concrete or link route.",
         "[Shear](#manual-method-shear)"],
        ["Torsion", "Effective tube, strut and stirrup resistances, longitudinal demand and assessment status.",
         "[Torsion](#manual-method-torsion)"],
        ["Combined actions", "Concurrent bending, shear and torsion checks with their governing components.",
         "[Combined actions](#manual-method-combined)"],
        ["Reinforcement detailing", "Minimum reinforcement, clear spacing, and shear/torsion link ratio and spacing.",
         "[Detailing](#manual-method-detailing)"],
        ["Calculation records", "Named cases, saved project inputs and Brief, Standard or Audit reports.",
         "[Report workspace](#manual-report-workspace)"],
    ])
    h2("Standards and method selection")
    md('Sector offers three design bases: **EN 1992-1-1:2005**, **DS/EN 1992-1-1:2005 + DK NA:2024**, and **DS/EN 1992-1-1:2023**. The table shows their implemented availability. The detailed method references identify the clauses used by each calculation.')
    table(["Capability", "2005 base", "2005 + DK NA:2024", "2023"], [
        ["Concrete, bar and tendon presets", "Available", "Available", "Available"],
        ["Ordinary crack width", "Available", "Fine and coarse systems", "Refined model"],
        ["Heightened crack-control minimum", "-", "Available", "-"],
        ["Fatigue design basis", "Available", "Available", "Available"],
        ["Reinforcement detailing", "Available", "Available", "Available"],
        ["Shear with and without links", "Available", "Available", "Available"],
        ["Torsion and combined M-V-T", "Available", "Available", "-"],
    ])
    md('Select material presets and check methods independently. Generic material curves supply editable project-defined starting values. Sector uses the selected values for the calculation. The report identifies their method and source. When combined M-V-T is enabled, its selected edition also controls the related shear and torsion editions.')
    md('For concrete fatigue, also select the calculation method: explicit Palmgren-Miner spectrum, user-defined Miner S-N relation, or damage-equivalent stress amplitude. Their required actions, cycle data and coefficients are different. The fatigue chapter gives the procedure for each method.')
    call("standard", 'Documented project adoption is necessary for the 2023 basis. Sector applies the published 2023 method without a Danish National Annex. Make sure that the applicability conditions and effective factors are correct for each selected check.')
    h2("From inputs to a calculation record")
    md('Section and material previews update during editing. **Calculate** produces the analysis results. Calculate again after a calculation-input change. Examine the named results and their statuses, then save the project and generate the report.')

    h1("Start here")
    md('Select the shortest reading path for the task. Each link has the same destination name in the PDF outline and HTML manual.')
    table(
        ["Reading path", "Use it when", "Destination"],
        [
            [
                "Quick calculation",
                'You want to define one section, calculate and examine a result.',
                "[Open Quick start](#manual-quick-calculation)",
            ],
            [
                "Input reference",
                'You want one field, default, validation rule or warning.',
                "[Open Input reference](#manual-input-reference)",
            ],
            [
                "Method reference",
                'You want an equation, assumption, calculation alternative or scope limit.',
                "[Open Method reference](#manual-method-reference)",
            ],
            [
                "Numerical procedures",
                "You want to reproduce solver arithmetic and intermediate results.",
                "[Open Numerical procedures](#manual-numerical-procedures)",
            ],
            [
                "Portable startup",
                'You want to start or update the Windows application.',
                "[Open Portable startup](#manual-portable-startup)",
            ],
            [
                "Troubleshooting",
                'You want the cause of a warning and the corrective step.',
                "[Open Troubleshooting](#manual-limitations-troubleshooting)",
            ],
        ],
    )

    h1("Start the portable application")
    md('The Windows release contains the full application in a portable ZIP. Microsoft Edge, or a different supported Chromium-family browser, supplies the image-export dependency for report figures.')
    md('1. Download the **0.96.5 Windows portable ZIP** from the repository release.\n2. Use **Extract All** to extract the full archive to a short local path, such as `C:\\Sector`.\n3. Keep the `_internal` folder beside `Sector.exe`.\n4. Open `Sector.exe`.\n5. Wait for the Sector interface to open in the default browser.')
    md("Sector runs on the local computer. Keep its console window open during use. "
       "To stop Sector, close that console window or press **Ctrl+C** in it.")
    md('Before an update, download the current project file. Keep the issued report. Extract the new release into a different folder. Open the saved project in the new version. Examine its inputs. Calculate again.')
    md("The portable package is unsigned. If Windows or company policy blocks it, use the organization's approved software process. The package README contains the release-specific startup information.")

    h1("Quick start")
    md('This tutorial calculates a 300 by 600 mm reinforced concrete beam. It gives one plastic capacity case and one elastic stress case. The selected values define a teaching example. The method chapters use the same geometry for independent calculations.')
    md('Before this exercise, save the current project if you must keep it. Replace its geometry and action rows with the tutorial data. Set optional fatigue, N-M, crack-control, shear, torsion, combined and detailing checks to off for this first calculation.')
    fig(fig_workspace_overview, 'Workspace overview (schematic): prepare inputs, calculate and examine named results, then publish.',
        'Three linked panels show the workspaces. Inputs has a stage selector. Analysis has Calculate and result details. Report has document details, references, profile selection and PDF generation.')
    h2("1. Select the calculation modes")
    md('1. Open **Inputs > Analysis settings**.\n2. Under **Bending analysis**, select **Both**.\n3. Set the plastic start angle to 0 degrees and the end angle to 360 degrees.\n4. Set the maximum angle increment to 15 degrees.\n5. Enable **Check utilisation against applied moment**.')
    md('Use the plastic and elastic calculations for this first exercise. The task procedures in Part B add crack width, fatigue, shear, torsion and detailing with their required inputs.')
    h2("2. Define the materials")
    md('Open **Inputs > Material parameters**. Enter these concrete values and define one reinforcing-steel material. If you use **Auto-calc all derived values**, then enter the teaching values in the table.')
    table(["Material input", "Value entered in Sector", "Use"], [
        ["Concrete preset", "Curve 2 (parabola-rectangle)", "Compression stress-strain law"],
        ["$f_{ck}$", "40 MPa", "Characteristic concrete strength"],
        ["$\\gamma_c$ / $\\alpha_{cc}$", "1.45 / 1.00", "Design concrete strength factors"],
        ["$\\varepsilon_{c2}$ / $\\varepsilon_{cu2}$", "2.0 / 3.5 \u2030", "Peak and ultimate compression strains"],
        ["Parabola exponent", "2", "Rising concrete branch"],
        ["$E_c$", "33.333333333 GPa", 'Teaching modulus. $33333.333333$ MPa in the calculation'],
        ["Reinforcing-steel preset", "DS/EN 1992-1-1:2005 + DK NA:2024", "Starting values for the bar law"],
        ["$f_{ytk}$ / $f_{yck}$ / $f_{utk}$", "550 / 550 / 550 MPa", "Tensile yield, compression yield and ultimate strengths"],
        ["$\\gamma_y$ / $\\gamma_u$ / $\\gamma_E$", "1.20 / 1.20 / 1.00", "Final effective material factors"],
        ["$E_s$", "200 GPa", 'Steel modulus. $200000$ MPa in the calculation'],
        ["$\\varepsilon_{ut}$", "50 \u2030", 'Ultimate bar strain. 0.05 in the calculation'],
        ["$k$ / $\\varepsilon_{0t}$ / $\\varepsilon_{0c}$", "1 / 0 / 0", "First-yield ratio and plastic strain offsets"],
        ["Active in compression (plastic)", "On", "Bars also contribute compression resistance"],
    ])
    md("Keep the reinforcing material ID for the next step. With zero creep, "
       "these moduli give the modular ratio $n=E_s/E_c=6$. The plastic calculation "
       "uses the design stress-strain laws and their strain limits.")
    md('After you enter $f_{ck}=40$ MPa, set $f_{ctm}$ with its **Auto** button. Sector uses this value for the cracking threshold and reports a result for that threshold. Then make sure that $E_c$ keeps the teaching value in the table.')
    h2("3. Enter the section and bars")
    md('Open **Inputs > Section**. Replace the outer concrete points with the four coordinates in the table. Keep the void and tendon tables empty for this example.')
    table(["Corner", "$x$ (mm)", "$y$ (mm)"], [
        ["1", "-150", "-300"], ["2", "-150", "300"],
        ["3", "150", "300"], ["4", "150", "-300"],
    ])
    md('Enter five reinforcing bars. Select **Diameter** as their size input. Assign the material ID from step 2 to each bar.')
    table(["Bar", "$x$ (mm)", "$y$ (mm)", "Diameter (mm)"], [
        ["1", "-100", "-250", "25"], ["2", "0", "-250", "25"],
        ["3", "100", "-250", "25"], ["4", "-100", "250", "16"],
        ["5", "100", "250", "16"],
    ])
    md('Examine the preview. The origin is at the rectangle center. Three bars are near the bottom and two near the top. Before calculation, correct the cause of each geometry or material-assignment warning.')
    h2("4. Enter two named actions")
    md('Open **Inputs > Loads**. Under **Global Elastic parameter**, set the creep coefficient to 0. Enter these rows. Use zero for the remaining action components.')
    table(["Table and case name", "Entered actions", "Requested output"], [
        ["Plastic/capacity: Beam capacity", '$N=0$ kN. $M_x=300$ kNm. $M_y=0$ kNm', "Bending capacity and utilization"],
        ["Elastic: Beam elastic", 'Sustained components: 0. Additional $M_x=150$ kNm', 'Elastic stresses. Crack width off for this exercise'],
    ])
    md("The additional moment is the short-term increment. With zero sustained "
       "action, the total moment is 150 kNm. Positive axial force means tension. "
       "Positive $M_x$ produces tension near the bottom of this section.")
    h2("5. Calculate and check the results")
    md('1. Open **Analysis** and press **Calculate**.\n2. Examine **Results Overview** for calculation warnings.\n3. Open **Plastic Results** and select **Beam capacity**.\n4. Select the 90-degree **Neutral-axis state**.\n5. Open **Elastic Results** and select **Beam elastic**.\n6. Compare the results with the values in the table.')
    table(["Result", "Expected value", "Comparison tolerance"], [
        ["Plastic compression depth at 90 degrees", "83.7991 mm", "0.01 mm"],
        ["Plastic $M_x$ resistance at 90 degrees", "345.9766 kNm", "0.01 kNm"],
        ["Plastic applied utilization", "Approximately 0.867", "0.001"],
        ["Elastic compression depth from the top face", "149.2505 mm", "0.01 mm"],
        ["Elastic bottom-bar stress", "+203.6223 MPa", "0.01 MPa"],
        ["Elastic top-bar stress", "-50.4296 MPa", "0.01 MPa"],
        ["Peak concrete compression magnitude", "12.6391 MPa", "0.01 MPa"],
    ])
    md('The tolerances allow for displayed rounding and the entered modulus precision. If a value differs, examine geometry, material factors, modulus units, action duration and selected case in that sequence.')
    h2("6. Save and report the calculation")
    md('1. Open **Inputs > Project**.\n2. Expand **Save / Load**.\n3. Select **Download project**.\n4. Keep that file with a descriptive calculation name.\n5. Open **Report**.\n6. Enter the project, section and revision details.\n7. Select **Standard**.\n8. Generate the report.\n9. Download the PDF.\n10. Open **Inputs > Project**.\n11. Expand **Save / Load**.\n12. Under **Load project**, select the saved project file.\n13. Examine the restored inputs.\n14. Open **Analysis**.\n15. Select **Calculate**.\n16. Compare the results again.')
    md('The project file keeps the inputs. The PDF records the issued calculation. Keep the two files and the Sector version with the calculation record.')

    h1("Task workflows")
    md('Select a task from the table. Its destination includes prerequisites, the steps and expected state.\n\nAfter you edit calculation inputs or load a project, open **Analysis**. Press **Calculate** before you use the results. If only Report details change, the report uses the current results.')
    table(
        ["Task", "Outcome"],
        [[f"[{workflow.label}](#{manual_ia.destination(workflow.destination_key).anchor})",
          workflow.outcome] for workflow in manual_ia.WORKFLOWS],
    )

    h1("The worked examples")
    md('The material, bending and elastic examples use the two sections in this chapter. Shear and torsion examples use the variants described with their calculations. Changed inputs and supplied scalar assumptions are stated there.')
    h2("Rectangular beam (reinforcing steel)")
    md('A 300 by 600 mm rectangular section uses C40/50 concrete and B550 reinforcement. Three 25 mm bars are near the bottom face. Two 16 mm bars are near the top. This example shows plastic capacity, cracked-elastic stresses and crack width.')
    fig(fig_beam_section, "Rectangular beam: 3 x 25 mm bottom, 2 x 16 mm top.",
        'A 300 by 600 mm concrete rectangle with three bottom bars and two top bars arranged symmetrically about the vertical centerline.')
    h2("Circular hollow section (mild + prestress)")
    md('An 800 mm diameter circular section has a 400 mm central void and C40/50 concrete. It has a ring of twelve 20 mm mild bars and a ring of eight prestressing tendons. This example adds voids, biaxial ring reinforcement and the prestress law to the beam example.')
    fig(fig_circular_section, "Circular hollow section: a central void, a mild-bar "
        "ring and a tendon ring.",
        'An annular concrete section with concentric outer and void boundaries. Mild reinforcement and prestressing tendons form two circular rings.')
    table(["Named variant / calculation", "Section and materials", "Actions / changed assumptions"], [
        ['[Beam](#manual-method-plastic). [elastic and cracking](#manual-method-cracking)',
         '300 x 600 mm, C40/50, B550. 3 x 25 mm bottom and 2 x 16 mm top bars.',
         "Plastic example: N = 0. Elastic/crack examples: $M_x$ = 150 kNm."],
        ["[Circular hollow](#manual-method-materials)",
         '800/400 mm annulus, C40/50. 12 x 20 mm bars and 8 tendons.',
         'Tendon-law example: initial strain 5.0 \u2030. Proof strength 1600 MPa, factor 1.15.'],
        ["[Shear without links](#manual-method-shear)",
         '300 x 600 mm rectangle. C35 with DK NA:2024.',
         'N = 0. Supplied $A_{sl}$ = 1473 $\\text{mm}^{2}$, d = 550 mm, $b_w$ = 300 mm.'],
        ["[Shear with links](#manual-method-shear)",
         'Same C35 shear section. Two-leg 10 mm links at 150 mm, $f_{ywk}$ = 500 MPa.',
         'Calculated $z=509.151$ mm. Maximum $\\cot\\theta=2.5$.'],
        ["[Torsion rectangle](#manual-method-torsion)",
         '300 x 600 mm, C35, DK NA:2024. Bar centers 50 mm from each wall.',
         'Closed 10 mm stirrup at 150 mm. $\\gamma_{ct}$ = 1.70. Resistance example.'],
        ["[2023 chord arithmetic](#manual-method-shear)",
         'Supplied scalar assumptions. No new section geometry is defined.',
         "$M_{Ed}$ = 90 kNm, $M_{Rd}$ = 100 kNm, $N_{Vd}$ = 250 kN and z = 0.5 m."],
    ])

    h1("Common use cases")
    md('Calculate ultimate capacity, examine biaxial columns, calculate service crack widths, calculate grouped fatigue, or compare reinforcement layouts and concrete grades. The outputs in this chapter stay related to the named actions.')

    h2('What Sector calculates')
    md("- **Plastic bending capacity.** Full biaxial $M_x$-$M_y$ interaction at the given axial force with nonlinear material laws, and applied-load utilization.\n- **Elastic response.** Cracked-section concrete and reinforcement stresses from long- and short-term actions, with creep through the modular ratio. Cracking threshold and transformed section properties.\n- **Crack width.** Requested long- and short-term widths. A 0 mm limit leaves that duration's calculated width. A positive limit adds the matching specified-limit comparison and source.\n- **Grouped fatigue.** Reinforcement S-N/Miner and concrete compression checks for each bar, tendon, concrete fiber and bin in independent named spectra.\n- **Longitudinal detailing.** Edition-specific minimum reinforcement per capacity case and section-wide clear spacing.\n- **Multi-case reporting.** Select individual Plastic/capacity, Elastic and fatigue results or examine their summary. PDF profiles give results and references, with detailed calculations in Audit. Project files save the inputs.")


    # =====================================================================
    # PART B - FEATURES & OPTIONS
    # =====================================================================
    part("Part B - Features & options")

    h1("Input reference")
    md('The reference follows the same five stages as the application. Select a stage from the table, then use the shared field definitions and troubleshooting entries in this part.')
    table(
        ["Application stage", "Manual destination"],
        [
            [stage.label, f"[Open {stage.label}](#{stage.anchor})"]
            for stage in manual_ia.INPUT_STAGES
        ],
    )

    h1("The workspace")
    md('The **Inputs** page stages *Analysis settings*, *Section*, *Material parameters*, *Loads* and *Project* in the **Input stage** selector. The *Section* stage places the section drawing beside its point tables, and each material panel places the selected stress-strain law beside its parameters. Each preview updates when an input changes. \n\nThe **Analysis** workspace contains calculated results selected with the **View** dropdown. \n\nThe **Report** workspace, immediately to its right, owns document details, profile selection, generation and PDF download.')
    table(["View", "Shows"],
          [["Results Overview", 'Most unfavorable result for each engineering check, with the governing action or direction'],
           ["Plastic Results", 'Selected case: M-M envelope and utilization'],
           ["N-M Interaction", "Selected Plastic case: axial-moment boundaries"],
           ["Elastic Results", "Selected case: stresses, cracking and crack width"],
           ["Fatigue Results", 'All spectra. Selected spectrum, element, fiber and bin results'],
           ["Detailing", 'Selected case: modeled-direction minimum reinforcement and link detailing. Section-wide spacing'],
           ["Shear", 'Selected Plastic case: $V_x$/$V_y$ summary and directional details'],
           ["Torsion", 'Selected Plastic case: torsion resistance and utilization'],
           ["M-V-T Combined", "Selected Plastic case: combined interactions"]])
    h2("Report workspace")
    md('Enter the project number, project name, section, revision, author, optional Checker and Approver names, and comments. Select **Brief**, **Standard** or **Audit**. Sector shows Checker and Approver only when you supply them. These fields identify document roles. \n\nSector uses Analysis results for the report if they match the current inputs. If they are different, Sector recalculates the results. \n\nAfter a project-detail or input edit, Sector marks the existing PDF out of date. Regenerate the PDF before download.')
    md('Under **Project and action references**, select Project assumptions or an exact named case/spectrum, then enter the document or record identifier and section/page locator. \n\nThe PDF identifies user-supplied references and calculation-method citations in different groups. Missing locations stay explicit in the PDF. \n\nAn unmatched reference stays saved after a case rename. Select it and clear the two fields to remove it. Project references do not automatically apply to each action.')
    call("tip", 'Report details and publication controls are in **Report**. Save/load and autosave are in **Inputs > Project > Save / Load**.')
    call("tip", '*Auto-calc all derived values* is in Material parameters. It calculates these quantities from the current grade:\n\n- Concrete strain limits.\n- $f_{ctm}$.\n- $E_c$.\n\nSector calculates the modular ratios from $E_c$, $E_s$, $E_p$ and creep.')

    h1("Project")
    h2("Project files and autosave")
    md('**Loaded-project messages.** **Saved-file input record: matches** means that the file agrees with its stored input record. **Inputs match the recorded calculation** means that those inputs also agree with the recorded calculation inputs. The two messages check different records. If the records are different, examine the loaded inputs and calculate again.')
    md('Sector shows the recorded saving version and calculation time when these are available. If Sector rejects a new file, it keeps the current project unchanged. Select a different compatible project file with no damage. If invalid current inputs disable the project download, correct the displayed input issue before you save.')
    md('Open **Inputs > Project**. Expand **Save / Load**. To save the inputs, select **Download project**. To restore inputs, select a saved file under **Load project**.\n\nA downloaded project file stores the section, materials, settings, named load cases and saving information. When you load a project, Sector restores its inputs and clears earlier results.\n\nExamine the restored inputs. Before you use or report the results, open **Analysis**. Select **Calculate**.')
    md('Open **Inputs > Project**. Expand **Save / Load**. Use **Autosave** for local recovery.\n\nThe default interval is five minutes. Set **Autosave interval (min)** from 1 to 120 minutes. A due save runs on the next interaction if the inputs are different from the last saved inputs. The panel shows the last save time.')
    md('Sector restores the recovery file on the next launch. An explicitly loaded project takes precedence. Examine the restored inputs. Open **Analysis**. Select **Calculate**. Save the project file used for each issued report.')
    md('The Windows executable usually stores recovery data in **%LOCALAPPDATA%/Sector/autosave.json**. A source installation uses **%USERPROFILE%/.sector/autosave.json**. An installation can specify a different recovery folder. If automatic recovery fails, load a saved project file with no damage through **Inputs > Project**.')
    h1("Defining the section")
    md('A section is a set of points in millimeters: concrete corners, voids, bars and tendons. Sector calculates from these point tables. Quick Section updates these tables when you apply its geometry.')
    h2("The point tables")
    md("**Add or delete a row.** Select **+ Add row** to append an input row. "
       "Use a row's **Delete row** control to remove it. Sector assigns the reinforcement IDs. "
       "The IDs of the remaining reinforcement elements stay unchanged.")
    md("**Paste point data**\n\n1. Copy a rectangular block of data without its column headings or ID column.\n2. Before compact reinforcement-area paste, set each target row's size basis to **Area**.\n3. Select the first target row in the point table.\n4. Paste the block.\n5. Examine the changed rows and section preview.\n\nUse the editable columns in their displayed order. For bars and tendons, the compact form is $x$, $y$ and area. For concrete and void corners, enter the $x$ and $y$ columns. A full-column reinforcement paste includes the required size basis.\n\nThe paste starts at the selected row. It replaces the supplied fields in existing rows and appends additional rows when necessary. Other editable fields stay unchanged.\n\nDerived area or diameter follows the selected size basis. In **Diameter** mode, Sector calculates area from diameter and replaces a pasted area. An incompatible column count gives a warning and leaves the table unchanged.")
    md('Four editable tables hold the concrete corners, the voids, the bars and the tendons. Coordinates and diameters are in millimeters. Areas are in square millimeters. Each reinforcement element has a fixed ID used by the figures, results and report. IDs stay unchanged when other rows are deleted.')
    table(["Size basis", "Entered", "Calculated"],
          [["Area", "Area", "Equivalent circular diameter"],
           ["Diameter", "Diameter", "Area of one circular element"],
           ["Independent", "Area and diameter", "Neither"]])
    md('Area controls section stiffness and resistance. Diameter controls detailing and crack-spacing geometry. Use *Independent* when one point represents a non-circular or grouped steel area.\n\nMaterial and fatigue-detail IDs stay assigned to the element. Use **Bulk assignments** above a reinforcement table to update all or selected IDs.\n\nWhen reinforcement fatigue is enabled, assign a fatigue detail to each bar and tendon. With reinforcement fatigue disabled, this assignment is optional. Sector uses a row only when it contains all necessary values.')
    md('**Add a void**\n\n1. Under **Concrete voids**, select **+ Add void**.\n2. Enter three or more corners in boundary sequence after the blank separator row.\n3. Examine the void in the section preview.\n\nYou can add up to ten voids. **Remove void** deletes the last void in the table.')
    md('**Clear the section**\n\n1. Select **Clear section...**.\n2. Select **Confirm clear** to remove all concrete, void, bar and tendon points.\n\n**Cancel** keeps the points. **Undo clear** restores the last cleared tables and their applied builder settings. This recovery stays available until you enter new section points.')
    md('**Preview labels.** **Label size** scales the corner, bar and tendon number labels from 0.5 to 3.0. **Label spacing** hides labels closer than the selected fraction of the section size. Enter 0 to show each label. These controls change the drawing labels.')
    call("concept", "The builder, presets and loaded projects populate these four point "
         "tables. You can edit the geometry directly in the tables.")
    md('**Assign a group of elements**\n\n1. Open **Bulk assignments** above the bar or tendon table.\n2. Under **Apply to**, select **All elements** or **Selected elements**.\n3. For selected elements, choose the required **Element IDs**.\n4. Select the **Material** and **Fatigue detail** assignments.\n5. Select **Apply assignments**.\n\n**No change** keeps that assignment. **Clear assignment** removes the fatigue detail from the selected elements. When reinforcement fatigue is enabled, assign a valid fatigue detail to each checked element before calculation.')
    h2("The Quick Section builder")
    md('**Apply or leave the builder.** **Apply to point tables** replaces the current concrete, void, bar and tendon tables with the previewed section. Save the current project first if it must stay available. Before you apply the section, examine the preview and dimensions. **Back** leaves the current point tables unchanged.')
    md("**Slab rows and physical bars.** Generated slab-density rows represent the specified reinforcement area per meter. "
       "If edits break that relationship, Sector marks the density layout **UNVERIFIED**. "
       "Reapply the slab layout to restore its density basis.")
    md('To use a physical bar arrangement, first replace the generated rows with the actual bar coordinates and sizes. Then select **Use current bars as explicit layout** when the control is available. Examine the reinforcement area and spacing before calculation. The explicit layout uses the entered physical bars.')
    md('Open **Quick Section** from the **Section** panel. Select the shape. Enter its dimensions. The preview updates when an input changes.')
    md('Select reinforcement by bar count or spacing. Enter the reinforcement for each layer. Enter the cover and bar diameter for each face. Select the cover measurement: bar edge or bar center.')
    md('Top and bottom faces can use different diameters and covers. A top layer can use a different bar count. Where the shape supports the arrangement, tendons can form a ring or different layers.')
    md('For the **1 m slab strip**, diameter and spacing define the reinforcement area per meter:\n\n$A_s=A_{bar}\\,1000/s$.\n\nFor 20 mm bars at 200 mm centers:\n\n$5A_{bar}=1570.796\\,\\mathrm{mm^2/m}$.\n\nThe top or bottom cover defines the layer depth.')
    md('An interleaved diameter adds a full second series at half-spacing positions. The builder shows each series and the total area for each layer and face.')
    md('With edge cover, each series uses its own diameter to keep the specified clear cover. Mixed sizes can thus have different center lines. With center cover, the two series use the entered center line. Sector rejects a bar envelope that crosses a concrete face.')
    md('For finite sections, the entered spacing defines the maximum gap over the covered face. The builder shows the calculated count and actual center-to-center spacing.')
    md('Sector places slab-strip bars symmetrically: at 100 mm centers, a 1 m strip contains ten bars per layer with 50 mm edge offsets. Symmetric edge-area weights keep the specified steel area per meter when the spacing does not divide the strip width exactly. Clear-spacing and crack-width calculations use the nominal spacing and face cover. The strip sides are not physical concrete edges.')
    fig(fig_slab_spacing_cover, 'Nominal bars in a one-meter strip with an interleaved series. Each series has its own row. The dashed outer lines mark strip cuts. Short dotted lines mark tributary boundaries. Each boundary bar has a 16 mm diameter and half-area weight. The two cover details use the same scale and full physical bar diameters.', 'The 20 mm bar row has five axes at 200 mm spacing. The 16 mm bar row has six axes offset by 100 mm, with a half-area axis at each strip cut. Below, equal-scale details compare 20 mm edge cover with 30 mm center cover for the two bar sizes.')
    md('The 20 mm bar row contains five full-bar areas: $1570.796\\,\\text{mm}^{2}$. The 16 mm bar row contains four full weights and two half weights: $1005.310\\,\\text{mm}^{2}$.\n\nA half weight changes the analytical area assigned to that axis. The physical diameter stays 16 mm.\n\nWith 20 mm edge cover, the centers of the 20 mm and 16 mm bars are 30 and 28 mm from the face. With 30 mm center cover, their clear covers are 20 and 22 mm.')
    table(["Shape", "Produces"],
          [["Rectangle", 'A solid rectangle $b\\times h$'],
           ["Slab strip", "A 1 m-wide strip of a given thickness"],
           ["Trapezoid", 'Bottom width, top width and overall height. Centered horizontal faces'],
           ["T-section", 'Flange width and thickness. Web width and depth outside the flange. Overall depth is $h_f+h_w$. Select the flange at top or bottom.'],
           ["L-section", 'Overall width and height. Left-web and bottom-flange thicknesses'],
           ["I-section", 'Equal flange widths and thicknesses. Web width and clear height between flanges. Overall depth is $h_w+2t_f$.'],
           ["U-section", 'Overall width and height. Common side-web thickness and base thickness'],
           ["Box girder", 'Outer width and height. Uniform wall thickness defines the rectangular void'],
           ["Circular", 'Outer diameter. A 48-sided polygon represents the concrete boundary'],
           ["Annulus", 'Outer and inner diameters. Two 48-sided polygons represent the boundaries']])
    md("**Tendon placement.** **Tendons** sets the number in a row or circular ring. "
       "**Area per tendon** specifies one tendon's area. **Tendon cover** locates its center from the concrete face. "
       "For stacked rows, **Tendon layers** sets the number of rows. **Tendon layer spacing** is the vertical center-to-center distance.")
    md('Circular and annular sections place tendons on a ring and ignore the layer count. T and I sections use the available width at each layer. Box sections divide placement across the concrete portions beside the void. The preview identifies an arrangement that cannot fit the concrete. Examine it before you apply the section.')
    md('Trapezoid, L-section and U-section apply their concrete geometry only: automatic face reinforcement is not defined for those non-uniform or split faces. Add their bars and tendons directly in the point tables. The T-section, I-section and annulus give bounded automatic placement. The builder rejects dimensions, layers or rings that create invalid geometry or put a generated point outside concrete.')
    h2("Validity checks")
    md('Sector checks the geometry before calculation. Each outer or void ring must have:\n\n- Finite numerical coordinates.\n- Three or more distinct points.\n- An area larger than the numerical tolerance.\n- Edges that form one simple closed boundary.\n\nSector rejects repeated or tolerance-coincident vertices. It also rejects non-adjacent edge crossings, contacts and overlaps. An adjacent edge must not reverse along the same line.\n\nForward collinear points are permitted. The last point can equal the first point. Clockwise and counter-clockwise sequences are valid. Sector keeps the entered order and uses oriented copies for integration.')
    md('Each void must be strictly inside the outer ring. It must not touch the outer boundary or a different void. A void must not contain a different void.\n\nThe net concrete area must stay connected. Each bar and tendon must be in concrete. Sector identifies the first geometry error and its ring, point or edge.')
    call("concept", 'The length tolerance is the greatest of **1e-12 m**, **1e-9 times the section span** and **8 ULP of the coordinate magnitude**. ULP is the spacing between adjacent representable coordinate values. Validation keeps the entered coordinate values unchanged. Geometry validation and calculation convergence have different acceptance criteria. A valid section can have a calculation that fails to converge.')
    call("limit", 'A void must keep the concrete in one connected piece. Sector rejects a slot that splits the section into two pieces. The plane-section assumption is applicable to one connected section.')

    field_guides(table_fields.TABLE_KEYS[:4])

    h1("Materials")
    md('**Catalog controls.** Select the required material definition before you edit it. **Add** creates a definition. **Duplicate** copies the selected definition. You can use **Delete** only if a different definition is available. Before deletion, assign a different definition to each affected element and to the member-check reference, where applicable.')
    md('When you select a different preset, Sector replaces the starting values supplied by that preset. Examine the resulting values and curve before calculation. Fixed tendon curves show only their applicable editable parameters. General tendon curves show the parameters of their full stress-strain law.')
    md('Concrete has one definition. Reinforcing steel and prestress use catalogs: each definition has a unique ID, name and optional description. Add, duplicate or delete definitions in the material panel. Then assign the ID to each bar or tendon in the Section table. An assigned definition cannot be deleted. A preset supplies starting values for the selected definition. You can change the applicable editable fields.')
    call("limit", 'Enter the **final effective** material partial factors in the material panels. Include each applicable national increase or reduction for construction, control and consequence category. Sector applies the entered factors directly.')
    h2("Concrete")
    md('Select the concrete stress-strain **Preset**. **Curve 2 (parabola-rectangle)** supplies the EC2 design law used in the worked examples. **Curve 1 (cubic)** supplies a project-defined curve for normal-strength concrete.\n\nEnter characteristic strength $f_{ck}$, partial factor $\\gamma_c$ and coefficient $\\alpha_{cc}$. Enter strain limits $\\varepsilon_{c2}$ and $\\varepsilon_{cu2}$, with exponent $n$. Also enter elastic modulus $E_c$ and mean tensile strength $f_{ctm}$.\n\nThe strain limits, $E_c$ and $f_{ctm}$ have **Auto** buttons. These buttons calculate values from the current $f_{ck}$ and selected edition.')
    call("standard", 'For DS/EN 1992-1-1:2023, Sector calculates the effective coefficient $\\eta_{cc}k_{tc}$. This coefficient is read-only. Sector also shows $k_{tc}$.\n\nThe default is **0.85** (general / other cases). Select **1.00** only if the conditions in 5.1.6(1) apply. These conditions include the reference age and a delay of three or more months before design loading. The PDF records this assumption.')
    fig(fig_beam_concrete_law, "The concrete-law preview for the rectangular "
        "example (C40/50).",
        'A compression stress-strain curve that increases parabolically from zero to the design strength and then stays horizontal to the ultimate strain.')
    h2("Reinforcing steel")
    md('Each reinforcing-steel definition uses the general **Curve 3** law. All parameters stay editable. The generic **Curve 1**, **Curve 2** and **Curve 3** selections supply project-defined starting values.')
    md('An edition-named selection supplies a **Eurocode design stress-strain diagram** and records its source. Sector uses the numerical values shown in the input fields. The plot beside the fields shows the selected definition.')
    md('Enter the yield strength, ultimate strength, ultimate strain and partial factors. Enter the yield offsets, first-yield ratio and modulus $E_s$. Part D defines each parameter in the implemented material law.')
    md('**Active in compression (plastic)** controls compression resistance in the plastic calculation. When this option is off, the plastic steel law carries tension only. The elastic calculation uses linear elastic steel in tension and compression.')
    fig(fig_beam_steel_law, "The B550 mild-steel law for the rectangular example.",
        "A symmetric reinforcing-steel stress-strain curve with linear tension and "
        "compression branches to yield followed by the selected post-yield response.")
    call("standard", 'Edition-named concrete and steel presets have their selected Eurocode source (3.1.7 / 3.2.7 for the 2005 family). Generic named curves and custom/imported laws stay project-defined and uncited.')
    h2("Prestressing steel")
    md('Each prestress definition contains a tendon law and an initial strain **IS**. Sector adds the initial strain to the section strain at the tendon. The material law uses this total strain. The preview marks the initial-strain point on the tendon curve.')
    call("concept", 'Plastic capacity, cracked-elastic stiffness and stress, and crack calculations use the material assigned to each element.\n\nShared member checks for shear and torsion use the selected mild-steel reference material. Sector shows its ID with those settings and results.')
    fig(fig_circular_prestress_law, "The tendon law for the circular example.",
        'A prestressing-steel stress-strain curve with an initial elastic branch and a nonlinear branch to design strength and ultimate strain.')

    h1("Analysis & result settings")
    h2("Analysis mode")
    md('**Bending analysis** selects **Plastic** (nonlinear M-M capacity), **Elastic** (cracked-section stresses), or **Both**. Record the project limit-state classification in each action-set name, source or note.')
    h2("The plastic sweep")
    md('Sector traces the envelope while it rotates the neutral axis from $V_{min}$ to $V_{max}$. The entered $V_{inc}$ is the maximum increment in degrees. Sector uses equal steps that include the two limits. Thus, the actual increment can be smaller. Each angle gives one point on the $M_x$-$M_y$ envelope at the design axial force. \n\n**Check utilisation against applied moment** compares the applied moment with the envelope. If you disable this option, Sector reports the capacity only.')
    fig(fig_beam_envelope, "The rectangular example's biaxial envelope with the applied load. The sweep from 0 to 360 degrees closes the curve.",
        'A closed $M_x$-$M_y$ capacity boundary around the origin with one applied-load point. Each boundary vertex is the result for one neutral-axis orientation.')
    h2("Reinforcement detailing")
    md('Select **Beam** or **Slab**. **Section cut direction** fixes the member-relative reinforcement direction represented by the section model. Detailing checks use the bars in that modeled cut.')
    table(["Section cut", "Modelled reinforcement direction"],
          [["Transverse cut", "Longitudinal"],
           ["Longitudinal cut", "Transverse"]])
    md("In words, a transverse cut models the Longitudinal reinforcement, while "
       "a longitudinal cut models the Transverse reinforcement.")
    md("The optional **Project direction alias** records local terminology, for "
       "example *span direction*. It is published after the standard Longitudinal "
       "or Transverse label and changes presentation only.")
    md('Enable **Check minimum reinforcement in modelled direction**. Select the check on each required Plastic/capacity row. Sector uses the selected detailing edition and global $f_{ctm}$ for those rows.\n\nThe secondary-direction slab minimum depends on primary reinforcement outside the modeled cut. Sector thus reports its 20% criterion as **NOT ASSESSED**.\n\nEnable **Check reinforcement clear spacing**. Enter $D_{upper}$. Sector checks the included element pairs across the section. To include tendons, select the tendon option. Enter the detailing-envelope diameter or duct diameter for each included tendon.')
    md('Enable **Check shear/torsion link detailing**. Sector checks each case with nonzero shear or torsion. It uses the shared stirrup diameter, longitudinal spacing and yield strength.\n\nFor each shear direction, enter the maximum transverse distance between effective legs. A value of zero selects the gross-web upper-bound check. If this upper bound satisfies the spacing limit, the spacing check passes. If the upper bound is larger than the limit, enter the actual maximum distance between legs.\n\nFor the 2023 edition, select the reinforcement ductility class. Select the minimum-ratio reduction only when it applies. The 2023 method uses the calculated link requirement. For a beam with $d>500$ mm and no calculated link requirement, the structural-system condition in 8.2.1(2) stays **NOT ASSESSED**.\n\nUnder the 2005 method, minimum links are necessary for an ordinary beam with nonzero shear. For a slab, omission of links depends on the verified resistance without links. Sector compares the provided links with each applicable requirement. An insufficient provided value gives **FAIL**.')
    table(["Member", "Vertical shear-link spacing limits"],
          [["Beam", '$s_l \\leq 0.75d$. $s_t \\leq \\min(0.75d,600\\,\\text{mm})$'],
           ["Slab", '$s_l \\leq 0.75d$. $s_t \\leq 1.5d$']])
    md('Measure $s_t$ in the section plane between adjacent parallel link legs:\n\n- Along $y$ for $V_x$.\n- Along $x$ for $V_y$.\n\nThe longitudinal spacing is $s_l$. Keep the closed-stirrup height unchanged.')
    call("standard", "EN 1992-1-1:2005 9.2.3(4)'s 350 mm value applies to "
         "longitudinal torsion bars around the link perimeter, not to spacing "
         "between closed links.")
    table(["Edition", "Minimum-reinforcement method"],
          [["EN 1992-1-1:2005 / DK NA:2024",
            "$A_{s,prov} \\geq A_{s,min}$ in the resultant bending-tension zone (9.1N)"],
           ["DS/EN 1992-1-1:2023",
            "Nominal section resistance at characteristic bar yield compared with the cracking action (12.1/12.2)"]])
    call("limit", 'The minimum-reinforcement check uses ordinary bars. Complete the DK NA side-face reinforcement check for high beam webs and the lap-length and bundle checks independently.\n\nThe minimum-reinforcement calculation assumes that ordinary bars have sufficient anchorage for the entered $f_{yk}$. Where the anchorage cannot resist that force, reduce $f_{yk}$.')
    h2("Crack width")
    md('**Bonded-tendon ratio** $\\xi$ is the tendon-to-ribbed-reinforcement bond-strength ratio for the 2023 mixed-reinforcement crack calculation. Enter the applicable value when the section combines ordinary reinforcement and bonded tendons. Zero leaves the ratio unspecified. First-generation crack methods save this value for use with the 2023 basis. Fatigue uses its own bond ratio, assigned through each tendon fatigue detail.')
    md("For each applicable Elastic table row, select **Crack width**. The global crack settings apply to each selected row.\n\nEnter the diameter override $\\phi$, or use 0 to select each element's table diameter. **Area** mode calculates diameter from area. Enter the ordinary-steel bond coefficient $k_1$: 0.8 for ribbed reinforcement or 1.6 for plain reinforcement. Select the code edition. For DK NA, also select the member type.")
    table(['Crack-width design basis', "What it changes"],
          [["EN 1992-1-1:2005", "The base EC2 model (7.3.4): $s_{r,max}$ from 7.11 / 7.14"],
           ["DS/EN 1992-1-1 + DK NA", 'Cover-dependent $k_3$ and the $(h-x)/3$ term for slabs / prestressed only. Reports the fine and coarse crack systems (the coarse: centroid-matched effective area, fig 7.100 NA, $w_k$ halved)'],
           ["DS/EN 1992-1-1:2023", "The refined model (9.2.3): $w_k = k_w\\,(k_1/r)\\,s_{r,m,cal}\\,(\\varepsilon_{sm}-\\varepsilon_{cm})$"]])
    call(
        "standard",
        'For each Elastic row with crack width enabled, Sector reports four DK NA crack widths:\n\n- Fine system, long-term actions.\n- Fine system, short-term actions.\n- Coarse system, long-term actions.\n- Coarse system, short-term actions.\n\nAnalysis settings have a user limit for each duration. A zero limit gives the calculated width without a limit comparison. A positive limit gives a comparison for that duration.\n\nSelect the limits and action classifications specified by the project basis. Part C gives the methods and worked examples.',
    )
    md('For the first-generation Danish basis, **DK heightened crack-control minimum** is an optional check.\n\nDeclare its applicability. Supply these inputs for Formula (7.100 NA):\n\n- Permitted width.\n- Reinforcement surface.\n- Effective tensile strength.\n- Effective tension area for the fine system.\n- Effective tension area for the coarse system.\n\nSector calculates the two systems together. It gets bar diameter, reinforcement modulus and provided area from one ordinary crack-width Elastic case.\n\nIf only one case is eligible, Sector selects it automatically. If more than one case is eligible, select the case.')
    h2("Grouped fatigue")
    md('1. Enable **Fatigue analysis**.\n2. Select the fatigue edition.\n3. Enable **Reinforcement**, **Concrete**, or the two options.\n4. Enter the effective project factors $\\gamma_{Ff}$, $\\gamma_s$ and $\\gamma_{c,fat}$.\n\nInclude the applicable control-, construction- and consequence-class effects in these factors.')
    md('Under **Concrete fatigue method**, select one of these methods:')
    md('- **Explicit Palmgren-Miner spectrum** uses the cycle count in each spectrum bin.\n- **Damage-equivalent stress amplitude** uses an action pair that represents an equivalent amplitude for $10^6$ cycles. Sector ignores the entered cycle count for this concrete check.\n- **User-defined Miner S-N relation** uses the entered cycles and coefficient $C$ in the project-defined concrete fatigue-life relation.')
    md('For the user-defined relation, record the coefficient and governing source with the project inputs. Sector identifies this relation as project-defined in the calculation record. Part C gives the fatigue-life equations and acceptance criteria.')
    table(["Input", "Use"],
          [["$\\gamma_{Ff}$", "Factors the cyclic action increment before the elastic solve"],
           ["$\\gamma_s$", "Reduces the reinforcement S-N resistance and yield/proof limit"],
           ["$\\gamma_{c,fat}$", "Reduces the concrete fatigue strength"],
           ["$\\beta_{cc}(t_0)$, $t_0$", "Concrete strength at the start of cyclic loading"],
           ["$k_1$, $C$", '2005 concrete-strength coefficient. C applies to the explicit and user-defined concrete fatigue-life methods']])
    md("The **Fatigue details** material tab holds named resistance definitions. Assign one detail ID to each checked bar or tendon. Standard presets lock $N^{*}$, the two S-N slopes, the characteristic reference range and its source. Custom / imported makes them editable. Sector applies the diameter-dependent and bent-bar reductions specified by the selected preset. If the section has mild reinforcement and bonded tendons, enter the bond ratio $\\xi$ for each tendon. Also enter each tendon's equivalent diameter.")
    md('**Create or change a fatigue detail**\n\n1. Open **Inputs > Material parameters > Fatigue details**.\n2. Select **Add mild** for reinforcing steel or **Add tendon** for prestressing steel.\n3. Enter the detail name.\n4. Select its preset.\n5. Examine the displayed parameters and source.\n6. Under **Inputs > Section**, assign the detail ID to the applicable reinforcement elements.\n\n**Duplicate** copies the selected detail to a new definition. **Assigned elements** shows its current use. **Delete** is available when the detail is unassigned and a different detail is available.')
    md('The **Spectrum basis** records the selected grouped-spectrum method and optional action-set notes. Sector uses each action and cycle count as entered. The project spectrum supplies the traffic coverage and route assumptions.')
    md("**Resistance preset** includes straight bars, bent bars, welded bars or fabrics, steel couplers, pretensioning and bonded tendon details. "
       "Tendon families distinguish plastic ducts, curved tendons in steel ducts, and coupler or anchorage details. "
       "Select the family and edition that apply to the physical detail.")
    md('Select **Custom / imported** to edit the resistance definition. Set **Element type** to mild reinforcement or prestressing tendon. Enter the reference cycles, characteristic stress range and the two S-N exponents. **Reference-range model** selects a fixed range or the applicable 2023 diameter-dependent range.')
    md("For a bent-bar detail, enter the mandrel diameter used by its reduction. For mixed ordinary and prestressing reinforcement, enter the tendon's **Bond ratio** and **Equivalent tendon diameter**. A zero bond ratio leaves the required property unspecified. Examine the resulting input warning before assessment.")
    md("**Resistance source** records the standard, clause or project source for the fatigue detail. "
       "The **Description** field identifies its physical arrangement. "
       "Action references belong to the spectrum or action record under **Report > Project and action references**.")
    md('The concrete fatigue age $t_0$ records the start of cyclic loading. Also enter the related strength-development factor $\\beta_{cc}(t_0)$. The 2023 strength expression does not use the 2005 coefficient $k_1$. The damage-equivalent route does not use the fatigue-life coefficient $C$.')
    table(["Fatigue edition", "Implemented resistance basis"],
          [["DS/EN 1992-1-1:2005",
            'Steel 6.8.4 and Tables 6.3N/6.4N. Concrete 6.72 equivalent method or corrected DS/EN 1992-2 6.106 Miner method'],
           ["DS/EN 1992-1-1:2005 + DK NA:2024",
            'Same calculation models, with the full Danish project factors entered explicitly'],
           ["DS/EN 1992-1-1:2023",
            'Reinforcement Annex E.5 and Tables E.1/E.2. Concrete E.2 equivalent method or E.7-E.8 Miner method']])
    call("limit", 'Sector calculates each named spectrum independently. Enter traffic cycles, dynamic allowance and lane/track concurrence in the project spectrum. The implemented fatigue scope covers normal force and bending.')
    h2("Shear capacity settings")
    md('With **Check shear capacity** on, Sector calculates the design shear resistance $V_{Rd,c}$ of a member **not** requiring shear reinforcement (EN 1992-1-1 6.2.2) in each active direction. Enter signed $V_{x,Ed}$ and $V_{y,Ed}$ in each Plastic/capacity row. Zero disables only that component.')
    table(["Component", 'Geometry and related bending'],
          [["$V_{x,Ed}$", 'Along x. Depth in x. Left/right faces. Paired with $M_{y,Ed}$'],
           ["$V_{y,Ed}$", 'Along y. Depth in y. Bottom/top faces. Paired with $M_{x,Ed}$']])
    md('Face selection is **Auto** by default. Sector transfers the related moment to the concrete centroid and includes the locked tendon moment.\n\n- A positive adjusted moment selects the negative-coordinate face.\n- A negative adjusted moment selects the positive-coordinate face.\n- At zero adjusted moment, Sector evaluates the two faces.\n\nSector selects the governing face independently for shear, V+T and combined checks. The result identifies the face and applicable strut angle. You can override the face in the action row. The bending moment selects the tension face independently of the shear sign.\n\nWeb-width overrides and effective link-leg counts apply independently to each direction. Method, aggregate and stirrup properties apply to the two directions.')
    fig(fig_directional_shear_faces, 'Directional shear geometry for a 300 by 600 mm rectangle with positive adjusted bending moments. Filled circles identify the selected longitudinal bars. The vertical shear uses the bottom bars and a 550 mm effective depth. The horizontal shear uses the left bars and a 250 mm effective depth.', 'Two equal-scale section views pair vertical shear with bending about the x axis and horizontal shear with bending about the y axis. The first view measures effective depth from the top compression edge to the bottom bar centers. The second measures it from the right compression edge to the left bar centers. The selected web widths are 300 and 600 mm.')
    call("limit", 'When the two shear components are nonzero, Sector calculates one check for each direction. With torsion, Sector calculates one $V+T$ check for each direction.\n\nFor simultaneous $V_x+V_y$ or $V_x+V_y+T$ interaction, do a member check independently of these directional checks.')
    md('Where torsion is active, the report shows the directional Formula (6.31) condition for $V_x+T$ and $V_y+T$. This condition identifies the cases where designed shear-and-torsion reinforcement beyond the required minimum is necessary. \n\nEach link minimum-ratio and spacing check has its own result. Their states are **PASS**, **FAIL**, **NOT RUN** or **NOT ASSESSED**. Do engineering checks of the arrangement and anchorage independently of the section calculation.\n\nSector calculates Formula (6.31) only for approximately solid rectangular sections with the first-generation $V_{Rd,c}$ method. For hollow, circular, triangular, flanged or compound sections, use the full shear-and-torsion checks.\n\nFor the 2023 shear method, assess shear with the 2023 check. Assess torsion and interaction with their selected methods. Formula (6.31) is unavailable for that combination.\n\nWhen $N_{Ed}$ or $M_{Ed}$ acts under the Danish National Annex, use the DK NA 6.3.2(6) combined N-M-V-T check. Its verdict includes the applicable concurrent actions.')
    table(["Shear method", "What it sets"],
          [["EN 1992-1-1:2005", "$C_{Rd,c} = 0.18/\\gamma_c$, $k_1 = 0.15$, "
            "$v_{min} = 0.035\\,k^{1.5}\\sqrt{f_{ck}}$"],
           ["DS/EN 1992-1-1:2005 + DK NA:2024", "2005 method with the raised $v_{min} = (0.051/\\gamma_c)\\,k^{1.5}\\sqrt{f_{ck}}$"],
           ["DS/EN 1992-1-1:2023", 'The strain-based $\\tau_{Rd,c}$ method (8.2.2) uses $d_{dg}$ and the selected $\\gamma_V$ (default 1.40). It applies while $|V_{Ed}|\\leq V_{Rd,c}$, with or without links. For greater demand, the compression-field method (8.2.3) applies.']])
    md('Select the **shear section form** independently of the polygon. Automatic geometry applies to a solid rectangle. For a non-rectangular constant-width web, enter the governing $b_w$.\n\nFor the 2023 links method, reinforcement inclination is necessary for a variable-width web: $\\delta$ in each active direction. For a circular section, supply hoop diameter $D_h$ and the lever arm $z$ from the fitted section. These section-form rules apply to the 2023 method. With a first-generation method, Sector reports **NOT ASSESSED** and an applicable member calculation is necessary.')
    md('**Duct allowance for the 2023 method**\n\nThe allowance applies when $\\sum\\phi_{duct}>b_w/8$:\n\n- Grouted steel ducts: $k_{duct}=0.5$.\n- Grouted plastic ducts with a confirmed thin wall: $k_{duct}=0.8$.\n- Thick-wall plastic, ungrouted or soft-filled ducts: $k_{duct}=1.2$.\n\n**Duct allowance for the 2005 links method**\n\n- For grouted steel, use $k_{duct}=0.5$ when the largest $\\phi_{duct}>b_w/8$.\n- For plastic, ungrouted or unbonded ducts, use $k_{duct}=1.2$.\n\nIf no ducts are selected, Sector keeps the full web width.')
    md('When the duct size is greater than the applicable threshold, use this compression-field width:\n\n$b_{w,nom}=b_w-k_{duct}\\sum\\phi_{duct}$.\n\nThe 2023 no-links check applies this allowance only to ungrouted or soft-filled ducts. The 2005 no-links check stays unchanged.\n\nFor the selected branch, Sector must have each applicable web, hoop, fitted-section, inclination and duct dimension. A missing dimension gives **NOT ASSESSED**.')
    call("standard", '**2023 shear factor**\n\nDS/EN 1992-1-1:2023, 4.3.3 and Table 4.3 (NDP), specify $\\gamma_V$ for shear resistance without shear reinforcement. The input starts at 1.40. Select the positive value specified by the project basis. Clause 8.2.2 uses that value.\n\n**Resistance without shear reinforcement**\n\nFormula (8.27) gives:\n\n$\\tau_{Rd,c} = (0.66/\\gamma_V)(100\\rho_l f_{ck} d_{dg}/d)^{1/3} \\geq \\tau_{Rd,c,min}$.\n\nThe aggregate term is $d_{dg} = 16 + D_{lower}$, with a maximum of 40 mm under 8.2.1(4). The method uses the flexural design yield strength $f_{yd}$.\n\n**Axial-force adjustment**\n\nWhen axial force is nonzero, Sector replaces $d$ with $k_{vp}d$ in Formula (8.27). Formulas (8.30)-(8.31) give:\n\n$k_{vp}=\\max[1+N_{Ed}/|V_{Ed}|\\,d/(3a_{cs}),0.1]$.\n\n$a_{cs}=\\max(|M_{Ed}/V_{Ed}|,d)$.\n\nThe actions include locked-in prestress. The section model assumes that tendons are parallel to the member axis, so $\\cos\\beta=1$.\n\n**Selection of the resistance method**\n\nWhen links are entered, Sector uses the selected $\\gamma_V$ wherever the 8.2.2 concrete route applies. For a demand larger than that resistance, Sector uses the compression-field method in 8.2.3. Torsion and the combined lock stay on the 2005 family.')
    call("limit", '$A_{sl}$ is the tension-face bars, **assumed fully anchored** ($\\geq l_{bd} + d$). Make sure that the member design satisfies the anchorage conditions. Where anchorage cannot resist the force, reduce $f_{yk}$ / $f_{ywk}$ to the strength that the anchorage can resist.')
    call(
        "limit",
        "The full compression-strut interval must be inside each active method's permitted range. The 2005 family and 2023 class B/C use $1.0\\leq\\cot\\theta\\leq2.5$. The 2023 upper limit decreases to 2.0 for class A. Axial tension can also decrease it under 8.2.3(4).\n\nExact boundaries are permitted. An interval outside the applicable range gives **NOT ASSESSED** for linked shear, torsion and dependent interactions. An applicable concrete-only $V_{Rd,c}$ route stays independent.",
    )
    md('With **Shared links / closed torsion stirrups present** on, Sector keeps $V_{Rd,c}$ as nominal resistance while $|V_{Ed}|\\leq V_{Rd,c}$. Above that boundary, the designed-link resistance $V_{Rd}=\\min(V_{Rd,s},V_{Rd,max})$ becomes the nominal route, under 6.2.3 or 8.2.3. Minimum reinforcement and link spacing each have their own check.\n\nUnder **Links / stirrups**, enter the effective legs for each direction and the bar diameter. Enter longitudinal spacing $s$ and link yield strength $f_{ywk}$. The link area is $A_{sw}=n_{legs}\\pi\\phi^2/4$. Enter the common bounds $\\cot\\theta_{min}$ and $\\cot\\theta_{max}$.\n\nA capacity-only check selects the greatest resistance in that range. For loaded member checks, Sector selects one angle that gives the lowest governing utilization.')
    call("standard", '**Permitted strut angle**\n\nEN 1992-1-1, Formula (6.7N), gives:\n\n$1 \\leq \\cot\\theta \\leq 2.5$.\n\nDK NA:2024, Formula (6.7a NA), gives the same range for class B/C steel.\n\n**Concrete-strut factor**\n\nThe DK NA factor is:\n\n$\\nu_1 = \\nu_v = 0.7 - f_{ck}/200 \\geq 0.45$.\n\nThis is Formula (5.103 NA). The recommended Eurocode factor is:\n\n$\\nu = 0.6(1 - f_{ck}/250)$.\n\n**Results outside the permitted range**\n\nYou can enter bounds outside the code range for exploration. For these bounds, Sector withholds the code verdict for links and each dependent interaction check.')
    call("standard", '**2023 link resistance**\n\nDS/EN 1992-1-1:2023, Formula (8.42), gives:\n\n$\\tau_{Rd,sy}=\\rho_w f_{ywd}\\cot\\theta$.\n\nFormula (8.44) limits the concrete compression stress:\n\n$\\sigma_{cd}=\\tau_{Ed}(\\cot\\theta+\\tan\\theta)\\leq\\nu f_{cd}$.\n\nThe concrete factor is $\\nu=0.5$.\n\n**Angle bounds**\n\nThe maximum cotangent is 2.5 for class B/C without axial tension. Class A and axial tension decrease that maximum under 8.2.3(4). Part C gives the calculation sequence and the lower bound.\n\nThe section check uses a maximum of 2.5. Before you use 3.0, do a member assessment of the condition $x<0.25d$.')
    h2("Torsion capacity settings")
    md("**Reference reinforcing material** selects the steel law used for the shared shear and torsion member checks. It supplies the steel partial factor and longitudinal design yield strength. Each bar's assigned material supplies its bending resistance and elastic stress.")
    md('**Sub-tube inputs**\n\n1. For a supported compound section, select **Subdivide into sub-tubes (T / compound section)**.\n2. Select two to four sub-rectangles.\n3. Enter the center coordinates $x_i$, $y_i$ of each rectangle in the section axes.\n4. Enter its width $b_i$ along $x$ and height $h_i$ along $y$, in millimeters.\n5. Examine the full partition before calculation.\n\nRectangle 1 is the web paired with shear.')
    fig(fig_torsion_partition, 'Positioned rectangles for a full T-section partition. The web and flange meet at $y=100$ mm. Their interiors have no overlap, and their areas sum to $200000\\,\\text{mm}^{2}$. Crosses mark the rectangle centers. Rectangle 1 is the web paired with shear.', 'The T-section has a 200 by 400 mm web and a 600 by 200 mm flange. The web center is (0, -100) mm. The flange center is (0, 200) mm. An adjacent table gives the four inputs for each rectangle.')
    md('This example establishes the geometric partition. The wall checks then use the actual reinforcement arrangement to calculate each effective tube.')
    md('Enable **Check torsion capacity** to use the thin-walled closed-tube model in section 6.3.\n\nWith current closed links, Sector reports:\n\n- Stirrup resistance $T_{Rd,s}$.\n- Concrete-strut resistance $T_{Rd,max}$.\n- Cracking torque $T_{Rd,c}$.\n- Transverse/strut utilization $T_{Ed}/T_{Rd}$.\n- Required longitudinal steel $\\sum A_{sl}$.\n\nThe utilization describes the transverse/strut resistance component. The overall torsion status also includes the longitudinal assessment.')
    md('**Applicability and member scope**\n\nFor each nonzero $T_{Ed}$, select one torsion classification:\n\n- Equilibrium torsion.\n- Deliberately retained residual compatibility torsion.\n- Compatibility torsion that makes a member/system assessment necessary.\n\nMake sure that the section is closed or solid. Make sure that warping torsion does not govern.\n\nThe classification stays attached to the named case when rows are reordered. A new or renamed case starts as Not established.\n\nSector gives **NOT ASSESSED** before the sectional torsion calculation for these conditions:\n\n- Missing evidence.\n- Compatibility torsion that makes a member assessment necessary.\n- Open thin-walled or warping-sensitive members.')
    call("limit", 'You can set compatibility torsion to zero at ULS only if the statically indeterminate system satisfies the applicable conditions. These conditions include stability independence and minimum reinforcement.\n\nDo checks of redistribution, restraints and member response independently of Sector. The residual method uses only the $T_{Ed}$ that you keep as a design action.\n\nA warping-torsion/member analysis can be necessary for open thin-walled members.')
    md('**Actions and tube geometry**\n\nEnter signed $T_{Ed}$ in each Plastic/capacity row. A value of zero skips torsion for that row.\n\nSector calculates $A$, $u$, $t_{ef}$, $A_k$ and $u_k$ from the outline and the modeled longitudinal reinforcement.\n\n**Wall-thickness limits**\n\nFor each tube wall, the minimum $t_{ef}$ is two times the distance from the concrete edge to the assigned bar center. For a hollow section, $t_{ef}$ must also be no greater than the actual wall thickness. A positive single-tube override must satisfy each wall interval.\n\nFor supported subdivision, set the global effective-wall-thickness override to 0 mm for automatic wall thickness. Supply full bar-to-wall evidence for each sub-tube.')
    md('**Material and strut inputs**\n\nEnter one compression-strut range under **Links / stirrups** for shear and torsion. Enter a positive $\\gamma_{ct}$.\n\nThe tensile design strength is:\n\n$f_{ctd}=f_{ctk,0.05}/\\gamma_{ct}$.\n\nThe starting factors are:\n\n- EN: $\\gamma_{ct}=1.50$.\n- DK/NA: $\\gamma_{ct}=1.70$.\n\nThe report records the selected value.')
    md('**Shared stirrup.** Shear uses the entered effective legs. Torsion uses one leg of the same closed, anchored loop for $A_{sw}/s$. The enabled shared-link selection records the presence of links.')
    call("concept", 'When the section has no current closed links, the result states $T_{Rd,max}$ as the concrete-strut cap, $T_{Rd,c}$ as cracking resistance and $\\sum A_{sl}$ as reinforcement demand. Current links are necessary for the transverse/strut resistance and its utilization.')
    call("limit", 'For nonzero torsion, sufficient longitudinal reinforcement in addition to the bending reinforcement is necessary. Distribute it around each side of each torsion tube. Anchor it along the member. Sector compares Formula (6.28) with the total design tensile resistance of the modeled passive bars. A shortfall is **FAIL**. An apparently sufficient total stays **NOT ASSESSED** because the section-plane calculation does not assess bending reserve, perimeter/sub-tube allocation or member anchorage.')
    md('**Torsion strut factor.** The recommended method uses:\n\n$\\nu=0.6(1-f_{ck}/250)$.\n\nThe DK NA:2024 default uses Formula (5.104 NA):\n\n$\\nu_t=0.7(0.7-f_{ck}/200)$.')
    md('**Closed-link detailing option.** With the DK NA method, $\\nu_t=\\nu_v$ selects $\\nu_v=\\max(0.7-f_{ck}/200,0.45)$. Here $f_{ck}$ is in MPa. Use this option only with current shared links and closed peripheral stirrups. Distribute longitudinal steel uniformly on the two wall faces.')
    md('Select **$\\nu_t=\\nu_v$ (closed stirrups + distributed long. steel)** only when the detailing condition is satisfied. The selection increases $T_{Rd,max}$ through the strut factor. The recommended EN method keeps its usual factor.')
    md('The option records a detailing declaration. Do checks of the bar arrangement and member anchorage independently of this declaration. The longitudinal torsion assessment and its status requirements apply.')
    md('With current shared links, Sector also calculates $T_{Ed}/T_{Rd,max}+V_{Ed}/V_{Rd,max}\\leq1$, from Formula (6.29).')
    call("limit", 'For a T, L, I or flanged outline, select **Subdivide into sub-tubes** under 6.3.1(3).\n\nEnter these dimensions for each positioned rectangle:\n\n- Center x/y.\n- Width b and height h.\n\nTogether, the rectangles must cover the concrete net area. They must have no overlap, boundary crossing or entry into a void.\n\nFor a multi-cell section, use a different applicable tube model. The entered rectangles alone are insufficient for that model.')
    call(
        "concept",
        "The calculation shows the entered strut bounds. If the full interval is outside the selected method's permitted range, Sector reports the angle-dependent results as NOT ASSESSED. This status applies to resistance, utilization and interaction verdicts. Correct the limits before calculation.",
    )
    h2("Combined M-V-T interaction")
    md('Enable **Check combined M-V-T** to assess concurrent bending, shear and torsion under one shared code edition. Sector locks the component method selectors to that edition. The Base-EN method assesses concrete crushing, the closed stirrup and longitudinal reinforcement. The Danish method also applies $\\sum(S_{Ed}/S_{Rd})\\leq1$ under DK NA 6.3.2(6).\n\nEnable Plastic, Shear and Torsion. Enter nonzero $V_{Ed}$ and $T_{Ed}$ in the same capacity row. These conditions make the combined check applicable to that row. The summary gives a status for each physical component.')
    call("standard", '**Danish interaction criterion**\n\nDK NA 6.3.2(6) applies this criterion to $N$, $M$, $V$ and $T$:\n\n$\\sum(S_{Ed}/S_{Rd}) \\leq 1$.\n\nEach $S_{Rd}$ is the resistance to that action acting alone.\n\n**Separate M/V route**\n\nFirst check the additional longitudinal reinforcement for shear, beyond the bending requirement, independently of the section calculation. If this reinforcement satisfies the applicable conditions, select **separate M/V route as a design assumption**.\n\nSector calculates $N+M+T$ and $N+V+T$ independently and uses the larger value. A value no greater than the numerical limit is **CONDITIONAL**. The section calculation does not assess the additional reinforcement area, distribution or anchorage.\n\nA value larger than the limit is **FAIL**, also under that favorable assumption.')
    call("limit", 'Scope: cross-section resistance. Complete the applicable Annex F member and detailing assessment independently.')
    h2("Modular ratios and creep")
    md('The cracked-elastic analysis calculates the modular ratios from the assigned moduli.\n\n**Short-term ratio**\n\n$n_s=E/E_c$.\n\n**Effective concrete modulus**\n\n$E_{c,eff}=E_c/(1+\\varphi)$.\n\n**Sustained ratio**\n\n$n_l=E/E_{c,eff}$.\n\nEnter the global creep coefficient $\\varphi$ under **Inputs > Loads**.\n\nSector uses the assigned $E_s$ or $E_p$ for each bar or tendon. Different material definitions can thus have different ratios. The results report the ratios for each material in the section.')

    h1("Loads")
    md('Enter loads in the three editable tables. Each active row has one name, and names are unique across the Plastic/capacity, Elastic and fatigue-bin rows. Use the optional description for the project classification, combination or source. Add, delete or paste rows directly in the tables.')
    table(["Table", "Per-row fields", "Row-specific rule"],
          [["Plastic / capacity", "$N_{Ed}$, $M_{x,Ed}$, $M_{y,Ed}$, $V_{x,Ed}$, $V_{y,Ed}$, $T_{Ed}$",
            'Zero shear/torsion skips that component. Minimum reinforcement is selected per row'],
           ["Elastic", "Long- and short-term $N_{Ed}$, $M_{x,Ed}$, $M_{y,Ed}$",
            'Stresses are always output. Optionally calculate crack width'],
           ["Grouped fatigue", 'Spectrum, bin name, cycles. Long- and short-term $N_{Ed}$, $M_{x,Ed}$, $M_{y,Ed}$',
            'Repeated Spectrum labels form one Miner sum. Each spectrum is independent']])
    h2("Editable table field definitions")
    md("Values are user inputs unless the field definition gives a different source. Enter finite, unambiguous decimals in numeric cells. Follow the displayed sign convention. Each table's calculation scope is above its field reference.")
    field_guides(table_fields.TABLE_KEYS[4:])
    md("The editable-table definitions in this chapter and **Defining the section** are the definitions used by the input screens. Open the guide immediately above a table for each field's meaning, unit, sign convention, source and blank behavior.\n\n**Decimal separators**\n\nThe Plastic/capacity, Elastic and grouped-fatigue numeric fields accept a dot or comma as the decimal separator. Sector rejects ambiguous grouped or mixed separators.\n\n**Blank cells**\n\nSector uses zero for blank ordinary action cells. Optional fields left blank stay empty. Enter the required names, IDs and cycle values.\n\nCalculations use the entered numeric precision. Display rounding does not change the calculation value.")
    md('Sector solves the Elastic sustained and additional instantaneous actions together. The global creep coefficient $\\varphi$ applies to all Elastic rows. Each row produces concrete, reinforcing-steel and tendon stresses.\n\nFor each selected row, the crack-width calculation includes the sustained and total response. The total response combines sustained and additional actions. The calculation uses the duration-specific criteria entered in **Analysis settings**.')
    md('The creep-coefficient input help follows the selected concrete preset:\n\n- First generation: 3.1.4 and Annex B.1.\n- Danish preset: also DK NA:2024 3.1.4(1)-(2), with the conditional $\\varphi=3$ simplification.\n- 2023: 5.1.5, Table 5.2 and Annex B.5.\n\nBefore you use the 2023 basis, record its adoption in the project basis. Sector applies no Danish National Annex to this basis. A named curve without an edition is project-defined and uncited.\n\nSector uses the entered creep coefficient in the calculation. The engineer must make sure that each cited simplification is applicable.')
    md('A fatigue bin uses the long-term fields for the sustained/basic state and the short-term fields for the cyclic increment. The Elastic analysis calculates the two states. Their stress difference is the range. Use the same **Spectrum** label for all bins that belong to the same Miner sum. Sector rejects spectrum labels that differ only by letter case.')
    call("tip", 'Use case names from the project combination register. Sector uses the same names in the result selector, summary and PDF.')

    h1("Reading the results")
    md('Open the required result view. Select its **Case**. When an input issue offers **Go to**, select it to open the related input stage. A setting can be disabled because of its parent calculation, selected edition or preset. Read its input help before you change the related selection.')
    h2("Result status reference")
    md('Read each status in the context of its named case, criterion and method scope. A passing resistance component does not override a failed or unavailable overall check. The overview gives no combined compliance verdict.')
    table(["Status", "Meaning", "Next action"], [
        ["CALCULATED", 'The requested output is available. This alone is no limit assessment.',
         "Read its value, units and method limitations."],
        ["CALCULATED - NO LIMIT COMPARISON", "A crack width is available and its matching criterion is 0 mm.",
         'Keep the width alone, or enter a positive project criterion for that duration.'],
        ["PASS / WITHIN USER-SPECIFIED LIMIT", "The named check meets its stated criterion.",
         'Make sure that the criterion is applicable. Examine the overall checks.'],
        ["FAIL / EXCEEDS USER-SPECIFIED LIMIT", "The named criterion is exceeded.",
         "Open the result detail and address the governing demand or resistance."],
        ["CONDITIONAL", "The result depends on a stated condition outside automatic verification.",
         'Before you use the result, make sure that the condition is satisfied. Record the condition.'],
        ["NOT ASSESSED", "A requested assessment lacks valid evidence or lies outside supported scope.",
         'Read the cause. Correct the input or use an applicable assessment.'],
        ["NOT REQUESTED", "The check is disabled for this case or setting.",
         'If the task includes this check, enable it. Then select Calculate.'],
        ["NOT RUN", "Sector did not run this check in the stated context.",
         'Examine prerequisites and run Calculate.'],
        ["NOT CALCULATED", "No valid calculated value is available.",
         'Read the calculation message. Correct the identified input or convergence issue.'],
        ["NOT APPLICABLE", "The named check does not apply in the stated scope.",
         'Make sure that the scope is correct. Keep the related message.'],
        ["INVALID", "Inputs or calculated evidence fail validation.",
         'Before you use the affected result, correct the identified issue.'],
        ["STALE", "Inputs changed after the displayed calculation or report was generated.",
         'Calculate after engineering edits. Regenerate the report after document-only edits.'],
    ])
    h2("Results overview")
    md("Select a result under **Result details**. Select **Open selected result** to open its view.")
    md('The overview shows one governing row for each engineering check. Each row identifies its action set, direction or scope, result, criterion and status. A calculated result takes precedence over an inactive state. For equal states, the largest valid utilization governs. An exact tie keeps the first listed case.\n\nFor a check with different directions, the most unfavorable direction governs. Its label identifies that direction. **Not run**, **Not calculated**, **Not applicable** and **Not requested** identify the calculation scope and state. Headline counts summarize the rows on the screen. Each row keeps its own status.')
    md('In analysis figures, hover text reports the plotted capacity or material response represented by the selected point. Section-result markers show stress and strain. Section maps also show coordinates. The full result tables give reinforcement areas and coordinates.\n\n**Plot controls**\n\nThe plot toolbar gives these controls:\n\n- **Download plot as a PNG:** save the plot shown as an image.\n- **Zoom:** select a region to make it larger.\n- **Pan:** move the region shown.\n- **Zoom in** and **Zoom out:** change the scale.\n- **Autoscale:** change the axis ranges to include all plotted data.\n- **Reset axes:** use the initial axis ranges.\n- **Fullscreen:** show the plot on the full screen.\n\nSelect the required control in the plot toolbar. For Zoom or Pan, drag within the plot.')
    h2("Plastic results")
    md("**Section stress and strain maps** show the selected ultimate-capacity state. "
       "Select its angle with **Neutral-axis state**. Read the strain map and stress map together. "
       "Both use the section coordinates, with tension positive and compression negative.")
    md("The concrete fill shows values from the accepted strain plane and selected design material law. "
       "Circles identify bars. Diamonds identify tendons. Tendon material strain includes initial prestress strain. "
       "A tendon can remain in tension inside the concrete compression region.")
    md("Strain uses one common color scale. Concrete and reinforcement have different stress scales. Each scale has a material label. "
       "Color limits stay fixed across valid angles of the selected action. Other actions can have different limits. "
       "Use the extrema tables and element values for exact comparisons.")
    md("The filled display bands show values from the accepted field. They keep the concrete outline and voids. "
       "The number of display bands changes only the image. The plastic calculation uses its own integration bands. "
       "The extrema include concrete-law turning points. They do not depend on display-band spacing.")
    md("In a section map, move the pointer over a concrete vertex or reinforcement marker to read its value and coordinates. "
       "The extrema table gives the largest and smallest values with their locations. The element tables give reinforcement areas.")
    fig(fig_plastic_strain_map,
        "Circular example at ultimate capacity: axial compression 1500 kN and neutral-axis angle 45 degrees. Tendon material strain includes initial strain.",
        "The annular section has a diagonal compatible strain field. Bar circles and tendon diamonds use the same strain scale. The central void stays empty.")
    fig(fig_plastic_stress_map,
        "Stress in the same ultimate-capacity state. Concrete and reinforcement use different stress scales with material labels.",
        "Concrete compression occupies one side of the annulus. Discrete bar and tendon markers show the calculated material stresses. The void remains empty.")
    md("Open **Selected neutral-axis state - calculation details** for the selected sweep point. "
       "Its concrete-corner rows show compatible strain and design stress. Reinforcement rows also show the force from stress multiplied by entered area. "
       "Use the point and element IDs to compare these values with the section drawing.")
    md('Select a Plastic/capacity case at the top of the view. The $M_x$-$M_y$ envelope shows the applied action point. Use **Neutral-axis state** to select a swept angle. The selected state gives strains, compression resultant, lever arm and neutral-axis intercepts. The full per-angle table follows.')
    h2("N-M Interaction results")
    md("Enable **N-M interaction diagrams** under **Analysis settings**. Run a "
       "Plastic or Both analysis, then open **N-M Interaction** for the selected "
       "capacity case. Sector performs additional calculations that vary axial force "
       "between the attainable tension and compression limits.")
    md('The $N$-$M_x$ diagram joins the 90-degree and 270-degree neutral-axis branches. The $N$-$M_y$ diagram joins the 0-degree and 180-degree branches. Each branch uses 32 axial-force intervals and includes the two endpoints. The applied point identifies the selected action.')
    md("For an asymmetric section, a fixed neutral-axis orientation can also "
       "produce an orthogonal moment. Read each diagram as the stated fixed-orientation "
       "trace. Use the full fixed-$N$ biaxial envelope to assess the concurrent "
       "applied moment pair. A nonconverged boundary is identified as diagnostic output.")
    h2("Elastic results")
    md("Use **Map action duration** to select **Combined actions (TOTAL)** or **Sustained actions (LONG)**. "
       "The maps use the same section geometry and fixed color limits for these two states. "
       "The captions identify the selected action and duration.")
    md("The strain fill shows compatible section deformation. TOTAL includes retained long-term deformation and the instantaneous response. "
       "LONG uses the effective concrete modulus for sustained actions. Reinforcement markers show material strain. Tendon markers also include initial strain.")
    md("The concrete stress map uses the retained cracked elastic state. Tensile concrete stress is zero, while tensile section strain can remain positive. "
       "Under creep, the zero section-strain line can differ from the concrete stress boundary. Each map identifies its own dashed line.")
    md("The depth profile and concrete-corner table show instantaneous concrete stress-plane strain. "
       "The depth-profile markers and reinforcement table show TOTAL material strain. These component labels explain their difference from the compatible section-strain map.")
    md("Marker size identifies an element and has no physical diameter scale. For slab-density input, markers identify retained integration points or nominal axes. "
       "Read their tributary areas in the element table. A missing or inconsistent retained state gives **Section maps unavailable**. Calculate again before you use the maps.")
    fig(fig_elastic_strain_map,
        "Rectangular example: TOTAL compatible strain for sustained moment 100 kNm, additional moment 50 kNm, concrete modulus 35 GPa and creep coefficient 2. Axial force is zero.",
        "A vertical compatible strain gradient crosses the rectangular section. The bar strains lie on that plane. A dashed line marks zero section strain.")
    fig(fig_elastic_stress_map,
        "Stress for the same combined actions. Concrete compression uses the instantaneous stress plane. Bar stress includes retained long-term stress.",
        "Concrete stress is zero in the tensile region and becomes compressive toward the top. Bar circles show their total stresses on the reinforcement scale.")
    md('Open **Concrete corner stress/strain details** to examine the entered outer-ring and void vertices. Compatible tensile strain can occur where concrete stress is zero. Read the displayed peak concrete result together with these point values.')
    md('**Transformed section properties** compares the uncracked section with the calculated cracked section at the sustained modular ratios. The uncracked properties include the full concrete region. The cracked properties use the calculated compression region. The two sets of properties include the transformed reinforcement contribution.')
    md("Open **All crack-width candidates** to compare the governing and other evaluated crack locations. "
       "Open **Reinforcement source details** for the bars and areas used by the heightened-control check. "
       "That check follows its selected reference case.")
    md('Select an Elastic case at the top of the view.\n\n**Stress results**\n\nSector reports the cracked-section stress in each bar for the long-term, short-term and total states. It also reports peak concrete compression, the neutral-axis position, the cracking threshold and section properties.\n\n**Crack-width results**\n\nSector calculates crack width for actions with this option enabled. It compares a calculated width with the positive user limit for the matching duration. Long-term and short-term limits are independent.\n\n- A 0 mm limit gives the calculated width without a limit comparison.\n- A positive limit gives **WITHIN USER-SPECIFIED LIMIT** or **EXCEEDS USER-SPECIFIED LIMIT**, with its source.\n\nThe status compares the calculated width with the entered project criterion.')
    md('Stress percentages are 100 times the absolute stress divided by the positive characteristic strength. The references are $f_{ck}$ for concrete, $f_{yk}$ for reinforcing steel, and $f_{pk}$ and $f_{p0.1k}$ for prestressing steel. Actual stress values keep their signs.\n\nIf the reference strength is missing or invalid, Sector does not show the percentage. These percentages are strength ratios. Use the applicable engineering checks to assess compliance.')
    h2("Fatigue results")
    md('The **Fatigue Results** view first lists each spectrum and its governing utilization.\n\nSelect a spectrum to see the section utilization map. Open **Reinforcement**, **Concrete**, **Spectrum bins** or **Basis**.\n\nElement and fiber selectors show the governing and all non-governing results. Reinforcement rows show one simplified stress-range screen state:\n\n- The screen passes.\n- The detailed check is necessary.\n- The screen is not applicable.\n\nThe tables show stresses, ranges, S-N life, per-bin damage, yield/proof checks and concrete stress ratios. They also show calculation convergence, resistance sources and the bounded concrete-search result.')
    h2("Detailing results")
    md('The **Detailing** view gives a concise status for modeled-direction minimum reinforcement, shear/torsion link detailing and clear spacing. The section figure highlights the bars included in the selected case and dimensions the governing spacing pair. Tables show provided and required values, utilization or margin and element IDs.')
    h2("Shear results")
    md('When the two shear components are active, use **Directional result** to examine each component. Examine its related bending moment, selected face and reinforcement. The directional summary identifies the governing result.')
    md('The **Shear** view shows the applied $V_{Ed}$, resistance $V_{Rd,c}$ and utilization.\n\n**Geometry and calculation inputs**\n\nThe view gives $d$, $b_w$, $A_{sl}$, $\\rho_l$, $k$, $\\sigma_{cp}$ and $A_c$, with the code coefficients used. It identifies the web width as entered or calculated.\n\nFor a calculation with links, the view also gives:\n\n- Physical web width and the duct-adjusted $b_{w,nom}$, where applicable.\n- Gross and effective $A_{sw}/s$.\n- The section-form factor.\n- The fitted circular lever arm, where applicable.\n\nIf required geometry is incomplete, Sector reports **NOT ASSESSED**. Resistance, utilization and a PASS/FAIL verdict are then unavailable.')
    h2("Torsion results")
    md("The **Torsion** view separates the tube geometry, transverse resistance and longitudinal reinforcement assessment.\n\n- **Tube geometry:** $A$, $u$, $A/u$, each wall's $a$ and $2a$, $t_{ef}$, $A_k$ and $u_k$.\n- **Resistance:** $T_{Rd,s}$, $T_{Rd,max}$, $T_{Rd}$, cracking torque $T_{Rd,c}$ and transverse/strut utilization.\n- **Longitudinal reinforcement:** required $\\sum A_{sl}$, the modeled passive-bar upper bound and the overall status.\n\nWhen shear links are defined, the view also shows the combined shear-and-torsion crushing check. Insufficient or unverified longitudinal reinforcement governs the overall assessment, even when the resistance component passes.")
    md("The view gives the selected torsion design basis and member scope. An applicability condition in these selections can make a member assessment necessary.\n\nIn that case, the view gives **NOT ASSESSED** / '-' for:\n\n- Resistance and utilization.\n- Governing angle and longitudinal demand.\n- Dependent M-V-T verdicts.\n\nBending, shear and detailing results can stay available when their calculation conditions are satisfied.")
    h2("M-V-T Combined results")
    md('Use **Directional combined result** to select the $V_x$ or $V_y$ combination with torsion. Each selection uses the concurrent actions from the same capacity case. When the two directions are active, examine each direction.')
    md('The **M-V-T Combined** view gives the $M$, $V$ and $T$ utilizations and the applicable DK NA $\\sum(S_{Ed}/S_{Rd})$ sum. It also shows the concrete-crushing interaction and a $V$-$T$ envelope.\n\nThree component results identify the concrete compression strut, shared closed stirrup and governing longitudinal reinforcement. Each detail block shows its contributions and the selected member strut angle. A longitudinal torsion failure governs the combined result. An unverified longitudinal requirement gives **NOT ASSESSED**, with the calculated component values available for you to examine.')
    h2("PDF report")
    md('Choose **Brief**, **Standard** or **Audit** in the Report workspace. Standard is the default. The profile changes presentation depth only: engineering values, rounding policy, statuses, warnings and sources are the same. Each profile includes its applicable figures.')
    md("With figures enabled, Standard and Audit include stress and strain maps for each calculated Plastic and Elastic case. "
       "Plastic maps use the retained selected capacity point. Elastic maps use Combined actions (TOTAL). "
       "Each pair has its action identity, state, units, signs and extrema tables. Brief keeps its governing capacity and elastic-response figures.")
    table(
        ["Profile", "Purpose", "Not included"],
        [
            [
                policy.label,
                policy.description,
                policy.omitted_detail,
            ]
            for policy in report_profiles.REPORT_PROFILES.values()
        ],
    )
    md('**Brief** starts with project and section identity, requested-check outcomes, governing results and essential limitations. The full effective inputs follow the results. These inputs include geometry, assigned materials, reinforcement, tendons, actions and active settings. Brief does not include non-governing results and worked derivations. Brief includes the available governing Plastic and Elastic plots.\n\n**Standard** includes the used inputs, full results, criteria, statuses and concise methods. It also includes references and limitations.\n\n**Audit** adds the detailed calculation sequences, numerical substitutions, worked examples and method theory. Calculation values, rounding, statuses and warnings are the same in all three profiles.')

    # =====================================================================
    # PART C - THEORY & METHODOLOGY
    # =====================================================================
    part("Part C - Theory & methodology")

    h1("Method reference")
    md("Methods are grouped by engineering task. Each destination states the "
       "implemented scope, edition, assumptions, equations, selected branches and "
       "section-level boundaries.")
    table(
        ["Engineering task", "Method destination"],
        [
            [method.label, f"[Open {method.label}](#{method.anchor})"]
            for method in manual_ia.METHODS
        ],
    )

    h1("Conventions and sign convention")
    md('Enter coordinates in millimeters about the section origin. Sector reports coordinates in millimeters and calculates with meters.\n\n**Reported signs and units**\n\nAxial force $N$ is positive in tension and negative in compression. Its unit is kN. Stress and strain use the same sign convention. Concrete compression strain is negative.\n\nMoments $M_x$ and $M_y$ are about the $x$ and $y$ axes. Their unit is kNm.\n\n**Local depth coordinate**\n\nAt sweep angle $\\varphi_{NA}$, calculate:\n\n$s=x\\cos\\varphi_{NA}+y\\sin\\varphi_{NA}$.\n\nThe neutral axis has $s=s_{na}$, where:\n\n$s_{na}=s_{max}-c$.\n\nLarger values of $s$ are on the compression side. The neutral-axis line is at $\\varphi_{NA}$ counter-clockwise from the positive $y$ axis.')
    fig(fig_sign_convention, "Axes and the positive senses of the axial force, the "
        "moments and the neutral-axis angle.",
        'The x-axis points right, and the y-axis points up. Arrows show positive axial force and moments. The neutral-axis angle is measured from positive y.')
    call("concept", "The reported axial force $N$, the stresses and the strains are "
         "all **tension-positive**. The plastic calculation uses a "
         "**compression-positive sign convention**. Sector converts its results to the "
         "reported tension-positive convention. Enter the concrete strain limits "
         "$\\varepsilon_{c2}$ and $\\varepsilon_{cu2}$ as positive compression magnitudes.")

    h1("Material laws")
    h2("Concrete (parabola-rectangle)")
    md(('**Concrete stress-strain law**\n\nThe design concrete law (Curve 2) increases along a power curve to the peak. Its stress then stays constant to the ultimate strain:\n\n$$\\sigma_c = f_{cd}\\left[1-\\left(1-\\tfrac{\\varepsilon_c}{\\varepsilon_{c2}}\\right)^{n}\\right] \\quad (0\\le\\varepsilon_c\\le\\varepsilon_{c2}), \\qquad \\sigma_c = f_{cd}\\quad(\\varepsilon_{c2}\\le\\varepsilon_c\\le\\varepsilon_{cu2}),$$\n\nThe stress is zero after $\\varepsilon_{cu2}$, which represents crushed concrete.\n\n**Design strength**\n\n- For the 2005 family: $f_{cd} = \\alpha_{cc}\\,f_{ck}/\\gamma_c$.\n- For DS/EN 1992-1-1:2023: $f_{cd}=\\eta_{cc}k_{tc}f_{ck}/\\gamma_c$.\n\n**2005 and Danish strain parameters**\n\nFor $f_{ck}\\le 50$ MPa, use:\n\n- $\\varepsilon_{c2}=2.0$ per mille.\n- $\\varepsilon_{cu2}=3.5$ per mille.\n- $n=2$.\n\nFor $f_{ck}>50$ MPa, Table 3.1 gives these expressions. Use $f_{ck}$ in MPa. The calculated strains are dimensionless:\n\n$\\varepsilon_{c2}=(2.0+0.085(f_{ck}-50)^{0.53})/1000$.\n\n$\\varepsilon_{cu2}=(2.6+35((90-f_{ck})/100)^4)/1000$.\n\n$n=1.4+23.4((90-f_{ck})/100)^4$.\n\nThese strength-dependent strain parameters apply to the 2005 and DK NA editions.\n\n**2023 strain parameters and strength factors**\n\nDS/EN 1992-1-1:2023 uses $\\varepsilon_{c2}=2.0$ per mille, $\\varepsilon_{cu2}=3.5$ per mille and $n=2$ for each grade.\n\nThe strength factor is:\n\n$\\eta_{cc}=\\min[(40/f_{ck})^{1/3},1.0]$.\n\nThe general-case factor is $k_{tc}=0.85$. Sector applies the two strength factors to the design strength. Select $k_{tc}=1.00$ only under the applicability conditions in 5.1.6(1).').replace(
           "per mille", _PERMILLE
       ))
    md(("**Worked (beam, C40/50):** $f_{cd}=1.0\\times 40/1.45 = 27.6$ MPa, with "
        "$\\varepsilon_{c2}=2.0$ and $\\varepsilon_{cu2}=3.5$ per mille.").replace(
            "per mille", _PERMILLE
        ))
    fig(fig_beam_concrete_law, "The C40/50 parabola-rectangle law of the beam "
        "example.",
        "Concrete compression stress increases on a curved branch to its design "
        "plateau, which continues until the marked crushing strain.")
    h2("Reinforcing steel")
    md(('**General mild-steel law**\n\nThe mild-steel editor uses one general Curve 3 law. It is linear to the first yield point. The plastic offsets can give a second yield point. The last branch reaches the entered ultimate point.\n\n**Elastic branch**\n\n$$\\sigma_s = E_{s,d}\\,\\varepsilon_s\\ \\ (|\\varepsilon_s|\\le\\varepsilon_{yd}), \\qquad f_{yd}=f_{yk}/\\gamma_s, \\qquad \\varepsilon_{yd}=f_{yd}/E_{s,d}.$$\n\nFor the general law, the design modulus is:\n\n$E_{s,d}=E_s/\\gamma_E$.\n\n**Flat post-yield branch**\n\nSet $k=1$ and the two offsets to zero to combine the two yield points. Set the factored ultimate stress equal to the factored yield stress for a flat post-yield branch.\n\n**B550 worked examples**\n\nThe edition-named Curve 3 design presets set $\\gamma_E=1$. The two worked examples use the B550 DK preset. Its yield strain is:\n\n$\\varepsilon_{yd}=f_{yd}/E_s=(550/1.20)/200000\\approx2.29$ per mille.\n\n**Generic preset**\n\nThe **Curve 2 (elastic-perfectly-plastic)** selection is a project-defined preset with no cited edition. It uses the general Curve 3 law with $k=1$, zero offsets and a flat branch. Its starting value is $\\gamma_E=1$. Edited values keep the selected preset label.').replace(
           "per mille", _PERMILLE
       ))
    fig(fig_beam_steel_law, "The B550 mild-steel law of the beam example.",
        'Positive and negative B550 stress branches are linear to the yield points and then follow matching post-yield branches to the strain limits.')
    h2("Prestressing steel")
    md(('Sector evaluates a tendon at its **total** strain. This is the entered locked-in initial strain $\\varepsilon_{p,IS}$ after prestress losses, plus the tension-positive section strain. For tendon $j$ at depth $s_{p,j}$ this is:\n\n$$\\varepsilon_{p,j}=\\varepsilon_{p,IS,j}-\\kappa(s_{p,j}-s_{na}), \\qquad \\sigma_p = f(\\varepsilon_p),\\quad f_{pd}=f_{p0.1k}/\\gamma_s.$$\n\n**Worked (circular):** $\\varepsilon_{p,IS}=5.0$ per mille and $f_{pd}=1600/1.15=1391$ MPa.').replace("per mille", _PERMILLE))
    fig(fig_circular_prestress_law, "The tendon law of the circular example.",
        'The tendon curve starts with an elastic slope, curves in the direction of the proof-strength region and ends at the defined ultimate strain.')
    call("standard", 'The beam and circular examples select the edition-named DS/EN 1992-1-1:2005 + DK NA:2024 Curve 3 design preset for mild steel. Edition-named concrete, mild-steel and tendon presets keep their own sources. Generic named curves stay project-defined / uncited.')

    h1("Cracked-section elastic analysis")
    md('The cracked-section model gives concrete compression resistance only. Concrete stress is zero where $\\varepsilon\\geq0$. Steel stays linear in tension and compression.\n\nEach element has modular ratio $n_i=E_i/E_c$. A bar or tendon contributes transformed area $(n_i-1)A_i$ in the concrete compression zone. In the cracked tension zone, it contributes $n_iA_i$. The subtraction removes the concrete displaced by reinforcement. Reinforcement stresses use the full material modulus.\n\nStage I cracking and uncracked properties use $(n_i-1)A_i$ for all reinforcement. Concrete is then active in tension and compression. The equilibrium equations normalize $E_c$ to 1 and solve the reference-stress plane $(\\sigma_0,g_x,g_y)$. The physical concrete strain is $\\varepsilon_c=\\sigma_{ref}/E_c$.\n\nNewton iteration adjusts the plane until section resultants balance the applied axial force and moments. Each iteration updates the concrete compression region. Part D gives the matrix, correction, stopping rule and worked iterations.')
    md('Creep changes the modular ratio through the effective concrete modulus:\n\n$E_{c,eff}=E_c/(1+\\varphi)$.\n\nFor reinforcing steel, use:\n\n- Long-term actions: $n_l = E_s/E_{c,eff}$.\n- Short-term actions: $n_s = E_s/E_c$.\n\nThe reported total combines the duration states and includes creep effects.\n\nFor a tendon, use its assigned modulus $E_p$. Its short-term ratio is $n_p=E_p/E_c$. For sustained actions, Sector uses the effective concrete modulus in that ratio.\n\nThe ratios follow from the assigned material modulus, $E_c$ and the creep coefficient $\\varphi$.')
    fig(fig_beam_cracked, "The beam's cracked (Stage II) state under the service "
        "moment: the compression zone (shaded) above the neutral axis.",
        "A rectangular section has a shaded concrete compression zone above a "
        "horizontal neutral axis, with reinforcement points included in the Stage II "
        "section.")

    h1("Plastic capacity analysis")
    h2("The strain plane at capacity")
    md('Plane sections stay plane, so the strain is linear across the depth:\n\n$\\varepsilon_{sec}(s) = \\kappa\\,(s - s_{na})$.\n\nHere, $\\kappa$ is the curvature and $s_{na}$ is the neutral-axis coordinate. The compression depth is:\n\n$c = s_{max}-s_{na}$.\n\nAt capacity, the first material strain limit governs. Concrete can reach its crushing strain, or a bar or tendon can reach its assigned limit first.')
    fig(fig_strain_plane, 'The capacity strain plane uses the reported tension-positive convention. The straight line is zero at the neutral axis, with compression above and tension below it. In this concrete-governed example, the top fiber reaches the crushing strain. The calculation formula above is compression-positive. The reported strains negate it.',
        'A straight strain line crosses zero at the neutral axis. Negative compression lies above it, and positive tension lies below it. The top fiber reaches ultimate concrete compression.')
    h2("The governing curvature")
    md("Sector increases the curvature until the **first** element reaches its assigned material limit. The selected curvature satisfies each element's material strain limit:\n\n$$\\kappa = \\min\\!\\left(\\frac{\\varepsilon_{cu2}}{c},\\; \\min_i\\frac{\\varepsilon_{u,i}}{s_{na}-s_{b,i}}\\;\\text{tension-side bars},\\; \\min_i\\frac{\\varepsilon_{u,i}}{s_{b,i}-s_{na}}\\;\\text{compression-side active bars},\\; \\min_j\\frac{\\varepsilon_{pu,j}-\\varepsilon_{p,IS,j}}{s_{na}-s_{p,j}}\\;\\text{tension-side tendons}\\right).$$\n\nThe terms represent four limits:\n\n- Concrete crushing.\n- Tensile mild-bar rupture.\n- Compressive mild-bar rupture, for a bar active in compression.\n- Tensile tendon rupture, measured from that tendon's locked-in strain.\n\nSector uses a candidate only when its denominator and remaining tendon strain margin are positive. Sector evaluates each bar and tendon with its own assigned law. The smallest candidate controls the curvature.")
    call("concept", "$s_{p,j}$ is tendon $j$'s projection on the local strain gradient. If all tendons share the same limit and initial strain, $s_{p,min}=\\min_j s_{p,j}$ is a useful shorthand for the most tensile location. Sector evaluates each tendon at its own position, initial strain and material limit.")
    call("tip", 'The results identify the greatest tensile bar strain $\\varepsilon_{s,t}$. When plastic compression is active, they also identify the most compressed bar strain $\\varepsilon_{s,c}$. The sign is positive in tension and negative in compression. For tension-only bars, the results show $\\varepsilon_s$ and the compressed bars have zero stress.')
    h2("Force resultants and equilibrium")
    md("The concrete compression force is the integral of $\\sigma_c$ over the compression region. Sector divides the rising stress region into 80 bands of equal depth. Each band uses its midpoint stress and exact polygon area and first moments. Green's theorem supplies those geometric integrals.\n\nSector integrates the constant-stress plateau in a different operation. Each bar and tendon adds $\\sigma(\\varepsilon)A$. The depth search adjusts compression depth $c$ until $\\sum F=-N$. Internal axial force is positive in compression. Entered $N$ is positive in tension.\n\nThe first moments of the force resultants about the origin give capacity moments $M_x$ and $M_y$.")
    h2("The interaction envelope")
    md(('Each neutral-axis angle $\\varphi_{NA}$ gives one solved point on the $M_x$-$M_y$ envelope. A sweep from $0$ to $360$ degrees closes the diagram.\n\n**Worked beam:** use $N=0$ and $\\varphi_{NA}=90^\\circ$. The concrete reaches its crushing strain of 3.5 per mille. The most tensile bar strain is 19.5 per mille, larger than its yield strain of 2.29 per mille. This state gives $M_x=346$ kNm. An applied $M_x=300$ kNm gives utilization $300/346=0.87$.').replace(
           "per mille", _PERMILLE
       ))
    fig(fig_beam_envelope, 'The beam envelope with its applied load. Each vertex is one solved neutral-axis angle.',
        'A closed biaxial moment-resistance curve contains the design moment point. Discrete points identify the angular sweep.')

    h1("Serviceability: cracking and crack width")
    h2("The cracking threshold")
    md('The uncracked (Stage I) peak concrete tensile stress $\\sigma_{ct,I}$ scales with the load. The load factor to first cracking is:\n\n$\\lambda_{cr}=f_{ctm}/\\sigma_{ct,I}$.\n\nA value $\\lambda_{cr}\\ge 1$ means that the section is uncracked.\n\n**Worked beam at $M_x=150$ kNm**\n\nThe factor is $\\lambda_{cr}=0.48<1$, so the section is cracked. Use the Stage II stresses. The bottom-bar stress is $\\sigma_s=204$ MPa.')
    md('Locked-in tendon prestress is permanent. Sector keeps it fixed while the external action changes.\n\nIf a prestress-only fiber stress is larger than $f_{ctm}$, Sector assigns $\\lambda_{cr}=0$ and classifies the section as cracked.\n\nIf no fiber stress is larger than that limit, examine each fiber with a tensile external increment. Sector solves:\n\n$\\sigma_{pre,i}+\\lambda_{cr}\\sigma_{ext,i}=f_{ctm}$.\n\nOnly the external $N/M$ scales. Sector uses the first cracking factor:\n\n- $\\lambda_{cr}<1$: cracked.\n- $\\lambda_{cr}\\ge 1$: uncracked.')
    call("concept", 'Sector classifies cracking from the two entered action states: sustained and total. The total state combines sustained and additional actions. If a state causes cracking, Sector treats the section as cracked for the two reported action parts.\n\nA large additional action can thus cause the cracked classification. A counteracting additional action can relieve the total demand while the sustained state governs cracking. The total-state check uses the same creep superposition as the reported stresses: sustained at $n_l$ and additional at $n_s$.')
    call("standard", 'The selected cracking method uses the entered sustained and peak actions. Sector reports the crack widths for the two actions. A positive duration limit gives a comparison with the width for that duration.')
    h2("Crack width - EN 1992-1-1:2005")
    md('$$w_k = s_{r,max}\\,(\\varepsilon_{sm}-\\varepsilon_{cm}),\\qquad \\varepsilon_{sm}-\\varepsilon_{cm} = \\max\\!\\left(\\frac{\\sigma_s - k_t\\,\\tfrac{f_{ct,eff}}{\\rho_{p,eff}}(1+\\alpha_e\\rho_{p,eff})}{E_s},\\; 0.6\\,\\frac{\\sigma_s}{E_s}\\right),$$\n\nwith $\\alpha_e=E_s/E_{cm}$ (7.8, 7.9). The maximum crack spacing is\n\n$$s_{r,max} = k_3\\,c + k_1 k_2 k_4\\,\\frac{\\phi}{\\rho_{p,eff}}\\ (7.11), \\qquad s_{r,max}=1.3\\,(h-x)\\ (7.14)$$\n\n**Spacing condition**\n\nFormula (7.11) applies when bar spacing is no greater than $5(c+\\phi/2)$. Formula (7.14) applies for larger spacing.\n\n**Effective reinforcement ratio**\n\n$\\rho_{p,eff}=A_{s,eff}/A_{c,eff}$.\n\nThe effective concrete area uses this height:\n\n$h_{c,ef}=\\min(2.5(h-d),(h-x)/3,h/2)$.\n\n**Recommended coefficients**\n\n- $k_1=0.8$ for ribbed bars or $k_1=1.6$ for plain bars.\n- $k_2=0.5$.\n- $k_3=3.4$.\n- $k_4=0.425$.')
    md(('**Worked (beam, $M_x=150$ kNm):** $\\sigma_s=204$ MPa, $\\rho_{p,eff}=0.0393$, $\\varepsilon_{sm}-\\varepsilon_{cm}=0.797$ per mille, $s_{r,max}=236$ mm, which gives $w_k=0.188$ mm.').replace(
            "per mille", _PERMILLE
        ))
    h2("DK NA fine crack system")
    md('The DK NA uses the cover-dependent coefficient $k_3=3.4(25/c)^{2/3}$. This reduces $s_{r,max}$ for cover above 25 mm. The $(h-x)/3$ term in $h_{c,ef}$ applies to slabs and prestressed members. For ordinary beams, the formula has no such term.\n\n**Worked result:** $s_{r,max}=206$ mm and $w_k=0.164$ mm.')
    h2("DK NA coarse crack system")
    md("The coarse system in 7.3.4(1) uses a band at the tension face as its effective tension area. The band's area centroid must coincide with the tension reinforcement centroid, as shown in Figure 7.100 NA. For a rectangle, the band height is $2(h-d)$. The coarse method halves the calculated crack width.\n\n**Worked result:** the band is 0.100 m high and $w_k=0.077$ mm.")
    call("tip", 'The **DS/EN 1992-1-1 + DK NA** option reports fine and coarse crack systems together. Each system has long-term and short-term results. The calculation thus gives four crack widths.')
    h2("DK NA heightened crack-control minimum")
    md('Enable **DK heightened crack-control minimum** to calculate the reinforcement ratio from DS/EN 1992-1-1 DK NA:2024 Formula 7.100 NA.\n\n$$\\rho_{s,min}=m_s\\sqrt{\\frac{\\phi f_{ct,eff}}{4E_{sk}kw_k}}$$\n\nUse $k=1$ for the fine system and $k=2$ for the coarse system. Use $m_s=1$ for ribbed reinforcement and $m_s=\\sqrt{2}$ for smooth reinforcement.\n\nSector uses the permitted width for Formula 7.100 NA. It calculates the two systems with the effective area entered for each system $A_{c,eff}$. A positive ordinary crack-diameter override supplies the bar diameter. If the override is zero, Sector uses the largest contributing mild-bar diameter.\n\n$E_{sk}$ is the lowest modulus of the contributing mild-steel materials. $A_{s,prov}$ is their total area. The report identifies the reference case, ordinary crack method, elements and material sources. It gives the two comparisons and the governing system.\n\nMissing or indeterminate source values prevent calculation. The user supplies the applicability, restraint, watertightness and permitted width $w_k$. The option applies to the first-generation Danish basis.')
    h2("DS/EN 1992-1-1:2023 refined model")
    md('The 2023 edition uses the refined model in 9.2.3:\n\n$$w_k = k_w\\,\\frac{k_1}{r}\\,s_{r,m,cal}\\,(\\varepsilon_{sm}-\\varepsilon_{cm}),\\qquad k_w=1.7,\\qquad \\frac{k_1}{r}=\\frac{h-x}{(h-x)-a_{y,i}},$$\n\nThe factor $k_1/r$ applies to each bar under Formula (9.9).\n\n**Mean crack spacing**\n\n$$s_{r,m,cal} = 1.5\\,c + \\frac{k_{fl}\\,k_b}{7.2}\\,\\frac{\\phi}{\\rho_{p,eff}} \\le \\frac{1.3}{k_w}(h-x)\\ (9.15),$$\n\nUse these parameters:\n\n- Flexural coefficient $k_{fl}$ from Formulas (9.16)-(9.17).\n- Bond factor $k_b=0.9$ for ribbed reinforcement or $k_b=1.2$ for plain reinforcement, from Formula (9.18).\n- Effective height $h_{c,eff}$ from Figure 9.3.\n\nThe height starts from the reinforcement layer nearest the face and extends across the tension layers.\n\n**Mean strain**\n\nFormula (9.11) keeps the same numerator. Its lower bound is:\n\n$(1-k_t)\\sigma_s/E_s$.\n\n**Worked result**\n\n- $s_{r,m,cal}=134$ mm.\n- $w_k=0.186$ mm.')
    md('The three code options give four method/system results for the same beam and service moment ($M_x=150$ kNm). DK NA calculates results for its fine and coarse reinforcement systems. The spacing column uses $s_{r,max}$ for 2005/DK NA and $s_{r,m,cal}$ for 2023:')
    table(["Crack-width edition", "Crack spacing (mm)", "$h_{c,ef}$ (m)", "$w_k$ (mm)"],
          [["EN 1992-1-1:2005", "236", "0.125", "0.188"],
           ["DS/EN + DK NA (fine)", "206", "0.125", "0.164"],
           ["DS/EN + DK NA (coarse)", "184", "0.100", "0.077"],
           ["DS/EN 1992-1-1:2023", "134", "0.175", "0.186"]])
    call("standard", 'The **Crack-width design basis** options are EN 1992-1-1:2005, DS/EN 1992-1-1 + DK NA, and DS/EN 1992-1-1:2023. The Danish option gives fine and coarse systems for long-term and short-term actions.\n\nStandard and Audit show the globally governing ordinary crack width. Audit also gives its worked calculation. For DK NA, the reports keep the governing fine and coarse results. Audit gives their worked examples.\n\nBrief gives full effective inputs and governing crack-width rows. Standard and Audit add the detailed results applicable to their profiles. When the user enters positive criteria, they compare the largest calculated ordinary width with its matching limit. That selection uses width, rather than the ratio to the limit.\n\nThe Danish heightened-control option gives its Formula 7.100 NA section assessment. Audit includes its numerical example.')

    h1("Grouped fatigue")
    h2("Elastic stress ranges")
    md('Each spectrum bin contains a sustained/basic action $S_l$, a cyclic increment $S_s$ and a cycle count $n_i$. Sector runs the cracked Elastic analysis two times and applies the action factor to the increment:\n\n$$\\Delta\\sigma_{Ed,i}=\\left|\\sigma(S_l+\\gamma_{Ff}S_s)-\\sigma(S_l)\\right|.$$\n\nLong-term actions use $n_l$ and the increment uses $n_s$. Prestress and element-specific elastic moduli follow the assigned material definitions. Sector reports the unfactored total state beside the design state.')
    call("concept", 'Sector applies $\\gamma_{Ff}$ to the action. The resulting design stress range goes into the S-N or concrete-life check. Do not apply $\\gamma_{Ff}$ to the resistance curve.')

    h2("Simplified reinforcement stress-range screen")
    md('Sector first evaluates the supported simplified stress-range check for each assigned named reinforcement or prestressing detail. Sector uses the shortcut only when each spectrum bin converges and has a tensile endpoint. A stress range equal to the stated limit passes. A lower range passes. A higher range does not fail the member, but makes the detailed S-N/Miner check necessary. Custom, imported or unsupported details also continue to the detailed check.')
    table(
        ["Fatigue basis and named detail", "Simplified limit"],
        [
            ["2005 family - unwelded straight or bent reinforcing bar",
             "70 MPa characteristic range"],
            ["2005 family - welded reinforcing bar or fabric",
             "35 MPa characteristic range"],
            ["2023 - unwelded straight or bent bar, $\\phi \\leq 12$ mm",
             "90 MPa design range"],
            ["2023 - unwelded straight or bent bar, $\\phi > 12$ mm",
             "73 MPa design range"],
            ["2023 - welded bar or fabric, $\\phi \\leq 12$ mm",
             "40 MPa design range"],
            ["2023 - welded bar or fabric, $\\phi > 12$ mm",
             "30 MPa design range"],
            ["2023 - reinforcing-steel coupler", "19 MPa design range"],
            ["2023 - pretensioning steel or single strand in plastic duct",
             "95 MPa design range"],
            ["2023 - tendon in plastic duct", "80 MPa design range"],
            ["2023 - curved tendon in steel duct", "55 MPa design range"],
        ],
    )
    md('For a 2023 bent-bar preset, the selected mandrel-to-diameter reduction also reduces the tabulated straight-bar limit. The 2023 shortcut is limited to a total of $10^8$ cycles. The 2005-family screen uses the characteristic fatigue range. The 2023 screen uses the design range with the action-level $\\gamma_{Ff}$ factor. Sector always reports the detailed S-N/Miner result, and the yield/proof-stress check stays independent of the shortcut.')
    md('References: DS/EN 1992-1-1:2004 + A1:2014 + AC:2010, 6.8.6(1)-(2), with DS/EN 1992-1-1 DK NA:2024. DS/EN 1992-1-1:2023, 10.4(1) for the selectable 2023 method.')
    call(
        "concept",
        'A passing simplified screen means that a more detailed stress-range assessment is not required for that element. The report includes the detailed calculation and independent strength checks.',
    )

    h2("Reinforcement S-N and Miner check")
    md("For each bar or tendon, the selected fatigue detail supplies $N^{*}$, slopes "
       "$k_1$ and $k_2$, and the characteristic reference range "
       "$\\Delta\\sigma_{Rsk}$. The design knee is\n\n"
       "$$\\Delta\\sigma_{Rd}=\\frac{\\Delta\\sigma_{Rsk}}{\\gamma_s},$$\n\n"
       "and the life of bin $i$ is\n\n"
       "$$N_{R,i}=N^*\\left(\\frac{\\Delta\\sigma_{Rd}}"
       "{\\Delta\\sigma_{Ed,i}}\\right)^{k},$$\n\n"
       "with $k=k_1$ above the knee and $k=k_2$ below it. Zero range gives infinite "
       "life. Diameter and bent-bar adjustments follow the selected detail preset.")
    md("Sector adds damage in one named spectrum:\n\n$$D=\\sum_i\\frac{n_i}{N_{R,i}}\\leq1.0.$$\n\nSector also checks the long-term and design-total stresses against the element's tension or compression yield/proof strength divided by $\\gamma_s$. If the simplified screen passes, its stress-range utilization replaces Miner damage for the governing range criterion. If the screen does not pass, Miner damage applies. Yield/proof utilization stays independent in the two cases.")
    fig(fig_fatigue_sn, 'Two-slope characteristic and design S-N curves. Each labeled marker is one applied spectrum bin. The two axes use logarithmic scales.',
        'A log-log stress-range versus cycles plot shows characteristic and design S-N curves with a knee. The applied spectrum-bin points are below the design resistance curve.')
    fig(fig_fatigue_damage, 'Per-bin and cumulative Miner damage for the same element. The cumulative line and $D=1.00$ limit show the governing contribution and remaining margin. The y-axis changes to a logarithmic scale for low-damage spectra so small contributions stay readable.',
        'Damage bars identify each spectrum bin, a cumulative Miner-damage line increases across the bins, and a horizontal D equals 1 limit shows the remaining margin.')

    h2("Mixed mild reinforcement and bonded tendons")
    md('When mild reinforcement and bonded tendons occur in one section, Sector applies the edition-specific bond model. The 2005 method applies the 6.8.2(2) bond correction $\\eta$ to the mild-reinforcement range and leaves the tendon range unadjusted. The 2023 method solves the section again with the equivalent tendon area from 10.3(2). The tendon detail thus requires $\\xi$ and an equivalent diameter. Sector reports the applied method and adjustment for each bin.')

    h2("Concrete compression fatigue")
    md("The fatigue strength is edition-specific. For the 2005 family Sector uses "
       "the corrected DS/EN 1992-2 expression\n\n"
       "$$f_{cd,fat}=k_1\\,\\beta_{cc}(t_0)\\,\\alpha_{cc}"
       "\\frac{f_{ck}}{\\gamma_{c,fat}}\\left(1-\\frac{f_{ck}}{250}\\right).$$\n\n"
       "For 2023:\n\n"
       "$$\\eta_{cc}=\\min\\left[\\left(\\frac{40}{f_{ck}}\\right)^{1/3},1\\right],"
       "\\quad\\eta_{cc,fat}=\\min(0.85\\eta_{cc},0.8),\\quad "
       "f_{cd,fat}=\\beta_{cc}(t_0)\\frac{f_{ck}}{\\gamma_{c,fat}}"
       "\\eta_{cc,fat}.$$")
    md('Use the same concrete fiber for the two states of a bin:\n\n- $\\sigma_{max}$ is the larger design compression magnitude.\n- $\\sigma_{min}$ is the smaller design compression magnitude.\n\nCalculate the normalized maximum and stress ratio:\n\n- $E_{max}=\\sigma_{max}/f_{cd,fat}$.\n- $R=\\sigma_{min}/\\sigma_{max}$.\n\nThe implemented life relation is:\n\n$$\\log_{10}N_R=C\\frac{1-E_{max}}{\\sqrt{1-R}}.$$\n\nSector sums Miner damage at that same fiber. Each location has its own result. Sector also checks direct stress utilization $E_{max}\\leq1.0$.')
    md('The damage-equivalent method checks each user-supplied equivalent action pair with\n\n$$E_{max}+0.43\\sqrt{1-\\frac{E_{min}}{E_{max}}}\\leq1.$$\n\nThis is Formula (6.72) for the 2005 family and Formula (E.2) for 2023. Each pair represents $10^6$ cycles. Sector uses the pair as entered. For more than one equivalent row, the largest criterion governs.')
    md('Sector checks the section vertices and runs an adaptive branch-and-bound search over the concrete area. The result includes the largest evaluated criterion, a conservative upper bound, the absolute and relative gap, sample and box counts, and convergence. The upper bound governs the calculation status, so an unresolved potentially critical region cannot pass.')

    h2("Edition and scope summary")
    table(["Edition", "Reinforcement", "Concrete", "Mixed bond"],
          [["DS/EN 1992-1-1:2005",
            '6.8.6 shortcut. 6.8.4 and Tables 6.3N/6.4N detailed check',
            "6.72 equivalent or corrected DS/EN 1992-2:2005/AC:2008 6.106 Miner",
            "6.8.2(2) eta correction"],
           ["DS/EN 1992-1-1:2005 + DK NA:2024",
            '6.8.6 shortcut unchanged. Detailed method with Danish project factors',
            'Same selectable methods. Explicit Danish project factors',
            "6.8.2(2) eta correction"],
           ["DS/EN 1992-1-1:2023",
            '10.4 shortcut. Annex E.5 and Tables E.1/E.2 detailed check',
            "E.2 equivalent or E.7-E.8 Miner",
            "10.3(2) equivalent tendon area"]])
    call("limit", 'Each spectrum forms an independent Miner sum and result. The Elastic fatigue model covers normal force and biaxial bending. Assess shear- and torsion-induced fatigue with a method that covers these actions.')

    h1("Shear resistance")
    md('The design shear resistance of a member not requiring shear reinforcement (EN 1992-1-1 6.2.2(1)) is\n\n$$V_{Rd,c} = \\Big[C_{Rd,c}\\,k\\,(100\\,\\rho_l\\,f_{ck})^{1/3} + k_1\\,\\sigma_{cp}\\Big]\\,b_w\\,d \\quad(6.2\\text{a}),$$\n\nwith a lower bound\n\n$$V_{Rd,c} = (v_{min} + k_1\\,\\sigma_{cp})\\,b_w\\,d \\quad(6.2\\text{b}),$$\n\n**Size factor**\n\n$k = 1 + \\sqrt{200/d} \\le 2$.\n\nUse $d$ in millimeters.\n\n**Tension-reinforcement ratio**\n\n$\\rho_l = A_{sl}/(b_w\\,d) \\le 0.02$.\n\n**Axial stress**\n\n$\\sigma_{cp} = N_{Ed}/A_c < 0.2\\,f_{cd}$.\n\nCompression is positive in this expression.\n\n**Edition coefficients**\n\n- $C_{Rd,c} = 0.18/\\gamma_c$.\n- $k_1 = 0.15$.\n\nThe recommended minimum stress is:\n\n$v_{min} = 0.035\\,k^{1.5}\\sqrt{f_{ck}}$.\n\nDK NA:2024 uses:\n\n$v_{min} = (0.051/\\gamma_c)\\,k^{1.5}\\sqrt{f_{ck}}$.')
    md('Sector calculates geometry for each active shear direction. The effective depth $d$ extends from the extreme compression fiber to the centroid of the tension bars. The compression fiber lies opposite the selected tension face.\n\nAn entered $b_w$ supplies the governing web width. If no positive override is entered, Sector samples solid widths over the middle 80% of the depth and uses the smallest value. Enter a governing web width for a curved outline. Make sure that the section-form requirements are satisfied under **Shear capacity settings**.\n\nFor $\\sigma_{cp}$, Sector reverses the entered tension-positive axial force to get compression-positive force. Automatic face selection follows the related moment. At zero related moment, Sector evaluates the two faces.')
    md('For DS/EN 1992-1-1:2023, the action-dependent factor is\n\n$$a_{cs}=\\max\\!\\left(\\left|M_{Ed}/V_{Ed}\\right|,d\\right),\\qquad k_{vp}=\\max\\!\\left(1+\\frac{N_{Ed}}{|V_{Ed}|}\\frac{d}{3a_{cs}},0.1\\right),$$\n\nand $d$ in Formula (8.27) is replaced by $k_{vp}d$. The 2023 convention takes $N_{Ed}$ positive in tension, so axial tension raises $k_{vp}$ and reduces the basic shear-stress resistance. Compression has the opposite effect. The minimum stress from Formula (8.20) and the lever arm $z=0.9d$ use the nominal $d$.')
    call("limit", '$A_{sl}$ is the longitudinal tension reinforcement, **assumed fully anchored** ($\\geq l_{bd} + d$) beyond the section. Make sure that the member design satisfies the anchorage conditions. Where anchorage cannot resist the force, reduce $f_{yk}$ / $f_{ywk}$ to the strength that the anchorage can resist. Sector does not automatically include bonded tendons in $\\rho_l$.')
    md('**Worked example: concrete shear resistance**\n\nUse these inputs:\n\n- Rectangle: 300 x 600 mm.\n- Concrete: C35.\n- Method: DK NA:2024.\n- $A_{sl}=1473$ $\\text{mm}^2$.\n- $d=550$ mm.\n- $b_w=300$ mm.\n- $N=0$.\n\nThe calculated parameters, rounded for display, are:\n\n- $k=1.603$.\n- $\\rho_l=0.00893$.\n- $C_{Rd,c}=0.124$.\n- Basic shear stress: $0.627$ MPa.\n- $v_{min}=0.535$ MPa.\n\nThe basic shear stress is greater than $v_{min}$. Use the basic stress with full precision. Multiply it by $b_wd$, then divide by 1000 to get kN:\n\n$V_{Rd,c}\\approx103.4$ kN.')

    h2("Members with shear reinforcement (links)")
    md('A member with designed links uses a truss model. The links are tension ties. The concrete web forms compression struts at angle $\\theta$ to the member axis.\n\n**2005-family resistances**\n\n$$V_{Rd,s} = \\frac{A_{sw}}{s}\\,z\\,f_{ywd}\\,\\cot\\theta \\quad(6.8), \\qquad V_{Rd,max} = \\frac{\\alpha_{cw}\\,b_w\\,z\\,\\nu_1\\,f_{cd}}{\\cot\\theta + \\tan\\theta} \\quad(6.9),$$\n\nThe governing resistance is:\n\n$V_{Rd} = \\min(V_{Rd,s}, V_{Rd,max})$.\n\nHere, $z$ is the internal lever arm. The strut effectiveness factor is $\\nu_1$.\n\n**Compression-chord factor**\n\nThe factor $\\alpha_{cw}$ is 1 for a non-prestressed section. It increases with axial compression as specified in Formula (6.11N).\n\n**Longitudinal tension**\n\nShear adds this force under Formula (6.18):\n\n$\\Delta F_{td} = 0.5\\,V_{Ed}\\,\\cot\\theta$.\n\nThe reinforcement at the selected tension chord must resist this force and the bending force.')
    md('For DS/EN 1992-1-1:2023,\n\n$$\\tau_{Rd,sy}=\\rho_w f_{ywd}\\cot\\theta \\quad(8.42),\\qquad \\sigma_{cd}=\\tau_{Ed}(\\cot\\theta+\\tan\\theta)\\leq\\nu f_{cd}\\quad(8.44),$$\n\nThe reinforcement ratio and concrete effectiveness factor are:\n\n- $\\rho_w=A_{sw}/(b_ws)$.\n- $\\nu=0.5$.\n\nSector reports the two stresses and the equivalent resistances $V_{Rd,s}$ and $V_{Rd,max}$.\n\n**Longitudinal force from shear**\n\nSector calculates the longitudinal force with Formula (8.50):\n\n$N_{Vd}=|V_{Ed}|\\cot\\theta$.\n\nSector uses this force without the support/load-specific relief in Formula (8.53). The force acts on the two flexural chords.\n\n**Force in the flexural tension chord**\n\nIn the two chord-force formulas, $M_{Ed}$ is the moment magnitude. Sector uses the physical face to assign the bending sign in the resistance comparison.\n\nFormula (8.51) gives:\n\n$F_{td}=M_{Ed}/z+N_{Vd}+N_{Ed}/2$.\n\n**Force in the flexural compression chord**\n\nFormula (8.52) gives:\n\n$F_{cd}=M_{Ed}/z-N_{Vd}+N_{Ed}/2$.\n\nPositive $F_{cd}$ is compression. Negative $F_{cd}$ is tension in this chord.\n\n**Comparison with bending resistance**\n\nSector checks the two physical faces with the correct bending sign for each face. Each face has its own bending resistance for the acting axial force and the moment about the other axis.\n\nThose resistances include the axial action. The equivalent-moment comparison does not add that action a second time.')
    call("standard", '**2023 variable-width section**\n\nSector uses the entered governing width $b_w$. It multiplies $A_{sw}$ by $\\cos\\delta$ under 8.2.3(9).\n\n**2023 circular section**\n\nSector multiplies $A_{sw}$ by $b_w/D_h$. It uses the entered fitted-section lever arm $z$.\n\nFor example:\n\n$b_w/D_h=400/600=2/3$.\n\nThe corrected link contribution is two thirds of the unadjusted contribution. The unadjusted contribution is 1.5 times the corrected contribution.\n\n**Duct allowance**\n\nFor 2023, Clause 8.2.3(10) applies the selected duct allowance to the compression-field width. For the 2005 family, Clause 6.2.3(6) applies it to $V_{Rd,max}$.')
    md('**2023 chord arithmetic example**\n\nUse these scalar assumptions:\n\n- $M_{Ed}=90$ kNm.\n- $M_{Rd}=100$ kNm.\n- $N_{Vd}=250$ kN.\n- $z=0.5$ m.\n\nThe equivalent total moment is:\n\n$M_{Ed,total}=90+250\\cdot0.5=215$ kNm.\n\nThe utilization is $215/100=2.15$, which gives **FAIL**.\n\nAssess the opposite chord independently with Formula (8.52). If its face-specific resistance is unavailable, the full longitudinal-chord assessment is **NOT ASSESSED**.')
    call("concept", 'For reinforced-shear checks, Sector calculates the internal lever arm $z$ at the exact face-aligned Plastic state and action-set axial force.\n\nThe compression and tension resultants include the sign-split contributions from concrete, mild steel and tendons. Their separation is $z$, with Cartesian components $z_x$ and $z_y$:\n\n- For x-axis bending, use $|z_y|$.\n- For y-axis bending, use $|z_x|$.\n\nIf the required Plastic state is unavailable, the links resistance is **NOT ASSESSED**.')
    md('The stirrup resistance $V_{Rd,s}$ increases with $\\cot\\theta$. The crushing resistance $V_{Rd,max}$ has its maximum at $\\cot\\theta=1$ and decreases for larger values.\n\n**Calculate the angle candidate**\n\nUse these two coefficients:\n\n- $a = (A_{sw}/s)\\,f_{ywd}$.\n- $b = \\alpha_{cw}\\,b_w\\,\\nu_1\\,f_{cd}$.\n\nThe lever arm $z$ cancels. For $a>0$, calculate:\n\n$r=\\sqrt{\\max(b/a-1,0)}$.\n\nThen include the crushing-branch peak:\n\n$c_0=\\max(r,1)$.\n\n**Apply the entered bounds**\n\n$\\cot\\theta=\\min(\\max(c_0,\\cot\\theta_{min}),\\cot\\theta_{max})$.\n\nThis procedure also gives a result when $b/a<1$. If transverse reinforcement is zero, Sector selects the upper bound.')
    call("standard", '**Recommended Eurocode factor**\n\nFormula (6.6N) gives:\n\n$\\nu_1 = \\nu = 0.6\\,(1 - f_{ck}/250)$.\n\n**Danish factor**\n\nDK NA:2024 uses the plasticity factor for pure shear:\n\n$\\nu_1 = \\nu_v = 0.7 - f_{ck}/200 \\geq 0.45$.\n\nThis is Formula (5.103 NA). Formula (5.101 NA) applies it to the truss struts.\n\n**Angle bounds**\n\nThe two editions give:\n\n$1 \\leq \\cot\\theta \\leq 2.5$.\n\nThe references are Formula (6.7N) and Formula (6.7a NA).')
    call("standard", '**2023 angle limits**\n\nSector uses a lower cotangent bound of 1.0. To calculate the upper bound, use this sequence:\n\n1. Start with $c_{max}=2.5$.\n2. For positive axial tension and nonzero shear, use $c_{max}=\\max(2.5-0.1N_{Ed}/|V_{Ed}|,1)$.\n3. For class A, multiply $c_{max}$ by 0.8.\n4. Use $\\max(c_{max},1)$ as the upper bound.\n\nHere, $N_{Ed}$ is positive in tension. Class B/C without axial tension thus gives $1\\leq\\cot\\theta\\leq2.5$.\n\nSector uses 2.5 as the maximum upper bound. Before you use 3.0, do a member assessment of the compression-chord depth.')
    call("standard", 'For net axial compression, Sector reports the reinforced-shear result as **NOT ASSESSED**.\n\nThe simplified 2023 route under 8.2.3(11) uses the force assigned to the web and the compression-chord depth for the action state. A member assessment must supply these quantities.\n\nComplete that assessment with Annex G where applicable.')
    md('**Worked shear example**\n\nUse the same section with C35 concrete, DK NA:2024 and these links:\n\n- Two legs of diameter 10 mm.\n- Spacing $s = 150$ mm.\n- Yield strength $f_{ywk} = 500$ MPa.\n\nThe calculated lever arm is $z = 509.151$ mm. The calculation values are:\n\n- $f_{ywd} = 417$ MPa.\n- $\\nu_1 = 0.525$.\n- $A_{sw}/s = 1.047$ mm$^2$/mm.\n\nThe crossing $\\cot\\theta = 2.78$ is larger than the upper limit. Sector thus selects $\\cot\\theta = 2.5$.\n\nThe branch resistances are $V_{Rd,s} = 555.4$ kN and $V_{Rd,max} = 667.5$ kN. The smaller value gives $V_{Rd} = 555.4$ kN, controlled by the links.')

    h1("Torsion (thin-walled tube)")
    md('EN 1992-1-1, 6.3.1, gives two torsion conditions:\n\n- Equilibrium torsion must be resisted.\n- You can omit compatibility torsion at ULS only under the stated system and minimum-reinforcement conditions.\n\nDo the member/system checks independently of Sector. Sector calculates compatibility torsion only when a residual $T_{Ed}$ stays in the design actions.\n\nUnder 6.3.3, a warping-torsion/member assessment can be necessary for open thin-walled or warping-sensitive members. Sector gives the sectional tube result only for an applicable closed/solid member scope.')
    md('Sector models a section under torsion as a thin-walled closed tube under 6.3.2(1). Constant shear flow around the walls resists the torque.\n\n**Effective wall thickness**\n\n$A$ is the area inside the outer perimeter, with the hollow area included. The perimeter is $u$. The effective thickness starts from $A/u$.\n\nEach wall must satisfy:\n\n$t_{ef,i}\\geq2a_i$.\n\nHere, $a_i$ is the distance from the concrete edge to the assigned longitudinal-bar center. A hollow wall supplies the upper thickness limit.\n\n**Tube centerline**\n\nThe centerline is inside the outline, at distance $t_{ef}/2$. Its enclosed area is $A_k$. Its perimeter is $u_k$.\n\n**Transverse and strut resistances**\n\nThe resistances use the strut angle $\\theta$:\n\n$$T_{Rd,s} = \\frac{A_{sw}}{s}\\,2A_k\\,f_{ywd}\\,\\cot\\theta, \\qquad T_{Rd,max} = 2\\,\\nu\\,\\alpha_{cw}\\,f_{cd}\\,A_k\\,t_{ef}\\,\\sin\\theta\\cos\\theta \\quad(6.30),$$\n\nThe $T_{Rd,s}$ expression follows the wall shear flow in Formula (6.27) and transverse equilibrium in Formula (6.8). The governing transverse resistance is:\n\n$T_{Rd}=\\min(T_{Rd,s},T_{Rd,max})$.\n\n**Longitudinal reinforcement**\n\nFormula (6.28) gives:\n\n$\\sum A_{sl}=T_{Ed}u_k\\cot\\theta/(2A_kf_{yd})$.\n\nOn the tension side, this reinforcement supplements the bending reinforcement.\n\n**Cracking torque**\n\n$T_{Rd,c}=2A_kt_{ef}f_{ctd}$.\n\nThe tensile design strength is:\n\n$f_{ctd}=f_{ctk,0.05}/\\gamma_{ct}=0.7f_{ctm}/\\gamma_{ct}$.\n\nThe editable starting factor $\\gamma_{ct}$ is 1.50 for EN and 1.70 for DK/NA.')
    md('For an isolated capacity calculation, $T_{Rd,s}$ increases with $\\cot\\theta$ in the permitted range. $T_{Rd,max}$ reaches its maximum at 45 degrees. Sector compares the stirrup and strut branches. It selects their crossover when applicable, the 45-degree strut peak when it governs, or a permitted bound.\n\nWhen shear and torsion act together, Sector checks the shared concrete struts:\n\n$$T_{Ed}/T_{Rd,max} + V_{Ed}/V_{Rd,max} \\le 1 \\quad(6.29),$$\n\nFor loaded cases, Sector selects one member strut angle for all active angle-dependent checks. These checks include concrete crushing, shared stirrups and longitudinal chord demand. Sector selects the angle with the lowest governing utilization across these checks. The combined-method chapter gives this selection procedure.')
    md('**Strut factor**\n\nThe selected method supplies the torsion effectiveness factor $\\nu$. Use $f_{ck}$ in MPa.\n\n- Recommended EN value, 6.2.2(6): $0.6(1-f_{ck}/250)$.\n- DK NA:2024, Formula (5.104 NA): $\\nu_t=0.7(0.7-f_{ck}/200)$.\n\nThe 0.45 lower bound in Formula (5.103 NA) applies to $\\nu_v$. It does not apply to $\\nu_t$.')
    md('**Automatic tube geometry.** Sector automatically idealizes solid and single-cell sections. For a re-entrant T, L, I or flanged outline, use supported component rectangles under **Subdivide into sub-tubes** (6.3.1(3)). The rectangles must cover the net concrete area. Their interiors must not overlap, cross the section boundary or enter a void. For sections with two or more cells, use a different applicable torsion model.')
    md('**Subdivided-section thickness.** Enter 0 mm for the global effective-thickness override. Sector then calculates the thickness for each tube wall. A positive global override prevents the subdivided calculation.')
    md('**Reinforcement locations.** Each tube needs sufficient evidence to assign longitudinal reinforcement to its walls. Missing, ambiguous or conflicting assignments give **NOT ASSESSED** before calculation of resistance or interaction. A thickness override does not supply this location evidence.')
    md("**Permitted strut angles.** If the entered $\\cot\\theta$ interval exceeds the selected method's permitted range, the angle-dependent checks give **NOT ASSESSED**. These checks include torsion resistance, utilization, longitudinal demand and dependent interaction. Sector shows the requested and permitted limits. The angle-independent cracking torque can stay available.")
    md('**Torsion example**\n\n- Section: 300 x 600 mm rectangle, C35, DK NA:2024.\n- Bar centers: 50 mm from each wall.\n- Closed stirrups: $\\phi10$ at $s=150$ mm.\n\n**Section and tube geometry**\n\n- Section area: $A=0.18\\,\\mathrm{m^2}$.\n- Section perimeter: $u=1.8$ m.\n- Each thickness criterion, $A/u$ and $2a$, equals 100 mm.\n- Effective thickness: $t_{ef}=100$ mm.\n- Tube area: $A_k=0.1\\,\\mathrm{m^2}$.\n- Tube perimeter: $u_k=1.4$ m.\n- Strut factor: $\\nu_t=0.368$.\n\n**Resistance**\n\nThe stirrup and strut branches meet at:\n\n- $\\cot\\theta=1.75$.\n- $T_{Rd}\\approx76.4$ kNm.\n\nWith $\\gamma_{ct}=1.70$, the cracking torque is:\n\n$T_{Rd,c}=26.435$ kNm.')

    h1("Combined M-V-T interaction")
    md('Bending, shear and torsion act together, so their checks are tied together under one code edition (6.3.2). For the two supported first-generation editions, the concrete web struts carry shear and torsion, limited by\n\n$$T_{Ed}/T_{Rd,max} + V_{Ed}/V_{Rd,max} \\le 1 \\quad(6.29),$$\n\nchecked at a common strut angle, together with the supported closed-stirrup and longitudinal-chord equilibrium checks. Base EN reports each physical check and does not publish an additional aggregate interaction verdict. The DK NA:2024 selection (6.3.2(6)) adds a general rule over the acting sectional forces,\n\n$$\\sum (S_{Ed}/S_{Rd}) \\le 1,$$\n\neach $S_{Rd}$ being the resistance to that force acting alone. Sector calculates four resistances:\n\n- Axial resistance for the entered tension or compression sign.\n- Plastic $M$-$M$ resistance at zero axial force, in the entered biaxial moment direction.\n- Shear resistance with the other external sectional actions set to zero.\n- Torsion resistance with the other external sectional actions set to zero.\n\nPrestress stays part of each section state.')
    call("standard", 'Under DK NA 6.3.2(6), use the separate M/V route only after you independently check additional shear reinforcement beyond the bending requirement. Sector then compares $N+M+T$ and $N+V+T$ independently. The larger value controls the result.\n\nFor torsion, add longitudinal steel $\\sum A_{sl}$ around the perimeter. For shear, add reinforcement for $\\Delta F_{td}$ on the tension chord. These reinforcement quantities supplement the bending reinforcement.')
    call("limit", 'When you select the separate $M$/$V$ route, Sector records a design assumption. Sector does not check the additional reinforcement area, distribution or anchorage. A DK NA sum no greater than the numerical limit is thus **CONDITIONAL**. A sum larger than the limit is **FAIL** even under that favorable assumption, because the ordinary simultaneous sum cannot be smaller. Make sure that the assumption is valid before you use a conditional result.')
    call("limit", 'The combined result is an internal cross-section resistance check. It does not replace a member and detailing assessment under Annex F where that assessment applies.')
    md('**Chord faces**\n\nSector compares each **longitudinal tension chord** demand with its bending resistance. Each force contribution becomes an equivalent moment on the lever arm $z$:\n\n- **Bending:** the applied bending demand for that chord.\n- **Shear shift:** $\\Delta F_{td}z$, from 6.18, with the cap in 6.2.3(7).\n- **Torsion:** $F_{td,T}z/2$, from 6.28.\n\nUnder biaxial bending, the available chord resistance depends on the moment about the other axis. Sector finds the neutral-axis angle that gives the same companion moment. The related point on the plastic envelope supplies $M_{Rd}$.\n\nTorsion adds tension at each chord face. Sector evaluates the two faces of each axis. The compression face of the shear axis receives the torsion share without the shear shift. Each other-axis chord includes its bending demand and torsion share. Its resistance depends on the coexisting shear-axis moment.\n\nSector reports the governing face for each axis: the face with the highest applicable utilization. With asymmetric reinforcement, torsion alone can make a face govern even when bending compresses that face. For a subdivided section, the torsion reinforcement belongs to individual tubes. Sector does not evaluate the other-axis share for that arrangement and reports this limit.')
    md('**Shared stirrups**\n\nThe **shared closed stirrup** carries the applicable shear and torsion demands. When $|V_{Ed}|\\leq V_{Rd,c}$, concrete supplies the nominal shear resistance under 6.2.1. The full stirrup area is then available for torsion. Above that boundary, Sector adds the shear and torsion stirrup demands.\n\n**Common strut angle**\n\nThe stirrup and concrete-crushing checks must satisfy their criteria at one strut angle. Stirrup demand is smallest for a flat strut. Crushing utilization is smallest at 45 degrees. Sector reports the common angle that gives the lowest governing utilization.')
    call("standard", 'Sector selects one angle to **minimize the governing utilization** across the dependent physical checks. When the strut becomes flatter, stirrup demand decreases. Concrete-crushing utilization and longitudinal-chord tension increase. The selected angle balances these effects in the permitted range.\n\nThis common angle governs the shared strut, stirrup and longitudinal chords. Sector calculates each DK NA denominator for its action acting alone. Enter the permitted $\\cot\\theta$ range under **Links / stirrups**. A capacity-only calculation with zero shear and torsion selects the angle that maximizes resistance in that range.')

    h1("Reinforcement detailing")
    md('Each detailing checkbox identifies the clauses used by the selected Detailing edition. Selecting an edition applies the rules in this chapter. Use the 2023 edition only where it is adopted by the project. The current 2023 option has no Danish National Annex.\n\nThe modeled-direction minimum check uses ordinary reinforcing bars only.')
    h2("EN 1992-1-1:2005 and DK NA:2024")
    md('Sector transfers the moments to the gross-concrete centroid and calculates the uncracked gross-concrete strain plane for the full $M_x$-$M_y$ action. Sector evaluates its tensile half-plane with:\n\n$$A_{s,min}=\\max\\!\\left(0.26\\frac{f_{ctm}}{f_{yk}},\\,0.0013\\right)b_t d, \\qquad A_{s,prov}\\ge A_{s,min}. $$\n\n$b_t$ is the exact mean width of the resultant tension half. Measure $d$ normal to its neutral line. The endpoints are the opposite extreme concrete fiber and the centroid of the tension bars. If more than one material is assigned, Sector uses the lowest $f_{yk}$. Reference: 9.2.1.1(1), Formula (9.1N).')
    call("limit", 'The DK NA:2024 side-face reinforcement requirement for high beam webs is outside Formula (9.1N) and is not included.')
    h2("DS/EN 1992-1-1:2023")
    md('For bending with axial force, Sector calculates the uncracked cracking action in the applied moment direction. It checks:\n\n$$M_{R,nom}(N_{Ed})\\ge M_{cr}(N_{Ed}).$$\n\nThe nominal resistance uses the entered design concrete law. Sector limits each reinforcing bar to its characteristic $f_{yk}$.\n\n1. Calculate a closed nominal-resistance envelope at 15-degree intervals.\n2. Find the governing moment direction.\n3. Refine around that direction with target intervals of 1, 0.1 and, when required, 0.01 degrees.\n4. At each stage, calculate the governing direction again.\n5. Continue that stage until its actual adjacent interval is no larger than the target.\n\n**Utilization interval**\n\nFrom the 0.1-degree stage, calculate:\n\n$u_f\\pm\\max(2|u_f-u_c|,10^{-6})$.\n\nHere, $u_f$ is the fine result and $u_c$ is the coarse result from the last stage. Each result satisfies its target interval. The acceptance boundary is:\n\n$u=1+10^{-9}$.\n\nAccept a verdict only when successive stages agree and the full interval is on one side of the boundary. If the interval crosses the boundary after the 0.01-degree stage, report **NOT ASSESSED**. Report **NOT ASSESSED** if the governing interval cannot be refined consistently.\n\nFor pure tension, the criterion is:\n\n$$\\sum A_{s,i}f_{yk,i}\\ge A_c f_{ctm}.$$\n\nReference: 12.2(2), Formulas (12.1) and (12.2). The bending check is not applicable when the compression magnitude is $0.5A_cf_{cd}$ or more.')
    h2("Clear spacing")
    md('For each included pair of longitudinal elements, Sector calculates the edge-to-edge distance from the entered coordinates and circular detailing diameters and checks:\n\n$$c_{clear}\\ge\\max(\\phi_{max},\\,D_{upper}+5\\,\\text{mm},\\,20\\,\\text{mm}).$$\n\nThis is 8.2(2) for the 2005 family and 11.2(2) for 2023. The smallest margin governs. Sector reports a geometric shortfall as **Fail**. Lap length, bond, bundle equivalence and longitudinal arrangement each have their own detailing check.')
    h2("Shear and torsion reinforcement")
    md('For vertical shear links, Sector checks the entered legs in each active direction with:\n\n$$\\rho_w=\\frac{A_{sw}}{s\\,b_w}\\ge\\rho_{w,min},\\qquad\\rho_{w,min}=c\\frac{\\sqrt{f_{ck}}}{f_{ywk}}.$$\n\n$c=0.063$ for DS/EN 1992-1-1:2005 DK NA:2024 and $c=0.08$ for EN 1992-1-1:2005 and DS/EN 1992-1-1:2023. In the 2023 method, Sector applies the optional class-B or class-C reduction only when you select it. References: 2005 9.2.2(5), Formulae (9.4)-(9.5). 2023 12.2(4), Formula (12.4).')
    md('Sector compares the longitudinal and transverse shear-link spacings with:\n\n$$s_l\\le0.75d,\\qquad s_t\\le\\min(0.75d,600\\,\\text{mm}).$$\n\n**Transverse distance set to zero**\n\nSector uses the gross web breadth $b_w$ as an upper bound for the transverse distance between legs:\n\n- A bound no greater than the limit gives **Pass**.\n- A bound larger than the limit gives **Not assessed** until you enter the actual maximum spacing.\n\nIf there are fewer than two effective legs, enter the distance.\n\n**Measurement direction**\n\nMeasure the distance in the section plane:\n\n- Along $y$ between $V_x$-parallel legs.\n- Along $x$ between $V_y$-parallel legs.\n\nThe longitudinal stirrup spacing has its own input. Keep the closed-stirrup height unchanged when you enter the transverse distance.')
    md('For a closed torsion link, Sector evaluates one leg in each effective tube wall:\n\n$$\\rho_{w,T}=\\frac{A_{leg}}{s\\,t_{ef}}\\ge\\rho_{w,min}.$$\n\nThe maximum longitudinal spacing is the lesser of $u_k/8$ and the rotation-invariant minimum physical section dimension. Sector evaluates each sub-tube. Each active shear direction has its own $0.75d$ check.')
    call("limit", 'Sector models the entered shear reinforcement as vertical stirrups. It models the entered torsion reinforcement as closed stirrups.\n\nThe resistance assumes full anchorage. Where full anchorage is unavailable, reduce $f_{ywk}$.\n\nComplete a check for each of these details:\n\n- Cover, bends and mandrel diameter.\n- Anchorage length and lap length.\n- Bundle equivalence.\n- Congestion and construction access.')
    call("standard", 'Under DS/EN 1992-1-1:2023 8.2.1(2), minimum shear reinforcement is necessary for statically determinate linear members with $d>500$ mm. Because this condition depends on the member system, the section result flags it for project review.')
    call("standard", 'BN1-59-5 and the Danish Road Directorate bridge basis add project- and existing-structure applicability requirements, with special treatment of inadequately anchored historic links. Record and apply owner-specific requirements in the project basis.')

    h1("Equilibrium check")
    md('Each numerical solve records its convergence state.\n\n**Plastic equilibrium**\n\nAt each plastic orientation, compression-positive internal forces must balance the tension-positive entered action:\n\n$\\sum F=-N$.\n\nThe acceptance condition is:\n\n$|\\sum F+N|\\le 10^{-6}\\max(1,|N|)$.\n\nUse forces in kN.')
    md('If the axial target is unreachable, the point keeps a nonconverged status. The envelope displays that diagnostic point and records the convergence state of all its points. Examine the axial action, section, materials and reported residual before you interpret the boundary.')
    md('**Elastic equilibrium**\n\nFor the elastic reference plane, tension-positive internal resultants use this target:\n\n$(N,-M_x,-M_y)$.\n\nThe resultant components are:\n\n- First: the stress integral over the section.\n- Second: the integral of stress multiplied by $y$.\n- Third: the integral of stress multiplied by $x$.\n\nSubtract the locked-prestress resultants from that target before the solve. Iteration updates the compressed region until the resultant residual meets the stated tolerance.')
    md('Each characteristic and action-factored elastic state in each bin must converge for a valid fatigue spectrum. A nonconverged state prevents a passing fatigue result.')

    # =====================================================================
    # PART D - REFERENCE
    # =====================================================================
    part("Part D - Reference")

    h1("Standards")
    md('Sector implements these Eurocode 2 methods. Select the material, crack-width, detailing and member-check editions explicitly. Sector records the selections in the results and report. Part C gives the implemented differences.')
    call("limit", 'DS/EN 1992-1-1:2023 is available as a **published project-adoption basis**. The engineer must document project adoption. Sector applies this basis without a Danish National Annex. Sector calculates the concrete law without the 2023 confinement enhancement.')
    table(["Topic", "Reference"],
          [["Concrete law (first generation)",
            "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010, 3.1.7, "
            "Formula (3.17), and Table 3.1"],
           ["Concrete law (2023)",
            "DS/EN 1992-1-1:2023, 5.1.6(1), Formulae (5.3)-(5.4), "
            "8.1.1(2)-(3), 8.1.2(1), and Formula (8.4)"],
           ["Reinforcement law (first generation)",
            "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010, 3.2.7"],
           ["Reinforcement law (2023)",
            "DS/EN 1992-1-1:2023, 5.2.4(1)-(3), Formula (5.11), "
            "and Figure 5.2"],
           ["Prestressing steel law (first generation)",
            "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010, 3.3.6"],
           ["Prestressing steel law (2023)",
            "DS/EN 1992-1-1:2023, 5.3.3(1)-(3), Formula (5.12), "
            "and Figure 5.3"],
           ["Creep coefficient (first generation)",
            _manual_input_source(
                design_standards.DesignBasisKey.FIRST_GEN_BASE,
                design_standards.InputGuidanceKey.CREEP_COEFFICIENT,
            )],
           ["Creep coefficient (DK NA:2024)",
            _manual_input_source(
                design_standards.DesignBasisKey.FIRST_GEN_DK_NA_2024,
                design_standards.InputGuidanceKey.CREEP_COEFFICIENT,
            )],
           ["Creep coefficient (2023)",
            _manual_input_source(
                design_standards.DesignBasisKey.PUBLISHED_2023,
                design_standards.InputGuidanceKey.CREEP_COEFFICIENT,
            )],
           ["Cracking and crack width (2005)", "DS/EN 1992-1-1 7.3"],
           ["Crack width (DK NA)", "DS/EN 1992-1-1 DK NA 7.3.4"],
           ["Crack width (2023)", "DS/EN 1992-1-1:2023 9.2.3"],
           ["Reinforcement fatigue (2005)", "DS/EN 1992-1-1:2005+A1:2014 6.8.2, 6.8.4 and Tables 6.3N/6.4N"],
           ["Concrete fatigue (2005)", 'DS/EN 1992-1-1:2005 6.8.7 / Formula (6.72). DS/EN 1992-2:2005/AC:2008, corrected 6.106'],
           ["Reinforcement fatigue (2023)", "DS/EN 1992-1-1:2023 Annex E.5 and Tables E.1/E.2"],
           ["Concrete fatigue (2023)", 'DS/EN 1992-1-1:2023 E.4.3 / Formula (E.2). E.5.3 / Formulae (E.7)-(E.8)'],
           ["Minimum reinforcement (first generation)",
            _manual_input_source(
                design_standards.DesignBasisKey.FIRST_GEN_BASE,
                design_standards.InputGuidanceKey.DETAILING_MINIMUM_REINFORCEMENT,
            )],
           ["Minimum reinforcement (DK NA:2024)",
            _manual_input_source(
                design_standards.DesignBasisKey.FIRST_GEN_DK_NA_2024,
                design_standards.InputGuidanceKey.DETAILING_MINIMUM_REINFORCEMENT,
            )],
           ["Minimum reinforcement (2023)",
            _manual_input_source(
                design_standards.DesignBasisKey.PUBLISHED_2023,
                design_standards.InputGuidanceKey.DETAILING_MINIMUM_REINFORCEMENT,
            )],
           ["Shear/torsion link detailing (first generation)",
            _manual_input_source(
                design_standards.DesignBasisKey.FIRST_GEN_BASE,
                design_standards.InputGuidanceKey.DETAILING_TRANSVERSE_LINKS,
            )],
           ["Shear/torsion link detailing (DK NA:2024)",
            _manual_input_source(
                design_standards.DesignBasisKey.FIRST_GEN_DK_NA_2024,
                design_standards.InputGuidanceKey.DETAILING_TRANSVERSE_LINKS,
            )],
           ["Shear/torsion link detailing (2023)",
            _manual_input_source(
                design_standards.DesignBasisKey.PUBLISHED_2023,
                design_standards.InputGuidanceKey.DETAILING_TRANSVERSE_LINKS,
            )],
           ["Clear spacing (first generation)",
            _manual_input_source(
                design_standards.DesignBasisKey.FIRST_GEN_BASE,
                design_standards.InputGuidanceKey.DETAILING_CLEAR_SPACING,
            )],
           ["Clear spacing (DK NA:2024)",
            _manual_input_source(
                design_standards.DesignBasisKey.FIRST_GEN_DK_NA_2024,
                design_standards.InputGuidanceKey.DETAILING_CLEAR_SPACING,
            )],
           ["Clear spacing (2023)",
            _manual_input_source(
                design_standards.DesignBasisKey.PUBLISHED_2023,
                design_standards.InputGuidanceKey.DETAILING_CLEAR_SPACING,
            )],
           ["Shear without shear reinforcement", "DS/EN 1992-1-1 6.2.2 + DK NA 6.2.2(1)"],
           ["Shear, strain-based (2023)", 'DS/EN 1992-1-1:2023 4.3.3 and Table 4.3 (NDP) ($\\gamma_V$). 8.2.2 ($\\tau_{Rd,c}$, $d_{dg}$)'],
           ["Shear with links (variable strut)", "DS/EN 1992-1-1 6.2.3 + DK NA 6.2.3(2)-(3)"],
           ["Torsion (thin-walled tube)", "DS/EN 1992-1-1 6.3 + DK NA 5.6.1(3)P / 6.3.2(6)"],
           ["Combined M-V-T (Base EN)", "EN 1992-1-1 6.3.2(2), (4) and (6.29)"],
           ["Combined M-V-T (Danish edition)", "DS/EN 1992-1-1 6.3.2 + DK NA 6.3.2(6)"]])

    h1("Limitations & troubleshooting")
    md('Use this indexed chapter for explicit model boundaries and for the symptom/cause/correction path shown by the application. A zero long-term or short-term ordinary crack criterion is an intentional no-comparison state. A zero enabled heightened criterion is invalid and must be corrected.')
    h2("Key assumptions & limitations")
    md('- **One plane section.** Plane sections stay plane. The strain field is linear across the section.\n- **Perfect bond.** Reinforcement strain equals the concrete strain at the same point (before cracking) and follows the strain plane after.\n- **Concrete stress.** Cracked-elastic and plastic section equilibrium use compression-only concrete. Concrete tensile strength enters the cracking threshold, crack-width rules and applicable resistance checks.\n- **Ultimate is strain-controlled.** The section fails when the first material reaches its strain limit (concrete crushing or steel/tendon rupture). No material is driven past its limit.\n- **Section calculations.** Sector includes section bending, elastic/crack response, grouped normal-force/bending fatigue, shear, torsion and combined M-V-T checks where the selected method is supported.\n- **Member-level review.** Buckling, second-order response, deflection, connections and global load paths stay member or system calculations.\n- **Fatigue spectrum basis.** Named spectra are independent and use the entered cycle/action assumptions. The fatigue calculation covers normal force and bending.\n- **Detailing scope.** The modeled-direction minimum check uses ordinary reinforcement. DK NA high-web side-face reinforcement, anchorage, lap length, bundle equivalence, cover and congestion each make an engineering review necessary. Beam torsion-link provisions apply to beam models.')
    call("limit", "The ordinary crack-width models define effective tension area and crack spacing along one bending direction. Sector uses the strain gradient of the combined $N$, $M_x$ and $M_y$ cracked state. It reports the governing bar's crack width along that direction. Use a different method to assess interacting crack systems.")
    h2("Troubleshooting index")
    table(
        ["Symptom", "Likely cause", "Correction"],
        [
            [warning.symptom, warning.cause, warning.correction]
            for warning in manual_ia.WARNINGS
        ],
    )

    h1("Glossary")
    table(["Symbol / term", "Meaning"],
          [["$N$", 'Entered and reported axial force. Tension positive (kN)'],
           ["$P$", 'Compression-positive axial target in the numerical procedures. $P=-N$ (kN)'],
           ["$M_x$, $M_y$", 'Bending moments about the x and y axes (kNm)'],
           ["$\\varphi_{NA}$", 'Neutral-axis sweep angle from +y (degrees)'],
           ["$s$", 'Local depth projection $x\\cos\\varphi_{NA}+y\\sin\\varphi_{NA}$. Larger $s$ is the compression side'],
           ["$s_{na}$", "Neutral-axis depth coordinate, $s_{max}-c$"],
           ["$s_{p,j}$", "Projected depth coordinate of tendon $j$"],
           ["$\\kappa$", 'Compression-positive internal section curvature (1/m)'],
           ["$V_{Ed}$", 'Applied design shear action (kN)'],
           ["$\\Delta\\sigma_{Ed}$", 'Action-factored fatigue stress range (MPa)'],
           ["$\\Delta\\sigma_{Rsk}$", 'Characteristic S-N reference range (MPa)'],
           ["$N^{*}$", "Reference cycle count at the S-N curve knee"],
           ["$k_1$, $k_2$", "S-N slopes above and below the knee"],
           ["$D$", 'Palmgren-Miner cumulative damage. Limit 1.0'],
           ["$\\gamma_{Ff}$", "Partial factor on the cyclic fatigue action increment"],
           ["$f_{cd,fat}$", 'Design concrete compressive fatigue strength (MPa)'],
           ["$A_{sl}$", 'Selected tension-side longitudinal reinforcement ($\\text{mm}^{2}$)'],
           ["$A_{s,min}$", 'Required minimum reinforcement in the modeled direction ($\\text{mm}^{2}$)'],
           ["$b_t$", 'Mean width of the bending tension zone (mm)'],
           ["$D_{upper}$", 'Upper aggregate size used in the clear-spacing rule (mm)'],
           ["$A_{sw}/s$", 'Shear-link area per spacing ($\\text{mm}^{2}$/mm)'],
           ["$F_c$", 'Concrete compression resultant (kN)'],
           ["$F_{comp}$", 'Total compression resultant from concrete and reinforcement in compression (kN)'],
           ["$z$, $z_x$, $z_y$", 'Internal resultant lever arm and its Cartesian components (mm)'],
           ["TOTAL", 'Elastic stress from long- and short-term actions (MPa)'],
           ["LONG", 'Elastic stress from the long-term action alone (MPa)'],
           ["DIF", 'TOTAL minus LONG (MPa)'],
           ["RST1", 'Instantaneous response to total actions after subtraction of locked prestress and retained reinforcement resultants (MPa)'],
           ["$f_{ck}$, $f_{cd}$", "Characteristic / design concrete strength"],
           ["$f_{yk}$, $f_{yd}$", "Characteristic / design steel strength"],
           ["$\\varepsilon_{cu2}$", "Ultimate concrete compressive strain"],
           ["$\\varepsilon_{ud}$", "Design ultimate steel strain (rupture)"],
           ["$n$", "Modular ratio $E_s/E_c$ (elastic analysis)"],
           ["$s_{r,max}$", "Maximum crack spacing"],
           ["$w_k$", "Characteristic crack width"],
           ["$h_{c,ef}$", "Effective tension-zone height (crack width)"],
           ["Stage I / II", "Uncracked / fully cracked elastic state"]])

    from manual_walkthroughs import extend_manual
    from manual_numerics import numerical_blocks

    expanded = extend_manual(blocks)
    reference = expanded.index(("part", "Part D - Reference"))
    expanded[reference] = ("part", "Part E - Reference")
    expanded[reference:reference] = numerical_blocks()
    return expanded


_PART_SUMMARIES = {
    "Part A - Get started": "Purpose, quick start, examples and common uses.",
    "Part B - Features & options": "Inputs, settings, load tables and result views.",
    "Part C - Theory & methodology": "Engineering models, equations and worked examples.",
    "Part D - Numerical procedures": "Worksheet procedures, iterations and independently reproducible examples.",
    "Part E - Reference": "Standards, assumptions, limitations and glossary.",
}


def manual_parts() -> dict[str, list]:
    """Return the manual blocks grouped into their navigable parts."""
    parts: dict[str, list] = {}
    current = None
    for block in manual_blocks():
        if block[0] == "part":
            current = block[1]
            parts[current] = [block]
        elif current is not None:
            parts[current].append(block)
    return parts


def manual_published_item_parts():
    """Return the visible manual with validated figure/table identities."""

    parts = published_manual_parts(manual_publication_blocks(manual_blocks()))
    if tuple(parts) != tuple(_PART_SUMMARIES):
        raise ValueError("Published manual part identity changed.")
    return parts


# ==========================================================================
# PDF RENDERER -- same content blocks, rendered with ReportLab
# ==========================================================================
# The in-app content uses Markdown + LaTeX (KaTeX). For the PDF the small, known
# subset used here is converted to ReportLab's HTML-like markup: Greek and
# operators become numeric entities, sub/superscripts become <sub>/<super>, and
# fractions become an inline ``a/b`` (parenthesised when compound).

_LATEX_CMD = {
    r"\lceil": "&#8968;", r"\rceil": "&#8969;",
    r"\varepsilon": "&#949;", r"\gamma": "&#947;", r"\sigma": "&#963;",
    r"\varphi": "&#966;", r"\alpha": "&#945;", r"\rho": "&#961;",
    r"\kappa": "&#954;", r"\delta": "&#948;",
    r"\lambda": "&#955;", r"\phi": "&#966;", r"\eta": "&#951;",
    r"\beta": "&#946;", r"\theta": "&#952;", r"\nu": "&#957;",
    r"\tau": "&#964;", r"\xi": "&#958;", r"\pi": "&#960;",
    r"\Delta": "&#916;", r"\le": "&#8804;", r"\ge": "&#8805;",
    r"\leq": "&#8804;", r"\geq": "&#8805;",
    r"\neq": "&#8800;", r"\times": "&#215;", r"\cdot": "&#183;",
    r"\approx": "&#8776;", r"\pm": "&#177;", r"\sum": "&#8721;",
    r"\circ": "&#176;", r"\rightarrow": "&#8594;",
    r"\int": "&#8747;",
}

_LATEX_LAYOUT_COMMANDS = (
    r"\left", r"\right", r"\Big", r"\big", r"\Bigg", r"\bigg",
    r"\mathrm", r"\!", r"\,", r"\;",
)
_LATEX_WORD_OPERATORS = ("min", "max", "ln", "log", "sin", "cos", "tan", "cot")


def _latex_to_rl(s: str) -> str:
    """Convert the LaTeX subset used in the manual to ReportLab inline markup."""
    # Preserve authored thin/medium spacing, including number-unit separation.
    s = s.replace(r"\,", "&nbsp;").replace(r"\;", "&nbsp;")
    # A TeX command can be a single superscript token, e.g. 90^\circ.
    s = re.sub(r"\^(\\[A-Za-z]+)", r"^{\1}", s)
    for c in sorted(_LATEX_LAYOUT_COMMANDS, key=len, reverse=True):
        s = s.replace(c, "")
    s = s.replace(r"\qquad", "&nbsp;&nbsp;&nbsp;").replace(r"\quad", "&nbsp;&nbsp;")
    s = re.sub(r"\\text\{([^{}]*)\}", r"\1", s)   # \text{label} -> label
    # Brace-form sub/superscripts first, so the fraction args are brace-free.
    s = re.sub(r"_\{([^{}]*)\}", r"<sub>\1</sub>", s)
    s = re.sub(r"\^\{([^{}]*)\}", r"<super>\1</super>", s)

    def _frac(m):
        def wrap(x):
            if x.startswith("&#8730;(") and x.endswith(")"):
                return x
            return "(" + x + ")" if re.search(r"[ +\-]", x) else x

        return wrap(m.group(1)) + "/" + wrap(m.group(2))

    # Iterate roots and fractions together to a fixed point. This handles both a
    # root inside a fraction and a fraction inside a root without exposing a TeX
    # command in the issued PDF.
    # An adjacent coefficient (for example C\frac{...}{...}) receives an
    # explicit multiplication dot because a linearised fraction has no fraction
    # bar to make the implied multiplication visually clear.
    while True:
        converted = re.sub(
            r"\\sqrt\{([^{}]*)\}",
            lambda m: "&#8730;(" + m.group(1) + ")",
            s,
        )
        converted = re.sub(
            r"(?<=[A-Za-z0-9)>])(?=\\t?frac\{)",
            "&#183;",
            converted,
        )
        converted = re.sub(
            r"\\t?frac\{([^{}]*)\}\{([^{}]*)\}",
            _frac,
            converted,
        )
        if converted == s:
            break
        s = converted
    for k in sorted(_LATEX_CMD, key=len, reverse=True):
        s = s.replace(k, _LATEX_CMD[k])
    s = re.sub(r"_([A-Za-z0-9])", r"<sub>\1</sub>", s)
    s = re.sub(r"\^([A-Za-z0-9*])", r"<super>\1</super>", s)
    operators = "|".join(_LATEX_WORD_OPERATORS)
    # TeX inserts operator spacing automatically. Use non-breaking gaps on both
    # sides so adjacent terms remain visibly separated. Match any operator
    # sub/superscript as part of the operator, keeping log_10 and cot^2 attached.
    script = r"((?:<(?:sub|super)>[^<>]*</(?:sub|super)>)*)"
    s = re.sub(
        rf"\\({operators})\b{script}",
        lambda match: (
            f"&nbsp;{match.group(1)}{match.group(2)}&nbsp;"
        ),
        s,
    )
    s = s.removeprefix("&nbsp;")
    converted = s.replace("{", "").replace("}", "").replace("\\", "")
    # In explicit mathematics, e/E can be a variable next to coefficients.
    # Shield that symbol from the prose scientific-number normalizer.
    converted = re.sub(
        r"(?<=\d)([eE])(?=[+-]?\d)",
        lambda match: f"&#{ord(match.group(1))};",
        converted,
    )
    return normalize_trusted_markup(converted)


def _inline_md_to_rl(text: str) -> str:
    """Inline Markdown (emphasis, bold and math) -> ReportLab inline markup.
    The literal ``<``/``>``/``&`` are escaped first so the introduced tags stay
    valid, then the supported spans reintroduce real markup."""
    from publication_notation import shield_literal_markup

    code_fragments = []

    def _stash_code(match):
        token = f"\ue002{len(code_fragments)}\ue003"
        literal = shield_literal_markup(match.group(1))
        code_fragments.append((token, f'<font name="Courier">{literal}</font>'))
        return token

    text = re.sub(r"`([^`]+)`", _stash_code, str(text))
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(
        r"\[([^\]]+)\]\(#([A-Za-z0-9_-]+)\)",
        r'<link href="#\2">\1</link>',
        text,
    )
    text = re.sub(r"\$([^$]+)\$", lambda m: _latex_to_rl(m.group(1)), text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", text)
    text = normalize_trusted_markup(text)
    # Compact rises preserve scripts within multiline body and caption leading.
    text = text.replace("<sub>", '<sub rise="25%">').replace(
        "<super>", '<super rise="35%">'
    )
    for token, fragment in code_fragments:
        text = text.replace(token, fragment)
    return text


def _manual_equation_anchor(number: str) -> str:
    return "equation-" + number.casefold()


def _manual_heading_key(
    outline: str,
    level: int,
    ordinal: int,
    used: set[str],
) -> str:
    """Return one stable PDF/HTML destination for an authored heading."""

    key = manual_ia.heading_anchor(_strip_num(outline), level)
    if key is None or key in used:
        key = f"manual-section-{ordinal}"
    used.add(key)
    return key


def _manual_equation_results_markdown(equation) -> str:
    rows = (
        f"${term.markup}$ - {term.meaning} (`{term.unit}`)"
        for term in equation.contract.results
    )
    return "**Result:** " + "; ".join(rows)


def _manual_equation_dependencies_markdown(equation) -> str:
    numbers = dependency_numbers(equation)
    if not numbers:
        return ""
    links = (
        f"[Equation {number}](#{_manual_equation_anchor(number)})"
        for number in numbers
    )
    return "**Uses:** " + ", ".join(links)


def _manual_equation_symbols_markdown(equation) -> str:
    rows = ["| Symbol | Meaning | Unit |", "| --- | --- | --- |"]
    rows.extend(
        f"| ${term.markup}$ | {term.meaning} | `{term.unit}` |"
        for term in equation.contract.symbols
    )
    return "\n".join(rows)


def _render_md_pdf(text, flow, styles, Paragraph):
    """Render a Markdown block (paragraphs, ``- ``/``1.`` lists, standalone
    ``$$display$$`` formulas) to ReportLab flowables."""
    buf = []
    numbered = []
    first_flowable = len(flow)

    def flush_numbered():
        if numbered:
            # Keep a short sequence together without nesting a layout group.
            # This lets a preceding heading join the same keep-with-next chain.
            for paragraph in numbered[:-1]:
                paragraph.keepWithNext = True
            flow.extend(numbered)
            numbered.clear()

    def flush():
        if buf:
            text = " ".join(buf).strip()
            paragraph = Paragraph(_inline_md_to_rl(text), styles["MBody"])
            if (re.fullmatch(r"\*\*[^*]+\*\*", text)
                    or text.startswith("**Before:**")
                    or text.endswith(":")):
                paragraph.keepWithNext = True
            paragraph._manual_link_only = bool(
                re.fullmatch(r"\[[^\]]+\]\(#[A-Za-z0-9_-]+\)", text)
            )
            flow.append(paragraph)
            buf.clear()

    for line in text.split("\n"):
        s = line.strip()
        if not s:
            flush()
            flush_numbered()
            continue
        # A standalone display equation, tolerating trailing sentence punctuation
        # outside the closing ``$$`` so it still renders as centred math.
        m_disp = re.match(r"^\$\$(.+)\$\$([.,;:]?)$", s)
        if m_disp:
            flush()
            flush_numbered()
            body = _latex_to_rl(m_disp.group(1).strip()) + m_disp.group(2)
            flow.append(Paragraph(body, styles["MMath"]))
            continue
        mb = re.match(r"^[-*]\s+(.*)", s)
        mn = re.match(r"^(\d+)\.\s+(.*)", s)
        if mb:
            flush()
            flush_numbered()
            flow.append(Paragraph("&bull;&nbsp; " + _inline_md_to_rl(mb.group(1)),
                                  styles["MBody"]))
        elif mn:
            flush()
            numbered.append(Paragraph(f"{mn.group(1)}.&nbsp; "
                                      + _inline_md_to_rl(mn.group(2)), styles["MBody"]))
        else:
            flush_numbered()
            buf.append(s)
    flush()
    flush_numbered()
    # Keep consecutive navigation links together at the end of a workflow.
    for current, following in zip(flow[first_flowable:], flow[first_flowable + 1:]):
        if (getattr(current, "_manual_link_only", False)
                and getattr(following, "_manual_link_only", False)):
            current.keepWithNext = True


def _render_manual_equation_pdf(
    equation,
    compiled_equation,
    flow,
    styles,
    Paragraph,
    Table,
    TableStyle,
    KeepTogether,
    Spacer,
    colors,
    page_w,
):
    """Render one exact contracted equation as a standard PDF block."""

    contract = equation.contract
    compiled_source, equation_flowable = compiled_equation
    if compiled_source != equation:
        raise ValueError(
            f"Compiled manual equation identity changed for {contract.key!r}."
        )
    anchor = _manual_equation_anchor(contract.number)
    heading = (
        f'<a name="{anchor}"/><b>Equation {contract.number}</b> | '
        f"{_inline_md_to_rl(contract.dimensional_class)}"
    )
    results = "; ".join(
        f"{_latex_to_rl(term.markup)} - {_inline_md_to_rl(term.meaning)} "
        f"[{_latex_to_rl(term.unit)}]"
        for term in contract.results
    )
    dependencies = dependency_numbers(equation)
    metadata = [
        Paragraph(heading, styles["MBody"]),
        equation_flowable,
        Paragraph(f"<b>Result:</b> {results}", styles["MSmall"]),
    ]
    if dependencies:
        dependency_links = ", ".join(
            f'<link href="#{_manual_equation_anchor(number)}">'
            f"Equation {number}</link>"
            for number in dependencies
        )
        metadata.append(
            Paragraph(f"<b>Uses:</b> {dependency_links}", styles["MSmall"])
        )
    metadata.append(
        Paragraph(
            f"<b>{source_kind_label(equation)}:</b> "
            f"{_inline_md_to_rl(equation.equation.source.source_text)}",
            styles["MSmall"],
        )
    )
    # A flat keep chain also includes a preceding prose heading. Nesting a
    # KeepTogether here can strand that heading at the preceding page bottom.
    for item in metadata[:-1]:
        item.keepWithNext = True
    flow.extend(metadata)

    data = [[Paragraph(f"<b>Symbols - Equation {contract.number}</b>", styles["MSmall"]), "", ""], [
        Paragraph("<b>Symbol</b>", styles["MSmall"]),
        Paragraph("<b>Meaning</b>", styles["MSmall"]),
        Paragraph("<b>Unit</b>", styles["MSmall"]),
    ]]
    data.extend(
        [
            Paragraph(_latex_to_rl(term.markup), styles["MSmall"]),
            Paragraph(_inline_md_to_rl(term.meaning), styles["MSmall"]),
            Paragraph(_latex_to_rl(term.unit), styles["MSmall"]),
        ]
        for term in contract.symbols
    )
    table = Table(
        data,
        colWidths=[0.22 * page_w, 0.58 * page_w, 0.20 * page_w],
        repeatRows=2,
        splitByRow=1,
        spaceBefore=3,
    )
    table.setStyle(TableStyle([
        ("SPAN", (0, 0), (-1, 0)),
        ("GRID", (0, 1), (-1, -1), 0.35,
         colors.HexColor(publication_theme.PALETTE.grid)),
        ("BACKGROUND", (0, 0), (-1, 1),
         colors.HexColor(publication_theme.PALETTE.manual_surface)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    flow.extend((table, Spacer(1, 6)))


def _compile_manual_equation_pdf_flowables(published_blocks, frame_width):
    """Compile and preflight every governed display before publication starts.

    The import is intentionally canonical and local: opening the Streamlit manual
    must not pull ReportLab's equation renderer into the application startup path.
    The returned association retains each complete contracted publication object,
    so a key cannot silently select a flowable compiled from another equation.
    """

    from dataclasses import replace

    from app import publication_equation_layout

    style = replace(
        publication_equation_layout.DEFAULT_EQUATION_STYLE,
        font_size=9.5,
        left_indent=0.0,
        right_indent=0.0,
        top_padding=6.0,
        bottom_padding=6.0,
        ink=publication_theme.PALETTE.ink,
        muted_ink=publication_theme.PALETTE.manual_muted,
        wrap_delimited_arguments=True,
    )
    compiled = {}
    governed_count = 0
    for published in published_blocks:
        block = published.block
        if block[0] != EQUATION_BLOCK:
            continue
        governed_count += 1
        equation = block[1]
        key = equation.contract.key
        if key in compiled:
            raise ValueError(f"Duplicate governed manual equation key: {key!r}.")
        expression = publication_equation_layout.compile_manual_math(
            equation.equation.equation.expression
        )
        equation_block = publication_equation_layout.EquationBlock(
            (
                publication_equation_layout.EquationLine(
                    "manual-expression",
                    expression,
                ),
            )
        )
        # Font, glyph, width and height failures are publication failures too.
        # Preflight all of them before a figure server or output canvas can start.
        publication_equation_layout.layout_equation(
            equation_block,
            frame_width,
            style=style,
        )
        compiled[key] = (
            equation,
            publication_equation_layout.EquationFlowable(
                equation_block,
                style=style,
            ),
        )
    if len(compiled) != governed_count:
        raise ValueError("Governed manual equation compilation is incomplete.")
    return compiled


_FIG_EXPORT_TIMEOUT_S = 30.0


class ManualFigureError(RuntimeError):
    """A requested figure could not be embedded in the issued manual."""


def _png_size(png):
    return int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")


def _fig_to_png(fig_callable, timeout=_FIG_EXPORT_TIMEOUT_S):
    """Render one manual figure through the shared process coordinator."""

    try:
        return publication_image_export.export_png(
            fig_callable(),
            scale=2,
            timeout=timeout,
            description="manual figure export",
        )
    except Exception as exc:
        raise ManualFigureError(
            "Manual figure export failed; manual not created."
        ) from exc


def _manual_pdf_styles(
    report, colors, ParagraphStyle, getSampleStyleSheet, align_center
):
    """Build the manual PDF styles without importing ReportLab at module load."""
    report._styles()                 # register the bundled Greek-capable font
    font, font_b = report._FONT, report._FONT_BOLD
    styles = getSampleStyleSheet()

    def _add(name, **kw):
        if name not in styles.byName:
            styles.add(ParagraphStyle(name=name, parent=styles["Normal"], **kw))

    def themed(name, role, **extra):
        values = publication_theme.reportlab_style_values(
            publication_theme.MANUAL_TEXT[role],
            font,
            font_b,
            colors.HexColor,
        )
        values.update(extra)
        _add(name, **values)

    themed("MTitle", "title")
    themed("MPart", "part", keepWithNext=True)
    themed("MH1", "h1", keepWithNext=True)
    themed("MH2", "h2", keepWithNext=True)
    themed("MH3", "h3", keepWithNext=True)
    themed("MBody", "body", allowWidows=0, allowOrphans=0)
    themed("MMath", "math", alignment=align_center)
    themed("MSmall", "small")
    themed("MPubRef", "publication_ref")
    themed("MPubCaption", "publication_caption")
    return styles


def build_manual_pdf(buffer, figures=True):
    """Render the manual to ``buffer`` as a PDF over the same content blocks.

    ``figures=False`` deliberately publishes placeholders without launching
    Kaleido.  With ``figures=True`` every requested image is mandatory and any
    exporter failure aborts before a partial PDF is written to ``buffer``.
    """
    import sector_report as report
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (CondPageBreak, Image, KeepTogether, PageBreak, Paragraph,
                                    SimpleDocTemplate, Spacer, Table, TableStyle)
    from reportlab.platypus.tableofcontents import TableOfContents

    published_blocks = tuple(
        publish_manual_blocks(manual_publication_blocks(manual_blocks()))
    )
    # ReportLab's default frame consumes 6 pt of padding at each side in
    # addition to the document margins. Preflight the exact usable width.
    equation_frame_w = A4[0] - 3.7 * cm - 12.0
    compiled_equations = _compile_manual_equation_pdf_flowables(
        published_blocks,
        equation_frame_w,
    )

    styles = _manual_pdf_styles(
        report, colors, ParagraphStyle, getSampleStyleSheet, TA_CENTER
    )
    toc_part_style = ParagraphStyle(
        "MTOCPart", parent=styles["MBody"], fontSize=9.5, leading=12,
        leftIndent=0, firstLineIndent=0, spaceBefore=5, spaceAfter=3,
    )
    toc_h1_style = ParagraphStyle(
        "MTOCH1", parent=toc_part_style, leftIndent=12, spaceBefore=2,
        spaceAfter=2,
    )
    toc_h2_style = ParagraphStyle(
        "MTOCH2", parent=toc_part_style, leftIndent=24, fontSize=9.5,
        leading=12, spaceBefore=1, spaceAfter=1,
    )

    class _ManualDocTemplate(SimpleDocTemplate):
        def afterFlowable(self, flowable):
            key = getattr(flowable, "_manual_bookmark", None)
            if key:
                self.canv.bookmarkPage(key)
                self.canv.addOutlineEntry(
                    getattr(flowable, "_manual_outline", key),
                    key,
                    level=getattr(flowable, "_manual_level", 0),
                    closed=False,
                )
                if getattr(flowable, "_manual_toc_entry", False):
                    title = getattr(flowable, "_manual_outline", key)
                    level = min(int(getattr(flowable, "_manual_level", 0)), 2)
                    summary = _PART_SUMMARIES.get(title, "") if level == 0 else ""
                    entry = f"<b>{_inline_md_to_rl(title)}</b>"
                    if summary:
                        entry += (
                            "<br/><font size=\"9.5\" color=\"#5A5A5A\">"
                            f"{_inline_md_to_rl(summary)}</font>"
                        )
                    self.notify(
                        "TOCEntry", (level, entry, self.page, key)
                    )
                if getattr(flowable, "_manual_level", None) == 0:
                    self.canv._header = getattr(
                        flowable, "_manual_outline", "Sector user manual"
                    )

    bookmark_no = 0
    bookmark_keys = set()

    def _heading(text, style, outline, level, toc_entry=False):
        nonlocal bookmark_no
        bookmark_no += 1
        paragraph = Paragraph(text, style)
        plain_outline = _strip_num(outline)
        key = _manual_heading_key(
            plain_outline, level, bookmark_no, bookmark_keys
        )
        paragraph._manual_bookmark = key
        paragraph._manual_outline = plain_outline
        paragraph._manual_level = level
        paragraph._manual_toc_entry = toc_entry
        return paragraph

    page_w = 16.5 * cm
    flow = [
        Paragraph("Sector user manual", styles["MTitle"]),
        Paragraph(f"Version {APP_VERSION}", styles["MSmall"]),
        Paragraph(f"Author: {APP_AUTHOR}", styles["MSmall"]),
        Paragraph(f"Proprietary software; licensed to {APP_LICENSEE} for internal use.",
                  styles["MSmall"]),
        Spacer(1, 0.3 * cm),
        Paragraph("What Sector computes, the theory it applies, its features, and "
                  "how to use it.", styles["MBody"]),
        Spacer(1, 0.4 * cm),
    ]
    contents = TableOfContents(
        levelStyles=[toc_part_style, toc_h1_style, toc_h2_style],
        dotsMinLevel=0,
        rightColumnWidth=1.2 * cm,
    )
    flow.extend([
        Paragraph("Contents", styles["MH1"]),
        Paragraph(
            "Select a part name or page number to open it.", styles["MSmall"]
        ),
        contents,
        PageBreak(),
    ])

    # Every requested figure is mandatory.  The shared coordinator serializes
    # startup and exports with report generation; any indeterminate operation
    # aborts before ReportLab receives the output buffer.
    n1 = n2 = 0
    figure_cache = {}
    if figures:
        try:
            publication_image_export.ensure_ready(
                timeout=_FIG_EXPORT_TIMEOUT_S
            )
        except publication_image_export.KaleidoExportError as exc:
            raise ManualFigureError(
                "Manual figure exporter could not start; manual not created."
            ) from exc
    for index, published in enumerate(published_blocks):
        block = published.block
        item = published.item
        kind = block[0]
        if kind == "part":
            if n1 or n2:
                flow.append(PageBreak())
            flow.append(Spacer(1, 0.3 * cm))
            flow.append(_heading(
                _inline_md_to_rl(block[1]), styles["MPart"], block[1], 0,
                toc_entry=True,
            ))
            n1 = n2 = 0
        elif kind == "h1":
            n1 += 1
            n2 = 0
            title = f"{n1}. " + _inline_md_to_rl(_strip_num(block[1]))
            flow.append(_heading(
                title, styles["MH1"], block[1], 1, toc_entry=True
            ))
        elif kind == "h2":
            if _strip_num(block[1]) == "Torsion (TRd, thin-walled tube)":
                flow.append(PageBreak())
            elif _strip_num(block[1]) == "Combined M-V-T interaction":
                # Keep room for the heading and its first applicability guidance.
                flow.append(CondPageBreak(7 * cm))
            n2 += 1
            title = f"{n1}.{n2} " + _inline_md_to_rl(_strip_num(block[1]))
            flow.append(_heading(
                title,
                styles["MH2"],
                block[1],
                2,
                toc_entry=manual_ia.heading_anchor(_strip_num(block[1]), 2)
                is not None,
            ))
        elif kind == "h3":
            flow.append(_heading(
                _inline_md_to_rl(_strip_num(block[1])),
                styles["MH3"], block[1], 3,
            ))
        elif kind == "md":
            _render_md_pdf(block[1], flow, styles, Paragraph)
            if (index + 1 < len(published_blocks)
                    and published_blocks[index + 1].block[0] == "table"
                    and flow and isinstance(flow[-1], Paragraph)):
                flow[-1].keepWithNext = 1
        elif kind == EQUATION_BLOCK:
            key = block[1].contract.key
            if key not in compiled_equations:
                raise ValueError(
                    f"Governed manual equation was not precompiled: {key!r}."
                )
            _render_manual_equation_pdf(
                block[1], compiled_equations[key], flow, styles,
                Paragraph, Table, TableStyle,
                KeepTogether, Spacer, colors, page_w,
            )
        elif kind == "callout":
            _icon, ttl = _CALLOUT.get(block[1], ("", "Note"))
            inner = []
            _render_md_pdf(f"**{ttl}:** " + block[2], inner, styles, Paragraph)
            t = Table([[inner]], colWidths=[page_w])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(
                    publication_theme.PALETTE.manual_callout_surface
                )),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(
                    publication_theme.PALETTE.manual_rule
                )),
                ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
            flow.append(KeepTogether([t]))
            flow.append(Spacer(1, 0.15 * cm))
        elif kind == "figure":
            if item is None:
                raise ValueError("A published manual figure has no identity.")
            caption = Paragraph(
                f'<a name="{item.anchor}"/><b>{item.label}.</b> '
                f"{_inline_md_to_rl(item.caption)}",
                styles["MPubCaption"],
            )
            if block[1] in figure_cache:
                png = figure_cache[block[1]]
            else:
                png = None
                if figures:
                    png = _fig_to_png(block[1])
                figure_cache[block[1]] = png
            if png:
                w, h = _png_size(png)
                img_h = page_w * (h / w) if w else 8 * cm
                figure_rows = [
                    [Image(io.BytesIO(png), width=page_w, height=img_h)],
                    [caption],
                ]
            else:
                figure_rows = [
                    [Paragraph("[figure unavailable]", styles["MSmall"])],
                    [caption],
                ]
            figure_table = Table(
                figure_rows,
                colWidths=[page_w],
                hAlign="LEFT",
                splitByRow=0,
                splitInRow=0,
            )
            figure_table.setStyle(TableStyle([
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            figure_table._sector_publication_label = item.label
            flow.append(figure_table)
            flow.append(Spacer(1, 0.2 * cm))
        elif kind == "table":
            if item is None:
                raise ValueError("A published manual table has no identity.")
            headers, rows = block[1], block[2]
            ncol = len(headers)
            caption_markup = (
                f'<a name="{item.anchor}"/><b>{item.label}.</b> '
                f"{_inline_md_to_rl(item.caption)}"
            )
            continued_caption_markup = (
                f"<b>{item.label} (continued).</b> "
                f"{_inline_md_to_rl(item.caption)}"
            )
            data = [[Paragraph(caption_markup, styles["MPubCaption"])]
                    + [""] * (ncol - 1)]
            data += [[Paragraph(f"<b>{_inline_md_to_rl(h)}</b>", styles["MSmall"])
                      for h in headers]]
            data += [[Paragraph(_inline_md_to_rl(str(c)), styles["MSmall"]) for c in row]
                     for row in rows]
            t = report._PaginatedReportTable(
                data,
                colWidths=[page_w / ncol] * ncol,
                # Both captions share one fixed height. A longer continuation
                # label can then wrap without covering the repeated header.
                rowHeights=[
                    max(
                        Paragraph(markup, styles["MPubCaption"]).wrap(
                            page_w - 12, 10000
                        )[1]
                        for markup in (caption_markup, continued_caption_markup)
                    ) + 10,
                    *([None] * (len(data) - 1)),
                ],
                hAlign="LEFT",
                repeatRows=2,
                splitByRow=1,
                splitInRow=0,
                spaceBefore=2,
            )
            t._sector_caption_row = 0
            t._sector_caption_markup = caption_markup
            t._sector_continued_caption_markup = continued_caption_markup
            t._sector_caption_style = styles["MPubCaption"]
            t._sector_is_continuation = False
            t._sector_publication_label = item.label
            t._sector_header_row = 1
            t._sector_data_start = 2
            t._sector_force_page_break_between_fragments = True
            t.setStyle(TableStyle([
                ("SPAN", (0, 0), (-1, 0)),
                ("GRID", (0, 1), (-1, -1), 0.4, colors.HexColor(
                    publication_theme.PALETTE.grid
                )),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(
                    publication_theme.PALETTE.manual_surface
                )),
                ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor(
                    publication_theme.PALETTE.manual_surface
                )),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, 0), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
            flow.append(t)
            flow.append(Spacer(1, 0.2 * cm))

    footer = f"Sector v{APP_VERSION} - user manual"
    doc = _ManualDocTemplate(buffer, pagesize=A4, leftMargin=1.85 * cm,
                             rightMargin=1.85 * cm, topMargin=2 * cm,
                             bottomMargin=2 * cm,
                             title=f"Sector user manual v{APP_VERSION}",
                             author=APP_AUTHOR,
                             subject=(
                                 "Sector cross-section analysis user manual, input "
                                 "reference, methods and limitations"
                             ),
                             keywords=(
                                 "Sector, structural engineering, cross-section, "
                                 "reinforced concrete, user manual"
                             ),
                             lang="en")
    doc.multiBuild(flow, canvasmaker=lambda *a, **k: report._NumberedCanvas(
        *a,
        footer=footer,
        header="Sector user manual",
        revision=None,
        **k,
    ))


def build_manual_pdf_bytes(figures=True):
    buf = io.BytesIO()
    build_manual_pdf(buf, figures=figures)
    buf.seek(0)
    return buf.getvalue()


# ==========================================================================
# ACCESSIBLE HTML RENDERER -- same governed content, no JavaScript
# ==========================================================================


def _html_math_parts(expression: str) -> tuple[str, str]:
    """Return safe rendered math and its clean plain-text accessible name."""

    rendered = _latex_to_rl(html.escape(str(expression), quote=False)).replace(
        "<super>", "<sup>"
    ).replace("</super>", "</sup>")
    plain = html.unescape(re.sub(r"<[^>]+>", "", rendered)).replace("\xa0", " ")
    plain = re.sub(r"\s+", " ", plain).strip()
    if not plain:
        raise ValueError("A manual mathematical expression cannot be empty.")
    return rendered, plain


def _math_code_html(expression: str) -> str:
    rendered, plain = _html_math_parts(expression)
    label = html.escape(f"Mathematical expression: {plain}", quote=True)
    return f'<code class="math" aria-label="{label}">{rendered}</code>'


def _inline_md_to_html(text: str) -> str:
    """Render the manual's bounded inline Markdown subset as safe HTML."""

    math_fragments = []
    code_fragments = []

    def _stash_code(match):
        token = f"\ue002{len(code_fragments)}\ue003"
        code_fragments.append((token, f"<code>{html.escape(match.group(1))}</code>"))
        return token

    def _stash_math(match):
        index = len(math_fragments)
        token = f"\ue000{index}\ue001"
        math_fragments.append((token, _math_code_html(match.group(1))))
        return token

    source = re.sub(r"`([^`]+)`", _stash_code, str(text))
    source = re.sub(r"\$([^$\n]+)\$", _stash_math, source)
    rendered = html.escape(source, quote=True)
    rendered = re.sub(
        r"\[([^\]]+)\]\(#([A-Za-z0-9_-]+)\)",
        r'<a href="#\2">\1</a>',
        rendered,
    )
    rendered = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", rendered)
    rendered = re.sub(
        r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", rendered
    )
    for token, fragment in math_fragments + code_fragments:
        rendered = rendered.replace(token, fragment)
    return rendered


def _markdown_block_html(text: str) -> str:
    """Render paragraphs, lists and standalone equations without a JS runtime."""

    output = []
    paragraph = []
    list_kind = None
    list_items = []

    def flush_paragraph():
        if paragraph:
            output.append(
                "<p>" + _inline_md_to_html(" ".join(paragraph).strip()) + "</p>"
            )
            paragraph.clear()

    def flush_list():
        nonlocal list_kind
        if list_kind is not None:
            output.append(
                f"<{list_kind}>"
                + "".join(
                    "<li>" + _inline_md_to_html(item) + "</li>"
                    for item in list_items
                )
                + f"</{list_kind}>"
            )
            list_kind = None
            list_items.clear()

    for line in str(text).splitlines():
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            flush_list()
            continue
        display = re.match(r"^\$\$(.+)\$\$([.,;:]?)$", stripped)
        if display:
            flush_paragraph()
            flush_list()
            expression = display.group(1).strip()
            _rendered_math, plain_math = _html_math_parts(expression)
            output.append(
                '<div class="display-math" role="math" aria-label="'
                + html.escape(
                    f"Mathematical expression: {plain_math}", quote=True
                )
                + '">'
                + _math_code_html(expression)
                + html.escape(display.group(2))
                + "</div>"
            )
            continue
        bullet = re.match(r"^[-*]\s+(.*)", stripped)
        numbered = re.match(r"^\d+\.\s+(.*)", stripped)
        if bullet or numbered:
            flush_paragraph()
            target_kind = "ul" if bullet else "ol"
            if list_kind not in (None, target_kind):
                flush_list()
            list_kind = target_kind
            list_items.append((bullet or numbered).group(1))
            continue
        flush_list()
        paragraph.append(stripped)
    flush_paragraph()
    flush_list()
    return "\n".join(output)


def _manual_html_heading_records(published_blocks):
    """Return PDF-identical heading identities plus the visible TOC entries."""

    records = {}
    toc = []
    used = set()
    ordinal = 0
    n1 = n2 = 0
    for index, published in enumerate(published_blocks):
        block = published.block
        kind = block[0]
        if kind not in ("part", "h1", "h2", "h3"):
            continue
        ordinal += 1
        if kind == "part":
            n1 = n2 = 0
            level = 0
            display = block[1]
        elif kind == "h1":
            n1 += 1
            n2 = 0
            level = 1
            display = f"{n1}. {_strip_num(block[1])}"
        elif kind == "h2":
            n2 += 1
            level = 2
            display = f"{n1}.{n2} {_strip_num(block[1])}"
        else:
            level = 3
            display = _strip_num(block[1])
        key = _manual_heading_key(block[1], level, ordinal, used)
        toc_entry = kind in ("part", "h1") or (
            kind == "h2"
            and manual_ia.heading_anchor(_strip_num(block[1]), 2) is not None
        )
        record = (level, key, display)
        records[index] = record
        if toc_entry:
            toc.append(record)
    return records, tuple(toc)


def _manual_equation_html(equation) -> str:
    """Publish one governed equation with selectable semantic alternatives."""

    number = equation.contract.number
    expression = _math_code_html(equation.equation.equation.expression)
    results = "".join(
        "<dt>"
        + _math_code_html(term.markup)
        + "</dt><dd>"
        + html.escape(term.meaning)
        + " ["
        + html.escape(term.unit)
        + "]</dd>"
        for term in equation.contract.results
    )
    dependencies = dependency_numbers(equation)
    uses = ""
    if dependencies:
        uses = (
            '<p class="equation-uses"><strong>Uses:</strong> '
            + ", ".join(
                f'<a href="#{_manual_equation_anchor(value)}">Equation '
                f"{html.escape(value)}</a>"
                for value in dependencies
            )
            + "</p>"
        )
    symbols = "".join(
        "<tr><th scope=\"row\">"
        + _math_code_html(term.markup)
        + "</th><td>"
        + html.escape(term.meaning)
        + "</td><td>"
        + html.escape(term.unit)
        + "</td></tr>"
        for term in equation.contract.symbols
    )
    return (
        f'<section class="equation" id="{_manual_equation_anchor(number)}">'
        f'<p class="equation-heading"><strong>Equation '
        f"{html.escape(number)}</strong></p>"
        '<p class="equation-text">'
        + expression
        + "</p>"
        + ("<dl class=\"equation-results\">" + results + "</dl>" if results else "")
        + uses
        + '<details><summary>Symbols and units</summary><table><thead><tr>'
        '<th scope="col">Symbol</th><th scope="col">Meaning</th>'
        '<th scope="col">Unit</th></tr></thead><tbody>'
        + symbols
        + "</tbody></table></details>"
        + '<p class="source"><strong>'
        + html.escape(source_kind_label(equation))
        + ":</strong> "
        + html.escape(equation.equation.source.source_text)
        + "</p></section>"
    )


def build_manual_html_bytes() -> bytes:
    """Build the self-contained, JavaScript-free accessible manual companion."""

    from manual_assets import figure_data_uri

    published_blocks = tuple(
        publish_manual_blocks(manual_publication_blocks(manual_blocks()))
    )
    heading_records, toc = _manual_html_heading_records(published_blocks)
    body = []
    for index, published in enumerate(published_blocks):
        block = published.block
        item = published.item
        kind = block[0]
        if kind in ("part", "h1", "h2", "h3"):
            level, key, display = heading_records[index]
            tag = ("h2", "h3", "h4", "h5")[level]
            body.append(
                f'<{tag} id="{key}">{_inline_md_to_html(display)}</{tag}>'
            )
        elif kind == "md":
            body.append(_markdown_block_html(block[1]))
        elif kind == EQUATION_BLOCK:
            body.append(_manual_equation_html(block[1]))
        elif kind == "callout":
            _icon, title = _CALLOUT.get(block[1], ("", "Note"))
            body.append(
                f'<aside class="callout {html.escape(block[1])}">'
                + _markdown_block_html(f"**{title}:** " + block[2])
                + "</aside>"
            )
        elif kind == "figure":
            if item is None:
                raise ValueError("A published manual figure has no identity.")
            alternative = published.alternative
            if not alternative or alternative.strip() == item.caption.strip():
                raise ValueError(
                    "A published manual figure requires a distinct text alternative."
                )
            caption = _inline_md_to_html(item.caption)
            alternative_label = re.sub(
                r"\$([^$\n]+)\$",
                lambda match: _html_math_parts(match.group(1))[1],
                alternative,
            )
            body.append(
                f'<figure id="{item.anchor}"><img class="manual-figure" '
                f'src="{figure_data_uri(block[1])}" alt="">'
                '<div class="figure-alternative" '
                f'role="img" aria-label="{html.escape(alternative_label, quote=True)}">'
                + _inline_md_to_html(alternative)
                + "</div><figcaption><strong>"
                + html.escape(item.label)
                + ".</strong> "
                + caption
                + "</figcaption></figure>"
            )
        elif kind == "table":
            if item is None:
                raise ValueError("A published manual table has no identity.")
            headers, rows = block[1], block[2]
            header_html = "".join(
                '<th scope="col">' + _inline_md_to_html(value) + "</th>"
                for value in headers
            )
            row_html = "".join(
                "<tr>"
                + "".join(
                    "<td>" + _inline_md_to_html(str(value)) + "</td>"
                    for value in row
                )
                + "</tr>"
                for row in rows
            )
            body.append(
                f'<figure class="table-figure" id="{item.anchor}"><figcaption>'
                f"<strong>{html.escape(item.label)}.</strong> "
                + _inline_md_to_html(item.caption)
                + "</figcaption><div class=\"table-scroll\"><table><thead><tr>"
                + header_html
                + "</tr></thead><tbody>"
                + row_html
                + "</tbody></table></div></figure>"
            )
        else:
            raise ValueError(f"Unsupported published manual block: {kind!r}.")

    toc_html = "".join(
        f'<li class="toc-level-{level}"><a href="#{key}">'
        f"{_inline_md_to_html(display)}</a></li>"
        for level, key, display in toc
    )
    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="author" content="{html.escape(APP_AUTHOR, quote=True)}">
<meta name="description" content="Sector cross-section analysis user manual, input reference, methods and limitations">
<meta name="keywords" content="Sector, structural engineering, cross-section, reinforced concrete, user manual">
<meta name="sector-version" content="{html.escape(APP_VERSION, quote=True)}">
<title>Sector user manual v{html.escape(APP_VERSION)}</title>
<style>
:root {{ color-scheme: light; --ink:#2c2c2a; --muted:#5a5a5a; --blue:#1f3b66; --surface:#eef2f7; --rule:#9fb3c8; }}
* {{ box-sizing:border-box; }}
body {{ margin:0 auto; padding:2rem; max-width:82ch; color:var(--ink); background:#fff; font:16px/1.5 Arial, sans-serif; }}
h1,h2,h3,h4,h5 {{ color:var(--blue); line-height:1.25; scroll-margin-top:1rem; }}
h1 {{ font-size:2rem; }} h2 {{ border-top:2px solid var(--rule); padding-top:1rem; }}
a {{ color:#0d4f8b; text-decoration-thickness:.1em; }}
.skip-link {{ position:absolute; left:1rem; top:1rem; z-index:10; padding:.65rem .9rem; background:#fff; border:2px solid var(--blue); transform:translateY(-180%); }}
.skip-link:focus {{ transform:translateY(0); }}
.document-control,.source,figcaption {{ color:var(--muted); }}
nav {{ border:1px solid var(--rule); background:var(--surface); padding:1rem 1.25rem; }}
nav ol {{ list-style:none; padding-left:0; }}
.toc-level-0 {{ font-weight:bold; margin-top:.8rem; }}
.toc-level-1 {{ margin-left:1rem; }} .toc-level-2 {{ margin-left:2rem; }}
table {{ width:100%; border-collapse:collapse; margin:.5rem 0 1.25rem; }}
th,td {{ border:1px solid #b5bdc6; padding:.45rem; text-align:left; vertical-align:top; }}
th {{ background:var(--surface); }} .table-scroll {{ overflow-x:auto; }}
.callout,.equation,figure {{ border:1px solid var(--rule); padding:1rem; margin:1rem 0; break-inside:avoid; }}
.display-math,.equation-text {{ overflow-wrap:anywhere; padding:.5rem; background:#f7f8fa; }}
.math {{ font-family:"Cambria Math","STIX Two Math","Times New Roman",serif; font-size:1.08em; }}
code {{ font-family:"Courier New", monospace; }}
.manual-figure {{ width:100%; height:auto; display:block; }}
.figure-alternative {{ padding:.4rem 0; color:var(--muted); font-size:.9rem; }}
@media print {{ body {{ max-width:none; padding:1cm; }} a {{ color:inherit; }} }}
</style>
</head>
<body>
<a class="skip-link" href="#manual-main">Skip to main content</a>
<header>
<h1>Sector user manual</h1>
<p class="document-control"><strong>Version:</strong> {html.escape(APP_VERSION)}<br>
<strong>Author:</strong> {html.escape(APP_AUTHOR)}<br>
Proprietary software; licensed to {html.escape(APP_LICENSEE)} for internal use.</p>
<p>What Sector computes, the theory it applies, its features, and how to use it.</p>
</header>
<nav aria-label="Manual contents"><h2>Contents</h2><ol>{toc_html}</ol></nav>
<main id="manual-main">{''.join(body)}</main>
</body>
</html>
"""
    return document.encode("utf-8")


# ==========================================================================
# STREAMLIT RENDERER
# ==========================================================================

def _render_manual_equation_streamlit(equation) -> None:
    """Render one exact contracted equation with on-demand semantic detail."""

    number = equation.contract.number
    st.markdown(f"##### Equation {number}")
    st.caption(f"Dimensional class: {equation.contract.dimensional_class}")
    st.markdown(f"$$\n{equation.equation.equation.expression}\n$$")
    st.markdown(_manual_equation_results_markdown(equation))
    dependencies = _manual_equation_dependencies_markdown(equation)
    if dependencies:
        st.markdown(dependencies)
    st.caption(
        f"{source_kind_label(equation)}: "
        f"{equation.equation.source.source_text}"
    )
    with st.expander(
        f"Symbols and units - Equation {number}", expanded=False
    ):
        st.markdown(_manual_equation_symbols_markdown(equation))


def render_manual_streamlit():
    """Render the selected manual part and its PDF actions."""
    with st.container(horizontal=True):
        if st.button(
            "Generate PDF", key="manual_gen_pdf", icon=":material/picture_as_pdf:"
        ):
            with st.spinner("Building the PDF and accessible HTML manuals..."):
                try:
                    st.session_state["manual_pdf"] = build_manual_pdf_bytes()
                    st.session_state["manual_html"] = build_manual_html_bytes()
                except Exception:                        # never break the dialog
                    _LOGGER.exception("Manual generation failed")
                    st.session_state["manual_pdf"] = None
                    st.session_state["manual_html"] = None
                    st.error(
                        "Manual generation failed. Try again. If the problem "
                        "continues, report the steps that produced it."
                    )
        if st.session_state.get("manual_pdf"):
            st.download_button(
                "Download PDF", st.session_state["manual_pdf"],
                file_name="Sector_User_Manual.pdf", mime="application/pdf",
                key="manual_dl_pdf", icon=":material/download:",
            )
        if st.session_state.get("manual_html"):
            st.download_button(
                "Download accessible HTML",
                st.session_state["manual_html"],
                file_name="Sector_User_Manual.html",
                mime="text/html",
                key="manual_dl_html",
                icon=":material/download:",
            )
        if st.button("Close", key="manual_close", icon=":material/close:"):
            st.session_state["_manual_open"] = False
            st.rerun(scope="app")

    st.caption("What Sector computes, the theory it applies, its features, and how "
               "to use it.")

    parts = manual_published_item_parts()
    selected_part = st.selectbox(
        "Manual part",
        list(parts),
        key="manual_part",
        help="Only the selected part is rendered; the PDF contains the full manual.",
    )
    st.caption(_PART_SUMMARIES[selected_part])

    n1 = n2 = 0
    for i, published in enumerate(parts[selected_part]):
        block = published.block
        item = published.item
        kind = block[0]
        if kind == "part":
            st.divider()
            st.markdown(f"# {block[1]}")
            n1 = n2 = 0
        elif kind == "h1":
            n1 += 1
            n2 = 0
            st.markdown(f"## {n1}. {_strip_num(block[1])}")
        elif kind == "h2":
            n2 += 1
            st.markdown(f"### {n1}.{n2} {_strip_num(block[1])}")
        elif kind == "h3":
            st.markdown(f"#### {_strip_num(block[1])}")
        elif kind == "md":
            st.markdown(block[1])
        elif kind == EQUATION_BLOCK:
            _render_manual_equation_streamlit(block[1])
        elif kind == "callout":
            icon, title = _CALLOUT.get(block[1], (":information_source:", "Note"))
            with st.container(border=True):
                st.markdown(f"{icon} **{title}**\n\n{block[2]}")
        elif kind == "figure":
            if item is None:
                raise ValueError("A published manual figure has no identity.")
            st.markdown(f"##### {item.label}")
            try:
                # A unique key per block: two structurally-similar figures would
                # otherwise share an auto-generated element id and Streamlit raises a
                # duplicate-id error (seen once other charts exist, e.g. after Calculate).
                st.plotly_chart(block[1](), width="stretch", key=f"manual_fig_{i}")
            except Exception:                            # a broken figure must not
                _LOGGER.exception("Manual figure unavailable")
                st.caption(
                    "[Figure unavailable. Continue with the accompanying text "
                    "and tables, or regenerate the manual.]"
                )  # break the whole manual
            st.caption(item.caption)
        elif kind == "table":
            if item is None:
                raise ValueError("A published manual table has no identity.")
            st.markdown(f"##### {item.label}")
            st.caption(item.caption)
            header = "| " + " | ".join(block[1]) + " |"
            sep = "| " + " | ".join(["---"] * len(block[1])) + " |"
            body = "\n".join("| " + " | ".join(str(c) for c in row) + " |"
                             for row in block[2])
            st.markdown(f"{header}\n{sep}\n{body}")


def _dismiss_manual_dialog() -> None:
    """Clear the durable open flag when the dialog is dismissed with X or Esc."""
    st.session_state["_manual_open"] = False


@st.dialog(
    "Sector user manual",
    width="large",
    icon=":material/menu_book:",
    on_dismiss=_dismiss_manual_dialog,
)
def render_manual_dialog():
    """Show the manual above the current workspace in a fragment-scoped dialog."""
    render_manual_streamlit()
