"""Independent native-result and geometry checks for quantitative section maps."""
import ast
import copy
from dataclasses import replace
from html import unescape
from pathlib import Path

import numpy as np
import pytest

from app import section_fields as fields
from sector import geometry, sls
from sector.elastic import solve_elastic_combined
from sector.materials import Concrete, MildSteel, Prestress
from sector.plastic import solve_plastic
from sector.section import Section


def adapters():
    source = Path(__file__).resolve().parents[1] / "app" / "sector_app.py"
    names = {"_plastic_point_result", "_elastic_state_result", "_elastic_resultant_result"}
    nodes = [n for n in ast.parse(source.read_text(encoding="utf-8")).body
             if isinstance(n, ast.FunctionDef) and n.name in names]
    namespace = {"_MM": 1000.0, "section_fields": fields}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), namespace)
    return namespace


def native_case(phi=2.0, tendon=True, curve=2, *, mixed=False,
                actions=(0, 50, 5, 0, 20, -2), steel_curve=2, tendon_curve=6,
                compression=True):
    outer = [(-.15, -.3), (.15, -.3), (.15, .3), (-.15, .3)]
    bars = [(-.1, -.25, 500), (.1, -.25, 500), (-.1, .25, 200), (.1, .25, 200)]
    tendons = [(0, -.2, 150)] if tendon else []
    concrete = Concrete(40, 1.45, curve=curve)
    steel = MildSteel(550, 550, futk=600, curve=steel_curve, active_in_compression=compression)
    prestress = Prestress(curve=tendon_curve, IS=.004, Es=195000, fytk=1600, futk=1860, eut=.035)
    bar_laws = [steel] * 4
    if mixed:
        bar_laws = [replace(steel, Es=180000), steel, replace(steel, Es=210000), steel]
    ec, ns = 35000., steel.Es / 35000.
    inp = dict(outer=outer, holes=[], bars=bars, tendons=tendons, concrete=concrete,
               steel=steel, prestress=prestress, bar_materials=bar_laws,
               tendon_materials=[prestress] * len(tendons), el_phi=phi,
               conc_Ec=ec / 1000, ns=ns, nl=ns * (1 + phi),
               elastic_case={"id": "SLS1"}, plastic_case={"id": "ULS1"},
               P_el_l=actions[0], Mx_el_l=actions[1], My_el_l=actions[2],
               P_el_s=actions[3], Mx_el_s=actions[4], My_el_s=actions[5])
    section = Section.from_polygon(outer, bars, tendons_xy_area_mm2=tendons)
    pts = solve_plastic(section, concrete, steel, 0, 90, 90, 15, prestress=prestress,
                        bar_materials=bar_laws)
    plastic = adapters()["_plastic_point_result"](pts[0], inp)
    elastic_section = Section.from_polygon(outer, bars + tendons)
    multipliers = np.array([law.Es / steel.Es for law in bar_laws] + ([prestress.Es / steel.Es] if tendon else []))
    locked = np.array([0.] * 4 + ([prestress.Es * prestress.IS * 1000] if tendon else []))
    result = solve_elastic_combined(elastic_section, *actions[:3], inp["nl"], *actions[3:], ns,
                                    n_mult=multipliers, prestress_stress=locked)
    rows = sls.element_rows(bars, tendons, total=result.bar_stress_total / 1000,
                            long=result.bar_stress_long / 1000, dif=result.bar_stress_dif / 1000,
                            rst1=result.bar_stress_rst1 / 1000, es_mpa=[law.Es for law in bar_laws], ep_mpa=prestress.Es)
    for row, initial in zip(rows, locked):
        row["locked_in_mpa"] = initial / 1000
    convert = adapters()["_elastic_state_result"]
    elastic = dict(converged=result.converged, field_context=fields.context_signature(inp, "Elastic"),
                   accepted_states=dict(long_term=convert(result.long), instantaneous_combined=convert(result.short_term)),
                   superposition=dict(long_term_modular_ratio=inp["nl"], short_term_modular_ratio=ns), elements=rows,
                   concrete_corners=sls.concrete_corner_rows(outer, [], stress_plane=result.short_term.raw_stress_plane, ec_mpa=ec))
    return inp, elastic, plastic, result


