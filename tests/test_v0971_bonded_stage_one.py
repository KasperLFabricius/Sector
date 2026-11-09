"""R2B-06 and R3-07: the Stage I bond state and the Newton correction.

Owner decision of 8 November 2026 (PR #577 owner items 2 and 3): under
prestress alone the tendon stress is Ep IS also in Stage I. Sector derives the
Stage I locked-in stress on the uncracked section with one linear solve, and a
Newton step replaces the plain residual step of the correction. The block
message names the tendon, its effective stress and the concrete strain at its
level.

Hand calculation A (independent of Sector output): 300 x 600 mm, one tendon
Ap = 1000 mm2 at y = -190 mm, Ep = 195 GPa, Ep IS = 500 MPa, nl = 18 with the
steel reference modulus 200 GPa, so n_p = 18 x 195/200 = 17.55. Under prestress
alone in Stage I the concrete carries the tendon force P = 500 kN on the
section without tendon stiffness. The tendon displaces its concrete:

    A_n = 180000 - 1000 = 179000 mm2
    y_n = 1000 x 190 / 179000 = 1.06145 mm (above the gross centroid)
    I_n = 300 x 600^3/12 + 180000 y_n^2 - 1000 (190 + y_n)^2 = 5.363698e9 mm4
    sigma_c(y) = -P/A_n - P (y_t - y_n)(y - y_n)/I_n   (tension positive)
    sigma_c(y_t) = -6.19622 MPa, top fibre +2.53098 MPa, bottom -8.15538 MPa
    sigma_0,I = 500 - n_p sigma_c(y_t) = 500 + 17.55 x 6.19622 = 608.7436 MPa

With an external sagging moment of 150 kNm on the transformed uncracked
section (tendon (n_p - 1) Ap):

    A_t = 180000 + 16.55 x 1000 = 196550 mm2, y_c = -15.99847 mm,
    I_t = 300 x 600^3/12 + 180000 y_c^2 + 16550 (-190 - y_c)^2 = 5.947148e9 mm4
    sigma_ext(bottom) = 150e6 (300 - 15.99847)/I_t = 7.16314 MPa
    lambda_cr = (f_ctm - sigma_pre) / sigma_ext = (3.0 + 8.15538)/7.16314
              = 1.557332   (EN 1992-1-1 7.1: Stage I tension reaches f_ct,eff)

Hand calculation B: 300 x 700 mm, four 113 mm2 bars at (+-100, +-300) mm, bottom
tendon 1120 mm2 at y = -270 mm with Ep IS = 1100 MPa, top tendon 420 mm2 at
y = +300 mm with Ep IS = 700 MPa, nl = 200000 x 3/34077 = 17.60718
(n_p = 17.16700). One-dimensional section without tendon stiffness: concrete,
bars (nl - 1) As, tendons -Ap (displaced concrete). The plane
sigma_c(y) = a + k y solves [A S; S I][a; k] = [-sum P; -sum P y]:

    a = -7.087890 MPa, k = 2.69068827e-2 MPa/mm
    top fibre +2.32952 MPa, sigma_c(-270) = -14.35275 MPa, sigma_c(300) = 0.98418 MPa
    sigma_0,I = 1100 + 17.167 x 14.35275 = 1346.3937 MPa
                700 - 17.167 x 0.98418 = 683.1047 MPa
"""

from __future__ import annotations

import copy
import pathlib
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "app", ROOT / "tests"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import sector.elastic as elastic  # noqa: E402
from sector.elastic import (  # noqa: E402
    BondedPrestressError,
    bonded_prestress_stress,
    solve_elastic_combined,
    solve_elastic_uncracked,
)
from sector.materials import Concrete, Prestress  # noqa: E402
from sector.section import Section  # noqa: E402
from sector.serviceability import analyse_cracking, combined_cracking  # noqa: E402

EP = 195_000.0
ES = 200_000.0


def _hand_a():
    ag, ig = 300.0 * 600.0, 300.0 * 600.0 ** 3 / 12.0
    ap, yt, force = 1000.0, -190.0, 1000.0 * 500.0
    an = ag - ap
    yn = ap * 190.0 / an
    i_n = ig + ag * yn ** 2 - ap * (yt - yn) ** 2

    def stress(y):
        return -force / an - force * (yt - yn) * (y - yn) / i_n

    n_p = 18.0 * EP / ES
    at = ag + (n_p - 1.0) * ap
    yc = (n_p - 1.0) * ap * yt / at
    it = ig + ag * yc ** 2 + (n_p - 1.0) * ap * (yt - yc) ** 2
    external_bottom = 150.0e6 * (300.0 + yc) / it
    return dict(
        stress=stress, locked=500.0 - n_p * stress(yt),
        external_bottom=external_bottom,
        lam=(3.0 - stress(-300.0)) / external_bottom,
    )


