"""Strict original-brand HTML envelope without rendering a document."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.publication_branding import logo_html
from tools.manual_generated_html import manual_generated_html_text

ROOT = Path(__file__).resolve().parents[1]


def _document():
    tree = ast.parse((ROOT / "app/manual.py").read_text("utf-8"))
    chunk = next(node.value for node in ast.walk(tree)
                 if isinstance(node, ast.Constant) and isinstance(node.value, str)
                 and "<style>" in node.value)
    css = chunk.split("<style>", 1)[1].split("</style>", 1)[0]
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<title>Sector user manual</title><style>' + css + '</style></head>'
            '<body><header>' + logo_html() + '<h1>Sector user manual</h1></header>'
            '<main id="manual-main"><p>Visible engineering guidance.</p></main>'
            '</body></html>')


def test_original_header_logo_and_fingerprinted_css_are_accepted():
    assert "Visible engineering guidance." in manual_generated_html_text(_document())
    assert 'style=' not in logo_html()


@pytest.mark.parametrize("old,new", [
    ('alt="Sweco"', 'alt="Sweco" hidden'),
    ('alt="Sweco"', 'alt="Sweco" aria-hidden="true"'),
    ('alt="Sweco"', 'alt="Sweco" style="display:none"'),
    ('alt="Sweco"', 'alt="Other"'),
    ('alt="Sweco"', 'alt="Sweco" width="1"'),
    ('width:180px', 'width:1px'),
    ('class="publication-logo"', 'class="manual-figure"'),
])
def test_branding_keeps_hidden_content_and_identity_guards(old, new):
    text = _document()
    assert old in text
    with pytest.raises(AssertionError):
        manual_generated_html_text(text.replace(old, new))


def test_original_logo_cannot_be_moved_into_engineering_figure():
    text = _document().replace('<header>', '<header></header><figure>')
    text = text.replace('</header><main', '</figure><main')
    with pytest.raises(AssertionError):
        manual_generated_html_text(text)


def test_logo_bytes_cannot_be_replaced_with_another_png():
    text = _document()
    payload = logo_html().split('src="')[1].split('"')[0]
    with pytest.raises(AssertionError, match="altered Sweco artwork"):
        manual_generated_html_text(text.replace(payload, 'data:image/png;base64,iVBORw0KGgo='))
