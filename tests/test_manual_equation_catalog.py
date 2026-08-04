import collections
import hashlib
import io
import pathlib
import sys

import pypdf
import pytest
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import manual  # noqa: E402
import manual_equation_catalog as catalogue  # noqa: E402
import sector_report  # noqa: E402


EXPECTED_KEYS = (
    "materials.concrete.curve-2",
    "materials.steel.initial-branch",
    "materials.prestress.total-strain",
    "plastic.governing-curvature",
    "detailing.minimum.2005",
    "detailing.minimum.2023-bending",
    "detailing.minimum.2023-tension",
    "detailing.clear-spacing",
    "detailing.links.minimum-ratio",
    "detailing.links.spacing",
    "detailing.torsion.minimum-ratio",
    "crack.2005.width-strain",
    "crack.2005.spacing",
    "crack.2023.width",
    "crack.2023.spacing",
    "fatigue.elastic.stress-range",
    "fatigue.reinforcement.design-range",
    "fatigue.reinforcement.life",
    "fatigue.reinforcement.miner",
    "fatigue.concrete.strength-2005",
    "fatigue.concrete.strength-2023",
    "fatigue.concrete.life",
    "fatigue.concrete.equivalent",
    "shear.2005.basic",
    "shear.2005.minimum",
    "shear.2023.action-factor",
    "shear.links.2005",
    "shear.links.2023",
    "torsion.resistance",
    "torsion.shear-interaction",
    "combined.strut-interaction",
    "combined.dk-na-sum",
)

EXPECTED_NUMBERS = (
    "C.3.1-1", "C.3.2-1", "C.3.3-1", "C.4.2-1", "C.5.1-1",
    "C.5.2-1", "C.5.2-2", "C.5.3-1", "C.5.4-1", "C.5.4-2",
    "C.5.4-3", "C.7.2-1", "C.7.2-2", "C.7.5-1", "C.7.5-2",
    "C.8.1-1", "C.8.2-1", "C.8.2-2", "C.8.2-3", "C.8.4-1",
    "C.8.4-2", "C.8.4-3", "C.8.4-4", "C.9-1", "C.9-2", "C.9-3",
    "C.9.1-1", "C.9.1-2", "C.10-1", "C.10-2", "C.11-1", "C.11-2",
)

EXPECTED_USES = {
    "fatigue.reinforcement.life": ("fatigue.reinforcement.design-range",),
    "fatigue.reinforcement.miner": ("fatigue.reinforcement.life",),
    "torsion.shear-interaction": ("torsion.resistance",),
    "combined.strut-interaction": ("torsion.shear-interaction",),
}

EXPECTED_SOURCE_INVENTORY_SHA256 = (
    "f406d20f7016a572476ca14bc098ea0fcbe95a56b4e94aaed7b36c3fc3358dde"
)
EXPECTED_SYMBOL_INVENTORY_SHA256 = (
    "b39a1a9ea4965b7b35b8c9c3c5c8b603438ed657fcbfac7540432a696ad04f63"
)


def _catalogued_occurrences():
    return [
        segment.equation
        for block in manual.manual_publication_blocks()
        if block[0] == "md"
        for segment in block[2]
        if segment.equation is not None
    ]


def _mutated_blocks(kind):
    blocks = list(manual.manual_blocks())
    equation_indices = [
        index for index, block in enumerate(blocks)
        if block[0] == "md" and "$$" in block[1]
    ]
    first = equation_indices[0]
    first_text = blocks[first][1]
    first_match = catalogue._DISPLAY_EQUATION_RE.search(first_text)
    assert first_match is not None

    if kind == "altered":
        changed = first_text.replace(r"\sigma_c", r"\sigma_x", 1)
        blocks[first] = ("md", changed)
    elif kind == "missing":
        changed = first_text[:first_match.start()] + first_text[first_match.end():]
        blocks[first] = ("md", changed)
    elif kind == "duplicate":
        changed = (
            first_text[:first_match.end()] + "\n\n" + first_match.group(0)
            + first_text[first_match.end():]
        )
        blocks[first] = ("md", changed)
    elif kind == "unknown":
        blocks[first] = ("md", "$$x=y$$\n\n" + first_text)
    elif kind == "moved":
        heading = max(
            index for index in range(first)
            if blocks[index][0] == "h2"
        )
        blocks[heading] = ("h2", "Moved concrete equation")
    elif kind == "reordered":
        target = next(
            index for index in equation_indices
            if blocks[index][1].count("$$") >= 4
            and "Delta" in blocks[index][1]
        )
        text = blocks[target][1]
        matches = list(catalogue._DISPLAY_EQUATION_RE.finditer(text))
        assert len(matches) == 2
        first_eq, second_eq = (match.group(0) for match in matches)
        changed = (
            text[:matches[0].start()] + second_eq
            + text[matches[0].end():matches[1].start()] + first_eq
            + text[matches[1].end():]
        )
        blocks[target] = ("md", changed)
    else:
        raise AssertionError(kind)
    return blocks


