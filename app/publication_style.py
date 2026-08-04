"""Immutable publication style and export-warning contract.

The module deliberately has no ReportLab import. The Streamlit manual can keep
its lazy PDF dependency boundary while the report and manual consume the same
typed style specifications.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from types import MappingProxyType
import warnings


@dataclass(frozen=True)
class PublicationPalette:
    primary: str = "#1F3B66"
    primary_dark: str = "#0D2440"
    ink: str = "#2C2C2A"
    muted: str = "#5A5A5A"
    manual_muted: str = "#808080"
    publication_reference: str = "#5A5A56"
    rule: str = "#9AA5B1"
    report_header: str = "#E8ECF2"
    manual_surface: str = "#EEF2F7"
    manual_rule: str = "#9FB3C8"
    light_grid: str = "#D3D3D3"


@dataclass(frozen=True)
class ParagraphSpec:
    font_size: float
    leading: float | None = None
    space_before: float = 0.0
    space_after: float = 0.0
    color: str | None = None
    bold: bool = False
    keep_with_next: bool = False


PALETTE = PublicationPalette()

REPORT_PARAGRAPHS = MappingProxyType({
    "title": ParagraphSpec(20, color=PALETTE.primary, bold=True, space_after=4),
    "subtitle": ParagraphSpec(11, color=PALETTE.muted, space_after=2),
    "h1": ParagraphSpec(
        14, color=PALETTE.primary, bold=True, space_before=10,
        space_after=6, keep_with_next=True,
    ),
    "h2": ParagraphSpec(
        11.5, color=PALETTE.primary, bold=True, space_before=8,
        space_after=4, keep_with_next=True,
    ),
    "body": ParagraphSpec(9.5, leading=13, space_after=4),
    "small": ParagraphSpec(8.5, leading=11, color=PALETTE.muted),
    "publication_ref": ParagraphSpec(
        8, leading=10, color=PALETTE.muted, space_before=2,
        space_after=2, keep_with_next=True,
    ),
    "publication_caption": ParagraphSpec(
        8, leading=10, color=PALETTE.ink, space_before=2,
        space_after=2, keep_with_next=True,
    ),
})

MANUAL_PARAGRAPHS = MappingProxyType({
    "title": ParagraphSpec(20, bold=True, space_after=6),
    "part": ParagraphSpec(
        17, color=PALETTE.primary_dark, bold=True, space_before=18,
        space_after=8, keep_with_next=True,
    ),
    "h1": ParagraphSpec(
        15, color=PALETTE.primary, bold=True, space_before=14,
        space_after=8, keep_with_next=True,
    ),
    "h2": ParagraphSpec(
        12.5, bold=True, space_before=9, space_after=4, keep_with_next=True,
    ),
    "h3": ParagraphSpec(
        11, bold=True, space_before=6, space_after=3, keep_with_next=True,
    ),
    "body": ParagraphSpec(9.5, leading=13, space_after=4),
    "math": ParagraphSpec(11, leading=15, space_before=6, space_after=6),
    "small": ParagraphSpec(8, leading=11, color=PALETTE.manual_muted),
    "publication_ref": ParagraphSpec(
        8, leading=10, color=PALETTE.manual_muted, space_before=2,
        space_after=2, keep_with_next=True,
    ),
    "publication_caption": ParagraphSpec(
        8, leading=10, color=PALETTE.ink, space_before=2,
        space_after=3, keep_with_next=True,
    ),
})

ASSESSMENT_PALETTE = MappingProxyType({
    "PASS": ("#E8F5E9", "#1B5E20"),
    "OK": ("#E8F5E9", "#1B5E20"),
    "FAIL": ("#FDECEC", "#9B1C1C"),
    "EXCEEDED": ("#FDECEC", "#9B1C1C"),
    "INVALID": ("#FDECEC", "#9B1C1C"),
    "REVIEW": ("#FFF4D6", "#7A4E00"),
    "NOT ASSESSED": ("#FFF4D6", "#7A4E00"),
    "NOT APPLICABLE": ("#EEF2F6", "#374151"),
})


def paragraph_kwargs(spec, normal_font, bold_font, color_factory):
    """Translate one immutable spec to ReportLab ``ParagraphStyle`` kwargs."""
    values = {
        "fontSize": spec.font_size,
        "fontName": bold_font if spec.bold else normal_font,
        "spaceBefore": spec.space_before,
        "spaceAfter": spec.space_after,
    }
    if spec.leading is not None:
        values["leading"] = spec.leading
    if spec.color is not None:
        values["textColor"] = color_factory(spec.color)
    if spec.keep_with_next:
        values["keepWithNext"] = 1
    return values


KALEIDO_SERVER_WARNING = "The kopts argument is ignored if using a server."
_KALEIDO_SERVER_WARNING_RE = (
    r"^The kopts argument is ignored if using a server\.$"
)


@contextmanager
def suppress_known_kaleido_server_warning():
    """Suppress only Plotly's inert server-mode ``kopts`` warning."""
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=_KALEIDO_SERVER_WARNING_RE,
            category=UserWarning,
            module=r"^plotly\.io\._kaleido$",
        )
        yield
