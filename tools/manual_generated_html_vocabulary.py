"""Immutable vocabulary emitted by Sector's generated-manual HTML renderer."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GeneratedManualHTMLVocabulary:
    """Describe generator-owned HTML tokens without validating a document."""

    current_head_style_sha256: str
    body_block_tags: frozenset[str]
    body_inline_tags: frozenset[str]
    body_void_tags: frozenset[str]
    head_void_tags: frozenset[str]
    table_children: tuple[tuple[str, frozenset[str]], ...]
    attribute_names_by_tag: tuple[tuple[str, frozenset[str]], ...]
    class_tokens_by_tag: tuple[tuple[str, frozenset[str]], ...]
    meta_names: frozenset[str]
    div_roles: frozenset[str]
    th_scopes: frozenset[str]
    doctype: str
    html_language: str
    html_charset: str
    nonvisual_class_token: str
    n_star_code_start: str
    html_ascii_whitespace: str
    fragment_href_pattern: str


CURRENT_GENERATED_MANUAL_HTML_VOCABULARY = GeneratedManualHTMLVocabulary(
    current_head_style_sha256=(
        "3925ff6f5ac21c001047c26a6bfd49dfe97c9d77fa9859992f05e0885a59f94a"
    ),
    body_block_tags=frozenset(
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
    ),
    body_inline_tags=frozenset({"a", "code", "em", "span", "strong"}),
    body_void_tags=frozenset({"br"}),
    head_void_tags=frozenset({"meta"}),
    table_children=(
        ("table", frozenset({"tbody", "thead"})),
        ("tbody", frozenset({"tr"})),
        ("thead", frozenset({"tr"})),
        ("tr", frozenset({"td", "th"})),
    ),
    attribute_names_by_tag=(
        ("a", frozenset({"href"})),
        ("aside", frozenset({"class"})),
        ("body", frozenset()),
        ("br", frozenset()),
        ("code", frozenset({"aria-label", "class"})),
        ("dd", frozenset()),
        ("details", frozenset()),
        ("div", frozenset({"aria-label", "class", "role"})),
        ("dl", frozenset({"class"})),
        ("dt", frozenset()),
        ("em", frozenset()),
        ("figcaption", frozenset()),
        ("figure", frozenset({"class", "id"})),
        ("h1", frozenset()),
        ("h2", frozenset({"id"})),
        ("h3", frozenset({"id"})),
        ("h4", frozenset({"id"})),
        ("h5", frozenset({"id"})),
        ("head", frozenset()),
        ("header", frozenset()),
        ("html", frozenset({"lang"})),
        ("li", frozenset({"class"})),
        ("main", frozenset()),
        ("meta", frozenset({"charset", "content", "name"})),
        ("nav", frozenset({"aria-label"})),
        ("ol", frozenset()),
        ("p", frozenset({"class"})),
        ("section", frozenset({"class", "id"})),
        ("span", frozenset({"class"})),
        ("strong", frozenset()),
        ("style", frozenset()),
        ("summary", frozenset()),
        ("table", frozenset()),
        ("tbody", frozenset()),
        ("td", frozenset()),
        ("th", frozenset({"scope"})),
        ("thead", frozenset()),
        ("title", frozenset()),
        ("tr", frozenset()),
        ("ul", frozenset()),
    ),
    class_tokens_by_tag=(
        (
            "aside",
            frozenset({"callout", "concept", "limit", "standard", "theory", "tip"}),
        ),
        ("code", frozenset({"math"})),
        ("div", frozenset({"display-math", "figure-alternative", "table-scroll"})),
        ("dl", frozenset({"equation-results"})),
        ("figure", frozenset({"table-figure"})),
        ("li", frozenset({"toc-level-0", "toc-level-1", "toc-level-2"})),
        (
            "p",
            frozenset(
                {
                    "document-control",
                    "equation-heading",
                    "equation-text",
                    "equation-uses",
                    "source",
                }
            ),
        ),
        ("section", frozenset({"equation"})),
        ("span", frozenset({"sr-only"})),
    ),
    meta_names=frozenset(
        {
            "author",
            "description",
            "keywords",
            "sector-source-revision",
            "sector-version",
            "viewport",
        }
    ),
    div_roles=frozenset({"img", "math"}),
    th_scopes=frozenset({"col", "row"}),
    doctype="doctype html",
    html_language="en",
    html_charset="utf-8",
    nonvisual_class_token="sr-only",
    n_star_code_start=(
        '<code class="math" aria-label="mathematical expression N^<em>">'
    ),
    html_ascii_whitespace="\t\n\f\r ",
    fragment_href_pattern=r"#[A-Za-z0-9_-]+",
)
