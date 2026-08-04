"""Frozen identity and authored location of Part C manual equations.

This module deliberately owns no source, symbol, unit, dimensional, dependency
or rendering field.  Those independent publication contracts are added only by
later PR-11 slices after this authored equation spine is accepted.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Iterable


PART_C = "Part C - Theory & methodology"
_DISPLAY_RE = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
_KEY_RE = re.compile(r"[a-z0-9]+(?:[.-][a-z0-9]+)*")
_NUMBER_RE = re.compile(r"C[0-9]+-[0-9]+")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class ManualEquationLocation:
    """One equation's immutable authored identity and location."""

    ordinal: int
    key: str
    number: str
    part: str
    section: str
    subsection: str
    expression_sha256: str


@dataclass(frozen=True, slots=True)
class RegisteredManualEquationLocation:
    """A canonical location bound to the expression found in the manual."""

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
        "a9125f6b7747160f86ebfe580b489be8e94a3719ff435f274d411ee1cb1c5cda",
    ),
    _location(
        5, "manual.detailing.minimum-2005", "C5-1",
        "Reinforcement detailing", "EN 1992-1-1:2005 and DK NA:2024",
        "7e00772db83d146d7df046f67ea3d9830cd8f1c2210d0421e2dbf57c42265a6b",
    ),
    _location(
        6, "manual.detailing.minimum-2023-bending", "C5-2",
        "Reinforcement detailing", "EN 1992-1-1:2023",
        "a3e8a44022ab1eeac1eb1e85361b1735d337f4289aabfa4748a06a31eb7f8c9d",
    ),
    _location(
        7, "manual.detailing.minimum-2023-axial", "C5-3",
        "Reinforcement detailing", "EN 1992-1-1:2023",
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
        14, "manual.crack.2023.width", "C7-3",
        "Serviceability: cracking and crack width",
        "EN 1992-1-1:2023 refined model",
        "4c15d71e9d8e368108149af68afc41acc767712cd71aa1ad7af0223bb5ae3d10",
    ),
    _location(
        15, "manual.crack.2023.spacing", "C7-4",
        "Serviceability: cracking and crack width",
        "EN 1992-1-1:2023 refined model",
        "3232760c0b31c26275f004adf2bf978d25bf8452b182b6966e3bfeb455cae8ea",
    ),
    _location(
        16, "manual.fatigue.stress-range", "C8-1", "Grouped fatigue",
        "Elastic stress ranges",
        "1c6d20674b30556d5158662f2eed158f78f16c0ec52b6134bf9ee4e728707878",
    ),
    _location(
        17, "manual.fatigue.reinforcement.design-range", "C8-2",
        "Grouped fatigue", "Reinforcement S-N and Miner check",
        "79409e2d84eb04d50e0b3ecdb1a23cbaee4988c086d4d63375c8dc87267f5514",
    ),
    _location(
        18, "manual.fatigue.reinforcement.life", "C8-3",
        "Grouped fatigue", "Reinforcement S-N and Miner check",
        "525ca21ac74aa72c0202fba278ff55bfc0e4c951c7c4b29a1d0776e657bad217",
    ),
    _location(
        19, "manual.fatigue.reinforcement.miner", "C8-4",
        "Grouped fatigue", "Reinforcement S-N and Miner check",
        "ace577b8ce30e7129bda1cc84198419a4fea29b0472f100afe793caddca79564",
    ),
    _location(
        20, "manual.fatigue.concrete.strength-2005", "C8-5",
        "Grouped fatigue", "Concrete compression fatigue",
        "5123cf1171bbf2a16ddc81bf351ebaff1c8aa4f26bdec70f846f81f1a1b68ce9",
    ),
    _location(
        21, "manual.fatigue.concrete.strength-2023", "C8-6",
        "Grouped fatigue", "Concrete compression fatigue",
        "85e38c135904be5a3507e919a0649d9c209549ebb4ee3f0875ac978984e09eda",
    ),
    _location(
        22, "manual.fatigue.concrete.life", "C8-7", "Grouped fatigue",
        "Concrete compression fatigue",
        "5a8cca7a9e50c8a23d37882d0fb575d459dcd187d9fd4e2a4c580da5cf154528",
    ),
    _location(
        23, "manual.fatigue.concrete.equivalent", "C8-8",
        "Grouped fatigue", "Concrete compression fatigue",
        "4a70d70fdded41c242471c53a26554257d8444562547f5763c882c00a137bdcf",
    ),
    _location(
        24, "manual.shear.no-links.variable", "C9-1",
        "Shear resistance without shear reinforcement", "",
        "e5a101ffeb8ed99a3ad22d269c843d73ab17a4830858ddcec135b958a9d0ee6c",
    ),
    _location(
        25, "manual.shear.no-links.minimum", "C9-2",
        "Shear resistance without shear reinforcement", "",
        "1279f09a95518892baa612be76e48350f9cf565aed5efd94aecadcf165c7cc67",
    ),
    _location(
        26, "manual.shear.action-factor-2023", "C9-3",
        "Shear resistance without shear reinforcement", "",
        "57910d0569783bc00ef2c62b0755400dc51059b6ffd96017e3f7b50d92a5190d",
    ),
    _location(
        27, "manual.shear.links-2005", "C9-4",
        "Shear resistance without shear reinforcement",
        "Members with shear reinforcement (links)",
        "8bbbf0a6261d72eea45965ba33b6b45bb65ff56f67fa308f8020f7f01598aed7",
    ),
    _location(
        28, "manual.shear.links-2023", "C9-5",
        "Shear resistance without shear reinforcement",
        "Members with shear reinforcement (links)",
        "85cfe8d83d492a4af5a911a3a7c1dc332f88dcf75ae2b1434c6ed6fef91d3439",
    ),
    _location(
        29, "manual.torsion.resistance", "C10-1",
        "Torsion (thin-walled tube)", "",
        "a5291e17e74a23e3ec4f59d6a894be40eb72247ab67a266cb5f0a7d14667bff6",
    ),
    _location(
        30, "manual.torsion.strut-interaction", "C10-2",
        "Torsion (thin-walled tube)", "",
        "0fde836b7555c3d5e63a45cc971b43eb8b53aeb68405c7294673b1704575b79b",
    ),
    _location(
        31, "manual.combined.strut-interaction", "C11-1",
        "Combined M-V-T interaction", "",
        "0fde836b7555c3d5e63a45cc971b43eb8b53aeb68405c7294673b1704575b79b",
    ),
    _location(
        32, "manual.combined.utilisation", "C11-2",
        "Combined M-V-T interaction", "",
        "850bd52dcea64b9e779bc904fa701d42d2d47657af17ea0f1ab0f32263f3ab8b",
    ),
)


