"""Keep original cover artwork separate from engineering image counts."""

import io

import pypdf
import pytest
from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from app.publication_branding import logo_bytes
from tools.report_render_fixture import _engineering_image_counts


def _document(*, copies=1, page=0, width=45 * 72 / 25.4,
              x=40, wrong_pixels=False):
    output = io.BytesIO()
    canvas = Canvas(output)
    logo = Image.open(io.BytesIO(logo_bytes())).convert("RGB")
    if wrong_pixels:
        logo.putpixel((0, 0), (123, 45, 67))
    for number in range(2):
        if number == page:
            for _ in range(copies):
                canvas.drawImage(ImageReader(logo), x, 700, width,
                                 width * 373 / 1280)
        if number == 1:
            canvas.drawImage(ImageReader(Image.new("RGB", (20, 20), "red")),
                             50, 500, 80, 80)
        canvas.showPage()
    canvas.save()
    return pypdf.PdfReader(io.BytesIO(output.getvalue()))


def test_exact_cover_brand_keeps_engineering_count():
    assert _engineering_image_counts(_document()) == (0, 1)


@pytest.mark.parametrize("change", [
    {"copies": 0}, {"copies": 2}, {"page": 1}, {"width": 60},
    {"x": -200}, {"wrong_pixels": True},
])
def test_missing_duplicate_misplaced_resized_or_modified_brand_rejected(change):
    with pytest.raises(AssertionError):
        _engineering_image_counts(_document(**change))


def test_undrawn_brand_resource_rejected():
    reader = _document()
    reader.pages[0][pypdf.generic.NameObject("/Contents")] = (
        pypdf.generic.DecodedStreamObject()
    )
    with pytest.raises(AssertionError, match="drawn exactly once"):
        _engineering_image_counts(reader)
