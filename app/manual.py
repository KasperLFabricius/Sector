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

import re

import streamlit as st

from sector import templates
from sector.materials import Concrete, MildSteel, Prestress

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
       "3. **Choose the analyses.** In *Analysis & Result Settings* pick Plastic, "
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
           ["Crack width (2023)", "EN 1992-1-1:2023 9.2.3"]])

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
          [["$N$ or $P$", "Axial force (compression positive)"],
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
# STREAMLIT RENDERER
# ==========================================================================

def render_manual_streamlit():
    """Render the manual in place of the analysis layout (viewport takeover).

    Mirrors the Quick Section builder: a session flag (``_manual_open``) makes the
    app render this instead of the normal views. A *Back* button closes it.
    """
    top = st.columns([1, 5])[0]
    if top.button("Back", use_container_width=True, key="manual_back"):
        st.session_state["_manual_open"] = False
        st.rerun()

    st.markdown("# Sector user manual")
    st.caption("What Sector computes, the theory it applies, its features, and how "
               "to use it.")

    n1 = n2 = 0
    for block in manual_blocks():
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
                st.plotly_chart(block[1](), use_container_width=True)
            except Exception as e:                       # a broken figure must not
                st.caption(f"[figure unavailable: {e}]")  # break the whole manual
            st.caption(block[2])
        elif kind == "table":
            header = "| " + " | ".join(block[1]) + " |"
            sep = "| " + " | ".join(["---"] * len(block[1])) + " |"
            body = "\n".join("| " + " | ".join(str(c) for c in row) + " |"
                             for row in block[2])
            st.markdown(f"{header}\n{sep}\n{body}")
