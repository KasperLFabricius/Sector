"""Independent F-041 contract for published figure and table identities."""

from __future__ import annotations

import base64
import io
import pathlib
import re
import sys

import plotly.graph_objects as go
import pypdf
import pytest
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, Table

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import manual
from manual_equation_publication import manual_publication_blocks
from publication_items import (
    MANUAL_FIGURE_SPECS,
    MANUAL_TABLE_SPECS,
    PublicationContractError,
    publish_manual_blocks,
)
import sector_report


EXPECTED_LABELS = (
    "Figure A2-1",
    "Figure A3-1", "Figure A3-2", "Table A3-1",
    "Table B1-1", "Table B3-1", "Table B3-2",
    "Figure B4-1", "Figure B4-2", "Figure B4-3",
    "Figure B5-1", "Table B5-1", "Table B5-2", "Table B5-3",
    "Table B5-4", "Table B5-5", "Table B5-6", "Table B5-7",
    "Table B6-1", "Figure C1-1",
    "Figure C2-1", "Figure C2-2", "Figure C2-3",
    "Figure C3-1", "Figure C3-2", "Figure C5-1", "Table C6-1",
    "Figure C7-1", "Figure C7-2", "Table C7-1",
    "Table D1-1", "Table D3-1",
)


def _blocks():
    return list(manual_publication_blocks(manual.manual_blocks()))


def _entries(blocks=None):
    return publish_manual_blocks(_blocks() if blocks is None else blocks)


def _cell_text(cell):
    if hasattr(cell, "getPlainText"):
        return cell.getPlainText()
    if isinstance(cell, (list, tuple)):
        return "".join(_cell_text(value) for value in cell)
    return str(cell)


def _flow_text(flowable):
    if isinstance(flowable, Paragraph):
        return flowable.getPlainText()
    if isinstance(flowable, Table):
        return " ".join(
            _cell_text(cell)
            for row in flowable._cellvalues
            for cell in row
        )
    if isinstance(flowable, KeepTogether):
        return " ".join(_flow_text(child) for child in flowable._content)
    return ""


def _tables(builder):
    found = []
    for flowable in builder.flow:
        if isinstance(flowable, Table):
            found.append(flowable)
        elif isinstance(flowable, KeepTogether):
            found.extend(
                child for child in flowable._content
                if isinstance(child, Table)
            )
    return found


def test_manual_inventory_has_exact_objects_labels_and_destinations():
    items = [entry.item for entry in _entries() if entry.item is not None]

    assert tuple(item.label for item in items) == EXPECTED_LABELS
    assert len(MANUAL_FIGURE_SPECS) == 16
    assert len(MANUAL_TABLE_SPECS) == 16
    assert len({item.label for item in items}) == len(items)
    assert len({item.anchor for item in items}) == len(items)
    assert all(item.caption.strip() for item in items)


@pytest.mark.parametrize("kind", ["figure", "table"])
def test_same_cardinality_manual_reorder_fails_before_caption_publication(kind):
    blocks = _blocks()
    positions = [index for index, block in enumerate(blocks) if block[0] == kind]
    # Swap two objects inside one unchanged part/section. Cardinality, section
    # numbering and surrounding structure therefore remain valid; only the
    # object-to-caption identity is hostile.
    left, right = ((1, 2) if kind == "figure" else (4, 5))
    blocks[positions[left]], blocks[positions[right]] = (
        blocks[positions[right]], blocks[positions[left]]
    )

    with pytest.raises(PublicationContractError, match="identity or order"):
        _entries(blocks)


def test_same_header_table_replacement_fails_complete_content_signature():
    blocks = _blocks()
    position = next(index for index, block in enumerate(blocks)
                    if block[0] == "table")
    original = blocks[position]
    hostile_rows = [list(row) for row in original[2]]
    hostile_rows[0][0] = "Different object with retained headers"
    blocks[position] = ("table", original[1], hostile_rows)

    with pytest.raises(PublicationContractError, match="content or row order"):
        _entries(blocks)


