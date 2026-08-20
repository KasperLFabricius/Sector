"""Direct contract tests for dormant issued-manual HTML text extraction."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import get_type_hints

import pytest

from tools.manual_visible_html import visible_manual_html_text


class _TextSubclass(str):
    pass


def test_visible_manual_html_text_preserves_real_block_and_inline_semantics():
    html = """<!doctype html>
<html lang="en"><head>
<title>Sector user manual v0.94</title>
<style>body { color: black; }</style>
</head><body>
<p><strong>Version:</strong> 0.94</p>
<details><summary>Prelude</summary>
<span>Inline</span> <em>detail</em>
<p>v0.93</p></details>
<p>Limitations &amp; troubleshooting</p>
</body></html>"""

    assert visible_manual_html_text(html) == (
        "Sector user manual v0.94\n"
        "Version: 0.94\n"
        "Prelude\n"
        "Inline detail\n"
        "v0.93\n"
        "Limitations & troubleshooting"
    )


def test_adjacent_html_blocks_remain_distinct_reference_lines():
    html = "<html><body><p>JSON</p><p>Schema 24</p></body></html>"

    assert visible_manual_html_text(html) == "JSON\nSchema 24"


def test_authored_inline_whitespace_does_not_create_rendered_lines():
    html = (
        "<html><head><title>Sector user\nmanual v0.94</title></head><body>"
        "<p><span>Version:</span>\n<span>0.93</span></p></body></html>"
    )

    assert visible_manual_html_text(html) == (
        "Sector user manual v0.94\nVersion: 0.93"
    )


@pytest.mark.parametrize(
    "suppressed",
    (
        "<div hidden>Hidden</div>",
        "<script>Hidden</script>",
        "<style>Hidden</style>",
        "<template>Hidden</template>",
    ),
)
def test_suppressed_elements_do_not_create_rendered_boundaries(suppressed):
    html = "<html><body><span>Version:</span>" + suppressed + (
        "<span>0.93</span></body></html>"
    )

    assert visible_manual_html_text(html) == "Version:0.93"


def test_compact_details_and_summary_have_independent_boundaries():
    html = (
        "<html><body><span>A</span><details><summary>B</summary>"
        "C</details><span>D</span></body></html>"
    )

    assert visible_manual_html_text(html) == "A\nB\nC\nD"


def test_manual_list_definition_table_and_break_boundaries_are_retained():
    html = (
        "<html><body><span>Lead</span><br><span>After break</span>"
        "<ul><li>One</li><li>Two</li></ul>"
        "<dl><dt>Term</dt><dd>Definition</dd></dl>"
        "<table><tr><th>H1</th><th>H2</th></tr>"
        "<tr><td>C1</td><td>C2</td></tr></table></body></html>"
    )

    assert visible_manual_html_text(html) == (
        "Lead\nAfter break\nOne\nTwo\nTerm\nDefinition\nH1\nH2\nC1\nC2"
    )


def test_void_elements_do_not_corrupt_suppression_or_the_element_stack():
    hidden_outer = (
        "<html><body><div hidden>Before<br>After</div>"
        "<span>Visible sibling</span></body></html>"
    )
    hidden_void = (
        "<html><body><span>Version:</span><br hidden>"
        "<span>0.93</span></body></html>"
    )

    assert visible_manual_html_text(hidden_outer) == "Visible sibling"
    assert visible_manual_html_text(hidden_void) == "Version:0.93"


@pytest.mark.parametrize(
    "wrapper",
    (
        "<div hidden>{}</div>",
        "<script>{}</script>",
        "<style>{}</style>",
        "<template>{}</template>",
    ),
)
def test_nonrendered_text_is_excluded_without_hiding_a_visible_sibling(wrapper):
    html = "<html><body>" + wrapper.format("Hidden") + (
        "<p>Visible sibling</p></body></html>"
    )

    assert visible_manual_html_text(html) == "Visible sibling"


@pytest.mark.parametrize(
    "nested_markup",
    (
        "<span><em>Nested inline</em></span>",
        "<style>Nested style</style>",
        "<template><strong>Nested template</strong></template>",
    ),
)
def test_nested_suppression_remains_active_until_the_outer_element_closes(
    nested_markup,
):
    html = (
        "<html><body><div hidden>"
        + nested_markup
        + "Hidden after the nested close</div><p>Visible after</p></body></html>"
    )

    assert visible_manual_html_text(html) == "Visible after"


@pytest.mark.parametrize(
    "suppressed_subtree",
    (
        "<div hidden><p>Hidden block</p><br></div>",
        "<template><p>Hidden block</p><br></template>",
    ),
)
def test_suppressed_descendants_contribute_neither_text_nor_layout(
    suppressed_subtree,
):
    html = (
        "<html><body><span>A</span>"
        + suppressed_subtree
        + "<span>B</span></body></html>"
    )

    assert visible_manual_html_text(html) == "AB"


def test_comments_attributes_and_head_content_do_not_become_visible_text():
    html = (
        '<html><head><meta data-version="v0.93"><style>Hidden style</style></head>'
        '<body><p data-note="v0.93">Visible<!-- v0.93 --></p></body></html>'
    )

    assert visible_manual_html_text(html) == "Visible"


@pytest.mark.parametrize("value", (None, b"<body>text</body>", 1, False, []))
def test_visible_manual_html_text_rejects_non_text_input(value):
    with pytest.raises(AssertionError, match="built-in text"):
        visible_manual_html_text(value)


def test_visible_manual_html_text_rejects_text_subclasses():
    with pytest.raises(AssertionError, match="built-in text"):
        visible_manual_html_text(_TextSubclass("<body>text</body>"))


def test_visible_manual_html_text_has_one_required_typed_parameter():
    signature = inspect.signature(visible_manual_html_text)
    assert tuple(signature.parameters) == ("html_text",)
    parameter = signature.parameters["html_text"]
    assert parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert parameter.default is inspect.Parameter.empty
    assert get_type_hints(visible_manual_html_text) == {
        "html_text": object,
        "return": str,
    }


def test_visible_manual_html_helper_is_dormant_and_stays_within_text_scope():
    module_path = Path(inspect.getfile(visible_manual_html_text))
    source = module_path.read_text(encoding="utf-8")
    repository = module_path.parents[1]
    callsites = []
    for path in repository.rglob("*.py"):
        if path == module_path or "tests" in path.parts:
            continue
        if "visible_manual_html_text" in path.read_text(
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
