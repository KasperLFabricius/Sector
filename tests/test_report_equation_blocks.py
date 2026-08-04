from __future__ import annotations

import ast
import io
import pathlib
import sys

import pypdf
import pytest
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import report_equation_blocks as equation_blocks  # noqa: E402
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


def _key_and_variants(call):
    key_node = next(
        keyword.value for keyword in call.keywords
        if keyword.arg == "equation_key"
    )
    if isinstance(key_node, ast.Constant):
        key = key_node.value
    else:
        assert ast.unparse(key_node) == (
            "f'materials.steel.fyd-{material_index + 1}'"
        )
        key = "materials.steel.fyd-*"

    variant_nodes = [
        keyword.value for keyword in call.keywords
        if keyword.arg == "equation_variant"
    ]
    assert len(variant_nodes) <= 1
    if not variant_nodes:
        return key, (None,)
    node = variant_nodes[0]
    if isinstance(node, ast.Constant):
        return key, (node.value,)
    assert ast.unparse(node) == "'2023' if model_2023 else '2005'"
    return key, ("2023", "2005")


def test_retained_formula_inventory_resolves_every_exact_block_specification():
    tree = ast.parse(
        (ROOT / "app" / "sector_report.py").read_text(encoding="utf-8")
    )
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_formula"
    ]
    assert len(calls) == 61

    used = set()
    result_calls = 0
    for call in calls:
        assert not any(
            keyword.arg == "equation_spec" for keyword in call.keywords
        ), f"line {call.lineno} bypasses the production block catalog"
        key, variants = _key_and_variants(call)
        has_result = any(
            keyword.arg == "result" for keyword in call.keywords
        )
        result_calls += int(has_result)
        for variant in variants:
            spec = equation_blocks.equation_block_spec(key, variant)
            assert (spec.result_unit is not None) is has_result, (
                call.lineno, key, variant
            )
            used.add((key, variant))

    catalog = dict(equation_blocks.equation_block_spec_items())
    assert len(catalog) == 62
    assert used == set(catalog)
    assert result_calls == 45


@pytest.mark.parametrize(
    "catalog_key,spec",
    equation_blocks.equation_block_spec_items(),
    ids=lambda value: str(value)[:80],
)
def test_every_catalog_variant_builds_complete_parseable_symbol_rows(
    catalog_key, spec
):
    key, variant = catalog_key
    runtime_key = "materials.steel.fyd-1" if key.endswith("-*") else key
    builder = _builder()
    builder._h1("Catalog probe")
    kwargs = {}
    if spec.result_unit is not None:
        kwargs["result"] = "published result"
    builder._formula(
        "x = 1",
        equation_key=runtime_key,
        equation_variant=variant,
        **kwargs,
    )
    equation = builder.flow[-1]
    assert equation._sector_equation_symbols == spec.symbols
    assert equation._sector_equation_result_unit == spec.result_unit
    symbol_rows = [
        child for child in equation._content
        if child._sector_equation_role == "symbol"
    ]
    assert len(symbol_rows) == len(spec.symbols)
    for row in equation._content:
        row.wrap(160 * mm, 250 * mm)


def test_equation_block_has_frozen_roles_symbols_result_unit_and_pdf_text():
    builder = _builder()
    builder._h1("Shear")
    builder._h2("Resistance")
    builder._formula(
        "V<sub>Rd,c</sub> = max(tau<sub>1</sub>, tau<sub>2</sub>) b<sub>w</sub> z",
        ref="Project-defined / uncited.",
        subst="max(0.55, 0.42) x 300 x 450 / 1000",
        result="V<sub>Rd,c</sub> = 74.25 kN",
        equation_key="shear.2023.vrdc",
    )

    equation = builder.flow[-1]
    spec = equation_blocks.equation_block_spec("shear.2023.vrdc")
    roles = [child._sector_equation_role for child in equation._content]
    assert roles == [
        "identity", "expression", "substitution", "result", "unit",
        "symbols-heading", *("symbol" for _ in spec.symbols), "source",
    ]
    assert equation._sector_equation_result_unit == "kN"
    assert equation._sector_equation_symbols == spec.symbols
    assert [
        child._sector_equation_symbol
        for child in equation._content
        if child._sector_equation_role == "symbol"
    ] == list(spec.symbols)

    plain = equation.getPlainText()
    for required in (
        "Symbolic expression:", "Numerical substitution:", "Result:",
        "Unit: kN", "Symbols:", "VRd,c - concrete shear resistance",
        "Source / method note: Project-defined / uncited.",
    ):
        assert required in plain

    text = "\n".join(
        page.extract_text() or ""
        for page in pypdf.PdfReader(io.BytesIO(_pdf(builder.flow))).pages
    )
    assert "Symbolic expression:" in text
    assert "Numerical substitution:" in text
    assert "Unit: kN" in text
    assert "Symbols:" in text


