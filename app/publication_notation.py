"""Trust-aware engineering notation for ReportLab publication surfaces.

Trusted report and manual copy may contain compact source notation such as
``1e-9`` or ``mm2``. Literal project, case, material, and provenance text must
remain exactly what the user entered. This module keeps those two channels
explicit instead of trying to infer trust from a finished paragraph.
"""

from __future__ import annotations

import html
import re


_PROTECTED_MARKUP_RE = re.compile(
    r"(<nobr\b[^>]*>.*?</nobr>|<[^>]+>|"
    r"&(?:#\d+|#x[0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]+);)",
    re.IGNORECASE | re.DOTALL,
)
_ENTITY_RE = re.compile(
    r"(&(?:#\d+|#x[0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]+);)"
)
_SCIENTIFIC_RE = re.compile(
    r"(?<![A-Za-z0-9_.,])"
    r"(?P<mantissa>[+-]?(?:(?:\d{1,3}(?:[ '_]\d{3})+|\d+)"
    r"(?:[.,]\d+)?|[.,]\d+))"
    r"(?P<marker>[eE])(?P<exponent>[+-]?\d+)"
    r"(?P<suffix>(?:[ \t]+(?:%|deg)|(?:%|deg)))?"
    r"(?![A-Za-z0-9_])"
)
_UNIT_POWER_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?P<unit>mm|cm|m)(?P<power>[234])"
    r"(?![A-Za-z0-9_])"
)
def _scientific_atom(match: re.Match[str]) -> str:
    exponent = str(int(match.group("exponent")))
    suffix = (match.group("suffix") or "").strip()
    suffix_markup = f"&nbsp;{suffix}" if suffix else ""
    return (
        f"<nobr>{match.group('mantissa')} &#215; "
        f"10<super>{exponent}</super>{suffix_markup}</nobr>"
    )


def _normalise_text(text: str) -> str:
    text = _SCIENTIFIC_RE.sub(_scientific_atom, text)
    return _UNIT_POWER_RE.sub(
        lambda match: (
            f"{match.group('unit')}<super>{match.group('power')}</super>"
        ),
        text,
    )


def _shield_text(text: str) -> str:
    text = _SCIENTIFIC_RE.sub(
        lambda match: (
            f"{match.group('mantissa')}&#{ord(match.group('marker'))};"
            f"{match.group('exponent')}{match.group('suffix') or ''}"
        ),
        text,
    )
    return _UNIT_POWER_RE.sub(
        lambda match: (
            f"{match.group('unit')}&#{ord(match.group('power'))};"
        ),
        text,
    )


def normalize_trusted_markup(value: object) -> str:
    """Normalise trusted engineering copy without disturbing existing markup.

    Scientific atoms are kept together and use a multiplication sign with a
    superscript exponent. Plain ``m2``/``cm3``/``mm4``-style unit powers receive
    a superscript. Existing tags, entities, and complete ``nobr`` atoms are inert,
    making the operation idempotent.
    """

    parts = _PROTECTED_MARKUP_RE.split(str(value))
    return "".join(
        part if not part or _PROTECTED_MARKUP_RE.fullmatch(part)
        else _normalise_text(part)
        for part in parts
    )


def shield_literal_markup(value: object, *, quote: bool = True) -> str:
    """Escape and fence literal text from every trusted notation transform.

    Only transformable scientific markers and unit exponents are encoded after
    HTML escaping. ReportLab decodes them back to the exact visible identity,
    while a later trusted-text pass cannot reinterpret ``1e-9`` or ``m2`` in
    that identity. Callers may additionally fence their own token transforms.
    """

    escaped = html.escape(str(value), quote=quote)
    escaped = escaped.replace("&lt;", "&#60;").replace("&gt;", "&#62;")
    parts = _ENTITY_RE.split(escaped)
    return "".join(
        part if not part or _ENTITY_RE.fullmatch(part)
        else _shield_text(part)
        for part in parts
    )
