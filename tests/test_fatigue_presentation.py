"""Shared fatigue-presentation contract tests."""

from __future__ import annotations

import pathlib
from types import SimpleNamespace as NS
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import fatigue_presentation as presentation  # noqa: E402


def _reinforcement(element_id="R1", utilisation=0.60):
    bin_result = NS(
        bin_name="FAT-1",
        cycles=2.0e5,
        converged=True,
        stress_long_mpa=120.0,
        stress_total_mpa=180.0,
        stress_total_design_mpa=186.0,
        stress_total_elastic_mpa=178.0,
        stress_range_mpa=60.0,
        stress_range_elastic_mpa=58.0,
        bond_adjustment=1.0,
        bond_method="Perfect bond",
        design_stress_range_mpa=66.0,
        delta_sigma_rsk_mpa=130.0,
        delta_sigma_rd_mpa=98.5,
        sn_exponent=5.0,
        cycles_to_failure=3.2e6,
        log10_cycles_to_failure=6.505,
        damage=0.0625,
        governing_stress_mpa=186.0,
        yield_limit_mpa=416.7,
        yield_utilisation=0.446,
    )
    return NS(
        element_id=element_id,
        kind="mild",
        detail_id="F1",
        diameter_mm=20.0,
        bins=(bin_result,),
        damage=utilisation,
        damage_utilisation=utilisation,
        governing_damage_bin="FAT-1",
        yield_utilisation=0.446,
        governing_yield_bin="FAT-1",
        utilisation=utilisation,
        converged=True,
        passed=utilisation <= 1.0,
    )


def _concrete(utilisation=0.35):
    bin_result = NS(
        bin_name="FAT-1",
        cycles=2.0e5,
        converged=True,
        compression_long_mpa=5.0,
        compression_total_mpa=9.0,
        compression_min_design_mpa=5.0,
        compression_max_design_mpa=9.4,
        stress_ratio=0.53,
        e_cd_min=0.20,
        e_cd_max=0.38,
        cycles_to_failure=2.0e7,
        log10_cycles_to_failure=7.301,
        damage=0.01,
        stress_utilisation=0.38,
    )
    return NS(
        fibre_index=4,
        x_m=0.2,
        y_m=-0.3,
        bins=(bin_result,),
        fcd_fat_mpa=24.7,
        damage=0.01,
        damage_utilisation=0.01,
        governing_damage_bin="FAT-1",
        stress_utilisation=utilisation,
        governing_stress_bin="FAT-1",
        utilisation=utilisation,
        converged=True,
        passed=utilisation <= 1.0,
    )


def _spectrum(*, utilisation=0.60, converged=True, passed=True):
    reinforcement = _reinforcement(utilisation=utilisation)
    concrete = _concrete()
    state = NS(
        name="FAT-1",
        description="Heavy vehicle",
        cycles=2.0e5,
        converged=True,
        bond_method="Perfect bond",
        design_action_factor=1.1,
    )
    search = NS(
        x_m=0.2,
        y_m=-0.3,
        damage=0.01,
        upper_damage=0.011,
        divisions=96,
        boxes_evaluated=100,
        points_evaluated=500,
        absolute_gap=0.001,
        relative_gap=0.1,
        converged=True,
    )
    return NS(
        spectrum_name="Traffic A",
        bins=(state,),
        reinforcement=(reinforcement,),
        concrete=(concrete,),
        concrete_search=search,
        governing_reinforcement_id="R1",
        governing_concrete_fibre=4,
        utilisation=utilisation,
        converged=converged,
        passed=passed,
    )


def _payload(**overrides):
    spectrum = overrides.pop("spectrum", _spectrum())
    value = {
        "spectra": (spectrum,),
        "warnings": (),
        "converged": spectrum.converged,
        "passed": spectrum.passed,
        "utilisation": spectrum.utilisation,
        "reinforcement_properties": (
            NS(element_id="R1", n_star=2.0e6),
        ),
    }
    value.update(overrides)
    return value


@pytest.mark.parametrize(
    ("payload", "stale", "expected"),
    [
        (None, False, "NOT RUN"),
        (_payload(), False, "PASS"),
        (_payload(warnings=("Source missing",)), False, "REVIEW"),
        (_payload(spectrum=_spectrum(utilisation=1.2, passed=False)),
         False, "FAIL"),
        (_payload(spectrum=_spectrum(converged=False, passed=False)),
         False, "INVALID"),
        (_payload(), True, "STALE"),
    ],
)
def test_aggregate_status_is_conservative(payload, stale, expected):
    assert presentation.overall_status(payload, stale=stale) == expected


def test_summary_rows_retain_each_independent_spectrum_and_governing_criterion():
    payload = _payload()

    rows = presentation.spectrum_rows(payload)

    assert rows == [{
        "spectrum": "Traffic A",
        "status": "PASS",
        "bins": 1,
        "reinforcement_elements": 1,
        "concrete_fibres": 1,
        "governing": "R1 - Miner damage",
        "utilisation": 0.60,
        "search_converged": True,
        "search_upper_damage": 0.011,
    }]


def test_reinforcement_rows_expose_miner_yield_and_full_bin_evidence():
    spectrum = _spectrum()
    element = spectrum.reinforcement[0]

    row = presentation.reinforcement_rows(spectrum)[0]
    bins = presentation.reinforcement_bin_rows(element)

    assert row["governing"] == "Miner damage"
    assert row["damage"] == pytest.approx(0.60)
    assert row["yield_utilisation"] == pytest.approx(0.446)
    assert bins[0]["stress_total_elastic_mpa"] == pytest.approx(178.0)
    assert bins[0]["bond_adjustment"] == pytest.approx(1.0)
    assert bins[0]["design_stress_range_mpa"] == pytest.approx(66.0)
    assert bins[0]["cycles_to_failure"] == pytest.approx(3.2e6)
    assert bins[0]["damage"] == pytest.approx(0.0625)
    assert bins[0]["bond_method"] == "Perfect bond"


def test_concrete_rows_identify_search_point_and_certification_evidence():
    spectrum = _spectrum()

    row = presentation.concrete_rows(spectrum)[0]
    bins = presentation.concrete_bin_rows(spectrum.concrete[0])

    assert row["source"] == "Adaptive search"
    assert (row["x_mm"], row["y_mm"]) == pytest.approx((200.0, -300.0))
    assert row["governing"] == "compressive stress"
    assert bins[0]["compression_max_design_mpa"] == pytest.approx(9.4)
    assert bins[0]["stress_ratio"] == pytest.approx(0.53)


def test_spectrum_bin_rows_join_component_evidence_without_recalculation():
    row = presentation.spectrum_bin_rows(_spectrum())[0]

    assert row["bin"] == "FAT-1"
    assert row["cycles"] == pytest.approx(2.0e5)
    assert row["gamma_ff"] == pytest.approx(1.1)
    assert row["max_design_stress_range_mpa"] == pytest.approx(66.0)
    assert row["max_concrete_compression_mpa"] == pytest.approx(9.4)


def test_stable_result_and_property_lookup():
    payload = _payload()
    spectrum = payload["spectra"][0]

    assert presentation.spectrum_by_name(payload, "Traffic A") is spectrum
    assert presentation.result_by_element(spectrum, "R1").element_id == "R1"
    assert presentation.result_by_fibre(spectrum, 4).fibre_index == 4
    assert presentation.reinforcement_property(payload, "R1").n_star == 2.0e6
