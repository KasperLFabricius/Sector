"""Browser-free contract for the shared publication equation renderer."""

from __future__ import annotations

import io
import pathlib
import re
import sys
from dataclasses import FrozenInstanceError, replace

import pypdf
import pypdfium2
import pytest
from PIL import Image, ImageChops
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import publication_equation_layout as equations

SQRT = chr(0x221A)
LE = chr(0x2264)
SIGMA = chr(0x03C3)
GAMMA = chr(0x03B3)


def _block(*, identity: str | None = "Equation (7.11)") -> equations.EquationBlock:
    symbolic = equations.compile_manual_math(
        r"w_k=\frac{\sqrt{a^2+b^2}}{\gamma_c}"
    )
    substitution = equations.compile_report_math(
        "w<sub>k</sub> = sqrt((3.0<super>2</super> + "
        "4.0<super>2</super>) / 1.5)"
    )
    result = equations.compile_report_math("w<sub>k</sub> = 3.333 mm")
    return equations.EquationBlock(
        (
            equations.EquationLine("symbolic", symbolic, "Symbolic"),
            equations.EquationLine(
                "substitution", substitution, "Substitution"
            ),
            equations.EquationLine("result", result, "Result"),
        ),
        identity=identity,
        source="EN 1992-1-1 Formula (7.11)",
    )


def _pdf(flow: list[object]) -> bytes:
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )
    document.build(flow)
    return buffer.getvalue()


def _page_texts(pdf: bytes) -> list[str]:
    return [
        page.extract_text() or ""
        for page in pypdf.PdfReader(io.BytesIO(pdf)).pages
    ]


def _font_objects(reader: pypdf.PdfReader) -> list[object]:
    found = []
    for page in reader.pages:
        resources = page["/Resources"].get_object()
        fonts = resources.get("/Font")
        if fonts is None:
            continue
        found.extend(reference.get_object() for reference in fonts.get_object().values())
    return found


def test_display_tree_and_publication_contracts_are_frozen_and_exact() -> None:
    variable = equations.Variable("x")
    tree = equations.Script(
        variable,
        equations.Upright("Ed"),
        equations.Number("2"),
    )
    line = equations.EquationLine("symbolic", tree, "Symbolic")
    block = equations.EquationBlock((line,), identity="Equation (1.1)")

    assert type(block.lines) is tuple
    assert equations.linear_math_text(tree) == "x_(Ed)^(2)"
    with pytest.raises(FrozenInstanceError):
        variable.text = "y"
    with pytest.raises(FrozenInstanceError):
        block.identity = "changed"
    with pytest.raises((TypeError, equations.EquationLayoutError)):
        equations.MathSequence([variable])
    with pytest.raises(TypeError):
        equations.EquationBlock([line])


def test_every_public_value_record_is_slot_only_hashable_and_tuple_sealed() -> None:
    variable = equations.Variable("x")
    text = equations.TextPlacement(
        "x", 0.0, 1.0, "face", 10.0, 0.18, "#202020", "variable"
    )
    rule = equations.RulePlacement(
        0.0, 1.0, 2.0, 1.0, 0.5, "#202020", "fraction-rule"
    )
    bounds = equations.Bounds(0.0, 0.0, 2.0, 2.0)
    node_placement = equations.NodePlacement("variable", bounds)
    row = equations.EquationRowLayout("symbolic", bounds, 1.0, False)
    layout = equations.MathLayout(
        2.0, 2.0, 1.0, (text,), (rule,), (node_placement,)
    )
    line = equations.EquationLine("symbolic", variable)
    records = (
        equations.EquationFonts(),
        equations.EquationStyle(),
        variable,
        equations.Upright("max"),
        equations.Number("1"),
        equations.Operator("+"),
        equations.Unit("MPa"),
        equations.LiteralText("verified result"),
        equations.MathSpace(),
        equations.MathSequence((variable, equations.Number("1"))),
        equations.Fraction(variable, equations.Number("2")),
        equations.Radical(variable),
        equations.Script(variable, equations.Upright("Ed")),
        equations.Overbar(variable),
        equations.RelationFragment(equations.Operator("="), variable),
        equations.Delimited(variable),
        line,
        equations.EquationBlock((line,)),
        bounds,
        text,
        rule,
        node_placement,
        layout,
        row,
        equations.EquationGeometry(
            2.0, 2.0, (text,), (rule,), (node_placement,), (row,)
        ),
    )

    for record in records:
        assert not hasattr(record, "__dict__")
        assert isinstance(hash(record), int)
        with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
            record.unowned_attribute = "mutation"
    with pytest.raises(TypeError):
        equations.MathLayout(2.0, 2.0, 1.0, [text], (rule,), (node_placement,))
    with pytest.raises(TypeError):
        equations.EquationGeometry(
            2.0, 2.0, (text,), (rule,), (node_placement,), [row]
        )


