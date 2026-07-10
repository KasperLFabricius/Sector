"""Sector user manual.

Single source of truth for the manual content. The content is authored as a
list of structured blocks (headings, markdown, callouts, figures, tables) so it
can be rendered both in the app (:func:`render_manual_streamlit`) and -- in a
later step -- to a downloadable PDF over the same blocks.

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

import io
import re
import threading

import plotly.graph_objects as go
import streamlit as st

from sector import __version__ as APP_VERSION
from sector import templates
from sector.codes import fctm
from sector.materials import Concrete, MildSteel, Prestress
from sector.plastic import solve_plastic
from sector.section import Section
from sector.serviceability import analyse_cracking

import viz

# Display scale for the section drawings: the geometry is in metres, drawn in mm.
_MM = 1000.0


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
    steel = MildSteel(fytk=550.0, fyck=550.0, futk=550.0, eut=0.05,
                      gamma_y=1.20, gamma_u=1.20, gamma_E=1.20, curve=2)
    return {
        "name": "Rectangular beam (mild steel)",
        "outer": outer, "holes": [], "bars": bars, "tendons": [],
        "concrete": concrete, "steel": steel, "prestress": None,
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
    steel = MildSteel(fytk=550.0, fyck=550.0, futk=550.0, eut=0.05,
                      gamma_y=1.20, gamma_u=1.20, gamma_E=1.20, curve=2)
    prestress = Prestress(curve=6, IS=0.005, fytk=1600.0, futk=1860.0, eut=0.035,
                          gamma_y=1.15, gamma_u=1.15, gamma_E=1.15, Es=195000.0)
    return {
        "name": "Circular hollow section (mild + prestress)",
        "outer": outer, "holes": [hole], "bars": bars, "tendons": tendons,
        "concrete": concrete, "steel": steel, "prestress": prestress,
        "P": 1500.0, "Mx": 600.0, "My": 0.0,
        "note": "800/400 mm annulus, C40/50; 12 x 20 mm mild ring + 8 tendons.",
    }


# ==========================================================================
# FIGURES -- live section drawings from the worked examples (reuse app viz)
# ==========================================================================

def _section_fig(ex: dict, title: str):
    bar_xy = [(x, y) for x, y, _ in ex["bars"]]
    tendon_xy = [(x, y) for x, y, _ in ex["tendons"]]
    return viz.section_figure(
        ex["outer"], ex["holes"], bar_xy, tendons=tendon_xy, title=title,
        show_labels=True, height=460, scale=_MM, unit="mm")


def fig_beam_section():
    return _section_fig(example_beam(), "Rectangular beam")


def fig_circular_section():
    return _section_fig(example_circular(), "Circular hollow section")


def _section_of(ex: dict) -> Section:
    return Section.from_polygon(corners=ex["outer"], holes=ex["holes"],
                                bars_xy_area_mm2=ex["bars"],
                                tendons_xy_area_mm2=ex["tendons"])


def fig_beam_concrete_law():
    return viz.concrete_curve_figure(example_beam()["concrete"])


def fig_beam_steel_law():
    return viz.steel_curve_figure(example_beam()["steel"])


def fig_circular_prestress_law():
    return viz.prestress_curve_figure(example_circular()["prestress"])


def fig_beam_envelope():
    """The rectangular example's M-M interaction envelope with its applied load."""
    ex = example_beam()
    pts = solve_plastic(_section_of(ex), ex["concrete"], ex["steel"], ex["P"],
                        0.0, 360.0, 15.0)
    mx = [p.Mx for p in pts]
    my = [p.My for p in pts]
    return viz.interaction_figure(mx, my, applied=(ex["Mx"], ex["My"]))


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
    na = viz.na_endpoints(st_.na_x_intercept, st_.na_y_intercept, 1.0)
    bar_xy = [(x, y) for x, y, _ in ex["bars"]]
    return viz.section_figure(ex["outer"], ex["holes"], bar_xy, na_line=na,
                              zones=zones, title="Cracked section (Stage II)",
                              show_labels=False, height=460, scale=_MM, unit="mm")


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
    fig.add_annotation(x=xs[-1], y=ys[-1], ax=xs[-4], ay=ys[-4], axref="x", ayref="y",
                       showarrow=True, arrowhead=2, arrowsize=1.4, arrowwidth=2.5,
                       arrowcolor=color, text="")


def fig_sign_convention():
    """Schematic of the centroidal axes and the positive senses of N, Mx, My and
    the neutral-axis sweep angle V."""
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
    # Lower-right of the centroid, clear of the (lower-left) neutral-axis line.
    fig.add_annotation(x=0.22, y=-0.32, text="N (+ tension, out of page)",
                       showarrow=False, xanchor="left", font=dict(size=11, color=ink))
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
    # The sweep angle V: a neutral axis at angle V from the +y axis, with an arc.
    vdeg = 35.0
    vr = math.radians(90.0 - vdeg)   # measured from +x for the geometry
    fig.add_shape(type="line", x0=-1.7 * math.cos(vr), y0=-1.7 * math.sin(vr),
                  x1=1.7 * math.cos(vr), y1=1.7 * math.sin(vr),
                  line=dict(color=viz.NA_LINE, width=1.5, dash="dash"))
    ts = [math.radians(90.0) - math.radians(90.0 - vr * 180.0 / math.pi) * i / 20.0
          for i in range(21)]
    fig.add_trace(go.Scatter(
        x=[0.9 * math.cos(t) for t in ts], y=[0.9 * math.sin(t) for t in ts],
        mode="lines", line=dict(color=viz.NA_LINE, width=1.2), hoverinfo="skip"))
    fig.add_annotation(x=0.62, y=1.15, text="V", showarrow=False,
                       font=dict(size=12, color=viz.NA_LINE))
    fig.add_annotation(x=1.55 * math.cos(vr), y=1.55 * math.sin(vr),
                       text="neutral axis (angle V from +y)", showarrow=False,
                       xanchor="left", xshift=6, font=dict(size=10, color=viz.NA_LINE))
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
    # red = compression (top), green = tension (bottom).
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


def _strip_num(text: str) -> str:
    """Drop a leading hardcoded section number so headings can be auto-numbered
    (lets a section be inserted without renumbering every following heading)."""
    return re.sub(r"^\s*\d+(?:\.\d+)*\.?\s+", "", text)


