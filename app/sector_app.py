"""Sector - reinforced-concrete cross-section analysis (Streamlit interface).

Define a section by its shape and reinforcement, choose elastic and/or plastic
analysis, then press Calculate to review the stresses and the ultimate capacity.
"""

from __future__ import annotations

import pathlib
import sys

# Make both the repo root (for ``sector``) and this app folder (for ``viz``)
# importable when run as a script or via Streamlit's AppTest.
_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE))

import numpy as np  # noqa: E402
import streamlit as st  # noqa: E402

import viz  # noqa: E402
from sector import kernels, material_presets as mp, templates  # noqa: E402
from sector.elastic import solve_elastic  # noqa: E402
from sector.plastic import solve_plastic  # noqa: E402
from sector.section import Section  # noqa: E402

APP_VERSION = "0.1.0"
ROOT = pathlib.Path(__file__).resolve().parent.parent

st.set_page_config(layout="wide", page_title=f"Sector v{APP_VERSION}")

# Colour the input help "?" icons amber-yellow so they stand out as hover hints.
st.markdown(
    "<style>[data-testid='stTooltipIcon']{color:#e0a800;}"
    "[data-testid='stTooltipIcon'] svg{stroke:#e0a800;}</style>",
    unsafe_allow_html=True)


@st.cache_resource(show_spinner="Preparing the solver...")
def _warm_solver():
    """Compile the solver kernels once per server, so the cost is paid at
    startup rather than on the first Calculate."""
    return kernels.warmup()


_warm_solver()

_logo = ROOT / "assets" / "logo.png"
if _logo.exists():
    st.sidebar.image(str(_logo), use_container_width=True)

st.title(f"Sector v{APP_VERSION}")
st.caption("Reinforced-concrete cross-section analysis - elastic stresses and plastic capacity")


# ---------------------------------------------------------------------------
# Material Parameters panel: one section per material, each with a preset
# dropdown (legacy curves + Eurocode editions), editable parameters and a live
# stress-strain diagram. A preset only prefills values; all stay editable.
# ---------------------------------------------------------------------------

_PRESET_HELP = ("Prefills a named stress-strain law (a legacy curve shape or a "
                "Eurocode edition). Every parameter stays editable afterwards.")


def _prefill(prefix, preset, presets):
    """Load a preset's defaults into the field keys when the selection changes."""
    prev = f"{prefix}_prev"
    if st.session_state.get(prev) != preset:
        for field, value in presets[preset].items():
            st.session_state[f"{prefix}_{field}"] = value
        st.session_state[prev] = preset


def _number(box, prefix, field, meta, help_map=None):
    label, lo, hi, step = meta[field]
    return box.number_input(label, float(lo), float(hi), step=float(step),
                            key=f"{prefix}_{field}",
                            help=(help_map or {}).get(field))


def _safe_build(box, builder, curve, vals):
    """Build a material from the flat parameter set, surviving degenerate input.

    A flat form lets the user enter values the active curve cannot accept (e.g. a
    zero rupture stress on a hardening curve). Rather than break the whole app,
    show a notice and retry with the offending stresses nudged just above zero so
    the diagram and the analysis still render.
    """
    try:
        return builder(curve=curve, **vals)
    except ValueError as exc:
        box.warning(f"Adjusted for this curve: {exc}")
        v = dict(vals)
        for f in ("fytk", "futk"):
            if v.get(f, 1.0) <= 0.0:
                v[f] = 1.0
        return builder(curve=curve, **v)


def _clamp_eut(box, vals, fields):
    """Keep the rupture strain at or above the (second) yield strain -- a
    meaningful, not arbitrary, limit: a curve cannot rupture before it has
    reached its yield/ultimate branch. For the two-yield laws the yield is the
    second yield, reached at ``ey0t + fytk/Es``. Only applies when the active
    curve uses ``fytk`` and ``eut``. Strain fields here are in per-mille."""
    if "eut" in fields and "fytk" in fields and vals.get("Es", 0.0) > 0.0:
        ey = vals["fytk"] / vals["Es"] * 1000.0   # yield strain in per-mille
        if "ey0t" in fields:
            ey += vals.get("ey0t", 0.0)           # second-yield (total) strain
        if vals["eut"] < ey:
            box.warning("eut must be at least the yield strain (ey0t + fytk/Es); "
                        "using that value for the diagram and analysis.")
            vals["eut"] = ey