def _section_a():
    return Section.from_polygon(
        corners=[(-0.15, -0.3), (0.15, -0.3), (0.15, 0.3), (-0.15, 0.3)],
        bars_xy_area_mm2=[(0.0, -0.19, 1000.0)],
    )


A_MULT = np.asarray([EP / ES])
A_EFF = np.asarray([500.0e3])


def test_hand_values():
    hand = _hand_a()
    assert hand["stress"](-190.0) == pytest.approx(-6.19622, abs=1.0e-5)
    assert hand["stress"](300.0) == pytest.approx(2.53098, abs=1.0e-5)
    assert hand["stress"](-300.0) == pytest.approx(-8.15538, abs=1.0e-5)
    assert hand["locked"] == pytest.approx(608.7436, abs=1.0e-4)
    assert hand["external_bottom"] == pytest.approx(7.16314, abs=1.0e-5)
    assert hand["lam"] == pytest.approx(1.557332, abs=1.0e-6)


def test_stage_one_locked_stress_of_one_tendon_matches_the_hand_calculation():
    hand = _hand_a()
    locked = bonded_prestress_stress(
        _section_a(), 18.0, A_EFF, n_mult=A_MULT, cracked=False
    )
    assert locked[0] / 1000.0 == pytest.approx(hand["locked"], rel=1.0e-9)
    # Owner item 2: one linear solve. Without a Newton step the direct solution
    # must already meet the tolerance and give the hand value.
    direct = bonded_prestress_stress(
        _section_a(), 18.0, A_EFF, n_mult=A_MULT, cracked=False, max_iter=0
    )
    assert direct[0] / 1000.0 == pytest.approx(hand["locked"], rel=1.0e-9)
    state = solve_elastic_uncracked(
        _section_a(), 0.0, 0.0, 0.0, 18.0, n_mult=A_MULT, prestress_stress=locked
    )
    assert (locked[0] + state.bar_stress[0]) / 1000.0 == pytest.approx(
        500.0, rel=1.0e-12
    )
    assert state.max_concrete_tension / 1000.0 == pytest.approx(
        hand["stress"](300.0), rel=1.0e-9
    )


def test_stage_two_stress_in_stage_one_misses_the_effective_stress():
    # Before the change the Stage I check used the no-tension locked-in stress.
    # Prestress alone puts the top fibre in tension, so the two states differ
    # and that stress misses Ep IS = 500 MPa in Stage I.
    cracked = bonded_prestress_stress(_section_a(), 18.0, A_EFF, n_mult=A_MULT)
    state = solve_elastic_uncracked(
        _section_a(), 0.0, 0.0, 0.0, 18.0, n_mult=A_MULT, prestress_stress=cracked
    )
    assert abs((cracked[0] + state.bar_stress[0]) / 1000.0 - 500.0) > 5.0