def manual_blocks() -> list:
    """The whole manual as a flat list of typed blocks (see the module header)."""
    blocks: list = []
    part = lambda t: blocks.append(("part", t))
    h1 = lambda t: blocks.append(("h1", t))
    h2 = lambda t: blocks.append(("h2", t))
    md = lambda t: blocks.append(("md", t))
    call = lambda kind, t: blocks.append(("callout", kind, t))
    fig = lambda fn, cap: blocks.append(("figure", fn, cap))
    table = lambda hdr, rows: blocks.append(("table", hdr, rows))

    # =====================================================================
    # PART A - GET STARTED
    # =====================================================================
    part("Part A - Get started")

    h1("Introduction & purpose")
    md("**Sector** is a cross-section analysis tool for reinforced-concrete and "
       "prestressed sections. You give it an arbitrary polygonal concrete outline "
       "(with any number of voids), the mild-steel bars and prestressing tendons, "
       "and the material laws; it returns the ultimate bending capacity, the "
       "cracked-section service stresses and the crack width, and it assembles a "
       "QA report you can hand in with a design.")
    md("The whole section lives on one screen. The drawing and the stress-strain "
       "diagrams update as you type; the result views recompute when you press "
       "*Calculate*.")
    call("concept", "Think of Sector as a solver for a single cut through a member. "
         "You draw the concrete, place the reinforcement, and it tells you how much "
         "moment the section can carry (ultimate) and how hard the concrete and "
         "steel are working under the service loads (cracking and crack width).")
    call("limit", "Sector analyses **one plane cross-section**. It assumes plane "
         "sections remain plane (a linear strain field) and perfect bond between "
         "concrete and steel; it does not do shear, torsion, buckling or "
         "member-level effects. Those are checked separately.")

    h2("What Sector computes - at a glance")
    md("- **Plastic bending capacity.** The biaxial $M_x$-$M_y$ interaction "
       "envelope at the given axial force, from the full nonlinear material laws, "
       "and the utilisation of an applied load against it.\n"
       "- **Cracked-section elastic stresses.** The concrete and reinforcement "
       "stresses under the long-term and short-term service loads, on the cracked "
       "(tension-ignored) section, with creep through the modular ratio.\n"
       "- **Serviceability.** Whether the section cracks under the service load, "
       "the transformed section properties, and the crack width to a choice of "
       "code editions.\n"
       "- **Reporting.** A one-click QA PDF with the worked formulas and their "
       "code references, plus a project file that saves the whole input set.")

    h1("Quick start")
    md("1. **Define the section.** Open the *Section* panel and either edit the "
       "point tables (concrete corners, voids, bars and tendons, all in mm) or "
       "press *Quick Section builder* to generate a parametric shape.\n"
       "2. **Set the materials.** In *Material Parameters* pick or enter the "
       "concrete, mild steel and (if any) prestress.\n"
       "3. **Choose the analyses.** In *Analysis settings* pick Plastic, "
       "Elastic or Both, and toggle the crack-width check.\n"
       "4. **Enter the loads.** Give the axial force and moments for the plastic "
       "utilisation and the service combinations.\n"
       "5. **Calculate.** Read the results in the *View* dropdown: the section, the "
       "stress-strain diagrams, the plastic envelope and the elastic stresses.\n"
       "6. **Export.** Generate the PDF report or download the project file.")
    fig(fig_beam_section, "The rectangular worked example as Sector draws it: the "
        "concrete corners and the bars are numbered. Turn on the point labels to "
        "see the numbering on your own section.")
    call("tip", "There is no separate run step for the drawing: the section and the "
         "stress-strain diagrams redraw as you edit. Only the result views (plastic "
         "and elastic) wait for *Calculate*.")

    h1("The worked examples")
    md("Two sections are threaded through this manual. Every worked derivation in "
       "Part C is carried out on one of them, and the figures are generated from "
       "them live, so the numbers you read here match what the app produces.")
    h2("Rectangular beam (mild steel)")
    md("A 300 x 600 mm rectangular section in C40/50 concrete with B550 "
       "reinforcement: three 25 mm bars near the bottom face and two 16 mm bars "
       "near the top. It is the simplest section that still exercises the plastic "
       "capacity, the cracked-elastic stresses and a crack width.")
    fig(fig_beam_section, "Rectangular beam: 3 x 25 mm bottom, 2 x 16 mm top.")
    h2("Circular hollow section (mild + prestress)")
    md("An 800 mm diameter circular section with a 400 mm central void, a ring of "
       "twelve 20 mm mild bars and a ring of eight prestressing tendons, in C40/50 "
       "concrete. It adds the void handling, the ring (biaxial) reinforcement "
       "layout and the prestress law on top of the beam.")
    fig(fig_circular_section, "Circular hollow section: a central void, a mild-bar "
        "ring and a tendon ring.")
    table(["Example", "Section", "Reinforcement", "Demonstrates"],
          [["Beam", "300 x 600 mm solid", "5 mild bars",
            "Plastic M-M, cracked elastic, crack width"],
           ["Circular hollow", "800/400 mm annulus", "12 mild + 8 tendons",
            "Voids, ring layout, prestress"]])

    h1("Common use cases")
    md("- **Ultimate capacity check.** Read the $M_x$-$M_y$ envelope at the design "
       "axial force and the utilisation of the applied moment.\n"
       "- **Biaxial column.** Sweep the neutral-axis angle to get the full biaxial "
       "interaction diagram, not just the two principal directions.\n"
       "- **Crack-width verification.** Check the service crack width against a "
       "limit, to whichever code edition applies to the job.\n"
       "- **Comparing layouts.** Change the bars or the concrete grade and read the "
       "capacity and crack width straight back.")

    # =====================================================================
    # PART B - FEATURES & OPTIONS
    # =====================================================================
    part("Part B - Features & options")

    h1("The workspace")
    md("The sidebar holds the input panels (*About*, *Save / Load*, *Report*, "
       "*Analysis settings*, *Section*, *Material Parameters*, *Loads*); "
       "the main area shows the drawings and results, chosen from the **View** "
       "dropdown. The section drawing and the stress-strain diagrams update live; "
       "the plastic and elastic result views recompute on **Calculate**.")
    table(["View", "Shows"],
          [["Section", "The concrete outline, voids and reinforcement (live)"],
           ["Stress-Strain diagrams", "The concrete, mild-steel and tendon laws (live)"],
           ["Plastic Results", "The M-M envelope and the utilisation (on Calculate)"],
           ["Elastic Results", "The cracked-section stresses and crack width (on Calculate)"],
           ["Shear", "The shear resistance $V_{Rd,c}$ and the utilisation (on Calculate)"]])
    call("tip", "*Auto-calc all derived values* (in Analysis settings) "
         "recomputes every auto quantity from the current grade at once: the concrete "
         "strain limits, $f_{ctm}$ and $E_c$. The modular ratios follow from $E_c$, "
         "$E_s$, $E_p$ and creep automatically.")

    h1("Defining the section")
    md("A section is a set of explicit points in millimetres -- the concrete "
       "corners, any voids, the bars and the tendons. The point tables are the "
       "**source of truth**; the Quick Section builder is a convenience that writes "
       "into them.")
    h2("The point tables")
    md("Four editable tables hold the concrete corners, the voids, the bars "
       "($x$, $y$, area) and the tendons ($x$, $y$, area). Coordinates are in "
       "millimetres and the bar and tendon **areas are in square millimetres** "
       "(the *area (mm2)* column) -- enter 314 for a 20 mm bar, not 20. A void is a "
       "closed ring of corners; several voids are separated by a blank row. "
       "Half-typed rows are ignored until complete, so the tables are "
       "paste-friendly.")
    call("concept", "Everything downstream reads these points. The builder, the "
         "presets and the save file all end up as rows in these four tables, so you "
         "can always edit the geometry by hand.")
    h2("The Quick Section builder")
    md("A full-width builder (opened from the *Section* panel) generates a "
       "parametric shape with a live preview, then *Apply* writes its points into "
       "the tables (or *Back* leaves them untouched). Reinforcement can be given by "
       "a bar count or by a spacing, in one or several layers, and tendons as a "
       "ring or in layers. The bottom and top faces take their own cover and bar "
       "diameter (entered directly in mm), a stacked upper layer can hold a "
       "different bar count than the main row, and a toggle measures the cover to "
       "the bar edge instead of its centre.")
    table(["Shape", "Produces"],
          [["Rectangle", "A solid rectangle b x h"],
           ["Slab strip", "A 1 m-wide strip of a given thickness"],
           ["T-section", "A flange over a web"],
           ["Box girder", "A hollow box (one rectangular void)"],
           ["Circular", "A circular section, optionally with a bar ring"]])
    h2("Validity checks")
    md("The section is rejected, with a message, when the geometry is not "
       "analysable: a void that would disconnect the concrete, or a bar or tendon "
       "that falls outside the concrete or inside a void.")
    call("limit", "A void must leave the concrete in one connected piece. A slot "
         "that splits the section in two is rejected rather than analysed, because "
         "the plane-section assumption no longer holds across a break.")

    h1("Materials")
    md("Each material can be entered by hand or loaded from a code preset, then "
       "adjusted. The presets carry the partial factors and the curve shape; the "
       "*Preset* dropdown at the top of each material sets them.")
    h2("Concrete")
    md("The concrete stress-strain law is chosen by the *Preset*: **Curve 2 "
       "(parabola-rectangle)**, the EC2 design law used throughout this manual, or "
       "**Curve 1 (cubic)**, the legacy cubic curve for normal-strength concrete. "
       "The inputs are the "
       "characteristic strength $f_{ck}$, the partial factor $\\gamma_c$, the "
       "coefficient $\\alpha_{cc}$, the strain limits $\\varepsilon_{c2}$ and "
       "$\\varepsilon_{cu2}$ with the exponent $n$, the elastic modulus $E_c$ and "
       "the mean tensile strength $f_{ctm}$. The strain limits, $E_c$ and $f_{ctm}$ "
       "have *Auto* buttons that derive them from $f_{ck}$ and the edition.")
    fig(fig_beam_concrete_law, "The concrete law for the rectangular example "
        "(C40/50), as the Stress-Strain view draws it.")
    h2("Mild steel")
    md("The mild steel is bilinear (optionally with hardening). The inputs are the "
       "yield and ultimate strengths $f_{yk}$ / $f_{tk}$, the ultimate strain "
       "$\\varepsilon_{uk}$, the partial factors and the modulus $E_s$. The "
       "**Active in compression** toggle decides whether the bars carry "
       "compression in the **plastic (ultimate)** law: with it off the steel is "
       "tension-only there. The cracked-elastic (service) analysis is linear and "
       "always treats the bars in both directions, regardless of this toggle.")
    fig(fig_beam_steel_law, "The B550 mild-steel law for the rectangular example.")
    call("standard", "The concrete and steel laws follow DS/EN 1992-1-1 3.1.7 and "
         "3.2.7; the ultimate strains follow Table 3.1. Part C derives them in full.")
    h2("Prestressing steel")
    md("A prestress material adds the tendon law and, crucially, the initial strain "
       "$\\varepsilon_{p,IS}$ locked into the tendons. The inputs mirror the mild "
       "steel plus that initial strain. Tendons are analysed at their **total** "
       "strain -- the initial strain plus the section strain at their location.")
    fig(fig_circular_prestress_law, "The tendon law for the circular example.")

    h1("Analysis & result settings")
    h2("Analysis mode")
    md("*Analysis* selects what runs: **Plastic** (the ultimate M-M envelope), "
       "**Elastic** (the cracked-section stresses for the service loads), or "
       "**Both**.")
    h2("The plastic sweep")
    md("The envelope is traced by rotating the neutral axis from $V_{min}$ to "
       "$V_{max}$ in steps of $V_{inc}$ (degrees). Each angle gives one point on "
       "the $M_x$-$M_y$ envelope at the design axial force. *Check utilisation* "
       "compares the applied moment to the envelope; turning it off reports the "
       "capacity only.")
    fig(fig_beam_envelope, "The rectangular example's biaxial envelope with the "
        "applied load; the sweep from 0 to 360 degrees closes the curve.")
    h2("Crack width")
    md("With **Crack width** on, the elastic analysis also computes the crack "
       "width. The bar diameter $\\phi$ (0 = derived from the bar area), the "
       "mild-steel bond coefficient $k_1$ (0.8 ribbed, 1.6 plain), the code edition "
       "and -- for the DK NA -- the member type are the inputs.")
    table(["Crack-width code", "What it changes"],
          [["EN 1992-1-1:2005", "The base EC2 model (7.3.4): $s_{r,max}$ from 7.11 / 7.14"],
           ["DS/EN 1992-1-1 + DK NA", "Cover-dependent $k_3$ and the $(h-x)/3$ term for slabs / prestressed only; reports **both** the fine and the coarse crack system (the coarse: centroid-matched effective area, fig 7.100 NA, $w_k$ halved)"],
           ["EN 1992-1-1:2023", "The refined model (9.2.3): $w_k = k_w\\,(k_1/r)\\,s_{r,m,cal}\\,(\\varepsilon_{sm}-\\varepsilon_{cm})$"]])
    call("standard", "The DK NA reports the fine and the coarse crack system side "
         "by side, each for the long-term and short-term load (four crack widths). "
         "Part C derives every model in full with the worked crack width.")
    h2("Shear (VRd,c, no shear reinforcement)")
    md("With **Check shear capacity** on, Sector computes the design shear "
       "resistance $V_{Rd,c}$ of a member **not** requiring shear reinforcement "
       "(EN 1992-1-1 6.2.2) and the utilisation $V_{Ed}/V_{Rd,c}$. The inputs are "
       "the applied shear $V_{Ed}$, the shear direction (vertical, bending about "
       "$x$; or horizontal, about $y$), the tension face, the method edition, and "
       "the web width $b_w$ (0 = derived). The effective depth $d$, the tension "
       "reinforcement $A_{sl}$ and, when $b_w = 0$, the web width are all derived "
       "from the geometry; the axial term uses the plastic (ULS) axial force $N$.")
    table(["Shear method", "What it sets"],
          [["EN 1992-1-1:2005", "$C_{Rd,c} = 0.18/\\gamma_c$, $k_1 = 0.15$, "
            "$v_{min} = 0.035\\,k^{1.5}\\sqrt{f_{ck}}$"],
           ["DS/EN 1992-1-1:2005 + DK NA:2024", "As 2005 but the raised "
            "$v_{min} = (0.051/\\gamma_c)\\,k^{1.5}\\sqrt{f_{ck}}$"],
           ["DS/EN 1992-1-1:2023", "The strain-based $\\tau_{Rd,c}$ (8.2.2) with the "
            "aggregate size $d_{dg}$ and $\\gamma_V = 1.40$; members without links"]])
    call("standard", "The **2023 method** uses "
         "$\\tau_{Rd,c} = (0.66/\\gamma_V)(100\\rho_l f_{ck} d_{dg}/d)^{1/3} \\geq "
         "\\tau_{Rd,c,min}$ (8.27), with $d_{dg} = 16 + D_{lower}$ ($\\leq 40$ mm, "
         "8.2.1(4)) and the flexural design yield $f_{yd}$ -- it does not use the "
         "axial stress. Its strain-based method for members **with** links (8.2.3) "
         "is a follow-up; torsion and the combined lock stay on the 2005 family.")
    call("limit", "$A_{sl}$ is taken as the longitudinal bars on the tension face, "
         "**assumed fully anchored** ($\\geq l_{bd} + d$) beyond the section -- an "
         "anchorage that cannot be known at section level, so it is the user's "
         "responsibility.")
    md("With **Shear reinforcement (links) present** on, the resistance becomes the "
       "variable-strut $V_{Rd} = \\min(V_{Rd,s}, V_{Rd,max})$ (6.2.3) instead of "
       "$V_{Rd,c}$ (which is still shown, to indicate whether links are strictly "
       "required). The link inputs are the number of legs, the bar diameter and the "
       "spacing $s$ (so $A_{sw} = n_{legs}\\,\\pi\\phi^2/4$), the link yield "
       "$f_{ywk}$, and the strut-angle bounds $\\cot\\theta_{min}$ / "
       "$\\cot\\theta_{max}$. Sector auto-optimises $\\theta$ within those bounds to "
       "maximise $V_{Rd}$.")
    call("standard", "EN 1992-1-1 6.7N (and the DK NA:2024 6.7a NA for class B/C "
         "steel) allow $1 \\leq \\cot\\theta \\leq 2.5$; the DK NA takes the strut "
         "factor $\\nu_1 = \\nu_v = 0.7 - f_{ck}/200 \\geq 0.45$ (5.103 NA) rather "
         "than the recommended $\\nu = 0.6(1 - f_{ck}/250)$. Bounds outside the "
         "code range are accepted but **warned**, not blocked.")
    h2("Torsion (TRd, thin-walled tube)")
    md("With **Check torsion capacity** on, Sector idealises the section as a "
       "thin-walled closed tube (6.3) and reports the closed-stirrup resistance "
       "$T_{Rd,s}$, the strut-crushing $T_{Rd,max}$, the cracking $T_{Rd,c}$, the "
       "utilisation $T_{Ed}/T_{Rd}$ and the required longitudinal steel "
       "$\\sum A_{sl}$. The inputs are the applied torsion $T_{Ed}$, an optional "
       "wall-thickness override $t_{ef}$ (0 = auto), and the strut-angle bounds. "
       "The tube $A$, $u$, $t_{ef}$, $A_k$ and $u_k$ are derived from the outline. "
       "The **stirrup is the shared closed stirrup** (defined once under Links / "
       "stirrups, and used by shear too -- one leg of the loop carries the torsion "
       "shear flow), and the longitudinal steel $\\sum A_{sl}$ uses the section's "
       "mild-reinforcement design yield.")
    call("standard", "$T_{Rd,max}$ uses the code torsion strut factor: recommended "
         "$\\nu = 0.6(1 - f_{ck}/250)$, or the DK NA:2024 pure-torsion "
         "$\\nu_t = 0.7\\,(0.7 - f_{ck}/200)$ (5.104 NA). When shear links are also "
         "defined, the combined concrete-crushing check "
         "$T_{Ed}/T_{Rd,max} + V_{Ed}/V_{Rd,max} \\leq 1$ (6.29) is added.")
    h2("Combined M-V-T interaction")
    md("With **Check combined M-V-T** on, Sector ties the bending (plastic $M$), "
       "shear ($V$) and torsion ($T$) checks together under **one shared code "
       "edition** (the per-check method selectors are then locked to it). It reports "
       "the concrete-crushing interaction (6.29) and the DK NA "
       "$\\sum(S_{Ed}/S_{Rd}) \\leq 1$ rule (6.3.2(6)), and lists the additional "
       "longitudinal steel that shear and torsion demand. All three checks (Plastic, "
       "Shear, Torsion) must be enabled.")
    call("standard", "DK NA 6.3.2(6): $\\sum(S_{Ed}/S_{Rd}) \\leq 1$ sums each "
         "action's utilisation (the axial $N$ is folded into the bending term). If "
         "the longitudinal steel for shear beyond bending is provided, tick **M & V "
         "separate** -- then $M$ and $V$ are not summed together but checked in two "
         "independent investigations, $\\max(M+T,\\,V+T)$.")
    call("concept", "One closed stirrup does both jobs: the stirrup defined once "
         "under Links / stirrups carries the shear and the torsion together. The DK "
         "NA $\\sum(S_{Ed}/S_{Rd})$ rule and the shared-stirrup transverse check both "
         "draw on it -- their transverse demands add only when $V_{Ed} > V_{Rd,c}$; "
         "below that the concrete carries the shear and the whole stirrup is free for "
         "torsion.")
    h2("Modular ratios and creep")
    md("The cracked-elastic analysis uses a short-term modular ratio $n_s = E/E_c$ "
       "and a long-term $n_l = E/E_{c,eff}$, the latter carrying creep through the "
       "effective modulus $E_{c,eff} = E_c/(1+\\varphi)$. These ratios are **not "
       "entered** -- they are derived from the elastic moduli and the creep "
       "coefficient $\\varphi$. Mild steel and prestress are **independent**, "
       "because $E_s \\neq E_p$: mild steel uses $n = E_s/E_c$ and tendons "
       "$n = E_p/E_c$. Both pairs are reported in the Loads panel and in the report.")

    h1("Loads")
    md("The plastic check uses one action set (axial force $N$, positive in "
       "tension, and moments $M_x$ / $M_y$). The elastic check uses a long-term "
       "and a short-term set, so creep and load duration are captured. The crack "
       "width is evaluated for both.")
    table(["Load set", "Feeds"],
          [["Plastic $N$, $M_x$, $M_y$", "The utilisation against the envelope"],
           ["Long-term $N$, $M_x$, $M_y$ + $\\varphi$", "The creep (long-term) elastic stresses"],
           ["Short-term $N$, $M_x$, $M_y$", "The instantaneous (total) elastic stresses"]])

    h1("Reading the results")
    h2("Plastic results")
    md("The $M_x$-$M_y$ envelope is drawn with the applied load marked; the "
       "**Neutral-axis state** selector steps through the swept angles and reports "
       "the strains, the compression resultant and lever arm, and the neutral-axis "
       "intercepts at each. The full per-angle table sits below.")
    h2("Elastic results")
    md("The cracked-section stresses are reported per bar for the long-term, "
       "short-term and total states, with the peak concrete compression and the "
       "neutral-axis position. When cracking is checked the section properties "
       "(uncracked and cracked) and the crack width follow.")
    h2("Shear results")
    md("The **Shear** view reports the applied $V_{Ed}$, the resistance "
       "$V_{Rd,c}$ and the utilisation, then the derived quantities ($d$, $b_w$, "
       "$A_{sl}$, $\\rho_l$, $k$, $\\sigma_{cp}$, $A_c$) and the code coefficients "
       "used. The web width shows whether it was entered or derived.")
    h2("Torsion results")
    md("The **Torsion** view reports $T_{Rd,s}$, $T_{Rd,max}$, $T_{Rd}$, the "
       "cracking $T_{Rd,c}$ and the utilisation, plus the derived tube ($A$, $u$, "
       "$t_{ef}$, $A_k$, $u_k$) and the required $\\sum A_{sl}$. When shear links "
       "are also defined it adds the combined shear+torsion crushing check.")
    h2("M-V-T Combined results")
    md("The **M-V-T Combined** view shows the $M$, $V$ and $T$ utilisations, the "
       "DK NA $\\sum(S_{Ed}/S_{Rd})$ sum, the concrete-crushing interaction with a "
       "$V$-$T$ envelope diagram, and the additional longitudinal steel demand.")

    # =====================================================================
    # PART C - THEORY & METHODOLOGY
    # =====================================================================
    part("Part C - Theory & methodology")

    h1("Conventions and sign convention")
    md("Coordinates are in metres, taken about the section origin. The axial force "
       "$N$ is positive in **tension** (compression negative, kN), so its sign agrees "
       "with the stresses and strains -- a crushing concrete strain reads negative; "
       "the moments $M_x$ and $M_y$ act "
       "about the $x$ and $y$ axes (kNm). Along any straining direction a **depth "
       "coordinate** $s$ is the projection of a point onto the strain gradient; the "
       "neutral axis is a line $s = s_{na}$, and in the plastic sweep its "
       "orientation is the angle $V$ measured from the $y$ axis.")
    fig(fig_sign_convention, "Axes and the positive senses of the axial force, the "
        "moments and the neutral-axis angle.")
    call("concept", "The reported axial force $N$, the stresses and the strains are "
         "all **tension-positive**. Internally the plastic solver works "
         "**compression-positive** (the compression zone has strain $> 0$); the sign "
         "is converted at the boundary, so you only enter and read tension-positive "
         "values. The concrete strain limits $\\varepsilon_{c2}$ / $\\varepsilon_{cu2}$ "
         "are still entered as positive compression magnitudes (as in EC2).")

    h1("Material laws")
    h2("Concrete (parabola-rectangle)")
    md("The design concrete law (Curve 2) rises as a power curve to the peak and "
       "then holds it to the ultimate strain:\n\n"
       "$$\\sigma_c = f_{cd}\\left[1-\\left(1-\\tfrac{\\varepsilon_c}"
       "{\\varepsilon_{c2}}\\right)^{n}\\right] \\quad (0\\le\\varepsilon_c\\le"
       "\\varepsilon_{c2}), \\qquad \\sigma_c = f_{cd}\\quad(\\varepsilon_{c2}\\le"
       "\\varepsilon_c\\le\\varepsilon_{cu2}),$$\n\n"
       "with $f_{cd} = \\alpha_{cc}\\,f_{ck}/\\gamma_c$ and zero stress beyond "
       "$\\varepsilon_{cu2}$ (crushed).\n\n"
       "For $f_{ck}\\le 50$ MPa the strain limits are $\\varepsilon_{c2}=2.0$ per "
       "mille, $\\varepsilon_{cu2}=3.5$ per mille and $n=2$.\n\n"
       "Above C50 they follow Table 3.1: "
       "$\\varepsilon_{c2}=(2.0+0.085(f_{ck}-50)^{0.53})/1000$, "
       "$\\varepsilon_{cu2}=(2.6+35((90-f_{ck})/100)^4)/1000$ and "
       "$n=1.4+23.4((90-f_{ck})/100)^4$. These strength-dependent strains apply to "
       "the 2005 and DK NA editions.\n\n"
       "The EN 1992-1-1:2023 edition instead keeps them **constant** "
       "($\\varepsilon_{c2}=2.0$, $\\varepsilon_{cu2}=3.5$ per mille, $n=2$) for "
       "every grade.")
    md("**Worked (beam, C40/50):** $f_{cd}=1.0\\times 40/1.45 = 27.6$ MPa, with "
       "$\\varepsilon_{c2}=2.0$ and $\\varepsilon_{cu2}=3.5$ per mille.")
    fig(fig_beam_concrete_law, "The C40/50 parabola-rectangle law of the beam "
        "example.")
    h2("Mild steel")
    md("The mild steel is linear to yield and then a plateau or a mild hardening "
       "branch:\n\n"
       "$$\\sigma_s = E_{s,d}\\,\\varepsilon_s\\ \\ (|\\varepsilon_s|\\le"
       "\\varepsilon_{yd}), \\qquad f_{yd}=f_{yk}/\\gamma_s, \\qquad "
       "\\varepsilon_{yd}=f_{yd}/E_{s,d}.$$\n\n"
       "The design elastic modulus $E_{s,d}$ depends on the curve.\n\n"
       "The selectable Eurocode presets (Curve 3) keep it unfactored, "
       "$E_{s,d}=E_s$, so B550 yields at "
       "$\\varepsilon_{yd}=f_{yd}/E_s=458/200000\\approx 2.29$ per mille.\n\n"
       "The elastic-perfectly-plastic law used in this worked example (Curve 2) "
       "factors it, $E_{s,d}=E_s/\\gamma_s$, so the whole curve scales by "
       "$1/\\gamma_s$ and yield moves to $\\varepsilon_{yd}=f_{yk}/E_s=550/200000="
       "2.75$ per mille.\n\n"
       "In both, $f_{yd}=550/1.20=458$ MPa.")
    fig(fig_beam_steel_law, "The B550 mild-steel law of the beam example.")
    h2("Prestressing steel")
    md("A tendon is evaluated at its **total** strain -- the locked-in initial "
       "strain $\\varepsilon_{p,IS}$ (from prestressing, after losses, given as an "
       "input) plus the section strain at the tendon location:\n\n"
       "$$\\varepsilon_p = \\varepsilon_{p,IS} + \\varepsilon_c(\\text{tendon}), "
       "\\qquad \\sigma_p = f(\\varepsilon_p),\\quad f_{pd}=f_{p0.1k}/\\gamma_s.$$\n\n"
       "**Worked (circular):** $\\varepsilon_{p,IS}=5.0$ per mille and "
       "$f_{pd}=1600/1.15=1391$ MPa.")
    fig(fig_circular_prestress_law, "The tendon law of the circular example.")
    call("standard", "The concrete, mild-steel and tendon laws follow DS/EN "
         "1992-1-1 3.1.7, 3.2.7 and 3.3.6; the strain limits follow Table 3.1.")

    h1("Plastic (ultimate) capacity")
    h2("The strain plane at ultimate")
    md("Plane sections remain plane, so the strain is linear across the depth: "
       "$\\varepsilon(s) = \\varphi\\,(s - s_{na})$, where $\\varphi$ is the "
       "curvature and $s_{na}$ the neutral-axis depth. At ultimate the extreme "
       "compression fibre reaches the concrete crushing strain "
       "$\\varepsilon_{cu2}$; the compression depth is $c = s_{max}-s_{na}$.")
    fig(fig_strain_plane, "The ultimate strain plane (reported tension-positive "
        "convention): one straight line -- zero at the neutral axis, compression "
        "(negative) above it and tension (positive) below, the top fibre at the "
        "crushing strain. The internal solver formula above is compression-positive; "
        "the reported strains negate it.")
    h2("The governing curvature")
    md("The curvature is scaled until the **first** material limit is reached, so "
       "none is driven past its limit:\n\n"
       "$$\\varphi = \\min\\!\\left(\\frac{\\varepsilon_{cu2}}{c},\\; "
       "\\frac{\\varepsilon_{ud}}{s_{na}-s_{bar,min}},\\; "
       "\\frac{\\varepsilon_{ud}}{s_{bar,max}-s_{na}},\\; "
       "\\frac{\\varepsilon_{pud}-\\varepsilon_{p,IS}}{s_{na}-s_{cab,min}}\\right),$$\n\n"
       "the four terms being concrete crushing, rupture of the most tensile mild "
       "bar, rupture of the most **compressed** mild bar (only when the bars are "
       "active in compression and their ultimate strain is below the concrete "
       "crushing strain -- otherwise the concrete crushes first) and rupture of the "
       "most tensile tendon (measured from its locked-in strain). Whichever is "
       "smallest governs.")
    call("tip", "The reported mild-steel strain is split into its two governing "
         "extremes: the most **tensile** bar strain $\\varepsilon_{s,t}$ and, when "
         "the bars are active in compression, the most **compressed** bar strain "
         "$\\varepsilon_{s,c}$ (tension-positive, so it reads negative). With the "
         "bars tension-only, the compression side carries no stress and only "
         "$\\varepsilon_s$ is shown.")
    h2("Force resultants and equilibrium")
    md("The concrete compression force is the integral of $\\sigma_c$ over the "
       "compression zone. The parabola is split into its rising region and the "
       "plateau and integrated over the polygon by Green's theorem (a compiled "
       "kernel, with a pure-Python fallback). Each bar and tendon adds "
       "$\\sigma(\\varepsilon)\\,A$. The compression depth $c$ is solved so the "
       "axial force balances, $\\sum F = N$; the first moments of the resultants "
       "about the origin are the capacity moments $M_x$, $M_y$.")
    h2("The interaction envelope")
    md("Rotating the neutral-axis angle $V$ and solving at each gives one point on "
       "the $M_x$-$M_y$ envelope; sweeping $0$ to $360$ degrees closes the biaxial "
       "diagram. **Worked (beam, $N=0$, $V=90$):** the concrete reaches its "
       "crushing strain ($3.5$ per mille) while the most tensile bars are well past "
       "yield ($18.9$ per mille, against the $2.75$ per mille yield), so this "
       "tension-controlled point gives $M_{x} = 346$ kNm. The applied $M_x=300$ "
       "kNm is then a utilisation of $300/346 = 0.87$.")
    fig(fig_beam_envelope, "The beam envelope with its applied load; each vertex is "
        "one solved neutral-axis angle.")

    h1("Cracked-section elastic analysis")
    md("For the service state the section is taken as already cracked: concrete "
       "carries compression only (zero stress where $\\varepsilon\\ge 0$) and the "
       "steel is linear in both directions. The analysis works with a reference "
       "concrete modulus and the modular ratio $n=E_s/E_c$: each bar contributes a "
       "transformed area $n\\,A$. (The solver can also subtract the concrete a "
       "compression-zone bar displaces, using $(n-1)\\,A$ there; Sector leaves that "
       "refinement off, so the reported stresses and section properties use "
       "$n\\,A$ throughout.) The strain plane $(\\varepsilon_0,k_x,k_y)$ is solved "
       "by Newton iteration so the transformed-section resultants equal "
       "$(N,M_x,M_y)$, updating the compression zone until it settles.")
    md("Creep enters through the modular ratio: the long-term state uses "
       "$n_l = E_s/E_{c,eff}$ with $E_{c,eff}=E_c/(1+\\varphi)$, and the "
       "short-term state uses $n_s = E_s/E_c$. The reported total combines the two, "
       "so both load duration and creep are captured. Prestressing tendons carry "
       "their **own** modular ratio $n_p = E_p/E_c$ (creep-reduced the same way), "
       "independent of the mild-steel ratio because $E_p \\neq E_s$; the solver "
       "applies it per bar. None of these ratios is entered -- they are all derived "
       "from the moduli $E_c$, $E_s$, $E_p$ and the creep coefficient $\\varphi$.")
    fig(fig_beam_cracked, "The beam's cracked (Stage II) state under the service "
        "moment: the compression zone (shaded) above the neutral axis.")

    h1("Serviceability: cracking and crack width")
    h2("The cracking threshold")
    md("The uncracked (Stage I) peak concrete tensile stress $\\sigma_{ct,I}$ "
       "scales with the load, so the load factor to first cracking is "
       "$\\lambda_{cr}=f_{ctm}/\\sigma_{ct,I}$; $\\lambda_{cr}\\ge 1$ means the "
       "section has not cracked. **Worked (beam, $M_x=150$ kNm):** "
       "$\\lambda_{cr}=0.49<1$, so the section is cracked and the Stage II stresses "
       "govern ($\\sigma_s=204$ MPa at the bottom bars).")
    call("concept", "Cracking is **irreversible** and is triggered by the largest "
         "load the section ever sees, so Sector decides cracked/uncracked from the "
         "**governing** of the sustained (long-term) and the peak (total = long + "
         "short) action -- not the sustained part alone. A section that only cracks "
         "under a large short-term load is therefore still treated as cracked "
         "(with a quasi-permanent crack width to check); one only cracked by the "
         "sustained load stays cracked even if a counteracting short-term action "
         "relieves the total. The peak check uses the same combined-creep "
         "superposition (long at $n_l$ + short at $n_s$) as the reported stresses.")
    call("standard", "EN 1992-1-1 7.4.3(3): a member is treated as uncracked only "
         "if it is not expected to be loaded above the cracking stress anywhere -- "
         "i.e. at the peak load. The crack-width *limit*, in contrast, is a "
         "quasi-permanent (long-term) check.")
    h2("Crack width - EN 1992-1-1:2005")
    md("$$w_k = s_{r,max}\\,(\\varepsilon_{sm}-\\varepsilon_{cm}),\\qquad "
       "\\varepsilon_{sm}-\\varepsilon_{cm} = \\max\\!\\left(\\frac{\\sigma_s - "
       "k_t\\,\\tfrac{f_{ct,eff}}{\\rho_{p,eff}}(1+\\alpha_e\\rho_{p,eff})}{E_s},\\; "
       "0.6\\,\\frac{\\sigma_s}{E_s}\\right),$$\n\n"
       "with $\\alpha_e=E_s/E_{cm}$ (7.8, 7.9). The maximum crack spacing is\n\n"
       "$$s_{r,max} = k_3\\,c + k_1 k_2 k_4\\,\\frac{\\phi}{\\rho_{p,eff}}\\ (7.11), "
       "\\qquad s_{r,max}=1.3\\,(h-x)\\ (7.14)$$\n\n"
       "where 7.11 applies for bars at close centres (spacing "
       "$\\le 5(c+\\phi/2)$) and 7.14 otherwise. The effective ratio "
       "$\\rho_{p,eff}=A_{s,eff}/A_{c,eff}$ uses the effective height "
       "$h_{c,ef}=\\min(2.5(h-d),(h-x)/3,h/2)$. Recommended coefficients: $k_1=0.8$ "
       "(ribbed) or $1.6$ (plain), $k_2=0.5$, $k_3=3.4$, $k_4=0.425$.")
    md("**Worked (beam, $M_x=150$ kNm):** $\\sigma_s=204$ MPa, "
       "$\\rho_{p,eff}=0.0393$, $\\varepsilon_{sm}-\\varepsilon_{cm}=0.797$ per "
       "mille, $s_{r,max}=236$ mm, hence $w_k=0.188$ mm.")
    h2("DK NA fine crack system")
    md("The DK National Annex makes the cover term cover-dependent, "
       "$k_3=3.4\\,(25/c)^{2/3}$, which lowers $s_{r,max}$ for covers above 25 mm, "
       "and limits the $(h-x)/3$ term in $h_{c,ef}$ to slabs and prestressed "
       "members (it is dropped for an ordinary beam). **Worked:** $s_{r,max}=206$ "
       "mm, $w_k=0.164$ mm.")
    h2("DK NA coarse crack system")
    md("The coarse system (7.3.4(1)) redefines the effective tension area as the "
       "band at the tension face whose area-centroid matches the tension "
       "reinforcement's centroid (figure 7.100 NA; for a rectangle the $2(h-d)$ "
       "band), and **halves** the crack width. **Worked:** the band is $0.100$ m "
       "high and $w_k=0.077$ mm.")
    call("tip", "The single *DS/EN 1992-1-1 + DK NA* option reports the fine and the "
         "coarse system side by side, each for the long-term and the short-term "
         "load -- four crack widths -- so you can read both without re-running.")
    h2("EN 1992-1-1:2023 refined model")
    md("The 2023 edition uses a refined model (9.2.3):\n\n"
       "$$w_k = k_w\\,\\frac{k_1}{r}\\,s_{r,m,cal}\\,(\\varepsilon_{sm}-"
       "\\varepsilon_{cm}),\\qquad k_w=1.7,\\qquad \\frac{k_1}{r}=\\frac{h-x}"
       "{(h-x)-a_{y,i}},$$\n\n"
       "with a per-bar curvature factor $k_1/r$ (9.9). The mean crack spacing is\n\n"
       "$$s_{r,m,cal} = 1.5\\,c + \\frac{k_{fl}\\,k_b}{7.2}\\,\\frac{\\phi}"
       "{\\rho_{p,eff}} \\le \\frac{1.3}{k_w}(h-x)\\ (9.15),$$\n\n"
       "with the flexural coefficient $k_{fl}$ (9.16/9.17), the bond factor "
       "$k_b=0.9$ (ribbed) or $1.2$ (plain) (9.18), and $h_{c,eff}$ from figure "
       "9.3 (built from the near-face layer and extended over the tension layers). "
       "The mean strain (9.11) keeps the same numerator but its lower bound is "
       "$(1-k_t)\\sigma_s/E_s$. **Worked:** $s_{r,m,cal}=134$ mm, $w_k=0.186$ mm.")
    md("The four editions on the same beam and service moment ($M_x=150$ kNm):")
    table(["Crack-width edition", "$s_{r,max}$ (mm)", "$h_{c,ef}$ (m)", "$w_k$ (mm)"],
          [["EN 1992-1-1:2005", "236", "0.125", "0.188"],
           ["DS/EN + DK NA (fine)", "206", "0.125", "0.164"],
           ["DS/EN + DK NA (coarse)", "184", "0.100", "0.077"],
           ["EN 1992-1-1:2023", "134", "0.175", "0.186"]])
    call("standard", "The *Crack-width code* offers three options -- EN 1992-1-1:"
         "2005, DS/EN 1992-1-1 + DK NA and EN 1992-1-1:2023. The DK NA option "
         "reports the fine and the coarse system together (all four columns above), "
         "each for the long-term and short-term load; the report writes out the "
         "governing worked crack width.")

    h1("Shear resistance without shear reinforcement")
    md("The design shear resistance of a member not requiring shear reinforcement "
       "(EN 1992-1-1 6.2.2(1)) is\n\n"
       "$$V_{Rd,c} = \\Big[C_{Rd,c}\\,k\\,(100\\,\\rho_l\\,f_{ck})^{1/3} + "
       "k_1\\,\\sigma_{cp}\\Big]\\,b_w\\,d \\quad(6.2\\text{a}),$$\n\n"
       "with a lower bound\n\n"
       "$$V_{Rd,c} = (v_{min} + k_1\\,\\sigma_{cp})\\,b_w\\,d \\quad(6.2\\text{b}),$$\n\n"
       "where $k = 1 + \\sqrt{200/d} \\le 2$ ($d$ in mm), "
       "$\\rho_l = A_{sl}/(b_w\\,d) \\le 0.02$ is the tension-reinforcement ratio, "
       "and $\\sigma_{cp} = N_{Ed}/A_c < 0.2\\,f_{cd}$ is the axial stress "
       "(compression positive). The edition supplies $C_{Rd,c} = 0.18/\\gamma_c$, "
       "$k_1 = 0.15$ and $v_{min}$: the recommended "
       "$v_{min} = 0.035\\,k^{1.5}\\sqrt{f_{ck}}$, or the DK NA:2024 "
       "$v_{min} = (0.051/\\gamma_c)\\,k^{1.5}\\sqrt{f_{ck}}$.")
    md("Sector derives the geometry from the section for the chosen shear "
       "direction: the effective depth $d$ is the distance from the extreme "
       "compression fibre (opposite the tension face) to the centroid of the "
       "tension bars; $b_w$, when not entered, is the smallest solid width sampled "
       "over the middle 80% of the depth (the web of a rectangular / T / box "
       "section -- a curved outline should have $b_w$ entered by hand). $\\sigma_{cp}$ "
       "uses the plastic (ULS) axial force $N$; since Sector's $N$ is "
       "tension-positive it is negated to the code's compression-positive "
       "convention, exactly as the axial-force flip elsewhere.")
    call("limit", "$A_{sl}$ is the longitudinal tension reinforcement, **assumed "
         "fully anchored** ($\\geq l_{bd} + d$) beyond the section. This anchorage "
         "cannot be checked at section level, so it is the engineer's "
         "responsibility. Bonded tendons are not counted toward $\\rho_l$ "
         "automatically.")
    md("**Worked** (300 x 600 mm rectangle, C35, DK NA:2024, "
       "$A_{sl} = 1473$ mm$^2$, $d = 550$ mm, $b_w = 300$ mm, $N = 0$): "
       "$k = 1.603$, $\\rho_l = 0.00893$, $C_{Rd,c} = 0.124$, the basic term "
       "$0.627$ MPa exceeds $v_{min} = 0.535$ MPa, so "
       "$V_{Rd,c} = 0.627 \\cdot 300 \\cdot 550 = 103.4$ kN.")

    h2("Members with shear reinforcement (links)")
    md("A member with designed vertical links is a truss: the links are the "
       "tension ties and the concrete web the inclined compression struts at an "
       "angle $\\theta$ to the axis (6.2.3). The resistance is the smaller of the "
       "tie yield and the strut crushing,\n\n"
       "$$V_{Rd,s} = \\frac{A_{sw}}{s}\\,z\\,f_{ywd}\\,\\cot\\theta \\quad(6.8), "
       "\\qquad V_{Rd,max} = \\frac{\\alpha_{cw}\\,b_w\\,z\\,\\nu_1\\,f_{cd}}"
       "{\\cot\\theta + \\tan\\theta} \\quad(6.9),$$\n\n"
       "and $V_{Rd} = \\min(V_{Rd,s}, V_{Rd,max})$. Here $z$ is the internal lever "
       "arm, $\\nu_1$ the strut effectiveness factor, and $\\alpha_{cw}$ the "
       "compression-chord factor (1 for a non-prestressed section, rising with an "
       "axial compression per 6.11N). The shear also adds a longitudinal tension "
       "$\\Delta F_{td} = 0.5\\,V_{Ed}\\,\\cot\\theta$ (6.18) that the bottom steel "
       "must carry on top of the bending force.")
    call("concept", "Rather than the code's $z \\approx 0.9d$ approximation, Sector "
         "uses the **internal lever arm the plastic engine already computes** -- the "
         "separation of the concrete compression resultant and the steel tension "
         "resultant for bending about the shear axis, at the ULS axial force. It "
         "falls back to $0.9d$ only when that lever arm is degenerate (no tension "
         "steel, or a fully compressed / non-converged state).")
    md("$V_{Rd,s}$ rises with $\\cot\\theta$ (a flatter strut engages more links) "
       "while $V_{Rd,max}$ falls with it, so $V_{Rd} = \\min$ is largest where the "
       "two are equal, at $\\cot^2\\theta = b/a - 1$ with $a = (A_{sw}/s)\\,f_{ywd}$ "
       "and $b = \\alpha_{cw}\\,b_w\\,\\nu_1\\,f_{cd}$ ($z$ cancels). Sector "
       "**auto-optimises** $\\theta$: it takes that crossing, clamped to the "
       "$\\cot\\theta$ bounds -- outside the crossing one limit governs throughout, "
       "so the best allowed angle is the nearer bound.")
    call("standard", "The recommended strut factor is $\\nu_1 = \\nu = "
         "0.6\\,(1 - f_{ck}/250)$ (6.6N); the DK NA:2024 uses its plasticity "
         "pure-shear factor $\\nu_1 = \\nu_v = 0.7 - f_{ck}/200 \\geq 0.45$ (5.103 "
         "NA), applied to the truss struts by 5.101 NA. Both editions bound "
         "$1 \\leq \\cot\\theta \\leq 2.5$ (6.7N / 6.7a NA).")
    md("**Worked** (same section, C35, DK NA:2024, 2-leg $\\phi$10 links at "
       "$s = 150$ mm, $f_{ywk} = 500$; taking $z = 0.9d = 495$ mm for illustration): "
       "$f_{ywd} = 417$ MPa, $\\nu_1 = 0.525$, $A_{sw}/s = 1.047$ mm$^2$/mm. The "
       "crossing $\\cot\\theta = 2.78$ exceeds the limit, so $\\cot\\theta = 2.5$ "
       "and the links govern: $V_{Rd,s} = 540$ kN $< V_{Rd,max} = 649$ kN, giving "
       "$V_{Rd} = 540$ kN. In the app the section's own (slightly smaller) plastic "
       "lever arm is used in place of $0.9d$.")

    h1("Torsion (thin-walled tube)")
    md("A section resisting torsion is idealised as a thin-walled closed tube "
       "(6.3.2(1)): the torque is carried by a constant shear flow round the walls. "
       "The effective wall thickness is $t_{ef} = A/u$ ($A$ the area within the "
       "outer perimeter including any hollow, $u$ that perimeter), capped at the "
       "real wall for a hollow section. The centre-line is the outline offset "
       "inward by $t_{ef}/2$; $A_k$ is the area it encloses and $u_k$ its "
       "perimeter. The resistances (at the strut angle $\\theta$) are\n\n"
       "$$T_{Rd,s} = \\frac{A_{sw}}{s}\\,2A_k\\,f_{ywd}\\,\\cot\\theta, \\qquad "
       "T_{Rd,max} = 2\\,\\nu\\,\\alpha_{cw}\\,f_{cd}\\,A_k\\,t_{ef}\\,"
       "\\sin\\theta\\cos\\theta \\quad(6.30),$$\n\n"
       "with $T_{Rd} = \\min(T_{Rd,s}, T_{Rd,max})$. The torsion also needs "
       "longitudinal steel $\\sum A_{sl} = T_{Ed}\\,u_k\\,\\cot\\theta/(2A_k\\,"
       "f_{yd})$ (6.28), **in addition** to the bending reinforcement on the "
       "tension side, and the cracking torque is $T_{Rd,c} = 2A_k\\,t_{ef}\\,"
       "f_{ctd}$ ($\\tau = f_{ctd}$).")
    md("As for shear, $T_{Rd,s}$ rises with $\\cot\\theta$ and $T_{Rd,max}$ peaks "
       "at 45 degrees, so $T_{Rd} = \\min$ is largest at the crossover, which "
       "Sector auto-optimises within the $\\cot\\theta$ bounds. When shear and "
       "torsion act together the concrete struts carry both, limited by\n\n"
       "$$T_{Ed}/T_{Rd,max} + V_{Ed}/V_{Rd,max} \\le 1 \\quad(6.29),$$\n\n"
       "checked at a common strut angle (the least-conservative shared angle, "
       "near 45 degrees, where both crushing resistances peak).")
    call("standard", "The strut factor $\\nu$ is the code torsion effectiveness "
         "factor: recommended $\\nu = 0.6(1 - f_{ck}/250)$ (via 6.2.2(6)), or the "
         "DK NA:2024 pure-torsion $\\nu_t = 0.7\\,(0.7 - f_{ck}/200)$ (5.104 NA) -- "
         "a further 0.7 on the pure-shear expression for the circulatory shear "
         "flow. Note $\\nu_t$ has NO lower bound: the 0.45 floor of 5.103 NA "
         "belongs to $\\nu_v$ only, so above C50 $\\nu_t$ keeps falling. Only solid and "
         "single-cell (box) sections are idealised automatically; a multi-cell "
         "section (two or more voids) is rejected (6.3.2(1) needs sub-division), and "
         "a curved outline should have $t_{ef}$ entered by hand.")
    md("**Worked** (300 x 600 mm rectangle, C35, DK NA:2024, closed $\\phi$10 "
       "stirrup at $s = 150$ mm): $A = 0.18$ m$^2$, $u = 1.8$ m, $t_{ef} = 100$ mm, "
       "$A_k = 0.1$ m$^2$, $u_k = 1.4$ m, $\\nu_t = 0.368$. At the optimum "
       "$\\cot\\theta = 1.75$ the stirrups and struts meet at "
       "$T_{Rd} \\approx 76.4$ kN.m, with $T_{Rd,c} \\approx 31$ kN.m.")

    h1("Combined M-V-T interaction")
    md("Bending, shear and torsion act together, so their checks are tied together "
       "under one code edition (6.3.2). Two interactions apply. The concrete web "
       "struts carry both shear and torsion, limited by\n\n"
       "$$T_{Ed}/T_{Rd,max} + V_{Ed}/V_{Rd,max} \\le 1 \\quad(6.29),$$\n\n"
       "checked at a common strut angle near 45 degrees. The DK NA:2024 (6.3.2(6)) "
       "adds a general rule over the acting sectional forces,\n\n"
       "$$\\sum (S_{Ed}/S_{Rd}) \\le 1,$$\n\n"
       "each $S_{Rd}$ being the resistance to that force acting alone. Sector takes "
       "the bending utilisation from the plastic $M$-$M$ envelope at the applied "
       "$N$ (so $N$ is folded in), the shear from $V_{Ed}/V_{Rd}$ and the torsion "
       "from $T_{Ed}/T_{Rd}$.")
    call("standard", "DK NA 6.3.2(6): if the longitudinal reinforcement provided for "
         "shear (beyond bending) is present, $M$ and $V$ are **not** summed at the "
         "same time -- two independent checks are made and the governing "
         "$\\max(M+T,\\,V+T)$ taken. Torsion also needs its longitudinal steel "
         "$\\sum A_{sl}$ round the perimeter and the shear its $\\Delta F_{td}$ on "
         "the tension chord, both beyond the bending reinforcement.")
    md("The **shared closed stirrup** carries both actions, so their transverse "
       "demands add. When $V_{Ed} \\leq V_{Rd,c}$ the concrete alone carries the "
       "shear (6.2.1), so the shear takes **no** stirrup and the whole stirrup "
       "serves torsion; only when $V_{Ed} > V_{Rd,c}$ do the shear and torsion "
       "stirrup demands add. The added stirrup demand (least at a flat strut) and "
       "the crushing (least at 45 degrees) must both hold at **one** strut angle, so "
       "Sector reports the check at the single angle that balances the two.")
    call("standard", "Sector optimises the strut angle $\\theta$ **per action**: the "
         "shear check picks its own $\\theta$ to maximise $V_{Rd}$ and the torsion "
         "check its own to maximise $T_{Rd}$, so the two need not share one angle. "
         "This is defensible under DK NA 6.3.2(6), where each $S_{Rd}$ is the "
         "resistance to that action **acting alone**. Only the concrete-crushing "
         "interaction (6.29) and the shared-stirrup transverse check use a single "
         "common $\\theta$, where the two actions load the same web strut at once.")

    h1("Equilibrium check")
    md("Both analyses carry a convergence flag. The plastic solve balances the "
       "axial force **at each swept angle** to a tight residual, "
       "$|\\sum F - N|\\le 10^{-6}\\max(1,|N|)$; an angle whose axial force cannot "
       "be balanced -- the axial demand exceeds what the section can carry there -- "
       "is marked not converged. Such a point is still drawn on the envelope (so an "
       "infeasible or partial sweep is visible rather than hidden), and the "
       "run records whether every point converged. The elastic solve iterates the "
       "compression zone until the transformed resultants match the applied "
       "$(N,M_x,M_y)$.")

    # =====================================================================
    # PART D - REFERENCE
    # =====================================================================
    part("Part D - Reference")

    h1("Standards")
    md("Sector follows the Eurocode 2 family. The crack-width check offers several "
       "editions (Part C sets them out in full); the rest of the analysis is common "
       "to all of them.")
    table(["Topic", "Reference"],
          [["Concrete stress-strain law", "DS/EN 1992-1-1 3.1.7 and Table 3.1"],
           ["Ultimate strains", "DS/EN 1992-1-1 Table 3.1"],
           ["Reinforcement law", "DS/EN 1992-1-1 3.2.7"],
           ["Prestressing steel law", "DS/EN 1992-1-1 3.3.6"],
           ["Cracking and crack width (2005)", "DS/EN 1992-1-1 7.3"],
           ["Crack width (DK NA)", "DS/EN 1992-1-1 DK NA 7.3.4"],
           ["Crack width (2023)", "EN 1992-1-1:2023 9.2.3"],
           ["Shear without shear reinforcement", "DS/EN 1992-1-1 6.2.2 + DK NA 6.2.2(1)"],
           ["Shear, strain-based (2023)", "DS/EN 1992-1-1:2023 8.2.2 (tau_Rd,c, ddg)"],
           ["Shear with links (variable strut)", "DS/EN 1992-1-1 6.2.3 + DK NA 6.2.3(2)-(3)"],
           ["Torsion (thin-walled tube)", "DS/EN 1992-1-1 6.3 + DK NA 5.6.1(3)P / 6.3.2(6)"],
           ["Combined M-V-T", "DS/EN 1992-1-1 6.3.2(4) + DK NA 6.3.2(6)"]])

    h1("Key assumptions & limitations")
    md("- **One plane section.** Plane sections remain plane; the strain field is "
       "linear across the section.\n"
       "- **Perfect bond.** Reinforcement strain equals the concrete strain at the "
       "same point (before cracking) and follows the strain plane after.\n"
       "- **No tension in the concrete** for the cracked-elastic and plastic "
       "analyses; the tensile strength enters only the cracking threshold.\n"
       "- **Ultimate is strain-controlled.** The section fails when the first "
       "material reaches its strain limit (concrete crushing or steel/tendon "
       "rupture); no material is driven past its limit.\n"
       "- **Section-level only.** No shear, torsion, buckling, second-order or "
       "member effects.")
    call("limit", "The crack-width models are one-directional: the effective "
         "tension area and the crack spacing are defined for a single bending "
         "direction, so the crack width is reported for the governing bar along the "
         "cracked-state strain gradient.")

    h1("Glossary")
    table(["Symbol / term", "Meaning"],
          [["$N$ or $P$", "Axial force (tension positive)"],
           ["$M_x$, $M_y$", "Bending moments about the x and y axes"],
           ["$V$", "Neutral-axis angle in the plastic sweep"],
           ["$f_{ck}$, $f_{cd}$", "Characteristic / design concrete strength"],
           ["$f_{yk}$, $f_{yd}$", "Characteristic / design steel strength"],
           ["$\\varepsilon_{cu2}$", "Ultimate concrete compressive strain"],
           ["$\\varepsilon_{ud}$", "Design ultimate steel strain (rupture)"],
           ["$n$", "Modular ratio $E_s/E_c$ (elastic analysis)"],
           ["$s_{r,max}$", "Maximum crack spacing"],
           ["$w_k$", "Characteristic crack width"],
           ["$h_{c,ef}$", "Effective tension-zone height (crack width)"],
           ["Stage I / II", "Uncracked / fully cracked elastic state"]])

    return blocks


