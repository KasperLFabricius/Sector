"""Keep software diagnostics out of engineer-facing error messages."""

from __future__ import annotations

import logging
import re


_LOGGER = logging.getLogger(__name__)
_ENGINEERING_NOTATION = re.compile(
    r"(?<![a-z0-9_])(?:gamma_(?:ff|s|c(?:,fat)?)|"
    r"beta_cc(?:\(t0\))?|alpha_cc)(?![a-z0-9_])",
    flags=re.IGNORECASE,
)
_TECHNICAL_MARKER = re.compile(
    r"(?:\bsha(?:-?256)?\b|\bhash(?:es|ed|ing)?\b|\bpayload\b|"
    r"\bschema\b|\bcontract\b|\bprovenance\b|\bkernel\b|"
    r"\bsolver\b|\bcanonical\b|\bmetadata\b|\bmigration\b|"
    r"\bdispatch\b|\btraceback\b|\bstack\s*trace\b|\bjson\b|"
    r"\binventory\b|\bcapability\s+binding\b|\bfallback\b|"
    r"\bstable\b|\bbasis\s+key\b|\binput\s+snapshot\b|"
    r"\bregistered\s+basis\b|\bretained\b|\bretains\b|"
    r"\bauthoritative\b|\bsemantic\s+check\b|\bidentity\b|"
    r"\btable[-\s]+owned\b|\blegacy\b|\bimplementation\b|"
    r"\bsource\s+(?:revision|version)\b|"
    r"\binternal\s+(?:id|identifier|key|keys)\b|"
    r"\beq-[a-z0-9][a-z0-9._-]*\b|"
    r"(?<![a-z0-9_])_*[a-z][a-z0-9]*_[a-z0-9_]+\b)",
    flags=re.IGNORECASE,
)


def error_detail(value: object, *, fallback: str) -> str:
    """Return concise engineering copy, replacing software diagnostics.

    The caller owns the action-specific fallback. Replaced details are retained
    in the application log for fault-finding but are never returned for display.
    """

    detail = " ".join(str(value).split()).strip().rstrip(".")
    replacement = " ".join(str(fallback).split()).strip().rstrip(".")
    if not replacement:
        raise ValueError("fallback must contain visible guidance")
    # A small, explicit allow-list keeps familiar Eurocode notation useful in
    # validation guidance.  It deliberately does not match longer application
    # field names such as ``fatigue_gamma_s``.
    detail_for_screening = _ENGINEERING_NOTATION.sub(
        "engineering-symbol",
        detail,
    )
    unsafe = (
        not detail
        or len(detail) > 240
        or _TECHNICAL_MARKER.search(detail_for_screening) is not None
        or any(character in detail for character in ("{", "}", "[", "]"))
    )
    if unsafe:
        _LOGGER.warning("Hidden software diagnostic: %s", detail or "<empty>")
        return replacement
    return detail
