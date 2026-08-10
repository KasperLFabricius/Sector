from __future__ import annotations

import ast
import collections
import io
import pathlib
import re
import sys
from types import SimpleNamespace

import pypdf
import pytest
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import sector_report

from app import publication_equation_layout as publication_equations

_TEST_RELATION = sector_report.report_equation_contract.EquationContract(
    symbols=(
        sector_report.report_equation_contract.EquationSymbol("x", "test symbol"),
    ),
)
_TEST_NUMERIC_RESULT = sector_report.report_equation_contract.EquationContract(
    symbols=(
        sector_report.report_equation_contract.EquationSymbol("R", "test result", "kN"),
    ),
    result_symbol="R",
    result_unit="kN",
    substitution_role="numerical",
)
_TEST_NUMERIC_RESULT_WITH_NOTE = (
    sector_report.report_equation_contract.EquationContract(
        symbols=_TEST_NUMERIC_RESULT.symbols,
        result_symbol="R",
        result_unit="kN",
        substitution_role="numerical",
        applicability_note_required=True,
    )
)
_TEST_DIRECT_RESULT = sector_report.report_equation_contract.EquationContract(
    symbols=(
        sector_report.report_equation_contract.EquationSymbol("R", "test result", "kN"),
    ),
    result_symbol="R",
    result_unit="kN",
)

EM_DASH = chr(0x2014)
SUM = chr(0x2211)
LE = chr(0x2264)
TIMES = chr(0x00D7)


def _builder(*, profile="Standard"):
    builder = sector_report.ReportBuilder(
        io.BytesIO(), {}, {}, {}, figures=False, profile=profile
    )
    formula = builder._formula

    def contracted_formula(*args, **kwargs):
        if "equation_spec" not in kwargs:
            result = kwargs.get("result")
            substitution = kwargs.get("subst")
            kwargs["equation_spec"] = (
                _TEST_NUMERIC_RESULT if result and substitution
                else _TEST_DIRECT_RESULT if result
                else _TEST_RELATION
            )
        return formula(*args, **kwargs)

    builder._formula = contracted_formula
    return builder


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


@pytest.mark.parametrize(
    ("source", "expected"),
    (
        (
            "= 14.000 + 14.500 + 14.5675",
            "= 14 + 14.5 + 14.568",
        ),
        ("= -0.000 MPa; 1 - 0.000", "= 0 MPa; 1 - 0"),
        (
            "= [-0.000, > -0.000, x - 0.000]",
            "= [0, > 0, x - 0]",
        ),
        ("= 0.0000004 + -0.0000004", "= 4e-7 + -4e-7"),
        (
            "= 0.00069 + 0.0015080 + 0.003500000",
            "= 6.9e-4 + 1.508e-3 + 3.5e-3",
        ),
        (
            "= 80.000000000x + 14.500MPa + 0.000000000y",
            "= 80x + 14.5MPa + 0y",
        ),
        ("= 6.4058947e+14 cycles", "= 6.406e+14 cycles"),
        (
            "= x<sub>2</sub> + &#189; &#183; 2.000",
            "= x<sub>2</sub> + &#189; &#183; 2",
        ),
        ("= &#x221A; 14.000", "= &#x221A; 14"),
        ("= 99.9999%", "= 100%"),
    ),
)
def test_equation_number_compaction_is_bounded_trimmed_and_honest(
    source, expected
):
    assert sector_report._compact_equation_numbers(source) == expected


def test_equation_substitution_and_result_publish_only_compact_numbers():
    builder = _builder()
    builder._h1("Compact equation values")
    builder._formula(
        "R = a + b + c",
        subst="= 14.000 + 14.500 + 0.0000004",
        result="R = 14.500 kN",
        equation_key="compact.values",
    )

    equation = builder.flow[-1]
    math = next(
        child
        for child in equation._content
        if isinstance(child, publication_equations.EquationFlowable)
    )
    text = equation.getPlainText()
    assert f"Numerical substitution: = 14 + 14.5 + 4 {TIMES} 10-7" in text
    assert f"Result {EM_DASH} R [kN]: R = 14.5 kN" in text
    assert "14.000" not in text
    assert "14.500" not in text

    pdf = _pdf(builder.flow)
    pdf_text = " ".join(
        (pypdf.PdfReader(io.BytesIO(pdf)).pages[0].extract_text() or "").split()
    )
    visible_math = " ".join(
        placement.text
        for placement in math.geometry.texts
        if placement.render_mode == 0
    )
    assert "14.000" not in pdf_text
    assert "14.500" not in pdf_text
    assert "14.5" in pdf_text
    assert "4e-7" in pdf_text or f"4 {TIMES} 10-7" in pdf_text
    assert "14.000" not in visible_math
    assert "14.500" not in visible_math
    assert "14.5" in visible_math


def test_equation_compaction_does_not_change_symbolic_source_note_or_table():
    builder = _builder()
    builder._h1("Compact equation scope")
    builder._table(
        [["Quantity", "Value"], ["Retained table value", "14.000"]],
        [80, 80],
    )
    builder._formula(
        "R = 14.000 a",
        ref="Project method 14.000",
        subst="= 14.000",
        result="R = 14.000 kN",
        note="Retained branch 14.000",
        equation_key="compact.scope",
        equation_spec=_TEST_NUMERIC_RESULT_WITH_NOTE,
    )

    equation = builder.flow[-1]
    text = equation.getPlainText()
    assert "Symbolic expression: R = 14.000 a" in text
    assert "Numerical substitution: = 14" in text
    assert f"Result {EM_DASH} R [kN]: R = 14 kN" in text
    assert "Applicability / method note: Retained branch 14.000" in text
    assert "Source / method note: Project method 14.000" in text

    pdf_text = " ".join(
        (pypdf.PdfReader(io.BytesIO(_pdf(builder.flow))).pages[0]
         .extract_text() or "").split()
    )
    assert "Retained table value 14.000" in pdf_text


