"""Stable identities for figures and tables on Sector publication surfaces.

The calculation report is assembled dynamically while the manual is a frozen
block stream.  Both surfaces nevertheless use the same small identity object so
captions, references and anchors cannot disagree about an item's number.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


class PublicationInventoryError(ValueError):
    """Raised when the retained manual publication inventory changes."""


@dataclass(frozen=True)
class PublicationIdentity:
    """One stable, visible figure or table identity."""

    kind: str
    number: str
    caption: str

    def __post_init__(self) -> None:
        if self.kind not in ("Figure", "Table"):
            raise PublicationInventoryError(
                f"Unsupported publication item kind: {self.kind!r}."
            )
        if not self.number or not self.caption.strip():
            raise PublicationInventoryError(
                "Publication items require a number and a non-empty caption."
            )

    @property
    def label(self) -> str:
        return f"{self.kind} {self.number}"

    @property
    def anchor(self) -> str:
        token = re.sub(r"[^a-z0-9]+", "-", self.number.lower()).strip("-")
        return f"{self.kind.lower()}-{token}"

    @property
    def caption_text(self) -> str:
        return f"{self.label}. {self.caption}"

    @property
    def continued_caption_text(self) -> str:
        return f"{self.label} (continued). {self.caption}"

    @property
    def markdown_reference(self) -> str:
        return f"[See {self.label}](#{self.anchor})."


class PublicationCounter:
    """Issue independent section-based figure and table numbers."""

    def __init__(self, section: str = "0", separator: str = ".") -> None:
        self._separator = separator
        self.enter_section(section)

    def enter_section(self, section: str) -> None:
        section = str(section).strip()
        if not section:
            raise PublicationInventoryError("A publication section is required.")
        self._section = section
        self._counts = {"Figure": 0, "Table": 0}

    def next(self, kind: str, caption: str) -> PublicationIdentity:
        if kind not in self._counts:
            raise PublicationInventoryError(
                f"Unsupported publication item kind: {kind!r}."
            )
        self._counts[kind] += 1
        number = f"{self._section}{self._separator}{self._counts[kind]}"
        return PublicationIdentity(kind, number, caption)


@dataclass(frozen=True)
class PublishedManualBlock:
    """A retained manual block and its optional figure/table identity."""

    block: tuple
    item: PublicationIdentity | None


# Exact authored subjects for the 17 retained manual tables, in block order.
# The inventory is intentionally independent of mutable header wording.
MANUAL_TABLE_CAPTIONS = (
    "Worked-example section and reinforcement comparison",
    "Analysis result views and their published evidence",
    "Reinforcement size input bases",
    "Quick Section builder shapes",
    "Vertical shear-link spacing limits",
    "Minimum-reinforcement methods by edition",
    "Crack-width method differences",
    "Grouped-fatigue input fields",
    "Fatigue resistance bases by edition",
    "Shear components and associated bending",
    "Implemented shear methods",
    "Action tables, row fields and row-specific rules",
    "Worked brittle-failure Method B calculation",
    "Worked crack-width comparison by edition",
    "Fatigue editions, reinforcement scope and concrete scope",
    "Standards and reference sources",
    "Glossary of symbols and terms",
)


def published_manual_blocks(blocks: Iterable[tuple]) -> tuple[PublishedManualBlock, ...]:
    """Bind the exact manual figure/table inventory to stable section IDs."""

    published: list[PublishedManualBlock] = []
    table_index = 0
    part_code = None
    section_number = 0
    counter = None

    for block in blocks:
        kind = block[0]
        if kind == "part":
            match = re.match(r"^Part ([A-Z])\b", str(block[1]))
            if match is None:
                raise PublicationInventoryError(
                    f"Manual part identity is not publication-safe: {block[1]!r}."
                )
            part_code = match.group(1)
            section_number = 0
            counter = None
        elif kind == "h1":
            if part_code is None:
                raise PublicationInventoryError(
                    "A manual section appeared before its part identity."
                )
            section_number += 1
            counter = PublicationCounter(
                f"{part_code}{section_number}", separator="-"
            )

        item = None
        if kind in ("figure", "table"):
            if counter is None:
                raise PublicationInventoryError(
                    f"A manual {kind} appeared before a numbered section."
                )
            if kind == "figure":
                caption = str(block[2]).strip()
                item = counter.next("Figure", caption)
            else:
                if table_index >= len(MANUAL_TABLE_CAPTIONS):
                    raise PublicationInventoryError(
                        "The manual contains an uncontracted table."
                    )
                caption = MANUAL_TABLE_CAPTIONS[table_index]
                table_index += 1
                item = counter.next("Table", caption)
        published.append(PublishedManualBlock(block, item))

    if table_index != len(MANUAL_TABLE_CAPTIONS):
        raise PublicationInventoryError(
            "The retained manual table inventory is incomplete: "
            f"expected {len(MANUAL_TABLE_CAPTIONS)}, found {table_index}."
        )

    items = [entry.item for entry in published if entry.item is not None]
    labels = [item.label for item in items]
    anchors = [item.anchor for item in items]
    if len(labels) != len(set(labels)) or len(anchors) != len(set(anchors)):
        raise PublicationInventoryError(
            "Manual publication labels and anchors must be globally unique."
        )
    return tuple(published)


def published_manual_parts(
    blocks: Iterable[tuple],
) -> dict[str, list[PublishedManualBlock]]:
    """Group the contracted publication stream without dropping item metadata."""

    parts: dict[str, list[PublishedManualBlock]] = {}
    current = None
    for entry in published_manual_blocks(blocks):
        if entry.block[0] == "part":
            current = entry.block[1]
            parts[current] = [entry]
        elif current is not None:
            parts[current].append(entry)
    return parts
