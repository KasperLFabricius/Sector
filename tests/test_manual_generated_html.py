"""Direct contract tests for dormant generated-manual visible text."""

from __future__ import annotations

import ast
import hashlib
import inspect
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import get_type_hints

import pytest

from sector import __version__
from tools.manual_generated_html import manual_generated_html_text
from tools.manual_generated_html_vocabulary import (
    CURRENT_GENERATED_MANUAL_HTML_VOCABULARY,
)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import manual


class _TextSubclass(str):
    pass


CURRENT_TITLE = f"Sector user manual v{__version__}"
CURRENT_STYLE_SHA256 = (
    CURRENT_GENERATED_MANUAL_HTML_VOCABULARY.current_head_style_sha256
)
GENERATED_HTML = manual.build_manual_html_bytes().decode("utf-8")
CURRENT_STYLE = GENERATED_HTML.partition("<style>")[2].partition("</style>")[0]
CLASS_TOKENS_BY_TAG = dict(CURRENT_GENERATED_MANUAL_HTML_VOCABULARY.class_tokens_by_tag)
ATTRIBUTE_NAMES_BY_TAG = dict(
    CURRENT_GENERATED_MANUAL_HTML_VOCABULARY.attribute_names_by_tag
)
ATTRIBUTE_VALUES = {
    "aria-label": "label",
    "charset": "utf-8",
    "class": "callout",
    "content": "content",
    "href": "#section",
    "id": "section",
    "lang": "en",
    "name": "description",
    "role": "img",
    "scope": "col",
}


def _document(body: str, *, title: str = CURRENT_TITLE, style: str = CURRENT_STYLE):
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        "<title>"
        + title
        + "</title><style>"
        + style
        + "</style></head><body>"
        + body
        + "</body></html>"
    )


def _dormant_generator_html(monkeypatch: pytest.MonkeyPatch) -> str:
    published = tuple(
        SimpleNamespace(block=block, item=None)
        for block in (
            ("h3", "Dormant heading"),
            ("md", "$$x+y$$"),
            ("callout", "theory", "Dormant theory callout."),
        )
    )
    monkeypatch.setattr(manual, "manual_blocks", list)
    monkeypatch.setattr(manual, "manual_publication_blocks", lambda blocks: ())
    monkeypatch.setattr(manual, "publish_manual_blocks", lambda blocks: published)
    monkeypatch.setattr(manual, "source_revision", lambda: "parser-test")
    return manual.build_manual_html_bytes().decode("utf-8")


def test_current_generated_stylesheet_has_frozen_identity():
    assert hashlib.sha256(CURRENT_STYLE.encode("utf-8")).hexdigest() == (
        CURRENT_STYLE_SHA256
    )


def test_current_generated_manual_satisfies_the_visible_text_boundary():
    text = manual_generated_html_text(GENERATED_HTML)
    lines = text.splitlines()

    assert lines[0] == CURRENT_TITLE
    assert f"Version: {__version__}" in lines
    assert "Symbols and units" in lines
    assert "Mathematical expression:" not in text


def test_dormant_generated_h5_display_math_and_theory_paths_are_supported(monkeypatch):
    generated_html = _dormant_generator_html(monkeypatch)

    assert '<h5 id="' in generated_html
    assert '<div class="display-math" role="math" aria-label="x+y">' in generated_html
    assert '<aside class="callout theory">' in generated_html
    visible_text = manual_generated_html_text(generated_html)
    assert "Dormant heading" in visible_text.splitlines()
    assert "x+y" in visible_text.splitlines()
    assert "Theory: Dormant theory callout." in visible_text.splitlines()


def test_source_wraps_collapse_while_real_blocks_retain_lines():
    html = _document(
        "<p><span>Version:</span>\n<span>0.94</span></p>"
        "<details><summary>Prelude</summary><span>Inline</span> detail</details>"
        "<p>Limitations &amp; troubleshooting</p>",
        title=f"Sector user\nmanual v{__version__}",
    )

    assert manual_generated_html_text(html) == (
        f"{CURRENT_TITLE}\n"
        "Version: 0.94\n"
        "Prelude\n"
        "Inline detail\n"
        "Limitations & troubleshooting"
    )


