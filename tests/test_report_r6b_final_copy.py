"""Preserve report values while grouping wall evidence and naming tables."""
from __future__ import annotations

import ast
import copy
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import report_equation_contract as contracts
import sector_report as report
from test_report_heading_layout import _LabeledBlock, _pdf, _page


def test_equation_meanings_keep_controlled_keys_and_reference_symbols():
    assert len(contracts._CONTRACTS) == 145
    meanings = [symbol.meaning for item in contracts._CONTRACTS.values()
                for symbol in item.symbols]
    assert not any("neutralising" in text or "neutralisation" in text
                   or "raw Ec=1" in text for text in meanings)
    assert sum("reference stress with E<sub>c</sub> = 1" in text
               for text in meanings) == 2
    assert any("neutralising" in key[0] for key in contracts._CONTRACTS)


def test_action_caption_preserves_every_concurrent_value_and_literal_case():
    actions = dict(n_ed_kn=-150, mx_ed_knm=180, my_ed_knm=-30,
                   vx_ed_kn=22, vy_ed_kn=-8, t_ed_knm=15)
    builder = report.ReportBuilder(io.BytesIO(), {},
        {"_report_case_actions": actions}, {}, figures=False, profile="Audit")
    captured = []
    builder._table = lambda rows, *args, **kw: captured.append((rows, kw))
    original = copy.deepcopy(builder.inp)
    builder._case_line("plastic")
    assert builder.inp == original
    rows, kwargs = captured[0]
    assert rows[1] == ["-150.000", "180.000", "-30.000", "22.000", "-8.000", "15.000"]
    assert kwargs["caption"] == "Concurrent section actions"
    assert rows[0][0] == "N<sub>Ed</sub> (kN)"


def test_mathematical_first_columns_have_explicit_meaningful_captions():
    source = Path(report.__file__).read_text()
    found = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_table" and node.args):
            continue
        try:
            heading = node.args[0].elts[0].elts[0]
        except (AttributeError, IndexError):
            continue
        if isinstance(heading, ast.Constant) and heading.value in {
            "N<sub>Ed</sub> (kN)", "M<sub>Ed</sub>", "T<sub>Ed</sub>"
        }:
            caption = next(k.value.value for k in node.keywords if k.arg == "caption")
            found.append((heading.value, caption))
    assert sorted(found) == sorted([
        ("N<sub>Ed</sub> (kN)", "Concurrent section actions"),
        ("M<sub>Ed</sub>", "Longitudinal chord demand and conditional resistance"),
        ("T<sub>Ed</sub>", "Torsion resistance and overall status"),
        ("T<sub>Ed</sub>", "Torsion resistance and overall status"),
    ])


@pytest.mark.parametrize("profile", ["Standard", "Audit"])
@pytest.mark.parametrize("height", [590, 610, 630])
def test_wall_evidence_introduction_stays_with_native_table(profile, height):
    builder = report.ReportBuilder(io.BytesIO(), {}, {}, {}, figures=False, profile=profile)
    builder._h1("Wall evidence")
    builder.flow.append(_LabeledBlock(height, "PRECEDING CONTENT"))
    t = dict(theta_deg=45, cot=1, nu=.528, alpha_cw=1, gamma_ct=1.5,
             fctd=1.2, fywd=435, tube=dict(A=.3, u=2.2, tef_auto=136.4,
             tef=100, Ak=.15, uk=1.8, tef_selection="USER SOURCE <sub>ID</sub>",
             wall_evidence={"walls": [dict(wall=1, bar_indices=[2, 3],
             a_mm=45, lower_bound_mm=90, real_wall_mm=100)]}))
    original = copy.deepcopy(t)
    table = builder._table
    calls = []
    def wall_table(rows, widths, **kwargs):
        calls.append(copy.deepcopy(rows))
        if rows[0][0] == "Wall":
            return table(rows, widths, **kwargs)
    builder._table = wall_table
    builder._h2 = lambda *args, **kwargs: None
    builder._single_tube_evidence_tables(t)
    assert t == original
    assert calls[1][1] == ["Wall 1", "2, 3", "45.0 mm", "90.0 mm", "100.0 mm"]
    _, texts = _pdf(builder)
    page = _page(texts, "Wall-specific reinforcement-center")
    assert page == _page(texts, "Wall 1")
    assert page == _page(texts, "Lower bound 2a")


def test_cracked_reference_stress_source_keeps_method_qualification():
    source = Path(report.__file__).read_text()
    values = [node.value for node in ast.walk(ast.parse(source))
              if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    assert values.count(
        "Sector cracked-section reference-stress formulation with E<sub>c</sub> = 1."
    ) == 2
