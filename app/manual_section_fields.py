"""Native worked fields for the manual's stress and strain maps."""
from functools import lru_cache

import numpy as np
import plotly.graph_objects as go
from section_fields import SectionField, section_field_figure

from sector.elastic import solve_elastic_combined
from sector.plastic import solve_plastic
from sector.section import Section


@lru_cache(maxsize=2)
def worked_field(family):
    import manual
    if family == "Plastic":
        ex = manual.example_circular()
        section = Section.from_polygon(ex["outer"], ex["bars"], holes=ex["holes"],
                                       tendons_xy_area_mm2=ex["tendons"])
        point = solve_plastic(section, ex["concrete"], ex["steel"], ex["P"], 45, 45, 15,
                              prestress=ex["prestress"])[0]
        if not point.converged or not point.axial_reachable:
            raise ValueError("Manual plastic field did not converge")
        strain = (-point.strain_offset, -point.strain_gradient_x, -point.strain_gradient_y)
        elements = []
        for kind, rows in (("Bar", point.bar_states), ("Tendon", point.tendon_states)):
            for row in rows:
                elements.append(dict(id=f"{kind} {row.element_index + 1}", kind=kind,
                                     x=row.x, y=row.y, area=row.area * 1e6,
                                     strain=row.material_strain, stress=row.material_stress,
                                     initial=row.initial_strain))
        return SectionField("Plastic", "Ultimate capacity: N = −1500 kN; neutral-axis angle = 45°",
                            tuple(map(tuple, ex["outer"])), tuple(tuple(map(tuple, h)) for h in ex["holes"]),
                            strain, strain, ex["concrete"], tuple(elements), "")
    ex = manual.example_beam()
    section = Section.from_polygon(ex["outer"], ex["bars"])
    es, ec, phi = ex["steel"].Es, 35000.0, 2.0
    ns = es / ec
    result = solve_elastic_combined(section, 0, 100, 0, ns * (1 + phi), 0, 50, 0, ns)
    if not result.converged:
        raise ValueError("Manual elastic field did not converge")
    strain = tuple((short_value + phi * long_value) / (ec * 1000) for short_value, long_value in
                   zip(result.short_term.raw_stress_plane, result.long.raw_stress_plane))
    stress = tuple(v / 1000 for v in result.short_term.raw_stress_plane)
    elements = tuple(dict(id=f"Bar {i + 1}", kind="Bar", x=p[0], y=p[1], area=p[2],
                          strain=float(s) / (es * 1000), stress=float(s) / 1000, initial=0.)
                     for i, (p, s) in enumerate(zip(ex["bars"], result.bar_stress_total)))
    return SectionField("Elastic", "TOTAL: sustained Mₓ = 100 kN·m; additional Mₓ = 50 kN·m; φ = 2",
                        tuple(map(tuple, ex["outer"])), (), strain, stress, None, elements, "")


def _figure(family, quantity):
    field = worked_field(family)
    figure = section_field_figure(field, quantity)
    # The static illustration has a documented display precision of ten
    # significant digits, with absolute values below 1e-12 displayed as zero.
    # Apply it to every numeric plot attribute, including
    # hover data and scale limits, so native BLAS last bits cannot alter the
    # asset identity. Retained solver values and validation stay unchanged.
    def display(value):
        if isinstance(value, dict):
            return {key: display(item) for key, item in value.items()}
        if isinstance(value, (tuple, list, np.ndarray)):
            return [display(item) for item in value]
        if isinstance(value, (float, np.floating)):
            return float(f"{value:.10g}") if abs(value) >= 1e-12 else 0.0
        return value
    return go.Figure(display(figure.to_plotly_json()))


def fig_plastic_strain_map():
    return _figure("Plastic", "strain")


def fig_plastic_stress_map():
    return _figure("Plastic", "stress")


def fig_elastic_strain_map():
    return _figure("Elastic", "strain")


def fig_elastic_stress_map():
    return _figure("Elastic", "stress")
