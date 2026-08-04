"""Exact source provenance for the accepted Part C manual equations."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

from manual_equation_location import (
    LocatedManualEquation,
    MANUAL_EQUATION_LOCATIONS,
)


SOURCE_STANDARD = "standard"
SOURCE_MIXED = "mixed"
SOURCE_PROJECT = "project"
SOURCE_KINDS = frozenset((SOURCE_STANDARD, SOURCE_MIXED, SOURCE_PROJECT))

DOC_BASE = "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010"
DOC_DK = "DS/EN 1992-1-1 DK NA:2024"
DOC_CURRENT = "DS/EN 1992-1-1:2023"
DOC_BRIDGE = "DS/EN 1992-2:2005 + AC:2008"
DOCUMENTS = (DOC_BASE, DOC_DK, DOC_CURRENT, DOC_BRIDGE)


@dataclass(frozen=True, slots=True)
class ManualEquationSource:
    """One equation's complete immutable source classification and text."""

    ordinal: int
    key: str
    number: str
    source_kind: str
    source_text: str


@dataclass(frozen=True, slots=True)
class SourcedManualEquation:
    """One canonical located expression bound to its canonical source."""

    equation: LocatedManualEquation
    source: ManualEquationSource


def _source(
    ordinal: int,
    key: str,
    number: str,
    source_kind: str,
    source_text: str,
) -> ManualEquationSource:
    return ManualEquationSource(ordinal, key, number, source_kind, source_text)


