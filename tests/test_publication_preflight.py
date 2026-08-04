"""Independent F042 publication-style and PDF-preflight contracts."""

from __future__ import annotations

import io
import pathlib
import sys
from types import SimpleNamespace
import warnings

from PIL import Image, ImageDraw
import pytest
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import manual  # noqa: E402
import publication_style  # noqa: E402
import sector_report  # noqa: E402
from tools.pdf_preflight import (  # noqa: E402
    PdfPreflightProfile,
    crop_difference_hash,
    hash_distance,
    validate_pdf_structure,
    validate_rendered_pages,
)


def _pdf(*texts, pagesize=A4, font_size=8.0):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=pagesize,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )
    style = ParagraphStyle("preflight-body", fontSize=font_size, leading=10)
    doc.build([Paragraph(text, style) for text in texts])
    return buffer.getvalue()


def _raster_page(*, body=True):
    image = Image.new("RGB", (600, 848), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((60, 24, 420, 31), fill="black")
    draw.rectangle((60, 810, 360, 817), fill="black")
    if body:
        draw.rectangle((90, 110, 510, 150), fill="black")
    return image


def test_report_and_manual_consume_the_shared_immutable_style():
    style = publication_style.STYLE
    assert style.report_margins_mm == (20.0, 20.0, 25.0, 20.0)
    assert style.manual_margins_mm == (22.0, 22.0, 20.0, 20.0)
    assert style.minimum_table_size == pytest.approx(7.2)
    assert style.spacing(4) == pytest.approx(4)
    with pytest.raises(ValueError, match="outside the grid"):
        style.spacing(5)
    assert sector_report._MIN_REPORT_TABLE_FONT == style.minimum_table_size
    assert sector_report._styles()["body"].fontSize == style.body_size

    manual_styles = manual._manual_pdf_styles(
        sector_report,
        sector_report.colors,
        sector_report.ParagraphStyle,
        sector_report.getSampleStyleSheet,
        sector_report.TA_CENTER,
    )
    assert manual_styles["MBody"].fontSize == style.body_size
    assert manual_styles["MPubCaption"].fontSize == style.caption_size


def test_page_break_is_inert_only_at_an_automatically_fresh_frame():
    page_break = sector_report._NonBlankPageBreak()
    frame = SimpleNamespace(_atTop=True)
    page_break.canv = SimpleNamespace(
        _doctemplate=SimpleNamespace(frame=frame)
    )
    assert page_break.wrap(100, 200) == (0, 0)

    frame._atTop = False
    width, height = page_break.wrap(100, 200)
    assert width == 100
    assert height == pytest.approx(200)


@pytest.mark.parametrize("exporter", ["report", "manual"])
def test_exact_kaleido_server_warning_is_suppressed_but_siblings_survive(exporter):
    unrelated = "independent export warning remains visible"

    class _Figure:
        def to_image(self, **_kwargs):
            warnings.warn(
                publication_style.KALEIDO_SERVER_KOPTS_WARNING,
                UserWarning,
            )
            warnings.warn(unrelated, UserWarning)
            return b"report-png"

        def write_image(self, buffer, **_kwargs):
            warnings.warn(
                publication_style.KALEIDO_SERVER_KOPTS_WARNING,
                UserWarning,
            )
            warnings.warn(unrelated, UserWarning)
            buffer.write(b"manual-png")

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        if exporter == "report":
            png, timed_out = sector_report._fig_png(_Figure(), 20, 20)
            assert png == b"report-png"
            assert timed_out is False
        else:
            assert manual._fig_to_png(lambda: _Figure()) == b"manual-png"

    messages = [str(item.message) for item in captured]
    assert publication_style.KALEIDO_SERVER_KOPTS_WARNING not in messages
    assert messages == [unrelated]


def test_structural_preflight_accepts_owned_a4_numeric_publication():
    pdf = _pdf("See Table 1.1. Table 1.1. Demand 125.0 %")
    texts = validate_pdf_structure(
        pdf,
        PdfPreflightProfile(required_numeric_tokens=("125.0 %",)),
    )
    assert len(texts) == 1


@pytest.mark.parametrize(
    ("pdf", "message"),
    [
        (_pdf("ordinary publication body", pagesize=LETTER), "MediaBox"),
        (_pdf("See Table 1.1. publication reference only"), "strands"),
        (_pdf("undersized ordinary publication sentence", font_size=6.5),
         "below 7.2 pt"),
        (_pdf("Source: stranded at page end"), "source/reference"),
    ],
)
def test_structural_preflight_rejects_adversarial_artifacts(pdf, message):
    with pytest.raises(AssertionError, match=message):
        validate_pdf_structure(pdf, PdfPreflightProfile())


def test_structural_preflight_rejects_missing_or_split_numeric_identity():
    pdf = _pdf("Demand 125.0 percent")
    with pytest.raises(AssertionError, match="numeric token"):
        validate_pdf_structure(
            pdf,
            PdfPreflightProfile(required_numeric_tokens=("125.0 %",)),
        )


def test_raster_preflight_rejects_furniture_only_page_and_clipped_edge():
    validate_rendered_pages([_raster_page()], minimum_pages=1)

    with pytest.raises(AssertionError, match="publication body"):
        validate_rendered_pages([_raster_page(body=False)], minimum_pages=1)

    clipped = _raster_page()
    ImageDraw.Draw(clipped).rectangle((0, 250, 8, 500), fill="black")
    with pytest.raises(AssertionError, match="clipped"):
        validate_rendered_pages([clipped], minimum_pages=1)


def test_crop_hash_is_stable_and_sensitive_to_visible_change():
    page = _raster_page()
    same = page.copy()
    changed = page.copy()
    ImageDraw.Draw(changed).rectangle((300, 300, 500, 500), fill="black")
    box = (0.05, 0.05, 0.95, 0.95)
    original_hash = crop_difference_hash(page, box)
    assert hash_distance(original_hash, crop_difference_hash(same, box)) == 0
    assert hash_distance(original_hash, crop_difference_hash(changed, box)) > 0
