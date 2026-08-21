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
    ORDINARY_CRACK_WIDTH = "ordinary_crack_width"
    HEIGHTENED_CRACK_CONTROL = "heightened_crack_control"


class InputGuidanceKey(StrEnum):
    """Stable semantic keys for basis-dependent input help."""

    FATIGUE_DETAIL_VALUES = "fatigue_detail_values"
    FATIGUE_CONCRETE_METHOD = "fatigue_concrete_method"
    FATIGUE_MIXED_BOND = "fatigue_mixed_bond"
    FATIGUE_ACTION_PARTIAL_FACTOR = "fatigue_action_partial_factor"
    FATIGUE_REINFORCEMENT_MATERIAL_FACTOR = (
        "fatigue_reinforcement_material_factor"
    )
    FATIGUE_CONCRETE_MATERIAL_FACTOR = "fatigue_concrete_material_factor"
    FATIGUE_CONCRETE_STRENGTH_DEVELOPMENT = (
        "fatigue_concrete_strength_development"
    )
    FATIGUE_CONCRETE_STRENGTH_K1 = "fatigue_concrete_strength_k1"
    FATIGUE_CONCRETE_LIFE_C = "fatigue_concrete_life_c"
    ORDINARY_CRACK_DIAMETER = "ordinary_crack_diameter"
    ORDINARY_CRACK_MILD_BOND = "ordinary_crack_mild_bond"
    ORDINARY_CRACK_TENDON_BOND = "ordinary_crack_tendon_bond"
    ORDINARY_CRACK_MEMBER_TYPE = "ordinary_crack_member_type"
    HEIGHTENED_CRACK_OPERANDS = "heightened_crack_operands"
    CREEP_COEFFICIENT = "creep_coefficient"
    DETAILING_MINIMUM_REINFORCEMENT = "detailing_minimum_reinforcement"
    DETAILING_TRANSVERSE_LINKS = "detailing_transverse_links"
    DETAILING_CLEAR_SPACING = "detailing_clear_spacing"


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
class OrdinaryCrackWidthSolverRoute:
    """Typed arguments that select one live ordinary crack-width route."""

    edition: str
    k3_cover_dependent: bool
    include_hx_term_for_ordinary_beams: bool
    include_hx_term_for_slabs_or_prestressed: bool
    report_coarse_system: bool


@dataclass(frozen=True, slots=True)
class CapabilityBinding:
    """One verified solver route and its bounded engineering provenance."""

    basis_key: DesignBasisKey
    capability: Capability
    solver_edition: str
    source: str
    disclosure: str
    ordinary_crack_width_route: OrdinaryCrackWidthSolverRoute | None = None


@dataclass(frozen=True, slots=True)
class InputGuidance:
    """One immutable, basis-scoped source for an input tooltip."""

    basis_key: DesignBasisKey
    key: InputGuidanceKey
    guidance: str
    source: str

    @property
    def tooltip(self) -> str:
        """Return the complete user-facing help without hiding its source."""

        return f"{self.guidance} Source: {self.source.rstrip('.')}."


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
_FIRST_GEN_CRACK_SOURCE = (
    "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010, 7.3.2 and 7.3.4, "
    "Formulas (7.8), (7.9), (7.11) and (7.14)"
)
_DK_ORDINARY_CRACK_SOURCE = (
    f"{_FIRST_GEN_CRACK_SOURCE}, with DS/EN 1992-1-1 DK NA:2024, "
    "7.3.4(1), 7.3.4(3) and Figure 7.100 NA"
)
_PUBLISHED_2023_CRACK_SOURCE = (
    "DS/EN 1992-1-1:2023, 9.2.2 and 9.2.3, Figure 9.3 and Formulas "
    "(9.6), (9.8), (9.9), (9.11), (9.12), (9.15), (9.17), (9.18) "
    "and (9.20)"
)
_DK_HEIGHTENED_CRACK_SOURCE = (
    "DS/EN 1992-1-1 DK NA:2024, supplementary provision to "
    "7.3.2(1)P, Formula 7.100 NA"
)
_DK_ORDINARY_CRACK_DISCLOSURE = (
    "The implemented Danish ordinary crack-width route reports the fine and "
    "coarse crack systems. Selection records the stated Danish project basis."
)
_DK_HEIGHTENED_CRACK_DISCLOSURE = (
    "Separate user-selected first-generation Danish calculation. The user "
    "supplies the permitted crack width and decides applicability; Sector "
    "does not infer that the supplementary provision applies."
)

