from __future__ import annotations

import pytest

from tools.crack_publication_wording import retired_crack_wording_rules


@pytest.mark.parametrize(
    "passage",
    (
        "the shared crack criterion",
        "Permitted crack width (shared)",
        "the permitted crack width is a shared Analysis setting",
        "the shared Analysis permitted width",
        "the shared permitted crack-width setting",
        "supply the shared permitted width",
        "shared by every ordinary and heightened crack check",
        "One optional permitted width in Analysis settings is shared",
        "Shared user-specified permitted crack width",
        "permitted crack width is shared from Analysis settings",
        "Compared with the shared Analysis criterion",
        "The ordinary criteria are shared",
        "the former shared crack-width value",
        "Stable row signature including the shared crack criterion where used.",
        "Lightweight identity for the shared permitted crack-width input.",
        "Schema 24 migrates the shared permitted crack width.",
    ),
)
def test_retired_shared_crack_limit_variants_are_detected(passage: str) -> None:
    before = passage
    assert retired_crack_wording_rules(passage) == (
        "shared-crack-limit-language",
    )
    assert passage == before


@pytest.mark.parametrize(
    "passage",
    (
        "Shared closed stirrups resist shear and torsion.",
        "The common member angle governs the check.",
        "Crack results are shown. Shared member checks follow.",
        "Crack results are shown, shared member checks follow.",
        "Crack results are shown; shared reinforcement operands follow.",
        "Crack results are shown: shared reinforcement operands follow.",
        "Are crack results shown? Shared member checks follow.",
        "Crack results are shown! Shared member checks follow.",
        "Shared member checks follow, crack results are shown.",
        "Shared member checks follow: crack results are shown.",
        "Shared member checks follow. Crack results are shown.",
        (
            "Plastic capacity, cracked-elastic stiffness and stress, and crack "
            "calculations use the material assigned to each element. Shared member "
            "checks for shear and torsion use the selected mild-steel material."
        ),
        (
            "The user declared applicability, permitted width, reinforcement surface, "
            "effective tensile strength and two effective tension areas. Sector derives "
            "the shared reinforcement operands from the retained ordinary crack result."
        ),
    ),
)
def test_unrelated_shared_mechanics_and_phrase_boundaries_are_allowed(
    passage: str,
) -> None:
    assert retired_crack_wording_rules(passage) == ()


@pytest.mark.parametrize(
    "passage",
    (
        "If no criterion is entered",
        "With no criteria the widths remain calculated",
        "Without a criterion, crack width is numerical",
        "No criterion is supplied",
        "With no permitted width the result is calculated",
        "If no permitted crack width is entered",
        "Without a permitted width, crack width is numerical",
        "No permitted crack width is provided",
        "If no crack criterion is entered",
        "Without a crack-width criterion the result remains numerical",
        "No crack width is set",
        "Without crack width, reinforcement stress is still reported",
    ),
)
def test_retired_explicit_no_field_variants_are_detected(passage: str) -> None:
    before = passage
    assert retired_crack_wording_rules(passage) == (
        "no-crack-limit-field-language",
    )
    assert passage == before


@pytest.mark.parametrize(
    "passage",
    (
        "The crack result evidence is absent.",
        "The retained crack branch is missing or unsupported.",
        "With no crack result evidence the row is not assessed.",
        "Without a fatigue criterion the fatigue screen remains unavailable.",
        "If no torsion criterion is entered, torsion is not assessed.",
        "No reinforcement criterion is supplied.",
        "Blank material rows are rejected.",
        "An absent retained result remains NOT ASSESSED.",
    ),
)
def test_unrelated_no_field_and_absence_language_are_allowed(passage: str) -> None:
    assert retired_crack_wording_rules(passage) == ()


def test_existing_shared_rule_remains_independent_of_no_field_rule() -> None:
    assert retired_crack_wording_rules("the shared crack criterion") == (
        "shared-crack-limit-language",
    )


@pytest.mark.parametrize("value", (None, False, 0, (), [], {}))
def test_non_text_passages_fail_closed(value: object) -> None:
    assert retired_crack_wording_rules(value) == ("invalid-text",)
