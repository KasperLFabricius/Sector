"""Build and rasterise a deterministic Sector report QA fixture.

The normal report tests inspect PDF text. This fixture also passes every page
through PDFium so CI exercises the artifact an engineer actually opens. The
Plotly exporter is replaced by deterministic images to keep the gate independent
of a locally installed browser while retaining the report's figure layout.
"""

from __future__ import annotations

import argparse
import datetime
import io
import pathlib
import sys

from PIL import Image, ImageDraw
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


class _FixedDateTime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 7, 19, 12, 0, 0)
        return value if tz is None else value.replace(tzinfo=tz)


def _placeholder_png(width: int, height: int) -> bytes:
    """Return a stable engineering-diagram placeholder at the requested size."""
    width = max(int(width), 20)
    height = max(int(height), 20)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    pad = max(min(width, height) // 12, 4)
    draw.rectangle((pad, pad, width - pad, height - pad), outline="#34495e", width=3)
    draw.line((pad, height - pad, width // 2, pad, width - pad, height - pad),
              fill="#0072b2", width=4)
    draw.line((pad, height // 2, width - pad, height // 2),
              fill="#d55e00", width=3)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


def _inputs() -> dict:
    return {
        "mode": "Both",
        "outer": [(-0.1, -0.15), (0.1, -0.15), (0.1, 0.15), (-0.1, 0.15)],
        "holes": [],
        "bars": [(0.0, -0.12, 5.0e-4)],
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
        "sls_fctm": 2.9,
        "sls_cw": True,
        "v_min": 0.0,
        "v_max": 360.0,
        "v_inc": 90.0,
        "extent": 0.2,
    }


def _crack() -> dict:
    return {
        "wk": 0.213,
        "sr_max": 235.0,
        "esm_ecm": 8.4e-4,
        "sigma_s": 215.0,
        "rho_p_eff": 0.04,
        "ac_eff": 0.0125,
        "hc_ef": 0.125,
        "phi": 16.0,
        "cover": 40.0,
        "gov_bar": 1,
    }


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
            "max_conc_point": 3,
            "na_x": 0.0,
            "na_y": 0.04,
            "max_steel": 150.0,
            "max_steel_bar": 1,
            "converged": True,
            "cracked": True,
            "lambda_cr": 0.4,
            "sigma_ct": 7.2,
            "fctm": 2.9,
            "show_cw": True,
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
            "crack_code": "EN 1992-1-1:2005",
            "crack_member": None,
        },
    }


def build_fixture_pdf() -> bytes:
    """Build the report with stable time and stable raster figure content."""
    original_datetime = sector_report.datetime.datetime
    original_server = sector_report.ensure_image_server
    original_export = sector_report._fig_png
    sector_report.datetime.datetime = _FixedDateTime
    sector_report.ensure_image_server = lambda: None
    sector_report._fig_png = (
        lambda _figure, width, height, timeout=None:
        (_placeholder_png(width, height), False)
    )
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
        sector_report.ensure_image_server = original_server
        sector_report._fig_png = original_export


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
    """Write the deterministic PDF and rendered page PNG evidence."""
    output.mkdir(parents=True, exist_ok=True)
    pdf = build_fixture_pdf()
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