def concrete_panel(box):
    """Concrete material: preset and editable parameters (diagram is in the main view)."""
    box.markdown("**Concrete**")
    presets = mp.CONCRETE_PRESETS
    labels = list(presets)
    preset = box.selectbox("Preset", labels, index=labels.index("EN 1992-1-1:2005"),
                           key="conc_preset", help=_PRESET_HELP)
    _prefill("conc", preset, presets)
    curve = presets[preset]["curve"]
    fck = _number(box, "conc", "fck", mp.CONCRETE_FIELD_META, mp.CONCRETE_HELP)
    gamma_c = _number(box, "conc", "gamma_c", mp.CONCRETE_FIELD_META, mp.CONCRETE_HELP)
    # For a strength-dependent edition (EN 2023), keep alpha_cc tracking fck --
    # recompute it whenever fck changes, while still allowing a manual override
    # in between. Constant-alpha_cc editions just keep the editable value.
    auto = mp.strength_dependent_alpha_cc(preset, fck)
    if auto is not None and st.session_state.get("conc_alpha_fck") != fck:
        st.session_state["conc_alpha_cc"] = auto
        st.session_state["conc_alpha_fck"] = fck
    if auto is None:
        st.session_state.pop("conc_alpha_fck", None)
    alpha_cc = _number(box, "conc", "alpha_cc", mp.CONCRETE_FIELD_META, mp.CONCRETE_HELP)
    concrete = mp.build_concrete(curve=curve, fck=fck, gamma_c=gamma_c,
                                 alpha_cc=alpha_cc)
    note = "  (alpha_cc tracks fck via eta_cc)" if auto is not None else ""
    box.caption(f"curve {curve},  fcd = {concrete.fcd:.1f} MPa{note}")
    return concrete


def mild_panel(box):
    """Mild-steel material: preset and editable parameters (diagram is in the main view).

    A flat form on the general two-yield law: every parameter is always shown
    and live, so the inputs never change with the preset. A preset only prefills
    the values; the named shapes (bilinear, elastic-perfectly-plastic) are
    special cases of the same law.
    """
    box.markdown("**Mild steel**")
    presets = mp.MILD_PRESETS
    labels = list(presets)
    preset = box.selectbox("Preset", labels, index=labels.index("EN 1992-1-1:2005"),
                           key="mild_preset", help=_PRESET_HELP)
    _prefill("mild", preset, presets)
    curve = presets[preset]["curve"]
    vals = {f: _number(box, "mild", f, mp.MILD_FIELD_META, mp.MILD_HELP)
            for f in mp.MILD_FIELD_META}
    _clamp_eut(box, vals, mp.MILD_FIELDS_BY_CURVE[curve])
    steel = _safe_build(box, mp.build_mild, curve, vals)
    box.caption(f"fyd = {steel.fytk / vals['gamma_y']:.0f} MPa,  "
                f"Es = {vals['Es'] / 1000.0:.0f} GPa")
    return steel


def prestress_panel(box):
    """Prestressing-steel material: preset and editable parameters (diagram is in the main view).

    A flat form: the user-defined and Eurocode presets build the general
    two-yield law, so every parameter is live. The built-in characteristic
    curves are fixed shapes -- only the prestrain (and yield factor) apply.
    """
    box.markdown("**Prestressing steel**")
    presets = mp.PRESTRESS_PRESETS
    labels = list(presets)
    preset = box.selectbox("Preset", labels, index=labels.index("EN 1992-1-1:2005"),
                           key="pre_preset", help=_PRESET_HELP)
    _prefill("pre", preset, presets)
    curve = presets[preset]["curve"]
    vals = {f: _number(box, "pre", f, mp.PRESTRESS_FIELD_META, mp.PRESTRESS_HELP)
            for f in mp.PRESTRESS_FIELD_META}
    _clamp_eut(box, vals, mp.PRESTRESS_FIELDS_BY_CURVE[curve])
    pre = _safe_build(box, mp.build_prestress, curve, vals)
    if curve in (1, 2, 3, 4, 5):
        box.caption(f"built-in curve {curve} (fixed shape); only the prestrain "
                    f"IS = {vals['IS']:.1f} permille applies")
    else:
        box.caption(f"IS = {vals['IS']:.1f} permille,  "
                    f"fpd = {vals['fytk'] / vals['gamma_y']:.0f} MPa,  "
                    f"Ep = {vals['Es'] / 1000.0:.0f} GPa")
    return pre


