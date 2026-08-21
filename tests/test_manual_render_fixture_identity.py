"""Browser-free identity checks for the issued manual fixture."""

from __future__ import annotations

import pytest

import tools.manual_render_fixture as manual_fixture
from sector import __version__
from tools.manual_current_program_statements import (
    CURRENT_REPORT_METADATA_WORDING,
)


def test_manual_fixture_routes_current_only_rules_to_visible_text(monkeypatch):
    calls = []

    monkeypatch.setattr(
        manual_fixture,
        "validate_current_manual_schema_statements",
        lambda text, *, project_schema: calls.append(
            ("schema statements", text, project_schema)
        ),
    )
    monkeypatch.setattr(
        manual_fixture,
        "validate_no_noncurrent_manual_schema_references",
        lambda text, *, project_schema: calls.append(
            ("schema references", text, project_schema)
        ),
    )
    monkeypatch.setattr(
        manual_fixture,
        "validate_no_noncurrent_manual_product_references",
        lambda text, *, product_version: calls.append(
            ("product references", text, product_version)
        ),
    )
    monkeypatch.setattr(
        manual_fixture,
        "validate_current_manual_program_statements",
        lambda text: calls.append(("program statements", text)),
    )

    manual_fixture._validate_current_manual_identity(
        "flat manual text",
        reference_text="line-preserving manual text",
    )

    assert calls == [
        (
            "schema statements",
            "flat manual text",
            manual_fixture.project_io.VERSION,
        ),
        (
            "schema references",
            "line-preserving manual text",
            manual_fixture.project_io.VERSION,
        ),
        (
            "product references",
            "line-preserving manual text",
            __version__,
        ),
        ("program statements", "flat manual text"),
    ]


def test_generated_html_fixture_passes_current_only_identity_checks():
    html = manual_fixture.build_fixture_html()
    text = manual_fixture.validate_html_content(html)

    assert CURRENT_REPORT_METADATA_WORDING in text
    assert "former shared crack-width" not in text


@pytest.mark.parametrize("stale_reference", ("Version: 0.93", "v0.93"))
def test_html_fixture_rejects_a_stale_visible_product_line(stale_reference):
    html = manual_fixture.build_fixture_html()
    stale_html = html.replace(
        b"</body>",
        f"<p>{stale_reference}</p></body>".encode(),
        1,
    )

    with pytest.raises(AssertionError, match="non-current Sector versions"):
        manual_fixture.validate_html_content(stale_html)


def test_html_fixture_preserves_schema_line_boundaries():
    html = manual_fixture.build_fixture_html()
    stale_html = html.replace(
        b"</body>",
        b"<p>JSON</p><p>Schema 25</p></body>",
        1,
    )

    with pytest.raises(AssertionError, match="non-current schema references"):
        manual_fixture.validate_html_content(stale_html)
