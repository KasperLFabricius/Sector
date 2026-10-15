"""Original Sweco artwork for publication covers and offline HTML."""

from __future__ import annotations

import base64
import io
from pathlib import Path

LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "logo.png"


def logo_bytes() -> bytes:
    """Read the mandatory artwork without resizing or changing its bytes."""
    try:
        payload = LOGO_PATH.read_bytes()
    except OSError as exc:
        raise RuntimeError("The required Sweco logo could not be read.") from exc
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("The required Sweco logo must be a PNG image.")
    return payload


def logo_flowable(width: float):
    """Build a left-aligned cover image with the original aspect ratio.

    Import ReportLab only when a PDF is requested. Branding is outside the
    numbered engineering figure inventory.
    """
    from reportlab.platypus import Image

    image = Image(io.BytesIO(logo_bytes()), width=width)
    image.drawHeight = width * image.imageHeight / image.imageWidth
    image.hAlign = "LEFT"
    return image


def logo_html() -> str:
    """Embed original artwork so an offline manual needs no external file."""
    encoded = base64.b64encode(logo_bytes()).decode("ascii")
    return (
        '<img class="publication-logo" alt="Sweco" '
        f'src="data:image/png;base64,{encoded}">'
    )
