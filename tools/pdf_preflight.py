"""Structural and raster preflight for issued Sector PDF artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import io
import re

from PIL import Image
import pypdf
import pypdfium2 as pdfium
from reportlab.lib.pagesizes import A4


_PUBLICATION_REFERENCE = re.compile(r"\bSee ((?:Table|Figure) \d+\.\d+)\.")
_SOURCE_LINE = re.compile(r"^(?:Source|Project basis|Reference):", re.IGNORECASE)
_FURNITURE_LINE = re.compile(
    r"^(?:Project:|Rev:|Sector (?:v)?0\.\d+|Page \d+ of \d+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PdfPreflightProfile:
    """Frozen artifact-specific limits over the shared PDF checks."""

    minimum_pages: int = 1
    minimum_body_font_size: float = 7.2
    required_numeric_tokens: tuple[str, ...] = ()
    require_publication_pairs: bool = True


def _reader(pdf: bytes) -> pypdf.PdfReader:
    if not isinstance(pdf, bytes) or not pdf.startswith(b"%PDF"):
        raise AssertionError("artifact is not a PDF byte stream")
    return pypdf.PdfReader(io.BytesIO(pdf))


def _normalise_text(text: str) -> str:
    return " ".join(text.split())


def _semantic_lines(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not _FURNITURE_LINE.match(line.strip())
    ]


def _validate_font_runs(page, number: int, minimum: float) -> None:
    failures = []

    def visit(text, _cm, _tm, _font, font_size):
        token = _normalise_text(text)
        if not token or float(font_size) + 0.01 >= minimum:
            return
        # ReportLab legitimately scales compact sub/superscript fragments. A
        # normal word, sentence or spaced number below the owned minimum is not
        # such a fragment and fails closed.
        if len(token) > 12 or any(char.isspace() for char in text.strip()):
            failures.append((token, float(font_size)))

    page.extract_text(visitor_text=visit)
    if failures:
        token, size = failures[0]
        raise AssertionError(
            f"page {number} publishes body text below {minimum:g} pt: "
            f"{token!r} at {size:g} pt"
        )


def validate_pdf_structure(pdf: bytes, profile: PdfPreflightProfile) -> list[str]:
    """Validate page geometry, text size, references and numeric identity."""

    reader = _reader(pdf)
    if len(reader.pages) < profile.minimum_pages:
        raise AssertionError(
            f"expected at least {profile.minimum_pages} pages, got "
            f"{len(reader.pages)}"
        )

    page_texts = []
    for number, page in enumerate(reader.pages, start=1):
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        if abs(width - A4[0]) > 0.5 or abs(height - A4[1]) > 0.5:
            raise AssertionError(
                f"page {number} MediaBox is not A4 portrait: "
                f"{width:.2f}x{height:.2f} pt"
            )
        text = page.extract_text() or ""
        page_texts.append(text)
        _validate_font_runs(page, number, profile.minimum_body_font_size)

        lines = _semantic_lines(text)
        if lines and _SOURCE_LINE.match(lines[-1]):
            raise AssertionError(
                f"page {number} strands a source/reference line at the page end"
            )
        if profile.require_publication_pairs:
            for match in _PUBLICATION_REFERENCE.finditer(text):
                label = match.group(1)
                if text.count(label) < 2:
                    raise AssertionError(
                        f"page {number} strands {label!r} away from its object"
                    )

    complete_text = _normalise_text("\n".join(page_texts))
    for token in profile.required_numeric_tokens:
        if _normalise_text(token) not in complete_text:
            raise AssertionError(
                f"required numeric token is missing or split: {token!r}"
            )
    return page_texts


def render_pdf(pdf: bytes, scale: float = 1.5) -> list[Image.Image]:
    """Rasterise all pages through PDFium as independent RGB images."""

    document = pdfium.PdfDocument(pdf)
    pages = []
    try:
        for index in range(len(document)):
            page = document[index]
            bitmap = page.render(scale=scale)
            try:
                pages.append(bitmap.to_pil().convert("RGB").copy())
            finally:
                bitmap.close()
                page.close()
    finally:
        document.close()
    return pages


def _pixels(image: Image.Image) -> list[int]:
    getter = getattr(image, "get_flattened_data", image.getdata)
    return list(getter())


def _ink_fraction(image: Image.Image, threshold: int = 245) -> float:
    pixels = _pixels(image.convert("L"))
    return sum(value < threshold for value in pixels) / max(len(pixels), 1)


def validate_rendered_pages(
    pages: list[Image.Image],
    *,
    require_document_control: bool = False,
    minimum_pages: int = 6,
) -> None:
    """Reject blank bodies, clipped glyphs and malformed raster pages."""

    if len(pages) < minimum_pages:
        raise AssertionError(f"expected at least {minimum_pages} pages, got {len(pages)}")

    for number, image in enumerate(pages, start=1):
        width, height = image.size
        ratio = width / height
        if not 0.70 < ratio < 0.72:
            raise AssertionError(f"page {number} is not A4 portrait: {width}x{height}")

        fraction = _ink_fraction(image)
        if not 0.002 < fraction < 0.45:
            raise AssertionError(
                f"page {number} has implausible ink coverage {fraction:.4f}"
            )

        # Exclude the report header/footer furniture. A page containing only
        # those repeated marks is blank for engineering-publication purposes.
        body = image.crop((
            int(0.06 * width), int(0.055 * height),
            int(0.94 * width), int(0.945 * height),
        ))
        body_fraction = _ink_fraction(body, threshold=250)
        if body_fraction < 0.00035:
            raise AssertionError(f"page {number} has no visible publication body")

        grey = image.convert("L")
        edge = max(min(width, height) // 125, 3)
        edge_pixels = (
            _pixels(grey.crop((0, 0, width, edge)))
            + _pixels(grey.crop((0, height - edge, width, height)))
            + _pixels(grey.crop((0, 0, edge, height)))
            + _pixels(grey.crop((width - edge, 0, width, height)))
        )
        edge_dark = sum(value < 245 for value in edge_pixels) / len(edge_pixels)
        if edge_dark > 0.01:
            raise AssertionError(
                f"page {number} has glyphs or rules clipped at the page edge"
            )

        if require_document_control:
            furniture_regions = {
                "header project": (0.09, 0.028, 0.72, 0.044),
                "header revision": (0.80, 0.028, 0.92, 0.044),
                "footer identity": (0.09, 0.952, 0.65, 0.967),
                "footer page number": (0.78, 0.952, 0.92, 0.967),
            }
            for label, (x0, y0, x1, y1) in furniture_regions.items():
                region = grey.crop((
                    int(x0 * width), int(y0 * height),
                    int(x1 * width), int(y1 * height),
                ))
                if _ink_fraction(region) < 0.01:
                    raise AssertionError(f"page {number} has no visible {label}")


def crop_difference_hash(
    image: Image.Image, box: tuple[float, float, float, float]
) -> str:
    """Return a compact stable visual signature for a normalized page crop."""

    width, height = image.size
    crop = image.crop((
        int(box[0] * width), int(box[1] * height),
        int(box[2] * width), int(box[3] * height),
    )).convert("L").resize((9, 8))
    values = _pixels(crop)
    bits = []
    for row in range(8):
        start = row * 9
        bits.extend(
            values[start + column] > values[start + column + 1]
            for column in range(8)
        )
    value = sum(int(bit) << index for index, bit in enumerate(bits))
    return f"{value:016x}"


def hash_distance(left: str, right: str) -> int:
    """Return the Hamming distance between two crop difference hashes."""

    return (int(left, 16) ^ int(right, 16)).bit_count()
