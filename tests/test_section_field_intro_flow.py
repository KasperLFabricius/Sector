"""Map introductions preserve unavailable states and bounded page groups."""
import io

import pytest
from reportlab.platypus import KeepTogether, Paragraph
from app import sector_report as report
from app import section_fields as fields
from test_section_fields import native_case


@pytest.mark.parametrize('profile', ['Standard', 'Audit'])
def test_unavailable_field_retains_subsection_and_literal_reason(profile, monkeypatch):
    def unavailable(*args, **kwargs):
        raise report.section_fields.FieldUnavailable('stale <state> & context')
    monkeypatch.setattr(report.section_fields, 'field_pair', unavailable)
    builder = report.ReportBuilder(io.BytesIO(), {}, {}, {}, figures=True, profile=profile)
    builder._h1('Section results')
    builder._section_field_maps({}, family='Elastic')
    texts = [item.getPlainText() for item in builder.flow if isinstance(item, Paragraph)]
    assert any('Section stress and strain maps' in text for text in texts)
    assert texts[-1] == 'Section maps unavailable. stale <state> & context'
    assert builder._subsection == 1
    assert not any(isinstance(item, KeepTogether) for item in builder.flow)


@pytest.mark.parametrize('delta,fallback', [(0., False), (0.000001, False), (-0.000001, True)])
def test_heading_join_uses_measured_page_height_boundary(delta, fallback, monkeypatch):
    from PIL import Image
    inp, result, _, _ = native_case()
    field = fields.build_field(inp, result, family='Elastic')
    figure = fields.section_field_figure(field, 'strain', title='Exact state')
    monkeypatch.setattr(report.section_fields, 'field_pair', lambda *a, **kw: (field, [('strain', figure)]))
    data = io.BytesIO()
    Image.new('RGB', (760, 665), 'white').save(data, format='PNG')
    monkeypatch.setattr(report, '_fig_png', lambda *a, **kw: (data.getvalue(), False))
    def builder():
        item = report.ReportBuilder(io.BytesIO(), {}, inp, {}, figures=True, profile='Standard')
        item._h1('Section results')
        return item
    first = builder()
    measured = []
    original = KeepTogether.wrapOn
    def wrap(group, *args, **kwargs):
        size = original(group, *args, **kwargs)
        if any(isinstance(child, Paragraph) and 'Section stress and strain maps' in child.getPlainText() for child in group._content):
            measured.append(group._H + group.getSpaceBefore())
        return size
    monkeypatch.setattr(KeepTogether, 'wrapOn', wrap)
    first._section_field_maps({}, family='Elastic')
    assert len(measured) == 1
    monkeypatch.setattr(report, '_A4_FRAME_USABLE_HEIGHT', measured[0] + delta)
    final = builder()
    final._section_field_maps({}, family='Elastic')
    group = final.flow[-1]
    assert isinstance(group, KeepTogether)
    has_heading = any(isinstance(child, Paragraph) and 'Section stress and strain maps' in child.getPlainText() for child in group._content)
    assert has_heading is not fallback
    assert any('Tension is positive' in child.getPlainText() for child in group._content if isinstance(child, Paragraph))
