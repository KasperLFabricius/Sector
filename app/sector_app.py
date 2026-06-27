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
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import viz  # noqa: E402
from sector import codes, geometry, kernels, material_presets as mp, templates  # noqa: E402
from sector.elastic import solve_elastic_combined, transformed_properties  # noqa: E402
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


def _number(box, prefix, field, meta, help_map=None, disabled=False):
    label, lo, hi, step = meta[field]
    return box.number_input(label, float(lo), float(hi), step=float(step),
                            key=f"{prefix}_{field}",
                            help=(help_map or {}).get(field), disabled=disabled)


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


def concrete_panel(box, locked=False):
    """Concrete material: preset and editable parameters (diagram is in the main view).

    ``locked`` (elastic-only mode) disables the parameters that do not affect the
    elastic results: gamma_c and alpha_cc set the design strength fcd, which is a
    plastic-only quantity. fck stays editable -- it feeds the serviceability fctm
    (the Auto button) -- and so does the preset, which prefills fck.
    """
    box.markdown("**Concrete**")
    presets = mp.CONCRETE_PRESETS
    labels = list(presets)
    preset = box.selectbox("Preset", labels, index=labels.index("EN 1992-1-1:2005"),
                           key="conc_preset", help=_PRESET_HELP)
    _prefill("conc", preset, presets)
    curve = presets[preset]["curve"]
    fck = _number(box, "conc", "fck", mp.CONCRETE_FIELD_META, mp.CONCRETE_HELP)
    gamma_c = _number(box, "conc", "gamma_c", mp.CONCRETE_FIELD_META, mp.CONCRETE_HELP,
                      disabled=locked)
    # For a strength-dependent edition (EN 2023), keep alpha_cc tracking fck --
    # recompute it whenever fck changes, while still allowing a manual override
    # in between. Constant-alpha_cc editions just keep the editable value.
    auto = mp.strength_dependent_alpha_cc(preset, fck)
    if auto is not None and st.session_state.get("conc_alpha_fck") != fck:
        st.session_state["conc_alpha_cc"] = auto
        st.session_state["conc_alpha_fck"] = fck
    if auto is None:
        st.session_state.pop("conc_alpha_fck", None)
    alpha_cc = _number(box, "conc", "alpha_cc", mp.CONCRETE_FIELD_META, mp.CONCRETE_HELP,
                       disabled=locked)
    concrete = mp.build_concrete(curve=curve, fck=fck, gamma_c=gamma_c,
                                 alpha_cc=alpha_cc)
    note = "  (alpha_cc tracks fck via eta_cc)" if auto is not None else ""
    box.caption(f"curve {curve},  fcd = {concrete.fcd:.1f} MPa{note}")
    return concrete


def mild_panel(box, locked=False):
    """Mild-steel material: preset and editable parameters (diagram is in the main view).

    A flat form on the general two-yield law: every parameter is always shown
    and live, so the inputs never change with the preset. A preset only prefills
    the values; the named shapes (bilinear, elastic-perfectly-plastic) are
    special cases of the same law.

    ``locked`` (elastic-only mode) disables the stress-strain law parameters,
    which do not affect the elastic results -- except ``Es``, which sets the
    crack-width mean strain and so stays editable.
    """
    box.markdown("**Mild steel**")
    presets = mp.MILD_PRESETS
    labels = list(presets)
    preset = box.selectbox("Preset", labels, index=labels.index("EN 1992-1-1:2005"),
                           key="mild_preset", help=_PRESET_HELP)
    _prefill("mild", preset, presets)
    curve = presets[preset]["curve"]
    vals = {f: _number(box, "mild", f, mp.MILD_FIELD_META, mp.MILD_HELP,
                       disabled=locked and f != "Es")
            for f in mp.MILD_FIELD_META}
    _clamp_eut(box, vals, mp.MILD_FIELDS_BY_CURVE[curve])
    steel = _safe_build(box, mp.build_mild, curve, vals)
    box.caption(f"fyd = {steel.fytk / vals['gamma_y']:.0f} MPa,  "
                f"Es = {vals['Es'] / 1000.0:.0f} GPa")
    return steel


