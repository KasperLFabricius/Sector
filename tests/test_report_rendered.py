"""Rendered-artifact regression tests for the issued Sector PDF."""

from __future__ import annotations

from tools.report_render_fixture import (
    build_fixture_pdf,
    render_pdf,
    validate_pdf_content,
    validate_rendered_pages,
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
