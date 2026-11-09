"""TB-05: bonded tendons in Asl and d of the concrete shear resistance.

Hand calculation, section 300 x 600 mm with its centroid at the origin:
ordinary bars 2 x 500 mm2 at y = -0.25 m (ds = 550 mm), one bonded tendon
Ap = 600 mm2 at y = -0.20 m (dp = 500 mm).

- Option off: Asl = 1000 mm2, d = 550 mm.
- EN 1992-1-1:2004 family, EN 1992-2 6.2.2(101), area-weighted mean d:
  d = (550 x 1000 + 500 x 600)/1600 = 531.25 mm, Asl = 1600 mm2.
- DS/EN 1992-1-1:2023 Formula (8.36):
  d = (550^2 x 1000 + 500^2 x 600)/(550 x 1000 + 500 x 600) = 532.353 mm.
  Formula (8.37): rho_l = (550 x 1000 + 500 x 600)/(bw d^2), so the area that
  gives rho_l = area/(bw d) is 850000/532.353 = 1596.68 mm2.
- Strands only: Asl = 600 mm2, d = 500 mm (the section had no shear result
  before 0.97.0, because d was 0).
"""

from __future__ import annotations

import pytest

from sector import capacity, codes, shear_inputs
from sector.materials import MildSteel, Prestress

OUTER = [(-0.15, -0.3), (0.15, -0.3), (0.15, 0.3), (-0.15, 0.3)]
BARS = [(-0.1, -0.25, 500.0), (0.1, -0.25, 500.0)]
TENDONS = [(0.0, -0.2, 600.0)]


def _steel(bars, *, include, model_2023, tendons=TENDONS, axis="x",
           tension_low=True, duct_case=None):
    inp = {
        "outer": OUTER,
        "bars": bars,
        "tendons": tendons,
        capacity.SHEAR_TENDONS_KEY: include,
    }
    if duct_case is not None:
        inp["shear_duct_case"] = duct_case
    return capacity.shear_tension_steel(
        inp, axis, tension_low, 0.0, model_2023=model_2023
    )


def test_option_off_keeps_ordinary_bars_only():
    steel = _steel(BARS, include=False, model_2023=False)
    assert (steel.asl, steel.d, steel.ap) == pytest.approx((1000.0, 550.0, 0.0))
    assert steel.rule == capacity.SHEAR_ASL_BARS
    assert steel.rho_area == pytest.approx(1000.0)


def test_2005_family_uses_area_weighted_depth():
    steel = _steel(BARS, include=True, model_2023=False)
    assert steel.asl == pytest.approx(1600.0)
    assert steel.ap == pytest.approx(600.0)
    assert steel.d == pytest.approx(531.25)
    assert steel.centroid == pytest.approx(0.3 - 0.53125)
    assert steel.rho_area == pytest.approx(1600.0)
    assert (steel.as_bars, steel.ds, steel.dp) == pytest.approx((1000.0, 550.0, 500.0))
    assert steel.rule == capacity.SHEAR_ASL_AREA_WEIGHTED
    assert steel.tendon_ids == [1]


def test_2023_uses_formulae_8_36_and_8_37():
    steel = _steel(BARS, include=True, model_2023=True)
    assert steel.d == pytest.approx(452.5e6 / 850000.0)
    assert steel.d == pytest.approx(532.353, abs=1.0e-3)
    # Formula (8.37): rho_l = (ds As + dp Ap)/(bw d^2) = rho_area/(bw d).
    assert steel.rho_area == pytest.approx(850000.0 / steel.d)
    assert steel.asl == pytest.approx(1600.0)
    assert steel.rule == capacity.SHEAR_ASL_FORMULA_8_36


def test_formula_8_37_with_a_spread_layout():
    # As = 500 mm2 at ds = 550 mm, Ap = 2000 mm2 at dp = 310 mm, bw = 300 mm:
    # d = (550^2 x 500 + 310^2 x 2000)/(550 x 500 + 310 x 2000) = 383.743 mm,
    # rho_l = 895000/(300 x 383.743^2) = 0.020259. (As + Ap)/(bw d) = 0.021716
    # overstates it by 7.2 %.
    bars = [(0.0, -0.25, 500.0)]
    tendons = [(-0.05, -0.01, 1000.0), (0.05, -0.01, 1000.0)]
    steel = _steel(bars, include=True, model_2023=True, tendons=tendons)
    assert steel.d == pytest.approx(343.45e6 / 895000.0)
    rho_l = steel.rho_area / (300.0 * steel.d)
    assert rho_l == pytest.approx(895000.0 / (300.0 * (343.45e6 / 895000.0) ** 2))
    assert rho_l == pytest.approx(0.020259, abs=1.0e-6)


