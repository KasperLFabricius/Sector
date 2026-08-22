"""Rendered-artifact regression for the issued Sector user manual."""

from __future__ import annotations

import io

import pypdf
import pytest

from tools.manual_render_fixture import (
    _MANUAL_CROPS,
    _unrendered_math_token,
    build_fixture_html,
    build_fixture_pdf,
    manual,
    render_pdf,
    validate_crops,
    validate_html_content,
    validate_pdf_content,
    validate_rendered_pages,
    validate_visible_contents_destinations,
)
from tools.publication_preflight import preflight_pdf
from tools.report_render_fixture import validate_outline_destinations


def test_manual_math_token_guard_does_not_match_ordinary_prose_substrings():
    assert _unrendered_math_token("Enter one unambiguous decimal number.") is None
    assert _unrendered_math_token(r"V = \Big[C + k\Big]") == "Big"


def test_manual_math_token_guard_ignores_canonical_semantic_rows_only():
    assert _unrendered_math_token(
        "SECTOR-MATH[manual-expression] x = sqrt(y)\n"
        "x = \u221ay"
    ) is None
    assert _unrendered_math_token("Visible fallback: sqrt(y)") == "sqrt"


def test_manual_visual_crop_excludes_commit_dependent_revision_text():
    contents_crop, footer_crop = _MANUAL_CROPS
    assert contents_crop.name == "manual contents navigation"
    assert contents_crop.box[1] >= 0.18
    assert footer_crop.name == "manual cover footer"


def test_browser_free_manual_semantics_keep_radicals_without_raw_math_leaks():
    pdf = manual.build_manual_pdf_bytes(figures=False)
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    cover_text = reader.pages[0].extract_text() or ""

    assert _unrendered_math_token(text) is None
    assert chr(0x221A) in text
    assert f"Sector v{manual.APP_VERSION} - user manual" in cover_text


def test_manual_part_running_headers_change_only_on_part_opening_pages():
    pdf = manual.build_manual_pdf_bytes(figures=False)
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    preflight_pdf(pdf, min_pages=6)
    validate_visible_contents_destinations(
        reader, validate_outline_destinations(reader)
    )
    parts = (
        "Part A - Get started",
        "Part B - Features & options",
        "Part C - Theory & methodology",
        "Part D - Reference",
    )
    body_pages = {}
    running_headers = []
    for page_number, page in enumerate(reader.pages, start=1):
        fragments = []

        def collect(text, _cm, tm, _font, size):
            value = " ".join(text.split())
            if value:
                fragments.append((value, float(size), float(tm[5])))

        page.extract_text(visitor_text=collect)
        running = {
            value for value, size, y in fragments
            if size == 7.5 and y > 800 and value in parts
        }
        running_headers.append(running)
        for value, size, _y in fragments:
            if value in parts and size >= 16:
                body_pages[value] = page_number

    assert tuple(body_pages) == parts
    for index, part in enumerate(parts):
        page_number = body_pages[part]
        assert running_headers[page_number - 1] == {part}
        if index:
            assert part not in running_headers[page_number - 2]


def test_accessible_html_fixture_is_self_contained_and_semantic():
    text = validate_html_content(build_fixture_html())
    assert "Standard is the default" in text
    assert (
        "Standard adds one governing worked calculation for each active check "
        "family"
    ) in text
    assert "Audit does not mean approved, compliant or certified" in text


@pytest.mark.real_image_export
@pytest.mark.xdist_group(name="publication-real-figures")
def test_issued_manual_renders_every_page_and_retains_navigation():
    pdf = build_fixture_pdf()
    validate_pdf_content(pdf)
    pages = render_pdf(pdf)
    validate_rendered_pages(pages)
    validate_crops(pages, _MANUAL_CROPS)
