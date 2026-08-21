"""Extract semantic text from Sector's generator-owned HTML manual."""

from __future__ import annotations

import re
from html.parser import HTMLParser

_BLOCK_TAGS = frozenset(
    {
        "aside",
        "body",
        "br",
        "dd",
        "details",
        "div",
        "dl",
        "dt",
        "figcaption",
        "figure",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "header",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "section",
        "summary",
        "table",
        "tbody",
        "td",
        "th",
        "thead",
        "title",
        "tr",
        "ul",
    }
)
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
        "source",
        "track",
        "wbr",
    }
)
_VISIBILITY_ATTRIBUTES = frozenset({"aria-hidden", "hidden", "style"})
_STRUCTURE_ERROR = "issued manual HTML lacks its explicit title/body structure"


class _ManualSemanticHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_html = False
        self.in_head = False
        self.in_head_style = False
        self.in_body = False
        self.in_title = False
        self.html_seen = False
        self.html_closed = False
        self.head_seen = False
        self.head_closed = False
        self.head_style_seen = False
        self.head_style_closed = False
        self.body_seen = False
        self.body_closed = False
        self.title_seen = False
        self.title_closed = False
        self.fragments: list[str | None] = []

    @property
    def in_semantic_document(self) -> bool:
        return self.in_body or self.in_title

    def _append_boundary(self) -> None:
        if not self.fragments or self.fragments[-1] is not None:
            self.fragments.append(None)

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if self.body_closed or self.html_closed:
            raise AssertionError(_STRUCTURE_ERROR)
        if tag in {"script", "template"}:
            raise AssertionError(
                "issued manual HTML contains non-semantic content"
            )
        if any(
            name.casefold() in _VISIBILITY_ATTRIBUTES for name, _ in attrs
        ):
            raise AssertionError(
                "issued manual HTML contains hidden semantic content"
            )

        if tag == "html":
            if self.html_seen:
                raise AssertionError(_STRUCTURE_ERROR)
            self.html_seen = True
            self.in_html = True
            return
        if not self.in_html:
            raise AssertionError(_STRUCTURE_ERROR)
        if tag == "head":
            if self.head_seen or self.body_seen:
                raise AssertionError(_STRUCTURE_ERROR)
            self.head_seen = True
            self.in_head = True
            return
        if tag == "title":
            if not self.in_head or self.title_seen or self.body_seen:
                raise AssertionError(_STRUCTURE_ERROR)
            self.title_seen = True
            self.in_title = True
        elif tag == "style":
            if (
                not self.in_head
                or self.in_title
                or self.head_style_seen
                or self.body_seen
            ):
                raise AssertionError(
                    "issued manual HTML contains non-semantic content"
                )
            self.head_style_seen = True
            self.in_head_style = True
        elif tag == "meta":
            if not self.in_head or self.in_title or self.in_head_style:
                raise AssertionError(_STRUCTURE_ERROR)
        if tag == "body":
            if (
                self.body_seen
                or self.in_title
                or self.in_head_style
                or not self.head_closed
                or not self.title_closed
            ):
                raise AssertionError(_STRUCTURE_ERROR)
            self.body_seen = True
            self.in_body = True
        elif not self.in_body and tag not in {"meta", "style", "title"}:
            raise AssertionError(_STRUCTURE_ERROR)

        if self.in_semantic_document and tag in _BLOCK_TAGS:
            self._append_boundary()

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag not in _VOID_TAGS:
            raise AssertionError(_STRUCTURE_ERROR)
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if self.html_closed:
            raise AssertionError(_STRUCTURE_ERROR)
        if self.in_semantic_document and tag in _BLOCK_TAGS:
            self._append_boundary()
        if tag == "title":
            if not self.in_title:
                raise AssertionError(_STRUCTURE_ERROR)
            self.in_title = False
            self.title_closed = True
        elif tag == "style":
            if not self.in_head_style:
                raise AssertionError(_STRUCTURE_ERROR)
            self.in_head_style = False
            self.head_style_closed = True
        elif tag == "head":
            if (
                not self.in_head
                or self.in_title
                or self.in_head_style
                or not self.title_closed
            ):
                raise AssertionError(_STRUCTURE_ERROR)
            self.in_head = False
            self.head_closed = True
        elif tag == "body":
            if not self.in_body:
                raise AssertionError(_STRUCTURE_ERROR)
            self.in_body = False
            self.body_closed = True
        elif tag == "html":
            if not self.in_html or not self.body_closed:
                raise AssertionError(_STRUCTURE_ERROR)
            self.in_html = False
            self.html_closed = True
        elif not self.in_body:
            raise AssertionError(_STRUCTURE_ERROR)

    def handle_data(self, data: str) -> None:
        if (
            data.strip()
            and not self.in_semantic_document
            and not self.in_head_style
        ):
            raise AssertionError(_STRUCTURE_ERROR)
        if self.in_semantic_document:
            self.fragments.append(re.sub(r"\s+", " ", data))

    def semantic_text(self) -> str:
        if (
            self.in_html
            or self.in_head
            or self.in_head_style
            or self.in_body
            or self.in_title
            or not self.html_seen
            or not self.html_closed
            or not self.head_seen
            or not self.head_closed
            or not self.head_style_seen
            or not self.head_style_closed
            or not self.body_seen
            or not self.body_closed
            or not self.title_seen
            or not self.title_closed
        ):
            raise AssertionError(_STRUCTURE_ERROR)

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


def manual_semantic_html_text(html_text: object) -> str:
    """Return line-preserving semantic text from issued manual HTML."""

    if type(html_text) is not str:
        raise AssertionError("manual HTML must be built-in text")
    parser = _ManualSemanticHTMLParser()
    parser.feed(html_text)
    parser.close()
    return parser.semantic_text()
