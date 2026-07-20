"""Build and rasterise a stable Sector report QA fixture.

The normal report tests inspect PDF text. This fixture also passes every page
through PDFium so CI exercises the artifact an engineer actually opens. The
real Plotly/Kaleido exporter is retained so the gate also fails when the figures
an engineer expects in the issued report cannot be produced.
"""

from __future__ import annotations

import argparse
import datetime
import functools
import io
import pathlib
import sys

from PIL import Image
import pypdf
import pypdfium2 as pdfium

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import sector_report  # noqa: E402
from sector import __version__  # noqa: E402
from sector.materials import Concrete, MildSteel  # noqa: E402

# Geometry, concrete law, steel law, plastic interaction, plastic state and
# elastic state and SLS strain profile. An intentional fixture change must update
# this explicit contract.
_EXPECTED_FIGURE_COUNT = 7


class _FixedDateTime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 7, 19, 12, 0, 0)
        return value if tz is None else value.replace(tzinfo=tz)


def _inputs() -> dict:
    return {
        "mode": "Both",
        "outer": [(-0.1, -0.15), (0.1, -0.15), (0.1, 0.15), (-0.1, 0.15)],
        "holes": [],
        "bars": [(0.0, -0.12, 500.0)],
        "tendons": [],
        "concrete": Concrete(fck=30.0, gamma_c=1.5, curve=2),
        "steel": MildSteel(
            fytk=500.0,
            fyck=500.0,
            futk=500.0,
            eut=0.05,
            gamma_y=1.15,
            curve=2,
        ),
        "prestress": None,
        "P_pl": 0.0,
        "Mx_pl": 100.0,
        "My_pl": 0.0,
        "P_el_l": 0.0,
        "Mx_el_l": 80.0,
        "My_el_l": 0.0,
        "P_el_s": 0.0,
        "Mx_el_s": 20.0,
        "My_el_s": 0.0,
        "nl": 15.0,
        "ns": 6.0,
        "conc_Ec": 33.0,
        "sls_fctm": 2.9,
        "sls_cw": True,
        "sls_wk_limit": 0.30,
        "sls_conc_limit_pct": 60.0,
        "sls_steel_limit_pct": 80.0,
        "sls_pre_limit_pct": 75.0,
        "sls_limit_source": "QA fixture SLS criteria",
        "v_min": 0.0,
        "v_max": 360.0,
        "v_inc": 90.0,
        "extent": 0.2,
    }


def _crack() -> dict:
    candidate = {
        "element_type": "Bar",
        "element_no": 1,
        "element_id": "bar 1",
        "x_mm": 0.0,
        "y_mm": -120.0,
        "area_mm2": 500.0,
        "wk": 0.213,
        "sr_max": 235.0,
        "esm_ecm": 8.4e-4,
        "sigma_s": 215.0,
        "rho_p_eff": 0.04,
        "ac_eff": 0.0125,
        "hc_ef": 0.125,
        "phi": 16.0,
        "cover": 40.0,
        "coarse": False,
        "edition": "2004",
        "kw": 1.0,
        "k1_r": 1.0,
        "kfl": 1.0,
        "sr_max_geometric": False,
    }
    return dict(candidate, gov_bar=1, candidates=[candidate])