# ==========================================================================
# PDF RENDERER -- same content blocks, rendered with ReportLab
# ==========================================================================
# The in-app content uses Markdown + LaTeX (KaTeX). For the PDF the small, known
# subset used here is converted to ReportLab's HTML-like markup: Greek and
# operators become numeric entities, sub/superscripts become <sub>/<super>, and
# fractions become an inline ``a/b`` (parenthesised when compound).

_LATEX_CMD = {
    r"\varepsilon": "&#949;", r"\gamma": "&#947;", r"\sigma": "&#963;",
    r"\varphi": "&#966;", r"\alpha": "&#945;", r"\rho": "&#961;",
    r"\lambda": "&#955;", r"\phi": "&#966;", r"\eta": "&#951;",
    r"\Delta": "&#916;", r"\le": "&#8804;", r"\ge": "&#8805;",
    r"\neq": "&#8800;", r"\times": "&#215;", r"\cdot": "&#183;",
    r"\approx": "&#8776;", r"\pm": "&#177;", r"\sum": "&#931;",
}


def _latex_to_rl(s: str) -> str:
    """Convert the LaTeX subset used in the manual to ReportLab inline markup."""
    for c in (r"\left", r"\right", r"\!", r"\,", r"\;"):
        s = s.replace(c, "")
    s = s.replace(r"\qquad", "&nbsp;&nbsp;&nbsp;").replace(r"\quad", "&nbsp;&nbsp;")
    s = re.sub(r"\\text\{([^{}]*)\}", r"\1", s)   # \text{label} -> label
    # Brace-form sub/superscripts first, so the fraction args are brace-free.
    s = re.sub(r"_\{([^{}]*)\}", r"<sub>\1</sub>", s)
    s = re.sub(r"\^\{([^{}]*)\}", r"<super>\1</super>", s)

    def _frac(m):
        wrap = lambda x: "(" + x + ")" if re.search(r"[ +\-]", x) else x
        return wrap(m.group(1)) + "/" + wrap(m.group(2))

    # Iterate to a fixed point so a nested fraction (an inner tfrac inside the
    # numerator of an outer frac) is fully flattened: the inner one goes first,
    # which leaves the outer args brace-free for the next pass.
    while True:
        flat = re.sub(r"\\t?frac\{([^{}]*)\}\{([^{}]*)\}", _frac, s)
        if flat == s:
            break
        s = flat
    for k in sorted(_LATEX_CMD, key=len, reverse=True):
        s = s.replace(k, _LATEX_CMD[k])
    s = re.sub(r"\\(min|max|ln|log)\b", r"\1", s)
    s = re.sub(r"_([A-Za-z0-9])", r"<sub>\1</sub>", s)
    s = re.sub(r"\^([A-Za-z0-9])", r"<super>\1</super>", s)
    return s.replace("{", "").replace("}", "").replace("\\", "")