# ---------------------------------------------------------------------------
# Build the section + materials from the sidebar inputs
# ---------------------------------------------------------------------------

def build_inputs():
    """Render the sidebar dropdown panels and return the section, materials and
    loads. Panels mirror the BriCoS layout: About, Analysis & Result Settings,
    Section, Material Parameters, Loads."""
    s = st.sidebar

    with s.expander("About", expanded=False):
        st.markdown(
            "**Sector** analyses reinforced-concrete (and optionally "
            "prestressed) cross-sections, returning the plastic bending "
            "capacity and the cracked-section elastic stresses.")
        st.caption("Define the section and materials, choose elastic and/or "
                   "plastic analysis, then press Calculate. The section drawing "
                   "and the stress-strain diagrams update live; the results "
                   "update on Calculate.")
        st.caption(f"Version {APP_VERSION}")

    aset = s.expander("Analysis & Result Settings", expanded=False)
    mode = aset.radio("Analysis", ["Plastic", "Elastic", "Both"], key="mode",
                      help="Plastic: ultimate bending capacity (M-M envelope). "
                           "Elastic: cracked-section concrete and bar stresses "
                           "for the applied loads. Both: run the two.")
    ratio = aset.number_input("Modular ratio n = Es/Ec", 5.0, 30.0, 15.0, 0.5,
                              key="ratio",
                              disabled=mode not in ("Elastic", "Both"),
                              help="Ratio of the steel to concrete elastic "
                                   "modulus (Es/Ec) for the cracked elastic "
                                   "analysis.")

    sec = s.expander("Section", expanded=True)
    shape = sec.selectbox("Shape", ["Rectangle", "Slab strip", "T-section",
                                    "Box girder", "Circular"], key="shape",
                          help="Outline of the concrete cross-section to analyse.")

    holes = []
    if shape == "Rectangle":
        b = sec.number_input("Width b (m)", 0.05, 10.0, 0.40, 0.05, key="b",
                             help="Overall section width.")
        h = sec.number_input("Height h (m)", 0.05, 10.0, 0.60, 0.05, key="h",
                             help="Overall section height (depth).")
        outer = templates.rectangle(b, h)
        width_b = b
    elif shape == "Slab strip":
        h = sec.number_input("Thickness h (m)", 0.05, 3.0, 0.30, 0.01, key="h",
                             help="Slab thickness; the strip is analysed per 1 m width.")
        b = 1.0
        outer = templates.slab_strip(h)
        width_b = b
    elif shape == "T-section":
        bf = sec.number_input("Flange width bf (m)", 0.1, 12.0, 1.20, 0.05, key="bf",
                              help="Width of the (top) flange.")
        hf = sec.number_input("Flange thickness hf (m)", 0.05, 2.0, 0.20, 0.01, key="hf",
                              help="Thickness of the flange.")
        bw = sec.number_input("Web width bw (m)", 0.05, 4.0, 0.30, 0.05, key="bw",
                              help="Width of the web.")
        hw = sec.number_input("Web depth hw (m)", 0.1, 6.0, 0.60, 0.05, key="hw",
                              help="Depth of the web below the flange.")
        outer = templates.t_section(bf, hf, bw, hw)
        b, h, width_b = bw, hf + hw, bf
    elif shape == "Box girder":
        b = sec.number_input("Width b (m)", 0.2, 12.0, 0.80, 0.05, key="b",
                             help="Overall outer width of the box.")
        h = sec.number_input("Height h (m)", 0.2, 12.0, 1.00, 0.05, key="h",
                             help="Overall outer height of the box.")
        # Cap the wall so the cavity stays positive (2*wall < b and < h).
        max_wall = round(min(b, h) / 2 - 0.01, 3)
        wall = sec.number_input("Wall thickness (m)", 0.02, max_wall,
                                min(0.20, max_wall), 0.01, key="wall",
                                help="Thickness of the box walls (uniform).")
        outer, holes = templates.box(b, h, wall)
        width_b = b
    else:  # Circular
        dia = sec.number_input("Diameter (m)", 0.1, 6.0, 0.60, 0.05, key="dia",
                               help="Outer diameter of the circular section.")
        outer = templates.circular(dia)
        b = h = dia
        width_b = dia

    sec.markdown("**Reinforcement**")
    if shape == "Circular":
        nb = sec.number_input("Perimeter bars", 0, 200, 8, 1, key="ring_n",
                              help="Number of bars evenly spaced around the perimeter.")
        rd = sec.selectbox("Bar diameter (mm)", templates.BAR_DIAMETERS, index=4,
                           key="ring_d", help="Diameter of each reinforcement bar.")
        cov = sec.number_input("Cover (m)", 0.0, 0.5, 0.05, 0.005, key="ring_c",
                               help="Distance from the section face to the bar centres.")
        bars = templates.bar_ring(0.0, 0.0, dia / 2 - cov, int(nb), rd)
    else:
        c1, c2 = sec.columns(2)
        with c1:
            st.markdown("**Bottom**")
            nb_bot = st.number_input("n##bot", 0, 100, 6, 1, key="bot_n", label_visibility="collapsed",
                                     help="Number of bars in the bottom layer.")
            rd_bot = st.selectbox("dia##bot", templates.BAR_DIAMETERS, index=4, key="bot_d",
                                  label_visibility="collapsed", help="Bottom bar diameter (mm).")
        with c2:
            st.markdown("**Top**")
            nb_top = st.number_input("n##top", 0, 100, 2, 1, key="top_n", label_visibility="collapsed",
                                     help="Number of bars in the top layer.")
            rd_top = st.selectbox("dia##top", templates.BAR_DIAMETERS, index=4, key="top_d",
                                  label_visibility="collapsed", help="Top bar diameter (mm).")
        cov = sec.number_input("Cover (m)", 0.0, 0.5, 0.05, 0.005, key="cover",
                               help="Distance from the top/bottom face to the bar centres.")
        bw_eff = width_b if shape == "T-section" else b
        bars = templates.merge_bars(
            templates.bar_row(-h / 2 + cov, -(b if shape != "T-section" else bw_eff) / 2 + cov,
                              (b if shape != "T-section" else bw_eff) / 2 - cov, int(nb_bot), rd_bot)
            if shape != "T-section" else
            templates.bar_row(-(hf + hw) / 2 + cov, -bw / 2 + cov, bw / 2 - cov, int(nb_bot), rd_bot),
            templates.bar_row(h / 2 - cov, -width_b / 2 + cov, width_b / 2 - cov, int(nb_top), rd_top),
        )

    sec.markdown("**Prestressing**")
    use_pre = sec.checkbox("Include prestressing tendons", value=False, key="use_pre",
                           help="Add a row of prestressing tendons and the "
                                "Prestressing-steel material panel.")
    tendons = []
    prestress = None
    if use_pre:
        nt = sec.number_input("Tendons", 0, 200, 4, 1, key="tnd_n",
                              help="Number of tendons in the row.")
        a_t = sec.number_input("Area per tendon (mm2)", 1.0, 50000.0, 150.0, 10.0, key="tnd_a",
                               help="Cross-sectional area of a single tendon.")
        cov_p = sec.number_input("Tendon cover (m)", 0.0, 2.0, 0.10, 0.01, key="tnd_c",
                                 help="Distance from the bottom face (or the "
                                      "circular ring) to the tendons.")
        if shape == "Circular":
            tendons = templates.point_ring(0.0, 0.0, max(dia / 2 - cov_p, 0.0),
                                           int(nt), a_t)
        else:
            # Bottom (tension) row; b and h are already the web/overall dimensions
            # for the T-section, matching the bottom reinforcement placement.
            tendons = templates.point_row(-h / 2 + cov_p, -b / 2 + cov_p,
                                          b / 2 - cov_p, int(nt), a_t)

    mat = s.expander("Material Parameters", expanded=False)
    concrete = concrete_panel(mat)
    mat.divider()
    steel = mild_panel(mat)
    if use_pre:
        mat.divider()
        prestress = prestress_panel(mat)

    loads = s.expander("Loads", expanded=True)
    P = loads.number_input("Axial force P (kN, + = compression)", -50000.0, 50000.0, 0.0, 50.0,
                           key="P", help="Axial force on the section; positive is "
                                         "compression. Used by both analyses.")
    Mx = loads.number_input("Applied Mx (kNm)", -100000.0, 100000.0, 200.0, 10.0, key="Mx",
                            help="Applied moment about the x-axis: the elastic "
                                 "stresses are computed for it, and it sets the "
                                 "plastic utilisation point on the M-M envelope.")
    My = loads.number_input("Applied My (kNm)", -100000.0, 100000.0, 0.0, 10.0, key="My",
                            help="Applied moment about the y-axis (biaxial bending).")

    section = Section.from_polygon(corners=outer, bars_xy_area_mm2=bars,
                                   tendons_xy_area_mm2=tendons, holes=holes)
    extent = max(abs(b), abs(h)) * 0.75
    sig = (st.session_state.get(k) for k in
           ("shape", "b", "h", "bf", "hf", "bw", "hw", "wall", "dia",
            "bot_n", "bot_d", "top_n", "top_d", "ring_n", "ring_d", "ring_c",
            "cover", "conc_preset", "conc_fck", "conc_gamma_c", "conc_alpha_cc",
            "mild_preset", "mild_fytk", "mild_fyck", "mild_futk", "mild_eut",
            "mild_gamma_y", "mild_gamma_u", "mild_gamma_E", "mild_k",
            "mild_ey0t", "mild_ey0c", "mild_Es", "use_pre", "tnd_n", "tnd_a",
            "tnd_c", "pre_preset", "pre_IS", "pre_fytk", "pre_futk", "pre_eut",
            "pre_gamma_y", "pre_gamma_u", "pre_gamma_E", "pre_k", "pre_ey0t",
            "pre_Es", "P", "Mx", "My", "ratio", "mode"))
    return dict(section=section, concrete=concrete, steel=steel, ratio=ratio,
                bars=bars, outer=outer, holes=holes, tendons=tendons,
                prestress=prestress, P=P, Mx=Mx, My=My, mode=mode,
                extent=extent, signature=tuple(sig))


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def run_analysis(inp):
    out = {}
    if inp["mode"] in ("Plastic", "Both"):
        pts = solve_plastic(inp["section"], inp["concrete"], inp["steel"],
                            inp["P"], 0.0, 360.0, 15.0, prestress=inp["prestress"])
        mx = [p.Mx for p in pts]
        my = [p.My for p in pts]
        out["plastic"] = dict(
            mx=mx, my=my,
            max_mx=max(mx), max_my=max(my),
            util=_radial_util(mx, my, inp["Mx"], inp["My"]),
            converged=all(p.converged for p in pts),
        )
    if inp["mode"] in ("Elastic", "Both"):
        # The elastic analysis ignores the section's tendons, so model each tendon
        # as an ordinary bar by folding them into the bar set for this run.
        sec = inp["section"]
        if inp["tendons"]:
            sec = Section.from_polygon(corners=inp["outer"],
                                       bars_xy_area_mm2=list(inp["bars"]) + list(inp["tendons"]),
                                       holes=inp["holes"])
        r = solve_elastic(sec, inp["P"], inp["Mx"], inp["My"], inp["ratio"])
        out["elastic"] = dict(
            bar_stress=[s / 1000.0 for s in r.bar_stress],  # kN/m2 -> MPa
            max_conc=r.max_concrete_compression / 1000.0,
            na_x=r.na_x_intercept, na_y=r.na_y_intercept,
            converged=r.converged,
        )
    return out


