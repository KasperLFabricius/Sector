"""Immutable identity and authored location for Part C manual equations.

This bounded module owns only the equation spine. Provenance, symbols, units,
dimensions, dependencies and rendering belong to later PR-11 slices.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence, Set
from dataclasses import dataclass
import hashlib
import re


PART_C = "Part C - Theory & methodology"
DISPLAY_DELIMITER = "$$"
_KEY = re.compile(r"[a-z0-9]+(?:[.-][a-z0-9]+)*")
_NUMBER = re.compile(r"C[0-9]+-[0-9]+")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_STRUCTURAL_KINDS = frozenset(("part", "h1", "h2", "md"))


@dataclass(frozen=True, slots=True)
class ManualEquationLocation:
    """One equation's complete immutable identity and authored location."""

    ordinal: int
    key: str
    number: str
    part: str
    section: str
    subsection: str
    expression_sha256: str


@dataclass(frozen=True, slots=True)
class LocatedManualEquation:
    """A frozen location bound to the exact expression found in the manual."""

    location: ManualEquationLocation
    expression: str


def _location(
    ordinal: int,
    key: str,
    number: str,
    section: str,
    subsection: str,
    expression_sha256: str,
) -> ManualEquationLocation:
    return ManualEquationLocation(
        ordinal=ordinal,
        key=key,
        number=number,
        part=PART_C,
        section=section,
        subsection=subsection,
        expression_sha256=expression_sha256,
    )


