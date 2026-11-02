"""TA-04 in the app: elastic and plastic bond strains, and the fail-closed path.

Hand calculation (independent of Sector output): 400 x 800 mm, C30/37, one
concentric tendon Ap = 1500 mm2, Ep = 195 GPa, IS = 1100/195000. The tendon area
displaces concrete, so the concrete area is 320000 - 1500 = 318500 mm2, and the
effective prestress force is P = 1500 * 1100 = 1.650 MN.

Elastic and fatigue models, nl = 18 (Ec,eff = 200000/18 MPa):
    eps_p(0) = IS + P/(Ec,eff * 318500) = 5.6410e-3 + 4.6626e-4 = 6.1073e-3
Plastic model, Ecm = 22000 (38/10)^0.3 = 32837 MPa (EN 1992-1-1 Table 3.1):
    eps_p(0) = IS + P/(Ecm * 318500) = 5.6410e-3 + 1.5776e-4 = 5.7988e-3
The creep strain under prestress does not recover in a short-term load to
failure, so the plastic model uses the short-term modulus.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import sector_app  # noqa: E402
from sector import capacity  # noqa: E402
from sector.materials import Concrete, Prestress  # noqa: E402
from sector.section import Section  # noqa: E402

EP = 195_000.0
IS = 1100.0 / EP
AP = 1500.0
A_NET = 400.0 * 800.0 - AP
P_N = AP * 1100.0
ECM = 22_000.0 * (38.0 / 10.0) ** 0.3
OUTER = [(-0.2, -0.4), (0.2, -0.4), (0.2, 0.4), (-0.2, 0.4)]


def _tendon(eut=0.035, strain=IS, fytk=1600.0, futk=1860.0):
    return Prestress(curve=6, IS=strain, fytk=fytk, futk=futk, eut=eut,
                     gamma_y=1.15, gamma_u=1.15, gamma_E=1.15, Es=EP)


def _inp(material):
    tendons = [(0.0, 0.0, AP)]
    return dict(
        outer=OUTER, holes=[], bars=[], tendons=tendons,
        section=Section.from_polygon(corners=OUTER, bars_xy_area_mm2=tendons),
        geometry_error=None, material_error=None,
        bar_materials=[], steel=None, tendon_materials=[material],
        concrete=Concrete(fck=30.0, gamma_c=1.5, curve=2), nl=18.0,
    )


def test_elastic_and_plastic_bond_strains_match_the_hand_calculation():
    inp = _inp(_tendon())
    sector_app._apply_bonded_prestrain(inp)
    assert inp["material_error"] is None
    assert inp["tendon_effective_prestrain"] == [pytest.approx(IS)]
    elastic = inp["tendon_materials"][0].IS
    plastic = inp["tendon_materials_uls"][0].IS
    assert elastic == pytest.approx(IS + P_N / (200_000.0 / 18.0 * A_NET), rel=1.0e-8)
    assert elastic == pytest.approx(6.1073e-3, abs=1.0e-7)
    assert plastic == pytest.approx(IS + P_N / (ECM * A_NET), rel=1.0e-8)
    assert plastic == pytest.approx(5.7988e-3, abs=1.0e-7)
    assert capacity.plastic_tendon_materials(inp)[0].IS == plastic


def test_effective_prestress_force_uses_the_entered_strain():
    inp = _inp(_tendon())
    sector_app._apply_bonded_prestrain(inp)
    result = capacity.locked_in_prestress_result(inp)
    assert result.total_n_kn == pytest.approx(P_N / 1000.0)


def test_bond_strain_beyond_rupture_blocks_the_input():
    # IS = 5.9 per mille < eut = 6.3 per mille, but the elastic bond strain
    # 5.9 + 1725.75e3/(11111.1 * 318500) = 6.39 per mille passes it.
    inp = _inp(_tendon(eut=0.0063, strain=0.0059, fytk=1200.0, futk=1300.0))
    sector_app._apply_bonded_prestrain(inp)
    assert inp["material_error"] is sector_app._PRESTRESS_BOND_BLOCKER
    assert "tendon_materials_uls" not in inp


def test_missing_material_leaves_the_existing_blocker():
    inp = _inp(None)
    inp["material_error"] = "existing blocker"
    sector_app._apply_bonded_prestrain(inp)
    assert inp["material_error"] == "existing blocker"
    assert "tendon_effective_prestrain" not in inp


def test_plastic_laws_fall_back_without_the_derived_list():
    material = _tendon()
    assert capacity.plastic_tendon_materials({"tendon_materials": [material]}) == [
        material
    ]
