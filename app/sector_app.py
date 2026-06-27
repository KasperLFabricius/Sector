"""Sector - reinforced-concrete cross-section analysis (Streamlit interface).

Define a section by its shape and reinforcement, choose elastic and/or plastic
analysis, then press Calculate to review the stresses and the ultimate capacity.
"""

from __future__ import annotations

import math
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
from sector import codes, geometry, kernels, material_presets as mp, templates  # noqa: E402
from sector.elastic import solve_elastic_combined  # noqa: E402
from sector.plastic import solve_plastic  # noqa: E402
from sector.section import Section  # noqa: E402
from sector.serviceability import analyse_cracking  # noqa: E402

APP_VERSION = "0.1.0"
ROOT = pathlib.Path(__file__).resolve().parent.parent

st.set_page_config(layout="wide", page_title=f"Sector v{APP_VERSION}")


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
# dropdown (named curves + Eurocode editions), editable parameters and a live
# stress-strain diagram. A preset only prefills values; all stay editable.
# ---------------------------------------------------------------------------

_PRESET_HELP = ("Prefills a named stress-strain law (a named curve shape or a "
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
            "capacity and the cracked-section elastic stresses, with two "
            "optional serviceability checks on the elastic side (a cracking "
            "threshold, and tension stiffening with crack width).")
        st.caption("Define the section and materials, choose the analyses, then "
                   "press Calculate. The section drawing and the stress-strain "
                   "diagrams update live; the results update on Calculate.")
        st.caption(f"Version {APP_VERSION}")

    aset = s.expander("Analysis & Result Settings", expanded=False)
    mode = aset.radio("Analysis", ["Plastic", "Elastic", "Both"], key="mode",
                      help="Plastic: ultimate bending capacity (M-M envelope). "
                           "Elastic: cracked-section concrete and bar stresses "
                           "for the applied loads. Both: run the two.")
    plastic_on = mode in ("Plastic", "Both")
    elastic_on = mode in ("Elastic", "Both")

    aset.markdown("**Neutral-axis sweep (plastic)**")
    v_min = aset.number_input("Start angle V.min (deg)", 0.0, 360.0, 0.0, 5.0,
                              key="v_min", disabled=not plastic_on,
                              help="First neutral-axis rotation angle of the plastic sweep.")
    v_max = aset.number_input("End angle V.max (deg)", 0.0, 360.0, 360.0, 5.0,
                              key="v_max", disabled=not plastic_on,
                              help="Last neutral-axis rotation angle of the plastic sweep.")
    v_inc = aset.number_input("Increment V.inc (deg)", 1.0, 90.0, 15.0, 1.0,
                              key="v_inc", disabled=not plastic_on,
                              help="Angular step between swept neutral-axis angles; "
                                   "a finer step gives a smoother M-M envelope.")

    # Extended elastic checks (SLS). The plain elastic analysis stays the
    # cracked-section result with zero concrete tensile strength; these are two
    # optional, theoretically fuller checks on top of it, run from their own
    # serviceability load set. Independent of the plastic/elastic mode above.
    aset.markdown("**Extended elastic checks (SLS)**")
    aset.caption("Optional. The plain Elastic analysis is unchanged (cracked "
                 "section, zero concrete tension).")
    sls_threshold = aset.checkbox(
        "Cracking threshold (Stage I / II)", value=False, key="sls_threshold",
        help="Compare the uncracked concrete tension with fctm to decide whether "
             "the section has cracked, and report the governing stage's stresses "
             "(the uncracked Stage I stresses when it has not cracked).")
    sls_ts = aset.checkbox(
        "Tension stiffening & crack width", value=False, key="sls_ts",
        help="Account for the intact concrete between cracks: the tension-"
             "stiffened mean state (zeta) and the crack width wk. Uses the "
             "cracking threshold.")
    sls_any = sls_threshold or sls_ts
    sls_long = aset.radio(
        "Load duration", ["Long-term (sustained)", "Short-term"], key="sls_dur",
        disabled=not sls_ts,
        help="Sets the tension-stiffening factors: long-term beta = 0.5, "
             "kt = 0.4; short-term beta = 1.0, kt = 0.6.") == "Long-term (sustained)"
    _fck_now = float(st.session_state.get("conc_fck", 30.0))
    sls_fctm = aset.number_input(
        "Concrete tensile strength fctm (MPa)", 0.0, 10.0,
        value=round(codes.fctm(_fck_now), 3), step=0.1, key="sls_fctm",
        disabled=not sls_any,
        help="Mean axial tensile strength for the cracking check (fct,eff). "
             "Defaults to the EC2 Table 3.1 value for the concrete grade.")
    aset.caption(f"EC2 Table 3.1 for the current grade: fctm = "
                 f"{codes.fctm(_fck_now):.2f} MPa")
    sls_cover = aset.number_input(
        "Cover to bar surface c (mm)", 0.0, 200.0, 40.0, 1.0, key="sls_cover",
        disabled=not sls_ts,
        help="Clear cover to the governing bar, used for the crack spacing sr,max.")
    sls_phi = aset.number_input(
        "Bar diameter (mm, 0 = auto)", 0.0, 60.0, 0.0, 1.0, key="sls_phi",
        disabled=not sls_ts,
        help="Governing bar diameter for sr,max; 0 derives it from the bar area.")

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

    # Loads: the plastic and elastic analyses take their own load sets, so a
    # capacity check (e.g. ULS) and a stress check (e.g. SLS) use different
    # actions without overwriting each other. The plastic axial force fixes the
    # M-M envelope; its moments are the point checked against it. Both sets stay
    # mounted (the inactive one is disabled) so their values survive a mode
    # switch instead of being reset when Streamlit drops unrendered widgets.
    loads = s.expander("Loads", expanded=True)

    def _load_set(prefix, n_help, m_help, active, mx_default=200.0):
        P = loads.number_input("Axial force N (kN, + = compression)", -50000.0,
                               50000.0, 0.0, 50.0, key=f"{prefix}_P", help=n_help,
                               disabled=not active)
        Mx = loads.number_input("Applied Mx (kNm)", -100000.0, 100000.0, mx_default,
                                10.0, key=f"{prefix}_Mx", help=m_help, disabled=not active)
        My = loads.number_input("Applied My (kNm)", -100000.0, 100000.0, 0.0, 10.0,
                                key=f"{prefix}_My", disabled=not active,
                                help="Applied bending moment about the y-axis (biaxial bending).")
        return P, Mx, My

    loads.markdown("**Plastic capacity**")
    P_pl, Mx_pl, My_pl = _load_set(
        "pl", "Axial force for which the plastic M-M capacity envelope is computed.",
        "Applied moment checked against the plastic envelope (utilisation).", plastic_on)

    loads.divider()
    loads.markdown("**Elastic stresses (long + short term)**")
    loads.caption("Long-term and short-term load with their own modular ratios "
                  "(the creep analysis). For a simple check leave the short-term "
                  "load at zero and set both ratios equal.")
    loads.markdown("_Long-term_")
    P_el_l, Mx_el_l, My_el_l = _load_set(
        "el_long", "Sustained axial force (long-term).",
        "Sustained moment (long-term).", elastic_on)
    nl = loads.number_input("Long-term modular ratio n_l = Es/Ec", 1.0, 50.0, 15.0, 0.5,
                            key="nl", disabled=not elastic_on,
                            help="Modular ratio for the sustained load (creep-reduced "
                                 "concrete stiffness, so larger than the short-term ratio).")
    loads.markdown("_Short-term_")
    P_el_s, Mx_el_s, My_el_s = _load_set(
        "el_short", "Instantaneous (variable) axial force.",
        "Instantaneous (variable) moment.", elastic_on, mx_default=0.0)
    ns = loads.number_input("Short-term modular ratio n_s = Es/Ec", 1.0, 50.0, 15.0, 0.5,
                            key="ns", disabled=not elastic_on,
                            help="Modular ratio for the instantaneous load.")

    loads.divider()
    loads.markdown("**Extended elastic checks (SLS)**")
    loads.caption("The serviceability action combination (typically "
                  "quasi-permanent) for the cracking-threshold and tension-"
                  "stiffening checks.")
    P_sls, Mx_sls, My_sls = _load_set(
        "sls", "Axial force for the serviceability combination.",
        "Moment for the serviceability combination.", sls_any)
    n_sls = loads.number_input("Effective modular ratio n_eff = Es/Ec", 1.0, 50.0, 15.0, 0.5,
                               key="sls_n", disabled=not sls_any,
                               help="Modular ratio for the serviceability check "
                                    "(creep-adjusted for a sustained combination).")

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
            "pre_Es", "pl_P", "pl_Mx", "pl_My", "el_long_P", "el_long_Mx",
            "el_long_My", "nl", "el_short_P", "el_short_Mx", "el_short_My", "ns",
            "v_min", "v_max", "v_inc", "mode",
            "sls_threshold", "sls_ts", "sls_dur", "sls_fctm", "sls_cover",
            "sls_phi", "sls_P", "sls_Mx", "sls_My", "sls_n"))
    return dict(section=section, concrete=concrete, steel=steel,
                bars=bars, outer=outer, holes=holes, tendons=tendons,
                prestress=prestress, P_pl=P_pl, Mx_pl=Mx_pl, My_pl=My_pl,
                v_min=v_min, v_max=v_max, v_inc=v_inc,
                P_el_l=P_el_l, Mx_el_l=Mx_el_l, My_el_l=My_el_l, nl=nl,
                P_el_s=P_el_s, Mx_el_s=Mx_el_s, My_el_s=My_el_s, ns=ns,
                sls_threshold=sls_threshold, sls_ts=sls_ts, sls_long=sls_long,
                sls_fctm=sls_fctm, sls_cover=sls_cover, sls_phi=sls_phi,
                P_sls=P_sls, Mx_sls=Mx_sls, My_sls=My_sls, n_sls=n_sls,
                mode=mode, extent=extent, signature=tuple(sig))


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def _sweep(v_min, v_max, v_inc):
    """Normalise a (min, max, increment) sweep so it lands exactly on both ends.

    The solver steps ``v_min + i*inc`` for a step count, which could overshoot or
    miss ``v_max`` when the increment does not divide the span. ``v_inc`` is a
    *maximum* increment: a ceiling interval count keeps the step at or below the
    requested resolution while landing exactly on ``v_max`` (no angle outside
    [v_min, v_max]).
    """
    span = max(v_max, v_min) - v_min   # >= 0 (guards a reversed range)
    if span < 1e-9 or v_inc <= 0.0:
        return v_min, v_min, max(v_inc, 1.0)   # a single angle
    n = max(1, math.ceil(span / v_inc))
    return v_min, v_min + span, span / n


