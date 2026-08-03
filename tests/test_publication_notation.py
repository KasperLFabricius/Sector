"""Independent contract tests for publication notation and identity fencing."""

from __future__ import annotations

import pathlib
import sys

import pytest


ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import publication_notation  # noqa: E402
import manual  # noqa: E402
from sector import torsion_trace_contract  # noqa: E402


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1.25e-8, "1.25 &#215; 10<super>-8</super>"),
        (-3.5e9, "-3.5 &#215; 10<super>9</super>"),
        (12.5, "12.5"),
    ],
)
def test_scientific_markup_is_atomic_and_typographic(value, expected):
    rendered = publication_notation.scientific_markup(value)
    assert rendered == f"<nobr>{expected}</nobr>"
    assert "e+" not in rendered.casefold()
    assert "e-" not in rendered.casefold()


@pytest.mark.parametrize(
    "identity", ["m2", "cm3", "mm4", "Bridge m2", "Bridge 100 m2"]
)
def test_untrusted_literal_identity_is_not_rewritten_as_a_unit(identity):
    assert publication_notation.publication_markup(identity) == identity


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("1000.000 mm2", "1000.000</nobr> <nobr>mm<super>2</super>"),
        ("Area [cm3]", "[<nobr>cm<super>3</super></nobr>]"),
        ("stress N/mm2", "N/<nobr>mm<super>2</super></nobr>"),
        ("m4", "<nobr>m<super>4</super></nobr>"),
    ],
)
def test_engineering_context_controls_unit_power_conversion(content, expected):
    rendered = publication_notation.publication_markup(
        content, trusted_units=True, protect_numbers=True
    )
    assert expected in rendered


def test_numeric_token_protection_is_idempotent():
    once = publication_notation.protect_numeric_tokens("1.250 MPa and -4e-6")
    assert publication_notation.protect_numeric_tokens(once) == once
    assert once.count("<nobr>") == 2


@pytest.mark.parametrize(
    ("authored", "expected"),
    [
        ("1e-12 m", "1 &#215; 10<super>-12</super>"),
        ("-2.50E+9", "-2.50 &#215; 10<super>9</super>"),
    ],
)
def test_authored_scientific_strings_use_typographic_notation(authored, expected):
    rendered = publication_notation.publication_markup(
        authored, protect_numbers=True, typographic_science=True
    )
    assert expected in rendered
    assert "e-" not in rendered.casefold()
    assert "e+" not in rendered.casefold()


def test_untrusted_scientific_identity_remains_literal():
    rendered = publication_notation.publication_markup(
        "case 1e-12", protect_numbers=True
    )
    assert "1e-12" in rendered
    assert "&#215;" not in rendered


def test_manual_uses_the_shared_trusted_notation_layer():
    rendered = manual._inline_md_to_rl("Second moment 4 m4 at 1e-12 m")
    assert "<nobr>4</nobr>" in rendered
    assert "<nobr>m<super>4</super></nobr>" in rendered
    assert "1 &#215; 10<super>-12</super>" in rendered


def test_transverse_and_longitudinal_torsion_sources_remain_distinct():
    transverse = torsion_trace_contract.TRANSVERSE_SOURCE.citation
    longitudinal = torsion_trace_contract.LONGITUDINAL_SOURCE.citation
    assert transverse.clause == "6.3.2(1) and 6.2.3(3)"
    assert transverse.locator == "Formulae (6.27) and (6.8)"
    assert longitudinal.clause == "6.3.2(3)"
    assert longitudinal.locator == "Formula (6.28)"
