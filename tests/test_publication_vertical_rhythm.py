"""Focused F019/F037 publication sequencing and rhythm contracts."""

from __future__ import annotations

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
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import manual  # noqa: E402
import sector_report  # noqa: E402


def _builder(inp=None, out=None):
    return sector_report.ReportBuilder(
        io.BytesIO(), {}, inp or {}, out or {}, figures=False, qa_appendix=False
    )


def _pdf(flow):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=25 * mm,
        bottomMargin=20 * mm,
    )
    doc.build(flow)
    return buffer.getvalue()


def test_report_formula_and_reference_geometry_is_explicit():
    styles = sector_report._styles()
    formula = styles["formula"]
    reference = styles["ref"]

    assert formula.fontSize == pytest.approx(9.5)
    assert formula.leading == pytest.approx(14)
    assert formula.leftIndent == pytest.approx(12)
    assert formula.rightIndent == pytest.approx(6)
    assert formula.spaceBefore == pytest.approx(2)
    assert formula.spaceAfter == pytest.approx(3)

    assert reference.fontSize == pytest.approx(8)
    assert reference.leading == pytest.approx(11)
    assert reference.leftIndent == pytest.approx(12)
    assert reference.rightIndent == pytest.approx(6)
    assert reference.spaceAfter == pytest.approx(6)


def test_assessment_banner_owns_spacing_and_retains_plain_table_palette():
    builder = _builder()
    builder._status_block("PASS - complete", "PASS")

    wrapper, = builder.flow
    assert isinstance(wrapper, KeepTogether)
    table, = wrapper._content
    assert type(table) is Table
    assert table._sector_status_banner is True
    assert table.spaceBefore == pytest.approx(2)
    assert table.spaceAfter == pytest.approx(6)
    background, foreground = sector_report._assessment_colors("PASS")
    assert any(command[0] == "BACKGROUND" and command[3] == background
               for command in table._bkgrndcmds)
    assert any(command[0] == "BOX" and command[4] == foreground
               for command in table._linecmds)


def test_loads_and_analysis_settings_start_on_distinct_pages(monkeypatch):
    builder = _builder()
    monkeypatch.setattr(
        sector_report.viz, "section_figure", lambda *args, **kwargs: object()
    )
    builder._geometry_tables = lambda: builder._p("GEOMETRY BODY")
    builder._concrete_block = lambda: builder._p("CONCRETE BODY")
    builder._loads_block = lambda: builder._p("LOADS BODY")
    builder._settings_block = lambda: builder._p("SETTINGS BODY")

    builder._inputs()
    loads_index = next(
        index for index, item in enumerate(builder.flow)
        if isinstance(item, Paragraph) and item.getPlainText() == "Loads"
    )
    settings_index = next(
        index for index, item in enumerate(builder.flow)
        if isinstance(item, Paragraph) and item.getPlainText() == "Analysis settings"
    )
    assert isinstance(builder.flow[loads_index - 1], PageBreak)
    assert isinstance(builder.flow[settings_index - 1], PageBreak)
    assert not any(
        isinstance(item, KeepTogether)
        and "LOADS BODY" in " ".join(
            child.getPlainText() for child in item._content
            if isinstance(child, Paragraph)
        )
        for item in builder.flow
    )

    reader = pypdf.PdfReader(io.BytesIO(_pdf(builder.flow)))
    page_texts = [page.extract_text() or "" for page in reader.pages]
    loads_page = next(index for index, text in enumerate(page_texts)
                      if "LOADS BODY" in text)
    settings_page = next(index for index, text in enumerate(page_texts)
                         if "SETTINGS BODY" in text)
    assert loads_page != settings_page
    assert "Loads" in page_texts[loads_page]
    assert "Analysis settings" in page_texts[settings_page]


def test_forced_page_break_discards_only_trailing_layout_gaps():
    builder = _builder()
    first = Paragraph("first semantic block", builder.s["body"])
    builder.flow.extend([first, Spacer(1, 4)])
    builder._page_break()
    assert builder.flow == [first, builder.flow[-1]]
    assert isinstance(builder.flow[-1], PageBreak)

    builder = _builder()
    nested = Paragraph("nested semantic block", builder.s["body"])
    wrapper = KeepTogether([nested, Spacer(1, 4)])
    builder.flow.append(wrapper)
    builder._page_break()
    assert builder.flow[0] is wrapper
    assert wrapper._content == [nested]
    assert isinstance(builder.flow[-1], PageBreak)


def test_main_and_grouped_fatigue_settings_tables_are_splittable():
    fatigue = {
        "checks": {},
        "partial_factors": {},
        "concrete_parameters": {},
        "basis": {},
    }
    builder = _builder(out={"fatigue": fatigue})
    calls = []

    def capture(data, widths, **kwargs):
        calls.append((data, widths, kwargs))

    builder._table = capture
    builder._settings_block()

    assert len(calls) == 2
    assert all(data[0] == ["Setting", "Value"] for data, _widths, _kwargs in calls)
    assert all(kwargs.get("keep") is False for _data, _widths, kwargs in calls)


def test_manual_pdf_styles_retain_lazy_dependency_boundary():
    styles = manual._manual_pdf_styles(
        sector_report,
        colors,
        ParagraphStyle,
        getSampleStyleSheet,
        TA_CENTER,
    )

    assert styles["MH1"].fontSize == pytest.approx(15)
    assert styles["MH1"].spaceBefore == pytest.approx(14)
    assert styles["MH1"].spaceAfter == pytest.approx(8)
    assert styles["MSmall"].fontSize == pytest.approx(8)
    assert styles["MSmall"].leading == pytest.approx(11)
    assert styles["MMath"].alignment == TA_CENTER


def test_manual_data_tables_use_bounded_spacing_and_padding(monkeypatch):
    import reportlab.platypus as platypus

    captured = {}

    class _CaptureDoc:
        def __init__(self, *args, **kwargs):
            captured["doc_kwargs"] = kwargs

        def multiBuild(self, flow, canvasmaker=None):
            captured["flow"] = flow
            captured["canvasmaker"] = canvasmaker

    monkeypatch.setattr(platypus, "SimpleDocTemplate", _CaptureDoc)
    monkeypatch.setattr(
        manual,
        "manual_publication_blocks",
        lambda: (("table", ["A", "B"], [["one", "two"]]),),
    )

    manual.build_manual_pdf(io.BytesIO(), figures=False)
    table = next(item for item in captured["flow"] if type(item) is Table)
    assert table.spaceBefore == pytest.approx(2)
    for row in table._cellStyles:
        for style in row:
            assert style.leftPadding == pytest.approx(5)
            assert style.rightPadding == pytest.approx(5)
            assert style.topPadding == pytest.approx(5)
            assert style.bottomPadding == pytest.approx(5)

    contents = next(
        item for item in captured["flow"]
        if isinstance(item, Paragraph) and item.getPlainText() == "Contents"
    )
    version = next(
        item for item in captured["flow"]
        if isinstance(item, Paragraph)
        and item.getPlainText().startswith("Version ")
    )
    assert contents.style.spaceAfter == pytest.approx(8)
    assert version.style.leading == pytest.approx(11)
