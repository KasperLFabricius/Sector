"""Structural and raster preflight for issued Sector PDF publications."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import io
import math
import re
from types import MappingProxyType

from PIL import Image
import pypdf
import pypdfium2 as pdfium


_POINTS_PER_MM = 72.0 / 25.4
_A4_WIDTH = 210.0 * _POINTS_PER_MM
_A4_HEIGHT = 297.0 * _POINTS_PER_MM
_PAGE_TOLERANCE = 0.5
_LINK_TOLERANCE = 0.75
_PUBLICATION_ID = r"(?:\d+\.\d+|[A-Z]\d+-\d+)"
_PUBLICATION_REFERENCE = re.compile(
    rf"\bSee ((?:Table|Figure) {_PUBLICATION_ID})\.(?![\d-])"
)
_PUBLICATION_CAPTION = re.compile(
    rf"(?<!See )\b((?:Table|Figure) {_PUBLICATION_ID})\.(?![\d-])"
)

REPORT_FURNITURE = MappingProxyType({
    "header project": (0.09, 0.028, 0.72, 0.044),
    "header revision": (0.80, 0.028, 0.92, 0.044),
    "footer identity": (0.09, 0.952, 0.65, 0.967),
    "footer page number": (0.78, 0.952, 0.92, 0.967),
})

MANUAL_FURNITURE = MappingProxyType({
    "footer identity": (0.09, 0.952, 0.65, 0.967),
    "footer page number": (0.78, 0.952, 0.92, 0.967),
})


@dataclass(frozen=True, slots=True)
class PositionedReference:
    label: str
    page: int
    origin: float
    left: float
    right: float
    baseline: float


@dataclass(frozen=True, slots=True)
class RasterCrop:
    name: str
    page: int
    box: tuple[float, float, float, float]
    sha256: str


def validate_pdf_pages(reader: pypdf.PdfReader, *, min_pages=1) -> None:
    """Require content-bearing, unrotated physical A4 portrait pages."""
    if len(reader.pages) < min_pages:
        raise AssertionError(
            f"expected at least {min_pages} PDF pages, got {len(reader.pages)}"
        )
    for number, page in enumerate(reader.pages, start=1):
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        if (
            abs(width - _A4_WIDTH) > _PAGE_TOLERANCE
            or abs(height - _A4_HEIGHT) > _PAGE_TOLERANCE
        ):
            raise AssertionError(
                f"page {number} is not physical A4 portrait: "
                f"{width:.2f}x{height:.2f} pt"
            )
        if int(page.get("/Rotate", 0)) % 360:
            raise AssertionError(f"page {number} has rotated page geometry")
        if page.get_contents() is None:
            raise AssertionError(f"page {number} has no PDF content stream")


def validate_caption_colocation(page_texts: list[str]) -> tuple[str, ...]:
    """Require one exact same-page caption for every publication reference."""
    references = {}
    for number, page_text in enumerate(page_texts, start=1):
        for match in _PUBLICATION_REFERENCE.finditer(page_text):
            references.setdefault(match.group(1), []).append(number)
    if not references:
        raise AssertionError("the PDF contains no Figure/Table references")

    for label, pages in references.items():
        if len(pages) != 1:
            raise AssertionError(
                f"{label} has {len(pages)} references; expected exactly one"
            )
        caption = re.compile(rf"(?<!See ){re.escape(label)}\.(?![\d-])")
        caption_count = len(caption.findall(page_texts[pages[0] - 1]))
        if caption_count == 0:
            raise AssertionError(
                f"page {pages[0]} strands the reference to {label}"
            )
        if caption_count != 1:
            raise AssertionError(
                f"page {pages[0]} has {caption_count} exact captions for "
                f"{label}; expected one"
            )
    return tuple(sorted(references))


def _matrix_multiply(left, right):
    return (
        left[0] * right[0] + left[1] * right[2],
        left[0] * right[1] + left[1] * right[3],
        left[2] * right[0] + left[3] * right[2],
        left[2] * right[1] + left[3] * right[3],
        left[4] * right[0] + left[5] * right[2] + right[4],
        left[4] * right[1] + left[5] * right[3] + right[5],
    )


def _font_width(text, font, size):
    widths = font.get("/Widths")
    if widths is None:
        raise AssertionError(
            "publication reference uses a font without embedded widths"
        )
    widths = widths.get_object() if hasattr(widths, "get_object") else widths
    first = int(font.get("/FirstChar", 0))
    units = 0.0
    for character in text:
        index = ord(character) - first
        if not 0 <= index < len(widths):
            raise AssertionError(
                "publication reference character is absent from embedded widths"
            )
        units += float(widths[index])
    return units * float(size) / 1000.0


def positioned_references(page, page_number) -> tuple[PositionedReference, ...]:
    """Locate exact publication-label bounds from embedded PDF font widths."""
    found = []

    def visit(text, user_matrix, text_matrix, font, font_size):
        matches = tuple(_PUBLICATION_REFERENCE.finditer(text))
        if not matches:
            return
        if font is None:
            raise AssertionError(
                "publication reference has no positioned font identity"
            )
        matrix = _matrix_multiply(text_matrix, user_matrix)
        scale = math.hypot(matrix[0], matrix[1])
        if scale <= 0:
            raise AssertionError("publication reference has invalid text scale")
        for match in matches:
            label = match.group(1)
            left = matrix[4] + _font_width(
                text[:match.start(1)], font, font_size
            ) * scale
            right = left + _font_width(label, font, font_size) * scale
            found.append(PositionedReference(
                label, page_number, matrix[4], left, right, matrix[5]
            ))

    page.extract_text(visitor_text=visit)
    return tuple(found)


def positioned_captions(page) -> dict[str, tuple[tuple[float, float], ...]]:
    """Return caption text origins/baselines by exact publication identity."""
    found = {}

    def visit(text, user_matrix, text_matrix, _font, _font_size):
        matches = tuple(_PUBLICATION_CAPTION.finditer(text))
        if not matches:
            return
        matrix = _matrix_multiply(text_matrix, user_matrix)
        for match in matches:
            found.setdefault(match.group(1), []).append(
                (matrix[4], matrix[5])
            )

    page.extract_text(visitor_text=visit)
    return {
        label: tuple(positions) for label, positions in found.items()
    }


def _annotation_destination(annotation):
    destination = annotation.get("/Dest")
    if destination:
        return destination
    action = annotation.get("/A")
    if action and action.get("/S") == "/GoTo":
        return action.get("/D")
    return None


def _target_page_id(destination, named_destinations):
    if isinstance(destination, str):
        named = named_destinations.get(destination)
        if named is None:
            return None
        target = named.page
    else:
        if not destination:
            return None
        target = destination[0]
    return getattr(target, "idnum", None) or getattr(
        getattr(target, "indirect_reference", None), "idnum", None
    )


def _link_annotations(page):
    links = []
    for reference in page.get("/Annots") or []:
        annotation = reference.get_object()
        if annotation.get("/Subtype") == "/Link":
            links.append(annotation)
    return links


def validate_internal_destinations(reader: pypdf.PdfReader) -> int:
    """Require every internal link target to resolve inside this document."""
    page_ids = {
        page.indirect_reference.idnum
        for page in reader.pages
        if page.indirect_reference is not None
    }
    count = 0
    for number, page in enumerate(reader.pages, start=1):
        for annotation in _link_annotations(page):
            destination = _annotation_destination(annotation)
            if destination is None:
                continue
            count += 1
            target = _target_page_id(destination, reader.named_destinations)
            if target not in page_ids:
                raise AssertionError(
                    f"page {number} has an unresolved internal PDF link"
                )
    if count == 0:
        raise AssertionError("the PDF contains no internal destinations")
    return count


def _matching_links(reference, annotations):
    matches = []
    for annotation in annotations:
        destination = _annotation_destination(annotation)
        rectangle = annotation.get("/Rect")
        if destination is None or rectangle is None:
            continue
        left, bottom, right, top = (float(value) for value in rectangle)
        if (
            abs(left - reference.left) <= _LINK_TOLERANCE
            and abs(right - reference.right) <= _LINK_TOLERANCE
            and bottom - _LINK_TOLERANCE
            <= reference.baseline
            <= top + _LINK_TOLERANCE
        ):
            matches.append(annotation)
    return matches


def _destination_coordinates(destination):
    if isinstance(destination, str) or len(destination) < 4:
        return None
    if destination[1] != "/XYZ":
        return None
    try:
        return float(destination[2]), float(destination[3])
    except (TypeError, ValueError):
        return None


def validate_publication_links(
    reader: pypdf.PdfReader, page_texts: list[str]
) -> tuple[PositionedReference, ...]:
    """Bind every visible publication reference to its own same-page link."""
    positioned = []
    for number, (page, text) in enumerate(
        zip(reader.pages, page_texts), start=1
    ):
        expected = Counter(
            match.group(1) for match in _PUBLICATION_REFERENCE.finditer(text)
        )
        occurrences = positioned_references(page, number)
        actual = Counter(item.label for item in occurrences)
        if actual != expected:
            raise AssertionError(
                f"page {number} publication text cannot be positioned exactly"
            )

        links = _link_annotations(page)
        captions = positioned_captions(page)
        source_id = page.indirect_reference.idnum
        for occurrence in occurrences:
            matches = _matching_links(occurrence, links)
            if len(matches) != 1:
                raise AssertionError(
                    f"page {number} {occurrence.label} has {len(matches)} "
                    "matching link annotations; expected exactly one"
                )
            destination = _annotation_destination(matches[0])
            target_id = _target_page_id(
                destination, reader.named_destinations
            )
            if target_id != source_id:
                raise AssertionError(
                    f"page {number} {occurrence.label} does not link to its "
                    "same-page caption"
                )
            coordinates = _destination_coordinates(destination)
            caption_positions = captions.get(occurrence.label, ())
            if coordinates is None or not caption_positions:
                raise AssertionError(
                    f"page {number} {occurrence.label} has no exact caption "
                    "destination position"
                )
            destination_x, destination_y = coordinates
            vertical_match = (
                abs(destination_y - occurrence.baseline) <= _LINK_TOLERANCE
                or any(
                    -_LINK_TOLERANCE
                    <= destination_y - caption_y
                    <= 15.0
                    for _caption_x, caption_y in caption_positions
                )
            )
            if (
                abs(destination_x - occurrence.origin) > _LINK_TOLERANCE
                or not vertical_match
            ):
                raise AssertionError(
                    f"page {number} {occurrence.label} link does not target "
                    "its own caption position"
                )
        positioned.extend(occurrences)
    return tuple(positioned)


def preflight_pdf(pdf: bytes, *, min_pages=1):
    """Run the complete shared structural preflight and return reader/text."""
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    validate_pdf_pages(reader, min_pages=min_pages)
    page_texts = [page.extract_text() or "" for page in reader.pages]
    validate_caption_colocation(page_texts)
    validate_internal_destinations(reader)
    validate_publication_links(reader, page_texts)
    return reader, page_texts


def render_pdf(pdf: bytes, scale=1.5) -> list[Image.Image]:
    """Rasterise every PDF page through PDFium as an independent RGB image."""
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


def _pixels(image):
    getter = getattr(image, "get_flattened_data", image.getdata)
    return list(getter())


def _absolute_box(image, relative_box):
    left, top, right, bottom = relative_box
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        raise ValueError(f"invalid relative page box: {relative_box!r}")
    return (
        int(left * image.width),
        int(top * image.height),
        int(right * image.width),
        int(bottom * image.height),
    )


def validate_raster_pages(
    pages: list[Image.Image], *, min_pages=1, furniture=None
) -> None:
    """Reject blank, clipped, saturated or furniture-deficient raster pages."""
    if len(pages) < min_pages:
        raise AssertionError(
            f"expected at least {min_pages} raster pages, got {len(pages)}"
        )
    for number, image in enumerate(pages, start=1):
        width, height = image.size
        if not 0.70 < width / height < 0.72:
            raise AssertionError(
                f"page {number} raster is not A4 portrait: {width}x{height}"
            )
        grey = image.convert("L")
        pixels = _pixels(grey)
        ink = sum(value < 245 for value in pixels) / len(pixels)
        if not 0.002 < ink < 0.45:
            raise AssertionError(
                f"page {number} has implausible ink coverage {ink:.4f}"
            )

        edge = max(min(width, height) // 250, 2)
        edge_pixels = (
            _pixels(grey.crop((0, 0, width, edge)))
            + _pixels(grey.crop((0, height - edge, width, height)))
            + _pixels(grey.crop((0, 0, edge, height)))
            + _pixels(grey.crop((width - edge, 0, width, height)))
        )
        edge_ink = sum(value < 245 for value in edge_pixels)
        edge_ink /= len(edge_pixels)
        if edge_ink > 0.01:
            raise AssertionError(
                f"page {number} has content clipped against the page edge"
            )

        for label, relative_box in (furniture or {}).items():
            region = grey.crop(_absolute_box(image, relative_box))
            region_pixels = _pixels(region)
            region_ink = sum(value < 245 for value in region_pixels)
            region_ink /= len(region_pixels)
            if region_ink < 0.01:
                raise AssertionError(
                    f"page {number} has no visible {label}"
                )


def crop_sha256(image: Image.Image, relative_box) -> str:
    """Return a stable 4-bit fingerprint for one relative publication crop."""
    crop = image.crop(_absolute_box(image, relative_box)).convert("L")
    crop = crop.resize((80, 80), Image.Resampling.LANCZOS)
    quantised = bytes(value >> 4 for value in _pixels(crop))
    return hashlib.sha256(quantised).hexdigest()


def validate_crops(
    pages: list[Image.Image], crops: tuple[RasterCrop, ...]
) -> dict[str, str]:
    """Require all one-based stable publication-crop fingerprints."""
    actual = {}
    for crop in crops:
        if not 1 <= crop.page <= len(pages):
            raise AssertionError(
                f"crop {crop.name!r} selects missing page {crop.page}"
            )
        digest = crop_sha256(pages[crop.page - 1], crop.box)
        actual[crop.name] = digest
        if digest != crop.sha256:
            raise AssertionError(
                f"crop {crop.name!r} changed: expected {crop.sha256}, "
                f"got {digest}"
            )
    return actual
