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
from sector.build_info import source_revision
from sector import design_standards, material_presets, templates
from sector.codes import fctm
from sector.fatigue import steel_fatigue_life
from sector.materials import Concrete, Prestress
from sector.plastic import solve_plastic
from sector.section import Section
from sector.serviceability import analyse_cracking

import viz

# Display scale for the section drawings: the geometry is in metres, drawn in mm.
_MM = 1000.0
_PERMILLE = chr(0x2030)


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

def _section_fig(ex: dict, title: str, labels=True):
    # Pass the full (x, y, area) points so the drawing scales markers by relative
    # bar diameter, matching the app's section views.
    return viz.section_figure(
        ex["outer"], ex["holes"], ex["bars"], tendons=ex["tendons"], title=title,
        show_labels=labels, height=460, scale=_MM, unit="mm")


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
    # Clip the NA to the section bounds: an unclipped +/-1 m span forces the axis
    # range wide and shrinks the section (the NA is the horizontal dashes anyway).
    xs, ys = [p[0] for p in ex["outer"]], [p[1] for p in ex["outer"]]
    na = viz.na_line_at(hp[0], hp[1], hp[2], 1.0,
                        bbox=(min(xs), min(ys), max(xs), max(ys)))
    bar_xy = [(x, y) for x, y, _ in ex["bars"]]
    return viz.section_figure(ex["outer"], ex["holes"], bar_xy, na_line=na,
                              zones=zones, title="Cracked section (Stage II)",
                              show_labels=False, height=460, scale=_MM, unit="mm")


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
    return viz.fatigue_sn_figure(
        result,
        properties,
        gamma_s,
        title="Reinforcement fatigue: S-N assessment",
    )