def test_stage_one_locked_stress_with_bars_and_two_tendons_matches_the_hand_calculation():
    nl = ES * 3.0 / 34_077.0
    n_p = nl * EP / ES
    elements = [(-300.0, 226.0, nl - 1.0), (300.0, 226.0, nl - 1.0),
                (-270.0, 1120.0, -1.0), (300.0, 420.0, -1.0)]
    area = 300.0 * 700.0 + sum(w * a for _, a, w in elements)
    first = sum(w * a * y for y, a, w in elements)
    second = 300.0 * 700.0 ** 3 / 12.0 + sum(w * a * y * y for y, a, w in elements)
    forces = [(-270.0, 1120.0 * 1100.0), (300.0, 420.0 * 700.0)]
    rhs_n = -sum(f for _, f in forces)
    rhs_m = -sum(f * y for y, f in forces)
    det = area * second - first * first
    a0 = (rhs_n * second - first * rhs_m) / det
    k = (area * rhs_m - first * rhs_n) / det
    hand = [1100.0 - n_p * (a0 + k * -270.0), 700.0 - n_p * (a0 + k * 300.0)]
    assert a0 + k * 350.0 == pytest.approx(2.32952, abs=1.0e-5)
    assert hand == pytest.approx([1346.3937, 683.1047], abs=1.0e-4)

    bars = [(-0.1, -0.3, 113.0), (0.1, -0.3, 113.0),
            (-0.1, 0.3, 113.0), (0.1, 0.3, 113.0)]
    section = Section.from_polygon(
        corners=[(-0.15, -0.35), (0.15, -0.35), (0.15, 0.35), (-0.15, 0.35)],
        bars_xy_area_mm2=bars + [(0.0, -0.27, 1120.0), (0.0, 0.30, 420.0)],
    )
    n_mult = np.asarray([1.0] * 4 + [EP / ES] * 2)
    effective = np.asarray([0.0] * 4 + [1100.0e3, 700.0e3])
    locked = bonded_prestress_stress(
        section, nl, effective, n_mult=n_mult, cracked=False
    )
    assert locked[:4] == pytest.approx([0.0] * 4, abs=0.0)
    assert locked[4:] / 1000.0 == pytest.approx(hand, rel=1.0e-9)
    state = solve_elastic_uncracked(
        section, 0.0, 0.0, 0.0, nl, n_mult=n_mult, prestress_stress=locked
    )
    assert (locked + state.bar_stress)[4:] / 1000.0 == pytest.approx(
        [1100.0, 700.0], rel=1.0e-12
    )
    assert state.max_concrete_tension / 1000.0 == pytest.approx(
        a0 + k * 350.0, rel=1.0e-9
    )


def test_cracking_checks_use_the_stage_one_stress():
    hand = _hand_a()
    stage_two = bonded_prestress_stress(_section_a(), 18.0, A_EFF, n_mult=A_MULT)
    stage_one = bonded_prestress_stress(
        _section_a(), 18.0, A_EFF, n_mult=A_MULT, cracked=False
    )
    alone = analyse_cracking(
        _section_a(), 0.0, 0.0, 0.0, 18.0, fctm=3.0, n_mult=A_MULT,
        prestress_stress=stage_two, stage_one_prestress_stress=stage_one,
    )
    assert alone.sigma_ct == pytest.approx(hand["stress"](300.0), rel=1.0e-9)
    assert alone.cracked is False and alone.lambda_cr == float("inf")
    # The Stage II state keeps its own locked-in stress: Ep IS under prestress alone.
    assert (stage_two[0] + alone.cracked_state.bar_stress[0]) / 1000.0 == pytest.approx(
        500.0, rel=1.0e-9
    )
    loaded = analyse_cracking(
        _section_a(), 0.0, 150.0, 0.0, 18.0, fctm=3.0, n_mult=A_MULT,
        prestress_stress=stage_two, stage_one_prestress_stress=stage_one,
    )
    assert loaded.lambda_cr == pytest.approx(hand["lam"], rel=1.0e-9)
    assert loaded.cracked is False
    cracked, lam, sigma_ct = combined_cracking(
        _section_a(), 0.0, 0.0, 0.0, 18.0, 0.0, 0.0, 0.0, 6.0, fctm=3.0,
        n_mult=A_MULT, prestress_stress=stage_two,
        stage_one_prestress_stress=stage_one,
    )
    assert sigma_ct == pytest.approx(hand["stress"](300.0), rel=1.0e-9)
    assert (cracked, lam) == (False, float("inf"))
    cracked, lam, _ = combined_cracking(
        _section_a(), 0.0, 150.0, 0.0, 18.0, 0.0, 0.0, 0.0, 6.0, fctm=3.0,
        n_mult=A_MULT, prestress_stress=stage_two,
        stage_one_prestress_stress=stage_one,
    )
    assert lam == pytest.approx(hand["lam"], rel=1.0e-9)


def test_stage_one_stress_needs_the_stage_two_stress():
    stage_one = np.asarray([608.0e3])
    with pytest.raises(ValueError, match="Stage I"):
        analyse_cracking(_section_a(), 0.0, 0.0, 0.0, 18.0, fctm=3.0,
                         n_mult=A_MULT, stage_one_prestress_stress=stage_one)
    with pytest.raises(ValueError, match="Stage I"):
        combined_cracking(_section_a(), 0.0, 0.0, 0.0, 18.0, 0.0, 0.0, 0.0, 6.0,
                          fctm=3.0, n_mult=A_MULT,
                          stage_one_prestress_stress=stage_one)


