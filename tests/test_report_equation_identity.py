from __future__ import annotations

import ast
import collections
import io
import pathlib
import re
import sys

import pypdf
import pytest
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import sector_report  # noqa: E402


def _builder():
    return sector_report.ReportBuilder(
        io.BytesIO(), {}, {}, {}, figures=False, qa_appendix=False
    )


def _pdf(flow):
    buffer = io.BytesIO()
    SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=25 * mm,
        bottomMargin=20 * mm,
    ).build(flow)
    return buffer.getvalue()


def test_equation_flowable_seals_public_identity_number_and_source():
    builder = _builder()
    builder._h1("Resistance")
    builder._h2("Direction x")
    builder._formula(
        "R = a + b",
        ref="EN 1992-1-1 Formula (1.2)",
        subst="4 + 6",
        result="R = 10 kN",
        equation_key="resistance.direction-x.result",
    )

    equation = builder.flow[-1]
    assert isinstance(equation, sector_report._EquationFlowable)
    assert equation._sector_equation_key == "resistance.direction-x.result"
    assert equation._sector_equation_anchor == (
        "sector-equation-1-1-resistance__direction-x__result"
    )
    assert equation._sector_equation_number == "1.1"
    assert equation._sector_equation_section == 1
    assert equation._sector_equation_subsection == 1
    assert equation.getPlainText() == (
        "Equation (1.1) | EQ-RESISTANCE.DIRECTION-X.RESULT "
        "R = a + b 4 + 6 R = 10 kN "
        "Source / method note: EN 1992-1-1 Formula (1.2)"
    )


def test_derived_source_is_explicit_and_unnumbered_relation_does_not_consume_number():
    builder = _builder()
    builder._h1("Basis")
    builder._formula(
        "a = b", equation_key="basis.informative", numbered=False
    )
    builder._formula("c = d", equation_key="basis.governing")

    informative, governing = builder.flow[-2:]
    assert informative._sector_equation_number is None
    assert "Derived relation; no separate normative source assigned." in (
        informative.getPlainText()
    )
    assert governing._sector_equation_number == "1.1"

    builder._h1("Next")
    builder._formula("e = f", equation_key="next.governing")
    assert builder.flow[-1]._sector_equation_number == "2.1"


def test_invalid_duplicate_and_blank_source_fail_before_publication():
    builder = _builder()
    with pytest.raises(ValueError, match="active section"):
        builder._formula("x = 1", equation_key="valid.key")

    builder._h1("Basis")
    before = len(builder.flow)
    for key in ("", "Upper", "space key", "user/<id>", ".leading"):
        with pytest.raises(ValueError, match="Invalid report equation key"):
            builder._formula("x = 1", equation_key=key)
    with pytest.raises(ValueError, match="source text"):
        builder._formula("x = 1", ref=" ", equation_key="blank.source")
    assert len(builder.flow) == before

    builder._formula("x = 1", equation_key="unique.key")
    with pytest.raises(ValueError, match="Duplicate report equation key"):
        builder._formula("x = 2", equation_key="unique.key")


def test_unknown_reference_is_atomic_and_valid_prior_links_render():
    builder = _builder()
    builder._h1("Resistance")
    builder._h2("Components")
    with pytest.raises(ValueError, match="unknown prior key"):
        builder._formula(
            "R = max(R1, R2)",
            equation_key="resistance.governing",
            references=("resistance.component-1",),
        )

    builder._formula("R1 = 10", equation_key="resistance.component-1")
    builder._formula("R2 = 12", equation_key="resistance.component-2")
    builder._formula(
        "R = max(R1, R2)",
        equation_key="resistance.governing",
        references=("resistance.component-1", "resistance.component-2"),
    )
    assert builder.flow[-1]._sector_equation_number == "1.3"
    assert "Uses: Equation (1.1), Equation (1.2)" in (
        builder.flow[-1].getPlainText()
    )

    text = "\n".join(
        page.extract_text() or ""
        for page in pypdf.PdfReader(io.BytesIO(_pdf(builder.flow))).pages
    )
    assert "Uses: Equation (1.1), Equation (1.2)" in text