MANUAL_EQUATION_SOURCES = (
    _source(
        1, "manual.material.concrete-law", "C3-1", SOURCE_STANDARD,
        f"{DOC_BASE} 3.1.7, Formula (3.17), and Table 3.1; "
        f"{DOC_CURRENT} 8.1.2(1), Formula (8.4).",
    ),
    _source(
        2, "manual.material.steel-law", "C3-2", SOURCE_PROJECT,
        "Project-defined / uncited general Curve 3 mild-steel law; "
        "edition-named presets retain selected material provenance separately.",
    ),
    _source(
        3, "manual.material.prestress-law", "C3-3", SOURCE_MIXED,
        "Project-defined / uncited plane-section total-strain composition with "
        f"selected prestressing-law provenance from {DOC_BASE} 3.3.6 or "
        f"{DOC_CURRENT} 5.3.3 when the corresponding edition preset is selected.",
    ),
    _source(
        4, "manual.plastic.governing-curvature", "C4-1", SOURCE_PROJECT,
        "Project-defined / uncited first-material-limit capacity search; selected "
        "material limits retain their own sources.",
    ),
    _source(
        5, "manual.detailing.minimum-2005", "C5-1", SOURCE_STANDARD,
        f"{DOC_BASE} 9.2.1.1(1), Formula (9.1N), with {DOC_DK} where selected.",
    ),
    _source(
        6, "manual.detailing.minimum-2023-bending", "C5-2", SOURCE_STANDARD,
        f"{DOC_CURRENT} 12.2(2)(a), Formula (12.1).",
    ),
    _source(
        7, "manual.detailing.minimum-2023-axial", "C5-3", SOURCE_STANDARD,
        f"{DOC_CURRENT} 12.2(2)(b), Formula (12.2).",
    ),
    _source(
        8, "manual.detailing.clear-spacing", "C5-4", SOURCE_STANDARD,
        f"{DOC_BASE} 8.2(2); {DOC_CURRENT} 11.2(2).",
    ),
    _source(
        9, "manual.detailing.links.minimum-ratio", "C5-5", SOURCE_STANDARD,
        f"{DOC_BASE} 9.2.2(5), Formulas (9.4) and (9.5N); {DOC_DK} "
        f"9.2.2(5), Formula (9.5N NA), where selected; {DOC_CURRENT} "
        "12.2(4), Formula (12.4).",
    ),
    _source(
        10, "manual.detailing.links.spacing", "C5-6", SOURCE_STANDARD,
        f"{DOC_BASE} 9.2.2(6),(8), Formulas (9.6N) and (9.8N), plus "
        f"9.3.2(2),(4)-(5) for the retained slab branch; {DOC_CURRENT} "
        "Table 12.1 items 5 and 7, plus Table 12.2 items 8 and 10 and "
        "12.4.2 for the retained slab branch.",
    ),
    _source(
        11, "manual.detailing.torsion.minimum-ratio", "C5-7", SOURCE_STANDARD,
        f"{DOC_BASE} 9.2.3(2), referring to 9.2.2(5), Formulas (9.4) and "
        f"(9.5N); {DOC_DK} 9.2.2(5), Formula (9.5N NA), where selected; "
        f"{DOC_CURRENT} 12.2(4), Formula (12.4), and Table 12.1 item 2.",
    ),
    _source(
        12, "manual.crack.2005.width", "C7-1", SOURCE_STANDARD,
        f"{DOC_BASE} 7.3.4, Formulas (7.8) and (7.9).",
    ),
    _source(
        13, "manual.crack.2005.spacing", "C7-2", SOURCE_STANDARD,
        f"{DOC_BASE} 7.3.4, Formulas (7.11) and (7.14).",
    ),
    _source(
        14, "manual.crack.2023.width", "C7-3", SOURCE_STANDARD,
        f"{DOC_CURRENT} 9.2.3, Formulas (9.8) and (9.9).",
    ),
    _source(
        15, "manual.crack.2023.spacing", "C7-4", SOURCE_STANDARD,
        f"{DOC_CURRENT} 9.2.3, Formulas (9.15)-(9.18).",
    ),
    _source(
        16, "manual.fatigue.stress-range", "C8-1", SOURCE_MIXED,
        "Project-defined / uncited retained Elastic stress reconstruction with "
        f"a selected fatigue action factor; {DOC_BASE} 2.4.2.3 and 6.8.4(1), "
        f"or {DOC_CURRENT} 10.2 and Annex E, defines how that factor enters the "
        "retained edition's fatigue action route.",
    ),
    _source(
        17, "manual.fatigue.reinforcement.design-range", "C8-2",
        SOURCE_MIXED,
        "Project-defined / uncited characteristic range for Custom / imported "
        f"fatigue details; {DOC_BASE} 6.8.4 and Tables 6.3N-6.4N, or "
        f"{DOC_CURRENT} Annex E.5 and Tables E.1-E.2, for the corresponding "
        "edition preset.",
    ),
    _source(
        18, "manual.fatigue.reinforcement.life", "C8-3", SOURCE_MIXED,
        "Project-defined / uncited S-N relationship for Custom / imported "
        f"fatigue details; {DOC_BASE} 6.8.4 and Tables 6.3N-6.4N, or "
        f"{DOC_CURRENT} Annex E.5 and Tables E.1-E.2, for the corresponding "
        "edition preset.",
    ),
    _source(
        19, "manual.fatigue.reinforcement.miner", "C8-4", SOURCE_STANDARD,
        f"{DOC_BASE} 6.8.4, Palmgren-Miner summation; {DOC_CURRENT} "
        "Annex E.5, Palmgren-Miner summation.",
    ),
    _source(
        20, "manual.fatigue.concrete.strength-2005", "C8-5", SOURCE_STANDARD,
        f"{DOC_BASE} 3.1.6 and 6.8.7, Formula (6.76).",
    ),
    _source(
        21, "manual.fatigue.concrete.strength-2023", "C8-6", SOURCE_STANDARD,
        f"{DOC_CURRENT} 5.1.6(1), Formula (5.3), and 10.5, Formula (10.5).",
    ),
    _source(
        22, "manual.fatigue.concrete.life", "C8-7", SOURCE_MIXED,
        "Project-defined / uncited concrete Miner S-N relation when the "
        f"user-defined method is selected; {DOC_BRIDGE} corrected 6.106, or "
        f"{DOC_CURRENT} E.5.3, Formulas (E.7)-(E.8), for the corresponding "
        "standard Miner method.",
    ),
    _source(
        23, "manual.fatigue.concrete.equivalent", "C8-8", SOURCE_STANDARD,
        f"{DOC_BASE} 6.8.7, Formula (6.72); {DOC_CURRENT} E.4.3, "
        "Formula (E.2).",
    ),
    _source(
        24, "manual.shear.no-links.variable", "C9-1", SOURCE_STANDARD,
        f"{DOC_BASE} 6.2.2(1), Formula (6.2a), with {DOC_DK} where selected.",
    ),
    _source(
        25, "manual.shear.no-links.minimum", "C9-2", SOURCE_STANDARD,
        f"{DOC_BASE} 6.2.2(1), Formula (6.2b), with {DOC_DK} where selected.",
    ),
    _source(
        26, "manual.shear.action-factor-2023", "C9-3", SOURCE_STANDARD,
        f"{DOC_CURRENT} 8.2.2(3)-(4), Formulas (8.30) and (8.31).",
    ),
    _source(
        27, "manual.shear.links-2005", "C9-4", SOURCE_STANDARD,
        f"{DOC_BASE} 6.2.3(3), Formulas (6.8) and (6.9), with {DOC_DK} "
        "6.2.3(2)-(3) where selected.",
    ),
    _source(
        28, "manual.shear.links-2023", "C9-5", SOURCE_STANDARD,
        f"{DOC_CURRENT} 8.2.3(5), Formulas (8.42) and (8.44).",
    ),
    _source(
        29, "manual.torsion.resistance", "C10-1", SOURCE_STANDARD,
        f"{DOC_BASE} 6.3.2(1), Formula (6.27), 6.2.3(3), Formula (6.8), "
        f"and 6.3.2(4), Formula (6.30), with {DOC_DK} where selected.",
    ),
    _source(
        30, "manual.torsion.strut-interaction", "C10-2", SOURCE_STANDARD,
        f"{DOC_BASE} 6.3.2(4), Formula (6.29).",
    ),
    _source(
        31, "manual.combined.strut-interaction", "C11-1", SOURCE_STANDARD,
        f"{DOC_BASE} 6.3.2(4), Formula (6.29).",
    ),
    _source(
        32, "manual.combined.utilisation", "C11-2", SOURCE_STANDARD,
        f"{DOC_DK} 6.3.2(6).",
    ),
)


