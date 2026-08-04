"""Independent F041 figure/table publication contract."""

from __future__ import annotations

import base64
import io
import pathlib
import re
import sys

import plotly.graph_objects as go
import pypdf
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, Table

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import manual
from publication_items import published_manual_blocks
import sector_report
import viz


_MANUAL_LABELS = (
    "Figure A2-1",
    "Figure A3-1", "Figure A3-2", "Table A3-1",
    "Table B1-1", "Table B3-1", "Table B3-2",
    "Figure B4-1", "Figure B4-2", "Figure B4-3",
    "Figure B5-1", "Table B5-1", "Table B5-2", "Table B5-3",
    "Table B5-4", "Table B5-5", "Table B5-6", "Table B5-7",
    "Table B6-1", "Figure C1-1", "Table C2-1",
    "Figure C3-1", "Figure C3-2", "Figure C3-3",
    "Figure C4-1", "Figure C4-2", "Figure C6-1", "Table C7-1",
    "Figure C8-1", "Figure C8-2", "Table C8-1",
    "Table D1-1", "Table D3-1",
)

_PUBLIC_FIGURE_FUNCTIONS = (
    "elastic_strain_figure",
    "concrete_curve_figure",
    "prestress_curve_figure",
    "steel_curve_figure",
    "section_figure",
    "fatigue_utilisation_map_figure",
    "fatigue_sn_figure",
    "fatigue_damage_figure",
    "detailing_geometry_figure",
    "shear_geometry_figure",
    "biaxial_shear_overview_figure",
    "interaction_figure",
    "interaction_nm_figure",
    "vt_interaction_figure",
    "tube_figure",
    "subtube_figure",
    "truss_figure",
)


def _manual_entries():
    return published_manual_blocks(
        manual.manual_publication_blocks(manual.manual_blocks())
    )


def _direct_tables(builder):
    tables = []
    for flowable in builder.flow:
        if isinstance(flowable, KeepTogether):
            tables.extend(
                child for child in flowable._content if isinstance(child, Table)
            )
        elif isinstance(flowable, Table):
            tables.append(flowable)
    return tables


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


def _cell_text(cell):
    if hasattr(cell, "getPlainText"):
        return cell.getPlainText()
    if isinstance(cell, (list, tuple)):
        return "".join(_cell_text(value) for value in cell)
    return str(cell)


def test_manual_item_inventory_is_complete_ordered_and_unique():
    items = [entry.item for entry in _manual_entries() if entry.item is not None]

    assert tuple(item.label for item in items) == _MANUAL_LABELS
    assert sum(item.kind == "Figure" for item in items) == 16
    assert sum(item.kind == "Table" for item in items) == 17
    assert len({item.anchor for item in items}) == len(items)
    assert all(item.caption.strip() for item in items)
    assert all(item.markdown_reference.endswith(f"](#{item.anchor}).") for item in items)


def test_manual_pdf_publishes_every_caption_reference_and_destination():
    items = [entry.item for entry in _manual_entries() if entry.item is not None]
    reader = pypdf.PdfReader(
        io.BytesIO(manual.build_manual_pdf_bytes(figures=False))
    )
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    flat_text = re.sub(r"\s+", " ", text)
    links = [
        annotation.get_object()
        for page in reader.pages
        for annotation in page.get("/Annots", [])
        if annotation.get_object().get("/Subtype") == "/Link"
    ]

    for item in items:
        assert f"See {item.label}." in text
        assert item.label in text
        expected_caption = re.sub(r"\s+", " ", item.caption.replace("*", "").replace("$", ""))
        assert expected_caption in flat_text
    # ReportLab refuses to save an unresolved local destination.  The completed
    # build plus concrete /Dest arrays proves that every emitted reference lands.
    assert len(links) >= len(items)
    assert all(link.get("/Dest") for link in links)


class _Context:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _FakeStreamlit:
    def __init__(self, selected_part):
        self.selected_part = selected_part
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
        return self.selected_part

    def caption(self, value, **_kwargs):
        self.captions.append(str(value))

    def markdown(self, value, **_kwargs):
        self.markdowns.append(str(value))

    def plotly_chart(self, *_args, **_kwargs):
        return None

    def divider(self):
        return None


