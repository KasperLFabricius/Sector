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


def test_routing_registries_do_not_concatenate_independent_messages() -> None:
    rows = audit_user_copy.inventory_file(
        audit_user_copy.ROOT / "app" / "result_presentation.py"
    )
    surfaces = {str(row["surface"]) for row in rows}

    assert not any(
        surface.startswith("registry__result_reason_messages[")
        for surface in surfaces
    )
    assert any(
        surface.startswith("registry__plastic_reason_messages[")
        for surface in surfaces
    )


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
    def is_document_copy(row):
        if row["file"] in {
            "app/manual.py", "app/manual_numerics.py", "app/manual_walkthroughs.py",
            "app/sector_report.py",
        }:
            return True
        # WORKFLOWS are expanded into numbered manual procedures. The same
        # module's warning, stage and result-view copy remains interactive.
        if row["file"] == "app/manual_information_architecture.py":
            return str(row["surface"]).startswith("workflow_")
        # These governed figure texts appear in the manual exports/viewer.
        return row["file"] == "app/publication_items.py" and row["surface"] in {
            "caption", "alternative",
        }

    inventory = _inventory()
    interactive = [
        row
        for row in inventory
        if not is_document_copy(row)
    ]

    assert interactive
    assert any(row["file"] == "app/sector_app.py" for row in interactive)
    assert any(row["file"] == "app/manual_information_architecture.py"
               and str(row["surface"]).startswith("warningreference_")
               for row in interactive)
    assert [(row["file"], row["line"], row["surface"], row["words"])
            for row in interactive if row["words"] > 50] == []

    # Document text remains in the complete jargon inventory above. The manual
    # numerical, workflow and figure contract suites also check its content.
    document_files = {row["file"] for row in inventory if is_document_copy(row)}
    assert {
        "app/manual_numerics.py", "app/manual_information_architecture.py",
        "app/publication_items.py",
    } <= document_files


def test_lexical_signals_remain_review_aids_not_automatic_defects() -> None:
    purpose = (audit_user_copy.__doc__ or "").casefold()

    assert "review aid" in purpose
    assert "not a prose-quality verdict" in purpose
    assert "fail-closed calculation reasons" in purpose
