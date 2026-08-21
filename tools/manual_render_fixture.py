"""Build and rasterise the issued Sector user-manual QA fixture."""

from __future__ import annotations

import argparse
import functools
from html.parser import HTMLParser
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import manual  # noqa: E402

from app import manual_information_architecture as manual_ia  # noqa: E402
from app import project_io  # noqa: E402
from sector import __version__  # noqa: E402
from tools.manual_current_program_statements import (  # noqa: E402
    validate_current_manual_program_statements,
)
from tools.manual_current_schema_statements import (  # noqa: E402
    validate_current_manual_schema_statements,
)
from tools.manual_generated_html import manual_generated_html_text  # noqa: E402
from tools.manual_product_references import (  # noqa: E402
    validate_no_noncurrent_manual_product_references,
)
from tools.manual_schema_references import (  # noqa: E402
    validate_no_noncurrent_manual_schema_references,
)
from tools.publication_preflight import (  # noqa: E402
    MANUAL_FURNITURE,
    RasterCrop,
    preflight_pdf,
    render_pdf,
    validate_crops,
    validate_raster_pages,
)
from tools.report_render_fixture import validate_outline_destinations  # noqa: E402

_EXPECTED_FIGURE_COUNT = 16
_UNRENDERED_MATH_TOKENS = (
    "sqrt",
    "Cfrac",
    "Big",
    "varepsilon",
    "rightarrow",
    "qquadk",
    "quadf",
    "kN.m",
)
# The source revision printed above the contents changes with every commit and
# is already checked semantically and in PDF metadata.  Keep the stable visual
# fingerprint below that line so updating this digest cannot change its pixels.
_MANUAL_CROPS = (
    RasterCrop(
        "manual contents navigation",
        1,
        (0.09, 0.18, 0.92, 0.45),
        "2bc633db1eed1c2ae60d1728eefaea767f7734b06ae4d6f223d7cdd28b7e5452",
    ),
    RasterCrop(
        "manual cover footer",
        1,
        (0.09, 0.94, 0.92, 0.98),
        "effaf2610f335e36f89db76653fc22407c6cfc65b2a551865c935723b72dd911",
    ),
)


def validate_rendered_pages(pages):
    """Retain the fixture API while delegating to the shared raster gate."""
    return validate_raster_pages(pages, min_pages=6)


@functools.lru_cache(maxsize=1)
def build_fixture_pdf() -> bytes:
    return manual.build_manual_pdf_bytes(figures=True)


@functools.lru_cache(maxsize=1)
def build_fixture_html() -> bytes:
    return manual.build_manual_html_bytes()


