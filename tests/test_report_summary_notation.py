"""Authored quantity notation must preserve literal text and summary selection."""

import io
import json
import re
import sys
from pathlib import Path

import pytest
from reportlab.platypus import Paragraph, Table, KeepTogether

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from app import report_summary_notation as notation
from app import elastic_display
import result_presentation as presentation
import sector_report as report
from sector.engineer_message import EngineerMessage


LITERAL = 'As,req VRd,c TEd f_ck sigma 1e-9 mm2 <sub>x</sub> A&B'


def markup(row, field):
    return report._html_escape(notation.row_field(row, field))


@pytest.mark.parametrize('plain,expected', notation.CATALOGUE.items())
def test_catalogue_formats_only_the_authored_chunk(plain, expected):
    value = notation.concat(notation.authored(plain), ' | ', plain, ' | ', LITERAL)
    rendered = report._html_escape(value)
    assert expected in rendered
    assert rendered.endswith(report._html_escape(plain + ' | ' + LITERAL))
    assert str(value) == plain + ' | ' + plain + ' | ' + LITERAL


@pytest.mark.parametrize('metadata', [None, {}, {'result': [('catalogue', '<b>bad</b>')]},
                                    {'result': [('catalogue', 'TEd')]},
                                    {'result': [('unknown', LITERAL)]},
                                    {'result': [None]}, {'result': [([], LITERAL)]}])
def test_missing_invalid_or_stale_metadata_falls_back_literally(metadata):
    row = {'result': LITERAL, 'report_fields': metadata}
    assert markup(row, 'result') == report._html_escape(LITERAL)


def test_plain_rows_json_and_stale_replacement_preserve_content():
    row = notation.attach({'result': notation.authored('As,req 120.0 mm2'),
                           'note': notation.authored('TEd = 0'), 'criterion': '-'})
    assert type(row['result']) is str
    assert type(row['note']) is str
    restored = json.loads(json.dumps(row))
    assert markup(restored, 'result') == markup(row, 'result')
    row['note'] = 'Last status: PASS; inputs changed'
    assert markup(row, 'note') == report._html_escape(row['note'])


def test_authored_template_keeps_format_specs_and_substituted_text_separate():
    value = notation.text('As,req {:.3f} mm2; source {}', 12.34567, LITERAL)
    assert value == f'As,req {12.34567:.3f} mm2; source {LITERAL}'
    assert 'A<sub>s,req</sub> 12.346 mm<super>2</super>' in report._html_escape(value)
    assert report._html_escape(value).endswith(report._html_escape(LITERAL))


def test_authored_template_preserves_nested_fragments():
    nested = notation.concat(notation.authored('TEd = 0; '), LITERAL)
    value = notation.text('As,req / As,prov = {:.3f}; {}', 0.75, nested)
    assert value == 'As,req / As,prov = 0.750; TEd = 0; ' + LITERAL
    rendered = report._html_escape(value)
    assert 'A<sub>s,req</sub> / A<sub>s,prov</sub>' in rendered
    assert 'T<sub>Ed</sub> = 0' in rendered
    assert rendered.endswith(report._html_escape(LITERAL))


def test_heightened_and_ordinary_producers_keep_reference_and_source_literal():
    row = presentation._heightened_crack_summary_row({
        'fine': {'required_reinforcement_area_mm2': 120.0},
        'coarse': {'required_reinforcement_area_mm2': 160.0},
        'provided_reinforcement_area_mm2': 200.0,
        'governing_comparison_ratio': 0.8, 'governing_status': 'PASS',
        'reference_case_id': LITERAL, 'ordinary_crack_branch': LITERAL,
        'governing_crack_system': LITERAL, 'source': LITERAL,
    })
    assert row['result'] == 'Fine As,req 120.0 mm2; coarse As,req 160.0 mm2; As,prov 200.0 mm2'
    assert 'A<sub>s,req</sub>' in markup(row, 'result')
    assert markup(row, 'note').count(report._html_escape(LITERAL)) == 4
    assert 'A<sub>s,req</sub> / A<sub>s,prov</sub> = 0.800' in markup(row, 'note')
    ordinary = presentation._ordinary_crack_summary_row({}, {
        'value': 0.15, 'criterion_mm': 0.2, 'ratio': 0.75,
        'reason': EngineerMessage('QA-LITERAL-CRACK-REASON', LITERAL),
        'case': LITERAL, 'governing': LITERAL,
        'criterion_source': LITERAL, 'duration': 'long_term',
    })
    assert markup(ordinary, 'note').count(report._html_escape(LITERAL)) == 4
    assert 'w<sub>k</sub> / w<sub>k,criterion</sub> = 0.750' in markup(ordinary, 'note')


def test_characteristic_references_use_exact_controlled_keys():
    value = elastic_display.comparison_text(-10.0, {'f_ck': 40.0, LITERAL: 20.0})
    assert value == f'25.0% of f_ck; 50.0% of {LITERAL}'
    assert 'f<sub>ck</sub>' in report._html_escape(value)
    assert report._html_escape(value).endswith(report._html_escape(LITERAL))


