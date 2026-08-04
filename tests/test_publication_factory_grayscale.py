"""Independent grayscale contract for Sector-owned Plotly factories."""

from __future__ import annotations

import pathlib
import sys
from types import SimpleNamespace as NS

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import viz
from sector.materials import Concrete, MildSteel, Prestress


def _first(value, default=None):
    if isinstance(value, (list, tuple)):
        return value[0] if value else default
    if hasattr(value, "tolist"):
        converted = value.tolist()
        if isinstance(converted, list):
            return converted[0] if converted else default
        return converted
    return default if value is None else value


def _visible_legend_traces(figure):
    if figure.layout.showlegend is False:
        return []
    return [
        trace
        for trace in figure.data
        if trace.visible is not False
        and trace.showlegend is not False
        and str(trace.name or "").strip()
    ]


def _visible_non_colour_cue(trace):
    if trace.type == "bar":
        pattern = trace.marker.pattern
        return ("bar", pattern.shape or "solid")

    mode = str(trace.mode or "")
    line = None
    if "lines" in mode:
        width = 2.0 if trace.line.width is None else float(trace.line.width)
        if width > 0.0:
            line = (trace.line.dash or "solid", width)

    marker = None
    if "markers" in mode:
        opacity = float(_first(trace.marker.opacity, 1.0))
        size = float(_first(trace.marker.size, 6.0))
        if opacity > 0.0 and size > 0.0:
            marker = (_first(trace.marker.symbol, "circle"), size)

    fill = trace.fill not in (None, "none")
    return ("scatter", fill, line, marker)


def _fatigue_inputs():
    steel_bin = NS(
        bin_name="FAT-1",
        cycles=2.0e5,
        design_stress_range_mpa=75.0,
        cycles_to_failure=3.0e6,
        damage=2.0e5 / 3.0e6,
    )
    steel = NS(
        element_id="R1",
        bins=(steel_bin,),
        damage_utilisation=steel_bin.damage,
        yield_utilisation=0.42,
        utilisation=0.42,
    )
    concrete_bin = NS(bin_name="FAT-1", cycles=2.0e5, damage=0.12)
    concrete = NS(
        fibre_index=4,
        x_m=0.2,
        y_m=-0.3,
        bins=(concrete_bin,),
        damage=0.12,
        damage_utilisation=0.12,
        stress_utilisation=1.08,
        utilisation=1.08,
    )
    search = NS(
        x_m=0.2,
        y_m=-0.3,
        upper_damage=0.13,
        converged=True,
    )
    spectrum = NS(
        spectrum_name="Traffic A",
        reinforcement=(steel,),
        concrete=(concrete,),
        concrete_search=search,
    )
    properties = NS(
        n_star=2.0e6,
        k1=5.0,
        k2=9.0,
        delta_sigma_rsk_mpa=130.0,
    )
    return spectrum, steel, properties


