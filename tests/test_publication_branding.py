"""Original-artwork identity and separate branding/engineering inventories."""

from __future__ import annotations

import ast
import base64
import hashlib
import io
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from reportlab.lib.units import mm

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from app import publication_branding as branding
from tools.manual_render_fixture import (
    _HTMLInventory,
    _validate_pdf_image_inventory,
)


def test_original_sweco_bytes_and_cover_aspect_are_preserved():
    payload = branding.logo_bytes()
    assert hashlib.sha256(payload).hexdigest() == (
        "46abdd46c2d6e2675109b31590936fb45963bb88e8962c838a35ba8dac7ed436"
    )
    logo = branding.logo_flowable(45 * mm)
    assert logo.drawWidth == 45 * mm
    assert logo.drawHeight == pytest.approx(45 * mm * 373 / 1280)
    assert logo.hAlign == "LEFT"
    with Image.open(io.BytesIO(payload)) as original:
        assert logo._img.getRGBData() == original.convert("RGB").tobytes()


def test_missing_mandatory_artwork_fails_clearly(tmp_path, monkeypatch):
    monkeypatch.setattr(branding, "LOGO_PATH", tmp_path / "missing.png")
    with pytest.raises(RuntimeError, match="required Sweco logo"):
        branding.logo_bytes()


def test_non_png_artwork_is_rejected(tmp_path, monkeypatch):
    path = tmp_path / "logo.png"
    path.write_bytes(b"not a PNG")
    monkeypatch.setattr(branding, "LOGO_PATH", path)
    with pytest.raises(ValueError, match="PNG"):
        branding.logo_html()


def _html(brand=None, figures=40):
    parser = _HTMLInventory()
    parser.feed("<header>" + (branding.logo_html() if brand is None else brand) + "</header>")
    parser.feed('<img class="manual-figure" src="data:image/png;base64,AA==">' * figures)
    return parser


def test_html_classifies_exact_original_logo_separately_from_all_40_figures():
    parser = _html()
    parser.validate_image_inventory()
    assert (parser.brand_images, parser.engineering_images) == (1, 40)
    source = branding.logo_html().split('src="')[1].split('"')[0]
    assert base64.b64decode(source.split(",", 1)[1]) == branding.logo_bytes()


@pytest.mark.parametrize("brand,figures", [("", 40), (None, 39), (None, 41)])
def test_html_requires_brand_and_unchanged_engineering_inventory(brand, figures):
    with pytest.raises(AssertionError):
        _html(brand, figures).validate_image_inventory()


@pytest.mark.parametrize("old,new", [
    ('alt="Sweco"', 'alt=""'), ('alt="Sweco"', 'alt="Sweco" height="80"'),
    ('alt="Sweco"', 'alt="Sweco" width="90"'),
    ('data:image/png;base64,', 'https://example.invalid/logo.png'),
])
def test_html_rejects_changed_brand_identity_or_aspect(old, new):
    with pytest.raises(AssertionError):
        _html(branding.logo_html().replace(old, new))


class _Object(dict):
    def get_object(self):
        return self

    def get_data(self):
        return self["pixels"]


def _pdf(figure_count=40, logo_count=1, *, wrong_pixels=False, logo_page=0):
    with Image.open(io.BytesIO(branding.logo_bytes())) as logo:
        pixels = logo.convert("RGB").tobytes()
    brand = _Object({"/Subtype": "/Image", "/Width": 1280, "/Height": 373,
                     "/ColorSpace": "/DeviceRGB", "pixels": b"bad" if wrong_pixels else pixels})
    figure = _Object({"/Subtype": "/Image", "/Width": 500, "/Height": 500})
    objects = [_Object(), _Object({str(i): figure for i in range(figure_count)})]
    objects[logo_page].update({"logo" + str(i): brand for i in range(logo_count)})
    return SimpleNamespace(pages=[{"/Resources": _Object({"/XObject": obj})} for obj in objects])


def test_pdf_requires_exact_original_rgb_logo_and_all_40_engineering_images():
    _validate_pdf_image_inventory(_pdf())


@pytest.mark.parametrize("changes", [
    {"figure_count": 39}, {"figure_count": 41}, {"logo_count": 0},
    {"logo_count": 2}, {"wrong_pixels": True}, {"logo_page": 1},
])
def test_pdf_inventory_rejects_missing_extra_modified_or_misplaced_brand(changes):
    with pytest.raises(AssertionError):
        _validate_pdf_image_inventory(_pdf(**changes))


@pytest.mark.parametrize("file,function", [
    ("app/sector_report.py", "_cover"), ("app/manual.py", "build_manual_pdf"),
])
def test_pdf_renderers_place_logo_before_the_document_title(file, function):
    tree = ast.parse((ROOT / file).read_text("utf-8"))
    body = next(node for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == function)
    calls = [node for node in ast.walk(body) if isinstance(node, ast.Call)]
    logos = [node for node in calls if isinstance(node.func, ast.Attribute)
             and ast.unparse(node.func) == "publication_branding.logo_flowable"]
    assert len(logos) == 1
    title = next(node for node in calls if isinstance(node.func, ast.Name)
                 and node.func.id == "Paragraph" and node.args
                 and isinstance(node.args[0], ast.Constant)
                 and node.args[0].value in {"Cross-section analysis report", "Sector user manual"})
    assert logos[0].lineno < title.lineno
    assert ast.unparse(logos[0].args[0]) in {"45 * mm", "4.5 * cm"}