def _validate_catalogue() -> None:
    if len(MANUAL_EQUATION_SOURCES) != 32:
        raise RuntimeError("Expected exactly 32 manual equation sources.")
    if tuple(item.ordinal for item in MANUAL_EQUATION_SOURCES) != tuple(
        range(1, 33)
    ):
        raise RuntimeError("Manual equation source ordinals must be contiguous.")
    for source, location in zip(
        MANUAL_EQUATION_SOURCES, MANUAL_EQUATION_LOCATIONS
    ):
        if type(source) is not ManualEquationSource:
            raise RuntimeError("Manual equation sources must retain exact type.")
        values = (
            source.ordinal,
            source.key,
            source.number,
            source.source_kind,
            source.source_text,
        )
        if (
            type(source.ordinal) is not int
            or any(type(value) is not str for value in values[1:])
        ):
            raise RuntimeError(f"Source field type drifted at {location.number}.")
        if values[:3] != (location.ordinal, location.key, location.number):
            raise RuntimeError(f"Source identity drifted at {location.number}.")
        if source.source_kind not in SOURCE_KINDS:
            raise RuntimeError(f"Unknown source kind at {source.number}.")
        if not source.source_text.strip():
            raise RuntimeError(f"Blank source text at {source.number}.")
        if not all(value.isascii() for value in values[1:]):
            raise RuntimeError(f"Non-ASCII source record at {source.number}.")
        has_document = any(
            document in source.source_text for document in DOCUMENTS
        )
        project_prefix = source.source_text.startswith("Project-defined / uncited")
        if source.source_kind == SOURCE_STANDARD and (
            not has_document or project_prefix
        ):
            raise RuntimeError(f"Invalid standard source at {source.number}.")
        if source.source_kind == SOURCE_MIXED and (
            not has_document or not project_prefix
        ):
            raise RuntimeError(f"Invalid mixed source at {source.number}.")
        if source.source_kind == SOURCE_PROJECT and (
            has_document or not project_prefix
        ):
            raise RuntimeError(f"Invalid project source at {source.number}.")
    counts = {
        kind: sum(item.source_kind == kind for item in MANUAL_EQUATION_SOURCES)
        for kind in SOURCE_KINDS
    }
    if counts != {SOURCE_STANDARD: 25, SOURCE_MIXED: 5, SOURCE_PROJECT: 2}:
        raise RuntimeError("Manual equation source classification drifted.")


_validate_catalogue()


def bind_manual_equation_sources(
    equations: tuple[LocatedManualEquation, ...],
    catalogue: tuple[ManualEquationSource, ...] = MANUAL_EQUATION_SOURCES,
) -> tuple[SourcedManualEquation, ...]:
    """Bind canonical live locations to the canonical source catalogue."""

    if type(equations) is not tuple:
        raise ValueError("Located manual equations must retain tuple identity.")
    if type(catalogue) is not tuple or catalogue != MANUAL_EQUATION_SOURCES:
        raise ValueError("Canonical manual equation source catalogue changed.")
    if len(equations) != 32:
        raise ValueError("Located manual equation cardinality changed.")
    sourced = []
    for equation, location, source in zip(
        equations, MANUAL_EQUATION_LOCATIONS, MANUAL_EQUATION_SOURCES
    ):
        if type(equation) is not LocatedManualEquation:
            raise ValueError("Located manual equation type changed.")
        if equation.location != location:
            raise ValueError(f"Located identity changed at {source.number}.")
        expression = equation.expression
        if type(expression) is not str or not expression or not expression.isascii():
            raise ValueError(f"Located expression changed at {source.number}.")
        digest = hashlib.sha256(expression.encode("ascii")).hexdigest()
        if digest != location.expression_sha256:
            raise ValueError(f"Located expression changed at {source.number}.")
        sourced.append(SourcedManualEquation(equation, source))
    return tuple(sourced)


def source_catalogue_sha256() -> str:
    """Return a deterministic seal of every retained source field."""

    rows = (
        "\x1f".join(
            (
                str(item.ordinal),
                item.key,
                item.number,
                item.source_kind,
                item.source_text,
            )
        )
        for item in MANUAL_EQUATION_SOURCES
    )
    return hashlib.sha256("\x1e".join(rows).encode("ascii")).hexdigest()
