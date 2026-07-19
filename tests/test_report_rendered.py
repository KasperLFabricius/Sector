"""Rendered-artifact regression tests for the issued Sector PDF."""

from __future__ import annotations

import io

import pypdf

from sector import __version__
from tools.report_render_fixture import (
    build_fixture_pdf,
    render_pdf,
    validate_rendered_pages,
)


def test_issued_report_renders_every_page():
    pdf = build_fixture_pdf()
    pages = render_pdf(pdf)
    validate_rendered_pages(pages)


def test_issued_report_retains_expected_page_content():
    pdf = build_fixture_pdf()
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "QA-REFERENCE" in text
    assert "Rendered report regression" in text
    assert "Ultimate (plastic) capacity" in text
    assert "Cracked-section elastic stresses" in text
    assert f"Generated 2026-07-19 12:00 by Sector {__version__}" in text
    assert "figure unavailable" not in text
