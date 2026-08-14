import io
import pathlib
import re
import sys

import pypdf
import pypdfium2
import pytest
from PIL import Image, ImageChops
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import report_equation_contract as contracts
import sector_report

from app import publication_equation_layout as publication_equations

EM_DASH = chr(0x2014)
DELTA = chr(0x0394)
ETA = chr(0x03B7)
GAMMA = chr(0x03B3)
SUM = chr(0x2211)


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


def _role_rows(equation, role):
    return [
        row for row in equation._content
        if getattr(row, "_sector_equation_role", None) == role
    ]


def _math_flowable(equation):
    rows = [
        row for row in equation._content
        if isinstance(row, publication_equations.EquationFlowable)
    ]
    assert len(rows) == 1
    return rows[0]


def _math_line(equation, role):
    rows = [
        line for line in _math_flowable(equation).block.lines
        if line.role == role
    ]
    assert len(rows) == 1
    return rows[0]


def _visible(markup, *, math=True):
    rendered = (
        sector_report._equation_math(markup)
        if math else sector_report._greek(markup)
    )
    return sector_report.Paragraph(
        rendered,
        sector_report._styles()["formula"],
    ).getPlainText()


@pytest.mark.parametrize(
    ("catalogue_identity", "contract"),
    contracts.equation_contract_items(),
)
def test_every_contract_publishes_one_complete_ordered_role_block(
    catalogue_identity, contract
):
    builder = _builder()
    builder._h1("Contract probe")
    kwargs = {}
    if contract.substitution_role == "numerical":
        kwargs["subst"] = "2 x 3"
    if contract.applicability_note_required:
        kwargs["note"] = "This branch is selected by the retained method."
    if contract.expects_result:
        kwargs["result"] = "candidate publication value"

    builder._formula(
        "x = y",
        equation_key="test.synthetic",
        equation_spec=contract,
        **kwargs,
    )
    equation = builder.flow[-1]

    expected_roles = ["identity", "symbolic-expression"]
    if contract.substitution_role == "numerical":
        expected_roles.append("numerical-substitution")
    if contract.expects_result:
        expected_roles.append("result")
    if contract.applicability_note_required:
        expected_roles.append("applicability-note")
    expected_roles.extend(
        ["symbols-heading"] + ["symbol"] * len(contract.symbols) + ["source"]
    )
    assert list(equation._sector_equation_roles) == expected_roles

    symbol_rows = _role_rows(equation, "symbol")
    assert [row._sector_equation_symbol for row in symbol_rows] == list(
        contract.symbols
    )
    for row, symbol in zip(symbol_rows, contract.symbols):
        text = row.getPlainText()
        assert _visible(symbol.markup) in text
        assert _visible(symbol.meaning, math=False) in text
        assert _visible(symbol.unit, math=False) in text

    if contract.expects_result:
        result_line = _math_line(equation, "result")
        assert result_line.label.startswith(
            f"Result {EM_DASH} {_visible(contract.result_symbol)} "
        )
        assert f"[{contract.result_unit}]" in result_line.label
        assert publication_equations.linear_math_text(
            result_line.expression
        ).endswith("candidate publication value")

    assert catalogue_identity in dict(contracts.equation_contract_items())