# R3-07 box section (review case 349): 550 x 626 mm, 120 mm walls, eight
# tendons and no bars, n = 12. The direct solution leaves a residual of about
# 6e-9 x max Ep IS, and the plain residual step reduced it only by a factor of
# about 0.85 per step, so 100 steps did not reach 1e-10 x max Ep IS. The section
# is not physical (about 757 MPa concrete compression under prestress alone),
# but the input is valid and the defining condition must hold.
BOX_TENDONS = [
    (-0.017, 0.253, 2383.0), (0.046, -0.253, 633.0), (0.098, 0.253, 1667.0),
    (0.223, 0.253, 4150.0), (-0.081, -0.253, 756.0), (-0.052, -0.253, 200.0),
    (0.223, 0.253, 5565.0), (-0.150, 0.253, 2902.0),
]
BOX_STRESS = np.asarray([61.7, 110.7, 722.3, 844.2, 776.6, 1416.3, 830.6, 61.7]) * 1000.0


def _box():
    bw, hh, t = 0.550, 0.626, 0.120
    return Section.from_polygon(
        corners=[(-bw / 2, -hh / 2), (bw / 2, -hh / 2), (bw / 2, hh / 2),
                 (-bw / 2, hh / 2)],
        holes=[[(-bw / 2 + t, -hh / 2 + t), (bw / 2 - t, -hh / 2 + t),
                (bw / 2 - t, hh / 2 - t), (-bw / 2 + t, hh / 2 - t)]],
        bars_xy_area_mm2=BOX_TENDONS,
    )


def _residual_step_iteration(section, n, effective, n_mult, steps):
    """The 0.97.0 correction: a plain residual step after the direct solution."""
    tendon = effective != 0.0
    bx, by, _ = section.bar_arrays()
    free = solve_elastic_combined(
        section, 0.0, 0.0, 0.0, n, 0.0, 0.0, 0.0, n,
        n_mult=np.where(tendon, 0.0, n_mult),
        prestress_stress=np.where(tendon, effective, 0.0),
    ).long
    locked = effective - n * n_mult * (free.eps0 + free.kx * bx + free.ky * by)
    for _ in range(steps):
        state = solve_elastic_combined(
            section, 0.0, 0.0, 0.0, n, 0.0, 0.0, 0.0, n,
            n_mult=n_mult, prestress_stress=locked,
        )
        locked = locked + effective - np.asarray(state.bar_stress_total)
    state = solve_elastic_combined(
        section, 0.0, 0.0, 0.0, n, 0.0, 0.0, 0.0, n,
        n_mult=n_mult, prestress_stress=locked,
    )
    return np.max(np.abs(np.asarray(state.bar_stress_total) - effective))


def test_one_newton_step_converges_where_the_residual_step_stalled():
    n_mult = np.full(8, EP / ES)
    tolerance = 1.0e-10 * BOX_STRESS.max()
    assert _residual_step_iteration(_box(), 12.0, BOX_STRESS, n_mult, 10) > tolerance
    locked = bonded_prestress_stress(
        _box(), 12.0, BOX_STRESS, n_mult=n_mult, max_iter=1
    )
    state = solve_elastic_combined(
        _box(), 0.0, 0.0, 0.0, 12.0, 0.0, 0.0, 0.0, 12.0,
        n_mult=n_mult, prestress_stress=locked,
    )
    assert np.max(np.abs(np.asarray(state.bar_stress_total) - BOX_STRESS)) <= tolerance


def test_correction_failure_names_the_tendon_and_its_state():
    # No Newton step is allowed, so the residual of the direct solution stays.
    n_mult = np.full(8, EP / ES)
    with pytest.raises(BondedPrestressError) as caught:
        bonded_prestress_stress(_box(), 12.0, BOX_STRESS, n_mult=n_mult, max_iter=0)
    error = caught.value
    assert isinstance(error, ValueError)
    assert "did not converge" in str(error)
    assert 0 <= error.element < 8
    assert error.effective_stress == BOX_STRESS[error.element]
    assert np.isfinite(error.concrete_stress)


def test_an_elastic_state_that_does_not_converge_names_no_tendon(monkeypatch):
    def not_converged(rings, bx, by, ba, target, *args, **kwargs):
        return np.zeros(3), False, 100, np.zeros(3), np.eye(3)

    monkeypatch.setattr(elastic, "_newton_solve", not_converged)
    with pytest.raises(BondedPrestressError, match="did not converge") as caught:
        bonded_prestress_stress(_section_a(), 18.0, A_EFF, n_mult=A_MULT)
    assert caught.value.element is None