@pytest.mark.parametrize('check,plain_result,token', [
    ({'type': 'minimum area', 'as_provided_mm2': 800.0, 'as_min_mm2': 500.0},
     'As,prov 800.0 mm2; As,min 500.0 mm2', 'A<sub>s,min</sub>'),
    ({'type': 'pure tension', 'resistance_kn': 200.0, 'demand_kn': 120.0},
     'Rnom 200.0 kN; Rcr 120.0 kN', 'R<sub>nom</sub>'),
    ({'type': 'bending', 'mr_nom_knm': 80.0, 'm_cr_knm': 60.0},
     'MR,nom 80.0 kNm; Mcr 60.0 kNm', 'M<sub>R,nom</sub>'),
])
def test_minimum_reinforcement_branches_retain_plain_values(check, plain_result, token):
    rows = presentation.result_summary_rows({'minimum_reinforcement_on': True}, {
        'minimum_reinforcement': {'clause': LITERAL, 'checks': [dict(check, status='PASS')]},
    })
    row = next(row for row in rows if row.get('overview_key') == 'minimum_reinforcement')
    assert row['result'] == plain_result
    assert token in markup(row, 'result')
    assert markup(row, 'note') == report._html_escape(LITERAL)


@pytest.mark.parametrize('kind,plain_result,token', [
    ('minimum_ratio', '\u03c1w,prov = 0.00500', '&#961;<sub>w,prov</sub>'),
    ('longitudinal_spacing', 'sprov = 0.0 mm', 's<sub>prov</sub>'),
])
def test_link_detailing_retains_literal_spacing_source(kind, plain_result, token):
    rows = presentation.result_summary_rows({'transverse_detailing_on': True}, {
        'transverse_reinforcement': {'checks': [
            {'kind': kind, 'provided': 0.005, 'limit': 0.003, 'status': 'PASS',
             'spacing_source': LITERAL, 'clause': LITERAL},
        ]},
    })
    row = next(row for row in rows if row['result'] == plain_result)
    assert token in markup(row, 'result')
    assert markup(row, 'note').count(report._html_escape(LITERAL)) == 2


def test_directional_zero_action_symbols_use_the_controlled_components(monkeypatch):
    inp = {'mode': 'Plastic', 'shear_on': True, 'torsion_on': True,
           'combined_on': True, 'plastic_cases': [], 'elastic_cases': []}
    monkeypatch.setattr(presentation, '_worked_case_contexts',
                        lambda *args: [(LITERAL, dict(inp), {}, True)])
    rows = presentation.multi_case_summary_rows(inp, {'plastic_cases': [{}]})
    for component in ('Vx', 'Vy'):
        row = next(row for row in rows if row['check'] == 'Shear ' + component)
        assert row['result'] == component + ',Ed = 0'
        assert markup(row, 'result') == f'V<sub>{component[-1]},Ed</sub> = 0'


def test_governing_selection_is_identical_with_and_without_fragments():
    rows = [presentation._summary_row('check', 'shear', 'PASS',
             notation.authored('VRd,c 12.0'), notation.authored('As,prov >= As,min'),
             util, note=notation.authored('TEd = 0'), overview_key='same')
            for util in (0.2, 0.7)]
    plain = [{k: v for k, v in row.items() if k != 'report_fields'} for row in rows]
    selected = presentation.governing_summary_rows(rows)
    assert [{k: v for k, v in row.items() if k != 'report_fields'} for row in selected] == presentation.governing_summary_rows(plain)
    assert selected[0]['util'] == 0.7


def all_markup(flow):
    for item in flow:
        if isinstance(item, Paragraph):
            yield item.text
        elif isinstance(item, KeepTogether):
            yield from all_markup(item._content)
        elif isinstance(item, Table):
            for row in item._cellvalues:
                for cell in row:
                    if isinstance(cell, (list, tuple)):
                        yield from all_markup(cell)
                    elif isinstance(cell, Paragraph):
                        yield cell.text


@pytest.mark.parametrize('profile', ['Brief', 'Standard', 'Audit'])
def test_every_summary_report_surface_preserves_authored_and_literal_parts(monkeypatch, profile):
    row = presentation._summary_row(
        LITERAL, 'shear', 'PASS', notation.authored('As,req 120.0 mm2'),
        notation.authored('As,prov >= As,min'), 0.5,
        note=notation.concat(notation.authored('TEd = 0; '), LITERAL),
    )
    row.update(case=LITERAL, source=LITERAL)
    info = dict(row, check='Scope', status='NOT RUN', result='VEd = 0',
                report_fields={'result': notation.authored('VEd = 0').fragments})
    monkeypatch.setattr(report.presentation, 'multi_case_summary_rows', lambda *a, **k: [row, info])
    monkeypatch.setattr(report.presentation, 'governing_summary_rows', lambda rows: rows)
    monkeypatch.setattr(report.presentation, 'governing_result_rows', lambda rows: [row])
    monkeypatch.setattr(report.presentation, 'governing_information_rows', lambda rows: [info])
    monkeypatch.setattr(report.presentation, 'non_governing_summary_rows', lambda rows: [row])
    monkeypatch.setattr(report.presentation, 'non_governing_fatigue_spectrum_rows', lambda *a, **k: [])
    builder = report.ReportBuilder(io.BytesIO(), {}, {}, {}, profile=profile)
    builder._results_overview()
    builder._non_governing_status_register()
    parts = list(all_markup(builder.flow))
    # Both summary surfaces must use compact script rises on wrapped cells.
    assert sum('A<sub rise=' in part and '120.0 mm<super rise=' in part
               for part in parts) == 2
    text = re.sub(r' (?:rise|size)="[^"]*"', '', '\n'.join(parts))
    assert text.count('A<sub>s,req</sub> 120.0 mm<super>2</super>') == 2
    assert 'A<sub>s,prov</sub>' in text
    assert 'T<sub>Ed</sub> = 0' in text
    assert 'V<sub>Ed</sub> = 0' in text
    assert text.count(report._html_escape(LITERAL)) >= 5