def prestress_panel(box, locked=False):
    """Prestressing-steel material: preset and editable parameters (diagram is in the main view).

    A flat form: the user-defined and Eurocode presets build the general
    two-yield law, so every parameter is live. The built-in characteristic
    curves are fixed shapes -- only the prestrain (and yield factor) apply.

    ``locked`` (elastic-only mode) disables every parameter: in the elastic
    analysis tendons are carried as ordinary bars at the modular ratio, so the
    prestress stress-strain law has no effect on the elastic results.
    """
    box.markdown("**Prestressing steel**")
    presets = mp.PRESTRESS_PRESETS
    labels = list(presets)
    preset = box.selectbox("Preset", labels, index=labels.index("EN 1992-1-1:2005"),
                           key="pre_preset", help=_PRESET_HELP)
    _prefill("pre", preset, presets)
    curve = presets[preset]["curve"]
    vals = {f: _number(box, "pre", f, mp.PRESTRESS_FIELD_META, mp.PRESTRESS_HELP,
                       disabled=locked)
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

def _rep_bar_dia(bars):
    """Representative bar diameter (mm) from the bar areas (mm^2); 0 if none.

    The largest bar is taken as representative for the crack-spacing term.
    """
    if not bars:
        return 0.0
    return math.sqrt(4.0 * max(b[2] for b in bars) / math.pi)


# Editable cross-section point tables (the section's source of truth).
_CORNER_COLS = ["x (m)", "y (m)"]
_REBAR_COLS = ["x (m)", "y (m)", "area (mm2)"]


def _corners_df(pts):
    """Concrete-corner DataFrame ``(x, y)`` from a list of points."""
    return pd.DataFrame([{"x (m)": float(p[0]), "y (m)": float(p[1])} for p in pts],
                        columns=_CORNER_COLS)


def _rebar_df(pts):
    """Reinforcement DataFrame ``(x, y, area)`` from a list of (x, y, area)."""
    return pd.DataFrame(
        [{"x (m)": float(p[0]), "y (m)": float(p[1]), "area (mm2)": float(p[2])}
         for p in pts], columns=_REBAR_COLS)


def _pts_from_df(df, cols):
    """Rows of ``df`` as tuples, skipping any with a blank/NaN cell."""
    out = []
    for _, row in df.iterrows():
        vals = [row.get(c) for c in cols]
        if any(pd.isna(v) for v in vals):
            continue
        out.append(tuple(float(v) for v in vals))
    return out


def _renumber(df, cols, start):
    """Editor base from ``df`` with a leading ``ID`` column numbered from
    ``start`` -- but only on complete rows. Blank/NaN rows (which the analysis and
    the plot skip) get no ID, so the table IDs always match the plotted/result
    numbering."""
    rows = df[cols].reset_index(drop=True)
    ids, n = [], start
    for _, row in rows.iterrows():
        if any(pd.isna(row[c]) for c in cols):
            ids.append(pd.NA)
        else:
            ids.append(n)
            n += 1
    out = rows.copy()
    out.insert(0, "ID", pd.array(ids, dtype="Int64"))
    return out


def _point_editor(box, base_key, ed_key, cols, id_start):
    """Render an editable point table with a read-only, plot-matching ID column.

    Edits are committed back to the base each run (and the widget state cleared),
    so the IDs renumber when rows are added or removed and tendon IDs follow the
    live bar count. Returns the valid points (NaN/blank rows skipped).
    """
    edited = box.data_editor(
        st.session_state[base_key], key=ed_key, num_rows="dynamic",
        use_container_width=True, hide_index=True,
        column_config={"ID": st.column_config.NumberColumn(
            "ID", disabled=True, help="Matches the number drawn on the plots.")})
    pts = _pts_from_df(edited, cols)
    st.session_state[base_key] = _renumber(edited, cols, id_start)
    st.session_state.pop(ed_key, None)
    return pts


def build_inputs():
    """Render the sidebar dropdown panels and return the section, materials and
    loads. Panels mirror the BriCoS layout: About, Analysis & Result Settings,
    Section, Material Parameters, Loads."""
    s = st.sidebar

    with s.expander("About", expanded=False):
        st.markdown(
            "**Sector** analyses reinforced-concrete (and optionally "
            "prestressed) cross-sections, returning the plastic bending "
            "capacity and the cracked-section elastic stresses. The elastic "
            "result also reports serviceability checks (cracking threshold, "
            "section properties, and optional tension stiffening and crack "
            "width) on the long-term load.")
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

    # ---- Cross-section points (always live; the source of truth) ----
    # The Quick Section above only prefills these on demand (the Load button), so a
    # later Quick Section tweak never silently discards manual point edits. The
    # void (e.g. a box cavity) is an editable corner table too; a single void is
    # supported here (multiple voids are a future extension).
    qs_outer = [(float(p[0]), float(p[1])) for p in outer]
    qs_hole = ([(float(p[0]), float(p[1])) for p in holes[0]] if holes else [])
    qs_bars = [(float(p[0]), float(p[1]), float(p[2])) for p in bars]
    qs_tendons = [(float(p[0]), float(p[1]), float(p[2])) for p in (tendons or [])]
    load_qs = sec.button("Load Quick Section into points", key="load_qs",
                         use_container_width=True,
                         help="Overwrite the editable point tables below with the "
                              "Quick Section above.")
    if "pts_init" not in st.session_state or load_qs:
        st.session_state["corners_base"] = _renumber(_corners_df(qs_outer),
                                                     _CORNER_COLS, 1)
        st.session_state["hole_base"] = _renumber(_corners_df(qs_hole), _CORNER_COLS,
                                                  len(qs_outer) + 1)
        st.session_state["bars_base"] = _renumber(_rebar_df(qs_bars), _REBAR_COLS, 1)
        st.session_state["tendons_base"] = _renumber(_rebar_df(qs_tendons),
                                                     _REBAR_COLS, len(qs_bars) + 1)
        for k in ("ed_corners", "ed_hole", "ed_bars", "ed_tendons"):
            st.session_state.pop(k, None)
        st.session_state["pts_init"] = True
    # Migrate a session that predates the void table: seed hole_base (from any old
    # holes state) without disturbing the other tables, so it never KeyErrors.
    if "hole_base" not in st.session_state:
        old = st.session_state.get("holes_pts") or []
        st.session_state["hole_base"] = _renumber(
            _corners_df(old[0] if old else []), _CORNER_COLS, 1)

    sec.markdown("**Cross-section points** (the analysis uses these)")
    sec.caption("Concrete corners define the outline (3 or more, in order); the "
                "void is an optional inner ring (3 or more corners, else ignored). "
                "Bars and tendons are points with an area (mm2). The ID column "
                "matches the numbers drawn on the plots. Edit freely; use Load "
                "Quick Section to refill from the template above.")
    sec.markdown("_Concrete corners_")
    outer = _point_editor(sec, "corners_base", "ed_corners", _CORNER_COLS, 1)
    if len(outer) < 3:
        sec.error("Need at least 3 concrete corners; using the Quick Section outline.")
        outer = qs_outer
    sec.markdown("_Concrete void (hole)_")
    # Void corner IDs continue after the outer corners (the concrete-vertex order).
    hole_ring = _point_editor(sec, "hole_base", "ed_hole", _CORNER_COLS, len(outer) + 1)
    holes = [hole_ring] if len(hole_ring) >= 3 else []
    sec.markdown("_Reinforcing bars_")
    bars = _point_editor(sec, "bars_base", "ed_bars", _REBAR_COLS, 1)
    tendons = []
    if use_pre:
        sec.markdown("_Tendons_")
        # Tendon IDs continue after the bars, matching the plot numbering.
        tendons = _point_editor(sec, "tendons_base", "ed_tendons", _REBAR_COLS,
                                len(bars) + 1)

    # In elastic-only mode the stress-strain laws do not enter the analysis (it is
    # linear: steel via the modular ratio, concrete linear in compression with no
    # tension), so lock the parameters that have no elastic effect. fck (it feeds
    # the serviceability fctm) and the steel modulus Es (the crack-width mean
    # strain) still matter, so they stay editable.
    lock_mats = mode == "Elastic"
    mat = s.expander("Material Parameters", expanded=False)
    if lock_mats:
        mat.caption("Elastic-only mode: the stress-strain laws do not affect the "
                    "elastic results and are locked. Only fck (feeds fctm) and the "
                    "steel modulus Es (crack width) stay editable; switch to "
                    "Plastic or Both to edit the full laws.")
    concrete = concrete_panel(mat, locked=lock_mats)
    mat.divider()
    steel = mild_panel(mat, locked=lock_mats)
    if use_pre:
        mat.divider()
        prestress = prestress_panel(mat, locked=lock_mats)

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
                                10.0, key=f"{prefix}_Mx", disabled=not active,
                                help=f"{m_help} Bending moment about the x-axis "
                                     "(its stress varies with y).")
        My = loads.number_input("Applied My (kNm)", -100000.0, 100000.0, 0.0, 10.0,
                                key=f"{prefix}_My", disabled=not active,
                                help="Bending moment about the y-axis (its stress "
                                     "varies with x); biaxial bending.")
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
    loads.caption("Run on the long-term (quasi-permanent) load above. The plain "
                  "elastic stresses are unchanged (cracked section, zero concrete "
                  "tension); these add the cracking threshold and section "
                  "properties, and -- when enabled -- tension stiffening and "
                  "crack width.")
    _fctm_ec = round(codes.fctm(concrete.fck), 3)
    st.session_state.setdefault("sls_fctm", _fctm_ec)
    if loads.button(f"Auto fctm (EC2: {_fctm_ec:.2f} MPa)", key="sls_fctm_auto",
                    disabled=not elastic_on, use_container_width=True,
                    help="Set fctm = 0.30*fck^(2/3) (EC2 Table 3.1) for the current "
                         "concrete grade. Press again after changing the grade."):
        st.session_state["sls_fctm"] = _fctm_ec
    sls_fctm = loads.number_input("Concrete tensile strength fctm (MPa)", 0.0, 10.0,
                                  step=0.1, key="sls_fctm", disabled=not elastic_on,
                                  help="Mean axial tensile strength for the cracking "
                                       "check (fct,eff). Use Auto for the EC2 value.")
    sls_ts = loads.checkbox("Tension stiffening & crack width", value=False,
                            key="sls_ts", disabled=not elastic_on,
                            help="Account for the intact concrete between cracks: "
                                 "the tension-stiffened mean state (zeta) and the "
                                 "crack width wk.")
    _cw_on = elastic_on and sls_ts
    sls_long = loads.radio("Load duration",
                           ["Long-term (sustained)", "Short-term"], key="sls_dur",
                           disabled=not _cw_on,
                           help="Tension-stiffening factors: long-term beta = 0.5, "
                                "kt = 0.4; short-term beta = 1.0, kt = 0.6."
                           ) == "Long-term (sustained)"
    # ``cov`` is the cover to the bar centres for the current shape (the circular
    # shape stores it under a different widget key, so use the local value, not a
    # fixed session key). The clear cover to the surface is that minus phi/2.
    _auto_cover = max(round(cov * 1000.0 - _rep_bar_dia(bars) / 2.0, 1), 0.0)
    st.session_state.setdefault("sls_cover", _auto_cover)
    if loads.button(f"Auto cover (c - phi/2 = {_auto_cover:.1f} mm)",
                    key="sls_cover_auto", disabled=not _cw_on, use_container_width=True,
                    help="Clear cover to the bar surface, from the section cover to "
                         "centre minus half the representative bar diameter."):
        st.session_state["sls_cover"] = _auto_cover
    sls_cover = loads.number_input("Cover to bar surface c (mm)", 0.0, 200.0, step=1.0,
                                   key="sls_cover", disabled=not _cw_on,
                                   help="Clear cover to the governing bar, for the "
                                        "crack spacing sr,max.")
    sls_phi = loads.number_input("Bar diameter (mm, 0 = auto)", 0.0, 60.0, 0.0, 1.0,
                                 key="sls_phi", disabled=not _cw_on,
                                 help="Governing bar diameter for sr,max; 0 derives "
                                      "it from the bar area.")

    section = Section.from_polygon(corners=outer, bars_xy_area_mm2=bars,
                                   tendons_xy_area_mm2=tendons, holes=holes)
    if outer:
        xs = [p[0] for p in outer]
        ys = [p[1] for p in outer]
        extent = 0.75 * max(max(xs) - min(xs), max(ys) - min(ys), 1e-6)
    else:
        extent = 1.0
    # The geometry signature is the point tables themselves (the source of truth),
    # so editing a point marks the results stale; Quick Section inputs do not, as
    # they only prefill on demand.
    geom_sig = (tuple(outer), tuple(bars), tuple(tendons),
                tuple(tuple(r) for r in holes))
    sig = geom_sig + tuple(st.session_state.get(k) for k in
           ("conc_preset", "conc_fck", "conc_gamma_c", "conc_alpha_cc",
            "mild_preset", "mild_fytk", "mild_fyck", "mild_futk", "mild_eut",
            "mild_gamma_y", "mild_gamma_u", "mild_gamma_E", "mild_k",
            "mild_ey0t", "mild_ey0c", "mild_Es", "use_pre", "pre_preset",
            "pre_IS", "pre_fytk", "pre_futk", "pre_eut", "pre_gamma_y",
            "pre_gamma_u", "pre_gamma_E", "pre_k", "pre_ey0t", "pre_Es",
            "pl_P", "pl_Mx", "pl_My", "el_long_P", "el_long_Mx", "el_long_My",
            "nl", "el_short_P", "el_short_Mx", "el_short_My", "ns",
            "v_min", "v_max", "v_inc", "mode",
            "sls_ts", "sls_dur", "sls_fctm", "sls_cover", "sls_phi"))
    return dict(section=section, concrete=concrete, steel=steel,
                bars=bars, outer=outer, holes=holes, tendons=tendons,
                prestress=prestress, P_pl=P_pl, Mx_pl=Mx_pl, My_pl=My_pl,
                v_min=v_min, v_max=v_max, v_inc=v_inc,
                P_el_l=P_el_l, Mx_el_l=Mx_el_l, My_el_l=My_el_l, nl=nl,
                P_el_s=P_el_s, Mx_el_s=Mx_el_s, My_el_s=My_el_s, ns=ns,
                sls_ts=sls_ts, sls_long=sls_long, sls_fctm=sls_fctm,
                sls_cover=sls_cover, sls_phi=sls_phi,
                mode=mode, extent=extent, signature=sig)


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


