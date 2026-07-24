"""Plotly figures for the Sector UI: the section drawing and the N-M diagram."""

from __future__ import annotations

from html import escape as _html_escape
import math

import plotly.graph_objects as go
import plotly.io as pio

from sector import geometry


def pct(x, nd=1):
    """A utilisation fraction as a percentage string, ``inf`` when unbounded/undefined.

    Shared by the Streamlit views and the PDF report so the same utilisation never
    formats differently on screen and in the document. ``nd`` is the decimal count
    (the sub-tube table prints whole percent, most checks one decimal).
    """
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "inf"
    return f"{x * 100:.{nd}f} %"


def util_ok(util, tol=0.0):
    """Whether a utilisation passes (<= 1). Non-finite or ``None`` is a fail.

    The single source of the pass/fail threshold so the on-screen OK/Over-limit
    badge and the report OK/EXCEEDED verdict can never diverge. ``tol`` allows the
    tiny float slack (1e-9) some call sites use.
    """
    return util is not None and math.isfinite(util) and util <= 1.0 + tol


def tension_face_label(tension_low, axis=None):
    """The shear/chord tension face as a display label (shared by views + report)."""
    if axis == "x":
        return "bottom (-y)" if tension_low else "top (+y)"
    if axis == "y":
        return "left (-x)" if tension_low else "right (+x)"
    return "bottom / left" if tension_low else "top / right"


def directional_face_label(component, face):
    """Physical label for a Vx/Vy negative- or positive-coordinate face."""
    token = str(face or "").casefold()
    if token not in {"negative", "positive"}:
        return "-"
    axis = "y" if str(component).casefold() == "vx" else "x"
    return tension_face_label(token == "negative", axis)


def chord_angle_note(theta_mode):
    """One shared sentence explaining how the M+V+T chord's strut angle was chosen.

    Reused verbatim by the Shear/Combined views and the PDF report so the on-screen
    caption and the generated document never diverge. Pure ASCII (no glyphs/entities),
    so it drops straight into both the Streamlit captions and the reportlab notes.

    ``theta_mode`` is one of ``utilisation`` (a live load drove the minimax choice),
    ``disjoint`` (shear and torsion are both live but their cot bands do not overlap,
    so no single angle is admissible) or ``resistance`` (no live transverse load, so
    the shear-shift and torsion terms are zero and nothing drives the angle).
    """
    if theta_mode == "utilisation":
        return ("Both contributions are at the ONE member strut angle shared by the "
                "shear and torsion checks (6.3.2(2)), selected to minimise the "
                "governing utilisation.")
    if theta_mode == "disjoint":
        return ("The shear and torsion strut-angle bands do not overlap, so no single "
                "angle is admissible; each term is at its own action's "
                "resistance-optimum angle.")
    return ("No shear or torsion is acting, so there is no strut-angle objective; the "
            "shear-shift and torsion terms are zero and the angle is each action's "
            "resistance-optimum.")


def elastic_strain_figure(corners, elements, stress_plane, *, ec_mpa,
                          title="SLS strain profile"):
    """Plot the section strain plane along its steepest gradient.

    The ordinate is projected section depth from the most compressed face. The
    concrete line comes from the cracked elastic plane; explicitly typed bar and
    tendon markers use their reported total elastic strains.
    """
    fig = go.Figure()
    rows = list(corners or [])
    if not rows or not stress_plane or not ec_mpa:
        fig.add_annotation(text="No strain-profile data", showarrow=False)
        return fig

    _eps0, kx, ky = (float(v) for v in stress_plane)
    mag = math.hypot(kx, ky)
    gx, gy = ((kx / mag, ky / mag) if mag > 0.0 else (0.0, 1.0))
    projections = [float(r["x_mm"]) * gx + float(r["y_mm"]) * gy for r in rows]
    s_min = min(projections)
    corner_depth = [s - s_min for s in projections]
    corner_strain = [float(r["strain_permille"]) for r in rows]
    order = sorted(range(len(rows)), key=lambda i: corner_depth[i])
    fig.add_trace(go.Scatter(
        x=[corner_strain[order[0]], corner_strain[order[-1]]],
        y=[corner_depth[order[0]], corner_depth[order[-1]]],
        mode="lines",
        name="Concrete strain plane",
        line=dict(color="#334155", width=3),
        hovertemplate="strain %{x:.4f} permille<br>depth %{y:.1f} mm<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=corner_strain,
        y=corner_depth,
        mode="markers",
        name="Concrete corners",
        marker=dict(color="#64748B", size=7, symbol="square-open"),
        text=[f"point {r['point_no']} ({r['ring']})" for r in rows],
        hovertemplate="%{text}<br>strain %{x:.4f} permille"
                      "<br>depth %{y:.1f} mm<extra></extra>",
    ))

    for kind, symbol, colour in (
        ("Bar", "circle", "#0072B2"),
        ("Tendon", "diamond", "#CC79A7"),
    ):
        typed = [r for r in (elements or []) if r.get("element_type") == kind]
        if not typed:
            continue
        depth = [
            float(r["x_mm"]) * gx + float(r["y_mm"]) * gy - s_min
            for r in typed
        ]
        fig.add_trace(go.Scatter(
            x=[float(r["strain_permille"]) for r in typed],
            y=depth,
            mode="markers",
            name=kind + "s",
            marker=dict(color=colour, size=9, symbol=symbol,
                        line=dict(color="#111827", width=0.8)),
            text=[r["element_id"] for r in typed],
            customdata=[[r["total_mpa"]] for r in typed],
            hovertemplate="%{text}<br>strain %{x:.4f} permille"
                          "<br>stress %{customdata[0]:.3f} MPa"
                          "<br>depth %{y:.1f} mm<extra></extra>",
        ))

    fig.add_vline(x=0.0, line_dash="dash", line_color="#111827", line_width=1)
    fig.update_layout(
        title=title,
        xaxis_title="Strain epsilon (permille, tension +)",
        yaxis_title="Projected depth from compression face (mm)",
        yaxis=dict(autorange="reversed"),
        template="plotly_white",
        margin=dict(l=55, r=20, t=55, b=50),
        legend=dict(orientation="h", yanchor="bottom", y=1.01,
                    xanchor="left", x=0.0),
        height=480,
    )
    return fig


def chord_mrd_label(axis, m_off, conditional):
    """One shared parenthetical describing how a chord's MRd was computed.

    Reused verbatim by the Shear/Combined views and the PDF report (pure ASCII).
    ``conditional`` True means MRd is the M-M envelope point that also carries
    the coexisting off-axis moment ``m_off`` (kNm, signed, plastic convention);
    False means the conditional solve failed and MRd fell back to the legacy
    pure-axis capacity, which can overstate the chord capacity under biaxial
    bending -- the caller then shows the biaxial warning.
    """
    off = "My" if axis == "x" else "Mx"
    if conditional and abs(m_off) > 1e-9:
        return (f"(capacity about {axis} at the applied N, conditional on the "
                f"coexisting {off} = {m_off:.1f} kNm -- the M-M envelope point "
                "carrying both moments at once)")
    if conditional:
        return f"(bending about {axis} at the applied N)"
    return (f"(pure-axis bending about {axis} at the applied N -- the conditional "
            "biaxial solve did not converge, so this fallback can overstate the "
            "chord capacity)")


# --- House palette, grouped by role -------------------------------------------
# Tension and compression use the colour-blind-safe blue / vermillion pair from
# the Okabe-Ito palette. Section markers also use a plain / x pattern, so sign is
# never communicated by colour alone.
# Structure
CONCRETE_FILL = "rgba(120,130,140,0.18)"
CONCRETE_LINE = "#5b6770"
HOLE_FILL = "white"                         # voids punched from the outline
# Reinforcement / strain state
BAR_TENSION = "#0072B2"                      # blue; plain marker
BAR_COMPRESSION = "#D55E00"                  # vermillion; x-pattern marker
BAR_NEUTRAL = "#534ab7"                      # purple (unstressed / plane marker)
TENDON = "#0b7285"                           # teal
COMP_ZONE_FILL = "rgba(213,94,0,0.22)"       # concrete compression zone
TENS_ZONE_FILL = "rgba(0,114,178,0.12)"      # tension side (no concrete stress)
NA_LINE = "#E69F00"                          # neutral axis (amber)
# Material stress-strain curves
CURVE_CHAR = "#534ab7"                        # characteristic curve + its input markers
CURVE_DESIGN = "#9aa3ab"                      # partial-factored design curve (grey reference)
# Results (interaction envelopes / schematics)
ENVELOPE = "#534ab7"                          # capacity envelope / limit line (purple)
ENVELOPE_FILL = "rgba(83,74,183,0.08)"        # shaded safe region under the envelope
LOAD_POINT = "#CC79A7"                        # applied-load marker (magenta)
LINK_LINE = "#56B4E9"                         # shear-link ties in the truss schematic
# Annotation
GUIDE_LINE = "#b8bdc4"                        # dotted projection guides
SCHEMATIC_INK = "#2c2c2a"                     # strong schematic lines + labels
SCHEMATIC_FILL = "rgba(120,130,140,0.10)"    # neutral schematic body fill

# One shared layout template, so every figure matches (and matches the PDF report
# typography). Registered as "sector" and layered on plotly_white; each figure uses
# ``template=_TEMPLATE`` and only overrides what is genuinely figure-specific
# (margins, axis titles, legend position).
_FONT_FAMILY = "DejaVu Sans, Arial, sans-serif"
_GRID_COLOR = "#e6e8eb"
_ZERO_COLOR = "#c8ccd0"
pio.templates["sector"] = go.layout.Template(layout=dict(
    font=dict(family=_FONT_FAMILY, size=12, color="#2c2c2a"),
    title=dict(font=dict(size=14)),
    legend=dict(font=dict(size=11)),
    xaxis=dict(gridcolor=_GRID_COLOR, zerolinecolor=_ZERO_COLOR),
    yaxis=dict(gridcolor=_GRID_COLOR, zerolinecolor=_ZERO_COLOR),
))
_TEMPLATE = "plotly_white+sector"

# Greek glyphs are written as ASCII escapes so the source stays ASCII (these are
# Basic-Multilingual-Plane code points, so they never form surrogate pairs).
_EPS = chr(0x3B5)       # epsilon
_SIGMA = chr(0x3C3)     # sigma
_DELTA = chr(0x394)     # uppercase delta
_PERMILLE = chr(0x2030)  # per-mille sign
_FLOAT_MAX = float.fromhex("0x1.fffffffffffffp+1023")
_FLOAT_MIN_POSITIVE = float.fromhex("0x0.0000000000001p-1022")

_MID = chr(0x00B7)  # middle dot, for products like k*fytk (BMP, surrogate-safe)

# Map a material's ASCII marker key to its display symbol (subscripts via <sub>).
# The keys are the *input* parameters, so editing any of them moves a labelled
# point on the diagram. Derived/design quantities (f1, f2, fyd, fud) are not shown.
_MARKER_LABELS = {
    "fcd": "f<sub>cd</sub>",
    "fck": "f<sub>ck</sub>",
    "eps_c2": _EPS + "<sub>c2</sub>",
    "eps_cu2": _EPS + "<sub>cu2</sub>",
    # mild steel inputs
    "fytk": "f<sub>ytk</sub>",
    "fyck": "f<sub>yck</sub>",
    "futk": "f<sub>utk</sub>",
    "k_fytk": "k" + _MID + "f<sub>ytk</sub>",
    "k_fyck": "k" + _MID + "f<sub>yck</sub>",
    "eut": _EPS + "<sub>ut</sub>",
    "ey0t": _EPS + "<sub>0t</sub>",
    "ey0c": _EPS + "<sub>0c</sub>",
    # prestressing-steel inputs
    "fp01k": "f<sub>p0.1k</sub>",
    "fpk": "f<sub>pk</sub>",
    "k_fp01k": "k" + _MID + "f<sub>p0.1k</sub>",
    "IS": "I<sub>S</sub>",
}


def _linspace(a, b, n):
    if n < 2:
        return [a]
    step = (b - a) / (n - 1)
    return [a + step * i for i in range(n)]


def _merge_labels(keys):
    """Join the symbols for values that share an axis position (e.g. f_yd/f_ud)."""
    seen = []
    for k in keys:
        sym = _MARKER_LABELS.get(k, k)
        if sym not in seen:
            seen.append(sym)
    return "/".join(seen)


def _spread(values, min_gap):
    """Push label anchor positions apart to at least ``min_gap``, keeping order.

    ``values`` are the true positions (sorted ascending); returns adjusted label
    positions so adjacent labels do not collide. The guide line still marks the
    true value, so a small label offset stays unambiguous.
    """
    out = list(values)
    for i in range(1, len(out)):
        if out[i] - out[i - 1] < min_gap:
            out[i] = out[i - 1] + min_gap
    shift = (values[-1] - out[-1]) / 2.0 if out else 0.0  # re-centre the stack
    return [v + shift for v in out]


def _grouped(pts, axis):
    """Group points by axis position -> ordered list of (value, [keys])."""
    groups = {}
    for s, sig, ek, sk in pts:
        value, key = (round(s * 1000.0, 2), ek) if axis == "x" else (round(sig, 1), sk)
        if key is not None:
            groups.setdefault(value, []).append(key)
    return sorted(groups.items())


