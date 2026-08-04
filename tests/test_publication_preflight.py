"""Independent PR-11C2 / F-042 publication-preflight contracts."""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
import io
import pathlib
import sys
import warnings

from PIL import Image, ImageDraw
import pytest
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import manual  # noqa: E402
import publication_style  # noqa: E402
import sector_report  # noqa: E402
from tools.pdf_preflight import (  # noqa: E402
    CropSpec,
    crop_sha256,
    preflight_structure,
    validate_crop_hashes,
    validate_publication_labels,
)


def _linked_pdf(*, link=True) -> bytes:
    buffer = io.BytesIO()
    document = canvas.Canvas(buffer, pagesize=A4)
    document.bookmarkPage("table-1-10")
    document.drawString(72, 760, "See Table 1.10.")
    document.drawString(72, 730, "Table 1.10. Published evidence")
    if link:
        document.linkAbsolute(
            "Table 1.10",
            "table-1-10",
            Rect=(70, 755, 170, 775),
        )
    document.showPage()
    document.save()
    return buffer.getvalue()


def test_style_contract_is_immutable_and_reportlab_independent():
    source = pathlib.Path(publication_style.__file__).read_text(encoding="utf-8")
    imported = {
        alias.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not any(name == "reportlab" or name.startswith("reportlab.")
                   for name in imported)

    with pytest.raises(TypeError):
        publication_style.REPORT_PARAGRAPHS["body"] = object()
    with pytest.raises(FrozenInstanceError):
        publication_style.PALETTE.primary = "#000000"


def test_shared_style_specs_reconstruct_retained_report_and_manual_styles():
    report_styles = sector_report._styles()
    manual_styles = manual._manual_pdf_styles(
        sector_report,
        colors,
        ParagraphStyle,
        getSampleStyleSheet,
        TA_CENTER,
    )

    assert report_styles["h1"].fontSize == pytest.approx(
        publication_style.REPORT_PARAGRAPHS["h1"].font_size
    )
    assert report_styles["publication_caption"].spaceAfter == pytest.approx(
        publication_style.REPORT_PARAGRAPHS["publication_caption"].space_after
    )
    assert manual_styles["MH1"].spaceBefore == pytest.approx(
        publication_style.MANUAL_PARAGRAPHS["h1"].space_before
    )
    assert manual_styles["MPubCaption"].spaceAfter == pytest.approx(
        publication_style.MANUAL_PARAGRAPHS["publication_caption"].space_after
    )


@pytest.mark.parametrize("exporter", ["report", "manual"])
def test_exporters_suppress_only_exact_kaleido_server_warning(exporter):
    class _Figure:
        def _warn(self):
            warnings.warn_explicit(
                publication_style.KALEIDO_SERVER_WARNING,
                UserWarning,
                "plotly/io/_kaleido.py",
                400,
                module="plotly.io._kaleido",
            )
            warnings.warn_explicit(
                "unrelated Kaleido diagnostic",
                UserWarning,
                "plotly/io/_kaleido.py",
                401,
                module="plotly.io._kaleido",
            )

        def to_image(self, **_kwargs):
            self._warn()
            return b"report-png"

        def write_image(self, target, **_kwargs):
            self._warn()
            target.write(b"manual-png")

    figure = _Figure()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        if exporter == "report":
            result, timed_out = sector_report._fig_png(
                figure, 100, 100, timeout=2
            )
            assert result == b"report-png"
            assert timed_out is False
        else:
            result = manual._fig_to_png(lambda: figure, timeout=2)
            assert result == b"manual-png"

    assert [str(item.message) for item in caught] == [
        "unrelated Kaleido diagnostic"
    ]


@pytest.mark.parametrize(
    ("message", "module"),
    [
        (publication_style.KALEIDO_SERVER_WARNING, "sector.other_exporter"),
        ("another server-mode warning", "plotly.io._kaleido"),
    ],
)
def test_warning_boundary_keeps_other_sources_and_messages_visible(
    message, module
):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with publication_style.suppress_known_kaleido_server_warning():
            warnings.warn_explicit(
                message,
                UserWarning,
                "synthetic.py",
                1,
                module=module,
            )
    assert [str(item.message) for item in caught] == [message]


def test_report_and_manual_publication_labels_retain_exact_boundaries():
    assert validate_publication_labels([
        "See Table 1.10.\nTable 1.10. Report table",
        "See Figure A3-10.\nFigure A3-10. Manual figure",
    ]) == ("Figure A3-10", "Table 1.10")

    with pytest.raises(AssertionError, match="Table 1.1"):
        validate_publication_labels([
            "See Table 1.1.\nTable 1.10. Prefix-hostile caption",
        ])
    with pytest.raises(AssertionError, match="Figure A3-1"):
        validate_publication_labels([
            "See Figure A3-1.\nFigure A3-10. Prefix-hostile caption",
        ])


def test_structural_preflight_requires_resolved_internal_destination():
    reader, page_texts = preflight_structure(_linked_pdf(), min_pages=1)
    assert len(reader.pages) == 1
    assert "Table 1.10" in page_texts[0]

    with pytest.raises(AssertionError, match="internal destinations"):
        preflight_structure(_linked_pdf(link=False), min_pages=1)


def test_crop_fingerprint_rejects_localised_tampering():
    image = Image.new("RGB", (400, 600), "white")
    ImageDraw.Draw(image).rectangle((80, 100, 320, 300), fill="#1F3B66")
    box = (0.10, 0.10, 0.90, 0.60)
    digest = crop_sha256(image, box)
    spec = CropSpec("synthetic evidence", 1, box, digest)
    assert validate_crop_hashes([image], (spec,)) == {
        "synthetic evidence": digest
    }

    changed = image.copy()
    ImageDraw.Draw(changed).rectangle((180, 180, 240, 240), fill="black")
    with pytest.raises(AssertionError, match="synthetic evidence.*changed"):
        validate_crop_hashes([changed], (spec,))
