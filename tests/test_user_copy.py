"""Regression contracts for engineer-facing UI, manual and report copy."""

from __future__ import annotations

import io

import pypdf

from tools import audit_user_copy
from tools.manual_render_fixture import manual
from tools.report_render_fixture import build_fixture_pdf


def _inventory() -> list[dict[str, object]]:
    return audit_user_copy.build_inventory()


def test_inventory_covers_all_engineering_publication_domains() -> None:
    result = audit_user_copy.summary(_inventory())

    assert result["surfaces"] >= 3000
    assert result["domains"]["streamlit_and_helpers"] >= 2000
    assert result["domains"]["manual"] >= 450
    assert result["domains"]["report"] >= 500


def test_engineer_facing_copy_has_no_development_process_jargon() -> None:
    offenders = [
        (row["file"], row["line"], row["developer_tokens"], row["text"])
        for row in _inventory()
        if row["developer_tokens"]
    ]

    assert offenders == []


def test_generated_manual_and_report_have_no_development_process_jargon() -> None:
    artifacts = {
        "manual": manual.build_manual_pdf_bytes(figures=False),
        "report": build_fixture_pdf(figures=False),
    }
    offenders = []
    for name, pdf in artifacts.items():
        reader = pypdf.PdfReader(io.BytesIO(pdf))
        for page_number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            terms = audit_user_copy.developer_terms(text)
            if terms:
                offenders.append((name, page_number, terms))

    assert offenders == []


def test_interactive_explanations_remain_concise() -> None:
    interactive = [
        row
        for row in _inventory()
        if row["file"] not in {"app/manual.py", "app/sector_report.py"}
    ]

    assert interactive
    assert max(row["words"] for row in interactive) <= 50


def test_lexical_signals_remain_review_aids_not_automatic_defects() -> None:
    purpose = (audit_user_copy.__doc__ or "").casefold()

    assert "review aid" in purpose
    assert "not a prose-quality verdict" in purpose
    assert "fail-closed calculation reasons" in purpose