def _results() -> dict:
    return {
        "plastic": {
            "mx": [100.0, 0.0, -100.0, 0.0],
            "my": [0.0, 100.0, 0.0, -100.0],
            "max_mx": 100.0,
            "max_my": 100.0,
            "min_mx": -100.0,
            "min_my": -100.0,
            "util": 0.8,
            "closed": True,
            "check_util": True,
            "applied": (80.0, 0.0),
            "converged": True,
            "points": [{
                "V": 0.0,
                "Mx": 100.0,
                "My": 0.0,
                "na_x": 0.0,
                "na_y": 0.05,
                "eps_c": 0.35,
                "eps_s": 2.0,
                "eps_s_comp": -0.1,
                "eps_cable": 0.0,
                "kappa": 0.02,
                "comp_force": 300.0,
                "lever": 0.2,
                "dx": 0.0,
                "dy": 0.2,
            }],
        },
        "elastic": {
            "total": [150.0],
            "long": [120.0],
            "dif": [30.0],
            "rst1": [0.0],
            "max_conc": 12.0,
            "max_conc_xy": (0.0, 0.15),
            "max_conc_point": 4,
            "na_x": 0.0,
            "na_y": 0.04,
            "max_steel": 150.0,
            "max_steel_bar": 1,
            "max_steel_element": "bar 1",
            "converged": True,
            "cracked": True,
            "lambda_cr": 0.4,
            "sigma_ct": 7.2,
            "fctm": 2.9,
            "show_cw": True,
            "stress_plane": (-12000.0, 0.0, 80000.0),
            "elements": [{
                "element_type": "Bar",
                "element_no": 1,
                "element_id": "bar 1",
                "x_mm": 0.0,
                "y_mm": -120.0,
                "area_mm2": 500.0,
                "strain_permille": 0.75,
                "total_mpa": 150.0,
                "long_mpa": 120.0,
                "dif_mpa": 30.0,
                "rst1_mpa": 0.0,
            }],
            "concrete_corners": [
                {"point_no": 1, "ring": "Outer", "ring_point_no": 1,
                 "x_mm": -100.0, "y_mm": -150.0,
                 "strain_permille": -0.72727, "stress_mpa": -24.0},
                {"point_no": 2, "ring": "Outer", "ring_point_no": 2,
                 "x_mm": 100.0, "y_mm": -150.0,
                 "strain_permille": -0.72727, "stress_mpa": -24.0},
                {"point_no": 3, "ring": "Outer", "ring_point_no": 3,
                 "x_mm": 100.0, "y_mm": 150.0,
                 "strain_permille": 0.0, "stress_mpa": 0.0},
                {"point_no": 4, "ring": "Outer", "ring_point_no": 4,
                 "x_mm": -100.0, "y_mm": 150.0,
                 "strain_permille": 0.0, "stress_mpa": 0.0},
            ],
            "stress_assessments": {
                "concrete": {"value": 12.0, "limit": 18.0, "util": 2 / 3,
                             "margin": 6.0, "status": "OK",
                             "criterion": "60% fck"},
                "reinforcement": {"value": 150.0, "limit": 400.0,
                                  "util": 0.375, "margin": 250.0,
                                  "status": "OK", "criterion": "80% fyk",
                                  "governing": "bar 1"},
                "prestress": {"value": None, "limit": None, "util": None,
                              "margin": None, "status": "NOT APPLICABLE",
                              "criterion": "75% fpk"},
            },
            "sls_limit_source": "QA fixture SLS criteria",
            "sls_wk_limit": 0.30,
            "props_un": {
                "area": 0.06,
                "cx": 0.0,
                "cy": 0.0,
                "Ix": 4.5e-4,
                "Iy": 2.0e-4,
                "Ixy": 0.0,
            },
            "props_cr": {
                "area": 0.03,
                "cx": 0.0,
                "cy": 0.02,
                "Ix": 2.1e-4,
                "Iy": 1.0e-4,
                "Ixy": 0.0,
            },
            "crack": _crack(),
            "crack_short": _crack(),
            "crack_assessment": {
                "value": 0.213,
                "limit": 0.30,
                "util": 0.71,
                "margin": 0.087,
                "status": "OK",
                "case": "Long-term",
                "governing": "bar 1",
                "criterion": "0.3 mm",
            },
            "crack_code": "EN 1992-1-1:2005",
            "crack_member": None,
        },
    }


