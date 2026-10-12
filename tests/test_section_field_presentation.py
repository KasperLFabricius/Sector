"""Retained-value and identity checks for section field presentation."""
from dataclasses import replace
from html import unescape

import pytest

from app import section_fields as fields
from test_section_fields import native_case


@pytest.mark.parametrize("kind,base", [("Bar", "circle"), ("Tendon", "diamond")])
@pytest.mark.parametrize("value,suffix", [(1., ""), (-1., "-x"), (0., "-dot"), (-0., "-dot"), (1e-300, ""), (-1e-300, "-x")])
def test_response_sign_is_exact_and_independent_of_material_shape(kind, base, value, suffix):
    assert fields._response_symbol(kind, value) == base + suffix


@pytest.mark.parametrize("kind", ["Bar", "Tendon"])
@pytest.mark.parametrize("value", [None, True, "0", float("nan"), float("inf")])
def test_missing_or_invalid_response_cannot_be_a_zero_marker(kind, value):
    with pytest.raises(fields.FieldUnavailable):
        fields._response_symbol(kind, value)


@pytest.mark.parametrize("duration", ["TOTAL", "LONG"])
@pytest.mark.parametrize("phi", [0., 2.])
def test_concrete_reference_and_compatible_strains_keep_distinct_native_definitions(duration, phi):
    inp, elastic, _, native = native_case(phi=phi, tendon=True, mixed=True)
    field = fields.build_field(inp, elastic, family="Elastic", duration=duration)
    state = native.short_term if duration == "TOTAL" else native.long
    expected = (state.eps0, state.kx, state.ky)
    assert field.reference_strain_plane == tuple(v / (inp["conc_Ec"] * 1e6) for v in expected)
    figure = fields.section_field_figure(field, "strain")
    corners = next(t for t in figure.data if t.name == "Concrete boundary")
    for (x, y), row in zip(field.corners(), corners.customdata, strict=True):
        assert row[2] == field.strain(x, y) * 1000
        assert row[3] == fields.at(field.reference_strain_plane, x, y) * 1000
    assert "without creep" in corners.hovertemplate
    assert list(corners.text) == [f"Outer boundary, point {i + 1}" for i in range(4)]


@pytest.mark.parametrize("quantity", ["stress", "strain"])
def test_prestress_marker_uses_material_response_and_retains_every_strain_component(quantity):
    inp, elastic, _, _ = native_case()
    field = fields.build_field(inp, elastic, family="Elastic")
    item = dict(field.elements[-1], x=0., y=0., strain=.003, stress=585., initial=.004,
                id="T<&sigma;>", material_id="M<&>", material_name="Law <b>literal</b>")
    field = replace(field, strain_plane=(-.001, 0., 0.), elements=(item,))
    trace = next(t for t in fields.section_field_figure(field, quantity).data if t.name == "Tendons")
    assert trace.marker.symbol == ("diamond",)
    assert list(trace.customdata[0][:4]) == [585., 3., 4., -1.]
    assert unescape(trace.text[0]) == item["id"]
    assert unescape(trace.customdata[0][4]) == "M<&> - Law <b>literal</b>"
    assert "<b>literal</b>" not in trace.customdata[0][4]


def test_retained_material_identity_and_void_corner_identity_are_exposed():
    inp, elastic, _, _ = native_case()
    elastic["elements"][0].update(material_id="R1", material_name="Reinforcement A")
    field = fields.build_field(inp, elastic, family="Elastic")
    assert field.elements[0]["material_id"] == "R1"
    assert field.elements[0]["material_name"] == "Reinforcement A"
    field = replace(field, holes=(((-.02, -.02), (.02, -.02), (.02, .02), (-.02, .02)),))
    corners = next(t for t in fields.section_field_figure(field, "stress").data if t.name == "Concrete boundary")
    assert list(corners.text)[4:] == [f"Void 1, point {i + 1}" for i in range(4)]


def test_footer_reserves_room_for_three_lines_without_shrinking_data_domain():
    field = fields.SectionField("Elastic", "Zero", ((-1., -1.), (1., -1.), (1., 1.), (-1., 1.)),
                                (), (0., 0., 0.), (0., 0., 0.), None, (), "")
    figure = fields.section_field_figure(field, "stress")
    layout = figure.layout
    assert layout.height - layout.margin.t - layout.margin.b == 395
    note = layout.annotations[0]
    assert note.yanchor == "top"
    assert note.text.count("<br>") == 2
    data_height = layout.height - layout.margin.t - layout.margin.b
    note_top = layout.margin.t + data_height * (1 - note.y)
    assert note_top + 3 * note.font.size * 1.5 < layout.height


def test_explicit_outer_outline_preserves_complete_geometry():
    inp, elastic, _, _ = native_case()
    field = fields.build_field(inp, elastic, family="Elastic")
    for quantity in ("stress", "strain"):
        traces = [trace for trace in fields.section_field_figure(field, quantity).data
                  if trace.name == "Concrete outline"]
        assert len(traces) == 1
        closed = list(field.outer) + [field.outer[0]]
        assert list(traces[0].x) == [x * 1000 for x, y in closed]
        assert list(traces[0].y) == [y * 1000 for x, y in closed]
        assert traces[0].showlegend is False
        assert traces[0].hoverinfo == "skip"
