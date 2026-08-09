"""Rendered-artifact regression tests for the issued Sector PDF."""

from __future__ import annotations

import io

import pypdf
import pytest

from tools.report_render_fixture import (
    _EXPECTED_PLASTIC_WORKED_HEADING,
    _inputs,
    _results,
    build_fixture_pdf,
    render_pdf,
    validate_fixture_engineering,
    validate_outline_destinations,
    validate_pdf_content,
    validate_rendered_pages,
    validate_worked_example_text,
)


def test_outline_validation_accepts_a_visible_heading_wrapped_by_pdf_layout(
    tmp_path,
):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    path = tmp_path / "wrapped-outline.pdf"
    title = "11. Governing shear + torsion concrete-strut interaction - PL-QA-1"
    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.bookmarkPage("wrapped")
    pdf.addOutlineEntry(title, "wrapped", level=0)
    pdf.drawString(72, 760, "11. Governing shear + torsion concrete-strut")
    pdf.drawString(72, 740, "interaction - PL-QA-1")
    pdf.save()

    reader = pypdf.PdfReader(str(path))
    assert validate_outline_destinations(reader) == [(title, 1)]


def test_outline_validation_still_rejects_a_destination_on_the_wrong_page(
    tmp_path,
):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    path = tmp_path / "wrong-outline-page.pdf"
    title = "11. Governing shear + torsion concrete-strut interaction - PL-QA-1"
    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.bookmarkPage("wrong")
    pdf.addOutlineEntry(title, "wrong", level=0)
    pdf.drawString(72, 760, "Unrelated preceding page")
    pdf.showPage()
    pdf.drawString(72, 760, "11. Governing shear + torsion concrete-strut")
    pdf.drawString(72, 740, "interaction - PL-QA-1")
    pdf.save()

    with pytest.raises(
        AssertionError, match="outline destination misses its heading"
    ):
        validate_outline_destinations(pypdf.PdfReader(str(path)))


def test_reference_fixture_engineering_is_internally_consistent():
    inp = _inputs()
    validate_fixture_engineering(inp, _results(inp))


def test_reference_fixture_retains_governing_worked_chains_without_figures():
    """Check the textbook payload and PDF text without launching a browser."""
    pdf = build_fixture_pdf(figures=False)
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    page_texts = [page.extract_text() or "" for page in reader.pages]
    text = "\n".join(page_texts)
    validate_worked_example_text(text)
    assert "Candidate summary for governing crack example" in text
    heading_pages = [
        page_text
        for page_text in page_texts
        if _EXPECTED_PLASTIC_WORKED_HEADING in page_text
    ]
    assert len(heading_pages) == 1
    assert "NA intercepts" in heading_pages[0]


def test_worked_example_text_rejects_any_unavailable_placeholder():
    with pytest.raises(AssertionError, match="unavailable worked-example"):
        validate_worked_example_text(
            "Worked plastic calculation\n"
            "The completed retained operands are unavailable"
        )


def test_issued_report_renders_every_page_and_retains_expected_content():
    """Exercise the issued artifact once so Kaleido is never run concurrently.

    The full CI gate uses pytest-xdist.  Keeping rendering and content checks in
    separate tests allowed two workers to start independent headless-browser
    servers at the same time, intermittently exhausting the first export's
    timeout even though the subsequent standalone render succeeded.
    """
    pdf = build_fixture_pdf()
    validate_pdf_content(pdf)
    pages = render_pdf(pdf)
    validate_rendered_pages(pages, require_document_control=True)