@pytest.mark.parametrize("separator", ("\u00a0", "\u202f"))
def test_non_html_whitespace_is_preserved_in_visible_text(separator):
    html = _document(f"<p>{separator}A{separator}B{separator}</p>")

    assert manual_generated_html_text(html).splitlines()[-1] == (
        f"{separator}A{separator}B{separator}"
    )


@pytest.mark.parametrize(
    "tag",
    (
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
        "ul",
    ),
)
def test_each_generated_non_table_container_preserves_a_line_boundary(tag):
    html = _document(f"<span>A</span><{tag}>B</{tag}><span>C</span>")

    assert manual_generated_html_text(html) == f"{CURRENT_TITLE}\nA\nB\nC"


def test_generated_table_family_preserves_boundaries_in_canonical_ancestry():
    html = _document(
        "<span>A</span><table><thead><tr><th>B</th></tr></thead>"
        "<tbody><tr><td>C</td></tr></tbody></table><span>D</span>"
    )

    assert manual_generated_html_text(html) == f"{CURRENT_TITLE}\nA\nB\nC\nD"


@pytest.mark.parametrize(
    "body",
    (
        (
            "<table><tbody><tr><td>Body</td></tr></tbody>"
            "<thead><tr><th>Head</th></tr></thead></table>"
        ),
        "<table><thead><tr><th>Head</th></tr></thead></table>",
        (
            "<table><thead><tr><th>Head</th></tr></thead>"
            "<tbody><tr><td>Body</td></tr></tbody>"
            "<tbody><tr><td>Extra</td></tr></tbody></table>"
        ),
    ),
)
def test_generated_tables_require_one_head_before_one_body(body):
    with pytest.raises(AssertionError):
        manual_generated_html_text(_document(body))


def test_html_ascii_whitespace_is_accepted_in_each_generated_table_container():
    whitespace = " \t\n\f\r"
    html = _document(
        f"<table>{whitespace}<thead>{whitespace}<tr>{whitespace}"
        f"<th>A</th></tr></thead><tbody>{whitespace}<tr>{whitespace}"
        "<td>B</td></tr></tbody></table>"
    )

    assert manual_generated_html_text(html) == f"{CURRENT_TITLE}\nA\nB"


@pytest.mark.parametrize(
    "body",
    (
        "<span>Version: </span><thead><tr><th>0.93</th></tr></thead>",
        "<span>Version: </span><tbody><tr><td>0.93</td></tr></tbody>",
        "<span>Version: </span><tr><td>0.93</td></tr>",
        "<span>Version: </span><td>0.93</td>",
        "<span>Version: </span><th>0.93</th>",
        "<span>Version: </span><table>0.93</table>",
        "<table><div>0.93</div></table>",
        "<table><tr><td>0.93</td></tr></table>",
        "<table><tbody><td>0.93</td></tbody></table>",
        "<table><thead><td>0.93</td></thead></table>",
        "<table><thead><div>0.93</div></thead></table>",
        "<table><tbody><div>0.93</div></tbody></table>",
        "<table><tbody><tr><div>0.93</div></tr></tbody></table>",
    ),
)
def test_orphan_or_foster_parented_table_content_fails_closed(body):
    with pytest.raises(AssertionError):
        manual_generated_html_text(_document(body))


@pytest.mark.parametrize("text", ("0.93", "\v", "\u00a0"))
@pytest.mark.parametrize(
    "template",
    (
        "<table>{}<thead><tr><th>A</th></tr></thead></table>",
        "<table><thead>{}<tr><th>A</th></tr></thead></table>",
        "<table><tbody>{}<tr><td>A</td></tr></tbody></table>",
        "<table><tbody><tr>{}<td>A</td></tr></tbody></table>",
    ),
)
def test_non_html_whitespace_or_text_in_each_table_container_fails_closed(
    template,
    text,
):
    with pytest.raises(AssertionError):
        manual_generated_html_text(_document(template.format(text)))


@pytest.mark.parametrize("tag", ("a", "code", "em", "span", "strong"))
def test_each_generated_inline_tag_preserves_inline_flow(tag):
    html = _document(f"<span>A</span><{tag}>B</{tag}><span>C</span>")

    assert manual_generated_html_text(html) == f"{CURRENT_TITLE}\nABC"


