"""Published concrete fatigue damage is the upper bound of the section search.

Decision of 2026-11-03 (0.97.0 part 2): every published concrete fatigue damage
value is the upper bound of the bounded section search, labelled as such. The
largest sampled damage and its location stay in the Audit detail with their own
label. The publication check recomputes the published values and rejects a
result that publishes the largest sampled damage as the damage.

Hand case (test_hand_case_*): rectangle b x h = 0.30 x 0.60 m without bars,
A = 0.18 m2, I = 0.30 x 0.60^3/12 = 0.0054 m4. Each bin has the sustained
compression P = 1620 kN, sigma_long = 1620/0.18 = 9.0 MPa on the full section.
The additional moment Mx gives sigma_total(y) = 9.0 + Mx y/I:

- H1: Mx = 108 kNm, n = 1e6, Delta = 108 x 0.30/0.0054 = 6.0 MPa at y = +h/2;
- H2: Mx = 54 kNm, n = 1e7, Delta = 3.0 MPa at y = +h/2.

The section stays in compression (smallest stress 3.0 MPa). DS/EN 1992-1-1:2023
with fck = 40 MPa, gamma_c = 1.5, beta_cc = 1: eta_cc = min((40/40)^(1/3), 1)
= 1, eta_cc,fat = min(0.85, 0.8) = 0.8, fcd,fat = 40 x 0.8/1.5 = 21.333 MPa.
log10 N = 14 (1 - Ecd,max)/sqrt(1 - sigma_min/sigma_max) and D = sum n/N.
On the top edge (y = +0.30 m):

- H1: sigma 9/15, Ecd,max = 0.703125, R = 0.6, log10 N = 14 x 0.296875/0.632456
  = 6.5717, N = 3.729e6, D1 = 0.26816;
- H2: sigma 9/12, Ecd,max = 0.5625, R = 0.75, log10 N = 14 x 0.4375/0.5 = 12.25,
  D2 = 1e7/10^12.25 = 5.6e-6.

D = 0.268164 on the top edge. Both Ecd,max and 1/sqrt(1 - R) increase with y,
so the top edge carries the field maximum.
"""

from __future__ import annotations

import copy
import dataclasses
import io
import math
import pathlib
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import fatigue_analysis
import fatigue_presentation
import reproducible_example
import result_presentation as presentation
import sector_report
from sector import fatigue as F
from sector.section import Section
from tools import report_render_fixture

_TOLERANCE_ABS = 1.0e-4
_TOLERANCE_REL = 1.0e-3
_FCD_FAT = 40.0 * 0.8 / 1.5
_BINS = ((6.0, 1.0e6), (3.0, 1.0e7))  # (stress increment at y = +h/2, cycles)


def _hand_damage(y_m):
    """Independent Miner sum at height y of the hand case (module docstring)."""

    total = 0.0
    for delta_top, cycles in _BINS:
        increment = delta_top * y_m / 0.30
        sigma_min = 9.0 + min(0.0, increment)
        sigma_max = 9.0 + max(0.0, increment)
        if sigma_min == sigma_max:
            continue  # constant compression: infinite life, no damage
        ratio = sigma_min / sigma_max
        log10_life = (
            14.0 * (1.0 - sigma_max / _FCD_FAT) / math.sqrt(1.0 - ratio)
        )
        total += cycles / 10.0 ** log10_life
    return total


def _hand_spectrum():
    section = Section.from_polygon(
        corners=[(-0.15, -0.30), (0.15, -0.30), (0.15, 0.30), (-0.15, 0.30)],
    )
    bins = (
        F.SpectrumBin("H1", 1.0e6, p_long_kn=1620.0, mx_short_knm=108.0),
        F.SpectrumBin("H2", 1.0e7, p_long_kn=1620.0, mx_short_knm=54.0),
    )
    return F.analyse_fatigue_spectrum(
        "Hand", section, bins, nl=15.0, ns=6.0,
        check_reinforcement=False,
        concrete=F.ConcreteFatigueProperties(
            edition="2023", fck_mpa=40.0, gamma_c=1.5, beta_cc_t0=1.0,
        ),
    )