def test_manual_compiler_builds_nested_structural_math() -> None:
    tree = equations.compile_manual_math(
        r"\log_{10}N_R=C\frac{1-E_{max}}"
        r"{\sqrt{1-\frac{E_{min}}{E_{max}}}}"
    )
    layout = equations.layout_math(tree)
    kinds = [item.kind for item in layout.nodes]

    assert kinds.count("fraction") == 2
    assert "radical" in kinds
    assert kinds.count("script") >= 4
    assert any(text.text == "log" and text.slant == 0.0 for text in layout.texts)
    radical_roles = {
        rule.role for rule in layout.rules if rule.role.startswith("radical-")
    }
    assert {
        "radical-hook",
        "radical-descender",
        "radical-stem",
        "radical-vinculum",
    } <= radical_roles
    radical_rules = {
        rule.role: rule for rule in layout.rules if rule.role.startswith("radical-")
    }
    for first, second in (
        ("radical-hook", "radical-descender"),
        ("radical-descender", "radical-stem"),
        ("radical-stem", "radical-vinculum"),
    ):
        assert radical_rules[first].x2 == pytest.approx(radical_rules[second].x1)
        assert radical_rules[first].y2 == pytest.approx(radical_rules[second].y1)
    assert sum(rule.role == "fraction-rule" for rule in layout.rules) == 2
    assert "sqrt" in equations.linear_math_text(tree)


def test_report_compiler_builds_fraction_scripts_greek_and_scaled_delimiters() -> None:
    tree = equations.compile_report_math(
        "sigma<sub>s</sub> = sqrt((a<super>2</super> + "
        "b<super>2</super>) / gamma<sub>c</sub>) &lt;= 25 MPa"
    )
    layout = equations.layout_math(tree)

    assert any(text.text == SIGMA and text.slant > 0.0 for text in layout.texts)
    assert any(text.text == GAMMA and text.slant > 0.0 for text in layout.texts)
    assert any(text.text == LE for text in layout.texts)
    assert any(text.text == "MPa" and text.slant == 0.0 for text in layout.texts)
    assert any(node.kind == "fraction" for node in layout.nodes)
    scaled = equations.layout_math(
        equations.compile_manual_math(r"\left(\frac{a}{b}\right)")
    )
    delimiters = [node for node in scaled.nodes if node.kind == "delimited"]
    assert delimiters
    assert max(node.bounds.height for node in delimiters) >= max(
        node.bounds.height for node in scaled.nodes if node.kind == "fraction"
    )


def test_report_corpus_aliases_entities_groups_and_radical_dialects_compile() -> None:
    superscript = equations.compile_report_math(
        "N<sub>R,i</sub> = N<super>*</super> "
        "(Delta sigma<sub>Rd</sub> / Delta sigma<sub>Ed,i</sub>)"
        "<super>k</super>"
    )
    alias = equations.compile_report_math("a<sup>2</sup> + b<super>2</super>")
    detailing = equations.compile_report_math(
        "&#961;<sub>w,min</sub> = 0.080 &#8730;f<sub>ck</sub> / "
        "f<sub>ywk</sub>"
    )
    grouped = equations.compile_report_math(
        "w<sub>k</sub> = {&#189;&#183;s<sub>r,max</sub>} &#183; eps"
    )
    overbar = equations.compile_report_math(
        "s&#772;<sub>c,eff</sub> = s&#772;<sub>s,t</sub>"
    )
    report_root = equations.compile_report_math(
        "sqrt[phi / (1 + phi)]"
    )
    manual_root = equations.compile_manual_math(r"\sqrt[3]{x}")

    assert "^(*)" in equations.linear_math_text(superscript)
    assert equations.linear_math_text(alias) == "a^(2) + b^(2)"
    assert any(node.kind == "radical" for node in equations.layout_math(detailing).nodes)
    assert any(node.kind == "fraction" for node in equations.layout_math(grouped).nodes)
    assert sum(
        rule.role == "overbar-rule"
        for rule in equations.layout_math(overbar).rules
    ) == 2
    assert "sqrt(" in equations.linear_math_text(report_root)
    assert "sqrt[" not in equations.linear_math_text(report_root)
    assert equations.linear_math_text(manual_root).startswith("sqrt[3](")