def _apply_markers(fig, points, eps_min, eps_max, ymin, ymax):
    """Annotate a material's points of interest, journal-style.

    ``points`` are ``(strain, stress, eps_key, sigma_key)`` from
    ``material.diagram_markers``. Each in-view point gets a dot on the curve and
    thin projection guides to the axes; the strain symbols sit on the strain
    axis and the stress symbols on the stress axis, so labels never touch the
    curve. Symbols sharing an axis position are merged (e.g. ``f_yd/f_ud``), and
    near-coincident labels are nudged apart so they never overlap one another.
    """
    pts = [(s, sig, ek, sk) for (s, sig, ek, sk) in points
           if eps_min <= s <= eps_max]
    if not pts:
        return

    fig.add_trace(go.Scatter(
        x=[s * 1000.0 for s, _, _, _ in pts], y=[sig for _, sig, _, _ in pts],
        mode="markers", marker=dict(size=8, color=CURVE_CHAR,
                                    line=dict(color="white", width=1.5)),
        hoverinfo="skip", showlegend=False))

    # Strain symbols above the plot (the numeric strain ticks stay on the bottom
    # axis, so the symbols and the values do not collide).
    x_groups = _grouped(pts, "x")
    x_span = (eps_max - eps_min) * 1000.0
    x_lab = _spread([v for v, _ in x_groups], x_span * 0.11)
    for (x0, keys), xl in zip(x_groups, x_lab):
        fig.add_vline(x=x0, line_width=0.8, line_dash="dot", line_color=GUIDE_LINE)
        fig.add_annotation(x=xl, xref="x", y=1.0, yref="paper", yshift=6,
                           yanchor="bottom", showarrow=False, text=_merge_labels(keys),
                           font=dict(size=12, color=CURVE_CHAR))

    # Stress symbols on the right edge (the numeric stress ticks stay on the
    # left axis), nudged apart so they never overlap one another.
    y_groups = _grouped(pts, "y")
    y_span = (ymax - ymin) or 1.0
    y_lab = _spread([v for v, _ in y_groups], y_span * 0.08)
    for (y0, keys), yl in zip(y_groups, y_lab):
        fig.add_hline(y=y0, line_width=0.8, line_dash="dot", line_color=GUIDE_LINE)
        fig.add_annotation(x=1.0, xref="paper", xshift=6, y=yl, yref="y",
                           xanchor="left", showarrow=False, text=_merge_labels(keys),
                           font=dict(size=12, color=CURVE_CHAR))


def _slope_label(fig, material):
    """Label the elastic-branch slope with the input modulus (steel only).

    Shows the characteristic modulus the user entered -- ``Es`` for mild steel,
    ``Ep`` for prestressing steel -- not the partial-factored design slope.
    """
    es = getattr(material, "Es", None)
    if not es:
        return
    pos = [(s, sig) for s, sig, _, _ in material.diagram_markers(design=False)
           if s > 0.0]
    if not pos:
        return
    e_yield = min(s for s, _ in pos)
    e_mid = 0.45 * e_yield
    sym = "E<sub>p</sub>" if type(material).__name__ == "Prestress" else "E<sub>s</sub>"
    fig.add_annotation(
        x=e_mid * 1000.0, y=es * e_mid, ax=-36, ay=-22, showarrow=True,
        arrowhead=0, arrowwidth=0.8, arrowcolor=GUIDE_LINE,
        text="%s = %.0f GPa" % (sym, es / 1000.0),
        font=dict(size=11, color=CURVE_CHAR))


_ORIGIN_EPS = 1.0e-4   # strain within this of zero is the origin, not a cutoff


def _trace_xy(fn, grid, peak):
    """Sample a material law, inserting a true vertical at each hard cutoff.

    A failure (concrete crushing at ``eps_cu2``, steel/tendon rupture at
    ``eut``) is an instantaneous drop to zero stress, but it falls between two
    samples and would otherwise be drawn as a slanted line across the gap. Where
    consecutive samples jump to/from zero, bisect to the exact cutoff strain and
    emit two points at that strain so the drop renders vertical. ``peak`` guards
    against treating the continuous pass through zero at the origin as a cutoff.
    """
    xs, ys = [], []
    pe = ps = None
    tol = 0.02 * peak
    for e in grid:
        s = fn(e)
        if ps is not None:
            z0, z1 = abs(ps) < 1e-9, abs(s) < 1e-9
            live = s if z0 else ps
            if z0 != z1 and abs(live) > tol:           # a candidate failure drop
                lo, hi = pe, e
                for _ in range(50):
                    mid = 0.5 * (lo + hi)
                    if (abs(fn(mid)) < 1e-9) == z0:
                        lo = mid
                    else:
                        hi = mid
                ec_strain = 0.5 * (lo + hi)
                # A genuine cutoff (rupture/crushing) is at a finite failure strain.
                # A one-sided law (zero in compression, elastic in tension) crosses
                # zero *at the origin*, where it is continuous -- not a drop -- so
                # the elastic branch ramps from zero rather than stepping up.
                if abs(ec_strain) > _ORIGIN_EPS:
                    ec = ec_strain * 1000.0
                    xs += [ec, ec]
                    ys += [0.0, live] if z0 else [live, 0.0]
        xs.append(e * 1000.0)
        ys.append(s)
        pe, ps = e, s
    return xs, ys


def _with_corners(grid, markers, lo, hi):
    """Add a law's corner strains to a uniform sampling grid.

    A piecewise-linear law (e.g. the elastic-then-yield steel branches) changes
    slope at its corners. On a uniform grid a corner almost never lands on a
    sample, so the single segment spanning it averages the two slopes and draws
    the kink as a shallow ramp -- looking like a spurious second yield. Injecting
    the corner strains (from ``diagram_markers``) and the origin as exact grid
    points puts a true vertex at every slope change, so each branch keeps its own
    slope right up to the corner.
    """
    pts = set(grid)
    pts.add(0.0 if lo <= 0.0 <= hi else lo)
    pts.update(m[0] for m in markers if lo <= m[0] <= hi)
    return sorted(pts)


def _curve_figure(material, eps_min, eps_max, title, n=240):
    """Stress-strain diagram of a material law over a strain range (tension +).

    The characteristic curve carries the input labels (the values the user
    enters) and is drawn solid; the partial-factored design curve is shown
    lighter for reference. Points of interest are dotted and labelled at the
    axes. Hard cutoffs (crushing/rupture) render as true verticals. The strain
    axis is in per-mille so compression (negative) and tension (positive) are
    both visible; stress in MPa.
    """
    base = _linspace(eps_min, eps_max, n)
    # The design and characteristic curves have their corners at different strains
    # (the partial factors shift the yield strain), so each gets its own grid.
    eps_d = _with_corners(base, material.diagram_markers(design=True), eps_min, eps_max)
    eps_c = _with_corners(base, material.diagram_markers(design=False), eps_min, eps_max)
    design = [material.stress(e, design=True) for e in eps_d]
    char = [material.stress(e, design=False) for e in eps_c]
    peak = max((abs(v) for v in design + char), default=0.0) or 1.0
    xd, yd = _trace_xy(lambda e: material.stress(e, design=True), eps_d, peak)
    xc, yc = _trace_xy(lambda e: material.stress(e, design=False), eps_c, peak)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=xd, y=yd, mode="lines", name="design",
                             line=dict(color=CURVE_DESIGN, width=1.5, dash="dot")))
    fig.add_trace(go.Scatter(x=xc, y=yc, mode="lines", name="characteristic",
                             line=dict(color=CURVE_CHAR, width=2.5)))
    # Markers sit on the characteristic curve and are labelled with the input
    # parameters, so editing any input visibly moves a labelled point.
    _apply_markers(fig, material.diagram_markers(design=False), eps_min, eps_max,
                   min(design + char), max(design + char))
    _slope_label(fig, material)
    fig.update_layout(
        title=dict(text=title, y=0.97),
        template=_TEMPLATE, height=340,
        margin=dict(l=58, r=54, t=44, b=96),
        xaxis=dict(title=dict(text="Strain " + _EPS + " [" + _PERMILLE + "]",
                              standoff=10),
                   zeroline=True, showgrid=True),
        yaxis=dict(title="Stress " + _SIGMA + " [MPa]",
                   zeroline=True, showgrid=True),
        legend=dict(orientation="h", yanchor="top", y=-0.34, x=0.5,
                    xanchor="center"),
    )
    return fig


def concrete_curve_figure(concrete, title="Concrete"):
    """Stress-strain diagram for a concrete law (compression is negative)."""
    # Slightly past the ultimate strain on the compression side, a little tension
    # (the default eps_cu2 = 0.0035 gives the usual -0.0042 window).
    fig = _curve_figure(concrete, -(concrete.eps_cu2 + 0.0007), 0.0006, title)
    # Label the DESIGN plateau too: f_ck is marked by the characteristic labels, but
    # with gamma_c = 1.5 the design plateau sits visibly apart and would otherwise be
    # the one unnamed line in the figure. Skip it when the curves coincide (gamma 1).
    try:
        f_cd = concrete.stress(-concrete.eps_c2, design=True)
        f_ck = concrete.stress(-concrete.eps_c2, design=False)
    except Exception:
        f_cd = f_ck = 0.0
    if f_cd and abs(f_cd - f_ck) > 0.02 * abs(f_ck or 1.0):
        fig.add_hline(y=f_cd, line_width=0.8, line_dash="dot",
                      line_color=GUIDE_LINE)
        fig.add_annotation(x=1.0, xref="paper", xshift=6, y=f_cd, yref="y",
                           xanchor="left", showarrow=False,
                           text="f<sub>cd</sub>",
                           font=dict(size=12, color=CURVE_DESIGN))
    return fig


def prestress_curve_figure(prestress, title="Prestressing steel"):
    """Stress-strain diagram for a prestressing-steel law (tension only).

    Tendons carry tension only, so the strain window starts just below zero and
    runs a little past the rupture strain (so the ultimate point shows). The
    strain axis is the *total* tendon strain -- the effective prestrain plus the
    section strain at the tendon.
    """
    top = prestress.rupture_strain
    top = top if 0.0 < top <= 0.06 else 0.035
    return _curve_figure(prestress, -0.001, top * 1.02, title)


def steel_curve_figure(steel, title="Mild steel", eps_max=0.025):
    """Stress-strain diagram for a reinforcement law (tension and compression).

    The window is scaled to the largest visible strain -- the rupture strain
    ``eut`` when it is finite and not extreme -- and is symmetric, because the
    rupture applies in both tension and compression. A no-strain-limit law (very
    large ``eut``) falls back to the default window.
    """
    top = steel.eut if 0.0 < steel.eut <= 0.1 else eps_max
    top = max(top, 0.01) * 1.06   # a little past eut so the rupture drop is visible
    return _curve_figure(steel, -top, top, title)


def _ring_xy(ring):
    if len(ring) == 0:
        return [], []
    xs = [p[0] for p in ring] + [ring[0][0]]
    ys = [p[1] for p in ring] + [ring[0][1]]
    return xs, ys


POINT_LABEL = "#2c2c2a"   # reinforcement point numbers
CORNER_LABEL = "#5b6770"  # concrete corner numbers


def _decimate(positions, min_dist):
    """Greedy indices to keep so the kept points are at least ``min_dist`` apart.

    Walks the points in order, keeping one only when it clears every already-kept
    point -- so closely spaced labels thin out (every 2nd, 3rd, ...) while
    well-spaced ones are all kept.
    """
    if min_dist <= 0.0:
        return list(range(len(positions)))
    keep, chosen = [], []
    for i, p in enumerate(positions):
        if all(math.hypot(p[0] - q[0], p[1] - q[1]) >= min_dist for q in chosen):
            keep.append(i)
            chosen.append(p)
    return keep


_LABEL_BASE_SIZE = 11.0   # default point-label font (px), scaled by label_scale


def _add_point_labels(fig, outer, holes, bars, tendons, label_scale=1.0,
                      label_min_gap=0.04, bar_ids=None, tendon_ids=None):
    """Number the reinforcement (bars then tendons, continuously) and the
    concrete corners, so the drawing cross-references the result tables.

    Reinforcement numbering matches the elastic per-bar table (tendons follow the
    bars); corner numbering matches ``Section.concrete_vertices`` order (outer
    ring then holes), which is the "corner N" reported with the peak concrete
    stress. ``label_scale`` scales the font; ``label_min_gap`` is the minimum
    label spacing as a fraction of the section size -- labels closer than that
    thin out, independently of the font size (0 keeps every label).
    """
    xs = [v[0] for v in outer] or [0.0]
    ys = [v[1] for v in outer] or [0.0]
    span = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    size = _LABEL_BASE_SIZE * label_scale
    min_dist = label_min_gap * span           # below this, labels are thinned out

    rebar = list(bars or []) + list(tendons or [])
    if rebar:
        labels = (list(bar_ids or []) + list(tendon_ids or []))
        if len(labels) != len(rebar):
            labels = [str(i + 1) for i in range(len(rebar))]
        keep = _decimate(rebar, min_dist)
        fig.add_trace(go.Scatter(
            x=[rebar[i][0] for i in keep], y=[rebar[i][1] for i in keep], mode="text",
            text=[labels[i] for i in keep], textposition="top center",
            textfont=dict(size=size, color=POINT_LABEL),
            hoverinfo="skip", showlegend=False))

    verts = [v for ring in [outer, *(holes or [])] for v in ring]
    if not verts:
        return
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)
    off = 0.05 * span * label_scale
    lx, ly, txt = [], [], []
    for i in _decimate(verts, min_dist):      # nudge each kept label outward
        v = verts[i]
        dx, dy = v[0] - cx, v[1] - cy
        d = math.hypot(dx, dy) or 1.0
        lx.append(v[0] + off * dx / d)
        ly.append(v[1] + off * dy / d)
        txt.append(str(i + 1))
    fig.add_trace(go.Scatter(
        x=lx, y=ly, mode="text", text=txt,
        textfont=dict(size=size, color=CORNER_LABEL), hoverinfo="skip",
        showlegend=False))


# The section / interaction plots put a horizontal legend below the x-axis title.
# ``legend.y`` is in paper coordinates (a fraction of the plot *area*, which grows
# with the figure height), so a constant y would sit a larger pixel distance below
# a taller plot and spill past the fixed bottom margin. Scale y inversely with the
# plot-area height so the legend keeps a constant pixel gap below the axis title
# (matching the stress-strain figure) and stays inside the margin at any height.
_LEGEND_TOP_M, _LEGEND_BOT_M = 40, 96
_LEGEND_GAP_PX = 68.0


