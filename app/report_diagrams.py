"""Report figures reconstructed from retained calculation evidence."""
from __future__ import annotations

import math
import textwrap
from html import escape

import plotly.graph_objects as go

from sector.geometry import area_moments, clip_halfplane, points_inside_concrete
from sector.section import Section
from sector.serviceability import _rectangle_frame
import viz


class DiagramUnavailable(ValueError):
    """Retained operands cannot support the requested diagram."""


def _finite(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise DiagramUnavailable("A required numerical operand is unavailable.")
    value = float(value)
    if not math.isfinite(value):
        raise DiagramUnavailable("A required numerical operand is not finite.")
    return value


def _matches(actual, retained):
    if not math.isclose(actual, _finite(retained), rel_tol=1e-8, abs_tol=1e-10):
        raise DiagramUnavailable("The diagram does not match the retained effective area.")


def shear_face_text(component, face):
    """Name controlled face selections; preserve unknown input text literally."""
    if not isinstance(face, str):
        return str(face)
    if face == "auto":
        return "automatic selection"
    token = {"low": "negative", "high": "positive"}.get(face, face)
    if token in {"negative", "positive"}:
        return viz.directional_face_label(component, token)
    return str(face)


def action_inset_text(inp, family, case_id, *, capacity_only=False):
    """Show one current case's simultaneous signed external actions."""
    rows = ["<b>" + family + " action set</b>"]
    identity = str(case_id)
    if len(identity) > 48:
        rows.append("Case identity: see caption")
    else:
        rows.extend(escape(part) for part in textwrap.wrap(identity, width=24))
    if family == "Plastic":
        rows.append("N = " + f"{_finite(inp.get('P_pl')):.3g} kN")
        if capacity_only and not any(inp.get(k) for k in ("shear_on", "torsion_on", "combined_on")):
            rows.append("Capacity slice at this N")
        else:
            for key, symbol in (("Mx_pl", "M<sub>x</sub>"), ("My_pl", "M<sub>y</sub>")):
                rows.append(f"{symbol} = {_finite(inp.get(key)):.3g} kN m")
        if inp.get("shear_on"):
            components = inp.get("shear_components") or {}
            for axis in ("x", "y"):
                value = inp.get("shear_V" + axis)
                if value is None:
                    value = (components.get("v" + axis) or {}).get("signed_v_ed")
                if value is None and not components and "shear_Vx" not in inp and "shear_Vy" not in inp:
                    value = inp.get("shear_V") if inp.get("shear_axis") == {"x": "y", "y": "x"}[axis] else 0.0
                rows.append(f"V<sub>{axis}</sub> = {_finite(value):.3g} kN")
            for axis in ("x", "y"):
                face = inp.get("shear_face_" + axis)
                if face is not None:
                    rows.append(f"V<sub>{axis}</sub> face: {escape(shear_face_text('v' + axis, face))}")
        if inp.get("torsion_on"):
            signed = _finite(inp.get("torsion_T_signed", inp.get("torsion_T")))
            magnitude = _finite(inp.get("torsion_T"))
            if not math.isclose(abs(signed), abs(magnitude), rel_tol=1e-12, abs_tol=1e-12):
                raise DiagramUnavailable("The signed torsion input and its magnitude disagree.")
            rows.append(f"T = {signed:.3g} kN m")
    elif family == "Elastic":
        rows.append("TOTAL = long + short")
        for prefix, symbol, unit in (("P", "N", "kN"), ("Mx", "M<sub>x</sub>", "kN m"),
                                     ("My", "M<sub>y</sub>", "kN m")):
            value = _finite(inp.get(prefix + "_el_l")) + _finite(inp.get(prefix + "_el_s"))
            rows.append(f"{symbol} = {value:.3g} {unit}")
    else:
        raise DiagramUnavailable("The action family is unavailable.")
    rows.extend(("<br>Positive action convention:", "N: axial tension",
                 "M<sub>x</sub>: bottom-face tension", "M<sub>y</sub>: left-face tension"))
    return "<br>".join(rows)


def section_axes_figure(inp, *, action_inset=None):
    """Show the physical input geometry and its coordinate origin."""
    fig = viz.section_figure(
        inp.get("outer", []), inp.get("holes", []), inp.get("bars", []),
        tendons=inp.get("tendons", []), show_labels=True,
        bar_ids=[item.get("id") for item in inp.get("bar_elements", [])],
        tendon_ids=[item.get("id") for item in inp.get("tendon_elements", [])],
        title="Section coordinates and element IDs", scale=1000.0, unit="mm", height=520,
    )
    outer = inp.get("outer", [])
    if not outer:
        return fig
    xs, ys = zip(*outer)
    span = max(max(xs) - min(xs), max(ys) - min(ys))
    if min(xs) - 0.1 * span <= 0 <= max(xs) + 0.1 * span and min(ys) - 0.1 * span <= 0 <= max(ys) + 0.1 * span:
        fig.add_trace(go.Scatter(x=[0], y=[0], mode="markers+text", text=["O (0, 0)"],
                                 textposition="bottom left", marker=dict(symbol="cross", size=9, color="#374151"),
                                 showlegend=False, hoverinfo="skip"))
    else:
        fig.add_annotation(x=0, y=1.04, xref="paper", yref="paper", xanchor="left",
                           text="Input origin: (0, 0) mm, outside the displayed section", showarrow=False)
    fig.update_layout(margin=dict(t=90), title=dict(y=0.98, yanchor="top"))
    fig.update_xaxes(title_text="x (mm), positive to the right", tickformat=",.0f")
    fig.update_yaxes(title_text="y (mm), positive upwards", tickformat=",.0f")
    if action_inset:
        fig.update_xaxes(domain=[0, 0.59])
        fig.add_annotation(
            x=0.65, y=0.98, xref="paper", yref="paper", xanchor="left",
            yanchor="top", align="left", showarrow=False,
            text=action_inset, font=dict(size=14),
        )
    return fig


def _neutral_axis_segments(outer, holes, plane):
    """Intersect the accepted zero-stress line with the actual concrete rings."""
    gx = _finite(plane.get("gradient_x_kpa_per_m"))
    gy = _finite(plane.get("gradient_y_kpa_per_m"))
    offset = _finite(plane.get("sigma0_kpa"))
    magnitude = math.hypot(gx, gy)
    if magnitude == 0:
        return [], ("Zero reference-stress plane" if offset == 0
                    else "No neutral axis within the section")
    nx, ny, offset = gx / magnitude, gy / magnitude, offset / magnitude
    span = max(max(p[i] for p in outer) - min(p[i] for p in outer) for i in (0, 1))
    tolerance = max(span * 1e-12, 1e-15)
    crossings = []
    for ring in (outer, *holes):
        for a, b in zip(ring, (*ring[1:], ring[0])):
            da, db = nx * a[0] + ny * a[1] + offset, nx * b[0] + ny * b[1] + offset
            if abs(da) <= tolerance:
                crossings.append((float(a[0]), float(a[1])))
            if da * db < 0:
                ratio = da / (da - db)
                crossings.append((a[0] + ratio * (b[0] - a[0]),
                                  a[1] + ratio * (b[1] - a[1])))
    crossings.sort(key=lambda p: -ny * p[0] + nx * p[1])
    unique = []
    for point in crossings:
        if not unique or math.dist(point, unique[-1]) > tolerance:
            unique.append(point)
    segments = []
    for a, b in zip(unique, unique[1:]):
        midpoint = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        if points_inside_concrete([midpoint], outer, holes, tol=tolerance)[0]:
            segments.append((a, b))
    return segments, ("Neutral axis: accepted reference-stress plane" if segments
                      else "No neutral axis within the section")


def chord_comparison_figure(candidates):
    """Compare retained concurrent chord demand and capacity on one moment scale."""
    if not candidates:
        raise DiagramUnavailable("The concurrent chord candidates are unavailable.")
    names, demand, capacity = [], [], []
    for row in candidates:
        if row.get("valid") is not True or row.get("conditional") is not True:
            raise DiagramUnavailable("A chord has no accepted conditional capacity.")
        axis, low = row.get("axis"), row.get("tension_low")
        if axis not in {"x", "y"} or not isinstance(low, bool):
            raise DiagramUnavailable("A physical chord face is unavailable.")
        name = f"{axis}-axis: {viz.tension_face_label(low, axis)} face"
        if name in names:
            raise DiagramUnavailable("A physical chord face is duplicated.")
        names.append(name)
        demand.append(_finite(row.get("m_total")))
        capacity.append(_finite(row.get("m_rd")))
    if min(demand + capacity) < 0:
        raise DiagramUnavailable("Chord magnitudes must be non-negative.")
    fig = go.Figure()
    for name, values, color, symbol in (
        ("Combined demand", demand, "#b45309", "circle"),
        ("Conditional capacity", capacity, "#005a8d", "line-ns"),
    ):
        fig.add_trace(go.Scatter(x=values, y=names, mode="markers+text",
                                 marker=dict(color=color, symbol=symbol, size=13, line=dict(width=2)),
                                 text=[f"{v:.3g}" for v in values],
                                 textposition="bottom right" if name == "Combined demand" else "top right",
                                 name=name, cliponaxis=False))
    maximum = max(demand + capacity)
    fig.update_layout(title="Longitudinal chords at the selected member angle",
                      template="plotly_white", height=390, font=dict(size=14),
                      margin=dict(l=175, r=65, t=75, b=90),
                      legend=dict(orientation="h", x=0, y=-0.25),
                      xaxis=dict(title="Equivalent moment (kN m)", range=[0, maximum * 1.17 if maximum else 1],
                                 zeroline=True, zerolinecolor="#475569"),
                      yaxis=dict(autorange="reversed", showgrid=True))
    return fig


def crack_effective_area_figure(inp, crack, state, *, title):
    """Draw the exact retained bending band or rectangular perimeter area.

    The accepted stress plane supplies the signed depth direction. The reported
    angle alone is folded modulo180degrees and cannot identify the tension face.
    """
    area = crack.get("effective_area_operands") or {}
    if not state or state.get("converged") is not True:
        raise DiagramUnavailable("The accepted elastic state is unavailable.")
    kind = area.get("record_kind")
    outer = inp.get("outer", [])
    holes = inp.get("holes", [])
    section = Section.from_polygon(outer, [], holes=holes)
    section.require_valid_geometry()
    rings = section.integration_rings()
    eligible = crack.get("effective_reinforcement") or (
        crack.get("effective_reinforcement_2023") or {}
    ).get("elements")
    points = list(inp.get("bars", [])) + list(inp.get("tendons", []))
    if not eligible or len(eligible) != len(points):
        raise DiagramUnavailable("The retained reinforcement eligibility schedule is incomplete.")
    zones = []
    if kind == "CrackEffectiveArea2023Direct":
        frame = _rectangle_frame(section)
        if frame is None:
            raise DiagramUnavailable("The retained direct-tension area requires a solid rectangle.")
        origin, ux, uy, width, height = frame
        _matches(width, area.get("width"))
        _matches(height, area.get("height"))
        left = _finite(area.get("left_band"))
        right = width - _finite(area.get("right_band"))
        bottom = _finite(area.get("bottom_band"))
        top = height - _finite(area.get("top_band"))
        _matches(max(right - left, 0), area.get("inner_width"))
        _matches(max(top - bottom, 0), area.get("inner_height"))
        shaded = width * height - max(right - left, 0) * max(top - bottom, 0)
        if left >= right or bottom >= top:
            zones = [(outer, "#c6dce8", "Effective concrete area")]
        else:
            for rect in (
                [(0, 0), (left, 0), (left, height), (0, height)],
                [(right, 0), (width, 0), (width, height), (right, height)],
                [(left, 0), (right, 0), (right, bottom), (left, bottom)],
                [(left, top), (right, top), (right, height), (left, height)],
            ):
                polygon = [tuple(origin + u * ux + v * uy) for u, v in rect]
                zones.append((polygon, "#c6dce8", "Effective concrete area"))
        def inside(x, y):
            delta = (x - origin[0], y - origin[1])
            u = delta[0] * ux[0] + delta[1] * ux[1]
            v = delta[0] * uy[0] + delta[1] * uy[1]
            tolerance = max(width, height) * 1e-8 + 1e-10
            return u <= left + tolerance or u >= right - tolerance or v <= bottom + tolerance or v >= top - tolerance
        direction_note = "Retained perimeter bands for direct tension"
    elif kind in {"CrackEffectiveArea2005Fine", "CrackEffectiveArea2005Coarse", "CrackEffectiveArea2023Bending"}:
        if not state or state.get("converged") is not True:
            raise DiagramUnavailable("The accepted elastic state is unavailable.")
        plane = state.get("raw_stress_plane") or {}
        gx = _finite(plane.get("gradient_x_kpa_per_m"))
        gy = _finite(plane.get("gradient_y_kpa_per_m"))
        magnitude = math.hypot(gx, gy)
        if magnitude <= 0:
            raise DiagramUnavailable("The retained bending direction is unavailable.")
        gx, gy = gx / magnitude, gy / magnitude
        boundary = _finite(area.get("band_limit_axis" if kind.endswith("Coarse") else "band_limit"))
        height = max(gx * x + gy * y for x, y in outer) - boundary
        _matches(height, area.get("selected_hc_eff"))
        clipped = [clip_halfplane(ring, gx, gy, -boundary) for ring in rings]
        shaded = sum(area_moments(ring).area for ring in clipped)
        if len(clipped[0]) >= 3:
            zones.append((clipped[0], "#c6dce8", "Effective concrete area"))
        def inside(x, y):
            return gx * x + gy * y >= boundary - 1e-12
        direction_note = (f"Tension direction: {math.degrees(math.atan2(gy, gx)):.1f} deg from +x, counterclockwise"
                          f"<br>Effective tension depth: {height * 1000:.3g} mm")
    else:
        raise DiagramUnavailable("The effective-area construction is unavailable.")
    _matches(shaded, area.get("ac_eff"))
    _matches(shaded, crack.get("ac_eff"))
    indices = set()
    included, excluded = [], []
    for row in eligible:
        index = row.get("element_index")
        if isinstance(index, bool) or not isinstance(index, int) or index in indices or not 0 <= index < len(points):
            raise DiagramUnavailable("The retained element index is invalid.")
        indices.add(index)
        x, y = points[index][:2]
        if not isinstance(row.get("in_effective_area"), bool) or inside(x, y) != row["in_effective_area"]:
            raise DiagramUnavailable("The diagram and retained element eligibility disagree.")
        (included if row["in_effective_area"] else excluded).append((x, y, str(row.get("element_id", index + 1)), index >= len(inp.get("bars", []))))
    fig = viz.section_figure(outer, holes, zones=zones, title=title, scale=1000, unit="mm", height=540)
    # Only one legend entry is needed when a perimeter consists of four bands.
    shown = False
    for trace in fig.data:
        if trace.name == "Effective concrete area":
            # A clipped concave ring can contain a zero-area bridge. Its fill is
            # valid, but a stroke would draw through an open recess.
            trace.line.width = 0
            trace.showlegend = not shown
            shown = True
    xs, ys = zip(*[(x * 1000, y * 1000) for x, y in outer])
    pad = max(max(xs) - min(xs), max(ys) - min(ys)) * 0.08
    rectangle = [(min(xs) - pad, min(ys) - pad), (max(xs) + pad, min(ys) - pad),
                 (max(xs) + pad, max(ys) + pad), (min(xs) - pad, max(ys) + pad)]
    path = " ".join("M " + " L ".join(f"{x},{y}" for x, y in ring) + " Z"
                    for ring in (rectangle, list(zip(xs, ys))))
    fig.add_shape(type="path", path=path, fillrule="evenodd", fillcolor="white",
                  line_width=0, layer="above", xref="x", yref="y")
    fig.update_xaxes(range=[min(xs) - pad, max(xs) + pad])
    fig.update_yaxes(range=[min(ys) - pad, max(ys) + pad])
    for rows, name, symbol, color in (
        (included, "Included reinforcement", "circle", "#005a8d"),
        (excluded, "Other reinforcement", "circle-open", "#6b7280"),
    ):
        if rows:
            fig.add_trace(go.Scatter(x=[r[0] * 1000 for r in rows], y=[r[1] * 1000 for r in rows],
                                     mode="markers", marker=dict(symbol=[("diamond" if r[3] else "circle") + ("-open" if symbol.endswith("-open") else "") for r in rows], color=color, size=10, line=dict(width=1.5)),
                                     name=name, customdata=[r[2] for r in rows], hovertemplate="%{customdata}<extra></extra>"))
    governing = crack.get("governing_candidate") or {}
    if governing.get("x_mm") is not None and governing.get("y_mm") is not None:
        fig.add_annotation(x=_finite(governing["x_mm"]), y=_finite(governing["y_mm"]),
                           text="Governing: " + escape(str(crack.get("element_id", ""))),
                           ax=35, ay=-35, arrowhead=2, bgcolor="white", borderpad=3)
    segments, neutral_note = _neutral_axis_segments(outer, holes, state.get("raw_stress_plane") or {})
    for index, (a, b) in enumerate(segments):
        fig.add_trace(go.Scatter(
            x=[a[0] * 1000, b[0] * 1000], y=[a[1] * 1000, b[1] * 1000],
            mode="lines", line=dict(color="#374151", dash="dash", width=2),
            name="Neutral axis", showlegend=index == 0, hoverinfo="skip",
        ))
    notes = [direction_note, f"Effective area: {shaded * 1e6:.3f} mm<sup>2</sup>"]
    cover = governing.get("cover")
    if cover is not None:
        cover = _finite(cover)
        _matches(cover, crack.get("cover"))
        source = governing.get("cover_source", crack.get("cover_source"))
        source = {"geometry": "geometry-derived", "override": "entered override"}.get(source, "retained value")
        notes[-1] += f"; governing clear cover: {cover:.3g} mm ({source})"
    if not segments:
        notes.append(neutral_note)
    fig.add_annotation(x=0, y=1.04, xref="paper", yref="paper", xanchor="left", yanchor="bottom", showarrow=False,
                       text="<br>".join(notes), align="left")
    fig.update_layout(margin=dict(l=65, r=35, t=145, b=100), legend=dict(orientation="h", y=-0.18))
    return fig
