"""Rendered acceptance for shared report math and table typography."""

from __future__ import annotations

import io
import itertools
import pathlib
import sys

import pypdf
import pypdfium2
import pytest
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import publication_equation_layout as equations  # noqa: E402
import sector_report  # noqa: E402

from tools.publication_preflight import crop_sha256  # noqa: E402

_TYPOGRAPHY_CROP = (0.08, 0.05, 0.92, 0.62)
_TYPOGRAPHY_CROP_SHA256 = (
    "b209ec09d3eeb223d21de8e1befdfb3beb57bbcf7ade76ab5185349e988597e8"
)


def _fixture() -> tuple[bytes, Table, dict[str, float]]:
    builder = sector_report.ReportBuilder(
        io.BytesIO(), {}, {}, {}, figures=False, qa_appendix=False
    )
    builder._h1("Report typography")
    builder._h2("Structured radicals")
    block = equations.EquationBlock(
        (
            equations.EquationLine(
                "simple-radical",
                equations.compile_report_math(
                    "E<sub>max</sub> + 0.43 sqrt(1 - "
                    "E<sub>min</sub>/E<sub>max</sub>) &lt;= 1"
                ),
                "Simple root:",
            ),
            equations.EquationLine(
                "complex-radical",
                equations.compile_report_math(
                    "rho<sub>s,min</sub> = sqrt((phi f<sub>ct,eff</sub>) / "
                    "(4 E<sub>sk</sub> k w<sub>k</sub> + "
                    "sqrt(a<super>2</super> + b<super>2</super>)))"
                ),
                "Nested root:",
            ),
        ),
        identity="Equation (T.1)",
    )
    builder.flow.append(equations.EquationFlowable(block))
    builder._h2("Prestressing table symbols")
    builder._table(
        [
            ["Parameter", "Symbol", "Value"],
            [
                "Initial prestrain",
                "eps<sub>p</sub><super>(0)</super>",
                "7.000 permille",
            ],
            ["Proof strength", "f<sub>p0.1k</sub>", "1640.000 MPa"],
            ["Ultimate strength", "f<sub>pk</sub>", "1860.000 MPa"],
            ["Elastic modulus", "E<sub>p</sub>", "195.0 GPa"],
            ["Rupture strain", "eps<sub>ut</sub>", "35.000 permille"],
        ],
        [60 * mm, 35 * mm, 50 * mm],
        keep=False,
    )
    table = next(item for item in builder.flow if isinstance(item, Table))
    proof_symbol = table._cellvalues[5][1]
    proof_script = next(
        fragment for fragment in proof_symbol.frags if fragment.text == "p0.1k"
    )
    initial_symbol = table._cellvalues[4][1]
    initial_super = next(
        fragment for fragment in initial_symbol.frags if fragment.text == "(0)"
    )
    script_rises = {
        "subscript": float(proof_script.rise),
        "superscript": float(initial_super.rise),
    }
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )
    document.build(builder.flow)
    return buffer.getvalue(), table, script_rises


def _render_first_page(pdf: bytes, *, scale: float = 3.0) -> Image.Image:
    document = pypdfium2.PdfDocument(pdf)
    try:
        page = document[0]
        try:
            bitmap = page.render(scale=scale)
            try:
                return bitmap.to_pil().convert("RGB").copy()
            finally:
                bitmap.close()
        finally:
            page.close()
    finally:
        document.close()


def _transform_point(matrix, x: float, y: float) -> tuple[float, float]:
    return (
        matrix[0] * x + matrix[2] * y + matrix[4],
        matrix[1] * x + matrix[3] * y + matrix[5],
    )


