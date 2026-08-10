"""Rendered-artifact regression for the issued Sector user manual."""

from __future__ import annotations

import io

import pypdf

from tools.manual_render_fixture import (
    _unrendered_math_token,
    build_fixture_pdf,
    manual,
    render_pdf,
    validate_pdf_content,
    validate_rendered_pages,
)


def test_manual_math_token_guard_does_not_match_ordinary_prose_substrings():
    assert _unrendered_math_token("Enter one unambiguous decimal number.") is None
    assert _unrendered_math_token(r"V = \Big[C + k\Big]") == "Big"


def test_manual_math_token_guard_ignores_canonical_semantic_rows_only():
    assert _unrendered_math_token(
        "SECTOR-MATH[manual-expression] x = sqrt(y)\n"
        "x = \u221ay"
    ) is None
    assert _unrendered_math_token("Visible fallback: sqrt(y)") == "sqrt"


def test_browser_free_manual_semantics_keep_radicals_without_raw_math_leaks():
    pdf = manual.build_manual_pdf_bytes(figures=False)
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert _unrendered_math_token(text) is None
    assert chr(0x221A) in text


def test_issued_manual_renders_every_page_and_retains_navigation():
    pdf = build_fixture_pdf()
    validate_pdf_content(pdf)
    pages = render_pdf(pdf)
    validate_rendered_pages(pages)