def _radial_util(mx, my, ax, ay):
    a_rad = float(np.hypot(ax, ay))
    if a_rad < 1e-9:
        return 0.0
    angs = np.arctan2(my, mx)
    rad = np.hypot(mx, my)
    order = np.argsort(angs)
    angs_s, rad_s = angs[order], rad[order]
    ext_a = np.concatenate([angs_s - 2 * np.pi, angs_s, angs_s + 2 * np.pi])
    ext_r = np.concatenate([rad_s, rad_s, rad_s])
    cap = float(np.interp(np.arctan2(ay, ax), ext_a, ext_r))
    return a_rad / cap if cap > 0 else float("inf")


# ---------------------------------------------------------------------------
# Views (main area). A "View" dropdown selects what fills the main viewport,
# the way BriCoS switches between its result diagrams. The Section drawing and
# the stress-strain diagrams reflect the inputs live; the Plastic and Elastic
# result views need a Calculate.
# ---------------------------------------------------------------------------

VIEWS = ["Section", "Stress-Strain diagrams", "Plastic Results", "Elastic Results"]


def section_view(inp, results, stale):
    """The section drawing, with the elastic neutral axis when available.

    The geometry redraws live, but the neutral axis comes from the last
    calculation. When the inputs have changed since then (``stale``), the
    cached axis would sit on a different section, so it is hidden and a notice
    is shown instead of drawing a misleading line.
    """
    bar_xy = [(b[0], b[1]) for b in inp["bars"]]
    tendon_xy = [(t[0], t[1]) for t in inp["tendons"]]
    has_elastic = bool(results and "elastic" in results)
    na_line = None
    if has_elastic and not stale:
        na_line = viz.na_endpoints(results["elastic"]["na_x"],
                                   results["elastic"]["na_y"], inp["extent"])
    if has_elastic and stale:
        st.warning("Inputs changed since the last calculation - the neutral "
                   "axis is hidden; press Calculate to update.")
    st.plotly_chart(viz.section_figure(inp["outer"], inp["holes"], bar_xy,
                                       na_line=na_line, title="Section",
                                       tendons=tendon_xy),
                    use_container_width=True)