MANUAL_EQUATION_LOCATIONS = (
    _location(
        1, "manual.material.concrete-law", "C3-1", "Material laws",
        "Concrete (parabola-rectangle)",
        "9056b4525fcd292ebd5769b7277ae491522d54ea6e8ee60f79d4ee0af2da6477",
    ),
    _location(
        2, "manual.material.steel-law", "C3-2", "Material laws",
        "Mild steel",
        "5972f92c2cf2dd2c16ab580e95c70f98ebe947a2baaef960c67252ac294a9c11",
    ),
    _location(
        3, "manual.material.prestress-law", "C3-3", "Material laws",
        "Prestressing steel",
        "e61a85aca0ae68096eae6d42740d5e556e839b765c69ec57f61ecc5c146cbaa5",
    ),
    _location(
        4, "manual.plastic.governing-curvature", "C4-1",
        "Plastic capacity analysis", "The governing curvature",
        "b7d2d42c417b87d22ce6eab64d35bd507eac0fd1395473841b00f0934ccadb6c",
    ),
    _location(
        5, "manual.detailing.minimum-2005", "C5-1",
        "Reinforcement detailing", "EN 1992-1-1:2005 and DK NA:2024",
        "7e00772db83d146d7df046f67ea3d9830cd8f1c2210d0421e2dbf57c42265a6b",
    ),
    _location(
        6, "manual.detailing.minimum-2023-bending", "C5-2",
        "Reinforcement detailing", "DS/EN 1992-1-1:2023",
        "a3e8a44022ab1eeac1eb1e85361b1735d337f4289aabfa4748a06a31eb7f8c9d",
    ),
    _location(
        7, "manual.detailing.minimum-2023-axial", "C5-3",
        "Reinforcement detailing", "DS/EN 1992-1-1:2023",
        "f52a3042781e1a85e83ae53f1e0031d3e5828a191421ba1c00bb968e81587822",
    ),
    _location(
        8, "manual.detailing.clear-spacing", "C5-4",
        "Reinforcement detailing", "Clear spacing",
        "f41ec7e90828e88a52fe0d33bb42a5637f4e92b874b2f3576f0c112b34bdfc46",
    ),
    _location(
        9, "manual.detailing.links.minimum-ratio", "C5-5",
        "Reinforcement detailing", "Shear and torsion reinforcement",
        "e39e98501124b045f90745c456fc6947ff91331fae7c48b4a107c95e6f89536b",
    ),
    _location(
        10, "manual.detailing.links.spacing", "C5-6",
        "Reinforcement detailing", "Shear and torsion reinforcement",
        "46578627e65dc94444a986bcd27740da82bd1c07073227810451b24b18498144",
    ),
    _location(
        11, "manual.detailing.torsion.minimum-ratio", "C5-7",
        "Reinforcement detailing", "Shear and torsion reinforcement",
        "10d5445bf8ce120f10d189ac9cce5c24d2c6d3018f122cd1ae4cd680488f13e9",
    ),
    _location(
        12, "manual.crack.2005.width", "C7-1",
        "Serviceability: cracking and crack width",
        "Crack width - EN 1992-1-1:2005",
        "4451827db7ec3ec1f7c7f07f3660b6ba6cf2cb44dd35f56b63595a2d594bfc42",
    ),
    _location(
        13, "manual.crack.2005.spacing", "C7-2",
        "Serviceability: cracking and crack width",
        "Crack width - EN 1992-1-1:2005",
        "e674c66afb21190f639015cce8da6a954fdcc19f8ddd326020667e25536c8fe3",
    ),
    _location(
        14, "manual.crack.dk-na-heightened", "C7-5",
        "Serviceability: cracking and crack width",
        "DK NA heightened crack-control minimum",
        "23ab63d96b5151f131dc2679f1c799de51a2b250febbfbcafea908999e0c7371",
    ),
    _location(
        15, "manual.crack.2023.width", "C7-3",
        "Serviceability: cracking and crack width",
        "DS/EN 1992-1-1:2023 refined model",
        "4c15d71e9d8e368108149af68afc41acc767712cd71aa1ad7af0223bb5ae3d10",
    ),
    _location(
        16, "manual.crack.2023.spacing", "C7-4",
        "Serviceability: cracking and crack width",
        "DS/EN 1992-1-1:2023 refined model",
        "3232760c0b31c26275f004adf2bf978d25bf8452b182b6966e3bfeb455cae8ea",
    ),
    _location(
        17, "manual.fatigue.stress-range", "C8-1", "Grouped fatigue",
        "Elastic stress ranges",
        "1c6d20674b30556d5158662f2eed158f78f16c0ec52b6134bf9ee4e728707878",
    ),
    _location(
        18, "manual.fatigue.reinforcement.design-range", "C8-2",
        "Grouped fatigue", "Reinforcement S-N and Miner check",
        "79409e2d84eb04d50e0b3ecdb1a23cbaee4988c086d4d63375c8dc87267f5514",
    ),
    _location(
        19, "manual.fatigue.reinforcement.life", "C8-3",
        "Grouped fatigue", "Reinforcement S-N and Miner check",
        "525ca21ac74aa72c0202fba278ff55bfc0e4c951c7c4b29a1d0776e657bad217",
    ),
    _location(
        20, "manual.fatigue.reinforcement.miner", "C8-4",
        "Grouped fatigue", "Reinforcement S-N and Miner check",
        "ace577b8ce30e7129bda1cc84198419a4fea29b0472f100afe793caddca79564",
    ),
    _location(
        21, "manual.fatigue.concrete.strength-2005", "C8-5",
        "Grouped fatigue", "Concrete compression fatigue",
        "5123cf1171bbf2a16ddc81bf351ebaff1c8aa4f26bdec70f846f81f1a1b68ce9",
    ),
    _location(
        22, "manual.fatigue.concrete.strength-2023", "C8-6",
        "Grouped fatigue", "Concrete compression fatigue",
        "85e38c135904be5a3507e919a0649d9c209549ebb4ee3f0875ac978984e09eda",
    ),
    _location(
        23, "manual.fatigue.concrete.life", "C8-7", "Grouped fatigue",
        "Concrete compression fatigue",
        "5a8cca7a9e50c8a23d37882d0fb575d459dcd187d9fd4e2a4c580da5cf154528",
    ),
    _location(
        24, "manual.fatigue.concrete.equivalent", "C8-8",
        "Grouped fatigue", "Concrete compression fatigue",
        "4a70d70fdded41c242471c53a26554257d8444562547f5763c882c00a137bdcf",
    ),
    _location(
        25, "manual.shear.no-links.variable", "C9-1",
        "Shear resistance without shear reinforcement", "",
        "e5a101ffeb8ed99a3ad22d269c843d73ab17a4830858ddcec135b958a9d0ee6c",
    ),
    _location(
        26, "manual.shear.no-links.minimum", "C9-2",
        "Shear resistance without shear reinforcement", "",
        "1279f09a95518892baa612be76e48350f9cf565aed5efd94aecadcf165c7cc67",
    ),
    _location(
        27, "manual.shear.action-factor-2023", "C9-3",
        "Shear resistance without shear reinforcement", "",
        "57910d0569783bc00ef2c62b0755400dc51059b6ffd96017e3f7b50d92a5190d",
    ),
    _location(
        28, "manual.shear.links-2005", "C9-4",
        "Shear resistance without shear reinforcement",
        "Members with shear reinforcement (links)",
        "8bbbf0a6261d72eea45965ba33b6b45bb65ff56f67fa308f8020f7f01598aed7",
    ),
    _location(
        29, "manual.shear.links-2023", "C9-5",
        "Shear resistance without shear reinforcement",
        "Members with shear reinforcement (links)",
        "85cfe8d83d492a4af5a911a3a7c1dc332f88dcf75ae2b1434c6ed6fef91d3439",
    ),
    _location(
        30, "manual.torsion.resistance", "C10-1",
        "Torsion (thin-walled tube)", "",
        "a5291e17e74a23e3ec4f59d6a894be40eb72247ab67a266cb5f0a7d14667bff6",
    ),
    _location(
        31, "manual.torsion.strut-interaction", "C10-2",
        "Torsion (thin-walled tube)", "",
        "0fde836b7555c3d5e63a45cc971b43eb8b53aeb68405c7294673b1704575b79b",
    ),
    _location(
        32, "manual.combined.strut-interaction", "C11-1",
        "Combined M-V-T interaction", "",
        "0fde836b7555c3d5e63a45cc971b43eb8b53aeb68405c7294673b1704575b79b",
    ),
    _location(
        33, "manual.combined.utilisation", "C11-2",
        "Combined M-V-T interaction", "",
        "850bd52dcea64b9e779bc904fa701d42d2d47657af17ea0f1ab0f32263f3ab8b",
    ),
)