def test_equation_anchor_encoding_preserves_dot_and_hyphen_identity():
    builder = _builder()
    builder._h1("Resistance")
    builder._h2("Components")
    builder._formula("R1 = 10", equation_key="capacity.x-y")
    builder._formula("R2 = 12", equation_key="capacity-x.y")
    builder._formula(
        "R = max(R1, R2)",
        equation_key="capacity.governing",
        references=("capacity.x-y", "capacity-x.y"),
    )

    first, second, governing = builder.flow[-3:]
    assert first._sector_equation_anchor == (
        "sector-equation-1-1-capacity__x-y"
    )
    assert second._sector_equation_anchor == (
        "sector-equation-1-1-capacity-x__y"
    )
    assert first._sector_equation_anchor != second._sector_equation_anchor

    link_markup = governing._content[-2].text
    assert f'href="#{first._sector_equation_anchor}"' in link_markup
    assert f'href="#{second._sector_equation_anchor}"' in link_markup


def test_grouping_preserves_equation_and_existing_direct_child_audit_text():
    builder = _builder()
    builder._h1("Combined")
    start = len(builder.flow)
    builder._h2("Directional screen")
    builder._p("Audit context")
    builder._formula(
        "sum(SEd / SRd) <= 1",
        equation_key="combined.directional.sum",
    )
    equation = builder.flow[-1]

    builder._keep_from(start)

    outer = builder.flow[-1]
    assert isinstance(outer, KeepTogether)
    assert equation in outer._content
    direct_text = " ".join(
        child.getPlainText()
        for child in outer._content
        if hasattr(child, "getPlainText")
    )
    assert "sum(SEd / SRd) <= 1" in direct_text
    assert "EQ-COMBINED.DIRECTIONAL.SUM" in direct_text


def test_grouping_still_flattens_an_ordinary_keep_together_wrapper():
    builder = _builder()
    builder._h1("Tables")
    start = len(builder.flow)
    inner_paragraph = Paragraph("short table stand-in", builder.s["body"])
    ordinary = KeepTogether([inner_paragraph])
    builder.flow.append(ordinary)

    builder._keep_from(start)

    outer = builder.flow[-1]
    assert inner_paragraph in outer._content
    assert ordinary not in outer._content


def test_oversized_outer_group_releases_without_splitting_equation_text():
    builder = _builder()
    builder._h1("Long grouped section")
    start = len(builder.flow)
    builder._h2("Evidence")
    for index in range(75):
        builder._p(f"Retained audit line {index + 1} with enough text to wrap.")
    builder._formula(
        "R = first contribution + second contribution + third contribution",
        ref="Project-defined / uncited.",
        result="R = 12.5 kN",
        equation_key="grouped.long.resistance",
    )
    builder._keep_from(start)

    pages = [
        page.extract_text() or ""
        for page in pypdf.PdfReader(io.BytesIO(_pdf(builder.flow))).pages
    ]
    equation_pages = [
        text for text in pages if "EQ-GROUPED.LONG.RESISTANCE" in text
    ]
    assert len(equation_pages) == 1
    equation_page = equation_pages[0]
    assert "first contribution + second contribution + third contribution" in (
        equation_page
    )
    assert "R = 12.5 kN" in equation_page
    assert "Source / method note: Project-defined / uncited." in equation_page


def test_same_semantic_key_is_reusable_in_a_new_titled_subsection():
    builder = _builder()
    builder._h1("Shear")
    builder._h2("Direction x")
    builder._formula("u = 0.5", equation_key="shear.utilisation")
    builder._h2("Direction y")
    builder._formula("u = 0.7", equation_key="shear.utilisation")
    assert builder.flow[-1]._sector_equation_anchor == (
        "sector-equation-1-2-shear__utilisation"
    )


def test_all_retained_report_formula_calls_have_code_authored_keys():
    path = ROOT / "app" / "sector_report.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_formula"
    ]
    assert len(calls) == 61

    allowed_dynamic = "f'materials.steel.fyd-{material_index + 1}'"
    authored = []
    for call in calls:
        keys = [keyword.value for keyword in call.keywords
                if keyword.arg == "equation_key"]
        assert len(keys) == 1, f"line {call.lineno} bypasses equation identity"
        key = keys[0]
        if isinstance(key, ast.Constant):
            authored.append(key.value)
            assert re.fullmatch(
                r"[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*", key.value
            ), f"line {call.lineno} has an invalid authored key"
        else:
            assert ast.unparse(key) == allowed_dynamic
            authored.append(allowed_dynamic)

    duplicates = {
        key: count
        for key, count in collections.Counter(authored).items()
        if count > 1
    }
    assert duplicates == {
        "materials.concrete.fcd": 2,
        "shear.links.vrds": 2,
        "shear.links.vrdmax": 2,
        "crack.2005.spacing": 2,
    }