def test_generated_break_preserves_a_line_boundary():
    assert manual_generated_html_text(_document("A<br>B")) == (f"{CURRENT_TITLE}\nA\nB")


def test_known_nonvisual_accessibility_duplicate_is_excluded_with_descendants():
    html = _document('<p>A<span class="sr-only"><strong>Hidden</strong></span>B</p>')

    assert manual_generated_html_text(html) == f"{CURRENT_TITLE}\nAB"


@pytest.mark.parametrize("tag", ("html", "body", "p", "div"))
def test_nonvisual_class_is_allowed_only_on_its_generated_span(tag):
    if tag == "html":
        html = _document("Visible").replace(
            '<html lang="en">', '<html class="sr-only" lang="en">', 1
        )
    elif tag == "body":
        html = _document("Visible").replace("<body>", '<body class="sr-only">', 1)
    else:
        html = _document(f'<{tag} class="sr-only">Hidden</{tag}>')

    with pytest.raises(AssertionError):
        manual_generated_html_text(html)


def test_known_inline_markdown_attribute_artifact_retains_its_visible_text():
    html = _document(
        '<p><code class="math" '
        'aria-label="mathematical expression N^<em>">N^</em></code></p>'
    )

    assert manual_generated_html_text(html) == f"{CURRENT_TITLE}\nN^"


@pytest.mark.parametrize(
    "body",
    (
        "<p>A</em>B</p>",
        ('<p><code aria-label="mathematical expression N^<em>">N^</em></code></p>'),
        '<p><code class="math" aria-label="N^<em>">N^</em></code></p>',
        (
            '<p><code class="math" '
            'aria-label="mathematical expression N^<em>">X</em></code></p>'
        ),
        (
            '<p>N^<code class="math" '
            'aria-label="mathematical expression N^<em>"></em></code></p>'
        ),
        (
            '<p><code aria-label="mathematical expression N^<em>" '
            'class="math">N^</em></code></p>'
        ),
        (
            '<p><code class="math" '
            'aria-label="mathematical expression N^<em>">'
            "N^</em></em></code></p>"
        ),
        (
            '<p><code class="math" '
            'aria-label="mathematical expression N^<em>">N^</code></p>'
        ),
        (
            '<p><code class="math" '
            'aria-label="mathematical expression N^<em>">X</code></p>'
        ),
        (
            '<p><code class="math" '
            'aria-label="mathematical expression N^<em>">N^</em>X</code></p>'
        ),
        (
            '<p><code class="math" '
            'aria-label="mathematical expression N^<em>">'
            "N^<strong></strong></em></code></p>"
        ),
        (
            '<p><em><code class="math" '
            'aria-label="mathematical expression N^<em>">'
            "N^</em></code></em></p>"
        ),
        (
            '<p><code class="math" '
            'aria-label="mathematical expression N^<em>">'
            "<strong></strong>N^</em></code></p>"
        ),
        (
            '<p><code class="math" '
            'aria-label="mathematical expression N^<em>">'
            "N^</em><strong></strong></code></p>"
        ),
        (
            '<p><code class="math" '
            'aria-label="mathematical expression N^<em>"></code></p>'
        ),
    ),
)
def test_only_the_exact_generated_inline_artifact_is_tolerated(body):
    with pytest.raises(AssertionError):
        manual_generated_html_text(_document(body))


def test_non_generator_class_names_fail_closed():
    html = _document('<p class="obsolete">Old statement</p>')

    with pytest.raises(AssertionError, match="class tokens"):
        manual_generated_html_text(html)


@pytest.mark.parametrize(
    ("owner_tag", "token"),
    tuple(
        (tag, token)
        for tag, tokens in sorted(CLASS_TOKENS_BY_TAG.items())
        for token in sorted(tokens)
    ),
)
def test_each_generated_class_token_is_supported_on_its_owner(owner_tag, token):
    manual_generated_html_text(
        _document(f'<{owner_tag} class="{token}">Visible</{owner_tag}>')
    )


