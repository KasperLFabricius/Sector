"""R2-20: the tendon stress in the crack-width formula is a stress range.

Standard text (read in the source PDF, DS/EN 1992-1-1 + AC:2008, PDF page 250,
printed page 124):

- 7.3.4(1), eps_sm: "Only the additional tensile strain beyond the state of
  zero strain of the concrete at the same level is considered".
- 7.3.4(2), Expression (7.9): sigma_s is the stress in the tension
  reinforcement assuming a cracked section. For pretensioned members, sigma_s
  may be replaced by Delta sigma_p, the stress variation in prestressing
  tendons from the state of zero strain of the concrete at the same level.
- DS/EN 1992-1-1:2023 9.2.3(3), Formula (9.11) (PDF page 170): the same
  replacement for members with bonded tendons.

The DK NA:2024 has no provision on 7.3.4(2). Sector uses the replacement for
all bonded tendons: at zero concrete strain at the tendon, the tendon strain is
the bond strain difference eps_p(0), so Delta sigma_p = sigma_p - Ep eps_p(0).

Hand calculation (independent of Sector output), legacy area model (no
displaced concrete): 400 x 600 mm, one tendon Ap = 1000 mm2 at d = 540 mm
(y = -240 mm), Ep = 195 GPa, Ep IS = 1000 MPa, nl = 18 (Ec = 200000/18 =
11111.1 MPa, n_p = 17.55), external sagging moment 600 kNm.

Prestress alone, no-tension concrete: the tendon force P = 1000 kN acts 60 mm
above the soffit, outside the kern, so the triangular stress block has
x = 3 x 60 = 180 mm and sigma_max = 2P/(b x) = 27.7778 MPa. At the tendon
sigma_c = -27.7778 (1 - 60/180) = -18.5185 MPa, and the locked-in stress is
sigma_0 = Ep eps_p(0) = 1000 + 17.55 x 18.5185 = 1325.000 MPa.

Under 600 kNm the section cracks from the soffit. With the neutral-axis depth
x from the top: C = M/(d - x/3), curvature kappa = 2C/(b Ec x^2), and C = T =
Ap (sigma_0 + Ep kappa (d - x)). Bisection gives x = 385.4761 mm,
kappa = 4.41561e-6 1/mm, so Delta sigma_p = Ep kappa (d - x) = 133.0519 MPa and
the tendon stress is 1458.0519 MPa.
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "app"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from sector.elastic import (  # noqa: E402
    bonded_prestress_stress,
    solve_elastic,
    solve_elastic_combined,
)
from sector.section import Section  # noqa: E402
from sector.serviceability import evaluate_crack_width  # noqa: E402

EP = 195_000.0
ES = 200_000.0
NL = 18.0


def _hand():
    b, ap, d, moment = 400.0, 1000.0, 540.0, 600.0e6
    ec = ES / NL
    n_p = NL * EP / ES
    force = ap * 1000.0
    block = 3.0 * 60.0
    peak = 2.0 * force / (b * block)
    locked = 1000.0 + n_p * peak * (1.0 - 60.0 / block)

    def balance(x):
        compression = moment / (d - x / 3.0)
        kappa = 2.0 * compression / (b * ec * x * x)
        return compression - ap * (locked + EP * kappa * (d - x)), kappa

    low, high = 1.0, d - 1.0
    for _ in range(200):
        middle = 0.5 * (low + high)
        if balance(low)[0] * balance(middle)[0] <= 0.0:
            high = middle
        else:
            low = middle
    x = 0.5 * (low + high)
    kappa = balance(x)[1]
    return dict(locked=locked, x=x, kappa=kappa, range=EP * kappa * (d - x))


def _section():
    return Section.from_polygon(
        corners=[(-0.2, -0.3), (0.2, -0.3), (0.2, 0.3), (-0.2, 0.3)],
        bars_xy_area_mm2=[(0.0, -0.24, 1000.0)],
    )


N_MULT = np.asarray([EP / ES])


def _locked():
    return bonded_prestress_stress(
        _section(), NL, np.asarray([1000.0e3]), n_mult=N_MULT,
        displace_concrete=False,
    )


def test_hand_values():
    hand = _hand()
    assert hand["locked"] == pytest.approx(1325.000, abs=1.0e-3)
    assert hand["x"] == pytest.approx(385.4761, abs=1.0e-4)
    assert hand["kappa"] == pytest.approx(4.41561e-6, rel=1.0e-5)
    assert hand["range"] == pytest.approx(133.0519, abs=1.0e-4)


def test_locked_in_stress_is_ep_times_the_bond_strain_difference():
    assert _locked()[0] / 1000.0 == pytest.approx(_hand()["locked"], rel=1.0e-9)


@pytest.mark.parametrize("edition", ["2004", "2023"])
def test_tendon_sigma_s_is_the_stress_range_from_zero_concrete_strain(edition):
    hand = _hand()
    locked = _locked()
    state = solve_elastic(
        _section(), 0.0, 600.0, 0.0, NL, n_mult=N_MULT,
        prestress_stress=locked, displace_concrete=False,
    )
    # The concrete strain at the tendon level gives Delta sigma_p = Ep eps_c.
    eps_c = (state.eps0 + state.ky * -0.24) / (ES / NL * 1000.0)
    assert EP * eps_c == pytest.approx(hand["range"], rel=1.0e-8)
    assert (locked[0] + state.bar_stress[0]) / 1000.0 == pytest.approx(
        hand["locked"] + hand["range"], rel=1.0e-9
    )
    evaluation = evaluate_crack_width(
        _section(), state, NL, fctm=3.0, Es=[EP], kt=0.4, n_mult=N_MULT,
        cover=[50.0], bar_diameter=[12.5], k1=[1.6], edition=edition,
        reinforcement_types=["prestress"], bond_ratio_xi=[0.5],
    )
    assert evaluation.status == "CALCULATED"
    candidate = evaluation.result.candidates[0]
    assert candidate.reinforcement_type == "prestress"
    assert candidate.sigma_s == pytest.approx(hand["range"], rel=1.0e-8)
    lower = (0.6 if edition == "2004" else 1.0 - 0.4) * hand["range"] / EP
    assert candidate.mean_strain_operands.lower_bound_candidate == pytest.approx(
        lower, rel=1.0e-8
    )


def test_short_term_route_removes_the_locked_in_stress():
    # The app subtracts sigma_p(0) = Ep eps_p(0) from the total tendon stress of
    # the combined solve. With no short-term part the result is Delta sigma_p.
    locked = _locked()
    state = solve_elastic_combined(
        _section(), 0.0, 600.0, 0.0, NL, 0.0, 0.0, 0.0, NL, n_mult=N_MULT,
        prestress_stress=locked, displace_concrete=False,
    )
    assert (state.bar_stress_total[0] - locked[0]) / 1000.0 == pytest.approx(
        _hand()["range"], rel=1.0e-8
    )


# Report and manual text: the clause reference where the stress range is described.

import manual  # noqa: E402
import sector_report as report  # noqa: E402


def _crack_table_notes(tendons, edition):
    builder = object.__new__(report.ReportBuilder)
    builder.inp = {"tendons": [(0.0, -0.24, 1000.0)] if tendons else []}
    builder.out = {"elastic": {"crack_edition": edition}}
    notes = []
    builder._h2 = lambda *a, **k: None
    builder._table = lambda *a, **k: None
    builder._small = notes.append
    row = {"wk": 0.1, "sr_max": 200.0, "esm_ecm": 4.0e-4, "sigma_s": 133.05,
           "rho_p_eff": 0.02, "hc_ef": 0.07, "ac_eff": 0.03, "cover": 50.0,
           "phi": 12.5, "element_id": "T1"}
    builder._crack_table(row, row)
    return notes


def test_report_states_the_clause_of_the_tendon_stress_range():
    notes = _crack_table_notes(True, "2004")
    assert len(notes) == 1
    text = notes[0]
    assert "&#916;sigma<sub>p</sub> = sigma<sub>p</sub> - E<sub>p</sub>" in text
    assert "Delta" not in text
    assert "zero concrete strain at the tendon level" in text
    assert "DS/EN 1992-1-1 &#167;7.3.4(2)" in text
    assert "Clause 7.3.4(2) gives this for pretensioned members" in text
    assert "bonded post-tensioned tendons" in text
    modern = _crack_table_notes(True, "2023")[0]
    assert "DS/EN 1992-1-1:2023 &#167;9.2.3(3)" in modern
    assert "7.3.4" not in modern
    assert _crack_table_notes(False, "2004") == []


def test_manual_states_the_clause_of_the_tendon_stress_range():
    text = next(
        block[1] for block in manual.manual_blocks()
        if block[0] == "md" and "**Tendons.**" in block[1]
    )
    for expected in (
        r"$\Delta\sigma_p=\sigma_p-E_p\varepsilon^{(0)}_{p}$",
        "zero concrete strain at the tendon level (7.3.4(2))",
        "Clause 7.3.4(2) gives this for pretensioned members",
        "bonded post-tensioned tendons",
        "(9.2.3(3))",
    ):
        assert expected in text