@pytest.mark.parametrize("phi", [0., 2.])
@pytest.mark.parametrize("tendon", [False, True])
@pytest.mark.parametrize("duration", ["TOTAL", "LONG"])
def test_elastic_compatible_plane_matches_native_material_strains(phi, tendon, duration):
    inp, elastic, _, native = native_case(phi, tendon)
    field = fields.build_field(inp, elastic, family="Elastic", duration=duration)
    native_stresses = native.bar_stress_total if duration == "TOTAL" else native.bar_stress_long
    for index, element in enumerate(field.elements):
        modulus = inp["steel"].Es if element["kind"] == "Bar" else inp["prestress"].Es
        assert element["stress"] == pytest.approx(native_stresses[index] / 1000, abs=1e-12)
        assert element["strain"] == pytest.approx(native_stresses[index] / (1000 * modulus), abs=1e-15)
        assert field.strain(element["x"], element["y"]) + element["initial"] == pytest.approx(element["strain"], abs=1e-15)
    raw = native.short_term if duration == "TOTAL" else native.long
    for x, y in field.corners():
        assert field.stress(x, y) == pytest.approx(min((raw.eps0 + raw.kx*x + raw.ky*y) / 1000, 0), abs=1e-12)


@pytest.mark.parametrize("curve", [1, 2])
def test_plastic_native_states_and_interior_material_law(curve):
    inp, _, plastic, _ = native_case(curve=curve)
    field = fields.build_field(inp, plastic, family="Plastic")
    for y in np.linspace(-.3, .3, 37):
        expected = -(plastic["strain_offset"] + plastic["strain_gradient_y"] * y)
        assert field.strain(0, y) == expected
        assert field.stress(0, y) == inp["concrete"].stress(expected)
    assert field.elements[-1]["initial"] == .004


@pytest.mark.parametrize("change", ["context", "nan", "bool", "missing", "unconverged", "mismatch"])
def test_bad_evidence_is_unavailable(change):
    inp, elastic, _, _ = native_case()
    if change == "context":
        inp["conc_Ec"] += 1
    elif change == "nan":
        elastic["accepted_states"]["long_term"]["raw_stress_plane"]["sigma0_kpa"] = float("nan")
    elif change == "bool":
        elastic["elements"][0]["total_mpa"] = True
    elif change == "missing":
        elastic["elements"].pop()
    elif change == "unconverged":
        elastic["converged"] = False
    else:
        elastic["elements"][0]["x_mm"] += 1
    with pytest.raises(fields.FieldUnavailable):
        fields.build_field(inp, elastic, family="Elastic")


def test_cubic_concrete_interior_peak_is_in_extrema_and_limits():
    inp, _, plastic, _ = native_case()
    original = fields.build_field(inp, plastic, family="Plastic")
    field = replace(original, concrete=Concrete(12, curve=1), stress_plane=(-.00175, 0, -.00175 / .3))
    minimum = fields.extrema(field, "stress")[0]
    assert minimum[1] == pytest.approx(-12.517633136094674)
    assert fields.limits([field], "stress")[0] == pytest.approx(-minimum[1])


def test_concave_clip_bands_preserve_area_and_recess():
    inp, _, plastic, _ = native_case()
    field = fields.build_field(inp, plastic, family="Plastic")
    outer = ((-2., -2.), (2., -2.), (2., 2.), (1., 2.), (1., -1.), (-1., -1.), (-1., 2.), (-2., 2.))
    field = replace(field, outer=outer, holes=(), strain_plane=(0, 0, .001), elements=())
    figure = fields.section_field_figure(field, "strain")
    bands = [trace for trace in figure.data if trace.name == "Concrete display band"]
    area = sum(geometry.area_moments(list(zip(np.array(t.x)/1000, np.array(t.y)/1000))).area for t in bands)
    assert area == pytest.approx(10., abs=1e-12)
    for trace in bands:
        poly = np.array(list(zip(np.array(trace.x)/1000, np.array(trace.y)/1000)))
        assert not geometry._strictly_inside(np.array([0., 1.]), poly)


def test_shared_geometry_and_fixed_comparison_scales():
    inp, elastic, _, _ = native_case()
    field, figures = fields.field_pair(inp, elastic, family="Elastic")
    other, second = fields.field_pair(inp, elastic, family="Elastic", duration="LONG")
    assert field.strain_plane != other.strain_plane
    assert figures[0][1].layout.margin == figures[1][1].layout.margin
    for (_, first), (_, last) in zip(figures, second):
        assert first.layout.coloraxis == last.layout.coloraxis
        assert first.layout.coloraxis2 == last.layout.coloraxis2
        assert first.layout.yaxis.scaleanchor == "x"