def test_a_bonded_check_that_does_not_converge_blocks(monkeypatch):
    # The direct solution converges; the check of the bonded model does not.
    original = elastic._newton_solve
    calls = []

    def second_fails(*args, **kwargs):
        calls.append(1)
        result = original(*args, **kwargs)
        return result if len(calls) == 1 else (result[0], False) + result[2:]

    monkeypatch.setattr(elastic, "_newton_solve", second_fails)
    with pytest.raises(BondedPrestressError, match="did not converge") as caught:
        bonded_prestress_stress(_section_a(), 18.0, A_EFF, n_mult=A_MULT)
    assert caught.value.element is None and len(calls) == 2


@pytest.mark.filterwarnings("ignore:overflow encountered:RuntimeWarning")
def test_a_bond_state_that_is_not_finite_blocks():
    # A modular ratio of 1e308 makes n x n_mult x sigma_c overflow.
    with pytest.raises(BondedPrestressError, match="not finite"):
        bonded_prestress_stress(_section_a(), 1.0e308, A_EFF, n_mult=A_MULT)


def test_tendon_flags_must_match_the_elements():
    with pytest.raises(ValueError, match="one tendon flag"):
        bonded_prestress_stress(_section_a(), 18.0, A_EFF, tendon_mask=[True, False])
    with pytest.raises(ValueError, match="ordinary bar"):
        bonded_prestress_stress(_section_a(), 18.0, A_EFF, tendon_mask=[False])


def test_a_singular_stage_one_section_blocks(monkeypatch):
    def singular(rings, bx, by, ba, u, n, displace_concrete, cracked, n_mult=None):
        return np.zeros(3), np.zeros((3, 3))

    monkeypatch.setattr(elastic, "_resultants_and_jacobian", singular)
    with pytest.raises(BondedPrestressError) as caught:
        bonded_prestress_stress(
            _section_a(), 18.0, A_EFF, n_mult=A_MULT, cracked=False
        )
    assert caught.value.element is None


@pytest.mark.parametrize("matrix", [np.zeros((3, 3)), np.full((3, 3), np.nan)],
                         ids=["singular", "not-finite"])
def test_a_singular_newton_matrix_gives_the_residual_step(matrix):
    residual = np.asarray([0.0, 2.0, -3.0])
    step = elastic._newton_correction(
        matrix, np.zeros(3), np.zeros(3), np.ones(3), np.ones(3),
        np.asarray([False, True, True]), residual,
    )
    assert step == pytest.approx(residual)


# Application: the Stage I state and the block message.

import sector_app  # noqa: E402


def _tendon(strain):
    return Prestress(curve=6, IS=strain, fytk=1600.0, futk=1860.0, eut=0.035,
                     gamma_y=1.15, gamma_u=1.15, gamma_E=1.15, Es=EP)


def _inp(mode="Both", fatigue=False):
    outer = [(-0.15, -0.3), (0.15, -0.3), (0.15, 0.3), (-0.15, 0.3)]
    tendons = [(0.0, -0.19, 1000.0)]
    return dict(
        outer=outer, holes=[], bars=[], tendons=tendons,
        section=Section.from_polygon(corners=outer, bars_xy_area_mm2=tendons),
        geometry_error=None, material_error=None,
        bar_materials=[], steel=None, tendon_materials=[_tendon(500.0 / EP)],
        concrete=Concrete(fck=30.0, gamma_c=1.5, curve=2), nl=18.0,
        conc_Ec=33.0, mode=mode, fatigue_on=fatigue,
    )


def test_app_derives_the_stage_one_stress():
    inp = _inp()
    sector_app._apply_bonded_prestrain(inp)
    assert inp["material_error"] is None
    assert inp["tendon_stage_one_stress"] == [
        pytest.approx(_hand_a()["locked"] * 1000.0, rel=1.0e-9)
    ]


def _failing(*, cracked_only=None, error):
    original = elastic.bonded_prestress_stress

    def fake(*args, **kwargs):
        if cracked_only is None or kwargs.get("cracked", True) is cracked_only:
            raise error
        return original(*args, **kwargs)

    return fake