def _legend_y(height: float) -> float:
    plot_h = max(height - _LEGEND_TOP_M - _LEGEND_BOT_M, 1.0)
    return -_LEGEND_GAP_PX / plot_h


def _point_hover(points, first_number, kind, unit, extra=None, ids=None):
    """Per-point hover strings ``'Kind N<br>x, y[<br>area][<br>extra]'`` for the
    section drawing.

    Numbering continues from ``first_number`` so it matches the drawn labels and the
    result tables (bars 1..n, tendons n+1.., concrete corners 1..). Coordinates are
    the already-scaled display values, shown in ``unit`` (0 decimals for mm, 3 for
    m). A reinforcement ``area`` (a 3rd tuple element, always in mm2) is shown when
    present; concrete corners are 2-tuples and carry none. ``extra`` is an optional
    per-point string (e.g. a stress/strain read-out) appended on its own line.
    """
    dec = 3 if unit == "m" else 0
    lines = []
    for i, p in enumerate(points):
        point_id = (str(ids[i]) if ids is not None and i < len(ids)
                    else str(first_number + i))
        s = (f"{kind} {point_id}<br>"
             f"x = {p[0]:.{dec}f} {unit}, y = {p[1]:.{dec}f} {unit}")
        if len(p) > 2 and p[2] is not None:
            s += f"<br>area = {p[2]:.0f} mm<sup>2</sup>"
        if extra is not None and i < len(extra) and extra[i]:
            s += f"<br>{extra[i]}"
        lines.append(s)
    return lines


_ARROW_UP = chr(0x2191)      # upwards arrow
_ARROW_RIGHT = chr(0x2192)   # rightwards arrow


def _direction_note(fig, lines):
    """Corner note stating the positive sign convention (with arrow glyphs).

    Pinned to the top-left of the plot area on a translucent backing, so the
    reader never has to leave the figure to know which PHYSICAL bending a
    positive axis value means. The interaction envelopes are centred, so the
    corner is reliably free under the equal-aspect autoscale.
    """
    fig.add_annotation(x=0.01, y=0.99, xref="paper", yref="paper",
                       xanchor="left", yanchor="top", showarrow=False,
                       align="left", text="<br>".join(lines),
                       font=dict(size=11, color=SCHEMATIC_INK),
                       bgcolor="rgba(255,255,255,0.75)")


def _marker_sizes(points, base, lo, hi):
    """Per-point marker sizes (px) scaled by RELATIVE bar diameter.

    Each point is ``(x, y, area)``; the marker diameter scales with ``sqrt(area)``
    (i.e. the true bar diameter) normalised by the median, so a mixed layout shows
    which bars are the big ones (an O25 next to an O16 reads ~1.6x wider). ``base``
    is the size at the median diameter; sizes are clamped to ``[lo, hi]`` so dense
    layouts stay legible and a single huge tendon cannot dwarf the drawing. A layout
    of equal areas (or missing areas) degrades to ``base`` for every point.
    """
    try:
        dias = [math.sqrt(max(float(p[2]), 0.0)) for p in points]
    except (IndexError, TypeError, ValueError):
        return base
    finite = sorted(d for d in dias if d > 0.0)
    if not finite:
        return base
    med = finite[len(finite) // 2]
    if med <= 0.0:
        return base
    return [min(max(base * (d / med), lo), hi) if d > 0.0 else base for d in dias]


def section_figure(outer, holes=None, bars=None, bar_colors=None,
                   na_line=None, title="Section", tendons=None, tendon_colors=None,
                   zones=None, show_labels=False, label_scale=1.0, label_min_gap=0.04,
                   height=440, scale=1.0, unit="m", bar_hover=None, tendon_hover=None,
                   bar_ids=None, tendon_ids=None):
    """Draw the section: concrete outline, holes, reinforcement and neutral axis.

    Reinforcement is drawn consistently across the views: bars are circles and
    tendons are diamonds, each coloured by ``bar_colors`` / ``tendon_colors``
    (e.g. by stress sign) when given, else a neutral colour. Compression-state
    markers receive an x pattern and tension-state markers remain plain, with
    explicit legend entries, so the state remains readable without colour.
    ``outer`` / ``holes`` / ``bars`` / ``na_line`` / ``zones`` are all given in
    metres; ``scale`` (and the matching axis ``unit`` label) converts them for
    display -- e.g. ``1000`` / ``"mm"`` draws the section in millimetres.
    ``show_labels`` numbers the reinforcement and concrete corners; ``label_scale``
    scales the label font and ``label_min_gap`` is the minimum label spacing
    (fraction of the section size) below which labels are thinned out -- the two
    are independent.
    """
    # Scale every geometry input once, up front, so the traces and the labels are
    # all drawn in the display units. Guard with ``is None`` rather than a truth
    # test so NumPy vertex arrays (whose truth value is ambiguous) pass through.
    outer = [] if outer is None else [(p[0] * scale, p[1] * scale) for p in outer]
    holes = [] if holes is None else [[(p[0] * scale, p[1] * scale) for p in ring] for ring in holes]
    bars = [] if bars is None else [(b[0] * scale, b[1] * scale) + tuple(b[2:]) for b in bars]
    tendons = [] if tendons is None else [(t[0] * scale, t[1] * scale) + tuple(t[2:]) for t in tendons]
    if na_line is not None:
        na_line = tuple(v * scale for v in na_line)
    zones = [] if zones is None else [([(p[0] * scale, p[1] * scale) for p in verts], color, name)
                                      for verts, color, name in zones]

    fig = go.Figure()
    xs, ys = _ring_xy(outer)
    fig.add_trace(go.Scatter(x=xs, y=ys, fill="toself", mode="lines",
                             fillcolor=CONCRETE_FILL, line=dict(color=CONCRETE_LINE),
                             hoverinfo="skip", showlegend=False))
    for verts, color, name in zones or []:
        if len(verts) >= 3:
            zx, zy = _ring_xy(verts)
            fig.add_trace(go.Scatter(x=zx, y=zy, fill="toself", mode="lines",
                                     fillcolor=color, line=dict(width=0),
                                     hoverinfo="skip", name=name))
    for hole in holes or []:
        hx, hy = _ring_xy(hole)
        fig.add_trace(go.Scatter(x=hx, y=hy, fill="toself", mode="lines",
                                 fillcolor=HOLE_FILL, line=dict(color=CONCRETE_LINE, dash="dot"),
                                 hoverinfo="skip", showlegend=False))
    # Invisible hover targets on the concrete corners (outer ring then holes, the
    # numbering used for the corner labels and the peak-stress "corner N"): the fill
    # polygons skip hover, so these markers report each corner's coordinates without
    # drawing anything over the outline.
    corner_verts = [v for ring in [outer, *(holes or [])] for v in ring]
    if corner_verts:
        fig.add_trace(go.Scatter(
            x=[v[0] for v in corner_verts], y=[v[1] for v in corner_verts],
            mode="markers", marker=dict(size=12, color="rgba(0,0,0,0)"),
            customdata=_point_hover(corner_verts, 1, "Corner", unit),
            hovertemplate="%{customdata}<extra></extra>", showlegend=False))
    if bars:
        bx = [b[0] for b in bars]
        by = [b[1] for b in bars]
        colors = bar_colors or [BAR_NEUTRAL] * len(bars)
        symbols = (["circle-x" if color == BAR_COMPRESSION else "circle"
                    for color in colors] if bar_colors else "circle")
        fig.add_trace(go.Scatter(x=bx, y=by, mode="markers", name="reinforcing bar",
                                 marker=dict(size=_marker_sizes(bars, 9.0, 6.5, 14.0),
                                             symbol=symbols, color=colors,
                                             line=dict(color="white", width=1)),
                                 customdata=_point_hover(
                                     bars, 1, "Bar", unit, bar_hover, bar_ids),
                                 hovertemplate="%{customdata}<extra></extra>",
                                 showlegend=True))
    if tendons:
        tx = [t[0] for t in tendons]
        ty = [t[1] for t in tendons]
        colors = tendon_colors or [TENDON] * len(tendons)
        symbols = (["diamond-x" if color == BAR_COMPRESSION else "diamond"
                    for color in colors] if tendon_colors else "diamond")
        fig.add_trace(go.Scatter(x=tx, y=ty, mode="markers", name="tendon",
                                 marker=dict(size=_marker_sizes(tendons, 11.0, 8.0, 16.0),
                                             symbol=symbols, color=colors,
                                             line=dict(color="white", width=1)),
                                 customdata=_point_hover(
                                     tendons, len(bars) + 1, "Tendon", unit,
                                     tendon_hover, tendon_ids),
                                 hovertemplate="%{customdata}<extra></extra>",
                                 showlegend=True))
    state_colors = list(bar_colors or []) + list(tendon_colors or [])
    if BAR_TENSION in state_colors:
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers", name="tension (+): plain marker",
            marker=dict(size=9, symbol="circle", color=BAR_TENSION,
                        line=dict(color="white", width=1)),
            hoverinfo="skip", showlegend=True,
        ))
    if BAR_COMPRESSION in state_colors:
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers", name="compression (-): x marker",
            marker=dict(size=9, symbol="circle-x", color=BAR_COMPRESSION,
                        line=dict(color="white", width=1)),
            hoverinfo="skip", showlegend=True,
        ))
    if na_line:
        x0, y0, x1, y1 = na_line
        fig.add_trace(go.Scatter(x=[x0, x1], y=[y0, y1], mode="lines",
                                 line=dict(color=NA_LINE, width=2, dash="dash"),
                                 name="neutral axis"))
    if show_labels:
        _add_point_labels(
            fig, outer, holes, bars, tendons, label_scale, label_min_gap,
            bar_ids, tendon_ids,
        )
    fig.update_layout(
        title=title, template=_TEMPLATE, height=height,
        margin=dict(l=10, r=10, t=_LEGEND_TOP_M, b=_LEGEND_BOT_M),
        xaxis=dict(title=dict(text=f"x ({unit})", standoff=10), zeroline=True),
        yaxis=dict(title=f"y ({unit})", scaleanchor="x", scaleratio=1, zeroline=True),
        showlegend=bool(na_line) or bool(zones) or bool(bars) or bool(tendons),
        # Below the plot and below the x-axis title, clear of the plotly modebar
        # (which the above-the-plot position collided with). A height-scaled y keeps
        # a constant gap below the title without spilling past the bottom margin.
        legend=dict(orientation="h", yanchor="top", y=_legend_y(height), x=0.5,
                    xanchor="center"),
    )
    return fig


def _fatigue_value(record, name, default=None):
    if isinstance(record, dict):
        return record.get(name, default)
    return getattr(record, name, default)


def _fatigue_items(record, name):
    return tuple(_fatigue_value(record, name, ()) or ())


def _fatigue_utilisation_scale(values):
    numeric = []
    for value in values:
        try:
            numeric.append(float(value))
        except (TypeError, ValueError):
            continue
    finite = [max(value, 0.0) for value in numeric if math.isfinite(value)]
    unbounded = any(value > 0.0 and not math.isfinite(value) for value in numeric)
    upper = max([1.0, *finite])
    if unbounded:
        upper = max(upper, 1.10)
    # Cividis is perceptually ordered and remains legible for common colour-vision
    # deficiencies.  The explicit 1.00 tick and x-patterns carry the limit.
    ticks = [0.0, 0.5, 1.0]
    if upper > 1.0 + 1.0e-9:
        ticks.append(upper)
    return upper, sorted(set(ticks))


