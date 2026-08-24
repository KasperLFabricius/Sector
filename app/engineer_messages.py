"""Sole publication gate for engineer-facing diagnostic copy."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping

from sector.engineer_message import EngineerMessage


_LOGGER = logging.getLogger(__name__)

# These examples document the authored-copy policy and support the static copy
# inventory. Publication trust never depends on matching this vocabulary:
# untyped values always fail closed, including text that looks harmless.
DEVELOPMENT_COPY_EXAMPLES = (
    "GitHub",
    "pull request",
    "PR #123",
    "git commit",
    "source control",
    "development history",
    "development process",
    "SHA-256",
    "hash",
    "payload",
    "schema",
    "contract",
    "provenance",
    "internal identifier",
    "private ID",
    "EQ-PRIVATE-1",
    "canonical JSON",
    "source revision",
    "source version",
    "input snapshot",
    "capability binding",
    "basis key",
    "registered basis",
    "solver state",
    "solver target",
    "solver edition",
    "solver binding",
    "traceback",
    "stack trace",
    "dispatch kernel",
    "fallback",
    "metadata",
    "migration",
    "legacy implementation",
    "table-owned",
    "stable identifier",
    "retained result",
    "authoritative output",
    "semantic check",
)

_NORMALIZED_PHRASES = (
    "github",
    "pull request",
    "git commit",
    "source control",
    "development history",
    "development process",
    "sha",
    "sha 256",
    "sha256",
    "hash",
    "hashes",
    "hashed",
    "hashing",
    "payload",
    "schema",
    "contract",
    "provenance",
    "canonical json",
    "source revision",
    "source version",
    "input snapshot",
    "capability binding",
    "basis key",
    "registered basis",
    "solver state",
    "solver target",
    "solver edition",
    "solver binding",
    "traceback",
    "stack trace",
    "dispatch kernel",
    "fallback",
    "metadata",
    "migration",
    "legacy implementation",
    "table owned",
    "stable identifier",
    "stable identity",
    "retained result",
    "authoritative output",
    "semantic check",
)
_PRIVATE_IDENTIFIER = re.compile(
    r"\b(?:internal|private)\s+(?:id|ids|identifier|identifiers|key|keys)\b"
)
_PR_NUMBER = re.compile(r"\bpr\s+\d+\b")
_EQ_IDENTIFIER = re.compile(
    r"\beq[-_]+[a-z0-9][a-z0-9._-]*\b",
    flags=re.IGNORECASE,
)
_NORMALIZED_EQ_IDENTIFIER = re.compile(
    r"\beq\s+(?=[a-z])(?:[a-z0-9]+\s+)*\d+\b",
    flags=re.IGNORECASE,
)
_PRIVATE_APPLICATION_IDENTIFIER = re.compile(
    r"\b(?:fatigue|report|project|plastic|elastic|torsion|shear|capacity|sls|"
    r"heightened)(?:_[a-z0-9]+){2,}\b",
    flags=re.IGNORECASE,
)


class EngineerValidationError(ValueError):
    """Expected application validation carrying literal authored guidance."""

    def __init__(self, message: EngineerMessage) -> None:
        if not isinstance(message, EngineerMessage):
            raise TypeError("message must be an EngineerMessage")
        super().__init__(message.code)
        self.engineer_message = message


def normalize_authored_copy(text: str) -> str:
    """Case-fold copy and treat every non-alphanumeric separator alike."""

    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.casefold()).split())


def development_process_terms(text: str) -> tuple[str, ...]:
    """Return development-specific expressions in authored visible copy."""

    normalized = normalize_authored_copy(text)
    # PDF extraction can render the recognised engineering symbol ``u_eq`` as
    # two words.  Protect that notation before applying the separator-neutral
    # internal equation-ID detector.
    normalized_equation_copy = re.sub(r"\bu\s+eq\b", "ueq", normalized)
    padded = f" {normalized} "
    found: list[str] = []
    for phrase in _NORMALIZED_PHRASES:
        if f" {phrase} " in padded and phrase not in found:
            found.append(phrase)
    if _PR_NUMBER.search(normalized) and "pr number" not in found:
        found.append("pr number")
    if _PRIVATE_IDENTIFIER.search(normalized) and "private identifier" not in found:
        found.append("private identifier")
    # Internal EQ identifiers require a non-numeric token after the prefix. This
    # leaves normative references such as "Eq. (6.31)" and u_eq notation intact
    # while treating every identifier separator consistently.
    if (
        _EQ_IDENTIFIER.search(text)
        or _NORMALIZED_EQ_IDENTIFIER.search(normalized_equation_copy)
    ) and "equation identifier" not in found:
        found.append("equation identifier")
    if (
        _PRIVATE_APPLICATION_IDENTIFIER.search(text)
        and "private application identifier" not in found
    ):
        found.append("private application identifier")
    return tuple(found)


def _attached_message(value: object) -> EngineerMessage | None:
    if isinstance(value, EngineerMessage):
        return value
    if isinstance(value, BaseException):
        try:
            message = getattr(value, "engineer_message", None)
        except Exception:  # pragma: no cover - hostile exception properties
            return None
        if isinstance(message, EngineerMessage):
            return message
    return None


def _diagnostic_repr(value: object) -> str:
    try:
        return repr(value)
    except Exception:  # pragma: no cover - hostile third-party object
        return f"<{type(value).__module__}.{type(value).__qualname__}>"


def resolve(
    value: object,
    *,
    fallback: EngineerMessage,
    context: str,
) -> EngineerMessage:
    """Resolve trusted authored copy or return an authored contextual fallback."""

    if not isinstance(fallback, EngineerMessage):
        raise TypeError("fallback must be an EngineerMessage")
    if development_process_terms(fallback.text):
        raise ValueError("fallback contains development-specific copy")

    message = _attached_message(value)
    if message is not None and not development_process_terms(message.text):
        return message

    _LOGGER.warning(
        "Suppressed untrusted diagnostic at %s: %s",
        context,
        _diagnostic_repr(value),
    )
    return fallback


def resolve_state(
    value: object,
    *,
    authored: Mapping[object, EngineerMessage],
    fallback: EngineerMessage,
    context: str,
) -> EngineerMessage:
    """Resolve a typed message or one finite authored state mapping."""

    candidate = value
    if not isinstance(value, (EngineerMessage, BaseException)):
        try:
            candidate = authored.get(value, value)
        except (TypeError, ValueError):
            candidate = value
    return resolve(candidate, fallback=fallback, context=context)


def error_detail(
    value: object,
    *,
    fallback: EngineerMessage,
    context: str,
) -> str:
    """Return visible copy after applying the positive-provenance gate."""

    return resolve(value, fallback=fallback, context=context).text
