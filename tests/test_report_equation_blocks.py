import io
import pathlib
import re
import sys

import pypdf
import pytest
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import report_equation_contract as contracts  # noqa: E402
import sector_report  # noqa: E402


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
        if row._sector_equation_role == role
    ]


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
    if contract.applicability_note_required:
        expected_roles.append("applicability-note")
    if contract.expects_result:
        expected_roles.append("result")
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
        result_text = _role_rows(equation, "result")[0].getPlainText()
        assert result_text.startswith(
            f"Result {EM_DASH} {_visible(contract.result_symbol)} "
        )
        assert f"[{contract.result_unit}]" in result_text
        assert result_text.endswith("candidate publication value")

    assert catalogue_identity in dict(contracts.equation_contract_items())


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


def test_applicability_note_is_not_mislabelled_as_a_numerical_substitution():
    builder = _builder()
    builder._h1("Combined")
    builder._formula(
        "max(r<sub>M</sub> + r<sub>T</sub>, r<sub>V</sub> + r<sub>T</sub>)",
        equation_key="combined.dk-na.sum",
        note="M and V are checked separately.",
        result="&#8721;(S<sub>Ed</sub>/S<sub>Rd</sub>) = 70.0% (PASS)",
    )
    equation = builder.flow[-1]
    text = equation.getPlainText()

    assert "Applicability / method note: M and V are checked separately." in text
    assert "Numerical substitution:" not in text
    assert (
        f"Result {EM_DASH} {SUM}(SEd/SRd) "
        f"[dimensionless; displayed as %]: {SUM}(SEd/SRd) = 70.0% (PASS)"
    ) in text


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
    token = "abcdefghij" * 24
    builder = _builder()
    builder._h1("Long expression")
    builder._formula(
        "q<sub>1</sub> = " + token,
        equation_key="test.long-expression",
        equation_spec=contract,
    )
    equation = builder.flow[-1]

    assert all(
        row.style.wordWrap == "LTR" and row.style.splitLongWords
        for row in equation._content
        if row._sector_equation_role in {"symbolic-expression", "symbol"}
    )
    pdf = _pdf(builder.flow)
    pages = pypdf.PdfReader(io.BytesIO(pdf)).pages
    assert len(pages) == 1
    compact = re.sub(r"\s+", "", pages[0].extract_text() or "")
    assert token in compact
    assert "retainedlong-expressionquantity8[kN]" in compact
