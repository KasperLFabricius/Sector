"""Trusted engineering notation for Sector's PDF publications.

The helpers deliberately distinguish authored engineering content from literal
project identities.  A project number such as ``m2`` is data, not a square-metre
unit, and must therefore survive publication byte-for-byte in extracted text.
"""

from __future__ import annotations

import math
import re


_UNIT_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_])(?P<base>mm|cm|m)(?P<power>[234])"
    r"(?![A-Za-z0-9_])"
)
_MARKUP_TOKEN = re.compile(r"(<[^>]+>|&(?:#[0-9]+|#x[0-9A-Fa-f]+|[A-Za-z]+);)")
_NUMBER_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"[+-]?(?:\d{1,3}(?:[ ,]\d{3})+|\d+)(?:[.,]\d+)?"
    r"(?:[eE][+-]?\d+)?(?:\s*(?:%|deg))?"
    r"(?![A-Za-z0-9_])"
)
_SCIENTIFIC_TOKEN = re.compile(
    r"(?P<mantissa>[+-]?(?:\d+(?:[.,]\d+)?|[.,]\d+))"
    r"[eE](?P<exponent>[+-]?\d+)"
)


def scientific_markup(value, significant: int = 6) -> str:
    """Return a finite value as atomic ReportLab scientific notation."""
    if value is None:
        return "-"
    numeric = float(value)
    if not math.isfinite(numeric):
        return "-inf" if numeric < 0.0 else "inf"
    rendered = f"{numeric:.{significant}g}"
    if "e" not in rendered.lower():
        return f"<nobr>{rendered}</nobr>"
    mantissa, exponent = re.split("[eE]", rendered, maxsplit=1)
    return (
        f"<nobr>{mantissa} &#215; 10"
        f"<super>{int(exponent)}</super></nobr>"
    )


def normalise_unit_exponents(text: str, *, trusted: bool = False) -> str:
    """Render unit powers while preserving untrusted literal identifiers.

    Authored formulae, table headers and manual prose opt in with
    ``trusted=True``. Untrusted report prose and table bodies are returned
    unchanged even when they look like engineering syntax: an identifier such
    as ``Bridge 100 m2`` is still identity data, not a value to reinterpret.
    """
    value = str(text)
    if not trusted:
        return value

    def replace(match: re.Match[str]) -> str:
        return (
            f"<nobr>{match.group('base')}"
            f"<super>{match.group('power')}</super></nobr>"
        )

    return _UNIT_TOKEN.sub(replace, value)


def protect_numeric_tokens(
    text: str, *, typographic_science: bool = False
) -> str:
    """Keep ordinary numeric tokens intact without nesting existing markup."""
    parts = _MARKUP_TOKEN.split(str(text))
    inside_nobr = 0
    rendered = []
    for part in parts:
        if not part:
            continue
        if part.startswith("<"):
            tag = part.casefold()
            if tag.startswith("<nobr"):
                inside_nobr += 1
            elif tag.startswith("</nobr"):
                inside_nobr = max(inside_nobr - 1, 0)
            rendered.append(part)
        elif part.startswith("&") or inside_nobr:
            rendered.append(part)
        else:
            def protect(match: re.Match[str]) -> str:
                token = match.group(0)
                scientific = _SCIENTIFIC_TOKEN.fullmatch(token)
                if typographic_science and scientific:
                    return (
                        f"<nobr>{scientific.group('mantissa')} &#215; 10"
                        f"<super>{int(scientific.group('exponent'))}</super>"
                        "</nobr>"
                    )
                return f"<nobr>{token}</nobr>"

            rendered.append(
                _NUMBER_TOKEN.sub(protect, part)
            )
    return "".join(rendered)


def publication_markup(
    text: str,
    *,
    trusted_units: bool = False,
    protect_numbers: bool = False,
    typographic_science: bool = False,
) -> str:
    """Apply the shared notation layer with an explicit trust boundary."""
    rendered = normalise_unit_exponents(text, trusted=trusted_units)
    if protect_numbers:
        rendered = protect_numeric_tokens(
            rendered, typographic_science=typographic_science
        )
    return rendered