def _normalise_expression(raw: str) -> str:
    expression = re.sub(r"\s+", " ", raw).strip()
    if not expression:
        raise ValueError("Part C display equation must not be empty.")
    if not expression.isascii():
        raise ValueError("Part C display equation must retain ASCII text.")
    return expression


def _nested_strings(value: object) -> Iterable[str]:
    """Yield all textual leaves without trusting one container position."""

    pending = [value]
    visited: set[int] = set()
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            yield item
            continue
        if isinstance(item, Mapping):
            identity = id(item)
            if identity in visited:
                continue
            visited.add(identity)
            for key, nested in item.items():
                pending.append(key)
                pending.append(nested)
            continue
        if isinstance(item, (Sequence, Set)):
            identity = id(item)
            if identity in visited:
                continue
            visited.add(identity)
            pending.extend(item)


def _contains_display(value: object) -> bool:
    return any(DISPLAY_DELIMITER in text for text in _nested_strings(value))


def _markdown_displays(markdown: str) -> tuple[str, ...]:
    fragments = markdown.split(DISPLAY_DELIMITER)
    if len(fragments) % 2 == 0:
        raise ValueError("Part C contains an unpaired display delimiter.")
    return tuple(_normalise_expression(raw) for raw in fragments[1::2])


def _extract_part_c(
    blocks: Iterable[tuple[str, object]],
) -> tuple[tuple[str, str, str, str], ...]:
    part = ""
    section = ""
    subsection = ""
    extracted: list[tuple[str, str, str, str]] = []

    for block in blocks:
        if not isinstance(block, tuple) or len(block) < 2:
            raise ValueError("Manual block must remain a tuple with two fields.")
        kind = block[0]
        if not isinstance(kind, str):
            raise ValueError("Manual block kind must retain string identity.")
        payload = block[1]
        if kind in _STRUCTURAL_KINDS and not isinstance(payload, str):
            raise ValueError(f"Manual {kind} payload must retain string type.")

        if kind == "part":
            if (part == PART_C or payload == PART_C) and _contains_display(block[1:]):
                raise ValueError("Part C structural fields cannot contain displays.")
            part = payload
            section = ""
            subsection = ""
            continue

        if part != PART_C:
            continue

        if kind == "h1":
            if _contains_display(block[1:]):
                raise ValueError("Part C structural fields cannot contain displays.")
            section = payload
            subsection = ""
        elif kind == "h2":
            if _contains_display(block[1:]):
                raise ValueError("Part C structural fields cannot contain displays.")
            subsection = payload
        elif kind == "md":
            if _contains_display(block[2:]):
                raise ValueError("Part C displays must remain in Markdown payloads.")
            for expression in _markdown_displays(payload):
                extracted.append((part, section, subsection, expression))
        elif _contains_display(block):
            raise ValueError("Part C displays must remain in Markdown payloads.")

    return tuple(extracted)


