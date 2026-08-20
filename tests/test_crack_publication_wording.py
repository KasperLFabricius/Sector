from __future__ import annotations

import pytest

from tools.crack_publication_wording import retired_crack_wording_rules


@pytest.mark.parametrize(
    ("passage", "rule"),
    (
        ("with an optional user-specified criterion", "singular-optional-criterion-language"),
        ("If no criterion is entered", "blank-or-absent-criterion-language"),
        ("the shared crack criterion", "shared-crack-limit-language"),
        ("Permitted crack width (shared)", "shared-crack-limit-language"),
        ("the permitted crack width is a shared Analysis setting", "shared-crack-limit-language"),
        ("With no criterion the width remains calculated", "blank-or-absent-criterion-language"),
        ("One optional positive permitted width", "singular-optional-criterion-language"),
        ("Blank means the width is calculated without a criterion", "blank-or-absent-criterion-language"),
        ("supply the shared permitted width", "shared-crack-limit-language"),
        ("Without a criterion, crack width is numerical", "blank-or-absent-criterion-language"),
        ("the shared Analysis permitted width", "shared-crack-limit-language"),
        ("the shared permitted crack-width setting", "shared-crack-limit-language"),
        ("shared by every ordinary and heightened crack check", "shared-crack-limit-language"),
        ("One optional permitted width in Analysis settings is shared", "shared-crack-limit-language"),
        ("Shared user-specified permitted crack width", "shared-crack-limit-language"),
        ("permitted crack width is shared from Analysis settings", "shared-crack-limit-language"),
        ("Compared with the shared Analysis criterion", "shared-crack-limit-language"),
        ("The ordinary criteria are shared", "shared-crack-limit-language"),
        ("no criterion is supplied", "blank-or-absent-criterion-language"),
        ("an optional user-specified crack-width criterion", "singular-optional-criterion-language"),
    ),
)
def test_every_exact_base_retired_variant_is_detected(passage: str, rule: str) -> None:
    before = passage
    assert rule in retired_crack_wording_rules(passage)
    assert passage == before


@pytest.mark.parametrize(
    "passage",
    (
        "Optional crack width is enabled per Elastic action.",
        "Independent long-term and short-term criteria apply.",
        "A 0 mm limit states the matching width without comparison.",
        "The duration-matched criterion source is retained.",
        "Shared closed stirrups resist shear and torsion.",
        "The common member angle governs the check.",
        "Formula 7.100 NA uses a separate permitted-width operand.",
        "Crack results are shown. Shared member checks follow.",
        "Crack results are shown; shared reinforcement operands follow.",
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
def test_current_language_and_unrelated_shared_mechanics_are_allowed(passage: str) -> None:
    assert retired_crack_wording_rules(passage) == ()


@pytest.mark.parametrize("value", (None, False, 0, (), [], {}))
def test_non_text_passages_fail_closed(value: object) -> None:
    assert retired_crack_wording_rules(value) == ("invalid-text",)
