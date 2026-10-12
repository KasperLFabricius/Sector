"""Keep retained numerical precision and literal identities in report notation."""
import io
import re
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from reportlab.platypus import Paragraph, Table, KeepTogether

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from app import report_summary_notation as notation
from app import elastic_display
import fatigue_presentation as fatigue
import result_presentation as presentation
import sector_report as report


IDENTITY = 'R1 f_yk 1.7475e-07 <sub>literal</sub> A&B'


@pytest.mark.parametrize('value', [1.7475e-7, -2.301e-12, 1.0e21, 5.408e14])
def test_scientific_fragment_preserves_formatted_numeric_value(value):
    plain = fatigue.compact_number(value)
    typed = notation.number(plain)
    assert typed == plain
    markup = report._html_escape(typed)
    match = re.fullmatch(r'([+\-0-9.]+) &#215; 10<super>([+\-0-9]+)</super>', markup)
    assert match
    assert Decimal(match[1]) * Decimal(10) ** int(match[2]) == Decimal(plain)
    row = notation.attach({'note': typed})
    assert type(row['note']) is str
    assert report._html_escape(notation.row_field(row, 'note')) == markup


@pytest.mark.parametrize('plain', ['0', '-inf', 'inf', '0.6', '-', IDENTITY])
def test_number_fragment_keeps_non_scientific_text_literal(plain):
    assert report._html_escape(notation.number(plain)) == report._html_escape(plain)


def test_scientific_fragment_rejects_mixed_or_replaced_metadata():
    row = {'result': IDENTITY, 'report_fields': {'result': [('scientific', IDENTITY)]}}
    assert report._html_escape(notation.row_field(row, 'result')) == report._html_escape(IDENTITY)
    row = notation.attach({'result': notation.number('1.7475e-07')})
    row['result'] = IDENTITY
    assert report._html_escape(notation.row_field(row, 'result')) == report._html_escape(IDENTITY)


@pytest.mark.parametrize('passed,warnings', [(True, []), (False, []), (True, ['basis'])])
def test_fatigue_breakdown_formats_only_native_damage(passed, warnings):
    payload = {'converged': True, 'passed': passed, 'warnings': warnings,
               'governing_domain': 'reinforcement', 'governing_reinforcement_id': IDENTITY,
               'governing_criterion': 'Miner damage', 'miner_damage': 1.7475e-7,
               'yield_utilisation': 0.446, 'utilisation': 0.446}
    plain = fatigue.criterion_breakdown(payload)
    assert plain == ('governing: ' + IDENTITY + ' - Miner damage; '
                     'max Miner D 1.7475e-07; max yield/proof utilisation 44.6 %')
    for value in (plain, fatigue.overall_note(payload)):
        rendered = report._html_escape(value)
        assert report._html_escape(IDENTITY) in rendered
        assert 'max Miner D 1.7475 &#215; 10<super>-7</super>' in rendered
    row = presentation.fatigue_summary_rows({'fatigue_on': True}, {'fatigue': payload})[0]
    assert type(row['note']) is str
    assert '<super>-7</super>' in report._html_escape(notation.row_field(row, 'note'))
    stale = presentation.fatigue_summary_rows({'fatigue_on': True}, {'fatigue': payload}, stale=True)[0]
    assert 'inputs changed' in stale['note']
    assert '<super>' not in report._html_escape(notation.row_field(stale, 'note'))


def paragraphs(flow):
    for item in flow:
        if isinstance(item, Paragraph):
            yield item
        elif isinstance(item, KeepTogether):
            yield from paragraphs(item._content)
        elif isinstance(item, Table):
            for row in item._cellvalues:
                for cell in row:
                    if isinstance(cell, (tuple, list)):
                        yield from paragraphs(cell)
                    elif isinstance(cell, Paragraph):
                        yield cell


def test_elastic_reference_and_output_cells_use_controlled_notation():
    elements = [dict(element_id=prefix + IDENTITY, material_id='Material ' + IDENTITY,
                     element_type=kind, x_mm=0, y_mm=0, area_mm2=150,
                     strain_permille=0.2, total_mpa=100.0, long_mpa=80.0,
                     dif_mpa=20.0, rst1_mpa=40.0)
                for prefix, kind in [('Bar ', 'Bar'), ('Tendon ', 'Tendon')]]
    inp = {'concrete': SimpleNamespace(fck=40), 'tendons': [(0, 0, 0.00015)],
           'bar_elements': [{'id': elements[0]['element_id'], 'material_id': elements[0]['material_id']}],
           'tendon_elements': [{'id': elements[1]['element_id'], 'material_id': elements[1]['material_id']}],
           'bar_materials': [SimpleNamespace(fytk=500)],
           'tendon_materials': [SimpleNamespace(curve=6, futk=1860, fytk=1600)]}
    elastic = {'na_x': 0.0, 'na_y': 0.0, 'elements': elements,
               'stress_outputs': {'concrete': {'value': -10.0, 'governing': 'Point ' + IDENTITY},
                                  'reinforcement': {'value': 100.0, 'governing': elements[0]['element_id']},
                                  'prestress': {'value': 100.0, 'governing': elements[1]['element_id']}}}
    builder = report.ReportBuilder(io.BytesIO(), {}, inp, {'elastic': elastic}, figures=False, profile='Standard')
    builder._elastic()
    text = '\n'.join(item.text for item in paragraphs(builder.flow))
    normalized = re.sub(r' (?:rise|size)="[^"]*"', '', text)
    for subscript in ('ck', 'yk', 'pk', 'p0.1k'):
        assert f'f<sub>{subscript}</sub>' in normalized
    assert 'Transformed section properties with long-term modular ratios' in normalized
    assert 'Transformed section properties (nl)' not in normalized
    # Input identities remain literal even beside controlled reference symbols.
    assert report._html_escape(IDENTITY) in text