@pytest.mark.parametrize(
    ("compiler_name", "source", "symbol", "expected_count"),
    (
        (
            "compile_report_math",
            "N<sub>int</sub> = F<sub>c</sub> + F<sub>s</sub> + F<sub>p</sub>",
            "N",
            1,
        ),
        (
            "compile_report_math",
            "rho<sub>s,min</sub> = m<sub>s</sub> rho<sub>s,min,base</sub>",
            "m",
            1,
        ),
        (
            "compile_report_math",
            (
                "N<sub>R,i</sub> = N<super>*</super> "
                "(Delta sigma<sub>Rd</sub> / Delta sigma<sub>Ed,i</sub>)"
                "<super>k</super>"
            ),
            "N",
            2,
        ),
        (
            "compile_manual_math",
            r"\rho_{s,\min}=m_s\sqrt{\frac{\phi f_{ct,eff}}{4E_{sk}kw_k}}",
            "m",
            1,
        ),
        (
            "compile_manual_math",
            (
                r"N_{R,i}=N^*\left(\frac{\Delta\sigma_{Rd}}"
                r"{\Delta\sigma_{Ed,i}}\right)^{k}"
            ),
            "N",
            2,
        ),
        (
            "compile_manual_math",
            r"\log_{10}N_R=C\frac{1-E_{max}}{\sqrt{1-R}}",
            "N",
            1,
        ),
        (
            "compile_report_math",
            "sigma<sub>N,v</sub> = sigma<sub>N</sub> + sigma<sub>M</sub>",
            "N",
            2,
        ),
        (
            "compile_report_math",
            "s<sub>r,m,cal</sub> = 1.5 c",
            "m",
            1,
        ),
        (
            "compile_manual_math",
            r"s_{r,m,cal}=1.5c",
            "m",
            1,
        ),
    ),
)
def test_ambiguous_single_letter_quantity_symbols_remain_italic(
    compiler_name: str,
    source: str,
    symbol: str,
    expected_count: int,
) -> None:
    compiler = getattr(equations, compiler_name)
    layout = equations.layout_math(compiler(source))
    placements = [text for text in layout.texts if text.text == symbol]

    assert len(placements) == expected_count
    assert all(text.role == "variable" for text in placements)
    assert all(
        text.slant
        == pytest.approx(equations.DEFAULT_EQUATION_STYLE.fonts.scalar_slant)
        for text in placements
    )


@pytest.mark.parametrize(
    ("source", "symbol"),
    (
        ("= 0.175 m", "m"),
        ("= 0.18 m<super>2</super>", "m"),
        ("= 0.0035 1/m", "m"),
        ("= 14 N", "N"),
        ("= 76.4 kN&#183;m", "m"),
    ),
)
def test_ambiguous_single_letter_numeric_units_remain_upright(
    source: str,
    symbol: str,
) -> None:
    layout = equations.layout_math(equations.compile_report_fragment(source))
    placements = [text for text in layout.texts if text.text == symbol]

    assert len(placements) == 1
    assert placements[0].role == "unit"
    assert placements[0].slant == 0.0


def test_same_single_letter_is_contextual_on_both_sides_of_a_relation() -> None:
    layout = equations.layout_math(
        equations.compile_report_math("m = 0.175 m")
    )
    placements = [text for text in layout.texts if text.text == "m"]

    assert [text.role for text in placements] == ["variable", "unit"]
    assert placements[0].slant == pytest.approx(
        equations.DEFAULT_EQUATION_STYLE.fonts.scalar_slant
    )
    assert placements[1].slant == 0.0


def test_ambiguous_unit_chain_and_relation_suffix_remain_upright() -> None:
    chain = equations.layout_math(
        equations.compile_report_fragment("= 14 N&#183;m")
    )
    equality = equations.layout_math(
        equations.compile_report_math("14 m = 14000 mm")
    )

    chain_units = [
        text for text in chain.texts if text.text in {"N", "m"}
    ]
    metre = next(text for text in equality.texts if text.text == "m")
    assert [text.role for text in chain_units] == ["unit", "unit"]
    assert all(text.slant == 0.0 for text in chain_units)
    assert metre.role == "unit"
    assert metre.slant == 0.0


