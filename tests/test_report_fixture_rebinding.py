"""Hostile checks for the reviewed Audit fixture composition."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pypdf
import pytest
from pypdf.generic import ArrayObject, FloatObject, NameObject
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.report_render_fixture import (
    _fixture_positioned_captions,
    validate_fixture_fatigue_note_link,
    validate_fixture_figure_inventory,
    validate_fixture_settings_heading,
    validate_results_overview_pagination,
)


def _overview_pdf(*, font_size=11.5, settings_label="Neutral-axis sweep start",
                  duplicate_note=False, clause_paragraphs=False):
    stream = io.BytesIO()
    pdf = canvas.Canvas(stream)
    pdf.setFont("Helvetica", 10.5)
    lines = [
        "The table shows the governing result for each check type.",
        "Table 1.1. Results overview across calculated checks",
        "Check Action set Status Result Criterion Source / note",
        "Checks and comparisons",
        "Plastic bending",
        "Formula (6.31) minimum-reinforcement screen - separate link detailing",
        "DK heightened crack-control minimum",
        "Calculated outputs",
        "Fatigue Road traffic PASS 46.2 % <= 100 %",
    ]
    y = 760
    for line in lines:
        pdf.drawString(50, y, line)
        y -= 18
    pdf.drawString(50, y, "Note 28")
    pdf.linkAbsolute("", "note28", Rect=(49, y-1, 100, y+12))
    pdf.drawString(50, y-18, "The table shows one governing row for each engineering check type.")
    pdf.showPage()
    pdf.setFont("Helvetica", 10.5)
    pdf.bookmarkPage("note28", fit="XYZ", left=50, top=774.5)
    pdf.drawString(50, 760, "Note 28. Fatigue: Road traffic.")
    pdf.drawString(50, 742, "Source: Grouped action spectrum")
    pdf.drawString(50, 724, "governing: R1 - simplified stress-range screen")
    if clause_paragraphs:
        pdf.drawString(50, 706, "max Miner D 1.7475 \u00d7 10-7;")
        pdf.drawString(50, 682, "max yield/proof utilisation 20.8 %")
    else:
        pdf.drawString(50, 706, "max Miner D 1.7475 \u00d7 10-7; max yield/proof utilisation 20.8 %")
    if duplicate_note:
        pdf.drawString(50, 680, "Note 28. Fatigue: Road traffic.")
    pdf.setFont("Helvetica-Bold", font_size)
    pdf.drawString(50, 620, "3.9 Analysis settings")
    pdf.setFont("Helvetica", 10.5)
    for n, line in enumerate(("General numerical analysis settings", "Setting Value",
                              "Analysis mode Both", settings_label + " 0.000")):
        pdf.drawString(50, 600 - 18*n, line)
    pdf.save()
    reader = pypdf.PdfReader(io.BytesIO(stream.getvalue()))
    return reader, [page.extract_text() or "" for page in reader.pages]


def test_reviewed_overview_row_note_link_and_settings_are_accepted():
    reader, texts = _overview_pdf()
    assert validate_results_overview_pagination(texts) == (1,)
    validate_fixture_fatigue_note_link(reader, texts)
    validate_fixture_settings_heading(reader)


@pytest.mark.parametrize("old,new", [
    ("46.2 %", "20.8 %"), ("PASS", "FAIL"),
    ("<= 100 %", "<= 200 %"), ("Road traffic PASS", "Other spectrum PASS"),
    ("Note 28\nThe table", "Note 27\nThe table"),
    ("max yield/proof utilisation 20.8 %", "max yield/proof utilisation 46.2 %"),
    ("max Miner D 1.7475 \u00d7 10-7", "max Miner D 1.7475 \u00d7 10-6"),
    ("governing: R1 -", "governing: R2 -"),
    ("Check Action set Status Result Criterion Source / note", "Check Result"),
    ("Note 28. Fatigue: Road traffic.", "Note 28. Other check: Road traffic."),
])
def test_overview_rejects_wrong_row_and_wrong_linked_criterion(old, new):
    _reader, texts = _overview_pdf()
    assert sum(t.count(old) for t in texts) == 1
    changed = [t.replace(old, new) for t in texts]
    with pytest.raises(AssertionError):
        validate_results_overview_pagination(changed)


def test_overview_rejects_duplicate_note_even_with_correct_evidence():
    _reader, texts = _overview_pdf(duplicate_note=True)
    with pytest.raises(AssertionError, match="exactly one"):
        validate_results_overview_pagination(texts)


def test_correct_percentages_elsewhere_do_not_repair_a_wrong_row_or_note():
    _reader, texts = _overview_pdf()
    texts[0] = texts[0].replace("46.2 %", "20.8 %")
    texts[1] += "\nUnrelated result: 46.2 %"
    with pytest.raises(AssertionError, match="exact fatigue overview row"):
        validate_results_overview_pagination(texts)
    _reader, texts = _overview_pdf()
    texts[1] = texts[1].replace("20.8 %", "46.2 %")
    texts.append("Unrelated result: max yield/proof utilisation 20.8 %")
    with pytest.raises(AssertionError, match="criterion evidence"):
        validate_results_overview_pagination(texts)


@pytest.mark.parametrize("change", ["none", "missing-header", "gap", "row-after-note"])
def test_overview_continuation_keeps_headers_order_and_contiguous_pages(change):
    _reader, texts = _overview_pdf()
    final_row = "Fatigue Road traffic PASS 46.2 % <= 100 %\nNote 28\n"
    note = "The table shows one governing row for each engineering check type.\n"
    assert final_row in texts[0] and note in texts[0]
    first = texts[0].replace(final_row, "").replace(note, "")
    second = texts[0].replace("Table 1.1.", "Table 1.1 (continued).")
    if change == "missing-header":
        second = second.replace("Check Action set Status Result Criterion Source / note", "")
    elif change == "row-after-note":
        second = second.replace(final_row, "").replace(note, note + final_row)
    changed = [first, second, texts[1]]
    if change == "gap":
        changed.insert(1, "Unrelated intervening page")
    if change == "none":
        assert validate_results_overview_pagination(changed) == (1, 2)
    else:
        with pytest.raises(AssertionError):
            validate_results_overview_pagination(changed)


@pytest.mark.parametrize("change", ["page", "height", "missing", "duplicate"])
def test_fatigue_link_must_reach_exact_heading(change):
    reader, texts = _overview_pdf()
    annotations = reader.pages[0]["/Annots"]
    annotation = annotations[0].get_object()
    if change == "page":
        annotation["/Dest"][0] = reader.pages[0].indirect_reference
    elif change == "height":
        annotation["/Dest"][3] = FloatObject(650)
    elif change == "missing":
        reader.pages[0][NameObject("/Annots")] = ArrayObject()
    else:
        annotations.append(annotations[0])
    with pytest.raises(AssertionError):
        validate_fixture_fatigue_note_link(reader, texts)


@pytest.mark.parametrize("font,label", [(10.5, "Neutral-axis sweep start"),
                                        (11.5, "Sweep start")])
def test_settings_rejects_body_font_or_obsolete_table(font, label):
    reader, _texts = _overview_pdf(font_size=font, settings_label=label)
    with pytest.raises(AssertionError):
        validate_fixture_settings_heading(reader)


class _PdfObject(dict):
    def get_object(self):
        return self

    def extract_text(self, *, visitor_text=None, visitor_operand_before=None):
        if visitor_operand_before is not None:
            return self.brand_page.extract_text(visitor_operand_before=visitor_operand_before)
        for text, cm, tm, font, size in self.caption_fragments:
            visitor_text(text, cm, tm, font, size)
        return ""


_FIGURE_CAPTIONS = (
    "Input coordinates and element IDs. Concurrent Plastic actions: PL-QA-2. Dimensions are",
    "Concrete", "M1 - New B500 reinforcement", "M2 - Existing reinforcement",
    "Governing clear-spacing pair", "Minimum-reinforcement geometry",
    "PL-QA-1: plastic strain. Ultimate capacity at NA angle 90 deg.",
    "PL-QA-1: plastic stress. Ultimate capacity at NA angle 90 deg.",
    "M-M interaction",
    "PL-QA-2: plastic strain. Ultimate capacity at NA angle 90 deg.",
    "PL-QA-2: plastic stress. Ultimate capacity at NA angle 90 deg.",
    "Plastic state at NA angle = 90 deg (tension + / compression -)",
    "Vy,Ed geometry - bottom (-y) tension", "Variable-strut truss",
    "Concurrent longitudinal chord demand and conditional bending capacity at each",
    "Torsion tube", "V-T interaction (crushing)", "V-T interaction (crushing)",
    "Case PL-QA-1; shear component Vy; member strut angle 45.00 degrees. Concurrent",
    "EL-QA-1: elastic strain. Combined actions (TOTAL).",
    "EL-QA-1: elastic stress. Combined actions (TOTAL).",
    "EL-QA-2: elastic strain. Combined actions (TOTAL).",
    "EL-QA-2: elastic stress. Combined actions (TOTAL).",
    "Elastic state (tension + / compression -)", "Elastic strain profile",
    "Effective concrete area and reinforcement included in the crack-width calculation. The",
    "Effective concrete area and reinforcement included in the crack-width calculation. The",
    "Fatigue utilization - Road traffic. Stars identify adaptive concrete search points.", "S-N assessment - R1", "Miner damage - R1",
    "Miner damage - concrete fiber 3",
)


def _figure_pages():
    from app.publication_branding import logo_bytes
    from reportlab.lib.utils import ImageReader

    pages = [_PdfObject({"/Resources": _PdfObject({"/XObject": _PdfObject({
        "/Img": _PdfObject({"/Subtype": "/Image"}),
    })})}) for _ in _FIGURE_CAPTIONS]
    for i, (page, caption) in enumerate(zip(pages, _FIGURE_CAPTIONS), 1):
        cm = (1., 0., 0., 1., 50., 400.)
        tm = (1., 0., 0., 1., 0., 14.5)
        page.caption_fragments = [
            (f"Figure 3.{i}.", cm, tm, {"/BaseFont": "/DejaVuSans-Bold"}, 9.5),
            (" " + caption + "\n", cm, tm, {"/BaseFont": "/DejaVuSans"}, 9.5),
        ]
    # Retain every caption/index mutation while adding the required real cover logo.
    stream = io.BytesIO()
    pdf = canvas.Canvas(stream)
    width = 45 * 72 / 25.4
    pdf.drawImage(ImageReader(io.BytesIO(logo_bytes())), 40, 700, width,
                  width * 373 / 1280)
    pdf.save()
    brand_page = pypdf.PdfReader(io.BytesIO(stream.getvalue())).pages[0]
    pages[0]["/Resources"]["/XObject"].update(
        brand_page["/Resources"]["/XObject"].get_object()
    )
    pages[0].brand_page = brand_page
    pages[0].mediabox = brand_page.mediabox
    reader = type("Reader", (), {"pages": pages})()
    texts = [f"Figure 3.{i}. {caption}\n" for i, caption in enumerate(_FIGURE_CAPTIONS, 1)]
    return reader, texts


def test_explicit_31_figure_inventory_is_accepted():
    reader, texts = _figure_pages()
    assert len(validate_fixture_figure_inventory(reader, texts)) == 31


@pytest.mark.parametrize("change", ["missing", "duplicate", "wrong-case", "image-page"])
def test_figure_count_alone_cannot_hide_identity_or_colocation_failure(change):
    reader, texts = _figure_pages()
    if change == "missing":
        reader.pages.pop(6)
        texts.pop(6)
    elif change == "duplicate":
        texts[6] = texts[7]
    elif change == "wrong-case":
        texts[6] = texts[6].replace("PL-QA-1", "PL-QA-2")
    else:
        reader.pages[6]["/Resources"]["/XObject"] = _PdfObject()
        reader.pages[7]["/Resources"]["/XObject"]["/Second"] = _PdfObject({"/Subtype": "/Image"})
    with pytest.raises(AssertionError):
        validate_fixture_figure_inventory(reader, texts)


def test_authored_note_clause_paragraphs_keep_exact_evidence_and_destination():
    reader, texts = _overview_pdf(clause_paragraphs=True)
    assert validate_results_overview_pagination(texts) == (1,)
    validate_fixture_fatigue_note_link(reader, texts)
    validate_fixture_settings_heading(reader)



@pytest.mark.parametrize("change", ["none", "missing-tail", "wrong-tail", "body-paragraph",
    "font", "size", "baseline-gap", "horizontal-origin", "other-page"])
def test_caption_wrap_keeps_exact_identity_and_physical_paragraph(change):
    reader, texts = _figure_pages()
    page = reader.pages[27]
    label, first = page.caption_fragments
    text, cm, tm, font, size = first
    assert text.endswith("search points.\n")
    page.caption_fragments = [label,
        (text.removesuffix("points.\n") + "\n", cm, tm, font, size),
        ("points.\n", cm, (*tm[:5], tm[5] - 12), font, size)]
    texts[27] = texts[27].replace("search points.", "search\npoints.")
    content, next_cm, next_tm, next_font, next_size = page.caption_fragments[-1]
    if change == "missing-tail":
        page.caption_fragments.pop()
    elif change == "wrong-tail":
        page.caption_fragments[-1] = ("wrong.\n", next_cm, next_tm, next_font, next_size)
    elif change == "body-paragraph":
        # Same font and adjacent baseline, but a different Paragraph transform.
        page.caption_fragments[-1] = (content, (*next_cm[:5], next_cm[5] - 12), tm, next_font, next_size)
    elif change == "font":
        page.caption_fragments[-1] = (content, next_cm, next_tm, {"/BaseFont": "/OtherFont"}, next_size)
    elif change == "size":
        page.caption_fragments[-1] = (content, next_cm, next_tm, next_font, 10.5)
    elif change == "baseline-gap":
        page.caption_fragments[-1] = (content, next_cm, (*next_tm[:5], next_tm[5] - 12), next_font, next_size)
    elif change == "horizontal-origin":
        page.caption_fragments[-1] = (content, next_cm, (*next_tm[:4], 30., next_tm[5]), next_font, next_size)
    elif change == "other-page":
        reader.pages[28].caption_fragments.append(page.caption_fragments.pop())
    if change == "none":
        assert len(validate_fixture_figure_inventory(reader, texts)) == 31
    else:
        with pytest.raises(AssertionError):
            validate_fixture_figure_inventory(reader, texts)


def test_actual_report_caption_paragraph_wraps_without_losing_words():
    from reportlab.platypus import Paragraph
    import sector_report

    caption = "Fatigue utilization - Road traffic. Stars identify adaptive concrete search points."
    stream = io.BytesIO()
    pdf = canvas.Canvas(stream)
    paragraph = Paragraph("<b>Figure 19.1.</b> " + caption,
        sector_report._styles()["publication_caption"])
    width, height = paragraph.wrap(150 * 72 / 25.4, 1000)
    assert height > 12
    paragraph.drawOn(pdf, 50, 700 - height)
    pdf.save()
    page = pypdf.PdfReader(io.BytesIO(stream.getvalue())).pages[0]
    assert "search\npoints." in page.extract_text()
    assert _fixture_positioned_captions(page) == [("Figure 19.1.", caption)]
