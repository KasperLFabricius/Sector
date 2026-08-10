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
        assert (
            "traffic models, dynamic effects, lane/track concurrence, owner "
            "requirements and complete bridge-fatigue compliance are not "
            "assessed"
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
    assert "does not infer" in binding.disclosure

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
