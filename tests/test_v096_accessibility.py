"""PR09 HTML/PDF accessibility and clean text-layer acceptance controls."""

from __future__ import annotations

from functools import lru_cache
from html.parser import HTMLParser
import io
from pathlib import Path
import re
import sys

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import manual
from publication_items import MANUAL_FIGURE_SPECS
from tools import report_render_fixture


class _AccessibilityParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_body = False
        self.first_body_element = None
        self.main_ids = []
        self.figure_labels = []
        self.figure_texts = []
        self.math_labels = []
        self.subscripts = 0
        self.superscripts = 0
        self._figure_depth = 0
        self._figure_fragments = []

    def handle_starttag(self, tag, attrs) -> None:
        values = dict(attrs)
        if tag == "body":
            self.in_body = True
            return
        if self.in_body and self.first_body_element is None:
            self.first_body_element = (tag, values)
        if tag == "main":
            self.main_ids.append(values.get("id"))
        classes = set((values.get("class") or "").split())
        if tag == "div" and "figure-alternative" in classes:
            self.figure_labels.append(values.get("aria-label"))
            self._figure_depth = 1
            self._figure_fragments = []
        elif self._figure_depth:
            self._figure_depth += 1
        if (tag == "code" and "math" in classes) or values.get("role") == "math":
            self.math_labels.append(values.get("aria-label"))
        if tag == "sub":
            self.subscripts += 1
        elif tag == "sup":
            self.superscripts += 1

    def handle_endtag(self, tag) -> None:
        if self._figure_depth:
            self._figure_depth -= 1
            if self._figure_depth == 0:
                self.figure_texts.append(
                    re.sub(r"\s+", " ", "".join(self._figure_fragments)).strip()
                )
        if tag == "body":
            self.in_body = False

    def handle_data(self, data) -> None:
        if self._figure_depth:
            self._figure_fragments.append(data)


@lru_cache(maxsize=1)
def _html() -> str:
    return manual.build_manual_html_bytes().decode("utf-8")


@lru_cache(maxsize=1)
def _parsed() -> _AccessibilityParser:
    parser = _AccessibilityParser()
    parser.feed(_html())
    return parser


def test_skip_link_is_first_body_control_and_targets_unique_main_landmark():
    parser = _parsed()
    assert parser.first_body_element == (
        "a",
        {"class": "skip-link", "href": "#manual-main"},
    )
    assert parser.main_ids == ["manual-main"]
    assert ".skip-link:focus { transform:translateY(0); }" in _html()


def test_every_figure_has_a_distinct_governed_descriptive_alternative():
    parser = _parsed()
    expected = [spec.alternative for spec in MANUAL_FIGURE_SPECS]
    assert parser.figure_labels == expected
    assert parser.figure_texts == expected
    assert all(
        spec.alternative.strip().casefold() != spec.caption.strip().casefold()
        and len(spec.alternative.split()) >= 12
        for spec in MANUAL_FIGURE_SPECS
    )


def test_html_math_is_rendered_labelled_and_free_of_raw_tex_or_pseudo_tags():
    text = _html()
    parser = _parsed()
    assert parser.subscripts > 100
    assert parser.superscripts > 10
    assert parser.math_labels
    assert all(
        label is not None and label.startswith("Mathematical expression: ")
        for label in parser.math_labels
    )
    for token in (
        r"\frac",
        r"\tfrac",
        r"\sqrt",
        r"\varepsilon",
        r"\Delta",
        r"\sum",
        "&lt;sub&gt;",
        "&lt;super&gt;",
        "SECTOR-MATH",
    ):
        assert token not in text
    assert '<code class="math" aria-label="Mathematical expression: N^*">' in text
    assert 'aria-label="Mathematical expression: N^<em>' not in text


def _pdf_text(pdf: bytes) -> tuple[PdfReader, list[str]]:
    reader = PdfReader(io.BytesIO(pdf), strict=True)
    return reader, [page.extract_text() or "" for page in reader.pages]


def test_manual_and_every_report_profile_declare_language_and_clean_text_layers():
    artifacts = {"Manual": manual.build_manual_pdf_bytes(figures=False)}
    artifacts.update({
        profile: report_render_fixture.build_fixture_pdf(
            figures=False,
            profile=profile,
        )
        for profile in ("Brief", "Standard", "Audit")
    })
    for name, pdf in artifacts.items():
        reader, page_texts = _pdf_text(pdf)
        text = "\n".join(page_texts)
        assert reader.trailer["/Root"].get("/Lang") == "en", name
        assert "SECTOR-MATH[" not in text, name
        assert "SECTOR-SOURCE-END[" not in text, name
        if name != "Brief":
            assert "Mathematical expression:" in text, name


def test_audit_equation_identities_semantics_and_sources_remain_colocated():
    _reader, page_texts = _pdf_text(report_render_fixture.build_fixture_pdf(
        figures=False,
        profile="Audit",
    ))
    total = 0
    for page_number, text in enumerate(page_texts, start=1):
        identities = re.findall(
            r"(?m)^(?:Equation \([^\n]+\) \| )?EQ-[A-Z0-9][A-Z0-9.\-]+\s*$",
            text,
        )
        sources = re.findall(r"(?m)^Source / method note:", text)
        semantics = re.findall(r"(?m)^Mathematical expression:", text)
        assert len(identities) == len(sources), page_number
        assert len(semantics) >= len(identities), page_number
        total += len(identities)
    assert total == 88
