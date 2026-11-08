"""TA-04 in the app: elastic and plastic bond strains, and the fail-closed path.

Hand calculation (independent of Sector output): 400 x 800 mm, C30/37, one
concentric tendon Ap = 1500 mm2, Ep = 195 GPa, IS = 1100/195000. The tendon area
displaces concrete, so the concrete area is 320000 - 1500 = 318500 mm2, and the
effective prestress force is P = 1500 * 1100 = 1.650 MN.

Elastic and fatigue models, nl = 18 (Ec,eff = 200000/18 MPa):
    eps_p(0) = IS + P/(Ec,eff * 318500) = 5.6410e-3 + 4.6626e-4 = 6.1073e-3
Plastic model, Ecm = entered Ec, here the Auto value 22000 (38/10)^0.3 =
32837 MPa (EN 1992-1-1 Table 3.1):
    eps_p(0) = IS + P/(Ecm * 318500) = 5.6410e-3 + 1.5776e-4 = 5.7988e-3
With an entered Ec = 30 GPa:
    eps_p(0) = 5.6410e-3 + 1.65e6/(30000 * 318500) = 5.6410e-3 + 1.7268e-4
             = 5.8137e-3
The creep strain under prestress does not recover in a short-term load to
failure, so the plastic model uses the short-term modulus.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import sector_app  # noqa: E402
from sector import capacity, material_presets  # noqa: E402
from sector.materials import Concrete, Prestress  # noqa: E402
from sector.elastic import solve_elastic_combined  # noqa: E402
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


def _inp(material, *, mode="Both", ec_gpa=ECM / 1000.0):
    tendons = [(0.0, 0.0, AP)]
    return dict(
        outer=OUTER, holes=[], bars=[], tendons=tendons,
        section=Section.from_polygon(corners=OUTER, bars_xy_area_mm2=tendons),
        geometry_error=None, material_error=None,
        bar_materials=[], steel=None, tendon_materials=[material],
        concrete=Concrete(fck=30.0, gamma_c=1.5, curve=2), nl=18.0,
        conc_Ec=ec_gpa, mode=mode, fatigue_on=False,
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


def test_plastic_bond_strain_uses_the_entered_ecm():
    inp = _inp(_tendon(), ec_gpa=30.0)
    sector_app._apply_bonded_prestrain(inp)
    plastic = inp["tendon_materials_uls"][0].IS
    assert plastic == pytest.approx(IS + P_N / (30_000.0 * A_NET), rel=1.0e-8)
    assert plastic == pytest.approx(5.8137e-3, abs=1.0e-7)


def test_plastic_only_run_continues_when_only_the_long_term_state_fails():
    # Same tendon as the rupture case: the long-term bond strain passes the
    # rupture strain, the short-term one (5.9 + 1725.75e3/(32837 * 318500) =
    # 6.065 per mille) does not.
    inp = _inp(
        _tendon(eut=0.0063, strain=0.0059, fytk=1200.0, futk=1300.0),
        mode="Plastic",
    )
    entered = inp["tendon_materials"][0]
    sector_app._apply_bonded_prestrain(inp)
    assert inp["material_error"] is None
    assert inp["tendon_bond_elastic_unavailable"] is True
    assert inp["tendon_materials"][0] is entered
    assert inp["tendon_materials_uls"][0].IS == pytest.approx(
        0.0059 + 0.0059 * EP * AP / (ECM * A_NET), rel=1.0e-8
    )
    inp = _inp(
        _tendon(eut=0.0063, strain=0.0059, fytk=1200.0, futk=1300.0),
        mode="Plastic",
    )
    inp["fatigue_on"] = True
    sector_app._apply_bonded_prestrain(inp)
    assert inp["material_error"] is sector_app._PRESTRESS_BOND_BLOCKER


def test_negative_bond_strain_law_carries_no_stress_until_the_strain_is_positive():
    law = _tendon().with_bond_strain(-0.0005)
    assert law.IS == -0.0005
    assert law.stress(law.IS + 0.0004) == 0.0
    assert law.stress(law.IS + 0.0010) > 0.0
    assert _tendon().with_bond_strain(0.004).IS == 0.004
    with pytest.raises(ValueError):
        _tendon().with_bond_strain(float("nan"))
    with pytest.raises(ValueError):
        Prestress(curve=6, IS=-0.0005, fytk=1600.0, futk=1860.0, eut=0.035,
                  gamma_y=1.15, gamma_u=1.15, gamma_E=1.15, Es=EP)


def test_lightly_stressed_top_tendon_gets_a_negative_bond_strain_in_the_app():
    """Pretensioned girder with a lightly stressed top tendon (review R2B-01).

    300 x 700 mm, C35/45 (Ec = 34.077 GPa), four 12 mm corner bars, bottom
    tendon 1120 mm2 with Ep IS = 1100 MPa, top tendon 280 mm2 with Ep IS =
    100 MPa. Under prestress alone the tendon stresses must be Ep IS (user
    decision); prestress alone elongates the concrete at the top tendon by more
    than its IS, so its bond strain difference is negative in both models.
    """
    outer = [(-0.15, -0.35), (0.15, -0.35), (0.15, 0.35), (-0.15, 0.35)]
    bars = [(-0.1, -0.3, 113.0), (0.1, -0.3, 113.0),
            (-0.1, 0.3, 113.0), (0.1, 0.3, 113.0)]
    tendons = [(0.0, -0.27, 1120.0), (0.0, 0.30, 280.0)]
    steel = material_presets.build_mild(
        **material_presets.MILD_PRESETS[
            "DS/EN 1992-1-1:2005 + DK NA:2024"
        ]
    )
    nl = 200_000.0 * 3.0 / 34_077.0
    inp = dict(
        outer=outer, holes=[], bars=bars, tendons=tendons,
        section=Section.from_polygon(corners=outer, bars_xy_area_mm2=bars + tendons),
        geometry_error=None, material_error=None,
        bar_materials=[steel] * 4, steel=steel,
        tendon_materials=[_tendon(strain=1100.0 / EP), _tendon(strain=100.0 / EP)],
        concrete=Concrete(fck=35.0, gamma_c=1.5, curve=2), nl=nl,
        conc_Ec=34.077, mode="Both", fatigue_on=False,
    )
    sector_app._apply_bonded_prestrain(inp)
    assert inp["material_error"] is None
    section = Section.from_polygon(corners=outer, bars_xy_area_mm2=bars + tendons)
    n_mult = np.asarray([1.0] * 4 + [EP / 200_000.0] * 2)
    for key, ratio in (
        ("tendon_materials", nl), ("tendon_materials_uls", 200_000.0 / 34_077.0),
    ):
        laws = inp[key]
        assert laws[1].IS < 0.0
        locked = np.asarray([0.0] * 4 + [law.Es * law.IS * 1000.0 for law in laws])
        state = solve_elastic_combined(
            section, 0.0, 0.0, 0.0, ratio, 0.0, 0.0, 0.0, ratio,
            n_mult=n_mult, prestress_stress=locked,
        )
        assert np.asarray(state.bar_stress_total[4:]) / 1000.0 == pytest.approx(
            [1100.0, 100.0], rel=1.0e-8
        )


def test_field_signature_binds_only_the_tendon_laws_of_its_family():
    # Codex review of PR #577: el_phi changes only the long-term (elastic) bond
    # strain, so a reused plastic result must keep its section field.
    import section_fields

    inp = _inp(_tendon())
    sector_app._apply_bonded_prestrain(inp)
    plastic = section_fields.context_signature(inp, "Plastic")
    elastic = section_fields.context_signature(inp, "Elastic")
    changed = dict(inp, nl=30.0, tendon_materials=[_tendon(strain=0.0062)])
    assert section_fields.context_signature(changed, "Plastic") == plastic
    assert section_fields.context_signature(changed, "Elastic") != elastic
    changed = dict(inp, tendon_materials_uls=[_tendon(strain=0.0059)])
    assert section_fields.context_signature(changed, "Plastic") != plastic
    assert section_fields.context_signature(changed, "Elastic") == elastic