def _script_baselines_and_grid_rules(pdf: bytes):
    page = pypdf.PdfReader(io.BytesIO(pdf)).pages[0]
    scripts = []
    horizontal_rules = []
    path_start = None

    def visit_text(text, cm, tm, _font, font_size):
        compact = "".join(text.split())
        if compact not in {"p(0)", "p0.1k", "pk", "ut"}:
            return
        local = _transform_point(tm, 0.0, 0.0)
        _x, baseline = _transform_point(cm, *local)
        scripts.append((compact, baseline, float(font_size)))

    def visit_operand(operator, operands, cm, _tm):
        nonlocal path_start
        if operator == b"m":
            path_start = _transform_point(
                cm, float(operands[0]), float(operands[1])
            )
        elif operator == b"l" and path_start is not None:
            path_end = _transform_point(
                cm, float(operands[0]), float(operands[1])
            )
            if (
                abs(path_start[1] - path_end[1]) <= 1e-7
                and abs(path_start[0] - path_end[0]) >= 100.0
            ):
                horizontal_rules.append(path_end[1])

    page.extract_text(
        visitor_text=visit_text,
        visitor_operand_before=visit_operand,
    )
    return scripts, tuple(sorted(set(horizontal_rules)))


def test_radicals_have_connected_bounded_vector_geometry() -> None:
    simple = equations.layout_math(
        equations.compile_report_math(
            "E<sub>max</sub> + 0.43 sqrt(1 - E<sub>min</sub>/E<sub>max</sub>)"
        )
    )
    complex_layout = equations.layout_math(
        equations.compile_report_math(
            "sqrt((phi f<sub>ct,eff</sub>) / (4 E<sub>sk</sub> k "
            "w<sub>k</sub> + sqrt(a<super>2</super> + b<super>2</super>)))"
        )
    )

    assert sum(node.kind == "radical" for node in simple.nodes) == 1
    assert sum(node.kind == "radical" for node in complex_layout.nodes) == 2
    radical_rules = [
        rule
        for rule in complex_layout.rules
        if rule.role.startswith("radical-")
    ]
    assert len(radical_rules) == 8
    for group_start in (0, 4):
        group = radical_rules[group_start : group_start + 4]
        assert [rule.role for rule in group] == [
            "radical-hook",
            "radical-descender",
            "radical-stem",
            "radical-vinculum",
        ]
        for first, second in itertools.pairwise(group):
            assert first.x2 == pytest.approx(second.x1)
            assert first.y2 == pytest.approx(second.y1)
    for layout in (simple, complex_layout):
        for rule in layout.rules:
            assert 0.0 <= min(rule.x1, rule.x2)
            assert max(rule.x1, rule.x2) <= layout.width + 1e-7
            assert 0.0 <= min(rule.y1, rule.y2)
            assert max(rule.y1, rule.y2) <= layout.height + 1e-7


def test_script_rows_reserve_semantic_and_issued_pdf_clearance() -> None:
    pdf, table, script_rises = _fixture()

    assert table._sector_script_source_rows == (1, 2, 3, 4, 5)
    assert table._sector_script_table_rows == (4, 5, 6, 7, 8)
    minimum_script_height = (
        table._sector_script_leading
        + table._sector_script_top_padding
        + table._sector_script_bottom_padding
    )
    for row_index in table._sector_script_table_rows:
        assert table._rowHeights[row_index] >= minimum_script_height - 1e-7
    assert script_rises["subscript"] == pytest.approx(
        -table._sector_subscript_rise
    )
    assert script_rises["superscript"] == pytest.approx(
        table._sector_superscript_rise
    )

    scripts, horizontal_rules = _script_baselines_and_grid_rules(pdf)
    assert {text for text, _baseline, _size in scripts} == {
        "p(0)",
        "p0.1k",
        "pk",
        "ut",
    }
    for text, baseline, font_size in scripts:
        lower_rule = max(rule for rule in horizontal_rules if rule < baseline)
        upper_rule = min(rule for rule in horizontal_rules if rule > baseline)
        # pypdf reports text origins rather than font ink boxes, so these checks
        # deliberately assert bracketing geometry only.  The reviewed raster
        # below is the physical-ink acceptance for rule clearance.
        assert baseline - lower_rule >= font_size * 0.5, text
        assert upper_rule - baseline >= font_size * 0.75, text


def test_typography_fixture_matches_reviewed_pdf_raster() -> None:
    pdf, _table, _script_rises = _fixture()
    page = _render_first_page(pdf)

    assert page.size == (1786, 2526)
    assert crop_sha256(page, _TYPOGRAPHY_CROP) == _TYPOGRAPHY_CROP_SHA256


def test_typography_test_source_remains_ascii() -> None:
    assert pathlib.Path(__file__).read_bytes().isascii()