def test_every_contract_identity_passes_semantic_vector_and_raster_qa():
    builder = _builder()
    builder._h1("Complete equation catalogue")
    equations = []

    for index, ((key, variant), contract) in enumerate(
        contracts.equation_contract_items(), start=1
    ):
        runtime_key = (
            "materials.steel.fyd-1"
            if key == "materials.steel.fyd-N"
            else key
        )
        builder._h2(f"Catalogue equation {index}")
        kwargs = {}
        if contract.substitution_role == "numerical":
            kwargs["subst"] = "2 x 3"
        if contract.applicability_note_required:
            kwargs["note"] = "Selected by the retained calculation branch."
        if contract.expects_result:
            kwargs["result"] = "candidate publication value"
        builder._formula(
            "x = y",
            equation_key=runtime_key,
            equation_variant=variant,
            **kwargs,
        )
        equations.append(builder.flow[-1])

    pdf = _pdf(builder.flow)
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    page_texts = [page.extract_text() or "" for page in reader.pages]

    assert len(equations) == 144
    assert sum(text.count("SECTOR-MATH[") for text in page_texts) == 416
    for equation in equations:
        math = _math_flowable(equation)
        identity_pages = [
            page_number
            for page_number, text in enumerate(page_texts, start=1)
            if math.block.identity in text
        ]
        source_end = (
            "SECTOR-SOURCE-END["
            f"{equation._sector_equation_anchor}]"
        )
        source_pages = [
            page_number
            for page_number, text in enumerate(page_texts, start=1)
            if source_end in text
        ]
        assert identity_pages == source_pages
        assert len(identity_pages) == 1

        geometry = math.geometry
        assert geometry.width > 0.0 and geometry.height > 0.0
        for node in geometry.nodes:
            assert node.bounds.x >= -1e-7
            assert node.bounds.y >= -1e-7
            assert node.bounds.right <= geometry.width + 1e-7
            assert node.bounds.top <= geometry.height + 1e-7
        for rule in geometry.rules:
            assert -1e-7 <= rule.x1 <= geometry.width + 1e-7
            assert -1e-7 <= rule.x2 <= geometry.width + 1e-7
            assert -1e-7 <= rule.y1 <= geometry.height + 1e-7
            assert -1e-7 <= rule.y2 <= geometry.height + 1e-7

    for page in reader.pages:
        resources = page["/Resources"].get_object()
        assert not resources.get("/XObject")

    document = pypdfium2.PdfDocument(pdf)
    try:
        assert len(document) == len(reader.pages)
        for page_number in range(len(document)):
            page = document[page_number]
            try:
                colour = page.render(scale=1.0).to_pil().convert("RGB")
                grayscale = page.render(
                    scale=1.0, grayscale=True
                ).to_pil().convert("L")
            finally:
                page.close()

            colour_ink = ImageChops.difference(
                colour, Image.new("RGB", colour.size, "white")
            ).getbbox()
            gray_ink = ImageChops.difference(
                grayscale, Image.new("L", grayscale.size, "white")
            ).getbbox()
            assert colour_ink is not None and gray_ink is not None
            for bounds, size in (
                (colour_ink, colour.size),
                (gray_ink, grayscale.size),
            ):
                left, top, right, bottom = bounds
                assert left >= 40 and top >= 50
                assert right <= size[0] - 40
                assert bottom <= size[1] - 40
            assert all(
                abs(colour_ink[index] - gray_ink[index]) <= 2
                for index in range(4)
            )
    finally:
        document.close()


def test_numerical_result_has_explicit_roles_canonical_identity_and_symbols():
    builder = _builder()
    builder._h1("Materials")
    builder._formula(
        "f<sub>cd</sub> = eta<sub>cc</sub> k<sub>tc</sub> "
        "f<sub>ck</sub> / gamma<sub>c</sub>",
        equation_key="materials.concrete.fcd",
        equation_variant="2023",
        subst="0.9 x 0.85 x 40 / 1.5",
        result="f<sub>cd</sub> = 20.4 MPa",
    )
    equation = builder.flow[-1]
    text = equation.getPlainText()

    assert equation._sector_equation_roles == (
        "identity",
        "symbolic-expression",
        "numerical-substitution",
        "result",
        "symbols-heading",
        "symbol",
        "symbol",
        "symbol",
        "symbol",
        "symbol",
        "source",
    )
    assert f"Symbolic expression: fcd = {ETA}cc ktc fck / {GAMMA}c" in text
    assert "Numerical substitution: 0.9 x 0.85 x 40 / 1.5" in text
    assert f"Result {EM_DASH} fcd [MPa]: fcd = 20.4 MPa" in text
    assert (
        f"Symbols: fcd {EM_DASH} design concrete compressive strength [MPa]"
        in text
    )
    assert (
        f"ktc {EM_DASH} time and sustained-loading factor [dimensionless]"
        in text
    )