_FIRST_GEN_MIXED_BOND_SOURCE = "EN 1992-1-1:2005 6.8.2(2)"
_PUBLISHED_2023_MIXED_BOND_SOURCE = "EN 1992-1-1:2023 10.3(2)"
_PUBLISHED_2023_CRACK_TENDON_BOND_SOURCE = (
    "DS/EN 1992-1-1:2023, 9.2.2(3), Formula (9.6)"
)
_FIRST_GEN_CONCRETE_METHOD_SOURCE = (
    f"{_FIRST_GEN_EQUIVALENT_SOURCE}; {_FIRST_GEN_DAMAGE_SOURCE}"
)
_PUBLISHED_2023_CONCRETE_METHOD_SOURCE = (
    "DS/EN 1992-1-1:2023, E.4.3, Formula (E.2), and E.5.3, "
    "Formulae (E.7)-(E.8)"
)
_FIRST_GEN_FATIGUE_ACTION_FACTOR_SOURCE = (
    "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010, 2.4.2.3 and 6.8.4(1)"
)
_PUBLISHED_2023_FATIGUE_ACTION_FACTOR_SOURCE = (
    "DS/EN 1992-1-1:2023, 10.2 and Annex E"
)
_FIRST_GEN_CONCRETE_STRENGTH_SOURCE = (
    "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010, 3.1.6 and 6.8.7, "
    "Formula (6.76)"
)
_PUBLISHED_2023_CONCRETE_STRENGTH_SOURCE = (
    "DS/EN 1992-1-1:2023, 5.1.6(1), Formula (5.3), and 10.5, "
    "Formula (10.5)"
)
_DK_CRACK_MEMBER_SOURCE = "DS/EN 1992-1-1 DK NA:2024, 7.3.4(1)"

_FIRST_GEN_CREEP_SOURCE = (
    "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010, 3.1.4 and Annex B.1"
)
_DK_CREEP_SOURCE = (
    f"{_FIRST_GEN_CREEP_SOURCE}; DS/EN 1992-1-1 DK NA:2024, "
    "3.1.4(1)-(2)"
)
_PUBLISHED_2023_CREEP_SOURCE = (
    "DS/EN 1992-1-1:2023, 5.1.5, Table 5.2 and Annex B.5"
)
_FIRST_GEN_MINIMUM_REINFORCEMENT_SOURCE = (
    "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010, 9.2.1.1(1), "
    "Formula (9.1N), and 9.3.1.1(1)-(2)"
)
_DK_MINIMUM_REINFORCEMENT_SOURCE = (
    f"{_FIRST_GEN_MINIMUM_REINFORCEMENT_SOURCE}; "
    "DS/EN 1992-1-1 DK NA:2024, 9.2.1.1(1)"
)
_PUBLISHED_2023_MINIMUM_REINFORCEMENT_SOURCE = (
    "DS/EN 1992-1-1:2023, 12.2(2), Formulae (12.1)-(12.2), "
    "and Table 12.2"
)
_FIRST_GEN_TRANSVERSE_LINK_SOURCE = (
    "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010, 9.2.2(2), "
    "9.2.2(5)-(8), Formulae (9.4)-(9.8), 9.2.3(3), and "
    "9.3.2(2), (4)-(5)"
)
_DK_TRANSVERSE_LINK_SOURCE = (
    f"{_FIRST_GEN_TRANSVERSE_LINK_SOURCE}; "
    "DS/EN 1992-1-1 DK NA:2024, 9.2.2(5), Formula (9.5N NA)"
)
_PUBLISHED_2023_TRANSVERSE_LINK_SOURCE = (
    "DS/EN 1992-1-1:2023, 8.2.1(2), 12.2(4), Tables 12.1 "
    "and 12.2, 12.3.3 and 12.4.2"
)
_FIRST_GEN_CLEAR_SPACING_SOURCE = (
    "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010, 8.2(2)"
)
_DK_CLEAR_SPACING_SOURCE = (
    f"{_FIRST_GEN_CLEAR_SPACING_SOURCE}; "
    "DS/EN 1992-1-1 DK NA:2024, 8.2(2) unchanged"
)
_PUBLISHED_2023_CLEAR_SPACING_SOURCE = (
    "DS/EN 1992-1-1:2023, 11.2(2)"
)


