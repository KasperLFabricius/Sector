"""Rendered-artifact regression for the issued Sector user manual."""

from __future__ import annotations

from tools.manual_render_fixture import (
    build_fixture_pdf,
    render_pdf,
    validate_pdf_content,
    validate_rendered_pages,
)


def test_issued_manual_renders_every_page_and_retains_navigation():
    pdf = build_fixture_pdf()
    validate_pdf_content(pdf)
    pages = render_pdf(pdf)
    validate_rendered_pages(pages)
