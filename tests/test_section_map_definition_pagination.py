"""Section-map definitions stay with their map or retained state at frame limits."""
import copy
import dataclasses
import io
from types import SimpleNamespace

import pypdf
import pytest
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, Spacer

from app import sector_report as report
from app import section_fields as fields
from test_section_fields import native_case


def _paragraphs(flow):
    for item in flow:
        if isinstance(item, KeepTogether):
            yield from _paragraphs(item._content)
        elif isinstance(item, Paragraph):
            yield item.getPlainText()


@pytest.mark.parametrize('family', ['Plastic', 'Elastic'])
@pytest.mark.parametrize('profile', ['Standard', 'Audit'])
@pytest.mark.parametrize('long_identity', [False, True])
@pytest.mark.parametrize('density', [False, True])
@pytest.mark.parametrize('preceding_height', [0, 440])
def test_definition_pages_retain_map_or_selected_state(family, profile, long_identity, density, preceding_height, monkeypatch):
    inp, elastic, plastic, _ = native_case()
    result = elastic if family == 'Elastic' else plastic
    original = copy.deepcopy(result)
    field = dataclasses.replace(fields.build_field(inp, result, family=family), density=density)
    if long_identity:
        inp['elastic_case' if family == 'Elastic' else 'plastic_case'] = {'id': 'ACTION <&> ' + 'Long identity ' * 12}
    figure = SimpleNamespace(layout=SimpleNamespace(width=760, height=665))
    monkeypatch.setattr(report.section_fields, 'field_pair', lambda *a, **kw: (field, [('strain', figure), ('stress', figure)]))
    raster = io.BytesIO()
    Image.new('RGB', (760, 665), 'white').save(raster, format='PNG')
    exports = []
    def export(fig, width, height):
        exports.append((fig, width, height))
        return raster.getvalue(), False
    monkeypatch.setattr(report, '_fig_png', export)
    builder = report.ReportBuilder(io.BytesIO(), {}, inp, {}, figures=True, profile=profile)
    builder._h1('Retained section results')
    if preceding_height:
        builder._p('Preceding substantive calculation.')
        builder.flow.append(Spacer(1, preceding_height))
    builder._section_field_maps(result, family=family)
    visible = list(_paragraphs(builder.flow))
    assert sum('Retained section results' in text for text in visible) == 1
    assert sum('Section stress and strain maps' in text for text in visible) == 1
    assert sum('For the section maps,' in text for text in visible) == 1
    assert sum('Display bands show values' in text for text in visible) == 1
    assert sum(field.state + '. ' + field.caption == text for text in visible) == 1
    assert sum('Slab-density markers' in text for text in visible) == int(density)
    assert exports == [(figure, 760, 665), (figure, 760, 665)]
    map_groups = [item for item in builder.flow if isinstance(item, KeepTogether)
                  and any('Tension is positive' in text for text in _paragraphs(item._content))]
    assert len(map_groups) == 2
    heading_joined = any('Section stress and strain maps' in text
                         for text in _paragraphs(map_groups[0]._content))
    if not heading_joined:
        heading = [item for item in builder.flow if isinstance(item, Paragraph)
                   and ('Section stress and strain maps' in item.getPlainText()
                        or item.getPlainText() == field.state + '. ' + field.caption)]
        assert len(heading) == 2
        prior_group = KeepTogether([*heading, *map_groups[0]._content])
        prior_group.wrapOn(report.canvas.Canvas(io.BytesIO()),
                           report._A4_CONTENT_WIDTH - 2 * report._REPORT_FRAME_PADDING,
                           report._A4_FRAME_USABLE_HEIGHT)
        assert prior_group._H + prior_group.getSpaceBefore() > report._A4_FRAME_USABLE_HEIGHT
    stream = io.BytesIO()
    doc = report._ReportDocTemplate(stream, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm, topMargin=25*mm, bottomMargin=20*mm)
    doc.multiBuild(builder.flow)
    pages = pypdf.PdfReader(io.BytesIO(stream.getvalue())).pages
    assert len(pages) <= (4 if preceding_height else 3)
    map_pages = []
    for page in pages:
        text = page.extract_text()
        if preceding_height == 0 and 'Retained section results' in text and not page.images:
            assert 'For the section maps,' in text, 'Dedicated chapter lost its original definition paragraphs'
        if heading_joined and 'Section stress and strain maps' in text:
            assert page.images, 'A normal map heading must not occupy an isolated page'
        if 'For the section maps,' in text:
            assert (page.images or field.state in text
                    or (preceding_height == 0 and 'Retained section results' in text))
            assert 'Display bands show values' in text
        if page.images:
            map_pages.append(text)
            assert 'Extremum' in text and 'maximum' in text and 'minimum' in text
            assert 'Tension is positive. Compression is negative.' in text
    assert len(map_pages) == 2
    assert family.lower() + ' strain' in ' '.join(map_pages[0].split())
    assert family.lower() + ' stress' in ' '.join(map_pages[1].split())
    assert result == original