def run_analysis(inp):
    out = {}
    if inp["mode"] in ("Plastic", "Both"):
        vlo, vhi, vstep = _sweep(inp["v_min"], inp["v_max"], inp["v_inc"])
        pts = solve_plastic(inp["section"], inp["concrete"], inp["steel"],
                            inp["P_pl"], vlo, vhi, vstep, prestress=inp["prestress"])
        mx = [p.Mx for p in pts]
        my = [p.My for p in pts]
        # Utilisation interpolates the capacity in the applied direction, which is
        # only a closed envelope when the sweep spans the full 360 deg. A partial
        # sweep is an open arc, so report no utilisation rather than a wrap-around
        # interpolation between the arc endpoints.
        closed = (vhi - vlo) >= 360.0 - 1e-6
        util = _radial_util(mx, my, inp["Mx_pl"], inp["My_pl"]) if closed else None
        out["plastic"] = dict(
            mx=mx, my=my,
            max_mx=max(mx), max_my=max(my),
            util=util, closed=closed,
            converged=all(p.converged for p in pts),
            points=[dict(V=p.V, Mx=p.Mx, My=p.My, na_x=p.na_x_intercept,
                         na_y=p.na_y_intercept, eps_c=p.eps_concrete,
                         eps_s=p.eps_steel, eps_cable=p.eps_cable, kappa=p.curvature,
                         comp_force=p.compression_force, lever=p.lever_arm,
                         dx=p.dx, dy=p.dy) for p in pts],
        )
    if inp["mode"] in ("Elastic", "Both"):
        # The elastic analysis ignores the section's tendons, so model each tendon
        # as an ordinary bar by folding them into the bar set for this run.
        sec = inp["section"]
        if inp["tendons"]:
            sec = Section.from_polygon(corners=inp["outer"],
                                       bars_xy_area_mm2=list(inp["bars"]) + list(inp["tendons"]),
                                       holes=inp["holes"])
        r = solve_elastic_combined(sec, inp["P_el_l"], inp["Mx_el_l"], inp["My_el_l"],
                                   inp["nl"], inp["P_el_s"], inp["Mx_el_s"],
                                   inp["My_el_s"], inp["ns"])
        mpa = lambda arr: [s / 1000.0 for s in arr]  # kN/m2 -> MPa
        total = mpa(r.bar_stress_total)
        out["elastic"] = dict(
            total=total, long=mpa(r.bar_stress_long), dif=mpa(r.bar_stress_dif),
            rst1=mpa(r.bar_stress_rst1),
            max_conc=r.max_concrete_compression / 1000.0,
            max_conc_xy=tuple(r.short_term.max_concrete_xy),
            max_conc_point=int(r.max_concrete_point),
            na_x=r.na_x_intercept, na_y=r.na_y_intercept,
            max_steel=max(total) if total else 0.0,
            max_steel_bar=(int(np.argmax(total)) + 1) if total else 0,
            converged=r.converged,
        )
    if inp["sls_threshold"] or inp["sls_ts"]:
        # Fold tendons into the bar set, as the cracked-section model does.
        sec = inp["section"]
        if inp["tendons"]:
            sec = Section.from_polygon(corners=inp["outer"],
                                       bars_xy_area_mm2=list(inp["bars"]) + list(inp["tendons"]),
                                       holes=inp["holes"])
        beta, kt = (0.5, 0.4) if inp["sls_long"] else (1.0, 0.6)
        # Crack width belongs to the tension-stiffening check; without it, run the
        # cracking-threshold decision only (no cover -> no crack width).
        cover = inp["sls_cover"] if inp["sls_ts"] else None
        cr = analyse_cracking(
            sec, inp["P_sls"], inp["Mx_sls"], inp["My_sls"], inp["n_sls"],
            fctm=inp["sls_fctm"], Es=inp["steel"].Es, beta=beta, kt=kt,
            cover=cover,
            bar_diameter=(inp["sls_phi"] if inp["sls_phi"] > 0.0 else None))
        cw = cr.crack
        # Draw the state that actually governs: the fully cracked solve when the
        # section has cracked, otherwise the uncracked (Stage I) solve. Their
        # neutral axes and compression extrema can differ substantially.
        gov = cr.governing
        out["cracking"] = dict(
            cracked=cr.cracked, lambda_cr=cr.lambda_cr, sigma_ct=cr.sigma_ct,
            fctm=cr.fctm, zeta=cr.zeta, long_term=inp["sls_long"],
            show_ts=inp["sls_ts"],
            na_x=gov.na_x_intercept, na_y=gov.na_y_intercept,
            max_conc=gov.max_concrete_compression / 1000.0,
            max_conc_xy=tuple(gov.max_concrete_xy),
            bars_cracked=[s / 1000.0 for s in cr.cracked_state.bar_stress],
            bars_uncracked=[s / 1000.0 for s in cr.uncracked.bar_stress],
            converged=cr.cracked_state.converged,
            crack=(None if cw is None else dict(
                wk=cw.wk, sr_max=cw.sr_max, esm_ecm=cw.esm_ecm, sigma_s=cw.sigma_s,
                rho_p_eff=cw.rho_p_eff, ac_eff=cw.ac_eff, hc_ef=cw.hc_ef,
                phi=cw.phi, gov_bar=cw.gov_bar + 1)),
        )
    return out