def test_block_message_names_the_tendon_its_stress_and_the_concrete_strain(
    monkeypatch,
):
    # Reference concrete stress -5000 kN/m2 at nl = 18: Ec = 200000/18 MPa, so
    # eps_c = -5.0 x 18/200000 = -0.450 per mille. Ep IS = 110.7 MPa.
    error = BondedPrestressError(
        "the bonded prestress state did not converge",
        element=0, effective_stress=110.7e3, concrete_stress=-5000.0,
    )
    monkeypatch.setattr(
        elastic, "bonded_prestress_stress",
        _failing(cracked_only=None, error=error),
    )
    inp = _inp()
    inp["conc_Ec"] = 200.0 / 18.0
    inp["tendon_elements"] = [{"id": "P7"}]
    sector_app._apply_bonded_prestrain(inp)
    message = inp["material_error"]
    assert message.code == "PRESTRESS-BOND-STATE"
    assert message.text == (
        "Sector cannot find the bond strain difference of tendon P7. The "
        "effective stress Ep IS is 110.7 MPa. Under prestress alone, the "
        "concrete strain at the tendon is -0.450 " + chr(0x2030)
        + " (tension positive, cracked section at Es/Ecm). Check the "
        "prestrain IS and the tendon positions"
    )
    assert len(message.text.split()) <= 50
    inp = _inp()
    inp["conc_Ec"] = 200.0 / 18.0
    sector_app._apply_bonded_prestrain(inp)
    assert "tendon 1." in inp["material_error"].text
    # A failed Stage I state names its model; its ratio is nl = 18.
    monkeypatch.undo()
    monkeypatch.setattr(
        elastic, "bonded_prestress_stress",
        _failing(cracked_only=False, error=error),
    )
    inp = _inp()
    sector_app._apply_bonded_prestrain(inp)
    assert "is -0.450 " + chr(0x2030) + " (tension positive, uncracked section at nl)." in (
        inp["material_error"].text
    )


def test_an_error_without_a_tendon_keeps_the_general_message(monkeypatch):
    monkeypatch.setattr(
        elastic, "bonded_prestress_stress",
        _failing(cracked_only=False, error=BondedPrestressError("singular")),
    )
    inp = _inp()
    sector_app._apply_bonded_prestrain(inp)
    assert inp["material_error"] is sector_app._PRESTRESS_BOND_BLOCKER
    inp = _inp(mode="Plastic")
    sector_app._apply_bonded_prestrain(inp)
    assert inp["material_error"] is None
    assert "tendon_stage_one_stress" not in inp
    assert "tendon_bond_elastic_unavailable" not in inp
    # An element index outside the tendons also keeps the general message.
    monkeypatch.setattr(
        elastic, "bonded_prestress_stress",
        _failing(cracked_only=None, error=BondedPrestressError(
            "x", element=5, effective_stress=1.0, concrete_stress=1.0)),
    )
    inp = _inp()
    sector_app._apply_bonded_prestrain(inp)
    assert inp["material_error"] is sector_app._PRESTRESS_BOND_BLOCKER


@pytest.fixture
def stage_one_app(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest

    from app import reinforcement_table
    from app_case_inputs import CALCULATION_RUN_TIMEOUT, apply_widget_changes
    from app_workflow_navigation import goto_page

    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path / "autosave"))
    at = AppTest.from_file(str(ROOT / "app" / "sector_app.py"), default_timeout=120).run()
    apply_widget_changes(at, [("radio", "mode", "Elastic"),
                              ("number_input", "pre_IS", 5.0)])
    apply_widget_changes(at, [
        ("number_input", key, 0.0)
        for key in ("el_long_P", "el_long_Mx", "el_long_My",
                    "el_short_P", "el_short_Mx", "el_short_My")
    ])
    goto_page(at, "Inputs")
    version = at.session_state["ed_tendons_ver"] if "ed_tendons_ver" in at.session_state else 0
    at.session_state["tendons_base"] = reinforcement_table.table_from_points(
        [(0.0, -200.0, 600.0)], "tendon"
    )
    at.session_state["ed_tendons_ver"] = version + 1
    if "ed_tendons" in at.session_state:
        del at.session_state["ed_tendons"]
    at.run()
    goto_page(at, "Analysis")
    at.button(key="calculate").click()
    at.run(timeout=CALCULATION_RUN_TIMEOUT)
    assert not at.exception
    return (copy.deepcopy(at.session_state["result_input_snapshot"]),
            copy.deepcopy(at.session_state["results"]))


