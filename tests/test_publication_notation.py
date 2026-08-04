"""Adversarial contract tests for the shared publication notation layer."""

from __future__ import annotations

import pathlib
import sys

import pytest
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import manual  # noqa: E402
import publication_notation as notation  # noqa: E402
import sector_report  # noqa: E402


@pytest.mark.parametrize(
    ("source", "mantissa", "exponent", "suffix"),
    [
        ("1e-12", "1", "-12", ""),
        ("1E-12", "1", "-12", ""),
        ("+1.25e+06", "+1.25", "6", ""),
        ("-0,5E3", "-0,5", "3", ""),
        ("1 234,5e-06", "1 234,5", "-6", ""),
        ("1e-9%", "1", "-9", "%"),
        ("1e-9 %", "1", "-9", "%"),
        ("2E+03deg", "2", "3", "deg"),
        ("2E+03 deg", "2", "3", "deg"),
    ],
)
def test_scientific_inventory_is_complete(source, mantissa, exponent, suffix):
    rendered = notation.normalize_trusted_markup(source)

    assert rendered.count("<nobr>") == 1
    assert rendered.count("</nobr>") == 1
    assert f"{mantissa} &#215; 10<super>{exponent}</super>" in rendered
    assert (f"&nbsp;{suffix}" in rendered) if suffix else "&nbsp;" not in rendered
    assert notation.normalize_trusted_markup(rendered) == rendered


@pytest.mark.parametrize(
    "source",
    ["1e", "1e-", "case1e-9", "1e-9mm", "1e-9x", "value_e-9"],
)
def test_malformed_and_identifier_near_matches_are_inert(source):
    assert notation.normalize_trusted_markup(source) == source


def test_unit_power_inventory_and_existing_markup_are_idempotent():
    source = (
        "m2 cm3 mm4 mm2/mm; existing m<super>2</super>; "
        "<nobr>1 &#215; 10<super>-9</super>&nbsp;%</nobr>"
    )
    rendered = notation.normalize_trusted_markup(source)

    assert "m<super>2</super>" in rendered
    assert "cm<super>3</super>" in rendered
    assert "mm<super>4</super>" in rendered
    assert "mm<super>2</super>/mm" in rendered
    assert rendered.count("<nobr>") == 1
    assert notation.normalize_trusted_markup(rendered) == rendered


@pytest.mark.parametrize(
    "literal",
    [
        "Bridge 100 m2",
        "case 1e-12 %",
        "M2 / cm3 / mm4",
        "sigma 2E+03 deg & <issued>",
        "1,25e-6 source",
    ],
)
def test_literal_identity_survives_trusted_rendering_exactly(literal):
    shielded = notation.shield_literal_markup(literal)
    rendered = notation.normalize_trusted_markup(shielded)
    paragraph = Paragraph(rendered, getSampleStyleSheet()["BodyText"])

    assert paragraph.getPlainText() == literal
    assert "<nobr>" not in rendered
    assert "<super>" not in rendered


def test_report_and_manual_entry_points_apply_the_same_trusted_contract():
    source = "Tolerance 1e-12 m; area mm2; angle 2e3 deg."
    report = sector_report._greek(source)
    manual_markup = manual._inline_md_to_rl(source)

    for rendered in (report, manual_markup):
        assert "1 &#215; 10<super>-12</super>" in rendered
        assert "mm<super>2</super>" in rendered
        assert "2 &#215; 10<super>3</super>&nbsp;deg" in rendered
        assert notation.normalize_trusted_markup(rendered) == rendered


def test_report_literal_fence_precedes_greek_and_notation_layers():
    literal = "sigma case 1e-12 % in 100 m2"
    rendered = sector_report._greek(sector_report._html_escape(literal))
    paragraph = Paragraph(rendered, getSampleStyleSheet()["BodyText"])

    assert paragraph.getPlainText() == literal
    assert "&#963;" not in rendered
    assert "<nobr>" not in rendered
    assert "<super>" not in rendered