def test_geometry_and_result_are_not_modified():
    inp, elastic, _, _ = native_case()
    before = copy.deepcopy((inp, elastic))
    fields.field_pair(inp, elastic, family="Elastic")
    assert (inp, elastic) == before


@pytest.mark.parametrize("value", [0., -.001, .001])
@pytest.mark.parametrize("quantity", ["strain", "stress"])
def test_uniform_fields_have_no_arbitrary_zero_contour(value, quantity):
    field = fields.SectionField("Elastic", "Uniform", ((-1., -1.), (1., -1.), (1., 1.), (-1., 1.)),
                                (), (value, 0., 0.), (value * 35000, 0., 0.), None, (), "")
    figure = fields.section_field_figure(field, quantity)
    assert not any(t.name in {"Zero section strain", "Concrete stress boundary"} for t in figure.data)
    assert "uniform concrete value" in figure.layout.annotations[0].text
    assert all(np.isfinite(t.x).all() and np.isfinite(t.y).all() for t in figure.data)
    assert fields.extrema(field, quantity)[0][1] == fields.extrema(field, quantity)[1][1]


def test_cosmetic_case_edits_reuse_fields_but_identity_and_actions_are_bound():
    inp, elastic, plastic, _ = native_case()
    for family, result, key in (("Plastic", plastic, "plastic_case"), ("Elastic", elastic, "elastic_case")):
        changed = copy.deepcopy(inp)
        changed[key].update(description="Revised description", type="Updated category")
        assert fields.build_field(changed, result, family=family)
        changed[key]["id"] = "Different action"
        with pytest.raises(fields.FieldUnavailable):
            fields.build_field(changed, result, family=family)
    inp["Mx_el_s"] += 1
    with pytest.raises(fields.FieldUnavailable):
        fields.build_field(inp, elastic, family="Elastic")


@pytest.mark.parametrize("actions", [(0, 50, 5, 0, -80, -10), (0, 50, 0, 0, 0, 0),
                                     (0, 0, 0, 0, 0, 0), (500, 0, 0, 200, 0, 0),
                                     (-500, 0, 0, -200, 0, 0)])
def test_mixed_moduli_and_action_patterns_match_native_states(actions):
    inp, elastic, _, native = native_case(mixed=True, actions=actions)
    for duration, stresses in (("TOTAL", native.bar_stress_total), ("LONG", native.bar_stress_long)):
        field = fields.build_field(inp, elastic, family="Elastic", duration=duration)
        moduli = [law.Es for law in inp["bar_materials"]] + [inp["prestress"].Es]
        for row, stress, modulus in zip(field.elements, stresses, moduli):
            assert row["strain"] == pytest.approx(stress / (1000 * modulus), abs=1e-15)
            assert field.strain(row["x"], row["y"]) + row["initial"] == pytest.approx(row["strain"], abs=1e-15)


@pytest.mark.parametrize("steel_curve", [1, 2, 3])
@pytest.mark.parametrize("compression", [True, False])
def test_plastic_bar_laws_use_retained_material_states(steel_curve, compression):
    inp, _, plastic, _ = native_case(steel_curve=steel_curve, compression=compression)
    field = fields.build_field(inp, plastic, family="Plastic")
    for row in field.elements[:4]:
        assert row["stress"] == pytest.approx(inp["steel"].stress(row["strain"]))


@pytest.mark.parametrize("tendon_curve", range(1, 8))
def test_plastic_tendon_laws_include_initial_strain(tendon_curve):
    inp, _, plastic, _ = native_case(tendon_curve=tendon_curve)
    field = fields.build_field(inp, plastic, family="Plastic")
    row = field.elements[-1]
    assert row["initial"] == .004
    assert row["stress"] == pytest.approx(inp["prestress"].stress(row["strain"]))