def test_block_validation_is_atomic_for_content_catalog_and_unit_mismatches():
    relation = equation_blocks.EquationBlockSpec(
        (("x", "test scalar", "1"),), None
    )
    result = equation_blocks.EquationBlockSpec(
        (("R", "test resistance", "kN"),), "kN"
    )
    builder = _builder()
    builder._h1("Checks")
    before = len(builder.flow)

    attempts = (
        pytest.param(
            lambda: builder._formula(
                "x = 1", equation_key="unknown.valid"
            ),
            "No report equation-block specification",
            id="unknown-catalog-key",
        ),
        pytest.param(
            lambda: builder._formula(
                " ", equation_key="blank.expression", equation_spec=relation
            ),
            "requires an expression",
            id="blank-expression",
        ),
        pytest.param(
            lambda: builder._formula(
                "x = 1", subst=" ", equation_key="blank.substitution",
                equation_spec=relation,
            ),
            "blank substitution",
            id="blank-substitution",
        ),
        pytest.param(
            lambda: builder._formula(
                "R = 1", result=" ", equation_key="blank.result",
                equation_spec=result,
            ),
            "blank result",
            id="blank-result",
        ),
        pytest.param(
            lambda: builder._formula(
                "R = 1", equation_key="missing.result", equation_spec=result
            ),
            "requires its specified result",
            id="missing-result",
        ),
        pytest.param(
            lambda: builder._formula(
                "x = 1", result="x = 1", equation_key="missing.unit",
                equation_spec=relation,
            ),
            "without a unit",
            id="result-without-unit",
        ),
        pytest.param(
            lambda: builder._formula(
                "x = 1", equation_key="variant.override",
                equation_variant="2005", equation_spec=relation,
            ),
            "cannot combine a variant and override",
            id="variant-and-override",
        ),
    )
    for attempt in attempts:
        function, message = attempt.values[:2]
        with pytest.raises(ValueError, match=message):
            function()
        assert len(builder.flow) == before
        assert builder._equation_number == 0
        assert builder._equations == {}


@pytest.mark.parametrize(
    "symbols,result_unit,message",
    [
        ((), None, "requires symbol definitions"),
        ((("x", "meaning", "1"), ("x", "other", "1")), None, "Duplicate"),
        ((("x", " ", "1"),), None, "non-blank"),
        ((("x", "meaning", "1"),), " ", "non-blank"),
    ],
)
def test_equation_block_spec_rejects_incomplete_symbol_and_unit_contracts(
    symbols, result_unit, message
):
    with pytest.raises(ValueError, match=message):
        equation_blocks.EquationBlockSpec(symbols, result_unit)


def test_long_expression_and_symbol_inventory_wrap_inside_one_pdf_page():
    spec = equation_blocks.EquationBlockSpec(
        tuple(
            (f"x<sub>{index}</sub>", f"retained contribution {index}", "kN")
            for index in range(1, 13)
        ),
        "kN",
    )
    builder = _builder()
    builder._h1("Long equations")
    builder._formula(
        "R=" + "x" * 260,
        ref="Project-defined / uncited.",
        result="R = 12 kN",
        equation_key="long.unbroken.expression",
        equation_spec=spec,
    )
    equation = builder.flow[-1]
    expression = next(
        child for child in equation._content
        if child._sector_equation_role == "expression"
    )
    _, height = expression.wrap(160 * mm, 250 * mm)
    assert builder.s["formula"].splitLongWords == 1
    assert height > builder.s["formula"].leading

    pages = pypdf.PdfReader(io.BytesIO(_pdf(builder.flow))).pages
    assert len(pages) == 1
    text = pages[0].extract_text() or ""
    assert "EQ-LONG.UNBROKEN.EXPRESSION" in text
    assert "retained contribution 12" in text
    assert "Source / method note: Project-defined / uncited." in text
