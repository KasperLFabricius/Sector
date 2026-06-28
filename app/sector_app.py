"""Sector - reinforced-concrete cross-section analysis (Streamlit interface).

Define a section by its shape and reinforcement, choose elastic and/or plastic
analysis, then press Calculate to review the stresses and the ultimate capacity.
"""

from __future__ import annotations

import dataclasses
import json
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

import project_io  # noqa: E402
import viz  # noqa: E402
from sector import codes, geometry, kernels, material_presets as mp, templates  # noqa: E402
from sector.elastic import solve_elastic_combined, transformed_properties  # noqa: E402
from sector.plastic import solve_plastic  # noqa: E402
from sector.section import Section  # noqa: E402
from sector.serviceability import analyse_cracking, crack_width  # noqa: E402

APP_VERSION = "0.1.0"
ROOT = pathlib.Path(__file__).resolve().parent.parent

# EC2 7.11 bond coefficient k1 by bar surface (cannot be inferred from geometry).
_BOND_K1 = {"Ribbed / high bond (k1 = 0.8)": 0.8, "Plain round (k1 = 1.6)": 1.6}

# Crack-width code edition -> whether the DK NA crack-spacing rules apply (cover-
# dependent k3, and the (h-x)/3 effective-height term only for slabs/prestressed).
_CRACK_CODES = {"EN 1992-1-1:2005": False, "DS/EN 1992-1-1 + DK NA": True}

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

# Default material edition (Danish practice: DS/EN with the DK National Annex).
_DEFAULT_PRESET = "DS/EN 1992-1-1:2005 + DK NA:2024"


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


def _safe_build(box, builder, curve, vals, **extra):
    """Build a material from the flat parameter set, surviving degenerate input.

    A flat form lets the user enter values the active curve cannot accept (e.g. a
    zero rupture stress on a hardening curve). Rather than break the whole app,
    show a notice and retry with the offending stresses nudged just above zero so
    the diagram and the analysis still render. ``extra`` carries non-field options
    (e.g. ``active_in_compression``) straight through to the builder.
    """
    try:
        return builder(curve=curve, **vals, **extra)
    except ValueError as exc:
        box.warning(f"Adjusted for this curve: {exc}")
        v = dict(vals)
        for f in ("fytk", "futk"):
            if v.get(f, 1.0) <= 0.0:
                v[f] = 1.0
        return builder(curve=curve, **v, **extra)


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