def test_unseparated_coefficient_and_reciprocal_force_remain_variables() -> None:
    layout = equations.layout_math(
        equations.compile_report_math("R = 2m + 1/N")
    )
    placements = [text for text in layout.texts if text.text in {"m", "N"}]

    assert [text.role for text in placements] == ["variable", "variable"]
    assert all(
        text.slant
        == pytest.approx(equations.DEFAULT_EQUATION_STYLE.fonts.scalar_slant)
        for text in placements
    )


def test_role_specific_report_compilers_accept_fragments_and_verdicts_only_explicitly() -> None:
    fragment = equations.compile_report_fragment("= max(13.4 / (1 + 2.0), 0.123) MPa")
    percentage = equations.compile_report_fragment("= 83.2%")
    cracked = equations.compile_report_math(
        "lambda<sub>cr</sub> = 0.925  ->  section is cracked "
        "(cracks when lambda<sub>cr</sub> &lt;= 1)"
    )
    invalid = equations.compile_report_math(
        "lambda<sub>cr</sub> = 1.125 -> INVALID; "
        "no verified cracking classification"
    )
    literal = equations.compile_report_literal(
        "Retained long-term reference-stress plane (x and y in m)."
    )

    assert isinstance(fragment, equations.RelationFragment)
    assert equations.linear_math_text(fragment).startswith("= max(")
    assert equations.linear_math_text(percentage) == "= 83.2%"
    with pytest.raises(equations.EquationLayoutError, match="duplicate postfix percent"):
        equations.compile_report_fragment("= 83.2%%")
    assert "section is cracked" in equations.linear_math_text(cracked)
    assert "INVALID; no verified" in equations.linear_math_text(invalid)
    assert isinstance(literal, equations.LiteralText)
    with pytest.raises(equations.EquationLayoutError):
        equations.compile_report_math("= 13.4 / (1 + 2.0)")
    with pytest.raises(equations.EquationLayoutError, match="raw markup"):
        equations.compile_report_literal("<b>untrusted</b>")


def test_equation_line_semantic_text_accepts_relations_but_rejects_markup_and_tex() -> None:
    expression = equations.compile_report_math("x = y")

    for semantic in ("x < y", "x -> y"):
        line = equations.EquationLine(
            "symbolic",
            expression,
            "Symbolic:",
            semantic,
        )
        assert line.semantic_text == semantic
    for semantic in ("<b>x</b>", r"\frac{x}{y}", "$x$"):
        with pytest.raises(equations.EquationLayoutError):
            equations.EquationLine(
                "symbolic",
                expression,
                "Symbolic:",
                semantic,
            )


def test_relation_alignment_preserves_internal_authored_spaces() -> None:
    spaced = equations.EquationBlock(
        (
            equations.EquationLine(
                "symbolic", equations.compile_report_math("a b = c d")
            ),
        )
    )
    compact = equations.EquationBlock(
        (
            equations.EquationLine(
                "symbolic", equations.compile_report_math("ab = cd")
            ),
        )
    )
    spaced_axis = equations.layout_equation(spaced, 300.0).rows[0].relation_x
    compact_axis = equations.layout_equation(compact, 300.0).rows[0].relation_x

    assert spaced_axis is not None and compact_axis is not None
    assert spaced_axis > compact_axis


def test_long_unbreakable_rhs_hangs_below_the_aligned_relation_without_clipping() -> None:
    block = equations.EquationBlock(
        (
            equations.EquationLine(
                "reference",
                equations.compile_report_math(
                    "sigma<sub>total,Ed,el,reinforcement,candidate</sub> = 1.0"
                ),
                "Reference:",
            ),
            equations.EquationLine(
                "symbolic",
                equations.compile_report_math(
                    "eta<sub>cc</sub> = min(1.10064242, 1.00000000)"
                ),
                "Symbolic expression:",
            ),
        )
    )

    geometry = equations.layout_equation(block, 380.0)

    symbolic_rows = [row for row in geometry.rows if row.role == "symbolic"]
    assert len(symbolic_rows) == 2
    assert symbolic_rows[0].relation_x is not None
    assert symbolic_rows[1].relation_x is None
    assert all(
        0.0 <= node.bounds.x
        and node.bounds.right <= geometry.width + 1e-7
        for node in geometry.nodes
    )