def test_streamlit_manual_publishes_matching_figure_and_table_links(monkeypatch):
    fake = _FakeStreamlit("Part A - Get started")
    monkeypatch.setattr(manual, "st", fake)

    manual.render_manual_streamlit()

    assert "[See Figure A2-1](#figure-a2-1)." in fake.markdowns
    assert "##### Figure A2-1" in fake.markdowns
    assert "[See Table A3-1](#table-a3-1)." in fake.markdowns
    assert "##### Table A3-1" in fake.markdowns
    assert any("Worked-example section" in value for value in fake.captions)


def test_report_table_identity_caption_and_reference_share_one_number():
    builder = sector_report.ReportBuilder(
        io.BytesIO(), {}, {}, {}, figures=False, qa_appendix=False
    )
    builder._h1("Actions")
    builder._h2("Design values")
    builder._table(
        [["Force (kN)", "Moment (kNm)"], ["100", "20"]],
        [45 * mm, 45 * mm],
    )

    table = next(
        value for value in _direct_tables(builder)
        if isinstance(value, sector_report._PaginatedReportTable)
    )
    text = " ".join(_flow_text(value) for value in builder.flow)
    caption = table._cellvalues[0][0].getPlainText()

    assert "See Table 1.1." in text
    assert caption == "Table 1.1. Published evidence for Design values: Force (kN)"
    assert table._sector_publication_label == "Table 1.1"
    # Caption, section, subsection and the unit-bearing header all repeat.
    assert table.repeatRows == 4
    assert table._sector_header_row == 3


def test_report_table_fragments_repeat_units_and_mark_continuation():
    builder = sector_report.ReportBuilder(
        io.BytesIO(), {}, {}, {}, figures=False, qa_appendix=False
    )
    builder._h1("Actions")
    rows = [["Force (kN)", "Moment (kNm)"]]
    rows.extend([[str(index), str(index * 2)] for index in range(20)])
    builder._table(rows, [40 * mm, 40 * mm], keep=False)
    table = next(
        value for value in _direct_tables(builder)
        if isinstance(value, sector_report._PaginatedReportTable)
    )

    leading, trailing = table.split(80 * mm, 70 * mm)
    assert "(continued)" not in leading._cellvalues[0][0].getPlainText()
    assert "Table 1.1 (continued)." in trailing._cellvalues[0][0].getPlainText()
    for fragment in (leading, trailing):
        header = fragment._cellvalues[fragment._sector_header_row]
        assert [_cell_text(cell) for cell in header] == [
            "Force (kN)", "Moment (kNm)"
        ]


def test_report_figure_identity_caption_reference_and_grayscale(monkeypatch):
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
    figure.add_scatter(x=[0, 1], y=[0, 1], mode="lines", name="first")
    figure.add_scatter(x=[0, 1], y=[1, 0], mode="lines", name="second")
    figure.update_layout(title="Capacity envelope")

    builder._fig(figure, 50, 40)

    published = builder.flow[-2]
    text = _flow_text(published)
    assert isinstance(published, Table)
    assert published.splitByRow == 0
    assert published.splitInRow == 0
    assert "See Figure 1.1." in text
    assert "Figure 1.1. Capacity envelope" in text
    cues = [cue for _name, cue in viz.grayscale_distinction_cues(figure)]
    assert len(cues) == len(set(cues))


def test_every_public_figure_factory_applies_grayscale_finalizer():
    assert all(
        hasattr(getattr(viz, name), "__wrapped__")
        for name in _PUBLIC_FIGURE_FUNCTIONS
    )


def test_grayscale_finalizer_distinguishes_lines_markers_and_bars():
    figure = go.Figure()
    for index in range(3):
        figure.add_scatter(
            x=[0, 1], y=[index, index + 1], mode="lines+markers",
            name=f"series {index}", line=dict(color=f"rgb({index},0,0)"),
        )
    figure.add_bar(x=["a"], y=[1], name="bar one")
    figure.add_bar(x=["a"], y=[2], name="bar two")

    viz.apply_grayscale_safe_distinctions(figure)
    cues = [cue for _name, cue in viz.grayscale_distinction_cues(figure)]

    assert len(cues) == len(set(cues))