def _plastic_halfplane(V_deg, na_x, na_y):
    """Compression half-plane (a*x + b*y + c >= 0) for a plastic NA angle.

    The compression gradient is ``(cos V, sin V)``; the NA is ``a*x + b*y = s_na``
    with ``s_na`` recovered from whichever axis intercept is finite.
    """
    v = math.radians(V_deg)
    a, b = math.cos(v), math.sin(v)
    if math.isfinite(na_x) and abs(a) > 1e-9:
        s_na = na_x * a
    elif math.isfinite(na_y) and abs(b) > 1e-9:
        s_na = na_y * b
    else:
        s_na = 0.0
    return a, b, -s_na


def _elastic_halfplane(na_x, na_y, inside_xy):
    """Compression half-plane from the NA axis intercepts, oriented so the point
    of maximum concrete compression lies on the positive (compression) side."""
    fx, fy = math.isfinite(na_x), math.isfinite(na_y)
    if fx and fy:
        a, b, c = na_y, na_x, -na_x * na_y      # line through (na_x,0) and (0,na_y)
    elif fx:
        a, b, c = 1.0, 0.0, -na_x               # vertical x = na_x
    elif fy:
        a, b, c = 0.0, 1.0, -na_y               # horizontal y = na_y
    else:
        return None
    n = math.hypot(a, b) or 1.0
    a, b, c = a / n, b / n, c / n
    if a * inside_xy[0] + b * inside_xy[1] + c < 0.0:
        a, b, c = -a, -b, -c
    return a, b, c


