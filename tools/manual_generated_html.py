"""Extract visible text from Sector's exact generated-manual HTML envelope."""

from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser

_CURRENT_HEAD_STYLE_SHA256 = (
    "3925ff6f5ac21c001047c26a6bfd49dfe97c9d77fa9859992f05e0885a59f94a"
)
_BODY_BLOCK_TAGS = frozenset(
    {
        "aside",
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
        "tr",
        "ul",
    }
)
_BODY_INLINE_TAGS = frozenset({"a", "code", "em", "span", "strong"})
_BODY_TAGS = _BODY_BLOCK_TAGS | _BODY_INLINE_TAGS | {"br"}
_TABLE_CHILDREN = {
    "table": frozenset({"tbody", "thead"}),
    "tbody": frozenset({"tr"}),
    "thead": frozenset({"tr"}),
    "tr": frozenset({"td", "th"}),
}
_TABLE_PARENTS = {
    "tbody": frozenset({"table"}),
    "td": frozenset({"tr"}),
    "th": frozenset({"tr"}),
    "thead": frozenset({"table"}),
    "tr": frozenset({"tbody", "thead"}),
}
_VOID_TAGS = frozenset({"br", "meta"})
_VISIBILITY_ATTRIBUTES = frozenset({"aria-hidden", "hidden", "style"})
_GENERATED_ATTRIBUTES = {
    "a": frozenset({"href"}),
    "aside": frozenset({"class"}),
    "body": frozenset(),
    "br": frozenset(),
    "code": frozenset({"aria-label", "class"}),
    "dd": frozenset(),
    "details": frozenset(),
    "div": frozenset({"aria-label", "class", "role"}),
    "dl": frozenset({"class"}),
    "dt": frozenset(),
    "em": frozenset(),
    "figcaption": frozenset(),
    "figure": frozenset({"class", "id"}),
    "h1": frozenset(),
    "h2": frozenset({"id"}),
    "h3": frozenset({"id"}),
    "h4": frozenset({"id"}),
    "h5": frozenset({"id"}),
    "head": frozenset(),
    "header": frozenset(),
    "html": frozenset({"lang"}),
    "li": frozenset({"class"}),
    "main": frozenset(),
    "meta": frozenset({"charset", "content", "name"}),
    "nav": frozenset({"aria-label"}),
    "ol": frozenset(),
    "p": frozenset({"class"}),
    "section": frozenset({"class", "id"}),
    "span": frozenset({"class"}),
    "strong": frozenset(),
    "style": frozenset(),
    "summary": frozenset(),
    "table": frozenset(),
    "tbody": frozenset(),
    "td": frozenset(),
    "th": frozenset({"scope"}),
    "thead": frozenset(),
    "title": frozenset(),
    "tr": frozenset(),
    "ul": frozenset(),
}
_GENERATED_CLASS_TOKENS = frozenset(
    {
        "callout",
        "concept",
        "document-control",
        "equation",
        "equation-heading",
        "equation-results",
        "equation-text",
        "equation-uses",
        "figure-alternative",
        "limit",
        "math",
        "source",
        "sr-only",
        "standard",
        "table-figure",
        "table-scroll",
        "tip",
        "toc-level-0",
        "toc-level-1",
        "toc-level-2",
    }
)
_GENERATED_META_NAMES = frozenset(
    {
        "author",
        "description",
        "keywords",
        "sector-source-revision",
        "sector-version",
        "viewport",
    }
)
_NONVISUAL_CLASS = "sr-only"
_N_STAR_CODE_START = '<code class="math" aria-label="mathematical expression N^<em>">'
_HTML_ASCII_WHITESPACE = "\t\n\f\r "
_ASCII_CLASS_SPACE_RE = re.compile(r"[\t\n\f\r ]+")
_FRAGMENT_HREF_RE = re.compile(r"#[A-Za-z0-9_-]+")
_STRUCTURE_ERROR = "issued manual HTML is outside its generated envelope"


