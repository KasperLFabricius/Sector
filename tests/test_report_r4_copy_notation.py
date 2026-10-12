"""Report notation must preserve diagnostic values and literal identities."""

import sys
import io
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))

from app import report_summary_notation as notation
from sector.engineer_message import EngineerMessage
import result_presentation as presentation
import sector_report as report


@pytest.mark.parametrize('family', sorted(presentation._RESULT_REASON_MESSAGES))
def test_catalogue_diagnostic_plain_strings_remain_exact(family):
    for state, message in presentation._RESULT_REASON_MESSAGES[family].items():
        result = presentation.result_reason(state, family)
        assert str(result) == message.text
        assert result == presentation.result_reason(message, family)


@pytest.mark.parametrize('family,state,markup', [
    ('shear', 'stirrups (VRd,s)', 'V<sub>Rd,s</sub>'),
    ('torsion', 'stirrups (TRd,s)', 'T<sub>Rd,s</sub>'),
])
def test_known_diagnostic_markup_survives_summary_assembly(family, state, markup):
    reason = presentation.result_reason(state, family)
    literal = 'N_Ed sigma <sub>user</sub> A&B'
    note = notation.join('; ', [reason, literal])
    row = notation.attach({'note': note})
    assert type(row['note']) is str
    assert row['note'] == state + '; ' + literal
    visible = report._html_escape(notation.row_field(row, 'note'))
    assert markup in visible
    assert visible.endswith(report._html_escape(literal))
    row['note'] = 'N_Ed updated by user'
    assert report._html_escape(notation.row_field(row, 'note')) == report._html_escape(row['note'])


def test_external_typed_message_and_unknown_state_keep_literal_policy():
    message = EngineerMessage('CUSTOM-USER', 'N_Ed VRd,s sigma <sub>user</sub>')
    value = presentation.result_reason(message, 'shear')
    assert type(value) is str
    assert value == message.text
    assert report._html_escape(value) == report._html_escape(message.text)
    same_text = EngineerMessage('CUSTOM-COPY', 'stirrups (VRd,s)')
    assert type(presentation.result_reason(same_text, 'shear')) is str
    unknown = presentation.result_reason('N_Ed USER-SUPPLIED-UNKNOWN', 'shear')
    assert unknown == presentation._RESULT_REASON_FALLBACKS['shear'].text


def test_combined_screen_note_keeps_plain_value_and_authored_symbols():
    value = presentation._MINIMUM_REINFORCEMENT_SCREEN_NOTES['dkna_combined_normal_or_moment']
    assert value == (
        'With acting N_Ed or M_Ed under the Danish National Annex, use the '
        'DK NA 6.3.2(6) combined N-M-V-T check; Formula (6.31) is not used as '
        'the combined verdict'
    )
    markup = report._html_escape(value)
    assert 'N<sub>Ed</sub>' in markup and 'M<sub>Ed</sub>' in markup


@pytest.mark.parametrize('axis,off_symbol', [('x','y'),('y','x')])
@pytest.mark.parametrize('moment', [-80.05, -0.000001, 30.0, 80.05])
def test_report_chord_label_preserves_axis_signed_operand_and_condition(axis, off_symbol, moment):
    value = report._report_chord_mrd_label(axis, moment, True)
    assert f'M<sub>{off_symbol}</sub> = {moment:.1f} kNm' in value
    assert f'capacity about {axis} at the applied N' in value
    assert 'M-M envelope point carries both moments' in value
    assert '--' not in value


def test_report_chord_zero_fallback_and_literal_axis():
    assert report._report_chord_mrd_label('x', 0.0, True) == '(bending about x at the applied N)'
    value = report._report_chord_mrd_label('y', 80.0, False)
    assert 'pure-axis bending about y at the applied N' in value
    assert 'did not converge' in value and 'overstate' in value
    assert report._html_escape('<sub>user</sub>') in report._report_chord_mrd_label('<sub>user</sub>', 0, True)


def test_adjacent_delta_sigma_tokens_render_as_greek():
    text = report._equation_math('&#916; sigma<sub>i</sub>')
    assert 'sigma' not in text
    assert '&#916;' in text and '&#963;' in text


def test_figure_caption_escapes_literal_identity_exactly_once(monkeypatch):
    from PIL import Image
    from reportlab.platypus import Paragraph, Table, KeepTogether
    data = io.BytesIO()
    Image.new('RGB', (2, 2), 'white').save(data, format='PNG')
    monkeypatch.setattr(report, '_fig_png', lambda *args: (data.getvalue(), False))
    builder = report.ReportBuilder(io.BytesIO(), {}, {}, {}, profile='Standard')
    literal = 'Case A&B <sub>ID</sub> sigma N_Ed'
    builder._fig(object(), caption=literal)
    def paragraphs(items):
        for item in items:
            if isinstance(item, Paragraph):
                yield item
            elif isinstance(item, KeepTogether):
                yield from paragraphs(item._content)
            elif isinstance(item, Table):
                for row in item._cellvalues:
                    for cell in row:
                        yield from paragraphs(cell if isinstance(cell, (tuple,list)) else [cell])
    visible = [p.getPlainText() for p in paragraphs(builder.flow)]
    assert any(text.endswith(literal) for text in visible)
    assert all('&amp;' not in text for text in visible)