@pytest.mark.parametrize(
    ("owner_tag", "token", "nonowner_tag"),
    tuple(
        (owner_tag, token, nonowner_tag)
        for owner_tag, tokens in sorted(CLASS_TOKENS_BY_TAG.items())
        for token in sorted(tokens)
        for nonowner_tag, nonowner_tokens in sorted(CLASS_TOKENS_BY_TAG.items())
        if token not in nonowner_tokens
    ),
)
def test_each_generated_class_token_fails_on_every_nonowner(
    owner_tag,
    token,
    nonowner_tag,
):
    del owner_tag
    with pytest.raises(AssertionError, match="class tokens"):
        manual_generated_html_text(
            _document(f'<{nonowner_tag} class="{token}">Wrong tag</{nonowner_tag}>')
        )


@pytest.mark.parametrize("separator", (" ", "\t", "\n", "\f", "\r"))
def test_ascii_html_class_separators_split_generated_tokens(separator):
    html = _document(f'<aside class="callout{separator}theory">Visible</aside>')

    assert manual_generated_html_text(html) == f"{CURRENT_TITLE}\nVisible"


@pytest.mark.parametrize("separator", ("\v", "\u00a0", "\u2003", "\u202f"))
def test_unicode_non_html_class_separators_fail_closed(separator):
    html = _document(f'<aside class="callout{separator}theory">Visible</aside>')

    with pytest.raises(AssertionError, match="class tokens"):
        manual_generated_html_text(html)


@pytest.mark.parametrize(
    "mutated_style",
    (
        CURRENT_STYLE + "\n.document-control { display:none; }",
        CURRENT_STYLE.replace(".sr-only", ".screen-reader-only", 1),
        CURRENT_STYLE.replace("overflow:hidden", "overflow:visible", 1),
    ),
)
def test_any_stylesheet_change_fails_closed(mutated_style):
    html = _document(
        '<p class="document-control">Old statement</p>',
        style=mutated_style,
    )

    with pytest.raises(AssertionError, match="current generated stylesheet"):
        manual_generated_html_text(html)


@pytest.mark.parametrize(
    "attribute",
    (
        "hidden",
        'aria-hidden="true"',
        'aria-hidden="false"',
        'style="display:none"',
        'style="display:block"',
    ),
)
def test_visibility_attributes_fail_closed_on_root_or_body(attribute):
    for html in (
        _document("<p>Hidden</p>").replace("<html ", f"<html {attribute} ", 1),
        _document(f"<p {attribute}>Hidden</p>"),
    ):
        with pytest.raises(AssertionError, match="visibility controls"):
            manual_generated_html_text(html)


@pytest.mark.parametrize(
    "mutator",
    (
        lambda html: html.replace("<style>", '<style media="not all">', 1),
        lambda html: html.replace(
            '<meta charset="utf-8">',
            (
                '<meta charset="utf-8"><meta '
                'http-equiv="Content-Security-Policy" '
                "content=\"style-src 'none'\">"
            ),
            1,
        ),
        lambda html: html.replace("<body>", '<body onload="alert(1)">', 1),
        lambda html: html.replace("<p>", '<p onclick="alert(1)">', 1),
        lambda html: html.replace("<p>", "<p popover>", 1),
    ),
)
def test_active_or_non_generator_attributes_fail_closed(mutator):
    with pytest.raises(AssertionError, match="attributes"):
        manual_generated_html_text(mutator(_document("<p>Current</p>")))


@pytest.mark.parametrize(
    ("owner_tag", "attribute", "nonowner_tag"),
    tuple(
        (owner_tag, attribute, nonowner_tag)
        for owner_tag, attributes in sorted(ATTRIBUTE_NAMES_BY_TAG.items())
        for attribute in sorted(attributes)
        for nonowner_tag, nonowner_attributes in sorted(ATTRIBUTE_NAMES_BY_TAG.items())
        if attribute not in nonowner_attributes
    ),
)
def test_each_generated_attribute_fails_on_every_nonowner(
    owner_tag,
    attribute,
    nonowner_tag,
):
    del owner_tag
    value = ATTRIBUTE_VALUES[attribute]
    body = f'<{nonowner_tag} {attribute}="{value}">Wrong tag</{nonowner_tag}>'

    with pytest.raises(AssertionError, match="attributes"):
        manual_generated_html_text(_document(body))


