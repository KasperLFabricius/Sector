"""Shared immutable publication tokens for Sector PDF artifacts.

The report and manual retain separate information architectures, but use one
owned palette, type scale, spacing grid and page geometry.  Warning handling
also lives here because both artifacts cross the same Plotly/Kaleido export
boundary.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import warnings


@dataclass(frozen=True)
class PublicationStyle:
    primary_hex: str = "#1F3B66"
    primary_dark_hex: str = "#0D2440"
    text_hex: str = "#2C2C2A"
    muted_hex: str = "#5A5A5A"
    rule_hex: str = "#9AA5B1"
    header_fill_hex: str = "#E8ECF2"
    panel_fill_hex: str = "#EEF2F7"
    panel_rule_hex: str = "#9FB3C8"
    title_size: float = 20.0
    body_size: float = 9.5
    body_leading: float = 13.0
    small_size: float = 8.0
    small_leading: float = 11.0
    caption_size: float = 8.0
    caption_leading: float = 10.0
    minimum_table_size: float = 7.2
    report_margins_mm: tuple[float, float, float, float] = (
        20.0, 20.0, 25.0, 20.0
    )
    manual_margins_mm: tuple[float, float, float, float] = (
        22.0, 22.0, 20.0, 20.0
    )
    spacing_grid_pt: tuple[float, ...] = (
        1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 10.0, 14.0, 18.0
    )
    publication_start_height_mm: float = 55.0

    def spacing(self, points: float) -> float:
        """Return one owned spacing-grid value and reject ad-hoc values."""

        value = float(points)
        if value not in self.spacing_grid_pt:
            raise ValueError(f"Publication spacing is outside the grid: {value:g} pt")
        return value


STYLE = PublicationStyle()

KALEIDO_SERVER_KOPTS_WARNING = (
    "The kopts argument is ignored if using a server."
)


@contextmanager
def suppress_kaleido_server_kopts_warning():
    """Suppress only Kaleido's known server-mode ``kopts`` warning."""

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=(
                r"^The kopts argument is ignored if using a server\.$"
            ),
            category=UserWarning,
        )
        yield