def _zones(outer, halfplane):
    """Compression and tension zone polygons for a section split by a half-plane."""
    if halfplane is None:
        return None
    a, b, c = halfplane
    comp = geometry.clip_halfplane(outer, a, b, c)
    tens = geometry.clip_halfplane(outer, -a, -b, -c)
    zones = []
    if len(comp) >= 3:
        zones.append((comp.tolist(), viz.COMP_ZONE_FILL, "compression zone"))
    if len(tens) >= 3:
        zones.append((tens.tolist(), viz.TENS_ZONE_FILL, "tension side"))
    return zones or None


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

VIEWS = ["Section", "Stress-Strain diagrams", "Plastic Results", "Elastic Results",
         "Extended elastic (SLS)"]


def section_view(inp):
    """The input geometry: concrete outline, reinforcement and tendons.

    This view is only for verifying the section. Analysis results -- the neutral
    axis, the compression zone, stresses -- are shown in the result views.
    """
    bar_xy = [(b[0], b[1]) for b in inp["bars"]]
    tendon_xy = [(t[0], t[1]) for t in inp["tendons"]]
    st.plotly_chart(viz.section_figure(inp["outer"], inp["holes"], bar_xy,
                                       title="Section", tendons=tendon_xy),
                    use_container_width=True)


def materials_view(inp):
    """Stress-strain diagrams for the chosen materials (live, no Calculate)."""
    c1, c2 = st.columns(2)
    c1.plotly_chart(viz.concrete_curve_figure(inp["concrete"]), use_container_width=True)
    c2.plotly_chart(viz.steel_curve_figure(inp["steel"]), use_container_width=True)
    if inp["prestress"] is not None:
        st.plotly_chart(viz.prestress_curve_figure(inp["prestress"]),
                        use_container_width=True)


