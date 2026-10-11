"""Retained longitudinal section fields shared by screen and publications.

Coordinates are metres, strains are dimensionless and stresses are MPa.
The adapter evaluates accepted planes; it performs no equilibrium solve.
"""
from __future__ import annotations

import hashlib
import json
import math
import textwrap
from dataclasses import asdict, dataclass, is_dataclass
from html import escape
from numbers import Real

import numpy as np
import plotly.graph_objects as go
from plotly.colors import sample_colorscale

from sector import geometry
from sector.section import Section

PALETTE = [[0.0, "#b45309"], [0.25, "#e8b67b"],
           [0.5, "#f1f3f5"], [0.75, "#8bbbd9"], [1.0, "#005a8d"]]
PERMILLE = chr(0x2030)


class FieldUnavailable(ValueError):
    """The retained evidence cannot support a quantitative section map."""


def context_signature(inp, family):
    """Bind field evidence to the calculated geometry, materials and actions."""
    keys = ["outer", "holes", "bars", "tendons", "bar_elements", "tendon_elements",
            "concrete", "steel", "prestress", "bar_materials", "tendon_materials", "slab_density"]
    keys += (["P_pl", "Mx_pl", "My_pl", "plastic_case"] if family == "Plastic" else
             ["P_el_l", "Mx_el_l", "My_el_l", "P_el_s", "Mx_el_s", "My_el_s",
              "conc_Ec", "el_phi", "ns", "nl", "elastic_case"])
    def plain(value):
        if is_dataclass(value):
            return plain(asdict(value))
        if isinstance(value, dict):
            return {str(k): plain(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, np.ndarray)):
            return [plain(v) for v in value]
        if isinstance(value, np.generic):
            return value.item()
        return value
    record = {key: plain(inp.get(key)) for key in keys}
    # Descriptions and category labels can change while a verified bending
    # result is reused. Bind the numerical state and stable action identity.
    case_key = "plastic_case" if family == "Plastic" else "elastic_case"
    record[case_key] = {"id": (inp.get(case_key) or {}).get("id")}
    raw = json.dumps(record, sort_keys=True, allow_nan=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _number(value):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise FieldUnavailable("A required field value is unavailable.")
    value = float(value)
    if not math.isfinite(value):
        raise FieldUnavailable("A required field value is not finite.")
    return value


def _close(left, right):
    if not math.isclose(_number(left), _number(right), rel_tol=1e-8, abs_tol=1e-9):
        raise FieldUnavailable("The retained field and element evidence disagree.")


def _plane(state):
    if not state or state.get("converged") is not True:
        raise FieldUnavailable("A converged section state is required.")
    raw = state.get("raw_stress_plane") or {}
    return tuple(_number(raw.get(k)) for k in
                 ("sigma0_kpa", "gradient_x_kpa_per_m", "gradient_y_kpa_per_m"))


def at(plane, x, y):
    return plane[0] + plane[1] * x + plane[2] * y


@dataclass(frozen=True)
class SectionField:
    family: str
    state: str
    outer: tuple
    holes: tuple
    strain_plane: tuple
    stress_plane: tuple
    concrete: object
    elements: tuple
    caption: str
    density: bool = False

    def strain(self, x, y):
        return at(self.strain_plane, x, y)

    def stress(self, x, y):
        value = at(self.stress_plane, x, y)
        if self.family == "Plastic":
            return float(self.concrete.stress(value))
        return min(value, 0.0)

    def corners(self):
        return [(x, y) for ring in (self.outer, *self.holes) for x, y in ring]


def build_field(inp, result, *, family, duration="TOTAL"):
    """Reconcile one retained result with its geometry and material context."""
    try:
        if result.get("field_context") != context_signature(inp, family):
            raise FieldUnavailable("The field belongs to different or incomplete inputs. Calculate again.")
        if result.get("converged") is not True:
            raise FieldUnavailable("The calculation did not produce a converged field.")
        outer = tuple(tuple(_number(v) for v in p) for p in inp["outer"])
        holes = tuple(tuple(tuple(_number(v) for v in p) for p in ring)
                      for ring in inp.get("holes", ()))
        Section.from_polygon(outer, [], holes=holes).require_valid_geometry()
        density = bool(inp.get("slab_density"))
        if family == "Plastic":
            if result.get("axial_reachable") is not True:
                raise FieldUnavailable("The selected capacity state has no verified axial equilibrium.")
            strain_plane = tuple(-_number(result.get(k)) for k in
                                 ("strain_offset", "strain_gradient_x", "strain_gradient_y"))
            stress_plane = strain_plane
            concrete = inp["concrete"]
            rows = result["reinforcement_states"]
            state = f"Ultimate capacity at NA angle {_number(result['V']):.3g} deg"
            caption = ("Ultimate-capacity state at the selected neutral-axis angle. "
                       "Concrete stress uses the selected design law. Tendon material strain includes initial strain.")
        elif family == "Elastic":
            accepted = result["accepted_states"]
            long = _plane(accepted["long_term"])
            instant = _plane(accepted["instantaneous_combined"])
            ec = _number(inp["conc_Ec"]) * 1000.0
            if ec <= 0.0:
                raise FieldUnavailable("A positive concrete modulus is required.")
            superposition = result["superposition"]
            ns = _number(superposition["short_term_modular_ratio"])
            nl = _number(superposition["long_term_modular_ratio"])
            if ns <= 0 or nl < ns:
                raise FieldUnavailable("The retained modular ratios are invalid.")
            phi = nl / ns - 1.0
            _close(phi, inp["el_phi"])
            if duration == "TOTAL":
                strain_plane = tuple((short_value + phi * long_value) / (ec * 1000.0)
                                     for short_value, long_value in zip(instant, long))
                stress_plane = tuple(v / 1000.0 for v in instant)
            elif duration == "LONG":
                strain_plane = tuple(v * (1.0 + phi) / (ec * 1000.0) for v in long)
                stress_plane = tuple(v / 1000.0 for v in long)
            else:
                raise FieldUnavailable("Select TOTAL or LONG for the elastic field.")
            concrete = None
            rows = result["elements"]
            state = "Combined actions (TOTAL)" if duration == "TOTAL" else "Sustained actions (LONG)"
            caption = ("Compatible section strain includes retained long-term deformation. "
                       "Tendon material strain includes initial strain. Concrete stress uses the cracked elastic state. "
                       "The zero-strain and zero-concrete-stress lines can differ under creep.")
        else:
            raise FieldUnavailable("The field family is unavailable.")

        geometry_rows = [("Bar", i, p) for i, p in enumerate(inp.get("bars", ()))]
        geometry_rows += [("Tendon", i, p) for i, p in enumerate(inp.get("tendons", ()))]
        if len(rows) != len(geometry_rows):
            raise FieldUnavailable("The reinforcement field is incomplete.")
        elements = []
        for row, (kind, index, point) in zip(rows, geometry_rows):
            if row.get("element_type") != kind or row.get("element_no") != index + 1:
                raise FieldUnavailable("The reinforcement field identities disagree.")
            x, y, area = (_number(v) for v in point)
            _close(row["x_mm"], x * 1000.0)
            _close(row["y_mm"], y * 1000.0)
            _close(row["area_mm2"], area)
            if family == "Elastic":
                stress = _number(row["total_mpa" if duration == "TOTAL" else "long_mpa"])
                modulus = _number(row["modulus_mpa"])
                if modulus <= 0:
                    raise FieldUnavailable("A positive reinforcement modulus is required.")
                strain = stress / modulus
                initial = _number(row["locked_in_mpa"]) / modulus
            else:
                stress = _number(row["stress_mpa"])
                strain = _number(row["strain_permille"]) / 1000.0
                initial = _number(row["initial_strain_permille"]) / 1000.0
            _close(strain, at(strain_plane, x, y) + initial)
            elements.append(dict(id=str(row["element_id"]), kind=kind, x=x, y=y,
                                 area=area, strain=strain, stress=stress, initial=initial))
        field = SectionField(family, state, outer, holes, strain_plane, stress_plane,
                             concrete, tuple(elements), caption, density)
        corner_rows = result["concrete_corner_states" if family == "Plastic" else "concrete_corners"]
        if len(corner_rows) != len(field.corners()):
            raise FieldUnavailable("The concrete boundary evidence is incomplete.")
        for row, (x, y) in zip(corner_rows, field.corners()):
            _close(row["x_mm"], x * 1000)
            _close(row["y_mm"], y * 1000)
            if family == "Plastic":
                _close(row["strain_permille"], field.strain(x, y) * 1000)
                _close(row["stress_mpa"], field.stress(x, y))
            else:
                _close(row["strain_permille"], at(instant, x, y) / ec)
                _close(row["stress_mpa"], min(at(instant, x, y) / 1000, 0))
        return field
    except FieldUnavailable:
        raise
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
        raise FieldUnavailable("The saved result lacks consistent section-field evidence. Calculate again.") from exc


def _level_points(field, plane, level=0.0):
    if plane[1] == 0.0 and plane[2] == 0.0:
        return []
    points = set()
    for ring in (field.outer, *field.holes):
        for first, second in zip(ring, (*ring[1:], ring[0])):
            a, b = at(plane, *first) - level, at(plane, *second) - level
            if a == 0:
                points.add(first)
            if a * b < 0:
                t = a / (a - b)
                points.add((first[0] + t * (second[0] - first[0]),
                            first[1] + t * (second[1] - first[1])))
    return sorted(points, key=lambda p: -plane[2] * p[0] + plane[1] * p[1])


def _critical_strains(concrete):
    values = [0.0, -concrete.eps_c2, -concrete.eps_cu2]
    if concrete.curve == 1:
        fc = concrete.fck
        e0 = 51.0 * fc / (13.0 + fc)
        a, b, c = 750.0 * (e0 - fc), 200.0 * (.75 * fc - e0), 10.0 * e0
        discriminant = b * b - 4 * a * c
        roots = [-c / b] if a == 0 and b != 0 else []
        if a != 0 and discriminant >= 0:
            roots = [(-b + sign * math.sqrt(discriminant)) / (2 * a) for sign in (-1, 1)]
        values.extend(-r / 100 for r in roots if 0 < r < concrete.eps_c2 * 100)
    return values


def _concrete_values(field, quantity):
    function = field.strain if quantity == "strain" else field.stress
    factor = 1000.0 if quantity == "strain" else 1.0
    points = field.corners()
    if quantity == "stress" and field.family == "Plastic":
        for level in _critical_strains(field.concrete):
            points.extend(_level_points(field, field.stress_plane, level))
    return [(function(x, y) * factor, x, y) for x, y in points]


def extrema(field, quantity):
    """Return exact boundary extrema and discrete material extrema."""
    factor = 1000.0 if quantity == "strain" else 1.0
    values = _concrete_values(field, quantity)
    low, high = min(values), max(values)
    result = [("Concrete minimum", *low), ("Concrete maximum", *high)]
    for kind in ("Bar", "Tendon"):
        items = [r for r in field.elements if r["kind"] == kind]
        if items:
            for name, select in (("minimum", min), ("maximum", max)):
                row = select(items, key=lambda r: r[quantity])
                result.append((f"{kind} {name}: {row['id']}", row[quantity] * factor,
                               row["x"], row["y"]))
    return result


def limits(fields, quantity):
    """Symmetric limits shared by the requested comparison population."""
    concrete = []
    steel = []
    factor = 1000.0 if quantity == "strain" else 1.0
    for field in fields:
        concrete.extend(abs(value) for value, _, _ in _concrete_values(field, quantity))
        steel.extend(abs(r[quantity] * factor) for r in field.elements)
    cmax, smax = max(concrete, default=0.0), max(steel, default=0.0)
    if quantity == "strain":
        cmax = smax = max(cmax, smax)
    # A zero field needs a nonzero color range; the extrema still show exact zero.
    return (cmax or 1.0, smax or 1.0)


def field_pair(inp, result, *, family, point_index=None, duration="TOTAL"):
    """Build the same selected state and comparison scales for every medium."""
    if family == "Plastic":
        points = result.get("points") or []
        if type(point_index) is not int or not 0 <= point_index < len(points):
            raise FieldUnavailable("Select an available plastic capacity point.")
        selected = build_field(inp, points[point_index], family=family)
        population = []
        for point in points:
            try:
                population.append(build_field(inp, point, family=family))
            except FieldUnavailable:
                continue
    else:
        selected = build_field(inp, result, family=family, duration=duration)
        population = [build_field(inp, result, family=family, duration=d) for d in ("TOTAL", "LONG")]
    case = inp.get("plastic_case" if family == "Plastic" else "elastic_case") or {}
    case_label = str(case.get("id") or "Unnamed action")
    figures = [(quantity, section_field_figure(
        selected, quantity, scale_limits=limits(population, quantity),
        title=f"{case_label}: {quantity.capitalize()}")) for quantity in ("strain", "stress")]
    return selected, figures


def _polygon_trace(points, **kwargs):
    closed = [*points, points[0]]
    return go.Scatter(x=[p[0] * 1000 for p in closed],
                      y=[p[1] * 1000 for p in closed], mode="lines", **kwargs)


def _convex_boundary(points):
    """Return whether every non-collinear boundary turn has the same sign."""
    turns = []
    for a, b, c in zip(points, (*points[1:], points[0]), (*points[2:], *points[:2])):
        turns.append((b[0] - a[0]) * (c[1] - b[1])
                     - (b[1] - a[1]) * (c[0] - b[0]))
    return not (any(v > 0 for v in turns) and any(v < 0 for v in turns))


def section_field_figure(field, quantity, *, scale_limits=None, title=None):
    """Draw clipped display bands and discrete material markers on equal axes."""
    if quantity not in {"strain", "stress"}:
        raise ValueError("quantity must be strain or stress")
    factor = 1000.0 if quantity == "strain" else 1.0
    unit = PERMILLE if quantity == "strain" else "MPa"
    plane = field.strain_plane if quantity == "strain" else field.stress_plane
    function = field.strain if quantity == "strain" else field.stress
    cmax, smax = scale_limits or limits([field], quantity)
    if not all(math.isfinite(v) and v > 0 for v in (cmax, smax)):
        raise ValueError("color limits must be positive and finite")
    fig = go.Figure()
    projection = [at(plane, x, y) for x, y in field.outer]
    lower, upper = min(projection), max(projection)
    critical = _critical_strains(field.concrete) if field.family == "Plastic" else [0.0]
    edges = sorted(set([*np.linspace(lower, upper, 65),
                        *(v for v in critical if lower < v < upper)]))
    bands = [(lower, upper)] if lower == upper else list(zip(edges, edges[1:]))
    # Concave clipping can connect disjoint pieces with zero-area edges.
    # Fill them without strokes so those edges cannot color an open recess.
    band_width = 0.5 if _convex_boundary(field.outer) else 0.0
    for low, high in bands:
        polygon = geometry.clip_halfplane(field.outer, plane[1], plane[2], plane[0] - low)
        polygon = geometry.clip_halfplane(polygon, -plane[1], -plane[2], high - plane[0])
        if len(polygon) < 3:
            continue
        middle = (low + high) / 2.0
        value = middle if quantity == "strain" or field.family == "Elastic" else float(field.concrete.stress(middle))
        if quantity == "stress" and field.family == "Elastic":
            value = min(value, 0.0)
        value *= factor
        color = sample_colorscale(PALETTE, [max(0.0, min(1.0, 0.5 + value / (2 * cmax)))])[0]
        fig.add_trace(_polygon_trace(polygon.tolist(), fill="toself", fillcolor=color,
                                    line=dict(color=color, width=band_width), showlegend=False,
                                    hoverinfo="skip", name="Concrete display band"))
    if band_width == 0:
        # SVG fill antialiasing can also expose a weak clipping bridge. An
        # even-odd exterior mask keeps every pixel outside the original ring
        # empty, including open recesses, at any strain-plane orientation.
        xs = [p[0] * 1000 for p in field.outer]
        ys = [p[1] * 1000 for p in field.outer]
        pad = max(max(xs) - min(xs), max(ys) - min(ys))
        rectangle = ((min(xs) - pad, min(ys) - pad),
                     (max(xs) + pad, min(ys) - pad),
                     (max(xs) + pad, max(ys) + pad),
                     (min(xs) - pad, max(ys) + pad))
        ring = tuple(zip(xs, ys))
        path = " ".join("M " + " L ".join(f"{x},{y}" for x, y in points) + " Z"
                        for points in (rectangle, ring))
        fig.add_shape(type="path", path=path, fillrule="evenodd",
                      fillcolor="white", line_width=0, layer="above",
                      xref="x", yref="y")
    # White masks preserve the exact void boundaries for every display band.
    for hole in field.holes:
        fig.add_trace(_polygon_trace(hole, fill="toself", fillcolor="white",
                                    line=dict(color="#475569", width=1.2),
                                    showlegend=False, hoverinfo="skip"))
    fig.add_trace(_polygon_trace(field.outer, line=dict(color="#334155", width=1.5),
                                showlegend=False, hoverinfo="skip"))
    intersections = _level_points(field, plane)
    shown_zero = False
    for first, second in zip(intersections, intersections[1:]):
        midpoint = np.array([(first[0] + second[0]) / 2, (first[1] + second[1]) / 2])
        if (geometry._strictly_inside(midpoint, np.array(field.outer))
                and not any(geometry._strictly_inside(midpoint, np.array(h)) for h in field.holes)):
            fig.add_trace(go.Scatter(x=[first[0] * 1000, second[0] * 1000],
                                    y=[first[1] * 1000, second[1] * 1000], mode="lines",
                                    name="Zero section strain" if quantity == "strain" else "Concrete stress boundary",
                                    line=dict(color="#17212b", dash="dash", width=1.5),
                                    showlegend=not shown_zero, hoverinfo="skip"))
            shown_zero = True
    corners = field.corners()
    fig.add_trace(go.Scatter(x=[x * 1000 for x, y in corners],
                            y=[y * 1000 for x, y in corners], mode="markers",
                            marker=dict(size=5, color=[function(x, y) * factor for x, y in corners],
                                        coloraxis="coloraxis", line=dict(color="#334155", width=0.5)),
                            showlegend=False, name="Concrete boundary",
                            customdata=[function(x, y) * factor for x, y in corners],
                            hovertemplate=f"Concrete<br>x %{{x:.2f}} mm; y %{{y:.2f}} mm<br>%{{customdata:.5g}} {unit}<extra></extra>"))
    for kind, symbol in (("Bar", "circle"), ("Tendon", "diamond")):
        rows = [r for r in field.elements if r["kind"] == kind]
        if not rows:
            continue
        fig.add_trace(go.Scatter(
            x=[r["x"] * 1000 for r in rows], y=[r["y"] * 1000 for r in rows], mode="markers",
            name=kind + "s",
            marker=dict(symbol=symbol, size=12, color=[r[quantity] * factor for r in rows],
                        coloraxis="coloraxis" if quantity == "strain" else "coloraxis2",
                        line=dict(color="#17212b", width=1.2)),
            text=[escape(r["id"]) for r in rows],
            customdata=[[r["stress"], r["strain"] * 1000, r["initial"] * 1000] for r in rows],
            hovertemplate=(f"%{{text}}<br>x %{{x:.2f}} mm; y %{{y:.2f}} mm"
                           f"<br>Stress %{{customdata[0]:.4g}} MPa<br>Material strain %{{customdata[1]:.5g}} {PERMILLE}"
                           f"<br>Initial strain %{{customdata[2]:.5g}} {PERMILLE}<extra></extra>")))
    extent = max(max(p[0] for p in field.outer) - min(p[0] for p in field.outer),
                 max(p[1] for p in field.outer) - min(p[1] for p in field.outer)) * 1000
    xs, ys = [p[0] * 1000 for p in field.outer], [p[1] * 1000 for p in field.outer]
    def coloraxis(maximum, label, position):
        return dict(colorscale=PALETTE, cmin=-maximum, cmax=maximum,
                    colorbar=dict(title=dict(text=label, side="top"), x=position,
                                  len=0.72, thickness=14, tickformat=".4~g", outlinewidth=0))
    heading = title or f"{field.family}: {quantity.capitalize()}"
    subtitle = field.state
    if title:
        subtitle = field.family + ": " + subtitle
    if field.density:
        subtitle += "; slab-density points"
    # Wrap before escaping so a long action ID keeps every character and the
    # quantity suffix. Both maps retain the same title and geometry domains.
    heading_lines = textwrap.wrap(heading, 48, break_on_hyphens=False) or [""]
    subtitle_lines = textwrap.wrap(subtitle, 76, break_on_hyphens=False) or [""]
    title_html = "<br>".join(escape(line) for line in heading_lines)
    subtitle_html = "<br>".join(escape(line) for line in subtitle_lines)
    title_extra = 22 * (len(heading_lines) - 1) + 16 * (len(subtitle_lines) - 1)
    uniform = ""
    concrete_values = [v for v, _, _ in _concrete_values(field, quantity)]
    if min(concrete_values) == max(concrete_values):
        uniform = f"; uniform concrete value {concrete_values[0]:.4g} {unit}"
    if max(abs(v) for v in concrete_values) == 0 and not any(r[quantity] for r in field.elements):
        uniform += "; zero field uses a reference scale"
    fig.update_layout(
        title=dict(text=title_html + f"<br><sup>{subtitle_html}</sup>", font_size=18, x=0.06),
        template="plotly_white", paper_bgcolor="white", plot_bgcolor="white",
        height=610 + title_extra, width=760,
        margin=dict(l=65, r=225, t=95 + title_extra, b=120, autoexpand=False),
        xaxis=dict(title="x (mm)", range=[min(xs) - extent * .08, max(xs) + extent * .08], showgrid=False, zeroline=False, constrain="domain"),
        yaxis=dict(title="y (mm)", range=[min(ys) - extent * .08, max(ys) + extent * .08], showgrid=False, zeroline=False, scaleanchor="x", scaleratio=1),
        coloraxis=coloraxis(cmax, f"{'Section / steel<br>strain' if quantity == 'strain' else 'Concrete<br>stress'}<br>{unit}", 1.02),
        coloraxis2=coloraxis(smax, f"Bars and<br>tendons<br>{unit}", 1.24),
        legend=dict(orientation="h", y=-.16, x=0, font_size=12),
        annotations=[dict(text="Tension +; compression -" + uniform,
                          x=0, y=-.28, xref="paper", yref="paper", xanchor="left",
                          showarrow=False, font_size=11)],
        font=dict(family="Arial", size=14),
    )
    return fig