@functools.lru_cache(maxsize=1)
def build_fixture_pdf() -> bytes:
    """Build the report with stable time and the real figure-export path."""
    original_datetime = sector_report.datetime.datetime
    sector_report.datetime.datetime = _FixedDateTime
    try:
        return sector_report.build_report(
            {
                "proj_no": "QA-REFERENCE",
                "proj_name": "Rendered report regression",
                "section": "Reference section",
                "author": "Sector QA",
            },
            _inputs(),
            _results(),
            version=__version__,
            figures=True,
        )
    finally:
        sector_report.datetime.datetime = original_datetime


def validate_pdf_content(pdf: bytes) -> str:
    """Reject a report that lost figures or core engineering content."""
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if "figure unavailable" in text.lower():
        raise AssertionError("the report contains an unavailable-figure placeholder")

    images = 0
    for page in reader.pages:
        resources = page.get("/Resources")
        if resources is None:
            continue
        xobjects = resources.get_object().get("/XObject")
        if xobjects is None:
            continue
        for reference in xobjects.get_object().values():
            if reference.get_object().get("/Subtype") == "/Image":
                images += 1
    if images != _EXPECTED_FIGURE_COUNT:
        raise AssertionError(
            f"expected {_EXPECTED_FIGURE_COUNT} exported engineering figures, "
            f"found {images}"
        )

    outlines = reader.outline
    if len(outlines) < 6:
        raise AssertionError(
            f"expected navigable section bookmarks, found {len(outlines)}"
        )

    for number, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        if "Project: QA-REFERENCE" not in page_text:
            raise AssertionError(
                f"page {number} is missing the repeated project/section header"
            )

    concrete_page = next(
        (page.extract_text() or "" for page in reader.pages
         if "Characteristic strength" in (page.extract_text() or "")),
        "",
    )
    if "= 20.000 MPa" not in concrete_page:
        raise AssertionError("the concrete worked formula is split across pages")

    governing_page = next(
        (page.extract_text() or "" for page in reader.pages
         if "Governing case worked" in (page.extract_text() or "")),
        "",
    )
    if "NA intercepts" not in governing_page:
        raise AssertionError("the governing-case heading is separated from its table")

    settings_page = next(
        (page.extract_text() or "" for page in reader.pages
         if "Analysis settings" in (page.extract_text() or "")),
        "",
    )
    if "Sweep start V.min" not in settings_page:
        raise AssertionError("the analysis-settings heading is separated from its table")
    if "Elastic long-term" not in settings_page:
        raise AssertionError("the loads and analysis settings are split across pages")

    for expected in (
        "QA-REFERENCE",
        "Rendered report regression",
        "Ultimate (plastic) capacity",
        "Elastic section response and stress limits",
        "Crack-width candidates",
        f"Generated 2026-07-19 12:00 by Sector {__version__}",
    ):
        if expected not in text:
            raise AssertionError(f"expected report content is missing: {expected}")
    return text


def render_pdf(pdf: bytes, scale: float = 1.5) -> list[Image.Image]:
    """Rasterise all pages through PDFium and return independent PIL images."""
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
    """Return flat pixel values across supported Pillow releases."""
    getter = getattr(image, "get_flattened_data", image.getdata)
    return list(getter())


def validate_rendered_pages(pages: list[Image.Image]) -> None:
    """Reject blank, clipped, malformed or ink-saturated report pages."""
    if len(pages) < 6:
        raise AssertionError(f"expected at least 6 report pages, got {len(pages)}")

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


def write_fixture(output: pathlib.Path) -> list[pathlib.Path]:
    """Write the stable PDF and rendered page PNG evidence."""
    output.mkdir(parents=True, exist_ok=True)
    pdf = build_fixture_pdf()
    validate_pdf_content(pdf)
    pdf_path = output / "sector-report-reference.pdf"
    pdf_path.write_bytes(pdf)
    pages = render_pdf(pdf)
    validate_rendered_pages(pages)
    paths = [pdf_path]
    for index, page in enumerate(pages, start=1):
        path = output / f"sector-report-page-{index:02d}.png"
        page.save(path, format="PNG")
        paths.append(path)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    paths = write_fixture(args.output)
    print(f"Rendered {len(paths) - 1} report pages to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
