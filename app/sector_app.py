"""Sector - reinforced-concrete cross-section analysis (Streamlit interface).

Define a section by its shape and reinforcement, choose elastic and/or plastic
analysis, then press Calculate to review the stresses and the ultimate capacity.
"""

from __future__ import annotations

import dataclasses
import json
import math
import os
import pathlib
import sys
import threading
import time
from datetime import datetime

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
from point_grid import point_grid, _rows_to_df  # noqa: E402
from sector import __version__ as sector_version  # noqa: E402
from sector import codes, geometry, kernels, material_presets as mp, templates  # noqa: E402
from sector.elastic import solve_elastic_combined, transformed_properties  # noqa: E402
from sector.plastic import solve_plastic  # noqa: E402
from sector.section import Section  # noqa: E402
from sector.serviceability import analyse_cracking, crack_width  # noqa: E402

# The tool version comes from the sector package (the single source of truth); it
# shows in the title, the browser tab, the About panel and the report footer.
APP_VERSION = sector_version
APP_AUTHOR = "Kasper Lindskov Fabricius"
APP_EMAIL = "Kasper.LindskovFabricius@sweco.dk"
ROOT = pathlib.Path(__file__).resolve().parent.parent

# Greek glyphs for the result tables (st.dataframe renders plain Unicode, not LaTeX,
# so widget labels use $...$ but table headers/cells use these). Written via chr()
# so the source stays ASCII (BMP code points, no surrogate pairs).
_EPS, _SIGMA, _RHO, _PHI = chr(0x3B5), chr(0x3C3), chr(0x3C1), chr(0x3C6)
_KAPPA = chr(0x3BA)

# EC2 7.11 bond coefficient k1 by bar surface (cannot be inferred from geometry).
_BOND_K1 = {"Ribbed / high bond (k1 = 0.8)": 0.8, "Plain round (k1 = 1.6)": 1.6}

# Crack-width code edition -> the crack-spacing flags. edition: "2004" (EC2 7.3.4)
# or "2023" (EC2 9.2.3 refined). dk_na: cover-dependent k3 and the (h-x)/3
# effective-height term only for slabs/prestressed. coarse: the DK NA coarse crack
# system (7.3.4(1)) -- the effective area is the band whose centroid matches the
# tension reinforcement (figure 7.100 NA) and wk is halved.
_CRACK_CODES = {
    "EN 1992-1-1:2005": dict(dk_na=False, coarse=False, edition="2004"),
    "DS/EN 1992-1-1 + DK NA (fine crack system)": dict(dk_na=True, coarse=False, edition="2004"),
    "DS/EN 1992-1-1 + DK NA (coarse crack system)": dict(dk_na=True, coarse=True, edition="2004"),
    "EN 1992-1-1:2023": dict(dk_na=False, coarse=False, edition="2023"),
}
# Old saved value for the fine DK NA option, renamed when the coarse system was added.
_CRACK_CODE_ALIASES = {"DS/EN 1992-1-1 + DK NA": "DS/EN 1992-1-1 + DK NA (fine crack system)"}

st.set_page_config(layout="wide", page_title=f"Sector v{APP_VERSION}")


@st.cache_resource(show_spinner=False)
def _warm_solver():
    """Compile the solver kernels in a background thread, so the ~1 s JIT warm-up
    does not block the first paint.

    The live Section and Stress-Strain views never call the kernels, so the page is
    interactive while the thread compiles; by the time a section is defined and
    Calculate is pressed the warm-up is normally finished. A Calculate that races
    the thread is safe -- numba's per-dispatcher compile lock makes the second
    caller wait for the first rather than compile twice. ``cache_resource`` starts
    the thread exactly once per server.
    """
    thread = threading.Thread(target=kernels.warmup, name="sector-warmup",
                              daemon=True)
    thread.start()
    return thread


_warm_solver()