def _validate_catalogue() -> None:
    if len(MANUAL_EQUATION_LOCATIONS) != 33:
        raise RuntimeError("Expected exactly 33 manual equation locations.")
    if tuple(item.ordinal for item in MANUAL_EQUATION_LOCATIONS) != tuple(
        range(1, 34)
    ):
        raise RuntimeError("Manual equation ordinals must be contiguous.")
    keys = tuple(item.key for item in MANUAL_EQUATION_LOCATIONS)
    numbers = tuple(item.number for item in MANUAL_EQUATION_LOCATIONS)
    if len(set(keys)) != 33 or len(set(numbers)) != 33:
        raise RuntimeError("Manual equation keys and numbers must be unique.")
    for item in MANUAL_EQUATION_LOCATIONS:
        if not _KEY.fullmatch(item.key):
            raise RuntimeError(f"Invalid equation key: {item.key!r}.")
        if not _NUMBER.fullmatch(item.number):
            raise RuntimeError(f"Invalid equation number: {item.number!r}.")
        if item.part != PART_C or not item.section:
            raise RuntimeError(f"Incomplete equation location: {item.key!r}.")
        if not _DIGEST.fullmatch(item.expression_sha256):
            raise RuntimeError(f"Invalid equation digest: {item.key!r}.")
        if not all(
            text.isascii()
            for text in (
                item.key,
                item.number,
                item.part,
                item.section,
                item.subsection,
                item.expression_sha256,
            )
        ):
            raise RuntimeError(f"Non-ASCII equation identity: {item.key!r}.")


_validate_catalogue()


def register_manual_equation_locations(
    blocks: Iterable[tuple[str, object]],
    catalogue: Iterable[ManualEquationLocation] = MANUAL_EQUATION_LOCATIONS,
) -> tuple[LocatedManualEquation, ...]:
    """Bind the canonical location catalogue to the live Part C displays."""

    supplied = tuple(catalogue)
    if supplied != MANUAL_EQUATION_LOCATIONS:
        raise ValueError("Canonical manual equation location catalogue changed.")

    extracted = _extract_part_c(blocks)
    if len(extracted) != 33:
        raise ValueError(
            f"Part C equation cardinality changed: expected 33, got {len(extracted)}."
        )

    located: list[LocatedManualEquation] = []
    for expected, (part, section, subsection, expression) in zip(
        MANUAL_EQUATION_LOCATIONS, extracted
    ):
        if (part, section, subsection) != (
            expected.part,
            expected.section,
            expected.subsection,
        ):
            raise ValueError(f"Manual equation {expected.number} moved.")
        digest = hashlib.sha256(expression.encode("ascii")).hexdigest()
        if digest != expected.expression_sha256:
            raise ValueError(f"Manual equation {expected.number} expression changed.")
        located.append(LocatedManualEquation(expected, expression))
    return tuple(located)


def location_catalogue_sha256() -> str:
    """Return a deterministic seal of every retained catalogue field."""

    rows = (
        "\x1f".join(
            (
                str(item.ordinal),
                item.key,
                item.number,
                item.part,
                item.section,
                item.subsection,
                item.expression_sha256,
            )
        )
        for item in MANUAL_EQUATION_LOCATIONS
    )
    return hashlib.sha256("\x1e".join(rows).encode("ascii")).hexdigest()
