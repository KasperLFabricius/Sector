"""Rendered-artifact regression tests for the issued Sector PDF."""

from __future__ import annotations

import io

import pypdf
import pytest

from tools.report_render_fixture import (
    _inputs,
    _results,
    build_fixture_pdf,
    render_pdf,
    validate_fixture_engineering,
    validate_pdf_content,
    validate_rendered_pages,
    validate_worked_example_text,
)


def test_reference_fixture_engineering_is_internally_consistent():
    inp = _inputs()
    validate_fixture_engineering(inp, _results(inp))


def test_reference_fixture_retains_governing_worked_chains_without_figures():
    """Check the textbook payload and PDF text without launching a browser."""
    pdf = build_fixture_pdf(figures=False)
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    validate_worked_example_text(text)


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
