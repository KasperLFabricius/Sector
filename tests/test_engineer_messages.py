"""Failure-message boundaries for the engineer-facing product."""

from __future__ import annotations

import pytest

from app import engineer_messages
from tools.audit_user_copy import DEVELOPER_TOKENS, developer_terms


@pytest.mark.parametrize(
    "diagnostic",
    [
        "SHA-256 mismatch in calculation payload",
        "equation contract key EQ-PLASTIC failed",
        "unknown current_schema field",
        "solver state has invalid metadata",
        "canonical JSON provenance hash mismatch",
        "Traceback from internal identifier",
        "dispatch kernel failure at source revision abc123",
        "unexpected _private_key state",
        "unexpected __cache_entry state",
        "details [private_key]",
        "x" * 241,
        "",
    ],
)
def test_software_diagnostics_are_replaced_and_logged(diagnostic, caplog):
    fallback = "Review the current engineering inputs and try again"

    visible = engineer_messages.error_detail(diagnostic, fallback=fallback)

    assert visible == fallback
    assert developer_terms(visible) == ()
    assert "Hidden software diagnostic" in caplog.text


def test_concise_engineering_detail_is_preserved_without_trailing_full_stop():
    visible = engineer_messages.error_detail(
        "Torsion wall thickness must be greater than zero.",
        fallback="Review the torsion inputs",
    )

    assert visible == "Torsion wall thickness must be greater than zero"


@pytest.mark.parametrize(
    "detail",
    [
        "gamma_Ff must be a finite number greater than zero",
        "gamma_s must be a finite number greater than zero",
        "gamma_V must be a finite number greater than zero",
        "gamma_c,fat must be a finite number greater than zero",
        "beta_cc(t0) must be a finite number greater than zero",
        "Concrete alpha_cc must be a finite number",
    ],
)
def test_eurocode_notation_is_preserved_in_engineering_guidance(detail):
    visible = engineer_messages.error_detail(
        detail,
        fallback="Review the fatigue inputs",
    )

    assert visible == detail


def test_engineering_notation_does_not_mask_a_software_diagnostic():
    fallback = "Review the fatigue inputs"

    visible = engineer_messages.error_detail(
        "gamma_s is unavailable in fatigue_gamma_s payload",
        fallback=fallback,
    )

    assert visible == fallback


@pytest.mark.parametrize(
    "identifier",
    ["_private_key", "__cache_entry", "fatigue_gamma_s"],
)
def test_private_and_application_identifiers_remain_hidden(identifier):
    fallback = "Review the current engineering inputs"

    visible = engineer_messages.error_detail(
        f"Unexpected {identifier} state",
        fallback=fallback,
    )

    assert visible == fallback


@pytest.mark.parametrize("developer_term", DEVELOPER_TOKENS)
def test_runtime_screen_covers_the_copy_audit_vocabulary(developer_term):
    fallback = "Review the current engineering inputs"

    visible = engineer_messages.error_detail(
        f"Unexpected {developer_term.strip()} in the calculation",
        fallback=fallback,
    )

    assert visible == fallback


def test_internal_equation_identifier_is_hidden_without_an_explanatory_keyword():
    fallback = "Review the current engineering inputs"

    visible = engineer_messages.error_detail(
        "EQ-PLASTIC-07 failed",
        fallback=fallback,
    )

    assert visible == fallback


def test_fallback_must_provide_an_engineering_action():
    with pytest.raises(ValueError, match="fallback"):
        engineer_messages.error_detail("detail", fallback="  ")
