"""Extract line-preserving visible text from issued-manual HTML."""

from __future__ import annotations

import re
from html.parser import HTMLParser

_BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "body",
        "br",
        "caption",
        "dd",
        "details",
        "dialog",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hgroup",
        "hr",
        "li",
        "main",
        "menu",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "summary",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "title",
        "tr",
        "ul",
    }
)
_NONRENDERED_TAGS = frozenset({"script", "style", "template"})
_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)


class _VisibleManualHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_body = False
        self.in_title = False
        self.fragments: list[str | None] = []
        self.suppressed_depth = 0
        self.element_stack: list[tuple[str, bool, bool]] = []

    @property
    def in_visible_document(self) -> bool:
        return self.in_body or self.in_title

    def _append_boundary(self) -> None:
        if not self.fragments or self.fragments[-1] is not None:
            self.fragments.append(None)

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        values = dict(attrs)
        if tag == "body":
            self.in_body = True
        if tag == "title":
            self.in_title = True
        starts_suppression = tag in _NONRENDERED_TAGS or "hidden" in values
        visible_block = (
            self.in_visible_document
            and self.suppressed_depth == 0
            and not starts_suppression
            and tag in _BLOCK_TAGS
        )
        if visible_block:
            self._append_boundary()

        if tag not in _VOID_TAGS:
            self.element_stack.append(
                (tag, starts_suppression, visible_block)
            )
            if starts_suppression:
                self.suppressed_depth += 1

    def handle_endtag(self, tag: str) -> None:
        visible_block = False
        if tag not in _VOID_TAGS and self.element_stack:
            _, started_suppression, visible_block = self.element_stack.pop()
            if started_suppression:
                self.suppressed_depth -= 1
        if visible_block:
            self._append_boundary()
        if tag == "body":
            self.in_body = False
        if tag == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_visible_document and self.suppressed_depth == 0:
            self.fragments.append(re.sub(r"\s+", " ", data))

    def visible_text(self) -> str:
        lines: list[str] = []
        current_line: list[str] = []

        def flush_line() -> None:
            normalized = " ".join("".join(current_line).split())
            if normalized:
                lines.append(normalized)
            current_line.clear()

        for fragment in self.fragments:
            if fragment is None:
                flush_line()
            else:
                current_line.append(fragment)
        flush_line()
        return "\n".join(lines)


def visible_manual_html_text(html_text: object) -> str:
    """Return title and body text with rendered block boundaries retained."""

    if type(html_text) is not str:
        raise AssertionError("manual HTML must be built-in text")
    parser = _VisibleManualHTMLParser()
    parser.feed(html_text)
    parser.close()
    return parser.visible_text()
