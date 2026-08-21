"""Direct contract tests for the dormant generated-manual HTML vocabulary."""

from __future__ import annotations

import ast
import hashlib
import re
import sys
from collections import Counter
from dataclasses import FrozenInstanceError, fields
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from typing import get_type_hints

import pytest

from tools.manual_generated_html_vocabulary import (
    CURRENT_GENERATED_MANUAL_HTML_VOCABULARY,
    GeneratedManualHTMLVocabulary,
)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import manual  # isort: skip


CURRENT_HTML = manual.build_manual_html_bytes().decode("utf-8")
_HTML_CLASS_SPACE_RE = re.compile(r"[\t\n\f\r ]+")


class _Inventory(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: set[str] = set()
        self.attribute_names: dict[str, set[str]] = {}
        self.attributes: dict[str, list[dict[str, str | None]]] = {}
        self.class_tokens: dict[str, set[str]] = {}
        self.style_fragments: list[str] = []
        self.declarations: list[str] = []
        self.in_style = False

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.tags.add(tag)
        self.attribute_names.setdefault(tag, set()).update(name for name, _ in attrs)
        values = dict(attrs)
        self.attributes.setdefault(tag, []).append(values)
        class_value = (values.get("class") or "").strip("\t\n\f\r ")
        self.class_tokens.setdefault(tag, set()).update(
            _HTML_CLASS_SPACE_RE.split(class_value) if class_value else ()
        )
        if tag == "style":
            self.in_style = True

    def handle_decl(self, decl: str) -> None:
        self.declarations.append(decl)

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self.in_style = False

    def handle_data(self, data: str) -> None:
        if self.in_style:
            self.style_fragments.append(data)


def _inventory(html_text: str) -> _Inventory:
    inventory = _Inventory()
    inventory.feed(html_text)
    inventory.close()
    return inventory


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
    monkeypatch.setattr(manual, "source_revision", lambda: "vocabulary-test")
    return manual.build_manual_html_bytes().decode("utf-8")


def test_generated_manual_html_vocabulary_has_exact_data_contract():
    vocabulary = CURRENT_GENERATED_MANUAL_HTML_VOCABULARY

    assert isinstance(vocabulary, GeneratedManualHTMLVocabulary)
    assert tuple(field.name for field in fields(vocabulary)) == (
        "current_head_style_sha256",
        "body_block_tags",
        "body_inline_tags",
        "body_void_tags",
        "head_void_tags",
        "table_children",
        "attribute_names_by_tag",
        "class_tokens_by_tag",
        "meta_names",
        "div_roles",
        "th_scopes",
        "doctype",
        "html_language",
        "html_charset",
        "nonvisual_class_token",
        "n_star_code_start",
        "html_ascii_whitespace",
        "fragment_href_pattern",
    )
    assert vocabulary.current_head_style_sha256 == (
        "3925ff6f5ac21c001047c26a6bfd49dfe97c9d77fa9859992f05e0885a59f94a"
    )
    assert vocabulary.body_block_tags == frozenset(
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
    assert vocabulary.body_inline_tags == frozenset(
        {"a", "code", "em", "span", "strong"}
    )
    assert vocabulary.body_void_tags == frozenset({"br"})
    assert vocabulary.head_void_tags == frozenset({"meta"})
    assert vocabulary.table_children == (
        ("table", frozenset({"tbody", "thead"})),
        ("tbody", frozenset({"tr"})),
        ("thead", frozenset({"tr"})),
        ("tr", frozenset({"td", "th"})),
    )
    attribute_tags = tuple(tag for tag, _ in vocabulary.attribute_names_by_tag)
    assert attribute_tags == tuple(sorted(attribute_tags))
    assert len(attribute_tags) == len(set(attribute_tags))
    assert dict(vocabulary.attribute_names_by_tag) == {
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
    class_tags = tuple(tag for tag, _ in vocabulary.class_tokens_by_tag)
    assert class_tags == tuple(sorted(class_tags))
    assert len(class_tags) == len(set(class_tags))
    assert dict(vocabulary.class_tokens_by_tag) == {
        "aside": frozenset(
            {"callout", "concept", "limit", "standard", "theory", "tip"}
        ),
        "code": frozenset({"math"}),
        "div": frozenset({"display-math", "figure-alternative", "table-scroll"}),
        "dl": frozenset({"equation-results"}),
        "figure": frozenset({"table-figure"}),
        "li": frozenset({"toc-level-0", "toc-level-1", "toc-level-2"}),
        "p": frozenset(
            {
                "document-control",
                "equation-heading",
                "equation-text",
                "equation-uses",
                "source",
            }
        ),
        "section": frozenset({"equation"}),
        "span": frozenset({"sr-only"}),
    }
    assert vocabulary.meta_names == frozenset(
        {
            "author",
            "description",
            "keywords",
            "sector-source-revision",
            "sector-version",
            "viewport",
        }
    )
    assert vocabulary.div_roles == frozenset({"img", "math"})
    assert vocabulary.th_scopes == frozenset({"col", "row"})
    assert vocabulary.doctype == "doctype html"
    assert vocabulary.html_language == "en"
    assert vocabulary.html_charset == "utf-8"
    assert vocabulary.nonvisual_class_token == "sr-only"
    assert vocabulary.n_star_code_start == (
        '<code class="math" aria-label="mathematical expression N^<em>">'
    )
    assert vocabulary.html_ascii_whitespace == "\t\n\f\r "
    assert vocabulary.fragment_href_pattern == r"#[A-Za-z0-9_-]+"
    assert get_type_hints(GeneratedManualHTMLVocabulary) == {
        "current_head_style_sha256": str,
        "body_block_tags": frozenset[str],
        "body_inline_tags": frozenset[str],
        "body_void_tags": frozenset[str],
        "head_void_tags": frozenset[str],
        "table_children": tuple[tuple[str, frozenset[str]], ...],
        "attribute_names_by_tag": tuple[tuple[str, frozenset[str]], ...],
        "class_tokens_by_tag": tuple[tuple[str, frozenset[str]], ...],
        "meta_names": frozenset[str],
        "div_roles": frozenset[str],
        "th_scopes": frozenset[str],
        "doctype": str,
        "html_language": str,
        "html_charset": str,
        "nonvisual_class_token": str,
        "n_star_code_start": str,
        "html_ascii_whitespace": str,
        "fragment_href_pattern": str,
    }


def test_generated_manual_html_vocabulary_is_deeply_immutable():
    vocabulary = CURRENT_GENERATED_MANUAL_HTML_VOCABULARY

    assert not hasattr(vocabulary, "__dict__")
    assert isinstance(hash(vocabulary), int)
    with pytest.raises(FrozenInstanceError):
        vocabulary.html_language = "da"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        vocabulary.body_block_tags.add("script")  # type: ignore[attr-defined]
    assert all(
        isinstance(children, frozenset) for _, children in vocabulary.table_children
    )
    assert all(
        isinstance(names, frozenset) for _, names in vocabulary.attribute_names_by_tag
    )
    assert all(
        isinstance(tokens, frozenset) for _, tokens in vocabulary.class_tokens_by_tag
    )


def test_current_and_dormant_generator_paths_exactly_cover_vocabulary(monkeypatch):
    current = _inventory(CURRENT_HTML)
    dormant_html = _dormant_generator_html(monkeypatch)
    dormant = _inventory(dormant_html)
    vocabulary = CURRENT_GENERATED_MANUAL_HTML_VOCABULARY

    assert "display-math" not in current.class_tokens.get("div", set())
    assert "theory" not in current.class_tokens.get("aside", set())
    assert "h5" not in current.tags
    assert '<div class="display-math" role="math" aria-label="x+y">' in dormant_html
    assert '<aside class="callout theory">' in dormant_html
    assert '<h5 id="' in dormant_html

    observed_tags = current.tags | dormant.tags
    observed_attributes = {
        tag: current.attribute_names.get(tag, set())
        | dormant.attribute_names.get(tag, set())
        for tag in observed_tags
    }
    observed_classes = {
        tag: current.class_tokens.get(tag, set()) | dormant.class_tokens.get(tag, set())
        for tag in observed_tags
        if current.class_tokens.get(tag) or dormant.class_tokens.get(tag)
    }

    assert observed_tags == set(dict(vocabulary.attribute_names_by_tag))
    assert observed_attributes == {
        tag: set(names) for tag, names in vocabulary.attribute_names_by_tag
    }
    assert observed_classes == {
        tag: set(tokens) for tag, tokens in vocabulary.class_tokens_by_tag
    }
    assert set(manual._CALLOUT) == {"concept", "theory", "standard", "tip", "limit"}
    for inventory in (current, dormant):
        assert inventory.declarations == [vocabulary.doctype]
        assert inventory.attributes["html"] == [{"lang": vocabulary.html_language}]
        assert {values.get("name") for values in inventory.attributes["meta"]} - {
            None
        } == set(vocabulary.meta_names)
        assert {"charset": vocabulary.html_charset} in inventory.attributes["meta"]
    assert {
        values["role"]
        for inventory in (current, dormant)
        for values in inventory.attributes["div"]
        if "role" in values
    } == set(vocabulary.div_roles)
    assert {
        values["scope"] for values in current.attributes["th"] if "scope" in values
    } == set(vocabulary.th_scopes)
    assert vocabulary.n_star_code_start in CURRENT_HTML
    fragment_pattern = re.compile(vocabulary.fragment_href_pattern)
    generated_hrefs = {
        values["href"]
        for inventory in (current, dormant)
        for values in inventory.attributes.get("a", ())
        if "href" in values
    }
    assert generated_hrefs
    assert all(
        href is not None and fragment_pattern.fullmatch(href)
        for href in generated_hrefs
    )


def test_dormant_display_math_branch_has_exact_generated_markup():
    assert manual._markdown_block_html("$$x+y$$") == (
        '<div class="display-math" role="math" aria-label="x+y"><code>x+y</code></div>'
    )


@pytest.mark.parametrize("href", ("#a", "#manual-section-1", "#A_1"))
def test_fragment_href_grammar_accepts_generated_forms(href):
    pattern = re.compile(CURRENT_GENERATED_MANUAL_HTML_VOCABULARY.fragment_href_pattern)

    assert pattern.fullmatch(href)


@pytest.mark.parametrize(
    "href",
    ("#", "section", "#manual.section", "#a/b", "#å", "#a onclick=alert(1)"),
)
def test_fragment_href_grammar_rejects_non_generator_forms(href):
    pattern = re.compile(CURRENT_GENERATED_MANUAL_HTML_VOCABULARY.fragment_href_pattern)

    assert pattern.fullmatch(href) is None


@pytest.mark.parametrize("separator", (" ", "\t", "\n", "\f", "\r"))
def test_inventory_splits_class_tokens_only_on_html_ascii_space(separator):
    inventory = _inventory(f'<div class="display-math{separator}table-scroll"></div>')

    assert inventory.class_tokens["div"] == {"display-math", "table-scroll"}


@pytest.mark.parametrize("separator", ("\v", "\u00a0", "\u2003", "\u202f"))
def test_inventory_does_not_split_classes_on_unicode_non_html_space(separator):
    token = f"display-math{separator}table-scroll"
    inventory = _inventory(f'<div class="{token}"></div>')

    assert inventory.class_tokens["div"] == {token}


def test_current_and_dormant_documents_share_exact_stylesheet(monkeypatch):
    current = _inventory(CURRENT_HTML)
    dormant = _inventory(_dormant_generator_html(monkeypatch))
    vocabulary = CURRENT_GENERATED_MANUAL_HTML_VOCABULARY

    for inventory in (current, dormant):
        style_text = "".join(inventory.style_fragments)
        assert hashlib.sha256(style_text.encode("utf-8")).hexdigest() == (
            vocabulary.current_head_style_sha256
        )


def test_generated_manual_html_vocabulary_is_data_only_and_dormant():
    module_path = ROOT / "tools" / "manual_generated_html_vocabulary.py"
    source = module_path.read_text(encoding="utf-8")
    syntax = ast.parse(source)
    functions = [
        node
        for node in ast.walk(syntax)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    callsites = []
    for path in ROOT.rglob("*.py"):
        if path == module_path or "tests" in path.parts:
            continue
        candidate_source = path.read_text(encoding="utf-8", errors="ignore")
        if any(
            reference in candidate_source
            for reference in (
                "manual_generated_html_vocabulary",
                "GeneratedManualHTMLVocabulary",
                "CURRENT_GENERATED_MANUAL_HTML_VOCABULARY",
            )
        ):
            callsites.append(path.relative_to(ROOT).as_posix())

    assert [type(node) for node in syntax.body] == [
        ast.Expr,
        ast.ImportFrom,
        ast.ImportFrom,
        ast.ClassDef,
        ast.Assign,
    ]
    assert ast.get_docstring(syntax) is not None
    imports = [node for node in syntax.body if isinstance(node, ast.ImportFrom)]
    assert [
        (
            node.module,
            tuple((alias.name, alias.asname) for alias in node.names),
            node.level,
        )
        for node in imports
    ] == [
        ("__future__", (("annotations", None),), 0),
        ("dataclasses", (("dataclass", None),), 0),
    ]
    class_node = syntax.body[3]
    assert isinstance(class_node, ast.ClassDef)
    assert class_node.name == "GeneratedManualHTMLVocabulary"
    assert class_node.bases == []
    assert class_node.keywords == []
    assert len(class_node.decorator_list) == 1
    decorator = class_node.decorator_list[0]
    assert isinstance(decorator, ast.Call)
    assert isinstance(decorator.func, ast.Name)
    assert decorator.func.id == "dataclass"
    assert decorator.args == []
    assert len(decorator.keywords) == 2
    assert all(
        keyword.arg in {"frozen", "slots"}
        and isinstance(keyword.value, ast.Constant)
        and type(keyword.value.value) is bool
        for keyword in decorator.keywords
    )
    assert {keyword.arg: keyword.value.value for keyword in decorator.keywords} == {
        "frozen": True,
        "slots": True,
    }
    assert [type(node) for node in class_node.body] == [ast.Expr] + [ast.AnnAssign] * 18
    assert ast.get_docstring(class_node) is not None
    class_fields = [node for node in class_node.body if isinstance(node, ast.AnnAssign)]
    assert tuple(
        node.target.id for node in class_fields if isinstance(node.target, ast.Name)
    ) == tuple(field.name for field in fields(GeneratedManualHTMLVocabulary))
    assert all(node.value is None and node.simple == 1 for node in class_fields)
    assignment = syntax.body[-1]
    assert isinstance(assignment, ast.Assign)
    assert len(assignment.targets) == 1
    assert isinstance(assignment.targets[0], ast.Name)
    assert assignment.targets[0].id == "CURRENT_GENERATED_MANUAL_HTML_VOCABULARY"
    assert isinstance(assignment.value, ast.Call)
    assert isinstance(assignment.value.func, ast.Name)
    assert assignment.value.func.id == "GeneratedManualHTMLVocabulary"
    assert assignment.value.args == []
    assert len(assignment.value.keywords) == 18
    assert all(keyword.arg is not None for keyword in assignment.value.keywords)
    assert tuple(keyword.arg for keyword in assignment.value.keywords) == tuple(
        field.name for field in fields(GeneratedManualHTMLVocabulary)
    )

    def assert_literal_container(node: ast.AST) -> None:
        if isinstance(node, ast.Constant):
            assert type(node.value) is str
            return
        if isinstance(node, (ast.Set, ast.Tuple)):
            for element in node.elts:
                assert_literal_container(element)
            return
        assert isinstance(node, ast.Call)
        assert isinstance(node.func, ast.Name)
        assert node.func.id == "frozenset"
        assert len(node.args) in {0, 1}
        assert node.keywords == []
        if node.args:
            assert_literal_container(node.args[0])

    for keyword in assignment.value.keywords:
        assert_literal_container(keyword.value)
    calls = [node for node in ast.walk(syntax) if isinstance(node, ast.Call)]
    assert all(isinstance(call.func, ast.Name) for call in calls)
    assert Counter(
        call.func.id for call in calls if isinstance(call.func, ast.Name)
    ) == {
        "dataclass": 1,
        "GeneratedManualHTMLVocabulary": 1,
        "frozenset": 60,
    }
    assert functions == []
    assert callsites == []
    for excluded in (
        "manual_schema_references",
        "manual_product_references",
        "certif",
        "authorit",
        "approv",
        "compliance",
        "conform",
        "acceptan",
        "attest",
        "global pass",
        "global fail",
        "global verdict",
        "verdict",
    ):
        assert excluded not in source.lower()
