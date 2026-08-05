"""Build and rasterise the issued Sector user-manual QA fixture."""

from __future__ import annotations

import argparse
import functools
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import manual  # noqa: E402
from sector import __version__  # noqa: E402
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
_MANUAL_CROPS = (
    RasterCrop(
        "manual cover and contents",
        1,
        (0.10, 0.07, 0.90, 0.45),
        "ef560fe7132bc0611aa3a016d21363d373897e63fda2ab477f8f75e8cb10b07c",
    ),
    RasterCrop(
        "manual cover footer",
        1,
        (0.09, 0.94, 0.92, 0.98),
        "020cbe9bd6073e7a3ccb32718007d6cac3c1dc7b7b7f6c130c6568685537ca5d",
    ),
)


def validate_rendered_pages(pages):
    """Retain the fixture API while delegating to the shared raster gate."""
    return validate_raster_pages(pages, min_pages=6)


@functools.lru_cache(maxsize=1)
def build_fixture_pdf() -> bytes:
    return manual.build_manual_pdf_bytes(figures=True)


def validate_pdf_content(pdf: bytes) -> str:
    reader, page_texts = preflight_pdf(pdf, min_pages=6)
    text = "\n".join(page_texts)
    if "figure unavailable" in text.lower():
        raise AssertionError("the manual contains an unavailable-figure placeholder")
    for token in (
        "sqrt", "Cfrac", "Big", "varepsilon", "rightarrow",
        "qquadk", "quadf", "kN.m",
    ):
        if token.casefold() in text.casefold():
            raise AssertionError(
                f"the manual exposes an unrendered mathematics token: {token}"
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

    page_ids = {
        page.indirect_reference.idnum: number
        for number, page in enumerate(reader.pages, start=1)
    }
    contents_links = set()
    for reference in reader.pages[0].get("/Annots") or []:
        annotation = reference.get_object()
        destination = annotation.get("/Dest")
        if annotation.get("/Subtype") == "/Link" and destination:
            contents_links.add(page_ids.get(destination[0].idnum))
    part_pages = {
        page for title, page in outline_entries
        if title in manual._PART_SUMMARIES
    }
    if not part_pages.issubset(contents_links):
        raise AssertionError(
            "the visible manual contents does not link to every part"
        )

    for number, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        if f"Sector v{__version__} - user manual" not in page_text:
            raise AssertionError(f"page {number} is missing the manual footer")

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
        "Governing",
        "PDF report",
        "Every computed case",
        "Bridge brittle Method B",
        "DS/EN 1992-2:2005 6.1(109)-(110)",
        "Project-defined / uncited",
        "Part D - Reference",
    ):
        if expected not in text:
            raise AssertionError(f"expected manual content is missing: {expected}")
    return text


def write_fixture(output: pathlib.Path) -> list[pathlib.Path]:
    output.mkdir(parents=True, exist_ok=True)
    pdf = build_fixture_pdf()
    validate_pdf_content(pdf)
    pdf_path = output / "sector-manual-reference.pdf"
    pdf_path.write_bytes(pdf)
    pages = render_pdf(pdf)
    validate_raster_pages(
        pages, min_pages=6, furniture=MANUAL_FURNITURE
    )
    validate_crops(pages, _MANUAL_CROPS)
    paths = [pdf_path]
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
    print(f"Rendered {len(paths) - 1} manual pages to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
