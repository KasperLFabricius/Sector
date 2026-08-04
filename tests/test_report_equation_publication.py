from __future__ import annotations

import ast
import io
import pathlib
import re
import sys

import pypdf
import pytest
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, SimpleDocTemplate

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


def test_equation_block_seals_identity_roles_source_and_number():
    builder = _builder()
    builder._h1("Shear")
    builder._h2("Resistance")

    builder._formula(
        "concrete-shear-resistance",
        "V<sub>Rd,c</sub> = tau b<sub>w</sub>d",
        source="EN 1992-1-1 Formula (6.2)",
        subst="0.50 MPa x 300 mm x 500 mm",
        result="V<sub>Rd,c</sub> = 75.0 kN",
        symbols="tau is shear stress; b<sub>w</sub> and d are in mm.",
        numbered=True,
    )

    block = builder.flow[-1]
    assert isinstance(block, KeepTogether)
    assert block._sector_equation == {
        "id": "concrete-shear-resistance",
        "anchor": "sector-equation-1-1-concrete-shear-resistance",
        "number": "1.1",
        "section": 1,
        "subsection": 1,
    }
    assert block._sector_equation_roles == (
        "identity", "expression", "substitution", "result", "symbols", "source"
    )
    text = [item.getPlainText() for item in block._content]
    tau = chr(0x03C4)
    assert text == [
        "Equation (1.1) | ID EQ-1.1-CONCRETE-SHEAR-RESISTANCE",
        f"Expression: VRd,c = {tau} bwd",
        "Substitution: 0.50 MPa x 300 mm x 500 mm",
        "Result: VRd,c = 75.0 kN",
        f"Symbols: {tau} is shear stress; bw and d are in mm.",
        "Source: EN 1992-1-1 Formula (6.2)",
    ]


def test_only_numbered_equations_consume_section_sequence():
    builder = _builder()
    builder._h1("Basis")
    builder._formula("informative-relation", "a = b")
    builder._formula("governing-relation", "c = d", numbered=True)
    assert builder.flow[-2]._sector_equation["number"] is None
    assert builder.flow[-1]._sector_equation["number"] == "1.1"

    builder._h1("Results")
    builder._formula("governing-relation", "c = d", numbered=True)
    assert builder.flow[-1]._sector_equation["number"] == "2.1"


def test_equation_identity_rejects_missing_section_bad_keys_and_blank_metadata():
    builder = _builder()
    with pytest.raises(ValueError, match="active report section"):
        builder._formula("valid-key", "x = 1")

    builder._h1("Basis")
    for bad in ("", "Uppercase", "space separated", "user/<id>", "-leading"):
        with pytest.raises(ValueError, match="Invalid equation ID"):
            builder._formula(bad, "x = 1")
    with pytest.raises(ValueError, match="source statement"):
        builder._formula("blank-source", "x = 1", source="  ")
    with pytest.raises(ValueError, match="symbol definitions"):
        builder._formula("blank-symbols", "x = 1", symbols="")


def test_duplicate_identity_is_fenced_within_subsection_but_reusable_after_heading():
    builder = _builder()
    builder._h1("Shear")
    builder._h2("Direction x")
    builder._formula("utilisation", "u = 0.5")
    with pytest.raises(ValueError, match="Duplicate equation ID"):
        builder._formula("utilisation", "u = 0.6")

    builder._h2("Direction y")
    builder._formula("utilisation", "u = 0.7")
    assert builder.flow[-1]._sector_equation["anchor"] == (
        "sector-equation-1-2-utilisation"
    )


def test_cross_reference_requires_prior_same_subsection_target_and_renders_link():
    builder = _builder()
    builder._h1("Shear")
    builder._h2("Resistance")
    with pytest.raises(ValueError, match="unknown prior equation"):
        builder._formula(
            "governing", "V = max(v1, v2)", references=("component-one",)
        )

    builder._formula("component-one", "v1 = 10", numbered=True)
    builder._formula("component-two", "v2 = 12", numbered=True)
    builder._formula(
        "governing",
        "V = max(v1, v2)",
        numbered=True,
        references=("component-one", "component-two"),
    )
    block = builder.flow[-1]
    assert "references" in block._sector_equation_roles
    uses = next(
        item for item in block._content if item.getPlainText().startswith("Uses:")
    )
    assert uses.getPlainText() == "Uses: Equation (1.1), Equation (1.2)"

    pdf = _pdf(builder.flow)
    text = "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(pdf)).pages)
    assert "Uses: Equation (1.1), Equation (1.2)" in text


def test_long_expression_wraps_inside_the_standard_block():
    builder = _builder()
    builder._h1("Long expression")
    builder._formula(
        "long-expression",
        "result = first contribution + second contribution + third contribution + "
        "fourth contribution + fifth contribution",
    )
    expression = builder.flow[-1]._content[1]
    _width, height = expression.wrap(75, 500)
    assert height > builder.s["formula"].leading


def test_grouping_preserves_equation_wrapper_and_metadata():
    builder = _builder()
    builder._h1("Grouped section")
    start = len(builder.flow)
    builder._h2("Resistance")
    builder._p("Retained context")
    builder._formula(
        "grouped-resistance",
        "R = a + b",
        result="R = 10 kN",
        numbered=True,
    )
    equation = builder.flow[-1]

    builder._keep_from(start)

    outer = builder.flow[-1]
    assert isinstance(outer, KeepTogether)
    assert equation in outer._content
    assert isinstance(equation, KeepTogether)
    assert equation._sector_equation["id"] == "grouped-resistance"
    assert equation._sector_equation_roles == (
        "identity", "expression", "result", "symbols", "source"
    )


def test_all_report_formula_calls_use_the_frozen_identity_boundary():
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

    allowed_dynamic = "f'reinforcement-design-strength-{material_index + 1}'"
    for call in calls:
        assert len(call.args) >= 2, f"line {call.lineno} lacks an explicit equation ID"
        assert not any(keyword.arg == "ref" for keyword in call.keywords)
        identity = call.args[0]
        if isinstance(identity, ast.Constant):
            assert re.fullmatch(
                r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", identity.value
            ), f"line {call.lineno} has an invalid authored equation ID"
        else:
            assert ast.unparse(identity) == allowed_dynamic
