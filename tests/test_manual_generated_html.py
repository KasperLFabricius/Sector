"""Direct contract tests for dormant generated-manual visible text."""

from __future__ import annotations

import hashlib
import inspect
import sys
from pathlib import Path
from typing import get_type_hints

import pytest

from sector import __version__
from tools.manual_generated_html import manual_generated_html_text

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import manual


class _TextSubclass(str):
    pass


CURRENT_TITLE = f"Sector user manual v{__version__}"
CURRENT_STYLE_SHA256 = (
    "3925ff6f5ac21c001047c26a6bfd49dfe97c9d77fa9859992f05e0885a59f94a"
)
GENERATED_HTML = manual.build_manual_html_bytes().decode("utf-8")
CURRENT_STYLE = GENERATED_HTML.partition("<style>")[2].partition("</style>")[0]


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
    html = _document(
        '<p>A<span class="math sr-only"><strong>Hidden</strong></span>B</p>'
    )

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


@pytest.mark.parametrize("separator", (" ", "\t", "\n", "\f", "\r"))
def test_ascii_html_class_separators_apply_the_nonvisual_class(separator):
    html = _document(f'<p>A<span class="math{separator}sr-only">Hidden</span>B</p>')

    assert manual_generated_html_text(html) == f"{CURRENT_TITLE}\nAB"


@pytest.mark.parametrize("separator", ("\v", "\u00a0", "\u2003", "\u202f"))
def test_unicode_non_html_class_separators_fail_closed(separator):
    html = _document(f'<p>A<span class="math{separator}sr-only">Hidden</span>B</p>')

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
    for excluded in (
        "manual_schema_references",
        "manual_product_references",
        "certif",
        "authorit",
        "compliance",
        "global verdict",
    ):
        assert excluded not in source.lower()