@pytest.mark.parametrize(
    "href",
    (
        "javascript:alert(1)",
        "data:text/html,stale",
        "https://example.invalid/stale",
        "#ok onclick=alert(1)",
    ),
)
def test_active_or_non_generator_links_fail_closed(href):
    html = _document(f'<p><a href="{href}">Current</a></p>')

    with pytest.raises(AssertionError, match="link"):
        manual_generated_html_text(html)


def test_generated_fragment_link_remains_visible():
    html = _document('<p><a href="#manual-section-1">Current</a></p>')

    assert manual_generated_html_text(html) == f"{CURRENT_TITLE}\nCurrent"


@pytest.mark.parametrize("tag", ("h6", "script", "template", "video"))
def test_non_generator_tags_fail_closed(tag):
    with pytest.raises(AssertionError, match="non-generator tag"):
        manual_generated_html_text(_document(f"<{tag}>Text</{tag}>"))


@pytest.mark.parametrize(
    "body",
    (
        "<ul><li>A<li>B</li></ul>",
        "<p><strong>A</p></strong>",
        "<p>A<p>B</p></p>",
        "A<br/>B",
        "A<p/>B",
        '<p class="a" class="b">B</p>',
    ),
)
def test_optional_mismatched_self_closing_or_duplicate_markup_fails_closed(body):
    with pytest.raises(AssertionError):
        manual_generated_html_text(_document(body))


@pytest.mark.parametrize(
    "html",
    (
        (
            "<html><head><meta charset=utf-8><title>T</title><style>x</style>"
            "</head><body>B</body></html>"
        ),
        (
            "<!doctype html><html><head><title>T</title><style>x</style>"
            "</head><body>B</body></html>"
        ),
        (
            "<!doctype html><html><head><meta charset=utf-8><style>x</style>"
            "</head><body>B</body></html>"
        ),
        (
            "<!doctype html><html><head><meta charset=utf-8><title>T</title>"
            "</head><body>B</body></html>"
        ),
        (
            "<!doctype html><html><head><meta charset=utf-8><title>T</title>"
            "<style>x</style></head></html>"
        ),
        (
            "<!doctype html><html><head><meta charset=utf-8><title>T</title>"
            "<style>x</style></head><p>Before body</p><body>B</body></html>"
        ),
        _document("B") + "Trailing",
        _document("B").replace("<title>", "<title>T</title><title>", 1),
        _document("B").replace("<body>", "<body><body>", 1),
        _document("<p>B</p>").replace("<p", "<!-- note --><p", 1),
        _document("<p>A<?stale?>B</p>"),
        _document("B").replace("<!doctype html>", "<!doctype svg>", 1),
        _document("B").replace("<html", "<!doctype html><html", 1),
    ),
)
def test_noncanonical_generated_envelope_fails_closed(html):
    with pytest.raises(AssertionError):
        manual_generated_html_text(html)


@pytest.mark.parametrize("text", ("\v", "\u00a0"))
def test_non_html_structural_whitespace_outside_the_document_fails_closed(text):
    for html in (text + _document("B"), _document("B") + text):
        with pytest.raises(AssertionError):
            manual_generated_html_text(html)


def test_html_ascii_whitespace_outside_the_document_remains_ignorable():
    whitespace = " \t\n\f\r"

    assert manual_generated_html_text(whitespace + _document("B") + whitespace) == (
        f"{CURRENT_TITLE}\nB"
    )


@pytest.mark.parametrize(
    "body",
    (
        "<p>A<![CDATA[stale]]>B</p>",
        (
            '<p><code class="math" '
            'aria-label="mathematical expression N^<em>">'
            "N^</em><![CDATA[stale]]></code></p>"
        ),
    ),
)
def test_unknown_declarations_fail_closed(body):
    with pytest.raises(AssertionError):
        manual_generated_html_text(_document(body))


