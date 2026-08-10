"""Browser-free accessibility contracts for the HTML manual companion."""

from __future__ import annotations

from functools import lru_cache
from html.parser import HTMLParser
import io

from pypdf import PdfReader

from app import manual_information_architecture as manual_ia
from manual_equation_publication import EQUATION_BLOCK, manual_publication_blocks
from publication_items import publish_manual_blocks

import manual


class _ManualHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []
        self.hrefs: list[str] = []
        self.scripts = 0
        self.external_resources: list[tuple[str, str]] = []
        self.heading_levels: list[int] = []
        self.tables = 0
        self.table_header_scopes: list[str | None] = []
        self.figure_alternatives = 0
        self.figcaptions = 0
        self.equations = 0
        self.lang: str | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        values = dict(attrs)
        if "id" in values:
            self.ids.append(values["id"])
        if tag == "html":
            self.lang = values.get("lang")
        if tag == "a" and values.get("href"):
            self.hrefs.append(values["href"])
        if tag == "script":
            self.scripts += 1
        if tag in {"img", "script", "iframe", "link"}:
            target = values.get("src") or values.get("href")
            if target:
                self.external_resources.append((tag, target))
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.heading_levels.append(int(tag[1]))
        if tag == "table":
            self.tables += 1
        if tag == "th":
            self.table_header_scopes.append(values.get("scope"))
        if tag == "div" and "figure-alternative" in values.get("class", ""):
            assert values.get("role") == "img"
            assert values.get("aria-label")
            self.figure_alternatives += 1
        if tag == "figcaption":
            self.figcaptions += 1
        if tag == "section" and "equation" in values.get("class", ""):
            self.equations += 1


@lru_cache(maxsize=1)
def _html() -> str:
    return manual.build_manual_html_bytes().decode("utf-8")


@lru_cache(maxsize=1)
def _pdf() -> bytes:
    return manual.build_manual_pdf_bytes(figures=False)


def _parsed() -> _ManualHTMLParser:
    parser = _ManualHTMLParser()
    parser.feed(_html())
    return parser


def test_html_manual_is_self_contained_javascript_free_and_identified():
    text = _html()
    parser = _parsed()
    assert text.startswith("<!doctype html>")
    assert parser.lang == "en"
    assert parser.scripts == 0
    assert parser.external_resources == []
    assert "Sector user manual v" in text
    assert 'name="sector-version"' in text
    assert 'name="sector-source-revision"' in text
    assert 'name="author"' in text
    assert "Source revision:" in text


def test_every_internal_link_resolves_to_one_unique_destination():
    parser = _parsed()
    assert len(parser.ids) == len(set(parser.ids))
    internal = [href[1:] for href in parser.hrefs if href.startswith("#")]
    assert internal
    assert set(internal) <= set(parser.ids)
    assert not [href for href in parser.hrefs if not href.startswith("#")]


def test_heading_hierarchy_does_not_skip_levels():
    levels = _parsed().heading_levels
    assert levels[0] == 1
    assert all(current <= previous + 1 for previous, current in zip(levels, levels[1:]))


def test_tables_figures_and_equations_have_semantic_alternatives():
    parser = _parsed()
    published = publish_manual_blocks(
        manual_publication_blocks(manual.manual_blocks())
    )
    authored_tables = sum(item.block[0] == "table" for item in published)
    authored_figures = sum(item.block[0] == "figure" for item in published)
    authored_equations = sum(item.block[0] == EQUATION_BLOCK for item in published)

    # Equation symbol tables add one semantic table per governed equation.
    assert parser.tables == authored_tables + authored_equations
    assert parser.table_header_scopes
    assert set(parser.table_header_scopes) == {"col", "row"}
    assert parser.figure_alternatives == authored_figures
    assert parser.figcaptions >= authored_figures + authored_tables
    assert parser.equations == authored_equations
    assert _html().count('<span class="sr-only">Mathematical expression:') == (
        authored_equations
    )


def test_html_and_pdf_share_registered_reading_path_destinations():
    text = _html()
    for anchor in (
        "manual-start-here",
        "manual-quick-calculation",
        "manual-input-reference",
        "manual-method-reference",
        "manual-limitations-troubleshooting",
    ):
        assert f'id="{anchor}"' in text
        assert f'href="#{anchor}"' in text


def _outline_titles(items) -> list[str]:
    titles = []
    for item in items:
        if isinstance(item, list):
            titles.extend(_outline_titles(item))
        else:
            titles.append(str(getattr(item, "title", "")))
    return titles


def test_pdf_declares_document_control_language_and_detailed_navigation():
    reader = PdfReader(io.BytesIO(_pdf()))
    metadata = reader.metadata
    assert metadata.title == f"Sector user manual v{manual.APP_VERSION}"
    assert metadata.author == manual.APP_AUTHOR
    assert "input reference" in metadata.subject.lower()
    assert "structural engineering" in metadata.get("/Keywords", "").lower()
    assert reader.trailer["/Root"].get("/Lang") == "en"

    titles = set(_outline_titles(reader.outline))
    assert set(manual._PART_SUMMARIES) <= titles
    assert {item.heading for item in manual_ia.INPUT_STAGES} <= titles
    assert {item.heading for item in manual_ia.RESULT_VIEWS} <= titles
    assert {item.heading for item in manual_ia.METHODS} <= titles

    first_page = " ".join((reader.pages[0].extract_text() or "").split())
    assert f"Version {manual.APP_VERSION}" in first_page
    assert f"Source revision: {manual.source_revision()}" in first_page
    for page in reader.pages:
        text = " ".join((page.extract_text() or "").split())
        assert f"Sector v{manual.APP_VERSION} - user manual" in text
        assert "Rev:" in text
