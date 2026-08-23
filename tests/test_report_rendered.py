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
    detect_sparse_report_pages,
    render_pdf,
    validate_equation_source_colocation,
    validate_fixture_engineering,
    validate_outline_destinations,
    validate_pdf_content,
    validate_rendered_pages,
    validate_results_overview_pagination,
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


def test_reference_fixture_uses_independent_duration_crack_width_criteria():
    inp = _inputs()
    elastic_cases = inp["elastic_cases"]

    assert inp["sls_long_term_permitted_crack_width_mm"] == pytest.approx(0.20)
    assert inp["sls_short_term_permitted_crack_width_mm"] == pytest.approx(0.20)
    assert inp["sls_heightened_permitted_crack_width_mm"] == pytest.approx(0.20)
    assert all(
        "ordinary_crack_criterion_mm" not in case for case in elastic_cases
    )
    output = _results(inp)["elastic_cases"][0]["results"]["elastic"][
        "crack_output"
    ]
    assert set(output) == {"long_term", "short_term"}
    for duration in ("long_term", "short_term"):
        assert output[duration]["duration"] == duration
        assert output[duration]["criterion_mm"] == pytest.approx(0.20)
        assert output[duration]["criterion_source"] == (
            f"User input - Analysis settings - {duration.replace('_', '-')}"
        )


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
        if (
            _EXPECTED_PLASTIC_WORKED_HEADING in page_text
            and "NA intercepts" in page_text
        )
    ]
    assert len(heading_pages) == 1
    concrete_pages = [
        page_text
        for page_text in page_texts
        if "Characteristic strength" in page_text
    ]
    assert len(concrete_pages) == 1
    assert "EQ-MATERIALS.CONCRETE.FCD" in concrete_pages[0]
    assert "= 20 MPa" in concrete_pages[0]
    assert validate_results_overview_pagination(page_texts)

    validate_equation_source_colocation(page_texts)


def test_audit_fixture_flags_sparse_non_opener_pages_for_visual_review():
    pdf = build_fixture_pdf(figures=False, profile="Audit")
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    page_texts = [page.extract_text() or "" for page in reader.pages]
    opener_pages = {
        reader.get_destination_page_number(item) + 1
        for item in reader.outline
        if not isinstance(item, list)
    }
    sparse = detect_sparse_report_pages(
        render_pdf(pdf),
        page_texts,
        opener_pages=opener_pages,
    )
    assert len(sparse) == 1
    assert all(0.0 < coverage < 0.35 for _page, coverage in sparse)
    sparse_text = page_texts[sparse[0][0] - 1]
    assert "EQ-FATIGUE.CONCRETE.UTILISATION" in sparse_text
    assert "SECTOR-MATH[" in sparse_text
    assert "Source / method note:" in sparse_text


def test_worked_example_text_rejects_any_unavailable_placeholder():
    with pytest.raises(AssertionError, match="unavailable worked-example"):
        validate_worked_example_text(
            "Worked plastic calculation\n"
            "The completed retained operands are unavailable"
        )


def test_equation_source_colocation_rejects_a_page_split():
    with pytest.raises(AssertionError, match="equation/source page split"):
        validate_equation_source_colocation(
            [
                (
                    "Equation (1.1) | EQ-TEST.RELATION\n"
                    "Source / method note: retained source begins\n"
                ),
                (
                    "retained source continuation\n"
                    "SECTOR-SOURCE-END[sector-equation-1-1-test__relation]\n"
                ),
            ],
            expected_equation_count=1,
        )


@pytest.mark.real_image_export
@pytest.mark.xdist_group(name="publication-real-figures")
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
