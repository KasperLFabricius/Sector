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
    """Short-term crack widths of the manual beam (kt = 0.6, n = 6).

    Hand calculation (EN 1992-1-1 7.3.4), 300 x 600 mm, As = 3 x 490.87 =
    1472.6 mm2 at d = 550 mm, As' = 2 x 201.06 = 402.1 mm2 at 50 mm, M = 150 kNm:
    cracked section 150 x^2 + 10846.3 x - 4960170 = 0 (displaced concrete
    (n - 1) As'), x = 149.25 mm, I = 1.7713e9 mm4,
    sigma_s = 6 x 150e6 x 400.75/1.7713e9 = 203.62 MPa.
    hc,eff = min(2.5 x 50, (600 - 149.25)/3, 300) = 125 mm, rho = 1472.6/37500 =
    0.03927, fct,eff = 0.3 x 40^(2/3) = 3.509 MPa:
    eps_sm - eps_cm = (203.62 - 0.6 x 3.509/0.03927 x (1 + 6 x 0.03927))/200000
    = 6.869e-4 (above 0.6 sigma_s/Es = 6.109e-4).
    sr,max = k3 c + 0.8 x 0.5 x 0.425 x 25/0.03927 = k3 x 37.5 + 108.23 mm:
    k3 = 3.4 gives 235.73 mm and wk = 0.162 mm; k3 = 3.4 (25/37.5)^(2/3) =
    2.5947 (7.3.4(3) Note) gives 205.53 mm and wk = 0.141 mm.
    The coarse-system (0.068 mm) and 2023 (0.149 mm) values are checks that the
    manual text agrees with the program.
    """
    text = _text()
    assert "$k_t=0.4$" in text and "$k_t=0.6$" in text
    assert "0.162, 0.141, 0.068 and 0.149 mm" in text
    strain = (203.62 - 0.6 * 3.509 / 0.03927 * (1.0 + 6.0 * 0.03927)) / 200000.0
    hand = {
        "2005": (3.4 * 37.5 + 108.23) * strain,
        "fine": (3.4 * (25.0 / 37.5) ** (2.0 / 3.0) * 37.5 + 108.23) * strain,
    }
    assert hand["2005"] == pytest.approx(0.162, abs=0.0005)
    assert hand["fine"] == pytest.approx(0.141, abs=0.0005)
    ex = manual.example_beam()
    section = manual._section_of(ex)
    fct = fctm(ex["concrete"].fck)
    expected = {
        "2005": ({}, hand["2005"]),
        "fine": ({"k3_cover_dependent": True}, hand["fine"]),
        "coarse": ({"k3_cover_dependent": True, "coarse": True}, 0.068),
        "2023": ({"edition": "2023"}, 0.149),
    }
    for options, width in expected.values():
        result = analyse_cracking(
            section, 0.0, manual._BEAM_SLS_MX, 0.0, 6.0, fctm=fct,
            bar_diameter=25.0, cover=37.5, beta=0.5, kt=0.6, **options,
        )
        assert result.crack.wk == pytest.approx(width, abs=0.0005)


def _status_table_rows():
    for block in manual.manual_blocks():
        if (
            isinstance(block, tuple)
            and block[0] == "table"
            and list(block[1]) == ["Status", "Meaning", "Next action"]
        ):
            return [str(row[0]) for row in block[2]]
    raise AssertionError("the manual has no status table")


def test_status_table_lists_every_displayed_status():
    # MN-03: each status that the Results Overview or a fatigue screen can show
    # has a row in the manual status table ("A / B" rows list two statuses).
    import result_presentation

    from sector import fatigue

    listed = {
        status.strip()
        for row in _status_table_rows()
        for status in row.split(" / ")
    }
    displayed = set(result_presentation.GOVERNING_OVERVIEW_STATUS_PRECEDENCE) | {
        "UNVERIFIED",
        fatigue.SIMPLIFIED_SCREEN_DETAILED,
        "NOT AVAILABLE",
    }
    assert displayed <= listed, sorted(displayed - listed)
