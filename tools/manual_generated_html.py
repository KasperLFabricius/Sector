"""Extract visible text from Sector's exact generated-manual HTML envelope."""

from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser

from tools.manual_generated_html_vocabulary import (
    CURRENT_GENERATED_MANUAL_HTML_VOCABULARY,
)

_VOCABULARY = CURRENT_GENERATED_MANUAL_HTML_VOCABULARY
_BODY_BLOCK_TAGS = _VOCABULARY.body_block_tags
_BODY_INLINE_TAGS = _VOCABULARY.body_inline_tags
_BODY_TAGS = _BODY_BLOCK_TAGS | _BODY_INLINE_TAGS | _VOCABULARY.body_void_tags
_TABLE_CHILDREN = dict(_VOCABULARY.table_children)
_TABLE_PARENTS = {
    child: frozenset(
        parent for parent, children in _VOCABULARY.table_children if child in children
    )
    for child in frozenset().union(*_TABLE_CHILDREN.values())
}
_VOID_TAGS = _VOCABULARY.body_void_tags | _VOCABULARY.head_void_tags
_VISIBILITY_ATTRIBUTES = frozenset({"aria-hidden", "hidden", "style"})
_GENERATED_ATTRIBUTES = dict(_VOCABULARY.attribute_names_by_tag)
_GENERATED_CLASS_TOKENS = dict(_VOCABULARY.class_tokens_by_tag)
_GENERATED_META_NAMES = _VOCABULARY.meta_names
_HTML_ASCII_WHITESPACE = _VOCABULARY.html_ascii_whitespace
_ASCII_CLASS_SPACE_RE = re.compile(f"[{re.escape(_HTML_ASCII_WHITESPACE)}]+")
_FRAGMENT_HREF_RE = re.compile(_VOCABULARY.fragment_href_pattern)
_STRUCTURE_ERROR = "issued manual HTML is outside its generated envelope"


class _GeneratedManualHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.fragments: list[str | None] = []
        self.style_fragments: list[str] = []
        self.table_section_states: list[int] = []
        self.doctype_seen = False
        self.html_seen = False
        self.head_seen = False
        self.head_closed = False
        self.charset_seen = False
        self.title_seen = False
        self.title_closed = False
        self.style_seen = False
        self.style_closed = False
        self.body_seen = False
        self.body_closed = False

    @property
    def current_tag(self) -> str | None:
        return self.stack[-1] if self.stack else None

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
        if tag == "html" and attributes != {"lang": _VOCABULARY.html_language}:
            raise AssertionError("issued manual HTML has non-generator attributes")
        if tag == "meta":
            charset = attributes == {"charset": _VOCABULARY.html_charset}
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
        if tag == "code" and attributes.get("class") == "math":
            label = attributes.get("aria-label") or ""
            if (
                not label.startswith("Mathematical expression: ")
                or not label.removeprefix("Mathematical expression: ").strip()
                or re.search(r"</?[A-Za-z][^>]*>", label)
            ):
                raise AssertionError(
                    "issued manual HTML has an incomplete mathematical label"
                )
        if (
            tag == "div"
            and "role" in attributes
            and attributes["role"] not in _VOCABULARY.div_roles
        ):
            raise AssertionError("issued manual HTML has non-generator attributes")
        if tag == "div" and attributes.get("role") in {"img", "math"}:
            label = attributes.get("aria-label") or ""
            if not label.strip() or re.search(r"</?[A-Za-z][^>]*>", label):
                raise AssertionError(
                    "issued manual HTML has an incomplete accessible label"
                )
            if (
                attributes["role"] == "math"
                and (
                    not label.startswith("Mathematical expression: ")
                    or not label.removeprefix(
                        "Mathematical expression: "
                    ).strip()
                )
            ):
                raise AssertionError(
                    "issued manual HTML has an incomplete mathematical label"
                )
        if (
            tag == "th"
            and "scope" in attributes
            and attributes["scope"] not in _VOCABULARY.th_scopes
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
        if self.doctype_seen or self.stack or decl.casefold() != _VOCABULARY.doctype:
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
        if tag not in _GENERATED_ATTRIBUTES:
            raise AssertionError("issued manual HTML contains a non-generator tag")
        attributes = self._attribute_map(tag, attrs)
        classes = self._class_tokens(attributes.get("class"))
        generated_class_tokens = _GENERATED_CLASS_TOKENS.get(tag, frozenset())
        if "class" in attributes and (
            not classes or any(token not in generated_class_tokens for token in classes)
        ):
            raise AssertionError("issued manual HTML has non-generator class tokens")
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
            if "charset" in attributes:
                if self.charset_seen:
                    raise AssertionError(_STRUCTURE_ERROR)
                self.charset_seen = True
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
            open_body_tags = set(self.stack[2:])
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
            if tag == "table":
                self.table_section_states.append(0)
            elif tag == "thead":
                if not self.table_section_states or self.table_section_states[-1] != 0:
                    raise AssertionError(_STRUCTURE_ERROR)
                self.table_section_states[-1] = 1
            elif tag == "tbody":
                if not self.table_section_states or self.table_section_states[-1] != 1:
                    raise AssertionError(_STRUCTURE_ERROR)
                self.table_section_states[-1] = 2
        if self.in_body:
            if (
                tag in _BODY_BLOCK_TAGS or tag == "br"
            ):
                self._append_boundary()

        if tag in _VOID_TAGS:
            return
        self.stack.append(tag)

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del tag, attrs
        raise AssertionError(_STRUCTURE_ERROR)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.current_tag != tag:
            raise AssertionError(_STRUCTURE_ERROR)
        if tag == "table":
            if not self.table_section_states or self.table_section_states[-1] != 2:
                raise AssertionError(_STRUCTURE_ERROR)
            self.table_section_states.pop()
        if self.in_body and tag in _BODY_BLOCK_TAGS:
            self._append_boundary()

        self.stack.pop()

        if tag == "title":
            self.title_closed = True
            self._append_boundary()
        elif tag == "style":
            self.style_closed = True
        elif tag == "head":
            if not self.charset_seen or not self.title_closed or not self.style_closed:
                raise AssertionError(_STRUCTURE_ERROR)
            self.head_closed = True
        elif tag == "body":
            self.body_closed = True
        elif tag == "html" and not self.body_closed:
            raise AssertionError(_STRUCTURE_ERROR)

    def handle_data(self, data: str) -> None:
        if self.current_tag in _TABLE_CHILDREN and data.strip(_HTML_ASCII_WHITESPACE):
            raise AssertionError(_STRUCTURE_ERROR)
        if self.current_tag == "style":
            self.style_fragments.append(data)
        elif self.current_tag == "title" or self.in_body:
            self.fragments.append(_ASCII_CLASS_SPACE_RE.sub(" ", data))
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
            or self.table_section_states
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
        if style_sha256 != _VOCABULARY.current_head_style_sha256:
            raise AssertionError(
                "issued manual HTML does not use the current generated stylesheet"
            )

        lines: list[str] = []
        current_line: list[str] = []

        def flush_line() -> None:
            normalized = _ASCII_CLASS_SPACE_RE.sub(" ", "".join(current_line)).strip(
                " "
            )
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