def _props_dict(p):
    """Flatten SectionProperties to a plain dict for the results payload."""
    return dict(area=p.area, cx=p.cx, cy=p.cy, Ix=p.Ix, Iy=p.Iy, Ixy=p.Ixy)


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

        # Extended serviceability checks on the long-term (quasi-permanent) load,
        # at the same modular ratio nl: the cracking threshold and the cracked /
        # uncracked section properties always, plus tension stiffening and crack
        # width when requested. Crack width needs the cover, so it is only run
        # when the tension-stiffening check is on.
        beta, kt = (0.5, 0.4) if inp["sls_long"] else (1.0, 0.6)
        cover = inp["sls_cover"] if inp["sls_ts"] else None
        cr = analyse_cracking(
            sec, inp["P_el_l"], inp["Mx_el_l"], inp["My_el_l"], inp["nl"],
            fctm=inp["sls_fctm"], Es=inp["steel"].Es, beta=beta, kt=kt,
            cover=cover,
            bar_diameter=(inp["sls_phi"] if inp["sls_phi"] > 0.0 else None))
        props_un = transformed_properties(sec, inp["nl"], cracked=False)
        props_cr = (transformed_properties(
            sec, inp["nl"], eps0=cr.cracked_state.eps0, kx=cr.cracked_state.kx,
            ky=cr.cracked_state.ky, cracked=True) if cr.cracked else None)
        cw = cr.crack
        out["elastic"].update(
            cracked=cr.cracked, lambda_cr=cr.lambda_cr, sigma_ct=cr.sigma_ct,
            fctm=cr.fctm, zeta=cr.zeta, show_ts=inp["sls_ts"],
            long_term=inp["sls_long"],
            props_un=_props_dict(props_un),
            props_cr=(_props_dict(props_cr) if props_cr is not None else None),
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

VIEWS = ["Section", "Stress-Strain diagrams", "Plastic Results", "Elastic Results"]


def section_view(inp):
    """The input geometry: concrete outline, reinforcement and tendons.

    This view is only for verifying the section. Analysis results -- the neutral
    axis, the compression zone, stresses -- are shown in the result views.
    """
    bar_xy = [(b[0], b[1]) for b in inp["bars"]]
    tendon_xy = [(t[0], t[1]) for t in inp["tendons"]]
    st.plotly_chart(viz.section_figure(inp["outer"], inp["holes"], bar_xy,
                                       title="Section", tendons=tendon_xy,
                                       show_labels=True, label_scale=inp["label_scale"],
                                       label_min_gap=inp["label_min_gap"]),
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
                               title=f"Section at V = {pt['V']:.0f} deg",
                               show_labels=True, label_scale=inp["label_scale"],
                               label_min_gap=inp["label_min_gap"]),
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
        # Size the table to all rows so the page scrolls, not the table itself.
        st.dataframe(_plastic_table(pts, bool(inp["tendons"])),
                     hide_index=True, use_container_width=True,
                     height=35 * (len(pts) + 1) + 3)


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
    # Tendons fold into the bar set for the solve, but are drawn as diamonds (bars
    # as circles), each coloured by its stress sign -- consistent with the other
    # views. The stress list runs bars first, then tendons.
    nb = len(inp["bars"])
    bar_xy = [(b[0], b[1]) for b in inp["bars"]]
    tendon_xy = [(t[0], t[1]) for t in inp["tendons"]]
    sign = lambda s: viz.BAR_TENSION if s >= 0 else viz.BAR_COMPRESSION
    bar_colors = [sign(s) for s in e["total"][:nb]]
    tendon_colors = [sign(s) for s in e["total"][nb:]]
    st.plotly_chart(
        viz.section_figure(inp["outer"], inp["holes"], bar_xy, bar_colors=bar_colors,
                           tendons=tendon_xy, tendon_colors=tendon_colors,
                           na_line=na, zones=zones, show_labels=True,
                           label_scale=inp["label_scale"],
                           label_min_gap=inp["label_min_gap"],
                           title="Elastic state (green tension, red compression)"),
        use_container_width=True)

    # The per-bar stress table sits below the figure, sized to all rows.
    st.markdown("**Steel stresses (MPa, tension +)**")
    n = len(e["total"])
    st.dataframe(
        {"Bar": list(range(1, n + 1)),
         "Total": [round(s, 1) for s in e["total"]],
         "Long": [round(s, 1) for s in e["long"]],
         "Dif": [round(s, 1) for s in e["dif"]],
         "RST1": [round(s, 1) for s in e["rst1"]]},
        hide_index=True, use_container_width=True, height=35 * (n + 1) + 3)
    st.caption("Total = long+short; Long = long-term alone; Dif = total - "
               "long; RST1 = instantaneous response with the long-term "
               "concrete stresses neutralised.")

    _elastic_sls_section(inp, e)


def _elastic_sls_section(inp, e):
    """Serviceability sub-report inside the elastic view: the cracking threshold
    and transformed section properties (always), plus tension stiffening and
    crack width when enabled. All on the long-term (quasi-permanent) load."""
    if "cracked" not in e:
        return
    show_ts = e.get("show_ts", False)
    st.divider()
    st.markdown("#### Serviceability checks (long-term / quasi-permanent)")
    if e["cracked"]:
        st.warning(f"**Cracked** under the long-term load - the uncracked concrete "
                   f"tension reaches fctm at a load factor lambda_cr = "
                   f"{e['lambda_cr']:.3f} (= Mcr/M for pure bending).")
    else:
        lam = "infinite" if math.isinf(e["lambda_cr"]) else f"{e['lambda_cr']:.2f}"
        st.success(f"**Uncracked** under the long-term load - peak concrete tension "
                   f"{e['sigma_ct']:.2f} MPa < fctm {e['fctm']:.2f} MPa "
                   f"(lambda_cr = {lam}).")

    mcols = st.columns(3 if show_ts else 1)
    mcols[0].metric("Cracking factor lambda_cr",
                    "inf" if math.isinf(e["lambda_cr"]) else f"{e['lambda_cr']:.3f}",
                    help="Proportional load factor to first cracking, "
                         "fctm / sigma_ct,I (= Mcr/M in pure bending). < 1 = cracked.")
    if show_ts:
        mcols[1].metric("Tension stiffening zeta", f"{e['zeta']:.3f}",
                        help="EC2 distribution coefficient. 0 = uncracked; -> 1 "
                             "deeply cracked. Softens the mean response.")
        wk = e["crack"]["wk"] if e["crack"] else None
        mcols[2].metric("Crack width wk", f"{wk:.3f} mm" if wk is not None else "-",
                        help=("EC2 7.3.4, on the governing tension bar." if wk
                              is not None else "Not computed (uncracked or no "
                              "tension bar)."))

    pL, pR = st.columns(2)
    with pL:
        st.markdown("**Transformed section properties (at n_l)**")
        un = e["props_un"]
        cr = e.get("props_cr")
        rows = ["Area A (m2)", "Centroid x (m)", "Centroid y (m)",
                "Ix about x-axis (m4)", "Iy about y-axis (m4)", "Ixy (m4)"]
        keys = ["area", "cx", "cy", "Ix", "Iy", "Ixy"]
        data = {"Property": rows, "Uncracked": [f"{un[k]:.4g}" for k in keys]}
        if cr is not None:
            data["Cracked"] = [f"{cr[k]:.4g}" for k in keys]
        st.dataframe(data, hide_index=True, use_container_width=True)
        st.caption("Transformed (n_l-weighted) properties about the section "
                   "centroid; the cracked column drops the concrete in tension. "
                   "Ix resists Mx (bending about the x-axis).")
    with pR:
        if show_ts and e["crack"] is not None:
            cw = e["crack"]
            st.markdown("**Crack width (EC2 7.3.4)**")
            st.dataframe(
                {"Quantity": ["wk (mm)", "sr,max (mm)", "esm - ecm", "sigma_s (MPa)",
                              "rho_p,eff", "hc,ef (m)", "Ac,eff (m2)", "bar dia (mm)",
                              "gov. bar"],
                 "Value": [f"{cw['wk']:.3f}", f"{cw['sr_max']:.1f}",
                           f"{cw['esm_ecm']:.3e}", f"{cw['sigma_s']:.1f}",
                           f"{cw['rho_p_eff']:.4f}", f"{cw['hc_ef']:.3f}",
                           f"{cw['ac_eff']:.4f}", f"{cw['phi']:.1f}",
                           str(cw["gov_bar"])]},
                hide_index=True, use_container_width=True)
            st.caption("Uniaxial-dominant (effective area / crack spacing about the "
                       "bending axis). Tension stiffening softens the mean response, "
                       "not the peak crack stress.")
        elif show_ts:
            st.info("No crack width: uncracked under the long-term load, or no bar "
                    "in tension.")


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

inp = build_inputs()

# Plot-label controls sit inline in the main viewport, directly above the View
# dropdown (not tucked inside a submenu). They only affect the drawings, so they
# are not part of the result-staleness signature.
st.markdown("**Plot labels**")
lc1, lc2 = st.columns(2)
inp["label_scale"] = lc1.number_input(
    "Label size", 0.5, 3.0, 1.0, 0.1, key="label_scale",
    help="Scales the corner / bar / tendon number labels on the section "
         "drawings.")
inp["label_min_gap"] = lc2.number_input(
    "Label spacing (hide threshold)", 0.0, 0.5, 0.04, 0.01, key="label_min_gap",
    help="Labels closer together than this fraction of the section size are "
         "hidden to avoid overlap. Lower shows more (0 shows every label); "
         "raise it for dense outlines like a circular section.")

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
else:
    elastic_view(inp, results)
