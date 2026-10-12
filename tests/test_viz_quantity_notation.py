"""Authored quantity notation preserves physical axis and material meanings."""
from app import viz
import pytest


@pytest.mark.parametrize('axis,face', [('x', 'bottom'), ('y', 'left')])
def test_nm_axis_and_landmark_use_the_same_subscript(axis, face):
    figure = viz.interaction_nm_figure([0., -500., 500., 0.], [200., 0., 0., -350.], axis=axis)
    symbol = f'M<sub>{axis}</sub>'
    assert figure.layout.xaxis.title.text == symbol + ' (kNm)'
    assert figure.layout.yaxis.title.text == 'N (kN, tension +)'
    assert any(item.text == 'max ' + symbol and item.x == 200. for item in figure.layout.annotations)
    landmark = next(item for item in figure.layout.annotations if item.text == 'max ' + symbol)
    assert (landmark.y, landmark.yshift, landmark.yanchor) == (0., 11, 'bottom')
    assert any('+' + symbol + ': tension at the ' + face + ' face' in item.text for item in figure.layout.annotations)
    note = next(item for item in figure.layout.annotations if item.xref == 'paper')
    assert (note.y, note.yshift, note.yanchor) == (1., 8, 'bottom')
    assert figure.layout.height - figure.layout.margin.t - figure.layout.margin.b == 324


@pytest.mark.parametrize('report_labels', [False, True])
def test_tube_quantity_and_area_unit_are_formatted_in_each_consumer(report_labels):
    figure = viz.tube_figure([(-.15, -.3), (.15, -.3), (.15, .3), (-.15, .3)], [], 40., ak_m2=.14, report_labels=report_labels)
    assert figure.data[1].name == 'inner wall face (t<sub>ef</sub> = 40 mm)'
    assert figure.data[2].name == 'wall center-line (A<sub>k</sub> = 140,000 mm<sup>2</sup>)'


def test_mm_axes_keep_the_physical_axis_mapping():
    figure = viz.interaction_figure([100., 0., -80.], [0., 90., 0.])
    assert figure.layout.xaxis.title.text == 'M<sub>y</sub> - about the y-axis (kNm)'
    assert figure.layout.yaxis.title.text == 'M<sub>x</sub> - about the x-axis (kNm)'
    note = next(item for item in figure.layout.annotations if item.xref == 'paper')
    assert (note.y, note.yshift, note.yanchor) == (1., 8, 'bottom')
    assert figure.layout.height - figure.layout.margin.t - figure.layout.margin.b == 304


def test_strain_axis_uses_epsilon_and_retains_sign_and_unit():
    rows = [{'x_mm': 0., 'y_mm': 0., 'strain_permille': 0., 'point_no': 1, 'ring': 'outer'}, {'x_mm': 0., 'y_mm': 10., 'strain_permille': 1., 'point_no': 2, 'ring': 'outer'}]
    figure = viz.elastic_strain_figure(rows, [], [0., 0., 1.], ec_mpa=33000.)
    assert figure.layout.xaxis.title.text == 'Strain ' + chr(949) + ' (' + chr(8240) + ', tension +)'