@pytest.mark.parametrize("reverse", [False, True])
def test_multiple_voids_keep_zero_line_out_of_voids(reverse):
    outer = ((-3., -2.), (3., -2.), (3., 2.), (-3., 2.))
    holes = (((-2., -1.), (-1., -1.), (-1., 1.), (-2., 1.)),
             ((1., -1.), (2., -1.), (2., 1.), (1., 1.)))
    if reverse:
        outer, holes = tuple(reversed(outer)), tuple(tuple(reversed(h)) for h in holes)
    field = fields.SectionField("Elastic", "Void fixture", outer, holes,
                                (0., 0., .001), (0., 0., 35.), None, (), "")
    figure = fields.section_field_figure(field, "strain")
    zero = [t for t in figure.data if t.name == "Zero section strain"]
    assert len(zero) == 3
    for trace in zero:
        midpoint = np.array([sum(trace.x) / 2000, sum(trace.y) / 2000])
        assert not any(geometry._strictly_inside(midpoint, np.array(h)) for h in holes)


def test_static_state_identity_and_density_markers():
    inp, elastic, _, _ = native_case()
    inp["slab_density"] = {"source": "tributary integration"}
    elastic["field_context"] = fields.context_signature(inp, "Elastic")
    field, figures = fields.field_pair(inp, elastic, family="Elastic", duration="LONG")
    assert field.density
    for _, figure in figures:
        assert "SLS1" in figure.layout.title.text
        assert "Elastic" in figure.layout.title.text
        assert "Sustained actions (LONG)" in figure.layout.title.text
        assert "Tension +; compression -" in figure.layout.annotations[0].text
        assert "slab-density points" in figure.layout.title.text
        assert any(t.name == "Bars" for t in figure.data)
        assert figure.layout.margin.autoexpand is False


def test_partial_sweep_does_not_publish_an_invalid_selected_point():
    inp, _, plastic, _ = native_case()
    invalid = dict(plastic, converged=False)
    result = {"points": [invalid, plastic]}
    with pytest.raises(fields.FieldUnavailable):
        fields.field_pair(inp, result, family="Plastic", point_index=0)
    _, figures = fields.field_pair(inp, result, family="Plastic", point_index=1)
    assert all("Ultimate capacity" in figure.layout.title.text for _, figure in figures)


def test_long_case_identity_wraps_before_escaping_without_losing_characters():
    inp, elastic, _, _ = native_case()
    name = "Case<" + "x" * 80 + ">&reference"
    inp["elastic_case"]["id"] = name
    elastic["field_context"] = fields.context_signature(inp, "Elastic")
    _, figures = fields.field_pair(inp, elastic, family="Elastic")
    for quantity, figure in figures:
        title = figure.layout.title.text
        heading = title.split("<sup>")[0].replace("<br>", "")
        assert unescape(heading) == f"{name}: {quantity.capitalize()}"
        assert "&lt;" in title and "&gt;" in title and "&amp;" in title
        assert figure.layout.margin.t > 95
    assert figures[0][1].layout.margin == figures[1][1].layout.margin

@pytest.mark.parametrize("shape", ["u", "c", "rectangle"])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("oblique", [False, True])
def test_display_bands_preserve_area_without_strokes_across_exterior(shape, reverse, oblique):
    u = ((-2., -2.), (2., -2.), (2., 2.), (1., 2.),
         (1., -1.), (-1., -1.), (-1., 2.), (-2., 2.))
    if shape == "c":
        outer = tuple((-y, x) for x, y in u)
    elif shape == "rectangle":
        outer = ((-2., -2.), (2., -2.), (2., 2.), (-2., 2.))
    else:
        outer = u
    if reverse:
        outer = tuple(reversed(outer))
    plane = (0., .00037, .001) if oblique else (0., 0., .001)
    if shape == "c":
        plane = (plane[0], -plane[2], plane[1])
    field = fields.SectionField("Elastic", "Domain regression", outer, (),
                                plane, plane, None, (), "")
    figure = fields.section_field_figure(field, "strain")
    bands = [trace for trace in figure.data if trace.name == "Concrete display band"]
    assert len(bands) >= 64
    total_area = 0.0
    for trace in bands:
        polygon = np.array(list(zip(trace.x, trace.y)), dtype=float) / 1000.0
        total_area += geometry.area_moments(polygon).area
        if not trace.line.width:
            continue
        for a, b in zip(polygon, polygon[1:]):
            for fraction in (.25, .5, .75):
                point = a + fraction * (b - a)
                assert (
                    geometry._strictly_inside(point, np.array(outer))
                    or geometry.distance_to_boundary(*point, [outer]) <= 1e-10
                ), "A visible band edge crosses the empty section exterior"
    assert total_area == pytest.approx(geometry.area_moments(outer).area, abs=1e-11)
