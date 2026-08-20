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
        "With no permitted width the result is calculated",
        "If no permitted crack width is entered",
        "If no crack criterion is entered",
        "With no crack-width criteria, only numerical widths are stated",
        "If no crack width is set",
        "With no permitted widths the comparison remains disabled",
    ),
)
def test_retired_with_or_if_no_field_variants_are_detected(passage: str) -> None:
    before = passage
    assert retired_crack_wording_rules(passage) == (
        "with-or-if-no-crack-limit-field-language",
    )
    assert passage == before


@pytest.mark.parametrize(
    "passage",
    (
        "Without a criterion, crack width is numerical",
        "Without criterion, crack width is numerical",
        "No criterion was entered",
        "No permitted crack width was provided",
        "With no crack result evidence the row is not assessed",
        "If no crack width result is retained, the row is not assessed",
        "With no permitted width branch the comparison is unavailable",
        "If no fatigue criterion is entered, fatigue is not assessed",
        "With no torsion criterion the torsion row remains unavailable",
        "The crack result evidence is absent",
    ),
)
def test_unowned_no_field_and_retained_result_forms_are_allowed(
    passage: str,
) -> None:
    assert retired_crack_wording_rules(passage) == ()


def test_existing_shared_rule_remains_independent_of_with_if_rule() -> None:
    assert retired_crack_wording_rules("the shared crack criterion") == (
        "shared-crack-limit-language",
    )


@pytest.mark.parametrize("value", (None, False, 0, (), [], {}))
def test_non_text_passages_fail_closed(value: object) -> None:
    assert retired_crack_wording_rules(value) == ("invalid-text",)
