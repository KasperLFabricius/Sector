"""MN-01 and MN-02: the manual examples state values that a checker can repeat."""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))

import manual  # noqa: E402

from sector.codes import fctm  # noqa: E402
from sector.serviceability import analyse_cracking  # noqa: E402


def _text() -> str:
    return "\n".join(str(block) for block in manual.manual_blocks())


def test_v_min_of_shear_example_follows_dk_na_formula():
    # DK NA:2024 6.2.2(1): v_min = (0.051/gamma_c) k^1.5 fck^0.5 with gamma_c = 1.45,
    # k = 1 + sqrt(200/550) = 1.603 and fck = 35 MPa.
    k = 1.0 + (200.0 / 550.0) ** 0.5
    v_min = 0.051 / 1.45 * k ** 1.5 * 35.0 ** 0.5
    assert v_min == pytest.approx(0.4223, abs=5.0e-5)
    assert "$v_{min}=0.422$ MPa" in _text()
    assert "0.535" not in _text()


def test_crack_width_example_states_duration_and_short_term_values():
    text = _text()
    assert "$k_t=0.4$" in text and "$k_t=0.6$" in text
    assert "0.162, 0.141, 0.068 and 0.149 mm" in text
    ex = manual.example_beam()
    section = manual._section_of(ex)
    fct = fctm(ex["concrete"].fck)
    expected = {
        "2005": ({}, 0.162),
        "fine": ({"k3_cover_dependent": True}, 0.141),
        "coarse": ({"k3_cover_dependent": True, "coarse": True}, 0.068),
        "2023": ({"edition": "2023"}, 0.149),
    }
    for options, width in expected.values():
        result = analyse_cracking(
            section, 0.0, manual._BEAM_SLS_MX, 0.0, 6.0, fctm=fct,
            bar_diameter=25.0, cover=37.5, beta=0.5, kt=0.6, **options,
        )
        assert result.crack.wk == pytest.approx(width, abs=0.0005)


def test_status_table_lists_every_displayed_status():
    # MN-03: each status that a result view or report can show has a manual row.
    from sector import fatigue

    rows = {row[0] for block in manual.manual_blocks()
            if getattr(block, "kind", None) == "table"
            for row in (getattr(block, "rows", None) or ())}
    text = _text() if not rows else "\n".join(rows)
    for status in (
        "REVIEW",
        "UNVERIFIED",
        "PROVIDED AREA BELOW CALCULATED REQUIREMENT",
        fatigue.SIMPLIFIED_SCREEN_DETAILED,
        "NOT AVAILABLE",
        "INVALID",
        "NOT ASSESSED",
        "NOT APPLICABLE",
    ):
        assert status in text