class _HTMLInventory(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lang = None
        self.ids = []
        self.hrefs = []
        self.scripts = 0
        self.external_resources = []
        self.heading_levels = []
        self.table_header_scopes = []
        self.figure_alternatives = 0
        self.figcaptions = 0
        self.equations = 0

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "id" in values:
            self.ids.append(values["id"])
        if tag == "html":
            self.lang = values.get("lang")
        if tag == "a" and values.get("href"):
            self.hrefs.append(values["href"])
        if tag == "script":
            self.scripts += 1
        if tag in {"img", "script", "iframe", "link"}:
            target = values.get("src") or values.get("href")
            if target:
                self.external_resources.append((tag, target))
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.heading_levels.append(int(tag[1]))
        if tag == "th":
            self.table_header_scopes.append(values.get("scope"))
        if tag == "div" and "figure-alternative" in values.get("class", ""):
            if values.get("role") != "img" or not values.get("aria-label"):
                raise AssertionError("manual figure alternative is incomplete")
            self.figure_alternatives += 1
        if tag == "figcaption":
            self.figcaptions += 1
        if tag == "section" and "equation" in values.get("class", ""):
            self.equations += 1


def validate_html_content(html: bytes) -> str:
    """Validate the semantic HTML companion without starting a browser."""
    text = html.decode("utf-8")
    reference_text = manual_generated_html_text(text)
    flat_text = " ".join(reference_text.split())
    parser = _HTMLInventory()
    parser.feed(text)
    if not text.startswith("<!doctype html>") or parser.lang != "en":
        raise AssertionError("manual HTML lacks its HTML5 language contract")
    if parser.scripts or parser.external_resources:
        raise AssertionError("manual HTML is not self-contained and script-free")
    if len(parser.ids) != len(set(parser.ids)):
        raise AssertionError("manual HTML contains duplicate destinations")
    internal = [href[1:] for href in parser.hrefs if href.startswith("#")]
    if not internal or set(internal) - set(parser.ids):
        raise AssertionError("manual HTML contains an unresolved internal link")
    if [href for href in parser.hrefs if not href.startswith("#")]:
        raise AssertionError("manual HTML contains an external link")
    if not parser.heading_levels or parser.heading_levels[0] != 1:
        raise AssertionError("manual HTML lacks its top-level heading")
    if any(
        current > previous + 1
        for previous, current in zip(
            parser.heading_levels, parser.heading_levels[1:]
        )
    ):
        raise AssertionError("manual HTML skips a heading level")
    if set(parser.table_header_scopes) != {"col", "row"}:
        raise AssertionError("manual HTML table headers lack scope semantics")
    if parser.figure_alternatives != _EXPECTED_FIGURE_COUNT:
        raise AssertionError(
            "manual HTML figure-alternative inventory changed: "
            f"{parser.figure_alternatives}"
        )
    if parser.figcaptions < parser.figure_alternatives:
        raise AssertionError("manual HTML figure captions are incomplete")
    if parser.equations != 33:
        raise AssertionError(
            f"manual HTML equation inventory changed: {parser.equations}"
        )
    for destination in manual_ia.ALL_DESTINATIONS:
        if destination.anchor not in parser.ids:
            raise AssertionError(
                f"manual HTML destination is missing: {destination.anchor}"
            )
    for expected in (
        "Sector user manual",
        "Source revision:",
        "Start here",
        "Quick calculation",
        "Input reference",
        "Method reference",
        "Brief",
        "Standard",
        "Audit",
        "Limitations &amp; troubleshooting",
    ):
        if expected not in text:
            raise AssertionError(f"expected manual HTML content is missing: {expected}")
    _validate_current_manual_identity(
        flat_text,
        reference_text=reference_text,
    )
    return text


def _unrendered_math_token(text: str) -> str | None:
    """Return a standalone leaked math command without matching prose substrings."""
    visible_text = "\n".join(
        line
        for line in text.splitlines()
        if not line.lstrip().startswith("SECTOR-MATH[")
    )
    for token in _UNRENDERED_MATH_TOKENS:
        if re.search(
            rf"(?<![A-Za-z]){re.escape(token)}(?![A-Za-z])",
            visible_text,
            flags=re.IGNORECASE,
        ):
            return token
    return None


def _validate_current_manual_identity(
    flat_text: str,
    *,
    reference_text: str,
) -> None:
    """Apply every bounded current-only rule to visible manual text."""

    validate_current_manual_schema_statements(
        flat_text,
        project_schema=project_io.VERSION,
    )
    validate_no_noncurrent_manual_schema_references(
        reference_text,
        project_schema=project_io.VERSION,
    )
    validate_no_noncurrent_manual_product_references(
        reference_text,
        product_version=__version__,
    )
    validate_current_manual_program_statements(flat_text)


def validate_visible_contents_destinations(reader, outline_entries) -> None:
    """Require every Part link across the complete visible contents pages."""

    page_ids = {
        page.indirect_reference.idnum: number
        for number, page in enumerate(reader.pages, start=1)
    }
    part_pages = {
        page for title, page in outline_entries
        if title in manual._PART_SUMMARIES
    }
    if not part_pages:
        raise AssertionError("the manual outline contains no Parts")
    contents_links = set()
    first_part_page = min(part_pages)
    for contents_page in reader.pages[: first_part_page - 1]:
        for reference in contents_page.get("/Annots") or []:
            annotation = reference.get_object()
            destination = annotation.get("/Dest")
            if annotation.get("/Subtype") == "/Link" and destination:
                contents_links.add(page_ids.get(destination[0].idnum))
    if not part_pages.issubset(contents_links):
        raise AssertionError(
            "the visible manual contents does not link to every part"
        )


def validate_pdf_content(pdf: bytes) -> str:
    reader, page_texts = preflight_pdf(pdf, min_pages=6)
    text = "\n".join(page_texts)
    flat_text = " ".join(text.split())
    if "figure unavailable" in text.lower():
        raise AssertionError("the manual contains an unavailable-figure placeholder")
    _validate_current_manual_identity(
        flat_text,
        reference_text=text,
    )
    leaked_token = _unrendered_math_token(text)
    if leaked_token is not None:
        raise AssertionError(
            "the manual exposes an unrendered mathematics token: "
            f"{leaked_token}"
        )
    for symbol in (chr(0x221A), chr(0x2211), chr(0x03B8), chr(0x03B2)):
        if symbol not in text:
            raise AssertionError(
                f"the manual is missing rendered mathematics symbol U+{ord(symbol):04X}"
            )

    images = 0
    for page in reader.pages:
        resources = page.get("/Resources")
        if resources is None:
            continue
        xobjects = resources.get_object().get("/XObject")
        if xobjects is None:
            continue
        images += sum(
            reference.get_object().get("/Subtype") == "/Image"
            for reference in xobjects.get_object().values()
        )
    if images != _EXPECTED_FIGURE_COUNT:
        raise AssertionError(
            f"expected {_EXPECTED_FIGURE_COUNT} manual figures, found {images}"
        )

    outline_entries = validate_outline_destinations(reader)
    outline_titles = [title for title, _ in outline_entries]
    for part in manual._PART_SUMMARIES:
        if part not in outline_titles:
            raise AssertionError(f"manual bookmark is missing: {part}")
    if len(outline_titles) < 25:
        raise AssertionError(
            f"expected detailed manual bookmarks, found {len(outline_titles)}"
        )
    required_titles = {
        *(item.heading for item in manual_ia.INPUT_STAGES),
        *(item.heading for item in manual_ia.RESULT_VIEWS),
        *(item.heading for item in manual_ia.METHODS),
    }
    missing_titles = required_titles - set(outline_titles)
    if missing_titles:
        raise AssertionError(
            "manual detailed bookmarks are missing: "
            + ", ".join(sorted(missing_titles))
        )

    metadata = reader.metadata
    if metadata.title != f"Sector user manual v{__version__}":
        raise AssertionError("manual PDF title metadata changed")
    if metadata.author != manual.APP_AUTHOR:
        raise AssertionError("manual PDF author metadata changed")
    if "input reference" not in str(metadata.subject or "").lower():
        raise AssertionError("manual PDF subject metadata is incomplete")
    if "structural engineering" not in str(
        metadata.get("/Keywords", "")
    ).lower():
        raise AssertionError("manual PDF keyword metadata is incomplete")
    if reader.trailer["/Root"].get("/Lang") != "en":
        raise AssertionError("manual PDF language metadata changed")

    validate_visible_contents_destinations(reader, outline_entries)

    for number, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        if f"Sector v{__version__} - user manual" not in page_text:
            raise AssertionError(f"page {number} is missing the manual footer")
        if "Rev:" not in page_text:
            raise AssertionError(f"page {number} is missing the manual revision")

    for expected in (
        "Sector user manual",
        "Sweco Danmark A/S",
        "Contents",
        "Plastic / capacity",
        "Serviceability: cracking and crack width",
        "Grouped fatigue",
        "Fatigue Results",
        "Partial factor on the cyclic fatigue action",
        "Miner damage",
        "bounded concrete-search result",
        "Results overview",
        "Reinforcement detailing",
        "Shear and torsion reinforcement",
        "Anchorage is assumed",
        "Bulk assignments",
        "one fully expanded governing row for each stable check family",
        "PDF report",
        "Worked numerical derivations are limited to the globally governing or "
        "extremal calculation in each family",
        "Editable table",
        "Plastic/capacity and Elastic action fields",
        "accept either a dot or comma as the decimal separator",
        "Blank ordinary action cells are normalised to canonical zero",
        "Optional-null fields remain absent rather than becoming zero",
        "retains the entered numeric precision internally",
        "published project-adoption basis",
        "no Danish National Annex",
        "confinement enhancement is not included or assessed",
        "DS/EN 1992-2:2005/AC:2008",
        "6.106",
        "Project-defined / uncited",
        "Part D - Reference",
    ):
        if expected not in text and expected not in flat_text:
            raise AssertionError(f"expected manual content is missing: {expected}")
    return text


def write_fixture(output: pathlib.Path) -> list[pathlib.Path]:
    output.mkdir(parents=True, exist_ok=True)
    pdf = build_fixture_pdf()
    validate_pdf_content(pdf)
    html = build_fixture_html()
    validate_html_content(html)
    pdf_path = output / "sector-manual-reference.pdf"
    pdf_path.write_bytes(pdf)
    html_path = output / "sector-manual-reference.html"
    html_path.write_bytes(html)
    pages = render_pdf(pdf)
    validate_raster_pages(
        pages, min_pages=6, furniture=MANUAL_FURNITURE
    )
    validate_crops(pages, _MANUAL_CROPS)
    paths = [pdf_path, html_path]
    for index, page in enumerate(pages, start=1):
        path = output / f"sector-manual-page-{index:02d}.png"
        page.save(path, format="PNG")
        paths.append(path)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    paths = write_fixture(args.output)
    print(
        f"Rendered {len(paths) - 2} manual pages and accessible HTML to "
        f"{args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
