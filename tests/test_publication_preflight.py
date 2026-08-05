"""Independent PR-11C2B structural and raster publication contracts."""

from __future__ import annotations

import io
import pathlib
import sys

from PIL import Image, ImageDraw
import pypdf
import pytest
from reportlab.lib.pagesizes import A4, A5
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import sector_report  # noqa: E402
from tools.publication_preflight import (  # noqa: E402
    RasterCrop,
    crop_sha256,
    preflight_pdf,
    validate_caption_colocation,
    validate_crops,
    validate_pdf_pages,
    validate_publication_links,
    validate_raster_pages,
)


def _publication_pdf(
    *, pagesize=A4, publication_link=True, same_page_target=True,
    own_target=True
):
    buffer = io.BytesIO()
    styles = sector_report._styles()
    document = SimpleDocTemplate(
        buffer,
        pagesize=pagesize,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )
    if publication_link:
        target = "published" if own_target else "unrelated"
        reference = (
            f'See <link href="#{target}">Table 1.10</link>.'
        )
    else:
        reference = "See Table 1.10."
    caption_anchor = '<a name="published"/>' if same_page_target else ""
    flow = [
        Paragraph(reference, styles["publication_ref"]),
        Paragraph(
            f"{caption_anchor}<b>Table 1.10.</b> Published evidence",
            styles["publication_caption"],
        ),
        Paragraph(
            'An <link href="#unrelated">unrelated internal link</link>.',
            styles["body"],
        ),
        Paragraph('<a name="unrelated"/>Unrelated target', styles["body"]),
    ]
    if not same_page_target:
        flow.extend((
            PageBreak(),
            Paragraph('<a name="published"/>Wrong-page target', styles["body"]),
        ))
    document.build(flow)
    return buffer.getvalue()


def test_physical_a4_identity_rejects_same_ratio_a5_and_blank_stream():
    valid = pypdf.PdfReader(io.BytesIO(_publication_pdf()))
    validate_pdf_pages(valid, min_pages=1)

    a5 = pypdf.PdfReader(io.BytesIO(_publication_pdf(pagesize=A5)))
    with pytest.raises(AssertionError, match="physical A4"):
        validate_pdf_pages(a5, min_pages=1)

    buffer = io.BytesIO()
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=A4[0], height=A4[1])
    writer.write(buffer)
    blank = pypdf.PdfReader(io.BytesIO(buffer.getvalue()))
    with pytest.raises(AssertionError, match="content stream"):
        validate_pdf_pages(blank, min_pages=1)


def test_exact_report_and_manual_label_boundaries_are_colocated():
    assert validate_caption_colocation([
        "See Table 1.10.\nTable 1.10. Report table",
        "See Figure A3-10.\nFigure A3-10. Manual figure",
    ]) == ("Figure A3-10", "Table 1.10")

    with pytest.raises(AssertionError, match="strands.*Table 1.1"):
        validate_caption_colocation([
            "See Table 1.1.\nTable 1.10. Prefix-hostile caption",
        ])
    with pytest.raises(AssertionError, match="strands.*Figure A3-1"):
        validate_caption_colocation([
            "See Figure A3-1.\nFigure A3-10. Prefix-hostile caption",
        ])
    with pytest.raises(AssertionError, match="2 exact captions"):
        validate_caption_colocation([
            "See Table 2.1.\nTable 2.1. First\nTable 2.1. Duplicate",
        ])


def test_each_publication_reference_is_bound_to_its_own_link_rectangle():
    reader, texts = preflight_pdf(_publication_pdf(), min_pages=1)
    positioned = validate_publication_links(reader, texts)
    assert [(item.page, item.label) for item in positioned] == [
        (1, "Table 1.10")
    ]

    # The unrelated internal link deliberately keeps the aggregate link count
    # high enough. It must not mask the missing Table link.
    with pytest.raises(AssertionError, match="Table 1.10.*0 matching link"):
        preflight_pdf(
            _publication_pdf(publication_link=False), min_pages=1
        )


def test_publication_link_must_target_its_same_page_caption():
    with pytest.raises(AssertionError, match="same-page caption"):
        preflight_pdf(
            _publication_pdf(same_page_target=False), min_pages=1
        )
    with pytest.raises(AssertionError, match="own caption position"):
        preflight_pdf(_publication_pdf(own_target=False), min_pages=1)


def test_raster_furniture_and_crop_fingerprint_reject_tampering():
    image = Image.new("RGB", (595, 842), "white")
    drawing = ImageDraw.Draw(image)
    drawing.rectangle((80, 80, 320, 330), fill="#1F3B66")
    drawing.rectangle((60, 800, 250, 812), fill="#5A5A5A")
    furniture = {"footer": (0.09, 0.94, 0.50, 0.98)}
    validate_raster_pages([image], min_pages=1, furniture=furniture)

    box = (0.10, 0.08, 0.90, 0.50)
    digest = crop_sha256(image, box)
    crop = RasterCrop("synthetic publication", 1, box, digest)
    assert validate_crops([image], (crop,)) == {
        "synthetic publication": digest
    }

    changed = image.copy()
    ImageDraw.Draw(changed).rectangle((180, 170, 250, 250), fill="black")
    with pytest.raises(AssertionError, match="synthetic publication.*changed"):
        validate_crops([changed], (crop,))

    with pytest.raises(AssertionError, match="visible footer"):
        validate_raster_pages(
            [image], min_pages=1,
            furniture={"footer": (0.70, 0.94, 0.90, 0.98)},
        )