def test_applicability_note_is_distinct_from_the_numerical_substitution():
    builder = _builder()
    builder._h1("Combined")
    builder._formula(
        "max(r<sub>M</sub> + r<sub>T</sub>, r<sub>V</sub> + r<sub>T</sub>)",
        equation_key="combined.dk-na.sum",
        subst="max(0.50 + 0.20, 0.40 + 0.20)",
        note="M and V are checked separately.",
        result="&#8721;(S<sub>Ed</sub>/S<sub>Rd</sub>) = 70.0% (PASS)",
    )
    equation = builder.flow[-1]
    text = equation.getPlainText()

    assert "Applicability / method note: M and V are checked separately." in text
    assert "Numerical substitution: max(0.5 + 0.2, 0.4 + 0.2)" in text
    assert (
        f"Result {EM_DASH} {SUM}(SEd/SRd) "
        f"[dimensionless; displayed as %]: {SUM}(SEd/SRd) = 70% (PASS)"
    ) in text
    roles = equation._sector_equation_roles
    assert roles.index("numerical-substitution") < roles.index("result")
    assert roles.index("result") < roles.index("applicability-note")


def test_relation_only_block_has_no_intermediate_or_result_row():
    builder = _builder()
    builder._h1("Basis")
    builder._formula(
        "F<sub>c</sub> + F<sub>s</sub> + F<sub>p</sub> - N = 0",
        equation_key="basis.plastic.equilibrium",
    )
    equation = builder.flow[-1]
    assert "numerical-substitution" not in equation._sector_equation_roles
    assert "applicability-note" not in equation._sector_equation_roles
    assert "result" not in equation._sector_equation_roles
    assert len(_role_rows(equation, "symbol")) == 7


@pytest.mark.parametrize(
    "key",
    ("combined.crushing.interaction", "torsion.shear.crushing-interaction"),
)
def test_concrete_strut_interactions_are_not_misnamed_as_utilisations(key):
    contract = contracts.equation_contract(key)
    interaction = next(
        symbol for symbol in contract.symbols if symbol.markup == "interaction"
    )
    assert interaction.meaning == "combined concrete-strut interaction value"


def test_equation_only_math_tokens_do_not_rewrite_symbol_meanings():
    contract = contracts.EquationContract(
        symbols=(
            contracts.EquationSymbol("Delta R", "sum of retained terms", "kN"),
            contracts.EquationSymbol("sum x", "governing sum", "kN"),
        ),
        result_symbol="Delta R",
        result_unit="kN",
        substitution_role="numerical",
    )
    builder = _builder()
    builder._h1("Math tokens")
    builder._formula(
        "Delta R = sum(x)",
        subst="Delta R = 1 + 2",
        result="Delta R = 3 kN",
        equation_key="test.math-tokens",
        equation_spec=contract,
    )
    text = builder.flow[-1].getPlainText()

    assert f"Symbolic expression: {DELTA} R = {SUM}(x)" in text
    assert f"Result {EM_DASH} {DELTA} R [kN]: {DELTA} R = 3 kN" in text
    assert f"{DELTA} R {EM_DASH} sum of retained terms [kN]" in text
    assert f"{SUM} x {EM_DASH} governing sum [kN]" in text


def test_long_unbroken_expression_and_maximum_symbol_inventory_fit_a4():
    symbols = tuple(
        contracts.EquationSymbol(
            f"q<sub>{index}</sub>",
            f"retained long-expression quantity {index}",
            "kN",
        )
        for index in range(1, 9)
    )
    contract = contracts.EquationContract(symbols=symbols)
    terms = " + ".join("abcdefghij" for _index in range(24))
    builder = _builder()
    builder._h1("Long expression")
    builder._formula(
        "q<sub>1</sub> = " + terms,
        equation_key="test.long-expression",
        equation_spec=contract,
    )
    equation = builder.flow[-1]

    assert isinstance(
        _math_flowable(equation), publication_equations.EquationFlowable
    )
    assert all(
        row.style.wordWrap == "LTR" and row.style.splitLongWords
        for row in equation._content
        if getattr(row, "_sector_equation_role", None) == "symbol"
    )
    pdf = _pdf(builder.flow)
    pages = pypdf.PdfReader(io.BytesIO(pdf)).pages
    assert len(pages) == 1
    compact = re.sub(r"\s+", "", pages[0].extract_text() or "")
    assert "SECTOR-MATH[symbolic-expression]" in compact
    assert compact.count("abcdefghij") >= 24
    assert "retainedlong-expressionquantity8[kN]" in compact