def _fmt(v):
    """Format a coordinate, showing an infinite neutral-axis intercept as 'inf'."""
    return "inf" if not math.isfinite(v) else f"{v:.3f}"


def _plastic_table(pts, cable):
    """Per-angle results table, one row per neutral-axis angle."""
    cols = {
        "V (deg)": [round(pt["V"], 1) for pt in pts],
        "Mx (kNm)": [round(pt["Mx"], 1) for pt in pts],
        "My (kNm)": [round(pt["My"], 1) for pt in pts],
        "NA x (m)": [_fmt(pt["na_x"]) for pt in pts],
        "NA y (m)": [_fmt(pt["na_y"]) for pt in pts],
        "eps_c (%)": [round(pt["eps_c"], 2) for pt in pts],
        "eps_s (%)": [round(pt["eps_s"], 2) for pt in pts],
        "kappa (1/m)": [round(pt["kappa"], 4) for pt in pts],
        "Comp (kN)": [round(pt["comp_force"], 0) for pt in pts],
        "L (m)": [round(pt["lever"], 3) for pt in pts],
        "Dx (m)": [round(pt["dx"], 3) for pt in pts],
        "Dy (m)": [round(pt["dy"], 3) for pt in pts],
    }
    if cable:
        cols["eps_cable (%)"] = [round(pt["eps_cable"], 2) for pt in pts]
    return cols