class _GeneratedManualHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, bool, int]] = []
        self.fragments: list[str | None] = []
        self.style_fragments: list[str] = []
        self.nonvisual_depth = 0
        self.doctype_seen = False
        self.html_seen = False
        self.head_seen = False
        self.head_closed = False
        self.meta_seen = False
        self.title_seen = False
        self.title_closed = False
        self.style_seen = False
        self.style_closed = False
        self.body_seen = False
        self.body_closed = False

    @property
    def current_tag(self) -> str | None:
        return self.stack[-1][0] if self.stack else None

    @property
    def in_body(self) -> bool:
        return self.body_seen and not self.body_closed

    def _append_boundary(self) -> None:
        if not self.fragments or self.fragments[-1] is not None:
            self.fragments.append(None)

    @staticmethod
    def _attribute_map(
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> dict[str, str | None]:
        names = [name.casefold() for name, _ in attrs]
        if len(names) != len(set(names)):
            raise AssertionError("issued manual HTML has duplicate attributes")
        if any(name in _VISIBILITY_ATTRIBUTES for name in names):
            raise AssertionError(
                "issued manual HTML has unsupported visibility controls"
            )
        if any(name not in _GENERATED_ATTRIBUTES[tag] for name in names):
            raise AssertionError("issued manual HTML has non-generator attributes")
        attributes = {name.casefold(): value for name, value in attrs}
        if tag == "html" and attributes != {"lang": "en"}:
            raise AssertionError("issued manual HTML has non-generator attributes")
        if tag == "meta":
            charset = attributes == {"charset": "utf-8"}
            named = (
                set(attributes) == {"content", "name"}
                and attributes["name"] in _GENERATED_META_NAMES
                and attributes["content"] is not None
            )
            if not charset and not named:
                raise AssertionError(
                    "issued manual HTML has active or non-generator metadata"
                )
        if tag == "a" and "href" in attributes:
            href = attributes["href"]
            if href is None or _FRAGMENT_HREF_RE.fullmatch(href) is None:
                raise AssertionError(
                    "issued manual HTML has an active or non-generator link"
                )
        if (
            tag == "div"
            and "role" in attributes
            and attributes["role"] not in {"img", "math"}
        ):
            raise AssertionError("issued manual HTML has non-generator attributes")
        if (
            tag == "th"
            and "scope" in attributes
            and attributes["scope"] not in {"col", "row"}
        ):
            raise AssertionError("issued manual HTML has non-generator attributes")
        return attributes

    @staticmethod
    def _class_tokens(value: str | None) -> tuple[str, ...]:
        stripped = (value or "").strip(_HTML_ASCII_WHITESPACE)
        if not stripped:
            return ()
        return tuple(_ASCII_CLASS_SPACE_RE.split(stripped))

    def handle_decl(self, decl: str) -> None:
        if self.doctype_seen or self.stack or decl.casefold() != "doctype html":
            raise AssertionError(_STRUCTURE_ERROR)
        self.doctype_seen = True

    def unknown_decl(self, data: str) -> None:
        del data
        raise AssertionError(_STRUCTURE_ERROR)

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if not self.doctype_seen or self.body_closed:
            raise AssertionError(_STRUCTURE_ERROR)
        if self.stack and self.stack[-1][2]:
            raise AssertionError(_STRUCTURE_ERROR)
        if tag not in _GENERATED_ATTRIBUTES:
            raise AssertionError("issued manual HTML contains a non-generator tag")
        attributes = self._attribute_map(tag, attrs)
        classes = self._class_tokens(attributes.get("class"))
        if "class" in attributes and (
            not classes
            or any(token not in _GENERATED_CLASS_TOKENS for token in classes)
        ):
            raise AssertionError("issued manual HTML has non-generator class tokens")
        if _NONVISUAL_CLASS in classes and tag != "span":
            raise AssertionError(
                "issued manual HTML has unsupported visibility controls"
            )

        if tag == "html":
            if self.html_seen or self.stack:
                raise AssertionError(_STRUCTURE_ERROR)
            self.html_seen = True
        elif tag == "head":
            if self.head_seen or self.current_tag != "html":
                raise AssertionError(_STRUCTURE_ERROR)
            self.head_seen = True
        elif tag == "meta":
            if self.current_tag != "head" or self.title_seen:
                raise AssertionError(_STRUCTURE_ERROR)
            self.meta_seen = True
            return
        elif tag == "title":
            if self.current_tag != "head" or self.title_seen:
                raise AssertionError(_STRUCTURE_ERROR)
            self.title_seen = True
            self._append_boundary()
        elif tag == "style":
            if self.current_tag != "head" or not self.title_closed or self.style_seen:
                raise AssertionError(_STRUCTURE_ERROR)
            self.style_seen = True
        elif tag == "body":
            if self.current_tag != "html" or not self.head_closed or self.body_seen:
                raise AssertionError(_STRUCTURE_ERROR)
            self.body_seen = True
        elif tag in _BODY_TAGS:
            if not self.in_body:
                raise AssertionError(_STRUCTURE_ERROR)
            open_body_tags = {name for name, _, _ in self.stack[2:]}
            if tag in _BODY_BLOCK_TAGS and (
                "p" in open_body_tags or open_body_tags.intersection(_BODY_INLINE_TAGS)
            ):
                raise AssertionError(_STRUCTURE_ERROR)
            if tag in _TABLE_PARENTS and self.current_tag not in _TABLE_PARENTS[tag]:
                raise AssertionError(_STRUCTURE_ERROR)
            if (
                self.current_tag in _TABLE_CHILDREN
                and tag not in _TABLE_CHILDREN[self.current_tag]
            ):
                raise AssertionError(_STRUCTURE_ERROR)
        own_nonvisual = False
        if self.in_body:
            own_nonvisual = _NONVISUAL_CLASS in classes
            if (
                self.nonvisual_depth == 0
                and not own_nonvisual
                and (tag in _BODY_BLOCK_TAGS or tag == "br")
            ):
                self._append_boundary()

        if tag in _VOID_TAGS:
            return
        n_star_artifact_state = int(self.get_starttag_text() == _N_STAR_CODE_START)
        self.stack.append((tag, own_nonvisual, n_star_artifact_state))
        if own_nonvisual:
            self.nonvisual_depth += 1

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del tag, attrs
        raise AssertionError(_STRUCTURE_ERROR)

    def handle_endtag(self, tag: str) -> None:
        if (
            self.in_body
            and tag == "em"
            and self.current_tag == "code"
            and self.stack[-1][2] == 2
            and all(open_tag != tag for open_tag, _, _ in self.stack)
        ):
            open_tag, own_nonvisual, _pending = self.stack[-1]
            self.stack[-1] = (open_tag, own_nonvisual, 3)
            return
        if not self.stack or self.current_tag != tag:
            raise AssertionError(_STRUCTURE_ERROR)
        if self.stack[-1][2] and not (tag == "code" and self.stack[-1][2] == 3):
            raise AssertionError(_STRUCTURE_ERROR)
        if self.in_body and self.nonvisual_depth == 0 and tag in _BODY_BLOCK_TAGS:
            self._append_boundary()

        _closed_tag, own_nonvisual, _artifact_pending = self.stack.pop()
        if own_nonvisual:
            self.nonvisual_depth -= 1

        if tag == "title":
            self.title_closed = True
            self._append_boundary()
        elif tag == "style":
            self.style_closed = True
        elif tag == "head":
            if not self.meta_seen or not self.title_closed or not self.style_closed:
                raise AssertionError(_STRUCTURE_ERROR)
            self.head_closed = True
        elif tag == "body":
            self.body_closed = True
        elif tag == "html" and not self.body_closed:
            raise AssertionError(_STRUCTURE_ERROR)

    def handle_data(self, data: str) -> None:
        if self.current_tag == "code" and self.stack[-1][2]:
            open_tag, own_nonvisual, artifact_state = self.stack[-1]
            if artifact_state != 1 or data != "N^":
                raise AssertionError(_STRUCTURE_ERROR)
            self.stack[-1] = (open_tag, own_nonvisual, 2)
        if self.current_tag in _TABLE_CHILDREN and data.strip(_HTML_ASCII_WHITESPACE):
            raise AssertionError(_STRUCTURE_ERROR)
        if self.current_tag == "style":
            self.style_fragments.append(data)
        elif self.current_tag == "title" or self.in_body:
            if self.nonvisual_depth == 0:
                self.fragments.append(re.sub(r"\s+", " ", data))
        elif data.strip(_HTML_ASCII_WHITESPACE):
            raise AssertionError(_STRUCTURE_ERROR)

    def handle_comment(self, data: str) -> None:
        del data
        raise AssertionError("issued manual HTML contains non-generator comments")

    def handle_pi(self, data: str) -> None:
        del data
        raise AssertionError(_STRUCTURE_ERROR)

    def visible_text(self) -> str:
        if (
            self.stack
            or self.nonvisual_depth
            or not self.doctype_seen
            or not self.html_seen
            or not self.head_seen
            or not self.head_closed
            or not self.title_seen
            or not self.title_closed
            or not self.style_seen
            or not self.style_closed
            or not self.body_seen
            or not self.body_closed
        ):
            raise AssertionError(_STRUCTURE_ERROR)

        style_text = "".join(self.style_fragments)
        style_sha256 = hashlib.sha256(style_text.encode("utf-8")).hexdigest()
        if style_sha256 != _CURRENT_HEAD_STYLE_SHA256:
            raise AssertionError(
                "issued manual HTML does not use the current generated stylesheet"
            )

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


def manual_generated_html_text(html_text: object) -> str:
    """Return line-preserving visible text from generated manual HTML."""

    if type(html_text) is not str:
        raise AssertionError("manual HTML must be built-in text")
    parser = _GeneratedManualHTMLParser()
    parser.feed(html_text)
    parser.close()
    return parser.visible_text()
