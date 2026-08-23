"""Contract tests for the capability-scoped v0.93 standards catalogue."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from operator import setitem

import pytest

from sector import design_standards as standards


EXPECTED_KEYS = (
    "ec2_1_1_first_gen_base",
    "ec2_1_1_first_gen_dk_na_2024",
    "ec2_1_1_2023_published",
)
EXPECTED_CAPABILITIES = {
    "reinforcement_fatigue",
    "concrete_fatigue_equivalent",
    "concrete_fatigue_damage_sum",
    "ordinary_crack_width",
    "heightened_crack_control",
}
FATIGUE_CAPABILITIES = (
    standards.Capability.REINFORCEMENT_FATIGUE,
    standards.Capability.CONCRETE_FATIGUE_EQUIVALENT,
    standards.Capability.CONCRETE_FATIGUE_DAMAGE_SUM,
)
COMMON_INPUT_GUIDANCE = (
    standards.InputGuidanceKey.FATIGUE_DETAIL_VALUES,
    standards.InputGuidanceKey.FATIGUE_CONCRETE_METHOD,
    standards.InputGuidanceKey.FATIGUE_MIXED_BOND,
    standards.InputGuidanceKey.FATIGUE_ACTION_PARTIAL_FACTOR,
    standards.InputGuidanceKey.FATIGUE_REINFORCEMENT_MATERIAL_FACTOR,
    standards.InputGuidanceKey.FATIGUE_CONCRETE_MATERIAL_FACTOR,
    standards.InputGuidanceKey.FATIGUE_CONCRETE_STRENGTH_DEVELOPMENT,
    standards.InputGuidanceKey.FATIGUE_CONCRETE_STRENGTH_K1,
    standards.InputGuidanceKey.FATIGUE_CONCRETE_LIFE_C,
    standards.InputGuidanceKey.ORDINARY_CRACK_DIAMETER,
    standards.InputGuidanceKey.ORDINARY_CRACK_MILD_BOND,
    standards.InputGuidanceKey.CREEP_COEFFICIENT,
    standards.InputGuidanceKey.DETAILING_MINIMUM_REINFORCEMENT,
    standards.InputGuidanceKey.DETAILING_TRANSVERSE_LINKS,
    standards.InputGuidanceKey.DETAILING_CLEAR_SPACING,
)


def test_catalogue_has_exactly_three_stable_basis_keys_and_labels():
    assert tuple(key.value for key in standards.DesignBasisKey) == EXPECTED_KEYS
    assert tuple(standards.DESIGN_BASES) == tuple(standards.DesignBasisKey)
    assert {
        basis.key.value: basis.label
        for basis in standards.DESIGN_BASES.values()
    } == {
        EXPECTED_KEYS[0]: (
            "EN 1992-1-1 first-generation family - recommended values"
        ),
        EXPECTED_KEYS[1]: (
            "DS/EN 1992-1-1 first-generation family + DK NA:2024"
        ),
        EXPECTED_KEYS[2]: (
            "DS/EN 1992-1-1:2023 - published reference; project adoption "
            "required"
        ),
    }


def test_family_national_choice_and_disclosures_are_independent_facts():
    base = standards.get_design_basis(EXPECTED_KEYS[0])
    dk = standards.get_design_basis(EXPECTED_KEYS[1])
    published = standards.get_design_basis(EXPECTED_KEYS[2])

    assert base.family is standards.StandardFamily.FIRST_GENERATION
    assert dk.family is standards.StandardFamily.FIRST_GENERATION
    assert published.family is standards.StandardFamily.PUBLISHED_2023
    assert base.national_choice is standards.NationalChoice.RECOMMENDED_VALUES
    assert dk.national_choice is standards.NationalChoice.DK_NA_2024
    assert published.national_choice is standards.NationalChoice.NO_DANISH_NA
    assert base.disclosure == (
        "First-generation EN reference values; no Danish National Annex is "
        "applied. Confirm the governing project basis."
    )
    assert dk.disclosure == (
        "Current Danish BR18-listed first-generation family; project "
        "applicability and final effective factors remain the engineer's "
        "responsibility."
    )
    assert published.disclosure == (
        "Published reference option; project adoption required; no Danish "
        "National Annex is applied."
    )


def test_only_verified_fatigue_and_crack_capabilities_are_registered():
    assert {item.value for item in standards.Capability} == EXPECTED_CAPABILITIES
    assert set(standards.CAPABILITY_BINDINGS) == {
        (basis, capability)
        for basis in standards.DesignBasisKey
        for capability in (
            *FATIGUE_CAPABILITIES,
            standards.Capability.ORDINARY_CRACK_WIDTH,
        )
    } | {
        (
            standards.DesignBasisKey.FIRST_GEN_DK_NA_2024,
            standards.Capability.HEIGHTENED_CRACK_CONTROL,
        )
    }
    for capability in (
        *FATIGUE_CAPABILITIES,
        standards.Capability.ORDINARY_CRACK_WIDTH,
    ):
        assert tuple(
            basis.key for basis in standards.basis_options(capability)
        ) == tuple(standards.DesignBasisKey)
    assert tuple(
        basis.key
        for basis in standards.basis_options(
            standards.Capability.HEIGHTENED_CRACK_CONTROL
        )
    ) == (standards.DesignBasisKey.FIRST_GEN_DK_NA_2024,)


def test_solver_dispatch_is_exact_capability_scoped_and_fail_closed():
    assert standards.fatigue_edition_for(
        standards.DesignBasisKey.FIRST_GEN_BASE,
        standards.Capability.REINFORCEMENT_FATIGUE,
    ) == "DS/EN 1992-1-1:2005"
    assert standards.fatigue_edition_for(
        standards.DesignBasisKey.FIRST_GEN_DK_NA_2024,
        standards.Capability.CONCRETE_FATIGUE_EQUIVALENT,
    ) == "DS/EN 1992-1-1:2005 + DK NA:2024"
    assert standards.fatigue_edition_for(
        standards.DesignBasisKey.PUBLISHED_2023,
        standards.Capability.CONCRETE_FATIGUE_DAMAGE_SUM,
    ) == "DS/EN 1992-1-1:2023"

    for invalid in (
        None,
        "",
        EXPECTED_KEYS[0] + " ",
        "DS/EN 1992-1-1:2023",
        "EN 1992-2:2023",
        "ec2_1_1_2023",
    ):
        with pytest.raises(ValueError, match="registered basis keys"):
            standards.parse_design_basis_key(invalid)
    with pytest.raises(ValueError, match="registered keys"):
        standards.capability_binding(EXPECTED_KEYS[0], "confinement")


def test_first_generation_damage_sum_keeps_its_source_only_scope():
    for basis in (
        standards.DesignBasisKey.FIRST_GEN_BASE,
        standards.DesignBasisKey.FIRST_GEN_DK_NA_2024,
    ):
        binding = standards.capability_binding(
            basis,
            standards.Capability.CONCRETE_FATIGUE_DAMAGE_SUM,
        )
        assert binding.source == (
            "DS/EN 1992-2:2005/AC:2008 Formula 6.106 - user-supplied "
            "spectrum"
        )
        assert "user-supplied section-action spectrum" in binding.disclosure
        assert (
            "Traffic models, dynamic effects, lane/track concurrence and "
            "owner-specific checks are outside this section calculation"
        ) in binding.disclosure
        assert "DK NA:2015" not in binding.source
        assert "DK NA:2015" not in binding.disclosure


def test_ordinary_crack_bindings_use_live_solver_editions_and_exact_sources():
    base = standards.capability_binding(
        standards.DesignBasisKey.FIRST_GEN_BASE,
        standards.Capability.ORDINARY_CRACK_WIDTH,
    )
    dk = standards.capability_binding(
        standards.DesignBasisKey.FIRST_GEN_DK_NA_2024,
        standards.Capability.ORDINARY_CRACK_WIDTH,
    )
    published = standards.capability_binding(
        standards.DesignBasisKey.PUBLISHED_2023,
        standards.Capability.ORDINARY_CRACK_WIDTH,
    )

    assert (base.solver_edition, dk.solver_edition) == ("2004", "2004")
    assert published.solver_edition == "2023"
    assert "7.3.2 and 7.3.4" in base.source
    assert "Formulas (7.8), (7.9), (7.11) and (7.14)" in base.source
    assert "DK NA:2024" in dk.source
    assert "Figure 7.100 NA" in dk.source
    assert published.source == (
        "DS/EN 1992-1-1:2023, 9.2.2 and 9.2.3, Figure 9.3 and "
        "Formulas (9.6), (9.8), (9.9), (9.11), (9.12), (9.15), "
        "(9.17), (9.18) and (9.20)"
    )
    assert base.ordinary_crack_width_route == (
        standards.OrdinaryCrackWidthSolverRoute(
            edition="2004",
            k3_cover_dependent=False,
            include_hx_term_for_ordinary_beams=True,
            include_hx_term_for_slabs_or_prestressed=True,
            report_coarse_system=False,
        )
    )
    assert dk.ordinary_crack_width_route == (
        standards.OrdinaryCrackWidthSolverRoute(
            edition="2004",
            k3_cover_dependent=True,
            include_hx_term_for_ordinary_beams=False,
            include_hx_term_for_slabs_or_prestressed=True,
            report_coarse_system=True,
        )
    )
    assert published.ordinary_crack_width_route == (
        standards.OrdinaryCrackWidthSolverRoute(
            edition="2023",
            k3_cover_dependent=False,
            include_hx_term_for_ordinary_beams=False,
            include_hx_term_for_slabs_or_prestressed=False,
            report_coarse_system=False,
        )
    )

    for binding in standards.CAPABILITY_BINDINGS.values():
        if binding.capability is not standards.Capability.ORDINARY_CRACK_WIDTH:
            assert binding.ordinary_crack_width_route is None


def test_heightened_crack_binding_is_first_generation_dk_only_and_bounded():
    binding = standards.capability_binding(
        standards.DesignBasisKey.FIRST_GEN_DK_NA_2024,
        standards.Capability.HEIGHTENED_CRACK_CONTROL,
    )

    assert binding.solver_edition == "dk_na_2024_formula_7_100_na"
    assert binding.source == (
        "DS/EN 1992-1-1 DK NA:2024, supplementary provision to "
        "7.3.2(1)P, Formula 7.100 NA"
    )
    assert "user-selected" in binding.disclosure
    assert "applicability follows the project basis" in binding.disclosure

    for unsupported in (
        standards.DesignBasisKey.FIRST_GEN_BASE,
        standards.DesignBasisKey.PUBLISHED_2023,
    ):
        with pytest.raises(ValueError, match="does not implement"):
            standards.capability_binding(
                unsupported,
                standards.Capability.HEIGHTENED_CRACK_CONTROL,
            )

    crack_bindings = (
        binding,
        *(
            standards.capability_binding(
                basis,
                standards.Capability.ORDINARY_CRACK_WIDTH,
            )
            for basis in standards.DesignBasisKey
        ),
    )
    new_claims = "\n".join(
        f"{item.source}\n{item.disclosure}" for item in crack_bindings
    ).casefold()
    for excluded in (
        "1992-2",
        "bridge",
        "confinement",
        "global compliance",
    ):
        assert excluded not in new_claims


def test_input_guidance_registry_is_complete_basis_bound_and_exact():
    assert set(standards.INPUT_GUIDANCE) == {
        (basis, key)
        for basis in standards.DesignBasisKey
        for key in COMMON_INPUT_GUIDANCE
    } | {
        (
            standards.DesignBasisKey.PUBLISHED_2023,
            standards.InputGuidanceKey.ORDINARY_CRACK_TENDON_BOND,
        ),
        (
            standards.DesignBasisKey.FIRST_GEN_DK_NA_2024,
            standards.InputGuidanceKey.ORDINARY_CRACK_MEMBER_TYPE,
        ),
        (
            standards.DesignBasisKey.FIRST_GEN_DK_NA_2024,
            standards.InputGuidanceKey.HEIGHTENED_CRACK_OPERANDS,
        ),
    }

    assert standards.input_guidance(
        standards.DesignBasisKey.FIRST_GEN_BASE,
        standards.InputGuidanceKey.FATIGUE_MIXED_BOND,
    ).source == "EN 1992-1-1:2005 6.8.2(2)"
    assert standards.input_guidance(
        standards.DesignBasisKey.PUBLISHED_2023,
        standards.InputGuidanceKey.FATIGUE_MIXED_BOND,
    ).source == "DS/EN 1992-1-1:2023 10.3(2)"
    assert standards.input_guidance(
        standards.DesignBasisKey.PUBLISHED_2023,
        standards.InputGuidanceKey.ORDINARY_CRACK_TENDON_BOND,
    ).source == (
        "DS/EN 1992-1-1:2023, 9.2.2(3), Formula (9.6)"
    )
    expected_fatigue_sources = {
        standards.InputGuidanceKey.FATIGUE_ACTION_PARTIAL_FACTOR: (
            "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010, 2.4.2.3 and "
            "6.8.4(1)",
            "DS/EN 1992-1-1:2023, 10.2 and Annex E",
        ),
        standards.InputGuidanceKey.FATIGUE_REINFORCEMENT_MATERIAL_FACTOR: (
            "DS/EN 1992-1-1:2005+A1:2014, clause 6.8.4 and Tables "
            "6.3N/6.4N",
            "DS/EN 1992-1-1:2023, Annex E.5 and Tables E.1/E.2",
        ),
        standards.InputGuidanceKey.FATIGUE_CONCRETE_MATERIAL_FACTOR: (
            "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010, 3.1.6 and 6.8.7, "
            "Formula (6.76)",
            "DS/EN 1992-1-1:2023, 5.1.6(1), Formula (5.3), and 10.5, "
            "Formula (10.5)",
        ),
        standards.InputGuidanceKey.FATIGUE_CONCRETE_STRENGTH_DEVELOPMENT: (
            "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010, 3.1.6 and 6.8.7, "
            "Formula (6.76)",
            "DS/EN 1992-1-1:2023, 5.1.6(1), Formula (5.3), and 10.5, "
            "Formula (10.5)",
        ),
        standards.InputGuidanceKey.FATIGUE_CONCRETE_STRENGTH_K1: (
            "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010, 3.1.6 and 6.8.7, "
            "Formula (6.76)",
            "DS/EN 1992-1-1:2023, 5.1.6(1), Formula (5.3), and 10.5, "
            "Formula (10.5)",
        ),
        standards.InputGuidanceKey.FATIGUE_CONCRETE_LIFE_C: (
            "DS/EN 1992-2:2005/AC:2008 Formula 6.106 - user-supplied spectrum",
            "DS/EN 1992-1-1:2023, E.5.3, Formulae (E.7)-(E.8)",
        ),
    }
    for key, (first_generation, published_2023) in expected_fatigue_sources.items():
        assert standards.input_guidance(
            standards.DesignBasisKey.FIRST_GEN_BASE, key
        ).source == first_generation
        assert standards.input_guidance(
            standards.DesignBasisKey.FIRST_GEN_DK_NA_2024, key
        ).source == first_generation
        assert standards.input_guidance(
            standards.DesignBasisKey.PUBLISHED_2023, key
        ).source == published_2023
    member_type = standards.input_guidance(
        standards.DesignBasisKey.FIRST_GEN_DK_NA_2024,
        standards.InputGuidanceKey.ORDINARY_CRACK_MEMBER_TYPE,
    )
    assert member_type.source == "DS/EN 1992-1-1 DK NA:2024, 7.3.4(1)"
    base_crack = standards.input_guidance(
        standards.DesignBasisKey.FIRST_GEN_BASE,
        standards.InputGuidanceKey.ORDINARY_CRACK_DIAMETER,
    )
    assert base_crack.source == (
        "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010, 7.3.2 and 7.3.4, "
        "Formulas (7.8), (7.9), (7.11) and (7.14)"
    )
    heightened = standards.input_guidance(
        standards.DesignBasisKey.FIRST_GEN_DK_NA_2024,
        standards.InputGuidanceKey.HEIGHTENED_CRACK_OPERANDS,
    )
    assert heightened.source == (
        "DS/EN 1992-1-1 DK NA:2024, supplementary provision to "
        "7.3.2(1)P, Formula 7.100 NA"
    )
    assert heightened.tooltip.endswith(f"Source: {heightened.source}.")


def test_creep_and_detailing_guidance_has_exact_selected_basis_sources():
    expected_sources = {
        standards.InputGuidanceKey.CREEP_COEFFICIENT: (
            "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010, 3.1.4 and Annex B.1",
            (
                "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010, 3.1.4 and "
                "Annex B.1; DS/EN 1992-1-1 DK NA:2024, 3.1.4(1)-(2)"
            ),
            "DS/EN 1992-1-1:2023, 5.1.5, Table 5.2 and Annex B.5",
        ),
        standards.InputGuidanceKey.DETAILING_MINIMUM_REINFORCEMENT: (
            (
                "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010, 9.2.1.1(1), "
                "Formula (9.1N), and 9.3.1.1(1)-(2)"
            ),
            (
                "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010, 9.2.1.1(1), "
                "Formula (9.1N), and 9.3.1.1(1)-(2); DS/EN 1992-1-1 "
                "DK NA:2024, 9.2.1.1(1)"
            ),
            (
                "DS/EN 1992-1-1:2023, 12.2(2), Formulae (12.1)-(12.2), "
                "and Table 12.2"
            ),
        ),
        standards.InputGuidanceKey.DETAILING_TRANSVERSE_LINKS: (
            (
                "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010, 9.2.2(2), "
                "9.2.2(5)-(8), Formulae (9.4)-(9.8), 9.2.3(3), and "
                "9.3.2(2), (4)-(5)"
            ),
            (
                "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010, 9.2.2(2), "
                "9.2.2(5)-(8), Formulae (9.4)-(9.8), 9.2.3(3), and "
                "9.3.2(2), (4)-(5); DS/EN 1992-1-1 DK NA:2024, "
                "9.2.2(5), Formula (9.5N NA)"
            ),
            (
                "DS/EN 1992-1-1:2023, 8.2.1(2), 12.2(4), Tables 12.1 "
                "and 12.2, 12.3.3 and 12.4.2"
            ),
        ),
        standards.InputGuidanceKey.DETAILING_CLEAR_SPACING: (
            "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010, 8.2(2)",
            (
                "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010, 8.2(2); "
                "DS/EN 1992-1-1 DK NA:2024, 8.2(2) unchanged"
            ),
            "DS/EN 1992-1-1:2023, 11.2(2)",
        ),
    }
    basis_order = (
        standards.DesignBasisKey.FIRST_GEN_BASE,
        standards.DesignBasisKey.FIRST_GEN_DK_NA_2024,
        standards.DesignBasisKey.PUBLISHED_2023,
    )

    for key, sources in expected_sources.items():
        for basis, source in zip(basis_order, sources, strict=True):
            guidance = standards.input_guidance(basis, key)
            assert guidance.source == source
            assert guidance.tooltip.endswith(f"Source: {source}.")

    dk_creep = standards.input_guidance(
        standards.DesignBasisKey.FIRST_GEN_DK_NA_2024,
        standards.InputGuidanceKey.CREEP_COEFFICIENT,
    )
    assert "phi = 3 is conditional" in dk_creep.guidance
    assert "does not infer whether creep is decisive" in dk_creep.guidance
    dk_minimum = standards.input_guidance(
        standards.DesignBasisKey.FIRST_GEN_DK_NA_2024,
        standards.InputGuidanceKey.DETAILING_MINIMUM_REINFORCEMENT,
    )
    assert "high-beam-web provision is not included" in dk_minimum.guidance
    published = standards.get_design_basis(
        standards.DesignBasisKey.PUBLISHED_2023
    )
    assert "project adoption required" in published.disclosure
    assert "no Danish National Annex" in published.disclosure


def test_input_guidance_lookup_fails_closed_for_unknown_or_unsupported_keys():
    for invalid in (
        None,
        "",
        "fatigue_mixed_bond ",
        "custom",
        "bond",
    ):
        with pytest.raises(ValueError, match="input guidance"):
            standards.parse_input_guidance_key(invalid)

    for unsupported in (
        (
            standards.DesignBasisKey.FIRST_GEN_BASE,
            standards.InputGuidanceKey.ORDINARY_CRACK_TENDON_BOND,
        ),
        (
            standards.DesignBasisKey.PUBLISHED_2023,
            standards.InputGuidanceKey.HEIGHTENED_CRACK_OPERANDS,
        ),
        (
            standards.DesignBasisKey.FIRST_GEN_BASE,
            standards.InputGuidanceKey.ORDINARY_CRACK_MEMBER_TYPE,
        ),
        (
            standards.DesignBasisKey.PUBLISHED_2023,
            standards.InputGuidanceKey.ORDINARY_CRACK_MEMBER_TYPE,
        ),
    ):
        with pytest.raises(ValueError, match="has no input guidance"):
            standards.input_guidance(*unsupported)


def test_context_records_are_non_selectable_and_have_no_solver_bindings():
    assert {
        (record.citation, record.role)
        for record in standards.STANDARD_CONTEXTS
    } == {
        (
            "DS/EN 1992-2:2005/AC:2008",
            standards.ContextRole.SOURCE_ONLY,
        ),
        (
            "DS/EN 1992-2 DK NA:2015",
            standards.ContextRole.CONTEXT_ONLY,
        ),
        (
            "DS/EN 1992-1-1:2023, normative Annex K",
            standards.ContextRole.CONTEXT_ONLY,
        ),
    }
    selectable_text = "\n".join(
        f"{basis.key.value}\n{basis.label}\n{basis.disclosure}"
        for basis in standards.DESIGN_BASES.values()
    )
    assert "1992-2 DK NA:2015" not in selectable_text
    assert "Annex K" not in selectable_text
    assert "EN 1992-2:2023" not in selectable_text


def test_catalogue_and_records_are_immutable():
    basis = standards.get_design_basis(EXPECTED_KEYS[0])
    with pytest.raises(FrozenInstanceError):
        setattr(basis, "label", "changed")
    with pytest.raises(TypeError):
        setitem(
            standards.DESIGN_BASES,
            standards.DesignBasisKey.FIRST_GEN_BASE,
            basis,
        )
    guidance = standards.input_guidance(
        standards.DesignBasisKey.FIRST_GEN_BASE,
        standards.InputGuidanceKey.FATIGUE_DETAIL_VALUES,
    )
    with pytest.raises(FrozenInstanceError):
        setattr(guidance, "source", "changed")
    with pytest.raises(TypeError):
        setitem(
            standards.INPUT_GUIDANCE,
            (
                standards.DesignBasisKey.FIRST_GEN_BASE,
                standards.InputGuidanceKey.FATIGUE_DETAIL_VALUES,
            ),
            guidance,
        )