def test_equation_flowable_seals_public_identity_number_and_source():
    builder = _builder(profile="Audit")
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
    anchor, math, *_prose = equation._content
    assert isinstance(anchor, sector_report._EquationAnchor)
    assert anchor.wrap(480.0, 700.0) == (0.0, 0.0)
    assert isinstance(math, publication_equations.EquationFlowable)
    assert math.block.identity == (
        "Equation (1.1) | EQ-RESISTANCE.DIRECTION-X.RESULT"
    )
    assert tuple(line.role for line in math.block.lines) == (
        "symbolic-expression",
        "numerical-substitution",
        "result",
    )
    assert equation.getPlainText() == (
        "Equation (1.1) | EQ-RESISTANCE.DIRECTION-X.RESULT "
        "Symbolic expression: R = a + b "
        "Numerical substitution: 4 + 6 "
        f"Result {EM_DASH} R [kN]: R = 10 kN "
        f"Symbols: R {EM_DASH} test result [kN] "
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


@pytest.mark.parametrize(
    ("expression", "substitution", "result", "contract"),
    (
        ("x =", None, None, _TEST_RELATION),
        ("R = 1", "= 83.2%%", "R = 1 kN", _TEST_NUMERIC_RESULT),
        ("R = 1", None, "<b>unsupported</b>", _TEST_DIRECT_RESULT),
    ),
)
def test_renderer_compilation_failures_leave_publication_state_atomic(
    expression, substitution, result, contract,
):
    builder = _builder()
    builder._h1("Atomic renderer failure")
    flow_before = tuple(builder.flow)
    equations_before = dict(builder._equations)
    number_before = builder._equation_number

    with pytest.raises(publication_equations.EquationLayoutError):
        builder._formula(
            expression,
            equation_key="atomic.renderer.failure",
            equation_spec=contract,
            subst=substitution,
            result=result,
        )

    assert tuple(builder.flow) == flow_before
    assert builder._equations == equations_before
    assert builder._equation_number == number_before


def test_literal_result_compiler_is_whitelisted_to_exact_stress_plane_identities():
    expected = frozenset({
        ("elastic.long.stress-plane", None),
        ("elastic.instantaneous.stress-plane", None),
    })
    assert sector_report._LITERAL_REPORT_RESULT_IDENTITIES == expected

    builder = _builder()
    builder._h1("Literal result boundary")
    flow_before = tuple(builder.flow)
    for key, variant in expected:
        contract = sector_report.report_equation_contract.equation_contract(
            key,
            variant,
        )
        with pytest.raises(publication_equations.EquationLayoutError):
            builder._formula(
                "sigma<sub>ref</sub> = sigma<sub>0</sub>",
                equation_key=key,
                equation_variant=variant,
                equation_spec=contract,
                subst="= 1.0 kN/m2",
                result="<b>active markup is forbidden</b>",
            )
        assert tuple(builder.flow) == flow_before
        assert builder._equations == {}
        assert builder._equation_number == 0


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

    reader = pypdf.PdfReader(io.BytesIO(_pdf(builder.flow)))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Uses: Equation (1.1), Equation (1.2)" in text
    assert text.count("SECTOR-MATH[symbolic-expression]") == 3
    annotations = [
        reference.get_object()
        for page in reader.pages
        for reference in page.get("/Annots", ())
    ]
    destinations = [
        annotation.get("/Dest") for annotation in annotations
        if annotation.get("/Subtype") == "/Link"
    ]
    assert len(destinations) == 2
    assert all(destination and destination[1] == "/XYZ" for destination in destinations)


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
    builder = _builder(profile="Audit")
    builder._h1("Combined")
    start = len(builder.flow)
    builder._h2("Directional screen")
    builder._p("Audit context")
    builder._formula(
        "sum(SEd / SRd) &lt;= 1",
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
    assert f"{SUM}(SEd / SRd) {LE} 1" in direct_text
    assert "EQ-COMBINED.DIRECTIONAL.SUM" in direct_text


def test_equation_keep_measurement_adds_only_unapplied_visible_leading_space():
    builder = _builder()
    builder._h1("Pagination measurement")
    builder._formula("x = y", equation_key="pagination.measurement")
    equation = builder.flow[-1]
    equation.canv = Canvas(io.BytesIO(), pagesize=A4)
    frame = SimpleNamespace(
        _atTop=False,
        _oASpace=True,
        _prevASpace=0.0,
    )
    equation._frame = frame
    equation.wrap(470.0, 700.0)
    zero_predecessor_space_height = equation._H

    frame._prevASpace = equation.getSpaceBefore()
    equation.wrap(470.0, 700.0)
    collapsed_predecessor_space_height = equation._H

    assert collapsed_predecessor_space_height == pytest.approx(
        zero_predecessor_space_height + equation.getSpaceBefore()
    )


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
    builder = _builder(profile="Audit")
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
    assert len(calls) == 144

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
        "crack.effective-area.2005": 2,
        "crack.effective-area.2023": 2,
        "crack.effective-reinforcement.ratio": 2,
        "detailing.links.provided-ratio": 2,
        "detailing.links.spacing-limit": 3,
        "fatigue.concrete.life": 2,
        "fatigue.concrete.strength": 2,
        "fatigue.reinforcement.sn-life": 2,
        "torsion.resistance.steel": 2,
        "torsion.resistance.crushing": 2,
        "torsion.resistance.governing": 2,
    }
