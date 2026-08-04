"""Rendered-artifact regression tests for the issued Sector PDF."""

from __future__ import annotations

from tools.report_render_fixture import (
    _inputs,
    _results,
    build_fixture_pdf,
    render_pdf,
    validate_fixture_engineering,
    validate_pdf_content,
    validate_rendered_pages,
)
from tools.pdf_preflight import crop_difference_hash, hash_distance


def test_reference_fixture_engineering_is_internally_consistent():
    inp = _inputs()
    validate_fixture_engineering(inp, _results(inp))


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
    overview_hash = crop_difference_hash(
        pages[1], (0.08, 0.07, 0.93, 0.91)
    )
    assert hash_distance(overview_hash, "0c2c0c8e8c2c2c00") <= 2
