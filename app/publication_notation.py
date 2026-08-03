"""Shared ReportLab-safe notation for Sector's published documents.

The application source remains ASCII-only.  This module therefore emits numeric
entities and ReportLab inline tags for multiplication signs, powers and no-break
spans instead of embedding typographic glyphs directly in Python source.
"""

from __future__ import annotations

import math
import re


MIN_TABLE_FONT_SIZE = 7.2

_TAG_OR_ENTITY_RE = re.compile(r"(<[^>]+>|&#\d+;|&[A-Za-z]+;)")
_UNIT_POWER_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?P<value>[+-]?(?:\d+(?:[.,]\d+)?|[.,]\d+)[ \t]+)?"
    r"(?P<unit>mm|cm|m)(?P<power>[234])"
    r"(?P<denominator>/(?:mm|cm|m))?"
    r"(?=$|[^A-Za-z0-9_])"
)
_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9_&])"
    r"(?P<number>[+-]?(?:\d+(?:[.,]\d+)?|[.,]\d+)(?:[eE][+-]?\d+)?)"
    r"(?P<unit>[ \t]*(?:%|MPa|GPa|kN(?:m)?|N|mm|cm|m|1)(?:/[A-Za-z]+)?)?"
    r"(?![A-Za-z0-9_])"
)


def clamp_table_font(value: float) -> float:
    """Return the practical minimum publication font for a requested table size."""

    return max(float(value), MIN_TABLE_FONT_SIZE)


def scientific_markup(value, significant_digits: int = 6) -> str:
    """Format a finite number without raw ``e`` notation in published output."""

    if value is None:
        return "-"
    number = float(value)
    if not math.isfinite(number):
        return "-inf" if math.isinf(number) and number < 0.0 else "inf"
    rendered = f"{number:.{significant_digits}g}"
    match = re.fullmatch(r"(?P<mantissa>[-+0-9.]+)[eE](?P<exponent>[-+]?\d+)", rendered)
    if match is None:
        return rendered
    exponent = int(match.group("exponent"))
    return (
        f"<nobr>{match.group('mantissa')} &#215; "
        f"10<super>{exponent}</super></nobr>"
    )


def normalise_unit_exponents(markup: str) -> str:
    """Render plain engineering unit powers such as ``mm2`` typographically."""

    return _UNIT_POWER_RE.sub(
        lambda match: (
            f"<nobr>{match.group('value') or ''}{match.group('unit')}"
            f"<super>{match.group('power')}</super>"
            f"{match.group('denominator') or ''}</nobr>"
        ),
        str(markup),
    )


def protect_numeric_tokens(markup: str) -> str:
    """Keep numeric values and their immediate units intact inside table cells.

    Existing ReportLab markup, entities, superscripts and explicit ``nobr`` spans
    are preserved.  The function is idempotent so renderers can safely apply it at
    both a shared conversion boundary and a table-specific boundary.
    """

    parts = _TAG_OR_ENTITY_RE.split(str(markup))
    protected = []
    protected_depth = 0
    for part in parts:
        if not part:
            continue
        if part.startswith("<"):
            tag = re.match(r"</?\s*([A-Za-z0-9]+)", part)
            name = tag.group(1).lower() if tag else ""
            if name in {"nobr", "sub", "super"}:
                if part.startswith("</"):
                    protected_depth = max(0, protected_depth - 1)
                elif not part.rstrip().endswith("/>"):
                    protected_depth += 1
            protected.append(part)
            continue
        if part.startswith("&") or protected_depth:
            protected.append(part)
            continue
        protected.append(
            _NUMBER_RE.sub(
                lambda match: (
                    f"<nobr>{match.group('number')}"
                    f"{match.group('unit') or ''}</nobr>"
                ),
                part,
            )
        )
    return "".join(protected)


def publication_markup(markup: str, *, protect_numbers: bool = False) -> str:
    """Apply the shared unit layer and, when requested, numeric no-break spans."""

    rendered = normalise_unit_exponents(markup)
    return protect_numeric_tokens(rendered) if protect_numbers else rendered
