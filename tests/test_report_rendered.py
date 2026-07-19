"""Rendered-artifact regression tests for the issued Sector PDF."""

from __future__ import annotations

from tools.report_render_fixture import (
    build_fixture_pdf,
    render_pdf,
    validate_pdf_content,
    validate_rendered_pages,
)


def test_issued_report_renders_every_page():
    pdf = build_fixture_pdf()
    pages = render_pdf(pdf)
    validate_rendered_pages(pages)


def test_issued_report_retains_expected_page_content():
    pdf = build_fixture_pdf()
    validate_pdf_content(pdf)