def _factory_figures():
    outer = [(-0.2, -0.3), (0.2, -0.3), (0.2, 0.3), (-0.2, 0.3)]
    bars = [(-0.1, -0.25, 314.0), (0.1, -0.25, 314.0)]
    bar_elements = [
        {"id": "R1", "x_mm": -100.0, "y_mm": -250.0,
         "diameter_mm": 20.0},
        {"id": "R2", "x_mm": 100.0, "y_mm": -250.0,
         "diameter_mm": 20.0},
    ]
    zones = [
        ([(-0.2, 0.0), (0.2, 0.0), (0.2, 0.3), (-0.2, 0.3)],
         viz.COMP_ZONE_FILL, "compression zone"),
        ([(-0.2, -0.3), (0.2, -0.3), (0.2, 0.0), (-0.2, 0.0)],
         viz.TENS_ZONE_FILL, "tension side"),
    ]
    corners = [
        {"point_no": 1, "ring": "Outer", "x_mm": -100.0, "y_mm": -200.0,
         "strain_permille": -0.5},
        {"point_no": 2, "ring": "Outer", "x_mm": 100.0, "y_mm": 200.0,
         "strain_permille": 1.0},
    ]
    elements = [
        {"element_type": "Bar", "element_id": "R1", "x_mm": 0.0,
         "y_mm": -150.0, "strain_permille": 0.8, "total_mpa": 160.0},
        {"element_type": "Tendon", "element_id": "P1", "x_mm": 0.0,
         "y_mm": 150.0, "strain_permille": 4.0, "total_mpa": 780.0},
    ]
    spectrum, steel_fatigue, fatigue_properties = _fatigue_inputs()
    prestress = Prestress(
        curve=7, IS=0.006, fytk=1600.0, futk=1860.0, eut=0.035,
        k=0.9, ey0t=0.002, gamma_y=1.15, gamma_u=1.15, gamma_E=1.0,
    )
    spacing = {
        "status": "FAIL",
        "first_id": "R1",
        "second_id": "R2",
        "phi_first_mm": 20.0,
        "phi_second_mm": 20.0,
        "clear_mm": 180.0,
        "required_mm": 205.0,
    }
    subtube = {
        "tube": {"tef": 100.0, "Ak": 0.10},
        "b_mm": 300.0,
        "h_mm": 600.0,
        "x_mm": 0.0,
        "y_mm": 0.0,
        "stiffness": 0.003,
        "t_ed": 24.6,
        "trd": 90.0,
        "util": 0.27,
        "governs": "stirrups",
    }

    return {
        "elastic strain": viz.elastic_strain_figure(
            corners, elements, (-10_000.0, 0.0, 50_000.0), ec_mpa=30_000.0
        ),
        "concrete law": viz.concrete_curve_figure(
            Concrete(fck=35.0, gamma_c=1.5, curve=2)
        ),
        "prestress law": viz.prestress_curve_figure(prestress),
        "steel law": viz.steel_curve_figure(
            MildSteel(fytk=500.0, fyck=500.0)
        ),
        "section state": viz.section_figure(
            outer,
            bars=[(0.0, -0.2)],
            bar_colors=[viz.BAR_TENSION],
            tendons=[(0.0, 0.2)],
            tendon_colors=[viz.BAR_COMPRESSION],
            zones=zones,
        ),
        "fatigue utilisation": viz.fatigue_utilisation_map_figure(
            outer,
            [],
            [{"id": "R1", "x_mm": 0.0, "y_mm": -220.0}],
            [],
            spectrum,
        ),
        "fatigue S-N": viz.fatigue_sn_figure(
            steel_fatigue, fatigue_properties, gamma_s=1.15
        ),
        "fatigue damage": viz.fatigue_damage_figure(steel_fatigue),
        "detailing": viz.detailing_geometry_figure(
            outer,
            [],
            bars,
            [],
            bar_elements=bar_elements,
            highlight_ids=["R1"],
            spacing_pair=spacing,
            tension_zone={
                "tension_direction": [-2 ** -0.5, -2 ** -0.5],
                "neutral_c_m": 0.0,
            },
        ),
        "shear geometry": viz.shear_geometry_figure(
            outer,
            [],
            bars,
            axis="x",
            tension_low=True,
            centroid=(0.0, 0.0),
            asl_bar_ids=[1, 2],
            asl_cg_m=-0.25,
            asl_mm2=628.0,
            d_mm=550.0,
            z_mm=495.0,
            bw_mm=400.0,
            bw_source="auto",
        ),
        "biaxial shear": viz.biaxial_shear_overview_figure(
            outer, vx_ed=-40.0, vy_ed=25.0
        ),
        "M-M interaction": viz.interaction_figure(
            [100.0, 0.0, -100.0], [0.0, 100.0, 0.0], applied=(20.0, 30.0)
        ),
        "N-M interaction": viz.interaction_nm_figure(
            [0.0, -500.0, 500.0], [200.0, 0.0, 0.0], applied=(0.0, 50.0)
        ),
        "V-T interaction": viz.vt_interaction_figure(600.0, 80.0, 100.0, 30.0),
        "torsion tube": viz.tube_figure(outer, tef_mm=90.0, ak_m2=0.09),
        "torsion subtube": viz.subtube_figure([subtube]),
        "variable-strut truss": viz.truss_figure(30.0, 495.0, s_mm=150.0),
    }


def test_all_sector_factory_legends_have_unique_visible_non_colour_cues():
    figures = _factory_figures()

    assert len(figures) == 17
    for family, figure in figures.items():
        traces = _visible_legend_traces(figure)
        cues = [_visible_non_colour_cue(trace) for trace in traces]
        assert all(
            cue != ("scatter", False, None, None) for cue in cues
        ), family
        assert len(cues) == len(set(cues)), family


def test_section_zones_and_state_keys_use_visible_independent_channels():
    section = _factory_figures()["section state"]
    compression = next(t for t in section.data if t.name == "compression zone")
    tension = next(t for t in section.data if t.name == "tension side")
    tension_key = next(
        t for t in section.data if t.name == "tension (+): plain marker"
    )
    compression_key = next(
        t for t in section.data if t.name == "compression (-): x marker"
    )

    assert compression.line.width > 0.0 and tension.line.width > 0.0
    assert compression.line.dash != tension.line.dash
    assert tension_key.marker.symbol == "square"
    assert compression_key.marker.symbol == "square-x"


def test_detailing_and_truss_semantics_are_authored_not_colour_only():
    figures = _factory_figures()
    detailing = figures["detailing"]
    included = next(t for t in detailing.data if t.name == "included reinforcement")
    spacing = next(t for t in detailing.data if t.name == "governing spacing pair")
    assert included.marker.symbol == "circle-open"
    assert spacing.marker.symbol == "diamond-open"

    truss = figures["variable-strut truss"]
    compression = next(t for t in truss.data if t.name == "compression chord")
    tension = next(t for t in truss.data if t.name == "tension chord")
    links = next(t for t in truss.data if str(t.name).startswith("links"))
    assert compression.line.dash in (None, "solid")
    assert tension.line.dash == "dash"
    assert links.line.dash == "dot"