def _binding(
    basis_key: DesignBasisKey,
    capability: Capability,
    solver_edition: str,
    source: str,
    disclosure: str,
    *,
    ordinary_crack_width_route: OrdinaryCrackWidthSolverRoute | None = None,
) -> CapabilityBinding:
    return CapabilityBinding(
        basis_key=basis_key,
        capability=capability,
        solver_edition=solver_edition,
        source=source,
        disclosure=disclosure,
        ordinary_crack_width_route=ordinary_crack_width_route,
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

_CAPABILITY_BINDINGS[
    (DesignBasisKey.FIRST_GEN_BASE, Capability.ORDINARY_CRACK_WIDTH)
] = _binding(
    DesignBasisKey.FIRST_GEN_BASE,
    Capability.ORDINARY_CRACK_WIDTH,
    "2004",
    _FIRST_GEN_CRACK_SOURCE,
    _BASE_BINDING_DISCLOSURE,
    ordinary_crack_width_route=OrdinaryCrackWidthSolverRoute(
        edition="2004",
        k3_cover_dependent=False,
        include_hx_term_for_ordinary_beams=True,
        include_hx_term_for_slabs_or_prestressed=True,
        report_coarse_system=False,
    ),
)
_CAPABILITY_BINDINGS[
    (DesignBasisKey.FIRST_GEN_DK_NA_2024, Capability.ORDINARY_CRACK_WIDTH)
] = _binding(
    DesignBasisKey.FIRST_GEN_DK_NA_2024,
    Capability.ORDINARY_CRACK_WIDTH,
    "2004",
    _DK_ORDINARY_CRACK_SOURCE,
    _DK_ORDINARY_CRACK_DISCLOSURE,
    ordinary_crack_width_route=OrdinaryCrackWidthSolverRoute(
        edition="2004",
        k3_cover_dependent=True,
        include_hx_term_for_ordinary_beams=False,
        include_hx_term_for_slabs_or_prestressed=True,
        report_coarse_system=True,
    ),
)
_CAPABILITY_BINDINGS[
    (DesignBasisKey.PUBLISHED_2023, Capability.ORDINARY_CRACK_WIDTH)
] = _binding(
    DesignBasisKey.PUBLISHED_2023,
    Capability.ORDINARY_CRACK_WIDTH,
    "2023",
    _PUBLISHED_2023_CRACK_SOURCE,
    _PUBLISHED_2023_DISCLOSURE,
    ordinary_crack_width_route=OrdinaryCrackWidthSolverRoute(
        edition="2023",
        k3_cover_dependent=False,
        include_hx_term_for_ordinary_beams=False,
        include_hx_term_for_slabs_or_prestressed=False,
        report_coarse_system=False,
    ),
)
_CAPABILITY_BINDINGS[
    (DesignBasisKey.FIRST_GEN_DK_NA_2024, Capability.HEIGHTENED_CRACK_CONTROL)
] = _binding(
    DesignBasisKey.FIRST_GEN_DK_NA_2024,
    Capability.HEIGHTENED_CRACK_CONTROL,
    "dk_na_2024_formula_7_100_na",
    _DK_HEIGHTENED_CRACK_SOURCE,
    _DK_HEIGHTENED_CRACK_DISCLOSURE,
)

CAPABILITY_BINDINGS: Mapping[
    tuple[DesignBasisKey, Capability], CapabilityBinding
] = MappingProxyType(_CAPABILITY_BINDINGS)


def _guidance(
    basis_key: DesignBasisKey,
    key: InputGuidanceKey,
    guidance: str,
    source: str,
) -> InputGuidance:
    return InputGuidance(
        basis_key=basis_key,
        key=key,
        guidance=guidance,
        source=source,
    )


_INPUT_GUIDANCE: dict[
    tuple[DesignBasisKey, InputGuidanceKey], InputGuidance
] = {}

for _basis_key in (
    DesignBasisKey.FIRST_GEN_BASE,
    DesignBasisKey.FIRST_GEN_DK_NA_2024,
):
    _first_gen_crack_source = (
        _DK_ORDINARY_CRACK_SOURCE
        if _basis_key is DesignBasisKey.FIRST_GEN_DK_NA_2024
        else _FIRST_GEN_CRACK_SOURCE
    )
    _INPUT_GUIDANCE[
        (_basis_key, InputGuidanceKey.FATIGUE_DETAIL_VALUES)
    ] = _guidance(
        _basis_key,
        InputGuidanceKey.FATIGUE_DETAIL_VALUES,
        "Named fatigue-detail values come from the registered reinforcement "
        "S-N resistance tables. The selected preset identifies the specific "
        "table row or note.",
        _FIRST_GEN_REINFORCEMENT_SOURCE,
    )
    _INPUT_GUIDANCE[
        (_basis_key, InputGuidanceKey.FATIGUE_CONCRETE_METHOD)
    ] = _guidance(
        _basis_key,
        InputGuidanceKey.FATIGUE_CONCRETE_METHOD,
        "Select either the damage-equivalent expression or the explicit "
        "user-supplied-spectrum damage sum implemented for this basis.",
        _FIRST_GEN_CONCRETE_METHOD_SOURCE,
    )
    _INPUT_GUIDANCE[
        (_basis_key, InputGuidanceKey.FATIGUE_MIXED_BOND)
    ] = _guidance(
        _basis_key,
        InputGuidanceKey.FATIGUE_MIXED_BOND,
        "For a section combining mild reinforcement and bonded tendons, these "
        "inputs define the mixed-bond adjustment used by the selected fatigue "
        "route.",
        _FIRST_GEN_MIXED_BOND_SOURCE,
    )
    for _key, _text, _source in (
        (
            InputGuidanceKey.FATIGUE_ACTION_PARTIAL_FACTOR,
            "Partial factor applied to each cyclic action increment before the "
            "Elastic fatigue solve.",
            _FIRST_GEN_FATIGUE_ACTION_FACTOR_SOURCE,
        ),
        (
            InputGuidanceKey.FATIGUE_REINFORCEMENT_MATERIAL_FACTOR,
            "Material factor reducing the reinforcement S-N resistance and "
            "yield or proof-stress limit.",
            _FIRST_GEN_REINFORCEMENT_SOURCE,
        ),
        (
            InputGuidanceKey.FATIGUE_CONCRETE_MATERIAL_FACTOR,
            "Material factor used in the concrete fatigue design strength.",
            _FIRST_GEN_CONCRETE_STRENGTH_SOURCE,
        ),
        (
            InputGuidanceKey.FATIGUE_CONCRETE_STRENGTH_DEVELOPMENT,
            "Strength-development factor at the age of first cyclic loading "
            "used in the concrete fatigue design strength.",
            _FIRST_GEN_CONCRETE_STRENGTH_SOURCE,
        ),
        (
            InputGuidanceKey.FATIGUE_CONCRETE_STRENGTH_K1,
            "Coefficient k1 used in the first-generation concrete fatigue "
            "design strength.",
            _FIRST_GEN_CONCRETE_STRENGTH_SOURCE,
        ),
        (
            InputGuidanceKey.FATIGUE_CONCRETE_LIFE_C,
            "Coefficient C used in the implemented concrete fatigue-life "
            "relation for a user-supplied spectrum.",
            _FIRST_GEN_DAMAGE_SOURCE,
        ),
    ):
        _INPUT_GUIDANCE[(_basis_key, _key)] = _guidance(
            _basis_key,
            _key,
            _text,
            _source,
        )
    for _key, _text in (
        (
            InputGuidanceKey.ORDINARY_CRACK_DIAMETER,
            (
                "Diameter used by the ordinary crack-spacing calculation; zero "
                "retains each reinforcement element's diameter."
            ),
        ),
        (
            InputGuidanceKey.ORDINARY_CRACK_MILD_BOND,
            (
                "Select the mild-reinforcement bond coefficient used by the "
                "ordinary crack-spacing calculation."
            ),
        ),
    ):
        _INPUT_GUIDANCE[(_basis_key, _key)] = _guidance(
            _basis_key,
            _key,
            _text,
            _first_gen_crack_source,
        )

_INPUT_GUIDANCE[
    (
        DesignBasisKey.PUBLISHED_2023,
        InputGuidanceKey.FATIGUE_DETAIL_VALUES,
    )
] = _guidance(
    DesignBasisKey.PUBLISHED_2023,
    InputGuidanceKey.FATIGUE_DETAIL_VALUES,
    "Named fatigue-detail values come from the registered reinforcement S-N "
    "resistance tables. The selected preset identifies the specific table row "
    "or note.",
    "DS/EN 1992-1-1:2023, Annex E.5 and Tables E.1/E.2",
)
_INPUT_GUIDANCE[
    (
        DesignBasisKey.PUBLISHED_2023,
        InputGuidanceKey.FATIGUE_CONCRETE_METHOD,
    )
] = _guidance(
    DesignBasisKey.PUBLISHED_2023,
    InputGuidanceKey.FATIGUE_CONCRETE_METHOD,
    "Select either the damage-equivalent expression or the explicit "
    "user-supplied-spectrum damage sum implemented for this basis.",
    _PUBLISHED_2023_CONCRETE_METHOD_SOURCE,
)
_INPUT_GUIDANCE[
    (DesignBasisKey.PUBLISHED_2023, InputGuidanceKey.FATIGUE_MIXED_BOND)
] = _guidance(
    DesignBasisKey.PUBLISHED_2023,
    InputGuidanceKey.FATIGUE_MIXED_BOND,
    "For a section combining mild reinforcement and bonded tendons, these "
    "inputs define the equivalent-tendon-area adjustment used by the selected "
    "fatigue route.",
    _PUBLISHED_2023_MIXED_BOND_SOURCE,
)
for _key, _text, _source in (
    (
        InputGuidanceKey.FATIGUE_ACTION_PARTIAL_FACTOR,
        "Partial factor applied to each cyclic action increment before the "
        "Elastic fatigue solve.",
        _PUBLISHED_2023_FATIGUE_ACTION_FACTOR_SOURCE,
    ),
    (
        InputGuidanceKey.FATIGUE_REINFORCEMENT_MATERIAL_FACTOR,
        "Material factor reducing the reinforcement S-N resistance and yield "
        "or proof-stress limit.",
        "DS/EN 1992-1-1:2023, Annex E.5 and Tables E.1/E.2",
    ),
    (
        InputGuidanceKey.FATIGUE_CONCRETE_MATERIAL_FACTOR,
        "Material factor used in the concrete fatigue design strength.",
        _PUBLISHED_2023_CONCRETE_STRENGTH_SOURCE,
    ),
    (
        InputGuidanceKey.FATIGUE_CONCRETE_STRENGTH_DEVELOPMENT,
        "Strength-development factor at the age of first cyclic loading used "
        "in the concrete fatigue design strength.",
        _PUBLISHED_2023_CONCRETE_STRENGTH_SOURCE,
    ),
    (
        InputGuidanceKey.FATIGUE_CONCRETE_STRENGTH_K1,
        "This field is not used by the 2023 concrete fatigue strength "
        "expression.",
        _PUBLISHED_2023_CONCRETE_STRENGTH_SOURCE,
    ),
    (
        InputGuidanceKey.FATIGUE_CONCRETE_LIFE_C,
        "Coefficient C used in the implemented concrete fatigue-life relation "
        "for a user-supplied spectrum.",
        "DS/EN 1992-1-1:2023, E.5.3, Formulae (E.7)-(E.8)",
    ),
):
    _INPUT_GUIDANCE[(DesignBasisKey.PUBLISHED_2023, _key)] = _guidance(
        DesignBasisKey.PUBLISHED_2023,
        _key,
        _text,
        _source,
    )
for _key, _text, _source in (
    (
        InputGuidanceKey.ORDINARY_CRACK_DIAMETER,
        (
            "Diameter used by the ordinary crack-width calculation; zero "
            "retains each reinforcement element's diameter."
        ),
        _PUBLISHED_2023_CRACK_SOURCE,
    ),
    (
        InputGuidanceKey.ORDINARY_CRACK_MILD_BOND,
        (
            "Select the mild-reinforcement bond input used by the ordinary "
            "crack-width calculation."
        ),
        _PUBLISHED_2023_CRACK_SOURCE,
    ),
    (
        InputGuidanceKey.ORDINARY_CRACK_TENDON_BOND,
        (
            "Tendon-to-ribbed-reinforcement bond-strength ratio used to derive "
            "the effective prestressing contribution."
        ),
        _PUBLISHED_2023_CRACK_TENDON_BOND_SOURCE,
    ),
):
    _INPUT_GUIDANCE[(DesignBasisKey.PUBLISHED_2023, _key)] = _guidance(
        DesignBasisKey.PUBLISHED_2023,
        _key,
        _text,
        _source,
    )

_INPUT_GUIDANCE[
    (
        DesignBasisKey.FIRST_GEN_DK_NA_2024,
        InputGuidanceKey.ORDINARY_CRACK_MEMBER_TYPE,
    )
] = _guidance(
    DesignBasisKey.FIRST_GEN_DK_NA_2024,
    InputGuidanceKey.ORDINARY_CRACK_MEMBER_TYPE,
    "Select Beam or Slab for the Danish fine-system effective-height branch; "
    "prestressed sections use the slabs-or-prestressed branch regardless of "
    "this selection.",
    _DK_CRACK_MEMBER_SOURCE,
)

_INPUT_GUIDANCE[
    (
        DesignBasisKey.FIRST_GEN_DK_NA_2024,
        InputGuidanceKey.HEIGHTENED_CRACK_OPERANDS,
    )
] = _guidance(
    DesignBasisKey.FIRST_GEN_DK_NA_2024,
    InputGuidanceKey.HEIGHTENED_CRACK_OPERANDS,
    "This value is an operand or selection for the optional, separately "
    "enabled heightened crack-control calculation.",
    _DK_HEIGHTENED_CRACK_SOURCE,
)

for (
    _basis_key,
    _creep_guidance,
    _creep_source,
    _minimum_guidance,
    _minimum_source,
    _links_source,
    _spacing_source,
) in (
    (
        DesignBasisKey.FIRST_GEN_BASE,
        (
            "Enter the final creep coefficient used in the effective concrete "
            "modulus. Sector does not derive humidity, notional size, age at "
            "loading or duration."
        ),
        _FIRST_GEN_CREEP_SOURCE,
        (
            "Run Sector's modelled-direction minimum-reinforcement check for "
            "the selected member type and selected Plastic/capacity rows."
        ),
        _FIRST_GEN_MINIMUM_REINFORCEMENT_SOURCE,
        _FIRST_GEN_TRANSVERSE_LINK_SOURCE,
        _FIRST_GEN_CLEAR_SPACING_SOURCE,
    ),
    (
        DesignBasisKey.FIRST_GEN_DK_NA_2024,
        (
            "Enter the final creep coefficient used in the effective concrete "
            "modulus. The Danish value phi = 3 is conditional; Sector does not "
            "infer whether creep is decisive or whether recycled-aggregate "
            "documentation is required."
        ),
        _DK_CREEP_SOURCE,
        (
            "Run Sector's modelled-direction minimum-reinforcement check for "
            "the selected member type and selected Plastic/capacity rows. The "
            "separate Danish high-beam-web provision is not included."
        ),
        _DK_MINIMUM_REINFORCEMENT_SOURCE,
        _DK_TRANSVERSE_LINK_SOURCE,
        _DK_CLEAR_SPACING_SOURCE,
    ),
    (
        DesignBasisKey.PUBLISHED_2023,
        (
            "Enter the final creep coefficient used in the effective concrete "
            "modulus. Sector does not derive the Table 5.2 or Annex B.5 "
            "operands or decide project adoption."
        ),
        _PUBLISHED_2023_CREEP_SOURCE,
        (
            "Run Sector's modelled-direction minimum-reinforcement check for "
            "the selected member type and selected Plastic/capacity rows."
        ),
        _PUBLISHED_2023_MINIMUM_REINFORCEMENT_SOURCE,
        _PUBLISHED_2023_TRANSVERSE_LINK_SOURCE,
        _PUBLISHED_2023_CLEAR_SPACING_SOURCE,
    ),
):
    for _key, _text, _source in (
        (
            InputGuidanceKey.CREEP_COEFFICIENT,
            _creep_guidance,
            _creep_source,
        ),
        (
            InputGuidanceKey.DETAILING_MINIMUM_REINFORCEMENT,
            _minimum_guidance,
            _minimum_source,
        ),
        (
            InputGuidanceKey.DETAILING_TRANSVERSE_LINKS,
            (
                "Check the implemented minimum shear/torsion link ratio and "
                "maximum link spacing for active actions. The selected member "
                "type and retained link geometry govern the applied branches."
            ),
            _links_source,
        ),
        (
            InputGuidanceKey.DETAILING_CLEAR_SPACING,
            (
                "Check pairwise edge-to-edge clear distance from the entered "
                "bar geometry and aggregate size. Anchorage, laps, bundles, "
                "cover and construction access remain outside this check."
            ),
            _spacing_source,
        ),
    ):
        _INPUT_GUIDANCE[(_basis_key, _key)] = _guidance(
            _basis_key,
            _key,
            _text,
            _source,
        )

INPUT_GUIDANCE: Mapping[
    tuple[DesignBasisKey, InputGuidanceKey], InputGuidance
] = MappingProxyType(_INPUT_GUIDANCE)

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


def _valid_input_guidance_keys() -> str:
    return ", ".join(key.value for key in InputGuidanceKey)


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


def parse_input_guidance_key(value: object) -> InputGuidanceKey:
    """Parse one exact input-guidance key without substring guessing."""

    if isinstance(value, InputGuidanceKey):
        return value
    if isinstance(value, str):
        try:
            return InputGuidanceKey(value)
        except ValueError:
            pass
    raise ValueError(
        "input guidance must be one of the registered keys: "
        f"{_valid_input_guidance_keys()}"
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


def input_guidance(
    basis: object,
    key: object,
) -> InputGuidance:
    """Resolve exact basis-dependent input help or fail closed."""

    basis_key = parse_design_basis_key(basis)
    guidance_key = parse_input_guidance_key(key)
    guidance = INPUT_GUIDANCE.get((basis_key, guidance_key))
    if guidance is None:
        raise ValueError(
            f"{basis_key.value} has no input guidance for "
            f"{guidance_key.value}"
        )
    return guidance


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