def _styles():
    return manual._manual_pdf_styles(
        sector_report,
        colors,
        ParagraphStyle,
        getSampleStyleSheet,
        TA_CENTER,
    )


class _FakeStreamlit:
    def __init__(self):
        self.markdowns = []
        self.captions = []

    def markdown(self, text, **kwargs):
        self.markdowns.append((text, kwargs))

    def caption(self, text):
        self.captions.append(text)


def test_catalogue_freezes_all_public_keys_numbers_symbols_and_provenance():
    contracts = catalogue.manual_equation_contracts()
    assert tuple(contract.key for contract in contracts) == EXPECTED_KEYS
    assert tuple(contract.number for contract in contracts) == EXPECTED_NUMBERS
    assert sum(len(contract.symbols) for contract in contracts) == 208
    assert collections.Counter(contract.source_kind for contract in contracts) == {
        "standard": 24,
        "mixed": 6,
        "project": 2,
    }
    assert {
        contract.key: contract.uses
        for contract in contracts if contract.uses
    } == EXPECTED_USES
    assert all(
        contract.public_id == "MEQ-" + contract.key.upper()
        for contract in contracts
    )
    assert all(
        contract.anchor.startswith("manual-equation-")
        and "." not in contract.anchor
        for contract in contracts
    )
    source_inventory = "\n".join(
        "\0".join((contract.key, contract.source_kind, contract.source))
        for contract in contracts
    )
    symbol_inventory = "\n".join(
        "\0".join((contract.key, symbol.latex, symbol.meaning, symbol.unit))
        for contract in contracts
        for symbol in contract.symbols
    )
    assert hashlib.sha256(source_inventory.encode()).hexdigest() == (
        EXPECTED_SOURCE_INVENTORY_SHA256
    )
    assert hashlib.sha256(symbol_inventory.encode()).hexdigest() == (
        EXPECTED_SYMBOL_INVENTORY_SHA256
    )


def test_catalogued_blocks_reconstruct_every_authored_markdown_byte_for_byte():
    raw = manual.manual_blocks()
    published = catalogue.catalogue_manual_blocks(raw)
    assert len(published) == len(raw)
    for raw_block, published_block in zip(raw, published):
        assert published_block[:2] == raw_block[:2]
        if raw_block[0] == "md":
            assert "".join(
                segment.markdown for segment in published_block[2]
            ) == raw_block[1]
    occurrences = _catalogued_occurrences()
    assert len(occurrences) == 32
    assert tuple(item.contract.key for item in occurrences) == EXPECTED_KEYS
    assert all(
        catalogue._expression_sha256(item.expression)
        == item.contract.expression_sha256
        for item in occurrences
    )


@pytest.mark.parametrize(
    "mutation",
    ("altered", "missing", "duplicate", "unknown", "moved", "reordered"),
)
def test_unknown_missing_moved_reordered_or_changed_equations_fail(mutation):
    with pytest.raises(ValueError, match="manual|Manual"):
        catalogue.catalogue_manual_blocks(_mutated_blocks(mutation))


@pytest.mark.parametrize("contract", catalogue.manual_equation_contracts())
def test_every_symbol_and_source_field_is_complete_and_immutable(contract):
    assert contract.symbols
    assert len({symbol.latex for symbol in contract.symbols}) == len(contract.symbols)
    for symbol in contract.symbols:
        assert symbol.latex.strip()
        assert symbol.meaning.strip()
        assert catalogue.unit_latex(symbol.unit)
    if contract.source_kind == "project":
        assert contract.source == "Project-defined / uncited."
    elif contract.source_kind == "mixed":
        assert "Project-defined / uncited" in contract.source
    else:
        assert "DS/EN" in contract.source or "EN 1992" in contract.source


def test_unknown_public_lookups_and_units_fail_closed():
    with pytest.raises(ValueError, match="Unknown manual equation key"):
        catalogue.manual_equation_contract("missing.key")
    with pytest.raises(ValueError, match="Unknown manual equation unit"):
        catalogue.unit_latex("widgets")


def test_internal_curvature_equations_use_retained_solver_units():
    prestress = catalogue.manual_equation_contract(
        "materials.prestress.total-strain"
    )
    curvature = catalogue.manual_equation_contract(
        "plastic.governing-curvature"
    )
    prestress_units = {symbol.latex: symbol.unit for symbol in prestress.symbols}
    curvature_units = {symbol.latex: symbol.unit for symbol in curvature.symbols}
    assert prestress_units[r"\kappa"] == "1/m"
    assert prestress_units[r"s_{p,j}"] == "m"
    assert prestress_units[r"s_{na}"] == "m"
    assert curvature_units[r"\kappa"] == "1/m"
    assert curvature_units["c"] == "m"
    assert curvature_units[r"s_{na}"] == "m"
    assert curvature_units[r"s_{b,i}"] == "m"
    assert curvature_units[r"s_{p,j}"] == "m"


