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
}


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


def test_only_the_three_verified_fatigue_capabilities_are_registered():
    assert {item.value for item in standards.Capability} == EXPECTED_CAPABILITIES
    assert set(standards.CAPABILITY_BINDINGS) == {
        (basis, capability)
        for basis in standards.DesignBasisKey
        for capability in standards.Capability
    }
    for capability in standards.Capability:
        assert tuple(
            basis.key for basis in standards.basis_options(capability)
        ) == tuple(standards.DesignBasisKey)


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