def plastic_view(inp, results):
    """Plastic capacity: metrics, the M-M envelope, an inspectable neutral-axis
    state (compression zone + section diagnostics), and the full per-angle table
    matching the handcalc verification."""
    if not results or "plastic" not in results:
        st.info("Run a Plastic or Both analysis, then press Calculate.")
        return
    p = results["plastic"]
    pts = p["points"]
    m1, m2, m3 = st.columns(3)
    m1.metric("Max Mx", f"{p['max_mx']:.0f} kNm")
    m2.metric("Max My", f"{p['max_my']:.0f} kNm")
    if p["util"] is None:
        m3.metric("Utilisation", "-",
                  help="Only meaningful for a full 0-360 deg sweep; the current "
                       "sweep is a partial arc.")
    else:
        m3.metric("Utilisation", f"{p['util']:.2f}",
                  help="applied / capacity in the load direction")
    st.plotly_chart(
        viz.interaction_figure(p["mx"], p["my"], applied=(inp["Mx_pl"], inp["My_pl"])),
        use_container_width=True)

    default_i = max(range(len(pts)), key=lambda i: pts[i]["Mx"])
    # The sweep length varies with V.min/V.max/V.inc; clamp a stale selection.
    if st.session_state.get("pl_state", 0) >= len(pts):
        st.session_state["pl_state"] = default_i
    sel = st.selectbox("Neutral-axis state", range(len(pts)), index=default_i,
                       format_func=lambda i: f"{i + 1}: V = {pts[i]['V']:.0f} deg",
                       key="pl_state",
                       help="Inspect the section state at one swept neutral-axis angle.")
    pt = pts[sel]
    hp = _plastic_halfplane(pt["V"], pt["na_x"], pt["na_y"])
    na = viz.na_line_at(hp[0], hp[1], hp[2], inp["extent"])
    cL, cR = st.columns([3, 2])
    with cL:
        bar_xy = [(b[0], b[1]) for b in inp["bars"]]
        tendon_xy = [(t[0], t[1]) for t in inp["tendons"]]
        st.plotly_chart(
            viz.section_figure(inp["outer"], inp["holes"], bar_xy, na_line=na,
                               tendons=tendon_xy, zones=_zones(inp["outer"], hp),
                               title=f"Section at V = {pt['V']:.0f} deg"),
            use_container_width=True)
    with cR:
        lines = [
            f"- **Mx / My**: {pt['Mx']:.0f} / {pt['My']:.0f} kNm",
            f"- **Curvature kappa**: {pt['kappa']:.4g} 1/m",
            f"- **Compression force**: {pt['comp_force']:.0f} kN",
            f"- **Lever arm L**: {pt['lever']:.3f} m  (Dx {pt['dx']:.3f}, Dy {pt['dy']:.3f})",
            f"- **Concrete strain**: {pt['eps_c']:.2f} %",
            f"- **Steel strain**: {pt['eps_s']:.2f} %",
            f"- **NA intercepts**: x {_fmt(pt['na_x'])}, y {_fmt(pt['na_y'])} m",
        ]
        if inp["tendons"]:
            lines.insert(6, f"- **Tendon strain**: {pt['eps_cable']:.2f} %")
        st.markdown("\n".join(lines))

    with st.expander("Full results table (per neutral-axis angle)"):
        st.dataframe(_plastic_table(pts, bool(inp["tendons"])),
                     hide_index=True, use_container_width=True)