def test_long_result_label_moves_above_math_and_remains_visible_once() -> None:
    label = (
        "Result - retained resistance "
        "[dimensionless; displayed as percent]:"
    )
    block = equations.EquationBlock(
        (
            equations.EquationLine(
                "symbolic",
                equations.compile_report_math("u = R<sub>Ed</sub>/R<sub>Rd</sub>"),
                "Symbolic expression:",
            ),
            equations.EquationLine(
                "substitution",
                equations.compile_report_fragment("= 0.832"),
                "Numerical substitution:",
            ),
            equations.EquationLine(
                "result",
                equations.compile_report_math("u = 83.2%"),
                label,
            ),
        )
    )

    geometry = equations.layout_equation(block, 300.0)

    label_rows = [
        placement.text
        for placement in geometry.texts
        if placement.role == "label-result"
    ]
    assert " ".join(label_rows) == label
    relation_axes = [
        row.relation_x for row in geometry.rows if row.relation_x is not None
    ]
    assert len(relation_axes) == 3
    assert relation_axes == pytest.approx([relation_axes[0]] * 3)
    assert all(
        0.0 <= node.bounds.x
        and node.bounds.right <= geometry.width + 1e-7
        for node in geometry.nodes
    )


def test_every_governed_manual_expression_compiles_without_migration_loss() -> None:
    import manual
    import manual_equation_publication as publication

    governed = tuple(
        block[1].equation.equation.expression
        for block in publication.manual_publication_blocks(manual.manual_blocks())
        if block[0] == publication.EQUATION_BLOCK
    )

    assert len(governed) == 33
    assert all(
        isinstance(equations.compile_manual_math(source), equations.MathNode)
        for source in governed
    )


@pytest.mark.parametrize(
    ("compiler", "source", "message"),
    [
        (equations.compile_manual_math, r"\matrix{a}", "unsupported manual"),
        (equations.compile_manual_math, r"\frac{}{b}", "empty"),
        (equations.compile_manual_math, r"\sqrt{}", "empty"),
        (equations.compile_manual_math, r"_i", "detached script"),
        (equations.compile_manual_math, r"a_{i", "unbalanced"),
        (equations.compile_manual_math, r"a<b", "raw markup"),
        (equations.compile_report_math, "a<sup>2</super>", "malformed"),
        (equations.compile_report_math, "a &copy; b", "unsupported entity"),
        (equations.compile_report_math, r"a \frac b", "raw TeX"),
        (equations.compile_report_math, "sqrt()", "empty"),
        (equations.compile_report_math, "a /", "empty right operand"),
        (equations.compile_report_math, "a<sub></sub>", "empty"),
    ],
)
def test_compilers_fail_closed_for_unsupported_or_malformed_input(
    compiler, source: str, message: str
) -> None:
    with pytest.raises(equations.EquationLayoutError, match=message):
        compiler(source)


def test_math_geometry_keeps_every_node_and_rule_inside_measured_bounds() -> None:
    tree = equations.compile_manual_math(
        r"\left[\frac{\sqrt[3]{a_i^2+b_i^2}}{c_{eff}}\right]^{1/2}"
    )
    layout = equations.layout_math(tree)

    assert layout.width > 0.0 and layout.height > 0.0
    assert 0.0 <= layout.baseline <= layout.height
    for node in layout.nodes:
        assert node.bounds.x >= -1e-7
        assert node.bounds.y >= -1e-7
        assert node.bounds.right <= layout.width + 1e-7
        assert node.bounds.top <= layout.height + 1e-7
    for rule in layout.rules:
        assert -1e-7 <= rule.x1 <= layout.width + 1e-7
        assert -1e-7 <= rule.x2 <= layout.width + 1e-7
        assert -1e-7 <= rule.y1 <= layout.height + 1e-7
        assert -1e-7 <= rule.y2 <= layout.height + 1e-7