def fig_fatigue_damage():
    result, _properties, _gamma_s = example_fatigue_reinforcement()
    return viz.fatigue_damage_figure(
        result,
        title="Reinforcement fatigue: Miner damage",
    )


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
    fig = lambda fn, cap, alt: blocks.append(("figure", fn, cap, alt))
    table = lambda hdr, rows: blocks.append(("table", hdr, rows))

    # =====================================================================
    # PART A - GET STARTED
    # =====================================================================
    part("Part A - Get started")

    h1("Introduction & purpose")
    md("**Sector** is a cross-section analysis tool for reinforced-concrete and "
       "prestressed sections. You give it an arbitrary polygonal concrete outline "
       "(with any number of voids), the mild-steel bars and prestressing tendons, "
       "and the material laws. It returns plastic capacity, cracked-section elastic "
       "response, grouped fatigue checks, independent resistance checks and a "
       "report.")
    call("concept", "Sector is a **transparent structural calculation tool**. It "
         "is not a compliance-management, certification, sign-off, authority-"
         "approval or code-completeness system. The engineer controls methods, "
         "action sets and coefficients. Selected standards supply equations, "
         "references, defaults and warnings.")
    md("The section and material-law diagrams update as you type; the result "
       "views recompute when you press *Calculate*.")
    call("limit", "Sector analyses **one plane cross-section**. It assumes plane "
         "sections remain plane (a linear strain field) and perfect bond between "
         "concrete and steel. Shear and torsion are section-level checks; buckling, "
         "second-order response and other member-level effects are outside scope.")
    call("standard", "DS/EN 1992-1-1:2023 is a selectable calculation method in "
         "Sector. Individual material and check methods remain independently "
         "selectable and are recorded with their numerical outputs. The 2023 shear methods with and without links "
         "and the refined crack model are implemented. Torsion and combined M-V-T "
         "remain on the 2005 family and are identified as such.")

    h2("What Sector computes - at a glance")
    md("- **Plastic bending capacity.** The biaxial $M_x$-$M_y$ interaction "
       "envelope at the given axial force, from the full nonlinear material laws, "
       "and the utilisation of an applied load against it.\n"
       "- **Cracked-section elastic stresses.** The concrete and reinforcement "
       "stresses from long- and short-term action components, on the cracked "
       "(tension-ignored) section, with creep through the modular ratio.\n"
       "- **Elastic and crack outputs.** Cracking threshold, transformed section "
       "properties, stresses and requested long- and short-term crack widths. "
       "A 0 mm limit leaves only that duration's calculated width; a positive "
       "limit produces only the matching specified-limit comparison and source.\n"
       "- **Grouped fatigue.** Reinforcement S-N/Miner and concrete compression "
       "checks from named spectra of sustained states and cyclic increments.\n"
       "- **Longitudinal detailing.** Edition-specific minimum-reinforcement "
       "checks per selected capacity case and a section-wide clear-spacing check.\n"
       "- **Multi-case review and reporting.** Named Plastic/capacity, Elastic and "
       "fatigue rows are summarised together, remain selectable individually, and "
       "are included in a QA PDF with formulas and code references. A project file "
       "saves the whole input set.")

    h1("Start here")
    md("Choose the shortest reading path for the task. Every destination below is "
       "the same stable destination in the PDF outline and the accessible HTML "
       "manual.")
    table(
        ["Reading path", "Use it when", "Destination"],
        [
            [
                "Quick calculation",
                "You want to define one section, calculate and review a result.",
                "[Open Quick start](#manual-quick-calculation)",
            ],
            [
                "Input reference",
                "You need one field, default, validation rule or warning.",
                "[Open Input reference](#manual-input-reference)",
            ],
            [
                "Method reference",
                "You need an implemented equation, assumption, branch or limitation.",
                "[Open Method reference](#manual-method-reference)",
            ],
        ],
    )

    h1("Quick start")
    md("1. **Define the section.** Open the *Section* panel and either edit the "
       "point tables (concrete corners, voids, bars and tendons, all in mm) or "
       "press *Quick Section builder* to generate a parametric shape.\n"
       "2. **Set the materials.** In *Material parameters* define the concrete "
       "and one or more mild-steel or prestress materials, then assign their IDs "
       "to the reinforcement rows.\n"
       "3. **Choose the analyses.** In *Analysis settings* pick Plastic, "
       "Elastic or Both, enable Fatigue if required, and set the selected "
       "methods and factors.\n"
       "4. **Enter the cases.** Add uniquely named rows to the Plastic/capacity, "
       "Elastic and grouped-fatigue tables. Optionally request crack width on "
       "each Elastic row; stresses are always reported.\n"
       "5. **Calculate.** Open *Analysis*, review *Results Overview*, then select "
       "a case in each detailed result view.\n"
       "6. **Export.** Generate the PDF report or download the project file.")
    fig(fig_beam_section, "The rectangular worked example as Sector draws it: the "
        "concrete corners and bars are numbered. Use the *Display* controls beside "
        "your Section inputs to adjust label size and spacing.",
        "A rectangular concrete outline with four numbered corner nodes, three "
        "numbered reinforcement bars near the lower face and two near the upper face.")

    h1("Task workflows")
    md("Each row states the intended outcome, prerequisite, action path, expected "
       "state and the troubleshooting entry to use when the expected state is not "
       "reached.")
    table(
        ["Workflow / outcome", "Before and do", "Expected state / if blocked"],
        [
            [
                (
                    f"[{workflow.label}](#{manual_ia.destination(workflow.destination_key).anchor}) - "
                    f"{workflow.outcome}"
                ),
                (
                    f"**Before:** {workflow.prerequisite}. "
                    f"**Do:** {workflow.action}"
                ),
                (
                    f"**Expected:** {workflow.expected_state}. "
                    "**If blocked:** "
                    f"{manual_ia.warning_reference(workflow.warning_key).correction}"
                ),
            ]
            for workflow in manual_ia.WORKFLOWS
        ],
    )

    h1("The worked examples")
    md("Two sections are threaded through this manual. Every worked derivation in "
       "Part C is carried out on one of them, and the figures are generated from "
       "them live, so the numbers you read here match what the app produces.")
    h2("Rectangular beam (mild steel)")
    md("A 300 x 600 mm rectangular section in C40/50 concrete with B550 "
       "reinforcement: three 25 mm bars near the bottom face and two 16 mm bars "
       "near the top. It is the simplest section that still exercises the plastic "
       "capacity, the cracked-elastic stresses and a crack width.")
    fig(fig_beam_section, "Rectangular beam: 3 x 25 mm bottom, 2 x 16 mm top.",
        "A 300 by 600 mm concrete rectangle with three bottom bars and two top bars "
        "arranged symmetrically about the vertical centreline.")
    h2("Circular hollow section (mild + prestress)")
    md("An 800 mm diameter circular section with a 400 mm central void, a ring of "
       "twelve 20 mm mild bars and a ring of eight prestressing tendons, in C40/50 "
       "concrete. It adds the void handling, the ring (biaxial) reinforcement "
       "layout and the prestress law on top of the beam.")
    fig(fig_circular_section, "Circular hollow section: a central void, a mild-bar "
        "ring and a tendon ring.",
        "An annular concrete section with concentric outer and void boundaries; mild "
        "reinforcement and prestressing tendons form two circular rings.")
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
       "- **Crack-width calculation.** Calculate the service crack width with the "
       "selected numerical method and the actual named action.\n"
       "- **Grouped fatigue verification.** Check several independently defined "
       "spectra and review each bar, tendon, concrete fibre and spectrum bin.\n"
       "- **Comparing layouts.** Change the bars or the concrete grade and read the "
       "capacity and crack width straight back.")

    # =====================================================================
    # PART B - FEATURES & OPTIONS
    # =====================================================================
    part("Part B - Features & options")

    h1("Input reference")
    md("The reference follows the same five stages as the application. Select a "
       "stage below, then use the shared field definitions and troubleshooting "
       "entries in this part.")
    table(
        ["Application stage", "Manual destination"],
        [
            [stage.label, f"[Open {stage.label}](#{stage.anchor})"]
            for stage in manual_ia.INPUT_STAGES
        ],
    )

    h1("The workspace")
    md("The **Inputs** page stages *Analysis settings*, *Section*, *Material "
       "parameters*, *Loads* and *Project* in full-width tabs. The "
       "*Section* tab places the section drawing beside its point tables, and each "
       "material panel places the selected stress-strain law beside its parameters. "
       "These previews update live. The **Analysis** workspace contains calculated "
       "results selected with the **View** dropdown. The **Report** workspace, "
       "immediately to its right, owns document metadata, profile selection, "
       "generation and PDF download.")
    table(["View", "Shows"],
          [["Results Overview", "One most-unfavourable retained result per semantic check type, with the governing action or direction preserved"],
           ["Plastic Results", "Selected case: M-M envelope and utilisation"],
           ["N-M Interaction", "Selected Plastic case: axial-moment boundaries"],
           ["Elastic Results", "Selected case: stresses, cracking and crack width"],
           ["Fatigue Results", "All spectra; selected spectrum, element, fibre and bin evidence"],
           ["Detailing", "Selected case: modelled-direction minimum reinforcement and link detailing; section-wide spacing"],
           ["Shear", "Selected Plastic case: Vx/Vy summary and directional details"],
           ["Torsion", "Selected Plastic case: torsion resistance and utilisation"],
           ["M-V-T Combined", "Selected Plastic case: combined interactions"]])
    h2("Report workspace")
    md("Enter project number, project name, section, revision, author and comments "
       "in this workspace, then select **Brief**, **Standard** or **Audit**. "
       "Generating reuses retained Analysis results only when their complete input "
       "signature matches the current inputs; otherwise Sector recalculates for the "
       "report and records that source. A metadata or input edit marks an existing "
       "PDF out of date and blocks its download until it is regenerated.")
    call("tip", "Report metadata and publication controls are grouped separately "
         "from the Project input stage. Save/load and autosave remain under "
         "**Inputs > Project**; publication remains under **Report**.")
    call("tip", "*Auto-calc all derived values* (in Material parameters) "
         "recomputes every auto quantity from the current grade at once: the concrete "
         "strain limits, $f_{ctm}$ and $E_c$. The modular ratios follow from $E_c$, "
         "$E_s$, $E_p$ and creep automatically.")

    h1("Project")
    h2("Project files and autosave")
    md("A downloaded project file stores the section, materials, settings, named "
       "load cases and provenance. Loading a project restores its inputs and clears "
       "earlier results. Review the restored inputs, then press *Calculate* before "
       "using or reporting results.")
    md("Local autosave is enabled by default at a five-minute interval. A due save "
       "runs on the next interaction and is restored on the next launch. Keep the "
       "issued project file with the calculation record; autosave is recovery, not "
       "an issued deliverable.")
    h1("Defining the section")
    md("A section is a set of explicit points in millimetres -- the concrete "
       "corners, any voids, the bars and the tendons. The point tables are the "
       "**source of truth**; the Quick Section builder is a convenience that writes "
       "into them.")
    h2("The point tables")
    md("Four editable tables hold the concrete corners, the voids, the bars "
       "and the tendons. Coordinates and diameters are in millimetres; areas are "
       "in square millimetres. Each reinforcement element has a fixed ID used by "
       "the figures, results and report. Deleting another row does not renumber it.")
    table(["Size basis", "Entered", "Calculated"],
          [["Area", "Area", "Equivalent circular diameter"],
           ["Diameter", "Diameter", "Area of one circular element"],
           ["Independent", "Area and diameter", "Neither"]])
    md("Area controls section stiffness and resistance; diameter controls detailing "
       "and crack-spacing geometry. *Independent* is therefore appropriate when "
       "one point represents a non-circular or grouped steel area. Material and "
       "fatigue-detail IDs are assignments carried with the element. Use **Bulk "
       "assignments** above a reinforcement table to update all or selected IDs. "
       "A fatigue "
       "detail is required on every bar and tendon when reinforcement fatigue is "
       "enabled; otherwise it is optional. Half-typed rows are ignored until "
       "complete.")
    call("concept", "Everything downstream reads these points. The builder, the "
         "presets and the save file all end up as rows in these four tables, so you "
         "can always edit the geometry by hand.")
    h2("The Quick Section builder")
    md("A full-width builder (opened from the *Section* panel) generates a "
       "parametric shape with a live preview, then *Apply* writes its points into "
       "the tables (or *Back* leaves them untouched). Reinforcement can be given by "
       "a bar count or by a spacing, in one or several layers, and tendons as a "
       "ring or in layers where that placement is unambiguous. The bottom and top "
       "faces take their own cover and bar diameter (entered directly in mm), a "
       "stacked upper layer can hold a different bar count than the main row, and "
       "a toggle measures the cover to the bar edge instead of its centre.")
    table(["Shape", "Produces"],
          [["Rectangle", "A solid rectangle b x h"],
           ["Slab strip", "A 1 m-wide strip of a given thickness"],
           ["Trapezoid", "A symmetric trapezoid with horizontal faces"],
           ["T-section", "A flange over a web, flange at top or bottom"],
           ["L-section", "A left web with a bottom flange"],
           ["I-section", "Equal top/bottom flanges around a central web"],
           ["U-section", "An open-top base with two side webs"],
           ["Box girder", "A hollow box (one rectangular void)"],
           ["Circular", "A circular section, optionally with a bar ring"],
           ["Annulus", "A circular hollow section (one circular void)"]])
    md("Trapezoid, L-section and U-section apply their concrete geometry only: "
       "automatic face reinforcement is not defined for those non-uniform or "
       "split faces. Add their bars and tendons directly in the point tables. "
       "The T-section, I-section and annulus provide bounded automatic placement, "
       "and the builder blocks Apply if a dimension, layer or ring would create "
       "invalid geometry or put a generated point outside concrete.")
    h2("Validity checks")
    md("Geometry is validated before any solver runs. Every outer or hole ring "
       "must contain finite numeric coordinates, at least three distinct points "
       "and an area above the resolved tolerance. A ring is rejected for a "
       "repeated or tolerance-coincident vertex, a non-adjacent crossing, touch or "
       "overlap, or an adjacent edge that reverses along the same line. Forward "
       "collinear points and one exact final point equal to the first are allowed. "
       "Clockwise and counter-clockwise winding are both valid; Sector retains the "
       "entered order and uses oriented copies only for integration.")
    md("Every hole must be strictly inside the outer ring. It cannot touch or cross "
       "the outer boundary, touch/cross/overlap another hole, or contain another "
       "hole. The concrete net area must remain connected, and every bar and tendon "
       "must lie in concrete rather than outside it or inside a void. The first "
       "causal defect is reported with its ring, point or edge location.")
    call("concept", "The length tolerance is the greatest of **1e-12 m**, "
         "**1e-9 times the section span** and **8 ULP of the coordinate magnitude**. "
         "Coordinates are classified but never snapped or rewritten. A geometry "
         "validation failure is distinct from a valid section whose numerical "
         "solver later fails to converge.")
    call("limit", "A void must leave the concrete in one connected piece. A slot "
         "that splits the section in two is rejected rather than analysed, because "
         "the plane-section assumption no longer holds across a break.")

    h1("Materials")
    md("Concrete has one definition. Mild steel and prestress use catalogues: each "
       "definition has a stable ID, name and optional description. Add, duplicate "
       "or delete definitions in the material panel, then assign the ID to each bar "
       "or tendon in the Section table. An assigned definition cannot be deleted. "
       "A preset supplies starting values for the selected definition; every value "
       "can then be adjusted.")
    call("limit", "Enter the **final effective** material partial factors in the "
         "material panels, including every applicable national increase or reduction "
         "for construction, control and consequence category. Sector does not ask for "
         "those categories and applies no hidden category multiplier.")
    h2("Concrete")
    md("The concrete stress-strain law is chosen by the *Preset*: **Curve 2 "
       "(parabola-rectangle)**, the EC2 design law used throughout this manual, or "
       "**Curve 1 (cubic)**, a user-defined cubic curve for normal-strength concrete. "
       "The inputs are the "
       "characteristic strength $f_{ck}$, the partial factor $\\gamma_c$, the "
       "coefficient $\\alpha_{cc}$, the strain limits $\\varepsilon_{c2}$ and "
       "$\\varepsilon_{cu2}$ with the exponent $n$, the elastic modulus $E_c$ and "
       "the mean tensile strength $f_{ctm}$. The strain limits, $E_c$ and $f_{ctm}$ "
       "have *Auto* buttons that derive them from $f_{ck}$ and the edition.")
    call("standard", "For DS/EN 1992-1-1:2023, Sector derives the read-only effective "
         "coefficient $\\eta_{cc}k_{tc}$ and exposes $k_{tc}$ separately. The "
         "default is **0.85** (general / other cases). Selecting **1.00** explicitly "
         "assumes the reference-age and at-least-three-month delayed design-loading "
         "conditions stated in 5.1.6(1); that assumption is repeated in the PDF.")
    fig(fig_beam_concrete_law, "The concrete-law preview for the rectangular "
        "example (C40/50).",
        "A compression stress-strain curve that rises parabolically from zero to the "
        "design strength and then remains horizontal to the ultimate strain.")
    h2("Mild steel")
    md("Each mild-steel definition uses the general **Curve 3** law, with every "
       "parameter visible and live. The generic **Curve 1**, **Curve 2** and "
       "**Curve 3** selections are user-defined/project-defined starting-value "
       "presets and are explicitly uncited. An edition-named selection is labelled "
       "a **Curve 3 Eurocode design preset** and retains that edition's source. "
       "The preset never locks the law: edited numerical values are the actual "
       "calculation inputs. The selected definition's plot is shown beside its "
       "inputs. These include yield and ultimate strengths, ultimate strain, the "
       "partial factors, yield offsets, first-yield ratio and modulus $E_s$. The "
       "**Active in compression** toggle decides whether the bars carry "
       "compression in the **plastic** law: with it off the steel is "
       "tension-only there. The cracked-elastic analysis is linear and "
       "always treats the bars in both directions, regardless of this toggle.")
    fig(fig_beam_steel_law, "The B550 mild-steel law for the rectangular example.",
        "A symmetric reinforcing-steel stress-strain curve with linear tension and "
        "compression branches to yield followed by the selected post-yield response.")
    call("standard", "Edition-named concrete and steel presets carry their selected "
         "Eurocode source (including 3.1.7 / 3.2.7 for the 2005 family). Generic "
         "named curves and custom/imported laws are project-defined and uncited; "
         "numerical similarity never assigns them a standard identity.")
    h2("Prestressing steel")
    md("Each prestress definition adds the tendon law and, crucially, the initial strain "
       "$\\varepsilon_{p,IS}$ locked into the tendons. The inputs mirror the mild "
       "steel plus that initial strain. Tendons are analysed at their **total** "
       "strain -- the initial strain plus the section strain at their location.")
    call("concept", "Plastic capacity, cracked-elastic stiffness and stress, and "
         "crack calculations use the material assigned to each element. Shared "
         "member checks for shear and torsion use the explicitly selected mild-"
         "steel reference material; its ID is shown with those settings and results.")
    fig(fig_circular_prestress_law, "The tendon law for the circular example.",
        "A prestressing-steel stress-strain curve with an initial elastic branch and "
        "a nonlinear approach to design strength and ultimate strain.")

    h1("Analysis & result settings")
    h2("Analysis mode")
    md("*Analysis* selects the calculation method: **Plastic** (nonlinear M-M "
       "capacity), **Elastic** (cracked-section stresses), or **Both**. These names "
       "do not prescribe a limit state; classify each action set for the project.")
    h2("The plastic sweep")
    md("The envelope is traced by rotating the neutral axis from $V_{min}$ to "
       "$V_{max}$ in steps of $V_{inc}$ (degrees). Each angle gives one point on "
       "the $M_x$-$M_y$ envelope at the design axial force. *Check utilisation* "
       "compares the applied moment to the envelope; turning it off reports the "
       "capacity only.")
    fig(fig_beam_envelope, "The rectangular example's biaxial envelope with the "
        "applied load; the sweep from 0 to 360 degrees closes the curve.",
        "A closed Mx-My capacity boundary around the origin with one applied-load "
        "point; successive boundary vertices correspond to rotated neutral-axis "
        "solutions.")
    h2("Reinforcement detailing")
    md("Select **Beam** or **Slab**. **Section cut direction** fixes the canonical, "
       "member-relative modelled reinforcement direction. Sector checks only the "
       "bars represented by that cut; it does not request an unmodelled orthogonal "
       "layer.")
    table(["Section cut", "Canonical modelled reinforcement direction"],
          [["Transverse cut", "Longitudinal"],
           ["Longitudinal cut", "Transverse"]])
    md("In words, a transverse cut models the Longitudinal reinforcement, while "
       "a longitudinal cut models the Transverse reinforcement.")
    md("The optional **Project direction alias** records local terminology, for "
       "example *span direction*. Sector publishes it in parentheses after the "
       "canonical direction; an alias never replaces the canonical Longitudinal "
       "or Transverse meaning and does not change a calculation.")
    md("Enable **Check minimum reinforcement in modelled direction** and select the check on each "
       "required Plastic/capacity row. The selected detailing edition and the "
       "global $f_{ctm}$ apply to those rows. A secondary-direction slab minimum is "
       "reported as not assessed because its 20% criterion depends on primary "
       "reinforcement outside the modelled cut. Enable **Clear spacing** for one "
       "section-wide pairwise check and enter $D_{upper}$; tendons are excluded "
       "unless explicitly included, in which case their entered diameter must be "
       "the detailing envelope or duct diameter.")
    md("Enable **Check shear/torsion link detailing** to check each "
       "non-zero shear/torsion case. The shared stirrup diameter, longitudinal "
       "spacing and yield strength are used. Enter the maximum transverse distance "
       "between effective legs for each shear direction, or leave it at zero for "
       "a gross-web upper-bound screen. The screen can establish a passing spacing "
       "check, but an "
       "actual spacing is required when the bound exceeds the limit. For the 2023 "
       "edition, select the "
       "reinforcement ductility class and explicitly choose whether its favourable "
       "minimum-ratio reduction is used. Under the 2005 method, an ordinary beam "
       "with non-zero shear requires minimum links; slab omissions follow the "
       "verified no-link resistance. The 2023 method follows the verified need for "
       "links; for a beam with $d>500$ mm and no calculated link requirement, "
       "Sector reports the structural-system condition in 8.2.1(2) as not assessed. "
       "A missing requirement fails without changing the input.")
    table(["Member", "Vertical shear-link spacing limits"],
          [["Beam", "$s_l \\leq 0.75d$; $s_t \\leq \\min(0.75d,600\\,\\text{mm})$"],
           ["Slab", "$s_l \\leq 0.75d$; $s_t \\leq 1.5d$"]])
    md("$s_t$ is measured in the section plane between adjacent parallel link "
       "legs: along $y$ for $V_x$ and along $x$ for $V_y$. It is not the "
       "longitudinal spacing $s_l$, and it does not require shortening a closed "
       "stirrup.")
    call("standard", "EN 1992-1-1:2005 9.2.3(4)'s 350 mm value applies to "
         "longitudinal torsion bars around the link perimeter, not to spacing "
         "between closed links.")
    table(["Edition", "Minimum-reinforcement method"],
          [["EN 1992-1-1:2005 / DK NA:2024",
            "$A_{s,prov} \\geq A_{s,min}$ in the resultant bending-tension zone (9.1N)"],
           ["DS/EN 1992-1-1:2023",
            "Nominal section resistance at characteristic bar yield compared with the cracking action (12.1/12.2)"]])
    call("limit", "Prestressing tendons are not credited in the minimum-"
         "reinforcement check. The DK NA side-face reinforcement rule for high "
         "beam webs, lap length and bundle verification remain separate detailing "
         "reviews. Ordinary bars are assumed anchored to develop the entered "
         "$f_{yk}$; reduce it where the force cannot be developed.")
    h2("Crack width")
    md("Tick **Crack width** on each Elastic table row that requires the numerical output. "
       "If any row is ticked, the global crack settings apply to every ticked row. "
       "The diameter override $\\phi$ (0 = each element's table diameter; Area "
       "mode derives it from area), the "
       "mild-steel bond coefficient $k_1$ (0.8 ribbed, 1.6 plain), the code edition "
       "and -- for the DK NA -- the member type are the inputs.")
    table(["Crack-width code", "What it changes"],
          [["EN 1992-1-1:2005", "The base EC2 model (7.3.4): $s_{r,max}$ from 7.11 / 7.14"],
           ["DS/EN 1992-1-1 + DK NA", "Cover-dependent $k_3$ and the $(h-x)/3$ term for slabs / prestressed only; reports **both** the fine and the coarse crack system (the coarse: centroid-matched effective area, fig 7.100 NA, $w_k$ halved)"],
           ["DS/EN 1992-1-1:2023", "The refined model (9.2.3): $w_k = k_w\\,(k_1/r)\\,s_{r,m,cal}\\,(\\varepsilon_{sm}-\\varepsilon_{cm})$"]])
    call(
        "standard",
        f"Sector {APP_VERSION} reports the DK NA fine and coarse crack systems "
        "side by side, each for the long-term and short-term load (four crack "
        "widths) for each crack-width-enabled Elastic row. Analysis settings "
        "provide independent long-term and short-term user limits. Zero means "
        "that duration is "
        "calculated without a limit comparison; when a positive value is "
        "entered, Sector reports only a bounded duration-matched comparison and "
        "does not infer exposure, durability, load-combination classification, "
        "prestress category or owner requirements. Part C derives every model in "
        "full with the critical worked crack width.",
    )
    md("For the first-generation Danish basis only, **DK heightened crack-control "
       "minimum** is a separate section-level opt-in. The user must declare its "
       "applicability and supply the separate Formula 7.100 NA permitted width, "
       "reinforcement surface, effective tensile strength and separate fine/coarse "
       "effective tension areas. "
       "Sector calculates both systems together. It derives bar diameter, reinforcement "
       "modulus and provided area from one retained ordinary crack-enabled Elastic "
       "case: the sole such case is automatic, otherwise the user selects it explicitly.")
    h2("Grouped fatigue")
    md("Enable **Fatigue analysis**, select the fatigue edition, then enable "
       "**Reinforcement** and/or **Concrete**. Enter the complete project factors "
       "$\\gamma_{Ff}$, $\\gamma_s$ and $\\gamma_{c,fat}$. Sector applies no "
       "control-, construction- or consequence-class multiplier.")
    md("For concrete, select **Explicit Palmgren-Miner spectrum** or "
       "**Damage-equivalent stress amplitude**. The explicit method uses every "
       "entered cycle count. For the equivalent method, each row's long/total "
       "action pair must already represent an equivalent amplitude for $10^6$ "
       "cycles; its Cycles value is ignored for concrete.")
    table(["Input", "Use"],
          [["$\\gamma_{Ff}$", "Factors the cyclic action increment before the elastic solve"],
           ["$\\gamma_s$", "Reduces the reinforcement S-N resistance and yield/proof limit"],
           ["$\\gamma_{c,fat}$", "Reduces the concrete fatigue strength"],
           ["$\\beta_{cc}(t_0)$, $t_0$", "Concrete strength at the start of cyclic loading"],
           ["$k_1$, $C$", "2005 concrete-strength coefficient; C applies only to the explicit concrete-life method"]])
    md("The **Fatigue details** material tab holds named resistance definitions. "
       "Assign one stable detail ID to every checked bar or tendon. Standard presets "
       "lock $N^*$, the two S-N slopes, the characteristic reference range and its "
       "source; Custom / imported makes them editable. Diameter-dependent and "
       "bent-bar reductions are applied where the selected preset requires them. "
       "For a section combining mild reinforcement and bonded tendons, each tendon "
       "also needs the bond ratio $\\xi$ and equivalent tendon diameter.")
    md("The **Spectrum basis** records the selected grouped-spectrum method and "
       "optional action-set notes. Every action and cycle count is used as entered; "
       "Sector does not infer traffic completeness or an owner-specific route.")
    table(["Fatigue edition", "Implemented resistance basis"],
          [["DS/EN 1992-1-1:2005",
            "Steel 6.8.4 and Tables 6.3N/6.4N; concrete 6.72 equivalent method or corrected DS/EN 1992-2 6.106 Miner method"],
           ["DS/EN 1992-1-1:2005 + DK NA:2024",
            "Same calculation models, with the complete Danish project factors entered explicitly"],
           ["DS/EN 1992-1-1:2023",
            "Reinforcement Annex E.5 and Tables E.1/E.2; concrete E.2 equivalent method or E.7-E.8 Miner method"]])
    call("limit", "Each named spectrum is assessed independently. Sector does not "
         "combine spectra or derive traffic cycles, dynamic allowance or lane/track "
         "concurrence. Fatigue from shear and torsion is not included.")
    h2("Shear (Vx,Ed and Vy,Ed)")
    md("With **Check shear capacity** on, Sector computes the design shear "
       "resistance $V_{Rd,c}$ of a member **not** requiring shear reinforcement "
       "(EN 1992-1-1 6.2.2) in each active direction. Signed $V_{x,Ed}$ and "
       "$V_{y,Ed}$ are entered per Plastic/capacity row; zero disables only that "
       "component.")
    table(["Component", "Geometry and associated bending"],
          [["$V_{x,Ed}$", "Along x; depth in x; left/right faces; paired with $M_{y,Ed}$"],
           ["$V_{y,Ed}$", "Along y; depth in y; bottom/top faces; paired with $M_{x,Ed}$"]])
    md("Face selection is **Auto** by default. Sector transfers the associated "
       "moment to the concrete centroid and includes the locked-in tendon moment; "
       "a positive adjusted moment selects the negative-coordinate face and a "
       "negative adjusted moment selects the positive face. "
       "If that moment is zero, both faces are checked and the governing result is "
       "reported separately for shear, V+T and combined checks, including the "
       "governing face and strut angle where applicable. The row can override either "
       "face. The sign of shear does not select "
       "the tension face. Web-width overrides and effective link-leg counts are "
       "directional; method, aggregate and stirrup properties are shared.")
    call("limit", "When both shear components are nonzero, Sector reports two "
         "independent directional checks. It does **not** calculate a generic "
         "cross-direction interaction or issue an aggregate Vx+Vy verdict. With "
         "torsion, each validated V+T direction is calculated separately; a generic "
         "three-component Vx+Vy+T interaction is **NOT CALCULATED**.")
    md("Where torsion is active, the report also retains the directional Equation "
       "6.31 minimum-reinforcement screen for Vx+T and Vy+T. This screen states "
       "whether minimum reinforcement suffices; it is not an overall resistance "
       "verdict.")
    table(["Shear method", "What it sets"],
          [["EN 1992-1-1:2005", "$C_{Rd,c} = 0.18/\\gamma_c$, $k_1 = 0.15$, "
            "$v_{min} = 0.035\\,k^{1.5}\\sqrt{f_{ck}}$"],
           ["DS/EN 1992-1-1:2005 + DK NA:2024", "As 2005 but the raised "
            "$v_{min} = (0.051/\\gamma_c)\\,k^{1.5}\\sqrt{f_{ck}}$"],
           ["DS/EN 1992-1-1:2023", "The strain-based $\\tau_{Rd,c}$ (8.2.2) with the "
            "aggregate size $d_{dg}$ and the user-selected $\\gamma_V$ without "
            "links (default 1.40); the "
            "compression-field method (8.2.3) with links"]])
    call("standard", "DS/EN 1992-1-1:2023, 4.3.3 and Table 4.3 (NDP), "
          "define $\\gamma_V$ for shear resistance without shear reinforcement. "
          "Sector defaults the input to 1.40 but does not force that value; the "
          "engineer selects the positive value required by the applicable project "
          "basis. Clause 8.2.2 then uses the selected value. The **2023 method** uses "
          "$\\tau_{Rd,c} = (0.66/\\gamma_V)(100\\rho_l f_{ck} d_{dg}/d)^{1/3} \\geq "
          "\\tau_{Rd,c,min}$ (8.27), with $d_{dg} = 16 + D_{lower}$ ($\\leq 40$ mm, "
          "8.2.1(4)) and the flexural design yield $f_{yd}$. When axial force is "
          "present, Sector applies $d \\rightarrow k_{vp}d$ in (8.27), with "
          "$k_{vp}=\\max[1+N_{Ed}/|V_{Ed}|\\,d/(3a_{cs}),0.1]$ and "
          "$a_{cs}=\\max(|M_{Ed}/V_{Ed}|,d)$ (8.30-8.31), including locked-in "
          "prestress effects. Tendons are assumed parallel to the member axis "
          "($\\cos\\beta=1$), because a cross-section model has no longitudinal "
          "tendon inclination. Members **with** links use the compression-field "
          "method in 8.2.3; torsion and the combined lock stay on the 2005 family.")
    call("limit", "$A_{sl}$ is the tension-face bars, **assumed fully anchored** "
          "($\\geq l_{bd} + d$). Sector does not check anchorage; where reinforcement "
          "is not fully anchored, the user must enter an appropriately reduced "
          "$f_{yk}$ / $f_{ywk}$ before relying on the result.")
    md("With **Shared links / closed torsion stirrups present** on, the shear "
       "resistance becomes "
       "$V_{Rd} = \\min(V_{Rd,s}, V_{Rd,max})$ (6.2.3 or 8.2.3) instead of "
       "$V_{Rd,c}$ (which is still shown, to indicate whether links are strictly "
       "required). The link inputs are the effective legs for each direction, the bar diameter and the "
       "spacing $s$ (so $A_{sw} = n_{legs}\\,\\pi\\phi^2/4$), the link yield "
       "$f_{ywk}$, and one compression-strut range $\\cot\\theta_{min}$ / "
       "$\\cot\\theta_{max}$ entered under **Links / stirrups**. A stand-alone "
       "capacity check maximises $V_{Rd}$ within that range. When live member "
       "actions are combined, Sector selects one angle within the same range to "
       "minimise the governing utilisation.")
    call("standard", "EN 1992-1-1 6.7N (and the DK NA:2024 6.7a NA for class B/C "
         "steel) allow $1 \\leq \\cot\\theta \\leq 2.5$; the DK NA takes the strut "
         "factor $\\nu_1 = \\nu_v = 0.7 - f_{ck}/200 \\geq 0.45$ (5.103 NA) rather "
         "than the recommended $\\nu = 0.6(1 - f_{ck}/250)$. Bounds outside the "
         "code range are allowed for exploration, but Sector withholds the code "
         "verdict for the links and every dependent interaction check.")
    call("standard", "For DS/EN 1992-1-1:2023, "
         "$\\tau_{Rd,sy}=\\rho_w f_{ywd}\\cot\\theta$ (8.42) and "
         "$\\sigma_{cd}=\\tau_{Ed}(\\cot\\theta+\\tan\\theta)\\leq\\nu f_{cd}$ "
         "(8.44), with $\\nu=0.5$. The upper angle limit is 2.5 for class B/C, "
         "reduced by 20% for class A and reduced further by axial tension per "
         "8.2.3(4). Sector does not credit the favourable compression extension "
         "towards 3.0 because the required $x<0.25d$ member condition is not "
         "established by an isolated section.")
    h2("Torsion (TRd, thin-walled tube)")
    md("With **Check torsion capacity** on, Sector idealises the section as a "
       "thin-walled closed tube (6.3) and reports the closed-stirrup resistance "
       "$T_{Rd,s}$, the strut-crushing $T_{Rd,max}$, the cracking $T_{Rd,c}$, the "
       "utilisation $T_{Ed}/T_{Rd}$ and the required longitudinal steel "
       "$\\sum A_{sl}$. The signed $T_{Ed}$ is entered per Plastic/capacity row; "
       "zero means not evaluated for that row. Torsion has an optional single-tube "
       "wall-thickness override $t_{ef}$ (0 = auto). Subdivision requires 0: Sector "
       "then derives $t_{ef}$ automatically and independently for every sub-tube. "
       "The compression-strut range is entered once "
       "under **Links / stirrups** and is shared with shear. "
       "The tube $A$, $u$, $t_{ef}$, $A_k$ and $u_k$ are derived from the outline. "
       "The concrete tensile factor $\\gamma_{ct}$ is a direct positive-finite "
       "input in $f_{ctd}=f_{ctk,0.05}/\\gamma_{ct}$ (EN default 1.50; DK/NA "
       "default 1.70); a custom value is used and reported unchanged. "
       "The **stirrup is one current shared physical input**: shear uses the "
       "selected number of effective vertical legs, while torsion requires a "
       "closed, anchored loop and uses one leg of that loop for $A_{sw}/s$. "
       "Positive stored diameter or spacing does not imply that links are "
       "present. Without the shared-link selection, Sector reports "
       "$T_{Rd,max}$ only as a concrete-strut cap and $T_{Rd,c}$ as cracking "
       "transparency; it does not publish $T_{Rd}$, utilisation, a governing "
       "resistance or PASS/FAIL. The calculated $\\sum A_{sl}$ remains an "
       "informational requirement at the displayed cap angle, not proof of "
       "provided torsion reinforcement. With current links, the longitudinal "
       "steel uses the section's mild-reinforcement design yield.")
    call("standard", "$T_{Rd,max}$ uses the code torsion strut factor: recommended "
         "$\\nu = 0.6(1 - f_{ck}/250)$, or the DK NA:2024 pure-torsion "
         "$\\nu_t = 0.7\\,(0.7 - f_{ck}/200)$ (5.104 NA). The favourable "
         "$\\nu_t=\\nu_v$ detailing option is applied only when current closed "
         "links are present. When the shared links are current, the combined "
         "concrete-crushing check "
         "$T_{Ed}/T_{Rd,max} + V_{Ed}/V_{Rd,max} \\leq 1$ (6.29) is added.")
    call("limit", "A re-entrant T, L, I or flanged outline is a compound section. "
         "Sector detects it and withholds the single-tube resistance and verdict until "
         "**Subdivide into sub-tubes** is enabled and positioned component rectangles "
         "are defined by global centre x/y and b/h (6.3.1(3)). Sector checks that their "
         "non-overlapping union equals the concrete net area, stays inside the outline "
         "and does not enter a void; until that geometric partition is valid, torsion "
         "and dependent interaction are not evaluated. Multi-cell sections likewise "
         "require subdivision. Strut bounds outside the selected method's default "
         "range remain actual calculation inputs; Sector reports the resulting "
         "demand/resistance verdict with a warning.")
    h2("Combined M-V-T interaction")
    md("With **Check combined M-V-T** on, Sector ties the bending (plastic $M$), "
       "shear ($V$) and torsion ($T$) checks together under **one shared code "
       "edition** (the per-check method selectors are then locked to it). It reports "
       "the concrete-crushing interaction (6.29) and the DK NA "
       "$\\sum(S_{Ed}/S_{Rd}) \\leq 1$ rule (6.3.2(6)), and lists the additional "
       "longitudinal steel that shear and torsion demand. The summary separates the "
       "three physical component checks: concrete compression strut, shared closed "
       "stirrup and governing longitudinal reinforcement. All three checks (Plastic, "
       "Shear, Torsion) must be enabled, and the row must have nonzero $V_{Ed}$ and "
       "$T_{Ed}$; otherwise the combined check is not applicable to that row.")
    call("standard", "DK NA 6.3.2(6): $\\sum(S_{Ed}/S_{Rd}) \\leq 1$ sums each "
         "action's utilisation (the axial $N$ is folded into the bending term). If "
         "the longitudinal steel for shear beyond bending is provided, tick **M & V "
         "separate** -- then $M$ and $V$ are not summed together but checked in two "
         "independent investigations, $\\max(M+T,\\,V+T)$.")
    h2("Modular ratios and creep")
    md("The cracked-elastic analysis uses a short-term modular ratio $n_s = E/E_c$ "
       "and a long-term $n_l = E/E_{c,eff}$, the latter carrying creep through the "
       "effective modulus $E_{c,eff} = E_c/(1+\\varphi)$. These ratios are **not "
       "entered** -- they are derived from the elastic moduli and the creep "
       "coefficient $\\varphi$. The appropriate $E_s$ or $E_p$ is used for each "
       "bar or tendon, so different material definitions may have different ratios. "
       "The ratios of every material used in the section are reported.")

    h1("Loads")
    md("Loads are entered in three editable tables. Every active row has one name, "
       "and names are unique across the Plastic/capacity, Elastic and fatigue-bin "
       "rows. Use the optional description for the project classification, "
       "combination or source. Add, delete, paste and reorder rows directly in the "
       "tables.")
    table(["Table", "Per-row fields", "Row-specific rule"],
          [["Plastic / capacity", "$N_{Ed}$, $M_{x,Ed}$, $M_{y,Ed}$, $V_{x,Ed}$, $V_{y,Ed}$, $T_{Ed}$",
            "Zero shear/torsion skips that component; minimum reinforcement is selected per row"],
           ["Elastic", "Long- and short-term $N_{Ed}$, $M_{x,Ed}$, $M_{y,Ed}$",
            "Stresses are always output; optionally calculate crack width"],
           ["Grouped fatigue", "Spectrum, bin name, cycles; long- and short-term $N_{Ed}$, $M_{x,Ed}$, $M_{y,Ed}$",
            "Repeated Spectrum labels form one Miner sum; each spectrum is independent"]])
    table(
        ["Editable table", "Fields / notation", "Blank / default"],
        editable_table_reference_rows(),
    )
    h2("Editable table field definitions")
    table(
        [
            "Table",
            "Field / notation",
            "Definition and sign",
            "Blank/default and validation",
            "Method dependency",
        ],
        editable_field_reference_rows(),
    )
    md("The seven editable-table definitions above are the same definitions used "
       "by the input screens. Open the guide immediately above a table for each "
       "field's meaning, unit, sign convention, source and blank behaviour. The "
       "Plastic/capacity and Elastic action fields, and grouped-fatigue numeric "
       "fields, accept either a dot or comma as the decimal separator; ambiguous "
       "grouped or mixed separators are rejected. Blank ordinary action cells are "
       "normalised to canonical zero. Optional-null fields remain absent rather "
       "than becoming zero, while required identity and cycle fields must be "
       "entered. Sector retains the entered numeric precision internally; display "
       "rounding does not change the calculation value.")
    md("The Elastic long-term and short-term components are solved together. The "
       "single global creep coefficient $\\varphi$ applies to all Elastic rows. "
       "Concrete, reinforcement and tendon stresses are outputs for every row. "
       "Crack width includes both the sustained and total long-plus-short response "
       "for each selected row. No stress, crack-width, exposure, durability, "
       "decompression or required-combination criterion is applied.")
    md("The creep-coefficient input help follows the selected concrete preset. "
       "The first-generation source is 3.1.4 and Annex B.1. The Danish preset "
       "also identifies DK NA:2024 3.1.4(1)-(2), including the conditional "
       "$\\varphi=3$ simplification. The 2023 source is 5.1.5, Table 5.2 and "
       "Annex B.5; project adoption is required and no Danish National Annex is "
       "applied. A named curve without an edition is project-defined and receives "
       "no inferred Eurocode source. Sector never changes the entered coefficient "
       "or decides whether a cited simplification applies.")
    md("A fatigue bin uses the long-term fields for the sustained/basic state and "
       "the short-term fields for the cyclic increment. Sector solves both states "
       "with the Elastic solver; their stress difference is the range. Reuse one "
       "**Spectrum** label for all bins that belong to the same Miner sum. Spectrum "
       "labels that differ only by letter case are rejected.")
    call("tip", "Use stable case names from the project combination register. They "
         "appear unchanged in the result selector, summary and PDF.")

    h1("Reading the results")
    h2("Results overview")
    md("The overview shows one fully expanded governing row for each semantic check "
       "type, with its selected action set, direction or scope, result, criterion "
       "and status. An executed result takes precedence over an inactive state; "
       "equal states use the largest valid utilisation and exact ties keep the "
       "first retained case. Direction-specific rows of the same check type compete "
       "and the selected direction remains in the check label. **Not run**, **Not "
       "calculated**, **Not applicable** and **Not requested** are listed separately "
       "as scope and calculation state, not as conclusions. Headline counts describe "
       "the visible rows; they do not combine them into a project result.")
    md("In analysis figures, hover text reports the retained capacity or material "
       "response represented by the selected point. Section-result markers show "
       "stress and strain; coordinates and reinforcement area remain in section "
       "input previews and the complete result tables.")
    h2("Plastic results")
    md("Select a Plastic/capacity case at the top of the view. The "
       "$M_x$-$M_y$ envelope is drawn with the applied load marked; the "
       "**Neutral-axis state** selector steps through the swept angles and reports "
       "the strains, the compression resultant and lever arm, and the neutral-axis "
       "intercepts at each. The full per-angle table sits below.")
    h2("N-M Interaction results")
    md("Select the same named Plastic/capacity case to review axial force against "
       "the moment-resistance boundaries. This view uses the retained capacity "
       "sweep; it does not start a second solver or create a separate comparison "
       "decision.")
    h2("Elastic results")
    md("Select an Elastic case at the top of the view. The cracked-section "
       "stresses are reported per bar for the long-term, "
       "short-term and total states, with the peak concrete compression and the "
       "neutral-axis position. The cracking threshold and section properties are "
       "always reported. The per-action request remains authoritative. "
       "Independent long-term and short-term crack-width limits are applied "
       "only for a crack-width-enabled case and only to their matching durations. "
       "A 0 mm limit leaves the "
       "calculated width without comparison; a positive limit produces "
       "**WITHIN USER-SPECIFIED LIMIT** or **EXCEEDS USER-SPECIFIED LIMIT** and "
       "its source. This is not a code-compliance conclusion.")
    h2("Fatigue results")
    md("The **Fatigue Results** view first lists every spectrum and its governing "
       "utilisation. Select a spectrum to see the section utilisation map, then "
       "open **Reinforcement**, **Concrete**, **Spectrum bins** or **Basis**. "
       "Element and fibre selectors expose the governing and all non-governing "
       "results. Reinforcement rows state whether the simplified stress-range "
       "screen passes, requires the detailed check, or is not applicable. The "
       "tables retain stresses, ranges, S-N life, per-bin damage, "
       "yield/proof checks, concrete stress ratios, solver convergence, resistance "
       "sources and the bounded concrete-search result.")
    h2("Detailing results")
    md("The **Detailing** view gives a concise status for modelled-direction minimum "
       "reinforcement, shear/torsion link detailing and "
       "clear spacing. The section figure highlights the bars included in the "
       "selected case and dimensions the governing spacing pair. Tables retain "
       "provided and required values, utilisation or margin and element IDs.")
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
       "$V$-$T$ envelope diagram, and three explicit physical component results: "
       "concrete compression strut, shared closed stirrup and governing longitudinal "
       "reinforcement. The detailed blocks retain each contribution and the selected "
       "member strut angle.")
    h2("PDF report")
    md("Choose **Brief**, **Standard** or **Audit** in the Report workspace. Standard "
       "is the default. The profile changes presentation depth only: retained "
       "engineering values, rounding policy, statuses, warnings and sources are "
       "identical, and figures remain a separate choice.")
    table(
        ["Profile", "Purpose", "Declared omitted detail"],
        [
            [
                policy.label,
                policy.description,
                policy.omitted_detail,
            ]
            for policy in report_profiles.REPORT_PROFILES.values()
        ],
    )
    md("Brief publishes the complete effective geometry, assigned-material, "
       "reinforcement, tendon, action and active-setting inputs for every result it "
       "reports, followed by governing results and concise limitations. It omits "
       "non-governing result registers, substituted equations, derivations, candidate "
       "searches and the worked result chain. When figures are requested, Brief keeps "
       "only the selected governing Plastic and Elastic result plots when available. "
       "Standard adds one governing worked calculation for each active check family; "
       "Audit adds complete retained candidates, traces, branches, substitutions and "
       "provenance. **Audit does not mean approved, compliant or certified**.")

    # =====================================================================
    # PART C - THEORY & METHODOLOGY
    # =====================================================================
    part("Part C - Theory & methodology")

    h1("Method reference")
    md("Methods are grouped by engineering task. Each destination states the "
       "implemented scope, edition, assumptions, equations, selected branches and "
       "explicit non-goals.")
    table(
        ["Engineering task", "Method destination"],
        [
            [method.label, f"[Open {method.label}](#{method.anchor})"]
            for method in manual_ia.METHODS
        ],
    )

    h1("Conventions and sign convention")
    md("Coordinates are entered and reported in millimetres about the section "
       "origin (the numerical core stores metres). The axial force "
       "$N$ is positive in **tension** (compression negative, kN), so its sign agrees "
       "with the stresses and strains -- a crushing concrete strain reads negative; "
       "the moments $M_x$ and $M_y$ act "
       "about the $x$ and $y$ axes (kNm). At sweep angle $\\varphi_{NA}$, a point "
       "has the **depth coordinate** "
       "$s=x\\cos\\varphi_{NA}+y\\sin\\varphi_{NA}$. The neutral axis is "
       "$s=s_{na}$, where $s_{na}=s_{max}-c$; larger $s$ is the compression side. "
       "The neutral-axis line is oriented at $\\varphi_{NA}$ counter-clockwise "
       "from the positive $y$ axis.")
    fig(fig_sign_convention, "Axes and the positive senses of the axial force, the "
        "moments and the neutral-axis angle.",
        "Section axes show positive x to the right and y upward, with arrows for "
        "positive axial force and moments and the neutral-axis angle measured from "
        "positive y.")
    call("concept", "The reported axial force $N$, the stresses and the strains are "
         "all **tension-positive**. Internally the plastic solver works "
         "**compression-positive** (the compression zone has strain $> 0$); the sign "
         "is converted at the boundary, so you only enter and read tension-positive "
         "values. The concrete strain limits $\\varepsilon_{c2}$ / $\\varepsilon_{cu2}$ "
         "are still entered as positive compression magnitudes (as in EC2).")

    h1("Material laws")
    h2("Concrete (parabola-rectangle)")
    md(("The design concrete law (Curve 2) rises as a power curve to the peak and "
       "then holds it to the ultimate strain:\n\n"
       "$$\\sigma_c = f_{cd}\\left[1-\\left(1-\\tfrac{\\varepsilon_c}"
       "{\\varepsilon_{c2}}\\right)^{n}\\right] \\quad (0\\le\\varepsilon_c\\le"
       "\\varepsilon_{c2}), \\qquad \\sigma_c = f_{cd}\\quad(\\varepsilon_{c2}\\le"
       "\\varepsilon_c\\le\\varepsilon_{cu2}),$$\n\n"
       "with $f_{cd} = \\alpha_{cc}\\,f_{ck}/\\gamma_c$ for the 2005 family and "
       "$f_{cd}=\\eta_{cc}k_{tc}f_{ck}/\\gamma_c$ for DS/EN 1992-1-1:2023, and zero "
       "stress beyond "
       "$\\varepsilon_{cu2}$ (crushed).\n\n"
       "For $f_{ck}\\le 50$ MPa the strain limits are $\\varepsilon_{c2}=2.0$ per "
       "mille, $\\varepsilon_{cu2}=3.5$ per mille and $n=2$.\n\n"
       "Above C50 they follow Table 3.1: "
       "$\\varepsilon_{c2}=(2.0+0.085(f_{ck}-50)^{0.53})/1000$, "
       "$\\varepsilon_{cu2}=(2.6+35((90-f_{ck})/100)^4)/1000$ and "
       "$n=1.4+23.4((90-f_{ck})/100)^4$. These strength-dependent strains apply to "
       "the 2005 and DK NA editions.\n\n"
       "The DS/EN 1992-1-1:2023 edition instead keeps them **constant** "
       "($\\varepsilon_{c2}=2.0$, $\\varepsilon_{cu2}=3.5$ per mille, $n=2$) for "
       "every grade. Its $\\eta_{cc}=\\min[(40/f_{ck})^{1/3},1.0]$ and the "
       "general-case $k_{tc}=0.85$ are applied separately; $k_{tc}=1.00$ is an "
       "explicit applicability choice under 5.1.6(1).").replace(
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
    h2("Mild steel")
    md(("The mild-steel editor uses one general Curve 3 law. It is linear to a "
       "first yield, can pass through a second yield defined by the plastic offsets, "
       "and then reaches the entered ultimate point. Setting $k=1$ and both offsets "
       "to zero collapses the two yields into one; setting the factored ultimate "
       "stress equal to the factored yield gives a flat post-yield branch. On the "
       "initial elastic branch:\n\n"
       "$$\\sigma_s = E_{s,d}\\,\\varepsilon_s\\ \\ (|\\varepsilon_s|\\le"
       "\\varepsilon_{yd}), \\qquad f_{yd}=f_{yk}/\\gamma_s, \\qquad "
       "\\varepsilon_{yd}=f_{yd}/E_{s,d}.$$\n\n"
       "For the general law, $E_{s,d}=E_s/\\gamma_E$. The edition-named Curve 3 "
       "design presets set $\\gamma_E=1$, so the B550 DK preset used by both "
       "examples yields at $\\varepsilon_{yd}=f_{yd}/E_s="
       "(550/1.20)/200000\\approx2.29$ per mille.\n\n"
       "The generic **Curve 2 (elastic-perfectly-plastic)** selection is a "
       "user-defined/project-defined and uncited preset. It also uses the general "
       "Curve 3 kernel with $k=1$, zero offsets and a flat branch; its stored "
       "starting value is $\\gamma_E=1$. Changing any field changes the law but "
       "does not change or promote the selected preset identity.").replace(
           "per mille", _PERMILLE
       ))
    fig(fig_beam_steel_law, "The B550 mild-steel law of the beam example.",
        "Positive and negative B550 stress branches are linear to the yield points "
        "and then follow matching post-yield branches toward the strain limits.")
    h2("Prestressing steel")
    md(("A tendon is evaluated at its **total** strain -- the locked-in initial "
       "strain $\\varepsilon_{p,IS}$ (from prestressing, after losses, given as an "
       "input) plus its tension-positive section strain. For tendon $j$ at depth "
       "$s_{p,j}$ this is:\n\n"
       "$$\\varepsilon_{p,j}=\\varepsilon_{p,IS,j}"
       "-\\kappa(s_{p,j}-s_{na}), "
       "\\qquad \\sigma_p = f(\\varepsilon_p),\\quad f_{pd}=f_{p0.1k}/\\gamma_s.$$\n\n"
       "**Worked (circular):** $\\varepsilon_{p,IS}=5.0$ per mille and "
       "$f_{pd}=1600/1.15=1391$ MPa.").replace("per mille", _PERMILLE))
    fig(fig_circular_prestress_law, "The tendon law of the circular example.",
        "The tendon curve starts with an elastic slope, bends toward the proof-strength "
        "region and terminates at the defined ultimate strain.")
    call("standard", "The beam and circular examples select the edition-named "
         "DS/EN 1992-1-1:2005 + DK NA:2024 Curve 3 design preset for mild steel. "
         "Edition-named concrete, mild-steel and tendon presets retain their own "
         "sources; generic named curves remain project-defined / uncited.")

    h1("Plastic capacity analysis")
    h2("The strain plane at capacity")
    md("Plane sections remain plane, so the strain is linear across the depth: "
       "$\\varepsilon_{sec}(s) = \\kappa\\,(s - s_{na})$, where $\\kappa$ is the "
       "curvature and $s_{na}$ the neutral-axis depth. At capacity the extreme "
       "compression fibre reaches the concrete crushing strain "
       "$\\varepsilon_{cu2}$; the compression depth is $c = s_{max}-s_{na}$.")
    fig(fig_strain_plane, "The capacity strain plane (reported tension-positive "
        "convention): one straight line -- zero at the neutral axis, compression "
        "(negative) above it and tension (positive) below, the top fibre at the "
        "crushing strain. The internal solver formula above is compression-positive; "
        "the reported strains negate it.",
        "A straight strain line crosses zero at the neutral axis; negative compression "
        "lies above it, positive tension below it, and the top fibre reaches ultimate "
        "concrete compression.")
    h2("The governing curvature")
    md("The curvature is scaled until the **first** element reaches its assigned "
       "material limit, so "
       "none is driven past its limit:\n\n"
       "$$\\kappa = \\min\\!\\left(\\frac{\\varepsilon_{cu2}}{c},\\; "
       "\\min_i\\frac{\\varepsilon_{u,i}}{s_{na}-s_{b,i}}\\;"
       "\\text{tension-side bars},\\; "
       "\\min_i\\frac{\\varepsilon_{u,i}}{s_{b,i}-s_{na}}\\;"
       "\\text{compression-side active bars},\\; "
       "\\min_j\\frac{\\varepsilon_{pu,j}-\\varepsilon_{p,IS,j}}"
       "{s_{na}-s_{p,j}}\\;\\text{tension-side tendons}\\right).$$\n\n"
       "The terms are concrete crushing, tensile mild-bar rupture, compressive "
       "mild-bar rupture (only for a bar active in compression), and tensile tendon "
       "rupture measured from that tendon's locked-in strain. A candidate is used "
       "only when its denominator and remaining tendon strain margin are positive. "
       "Every bar and tendon is evaluated with its own assigned law; the smallest "
       "candidate governs.")
    call("concept", "$s_{p,j}$ is tendon $j$'s projection on the local strain "
         "gradient. If all tendons share the same limit and initial strain, "
         "$s_{p,min}=\\min_j s_{p,j}$ is a useful shorthand for the most tensile "
         "location. The solver still inventories every $j$; no undefined global "
         "cable coordinate replaces the element-specific candidates.")
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
    md(("Rotating the neutral-axis angle $\\varphi_{NA}$ and solving at each gives "
       "one point on "
       "the $M_x$-$M_y$ envelope; sweeping $0$ to $360$ degrees closes the biaxial "
       "diagram. **Worked (beam, $N=0$, $\\varphi_{NA}=90^\\circ$):** the concrete "
       "reaches its "
       "crushing strain ($3.5$ per mille) while the most tensile bars are well past "
       "yield ($19.5$ per mille, against the $2.29$ per mille yield), so this "
       "tension-controlled point gives $M_{x} = 346$ kNm. The applied $M_x=300$ "
       "kNm is then a utilisation of $300/346 = 0.87$.").replace(
           "per mille", _PERMILLE
       ))
    fig(fig_beam_envelope, "The beam envelope with its applied load; each vertex is "
        "one solved neutral-axis angle.",
        "A closed biaxial moment-resistance curve is plotted with the design moment "
        "point, showing its position inside the boundary and the discrete angular "
        "sweep points.")

    h1("Reinforcement detailing")
    md("Each detailing checkbox identifies the clauses used by the selected "
       "Detailing edition. The help adds no separate calculation state: selecting "
       "an edition continues to choose the edition-specific rules described below, "
       "while the help itself does not change checkbox state or entered geometry. "
       "The 2023 edition is a published reference that requires project adoption, "
       "and no Danish National Annex is applied.")
    h2("EN 1992-1-1:2005 and DK NA:2024")
    md("Sector transfers the moments to the gross-concrete centroid and derives "
       "the uncracked gross-concrete strain plane for the complete $M_x$-$M_y$ "
       "action. Its tensile half-plane is checked using:\n\n"
       "$$A_{s,min}=\\max\\!\\left(0.26\\frac{f_{ctm}}{f_{yk}},\\,0.0013\\right)"
       "b_t d, \\qquad A_{s,prov}\\ge A_{s,min}. $$\n\n"
       "$b_t$ is the exact mean width of that resultant tension half, and $d$ "
       "is measured normal to its neutral line from the opposite extreme concrete "
       "fibre to the centroid of the bars in tension. If several assigned materials occur, "
       "the lowest $f_{yk}$ is used. Reference: 9.2.1.1(1), Formula (9.1N).")
    call("limit", "The DK NA:2024 side-face reinforcement requirement for high "
         "beam webs is separate from Formula (9.1N) and is not included.")
    h2("DS/EN 1992-1-1:2023")
    md("For bending with axial force, Sector derives the uncracked cracking action "
       "in the applied moment direction and checks:\n\n"
       "$$M_{R,nom}(N_{Ed})\\ge M_{cr}(N_{Ed}).$$\n\n"
       "The nominal resistance uses the entered design concrete law and limits "
       "each mild bar to its characteristic $f_{yk}$; a biaxial case uses a "
       "15-degree nominal-resistance envelope. Pure tension uses:\n\n"
       "$$\\sum A_{s,i}f_{yk,i}\\ge A_c f_{ctm}.$$\n\n"
       "Reference: 12.2(2), Formulae (12.1) and (12.2). The bending check is "
       "reported not applicable when compressive $N_{Ed}$ is not below "
       "$0.5A_cf_{cd}$.")
    h2("Clear spacing")
    md("For each included pair of longitudinal elements, Sector computes the "
       "edge-to-edge distance from the entered coordinates and circular detailing "
       "diameters and checks:\n\n"
       "$$c_{clear}\\ge\\max(\\phi_{max},\\,D_{upper}+5\\,\\text{mm},\\,20\\,\\text{mm}).$$\n\n"
       "This is 8.2(2) for the 2005 family and 11.2(2) for 2023. The smallest "
       "margin governs, and a geometric shortfall is reported as **Fail**. Lap "
       "length, bond, bundle equivalence and longitudinal arrangement remain "
       "separate detailing checks.")
    h2("Shear and torsion reinforcement")
    md("For vertical shear links, Sector checks the entered legs in each active "
       "direction using:\n\n"
       "$$\\rho_w=\\frac{A_{sw}}{s\\,b_w}\\ge\\rho_{w,min},\\qquad"
       "\\rho_{w,min}=c\\frac{\\sqrt{f_{ck}}}{f_{ywk}}.$$\n\n"
       "$c=0.063$ for DS/EN 1992-1-1:2005 DK NA:2024 and $c=0.08$ "
       "for EN 1992-1-1:2005 and DS/EN 1992-1-1:2023. In the 2023 method, "
       "the optional class-B or class-C reduction is applied only when selected "
       "explicitly. References: 2005 9.2.2(5), Formulae (9.4)-(9.5); "
       "2023 12.2(4), Formula (12.4).")
    md("The longitudinal and transverse shear-link spacings are checked against:\n\n"
       "$$s_l\\le0.75d,\\qquad s_t\\le\\min(0.75d,600\\,\\text{mm}).$$\n\n"
       "If the maximum transverse distance between legs is entered as zero, "
       "Sector uses the gross web breadth $b_w$ as an upper-bound screen. A bound "
       "within the limit proves **Pass**; a bound above it is **Not assessed**, not "
       "**Fail**, until the actual maximum spacing is entered. With fewer than two "
       "effective legs, the user must enter the distance. The distance is measured "
       "in the section plane: along $y$ between $V_x$-parallel legs and along $x$ "
       "between $V_y$-parallel legs. It is separate from the longitudinal stirrup "
       "spacing and does not require reducing the closed-stirrup height.")
    md("For a closed torsion link, one leg is checked in each effective tube wall:\n\n"
       "$$\\rho_{w,T}=\\frac{A_{leg}}{s\\,t_{ef}}\\ge\\rho_{w,min}.$$\n\n"
       "The maximum longitudinal spacing is the lesser of $u_k/8$ and the "
       "rotation-invariant minimum physical section dimension. Each sub-tube is "
       "checked separately; an active shear direction has its own $0.75d$ check.")
    call("limit", "Sector models all entered shear reinforcement as vertical "
         "stirrups and all entered torsion reinforcement as closed stirrups. "
         "Anchorage is assumed; reduce $f_{ywk}$ when full anchorage is not "
         "available. Cover, bends, mandrel diameter, anchorage length, lap length, "
         "bundle equivalence, congestion and construction access are not verified.")
    call("standard", "DS/EN 1992-1-1:2023 8.2.1(2) requires minimum shear "
         "reinforcement for statically determinate linear members with "
         "$d>500$ mm. The section model does not declare the global structural "
         "system, so that condition is reported as not assessed when relevant.")
    call("standard", "BN1-59-5 and the Danish Road Directorate bridge basis add "
         "project- and existing-structure applicability requirements, including "
         "special treatment of inadequately anchored historic links. Sector does "
         "not apply hidden owner-specific coefficients.")

    h1("Cracked-section elastic analysis")
    md("The Elastic solver takes the section as already cracked: concrete "
       "carries compression only (zero stress where $\\varepsilon\\ge 0$) and the "
       "steel is linear in both directions. The analysis works with a reference "
       "concrete modulus and an element-specific modular ratio $n_i=E_i/E_c$: each "
       "bar or tendon contributes a "
       "transformed area $n\\,A$. (The solver can also subtract the concrete a "
       "compression-zone bar displaces, using $(n-1)\\,A$ there; Sector leaves that "
       "refinement off, so the reported stresses and section properties use "
       "$n\\,A$ throughout.) The Elastic solver stores an $E_c=1$ reference-stress "
       "plane $(\\sigma_0,g_x,g_y)$, not a physical strain/curvature plane. The "
       "physical concrete strain is $\\varepsilon_c=\\sigma_{ref}/E_c$. Report "
       "labels identify the physical quantity represented by each result field. "
       "Newton iteration solves the "
       "reference-stress plane so the transformed-section resultants equal "
       "$(N,M_x,M_y)$, updating the compression zone until it settles.")
    md("Creep enters through the modular ratio: the long-term state uses "
       "$n_l = E_s/E_{c,eff}$ with $E_{c,eff}=E_c/(1+\\varphi)$, and the "
       "short-term state uses $n_s = E_s/E_c$. The reported total combines the two, "
       "so both load duration and creep are captured. Prestressing tendons carry "
       "the corresponding material's modular ratio $n_p = E_p/E_c$ (creep-reduced "
       "the same way). None of these ratios is entered -- each is derived from the "
       "assigned material modulus, $E_c$ and the creep coefficient $\\varphi$.")
    fig(fig_beam_cracked, "The beam's cracked (Stage II) state under the service "
        "moment: the compression zone (shaded) above the neutral axis.",
        "A rectangular section has a shaded concrete compression zone above a "
        "horizontal neutral axis, with reinforcement points retained in the Stage II "
        "section.")

    h1("Serviceability: cracking and crack width")
    h2("The cracking threshold")
    md("The uncracked (Stage I) peak concrete tensile stress $\\sigma_{ct,I}$ "
       "scales with the load, so the load factor to first cracking is "
       "$\\lambda_{cr}=f_{ctm}/\\sigma_{ct,I}$; $\\lambda_{cr}\\ge 1$ means the "
       "section has not cracked. **Worked (beam, $M_x=150$ kNm):** "
       "$\\lambda_{cr}=0.49<1$, so the section is cracked and the Stage II stresses "
       "govern ($\\sigma_s=204$ MPa at the bottom bars).")
    md("With tendons, locked-in prestress is permanent and is not scaled. If any "
       "prestress-only fibre is above $f_{ctm}$, Sector assigns "
       "$\\lambda_{cr}=0$ directly and the section is classified cracked. "
       "Otherwise, at each fibre with a tensile external increment Sector solves "
       "$\\sigma_{pre,i}+\\lambda_{cr}\\sigma_{ext,i}=f_{ctm}$, scaling only the "
       "external $N/M$, and takes the first cracking factor. "
       "$\\lambda_{cr}<1$ is cracked and $\\lambda_{cr}\\ge 1$ is uncracked.")
    call("concept", "Cracking is **irreversible** and is triggered by the largest "
         "load the section ever sees, so Sector decides cracked/uncracked from the "
         "**governing** of the sustained (long-term) and the peak (total = long + "
         "short) action -- not the sustained part alone. A section that only cracks "
         "under a large short-term load is therefore still treated as cracked "
         "(with both user-defined action parts reported); one only cracked by the "
         "sustained load stays cracked even if a counteracting short-term action "
         "relieves the total. The peak check uses the same combined-creep "
         "superposition (long at $n_l$ + short at $n_s$) as the reported stresses.")
    call("standard", "The selected cracking method evaluates the user-entered "
         "sustained and peak actions. Sector reports the resulting crack widths "
         "without assigning either action a criterion role.")
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
    md(("**Worked (beam, $M_x=150$ kNm):** $\\sigma_s=204$ MPa, "
        "$\\rho_{p,eff}=0.0393$, $\\varepsilon_{sm}-\\varepsilon_{cm}=0.797$ per "
        "mille, $s_{r,max}=236$ mm, hence $w_k=0.188$ mm.").replace(
            "per mille", _PERMILLE
        ))
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
    h2("DK NA heightened crack-control minimum")
    md("This is a separate, user-selected DS/EN 1992-1-1 DK NA:2024 "
       "Formula 7.100 NA calculation, not another ordinary crack-width result. "
       "The required reinforcement ratio is\n\n"
       "$$\\rho_{s,min}=m_s\\sqrt{\\frac{\\phi f_{ct,eff}}"
       "{4E_{sk}kw_k}}$$\n\n"
       "where $k=1$ for the fine crack system and $k=2$ for the coarse system; "
       "$m_s=1$ for ribbed reinforcement and $m_s=\\sqrt{2}$ for smooth "
       "reinforcement. Sector uses the separate Formula 7.100 NA permitted-width "
       "input and calculates the fine and coarse systems together, each with its own user-supplied "
       "$A_{c,eff}$. Bar diameter uses the ordinary crack override when positive, "
       "otherwise the largest contributing mild bar; $E_{sk}$ is the conservative "
       "minimum among contributing mild materials and $A_{s,prov}$ is their retained "
       "area sum. The report preserves the reference case, ordinary branch, element "
       "and material provenance and publishes both comparisons plus the governing "
       "system. Missing or indeterminate retained evidence blocks the calculation. "
       "Applicability, restraint, watertightness and the permitted "
       "$w_k$ remain user declarations. The option is unavailable for the 2023 "
       "basis.")
    h2("DS/EN 1992-1-1:2023 refined model")
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
    md("The three code options give four method/system results on the same beam and "
       "service moment ($M_x=150$ kNm), because DK/NA evaluates distinct fine and "
       "coarse reinforcement systems:")
    table(["Crack-width edition", "$s_{r,max}$ (mm)", "$h_{c,ef}$ (m)", "$w_k$ (mm)"],
          [["EN 1992-1-1:2005", "236", "0.125", "0.188"],
           ["DS/EN + DK NA (fine)", "206", "0.125", "0.164"],
           ["DS/EN + DK NA (coarse)", "184", "0.100", "0.077"],
           ["DS/EN 1992-1-1:2023", "134", "0.175", "0.186"]])
    call("standard", "The *Crack-width code* offers three options -- EN 1992-1-1:"
         "2005, DS/EN 1992-1-1 + DK NA and DS/EN 1992-1-1:2023. The DK NA option "
         "reports the fine and the coarse system together (all four columns above), "
         "each for the long-term and short-term load. Ordinary methods show one "
         "globally governing worked crack width in Standard and Audit; DK/NA shows "
         "one global fine-system and one global coarse-system worked example there. "
         "Brief retains the complete effective inputs and the semantic governing "
         "crack-width rows, but no worked example or non-governing case register. "
         "If user criteria are present, Standard and Audit show one comparison for "
         "the largest calculated ordinary width -- never the largest ratio -- plus "
         "at most one section-level Formula 7.100 NA worked example when that "
         "separate DK option is enabled.")

    h1("Grouped fatigue")
    h2("Elastic stress ranges")
    md("Each spectrum bin contains a sustained/basic action $S_l$, a cyclic "
       "increment $S_s$ and a cycle count $n_i$. Sector uses the cracked Elastic "
       "solver twice and applies the action factor to the increment:\n\n"
       "$$\\Delta\\sigma_{Ed,i}=\\left|\\sigma(S_l+\\gamma_{Ff}S_s)"
       "-\\sigma(S_l)\\right|.$$\n\n"
       "Long-term actions use $n_l$ and the increment uses $n_s$. Prestress and "
       "element-specific elastic moduli follow the assigned material definitions. "
       "The unfactored total state is retained beside the design state for QA.")
    call("concept", "$\\gamma_{Ff}$ is applied once, at action level. The resulting "
         "design stress range enters the S-N or concrete-life check; it is not "
         "applied again to the resistance curve.")

    h2("Simplified reinforcement stress-range screen")
    md("Sector first evaluates the supported Eurocode shortcut for each assigned "
       "named reinforcement or prestressing detail. The shortcut is used only "
       "when every retained spectrum bin converged and has a tensile endpoint. "
       "A stress range exactly equal to the stated limit passes. A lower range "
       "passes; a higher range does not fail the member, but makes the detailed "
       "S-N/Miner check necessary. Custom, imported or otherwise unsupported "
       "details also continue to the detailed check.")
    table(
        ["Fatigue basis and named detail", "Simplified limit"],
        [
            ["2005 family - unwelded straight or bent reinforcing bar",
             "70 MPa characteristic range"],
            ["2005 family - welded reinforcing bar or fabric",
             "35 MPa characteristic range"],
            ["2023 - unwelded straight or bent bar, phi <= 12 mm",
             "90 MPa design range"],
            ["2023 - unwelded straight or bent bar, phi > 12 mm",
             "73 MPa design range"],
            ["2023 - welded bar or fabric, phi <= 12 / > 12 mm",
             "40 / 30 MPa design range"],
            ["2023 - reinforcing-steel coupler", "19 MPa design range"],
            ["2023 - pretensioning steel or single strand in plastic duct",
             "95 MPa design range"],
            ["2023 - tendon in plastic duct", "80 MPa design range"],
            ["2023 - curved tendon in steel duct", "55 MPa design range"],
        ],
    )
    md("For a 2023 bent-bar preset, the selected mandrel-to-diameter reduction "
       "also reduces the tabulated straight-bar limit. The 2023 shortcut is "
       "limited to a retained total of $10^8$ cycles. The 2005-family screen "
       "uses the characteristic fatigue range; the 2023 screen uses the design "
       "range including the action-level $\\gamma_{Ff}$ factor. Sector always "
       "retains the detailed S-N/Miner result for transparency, and the "
       "yield/proof-stress check remains independent of the shortcut.")
    md("References: DS/EN 1992-1-1:2004 + A1:2014 + AC:2010, "
       "6.8.6(1)-(2), with DS/EN 1992-1-1 DK NA:2024; and "
       "DS/EN 1992-1-1:2023, 10.4(1) for the selectable published-2023 route.")
    call(
        "concept",
        "A passing simplified screen means that a more detailed stress-range "
        "assessment is not required for that element. It does not suppress the "
        "reported detailed calculation or the independent strength checks.",
    )

    h2("Reinforcement S-N and Miner check")
    md("For each bar or tendon, the selected fatigue detail supplies $N^*$, slopes "
       "$k_1$ and $k_2$, and the characteristic reference range "
       "$\\Delta\\sigma_{Rsk}$. The design knee is\n\n"
       "$$\\Delta\\sigma_{Rd}=\\frac{\\Delta\\sigma_{Rsk}}{\\gamma_s},$$\n\n"
       "and the life of bin $i$ is\n\n"
       "$$N_{R,i}=N^*\\left(\\frac{\\Delta\\sigma_{Rd}}"
       "{\\Delta\\sigma_{Ed,i}}\\right)^{k},$$\n\n"
       "with $k=k_1$ above the knee and $k=k_2$ below it. Zero range gives infinite "
       "life. Diameter and bent-bar adjustments follow the selected detail preset.")
    md("Damage is accumulated within one named spectrum:\n\n"
       "$$D=\\sum_i\\frac{n_i}{N_{R,i}}\\leq1.0.$$\n\n"
       "The long-term and design-total stresses are also checked against the "
       "element's tension or compression yield/proof strength divided by "
       "$\\gamma_s$. If the simplified screen passes, its stress-range utilisation "
       "replaces Miner damage for the governing range criterion; otherwise Miner "
       "damage applies. Yield/proof utilisation remains independent in both cases.")
    fig(fig_fatigue_sn, "Two-slope characteristic and design S-N curves. Each "
        "labelled marker is one applied spectrum bin; logarithmic axes retain the "
        "wide cycle and stress ranges without visual distortion.",
        "A log-log stress-range versus cycles plot shows characteristic and design "
        "S-N curves with a knee and labelled spectrum-bin points on the relevant "
        "branches.")
    fig(fig_fatigue_damage, "Per-bin and cumulative Miner damage for the same "
        "element. The cumulative line and $D=1.00$ limit make the governing "
        "contribution and remaining margin visible. The y-axis changes to a "
        "logarithmic scale for low-damage spectra so small contributions remain "
        "readable.",
        "Damage bars identify each spectrum bin, a cumulative Miner-damage line rises "
        "across the bins, and a horizontal D equals 1 limit shows the remaining "
        "margin.")

    h2("Mixed mild reinforcement and bonded tendons")
    md("When both occur in one section, Sector applies the edition-specific bond "
       "model. The 2005 method applies the 6.8.2(2) bond correction $\\eta$ to the "
       "mild-reinforcement range and leaves the tendon range unadjusted. The 2023 "
       "method resolves the section using the equivalent tendon area from 10.3(2). "
       "The tendon detail therefore requires $\\xi$ and an equivalent diameter. "
       "The applied method and adjustment are reported for every bin.")

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
    md("At one fixed concrete fibre, let $\\sigma_{max}$ and $\\sigma_{min}$ be the "
       "larger and smaller design compression magnitudes for a bin, "
       "$E_{max}=\\sigma_{max}/f_{cd,fat}$ and "
       "$R=\\sigma_{min}/\\sigma_{max}$. The implemented life relation is\n\n"
       "$$\\log_{10}N_R=C\\frac{1-E_{max}}{\\sqrt{1-R}}.$$\n\n"
       "Miner damage is summed at that same fibre; maxima from different locations "
       "are never combined into a fictitious history. Direct stress utilisation "
       "$E_{max}\\leq1.0$ is checked in parallel.")
    md("Alternatively, the damage-equivalent method checks each user-supplied "
       "equivalent action pair using\n\n"
       "$$E_{max}+0.43\\sqrt{1-\\frac{E_{min}}{E_{max}}}\\leq1.$$\n\n"
       "This is Formula (6.72) for the 2005 family and Formula (E.2) for 2023. "
       "The pair represents $10^6$ cycles; Sector does not derive it from the "
       "entered spectrum. When several equivalent rows are supplied, the largest "
       "criterion governs.")
    md("Sector checks the section vertices and runs an adaptive branch-and-bound "
       "search over the concrete area. The result includes the largest evaluated "
       "criterion, a conservative upper bound, the absolute and relative gap, sample "
       "and box counts, and convergence. The upper bound governs "
       "the calculation conclusion, so an unresolved potentially critical region "
       "cannot pass.")

    h2("Edition and scope summary")
    table(["Edition", "Reinforcement", "Concrete", "Mixed bond"],
          [["DS/EN 1992-1-1:2005",
            "6.8.6 shortcut; 6.8.4 and Tables 6.3N/6.4N detailed check",
            "6.72 equivalent or corrected DS/EN 1992-2:2005/AC:2008 6.106 Miner",
            "6.8.2(2) eta correction"],
           ["DS/EN 1992-1-1:2005 + DK NA:2024",
            "6.8.6 shortcut unchanged; detailed method with Danish project factors",
            "Same selectable methods; explicit Danish project factors",
            "6.8.2(2) eta correction"],
           ["DS/EN 1992-1-1:2023",
            "10.4 shortcut; Annex E.5 and Tables E.1/E.2 detailed check",
            "E.2 equivalent or E.7-E.8 Miner",
            "10.3(2) equivalent tendon area"]])
    call("limit", "Each spectrum forms its own Miner sum and result. Sector does "
         "not combine spectra. The fatigue implementation covers normal force and "
         "biaxial bending through the Elastic solver; shear- and torsion-induced "
         "fatigue are outside the present scope.")

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
    md("Sector derives the geometry separately for each active shear direction: "
       "the effective depth $d$ is the distance from the extreme "
       "compression fibre (opposite the tension face) to the centroid of the "
       "tension bars; $b_w$, when not entered, is the smallest solid width sampled "
       "over the middle 80% of the depth (the web of a rectangular / T / box "
       "section -- a curved outline should have $b_w$ entered by hand). $\\sigma_{cp}$ "
       "uses the Plastic action-set force $N$; since Sector's $N$ is "
       "tension-positive it is negated to the code's compression-positive "
       "convention, exactly as the axial-force flip elsewhere. Automatic face "
       "selection follows the associated moment; at zero moment both faces are "
       "evaluated.")
    md("For DS/EN 1992-1-1:2023, the action-dependent factor is\n\n"
       "$$a_{cs}=\\max\\!\\left(\\left|M_{Ed}/V_{Ed}\\right|,d\\right),\\qquad "
       "k_{vp}=\\max\\!\\left(1+\\frac{N_{Ed}}{|V_{Ed}|}\\frac{d}{3a_{cs}},0.1\\right),$$\n\n"
       "and $d$ in Formula (8.27) is replaced by $k_{vp}d$. The 2023 convention "
       "takes $N_{Ed}$ positive in tension, so axial tension raises $k_{vp}$ and "
       "reduces the basic shear-stress resistance; compression has the opposite "
       "effect. The minimum stress from Formula (8.20) and the lever arm "
       "$z=0.9d$ retain the nominal $d$.")
    call("limit", "$A_{sl}$ is the longitudinal tension reinforcement, **assumed "
          "fully anchored** ($\\geq l_{bd} + d$) beyond the section. This anchorage "
          "cannot be checked at section level. If it is not fully anchored, enter "
          "an appropriately reduced $f_{yk}$ / $f_{ywk}$; bonded tendons are not "
          "counted toward $\\rho_l$ automatically.")
    md("**Worked** (300 x 600 mm rectangle, C35, DK NA:2024, "
       "$A_{sl} = 1473$ mm$^2$, $d = 550$ mm, $b_w = 300$ mm, $N = 0$): "
       "$k = 1.603$, $\\rho_l = 0.00893$, $C_{Rd,c} = 0.124$, the basic term "
       "$0.627$ MPa exceeds $v_{min} = 0.535$ MPa, so "
       "$V_{Rd,c} = 0.627 \\cdot 300 \\cdot 550 = 103.4$ kN.")

    h2("Members with shear reinforcement (links)")
    md("A member with designed vertical links is a truss: the links are the "
       "tension ties and the concrete web the inclined compression struts at an "
       "angle $\\theta$ to the axis. For the 2005 family, the resistance is\n\n"
       "$$V_{Rd,s} = \\frac{A_{sw}}{s}\\,z\\,f_{ywd}\\,\\cot\\theta \\quad(6.8), "
       "\\qquad V_{Rd,max} = \\frac{\\alpha_{cw}\\,b_w\\,z\\,\\nu_1\\,f_{cd}}"
       "{\\cot\\theta + \\tan\\theta} \\quad(6.9),$$\n\n"
       "and $V_{Rd} = \\min(V_{Rd,s}, V_{Rd,max})$. Here $z$ is the internal lever "
       "arm, $\\nu_1$ the strut effectiveness factor, and $\\alpha_{cw}$ the "
       "compression-chord factor (1 for a non-prestressed section, rising with an "
       "axial compression per 6.11N). The shear also adds a longitudinal tension "
       "$\\Delta F_{td} = 0.5\\,V_{Ed}\\,\\cot\\theta$ (6.18) that the bottom steel "
       "must carry on top of the bending force.")
    md("For DS/EN 1992-1-1:2023,\n\n"
       "$$\\tau_{Rd,sy}=\\rho_w f_{ywd}\\cot\\theta \\quad(8.42),\\qquad "
       "\\sigma_{cd}=\\tau_{Ed}(\\cot\\theta+\\tan\\theta)"
       "\\leq\\nu f_{cd}\\quad(8.44),$$\n\n"
       "where $\\rho_w=A_{sw}/(b_ws)$ and $\\nu=0.5$. Sector reports both stresses "
       "and the equivalent $V_{Rd,s}$ / $V_{Rd,max}$ resistances. The longitudinal "
       "addition is $N_{Vd}=|V_{Ed}|\\cot\\theta$ (8.50), applied without the "
       "support/load-specific relief in (8.53).")
    call("concept", "For reinforced-shear checks, Sector calculates the internal "
         "lever arm $z$ at the exact face-aligned Plastic state and action-set axial "
         "force. The compression and tension resultants each include the sign-split "
         "contributions from concrete, mild steel and tendons. Their separation is "
         "$z$, with Cartesian components $z_x$ and $z_y$; x-axis bending uses "
         "$|z_y|$ and y-axis bending uses $|z_x|$. If the required Plastic state is "
         "unavailable, the links resistance is not assessed.")
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
    call("standard", "For 2023 class B/C links, the directly verifiable range is "
         "$1\\leq\\cot\\theta\\leq2.5$; axial tension reduces the upper limit to "
         "$\\max(2.5-0.1N_{Ed}/|V_{Ed}|,1)$ and class A reduces it by 20%. "
         "The favourable compression extension to 3.0 is not credited because "
         "Sector does not establish the required compression-chord depth.")
    md("**Worked** (same section, C35, DK NA:2024, 2-leg $\\phi$10 links at "
       "$s = 150$ mm, $f_{ywk} = 500$; calculated $z = 509.151$ mm): "
       "$f_{ywd} = 417$ MPa, $\\nu_1 = 0.525$, $A_{sw}/s = 1.047$ mm$^2$/mm. The "
       "crossing $\\cot\\theta = 2.78$ exceeds the limit, so $\\cot\\theta = 2.5$ "
       "and the links govern: $V_{Rd,s} = 555.4$ kN $< V_{Rd,max} = 667.5$ kN, "
       "giving $V_{Rd} = 555.4$ kN.")

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
       "The transverse $T_{Rd,s}$ expression follows the torsional wall shear "
       "flow (6.27) and transverse equilibrium (6.8). "
       "With $T_{Rd} = \\min(T_{Rd,s}, T_{Rd,max})$, the torsion also needs "
       "longitudinal steel $\\sum A_{sl} = T_{Ed}\\,u_k\\,\\cot\\theta/(2A_k\\,"
       "f_{yd})$ (6.28), **in addition** to the bending reinforcement on the "
       "tension side, and the cracking torque is $T_{Rd,c} = 2A_k\\,t_{ef}\\,"
       "f_{ctd}$ ($\\tau = f_{ctd}$), where "
       "$f_{ctd}=f_{ctk,0.05}/\\gamma_{ct}=0.7f_{ctm}/\\gamma_{ct}$. "
       "The selected method supplies the editable starting value "
       "$\\gamma_{ct}=1.50$ (EN) or 1.70 (DK/NA).")
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
         "single-cell (box) sections are idealised automatically; a multi-cell section "
         "(two or more voids) and a re-entrant compound outline (T, L, I or flanged) "
         "require explicit sub-division (6.3.1(3)); the single-tube resistance and "
         "verdict are withheld until component rectangles are defined. A positive "
         "global $t_{ef}$ override is not transferred to those component tubes and "
         "therefore blocks a subdivided calculation; 0 selects automatic $A/u$ for "
         "each sub-tube. A curved "
         "outline should have $t_{ef}$ entered by hand. Bounds outside the selected "
         "method's default $\\cot\\theta$ range remain actual calculation inputs; "
         "Sector reports the resulting demand/resistance verdict with a warning.")
    md("**Worked** (300 x 600 mm rectangle, C35, DK NA:2024, closed $\\phi$10 "
       "stirrup at $s = 150$ mm): $A = 0.18$ m$^2$, $u = 1.8$ m, $t_{ef} = 100$ mm, "
       "$A_k = 0.1$ m$^2$, $u_k = 1.4$ m, $\\nu_t = 0.368$. At the optimum "
       "$\\cot\\theta = 1.75$ the stirrups and struts meet at "
       "$T_{Rd} \\approx 76.4$ kN$\\cdot$m, with "
       "$\\gamma_{ct}=1.70$ and $T_{Rd,c} = 26.435$ kN$\\cdot$m.")

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
    md("The **longitudinal tension chord** collects all three demands: the bending "
       "tension, the shear shift $\\Delta F_{td}\\,z$ (6.18, capped per 6.2.3(7)) "
       "and half the distributed torsion force $F_{td,T}\\,z/2$ (6.28), as "
       "equivalent moments on the lever arm $z$, checked against the chord's "
       "bending capacity $M_{Rd}$. Under biaxial bending that capacity is "
       "**conditional**: $M_{Rd}$ is the point on the plastic $M$-$M$ envelope "
       "that also carries the coexisting off-axis moment (found by solving the "
       "neutral-axis angle whose companion moment matches it), since the pure-axis "
       "capacity overstates what the chord can lean on while the other axis is "
       "loaded. The torsion force is tensile round the whole tube, so it tensions "
       "**every** chord face -- both faces of the shear axis (the compression face "
       "carrying the torsion share without the shear shift) **and** both faces of "
       "the **off-axis** chord (its bending tension plus the torsion share, "
       "conditional on the shear-axis moment). All four are checked and the "
       "governing face of each axis reported: on a section with asymmetric steel a "
       "face the bending does not tension can still govern under the torsion share "
       "alone. On a compound (subdivided) section the torsion steel is per "
       "sub-tube, so the off-axis share is not evaluated there and a note says so.")
    md("The **shared closed stirrup** carries both actions, so their transverse "
       "demands add. When $V_{Ed} \\leq V_{Rd,c}$ the concrete alone carries the "
       "shear (6.2.1), so the shear takes **no** stirrup and the whole stirrup "
       "serves torsion; only when $V_{Ed} > V_{Rd,c}$ do the shear and torsion "
       "stirrup demands add. The added stirrup demand (least at a flat strut) and "
       "the crushing (least at 45 degrees) must both hold at **one** strut angle, so "
       "Sector reports the check at the single angle that balances the two.")
    call("standard", "That one angle is chosen to **minimise the governing "
         "utilisation** across every check that depends on it: as the strut "
         "flattens the stirrup demands ease while the crushing checks (6.9, 6.30) "
         "and the longitudinal-chord tension grow, so the optimum tracks the load "
         "instead of sitting at a band edge. Each $S_{Rd}$ in DK NA 6.3.2(6) is "
         "still the resistance to that action **acting alone** -- Sector only "
         "reports them all at that shared angle. The user enters one admissible "
         "$\\cot\\theta$ range for the physical member under **Links / stirrups**. "
         "A capacity-only run with no live shear or torsion uses the resistance-"
         "optimising angle within that same range.")

    h1("Equilibrium check")
    md("Every numerical solve carries a convergence flag. The plastic solve balances the "
       "axial force **at each swept angle** to a tight residual, "
       "$|\\sum F - N|\\le 10^{-6}\\max(1,|N|)$; an angle whose axial force cannot "
       "be balanced -- the axial demand exceeds what the section can carry there -- "
       "is marked not converged. Such a point is still drawn on the envelope (so an "
       "infeasible or partial sweep is visible rather than hidden), and the "
       "run records whether every point converged. Each Elastic state iterates the "
       "compression zone until the transformed resultants match the applied "
       "$(N,M_x,M_y)$. A fatigue spectrum converges only when its characteristic "
       "and action-factored Elastic state in every bin converge; a non-converged "
       "state cannot pass.")

    # =====================================================================
    # PART D - REFERENCE
    # =====================================================================
    part("Part D - Reference")

    h1("Standards")
    md("Sector follows the Eurocode 2 family. Material, crack-width, detailing and "
       "member-check editions are selected explicitly and recorded in the results "
       "and report; Part C states the implemented differences.")
    call("limit", "DS/EN 1992-1-1:2023 is available as a **published "
         "project-adoption basis**. The engineer must document project adoption; "
         "Sector applies no Danish National Annex to this basis. The 2023 "
         "confinement enhancement is not included or assessed.")
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
           ["Concrete fatigue (2005)", "DS/EN 1992-1-1:2005 6.8.7 / Formula (6.72); DS/EN 1992-2:2005/AC:2008, corrected 6.106"],
           ["Reinforcement fatigue (2023)", "DS/EN 1992-1-1:2023 Annex E.5 and Tables E.1/E.2"],
           ["Concrete fatigue (2023)", "DS/EN 1992-1-1:2023 E.4.3 / Formula (E.2); E.5.3 / Formulae (E.7)-(E.8)"],
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
           ["Shear, strain-based (2023)", "DS/EN 1992-1-1:2023 4.3.3 and Table 4.3 (NDP) ($\\gamma_V$); 8.2.2 ($\\tau_{Rd,c}$, $d_{dg}$)"],
           ["Shear with links (variable strut)", "DS/EN 1992-1-1 6.2.3 + DK NA 6.2.3(2)-(3)"],
           ["Torsion (thin-walled tube)", "DS/EN 1992-1-1 6.3 + DK NA 5.6.1(3)P / 6.3.2(6)"],
           ["Combined M-V-T", "DS/EN 1992-1-1 6.3.2(4) + DK NA 6.3.2(6)"]])

    h1("Limitations & troubleshooting")
    md("Use this indexed chapter for explicit model boundaries and for the "
       "symptom/cause/correction path shown by the application. A zero long-term "
       "or short-term ordinary crack criterion is an intentional no-comparison "
       "state; a zero enabled heightened criterion is invalid and must be "
       "corrected.")
    h2("Key assumptions & limitations")
    md("- **One plane section.** Plane sections remain plane; the strain field is "
       "linear across the section.\n"
       "- **Perfect bond.** Reinforcement strain equals the concrete strain at the "
       "same point (before cracking) and follows the strain plane after.\n"
       "- **No tension in the concrete** for the cracked-elastic and plastic "
       "analyses; the tensile strength enters only the cracking threshold.\n"
       "- **Ultimate is strain-controlled.** The section fails when the first "
       "material reaches its strain limit (concrete crushing or steel/tendon "
       "rupture); no material is driven past its limit.\n"
       "- **Section and resistance scope.** Sector includes section bending, "
       "elastic/crack response, grouped normal-force/bending fatigue, shear, "
       "torsion and combined M-V-T checks where the selected method is supported. "
       "It does not model member buckling, second-order response, deflection, "
       "connections or global load paths.\n"
       "- **Fatigue spectrum ownership.** Named spectra are independent. The user "
       "owns the cycle spectrum and all action assumptions; Sector uses the entered "
       "values without inferring traffic completeness. Shear and torsion fatigue "
       "are not included.\n"
       "- **Detailing scope.** The modelled-direction check does not credit tendons and "
       "does not verify the DK NA high-web side-face rule. The clear-spacing check "
       "uses the entered section-plane geometry; anchorage, lap length, bundle "
       "equivalence, cover and congestion remain separate reviews. Beam torsion-link "
       "detailing provisions are not applied to slabs.")
    call("limit", "The ordinary crack-width models are one-directional: the effective "
         "tension area and the crack spacing are defined for a single bending "
         "direction, so the crack width is reported for the governing bar along the "
         "combined N+Mx+My cracked-state strain gradient. No separate crack-system "
         "interaction layer is applied.")
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
          [["$N$ or $P$", "Axial force; tension positive; kN"],
           ["$M_x$, $M_y$", "Bending moments about the x and y axes; kNm"],
           ["$\\varphi_{NA}$", "Neutral-axis sweep angle from +y; degrees"],
           ["$s$", "Local depth projection $x\\cos\\varphi_{NA}+y\\sin\\varphi_{NA}$; larger $s$ is the compression side"],
           ["$s_{na}$", "Neutral-axis depth coordinate, $s_{max}-c$"],
           ["$s_{p,j}$", "Projected depth coordinate of tendon $j$"],
           ["$\\kappa$", "Compression-positive internal section curvature; 1/m"],
           ["$V_{Ed}$", "Applied design shear action; kN"],
           ["$\\Delta\\sigma_{Ed}$", "Action-factored fatigue stress range; MPa"],
           ["$\\Delta\\sigma_{Rsk}$", "Characteristic S-N reference range; MPa"],
           ["$N^*$", "Reference cycle count at the S-N curve knee"],
           ["$k_1$, $k_2$", "S-N slopes above and below the knee"],
           ["$D$", "Palmgren-Miner cumulative damage; limit 1.0"],
           ["$\\gamma_{Ff}$", "Partial factor on the cyclic fatigue action increment"],
           ["$f_{cd,fat}$", "Design concrete compressive fatigue strength; MPa"],
           ["$A_{sl}$", "Selected tension-side longitudinal reinforcement; mm2"],
           ["$A_{s,min}$", "Required minimum reinforcement in the modelled direction; mm2"],
           ["$b_t$", "Mean width of the bending tension zone; mm"],
           ["$D_{upper}$", "Upper aggregate size used in the clear-spacing rule; mm"],
           ["$A_{sw}/s$", "Shear-link area per spacing; mm2/mm"],
           ["$F_c$", "Concrete compression resultant; kN"],
           ["$z$, $z_x$, $z_y$", "Internal resultant lever arm and its Cartesian components; mm"],
           ["TOTAL", "Elastic stress from long- and short-term actions; MPa"],
           ["LONG", "Elastic stress from the long-term action alone; MPa"],
           ["DIF", "TOTAL minus LONG; MPa"],
           ["RST1", "Instantaneous response after neutralising long-term concrete stress; MPa"],
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


_PART_SUMMARIES = {
    "Part A - Get started": "Purpose, quick start, examples and common uses.",
    "Part B - Features & options": "Inputs, settings, load tables and result views.",
    "Part C - Theory & methodology": "Engineering models, equations and worked examples.",
    "Part D - Reference": "Standards, assumptions, limitations and glossary.",
}


def manual_parts() -> dict[str, list]:
    """Return the manual blocks grouped into their four navigable parts."""
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
    r"\varepsilon": "&#949;", r"\gamma": "&#947;", r"\sigma": "&#963;",
    r"\varphi": "&#966;", r"\alpha": "&#945;", r"\rho": "&#961;",
    r"\kappa": "&#954;",
    r"\lambda": "&#955;", r"\phi": "&#966;", r"\eta": "&#951;",
    r"\beta": "&#946;", r"\theta": "&#952;", r"\nu": "&#957;",
    r"\tau": "&#964;", r"\xi": "&#958;", r"\pi": "&#960;",
    r"\Delta": "&#916;", r"\le": "&#8804;", r"\ge": "&#8805;",
    r"\leq": "&#8804;", r"\geq": "&#8805;",
    r"\neq": "&#8800;", r"\times": "&#215;", r"\cdot": "&#183;",
    r"\approx": "&#8776;", r"\pm": "&#177;", r"\sum": "&#8721;",
    r"\circ": "&#176;", r"\rightarrow": "&#8594;",
}

