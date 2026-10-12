"""Retain crack-ratio digits through the final mathematical presentation."""
import io
import pickle
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
import sector_report as report
from sector.serviceability import analyse_cracking
from sector.section import Section
from sector_app import _crack_dict


@pytest.mark.parametrize('edition,coarse,direct', [('2005',False,False),('2005',True,False),('2023',False,False),('2023',False,True)])
def test_native_ratio_digits_reproduce_spacing_and_survive_presentation(edition, coarse, direct):
    section = Section.from_polygon([(-.15,-.3),(.15,-.3),(.15,.3),(-.15,.3)], [(-.1,-.25,400.),(.1,-.25,400.),(-.1,.25,400.),(.1,.25,400.)])
    result = analyse_cracking(section, *[(-800.,0.,0.) if direct else (0.,150.,0.)][0], 6., fctm=3., bar_diameter=20., edition=edition, coarse=coarse)
    cw = _crack_dict(result.crack, ['R1','R2','R3','R4'])
    original = pickle.dumps(cw)
    builder = report.ReportBuilder(io.BytesIO(), {}, {}, {'elastic':{'crack_code':edition}}, profile='Audit', figures=False)
    builder._h1('Crack arithmetic')
    texts = {}
    method = builder._formula
    def capture(*args, **kwargs):
        method(*args, **kwargs)
        item = builder.flow[-1]
        equations = getattr(item, '_sector_equations', (item,))
        texts[kwargs['equation_key']] = ' '.join(e.getPlainText() for e in equations)
    builder._formula = capture
    builder._crack_worked(cw)
    assert pickle.dumps(cw) == original
    ratio = float(format(cw['rho_p_eff'], '.8f'))
    printed = format(ratio, '.8f').rstrip('0').rstrip('.')
    assert printed in texts['crack.effective-reinforcement.ratio']
    spacing = cw['governing_candidate']['spacing_operands']
    if edition == '2023':
        arithmetic = spacing['cover_coefficient'] * spacing['cover'] + (spacing['flexural_factor'] * spacing['bond_factor_kb'] / spacing['diameter_ratio_divisor']) * spacing['diameter'] / ratio
        if spacing['cap_spacing'] is not None:
            arithmetic = min(arithmetic, spacing['cap_spacing'])
    elif spacing['selected_candidate'] == 'formula-7.11':
        arithmetic = spacing['k3_used'] * spacing['cover'] + spacing['k1'] * spacing['k2'] * spacing['k4'] * spacing['diameter'] / ratio
    else:
        arithmetic = spacing['selected_spacing']
    assert round(arithmetic, 3) == round(spacing['selected_spacing'], 3)
    published = texts['crack.'+edition+'.spacing'].split('Numerical substitution:', 1)[1].split('Result quantity:', 1)[0].split('Result:', 1)[0].strip()
    expression = published.split(';', 1)[0].split('=')
    expression = expression[1]
    expression = expression.replace(chr(183), '*').replace('mm', '').strip()
    assert re.fullmatch(r'[0-9.()+*/ -]+', expression)
    displayed_arithmetic = eval(expression, {"__builtins__": {}}, {})
    target_formula = spacing['formula_spacing'] if edition == '2023' else spacing['selected_spacing']
    assert round(displayed_arithmetic, 3) == round(target_formula, 3)

    if edition == '2023' or spacing['selected_candidate'] == 'formula-7.11':
        assert printed in texts['crack.'+edition+'.spacing']
    if edition == '2023':
        assert chr(958) + '1,j: bond-weighting factor' in texts['crack.effective-reinforcement.ratio']


def test_other_equations_keep_the_existing_three_decimal_policy():
    assert report._compact_equation_numbers('= 0.00800429 + 12.345678') == '= 0.008 + 12.346'
    assert report._compact_equation_numbers('= 0.00800429 + 12.345678', decimal_places=8) == '= 0.00800429 + 12.345678'
    assert report._compact_equation_numbers('= 0.0000000004', decimal_places=8) == '= 4e-10'


@pytest.mark.parametrize("value", [1.234567891e-12, 4.999e-9, 5.001e-9, 5.1e-9, 1.4999e-8, 1.5001e-8, 1.23456789e-6, .00800429, .012345678, 0.])
def test_ratio_display_preserves_tiny_nonzero_values(value):
    text = report._compact_equation_numbers(report._fmt_crack_ratio(value), decimal_places=8)
    if value:
        assert float(text) > 0
    else:
        assert float(text) == 0
    if value:
        assert float(text) == pytest.approx(value, rel=1e-6, abs=0)
        # The published denominator must retain inverse-ratio spacing arithmetic.
        assert 20. / float(text) == pytest.approx(20. / value, rel=1.00001e-6, abs=0)
    if 0 < value < 2e-8:
        assert float(text) == pytest.approx(value, rel=5e-9, abs=0)
