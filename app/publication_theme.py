"""Frozen visual and export-noise contract for Sector publications.

This module intentionally does not import ReportLab.  The eagerly imported
manual module can therefore share the publication theme without giving up its
lazy PDF-dependency boundary.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from types import MappingProxyType
import warnings


@dataclass(frozen=True, slots=True)
class Palette:
    primary: str = "#1F3B66"
    primary_dark: str = "#0D2440"
    ink: str = "#2C2C2A"
    muted: str = "#5A5A5A"
    manual_muted: str = "#5A5A5A"
    publication_reference: str = "#5A5A56"
    rule: str = "#9AA5B1"
    report_header: str = "#E8ECF2"
    manual_surface: str = "#EEF2F7"
    manual_rule: str = "#9FB3C8"
    grid: str = "#D3D3D3"


@dataclass(frozen=True, slots=True)
class TextStyle:
    size: float
    leading: float | None = None
    before: float = 0.0
    after: float = 0.0
    color: str | None = None
    bold: bool = False
    keep_next: bool = False


PALETTE = Palette()

REPORT_TEXT = MappingProxyType({
    "title": TextStyle(20, after=4, color=PALETTE.primary, bold=True),
    "subtitle": TextStyle(11, after=2, color=PALETTE.muted),
    "h1": TextStyle(
        14, before=10, after=6, color=PALETTE.primary,
        bold=True, keep_next=True,
    ),
    "h2": TextStyle(
        11.5, before=8, after=4, color=PALETTE.primary,
        bold=True, keep_next=True,
    ),
    "body": TextStyle(9.5, leading=13, after=4),
    "small": TextStyle(8.5, leading=11, color=PALETTE.muted),
    "publication_ref": TextStyle(
        8, leading=10, before=2, after=2, color=PALETTE.muted,
        keep_next=True,
    ),
    "publication_caption": TextStyle(
        8, leading=10, before=2, after=2, color=PALETTE.ink,
        keep_next=True,
    ),
})

MANUAL_TEXT = MappingProxyType({
    "title": TextStyle(20, after=6, bold=True),
    "part": TextStyle(
        17, before=18, after=8, color=PALETTE.primary_dark,
        bold=True, keep_next=True,
    ),
    "h1": TextStyle(
        15, before=14, after=8, color=PALETTE.primary,
        bold=True, keep_next=True,
    ),
    "h2": TextStyle(12.5, before=9, after=4, bold=True, keep_next=True),
    "h3": TextStyle(11, before=6, after=3, bold=True, keep_next=True),
    "body": TextStyle(9.5, leading=13, after=4),
    "math": TextStyle(11, leading=15, before=6, after=6),
    "small": TextStyle(9.5, leading=12, color=PALETTE.manual_muted),
    "publication_ref": TextStyle(
        9.5, leading=12, before=2, after=2, color=PALETTE.manual_muted,
        keep_next=True,
    ),
    "publication_caption": TextStyle(
        9.5, leading=12, before=2, after=3, color=PALETTE.ink,
        keep_next=True,
    ),
})

ASSESSMENT_COLORS = MappingProxyType({
    "PASS": ("#E8F5E9", "#1B5E20"),
    "OK": ("#E8F5E9", "#1B5E20"),
    "FAIL": ("#FDECEC", "#9B1C1C"),
    "EXCEEDED": ("#FDECEC", "#9B1C1C"),
    "INVALID": ("#FDECEC", "#9B1C1C"),
    "REVIEW": ("#FFF4D6", "#7A4E00"),
    "NOT ASSESSED": ("#FFF4D6", "#7A4E00"),
    "NOT APPLICABLE": ("#EEF2F6", "#374151"),
})


def reportlab_style_values(style, regular_font, bold_font, make_color):
    """Translate one frozen text role to ParagraphStyle keyword values."""
    values = {
        "fontName": bold_font if style.bold else regular_font,
        "fontSize": style.size,
        "spaceBefore": style.before,
        "spaceAfter": style.after,
    }
    if style.leading is not None:
        values["leading"] = style.leading
    if style.color is not None:
        values["textColor"] = make_color(style.color)
    if style.keep_next:
        values["keepWithNext"] = 1
    return values


KALEIDO_SERVER_KOPTS_WARNING = (
    "The kopts argument is ignored if using a server."
)


@contextmanager
def without_kaleido_server_kopts_noise():
    """Hide only Plotly's inert server-mode ``kopts`` UserWarning."""
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"^The kopts argument is ignored if using a server\.$",
            category=UserWarning,
            module=r"^plotly\.io\._kaleido$",
        )
        yield
