"""Failure-message boundaries for the engineer-facing product."""

from __future__ import annotations

import pytest

from app import engineer_messages
from tools.audit_user_copy import developer_terms


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


def test_fallback_must_provide_an_engineering_action():
    with pytest.raises(ValueError, match="fallback"):
        engineer_messages.error_detail("detail", fallback="  ")
