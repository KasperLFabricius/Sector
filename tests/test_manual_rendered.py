"""Rendered-artifact regression for the issued Sector user manual."""

from __future__ import annotations

from tools.manual_render_fixture import (
    build_fixture_pdf,
    render_pdf,
    validate_pdf_content,
    validate_rendered_pages,
)
from tools.pdf_preflight import crop_difference_hash, hash_distance


def test_issued_manual_renders_every_page_and_retains_navigation():
    pdf = build_fixture_pdf()
    validate_pdf_content(pdf)
    pages = render_pdf(pdf)
    validate_rendered_pages(pages)
    equation_hash = crop_difference_hash(
        pages[19], (0.08, 0.06, 0.93, 0.94)
    )
    assert hash_distance(equation_hash, "622301090a490103") <= 2