def test_hand_case_publishes_the_search_upper_bound_not_below_the_dense_grid_maximum():
    spectrum = _hand_spectrum()
    search = spectrum.concrete_search
    hand_top = _hand_damage(0.30)
    assert hand_top == pytest.approx(0.268164228, rel=1.0e-8)
    assert spectrum.fcd_fat_mpa == pytest.approx(_FCD_FAT, rel=1.0e-12)
    top_fibres = [item for item in spectrum.concrete if item.y_m == 0.30]
    assert len(top_fibres) == 2
    for fibre in top_fibres:
        assert fibre.damage == pytest.approx(hand_top, rel=1.0e-12)

    # Independent dense grid of the hand formula over the section depth. The
    # hand stresses do not change with x, so one column of points is complete.
    grid_max = max(
        _hand_damage(float(y)) for y in np.linspace(-0.30, 0.30, 241)
    )
    assert grid_max == pytest.approx(hand_top, rel=1.0e-14)

    published = fatigue_presentation.concrete_damage_upper_bound(spectrum)
    assert search.converged is True
    assert published == search.upper_damage
    assert published >= grid_max * (1.0 - 1.0e-12)
    assert published <= hand_top + _TOLERANCE_ABS + _TOLERANCE_REL * hand_top
    assert spectrum.miner_damage == published
    assert fatigue_presentation.damage_publication_issue(spectrum) is None

    payload = {"spectra": (spectrum,), "converged": True, "passed": True,
               "miner_damage": spectrum.miner_damage,
               "utilisation": spectrum.utilisation}
    row = fatigue_presentation.spectrum_rows(payload)[0]
    assert row["concrete_damage_upper_bound"] == published
    assert row["miner_damage"] == published
    assert row["miner_damage_concrete_bound"] is True
    assert "(concrete, upper bound)" in fatigue_presentation.criterion_breakdown(
        payload
    )


def _fixture_payload():
    return fatigue_analysis.run_analysis(report_render_fixture._inputs())


def test_report_fixture_upper_bound_is_not_below_the_field_maximum():
    # Triage case of 0.97.0 part 2: far from the limit the largest sampled
    # damage (section vertex) is much lower than the field maximum.
    inp = report_render_fixture._inputs()
    prepared = fatigue_analysis.prepare(inp)
    payload = fatigue_analysis.run_analysis(inp)
    spectrum = fatigue_presentation.items(payload, "spectra")[0]
    search = spectrum.concrete_search
    data = F._concrete_search_data(
        spectrum.bins, prepared.concrete, prepared.gamma_ff
    )
    grid_x, grid_y = np.meshgrid(
        np.linspace(-0.10, 0.10, 201), np.linspace(-0.15, 0.15, 301)
    )
    points = np.column_stack((grid_x.ravel(), grid_y.ravel()))
    grid_max = float(np.max(F._search_damage_field(points, data)))

    published = fatigue_presentation.concrete_damage_upper_bound(spectrum)
    assert published == search.upper_damage
    assert published >= grid_max
    assert grid_max > 50.0 * search.damage
    assert published - search.damage <= (
        _TOLERANCE_ABS + _TOLERANCE_REL * search.damage
    )
    row = fatigue_presentation.spectrum_rows(payload)[0]
    assert row["concrete_damage_upper_bound"] == published
    # R1 governs the maximum Miner damage; it is not a concrete bound.
    assert row["miner_damage"] == max(
        item.damage for item in spectrum.reinforcement
    )
    assert row["miner_damage_concrete_bound"] is False


def _report_tables(profile):
    inp = report_render_fixture._inputs()
    out = report_render_fixture._results(inp)
    out["worked_example_selection"] = presentation.worked_example_selection(
        inp, out
    )
    builder = sector_report.ReportBuilder(
        io.BytesIO(), {}, inp, out, figures=False, profile=profile
    )
    tables = []
    notes = []
    builder._case_heading = lambda *_args, **_kwargs: None
    builder._h1 = lambda *_args, **_kwargs: None
    builder._h2 = lambda *_args, **_kwargs: None
    builder._table = (
        lambda rows, *_args, **_kwargs: tables.append(copy.deepcopy(rows))
    )
    builder._formula = lambda *_args, **_kwargs: None
    builder._fig = lambda *_args, **_kwargs: None
    builder._status_block = lambda *_args, **_kwargs: None
    builder._small = notes.append
    builder._p = lambda *_args, **_kwargs: None
    builder._keep_from = lambda *_args, **_kwargs: None
    builder._keep_measured_calculation_from = lambda *_args, **_kwargs: None
    builder._fatigue()
    return builder._base_out["fatigue"], tables, notes


