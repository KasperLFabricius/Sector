"""Dormant visible product-version check for the issued user manual."""

from __future__ import annotations

import re


_HSPACE = r"[\t \u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]"
_LINE_BREAK = r"\r\n\v\f\x85\u2028\u2029"
_QUOTE_CHARS = r"\"'\u00ab\u00bb\u2018\u2019\u201c\u201d\u201e\u201f\u2039\u203a"
_QUOTE = rf"[{_QUOTE_CHARS}]"
_DASH_CHARS = r"\-\u2010\u2011\u2012\u2013\u2014"
_SEPARATOR = rf"[:=#{_DASH_CHARS}]"
_JOIN = rf"(?:{_HSPACE}+|{_HSPACE}*{_SEPARATOR}{_HSPACE}*)"
_REFERENCE_SUFFIX = (
    rf"[^\s,;:!?()\[\]{{}}<>"
    rf"{_QUOTE_CHARS}\u2026\u3002]*"
)
_VISIBLE_VERSION = rf"(?P<version>\d+(?:\.\d+)+{_REFERENCE_SUFFIX})"

_SECTOR_LABELLED_PRODUCT_REFERENCE = re.compile(
    r"\bsector\b"
    rf"{_QUOTE}?{_JOIN}"
    rf"(?:user{_JOIN}manual{_QUOTE}?{_JOIN})?"
    rf"{_QUOTE}?{_HSPACE}*"
    r"(?:(?:version|release)\b|v)"
    rf"{_QUOTE}?{_HSPACE}*"
    rf"(?:{_SEPARATOR}{_HSPACE}*)?"
    rf"{_QUOTE}?{_HSPACE}*"
    rf"v?{_QUOTE}?{_HSPACE}*"
    + _VISIBLE_VERSION,
    flags=re.IGNORECASE,
)
_SECTOR_TITLE_PRODUCT_REFERENCE = re.compile(
    r"\bSector\b"
    rf"{_QUOTE}?{_JOIN}"
    rf"(?:(?i:user){_JOIN}(?i:manual){_QUOTE}?{_JOIN})?"
    rf"{_QUOTE}?{_HSPACE}*"
    + _VISIBLE_VERSION,
)
_BARE_PRODUCT_REFERENCE = re.compile(
    rf"(?:\A|(?<=[{_LINE_BREAK}]))"
    rf"{_HSPACE}*{_QUOTE}?{_HSPACE}*"
    rf"v{_QUOTE}?{_HSPACE}*"
    + _VISIBLE_VERSION,
    flags=re.IGNORECASE,
)
_VERSION_LABEL_REFERENCE = re.compile(
    rf"(?:\A|(?<=[{_LINE_BREAK}]))"
    rf"{_HSPACE}*{_QUOTE}?{_HSPACE}*"
    r"version\b"
    rf"{_QUOTE}?{_HSPACE}*"
    rf"(?:{_SEPARATOR}{_HSPACE}*)?"
    rf"{_QUOTE}?{_HSPACE}*"
    rf"v?{_QUOTE}?{_HSPACE}*"
    + _VISIBLE_VERSION,
    flags=re.IGNORECASE,
)
_CURRENT_PRODUCT_VERSION = re.compile(r"[0-9]+(?:\.[0-9]+)+\Z")


def _visible_product_versions(flat_text: str) -> set[str]:
    versions: set[str] = set()
    for pattern in (
        _SECTOR_LABELLED_PRODUCT_REFERENCE,
        _SECTOR_TITLE_PRODUCT_REFERENCE,
        _BARE_PRODUCT_REFERENCE,
        _VERSION_LABEL_REFERENCE,
    ):
        versions.update(
            match.group("version").rstrip(".")
            for match in pattern.finditer(flat_text)
        )
    return versions


def validate_no_noncurrent_manual_product_references(
    flat_text: object,
    *,
    product_version: str,
) -> None:
    """Reject visible Sector versions other than the supplied current one."""

    if type(flat_text) is not str:
        raise AssertionError("manual product-reference content must be text")
    if (
        type(product_version) is not str
        or _CURRENT_PRODUCT_VERSION.fullmatch(product_version) is None
    ):
        raise AssertionError(
            "current product version must be an ASCII dotted number"
        )

    noncurrent_versions = sorted(
        version
        for version in _visible_product_versions(flat_text)
        if version != product_version
    )
    if noncurrent_versions:
        raise AssertionError(
            "the manual contains non-current Sector versions: "
            + ", ".join(noncurrent_versions)
        )
