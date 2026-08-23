"""PR-07 cross-surface reference, terminology and notation controls."""

from __future__ import annotations

import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import manual  # noqa: E402
import sector_report  # noqa: E402

from sector import codes, design_standards, material_presets, sls  # noqa: E402


_PERMILLE = chr(0x2030)
_GUIDANCE_KEYS = (
    design_standards.InputGuidanceKey.CREEP_COEFFICIENT,
    design_standards.InputGuidanceKey.DETAILING_MINIMUM_REINFORCEMENT,
    design_standards.InputGuidanceKey.DETAILING_TRANSVERSE_LINKS,
    design_standards.InputGuidanceKey.DETAILING_CLEAR_SPACING,
)
_BASIS_EDITIONS = (
    (
        design_standards.DesignBasisKey.FIRST_GEN_BASE,
        codes.EC2_2005.label,
    ),
    (
        design_standards.DesignBasisKey.FIRST_GEN_DK_NA_2024,
        codes.EC2_2005_DKNA.label,
    ),
    (
        design_standards.DesignBasisKey.PUBLISHED_2023,
        codes.EC2_2023.label,
    ),
)


def _manual_text() -> str:
    return "\n".join(str(block) for block in manual.manual_blocks())


def test_manual_and_report_use_the_registry_owned_input_sources() -> None:
    manual_text = _manual_text()
    for basis_key, edition in _BASIS_EDITIONS:
        for guidance_key in _GUIDANCE_KEYS:
            source = design_standards.input_guidance(
                basis_key,
                guidance_key,
            ).source
            assert source in manual_text
            assert sector_report._input_reference_source(
                edition,
                guidance_key,
            ) == source

    assert sector_report._input_reference_source(
        "Curve 2 (parabola-rectangle)",
        design_standards.InputGuidanceKey.CREEP_COEFFICIENT,
        project_defined=True,
    ) == "Project-defined input; no Eurocode source inferred."


def test_2023_material_references_are_exact_and_consistent() -> None:
    edition = codes.EC2_2023.label
    assert sector_report._concrete_ultimate_reference(edition) == (
        "DS/EN 1992-1-1:2023, 8.1.1(2)-(3) and 8.1.2(1), Formula (8.4)"
    )
    assert sector_report._steel_standard_reference(edition) == (
        "DS/EN 1992-1-1:2023, 5.2.4(1)-(3), Formula (5.11) and Figure 5.2"
    )
    assert sector_report._prestress_standard_reference(edition) == (
        "DS/EN 1992-1-1:2023, 5.3.3(1)-(3), Formula (5.12) and Figure 5.3"
    )
    manual_text = _manual_text()
    for phrase in (
        "Formulae (5.3)-(5.4)",
        "Formula (8.4)",
        "Formula (5.11)",
        "Figure 5.2",
        "Formula (5.12)",
        "Figure 5.3",
    ):
        assert phrase in manual_text
    assert re.search(r"(?<!DS/)EN 1992-1-1:2023", manual_text) is None


def test_user_facing_strain_notation_and_concrete_help_are_correct() -> None:
    manual_text = _manual_text()
    assert _PERMILLE in manual_text
    assert "per mille" not in manual_text.casefold()
    assert "permille" not in manual_text.casefold()

    for field in ("eps_c2", "eps_cu2"):
        assert _PERMILLE in material_presets.CONCRETE_FIELD_META[field][0]
        assert _PERMILLE in material_presets.CONCRETE_HELP[field]
    assert "2.0 " + _PERMILLE in material_presets.CONCRETE_HELP["eps_c2"]
    assert "3.5 " + _PERMILLE in material_presets.CONCRETE_HELP["eps_cu2"]

    concrete = material_presets.build_concrete(
        **material_presets.CONCRETE_PRESETS["Curve 2 (parabola-rectangle)"]
    )
    assert concrete.eps_c2 == pytest.approx(0.002)
    assert concrete.eps_cu2 == pytest.approx(0.0035)


def test_neutral_calculation_language_preserves_product_identity() -> None:
    manual_text = _manual_text()
    for removed_phrase in (
        "acceptance comparison",
        "authority route",
        "shared-link authority",
        "separate acceptance decision",
        "published evidence",
    ):
        assert removed_phrase not in manual_text.casefold()
    assert "is not a compliance-management, certification, sign-off" in manual_text
    assert sls.CRACK_CALCULATED_UNASSESSED == (
        "CALCULATED - NO LIMIT COMPARISON"
    )