def test_head_metadata_and_attributes_are_not_visible_text():
    html = _document(
        '<div class="figure-alternative" role="img" aria-label="v0.93">Visible</div>'
    ).replace(
        '<meta charset="utf-8">',
        '<meta charset="utf-8"><meta name="description" content="v0.93">',
        1,
    )

    assert manual_generated_html_text(html) == f"{CURRENT_TITLE}\nVisible"


@pytest.mark.parametrize(
    "replacement",
    (
        '<meta name="description" content="current manual">',
        '<meta charset="utf-16">',
        '<meta charset="utf-8"><meta charset="utf-8">',
    ),
)
def test_generated_envelope_requires_one_exact_utf8_charset_declaration(replacement):
    html = _document("Visible").replace(
        '<meta charset="utf-8">',
        replacement,
        1,
    )

    with pytest.raises(AssertionError):
        manual_generated_html_text(html)


@pytest.mark.parametrize("language", ("da", "EN", "en-US", ""))
def test_generated_root_rejects_every_non_authoritative_language(language):
    html = _document("Visible").replace(
        '<html lang="en">',
        f'<html lang="{language}">',
        1,
    )

    with pytest.raises(AssertionError, match="attributes"):
        manual_generated_html_text(html)


@pytest.mark.parametrize(
    "meta_name",
    sorted(CURRENT_GENERATED_MANUAL_HTML_VOCABULARY.meta_names),
)
def test_each_generated_named_metadata_value_is_supported(meta_name):
    html = _document("Visible").replace(
        "<title>",
        f'<meta name="{meta_name}" content="value"><title>',
        1,
    )

    assert manual_generated_html_text(html) == f"{CURRENT_TITLE}\nVisible"


@pytest.mark.parametrize(
    "metadata",
    (
        '<meta name="obsolete" content="value">',
        '<meta name="Description" content="value">',
        '<meta name="description">',
        '<meta content="value">',
        '<meta name="description" content>',
    ),
)
def test_named_metadata_outside_the_exact_generated_shape_fails(metadata):
    html = _document("Visible").replace("<title>", metadata + "<title>", 1)

    with pytest.raises(AssertionError, match="metadata"):
        manual_generated_html_text(html)


@pytest.mark.parametrize(
    "role", sorted(CURRENT_GENERATED_MANUAL_HTML_VOCABULARY.div_roles)
)
def test_each_generated_div_role_is_supported(role):
    html = _document(f'<div role="{role}">Visible</div>')

    assert manual_generated_html_text(html) == f"{CURRENT_TITLE}\nVisible"


@pytest.mark.parametrize("role", ("image", "IMG", "Math", "", "presentation"))
def test_non_generator_div_roles_fail_closed(role):
    with pytest.raises(AssertionError, match="attributes"):
        manual_generated_html_text(_document(f'<div role="{role}">Visible</div>'))


@pytest.mark.parametrize(
    "scope",
    sorted(CURRENT_GENERATED_MANUAL_HTML_VOCABULARY.th_scopes),
)
def test_each_generated_table_header_scope_is_supported(scope):
    html = _document(
        f'<table><thead><tr><th scope="{scope}">Visible</th></tr></thead>'
        "<tbody><tr><td>Value</td></tr></tbody></table>"
    )

    assert "Visible" in manual_generated_html_text(html).splitlines()


@pytest.mark.parametrize("scope", ("column", "COL", "Row", "", "rowgroup"))
def test_non_generator_table_header_scopes_fail_closed(scope):
    html = _document(
        f'<table><thead><tr><th scope="{scope}">Visible</th></tr></thead>'
        "<tbody><tr><td>Value</td></tr></tbody></table>"
    )

    with pytest.raises(AssertionError, match="attributes"):
        manual_generated_html_text(html)


@pytest.mark.parametrize("value", (None, b"<html></html>", 1, False, []))
def test_manual_generated_html_text_rejects_non_text_input(value):
    with pytest.raises(AssertionError, match="built-in text"):
        manual_generated_html_text(value)


def test_manual_generated_html_text_rejects_text_subclasses():
    with pytest.raises(AssertionError, match="built-in text"):
        manual_generated_html_text(_TextSubclass(_document("text")))


