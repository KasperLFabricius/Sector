"""Keep fatigue enum descriptions at the report boundary with literal fallback."""
import ast
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import sector_report as report
from sector.fatigue import _yield_assessment


@pytest.mark.parametrize('kind,stress,compression,symbol,word', [
    ('mild', 100.0, 450.0, 'f<sub>ytk</sub>', 'Tensile yield'),
    ('mild', -100.0, 450.0, 'f<sub>yck</sub>', 'Compressive yield'),
    ('mild', -100.0, None, 'f<sub>ytk</sub>', 'used for compression'),
    ('prestress', 100.0, None, 'f<sub>p0.1k</sub>', '0.1% proof'),
    ('prestress', -100.0, None, 'f<sub>p0.1k</sub>', 'used for compression'),
])
def test_yield_label_uses_actual_solver_branch_without_changing_evidence(kind, stress, compression, symbol, word):
    check = _yield_assessment(stress, SimpleNamespace(fytk_mpa=500.0, fyck_mpa=compression),
                              1.15, state='test')
    before = repr(check)
    label = report._fatigue_report_label(check.branch, 'yield_branch', kind=kind)
    assert symbol in label and word in label
    assert repr(check) == before
    assert check.design_limit_mpa == (compression if stress < 0 and compression else 500.0) / 1.15


@pytest.mark.parametrize('family,value,expected', [
    ('kind', 'mild', 'Reinforcing steel'),
    ('kind', 'prestress', 'Prestressing steel'),
    ('stress_model', 'fixed', 'Fixed characteristic stress range'),
    ('stress_model', 'ec2_2023_bar_diameter', 'EC2:2023 bar-diameter-dependent stress range'),
    ('stress_model', 'ec2_2023_welded_diameter', 'EC2:2023 welded-bar-diameter-dependent stress range'),
    ('range_basis', 'characteristic', 'Characteristic stress range'),
    ('range_basis', 'design', 'Design stress range'),
    ('sn_branch', 'zero stress range', 'Zero stress range'),
    ('sn_branch', 'k1 (at or above knee)', 'Exponent k<sub>1</sub>: stress range at or above the S-N curve knee'),
    ('sn_branch', 'k2 (below knee)', 'Exponent k<sub>2</sub>: stress range below the S-N curve knee'),
])
def test_exact_controlled_fatigue_labels(family, value, expected):
    assert report._fatigue_report_label(value, family) == expected


@pytest.mark.parametrize('family', ['kind', 'stress_model', 'range_basis', 'sn_branch', 'yield_branch', 'unknown'])
def test_unknown_labels_and_id_like_text_remain_literal(family):
    value = 'tension fytk <sub>ID</sub> A&B 1.7475e-07'
    assert report._fatigue_report_label(value, family, kind='mild') == report._html_escape(value)
    assert report._fatigue_report_label('tension fytk', 'yield_branch', kind='unknown') == 'tension fytk'


def test_report_consumers_select_labels_only_for_named_controlled_fields():
    tree = ast.parse(Path(report.__file__).read_text())
    callers = []
    for item in ast.walk(tree):
        if isinstance(item, ast.Call) and isinstance(item.func, ast.Name) and item.func.id == '_fatigue_report_label':
            callers.append(ast.unparse(item))
    assert len(callers) == 9
    assert sum("'yield_branch'" in item for item in callers) == 1
    assert any("value(result, 'kind')" in item for item in callers)
    assert not any(key in item for item in callers for key in ('element_id', 'detail_id', 'source', 'bin_name'))