def _inline_md_to_rl(text: str) -> str:
    """Inline Markdown (``**bold**``, ``$math$``) -> ReportLab inline markup.
    The literal ``<``/``>``/``&`` are escaped first so the introduced tags stay
    valid, then the math and bold spans reintroduce real markup."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\$([^$]+)\$", lambda m: _latex_to_rl(m.group(1)), text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    return text


def _render_md_pdf(text, flow, styles, Paragraph):
    """Render a Markdown block (paragraphs, ``- ``/``1.`` lists, standalone
    ``$$display$$`` formulas) to ReportLab flowables."""
    buf = []

    def flush():
        if buf:
            flow.append(Paragraph(_inline_md_to_rl(" ".join(buf).strip()),
                                  styles["MBody"]))
            buf.clear()

    for line in text.split("\n"):
        s = line.strip()
        if not s:
            flush()
            continue
        # A standalone display equation, tolerating trailing sentence punctuation
        # outside the closing ``$$`` so it still renders as centred math.
        m_disp = re.match(r"^\$\$(.+)\$\$([.,;:]?)$", s)
        if m_disp:
            flush()
            body = _latex_to_rl(m_disp.group(1).strip()) + m_disp.group(2)
            flow.append(Paragraph(body, styles["MMath"]))
            continue
        mb = re.match(r"^[-*]\s+(.*)", s)
        mn = re.match(r"^(\d+)\.\s+(.*)", s)
        if mb:
            flush()
            flow.append(Paragraph("&bull;&nbsp; " + _inline_md_to_rl(mb.group(1)),
                                  styles["MBody"]))
        elif mn:
            flush()
            flow.append(Paragraph(f"{mn.group(1)}.&nbsp; "
                                  + _inline_md_to_rl(mn.group(2)), styles["MBody"]))
        else:
            buf.append(s)
    flush()


_FIG_EXPORT_TIMEOUT_S = 30.0
_FIG_TIMED_OUT = object()


def _png_size(png):
    return int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")


def _call_with_timeout(fn, timeout):
    """Run ``fn()`` in a daemon thread, returning its result (``None`` on error)
    or the ``_FIG_TIMED_OUT`` sentinel if it does not finish within ``timeout``.

    kaleido's browser export -- both the shared-server startup and each figure
    render -- can block indefinitely when the headless browser is in a bad state,
    so it runs off the main thread with a join timeout; the PDF then still
    completes (with placeholders) instead of hanging the app."""
    box = {}

    def _work():
        try:
            box["v"] = fn()
        except Exception:
            box["v"] = None

    worker = threading.Thread(target=_work, daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        return _FIG_TIMED_OUT
    return box.get("v")


def _fig_to_png(fig_callable, timeout=_FIG_EXPORT_TIMEOUT_S):
    """Render a manual figure to PNG bytes, ``None`` on failure, or the
    ``_FIG_TIMED_OUT`` sentinel if kaleido does not finish in ``timeout``."""
    def _render():
        buf = io.BytesIO()
        fig_callable().write_image(buf, format="png", scale=2)
        return buf.getvalue()

    return _call_with_timeout(_render, timeout)


def build_manual_pdf(buffer, figures=True):
    """Render the manual to ``buffer`` as a PDF over the same content blocks.

    ``figures=False`` skips the Plotly-to-PNG export (used by the tests, and a
    graceful fallback when kaleido or a browser is unavailable)."""
    import sector_report as report
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (Image, KeepTogether, Paragraph, SimpleDocTemplate,
                                    Spacer, Table, TableStyle)

    report._styles()                 # ensure the Greek-capable font is registered
    font, font_b = report._FONT, report._FONT_BOLD
    styles = getSampleStyleSheet()

    def _add(name, **kw):
        if name not in styles.byName:
            styles.add(ParagraphStyle(name=name, parent=styles["Normal"], **kw))

    _add("MTitle", fontSize=20, spaceAfter=6, fontName=font_b)
    _add("MPart", fontSize=17, spaceBefore=18, spaceAfter=8, fontName=font_b,
         textColor=colors.HexColor("#0d2440"))
    _add("MH1", fontSize=15, spaceBefore=14, spaceAfter=6, fontName=font_b,
         textColor=colors.HexColor("#1f3b66"))
    _add("MH2", fontSize=12.5, spaceBefore=9, spaceAfter=4, fontName=font_b)
    _add("MH3", fontSize=11, spaceBefore=6, spaceAfter=3, fontName=font_b)
    _add("MBody", fontSize=9.5, leading=13, spaceAfter=4, fontName=font)
    _add("MMath", fontSize=11, leading=15, alignment=TA_CENTER, spaceBefore=6,
         spaceAfter=6, fontName=font)
    _add("MSmall", fontSize=8, leading=10, textColor=colors.grey, fontName=font)

    page_w = 16.5 * cm
    flow = [
        Paragraph("Sector user manual", styles["MTitle"]),
        Paragraph(f"Version {APP_VERSION}", styles["MSmall"]),
        Spacer(1, 0.3 * cm),
        Paragraph("What Sector computes, the theory it applies, its features, and "
                  "how to use it.", styles["MBody"]),
        Spacer(1, 0.4 * cm),
    ]

    # One shared kaleido server for all figures. Start it behind the same timeout
    # as the figure renders, so a wedged browser startup cannot hang the build;
    # if it times out, drop to tables-only. Skipped entirely when figures are off.
    n1 = n2 = 0
    figures_hung = False
    if figures:
        if _call_with_timeout(report.ensure_image_server,
                              _FIG_EXPORT_TIMEOUT_S) is _FIG_TIMED_OUT:
            figures_hung = True
    for block in manual_blocks():
        kind = block[0]
        if kind == "part":
            flow.append(Spacer(1, 0.3 * cm))
            flow.append(Paragraph(_inline_md_to_rl(block[1]), styles["MPart"]))
            n1 = n2 = 0
        elif kind == "h1":
            n1 += 1
            n2 = 0
            flow.append(Paragraph(f"{n1}. " + _inline_md_to_rl(_strip_num(block[1])),
                                  styles["MH1"]))
        elif kind == "h2":
            n2 += 1
            flow.append(Paragraph(f"{n1}.{n2} "
                                  + _inline_md_to_rl(_strip_num(block[1])), styles["MH2"]))
        elif kind == "h3":
            flow.append(Paragraph(_inline_md_to_rl(_strip_num(block[1])), styles["MH3"]))
        elif kind == "md":
            _render_md_pdf(block[1], flow, styles, Paragraph)
        elif kind == "callout":
            _icon, ttl = _CALLOUT.get(block[1], ("", "Note"))
            inner = Paragraph(f"<b>{ttl}:</b> " + _inline_md_to_rl(block[2]),
                              styles["MBody"])
            t = Table([[inner]], colWidths=[page_w])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eef2f7")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#9fb3c8")),
                ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
            flow.append(KeepTogether([t]))
            flow.append(Spacer(1, 0.15 * cm))
        elif kind == "figure":
            png = None
            if figures and not figures_hung:
                png = _fig_to_png(block[1])
                if png is _FIG_TIMED_OUT:
                    figures_hung = True   # kaleido wedged: skip the rest promptly
                    png = None
            if png:
                w, h = _png_size(png)
                img_h = page_w * (h / w) if w else 8 * cm
                flow.append(KeepTogether([
                    Image(io.BytesIO(png), width=page_w, height=img_h),
                    Paragraph(block[2], styles["MSmall"])]))
            else:
                flow.append(Paragraph(f"[figure unavailable] {block[2]}",
                                      styles["MSmall"]))
            flow.append(Spacer(1, 0.2 * cm))
        elif kind == "table":
            headers, rows = block[1], block[2]
            ncol = len(headers)
            data = [[Paragraph(f"<b>{_inline_md_to_rl(h)}</b>", styles["MSmall"])
                     for h in headers]]
            data += [[Paragraph(_inline_md_to_rl(str(c)), styles["MSmall"]) for c in row]
                     for row in rows]
            t = Table(data, colWidths=[page_w / ncol] * ncol)
            t.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
            flow.append(t)
            flow.append(Spacer(1, 0.2 * cm))

    footer = f"Sector v{APP_VERSION} - user manual"
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=2.2 * cm,
                            rightMargin=2.2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
                            title=f"Sector user manual v{APP_VERSION}")
    doc.build(flow, canvasmaker=lambda *a, **k: report._NumberedCanvas(
        *a, footer=footer, **k))


def build_manual_pdf_bytes(figures=True):
    buf = io.BytesIO()
    build_manual_pdf(buf, figures=figures)
    buf.seek(0)
    return buf.getvalue()


# ==========================================================================
# STREAMLIT RENDERER
# ==========================================================================

def render_manual_streamlit():
    """Render the manual in place of the analysis layout (viewport takeover).

    Mirrors the Quick Section builder: a session flag (``_manual_open``) makes the
    app render this instead of the normal views. Exiting is via the *Back to
    analysis* button in the sidebar (rendered by ``build_inputs``), so it is
    reachable without scrolling the manual.
    """
    c_gen, c_dl, _ = st.columns([1, 1, 4])
    if c_gen.button("Generate PDF", width="stretch", key="manual_gen_pdf"):
        with st.spinner("Building the PDF manual..."):
            try:
                st.session_state["manual_pdf"] = build_manual_pdf_bytes()
            except Exception as e:                       # never break the viewport
                st.session_state["manual_pdf"] = None
                st.error(f"PDF build failed: {e}")
    if st.session_state.get("manual_pdf"):
        c_dl.download_button("Download PDF", st.session_state["manual_pdf"],
                             file_name="Sector_User_Manual.pdf",
                             mime="application/pdf", width="stretch",
                             key="manual_dl_pdf")

    st.markdown("# Sector user manual")
    st.caption("What Sector computes, the theory it applies, its features, and how "
               "to use it.")

    n1 = n2 = 0
    for i, block in enumerate(manual_blocks()):
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
        elif kind == "callout":
            icon, title = _CALLOUT.get(block[1], (":information_source:", "Note"))
            with st.container(border=True):
                st.markdown(f"{icon} **{title}** -- {block[2]}")
        elif kind == "figure":
            try:
                # A unique key per block: two structurally-similar figures would
                # otherwise share an auto-generated element id and Streamlit raises a
                # duplicate-id error (seen once other charts exist, e.g. after Calculate).
                st.plotly_chart(block[1](), width="stretch", key=f"manual_fig_{i}")
            except Exception as e:                       # a broken figure must not
                st.caption(f"[figure unavailable: {e}]")  # break the whole manual
            st.caption(block[2])
        elif kind == "table":
            header = "| " + " | ".join(block[1]) + " |"
            sep = "| " + " | ".join(["---"] * len(block[1])) + " |"
            body = "\n".join("| " + " | ".join(str(c) for c in row) + " |"
                             for row in block[2])
            st.markdown(f"{header}\n{sep}\n{body}")