# The sidebar's scroll container (stSidebarContent) ships with height:100% +
# overflow:auto, which only scrolls while its <section> parent keeps a definite
# height from the flex layout. When that height intermittently collapses to auto
# (seen with a single tall expander open, e.g. only Material Parameters), the
# container grows to full content height, no scrollbar appears, and everything
# below the fold becomes unreachable. Capping it at the viewport height gives
# overflow:auto a definite height to act against -- a no-op in the healthy case.
st.markdown(
    "<style>"
    'section[data-testid="stSidebar"] [data-testid="stSidebarContent"]'
    "{max-height:100vh;overflow-y:auto;}"
    "</style>",
    unsafe_allow_html=True,
)

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
    # Auto values follow the selected edition: EN 1992-1-1:2023 keeps the ultimate
    # parabola strains constant for every class, so deriving the Table 3.1
    # strength-dependent values above C50/60 would silently overwrite the 2023 law
    # (the manual button and Auto-calc-all share these). Non-edition curve presets
    # are not in the registry -> fall back to Table 3.1.
    _code = codes.CODES.get(preset)
    _ec2_f, _ecu2_f, _n_f = (_code.strain_law(fck) if _code is not None
                             else (codes.eps_c2(fck), codes.eps_cu2(fck),
                                   codes.n_exponent(fck)))
    a_ec2 = round(_ec2_f * 1000.0, 2)
    a_ecu2 = round(_ecu2_f * 1000.0, 2)
    a_n = round(_n_f, 3)
    auto_all = st.session_state.get("_auto_all", False)
    if (box.button(f"Auto $\\varepsilon$/n (EC2: {a_ec2:.2f}/{a_ecu2:.2f} permille, n={a_n:.2f})",
                   key="conc_strain_auto", use_container_width=True, disabled=strain_lock,
                   help="Set eps_c2, eps_cu2 and n for the current grade and edition "
                        "(EC2 Table 3.1, strength-dependent above C50/60; kept constant "
                        "for EN 1992-1-1:2023). Press again after changing fck or preset.")
            or (auto_all and not strain_lock)):
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
        box.warning(r"$\varepsilon_{cu2}$ must be at least $\varepsilon_{c2}$ (the peak "
                    "strain); using that value for the diagram and analysis.")
        eps_cu2 = eps_c2

    concrete = mp.build_concrete(curve=curve, fck=fck, gamma_c=gamma_c,
                                 alpha_cc=alpha_cc, eps_c2=eps_c2, eps_cu2=eps_cu2, n=n)
    note = "  (alpha_cc tracks fck via eta_cc)" if auto is not None else ""
    box.caption(f"curve {curve},  $f_{{cd}}$ = {concrete.fcd:.1f} MPa,  "
                f"$\\varepsilon_{{cu2}}$ = {concrete.eps_cu2 * 1000.0:.2f} permille{note}")

    # Mean tensile strength fctm feeds the serviceability cracking check. It lives
    # with the concrete (not the loads); the Auto button refreshes it from the
    # current grade because the number_input persists across a grade change.
    fctm_ec = round(codes.fctm(fck), 3)
    st.session_state.setdefault("sls_fctm", fctm_ec)
    if (box.button(f"Auto $f_{{ctm}}$ (EC2: {fctm_ec:.2f} MPa)", key="sls_fctm_auto",
                   use_container_width=True, disabled=lock_elastic,
                   help="Set fctm = 0.30*fck^(2/3) (EC2 Table 3.1) for the current "
                        "concrete grade. Press again after changing the grade.")
            or (auto_all and not lock_elastic)):
        st.session_state["sls_fctm"] = fctm_ec
    fctm_val = box.number_input(r"Tensile strength $f_{ctm}$ (MPa)", 0.0, 10.0, step=0.1,
                                key="sls_fctm", disabled=lock_elastic,
                                help="Mean axial tensile strength for the cracking "
                                     "check (fct,eff). Use Auto for the EC2 value.")

    # Elastic modulus Ec: only used by the elastic analysis, to derive the modular
    # ratios n = Es/Ec. The Auto button sets the EC2 secant modulus for the grade.
    ecm_gpa = round(codes.ecm(fck) / 1000.0, 1)
    st.session_state.setdefault("conc_Ec", ecm_gpa)
    if (box.button(f"Auto $E_c$ (EC2: {ecm_gpa:.1f} GPa)", key="conc_Ec_auto",
                   use_container_width=True, disabled=lock_elastic,
                   help="Set Ec = Ecm = 22*(fcm/10)^0.3 GPa (EC2 Table 3.1) for the "
                        "current grade. Press again after changing the grade.")
            or (auto_all and not lock_elastic)):
        st.session_state["conc_Ec"] = ecm_gpa
    Ec = box.number_input(r"Elastic modulus $E_c$ (GPa)", 1.0, 100.0, step=0.5,
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
    box.caption(f"$f_{{yd}}$ = {steel.fytk / vals['gamma_y']:.0f} MPa,  "
                f"$E_s$ = {vals['Es'] / 1000.0:.0f} GPa,  compression {comp}")
    return steel


def prestress_panel(box, locked=False):
    """Prestressing-steel material: preset and editable parameters (diagram is in the main view).

    A flat form: the user-defined and Eurocode presets build the general
    two-yield law, so every parameter is live. The built-in characteristic
    curves are fixed shapes -- only the prestrain (and yield factor) apply.

    ``locked`` (elastic-only mode) disables the stress-strain law parameters, which
    only the plastic analysis uses. The initial prestrain ``IS`` and the modulus
    ``Es`` (Ep) stay editable: the elastic analysis applies the tendon prestress
    ``Ep*IS`` as a force and uses ``Ep/Ec`` for the tendon's modular ratio.
    """
    box.markdown("**Prestressing steel**")
    presets = mp.PRESTRESS_PRESETS
    labels = list(presets)
    preset = box.selectbox("Preset", labels, index=labels.index("EN 1992-1-1:2005"),
                           key="pre_preset", help=_PRESET_HELP)
    _prefill("pre", preset, presets)
    curve = presets[preset]["curve"]
    vals = {f: _number(box, "pre", f, mp.PRESTRESS_FIELD_META, mp.PRESTRESS_HELP,
                       disabled=locked and f not in ("IS", "Es"))
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
    """Convert (x, y[, area]) points from m to mm for the tables (area unchanged).

    The coordinates are rounded to clean the float noise the m->mm scaling adds
    (e.g. -0.15 * 1000 = -150.00000000000003), so the grid shows -150, not a long
    truncated value. 6 decimals is far finer than any real placement tolerance.
    """
    return [(round(p[0] * _MM, 6), round(p[1] * _MM, 6)) + tuple(p[2:]) for p in pts]


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


def _reseed_table(base_key, ed_key, df):
    """Replace a point table's contents and make its grid re-seed from them.

    Bumping the version token is what tells the Tabulator grid to rebuild from the
    new base; dropping the stale component value makes the grid fall back to it
    until the frontend reports again. Only this table is touched, so a Load / Clear
    / Add-void never disturbs the others.
    """
    st.session_state[base_key] = df
    st.session_state[ed_key + "_ver"] = st.session_state.get(ed_key + "_ver", 0) + 1
    st.session_state.pop(ed_key, None)


def _render_point_table(box, base_key, ed_key, cols, id_start=1):
    """Draw the editable grid and return its current contents as a DataFrame.

    One Tabulator grid carries the frozen, auto-numbered ID column (from
    ``id_start``, matching the plot), a frozen header and freely editable numeric
    cells with Excel block paste. The grid owns its live state across reruns and
    only re-seeds when its version token changes (see ``_reseed_table``), so a
    typed or pasted value sticks on the first keystroke instead of lagging behind.
    """
    version = st.session_state.get(ed_key + "_ver", 0)
    with box:
        return point_grid(st.session_state[base_key], cols, key=ed_key,
                          id_start=id_start, data_version=version)


def _point_editor(box, base_key, ed_key, cols, id_start=1):
    """Editable point table. A row is only used once all its coordinates are
    filled, so a half-typed point is ignored rather than rejected. Returns the
    valid points, numbered by position (the order they appear)."""
    return _pts_from_df(_render_point_table(box, base_key, ed_key, cols, id_start),
                        cols)


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


def _void_editor(box, base_key, ed_key, id_start=1):
    """Editable void table: several voids in one table, separated by a blank row.
    Returns the hole rings (each void with 3 or more corners), capped at
    ``_MAX_VOIDS`` -- the cap is enforced here, not only on the Add button, so a
    paste of more voids cannot push extra holes into the drawing and analysis."""
    edited = _render_point_table(box, base_key, ed_key, _CORNER_COLS, id_start)
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
    """The grid's current rows as a DataFrame.

    The grid reports its full contents (not a delta), so a button handler that runs
    before the grid re-renders (Add / Remove void) reads the last reported value;
    it falls back to the stable base if the grid has not reported yet (just
    re-seeded), so unsaved edits are never discarded.
    """
    value = st.session_state.get(ed_key)
    if not isinstance(value, list):   # absent / not yet reported -- use the base
        return st.session_state[base_key].copy().reset_index(drop=True)
    return _rows_to_df(value, cols)   # an empty list is a valid (cleared) grid


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


_AUTOSAVE_DEFAULT_MIN = 5     # default autosave interval (minutes), BriCoS-style


def _autosave_path() -> pathlib.Path:
    """The local autosave file. Overridable via ``SECTOR_AUTOSAVE_DIR`` (used by
    tests and for a packaged build's data folder); defaults to ``~/.sector``."""
    base = os.environ.get("SECTOR_AUTOSAVE_DIR") or (pathlib.Path.home() / ".sector")
    return pathlib.Path(base) / "autosave.json"


def _write_autosave(data: str, path) -> bool:
    """Atomically write the project JSON to ``path`` (creating the folder).

    The new content is written to a sibling temp file and then ``os.replace``d in,
    so a crash or power loss mid-write -- the very failure autosave guards against --
    cannot leave the recovery file empty or half-written; the old autosave survives
    until the new one is complete. Returns whether the write succeeded; never raises,
    so a read-only or missing folder cannot break the app."""
    path = pathlib.Path(path)
    tmp = path.parent / (path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(data, encoding="utf-8")
        os.replace(tmp, path)        # atomic on the same filesystem
        return True
    except Exception:
        try:
            tmp.unlink()
        except Exception:
            pass
        return False


def _perform_autosave() -> bool:
    """Write the current project to the autosave file, returning whether it wrote.

    Skips a section with no usable outline (fewer than three complete corners) and a
    project unchanged since the last autosave, so the recovery file is never
    overwritten with nothing or rewritten needlessly."""
    corners = _pts_from_df(_current_table("corners_base", "ed_corners", _CORNER_COLS),
                           _CORNER_COLS)
    if len(corners) < 3:
        return False   # no usable outline yet
    try:
        data = _gather_project()
    except Exception:
        return False
    if data == st.session_state.get("_autosave_data"):
        return False                                 # unchanged since the last save
    if _write_autosave(data, _autosave_path()):
        st.session_state["_autosave_data"] = data
        st.session_state["_autosave_last"] = datetime.now().strftime("%H:%M:%S")
        return True
    return False


def _reset_autosave_clock() -> None:
    st.session_state["_autosave_t"] = time.time()    # restart the interval on a change


def _maybe_autosave() -> None:
    """Autosave on user interaction once the interval has elapsed (the BriCoS model:
    the save rides the reruns that interaction triggers, so the app never reruns or
    saves while idle). Call from the main flow after the inputs are built."""
    if not st.session_state.get("autosave_on", True):
        return
    interval = max(1, int(st.session_state.get("autosave_min", _AUTOSAVE_DEFAULT_MIN))) * 60
    if time.time() - st.session_state.get("_autosave_t", 0.0) < interval:
        return
    st.session_state["_autosave_t"] = time.time()    # reset whether or not it writes
    if _perform_autosave():
        st.toast("Session autosaved.")


def _autosave_startup() -> None:
    """Once per session, restore the last autosaved project (the BriCoS principle:
    re-open where you left off) and start the autosave clock. A missing autosave
    just leaves the default section; an unreadable one starts fresh with a notice.
    An explicitly uploaded project takes precedence over the autosave."""
    if st.session_state.get("_autosave_init"):
        return
    st.session_state["_autosave_init"] = True
    st.session_state["_autosave_t"] = time.time()
    if "_pending_project" in st.session_state:
        return                                       # an upload is already pending
    path = _autosave_path()
    try:
        if not path.exists():
            return
        text = path.read_text(encoding="utf-8")
        project_io.parse_project(text)               # validate before restoring
    except Exception:
        st.session_state["_project_msg"] = (
            "error", "An autosave file was found but could not be read; "
                     "starting with the default section.")
        return
    st.session_state["_pending_project"] = text
    st.session_state["_autosave_restoring"] = True
    st.session_state["_autosave_data"] = text        # do not immediately re-save it


def _autosave_panel(box) -> None:
    """Autosave toggle, interval and status inside the Save / Load panel."""
    enabled = box.checkbox(
        "Autosave", value=True, key="autosave_on",
        help="Save the section, materials, loads and settings to a local file and "
             "restore them on the next launch. Saving happens as you work (on edits "
             "and clicks) once the interval has passed, not while the app is idle.")
    box.number_input(
        "Autosave interval (min)", 1, 120, _AUTOSAVE_DEFAULT_MIN, 1, key="autosave_min",
        disabled=not enabled, on_change=_reset_autosave_clock,
        help="Minutes between automatic saves.")
    last = st.session_state.get("_autosave_last")
    box.caption(f"Autosaved at {last}." if last
                else "Autosaves as you work; restored on the next launch.")


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
    ed_for_base = {base: ed for base, ed, _ in _PROJECT_TABLES}
    for key, df in tables.items():
        # Re-seed the grid (bump its version) so it rebuilds from the loaded points
        # rather than keeping the previous session's live state.
        _reseed_table(key, ed_for_base.get(key, key + "_ed"), df)
    for key, value in scalars.items():
        st.session_state[key] = value
    # Keep each preset's change-marker in step with the loaded preset so the panel
    # does not re-prefill over the loaded field values.
    for marker, src in project_io.PREV_MARKERS.items():
        if src in scalars:
            st.session_state[marker] = scalars[src]
    # For a strength-dependent edition (EN 2023) alpha_cc tracks fck via a hidden
    # marker; align it to the loaded fck so the loaded alpha_cc is not overwritten.
    if "conc_fck" in scalars:
        st.session_state["conc_alpha_fck"] = scalars["conc_fck"]
    for ed in ("ed_corners", "ed_hole", "ed_bars", "ed_tendons"):
        st.session_state.pop(ed, None)
    st.session_state["pts_init"] = True   # do not re-seed the tables from a template
    if st.session_state.pop("_autosave_restoring", False):
        st.session_state["_project_msg"] = ("success", "Restored your last autosaved session.")
    else:
        st.session_state["_project_msg"] = ("success", "Project loaded.")


def _save_load_panel(parent) -> None:
    """Download the current project and upload one to restore it.

    Rendered into a slot reserved near the top of the sidebar but only *after* the
    point tables and inputs have been seeded this run, so the download always
    reflects the live section (not an empty one on a fresh session).
    """
    box = parent.expander("Save / Load", expanded=False)
    box.download_button("Download project", data=_gather_project(),
                        file_name="sector_section.json", mime="application/json",
                        use_container_width=True,
                        help="Save the section, materials, loads and settings to a "
                             "JSON file.")
    _autosave_panel(box)
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


_REPORT_FIELDS = [("proj_no", "Project no."), ("proj_name", "Project name"),
                  ("section", "Section"), ("rev", "Revision"), ("author", "Author"),
                  ("checker", "Checker"), ("approver", "Approver")]

# The progress placeholder lives in the Report panel; report generation (which runs
# later in the same script run) fills it.
_REPORT_PROG = None


def _report_panel(parent):
    """Report metadata inputs plus Generate / Download, like the BriCoS panel."""
    box = parent.expander("Report", expanded=False)
    box.caption("Fill in the project details, press Generate, then download the PDF. "
                "The report uses the current inputs and the analyses for the selected "
                "mode.")
    box.text_input(_REPORT_FIELDS[0][1], key="rep_proj_no")
    box.text_input(_REPORT_FIELDS[1][1], key="rep_proj_name")
    box.text_input(_REPORT_FIELDS[2][1], key="rep_section")
    c1, c2 = box.columns(2)
    c1.text_input("Revision", key="rep_rev")
    c2.text_input("Author", key="rep_author")
    c3, c4 = box.columns(2)
    c3.text_input("Checker", key="rep_checker")
    c4.text_input("Approver", key="rep_approver")
    box.text_area("Comments", key="rep_comments", height=80)
    # Only flag the request here; the report is built at the end of the run, once
    # build_inputs has rendered every panel (so the materials/loads are complete).
    # Re-running now would abort this run before those panels set their values.
    if box.button("Generate report", type="primary", use_container_width=True,
                  key="gen_report"):
        st.session_state["_generating_report"] = True
    # A progress placeholder in the panel (filled live during generation, which runs
    # at the end of this same run), in the BriCoS location -- below the button.
    global _REPORT_PROG
    _REPORT_PROG = box.empty()
    msg = st.session_state.pop("_report_msg", None)
    if msg:
        (box.success if msg[0] == "success" else box.error)(msg[1])
    if st.session_state.get("report_buffer"):
        name = (st.session_state.get("rep_proj_no") or "section").strip() or "section"
        box.download_button("Download report (PDF)", st.session_state["report_buffer"],
                            file_name=f"Sector_report_{name}.pdf",
                            mime="application/pdf", use_container_width=True)


def _generate_report(inp):
    """Build the PDF from the current inputs when the Generate button was pressed."""
    if not st.session_state.pop("_generating_report", False):
        return
    if inp.get("section") is None or inp.get("void_error") or inp.get("steel_error"):
        st.session_state["_report_msg"] = ("error", "Define a valid section (and "
                                           "resolve any void or reinforcement error) "
                                           "before generating a report.")
        st.rerun()
    prog = _REPORT_PROG
    bar = prog.progress(0.0, text="Preparing report...") if prog is not None else None

    def _on_progress(frac, text="Generating report..."):
        if bar is not None:
            bar.progress(max(0.0, min(1.0, float(frac))), text=text)

    try:
        import sector_report
        meta = {k: st.session_state.get(f"rep_{k}", "")
                for k, _ in _REPORT_FIELDS}
        meta["comments"] = st.session_state.get("rep_comments", "")
        figs = not st.session_state.get("_report_no_figures", False)
        out = run_analysis(inp)
        pdf = sector_report.build_report(meta, inp, out, version=APP_VERSION,
                                         figures=figs, progress=_on_progress)
        st.session_state["report_buffer"] = pdf
        st.session_state["_report_msg"] = ("success", "Report generated - use the "
                                           "Download button in the Report panel.")
    except Exception as exc:                       # never let it crash the app
        st.session_state["_report_msg"] = ("error", f"Report generation failed: {exc}")
    if prog is not None:
        prog.empty()
    st.rerun()


_QS_SHAPES = ["Rectangle", "Slab strip", "T-section", "Box girder", "Circular"]

# The builder's own widget keys. Streamlit drops a widget's key from session state
# on any run where the widget is not rendered, so while the builder is closed these
# would be lost (resetting the builder to defaults on reopen, and dropping them
# from a saved project). The builder mirrors them to durable "qsv_" keys whenever it
# renders and restores them when it opens; project_io persists the durable copies.
_QS_WIDGET_KEYS = (
    "shape", "b_mm", "h_mm", "bf_mm", "hf_mm", "bw_mm", "hw_mm", "wall_mm",
    "dia_mm", "ring_n", "ring_d", "ring_c_mm", "qs_rebar_mode",
    "bot_n", "bot_d", "bot_s", "top_n", "top_d", "top_s",
    "bot_layers", "top_layers", "layer_s",
    "cover_mm", "tnd_n", "tnd_a", "tnd_c_mm", "tnd_layers", "tnd_layer_s",
)


def _qs_restore_settings():
    """Seed the builder widgets from their durable copies before they are created.

    Only fills a key that is absent (the closed-builder case); a key already present
    from the live widget this run is left alone, so in-progress edits are kept.
    """
    for k in _QS_WIDGET_KEYS:
        dk = "qsv_" + k
        if k not in st.session_state and dk in st.session_state:
            st.session_state[k] = st.session_state[dk]


def _qs_mirror_settings():
    """Copy the builder widgets to their durable keys, so the settings survive the
    builder being closed (and are what a saved project stores)."""
    for k in _QS_WIDGET_KEYS:
        if k in st.session_state:
            st.session_state["qsv_" + k] = st.session_state[k]


def _default_quick_section():
    """The section a fresh session starts from (used to seed the point tables): a
    400 x 600 mm rectangle with 6 bottom and 2 top 20 mm bars at 50 mm cover."""
    b, h, cov = 0.4, 0.6, 0.05
    outer = templates.rectangle(b, h)
    bars = templates.merge_bars(
        templates.bar_row(-h / 2 + cov, -b / 2 + cov, b / 2 - cov, 6, 20.0),
        templates.bar_row(h / 2 - cov, -b / 2 + cov, b / 2 - cov, 2, 20.0))
    return outer, [], bars, []


def _quick_section_geometry(box):
    """Render the shape, dimension and reinforcement inputs in ``box`` and return
    the generated ``(outer, holes, bars, tendons)`` (metres / mm areas).

    Shared by the builder viewport: the widgets keep their own keys so the last
    settings persist between openings. Reinforcement is two rows (bottom / top)
    placed either by bar count or by centre-to-centre spacing (slab ``phi @ s``);
    a circular section uses a perimeter ring.
    """
    shape = box.selectbox("Shape", _QS_SHAPES, key="shape",
                          help="Outline of the concrete cross-section to analyse.")
    holes = []
    if shape == "Rectangle":
        b = box.number_input(r"Width $b$ (mm)", 50.0, 10000.0, 400.0, 10.0, key="b_mm",
                             help="Overall section width.") / 1000.0
        h = box.number_input(r"Height $h$ (mm)", 50.0, 10000.0, 600.0, 10.0, key="h_mm",
                             help="Overall section height (depth).") / 1000.0
        outer = templates.rectangle(b, h)
        width_b = b
    elif shape == "Slab strip":
        h = box.number_input(r"Thickness $h$ (mm)", 50.0, 3000.0, 300.0, 10.0, key="h_mm",
                             help="Slab thickness; the strip is analysed per 1 m width.") / 1000.0
        b = width_b = 1.0
        outer = templates.slab_strip(h)
    elif shape == "T-section":
        bf = box.number_input(r"Flange width $b_f$ (mm)", 100.0, 12000.0, 1200.0, 10.0, key="bf_mm",
                              help="Width of the (top) flange.") / 1000.0
        hf = box.number_input(r"Flange thickness $h_f$ (mm)", 50.0, 2000.0, 200.0, 10.0, key="hf_mm",
                              help="Thickness of the flange.") / 1000.0
        bw = box.number_input(r"Web width $b_w$ (mm)", 50.0, 4000.0, 300.0, 10.0, key="bw_mm",
                              help="Width of the web.") / 1000.0
        hw = box.number_input(r"Web depth $h_w$ (mm)", 100.0, 6000.0, 600.0, 10.0, key="hw_mm",
                              help="Depth of the web below the flange.") / 1000.0
        outer = templates.t_section(bf, hf, bw, hw)
        b, h, width_b = bw, hf + hw, bf
    elif shape == "Box girder":
        b = box.number_input(r"Width $b$ (mm)", 200.0, 12000.0, 800.0, 10.0, key="b_mm",
                             help="Overall outer width of the box.") / 1000.0
        h = box.number_input(r"Height $h$ (mm)", 200.0, 12000.0, 1000.0, 10.0, key="h_mm",
                             help="Overall outer height of the box.") / 1000.0
        max_wall = round((min(b, h) / 2 - 0.01) * 1000.0, 0)
        wall = box.number_input("Wall thickness (mm)", 20.0, max_wall,
                                min(200.0, max_wall), 10.0, key="wall_mm",
                                help="Thickness of the box walls (uniform).") / 1000.0
        outer, holes = templates.box(b, h, wall)
        width_b = b
    else:  # Circular
        dia = box.number_input("Diameter (mm)", 100.0, 6000.0, 600.0, 10.0, key="dia_mm",
                               help="Outer diameter of the circular section.") / 1000.0
        outer = templates.circular(dia)
        b = h = width_b = dia

    box.markdown("**Reinforcement**")
    if shape == "Circular":
        nb = box.number_input("Perimeter bars", 0, 200, 8, 1, key="ring_n",
                              help="Number of bars evenly spaced around the perimeter.")
        rd = box.selectbox("Bar diameter (mm)", templates.BAR_DIAMETERS, index=4,
                           key="ring_d", help="Diameter of each reinforcement bar.")
        cov = box.number_input("Cover (mm)", 0.0, 500.0, 50.0, 5.0, key="ring_c_mm",
                               help="Distance from the section face to the bar centres.") / 1000.0
        bars = templates.bar_ring(0.0, 0.0, templates.ring_radius(dia, cov), int(nb), rd)
    else:
        by_spacing = box.radio(
            "Bar placement", ["By number", "By spacing"], horizontal=True,
            key="qs_rebar_mode",
            help="Place each row as a fixed bar count, or at a target centre-to-"
                 "centre spacing (slab phi @ s); the count is then derived from the "
                 "face width.") == "By spacing"
        cov = box.number_input("Cover (mm)", 0.0, 500.0, 50.0, 5.0, key="cover_mm",
                               help="Distance from the top/bottom face to the bar centres.") / 1000.0
        bot_w, top_w = b - 2.0 * cov, width_b - 2.0 * cov
        c1, c2 = box.columns(2)
        c1.markdown("**Bottom**")
        c2.markdown("**Top**")
        rd_bot = c1.selectbox("Bottom dia (mm)", templates.BAR_DIAMETERS, index=4,
                              key="bot_d", help="Bottom bar diameter (mm).")
        rd_top = c2.selectbox("Top dia (mm)", templates.BAR_DIAMETERS, index=4,
                              key="top_d", help="Top bar diameter (mm).")
        n_at_bot = n_at_top = None     # by-number: a fixed count per layer
        if by_spacing:
            s_bot = c1.number_input("Bottom spacing (mm)", 10.0, 1000.0, 150.0, 5.0,
                                    key="bot_s", help="Target centre-to-centre spacing.") / 1000.0
            s_top = c2.number_input("Top spacing (mm)", 10.0, 1000.0, 150.0, 5.0,
                                    key="top_s", help="Target centre-to-centre spacing.") / 1000.0
            nb_bot = templates.count_for_spacing(bot_w, s_bot)
            nb_top = templates.count_for_spacing(top_w, s_top)
            c1.caption(f"-> {nb_bot} bars")
            c2.caption(f"-> {nb_top} bars")

            # By spacing the count follows each row's own clear span, so a top row
            # narrowed to the web keeps the target spacing instead of the flange count.
            def n_at_bot(xs, xe):
                return templates.count_for_spacing(xe - xs, s_bot)

            def n_at_top(xs, xe):
                return templates.count_for_spacing(xe - xs, s_top)
        else:
            nb_bot = c1.number_input("Bottom bars", 0, 100, 6, 1, key="bot_n",
                                     help="Number of bars in each bottom layer.")
            nb_top = c2.number_input("Top bars", 0, 100, 2, 1, key="top_n",
                                     help="Number of bars in each top layer.")
        nl_bot = c1.number_input("Bottom layers", 1, 10, 1, 1, key="bot_layers",
                                 help="Number of stacked bar rows at the bottom face.")
        nl_top = c2.number_input("Top layers", 1, 10, 1, 1, key="top_layers",
                                 help="Number of stacked bar rows at the top face.")
        layer_s = box.number_input(
            "Layer spacing (mm)", 10.0, 1000.0, 60.0, 5.0, key="layer_s",
            disabled=int(nl_bot) == 1 and int(nl_top) == 1,
            help="Vertical centre-to-centre distance between stacked bar layers "
                 "(used only when a face has more than one layer).") / 1000.0
        # A T-section's top face is the flange (width width_b); a top layer pushed
        # below the flange must fit the narrower web (width b) or it would fall
        # outside the concrete. The bottom layers stay in the web (b) and only ever
        # widen into the flange, so they need no such limit.
        top_span_at = None
        if shape == "T-section":
            flange_y = h / 2 - hf

            def top_span_at(y):
                if y >= flange_y:                 # within the flange
                    return -width_b / 2 + cov, width_b / 2 - cov
                return -b / 2 + cov, b / 2 - cov  # below the flange -> the web

        if shape == "Box girder":
            # A box girder's rows split into the side walls once they rise into the
            # hollow, so multi-layer reinforcement keeps its count in the webs.
            bars = templates.merge_bars(
                templates.box_layers(-h / 2 + cov, 1.0, int(nl_bot), layer_s,
                                     b, h, wall, cov, int(nb_bot),
                                     templates.bar_area(rd_bot)),
                templates.box_layers(h / 2 - cov, -1.0, int(nl_top), layer_s,
                                     b, h, wall, cov, int(nb_top),
                                     templates.bar_area(rd_top)))
        else:
            bars = templates.merge_bars(
                templates.bar_layers(-h / 2 + cov, 1.0, int(nl_bot), layer_s,
                                     -b / 2 + cov, b / 2 - cov, int(nb_bot), rd_bot,
                                     n_at=n_at_bot),
                templates.bar_layers(h / 2 - cov, -1.0, int(nl_top), layer_s,
                                     -width_b / 2 + cov, width_b / 2 - cov,
                                     int(nb_top), rd_top, span_at=top_span_at, n_at=n_at_top))

    box.markdown("**Prestressing tendons**")
    nt = box.number_input("Tendons", 0, 200, 0, 1, key="tnd_n",
                          help="Number of tendons the Quick Section places (0 = none). "
                               "Tendons can also be entered directly in the points table.")
    a_t = box.number_input("Area per tendon (mm2)", 1.0, 50000.0, 150.0, 10.0, key="tnd_a",
                           help="Cross-sectional area of a single tendon.")
    cov_p = box.number_input("Tendon cover (mm)", 0.0, 2000.0, 100.0, 10.0, key="tnd_c_mm",
                             help="Distance from the bottom face (or the circular "
                                  "ring) to the tendons.") / 1000.0
    nl_t = box.number_input("Tendon layers", 1, 10, 1, 1, key="tnd_layers",
                            help="Number of stacked tendon rows from the bottom face "
                                 "(ignored for a circular ring).")
    ls_t = box.number_input(
        "Tendon layer spacing (mm)", 10.0, 1000.0, 60.0, 5.0, key="tnd_layer_s",
        disabled=int(nl_t) == 1,
        help="Vertical centre-to-centre distance between stacked tendon rows.") / 1000.0
    tendons = []
    if nt > 0:
        if shape == "Circular":
            tendons = templates.point_ring(
                0.0, 0.0, templates.ring_radius(b, cov_p), int(nt), a_t)
        elif shape == "Box girder":
            tendons = templates.box_layers(-h / 2 + cov_p, 1.0, int(nl_t), ls_t,
                                           b, h, wall, cov_p, int(nt), a_t)
        else:
            tendons = templates.point_layers(-h / 2 + cov_p, 1.0, int(nl_t), ls_t,
                                             -b / 2 + cov_p, b / 2 - cov_p, int(nt), a_t)
    return outer, (holes or []), bars, tendons


def _quick_section_viewport():
    """Full-width Quick Section builder shown in place of the analysis layout.

    Pick a shape, dimensions and a reinforcement layout with a live preview, then
    Apply to write explicit points into the editable tables (which stay the source
    of truth) or Back to leave them untouched. Mirrors the BriCoS manual viewport:
    a session flag (``_qs_open``) renders this instead of the normal layout.
    """
    _qs_restore_settings()   # bring back the settings from the last time it was open
    st.markdown("## Quick Section builder")
    st.caption("Generate a parametric section. Apply overwrites the corner, bar "
               "and tendon point tables with what is drawn here; Back discards it "
               "and leaves the current points untouched.")
    bcol, acol, _ = st.columns([1, 1, 3])
    back = bcol.button("Back", use_container_width=True, key="qs_back")
    apply = acol.button("Apply to point tables", type="primary",
                        use_container_width=True, key="qs_apply")

    form, preview = st.columns([2, 3])
    with form:
        outer, holes, bars, tendons = _quick_section_geometry(st)
    _qs_mirror_settings()   # keep the durable copy current with what is shown
    with preview:
        bar_xy = [(x, y) for x, y, _ in bars]
        tendon_xy = [(x, y) for x, y, _ in tendons]
        st.plotly_chart(
            viz.section_figure(outer, holes, bar_xy, tendons=tendon_xy,
                               title="Preview", show_labels=True, height=560,
                               scale=_MM, unit="mm"),
            use_container_width=True)
        st.caption(f"{len(outer)} concrete corners, {len(holes)} void(s), "
                   f"{len(bars)} bars, {len(tendons)} tendons.")

    if back:
        st.session_state["_qs_open"] = False
        st.rerun()
    if apply:
        qs_hole = [(float(p[0]), float(p[1])) for p in holes[0]] if holes else []
        _reseed_table("corners_base", "ed_corners", _corners_df(_pts_to_mm(
            [(float(p[0]), float(p[1])) for p in outer])))
        _reseed_table("hole_base", "ed_hole", _corners_df(_pts_to_mm(qs_hole)))
        _reseed_table("bars_base", "ed_bars", _rebar_df(_pts_to_mm(
            [(float(p[0]), float(p[1]), float(p[2])) for p in bars])))
        _reseed_table("tendons_base", "ed_tendons", _rebar_df(_pts_to_mm(
            [(float(p[0]), float(p[1]), float(p[2])) for p in tendons])))
        st.session_state["pts_init"] = True
        st.session_state["_qs_open"] = False
        st.rerun()


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
        st.markdown(f"**Sector v{APP_VERSION}**")
        st.caption(f"Author: {APP_AUTHOR}  \nEmail: {APP_EMAIL}")
        st.caption("Internal engineering tool, Sweco.")

    if s.button("User manual", key="open_manual", use_container_width=True,
                help="Open the full-width user manual: what Sector computes, the "
                     "theory it applies, its features, and how to use it."):
        st.session_state["_manual_open"] = True
        st.rerun()

    # Reserve the Save / Load slot here (near the top) but fill it at the end of
    # build_inputs, once the point tables and inputs exist, so the download
    # captures the live section even on a fresh session.
    save_slot = s.container()
    _report_panel(s)

    aset = s.expander("Analysis & Result Settings", expanded=False)
    mode = aset.radio("Analysis", ["Plastic", "Elastic", "Both"], key="mode",
                      help="Plastic: ultimate bending capacity (M-M envelope). "
                           "Elastic: cracked-section concrete and bar stresses "
                           "for the applied loads. Both: run the two.")
    plastic_on = mode in ("Plastic", "Both")
    elastic_on = mode in ("Elastic", "Both")

    # Recompute every auto-derived value from the current inputs in one click. It
    # sets a flag that each panel's Auto handler honours as it renders later this
    # run; the flag is cleared at the end of build_inputs (one-shot).
    if aset.button("Auto-calc all derived values", use_container_width=True,
                   key="auto_all_btn",
                   help="Recompute all auto values from the current grade and creep: "
                        "the concrete strain limits eps_c2/eps_cu2/n, fctm, Ec, and "
                        "the modular ratios n_l and n_s."):
        st.session_state["_auto_all"] = True

    aset.markdown("**Neutral-axis sweep (plastic)**")
    v_min = aset.number_input(r"Start angle $V_{min}$ (deg)", 0.0, 360.0, 0.0, 5.0,
                              key="v_min", disabled=not plastic_on,
                              help="First neutral-axis rotation angle of the plastic sweep.")
    v_max = aset.number_input(r"End angle $V_{max}$ (deg)", 0.0, 360.0, 360.0, 5.0,
                              key="v_max", disabled=not plastic_on,
                              help="Last neutral-axis rotation angle of the plastic sweep.")
    v_inc = aset.number_input(r"Increment $V_{inc}$ (deg)", 1.0, 90.0, 15.0, 1.0,
                              key="v_inc", disabled=not plastic_on,
                              help="Angular step between swept neutral-axis angles; "
                                   "a finer step gives a smoother M-M envelope.")
    check_util = aset.checkbox(
        "Check utilisation against applied moment", value=True, key="pl_check_util",
        disabled=not plastic_on,
        help="On: the applied plastic Mx/My are checked against the capacity envelope "
             "(utilisation). Off: report the capacity only -- the applied Mx/My are "
             "ignored and locked.")

    aset.markdown("**Serviceability (elastic SLS)**")
    aset.caption("Extra cracked-section checks in the Elastic view.")
    sls_cw = aset.checkbox("Crack width", value=False, key="sls_cw",
                           disabled=not elastic_on,
                           help="Report the EC2 crack width wk for both the long-term "
                                "and the short-term (instantaneous) load. Each bar's "
                                "clear cover is taken from the geometry.")
    sls_phi = aset.number_input(r"Crack-width bar diameter $\phi$ (mm, 0 = auto)", 0.0, 60.0,
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
    # Migrate the pre-coarse-system saved value before the selectbox reads it.
    if st.session_state.get("sls_code") in _CRACK_CODE_ALIASES:
        st.session_state["sls_code"] = _CRACK_CODE_ALIASES[st.session_state["sls_code"]]
    sls_code = aset.selectbox(
        "Crack-width code", list(_CRACK_CODES), key="sls_code",
        disabled=not (elastic_on and sls_cw),
        help="Code edition for the crack-spacing rules. The DK NA makes k3 cover-"
             "dependent (k3 = 3.4*(25/c)^(2/3)) and limits the (h-x)/3 effective-"
             "height term to slabs and prestressed members. The coarse crack system "
             "(7.3.4(1)) sets the effective area to the band whose centroid matches "
             "the tension reinforcement (figure 7.100 NA) and halves the crack width. "
             "EN 1992-1-1:2023 uses the refined model (9.2.3): wk = kw*k1/r*sr,m,cal*"
             "(esm-ecm) with kw = 1.7 and a per-bar curvature factor.")
    sls_dk_na = _CRACK_CODES[sls_code]["dk_na"]
    sls_coarse = _CRACK_CODES[sls_code]["coarse"]
    sls_edition = _CRACK_CODES[sls_code]["edition"]
    sls_member = aset.selectbox(
        "Member type", ["Beam", "Slab"], key="sls_member",
        disabled=not (elastic_on and sls_cw and sls_dk_na and not sls_coarse),
        help="Under the DK NA fine system the (h-x)/3 effective-height term applies "
             "only to slabs (and prestressed members); for a beam it is dropped. "
             "Ignored for the base EN 1992-1-1 code and the coarse crack system "
             "(which uses the centroid-matched effective area, not hc,ef).")

    sec = s.expander("Section", expanded=True)
    sec.caption("The section is a set of explicit points (the source of truth). "
                "Use the Quick Section builder to generate a parametric shape and "
                "write its points here, or edit the point tables directly.")
    if sec.button("Quick Section builder...", key="open_qs", use_container_width=True,
                  help="Open a full-width builder: pick a shape, dimensions and "
                       "reinforcement with a live preview, then Apply to fill the "
                       "point tables."):
        st.session_state["_qs_open"] = True
        st.rerun()
    clear_pts = sec.button("Clear Section (empty all points)", key="clear_pts",
                           use_container_width=True,
                           help="Remove every concrete corner, the void, and all "
                                "bars and tendons from the point tables, to start "
                                "from a blank section.")
    if "pts_init" not in st.session_state:
        # Seed the tables once from the default Quick Section (metres -> mm).
        d_outer, d_holes, d_bars, d_tendons = _default_quick_section()
        d_hole = [(float(p[0]), float(p[1])) for p in d_holes[0]] if d_holes else []
        _reseed_table("corners_base", "ed_corners", _corners_df(_pts_to_mm(
            [(float(p[0]), float(p[1])) for p in d_outer])))
        _reseed_table("hole_base", "ed_hole", _corners_df(_pts_to_mm(d_hole)))
        _reseed_table("bars_base", "ed_bars", _rebar_df(_pts_to_mm(
            [(float(p[0]), float(p[1]), float(p[2])) for p in d_bars])))
        _reseed_table("tendons_base", "ed_tendons", _rebar_df(_pts_to_mm(
            [(float(p[0]), float(p[1]), float(p[2])) for p in d_tendons])))
        st.session_state["pts_init"] = True
    if clear_pts:
        # Empty every point table (corners, void, bars, tendons) and drop the live
        # editor edits, so the section starts blank.
        _reseed_table("corners_base", "ed_corners", _corners_df([]))
        _reseed_table("hole_base", "ed_hole", _corners_df([]))
        _reseed_table("bars_base", "ed_bars", _rebar_df([]))
        _reseed_table("tendons_base", "ed_tendons", _rebar_df([]))
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
        if df is None:
            # A loaded or partial project may omit a table (e.g. a non-prestressed
            # project has no tendon table); seed it empty so the always-mounted
            # grid has a base to read.
            st.session_state[base_key] = (_corners_df([]) if cols is _CORNER_COLS
                                          else _rebar_df([]))
            continue
        if list(df.columns) != cols:
            if set(cols).issubset(df.columns):
                _reseed_table(base_key, ed_key, df.reindex(columns=cols))  # drop legacy ID col
            else:   # an older schema (e.g. metre column names) -> reset to empty
                _reseed_table(base_key, ed_key, _corners_df([]) if cols is _CORNER_COLS
                              else _rebar_df([]))

    sec.markdown("**Cross-section points** (the analysis uses these)")
    sec.caption("Concrete corners define the outline (3 or more, in order); the "
                "voids are optional inner rings. Bars and tendons are points with an "
                "area (mm2). Type or paste values (a block copied from a spreadsheet "
                "auto-grows the table); a point is used once all its cells are "
                "filled. The frozen ID column numbers the points to match the plots. "
                "Use the Quick Section builder to refill the tables.")
    sec.markdown("_Concrete corners_")
    outer_mm = _point_editor(sec, "corners_base", "ed_corners", _CORNER_COLS, 1)
    outer = _pts_to_m(outer_mm)
    if len(outer) < 3:
        # No valid outline. Leave it empty (do NOT fall back to the Quick Section,
        # or Clear Section would silently revert to the template) and let the
        # downstream treat the section as blank.
        sec.warning("The section has no concrete outline. Add at least 3 corners, "
                    "or open the Quick Section builder.")
    sec.markdown("_Concrete voids_")
    sec.caption("Several voids share this table, each separated by a blank row "
                "(each void needs 3 or more corners).")
    # The buttons act on the grid's current rows (its last reported value) so typing
    # a void and then adding/removing one does not discard the in-progress corners.
    void_now = _current_table("hole_base", "ed_hole", _CORNER_COLS)
    n_voids = len(_void_groups(void_now, _CORNER_COLS))
    vc1, vc2 = sec.columns(2)
    if vc1.button("+ Add void", key="add_void", use_container_width=True,
                  disabled=n_voids >= _MAX_VOIDS,
                  help=f"Append a blank separator row, so the next corners you enter "
                       f"start a new void (up to {_MAX_VOIDS})."):
        groups = _void_groups(void_now, _CORNER_COLS)
        _reseed_table("hole_base", "ed_hole",
                      _void_table_from_groups(groups, trailing_blank=True))
    if vc2.button("Remove void", key="rem_void", use_container_width=True,
                  disabled=n_voids == 0, help="Drop the last void from the table."):
        groups = _void_groups(void_now, _CORNER_COLS)
        _reseed_table("hole_base", "ed_hole", _void_table_from_groups(groups[:-1]))
    holes_mm = _void_editor(sec, "hole_base", "ed_hole", len(outer) + 1)
    holes = [_pts_to_m(ring) for ring in holes_mm]
    sec.markdown("_Reinforcing bars_")
    bars_mm = _point_editor(sec, "bars_base", "ed_bars", _REBAR_COLS, 1)
    bars = _pts_to_m(bars_mm)
    # Tendons are always definable; they only enter the analysis and the report when
    # at least one is present (a section with no tendons is simply not prestressed).
    sec.markdown("_Tendons_")
    tendons_mm = _point_editor(sec, "tendons_base", "ed_tendons", _REBAR_COLS,
                               len(bars) + 1)
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
    # The reinforcement laws are always definable; whether each is used follows from
    # the section (mild steel when bars exist, prestress when tendons exist).
    mat.divider()
    prestress = prestress_panel(mat, locked=lock_mats)

    # Loads: the plastic and elastic analyses take their own load sets, so a
    # capacity check (e.g. ULS) and a stress check (e.g. SLS) use different
    # actions without overwriting each other. The plastic axial force fixes the
    # M-M envelope; its moments are the point checked against it. Both sets stay
    # mounted (the inactive one is disabled) so their values survive a mode
    # switch instead of being reset when Streamlit drops unrendered widgets.
    loads = s.expander("Loads", expanded=True)

    def _load_set(prefix, n_help, m_help, active, mx_default=200.0, moments_active=None):
        # ``moments_active`` lets the moments lock independently of the axial force
        # (the plastic capacity-only mode keeps N but disables the applied moments).
        moments_active = active if moments_active is None else moments_active
        P = loads.number_input(r"Axial force $N$ (kN, + = compression)", -50000.0,
                               50000.0, 0.0, 50.0, key=f"{prefix}_P", help=n_help,
                               disabled=not active)
        Mx = loads.number_input(r"Applied $M_x$ (kNm)", -100000.0, 100000.0, mx_default,
                                10.0, key=f"{prefix}_Mx", disabled=not moments_active,
                                help=f"{m_help} Bending moment about the x-axis "
                                     "(its stress varies with y).")
        My = loads.number_input(r"Applied $M_y$ (kNm)", -100000.0, 100000.0, 0.0, 10.0,
                                key=f"{prefix}_My", disabled=not moments_active,
                                help="Bending moment about the y-axis (its stress "
                                     "varies with x); biaxial bending.")
        return P, Mx, My

    loads.markdown("**Plastic capacity**")
    P_pl, Mx_pl, My_pl = _load_set(
        "pl", "Axial force for which the plastic M-M capacity envelope is computed.",
        "Applied moment checked against the plastic envelope (utilisation).",
        plastic_on, moments_active=plastic_on and check_util)

    loads.divider()
    loads.markdown("**Elastic stresses (long + short term)**")
    loads.caption("Long-term and short-term load with their own modular ratios "
                  "(the creep analysis). For a simple check leave the short-term "
                  "load at zero and set both ratios equal.")
    loads.markdown("_Long-term_")
    P_el_l, Mx_el_l, My_el_l = _load_set(
        "el_long", "Sustained external axial force (long-term). A tendon's prestress "
        "is applied automatically from its initial strain, so N is the external "
        "force only -- as in the plastic solver; do not add the prestress force here.",
        "Sustained moment (long-term).", elastic_on)
    phi_creep = loads.number_input(r"Creep coefficient $\varphi$ (long-term)", 0.0, 5.0, 3.0,
                                   0.1, key="el_phi", disabled=not elastic_on,
                                   help="Final creep coefficient for the long-term "
                                        "modular ratio n_l = Es*(1+phi)/Ec.")
    _nl_auto = round(min(50.0, max(1.0, steel.Es * (1.0 + phi_creep)
                                   / (conc_Ec * 1000.0))), 1)
    st.session_state.setdefault("nl", _nl_auto)   # default from Ec, phi (EC2)
    if (loads.button(f"Auto $n_l$ ($E_s(1+\\varphi)/E_c$ = {_nl_auto:.1f})", key="nl_auto",
                     disabled=not elastic_on, use_container_width=True,
                     help="Long-term modular ratio from the concrete Ec, creep-reduced "
                          "by phi (effective-modulus method).")
            or (st.session_state.get("_auto_all", False) and elastic_on)):
        st.session_state["nl"] = _nl_auto
    nl = loads.number_input(r"Long-term modular ratio $n_l = E_s/E_{c,eff}$", 1.0, 50.0,
                            step=0.5, key="nl", disabled=not elastic_on,
                            help="Modular ratio for the sustained load (creep-reduced "
                                 "concrete stiffness, so larger than the short-term "
                                 "ratio). Use Auto to derive it from Ec and phi.")
    loads.markdown("_Short-term_")
    P_el_s, Mx_el_s, My_el_s = _load_set(
        "el_short", "Instantaneous (variable) external axial force (prestress is "
        "applied automatically from the tendon initial strain).",
        "Instantaneous (variable) moment.", elastic_on, mx_default=0.0)
    _ns_auto = round(min(50.0, max(1.0, steel.Es / (conc_Ec * 1000.0))), 1)
    st.session_state.setdefault("ns", _ns_auto)   # default from Ec (Es/Ec)
    if (loads.button(f"Auto $n_s$ ($E_s/E_c$ = {_ns_auto:.1f})", key="ns_auto",
                     disabled=not elastic_on, use_container_width=True,
                     help="Short-term (instantaneous) modular ratio from the concrete Ec.")
            or (st.session_state.get("_auto_all", False) and elastic_on)):
        st.session_state["ns"] = _ns_auto
    ns = loads.number_input(r"Short-term modular ratio $n_s = E_s/E_c$", 1.0, 50.0,
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
    # Every reinforcing bar and tendon must sit in the concrete: outside the outline
    # or inside a void it carries no force, so the section is ill-defined. Checked
    # only once the outline itself is valid (a void error is the more basic fault).
    steel_error = None
    if section is not None and not void_error:
        steel_pts = list(bars) + list(tendons)
        if steel_pts:
            ok = geometry.points_inside_concrete(steel_pts, outer, holes)
            nb = len(bars)
            bad_bars = [i + 1 for i in range(nb) if not ok[i]]
            bad_tendons = [i - nb + 1 for i in range(nb, len(steel_pts)) if not ok[i]]
            parts = []
            if bad_bars:
                parts.append(f"bar(s) {', '.join(map(str, bad_bars))}")
            if bad_tendons:
                parts.append(f"tendon(s) {', '.join(map(str, bad_tendons))}")
            if parts:
                steel_error = ("Reinforcement must lie within the concrete: "
                               + " and ".join(parts) + " fall outside the section "
                               "or inside a void. Move them into the concrete.")
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
            "pre_preset",
            "pre_IS", "pre_fytk", "pre_futk", "pre_eut", "pre_gamma_y",
            "pre_gamma_u", "pre_gamma_E", "pre_k", "pre_ey0t", "pre_Es",
            "pl_P", "pl_Mx", "pl_My", "el_long_P", "el_long_Mx", "el_long_My",
            "nl", "el_short_P", "el_short_Mx", "el_short_My", "ns",
            "v_min", "v_max", "v_inc", "mode", "pl_check_util",
            "sls_cw", "sls_fctm", "sls_phi", "sls_bond",
            "sls_code", "sls_member"))
    st.session_state.pop("_auto_all", None)   # one-shot: applied this run only
    _save_load_panel(save_slot)   # fill the reserved slot now the inputs exist
    return dict(section=section, void_error=void_error, steel_error=steel_error,
                concrete=concrete, steel=steel,
                bars=bars, outer=outer, holes=holes, tendons=tendons,
                prestress=prestress, P_pl=P_pl, Mx_pl=Mx_pl, My_pl=My_pl,
                check_util=check_util,
                v_min=v_min, v_max=v_max, v_inc=v_inc,
                P_el_l=P_el_l, Mx_el_l=Mx_el_l, My_el_l=My_el_l, nl=nl,
                P_el_s=P_el_s, Mx_el_s=Mx_el_s, My_el_s=My_el_s, ns=ns,
                sls_cw=sls_cw, sls_fctm=sls_fctm, sls_phi=sls_phi,
                sls_k1=sls_k1, sls_dk_na=sls_dk_na, sls_coarse=sls_coarse,
                sls_edition=sls_edition, sls_code=sls_code, sls_member=sls_member,
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
                phi=cw.phi, cover=cw.cover, gov_bar=cw.gov_bar + 1, coarse=cw.coarse,
                edition=cw.edition, kw=cw.kw, k1_r=cw.k1_r, kfl=cw.kfl,
                sr_max_geometric=cw.sr_max_geometric)


def run_analysis(inp):
    out = {}
    if inp["section"] is None or inp.get("void_error") or inp.get("steel_error"):
        return out                          # invalid section -> nothing to run
    if inp["mode"] in ("Plastic", "Both"):
        vlo, vhi, vstep = _sweep(inp["v_min"], inp["v_max"], inp["v_inc"])
        # Prestress enters the analysis only when the section actually has tendons.
        pre = inp["prestress"] if inp["tendons"] else None
        pts = solve_plastic(inp["section"], inp["concrete"], inp["steel"],
                            inp["P_pl"], vlo, vhi, vstep, prestress=pre)
        mx = [p.Mx for p in pts]
        my = [p.My for p in pts]
        # Utilisation interpolates the capacity in the applied direction, which is
        # only a closed envelope when the sweep spans the full 360 deg. A partial
        # sweep is an open arc, so report no utilisation rather than a wrap-around
        # interpolation between the arc endpoints.
        closed = (vhi - vlo) >= 360.0 - 1e-6
        # Utilisation is only reported when the user asks to check it; otherwise this
        # is a capacity-only run (the applied moments are ignored and locked).
        check_util = inp.get("check_util", True)
        util = (_radial_util(mx, my, inp["Mx_pl"], inp["My_pl"])
                if (closed and check_util) else None)
        out["plastic"] = dict(
            mx=mx, my=my,
            max_mx=max(mx), max_my=max(my), min_mx=min(mx), min_my=min(my),
            util=util, closed=closed, check_util=check_util,
            applied=((inp["Mx_pl"], inp["My_pl"]) if check_util else None),
            converged=all(p.converged for p in pts),
            points=[dict(V=p.V, Mx=p.Mx, My=p.My, na_x=p.na_x_intercept,
                         na_y=p.na_y_intercept, eps_c=p.eps_concrete,
                         eps_s=p.eps_steel, eps_cable=p.eps_cable, kappa=p.curvature,
                         comp_force=p.compression_force, lever=p.lever_arm,
                         dx=p.dx, dy=p.dy) for p in pts],
        )
    if inp["mode"] in ("Elastic", "Both"):
        # Tendons are folded into the bar set for the elastic run. Each tendon uses
        # its own modular ratio (Ep/Ec, via the multiplier Ep/Es) and carries the
        # locked-in prestress Ep*IS, applied as a force so the user's N is the
        # external normal force only -- matching the plastic solver.
        sec = inp["section"]
        n_mult = prestress_stress = pre_resultant = None
        if inp["tendons"]:
            sec = Section.from_polygon(corners=inp["outer"],
                                       bars_xy_area_mm2=list(inp["bars"]) + list(inp["tendons"]),
                                       holes=inp["holes"])
            pre_mat = inp["prestress"]
            if pre_mat is not None:
                nb, nt = len(inp["bars"]), len(inp["tendons"])
                ep, es = pre_mat.Es, inp["steel"].Es
                sig_ps = ep * pre_mat.IS * 1000.0   # MPa -> kN/m2 (bar-stress units)
                n_mult = np.array([1.0] * nb + [ep / es] * nt)
                prestress_stress = np.array([0.0] * nb + [sig_ps] * nt)
                bx, by, ba = sec.bar_arrays()
                f = prestress_stress * ba           # kN per tendon
                pre_resultant = (float(f.sum()), float((f * by).sum()),
                                 float((f * bx).sum()))   # N, Mx, My (kN, kNm)
        r = solve_elastic_combined(sec, inp["P_el_l"], inp["Mx_el_l"], inp["My_el_l"],
                                   inp["nl"], inp["P_el_s"], inp["Mx_el_s"],
                                   inp["My_el_s"], inp["ns"],
                                   n_mult=n_mult, prestress_stress=prestress_stress)
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
            prestress=pre_resultant,
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
        # Cracking is irreversible and is triggered by the *maximum* load the
        # section ever sees, so the cracked decision uses the total (long + short)
        # load, not the sustained part alone: a section that only cracks under the
        # short-term peak is still cracked (and has a quasi-permanent crack width to
        # check). The instantaneous modular ratio ns applies to that peak event.
        cr_t = analyse_cracking(
            sec, inp["P_el_l"] + inp["P_el_s"], inp["Mx_el_l"] + inp["Mx_el_s"],
            inp["My_el_l"] + inp["My_el_s"], inp["ns"],
            fctm=inp["sls_fctm"], Es=inp["steel"].Es, beta=1.0, kt=0.6,
            bar_diameter=phi, k1=k1_bars, k3_cover_dependent=dk_na,
            include_hx_term=include_hx, coarse=inp["sls_coarse"],
            edition=inp["sls_edition"], n_mult=n_mult,
            prestress_stress=prestress_stress)
        # The long-term (quasi-permanent) cracked state drives the code-limit crack
        # width and the reported section properties.
        cr_l = analyse_cracking(
            sec, inp["P_el_l"], inp["Mx_el_l"], inp["My_el_l"], inp["nl"],
            fctm=inp["sls_fctm"], Es=inp["steel"].Es, beta=0.5, kt=0.4,
            bar_diameter=phi, k1=k1_bars,
            k3_cover_dependent=dk_na, include_hx_term=include_hx,
            coarse=inp["sls_coarse"], edition=inp["sls_edition"],
            n_mult=n_mult, prestress_stress=prestress_stress)
        # The section is cracked if EITHER the long-term or the total action exceeds
        # the cracking stress: cracking is irreversible, so a short-term action that
        # counteracts the sustained one (a negative moment) can leave the total
        # uncracked while the long-term already cracked. Report the governing (most
        # onerous, smallest lambda_cr) of the two.
        cr_gov = cr_t if cr_t.lambda_cr <= cr_l.lambda_cr else cr_l
        cracked = cr_gov.cracked
        props_un = transformed_properties(sec, inp["nl"], cracked=False)
        # The cracked transformed properties use the governing cracked state's
        # strain plane (which fibres are in compression). Building them from the
        # long-term state would keep the full section when the section is cracked
        # only by the short-term action and the long-term load is (near) zero.
        props_cr = (transformed_properties(
            sec, inp["nl"], eps0=cr_gov.cracked_state.eps0,
            kx=cr_gov.cracked_state.kx, ky=cr_gov.cracked_state.ky, cracked=True)
            if cracked else None)
        out["elastic"].update(
            cracked=cracked, lambda_cr=cr_gov.lambda_cr, sigma_ct=cr_gov.sigma_ct,
            fctm=cr_gov.fctm, show_cw=inp["sls_cw"],
            props_un=_props_dict(props_un),
            props_cr=(_props_dict(props_cr) if props_cr is not None else None),
            crack=None, crack_short=None,
        )
        # Crack width is its own opt-in, reported for both load cases once the
        # section has cracked. The short-term state reuses the combined creep solve
        # `r`: its instantaneous neutral axis with the displayed total steel stress
        # (s2 + RST1), so the crack-width sigma_s matches the Total column rather
        # than a raw (long+short)-at-ns solve. Each bar's cover comes from geometry.
        if inp["sls_cw"] and cracked:
            # Long-term crack width on the cracked section under the quasi-permanent
            # load (kt = 0.4). Computed directly from the long-term cracked state so
            # it is reported even when the long-term load alone would not cross the
            # cracking threshold (the section is cracked by the short-term peak).
            cw_long = crack_width(sec, cr_l.cracked_state, inp["nl"],
                                  fctm=inp["sls_fctm"], Es=inp["steel"].Es, kt=0.4,
                                  bar_diameter=phi, k1=k1_bars,
                                  k3_cover_dependent=dk_na, include_hx_term=include_hx,
                                  coarse=inp["sls_coarse"], edition=inp["sls_edition"],
                                  n_mult=n_mult)
            # Crack width uses the load-induced steel stress, so strip the locked-in
            # tendon prestress back out of the reported total (mild bars unaffected).
            cw_stress = np.asarray(r.bar_stress_total, dtype=float)
            if prestress_stress is not None:
                cw_stress = cw_stress - prestress_stress
            short_state = dataclasses.replace(r.short_term, bar_stress=cw_stress)
            cw_short = crack_width(sec, short_state, inp["ns"], fctm=inp["sls_fctm"],
                                   Es=inp["steel"].Es, kt=0.6, bar_diameter=phi,
                                   k1=k1_bars, k3_cover_dependent=dk_na,
                                   include_hx_term=include_hx, coarse=inp["sls_coarse"],
                                   edition=inp["sls_edition"], n_mult=n_mult)
            out["elastic"].update(
                crack=_crack_dict(cw_long), crack_short=_crack_dict(cw_short),
                crack_code=inp["sls_code"],
                crack_member=(inp["sls_member"] if dk_na else None),
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


def _memo_fig(name, sig, build):
    """Return a cached live figure, rebuilding only when its inputs change.

    Streamlit reruns the whole script on every widget change, so the live Section
    and Stress-Strain views would otherwise re-run the ~10-20 ms plotly figure
    construction each time -- e.g. rebuilding the material curves when the user
    only touched a load. One slot per figure kind is kept in session state, keyed
    by ``sig`` (compared by value); the figure is reused in place rather than
    pickled (unlike ``st.cache_data``), which is safe because the views only read
    it. On a cache miss the cost is just the rebuild that would happen anyway, so
    this never makes the point-editing path (where the geometry changes every
    keystroke) slower.
    """
    cache = st.session_state.setdefault("_fig_cache", {})
    entry = cache.get(name)
    if entry is None or entry[0] != sig:
        entry = cache[name] = (sig, build())
    return entry[1]


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
    sig = (inp["outer"], inp["holes"], bar_xy, tendon_xy,
           inp["label_scale"], inp["label_min_gap"])
    fig = _memo_fig("section", sig, lambda: viz.section_figure(
        inp["outer"], inp["holes"], bar_xy, title="Section", tendons=tendon_xy,
        show_labels=True, label_scale=inp["label_scale"],
        label_min_gap=inp["label_min_gap"], height=640, scale=_MM, unit="mm"))
    st.plotly_chart(fig, use_container_width=True)


def materials_view(inp):
    """Stress-strain diagrams for the chosen materials (live, no Calculate).

    One diagram per row (full width) so each curve is large and easy to read. The
    material objects are value-comparable (frozen dataclasses), so the figures are
    memoised on them and only rebuilt when a material parameter actually changes.
    """
    conc, steel, pre = inp["concrete"], inp["steel"], inp["prestress"]
    st.plotly_chart(_memo_fig("concrete", conc, lambda: viz.concrete_curve_figure(conc)),
                    use_container_width=True)
    st.plotly_chart(_memo_fig("steel", steel, lambda: viz.steel_curve_figure(steel)),
                    use_container_width=True)
    if pre is not None:
        st.plotly_chart(_memo_fig("prestress", pre, lambda: viz.prestress_curve_figure(pre)),
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
        f"{_EPS}c (%)": [round(pt["eps_c"], 2) for pt in pts],
        f"{_EPS}s (%)": [round(pt["eps_s"], 2) for pt in pts],
        f"{_KAPPA} (1/m)": [round(pt["kappa"], 4) for pt in pts],
        "Comp (kN)": [round(pt["comp_force"], 0) for pt in pts],
        "L (mm)": [round(pt["lever"] * _MM, 1) for pt in pts],
        "Dx (mm)": [round(pt["dx"] * _MM, 1) for pt in pts],
        "Dy (mm)": [round(pt["dy"] * _MM, 1) for pt in pts],
    }
    if cable:
        cols[f"{_EPS}cable (%)"] = [round(pt["eps_cable"], 2) for pt in pts]
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
    # Derive the minima from the envelope if absent, so a result payload cached
    # before min_mx/min_my existed (matching inputs -> no recompute) still renders.
    min_mx = p.get("min_mx", min(p["mx"]))
    min_my = p.get("min_my", min(p["my"]))
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Max $M_x$", f"{p['max_mx']:.0f} kNm")
    m2.metric("Min $M_x$", f"{min_mx:.0f} kNm")
    m3.metric("Max $M_y$", f"{p['max_my']:.0f} kNm")
    m4.metric("Min $M_y$", f"{min_my:.0f} kNm")
    if not p.get("check_util", True):
        m5.metric("Utilisation", "-",
                  help="Capacity-only run: the applied moments are not checked. "
                       "Enable 'Check utilisation against applied moment' to check.")
    elif p["util"] is None:
        m5.metric("Utilisation", "-",
                  help="Only meaningful for a full 0-360 deg sweep; the current "
                       "sweep is a partial arc.")
    else:
        m5.metric("Utilisation", f"{p['util']:.2f}",
                  help="applied / capacity in the load direction")
    st.plotly_chart(
        viz.interaction_figure(p["mx"], p["my"], applied=p.get("applied")),
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
    hp = viz.plastic_halfplane(pt["V"], pt["na_x"], pt["na_y"])
    na = viz.na_line_at(hp[0], hp[1], hp[2], inp["extent"])
    cL, cR = st.columns([3, 2])
    with cL:
        bar_xy = [(b[0], b[1]) for b in inp["bars"]]
        tendon_xy = [(t[0], t[1]) for t in inp["tendons"]]
        st.plotly_chart(
            viz.section_figure(inp["outer"], inp["holes"], bar_xy, na_line=na,
                               tendons=tendon_xy, zones=viz.compression_zones(inp["outer"], hp),
                               title=f"Section at V = {pt['V']:.0f} deg",
                               show_labels=True, label_scale=inp["label_scale"],
                               label_min_gap=inp["label_min_gap"], scale=_MM, unit="mm"),
            use_container_width=True)
    with cR:
        lines = [
            f"- **$M_x$ / $M_y$**: {pt['Mx']:.0f} / {pt['My']:.0f} kNm",
            f"- **Curvature $\\kappa$**: {pt['kappa']:.4g} 1/m",
            f"- **Compression force**: {pt['comp_force']:.0f} kN",
            f"- **Lever arm $L$**: {pt['lever'] * _MM:.0f} mm  "
            f"($D_x$ {pt['dx'] * _MM:.0f}, $D_y$ {pt['dy'] * _MM:.0f})",
            f"- **Concrete strain $\\varepsilon_c$**: {pt['eps_c']:.2f} %",
            f"- **Steel strain $\\varepsilon_s$**: {pt['eps_s']:.2f} %",
            f"- **NA intercepts**: x {_fmt(pt['na_x'] * _MM)}, "
            f"y {_fmt(pt['na_y'] * _MM)} mm",
        ]
        if inp["tendons"]:
            lines.insert(6, f"- **Tendon strain $\\varepsilon_p$**: {pt['eps_cable']:.2f} %")
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

    # The tendon prestress is applied automatically from the initial strain, so N
    # is the external force only; show the equivalent prestress action that was added.
    ps = e.get("prestress")
    if ps is not None:
        st.caption(f"Applied tendon prestress (from the initial strain): "
                   f"N = {ps[0]:.0f} kN, $M_x$ = {ps[1]:.0f} kNm, $M_y$ = {ps[2]:.0f} kNm "
                   f"(compression positive; this is added to the external N/M).")

    # The neutral axis and the compression/tension zones only make sense when the
    # concrete actually carries compression; a fully tensile case has none.
    has_comp = e["max_conc"] > 0.0
    if has_comp:
        st.caption(f"Neutral-axis intercepts (for concrete stress): "
                   f"x {_fmt(e['na_x'] * _MM)} mm,  y {_fmt(e['na_y'] * _MM)} mm")
    else:
        st.caption("The concrete carries no compression (the section is fully "
                   "cracked in tension); no neutral axis is shown.")

    hp = viz.elastic_halfplane(e["na_x"], e["na_y"], e["max_conc_xy"]) if has_comp else None
    na = viz.na_line_at(hp[0], hp[1], hp[2], inp["extent"]) if hp else None
    zones = viz.compression_zones(inp["outer"], hp) if hp else None
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
    st.caption(
        "**Total** = long + short  \n"
        "**Long** = long-term alone  \n"
        "**Dif** = total - long  \n"
        "**RST1** = instantaneous response with the long-term concrete stresses "
        "neutralised.")

    _elastic_sls_section(inp, e)


def _elastic_sls_section(inp, e):
    """Serviceability sub-report inside the elastic view: the cracking threshold
    and transformed section properties (always); crack width is an independent
    opt-in. The cracking decision is on the *total* (long + short) load -- cracking
    is triggered by the peak load the section ever sees and is irreversible -- while
    the crack width is reported for both the long-term (quasi-permanent, the
    code-limit case) and the short-term (instantaneous) load."""
    if "cracked" not in e:
        return
    show_cw = e.get("show_cw", False)
    st.divider()
    st.markdown("#### Serviceability checks")
    if e["cracked"]:
        st.warning(f"**Cracked** - the uncracked concrete tension reaches $f_{{ctm}}$ "
                   f"at a load factor $\\lambda_{{cr}}$ = {e['lambda_cr']:.3f} "
                   f"(governing of the long-term and total actions; "
                   f"= $M_{{cr}}/M$ for pure bending).")
    else:
        lam = "infinite" if math.isinf(e["lambda_cr"]) else f"{e['lambda_cr']:.2f}"
        st.success(f"**Uncracked** - peak concrete tension {e['sigma_ct']:.2f} MPa "
                   f"< $f_{{ctm}}$ {e['fctm']:.2f} MPa under both the long-term and "
                   f"the total action ($\\lambda_{{cr}}$ = {lam}).")

    st.metric(r"Cracking factor $\lambda_{cr}$",
              "inf" if math.isinf(e["lambda_cr"]) else f"{e['lambda_cr']:.3f}",
              help="Proportional load factor to first cracking, fctm / sigma_ct,I "
                   "(= Mcr/M in pure bending), taken as the governing (smaller) of "
                   "the long-term and total actions. < 1 = cracked.")

    pL, pR = st.columns(2)
    with pL:
        st.markdown(r"**Transformed section properties (at $n_l$)**")
        un = e["props_un"]
        cr = e.get("props_cr")
        rows = ["Area A (m2)", "Centroid x (m)", "Centroid y (m)",
                "Ix about x-axis (m4)", "Iy about y-axis (m4)", "Ixy (m4)"]
        keys = ["area", "cx", "cy", "Ix", "Iy", "Ixy"]
        data = {"Property": rows, "Uncracked": [f"{un[k]:.4g}" for k in keys]}
        if cr is not None:
            data["Cracked"] = [f"{cr[k]:.4g}" for k in keys]
        st.dataframe(data, hide_index=True, use_container_width=True)
        st.caption("Transformed ($n_l$-weighted) properties about the section "
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
    st.markdown(f"**Crack width $w_k$** ({e.get('crack_code', 'EC2 7.3.4')})")
    if cl is None and cs is None:
        st.info("No crack width: uncracked, or no bar in tension, under either "
                "the long-term or the short-term load.")
        return
    quants = ["wk (mm)", "sr,max (mm)", f"{_EPS}sm - {_EPS}cm",
              f"{_SIGMA}s (MPa)", f"{_RHO}p,eff", "hc,ef (m)", "cover c (mm)",
              f"bar dia {_PHI} (mm)", "gov. bar"]
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
    st.caption("Governing (largest-$w_k$) bar per load case; each bar's clear cover "
               "is the distance to the nearest concrete face minus its radius.")
    member = e.get("crack_member")
    if member:
        st.caption(f"DK NA fine crack system: cover-dependent k3 = 3.4*(25/c)^(2/3); "
                   f"member type = {member} (the (h-x)/3 effective-height term "
                   f"applies to slabs and prestressed members).")


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

_autosave_startup()        # restore the last autosaved session (BriCoS-style) on launch
_apply_pending_project()   # restore an uploaded project before any widget is built
# Always build the sidebar inputs, even while the Quick Section builder is open:
# Streamlit discards a widget's state on any run where it is not rendered, so
# skipping build_inputs would reset every material and load input to its minimum
# (and break the next Calculate). build_inputs is cheap; its result is unused
# while the builder owns the main area.
inp = build_inputs()

# The Quick Section builder and the user manual each take over the main viewport
# (the BriCoS manual pattern): render in place of the analysis views while open,
# and stop before they draw. The sidebar stays, so its widget state survives.
if st.session_state.get("_manual_open"):
    import manual                          # lazy: keep the manual off the hot path
    manual.render_manual_streamlit()
    st.stop()

if st.session_state.get("_qs_open"):
    _quick_section_viewport()
    st.stop()

# Autosave rides this rerun (triggered by the user's edit/click) once the interval
# has elapsed. It runs only past the Quick Section branch: applying the builder
# reseeds the tables and reruns with the builder closed, so this saves the applied
# geometry rather than the stale pre-apply tables.
_maybe_autosave()

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

_generate_report(inp)   # builds the PDF when the Report panel's Generate was pressed

results = st.session_state.get("results")
stale = results is not None and st.session_state.get("result_sig") != inp["signature"]
if stale and view in ("Plastic Results", "Elastic Results"):
    st.warning("Inputs changed since the last calculation - press Calculate to update.")

for _section_err in (inp.get("void_error"), inp.get("steel_error")):
    if _section_err:
        st.error(_section_err)

if view == "Section":
    section_view(inp)
elif view == "Stress-Strain diagrams":
    materials_view(inp)
elif view == "Plastic Results":
    plastic_view(inp, results)
else:
    elastic_view(inp, results)
