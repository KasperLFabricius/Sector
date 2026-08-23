"""PR-08 navigation, pagination and lean-composition acceptance controls."""

from __future__ import annotations

from dataclasses import fields
from functools import lru_cache
import io
import pathlib
import re
import sys

from pypdf import PdfReader

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import report_profiles  # noqa: E402
import sector_report  # noqa: E402
from tools import report_render_fixture  # noqa: E402


@lru_cache(maxsize=3)
def _profile_pdf(profile: str) -> bytes:
    return report_render_fixture.build_fixture_pdf(
        figures=False,
        profile=profile,
    )


def _page_text(page) -> str:
    return page.extract_text() or ""


def _contents_pages(reader: PdfReader):
    texts = [_page_text(page) for page in reader.pages]
    start = next(index for index, text in enumerate(texts) if text.startswith("Contents"))
    end = next(
        index for index, text in enumerate(texts[start + 1:], start + 1)
        if text.startswith("1. Results summary")
    )
    return list(reader.pages[start:end]), "\n".join(texts[start:end])


def _outline_page_ids(items) -> set[int]:
    page_ids = set()
    for item in items:
        if isinstance(item, list):
            page_ids.update(_outline_page_ids(item))
            continue
        page = getattr(item, "page", None)
        if page is not None:
            page_ids.add(page.idnum)
    return page_ids


def _outline_titles(items) -> list[str]:
    titles = []
    for item in items:
        if isinstance(item, list):
            titles.extend(_outline_titles(item))
            continue
        titles.append(str(getattr(item, "title", item)))
    return titles


def test_every_profile_has_linked_contents_with_matching_outline_destinations():
    link_counts = {}
    for profile in ("Brief", "Standard", "Audit"):
        reader = PdfReader(io.BytesIO(_profile_pdf(profile)))
        pages, text = _contents_pages(reader)
        assert "1. Results summary" in text
        assert re.search(r"Results summary\s+\.?\s*(?:\.\s*)+\d+", text)

        annotations = [
            annotation.get_object()
            for page in pages
            for annotation in page.get("/Annots", ())
            if annotation.get_object().get("/Subtype") == "/Link"
        ]
        destinations = {
            annotation["/Dest"][0].idnum
            for annotation in annotations
            if annotation.get("/Dest")
        }
        assert destinations
        assert destinations <= _outline_page_ids(reader.outline)
        link_counts[profile] = len(annotations)

        if profile == "Brief":
            assert "2. Analysis input summary" in text
            assert "Geometry and reinforcement" not in text
        elif profile == "Standard":
            assert "2. Conventions and units" in text
            assert "Geometry\n" not in text
        else:
            assert "1.1 Results overview" in text
            assert re.search(r"\d+\.\d+ Geometry", text)
            outline_titles = _outline_titles(reader.outline)
            assert "1.1 Results overview" in outline_titles
            assert "Results overview" not in outline_titles

    assert link_counts["Audit"] > link_counts["Standard"]
    assert link_counts["Standard"] > link_counts["Brief"]


def test_toc_multibuild_writes_one_strictly_parseable_pdf_container_per_profile():
    for profile in ("Brief", "Standard", "Audit"):
        pdf = _profile_pdf(profile)
        assert pdf.count(b"%PDF-") == 1
        assert pdf.count(b"%%EOF") == 1
        reader = PdfReader(io.BytesIO(pdf), strict=True)
        assert len(reader.pages) > 0


def test_profiles_have_no_arbitrary_page_count_policy_fields():
    names = {field.name for field in fields(report_profiles.ReportProfilePolicy)}
    assert not any("page_limit" in name for name in names)
    assert not any("page_target" in name for name in names)
    assert not any("target_exception" in name for name in names)


def test_rendered_report_captions_are_compact_and_not_self_referential():
    for profile in ("Brief", "Standard", "Audit"):
        reader = PdfReader(io.BytesIO(_profile_pdf(profile)))
        text = "\n".join(_page_text(page) for page in reader.pages)
        assert "See Table " not in text
        assert "See Figure " not in text
        assert "Reported information for" not in text
        assert "Table 0.1. Document control: Field" in text


def test_results_overview_group_label_cannot_split_from_first_child(monkeypatch):
    rows = [
        {
            "family": "plastic_bending",
            "check": f"Check {index}",
            "case": f"PL-{index}",
            "status": "PASS",
            "result": "50.0 %",
            "criterion": "<= 100 %",
            "util": 0.5,
        }
        for index in range(4)
    ]
    rows.extend({
        "family": "elastic_stress",
        "check": f"Output {index}",
        "case": f"EL-{index}",
        "status": "CALCULATED",
        "result": "10.0 MPa",
        "criterion": "Output only",
        "util": None,
    } for index in range(4))
    monkeypatch.setattr(
        sector_report.presentation,
        "multi_case_summary_rows",
        lambda _inp, _out: rows,
    )

    builder = sector_report.ReportBuilder(
        io.BytesIO(), {}, {}, {}, figures=False, profile="Standard"
    )
    builder._results_overview()
    table = next(
        item for item in builder.flow
        if getattr(item, "_sector_results_overview", False)
    )
    groups = {
        cell.getPlainText(): index
        for index, row in enumerate(table._cellvalues)
        for cell in row[:1]
        if hasattr(cell, "getPlainText")
        and cell.getPlainText() in {"Checks and comparisons", "Calculated outputs"}
    }
    protected = {
        (start[1], end[1])
        for _command, start, end in table._nosplitCmds
    }
    assert protected == {
        (groups["Checks and comparisons"], groups["Checks and comparisons"] + 1),
        (groups["Calculated outputs"], groups["Calculated outputs"] + 1),
    }


def test_pr08_acceptance_document_freezes_exact_base_and_scope():
    text = (ROOT / "docs" / "pr08_v096_publication_composition_acceptance.md").read_text(
        encoding="utf-8"
    )
    for token in (
        "42a6b100af81946595850dcb0cb069d7b335be0c",
        "4dc503c7a62becd7f674cd63185071263dc95495",
        "D096-017",
        "F096-012",
        "Product version remains `0.95`",
        "project schema remains `27`",
        "complete effective inputs",
    ):
        assert token in text