def test_long_root_index_and_large_inline_identity_expand_measured_bounds() -> None:
    indexed = equations.layout_math(
        equations.compile_manual_math(r"\sqrt[123456789]{x}+y")
    )
    for node in indexed.nodes:
        assert node.bounds.x >= -1e-7
        assert node.bounds.y >= -1e-7
        assert node.bounds.right <= indexed.width + 1e-7
        assert node.bounds.top <= indexed.height + 1e-7
    for rule in indexed.rules:
        assert max(rule.x1, rule.x2) <= indexed.width + 1e-7
        assert max(rule.y1, rule.y2) <= indexed.height + 1e-7

    block = equations.EquationBlock(
        (
            equations.EquationLine(
                "symbolic", equations.compile_report_math("R = a + b")
            ),
        ),
        identity="Equation (large identity)",
    )
    style = replace(equations.DEFAULT_EQUATION_STYLE, identity_size=30.0)
    geometry = equations.layout_equation(block, 520.0, style=style)
    identity_nodes = [node for node in geometry.nodes if node.kind == "identity"]

    assert identity_nodes
    assert all(node.bounds.y >= -1e-7 for node in identity_nodes)
    assert all(node.bounds.top <= geometry.height + 1e-7 for node in identity_nodes)


def test_scalar_italics_are_deliberate_and_upright_roles_remain_upright() -> None:
    tree = equations.math_sequence(
        equations.Variable("x"),
        equations.MathSpace(),
        equations.Upright("max"),
        equations.MathSpace(),
        equations.Unit("MPa"),
    )
    layout = equations.layout_math(tree)
    by_text = {placement.text: placement for placement in layout.texts}

    assert by_text["x"].slant == pytest.approx(0.18)
    assert by_text["max"].slant == 0.0
    assert by_text["MPa"].slant == 0.0
    assert by_text["x"].font_name == by_text["max"].font_name


def test_aligned_rows_share_one_relation_axis_and_wrap_only_at_top_level() -> None:
    long_right = " + ".join(f"q<sub>{index}</sub>" for index in range(1, 9))
    block = equations.EquationBlock(
        (
            equations.EquationLine(
                "symbolic",
                equations.compile_report_math("R = " + long_right),
                "Symbolic",
            ),
            equations.EquationLine(
                "substitution",
                equations.compile_report_math("R<sub>d</sub> = 1 + 2 + 3 + 4"),
                "Substitution",
            ),
            equations.EquationLine(
                "result",
                equations.compile_report_math("R = 10 kN"),
                "Result",
            ),
        ),
        identity="Equation (6.29)",
        source="Project-defined method",
    )
    geometry = equations.layout_equation(block, 220.0)
    first_rows = [row for row in geometry.rows if not row.continuation]
    relation_axes = [row.relation_x for row in first_rows]

    assert len(geometry.rows) > len(block.lines)
    assert all(axis is not None for axis in relation_axes)
    assert max(axis for axis in relation_axes if axis is not None) == pytest.approx(
        min(axis for axis in relation_axes if axis is not None)
    )
    assert all(row.relation_x is None for row in geometry.rows if row.continuation)
    assert any(text.role == "identity" for text in geometry.texts)
    assert geometry.height <= equations.DEFAULT_EQUATION_STYLE.maximum_height


def test_unbreakable_width_height_and_missing_font_fail_before_drawing() -> None:
    wide = equations.EquationBlock(
        (
            equations.EquationLine(
                "symbolic", equations.Variable("X" * 120), "Symbolic"
            ),
        )
    )
    with pytest.raises(equations.EquationLayoutError, match="unbreakable"):
        equations.layout_equation(wide, 160.0)

    with pytest.raises(equations.EquationLayoutError, match="high"):
        equations.layout_equation(
            _block(),
            480.0,
            style=replace(equations.DEFAULT_EQUATION_STYLE, maximum_height=30.0),
        )

    missing_fonts = equations.EquationFonts(
        regular="MissingEquationFace",
        bold="MissingEquationFace-Bold",
    )
    missing_style = replace(
        equations.DEFAULT_EQUATION_STYLE, fonts=missing_fonts
    )
    with pytest.raises(equations.EquationFontError, match="not registered"):
        equations.layout_equation(_block(), 480.0, style=missing_style)


def test_default_faces_are_embedded_greek_capable_and_never_helvetica() -> None:
    fonts = equations.register_default_equation_fonts()
    for name in (fonts.regular, fonts.bold):
        font = pdfmetrics.getFont(name)
        assert font.__class__.__name__ == "TTFont"
        for character in (SQRT, LE, SIGMA, GAMMA, chr(0x2211), chr(0x00B7)):
            assert ord(character) in font.face.charWidths
    assert "Helvetica" not in {fonts.regular, fonts.bold}