def test_manual_pdf_contains_every_reference_caption_and_resolved_link():
    items = [entry.item for entry in _entries() if entry.item is not None]
    reader = pypdf.PdfReader(
        io.BytesIO(manual.build_manual_pdf_bytes(figures=False))
    )
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    flat = re.sub(r"\s+", " ", text)
    links = [
        annotation.get_object()
        for page in reader.pages
        for annotation in page.get("/Annots", [])
        if annotation.get_object().get("/Subtype") == "/Link"
    ]

    for item in items:
        assert f"See {item.label}." in text
        caption = re.sub(
            r"\s+", " ", item.caption.replace("*", "").replace("$", "")
        )
        assert caption in flat
    assert len(links) >= len(items)
    assert all(link.get("/Dest") for link in links)


class _Context:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _FakeStreamlit:
    def __init__(self):
        self.session_state = {}
        self.markdowns = []
        self.captions = []

    def container(self, **_kwargs):
        return _Context()

    def expander(self, *_args, **_kwargs):
        return _Context()

    def spinner(self, *_args, **_kwargs):
        return _Context()

    def button(self, *_args, **_kwargs):
        return False

    def download_button(self, *_args, **_kwargs):
        return False

    def selectbox(self, *_args, **_kwargs):
        return "Part A - Get started"

    def caption(self, value, **_kwargs):
        self.captions.append(str(value))

    def markdown(self, value, **_kwargs):
        self.markdowns.append(str(value))

    def plotly_chart(self, *_args, **_kwargs):
        return None

    def divider(self):
        return None


def test_streamlit_manual_uses_matching_reference_heading_and_caption(monkeypatch):
    fake = _FakeStreamlit()
    monkeypatch.setattr(manual, "st", fake)

    manual.render_manual_streamlit()

    assert "[See Figure A2-1](#figure-a2-1)." in fake.markdowns
    assert "##### Figure A2-1" in fake.markdowns
    assert "[See Table A3-1](#table-a3-1)." in fake.markdowns
    assert "##### Table A3-1" in fake.markdowns
    assert any("Worked-example section" in text for text in fake.captions)


def test_report_table_reference_caption_and_fragments_share_one_identity():
    builder = sector_report.ReportBuilder(
        io.BytesIO(), {}, {}, {}, figures=False, qa_appendix=False
    )
    builder._h1("Actions")
    builder._h2("Design values")
    rows = [["Force (kN)", "Moment (kNm)"]]
    rows.extend([[str(index), str(index * 2)] for index in range(20)])
    builder._table(rows, [40 * mm, 40 * mm], keep=False)
    table = next(
        value for value in _tables(builder)
        if isinstance(value, sector_report._PaginatedReportTable)
    )

    assert "See Table 1.1." in " ".join(
        _flow_text(value) for value in builder.flow
    )
    assert table._cellvalues[0][0].getPlainText() == (
        "See Table 1.1."
        "Table 1.1. Published evidence for Design values: Force (kN)"
    )
    assert table.repeatRows == 4
    leading, trailing = table.split(80 * mm, 70 * mm)
    assert "See Table 1.1." in leading._cellvalues[0][0].getPlainText()
    assert "(continued)" not in leading._cellvalues[0][0].getPlainText()
    assert "See Table 1.1." not in trailing._cellvalues[0][0].getPlainText()
    assert "Table 1.1 (continued)." in trailing._cellvalues[0][0].getPlainText()
    for fragment in (leading, trailing):
        assert [
            _cell_text(cell)
            for cell in fragment._cellvalues[fragment._sector_header_row]
        ] == ["Force (kN)", "Moment (kNm)"]


def test_report_figure_reference_image_and_caption_are_indivisible(monkeypatch):
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
        "/x8AAusB9Wl2nGQAAAAASUVORK5CYII="
    )
    monkeypatch.setattr(sector_report, "_fig_png", lambda *_args: (png, False))
    builder = sector_report.ReportBuilder(
        io.BytesIO(), {}, {}, {}, figures=True, qa_appendix=False
    )
    builder._h1("Capacity")
    figure = go.Figure()
    figure.update_layout(title="Capacity envelope")

    builder._fig(figure, 50, 40)

    published = builder.flow[-2]
    assert isinstance(published, Table)
    assert published.splitByRow == 0
    assert published.splitInRow == 0
    text = _flow_text(published)
    assert "See Figure 1.1." in text
    assert "Figure 1.1. Capacity envelope" in text
