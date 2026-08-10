"""Rendered-artifact regression for the issued Sector user manual."""

from __future__ import annotations

from tools.manual_render_fixture import (
    _unrendered_math_token,
    build_fixture_pdf,
    render_pdf,
    validate_pdf_content,
    validate_rendered_pages,
)


def test_manual_math_token_guard_does_not_match_ordinary_prose_substrings():
    assert _unrendered_math_token("Enter one unambiguous decimal number.") is None
    assert _unrendered_math_token(r"V = \Big[C + k\Big]") == "Big"


def test_issued_manual_renders_every_page_and_retains_navigation():
    pdf = build_fixture_pdf()
    validate_pdf_content(pdf)
    pages = render_pdf(pdf)
    validate_rendered_pages(pages)
