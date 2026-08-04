import collections
import hashlib
import io
import pathlib
import re
import sys

import pypdf
import pytest
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Table, TableStyle

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import manual  # noqa: E402
import manual_equation_registry as registry  # noqa: E402
import sector_report  # noqa: E402


EXPECTED_KEYS = (
    "material.concrete.curve2",
    "material.reinforcement.initial",
    "material.prestress.compatibility",
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

EXPECTED_SEALS = {
    "sources": "54547bbef20900b8bc1ffa0ff1b2668dacfc1309525af566cd64ff0867bb2b90",
    "symbols": "42b0ef667dbae2968587d550287b8c8d903cb77882d2c4c3f5665e148cbd32e1",
    "dimensions": "ecba4836419ee26c02c7c4f3f0422b250e4bc09c89efc1cd00015eab895ba105",
}


def _occurrences():
    return [
        segment.equation
        for block in manual.manual_publication_blocks()
        if block[0] == "md"
        for segment in block[2]
        if segment.equation is not None
    ]


def _styles():
    return manual._manual_pdf_styles(
        sector_report, colors, ParagraphStyle, getSampleStyleSheet, TA_CENTER
    )


def _mutated_blocks(mutation):
    blocks = list(manual.manual_blocks())
    equation_blocks = [
        index for index, block in enumerate(blocks)
        if block[0] == "md" and "$$" in block[1]
    ]
    first = equation_blocks[0]
    first_text = blocks[first][1]
    first_match = registry._DISPLAY_RE.search(first_text)
    assert first_match is not None
    if mutation == "altered":
        blocks[first] = ("md", first_text.replace(r"\sigma_c", r"\sigma_x", 1))
    elif mutation == "missing":
        blocks[first] = (
            "md", first_text[:first_match.start()] + first_text[first_match.end():]
        )
    elif mutation == "duplicate":
        blocks[first] = (
            "md", first_text[:first_match.end()] + first_match.group(0)
            + first_text[first_match.end():],
        )
    elif mutation == "unknown":
        blocks[first] = ("md", "$$x=y$$\n" + first_text)
    elif mutation == "moved":
        heading = max(index for index in range(first) if blocks[index][0] == "h2")
        blocks[heading] = ("h2", "Different subsection")
    elif mutation == "reordered":
        target = next(
            index for index in equation_blocks
            if blocks[index][1].count("$$") >= 4 and "Delta" in blocks[index][1]
        )
        text = blocks[target][1]
        matches = list(registry._DISPLAY_RE.finditer(text))
        assert len(matches) == 2
        blocks[target] = (
            "md", text[:matches[0].start()] + matches[1].group(0)
            + text[matches[0].end():matches[1].start()] + matches[0].group(0)
            + text[matches[1].end():],
        )
    else:
        raise AssertionError(mutation)
    return blocks


class _FakeStreamlit:
    def __init__(self):
        self.markdowns = []
        self.captions = []

    def markdown(self, text, **kwargs):
        self.markdowns.append((text, kwargs))

    def caption(self, text):
        self.captions.append(text)


def test_registry_freezes_complete_identity_sources_symbols_and_dimensions():
    specs = registry.manual_equation_specs()
    assert tuple(spec.key for spec in specs) == EXPECTED_KEYS
    assert tuple(spec.number for spec in specs) == EXPECTED_NUMBERS
    assert sum(len(spec.symbols) for spec in specs) == 205
    assert collections.Counter(spec.source_kind for spec in specs) == {
        "standard": 24,
        "mixed": 6,
        "project": 2,
    }
    inventories = {
        "sources": "\n".join(
            f"{spec.key}|{spec.source_kind}|{spec.source}" for spec in specs
        ),
        "symbols": "\n".join(
            f"{spec.key}|{symbol.latex}|{symbol.meaning}|{symbol.unit}"
            for spec in specs for symbol in spec.symbols
        ),
        "dimensions": "\n".join(
            f"{spec.key}|{spec.dimensional_note}" for spec in specs
        ),
    }
    assert {
        key: hashlib.sha256(value.encode()).hexdigest()
        for key, value in inventories.items()
    } == EXPECTED_SEALS


def test_registration_reconstructs_every_authored_markdown_exactly():
    raw = manual.manual_blocks()
    published = registry.register_manual_blocks(raw)
    assert len(published) == len(raw)
    for source, result in zip(raw, published):
        assert result[:2] == source[:2]
        if source[0] == "md":
            assert "".join(segment.markdown for segment in result[2]) == source[1]
    occurrences = _occurrences()
    assert len(occurrences) == 32
    assert tuple(item.spec.key for item in occurrences) == EXPECTED_KEYS
    assert all(
        registry.expression_sha256(item.expression) == item.spec.expression_sha256
        for item in occurrences
    )


def test_every_formula_identifier_reaches_its_local_symbol_inventory():
    layout_and_operator_words = {
        "left", "right", "Big", "big", "Bigg", "bigg", "tfrac", "frac",
        "min", "max", "text", "quad", "qquad", "le", "ge", "leq", "geq",
        "sum", "log", "sqrt", "sin", "cos", "tan", "cot",
    }

    def atoms(value):
        value = re.sub(r"\\text\{[^{}]*\}", "", value)
        return {
            token for token in re.findall(r"[A-Za-z]+", value)
            if token not in layout_and_operator_words
        }

    for occurrence in _occurrences():
        advertised = set().union(
            *(atoms(symbol.latex) for symbol in occurrence.spec.symbols)
        )
        assert atoms(occurrence.expression) <= advertised, occurrence.spec.key


@pytest.mark.parametrize(
    "mutation", ("altered", "missing", "duplicate", "unknown", "moved", "reordered")
)
def test_unknown_missing_duplicate_moved_reordered_or_altered_equations_fail(mutation):
    with pytest.raises(ValueError, match="manual|Manual"):
        registry.register_manual_blocks(_mutated_blocks(mutation))


@pytest.mark.parametrize("spec", registry.manual_equation_specs())
def test_every_equation_has_complete_local_symbols_source_and_dimension(spec):
    assert spec.symbols
    assert len({symbol.latex for symbol in spec.symbols}) == len(spec.symbols)
    assert spec.dimensional_note.strip()
    assert all(symbol.meaning.strip() for symbol in spec.symbols)
    assert all(registry.unit_markup(symbol.unit) for symbol in spec.symbols)
    if spec.source_kind == "project":
        assert spec.source == "Project-defined / uncited."
    elif spec.source_kind == "mixed":
        assert "Project-defined / uncited" in spec.source
    else:
        assert "EN 1992" in spec.source


def test_conversion_sensitive_equations_pin_solver_compatible_units():
    prestress = registry.manual_equation_spec("material.prestress.compatibility")
    curvature = registry.manual_equation_spec("plastic.governing-curvature")
    action = registry.manual_equation_spec("shear.2023.action-factor")
    torsion = registry.manual_equation_spec("torsion.resistance")
    units = lambda spec: {symbol.latex: symbol.unit for symbol in spec.symbols}
    assert units(prestress)[r"\kappa"] == units(curvature)[r"\kappa"] == "1/m"
    assert units(prestress)[r"s_{p,j}"] == units(curvature)[r"s_{p,j}"] == "m"
    assert units(action)[r"a_{cs}"] == units(action)["d"] == "m"
    assert units(action)[r"M_{Ed}"] == "kNm"
    assert units(action)[r"V_{Ed}"] == "kN"
    assert units(torsion)[r"A_k"] == "m2"
    assert units(torsion)[r"t_{ef}"] == "m"


def test_dimensional_constants_and_interaction_pairs_are_explicit():
    old_strength = registry.manual_equation_spec("fatigue.concrete.strength-2005")
    new_strength = registry.manual_equation_spec("fatigue.concrete.strength-2023")
    assert {s.latex: s.unit for s in old_strength.symbols}["250"] == "MPa"
    assert {s.latex: s.unit for s in new_strength.symbols}["40"] == "MPa"
    for key in ("torsion.shear-interaction", "combined.strut-interaction"):
        unit = {s.latex: s.unit for s in registry.manual_equation_spec(key).symbols}
        assert unit[r"T_{Ed}"] == unit[r"T_{Rd,max}"] == "kNm"
        assert unit[r"V_{Ed}"] == unit[r"V_{Rd,max}"] == "kN"
    generic = registry.manual_equation_spec("combined.dk-na-sum")
    assert {symbol.unit for symbol in generic.symbols} == {"actions"}


def test_every_retained_unit_converts_without_literal_latex():
    units = {
        symbol.unit
        for spec in registry.manual_equation_specs()
        for symbol in spec.symbols
    }
    converted = {
        unit: manual._latex_to_rl(registry.unit_markup(unit)) for unit in units
    }
    assert all(
        "^" not in markup and "\\" not in markup
        for markup in converted.values()
    )
    assert converted["degrees"] == "<super>&#176;</super>"


def test_dependency_graph_is_exact_and_resolvable():
    dependencies = {
        spec.key: spec.uses for spec in registry.manual_equation_specs() if spec.uses
    }
    assert dependencies == {
        "detailing.torsion.minimum-ratio": ("detailing.links.minimum-ratio",),
        "crack.2005.width-strain": ("crack.2005.spacing",),
        "crack.2023.width": ("crack.2023.spacing",),
        "fatigue.reinforcement.life": ("fatigue.reinforcement.design-range",),
        "fatigue.reinforcement.miner": ("fatigue.reinforcement.life",),
        "shear.links.2023": ("detailing.links.minimum-ratio",),
        "torsion.shear-interaction": ("torsion.resistance", "shear.links.2005"),
        "combined.strut-interaction": ("torsion.shear-interaction",),
    }
    for values in dependencies.values():
        assert all(registry.manual_equation_spec(value) for value in values)


def test_streamlit_publishes_exact_formula_symbols_dimensions_sources_and_links():
    fake = _FakeStreamlit()
    for block in manual.manual_publication_blocks():
        if block[0] == "md":
            manual._render_registered_md_streamlit(block[2], fake)
    identities = [
        text for text, kwargs in fake.markdowns
        if kwargs.get("unsafe_allow_html") and "MEQ-" in text
    ]
    formulas = [
        text for text, kwargs in fake.markdowns
        if not kwargs and text.startswith("$$")
    ]
    tables = [
        text for text, kwargs in fake.markdowns
        if not kwargs and text.startswith("| Symbol | Meaning | Unit |")
    ]
    uses = [
        text for text, kwargs in fake.markdowns
        if not kwargs and text.startswith("**Uses:**")
    ]
    assert len(identities) == len(formulas) == len(tables) == 32
    assert len(uses) == 8
    assert sum(table.count("\n| $") for table in tables) == 205
    assert len([text for text in fake.captions if text.startswith("Dimensional")]) == 32
    assert len([text for text in fake.captions if text.startswith("Source")]) == 32


def test_pdf_records_retain_identity_symbols_and_dependency_links():
    flow = []
    for occurrence in _occurrences():
        manual._manual_equation_pdf(
            occurrence, flow, _styles(), Paragraph, KeepTogether,
            Table, TableStyle, colors, mm,
        )
    assert len(flow) == 32
    for record, occurrence in zip(flow, _occurrences()):
        assert record._manual_equation_key == occurrence.spec.key
        assert record._manual_equation_number == occurrence.spec.number
        assert record._manual_equation_symbols == occurrence.spec.symbols
    links = [
        item.text
        for record in flow for item in record._content
        if isinstance(item, Paragraph) and item.text.startswith("<b>Uses:")
    ]
    assert len(links) == 8
    assert all('href="#manual-equation-' in text for text in links)


def test_all_manual_equation_records_render_and_extract_on_a4():
    flow = []
    styles = _styles()
    for occurrence in _occurrences():
        manual._manual_equation_pdf(
            occurrence, flow, styles, Paragraph, KeepTogether,
            Table, TableStyle, colors, mm,
        )
    buffer = io.BytesIO()
    SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=25 * mm, bottomMargin=20 * mm,
    ).build(flow)
    text = "\n".join(
        page.extract_text() or ""
        for page in pypdf.PdfReader(io.BytesIO(buffer.getvalue())).pages
    )
    assert text.count("Dimensional closure") == 32
    assert text.count("Source / method") == 32
    for spec in registry.manual_equation_specs():
        assert spec.public_id in text
        assert f"Equation ({spec.number})" in text


def test_manual_equation_styles_pin_safe_wrapping():
    styles = _styles()
    assert styles["MMath"].wordWrap == "LTR"
    assert styles["MMath"].splitLongWords is True
    assert styles["MEqSymbol"].wordWrap == "LTR"
    assert styles["MEqSymbol"].splitLongWords is True
    assert styles["MEqIdentity"].keepWithNext == 1


def test_unknown_registry_lookups_fail_closed():
    with pytest.raises(ValueError, match="Unknown manual equation key"):
        registry.manual_equation_spec("missing")
    with pytest.raises(ValueError, match="Unknown manual equation unit"):
        registry.unit_markup("widgets")
