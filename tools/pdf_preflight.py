"""Shared structural and raster preflight for issued Sector PDFs."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import re

from PIL import Image
import pypdf
import pypdfium2 as pdfium


_PUBLICATION_ID = r"(?:\d+\.\d+|[A-Z]\d+-\d+)"
_PUBLICATION_REFERENCE = re.compile(
    rf"\bSee ((?:Table|Figure) {_PUBLICATION_ID})\.(?![\d-])"
)

REPORT_FURNITURE_REGIONS = {
    "header project": (0.09, 0.028, 0.72, 0.044),
    "header revision": (0.80, 0.028, 0.92, 0.044),
    "footer identity": (0.09, 0.952, 0.65, 0.967),
    "footer page number": (0.78, 0.952, 0.92, 0.967),
}

MANUAL_FURNITURE_REGIONS = {
    "footer identity": (0.09, 0.952, 0.65, 0.967),
    "footer page number": (0.78, 0.952, 0.92, 0.967),
}


@dataclass(frozen=True)
class CropSpec:
    name: str
    page: int
    box: tuple[float, float, float, float]
    sha256: str


def validate_pdf_structure(reader: pypdf.PdfReader, *, min_pages=1) -> None:
    """Reject malformed, empty, non-A4 or content-stream-free documents."""
    if len(reader.pages) < min_pages:
        raise AssertionError(
            f"expected at least {min_pages} PDF pages, got {len(reader.pages)}"
        )
    for number, page in enumerate(reader.pages, start=1):
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        if height <= 0 or not 0.70 < width / height < 0.72:
            raise AssertionError(
                f"page {number} is not A4 portrait: {width:.2f}x{height:.2f}"
            )
        if page.get_contents() is None:
            raise AssertionError(f"page {number} has no PDF content stream")


def validate_publication_labels(page_texts: list[str]) -> tuple[str, ...]:
    """Pin exact report and manual reference/caption identity and colocation."""
    references = {}
    for number, page_text in enumerate(page_texts, start=1):
        for match in _PUBLICATION_REFERENCE.finditer(page_text):
            references.setdefault(match.group(1), []).append(number)
    if not references:
        raise AssertionError("the PDF contains no published Figure/Table reference")

    for label, pages in references.items():
        if len(pages) != 1:
            raise AssertionError(
                f"{label} has {len(pages)} references; expected exactly one"
            )
        page_text = page_texts[pages[0] - 1]
        caption = re.compile(rf"(?<!See ){re.escape(label)}\.(?![\d-])")
        if caption.search(page_text) is None:
            raise AssertionError(
                f"page {pages[0]} strands the reference to {label}"
            )
    return tuple(sorted(references))


def validate_internal_links(
    reader: pypdf.PdfReader, *, minimum_destinations=1
) -> int:
    """Require internal link destinations to resolve to pages in this PDF."""
    page_ids = {
        page.indirect_reference.idnum for page in reader.pages
        if page.indirect_reference is not None
    }
    destinations = 0
    for number, page in enumerate(reader.pages, start=1):
        for reference in page.get("/Annots") or []:
            annotation = reference.get_object()
            if annotation.get("/Subtype") != "/Link":
                continue
            destination = annotation.get("/Dest")
            if not destination:
                continue
            destinations += 1
            target = destination[0]
            if getattr(target, "idnum", None) not in page_ids:
                raise AssertionError(
                    f"page {number} has an unresolved internal PDF link"
                )
    if destinations < minimum_destinations:
        raise AssertionError(
            f"expected at least {minimum_destinations} internal destinations, "
            f"found {destinations}"
        )
    return destinations


def preflight_structure(pdf: bytes, *, min_pages=1):
    """Return reader/text after the complete shared structural preflight."""
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    validate_pdf_structure(reader, min_pages=min_pages)
    page_texts = [page.extract_text() or "" for page in reader.pages]
    labels = validate_publication_labels(page_texts)
    validate_internal_links(reader, minimum_destinations=len(labels))
    return reader, page_texts


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


def validate_rendered_pages(
    pages: list[Image.Image],
    *,
    require_document_control: bool = False,
    furniture_regions=None,
) -> None:
    """Reject blank, clipped, malformed or furniture-deficient pages."""
    if len(pages) < 6:
        raise AssertionError(f"expected at least 6 report pages, got {len(pages)}")
    if require_document_control and furniture_regions is None:
        furniture_regions = REPORT_FURNITURE_REGIONS

    for number, image in enumerate(pages, start=1):
        width, height = image.size
        ratio = width / height
        if not 0.70 < ratio < 0.72:
            raise AssertionError(f"page {number} is not A4 portrait: {width}x{height}")

        grey = image.convert("L")
        pixels = _pixels(grey)
        dark = sum(value < 245 for value in pixels)
        fraction = dark / len(pixels)
        if not 0.002 < fraction < 0.45:
            raise AssertionError(
                f"page {number} has implausible ink coverage {fraction:.4f}"
            )

        bbox = Image.eval(
            Image.frombytes("L", grey.size, bytes(
                255 if value < 250 else 0 for value in pixels
            )),
            lambda value: value,
        ).getbbox()
        if bbox is None:
            raise AssertionError(f"page {number} rendered blank")

        edge = max(min(width, height) // 250, 2)
        edge_pixels = (
            _pixels(grey.crop((0, 0, width, edge)))
            + _pixels(grey.crop((0, height - edge, width, height)))
            + _pixels(grey.crop((0, 0, edge, height)))
            + _pixels(grey.crop((width - edge, 0, width, height)))
        )
        edge_dark = sum(value < 245 for value in edge_pixels) / len(edge_pixels)
        if edge_dark > 0.01:
            raise AssertionError(
                f"page {number} has content clipped against the page edge"
            )

        for label, relative_box in (furniture_regions or {}).items():
            box = _absolute_box(image, relative_box)
            region_pixels = _pixels(grey.crop(box))
            region_dark = sum(value < 245 for value in region_pixels)
            region_dark /= len(region_pixels)
            if region_dark < 0.01:
                raise AssertionError(f"page {number} has no visible {label}")


def _absolute_box(image, box):
    left, top, right, bottom = box
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        raise ValueError(f"invalid relative crop box: {box!r}")
    return (
        int(left * image.width), int(top * image.height),
        int(right * image.width), int(bottom * image.height),
    )


def crop_sha256(image: Image.Image, box) -> str:
    """Return a stable 4-bit greyscale fingerprint of one relative page crop."""
    crop = image.crop(_absolute_box(image, box)).convert("L")
    crop = crop.resize((96, 96), Image.Resampling.LANCZOS)
    quantised = bytes(value // 16 for value in _pixels(crop))
    return hashlib.sha256(quantised).hexdigest()


def validate_crop_hashes(
    pages: list[Image.Image], specs: tuple[CropSpec, ...]
) -> dict[str, str]:
    """Validate named one-based-page crop fingerprints."""
    actual = {}
    for spec in specs:
        if not 1 <= spec.page <= len(pages):
            raise AssertionError(
                f"crop {spec.name!r} selects missing page {spec.page}"
            )
        digest = crop_sha256(pages[spec.page - 1], spec.box)
        actual[spec.name] = digest
        if digest != spec.sha256:
            raise AssertionError(
                f"crop {spec.name!r} changed: expected {spec.sha256}, got {digest}"
            )
    return actual