def test_pdf_is_searchable_vector_math_with_one_canonical_semantic_row() -> None:
    flowable = equations.EquationFlowable(_block())
    pdf = _pdf([flowable])
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    text = " ".join((reader.pages[0].extract_text() or "").split())

    for role in ("symbolic", "substitution", "result"):
        marker = f"SECTOR-MATH[{role}]"
        assert text.count(marker) == 1
    assert "Equation (7.11)" in text
    assert "EN 1992-1-1 Formula (7.11)" in text
    assert "sqrt" in text
    assert "frac" not in text and "\\" not in text

    resources = reader.pages[0]["/Resources"].get_object()
    assert not resources.get("/XObject")
    fonts = _font_objects(reader)
    embedded = [font for font in fonts if "DejaVuSans" in str(font.get("/BaseFont"))]
    assert embedded
    assert all(font.get("/ToUnicode") is not None for font in embedded)
    assert all("Helvetica" not in text.font_name for text in flowable.geometry.texts)

    operations = pypdf.generic.ContentStream(
        reader.pages[0].get_contents(), reader
    ).operations
    operators = [operator for _operands, operator in operations]
    assert operators.count(b"S") >= 2
    assert b"m" in operators and b"l" in operators


def test_pdfium_raster_is_visible_in_colour_and_grayscale_without_edge_clipping() -> None:
    pdf = _pdf([equations.EquationFlowable(_block())])
    document = pypdfium2.PdfDocument(pdf)
    try:
        page = document[0]
        try:
            colour = page.render(scale=2.0).to_pil().convert("RGB")
            grayscale = page.render(scale=2.0, grayscale=True).to_pil().convert("L")
        finally:
            page.close()
    finally:
        document.close()

    colour_ink = ImageChops.difference(
        colour, Image.new("RGB", colour.size, "white")
    ).getbbox()
    gray_ink = ImageChops.difference(
        grayscale, Image.new("L", grayscale.size, "white")
    ).getbbox()

    assert colour_ink is not None and gray_ink is not None
    for bounds, size in ((colour_ink, colour.size), (gray_ink, grayscale.size)):
        left, top, right, bottom = bounds
        assert left >= 20 and top >= 20
        assert right <= size[0] - 20 and bottom <= size[1] - 20
        assert right - left > 300 and bottom - top > 40
    assert sum(grayscale.histogram()[:245]) > 1_000
    assert all(abs(colour_ink[index] - gray_ink[index]) <= 2 for index in range(4))


def test_equation_is_indivisible_at_a_page_foot_without_orphan_roles() -> None:
    styles = getSampleStyleSheet()
    flowable = equations.EquationFlowable(_block(identity="Equation (P-1)"))
    pdf = _pdf(
        [
            Paragraph("PRECEDING PAGE", styles["Normal"]),
            Spacer(1, 620.0),
            flowable,
        ]
    )
    pages = _page_texts(pdf)

    assert len(pages) == 2
    assert "PRECEDING PAGE" in pages[0]
    assert "SECTOR-MATH" not in pages[0]
    for expected in (
        "Equation (P-1)",
        "SECTOR-MATH[symbolic]",
        "SECTOR-MATH[substitution]",
        "SECTOR-MATH[result]",
        "EN 1992-1-1 Formula (7.11)",
    ):
        assert expected in pages[1]


def test_flowable_exposes_geometry_only_after_wrap_and_never_splits() -> None:
    flowable = equations.EquationFlowable(_block())
    with pytest.raises(equations.EquationLayoutError, match="before wrap"):
        _ = flowable.geometry

    width, height = flowable.wrap(480.0, 20.0)
    assert width == pytest.approx(480.0)
    assert height == pytest.approx(flowable.geometry.height)
    assert height > 20.0
    assert flowable.split(480.0, 20.0) == []


def test_source_files_remain_ascii_despite_runtime_math_glyphs() -> None:
    for path in (
        ROOT / "app" / "publication_equation_layout.py",
        ROOT / "tests" / "test_publication_equation_layout.py",
    ):
        assert path.read_bytes().isascii()
    assert re.fullmatch(r"[\x00-\x7f]*", __doc__ or "")
