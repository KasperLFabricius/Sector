"""Sector - reinforced-concrete cross-section analysis (Streamlit interface).

Define a section by its shape and reinforcement, choose elastic and/or plastic
analysis, then press Calculate to review the stresses and the ultimate capacity.
"""

from __future__ import annotations

import dataclasses
import functools
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
from sector import (codes, combined, geometry, kernels,  # noqa: E402
                    material_presets as mp, shear, templates, torsion)
from sector.elastic import solve_elastic_combined, transformed_properties  # noqa: E402
from sector.plastic import (plastic_capacity_at_angle, solve_interaction,  # noqa: E402
                            solve_plastic)
from sector.section import Section  # noqa: E402
from sector.serviceability import (analyse_cracking, combined_cracking,  # noqa: E402
                                   crack_width)

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
_THETA, _NU, _ALPHA, _DELTA = chr(0x3B8), chr(0x3BD), chr(0x3B1), chr(0x394)
_TAU = chr(0x3C4)

# EC2 7.11 bond coefficient k1 by bar surface (cannot be inferred from geometry).
_BOND_K1 = {"Ribbed / high bond (k1 = 0.8)": 0.8, "Plain round (k1 = 1.6)": 1.6}

# Crack-width code edition -> the crack-spacing flags. edition: "2004" (EC2 7.3.4)
# or "2023" (EC2 9.2.3 refined). dk_na: cover-dependent k3 and the (h-x)/3
# effective-height term only for slabs/prestressed; the DK NA option reports BOTH
# the fine and the coarse crack system (7.3.4(1)) -- the coarse effective area is
# the band whose centroid matches the tension reinforcement (figure 7.100 NA) and
# its wk is halved -- for both the long-term and the short-term load.
_CRACK_CODES = {
    "EN 1992-1-1:2005": dict(dk_na=False, edition="2004"),
    "DS/EN 1992-1-1 + DK NA": dict(dk_na=True, edition="2004"),
    "EN 1992-1-1:2023": dict(dk_na=False, edition="2023"),
}
# Old saved values for the (now merged) fine/coarse DK NA options.
_CRACK_CODE_ALIASES = {
    "DS/EN 1992-1-1 + DK NA (fine crack system)": "DS/EN 1992-1-1 + DK NA",
    "DS/EN 1992-1-1 + DK NA (coarse crack system)": "DS/EN 1992-1-1 + DK NA",
}

# Shear methods for a member without shear reinforcement. The 2005 variable-strut
# family drives the with-links truss, the torsion tube and the combined lock; the
# strain-based EN 1992-1-1:2023 tau_Rd,c (sec. 8.2.2) is offered for the shear check
# without links. Default is the DK NA:2024 edition (the house default material code).
_SHEAR_CODES = {c.label: c for c in (codes.EC2_2005_DKNA, codes.EC2_2005)}
_SHEAR_METHODS = dict(_SHEAR_CODES, **{codes.EC2_2023.label: codes.EC2_2023})
# Shear direction -> the bending axis passed to the engine ("x" = vertical shear,
# stress varies with y; "y" = horizontal shear, stress varies with x).
_SHEAR_AXES = {
    "Vertical shear (bending about x)": "x",
    "Horizontal shear (bending about y)": "y",
}
# Tension face -> tension_low (True when the tension face is the low-coordinate side).
_SHEAR_TENSION = {"Bottom / left face": True, "Top / right face": False}

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
    st.sidebar.image(str(_logo), width="stretch")

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


def _seeded_number(box, label, lo, hi, default, step, key, **kw):
    """A number_input whose initial value is seeded into session state rather than
    passed as ``value=``.

    A loaded project (or an autosave restore) writes the widget key before the widget
    is created; a widget that also passes ``value=`` then trips Streamlit's "created
    with a default value but also had its value set via the Session State API"
    warning. Seeding via ``setdefault`` (a no-op once the key exists) and omitting
    ``value=`` avoids it while keeping the same default on a fresh session."""
    st.session_state.setdefault(key, default)
    return box.number_input(label, lo, hi, step=step, key=key, **kw)


def _seeded_checkbox(box, label, default, key, **kw):
    """A checkbox whose default is seeded into session state rather than passed as
    ``value=`` -- same reason as :func:`_seeded_number`: a loaded project writes the
    key before the widget is built, and a ``value=`` alongside it trips the warning."""
    st.session_state.setdefault(key, default)
    return box.checkbox(label, key=key, **kw)