def elastic_view(inp, results):
    """Cracked-section elastic stresses: peak concrete, neutral axis, the section
    diagnostic and per-bar stresses, matching the handcalc verification."""
    if not results or "elastic" not in results:
        st.info("Run an Elastic or Both analysis, then press Calculate.")
        return
    e = results["elastic"]
    m1, m2 = st.columns(2)
    m1.metric("Max concrete compression", f"{e['max_conc']:.1f} MPa",
              help=f"at concrete corner {e['max_conc_point'] + 1}")
    m2.metric("Max steel tension", f"{e['max_steel']:.1f} MPa",
              help=f"in bar {e['max_steel_bar']}")

    # The neutral axis and the compression/tension zones only make sense when the
    # concrete actually carries compression; a fully tensile case has none.
    has_comp = e["max_conc"] > 0.0
    if has_comp:
        st.caption(f"Neutral-axis intercepts (for concrete stress): "
                   f"x {_fmt(e['na_x'])} m,  y {_fmt(e['na_y'])} m")
    else:
        st.caption("The concrete carries no compression (the section is fully "
                   "cracked in tension); no neutral axis is shown.")

    hp = _elastic_halfplane(e["na_x"], e["na_y"], e["max_conc_xy"]) if has_comp else None
    na = viz.na_line_at(hp[0], hp[1], hp[2], inp["extent"]) if hp else None
    zones = _zones(inp["outer"], hp) if hp else None
    cL, cR = st.columns([3, 2])
    with cL:
        # Tendons are modelled as ordinary bars in the elastic run, in bar order.
        bar_xy = ([(b[0], b[1]) for b in inp["bars"]]
                  + [(t[0], t[1]) for t in inp["tendons"]])
        colors = [viz.BAR_TENSION if s >= 0 else viz.BAR_COMPRESSION
                  for s in e["total"]]
        st.plotly_chart(
            viz.section_figure(inp["outer"], inp["holes"], bar_xy, bar_colors=colors,
                               na_line=na, zones=zones,
                               title="Elastic state (bars: green tension, red compression)"),
            use_container_width=True)
    with cR:
        st.markdown("**Steel stresses (MPa, tension +)**")
        st.dataframe(
            {"Bar": list(range(1, len(e["total"]) + 1)),
             "Total": [round(s, 1) for s in e["total"]],
             "Long": [round(s, 1) for s in e["long"]],
             "Dif": [round(s, 1) for s in e["dif"]],
             "RST1": [round(s, 1) for s in e["rst1"]]},
            hide_index=True, use_container_width=True)
        st.caption("Total = long+short; Long = long-term alone; Dif = total - "
                   "long; RST1 = instantaneous response with the long-term "
                   "concrete stresses neutralised.")