def _free_section_stress(inp):
    """Stage I concrete stress (MPa) at the corners under prestress alone.

    Independent hand calculation on the rectangle: concrete, bars (nl - 1) As
    and tendons -Ap (no tendon stiffness, displaced concrete), loaded by the
    tendon forces Ap Ep IS. Sums of first and second moments give the 3 x 3
    equilibrium of the plane a + kx x + ky y (tension positive).
    """
    xs = [point[0] for point in inp["outer"]]
    ys = [point[1] for point in inp["outer"]]
    assert len(inp["outer"]) == 4 and not inp["holes"]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    b, h = x1 - x0, y1 - y0
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    area = b * h
    sx, sy = area * cx, area * cy
    sxx = b * h ** 3 / 12.0 + area * cy * cy      # sum y^2 dA
    syy = h * b ** 3 / 12.0 + area * cx * cx      # sum x^2 dA
    sxy = area * cx * cy
    nl = float(inp["nl"])
    points = [(x, y, a * 1.0e-6 * (law.Es / ES * nl - 1.0), 0.0)
              for (x, y, a), law in zip(inp["bars"], inp["bar_materials"])]
    points += [(x, y, -a * 1.0e-6, a * 1.0e-6 * law.Es * strain * 1000.0)
               for (x, y, a), law, strain in zip(
                   inp["tendons"], inp["tendon_materials"],
                   inp["tendon_effective_prestrain"])]
    matrix = np.asarray([[area, sx, sy], [sy, sxy, sxx], [sx, syy, sxy]])
    target = np.zeros(3)
    for x, y, weight, force in points:
        matrix += weight * np.asarray([[1.0, x, y], [y, x * y, y * y], [x, x * x, x * y]])
        target -= force * np.asarray([1.0, y, x])
    plane = np.linalg.solve(matrix, target)
    return [(plane[0] + plane[1] * x + plane[2] * y) / 1000.0 for x, y in inp["outer"]]


@pytest.mark.slow
def test_plastic_only_report_has_no_stage_one_reference(monkeypatch, tmp_path):
    # Review E1-R2-T01: a Plastic-only report has no cracking threshold and no
    # Stage I values, so the bond paragraph must not refer to them.
    import io

    import pypdf
    from streamlit.testing.v1 import AppTest

    import sector_report
    from app import reinforcement_table
    from app_case_inputs import CALCULATION_RUN_TIMEOUT, apply_widget_changes
    from app_workflow_navigation import goto_page

    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path / "autosave"))
    at = AppTest.from_file(str(ROOT / "app" / "sector_app.py"), default_timeout=120).run()
    apply_widget_changes(at, [("radio", "mode", "Plastic"),
                              ("number_input", "pre_IS", 5.0)])
    goto_page(at, "Inputs")
    version = at.session_state["ed_tendons_ver"] if "ed_tendons_ver" in at.session_state else 0
    at.session_state["tendons_base"] = reinforcement_table.table_from_points(
        [(0.0, -270.0, 600.0)], "tendon"
    )
    at.session_state["ed_tendons_ver"] = version + 1
    if "ed_tendons" in at.session_state:
        del at.session_state["ed_tendons"]
    at.run()
    goto_page(at, "Analysis")
    at.button(key="calculate").click()
    at.run(timeout=CALCULATION_RUN_TIMEOUT)
    assert not at.exception
    inp = copy.deepcopy(at.session_state["result_input_snapshot"])
    out = copy.deepcopy(at.session_state["results"])
    assert inp["mode"] == "Plastic"
    pdf = sector_report.build_report(
        {"proj_no": "P", "proj_name": "N", "section": "S", "author": "A"},
        inp, out, version="test", figures=False, profile="Standard",
    )
    text = " ".join(
        " ".join((page.extract_text() or "").split())
        for page in pypdf.PdfReader(io.BytesIO(pdf)).pages
    )
    assert "bond strain difference" in text
    assert "The Stage I cracking check" not in text
    assert "The cracking threshold gives" not in text
    assert "Stage I locked-in tendon stress" not in text


@pytest.mark.slow
def test_app_stage_one_tension_is_the_hand_value_under_prestress_alone(stage_one_app):
    inp, out = stage_one_app
    corners = _free_section_stress(inp)
    assert max(corners) > 0.0
    assert out["elastic"]["sigma_ct"] == pytest.approx(max(corners), rel=1.0e-9)