@pytest.mark.parametrize('delta,joined', [(0.0, True), (0.000001, True), (-0.000001, False)])
def test_definition_map_fallback_uses_exact_measured_boundary(delta, joined, monkeypatch):
    inp, result, _, _ = native_case()
    field = fields.build_field(inp, result, family='Elastic')
    figure = SimpleNamespace(layout=SimpleNamespace(width=760, height=665))
    monkeypatch.setattr(report.section_fields, 'field_pair', lambda *a, **kw: (field, [('strain', figure), ('stress', figure)]))
    raster = io.BytesIO()
    Image.new('RGB', (760, 665), 'white').save(raster, format='PNG')
    monkeypatch.setattr(report, '_fig_png', lambda *a, **kw: (raster.getvalue(), False))
    measured = []
    wrap = KeepTogether.wrapOn
    def measure(group, *args, **kwargs):
        answer = wrap(group, *args, **kwargs)
        text = list(_paragraphs(group._content))
        if any('For the section maps,' in t for t in text) and not any('Section stress and strain maps' in t for t in text):
            measured.append(group._H + group.getSpaceBefore())
        return answer
    monkeypatch.setattr(KeepTogether, 'wrapOn', measure)
    first = report.ReportBuilder(io.BytesIO(), {}, inp, {}, figures=True, profile='Audit')
    first._h1('Retained section results')
    first._p('Preceding substantive calculation.')
    first._section_field_maps(result, family='Elastic')
    assert len(measured) == 1
    monkeypatch.setattr(report, '_A4_FRAME_USABLE_HEIGHT', measured[0] + delta)
    final = report.ReportBuilder(io.BytesIO(), {}, inp, {}, figures=True, profile='Audit')
    final._h1('Retained section results')
    final._p('Preceding substantive calculation.')
    final._section_field_maps(result, family='Elastic')
    assert any('For the section maps,' in t for t in _paragraphs(final.flow[-1]._content)) is joined
    assert sum('Retained section results' in t for t in _paragraphs(final.flow)) == 1

@pytest.mark.parametrize('delta,joined', [(0.0, True), (0.000001, True), (-0.000001, False)])
def test_complete_introduction_uses_exact_measured_boundary(delta, joined, monkeypatch):
    inp, result, _, _ = native_case()
    field = fields.build_field(inp, result, family='Elastic')
    figure = SimpleNamespace(layout=SimpleNamespace(width=1000, height=610))
    monkeypatch.setattr(report.section_fields, 'field_pair', lambda *a, **kw: (field, [('strain', figure), ('stress', figure)]))
    raster = io.BytesIO()
    Image.new('RGB', (1000, 610), 'white').save(raster, format='PNG')
    monkeypatch.setattr(report, '_fig_png', lambda *a, **kw: (raster.getvalue(), False))
    measured = []
    wrap = KeepTogether.wrapOn
    def measure(group, *args, **kwargs):
        answer = wrap(group, *args, **kwargs)
        text = list(_paragraphs(group._content))
        if any('For the section maps,' in t for t in text) and any('Section stress and strain maps' in t for t in text):
            measured.append(group._H + group.getSpaceBefore())
        return answer
    monkeypatch.setattr(KeepTogether, 'wrapOn', measure)
    def make():
        builder = report.ReportBuilder(io.BytesIO(), {}, inp, {}, figures=True, profile='Audit')
        builder._h1('Retained section results')
        builder._p('Preceding substantive calculation.')
        builder._section_field_maps(result, family='Elastic')
        return builder
    make()
    assert len(measured) == 1
    monkeypatch.setattr(report, '_A4_FRAME_USABLE_HEIGHT', measured[0] + delta)
    final = make()
    groups = [list(_paragraphs(item._content)) for item in final.flow if isinstance(item, KeepTogether)]
    assert any(any('For the section maps,' in t for t in texts) and any('Section stress and strain maps' in t for t in texts) for texts in groups) is joined
    assert sum('Retained section results' in t for t in _paragraphs(final.flow)) == 1