_LATEX_LAYOUT_COMMANDS = (
    r"\left", r"\right", r"\Big", r"\big", r"\Bigg", r"\bigg",
    r"\mathrm", r"\!", r"\,", r"\;",
)
_LATEX_WORD_OPERATORS = ("min", "max", "ln", "log", "sin", "cos", "tan", "cot")


def _latex_to_rl(s: str) -> str:
    """Convert the LaTeX subset used in the manual to ReportLab inline markup."""
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
    s = re.sub(r"\^([A-Za-z0-9])", r"<super>\1</super>", s)
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
    return normalize_trusted_markup(converted)


def _inline_md_to_rl(text: str) -> str:
    """Inline Markdown (emphasis, bold and math) -> ReportLab inline markup.
    The literal ``<``/``>``/``&`` are escaped first so the introduced tags stay
    valid, then the supported spans reintroduce real markup."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(
        r"\[([^\]]+)\]\(#([A-Za-z0-9_-]+)\)",
        r'<link href="#\2">\1</link>',
        text,
    )
    text = re.sub(r"\$([^$]+)\$", lambda m: _latex_to_rl(m.group(1)), text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", text)
    return normalize_trusted_markup(text)


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
    flow.append(KeepTogether(metadata))

    data = [[
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
        repeatRows=1,
        splitByRow=1,
        spaceBefore=3,
    )
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.35,
         colors.HexColor(publication_theme.PALETTE.grid)),
        ("BACKGROUND", (0, 0), (-1, 0),
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
    themed("MPart", "part")
    themed("MH1", "h1")
    themed("MH2", "h2")
    themed("MH3", "h3")
    themed("MBody", "body")
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
    from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph,
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
    revision = source_revision()
    flow = [
        Paragraph("Sector user manual", styles["MTitle"]),
        Paragraph(f"Version {APP_VERSION}", styles["MSmall"]),
        Paragraph(f"Source revision: {revision}", styles["MSmall"]),
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
    for published in published_blocks:
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
            inner = Paragraph(f"<b>{ttl}:</b> " + _inline_md_to_rl(block[2]),
                              styles["MBody"])
            t = Table([[inner]], colWidths=[page_w])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(
                    publication_theme.PALETTE.manual_surface
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
            reference = Paragraph(
                f'See <link href="#{item.anchor}">{item.label}</link>.',
                styles["MPubRef"],
            )
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
                    [reference],
                    [Image(io.BytesIO(png), width=page_w, height=img_h)],
                    [caption],
                ]
            else:
                figure_rows = [
                    [reference],
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
            flow.append(Paragraph(
                f'See <link href="#{item.anchor}">{item.label}</link>.',
                styles["MPubRef"],
            ))
            data = [[Paragraph(caption_markup, styles["MPubCaption"])]
                    + [""] * (ncol - 1)]
            data += [[Paragraph(f"<b>{_inline_md_to_rl(h)}</b>", styles["MSmall"])
                      for h in headers]]
            data += [[Paragraph(_inline_md_to_rl(str(c)), styles["MSmall"]) for c in row]
                     for row in rows]
            t = report._PaginatedReportTable(
                data,
                colWidths=[page_w / ncol] * ncol,
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
        revision=revision,
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

    rendered = _latex_to_rl(str(expression)).replace(
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

    def _stash_math(match):
        index = len(math_fragments)
        token = f"\ue000{index}\ue001"
        math_fragments.append((token, _math_code_html(match.group(1))))
        return token

    source = re.sub(r"\$([^$\n]+)\$", _stash_math, str(text))
    rendered = html.escape(source, quote=True)
    rendered = re.sub(
        r"\[([^\]]+)\]\(#([A-Za-z0-9_-]+)\)",
        r'<a href="#\2">\1</a>',
        rendered,
    )
    rendered = re.sub(
        r"`([^`]+)`",
        r"<code>\1</code>",
        rendered,
    )

    rendered = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", rendered)
    rendered = re.sub(
        r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", rendered
    )
    for token, fragment in math_fragments:
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

    published_blocks = tuple(
        publish_manual_blocks(manual_publication_blocks(manual_blocks()))
    )
    heading_records, toc = _manual_html_heading_records(published_blocks)
    revision = source_revision()
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
                f'<aside class="callout {html.escape(block[1])}"><strong>'
                + html.escape(title)
                + ":</strong> "
                + _inline_md_to_html(block[2])
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
            body.append(
                f'<figure id="{item.anchor}"><div class="figure-alternative" '
                f'role="img" aria-label="{html.escape(alternative, quote=True)}">'
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
<meta name="sector-source-revision" content="{html.escape(revision, quote=True)}">
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
nav ol {{ padding-left:1.5rem; }} .toc-level-1 {{ margin-left:1rem; }} .toc-level-2 {{ margin-left:2rem; }}
table {{ width:100%; border-collapse:collapse; margin:.5rem 0 1.25rem; }}
th,td {{ border:1px solid #b5bdc6; padding:.45rem; text-align:left; vertical-align:top; }}
th {{ background:var(--surface); }} .table-scroll {{ overflow-x:auto; }}
.callout,.equation,figure {{ border:1px solid var(--rule); padding:1rem; margin:1rem 0; break-inside:avoid; }}
.display-math,.equation-text {{ overflow-wrap:anywhere; padding:.5rem; background:#f7f8fa; }}
.math,code {{ font-family:"Courier New", monospace; }}
.figure-alternative {{ padding:1rem; border:2px dashed var(--rule); background:#f7f8fa; }}
@media print {{ body {{ max-width:none; padding:1cm; }} a {{ color:inherit; }} }}
</style>
</head>
<body>
<a class="skip-link" href="#manual-main">Skip to main content</a>
<header>
<h1>Sector user manual</h1>
<p class="document-control"><strong>Version:</strong> {html.escape(APP_VERSION)}<br>
<strong>Source revision:</strong> {html.escape(revision)}<br>
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
                except Exception as e:                   # never break the dialog
                    st.session_state["manual_pdf"] = None
                    st.session_state["manual_html"] = None
                    st.error(f"Manual build failed: {e}")
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
                st.markdown(f"{icon} **{title}** -- {block[2]}")
        elif kind == "figure":
            if item is None:
                raise ValueError("A published manual figure has no identity.")
            st.markdown(item.markdown_reference)
            st.markdown(f"##### {item.label}")
            try:
                # A unique key per block: two structurally-similar figures would
                # otherwise share an auto-generated element id and Streamlit raises a
                # duplicate-id error (seen once other charts exist, e.g. after Calculate).
                st.plotly_chart(block[1](), width="stretch", key=f"manual_fig_{i}")
            except Exception as e:                       # a broken figure must not
                st.caption(f"[figure unavailable: {e}]")  # break the whole manual
            st.caption(item.caption)
        elif kind == "table":
            if item is None:
                raise ValueError("A published manual table has no identity.")
            st.markdown(item.markdown_reference)
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
