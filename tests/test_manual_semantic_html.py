"""Direct contract tests for dormant issued-manual semantic HTML text."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import get_type_hints

import pytest

from sector import __version__
from tools.manual_semantic_html import manual_semantic_html_text

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import manual


class _TextSubclass(str):
    pass


CURRENT_TITLE = f"Sector user manual v{__version__}"


def _document(body: str, *, title: str = CURRENT_TITLE) -> str:
    return (
        "<!doctype html><html><head><title>"
        + title
        + "</title><style>body { color: black; }</style></head><body>"
        + body
        + "</body></html>"
    )


def test_manual_semantic_text_collapses_source_wraps_and_retains_real_blocks():
    html = _document(
        "<p><span>Version:</span>\n<span>0.94</span></p>"
        "<details><summary>Prelude</summary><span>Inline</span> detail</details>"
        "<p>Limitations &amp; troubleshooting</p>",
        title=f"Sector user\nmanual v{__version__}",
    )

    assert manual_semantic_html_text(html) == (
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
        "table",
        "tbody",
        "td",
        "th",
        "thead",
        "tr",
        "ul",
    ),
)
def test_each_owned_container_preserves_a_semantic_line_boundary(tag):
    html = _document(f"<span>A</span><{tag}>B</{tag}><span>C</span>")

    assert manual_semantic_html_text(html) == (
        f"{CURRENT_TITLE}\nA\nB\nC"
    )


def test_break_preserves_a_semantic_line_boundary():
    html = _document("<span>A</span><br/><span>B</span>")

    assert manual_semantic_html_text(html) == (
        f"{CURRENT_TITLE}\nA\nB"
    )


def test_optional_end_tags_do_not_require_browser_scope_emulation():
    html = _document(
        "<ul><li>A<li>B</ul><dl><dt>Term<dd>Definition</dl>"
        "<table><tr><td>C<td>D</table>"
    )

    assert manual_semantic_html_text(html) == (
        f"{CURRENT_TITLE}\nA\nB\nTerm\nDefinition\nC\nD"
    )


@pytest.mark.parametrize(
    "body",
    (
        "<ul><li hidden>A<li>B</ul>",
        '<p aria-hidden="true">Hidden</p>',
        '<p aria-hidden=" TRUE ">Hidden</p>',
        '<p aria-hidden="false">Unsupported visibility control</p>',
        '<p style="display: none">Hidden</p>',
        '<p style="color: red; display:none">Hidden</p>',
        '<p style="visibility : hidden !important">Hidden</p>',
        '<p style="visibility:collapse">Hidden</p>',
        '<p style="content-visibility:hidden">Hidden</p>',
        '<p style="/* guard */display:none">Hidden</p>',
        '<p style="display:/**/none">Hidden</p>',
        '<p style="font-family:&quot;x;display:none&quot;">Unsupported</p>',
        '<p aria-hidden="true" aria-hidden="false">Hidden</p>',
        '<p aria-hidden="false" aria-hidden="true">Unsupported</p>',
        '<p style="display:none" style="display:block">Hidden</p>',
        '<p style="display:block" style="display:none">Unsupported</p>',
        "<script>Hidden</script>",
        "<style>Hidden</style>",
        "<template>Hidden</template>",
    ),
)
def test_hidden_or_nonsemantic_body_content_fails_closed(body):
    with pytest.raises(AssertionError, match="content"):
        manual_semantic_html_text(_document(body))


def test_comments_attributes_and_head_style_do_not_become_semantic_text():
    html = (
        '<!doctype html><html><head><meta data-version="v0.93">'
        "<title>Current title</title><style>v0.93</style></head>"
        '<body><p data-note="v0.93">Visible<!-- v0.93 --></p></body></html>'
    )

    assert manual_semantic_html_text(html) == "Current title\nVisible"


def test_non_visibility_semantic_attributes_remain_supported():
    html = _document(
        '<p aria-label="Visible paragraph" class="current" '
        'data-note="current">Visible</p>'
    )

    assert manual_semantic_html_text(html) == f"{CURRENT_TITLE}\nVisible"


@pytest.mark.parametrize(
    "root_attribute",
    (
        "hidden",
        'aria-hidden="true"',
        'aria-hidden="false"',
        'style="display:none"',
    ),
)
def test_root_visibility_controls_fail_closed(root_attribute):
    html = _document("<p>Hidden document</p>").replace(
        "<html>", f"<html {root_attribute}>", 1
    )

    with pytest.raises(AssertionError, match="hidden semantic content"):
        manual_semantic_html_text(html)


@pytest.mark.parametrize("tag", ("script", "template"))
def test_nonsemantic_head_content_fails_closed(tag):
    html = _document("<p>Body</p>").replace(
        "<title>", f"<{tag}>Hidden</{tag}><title>", 1
    )

    with pytest.raises(AssertionError, match="non-semantic content"):
        manual_semantic_html_text(html)


@pytest.mark.parametrize(
    "html",
    (
        "<html><head><title>T</title></head><p>No body</p></html>",
        "<html><head></head><body>No title</body></html>",
        "<html><head><title>T</head><body>B</body></html>",
        "<html><head><title>T</title></head><body>B",
        "<html><head><title>T</title></head><body>B</body>Trailing</html>",
        (
            "<html><head><title>T</title></head><body>B</body>"
            "<p>After body</p></html>"
        ),
        "<html><head><title>T</title><title>Again</title></head><body>B</body></html>",
        "<html><head><title>T</title></head><body>B</body><body>C</body></html>",
        (
            "<html><html><head><title>T</title><style>x</style></head>"
            "<body>B</body></html>"
        ),
        (
            "<html><head><head><title>T</title><style>x</style></head>"
            "<body>B</body></html>"
        ),
        "<html><head><title/></head><body>B</body></html>",
        "<html><head><title>T</title><style>x</style></head><body/></html>",
        (
            "<html><head><title>T</title><style>x</style></head>"
            "<body>A<p/>B</body></html>"
        ),
        (
            "<html><head><title>T</title><style>x</style></head>"
            "<body>A<div/>B</body></html>"
        ),
        (
            "<html><head><title>T</title><style>x</style></head>"
            "<p>Version: 0.93</p><body>B</body></html>"
        ),
        (
            "<html><head><title>T</title><style>x</style></head>"
            "Version: 0.93<body>B</body></html>"
        ),
        "Version: 0.93<html><head><title>T</title><style>x</style></head><body>B</body></html>",
        "<html><title>T</title><style>x</style><body>B</body></html>",
        "<html><head><title>T</title></head><body>B</body></html>",
    ),
)
def test_noncanonical_title_or_body_structure_fails_closed(html):
    with pytest.raises(AssertionError, match="title/body structure"):
        manual_semantic_html_text(html)


def test_duplicate_head_style_fails_closed():
    html = (
        "<html><head><title>T</title><style>x</style><style>y</style>"
        "</head><body>B</body></html>"
    )

    with pytest.raises(AssertionError, match="non-semantic content"):
        manual_semantic_html_text(html)


def test_unmatched_inline_end_tag_does_not_change_semantic_text():
    html = _document("<p><code>N^</em></code></p>")

    assert manual_semantic_html_text(html) == f"{CURRENT_TITLE}\nN^"


def test_current_generated_manual_satisfies_the_semantic_boundary():
    text = manual_semantic_html_text(
        manual.build_manual_html_bytes().decode("utf-8")
    )
    lines = text.splitlines()

    assert lines[0] == CURRENT_TITLE
    assert f"Version: {__version__}" in lines
    assert "Symbols and units" in lines


@pytest.mark.parametrize("value", (None, b"<body>text</body>", 1, False, []))
def test_manual_semantic_html_text_rejects_non_text_input(value):
    with pytest.raises(AssertionError, match="built-in text"):
        manual_semantic_html_text(value)


def test_manual_semantic_html_text_rejects_text_subclasses():
    with pytest.raises(AssertionError, match="built-in text"):
        manual_semantic_html_text(_TextSubclass(_document("text")))


def test_manual_semantic_html_text_has_one_required_typed_parameter():
    signature = inspect.signature(manual_semantic_html_text)
    assert tuple(signature.parameters) == ("html_text",)
    parameter = signature.parameters["html_text"]
    assert parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert parameter.default is inspect.Parameter.empty
    assert get_type_hints(manual_semantic_html_text) == {
        "html_text": object,
        "return": str,
    }


def test_manual_semantic_html_helper_is_dormant_and_text_only():
    module_path = Path(inspect.getfile(manual_semantic_html_text))
    source = module_path.read_text(encoding="utf-8")
    repository = module_path.parents[1]
    callsites = []
    for path in repository.rglob("*.py"):
        if path == module_path or "tests" in path.parts:
            continue
        if "manual_semantic_html_text" in path.read_text(
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