def _fatigue_plot_utilisation(value, upper):
    """Return a finite colour value while preserving failure through symbols."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return upper if number > 0.0 else 0.0
    return min(max(number, 0.0), upper)


def _fatigue_hover_number(value, format_spec=".3g"):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    return format(number, format_spec) if math.isfinite(number) else "inf"


def _fatigue_limit_exceeded(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return number > 1.0 or (number > 0.0 and not math.isfinite(number))


def _fatigue_text(value):
    """Escape user-controlled text before Plotly interprets its HTML subset."""

    return _html_escape(str(value), quote=True)


def fatigue_utilisation_map_figure(
    outer,
    holes,
    bar_elements,
    tendon_elements,
    spectrum,
    *,
    title=None,
):
    """Map steel and concrete fatigue utilisation on the section.

    Geometry is supplied in the application's native convention: concrete rings
    in metres and element records in millimetres. Stable element/fibre labels and
    over-limit x-patterns make the figure interpretable without colour.
    """

    outer = [] if outer is None else list(outer)
    holes = [] if holes is None else list(holes)
    bar_elements = list(bar_elements or [])
    tendon_elements = list(tendon_elements or [])
    reinforcement = {
        str(_fatigue_value(result, "element_id", "")): result
        for result in _fatigue_items(spectrum, "reinforcement")
    }
    concrete = list(_fatigue_items(spectrum, "concrete"))
    utilisation_values = [
        _fatigue_value(result, "utilisation")
        for result in [*reinforcement.values(), *concrete]
    ]
    search = _fatigue_value(spectrum, "concrete_search")
    # The certified upper damage is a bound over a search region, not a sampled
    # point represented by the colour axis. It has a dedicated red indicator below;
    # including it here can collapse every actual point into the bottom of the scale.
    cmax, tickvals = _fatigue_utilisation_scale(utilisation_values)

    fig = go.Figure()
    ox, oy = _ring_xy([
        (float(point[0]) * 1000.0, float(point[1]) * 1000.0)
        for point in outer
    ])
    fig.add_trace(go.Scatter(
        x=ox,
        y=oy,
        fill="toself",
        mode="lines",
        fillcolor=CONCRETE_FILL,
        line=dict(color=CONCRETE_LINE, width=1.5),
        hoverinfo="skip",
        showlegend=False,
    ))
    for ring in holes:
        hx, hy = _ring_xy([
            (float(point[0]) * 1000.0, float(point[1]) * 1000.0)
            for point in ring
        ])
        fig.add_trace(go.Scatter(
            x=hx,
            y=hy,
            fill="toself",
            mode="lines",
            fillcolor=HOLE_FILL,
            line=dict(color=CONCRETE_LINE, width=1.0, dash="dot"),
            hoverinfo="skip",
            showlegend=False,
        ))

    search_x = (
        float(_fatigue_value(search, "x_m")) * 1000.0
        if search is not None else None
    )
    search_y = (
        float(_fatigue_value(search, "y_m")) * 1000.0
        if search is not None else None
    )
    search_upper = (
        float(_fatigue_value(search, "upper_damage"))
        if search is not None else None
    )
    search_converged = (
        bool(_fatigue_value(search, "converged", False))
        if search is not None else True
    )
    search_bound_failed = bool(
        search_upper is not None
        and (not math.isfinite(search_upper) or search_upper > 1.0)
    )

    if concrete:
        concrete_x = [
            float(_fatigue_value(result, "x_m")) * 1000.0
            for result in concrete
        ]
        concrete_y = [
            float(_fatigue_value(result, "y_m")) * 1000.0
            for result in concrete
        ]
        concrete_raw_util = [
            float(_fatigue_value(result, "utilisation"))
            for result in concrete
        ]
        concrete_util = [
            _fatigue_plot_utilisation(value, cmax)
            for value in concrete_raw_util
        ]
        symbols = []
        labels = []
        hover = []
        for result, x_mm, y_mm, raw_util in zip(
            concrete, concrete_x, concrete_y, concrete_raw_util
        ):
            is_search = bool(
                search is not None
                and math.isclose(x_mm, search_x, abs_tol=1.0e-9)
                and math.isclose(y_mm, search_y, abs_tol=1.0e-9)
            )
            exceeded = _fatigue_limit_exceeded(raw_util)
            if is_search:
                symbols.append("star-square" if exceeded else "star")
            else:
                symbols.append("square-x" if exceeded else "square")
            fibre = _fatigue_text(_fatigue_value(result, "fibre_index", "-"))
            labels.append(f"C{fibre}")
            hover.append(
                f"Concrete fibre {fibre}"
                + (" (adaptive search)" if is_search else "")
                + f"<br>x = {x_mm:.1f} mm, y = {y_mm:.1f} mm"
                + "<br>utilisation = "
                + _fatigue_hover_number(raw_util, ".3f")
                + f"<br>damage = "
                f"{_fatigue_hover_number(_fatigue_value(result, 'damage', 0.0))}"
                + f"<br>stress utilisation = "
                f"{_fatigue_hover_number(
                    _fatigue_value(result, 'stress_utilisation', 0.0),
                    '.3f',
                )}"
                + (
                    "<br>search upper damage = "
                    f"{_fatigue_hover_number(search_upper, '.3f')}"
                    + (
                        "<br>search convergence = certified"
                        if search_converged
                        else "<br>search convergence = not converged"
                    )
                    if is_search else ""
                )
            )
        fig.add_trace(go.Scatter(
            x=concrete_x,
            y=concrete_y,
            mode="markers+text",
            name="concrete fibres",
            marker=dict(
                size=10,
                symbol=symbols,
                color=concrete_util,
                coloraxis="coloraxis",
                line=dict(color="#111827", width=0.8),
            ),
            text=labels,
            textposition="top center",
            textfont=dict(size=9, color=SCHEMATIC_INK),
            customdata=hover,
            hovertemplate="%{customdata}<extra></extra>",
        ))

    def add_elements(records, kind, base_symbol, size):
        selected = [
            (record, reinforcement.get(str(record.get("id") or "")))
            for record in records
        ]
        selected = [
            (record, result)
            for record, result in selected
            if result is not None
        ]
        if not selected:
            return
        utils = [
            float(_fatigue_value(result, "utilisation"))
            for _record, result in selected
        ]
        plot_utils = [
            _fatigue_plot_utilisation(value, cmax)
            for value in utils
        ]
        symbols = [
            (
                base_symbol + "-x"
                if _fatigue_limit_exceeded(util)
                else base_symbol
            )
            for util in utils
        ]
        labels = [
            _fatigue_text(record.get("id") or "-")
            for record, _ in selected
        ]
        hover = []
        for (record, result), util in zip(selected, utils):
            damage = float(_fatigue_value(result, "damage_utilisation", 0.0))
            stress = float(_fatigue_value(result, "yield_utilisation", 0.0))
            element_id = _fatigue_text(record.get("id", "-"))
            hover.append(
                f"{kind} {element_id}"
                f"<br>x = {float(record.get('x_mm', 0.0)):.1f} mm, "
                f"y = {float(record.get('y_mm', 0.0)):.1f} mm"
                "<br>utilisation = "
                + _fatigue_hover_number(util, ".3f")
                + "<br>Miner damage = "
                + _fatigue_hover_number(damage)
                + "<br>yield/proof utilisation = "
                + _fatigue_hover_number(stress, ".3f")
            )
        fig.add_trace(go.Scatter(
            x=[float(record.get("x_mm", 0.0)) for record, _ in selected],
            y=[float(record.get("y_mm", 0.0)) for record, _ in selected],
            mode="markers+text",
            name=kind.lower(),
            marker=dict(
                size=size,
                symbol=symbols,
                color=plot_utils,
                coloraxis="coloraxis",
                line=dict(color="#111827", width=1.0),
            ),
            text=labels,
            textposition="top center",
            textfont=dict(size=10, color=SCHEMATIC_INK),
            customdata=hover,
            hovertemplate="%{customdata}<extra></extra>",
        ))

    add_elements(bar_elements, "Reinforcing bar", "circle", 12)
    add_elements(tendon_elements, "Tendon", "diamond", 13)
    if search_bound_failed and search_x is not None and search_y is not None:
        fig.add_trace(go.Scatter(
            x=[search_x],
            y=[search_y],
            mode="markers",
            name="certified search bound > 1.00",
            marker=dict(
                size=19,
                symbol="x",
                color="#9B1C1C",
                line=dict(color="#FFFFFF", width=1.0),
            ),
            customdata=[(
                "Certified upper damage = "
                f"{_fatigue_hover_number(search_upper, '.3f')}"
                "<br>Marker is at the worst evaluated fibre; the conservative "
                "bound applies to the complete concrete search region."
            )],
            hovertemplate="%{customdata}<extra></extra>",
        ))
    if any(
        _fatigue_limit_exceeded(value)
        for value in utilisation_values
    ):
        fig.add_trace(go.Scatter(
            x=[None],
            y=[None],
            mode="markers",
            name="limit exceeded (x marker)",
            marker=dict(
                size=10,
                symbol="circle-x",
                color="#FFFFFF",
                line=dict(color="#111827", width=1.0),
            ),
            hoverinfo="skip",
        ))

    spectrum_name = _fatigue_text(
        _fatigue_value(spectrum, "spectrum_name", "")
    )
    fig.update_layout(
        title=(
            _fatigue_text(title)
            if title is not None
            else f"Fatigue utilisation - {spectrum_name}"
        ),
        template=_TEMPLATE,
        height=520,
        margin=dict(l=20, r=25, t=55, b=96),
        xaxis=dict(title=dict(text="x (mm)", standoff=10), zeroline=True),
        yaxis=dict(
            title="y (mm)",
            scaleanchor="x",
            scaleratio=1,
            zeroline=True,
        ),
        coloraxis=dict(
            cmin=0.0,
            cmax=cmax,
            colorscale="Cividis",
            colorbar=dict(
                title="Utilisation",
                tickvals=tickvals,
                ticktext=[f"{tick:.2f}" for tick in tickvals],
                thickness=14,
                len=0.72,
            ),
        ),
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="top",
            y=_legend_y(520),
            x=0.5,
            xanchor="center",
        ),
    )
    fig.add_annotation(
        x=0.99,
        y=0.99,
        xref="paper",
        yref="paper",
        xanchor="right",
        yanchor="top",
        text="acceptance limit = 1.00",
        showarrow=False,
        bgcolor="rgba(255,255,255,0.82)",
        font=dict(size=10, color=SCHEMATIC_INK),
    )
    if search_bound_failed:
        fig.add_annotation(
            x=0.01,
            y=0.99,
            xref="paper",
            yref="paper",
            xanchor="left",
            yanchor="top",
            text=(
                "certified search upper D = "
                f"{_fatigue_hover_number(search_upper, '.3f')} &gt; 1.00"
            ),
            showarrow=False,
            bgcolor="rgba(253,236,236,0.92)",
            bordercolor="#9B1C1C",
            font=dict(size=10, color="#9B1C1C"),
        )
    if search is not None and not search_converged:
        fig.add_annotation(
            x=0.01,
            y=0.90 if search_bound_failed else 0.99,
            xref="paper",
            yref="paper",
            xanchor="left",
            yanchor="top",
            text="adaptive concrete search not converged; result invalid",
            showarrow=False,
            bgcolor="rgba(255,244,214,0.94)",
            bordercolor="#7A4E00",
            font=dict(size=10, color="#7A4E00"),
        )
    return fig


def _sn_range_at_cycles(cycles, *, n_star, knee_range, k1, k2):
    exponent = k1 if cycles <= n_star else k2
    return knee_range * (n_star / cycles) ** (1.0 / exponent)


def _finite_power_of_ten(exponent):
    """Return a positive finite float at extreme base-10 exponents."""

    try:
        value = 10.0 ** exponent
    except OverflowError:
        return _FLOAT_MAX
    if value == 0.0:
        return _FLOAT_MIN_POSITIVE
    return min(value, _FLOAT_MAX)


def fatigue_sn_figure(
    result,
    properties,
    gamma_s,
    *,
    title=None,
):
    """Plot characteristic/design two-slope S-N curves and applied bins."""

    n_star = float(_fatigue_value(properties, "n_star"))
    k1 = float(_fatigue_value(properties, "k1"))
    k2 = float(_fatigue_value(properties, "k2"))
    characteristic_knee = float(
        _fatigue_value(properties, "delta_sigma_rsk_mpa")
    )
    gamma_s = float(gamma_s)
    design_knee = characteristic_knee / gamma_s
    bins = list(_fatigue_items(result, "bins"))
    applied_cycles = [
        float(_fatigue_value(item, "cycles"))
        for item in bins
        if float(_fatigue_value(item, "cycles", 0.0)) > 0.0
    ]
    finite_lives = [
        float(_fatigue_value(item, "cycles_to_failure"))
        for item in bins
        if (
            _fatigue_value(item, "cycles_to_failure") is not None
            and math.isfinite(float(_fatigue_value(item, "cycles_to_failure")))
            and float(_fatigue_value(item, "cycles_to_failure")) > 0.0
        )
    ]
    minimum_cycles = min([1.0e3, n_star, *applied_cycles, *finite_lives])
    maximum_cycles = max([1.0e9, n_star, *applied_cycles, *finite_lives])
    log_min = max(
        math.floor(math.log10(minimum_cycles)),
        math.log10(_FLOAT_MIN_POSITIVE),
    )
    log_max = min(
        math.ceil(math.log10(maximum_cycles)),
        math.log10(_FLOAT_MAX),
    )
    count = min(
        600,
        max(120, int(math.ceil((log_max - log_min) * 30))),
    )
    curve_cycles = [
        _finite_power_of_ten(
            log_min + (log_max - log_min) * index / (count - 1)
        )
        for index in range(count)
    ]
    characteristic = [
        _sn_range_at_cycles(
            cycles,
            n_star=n_star,
            knee_range=characteristic_knee,
            k1=k1,
            k2=k2,
        )
        for cycles in curve_cycles
    ]
    design = [value / gamma_s for value in characteristic]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=curve_cycles,
        y=characteristic,
        mode="lines",
        name="characteristic S-N curve",
        line=dict(color=CURVE_CHAR, width=2.0, dash="dash"),
        hovertemplate=(
            "N = %{x:.3g}<br>"
            f"{_DELTA}{_SIGMA} = %{{y:.3g}} MPa<extra></extra>"
        ),
    ))
    fig.add_trace(go.Scatter(
        x=curve_cycles,
        y=design,
        mode="lines",
        name="design S-N curve",
        line=dict(color=ENVELOPE, width=2.8),
        hovertemplate=(
            "N = %{x:.3g}<br>"
            f"design {_DELTA}{_SIGMA} = %{{y:.3g}} MPa<extra></extra>"
        ),
    ))
    fig.add_trace(go.Scatter(
        x=[n_star],
        y=[design_knee],
        mode="markers",
        name="design knee N*",
        marker=dict(
            size=9,
            color=ENVELOPE,
            symbol="diamond",
            line=dict(color="white", width=1.0),
        ),
        hovertemplate=(
            "N* = %{x:.3g}<br>"
            f"design {_DELTA}{_SIGMA} = %{{y:.3g}} MPa<extra></extra>"
        ),
    ))

    plotted = [
        item
        for item in bins
        if (
            float(_fatigue_value(item, "cycles", 0.0)) > 0.0
            and float(_fatigue_value(item, "design_stress_range_mpa", 0.0))
            > 0.0
        )
    ]
    if plotted:
        custom = [
            [
                _fatigue_text(_fatigue_value(item, "bin_name", "-")),
                _fatigue_hover_number(
                    _fatigue_value(item, "cycles_to_failure", math.inf)
                ),
                _fatigue_hover_number(_fatigue_value(item, "damage", 0.0)),
            ]
            for item in plotted
        ]
        fig.add_trace(go.Scatter(
            x=[float(_fatigue_value(item, "cycles")) for item in plotted],
            y=[
                float(_fatigue_value(item, "design_stress_range_mpa"))
                for item in plotted
            ],
            mode="markers+text",
            name="applied spectrum bins",
            marker=dict(
                size=10,
                color=LOAD_POINT,
                symbol="circle",
                line=dict(color="#111827", width=0.8),
            ),
            text=[
                _fatigue_text(_fatigue_value(item, "bin_name", "-"))
                for item in plotted
            ],
            textposition="top center",
            textfont=dict(size=9, color=SCHEMATIC_INK),
            customdata=custom,
            hovertemplate=(
                "%{customdata[0]}<br>applied cycles = %{x:.3g}<br>"
                f"design {_DELTA}{_SIGMA} = %{{y:.3g}} MPa<br>"
                "N_R = %{customdata[1]}<br>"
                "Miner contribution = %{customdata[2]}<extra></extra>"
            ),
        ))
    omitted = len(bins) - len(plotted)
    if omitted:
        fig.add_annotation(
            x=0.01,
            y=0.02,
            xref="paper",
            yref="paper",
            xanchor="left",
            yanchor="bottom",
            text=f"{omitted} zero-range bin omitted from logarithmic axes",
            showarrow=False,
            bgcolor="rgba(255,255,255,0.82)",
            font=dict(size=10, color=SCHEMATIC_INK),
        )
    fig.add_vline(
        x=n_star,
        line_width=0.9,
        line_dash="dot",
        line_color=GUIDE_LINE,
    )
    element_id = _fatigue_text(_fatigue_value(result, "element_id", ""))
    fig.update_layout(
        title=(
            _fatigue_text(title)
            if title is not None
            else f"S-N assessment - {element_id}"
        ),
        template=_TEMPLATE,
        height=450,
        margin=dict(l=65, r=25, t=55, b=100),
        xaxis=dict(
            title=dict(text="Cycles, N", standoff=10),
            type="log",
            exponentformat="power",
        ),
        yaxis=dict(
            title=f"Stress range, {_DELTA}{_SIGMA} (MPa)",
            type="log",
            exponentformat="power",
        ),
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="top",
            y=_legend_y(450),
            x=0.5,
            xanchor="center",
        ),
    )
    return fig


def fatigue_damage_figure(result, *, title=None):
    """Plot per-bin and cumulative Palmgren-Miner damage."""

    bins = list(_fatigue_items(result, "bins"))
    names = [
        _fatigue_text(_fatigue_value(item, "bin_name", "-"))
        for item in bins
    ]
    raw_damage = [
        float(_fatigue_value(item, "damage", 0.0))
        for item in bins
    ]
    finite_damage = [
        max(value, 0.0) for value in raw_damage if math.isfinite(value)
    ]
    unbounded = [
        value > 0.0 and not math.isfinite(value)
        for value in raw_damage
    ]
    largest_finite = max([1.0, *finite_damage])
    finite_sum = sum(finite_damage)
    cap_basis = max(
        largest_finite,
        finite_sum if math.isfinite(finite_sum) else largest_finite,
    )
    plot_cap = (
        _FLOAT_MAX
        if cap_basis >= _FLOAT_MAX / 1.05
        else max(1.10, cap_basis * 1.05)
    )
    damage = [
        plot_cap if is_unbounded else max(value, 0.0)
        for value, is_unbounded in zip(raw_damage, unbounded)
    ]
    cumulative_raw = []
    cumulative = []
    cumulative_unbounded = []
    running = 0.0
    for raw in raw_damage:
        running = running + raw if math.isfinite(running) else running
        is_unbounded = not math.isfinite(running)
        cumulative_raw.append(running)
        cumulative_unbounded.append(is_unbounded)
        cumulative.append(plot_cap if is_unbounded else running)
    any_unbounded = any(unbounded) or any(cumulative_unbounded)
    positive = [value for value in [*damage, *cumulative] if value > 0.0]
    use_log_scale = (
        not any_unbounded
        and bool(positive)
        and max(cumulative, default=0.0) < 0.05
    )
    fig = go.Figure()
    cycles = [
        float(_fatigue_value(item, "cycles", 0.0))
        for item in bins
    ]
    if use_log_scale:
        visible = [
            (name, value, count)
            for name, value, count in zip(names, damage, cycles)
            if value > 0.0
        ]
        fig.add_trace(go.Scatter(
            x=[item[0] for item in visible],
            y=[item[1] for item in visible],
            mode="markers",
            name="bin damage",
            marker=dict(
                size=10,
                color=LOAD_POINT,
                symbol="square",
                line=dict(color="#111827", width=0.7),
            ),
            customdata=[item[2] for item in visible],
            hovertemplate=(
                "%{x}<br>cycles = %{customdata:.3g}<br>"
                "damage = %{y:.3g}<extra></extra>"
            ),
        ))
    else:
        fig.add_trace(go.Bar(
            x=names,
            y=damage,
            name="bin damage",
            marker=dict(
                color=[
                    "#9B1C1C" if is_unbounded else LOAD_POINT
                    for is_unbounded in unbounded
                ],
                line=dict(color="#111827", width=0.5),
            ),
            customdata=[
                [count, _fatigue_hover_number(raw)]
                for count, raw in zip(cycles, raw_damage)
            ],
            text=["inf" if is_unbounded else "" for is_unbounded in unbounded],
            textposition="outside",
            cliponaxis=False,
            hovertemplate=(
                "%{x}<br>cycles = %{customdata[0]:.3g}<br>"
                "damage = %{customdata[1]}<extra></extra>"
            ),
        ))
    fig.add_trace(go.Scatter(
        x=names,
        y=[
            value if (not use_log_scale or value > 0.0) else None
            for value in cumulative
        ],
        mode=(
            "lines+markers+text"
            if any(cumulative_unbounded)
            else "lines+markers"
        ),
        name="cumulative damage",
        line=dict(color=ENVELOPE, width=2.4),
        marker=dict(size=7, symbol="diamond"),
        text=[
            "inf" if is_unbounded else ""
            for is_unbounded in cumulative_unbounded
        ],
        textposition="top center",
        cliponaxis=False,
        customdata=[
            _fatigue_hover_number(value) for value in cumulative_raw
        ],
        hovertemplate=(
            "%{x}<br>cumulative damage = %{customdata}<extra></extra>"
        ),
    ))
    fig.add_hline(
        y=1.0,
        line_width=1.5,
        line_dash="dash",
        line_color=BAR_COMPRESSION,
        annotation_text="D = 1.00 limit",
        annotation_position="top right",
    )
    if any_unbounded:
        fig.add_annotation(
            x=0.01,
            y=0.98,
            xref="paper",
            yref="paper",
            xanchor="left",
            yanchor="top",
            text=(
                "Unbounded Miner damage (inf); affected bars or the cumulative "
                "line are capped for plotting"
            ),
            showarrow=False,
            bgcolor="rgba(253,236,236,0.92)",
            bordercolor="#9B1C1C",
            font=dict(size=10, color="#9B1C1C"),
        )
    identifier = (
        _fatigue_value(result, "element_id")
        or (
            "concrete fibre "
            + str(_fatigue_value(result, "fibre_index", "-"))
        )
    )
    identifier = _fatigue_text(identifier)
    yaxis = dict(
        title=(
            "Miner damage, D (log scale)"
            if use_log_scale else "Miner damage, D"
        ),
        rangemode=None if use_log_scale else "tozero",
        gridcolor=_GRID_COLOR,
    )
    if use_log_scale:
        yaxis.update(
            type="log",
            exponentformat="power",
            range=[
                math.floor(math.log10(min(positive))) - 0.25,
                0.15,
            ],
        )
        zero_bins = sum(value <= 0.0 for value in damage)
        if zero_bins:
            note = f"{zero_bins} zero-damage bin"
            if zero_bins != 1:
                note += "s"
            note += " omitted"
            fig.add_annotation(
                x=0.01,
                y=0.02,
                xref="paper",
                yref="paper",
                xanchor="left",
                yanchor="bottom",
                text=note,
                showarrow=False,
                bgcolor="rgba(255,255,255,0.82)",
                font=dict(size=10, color=SCHEMATIC_INK),
            )
    fig.update_layout(
        title=(
            _fatigue_text(title)
            if title is not None
            else f"Miner damage - {identifier}"
        ),
        template=_TEMPLATE,
        height=400,
        margin=dict(l=60, r=25, t=55, b=100),
        xaxis=dict(title=dict(text="Spectrum bin", standoff=10)),
        yaxis=yaxis,
        barmode="group",
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="top",
            y=_legend_y(400),
            x=0.5,
            xanchor="center",
        ),
    )
    return fig


def detailing_geometry_figure(
    outer,
    holes,
    bars,
    tendons,
    *,
    bar_elements=None,
    tendon_elements=None,
    highlight_ids=None,
    spacing_pair=None,
    tension_zone=None,
    title="Detailing geometry",
):
    """Publication-ready section figure for minimum steel and spacing evidence.

    Element coordinates remain tied to stable IDs.  A governing spacing pair is
    dimensioned between the actual circular perimeters using the entered
    diameters; selected minimum-reinforcement bars receive an open highlight.
    """
    bar_elements = list(bar_elements or [])
    tendon_elements = list(tendon_elements or [])
    bar_ids = [str(item.get("id") or index + 1)
               for index, item in enumerate(bar_elements)]
    tendon_ids = [str(item.get("id") or index + 1)
                  for index, item in enumerate(tendon_elements)]
    fig = section_figure(
        outer,
        holes,
        bars,
        title=title,
        tendons=tendons,
        show_labels=True,
        scale=1000.0,
        unit="mm",
        height=570,
        bar_ids=bar_ids,
        tendon_ids=tendon_ids,
    )
    records = {
        str(item.get("id")): item
        for item in bar_elements + tendon_elements
        if item.get("id")
    }
    selected = [records[value] for value in (highlight_ids or []) if value in records]
    if selected:
        fig.add_trace(go.Scatter(
            x=[float(item["x_mm"]) for item in selected],
            y=[float(item["y_mm"]) for item in selected],
            mode="markers",
            name="included reinforcement",
            marker=dict(
                size=20,
                symbol="circle-open",
                color="#0072B2",
                line=dict(color="#0072B2", width=2.4),
            ),
            text=[str(item.get("id")) for item in selected],
            hovertemplate="%{text}<br>included in check<extra></extra>",
        ))

    zone = tension_zone or {}
    direction = zone.get("tension_direction") or []
    if len(direction) == 2 and zone.get("neutral_c_m") is not None and outer:
        ux, uy = float(direction[0]), float(direction[1])
        c_mm = float(zone["neutral_c_m"]) * 1000.0
        outer_x = [float(point[0]) * 1000.0 for point in outer]
        outer_y = [float(point[1]) * 1000.0 for point in outer]
        xmin, xmax = min(outer_x), max(outer_x)
        ymin, ymax = min(outer_y), max(outer_y)
        span = max(xmax - xmin, ymax - ymin, 1.0)
        tolerance = 1.0e-9 * span
        intersections = []
        if abs(uy) > 1.0e-12:
            for x_value in (xmin, xmax):
                y_value = (-c_mm - ux * x_value) / uy
                if ymin - tolerance <= y_value <= ymax + tolerance:
                    intersections.append((x_value, y_value))
        if abs(ux) > 1.0e-12:
            for y_value in (ymin, ymax):
                x_value = (-c_mm - uy * y_value) / ux
                if xmin - tolerance <= x_value <= xmax + tolerance:
                    intersections.append((x_value, y_value))
        unique = []
        for point in intersections:
            if not any(math.hypot(point[0] - other[0], point[1] - other[1])
                       <= tolerance for other in unique):
                unique.append(point)
        if len(unique) >= 2:
            first, second = max(
                ((first, second) for index, first in enumerate(unique)
                 for second in unique[index + 1:]),
                key=lambda pair: math.hypot(
                    pair[1][0] - pair[0][0], pair[1][1] - pair[0][1]
                ),
            )
            fig.add_trace(go.Scatter(
                x=[first[0], second[0]],
                y=[first[1], second[1]],
                mode="lines",
                name="resultant tension boundary",
                line=dict(color="#4B5563", width=2.0, dash="dash"),
                hovertemplate="gross-concrete zero-strain line<extra></extra>",
            ))
            mid_x = 0.5 * (first[0] + second[0])
            mid_y = 0.5 * (first[1] + second[1])
            fig.add_annotation(
                x=mid_x + ux * 0.16 * span,
                y=mid_y + uy * 0.16 * span,
                ax=mid_x,
                ay=mid_y,
                xref="x",
                yref="y",
                axref="x",
                ayref="y",
                text="tension",
                showarrow=True,
                arrowhead=3,
                arrowsize=1.0,
                arrowwidth=1.8,
                arrowcolor="#4B5563",
                font=dict(color="#4B5563", size=11),
                bgcolor="rgba(255,255,255,0.82)",
            )

    pair = spacing_pair or {}
    first = records.get(str(pair.get("first_id")))
    second = records.get(str(pair.get("second_id")))
    if first is not None and second is not None:
        x1, y1 = float(first["x_mm"]), float(first["y_mm"])
        x2, y2 = float(second["x_mm"]), float(second["y_mm"])
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        ux, uy = ((dx / length, dy / length) if length > 0.0 else (1.0, 0.0))
        r1 = 0.5 * float(pair.get("phi_first_mm") or first.get("diameter_mm") or 0.0)
        r2 = 0.5 * float(pair.get("phi_second_mm") or second.get("diameter_mm") or 0.0)
        ax, ay = x1 + ux * r1, y1 + uy * r1
        bx, by = x2 - ux * r2, y2 - uy * r2
        status = str(pair.get("status") or "REVIEW").upper()
        colour = {
            "PASS": "#009E73",
            "FAIL": "#D55E00",
            "REVIEW": "#E69F00",
        }.get(status, "#334155")
        fig.add_trace(go.Scatter(
            x=[x1, x2],
            y=[y1, y2],
            mode="markers",
            name="governing spacing pair",
            marker=dict(
                size=22,
                symbol="circle-open",
                color=colour,
                line=dict(color=colour, width=2.6),
            ),
            text=[str(pair.get("first_id")), str(pair.get("second_id"))],
            hovertemplate="%{text}<br>governing pair<extra></extra>",
        ))
        fig.add_shape(
            type="line", x0=ax, y0=ay, x1=bx, y1=by,
            line=dict(color=colour, width=2.4),
        )
        outer_x = [float(point[0]) * 1000.0 for point in (outer or [])]
        outer_y = [float(point[1]) * 1000.0 for point in (outer or [])]
        span = max(
            (max(outer_x) - min(outer_x)) if outer_x else 1.0,
            (max(outer_y) - min(outer_y)) if outer_y else 1.0,
            1.0,
        )
        tick = 0.018 * span
        px, py = -uy, ux
        for x, y in ((ax, ay), (bx, by)):
            fig.add_shape(
                type="line",
                x0=x - px * tick / 2.0,
                y0=y - py * tick / 2.0,
                x1=x + px * tick / 2.0,
                y1=y + py * tick / 2.0,
                line=dict(color=colour, width=2.0),
            )
        clear = float(pair.get("clear_mm") or 0.0)
        required = float(pair.get("required_mm") or 0.0)
        fig.add_annotation(
            x=0.5 * (ax + bx),
            y=0.5 * (ay + by),
            text=(f"c = {clear:.1f} mm<br>required = {required:.1f} mm"),
            showarrow=False,
            xanchor="center",
            yanchor="bottom",
            yshift=8,
            bgcolor="rgba(255,255,255,0.88)",
            bordercolor=colour,
            borderwidth=1.2,
            font=dict(color=SCHEMATIC_INK, size=11),
        )
    return fig


def shear_geometry_figure(outer, holes, bars, *, axis, tension_low,
                          centroid, asl_bar_ids, asl_cg_m, asl_mm2,
                          d_mm, z_mm, bw_mm, bw_source,
                          signed_v_ed=None,
                          title="Shear geometry"):
    """Annotated section used to audit the geometry behind a shear check.

    ``axis == 'x'`` means vertical shear / bending about x; ``axis == 'y'``
    means horizontal shear / bending about y. The actual section is retained,
    the bars counted in ``A_sl`` are marked and numbered, and the displayed
    dimensions use the same derived payload as the resistance calculation.
    ``b_w`` is a callout because an automatic value can be the sum of multiple
    solid web intervals (for example a box section), not one bounding width.
    """
    outer = list(outer or [])
    holes = list(holes or [])
    bars = list(bars or [])
    fig = section_figure(
        outer, holes, bars, title=title, show_labels=False,
        scale=1000.0, unit="mm", height=470,
    )
    if not outer:
        return fig
    action_symbol = "V<sub>y,Ed</sub>" if axis == "x" else "V<sub>x,Ed</sub>"
    signed_action = None if signed_v_ed is None else float(signed_v_ed)
    action_label = (
        action_symbol
        if signed_action is None
        else f"{action_symbol} = {signed_action:.3g} kN"
    )
    positive_action = signed_action is None or signed_action >= 0.0

    xs = [float(p[0]) * 1000.0 for p in outer]
    ys = [float(p[1]) * 1000.0 for p in outer]
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    span_x = max(xmax - xmin, 1.0)
    span_y = max(ymax - ymin, 1.0)
    cx, cy = float(centroid[0]) * 1000.0, float(centroid[1]) * 1000.0
    selected = [i for i in asl_bar_ids or [] if 1 <= i <= len(bars)]
    if selected:
        pts = [bars[i - 1] for i in selected]
        fig.add_trace(go.Scatter(
            x=[p[0] * 1000.0 for p in pts],
            y=[p[1] * 1000.0 for p in pts],
            mode="markers+text", name="included in Asl",
            marker=dict(size=18, symbol="star", color=LOAD_POINT,
                        line=dict(color="white", width=1.2)),
            text=[str(i) for i in selected], textposition="bottom center",
            textfont=dict(size=10, color=SCHEMATIC_INK),
            hovertemplate="Bar %{text}<br>included in Asl<extra></extra>",
        ))

    if axis == "x":
        fig.add_shape(type="line", x0=xmin, x1=xmax, y0=cy, y1=cy,
                      line=dict(color=SCHEMATIC_INK, width=1, dash="dot"))
        face_level = ymin if tension_low else ymax
        fig.add_shape(type="line", x0=xmin, x1=xmax, y0=face_level, y1=face_level,
                      line=dict(color=LOAD_POINT, width=2, dash="dash"))
        fig.add_annotation(x=xmin + 0.04 * span_x, y=face_level,
                           text="tension face", showarrow=False,
                           xanchor="left",
                           yanchor="bottom" if tension_low else "top",
                           yshift=6 if tension_low else -6,
                           font=dict(size=10, color=SCHEMATIC_INK))
        # VEd arrow in the physical shear direction.
        arrow_y0, arrow_y1 = (
            (ymin, ymax) if positive_action else (ymax, ymin)
        )
        fig.add_annotation(x=xmin - 0.12 * span_x, y=arrow_y1,
                           ax=xmin - 0.12 * span_x, ay=arrow_y0,
                           axref="x", ayref="y", text="", showarrow=True,
                           arrowhead=2, arrowwidth=2, arrowcolor=LOAD_POINT,
                           font=dict(size=11, color=SCHEMATIC_INK))
        fig.add_annotation(x=xmin - 0.12 * span_x, y=(ymin + ymax) / 2.0,
                           text=action_label, showarrow=False, xanchor="right", xshift=-6,
                           font=dict(size=11, color=SCHEMATIC_INK))
        if asl_cg_m is not None and d_mm > 0.0:
            cg = float(asl_cg_m) * 1000.0
            direction = 1.0 if tension_low else -1.0
            comp = ymax if tension_low else ymin
            dim_x = xmax + 0.13 * span_x
            z_x = xmax + 0.25 * span_x
            fig.add_shape(type="line", x0=dim_x, x1=dim_x, y0=cg, y1=comp,
                          line=dict(color=SCHEMATIC_INK, width=1.2))
            fig.add_annotation(x=dim_x, y=comp, ax=dim_x,
                               ay=comp - direction * 0.10 * span_y,
                               axref="x", ayref="y", text="", showarrow=True,
                               arrowhead=2, arrowwidth=1, arrowcolor=SCHEMATIC_INK)
            fig.add_annotation(x=dim_x, y=cg, ax=dim_x,
                               ay=cg + direction * 0.10 * span_y,
                               axref="x", ayref="y", text="", showarrow=True,
                               arrowhead=2, arrowwidth=1, arrowcolor=SCHEMATIC_INK)
            fig.add_annotation(x=dim_x, y=(cg + comp) / 2.0,
                               text=f"d = {d_mm:.0f} mm", showarrow=False,
                               xanchor="right", xshift=-6)
            z_end = cg + direction * min(float(z_mm), float(d_mm))
            fig.add_shape(type="line", x0=z_x, x1=z_x, y0=cg, y1=z_end,
                          line=dict(color=ENVELOPE, width=1.2))
            fig.add_annotation(x=z_x, y=(cg + z_end) / 2.0,
                               text=f"z = {z_mm:.0f} mm", showarrow=False,
                               xanchor="left", xshift=6,
                               font=dict(color=ENVELOPE))
    else:
        fig.add_shape(type="line", x0=cx, x1=cx, y0=ymin, y1=ymax,
                      line=dict(color=SCHEMATIC_INK, width=1, dash="dot"))
        face_level = xmin if tension_low else xmax
        fig.add_shape(type="line", x0=face_level, x1=face_level, y0=ymin, y1=ymax,
                      line=dict(color=LOAD_POINT, width=2, dash="dash"))
        fig.add_annotation(x=face_level, y=ymin + 0.05 * span_y,
                           text="tension face", showarrow=False,
                           xanchor="left" if tension_low else "right",
                           xshift=6 if tension_low else -6, yanchor="bottom",
                           font=dict(size=10, color=SCHEMATIC_INK))
        arrow_x0, arrow_x1 = (
            (xmin, xmax) if positive_action else (xmax, xmin)
        )
        fig.add_annotation(x=arrow_x1, y=ymax + 0.12 * span_y,
                           ax=arrow_x0, ay=ymax + 0.12 * span_y,
                           axref="x", ayref="y", text="", showarrow=True,
                           arrowhead=2, arrowwidth=2, arrowcolor=LOAD_POINT,
                           font=dict(size=11, color=SCHEMATIC_INK))
        fig.add_annotation(x=(xmin + xmax) / 2.0, y=ymax + 0.12 * span_y,
                           text=action_label, showarrow=False, yanchor="bottom", yshift=6,
                           font=dict(size=11, color=SCHEMATIC_INK))
        if asl_cg_m is not None and d_mm > 0.0:
            cg = float(asl_cg_m) * 1000.0
            direction = 1.0 if tension_low else -1.0
            comp = xmax if tension_low else xmin
            dim_y = ymax + 0.13 * span_y
            z_y = ymax + 0.25 * span_y
            fig.add_shape(type="line", x0=cg, x1=comp, y0=dim_y, y1=dim_y,
                          line=dict(color=SCHEMATIC_INK, width=1.2))
            fig.add_annotation(x=comp, y=dim_y,
                               ax=comp - direction * 0.10 * span_x, ay=dim_y,
                               axref="x", ayref="y", text="", showarrow=True,
                               arrowhead=2, arrowwidth=1, arrowcolor=SCHEMATIC_INK)
            fig.add_annotation(x=cg, y=dim_y,
                               ax=cg + direction * 0.10 * span_x, ay=dim_y,
                               axref="x", ayref="y", text="", showarrow=True,
                               arrowhead=2, arrowwidth=1, arrowcolor=SCHEMATIC_INK)
            fig.add_annotation(x=(cg + comp) / 2.0, y=dim_y,
                               text=f"d = {d_mm:.0f} mm", showarrow=False,
                               yanchor="top", yshift=-6)
            z_end = cg + direction * min(float(z_mm), float(d_mm))
            fig.add_shape(type="line", x0=cg, x1=z_end, y0=z_y, y1=z_y,
                          line=dict(color=ENVELOPE, width=1.2))
            fig.add_annotation(x=(cg + z_end) / 2.0, y=z_y,
                               text=f"z = {z_mm:.0f} mm", showarrow=False,
                               yanchor="bottom", yshift=6,
                               font=dict(color=ENVELOPE))

    ids = ", ".join(str(i) for i in selected) if selected else "none"
    fig.add_annotation(
        x=0.99, y=0.99, xref="paper", yref="paper",
        xanchor="right", yanchor="top", showarrow=False, align="left",
        text=(f"<b>b<sub>w</sub></b> = {bw_mm:.0f} mm ({bw_source})<br>"
              f"<b>A<sub>sl</sub></b> = {asl_mm2:.0f} mm<sup>2</sup> "
              f"(bars {ids})<br>bending about {axis}<br>"
              "dotted: gross centroid / Asl selection"),
        bgcolor="rgba(255,255,255,0.82)",
        font=dict(size=10, color=SCHEMATIC_INK),
    )
    return fig


def biaxial_shear_overview_figure(
    outer, holes=None, bars=None, *, vx_ed=0.0, vy_ed=0.0,
    title="Biaxial shear actions",
):
    """Section-coordinate overview of signed Vx,Ed and Vy,Ed actions.

    The plot is evidence, not an interaction diagram: arrow direction follows the
    entered sign and no resultant vector or acceptance boundary is drawn.
    """
    outer = list(outer or [])
    fig = section_figure(
        outer, holes or [], bars or [], title=title, show_labels=False,
        scale=1000.0, unit="mm", height=500,
    )
    if not outer:
        return fig
    xs = [float(point[0]) * 1000.0 for point in outer]
    ys = [float(point[1]) * 1000.0 for point in outer]
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    span_x = max(xmax - xmin, 1.0)
    span_y = max(ymax - ymin, 1.0)

    def arrow(x0, y0, x1, y1, colour):
        fig.add_annotation(
            x=x1, y=y1, ax=x0, ay=y0, axref="x", ayref="y",
            text="", showarrow=True, arrowhead=3, arrowsize=1.1,
            arrowwidth=2.2, arrowcolor=colour,
        )

    vx_y = ymax + 0.16 * span_y
    if float(vx_ed) >= 0.0:
        arrow(xmin, vx_y, xmax, vx_y, LOAD_POINT)
    else:
        arrow(xmax, vx_y, xmin, vx_y, LOAD_POINT)
    fig.add_annotation(
        x=0.5 * (xmin + xmax), y=vx_y, yshift=11, showarrow=False,
        text=f"V<sub>x,Ed</sub> = {float(vx_ed):.3g} kN",
        font=dict(size=11, color=LOAD_POINT),
    )

    vy_x = xmin - 0.18 * span_x
    if float(vy_ed) >= 0.0:
        arrow(vy_x, ymin, vy_x, ymax, BAR_TENSION)
    else:
        arrow(vy_x, ymax, vy_x, ymin, BAR_TENSION)
    fig.add_annotation(
        x=vy_x, y=0.5 * (ymin + ymax), xshift=-12, showarrow=False,
        text=f"V<sub>y,Ed</sub> = {float(vy_ed):.3g} kN",
        textangle=-90, font=dict(size=11, color=BAR_TENSION),
    )
    fig.update_xaxes(range=[xmin - 0.34 * span_x, xmax + 0.10 * span_x])
    fig.update_yaxes(range=[ymin - 0.10 * span_y, ymax + 0.32 * span_y])
    return fig


def interaction_figure(mx, my, applied=None, angles=None, util=None,
                       closed=True, title="M-M interaction"):
    """Biaxial moment capacity envelope, with an optional applied-load point.

    Drawn to match the section's orientation: ``Mx`` is bending *about* the
    x-axis (its stress varies with y), so it is the **vertical** axis here, and
    ``My`` (about the y-axis) is the **horizontal** axis. The two axes share a
    common scale (equal aspect), so the envelope keeps its true shape. ``applied``
    is ``(Mx, My)``. ``angles`` (the swept neutral-axis angle at each envelope
    vertex, aligned with ``mx``/``my``) is shown on hover. When ``util`` (the
    radial utilisation) is given with ``applied``, a dotted ray from the origin
    through the applied point marks the capacity in that load direction, so the
    utilisation reads off the figure.
    """
    # Snap the floating-point noise at the apexes to zero: a pure-Mx (or pure-My)
    # point should sit on the axis, but the solver leaves a tiny residual that the
    # hover would otherwise show as e.g. "(333.9551, 0.0007)". Round it to 0 so the
    # apex reads cleanly; the threshold is relative to the envelope size.
    scale = max((abs(v) for v in list(mx) + list(my)), default=1.0) or 1.0
    snap = lambda v: 0.0 if abs(v) <= scale * 1e-4 else v
    mx = [snap(v) for v in mx]
    my = [snap(v) for v in my]

    fig = go.Figure()
    # My on the horizontal axis, Mx on the vertical -- see the note above. A full 360
    # sweep is a CLOSED envelope: repeat the first vertex and fill it so it reads as an
    # enclosed capacity region. A partial sweep is an OPEN arc, drawn as a bare line (no
    # closing chord, no fill) -- filling it would shade a capacity area across the
    # artificial closing chord that was never computed.
    if closed:
        cap = go.Scatter(x=my + my[:1], y=mx + mx[:1], mode="lines", fill="toself",
                         fillcolor=ENVELOPE_FILL, line=dict(color=ENVELOPE, width=2),
                         name="capacity")
        cap_angles = (list(angles) + list(angles[:1])) if angles is not None else None
    else:
        cap = go.Scatter(x=list(my), y=list(mx), mode="lines",
                         line=dict(color=ENVELOPE, width=2),
                         name="capacity (partial arc)")
        cap_angles = list(angles) if angles is not None else None
    if angles is not None and len(angles) == len(mx):
        cap.customdata = cap_angles
        cap.hovertemplate = ("V = %{customdata:.0f} deg<br>My = %{x:.1f} kNm"
                             "<br>Mx = %{y:.1f} kNm<extra></extra>")
    else:
        cap.hovertemplate = "My = %{x:.1f} kNm<br>Mx = %{y:.1f} kNm<extra></extra>"
    fig.add_trace(cap)

    if applied is not None:
        a_mx, a_my = snap(applied[0]), snap(applied[1])
        # Utilisation ray: origin -> applied -> the envelope crossing in that same
        # direction (capacity = applied / util). The applied point then sits at the
        # fraction ``util`` of the way out to the capacity, so the ratio is visual.
        if util is not None and math.isfinite(util) and util > 1e-9:
            gx, gy = a_my / util, a_mx / util
            fig.add_trace(go.Scatter(
                x=[0.0, gx], y=[0.0, gy], mode="lines",
                line=dict(color=GUIDE_LINE, width=1, dash="dot"),
                name="load direction", hoverinfo="skip"))
            fig.add_trace(go.Scatter(
                x=[gx], y=[gy], mode="markers", name="capacity (this direction)",
                marker=dict(size=11, color=ENVELOPE, symbol="circle-open",
                            line=dict(width=2)),
                hovertemplate="My = %{x:.1f} kNm<br>Mx = %{y:.1f} kNm<extra></extra>"))
        fig.add_trace(go.Scatter(
            x=[a_my], y=[a_mx], mode="markers",
            marker=dict(size=11, color=LOAD_POINT, symbol="x"), name="applied",
            hovertemplate="My = %{x:.1f} kNm<br>Mx = %{y:.1f} kNm<extra></extra>"))
        if util is not None and math.isfinite(util):
            # Below-right of the applied point, clear of the (up-and-out) load ray.
            fig.add_annotation(x=a_my, y=a_mx, text=f"util = {util:.2f}",
                               showarrow=True, arrowhead=2, arrowsize=0.7,
                               arrowwidth=1, arrowcolor=GUIDE_LINE, ax=32, ay=26,
                               font=dict(size=11, color=LOAD_POINT))
    # Which PHYSICAL bending each positive axis half means (the solver's V = 90 /
    # V = 0 convention): +Mx tensions the bottom face, +My the left face.
    _direction_note(fig, [
        _ARROW_UP + " +Mx: tension at the bottom face",
        _ARROW_RIGHT + " +My: tension at the left face"])
    fig.update_layout(
        title=title, template=_TEMPLATE, height=440,
        margin=dict(l=10, r=10, t=_LEGEND_TOP_M, b=_LEGEND_BOT_M),
        xaxis=dict(title=dict(text="My - about the y-axis (kNm)", standoff=10),
                   zeroline=True),
        yaxis=dict(title="Mx - about the x-axis (kNm)", zeroline=True,
                   scaleanchor="x", scaleratio=1),
        # Below the plot and below the x-axis title, clear of the plotly modebar.
        # Forced on: with a single trace (a capacity-only run, or a partial arc)
        # Plotly hides the legend by default -- losing the "capacity (partial arc)"
        # cue that tells the reader the drawn line is NOT the full closed envelope.
        showlegend=True,
        legend=dict(orientation="h", yanchor="top", y=_legend_y(440), x=0.5,
                    xanchor="center"),
    )
    return fig


def interaction_nm_figure(N, M, axis="x", applied=None, title="N-M interaction"):
    """Axial-moment (N-M) capacity diagram: N vertical, M horizontal.

    ``N`` (kN, tension positive) and ``M`` (kNm, about ``axis``) trace the closed
    capacity boundary -- the ``+M`` branch from pure tension to the squash load then
    the ``-M`` branch back. ``applied`` is ``(N, M)`` and marked on the diagram.
    """
    mlabel = "M_x" if axis == "x" else "M_y"
    scale = max((abs(v) for v in list(N) + list(M)), default=1.0) or 1.0
    snap = lambda v: 0.0 if abs(v) <= scale * 1e-4 else v
    Ms = [snap(v) for v in M]
    hover = ("M = %{x:.1f} kNm<br>N = %{y:.1f} kN<extra></extra>")

    fig = go.Figure()
    # Close the polyline (repeat the first vertex) so the boundary is drawn all the
    # way round, not just filled: without this the outline has a gap between the two
    # tension apexes.
    Ns = list(N)
    fig.add_trace(go.Scatter(x=Ms + Ms[:1], y=Ns + Ns[:1], mode="lines", fill="toself",
                             line=dict(color=ENVELOPE, width=2), name="capacity",
                             fillcolor=ENVELOPE_FILL, hovertemplate=hover))
    # Landmark points (derived from the boundary): the squash load (most
    # compression), the tension limit (most tension) and the max-moment apex. They
    # make the figure readable on its own.
    if Ns:
        i_sq = min(range(len(Ns)), key=lambda i: Ns[i])     # min N = squash
        i_te = max(range(len(Ns)), key=lambda i: Ns[i])     # max N = tension limit
        # SIGNED maximum (not abs): the "max Mx/My" label must sit on the positive
        # branch to match the signed "Max Mx/My" reported in the metrics. On an
        # asymmetric section the negative branch can have a larger |M|, so abs() would
        # place the label on the wrong side and contradict the numeric result.
        i_mm = max(range(len(Ms)), key=lambda i: Ms[i])       # positive max moment
        fig.add_trace(go.Scatter(
            x=[Ms[i_sq], Ms[i_te], Ms[i_mm]], y=[Ns[i_sq], Ns[i_te], Ns[i_mm]],
            mode="markers", marker=dict(size=7, color=ENVELOPE, symbol="diamond"),
            name="landmarks", hovertemplate=hover))
        # Short descriptors (the exact values are in the metrics row and on hover),
        # placed so they never clip the frame in the half-width side-by-side view:
        # squash below its apex, tension above its apex, max-moment just left of the
        # right-most apex.
        fig.add_annotation(x=Ms[i_sq], y=Ns[i_sq], text="squash", showarrow=False,
                           yshift=-11, yanchor="top", font=dict(size=11, color=ENVELOPE))
        fig.add_annotation(x=Ms[i_te], y=Ns[i_te], text="tension", showarrow=False,
                           yshift=11, yanchor="bottom", font=dict(size=11, color=ENVELOPE))
        fig.add_annotation(x=Ms[i_mm], y=Ns[i_mm], text="max " + mlabel.replace("_", ""),
                           showarrow=False, xshift=-8, xanchor="right",
                           font=dict(size=11, color=ENVELOPE))
    if applied is not None:
        fig.add_trace(go.Scatter(x=[snap(applied[1])], y=[applied[0]], mode="markers",
                                 marker=dict(size=11, color=LOAD_POINT, symbol="x"),
                                 name="applied", hovertemplate=hover))
    # Which PHYSICAL state each positive axis half means: +Mx tensions the bottom
    # face / +My the left face (the solver's V = 90 / V = 0 convention), +N is
    # axial tension.
    face = "bottom" if axis == "x" else "left"
    _direction_note(fig, [
        _ARROW_RIGHT + f" +{mlabel.replace('_', '')}: tension at the {face} face",
        _ARROW_UP + " +N: axial tension"])
    fig.update_layout(
        title=title, template=_TEMPLATE, height=460,
        margin=dict(l=10, r=10, t=_LEGEND_TOP_M, b=_LEGEND_BOT_M),
        xaxis=dict(title=dict(text=f"{mlabel.replace('_', '')} (kNm)", standoff=10),
                   zeroline=True),
        yaxis=dict(title="N (kN, tension +)", zeroline=True),
        legend=dict(orientation="h", yanchor="top", y=_legend_y(460), x=0.5,
                    xanchor="center"),
    )
    return fig


def vt_interaction_figure(vrd_max, trd_max, v_ed, t_ed,
                          title="V-T interaction (crushing)",
                          show_verdict=True):
    """Shear-torsion concrete-crushing envelope (EN 1992-1-1 6.29).

    The limit ``VEd/VRd,max + TEd/TRd,max = 1`` is the straight line from
    ``(VRd,max, 0)`` to ``(0, TRd,max)``; the safe region is below it. ``V`` is
    horizontal (kN), ``T`` vertical (kNm); the applied ``(VEd, TEd)`` is marked.
    """
    fig = go.Figure()
    if vrd_max > 0.0 and trd_max > 0.0:
        fig.add_trace(go.Scatter(
            x=[vrd_max, 0.0], y=[0.0, trd_max], mode="lines", fill="tozeroy",
            line=dict(color=ENVELOPE, width=2), name="limit (= 1)",
            fillcolor=ENVELOPE_FILL,
            hovertemplate="V = %{x:.1f} kN<br>T = %{y:.1f} kNm<extra></extra>"))
        # Interaction sum V/VRd,max + T/TRd,max: the applied point sits at that
        # fraction along the ray from the origin to the limit line, so draw the ray
        # to the crossing and annotate the sum (<= 1 is safe).
        s = v_ed / vrd_max + t_ed / trd_max
        if s > 1e-9:
            fig.add_trace(go.Scatter(
                x=[0.0, v_ed / s], y=[0.0, t_ed / s], mode="lines",
                line=dict(color=GUIDE_LINE, width=1, dash="dot"),
                name="load direction", hoverinfo="skip"))
            # Mark the ray's crossing of the limit line (the capacity in this load
            # direction), matching the M-M diagram's open-circle capacity marker.
            fig.add_trace(go.Scatter(
                x=[v_ed / s], y=[t_ed / s], mode="markers",
                name="capacity (this direction)",
                marker=dict(size=11, color=ENVELOPE, symbol="circle-open",
                            line=dict(width=2)),
                hovertemplate="V = %{x:.1f} kN<br>T = %{y:.1f} kNm<extra></extra>"))
            ok = s <= 1.0 + 1e-9
            fig.add_annotation(
                x=v_ed, y=t_ed, ax=30, ay=26, showarrow=True, arrowhead=2,
                arrowsize=0.7, arrowwidth=1, arrowcolor=GUIDE_LINE,
                text=(f"sum = {s:.2f} ({'OK' if ok else 'over'})"
                      if show_verdict else f"sum = {s:.2f} (exploratory)"),
                font=dict(size=11, color=(ENVELOPE if (show_verdict and ok)
                                          else LOAD_POINT)))
    fig.add_trace(go.Scatter(
        x=[v_ed], y=[t_ed], mode="markers",
        marker=dict(size=11, color=LOAD_POINT, symbol="x"), name="applied",
        hovertemplate="V<sub>Ed</sub> = %{x:.1f} kN<br>T<sub>Ed</sub> = %{y:.1f} "
                      "kNm<extra></extra>"))
    fig.update_layout(
        title=title, template=_TEMPLATE, height=460,
        margin=dict(l=10, r=10, t=_LEGEND_TOP_M, b=_LEGEND_BOT_M),
        # Subscripted axis titles (V_Ed with a literal underscore is below the house
        # style; Plotly axis titles accept the same HTML as annotations).
        xaxis=dict(title=dict(text="V<sub>Ed</sub> (kN)", standoff=10), zeroline=True,
                   rangemode="tozero"),
        yaxis=dict(title="T<sub>Ed</sub> (kNm)", zeroline=True, rangemode="tozero"),
        legend=dict(orientation="h", yanchor="top", y=_legend_y(460), x=0.5,
                    xanchor="center"),
    )
    return fig


def tube_figure(outer, holes=None, tef_mm=0.0, ak_m2=None,
                title="Torsion tube", scale=1000.0, unit="mm"):
    """Thin-walled torsion tube (EN 1992-1-1 6.3.2): the concrete outline, the
    effective wall of thickness ``tef`` and the wall centre-line that encloses the
    torsion area ``Ak``. Geometry in metres; ``scale`` / ``unit`` draw it in mm by
    default. The centre-line and inner face reuse the engine's inward offset, so
    they match the tube the resistance was computed on.
    """
    from sector import torsion   # local import keeps viz free of a load-order cycle
    fig = go.Figure()
    # Guard with ``is None`` rather than a truth test: the section model stores rings
    # as NumPy arrays, whose truth value is ambiguous (as in section_figure).
    outer = [] if outer is None else list(outer)
    holes = [] if holes is None else list(holes)
    if len(outer) >= 3:
        ox, oy = _ring_xy([(p[0] * scale, p[1] * scale) for p in outer])
        fig.add_trace(go.Scatter(x=ox, y=oy, fill="toself", mode="lines",
                                 fillcolor=CONCRETE_FILL, line=dict(color=CONCRETE_LINE),
                                 name="outline", hoverinfo="skip"))
    for hole in holes:
        hx, hy = _ring_xy([(p[0] * scale, p[1] * scale) for p in hole])
        fig.add_trace(go.Scatter(x=hx, y=hy, fill="toself", mode="lines",
                                 fillcolor=HOLE_FILL, line=dict(color=CONCRETE_LINE, dash="dot"),
                                 name="void", hoverinfo="skip", showlegend=False))
    tef_m = (tef_mm or 0.0) / 1000.0
    have_tube = tef_m > 0.0 and len(outer) >= 3
    centre = torsion.offset_polygon_inward(outer, tef_m / 2.0) if have_tube else None
    inner = torsion.offset_polygon_inward(outer, tef_m) if have_tube else None
    if inner:
        ix, iy = _ring_xy([(p[0] * scale, p[1] * scale) for p in inner])
        fig.add_trace(go.Scatter(x=ix, y=iy, mode="lines",
                                 line=dict(color=CONCRETE_LINE, width=1, dash="dot"),
                                 name=f"inner wall face (tef = {tef_mm:.0f} mm)"))
    if centre:
        cx, cy = _ring_xy([(p[0] * scale, p[1] * scale) for p in centre])
        ak_txt = f" (Ak = {ak_m2 * 1.0e6:,.0f} mm2)" if ak_m2 else ""
        fig.add_trace(go.Scatter(x=cx, y=cy, mode="lines",
                                 line=dict(color=ENVELOPE, width=2, dash="dash"),
                                 name="wall centre-line" + ak_txt))
    fig.update_layout(
        title=title, template=_TEMPLATE, height=440,
        margin=dict(l=10, r=10, t=_LEGEND_TOP_M, b=_LEGEND_BOT_M),
        xaxis=dict(title=dict(text=f"x ({unit})", standoff=10), zeroline=True),
        yaxis=dict(title=f"y ({unit})", scaleanchor="x", scaleratio=1, zeroline=True),
        legend=dict(orientation="h", yanchor="top", y=_legend_y(440), x=0.5,
                    xanchor="center"),
    )
    return fig


def subtube_figure(subtubes, title="Torsion sub-tubes (6.3.1(3))"):
    """Component rectangles of a subdivided (compound) torsion section.

    Each sub-tube is drawn in its validated global ``(x, y)`` position at its true
    ``b x h`` (mm), with its wall centre-line and torsion utilisation. This makes the
    geometric partition used by the calculation directly auditable.
    """
    fig = go.Figure()
    subtubes = list(subtubes or [])
    if not subtubes:
        fig.update_layout(title=title, template=_TEMPLATE, height=340)
        return fig
    for i, s in enumerate(subtubes):
        b, h, tef = s["b_mm"], s["h_mm"], s["tube"]["tef"]
        cx, cy = s.get("x_mm", 0.0), s.get("y_mm", 0.0)
        xmin, xmax = cx - b / 2.0, cx + b / 2.0
        ymin, ymax = cy - h / 2.0, cy + h / 2.0
        role = "web" if i == 0 else f"part {i + 1}"
        fig.add_trace(go.Scatter(
            x=[xmin, xmax, xmax, xmin, xmin],
            y=[ymin, ymin, ymax, ymax, ymin],
            fill="toself", mode="lines", fillcolor=CONCRETE_FILL,
            line=dict(color=CONCRETE_LINE, width=2), name=role,
            customdata=[[cx, cy, b, h, s["t_ed"], s["trd"], s["util"]]] * 5,
            hovertemplate=(
                f"<b>{role}</b><br>"
                "centre (%{customdata[0]:.0f}, %{customdata[1]:.0f}) mm<br>"
                "b x h %{customdata[2]:.0f} x %{customdata[3]:.0f} mm<br>"
                "TEd %{customdata[4]:.2f} kNm<br>"
                "TRd %{customdata[5]:.2f} kNm<br>"
                "util %{customdata[6]:.1%}<extra></extra>"
            ),
            showlegend=False))
        if 0.0 < tef < min(b, h):            # wall centre-line, inset by tef/2
            fig.add_trace(go.Scatter(
                x=[xmin + tef / 2, xmax - tef / 2, xmax - tef / 2,
                   xmin + tef / 2, xmin + tef / 2],
                y=[ymin + tef / 2, ymin + tef / 2, ymax - tef / 2,
                   ymax - tef / 2, ymin + tef / 2],
                mode="lines", line=dict(color=ENVELOPE, width=1.5, dash="dash"),
                hoverinfo="skip", showlegend=False))
        util_txt = "inf" if not math.isfinite(s["util"]) else f"{s['util'] * 100:.0f}%"
        fig.add_annotation(
            x=cx, y=cy, showarrow=False,
            text=(f"<b>{role}</b><br>{b:.0f} x {h:.0f} mm<br>"
                  f"util {util_txt}"),
            font=dict(size=11, color=SCHEMATIC_INK), align="center")
    fig.update_layout(
        title=title, template=_TEMPLATE, height=420,
        margin=dict(l=10, r=10, t=40, b=36),
        xaxis=dict(title="x (mm)", zeroline=True),
        yaxis=dict(title="y (mm)", scaleanchor="x", scaleratio=1, zeroline=True),
        showlegend=False)
    return fig


def truss_figure(theta_deg, z_mm, legs=2.0, dia_mm=0.0, s_mm=0.0,
                 title="Variable-strut truss"):
    """Schematic of the variable-angle truss (EN 1992-1-1 6.2.3): the compression
    chord and the tension chord a lever arm ``z`` apart, an inclined concrete strut
    at angle ``theta``, and the vertical link ties at spacing ``s``. A schematic
    (equal aspect so the strut angle reads true), not drawn to section scale.
    """
    fig = go.Figure()
    z = max(z_mm or 0.0, 1.0)
    th = math.radians(theta_deg) if theta_deg else math.radians(45.0)
    cot = (1.0 / math.tan(th)) if math.tan(th) > 1.0e-9 else 1.0
    panel = z * cot                        # horizontal run of one strut
    L = panel * 1.3                        # a little chord beyond one strut panel
    fig.add_trace(go.Scatter(x=[0, L], y=[z, z], mode="lines",
                             line=dict(color=BAR_COMPRESSION, width=3),
                             name="compression chord"))
    fig.add_trace(go.Scatter(x=[0, L], y=[0, 0], mode="lines",
                             line=dict(color=BAR_TENSION, width=3),
                             name="tension chord"))
    fig.add_trace(go.Scatter(x=[0, panel], y=[0, z], mode="lines",
                             line=dict(color=CONCRETE_LINE, width=7), opacity=0.55,
                             name=f"strut {chr(0x3B8)} = {theta_deg:.1f} deg"))
    # Vertical link ties at spacing s (capped so a very small s stays legible).
    step = s_mm if (s_mm and s_mm > 0.0) else (L / 4.0)
    xs, x = [], 0.0
    while x <= L + 1.0e-6 and len(xs) < 30:
        xs.append(x)
        x += step
    tie_name = f"links (s = {s_mm:.0f} mm)" if s_mm else "links"
    for k, xv in enumerate(xs):
        fig.add_trace(go.Scatter(x=[xv, xv], y=[0, z], mode="lines",
                                 line=dict(color=LINK_LINE, width=1.5),
                                 name=tie_name, showlegend=(k == 0)))
    # Angle arc at the strut base (between the tension chord and the strut) so the
    # strut angle theta reads directly off the figure.
    ar = 0.34 * z
    t_arc = [th * i / 24.0 for i in range(25)]
    fig.add_trace(go.Scatter(x=[ar * math.cos(t) for t in t_arc],
                             y=[ar * math.sin(t) for t in t_arc], mode="lines",
                             line=dict(color=SCHEMATIC_INK, width=1.2),
                             hoverinfo="skip", showlegend=False))
    fig.add_annotation(x=ar * 1.3 * math.cos(th / 2.0), y=ar * 1.3 * math.sin(th / 2.0),
                       text=chr(0x3B8), showarrow=False,
                       font=dict(size=13, color=SCHEMATIC_INK))
    # z as a dimension arrow (double-headed) just right of the panel, not floating text.
    zx = L * 1.06
    for y_end, y_in in ((z, z * 0.82), (0.0, z * 0.18)):
        fig.add_annotation(x=zx, y=y_end, ax=zx, ay=y_in, axref="x", ayref="y",
                           showarrow=True, arrowhead=2, arrowsize=1.0, arrowwidth=1,
                           arrowcolor=SCHEMATIC_INK, text="")
    fig.add_annotation(x=zx, y=z / 2.0, text=f"z = {z:.0f} mm", showarrow=False,
                       xanchor="left", xshift=7, font=dict(size=11, color=SCHEMATIC_INK))
    fig.update_layout(
        title=title, template=_TEMPLATE, height=320,
        margin=dict(l=10, r=10, t=_LEGEND_TOP_M, b=_LEGEND_BOT_M),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False, scaleanchor="x", scaleratio=1),
        legend=dict(orientation="h", yanchor="top", y=_legend_y(320), x=0.5,
                    xanchor="center"),
    )
    return fig


def na_line_at(a, b, c, extent, bbox=None):
    """Endpoints of the line ``a*x + b*y + c = 0`` for drawing.

    ``(a, b)`` is the (unit) normal. The line's closest point to the origin is
    ``-c*(a, b)``; the segment runs along the line direction ``(-b, a)``.

    Without ``bbox`` the segment spans ``+/- extent`` about that closest point --
    which is anchored at the ORIGIN, so for a section drawn away from the origin
    (e.g. corner-at-(0,0) coordinates) the segment overshoots asymmetrically and
    the equal-aspect autoscale shrinks the section to fit it. Pass ``bbox``
    ``(xmin, ymin, xmax, ymax)`` (the section bounds) to clip the line to the box
    grown by an 8 percent margin instead, so the drawn segment always hugs the
    section. Falls back to the ``extent`` span if the line misses the box.
    """
    px, py = -c * a, -c * b
    if bbox is not None:
        xmin, ymin, xmax, ymax = bbox
        m = 0.08 * max(xmax - xmin, ymax - ymin, 1e-9)
        xmin, ymin, xmax, ymax = xmin - m, ymin - m, xmax + m, ymax + m
        # Clip P(t) = (px - t*b, py + t*a) to the box (slab intersection in t).
        t_lo, t_hi = -math.inf, math.inf
        for pos, d, lo, hi in ((px, -b, xmin, xmax), (py, a, ymin, ymax)):
            if abs(d) < 1e-12:
                if pos < lo or pos > hi:
                    t_lo, t_hi = math.inf, -math.inf   # parallel outside the slab
                    break
                continue                                # parallel inside: no bound
            t0, t1 = (lo - pos) / d, (hi - pos) / d
            t_lo = max(t_lo, min(t0, t1))
            t_hi = min(t_hi, max(t0, t1))
        if t_lo < t_hi and math.isfinite(t_lo) and math.isfinite(t_hi):
            return (px - t_lo * b, py + t_lo * a, px - t_hi * b, py + t_hi * a)
    return (px - extent * b, py + extent * a, px + extent * b, py - extent * a)


def plastic_halfplane(V_deg, na_x, na_y):
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


def elastic_halfplane(na_x, na_y, inside_xy):
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


def compression_zones(outer, halfplane):
    """Compression and tension zone polygons for a section split by a half-plane."""
    if halfplane is None:
        return None
    a, b, c = halfplane
    comp = geometry.clip_halfplane(outer, a, b, c)
    tens = geometry.clip_halfplane(outer, -a, -b, -c)
    zones = []
    if len(comp) >= 3:
        zones.append((comp.tolist(), COMP_ZONE_FILL, "compression zone"))
    if len(tens) >= 3:
        zones.append((tens.tolist(), TENS_ZONE_FILL, "tension side"))
    return zones or None


def halfplane_bar_colors(points, halfplane, kappa=0.0, prestrain=0.0):
    """Colour reinforcement by tension/compression at a plastic neutral-axis state.

    ``halfplane`` is the compression half-plane ``(a, b, c)`` from
    :func:`plastic_halfplane` (``a*x + b*y + c >= 0`` is the compression side, with
    ``(a, b)`` unit-norm so ``a*x + b*y + c`` is the signed distance ``d`` from the
    neutral axis). The section strain at a point (compression positive) is
    ``kappa*d``, so a bar's net strain (tension positive) is ``prestrain - kappa*d``.
    A non-negative net strain is tension (blue/plain), the rest compression
    (vermillion/x-pattern) -- matching the elastic view's stress-sign encoding.

    Mild bars pass ``prestrain = 0`` (their colour is just the neutral-axis side);
    tendons pass their locked-in prestrain ``IS`` so a tendon on the compression
    side still reads as tension when the prestrain dominates. ``points`` are given
    in the same (metre) units as the half-plane. Returns ``None`` for no half-plane.
    """
    if halfplane is None:
        return None
    points = list(points)
    a, b, c = halfplane
    if isinstance(prestrain, (list, tuple)):
        values = list(prestrain)
        if len(values) != len(points):
            raise ValueError("one prestrain value is required per point")
    else:
        values = [prestrain] * len(points)
    return [BAR_TENSION if value - kappa * (a * p[0] + b * p[1] + c) >= 0.0
            else BAR_COMPRESSION for p, value in zip(points, values)]
