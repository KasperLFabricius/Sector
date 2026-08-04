"""Authored identity and source catalogue for Part C manual equations.

Only Part C display equations are in scope.  Symbol, dimensional, dependency and
renderer contracts intentionally belong to later PR-11A3 slices.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Iterable, Sequence


PART_C = "Part C - Theory & methodology"
_DISPLAY_RE = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
_KEY_RE = re.compile(r"manual\.[a-z0-9]+(?:[.-][a-z0-9]+)*\Z")
_NUMBER_RE = re.compile(r"C(?:3|4|5|7|8|9|10|11)-[1-9][0-9]*\Z")
_SOURCE_KINDS = frozenset({"standard", "mixed", "project"})


@dataclass(frozen=True, slots=True)
class ManualEquationIdentity:
    ordinal: int
    key: str
    number: str
    part: str
    section: str
    subsection: str
    expression_sha256: str
    source_kind: str
    source: str


@dataclass(frozen=True, slots=True)
class RegisteredManualEquationIdentity:
    identity: ManualEquationIdentity
    expression: str


def _identity(
    ordinal: int,
    key: str,
    number: str,
    section: str,
    subsection: str,
    digest: str,
    source_kind: str,
    source: str,
) -> ManualEquationIdentity:
    return ManualEquationIdentity(
        ordinal, key, number, PART_C, section, subsection, digest,
        source_kind, source,
    )


MANUAL_EQUATION_IDENTITIES = (
    _identity(
        1, "manual.material.concrete-law", "C3-1", "Material laws",
        "Concrete (parabola-rectangle)",
        "9056b4525fcd292ebd5769b7277ae491522d54ea6e8ee60f79d4ee0af2da6477",
        "standard",
        "DS/EN 1992-1-1 3.1.7, Formula (3.17), with the selected edition's material parameters.",
    ),
    _identity(
        2, "manual.material.steel-law", "C3-2", "Material laws", "Mild steel",
        "5972f92c2cf2dd2c16ab580e95c70f98ebe947a2baaef960c67252ac294a9c11",
        "project",
        "Project-defined editable general Curve 3 law; no normative citation assigned.",
    ),
    _identity(
        3, "manual.material.prestress-law", "C3-3", "Material laws",
        "Prestressing steel",
        "e61a85aca0ae68096eae6d42740d5e556e839b765c69ec57f61ecc5c146cbaa5",
        "mixed",
        "Project locked-in-strain convention; DS/EN 1992-1-1 3.3.6 for the selected prestressing-steel law.",
    ),
    _identity(
        4, "manual.plastic.governing-curvature", "C4-1",
        "Plastic capacity analysis", "The governing curvature",
        "a9125f6b7747160f86ebfe580b489be8e94a3719ff435f274d411ee1cb1c5cda",
        "project",
        "Project-defined capacity-search selector over retained material strain limits; no normative solver citation assigned.",
    ),
    _identity(
        5, "manual.detailing.minimum-2005", "C5-1", "Reinforcement detailing",
        "EN 1992-1-1:2005 and DK NA:2024",
        "7e00772db83d146d7df046f67ea3d9830cd8f1c2210d0421e2dbf57c42265a6b",
        "standard",
        "DS/EN 1992-1-1:2005 9.2.1.1(1), Formula (9.1N); DK NA:2024 where selected.",
    ),
    _identity(
        6, "manual.detailing.minimum-2023-bending", "C5-2",
        "Reinforcement detailing", "EN 1992-1-1:2023",
        "a3e8a44022ab1eeac1eb1e85361b1735d337f4289aabfa4748a06a31eb7f8c9d",
        "standard", "DS/EN 1992-1-1:2023 12.2(2)(a), Formula (12.1).",
    ),
    _identity(
        7, "manual.detailing.minimum-2023-axial", "C5-3",
        "Reinforcement detailing", "EN 1992-1-1:2023",
        "f52a3042781e1a85e83ae53f1e0031d3e5828a191421ba1c00bb968e81587822",
        "standard", "DS/EN 1992-1-1:2023 12.2(2)(b), Formula (12.2).",
    ),
    _identity(
        8, "manual.detailing.clear-spacing", "C5-4", "Reinforcement detailing",
        "Clear spacing",
        "f41ec7e90828e88a52fe0d33bb42a5637f4e92b874b2f3576f0c112b34bdfc46",
        "standard",
        "DS/EN 1992-1-1:2005 8.2(2); DS/EN 1992-1-1:2023 11.2(2).",
    ),
    _identity(
        9, "manual.detailing.links.minimum-ratio", "C5-5",
        "Reinforcement detailing", "Shear and torsion reinforcement",
        "e39e98501124b045f90745c456fc6947ff91331fae7c48b4a107c95e6f89536b",
        "standard",
        "DS/EN 1992-1-1:2005 9.2.2(5), Formulas (9.4)-(9.5), with DK NA:2024 coefficient where selected; DS/EN 1992-1-1:2023 12.2(4), Formula (12.4).",
    ),
    _identity(
        10, "manual.detailing.links.spacing", "C5-6", "Reinforcement detailing",
        "Shear and torsion reinforcement",
        "46578627e65dc94444a986bcd27740da82bd1c07073227810451b24b18498144",
        "standard",
        "DS/EN 1992-1-1:2005 9.2.2(5)-(8), Formulas (9.4)-(9.8); DS/EN 1992-1-1:2023 12.2(4), Tables 12.1-12.2.",
    ),
    _identity(
        11, "manual.detailing.torsion.minimum-ratio", "C5-7",
        "Reinforcement detailing", "Shear and torsion reinforcement",
        "10d5445bf8ce120f10d189ac9cce5c24d2c6d3018f122cd1ae4cd680488f13e9",
        "standard",
        "DS/EN 1992-1-1:2005 9.2.2(5), Formulas (9.4)-(9.5), applied to the effective torsion wall.",
    ),
    _identity(
        12, "manual.crack.2005.width", "C7-1",
        "Serviceability: cracking and crack width",
        "Crack width - EN 1992-1-1:2005",
        "4451827db7ec3ec1f7c7f07f3660b6ba6cf2cb44dd35f56b63595a2d594bfc42",
        "standard", "DS/EN 1992-1-1:2005 7.3.4, Formulas (7.8)-(7.9).",
    ),
    _identity(
        13, "manual.crack.2005.spacing", "C7-2",
        "Serviceability: cracking and crack width",
        "Crack width - EN 1992-1-1:2005",
        "e674c66afb21190f639015cce8da6a954fdcc19f8ddd326020667e25536c8fe3",
        "standard",
        "DS/EN 1992-1-1:2005 Formulas (7.11) and (7.14); DK NA 7.3.4 where selected.",
    ),
    _identity(
        14, "manual.crack.2023.width", "C7-3",
        "Serviceability: cracking and crack width",
        "EN 1992-1-1:2023 refined model",
        "4c15d71e9d8e368108149af68afc41acc767712cd71aa1ad7af0223bb5ae3d10",
        "standard", "DS/EN 1992-1-1:2023 9.2.3, Formula (9.9).",
    ),
    _identity(
        15, "manual.crack.2023.spacing", "C7-4",
        "Serviceability: cracking and crack width",
        "EN 1992-1-1:2023 refined model",
        "3232760c0b31c26275f004adf2bf978d25bf8452b182b6966e3bfeb455cae8ea",
        "standard",
        "DS/EN 1992-1-1:2023 9.2.3, Formulas (9.15)-(9.18).",
    ),
    _identity(
        16, "manual.fatigue.stress-range", "C8-1", "Grouped fatigue",
        "Elastic stress ranges",
        "1c6d20674b30556d5158662f2eed158f78f16c0ec52b6134bf9ee4e728707878",
        "mixed",
        "Project replay of retained Elastic states; fatigue action factors from DS/EN 1992-1-1:2005+A1:2014 6.8.2 or DS/EN 1992-1-1:2023 Annex E.5.",
    ),
    _identity(
        17, "manual.fatigue.reinforcement.design-range", "C8-2",
        "Grouped fatigue", "Reinforcement S-N and Miner check",
        "79409e2d84eb04d50e0b3ecdb1a23cbaee4988c086d4d63375c8dc87267f5514",
        "standard",
        "DS/EN 1992-1-1:2005+A1:2014 6.8.4 and Tables 6.3N-6.4N; DS/EN 1992-1-1:2023 Annex E.5 and Tables E.1-E.2.",
    ),
    _identity(
        18, "manual.fatigue.reinforcement.life", "C8-3", "Grouped fatigue",
        "Reinforcement S-N and Miner check",
        "525ca21ac74aa72c0202fba278ff55bfc0e4c951c7c4b29a1d0776e657bad217",
        "standard",
        "DS/EN 1992-1-1:2005+A1:2014 6.8.4 and Tables 6.3N-6.4N; DS/EN 1992-1-1:2023 Annex E.5 and Tables E.1-E.2.",
    ),
    _identity(
        19, "manual.fatigue.reinforcement.miner", "C8-4", "Grouped fatigue",
        "Reinforcement S-N and Miner check",
        "ace577b8ce30e7129bda1cc84198419a4fea29b0472f100afe793caddca79564",
        "standard",
        "DS/EN 1992-1-1:2005+A1:2014 6.8.4; DS/EN 1992-1-1:2023 Annex E.5.",
    ),
    _identity(
        20, "manual.fatigue.concrete.strength-2005", "C8-5",
        "Grouped fatigue", "Concrete compression fatigue",
        "5123cf1171bbf2a16ddc81bf351ebaff1c8aa4f26bdec70f846f81f1a1b68ce9",
        "standard",
        "DS/EN 1992-1-1:2005+A1:2014 6.8.7, Formula (6.76).",
    ),
    _identity(
        21, "manual.fatigue.concrete.strength-2023", "C8-6",
        "Grouped fatigue", "Concrete compression fatigue",
        "85e38c135904be5a3507e919a0649d9c209549ebb4ee3f0875ac978984e09eda",
        "standard", "DS/EN 1992-1-1:2023 10.5, Formula (10.5).",
    ),
    _identity(
        22, "manual.fatigue.concrete.life", "C8-7", "Grouped fatigue",
        "Concrete compression fatigue",
        "5a8cca7a9e50c8a23d37882d0fb575d459dcd187d9fd4e2a4c580da5cf154528",
        "standard",
        "DS/EN 1992-2:2005/AC:2008 corrected Formula (6.106); DS/EN 1992-1-1:2023 E.5.3 where selected.",
    ),
    _identity(
        23, "manual.fatigue.concrete.equivalent", "C8-8", "Grouped fatigue",
        "Concrete compression fatigue",
        "4a70d70fdded41c242471c53a26554257d8444562547f5763c882c00a137bdcf",
        "standard",
        "DS/EN 1992-1-1:2005+A1:2014 6.8.7, Formula (6.72); "
        "DS/EN 1992-1-1:2023 E.4.3, Formula (E.2).",
    ),
    _identity(
        24, "manual.shear.no-links.variable", "C9-1",
        "Shear resistance without shear reinforcement", "",
        "e5a101ffeb8ed99a3ad22d269c843d73ab17a4830858ddcec135b958a9d0ee6c",
        "standard",
        "DS/EN 1992-1-1:2005 6.2.2(1), Formula (6.2a), with DK NA:2024 where selected.",
    ),
    _identity(
        25, "manual.shear.no-links.minimum", "C9-2",
        "Shear resistance without shear reinforcement", "",
        "1279f09a95518892baa612be76e48350f9cf565aed5efd94aecadcf165c7cc67",
        "standard",
        "DS/EN 1992-1-1:2005 6.2.2(1), Formula (6.2b), with DK NA:2024 where selected.",
    ),
    _identity(
        26, "manual.shear.action-factor-2023", "C9-3",
        "Shear resistance without shear reinforcement", "",
        "57910d0569783bc00ef2c62b0755400dc51059b6ffd96017e3f7b50d92a5190d",
        "standard",
        "DS/EN 1992-1-1:2023 8.2.2(4), Formulas (8.30) and (8.31).",
    ),
    _identity(
        27, "manual.shear.links-2005", "C9-4",
        "Shear resistance without shear reinforcement",
        "Members with shear reinforcement (links)",
        "8bbbf0a6261d72eea45965ba33b6b45bb65ff56f67fa308f8020f7f01598aed7",
        "standard", "DS/EN 1992-1-1:2005 6.2.3, Formulas (6.8)-(6.9).",
    ),
    _identity(
        28, "manual.shear.links-2023", "C9-5",
        "Shear resistance without shear reinforcement",
        "Members with shear reinforcement (links)",
        "85cfe8d83d492a4af5a911a3a7c1dc332f88dcf75ae2b1434c6ed6fef91d3439",
        "standard", "DS/EN 1992-1-1:2023 Formulas (8.42) and (8.44).",
    ),
    _identity(
        29, "manual.torsion.resistance", "C10-1", "Torsion (thin-walled tube)",
        "", "a5291e17e74a23e3ec4f59d6a894be40eb72247ab67a266cb5f0a7d14667bff6",
        "standard",
        "DS/EN 1992-1-1:2005 torsional wall shear flow Formula (6.27), transverse equilibrium Formula (6.8), and concrete-strut Formula (6.30).",
    ),
    _identity(
        30, "manual.torsion.strut-interaction", "C10-2",
        "Torsion (thin-walled tube)", "",
        "0fde836b7555c3d5e63a45cc971b43eb8b53aeb68405c7294673b1704575b79b",
        "standard", "DS/EN 1992-1-1:2005 Formula (6.29).",
    ),
    _identity(
        31, "manual.combined.strut-interaction", "C11-1",
        "Combined M-V-T interaction", "",
        "0fde836b7555c3d5e63a45cc971b43eb8b53aeb68405c7294673b1704575b79b",
        "standard", "DS/EN 1992-1-1:2005 Formula (6.29), reused by the combined check.",
    ),
    _identity(
        32, "manual.combined.utilisation", "C11-2",
        "Combined M-V-T interaction", "",
        "850bd52dcea64b9e779bc904fa701d42d2d47657af17ea0f1ab0f32263f3ab8b",
        "standard", "DK NA:2024 6.3.2(6).",
    ),
)


def _normalise_expression(expression: str) -> str:
    return " ".join(expression.split())


def _digest(expression: str) -> str:
    return hashlib.sha256(expression.encode("ascii")).hexdigest()


def _validate_canonical_catalogue() -> None:
    identities = MANUAL_EQUATION_IDENTITIES
    if len(identities) != 32:
        raise ValueError("The Part C identity catalogue must contain 32 equations.")
    if tuple(item.ordinal for item in identities) != tuple(range(1, 33)):
        raise ValueError("Manual equation ordinals must be contiguous and ordered.")
    keys = tuple(item.key for item in identities)
    numbers = tuple(item.number for item in identities)
    if len(set(keys)) != 32 or any(not _KEY_RE.fullmatch(key) for key in keys):
        raise ValueError("Manual equation keys must be unique and canonical.")
    if len(set(numbers)) != 32 or any(
        not _NUMBER_RE.fullmatch(number) for number in numbers
    ):
        raise ValueError("Manual equation numbers must be unique and section-based.")
    for item in identities:
        if item.part != PART_C or not item.section:
            raise ValueError(f"{item.key} has an invalid Part C location.")
        if not re.fullmatch(r"[0-9a-f]{64}", item.expression_sha256):
            raise ValueError(f"{item.key} has an invalid expression digest.")
        if item.source_kind not in _SOURCE_KINDS or not item.source.strip():
            raise ValueError(f"{item.key} has incomplete source provenance.")
        if item.source_kind == "project" and "DS/EN" in item.source:
            raise ValueError(f"{item.key} assigns a citation to a project method.")


def _part_c_source_equations(blocks: Iterable[Sequence[object]]):
    part = section = subsection = ""
    for block in blocks:
        if not block:
            raise ValueError("Manual blocks cannot contain empty records.")
        kind = block[0]
        if kind == "part":
            part = str(block[1])
            section = subsection = ""
        elif kind == "h1":
            section = str(block[1])
            subsection = ""
        elif kind == "h2":
            subsection = str(block[1])
        elif kind == "md" and part == PART_C:
            for expression in _DISPLAY_RE.findall(str(block[1])):
                yield part, section, subsection, _normalise_expression(expression)


def register_manual_equation_identities(
    blocks: Iterable[Sequence[object]],
    identities: Sequence[ManualEquationIdentity] = MANUAL_EQUATION_IDENTITIES,
) -> tuple[RegisteredManualEquationIdentity, ...]:
    """Match the exact Part C source to the canonical identity/source catalogue."""

    identities = tuple(identities)
    if identities != MANUAL_EQUATION_IDENTITIES:
        raise ValueError("The canonical manual equation identity catalogue changed.")
    source = tuple(_part_c_source_equations(blocks))
    if len(source) != len(identities):
        raise ValueError(
            f"Part C equation cardinality changed: expected 32, got {len(source)}."
        )
    registered = []
    for identity, (part, section, subsection, expression) in zip(identities, source):
        if (part, section, subsection) != (
            identity.part, identity.section, identity.subsection,
        ):
            raise ValueError(f"Manual equation {identity.key} moved.")
        if _digest(expression) != identity.expression_sha256:
            raise ValueError(f"Manual equation {identity.key} expression changed.")
        registered.append(RegisteredManualEquationIdentity(identity, expression))
    return tuple(registered)


def catalogue_sha256(field: str) -> str:
    if field == "identity":
        rows = (
            f"{item.ordinal}|{item.key}|{item.number}|{item.part}|{item.section}|"
            f"{item.subsection}|{item.expression_sha256}"
            for item in MANUAL_EQUATION_IDENTITIES
        )
    elif field == "sources":
        rows = (
            f"{item.key}|{item.source_kind}|{item.source}"
            for item in MANUAL_EQUATION_IDENTITIES
        )
    else:
        raise ValueError(f"Unknown manual equation catalogue field: {field!r}.")
    return hashlib.sha256("\n".join(rows).encode("ascii")).hexdigest()


_validate_canonical_catalogue()