def materials_view(inp):
    """Stress-strain diagrams for the chosen materials (live, no Calculate)."""
    c1, c2 = st.columns(2)
    c1.plotly_chart(viz.concrete_curve_figure(inp["concrete"]), use_container_width=True)
    c2.plotly_chart(viz.steel_curve_figure(inp["steel"]), use_container_width=True)
    if inp["prestress"] is not None:
        st.plotly_chart(viz.prestress_curve_figure(inp["prestress"]),
                        use_container_width=True)


def plastic_view(inp, results):
    """Plastic capacity metrics and the biaxial interaction envelope."""
    if not results or "plastic" not in results:
        st.info("Run a Plastic or Both analysis, then press Calculate.")
        return
    p = results["plastic"]
    m1, m2, m3 = st.columns(3)
    m1.metric("Max Mx", f"{p['max_mx']:.0f} kNm")
    m2.metric("Max My", f"{p['max_my']:.0f} kNm")
    m3.metric("Utilisation", f"{p['util']:.2f}",
              help="applied / capacity in the load direction")
    st.plotly_chart(
        viz.interaction_figure(p["mx"], p["my"], applied=(inp["Mx"], inp["My"])),
        use_container_width=True)


def elastic_view(inp, results):
    """Cracked-section elastic stresses: peak concrete and per-bar stresses."""
    if not results or "elastic" not in results:
        st.info("Run an Elastic or Both analysis, then press Calculate.")
        return
    e = results["elastic"]
    st.metric("Max concrete compression", f"{e['max_conc']:.1f} MPa")
    st.dataframe(
        {"Bar": list(range(1, len(e["bar_stress"]) + 1)),
         "Stress (MPa)": [round(s, 1) for s in e["bar_stress"]]},
        hide_index=True, use_container_width=True)


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

inp = build_inputs()

c_view, c_calc = st.columns([3, 1])
view = c_view.selectbox("View", VIEWS, key="view",
                        help="What to show in the main area. Section and "
                             "Stress-Strain diagrams update live; the result "
                             "views need a Calculate.")
# Nudge the unlabelled button down so it lines up with the selectbox input.
c_calc.markdown("<div style='height:1.7em'></div>", unsafe_allow_html=True)
calc = c_calc.button("Calculate", type="primary", key="calculate",
                     use_container_width=True,
                     help="Run the selected analysis for the current inputs.")

if calc:
    st.session_state["results"] = run_analysis(inp)
    st.session_state["result_sig"] = inp["signature"]

results = st.session_state.get("results")
stale = results is not None and st.session_state.get("result_sig") != inp["signature"]
if stale and view in ("Plastic Results", "Elastic Results"):
    st.warning("Inputs changed since the last calculation - press Calculate to update.")

if view == "Section":
    section_view(inp, results, stale)
elif view == "Stress-Strain diagrams":
    materials_view(inp)
elif view == "Plastic Results":
    plastic_view(inp, results)
else:
    elastic_view(inp, results)