def test_manual_generated_html_text_has_one_required_typed_parameter():
    signature = inspect.signature(manual_generated_html_text)
    assert tuple(signature.parameters) == ("html_text",)
    parameter = signature.parameters["html_text"]
    assert parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert parameter.default is inspect.Parameter.empty
    assert get_type_hints(manual_generated_html_text) == {
        "html_text": object,
        "return": str,
    }


def test_generated_manual_text_helper_is_dormant_and_text_only():
    module_path = Path(inspect.getfile(manual_generated_html_text))
    source = module_path.read_text(encoding="utf-8")
    syntax = ast.parse(source)
    repository = module_path.parents[1]
    callsites = []
    for path in repository.rglob("*.py"):
        if path == module_path or "tests" in path.parts:
            continue
        if "manual_generated_html_text" in path.read_text(
            encoding="utf-8", errors="ignore"
        ):
            callsites.append(path.relative_to(repository).as_posix())

    assert callsites == []
    expected_assignments = {
        "_VOCABULARY": "CURRENT_GENERATED_MANUAL_HTML_VOCABULARY",
        "_BODY_BLOCK_TAGS": "_VOCABULARY.body_block_tags",
        "_BODY_INLINE_TAGS": "_VOCABULARY.body_inline_tags",
        "_BODY_TAGS": (
            "_BODY_BLOCK_TAGS | _BODY_INLINE_TAGS | _VOCABULARY.body_void_tags"
        ),
        "_TABLE_CHILDREN": "dict(_VOCABULARY.table_children)",
        "_TABLE_PARENTS": (
            "{child: frozenset(parent for parent, children in "
            "_VOCABULARY.table_children if child in children) for child in "
            "frozenset().union(*_TABLE_CHILDREN.values())}"
        ),
        "_VOID_TAGS": "_VOCABULARY.body_void_tags | _VOCABULARY.head_void_tags",
        "_VISIBILITY_ATTRIBUTES": 'frozenset({"aria-hidden", "hidden", "style"})',
        "_GENERATED_ATTRIBUTES": "dict(_VOCABULARY.attribute_names_by_tag)",
        "_GENERATED_CLASS_TOKENS": "dict(_VOCABULARY.class_tokens_by_tag)",
        "_GENERATED_META_NAMES": "_VOCABULARY.meta_names",
        "_NONVISUAL_CLASS": "_VOCABULARY.nonvisual_class_token",
        "_N_STAR_CODE_START": "_VOCABULARY.n_star_code_start",
        "_HTML_ASCII_WHITESPACE": "_VOCABULARY.html_ascii_whitespace",
        "_ASCII_CLASS_SPACE_RE": (
            're.compile(f"[{re.escape(_HTML_ASCII_WHITESPACE)}]+")'
        ),
        "_FRAGMENT_HREF_RE": "re.compile(_VOCABULARY.fragment_href_pattern)",
        "_STRUCTURE_ERROR": '"issued manual HTML is outside its generated envelope"',
    }
    assignments = {
        node.targets[0].id: node.value
        for node in syntax.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    }
    assert tuple(assignments) == tuple(expected_assignments)
    for name, expression in expected_assignments.items():
        assert ast.dump(assignments[name], include_attributes=False) == ast.dump(
            ast.parse(expression, mode="eval").body,
            include_attributes=False,
        )
    assert Counter(
        node.attr
        for node in ast.walk(syntax)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "_VOCABULARY"
    ) == {
        "body_block_tags": 1,
        "body_inline_tags": 1,
        "body_void_tags": 2,
        "table_children": 2,
        "head_void_tags": 1,
        "attribute_names_by_tag": 1,
        "class_tokens_by_tag": 1,
        "meta_names": 1,
        "nonvisual_class_token": 1,
        "n_star_code_start": 1,
        "html_ascii_whitespace": 1,
        "fragment_href_pattern": 1,
        "html_language": 1,
        "html_charset": 1,
        "div_roles": 1,
        "th_scopes": 1,
        "doctype": 1,
        "current_head_style_sha256": 1,
    }
    assert CURRENT_STYLE_SHA256 not in source
    for excluded in (
        "manual_schema_references",
        "manual_product_references",
        "certif",
        "authorit",
        "compliance",
        "global verdict",
    ):
        assert excluded not in source.lower()
