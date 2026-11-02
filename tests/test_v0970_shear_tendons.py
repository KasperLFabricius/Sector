"""TB-05: bonded tendons in Asl and d of the concrete shear resistance.

Hand calculation, section 300 x 600 mm with its centroid at the origin:
ordinary bars 2 x 500 mm2 at y = -0.25 m (ds = 550 mm), one bonded tendon
Ap = 600 mm2 at y = -0.20 m (dp = 500 mm).

- Option off: Asl = 1000 mm2, d = 550 mm.
- 2005 family, EN 1992-2 6.2.2(101), area-weighted:
  d = (550 x 1000 + 500 x 600)/1600 = 531.25 mm, Asl = 1600 mm2.
- DS/EN 1992-1-1:2023 Formula (8.36):
  d = (550^2 x 1000 + 500^2 x 600)/(550 x 1000 + 500 x 600) = 532.353 mm.
- Strands only: Asl = 600 mm2, d = 500 mm (the section had no shear result
  before 0.97.0, because d was 0).
"""

from __future__ import annotations

import pytest

from sector import capacity, codes

OUTER = [(-0.15, -0.3), (0.15, -0.3), (0.15, 0.3), (-0.15, 0.3)]
BARS = [(-0.1, -0.25, 500.0), (0.1, -0.25, 500.0)]
TENDONS = [(0.0, -0.2, 600.0)]


def _steel(bars, *, include, model_2023):
    inp = {
        "outer": OUTER,
        "bars": bars,
        "tendons": TENDONS,
        capacity.SHEAR_TENDONS_KEY: include,
    }
    return capacity.shear_tension_steel(inp, "x", True, 0.0, model_2023=model_2023)


def test_option_off_keeps_ordinary_bars_only():
    asl, _cg, _ids, d, ap = _steel(BARS, include=False, model_2023=False)
    assert (asl, d, ap) == pytest.approx((1000.0, 550.0, 0.0))


def test_2005_family_uses_area_weighted_depth():
    asl, cg, _ids, d, ap = _steel(BARS, include=True, model_2023=False)
    assert asl == pytest.approx(1600.0)
    assert ap == pytest.approx(600.0)
    assert d == pytest.approx(531.25)
    assert cg == pytest.approx(0.3 - 0.53125)


def test_2023_uses_formula_8_36():
    _asl, _cg, _ids, d, _ap = _steel(BARS, include=True, model_2023=True)
    assert d == pytest.approx(452.5e6 / 850000.0)
    assert d == pytest.approx(532.353, abs=1.0e-3)


def test_strand_only_section_has_a_depth():
    asl, _cg, _ids, d, _ap = _steel([], include=True, model_2023=False)
    assert (asl, d) == pytest.approx((600.0, 500.0))


def test_default_follows_the_edition():
    assert capacity.shear_tendons_default(codes.EC2_2023.label) is True
    assert capacity.shear_tendons_default(codes.EC2_2005_DKNA.label) is False