def concrete_panel(box, locked=False, lock_elastic=False):
    """Concrete material: preset and editable parameters (diagram is in the main view).

    ``locked`` (elastic-only mode) disables the parameters that do not affect the
    elastic results: gamma_c and alpha_cc set the design strength fcd, which is a
    plastic-only quantity. fck stays editable -- it feeds the serviceability fctm
    (the Auto button) -- and so does the preset, which prefills fck.
    ``lock_elastic`` (plastic-only mode) disables fctm and Ec, which only affect
    the elastic/SLS results.
    """
    box.markdown("**Concrete**")
    presets = mp.CONCRETE_PRESETS
    labels = list(presets)
    preset = box.selectbox("Preset", labels, index=labels.index(_DEFAULT_PRESET),
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

    # Concrete strain limits eps_c2, eps_cu2 and the parabola exponent n shape the
    # ULS compression curve (plastic-only). Making them editable lets grades above
    # C50/60 -- where EC2 Table 3.1 makes them strength-dependent -- be modelled;
    # they apply to the parabola-rectangle (curve 2). The Auto button fills the
    # Table 3.1 values for the current grade (constant up to C50/60).
    parabola = curve == 2
    strain_lock = locked or not parabola
    a_ec2 = round(codes.eps_c2(fck) * 1000.0, 2)
    a_ecu2 = round(codes.eps_cu2(fck) * 1000.0, 2)
    a_n = round(codes.n_exponent(fck), 3)
    if box.button(f"Auto eps/n (EC2: {a_ec2:.2f}/{a_ecu2:.2f} permille, n={a_n:.2f})",
                  key="conc_strain_auto", use_container_width=True, disabled=strain_lock,
                  help="Set eps_c2, eps_cu2 and n from EC2 Table 3.1 for the current "
                       "grade (strength-dependent above C50/60). Press again after "
                       "changing fck."):
        st.session_state["conc_eps_c2"] = a_ec2
        st.session_state["conc_eps_cu2"] = a_ecu2
        st.session_state["conc_n"] = a_n
    eps_c2 = _number(box, "conc", "eps_c2", mp.CONCRETE_FIELD_META, mp.CONCRETE_HELP,
                     disabled=strain_lock)
    eps_cu2 = _number(box, "conc", "eps_cu2", mp.CONCRETE_FIELD_META, mp.CONCRETE_HELP,
                      disabled=strain_lock)
    n = _number(box, "conc", "n", mp.CONCRETE_FIELD_META, mp.CONCRETE_HELP,
                disabled=strain_lock)
    # The two strains are independent inputs, so the form allows eps_cu2 < eps_c2
    # (the law would reject it). Cross-validate here and lift eps_cu2 to the peak
    # strain so a half-finished edit shows a warning instead of aborting the run.
    if eps_cu2 < eps_c2:
        box.warning("eps_cu2 must be at least eps_c2 (the peak strain); using that "
                    "value for the diagram and analysis.")
        eps_cu2 = eps_c2

    concrete = mp.build_concrete(curve=curve, fck=fck, gamma_c=gamma_c,
                                 alpha_cc=alpha_cc, eps_c2=eps_c2, eps_cu2=eps_cu2, n=n)
    note = "  (alpha_cc tracks fck via eta_cc)" if auto is not None else ""
    box.caption(f"curve {curve},  fcd = {concrete.fcd:.1f} MPa,  "
                f"eps_cu2 = {concrete.eps_cu2 * 1000.0:.2f} permille{note}")

    # Mean tensile strength fctm feeds the serviceability cracking check. It lives
    # with the concrete (not the loads); the Auto button refreshes it from the
    # current grade because the number_input persists across a grade change.
    fctm_ec = round(codes.fctm(fck), 3)
    st.session_state.setdefault("sls_fctm", fctm_ec)
    if box.button(f"Auto fctm (EC2: {fctm_ec:.2f} MPa)", key="sls_fctm_auto",
                  use_container_width=True, disabled=lock_elastic,
                  help="Set fctm = 0.30*fck^(2/3) (EC2 Table 3.1) for the current "
                       "concrete grade. Press again after changing the grade."):
        st.session_state["sls_fctm"] = fctm_ec
    fctm_val = box.number_input("Tensile strength fctm (MPa)", 0.0, 10.0, step=0.1,
                                key="sls_fctm", disabled=lock_elastic,
                                help="Mean axial tensile strength for the cracking "
                                     "check (fct,eff). Use Auto for the EC2 value.")

    # Elastic modulus Ec: only used by the elastic analysis, to derive the modular
    # ratios n = Es/Ec. The Auto button sets the EC2 secant modulus for the grade.
    ecm_gpa = round(codes.ecm(fck) / 1000.0, 1)
    st.session_state.setdefault("conc_Ec", ecm_gpa)
    if box.button(f"Auto Ec (EC2: {ecm_gpa:.1f} GPa)", key="conc_Ec_auto",
                  use_container_width=True, disabled=lock_elastic,
                  help="Set Ec = Ecm = 22*(fcm/10)^0.3 GPa (EC2 Table 3.1) for the "
                       "current grade. Press again after changing the grade."):
        st.session_state["conc_Ec"] = ecm_gpa
    Ec = box.number_input("Elastic modulus Ec (GPa)", 1.0, 100.0, step=0.5,
                          key="conc_Ec", disabled=lock_elastic,
                          help="Concrete secant modulus, used only by the elastic "
                               "analysis to auto-derive the modular ratios n = Es/Ec.")
    return concrete, fctm_val, Ec


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
    preset = box.selectbox("Preset", labels, index=labels.index(_DEFAULT_PRESET),
                           key="mild_preset", help=_PRESET_HELP)
    # Selecting a preset whose compression yield is active (fyck > 0) turns the
    # "Active in compression" toggle on, so the preset's compression is not
    # silently dropped. (Checked before _prefill, which updates the change marker.)
    if (st.session_state.get("mild_prev") != preset
            and presets[preset].get("fyck", 0.0) > 0.0):
        st.session_state["mild_active_comp"] = True
    _prefill("mild", preset, presets)
    curve = presets[preset]["curve"]
    st.session_state.setdefault("mild_active_comp", True)
    active_comp = box.checkbox(
        "Active in compression", key="mild_active_comp", disabled=locked,
        help="On: the bar carries compression and its compression-side inputs "
             "(fyck, ey0c) are used. Off: the reinforcement is tension-only "
             "(no compression), for every curve type. This applies to the plastic "
             "(ultimate) capacity; the elastic/SLS analysis is linear and treats "
             "the bars in both directions.")
    # The compression-side inputs only matter when compression is active.
    comp_only = {"fyck", "ey0c"}
    vals = {f: _number(box, "mild", f, mp.MILD_FIELD_META, mp.MILD_HELP,
                       disabled=(locked and f != "Es")
                       or (f in comp_only and not active_comp))
            for f in mp.MILD_FIELD_META}
    _clamp_eut(box, vals, mp.MILD_FIELDS_BY_CURVE[curve])
    steel = _safe_build(box, mp.build_mild, curve, vals,
                        active_in_compression=active_comp)
    comp = "active" if active_comp else "tension-only"
    box.caption(f"fyd = {steel.fytk / vals['gamma_y']:.0f} MPa,  "
                f"Es = {vals['Es'] / 1000.0:.0f} GPa,  compression {comp}")
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

# Editable cross-section point tables (the section's source of truth). Coordinates
# are entered and drawn in millimetres; the engine works in metres, so the points
# are converted at the table/plot boundary.
_MM = 1000.0   # millimetres per metre
_CORNER_COLS = ["x (mm)", "y (mm)"]
_REBAR_COLS = ["x (mm)", "y (mm)", "area (mm2)"]


def _pts_to_m(pts):
    """Convert (x, y[, area]) points from mm to m for the engine (area unchanged)."""
    return [(p[0] / _MM, p[1] / _MM) + tuple(p[2:]) for p in pts]


def _pts_to_mm(pts):
    """Convert (x, y[, area]) points from m to mm for the tables (area unchanged)."""
    return [(p[0] * _MM, p[1] * _MM) + tuple(p[2:]) for p in pts]


def _corners_df(pts):
    """Concrete-corner DataFrame ``(x, y)`` in mm from a list of mm points.

    The columns are forced to ``float64`` (even when empty) so the editor always
    renders numeric inputs -- an object-dtype column lets a paste land a string or
    a list in a cell, which then crashes the numeric parsing.
    """
    return pd.DataFrame(
        [{_CORNER_COLS[0]: float(p[0]), _CORNER_COLS[1]: float(p[1])} for p in pts],
        columns=_CORNER_COLS).astype("float64")


def _rebar_df(pts):
    """Reinforcement DataFrame ``(x, y, area)`` in mm/mm2 from mm/mm2 points."""
    return pd.DataFrame(
        [{_REBAR_COLS[0]: float(p[0]), _REBAR_COLS[1]: float(p[1]),
          _REBAR_COLS[2]: float(p[2])} for p in pts],
        columns=_REBAR_COLS).astype("float64")


def _to_number(v):
    """Coerce a cell to a finite float, or ``None`` if it is blank/non-numeric
    (NaN, text, a stray list from a paste). Never raises."""
    if isinstance(v, (list, tuple, dict, set, np.ndarray)):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _pts_from_df(df, cols):
    """Rows of ``df`` as numeric tuples, keeping only complete, valid points.

    A row is kept only when every coordinate coerces to a finite number; partial
    rows (e.g. an x with no y yet) and any non-numeric cell (a stray paste, text,
    a list) are skipped rather than raising, so editing never crashes the app.
    """
    out = []
    for _, row in df.iterrows():
        vals = [_to_number(row.get(c)) for c in cols]
        if any(v is None for v in vals):
            continue
        out.append(tuple(vals))
    return out


_MAX_VOIDS = 10   # arbitrary cap on the number of separate voids


def _render_point_table(box, base_key, ed_key, cols):
    """Draw the editable table and return its current contents.

    The base DataFrame is the *stable* source the widget owns across reruns: it is
    set only by explicit actions (Load / Clear / Add or Remove void), never
    re-seeded or cleared on every run, so a typed or pasted value sticks on the
    first keystroke instead of lagging a rerun behind. Every data column is a
    numeric input, so a value can be typed or pasted (a spreadsheet block
    auto-grows the table) and a cell can never become text or a list. The point
    numbers are drawn on the plots (by position), not stored as an ID column.
    """
    column_config = {c: st.column_config.NumberColumn(c, step=None) for c in cols}
    return box.data_editor(
        st.session_state[base_key], key=ed_key, num_rows="dynamic",
        use_container_width=True, hide_index=True, column_config=column_config)


def _point_editor(box, base_key, ed_key, cols):
    """Editable point table. A row is only used once all its coordinates are
    filled, so a half-typed point is ignored rather than rejected. Returns the
    valid points, numbered by position (the order they appear)."""
    return _pts_from_df(_render_point_table(box, base_key, ed_key, cols), cols)


def _void_groups(df, cols):
    """Split the void table into voids: runs of complete (x, y) rows, separated by
    a blank row. Returns the groups in order (each a list of points), including
    short ones (fewer than 3 corners), so callers can both count and validate."""
    groups, current = [], []
    for _, row in df.iterrows():
        vals = [_to_number(row.get(c)) for c in cols]
        if any(v is None for v in vals):     # a blank/partial row separates voids
            if current:
                groups.append(current)
                current = []
        else:
            current.append(tuple(vals))
    if current:
        groups.append(current)
    return groups


def _void_editor(box, base_key, ed_key):
    """Editable void table: several voids in one table, separated by a blank row.
    Returns the hole rings (each void with 3 or more corners), capped at
    ``_MAX_VOIDS`` -- the cap is enforced here, not only on the Add button, so a
    paste of more voids cannot push extra holes into the drawing and analysis."""
    edited = _render_point_table(box, base_key, ed_key, _CORNER_COLS)
    rings = [g for g in _void_groups(edited, _CORNER_COLS) if len(g) >= 3]
    if len(rings) > _MAX_VOIDS:
        box.warning(f"Only the first {_MAX_VOIDS} voids are used; "
                    f"{len(rings) - _MAX_VOIDS} extra ignored.")
    return rings[:_MAX_VOIDS]


def _void_table_from_groups(groups, trailing_blank=False):
    """Rebuild a void DataFrame from a list of voids, one blank row between each.
    With ``trailing_blank`` a blank row is also appended (an empty void slot)."""
    rows = []
    for i, g in enumerate(groups):
        if i > 0:
            rows.append({c: None for c in _CORNER_COLS})   # separator
        rows.extend({_CORNER_COLS[0]: x, _CORNER_COLS[1]: y} for x, y in g)
    if trailing_blank:
        rows.append({c: None for c in _CORNER_COLS})
    return pd.DataFrame(rows, columns=_CORNER_COLS).astype("float64")


def _current_table(base_key, ed_key, cols):
    """The table as currently shown = the stable base plus the live editor delta.

    The base is changed only by explicit actions, so a button handler that runs
    before the editor re-renders (Add / Remove void) must fold in the user's
    unsaved edits (held in the data_editor's delta) to avoid discarding them.
    """
    df = st.session_state[base_key].copy().reset_index(drop=True)
    delta = st.session_state.get(ed_key) or {}
    for i, changes in delta.get("edited_rows", {}).items():
        for c, v in changes.items():
            if c in df.columns and int(i) in df.index:
                df.at[int(i), c] = v
    deleted = [int(i) for i in (delta.get("deleted_rows") or []) if int(i) in df.index]
    if deleted:
        df = df.drop(index=deleted)
    added = delta.get("added_rows") or []
    if added:
        df = pd.concat([df, pd.DataFrame(added).reindex(columns=cols)],
                       ignore_index=True)
    return df.reset_index(drop=True)


def _points_preview(box, pts, cols, start):
    """Read-only numbered view of the valid points, matching the plot numbering --
    a non-editable ID next to each point (the editable table has no ID column)."""
    if not pts:
        return
    data = {"ID": list(range(start, start + len(pts)))}
    for j, c in enumerate(cols):
        data[c] = [p[j] for p in pts]
    box.dataframe(data, hide_index=True, use_container_width=True,
                  height=min(35 * (len(pts) + 1) + 3, 240))


_PROJECT_TABLES = (
    ("corners_base", "ed_corners", _CORNER_COLS),
    ("hole_base", "ed_hole", _CORNER_COLS),
    ("bars_base", "ed_bars", _REBAR_COLS),
    ("tendons_base", "ed_tendons", _REBAR_COLS),
)


def _gather_project() -> str:
    """Serialise the current inputs (live point tables + scalar keys) to JSON."""
    tables = {base: _current_table(base, ed, cols)
              for base, ed, cols in _PROJECT_TABLES if base in st.session_state}
    scalars = {k: st.session_state[k] for k in project_io.SCALAR_KEYS
               if k in st.session_state}
    return project_io.dump_project(tables, scalars)


def _apply_pending_project() -> None:
    """Apply an uploaded project, if any, before the widgets are created.

    Runs at the top of the script so writing the loaded values into the widget
    keys (and the point-table bases) happens before those widgets exist -- the
    only point at which Streamlit allows their state to be set.
    """
    text = st.session_state.pop("_pending_project", None)
    if text is None:
        return
    try:
        tables, scalars = project_io.parse_project(text)
    except ValueError as exc:
        st.session_state["_project_msg"] = ("error", f"Could not load project: {exc}.")
        return
    for key, df in tables.items():
        st.session_state[key] = df
    for key, value in scalars.items():
        st.session_state[key] = value
    # Keep each preset's change-marker in step with the loaded preset so the panel
    # does not re-prefill over the loaded field values.
    for marker, src in project_io.PREV_MARKERS.items():
        if src in scalars:
            st.session_state[marker] = scalars[src]
    for ed in ("ed_corners", "ed_hole", "ed_bars", "ed_tendons"):
        st.session_state.pop(ed, None)
    st.session_state["pts_init"] = True   # do not re-seed the tables from a template
    st.session_state["_project_msg"] = ("success", "Project loaded.")


def _save_load_panel(box) -> None:
    """Download the current project and upload one to restore it."""
    box.download_button("Download project", data=_gather_project(),
                        file_name="sector_section.json", mime="application/json",
                        use_container_width=True,
                        help="Save the section, materials, loads and settings to a "
                             "JSON file.")
    up = box.file_uploader("Load project", type=["json"], key="project_upload",
                           help="Restore a section from a downloaded project file.")
    if up is not None:
        fid = (up.name, up.size)
        if st.session_state.get("_project_upload_id") != fid:
            st.session_state["_project_upload_id"] = fid
            st.session_state["_pending_project"] = up.getvalue().decode("utf-8")
            st.rerun()
    msg = st.session_state.pop("_project_msg", None)
    if msg:
        (box.success if msg[0] == "success" else box.error)(msg[1])


def build_inputs():
    """Render the sidebar dropdown panels and return the section, materials and
    loads. Panels mirror the BriCoS layout: About, Analysis & Result Settings,
    Section, Material Parameters, Loads."""
    s = st.sidebar

    with s.expander("About", expanded=False):
        st.markdown("### Sector")
        st.caption("Reinforced-concrete and prestressed cross-section analysis.")
        st.markdown(
            "Sector analyses an arbitrary RC (and optionally prestressed) "
            "cross-section and reports:\n"
            "- **Plastic bending capacity** -- the biaxial M-M interaction "
            "envelope and the load utilisation.\n"
            "- **Cracked-section elastic stresses** -- concrete and "
            "reinforcement stresses under the long- and short-term loads.\n"
            "- **Serviceability checks** -- cracking threshold, section "
            "properties, and optional tension stiffening and crack width.")
        st.markdown("**Workflow**")
        st.caption("Define the section and materials, choose the analyses, then "
                   "press Calculate. The section drawing and the stress-strain "
                   "diagrams update live; the result views update on Calculate.")
        st.divider()
        st.caption(f"Sector v{APP_VERSION}  -  internal engineering tool, Sweco.")

    _save_load_panel(s.expander("Save / Load", expanded=False))

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

    aset.markdown("**Serviceability (elastic SLS)**")
    aset.caption("Extra cracked-section checks in the Elastic view.")
    sls_cw = aset.checkbox("Crack width", value=False, key="sls_cw",
                           disabled=not elastic_on,
                           help="Report the EC2 crack width wk for both the long-term "
                                "and the short-term (instantaneous) load. Each bar's "
                                "clear cover is taken from the geometry.")
    sls_phi = aset.number_input("Crack-width bar diameter (mm, 0 = auto)", 0.0, 60.0,
                                0.0, 1.0, key="sls_phi",
                                disabled=not (elastic_on and sls_cw),
                                help="Governing bar diameter for the crack spacing "
                                     "sr,max; 0 derives it from each bar's area.")
    # k1 (EC2 7.11 bond coefficient) depends on the bar surface, which the geometry
    # cannot tell, so it is a user choice: 0.8 ribbed / high-bond, 1.6 plain round.
    sls_bond = aset.selectbox(
        "Mild-steel bond (k1)",
        list(_BOND_K1), key="sls_bond", disabled=not (elastic_on and sls_cw),
        help="EC2 7.11 bond coefficient k1 for the crack spacing, applied to the "
             "mild reinforcement: 0.8 for ribbed / high-bond bars (e.g. Tentor), "
             "1.6 for plain round bars. Prestressing tendons always use k1 = 1.6.")
    sls_k1 = _BOND_K1[sls_bond]
    sls_code = aset.selectbox(
        "Crack-width code", list(_CRACK_CODES), key="sls_code",
        disabled=not (elastic_on and sls_cw),
        help="Code edition for the crack-spacing rules. The DK NA makes k3 cover-"
             "dependent (k3 = 3.4*(25/c)^(2/3)) and limits the (h-x)/3 effective-"
             "height term to slabs and prestressed members.")
    sls_dk_na = _CRACK_CODES[sls_code]
    sls_member = aset.selectbox(
        "Member type", ["Beam", "Slab"], key="sls_member",
        disabled=not (elastic_on and sls_cw and sls_dk_na),
        help="Under the DK NA the (h-x)/3 effective-height term applies only to "
             "slabs (and prestressed members); for a beam it is dropped. Ignored "
             "for the base EN 1992-1-1 code.")

    sec = s.expander("Section", expanded=True)
    shape = sec.selectbox("Shape", ["Rectangle", "Slab strip", "T-section",
                                    "Box girder", "Circular"], key="shape",
                          help="Outline of the concrete cross-section to analyse.")

    holes = []
    if shape == "Rectangle":
        b = sec.number_input("Width b (mm)", 50.0, 10000.0, 400.0, 10.0, key="b_mm",
                             help="Overall section width.") / 1000.0
        h = sec.number_input("Height h (mm)", 50.0, 10000.0, 600.0, 10.0, key="h_mm",
                             help="Overall section height (depth).") / 1000.0
        outer = templates.rectangle(b, h)
        width_b = b
    elif shape == "Slab strip":
        h = sec.number_input("Thickness h (mm)", 50.0, 3000.0, 300.0, 10.0, key="h_mm",
                             help="Slab thickness; the strip is analysed per 1 m width.") / 1000.0
        b = 1.0
        outer = templates.slab_strip(h)
        width_b = b
    elif shape == "T-section":
        bf = sec.number_input("Flange width bf (mm)", 100.0, 12000.0, 1200.0, 10.0, key="bf_mm",
                              help="Width of the (top) flange.") / 1000.0
        hf = sec.number_input("Flange thickness hf (mm)", 50.0, 2000.0, 200.0, 10.0, key="hf_mm",
                              help="Thickness of the flange.") / 1000.0
        bw = sec.number_input("Web width bw (mm)", 50.0, 4000.0, 300.0, 10.0, key="bw_mm",
                              help="Width of the web.") / 1000.0
        hw = sec.number_input("Web depth hw (mm)", 100.0, 6000.0, 600.0, 10.0, key="hw_mm",
                              help="Depth of the web below the flange.") / 1000.0
        outer = templates.t_section(bf, hf, bw, hw)
        b, h, width_b = bw, hf + hw, bf
    elif shape == "Box girder":
        b = sec.number_input("Width b (mm)", 200.0, 12000.0, 800.0, 10.0, key="b_mm",
                             help="Overall outer width of the box.") / 1000.0
        h = sec.number_input("Height h (mm)", 200.0, 12000.0, 1000.0, 10.0, key="h_mm",
                             help="Overall outer height of the box.") / 1000.0
        # Cap the wall so the cavity stays positive (2*wall < b and < h).
        max_wall = round((min(b, h) / 2 - 0.01) * 1000.0, 0)
        wall = sec.number_input("Wall thickness (mm)", 20.0, max_wall,
                                min(200.0, max_wall), 10.0, key="wall_mm",
                                help="Thickness of the box walls (uniform).") / 1000.0
        outer, holes = templates.box(b, h, wall)
        width_b = b
    else:  # Circular
        dia = sec.number_input("Diameter (mm)", 100.0, 6000.0, 600.0, 10.0, key="dia_mm",
                               help="Outer diameter of the circular section.") / 1000.0
        outer = templates.circular(dia)
        b = h = dia
        width_b = dia

    sec.markdown("**Reinforcement**")
    if shape == "Circular":
        nb = sec.number_input("Perimeter bars", 0, 200, 8, 1, key="ring_n",
                              help="Number of bars evenly spaced around the perimeter.")
        rd = sec.selectbox("Bar diameter (mm)", templates.BAR_DIAMETERS, index=4,
                           key="ring_d", help="Diameter of each reinforcement bar.")
        cov = sec.number_input("Cover (mm)", 0.0, 500.0, 50.0, 5.0, key="ring_c_mm",
                               help="Distance from the section face to the bar centres.") / 1000.0
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
        cov = sec.number_input("Cover (mm)", 0.0, 500.0, 50.0, 5.0, key="cover_mm",
                               help="Distance from the top/bottom face to the bar centres.") / 1000.0
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
        cov_p = sec.number_input("Tendon cover (mm)", 0.0, 2000.0, 100.0, 10.0, key="tnd_c_mm",
                                 help="Distance from the bottom face (or the "
                                      "circular ring) to the tendons.") / 1000.0
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
    clear_pts = sec.button("Clear Section (empty all points)", key="clear_pts",
                           use_container_width=True,
                           help="Remove every concrete corner, the void, and all "
                                "bars and tendons from the point tables, to start "
                                "from a blank section.")
    if "pts_init" not in st.session_state or load_qs:
        # The Quick Section template is in metres; the tables hold millimetres.
        st.session_state["corners_base"] = _corners_df(_pts_to_mm(qs_outer))
        st.session_state["hole_base"] = _corners_df(_pts_to_mm(qs_hole))
        st.session_state["bars_base"] = _rebar_df(_pts_to_mm(qs_bars))
        st.session_state["tendons_base"] = _rebar_df(_pts_to_mm(qs_tendons))
        for k in ("ed_corners", "ed_hole", "ed_bars", "ed_tendons"):
            st.session_state.pop(k, None)
        st.session_state["pts_init"] = True
    if clear_pts:
        # Empty every point table (corners, void, bars, tendons) and drop the live
        # editor edits, so the section starts blank.
        st.session_state["corners_base"] = _corners_df([])
        st.session_state["hole_base"] = _corners_df([])
        st.session_state["bars_base"] = _rebar_df([])
        st.session_state["tendons_base"] = _rebar_df([])
        for k in ("ed_corners", "ed_hole", "ed_bars", "ed_tendons"):
            st.session_state.pop(k, None)
    # Migrate a session that predates the void table (or the ID-column tables): seed
    # hole_base, and coerce any stored table to the current data-only schema.
    if "hole_base" not in st.session_state:
        old = st.session_state.get("holes_pts") or []
        st.session_state["hole_base"] = _corners_df(old[0] if old else [])
    for base_key, cols, ed_key in (
            ("corners_base", _CORNER_COLS, "ed_corners"),
            ("hole_base", _CORNER_COLS, "ed_hole"),
            ("bars_base", _REBAR_COLS, "ed_bars"),
            ("tendons_base", _REBAR_COLS, "ed_tendons")):
        df = st.session_state.get(base_key)
        if df is not None and list(df.columns) != cols:
            if set(cols).issubset(df.columns):
                st.session_state[base_key] = df.reindex(columns=cols)  # drop a legacy ID col
            else:   # an older schema (e.g. metre column names) -> reset to empty
                st.session_state[base_key] = (_corners_df([]) if cols is _CORNER_COLS
                                              else _rebar_df([]))
            st.session_state.pop(ed_key, None)

    sec.markdown("**Cross-section points** (the analysis uses these)")
    sec.caption("Concrete corners define the outline (3 or more, in order); the "
                "voids are optional inner rings. Bars and tendons are points with an "
                "area (mm2). Type or paste values (a block copied from a spreadsheet "
                "auto-grows the table); a point is used once all its cells are "
                "filled. Below each table a read-only list numbers the points (the "
                "ID matches the plots). Use Load Quick Section to refill from the "
                "template above.")
    sec.markdown("_Concrete corners_")
    outer_mm = _point_editor(sec, "corners_base", "ed_corners", _CORNER_COLS)
    _points_preview(sec, outer_mm, _CORNER_COLS, 1)
    outer = _pts_to_m(outer_mm)
    if len(outer) < 3:
        # No valid outline. Leave it empty (do NOT fall back to the Quick Section,
        # or Clear Section would silently revert to the template) and let the
        # downstream treat the section as blank.
        sec.warning("The section has no concrete outline. Add at least 3 corners, "
                    "or press Load Quick Section.")
    sec.markdown("_Concrete voids_")
    sec.caption("Several voids share this table, each separated by a blank row "
                "(each void needs 3 or more corners).")
    # The buttons act on the live table (base + unsaved editor edits) so typing a
    # void and then adding/removing one does not discard the in-progress corners.
    void_now = _current_table("hole_base", "ed_hole", _CORNER_COLS)
    n_voids = len(_void_groups(void_now, _CORNER_COLS))
    vc1, vc2 = sec.columns(2)
    if vc1.button("+ Add void", key="add_void", use_container_width=True,
                  disabled=n_voids >= _MAX_VOIDS,
                  help=f"Append a blank separator row, so the next corners you enter "
                       f"start a new void (up to {_MAX_VOIDS})."):
        groups = _void_groups(void_now, _CORNER_COLS)
        st.session_state["hole_base"] = _void_table_from_groups(groups,
                                                                trailing_blank=True)
        st.session_state.pop("ed_hole", None)
    if vc2.button("Remove void", key="rem_void", use_container_width=True,
                  disabled=n_voids == 0, help="Drop the last void from the table."):
        groups = _void_groups(void_now, _CORNER_COLS)
        st.session_state["hole_base"] = _void_table_from_groups(groups[:-1])
        st.session_state.pop("ed_hole", None)
    holes_mm = _void_editor(sec, "hole_base", "ed_hole")
    _points_preview(sec, [p for ring in holes_mm for p in ring], _CORNER_COLS,
                    len(outer) + 1)
    holes = [_pts_to_m(ring) for ring in holes_mm]
    sec.markdown("_Reinforcing bars_")
    bars_mm = _point_editor(sec, "bars_base", "ed_bars", _REBAR_COLS)
    _points_preview(sec, bars_mm, _REBAR_COLS, 1)
    bars = _pts_to_m(bars_mm)
    tendons = []
    if use_pre:
        sec.markdown("_Tendons_")
        tendons_mm = _point_editor(sec, "tendons_base", "ed_tendons", _REBAR_COLS)
        _points_preview(sec, tendons_mm, _REBAR_COLS, len(bars) + 1)
        tendons = _pts_to_m(tendons_mm)

    # In elastic-only mode the stress-strain laws do not enter the analysis (it is
    # linear: steel via the modular ratio, concrete linear in compression with no
    # tension), so lock the parameters that have no elastic effect. fck (it feeds
    # the serviceability fctm) and the steel modulus Es (the crack-width mean
    # strain) still matter, so they stay editable.
    lock_mats = mode == "Elastic"
    lock_elastic = mode == "Plastic"   # fctm + Ec are elastic-only inputs
    mat = s.expander("Material Parameters", expanded=False)
    if lock_mats:
        mat.caption("Elastic-only mode: the stress-strain laws do not affect the "
                    "elastic results and are locked. Only fck (feeds fctm) and the "
                    "steel modulus Es (crack width) stay editable; switch to "
                    "Plastic or Both to edit the full laws.")
    concrete, sls_fctm, conc_Ec = concrete_panel(mat, locked=lock_mats,
                                                 lock_elastic=lock_elastic)
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
    phi_creep = loads.number_input("Creep coefficient phi (long-term)", 0.0, 5.0, 2.0,
                                   0.1, key="el_phi", disabled=not elastic_on,
                                   help="Final creep coefficient for the long-term "
                                        "modular ratio n_l = Es*(1+phi)/Ec.")
    _nl_auto = round(min(50.0, max(1.0, steel.Es * (1.0 + phi_creep)
                                   / (conc_Ec * 1000.0))), 1)
    st.session_state.setdefault("nl", _nl_auto)   # default from Ec, phi (EC2)
    if loads.button(f"Auto n_l (Es(1+phi)/Ec = {_nl_auto:.1f})", key="nl_auto",
                    disabled=not elastic_on, use_container_width=True,
                    help="Long-term modular ratio from the concrete Ec, creep-reduced "
                         "by phi (effective-modulus method)."):
        st.session_state["nl"] = _nl_auto
    nl = loads.number_input("Long-term modular ratio n_l = Es/Ec_eff", 1.0, 50.0,
                            step=0.5, key="nl", disabled=not elastic_on,
                            help="Modular ratio for the sustained load (creep-reduced "
                                 "concrete stiffness, so larger than the short-term "
                                 "ratio). Use Auto to derive it from Ec and phi.")
    loads.markdown("_Short-term_")
    P_el_s, Mx_el_s, My_el_s = _load_set(
        "el_short", "Instantaneous (variable) axial force.",
        "Instantaneous (variable) moment.", elastic_on, mx_default=0.0)
    _ns_auto = round(min(50.0, max(1.0, steel.Es / (conc_Ec * 1000.0))), 1)
    st.session_state.setdefault("ns", _ns_auto)   # default from Ec (Es/Ec)
    if loads.button(f"Auto n_s (Es/Ec = {_ns_auto:.1f})", key="ns_auto",
                    disabled=not elastic_on, use_container_width=True,
                    help="Short-term (instantaneous) modular ratio from the concrete Ec."):
        st.session_state["ns"] = _ns_auto
    ns = loads.number_input("Short-term modular ratio n_s = Es/Ec", 1.0, 50.0,
                            step=0.5, key="ns", disabled=not elastic_on,
                            help="Modular ratio for the instantaneous load. Use Auto "
                                 "to derive it from Ec.")

    section = (Section.from_polygon(corners=outer, bars_xy_area_mm2=bars,
                                    tendons_xy_area_mm2=tendons, holes=holes)
               if len(outer) >= 3 else None)
    # A void must not split the concrete into disconnected pieces (e.g. a slot
    # reaching across the section): such a section has no valid capacity.
    void_error = None
    if section is not None and holes and not geometry.concrete_is_connected(outer, holes):
        void_error = ("A void splits the concrete into disconnected regions. "
                      "Adjust the voids so the concrete outline stays continuous.")
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
            "conc_eps_c2", "conc_eps_cu2", "conc_n",
            "mild_preset", "mild_fytk", "mild_fyck", "mild_futk", "mild_eut",
            "mild_gamma_y", "mild_gamma_u", "mild_gamma_E", "mild_k",
            "mild_ey0t", "mild_ey0c", "mild_Es", "mild_active_comp",
            "use_pre", "pre_preset",
            "pre_IS", "pre_fytk", "pre_futk", "pre_eut", "pre_gamma_y",
            "pre_gamma_u", "pre_gamma_E", "pre_k", "pre_ey0t", "pre_Es",
            "pl_P", "pl_Mx", "pl_My", "el_long_P", "el_long_Mx", "el_long_My",
            "nl", "el_short_P", "el_short_Mx", "el_short_My", "ns",
            "v_min", "v_max", "v_inc", "mode",
            "sls_cw", "sls_fctm", "sls_phi", "sls_bond",
            "sls_code", "sls_member"))
    return dict(section=section, void_error=void_error, concrete=concrete, steel=steel,
                bars=bars, outer=outer, holes=holes, tendons=tendons,
                prestress=prestress, P_pl=P_pl, Mx_pl=Mx_pl, My_pl=My_pl,
                v_min=v_min, v_max=v_max, v_inc=v_inc,
                P_el_l=P_el_l, Mx_el_l=Mx_el_l, My_el_l=My_el_l, nl=nl,
                P_el_s=P_el_s, Mx_el_s=Mx_el_s, My_el_s=My_el_s, ns=ns,
                sls_cw=sls_cw, sls_fctm=sls_fctm, sls_phi=sls_phi,
                sls_k1=sls_k1, sls_dk_na=sls_dk_na, sls_member=sls_member,
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


def _crack_dict(cw):
    """Flatten a CrackWidthResult (or None) for the results payload."""
    if cw is None:
        return None
    return dict(wk=cw.wk, sr_max=cw.sr_max, esm_ecm=cw.esm_ecm, sigma_s=cw.sigma_s,
                rho_p_eff=cw.rho_p_eff, ac_eff=cw.ac_eff, hc_ef=cw.hc_ef,
                phi=cw.phi, cover=cw.cover, gov_bar=cw.gov_bar + 1)


def run_analysis(inp):
    out = {}
    if inp["section"] is None or inp.get("void_error"):
        return out                          # no valid concrete outline -> nothing to run
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

        # Extended serviceability checks. Each bar's clear cover is taken from the
        # geometry, so no cover input is needed. The long-term (quasi-permanent)
        # state at nl (beta/kt = 0.5/0.4) drives the cracking threshold, the
        # section properties and tension stiffening; the short-term (instantaneous)
        # state -- the total long+short load at ns (beta/kt = 1.0/0.6) -- gives the
        # short-term crack width. Crack width is reported for both loads.
        phi = inp["sls_phi"] if inp["sls_phi"] > 0.0 else None
        # k1 per bar: the mild reinforcement uses the selected bond value; any
        # prestressing tendons (folded into the bar set after the bars) always
        # use 1.6. Order matches sec.bar_arrays() (bars first, then tendons).
        k1_bars = [inp["sls_k1"]] * len(inp["bars"]) + [1.6] * len(inp["tendons"])
        # DK NA crack-spacing rules: cover-dependent k3, and -- for an ordinary beam
        # (not a slab or a prestressed member) -- dropping the (h-x)/3 hc,ef term.
        dk_na = inp["sls_dk_na"]
        include_hx = (not dk_na) or inp["sls_member"] == "Slab" or bool(inp["tendons"])
        cr_l = analyse_cracking(
            sec, inp["P_el_l"], inp["Mx_el_l"], inp["My_el_l"], inp["nl"],
            fctm=inp["sls_fctm"], Es=inp["steel"].Es, beta=0.5, kt=0.4,
            bar_diameter=phi, k1=k1_bars,
            k3_cover_dependent=dk_na, include_hx_term=include_hx)
        props_un = transformed_properties(sec, inp["nl"], cracked=False)
        props_cr = (transformed_properties(
            sec, inp["nl"], eps0=cr_l.cracked_state.eps0, kx=cr_l.cracked_state.kx,
            ky=cr_l.cracked_state.ky, cracked=True) if cr_l.cracked else None)
        out["elastic"].update(
            cracked=cr_l.cracked, lambda_cr=cr_l.lambda_cr, sigma_ct=cr_l.sigma_ct,
            fctm=cr_l.fctm, show_cw=inp["sls_cw"],
            props_un=_props_dict(props_un),
            props_cr=(_props_dict(props_cr) if props_cr is not None else None),
            crack=None, crack_short=None,
        )
        # Crack width is its own opt-in, reported for both load cases once the
        # (quasi-permanent) section has cracked. The long-term state is the solve
        # at nl above. The short-term state reuses the combined creep solve `r`:
        # its instantaneous neutral axis with the displayed total steel stress
        # (s2 + RST1), so the crack-width sigma_s matches the Total column rather
        # than a raw (long+short)-at-ns solve. Each bar's cover comes from geometry.
        if inp["sls_cw"] and cr_l.cracked:
            short_state = dataclasses.replace(r.short_term,
                                              bar_stress=r.bar_stress_total)
            cw_short = crack_width(sec, short_state, inp["ns"], fctm=inp["sls_fctm"],
                                   Es=inp["steel"].Es, kt=0.6, bar_diameter=phi,
                                   k1=k1_bars, k3_cover_dependent=dk_na,
                                   include_hx_term=include_hx)
            out["elastic"].update(
                crack=_crack_dict(cr_l.crack), crack_short=_crack_dict(cw_short),
                crack_code=("DS/EN 1992-1-1 + DK NA (fine crack system)" if dk_na
                            else "EN 1992-1-1:2005"),
                crack_member=(inp["sls_member"] if dk_na else None),
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
    if inp["section"] is None:
        st.info("The section has no concrete outline yet -- add at least 3 corners "
                "in the Section panel, or press Load Quick Section. Any reinforcement "
                "you have added is still drawn below.")
    bar_xy = [(b[0], b[1]) for b in inp["bars"]]
    tendon_xy = [(t[0], t[1]) for t in inp["tendons"]]
    st.plotly_chart(viz.section_figure(inp["outer"], inp["holes"], bar_xy,
                                       title="Section", tendons=tendon_xy,
                                       show_labels=True, label_scale=inp["label_scale"],
                                       label_min_gap=inp["label_min_gap"], height=640,
                                       scale=_MM, unit="mm"),
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
        "NA x (mm)": [_fmt(pt["na_x"] * _MM) for pt in pts],
        "NA y (mm)": [_fmt(pt["na_y"] * _MM) for pt in pts],
        "eps_c (%)": [round(pt["eps_c"], 2) for pt in pts],
        "eps_s (%)": [round(pt["eps_s"], 2) for pt in pts],
        "kappa (1/m)": [round(pt["kappa"], 4) for pt in pts],
        "Comp (kN)": [round(pt["comp_force"], 0) for pt in pts],
        "L (mm)": [round(pt["lever"] * _MM, 1) for pt in pts],
        "Dx (mm)": [round(pt["dx"] * _MM, 1) for pt in pts],
        "Dy (mm)": [round(pt["dy"] * _MM, 1) for pt in pts],
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
                               label_min_gap=inp["label_min_gap"], scale=_MM, unit="mm"),
            use_container_width=True)
    with cR:
        lines = [
            f"- **Mx / My**: {pt['Mx']:.0f} / {pt['My']:.0f} kNm",
            f"- **Curvature kappa**: {pt['kappa']:.4g} 1/m",
            f"- **Compression force**: {pt['comp_force']:.0f} kN",
            f"- **Lever arm L**: {pt['lever'] * _MM:.0f} mm  "
            f"(Dx {pt['dx'] * _MM:.0f}, Dy {pt['dy'] * _MM:.0f})",
            f"- **Concrete strain**: {pt['eps_c']:.2f} %",
            f"- **Steel strain**: {pt['eps_s']:.2f} %",
            f"- **NA intercepts**: x {_fmt(pt['na_x'] * _MM)}, "
            f"y {_fmt(pt['na_y'] * _MM)} mm",
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
                   f"x {_fmt(e['na_x'] * _MM)} mm,  y {_fmt(e['na_y'] * _MM)} mm")
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
                           label_min_gap=inp["label_min_gap"], scale=_MM, unit="mm",
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
    and transformed section properties (always); tension stiffening and crack
    width are independent opt-ins. The threshold, properties and tension
    stiffening are on the long-term load; crack width is reported for both the
    long-term and the short-term (instantaneous) load."""
    if "cracked" not in e:
        return
    show_cw = e.get("show_cw", False)
    st.divider()
    st.markdown("#### Serviceability checks")
    if e["cracked"]:
        st.warning(f"**Cracked** under the long-term load - the uncracked concrete "
                   f"tension reaches fctm at a load factor lambda_cr = "
                   f"{e['lambda_cr']:.3f} (= Mcr/M for pure bending).")
    else:
        lam = "infinite" if math.isinf(e["lambda_cr"]) else f"{e['lambda_cr']:.2f}"
        st.success(f"**Uncracked** under the long-term load - peak concrete tension "
                   f"{e['sigma_ct']:.2f} MPa < fctm {e['fctm']:.2f} MPa "
                   f"(lambda_cr = {lam}).")

    st.metric("Cracking factor lambda_cr",
              "inf" if math.isinf(e["lambda_cr"]) else f"{e['lambda_cr']:.3f}",
              help="Proportional load factor to first cracking, "
                   "fctm / sigma_ct,I (= Mcr/M in pure bending). < 1 = cracked.")

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
        if show_cw:
            _crack_width_panel(e)


def _crack_width_panel(e):
    """Crack width (EC2 7.3.4) for the long-term and short-term load cases, side
    by side. Each bar's clear cover is taken from the geometry and the bar with
    the largest wk governs, reported per load case."""
    cl, cs = e.get("crack"), e.get("crack_short")
    st.markdown(f"**Crack width wk** ({e.get('crack_code', 'EC2 7.3.4')})")
    if cl is None and cs is None:
        st.info("No crack width: uncracked, or no bar in tension, under either "
                "the long-term or the short-term load.")
        return
    quants = ["wk (mm)", "sr,max (mm)", "esm - ecm", "sigma_s (MPa)", "rho_p,eff",
              "hc,ef (m)", "cover c (mm)", "bar dia (mm)", "gov. bar"]
    keys = ["wk", "sr_max", "esm_ecm", "sigma_s", "rho_p_eff", "hc_ef", "cover",
            "phi", "gov_bar"]
    fmts = ["{:.3f}", "{:.1f}", "{:.3e}", "{:.1f}", "{:.4f}", "{:.3f}", "{:.1f}",
            "{:.1f}", "{:d}"]

    def column(c):
        if c is None:
            return ["-"] * len(keys)
        return [f.format(c[k]) for k, f in zip(keys, fmts)]

    st.dataframe({"Quantity": quants, "Long-term": column(cl),
                  "Short-term": column(cs)}, hide_index=True,
                 use_container_width=True)
    st.caption("Governing (largest-wk) bar per load case; each bar's clear cover "
               "is the distance to the nearest concrete face minus its radius.")
    member = e.get("crack_member")
    if member:
        st.caption(f"DK NA fine crack system: cover-dependent k3 = 3.4*(25/c)^(2/3); "
                   f"member type = {member} (the (h-x)/3 effective-height term "
                   f"applies to slabs and prestressed members).")


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

_apply_pending_project()   # restore an uploaded project before any widget is built
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

if inp.get("void_error"):
    st.error(inp["void_error"])

if view == "Section":
    section_view(inp)
elif view == "Stress-Strain diagrams":
    materials_view(inp)
elif view == "Plastic Results":
    plastic_view(inp, results)
else:
    elastic_view(inp, results)