def _seeded_selectbox(box, label, options, default, key, **kw):
    """A selectbox whose default is seeded into session state rather than passed as
    ``index=`` -- same reason as :func:`_seeded_number`. ``default`` must be one of
    ``options``."""
    st.session_state.setdefault(key, default)
    return box.selectbox(label, options, key=key, **kw)


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
        # Es is in GPa here (the panel unit), so fytk[MPa] / Es[GPa] is already the
        # yield strain in per-mille (= fytk[MPa] / Es[MPa] * 1000).
        ey = vals["fytk"] / vals["Es"]
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
    preset = _seeded_selectbox(box, "Preset", labels, _DEFAULT_PRESET,
                               "conc_preset", help=_PRESET_HELP)
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
                   key="conc_strain_auto", width="stretch", disabled=strain_lock,
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
    box.caption(f"curve {curve},  $f_{{cd}}$ = {concrete.fcd:.3f} MPa,  "
                f"$\\varepsilon_{{cu2}}$ = {concrete.eps_cu2 * 1000.0:.3f} permille{note}")

    # Mean tensile strength fctm feeds the serviceability cracking check. It lives
    # with the concrete (not the loads); the Auto button refreshes it from the
    # current grade because the number_input persists across a grade change.
    fctm_ec = round(codes.fctm(fck), 3)
    st.session_state.setdefault("sls_fctm", fctm_ec)
    if (box.button(f"Auto $f_{{ctm}}$ (EC2: {fctm_ec:.2f} MPa)", key="sls_fctm_auto",
                   width="stretch", disabled=lock_elastic,
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
                   width="stretch", disabled=lock_elastic,
                   help="Set Ec = Ecm = 22*(fcm/10)^0.3 GPa (EC2 Table 3.1) for the "
                        "current grade.")
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
    preset = _seeded_selectbox(box, "Preset", labels, _DEFAULT_PRESET,
                               "mild_preset", help=_PRESET_HELP)
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
             "capacity; the elastic analysis is linear and treats "
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
    box.caption(f"$f_{{yd}}$ = {steel.fytk / vals['gamma_y']:.3f} MPa,  "
                f"$E_s$ = {vals['Es']:.0f} GPa,  compression {comp}")
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
    preset = _seeded_selectbox(box, "Preset", labels, "EN 1992-1-1:2005",
                               "pre_preset", help=_PRESET_HELP)
    _prefill("pre", preset, presets)
    curve = presets[preset]["curve"]
    vals = {f: _number(box, "pre", f, mp.PRESTRESS_FIELD_META, mp.PRESTRESS_HELP,
                       disabled=locked and f not in ("IS", "Es"))
            for f in mp.PRESTRESS_FIELD_META}
    _clamp_eut(box, vals, mp.PRESTRESS_FIELDS_BY_CURVE[curve])
    pre = _safe_build(box, mp.build_prestress, curve, vals)
    if curve in (1, 2, 3, 4, 5):
        box.caption(f"built-in curve {curve} (fixed shape); only the prestrain "
                    f"IS = {vals['IS']:.3f} permille applies")
    else:
        box.caption(f"IS = {vals['IS']:.3f} permille,  "
                    f"fpd = {vals['fytk'] / vals['gamma_y']:.3f} MPa,  "
                    f"Ep = {vals['Es']:.0f} GPa")
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
    # Forget the Quick Section builder's last shape so the loaded qsv_ dimensions are
    # not mistaken for an in-builder shape switch: the next builder open takes the
    # first-call branch (records the loaded shape, no re-seed) and keeps b/h as saved.
    st.session_state.pop("qs_shape_prev", None)
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
                        width="stretch",
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
    if box.button("Generate report", type="primary", width="stretch",
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
                            mime="application/pdf", width="stretch")


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

# b_mm and h_mm are reused across shapes with different meanings and defaults (a
# 400x600 rectangle, an 800x1000 box, a 300 mm slab thickness). Switching shape must
# re-seed them to the new shape's default -- a plain setdefault would keep the
# previous shape's value. The other dimension keys are unique to one shape, so their
# own setdefault default is enough. Mirrors the material-preset prefill.
_QS_SHARED_DIMS = {
    "Rectangle":  {"b_mm": 400.0, "h_mm": 600.0},
    "Slab strip": {"h_mm": 300.0},
    "Box girder": {"b_mm": 800.0, "h_mm": 1000.0},
}


def _qs_shape_prefill(shape):
    """Seed the shared dimension keys with the current shape's defaults when the shape
    selection changes, so the dimension widgets can be created without ``value=``
    (avoiding the "default value + Session State API" warning) while a shape switch
    still resets b/h to that shape's default.

    The very first call in a session only records the shape -- it does not re-seed --
    so a project or autosave restored before the builder is first opened keeps its
    own b/h (the restore is not a shape change). A genuine in-builder shape switch
    (``qs_shape_prev`` already set) still re-seeds."""
    if "qs_shape_prev" not in st.session_state:
        st.session_state["qs_shape_prev"] = shape
        return
    if st.session_state["qs_shape_prev"] != shape:
        for k, v in _QS_SHARED_DIMS.get(shape, {}).items():
            st.session_state[k] = v
        st.session_state["qs_shape_prev"] = shape

# The builder's own widget keys. Streamlit drops a widget's key from session state
# on any run where the widget is not rendered, so while the builder is closed these
# would be lost (resetting the builder to defaults on reopen, and dropping them
# from a saved project). The builder mirrors them to durable "qsv_" keys whenever it
# renders and restores them when it opens; project_io persists the durable copies.
_QS_WIDGET_KEYS = (
    "shape", "b_mm", "h_mm", "bf_mm", "hf_mm", "bw_mm", "hw_mm", "wall_mm",
    "dia_mm", "ring_n", "ring_d", "ring_c_mm", "qs_rebar_mode", "qs_cover_to_edge",
    "bot_n", "bot_d", "bot_s", "top_n", "top_d", "top_s",
    "bot_c_mm", "top_c_mm", "bot_n2", "top_n2",
    "bot_layers", "top_layers", "layer_s", "bot_off_d", "top_off_d",
    "tnd_n", "tnd_a", "tnd_c_mm", "tnd_layers", "tnd_layer_s",
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


def _qs_interleave(face_group, diameter_mm):
    """A second bar size at the midpoints between a face group's bars.

    Groups the given bars by y-level and places one bar of ``diameter_mm`` at each
    gap midpoint, so a face row of one size is interleaved with another (e.g. a
    Y20/100 row with Y16 bars sitting between them -- two sizes in the same layer
    without overlapping). Midpoints always sit between existing bars, so the
    interleaved bars stay inside the concrete. Each stacked layer is interleaved.
    """
    a = templates.bar_area(float(diameter_mm))
    by_y = {}
    for x, y, _area in face_group:
        by_y.setdefault(round(float(y), 9), []).append(float(x))
    out = []
    for y, xs in by_y.items():
        xs.sort()
        out.extend((0.5 * (xs[i] + xs[i + 1]), y, a) for i in range(len(xs) - 1))
    return out


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
    _qs_shape_prefill(shape)   # re-seed b/h on a shape change (see the prefill note)
    holes = []
    if shape == "Rectangle":
        b = _seeded_number(box, r"Width $b$ (mm)", 50.0, 10000.0, 400.0, 10.0, "b_mm",
                           help="Overall section width.") / 1000.0
        h = _seeded_number(box, r"Height $h$ (mm)", 50.0, 10000.0, 600.0, 10.0, "h_mm",
                           help="Overall section height (depth).") / 1000.0
        outer = templates.rectangle(b, h)
        width_b = b
    elif shape == "Slab strip":
        h = _seeded_number(box, r"Thickness $h$ (mm)", 50.0, 3000.0, 300.0, 10.0, "h_mm",
                           help="Slab thickness; the strip is analysed per 1 m width.") / 1000.0
        b = width_b = 1.0
        outer = templates.slab_strip(h)
    elif shape == "T-section":
        bf = _seeded_number(box, r"Flange width $b_f$ (mm)", 100.0, 12000.0, 1200.0, 10.0, "bf_mm",
                            help="Width of the (top) flange.") / 1000.0
        hf = _seeded_number(box, r"Flange thickness $h_f$ (mm)", 50.0, 2000.0, 200.0, 10.0, "hf_mm",
                            help="Thickness of the flange.") / 1000.0
        bw = _seeded_number(box, r"Web width $b_w$ (mm)", 50.0, 4000.0, 300.0, 10.0, "bw_mm",
                            help="Width of the web.") / 1000.0
        hw = _seeded_number(box, r"Web depth $h_w$ (mm)", 100.0, 6000.0, 600.0, 10.0, "hw_mm",
                            help="Depth of the web below the flange.") / 1000.0
        outer = templates.t_section(bf, hf, bw, hw)
        b, h, width_b = bw, hf + hw, bf
    elif shape == "Box girder":
        b = _seeded_number(box, r"Width $b$ (mm)", 200.0, 12000.0, 800.0, 10.0, "b_mm",
                           help="Overall outer width of the box.") / 1000.0
        h = _seeded_number(box, r"Height $h$ (mm)", 200.0, 12000.0, 1000.0, 10.0, "h_mm",
                           help="Overall outer height of the box.") / 1000.0
        max_wall = round((min(b, h) / 2 - 0.01) * 1000.0, 0)
        # wall_mm has a dimension-dependent maximum, so clamp the seeded value into
        # range before the widget (a wider box left a wall that the narrower one can
        # no longer accept would otherwise error).
        st.session_state.setdefault("wall_mm", min(200.0, max_wall))
        st.session_state["wall_mm"] = min(float(st.session_state["wall_mm"]), max_wall)
        wall = box.number_input("Wall thickness (mm)", 20.0, max_wall, step=10.0,
                                key="wall_mm",
                                help="Thickness of the box walls (uniform).") / 1000.0
        outer, holes = templates.box(b, h, wall)
        width_b = b
    else:  # Circular
        dia = _seeded_number(box, "Diameter (mm)", 100.0, 6000.0, 600.0, 10.0, "dia_mm",
                             help="Outer diameter of the circular section.") / 1000.0
        outer = templates.circular(dia)
        b = h = width_b = dia

    box.markdown("**Reinforcement**")
    # Cover can be measured to the near edge of the bars rather than to their centres
    # -- the centre then sits a bar radius deeper. Applied to the mild bars (bottom /
    # top rows and the circular ring); tendons keep a centre cover.
    cover_to_edge = _seeded_checkbox(
        box, "Cover to bar edge (else to bar centre)", False, "qs_cover_to_edge",
        help="Measure the cover to the near surface of the bars, not their centres.")
    _edge = lambda cov, dia_mm: cov + (dia_mm / 2000.0 if cover_to_edge else 0.0)
    if shape == "Circular":
        nb = _seeded_number(box, "Perimeter bars", 0, 200, 8, 1, "ring_n",
                            help="Number of bars evenly spaced around the perimeter.")
        rd = _seeded_number(box, "Bar diameter (mm)", 1.0, 100.0, 20.0, 1.0, "ring_d",
                            help="Diameter of each reinforcement bar.")
        cov = _seeded_number(box, "Cover (mm)", 0.0, 500.0, 50.0, 5.0, "ring_c_mm",
                             help="Cover from the section face to the bars.") / 1000.0
        bars = templates.bar_ring(0.0, 0.0,
                                  templates.ring_radius(dia, _edge(cov, rd)), int(nb), rd)
    else:
        by_spacing = box.radio(
            "Bar placement", ["By number", "By spacing"], horizontal=True,
            key="qs_rebar_mode",
            help="Place each row as a fixed bar count, or at a target centre-to-"
                 "centre spacing (slab phi @ s); the count is then derived from the "
                 "face width.") == "By spacing"
        c1, c2 = box.columns(2)
        c1.markdown("**Bottom**")
        c2.markdown("**Top**")
        rd_bot = _seeded_number(c1, "Bottom dia (mm)", 1.0, 100.0, 20.0, 1.0, "bot_d",
                                help="Bottom bar diameter (mm).")
        rd_top = _seeded_number(c2, "Top dia (mm)", 1.0, 100.0, 20.0, 1.0, "top_d",
                                help="Top bar diameter (mm).")
        bot_cov = _seeded_number(c1, "Bottom cover (mm)", 0.0, 500.0, 50.0, 5.0, "bot_c_mm",
                                 help="Cover at the bottom face.") / 1000.0
        top_cov = _seeded_number(c2, "Top cover (mm)", 0.0, 500.0, 50.0, 5.0, "top_c_mm",
                                 help="Cover at the top face.") / 1000.0
        # Bar-centre covers (add a radius when the cover is measured to the bar edge).
        bot_e, top_e = _edge(bot_cov, rd_bot), _edge(top_cov, rd_top)
        bot_w, top_w = b - 2.0 * bot_e, width_b - 2.0 * top_e
        n_at_bot = n_at_top = None     # by-number: a fixed count per layer
        if by_spacing:
            s_bot = _seeded_number(c1, "Bottom spacing (mm)", 10.0, 1000.0, 150.0, 5.0,
                                   "bot_s", help="Target centre-to-centre spacing.") / 1000.0
            s_top = _seeded_number(c2, "Top spacing (mm)", 10.0, 1000.0, 150.0, 5.0,
                                   "top_s", help="Target centre-to-centre spacing.") / 1000.0
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
            nb_bot = _seeded_number(c1, "Bottom bars", 0, 100, 6, 1, "bot_n",
                                    help="Number of bars in the first bottom layer.")
            nb_top = _seeded_number(c2, "Top bars", 0, 100, 2, 1, "top_n",
                                    help="Number of bars in the first top layer.")
        nl_bot = _seeded_number(c1, "Bottom layers", 1, 10, 1, 1, "bot_layers",
                                help="Number of stacked bar rows at the bottom face.")
        nl_top = _seeded_number(c2, "Top layers", 1, 10, 1, 1, "top_layers",
                                help="Number of stacked bar rows at the top face.")
        # By number, the stacked (upper) layers can hold a different count than the
        # first row. By spacing, each row's count follows its own span, so it is off.
        bot_n2 = _seeded_number(c1, "Bottom upper-layer bars", 0, 100, 6, 1, "bot_n2",
                                disabled=by_spacing or int(nl_bot) <= 1,
                                help="Bars in each bottom layer above the first.")
        top_n2 = _seeded_number(c2, "Top upper-layer bars", 0, 100, 2, 1, "top_n2",
                                disabled=by_spacing or int(nl_top) <= 1,
                                help="Bars in each top layer above the first.")
        ne_bot = int(bot_n2) if (not by_spacing and int(nl_bot) > 1) else None
        ne_top = int(top_n2) if (not by_spacing and int(nl_top) > 1) else None
        layer_s = _seeded_number(
            box, "Layer spacing (mm)", 10.0, 1000.0, 60.0, 5.0, "layer_s",
            disabled=int(nl_bot) == 1 and int(nl_top) == 1,
            help="Vertical centre-to-centre distance between stacked bar layers "
                 "(used only when a face has more than one layer).") / 1000.0
        # Optional second bar size, interleaved at the midpoints of each face row
        # (0 = off) -- e.g. a Y20/100 row with Y16 bars between them (two sizes in one
        # layer).
        o1, o2 = box.columns(2)
        bot_off_d = _seeded_number(o1, "Bottom interleave dia (mm, 0 = off)", 0.0, 100.0,
                                   0.0, 1.0, "bot_off_d",
                                   help="Second bar size at the midpoints of the bottom "
                                        "row(s); 0 = off.")
        top_off_d = _seeded_number(o2, "Top interleave dia (mm, 0 = off)", 0.0, 100.0,
                                   0.0, 1.0, "top_off_d",
                                   help="Second bar size at the midpoints of the top "
                                        "row(s); 0 = off.")
        # A T-section's top face is the flange (width width_b); a top layer pushed
        # below the flange must fit the narrower web (width b) or it would fall
        # outside the concrete. The bottom layers stay in the web (b) and only ever
        # widen into the flange, so they need no such limit.
        top_span_at = None
        if shape == "T-section":
            flange_y = h / 2 - hf

            def top_span_at(y):
                if y >= flange_y:                 # within the flange
                    return -width_b / 2 + top_e, width_b / 2 - top_e
                return -b / 2 + top_e, b / 2 - top_e  # below the flange -> the web

        if shape == "Box girder":
            # A box girder's rows split into the side walls once they rise into the
            # hollow, so multi-layer reinforcement keeps its count in the webs.
            bot_group = templates.box_layers(-h / 2 + bot_e, 1.0, int(nl_bot), layer_s,
                                             b, h, wall, bot_e, int(nb_bot),
                                             templates.bar_area(rd_bot), n_extra=ne_bot)
            top_group = templates.box_layers(h / 2 - top_e, -1.0, int(nl_top), layer_s,
                                             b, h, wall, top_e, int(nb_top),
                                             templates.bar_area(rd_top), n_extra=ne_top)
        else:
            bot_group = templates.bar_layers(-h / 2 + bot_e, 1.0, int(nl_bot), layer_s,
                                             -b / 2 + bot_e, b / 2 - bot_e, int(nb_bot),
                                             rd_bot, n_at=n_at_bot, n_extra=ne_bot)
            top_group = templates.bar_layers(h / 2 - top_e, -1.0, int(nl_top), layer_s,
                                             -width_b / 2 + top_e, width_b / 2 - top_e,
                                             int(nb_top), rd_top, span_at=top_span_at,
                                             n_at=n_at_top, n_extra=ne_top)
        groups = [bot_group, top_group]
        for grp, off_d in ((bot_group, bot_off_d), (top_group, top_off_d)):
            if off_d <= 0.0:
                continue
            inter = _qs_interleave(grp, off_d)
            # A row split across a void (a box girder's hollow) leaves a gap whose
            # midpoint would fall in the void; keep only interleaved bars in concrete.
            if inter and holes:
                ok = geometry.points_inside_concrete(
                    [(x, y) for x, y, _a in inter], outer, holes)
                inter = [p for p, good in zip(inter, ok) if good]
            groups.append(inter)
        bars = templates.merge_bars(*groups)

    box.markdown("**Prestressing tendons**")
    nt = _seeded_number(box, "Tendons", 0, 200, 0, 1, "tnd_n",
                        help="Number of tendons the Quick Section places (0 = none). "
                             "Tendons can also be entered directly in the points table.")
    a_t = _seeded_number(box, "Area per tendon (mm2)", 1.0, 50000.0, 150.0, 10.0, "tnd_a",
                         help="Cross-sectional area of a single tendon.")
    cov_p = _seeded_number(box, "Tendon cover (mm)", 0.0, 2000.0, 100.0, 10.0, "tnd_c_mm",
                           help="Distance from the bottom face (or the circular "
                                "ring) to the tendons.") / 1000.0
    nl_t = _seeded_number(box, "Tendon layers", 1, 10, 1, 1, "tnd_layers",
                          help="Number of stacked tendon rows from the bottom face "
                               "(ignored for a circular ring).")
    ls_t = _seeded_number(
        box, "Tendon layer spacing (mm)", 10.0, 1000.0, 60.0, 5.0, "tnd_layer_s",
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
    back = bcol.button("Back", width="stretch", key="qs_back")
    apply = acol.button("Apply to point tables", type="primary",
                        width="stretch", key="qs_apply")

    form, preview = st.columns([2, 3])
    with form:
        outer, holes, bars, tendons = _quick_section_geometry(st)
    _qs_mirror_settings()   # keep the durable copy current with what is shown
    with preview:
        bar_xy = [(x, y, a) for x, y, a in bars]
        tendon_xy = [(x, y, a) for x, y, a in tendons]
        st.plotly_chart(
            viz.section_figure(outer, holes, bar_xy, tendons=tendon_xy,
                               title="Preview", show_labels=True, height=560,
                               scale=_MM, unit="mm"),
            width="stretch")
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


def _modular_ratio_readout(box, ns, nl, ns_p, nl_p, *, has_tendons):
    """Report the derived short/long-term modular ratios (mild + prestress).

    n_l and n_s are no longer entered but computed from the elastic moduli and the
    creep coefficient, so the values actually used are shown here (and in the PDF
    report). Mild steel and prestress get their own ratios because Es != Ep; the
    prestress row is shown only when the section has tendons.
    """
    # Plain-text cells (no LaTeX): KaTeX does not render reliably inside a markdown
    # table cell, so keep the maths in the intro line and the table simply readable.
    box.markdown(r"**Modular ratios** (derived from $E_c$, $E_s$, $E_p$, $\varphi$)")
    rows = ["| Steel | Short-term n_s | Long-term n_l |",
            "|:--|--:|--:|",
            f"| Mild (Es/Ec) | {ns:.3f} | {nl:.3f} |"]
    if has_tendons:
        rows.append(f"| Prestress (Ep/Ec) | {ns_p:.3f} | {nl_p:.3f} |")
    box.markdown("\n".join(rows))


# Result-staleness signature keys, split so an input change recomputes only the
# affected analysis on the next Calculate. Shared keys affect both analyses
# (materials + mode); the per-analysis buckets hold keys that touch only that one.
# Anything that could affect both stays shared, so a reused result is never stale.
# n_l/n_s are derived from conc_Ec and el_phi, so those enter the elastic signature.
_SHARED_SIG_KEYS = (
    "conc_preset", "conc_fck", "conc_gamma_c", "conc_alpha_cc",
    "conc_eps_c2", "conc_eps_cu2", "conc_n",
    "mild_preset", "mild_fytk", "mild_fyck", "mild_futk", "mild_eut",
    "mild_gamma_y", "mild_gamma_u", "mild_gamma_E", "mild_k",
    "mild_ey0t", "mild_ey0c", "mild_Es", "mild_active_comp",
    "pre_preset", "pre_IS", "pre_fytk", "pre_futk", "pre_eut", "pre_gamma_y",
    "pre_gamma_u", "pre_gamma_E", "pre_k", "pre_ey0t", "pre_Es",
    "mode",
)
_PLASTIC_SIG_KEYS = (
    "pl_P", "pl_Mx", "pl_My", "v_min", "v_max", "v_inc",
    "pl_check_util", "pl_interaction",
)
_ELASTIC_SIG_KEYS = (
    "el_long_P", "el_long_Mx", "el_long_My",
    "el_short_P", "el_short_Mx", "el_short_My",
    "conc_Ec", "el_phi",
    "sls_cw", "sls_fctm", "sls_phi", "sls_bond", "sls_code", "sls_member",
)
# Shear inputs. Folded into the overall signature (not the plastic/elastic split)
# so a shear-only change marks the results stale without forcing the bending
# analyses to recompute; the shear resistance itself is cheap and recomputed on
# every Calculate. Its geometry/fck/axial dependencies already sit in the shared
# and plastic parts of the signature.
_SHEAR_SIG_KEYS = (
    "shear_on", "shear_method", "shear_axis", "shear_tension", "shear_V", "shear_bw",
    "shear_dlower",
    "shear_links", "shear_link_legs", "shear_link_dia", "shear_link_s", "shear_fywk",
    "shear_cot_min", "shear_cot_max",
    "torsion_on", "torsion_method", "torsion_T", "torsion_tef", "torsion_nu_v",
    "torsion_cot_min", "torsion_cot_max",
    "torsion_subdivide", "torsion_nsub",
    "torsion_sub_b0", "torsion_sub_h0", "torsion_sub_b1", "torsion_sub_h1",
    "torsion_sub_b2", "torsion_sub_h2", "torsion_sub_b3", "torsion_sub_h3",
    "combined_on", "combined_method", "combined_mv_independent",
)


def build_inputs():
    """Render the sidebar dropdown panels and return the section, materials and
    loads. Panels follow the workflow order: About, Analysis settings (+ its check
    configs), Section, Material Parameters, Loads, Report, Save/Load."""
    s = st.sidebar

    # The panels are CREATED here in their on-screen order but FILLED lower down in
    # dependency order: Analysis settings computes the bending mode and the check
    # toggles that the Material and Loads panels gate on, so those two are written
    # after it even though Analysis settings now sits above them anyway. Streamlit
    # fixes each panel's position when it is created, so a later write still lands in
    # the right place. The "Back to analysis" slot (shown only while the manual is
    # open) sits at the very top; About/Report/Save-Load are filled at the end so the
    # download and report capture the fully-built inputs.
    back_slot = s.container()
    about_slot = s.container()
    # The four core input steps are numbered so the workflow order reads at a glance;
    # the optional check configs and Report / Save stay unnumbered. The two check-
    # config panels sit directly under Analysis settings because they parameterise
    # its checks. Panels carry the calculation methodology (Elastic / Plastic), not a
    # limit state -- the same analysis can serve several load combinations.
    _dot = chr(0x00B7)   # middle dot (BMP code point, source stays ASCII)
    aset = s.expander(f"1 {_dot} Analysis settings", expanded=False)
    scw = s.expander("Crack width (Elastic)", expanded=False)
    sts = s.expander("Shear, torsion & combined (Plastic)", expanded=False)
    sec = s.expander(f"2 {_dot} Section", expanded=True)
    mat = s.expander(f"3 {_dot} Material Parameters", expanded=False)
    loads = s.expander(f"4 {_dot} Loads", expanded=True)
    report_slot = s.container()
    save_slot = s.container()
    mode = aset.radio("Bending analysis", ["Plastic", "Elastic", "Both"], key="mode",
                      help="The bending analysis only -- the shear, torsion and crack "
                           "checks are separate toggles below. Plastic: the "
                           "bending capacity (M-M envelope). Elastic: cracked-section "
                           "concrete and bar stresses for the applied loads. Both: "
                           "run the two.")
    plastic_on = mode in ("Plastic", "Both")
    elastic_on = mode in ("Elastic", "Both")

    aset.markdown("**Neutral-axis sweep (plastic)**")
    v_min = _seeded_number(aset, r"Start angle $V_{min}$ (deg)", 0.0, 360.0, 0.0, 5.0,
                           "v_min", disabled=not plastic_on,
                           help="First neutral-axis rotation angle of the plastic sweep.")
    v_max = _seeded_number(aset, r"End angle $V_{max}$ (deg)", 0.0, 360.0, 360.0, 5.0,
                           "v_max", disabled=not plastic_on,
                           help="Last neutral-axis rotation angle of the plastic sweep.")
    v_inc = _seeded_number(aset, r"Increment $V_{inc}$ (deg)", 1.0, 90.0, 15.0, 1.0,
                           "v_inc", disabled=not plastic_on,
                           help="Angular step between swept neutral-axis angles; "
                                "a finer step gives a smoother M-M envelope.")
    check_util = _seeded_checkbox(
        aset, "Check utilisation against applied moment", True, "pl_check_util",
        disabled=not plastic_on,
        help="On: the applied plastic Mx/My are checked against the capacity envelope "
             "(utilisation). Off: report the capacity only -- the applied Mx/My are "
             "ignored and locked.")
    interaction = _seeded_checkbox(
        aset, "N-M interaction diagrams", False, "pl_interaction",
        disabled=not plastic_on,
        help="Trace the axial-moment (N-M) capacity curves about both bending axes "
             "(N-Mx and N-My), from pure tension to the squash load. Shown in the "
             "N-M Interaction view. Adds a short extra sweep to Calculate.")

    scw.caption("Cracked-section stress and crack-width check, reported in the "
                "Elastic view.")
    sls_cw = _seeded_checkbox(scw, "Crack width", False, "sls_cw",
                              disabled=not elastic_on,
                              help="Report the EC2 crack width wk for both the long-term "
                                   "and the short-term (instantaneous) load. Each bar's "
                                   "clear cover is taken from the geometry.")
    sls_phi = _seeded_number(scw, r"Crack-width bar diameter $\phi$ (mm, 0 = auto)", 0.0,
                             60.0, 0.0, 1.0, "sls_phi",
                             disabled=not (elastic_on and sls_cw),
                             help="Governing bar diameter for the crack spacing "
                                  "sr,max; 0 derives it from each bar's area.")
    # k1 (EC2 7.11 bond coefficient) depends on the bar surface, which the geometry
    # cannot tell, so it is a user choice: 0.8 ribbed / high-bond, 1.6 plain round.
    sls_bond = scw.selectbox(
        "Mild-steel bond (k1)",
        list(_BOND_K1), key="sls_bond", disabled=not (elastic_on and sls_cw),
        help="EC2 7.11 bond coefficient k1 for the crack spacing, applied to the "
             "mild reinforcement: 0.8 for ribbed / high-bond bars (e.g. Tentor), "
             "1.6 for plain round bars. Prestressing tendons always use k1 = 1.6.")
    sls_k1 = _BOND_K1[sls_bond]
    # Migrate the pre-coarse-system saved value before the selectbox reads it.
    if st.session_state.get("sls_code") in _CRACK_CODE_ALIASES:
        st.session_state["sls_code"] = _CRACK_CODE_ALIASES[st.session_state["sls_code"]]
    sls_code = scw.selectbox(
        "Crack-width code", list(_CRACK_CODES), key="sls_code",
        disabled=not (elastic_on and sls_cw),
        help="Code edition for the crack-spacing rules. The DK NA makes k3 cover-"
             "dependent (k3 = 3.4*(25/c)^(2/3)), limits the (h-x)/3 effective-height "
             "term to slabs and prestressed members, and reports BOTH the fine and "
             "the coarse crack system: the coarse system (7.3.4(1)) sets the "
             "effective area to the band whose centroid matches the tension "
             "reinforcement (figure 7.100 NA) and halves the crack width. "
             "EN 1992-1-1:2023 uses the refined model (9.2.3): wk = kw*k1/r*sr,m,cal*"
             "(esm-ecm) with kw = 1.7 and a per-bar curvature factor.")
    sls_dk_na = _CRACK_CODES[sls_code]["dk_na"]
    sls_edition = _CRACK_CODES[sls_code]["edition"]
    sls_member = scw.selectbox(
        "Member type", ["Beam", "Slab"], key="sls_member",
        disabled=not (elastic_on and sls_cw and sls_dk_na),
        help="Under the DK NA fine system the (h-x)/3 effective-height term applies "
             "only to slabs (and prestressed members); for a beam it is dropped. It "
             "affects the fine system only (the coarse system uses the centroid-"
             "matched effective area, not hc,ef). Ignored for the base EN 1992-1-1 "
             "code.")

    sts.markdown("**Combined M-V-T interaction**")
    sts.caption("Tie the bending (plastic M), shear (V) and torsion (T) checks "
                 "together under one consistent code edition (6.3.2). Enable Plastic "
                 "(or Both), the shear check and the torsion check as well.")
    combined_on = _seeded_checkbox(
        sts, "Check combined M-V-T", False, "combined_on",
        help="Tie the M, V and T checks together (crushing 6.29 + DK NA sum rule); "
             "locks their method to the shared edition below. See the manual.")
    combined_method = _seeded_selectbox(
        sts, "Combined edition (shared)", list(_SHEAR_CODES),
        codes.EC2_2005_DKNA.label, key="combined_method", disabled=not combined_on,
        help="The single code edition used for the shear and torsion checks while "
             "Combined is on (their own method selectors are locked to this).")
    combined_mv_independent = _seeded_checkbox(
        sts, "Shear longitudinal steel provided (M & V separate)", False,
        "combined_mv_independent", disabled=not combined_on,
        help="DK NA 6.3.2(6): when the longitudinal steel for shear (beyond bending) "
             "is present, M and V are not summed in sum(SEd/SRd) -- two independent "
             "checks (M+T and V+T) are made and the governing one taken.")
    # Filled at the end of this block (once the shear/torsion toggles below are
    # known) with any missing combined-check prerequisites -- so the user sees them
    # here, right under the toggle, instead of only after Calculate.
    combined_warn = sts.container()

    sts.markdown("**Shear without shear reinforcement (VRd,c)**")
    sts.caption("Design shear resistance of a member not requiring shear "
                 "reinforcement (EN 1992-1-1 sec. 6.2.2). A capacity check of the "
                 "applied shear VEd; the axial term uses the axial force N from the "
                 "Plastic capacity load set (its N input stays enabled here even in "
                 "Elastic-only mode).")
    shear_on = _seeded_checkbox(
        sts, "Check shear capacity", False, "shear_on",
        help="Compute VRd,c and the utilisation VEd/VRd,c. Members that need "
             "designed shear reinforcement (VEd > VRd,c) are covered in a later "
             "addition.")
    shear_method = _seeded_selectbox(
        sts, "Shear method", list(_SHEAR_METHODS), codes.EC2_2005_DKNA.label,
        key="shear_method", disabled=(not shear_on) or combined_on,
        help="Code edition for the shear rules: the 2005 family (VRd,c, 6.2.2(1)) or "
             "EN 1992-1-1:2023 (strain-based tau_Rd,c, 8.2.2, no links). See the "
             "manual for the difference.")
    _eff_shear_method = combined_method if combined_on else shear_method
    _shear_2023 = (_SHEAR_METHODS.get(_eff_shear_method) is not None
                   and getattr(_SHEAR_METHODS[_eff_shear_method], "shear_model",
                               "2005") == "2023")
    shear_dlower = _seeded_number(
        sts, "Aggregate size Dlower (mm)", 4.0, 40.0, 16.0, 1.0, "shear_dlower",
        disabled=not (shear_on and _shear_2023),
        help="Lower sieve size of the coarsest aggregate (2023 method only): "
             "ddg = 16 + Dlower (<= 40 mm) for fck <= 60 (8.2.1(4)).")
    if combined_on:
        sts.caption(f"Shear method set by Combined: {combined_method}")
    shear_axis = _seeded_selectbox(
        sts, "Shear direction", list(_SHEAR_AXES),
        next(iter(_SHEAR_AXES)), key="shear_axis", disabled=not shear_on,
        help="The plane the shear acts in. Vertical shear (bending about x) uses "
             "the section depth in y; horizontal shear (about y) uses the width in "
             "x. Sector derives the effective depth d and the web width from this.")
    shear_tension = _seeded_selectbox(
        sts, "Tension face", list(_SHEAR_TENSION), next(iter(_SHEAR_TENSION)),
        key="shear_tension", disabled=not shear_on,
        help="Which face carries tension under the accompanying bending. The "
             "tension reinforcement Asl is the longitudinal bars on that side of "
             "the section centroid, and d is measured from the opposite fibre.")
    sts.caption("The applied shear VEd is entered in the Loads panel.")
    shear_bw = _seeded_number(
        sts, r"Web width $b_w$ (mm, 0 = auto)", 0.0, 100000.0, 0.0, 10.0, "shear_bw",
        disabled=not shear_on,
        help="Smallest web width in the tension zone. 0 derives it from the outline "
             "(minimum solid width over the effective depth); enter a value for a "
             "curved section, where the automatic width is unreliable.")
    # Shear reinforcement (vertical links). When present, the member's resistance is
    # the variable-strut VRd = min(VRd,s, VRd,max) (sec. 6.2.3) rather than VRd,c; the
    # strut angle theta is auto-optimised within the cot(theta) bounds below.
    shear_links = _seeded_checkbox(
        sts, "Shear reinforcement (links) present", False, "shear_links",
        disabled=not shear_on,
        help="Add vertical links (stirrups). The resistance becomes the variable-"
             "strut VRd = min(VRd,s, VRd,max) (EN 1992-1-1 6.2.3); VRd,c is still "
             "shown to indicate whether links are strictly required.")
    _links = shear_on and shear_links
    shear_cot_min = _seeded_number(
        sts, r"Strut $\cot\theta$ min", 0.5, 5.0, 1.0, 0.1, "shear_cot_min",
        disabled=not _links,
        help="Lower bound for the auto-optimised strut angle. EN 1992-1-1 6.7N (and "
             "DK NA:2024 6.7a NA) allow 1 <= cot(theta) <= 2.5; a value outside that "
             "is allowed but warned, not blocked.")
    shear_cot_max = _seeded_number(
        sts, r"Strut $\cot\theta$ max", 0.5, 5.0, 2.5, 0.1, "shear_cot_max",
        disabled=not _links,
        help="Upper bound for the auto-optimised strut angle (cot(theta) = 2.5 is the "
             "code maximum; 1.0 corresponds to a 45-degree strut). Sector picks the "
             "angle in [min, max] that maximises VRd = min(VRd,s, VRd,max).")
    if _links and (shear_cot_min < 1.0 - 1e-9 or shear_cot_max > 2.5 + 1e-9):
        sts.caption("Note: the strut bounds fall outside the code range 1..2.5 "
                    "(6.7N / 6.7a NA) -- allowed, but check the value is justified.")

    sts.markdown("**Torsion (TRd, thin-walled tube)**")
    sts.caption("Torsion resistance from the thin-walled tube idealisation "
                 "(EN 1992-1-1 sec. 6.3): closed stirrups TRd,s, strut crushing "
                 "TRd,max, cracking TRd,c, and the required longitudinal steel. The "
                 "tube (A, u, tef, Ak, uk) is derived from the outline.")
    torsion_on = _seeded_checkbox(
        sts, "Check torsion capacity", False, "torsion_on",
        help="Compute the torsion resistance TRd = min(TRd,s, TRd,max) and the "
             "utilisation TEd/TRd, plus the combined shear+torsion crushing check "
             "(6.29) when links are also defined.")
    torsion_method = _seeded_selectbox(
        sts, "Torsion method", list(_SHEAR_CODES), codes.EC2_2005_DKNA.label,
        key="torsion_method", disabled=(not torsion_on) or combined_on,
        help="Code edition for the torsion rules. The DK NA:2024 uses its plasticity "
             "pure-torsion strut factor nu_t = 0.7*(0.7 - fck/200) (5.104 NA) in "
             "place of the recommended nu = 0.6*(1 - fck/250).")
    if combined_on:
        sts.caption(f"Torsion method set by Combined: {combined_method}")
    sts.caption("The applied torsion TEd is entered in the Loads panel.")
    _tors = torsion_on
    sts.caption("Torsion uses the shared closed stirrup defined in Links / stirrups "
                 "below (one leg carries the shear flow); the required longitudinal "
                 "steel uses the mild-reinforcement design yield.")
    torsion_tef = _seeded_number(
        sts, r"Wall thickness $t_{ef}$ (mm, 0 = auto)", 0.0, 5000.0, 0.0, 5.0,
        "torsion_tef", disabled=not _tors,
        help="Effective wall thickness of the tube. 0 derives it as A/u (capped at "
             "the real wall for a hollow section); enter a value to override.")
    torsion_nu_v = _seeded_checkbox(
        sts, r"$\nu_t = \nu_v$ (closed stirrups + distributed long. steel)", False,
        "torsion_nu_v", disabled=not _tors,
        help="DK NA Figur 5.100 NA: when every tube wall has closed stirrups round "
             "the periphery and uniformly distributed longitudinal steel on both "
             "faces, the torsion strut factor may be raised from nu_t to the "
             "pure-shear nu_v. Only affects the DK NA edition.")
    torsion_subdivide = _seeded_checkbox(
        sts, "Subdivide into sub-tubes (T / compound section)", False,
        "torsion_subdivide", disabled=not _tors,
        help="EN 1992-1-1 6.3.1(3): model a T / L / I / flanged section as component "
             "rectangles, each an equivalent thin-walled tube. TRd is the SUM of the "
             "sub-tube capacities and the applied TEd is split by uncracked torsional "
             "stiffness C = beta*h*b^3 (6.3.1(4)). The FIRST rectangle is the web -- it "
             "carries the shear in the combined V+T checks. Off = the single tube from "
             "the outline.")
    torsion_subrects = []
    if torsion_subdivide and _tors:
        n_sub = int(_seeded_number(
            sts, "Number of sub-rectangles", 2.0, 4.0, 2.0, 1.0, "torsion_nsub",
            help="Component rectangles: a T = web + flange (2), a double console = web "
                 "+ 2 consoles (3). The first is the web."))
        for i in range(n_sub):
            role = "web" if i == 0 else f"part {i + 1}"
            cb, ch = sts.columns(2)
            b_i = _seeded_number(
                cb, f"b{i + 1} (mm) - {role}", 1.0, 100000.0, 300.0, 10.0,
                f"torsion_sub_b{i}", disabled=not _tors,
                help="The width / height order does not matter to the tube.")
            h_i = _seeded_number(
                ch, f"h{i + 1} (mm) - {role}", 1.0, 100000.0, 600.0, 10.0,
                f"torsion_sub_h{i}", disabled=not _tors)
            torsion_subrects.append((b_i, h_i))
        sts.caption("Rectangles should partition the section without overlap "
                    "(6.3.1(3)); the first is the web (it pairs with the shear in the "
                    "combined checks).")
    torsion_cot_min = _seeded_number(
        sts, r"Strut $\cot\theta$ min (torsion)", 0.5, 5.0, 1.0, 0.1,
        "torsion_cot_min", disabled=not _tors,
        help="Lower bound for the auto-optimised torsion strut angle (code range "
             "1..2.5; outside is warned, not blocked).")
    torsion_cot_max = _seeded_number(
        sts, r"Strut $\cot\theta$ max (torsion)", 0.5, 5.0, 2.5, 0.1,
        "torsion_cot_max", disabled=not _tors,
        help="Upper bound for the auto-optimised torsion strut angle. Sector picks "
             "the angle in [min, max] that maximises TRd = min(TRd,s, TRd,max).")
    if _tors and (torsion_cot_min < 1.0 - 1e-9 or torsion_cot_max > 2.5 + 1e-9):
        sts.caption("Note: the torsion strut bounds fall outside the code range "
                    "1..2.5 (6.7N / 6.7a NA) -- allowed, but check it is justified.")

    # One shared stirrup definition for both the shear links and the torsion tube:
    # physically it is the same closed stirrup, whose vertical legs resist shear and
    # whose closed loop resists torsion. Shear uses n legs; torsion uses one leg.
    sts.markdown("**Links / stirrups (shear + torsion)**")
    _stirrups = (shear_on and shear_links) or torsion_on
    sts.caption("The same closed stirrup carries shear (through its legs) and "
                 "torsion (through the closed loop). For torsion the stirrup must be "
                 "closed. Enabled when shear links or the torsion check is on.")
    shear_link_legs = _seeded_number(
        sts, "Stirrup legs (n, for shear)", 1.0, 20.0, 2.0, 1.0, "shear_link_legs",
        disabled=not _stirrups,
        help="Number of vertical legs crossing the shear plane (a single closed "
             "stirrup = 2 legs). Torsion always uses one leg of the closed loop.")
    shear_link_dia = _seeded_number(
        sts, "Stirrup diameter (mm)", 4.0, 40.0, 10.0, 1.0, "shear_link_dia",
        disabled=not _stirrups, help="Stirrup bar diameter; the leg area is pi/4*dia^2.")
    shear_link_s = _seeded_number(
        sts, "Stirrup spacing s (mm)", 10.0, 2000.0, 150.0, 10.0, "shear_link_s",
        disabled=not _stirrups, help="Longitudinal spacing of the stirrups.")
    shear_fywk = _seeded_number(
        sts, r"Stirrup yield $f_{ywk}$ (MPa)", 100.0, 900.0, 500.0, 10.0, "shear_fywk",
        disabled=not _stirrups,
        help="Characteristic yield strength of the stirrup steel; the design value "
             "is fywk / gamma_s of the selected method.")

    # Pre-flight for the combined check (it needs several things at once): flag what
    # is missing in the reserved slot right under its toggle, not only after Calculate.
    if combined_on:
        ok_mark, no_mark = chr(0x2713), chr(0x2717)   # check / cross (BMP, ASCII src)
        reqs = [
            (mode in ("Plastic", "Both"), "Plastic / Both bending analysis"),
            (check_util, "Check utilisation against applied moment"),
            (shear_on, "Shear check enabled"),
            (torsion_on, "Torsion check enabled"),
        ]
        lines = "  \n".join(f"{ok_mark if met else no_mark} {name}"
                            for met, name in reqs)
        if all(met for met, _ in reqs):
            combined_warn.success("Combined M-V-T requirements met:  \n" + lines)
        else:
            combined_warn.warning("Combined M-V-T needs all of these (it is not "
                                  "evaluated until then):  \n" + lines)

    # (Section / Material / Loads expanders were created at the top; fill them now.)
    sec.caption("The section is a set of explicit points (the source of truth). "
                "Use the Quick Section builder to generate a parametric shape and "
                "write its points here, or edit the point tables directly.")
    if sec.button("Quick Section builder...", key="open_qs", width="stretch",
                  help="Open a full-width builder: pick a shape, dimensions and "
                       "reinforcement with a live preview, then Apply to fill the "
                       "point tables."):
        # Do NOT st.rerun() here: this button renders partway through build_inputs, so a
        # rerun would abort the rest of it -- including the deferred Report panel at the
        # end -- and Streamlit drops the unrendered rep_* widget state, resetting the
        # Report metadata. Just set the flag; build_inputs finishes (preserving rep_*)
        # and the _qs_open check after it opens the builder viewport this same run.
        st.session_state["_qs_open"] = True
    clear_pts = sec.button("Clear Section (empty all points)", key="clear_pts",
                           width="stretch",
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
    if vc1.button("+ Add void", key="add_void", width="stretch",
                  disabled=n_voids >= _MAX_VOIDS,
                  help=f"Append a blank separator row, so the next corners you enter "
                       f"start a new void (up to {_MAX_VOIDS})."):
        groups = _void_groups(void_now, _CORNER_COLS)
        _reseed_table("hole_base", "ed_hole",
                      _void_table_from_groups(groups, trailing_blank=True))
    if vc2.button("Remove void", key="rem_void", width="stretch",
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

    # Auto-calc all derived material values lives here (with the values it computes),
    # not next to Calculate -- which it was being mistaken for. It sets a one-shot
    # flag that concrete_panel applies on the rerun (before this button re-renders).
    mat.divider()
    if mat.button("Auto-calc all derived values", key="auto_all_btn", width="stretch",
                  help="Recompute all auto values from the current grade: the concrete "
                       "strain limits eps_c2/eps_cu2/n, fctm and Ec. The modular ratios "
                       "n_l/n_s follow from Ec, Es, Ep and creep automatically."):
        st.session_state["_auto_all"] = True
        st.rerun()

    # Loads: the plastic and elastic analyses take their own load sets, so a
    # capacity check (e.g. ULS) and a stress check (e.g. SLS) use different
    # actions without overwriting each other. The plastic axial force fixes the
    # M-M envelope; its moments are the point checked against it. Both sets stay
    # mounted (the inactive one is disabled) so their values survive a mode
    # switch instead of being reset when Streamlit drops unrendered widgets.
    def _load_set(prefix, n_help, m_help, active, mx_default=0.0, moments_active=None):
        # ``moments_active`` lets the moments lock independently of the axial force
        # (the plastic capacity-only mode keeps N but disables the applied moments).
        moments_active = active if moments_active is None else moments_active
        P = _seeded_number(loads, r"Axial force $N$ (kN, + = tension)", -50000.0,
                           50000.0, 0.0, 50.0, f"{prefix}_P", help=n_help,
                           disabled=not active)
        Mx = _seeded_number(loads, r"Applied $M_x$ (kNm)", -100000.0, 100000.0,
                            mx_default, 10.0, f"{prefix}_Mx", disabled=not moments_active,
                            help=f"{m_help} Bending moment about the x-axis "
                                 "(its stress varies with y).")
        My = _seeded_number(loads, r"Applied $M_y$ (kNm)", -100000.0, 100000.0, 0.0,
                            10.0, f"{prefix}_My", disabled=not moments_active,
                            help="Bending moment about the y-axis (its stress "
                                 "varies with x); biaxial bending.")
        return P, Mx, My

    loads.markdown("**Bending & axial (Plastic)**")
    # The plastic axial force N is also the axial used by the shear and torsion
    # checks (their sigma_cp / alpha_cw), so its input stays enabled whenever any of
    # those checks is on -- even in Elastic-only mode, where the rest of the plastic
    # set is disabled -- so the user can always enter the axial force the result
    # depends on. The moments stay gated on the plastic analysis (envelope only).
    P_pl, Mx_pl, My_pl = _load_set(
        "pl", "External axial force for the plastic M-M capacity envelope; also the "
        "axial N used by the shear and torsion checks (sigma_cp / alpha_cw). Enter "
        "the external force only -- any tendon precompression is added automatically "
        "from the prestress initial strain. Enabled whenever a plastic, shear or "
        "torsion check is active.",
        "Applied moment checked against the plastic envelope (utilisation).",
        plastic_on or shear_on or torsion_on,
        moments_active=plastic_on and check_util)

    # The applied shear VEd and torsion TEd sit with the other capacity actions here
    # (enable each check in Analysis settings to make its input live).
    loads.markdown("**Shear / torsion (Plastic)**")
    shear_V = _seeded_number(
        loads, r"Applied shear $V_{Ed}$ (kN)", 0.0, 100000.0, 0.0, 10.0, "shear_V",
        disabled=not shear_on, help="Design shear force at the section (magnitude). "
        "Enable 'Check shear capacity' in Analysis settings.")
    torsion_T = _seeded_number(
        loads, r"Applied torsion $T_{Ed}$ (kNm)", 0.0, 100000.0, 0.0, 5.0, "torsion_T",
        disabled=not torsion_on, help="Design torsional moment at the section. Enable "
        "'Check torsion capacity' in Analysis settings.")

    loads.divider()
    loads.markdown("**Elastic stresses (long + short term)**")
    loads.caption("A sustained (long-term) and an instantaneous (short-term) action, "
                  "each carried at its own modular ratio so creep is explicit. For an "
                  "instantaneous-only check put the load in the short-term set and "
                  "leave the long-term at zero; set the creep coefficient to zero to "
                  "drop creep for a single load case.")
    loads.markdown("_Long-term_")
    P_el_l, Mx_el_l, My_el_l = _load_set(
        "el_long", "Sustained external axial force (long-term). A tendon's prestress "
        "is applied automatically from its initial strain, so N is the external "
        "force only -- as in the plastic solver; do not add the prestress force here.",
        "Sustained moment (long-term).", elastic_on)
    phi_creep = _seeded_number(loads, r"Creep coefficient $\varphi$ (long-term)", 0.0, 5.0,
                               3.0, 0.1, "el_phi", disabled=not elastic_on,
                               help="Final creep coefficient. The long-term modular "
                                    "ratios use the effective modulus "
                                    "Ec,eff = Ec/(1+phi).")
    loads.markdown("_Short-term_")
    P_el_s, Mx_el_s, My_el_s = _load_set(
        "el_short", "Instantaneous (variable) external axial force (prestress is "
        "applied automatically from the tendon initial strain).",
        "Instantaneous (variable) moment.", elastic_on, mx_default=0.0)
    # The modular ratios are derived from the elastic moduli, not entered: mild steel
    # uses n = Es/Ec and prestress n = Ep/Ec (independent ratios, since Es != Ep), each
    # creep-reduced to E/Ec,eff = E(1+phi)/Ec for the sustained (long-term) state. The
    # scalar nl/ns handed to the solver are the mild-steel ratios; the tendons carry
    # their own ratio per bar (the Ep/Es multiplier), so both pairs are reported below.
    ec_mpa = max(conc_Ec, 1e-6) * 1000.0
    ns = steel.Es / ec_mpa
    nl = steel.Es * (1.0 + phi_creep) / ec_mpa
    ns_p = prestress.Es / ec_mpa
    nl_p = prestress.Es * (1.0 + phi_creep) / ec_mpa
    _modular_ratio_readout(loads, ns, nl, ns_p, nl_p, has_tendons=bool(tendons))

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
    # Split the signature so a change to only the plastic (or only the elastic)
    # inputs recomputes just that analysis; the shared part (geometry, materials,
    # mode) forces both. The overall signature is the pair, so any change is stale.
    _get = lambda keys: tuple(st.session_state.get(k) for k in keys)
    shared_sig = geom_sig + _get(_SHARED_SIG_KEYS)
    plastic_sig = shared_sig + _get(_PLASTIC_SIG_KEYS)
    elastic_sig = shared_sig + _get(_ELASTIC_SIG_KEYS)
    sig = plastic_sig + elastic_sig + _get(_SHEAR_SIG_KEYS)
    st.session_state.pop("_auto_all", None)   # one-shot: applied this run only
    # Fill the reserved Report / Save-Load / About slots now the inputs exist, so
    # the report and the download capture the fully-built section and loads.
    _report_panel(report_slot)
    _save_load_panel(save_slot)
    with about_slot.expander("About", expanded=False):
        st.markdown("### Sector")
        st.caption("Reinforced-concrete and prestressed cross-section analysis.")
        st.markdown(
            "Sector analyses an arbitrary RC (and optionally prestressed) "
            "cross-section and reports:\n"
            "- **Plastic bending capacity** -- the biaxial M-M interaction "
            "envelope and the load utilisation.\n"
            "- **Cracked-section elastic stresses** -- concrete and "
            "reinforcement stresses under the long- and short-term loads.\n"
            "- **Cracking and crack width** -- cracking threshold, section "
            "properties, and optional tension stiffening and crack width.")
        st.markdown("**Workflow**")
        st.caption("Define the section and materials, choose the analyses, then "
                   "press Calculate. The section drawing and the stress-strain "
                   "diagrams update live; the result views update on Calculate.")
        st.divider()
        st.markdown(f"**Sector v{APP_VERSION}**")
        st.caption(f"Author: {APP_AUTHOR}  \nEmail: {APP_EMAIL}")
        st.caption("Internal engineering tool, Sweco.")
        if st.button("User manual", key="open_manual", width="stretch",
                     help="Open the full-width user manual: what Sector computes, "
                          "the theory it applies, its features, and how to use it."):
            # No rerun: build_inputs continues so every panel renders (state kept);
            # the reserved back_slot below shows the Back button on this same run.
            st.session_state["_manual_open"] = True
    # Fill the reserved Back-to-analysis slot now that every panel has rendered, so
    # its rerun cannot drop any sidebar input's widget state.
    if st.session_state.get("_manual_open"):
        if back_slot.button("Back to analysis", type="primary",
                            width="stretch", key="manual_back"):
            st.session_state["_manual_open"] = False
            st.rerun()
    return dict(section=section, void_error=void_error, steel_error=steel_error,
                concrete=concrete, steel=steel,
                bars=bars, outer=outer, holes=holes, tendons=tendons,
                prestress=prestress, P_pl=P_pl, Mx_pl=Mx_pl, My_pl=My_pl,
                check_util=check_util,
                interaction=interaction,
                v_min=v_min, v_max=v_max, v_inc=v_inc,
                P_el_l=P_el_l, Mx_el_l=Mx_el_l, My_el_l=My_el_l, nl=nl,
                P_el_s=P_el_s, Mx_el_s=Mx_el_s, My_el_s=My_el_s, ns=ns,
                el_phi=phi_creep, conc_Ec=conc_Ec,
                sls_cw=sls_cw, sls_fctm=sls_fctm, sls_phi=sls_phi,
                sls_k1=sls_k1, sls_dk_na=sls_dk_na,
                sls_edition=sls_edition, sls_code=sls_code, sls_member=sls_member,
                shear_on=shear_on,
                shear_method=(combined_method if combined_on else shear_method),
                shear_axis=_SHEAR_AXES[shear_axis],
                shear_tension=_SHEAR_TENSION[shear_tension],
                shear_V=shear_V, shear_bw=shear_bw, shear_dlower=shear_dlower,
                shear_links=shear_links, shear_link_legs=shear_link_legs,
                shear_link_dia=shear_link_dia, shear_link_s=shear_link_s,
                shear_fywk=shear_fywk, shear_cot_min=shear_cot_min,
                shear_cot_max=shear_cot_max,
                torsion_on=torsion_on,
                torsion_method=(combined_method if combined_on else torsion_method),
                torsion_T=torsion_T, torsion_tef=torsion_tef,
                torsion_nu_v=torsion_nu_v, torsion_subdivide=torsion_subdivide,
                torsion_subrects=torsion_subrects,
                torsion_cot_min=torsion_cot_min, torsion_cot_max=torsion_cot_max,
                combined_on=combined_on, combined_method=combined_method,
                combined_mv_independent=combined_mv_independent,
                mode=mode, extent=extent, signature=sig,
                plastic_sig=plastic_sig, elastic_sig=elastic_sig)


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


def _gross_area_centroid(outer, holes):
    """Net concrete area (m2) and its centroid ``(cx, cy)`` in metres: the outline
    minus the voids, from the exact polygon moments. Orientation-independent -- the
    centroid ``sx/area`` is unchanged by a sign flip and each area is taken positive.
    Returns ``(0, 0, 0)`` for a degenerate section."""
    mo = geometry.area_moments(outer)
    a = abs(mo.area)
    if a <= 0.0:
        return 0.0, 0.0, 0.0
    cx, cy = mo.sx / mo.area, mo.sy / mo.area
    area, mx, my = a, cx * a, cy * a
    for h in holes or []:
        mh = geometry.area_moments(h)
        ah = abs(mh.area)
        if ah <= 0.0:
            continue
        area -= ah
        mx -= (mh.sx / mh.area) * ah
        my -= (mh.sy / mh.area) * ah
    if area <= 0.0:
        return a, cx, cy
    return area, mx / area, my / area


def _design_yield(mat):
    """Design yield strength f_yd = f_ytk / gamma_y (falls back to f_ytk if unset).

    Taken from the yield parameters, not by sampling stress() at a fixed strain,
    which a hardening or low-rupture-strain law would misread. Used for both the
    2023 shear flexural yield and the torsion longitudinal steel.
    """
    gy = getattr(mat, "gamma_y", 0.0)
    return mat.fytk / gy if gy > 0.0 else mat.fytk


def _prestress_axial(inp):
    """Tendon precompression from the prestress initial strain, in kN (concrete
    compression-positive), for the shear/torsion sigma_cp and alpha_cw.

    Equals the locked-in tendon force ``sum(Ep*IS*Ap)`` -- the same quantity the
    elastic solver applies as a force (so the user's N stays the external axial
    only, EN 1992-1-1 6.2.2(1)/6.2.3(3) include the prestress in sigma_cp). Zero
    without tendons or a prestress material. Recomputed here rather than read from
    ``out['elastic']`` because the shear/torsion checks can run with the elastic
    analysis switched off.
    """
    pre = inp.get("prestress")
    tendons = inp.get("tendons")
    if pre is None or not tendons:
        return 0.0
    sig_ps = pre.Es * pre.IS * 1000.0                  # MPa -> kN/m2 (bar-stress units)
    area_m2 = sum(t[2] for t in tendons) / 1.0e6       # mm2 -> m2
    return sig_ps * area_m2                             # kN (tendon tension = concrete compression)


def _outline_bbox(outer):
    """Bounding box ``(xmin, ymin, xmax, ymax)`` of the outline, or ``None``.

    Used to clip the drawn neutral-axis segment to the section (viz.na_line_at):
    unclipped it spans +/- extent about the origin-closest point, which overshoots
    badly for a section drawn away from the origin.
    """
    outer = [] if outer is None else list(outer)
    if len(outer) < 3:
        return None
    xs = [p[0] for p in outer]
    ys = [p[1] for p in outer]
    return (min(xs), min(ys), max(xs), max(ys))


# Neutral-axis angle giving bending about the shear axis with the tension face on the
# chosen side (the plastic solver's convention: V=90 -> +Mx, tension at the bottom;
# V=0 -> +My, tension on the left). Used to pull the internal lever arm z for shear.
_SHEAR_LEVER_ANGLE = {("x", True): 90.0, ("x", False): 270.0,
                      ("y", True): 0.0, ("y", False): 180.0}


def _shear_lever_arm(inp, axis, tension_low, d_mm):
    """Internal lever arm z (mm) for the shear truss and its source label.

    The plastic engine already computes the lever arm between the concrete
    compression resultant and the steel tension resultant; for shear about the given
    axis this is the depth-direction component of that lever arm (its y-part for
    vertical shear, x-part for horizontal). It is evaluated at the ULS axial force and
    the neutral-axis angle whose bending puts the chosen face in tension. Falls back to
    the EC2-permitted ``z = 0.9 d`` when the lever arm is degenerate (no tension
    reinforcement, a non-converged / fully-compressed state, or a solver error).
    """
    fallback = (0.9 * d_mm, "0.9 d (fallback)")
    if inp["section"] is None:
        return fallback
    angle = _SHEAR_LEVER_ANGLE[(axis, tension_low)]
    pre = inp["prestress"] if inp["tendons"] else None
    try:
        pt = plastic_capacity_at_angle(inp["section"], inp["concrete"], inp["steel"],
                                       -inp["P_pl"], angle, prestress=pre)
    except Exception:
        return fallback
    lever = abs(pt.dy) if axis == "x" else abs(pt.dx)   # depth-direction component, m
    if not pt.converged or lever <= 1e-6:
        return fallback
    return lever * 1000.0, "plastic internal lever arm"


def _shear_face_mrd(inp, axis, tension_low):
    """Pure-axis bending capacity MRd (kNm) for the shear tension chord.

    Evaluated at the neutral-axis angle whose bending is purely about the shear axis
    with the chosen face in tension (the same angle as the lever arm), so MRd is the
    uniaxial chord capacity -- NOT an extremum of the biaxial M-M sweep, whose peak Mx
    can sit at a point carrying a companion My and so overstate the chord capacity on an
    asymmetric section. Returns ``(mrd, exact)``; ``exact`` is False when the solve did
    not converge, so the caller can fall back to the sweep extremum.
    """
    if inp["section"] is None:
        return 0.0, False
    angle = _SHEAR_LEVER_ANGLE[(axis, tension_low)]
    pre = inp["prestress"] if inp["tendons"] else None
    try:
        pt = plastic_capacity_at_angle(inp["section"], inp["concrete"], inp["steel"],
                                       -inp["P_pl"], angle, prestress=pre)
    except Exception:
        return 0.0, False
    if not pt.converged:
        return 0.0, False
    return (abs(pt.Mx) if axis == "x" else abs(pt.My)), True


def _tube_torsion(tube, t_ed, *, tcode, fck, fcd, alpha_cw, fywd, asw_over_s,
                  cot_min, cot_max, nu_detail, fctd, fyd_long):
    """Torsion resistances + utilisation for ONE thin-walled tube at its optimum angle.

    Shared by the single-tube check and each sub-tube of a compound section. Returns a
    dict with the resistances (TRd,s / TRd,max / TRd,c), the chosen ``TRd = min`` and its
    governing mechanism, the optimum ``cot(theta)``, the utilisation ``t_ed / TRd`` and
    the required longitudinal steel ``asl_req``.
    """
    nu_t = tcode.torsion_nu(fck, closed_detailing=nu_detail)
    a_t = asw_over_s * fywd
    b_t = nu_t * alpha_cw * fcd * tube["tef"]
    cot = (shear.optimum_cot_theta(a_t, b_t, cot_min, cot_max)
           if a_t > 0.0 else max(cot_min, 1.0))
    trds = torsion.trd_s(tube["Ak"], fywd, asw_over_s, cot)
    trdmax = torsion.trd_max(fck, tcode, tube["Ak"], tube["tef"], alpha_cw, cot,
                             closed_detailing=nu_detail)
    trd = min(trds, trdmax) if asw_over_s > 0.0 else trdmax
    trdc = torsion.trd_c(fctd, tube["Ak"], tube["tef"])
    util = (t_ed / trd) if trd > 0.0 else math.inf
    asl = torsion.asl_required(t_ed, tube["uk"], tube["Ak"], fyd_long, cot)
    governs = ("stirrups (TRd,s)" if (asw_over_s > 0.0 and trds <= trdmax)
               else "crushing (TRd,max)")
    return dict(tube=tube, t_ed=t_ed, trd_s=trds, trd_max=trdmax, trd=trd, trd_c=trdc,
                cot=cot, theta_deg=math.degrees(math.atan(1.0 / cot)) if cot > 0 else 0.0,
                util=util, asl_req=asl, nu=nu_t, governs=governs, valid=tube["valid"])


def run_analysis(inp, *, reuse_plastic=None, reuse_elastic=None):
    """Run the selected analyses for ``inp`` and return the results payload.

    ``reuse_plastic`` / ``reuse_elastic`` let the caller pass a previously computed
    plastic / elastic sub-result whose inputs are unchanged (its split signature
    matches); that analysis is then skipped and the cached result reused, so a Both
    run that only touched the elastic (or only the plastic) inputs recomputes just
    the affected half.
    """
    out = {}
    if inp["section"] is None or inp.get("void_error") or inp.get("steel_error"):
        return out                          # invalid section -> nothing to run
    if inp["mode"] in ("Plastic", "Both") and reuse_plastic is not None:
        out["plastic"] = reuse_plastic
    elif inp["mode"] in ("Plastic", "Both"):
        vlo, vhi, vstep = _sweep(inp["v_min"], inp["v_max"], inp["v_inc"])
        # A full 360 deg turn returns to the start, so the last angle (v_max) repeats
        # the first (v_min) exactly. Sweep only up to the angle before it -- the
        # envelope closes itself -- so that duplicate point is neither computed nor
        # reported. The closed-envelope flag still reflects the full turn.
        closed = (vhi - vlo) >= 360.0 - 1e-6
        sweep_hi = vhi - vstep if closed else vhi
        # Prestress enters the analysis only when the section actually has tendons.
        pre = inp["prestress"] if inp["tendons"] else None
        # The user enters N tension-positive; the solver is compression-positive, so
        # negate at the boundary (the engine and its verification are unchanged).
        pts = solve_plastic(inp["section"], inp["concrete"], inp["steel"],
                            -inp["P_pl"], vlo, sweep_hi, vstep, prestress=pre)
        mx = [p.Mx for p in pts]
        my = [p.My for p in pts]
        # Utilisation is a closed-envelope check (a partial arc has no wrap-around), and
        # only reported when the user asks to check it; otherwise this is a capacity-only
        # run (the applied moments are ignored and locked).
        check_util = inp.get("check_util", True)
        if closed and check_util:
            util, util_gov = combined.radial_util(mx, my, inp["Mx_pl"], inp["My_pl"])
        else:
            util, util_gov = None, None
        out["plastic"] = dict(
            mx=mx, my=my,
            max_mx=max(mx), max_my=max(my), min_mx=min(mx), min_my=min(my),
            util=util, util_gov=util_gov, closed=closed, check_util=check_util,
            applied=((inp["Mx_pl"], inp["My_pl"]) if check_util else None),
            converged=all(p.converged for p in pts),
            # The solver reports strains compression-positive (its internal
            # convention); negate them so the displayed strains are tension-positive,
            # agreeing with N and the stresses (concrete crushing then reads negative).
            points=[dict(V=p.V, Mx=p.Mx, My=p.My, na_x=p.na_x_intercept,
                         na_y=p.na_y_intercept, eps_c=-p.eps_concrete,
                         eps_s=-p.eps_steel, eps_s_comp=-p.eps_steel_comp,
                         eps_cable=-p.eps_cable, kappa=p.curvature,
                         comp_force=p.compression_force, lever=p.lever_arm,
                         dx=p.dx, dy=p.dy) for p in pts],
        )
        # Opt-in N-M interaction diagrams, one about each bending axis. For each axis
        # trace the +M branch (neutral-axis angle V) and the -M branch (V+180) from
        # pure tension to the squash load, then join them into one closed capacity
        # boundary. About x uses a horizontal neutral axis (V = 90/270, Mx varies);
        # about y a vertical one (V = 0/180, My varies).
        if inp.get("interaction"):
            branch = lambda v: solve_interaction(inp["section"], inp["concrete"],
                                                 inp["steel"], v, prestress=pre)
            loop_x = branch(90.0) + list(reversed(branch(270.0)))
            loop_y = branch(0.0) + list(reversed(branch(180.0)))
            # The solver reports the axial compression-positive; negate it so the
            # diagram and the applied point are both tension-positive (matching N).
            out["plastic"]["interaction"] = dict(
                x=dict(N=[-q.axial for q in loop_x], M=[q.Mx for q in loop_x],
                       applied=(inp["P_pl"], inp["Mx_pl"]),
                       converged=all(q.converged for q in loop_x)),
                y=dict(N=[-q.axial for q in loop_y], M=[q.My for q in loop_y],
                       applied=(inp["P_pl"], inp["My_pl"]),
                       converged=all(q.converged for q in loop_y)),
            )
    if inp["mode"] in ("Elastic", "Both") and reuse_elastic is not None:
        out["elastic"] = reuse_elastic
    elif inp["mode"] in ("Elastic", "Both"):
        # The user enters N tension-positive; the elastic solver takes it
        # compression-positive, so negate it once here and pass the compression form
        # to every elastic call (main solve and the two cracking checks).
        p_el_l, p_el_s = -inp["P_el_l"], -inp["P_el_s"]
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
        r = solve_elastic_combined(sec, p_el_l, inp["Mx_el_l"], inp["My_el_l"],
                                   inp["nl"], p_el_s, inp["Mx_el_s"],
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
        # Cracking is irreversible and is triggered by the maximum load the section
        # ever sees, so the section is cracked if EITHER the sustained (long-term) or
        # the peak (total) action exceeds the cracking stress. The peak check uses
        # the combined creep state (long @ nl superposed with short @ ns), matching
        # the reported Total/RST1 stresses; a short-term action that counteracts the
        # sustained one can leave the peak uncracked while the long-term already
        # cracked, and vice versa. Report the governing (smallest lambda_cr) of the
        # two.
        # cr_l provides the long-term cracked state and the sustained cracking
        # factor; its own crack width is unused (the crack widths are computed
        # below per system), so the coarse flag here is immaterial.
        cr_l = analyse_cracking(
            sec, p_el_l, inp["Mx_el_l"], inp["My_el_l"], inp["nl"],
            fctm=inp["sls_fctm"], Es=inp["steel"].Es, beta=0.5, kt=0.4,
            bar_diameter=phi, k1=k1_bars,
            k3_cover_dependent=dk_na, include_hx_term=include_hx,
            edition=inp["sls_edition"],
            n_mult=n_mult, prestress_stress=prestress_stress)
        crk_t, lam_t, sig_t = combined_cracking(
            sec, p_el_l, inp["Mx_el_l"], inp["My_el_l"], inp["nl"],
            p_el_s, inp["Mx_el_s"], inp["My_el_s"], inp["ns"],
            fctm=inp["sls_fctm"], n_mult=n_mult, prestress_stress=prestress_stress)
        # Governing case. Its cracked state (for the reported cracked properties) is
        # the combined creep total state (r.short_term) when the peak strictly
        # governs, or the long-term cracked state when the sustained action governs.
        # Ties (e.g. no short-term load, where the peak reduces to the sustained
        # check) go to the sustained state, so a long-term-only run keeps its nl
        # cracked properties rather than the instantaneous combined state.
        if lam_t < cr_l.lambda_cr:
            cracked, lambda_cr, sigma_ct, gov_state = crk_t, lam_t, sig_t, r.short_term
        else:
            cracked, lambda_cr, sigma_ct = (cr_l.cracked, cr_l.lambda_cr,
                                            cr_l.sigma_ct)
            gov_state = cr_l.cracked_state
        # Reinforcement enters the transformed properties at n*A, or n*(Ep/Es)*A per
        # tendon via n_mult -- the same per-bar modular ratio the elastic and cracking
        # solves use, so the reported section properties are consistent with them.
        props_un = transformed_properties(sec, inp["nl"], cracked=False, n_mult=n_mult)
        props_cr = (transformed_properties(
            sec, inp["nl"], eps0=gov_state.eps0, kx=gov_state.kx, ky=gov_state.ky,
            cracked=True, n_mult=n_mult) if cracked else None)
        out["elastic"].update(
            cracked=cracked, lambda_cr=lambda_cr, sigma_ct=sigma_ct,
            fctm=inp["sls_fctm"], show_cw=inp["sls_cw"],
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
            # Crack width uses the load-induced steel stress, so strip the locked-in
            # tendon prestress back out of the reported total (mild bars unaffected).
            cw_stress = np.asarray(r.bar_stress_total, dtype=float)
            if prestress_stress is not None:
                cw_stress = cw_stress - prestress_stress
            short_state = dataclasses.replace(r.short_term, bar_stress=cw_stress)

            def _cw(state, n, kt, coarse):
                return crack_width(sec, state, n, fctm=inp["sls_fctm"],
                                   Es=inp["steel"].Es, kt=kt, bar_diameter=phi,
                                   k1=k1_bars, k3_cover_dependent=dk_na,
                                   include_hx_term=include_hx, coarse=coarse,
                                   edition=inp["sls_edition"], n_mult=n_mult)

            # Long-term crack width is on the cracked section under the quasi-permanent
            # load (kt = 0.4), computed directly from the long-term cracked state so it
            # is reported even when the long-term load alone would not cross the
            # cracking threshold. The short-term is the instantaneous total (kt = 0.6).
            out["elastic"].update(
                crack=_crack_dict(_cw(cr_l.cracked_state, inp["nl"], 0.4, False)),
                crack_short=_crack_dict(_cw(short_state, inp["ns"], 0.6, False)),
                crack_code=inp["sls_code"],
                crack_member=(inp["sls_member"] if dk_na else None),
            )
            # The DK NA reports the coarse crack system alongside the fine one, for
            # both load cases (four crack widths in total).
            if dk_na:
                out["elastic"].update(
                    crack_coarse=_crack_dict(_cw(cr_l.cracked_state, inp["nl"], 0.4, True)),
                    crack_short_coarse=_crack_dict(_cw(short_state, inp["ns"], 0.6, True)),
                )
    _run_capacity_checks(inp, out)
    return out


def _run_capacity_checks(inp, out):
    """Shear, torsion and the combined M-V-T checks for ``inp``; mutates ``out``.

    Runs after the independent plastic and elastic analyses. Reads ``inp`` and the
    already-built ``out["plastic"/"shear"/"torsion"]``; writes ``out["shear"]``,
    ``out["torsion"]`` and ``out["combined"]``. One member strut angle serves shear
    AND torsion (EN 1992-1-1 6.3.2(2)), chosen to minimise the governing utilisation
    -- the sizeable strut-angle pass that used to sit inline in run_analysis.
    """
    # ULS axial for the shear/torsion sigma_cp / alpha_cw (EN 1992-1-1 6.2.2/6.2.3):
    # the external axial N (tension-positive P_pl, flipped to compression) PLUS the
    # tendon precompression from the prestress initial strain, so a prestressed member
    # earns its sigma_cp / alpha_cw credit. Compression-positive, as the engines expect.
    n_prestress = _prestress_axial(inp)
    n_ed_comp = -inp["P_pl"] + n_prestress
    # Parameter stashes for the member strut-angle pass below: the links and torsion
    # payloads are built there, at ONE shared angle (EN 1992-1-1 6.3.2(2)).
    link_ctx = None
    tors_ctx = None
    # Shear resistance without shear reinforcement (VRd,c). An independent ULS check,
    # recomputed on every Calculate whenever enabled (cheap; no plastic/elastic
    # reuse). The axial term uses the plastic (ULS) axial force N (tension-positive)
    # plus the tendon precompression, as the compression-positive sigma_cp.
    if inp.get("shear_on"):
        code = _SHEAR_METHODS.get(inp["shear_method"], codes.EC2_2005_DKNA)
        model_2023 = getattr(code, "shear_model", "2005") == "2023"
        axis, tension_low = inp["shear_axis"], inp["shear_tension"]
        ac, cx, cy = _gross_area_centroid(inp["outer"], inp["holes"])
        centroid_coord = cy if axis == "x" else cx
        asl, cg = shear.tension_reinforcement(inp["bars"], axis, tension_low,
                                              centroid_coord)
        d = shear.effective_depth(inp["outer"], axis, tension_low, cg)
        bw_auto = shear.min_web_width(inp["outer"], inp["holes"], axis)
        bw = inp["shear_bw"] if inp["shear_bw"] > 0.0 else bw_auto
        fck = inp["concrete"].fck
        # The 2023 tau_Rd,c uses the flexural-reinforcement design yield and the
        # aggregate size ddg; the 2005 VRd,c ignores both. Take fyd from the yield
        # parameters (fytk/gamma_y) rather than sampling stress() at a fixed strain,
        # which a hardening or low-rupture-strain law would misread.
        fyd_flex = _design_yield(inp["steel"])
        ddg = code.shear_ddg(fck, inp["shear_dlower"]) if model_2023 else 0.0
        res = shear.vrd_c(fck, code, bw, d, asl, n_ed_comp, ac,
                          fyd_mpa=fyd_flex, ddg_mm=(ddg or 32.0))
        v_ed = inp["shear_V"]
        util = (v_ed / res["vrd_c"]) if res["vrd_c"] > 0.0 else math.inf
        # F2: the 2023 tau_Rd,c (8.2.2) carries no axial term, so it silently ignores
        # a net axial TENSION -- unconservative. Flag it for the view/report.
        n2023_tension = bool(model_2023 and n_ed_comp < -1e-9)
        out["shear"] = dict(res=res, v_ed=v_ed, util=util, axis=axis,
                            tension_low=tension_low, bw=bw, bw_auto=bw_auto,
                            bw_user=bool(inp["shear_bw"] > 0.0), d=d, asl=asl,
                            ac=ac, fck=fck, n_ed=inp["P_pl"],
                            n_prestress=n_prestress, n_ed_comp=n_ed_comp,
                            n2023_tension=n2023_tension,
                            method=inp["shear_method"], model_2023=model_2023,
                            ddg=ddg, fyd_flex=fyd_flex)
        # Shear reinforcement (vertical links): the 2005 variable-strut VRd =
        # min(VRd,s, VRd,max), sec. 6.2.3. Not offered for the 2023 method here -- its
        # with-links strain-based truss (8.2.3) is a follow-up; a note is shown in the
        # view instead. The strut angle is NOT chosen here: one member angle serves
        # shear and torsion (6.3.2(2)) and is selected further down to minimise the
        # governing utilisation -- stash the parameters and a builder for that pass.
        if inp.get("shear_links") and not model_2023:
            cot_min = min(inp["shear_cot_min"], inp["shear_cot_max"])
            cot_max = max(inp["shear_cot_min"], inp["shear_cot_max"])
            asw = inp["shear_link_legs"] * templates.bar_area(inp["shear_link_dia"])
            asw_over_s = asw / inp["shear_link_s"] if inp["shear_link_s"] > 0.0 else 0.0
            # z is the internal lever arm actually computed by the plastic engine (the
            # separation of the concrete compression resultant and the steel tension
            # resultant) for bending about the shear axis with the chosen tension face,
            # at the ULS axial force -- not the 0.9d approximation. Fall back to 0.9d
            # only when that lever arm is degenerate (no tension steel / non-converged).
            z_mm, z_src = _shear_lever_arm(inp, axis, tension_low, d)

            def _links_at(cot_lo, cot_hi, _fck=fck, _code=code, _bw=bw, _d=d,
                          _aos=asw_over_s, _ac=ac, _z=z_mm):
                return shear.vrd_links(_fck, _code, _bw, _d, _aos, inp["shear_fywk"],
                                       n_ed_comp, _ac, cot_lo, cot_hi, z_mm=_z)

            link_ctx = dict(build=_links_at, cot_min=cot_min, cot_max=cot_max,
                            asw=asw, asw_over_s=asw_over_s, z_mm=z_mm, z_src=z_src,
                            code=code, v_ed=v_ed, vrd_c=res["vrd_c"],
                            axis=axis, tension_low=tension_low)

    # Torsion (thin-walled tube, sec. 6.3). An independent ULS check: the tube
    # (A, u, tef, Ak, uk) is derived from the outline, the closed stirrups give
    # TRd,s and the struts TRd,max at the auto-optimised angle, plus the required
    # longitudinal steel. When shear links are also present the combined V+T
    # concrete-crushing check (6.29) is evaluated at a common strut angle.
    if inp.get("torsion_on") and inp["section"] is not None:
        tcode = _SHEAR_CODES.get(inp["torsion_method"], codes.EC2_2005_DKNA)
        fck = inp["concrete"].fck
        fcd = tcode.concrete_factor(fck) * fck / tcode.gamma_c
        tac, _tcx, _tcy = _gross_area_centroid(inp["outer"], inp["holes"])
        # sigma_cp = (external N + tendon precompression) / Ac, compression-positive.
        sigma_cp = n_ed_comp / tac / 1000.0 if tac > 0.0 else 0.0
        alpha_cw = tcode.shear_alpha_cw(sigma_cp, fcd)
        tube = torsion.tube_properties(inp["outer"], inp["holes"],
                                       tef_override=inp["torsion_tef"])
        # The torsion tube uses the shared closed stirrup (one leg of the loop) and
        # the section's own mild-reinforcement design yield for the longitudinal steel.
        fywd_t = inp["shear_fywk"] / tcode.gamma_s
        fyd_long = _design_yield(inp["steel"])
        asw_t = templates.bar_area(inp["shear_link_dia"])
        asw_over_s_t = (asw_t / inp["shear_link_s"]
                        if inp["shear_link_s"] > 0.0 else 0.0)
        tcot_min = min(inp["torsion_cot_min"], inp["torsion_cot_max"])
        tcot_max = max(inp["torsion_cot_min"], inp["torsion_cot_max"])
        nu_detail = inp["torsion_nu_v"]   # DK NA Fig 5.100 NA: nu_t raised to nu_v
        # The allowance only actually changes nu on the DK NA edition; the recommended
        # edition's torsion_nu ignores closed_detailing. Record the DISPLAY flag (which
        # drives the "nu raised to nu_v" captions) only when nu truly changed, so a
        # recommended-edition run with the toggle on does not claim an unapplied change.
        nu_detail_applied = bool(
            nu_detail and tcode.torsion_nu(fck, closed_detailing=True)
            != tcode.torsion_nu(fck, closed_detailing=False))
        fctd = 0.7 * codes.fctm(fck) / tcode.gamma_c        # fctk,0.05 / gamma_c
        t_ed = inp["torsion_T"]
        _tk = dict(tcode=tcode, fck=fck, fcd=fcd, alpha_cw=alpha_cw, fywd=fywd_t,
                   asw_over_s=asw_over_s_t, cot_min=tcot_min, cot_max=tcot_max,
                   nu_detail=nu_detail, fctd=fctd, fyd_long=fyd_long)
        # A compound (T / L / I / flanged) section may be modelled as a set of component
        # rectangles, each an equivalent thin-walled tube (EN 1992-1-1 6.3.1(3)): TEd is
        # split by uncracked torsional stiffness (6.3.1(4)) and every sub-tube is checked
        # against its OWN capacity. Because the split is by stiffness, not capacity, a
        # sub-tube can be overstressed (util_i > 1) even while TEd <= sum(TRd_i), so the
        # GOVERNING utilisation is the worst sub-tube (max util_i), not TEd/sum(TRd_i) --
        # sum(TRd_i) is only the theoretical total if the torque could redistribute to
        # match capacity. The FIRST rectangle is the web -- the combined V+T checks pair
        # the shear with it (`primary`). Without subdivision the single tube is used.
        subrects = inp.get("torsion_subrects") or []
        subdivide = bool(inp.get("torsion_subdivide") and subrects)
        # The tube set and the TEd split are strut-angle independent; the per-tube
        # resistances are evaluated below at the MEMBER strut angle (one angle for
        # shear and torsion, 6.3.2(2)).
        if subdivide:
            subtubes, consts, sub_dims = [], [], []
            for (b_mm, h_mm) in subrects:
                bm, hm = b_mm / 1000.0, h_mm / 1000.0
                subtubes.append(
                    torsion.tube_properties(torsion.rectangle_ring(bm, hm), None))
                consts.append(torsion.rectangle_torsion_constant(bm, hm))
                sub_dims.append((b_mm, h_mm))
            ted_parts = torsion.distribute_by_stiffness(t_ed, consts)
        else:
            subtubes, consts, sub_dims, ted_parts = [tube], [1.0], [None], [t_ed]
        tors_ctx = dict(
            _tk=_tk, tube=tube, subdivide=subdivide, subtubes=subtubes, consts=consts,
            ted_parts=ted_parts, sub_dims=sub_dims, t_ed=t_ed, tcode=tcode, fck=fck,
            fcd=fcd, alpha_cw=alpha_cw, fywd_t=fywd_t, fyd_long=fyd_long, asw_t=asw_t,
            asw_over_s_t=asw_over_s_t, tcot_min=tcot_min, tcot_max=tcot_max,
            nu_detail=nu_detail, nu_detail_applied=nu_detail_applied, fctd=fctd,
            sigma_cp=sigma_cp)

    # ---- Member strut angle (EN 1992-1-1 6.3.2(2)) ----------------------------
    # One strut angle serves shear AND torsion (the same web struts carry both).
    # It is chosen to MINIMISE THE GOVERNING UTILISATION over every reported check
    # that depends on it: the stirrup checks relax with a flatter strut while the
    # crushing checks and the longitudinal-chord demand (MEd + 0.5*VEd*cot*z
    # [+ Ftd,T*z/2] vs MRd) grow, so the optimum is load-dependent -- unlike the
    # old per-action angle, which maximised each resistance alone and therefore sat
    # at the band edge regardless of VEd/MEd/NEd. The chord enters the objective as
    # the SAME capped utilisation the app reports (6.2.3(7)), so the chosen angle
    # can never fail a reported check that another admissible angle would pass.
    # Only LIVE checks constrain the angle -- valid AND loaded: an invalid tube
    # (util = inf at every angle) or a companion with zero load must not drag the
    # angle of a valid check. With no live checks (capacity-only runs) the legacy
    # resistance-maximising angles are kept.
    if link_ctx is not None or tors_ctx is not None:
        v_ed_s = link_ctx["v_ed"] if link_ctx is not None else 0.0
        t_ed_s = tors_ctx["t_ed"] if tors_ctx is not None else 0.0
        # Validity probes: a broken links result (no stirrup area / degenerate web)
        # or an invalid tube gives infinite utilisations at EVERY angle, which would
        # otherwise tie the scan and pin the angle at the band edge.
        lk_probe = (link_ctx["build"](link_ctx["cot_min"], link_ctx["cot_min"])
                    if link_ctx is not None else None)
        links_valid = bool(lk_probe is not None and lk_probe["valid"]
                           and lk_probe["vrd_s"] > 0.0 and lk_probe["vrd_max"] > 0.0)
        tors_valid = bool(tors_ctx is not None
                          and all(tb["valid"] for tb in tors_ctx["subtubes"]))
        shear_live = links_valid and v_ed_s > 0.0
        tors_live = tors_valid and t_ed_s > 0.0

        # Longitudinal-chord parameters: the shear tension face's applied moment and
        # pure-axis capacity (the B1 machinery), available when the plastic
        # utilisation was computed and the links provide a lever arm.
        pl = out.get("plastic")
        chord = None
        if links_valid and pl is not None and pl.get("util") is not None:
            l_axis, tlow = link_ctx["axis"], link_ctx["tension_low"]
            m_signed = inp["Mx_pl"] if l_axis == "x" else inp["My_pl"]
            m_ed_l = combined.chord_applied_moment(m_signed, tlow)
            m_rd_l, mrd_exact = _shear_face_mrd(inp, l_axis, tlow)
            if not mrd_exact:
                max_m = pl["max_mx"] if l_axis == "x" else pl["max_my"]
                min_m = pl.get("min_mx" if l_axis == "x" else "min_my", -max_m)
                m_rd_l = max_m if tlow else abs(min_m)
            off_signed = inp["My_pl"] if l_axis == "x" else inp["Mx_pl"]
            off_max = pl["max_my"] if l_axis == "x" else pl["max_mx"]
            off_min = pl.get("min_my" if l_axis == "x" else "min_mx", -off_max)
            off_cap = off_max if off_signed >= 0.0 else abs(off_min)
            off_util = (abs(off_signed) / off_cap if off_cap > 0.0
                        else (math.inf if off_signed else 0.0))
            if m_rd_l > 0.0:
                chord = dict(m_ed=m_ed_l, m_rd=m_rd_l, z_m=link_ctx["z_mm"] / 1000.0,
                             axis=l_axis, tension_low=tlow, off_util=off_util)

        # The scan band comes from the LIVE actions only: a companion that is
        # invalid or carries no load does not constrain the member angle. Bands are
        # "disjoint" only when BOTH actions are live and their bands do not overlap
        # (then the legacy per-action angles + "no common strut angle" flags apply).
        band = None
        bands_disjoint = False
        if shear_live and tors_live:
            band = (max(link_ctx["cot_min"], tors_ctx["tcot_min"]),
                    min(link_ctx["cot_max"], tors_ctx["tcot_max"]))
            bands_disjoint = band[1] < band[0] - 1e-9
        elif shear_live:
            band = (link_ctx["cot_min"], link_ctx["cot_max"])
        elif tors_live:
            band = (tors_ctx["tcot_min"], tors_ctx["tcot_max"])

        @functools.lru_cache(maxsize=4096)
        def _snap(cot):
            """Every strut-angle-dependent resistance at one cot."""
            s = {}
            if link_ctx is not None:
                s["lk"] = link_ctx["build"](cot, cot)
            if tors_ctx is not None:
                tk = dict(tors_ctx["_tk"], cot_min=cot, cot_max=cot)
                s["subs"] = tuple(_tube_torsion(tb, te, **tk)
                                  for tb, te in zip(tors_ctx["subtubes"],
                                                    tors_ctx["ted_parts"]))
            return s

        def _ftd_t_at(cot):
            """Torsion longitudinal force on the web chord (kN) at one cot."""
            if not tors_live:
                return 0.0
            web = _snap(cot)["subs"][0]
            return web["asl_req"] * tors_ctx["fyd_long"] / 1000.0

        utils = []
        if shear_live:
            utils.append(lambda c: combined.ratio(v_ed_s, _snap(c)["lk"]["vrd_s"]))
            utils.append(lambda c: combined.ratio(v_ed_s, _snap(c)["lk"]["vrd_max"]))
        if tors_live:
            for i in range(len(tors_ctx["subtubes"])):
                utils.append(lambda c, i=i: _snap(c)["subs"][i]["util"])
        if links_valid and tors_live and tors_ctx["asw_over_s_t"] > 0.0:
            # The one closed stirrup carries shear AND the web's torsion share (the
            # transverse check); the web struts crush under both (6.29).
            def _shared_stirrup(c):
                sf = (0.0 if v_ed_s <= link_ctx["vrd_c"]
                      else combined.ratio(v_ed_s, _snap(c)["lk"]["vrd_s"]))
                tf = combined.ratio(_snap(c)["subs"][0]["t_ed"],
                                    _snap(c)["subs"][0]["trd_s"])
                return sf + tf

            def _crush_629(c):
                snap = _snap(c)
                return combined.crushing_interaction(
                    snap["subs"][0]["t_ed"], snap["subs"][0]["trd_max"],
                    v_ed_s, snap["lk"]["vrd_max"])
            utils.append(_shared_stirrup)
            utils.append(_crush_629)
        if chord is not None and (shear_live or tors_live):
            # The objective sees EXACTLY the reported chord utilisation (capped per
            # 6.2.3(7)), so the optimiser and the verdicts agree: it steepens the
            # strut while that genuinely lowers the reported check, and stops once
            # the cap saturates (steepening further would only waste stirrups).
            utils.append(lambda c: combined.longitudinal_check(
                chord["m_ed"], chord["m_rd"], 0.5 * v_ed_s * c, _ftd_t_at(c),
                chord["z_m"])["util"])
        if (inp.get("combined_on") and pl is not None and pl.get("util") is not None
                and math.isfinite(pl["util"])
                and links_valid and tors_valid and (shear_live or tors_live)):
            _mv_ind = bool(inp["combined_mv_independent"])

            def _dkna(c, r_m=pl["util"]):
                r_v = combined.ratio(v_ed_s, _snap(c)["lk"]["vrd"])
                r_t = max(s["util"] for s in _snap(c)["subs"])
                return combined.dkna_sum(r_m, r_v, r_t, m_v_independent=_mv_ind)
            utils.append(_dkna)

        cot_star = None
        if band is not None and not bands_disjoint and utils:
            cot_star, _ = combined.governing_strut_cot(utils, band[0], band[1])
        # One label for how the member angle was chosen, reused by every payload:
        #   utilisation -> a live load drove the minimax choice (cot_star found);
        #   disjoint    -> shear and torsion are both live but their cot bands do
        #                  not overlap, so no single angle is admissible;
        #   resistance  -> no live transverse load, so each check sits at its own
        #                  resistance-optimum angle (nothing to optimise).
        theta_mode_str = ("utilisation" if cot_star is not None
                          else "disjoint" if bands_disjoint else "resistance")

        # ---- torsion payload at the member angle (or its own band when no load
        # drives the choice / the bands do not overlap) ----
        if tors_ctx is not None:
            t_ed = tors_ctx["t_ed"]
            subdivide = tors_ctx["subdivide"]
            tk = tors_ctx["_tk"]
            # Pin to the member angle only when torsion is a LIVE participant. A dead
            # companion (TEd = 0) does not join the shared-angle objective, so forcing
            # it to cot_star would report a torsion angle (and TRd) outside the user's
            # own torsion cot band; leave it at its own resistance-optimum instead.
            if cot_star is not None and tors_live:
                tk = dict(tk, cot_min=cot_star, cot_max=cot_star)
            sub_res = [_tube_torsion(tb, te, **tk)
                       for tb, te in zip(tors_ctx["subtubes"], tors_ctx["ted_parts"])]
            governing_sub = None
            if subdivide:
                for r, c, dims in zip(sub_res, tors_ctx["consts"],
                                      tors_ctx["sub_dims"]):
                    r["stiffness"], (r["b_mm"], r["h_mm"]) = c, dims
                valid = all(r["valid"] for r in sub_res)
                trd = sum(r["trd"] for r in sub_res) if valid else 0.0
                asl_req = sum(r["asl_req"] for r in sub_res)
                primary = sub_res[0]
                tube_main = primary["tube"]
                # Governing = the WORST sub-tube (each carries its stiffness share).
                governing_sub = max(range(len(sub_res)),
                                    key=lambda i: sub_res[i]["util"])
                util_t = sub_res[governing_sub]["util"]
            else:
                primary = sub_res[0]
                sub_res = None
                trd, asl_req = primary["trd"], primary["asl_req"]
                tube_main, valid = tors_ctx["tube"], tors_ctx["tube"]["valid"]
                util_t = (t_ed / trd) if trd > 0.0 else math.inf
            tcode = tors_ctx["tcode"]
            tcot_min, tcot_max = tors_ctx["tcot_min"], tors_ctx["tcot_max"]
            lo_t, hi_t = tcode.shear_cot_min_limit, tcode.shear_cot_max_limit
            out["torsion"] = dict(
                tube=tube_main, trd_s=primary["trd_s"], trd_max=primary["trd_max"],
                trd=trd, trd_c=primary["trd_c"], cot=primary["cot"],
                theta_deg=primary["theta_deg"], util=util_t, asl_req=asl_req,
                t_ed=t_ed, fcd=tors_ctx["fcd"], fywd=tors_ctx["fywd_t"],
                fyd_long=tors_ctx["fyd_long"], nu=primary["nu"],
                alpha_cw=tors_ctx["alpha_cw"], fctd=tors_ctx["fctd"],
                nu_v_detailing=tors_ctx["nu_detail_applied"],
                sigma_cp=tors_ctx["sigma_cp"], n_prestress=n_prestress,
                asw_t=tors_ctx["asw_t"], asw_over_s=tors_ctx["asw_over_s_t"],
                dia=inp["shear_link_dia"], s=inp["shear_link_s"], cot_min=tcot_min,
                cot_max=tcot_max, method=inp["torsion_method"],
                governs=primary["governs"], valid=valid,
                reason=tube_main.get("reason"), cot_limit_lo=lo_t, cot_limit_hi=hi_t,
                out_of_limits=bool(tcot_min < lo_t - 1e-9 or tcot_max > hi_t + 1e-9),
                subdivided=subdivide, subtubes=sub_res, primary=primary,
                governing_sub=governing_sub,
                theta_mode=(theta_mode_str if tors_live else "resistance"))

        # ---- links payload at the member angle ----
        if link_ctx is not None:
            v_ed = link_ctx["v_ed"]
            # Pin to the member angle only when shear is a LIVE participant; a dead
            # shear companion (VEd = 0) keeps its own resistance-optimum rather than
            # being forced to a torsion-driven angle outside its own cot band.
            if cot_star is not None and shear_live:
                lk = link_ctx["build"](cot_star, cot_star)
            else:
                lk = link_ctx["build"](link_ctx["cot_min"], link_ctx["cot_max"])
            util_l = (v_ed / lk["vrd"]) if lk["vrd"] > 0.0 else math.inf
            # delta_Ftd = 0.5*VEd*cot(theta): extra longitudinal tension from shear.
            delta_ftd = 0.5 * v_ed * lk["cot"] if lk["valid"] else 0.0
            code = link_ctx["code"]
            lo, hi = code.shear_cot_min_limit, code.shear_cot_max_limit
            # The reported longitudinal-chord check (capped per 6.2.3(7)), on the
            # shear tension face; the torsion term is the web tube's share (zero
            # without torsion). Shown in the Shear view and reused by the combined
            # view, so both present the same numbers.
            lchk = None
            if chord is not None and lk["valid"]:
                # The torsion term comes from the BUILT torsion payload (the web
                # tube's Asl at ITS final angle) -- with disjoint bands the links
                # angle can lie outside the torsion band, so evaluating Ftd,T there
                # would use an inadmissible torsion angle.
                p_web = out.get("torsion", {}).get("primary")
                ftd_t_star = (p_web["asl_req"] * tors_ctx["fyd_long"] / 1000.0
                              if (p_web is not None and tors_live) else 0.0)
                lchk = combined.longitudinal_check(chord["m_ed"], chord["m_rd"],
                                                   delta_ftd, ftd_t_star,
                                                   chord["z_m"])
                lchk.update(valid=True, axis=chord["axis"],
                            tension_low=chord["tension_low"],
                            off_util=chord["off_util"],
                            biaxial=bool(chord["off_util"] > 0.05),
                            has_torsion=tors_live,
                            theta_mode=theta_mode_str)
            out["shear"].update(
                links=dict(res=lk, util=util_l, asw=link_ctx["asw"],
                           asw_over_s=link_ctx["asw_over_s"],
                           legs=inp["shear_link_legs"], dia=inp["shear_link_dia"],
                           s=inp["shear_link_s"], fywk=inp["shear_fywk"],
                           cot_min=link_ctx["cot_min"], cot_max=link_ctx["cot_max"],
                           delta_ftd=delta_ftd, cot_limit_lo=lo, cot_limit_hi=hi,
                           z_source=link_ctx["z_src"],
                           out_of_limits=bool(link_ctx["cot_min"] < lo - 1e-9
                                              or link_ctx["cot_max"] > hi + 1e-9),
                           required=bool(v_ed > link_ctx["vrd_c"]), chord=lchk,
                           theta_mode=(theta_mode_str if shear_live
                                       else "resistance")))

        # ---- checks that pair shear and torsion, at the member angle ----
        if tors_ctx is not None:
            t_ed = tors_ctx["t_ed"]
            primary = out["torsion"]["primary"]
            # Minimum-reinforcement screen (EN 1992-1-1 6.3.2(5), Eq 6.31): for an
            # approximately solid rectangular section, no DESIGNED shear+torsion
            # reinforcement (only the minimum) is needed if TEd/TRd,c + VEd/VRd,c <= 1.
            sh_ms = out.get("shear")
            _trdc = primary["trd_c"]
            if tors_ctx["subdivide"]:
                # 6.31 is written for an approximately solid rectangular section, so
                # it does not apply to a subdivided compound section.
                out["torsion"]["min_reinf"] = dict(
                    applicable=False, reason="subdivided (compound) section")
            elif sh_ms is None or not sh_ms["res"]["valid"]:
                out["torsion"]["min_reinf"] = dict(applicable=False,
                                                   reason="no shear check")
            elif _trdc <= 0.0 or sh_ms["res"]["vrd_c"] <= 0.0:
                out["torsion"]["min_reinf"] = dict(applicable=False,
                                                   reason="zero resistance")
            else:
                vrd_c_ms, v_ed_ms = sh_ms["res"]["vrd_c"], sh_ms["v_ed"]
                screen = t_ed / _trdc + v_ed_ms / vrd_c_ms
                out["torsion"]["min_reinf"] = dict(
                    applicable=True, value=screen, ok=bool(screen <= 1.0 + 1e-9),
                    t_ed=t_ed, trd_c=_trdc, v_ed=v_ed_ms, vrd_c=vrd_c_ms,
                    solid=bool(not inp["holes"]),
                    model_2023=bool(sh_ms.get("model_2023")))
            # Combined shear+torsion concrete crushing (6.29) at the member angle,
            # pairing the shear with the PRIMARY (web) tube's torsion share.
            sh_links = out.get("shear", {}).get("links")
            p_tube, t_ed_p = primary["tube"], primary["t_ed"]
            if sh_links is not None and sh_links["res"]["valid"] and p_tube["valid"]:
                # The plain band intersection: the fallback angle for a no-load run
                # and the disjointness test for the 6.29 flag.
                pl_lo = max(link_ctx["cot_min"], tors_ctx["tcot_min"])
                pl_hi = min(link_ctx["cot_max"], tors_ctx["tcot_max"])
                if cot_star is None and pl_hi < pl_lo - 1e-9:
                    # No strut angle is admissible for both shear and torsion, so the
                    # shared-angle crushing check (6.29) is undefined -- flag it.
                    # (With a live single-action scan the member angle exists and the
                    # zero-load companion does not constrain it.)
                    out["torsion"]["interaction"] = dict(
                        valid=False, reason="no common strut angle",
                        cot_shear=(link_ctx["cot_min"], link_ctx["cot_max"]),
                        cot_torsion=(tors_ctx["tcot_min"], tors_ctx["tcot_max"]))
                else:
                    # The member angle when a load drives it; otherwise the
                    # least-conservative common angle (cot = 1 clamped to the band).
                    cot_c = (cot_star if cot_star is not None
                             else min(max(1.0, pl_lo), pl_hi))
                    trdmax_c = torsion.trd_max(
                        tors_ctx["fck"], tors_ctx["tcode"], p_tube["Ak"],
                        p_tube["tef"], tors_ctx["alpha_cw"], cot_c,
                        closed_detailing=tors_ctx["nu_detail"])
                    vlk = link_ctx["build"](cot_c, cot_c)
                    inter = combined.crushing_interaction(
                        t_ed_p, trdmax_c, v_ed_s, vlk["vrd_max"])
                    out["torsion"]["interaction"] = dict(
                        valid=True, cot=cot_c,
                        theta_deg=math.degrees(math.atan(1.0 / cot_c)),
                        trd_max=trdmax_c, vrd_max=vlk["vrd_max"], t_ed=t_ed_p,
                        v_ed=v_ed_s, value=inter)

    # Combined bending + shear + torsion (M-V-T), sec. 6.3.2. Ties the three checks
    # together: the concrete-crushing interaction (6.29, from the torsion block) and
    # the DK NA sum(SEd/SRd) <= 1 rule (6.3.2(6)). Requires the plastic utilisation
    # (M, at the applied N), the shear utilisation (V) and the torsion utilisation (T).
    if inp.get("combined_on"):
        pl = out.get("plastic")
        sh = out.get("shear")
        to = out.get("torsion")
        r_m = pl.get("util") if pl else None
        have_m = r_m is not None
        have_v = sh is not None and sh["res"]["valid"]
        have_t = to is not None and to["valid"]
        if have_m and have_v and have_t:
            sl = sh.get("links")
            r_v = sl["util"] if sl is not None else sh["util"]
            r_t = to["util"]
            indep = bool(inp["combined_mv_independent"])
            dk_sum = combined.dkna_sum(r_m, r_v, r_t, m_v_independent=indep)
            out["combined"] = dict(
                valid=True, method=inp["combined_method"], r_m=r_m, r_v=r_v, r_t=r_t,
                m_v_independent=indep, dkna_sum=dk_sum, dkna_ok=dk_sum <= 1.0 + 1e-9,
                crushing=to.get("interaction"),
                asl_torsion=to["asl_req"],
                delta_ftd=(sl["delta_ftd"] if sl is not None else 0.0),
                links=sl is not None)
            # Longitudinal-steel combined check (the appendix's mode 1): computed once
            # in the strut-angle pass (the Shear view shows the same numbers) and
            # surfaced here with the combined verdicts.
            lchk = sl.get("chord") if sl is not None else None
            if lchk is not None:
                out["combined"]["longitudinal"] = lchk
            # Shared-stirrup transverse check: the one closed stirrup carries shear
            # AND torsion, so their demands add; the web struts crush under both.
            # Evaluated AT the member strut angle (both demands and both resistances
            # at the same theta as every other check).
            if sl is not None and sl["res"]["valid"] and to["asw_over_s"] > 0.0:
                inter = to.get("interaction")
                if inter is not None and not inter.get("valid"):
                    # The shear and torsion strut-angle bands do not overlap, so no
                    # single angle can satisfy both -- the shared-stirrup check is
                    # undefined. Flag it rather than inventing a common angle.
                    out["combined"]["transverse"] = dict(
                        valid=False, reason="no common strut angle",
                        cot_shear=inter.get("cot_shear"),
                        cot_torsion=inter.get("cot_torsion"))
                else:
                    # The shared stirrup is on the web, so its torsion demand is the
                    # PRIMARY (web) sub-tube's share against that tube's TRd,s; when
                    # VEd <= VRd,c the concrete alone carries the shear (6.2.1) and
                    # the whole stirrup serves torsion.
                    v_ed, t_ed_w = sh["v_ed"], to["primary"]["t_ed"]
                    vrd_c = sh["res"]["vrd_c"]
                    # Label with the MEMBER angle the shared-stirrup numbers are
                    # actually evaluated at (cot_c = cot_star): u_crush = interaction
                    # value and the web torsion share both sit there. sl["res"]["cot"]
                    # only equals it when shear is a live participant -- with a dead
                    # shear companion (VEd = 0) the links are de-pinned to their own
                    # band, so reading their cot here would mislabel the check.
                    cot_b = inter["cot"] if inter is not None else sl["res"]["cot"]
                    shear_credited = v_ed <= vrd_c
                    sf = (0.0 if shear_credited
                          else combined.ratio(v_ed, sl["res"]["vrd_s"]))
                    tf = combined.ratio(t_ed_w, to["primary"]["trd_s"])
                    u_stir = sf + tf
                    u_crush = (inter["value"] if inter is not None
                               else combined.ratio(v_ed, sl["res"]["vrd_max"]))
                    out["combined"]["transverse"] = dict(
                        valid=True,
                        cot=cot_b, theta_deg=math.degrees(math.atan(1.0 / cot_b)),
                        u_stirrup=u_stir, u_crush=u_crush,
                        governing=max(u_stir, u_crush),
                        governs=("crushing" if u_crush > u_stir else "stirrups"),
                        ok=bool(max(u_stir, u_crush) <= 1.0 + 1e-9),
                        shear_fraction=sf, torsion_fraction=tf,
                        shear_credited=shear_credited, vrd_c=vrd_c, v_ed=v_ed)
        else:
            out["combined"] = dict(valid=False, have_m=have_m, have_v=have_v,
                                   have_t=have_t, method=inp["combined_method"])


# ---------------------------------------------------------------------------
# Views (main area). A "View" dropdown selects what fills the main viewport,
# the way BriCoS switches between its result diagrams. The Section drawing and
# the stress-strain diagrams reflect the inputs live; the Plastic and Elastic
# result views need a Calculate.
# ---------------------------------------------------------------------------

# View order follows the results workflow: the live input previews first, then the
# plastic bending results (envelope + its N-M diagram kept adjacent), then elastic,
# then the shear/torsion/combined checks.
VIEWS = ["Section", "Stress-Strain diagrams", "Plastic Results", "N-M Interaction",
         "Elastic Results", "Shear", "Torsion", "M-V-T Combined"]
# The result views (everything except the two live input previews) -- used for the
# staleness banner and to know which views need a Calculate.
_RESULT_VIEWS = tuple(v for v in VIEWS
                      if v not in ("Section", "Stress-Strain diagrams"))


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
                "in the Section panel, or open the Quick Section builder. Any "
                "reinforcement you have added is still drawn below.")
    bar_xy = [(b[0], b[1], b[2]) for b in inp["bars"]]
    tendon_xy = [(t[0], t[1], t[2]) for t in inp["tendons"]]
    sig = (inp["outer"], inp["holes"], bar_xy, tendon_xy,
           inp["label_scale"], inp["label_min_gap"])
    fig = _memo_fig("section", sig, lambda: viz.section_figure(
        inp["outer"], inp["holes"], bar_xy, title="Section", tendons=tendon_xy,
        show_labels=True, label_scale=inp["label_scale"],
        label_min_gap=inp["label_min_gap"], height=640, scale=_MM, unit="mm"))
    st.plotly_chart(fig, width="stretch")


def materials_view(inp):
    """Stress-strain diagrams for the chosen materials (live, no Calculate).

    One diagram per row (full width) so each curve is large and easy to read. The
    material objects are value-comparable (frozen dataclasses), so the figures are
    memoised on them and only rebuilt when a material parameter actually changes.
    """
    conc, steel, pre = inp["concrete"], inp["steel"], inp["prestress"]
    st.plotly_chart(_memo_fig("concrete", conc, lambda: viz.concrete_curve_figure(conc)),
                    width="stretch")
    st.plotly_chart(_memo_fig("steel", steel, lambda: viz.steel_curve_figure(steel)),
                    width="stretch")
    if pre is not None:
        st.plotly_chart(_memo_fig("prestress", pre, lambda: viz.prestress_curve_figure(pre)),
                        width="stretch")


def _fmt(v):
    """Format a coordinate, showing an infinite neutral-axis intercept as 'inf'."""
    return "inf" if not math.isfinite(v) else f"{v:.3f}"


def _plastic_table(pts, cable, steel_comp=False):
    """Per-angle results table, one row per neutral-axis angle. ``steel_comp`` splits
    the steel-strain column into a tensile and a compression column (only meaningful
    when the mild steel is active in compression)."""
    eps_s_cols = ({f"{_EPS}s,t (%)": [round(pt["eps_s"], 3) for pt in pts],
                   f"{_EPS}s,c (%)": [round(pt["eps_s_comp"], 3) for pt in pts]}
                  if steel_comp else
                  {f"{_EPS}s (%)": [round(pt["eps_s"], 3) for pt in pts]})
    cols = {
        "V (deg)": [round(pt["V"], 1) for pt in pts],
        "Mx (kNm)": [round(pt["Mx"], 3) for pt in pts],
        "My (kNm)": [round(pt["My"], 3) for pt in pts],
        "NA x (mm)": [_fmt(pt["na_x"] * _MM) for pt in pts],
        "NA y (mm)": [_fmt(pt["na_y"] * _MM) for pt in pts],
        f"{_EPS}c (%)": [round(pt["eps_c"], 3) for pt in pts],
        **eps_s_cols,
        f"{_KAPPA} (1/m)": [round(pt["kappa"], 4) for pt in pts],
        "Comp (kN)": [round(pt["comp_force"], 3) for pt in pts],
        "L (mm)": [round(pt["lever"] * _MM, 3) for pt in pts],
        "Dx (mm)": [round(pt["dx"] * _MM, 3) for pt in pts],
        "Dy (mm)": [round(pt["dy"] * _MM, 3) for pt in pts],
    }
    if cable:
        cols[f"{_EPS}cable (%)"] = [round(pt["eps_cable"], 3) for pt in pts]
    return cols


def _plastic_bar_hover(points, hp, kappa, material, prestrain=0.0):
    """Per-bar hover strings 'sigma = X MPa, eps = Y %' at a plastic state.

    From the strain plane -- the compression half-plane ``hp`` gives the signed
    distance ``d`` from the neutral axis, so the section strain is ``kappa*d``
    (compression positive) -- and the material's design stress. Tension-positive: the
    net strain is ``prestrain - kappa*d`` (prestrain 0 for mild bars, IS for tendons)
    and the stress is the design stress at that strain, matching the solver's per-bar
    integration. ``points`` are in metres (the half-plane units)."""
    if material is None:
        return None
    a, b, c = hp
    out = []
    for p in points:
        eps = prestrain - kappa * (a * p[0] + b * p[1] + c)   # net strain, tension +
        sig = material.stress(eps, design=True)               # MPa, tension +
        out.append(f"{_SIGMA} = {sig:.1f} MPa, {_EPS} = {eps * 100.0:.3f} %")
    return out


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
    m1.metric("Max $M_x$", f"{p['max_mx']:.3f} kNm")
    m2.metric("Min $M_x$", f"{min_mx:.3f} kNm")
    m3.metric("Max $M_y$", f"{p['max_my']:.3f} kNm")
    m4.metric("Min $M_y$", f"{min_my:.3f} kNm")
    if not p.get("check_util", True):
        m5.metric("Utilisation", "-",
                  help="Capacity-only run: the applied moments are not checked. "
                       "Enable 'Check utilisation against applied moment' to check.")
    elif p["util"] is None:
        m5.metric("Utilisation", "-",
                  help="Only meaningful for a full 0-360 deg sweep; the current "
                       "sweep is a partial arc.")
    else:
        m5.metric("Utilisation", f"{p['util']:.3f}",
                  help="applied / capacity in the load direction")
    st.plotly_chart(
        viz.interaction_figure(p["mx"], p["my"], applied=p.get("applied"),
                               angles=[pt["V"] for pt in p["points"]],
                               util=p.get("util"), closed=p.get("closed", True)),
        width="stretch")

    # Default to the utilisation-governing angle (the state in the applied load's
    # direction) when a utilisation was checked; otherwise show the strongest-about-x
    # state, which is a sensible landmark for a capacity-only run.
    gov_i = p.get("util_gov")
    default_i = (gov_i if gov_i is not None and gov_i < len(pts)
                 else max(range(len(pts)), key=lambda i: pts[i]["Mx"]))
    # The sweep length varies with V.min/V.max/V.inc; clamp a stale selection.
    if st.session_state.get("pl_state", 0) >= len(pts):
        st.session_state["pl_state"] = default_i
    sel = st.selectbox("Neutral-axis state", range(len(pts)), index=default_i,
                       format_func=lambda i: f"{i + 1}: V = {pts[i]['V']:.0f} deg",
                       key="pl_state",
                       help="Inspect the section state at one swept neutral-axis angle.")
    pt = pts[sel]
    hp = viz.plastic_halfplane(pt["V"], pt["na_x"], pt["na_y"])
    na = viz.na_line_at(hp[0], hp[1], hp[2], inp["extent"],
                        bbox=_outline_bbox(inp["outer"]))
    cL, cR = st.columns([3, 2])
    with cL:
        bar_xy = [(b[0], b[1], b[2]) for b in inp["bars"]]
        tendon_xy = [(t[0], t[1], t[2]) for t in inp["tendons"]]
        # Colour the steel by its tension/compression state at this neutral-axis
        # angle, like the elastic view. Mild bars follow the side of the neutral
        # axis; tendons carry their locked-in prestrain so one on the compression
        # side still reads as tension. Points are in metres (the half-plane units).
        pre_IS = inp["prestress"].IS if inp["prestress"] is not None else 0.0
        bar_colors = viz.halfplane_bar_colors(inp["bars"], hp, kappa=pt["kappa"])
        tendon_colors = viz.halfplane_bar_colors(inp["tendons"], hp, kappa=pt["kappa"],
                                                 prestrain=pre_IS)
        # Per-bar stress/strain at this rotation, shown on hover (varies with V).
        bar_hover = _plastic_bar_hover(inp["bars"], hp, pt["kappa"], inp["steel"])
        tendon_hover = _plastic_bar_hover(inp["tendons"], hp, pt["kappa"],
                                          inp["prestress"], prestrain=pre_IS)
        st.plotly_chart(
            viz.section_figure(inp["outer"], inp["holes"], bar_xy, na_line=na,
                               bar_colors=bar_colors, tendons=tendon_xy,
                               tendon_colors=tendon_colors,
                               zones=viz.compression_zones(inp["outer"], hp),
                               title=f"Section at V = {pt['V']:.0f} deg "
                                     "(green tension, red compression)",
                               show_labels=True, label_scale=inp["label_scale"],
                               label_min_gap=inp["label_min_gap"], scale=_MM, unit="mm",
                               bar_hover=bar_hover, tendon_hover=tendon_hover),
            width="stretch")
        st.caption("Hover a bar or tendon for its design stress and strain at this "
                   "rotation (tension-positive). The summary reports the extreme "
                   "tensile and compression strains.")
    with cR:
        # Split the bar strain into its tensile and compression extreme only when
        # there are mild bars that are active in compression (a tendon-only section has
        # no mild bar to compress). Also guard on the field being present so a pre-v0.40
        # reused payload (which lacks eps_s_comp) degrades to the single strain.
        active_comp = (inp["steel"].active_in_compression and bool(inp["bars"])
                       and "eps_s_comp" in pt)
        lines = [
            f"- **$M_x$ / $M_y$**: {pt['Mx']:.3f} / {pt['My']:.3f} kNm",
            f"- **Curvature $\\kappa$**: {pt['kappa']:.4g} 1/m",
            f"- **Compression force**: {pt['comp_force']:.3f} kN",
            f"- **Lever arm $L$**: {pt['lever'] * _MM:.3f} mm  "
            f"($D_x$ {pt['dx'] * _MM:.3f}, $D_y$ {pt['dy'] * _MM:.3f})",
            f"- **Concrete strain $\\varepsilon_c$**: {pt['eps_c']:.3f} %",
        ]
        if active_comp:
            lines.append(f"- **Steel strain, tension $\\varepsilon_{{s,t}}$**: "
                         f"{pt['eps_s']:.3f} %")
            lines.append(f"- **Steel strain, compression $\\varepsilon_{{s,c}}$**: "
                         f"{pt['eps_s_comp']:.3f} %")
        else:
            lines.append(f"- **Steel strain $\\varepsilon_s$**: {pt['eps_s']:.3f} %")
        if inp["tendons"]:
            lines.append(f"- **Tendon strain $\\varepsilon_p$**: {pt['eps_cable']:.3f} %")
        lines.append(f"- **NA intercepts**: x {_fmt(pt['na_x'] * _MM)}, "
                     f"y {_fmt(pt['na_y'] * _MM)} mm")
        st.markdown("\n".join(lines))
        st.caption("Strains are tension-positive (compression negative), agreeing "
                   "with N and the stresses -- so a crushing concrete strain reads "
                   "negative.")

    with st.expander("Full results table (per neutral-axis angle)"):
        # Size the table to all rows so the page scrolls, not the table itself.
        steel_comp = (inp["steel"].active_in_compression and bool(inp["bars"])
                      and bool(pts) and "eps_s_comp" in pts[0])
        st.dataframe(_plastic_table(pts, bool(inp["tendons"]), steel_comp),
                     hide_index=True, width="stretch",
                     height=35 * (len(pts) + 1) + 3)


def interaction_view(inp, results):
    """Axial-moment (N-M) interaction diagrams about both bending axes."""
    if not inp.get("interaction"):
        st.info("Enable 'N-M interaction diagrams' in Analysis settings, "
                "then run a Plastic or Both analysis and press Calculate.")
        return
    if not results or "plastic" not in results or "interaction" not in results["plastic"]:
        st.info("Run a Plastic or Both analysis, then press Calculate.")
        return
    d = results["plastic"]["interaction"]
    dx, dy = d["x"], d["y"]
    # The pure-axial extremes (squash load, tension limit) are the same for either
    # bending axis; take them across both boundaries so the metrics are consistent.
    # N is tension-positive, so the squash (compression) load is the minimum and the
    # tension limit the maximum.
    all_N = list(dx["N"]) + list(dy["N"])
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Squash load $N_c$", f"{min(all_N):.3f} kN")
    m2.metric("Tension limit $N_t$", f"{max(all_N):.3f} kN")
    m3.metric("Max $M_x$", f"{max(dx['M']):.3f} kNm")
    m4.metric("Max $M_y$", f"{max(dy['M']):.3f} kNm")
    show_applied = inp.get("check_util")
    cL, cR = st.columns(2)
    with cL:
        st.plotly_chart(viz.interaction_nm_figure(
            dx["N"], dx["M"], axis="x",
            applied=dx.get("applied") if show_applied else None,
            title="N-Mx interaction"), width="stretch")
    with cR:
        st.plotly_chart(viz.interaction_nm_figure(
            dy["N"], dy["M"], axis="y",
            applied=dy.get("applied") if show_applied else None,
            title="N-My interaction"), width="stretch")
    st.caption("Capacity boundary about each axis, from pure tension to the squash "
               "load. The marked point is the applied plastic action ($N$, $M$); "
               "inside the curve is safe. Concrete carries compression only, so the "
               "tension end is reinforcement-controlled. Hover any point for its "
               "$N$ and $M$.")


def elastic_view(inp, results):
    """Cracked-section elastic stresses: peak concrete, neutral axis, the section
    diagnostic and per-bar stresses, matching the handcalc verification."""
    if not results or "elastic" not in results:
        st.info("Run an Elastic or Both analysis, then press Calculate.")
        return
    e = results["elastic"]
    m1, m2 = st.columns(2)
    m1.metric("Max concrete compression", f"{e['max_conc']:.3f} MPa",
              help=f"at concrete corner {e['max_conc_point'] + 1}")
    m2.metric("Max steel tension", f"{e['max_steel']:.3f} MPa",
              help=f"in bar {e['max_steel_bar']}")

    # Modular ratios are derived (not entered); report the values actually used. Mild
    # steel and prestress differ (Es != Ep), so both pairs are shown when tendons exist.
    _nl, _ns = inp["nl"], inp["ns"]
    ratio_txt = (f"Modular ratios ($E_s/E_c$, $E_p/E_c$; creep-reduced for long-term): "
                 f"mild $n_s$ = {_ns:.3f}, $n_l$ = {_nl:.3f}")
    if inp["tendons"] and inp.get("prestress") is not None:
        _r = inp["prestress"].Es / inp["steel"].Es
        ratio_txt += f"; prestress $n_s$ = {_ns * _r:.3f}, $n_l$ = {_nl * _r:.3f}"
    st.caption(ratio_txt)

    # The tendon prestress is applied automatically from the initial strain, so N
    # is the external force only; show the equivalent prestress action that was added.
    ps = e.get("prestress")
    if ps is not None:
        # ps[0] is the tendon tension resultant; the prestress precompresses the
        # section, so as an axial action (tension-positive) it is a compression.
        st.caption(f"Applied tendon prestress (from the initial strain): "
                   f"N = {-ps[0]:.3f} kN, $M_x$ = {ps[1]:.3f} kNm, $M_y$ = {ps[2]:.3f} kNm "
                   f"(N tension-positive; this equivalent action is added to the external N/M).")

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
    na = (viz.na_line_at(hp[0], hp[1], hp[2], inp["extent"],
                         bbox=_outline_bbox(inp["outer"])) if hp else None)
    zones = viz.compression_zones(inp["outer"], hp) if hp else None
    # Tendons fold into the bar set for the solve, but are drawn as diamonds (bars
    # as circles), each coloured by its stress sign -- consistent with the other
    # views. The stress list runs bars first, then tendons.
    nb = len(inp["bars"])
    bar_xy = [(b[0], b[1], b[2]) for b in inp["bars"]]
    tendon_xy = [(t[0], t[1], t[2]) for t in inp["tendons"]]
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
        width="stretch")

    # The per-bar stress table sits below the figure, sized to all rows.
    st.markdown("**Steel stresses (MPa, tension +)**")
    n = len(e["total"])
    st.dataframe(
        {"Bar": list(range(1, n + 1)),
         "Total": [round(s, 3) for s in e["total"]],
         "Long": [round(s, 3) for s in e["long"]],
         "Dif": [round(s, 3) for s in e["dif"]],
         "RST1": [round(s, 3) for s in e["rst1"]]},
        hide_index=True, width="stretch", height=35 * (n + 1) + 3)
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
    st.markdown("#### Cracking and crack width")
    if e["cracked"]:
        st.warning(f"**Cracked** - the uncracked concrete tension reaches $f_{{ctm}}$ "
                   f"at a load factor $\\lambda_{{cr}}$ = {e['lambda_cr']:.3f} "
                   f"(governing of the long-term and total actions; "
                   f"= $M_{{cr}}/M$ for pure bending).")
    else:
        lam = "infinite" if math.isinf(e["lambda_cr"]) else f"{e['lambda_cr']:.3f}"
        st.success(f"**Uncracked** - peak concrete tension {e['sigma_ct']:.3f} MPa "
                   f"< $f_{{ctm}}$ {e['fctm']:.3f} MPa under both the long-term and "
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
        st.dataframe(data, hide_index=True, width="stretch")
        st.caption("Transformed ($n_l$-weighted) properties about the section "
                   "centroid; the cracked column drops the concrete in tension. "
                   "Ix resists Mx (bending about the x-axis).")
    with pR:
        if show_cw:
            _crack_width_panel(e)


def _crack_width_panel(e):
    """Crack width (EC2 7.3.4) for the long-term and short-term load cases, side
    by side. The DK NA reports the fine and the coarse crack system (four columns);
    each bar's clear cover is taken from the geometry and the bar with the largest
    wk governs, reported per load case."""
    cl, cs = e.get("crack"), e.get("crack_short")
    clc, csc = e.get("crack_coarse"), e.get("crack_short_coarse")
    st.markdown(f"**Crack width $w_k$** ({e.get('crack_code', 'EC2 7.3.4')})")
    if cl is None and cs is None and clc is None and csc is None:
        st.info("No crack width: uncracked, or no bar in tension, under either "
                "the long-term or the short-term load.")
        return
    quants = ["wk (mm)", "sr,max (mm)", f"{_EPS}sm - {_EPS}cm",
              f"{_SIGMA}s (MPa)", f"{_RHO}p,eff", "hc,ef (m)", "cover c (mm)",
              f"bar dia {_PHI} (mm)", "gov. bar"]
    keys = ["wk", "sr_max", "esm_ecm", "sigma_s", "rho_p_eff", "hc_ef", "cover",
            "phi", "gov_bar"]
    fmts = ["{:.3f}", "{:.3f}", "{:.3e}", "{:.3f}", "{:.4f}", "{:.3f}", "{:.3f}",
            "{:.3f}", "{:d}"]

    def column(c):
        if c is None:
            return ["-"] * len(keys)
        return [f.format(c[k]) for k, f in zip(keys, fmts)]

    has_coarse = clc is not None or csc is not None
    if has_coarse:
        # DK NA: fine and coarse crack systems, each for both load cases.
        data = {"Quantity": quants, "Long-term (fine)": column(cl),
                "Short-term (fine)": column(cs), "Long-term (coarse)": column(clc),
                "Short-term (coarse)": column(csc)}
    else:
        data = {"Quantity": quants, "Long-term": column(cl),
                "Short-term": column(cs)}
    st.dataframe(data, hide_index=True, width="stretch")
    st.caption("Governing (largest-$w_k$) bar per load case; each bar's clear cover "
               "is the distance to the nearest concrete face minus its radius.")
    member = e.get("crack_member")
    if member:
        st.caption(r"DK NA: cover-dependent $k_3 = 3.4(25/c)^{2/3}$, reported for both "
                   f"the fine and the coarse crack system (7.3.4(1): centroid-matched "
                   f"effective area, $w_k$ halved). Member type = {member} (the "
                   f"(h-x)/3 effective-height term applies to slabs and prestressed "
                   f"members, fine system only).")


def shear_view(inp, results):
    """Shear resistance without shear reinforcement (VRd,c) and the utilisation.

    Reports the resistance, the derived geometry (effective depth, web width,
    tension reinforcement) and the intermediate quantities of EN 1992-1-1 sec.
    6.2.2(1), then the utilisation VEd/VRd,c.
    """
    if not results or "shear" not in results:
        if not inp.get("shear_on"):
            st.info("Enable 'Check shear capacity' in Analysis settings, "
                    "then press Calculate.")
        else:
            st.info("Press Calculate to run the shear check.")
        return
    sh = results["shear"]
    res = sh["res"]
    axis_lbl = ("Vertical (bending about x)" if sh["axis"] == "x"
                else "Horizontal (bending about y)")
    face_lbl = viz.tension_face_label(sh["tension_low"])
    if not res["valid"]:
        st.warning("VRd,c is zero -- there is no tension reinforcement on the chosen "
                   "face, or the derived effective depth / web width is zero. Add "
                   "tension bars on that face and check the geometry (or enter bw).")
    util = sh["util"]
    ok = viz.util_ok(util)
    m1, m2, m3 = st.columns(3)
    m1.metric("Applied VEd", f"{sh['v_ed']:.3f} kN")
    m2.metric("Resistance VRd,c", f"{res['vrd_c']:.3f} kN")
    util_txt = _pct(util)
    m3.metric("Utilisation VEd/VRd,c", util_txt, delta=("OK" if ok else "Over limit"),
              delta_color=("normal" if ok else "inverse"))
    pre_note = (f" plus tendon precompression {sh['n_prestress']:.1f} kN (from the "
                "prestress initial strain)" if sh.get("n_prestress") else "")
    st.caption(f"{axis_lbl} shear, tension on the {face_lbl} face. Method: "
               f"{sh['method']}. The axial term uses the plastic axial force "
               f"N = {sh['n_ed']:.1f} kN (tension-positive){pre_note}.")
    if sh.get("n2023_tension"):
        st.warning("This 2023 " + _TAU + "Rd,c formula (8.2.2) carries no axial term, "
                   "so the net axial TENSION on the section is ignored -- an "
                   "UNCONSERVATIVE result, as tension lowers the real shear "
                   "resistance (8.2.2(4) / the strain-based 8.2.3, not implemented). "
                   "Use a 2005 edition, which reduces VRd,c via k1*" + _SIGMA + "cp, "
                   "or account for the tension separately.")

    bw_note = ("user input" if sh["bw_user"]
               else f"auto = min solid width {sh['bw_auto']:.1f} mm")
    st.markdown("**Derived quantities**")
    if sh.get("model_2023"):
        st.dataframe(
            {"Quantity": ["Effective depth d", "Web width bw", "Lever arm z",
                          "Tension reinf. Asl", f"Reinf. ratio {_RHO}l",
                          "Aggregate ddg", f"{_TAU}Rd,c", f"{_TAU}Rd,c,min",
                          "Flexural fyd", "gamma_v"],
             "Value": [f"{sh['d']:.1f} mm", f"{sh['bw']:.1f} mm ({bw_note})",
                       f"{res['z']:.1f} mm (0.9 d)", f"{sh['asl']:.1f} mm2",
                       f"{res['rho_l']:.4f}", f"{res['ddg']:.1f} mm",
                       f"{res['tau_rdc']:.3f} MPa", f"{res['tau_min']:.3f} MPa",
                       f"{res['fyd']:.1f} MPa", f"{res['gamma_v']:.2f}"]},
            hide_index=True, width="stretch")
        st.caption(
            r"$\tau_{Rd,c} = \max[\,(0.66/\gamma_V)(100\,\rho_l f_{ck} d_{dg}/d)^{1/3},"
            r"\ \tau_{Rd,c,min}]$ (EN 1992-1-1:2023, 8.27); "
            r"$V_{Rd,c} = \tau_{Rd,c}\,b_w z$, $z = 0.9d$. "
            r"$d_{dg} = 16 + D_{lower}$ ($\leq 40$ mm). $A_{sl}$ is the tension "
            "reinforcement on the chosen face, assumed fully anchored beyond d.")
    else:
        st.dataframe(
            {"Quantity": ["Effective depth d", "Web width bw", "Tension reinf. Asl",
                          f"Reinf. ratio {_RHO}l", "Size factor k",
                          f"Axial stress {_SIGMA}cp", "Concrete area Ac",
                          "CRd,c", "vmin", "fcd"],
             "Value": [f"{sh['d']:.1f} mm", f"{sh['bw']:.1f} mm ({bw_note})",
                       f"{sh['asl']:.1f} mm2",
                       f"{res['rho_l']:.4f} ({chr(0x2264)} 0.02)",
                       f"{res['k']:.3f} ({chr(0x2264)} 2.0)",
                       f"{res['sigma_cp']:.3f} MPa ({chr(0x2264)} 0.2 fcd)",
                       f"{sh['ac'] * 1e6:.0f} mm2", f"{res['crd_c']:.4f}",
                       f"{res['vmin']:.3f} MPa", f"{res['fcd']:.2f} MPa"]},
            hide_index=True, width="stretch")
        st.caption(
            r"$V_{Rd,c} = \max[\,C_{Rd,c}\,k(100\,\rho_l f_{ck})^{1/3} + k_1\sigma_{cp},"
            r"\ v_{min} + k_1\sigma_{cp}]\,b_w d$, with $k_1 = "
            f"{res['k1']:.2f}$. "
            r"$A_{sl}$ is the tension reinforcement on the chosen face, assumed fully "
            r"anchored ($\geq l_{bd} + d$) beyond the section.")

    if sh.get("model_2023") and inp.get("shear_links"):
        st.info("The 2023 method's strain-based check for members WITH shear "
                "reinforcement (8.2.3) is not yet implemented; only tau_Rd,c is "
                "shown. Select a 2005 edition for a links check.")

    # Shear reinforcement (links): the governing check when present.
    links = sh.get("links")
    if links is not None:
        lk = links["res"]
        st.divider()
        st.markdown("**Shear reinforcement (links)**")
        if not lk["valid"]:
            st.warning("The link resistance could not be computed -- check the leg "
                       "count, diameter and spacing (Asw/s must be > 0).")
        if links["out_of_limits"]:
            st.warning(f"The strut angle bounds (cot {_THETA} in "
                       f"[{links['cot_min']:.2f}, {links['cot_max']:.2f}]) fall "
                       f"outside the code range [{links['cot_limit_lo']:.1f}, "
                       f"{links['cot_limit_hi']:.1f}] (EN 1992-1-1 6.7N / DK NA 6.7a "
                       "NA). The value is still computed, but check it is justified.")
        req_txt = ("links are required (VEd > VRd,c)" if links["required"]
                   else "links are not strictly required (VEd <= VRd,c); minimum "
                        "reinforcement rules still apply")
        st.caption(f"For this VEd, {req_txt}.")
        util_l = links["util"]
        ok_l = viz.util_ok(util_l)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("VRd,s", f"{lk['vrd_s']:.3f} kN")
        c2.metric("VRd,max", f"{lk['vrd_max']:.3f} kN")
        c3.metric("VRd = min", f"{lk['vrd']:.3f} kN", help=f"governed by {lk['governs']}")
        ul_txt = _pct(util_l)
        c4.metric("Utilisation VEd/VRd", ul_txt,
                  delta=("OK" if ok_l else "Over limit"),
                  delta_color=("normal" if ok_l else "inverse"))
        st.dataframe(
            {"Quantity": [f"Strut angle {_THETA}", f"cot {_THETA} (auto)",
                          "Lever arm z", "Link area/spacing Asw/s", "Design yield fywd",
                          f"Strut factor {_NU}1", f"Chord factor {_ALPHA}cw",
                          f"Extra long. tension {_DELTA}Ftd"],
             "Value": [f"{lk['theta_deg']:.1f} deg", f"{lk['cot']:.3f}",
                       f"{lk['z']:.1f} mm ({links['z_source']})",
                       f"{links['asw']:.1f} mm2 / {links['s']:.0f} mm "
                       f"({links['legs']:.0f} x {chr(0x00F8)}{links['dia']:.0f})",
                       f"{lk['fywd']:.1f} MPa", f"{lk['nu1']:.3f}",
                       f"{lk['alpha_cw']:.3f}", f"{links['delta_ftd']:.1f} kN"]},
            hide_index=True, width="stretch")
        if links.get("theta_mode") == "utilisation":
            theta_txt = ("Sector selects ONE member strut angle " + _THETA +
                         " (shared with torsion when enabled, EN 1992-1-1 "
                         "6.3.2(2)) that MINIMISES THE GOVERNING UTILISATION: a "
                         "flatter strut relaxes the stirrups but raises the "
                         "crushing demand and the longitudinal chord tension, so "
                         "the chosen angle depends on VEd, MEd and NEd.")
        else:
            theta_txt = (r"Sector auto-optimises $\theta$ within the bounds to "
                         r"maximise $V_{Rd} = \min(V_{Rd,s}, V_{Rd,max})$.")
        st.caption(
            r"$V_{Rd,s} = (A_{sw}/s)\,z f_{ywd}\cot\theta$ (6.8); "
            r"$V_{Rd,max} = \alpha_{cw} b_w z\,\nu_1 f_{cd}/(\cot\theta+\tan\theta)$ "
            r"(6.9). " + theta_txt +
            r" $\Delta F_{td} = 0.5 V_{Ed}\cot\theta$ is the extra longitudinal "
            "tension the tension chord must also carry.")
        # Longitudinal chord under M + V (+ T): the same check the combined view
        # shows, computed at the member strut angle.
        ch = links.get("chord")
        if ch is not None and ch.get("valid"):
            st.markdown("**Longitudinal chord: bending + shear"
                        + (" + torsion" if ch.get("has_torsion") else "")
                        + " tension**")
            face_lbl = viz.tension_face_label(ch.get("tension_low", True))
            g1, g2, g3 = st.columns(3)
            g1.metric(f"MEd (about {ch['axis']})", f"{ch['m_ed']:.1f} kNm")
            g2.metric("MEd,total", f"{ch['m_total']:.1f} kNm",
                      help="bending + shear shift (+ torsion) as an equivalent "
                           "moment on the tension chord")
            if ch.get("biaxial"):
                g3.metric("MEd,total/MRd", _pct(ch["util"]),
                          help="uniaxial (shear-plane) chord only -- see the "
                               "warning below")
            else:
                g3.metric("MEd,total/MRd", _pct(ch["util"]),
                          delta=("OK" if ch["ok"] else "Over limit"),
                          delta_color=("normal" if ch["ok"] else "inverse"))
            obj_note = (" This demand is part of the strut-angle objective, so "
                        + _THETA + " backs off the band edge when the chord would "
                        "otherwise govern."
                        if ch.get("theta_mode") == "utilisation" else "")
            st.caption(
                f"Tension chord = the shear tension face ({face_lbl}). "
                r"$M_{Ed,total} = M_{Ed} + \Delta F_{td}\,z + F_{td,T}\,z/2 = "
                f"{ch['m_ed']:.1f} + {ch['mv']:.1f} + {ch['mt']:.1f} = "
                f"{ch['m_total']:.1f}$ kNm vs $M_{{Rd}} = {ch['m_rd']:.1f}$ kNm "
                f"(pure bending about {ch['axis']} at the applied N); "
                f"$z = {ch['z']:.3f}$ m." + obj_note)
            if ch.get("capped"):
                st.caption("The shear shift is capped so bending + shear does not "
                           "exceed MRd (6.2.3(7)); the strut-angle objective uses "
                           "this same capped demand.")
            if ch.get("biaxial"):
                st.warning(
                    f"Biaxial bending: a moment about the OTHER axis is acting "
                    f"({_pct(ch['off_util'])} of that axis' capacity). This "
                    "uniaxial chord check does not evaluate the off-axis chord -- "
                    "rely on the combined " + chr(0x03A3) + "(SEd/SRd) check.")
        st.plotly_chart(viz.truss_figure(lk["theta_deg"], lk["z"], links["legs"],
                                         links["dia"], links["s"]), width="stretch")


def torsion_view(inp, results):
    """Torsion resistance from the thin-walled tube (TRd,s / TRd,max / TRd,c), the
    required longitudinal steel, and the combined shear+torsion crushing check."""
    if not results or "torsion" not in results:
        if not inp.get("torsion_on"):
            st.info("Enable 'Check torsion capacity' in Analysis settings, "
                    "then press Calculate.")
        else:
            st.info("Press Calculate to run the torsion check.")
        return
    t = results["torsion"]
    tube = t["tube"]
    if not t["valid"]:
        if t.get("reason") == "multi-cell (2+ voids)":
            st.warning("Torsion is not available for a multi-cell section (two or "
                       "more voids): the thin-walled single-tube idealisation does "
                       "not model the internal webs, so its TRd would be "
                       "unconservative (EN 1992-1-1 6.3.2(1) requires sub-dividing "
                       "into separate tubes). Use a solid or single-cell outline.")
        else:
            st.warning("The torsion tube could not be formed from the outline (a "
                       "degenerate or too-thin section). Enter a wall thickness tef "
                       "to override, or check the geometry.")
        return
    if t["out_of_limits"]:
        st.warning(f"The strut bounds (cot {_THETA} in [{t['cot_min']:.2f}, "
                   f"{t['cot_max']:.2f}]) fall outside the code range "
                   f"[{t['cot_limit_lo']:.1f}, {t['cot_limit_hi']:.1f}] "
                   "(6.7N / 6.7a NA). The value is still computed.")
    util = t["util"]
    ok = viz.util_ok(util)
    util_txt = _pct(util)
    if t.get("subdivided"):
        m1, m2, m3 = st.columns(3)
        m1.metric("Applied TEd", f"{t['t_ed']:.3f} kNm")
        m2.metric(chr(0x03A3) + " TRd,i", f"{t['trd']:.3f} kNm",
                  help="theoretical sum of the sub-tube capacities (6.3.1(3)); the "
                       "pass/fail check is the governing sub-tube, not this sum")
        m3.metric("Governing util (max TEd_i/TRd_i)", util_txt,
                  delta=("OK" if ok else "Over limit"),
                  delta_color=("normal" if ok else "inverse"))
    else:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Applied TEd", f"{t['t_ed']:.3f} kNm")
        m2.metric("TRd = min", f"{t['trd']:.3f} kNm", help=f"governed by {t['governs']}")
        m3.metric("Cracking TRd,c", f"{t['trd_c']:.3f} kNm")
        m4.metric("Utilisation TEd/TRd", util_txt, delta=("OK" if ok else "Over limit"),
                  delta_color=("normal" if ok else "inverse"))

    if t.get("subdivided"):
        subs = t["subtubes"]
        c_tot = sum(s["stiffness"] for s in subs) or 1.0
        if t.get("theta_mode") == "utilisation":
            angle_clause = (f"every sub-tube is at the ONE member strut angle "
                            f"(6.3.2(2), cot {_THETA} = {t['cot']:.3f}), shared with "
                            "the shear check and selected to minimise the governing "
                            "utilisation")
        else:
            angle_clause = ("each sub-tube is at its OWN resistance-optimum strut angle "
                            "(no single member angle applies -- see the cot column)")
        st.caption(f"Compound section (6.3.1(3)): TRd = {chr(0x03A3)} of the sub-tube "
                   f"capacities; TEd is split by uncracked torsional stiffness "
                   r"$C = \beta\,h\,b^3$ (6.3.1(4)). The first row (web) carries the "
                   f"shear in the combined V+T checks; {angle_clause}. "
                   f"Method: {t['method']}.")
        st.markdown("**Sub-tubes (TRd = " + chr(0x03A3) + " TRd,i)**")
        st.dataframe(
            {"Sub-tube": [("web" if i == 0 else f"part {i + 1}")
                          for i in range(len(subs))],
             "b x h (mm)": [f"{s['b_mm']:.0f} x {s['h_mm']:.0f}" for s in subs],
             "tef (mm)": [f"{s['tube']['tef']:.1f}" for s in subs],
             "Ak (mm2)": [f"{s['tube']['Ak'] * 1e6:.0f}" for s in subs],
             f"cot {_THETA}": [f"{s['cot']:.3f}" for s in subs],
             "Stiffness": [f"{s['stiffness'] / c_tot * 100:.1f} %" for s in subs],
             "TEd,i (kNm)": [f"{s['t_ed']:.3f}" for s in subs],
             "TRd,i (kNm)": [f"{s['trd']:.3f}" for s in subs],
             "TEd/TRd,i": [_pct(s["util"]) for s in subs],
             "Governs": [s["governs"] for s in subs]},
            hide_index=True, width="stretch")
        g = t.get("governing_sub")
        gov_lbl = (("web" if g == 0 else f"part {g + 1}") if g is not None else "-")
        st.caption(f"Governing sub-tube: {gov_lbl} (worst TEd_i/TRd_i = {util_txt}). "
                   "Because TEd is split by stiffness, not capacity, the section passes "
                   "only when EVERY sub-tube passes (max util), not when TEd <= "
                   f"{chr(0x03A3)}TRd,i. Total longitudinal steel {chr(0x03A3)}Asl = "
                   f"{t['asl_req']:.0f} mm2 (sum over the sub-tubes), in ADDITION to the "
                   "bending steel.")
        st.plotly_chart(viz.subtube_figure(subs), width="stretch")
    else:
        theta_note = ("the ONE member strut angle (6.3.2(2)), shared with the shear "
                      "check and selected to minimise the governing utilisation"
                      if t.get("theta_mode") == "utilisation"
                      else "auto-optimised for the torsion resistance")
        st.caption(f"{t['theta_deg']:.1f} deg strut (cot {_THETA} = {t['cot']:.3f}, "
                   f"{theta_note}). Method: {t['method']}. TRd,s = {t['trd_s']:.3f} "
                   f"kNm, TRd,max = {t['trd_max']:.3f} kNm.")
        tef_note = ("user input" if tube["tef_user"]
                    else ("auto A/u, capped at the wall" if tube["tef_capped"]
                          else "auto = A/u"))
        st.markdown("**Tube idealisation and torsion quantities**")
        st.dataframe(
            {"Quantity": ["Gross area A", "Outer perimeter u", "Wall thickness tef",
                          "Enclosed area Ak", "Centre-line perimeter uk",
                          f"Strut factor {_NU}", f"Chord factor {_ALPHA}cw",
                          "Required long. steel " + chr(0x03A3) + "Asl"],
             "Value": [f"{tube['A'] * 1e6:.0f} mm2", f"{tube['u'] * 1e3:.0f} mm",
                       f"{tube['tef']:.1f} mm ({tef_note})",
                       f"{tube['Ak'] * 1e6:.0f} mm2",
                       f"{tube['uk'] * 1e3:.0f} mm", f"{t['nu']:.3f}",
                       f"{t['alpha_cw']:.3f}", f"{t['asl_req']:.0f} mm2"]},
            hide_index=True, width="stretch")
        st.caption(
            r"$T_{Rd,s} = (A_{sw}/s)\,2 A_k f_{ywd}\cot\theta$ (6.28); "
            r"$T_{Rd,max} = 2\,\nu\,\alpha_{cw} f_{cd} A_k t_{ef}\sin\theta\cos\theta$ "
            r"(6.30); $T_{Rd,c} = 2 A_k t_{ef} f_{ctd}$. The required longitudinal "
            r"steel $\sum A_{sl} = T_{Ed}\,u_k\cot\theta / (2 A_k f_{yd})$ (6.28) is "
            "in ADDITION to the bending reinforcement on the tension side.")
        st.plotly_chart(viz.tube_figure(inp["outer"], inp.get("holes"), tube["tef"],
                                        ak_m2=tube["Ak"]), width="stretch")
    if t.get("n_prestress"):
        st.caption(f"{_ALPHA}cw uses {_SIGMA}cp = {t['sigma_cp']:.3f} MPa, which "
                   f"includes the tendon precompression {t['n_prestress']:.1f} kN "
                   "(from the prestress initial strain) as well as the axial N.")
    if t.get("nu_v_detailing"):
        st.caption(f"{_NU} = {_NU}v (raised from {_NU}t) under DK NA Figur 5.100 NA: "
                   "closed stirrups round the periphery + distributed longitudinal "
                   "steel on both faces.")

    mr = t.get("min_reinf")
    if mr is not None:
        st.divider()
        st.markdown("**Minimum-reinforcement screen (6.3.2(5), Eq 6.31)**")
        if not mr.get("applicable"):
            st.caption("Enable the shear check (VRd,c) as well to evaluate the 6.31 "
                       "screen TEd/TRd,c + VEd/VRd,c <= 1.")
        else:
            val = mr["value"]
            ok_mr = mr["ok"]
            s1, s2, s3 = st.columns(3)
            s1.metric("TEd / TRd,c", f"{mr['t_ed'] / mr['trd_c'] * 100:.1f} %")
            s2.metric("VEd / VRd,c", f"{mr['v_ed'] / mr['vrd_c'] * 100:.1f} %")
            s3.metric("Sum (<= 100%)", f"{val * 100:.1f} %",
                      delta=("minimum reinf. suffices" if ok_mr
                             else "designed reinf. required"),
                      delta_color=("normal" if ok_mr else "inverse"))
            solid_note = ("Assumes an approximately solid rectangular section."
                          if mr["solid"] else "This section has a void: 6.31 is for "
                          "solid sections, so it does not strictly apply (a hollow "
                          "section needs the full shear + torsion check).")
            ed_note = (" VRd,c here is the 2023 tau_Rd,c, which carries no axial term."
                       if mr["model_2023"] else "")
            st.caption("TEd/TRd,c + VEd/VRd,c <= 1 (6.3.2(5), Eq 6.31): if satisfied, "
                       "only minimum shear + torsion reinforcement is required -- no "
                       "designed stirrups for these actions. " + solid_note + ed_note)

    inter = t.get("interaction")
    if inter is not None and not inter.get("valid"):
        st.divider()
        st.markdown("**Combined shear + torsion (concrete crushing, 6.29)**")
        st.warning(_no_common_angle_msg(inter))
    elif inter is not None:
        st.divider()
        st.markdown("**Combined shear + torsion (concrete crushing, 6.29)**")
        val = inter["value"]
        ok_i = viz.util_ok(val)
        i1, i2, i3 = st.columns(3)
        i1.metric("TEd / TRd,max", f"{(inter['t_ed']/inter['trd_max']*100):.1f} %"
                  if inter["trd_max"] > 0 else "inf")
        i2.metric("VEd / VRd,max", f"{(inter['v_ed']/inter['vrd_max']*100):.1f} %"
                  if inter["vrd_max"] > 0 else "inf")
        val_txt = _pct(val)
        i3.metric("Sum (<= 100%)", val_txt, delta=("OK" if ok_i else "Over limit"),
                  delta_color=("normal" if ok_i else "inverse"))
        st.caption(
            "TEd/TRd,max + VEd/VRd,max <= 1 (6.29), evaluated at a common strut angle "
            f"cot {_THETA} = {inter['cot']:.2f} ({inter['theta_deg']:.1f} deg) -- both "
            "TRd,max and VRd,max peak near 45 deg, so this is the least-conservative "
            "shared angle. TRd,max and VRd,max here are at that common angle, so they "
            "differ from the stand-alone values above.")


_pct = viz.pct   # shared util-% formatter (see app/viz.py); keeps screen == report


def _no_common_angle_msg(d):
    """Message for a combined check whose shear and torsion cot(theta) bands do not
    overlap, so no single strut angle satisfies both."""
    cs, ct = d.get("cot_shear", (0, 0)), d.get("cot_torsion", (0, 0))
    return (f"No common strut angle: the shear cot {_THETA} band "
            f"[{cs[0]:.2f}, {cs[1]:.2f}] and the torsion band "
            f"[{ct[0]:.2f}, {ct[1]:.2f}] do not overlap, so no single strut angle "
            "satisfies both. Align the shear and torsion cot(theta) bounds.")


def combined_view(inp, results):
    """Combined M-V-T interaction: the concrete-crushing (6.29) and DK NA
    sum(SEd/SRd) checks across the plastic (M), shear (V) and torsion (T) results."""
    if not results or "combined" not in results:
        if not inp.get("combined_on"):
            st.info("Enable 'Check combined M-V-T' in Analysis settings "
                    "(with Plastic, the shear check and the torsion check), then "
                    "press Calculate.")
        else:
            st.info("Press Calculate to run the combined check.")
        return
    c = results["combined"]
    if not c["valid"]:
        missing = []
        if not c.get("have_m"):
            missing.append("plastic bending (M) with a utilisation "
                           "(enable Plastic and 'Check utilisation')")
        if not c.get("have_v"):
            missing.append("a valid shear check (V)")
        if not c.get("have_t"):
            missing.append("a valid torsion check (T)")
        st.warning("The combined check needs all three actions. Missing: "
                   + "; ".join(missing) + ".")
        return
    st.caption(f"Shared code edition: {c['method']}.")
    m1, m2, m3 = st.columns(3)
    m1.metric("Bending M", _pct(c["r_m"]))
    m2.metric("Shear V", _pct(c["r_v"]))
    m3.metric("Torsion T", _pct(c["r_t"]))
    st.caption("Each is the action's utilisation acting alone (M is the plastic M-M "
               "envelope at the applied N; V and T the shear and torsion checks).")

    st.divider()
    st.markdown("**DK NA 6.3.2(6): " + chr(0x03A3) + "(SEd/SRd) <= 1**")
    ok = c["dkna_ok"]
    d1, d2 = st.columns([1, 2])
    d1.metric(chr(0x03A3) + "(SEd/SRd)", _pct(c["dkna_sum"]),
              delta=("OK" if ok else "Over limit"),
              delta_color=("normal" if ok else "inverse"))
    if c["m_v_independent"]:
        d2.caption("M and V are checked separately (shear longitudinal steel "
                   "provided): sum = max(M+T, V+T). N is folded into the bending "
                   "utilisation.")
    else:
        d2.caption("sum = M + V + T (each alone; N folded into the bending "
                   "utilisation). Turn on 'M & V separate' if the shear longitudinal "
                   "steel beyond bending is provided (then sum = max(M+T, V+T)).")

    cr = c.get("crushing")
    if cr is not None and cr.get("valid"):
        st.divider()
        st.markdown("**Concrete crushing (6.29): TEd/TRd,max + VEd/VRd,max <= 1**")
        val = cr["value"]
        ok_c = viz.util_ok(val)
        cc1, cc2 = st.columns([1, 2])
        cc1.metric("Sum", _pct(val), delta=("OK" if ok_c else "Over limit"),
                   delta_color=("normal" if ok_c else "inverse"))
        cc2.caption(f"At a common strut cot {_THETA} = {cr['cot']:.2f} "
                    f"({cr['theta_deg']:.1f} deg). TRd,max = {cr['trd_max']:.1f} kNm, "
                    f"VRd,max = {cr['vrd_max']:.1f} kN.")
        st.plotly_chart(viz.vt_interaction_figure(
            cr["vrd_max"], cr["trd_max"], cr["v_ed"], cr["t_ed"]), width="stretch")
    elif cr is not None and not cr.get("valid"):
        st.warning(_no_common_angle_msg(cr))
    else:
        st.caption("The shear+torsion crushing interaction (6.29) needs shear links "
                   "(for VRd,max); enable them in the shear block.")

    tr = c.get("transverse")
    if tr is not None and not tr.get("valid"):
        st.divider()
        st.markdown("**Shared stirrup: shear + torsion transverse steel**")
        st.warning(_no_common_angle_msg(tr))
    elif tr is not None:
        st.divider()
        st.markdown("**Shared stirrup: shear + torsion transverse steel**")
        t1, t2, t3 = st.columns(3)
        t1.metric("Shear share", _pct(tr["shear_fraction"]))
        t2.metric("Torsion share", _pct(tr["torsion_fraction"]))
        t3.metric("Stirrup utilisation", _pct(tr["u_stirrup"]))
        ok_t = tr["ok"]
        g1, g2 = st.columns(2)
        g1.metric("Crushing utilisation", _pct(tr["u_crush"]))
        g2.metric(f"Governing ({tr['governs']})", _pct(tr["governing"]),
                  delta=("OK" if ok_t else "Over limit"),
                  delta_color=("normal" if ok_t else "inverse"))
        if tr["shear_credited"]:
            st.caption(f"The concrete alone carries the shear (VEd = {tr['v_ed']:.1f} "
                       f"kN <= VRd,c = {tr['vrd_c']:.1f} kN, 6.2.1), so the shear "
                       "takes NO stirrup -- the whole closed stirrup serves torsion.")
        else:
            st.caption(f"VEd > VRd,c, so the stirrup carries both: shear and torsion "
                       "demands add on the shared closed stirrup.")
        st.caption(f"At the member strut angle cot {_THETA} = {tr['cot']:.2f} "
                   f"({tr['theta_deg']:.1f} deg) -- the ONE angle shared by every "
                   "shear and torsion check (6.3.2(2)), selected to minimise the "
                   "governing utilisation.")

    st.divider()
    st.markdown("**Longitudinal reinforcement: combined M + V + T tension chord**")
    lg = c.get("longitudinal")
    if lg is not None and lg["valid"]:
        ax_lbl = lg["axis"]
        face_lbl = viz.tension_face_label(lg.get("tension_low", True))
        biaxial = lg.get("biaxial", False)
        ok_l = lg["ok"]
        g1, g2, g3 = st.columns(3)
        g1.metric(f"MEd (about {ax_lbl})", f"{lg['m_ed']:.1f} kNm")
        g2.metric("MEd,total", f"{lg['m_total']:.1f} kNm",
                  help="bending + shear shift + torsion, as an equivalent moment "
                       "on the tension chord")
        if biaxial:
            # Under biaxial bending the off-axis chord may govern (not checked here),
            # so show the number but withhold the reassuring OK/Over-limit verdict.
            g3.metric("MEd,total/MRd", _pct(lg["util"]),
                      help="uniaxial (shear-plane) chord only -- see the warning below")
        else:
            g3.metric("MEd,total/MRd", _pct(lg["util"]),
                      delta=("OK" if ok_l else "Over limit"),
                      delta_color=("normal" if ok_l else "inverse"))
        st.caption(
            f"Tension chord = the shear tension face ({face_lbl}) about the "
            f"{ax_lbl}-axis; $M_{{Ed}}$ and $M_{{Rd}}$ are taken on that face. "
            r"$M_{Ed,total} = M_{Ed} + \Delta F_{td}\,z + F_{td,T}\,z/2 = "
            f"{lg['m_ed']:.1f} + {lg['mv']:.1f} + {lg['mt']:.1f} = {lg['m_total']:.1f}$ "
            f"kNm, vs $M_{{Rd}} = {lg['m_rd']:.1f}$ kNm (pure bending about {ax_lbl} at "
            r"the applied N). Shear shift $\Delta F_{td} = 0.5 V_{Ed}\cot\theta = "
            f"{lg['ftd_v']:.1f}$ kN (6.18); torsion "
            r"$F_{td,T} = T_{Ed}\,u_k\cot\theta / (2 A_k) = "
            f"{lg['ftd_t']:.1f}$ kN, distributed round the perimeter so half acts on "
            f"this chord (6.28); $z = {lg['z']:.3f}$ m."
            + " " + viz.chord_angle_note(lg.get("theta_mode")))
        if lg["capped"]:
            st.caption("The shear shift is capped so bending + shear does not exceed "
                       "MRd (6.2.3(7): the added tension need not exceed the "
                       "peak-moment tension; a section tool has no beam peak, so MRd "
                       "is used as that cap).")
        if biaxial:
            st.warning(
                f"Biaxial bending: a moment about the OTHER axis is acting "
                f"({_pct(lg['off_util'])} of that axis' capacity). This uniaxial chord "
                "check only inspects the shear-plane chord, so the off-axis chord -- "
                "its full bending tension plus its share of the distributed torsion "
                "steel -- may govern and is NOT evaluated here. Rely on the "
                + chr(0x03A3) + "(SEd/SRd) check above, which uses the full biaxial "
                "bending utilisation.")
        else:
            st.caption("Uniaxial refinement in the shear plane; the DK NA "
                       + chr(0x03A3) + "(SEd/SRd) sum above uses the full biaxial "
                       "bending utilisation and remains the primary combined check.")
    else:
        st.caption(f"Torsion needs {chr(0x03A3)}Asl = {c['asl_torsion']:.0f} mm2 "
                   "distributed round the tube perimeter (6.28); the shear adds "
                   f"{_DELTA}Ftd = {c['delta_ftd']:.1f} kN on the tension chord (6.18). "
                   "Both are in ADDITION to the bending reinforcement. Enable shear "
                   "links for the full longitudinal-steel utilisation check.")


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
inp["label_scale"] = _seeded_number(
    lc1, "Label size", 0.5, 3.0, 1.0, 0.1, "label_scale",
    help="Scales the corner / bar / tendon number labels on the section "
         "drawings.")
inp["label_min_gap"] = _seeded_number(
    lc2, "Label spacing (hide threshold)", 0.0, 0.5, 0.04, 0.01, "label_min_gap",
    help="Labels closer together than this fraction of the section size are "
         "hidden to avoid overlap. Lower shows more (0 shows every label); "
         "raise it for dense outlines like a circular section.")

# Migrate a renamed view label from an older session BEFORE the selectbox renders: a
# keyed selectbox otherwise keeps returning the stale string, which the dispatch no
# longer recognises, so the combined view silently falls through to the elastic one.
_VIEW_ALIASES = {"M-V-T Interaction": "M-V-T Combined"}
if st.session_state.get("view") in _VIEW_ALIASES:
    st.session_state["view"] = _VIEW_ALIASES[st.session_state["view"]]
# A pending post-Calculate view switch is applied BEFORE the selectbox renders, so
# the widget picks it up cleanly (setting a widget key after it renders is unsafe).
if "_switch_view" in st.session_state:
    st.session_state["view"] = st.session_state.pop("_switch_view")
c_view, c_calc = st.columns([3, 1])
view = c_view.selectbox("View", VIEWS, key="view",
                        help="What to show in the main area. Section and "
                             "Stress-Strain diagrams update live; the result "
                             "views need a Calculate.")
# Nudge the button down so it lines up with the selectbox input.
c_calc.markdown("<div style='height:1.7em'></div>", unsafe_allow_html=True)
calc = c_calc.button("Calculate", type="primary", key="calculate",
                     width="stretch",
                     help="Run the selected analysis for the current inputs.")

if calc:
    # Reuse a previously computed half whose split signature is unchanged, so a Both
    # run that only touched the elastic (or only the plastic) inputs recomputes just
    # the affected analysis instead of both.
    prev = st.session_state.get("results") or {}
    reuse_plastic = (prev.get("plastic")
                     if st.session_state.get("result_plastic_sig") == inp["plastic_sig"]
                     else None)
    reuse_elastic = (prev.get("elastic")
                     if st.session_state.get("result_elastic_sig") == inp["elastic_sig"]
                     else None)
    st.session_state["results"] = run_analysis(
        inp, reuse_plastic=reuse_plastic, reuse_elastic=reuse_elastic)
    st.session_state["result_sig"] = inp["signature"]
    st.session_state["result_plastic_sig"] = inp["plastic_sig"]
    st.session_state["result_elastic_sig"] = inp["elastic_sig"]
    # Re-default the Plastic view's neutral-axis state to this result's governing
    # angle (the sticky selectbox key would otherwise keep the previously shown
    # rotation, e.g. 90 deg, after the load -- and its governing angle -- changed).
    # The user can still pick another rotation until the next Calculate.
    st.session_state.pop("pl_state", None)
    # If the user calculated while on a live input view, take them to the natural
    # result view so they see the outcome (queue it; applied before the selectbox).
    # Only when a result was actually produced -- an invalid section returns {} and
    # must NOT navigate the user away to an empty result page.
    if view in ("Section", "Stress-Strain diagrams") and st.session_state["results"]:
        st.session_state["_switch_view"] = ("Plastic Results"
                                            if inp["mode"] in ("Plastic", "Both")
                                            else "Elastic Results")
        st.rerun()

_generate_report(inp)   # builds the PDF when the Report panel's Generate was pressed

results = st.session_state.get("results")
# An invalid section (a void that disconnects the concrete, steel outside the outline)
# makes run_analysis return {} -- falsy but not None. Treat that like no result so the
# badge does not read green "up to date" for a Calculate that produced nothing.
stale = bool(results) and st.session_state.get("result_sig") != inp["signature"]
# Result freshness, shown under the Calculate button on EVERY view (not just the
# result views) so the user always knows whether the results reflect the inputs.
if not results:
    c_calc.caption("Not calculated yet")
elif stale:
    c_calc.caption(":orange[Inputs changed -- recalculate]")
else:
    c_calc.caption(":green[Results up to date]")
# On a result view, keep the prominent in-view banner as well.
if stale and view in _RESULT_VIEWS:
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
elif view == "N-M Interaction":
    interaction_view(inp, results)
elif view == "Shear":
    shear_view(inp, results)
elif view == "Torsion":
    torsion_view(inp, results)
elif view == "M-V-T Combined":
    combined_view(inp, results)
else:
    elastic_view(inp, results)
