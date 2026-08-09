"""Typed, capability-scoped design-basis catalogue for Sector.

Persisted values use :class:`DesignBasisKey`; labels are presentation only.
Every solver dispatch must resolve a concrete ``(basis, capability)`` binding.
Context records are deliberately separate and can never make a basis
selectable or imply an implemented calculation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType


class DesignBasisKey(StrEnum):
    """Stable values persisted by capability-specific selectors."""

    FIRST_GEN_BASE = "ec2_1_1_first_gen_base"
    FIRST_GEN_DK_NA_2024 = "ec2_1_1_first_gen_dk_na_2024"
    PUBLISHED_2023 = "ec2_1_1_2023_published"


class StandardFamily(StrEnum):
    """Generation identity, independent of any national choice."""

    FIRST_GENERATION = "ec2_1_1_first_generation"
    PUBLISHED_2023 = "ec2_1_1_2023"


class NationalChoice(StrEnum):
    """National-choice status explicitly represented by one basis."""

    RECOMMENDED_VALUES = "recommended_values"
    DK_NA_2024 = "dk_na_2024"
    NO_DANISH_NA = "no_danish_na"


class Capability(StrEnum):
    """The capability vocabulary registered by the current programme slice."""

    REINFORCEMENT_FATIGUE = "reinforcement_fatigue"
    CONCRETE_FATIGUE_EQUIVALENT = "concrete_fatigue_equivalent"
    CONCRETE_FATIGUE_DAMAGE_SUM = "concrete_fatigue_damage_sum"


class ContextRole(StrEnum):
    """Why a non-selectable standards reference is retained."""

    SOURCE_ONLY = "source_only"
    CONTEXT_ONLY = "context_only"


@dataclass(frozen=True, slots=True)
class DesignBasis:
    """Presentation metadata for one stable, selectable basis identity."""

    key: DesignBasisKey
    label: str
    family: StandardFamily
    national_choice: NationalChoice
    disclosure: str


@dataclass(frozen=True, slots=True)
class CapabilityBinding:
    """One verified solver route and its bounded engineering provenance."""

    basis_key: DesignBasisKey
    capability: Capability
    solver_edition: str
    source: str
    disclosure: str


@dataclass(frozen=True, slots=True)
class StandardContext:
    """A non-selectable reference that grants no solver capability."""

    key: str
    citation: str
    role: ContextRole
    disclosure: str


_BASE_DISCLOSURE = (
    "First-generation EN reference values; no Danish National Annex is "
    "applied. Confirm the governing project basis."
)
_DK_DISCLOSURE = (
    "Current Danish BR18-listed first-generation family; project "
    "applicability and final effective factors remain the engineer's "
    "responsibility."
)
_PUBLISHED_2023_DISCLOSURE = (
    "Published reference option; project adoption required; no Danish "
    "National Annex is applied."
)

_DESIGN_BASES: dict[DesignBasisKey, DesignBasis] = {
    DesignBasisKey.FIRST_GEN_BASE: DesignBasis(
        key=DesignBasisKey.FIRST_GEN_BASE,
        label=(
            "EN 1992-1-1 first-generation family - recommended values"
        ),
        family=StandardFamily.FIRST_GENERATION,
        national_choice=NationalChoice.RECOMMENDED_VALUES,
        disclosure=_BASE_DISCLOSURE,
    ),
    DesignBasisKey.FIRST_GEN_DK_NA_2024: DesignBasis(
        key=DesignBasisKey.FIRST_GEN_DK_NA_2024,
        label=(
            "DS/EN 1992-1-1 first-generation family + DK NA:2024"
        ),
        family=StandardFamily.FIRST_GENERATION,
        national_choice=NationalChoice.DK_NA_2024,
        disclosure=_DK_DISCLOSURE,
    ),
    DesignBasisKey.PUBLISHED_2023: DesignBasis(
        key=DesignBasisKey.PUBLISHED_2023,
        label=(
            "DS/EN 1992-1-1:2023 - published reference; project adoption "
            "required"
        ),
        family=StandardFamily.PUBLISHED_2023,
        national_choice=NationalChoice.NO_DANISH_NA,
        disclosure=_PUBLISHED_2023_DISCLOSURE,
    ),
}

DESIGN_BASES: Mapping[DesignBasisKey, DesignBasis] = MappingProxyType(
    _DESIGN_BASES
)

_FIRST_GEN_REINFORCEMENT_SOURCE = (
    "DS/EN 1992-1-1:2005+A1:2014, clause 6.8.4 and Tables 6.3N/6.4N"
)
_FIRST_GEN_EQUIVALENT_SOURCE = (
    "DS/EN 1992-1-1:2005+A1:2014, clause 6.8.7, Formula (6.72)"
)
_FIRST_GEN_DAMAGE_SOURCE = (
    "DS/EN 1992-2:2005/AC:2008 Formula 6.106 - user-supplied spectrum"
)
_FIRST_GEN_DAMAGE_DISCLOSURE = (
    "Bridge-source calculation using a user-supplied section-action spectrum; "
    "traffic models, dynamic effects, lane/track concurrence, owner "
    "requirements and complete bridge-fatigue compliance are not assessed."
)
_BASE_BINDING_DISCLOSURE = (
    "Eurocode recommended values are used; no Danish national choice is "
    "applied."
)
_DK_BINDING_DISCLOSURE = (
    "The implemented fatigue equations are unchanged. User-supplied factors "
    "govern; this selection records the stated Danish project basis and "
    "applies no hidden DK-specific fatigue equation or factor."
)
_PUBLISHED_2023_BINDING_DISCLOSURE = (
    "Annex E implementation; no Danish National Annex is applied."
)


def _binding(
    basis_key: DesignBasisKey,
    capability: Capability,
    solver_edition: str,
    source: str,
    disclosure: str,
) -> CapabilityBinding:
    return CapabilityBinding(
        basis_key=basis_key,
        capability=capability,
        solver_edition=solver_edition,
        source=source,
        disclosure=disclosure,
    )


_CAPABILITY_BINDINGS: dict[
    tuple[DesignBasisKey, Capability], CapabilityBinding
] = {}

for _basis_key, _solver_edition, _binding_disclosure in (
    (
        DesignBasisKey.FIRST_GEN_BASE,
        "DS/EN 1992-1-1:2005",
        _BASE_BINDING_DISCLOSURE,
    ),
    (
        DesignBasisKey.FIRST_GEN_DK_NA_2024,
        "DS/EN 1992-1-1:2005 + DK NA:2024",
        _DK_BINDING_DISCLOSURE,
    ),
):
    _CAPABILITY_BINDINGS[(_basis_key, Capability.REINFORCEMENT_FATIGUE)] = (
        _binding(
            _basis_key,
            Capability.REINFORCEMENT_FATIGUE,
            _solver_edition,
            _FIRST_GEN_REINFORCEMENT_SOURCE,
            _binding_disclosure,
        )
    )
    _CAPABILITY_BINDINGS[
        (_basis_key, Capability.CONCRETE_FATIGUE_EQUIVALENT)
    ] = _binding(
        _basis_key,
        Capability.CONCRETE_FATIGUE_EQUIVALENT,
        _solver_edition,
        _FIRST_GEN_EQUIVALENT_SOURCE,
        _binding_disclosure,
    )
    _CAPABILITY_BINDINGS[
        (_basis_key, Capability.CONCRETE_FATIGUE_DAMAGE_SUM)
    ] = _binding(
        _basis_key,
        Capability.CONCRETE_FATIGUE_DAMAGE_SUM,
        _solver_edition,
        _FIRST_GEN_DAMAGE_SOURCE,
        f"{_FIRST_GEN_DAMAGE_DISCLOSURE} {_binding_disclosure}",
    )

_CAPABILITY_BINDINGS[
    (DesignBasisKey.PUBLISHED_2023, Capability.REINFORCEMENT_FATIGUE)
] = _binding(
    DesignBasisKey.PUBLISHED_2023,
    Capability.REINFORCEMENT_FATIGUE,
    "DS/EN 1992-1-1:2023",
    "DS/EN 1992-1-1:2023, Annex E.5 and Tables E.1/E.2",
    _PUBLISHED_2023_BINDING_DISCLOSURE,
)
_CAPABILITY_BINDINGS[
    (DesignBasisKey.PUBLISHED_2023, Capability.CONCRETE_FATIGUE_EQUIVALENT)
] = _binding(
    DesignBasisKey.PUBLISHED_2023,
    Capability.CONCRETE_FATIGUE_EQUIVALENT,
    "DS/EN 1992-1-1:2023",
    "DS/EN 1992-1-1:2023, E.4.3, Formula (E.2)",
    _PUBLISHED_2023_BINDING_DISCLOSURE,
)
_CAPABILITY_BINDINGS[
    (DesignBasisKey.PUBLISHED_2023, Capability.CONCRETE_FATIGUE_DAMAGE_SUM)
] = _binding(
    DesignBasisKey.PUBLISHED_2023,
    Capability.CONCRETE_FATIGUE_DAMAGE_SUM,
    "DS/EN 1992-1-1:2023",
    "DS/EN 1992-1-1:2023, E.5.3, Formulae (E.7)-(E.8)",
    _PUBLISHED_2023_BINDING_DISCLOSURE,
)

CAPABILITY_BINDINGS: Mapping[
    tuple[DesignBasisKey, Capability], CapabilityBinding
] = MappingProxyType(_CAPABILITY_BINDINGS)

STANDARD_CONTEXTS: tuple[StandardContext, ...] = (
    StandardContext(
        key="ec2_2_first_gen_ac_2008_fatigue_source",
        citation="DS/EN 1992-2:2005/AC:2008",
        role=ContextRole.SOURCE_ONLY,
        disclosure=(
            "Formula 6.106 is a source for the registered first-generation "
            "concrete-fatigue damage-sum calculation only; it is not a "
            "selectable bridge basis."
        ),
    ),
    StandardContext(
        key="ec2_2_first_gen_dk_na_2015_context",
        citation="DS/EN 1992-2 DK NA:2015",
        role=ContextRole.CONTEXT_ONLY,
        disclosure=(
            "Project context only; no solver binding or selectable basis is "
            "registered."
        ),
    ),
    StandardContext(
        key="ec2_1_1_2023_annex_k_context",
        citation="DS/EN 1992-1-1:2023, normative Annex K",
        role=ContextRole.CONTEXT_ONLY,
        disclosure=(
            "Bridge scope in the standard only; no solver binding or Sector "
            "implementation claim is registered."
        ),
    ),
)


def _valid_basis_keys() -> str:
    return ", ".join(key.value for key in DesignBasisKey)


def _valid_capabilities() -> str:
    return ", ".join(capability.value for capability in Capability)


def parse_design_basis_key(value: object) -> DesignBasisKey:
    """Parse one exact persisted key without label or substring guessing."""

    if isinstance(value, DesignBasisKey):
        return value
    if isinstance(value, str):
        try:
            return DesignBasisKey(value)
        except ValueError:
            pass
    raise ValueError(
        "fatigue_edition must be one of the registered basis keys: "
        f"{_valid_basis_keys()}"
    )


def parse_capability(value: object) -> Capability:
    """Parse one exact capability key without heuristic dispatch."""

    if isinstance(value, Capability):
        return value
    if isinstance(value, str):
        try:
            return Capability(value)
        except ValueError:
            pass
    raise ValueError(
        "capability must be one of the registered keys: "
        f"{_valid_capabilities()}"
    )


def get_design_basis(value: object) -> DesignBasis:
    """Return the immutable metadata for one exact basis key."""

    return DESIGN_BASES[parse_design_basis_key(value)]


def capability_binding(
    basis: object,
    capability: object,
) -> CapabilityBinding:
    """Resolve one exact implementation binding or fail closed."""

    basis_key = parse_design_basis_key(basis)
    capability_key = parse_capability(capability)
    binding = CAPABILITY_BINDINGS.get((basis_key, capability_key))
    if binding is None:
        raise ValueError(
            f"{basis_key.value} does not implement {capability_key.value}"
        )
    return binding


def fatigue_edition_for(basis: object, capability: object) -> str:
    """Return the internal solver token from an exact fatigue binding."""

    return capability_binding(basis, capability).solver_edition


def basis_options(capability: object) -> tuple[DesignBasis, ...]:
    """Return ordered UI options only for one implemented capability."""

    capability_key = parse_capability(capability)
    return tuple(
        basis
        for basis in DESIGN_BASES.values()
        if (basis.key, capability_key) in CAPABILITY_BINDINGS
    )