def _normalise_expression(expression: str) -> str:
    value = re.sub(r"\s+", " ", expression).strip()
    if not value or not value.isascii():
        raise ValueError("Manual display equation must be non-empty ASCII text.")
    return value


def _text_fields(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _text_fields(key)
            yield from _text_fields(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from _text_fields(item)


def _extract_part_c_equations(
    blocks: Iterable[tuple[str, object]],
) -> tuple[tuple[str, str, str, str], ...]:
    part = ""
    section = ""
    subsection = ""
    extracted: list[tuple[str, str, str, str]] = []

    for block in blocks:
        if not isinstance(block, tuple) or len(block) < 2:
            raise ValueError("Malformed manual block encountered.")
        kind, payload = block[0], block[1]
        if not isinstance(kind, str):
            raise ValueError("Manual block kind must retain string identity.")
        if kind in {"part", "h1", "h2", "md"} and not isinstance(payload, str):
            raise ValueError(f"Manual {kind} block must retain string content.")
        if kind == "part":
            part = payload
            section = ""
            subsection = ""
            if part == PART_C and any(
                "$$" in text for text in _text_fields(block[2:])
            ):
                raise ValueError(
                    "Part C display equation must remain in Markdown content."
                )
        elif kind == "h1":
            section = payload
            subsection = ""
            if part == PART_C and any(
                "$$" in text for text in _text_fields(block[2:])
            ):
                raise ValueError(
                    "Part C display equation must remain in Markdown content."
                )
        elif kind == "h2":
            subsection = payload
            if part == PART_C and any(
                "$$" in text for text in _text_fields(block[2:])
            ):
                raise ValueError(
                    "Part C display equation must remain in Markdown content."
                )
        elif kind == "md" and part == PART_C:
            if payload.count("$$") % 2:
                raise ValueError("Malformed Part C display-equation delimiter.")
            for raw_expression in _DISPLAY_RE.findall(payload):
                expression = _normalise_expression(raw_expression)
                extracted.append((part, section, subsection, expression))
            if any("$$" in text for text in _text_fields(block[2:])):
                raise ValueError(
                    "Part C display equation must remain in Markdown content."
                )
        elif part == PART_C and any(
            "$$" in text for text in _text_fields(block[1:])
        ):
            raise ValueError(
                "Part C display equation must remain in Markdown content."
            )
    return tuple(extracted)


def _validate_catalogue() -> None:
    if len(MANUAL_EQUATION_LOCATIONS) != 32:
        raise RuntimeError("Expected exactly 32 Part C equation locations.")
    if tuple(item.ordinal for item in MANUAL_EQUATION_LOCATIONS) != tuple(
        range(1, 33)
    ):
        raise RuntimeError("Manual equation ordinals are not contiguous.")
    keys = tuple(item.key for item in MANUAL_EQUATION_LOCATIONS)
    numbers = tuple(item.number for item in MANUAL_EQUATION_LOCATIONS)
    if len(set(keys)) != len(keys) or len(set(numbers)) != len(numbers):
        raise RuntimeError("Manual equation keys and numbers must be unique.")
    for item in MANUAL_EQUATION_LOCATIONS:
        if not _KEY_RE.fullmatch(item.key):
            raise RuntimeError(f"Invalid manual equation key: {item.key!r}.")
        if not _NUMBER_RE.fullmatch(item.number):
            raise RuntimeError(f"Invalid manual equation number: {item.number!r}.")
        if item.part != PART_C or not item.section:
            raise RuntimeError(f"Incomplete manual equation location: {item.key!r}.")
        if not _SHA256_RE.fullmatch(item.expression_sha256):
            raise RuntimeError(f"Invalid expression digest: {item.key!r}.")
        if not all(
            value.isascii()
            for value in (
                item.key, item.number, item.part, item.section, item.subsection,
                item.expression_sha256,
            )
        ):
            raise RuntimeError(f"Non-ASCII manual equation identity: {item.key!r}.")


_validate_catalogue()


def register_manual_equation_locations(
    blocks: Iterable[tuple[str, object]],
    catalogue: Iterable[ManualEquationLocation] = MANUAL_EQUATION_LOCATIONS,
) -> tuple[RegisteredManualEquationLocation, ...]:
    """Bind the exact canonical Part C location catalogue to authored equations."""

    candidate = tuple(catalogue)
    if candidate != MANUAL_EQUATION_LOCATIONS:
        raise ValueError("Canonical manual equation location catalogue changed.")

    extracted = _extract_part_c_equations(blocks)
    if len(extracted) != len(MANUAL_EQUATION_LOCATIONS):
        raise ValueError(
            "Part C equation cardinality changed: expected "
            f"{len(MANUAL_EQUATION_LOCATIONS)}, got {len(extracted)}."
        )

    registered: list[RegisteredManualEquationLocation] = []
    for expected, (part, section, subsection, expression) in zip(
        MANUAL_EQUATION_LOCATIONS, extracted
    ):
        if (part, section, subsection) != (
            expected.part, expected.section, expected.subsection
        ):
            raise ValueError(f"Manual equation {expected.number} moved.")
        digest = hashlib.sha256(expression.encode("ascii")).hexdigest()
        if digest != expected.expression_sha256:
            raise ValueError(f"Manual equation {expected.number} expression changed.")
        registered.append(RegisteredManualEquationLocation(expected, expression))
    return tuple(registered)


def location_catalogue_sha256() -> str:
    """Return the frozen seal of the complete location catalogue."""

    rows = (
        "\x1f".join(
            (
                str(item.ordinal), item.key, item.number, item.part, item.section,
                item.subsection, item.expression_sha256,
            )
        )
        for item in MANUAL_EQUATION_LOCATIONS
    )
    return hashlib.sha256("\x1e".join(rows).encode("ascii")).hexdigest()