def test_strand_only_section_has_a_depth():
    steel = _steel([], include=True, model_2023=False)
    assert (steel.asl, steel.d) == pytest.approx((600.0, 500.0))
    assert steel.rule == capacity.SHEAR_ASL_TENDONS_ONLY
    assert steel.rho_area == pytest.approx(600.0)


def test_hogging_face_and_y_axis_select_the_tension_side_tendons():
    # Hogging about x: the tension face is the top. A tendon at y = +0.22 m
    # (dp = 0.3 + 0.22 = 520 mm from the bottom fibre) joins the top bar
    # 400 mm2 at y = +0.25 m (ds = 550 mm). The bottom tendon stays out.
    bars = [(0.0, 0.25, 400.0), (0.0, -0.25, 900.0)]
    tendons = [(0.0, 0.22, 200.0), (0.0, -0.2, 600.0)]
    steel = _steel(bars, include=True, model_2023=False, tendons=tendons,
                   tension_low=False)
    assert (steel.as_bars, steel.ap) == pytest.approx((400.0, 200.0))
    assert steel.d == pytest.approx((550.0 * 400.0 + 520.0 * 200.0) / 600.0)
    assert steel.centroid == pytest.approx(-0.3 + steel.d / 1000.0)
    assert steel.tendon_ids == [1]
    # Bending about y with the left face in tension: x < 0 is the tension side.
    # Bars at x = -0.1 m give ds = 0.15 + 0.1 = 250 mm; the tendon at x = 0
    # is on the centroid line and stays out, as the bars there would.
    steel_y = _steel(BARS, include=True, model_2023=False, axis="y")
    assert (steel_y.as_bars, steel_y.ap, steel_y.d) == pytest.approx((500.0, 0.0, 250.0))


def test_several_tendon_rows_and_compression_side_tendons():
    # Two rows on the tension side: 300 mm2 at dp = 560 mm and 300 mm2 at
    # dp = 440 mm, so dp = 500 mm. A tendon in the compression half and a
    # zero-area tendon add nothing.
    tendons = [(0.0, -0.26, 300.0), (0.0, -0.14, 300.0), (0.0, 0.2, 800.0),
               (0.05, -0.2, 0.0)]
    steel = _steel(BARS, include=True, model_2023=False, tendons=tendons)
    assert steel.ap == pytest.approx(600.0)
    assert steel.dp == pytest.approx(500.0)
    assert steel.d == pytest.approx(531.25)
    assert steel.tendon_ids == [1, 2, 4]


@pytest.mark.parametrize(
    "duct_case",
    [shear_inputs.SHEAR_DUCT_UNGROUTED_OR_SOFT, shear_inputs.SHEAR_DUCT_DETAILS_INCOMPLETE],
)
def test_unbonded_duct_case_keeps_the_tendons_out(duct_case):
    # DS/EN 1992-1-1:2023 8.2.2(6) NOTE: unbonded tendons act on the action side.
    steel = _steel(BARS, include=True, model_2023=True, duct_case=duct_case)
    assert (steel.asl, steel.d, steel.ap) == pytest.approx((1000.0, 550.0, 0.0))
    assert steel.tendons_excluded == duct_case
    grouted = _steel(BARS, include=True, model_2023=True,
                     duct_case=shear_inputs.SHEAR_DUCT_GROUTED_STEEL)
    assert grouted.ap == pytest.approx(600.0)


def test_strand_only_face_uses_fpd_of_the_tendons():
    # DS/EN 1992-1-1:2023 8.2.1(4): fyd of Formula (8.20) is the design yield
    # strength of the flexural reinforcement, here fpd = fp0.1k/gamma_s.
    mild = MildSteel(fytk=550.0, fyck=550.0, futk=600.0, eut=0.05, gamma_y=1.2,
                     gamma_u=1.2, gamma_E=1.0, curve=3, k=1.0, ey0t=0.0, ey0c=0.0)
    strand = Prestress(fytk=1640.0, futk=1860.0, eut=0.035, gamma_y=1.2,
                       gamma_u=1.2, gamma_E=1.0, Es=195000.0)
    inp = {"outer": OUTER, "bars": [], "tendons": TENDONS, "steel": mild,
           "prestress": strand, "tendon_materials": [strand],
           capacity.SHEAR_TENDONS_KEY: True}
    steel = capacity.shear_tension_steel(inp, "x", True, 0.0, model_2023=True)
    assert capacity.shear_flexural_fyd(inp, steel) == pytest.approx(1640.0 / 1.2)
    mixed = dict(inp, bars=BARS)
    steel = capacity.shear_tension_steel(mixed, "x", True, 0.0, model_2023=True)
    assert capacity.shear_flexural_fyd(mixed, steel) == pytest.approx(550.0 / 1.2)


def test_default_follows_the_edition():
    assert capacity.shear_tendons_default(codes.EC2_2023.label) is True
    assert capacity.shear_tendons_default(codes.EC2_2005_DKNA.label) is False