@pytest.mark.parametrize("profile", ["Standard", "Audit"])
def test_report_publishes_the_upper_bound_and_keeps_the_sampled_value_in_audit(
    profile,
):
    payload, tables, notes = _report_tables(profile)
    spectrum = fatigue_presentation.items(payload, "spectra")[0]
    upper = spectrum.concrete_search.upper_damage
    sampled = spectrum.concrete_search.damage

    summary = next(rows for rows in tables if rows[0][0] == "Spectrum"
                   and "Concrete D, upper bound" in rows[0])
    column = summary[0].index("Concrete D, upper bound")
    assert summary[1][column] == sector_report._fmt_sig(upper, 6)

    search = next(rows for rows in tables if "D, upper bound" in rows[0])
    assert search[1][search[0].index("D, upper bound")] == (
        sector_report._fmt_sig(upper, 6)
    )
    fibres = next(rows for rows in tables if rows[0][:4] == [
        "Fiber", "Source", "x", "y",
    ])
    if profile == "Audit":
        assert search[1][search[0].index("Largest sampled D")] == (
            sector_report._fmt_sig(sampled, 6)
        )
        assert search[0][1:3] == ["x", "y"]
        assert "D at point" in fibres[0]
    else:
        assert "Largest sampled D" not in search[0]
        assert "x" not in search[0]
        assert "D at point" not in fibres[0]
        assert "Miner D" not in fibres[0]
    assert any(
        fatigue_presentation.CONCRETE_UPPER_BOUND_NOTE in str(note)
        for note in notes
    )


def _concrete_governing_spectrum():
    # The fixture spectrum without reinforcement: the concrete damage alone
    # gives the maximum Miner damage.
    spectrum = fatigue_presentation.items(_fixture_payload(), "spectra")[0]
    return dataclasses.replace(
        spectrum,
        reinforcement=(),
        miner_damage=spectrum.concrete_search.upper_damage,
    )


def test_publication_check_accepts_the_upper_bound_as_the_concrete_damage():
    spectrum = _concrete_governing_spectrum()
    payload = {"spectra": (spectrum,), "converged": True, "passed": True,
               "miner_damage": spectrum.miner_damage}

    assert fatigue_presentation.damage_publication_issue(spectrum) is None
    assert fatigue_presentation.damage_publication_issue(payload) is None
    assert fatigue_presentation.result_status(spectrum) == "PASS"
    row = fatigue_presentation.spectrum_rows(payload)[0]
    assert row["miner_damage"] == spectrum.concrete_search.upper_damage
    assert row["miner_damage_concrete_bound"] is True


def test_publication_check_rejects_the_sampled_value_as_the_concrete_damage():
    valid = _concrete_governing_spectrum()
    search = valid.concrete_search
    assert search.upper_damage > search.damage

    # 1. The maximum Miner damage publishes the largest sampled damage.
    sampled_miner = dataclasses.replace(valid, miner_damage=search.damage)
    # 2. The search publishes the largest sampled damage as its upper bound.
    sampled_bound = dataclasses.replace(
        valid,
        concrete_search=dataclasses.replace(
            search, upper_damage=search.damage
        ),
        miner_damage=search.damage,
    )
    # 3. A fixed fibre damage is above the published upper bound.
    fibre = valid.concrete[0]
    above_bound = dataclasses.replace(
        valid,
        concrete=(
            dataclasses.replace(fibre, damage=2.0 * search.upper_damage),
            *valid.concrete[1:],
        ),
    )
    for spectrum in (sampled_miner, sampled_bound, above_bound):
        assert fatigue_presentation.damage_publication_issue(spectrum)
        assert fatigue_presentation.result_status(spectrum) == "INVALID"
        payload = {"spectra": (spectrum,), "converged": True, "passed": True,
                   "miner_damage": spectrum.miner_damage, "warnings": (),
                   "governing_spectrum": spectrum.spectrum_name,
                   "utilisation": spectrum.utilisation}
        assert fatigue_presentation.overall_status(payload) == "INVALID"
        row = fatigue_presentation.spectrum_rows(payload)[0]
        assert row["miner_damage"] is None
        assert row["concrete_damage_upper_bound"] is None
        assert "max Miner D" not in fatigue_presentation.criterion_breakdown(
            spectrum
        )
        summary = presentation.fatigue_summary_rows(
            {"fatigue_on": True}, {"fatigue": payload}
        )[0]
        assert summary["status"] == "INVALID"
        assert valid.spectrum_name + ": " in summary["note"]

    # 4. The payload maximum publishes the largest sampled damage.
    payload = {"spectra": (valid,), "converged": True, "passed": True,
               "miner_damage": search.damage, "warnings": ()}
    assert fatigue_presentation.damage_publication_issue(payload)
    assert fatigue_presentation.overall_status(payload) == "INVALID"


def test_checking_pack_states_the_upper_bound_interval_from_the_hand_values():
    flat = " ".join(reproducible_example.checking_pack().split())
    top_fibre = 5.358432445e-12
    assert "producing Miner damage 5.358432445e-12 at that fibre" in flat
    assert (
        "The published concrete damage is the upper bound D,upper of the "
        "adaptive section search."
    ) in flat
    assert "5.358432445e-12 <= D,upper <= 1.000000054e-4" in flat
    limit = top_fibre + _TOLERANCE_ABS + _TOLERANCE_REL * top_fibre
    assert limit <= 1.000000054e-4
    assert 1.000000054e-4 - limit < 1.0e-13