def crack_control_view(inp, results):
    """Extended elastic checks (SLS): the cracking-threshold decision and, when
    enabled, the tension-stiffened state and crack width (EN 1992-1-1)."""
    if not results or "cracking" not in results:
        st.info("Tick **Cracking threshold** and/or **Tension stiffening & crack "
                "width** in Analysis & Result Settings, set the serviceability "
                "load, then press Calculate.")
        return
    c = results["cracking"]
    show_ts = c.get("show_ts", True)
    bars = c["bars_cracked"] if c["cracked"] else c["bars_uncracked"]
    max_steel = max(bars) if bars else 0.0

    if c["cracked"]:
        st.warning(f"**Cracked** - the uncracked concrete tension reaches fctm at "
                   f"a load factor lambda_cr = {c['lambda_cr']:.3f} "
                   f"(= Mcr/M for pure bending), so the section has cracked under "
                   f"this load.")
    else:
        lam = "infinite" if math.isinf(c["lambda_cr"]) else f"{c['lambda_cr']:.2f}"
        st.success(f"**Uncracked** - peak concrete tension {c['sigma_ct']:.2f} MPa "
                   f"< fctm {c['fctm']:.2f} MPa (cracking load factor "
                   f"lambda_cr = {lam}). Stage I stresses govern.")

    cols = st.columns(4 if show_ts else 2)
    cols[0].metric("Cracking factor lambda_cr",
                   "inf" if math.isinf(c["lambda_cr"]) else f"{c['lambda_cr']:.3f}",
                   help="Proportional load factor to first cracking, "
                        "fctm / sigma_ct,I (= Mcr/M in pure bending). < 1 = cracked.")
    cols[1 if not show_ts else 2].metric(
        "Max steel tension", f"{max_steel:.1f} MPa",
        help="Governing bar, in the state that governs (Stage II if cracked).")
    if show_ts:
        cols[1].metric("Tension stiffening zeta", f"{c['zeta']:.3f}",
                       help="EC2 distribution coefficient. 0 = uncracked (Stage I); "
                            "-> 1 deeply cracked (Stage II). Softens the mean response.")
        if c["crack"] is not None:
            cols[3].metric("Crack width wk", f"{c['crack']['wk']:.3f} mm",
                           help="EC2 7.3.4, on the governing tension bar.")
        else:
            cols[3].metric("Crack width wk", "-",
                           help="Not computed (uncracked, or no tension bar).")

    # Section drawing of the cracked state: compression zone, neutral axis and the
    # bars coloured by their cracked-state stress.
    has_comp = c["max_conc"] > 0.0
    hp = _elastic_halfplane(c["na_x"], c["na_y"], c["max_conc_xy"]) if has_comp else None
    na = viz.na_line_at(hp[0], hp[1], hp[2], inp["extent"]) if hp else None
    zones = _zones(inp["outer"], hp) if hp else None
    cL, cR = st.columns([3, 2])
    with cL:
        bar_xy = ([(b[0], b[1]) for b in inp["bars"]]
                  + [(t[0], t[1]) for t in inp["tendons"]])
        colors = [viz.BAR_TENSION if s >= 0 else viz.BAR_COMPRESSION for s in bars]
        title = ("Cracked state (bars: green tension, red compression)"
                 if c["cracked"] else "Uncracked (Stage I) state")
        st.plotly_chart(
            viz.section_figure(inp["outer"], inp["holes"], bar_xy, bar_colors=colors,
                               na_line=na, zones=zones, title=title),
            use_container_width=True)
    with cR:
        if show_ts and c["crack"] is not None:
            cw = c["crack"]
            st.markdown("**Crack width (EC2 7.3.4)**")
            st.dataframe(
                {"Quantity": ["wk (mm)", "sr,max (mm)", "esm - ecm",
                              "sigma_s (MPa)", "rho_p,eff", "hc,ef (m)",
                              "Ac,eff (m2)", "bar dia (mm)", "gov. bar"],
                 "Value": [f"{cw['wk']:.3f}", f"{cw['sr_max']:.1f}",
                           f"{cw['esm_ecm']:.3e}", f"{cw['sigma_s']:.1f}",
                           f"{cw['rho_p_eff']:.4f}", f"{cw['hc_ef']:.3f}",
                           f"{cw['ac_eff']:.4f}", f"{cw['phi']:.1f}",
                           str(cw["gov_bar"])]},
                hide_index=True, use_container_width=True)
            st.caption("Crack width is uniaxial-dominant: the effective tension "
                       "area and crack spacing are taken about the cracked-state "
                       "bending axis on the governing bar.")
        else:
            st.markdown("**Bar stresses (MPa, tension +)**")
            st.dataframe(
                {"Bar": list(range(1, len(bars) + 1)),
                 "Uncracked": [round(s, 1) for s in c["bars_uncracked"]],
                 "Cracked": [round(s, 1) for s in c["bars_cracked"]]},
                hide_index=True, use_container_width=True)

    if show_ts:
        st.caption("Tension stiffening softens the *mean* response (curvature, "
                   "deflection, mean crack width) via zeta; the peak steel stress "
                   "at a crack stays the cracked-section (Stage II) value. A "
                   "nonlinear concrete tension-softening law (continuous partial "
                   "cracking) is a planned future extension.")
    else:
        st.caption("The cracking threshold reports the governing stage: the "
                   "uncracked Stage I stresses when the section has not cracked, "
                   "or the fully cracked Stage II stresses once it has. Enable "
                   "tension stiffening for the mean state and crack width.")


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
    section_view(inp)
elif view == "Stress-Strain diagrams":
    materials_view(inp)
elif view == "Plastic Results":
    plastic_view(inp, results)
elif view == "Elastic Results":
    elastic_view(inp, results)
else:
    crack_control_view(inp, results)
