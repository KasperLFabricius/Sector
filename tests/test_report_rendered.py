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
from tools.pr05_dk_report_fixture import (
    build_fixture_pdf as build_pr05_fixture_pdf,
)


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


def test_pr05_split_danish_tables_keep_visible_document_control():
    """Exercise the Danish basis/evidence continuation-page transformation."""

    pages = render_pdf(build_pr05_fixture_pdf())
    validate_rendered_pages(pages, require_document_control=True)