def test_every_catalogued_unit_uses_supported_pdf_markup():
    units = {
        symbol.unit
        for contract in catalogue.manual_equation_contracts()
        for symbol in contract.symbols
    }
    rendered = {
        unit: manual._latex_to_rl(catalogue.unit_latex(unit))
        for unit in units
    }
    assert all(
        "^" not in markup and "\\" not in markup
        for markup in rendered.values()
    )
    assert rendered["degrees"] == "<super>&#176;</super>"


def test_streamlit_renders_exact_formula_ids_symbols_sources_and_links():
    fake = _FakeStreamlit()
    for block in manual.manual_publication_blocks():
        if block[0] == "md":
            manual._render_catalogued_md_streamlit(block[2], fake)

    identities = [
        text for text, kwargs in fake.markdowns
        if kwargs.get("unsafe_allow_html") and "MEQ-" in text
    ]
    equations = [
        text for text, kwargs in fake.markdowns
        if not kwargs and text.startswith("$$")
    ]
    expected_equations = [
        segment.markdown
        for block in manual.manual_publication_blocks()
        if block[0] == "md"
        for segment in block[2]
        if segment.equation is not None
    ]
    symbol_blocks = [
        text for text, kwargs in fake.markdowns
        if not kwargs and text.startswith("**Symbols:**")
    ]
    uses = [
        text for text, kwargs in fake.markdowns
        if not kwargs and text.startswith("**Uses:**")
    ]
    assert len(identities) == len(equations) == len(symbol_blocks) == 32
    assert equations == expected_equations
    assert len(fake.captions) == 32
    assert len(uses) == 4

    for occurrence, identity, symbols, source in zip(
        _catalogued_occurrences(), identities, symbol_blocks, fake.captions,
    ):
        contract = occurrence.contract
        assert contract.public_id in identity
        assert contract.anchor in identity
        assert symbols.count("\n- $") == len(contract.symbols)
        assert source == (
            f"Source / method note ({contract.source_kind}): {contract.source}"
        )
    assert all("#manual-equation-" in text for text in uses)


def test_pdf_equation_flowables_retain_complete_roles_and_cross_references():
    flow = []
    styles = _styles()
    occurrences = _catalogued_occurrences()
    for occurrence in occurrences:
        manual._render_manual_equation_pdf(
            occurrence, flow, styles, Paragraph, KeepTogether
        )

    assert len(flow) == 32
    for equation, occurrence in zip(flow, occurrences):
        contract = occurrence.contract
        expected = ["identity", "expression", "symbols-heading"]
        expected.extend(["symbol"] * len(contract.symbols))
        if contract.uses:
            expected.append("uses")
        expected.append("source")
        assert list(equation._manual_equation_roles) == expected
        assert equation._manual_equation_key == contract.key
        assert equation._manual_equation_number == contract.number
        symbol_rows = [
            row for row in equation._content
            if row._manual_equation_role == "symbol"
        ]
        assert [row._manual_equation_symbol for row in symbol_rows] == list(
            contract.symbols
        )

    uses_rows = [
        row for equation in flow for row in equation._content
        if row._manual_equation_role == "uses"
    ]
    assert len(uses_rows) == 4
    assert all('href="#manual-equation-' in row.text for row in uses_rows)


def test_all_catalogued_equations_render_and_extract_on_a4():
    flow = []
    styles = _styles()
    for occurrence in _catalogued_occurrences():
        manual._render_manual_equation_pdf(
            occurrence, flow, styles, Paragraph, KeepTogether
        )
    buffer = io.BytesIO()
    SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=25 * mm,
        bottomMargin=20 * mm,
    ).build(flow)
    text = "\n".join(
        page.extract_text() or ""
        for page in pypdf.PdfReader(io.BytesIO(buffer.getvalue())).pages
    )
    for contract in catalogue.manual_equation_contracts():
        assert contract.public_id in text
        assert f"Equation ({contract.number})" in text
    assert text.count("Source / method note") == 32


def test_manual_equation_styles_pin_long_expression_and_symbol_wrapping():
    styles = _styles()
    assert styles["MMath"].wordWrap == "LTR"
    assert styles["MMath"].splitLongWords is True
    assert styles["MEqSymbol"].wordWrap == "LTR"
    assert styles["MEqSymbol"].splitLongWords is True
    assert styles["MEqId"].keepWithNext == 1
